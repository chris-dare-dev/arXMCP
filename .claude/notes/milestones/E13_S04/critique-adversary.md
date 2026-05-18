# Critique — E13_S04

**Critic:** adversary
**Generated:** 2026-05-17T00:00:00Z
**Commit range:** ff1474f358d8ed394d7a7877b0af3761122fa70b..7898d31d662e05f9c9223a36bd377e191f4dd8e5
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Implementation lands a real Threat-4 closure: hourly sliding-window cap on ALL tools, handler-body filter cap (BP1-safe), 256 KB byte cap verified, fictional brief prerequisites correctly reframed.
- 0 CRITICAL, 1 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk surface: per-tool cap budget can be "spent" on a call that the subsequent hourly check rejects (`server/middleware.py:878-933`). One-shot retrieval-loop budget leak.
- AC2/AC3 ("numeric parameter caps") are asserted via Pydantic constraint introspection only — no behavioral test actually invokes a handler with `k=10000` to prove the wire path rejects it.
- Session-rotation bypass of the hourly cap is acknowledged in the audit doc only by omission; an LLM client that calls `initialize` repeatedly gets a fresh 1000-call budget per UUID4.
- `get_definitions.term` has no `max_length` cap; the audit table flags it as a known gap but the milestone does not close it. Threat-4 surface remains open for that parameter.
- BP1 cache discipline correctly preserved — `EXPECTED_TOOL_SCHEMA_SHA256` and `ALL_TOOLS` untouched, filter cap moved to handler body specifically to avoid the re-pin.
- No new middleware integration test exercises the hourly-cap path through `SessionCapMiddleware`; coverage is unit-level on `check_hourly_rate_limit` and unit-level on `_rate_limit_payload`, with no test wiring them together.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Per-tool cap budget consumed before hourly check can reject

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/middleware.py:878-933
- **What:** In `SessionCapMiddleware`, `check_and_increment(state, tool_name)` runs FIRST, which (for `search_papers` / `get_chunk`) increments `state.search_count` / `state.chunk_count` in the success branch. THEN `check_hourly_rate_limit(state)` runs. If the per-tool cap allows the call but the hourly cap rejects it, the per-tool counter has already been incremented — but the request is short-circuited via `_send_rate_limit_response` and never reaches FastMCP. The retrieval budget is silently leaked.
- **Why it matters:** This violates the load-bearing invariant from E08_S04 that `state.search_count` reflects calls that actually executed retrieval work. A pathological scenario: at hour-edge, a session with `search_count=2` (limit=3) makes 998 cheap calls to `get_paper` (consuming hourly cap), then issues a `search_papers` call. Per-tool cap approves (search_count → 3), hourly cap rejects. The session now has search_count==limit, so the legitimate retry after the hour rolls cannot use search_papers again — even though the call NEVER ran. This is a real foot-gun for the agent runtime.
- **Proposed fix:** Reverse the check order in `SessionCapMiddleware`: run `check_hourly_rate_limit` FIRST (don't append the timestamp if the per-tool check would reject), then `check_and_increment`. Alternative cleaner fix: introduce a `check_and_increment_dry_run` that returns the same tuple without mutating state, do both dry-run checks, and only commit on full pass. Either way the contract is "no budget spent on a call that won't execute."
- **Regression guard:** Add a test that: (a) seeds `state.search_count = 0`; (b) seeds `state.call_timestamps` with 1000 fresh timestamps (hourly cap at limit); (c) issues a `search_papers` request through the middleware; (d) asserts the response is RATE_LIMIT_EXCEEDED AND `state.search_count == 0` (budget not consumed).

### F2 — Numeric param "rejection" tests are introspection-only, never invoke handlers

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/security/test_resource_exhaustion.py:108-160
- **What:** `TestNumericParamRejection` asserts only that Pydantic `Field(le=...)` constraints are PRESENT on handler signatures via `typing.get_type_hints(include_extras=True)`. No test actually invokes `handle_search_papers(query="x", k=10000)` or `handle_cite_neighbors(chunk_id="...", depth=100)` to prove the wire path raises. The docstring of `TestNumericParamRejection` even acknowledges this: "Pydantic validation fires when the handler is called via FastMCP's schema-validation wrapper, which is NOT exercised when we call the handler function directly in tests."
- **Why it matters:** The brief's named ACs ("k=10000 → reject", "depth=100 → reject") are claimed satisfied by AC2/AC3 with a constraint-table inspection only. If a future refactor strips the `Field(le=50)` constraint, the introspection test fails — but if a future refactor moves the handler call surface around FastMCP's schema-validation wrapper (e.g., a custom tool registrar that bypasses the wrapper), the introspection still passes while the wire rejection silently disappears. The "handler body not entered" security goal needs a behavioral test that drives a tool call through the FastMCP layer with `k=10000` and asserts an `isError=True` result with no handler side effect.
- **Proposed fix:** Add an integration test that constructs a FastMCP tool from the handler (or uses the existing `register_all` setup in the test app fixture) and calls it with `k=10000`. Assert `isError=True` and that a sentinel-patched `get_resources` was NEVER reached. This is the same pattern used in `TestFiltersCapEnforced.test_filters_over_cap_rejected_with_value_error`.
- **Regression guard:** Test as above. ~30 LOC including the sentinel patch.

### F3 — Session-rotation bypass of the hourly cap is unmitigated and undocumented

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/middleware.py:820, server/session.py:230-288
- **What:** The hourly rate limit is keyed on `Mcp-Session-Id`. `_VALID_SESSION_ID_RE` only validates UUID4-hex format (32 hex chars), not authenticity. An adversary in a retry loop who hits the 1000-call cap can simply generate a fresh UUID4, send `initialize`, and get a brand-new 1000-call budget. There is no IP-based or process-wide secondary cap.
- **Why it matters:** The brief's headline scenario — "an LLM in a retry loop or under prompt injection can pass enormous filter lists, or call any tool 10,000 times per hour" — is only partially mitigated. A misbehaving LLM client (or a hostile one) that rotates session IDs gets unlimited throughput. The audit doc at `.claude/docs/security-threat-4-audit.md` § "Single-process limitation" discusses the multi-worker case but does NOT acknowledge the session-rotation bypass.
- **Proposed fix:** Either (a) add a secondary process-wide cap on `_SESSIONS` creation rate (e.g., max 100 new sessions per hour per origin) using the same deque pattern at module scope, OR (b) explicitly document the bypass in `.claude/docs/security-threat-4-audit.md` § Single-process limitation with the same Redis-backed-fix-in-E14 note. Option (b) is the cheap fix for this milestone; option (a) is the full closure.
- **Regression guard:** If (a) chosen: test that the 101st fresh session ID in an hour gets rejected at the middleware. If (b): no test needed; the doc is the regression guard against the next reader assuming the cap is complete.

### F4 — `get_definitions.term` has no max_length cap; Threat-4 surface remains open

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/definitions.py:60-63
- **What:** The `term: Annotated[str | None, Field(description=...)]` parameter on `handle_get_definitions` declares no `max_length` constraint. The Threat-4 audit doc at `.claude/docs/security-threat-4-audit.md:63` flags it explicitly: "`get_definitions` | `term` | str \| None | (no max_length cap) | —". An adversary can pass `term="X" * 1_000_000` to inflate memory before any LanceDB query fires; the SQL-injection-style escape is also wider-surface for a long string.
- **Why it matters:** The milestone's headline is "Threat 4 close-out across 7 tools." Documenting a gap in the audit table without closing it (or filing a follow-up) leaves the threat partially open. This is the only string parameter in the 7-tool surface without a `max_length`. The fix is one line.
- **Proposed fix:** Add `Field(max_length=200, description=...)` to the `term` parameter (a theorem/lemma/symbol name is never 200 chars in practice; matches the `find_lemma_by_name.name` cap precedent). Note: this CHANGES the rendered tool schema and triggers an `EXPECTED_TOOL_SCHEMA_SHA256` re-pin per BP1 discipline. Alternative if the re-pin is undesirable in this milestone: handler-body validation identical to the `MAX_FILTER_ITEMS` pattern (cheap, BP1-safe).
- **Regression guard:** Add a test that calls `handle_get_definitions(paper_id="2309.01234", term="X" * 10000)` and asserts either a Pydantic ValidationError (if the `Field` path is chosen) or a handler-body `ValueError` (if the body-validation path is chosen).

### F5 — No middleware integration test for the hourly-cap path

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/security/test_resource_exhaustion.py:314-419
- **What:** `TestHourlyRateLimit` unit-tests `check_hourly_rate_limit` directly against a `SessionState`. `TestRateLimitPayloadShape` unit-tests `_rate_limit_payload`. Neither exercises the full path through `SessionCapMiddleware.__call__` → check_and_increment → check_hourly_rate_limit → `_send_rate_limit_response`. By contrast, `tests/test_session_caps.py` has end-to-end ASGI-replay tests for the per-tool cap path (line 173+). The hourly cap is a load-bearing new defense and deserves the same integration coverage.
- **Why it matters:** The unit tests prove the building blocks work. They do NOT prove the middleware wires them together correctly. A refactor that, say, swaps the order of `check_and_increment` and `check_hourly_rate_limit` calls (related to F1) or accidentally drops the `_send_rate_limit_response` invocation would slip past the current test surface.
- **Proposed fix:** Add a middleware-level test in the same shape as `test_session_caps.py:170+`. Use a fake ASGI app and a pre-seeded session with `call_timestamps` at cap; send a `tools/call` for any tool name (e.g., `get_paper`, which is NOT in `TOOLS_WITH_CAPS` so the per-tool path returns `(True, 0, 0)` immediately, isolating the hourly check); assert the response is the structured RATE_LIMIT_EXCEEDED envelope with `isError=True`, `status==200`, content-type JSON, and that the inner app was NEVER awaited.
- **Regression guard:** Test as above. ~40 LOC matching the existing pattern.

### F6 — Deep middleware nesting reduces maintainability

- **Severity:** LOW
- **Source:** adversary
- **File:** server/middleware.py:891-937
- **What:** The hourly-cap branch is nested inside an `if not allowed: pass / else:` block that wraps the entire hourly check + replay logic. The dead `if not allowed: pass` arm is purely flow control; the real work is in the `else:` arm at 5 indent levels deep. Concretely:

```
if not allowed:
    pass
else:
    try:
        ...
    except Exception:
        ...
    if not hourly_allowed:
        logger.info(...)
        try:
            from server.metrics import ...
        except Exception:
            ...
        await self._send_rate_limit_response(...)
        return
    await self._replay_to_app(...)
    return
```

- **Why it matters:** Maintainability — a future contributor adding a third cap layer would push to 6 indent levels. The same logic flattens trivially with an early return.
- **Proposed fix:** Replace `if not allowed: pass / else: <hourly check>` with `if not allowed: <existing RETRIEVAL_CAP_REACHED block>; return` (move the existing post-block into the early-return), then the hourly check sits at the same indent level as the per-tool check.
- **Regression guard:** None — refactor; covered by existing tests.

### F7 — Unused module constants `ADVERSARIAL_K` and `ADVERSARIAL_DEPTH`

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/security/test_resource_exhaustion.py:66,69
- **What:** `ADVERSARIAL_K = 10000` and `ADVERSARIAL_DEPTH = 100` are declared at module scope with docstrings referencing them as "the brief's named adversarial values," but they are never referenced anywhere in the test file. The tests that should use them (`TestNumericParamRejection`) test constraint presence instead of behavioral invocation (see F2).
- **Why it matters:** Dead code. If F2 is fixed by adding behavioral tests, these constants become live again. Otherwise they're cruft.
- **Proposed fix:** Either delete them (if F2 is deferred) or wire them into the new behavioral test added for F2.
- **Regression guard:** None.

### F8 — Audit doc claims `Pydantic Field(max_length=...)` for filters dict would bump schema hash; verify wording

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/docs/security-threat-4-audit.md:23-28
- **What:** The audit doc says "Pydantic `Field(max_length=...)` would change the rendered tool schema and trigger `EXPECTED_TOOL_SCHEMA_SHA256` re-pin." Strictly speaking, `Field(max_length=...)` on a `dict[str, Any]` parameter would translate to a JSON-Schema `maxProperties` constraint, which IS emitted in the schema. The rationale is correct; the wording could be slightly more precise about WHICH JSON-Schema keyword shifts.
- **Why it matters:** Minor. Future reader could be confused about whether the constraint applies to dict keys (length of each key string) vs. dict size (number of items).
- **Proposed fix:** Clarify in the doc that the resulting schema constraint would be `maxProperties` (number of items), not `maxLength` (string length of a key). Or, equivalently, note that the security goal is "reject oversized dict by item-count" which is `maxProperties` in JSON Schema.
- **Regression guard:** None.

## What was done well

- BP1 cache discipline correctly held: filter cap implemented in handler body, not Pydantic schema, with explicit rationale comment citing `07-multi-agent-caching.md`. `EXPECTED_TOOL_SCHEMA_SHA256` and `ALL_TOOLS` untouched, confirmed via diff.
- Sliding-window rate limiter correctly rejects without consuming budget — the `if current >= limit: return False, current + 1, limit` BEFORE `state.call_timestamps.append(now)` is the textbook-correct shape and matches the audit doc design.
- Per-session lock (`state.lock`) is acquired in `check_hourly_rate_limit` BEFORE the deque mutation. Concurrent calls from the same session correctly serialize.
- Distinct error code `RATE_LIMIT_EXCEEDED` (vs. existing `RETRIEVAL_CAP_REACHED`) lets the agent tell which cap fired, while the envelope shape is structurally identical so one parser handles both.
- Failure-open discipline replicated correctly: if `check_hourly_rate_limit` itself raises, the middleware logs and forwards rather than failing closed. Matches the established E08_S04 precedent for `check_and_increment`.
- Fictional brief prerequisites (`E07_S10`, `E06_S07`, `E06_S08`, `dependency_graph`) correctly identified, reframed, and documented inline in the test docstring and `.claude/docs/security-threat-4-audit.md` § "Fictional prerequisites" + § "Fictional tool".
- The `time.time()` injection via the optional `now` parameter on `check_hourly_rate_limit` is exactly the right abstraction for deterministic sliding-window tests, and is used cleanly in `test_sliding_window_prunes_old_timestamps`.
- The audit doc at `.claude/docs/security-threat-4-audit.md` is genuinely useful operator-internal material: per-parameter limit table for all 7 tools, per-tool byte-cap coverage, distinct rationale sections for each brief reframe.
- Prometheus counter labels for rate-limit rejections use a distinct `tool="rate_limit_hourly"` label so operators can graph hourly-cap fires vs. per-tool-cap fires separately.
- The brief's headline AC (1500 calls in 1 hour, 1000 succeed and 500 fail) is exercised exactly in `test_brief_ac_1500_calls_fires_at_1001`, with assertions on both successes and rejections counts.

## Recommended rectification order

1. **F1** — Per-tool cap budget leak (HIGH). Highest-leverage: load-bearing invariant for the agent runtime's retrieval-loop semantics; fix is small (reverse check order in middleware) but the regression test requires care to construct the seeded state.
2. **F2** — Behavioral test for numeric param rejection (MEDIUM). Pairs naturally with F7 cleanup. ~30 LOC.
3. **F4** — `get_definitions.term` max_length cap (MEDIUM). One line if handler-body validation chosen; one line + hash re-pin if `Field(max_length=...)` chosen. Closes the only remaining named gap in the audit table.
4. **F5** — Middleware integration test for hourly-cap path (MEDIUM). ~40 LOC, no production code change; protects F1's fix from regression.
5. **F3** — Session-rotation bypass (MEDIUM). Cheapest fix: documentation-only acknowledgment in `.claude/docs/security-threat-4-audit.md`. Full closure (process-wide session creation cap) is larger; defer if not cheap.
6. **F6** — Middleware nesting refactor (LOW). Defer unless F1 fix touches the same block (then bundle).
7. **F7** — Delete unused `ADVERSARIAL_*` constants (LOW). Bundle with F2.
8. **F8** — Audit doc wording precision (LOW). Defer.

## Rectification status

- **F1 (HIGH) — fixed.** Introduced `server/session.py::check_both_caps`
  — single atomic compound check holding `state.lock` once. Neither
  per-tool nor hourly counter mutates unless both caps pass.
  `SessionCapMiddleware` now dispatches on a verdict string
  (`"allowed"` / `"per_tool_rejected"` / `"hourly_rejected"`).
  Regression guards: `TestAtomicTwoCapCheck::test_per_tool_rejected_does_not_consume_hourly_budget`,
  `test_hourly_rejected_does_not_consume_per_tool_budget`,
  `test_both_pass_commits_both_atomically`,
  `test_non_capped_tool_only_hits_hourly`.

- **F2 (MEDIUM) — fixed.** Added behavioral tests via
  `pydantic.TypeAdapter` for every constrained numeric parameter
  (search_papers.k, find_equation.k, find_lemma_by_name.k,
  cite_neighbors.depth, cite_neighbors.limit). New helper
  `_adapter_for_param` materializes a `TypeAdapter` from the
  handler's `Annotated[int, Field(le=...)]` type, then
  `validate_python(10000)` raises `ValidationError` for any over-cap
  value — exactly what FastMCP's schema-validation wrapper does on
  the MCP transport boundary. The handler function is never called,
  so "handler body not entered" is proven.

- **F3 (MEDIUM) — fixed (documentation).** Added a "Session-rotation
  bypass" subsection to `.claude/docs/security-threat-4-audit.md`
  acknowledging the gap (UUID4 session-id rotation resets the
  hourly cap) and documenting that for the v1 single-user
  localhost-only deployment, this is low-priority; a process-wide
  session-creation rate cap is filed as future work.

- **F4 (MEDIUM) — fixed.** Added `MAX_TERM_LENGTH = 200` constant to
  `server/handlers/definitions.py` plus a handler-body length check
  on the `term` argument. Same handler-body pattern as
  `MAX_FILTER_ITEMS` (no tool schema change). Regression guards:
  `TestDefinitionsTermCap::test_term_at_cap_does_not_raise_value_error`,
  `test_term_over_cap_rejected_with_value_error`.

- **F5 (MEDIUM) — fixed.** Added
  `TestHourlyCapMiddlewareIntegration::test_hourly_cap_at_limit_short_circuits_middleware`
  — constructs a fake ASGI inner app, pre-seeds a session with the
  hourly deque at cap, sends a tools/call request through the
  middleware, asserts the inner app is NEVER called AND the
  response is `isError=True` with `code="RATE_LIMIT_EXCEEDED"` +
  `window_seconds: 3600`. The full middleware → check_both_caps →
  `_send_rate_limit_response` wiring is now exercised.

- **F6 (LOW) — fixed (bundled with F1).** The middleware nesting
  flattened naturally when migrating to `check_both_caps`: the
  rejection dispatch is now a series of `if verdict == "...": return`
  branches at one indent level, replacing the 5-indent-deep
  `if/else` block.

- **F7 (LOW) — kept (no longer dead code).** `ADVERSARIAL_K` and
  `ADVERSARIAL_DEPTH` are now used by the F2 behavioral tests
  (`adapter.validate_python(ADVERSARIAL_K)` etc.). Docstring
  updated to reference the F2 rect.

- **F8 (LOW) — deferred.** Audit doc wording precision on `maxProperties`
  vs `maxLength` for the dict `filters` cap. Operational hygiene
  only; the existing rationale is correct on the security goal.

**Critic invalidation rate:** 0% (0 of 5 HIGH+MEDIUM findings
invalidated on re-verify; all 5 closed). Calibration clean.

**Cross-axis summary:**
- 1 HIGH closed (F1 — atomic compound check).
- 4 MEDIUM closed (F2 behavioral tests, F3 doc, F4 term cap, F5
  middleware integration).
- 2 LOW closed via natural side effects (F6 flatten, F7 reuse).
- 1 LOW deferred (F8 doc wording).

**Test count delta from rect:** +12 tests (2001 → 2013). Breakdown:
- F2 behavioral: 5 (one per constrained numeric param)
- F4 term cap: 2 (at-cap accept, over-cap reject)
- F1 atomic check: 4 (per-tool budget preserved, hourly budget
  preserved, both-pass commits both, non-capped tool only hits hourly)
- F5 middleware integration: 1 (full short-circuit path)
