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


#: A valid UUID4-hex session-id used by tests that need cap
#: enforcement to engage. Must be 32 lowercase hex chars (matching
#: the FastMCP ``StreamableHTTPSessionManager``'s ``uuid4().hex``
#: format). The F2 fix from the E08_S04 critique rejects non-matching
#: strings as a defense against trivial cap bypass via spoofed
#: session-ids.
_DEFAULT_VALID_SESSION_ID = "abcdef0123456789abcdef0123456789"


def _make_scope(
    *,
    path: str = "/mcp",
    method: str = "POST",
    session_id: str | None = _DEFAULT_VALID_SESSION_ID,
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


def _hex_session_id(seed: str) -> str:
    """Build a deterministic, valid UUID4-hex format string from
    ``seed``. Used by tests that need DISTINCT session-ids."""
    import hashlib
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


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
    """AC: a session that exhausts the ``search_papers`` cap receives
    ``RETRIEVAL_CAP_REACHED`` on the next call. Expressed relative to
    :data:`MAX_SEARCH_PAPERS_CALLS` — the cap is configurable
    (agent-platform-m1), so the boundary is N/N+1, not 3/4."""

    def test_search_papers_calls_up_to_cap_pass_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id=_hex_session_id("s-search-3-pass"))
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
            scope = _make_scope(session_id=_hex_session_id("s-search-cap"))
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
    """AC: a session that exhausts the ``get_chunk`` cap receives
    ``RETRIEVAL_CAP_REACHED`` on the next call. Expressed relative to
    :data:`MAX_GET_CHUNK_CALLS` — see :class:`TestSearchPapersCap`."""

    def test_get_chunk_calls_up_to_cap_pass_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id=_hex_session_id("s-chunk-4-pass"))
            body = _make_jsonrpc_body("tools/call", "get_chunk")
            for i in range(MAX_GET_CHUNK_CALLS):
                received, sent = await _drive_middleware(mw, scope, body)
                assert received, f"get_chunk call #{i+1} should pass"
        asyncio.run(_run())

    def test_get_chunk_fifth_call_returns_retrieval_cap_reached(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id=_hex_session_id("s-chunk-cap"))
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
            scope_a = _make_scope(session_id=_hex_session_id("session-A"))
            scope_b = _make_scope(session_id=_hex_session_id("session-B"))
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
            scope = _make_scope(path="/healthz", session_id=_hex_session_id("s-health"))
            body = _make_jsonrpc_body("tools/call", "search_papers")
            received, _ = await _drive_middleware(mw, scope, body)
            assert received

        asyncio.run(_run())

    def test_non_post_method_passes_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(method="GET", session_id=_hex_session_id("s-get"))
            received, _ = await _drive_middleware(mw, scope, body=b"")
            assert received

        asyncio.run(_run())

    def test_non_tools_call_method_passes_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id=_hex_session_id("s-init"))
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
            scope = _make_scope(session_id=_hex_session_id("s-other-tool"))
            # ``get_definitions`` is NOT in TOOLS_WITH_CAPS.
            body = _make_jsonrpc_body("tools/call", "get_definitions")
            for _ in range(10):
                received, _ = await _drive_middleware(mw, scope, body)
                assert received

        asyncio.run(_run())

    def test_malformed_body_passes_through(self):
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id=_hex_session_id("s-malformed"))
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
        check + both increment past it. Over-subscribe the cap with
        concurrent ``search_papers`` increments — exactly
        :data:`MAX_SEARCH_PAPERS_CALLS` should succeed.

        The over-subscription is expressed relative to the cap
        (agent-platform-m1): the old literal 5-against-a-cap-of-3 stopped
        over-subscribing the moment the default rose to 30, which would
        have made the race guard silently vacuous rather than failing."""

        async def _run():
            state = await get_or_create_session("session-race")

            async def attempt() -> bool:
                ok, _, _ = await check_and_increment(state, "search_papers")
                return ok

            attempts = MAX_SEARCH_PAPERS_CALLS + 2
            results = await asyncio.gather(*(attempt() for _ in range(attempts)))
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
            scope = _make_scope(session_id=_hex_session_id("s-envelope"))
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
    """agent-platform-m1 pins the interactive defaults at 30
    search_papers and 100 get_chunk (raised from the E08_S04 values of
    3 and 4, which fired on legitimate single-question research).

    Pin the constants here so a future edit catches the eye. These are
    the DEFAULTS; operators override via ARXMCP_MAX_SEARCH_PAPERS_CALLS
    / ARXMCP_MAX_GET_CHUNK_CALLS (see TestCapConfiguration)."""

    def test_max_search_papers_default_is_30(self):
        assert MAX_SEARCH_PAPERS_CALLS == 30

    def test_max_get_chunk_default_is_100(self):
        assert MAX_GET_CHUNK_CALLS == 100


class TestCapConfiguration:
    """agent-platform-m1 — the caps are operator-configurable, and the
    env vars are declared on Config so they do not trip the
    ``extra="forbid"`` startup scan."""

    def test_config_fields_read_the_env_vars(self, monkeypatch):
        from server.config import Config

        monkeypatch.setenv("ARXMCP_MAX_SEARCH_PAPERS_CALLS", "7")
        monkeypatch.setenv("ARXMCP_MAX_GET_CHUNK_CALLS", "11")
        cfg = Config()
        assert cfg.max_search_papers_calls == 7
        assert cfg.max_get_chunk_calls == 11

    def test_configure_caps_rebinds_the_module_globals(self, monkeypatch):
        """The effective cap — the value check_both_caps reads —
        reflects the configured value."""
        import server.session as session_mod
        from server.config import Config

        monkeypatch.setattr(session_mod, "MAX_SEARCH_PAPERS_CALLS", 3)
        monkeypatch.setattr(session_mod, "MAX_GET_CHUNK_CALLS", 4)
        monkeypatch.setenv("ARXMCP_MAX_SEARCH_PAPERS_CALLS", "7")
        monkeypatch.setenv("ARXMCP_MAX_GET_CHUNK_CALLS", "11")

        session_mod.configure_caps(Config())

        assert session_mod.MAX_SEARCH_PAPERS_CALLS == 7
        assert session_mod.MAX_GET_CHUNK_CALLS == 11

    def test_configured_cap_is_the_enforced_cap(self, monkeypatch):
        """End to end: configure a cap of 2, and the 3rd call is the
        one that gets RETRIEVAL_CAP_REACHED."""
        import server.session as session_mod
        from server.config import Config

        # Register the restore BEFORE configure_caps rebinds the global:
        # monkeypatch remembers the pre-call value and puts it back at
        # teardown, so this test cannot leak a cap of 2 into the rest of
        # the module (configure_caps has no unset path of its own).
        monkeypatch.setattr(
            session_mod,
            "MAX_SEARCH_PAPERS_CALLS",
            session_mod.MAX_SEARCH_PAPERS_CALLS,
        )
        monkeypatch.setenv("ARXMCP_MAX_SEARCH_PAPERS_CALLS", "2")
        session_mod.configure_caps(Config())

        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id=_hex_session_id("s-configured"))
            body = _make_jsonrpc_body("tools/call", "search_papers")
            for i in range(2):
                received, _ = await _drive_middleware(mw, scope, body)
                assert received, f"call #{i+1} should pass under cap=2"
            received, sent = await _drive_middleware(mw, scope, body)
            assert not received
            structured = _extract_response_body(sent)["result"][
                "structuredContent"
            ]
            assert structured["code"] == "RETRIEVAL_CAP_REACHED"
            assert structured["limit"] == 2

        asyncio.run(_run())

    def test_env_vars_are_declared_so_startup_scan_accepts_them(
        self, monkeypatch
    ):
        """Regression guard for the failure mode a raw os.getenv
        implementation would have shipped: an undeclared ARXMCP_* var
        makes the server refuse to boot, so setting the documented
        knob would have been worse than not having it."""
        from server.config import Config
        from server.main import _scan_unknown_arxmcp_env_vars

        monkeypatch.setenv("ARXMCP_MAX_SEARCH_PAPERS_CALLS", "30")
        monkeypatch.setenv("ARXMCP_MAX_GET_CHUNK_CALLS", "100")
        _scan_unknown_arxmcp_env_vars(Config())  # must not raise

    def test_cap_below_one_is_rejected(self, monkeypatch):
        """A cap of 0 would reject every retrieval call, which reads as
        a broken server rather than a tight budget. ge=1 catches it at
        startup instead."""
        import pytest
        from pydantic import ValidationError

        from server.config import Config

        monkeypatch.setenv("ARXMCP_MAX_SEARCH_PAPERS_CALLS", "0")
        with pytest.raises(ValidationError):
            Config()


# ===========================================================================
# E08_S04 critique rectification guards (F2, F6, F7, F9)
# ===========================================================================


class TestRectificationGuards:
    """Regression guards for the E08_S04 critique findings F2
    (session-id format check), F6 (LRU eviction), F7 (middleware
    order), F9 (Prometheus counter)."""

    # The FastMCP-issued id format: 32 lowercase hex chars (uuid4().hex).
    _VALID_ID = "0123456789abcdef0123456789abcdef"

    def test_f2_spoofed_non_hex_session_id_skips_cap(self):
        """F2 fix: a session-id that doesn't match the UUID4-hex
        format MUST be excluded from cap accounting. The cap
        middleware passes through; FastMCP itself will then reject
        the unknown session-id."""
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="attacker-spoof-1")
            body = _make_jsonrpc_body("tools/call", "search_papers")
            # 5 spoofed-id requests should all pass through the
            # cap middleware (the cap doesn't apply because the
            # session-id is invalid format).
            for _ in range(5):
                received, _ = await _drive_middleware(mw, scope, body)
                assert received, (
                    "spoofed (non-UUID4-hex) session-id should NOT "
                    "engage cap enforcement; FastMCP rejects it later."
                )
            # Crucially: NO SessionState entries created for spoofed ids.
            assert get_session_count() == 0
        asyncio.run(_run())

    def test_f2_uppercase_hex_session_id_is_rejected_as_format(self):
        """F2 fix: only LOWERCASE hex chars match the FastMCP
        ``uuid4().hex`` format. Mixed-case strings are spoof
        candidates."""
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id="ABCDEF" * 5 + "AB")
            body = _make_jsonrpc_body("tools/call", "search_papers")
            received, _ = await _drive_middleware(mw, scope, body)
            assert received
            assert get_session_count() == 0
        asyncio.run(_run())

    def test_f2_valid_format_session_id_engages_cap(self):
        """F2: a session-id that matches the UUID4-hex format DOES
        engage cap enforcement. The 4th call hits the cap."""
        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            scope = _make_scope(session_id=self._VALID_ID)
            body = _make_jsonrpc_body("tools/call", "search_papers")
            for _ in range(MAX_SEARCH_PAPERS_CALLS):
                await _drive_middleware(mw, scope, body)
            received, sent = await _drive_middleware(mw, scope, body)
            assert not received
            response = _extract_response_body(sent)
            assert (
                response["result"]["structuredContent"]["code"]
                == "RETRIEVAL_CAP_REACHED"
            )
        asyncio.run(_run())

    def test_f6_lru_eviction_drops_oldest_when_registry_full(self, monkeypatch):
        """F6 fix: when the registry is at MAX_REGISTRY_SIZE,
        creating a new SessionState evicts the LRU (oldest)
        entry. Patch the cap to a tiny value so the test is fast."""
        import server.session as session_mod

        monkeypatch.setattr(session_mod, "MAX_REGISTRY_SIZE", 4)

        async def _run():
            # Create 5 sessions; the first MUST be evicted.
            await get_or_create_session("a" * 32)
            await get_or_create_session("b" * 32)
            await get_or_create_session("c" * 32)
            await get_or_create_session("d" * 32)
            assert get_session_count() == 4

            await get_or_create_session("e" * 32)
            assert get_session_count() == 4
            # The oldest ("a"*32) was evicted; "e"*32 was inserted.
            # Verify by re-fetching: a fetch creates a NEW state
            # (because the previous one was evicted), so search_count
            # is back to 0.
            new_a = await get_or_create_session("a" * 32)
            assert new_a.search_count == 0
            # And: this fetch evicts ANOTHER entry.
            assert get_session_count() == 4

        asyncio.run(_run())

    def test_f6_lru_eviction_promotes_recently_used_entry(self, monkeypatch):
        """F6 sub-test: ``move_to_end`` on a registry hit means the
        most-recently-used entry is NOT evicted next."""
        import server.session as session_mod

        monkeypatch.setattr(session_mod, "MAX_REGISTRY_SIZE", 3)

        async def _run():
            await get_or_create_session("a" * 32)
            await get_or_create_session("b" * 32)
            await get_or_create_session("c" * 32)
            # Touch "a" — moves it to most-recently-used.
            await get_or_create_session("a" * 32)
            # Inserting a new entry should now evict "b" (not "a").
            await get_or_create_session("d" * 32)
            # "a" is still alive (just touched).
            a_state = await get_or_create_session("a" * 32)
            assert a_state.search_count == 0  # never incremented but alive
            # Touching "b" (which was evicted) creates a fresh state.
            b_state = await get_or_create_session("b" * 32)
            assert b_state.search_count == 0  # fresh, was evicted

        asyncio.run(_run())

    def test_f7_middleware_order_session_cap_inside_request_body_size_limit(self):
        """F7 fix: assert the middleware mount order so a future
        refactor that inverts it (turning SessionCapMiddleware
        into a memory-DoS surface) fails at test time.

        Expected request flow:
            SecurityHeaders -> OriginValidation -> HostValidation
                -> RequestBodySizeLimit -> SessionCap
                -> BodySizeCap -> handler

        SessionCap MUST be INSIDE RequestBodySizeLimit so a
        100MB malicious body is 413-rejected BEFORE SessionCap
        buffers it."""
        from server.config import Config
        from server.main import create_app
        from server.middleware import (
            HostValidationMiddleware,
            OriginValidationMiddleware,
            RequestBodySizeLimitMiddleware,
            SecurityHeadersMiddleware,
            SessionCapMiddleware,
        )

        app = create_app(Config())
        # FastAPI exposes ``app.user_middleware`` as a list of
        # Middleware namedtuples in MOUNT order. Add-order is LIFO
        # for request flow, so the LAST add wraps OUTERMOST.
        cls_in_mount_order = [m.cls for m in app.user_middleware]
        # FastAPI stores user_middleware in OUTERMOST-first order
        # (because it iterates in the same order it adds). Reverse
        # for inner-to-outer comparison.
        actual_inner_to_outer = list(reversed(cls_in_mount_order))

        # The load-bearing invariant for F7 is the RELATIVE order:
        # SessionCap MUST be INSIDE RequestBodySizeLimit so a
        # malicious 100 MB body is 413-rejected before SessionCap
        # buffers it. Asserting the full list as equality has caused
        # spurious failures every time a new middleware was added
        # (E14_S02 added TracingContextMiddleware as the new
        # innermost wrapper). Switch to a relative-ordering check
        # that survives additive middleware changes while still
        # catching a malicious refactor that swaps the two key
        # layers.
        sc_idx = actual_inner_to_outer.index(SessionCapMiddleware)
        rbsl_idx = actual_inner_to_outer.index(RequestBodySizeLimitMiddleware)
        assert sc_idx < rbsl_idx, (
            f"SessionCapMiddleware MUST stay INSIDE "
            f"RequestBodySizeLimitMiddleware so a malicious 100MB "
            f"request is 413-rejected before SessionCap buffers it. "
            f"Got inner→outer: {actual_inner_to_outer}"
        )
        # Secondary invariants — these surfaced bugs in the past so
        # we keep them as explicit assertions even though they're
        # not the F7 fix:
        host_idx = actual_inner_to_outer.index(HostValidationMiddleware)
        origin_idx = actual_inner_to_outer.index(OriginValidationMiddleware)
        sec_idx = actual_inner_to_outer.index(SecurityHeadersMiddleware)
        assert rbsl_idx < host_idx < origin_idx < sec_idx, (
            f"Outer-layer order regressed: expected RequestBodySize → "
            f"HostValidation → OriginValidation → SecurityHeaders "
            f"(inner→outer). Got: {actual_inner_to_outer}"
        )

    def test_f9_cap_rejection_increments_prometheus_counter(self):
        """F9 fix: a cap rejection must increment the Prometheus
        counter ``arxmcp_retrieval_cap_rejections_total{tool}``.
        Without this, operators have no visibility into how often
        caps fire (FastMCP-side per-tool counters are bypassed)."""
        from server.metrics import RETRIEVAL_CAP_REJECTIONS_COUNTER

        # Reset the counter to 0 for the tool we're about to exercise.
        RETRIEVAL_CAP_REJECTIONS_COUNTER.labels(tool="search_papers")._value.set(0)

        async def _run():
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            # Use a valid-format session-id so cap engages.
            scope = _make_scope(session_id="0" * 32)
            body = _make_jsonrpc_body("tools/call", "search_papers")
            # Fill the cap; the next call rejects.
            for _ in range(MAX_SEARCH_PAPERS_CALLS):
                await _drive_middleware(mw, scope, body)
            await _drive_middleware(mw, scope, body)
            await _drive_middleware(mw, scope, body)
            # Counter incremented at least 2x (the two over-cap calls).
            count = RETRIEVAL_CAP_REJECTIONS_COUNTER.labels(
                tool="search_papers"
            )._value.get()
            assert count >= 2

        asyncio.run(_run())


class TestBatchCapByN:
    """agent-platform-t-batch-chunk-fetch (#83): a batched get_chunk
    consumes N per-tool cap units, not 1."""

    def test_batch_increments_chunk_count_by_n(self, monkeypatch):
        import server.session as sm
        monkeypatch.setattr(sm, "MAX_GET_CHUNK_CALLS", 100)

        async def _run_():
            state = sm.SessionState(session_id="0" * 32)
            verdict, count, limit = await sm.check_both_caps(
                state, "get_chunk", n=5
            )
            assert verdict == "allowed"
            assert state.chunk_count == 5  # by N, not 1
        asyncio.run(_run_())

    def test_batch_wholesale_rejected_when_over_cap(self, monkeypatch):
        import server.session as sm
        monkeypatch.setattr(sm, "MAX_GET_CHUNK_CALLS", 10)

        async def _run_():
            state = sm.SessionState(session_id="1" * 32)
            state.chunk_count = 8  # 8 used of 10
            # a batch of 5 would reach 13 > 10 -> whole batch rejected,
            # no partial serve, counter untouched.
            verdict, count, limit = await sm.check_both_caps(
                state, "get_chunk", n=5
            )
            assert verdict == "per_tool_rejected"
            assert state.chunk_count == 8  # unchanged
            assert count == 13  # attempted total
            assert limit == 10
        asyncio.run(_run_())

    def test_batch_exactly_at_cap_allowed(self, monkeypatch):
        import server.session as sm
        monkeypatch.setattr(sm, "MAX_GET_CHUNK_CALLS", 10)

        async def _run_():
            state = sm.SessionState(session_id="2" * 32)
            state.chunk_count = 5
            verdict, _, _ = await sm.check_both_caps(state, "get_chunk", n=5)
            assert verdict == "allowed"  # 5 + 5 == 10, not over
            assert state.chunk_count == 10
        asyncio.run(_run_())


class TestBatchLeakFix:
    """The middleware must charge N only for a batch the handler will
    actually serve — an invalid batch charges 0, so bad input can't burn
    the retrieval budget."""

    @staticmethod
    def _chunk_body(chunk_id) -> bytes:
        return json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "get_chunk", "arguments": {"chunk_id": chunk_id}},
        }).encode("utf-8")

    def _drive_and_count(self, chunk_id, seed):
        async def _run():
            reset_session_state_for_tests()
            mw = SessionCapMiddleware(app=None)  # type: ignore[arg-type]
            sid = _hex_session_id(seed)
            scope = _make_scope(session_id=sid)
            await _drive_middleware(mw, scope, self._chunk_body(chunk_id))
            state = await get_or_create_session(sid)
            return state.chunk_count
        return asyncio.run(_run())

    _GOOD = "arxiv:2401.00001:0123456789abcdef"

    def test_valid_batch_charges_n(self):
        n = self._drive_and_count([self._GOOD, self._GOOD, self._GOOD], "valid-b")
        assert n == 3

    def test_over_max_batch_charges_zero(self):
        ids = [f"arxiv:2401.{i:05d}:0123456789abcdef" for i in range(25)]
        assert self._drive_and_count(ids, "overmax-b") == 0

    def test_malformed_id_batch_charges_zero(self):
        assert self._drive_and_count([self._GOOD, "not-an-id"], "malformed-b") == 0

    def test_empty_batch_charges_zero(self):
        assert self._drive_and_count([], "empty-b") == 0

    def test_scalar_charges_one(self):
        assert self._drive_and_count(self._GOOD, "scalar-b") == 1
