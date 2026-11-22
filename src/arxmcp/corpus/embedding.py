"""The embedding model and where a paper's embeddings live on disk.

The model is BGE-M3, pinned at :data:`BGE_M3_COMMIT_SHA`
(:data:`EMBEDDER_VERSION` names those weights in every stored row).
:func:`get_embedding_model` and :func:`get_embedding_tokenizer` load it
lazily, so importing this module never imports torch or transformers;
ingest's batch embedding and the server's query encoding share the one
loaded copy in a process. The Threat 6 loader guards live in
:mod:`arxmcp.corpus.model_loader`.

Each embedded paper has a directory under :data:`EMBEDDINGS_DIR` holding
the vectors (:data:`EMBEDDINGS_NPZ_NAME`) and a JSON sidecar
(:data:`EMBEDDINGS_MANIFEST_NAME`) that records which chunks were embedded
under which embedder version and input policy. Ingest writes both; the
store reads them when it loads a paper into LanceDB.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from arxmcp.settings import ApplicationPaths

# Quiet two third-party log streams that dominate the model's cold-
# start + per-paper output without carrying actionable signal:
#
# - ``httpx`` emits an INFO line per HF-Hub GET/HEAD (model.safetensors
#   probe, tokenizer config, etc.). Repeats on every long-run process
#   restart. Real network failures are still surfaced at WARNING+.
# - ``transformers.tokenization_utils_base`` emits "Token indices
#   sequence length is longer than the specified maximum sequence
#   length" whenever a pre-tokenization length exceeds the model's
#   max_position_embeddings. Misleading: the warning text claims
#   "indexing errors", but the embedder always passes
#   ``max_length=MAX_TOKENS`` to the encode call which truncates
#   safely. Real tokenizer errors propagate as exceptions, not as
#   this logger warning.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("transformers.tokenization_utils_base").setLevel(
    logging.ERROR
)


# ---------------------------------------------------------------------------
# Pinned model identity (Threat 6)
# ---------------------------------------------------------------------------

# Single source of truth for the BGE-M3 commit SHA. Bumping this constant
# invalidates every cached embedding under ``var/arxmcp/corpus/embeddings``
# and signals E04_S02's MVCC writer to re-encode. The value must match the
# project's security manifest entry for ``BAAI/bge-m3`` (Threat 6
# mitigation). Refresh procedure:
#   curl -s https://huggingface.co/api/models/BAAI/bge-m3 \
#     | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
# Verified 2026-05-07; HEAD of `BAAI/bge-m3` `main` (commit message:
# "Update MIRACL evaluation results of BGE-M3", 2024-07-03).
BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"

# Convenience formatter used for stats logs and the LanceDB
# ``embedder_version`` column. Same short-and-sortable style as
# ``chunker_version`` (single source of truth in ``arxmcp.corpus.chunk``). It names
# the model weights only: a change to pooling, normalisation or tokenizer
# arguments in ``arxmcp.ingest.embedder._encode_batch`` must bump it (or the embedding input
# policy), because reuse matches on it.
EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"

# Maximum number of tokens BGE-M3 attends to. The chunker already enforces
# this for ``body_text`` alone (stmt: 512, proof: 448) but the embed input
# adds an uncapped preamble prefix; the tokenizer's ``truncation=True,
# max_length=MAX_TOKENS`` handles the overflow at encode time.
MAX_TOKENS = 2048

# Where the model runs. Ingest also sizes its default batch from it.
EMBED_DEVICE = os.environ.get("ARXMCP_EMBED_DEVICE", "cpu")
if EMBED_DEVICE not in {"cpu", "cuda"}:
    raise ValueError("ARXMCP_EMBED_DEVICE must be cpu or cuda")

EMBEDDINGS_DIR: Path = ApplicationPaths.resolve().corpus / "embeddings"

# Constant filename for the NPZ + sidecar — co-located under
# ``var/arxmcp/corpus/embeddings/<paper_id>/``. The naming mirrors
# ``chunk_manifest.json`` so a future maintainer immediately understands
# the role from the path alone.
EMBEDDINGS_NPZ_NAME = "embeddings.npz"
EMBEDDINGS_MANIFEST_NAME = "embeddings_manifest.json"


def read_embeddings_manifest(out_path: Path) -> dict | None:
    """Return the sidecar dict, or ``None`` if absent / corrupt.

    A corrupt sidecar (any exception during read or parse) is treated
    as absent — the paper will be re-embedded, regenerating a clean
    sidecar in the process. This is the same self-healing discipline
    ``preamble._read_existing_preamble`` uses (see preamble.py F2 fix).
    """
    if not out_path.exists():
        return None
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # Corrupt sidecar => re-embed (regenerates a clean sidecar).
        return None


# ---------------------------------------------------------------------------
# Lazy model + tokenizer loaders, shared by batch and query encoding
# ---------------------------------------------------------------------------

_model = None
_tokenizer = None


def get_embedding_tokenizer():
    """Return the BGE-M3 tokenizer pinned to :data:`BGE_M3_COMMIT_SHA`.

    Lazy-loaded so importing this module is cheap. Pins the tokenizer to
    the same SHA as the model so that token-id sequences cannot drift
    between encode passes if HuggingFace ships a new tokenizer revision.
    """
    global _tokenizer
    if _tokenizer is None:
        try:
            from transformers import AutoTokenizer  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover — dependency check
            raise ImportError(
                "transformers is required for arxmcp.corpus.embedding. "
                "Install via `pip install -e '.[dev]'` after adding "
                "transformers to pyproject.toml."
            ) from exc
        # E13_S06 Threat 6: refuse a non-SHA revision before any
        # network round trip. The constant is validated at every
        # load (not module import) so a runtime monkeypatch in a
        # test cannot bypass the guard.
        from arxmcp.corpus.model_loader import (  # noqa: PLC0415
            resolve_trust_remote_code,
            validate_model_revision,
        )

        validate_model_revision(BGE_M3_COMMIT_SHA, model_name="BAAI/bge-m3")
        _tokenizer = AutoTokenizer.from_pretrained(
            "BAAI/bge-m3",
            revision=BGE_M3_COMMIT_SHA,
            trust_remote_code=resolve_trust_remote_code(),
        )
    return _tokenizer


def get_embedding_model():
    """Return the BGE-M3 model in eval mode, pinned to :data:`BGE_M3_COMMIT_SHA`.

    Lazy-loaded — the ~2.3 GB safetensors download happens on first call,
    not at import time. Loaded with ``trust_remote_code=False`` per Threat
    6. ``model.eval()`` is required to disable XLM-RoBERTa dropout, without
    which the same input would produce different embeddings on each
    forward pass and break BP1 byte-stability.
    """
    global _model
    if _model is None:
        try:
            import torch  # noqa: PLC0415
            from transformers import AutoModel  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover — dependency check
            raise ImportError(
                "torch and transformers are required for arxmcp.corpus.embedding. "
                "Add 'torch>=2.0' and 'safetensors>=0.4' to pyproject.toml."
            ) from exc
        # E13_S06 Threat 6 closes the remaining model-supply-chain
        # gap. The validator refuses any non-SHA revision before the
        # network round trip; ``resolve_trust_remote_code()`` reads
        # ``ARXMCP_TRUST_REMOTE_CODE`` and returns ``False`` unless
        # the operator opted in (with a WARN log on opt-in).
        from arxmcp.corpus.model_loader import (  # noqa: PLC0415
            resolve_trust_remote_code,
            validate_model_revision,
        )

        validate_model_revision(BGE_M3_COMMIT_SHA, model_name="BAAI/bge-m3")
        _model = AutoModel.from_pretrained(
            "BAAI/bge-m3",
            revision=BGE_M3_COMMIT_SHA,
            # Threat 6: refuse model-card-supplied custom modeling code.
            # Explicit (rather than relying on the transformers default)
            # so a future library default change cannot silently disable
            # the guard.
            trust_remote_code=resolve_trust_remote_code(),
            # NOTE: ``use_safetensors=True`` would close Threat 6's
            # second mitigation (refuse .bin / pickle weights), but
            # the pinned BGE-M3 SHA ``5617a9f6...`` ships only
            # ``pytorch_model.bin`` — adding the kwarg would fail the
            # load. Bumping the SHA to a safetensors-bearing revision
            # would invalidate every cached embedding under
            # ``var/arxmcp/corpus/embeddings`` (a full MVCC re-encode).
            # The reranker IS safetensors-only (see
            # ``src/arxmcp/server/resources.py:_load_reranker_or_raise``). Closing
            # the gap means bumping BGE_M3_COMMIT_SHA to a
            # safetensors-bearing revision and adding
            # ``use_safetensors=True`` here.
        )
        _model.eval()
        if EMBED_DEVICE == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("ARXMCP_EMBED_DEVICE=cuda but CUDA is unavailable")
            _model.to("cuda")
        # Default torch CPU thread count can be 1 on some configurations;
        # explicit setting eliminates the surprise. CPU-only by design —
        # never call .cuda() / .to("cuda"); GPU acceleration is an E11
        # concern. Closes F11: ``torch`` is already imported above; no
        # need to re-import inside this branch.
        if EMBED_DEVICE == "cpu":
            torch.set_num_threads(os.cpu_count() or 4)
    return _model


__all__ = [
    "BGE_M3_COMMIT_SHA",
    "EMBEDDER_VERSION",
    "EMBEDDINGS_DIR",
    "EMBEDDINGS_MANIFEST_NAME",
    "EMBEDDINGS_NPZ_NAME",
    "EMBED_DEVICE",
    "MAX_TOKENS",
    "get_embedding_model",
    "get_embedding_tokenizer",
    "read_embeddings_manifest",
]
