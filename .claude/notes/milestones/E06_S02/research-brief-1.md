# E06_S02 Research Brief — Stdio shim binary

## 1. In-codebase context

**The `~/.claude.json` snippet (load-bearing).** From `06-mcp-server-design.md:19-29`,
the EXACT 11-line block the shim docs MUST mirror is:

```json
{
  "mcpServers": {
    "arxmcp": {
      "command": "arxmcp-shim",
      "args": ["--server", "http://127.0.0.1:7733"]
    }
  }
}
```

That snippet is 11 lines counting both fence lines (the AC says "matching
.claude/notes/06-mcp-server-design.md lines 19–29"). Brief AC says "verbatim";
copy fence-to-fence into `docs/install.md`.

**`shim/` directory state.** Exists as `shim/__init__.py` (empty, 0 bytes) +
`shim/README.md` (514 bytes, just an explanatory stub pointing at note 02).
No code, no entry point, no setup config — net-new.

**`docs/` directory.** Two files (`chunker-fixtures.md`, `eval-curation.md`).
No `install.md` yet — net-new file.

**MCP server `/mcp` endpoint behavior (E06_S01).** From `server/_mcp_mount.py`:
mounted at `/mcp`; `FastMCP("arxmcp").streamable_http_app()` returns the
Starlette sub-app. The mount-routing yields `/mcp/` (trailing slash). From
`server/main.py:105`, `/mcp` is exempt from the body-size cap because
"Streamable HTTP carries SSE streams that defeat buffering."

**FastMCP's `json_response` toggle exists.** From
`mcp/server/fastmcp/server.py:106-107` and `:166-168`:
`json_response: bool = False, stateless_http: bool = False`. Setting
`json_response=True` makes the server return single-shot JSON instead of SSE.
From `mcp/server/streamable_http.py:427-443` the server DOES validate Accept
headers strictly — if `json_response=False` the client must send
`Accept: application/json, text/event-stream`. Currently the server in `server/main.py:381`
constructs `FastMCP("arxmcp")` with default kwargs — i.e. SSE mode.

**Session-id wire format.** `mcp/server/streamable_http.py:52-53`:
`MCP_SESSION_ID_HEADER = "mcp-session-id"`,
`MCP_PROTOCOL_VERSION_HEADER = "mcp-protocol-version"`. The server sets
`mcp-session-id` on the response to `initialize`; subsequent client requests
must echo it.

**`/readyz` contract.** `server/health.py:116-165`: returns 200 with
`{"status": "ready", ...}` once warm; 503 with `{"status": "not_ready", ...}`
otherwise. Plain HTTP GET, no auth, no headers required. Perfect for the
shim's startup probe.

**`pyproject.toml` packaging.** Lines 11-15: `[tool.setuptools] packages =
["server", "ingest", "tools"]`. No `[project.scripts]` section yet. The
package list explicitly excludes `shim/` even though the directory exists —
the comment at line 5 calls out flat-layout discovery as the reason.

**Existing tests.** No `tests/test_shim.py`. `tests/conftest.py` is small;
no shared HTTP-mock fixtures.

## 2. Prior decisions and lessons

**Recent commits are E06_S01-shaped.** `3dcc12c rect(server)` and
`ad8b956 feat(server)` landed the FastAPI skeleton with the Streamable HTTP
mount. The shim is the natural follow-on; nothing in the recent log
constrains shim design.

**Streamable HTTP transport — what the shim actually carries.** The CLIENT
(Claude Code) speaks line-delimited JSON-RPC over the shim's stdin/stdout —
exact protocol the `mcp` lib's own `stdio_client` implements at
`mcp/client/stdio/__init__.py:139-180`: `stdout_reader` splits by `\n` and
parses each line as a JSONRPC frame; `stdin_writer` writes
`json + "\n"` per outgoing frame. **One JSON-RPC message per line, terminated
by `\n`.** No length prefix, no SSE framing on the stdio side.

The SERVER speaks Streamable HTTP. With `json_response=False` (current
default), the server's POST response is `text/event-stream` with each
JSON-RPC reply wrapped in an SSE `data:` frame. With `json_response=True`,
the response is single-shot `Content-Type: application/json` carrying one
JSON-RPC frame in the body. **The brief's risk note ("forward verbatim; any
re-serialization risks breaking byte-stability of tool schemas") is the
deciding constraint.**

**Session-id management.** The MCP spec says session-id is per-connection and
the client must echo `Mcp-Session-Id` on every subsequent request after
initialize. The brief calls the shim "stateless" but the spec demands the
client (= shim, from the server's perspective) hold the session-id for the
duration of the connection. The reconciliation: each Claude sub-agent spawns
its OWN shim process; that process lives only as long as the sub-agent. The
shim holding the session-id IN MEMORY for its process lifetime is not
"persistent state" — it is per-connection state that the Streamable HTTP spec
requires the client to track. "Stateless" in the brief means "no auth, no
disk, no shared state across processes."

**Byte-stability rule from `07-multi-agent-caching.md`.** Property 1: tool
definitions must be byte-stable. Property 2: tool result payloads
canonicalized. The shim is downstream of both — the server emits canonical
bytes; the shim's job is to NOT corrupt them. Byte-pass-through is the
strongest guarantee: never deserialize, never re-encode, never re-sort keys.

**The 60-LOC cap is achievable** if (a) we configure the server with
`json_response=True` so the shim never sees SSE, and (b) we extract
`mcp-session-id` from response HEADERS (cheap regex / `http.client` header
access, no body parse) and inject it into subsequent request headers. Body
stays untouched bytes.

## 3. External sources

**MCP 2025-06-18 Streamable HTTP spec.** Single endpoint, supports POST + GET.
POST request body is one JSON-RPC message; response is either
`application/json` (single frame) or `text/event-stream` (one or more SSE
events, each `data:` line a JSON-RPC frame). `Mcp-Session-Id` returned on
initialize response, echoed thereafter. `Mcp-Protocol-Version` header echoed
after the initialize handshake.

**JSON-RPC over stdio framing.** The mcp lib's reference client
(`mcp/client/stdio/__init__.py:144-178`) uses line-delimited UTF-8: split on
`\n`, parse each line as one JSON object. NO `Content-Length` prefix. This
contradicts the older LSP-style framing — the MCP stdio transport is
line-delimited only.

**`http.client` vs `urllib.request` vs `httpx`.** `http.client.HTTPConnection`
gives full header control + per-request connection reuse + raw byte access to
both request and response bodies. `urllib.request` adds an opener layer that
fights us on header injection and on getting raw bytes back. `httpx` is in
deps (transitively via `mcp`?  no — direct check shows it isn't in
`pyproject.toml` `dependencies`) but the brief says "no dependencies beyond
stdlib." `http.client` it is.

**stdio buffering.** `sys.stdin.buffer.readline()` + `sys.stdout.buffer.write()
+ flush()` is the safe pattern. Text-mode I/O in Python on Windows mangles
`\n` → `\r\n` and corrupts the JSON-RPC frame. **Use binary mode and write a
literal `\n` after each frame.**

## Open questions (with recommendations)

**(a) Byte-pass-through vs JSON-parse for session-id.** Recommend:
**byte-pass-through for the BODY; minimal HEADER inspection for session-id.**
The shim never calls `json.loads`. It reads one stdin line, POSTs the bytes
verbatim as the request body, reads the response, extracts
`mcp-session-id` from response headers via `http.client.HTTPResponse.getheader(
"mcp-session-id")` (no body parse), caches it in a module-level variable,
and writes the response body bytes + `\n` to stdout. This satisfies the
byte-stability risk note absolutely and keeps the shim under the LOC cap.

**(b) SSE handling.** Recommend: **set `json_response=True` on the server's
FastMCP** so the shim never sees SSE. One-line change in `server/main.py:381`
(`FastMCP("arxmcp", json_response=True)`). The shim is then a pure
single-frame request/response proxy. Trade-off: we lose server→client
unsolicited notifications (the streaming-progress channel) — but the design
doc at `06-mcp-server-design.md:46-47` already says "No protocol-level
streaming of tool results. notifications/progress is a heartbeat, not a
partial-result channel." We don't need the SSE pipe. Also flip the body-size
cap exemption logic — with `json_response=True`, MCP responses are single-shot
JSON and the cap could apply (but keep the exemption; tool-internal pagination
already enforces the cap). Update Accept header in shim to
`application/json` only.

**(c) 60-LOC cap.** With (a) + (b), the shim is ~35-45 LOC: a `while True`
loop with `readline()` → `HTTPConnection.request("POST", "/mcp/", body,
headers)` → `getheader("mcp-session-id")` capture → `read()` body →
`stdout.buffer.write(body + b"\n")` + `flush()`. Plus argparse for `--server`
and a 5-second `/readyz` probe at startup. Comfortably under 60.

**(d) HTTP client.** Recommend: **`http.client.HTTPConnection`**. Stdlib,
zero deps, raw bytes in/out, header passthrough trivial, persistent connection
cheap (one `HTTPConnection` for the shim's lifetime). Auto-reconnect on
`ConnectionError` with one retry to handle keep-alive timeout.

**(e) Entry point packaging.** Recommend: **add `[project.scripts]` to
`pyproject.toml` AND add `"shim"` to `packages`.** Concretely:

```toml
[tool.setuptools]
packages = ["server", "ingest", "tools", "shim"]

[project.scripts]
arxmcp-shim = "shim.arxmcp_shim:main"
```

Setuptools needs `shim` in `packages` because the entry point references
`shim.arxmcp_shim`. The brief mentions `shim/setup.cfg` as an alternative —
do NOT introduce that; it splits config across two files. Pure
`pyproject.toml`.

**(f) Test strategy.** Recommend: **use `http.server.HTTPServer` in a thread
to mock the arxmcp server.** Spawning the real `arxmcp-server` requires
loading BGE-M3 (~2GB, ~10s warm time) — unacceptable for a unit test. The
mock server (~30 lines) handles `GET /readyz` → 200 and `POST /mcp/` →
returns a canned `tools/list` response with a `mcp-session-id` header. The
test spawns the shim as a subprocess via `subprocess.Popen`, writes a
`tools/list` JSON-RPC frame to stdin, reads the reply from stdout, asserts
byte-equality with the canned response. Second test case: kill the mock
server, spawn shim, assert exit code 1 and stderr contains a probe-failure
message. Total: ~80 LOC of test code; runs in <1s.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| (none) | (none) | All deliverables are local-repo file writes. No PR, no tag, no infra mutation, no third-party API call. The implementer commits on the milestone branch; PR creation is downstream of the milestone-pipeline external-write gate, not part of this milestone's scope. |
