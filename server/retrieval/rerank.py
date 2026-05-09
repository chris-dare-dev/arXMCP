"""Phase 3 BGE-reranker cross-encoder + Tier-3 cache (E07_S03).

Implements the third stage of the hybrid retrieval pipeline: a
cross-encoder neural reranker scores each Phase-2 RRF candidate
against the original query and reorders them. Returns the top-k
candidates as ``(chunk_id, rerank_score)`` tuples.

**Default-off via ``ARXMCP_ENABLE_RERANK``.** Phase 3 is gated by
the env-var (default ``False``). When disabled,
:meth:`RerankPhase.rerank` is a passthrough that returns the input
candidates truncated to ``top_k`` — no encode, no model load, no
semaphore acquisition, no singleflight lookup. The activation path
(per ``.claude/notes/05-storage-and-indexing.md:329-331``): E07_S04
demonstrates that nDCG@5 ≥ 0.80 requires the reranker; only then
the flag flips on. If nDCG@5 ≥ 0.80 is reached without rerank, the
flag stays off and Phase 3 remains dormant.

**Model: ``BAAI/bge-reranker-v2-m3``** loaded via
:class:`transformers.AutoModelForSequenceClassification` (NOT
FlagEmbedding, mirroring the embedder's E03_S01 precedent — keeps
the dependency surface minimal). Pinned to
:data:`BGE_RERANKER_COMMIT_SHA` via ``revision=`` kwarg
(Threat 6 from ``08-security-observability-ops.md``;
``trust_remote_code=False`` blocks the modeling-script RCE vector).
``model.eval()`` + ``torch.no_grad()`` at inference.

**Tier-3 cache** (``.claude/notes/07-multi-agent-caching.md:155-166``):
the singleflight key is
``sha256(query_vec.tobytes() + sorted_chunk_id_bytes + reranker_version_bytes)``.
This deduplicates concurrent identical rerank requests — the spec
also calls for a separate LRU memo (1-hour TTL) for completed
results; that's deferred to a follow-up. The singleflight is the
in-process collapse; the LRU is the cross-request memo.

**Two-tier concurrency.** ``async with r.rerank_semaphore:`` caps
distinct-rerank parallelism (``max_concurrent_reranks=4`` per
``server/config.py:120``); the ``r.rerank_singleflight.run(...)``
inside collapses same-rerank duplicates. Mirrors the embedder's
``embed_semaphore`` + ``encode_query`` singleflight pattern.

**Cross-encoder API.** ``model(**inputs).logits.view(-1)`` returns
one logit per ``(query, doc)`` pair. ``sigmoid`` maps to bounded
[0, 1] so the rerank score is comparable to the dense cosine score
(also in [0, 1]). Tokenize as ``[(query, body) for body in bodies]``
with ``max_length=512`` (latency budget; BGE-reranker-v2-m3 supports
up to 8192 but at 50 candidates this would blow the brief's 5s
budget on commodity hardware). All 50 pairs go through ONE forward
pass — batching, not a Python loop.

**SHA drift = WARNING, not FATAL.** Brief explicit. The opt-in
default justifies the asymmetry vs the embedder (which raises on
SHA mismatch via ``revision=``): until E07_S04 flips the flag,
SHA drift cannot affect production retrieval.

**Phantom-id contract** (E07_S02 F5 → carried through here): if a
candidate's ``chunk_id`` does not exist in the live LanceDB table
(stale BM25 artifact, mid-process corpus mutation), the
body-text fetch returns no row for it. We silently drop the
phantom from the rerank set (it has no body to score) and continue
with the rest. Document; don't crash.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
    from transformers import (  # type: ignore[import-untyped]
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pinned model identity (Threat 6, 08-security-observability-ops.md)
# ---------------------------------------------------------------------------

#: Single source of truth for the BGE-reranker-v2-m3 commit SHA.
#: Bumping this constant invalidates every cached rerank result
#: under ``Resources.rerank_singleflight`` (the dedup window is
#: per-process, so a restart suffices) AND would change the
#: ``RERANKER_VERSION`` string baked into the Tier-3 cache key.
#:
#: Refresh procedure (mirrors ``ingest/embedder.py:108-110``):
#:
#:   curl -s https://huggingface.co/api/models/BAAI/bge-reranker-v2-m3 \
#:     | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
#:
#: Verified 2026-05-09; HEAD of ``BAAI/bge-reranker-v2-m3`` ``main``
#: (commit message: "update README.md", 2024-06-24). The SHA is
#: encoded as the lowercase hex string; comparison with a HuggingFace
#: cache snapshot dir name is direct equality.
BGE_RERANKER_COMMIT_SHA: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"

#: Convenience formatter for the singleflight key + log lines.
#: Same short-and-sortable style as ``EMBEDDER_VERSION`` at
#: ``ingest/embedder.py:117``.
RERANKER_VERSION: str = f"bge-reranker-v2-m3@{BGE_RERANKER_COMMIT_SHA[:8]}"

#: HuggingFace model identifier (the ``org/name`` repo path used by
#: ``from_pretrained``).
RERANKER_MODEL_ID: str = "BAAI/bge-reranker-v2-m3"

#: Tokenizer max length per encode pair. BGE-reranker-v2-m3 supports
#: up to 8192 but at 50 candidates × 8K tokens = ~10s on CPU. 512
#: matches the embedder's ``MAX_TOKENS`` and keeps the brief's
#: 5-second budget achievable. Document the trade-off; revisit in
#: E07_S04 with nDCG data.
RERANKER_MAX_LENGTH: int = 512

#: Maximum k value accepted by :meth:`RerankPhase.rerank`. Mirrors
#: ``server/handlers/search.py:MAX_K`` so a misconfigured caller
#: cannot ask for more candidates than the upstream cap.
MAX_K: int = 50


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RerankerLoadError(RuntimeError):
    """Raised when the reranker model cannot be loaded.

    Lifted to a startup-time error by :func:`server.resources._load_reranker_or_raise`,
    which wraps as :class:`server.resources.RerankerUnavailableError`."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _huggingface_cache_snapshot_sha(model_id: str) -> str | None:
    """Return the SHA of the locally-cached ``model_id`` snapshot,
    or ``None`` if the model is not cached.

    HuggingFace cache layout (verified for ``huggingface_hub`` 0.25):
    ``~/.cache/huggingface/hub/models--<org>--<name>/snapshots/<sha>/``
    where the snapshot directory name IS the commit SHA. We pick the
    first non-empty snapshot dir; if there are multiple (rare), we
    return the most-recently-modified one, since transformers always
    updates the cache symlinks at load time.

    Used by :func:`maybe_log_sha_drift` for the brief-mandated
    startup drift check.
    """
    cache_root = (
        Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
        / "hub"
    )
    # ``models--BAAI--bge-reranker-v2-m3``
    safe_name = "models--" + model_id.replace("/", "--")
    snapshots_dir = cache_root / safe_name / "snapshots"
    if not snapshots_dir.is_dir():
        return None
    # Snapshot dirs are SHA hex strings (40 lowercase chars).
    candidates = sorted(
        (
            d
            for d in snapshots_dir.iterdir()
            if d.is_dir() and len(d.name) == 40
        ),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    return candidates[0].name


def maybe_log_sha_drift(expected_sha: str) -> None:
    """If the locally-cached BGE-reranker SHA differs from
    ``expected_sha``, log a WARNING (NOT a fatal raise — brief
    explicit).

    Called from :func:`server.resources._load_reranker_or_raise`
    AFTER a successful model load (so we know the cache is
    populated). The drift signal is informational: until E07_S04
    flips ``ARXMCP_ENABLE_RERANK=true`` in production, SHA drift
    has no behavioral impact (the model is never invoked).
    """
    cached_sha = _huggingface_cache_snapshot_sha(RERANKER_MODEL_ID)
    if cached_sha is None:
        logger.info(
            "BGE-reranker SHA drift check: no local cache snapshot "
            "found at HF_HOME (model loaded fresh from the Hub)"
        )
        return
    if cached_sha != expected_sha:
        logger.warning(
            "BGE-reranker SHA drift: cached snapshot=%s, pinned SHA=%s. "
            "The transformers loader fetched the pinned revision from "
            "the Hub, so this run is safe; the warning surfaces a "
            "stale local cache. Refresh: rm -rf "
            "~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3 "
            "and re-load.",
            cached_sha, expected_sha,
        )
    else:
        logger.info(
            "BGE-reranker SHA drift check: cached snapshot matches "
            "pinned SHA (%s)", expected_sha,
        )


def _build_singleflight_key(
    query_vec: np.ndarray,
    candidates: Sequence[tuple[str, float]],
) -> str:
    """Build the Tier-3 cache key per
    ``.claude/notes/07-multi-agent-caching.md:155-166``:

        key = sha256(
            query_embedding_hash
            + sorted_candidate_id_tuple_hash
            + reranker_version
        )

    We hash by feeding all three components into one ``sha256``,
    not by composing three separate hexdigests — equivalent
    cryptographically but cheaper.

    Sort ASC matches the project-wide determinism rule
    (``server/retrieval/rrf.py``: sort key ``(score desc, chunk_id
    asc)``). Stable across runs so two callers with the same query
    vector + candidate set hit the singleflight even if they
    received the candidates in different RRF-derived orders (rare;
    RRF itself is deterministic, but defensive).
    """
    h = hashlib.sha256()
    # Query embedding bytes — float32 1024-dim L2-normalized.
    h.update(query_vec.tobytes())
    h.update(b"\x00")  # field separator (any byte not in the field)
    # Sorted chunk_ids, joined by NUL.
    sorted_ids = sorted(cid for cid, _score in candidates)
    h.update(b"\n".join(cid.encode("utf-8") for cid in sorted_ids))
    h.update(b"\x00")
    # Reranker version.
    h.update(RERANKER_VERSION.encode("utf-8"))
    return h.hexdigest()


def _fetch_body_texts(
    chunks_table: Any,
    chunk_ids: Sequence[str],
) -> dict[str, str]:
    """Fetch ``body_text`` for each chunk_id from LanceDB.

    Returns ``{chunk_id: body_text}``. Phantom ids (per E07_S02 F5
    contract — ids in the BM25 list that don't exist in the live
    table) are simply absent from the returned dict; the caller
    drops them from the rerank set.
    """
    if not chunk_ids:
        return {}
    # Quote chunk_ids for the SQL IN clause. chunk_id format is
    # ``arxiv:<paper_id>:<16-hex>`` — no internal quotes to escape,
    # but defense-in-depth: refuse any id containing a single quote.
    safe_ids: list[str] = []
    for cid in chunk_ids:
        if "'" in cid:
            logger.warning(
                "_fetch_body_texts: dropping chunk_id %r containing "
                "a single quote (defense-in-depth against SQL "
                "injection through a tampered candidate list)",
                cid,
            )
            continue
        safe_ids.append(cid)
    if not safe_ids:
        return {}
    csv = ", ".join(f"'{cid}'" for cid in safe_ids)
    arrow = (
        chunks_table.search()
        .where(f"chunk_id IN ({csv})")
        .select(["chunk_id", "body_text"])
        .limit(len(safe_ids))
        .to_arrow()
    )
    cids = arrow.column("chunk_id").to_pylist()
    bodies = arrow.column("body_text").to_pylist()
    out: dict[str, str] = {}
    for cid, body in zip(cids, bodies, strict=True):
        if cid is None or body is None:
            continue
        out[cid] = body
    return out


# ---------------------------------------------------------------------------
# Sync inference helper — runs inside the executor thread
# ---------------------------------------------------------------------------


def _rerank_sync(
    model: AutoModelForSequenceClassification,
    tokenizer: AutoTokenizer,
    query_text: str,
    bodies: Sequence[str],
) -> list[float]:
    """Run the cross-encoder forward pass; return one score per body
    in input order.

    All ``len(bodies)`` pairs go through ONE forward pass — batching,
    not a Python loop. Score is ``sigmoid(logit)`` so the result is
    bounded in [0, 1] and comparable to the dense cosine score.

    Runs in a thread pool worker (off-loaded from the asyncio event
    loop) because PyTorch's CPU forward pass is synchronous +
    long-running.
    """
    import torch  # noqa: PLC0415

    if not bodies:
        return []

    pairs = [[query_text, body] for body in bodies]
    inputs = tokenizer(
        pairs,
        padding=True,
        truncation=True,
        max_length=RERANKER_MAX_LENGTH,
        return_tensors="pt",
    )
    with torch.no_grad():
        # logits shape: [batch, num_labels=1]; squeeze to [batch]
        logits = model(**inputs).logits.view(-1).float()
        scores = torch.sigmoid(logits)
    return scores.tolist()


# ---------------------------------------------------------------------------
# RerankPhase
# ---------------------------------------------------------------------------


class RerankPhase:
    """Phase-3 cross-encoder reranker (gated by
    ``ARXMCP_ENABLE_RERANK``).

    Constructed once at server startup; reused across every request.

    Public API:

    - :meth:`rerank` — async; gates on the ``enabled`` flag, builds
      the Tier-3 singleflight key, and either passes through (flag
      off) or runs the cross-encoder inside the singleflight + the
      ``rerank_semaphore``.

    The reranker model + tokenizer are loaded by
    :func:`server.resources._load_reranker_or_raise` and passed in
    via the constructor (``model_handle``); the phase does NOT load
    the model itself.
    """

    def __init__(
        self,
        chunks_table: Any,
        rerank_singleflight: Any,
        rerank_semaphore: Any,
        enabled: bool,
        model_handle: Any | None = None,
    ) -> None:
        """Direct construction.

        Parameters
        ----------
        chunks_table:
            The LanceDB chunks table handle (for body_text fetch).
        rerank_singleflight:
            The :class:`server.resources.Singleflight` instance
            (Tier-3 dedup of concurrent identical reranks).
        rerank_semaphore:
            ``asyncio.Semaphore(max_concurrent_reranks)`` (caps
            distinct-rerank parallelism).
        enabled:
            ``ARXMCP_ENABLE_RERANK`` value. When ``False``,
            :meth:`rerank` is a passthrough.
        model_handle:
            ``(model, tokenizer)`` tuple from
            :func:`server.resources._load_reranker_or_raise` (or
            equivalent test stub). Required when ``enabled=True``;
            ignored when ``enabled=False`` (allowed to be ``None``
            so the off-path doesn't require a model load).

        Raises
        ------
        ValueError
            ``enabled=True`` but ``model_handle is None``.
        """
        if enabled and model_handle is None:
            raise ValueError(
                "RerankPhase: enabled=True requires a non-None "
                "model_handle from _load_reranker_or_raise()"
            )
        self._chunks_table = chunks_table
        self._rerank_singleflight = rerank_singleflight
        self._rerank_semaphore = rerank_semaphore
        self._enabled = enabled
        self._model_handle = model_handle

    # ------------------------------------------------------------------
    # Read-only introspection
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the cross-encoder is active. Mirrors
        ``Config.enable_rerank`` at startup; not mutable post-init."""
        return self._enabled

    # ------------------------------------------------------------------
    # Rerank
    # ------------------------------------------------------------------

    async def rerank(
        self,
        query_text: str,
        query_vec: np.ndarray,
        candidates: Sequence[tuple[str, float]],
        top_k: int,
    ) -> list[tuple[str, float]]:
        """Rerank ``candidates`` and return the top-``top_k`` ranked
        list.

        Parameters
        ----------
        query_text:
            Original query string. Passed verbatim to the
            cross-encoder.
        query_vec:
            The L2-normalized 1024-dim query embedding from
            :func:`server.query_encoder.encode_query` (already
            computed by Phase 2). Used for the Tier-3 singleflight
            key — the BYTES of this vector are part of the cache
            identity, so two queries with byte-identical vectors
            (after singleflight in encode_query) hit the same
            reranked output.
        candidates:
            Phase-2 RRF candidates as ``(chunk_id, fused_score)``
            tuples. May be any length; only the first ``top_k`` are
            returned in either branch.
        top_k:
            Number of candidates to return. ``1 ≤ top_k ≤ 50``
            (mirrors ``server/handlers/search.py``'s ``MAX_K``).

        Returns
        -------
        list[tuple[str, float]]
            ``(chunk_id, score)`` tuples sorted by ``(score desc,
            chunk_id asc)``. Length ≤ ``top_k``.

            **Off-path** (``enabled=False``): returns
            ``list(candidates[:top_k])`` verbatim — preserves the
            input RRF score in the second slot.

            **On-path** (``enabled=True``): cross-encoder scores
            replace the RRF scores; the order can differ from the
            input order.

        Raises
        ------
        ValueError
            ``top_k < 1`` or ``top_k > MAX_K``.
        """
        if not 1 <= top_k <= MAX_K:
            raise ValueError(
                f"top_k must be in [1, {MAX_K}]; got {top_k}"
            )

        # OFF-PATH: passthrough. No encode, no model, no semaphore,
        # no singleflight. AC #1.
        if not self._enabled:
            return list(candidates[:top_k])

        # ON-PATH: two-tier concurrency. Semaphore caps distinct-
        # rerank parallelism; singleflight collapses same-rerank
        # duplication.
        if not candidates:
            # No candidates → nothing to rerank → empty result.
            return []

        key = _build_singleflight_key(query_vec, candidates)

        async with self._rerank_semaphore:
            # The singleflight returns the SAME list object to all
            # waiters (no defensive copy in the generic Singleflight,
            # unlike encode_query). Callers MUST NOT mutate the
            # returned list — the docstring documents this. Tuple
            # elements are immutable, so a shared reference is safe
            # for read.
            ranked = await self._rerank_singleflight.run(
                key, lambda: self._do_rerank(query_text, candidates),
            )
        return ranked[:top_k]

    async def _do_rerank(
        self,
        query_text: str,
        candidates: Sequence[tuple[str, float]],
    ) -> list[tuple[str, float]]:
        """The actual rerank work — fetch body_texts, run the
        cross-encoder, return sorted ``(chunk_id, score)``.

        Called only when ``enabled=True`` and inside the singleflight
        + semaphore. Off-loaded to the executor for the
        PyTorch forward pass (which is sync + CPU-bound)."""
        chunk_ids = [cid for cid, _ in candidates]
        body_by_id = _fetch_body_texts(self._chunks_table, chunk_ids)

        # Build aligned lists in the input order; phantom ids
        # (per E07_S02 F5) are silently dropped.
        aligned_ids: list[str] = []
        aligned_bodies: list[str] = []
        for cid in chunk_ids:
            body = body_by_id.get(cid)
            if body is None:
                continue
            aligned_ids.append(cid)
            aligned_bodies.append(body)

        if not aligned_ids:
            # Every candidate was a phantom — nothing to score.
            return []

        model, tokenizer = self._model_handle  # type: ignore[misc]
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(
            None,
            _rerank_sync,
            model,
            tokenizer,
            query_text,
            aligned_bodies,
        )

        # Pair up + sort (score desc, chunk_id asc) per project-wide
        # determinism rule.
        ranked = list(zip(aligned_ids, scores, strict=True))
        ranked.sort(key=lambda x: (-x[1], x[0]))
        return ranked


__all__ = [
    "BGE_RERANKER_COMMIT_SHA",
    "MAX_K",
    "RERANKER_MAX_LENGTH",
    "RERANKER_MODEL_ID",
    "RERANKER_VERSION",
    "RerankPhase",
    "RerankerLoadError",
    "maybe_log_sha_drift",
]
