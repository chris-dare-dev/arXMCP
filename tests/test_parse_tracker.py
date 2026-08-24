"""Tests for the textbook-ingest-m6 ParseTaskTracker.

The project does NOT use pytest-asyncio; per the existing pattern in
`tests/test_notebook_api.py`, async tests wrap their body in a local
`async def` then call `asyncio.run()`. We follow that convention here
so the test suite stays homogeneous.

All heavy work (MinerU + LaTeXML) is mocked. Real-MinerU exercise
lives in tests/test_textbook_parser.py + tests/test_textbook_renderer.py.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ingest import textbook_parser
from ingest.textbook_parser import MinerUResult
from ingest.textbook_renderer import RenderResult
from server.parse_tracker import (
    PARSE_ERROR_TAIL_MAX_BYTES,
    ParseTaskTracker,
    _format_parse_error,
    redact_html_path,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store_mock() -> MagicMock:
    """Build a NotebooksStore mock with parse_status constants + an
    AsyncMock for update_parse_status."""
    store = MagicMock()
    store.PARSE_STATUS_SKIPPED = "skipped"
    store.PARSE_STATUS_PENDING = "pending"
    store.PARSE_STATUS_RUNNING = "running"
    store.PARSE_STATUS_COMPLETE = "complete"
    store.PARSE_STATUS_FAILED = "failed"
    store.update_parse_status = AsyncMock(return_value=True)
    return store


def _make_render_result(tmp_path: Path) -> RenderResult:
    return RenderResult(
        output_html_path=tmp_path / "parsed" / "x" / "index.html",
        wall_clock_s=2.0,
        latex_error_annotations=0,
    )


def _make_mineru_result(tmp_path: Path) -> MinerUResult:
    return MinerUResult(
        output_dir=tmp_path / "mineru",
        markdown_path=tmp_path / "mineru" / "x" / "auto" / "x.md",
        content_list_path=tmp_path / "mineru" / "x" / "auto" / "x_cl.json",
        stdout="", stderr="", wall_clock_s=5.0,
    )


# ---------------------------------------------------------------------------
# Pure unit tests
# ---------------------------------------------------------------------------


class TestFormatParseError:
    def test_short_passes_through(self) -> None:
        assert _format_parse_error("hello") == "hello"

    def test_long_truncated_to_tail(self) -> None:
        long = "x" * (PARSE_ERROR_TAIL_MAX_BYTES + 100) + "TAIL_MARKER"
        formatted = _format_parse_error(long)
        assert len(formatted.encode("utf-8")) <= PARSE_ERROR_TAIL_MAX_BYTES
        assert "TAIL_MARKER" in formatted

    def test_html_escape_applied(self) -> None:
        msg = "boom: <script>alert('xss')</script>"
        out = _format_parse_error(msg)
        assert "&lt;script&gt;" in out
        assert "<script>" not in out

    def test_byte_boundary_safe(self) -> None:
        """Multi-byte chars at the truncation boundary don't corrupt
        output. The encode/decode round-trip uses errors='replace',
        and the replacement character U+FFFD is 3 bytes — so the
        post-decode tail can be SLIGHTLY larger than the budget if a
        replace lands on the boundary. The bound is "fits within the
        budget plus one replacement char" (≤ MAX + 2 bytes)."""
        msg = "α" * (PARSE_ERROR_TAIL_MAX_BYTES // 2 + 5) + "END"
        out = _format_parse_error(msg)
        # Replace can grow by at most 2 bytes per boundary cut (the
        # leading partial byte is replaced with U+FFFD which is 3
        # bytes — a 1-byte input becomes 3 bytes of output).
        assert len(out.encode("utf-8")) <= PARSE_ERROR_TAIL_MAX_BYTES + 2
        assert "END" in out

    def test_redacts_absolute_path_in_message(self) -> None:
        """m6 F1: an exception message carrying an absolute path under
        var/arxmcp must be scrubbed to the var/arxmcp-relative form."""
        msg = (
            "RuntimeError: mineru exited 1 on "
            "/Users/chris.dare/repo/var/arxmcp/notebooks/sv/pdfs/x.pdf"
        )
        out = _format_parse_error(msg)
        assert "/Users/" not in out
        assert "var/arxmcp/notebooks/sv/pdfs/x.pdf" in out


class TestRedactHtmlPath:
    """m6 F1 — redact_html_path scrubs absolute prefixes."""

    def test_var_arxmcp_relative(self) -> None:
        p = Path(
            "/Users/chris.dare/Personal/SourceCode/arXMCP/var/arxmcp/"
            "notebooks/sv/parsed/textbook_sv/index.html"
        )
        out = redact_html_path(p)
        assert out == (
            "var/arxmcp/notebooks/sv/parsed/textbook_sv/index.html"
        )
        assert "/Users/" not in out

    def test_linux_home_prefix(self) -> None:
        p = Path(
            "/home/ci/build/arXMCP/var/arxmcp/notebooks/x/parsed/y/index.html"
        )
        out = redact_html_path(p)
        assert out.startswith("var/arxmcp/")
        assert "/home/" not in out

    def test_already_relative_path_unchanged(self) -> None:
        p = Path("var/arxmcp/notebooks/x/parsed/y/index.html")
        out = redact_html_path(p)
        assert out == "var/arxmcp/notebooks/x/parsed/y/index.html"

    def test_path_without_var_arxmcp_anchor_falls_back(self) -> None:
        # No var/arxmcp anchor — regex scrub returns the input
        # unchanged (nothing to redact).
        p = Path("/tmp/something/index.html")
        out = redact_html_path(p)
        # Compare to str(p) — not a hard-coded POSIX literal — so the
        # "returned unchanged" contract holds on Windows too, where the
        # fallback preserves the native separator.
        assert out == str(p)


class TestParseTaskTrackerSurface:
    def test_initial_state_empty(self) -> None:
        tracker = ParseTaskTracker()
        assert tracker.is_running("any") is False

    def test_success_path_updates_status_complete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = _make_store_mock()
        mineru_result = _make_mineru_result(tmp_path)
        render_result = _make_render_result(tmp_path)

        from ingest import textbook_parser, textbook_renderer
        monkeypatch.setattr(
            textbook_parser, "run_mineru_sandboxed",
            lambda pdf_path, output_dir: mineru_result,
        )
        monkeypatch.setattr(
            textbook_renderer, "render_mineru_to_html",
            lambda r, p, pid: render_result,
        )

        async def _run() -> None:
            tracker = ParseTaskTracker()
            task = tracker.start_parse(
                slug="test-slug",
                pdf_path=tmp_path / "x.pdf",
                paper_id="textbook:x",
                output_dir=tmp_path / "out",
                parsed_dir=tmp_path / "parsed",
                store=store,
            )
            assert tracker.is_running("test-slug") is True
            await task
            # No longer running.
            assert tracker.is_running("test-slug") is False

        asyncio.run(_run())
        # Final state: complete.
        store.update_parse_status.assert_called()
        last_call = store.update_parse_status.call_args
        assert last_call.args[1] == "complete"
        assert last_call.kwargs["parsed_html_path"] == str(
            render_result.output_html_path,
        )

    def test_mineru_failure_records_parse_status_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = _make_store_mock()

        def fake_mineru(pdf_path, output_dir):  # noqa: ARG001
            raise RuntimeError("boom: subprocess exited 137")

        from ingest import textbook_parser
        monkeypatch.setattr(
            textbook_parser, "run_mineru_sandboxed", fake_mineru,
        )

        async def _run() -> None:
            tracker = ParseTaskTracker()
            task = tracker.start_parse(
                slug="test-slug",
                pdf_path=tmp_path / "x.pdf",
                paper_id="textbook:x",
                output_dir=tmp_path / "out",
                parsed_dir=tmp_path / "parsed",
                store=store,
            )
            await task

        asyncio.run(_run())
        store.update_parse_status.assert_called_once()
        call = store.update_parse_status.call_args
        assert call.args[1] == "failed"
        assert "boom" in call.kwargs["parse_error"]
        # HTML escape applied — no raw < in stored error.
        assert "<" not in call.kwargs["parse_error"]

    def test_renderer_failure_records_parse_status_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = _make_store_mock()
        mineru_result = _make_mineru_result(tmp_path)

        from ingest import textbook_parser, textbook_renderer
        monkeypatch.setattr(
            textbook_parser, "run_mineru_sandboxed",
            lambda pdf_path, output_dir: mineru_result,
        )

        def fake_render(r, p, pid):  # noqa: ARG001
            raise RuntimeError("latexmlc failed")

        monkeypatch.setattr(
            textbook_renderer, "render_mineru_to_html", fake_render,
        )

        async def _run() -> None:
            tracker = ParseTaskTracker()
            task = tracker.start_parse(
                slug="s",
                pdf_path=tmp_path / "x.pdf",
                paper_id="textbook:x",
                output_dir=tmp_path / "out",
                parsed_dir=tmp_path / "parsed",
                store=store,
            )
            await task

        asyncio.run(_run())
        call = store.update_parse_status.call_args
        assert call.args[1] == "failed"
        assert "latexmlc failed" in call.kwargs["parse_error"]

    def test_shutdown_with_no_tasks(self) -> None:
        async def _run() -> None:
            tracker = ParseTaskTracker()
            await tracker.shutdown()

        asyncio.run(_run())  # should not raise

    def test_dataclass_render_result_is_frozen(self) -> None:
        rr = RenderResult(
            output_html_path=Path("/x"),
            wall_clock_s=1.0,
            latex_error_annotations=0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rr.latex_error_annotations = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Issue #500 — shutdown terminates the subprocess, not just the wrapper
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Direct signal-0 probe. Deliberately not the code under test."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.mark.skipif(
    not hasattr(os, "getpgid"), reason="POSIX process groups required"
)
class TestShutdownTerminatesMineru:
    """The gap #500 exists to close.

    Cancelling the task raises ``CancelledError`` in the awaiting coroutine
    while the offloaded THREAD stays blocked in ``proc.communicate()``. Before
    this, MinerU kept running until its own wall timeout — minutes — and the
    supervisor could not reach it either, because ``start_new_session=True``
    puts it outside the process group the supervisor sweeps (#467, #499).
    """

    def test_a_registered_subprocess_is_terminated(self) -> None:
        # A real, session-detached process standing in for MinerU: same
        # spawn discipline, so the registry and the group signal are
        # exercised exactly as they are in production.
        proc = subprocess.Popen(  # noqa: S603
            ["/bin/sleep", "300"],  # noqa: S607
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert os.getpgid(proc.pid) == proc.pid, (
            "the stand-in must be session-detached, or this test passes "
            "for the wrong reason — the supervisor's group sweep would "
            "already have caught it (#499)"
        )
        with textbook_parser._LIVE_LOCK:
            textbook_parser._LIVE_MINERU.add(proc)
        try:
            terminated = textbook_parser.terminate_live_mineru(grace_s=1.0)
            assert terminated == 1
            proc.wait(timeout=5)
            assert not _pid_alive(proc.pid), "MinerU stand-in outlived shutdown"
        finally:
            with textbook_parser._LIVE_LOCK:
                textbook_parser._LIVE_MINERU.discard(proc)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_shutdown_reaches_the_terminator(self) -> None:
        """The tracker must actually call it, in a thread, before gathering."""
        proc = subprocess.Popen(  # noqa: S603
            ["/bin/sleep", "300"],  # noqa: S607
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        with textbook_parser._LIVE_LOCK:
            textbook_parser._LIVE_MINERU.add(proc)

        async def _run() -> None:
            tracker = ParseTaskTracker()
            # shutdown() returns early on an empty registry, so give it a
            # task to make the real path run.
            tracker._tasks["slug"] = asyncio.create_task(asyncio.sleep(60))
            await tracker.shutdown(timeout_seconds=5.0)

        try:
            asyncio.run(_run())
            proc.wait(timeout=5)
            assert not _pid_alive(proc.pid), (
                "ParseTaskTracker.shutdown must terminate live MinerU "
                "subprocesses, not only cancel the wrappers (#500)"
            )
        finally:
            with textbook_parser._LIVE_LOCK:
                textbook_parser._LIVE_MINERU.discard(proc)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_terminating_nothing_is_safe(self) -> None:
        with textbook_parser._LIVE_LOCK:
            assert not textbook_parser._LIVE_MINERU
        assert textbook_parser.terminate_live_mineru() == 0
