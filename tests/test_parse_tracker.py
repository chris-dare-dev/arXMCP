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
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ingest.textbook_parser import MinerUResult
from ingest.textbook_renderer import RenderResult
from server.parse_tracker import (
    PARSE_ERROR_TAIL_MAX_BYTES,
    ParseTaskTracker,
    _format_parse_error,
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
