"""Background-task tracker for the m9 UI ingest trigger.

Spawns ``tools/notebook_ingest.py <slug>`` as a subprocess inside
an ``asyncio.create_task`` so the daemon can fire-and-forget a
long-running ingest without blocking the event loop or losing the
task reference to garbage collection.

Architectural choices (from the m9 research synthesis):

- **Subprocess over in-process** — `asyncio.create_subprocess_exec`
  gives true isolation (an ingest crash cannot crash the daemon)
  AND native stderr capture via `asyncio.subprocess.PIPE`. The
  ~30s BGE-M3 cold-start overhead in the subprocess is acceptable
  amortized over minutes-to-hours of ingest. In-process
  `asyncio.to_thread` was the alternative; rejected because
  stderr capture would require global `sys.stderr` redirection
  from a worker thread (dangerous + AC #2 requires the captured
  stderr tail).
- **Global concurrency cap of 1** — `asyncio.Semaphore(1)`
  prevents the "100 notebooks × 100 concurrent subprocesses"
  resource-exhaustion path (m9 FM-1). Combined with the per-
  notebook check via `is_running(slug)`, the daemon serves at
  most one ingest at any moment AND at most one ingest per slug.
- **DB row inserted BEFORE the task is spawned** (FM-7 closure).
  The first 2s poll from the UI fires before subprocess startup
  completes — without the row already in place that poll would
  404.
- **`done_callback` updates the DB row** on subprocess exit. The
  callback runs in the asyncio event loop (the task is on the
  main loop); it schedules the DB write via `asyncio.create_task`
  so the callback returns quickly.
- **Path redaction before storing stderr** (FM-4). The subprocess
  emits absolute paths like
  ``/Users/.../var/arxmcp/notebooks/<slug>/ops/parser-failures.jsonl``;
  the AC requires scrubbing the prefix down to ``var/arxmcp/``.
- **HTML escape before storing stderr** (FM-3). Threat 2 —
  the stderr text could in principle contain
  ``<retrieved_chunk>`` literals from a parser-failure log; the
  delimiter contract requires escaping at the boundary.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from server.notebooks_store import NotebooksStore

logger = logging.getLogger(__name__)

#: Maximum bytes of subprocess stderr to capture + store. AC #2
#: requirement: "the last 1 KB of stderr". Truncation happens
#: BEFORE redaction so the regex never scans multi-MB output.
STDERR_TAIL_MAX_BYTES: int = 1024

#: Regex that strips absolute-path prefixes up to and including
#: ``var/arxmcp/`` (m9 FM-4). The repo-root prefix is not stable
#: across operator installs; this regex handles
#: ``/Users/<name>/path/to/repo/var/arxmcp/...``,
#: ``/home/<name>/path/to/repo/var/arxmcp/...``,
#: ``C:\Users\<name>\path\to\repo\var\arxmcp\...`` consistently.
#:
#: m9 rect F4: includes a literal space in the character class so
#: macOS paths with spaces in the username (e.g.
#: ``/Users/Joe Smith/repo/var/arxmcp/foo``) redact correctly. Linux
#: usernames cannot contain spaces (POSIX), so this only affects
#: macOS — but a leak on macOS is still an AC #2 violation.
#:
#: Bytes domain so it works whether the subprocess emits UTF-8 or
#: punted-to-Latin-1 output.
_ABS_PATH_PREFIX_RE: re.Pattern[bytes] = re.compile(
    rb"[/\\][\w /\\.\-]*?var[/\\]arxmcp[/\\]"
)


def redact_paths(stderr_bytes: bytes) -> bytes:
    """Replace absolute-path prefixes up to ``var/arxmcp/`` in
    ``stderr_bytes`` with the bare ``var/arxmcp/`` (m9 FM-4).

    Run AFTER truncating to ``STDERR_TAIL_MAX_BYTES`` so the regex
    is bounded. Bytes-in, bytes-out so it composes with the
    truncation step without re-decoding."""
    return _ABS_PATH_PREFIX_RE.sub(b"var/arxmcp/", stderr_bytes)


def prepare_stderr_tail(stderr_bytes: bytes) -> str:
    """Truncate → redact → decode → HTML-escape pipeline for the
    stderr tail stored on a failed run row.

    Order matters:
    1. Truncate first — bounds the regex scan.
    2. Redact paths — m9 FM-4; removes the absolute-path leak.
    3. Decode with ``errors="replace"`` — locale-safe for
       arbitrary subprocess output.
    4. HTML-escape — m9 FM-3 (Threat 2 — the text may eventually
       reach a Jinja2 template with autoescape, but explicit
       escape at storage time gives defense-in-depth).
    """
    truncated = stderr_bytes[-STDERR_TAIL_MAX_BYTES:]
    redacted = redact_paths(truncated)
    text = redacted.decode("utf-8", errors="replace")
    return html.escape(text)


# ---------------------------------------------------------------------------
# stage2/arx-a23 (WS-A A3, gap R4) — additive ingest stage events
# ---------------------------------------------------------------------------

#: Parses the terminal summary line ``tools/notebook_ingest.py`` prints
#: on stdout (``bulk_ingest: total=N ok=N fail=N ar5iv_rate=F``). Used
#: to derive per-stage completion events (chunk/embed) from a finished
#: run — the subprocess is opaque mid-run (one Python process running
#: per-paper fetch→chunk→embed loops), so run-summary derivation is
#: the honest granularity available without instrumenting
#: ``ingest/bulk_ingest.py`` itself (a follow-up owned by the ingest
#: lane). The event ``detail`` marks ``derived: "run_summary"``.
_BULK_SUMMARY_RE: re.Pattern[bytes] = re.compile(
    rb"bulk_ingest: total=(\d+) ok=(\d+) fail=(\d+)"
)

#: Parses the ``BM25 built for corpus_version=N`` stdout line → the
#: ``index`` stage completion event.
_BM25_BUILT_RE: re.Pattern[bytes] = re.compile(
    rb"BM25 built for corpus_version=(\d+)"
)


def _publish_stage(  # pragma: no cover — thin forwarding shim
    slug: str, run_id: int, stage: str, phase: str,
    detail: dict | None = None,
) -> None:
    """Best-effort forward to the observability event tier. Lazy
    import + broad except: the tracker predates the event tier and
    must keep working if it is unavailable (partial installs, tests
    that stub modules)."""
    try:
        from server.observability.events import (  # noqa: PLC0415
            publish_ingest_stage_event,
        )

        publish_ingest_stage_event(
            kind="ingest", slug=slug, stage=stage, phase=phase,
            run_id=run_id, detail=detail,
        )
    except Exception:  # noqa: BLE001
        logger.debug("ingest stage event publish failed", exc_info=True)


def _publish_run_summary_stages(
    slug: str, run_id: int, stdout_bytes: bytes, exit_code: int | None
) -> None:
    """Derive chunk/embed/index stage completions from the finished
    subprocess's stdout (see :data:`_BULK_SUMMARY_RE`). Additive only."""
    summary = _BULK_SUMMARY_RE.search(stdout_bytes or b"")
    if summary is not None:
        detail = {
            "papers_total": int(summary.group(1)),
            "papers_ok": int(summary.group(2)),
            "papers_failed": int(summary.group(3)),
            "derived": "run_summary",
        }
        phase = "finished" if int(summary.group(2)) > 0 else "failed"
        _publish_stage(slug, run_id, "chunk", phase, detail)
        _publish_stage(slug, run_id, "embed", phase, detail)
    bm25 = _BM25_BUILT_RE.search(stdout_bytes or b"")
    if bm25 is not None:
        _publish_stage(
            slug, run_id, "index", "finished",
            {"corpus_version": int(bm25.group(1)), "derived": "run_summary"},
        )
    elif exit_code is not None and exit_code != 0:
        _publish_stage(slug, run_id, "index", "failed", {"exit_code": exit_code})


