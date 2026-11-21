"""Background-task tracker for the textbook-ingest-m6 parse pipeline.

Mirrors :mod:`server.ingest_tracker` for textbook PDF parsing. Where
``IngestTaskTracker`` spawns ``tools/notebook_ingest.py`` as a Python
subprocess, ``ParseTaskTracker`` drives the work from the daemon's event
loop and runs it on a dedicated daemon thread: the heavy lifting (MinerU,
LaTeXML) is already-subprocess-isolated by m5's
:func:`ingest.textbook_parser.run_mineru_sandboxed` and m6's
:func:`ingest.textbook_renderer.render_mineru_to_html` (which delegates
to :func:`ingest.arxiv_fetch.parse_with_latexml`). Wrapping in another
Python subprocess buys no isolation and would double the cold-start
overhead.

Architectural choices (from research-synthesis §D1 + §3):

- **In-process asyncio task + daemon-thread offload over Python
  subprocess** — MinerU and LaTeXML are already subprocess-isolated.
  The tracker needs only an event-loop-friendly wrapper. The thread is
  a daemon thread of its own rather than a default-executor worker
  because a thread cannot be cancelled: the loop's teardown and the
  interpreter's exit both join executor workers, so a render still
  running at shutdown would hold the process open until it finished.
- **Global concurrency cap of 1** — ``asyncio.Semaphore(1)`` prevents
  GPU/MLX memory pressure (synthesis FM-3). MinerU on Apple Silicon
  with MLX takes ~2-3 GB working set; two parallel parses would
  double that and risk OOM on lower-end M-series.
- **DB row set to ``running`` BEFORE the heavy work begins** (FM-7
  closure pattern from m9). The caller's 202-Accepted response is
  followed by a poll; without ``running`` in place that poll would
  see ``pending`` indefinitely.
- **``done_callback`` removes the tracker entry** but the DB row
  update is INSIDE the worker function so terminal-state writes
  happen even if the callback is delayed. Every path out of the
  worker attempts a terminal write: a row left ``running`` blocks
  every later upload to that notebook until a restart.
- **Lifespan shutdown stops in-flight work and records what happened**
  — a queued parse is recorded as never started, a MinerU run is
  terminated and recorded as stopped, a parse that finishes inside the
  shutdown grace is recorded complete, and one still running when the
  grace ends is recorded as abandoned. A startup-time
  ``mark_orphaned_parses_failed()`` sweep cleans up any leftover
  ``running`` rows from a hard crash (synthesis FM-4).
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from server.notebooks_store import ParseMetrics

if TYPE_CHECKING:
    from ingest.textbook_parser import MinerUResult
    from server.notebooks_store import NotebooksStore

logger = logging.getLogger(__name__)


#: Maximum bytes of parse-error text to store on the notebook row.
#: Matches the ingest_tracker pattern; gives operators meaningful
#: diagnostic surface without bloating the SQLite row.
PARSE_ERROR_TAIL_MAX_BYTES: int = 1024


def _format_parse_error(message: str) -> str:
    """Truncate + HTML-escape + bound the parse_error column value.

    Mirrors :func:`server.ingest_tracker.prepare_stderr_tail`'s
    discipline (Threat-2 indirect-injection wrap + boundary tail).
    The textbook parse path does not capture raw subprocess stderr
    (MinerU + LaTeXML already truncate at their boundary); this
    helper formats Python-side exception messages and runtime errors
    consistently.

    m6 F1: redact absolute path prefixes BEFORE escaping so an
    exception message carrying ``/Users/<name>/.../var/arxmcp/...``
    does not leak the operator's home dir through ``/parse-status``.
    """
    redacted = _redact_path_prefix(message)
    truncated = redacted.encode("utf-8", errors="replace")[
        -PARSE_ERROR_TAIL_MAX_BYTES:
    ]
    return html.escape(truncated.decode("utf-8", errors="replace"))


def _redact_path_prefix(text: str) -> str:
    """Scrub absolute-path prefixes up to ``var/arxmcp/`` to a bare
    ``var/arxmcp/`` (m6 F1; peer of
    :func:`server.ingest_tracker.redact_paths`).

    Operates on str (not bytes) because the parse path's stored
    values are Python-side strings (the rendered html path + Python
    exception messages), not raw subprocess stderr bytes. The regex
    handles POSIX (``/Users/<name>/repo/var/arxmcp/...``,
    ``/home/<name>/repo/var/arxmcp/...``) and tolerates spaces in
    the username (macOS). Any text NOT containing ``var/arxmcp`` is
    returned unchanged.
    """
    return _ABS_PATH_PREFIX_RE.sub("var/arxmcp/", text)


#: str-domain peer of ``ingest_tracker._ABS_PATH_PREFIX_RE``. Matches
#: an absolute-path prefix (leading ``/`` or ``\``) up to and
#: including ``var/arxmcp/`` and replaces it with the bare relative
#: form. Non-greedy so only the prefix is consumed.
#: Seconds to wait before each retry of the success-path status write.
#: A failure there is most likely SQLite ``database is locked`` under a
#: concurrent status poll, which clears within moments.
_COMPLETE_WRITE_RETRY_DELAYS_S: tuple[float, ...] = (0.25, 1.0)

_ABS_PATH_PREFIX_RE = re.compile(r"[/\\][\w /\\.\-]*?var[/\\]arxmcp[/\\]")

#: Seconds :meth:`ParseTaskTracker.shutdown` allows for the final status
#: writes once it has given up waiting on a parse's thread.
_ABANDON_WRITE_TIMEOUT_S: float = 2.0


class _StoppedBeforeRender(Exception):
    """MinerU finished after shutdown began, so rendering was skipped."""


def _run_on_daemon_thread(fn: Callable[[], Any], *, name: str) -> asyncio.Future:
    """Run ``fn`` on a new daemon thread and return a future for its result.

    A daemon thread is never joined: not by the event loop's teardown and
    not at interpreter exit, both of which join default-executor workers.
    So abandoning the future really does release the process. The future
    is only settled while its loop is still open; a result that arrives
    after the loop has closed is dropped.
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def _settle(result: Any, exc: BaseException | None) -> None:
        if fut.done():
            return
        if exc is not None:
            fut.set_exception(exc)
        else:
            fut.set_result(result)

    def _target() -> None:
        try:
            result = fn()
        except BaseException as exc:  # noqa: BLE001 -- handed to the awaiting task
            outcome: tuple[Any, BaseException | None] = (None, exc)
        else:
            outcome = (result, None)
        with contextlib.suppress(RuntimeError):  # loop already closed
            loop.call_soon_threadsafe(_settle, *outcome)

    # An abandoned future's exception is never awaited; retrieve it here so
    # it is not reported as "never retrieved" when it is collected.
    fut.add_done_callback(lambda f: f.cancelled() or f.exception())
    threading.Thread(target=_target, name=name, daemon=True).start()
    return fut


