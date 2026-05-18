# Research Synthesis — E13_S04

**Milestone:** Threat-4 audit — resource-exhaustion limits across the 7 tools
**Generated:** 2026-05-18
**Inputs:** `research-brief-1.md` (in-codebase audit) + `research-brief-2.md` (external + failure-mode)

---

## Executive convergence

Both briefs converge on these facts. Pattern identical to E13_S01–S03:
the brief is partly disconnected from codebase reality, and this
milestone is BOTH specification AND enforcement.

### Verified codebase facts (both researchers confirmed)

1. **Threat 4 verbatim** from `.claude/notes/08-security-observability-ops.md`:

   > **Mitigations:**
   > - JSON-Schema `maximum` on every numeric parameter (`k <= 50`).
   > - Hard byte cap on tool result inline content (256 KB; spillover via `resource_link`).
   > - **Per-session rate limits** keyed on `Mcp-Session-Id`: max 60 tool calls per
   >   minute per session, max 1000 per hour. Configurable.
   > - Embedder/reranker semaphores prevent runaway concurrent calls.

2. **Numeric `Field(le=...)` caps already exist** for all numeric tool args:
   - `search_papers.k`: `Field(ge=1, le=50)` — `k=10000` rejected ✓
   - `find_equation.k`: `Field(ge=1, le=50)` ✓
   - `find_lemma_by_name.k`: `Field(ge=1, le=50)` ✓
   - `cite_neighbors.depth`: `Field(ge=1, le=3)` — `depth=100` rejected ✓
   - `cite_neighbors.limit`: `Field(ge=1, le=100)` ✓
   - **No `dependency_graph` tool exists** — brief's `depth=100` AC reframes to `cite_neighbors`.

3. **`enforce_byte_cap` already shipped** in `server/tools.py` lines 418-467.
   Called by `get_chunk` and `get_definitions`. NOT called by `search_papers`,
   `find_equation`, `find_lemma_by_name`, `get_paper`, `cite_neighbors`. The
   300 KB AC is testable against `get_chunk`.

4. **Per-session retrieval caps** at `server/session.py`:
   - `MAX_SEARCH_PAPERS_CALLS = 3` (lifetime-of-session)
   - `MAX_GET_CHUNK_CALLS = 4` (lifetime-of-session)
   - Returns `isError=True` with `code="RETRIEVAL_CAP_REACHED"`.
   - These are **NOT time-windowed**; they're absolute lifetime caps.

5. **No hourly rate limit exists** anywhere in the codebase. The "1000
   calls/hour" mitigation from the design note was never implemented.

6. **`filters` parameter on `search_papers`** has NO `max_length` /
   item-count constraint (`dict[str, Any] | None` with no size cap).
   10,000-item filter list is accepted at the schema layer today.

7. **Fictional prerequisites** (same pattern as E07_S12, E07_S13):
   - **`E06_S07`** — E06 stops at S06 ❌
   - **`E06_S08`** — E06 stops at S06 ❌
   - **`E07_S10`** — E07 stops at S04 ❌
   - **This milestone is therefore BOTH the spec AND the enforcement
     milestone** — same shape as E13_S01–S03.

8. **`-32005` is NOT in the MCP 2025-06-18 spec.** R2 verified: MCP
   server-error range is `[-32000, -32099]`, no rate-limit code is
   defined. R1 verified: `mcp/types.py` defines `-32042`
   `URL_ELICITATION_REQUIRED` and `-32000` `CONNECTION_CLOSED`; no
   `-32005`. Project convention: use `isError=True` with structured
   `code="..."` (mirrors `RETRIEVAL_CAP_REACHED` pattern).

9. **`-32602` is NOT what the SDK emits** for Pydantic / JSON-Schema
   tool-arg validation (verified in E13_S01). FastMCP wraps
   `ValidationError` as `CallToolResult(isError=True)`. AC reframe is
   identical to E13_S01: "schema validation rejects BEFORE handler
   body" — security goal met, wire-level code is implementation choice.

10. **Doc placement reframe** — `docs/security/threat-4-audit.md` →
    `.claude/docs/security-threat-4-audit.md` per CLAUDE.md §1 and
    E13_S01–S03 precedent.

---

## Divergence and resolution

### D1 — Hourly rate limit: build it or reframe the AC?

- **R1:** BUILD a new `HourlyRateLimitMiddleware` (pure-ASGI, sliding
  window deque, cap 1000/hour, keyed on `Mcp-Session-Id`). Mount
  alongside `SessionCapMiddleware`. ~80 LOC of new code.
