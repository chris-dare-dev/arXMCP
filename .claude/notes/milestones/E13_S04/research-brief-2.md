# Research Brief — E13_S04

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-18T02:30:00Z

## In-codebase context

### Rate-cap as actually implemented vs. the brief

The brief's rate-limit AC states: "1,500 calls in 1 hour from one session, limit fires at 1,000."

**CRITICAL MISMATCH — `server/session.py` implements no hourly rate limit.** The existing
`SessionCapMiddleware` tracks per-session counts of `search_papers` (cap=3) and `get_chunk`
(cap=4) with no time window at all. These are lifetime-of-session caps, not hourly rate
limits, and they cover only 2 of the 7 tools. There is no "max 1000 calls per hour" counter
anywhere. From `server/session.py`:

> `MAX_SEARCH_PAPERS_CALLS: int = 3`
> `MAX_GET_CHUNK_CALLS: int = 4`
> `TOOLS_WITH_CAPS: Final[dict[str, str]] = {"search_papers": "search_papers", "get_chunk": "get_chunk"}`

And from `08-security-observability-ops.md § Threat 4`:

> "Per-session rate limits keyed on `Mcp-Session-Id`: max 60 tool calls per minute per
> session, max 1000 per hour. Configurable."

This spec was never implemented (no minute or hour window logic exists). The brief's "1,500
calls, fires at 1,000" is referencing a design-note goal, not existing code. **The
implementer must BUILD the hourly rate limiter from scratch** or reframe AC to match the
existing per-call retrieval caps.

### JSON-Schema `k` constraints — PRESENT for all tools

`search_papers`: `Field(ge=1, le=50)` — `k=10000` WILL be rejected.
`find_equation`: `Field(ge=1, le=MAX_K)` where `MAX_K=50`.
`find_lemma_by_name`: `Field(ge=1, le=MAX_K)`.
`cite_neighbors`: `Field(ge=1, le=3)` for `depth`, `Field(ge=1, le=100)` for `limit`.

**k=10000 and depth=100 ARE already enforced** by Pydantic Field constraints that flow
into JSON Schema via FastMCP's introspection. The constraint `le=MAX_K (=50)` on k and
`le=3` on depth pre-exist. The test just needs to confirm Pydantic rejects at the right
surface before the handler body fires.

### `filters` dict — no max-size constraint

`search_papers` has: `filters: Annotated[dict[str, Any] | None, Field(description="Reserved...")]`
— NO `max_length`, `max_items`, or size constraint. A 10,000-key dict is accepted by
Pydantic. **This is a real gap.** The brief's "10,000-item filter list → -32602" AC
requires a NEW constraint to be added.

### Byte cap — PRESENT and wired

`server/tools.py::enforce_byte_cap` exists and is called in `get_chunk`. It checks:
`len(serialized.encode("utf-8")) * _WIRE_OVERHEAD_FACTOR <= cap` where
`_WIRE_OVERHEAD_FACTOR = 2` and `cap = get_resources().config.result_byte_cap` (default 256KB).
The test for "300 KB chunk body → resource_link" is testing a real, wired mechanism.
**However**: `search_papers` does NOT call `enforce_byte_cap`. The brief implies all 7
tools are covered; in reality only `get_chunk` calls it.

### `dependency_graph` does NOT exist

**The brief's `dependency_graph(depth=100)` AC references a non-existent tool.** The
real tool surface (from `server/tools.py::ALL_TOOLS`) is:
`search_papers`, `get_chunk`, `find_equation`, `get_definitions`, `find_lemma_by_name`,
`get_paper`, `cite_neighbors`. The closest real tool with a `depth` parameter is
`cite_neighbors` (depth already constrained `le=3`). Reframe AC to `cite_neighbors(depth=100)`.

### Prerequisite milestones E06_S07, E06_S08, E07_S10 — FICTIONAL

`E06` roadmap has only S01–S06 (`grep "^### E06_S"` returns S01–S06 only). E06_S07 and
E06_S08 do not exist. `E07` roadmap has only S01–S04. E07_S10 does not exist. These
are all fictional prerequisites following the same drift pattern found in E13_S01/S02.
The design-note-level specs for these features live in `08-security-observability-ops.md`
§ Threat 4, but no prior milestone formalized them. **E13_S04 is both specification AND
enforcement**, same pattern as E13_S03 for the LaTeXML sandbox.

### Doc placement — `docs/security/` is WRONG

The brief states deliverable: `docs/security/threat-4-audit.md`. Per CLAUDE.md §1,
`docs/` is ONLY operator-facing documentation. Correct destination:
`.claude/docs/security-threat-4-audit.md`. Precedent established in E13_S01
implementation-summary.

## Prior decisions and lessons

From agent memory (carried forward from E13_S01–S03):

- **E07 roadmap has only S01–S04.** Any brief referencing E07_S10 as dependency cites
  a fictional milestone. Confirmed again here.
