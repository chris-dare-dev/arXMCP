"""Per-session retrieval-cap tests (E08_S04 Rule 2).

Coverage map (acceptance criteria → test class):

  AC                                                              Test class
  ────────────────────────────────────────────────────────────────────────────
  search_papers x4 → RETRIEVAL_CAP_REACHED on the 4th call        TestSearchPapersCap
  get_chunk x5 → RETRIEVAL_CAP_REACHED on the 5th call            TestGetChunkCap

Plus:
- Cap counters are PER-SESSION (different session-ids don't share)
- Counter increments AT entry, BEFORE serving the call
- RETRIEVAL_CAP_REACHED envelope shape is correct (code, message,
  tool, limit, session_attempted_count, isError=True)
- Missing mcp-session-id header → cap enforcement skipped
- Non-tools/call methods (initialize, tools/list) bypass the cap
- Non-cap-tracked tool names (get_definitions etc.) bypass the cap
- Counter survives across multiple inflight async calls (per-
  session asyncio.Lock prevents the race)
- Reset hook clears the registry (test isolation)

The tests exercise the SessionCapMiddleware directly via a fake
ASGI scope/receive/send rather than through a TestClient — keeps
the surface focused on the cap behavior and avoids pulling in
LanceDB / BGE-M3 warm paths.
"""

from __future__ import annotations

import asyncio
import json

from server.middleware import SessionCapMiddleware
from server.session import (
    MAX_GET_CHUNK_CALLS,
    MAX_SEARCH_PAPERS_CALLS,
    check_and_increment,
    get_or_create_session,
    get_session_count,
    reset_session_state_for_tests,
)

# ---------------------------------------------------------------------------
# Helpers — fake ASGI scope/receive/send for direct middleware testing
# ---------------------------------------------------------------------------


def _make_scope(
    *,
    path: str = "/mcp",
    method: str = "POST",
    session_id: str | None = "session-abc-123",
) -> dict:
    headers: list[tuple[bytes, bytes]] = []
    if session_id is not None:
        headers.append((b"mcp-session-id", session_id.encode("ascii")))
    headers.append((b"content-type", b"application/json"))
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
    }


def _make_jsonrpc_body(
    method: str,
    tool_name: str | None,
    *,
    request_id: int = 1,
) -> bytes:
    if method != "tools/call":
        return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method}).encode()
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {"query": "demo"}},
        }
    ).encode("utf-8")


async def _drive_middleware(
    middleware: SessionCapMiddleware,
    scope: dict,
    body: bytes,
) -> tuple[list[dict], list[dict]]:
    """Drive ``middleware.__call__(scope, receive, send)`` once.

    Returns ``(received_by_inner_app, sent_events)``. If the
    middleware short-circuits, the inner-app list is empty and the
    sent events contain the synthesized error response.
    """
    received_by_inner: list[dict] = []

    async def fake_receive() -> dict:
        # Single-shot body event with more_body=False.
        return {"type": "http.request", "body": body, "more_body": False}

    sent: list[dict] = []

    async def fake_send(event: dict) -> None:
        sent.append(event)

    # Replace the underlying app with a recorder so we can tell
    # whether the middleware passed the request through.
    async def fake_app(scope: dict, receive, send) -> None:
        # Drain the receive stream to mimic a real handler.
        while True:
            evt = await receive()
            received_by_inner.append(evt)
            if evt["type"] == "http.disconnect":
                break
            if not evt.get("more_body", False):
                break
        # Emit a trivial 200 OK so the response shape is well-formed.
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"jsonrpc":"2.0","id":1,"result":{}}',
            "more_body": False,
        })

    middleware.app = fake_app
    await middleware(scope, fake_receive, fake_send)
    return received_by_inner, sent


def _extract_response_body(sent: list[dict]) -> dict:
    """Pull the JSON body out of an ASGI response stream."""
    body_events = [e for e in sent if e["type"] == "http.response.body"]
    raw = b"".join(e.get("body", b"") for e in body_events)
    return json.loads(raw.decode("utf-8"))