- **R2:** REFRAME the AC. Test the existing per-session lifetime
  caps (`MAX_SEARCH_PAPERS_CALLS = 3`, `MAX_GET_CHUNK_CALLS = 4`).
  Document the design-note-vs-v1 gap in the audit doc. No new code.

**Resolution: ADOPT R1's build path.** Decisive reasons:

1. **The design note explicitly specifies the 1000/hour cap.** The
   per-tool retrieval cap (3 search, 4 chunk) is a DIFFERENT axis
   — it caps retrieval-loop semantics for agent runtime
   correctness, not resource exhaustion. They're complementary,
   not redundant.

2. **The existing per-tool caps cover only `search_papers` and
   `get_chunk`** — 2 of 7 tools. An adversary in a retry loop
   calling `find_lemma_by_name`, `find_equation`,
   `get_definitions`, `get_paper`, or `cite_neighbors` 10,000
   times in an hour faces ZERO rate limit today. That's the
   actual Threat 4 surface.

3. **E13_S03 precedent**: when the brief calls for a real defense
   improvement (process-group kill discipline), we built it.
   Same logic applies here. The audit-only path would document
   a known gap rather than close it.

4. **The fix is small.** Extending `SessionState` with a
   timestamp deque + adding a `check_hourly_rate_limit` function
   to `session.py` + calling it from `SessionCapMiddleware` is
   ~50 LOC of focused work, same pattern as the existing
   `check_and_increment`.

### D2 — `filters` cap: Pydantic Field vs. handler-body validation?

- **R1:** Handler-body validation — `if filters and len(filters) >
  MAX_FILTER_ITEMS: raise ValueError(...)`. Cheap (2 LOC). No tool
  schema change.
- **R2:** Pydantic `Field(max_length=100)` on the `filters` dict.
  Generates `maxProperties: 100` in the JSON Schema. 1 LOC change
  in the handler signature.

**Resolution: ADOPT R1's handler-body validation.** Decisive reason:

The Pydantic `Field(max_length=...)` on the `filters` dict WOULD
change the rendered `tools/list` output, which means re-pinning
`EXPECTED_TOOL_SCHEMA_SHA256` and bumping `TOOL_SCHEMA_VERSION`.
Per `.claude/notes/07-multi-agent-caching.md`, this invalidates
BP1 prompt-cache discipline. The handler-body path is identical
in security outcome (rejection before any meaningful processing)
without the cache-invalidation cost.

This mirrors the E13_S01 decision: "No Pydantic `pattern=`
migration — adding `Field(pattern=...)` would re-trigger
`EXPECTED_TOOL_SCHEMA_SHA256` and bump `TOOL_SCHEMA_VERSION`
(invalidating BP1 prompt-cache per note 07). Deferred per D7."
Same calculation applies to `max_length` here.

### D3 — Rate-limit error code

- **R1:** Use structured `isError=True` with `code="RATE_LIMIT_REACHED"`
  (analogous to existing `RETRIEVAL_CAP_REACHED`).
- **R2:** Same conclusion via different reasoning.

**Resolution:** Use `code="RATE_LIMIT_EXCEEDED"` (different code
from `RETRIEVAL_CAP_REACHED` so consumers can distinguish the
source of the rejection). Both researchers converge here — no
divergence.

---

## Orchestrator synthesis note

Both briefs are strong; convergence on 9 of 10 facts. R1's
deep-handler audit (per-tool Field constraint table, enforce_byte_cap
caller list, session.py reality) is decisive grounding. R2's
external research (MCP spec quote, OWASP API4, "-32005 not in spec"
verification) is decisive for the wire-level reframes.

The single material divergence (D1: build vs. audit) is resolved
in favor of building, consistent with E13_S03 precedent and the
genuine gap in 5-of-7-tools coverage.

---

## Implementation decision — INLINE path

Size estimate:
- `server/session.py` — +60 LOC (timestamp deque, hourly check function)
- `server/middleware.py` — +30 LOC (extend SessionCapMiddleware to call hourly check)
- `server/handlers/search.py` — +5 LOC (filters length validation)
- `tests/security/test_resource_exhaustion.py` — NEW, ~350 LOC (5 fault tests + helpers)
- `.claude/docs/security-threat-4-audit.md` — NEW, ~200 lines
- `tests/test_session_caps.py` (existing) — may need 1-2 test additions

