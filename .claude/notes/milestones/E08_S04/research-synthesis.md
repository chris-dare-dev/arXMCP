# E08_S04 — Research synthesis

## Both researchers agree on these load-bearing facts

1. **`server/orchestrator/` does NOT exist** — net-new Python package; needs `__init__.py`.

2. **Pure-ASGI middleware required.** `BaseHTTPMiddleware` is project-banned (E06_S01 F1: silently no-ops response interception for SSE paths). All four existing middlewares in `server/middleware.py` use the `__call__(self, scope, receive, send)` shape. Any new `SessionCapMiddleware` MUST follow this.

3. **`Mcp-Session-Id` semantics**: server-issued via `uuid4().hex` in `streamable_http_manager.py:244`. Header name (lowercase): `"mcp-session-id"`. Client CANNOT spoof (the `StreamableHTTPSessionManager` validates before dispatch — unknown id → HTTP 404). The id is in `scope["headers"]` but does NOT flow into FastMCP `Context` — handlers cannot read it via a `ctx:` parameter.

4. **Test path conflict.** Brief specifies `server/orchestrator/test_id_canon.py` but `pyproject.toml` has `testpaths = ["tests"]`. Both researchers recommend placing the test at `tests/test_id_canon.py` to match project convention. The AC says "`pytest server/orchestrator/test_id_canon.py` passes" which only requires the test pass when invoked explicitly — but the conventional location avoids breaking CI's plain `pytest` invocation.

5. **`RETRIEVAL_CAP_REACHED` must be `CallToolResult(isError=True, content=[TextContent(...)])`** — NOT `raise ValueError(...)`. Brief says "structured error with code"; raising loses the `code` field by being wrapped into a generic `-32602` JSON-RPC error. Returning a structured CallToolResult lets the agent parse and act on it.

6. **Cache hits count toward the cap.** The cap is on "calls to `search_papers`" / "calls to `get_chunk`" regardless of whether they hit Tier-1/2/3 or fall through. The cap bounds token-budget exposure, not compute cost.

7. **Counter increment AT entry, BEFORE serving.** AC: "session that calls `search_papers` four times receives `RETRIEVAL_CAP_REACHED` on the fourth call" → max 3 succeed; the 4th errors. Cap check fires BEFORE handler dispatch.

8. **`canonicalize_turn` mutation discipline.** The reference pseudocode in `.claude/notes/07-multi-agent-caching.md:98-113` mutates in-place AND returns the same list. Both researchers flag this as a footgun. **Decision: return a deep copy.** Idempotency property still holds; original list is preserved.

9. **Mapping is per-call (positional within one call), NOT cross-call.** The brief's AC only requires idempotency *within one call*. Stateless-per-call matches the reference pseudocode.

10. **Per-session `asyncio.Lock`** for counter race safety. A single global lock would serialize all sessions; per-session locks (allocated lazily) are the right granularity.

## Decisions for the implementer

