"""``tool_calls`` audit-store tests (stage2/arx-a23, WS-A A2 — AC-A.9).

Covers: append/tail round-trip, the ring bound (insert N+1 over the
cap evicts oldest), the sanitize pipeline (filesystem-path redaction
per the AC's named test, injection-literal strip, truncation),
session-id prefixing, and the never-raise module-level appender.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from server.audit import (
    ARGS_SUMMARY_MAX_CHARS,
    SESSION_ID_PREFIX_LEN,
    ToolCallAuditStore,
    ToolCallRecord,
    append_tool_call,
    sanitize_audit_text,
    set_audit_store,
)


def _record(**overrides) -> ToolCallRecord:
    base = {
        "tool": "search_papers",
        "outcome": "ok",
        "profile": "default",
        "session_id": "abcdef0123456789abcdef0123456789",
        "role": "sketcher",
        "notebook": None,
        "latency_ms": 12.5,
        "cache_tier": "tier1",
        "result_bytes": 2048,
        "error_code": None,
        "args_summary": "stability conditions on K3 surfaces",
    }
    base.update(overrides)
    return ToolCallRecord(**base)


class TestAppendAndTail:
    def test_round_trip_newest_first(self, tmp_path: Path) -> None:
        async def _run() -> None:
            store = await ToolCallAuditStore.open(tmp_path / "audit.db")
            try:
                await store.append(_record(tool="search_papers"))
                await store.append(_record(tool="get_chunk", outcome="error",
                                           error_code="ValueError"))
                rows = await store.tail(limit=10)
                assert [r["tool"] for r in rows] == ["get_chunk", "search_papers"]
                assert rows[0]["outcome"] == "error"
                assert rows[0]["error_code"] == "ValueError"
                assert rows[1]["cache_tier"] == "tier1"
                assert rows[1]["result_bytes"] == 2048
                assert rows[1]["ts"]  # stamped at append
                assert await store.count() == 2
            finally:
                await store.close()

        asyncio.run(_run())

    def test_session_id_stored_as_16_char_prefix(self, tmp_path: Path) -> None:
        async def _run() -> None:
            store = await ToolCallAuditStore.open(tmp_path / "audit.db")
            try:
                full = "abcdef0123456789abcdef0123456789"
                await store.append(_record(session_id=full))
                rows = await store.tail(limit=1)
                assert rows[0]["session_id"] == full[:SESSION_ID_PREFIX_LEN]
                assert len(rows[0]["session_id"]) == 16
            finally:
                await store.close()

        asyncio.run(_run())


class TestRingBound:
    def test_insert_over_cap_evicts_oldest(self, tmp_path: Path) -> None:
        """AC-A.9: 'The store is ring-bounded (insert N+1 over the cap
        evicts oldest).'"""

        async def _run() -> None:
            store = await ToolCallAuditStore.open(
                tmp_path / "audit.db", max_rows=5
            )
            try:
                for i in range(6):
                    await store.append(_record(args_summary=f"query-{i}"))
                assert await store.count() == 5
                rows = await store.tail(limit=10)
                summaries = [r["args_summary"] for r in rows]
                assert "query-0" not in summaries, "oldest row must be evicted"
                assert summaries[0] == "query-5"
            finally:
                await store.close()

        asyncio.run(_run())


class TestSanitize:
    def test_filesystem_path_in_query_stored_redacted(self, tmp_path: Path) -> None:
        """The AC-A.9 named test: a query containing a filesystem path
        is stored redacted (absolute prefix scrubbed to var/arxmcp/)."""

        async def _run() -> None:
            store = await ToolCallAuditStore.open(tmp_path / "audit.db")
            try:
                await store.append(_record(
                    args_summary=(
                        "find /Users/chris.dare/Source Code/arXMCP/"
                        "var/arxmcp/notebooks/secret-nb/papers.txt"
                    ),
                ))
                rows = await store.tail(limit=1)
                stored = rows[0]["args_summary"]
                assert "chris.dare" not in stored, "home dir leaked"
                assert "var/arxmcp/notebooks/secret-nb/papers.txt" in stored
            finally:
                await store.close()

        asyncio.run(_run())

    def test_sanitize_strips_injection_literals(self) -> None:
        text = "before <|system|> mid [INST] end <|im_start|>"
        out = sanitize_audit_text(text)
        assert "<|system|>" not in out
        assert "[INST]" not in out
        assert "<|im_start|>" not in out
        assert out.startswith("before ")

    def test_sanitize_truncates(self) -> None:
        out = sanitize_audit_text("x" * 10_000)
        assert len(out) == ARGS_SUMMARY_MAX_CHARS

    def test_windows_style_path_redacted(self) -> None:
        out = sanitize_audit_text(
            r"C:\Users\cedar\Documents\repo\var\arxmcp\cache\notebooks.db"
        )
        assert "cedar" not in out


class TestModuleLevelAppender:
    def test_no_store_bound_returns_false(self) -> None:
        async def _run() -> bool:
            return await append_tool_call(_record())

        assert asyncio.run(_run()) is False

    def test_bound_store_returns_true_and_lands_row(self, tmp_path: Path) -> None:
        async def _run() -> None:
            store = await ToolCallAuditStore.open(tmp_path / "audit.db")
            set_audit_store(store)
            try:
                assert await append_tool_call(_record()) is True
                assert await store.count() == 1
            finally:
                set_audit_store(None)
                await store.close()

        asyncio.run(_run())

    def test_broken_store_swallows_and_returns_false(self, tmp_path: Path) -> None:
        """The appender must never raise into a request path."""

        class _Broken:
            async def append(self, record) -> int:
                raise RuntimeError("disk full")

        set_audit_store(_Broken())  # type: ignore[arg-type]
        try:
            assert asyncio.run(append_tool_call(_record())) is False
        finally:
            set_audit_store(None)
