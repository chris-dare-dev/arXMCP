# E08_S04 Research Brief 2 — Tool-use ID canonicalization + hard retrieval caps

## 1. In-codebase context

### Applicable design notes

**`07-multi-agent-caching.md` lines 87–117** (verbatim):

> ## The cache-killer the strawman missed: tool-use IDs
>
> Anthropic's API assigns server-side `id` fields to `tool_use` and `tool_result`
> content blocks (e.g. `toulu_01Abc...`). These IDs are **non-deterministic across
> calls**. As soon as one tool call happens in agent A and a different one happens
> in agent B, the prefix between them diverges and downstream cache reuse dies.
>
> **Mitigation:** the orchestrator (the layer that composes sub-agent prompts) must
> **normalize tool-use/tool-result IDs to deterministic values** before composing
> the next agent turn. Strategy:
>
> ```python
> def canonicalize_turn(messages):
>     counter = 0
>     id_map = {}
>     for msg in messages:
>         for block in msg.get("content", []):
>             if block.get("type") in ("tool_use", "tool_result"):
>                 old_id = block.get("id") or block.get("tool_use_id")
>                 if old_id not in id_map:
>                     id_map[old_id] = f"toolu_{counter:08d}"
>                     counter += 1
>                 if "id" in block:
>                     block["id"] = id_map[old_id]
>                 if "tool_use_id" in block:
>                     block["tool_use_id"] = id_map[old_id]
>     return messages
> ```
>
> Apply this when materializing one agent's turn into another agent's prompt
> context. **This is the single most underrated optimization in agentic pipelines.**

Note line 117: function **mutates in-place** and returns the same list.

**`08-security-observability-ops.md` lines 60–61**:

> **Per-session rate limits** keyed on `Mcp-Session-Id`: max 60 tool calls per
> minute per session, max 1000 per hour. Configurable.

This is broader rate-limiting (E13-security); E08_S04's caps are hard
counts (3 `search_papers` calls, 4 `get_chunk` calls), not rate limits.
No `RETRIEVAL_CAP_REACHED` error code appears anywhere in the codebase or
design notes — this is a new structured error.

### Existing middleware shape

`server/middleware.py` contains four **pure-ASGI** classes (not
`BaseHTTPMiddleware`). All four follow this shape:

```python
class FooMiddleware:
    def __init__(self, app, ...) -> None: ...
    async def __call__(self, scope, receive, send) -> None: ...
```

This is the only pattern used and the only one that works (the E06_S01
critique proved `BaseHTTPMiddleware` silently no-ops response interception
for SSE paths). The new `SessionState` middleware must follow the same
pure-ASGI shape.

### Session state and the `Mcp-Session-Id` header

The MCP library uses header name `"mcp-session-id"` (lowercase — verified
in `.venv/lib/python3.13/site-packages/mcp/server/streamable_http.py:52`:
`MCP_SESSION_ID_HEADER = "mcp-session-id"`). It is **server-issued** on
the first response to `initialize` and echoed back by the client on every
subsequent request.

The `mcp_session_id` is stored on the transport instance
(`StreamableHTTPServerTransport.mcp_session_id`) and written into response
headers. It does NOT flow into the `request_ctx` ContextVar used by
`ServerSession` or `FastMCP.Context`. The FastMCP `Context` object exposes
`client_id`, `request_id`, and `session` (the `ServerSession`) — **none of
which carry the `mcp-session-id` string**. `ServerSession` has no
`mcp_session_id` attribute.

**Consequence**: tool handlers (`handle_search_papers`, `handle_get_chunk`)
cannot read the `Mcp-Session-Id` header from a `ctx: Context` parameter.
The only viable approach is for a pure-ASGI middleware to extract the
header from `scope["headers"]` and set a module-level `ContextVar` BEFORE
the request reaches the FastMCP handler. This mirrors the pattern in
`mcp/server/auth/middleware/auth_context.py` which uses:
`auth_context_var = contextvars.ContextVar("auth_context", default=None)`.

### Handler error patterns

Existing handlers raise Python exceptions for validation failures (e.g.,
`raise ValueError(...)` in `handle_get_chunk` when `chunk_id` is
malformed). FastMCP converts these to JSON-RPC `-32602` (Invalid Params)
errors. For the `RETRIEVAL_CAP_REACHED` signal, the brief requires a
structured error with a `code` field and human-readable message. This
should return a `CallToolResult(isError=True, content=[TextContent(...)])` —
NOT a `raise` — so the agent receives the error as a structured tool result
it can read and act on, rather than an exception that would crash the
JSON-RPC call. The `handle_search_papers` handler already returns
`CallToolResult` objects for normal results (line 122), confirming this
pattern is feasible.

### Pytest test paths

`pyproject.toml` `[tool.pytest.ini_options]` sets `testpaths = ["tests"]`.
The brief specifies the test file as `server/orchestrator/test_id_canon.py`.
A file in `server/orchestrator/` will NOT be collected by `pytest` unless
`testpaths` is updated or `--rootdir` is used. **The test must live at
`tests/test_id_canon.py`** (or `testpaths` in `pyproject.toml` must be
extended to include `server/orchestrator` — either works but the former
requires no config change).

### Existing autouse fixture pattern

`tests/conftest.py` contains four autouse fixtures: `_patched_store_stats_path`,
`_patched_bm25_stats_path`, `_patched_bm25_index_root`, and
`_patched_cache_db_path`. All use `monkeypatch.setattr` or `monkeypatch.setenv`
and `yield`. The `SessionState` registry (a dict keyed by session ID) will be a
module-level singleton; a fifth autouse fixture `_reset_session_state`
following the same pattern is mandatory to avoid cross-test contamination.