def _extract_status(sent: list[dict]) -> int:
    start = next(e for e in sent if e["type"] == "http.response.start")
    return start["status"]


# ===========================================================================
# AC — search_papers cap at 3 (4th call rejected)
# ===========================================================================


class TestSearchPapersCap:
    """AC: a session that calls ``search_papers`` four times receives
    ``RETRIEVAL_CAP_REACHED`` on the fourth call."""

    def test_search_papers_first_three_calls_pass_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="s-search-3-pass")
            body = _make_jsonrpc_body("tools/call", "search_papers")
            for i in range(MAX_SEARCH_PAPERS_CALLS):
                received, sent = await _drive_middleware(mw, scope, body)
                # Inner app saw the request → middleware forwarded.
                assert received, f"call #{i+1} should pass through"
                # Status from the inner app's fake response.
                assert _extract_status(sent) == 200
        asyncio.run(_run())

    def test_search_papers_fourth_call_returns_retrieval_cap_reached(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="s-search-cap")
            body = _make_jsonrpc_body("tools/call", "search_papers")
            # Drive the first 3 calls (within cap).
            for _ in range(MAX_SEARCH_PAPERS_CALLS):
                await _drive_middleware(mw, scope, body)
            # The 4th call MUST be rejected.
            received, sent = await _drive_middleware(mw, scope, body)
            assert not received, (
                "4th search_papers call should be short-circuited; "
                "the inner app should NOT see it."
            )
            response = _extract_response_body(sent)
            assert response["jsonrpc"] == "2.0"
            result = response["result"]
            assert result["isError"] is True
            structured = result["structuredContent"]
            assert structured["code"] == "RETRIEVAL_CAP_REACHED"
            assert structured["tool"] == "search_papers"
            assert structured["limit"] == MAX_SEARCH_PAPERS_CALLS
            assert structured["session_attempted_count"] == MAX_SEARCH_PAPERS_CALLS + 1

        asyncio.run(_run())


# ===========================================================================
# AC — get_chunk cap at 4 (5th call rejected)
# ===========================================================================


class TestGetChunkCap:
    """AC: a session that calls ``get_chunk`` five times receives
    ``RETRIEVAL_CAP_REACHED`` on the fifth call."""

    def test_get_chunk_first_four_calls_pass_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="s-chunk-4-pass")
            body = _make_jsonrpc_body("tools/call", "get_chunk")
            for i in range(MAX_GET_CHUNK_CALLS):
                received, sent = await _drive_middleware(mw, scope, body)
                assert received, f"get_chunk call #{i+1} should pass"
        asyncio.run(_run())

    def test_get_chunk_fifth_call_returns_retrieval_cap_reached(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="s-chunk-cap")
            body = _make_jsonrpc_body("tools/call", "get_chunk")
            for _ in range(MAX_GET_CHUNK_CALLS):
                await _drive_middleware(mw, scope, body)
            received, sent = await _drive_middleware(mw, scope, body)
            assert not received
            response = _extract_response_body(sent)
            structured = response["result"]["structuredContent"]
            assert structured["code"] == "RETRIEVAL_CAP_REACHED"
            assert structured["tool"] == "get_chunk"
            assert structured["limit"] == MAX_GET_CHUNK_CALLS
            assert structured["session_attempted_count"] == MAX_GET_CHUNK_CALLS + 1

        asyncio.run(_run())


# ===========================================================================
# Per-session isolation
# ===========================================================================


