"""Background-task tracker for the textbook-ingest-m6 parse pipeline.

Mirrors :mod:`server.ingest_tracker` for textbook PDF parsing. Where
``IngestTaskTracker`` spawns ``tools/notebook_ingest.py`` as a Python
subprocess, ``ParseTaskTracker`` runs the work in the daemon's event
loop via :func:`asyncio.to_thread`: the heavy lifting (MinerU,
LaTeXML) is already-subprocess-isolated by m5's
:func:`ingest.textbook_parser.run_mineru_sandboxed` and m6's
:func:`ingest.textbook_renderer.render_mineru_to_html` (which delegates
to :func:`tools.arxiv_fetch.parse_with_latexml`). Wrapping in another
Python subprocess buys no isolation and would double the cold-start
overhead.

Architectural choices (from research-synthesis §D1 + §3):

- **In-process asyncio task + thread-offload over Python subprocess** —
  MinerU and LaTeXML are already subprocess-isolated. The tracker
  needs only an event-loop-friendly wrapper.
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
  happen even if the callback is delayed.
- **Lifespan shutdown cancels in-flight tasks** then a startup-time
  ``mark_orphaned_parses_failed()`` sweep cleans up any leftover
  ``running`` rows from a hard crash (synthesis FM-4).
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

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
_ABS_PATH_PREFIX_RE = re.compile(r"[/\\][\w /\\.\-]*?var[/\\]arxmcp[/\\]")


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
    driver and the m6 renderer in :func:`asyncio.to_thread` — both
    helpers are sync and spawn their own subprocesses internally,
    so a single thread-offload is sufficient.

    Construct via :meth:`__init__` and attach to ``app.state.parse_tracker``.
    Call :meth:`shutdown` from the lifespan finally to cancel
    in-flight tasks on daemon stop.
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
        are sync and offloaded via :func:`asyncio.to_thread` so the
        event loop stays responsive to other requests.
        """
        # Lazy imports — avoid pulling MinerU / LaTeXML helpers into
        # the daemon's import graph until a parse actually runs.
        from ingest.textbook_parser import run_mineru_sandboxed
        from ingest.textbook_renderer import render_mineru_to_html

        async with self._global_cap:
            try:
                mineru_result: MinerUResult = await asyncio.to_thread(
                    run_mineru_sandboxed,
                    pdf_path,
                    output_dir,
                )
                render_result = await asyncio.to_thread(
                    render_mineru_to_html,
                    mineru_result,
                    parsed_dir,
                    paper_id,
                )
            except asyncio.CancelledError:
                # Mark the row as failed on lifespan shutdown — same
                # contract as IngestTaskTracker's cancel path. The
                # subprocess hierarchy (MinerU + LaTeXML) cannot be
                # signalled from here directly (we are in a thread-
                # offload); they will see their own wall-timeout
                # expire and terminate.
                try:
                    await store.update_parse_status(
                        slug,
                        store.PARSE_STATUS_FAILED,
                        parse_error=html.escape(
                            "cancelled at daemon shutdown",
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "parse cancel-path DB write failed for slug=%s; "
                        "orphan-recovery will pick this up on next boot",
                        slug,
                    )
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception(
                    "parse pipeline for slug=%s failed", slug,
                )
                with contextlib.suppress(Exception):
                    await store.update_parse_status(
                        slug,
                        store.PARSE_STATUS_FAILED,
                        parse_error=_format_parse_error(
                            f"{type(e).__name__}: {e}"
                        ),
                    )
                return

            # Success: record the parsed_html_path scrubbed to its
            # ``var/arxmcp/``-relative form (m6 F1). Storing the
            # absolute path would leak the operator's home dir
            # through the /parse-status JSON — the m9 redact_paths
            # discipline applies here too.
            html_path_str = redact_html_path(render_result.output_html_path)
            await store.update_parse_status(
                slug,
                store.PARSE_STATUS_COMPLETE,
                parse_error="",
                parsed_html_path=html_path_str,
            )
            logger.info(
                "parse complete: slug=%s html=%s errors=%d "
                "mineru_wall=%.1fs render_wall=%.2fs",
                slug, html_path_str,
                render_result.latex_error_annotations,
                mineru_result.wall_clock_s, render_result.wall_clock_s,
            )

    async def shutdown(self, *, timeout_seconds: float = 5.0) -> None:
        """Cancel every in-flight parse task AND terminate MinerU.

        Issue #500. Cancelling the task is not enough and never was:
        ``run_mineru_sandboxed`` runs through :func:`asyncio.to_thread`, so
        ``CancelledError`` reaches the awaiting coroutine while the THREAD
        stays blocked in ``proc.communicate()`` until MinerU exits on its own
        wall timeout -- minutes, typically. Nothing else could reach it
        either: ``start_new_session=True`` puts MinerU in its own process
        group, outside what the supervisor's group sweep can signal
        (issues #467, #499). So the spawner is asked to stop it, since it is
        the only holder of the handle and has no race.

        Killing the subprocess is also what UNBLOCKS the offloaded thread, so
        it happens before the gather rather than after: cancel, terminate,
        then wait for the wrappers to unwind.

        The ordering leaves the DB row correct either way -- ``_run_parse``'s
        ``CancelledError`` branch writes the failed row, and the lifespan
        ``mark_orphaned_parses_failed`` still covers a row this misses.
        """
        if not self._tasks:
            return
        for task in self._tasks.values():
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
        tasks_snapshot = list(self._tasks.values())
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks_snapshot, return_exceptions=True),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                "ParseTaskTracker.shutdown: %d task(s) did not exit "
                "within %.1fs; abandoning",
                sum(1 for t in tasks_snapshot if not t.done()),
                timeout_seconds,
            )


__all__ = [
    "PARSE_ERROR_TAIL_MAX_BYTES",
    "ParseTaskTracker",
    "_format_parse_error",
    "redact_html_path",
]