### Threadsafety

The FastMCP server is async-only — tool handlers are async coroutines.
A `SessionState` counter dict does NOT need a `threading.Lock`. It needs
an `asyncio.Lock` per session (mirroring `cache.py:249`,
`resources.py:147`) to guard concurrent `search_papers` calls from the
same session that might race to increment the counter.

## 2. Prior decisions and lessons

- **E08_S02** (E08_S04's declared dependency) shipped `server/prompts.py`
  and left a TODO: "E08_S04 owns the v1 system-prompt body." E08_S04 does
  NOT touch `server/prompts.py`; the SYSTEM_PROMPT placeholder remains.
- **E06_S05** decided NOT to override the MCP library's `uuid4().hex`
  session-id generation (122 bits is ample for localhost; see
  `milestones/E06_S05/research-synthesis.md:112–118`). That decision stands
  here: the session ID we read from the header is the library's UUID4 hex.
- **No prior milestone** defines `RETRIEVAL_CAP_REACHED` or any per-session
  retrieval counter. This is net-new.
- **In-memory persistence**: the brief states caps are in-memory. This
  means counters reset on server restart. No SQLite or disk persistence
  needed (and per E08_S03 precedent, caching state is never correctness-
  critical).
- **Cache hit counts toward the cap**: the brief says "calls to
  `search_papers`" not "cache-miss calls." A Tier-1 hit still counts. The
  cap is about token-budget safety, not compute cost.

**FLAG**: the brief specifies `server/orchestrator/id_canon.py` and a test
at `server/orchestrator/test_id_canon.py`. Neither a `server/orchestrator/`
package nor a `server/orchestrator/__init__.py` exists. Two consequences:
(1) creating the directory requires adding `__init__.py`; (2) the test
path conflicts with `testpaths = ["tests"]`. Recommend: place the module at
`server/orchestrator/id_canon.py` (new package) and the test at
`tests/test_id_canon.py` (matches `testpaths`).

**FLAG — mutation discipline**: the pseudocode in `07-multi-agent-caching.md`
mutates `messages` in-place AND returns the same list. The brief calls
the function "idempotent — applying it twice produces the same result."
In-place mutation is safe here ONLY if callers do not expect to preserve
the original list. The function should return a NEW list (deep-copied) to
avoid footguns; idempotency must still hold.

## 3. External sources

### MCP 2025-06-18 spec — `mcp-session-id`

From the spec's Streamable HTTP section (verified in the MCP library source
as the authoritative implementation of the spec):

The spec states servers **MUST** include the `mcp-session-id` header in
the response to `initialize`. Clients **MUST** include it in all subsequent
requests to the same logical session. Servers **MUST** return HTTP 404 if
a request carries an unknown session ID.

The session ID is **server-issued** (not client-issued). A new session
begins with a client-sent `initialize` request that does NOT carry an
`mcp-session-id`. The server generates an ID and returns it. This matches
`streamable_http_manager.py:244`: `new_session_id = uuid4().hex`.

### Anthropic API — `tool_use_id` non-determinism

The Anthropic API's prompt-caching documentation notes that cache keys are
the hash of the exact prefix bytes. Any non-deterministic field in the
message history invalidates cross-agent cache reuse. The `tool_use_id`
field in `tool_use` content blocks and the `tool_use_id` field in
`tool_result` blocks are both assigned server-side and non-deterministic.
The design note at `07-multi-agent-caching.md:88–93` provides the verbatim
description and mitigation.

---

## Open questions

1. **Test path**: the brief says `pytest server/orchestrator/test_id_canon.py`
   but `testpaths = ["tests"]`. Recommendation: put the test at
   `tests/test_id_canon.py` and note the discrepancy in `docs/orchestrator-rules.md`.
   Do NOT change `testpaths` to avoid breaking the existing test collection.

2. **Mutation vs copy in `canonicalize_turn`**: the design note pseudocode
   mutates in-place. Recommendation: return a deep copy (via `copy.deepcopy`)
   so the caller's original list is preserved. The idempotency property still
   holds. Document this in the function's docstring.

3. **Missing session ID on request**: if `mcp-session-id` is absent from a
   `search_papers` or `get_chunk` request (e.g., a stateless call), the cap
   middleware cannot key the counter. Recommendation: skip cap enforcement
   (count = 0, caps never reached) and log a DEBUG line. Do NOT reject with 400;
   that would break stateless clients.

4. **`RETRIEVAL_CAP_REACHED` error envelope**: use
   `CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps({...}))])`.
   Do NOT use `raise` (which produces a JSON-RPC error the agent cannot parse as
   structured tool output). The handler must return the error object, not raise.

5. **Does the Tier-1 cache hit count toward the cap?** Recommendation: yes —
   the cap is "calls to `search_papers`" regardless of cache tier. The cap
   bounds token budget, not compute cost.

6. **AsyncIO lock per session**: each `SessionState` should carry an
   `asyncio.Lock` to prevent counter races from concurrent tool calls within
   the same session. A single module-level `asyncio.Lock` guarding the whole
   registry is too coarse (serializes all sessions); per-session locks are the
   right granularity.

7. **Registry growth**: the in-memory registry is `dict[str, SessionState]`.
   Long-running servers accumulate dead session entries. A simple LRU eviction
   (cap at 10K entries, matching the Tier-1 cache) or TTL (purge sessions
   inactive > 1 hour) prevents unbounded growth. The brief does not specify;
   the implementer must decide.

---

## External writes the implementation will require

None. All deliverables are local source files and tests. No git push, no PR,
no third-party API call, no infra mutation required to implement this milestone.
