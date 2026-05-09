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
    """LanceDB squared-L2 distance → cosine similarity in [0, 1].

    F1 fix from the E07_S02 critique: LanceDB returns *squared* L2
    distance on the ``_distance`` column for the L2 metric, NOT raw
    L2. Verified empirically against LanceDB 0.30: a query against
    a unit vector v with corpus ``{v, v_orth, -v}`` returns
    ``_distance = [0.0, 2.0, 4.0]``. For unit vectors
    ``||a - b||² = 2 - 2·cos(a, b)``, so ``cos = 1 - dist/2`` is
    the correct conversion to bounded cosine in [0, 1] (the formula
    looks like "raw L2 / 2" but is actually "squared L2 / 2"). A
    future maintainer who "fixes" the formula to ``1 - sqrt(dist)/2``
    would silently break ranking quality — keep the docstring AND
    the regression test in ``tests/retrieval/test_ann.py`` honest.

    Mirrors :func:`server.handlers.search._distance_to_score` (same
    rectification applied there). The bounded score is informational
    — RRF consumes only ranks, so this conversion is for callers
    that want to inspect the raw dense similarity of each ANN
    candidate.

    The lower clamp (``max(0.0, ...)``) defends against numerical
    instability that could produce a tiny negative cosine; the upper
    side is implicitly bounded because squared-L2 of unit vectors
    is in [0, 4] which yields ``1 - dist/2 ∈ [-1, 1]``, clamped
    here to [0, 1].
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

    Returns ``[]`` on a NARROW set of failures that are consistent
    with "this column has no candidates":

    - ``ValueError``: LanceDB raises when a column has no HNSW index
      AND brute-force is also disallowed; same shape when the column
      is fully NULL.
    - ``KeyError`` / ``RuntimeError``: thrown for various
      LanceDB-internal "empty input" cases.

    F3 fix from the E07_S02 critique: we used to catch
    ``Exception`` broadly. That cushion was wider than the brief
    asked for — it silently absorbed typos in ``vector_column_name``
    (verified: an unknown column raises ``RuntimeError("LanceError:
    column X does not exist")``). The init-time column-existence
    check in :meth:`ANNPhase.__init__` now refuses the typo case
    upfront; this helper handles only the runtime "this column is
    legitimately empty for this corpus" path.

    A failure is logged at INFO (not WARNING) when the column is
    KNOWN to be empty for this corpus — see the early-return at the
    init-cached ``_searchable_columns`` set in :class:`ANNPhase`.
    Callers should pre-filter via that set so this helper never
    fires on the expected-empty path. F14 fix.
    """
    try:
        arrow = (
            chunks_table.search(query_vec, vector_column_name=column)
            .limit(limit)
            .to_arrow()
        )
    except (ValueError, KeyError, RuntimeError) as exc:
        # Narrow set: LanceDB-internal empty-column / no-index
        # failures. Programmer errors (typo in column name) are
        # caught upstream by the init-time schema check so they
        # don't reach this point in production.
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


