"""Background refresher for the filesystem-backed Prometheus gauges (issue #208).

The gauges whose source of truth is a file on disk — the cron-emitted
sentinels (``backup-status.json``, ``drift-detected.flag``, …) and the
disk-free reading that drives the failure-mode-7 ingest pause — used to be
refreshed inside the ``/metrics`` ASGI wrapper. That made a Prometheus scrape
do three things it had no business doing:

1. **Blocking disk I/O on the event loop.** ``stat`` + ``read_text`` +
   ``json.loads`` per sentinel, plus a ``statvfs``, synchronously inside a
   request handler.
2. **Filesystem WRITES from a ``GET``.** The disk-full mitigation writes and
   clears ``var/arxmcp/ops/ingest-paused``, so a read-only observability
   endpoint was the control plane for pausing ingestion.
3. **Nothing at all, on a stock install.** The shipped compose stack contains
   no Prometheus. With the mitigation living on the scrape path, *nobody ever
   scraped*, so failure-mode 7 was never mitigated — while
   ``docs/ops/README.md`` and the ``ArXMCPDiskFull`` alert both described it
   as active. This is the worst of the three: a documented safety mechanism
   that was inert by construction.

This module owns the replacement: a lifespan-scoped asyncio task that calls
:func:`server.health.refresh_filesystem_metrics` on a fixed interval,
**independent of scrape traffic**, with every tick dispatched through
``asyncio.to_thread`` so the blocking work never touches the loop.

Design notes:

* **Ticks are fail-soft and isolated.** A tick that raises logs and the loop
  continues. A read-only ``var/`` tree — the condition the disk gauge exists
  to report — must not be able to kill the refresher, and must not be able to
  take down request handling either.
* **Cancellation is cooperative.** ``asyncio.CancelledError`` propagates so
  the lifespan can await the task on shutdown without a timeout dance.
* **The first tick runs immediately**, not after one interval, so a freshly
  started process exposes real sentinel values rather than zeros until the
  first interval elapses. Startup itself does no filesystem metric work.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.resources import Resources

logger = logging.getLogger(__name__)

#: Seconds between filesystem-metric refreshes. The values this reads move on
#: cron timescales (the nightly backup, the daily drift check) or slowly (disk
#: free), so a 30s cadence is already far finer-grained than the signals it
#: samples. It is comfortably under the 5m ``for:`` on ``ArXMCPDiskFull``, so
#: the alert's own debounce still governs when it fires.
DEFAULT_REFRESH_INTERVAL_SECONDS: float = 30.0


async def _run_one_tick(resources: Resources) -> bool:
    """Run a single refresh off-loop. Returns True when the tick succeeded.

    Isolated from the loop body so tests can drive exactly one tick without
    scheduling, and so the exception boundary is one obvious place.
    """
    from server.health import refresh_filesystem_metrics  # noqa: PLC0415

    try:
        await asyncio.to_thread(refresh_filesystem_metrics, resources)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Deliberately broad. This task's whole job is to keep running while
        # the filesystem misbehaves; narrowing to OSError would let an
        # unexpected error type end the refresher silently for the life of
        # the process, and the operator's first symptom would be gauges
        # frozen at their last-good values with nothing saying why.
        logger.warning(
            "filesystem metrics refresh tick failed; gauges keep their "
            "previous values and the next tick will retry",
            exc_info=True,
        )
        return False
    return True


async def run_metrics_refresh_loop(
    resources: Resources,
    interval_seconds: float = DEFAULT_REFRESH_INTERVAL_SECONDS,
) -> None:
    """Refresh the filesystem-backed gauges forever, every ``interval_seconds``.

    Intended to be wrapped in :func:`asyncio.create_task` by the app lifespan
    and cancelled on shutdown. Runs one tick immediately, then sleeps between
    ticks — so the sleep, not the work, is what a cancellation interrupts in
    the steady state.
    """
    logger.info(
        "filesystem metrics refresher started (interval=%.1fs)",
        interval_seconds,
    )
    try:
        while True:
            await _run_one_tick(resources)
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("filesystem metrics refresher stopped")
        raise


def start_metrics_refresh_task(
    resources: Resources,
    interval_seconds: float = DEFAULT_REFRESH_INTERVAL_SECONDS,
) -> asyncio.Task:
    """Create and return the refresher task.

    A thin seam so the lifespan reads as one line and tests can construct the
    task without importing asyncio plumbing.
    """
    return asyncio.create_task(
        run_metrics_refresh_loop(resources, interval_seconds),
        name="arxmcp-metrics-refresh",
    )


async def stop_metrics_refresh_task(task: asyncio.Task | None) -> None:
    """Cancel ``task`` and await its unwind. Safe to call with ``None``.

    Swallows :class:`asyncio.CancelledError` from the awaited task — that is
    the expected outcome of cancelling it, not a shutdown failure.
    """
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning(
            "filesystem metrics refresher raised during shutdown",
            exc_info=True,
        )


__all__ = [
    "DEFAULT_REFRESH_INTERVAL_SECONDS",
    "run_metrics_refresh_loop",
    "start_metrics_refresh_task",
    "stop_metrics_refresh_task",
]
