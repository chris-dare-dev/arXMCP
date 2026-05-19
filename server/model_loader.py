"""Shared model-loader guards for the BGE-M3 embedder and the
BGE-reranker-v2-m3 reranker (Threat 6 in
``.claude/notes/08-security-observability-ops.md``).

Three guards are exposed:

* :func:`validate_model_revision` — refuses any ``revision=`` argument
  to ``from_pretrained`` that is not a 40-character lowercase hex
  SHA. Closes the brief's AC1 / AC2 ("``load(revision='main')``
  raises ``ModelPinningError``"). Called BEFORE the network round
  trip so a misconfigured pin fails fast with a clear message.

* :func:`resolve_trust_remote_code` — reads ``ARXMCP_TRUST_REMOTE_CODE``
  and returns ``True`` only when the value is the literal ``"1"``.
  Any other value (including empty / unset) returns ``False``. When
  enabled, emits a ``WARNING`` log so the operator sees the override
  on every server start. Closes AC5.

* :func:`assert_no_bin_in_snapshot` — walks the HuggingFace cache
  snapshot for a loaded ``(model_id, revision)`` and raises
  ``ModelPinningError`` if any ``.bin`` file slipped through. Closes
  AC4's defensive half: ``use_safetensors=True`` silently falls back
  to ``.bin`` in some transformers versions when no safetensors file
  exists in the repo, so passing the kwarg alone is not sufficient.

The module deliberately has zero runtime dependencies on
``transformers`` / ``huggingface_hub`` — it operates purely on the
on-disk cache layout. This keeps the validator usable from unit
tests that mock the model load.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("arxmcp.security.model_loader")


class ModelPinningError(RuntimeError):
    """Raised when a model load attempt violates a Threat-6 guard.

    Inherits from ``RuntimeError`` (not ``ValueError``) because the
    failure represents a security policy violation, not a malformed
    Python value — a calling layer should NOT silently swallow it
    via ``except ValueError``.
    """


#: Canonical 40-character lowercase hex SHA. HuggingFace returns
#: SHAs in lowercase and the existing pinned constants
#: (``BGE_M3_COMMIT_SHA``, ``BGE_RERANKER_COMMIT_SHA``) are
#: lowercase, so accepting uppercase would create an asymmetric
#: validator and silently allow a typo'd pin to load.
_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")


def validate_model_revision(revision: str, *, model_name: str) -> None:
    """Refuse ``revision`` if it is not a 40-character lowercase hex SHA.

    The brief's mitigation is explicit:
    "Pin model commit SHAs in configuration (``BAAI/bge-m3@<sha>``),
    not just names."
    A branch name like ``main`` or a tag like ``v1.0`` resolves to a
    moving target — a compromised upload on the same branch would be
    loaded silently. This validator closes that gap.

    :param revision: the value about to be passed to
        ``from_pretrained(..., revision=...)``.
    :param model_name: the HuggingFace ``org/name`` identifier (e.g.
        ``"BAAI/bge-m3"``); included in the error message so the
        operator can find the bad pin without grepping.

    :raises ModelPinningError: if ``revision`` is not exactly 40
        characters of lowercase ``[0-9a-f]``.
    """
    if not isinstance(revision, str) or not _SHA_RE.fullmatch(revision):
        raise ModelPinningError(
            f"Model revision must be a 40-character lowercase hex SHA "
            f"(Threat 6, .claude/notes/08-security-observability-ops.md). "
            f"model={model_name!r} got={revision!r}. "
            f"Example: 5617a9f61b028005a4858fdac845db406aefb181 "
            f"(verify via: curl -s "
            f"https://huggingface.co/api/models/{model_name} | "
            f"python -c \"import sys,json;print(json.load(sys.stdin)['sha'])\")"
        )


#: Env-var name for the trust-remote-code escape hatch. Documented
#: in ``.claude/docs/security-threat-6-audit.md``. The implementation
#: refuses values other than the literal string ``"1"`` so the
#: operator must opt in explicitly (no fuzzy truthiness like
#: ``True`` / ``yes`` / ``on``).
_TRUST_REMOTE_CODE_ENV = "ARXMCP_TRUST_REMOTE_CODE"


def resolve_trust_remote_code() -> bool:
    """Return whether ``trust_remote_code=True`` is opted-in.

    Default: ``False`` (no env var set, or any value other than
    ``"1"``). When enabled, emits a ``logging.WARNING`` line so the
    deviation from the safe default is visible in the server log.

    The brief's AC reads:
    "``trust_remote_code=False`` is the default; enabling it requires
    ``ARXMCP_TRUST_REMOTE_CODE=1`` and logs a WARN."
    """
    raw = os.environ.get(_TRUST_REMOTE_CODE_ENV, "")
    if raw == "1":
        logger.warning(
            "%s=1: model loaders will pass trust_remote_code=True. "
            "This re-enables the modeling-script RCE vector from "
            "Threat 6 (.claude/notes/08-security-observability-ops.md). "
            "Production deployments must leave this unset.",
            _TRUST_REMOTE_CODE_ENV,
        )
        return True
    return False


def _huggingface_cache_root() -> Path:
    """Return the resolved HuggingFace hub cache root.

    Mirrors the precedence used elsewhere in the repo
    (``server.retrieval.rerank._huggingface_cache_snapshot_sha``):
    ``$HF_HOME`` if set, else ``~/.cache/huggingface``. The ``hub``
    subdirectory holds per-model snapshot trees.
    """
    base = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return Path(base) / "hub"


def assert_no_bin_in_snapshot(model_name: str, revision: str) -> None:
    """Raise ``ModelPinningError`` if the cached snapshot for
    ``(model_name, revision)`` contains any ``.bin`` weight file.

    ``transformers``' ``use_safetensors=True`` documents safetensors
    preference but, in some versions, silently falls back to ``.bin``
    when no safetensors file is present in the repo. Passing the
    kwarg alone is insufficient — this post-load check closes the
    gap by inspecting the on-disk cache layout directly.

    The HuggingFace cache layout is
    ``<HF_HOME>/hub/models--<org>--<name>/snapshots/<sha>/`` where
    the snapshot dir is the commit SHA and contains symlinks /
    files for the materialized weight set. We walk that directory
    (one level, no recursion — safetensors and bin weights live at
    the top level of a snapshot) and refuse if any ``.bin`` is
    present, even alongside a ``.safetensors`` (because we cannot
    prove which was used by the loaded model).

    :param model_name: the HF ``org/name`` identifier.
    :param revision: the 40-char SHA (already validated by
        :func:`validate_model_revision`).

    :raises ModelPinningError: if the snapshot directory exists and
        contains a ``*.bin`` file (excluding ``training_args.bin``,
        which is a sidecar produced by Trainer and does NOT carry
        model weights).
    """
    cache_root = _huggingface_cache_root()
    safe_name = "models--" + model_name.replace("/", "--")
    snapshot_dir = cache_root / safe_name / "snapshots" / revision
    if not snapshot_dir.is_dir():
        # Cache layout absent — either the model is loaded from a
        # different cache (CI artifact mount) or transformers is
        # running in offline mode against a pre-populated dir. In
        # either case, we cannot prove safety, but we also cannot
        # prove a violation; return silently and trust the load.
        logger.debug(
            "assert_no_bin_in_snapshot: no snapshot dir at %s — skipped",
            snapshot_dir,
        )
        return
    bin_files = [
        p
        for p in snapshot_dir.iterdir()
        if p.is_file() and p.suffix == ".bin" and p.name != "training_args.bin"
    ]
    if bin_files:
        names = ", ".join(sorted(p.name for p in bin_files))
        raise ModelPinningError(
            f"Snapshot for {model_name}@{revision} contains pickle "
            f"weight file(s): {names}. Threat 6 mandates safetensors-"
            f"only loads (.claude/notes/08-security-observability-ops.md). "
            f"Either bump the pinned revision to a commit that ships "
            f".safetensors weights, or remove the .bin file(s) from "
            f"{snapshot_dir} and re-fetch with use_safetensors=True."
        )


__all__ = [
    "ModelPinningError",
    "assert_no_bin_in_snapshot",
    "resolve_trust_remote_code",
    "validate_model_revision",
]