- **No `dependency_graph` tool exists.** Established in E13_S01/S02 briefs; the 7-tool
  surface is authoritative at `server/tools.py::ALL_TOOLS`.
- **AC error code `-32602` is not what the mcp Python SDK emits** for Pydantic validation
  failures (established in E13_S01). FastMCP wraps Pydantic `ValidationError` as
  `isError=True` in `CallToolResult`, NOT as JSON-RPC `-32602`. Tests must assert
  rejection (handler body not entered) rather than asserting the specific JSON-RPC code.

From git log: E13_S01, S02, S03 all shipped a three-commit pattern. Rate limit and byte
cap functionality have never been audited in a dedicated security test file. `tests/security/`
directory currently has: `test_delimiters.py`, `test_latexml_sandbox.py`,
`test_path_traversal.py`, `__init__.py`, `fixtures/`.

## External sources

### MCP 2025-06-18 spec — error codes and tool errors

From the spec (fetched live at https://modelcontextprotocol.io/specification/2025-06-18/server/tools):

> "Tools use two error reporting mechanisms:
> 1. **Protocol Errors**: Standard JSON-RPC errors for issues like: Unknown tools, Invalid
>    arguments, Server errors
> 2. **Tool Execution Errors**: Reported in tool results with `isError: true`: API failures,
>    Invalid input data, Business logic errors"

Example for invalid arguments: `{"code": -32602, "message": "Unknown tool: invalid_tool_name"}`.

**On rate limiting:** The MCP 2025-06-18 spec says servers MUST "Rate limit tool invocations"
(Security Considerations section) but defines NO specific error code for rate limiting.
`-32005` is NOT defined in the MCP spec. The server-defined range is `-32000` to `-32099`.
Using `-32005` is a project convention, not a spec requirement.

**Conclusion on `-32005`:** Not in spec. The existing `SessionCapMiddleware` returns a
structured `isError=True` JSON-RPC result (code `RETRIEVAL_CAP_REACHED` in
structuredContent), not a JSON-RPC error with `-32005`. The brief's AC "returning -32005"
is incorrect for current architecture. Reframe: rate-limit response surface is
`CallToolResult(isError=True, structuredContent={"code": "RETRIEVAL_CAP_REACHED", ...})`.

### OWASP API4:2023 — Unrestricted Resource Consumption

From https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/:

> "Implement a limit on how often a client can interact with the API within a defined
> timeframe (rate limiting). Rate limiting should be fine tuned based on the business needs."
> "Define and enforce a maximum size of data on all incoming parameters and payloads, such
> as maximum length for strings, maximum number of elements in arrays."

OWASP does NOT prescribe per-session vs per-IP vs per-tenant; it is intentionally
flexible. For arXMCP's localhost-only single-user deployment, **per-session keyed on
`Mcp-Session-Id` is correct**: it reflects the MCP protocol's session identity and
matches the existing `SessionCapMiddleware` architecture. Per-IP would be meaningless
(all traffic is 127.0.0.1).

### Spec source for no `-32005`

From https://www.mcpevals.io/blog/mcp-error-codes (secondary source corroborating the
spec): "The standard reserved range is -32000 to -32099 for server implementation errors.
-32005 is not documented as a standard MCP error code." `-32050` appears as informal
convention for rate limiting in some implementations, not `-32005`.

## Failure-mode analysis

