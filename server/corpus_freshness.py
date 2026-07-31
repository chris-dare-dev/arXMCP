"""Corpus-freshness seam — who owns "is the served corpus still the
corpus on disk?" (issue #207).

Before this module existed, nothing did. :mod:`server.corpus`'s
module docstring declared cache invalidation on a corpus-version
change a MUST and asserted the implementation honored it; the
implementation did not. Concretely, at the time #207 was filed:

* :meth:`server.cache_sqlite.Tier1Store.purge_other_corpus_versions`
  had **zero callers** anywhere in the repo.
* :meth:`server.resources.Resources.notebook_table` memoized
  ``(table, corpus_info)`` for process lifetime with no re-check.
* Nothing re-read ``corpus-version.json`` after startup.

The reachable consequence was the operator's most common action: click
**Ingest** in the shipped loopback ``/ui/`` console, the subprocess
completes, ``corpus-version.json`` bumps — and the running server keeps
serving the memoized pre-ingest table while echoing the OLD
``corpus_version`` in the response envelope as truth. Silent
degradation through a button the project ships.

**What this seam owns.** The agreement between the served process and
the LanceDB dataset it was bound to, plus every handle derived from
that binding: the ``chunks`` table, the BM25 artifact, the ANN/rerank
phases, the retrieval cache, the optional definitions/equations
tables, and the theorem-names + paper-metadata SQLite stores. Two
trigger paths feed it:

1. **Push (the common case).** ``IngestTaskTracker``'s
   ``on_success_callback`` calls
   :meth:`server.resources.Resources.on_ingest_complete` the moment an
   ingest subprocess exits 0. This runs on a background task, off the
   request path, so the rebind normally completes before any query
   observes the bump.
2. **Pull (the fallback).** Every MCP tool dispatch passes through
   :func:`server.tools._wrap_with_observability`, which asks the
   served process to re-probe the marker. This covers ingest that
   happened out-of-band (``make ingest``, a ``tools/notebook_ingest.py``
   run from a terminal, a backup restore) where no in-process callback
   ever fired. Throttled + single-flighted by :class:`FreshnessGate`.

**What this seam does NOT own — the honest boundary.** A set of
independent on-disk stores must agree about what "the corpus"
contains, and no component owns that agreement. Census taken
2026-07-31 against this tree:

1. the LanceDB dataset — ``chunks`` + ``definitions`` + ``equations``
2. the Kùzu citation graph (``var/arxmcp/index/kuzu/``)
3. the BM25 pickle (``bm25.pkl`` + ``chunk_ids.json``, per version)
4. ``retrieval.db`` — the Tier-1 cache
5. ``theorem_names.db`` — the FTS5 lemma-name index
6. ``notebooks.db`` — notebook registry + ingest-run rows
7. ``paper_metadata.db`` — per-notebook paper identity
8. ``documents.db`` — per-notebook per-revision document records

Issue #207 says "seven"; the count is **eight**. ``documents.db``
(``server/documents_store.py``) is a fifth SQLite store, not a fourth,
and the issue text predates or overlooks it. Recorded here rather than
silently repeated, per CLAUDE.md §4.9 rule 3 — a census is only useful
if it is re-counted.

**Only #1 carries a version marker.** Everything else is re-opened at
whatever state it happens to be in on disk, which is an improvement
over holding a handle bound to the previous corpus but is NOT proof of
agreement. A Kùzu graph ingested against corpus v3 and queried after a
rebind to v4 remains an unversioned join — ``cite_neighbors``
deliberately does not cache, so it reads live, but nothing establishes
that the two describe the same corpus. Closing that needs a corpus
epoch spanning all eight stores. Out of scope for #207 and named here
so the next agent does not mistake this seam for that guarantee.

**Concurrency (#208 boundary).** :class:`FreshnessGate` is pure policy
— it performs no I/O at all, which is why its throttle is testable
against an injected clock with no filesystem in the loop. The one I/O
helper here, :func:`read_marker_off_loop`, runs its read in the default
executor rather than on the event loop. The gate's single-flight
discipline means a version bump triggers exactly ONE rebind even when N
requests observe it concurrently; the callers that lose the race await
the winner rather than each opening their own handles. The rest of the
rebind's I/O runs through
``run_in_executor`` / ``asyncio.to_thread`` in
:meth:`server.resources.Resources._bind_corpus`, so the single uvicorn
worker's event loop is never blocked — the triggering request awaits,
the loop keeps serving. The project deliberately runs one worker to
preserve shared-cache semantics (CLAUDE.md), which is also what makes
a process-local gate sufficient: there is no second worker holding a
divergent binding.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:  # pragma: no cover
    from server.corpus import CorpusVersionInfo

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Default minimum wall-clock gap between two request-path marker
#: probes, in seconds. A probe is a ``stat`` + small-JSON read routed
#: through the default executor — cheap, but not free at 10+
#: search_papers/sec, so it is throttled rather than run per call.
#:
#: The value bounds the worst-case staleness window for the PULL path
#: only (out-of-band ingest). The PUSH path — the ``/ui/`` Ingest
#: button, which is the reachable consequence in #207 — force-refreshes
#: and is not subject to it.
DEFAULT_FRESHNESS_INTERVAL_SECONDS: float = 2.0


class FreshnessGate:
    """Throttle + single-flight for corpus-freshness probes.

    One gate guards one corpus (the process-wide dataset, or one
    per-call notebook). :meth:`run_if_due` is the whole surface:

    * **Throttled** — at most one probe per ``interval_seconds``.
      Callers arriving inside the window get ``None`` back immediately
      and proceed against the currently-bound corpus.
    * **Single-flight** — the probe (and any rebind it triggers) runs
      under an internal lock. When N requests race to observe the same
      bump, one rebinds and the rest wait on the lock, then find the
      check no longer due and return. Exactly one rebind, and no
      caller is served from the old binding after the swap lands.

    ``interval_seconds`` semantics:

    * ``> 0`` — throttle to one probe per interval (production default).
    * ``0``   — probe on every call (the tightest freshness, highest
      probe rate; used by tests that need determinism).
    * ``< 0`` — the pull path is DISABLED; :meth:`run_if_due` is a
      no-op unless ``force=True``. The push path still works, so an
      operator who turns this off still gets invalidation from the
      ``/ui/`` Ingest button — they only lose out-of-band detection.

    ``clock`` is injectable so the throttle is unit-testable without
    sleeping; it must be a monotonic source (``time.monotonic`` by
    default) so a wall-clock step never freezes the gate.
    """

    __slots__ = ("_interval", "_clock", "_last_checked", "_lock", "_probe_count")

    def __init__(
        self,
        interval_seconds: float = DEFAULT_FRESHNESS_INTERVAL_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = float(interval_seconds)
        self._clock = clock
        self._last_checked: float | None = None
        self._lock = asyncio.Lock()
        self._probe_count = 0

    @property
    def enabled(self) -> bool:
        """``False`` when the pull path is disabled (negative interval)."""
        return self._interval >= 0.0

    @property
    def probe_count(self) -> int:
        """Probes actually run since construction. Test/ops signal."""
        return self._probe_count

    def is_due(self) -> bool:
        """``True`` when a probe is due *right now*.

        Read-only: does not take the lock and does not mark the gate.
        Callers should prefer :meth:`run_if_due`, which does both
        atomically; this exists for assertions and log lines.
        """
        if not self.enabled:
            return False
        if self._last_checked is None:
            return True
        return (self._clock() - self._last_checked) >= self._interval

    def reset(self) -> None:
        """Make the next :meth:`is_due` return ``True``.

        Used after an event that invalidates the throttle's premise —
        e.g. a notebook table was dropped, so the next access must
        re-probe rather than trust a check from before the drop.
        """
        self._last_checked = None

    def mark_checked(self) -> None:
        """Record that the on-disk version is known as of NOW, without
        running a probe.

        Called by the paths that read the marker as part of their own
        work — a startup bind, a rebind — so the very next request does
        not immediately re-read a file that was just read. Without this
        the first call after every bind pays a redundant probe, and a
        long throttle interval could not be used to isolate the push
        path from the pull path at all.
        """
        self._last_checked = self._clock()

    async def run_if_due(
        self,
        probe: Callable[[], Awaitable[T]],
        *,
        force: bool = False,
    ) -> T | None:
        """Run ``probe()`` at most once per ``interval_seconds``.

        Returns the probe's result, or ``None`` when the probe was
        skipped (not due, or the gate is disabled). ``None`` is
        therefore ambiguous by construction — callers treat "skipped"
        and "probe found nothing to do" identically, which is the
        correct behavior for a freshness check: both mean "keep serving
        what is bound".

        ``force=True`` bypasses BOTH the throttle and the disabled
        state, but still takes the lock (so a forced refresh cannot
        race a pull-path refresh) and still marks the gate checked.
        This is the push path: the ingest-completion callback knows a
        bump just happened and must not wait out an interval.

        The gate is marked checked even when ``probe`` raises — a
        probe that fails every time must not turn into a hot loop of
        failing probes on the request path. The caller is responsible
        for logging; exceptions propagate unchanged.
        """
        if not force and not self.enabled:
            return None
        async with self._lock:
            if not force and not self.is_due():
                # Lost the race to a concurrent rebind that just
                # finished, or simply inside the throttle window.
                return None
            self._probe_count += 1
            try:
                return await probe()
            finally:
                self._last_checked = self._clock()


async def read_marker_off_loop(
    lancedb_path: str | Path,
    *,
    reader: Callable[[Any], CorpusVersionInfo | None],
) -> CorpusVersionInfo | None:
    """Read ``corpus-version.json`` in the default executor.

    Returns the parsed :class:`server.corpus.CorpusVersionInfo`, or
    ``None`` when the marker is absent, unreadable, or malformed.

    **Every failure collapses to ``None`` on purpose.** This runs on
    the request path; "I could not determine the on-disk version" must
    degrade to "keep serving the currently-bound corpus", never to a
    failed tool call. A marker that is momentarily absent or
    half-written is the NORMAL state during an ingest's atomic rename
    window, so raising here would turn a routine race into operator-
    visible errors. A corrupt marker that persists is caught loudly by
    ``Resources.startup`` on the next restart and by ``/readyz``.

    ``reader`` is injected (rather than importing
    :func:`server.corpus.read_corpus_version` here) so the caller's own
    module-level binding is the one exercised — that keeps the existing
    ``monkeypatch.setattr(server.resources, "read_corpus_version", ...)``
    test idiom effective through this helper.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, reader, lancedb_path)
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning(
            "corpus-freshness probe could not read the version marker at "
            "%s (%s); continuing with the currently-bound corpus",
            lancedb_path,
            exc,
        )
        return None


__all__ = [
    "DEFAULT_FRESHNESS_INTERVAL_SECONDS",
    "FreshnessGate",
    "read_marker_off_loop",
]
