# Research Brief — E13_S04

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-18T02:15:00Z

## In-codebase context

### Threat 4 verbatim from `08-security-observability-ops.md`

> **Mitigations:**
> - JSON-Schema `maximum` on every numeric parameter (`k <= 50`).
> - Hard byte cap on tool result inline content (256 KB; spillover via `resource_link`).
> - **Per-session rate limits** keyed on `Mcp-Session-Id`: max 60 tool calls per
>   minute per session, max 1000 per hour. Configurable.
> - Embedder/reranker semaphores prevent runaway concurrent calls.

### Per-tool numeric parameter audit (as of current codebase)

**`search_papers` (`server/handlers/search.py`):**
- `k`: `Field(ge=1, le=50)` — MAX_K=50. k=10000 WILL be rejected by Pydantic at handler entry.
- `query`: `Field(min_length=1, max_length=2000)` — string cap present.
- `filters`: `dict[str, Any] | None` — **NO** `max_length`, NO item-count cap. A dict with 10,000 author entries is NOT rejected at the schema level. This is a real enforcement gap.
- `cursor`: `str | None` — no cap.

**`get_chunk` (`server/handlers/chunk.py`):**
- No numeric `k` parameter. Only `chunk_id` (string), `include_referenced` (bool), `include_equations` (bool).
- **Calls `enforce_byte_cap`** — 256 KB cap is enforced. `resource_link` is emitted when exceeded.

**`find_equation` (`server/handlers/equation.py`):**
- `k`: `Field(ge=1, le=50)` — MAX_K=50. k=10000 rejected.
- `latex_or_mathml`: `Field(min_length=1, max_length=4000)`.
- Does NOT call `enforce_byte_cap`.

**`get_definitions` (`server/handlers/definitions.py`):**
- `paper_id`, `term`, `cursor` — no numeric k parameter. PAGE_SIZE=100 is a module-level constant, not a user-supplied argument.
- **Calls `enforce_byte_cap`** for the full definitions payload.
- No list-argument to have a count cap on.

**`find_lemma_by_name` (`server/handlers/lemma.py`):**
- `k`: `Field(ge=1, le=50)` — MAX_K=50. k=10000 rejected.
- `name`: `Field(min_length=1, max_length=200)`.
- Does NOT call `enforce_byte_cap`.

**`get_paper` (`server/handlers/paper.py`):**
- No numeric k. Only `paper_id` (string), `version` (int | None, reserved, no le= cap).
- Does NOT call `enforce_byte_cap`.

**`cite_neighbors` (`server/handlers/citations.py`):**
- `depth`: `Field(ge=1, le=3)` — depth=100 WILL be rejected by Pydantic. This is the real cap.
- `limit`: `Field(ge=1, le=100)` — max 100 neighbors.
- Does NOT call `enforce_byte_cap` (v1 stub returns empty list).

### Byte-cap mechanism: `enforce_byte_cap` in `server/tools.py`

`enforce_byte_cap` is the canonical mechanism (lines 418–467 of `server/tools.py`). When `json.dumps(structured_content).encode('utf-8') * 2 > config.result_byte_cap`, the body at `body_text_path` is truncated to 1024 chars, `body_truncated=True` is set, and a `resource_link` content block with `uri=arxmcp://chunks/<chunk_id>` is returned.

**Handlers that call `enforce_byte_cap`:** `get_chunk`, `get_definitions`.
**Handlers that do NOT call `enforce_byte_cap`:** `search_papers`, `find_equation`, `find_lemma_by_name`, `get_paper`, `cite_neighbors`.

The `search_papers.py` docstring explicitly acknowledges this: "Note: `search_papers` does NOT call `enforce_byte_cap` (only `get_chunk` does at v1)."

The 256 KB byte cap AC — "Synthetic 300 KB chunk body → response carries `resource_link`" — is already implemented for `get_chunk`. The test should verify this against the handler that actually enforces it.

### Per-session rate limit: CRITICAL gap

`server/session.py` implements per-session caps for `search_papers` (max 3 calls) and `get_chunk` (max 4 calls) per the E08_S04 design. These are **retrieval-round caps**, NOT an hourly tool-call rate limit.

The design note specifies: "max 60 tool calls per minute per session, max 1000 per hour." **NEITHER of these limits exists anywhere in the codebase.** There is:
- No timestamp tracking per tool call
- No sliding-window rate limiter
- No 1000/hour global cap
- No 60/minute cap