| # | Trigger | Symptom | Mitigation |
|---|---|---|---|
| FM-1 | `filters` dict with 10,000 keys accepted | Pydantic passes, handler enters with massive dict; v1 ignores it but future filter wiring would OOM | Add `max_length=100` (or `max_items` if using list-form) to `filters` Field in `search_papers`; test must confirm Pydantic rejects at this surface |
| FM-2 | `k=10001` — test asserts -32602 but SDK emits isError=True | FastMCP wraps Pydantic ValidationError as isError=True result, NOT JSON-RPC -32602. Test asserting wrong surface always fails | Assert `result.isError == True` and handler body not entered (via spy or early-return mock), not JSON-RPC error code |
| FM-3 | `enforce_byte_cap` called but handler ignores `content_blocks` | Handler calls `enforce_byte_cap()` but does `return envelope(structured)` instead of using the returned `(structured, blocks)` tuple; 300 KB body emits inline silently | Test must inspect actual response wire shape; mock the config to set a low cap and send a body over cap, assert resource_link present |
| FM-4 | Rate limit is per-process; multi-worker bypasses it | `_SESSIONS` in `server/session.py` is a module-level in-memory dict; multi-worker deployments have independent dicts; the cap is trivially bypassed | Document single-process constraint in audit doc; the test must note this limitation. arXMCP runs single-worker by default (E08_S01 made `--workers 1` the documented prod config) |
| FM-5 | Hourly rate limit does not exist | The brief's "1,500 calls, fires at 1,000" AC references a feature that was never implemented. Tests against this behavior test nothing | Either implement the hourly counter (adds complexity) or reframe AC to existing `SessionCapMiddleware` per-call caps (max 3 search_papers, max 4 get_chunk per session). Recommendation: reframe AC |
| FM-6 | `cite_neighbors(depth=100)` — the `le=3` constraint already rejects it | This is a pre-existing enforcement; the test just needs to confirm it. No implementation needed | Write test that asserts isError=True for depth=100 using the same surface-assertion discipline |
| FM-7 | Rate limit off-by-one: fires at 2 instead of 3 (fencepost) | `check_and_increment` returns `allowed=False` when `current >= limit`; for `MAX_SEARCH_PAPERS_CALLS=3` this allows calls 1,2,3 and blocks 4th. Test must verify exactly 3 allowed, 4th blocked | Write an explicit off-by-one test: call 3 times, verify success; call 4th, verify RETRIEVAL_CAP_REACHED |
| FM-8 | Test OOM from oversized synthetic body | A 300 KB test payload is fine; do NOT use 30 MB. The cap is at 256 KB (after `_WIRE_OVERHEAD_FACTOR=2`, the inner content must exceed 128 KB to trip it). Use exactly 130 KB of body_text | Size synthetic bodies precisely: `"x" * (130 * 1024)` trips the cap cleanly |
| FM-9 | `dependency_graph` tool in test fixture doesn't exist | Any pytest parametrization including `dependency_graph` fails with tool-not-found, not with the expected validation error | Remove `dependency_graph` from all test fixtures; use `cite_neighbors` as the depth-constrained tool |
| FM-10 | `search_papers` does not call `enforce_byte_cap` | Brief implies all 7 tools covered; only `get_chunk` does it at v1. Byte-cap test scoped to `get_chunk` only. | Scope byte-cap AC to `get_chunk`; note in audit doc that `search_papers` is excluded (bounded by k≤50 × snippet≤150 chars, so max response is ~75 KB before cap fires) |
| FM-11 | Pydantic validates BEFORE JSON-Schema maximum check | In the FastMCP+Pydantic stack, Pydantic IS the JSON-Schema validator for input. The schema `maximum` constraint IS the Pydantic `le=` constraint. They are the same check. There is no second layer | Tests should confirm via a handler-spy or mock that the handler async function is never awaited when Pydantic rejects |

## Recommendation

**Reframe three ACs before writing any code:**

1. `dependency_graph(depth=100)` → `cite_neighbors(depth=100)` (tool does not exist)
2. "1,500 calls / 1 hour / fires at 1,000" → verify existing `SessionCapMiddleware` fires
   at 4 for `search_papers` (3 allowed) and 5 for `get_chunk` (4 allowed). Document the
   gap between the design note and the v1 implementation in the audit doc, not a new
   implementation.
3. "-32005" → `isError=True` with `code="RETRIEVAL_CAP_REACHED"` in `structuredContent`

**Proceed with this test structure:**

- `test_k_constraint_rejected`: `search_papers(k=10001)` → confirm handler body not entered
  (use `AsyncMock` on handler internals or patch `get_resources`)
- `test_depth_constraint_rejected`: `cite_neighbors(depth=100)` → same pattern
- `test_filter_list_constraint_rejected`: `search_papers(filters={"a": i for i in range(10001)})` →
  **requires adding `max_length=100` to the `filters` Field** (no constraint exists today)
- `test_byte_cap_overflow`: monkeypatch `config.result_byte_cap=1024`, call `get_chunk` with
  `body_text = "x" * 2000`, assert `resource_link` in response content blocks
- `test_retrieval_cap_fires`: call `search_papers` 4 times on same session, assert 4th
  returns `isError=True` with `code="RETRIEVAL_CAP_REACHED"`

**Doc placement:** `.claude/docs/security-threat-4-audit.md` (NOT `docs/security/`).

**No tool-schema change required** if `filters` Field constraint is added inline to the
existing parameter annotation (it does not add a new tool or change the tool name/description).
If the description text changes, re-pin `EXPECTED_TOOL_SCHEMA_SHA256`.

## Open questions

1. **`filters` constraint type:** Pydantic `Field(max_length=N)` on a `dict` constrains
   the number of keys. Verify that `max_length=100` on `dict[str, Any] | None` generates
   `maxProperties: 100` in the JSON Schema (the FastMCP → Pydantic path should do this,
   but needs verification before writing the test).

2. **Hourly rate limit implementation decision:** The design note specifies "max 60/min,
   max 1000/hour". The brief imports this verbatim. The recommendation is to reframe to the
   existing session-cap model. The orchestrator should confirm this reframing is acceptable
   before the implementer writes code — if the hourly counter is required, it adds a
   `time.time()`-windowed counter to `SessionState`, which is non-trivial.

## External writes the implementation will require

None — this milestone is purely local (test + doc files, no git push, no infra mutation).

Sources consulted:
- [OWASP API4:2023 Unrestricted Resource Consumption](https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/)
- [MCP 2025-06-18 Tools spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP Error Codes](https://www.mcpevals.io/blog/mcp-error-codes)
