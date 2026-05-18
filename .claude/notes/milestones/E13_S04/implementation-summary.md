# Implementation Summary — E13_S04

**One-line summary:** Close Threat 4 — numeric caps audited, filters cap implemented, byte cap verified, hourly rate limiter implemented from scratch.
**Commit range:** ff1474f..HEAD (pending feat SHA)
**Branch:** main
**Date:** 2026-05-18

## What landed

Closes Threat 4 (resource exhaustion) from
`.claude/notes/08-security-observability-ops.md` § Threat 4.

Pre-milestone audit revealed (verified by both researchers):
- **`E07_S10`, `E06_S07`, `E06_S08` are fictional prerequisites** —
  same drift as E07_S12 (E13_S01), E07_S13 (E13_S02), E02_S02
  sandbox spec (E13_S03). This milestone is BOTH spec AND enforcement.
- **Existing `Field(le=...)` caps already enforce numeric over-cap**
  for `search_papers.k`, `find_equation.k`, `find_lemma_by_name.k`,
  `cite_neighbors.depth`, `cite_neighbors.limit`. No new code needed
  for ACs 2-3 (audit-only).
- **`search_papers.filters` had NO size cap.** 10,000-item dict
  accepted today.
- **The `enforce_byte_cap` helper exists** (`server/tools.py`) and is
  called by `get_chunk` + `get_definitions`. AC5 testable today.
- **No hourly rate limiter exists.** Existing `SessionCapMiddleware`
  enforces lifetime-of-session caps (3 search, 4 chunk) covering 2
  of 7 tools. The brief's "1000 calls/hour" never shipped.

## Files changed

| Path | Change | Synthesis ref |
|---|---|---|
| `server/session.py` | +60 LOC: `HOURLY_WINDOW_SECONDS`, `MAX_CALLS_PER_HOUR`, `SessionState.call_timestamps` deque, `check_hourly_rate_limit()` function. Sliding-window logic; rejected calls do NOT consume budget. | D1 (build path) |
| `server/middleware.py` | +75 LOC: extended `SessionCapMiddleware` to call `check_hourly_rate_limit` AFTER per-tool cap, on ALL tools (not just `TOOLS_WITH_CAPS`). New `_send_rate_limit_response` method + `_rate_limit_payload` helper with distinct `code="RATE_LIMIT_EXCEEDED"`. | D1 |
| `server/handlers/search.py` | +8 LOC: handler-body filters length check at top of `handle_search_papers`. New `MAX_FILTER_ITEMS = 100` constant. | D2 (handler-body validation) |
| `tests/security/test_resource_exhaustion.py` | NEW, ~350 LOC: 19 tests across 5 test classes — numeric param constraints (5), filters cap (3), byte cap (2), hourly rate limit (6), payload shape (3) | All ACs |
| `.claude/docs/security-threat-4-audit.md` | NEW operator-internal audit doc with per-parameter limit table, per-tool byte-cap coverage, hourly rate-limit design, reframe rationales | doc-placement reframe |

## Drift from brief (deliberate; pattern carried from E13_S01–S03)

1. **Doc placement.** Brief said `docs/security/threat-4-audit.md`.
   Per CLAUDE.md §1, `docs/` is operator-only. Landed at
   `.claude/docs/security-threat-4-audit.md`.

2. **Fictional prerequisites reframe.** Brief named `E07_S10`,
   `E06_S07`, `E06_S08` as dependencies. None exist — E07 stops at
   S04, E06 stops at S06. This milestone implements the
   "mitigations that were specified" from the design note, not from
   prior milestones (which never shipped).

3. **`dependency_graph` reframe.** Brief named
   `dependency_graph(depth=100)`. That tool does NOT exist. Reframed
   to `cite_neighbors(depth=100)` (which has `Field(ge=1, le=3)`
   already).

4. **`-32602` AC reframe.** Brief asserted JSON-RPC `-32602` for
   Pydantic over-cap rejection. From E13_S01 §Drift 2: the mcp
   Python SDK wraps `ValidationError` as `isError=True`, never as
   `-32602`. Tests assert the security GOAL (Pydantic constraint
   present → handler body not entered), not the wire-level code.

5. **`-32005` AC reframe.** Brief asserted `-32005` for rate-limit
   rejection. Verified two ways: (a) `mcp/types.py` does NOT define
   `-32005`; (b) the MCP 2025-06-18 spec defines server-error range
   `[-32000, -32099]` but no rate-limit code. Used
   `code="RATE_LIMIT_EXCEEDED"` in structured payload (mirrors
   E08_S04 `RETRIEVAL_CAP_REACHED` pattern).