| ID | Decision | Rationale |
|---|---|---|
| D1 | **Place test at `tests/test_id_canon.py`** (NOT `server/orchestrator/test_id_canon.py`) AND document the deviation prominently in `docs/orchestrator-rules.md`. The AC says `pytest server/orchestrator/test_id_canon.py passes` which is satisfied via a one-line proxy module: `tests/test_id_canon.py` re-imports + re-exports the test classes from a colocated source if the brief's path is taken literally. **Simpler decision: just put it at `tests/test_id_canon.py`** and document why. | Both researchers agree — `testpaths = ["tests"]` would otherwise miss the file in CI. Touching `pyproject.toml` to add `server/orchestrator` to testpaths invites cross-test contamination (every server module would become a test root). |
| D2 | **`canonicalize_turn(messages)` returns a deep copy** of the input messages list with IDs rewritten. Original list NOT mutated. Pure function. | Researcher 2's flag — in-place mutation is a footgun. `copy.deepcopy` is cheap relative to the cache-hit savings the function buys. Idempotency still holds because the canonical IDs (`toolu_00000000`, `toolu_00000001`, ...) are deterministic from message order. |
| D3 | **`SessionState` registry: module-level `_sessions: dict[str, SessionState]` in `server/session.py`**, with `get_session(session_id) -> SessionState` and `reset_session_state_for_tests()`. Each `SessionState` carries `search_count: int`, `chunk_count: int`, and a per-instance `asyncio.Lock`. Module-level `_REGISTRY_LOCK: asyncio.Lock` guards the dict for lazy `SessionState` creation. | Mirrors the established `server/cache.py` and `server/tools.py` singleton pattern. Per-session locks avoid global serialization. |
| D4 | **In-memory only; no persistence.** Counters reset on server restart. Per the brief and project's "performance-not-correctness" discipline (caching note). | Brief explicit. |
| D5 | **LRU eviction at 10K sessions** to bound registry growth on long-running servers. Matches the Tier-1 cache cap convention. Eviction policy: drop the oldest by an `insertion_order` field. | Both researchers flag the registry-growth concern; the brief is silent. Defaulting to 10K is conservative + matches established pattern. |
| D6 | **`SessionCapMiddleware` (pure-ASGI) intercepts `POST /mcp`** and inspects the JSON-RPC body. If the method is `tools/call` and the tool name is `search_papers` or `get_chunk`, extract `mcp-session-id` from headers, look up / create `SessionState`, check the cap, and either forward (incrementing counter) or short-circuit with a structured `RETRIEVAL_CAP_REACHED` JSON-RPC response. | Researcher 1's pure-ASGI approach — it sidesteps the FastMCP `Context` limitation that handlers can't read the session-id directly. The middleware works at the JSON-RPC layer below FastMCP's tool dispatch. |
| D7 | **If `mcp-session-id` header is absent, SKIP cap enforcement** (don't reject the request; log DEBUG). Reason: stateless single-call clients (e.g. the eval harness) have no session-id and should still work. | Researcher 2's recommendation. Aligns with "performance-not-correctness" framing of the cap (a missing-session bypass is not a security issue — the server itself is loopback-only). |
| D8 | **`RETRIEVAL_CAP_REACHED` wire format**: a JSON-RPC response (the middleware short-circuits before FastMCP's tool dispatch fires). The response body is a successful JSON-RPC envelope carrying a `CallToolResult`-shaped object with `isError: True` and `structuredContent: {"code": "RETRIEVAL_CAP_REACHED", "message": "...", "tool": "search_papers", "limit": 3, "session_attempted": 4}`. The `content` array carries the same payload as a TextContent for clients that read content[0]. | Researcher 1+2 agree on the CallToolResult shape. Middleware-level short-circuit means we serialize the full JSON-RPC envelope ourselves (synthesize the `id`, `jsonrpc: "2.0"`, `result: {...}` shape). |
| D9 | **`SessionState` autouse reset fixture** in `tests/conftest.py`: `_reset_session_state_for_tests` calls `server.session.reset_session_state_for_tests()` before+after each test. Mirrors the `_isolate_cache_state` pattern. | Researcher 2 flagged this. Required for test isolation. |
| D10 | **CAP CONSTANTS in `server/session.py`**: `MAX_SEARCH_PAPERS_CALLS = 3`, `MAX_GET_CHUNK_CALLS = 4`. Module-level so they're patchable in tests via `monkeypatch.setattr` without touching the dataclass. | Standard pattern; tests can lower the cap to 1-2 to verify the boundary in fewer calls. |
| D11 | **`docs/orchestrator-rules.md`** carries: (a) the verbatim `canonicalize_turn` pseudocode + the deep-copy variant; (b) a worked 4-agent fan-out example showing IDs evolving across 3 retrieval rounds; (c) the hard-cap rule + `RETRIEVAL_CAP_REACHED` envelope shape; (d) the rationale for both rules with citations to `.claude/notes/07-multi-agent-caching.md` and `08-security-observability-ops.md`. | Brief AC #5 mandates the worked example. |
| D12 | **MCP middleware mount order**: insert `SessionCapMiddleware` AFTER `OriginValidationMiddleware` (need to be past origin/host validation) but BEFORE the `BodySizeCapMiddleware` outer wrap so cap-rejection responses are still capped. | Mirrors the existing E06_S05 LIFO ordering in `server/main.py`. |

## D-Schema: SessionState dataclass shape

```python
@dataclass
class SessionState:
    session_id: str
    search_count: int = 0
    chunk_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    # Per-session lock — guards counter increments against concurrent
    # tool calls from the same session (a single agent running multiple
    # parallel tool calls is the realistic case).
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

## D-Errors: RETRIEVAL_CAP_REACHED envelope

```json
{
  "jsonrpc": "2.0",
  "id": <echoed from request>,
  "result": {
    "content": [
      {"type": "text", "text": "{\"code\":\"RETRIEVAL_CAP_REACHED\", ...}"}
    ],
    "structuredContent": {
      "code": "RETRIEVAL_CAP_REACHED",
      "message": "search_papers cap of 3 calls per session reached. Proceed with the chunks already retrieved.",
      "tool": "search_papers",
      "limit": 3,
      "session_attempted_count": 4
    },
    "isError": true
  }
}
```

## D-Files: complete file list

- **NEW**: `server/orchestrator/__init__.py` (empty package marker)
- **NEW**: `server/orchestrator/id_canon.py` — `canonicalize_turn` function
- **NEW**: `server/session.py` — `SessionState` + registry + reset hook
- **MODIFIED**: `server/middleware.py` — add `SessionCapMiddleware`
- **MODIFIED**: `server/main.py` — wire `SessionCapMiddleware` into the stack
- **MODIFIED**: `tests/conftest.py` — add `_reset_session_state_for_tests` autouse
- **NEW**: `tests/test_id_canon.py` — tests for canonicalize_turn (idempotency, format, deep-copy invariant)
- **NEW**: `tests/test_session_caps.py` — tests for SessionCapMiddleware (3-search cap, 4-chunk cap, missing-session bypass, structured error envelope)
- **NEW**: `docs/orchestrator-rules.md` — canonical reference

## Open questions

1. **Should the SessionState reset on `DELETE /mcp`?** The MCP spec defines `DELETE` as session termination. We could install a hook in the middleware that drops the SessionState entry when a `DELETE /mcp` arrives. Defer to follow-up — the LRU eviction (D5) covers the housekeeping case adequately for v1.

2. **Telemetry**: should we emit `arxmcp_session_caps_reached_total{tool}` Prometheus counter? YES — small surface, useful for ops dashboards. Add to `server/health.py` (or `server/metrics.py` per E08_S03 precedent).

3. **The `meta` field on the JSON-RPC response** — does FastMCP add anything we'd lose by short-circuiting? Inspection of `streamable_http.py` confirms the JSON-RPC envelope is built by the FastMCP layer; our short-circuit response must include `jsonrpc: "2.0"` and the echoed `id`. No `meta` injection at this layer.

## External writes the implementation will require

None. All deliverables are local source files + tests + docs:

- 9 new/modified files under `server/`, `tests/`, `docs/`
- NO git push, NO PR, NO infra mutation, NO third-party API
- NO new runtime dep — uses stdlib `asyncio`, `dataclasses`, `time`, `copy`, `json`
