"""CapabilityMiddleware tests (stage2/arx-a23, WS-A A2).

Coverage map (acceptance criteria → test class):

  AC                                                        Test class
  ──────────────────────────────────────────────────────────────────────
  AC-A.5  no token → default profile, flows unchanged       TestDefaultProfilePassThrough
  AC-A.6  allowlist deny envelope + tools/list unchanged    TestToolAllowlistDenial,
                                                            TestToolsListByteStability
  AC-A.7  profile caps supersede constants, no restart      TestProfileCapOverrides
  AC-A.8  server-side notebook scoping                      TestNotebookScoping
  AC-A.9  denied calls append exactly one audit row         TestDenialAuditRow
  AC-A.10 token never in logs / audit / responses           TestTokenHygiene

Middleware is driven directly via fake ASGI scope/receive/send (the
``tests/test_session_caps.py`` harness shape) — no LanceDB / model
warm paths. The profile store is the in-memory double from
``tests/test_capabilities.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from server import capabilities as cap
from server.capabilities import hash_token, set_capability_settings_store
from server.middleware import CapabilityMiddleware, SessionCapMiddleware

_VALID_SESSION_ID = "abcdef0123456789abcdef0123456789"


class _FakeSettingsStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)


def _set_profiles(profiles: dict[str, Any]) -> _FakeSettingsStore:
    store = _FakeSettingsStore()
    store.data[cap.CAPABILITY_PROFILES_KEY] = json.dumps(
        {"format_version": 1, "profiles": profiles}
    )
    set_capability_settings_store(store, cache_ttl_s=0.0)
    return store


def _scope(
    *,
    token: str | None = None,
    session_id: str | None = None,
    role: str | None = None,
    path: str = "/mcp",
    method: str = "POST",
) -> dict:
    headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode("ascii")))
    if session_id is not None:
        headers.append((b"mcp-session-id", session_id.encode("ascii")))
    if role is not None:
        headers.append((b"arxmcp-agent-role", role.encode("ascii")))
    return {"type": "http", "method": method, "path": path, "headers": headers}


def _tools_call_body(
    tool: str, *, arguments: dict | None = None, request_id: int = 1
) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {"query": "demo"}},
        }
    ).encode("utf-8")


def _jsonrpc_body(method: str, request_id: int = 1) -> bytes:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method}
    ).encode("utf-8")


async def _drive(
    asgi_app, scope: dict, body: bytes
) -> tuple[list[dict], list[dict]]:
    """Drive an ASGI callable once; returns (inner_received, sent)."""
    inner_received: list[dict] = []
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(event: dict) -> None:
        sent.append(event)

    async def inner_app(scope: dict, receive, send) -> None:
        while True:
            evt = await receive()
            inner_received.append(evt)
            if evt["type"] == "http.disconnect" or not evt.get("more_body", False):
                break
        await send({
            "type": "http.response.start", "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"jsonrpc":"2.0","id":1,"result":{}}',
            "more_body": False,
        })

    # Attach the recorder at the innermost position.
    node = asgi_app
    while hasattr(node, "app") and hasattr(node.app, "app"):
        node = node.app
    node.app = inner_app
    await asgi_app(scope, receive, send)
    return inner_received, sent


def _response_payload(sent: list[dict]) -> dict:
    body = b"".join(
        e.get("body", b"") for e in sent if e["type"] == "http.response.body"
    )
    return json.loads(body.decode("utf-8"))


def _denial_scope_of(sent: list[dict]) -> str:
    rpc = _response_payload(sent)
    structured = rpc["result"]["structuredContent"]
    assert rpc["result"]["isError"] is True
    assert structured["error_code"] == "CAPABILITY_DENIED"
    return structured["denial_scope"]


# ---------------------------------------------------------------------------
# AC-A.5 — default profile pass-through
# ---------------------------------------------------------------------------


class TestDefaultProfilePassThrough:
    def test_no_token_tools_call_passes_through(self) -> None:
        """No token, no configured profiles → the synthesized default
        forwards everything (day-one behavior). The full existing MCP
        suite passing with the middleware installed is the systemic
        half of AC-A.5 (asserted by the whole-suite run)."""
        mw = CapabilityMiddleware(app=None)
        inner, sent = asyncio.run(
            _drive(mw, _scope(), _tools_call_body("search_papers"))
        )
        assert inner, "request should reach the inner app"
        assert _response_payload(sent)["result"] == {}

    def test_no_token_all_eight_tools_pass(self) -> None:
        for tool in (
            "search_papers", "get_chunk", "find_equation", "get_definitions",
            "find_lemma_by_name", "get_paper", "cite_neighbors", "lean_verify",
        ):
            mw = CapabilityMiddleware(app=None)
            inner, _ = asyncio.run(_drive(mw, _scope(), _tools_call_body(tool)))
            assert inner, tool

    def test_non_tools_call_methods_bypass_policy(self) -> None:
        """initialize / tools/list are NEVER gated (D5) — even under a
        maximally restrictive default profile."""
        _set_profiles({"default": {"tools": {"allow": []}}})
        for method in ("initialize", "tools/list", "ping"):
            mw = CapabilityMiddleware(app=None)
            inner, _ = asyncio.run(_drive(mw, _scope(), _jsonrpc_body(method)))
            assert inner, method

    def test_non_mcp_paths_bypass(self) -> None:
        mw = CapabilityMiddleware(app=None)
        inner, _ = asyncio.run(
            _drive(mw, _scope(path="/api/v1/notebooks", method="GET"), b"")
        )
        assert inner

    def test_malformed_body_forwards_unchanged(self) -> None:
        mw = CapabilityMiddleware(app=None)
        inner, _ = asyncio.run(_drive(mw, _scope(), b"{not json"))
        assert inner


# ---------------------------------------------------------------------------
# AC-A.6 — tool allowlist denial
# ---------------------------------------------------------------------------


class TestToolAllowlistDenial:
    def test_unlisted_tool_denied_with_structured_envelope(self) -> None:
        _set_profiles({
            "narrow": {
                "token_sha256": hash_token("tok-narrow"),
                "tools": {"allow": ["search_papers"]},
            }
        })
        mw = CapabilityMiddleware(app=None)
        inner, sent = asyncio.run(
            _drive(mw, _scope(token="tok-narrow"), _tools_call_body("get_chunk"))
        )
        assert not inner, "denied call must not reach the inner app"
        assert _denial_scope_of(sent) == "tool_not_allowed"
        structured = _response_payload(sent)["result"]["structuredContent"]
        assert structured["tool"] == "get_chunk"
        assert structured["profile"] == "narrow"

    def test_listed_tool_passes(self) -> None:
        _set_profiles({
            "narrow": {
                "token_sha256": hash_token("tok-narrow"),
                "tools": {"allow": ["search_papers"]},
            }
        })
        mw = CapabilityMiddleware(app=None)
        inner, _ = asyncio.run(
            _drive(mw, _scope(token="tok-narrow"), _tools_call_body("search_papers"))
        )
        assert inner

    def test_unknown_token_denied(self) -> None:
        _set_profiles({
            "narrow": {"token_sha256": hash_token("real-token")}
        })
        mw = CapabilityMiddleware(app=None)
        inner, sent = asyncio.run(
            _drive(mw, _scope(token="stolen-guess"), _tools_call_body("search_papers"))
        )
        assert not inner
        assert _denial_scope_of(sent) == "token_unknown"

    def test_disabled_profile_denied(self) -> None:
        _set_profiles({
            "off": {"enabled": False, "token_sha256": hash_token("t-off")}
        })
        mw = CapabilityMiddleware(app=None)
        inner, sent = asyncio.run(
            _drive(mw, _scope(token="t-off"), _tools_call_body("search_papers"))
        )
        assert not inner
        assert _denial_scope_of(sent) == "profile_disabled"


# ---------------------------------------------------------------------------
# AC-A.6 second half — tools/list bytes byte-identical (BP1 guard)
# ---------------------------------------------------------------------------


class TestToolsListByteStability:
    def test_tools_list_hash_unchanged_with_capability_layer_active(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """The capability layer is mounted app-wide in create_app; the
        canonical tools/list hash must still equal the pinned constant
        (the same pin tests/test_server_tool_schema.py enforces).
        Restrictive profiles change NOTHING about the tool surface —
        gating is call-time only (D5)."""
        _set_profiles({
            "restrictive": {
                "token_sha256": hash_token("x"),
                "tools": {"allow": []},
            },
            "default": {"tools": {"allow": []}},
        })
        import server.query_encoder as qe_mod
        from tests.test_server_tool_schema import (
            _build_app_and_list_tools,
            _read_current_pin,
            compute_tool_schema_hash,
        )

        monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
        monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())
        tools = _build_app_and_list_tools(tmp_path)
        assert len(tools) == 8, "all 8 tools listed regardless of profiles"
        pinned_hash, _ = _read_current_pin()
        assert compute_tool_schema_hash(tools) == pinned_hash, (
            "tools/list bytes drifted — capability profiles must NEVER "
            "filter or reorder the tool surface (D5 / BP1)"
        )


# ---------------------------------------------------------------------------
# AC-A.7 — per-profile caps supersede the hardcoded constants
# ---------------------------------------------------------------------------


def _chain() -> CapabilityMiddleware:
    """Capability → SessionCap → (recorder), the create_app order."""
    return CapabilityMiddleware(app=SessionCapMiddleware(app=None))


class TestProfileCapOverrides:
    def test_profile_cap_of_5_permits_a_5th_search_call(self) -> None:
        _set_profiles({
            "wide": {
                "token_sha256": hash_token("tok-wide"),
                "caps": {"search_papers": 5},
            }
        })

        async def _run() -> None:
            chain = _chain()
            for i in range(5):
                inner, sent = await _drive(
                    chain,
                    _scope(token="tok-wide", session_id=_VALID_SESSION_ID),
                    _tools_call_body("search_papers"),
                )
                assert inner, f"call {i + 1} of 5 should pass under the profile cap"
            # 6th call rejects with the structured cap envelope.
            inner, sent = await _drive(
                chain,
                _scope(token="tok-wide", session_id=_VALID_SESSION_ID),
                _tools_call_body("search_papers"),
            )
            assert not inner
            structured = _response_payload(sent)["result"]["structuredContent"]
            assert structured["code"] == "RETRIEVAL_CAP_REACHED"
            assert structured["limit"] == 5

        asyncio.run(_run())

    def test_legacy_default_remains_3_without_profile_cap(self) -> None:
        async def _run() -> None:
            chain = _chain()
            for _ in range(3):
                inner, _sent = await _drive(
                    chain,
                    _scope(session_id=_VALID_SESSION_ID),
                    _tools_call_body("search_papers"),
                )
                assert inner
            inner, sent = await _drive(
                chain,
                _scope(session_id=_VALID_SESSION_ID),
                _tools_call_body("search_papers"),
            )
            assert not inner
            structured = _response_payload(sent)["result"]["structuredContent"]
            assert structured["code"] == "RETRIEVAL_CAP_REACHED"
            assert structured["limit"] == 3

        asyncio.run(_run())

    def test_cap_change_effective_without_restart(self) -> None:
        """AC-A.7's no-restart clause: tighten the default profile's
        get_chunk cap mid-session by writing the store — the very next
        call sees the new limit (TTL=0 read-through; the middleware
        chain object is never rebuilt)."""
        store = _set_profiles({})

        async def _run() -> None:
            chain = _chain()
            inner, _ = await _drive(
                chain,
                _scope(session_id=_VALID_SESSION_ID),
                _tools_call_body("get_chunk"),
            )
            assert inner  # 1st call, legacy cap 4

            # Operator tightens the cap to 1 at runtime.
            store.data[cap.CAPABILITY_PROFILES_KEY] = json.dumps(
                {"profiles": {"default": {"caps": {"get_chunk": 1}}}}
            )
            inner, sent = await _drive(
                chain,
                _scope(session_id=_VALID_SESSION_ID),
                _tools_call_body("get_chunk"),
            )
            assert not inner, "2nd call must reject under the new cap of 1"
            structured = _response_payload(sent)["result"]["structuredContent"]
            assert structured["limit"] == 1

        asyncio.run(_run())

    def test_profile_cap_on_untracked_tool(self) -> None:
        """Profile caps extend beyond the two legacy tools: a cap on
        get_definitions is enforced via the generic counter."""
        _set_profiles({
            "default": {"caps": {"get_definitions": 2}},
        })

        async def _run() -> None:
            chain = _chain()
            for _ in range(2):
                inner, _sent = await _drive(
                    chain,
                    _scope(session_id=_VALID_SESSION_ID),
                    _tools_call_body("get_definitions"),
                )
                assert inner
            inner, sent = await _drive(
                chain,
                _scope(session_id=_VALID_SESSION_ID),
                _tools_call_body("get_definitions"),
            )
            assert not inner
            structured = _response_payload(sent)["result"]["structuredContent"]
            assert structured["limit"] == 2

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# AC-A.8 — notebook scoping
# ---------------------------------------------------------------------------


class TestNotebookScoping:
    def _scoped_profiles(self) -> None:
        _set_profiles({
            "scoped": {
                "token_sha256": hash_token("tok-scoped"),
                "notebooks": {"allow": ["bridgeland-stability"]},
            }
        })

    def test_other_notebook_denied(self) -> None:
        self._scoped_profiles()
        mw = CapabilityMiddleware(app=None)
        inner, sent = asyncio.run(
            _drive(
                mw,
                _scope(token="tok-scoped"),
                _tools_call_body(
                    "search_papers",
                    arguments={"query": "q", "filters": {"notebook": "fourier-duality"}},
                ),
            )
        )
        assert not inner
        assert _denial_scope_of(sent) == "notebook_not_allowed"
        structured = _response_payload(sent)["result"]["structuredContent"]
        assert structured["notebook"] == "fourier-duality"

    def test_allowed_notebook_passes(self) -> None:
        self._scoped_profiles()
        mw = CapabilityMiddleware(app=None)
        inner, _ = asyncio.run(
            _drive(
                mw,
                _scope(token="tok-scoped"),
                _tools_call_body(
                    "search_papers",
                    arguments={
                        "query": "q",
                        "filters": {"notebook": "bridgeland-stability"},
                    },
                ),
            )
        )
        assert inner

    def test_unscoped_search_denied_for_scoped_profile(self) -> None:
        self._scoped_profiles()
        mw = CapabilityMiddleware(app=None)
        inner, sent = asyncio.run(
            _drive(mw, _scope(token="tok-scoped"), _tools_call_body("search_papers"))
        )
        assert not inner
        assert _denial_scope_of(sent) == "notebook_scope_required"

    def test_non_routed_tool_unaffected_by_scope(self) -> None:
        self._scoped_profiles()
        mw = CapabilityMiddleware(app=None)
        inner, _ = asyncio.run(
            _drive(mw, _scope(token="tok-scoped"), _tools_call_body("get_chunk"))
        )
        assert inner


# ---------------------------------------------------------------------------
# AC-A.9 (denied half) — audit row on denial
# ---------------------------------------------------------------------------


class TestDenialAuditRow:
    def test_denied_call_appends_exactly_one_audit_row(self, tmp_path: Path) -> None:
        from server.audit import (
            ToolCallAuditStore,
            get_audit_store,
            set_audit_store,
        )

        _set_profiles({
            "narrow": {
                "token_sha256": hash_token("tok-n"),
                "tools": {"allow": ["search_papers"]},
            }
        })

        async def _run() -> None:
            store = await ToolCallAuditStore.open(tmp_path / "audit.db")
            set_audit_store(store)
            try:
                mw = CapabilityMiddleware(app=None)
                inner, _sent = await _drive(
                    mw,
                    _scope(
                        token="tok-n",
                        session_id=_VALID_SESSION_ID,
                        role="tactician",
                    ),
                    _tools_call_body("get_chunk"),
                )
                assert not inner
                rows = await store.tail(limit=10)
                assert len(rows) == 1, "exactly one audit row per denied call"
                row = rows[0]
                assert row["tool"] == "get_chunk"
                assert row["outcome"] == "denied"
                assert row["profile"] == "narrow"
                assert row["role"] == "tactician"
                assert row["error_code"] == "CAPABILITY_DENIED"
                assert row["session_id"] == _VALID_SESSION_ID[:16]
            finally:
                assert get_audit_store() is store
                set_audit_store(None)
                await store.close()

        asyncio.run(_run())

    def test_denied_call_lands_in_request_event_ring(self) -> None:
        from server.observability.events import REQUEST_EVENTS

        _set_profiles({
            "narrow": {
                "token_sha256": hash_token("tok-n"),
                "tools": {"allow": []},
            }
        })
        mw = CapabilityMiddleware(app=None)
        asyncio.run(
            _drive(mw, _scope(token="tok-n"), _tools_call_body("search_papers"))
        )
        items, total, _ = REQUEST_EVENTS.snapshot(limit=10)
        assert total == 1
        assert items[0]["status"] == "denied"
        assert items[0]["tool"] == "search_papers"


# ---------------------------------------------------------------------------
# AC-A.10 — token hygiene
# ---------------------------------------------------------------------------


class TestTokenHygiene:
    _TOKEN = "super-secret-token-value-abc123"

    def test_token_value_never_in_logs_or_response(self, caplog) -> None:
        _set_profiles({"p": {"token_sha256": hash_token("other")}})
        mw = CapabilityMiddleware(app=None)
        with caplog.at_level(logging.DEBUG):
            _inner, sent = asyncio.run(
                _drive(mw, _scope(token=self._TOKEN), _tools_call_body("search_papers"))
            )
        joined_logs = "\n".join(r.getMessage() for r in caplog.records)
        assert self._TOKEN not in joined_logs, "token leaked into logs"
        body = b"".join(
            e.get("body", b"") for e in sent if e["type"] == "http.response.body"
        ).decode("utf-8")
        assert self._TOKEN not in body, "token leaked into the denial envelope"

    def test_token_value_never_in_audit_rows(self, tmp_path: Path) -> None:
        from server.audit import ToolCallAuditStore, set_audit_store

        _set_profiles({"p": {"token_sha256": hash_token("other")}})

        async def _run() -> None:
            store = await ToolCallAuditStore.open(tmp_path / "a.db")
            set_audit_store(store)
            try:
                mw = CapabilityMiddleware(app=None)
                await _drive(
                    mw, _scope(token=self._TOKEN), _tools_call_body("search_papers")
                )
                rows = await store.tail(limit=10)
                dumped = json.dumps(rows)
                assert self._TOKEN not in dumped
            finally:
                set_audit_store(None)
                await store.close()

        asyncio.run(_run())

    def test_bearer_extraction_ignores_other_schemes(self) -> None:
        from server.middleware import _extract_bearer_token

        assert _extract_bearer_token([(b"authorization", b"Basic dXNlcg==")]) is None
        assert _extract_bearer_token([(b"authorization", b"Bearer  tok ")]) == "tok"
        assert _extract_bearer_token([(b"authorization", b"Bearer")]) is None
        assert _extract_bearer_token([]) is None
