"""Server-process lifecycle resources (E06_S01).

Owns the three expensive, long-lived objects that the
``arxmcp-server`` process loads once and reuses for every request:

1. The **BGE-M3 embedder** (loaded into CPU/GPU memory; ~1.5 GB on
   CPU). Re-uses the existing module-level model singleton in
   :mod:`server.query_encoder` — this module just *forces* the eager
   load at startup so :func:`server.query_encoder.encode_query` does
   not pay the cold-load cost on the first request.
2. The **LanceDB chunks-table handle**, opened per pinned
   ``corpus_version`` and cached. The original brief said the server
   never auto-switches versions and a restart was required to pick up
   a new corpus; **issue #207 changed that**, because the shipped
   ``/ui/`` console has an Ingest button and an operator pressing it
   reasonably expects the next query to see the result. The handle is
   still opened once per version and never ``checkout``-ed in place
   (that would corrupt other readers' views per
   :mod:`server.corpus`) — a version change opens a NEW handle and
   swaps it in via :meth:`Resources._bind_corpus`. See
   :mod:`server.corpus_freshness` for what triggers that and what it
   does not cover.
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
from collections import OrderedDict
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
from server.corpus_freshness import (
    DEFAULT_FRESHNESS_INTERVAL_SECONDS,
    FreshnessGate,
    read_marker_off_loop,
)
from server.query_encoder import (
    _get_model,
    _get_tokenizer,
    shutdown_executor,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: notebook-retrieval-m2 (fork A) — upper bound on the per-call
#: notebook chunks-table registry (:meth:`Resources.notebook_table`).
#: Each slot holds one open LanceDB table handle; an unbounded registry
#: would let a caller cycling synthetic slugs exhaust file descriptors
#: (m2 FM-6). 16 is generous for a single-user workstation that serves a
#: handful of notebooks; eviction is LRU (evict-oldest).
MAX_NOTEBOOK_TABLE_SLOTS = 16


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


def compute_chunk_count_divergence(
    marker_count: int, actual_count: int, tolerance: float
) -> str | None:
    """Return the divergence direction if the live chunk count diverges
    from the marker beyond ``tolerance``, else ``None``
    (corpus-integrity-observability-m2).

    The pure, deterministic core of the startup reconciliation invariant —
    extracted so every edge case is unit-testable without booting the
    server. Returns ``"rows_added"`` (actual > marker), ``"rows_lost"``
    (actual < marker), or ``None`` (within tolerance / not comparable).

    - FM-2: ``actual_count < 0`` is the count-unavailable sentinel →
      ``None`` (caller skips; no false degrade).
    - FM-3: a zero/empty marker never div-by-zeros; ``0`` vs ``0`` is not
      a divergence, ``0`` vs ``>0`` is.
    - FM-4: a 1-row absolute floor stops micro-corpora alarming on a
      single-row delta even when ``tolerance * marker < 1``.
    - FM-6: symmetric in direction — both rows lost and rows added
      diverge.
    """
    if actual_count < 0:
        return None
    if marker_count <= 0:
        diverged = actual_count > 0
    else:
        diverged = abs(actual_count - marker_count) > max(
            1, tolerance * marker_count
        )
    if not diverged:
        return None
    return "rows_added" if actual_count > marker_count else "rows_lost"


def compute_unindexed_rows(table: Any) -> tuple[int, list[str]]:
    """Sum HNSW ``num_unindexed_rows`` across all ANN indexes on ``table``
    (corpus-integrity-observability-m3 / scout CAND-10). Returns
    ``(value, per_index_breakdown)`` where ``value`` is:

    - ``-1`` — could NOT determine: no resolvable ANN index exists (an empty
      ``list_indices()``, or every ``index_stats()`` returned ``None``). A
      never-indexed corpus brute-forces EVERY row, so reporting ``0`` there
      would be a dangerous false-clean (synthesis D2);
    - ``0`` — checked & clean: ≥1 index, all report 0 unindexed rows;
    - ``>0`` — abnormal: some index has rows the ANN graph doesn't cover, so
      ANN queries brute-force over them.

    The pure, deterministic core of the m3 tripwire — extracted so the
    sentinel rule is unit-testable with a fake table without booting the
    server. Index names are DISCOVERED via ``list_indices()`` (never
    hardcoded). Does NOT catch exceptions — the caller's try/except maps an
    API failure to the same ``-1`` sentinel. ``index_stats(name)`` may return
    ``None`` (unknown/dropped index) and is skipped.

    NB lancedb 0.30.2: ``list_indices()`` → ``Iterable[IndexConfig]`` (``.name``);
    ``index_stats(name)`` → ``Optional[IndexStatistics]`` (``.num_unindexed_rows``).
    """
    total = 0
    index_count = 0
    breakdown: list[str] = []
    for cfg in table.list_indices():
        # m3 critique F1: list_indices() ALSO returns SCALAR indexes — e.g. the
        # paper_id BTree built unconditionally by _create_indices'
        # create_scalar_index (live-verified on lancedb 0.30.2:
        # [embedding_stmt_idx(IvfHnswSq), paper_id_idx(BTree)]). A scalar index
        # has no ANN-brute-force relevance, and counting it would defeat the D2
        # sentinel — a corpus whose VECTOR indexes were skipped (empty embedding
        # columns) but which still has the paper_id BTree would falsely report 0
        # ("clean") instead of -1 ("no resolvable ANN index"). Filter to vector
        # index types only (HNSW / IVF families; scalar = BTree/Bitmap/etc.).
        stats = table.index_stats(cfg.name)
        if stats is None:
            continue
        idx_type = (
            getattr(cfg, "index_type", None)
            or getattr(stats, "index_type", "")
            or ""
        ).upper()
        if "HNSW" not in idx_type and "IVF" not in idx_type:
            continue  # non-vector (scalar) index — not an ANN-coverage signal
        index_count += 1
        n = int(stats.num_unindexed_rows)
        total += n
        breakdown.append(f"{cfg.name}={n}")
    if index_count == 0:
        return -1, breakdown
    return total, breakdown


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
    # onboarding-uplift-m4: both nullable in bootstrap mode (when
    # ARXMCP_BOOTSTRAP_MODE=1 and no corpus marker exists). The
    # orchestrator-level stub-check in server.tools._build_bootstrap_envelope
    # handles the None path — handlers never reach corpus_info.version in
    # bootstrap mode.  On the normal (non-bootstrap) path these are always
    # populated by Resources.startup before /readyz opens.
    corpus_info: CorpusVersionInfo | None
    chunks_table: Any | None  # lancedb.table.Table — typed via duck-shape; None in bootstrap mode
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
    # Per-notebook paper-metadata SQLite store (paper-metadata-m2).
    # A ``server.paper_metadata_store.PaperMetadataStore`` when the
    # sibling ``paper_metadata.db`` file exists next to the lancedb
    # dir (hydrated by ``tools/notebook_metadata_backfill.py``);
    # ``None`` otherwise — ``get_paper`` degrades gracefully to the
    # v1 null identity fields with
    # ``metadata_status="synthesized_from_chunks"``. Duck-typed to
    # keep the import off the module-load path.
    paper_metadata_store: Any | None = None
    # Managed Lean 4 REPL subprocess (verification-feedback-m2). A
    # ``server.lean_repl.LeanRepl`` when ``ARXMCP_ENABLE_LEAN=true``;
    # ``None`` (the default) when disabled — no subprocess is spawned
    # and the 7 existing MCP tools are unaffected. Duck-typed to keep
    # ``lean_repl`` off the import path on the disabled (default) path.
    lean_repl: Any | None = None
    process_start_time_seconds: float = field(default_factory=time.time)
    warm: bool = False
    #: Failure-mode degradation marker (E14_S05 D2). ``None`` on
    #: the happy path. Set to a :class:`server.corpus.DegradedState`
    #: when ``open_chunks_table_with_fallback`` activated the N-1
    #: fallback. Read by :func:`server.health.readyz` (degraded body)
    #: and by ``server.observability.metrics.DEGRADED_MODE_ACTIVE``
    #: scrape refresh.
    degraded: DegradedState | None = None
    #: Live ``chunks_table.count_rows()`` captured once for the
    #: reconciliation + gauge path at startup
    #: (corpus-integrity-observability-m2). ``-1`` sentinel means the
    #: count could not be read (``count_rows()`` raised — FM-2). Read by
    #: :func:`server.health.refresh_metrics_from_singleton_state` to set
    #: the ``arxmcp_corpus_chunk_count_actual`` gauge WITHOUT re-scanning
    #: per ``/metrics`` scrape. Cached, but NOT stale-by-design any more:
    #: issue #207 made :meth:`_bind_corpus` recompute it on every corpus
    #: rebind, so it always describes the corpus whose ``corpus_version``
    #: the envelope is echoing. (Before #207 a rebind was impossible, so
    #: "restart to refresh" was accurate; once the process can re-bind,
    #: a gauge left describing the previous corpus is the same silent
    #: lie #207 closed one layer up.)
    #: (F5: the reranker warm-up block independently calls ``count_rows()``
    #: when ``enable_rerank`` is on — that is a separate concern; do NOT
    #: couple it to this cached value.)
    startup_chunk_count: int = -1
    #: Total HNSW unindexed rows across all ANN indexes, read ONCE at startup
    #: (corpus-integrity-observability-m3 / scout CAND-10). ``-1`` = could not
    #: determine (index API raised, or no ANN index exists); ``0`` = checked &
    #: clean; ``>0`` = abnormal (rows committed without an index rebuild → ANN
    #: brute-forces them). Read by
    #: :func:`server.health.refresh_metrics_from_singleton_state` to set the
    #: ``arxmcp_corpus_unindexed_rows`` gauge WITHOUT re-querying per scrape.
    #: Recomputed on every corpus rebind alongside ``startup_chunk_count``
    #: (issue #207) — see that field's note for why "restart to refresh"
    #: stopped being true.
    startup_unindexed_rows: int = -1
    # notebook-retrieval-m2 (fork A): bounded LRU registry of per-call
    # notebook chunks-tables, keyed by validated slug → (table, info).
    # Lazily opened on the first ``filters.notebook=<slug>`` query and
    # memoized for process lifetime; bounded at MAX_NOTEBOOK_TABLE_SLOTS
    # with evict-oldest (m2 FM-6). The lock serializes the lazy-open so
    # concurrent first-access for the same OR different slugs cannot
    # double-open / leak file descriptors (m2 FM-8). Leading underscores
    # keep these off the public dataclass surface; default_factory means
    # the existing ``cls(...)`` construction in ``startup`` needs no new
    # positional args.
    _notebook_tables: OrderedDict[str, tuple[Any, CorpusVersionInfo]] = field(
        default_factory=OrderedDict
    )
    _notebook_tables_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # issue #207 — corpus-freshness gates. Both are created lazily (on
    # first use, inside a running loop) rather than via default_factory
    # because the throttle interval comes from ``self.config`` and
    # ``FreshnessGate`` builds an ``asyncio.Lock``. Lazy also means the
    # ~40 tests that construct ``Resources(...)`` positionally keep
    # working untouched.
    #
    # ``_corpus_gate`` guards the PROCESS corpus (``config.lancedb_path``
    # — the shared corpus, or one notebook under fork-C
    # ``ARXMCP_NOTEBOOK``). ``_notebook_gates`` holds one gate per
    # memoized per-call notebook table, pruned in lockstep with
    # ``_notebook_tables`` so a caller cycling synthetic slugs cannot
    # grow it without bound (the m2 FM-6 discipline).
    _corpus_gate: Any | None = None
    _notebook_gates: dict[str, Any] = field(default_factory=dict)
    # onboarding-uplift-m4: bootstrap mode support.
    # ``bootstrap_mode_active`` is True only when ARXMCP_BOOTSTRAP_MODE=1
    # AND no corpus marker was present at startup.  Flips to False
    # permanently after ``late_bind`` completes successfully (one-way).
    # Checked by the orchestrator stub-check in server.tools before
    # dispatching handlers; handlers must NOT check this directly.
    bootstrap_mode_active: bool = False
    # _corpus_ready_event REMOVED (onboarding-uplift-m4 F6 rect):
    # no consumer awaits it; the orchestrator stub-check reads the
    # bootstrap_mode_active bool flag. If a future /ui/api/bootstrap-status
    # poll endpoint wants event semantics, re-add it then.

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
        # onboarding-uplift-m4: bootstrap_mode=True + absent marker → skip
        # CorpusNotIngestedError and return a stub instance immediately.
        # bootstrap_mode=True + PRESENT marker → log INFO and ignore the
        # hint (FM-7); continue with normal boot.
        corpus_info = read_corpus_version(config.lancedb_path)
        if corpus_info is None:
            if not config.bootstrap_mode:
                marker = Path(config.lancedb_path) / "corpus-version.json"
                raise CorpusNotIngestedError(
                    f"corpus-version.json not found at {marker}; "
                    f"run the ingest pipeline first. The server "
                    f"refuses to start on a cold-start corpus state. "
                    f"(Operators wanting a fresh-clone wizard flow: set "
                    f"ARXMCP_BOOTSTRAP_MODE=1 or run `make up-wizard`.)"
                )
            # Bootstrap mode: no corpus yet. Build a minimal stub instance
            # and return early — BGE-M3, LanceDB, BM25, cache, Lean are
            # all deferred until late_bind() is called after first ingest.
            logger.info(
                "Resources.startup: bootstrap mode active; no corpus marker "
                "found at %s — MCP tools will return stub-mode envelope until "
                "ingest completes and Resources.late_bind() is called",
                Path(config.lancedb_path) / "corpus-version.json",
            )
            embed_semaphore = asyncio.Semaphore(config.max_concurrent_embeddings)
            rerank_semaphore = asyncio.Semaphore(config.max_concurrent_reranks)
            rerank_singleflight = Singleflight()
            stub = cls(
                config=config,
                corpus_info=None,
                chunks_table=None,
                embed_semaphore=embed_semaphore,
                rerank_semaphore=rerank_semaphore,
                rerank_singleflight=rerank_singleflight,
                warm=False,
                bootstrap_mode_active=True,
            )
            return stub

        if config.bootstrap_mode:
            # FM-7: corpus is already ingested; the flag is a hint, not
            # an override.  Log and continue with normal boot.
            logger.info(
                "Resources.startup: ARXMCP_BOOTSTRAP_MODE=1 requested but "
                "corpus marker already present at %s (version=%d); "
                "booting normally (bootstrap_mode hint ignored)",
                Path(config.lancedb_path) / "corpus-version.json",
                corpus_info.version,
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

        # 2b. Corpus-count reconciliation invariant
        # (corpus-integrity-observability-m2). Compute count_rows() ONCE
        # (O(1) Lance fragment metadata) and cache it on the instance so
        # the /metrics gauges read a startup snapshot, never a per-scrape
        # scan. Reconcile against the marker's chunk_count: a divergence
        # beyond the configured tolerance (with a 1-row absolute floor) is
        # a WARN-and-serve signal — retrieval is unaffected — that flips
        # /readyz to degraded so an operator notices the silent drift the
        # m1 bug class produced.
        #
        # FM-2: count_rows() failure is NON-FATAL — sentinel -1, skip the
        #   check, gauges report -1.0 so operators see the count-miss.
        # FM-7: if the LanceDB N-1 fallback already set ``degraded``
        #   (corpus_corruption — strictly more severe), do NOT clobber it;
        #   skip reconciliation. The cached count is still set either way.
        try:
            startup_chunk_count = await loop.run_in_executor(
                None, chunks_table.count_rows
            )
        except Exception as exc:  # noqa: BLE001 — non-fatal observability
            logger.warning(
                "Resources.startup: count_rows() failed (%s); skipping "
                "chunk_count reconciliation. Retrieval is unaffected.",
                exc,
            )
            startup_chunk_count = -1

        if degraded is not None:
            logger.info(
                "Resources.startup: skipping chunk_count reconciliation "
                "(degraded=%s already active — more severe).",
                degraded.reason,
            )
        else:
            direction = compute_chunk_count_divergence(
                marker_count=corpus_info.chunk_count,
                actual_count=startup_chunk_count,
                tolerance=config.corpus_chunk_count_tolerance,
            )
            if direction is not None:
                logger.warning(
                    "Resources.startup: corpus chunk_count DIVERGED — "
                    "marker=%d actual=%d direction=%s tolerance=%.3f. "
                    "Serving anyway (retrieval unaffected); /readyz will "
                    "report degraded(reason=chunk_count_diverged). Re-run "
                    "ingest to reconcile the marker.",
                    corpus_info.chunk_count,
                    startup_chunk_count,
                    direction,
                    config.corpus_chunk_count_tolerance,
                )
                # D2: fallback_version / original_version carry
                # corpus_corruption semantics and are N/A for a count
                # divergence; use the pinned version for both (no actual
                # version fallback occurred).
                degraded = DegradedState(
                    reason="chunk_count_diverged",
                    fallback_version=corpus_info.version,
                    original_version=corpus_info.version,
                )

        # 2c. HNSW unindexed-rows tripwire (corpus-integrity-observability-m3 /
        # scout CAND-10). _create_indices (ingest/store.py) runs SYNCHRONOUSLY
        # inside write_chunks, so on the normal post-ingest path every ANN index
        # fully covers the table (num_unindexed_rows == 0). A non-zero count
        # therefore means rows were committed without a matching index rebuild
        # (partial write / corruption / a future async-index path) and ANN
        # queries silently brute-force over those rows — correct results, but a
        # silent perf degradation. We surface it as a WARN + the
        # arxmcp_corpus_unindexed_rows gauge (NOT a /readyz degrade: brute-force
        # ANN is still CORRECT, so a 503 would be an over-reaction for a
        # perf-only anomaly).
        #
        # Sentinel discipline (m3 synthesis D2): startup_unindexed_rows is
        #   -1  → could NOT determine (the index API raised, OR no ANN index
        #         exists at all — a never-indexed corpus brute-forces EVERYTHING,
        #         so reporting 0 there would be a dangerous false-clean);
        #    0  → checked & clean (>=1 index, all report 0 unindexed);
        #   >0  → abnormal (some index has unindexed rows).
        # FM-2: any failure is NON-FATAL (-1 + WARN, never abort startup). FM-7:
        # skip entirely when `degraded` is already set (corpus_corruption is more
        # severe — do not clobber). MVCC-safe: index_stats on the version-pinned
        # handle reflects that version's coverage. Index names are DISCOVERED via
        # list_indices() — never hardcoded. Startup-cached and recomputed on
        # every corpus rebind (#207). NB list_indices()/index_stats() are sync I/O →
        # run_in_executor; index_stats(name) can return None → guard.
        if degraded is not None:
            startup_unindexed_rows = -1
            logger.info(
                "Resources.startup: skipping unindexed-rows check "
                "(degraded=%s already active — more severe).",
                degraded.reason,
            )
        else:
            try:
                startup_unindexed_rows, _idx_breakdown = (
                    await loop.run_in_executor(
                        None, compute_unindexed_rows, chunks_table
                    )
                )
            except Exception as exc:  # noqa: BLE001 — non-fatal observability
                startup_unindexed_rows = -1
                logger.warning(
                    "Resources.startup: index_stats()/list_indices() "
                    "unavailable (%s); skipping unindexed-rows check. "
                    "Retrieval is unaffected.",
                    exc,
                )
            else:
                if startup_unindexed_rows > 0:
                    logger.warning(
                        "Resources.startup: %d unindexed HNSW rows detected "
                        "(%s) — ANN queries brute-force over these rows. "
                        "Non-zero is ALWAYS abnormal (partial write / "
                        "corruption); re-run ingest to rebuild the index.",
                        startup_unindexed_rows,
                        ", ".join(_idx_breakdown),
                    )
                elif startup_unindexed_rows < 0:
                    logger.warning(
                        "Resources.startup: no resolvable ANN index found "
                        "(list_indices returned none / index_stats "
                        "unavailable); unindexed-rows coverage UNKNOWN. "
                        "Re-run ingest to build the HNSW indexes.",
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
            bm25_index_root=config.bm25_index_root,
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
        definitions_table, equations_table = await _open_optional_lancedb_tables(
            config, caller="Resources.startup"
        )

        # 6d. Theorem-names SQLite FTS5 store (E10_S02). Same lazy-
        # open contract as the LanceDB optional tables — missing
        # file is normal until the indexer runs. The find_lemma_by_name
        # handler falls back to in-memory scan on absent store.
        theorem_names_db = await _open_theorem_names_store(
            config, caller="Resources.startup"
        )

        # 6e. Per-notebook paper-metadata SQLite store (paper-metadata-m2).
        # Same lazy-open contract as the theorem-names store — the file
        # is created by the backfill CLI, never by the server, so a
        # missing file is normal (un-hydrated notebook, or the shared
        # corpus whose lancedb parent has no metadata sibling). The
        # get_paper handler degrades to synthesized-from-chunks nulls
        # when this is None.
        paper_metadata_store = await _open_paper_metadata_store(config)

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
            paper_metadata_store=paper_metadata_store,
            lean_repl=None,
            warm=True,
            degraded=degraded,
            startup_chunk_count=startup_chunk_count,
            startup_unindexed_rows=startup_unindexed_rows,
        )

        # 6e. Lean REPL subprocess harness (verification-feedback-m2).
        # Only when ARXMCP_ENABLE_LEAN=true. Mirrors the enable_rerank
        # discipline (step 4): when the operator opts in, an
        # unresolvable toolchain is FATAL — LeanRepl.spawn_from_config
        # raises LeanUnavailableError (a ResourceStartupError), the
        # lifespan's broad except propagates it, the server refuses to
        # start. On the disabled (default) path nothing is spawned.
        #
        # The spawn runs AFTER `cls(...)` so that a spawn failure can
        # tear down the resources warmed in steps 1-6d (BGE-M3 weights,
        # LanceDB, the retrieval cache, the theorem-names SQLite store)
        # via the instance's own `shutdown()` before re-raising (m2
        # critique F1). Without this, an `enable_lean=true` operator
        # with a broken ARXMCP_LAKE_PATH gets a crash-restart loop that
        # leaks ~1.5 GB of weights and an open SQLite WAL handle every
        # iteration.
        #
        # The spawn itself is instant (asyncio.create_subprocess_exec
        # returns after fork+exec); Lean's kernel loads lazily on the
        # first query — so this does NOT block the lifespan yield.
        if config.enable_lean:
            from server.lean_repl import LeanRepl

            try:
                instance.lean_repl = await LeanRepl.spawn_from_config(config)
            except Exception:
                await instance.shutdown()
                raise
            logger.info(
                "Resources.startup: Lean REPL subprocess spawned "
                "(ARXMCP_ENABLE_LEAN=true)"
            )

        # issue #207: step 1 read the marker, so the freshness gate
        # starts already-satisfied. Without this the FIRST tool call of
        # every process life pays a redundant marker re-read.
        instance._get_corpus_gate().mark_checked()

        logger.info("Resources.startup: warm")
        return instance

    async def _bind_corpus(
        self, config: Config, corpus_info: CorpusVersionInfo, *, caller: str
    ) -> bool:
        """Open every corpus-derived handle at ``corpus_info.version`` and
        swap them onto this instance. Returns ``True`` on success.

        The ONE place the served process binds itself to a corpus after
        startup — shared by :meth:`late_bind` (bootstrap promotion) and
        :meth:`refresh_corpus_if_stale` (issue #207's version-bump
        rebind). Before #207 the second caller did not exist and this
        body lived inline in ``late_bind``; adding a rebind that
        re-implemented it would have made three copies of "how to open a
        corpus" inside this class, and three chances to forget a handle.
        (``startup`` remains a separate path: it also builds the
        semaphores, eager-loads the reranker fatally-on-failure, runs
        the warm-up pass and spawns Lean. Converging the two is a
        worthwhile follow-up, not #207's job.)

        **Build-everything-then-publish.** Every handle is constructed
        BEFORE any field is assigned, so a failure part-way through
        leaves the instance serving the PREVIOUS corpus intact rather
        than half-swapped. This is the onboarding-uplift-m4 F7
        discipline generalized from the cache to the whole binding: a
        rebind either fully lands or fully does not.

        **Never raises.** Failure is logged at ERROR and returns
        ``False``. A rebind is a best-effort convergence step; the
        correct fallback is "keep serving the corpus we have", not "take
        the server down". The caller decides what to do with ``False``.

        **Every heavyweight I/O runs off-loop** — ``run_in_executor``
        for the LanceDB opens and the chunk_id scan, ``asyncio.to_thread``
        inside the SQLite stores' own ``open``. So the single uvicorn
        worker's event loop keeps serving while a rebind runs; the
        triggering request awaits, the loop does not block. That is the
        #208 boundary. (A stray ``mkdir`` and ``Path.exists`` still land
        on the loop inside the store opens — microseconds, pre-existing,
        and not worth threading.) Note that
        ``BM25Phase.startup`` can AUTO-BUILD a missing artifact, which
        is minutes on a large corpus; that is why the request-path
        entry point is throttled and single-flighted, and why the push
        path (ingest completion, already on a background task) is the
        one expected to do this work in practice.
        """
        try:
            loop = asyncio.get_running_loop()

            # 1. LanceDB chunks table at the pinned version, with the
            #    E14_S05 D2 N-1 fallback discipline.
            chunks_table, degraded = await loop.run_in_executor(
                None,
                lambda: open_chunks_table_with_fallback(
                    lancedb_path=config.lancedb_path,
                    version=corpus_info.version,
                ),
            )
            if degraded is not None:
                logger.warning(
                    "%s: LanceDB OPENED IN DEGRADED MODE (reason=%s); "
                    "serving fallback version %d",
                    caller,
                    degraded.reason,
                    degraded.fallback_version,
                )

            # 2. Count reconciliation + HNSW coverage against the NEW
            #    marker. Without this a rebind would leave
            #    ``/metrics`` and ``/readyz`` reporting the PREVIOUS
            #    corpus's numbers next to the new corpus_version — the
            #    same species of silent lie #207 is about. Both are
            #    non-fatal observability (FM-2: -1 sentinel on failure)
            #    and both are skipped when the more-severe
            #    ``corpus_corruption`` degrade is already set (FM-7).
            try:
                startup_chunk_count = await loop.run_in_executor(
                    None, chunks_table.count_rows
                )
            except Exception as exc:  # noqa: BLE001 — non-fatal
                logger.warning(
                    "%s: count_rows() failed (%s); skipping chunk_count "
                    "reconciliation. Retrieval is unaffected.",
                    caller,
                    exc,
                )
                startup_chunk_count = -1

            startup_unindexed_rows = -1
            if degraded is None:
                direction = compute_chunk_count_divergence(
                    marker_count=corpus_info.chunk_count,
                    actual_count=startup_chunk_count,
                    tolerance=config.corpus_chunk_count_tolerance,
                )
                if direction is not None:
                    logger.warning(
                        "%s: corpus chunk_count DIVERGED — marker=%d "
                        "actual=%d direction=%s tolerance=%.3f. Serving "
                        "anyway (retrieval unaffected); /readyz will report "
                        "degraded(reason=chunk_count_diverged).",
                        caller,
                        corpus_info.chunk_count,
                        startup_chunk_count,
                        direction,
                        config.corpus_chunk_count_tolerance,
                    )
                    degraded = DegradedState(
                        reason="chunk_count_diverged",
                        fallback_version=corpus_info.version,
                        original_version=corpus_info.version,
                    )
                else:
                    try:
                        startup_unindexed_rows, _breakdown = (
                            await loop.run_in_executor(
                                None, compute_unindexed_rows, chunks_table
                            )
                        )
                    except Exception as exc:  # noqa: BLE001 — non-fatal
                        startup_unindexed_rows = -1
                        logger.warning(
                            "%s: index_stats()/list_indices() unavailable "
                            "(%s); unindexed-rows coverage UNKNOWN.",
                            caller,
                            exc,
                        )
                    else:
                        if startup_unindexed_rows > 0:
                            logger.warning(
                                "%s: %d unindexed HNSW rows detected (%s) — "
                                "ANN queries brute-force over these rows. "
                                "Re-run ingest to rebuild the index.",
                                caller,
                                startup_unindexed_rows,
                                ", ".join(_breakdown),
                            )

            # 3. BM25 phase. The chunk_id scan is a full column
            #    materialization — off-loop (it was on the event loop in
            #    the pre-#207 ``late_bind``, which was fine at cold start
            #    and is not fine on a live rebind).
            from server.retrieval import ANNPhase, BM25Phase  # noqa: PLC0415

            live_chunk_ids = await loop.run_in_executor(
                None,
                lambda: set(
                    chunks_table.to_arrow().column("chunk_id").to_pylist()
                ),
            )
            bm25_phase = await BM25Phase.startup(
                lancedb_path=config.lancedb_path,
                corpus_version=corpus_info.version,
                live_chunk_ids=live_chunk_ids,
                bm25_index_root=config.bm25_index_root,
            )

            # 4. ANN phase — cheap; just caches the table reference.
            ann_phase = ANNPhase(chunks_table=chunks_table)

            # 5. Retrieval cache, pinned to the NEW version and purging
            #    the previous version's Tier-1 rows (#207). Constructing
            #    a fresh object also empties the Tier-2/Tier-3 semantic
            #    memos, which are NOT version-namespaced and would
            #    otherwise serve pre-bump results.
            from server.cache import RetrievalCache, set_cache  # noqa: PLC0415

            retrieval_cache = await RetrievalCache.open(
                cache_db_path=config.cache_db_path,
                corpus_version=corpus_info.version,
                purge_other_versions=True,
            )

            # 6. Rerank phase. onboarding-uplift-m4 F5: the bootstrap
            #    stub skips the reranker eager-load, so load it here
            #    BEFORE constructing RerankPhase (enabled=True +
            #    model_handle=None would raise). A no-op on the rebind
            #    path, where the model is already resident.
            from server.retrieval.rerank import RerankPhase  # noqa: PLC0415

            if config.enable_rerank and self.reranker_model is None:
                logger.info(
                    "%s: lazily loading BGE-reranker-v2-m3 "
                    "(skipped at bootstrap startup)",
                    caller,
                )
                self.reranker_model = await _load_reranker_or_raise()
                logger.info("%s: BGE-reranker-v2-m3 warm", caller)

            rerank_phase = RerankPhase(
                chunks_table=chunks_table,
                rerank_singleflight=self.rerank_singleflight,
                rerank_semaphore=self.rerank_semaphore,
                enabled=config.enable_rerank,
                model_handle=self.reranker_model,
            )

            # 7. The optional side stores. Re-opened rather than
            #    carried over: an ingest rebuilds them too, and a
            #    handle bound to the previous corpus is exactly the
            #    staleness this seam exists to remove. All three
            #    helpers return None instead of raising.
            definitions_table, equations_table = (
                await _open_optional_lancedb_tables(config, caller=caller)
            )
            theorem_names_db = await _open_theorem_names_store(
                config, caller=caller
            )
            paper_metadata_store = await _open_paper_metadata_store(config)

            # --- Publish. Everything above succeeded; swap atomically
            # from the handlers' point of view (no await between the
            # assignments, so no request can observe a half-swap).
            previous_cache = self.cache
            previous_theorem_names_db = self.theorem_names_db
            previous_paper_metadata_store = self.paper_metadata_store

            set_cache(retrieval_cache)
            self.corpus_info = corpus_info
            self.chunks_table = chunks_table
            self.bm25_phase = bm25_phase
            self.ann_phase = ann_phase
            self.rerank_phase = rerank_phase
            self.cache = retrieval_cache
            self.definitions_table = definitions_table
            self.equations_table = equations_table
            self.theorem_names_db = theorem_names_db
            self.paper_metadata_store = paper_metadata_store
            self.degraded = degraded
            self.startup_chunk_count = startup_chunk_count
            self.startup_unindexed_rows = startup_unindexed_rows
            self.warm = True

        except Exception:  # noqa: BLE001 — see docstring
            logger.exception(
                "%s: corpus bind FAILED; the previously-bound corpus is "
                "still being served. Fix the underlying error and retry "
                "via another ingest run or a restart.",
                caller,
            )
            return False

        # Release the previous corpus's SQLite handles AFTER the swap,
        # so an in-flight request never loses the handle it is using
        # mid-query. Best-effort; a close failure is logged, not fatal.
        if previous_cache is not None and previous_cache is not retrieval_cache:
            await _close_quietly(previous_cache, label="retrieval cache")
        if previous_theorem_names_db is not theorem_names_db:
            await _close_quietly(
                previous_theorem_names_db, label="theorem-names store"
            )
        if previous_paper_metadata_store is not paper_metadata_store:
            await _close_quietly(
                previous_paper_metadata_store, label="paper-metadata store"
            )

        # The marker was read as part of this bind, so the freshness
        # gate's premise is satisfied as of now — no need for the very
        # next request to re-read the file we just consumed. (Redundant
        # when this ran THROUGH the gate, which marks in its own
        # ``finally``; load-bearing for ``late_bind``, which calls here
        # directly.)
        self._get_corpus_gate().mark_checked()

        logger.info(
            "%s: bound corpus_version=%d (paper_count=%d, chunk_count=%d)",
            caller,
            corpus_info.version,
            corpus_info.paper_count,
            corpus_info.chunk_count,
        )
        return True

    async def late_bind(self, config: Config) -> bool:
        """Promote a bootstrap-mode stub to a fully-operational instance.

        Called by :class:`server.ingest_tracker.IngestTaskTracker`'s
        ``on_success_callback`` (via :meth:`on_ingest_complete`) after
        the first ingest subprocess exits 0. Idempotent: returns
        ``False`` immediately if ``bootstrap_mode_active`` is already
        ``False`` (either a previous call succeeded, or the server
        booted normally).

        Failure modes:
        - ``corpus-version.json`` still absent after exit 0 (FM-3): logs
          WARN and returns ``False`` without flipping.  The next ingest
          run will retry.
        - Any other exception (LanceDB open, BM25 build, cache open):
          logged at ERROR by :meth:`_bind_corpus`, NOT propagated.  The
          stub remains active; the operator can trigger a retry via
          another ingest.

        Returns ``True`` on successful promotion, ``False`` otherwise.
        """
        if not self.bootstrap_mode_active:
            return False

        corpus_info = read_corpus_version(config.lancedb_path)
        if corpus_info is None:
            logger.warning(
                "Resources.late_bind: corpus marker still absent after "
                "ingest exited 0 (FM-3); staying in bootstrap mode. "
                "The next successful ingest will retry.",
            )
            return False

        bound = await self._bind_corpus(
            config, corpus_info, caller="Resources.late_bind"
        )
        if not bound:
            logger.error(
                "Resources.late_bind: promotion failed; staying in "
                "bootstrap mode. Retry via another ingest run."
            )
            return False

        # Flip bootstrap_mode_active LAST, after every other field is
        # settled — the orchestrator stub-check in server.tools reads
        # this bool to decide whether to dispatch handlers at all.
        self.bootstrap_mode_active = False
        logger.info(
            "Resources.late_bind: promoted to normal operation "
            "(corpus_version=%d)",
            corpus_info.version,
        )
        return True

    # ------------------------------------------------------------------
    # Corpus freshness (issue #207)
    # ------------------------------------------------------------------

    def _freshness_interval(self) -> float:
        """The configured probe interval, defaulting defensively.

        ``getattr`` rather than a plain attribute read because tests
        install ``SimpleNamespace`` configs that predate this knob; a
        missing field must fall back, not raise on the request path.
        """
        return getattr(
            self.config,
            "corpus_freshness_interval_seconds",
            DEFAULT_FRESHNESS_INTERVAL_SECONDS,
        )

    def _get_corpus_gate(self) -> FreshnessGate:
        """Lazily build the process-corpus freshness gate.

        Lazy (not a ``default_factory``) because the throttle interval
        comes from ``self.config`` and the gate builds an
        ``asyncio.Lock``, which wants a running loop.
        """
        if self._corpus_gate is None:
            self._corpus_gate = FreshnessGate(self._freshness_interval())
        return self._corpus_gate

    def _get_notebook_gate(self, slug: str) -> FreshnessGate:
        """Lazily build the freshness gate for one memoized notebook.

        Callers MUST hold ``self._notebook_tables_lock`` — the gate dict
        is pruned in lockstep with ``_notebook_tables`` under that same
        lock, so an unsynchronized insert here could resurrect a gate
        for a slug that was just evicted.
        """
        gate = self._notebook_gates.get(slug)
        if gate is None:
            gate = FreshnessGate(self._freshness_interval())
            self._notebook_gates[slug] = gate
        return gate

    def _can_refresh_corpus(self) -> bool:
        """Whether this instance is eligible for a corpus rebind.

        Requires a process that actually completed a corpus binding:
        warm, with a live table and marker info. This excludes the
        bootstrap stub (whose path is :meth:`late_bind`, not a rebind)
        and the hand-constructed ``Resources(...)`` doubles that ~40
        unit tests build with ``chunks_table=None`` — neither should
        reach out to the filesystem and try to open a corpus.
        """
        return (
            self.warm
            and not self.bootstrap_mode_active
            and self.chunks_table is not None
            and self.corpus_info is not None
        )

    async def refresh_corpus_if_stale(
        self, config: Config | None = None, *, force: bool = False
    ) -> bool:
        """Re-read the corpus marker; rebind if it names a different
        version than the one being served. Returns ``True`` iff a
        rebind actually landed (issue #207).

        This is the seam ``server/corpus.py``'s cache-invalidation
        contract has always described and never had. Two callers:

        * :func:`server.tools._wrap_with_observability` — the PULL path,
          on every MCP tool dispatch, throttled by
          ``ARXMCP_CORPUS_FRESHNESS_INTERVAL_SECONDS``. Catches ingest
          that happened outside this process.
        * :meth:`on_ingest_complete` — the PUSH path, ``force=True``,
          fired the moment the ``/ui/`` console's Ingest subprocess
          exits 0. This is the one that matters for the reachable
          consequence in #207, and it runs on a background task, so the
          rebind normally completes before any query sees the bump.

        **Any difference triggers a rebind, not just an increase.** The
        contract text said "a higher version", but a restore-from-backup
        lowers it, and serving v5 handles against a v3 dataset on disk
        is the same silent lie in the other direction.

        Never raises: a probe that cannot read the marker, and a rebind
        that fails, both leave the currently-bound corpus in place.
        """
        cfg = config if config is not None else self.config
        if not self._can_refresh_corpus():
            return False

        async def _probe_and_rebind() -> bool:
            info = await read_marker_off_loop(
                cfg.lancedb_path, reader=read_corpus_version
            )
            if info is None:
                # Absent / unreadable / mid-rename. Keep serving.
                return False
            current = self.corpus_info
            if current is not None and info.version == current.version:
                return False
            logger.warning(
                "corpus-freshness: on-disk corpus_version=%d differs from "
                "the served version=%s at %s; rebinding the process corpus. "
                "Until this completes, responses echo the OLD version.",
                info.version,
                current.version if current is not None else "<unbound>",
                cfg.lancedb_path,
            )
            return await self._bind_corpus(
                cfg, info, caller="Resources.refresh_corpus_if_stale"
            )

        result = await self._get_corpus_gate().run_if_due(
            _probe_and_rebind, force=force
        )
        return bool(result)

    async def invalidate_notebook_table(self, slug: str) -> bool:
        """Drop the memoized per-call notebook table for ``slug``.

        Returns ``True`` if an entry was actually dropped. The next
        ``filters.notebook=<slug>`` query re-opens the table through
        :meth:`notebook_table`'s normal lazy path, at whatever version
        the marker names then.

        Also clears the retrieval cache's Tier-2 + Tier-3 memos. Tier-3
        is the one that needs it: its key carries no corpus version, so
        a re-ingest that rewrites a chunk's body under the same
        ``chunk_id`` leaves a reachable, stale rerank memo. Tier-1 and
        (since #204) Tier-2 are version-scoped and self-correcting;
        dropping Tier-2 here just reclaims entries that can never be hit
        again. See
        :meth:`server.cache.RetrievalCache.invalidate_semantic_tiers`.

        Never raises; the caller is an ingest-completion callback whose
        failure must not corrupt the ingest-status row.
        """
        dropped = False
        async with self._notebook_tables_lock:
            if self._notebook_tables.pop(slug, None) is not None:
                dropped = True
            gate = self._notebook_gates.pop(slug, None)
            if gate is not None:
                gate.reset()
        if dropped:
            logger.info(
                "corpus-freshness: dropped the memoized notebook table for "
                "%r; the next query re-opens it at the current version",
                slug,
            )
            cache = self.cache
            invalidate = getattr(cache, "invalidate_semantic_tiers", None)
            if invalidate is not None:
                try:
                    await invalidate()
                except Exception:  # noqa: BLE001 — cache is not correctness
                    logger.exception(
                        "corpus-freshness: clearing the semantic cache tiers "
                        "failed after dropping notebook %r",
                        slug,
                    )
        return dropped

    async def on_ingest_complete(self, config: Config, slug: str) -> None:
        """Corpus-freshness entry point for a completed ingest (#207).

        Wired to :class:`server.ingest_tracker.IngestTaskTracker`'s
        ``on_success_callback``, so it fires the moment the ``/ui/``
        console's Ingest subprocess exits 0 — the operator's most common
        action, and the path along which the pre-#207 server kept
        serving its memoized pre-ingest table while echoing the OLD
        ``corpus_version`` as truth.

        Three steps, in order, each independently safe:

        1. **Bootstrap promotion.** If the process is still a bootstrap
           stub, this ingest is its first corpus — promote it. That
           binds the corpus, so steps 2-3 find nothing to do.
        2. **Drop the memoized notebook table** for ``slug``, whether or
           not this notebook is the process corpus. Cheap, and it is the
           only invalidation a per-call ``filters.notebook`` query needs.
        3. **Force a process-corpus freshness check.** A no-op unless
           the ingested notebook IS what this process serves (fork-C
           ``ARXMCP_NOTEBOOK``, or the shared corpus): the probe reads
           the marker, finds the version unchanged, and returns.

        Never raises — the tracker logs and swallows, but a callback
        that threw would still be a defect at this boundary.
        """
        try:
            if self.bootstrap_mode_active:
                await self.late_bind(config)
            await self.invalidate_notebook_table(slug)
            await self.refresh_corpus_if_stale(config, force=True)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Resources.on_ingest_complete: corpus-freshness handling "
                "failed for slug=%r. The ingest itself succeeded; the "
                "served process may still be bound to the previous corpus "
                "until the next request-path freshness probe or a restart.",
                slug,
            )

    async def _notebook_entry_is_stale(
        self, slug: str, cached: tuple[Any, CorpusVersionInfo]
    ) -> bool:
        """Whether the memoized notebook entry no longer matches disk.

        Called with ``self._notebook_tables_lock`` HELD, so the probe
        and the resulting drop cannot interleave with another caller's
        re-open. The gate adds throttling on top: at most one marker
        read per slug per ``corpus_freshness_interval_seconds``, so a
        hot notebook does not pay a ``stat``+read per query.

        Returns ``False`` — "keep serving" — for every ambiguous case:
        a marker that is absent (a delete/re-create window), unreadable,
        or malformed. Only a marker that parses AND names a different
        version is treated as staleness. Dropping a live table because
        an ingest was mid-atomic-rename would be a worse bug than the
        one this closes.
        """
        _table, info = cached
        gate = self._get_notebook_gate(slug)

        async def _probe() -> bool:
            from tools._notebook_common import (  # noqa: PLC0415
                notebook_lancedb_path,
            )

            try:
                lancedb_path = notebook_lancedb_path(slug)
            except Exception as exc:  # noqa: BLE001
                # The slug validated on entry; a failure here means the
                # notebook directory changed shape underneath us. Keep
                # serving and let the next real open surface it.
                logger.warning(
                    "corpus-freshness: could not resolve the lancedb path "
                    "for notebook %r (%s); keeping the memoized table",
                    slug,
                    exc,
                )
                return False
            fresh = await read_marker_off_loop(
                lancedb_path, reader=read_corpus_version
            )
            if fresh is None or fresh.version == info.version:
                return False
            logger.warning(
                "corpus-freshness: notebook %r bumped from corpus_version=%d "
                "to %d on disk; dropping the memoized table so the next "
                "query reflects the new corpus",
                slug,
                info.version,
                fresh.version,
            )
            return True

        stale = bool(await gate.run_if_due(_probe))
        if stale:
            # A dropped entry invalidates the throttle's premise: the
            # re-opened table is a different binding, so the next access
            # must be free to probe again rather than sit inside the
            # window this probe just opened.
            gate.reset()
            cache = self.cache
            invalidate = getattr(cache, "invalidate_semantic_tiers", None)
            if invalidate is not None:
                try:
                    await invalidate()
                except Exception:  # noqa: BLE001 — cache is not correctness
                    logger.exception(
                        "corpus-freshness: clearing the semantic cache tiers "
                        "failed after detecting a bump on notebook %r",
                        slug,
                    )
        return stale

    async def notebook_table(
        self, slug: str
    ) -> tuple[Any, CorpusVersionInfo]:
        """Return ``(chunks_table, corpus_info)`` for a per-call notebook
        (fork A, notebook-retrieval-m2).

        Lazily opens ``var/arxmcp/notebooks/<slug>/lancedb`` on first use
        and memoizes the handle in a bounded LRU registry
        (:data:`MAX_NOTEBOOK_TABLE_SLOTS`). Subsequent calls for the same
        slug reuse the open handle (no repeated cold-open cost), the same
        startup-bound discipline the shared ``chunks_table`` uses.

        Safety + correctness:

        * **Threat-1 (m2 FM-4).** ``slug`` is validated by
          :func:`tools._notebook_common.validate_slug` (regex + the
          ``notebook_dir`` symlink rejection + containment) BEFORE any
          path construction or I/O. A traversal / symlink / malformed
          slug raises :class:`tools._notebook_common.NotebookError`.
        * **Un-ingested notebook (m2 FM-5a).** A valid slug whose
          ``lancedb`` has no ``corpus-version.json`` marker raises
          :class:`CorpusNotIngestedError` — the SAME typed error the
          shared-corpus startup uses — rather than silently falling
          through to an empty result. The caller converts both to a
          clean ``ValueError`` so the tool surfaces an error, not a 500.
        * **Concurrency (m2 FM-8).** The lazy-open is serialized by
          ``self._notebook_tables_lock`` with a double-check, so two
          concurrent first-accesses cannot both open the table (fd leak)
          nor leave one request holding a closed handle.
        * **Freshness (issue #207).** A memoized entry is NOT trusted
          indefinitely. Before serving one, a throttled probe re-reads
          that notebook's ``corpus-version.json``; a version that no
          longer matches the memoized ``corpus_info`` drops the entry
          and falls through to the re-open path below, so the caller
          gets the new corpus AND the new ``corpus_version`` in its
          envelope. Pre-#207 this method memoized ``(table,
          corpus_info)`` for process lifetime with no re-check, which is
          what let a mid-session ingest go unnoticed.
        """
        # Defer the import: tools._notebook_common is the shared C/A
        # seam (validate_slug + notebook_lancedb_path). Lazy keeps the
        # server→tools import off the module-load path for the common
        # (no-notebook) query.
        from tools._notebook_common import (  # noqa: PLC0415
            notebook_lancedb_path,
            validate_slug,
        )

        # Threat-1 boundary: validate BEFORE any path use. Raises
        # NotebookError on a bad slug; the handler maps it to ValueError.
        validate_slug(slug)

        async with self._notebook_tables_lock:
            cached = self._notebook_tables.get(slug)
            if cached is not None:
                if not await self._notebook_entry_is_stale(slug, cached):
                    # LRU touch: most-recently-used moves to the end.
                    self._notebook_tables.move_to_end(slug)
                    return cached
                # Stale — drop it and fall through to the re-open path
                # below, which reads the marker again and pins the new
                # version. Dropping under the SAME lock that guards the
                # re-open means no concurrent caller can observe the
                # gap.
                self._notebook_tables.pop(slug, None)

            # Miss — open the notebook's lancedb. notebook_lancedb_path
            # re-runs the slug guard (symlink + containment) and builds
            # the path; read the corpus marker, then open the table at
            # the pinned version with the same fallback discipline as the
            # shared corpus (E14_S05 D2).
            lancedb_path = notebook_lancedb_path(slug)
            corpus_info = read_corpus_version(lancedb_path)
            if corpus_info is None:
                marker = Path(lancedb_path) / "corpus-version.json"
                raise CorpusNotIngestedError(
                    f"notebook {slug!r}: no ingested corpus "
                    f"(corpus-version.json not found at {marker}). Ingest "
                    f"it first: `uv run python tools/notebook_ingest.py "
                    f"{slug}`."
                )
            loop = asyncio.get_running_loop()
            table, degraded = await loop.run_in_executor(
                None,
                lambda: open_chunks_table_with_fallback(
                    lancedb_path=lancedb_path,
                    version=corpus_info.version,
                ),
            )
            if degraded is not None:
                logger.warning(
                    "Resources.notebook_table(%s): OPENED IN DEGRADED "
                    "MODE — live tip version %d failed; serving fallback "
                    "version %d (reason=%s).",
                    slug,
                    degraded.original_version,
                    degraded.fallback_version,
                    degraded.reason,
                )
            self._notebook_tables[slug] = (table, corpus_info)
            self._notebook_tables.move_to_end(slug)
            # #207: the marker was read a few lines up, so start this
            # slug's gate already-satisfied rather than making the next
            # query re-read the same file.
            self._get_notebook_gate(slug).mark_checked()
            # Evict-oldest if over the slot cap (m2 FM-6). #207: the
            # per-slug freshness gate is pruned in lockstep so the gate
            # registry stays bounded by the SAME cap — an unbounded
            # gates dict would reintroduce the fd-exhaustion shape m2
            # FM-6 closed, one dict over.
            while len(self._notebook_tables) > MAX_NOTEBOOK_TABLE_SLOTS:
                evicted_slug, _ = self._notebook_tables.popitem(last=False)
                self._notebook_gates.pop(evicted_slug, None)
                logger.info(
                    "Resources.notebook_table: evicted %r (LRU; cap=%d)",
                    evicted_slug,
                    MAX_NOTEBOOK_TABLE_SLOTS,
                )
            return self._notebook_tables[slug]

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
        # paper-metadata-m2: close the paper-metadata SQLite store.
        # Same best-effort discipline (regenerable NORMAL-tier state;
        # SQLite's WAL recovers on the next open).
        if self.paper_metadata_store is not None:
            try:
                await self.paper_metadata_store.close()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Resources.shutdown: paper_metadata_store close failed"
                )
        # verification-feedback-m2: tear down the Lean REPL subprocess
        # before the executor drain. terminate() + reap is mandatory —
        # an unreaped subprocess is a zombie (POSIX) / leaked handle
        # (Windows). Best-effort: a close error is logged and swallowed
        # so it cannot block the rest of shutdown.
        if self.lean_repl is not None:
            try:
                await self.lean_repl.close()
            except Exception:  # noqa: BLE001
                logger.exception("Resources.shutdown: Lean REPL close failed")
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


async def _open_optional_lancedb_tables(
    config: Config, *, caller: str
) -> tuple[Any | None, Any | None]:
    """Open the optional ``definitions`` + ``equations`` LanceDB tables.

    Returns ``(definitions_table, equations_table)``, either of which is
    ``None`` when that table is absent — a normal state that the
    ``get_definitions`` / ``find_equation`` handlers degrade for
    (``index_status="absent"`` / ``retrieval_mode="dense_only_fallback"``).
    Never raises: these are enrichments, not hard requirements.

    Extracted from :meth:`Resources.startup` for issue #207 so the
    corpus-rebind path (:meth:`Resources._bind_corpus`) opens them the
    SAME way rather than inheriting handles bound to the previous
    corpus. Before the extraction, ``late_bind`` did not open them at
    all — a bootstrap-mode server never got its optional tables until a
    restart.

    ``caller`` only labels the log lines, so an operator reading the
    journal can tell a cold start from a mid-session rebind.

    F7 (E10_S03 critique) — share ONE ``lancedb.connect`` across both
    tables. LanceDB's idiom is one connection per process with multiple
    ``open_table`` calls on top of it.
    """
    definitions_table: Any | None = None
    equations_table: Any | None = None
    loop = asyncio.get_running_loop()
    try:
        import lancedb  # noqa: PLC0415

        from ingest.schema import (  # noqa: PLC0415
            DEFINITIONS_TABLE_NAME,
            EQUATIONS_TABLE_NAME,
        )

        db_conn = await loop.run_in_executor(
            None,
            lambda: lancedb.connect(str(Path(config.lancedb_path).resolve())),
        )

        # Try open_table directly rather than relying on a
        # version-fragile table-listing API. LanceDB raises
        # ``ValueError`` (and on some versions ``FileNotFoundError``)
        # when the table is absent; either is the cue to skip.
        try:
            definitions_table = await loop.run_in_executor(
                None,
                lambda: db_conn.open_table(DEFINITIONS_TABLE_NAME),
            )
            logger.info(
                "%s: opened LanceDB %s table", caller, DEFINITIONS_TABLE_NAME
            )
        except (ValueError, FileNotFoundError):
            logger.info(
                "%s: %s table not present; get_definitions will return "
                "index_status=absent",
                caller,
                DEFINITIONS_TABLE_NAME,
            )

        # Equations table (E10_S03). Same pattern — missing table is
        # normal at v1 because the equation atom extractor is deferred.
        try:
            equations_table = await loop.run_in_executor(
                None,
                lambda: db_conn.open_table(EQUATIONS_TABLE_NAME),
            )
            logger.info(
                "%s: opened LanceDB %s table", caller, EQUATIONS_TABLE_NAME
            )
        except (ValueError, FileNotFoundError):
            logger.info(
                "%s: %s table not present; find_equation will use "
                "dense-only fallback for MathML inputs",
                caller,
                EQUATIONS_TABLE_NAME,
            )
    except Exception as exc:  # noqa: BLE001 — both tables are non-critical
        logger.warning("%s: could not open optional tables: %s", caller, exc)
    return definitions_table, equations_table


async def _open_theorem_names_store(config: Config, *, caller: str) -> Any | None:
    """Open the theorem-names SQLite FTS5 store, or return ``None``.

    Same lazy-open contract as the optional LanceDB tables — a missing
    file is normal until ``python -m ingest.index_theorem_names`` runs,
    and ``find_lemma_by_name`` falls back to the in-memory scan
    (``retrieval_mode="in_memory_scan_fallback"``). Never raises.

    Extracted alongside :func:`_open_optional_lancedb_tables` for issue
    #207; see that function's docstring for why.
    """
    try:
        from server.theorem_names_store import TheoremNamesStore  # noqa: PLC0415

        tdb_path = Path(config.theorem_names_db_path)
        if not tdb_path.exists():
            logger.info(
                "%s: theorem_names DB not present at %s; find_lemma_by_name "
                "will use in-memory scan fallback",
                caller,
                tdb_path,
            )
            return None
        store = await TheoremNamesStore.open(tdb_path)
        # F5 (E10_S02 critique) — log the row count so an empty store
        # (a recent schema bump, or a never-completed first ingest) is
        # distinguishable from a populated one. An empty store + cold
        # corpus would otherwise be indistinguishable from "no named
        # theorems anywhere in the corpus."
        row_count = await store.row_count()
        logger.info(
            "%s: opened theorem_names SQLite store at %s (rows=%d)",
            caller,
            tdb_path,
            row_count,
        )
        if row_count == 0:
            logger.warning(
                "%s: theorem_names store is EMPTY. Re-run "
                "`python -m ingest.index_theorem_names` to populate it; "
                "until then find_lemma_by_name returns zero matches.",
                caller,
            )
        return store
    except Exception as exc:  # noqa: BLE001 — non-critical enrichment
        logger.warning("%s: could not open theorem_names store: %s", caller, exc)
        return None


async def _close_quietly(handle: Any, *, label: str) -> None:
    """Await ``handle.close()`` if it has one, swallowing any failure.

    Used by :meth:`Resources._bind_corpus` to release the PREVIOUS
    corpus's SQLite handles after the swap. A rebind that leaked them
    would turn every ingest into a permanent fd + WAL-handle leak in a
    long-lived server — the kind of slow failure a once-per-ingest code
    path hides for weeks. Best-effort by design: the new handles are
    already live, so a close error must not fail the rebind.

    **Known narrow window.** A request that read ``get_cache()`` just
    before the swap holds the OLD cache object and can have it closed
    underneath it. Every cache method logs-and-falls-through on error
    (``.claude/notes/07-multi-agent-caching.md``: caching is
    performance, not correctness), so the worst outcome is one logged
    cache miss on one request, at most once per ingest. Closing after
    the swap rather than before is what keeps the window this small;
    the alternatives are leaking a handle per ingest or refcounting
    every cache borrow, and neither is worth it for a miss.
    """
    if handle is None:
        return
    close = getattr(handle, "close", None)
    if close is None:
        return
    try:
        result = close()
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # noqa: BLE001
        logger.exception("corpus rebind: closing the previous %s failed", label)


async def _open_paper_metadata_store(config: Config) -> Any | None:
    """Open the per-notebook ``paper_metadata.db`` sibling of the
    lancedb dir, or return ``None`` (paper-metadata-m2).

    The store file lives at
    ``var/arxmcp/notebooks/<slug>/paper_metadata.db`` — the sibling of
    the notebook's ``lancedb/`` dir, which is exactly what
    ``config.lancedb_path`` points at after the ``ARXMCP_NOTEBOOK``
    rewrite in :meth:`server.config.Config.derive_notebook_lancedb_path`.
    Derived as ``lancedb_path.parent / PAPER_METADATA_DB_FILENAME`` per
    the m1 placement decision (option B).

    Open-only-if-exists is load-bearing: ``PaperMetadataStore.open``
    CREATES the file, but hydration is the backfill CLI's job — the
    server must not scatter empty DBs next to un-hydrated notebooks
    (or next to the shared corpus at ``var/arxmcp/index/``).

    Never raises: the store is a non-critical enrichment, so any
    failure logs a WARN and returns ``None`` (the get_paper handler
    then serves the v1 synthesized-from-chunks nulls).
    """
    try:
        from server.paper_metadata_store import (  # noqa: PLC0415
            PAPER_METADATA_DB_FILENAME,
            PaperMetadataStore,
        )

        pmd_path = Path(config.lancedb_path).parent / PAPER_METADATA_DB_FILENAME
        if not pmd_path.exists():
            logger.info(
                "Resources: paper metadata DB not present at %s; get_paper "
                "will synthesize from chunks (run "
                "tools/notebook_metadata_backfill.py to hydrate)",
                pmd_path,
            )
            return None
        store = await PaperMetadataStore.open(pmd_path)
        row_count = await store.row_count()
        logger.info(
            "Resources: opened paper_metadata SQLite store at %s (rows=%d)",
            pmd_path,
            row_count,
        )
        if row_count == 0:
            # Distinguish an empty store (schema created, hydration
            # never ran / all rows failed) from a populated one — the
            # F5-from-E10_S02 lesson for the theorem-names store.
            logger.warning(
                "Resources: paper_metadata store is EMPTY. Re-run "
                "`python tools/notebook_metadata_backfill.py <slug>` to "
                "hydrate it; until then get_paper returns "
                "metadata_status=synthesized_from_chunks.",
            )
        return store
    except Exception as exc:  # noqa: BLE001 — non-critical enrichment
        logger.warning(
            "Resources: could not open paper_metadata store: %s", exc,
        )
        return None


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
    "compute_chunk_count_divergence",
    "compute_unindexed_rows",
]
