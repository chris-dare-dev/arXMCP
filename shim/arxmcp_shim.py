#!/usr/bin/env python3
"""arxmcp-shim: stdio↔HTTP MCP proxy (E06_S02).

Stateless one-process-per-sub-agent bridge. Claude Code spawns this
binary as a stdio MCP server (per ``~/.claude.json``); we forward
JSON-RPC frames over Streamable HTTP to ``--server`` (default
``http://127.0.0.1:7733``).

**Byte-pass-through body** (load-bearing — closes the brief's
risk note "any re-serialization risks breaking byte-stability").
We never call ``json.loads`` on the request or response body. One
stdin line in → POST bytes verbatim → response body bytes + ``\\n``
to stdout. Tool schemas and result payloads transit untouched.

**Per-process session-id** (header-only). The MCP 2025-06-18 spec
requires the client echo ``Mcp-Session-Id`` after ``initialize``.
We capture it from response headers, inject into subsequent
requests. Each Claude sub-agent's shim process holds its own
session-id in module-level memory — that's the spec-mandated
CONNECTION state, not persistent state.

**JSON response mode required**. The server MUST be configured
with ``FastMCP("arxmcp", json_response=True)`` so responses are
single-shot ``application/json`` rather than ``text/event-stream``.
We do NOT parse SSE.

**Stdio framing**: line-delimited UTF-8, one JSON-RPC message per
line, terminated by ``\\n``. Binary I/O so Windows newline
translation cannot corrupt the frame.
"""

from __future__ import annotations

import argparse
import http.client
import sys
import urllib.parse

DEFAULT_SERVER = "http://127.0.0.1:7733"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


def _connect(url: str, timeout: float) -> http.client.HTTPConnection:
    p = urllib.parse.urlparse(url)
    if p.scheme != "http":
        raise SystemExit(f"FATAL: --server must be http:// (got {p.scheme!r})")
    return http.client.HTTPConnection(
        p.hostname or "127.0.0.1", p.port or 80, timeout=timeout
    )


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


def _proxy(url: str) -> None:
    sid: str | None = None
    conn = _connect(url, 60.0)
    try:
        while line := sys.stdin.buffer.readline():
            body = line.rstrip(b"\n")
            if not body: continue  # noqa: E701
            h = {**HEADERS, "Content-Length": str(len(body))}
            if sid is not None: h["mcp-session-id"] = sid  # noqa: E701
            for attempt in (0, 1):
                try:
                    conn.request("POST", "/mcp/", body=body, headers=h)
                    resp = conn.getresponse()
                    break
                except (OSError, http.client.HTTPException):
                    if attempt:
                        raise
                    conn.close()
                    conn = _connect(url, 60.0)
            sid = resp.getheader("mcp-session-id") or sid
            sys.stdout.buffer.write(resp.read() + b"\n")
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