def redact_html_path(output_html_path: Path) -> str:
    """Return the ``var/arxmcp/``-relative form of a rendered html
    path for storage in ``parsed_html_path`` (m6 F1).

    Prefers a clean ``Path.relative_to`` against the ``var/arxmcp``
    anchor when the segment is present; falls back to the regex
    scrub otherwise. Guarantees the stored value never contains the
    absolute repo / home prefix.
    """
    parts = output_html_path.parts
    if "var" in parts:
        idx = parts.index("var")
        # Only treat it as the anchor if the next part is 'arxmcp'.
        if idx + 1 < len(parts) and parts[idx + 1] == "arxmcp":
            return "/".join(parts[idx:])
    # Fallback: regex scrub (handles odd layouts) — if nothing
    # matched, return the original string (no var/arxmcp anchor at
    # all means it's already relative or an unexpected layout).
    return _redact_path_prefix(str(output_html_path))


class ParseTaskTracker:
    """Live-task registry for textbook parse pipelines.

    Mirrors :class:`server.ingest_tracker.IngestTaskTracker` with
    in-process worker semantics. The worker invokes the m5 MinerU
    driver and the m6 renderer on one daemon thread per parse — both
    helpers are sync and spawn their own subprocesses internally,
    so a single thread-offload is sufficient.

    Construct via :meth:`__init__` and attach to ``app.state.parse_tracker``.
    Call :meth:`shutdown` from the lifespan finally to stop in-flight
    parses on daemon stop.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._global_cap = asyncio.Semaphore(1)

    def is_running(self, slug: str) -> bool:
        """Return True if a live in-flight parse task exists for ``slug``.

        Used as the primary 409 collision check; paired with
        :meth:`server.notebooks_store.NotebooksStore.has_running_parse`
        as a cross-restart fallback in the handler.
        """
        task = self._tasks.get(slug)
        return task is not None and not task.done()

    def start_parse(
        self,
        slug: str,
        pdf_path: Path,
        paper_id: str,
        output_dir: Path,
        parsed_dir: Path,
        store: NotebooksStore,
    ) -> asyncio.Task:
        """Schedule a parse pipeline for ``slug``.

        The notebook row's ``parse_status`` must already be set to
        ``running`` by the caller BEFORE this returns (FM-7 closure).
        Returns the created :class:`asyncio.Task`; the tracker holds
        its own reference for GC safety.

        Parameters mirror the worker invocation:
        ``pdf_path`` is the uploaded PDF on disk;
        ``output_dir`` is the per-invocation MinerU scratch dir
        (under the notebook's parsed root);
        ``parsed_dir`` is the per-notebook parsed root that the
        renderer writes ``<flat_paper_id>/index.html`` into.
        """
        task = asyncio.create_task(
            self._run_parse(
                slug=slug,
                pdf_path=pdf_path,
                paper_id=paper_id,
                output_dir=output_dir,
                parsed_dir=parsed_dir,
                store=store,
            ),
            name=f"parse:{slug}",
        )
        self._tasks[slug] = task
        task.add_done_callback(
            lambda t, s=slug: self._on_task_done(s, t),
        )
        return task

    def _on_task_done(self, slug: str, task: asyncio.Task) -> None:
        """Remove the task from the tracker once it's done.

        DB-row update happens inside ``_run_parse`` before the task
        returns; this callback is registry hygiene only. We call
        ``task.exception()`` so the wrapper's exception, if any,
        is consumed (avoids "Task exception was never retrieved").
        """
        current = self._tasks.get(slug)
        if current is task:
            self._tasks.pop(slug, None)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "parse task for slug=%s raised: %s", slug, exc,
                )

    @staticmethod
    async def _record_complete(
        store: NotebooksStore, slug: str, html_path_str: str,
        metrics: ParseMetrics,
    ) -> None:
        """Write ``complete``, retrying a transient failure."""
        for delay in (*_COMPLETE_WRITE_RETRY_DELAYS_S, None):
            try:
                await store.update_parse_status(
                    slug,
                    store.PARSE_STATUS_COMPLETE,
                    parse_error="",
                    parsed_html_path=html_path_str,
                    metrics=metrics,
                )
                return
            except Exception:
                if delay is None:
                    raise
                logger.warning(
                    "recording parse complete for slug=%s failed; "
                    "retrying in %.2fs", slug, delay, exc_info=True,
                )
                await asyncio.sleep(delay)

    async def _run_parse(
        self,
        *,
        slug: str,
        pdf_path: Path,
        paper_id: str,
        output_dir: Path,
        parsed_dir: Path,
        store: NotebooksStore,
    ) -> None:
        """Run MinerU → renderer → DB update.

        Bounded by the global semaphore so at most one parse runs at
        a time across all notebooks. The two heavy subprocess-spawning
        helpers (``run_mineru_sandboxed`` and ``render_mineru_to_html``)
        are sync and run back to back on a daemon thread so the event
        loop stays responsive to other requests.

        Cancellation (only :meth:`shutdown` cancels) cannot stop that
        thread, so the first cancel does not end the task. It asks the
        thread to skip rendering and keeps waiting, so the row records
        what the thread actually did: complete if it finished, failed
        with its error if MinerU was terminated under it. A second
        cancel means shutdown has stopped waiting, and the row says the
        parse was abandoned while still running.
        """
        # Lazy imports — avoid pulling MinerU / LaTeXML helpers into
        # the daemon's import graph until a parse actually runs.
        from ingest import textbook_parser, textbook_renderer

        try:
            await self._global_cap.acquire()
        except asyncio.CancelledError:
            await self._record_failed(
                store, slug,
                "cancelled at daemon shutdown before it started "
                "(it was queued behind another parse)",
            )
            raise
        try:
            stop = threading.Event()
            stage = ["MinerU"]
            # Set by the worker thread once MinerU returns, so a render
            # failure still records how long MinerU took.
            mineru_done: list[MinerUResult] = []

            def _partial_metrics() -> ParseMetrics:
                if not mineru_done:
                    return ParseMetrics()
                return ParseMetrics(mineru_wall_s=mineru_done[0].wall_clock_s)

            def _work() -> tuple[MinerUResult, Any]:
                mineru = textbook_parser.run_mineru_sandboxed(pdf_path, output_dir)
                mineru_done.append(mineru)
                if stop.is_set():
                    raise _StoppedBeforeRender(
                        "MinerU finished, rendering was skipped",
                    )
                stage[0] = "rendering"
                rendered = textbook_renderer.render_mineru_to_html(
                    mineru, parsed_dir, paper_id,
                )
                return mineru, rendered

            work = _run_on_daemon_thread(_work, name=f"parse:{slug}")
            interrupted = False
            while True:
                try:
                    mineru_result, render_result = await asyncio.shield(work)
                    break
                except asyncio.CancelledError:
                    if interrupted:
                        await self._record_failed(
                            store, slug,
                            "abandoned at daemon shutdown while "
                            f"{stage[0]} was still running; any output it "
                            "writes afterwards is not recorded",
                            metrics=_partial_metrics(),
                        )
                        raise
                    interrupted = True
                    stop.set()
                except Exception as e:  # noqa: BLE001
                    if interrupted:
                        detail = (
                            str(e) if isinstance(e, _StoppedBeforeRender)
                            else f"{type(e).__name__}: {e}"
                        )
                        await self._record_failed(
                            store, slug, f"stopped at daemon shutdown: {detail}",
                            metrics=_partial_metrics(),
                        )
                        raise asyncio.CancelledError from e
                    logger.exception(
                        "parse pipeline for slug=%s failed", slug,
                    )
                    await self._record_failed(
                        store, slug, f"{type(e).__name__}: {e}",
                        metrics=_partial_metrics(),
                    )
                    return

            # Success: record the parsed_html_path scrubbed to its
            # ``var/arxmcp/``-relative form. Storing the absolute path
            # would leak the operator's home dir through the
            # /parse-status JSON.
            metrics = ParseMetrics(
                latex_errors=render_result.latex_error_annotations,
                mineru_wall_s=mineru_result.wall_clock_s,
                render_wall_s=render_result.wall_clock_s,
            )
            try:
                html_path_str = redact_html_path(render_result.output_html_path)
                await self._record_complete(store, slug, html_path_str, metrics)
            except Exception as e:  # noqa: BLE001
                # The HTML is on disk, but a row left ``running`` would
                # block every later upload to this notebook, so settle
                # for a terminal ``failed`` that says what happened.
                logger.exception(
                    "parse for slug=%s finished but its status could not "
                    "be recorded", slug,
                )
                await self._record_failed(
                    store, slug,
                    "parse finished but recording it failed: "
                    f"{type(e).__name__}: {e}",
                    metrics=metrics,
                )
                return
            logger.info(
                "parse complete: slug=%s html=%s errors=%d "
                "mineru_wall=%.1fs render_wall=%.2fs",
                slug, html_path_str,
                render_result.latex_error_annotations,
                mineru_result.wall_clock_s, render_result.wall_clock_s,
            )
            if interrupted:
                raise asyncio.CancelledError
        finally:
            self._global_cap.release()

    @staticmethod
    async def _record_failed(
        store: NotebooksStore, slug: str, message: str,
        *, metrics: ParseMetrics | None = None,
    ) -> None:
        """Write a terminal ``failed`` row; a failed write is logged.

        ``metrics`` is whatever the parse measured before it failed;
        omitted, every measurement is written as not measured, so a
        failed row never carries an earlier parse's numbers.

        The startup orphan sweep still covers a row this cannot write.
        """
        try:
            await store.update_parse_status(
                slug,
                store.PARSE_STATUS_FAILED,
                parse_error=_format_parse_error(message),
                metrics=metrics if metrics is not None else ParseMetrics(),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "parse status write failed for slug=%s; orphan-recovery "
                "will pick this up on next boot", slug,
            )

    async def shutdown(self, *, timeout_seconds: float = 5.0) -> None:
        """Stop every in-flight parse, recording each outcome, in bounded time.

        Cancelling the task does not stop the thread doing the work, and
        MinerU runs in its own session, outside any process group the
        supervisor signals. So shutdown, in order:

        1. cancels every task. A queued one records that it never started;
           a running one asks its thread to skip rendering and keeps
           waiting on it;
        2. terminates live MinerU subprocesses, which is what unblocks a
           thread waiting on MinerU;
        3. waits up to ``timeout_seconds`` for the tasks to record what
           their threads did;
        4. cancels whatever is still waiting, so it records the parse as
           abandoned, and allows a short, fixed time for those writes.

        The threads are daemon threads, so one still rendering does not
        hold the process open after this returns.
        """
        if not self._tasks:
            return
        tasks_snapshot = list(self._tasks.values())
        for task in tasks_snapshot:
            if not task.done():
                task.cancel()
        # Lazy import, matching `_run_parse`: the MinerU helpers stay out of
        # the daemon's import graph until a parse has actually run.
        from ingest.textbook_parser import (  # noqa: PLC0415
            terminate_live_mineru,
        )

        # In a thread: it signals, waits out a short grace, then SIGKILLs, and
        # the event loop should not block on that.
        terminated = await asyncio.to_thread(terminate_live_mineru)
        if terminated:
            logger.info(
                "ParseTaskTracker.shutdown: terminated %d live mineru "
                "subprocess(es)",
                terminated,
            )
        _, pending = await asyncio.wait(tasks_snapshot, timeout=timeout_seconds)
        if not pending:
            return
        # A MinerU spawned after the first sweep would otherwise outlive us.
        await asyncio.to_thread(terminate_live_mineru)
        logger.warning(
            "ParseTaskTracker.shutdown: %d parse(s) still running after "
            "%.1fs; abandoning",
            len(pending), timeout_seconds,
        )
        for task in pending:
            task.cancel()
        _, unsettled = await asyncio.wait(
            pending, timeout=_ABANDON_WRITE_TIMEOUT_S,
        )
        if unsettled:
            logger.warning(
                "ParseTaskTracker.shutdown: %d parse status write(s) did not "
                "finish; orphan-recovery will settle them on next boot",
                len(unsettled),
            )


__all__ = [
    "PARSE_ERROR_TAIL_MAX_BYTES",
    "ParseTaskTracker",
    "_format_parse_error",
    "redact_html_path",
]