The `SessionCapMiddleware` in `server/middleware.py` enforces the retrieval caps (3 search, 4 chunk) by inspecting the JSON-RPC body tool name. It does NOT implement any time-based rate limiting.

The brief's AC — "1,500 calls in 1 hour from one session, limit fires at 1,000" — requires implementing a time-based rate limiter that does NOT exist. This is NEW implementation work, not just test writing.

### Dependency milestones: ALL THREE ARE FICTIONAL

**`E06_S07`**: E06 has milestones S01–S06 only (per `grep "^### " .claude/roadmap/E06-mcp-server.md`). E06_S07 does not exist.

**`E06_S08`**: Same — does not exist. E06 stops at S06.

**`E07_S10`**: E07 has milestones S01–S04 only (per `grep "^### " .claude/roadmap/E07-hybrid-retrieval.md`). E07_S10 does not exist.

**This is the same pattern as E07_S12 (fictional, E13_S01) and E07_S13 (fictional, E13_S02).** The mitigations referenced were NEVER implemented by those milestones. E13_S04 is therefore BOTH the spec milestone AND the enforcement milestone — identical to the precedent set by S01–S03.

### What `dependency_graph(depth=100)` means for the real codebase

**`dependency_graph` does not exist.** The real 7-tool surface (`server/tools.py::ALL_TOOLS`) is: `search_papers`, `get_chunk`, `find_equation`, `get_definitions`, `find_lemma_by_name`, `get_paper`, `cite_neighbors`. The closest real tool is `cite_neighbors` which has `depth: Field(ge=1, le=3)`. depth=100 IS rejected by Pydantic before handler body executes.

### `filters` list: enforcement gap

`search_papers.filters` is `dict[str, Any] | None` with no `max_length` or item-count constraint. A filter dict with 10,000 items is NOT rejected at the schema level. However, the E13_S01 implementation-summary §Drift 5 flags: "No `max_length` caps — adding `Field(max_length=...)` would bump `TOOL_SCHEMA_VERSION` and invalidate BP1 prompt-cache." This deferred the same decision for the `pattern=` migration.

Adding a `max_length` or item-count cap to `filters` (which is a `dict`) requires either (a) changing the type to a more constrained model (which re-pins `EXPECTED_TOOL_SCHEMA_SHA256` and bumps `TOOL_SCHEMA_VERSION`), or (b) doing the validation in the handler body with `raise ValueError` (not at schema level). The AC says "-32602 at JSON-Schema validation" — but as established in E13_S01 §Drift 2, the SDK never emits -32602; it wraps as `CallToolResult(isError=True)`. Handler-body validation is semantically equivalent.

### Tool schema re-pinning requirement

If the milestone adds `max_length` or any Field constraint to the `filters` parameter of `search_papers`, `EXPECTED_TOOL_SCHEMA_SHA256` must be re-pinned and `TOOL_SCHEMA_VERSION` bumped. This triggers BP1 prompt-cache invalidation per `07-multi-agent-caching.md`.

## Prior decisions and lessons

**From E13_S01 (Drift 2):** The mcp Python SDK NEVER emits JSON-RPC -32602 for tool-arg validation. Pydantic and jsonschema failures surface as `CallToolResult(isError=True)`. Reframe all AC assertions from "-32602" to "isError=True, handler body not entered." The security goal (handler not entered) is met; wire-level code is implementation choice.

**From E13_S01 (Drift 7) and E13_S02 (Drift 3):** Doc destination is `.claude/docs/security-threat-4-audit.md`, NOT `docs/security/threat-4-audit.md`. CLAUDE.md §1 restricts `docs/` to operator-facing content referenced by root README.

**From E13_S01–S03:** Fictional dependency milestones (E07_S12, E07_S13, E02_S02) become BOTH the spec AND the enforcement source. Same here: E06_S07, E06_S08, E07_S10 never shipped. This milestone must both spec the limits AND implement/test them.

**From E13_S02:** `enforce_byte_cap` and `wrap_retrieved_text` are now wired into the codebase. The byte-cap AC is testable against `get_chunk` directly.

**`KMP_DUPLICATE_LIB_OK=TRUE` guard in `tests/conftest.py` is load-bearing.** New security tests must not remove it.

