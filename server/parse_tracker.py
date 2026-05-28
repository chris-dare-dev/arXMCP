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
    """
    truncated = message.encode("utf-8", errors="replace")[
        -PARSE_ERROR_TAIL_MAX_BYTES:
    ]
    return html.escape(truncated.decode("utf-8", errors="replace"))


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

            # Success: record the parsed_html_path relative to repo
            # root if possible (more readable for operators) or
            # absolute otherwise. Either way, the path is stored
            # verbatim; consumers must treat it as opaque.
            html_path_str = str(render_result.output_html_path)
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
        """Cancel every in-flight parse task; await with a short timeout.

        Cancellation cannot signal MinerU's or LaTeXML's subprocess
        from inside ``asyncio.to_thread``; those subprocesses continue
        running until their own wall-timeouts fire. The lifespan-
        startup ``mark_orphaned_parses_failed`` covers the resulting
        orphan row on the next boot.
        """
        if not self._tasks:
            return
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
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
]