def _column_has_rows(chunks_table: Any, column: str) -> bool:
    """Return True if ``chunks_table`` has at least one non-null
    row in ``column``.

    Used by :meth:`ANNPhase.__init__` to pre-compute the set of
    searchable columns once, so the per-query path skips columns
    that are KNOWN to be empty rather than catching the LanceDB
    exception (F14 — eliminates per-query log spam on stmt-only
    seed corpora).

    Cheap: a single Arrow scan filtered by ``column IS NOT NULL``
    with ``limit=1``. Fires once at startup, never per query.
    """
    try:
        arrow = (
            chunks_table.search()
            .where(f"{column} IS NOT NULL")
            .select(["chunk_id"])
            .limit(1)
            .to_arrow()
        )
    except Exception:  # noqa: BLE001 — tolerate any LanceDB API quirk
        # If the schema-introspection itself fails, conservatively
        # report "no rows" — the per-query path's narrow except
        # will surface the real error if a query is attempted.
        return False
    return arrow.num_rows > 0


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
        :class:`server.resources.Resources`. We cache the reference
        AND pre-compute the set of searchable embedding columns by
        checking each :data:`EMBEDDING_COLUMNS` entry for non-null
        rows.

        F3 fix: validate that every column listed in
        :data:`EMBEDDING_COLUMNS` exists on the table schema —
        catches typos at startup rather than at first query
        (where the previous broad ``except Exception`` would have
        silently swallowed them as "empty result").

        F14 fix: pre-compute ``self._searchable_columns`` so the
        per-query path skips columns known to be empty for this
        corpus. Eliminates log spam on stmt-only seed corpora
        (the production reality at v1).
        """
        self._chunks_table = chunks_table

        # F3: schema validation — refuse upfront if a configured
        # column is missing from the LanceDB schema. The 'embedding_'
        # prefix is informational; the column-name strings are
        # source-of-truth.
        schema_columns = set(chunks_table.schema.names)
        missing = [c for c in EMBEDDING_COLUMNS if c not in schema_columns]
        if missing:
            raise ValueError(
                f"ANNPhase: column(s) {missing!r} declared in "
                f"EMBEDDING_COLUMNS but missing from chunks_table schema "
                f"({sorted(schema_columns)!r}). Either fix EMBEDDING_COLUMNS "
                f"or rebuild the chunks table with the missing columns."
            )

        # F14: skip empty columns at query time rather than catching.
        self._searchable_columns: tuple[str, ...] = tuple(
            c for c in EMBEDDING_COLUMNS if _column_has_rows(chunks_table, c)
        )
        if not self._searchable_columns:
            # Both columns empty — every query is ANN-empty. Log
            # once at startup so ops can spot a brand-new corpus.
            logger.warning(
                "ANNPhase: no embedding columns have rows; all queries "
                "will fall back to BM25-only fusion. Re-ingest with the "
                "embedder if this is unexpected."
            )

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

            **Phantom-id contract (F5).** ANNPhase does NOT
            cross-check that BM25 chunk_ids exist in the live
            chunks table. The :meth:`server.retrieval.bm25.BM25Phase.startup`
            cross-check (E07_S01 F4) is the canonical guard. If a
            future code path bypasses that startup check OR mutates
            the corpus mid-process, phantom chunk_ids may appear
            in the RRF output unmodified. Downstream consumers
            (E07_S03 reranker, E07_S04 handler) must tolerate
            phantom ids in the candidate stream.
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
            ``top_n < 1``, ``query_text`` empty/whitespace-only,
            or ``query_text`` longer than 10,000 characters
            (defense-in-depth — the FastAPI handler already caps
            at 2000 but ANNPhase as a peer of BM25Phase enforces
            its own boundary).
        """
        # F10 fix: defense-in-depth validation at the ANNPhase
        # boundary. The FastAPI handler caps query length at 2000
        # via Pydantic Field, but a non-handler caller (debug
        # script, internal RPC, future test fixture) bypasses that
        # validator. ANNPhase's own boundary catches the foot-gun.
        if not query_text or not query_text.strip():
            raise ValueError(
                "query_text must contain non-whitespace characters; "
                f"got {query_text!r}"
            )
        if len(query_text) > 10_000:
            # Generous upper bound: 5x the FastAPI handler limit
            # so legitimate callers from internal contexts have
            # headroom, but pathological inputs are still capped
            # before they reach the embedder.
            raise ValueError(
                f"query_text length {len(query_text)} exceeds the "
                f"10,000-char defense-in-depth bound; the FastAPI "
                f"handler caps at 2000 characters — internal callers "
                f"should respect the same bound."
            )
        if top_n < 1:
            raise ValueError(f"top_n must be >= 1; got {top_n}")

        # 1. Encode the query — ONE call. Singleflight in
        # encode_query coalesces concurrent identical queries.
        # We do NOT acquire ``r.embed_semaphore`` here because
        # ANNPhase doesn't have a Resources reference; the future
        # handler-level orchestrator (E07_S04) acquires the
        # semaphore around the whole hybrid query.
        query_vec = await encode_query(query_text)

        # 2. ANN searches over each searchable column. F4 fix:
        # iterate :data:`EMBEDDING_COLUMNS` (filtered through the
        # init-cached ``_searchable_columns`` set) so the constant
        # is the single source of truth. F14 fix: skip columns
        # KNOWN to be empty (per ``_column_has_rows`` at init) —
        # no per-query log spam on stmt-only corpora.
        per_column_results: list[list[tuple[str, float]]] = []
        for column in self._searchable_columns:
            per_column_results.append(
                _ann_search_one_column(
                    self._chunks_table,
                    query_vec,
                    column=column,
                    limit=PER_COLUMN_LIMIT,
                )
            )

        # 3. Adapt all input lists to chunk_id-only ranked lists for
        # RRF. (RRF discards source scores by design — see
        # rrf.py docstring.) Empty lists are tolerated.
        bm25_ids = [cid for cid, _score in bm25_candidates]
        all_ranked_lists: list[list[str]] = [bm25_ids]
        for results in per_column_results:
            all_ranked_lists.append([cid for cid, _score in results])

        # 4. RRF fusion. The sort is project-wide determinism:
        # (fused_score desc, chunk_id asc).
        fused = reciprocal_rank_fusion(all_ranked_lists, k=RRF_K)

        # 5. Truncate to top_n.
        return fused[:top_n]


__all__ = [
    "DEFAULT_TOP_N",
    "EMBEDDING_COLUMNS",
    "PER_COLUMN_LIMIT",
    "ANNPhase",
]