class IngestTaskTracker:
    """Live-task registry for ingest subprocesses.

    Owns:
      - ``_tasks: dict[str, asyncio.Task]`` — slug → live task ref
        (keeps the task alive against GC, per Python docs:
        "Save a reference to the result of [create_task], to avoid
        a task disappearing mid-execution.")
      - ``_global_cap: asyncio.Semaphore(1)`` — at most one ingest
        runs across the whole daemon at any time (FM-1 closure).

    Construct via :meth:`__init__` and attach to ``app.state``.
    Call :meth:`shutdown` from the lifespan finally to cancel
    in-flight tasks on daemon stop.
    """

    def __init__(
        self,
        *,
        on_success_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Construct the tracker.

        Args:
            on_success_callback: Optional async callable invoked after
                a successful ingest subprocess exits 0.  Receives the
                slug as its single argument.  Exceptions are logged at
                ERROR and NOT propagated (FM-3 from m4 synthesis §3 D6)
                so a late-bind failure never leaves the ingest-status
                row in a bad state or prevents the task from completing.
        """
        self._tasks: dict[str, asyncio.Task] = {}
        self._global_cap = asyncio.Semaphore(1)
        self._on_success_callback = on_success_callback

    def is_running(self, slug: str) -> bool:
        """Return True if a live in-flight task exists for ``slug``.

        Used as the primary 409 collision check (AC #3); paired
        with ``NotebooksStore.has_running_ingest(slug)`` as a
        cross-restart fallback in the handler.
        """
        task = self._tasks.get(slug)
        return task is not None and not task.done()

    def start_ingest(
        self,
        slug: str,
        run_id: int,
        store: NotebooksStore,
        now_iso_provider,
        notebook_kind: str = "arxiv",
        textbook_chunker: str = "html",
        textbook_paper_ids: list[str] | None = None,
    ) -> asyncio.Task:
        """Spawn the ingest subprocess as a background task.

        The DB row for ``run_id`` must already exist (caller is
        responsible — FM-7). Returns the created
        :class:`asyncio.Task` so callers can attach extra
        callbacks if needed; the tracker stores its own
        reference for GC safety.

        ``now_iso_provider`` is a callable that returns the
        current ISO-8601 UTC string; passing it (rather than
        calling a module-level helper) keeps the tracker
        test-friendly (deterministic timestamps).

        stage2/arx-a45 (AC-A.18): ``notebook_kind`` selects the
        subprocess. arxiv-kind (default) keeps the historical
        ``tools.notebook_ingest <slug>`` (papers.txt bulk ingest +
        BM25). textbook-kind dispatches
        ``tools.notebook_textbook_ingest <slug> --paper-id ...
        --chunker <textbook_chunker>`` — the SAME CLI an operator
        runs by hand, so the API path and the CLI path are one
        implementation (the AC-A.18 parity property).
        ``textbook_paper_ids`` is the notebook's junction-row
        paper_id list, computed by the ROUTE (async store access
        happens there, before the 202 returns) — the tracker never
        queries the store for it.
        """
        # stage2/arx-a23 (gap R4): the caller has validated the slug,
        # cleared the 409 collision checks, and inserted the run row —
        # that IS the preflight; record it additively.
        _publish_stage(slug, run_id, "preflight", "finished")
        task = asyncio.create_task(
            self._run_ingest_subprocess(
                slug, run_id, store, now_iso_provider,
                notebook_kind=notebook_kind,
                textbook_chunker=textbook_chunker,
                textbook_paper_ids=list(textbook_paper_ids or []),
            ),
            name=f"ingest:{slug}:{run_id}",
        )
        self._tasks[slug] = task
        task.add_done_callback(
            lambda t, s=slug: self._on_task_done(s, t)
        )
        return task

    def _on_task_done(self, slug: str, task: asyncio.Task) -> None:
        """Remove the task from the tracker once it's done.

        The DB row update happens INSIDE ``_run_ingest_subprocess``
        before the task returns; this callback is purely for
        registry hygiene. We also call ``task.exception()`` to
        avoid the "Task exception was never retrieved" log noise
        if the wrapper itself raised (subprocess failure with
        non-zero exit is NOT an exception — the wrapper handles
        that as a normal terminal state).
        """
        current = self._tasks.get(slug)
        if current is task:
            self._tasks.pop(slug, None)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "ingest task for slug=%s raised: %s", slug, exc,
                )

    def _build_subprocess_args(
        self,
        slug: str,
        *,
        notebook_kind: str,
        textbook_chunker: str,
        textbook_paper_ids: list[str],
    ) -> list[str]:
        """Return the ``python -m ...`` argv tail for the ingest kind.

        stage2/arx-a45 (AC-A.18). Extracted as a method (rather than
        inlined in ``_run_ingest_subprocess``) so tests can pin the
        exact argv without spawning a real subprocess. The textbook
        branch passes every junction-row paper_id — multi-segment
        textbooks (``textbook:<slug>:partNN`` uploads) each get their
        own ``--paper-id`` — and the notebook's stored chunker.
        """
        if notebook_kind == "textbook":
            args = ["-m", "tools.notebook_textbook_ingest", slug]
            for pid in textbook_paper_ids:
                args += ["--paper-id", pid]
            args += ["--chunker", textbook_chunker]
            return args
        return ["-m", "tools.notebook_ingest", slug]

    async def _run_ingest_subprocess(
        self,
        slug: str,
        run_id: int,
        store: NotebooksStore,
        now_iso_provider,
        *,
        notebook_kind: str = "arxiv",
        textbook_chunker: str = "html",
        textbook_paper_ids: list[str] | None = None,
    ) -> None:
        """Spawn the subprocess, await completion, update the DB row.

        Bounded by the global semaphore so at most one ingest runs
        across the daemon at any time. The semaphore is acquired
        AFTER `create_task` returns to the caller (which gave back
        the 202 response immediately) — a queued second ingest
        would wait here, not in the handler. The per-notebook
        ``is_running`` check in the handler still 409s rather than
        queuing (AC #3); the semaphore is the global-cap defense
        that fires only if two different notebooks both pass the
        per-slug check.
        """
        subprocess_args = self._build_subprocess_args(
            slug,
            notebook_kind=notebook_kind,
            textbook_chunker=textbook_chunker,
            textbook_paper_ids=list(textbook_paper_ids or []),
        )
        async with self._global_cap:
            proc: asyncio.subprocess.Process | None = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    *subprocess_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # stage2/arx-a23 (gap R4): the run is live.
                _publish_stage(slug, run_id, "run", "started")
                _stdout, stderr_bytes = await proc.communicate()
                exit_code = proc.returncode
            except asyncio.CancelledError:
                # m9 rect F1: CancelledError is BaseException (NOT
                # Exception) in Python 3.8+, so the prior single
                # ``except Exception`` branch would NOT catch this
                # path. Without the explicit handler, daemon
                # shutdown leaves the DB row pinned to ``running``
                # AND the subprocess orphaned (no SIGTERM was sent)
                # — combined with F2's 1-hour cutoff, operators
                # hit permanent 409s for up to 55 minutes after a
                # restart-during-ingest. This branch terminates the
                # subprocess (best-effort SIGTERM + 2s grace +
                # SIGKILL) AND writes a terminal-state row before
                # re-raising so the cancellation propagates
                # normally to the gathering shutdown() call.
                if proc is not None:
                    import contextlib  # noqa: PLC0415

                    with contextlib.suppress(ProcessLookupError):
                        proc.terminate()
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=2.0)
                        except TimeoutError:
                            with contextlib.suppress(ProcessLookupError):
                                proc.kill()
                # Write the terminal-state row OUTSIDE the suppress
                # block (we want errors here to propagate to logs).
                # exit_code=-2 distinguishes "cancelled" from
                # exit_code=-1 ("spawn failed").
                try:
                    await store.update_ingest_run(
                        run_id=run_id,
                        status=store.INGEST_STATUS_FAILED,
                        finished_at=now_iso_provider(),
                        exit_code=-2,
                        stderr_tail=html.escape(
                            "cancelled at daemon shutdown"
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "ingest cancel-path DB write failed for slug=%s; "
                        "orphan-recovery will pick this up on next boot",
                        slug,
                    )
                _publish_stage(
                    slug, run_id, "run", "failed",
                    {"reason": "cancelled_at_shutdown"},
                )
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception(
                    "ingest subprocess for slug=%s spawn/await failed",
                    slug,
                )
                await store.update_ingest_run(
                    run_id=run_id,
                    status=store.INGEST_STATUS_FAILED,
                    finished_at=now_iso_provider(),
                    exit_code=-1,
                    stderr_tail=html.escape(
                        f"subprocess could not be spawned: {e}"
                    ),
                )
                _publish_stage(
                    slug, run_id, "run", "failed", {"reason": "spawn_failed"},
                )
                return

            stderr_tail = prepare_stderr_tail(stderr_bytes or b"")
            status = (
                store.INGEST_STATUS_SUCCESS
                if exit_code == 0
                else store.INGEST_STATUS_FAILED
            )
            await store.update_ingest_run(
                run_id=run_id,
                status=status,
                finished_at=now_iso_provider(),
                exit_code=exit_code,
                stderr_tail=stderr_tail if status == store.INGEST_STATUS_FAILED else None,
            )
            # stage2/arx-a23 (gap R4): derive chunk/embed/index stage
            # completions from the run's stdout summary + emit the
            # terminal run event. Purely additive — the tri-state row
            # above is untouched and remains the poll surface.
            _publish_run_summary_stages(slug, run_id, _stdout or b"", exit_code)
            _publish_stage(
                slug, run_id, "run",
                "finished" if exit_code == 0 else "failed",
                {"exit_code": exit_code},
            )
            # onboarding-uplift-m4: fire on_success_callback after a
            # successful ingest so Resources.late_bind() can promote the
            # server from bootstrap mode to normal operation in-process.
            # Exceptions are logged at ERROR and NOT propagated (FM-3 /
            # synthesis D6) — a late-bind failure must never corrupt the
            # DB row or re-raise through the task.
            if exit_code == 0 and self._on_success_callback is not None:
                try:
                    await self._on_success_callback(slug)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "IngestTaskTracker on_success_callback raised for "
                        "slug=%s; bootstrap late-bind may not have occurred",
                        slug,
                    )

    async def shutdown(self, *, timeout_seconds: float = 5.0) -> None:
        """Cancel every in-flight task and await with a short timeout.

        Cancellation is best-effort: the subprocess receives no
        signal from cancelling the asyncio wrapper; on the next
        event-loop tick the wrapper's `await proc.communicate()`
        sees a CancelledError. The subprocess continues running
        until the OS reaps it. The startup-recovery in
        ``mark_orphaned_runs_failed`` covers the resulting orphan
        row on the next boot.
        """
        if not self._tasks:
            return
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        # Snapshot before awaiting — done_callbacks may mutate the dict.
        tasks_snapshot = list(self._tasks.values())
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks_snapshot, return_exceptions=True),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                "IngestTaskTracker.shutdown: %d task(s) did not exit "
                "within %.1fs; abandoning",
                sum(1 for t in tasks_snapshot if not t.done()),
                timeout_seconds,
            )


__all__ = [
    "STDERR_TAIL_MAX_BYTES",
    "IngestTaskTracker",
    "prepare_stderr_tail",
    "redact_paths",
]
