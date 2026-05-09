"""Phase 2 dual-ANN retrieval + RRF (E07_S02).

Implements the second stage of the hybrid retrieval pipeline:
HNSW ANN search over both ``embedding_stmt`` and ``embedding_proof``
columns, fused with the Phase-1 BM25 candidates via Reciprocal
Rank Fusion (k=60). Returns the top-N fused candidates as input
to Phase 3 (E07_S03 BGE-reranker).

**One encoder, two columns, one query vector.** The brief's
"prose encoder" / "LaTeX encoder" framing is fictional — the
codebase has ONE BGE-M3 encoder
(``ingest/embedder.py:112-122``) and the dual columns are
KIND-ROUTED at index time (``kind == "proof"`` →
``embedding_proof``; everything else → ``embedding_stmt``;
``ingest/embedder.py:19-22``). At query time we call
:func:`server.query_encoder.encode_query` ONCE and reuse the
single 1024-dim L2-normalized vector against both columns. See
research-synthesis.md, fact 1.

**Score conversion.** L2 distance on unit-normalized vectors →
cosine similarity in [0, 1] via ``score = max(0, 1 - dist / 2)``.
Mirrors the existing dense-only path in
``server/handlers/search.py:260-264``. RRF doesn't consume the
scores — only ranks — so this conversion is informational
(returned alongside the rank for callers that want to surface a
pre-RRF dense similarity).

**Graceful degradation.** Three input lists, three independent
empty cases:

1. ``bm25_candidates == []`` (highly symbolic queries with no
   body-token matches): fuse only the two ANN lists. AC #1.
2. ``embedding_proof`` column has no rows OR no HNSW index built
   (seed corpus, all stmt-kind chunks; ``ingest/store.py:411-435``
   skips index build when ``_count_non_null == 0``): fuse
   ``bm25`` + ``stmt`` only. Brief risk note.
3. All three empty (degenerate / new corpus): return ``[]``.

The proof-search call is wrapped in a try/except that catches
LanceDB exceptions (no HNSW → brute-force OR raise) AND zero-row
results, both surfacing as an empty rank-list contribution to RRF.

**`Resources.ann_phase` lifecycle.** The class is instantiated
once at server startup from ``Resources.startup`` (after
``bm25_phase`` so the dependency order is BM25 → ANN). The
constructor is cheap — it caches the ``chunks_table`` reference
and nothing else; no expensive load. No async startup classmethod
required.

**Sequential ANN searches.** Two ``tbl.search(...)`` calls in
sequence, not parallel. Seed-scale latency is sub-10ms each;
sequential is fine for v1. Parallel fan-out via
``asyncio.to_thread + gather`` is documented as a future
optimization but not implemented here.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from server.query_encoder import encode_query
from server.retrieval.rrf import RRF_K, reciprocal_rank_fusion

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Default top-N candidates returned by :meth:`ANNPhase.query`. Per
#: ``.claude/notes/05-storage-and-indexing.md:328-329`` ("Take
#: top-50") — Phase 3 (E07_S03) reduces this further via reranking.
DEFAULT_TOP_N: int = 50

#: Per-column ANN candidate count. Each column contributes its
#: top-50 to the RRF fusion before truncation. Per
#: ``.claude/notes/05-storage-and-indexing.md:325`` ("top-50 each").
PER_COLUMN_LIMIT: int = 50

#: The two embedding columns the dual-ANN searches. Listed
#: explicitly so ``embedding_eq`` (reserved for E10_S03) is NEVER
#: searched here even if a future schema change makes it nullable.
EMBEDDING_COLUMNS: tuple[str, ...] = ("embedding_stmt", "embedding_proof")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _distance_to_score(dist: float | None) -> float:
    """L2 distance on unit vectors → cosine similarity in [0, 1].

    Mirrors :func:`server.handlers.search._distance_to_score`. The
    bounded score is informational — RRF consumes only ranks, so
    this conversion is for callers that want to inspect the raw
    dense similarity of each ANN candidate.
    """
    if dist is None:
        return 0.0
    return max(0.0, 1.0 - float(dist) / 2.0)


def _ann_search_one_column(
    chunks_table: Any,
    query_vec: np.ndarray,
    column: str,
    limit: int,
) -> list[tuple[str, float]]:
    """Run a single-column ANN search; return ``(chunk_id, score)``
    candidates ordered by relevance (best first).

    Returns ``[]`` on any failure that is consistent with "this
    column has no candidates" — most commonly the column has zero
    non-null rows and therefore no HNSW index. We log the underlying
    exception at WARNING (not ERROR) so ops can spot a brand-new
    corpus that hasn't been re-indexed yet, but the search still
    completes via the other column + BM25.
    """
    try:
        arrow = (
            chunks_table.search(query_vec, vector_column_name=column)
            .limit(limit)
            .to_arrow()
        )
    except Exception as exc:
        # LanceDB raises a variety of exception types when a column
        # is unindexed / empty. We catch broadly because the
        # graceful-degradation path is what the brief mandates; a
        # narrower except would let an unanticipated subclass
        # propagate and break all retrieval.
        logger.warning(
            "ANN search on column %s failed (%s); treating as empty",
            column, exc,
        )
        return []

    cids = arrow.column("chunk_id").to_pylist()
    distances = arrow.column("_distance").to_pylist()
    out: list[tuple[str, float]] = []
    for cid, dist in zip(cids, distances, strict=True):
        if cid is None:
            # Defensive: chunk_id is non-null in the schema, but if a
            # row slipped in with NULL we don't want to rank it.
            continue
        out.append((cid, _distance_to_score(dist)))
    return out


# ---------------------------------------------------------------------------
# ANNPhase
# ---------------------------------------------------------------------------


class ANNPhase:
    """Phase-2 dual-ANN retrieval + RRF fusion.

    Constructed once at server startup; reused across every request.
    Read-only after construction; safe for concurrent readers.

    Public API:

    - :meth:`query` — async; encodes the query, runs both ANN
      searches sequentially, fuses with the BM25 list via RRF,
      returns top-N candidates.

    The class does NOT call :meth:`server.retrieval.bm25.BM25Phase.query`
    — the caller (a future hybrid-search orchestrator) provides
    the BM25 candidate list as a separate argument. This keeps
    ANNPhase a peer of BM25Phase rather than a dependent.
    """

    def __init__(self, chunks_table: Any) -> None:
        """Direct construction from the LanceDB chunks table handle.

        ``chunks_table`` is the duck-typed handle from
        :class:`server.resources.Resources`. We cache the reference;
        no per-request copy or rebuild.
        """
        self._chunks_table = chunks_table

    # ------------------------------------------------------------------
    # Read-only introspection
    # ------------------------------------------------------------------

    @property
    def chunks_table(self) -> Any:
        """The LanceDB table handle. Useful for tests that want to
        cross-check returned chunk_ids against the live corpus."""
        return self._chunks_table

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def query(
        self,
        query_text: str,
        bm25_candidates: Sequence[tuple[str, float]],
        top_n: int = DEFAULT_TOP_N,
    ) -> list[tuple[str, float]]:
        """Run dual-ANN + RRF fusion. Return top-N fused candidates.

        Parameters
        ----------
        query_text:
            The user query string. Passed verbatim to
            :func:`server.query_encoder.encode_query` (which
            NFC-normalizes + strips, then routes through the
            singleflight). NOT tokenized for BM25 here — that's the
            caller's responsibility (E07_S01's ``BM25Phase.query``
            already produced ``bm25_candidates``).
        bm25_candidates:
            ``(chunk_id, bm25_score)`` tuples from
            ``BM25Phase.query``'s first return element. May be
            empty (highly symbolic queries with no body-token
            matches). Scores are NOT consumed — RRF is rank-based.
        top_n:
            Maximum number of fused candidates to return. Default
            :data:`DEFAULT_TOP_N` (50) per the design note.

        Returns
        -------
        list[tuple[str, float]]
            ``(chunk_id, fused_score)`` tuples sorted by
            ``(fused_score desc, chunk_id asc)``. Length ≤ ``top_n``.
            May be empty when all three input lists are empty (new
            corpus / pathological query).

        Raises
        ------
        ValueError
            ``top_n < 1``.
        """
        if top_n < 1:
            raise ValueError(f"top_n must be >= 1; got {top_n}")

        # 1. Encode the query — ONE call. Singleflight in
        # encode_query coalesces concurrent identical queries.
        # We do NOT acquire ``r.embed_semaphore`` here because
        # ANNPhase doesn't have a Resources reference; the future
        # handler-level orchestrator (E07_S04) acquires the
        # semaphore around the whole hybrid query.
        query_vec = await encode_query(query_text)

        # 2. Two sequential ANN searches. Each returns
        # (chunk_id, score) candidates ordered best-first. Either
        # may return empty: stmt is empty if the column has no
        # rows; proof is empty in the seed-corpus case where all
        # chunks are kind="stmt".
        stmt_candidates = _ann_search_one_column(
            self._chunks_table,
            query_vec,
            column="embedding_stmt",
            limit=PER_COLUMN_LIMIT,
        )
        proof_candidates = _ann_search_one_column(
            self._chunks_table,
            query_vec,
            column="embedding_proof",
            limit=PER_COLUMN_LIMIT,
        )

        # 3. Adapt all three lists to chunk_id-only ranked lists for
        # RRF. (RRF discards source scores by design — see
        # rrf.py docstring.) Empty lists are tolerated.
        bm25_ids = [cid for cid, _score in bm25_candidates]
        stmt_ids = [cid for cid, _score in stmt_candidates]
        proof_ids = [cid for cid, _score in proof_candidates]

        # 4. RRF fusion. The sort is project-wide determinism:
        # (fused_score desc, chunk_id asc).
        fused = reciprocal_rank_fusion(
            [bm25_ids, stmt_ids, proof_ids], k=RRF_K
        )

        # 5. Truncate to top_n.
        return fused[:top_n]


__all__ = [
    "DEFAULT_TOP_N",
    "EMBEDDING_COLUMNS",
    "PER_COLUMN_LIMIT",
    "ANNPhase",
]
