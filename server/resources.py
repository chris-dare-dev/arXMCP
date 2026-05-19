"""Server-process lifecycle resources (E06_S01).

Owns the three expensive, long-lived objects that the
``arxmcp-server`` process loads once and reuses for every request:

1. The **BGE-M3 embedder** (loaded into CPU/GPU memory; ~1.5 GB on
   CPU). Re-uses the existing module-level model singleton in
   :mod:`server.query_encoder` — this module just *forces* the eager
   load at startup so :func:`server.query_encoder.encode_query` does
   not pay the cold-load cost on the first request.
2. The **LanceDB chunks-table handle**, opened ONCE per pinned
   ``corpus_version`` and cached for process lifetime. The brief is
   load-bearing on this — the server never auto-switches versions;
   restart the process to pick up a new corpus.
3. The **BGE-reranker-v2-m3** model handle, when
   ``ARXMCP_ENABLE_RERANK=true``. Loaded eagerly at startup (per
   ``/readyz`` semantics — see synthesis D3); failure on load is
   FATAL (synthesis D6).

**Two-tier concurrency model (synthesis D2).** Concurrency is bounded
at TWO layers that compose:

- :data:`Resources.embed_semaphore` is an
  ``asyncio.Semaphore(max_concurrent_embeddings=8)`` that bounds
  DISTINCT-query parallelism. Acquired by callers BEFORE invoking
  :func:`server.query_encoder.encode_query`. Without this, a
  thundering herd of N distinct queries would all queue inside the
  single-worker BGE-M3 executor; the semaphore caps N at the chosen
  bound and prevents event-loop slot starvation.
- :func:`server.query_encoder.encode_query` carries an internal
  singleflight that collapses SAME-query duplicates: N concurrent
  agents asking the identical query produce ONE forward pass.

The brief's "Singleflight asyncio class wraps the embedder" deliverable
is **already done** by ``query_encoder``. This module adds the
semaphore (the new knob) plus the reranker-side singleflight (which
does not yet exist; the embedder is the only model in the
standalone-encoder line today).

**Cold-start contract.** The :func:`Resources.startup` coroutine
either succeeds and returns a fully-warm ``Resources`` instance, or
raises a clear exception that the lifespan should propagate (uvicorn
exits non-zero, ``/readyz`` never opens). Specifically:

- Missing ``corpus-version.json`` → :class:`CorpusNotIngestedError`
  (synthesis D5: refuse to start; ingest must run first).
- Reranker model load failure when ``enable_rerank=True`` →
  :class:`RerankerUnavailableError` (synthesis D6: trust the
  operator's choice; refuse to start).
- LanceDB open failure → propagates the underlying exception
  (``FileNotFoundError`` for missing path, ``ValueError`` for an
  unknown version per :func:`server.corpus.open_chunks_table`).

The single-worker BGE-M3 executor in :mod:`server.query_encoder` is
shut down via :func:`server.query_encoder.shutdown_executor` from
:meth:`Resources.shutdown` — that hook was specifically designed to
be called from a lifespan-shutdown / SIGTERM path (closes F4 from
the E03_S03 critique).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from server.config import Config
from server.corpus import (
    CorpusVersionInfo,
    DegradedState,
    open_chunks_table_with_fallback,
    read_corpus_version,
)
from server.query_encoder import (
    _get_model,
    _get_tokenizer,
    shutdown_executor,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ResourceStartupError(RuntimeError):
    """Base class for any startup-time error that should refuse to
    open ``/readyz``. Lifespan catches this, logs ``FATAL: ...``, and
    re-raises so uvicorn exits non-zero."""


class CorpusNotIngestedError(ResourceStartupError):
    """Raised when ``corpus-version.json`` is absent at startup.

    Synthesis D5: the server REFUSES TO START on cold-start. The
    "live-tip fallback" path that :func:`server.corpus.read_corpus_version`
    supports is for the eval harness, not the long-running server.
    Run the ingest pipeline first, then start the server.
    """


class RerankerUnavailableError(ResourceStartupError):
    """Raised when ``ARXMCP_ENABLE_RERANK=true`` and reranker model
    load fails.

    Synthesis D6: trust the operator's choice. Falling back to
    "rerank disabled even though config said enabled" is a foot-shot
    for the eval harness and would produce confusing nDCG
    regressions.
    """


# ---------------------------------------------------------------------------
# Singleflight (generic; for the reranker — embedder uses query_encoder)
# ---------------------------------------------------------------------------


class Singleflight:
    """Per-key in-flight-future deduplication.

    Generic version of the embedder-specific singleflight in
    :mod:`server.query_encoder`. The reranker (E07) will be the
    first non-test consumer; for E06_S01 this class ships
    instantiated under :attr:`Resources.rerank_singleflight` but
    unused (no tools registered yet).

    Contract: concurrent calls to :meth:`run` with the same ``key``
    share a single in-flight ``asyncio.Future`` — only one
    ``coro_factory()`` call actually executes. Cancellation on one
    waiter does NOT cancel the shared future (closes F1 from the
    E03_S03 critique — same discipline as the embedder
    singleflight).

    Eviction: the future is removed from the in-flight map ONCE the
    first waiter observes its result. A cache layer atop this is
    out-of-scope (singleflight is dedup, not memoization).
    """

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._dedup_count = 0

    async def run(self, key: str, coro_factory) -> Any:
        """Dispatch ``coro_factory()`` for ``key``, deduplicating
        concurrent callers with the same key.

        ``coro_factory`` is a no-arg callable returning a coroutine
        (NOT a coroutine itself). The factory is invoked at most
        once per in-flight key.

        **Cancellation safety (closes F3 from the E06_S01 critique).**
        We submit the factory's coroutine as a separate
        :class:`asyncio.Task` and have BOTH the slow-path runner
        AND every fast-path waiter await it via
        :func:`asyncio.shield`. Cancelling any individual caller
        only unwinds that caller's await; the shared task keeps
        running, sets its result, and remaining waiters receive it.
        This mirrors the ``loop.run_in_executor``-based discipline
        in :func:`server.query_encoder.encode_query` — both isolate
        the underlying work from caller-driven cancellation.
        """
        # Fast path: a future is already in flight for this key.
        async with self._lock:
            inflight_task = self._inflight.get(key)
            if inflight_task is not None:
                self._dedup_count += 1
                # Shield protects THIS caller's cancellation from
                # propagating to the shared task; the shared task
                # keeps running.
                return await asyncio.shield(inflight_task)
            # Slow path: WE schedule the task. Create the task
            # FIRST, then register it under the key so concurrent
            # fast-path lookups see it.
            task = asyncio.get_running_loop().create_task(coro_factory())
            self._inflight[key] = task

        # Eviction is best-effort: schedule it via the task's done
        # callback so it fires once even if the slow-path caller is
        # cancelled (the task itself runs to completion under the
        # shield).
        def _evict(_t: asyncio.Task) -> None:
            self._inflight.pop(key, None)

        task.add_done_callback(_evict)
        # The slow-path caller awaits the same shielded task as fast-
        # path waiters. ``asyncio.shield`` here lets the slow caller
        # be cancelled without killing the underlying task — other
        # waiters still get their result.
        return await asyncio.shield(task)

    @property
    def dedup_count(self) -> int:
        """Total number of fast-path cache hits since process start."""
        return self._dedup_count


# ---------------------------------------------------------------------------
# Resources — the lifecycle container
# ---------------------------------------------------------------------------


@dataclass
class Resources:
    """Process-wide state for the FastAPI app.

    Attached to ``app.state.resources`` by the lifespan in
    :mod:`server.main`. Every request handler reaches into this
    object to acquire the embedding semaphore, look up the LanceDB
    table handle, etc.

    Construct via :meth:`startup`; destroy via :meth:`shutdown`. Do
    NOT call ``__init__`` directly outside tests.
    """

    config: Config
    corpus_info: CorpusVersionInfo
    chunks_table: Any  # lancedb.table.Table — typed via duck-shape to avoid heavy import in tests
    embed_semaphore: asyncio.Semaphore
    rerank_semaphore: asyncio.Semaphore
    rerank_singleflight: Singleflight
    reranker_model: Any | None = None  # populated when enable_rerank=True
    # server.retrieval.BM25Phase; duck-typed to keep this import light.
    bm25_phase: Any | None = None
    # server.retrieval.ANNPhase; duck-typed (E07_S02). Phase-2 dual-ANN
    # retrieval over embedding_stmt + embedding_proof columns plus RRF
    # fusion with the BM25 candidates from ``bm25_phase``.
    ann_phase: Any | None = None
    # server.retrieval.RerankPhase; duck-typed (E07_S03). Phase-3
    # cross-encoder reranker over the ANNPhase top-50 candidates,
    # gated by ARXMCP_ENABLE_RERANK (default off). On-path uses the
    # rerank_singleflight + rerank_semaphore for two-tier concurrency.
    rerank_phase: Any | None = None
    # server.cache.RetrievalCache (E08_S03). 3-tier retrieval cache
    # singleton: SQLite-backed Tier-1 (exact-query memo), in-process
    # FAISS Tier-2 (semantic-query memo at cosine ≥0.97), in-process
    # Tier-3 (rerank-set memo). Initialized in ``startup()`` AFTER the
    # corpus version is pinned (Tier-1 keys depend on it). Closed in
    # ``shutdown()`` so the SQLite file is flushed cleanly.
    cache: Any | None = None
    # Per-paper definitions table (E10_S01). ``None`` when the corpus
    # has no preamble index — ``get_definitions`` degrades gracefully
    # to an empty-result response with ``index_status="absent"``.
    definitions_table: Any | None = None
    # Per-equation table (E10_S03). ``None`` when the corpus has no
    # equation index — ``find_equation`` degrades gracefully to the
    # dense-only path with ``retrieval_mode="dense_only_fallback"`` for
    # MathML inputs or ``"dense_only_stmt_fallback"`` for LaTeX inputs.
    equations_table: Any | None = None
    # Theorem-name SQLite FTS5 store (E10_S02). ``None`` when the
    # corpus has not been indexed yet — ``find_lemma_by_name``
    # degrades gracefully to the legacy in-memory scan over the
    # chunks table with ``retrieval_mode="in_memory_scan_fallback"``.
    theorem_names_db: Any | None = None
    process_start_time_seconds: float = field(default_factory=time.time)
    warm: bool = False
    #: Failure-mode degradation marker (E14_S05 D2). ``None`` on
    #: the happy path. Set to a :class:`server.corpus.DegradedState`
    #: when ``open_chunks_table_with_fallback`` activated the N-1
    #: fallback. Read by :func:`server.health.readyz` (degraded body)
    #: and by ``server.observability.metrics.DEGRADED_MODE_ACTIVE``
    #: scrape refresh.
    degraded: DegradedState | None = None

    # ------------------------------------------------------------------
    # Startup / shutdown
    # ------------------------------------------------------------------

    @classmethod
    async def startup(cls, config: Config) -> Resources:
        """Eagerly load every long-lived resource.

        Order of operations (load-bearing — failures earlier in the
        chain should not leave half-initialized state behind):

        1. Read ``corpus-version.json`` (raise
           :class:`CorpusNotIngestedError` on absent).
        2. Open LanceDB chunks table at the pinned version. Per the
           ``server.corpus.open_chunks_table`` contract, the table
           handle is fresh; we cache it for process lifetime and
           never re-checkout.
        3. Eager-load BGE-M3 (forces ``query_encoder._get_model()``
           to populate its module-level singleton; subsequent
           ``encode_query`` calls hit the cached model).
        4. If ``enable_rerank=True``, load the reranker model (raise
           :class:`RerankerUnavailableError` on any failure).
        5. Build the asyncio primitives (semaphores +
           reranker-singleflight). Cheap; no failure mode.
        6. Set ``warm = True``. ``/readyz`` flips to 200 only after
           this returns successfully.
        """
        # 1. Corpus marker — REFUSE TO START on absent (synthesis D5).
        corpus_info = read_corpus_version(config.lancedb_path)
        if corpus_info is None:
            marker = Path(config.lancedb_path) / "corpus-version.json"
            raise CorpusNotIngestedError(
                f"corpus-version.json not found at {marker}; "
                f"run the ingest pipeline first. The server "
                f"refuses to start on a cold-start corpus state."
            )
        logger.info(
            "Resources.startup: pinning corpus_version=%d (paper_count=%d, "
            "chunk_count=%d, chunker=%s, embedder=%s)",
            corpus_info.version,
            corpus_info.paper_count,
            corpus_info.chunk_count,
            corpus_info.chunker_version,
            corpus_info.embedder_version,
        )

        # 2. LanceDB handle — open ONCE at the pinned version with
        # E14_S05 D2 fallback discipline. ``open_chunks_table_with_fallback``
        # tries the live tip first; on corruption (broad catch — see
        # the function docstring) retries at ``version - 1``. Returns
        # the table handle + a DegradedState marker (None on the
        # happy path) so the lifespan can surface degraded state via
        # ``/readyz``.
        loop = asyncio.get_running_loop()
        chunks_table, degraded = await loop.run_in_executor(
            None,
            lambda: open_chunks_table_with_fallback(
                lancedb_path=config.lancedb_path,
                version=corpus_info.version,
            ),
        )
        if degraded is not None:
            logger.warning(
                "Resources.startup: LanceDB OPENED IN DEGRADED MODE — "
                "live tip version %d failed; serving fallback "
                "version %d (reason=%s). See "
                "docs/ops/failure-modes.md#lancedb-corruption.",
                degraded.original_version,
                degraded.fallback_version,
                degraded.reason,
            )
        else:
            logger.info(
                "Resources.startup: opened LanceDB chunks at version=%d",
                corpus_info.version,
            )

        # 3. Eager BGE-M3 load (forces query_encoder's singletons to
        #    populate; subsequent calls hit cached model + tokenizer).
        await loop.run_in_executor(None, _get_tokenizer)
        await loop.run_in_executor(None, _get_model)
        logger.info("Resources.startup: BGE-M3 embedder warm")

        # 4. Reranker — only when enabled (synthesis D6: refuse on
        #    failure, do not silently disable).
        reranker_model: Any | None = None
        if config.enable_rerank:
            reranker_model = await _load_reranker_or_raise()
            logger.info("Resources.startup: BGE-reranker-v2-m3 warm")

        # 4b. BM25 Phase 1 (E07_S01). Loads the per-corpus-version
        # ``bm25.pkl`` artifact built by ``ingest.bm25_indexer``;
        # auto-builds if missing (closes E04_S04 H1). Startup path
        # opens via fstat-then-load to close TOCTOU (E07_S01 F1),
        # checks the parent directory (F2), and cross-checks the
        # chunk_ids against the LIVE LanceDB table (F4) so a
        # tampered or stale artifact is rejected at startup rather
        # than producing phantom candidates. Failure raises
        # :class:`server.retrieval.BM25IndexUnavailableError` which
        # propagates through the lifespan's broad exception
        # handler — server refuses to open ``/readyz``.
        from server.retrieval import BM25Phase

        # Materialize the live chunk_id set from the table we just
        # opened in step 2. The full scan is bounded by corpus size
        # and is the same I/O pattern build_bm25_index uses.
        live_chunk_ids = set(
            chunks_table.to_arrow().column("chunk_id").to_pylist()
        )
        bm25_phase = await BM25Phase.startup(
            lancedb_path=config.lancedb_path,
            corpus_version=corpus_info.version,
            live_chunk_ids=live_chunk_ids,
        )
        logger.info(
            "Resources.startup: BM25Phase warm (corpus_size=%d)",
            bm25_phase.corpus_size,
        )

        # 4c. ANN Phase 2 (E07_S02). Cheap construction — just caches
        # the chunks_table reference. The two HNSW indexes were built
        # by ``ingest.store.write_chunks`` (one per embedding column);
        # this phase just queries them at request time. Fuses with
        # ``bm25_phase``'s candidates via RRF.
        from server.retrieval import ANNPhase

        ann_phase = ANNPhase(chunks_table=chunks_table)
        logger.info("Resources.startup: ANNPhase ready")

        # 5. Concurrency primitives.
        embed_semaphore = asyncio.Semaphore(config.max_concurrent_embeddings)
        rerank_semaphore = asyncio.Semaphore(config.max_concurrent_reranks)
        rerank_singleflight = Singleflight()

        # 5b. Phase-3 RerankPhase (E07_S03). Gated by
        # ARXMCP_ENABLE_RERANK (default off). On the off-path the
        # phase is constructed with model_handle=None and rerank()
        # is a passthrough — no model load required for v1
        # (Tier-0/1 deployments). On the on-path the model_handle
        # carries the (model, tokenizer) pair from step 4.
        from server.retrieval.rerank import RerankPhase

        rerank_phase = RerankPhase(
            chunks_table=chunks_table,
            rerank_singleflight=rerank_singleflight,
            rerank_semaphore=rerank_semaphore,
            enabled=config.enable_rerank,
            model_handle=reranker_model,
        )
        logger.info(
            "Resources.startup: RerankPhase ready (enabled=%s)",
            config.enable_rerank,
        )

        # 5c. Reranker warm-up dummy inference (E14_S05 D3). The
        # brief's failure-mode table calls for explicit pre-warming
        # at server startup ("Reranker model load slow on cold
        # start: Pre-warm at server startup; readiness probe blocks
        # shim until ready" — `.claude/notes/08-security-observability-ops.md`).
        # Run a single batched forward pass over the first 10
        # chunks of the table BEFORE /readyz opens. Deterministic
        # slice (not random) so the startup-time signal is stable
        # across restarts. Off-loaded to the executor — the
        # cross-encoder forward pass is a synchronous C++ kernel
        # call.
        if config.enable_rerank and reranker_model is not None:
            try:
                # F4 rectification (E14_S05 adversary critique): the
                # prior implementation materialised the FULL chunks
                # table via ``to_arrow()`` and discarded 99.99% of it.
                # For a 200K-chunk corpus that's hundreds of MB of
                # peak allocation at the moment the disk-free
                # sentinel is also writing — wasteful and a real
                # interaction hazard on a constrained workstation.
                # ``take_offsets`` is the bounded-scan primitive.
                total_rows = chunks_table.count_rows()
                limit = min(10, total_rows)
                if limit > 0:
                    warmup_arrow = chunks_table.take_offsets(
                        list(range(limit))
                    ).to_arrow()
                    warmup_bodies = warmup_arrow.column("body_text").to_pylist()
                    # F10 rectification: use a query that includes a
                    # Unicode character (étale) so the BPE tokenizer's
                    # non-ASCII path is warmed alongside the ASCII one.
                    # Real production queries contain Unicode (LaTeX
                    # accents, Greek symbols); the warm-up should
                    # exercise the same code paths.
                    warmup_query = "étale cohomology warmup"
                    await loop.run_in_executor(
                        None,
                        lambda: _warmup_rerank_pass(
                            reranker_model, warmup_query, warmup_bodies
                        ),
                    )
                    logger.info(
                        "Resources.startup: reranker warmed via "
                        "%d-chunk dummy inference (best-effort; the "
                        "server starts anyway if warm-up fails — see "
                        "F9 in the E14_S05 critique)",
                        len(warmup_bodies),
                    )
                else:
                    logger.info(
                        "Resources.startup: reranker warm-up skipped "
                        "(no chunks in corpus yet)"
                    )
            except Exception as exc:  # noqa: BLE001 — non-fatal
                # F9 rectification: log message now explicitly says
                # "best-effort; server starts anyway" so an operator
                # reading the log understands the warm-up is non-fatal.
                logger.warning(
                    "Resources.startup: reranker warm-up failed (%s); "
                    "server starts anyway (best-effort warm-up). The "
                    "first real request will pay the cold-start cost.",
                    exc,
                )

        # 6. Retrieval cache (E08_S03). 3-tier cache singleton —
        # SQLite-backed Tier-1, in-process FAISS Tier-2, in-process
        # LRU Tier-3. Pinned to ``corpus_info.version`` so a corpus
        # bump unreachable-izes prior entries by hash construction.
        # The SQLite file at ``config.cache_db_path`` is opened (or
        # created) here; unexpired rows are loaded into the in-process
        # mirror.
        from server.cache import RetrievalCache, set_cache

        retrieval_cache = await RetrievalCache.open(
            cache_db_path=config.cache_db_path,
            corpus_version=corpus_info.version,
        )
        set_cache(retrieval_cache)
        logger.info(
            "Resources.startup: RetrievalCache warm "
            "(corpus_version=%d, sqlite=%s)",
            corpus_info.version,
            config.cache_db_path,
        )

        # 6b. Definitions table (E10_S01). Optional handle: the table
        # is created lazily by the indexer (`ingest.index_definitions`)
        # and only opened here if it already exists. Missing-table is
        # not an error — the get_definitions handler reports
        # ``index_status="absent"`` until the indexer runs.
        #
        # F7 (E10_S03 critique) — share ONE ``lancedb.connect`` across
        # both optional tables. The previous code opened two distinct
        # Database handles to the same directory; LanceDB's idiom is
        # one shared connection per process, multiple open_table calls
        # on top of it. Negligible perf today; matters if a third
        # optional table joins the pattern.
        definitions_table: Any | None = None
        equations_table: Any | None = None
        try:
            import lancedb

            from ingest.schema import (
                DEFINITIONS_TABLE_NAME,
                EQUATIONS_TABLE_NAME,
            )

            db_conn = await loop.run_in_executor(
                None,
                lambda: lancedb.connect(str(Path(config.lancedb_path).resolve())),
            )

            # 6b-i. Definitions table. Try open_table directly rather
            # than relying on a version-fragile table-listing API.
            # LanceDB raises ``ValueError`` (and on some versions
            # ``FileNotFoundError``) when the table is absent; either
            # is the cue to skip.
            try:
                definitions_table = await loop.run_in_executor(
                    None,
                    lambda: db_conn.open_table(DEFINITIONS_TABLE_NAME),
                )
                logger.info(
                    "Resources.startup: opened LanceDB %s table",
                    DEFINITIONS_TABLE_NAME,
                )
            except (ValueError, FileNotFoundError):
                logger.info(
                    "Resources.startup: %s table not present; "
                    "get_definitions will return index_status=absent",
                    DEFINITIONS_TABLE_NAME,
                )

            # 6b-ii. Equations table (E10_S03). Same pattern —
            # missing table is normal at v1 because the equation
            # atom extractor is deferred. The find_equation handler
            # degrades gracefully when this is None.
            try:
                equations_table = await loop.run_in_executor(
                    None,
                    lambda: db_conn.open_table(EQUATIONS_TABLE_NAME),
                )
                logger.info(
                    "Resources.startup: opened LanceDB %s table",
                    EQUATIONS_TABLE_NAME,
                )
            except (ValueError, FileNotFoundError):
                logger.info(
                    "Resources.startup: %s table not present; "
                    "find_equation will use dense-only fallback for "
                    "MathML inputs",
                    EQUATIONS_TABLE_NAME,
                )
        except Exception as exc:  # noqa: BLE001 — both tables are non-critical
            # Optional tables are enrichments, not hard requirements.
            # Log but do not block server startup.
            logger.warning(
                "Resources.startup: could not open optional tables: %s",
                exc,
            )

        # 6d. Theorem-names SQLite FTS5 store (E10_S02). Same lazy-
        # open contract as the LanceDB optional tables — missing
        # file is normal until the indexer runs. The find_lemma_by_name
        # handler falls back to in-memory scan on absent store.
        theorem_names_db: Any | None = None
        try:
            from server.theorem_names_store import TheoremNamesStore

            tdb_path = Path(config.theorem_names_db_path)
            if tdb_path.exists():
                theorem_names_db = await TheoremNamesStore.open(tdb_path)
                # F5 (E10_S02 critique) — log the row count so an
                # empty store (caused by a recent schema bump or a
                # never-completed first ingest) is distinguishable
                # from a populated one. An empty store + cold corpus
                # would otherwise be silently indistinguishable from
                # "no named theorems anywhere in the corpus."
                row_count = await theorem_names_db.row_count()
                logger.info(
                    "Resources.startup: opened theorem_names SQLite store "
                    "at %s (rows=%d)",
                    tdb_path, row_count,
                )
                if row_count == 0:
                    logger.warning(
                        "Resources.startup: theorem_names store is EMPTY. "
                        "Re-run `python -m ingest.index_theorem_names` "
                        "to populate it; until then find_lemma_by_name "
                        "returns zero matches.",
                    )
            else:
                logger.info(
                    "Resources.startup: theorem_names DB not present at %s; "
                    "find_lemma_by_name will use in-memory scan fallback",
                    tdb_path,
                )
        except Exception as exc:  # noqa: BLE001 — non-critical enrichment
            logger.warning(
                "Resources.startup: could not open theorem_names store: %s",
                exc,
            )

        instance = cls(
            config=config,
            corpus_info=corpus_info,
            chunks_table=chunks_table,
            embed_semaphore=embed_semaphore,
            rerank_semaphore=rerank_semaphore,
            rerank_singleflight=rerank_singleflight,
            reranker_model=reranker_model,
            bm25_phase=bm25_phase,
            ann_phase=ann_phase,
            rerank_phase=rerank_phase,
            cache=retrieval_cache,
            definitions_table=definitions_table,
            equations_table=equations_table,
            theorem_names_db=theorem_names_db,
            warm=True,
            degraded=degraded,
        )
        logger.info("Resources.startup: warm")
        return instance

    async def shutdown(self) -> None:
        """Close LanceDB, flush metrics, and shut the BGE-M3
        executor.

        The brief mandates a 30-second drain on shutdown; the
        lifespan in :mod:`server.main` wraps THIS call in
        ``asyncio.wait_for(..., timeout=30)`` so a stuck shutdown
        does not block ``docker stop`` past its grace period.

        :func:`server.query_encoder.shutdown_executor` is the hook
        F4-from-E03_S03 specifically added for this; calling it
        with ``wait=True`` lets in-flight encodes finish before the
        thread-pool tears down.
        """
        # LanceDB Table objects do not expose an explicit close in
        # the current API; releasing the reference is sufficient
        # (the underlying connection cleans up at GC). We mark the
        # resource as un-warm so /readyz flips back to 503 if any
        # straggler request hits it.
        self.warm = False
        # E08_S03: close the cache singleton FIRST so any in-flight
        # writes flush to SQLite before the executor drain. The cache
        # is performance-not-correctness; a close error is logged and
        # swallowed.
        if self.cache is not None:
            try:
                await self.cache.close()
            except Exception:  # noqa: BLE001
                logger.exception("Resources.shutdown: cache close failed")
        # E10_S02: close the theorem-names SQLite store. Same
        # discipline — best-effort close, swallow errors (correctness
        # is preserved by SQLite's WAL on the next open).
        if self.theorem_names_db is not None:
            try:
                await self.theorem_names_db.close()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Resources.shutdown: theorem_names_db close failed"
                )
        # Drop the module-level cache reference so post-shutdown calls
        # to ``get_cache()`` return ``None`` (handlers fall through to
        # the underlying pipeline).
        from server.cache import set_cache

        set_cache(None)
        shutdown_executor(wait=True, cancel_futures=False)
        logger.info("Resources.shutdown: BGE-M3 executor drained")

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def is_resource_warm(self, name: str) -> bool:
        """Per-resource warm-state for ``/metrics`` exposition.

        Returns 1 (truthy) when the named resource is loaded and
        usable, 0 otherwise. ``name`` ∈ {"embedder", "lancedb",
        "reranker"}; unknown names raise ``KeyError`` so a typo in a
        future metric label fires loudly.
        """
        if name == "embedder" or name == "lancedb":
            return self.warm
        if name == "reranker":
            return self.warm and self.reranker_model is not None
        raise KeyError(
            f"unknown resource {name!r}; expected one of "
            f"{{'embedder', 'lancedb', 'reranker'}}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _warmup_rerank_pass(
    reranker_model: Any, query: str, bodies: list[str]
) -> None:
    """Run a single batched forward pass through the reranker to
    warm caches (model weights into CPU/GPU memory, tokenizer
    state, etc.). E14_S05 D3.

    Called from :meth:`Resources.startup` before ``/readyz``
    opens; the cross-encoder's first inference pays the full cold-
    start cost (~0.5-2s on CPU) which the readiness probe should
    not block individual handler requests on.

    ``reranker_model`` is the `(model, tokenizer)` tuple from
    :func:`_load_reranker_or_raise`. Imported here lazily because
    the rerank module pulls heavy deps and we don't want to
    require it on the disabled-rerank path.
    """
    from server.retrieval.rerank import _rerank_sync  # noqa: PLC0415

    model, tokenizer = reranker_model
    # Discard the scores — we just want the model paths primed.
    _rerank_sync(model, tokenizer, query, bodies)


async def _load_reranker_or_raise() -> Any:
    """Load the BGE-reranker-v2-m3 model + tokenizer; raise on failure.

    Synthesis D6: when ``enable_rerank=True``, model load failure is
    FATAL. Returns ``(model, tokenizer)`` — both objects opaque to
    this module; consumed by :class:`server.retrieval.rerank.RerankPhase`.

    Off-loaded to the default executor since
    :meth:`AutoModelForSequenceClassification.from_pretrained` is
    sync I/O (downloads + reads safetensors). Mirrors the discipline
    in ``Resources.startup`` for the LanceDB handle and BGE-M3
    embedder loads.

    Threat 6 (``08-security-observability-ops.md``): pass
    ``trust_remote_code=False`` so a tampered ``modeling_*.py`` in
    the cache cannot achieve RCE, and ``revision=BGE_RERANKER_COMMIT_SHA``
    so transformers fetches the pinned ref (rather than HEAD).
    """
    from server.model_loader import (
        assert_no_bin_in_snapshot,
        resolve_trust_remote_code,
        validate_model_revision,
    )
    from server.retrieval.rerank import (
        BGE_RERANKER_COMMIT_SHA,
        RERANKER_MODEL_ID,
        RerankerHandle,
        maybe_log_sha_drift,
    )

    # E13_S06 Threat 6: refuse a non-SHA pin before any network
    # I/O. Validated outside ``_load`` so the error surfaces on the
    # current event loop without a thread-pool hop.
    validate_model_revision(
        BGE_RERANKER_COMMIT_SHA, model_name=RERANKER_MODEL_ID
    )
    # F1 fix (E13_S06 adversary): resolve the trust-remote-code
    # opt-in BEFORE the executor hop so both Threat-6 guards (SHA
    # validation + escape-hatch env read) operate on a single
    # process-state snapshot. Reading the env var inside ``_load``
    # would let an external mutator (test setenv, signal handler)
    # change the resolved value between the two guards, leaving
    # the post-load WARN log out of sync with what transformers
    # was actually told.
    trc = resolve_trust_remote_code()

    def _load() -> Any:
        from transformers import (  # noqa: PLC0415
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        try:
            tokenizer = AutoTokenizer.from_pretrained(
                RERANKER_MODEL_ID,
                revision=BGE_RERANKER_COMMIT_SHA,
                trust_remote_code=trc,
                # Tokenizer files are JSON / sentencepiece / vocab —
                # no pickle surface. The kwarg has no effect on the
                # tokenizer load but is documented for symmetry with
                # the model load below.
            )
            model = AutoModelForSequenceClassification.from_pretrained(
                RERANKER_MODEL_ID,
                revision=BGE_RERANKER_COMMIT_SHA,
                trust_remote_code=trc,
                # F1 fix from the E07_S03 critique: enforce safetensors
                # to close the pickle-RCE vector. Threat 6 in
                # 08-security-observability-ops.md mandates "Use
                # safetensors format only; refuse .bin / pickle weights."
                # If a future SHA upgrade ships only .bin, this
                # raises loudly — the correct security failure mode.
                use_safetensors=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise RerankerUnavailableError(
                f"BGE-reranker-v2-m3 failed to load (revision="
                f"{BGE_RERANKER_COMMIT_SHA}): {exc}. ENABLE_RERANK=true "
                f"requires the model to be available; either set "
                f"ENABLE_RERANK=false (default) or fix the load. "
                f"Note: use_safetensors=True is enforced (Threat 6); "
                f"a .bin-only model upgrade will fail this load."
            ) from exc
        # E13_S06: defensive post-load check — ``use_safetensors=True``
        # silently falls back to ``.bin`` in some transformers
        # versions when no safetensors file exists in the repo. The
        # on-disk snapshot check catches that fallback before the
        # model is exposed to inference.
        assert_no_bin_in_snapshot(RERANKER_MODEL_ID, BGE_RERANKER_COMMIT_SHA)
        model.eval()
        # F9 fix from the E07_S03 critique: return as a NamedTuple
        # so destructuring is explicit and a future 3-element
        # addition fails with a clear error.
        return RerankerHandle(model=model, tokenizer=tokenizer)

    loop = asyncio.get_running_loop()
    handle = await loop.run_in_executor(None, _load)
    # Brief: SHA drift is a WARNING, not FATAL. Logged after the
    # successful load (the load itself enforces ``revision=`` by
    # fetching from the Hub if the local cache mismatches).
    maybe_log_sha_drift(BGE_RERANKER_COMMIT_SHA)
    return handle


__all__ = [
    "CorpusNotIngestedError",
    "RerankerUnavailableError",
    "ResourceStartupError",
    "Resources",
    "Singleflight",
]