6. **Filters cap via handler-body validation, not Pydantic
   `Field(max_length=...)`.** Synthesis D2. Pydantic constraint
   would change the rendered tool schema → `EXPECTED_TOOL_SCHEMA_SHA256`
   re-pin → BP1 prompt-cache invalidation per
   `.claude/notes/07-multi-agent-caching.md`. Handler-body is
   identical for security goal without the cache cost.

7. **Hourly rate limit BUILT, not just audited.** Synthesis D1.
   E13_S03 set the precedent (process-group kill discipline was
   built as a real defense improvement, not deferred). Same logic
   here: 5 of 7 tools have zero rate-limit defense today; the
   1000/hour cap closes that gap across all tools.

## Test count delta

* Pre-milestone (post-E13_S03 — ff1474f): 1982 passed, 9 skipped, 1 xfailed.
* Post-feat: 2001 passed (+19 net):
  - 5 in `TestNumericParamRejection` (k/depth/limit Pydantic constraints)
  - 3 in `TestFiltersCapEnforced` (at-cap, over-cap, 10000-item brief AC)
  - 2 in `TestByteCapEnforcement` (under-cap pass-through, over-cap truncation + resource_link)
  - 6 in `TestHourlyRateLimit` (constants, under-cap success, 1001st rejected, sliding window, per-session isolation, brief's 1500-call AC)
  - 3 in `TestRateLimitPayloadShape` (distinct codes, window_seconds present, shape parity with retrieval cap)
* `ruff check .` — clean.

## Acceptance criteria status (reframed from brief)

- [x] **AC1** — `pytest tests/security/test_resource_exhaustion.py` passes.
- [x] **AC2** — `search_papers(k=10000)` rejected by Pydantic
  `Field(le=50)` BEFORE handler body. Reframed from "-32602" to
  "constraint present + handler body not entered" per E13_S01 §Drift 2.
- [x] **AC3** — `cite_neighbors(depth=100)` rejected by Pydantic
  `Field(le=3)`. REFRAMED from fictional `dependency_graph` to the
  real depth-constrained tool.
- [x] **AC4** — 10,000-item filter dict rejected by handler-body
  `ValueError` BEFORE any resource lookup. New `MAX_FILTER_ITEMS=100`
  constant.
- [x] **AC5** — Synthetic 300 KB chunk body → `enforce_byte_cap`
  truncates to 1024 chars, sets `body_truncated=True`, emits
  `resource_link` content block.
- [x] **AC6** — Rate-limit test: 1001st call in 1 hour from one
  session returns `isError=True` with `code="RATE_LIMIT_EXCEEDED"`.
  REFRAMED from "-32005" to project convention (not in MCP spec).

## What this milestone does NOT cover

- **Multi-worker rate limit coordination.** The deque is in-memory
  per process. arXMCP runs single-worker by convention (`--workers 1`)
  but multi-worker deployments would need Redis-backed shared state.
  Deferred to E14 when multi-worker becomes a real config.
- **Per-minute rate limit.** Design note mentions "60/minute, 1000/hour".
  Only the 1000/hour cap is implemented at v1. The 60/minute would
  add an additional deque with shorter window — straightforward
  extension when needed.
- **`enforce_byte_cap` wiring on the 5 tools that don't currently
  call it.** Those tools' v1 response sizes are bounded by other
  constraints (`search_papers` by k×snippet, `find_equation` by
  result-row shape, etc.). When E10/E11 wires body content into
  those tools, each call site should add `enforce_byte_cap`.
- **Threats 5–9.** Each is its own milestone.

## External writes the orchestrator must authorize

**None — purely local.** Standard Phase 4 user-authorization for
`git push origin main` at end.

## Threat-coverage matrix snapshot

After E13_S04:

| Threat | Status |
|---|---|
| 1. Path traversal via paper_id | ✅ E13_S01 |
| 2. Indirect prompt injection | ✅ E13_S02 |
| 3. LaTeXML sandbox hostile input (Phase 1) | ✅ E13_S03 |
| 4. Resource exhaustion | ✅ E13_S04 |
| 5. Origin spoofing / DNS rebinding | ⏳ E13_S05 (partial — Origin/Host in E06_S05) |
| 6. Model SHA pinning / safetensors | ⏳ E13_S06 (partial — BGE-M3 SHA pinned) |
| 7. Source ingestion TLS | ⏳ E13_S07 |
| 8. Log redaction | ⏳ E13_S08 |
| 9. Localhost binding regression test | ⏳ E13_S09 |
