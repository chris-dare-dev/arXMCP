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
    open_chunks_table,
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
    process_start_time_seconds: float = field(default_factory=time.time)
    warm: bool = False

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

        # 2. LanceDB handle — open ONCE at the pinned version. F13
        # fix: `open_chunks_table` is a synchronous file-I/O call
        # (LanceDB dataset open). Run in the default executor so we
        # don't block the event loop during startup. The discipline
        # mirrors step 3 (the embedder load) which is already
        # off-loaded.
        loop = asyncio.get_running_loop()
        chunks_table = await loop.run_in_executor(
            None,
            lambda: open_chunks_table(
                lancedb_path=config.lancedb_path,
                version=corpus_info.version,
            ),
        )
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
        # auto-builds if missing (closes E04_S04 H1). The startup
        # path file-safety-checks the pickle before loading
        # (closes E04_S04 TODO(E07)). Failure raises
        # :class:`server.retrieval.BM25IndexUnavailableError` which
        # is a ``ResourceStartupError`` subclass — server refuses to
        # open ``/readyz``.
        from server.retrieval import BM25Phase

        bm25_phase = await BM25Phase.startup(
            lancedb_path=config.lancedb_path,
            corpus_version=corpus_info.version,
        )
        logger.info(
            "Resources.startup: BM25Phase warm (corpus_size=%d)",
            bm25_phase.corpus_size,
        )

        # 5. Concurrency primitives.
        embed_semaphore = asyncio.Semaphore(config.max_concurrent_embeddings)
        rerank_semaphore = asyncio.Semaphore(config.max_concurrent_reranks)
        rerank_singleflight = Singleflight()

        instance = cls(
            config=config,
            corpus_info=corpus_info,
            chunks_table=chunks_table,
            embed_semaphore=embed_semaphore,
            rerank_semaphore=rerank_semaphore,
            rerank_singleflight=rerank_singleflight,
            reranker_model=reranker_model,
            bm25_phase=bm25_phase,
            warm=True,
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


async def _load_reranker_or_raise() -> Any:
    """Load the BGE-reranker-v2-m3 model; raise on failure.

    Synthesis D6: when ``enable_rerank=True``, model load failure is
    FATAL. The reranker integration itself lands in E07; this
    function is a placeholder that fails consistently until E07
    ships the actual loader.

    The actual reranker integration in E07 will replace this
    function's body with the real model load (transformers +
    sentence-transformers, similar to ``ingest.embedder``).
    """
    raise RerankerUnavailableError(
        "BGE-reranker-v2-m3 is not yet integrated (E07 will ship it). "
        "Set ARXMCP_ENABLE_RERANK=false until E07 lands. The brief's "
        "fail-fast contract (synthesis D6) makes this an explicit "
        "FATAL rather than a silent fallback to a disabled reranker."
    )


__all__ = [
    "CorpusNotIngestedError",
    "RerankerUnavailableError",
    "ResourceStartupError",
    "Resources",
    "Singleflight",
]