class TestPerSessionIsolation:
    """Each MCP session has its own cap counter; one session
    reaching the cap MUST NOT affect another."""

    def test_two_sessions_have_independent_search_counters(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            body = _make_jsonrpc_body("tools/call", "search_papers")
            scope_a = _make_scope(session_id="session-A")
            scope_b = _make_scope(session_id="session-B")
            # Exhaust session A's quota.
            for _ in range(MAX_SEARCH_PAPERS_CALLS):
                await _drive_middleware(mw, scope_a, body)
            # Session A's 4th call rejected.
            received_a, _ = await _drive_middleware(mw, scope_a, body)
            assert not received_a
            # Session B should still have full quota.
            received_b, _ = await _drive_middleware(mw, scope_b, body)
            assert received_b, (
                "session B's first call should NOT be affected by "
                "session A reaching its cap."
            )
        asyncio.run(_run())


# ===========================================================================
# Pass-through paths — middleware doesn't interfere
# ===========================================================================


class TestPassThroughPaths:
    """The cap MUST NOT interfere with: missing session-id, non-mcp
    paths, non-POST methods, non-tools/call methods, non-capped tool
    names, and malformed JSON bodies."""

    def test_missing_mcp_session_id_skips_cap_enforcement(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id=None)  # no header
            body = _make_jsonrpc_body("tools/call", "search_papers")
            # 4 consecutive calls all pass through — no cap.
            for _ in range(MAX_SEARCH_PAPERS_CALLS + 1):
                received, _sent = await _drive_middleware(mw, scope, body)
                assert received, "without session-id, cap is skipped"
        asyncio.run(_run())

    def test_non_mcp_path_passes_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(path="/healthz", session_id="s-health")
            body = _make_jsonrpc_body("tools/call", "search_papers")
            received, _ = await _drive_middleware(mw, scope, body)
            assert received

        asyncio.run(_run())

    def test_non_post_method_passes_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(method="GET", session_id="s-get")
            received, _ = await _drive_middleware(mw, scope, body=b"")
            assert received

        asyncio.run(_run())

    def test_non_tools_call_method_passes_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="s-init")
            body = _make_jsonrpc_body("initialize", tool_name=None)
            # Drive 5 calls — none should hit the cap (initialize is
            # not in TOOLS_WITH_CAPS).
            for _ in range(5):
                received, _ = await _drive_middleware(mw, scope, body)
                assert received

        asyncio.run(_run())

    def test_non_capped_tool_name_passes_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="s-other-tool")
            # ``get_definitions`` is NOT in TOOLS_WITH_CAPS.
            body = _make_jsonrpc_body("tools/call", "get_definitions")
            for _ in range(10):
                received, _ = await _drive_middleware(mw, scope, body)
                assert received

        asyncio.run(_run())

    def test_malformed_body_passes_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="s-malformed")
            received, _ = await _drive_middleware(mw, scope, body=b"not json {{")
            # Should NOT raise; should pass to the inner app
            # (which would then emit its own JSON-RPC error).
            assert received

        asyncio.run(_run())


# ===========================================================================
# SessionState invariants — direct API tests
# ===========================================================================