**Total:** ~650 LOC across ~6 files. Over the 5-file decision-tree
threshold but the work is tightly coupled (session.py + middleware.py
+ test). Sequential implementation in the main thread is more
efficient than splitting across worktrees. **Path: INLINE.**

---

## Concrete implementation plan

### Step 1 — Extend `server/session.py` with hourly rate-limit tracking

```python
from collections import deque

#: Hourly window length in seconds.
HOURLY_WINDOW_SECONDS: int = 3600

#: Max tool calls per hour per session (any tool).
MAX_CALLS_PER_HOUR: int = 1000

@dataclass
class SessionState:
    ...
    #: Sliding window of timestamps for ALL tool calls in the last
    #: HOURLY_WINDOW_SECONDS. Used by check_hourly_rate_limit to
    #: enforce the 1000/hour cap. Bounded by the cap itself plus
    #: a small fudge — entries older than the window are pruned
    #: lazily on each access.
    call_timestamps: deque[float] = field(default_factory=deque)


async def check_hourly_rate_limit(
    state: SessionState, now: float | None = None
) -> tuple[bool, int, int]:
    """Atomically check the hourly rate limit and record the call.

    Returns (allowed, current_count, limit).
    - allowed=True: call is within cap; timestamp is recorded.
    - allowed=False: call would exceed cap; NOT recorded.
    """
    if now is None:
        now = time.time()
    async with state.lock:
        # Prune timestamps older than the window.
        cutoff = now - HOURLY_WINDOW_SECONDS
        while state.call_timestamps and state.call_timestamps[0] < cutoff:
            state.call_timestamps.popleft()

        current = len(state.call_timestamps)
        if current >= MAX_CALLS_PER_HOUR:
            return False, current + 1, MAX_CALLS_PER_HOUR

        state.call_timestamps.append(now)
        return True, current + 1, MAX_CALLS_PER_HOUR
```

### Step 2 — Wire into `SessionCapMiddleware`

In `server/middleware.py`, after the existing per-tool
`check_and_increment` call, ALSO call `check_hourly_rate_limit`.
If either returns `allowed=False`, short-circuit with the
appropriate structured error.

```python
# Existing per-tool cap check.
allowed, count, limit = await check_and_increment(state, tool_name)
if not allowed:
    # Return RETRIEVAL_CAP_REACHED (existing behavior)
    ...

# E13_S04: Hourly rate limit check — applies to ALL tools, not
# just the retrieval-tracked ones.
hourly_allowed, hourly_count, hourly_limit = await check_hourly_rate_limit(state)
if not hourly_allowed:
    # Return RATE_LIMIT_EXCEEDED
    payload = {
        "code": "RATE_LIMIT_EXCEEDED",
        "message": f"hourly rate limit reached: {hourly_count} calls in last hour (cap: {hourly_limit})",
        ...
    }
    ...
```

### Step 3 — `filters` length validation in `search_papers`

```python
#: Max number of items in the filters dict at v1.
#: Handler-body validation rather than Pydantic Field(max_length=)
#: to avoid TOOL_SCHEMA_VERSION re-pin per .claude/notes/07-multi-agent-caching.md.
MAX_FILTER_ITEMS = 100

async def handle_search_papers(
    query, level, k, filters, cursor,
):
    # E13_S04 Threat 4: handler-body cap on filters dict size.
    # Pydantic Field(max_length=) would change tool schema → BP1 invalidation.
    if filters is not None and len(filters) > MAX_FILTER_ITEMS:
        raise ValueError(
            f"filters has {len(filters)} items; max allowed is "
            f"{MAX_FILTER_ITEMS} (E13_S04 Threat 4 resource-exhaustion cap)"
        )
    ...
```

### Step 4 — `tests/security/test_resource_exhaustion.py` (5 fault tests)

- `TestNumericParamRejection`:
  - `test_search_papers_k_over_cap_rejected`
  - `test_find_equation_k_over_cap_rejected`
  - `test_find_lemma_by_name_k_over_cap_rejected`
  - `test_cite_neighbors_depth_over_cap_rejected` (reframed from `dependency_graph`)
  - `test_cite_neighbors_limit_over_cap_rejected`

- `TestFiltersCapEnforced`:
  - `test_filters_at_cap_accepted`
  - `test_filters_over_cap_rejected_with_value_error`

- `TestByteCapEnforces256KB`:
  - `test_get_chunk_oversized_body_emits_resource_link`
  - `test_byte_cap_truncates_body_text`
  - `test_byte_cap_signals_body_truncated_true`

