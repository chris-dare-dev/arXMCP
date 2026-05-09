#!/usr/bin/env python3
"""arxmcp-shim: stdio<->HTTP MCP proxy (E06_S02).

Stateless one-process-per-sub-agent bridge. Claude Code spawns this
binary as a stdio MCP server (per ``~/.claude.json``); we forward
JSON-RPC frames over Streamable HTTP to ``--server`` (default
``http://127.0.0.1:7733``).

**Loopback-only** (Threat 4 egress side, closes F1 from the
E06_S02 critique). The ``--server`` URL host MUST be one of
``127.0.0.1``, ``::1``, or ``localhost``. The server-side
:class:`server.config.Config` enforces the symmetric LISTEN-side
guard; the shim closes the EGRESS-side gap. A misconfigured or
malicious ``~/.claude.json`` pointing at a remote host is rejected
at startup with a clear FATAL message rather than silently
exfiltrating every prompt body.

**Byte-pass-through body** (load-bearing, closes the brief's
risk note "any re-serialization risks breaking byte-stability").
We never call ``json.loads`` on the request or response body. One
stdin line in -> POST bytes verbatim -> response body bytes + LF
to stdout. Tool schemas and result payloads transit untouched.

**Non-200 HTTP responses get a JSON-RPC error envelope** (F3
fix). Without this, server-emitted 503 / 413 / 400 bodies would
be written to stdout as if they were JSON-RPC responses; Claude
Code's stdio client would fail to parse them as ``result`` frames
and surface a confusing client-side error. Instead we synthesize
``{"jsonrpc":"2.0","id":null,"error":{"code":-32603,...}}\\n`` so
the client sees a well-formed JSON-RPC error.

**Per-process session-id** (header-only). The MCP 2025-06-18 spec
requires the client echo ``Mcp-Session-Id`` after ``initialize``.
We capture it from response headers, inject into subsequent
requests. Each Claude sub-agent's shim process holds its own
session-id in module-level memory -- spec-mandated CONNECTION
state, not persistent state.

**Mcp-Protocol-Version** is pinned at ``2025-06-18`` on every
request (F8 fix). Without an explicit pin the mcp library's
server defaults to ``2025-03-26`` which would silently downgrade
the negotiated protocol.

**JSON response mode required**. The server MUST be configured
with ``FastMCP("arxmcp", json_response=True)`` so responses are
single-shot ``application/json`` rather than ``text/event-stream``.
We do NOT parse SSE.

**Stdio framing**: line-delimited UTF-8, one JSON-RPC message per
line, terminated by LF. Binary I/O so Windows newline translation
cannot corrupt the frame. The MCP stdio spec REQUIRES every frame
end with LF; ``readline()`` blocks if a frame arrives without one
(documented limitation, not a bug).
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import urllib.parse

DEFAULT_SERVER = "http://127.0.0.1:7733"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Mcp-Protocol-Version": "2025-06-18",
}
JSONRPC_INTERNAL_ERROR = -32603


def _connect(url: str, timeout: float) -> http.client.HTTPConnection:
    p = urllib.parse.urlparse(url)
    if p.scheme != "http":
        raise SystemExit(f"FATAL: --server must be http:// (got {p.scheme!r})")
    host = (p.hostname or "").lower()
    if not host:
        raise SystemExit(f"FATAL: --server URL has no hostname: {url!r}")
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"FATAL: --server host must be loopback ({sorted(LOOPBACK_HOSTS)}); "
            f"got {host!r}. The shim refuses to proxy to non-loopback "
            f"addresses (Threat 4)."
        )
    return http.client.HTTPConnection(host, p.port or 80, timeout=timeout)


def _probe(url: str) -> None:
    conn = _connect(url, 5.0)
    try:
        conn.request("GET", "/readyz")
        r = conn.getresponse()
        if r.status != 200:
            raise SystemExit(f"FATAL: {url} /readyz returned {r.status}; not ready")
        r.read()
    except (OSError, http.client.HTTPException) as exc:
        raise SystemExit(f"FATAL: cannot reach arxmcp-server at {url}: {exc}") from exc
    finally:
        conn.close()


def _error_frame(status: int, body: bytes) -> bytes:
    """Build a JSON-RPC error frame for a non-200 HTTP response.

    Closes F3: without this, the server's error body would be
    written to stdout as if it were a JSON-RPC ``result`` frame
    and confuse Claude Code's stdio client. The synthesized frame
    has ``id=null`` because the shim does not parse the request
    body to extract the JSON-RPC id (would violate byte-pass-through).
    """
    payload = {
        "jsonrpc": "2.0",
        "id": None,
        "error": {
            "code": JSONRPC_INTERNAL_ERROR,
            "message": f"arxmcp-server returned HTTP {status}",
            "data": {"http_status": status, "body": body.decode("utf-8", "replace")},
        },
    }
    return json.dumps(payload).encode("utf-8") + b"\n"


def _proxy(url: str) -> None:
    sid: str | None = None
    conn = _connect(url, 60.0)
    try:
        while line := sys.stdin.buffer.readline():
            body = line.rstrip(b"\n")
            if not body:
                continue
            h = {**HEADERS, "Content-Length": str(len(body))}
            if sid is not None:
                h["mcp-session-id"] = sid
            # F5 fix: include resp.read() in the retry block — a
            # mid-response connection drop is the second-most-common
            # transient after keep-alive timeouts.
            for attempt in (0, 1):
                try:
                    conn.request("POST", "/mcp/", body=body, headers=h)
                    resp = conn.getresponse()
                    response_body = resp.read()
                    break
                except (OSError, http.client.HTTPException):
                    if attempt:
                        raise
                    conn.close()
                    conn = _connect(url, 60.0)
            sid = resp.getheader("mcp-session-id") or sid
            # F3 fix: synthesize a JSON-RPC error envelope on non-200.
            if resp.status != 200:
                out = _error_frame(resp.status, response_body)
            else:
                out = response_body + b"\n"
            sys.stdout.buffer.write(out)
            sys.stdout.buffer.flush()
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arxmcp-shim")
    p.add_argument("--server", default=DEFAULT_SERVER)
    args = p.parse_args(argv)
    _probe(args.server)
    _proxy(args.server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