class TestSessionStateAPI:
    """Direct tests on the ``server.session`` API — no middleware
    involved. Verifies the per-session state primitives the
    middleware composes."""

    def test_get_or_create_session_returns_same_instance_for_same_id(self):
        async def _run():
            a = await get_or_create_session("session-X")
            b = await get_or_create_session("session-X")
            assert a is b

        asyncio.run(_run())

    def test_get_or_create_session_returns_distinct_for_different_ids(self):
        async def _run():
            a = await get_or_create_session("session-X")
            b = await get_or_create_session("session-Y")
            assert a is not b
            assert a.session_id == "session-X"
            assert b.session_id == "session-Y"

        asyncio.run(_run())

    def test_check_and_increment_search_within_cap(self):
        async def _run():
            state = await get_or_create_session("session-Z")
            allowed, count, limit = await check_and_increment(state, "search_papers")
            assert allowed is True
            assert count == 1
            assert limit == MAX_SEARCH_PAPERS_CALLS

        asyncio.run(_run())

    def test_check_and_increment_returns_false_at_cap(self):
        async def _run():
            state = await get_or_create_session("session-W")
            for _ in range(MAX_SEARCH_PAPERS_CALLS):
                ok, _, _ = await check_and_increment(state, "search_papers")
                assert ok
            # The next call MUST be rejected.
            allowed, count, limit = await check_and_increment(state, "search_papers")
            assert allowed is False
            assert count == MAX_SEARCH_PAPERS_CALLS + 1
            assert limit == MAX_SEARCH_PAPERS_CALLS
            # Internal state remains at the cap (didn't increment further).
            assert state.search_count == MAX_SEARCH_PAPERS_CALLS

        asyncio.run(_run())

    def test_check_and_increment_unrecognized_tool_passes(self):
        async def _run():
            state = await get_or_create_session("session-U")
            allowed, count, limit = await check_and_increment(state, "get_definitions")
            assert allowed is True
            assert count == 0
            assert limit == 0

        asyncio.run(_run())

    def test_concurrent_increments_under_per_session_lock_serialize(self):
        """Per-session ``asyncio.Lock`` MUST serialize concurrent
        increments so two parallel callers can't both pass the cap
        check + both increment past it. Drive 5 concurrent
        ``search_papers`` increments — exactly 3 should succeed."""

        async def _run():
            state = await get_or_create_session("session-race")

            async def attempt() -> bool:
                ok, _, _ = await check_and_increment(state, "search_papers")
                return ok

            results = await asyncio.gather(*(attempt() for _ in range(5)))
            successes = sum(1 for r in results if r)
            assert successes == MAX_SEARCH_PAPERS_CALLS
            assert state.search_count == MAX_SEARCH_PAPERS_CALLS

        asyncio.run(_run())

    def test_reset_session_state_clears_registry(self):
        async def _run():
            await get_or_create_session("a")
            await get_or_create_session("b")
            assert get_session_count() == 2
            reset_session_state_for_tests()
            assert get_session_count() == 0

        asyncio.run(_run())


# ===========================================================================
# RETRIEVAL_CAP_REACHED envelope shape
# ===========================================================================


class TestRetrievalCapEnvelope:
    """Pin the structured-error envelope shape so a future
    middleware refactor can't quietly drop fields."""

    def test_envelope_has_required_fields(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="s-envelope")
            body = _make_jsonrpc_body(
                "tools/call", "search_papers", request_id=42,
            )
            for _ in range(MAX_SEARCH_PAPERS_CALLS):
                await _drive_middleware(mw, scope, body)
            _, sent = await _drive_middleware(mw, scope, body)
            response = _extract_response_body(sent)
            # JSON-RPC envelope.
            assert response["jsonrpc"] == "2.0"
            assert response["id"] == 42
            # CallToolResult shape.
            result = response["result"]
            assert "content" in result
            assert "structuredContent" in result
            assert result["isError"] is True
            # content[0] is a TextContent carrying the structured payload.
            assert result["content"][0]["type"] == "text"
            inner = json.loads(result["content"][0]["text"])
            assert inner == result["structuredContent"]
            # Required structuredContent fields.
            sc = result["structuredContent"]
            assert sc["code"] == "RETRIEVAL_CAP_REACHED"
            assert "message" in sc and isinstance(sc["message"], str)
            assert sc["tool"] == "search_papers"
            assert sc["limit"] == MAX_SEARCH_PAPERS_CALLS
            assert sc["session_attempted_count"] == MAX_SEARCH_PAPERS_CALLS + 1

        asyncio.run(_run())


# ===========================================================================
# Cap-constants pinned (regression guard for accidental brief drift)
# ===========================================================================


class TestCapConstants:
    """The brief pins the caps at 3 search_papers and 4 get_chunk.
    Pin the constants here so a future edit catches the eye."""

    def test_max_search_papers_is_3(self):
        assert MAX_SEARCH_PAPERS_CALLS == 3

    def test_max_get_chunk_is_4(self):
        assert MAX_GET_CHUNK_CALLS == 4