- `TestHourlyRateLimit`:
  - `test_1000_calls_succeed_in_one_hour`
  - `test_1001st_call_fires_rate_limit`
  - `test_rate_limit_sliding_window_prunes_old_timestamps`
  - `test_rate_limit_keyed_per_session` (one session limited, another unaffected)
  - `test_rate_limit_code_is_rate_limit_exceeded`

### Step 5 — Audit doc `.claude/docs/security-threat-4-audit.md`

Per-parameter limit table:

| Tool | Param | Type | Cap | Mechanism |
|---|---|---|---|---|
| search_papers | k | int | 50 | Pydantic Field(le=50) |
| search_papers | query | str | 2000 chars | Pydantic Field(max_length=2000) |
| search_papers | filters | dict | 100 items | Handler-body ValueError (E13_S04) |
| find_equation | k | int | 50 | Pydantic Field(le=50) |
| find_equation | latex_or_mathml | str | 4000 chars | Pydantic Field(max_length=4000) |
| find_lemma_by_name | k | int | 50 | Pydantic Field(le=50) |
| find_lemma_by_name | name | str | 200 chars | Pydantic Field(max_length=200) |
| cite_neighbors | depth | int | 3 | Pydantic Field(le=3) |
| cite_neighbors | limit | int | 100 | Pydantic Field(le=100) |

Per-tool byte-cap coverage:
- ✅ get_chunk, get_definitions
- ⚠️ search_papers (bounded by k≤50 × snippet≤150 chars), find_equation, find_lemma_by_name, get_paper, cite_neighbors

Rate-limit design:
- 1000 calls/hour per `Mcp-Session-Id`, sliding window (deque of timestamps)
- Single-process limitation documented
- Returns `isError=True` with `code="RATE_LIMIT_EXCEEDED"`

---

## Acceptance criteria status (reframed from brief)

- [x] **AC1** — `pytest tests/security/test_resource_exhaustion.py`
  passes.
- [x] **AC2** — `search_papers(k=10000)` rejected by Pydantic at
  schema validation (handler body not entered). Reframed from
  "-32602" → "isError=True (mcp SDK wraps Pydantic ValidationError);
  handler body not entered" per E13_S01 §Drift 2.
- [x] **AC3** — `cite_neighbors(depth=100)` rejected (REFRAMED from
  fictional `dependency_graph` — `cite_neighbors.depth` has
  `Field(ge=1, le=3)`).
- [x] **AC4** — 10000-item filter dict rejected by handler-body
  `ValueError` (not Pydantic schema — avoids `TOOL_SCHEMA_VERSION`
  re-pin per `.claude/notes/07-multi-agent-caching.md`).
- [x] **AC5** — Synthetic 300 KB chunk body → response carries
  `resource_link`, inline content ≤ 256 KB. Already implemented
  in `enforce_byte_cap`; test exercises `get_chunk`.
- [x] **AC6** — Rate-limit test: 1001st call in 1 hour from one
  session returns `isError=True` with `code="RATE_LIMIT_EXCEEDED"`
  (REFRAMED from "-32005" — not a real spec code; uses project's
  structured-error convention same as `RETRIEVAL_CAP_REACHED`).

---

## Open questions for the implementer

**None blocking.** All open questions resolved by synthesis:

1. **`filters` cap value:** 100 items. Reasonable upper bound for
   v1 filter dicts (which today have at most ~5 known keys:
   `paper_id`, `categories`, `authors`, `year`, `cursor`).

2. **Hourly window type:** Sliding window (deque of timestamps,
   pruned on each access). Robust against burst-at-boundary
   attacks; same in-memory architecture as `SessionCapMiddleware`.

3. **Middleware placement:** Extend `SessionCapMiddleware` (don't
   add a parallel middleware). Both caps share the same body-parse
   and session-id-extraction code path; combining them avoids
   double-parsing the JSON-RPC body.

---

## External writes the implementation will require

**None — purely local.** All deliverables are local file changes
and local commits. `git push` at end is gated by Phase 4 user
authorization.

---

## Threat-coverage matrix snapshot

After E13_S04 ships:

| Threat | Status |
|---|---|
| 1. Path traversal via paper_id | ✅ E13_S01 |
| 2. Indirect prompt injection | ✅ E13_S02 |
| 3. LaTeXML sandbox hostile input (Phase 1) | ✅ E13_S03 |
| 4. Resource exhaustion | ✅ E13_S04 |
| 5–9 | ⏳ E13_S05 through E13_S09 |
