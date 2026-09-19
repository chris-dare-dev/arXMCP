"""Live-server ``lean_verify`` smoke test (Stage-2 slice arx-d1 / WS-D D-1).

Drives ONE mathlib-importing snippet through the ``lean_verify`` MCP
tool against a RUNNING arxmcp-server over the real Streamable-HTTP
wire — the acceptance-criteria harness note ("``lean_verify``
exercised over MCP against the live server") as a repeatable dev
script rather than a one-off curl transcript.

Protocol notes are lifted from ``shim/arxmcp_shim.py`` (the wire
contract of record): JSON-RPC over ``POST /mcp/``, single-shot
``application/json`` responses (the server runs
``FastMCP(json_response=True)``), ``Mcp-Session-Id`` captured from the
``initialize`` response headers and echoed on every subsequent
request, ``Mcp-Protocol-Version`` pinned at ``2025-06-18``.

Loopback-only egress, mirroring the shim's Threat-4 guard: this script
refuses to talk to a non-loopback host.

Usage (server already running with the Lean lane enabled — see
``docs/install.md`` § "enable lean_verify"):

    uv run python -m tools.lean_verify_smoke
    uv run python -m tools.lean_verify_smoke --server http://127.0.0.1:7743 \
        --import Mathlib.Algebra.Group.Defs \
        --snippet "theorem smoke (G : Type) [Group G] (a : G) : 1 * a = a := one_mul a"

Exit codes: 0 = round-trip verified (``status == "ok"`` and
``compilation_success is True`` and ``lean_status == "available"``);
1 = tool reachable but the snippet did not verify (the full envelope
is printed either way); 2 = transport/protocol failure.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import urllib.parse
from typing import Any

DEFAULT_SERVER = "http://127.0.0.1:7733"
DEFAULT_SNIPPET = (
    "theorem arx_d1_live_smoke (G : Type) [Group G] (a : G) : "
    "1 * a = a := one_mul a"
)
DEFAULT_IMPORT = "Mathlib.Algebra.Group.Defs"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Mcp-Protocol-Version": "2025-06-18",
}


class SmokeTransportError(RuntimeError):
    """Transport/protocol failure (exit 2) — distinct from a snippet
    that reached the REPL and failed to verify (exit 1)."""


def _connect(url: str, timeout: float) -> http.client.HTTPConnection:
    p = urllib.parse.urlparse(url)
    if p.scheme != "http":
        raise SmokeTransportError(f"--server must be http:// (got {p.scheme!r})")
    host = (p.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise SmokeTransportError(
            f"--server host must be loopback ({sorted(LOOPBACK_HOSTS)}); "
            f"got {host!r} (Threat 4 — same refusal as the shim)"
        )
    return http.client.HTTPConnection(host, p.port or 80, timeout=timeout)


def _post(
    conn: http.client.HTTPConnection,
    payload: dict[str, Any],
    session_id: str | None,
) -> tuple[int, bytes, str | None]:
    body = json.dumps(payload).encode("utf-8")
    headers = {**HEADERS, "Content-Length": str(len(body))}
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    conn.request("POST", "/mcp/", body=body, headers=headers)
    resp = conn.getresponse()
    resp_body = resp.read()
    return resp.status, resp_body, resp.getheader("mcp-session-id") or session_id


def _rpc(
    conn: http.client.HTTPConnection,
    payload: dict[str, Any],
    session_id: str | None,
    *,
    expect_body: bool = True,
) -> tuple[dict[str, Any] | None, str | None]:
    status, body, session_id = _post(conn, payload, session_id)
    if status not in (200, 202):
        raise SmokeTransportError(
            f"{payload.get('method')}: HTTP {status}: "
            f"{body.decode('utf-8', 'replace')[:500]}"
        )
    if not expect_body or not body:
        return None, session_id
    try:
        frame = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SmokeTransportError(
            f"{payload.get('method')}: non-JSON response body: {body[:200]!r}"
        ) from exc
    if isinstance(frame, dict) and frame.get("error"):
        raise SmokeTransportError(
            f"{payload.get('method')}: JSON-RPC error: {frame['error']}"
        )
    return frame, session_id


def _extract_envelope(frame: dict[str, Any]) -> dict[str, Any]:
    """Pull the lean_verify result envelope out of a tools/call frame.

    Prefers ``structuredContent`` (present when the tool declares an
    output schema); falls back to parsing ``content[0].text`` as JSON.
    """
    result = frame.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in result.get("content") or []:
        if item.get("type") == "text":
            try:
                parsed = json.loads(item["text"])
            except (json.JSONDecodeError, KeyError):
                continue
            if isinstance(parsed, dict):
                return parsed
    raise SmokeTransportError(
        f"tools/call: no parsable envelope in result: {json.dumps(result)[:500]}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lean-verify-smoke")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument(
        "--import",
        dest="imports",
        action="append",
        metavar="MODULE",
        help=f"context import (repeatable; default: {DEFAULT_IMPORT})",
    )
    parser.add_argument("--snippet", default=DEFAULT_SNIPPET)
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="HTTP timeout in seconds (must exceed the server's 30 s "
        "per-query Lean timeout; default 90)",
    )
    args = parser.parse_args(argv)
    imports = args.imports or [DEFAULT_IMPORT]

    try:
        conn = _connect(args.server, args.timeout)
    except SmokeTransportError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    session_id: str | None = None
    try:
        frame, session_id = _rpc(
            conn,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "lean-verify-smoke",
                        "version": "0.1.0",
                    },
                },
            },
            session_id,
        )
        server_info = (frame or {}).get("result", {}).get("serverInfo", {})
        _, session_id = _rpc(
            conn,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id,
            expect_body=False,
        )
        frame, session_id = _rpc(
            conn,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "lean_verify",
                    "arguments": {
                        "snippet": args.snippet,
                        "imports": imports,
                    },
                },
            },
            session_id,
        )
        envelope = _extract_envelope(frame or {})
    except SmokeTransportError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2
    except (OSError, http.client.HTTPException) as exc:
        print(f"FATAL: cannot reach arxmcp-server at {args.server}: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    print(f"server: {server_info.get('name')} {server_info.get('version')}")
    print(f"imports: {imports}")
    print(f"snippet: {args.snippet}")
    print(json.dumps(envelope, indent=2, ensure_ascii=False, sort_keys=True))
    verified = (
        envelope.get("status") == "ok"
        and envelope.get("compilation_success") is True
        and envelope.get("lean_status") == "available"
    )
    print(f"ROUND-TRIP: {'VERIFIED' if verified else 'NOT VERIFIED'}")
    return 0 if verified else 1


if __name__ == "__main__":
    sys.exit(main())
