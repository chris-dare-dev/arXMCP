# E06_S02 Implementation Summary

**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 5 (3 new, 2 modified)
**Commit (planned):** see Phase 4 footer once committed.

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `shim/arxmcp_shim.py` | NEW | The 59-LOC stdio↔HTTP MCP proxy. Byte-pass-through body; header-only session-id capture/echo; one-shot retry on connection failure. Stdlib-only (`http.client`, `urllib.parse`, `argparse`, `sys`). |
| `docs/install.md` | NEW | Operator install runbook: `pipx install arxmcp`, `~/.claude.json` snippet (verbatim from design note), `make up`, end-to-end verify, troubleshooting table. |
| `tests/test_shim.py` | NEW | 10 integration tests across 6 classes. Mock `http.server` + subprocess shim; covers all 4 ACs plus byte-pass-through and per-process session-id invariants. |
| `pyproject.toml` | modified | Added `shim` to `[tool.setuptools] packages`; added `[project.scripts] arxmcp-shim = "shim.arxmcp_shim:main"` console-script entry point. |
| `server/main.py` | modified | One-line change: `FastMCP("arxmcp", json_response=True)` so responses are single-shot `application/json` (the shim does NOT parse SSE). |

## Decisions exercised from research-brief-1.md (single-mode synthesis)

| Decision | Where it landed |
|---|---|
| (a) Byte-pass-through body; header-only session-id | `_proxy()` reads stdin bytes, posts verbatim, captures `mcp-session-id` from `resp.getheader()`, echoes on next request. NEVER calls `json.loads`. |
| (b) `json_response=True` on FastMCP | `server/main.py:381` — `FastMCP("arxmcp", json_response=True)`. Shim sends `Accept: application/json` only. |
| (c) ≤60 LOC achievable with the synthesis approach | 59 effective LOC (excluding comments, blanks, docstrings; AST-verified). |
| (d) `http.client.HTTPConnection` (stdlib only) | `_connect()`. Persistent connection per shim process; one-shot reconnect on `OSError`/`HTTPException` for keep-alive timeouts. |
| (e) Add `shim` to packages + `[project.scripts]` | `pyproject.toml`: both lines added. `arxmcp-shim` resolves on `$PATH` after `pip install -e .`. |
| (f) Mock HTTP server in test (not real arxmcp-server) | `tests/test_shim.py::_MockHandler` (threaded `http.server`); subprocess-spawned shim; ~1s test runtime. |

## Test results

- **629 passed**, 3 skipped (pre-existing), ruff clean
- 10 new tests in `tests/test_shim.py`; sub-second runtime each

## Acceptance-criteria mapping

| AC | Status | Where verified |
|---|---|---|
| `arxmcp-shim --server http://...:7733` forwards `tools/list` end-to-end | **met** | `TestShimEndToEnd::test_tools_list_round_trip` (mock server returns canned `tools/list`; asserts byte-equality of request body and stdout response) |
| Shim exits 1 + stderr on `/readyz` failure | **met** | `TestProbeFailure` (2 tests: server unreachable, `/readyz` returns 503) |
| Shim binary ≤60 lines (excluding comments + blanks) | **met** | `TestShimLineCount::test_loc_under_60` — AST-based scan, 59 LOC measured |
| `docs/install.md` contains verbatim `~/.claude.json` snippet | **met** | `TestInstallDoc::test_claude_json_snippet_verbatim` — extracts the JSON content from the `\`\`\`json` block in `06-mcp-server-design.md`, asserts byte-for-byte presence in `docs/install.md` |

## Notable design choices for the critic

- **The `json_response=True` server change is load-bearing.** Without it, the server returns `text/event-stream` for tool-call responses; the shim is a pure single-frame proxy and cannot parse SSE. The design note (`06-mcp-server-design.md` line 46) explicitly says protocol-level streaming of tool results is out of scope, so this is the right default. It also tightens the `Accept` header negotiation: the server's `_validate_accept_header` requires only `application/json` when JSON-mode is enabled.

- **Byte-pass-through is the strongest BP1 guarantee.** The shim NEVER calls `json.loads` on the body. The mcp library's tool-schema-hash test (E06_S06) depends on byte-stable JSON; any re-serialization in the proxy path could re-order keys or change whitespace and break the hash. Locked by `TestBytePassThrough` (sends non-canonical JSON, asserts the mock server receives it byte-equal).

- **Per-process session-id is NOT "stateful" in the brief's sense.** The brief calls the shim "stateless" — meaning no auth, no disk, no shared state across processes. But the MCP spec REQUIRES the client to echo `Mcp-Session-Id` after the initialize handshake. We hold it in module-level memory for the duration of the shim's process lifetime (one process per Claude sub-agent). When the sub-agent exits, the shim exits, the session-id is gone. That's per-CONNECTION state, not persistent state. Locked by `TestSessionIdHandling` (asserts capture from response header AND echo on next request).

- **Stdlib-only.** No `httpx` (which would be transitively-OK via `mcp` deps, but the brief says "no dependencies beyond stdlib"). `http.client.HTTPConnection` gives raw byte access in/out and is the right primitive for byte-pass-through.

- **One-shot retry on connection failure.** Keep-alive timeouts on the server side (or a server restart) cause `http.client.RemoteDisconnected`. The shim catches `(OSError, HTTPException)`, reconnects once, and re-sends. A second failure propagates. This handles the most common transient mode without inviting infinite loops.

- **Two `# noqa: E701` markers** on `if X: continue` and `if X: Y` one-liners are the price of the 60-LOC cap. They're used sparingly (2 lines) and explicitly mark the convention.

- **`HEADERS` constant is at module level** rather than in-function. Saves 1 LOC + makes the per-request header dict construction obvious (`{**HEADERS, "Content-Length": ...}`).

- **No SSE parsing, no protocol-level streaming, no auth, no TLS.** All explicitly out-of-scope per the brief. The shim's surface is intentionally tiny.

- **The mock-server test fixture writes class-level state** (`_MockHandler.canned_response_body`, `record_requests`). That's the standard `http.server.BaseHTTPRequestHandler` pattern — the handler is instantiated per-request, so state must live elsewhere. Reset between tests via the `mock_server` fixture.

## Out-of-scope (deferred per brief)

- TLS (localhost only).
- Authentication.
- Stateful session logic across shim invocations.
- SSE streaming (we configure the server with `json_response=True`).

## External writes

**None at commit time.** All deliverables are local commits.
- The `pip install -e .` re-runs locally to register the
  `arxmcp-shim` entry point, but that's a developer-machine
  action, not a remote write.
- No git push, no PR, no infra mutation, no third-party API call.
