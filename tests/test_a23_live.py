"""Live-server integration tests for the stage2/arx-a23 surfaces.

Opt-in (spawns a real ``python -m server.main`` subprocess in bootstrap
mode and talks to it over loopback HTTP)::

    ARXMCP_RUN_LIVE_SERVER_TESTS=1 pytest tests/test_a23_live.py

The "against a running server instance" evidence pass for WS-A A2/A3:
real uvicorn, real middleware stack (Capability → SessionCap in the
production mount order), real lifespan (operator_settings + audit
store + event tier bound), real HTTP, real SSE. Harness mirrors
``tests/test_api_v1_live.py`` (isolated data tree, non-default port,
file-backed server log).
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ARXMCP_RUN_LIVE_SERVER_TESTS") != "1",
    reason=(
        "live-server integration is opt-in: set "
        "ARXMCP_RUN_LIVE_SERVER_TESTS=1 (spawns a real server "
        "subprocess in bootstrap mode)"
    ),
)

_PORT = 7801  # distinct from the a1 live suite (7799) + dev 7733
_BASE = f"http://127.0.0.1:{_PORT}"
_REPO_ROOT = Path(__file__).resolve().parents[1]

_TOKEN = "live-a23-capability-token"
_TOKEN_SHA = hashlib.sha256(_TOKEN.encode()).hexdigest()


def _http(
    method: str, path: str, body: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, dict | bytes, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            status = resp.status
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        resp_headers = {k.lower(): v for k, v in e.headers.items()}
    try:
        return status, json.loads(raw), resp_headers
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, raw, resp_headers


def _mcp_headers(token: str | None, sid: str | None = None) -> dict:
    headers = {
        "Accept": "application/json",
        "Mcp-Protocol-Version": "2025-06-18",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if sid is not None:
        headers["mcp-session-id"] = sid
    return headers


def _mcp_initialize(token: str | None = None) -> str:
    """Real MCP handshake: initialize → capture the server-issued
    ``Mcp-Session-Id`` header → notifications/initialized. The shim's
    exact flow (fresh session per query — the website pattern)."""
    status, body, resp_headers = _http(
        "POST", "/mcp/",
        body={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "a23-live", "version": "0"},
            },
        },
        headers=_mcp_headers(token),
    )
    assert status == 200, body
    sid = resp_headers.get("mcp-session-id")
    assert sid, "server must issue a session id on initialize"
    _http(
        "POST", "/mcp/",
        body={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=_mcp_headers(token, sid),
    )
    return sid


def _mcp_tools_call(
    tool: str, arguments: dict, *, token: str | None = None,
) -> dict:
    """One tools/call on a FRESH session (initialize handshake each
    time — matches the pipeline's fresh-session-per-query reality)."""
    sid = _mcp_initialize(token)
    status, body, _ = _http(
        "POST", "/mcp/",
        body={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
        headers=_mcp_headers(token, sid),
    )
    assert status == 200, body
    return body if isinstance(body, dict) else json.loads(body)


def _mcp_initialize_with_role(role: str) -> str:
    """initialize + notifications/initialized carrying Arxmcp-Agent-Role.

    The stage3/cross-r1 regression needs the role present at INITIALIZE
    (when the session task's context is captured) so a stale read would
    freeze to it."""
    status, _, resp_headers = _http(
        "POST", "/mcp/",
        body={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "a23-live-role", "version": "0"},
            },
        },
        headers={**_mcp_headers(None), "Arxmcp-Agent-Role": role},
    )
    assert status == 200
    sid = resp_headers.get("mcp-session-id")
    assert sid, "server must issue a session id on initialize"
    _http(
        "POST", "/mcp/",
        body={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={**_mcp_headers(None, sid), "Arxmcp-Agent-Role": role},
    )
    return sid


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("live-a23")
    env = dict(os.environ)
    env.pop("ARXMCP_RUN_LIVE_SERVER_TESTS", None)
    env.update({
        "ARXMCP_BOOTSTRAP_MODE": "1",
        "ARXMCP_BIND_PORT": str(_PORT),
        "ARXMCP_DATA_DIR": str(tmp / "arxmcp"),
        "ARXMCP_NOTEBOOKS_DB_PATH": str(tmp / "arxmcp" / "cache" / "notebooks.db"),
        "ARXMCP_AUDIT_DB_PATH": str(tmp / "arxmcp" / "cache" / "tool_calls.db"),
        "ARXMCP_CAPABILITY_CACHE_TTL_S": "0",
    })
    log_path = tmp / "server.log"
    log_file = log_path.open("wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.main"],
        cwd=str(_REPO_ROOT), env=env,
        stdout=log_file, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                out = log_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(
                    f"server exited early (rc={proc.returncode}):\n{out[-4000:]}"
                )
            try:
                status, _, _ = _http("GET", "/healthz")
                if status == 200:
                    break
            except OSError as exc:  # noqa: PERF203 — startup poll
                last_err = exc
            time.sleep(0.5)
        else:
            raise RuntimeError(f"server never became healthy: {last_err}")
        yield
    finally:
        proc.kill()
        proc.wait(timeout=15)
        log_file.close()


class TestLiveCapabilityLayer:
    def test_profile_crud_and_call_time_denial(self, live_server) -> None:
        # Upsert a restricted profile over the live CRUD surface.
        status, body, _ = _http(
            "PUT", "/api/v1/capabilities/profiles/live-narrow",
            body={
                "token_sha256": _TOKEN_SHA,
                "tools": ["search_papers"],
            },
        )
        assert status == 200, body

        # Allowed tool under the token: passes the capability gate
        # (bootstrap mode answers with the no_notebook_selected stub —
        # which PROVES the call reached the wrapped handler).
        rpc = _mcp_tools_call("search_papers", {"query": "q"}, token=_TOKEN)
        structured = rpc["result"]["structuredContent"]
        assert structured.get("error_code") == "no_notebook_selected"

        # Denied tool: the structured CAPABILITY_DENIED envelope, not
        # a transport error (AC-A.6 live).
        rpc = _mcp_tools_call("get_chunk", {"chunk_id": "x"}, token=_TOKEN)
        structured = rpc["result"]["structuredContent"]
        assert rpc["result"]["isError"] is True
        assert structured["error_code"] == "CAPABILITY_DENIED"
        assert structured["denial_scope"] == "tool_not_allowed"
        assert structured["profile"] == "live-narrow"

        # Unknown token fails closed.
        rpc = _mcp_tools_call("search_papers", {"query": "q"}, token="wrong")
        assert rpc["result"]["structuredContent"]["denial_scope"] == "token_unknown"

        # No token → default profile → gate passes (AC-A.5 live).
        rpc = _mcp_tools_call("search_papers", {"query": "q"})
        assert (
            rpc["result"]["structuredContent"].get("error_code")
            == "no_notebook_selected"
        )

    def test_denials_land_in_audit_and_request_ring(self, live_server) -> None:
        status, body, _ = _http("GET", "/api/v1/tool-calls?limit=50")
        assert status == 200
        outcomes = {(r["tool"], r["outcome"]) for r in body["items"]}
        assert ("get_chunk", "denied") in outcomes
        assert ("search_papers", "ok") in outcomes

        status, body, _ = _http("GET", "/api/v1/requests?limit=50")
        assert status == 200
        statuses = {(e["tool"], e["status"]) for e in body["items"]}
        assert ("get_chunk", "denied") in statuses
        assert ("search_papers", "ok") in statuses


class TestLiveObservabilitySurfaces:
    def test_sessions_snapshot_live(self, live_server) -> None:
        status, body, _ = _http("GET", "/api/v1/sessions")
        assert status == 200
        assert body["format_version"] == 1

    def test_logs_tail_live_and_redacted(self, live_server) -> None:
        status, body, _ = _http("GET", "/api/v1/logs/tail?limit=200")
        assert status == 200
        # The live process has logged since startup; no record may
        # carry a redactable field at INFO+ (AC-A.12 live).
        for record in body["items"]:
            assert "query" not in record or record.get("level") == "DEBUG"

    def test_sse_stream_serves_frames(self, live_server) -> None:
        """Open the multiplexed stream, trigger a request event via a
        real tool call, and read frames off the socket (raw HTTP —
        urllib buffers streams unhelpfully)."""
        conn = socket.create_connection(("127.0.0.1", _PORT), timeout=10)
        try:
            conn.sendall(
                b"GET /api/v1/events/stream?topics=requests,logs HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nAccept: text/event-stream\r\n\r\n"
            )
            time.sleep(0.3)
            _mcp_tools_call("search_papers", {"query": "sse probe"})
            deadline = time.monotonic() + 10
            buf = b""
            while time.monotonic() < deadline:
                buf += conn.recv(65536)
                if b"event: ready" in buf and b"event: requests" in buf:
                    break
            assert b"text/event-stream" in buf
            assert b"event: ready" in buf, buf[:500]
            assert b"event: requests" in buf, (
                "the live tool call should surface on the stream"
            )
        finally:
            conn.close()

    def test_capability_denial_metric_exported(self, live_server) -> None:
        status, raw, _ = _http("GET", "/metrics")
        assert status == 200
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        assert "arxmcp_capability_denials_total" in text


class TestLiveRequestEventIdentity:
    """stage3/cross-r1 regression for
    ``request-events-lose-session-id-and-pin-role-at-initialize``.

    The MCP Streamable-HTTP session manager runs every ``tools/call`` on
    a long-lived per-session task whose ``contextvars.Context`` was
    captured at ``initialize`` — before the ``Mcp-Session-Id`` header
    exists and with the initialize-time ``Arxmcp-Agent-Role`` frozen in.
    The observability wrapper used to read
    ``current_session_id`` / ``current_agent_role`` from those frozen
    ContextVars, so EVERY request-ring event carried ``session_id=null``
    and the role pinned to the initialize value — while the session-cap
    roster (which reads headers directly per request) was correct. Two
    surfaces disagreed on the SAME call: the Requests SESSION column was
    always "—", and the Connections roster ``requests`` cross-link
    (``/app/requests?session=<prefix>``) dead-ended on an empty state
    with no session facet chip.

    Only a live server reproduces it — the ContextVar freeze is a
    property of the real session-task execution model, invisible to
    TestClient/direct-handler unit tests. This test would FAIL before
    the ``resolve_request_identity`` fix (row role='tactician',
    session_id=None)."""

    def test_request_event_uses_per_call_session_and_role(
        self, live_server,
    ) -> None:
        # initialize with 'tactician' (captured into the session task's
        # context); tools/call on the SAME session with 'fixer'.
        sid = _mcp_initialize_with_role("tactician")
        status, body, _ = _http(
            "POST", "/mcp/",
            body={
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "name": "search_papers",
                    "arguments": {"query": "cross-r1 identity probe"},
                },
            },
            headers={**_mcp_headers(None, sid), "Arxmcp-Agent-Role": "fixer"},
        )
        assert status == 200, body

        status, rbody, _ = _http("GET", "/api/v1/requests?limit=50")
        assert status == 200
        rows = [e for e in rbody["items"] if e["tool"] == "search_papers"]
        assert rows, "the tool call must surface in the request ring"
        newest = rows[0]

        # The event must carry the tools/call role + the minted session
        # id prefix — NOT the initialize-time 'tactician' and NOT null.
        assert newest["role"] == "fixer", (
            f"request event role pinned to the initialize-time value: "
            f"got {newest['role']!r}, expected 'fixer' (the per-call "
            f"Arxmcp-Agent-Role) — the ContextVar freeze regressed"
        )
        assert newest["session_id"] is not None, (
            "request event session_id is null — the SPA Requests SESSION "
            "column would render '—' and the Connections roster cross-link "
            "would dead-end with no session facet chip"
        )
        assert sid.startswith(newest["session_id"]), (
            f"request event session_id {newest['session_id']!r} is not a "
            f"prefix of the minted session id {sid!r}"
        )

        # Cross-surface agreement: the same call's session appears in the
        # roster keyed by the SAME 16-char prefix the ring stamped.
        status, sbody, _ = _http("GET", "/api/v1/sessions")
        assert status == 200
        roster_prefixes = {
            s.get("session_id_prefix") for s in sbody.get("items", [])
        }
        assert newest["session_id"] in roster_prefixes, (
            "the request-ring session_id prefix must match a session in "
            "the roster — the ring and roster must agree on the same call"
        )