**No `anthropic` SDK at runtime** — new test helpers must not import `anthropic`.

**No `BaseHTTPMiddleware`** — any new rate-limit middleware must be pure-ASGI (same pattern as `SessionCapMiddleware`).

## External sources

**MCP 2025-06-18 spec error codes** (from `mcp/types.py` installed in `.venv`):
- MCP-specific range: `[-32000, -32099]`. Defined constants: `URL_ELICITATION_REQUIRED = -32042`, `CONNECTION_CLOSED = -32000`.
- Standard JSON-RPC: `PARSE_ERROR = -32700`, `INVALID_REQUEST = -32600`, `METHOD_NOT_FOUND = -32601`, `INVALID_PARAMS = -32602`, `INTERNAL_ERROR = -32603`.
- **`-32005` does NOT appear anywhere** in the MCP spec or the `mcp` Python SDK. It is a project invention or aspirational code in the brief. The existing project pattern from E08_S04 is `RETRIEVAL_CAP_REACHED` (a structured `isError=True` payload, not a JSON-RPC wire error). The rate-limit response should follow the same pattern.

**MCP 2025-06-18 spec rate limits:** The spec (fetched at `modelcontextprotocol.io/specification/2025-06-18`) does not define any rate-limit mechanism or error code for rate limiting. Rate-limiting is entirely implementation-defined.

**Anthropic prompt-caching docs:** Not fetched (this milestone does not touch tool schema or caching). If `filters` Field constraints are added, tool schema changes and caching must be re-evaluated.

## Recommendation

**Implement E13_S04 as a COMBINED enforcement + test milestone** (same pattern as E13_S01–S03), with five targeted sub-tasks:

1. **`k=10000` AC (search_papers, find_equation, find_lemma_by_name):** These already have `Field(ge=1, le=50)`. Tests just need to call the handler with k=10000 and assert `isError=True` without handler body executing. No new code needed.

2. **`depth=100` AC (cite_neighbors reframe):** `dependency_graph` does not exist. Reframe to `cite_neighbors(depth=100)`. Already has `Field(ge=1, le=3)`. Test is trivial.

3. **`filters` list cap (search_papers):** Implement as handler-body validation (`if filters and len(filters) > 100: raise ValueError(...)`) rather than a Pydantic Field constraint, to avoid tool schema re-pinning cost. The security goal is identical.

4. **300 KB byte-cap AC:** Already enforced by `get_chunk` via `enforce_byte_cap`. Write a test that injects a synthetic oversized chunk body into the handler and asserts `body_truncated=True` + `resource_link` in response. No new code needed.

5. **1,000/hour rate-limit AC:** Implement a new `HourlyRateLimitMiddleware` (pure-ASGI, same pattern as `SessionCapMiddleware`) with a sliding-window token bucket keyed on `Mcp-Session-Id`, cap=1000/hour. Return `isError=True` with `code="RATE_LIMIT_REACHED"` (mirroring `RETRIEVAL_CAP_REACHED` pattern) rather than -32005 (which does not exist in the spec). Mount alongside `SessionCapMiddleware` in `server/main.py`.

**Doc destination:** `.claude/docs/security-threat-4-audit.md` (not `docs/security/`).

**Do NOT re-pin `EXPECTED_TOOL_SCHEMA_SHA256`** unless the filters validation moves to Pydantic Field level. Handler-body validation is invisible to the tool schema.

## Open questions

1. **`filters` cap level:** Should filters be capped at 100 items (reasonable) or some other value? The brief says "10,000-item filter list → -32602" but doesn't specify what the actual cap should be. Implementer should pick `max_filter_items=100` as the enforcement threshold (matches MCP server convention of small payloads).

2. **Hourly rate-limit window:** Should the 1,000/hour cap use a fixed window (reset at the top of each hour) or a sliding window (rolling 3600 seconds)? Sliding window is more robust against burst-at-boundary attacks but slightly more complex. Recommend sliding window with a simple `deque` of timestamps per session — same in-memory approach as `SessionCapMiddleware`.

3. **Rate-limit middleware placement:** Where in the middleware stack should `HourlyRateLimitMiddleware` sit? Recommend: after `SessionCapMiddleware` (reuses the same session-id validation and MCP path prefix logic) so both caps apply on the same request.

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR creation, no external API calls, no infra mutations.
