# Critique — E13_S04b

**Critic:** adversary
**Generated:** 2026-05-20T22:04:00Z
**Commit range:** 601cb91289d1f483faf3c6a27ddeaa8c0e538650..874db28b96f1f15164619961971bf07d12716068
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- **CRITICAL: The cap "fires" but doesn't truncate for 4 of 5 newly-covered tools** — `search_papers`, `find_equation`, `find_lemma_by_name`, and `get_paper` all call `enforce_byte_cap()` with no arguments, defaulting to `body_text_path=("body_text",)`. Their response payloads have no top-level `body_text` key, so `_truncate_at_path()` silently no-ops (returns without truncating). The `body_truncated=True` flag IS set, but the payload size is NOT reduced. This violates Threat 4 mitigation ("hard byte cap on tool result inline content"). Only `cite_neighbors` has the correct semantics (though it's a v1 stub).
- **Finding count:** 1 CRITICAL, 0 HIGH, 1 MEDIUM, 0 LOW
- **Highest-risk location:** `server/handlers/search.py:341` and parallel `_cap()` implementations in `equation.py`, `lemma.py`, `paper.py`
- **The fix is straightforward:** each handler's `_cap()` must pass the correct `body_text_path` that matches its actual response structure, OR accept that multi-result tools have no single body to truncate and use a different truncation strategy (e.g., limit results list instead of truncating a body field).
- **Cache byte-stability:** Axis 1 passes; the cap helper is called AFTER the cache store, and the cache lookup key is NOT affected by the truncated body.
- **No schema change:** `EXPECTED_TOOL_SCHEMA_SHA256` remains stable; BP1 byte-stability unbroken.
- **Tests exist but have a blind spot:** tests only verify `body_truncated=True` is set, not that the payload was actually reduced.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Truncation silently no-ops for multi-result tools; `body_truncated` flag set without payload size reduction

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** `server/tools.py:470-481` (the `_truncate_at_path` helper); also `server/handlers/search.py:341`, `server/handlers/equation.py:41`, `server/handlers/lemma.py:62`, `server/handlers/paper.py:32`
- **What:** The `_truncate_at_path` helper returns silently when the requested path doesn't exist in the dict. Four newly-covered handlers (`search_papers`, `find_equation`, `find_lemma_by_name`, `get_paper`) call `enforce_byte_cap(payload)` with no arguments, defaulting to `body_text_path=("body_text",)`. Their response payloads have no top-level `body_text` key — so the truncation never happens. Meanwhile, `body_truncated=True` IS set (line 457 in `tools.py`), and `_sort_dict()` IS applied, so the response looks like it was capped — but the actual payload bytes are unchanged. A 500 KB response marked with `body_truncated=True` still leaves 500 KB on the wire.
- **Why it matters:** Threat 4 in `08-security-observability-ops.md` specifies "hard byte cap on tool result inline content (256 KB; spillover via `resource_link`)." A cap that marks truncation without reducing size is not a hard cap; it's a misleading flag. An adversarial or malfunctioning agent that receives a 500 KB response with `body_truncated=True` has no signal about which part of the aggregate was elided. The threat mitigation is broken: the 256 KB hard limit does not hold for any of the 4 multi-result tools at their common paths (when they do return results).
- **Proposed fix:** Each multi-result tool's `_cap()` must pass the correct `body_text_path` for the field it actually returns, OR accept that there is no single "body" to truncate and instead limit the result list itself. Two options:
  1. **Per-tool truncation paths (surgical):** Pass the path to the actual body/content field if one exists. For `search_papers`, `results[*].snippet` is not truncated further (it's already capped at 150 chars); the payload growth comes from adding more rows. For `find_equation` and `find_lemma_by_name`, same — the rows are small. For `get_paper`, when metadata lands in E11/E12, the abstract or authors field would be the truncation target. This option requires identifying the actual over-cap culprit per tool.
  2. **Aggregate result-list limiting (simpler):** For multi-result tools, when the cap fires, limit the `results[]` / `matches[]` list instead of truncating a body field. Return fewer rows rather than truncated rows. E.g.: `search_papers` over cap → return 20 results instead of 50, set `body_truncated=True`, no resource_link (the per-row chunk_ids are still available). This is semantically clearer: "the response was over cap, so we're returning fewer results" rather than "your payload was truncated but we won't tell you where."
  3. **Hybrid:** For `cite_neighbors` (which passes `chunk_id=chunk_id`), the resource_link IS meaningful and the current code is correct — keep that as-is. For the 4 multi-result tools, apply option 2 (result-list limiting).
  
  Recommend **option 3 (hybrid)** for Phase 4 rectification:
  - `cite_neighbors`: no change (already correct).
  - `search_papers`, `find_equation`, `find_lemma_by_name`, `get_paper`: modify each `_cap()` to not rely on `_truncate_at_path`'s missing-path no-op. Instead, check whether the payload size exceeds the cap, and if it does, truncate the result list to a smaller `k` until it fits, then set `body_truncated=True`. The truncation point is deterministic per tool.
- **Regression guard:** Add a test case for each of the 4 multi-result tools that constructs an over-cap payload and asserts NOT ONLY that `body_truncated=True`, but also that the serialized JSON byte length is actually ≤ 256 KB when the cap fires. E.g.: `assert len(json.dumps(out, sort_keys=True).encode("utf-8")) * 2 <= 262144` (applying the 2× wire-overhead factor). The existing tests in `test_resource_exhaustion.py::TestE13S04bCapExtension::test_multi_result_cap_fires_on_over_cap` only check the flag, not the size.

---

### F2 — Test gap: size assertion missing for over-cap path

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/security/test_resource_exhaustion.py:869-906` (the `test_multi_result_cap_fires_on_over_cap` parametrized test)
- **What:** The test constructs a 200 KB filler string and asserts that `body_truncated=True` is set in the response. However, it does NOT assert that the payload size was actually reduced. A payload that is 400 KB (200 KB × 2 for wire overhead) would still trip the cap condition (line 450 in `tools.py`), set the flag, but fail to truncate because the target path doesn't exist. The test passes with flying colors.
- **Why it matters:** The test should be the first line of defense against F1. By not asserting the actual size, it lets a broken cap implementation pass. This is a leading indicator that the threat mitigation is incomplete.
- **Proposed fix:** After calling `module._cap()`, add an assertion that the serialized size of the result is ≤ `cap_bytes`:
  ```python
  serialized_size = len(json.dumps(out, sort_keys=True).encode("utf-8")) * 2
  assert serialized_size <= cap_bytes, (
      f"over-cap payload was NOT reduced: {serialized_size} > {cap_bytes}"
  )
  ```
  Apply this to all four multi-result tool tests (and the `cite_neighbors` tests for completeness, though they are also currently stubs).
- **Regression guard:** This assertion should be added to the existing test parametrization, not as a separate test. Update lines 869–906 to add the size check after the `body_truncated` flag check.

---

## What was done well

- **Correct identification of the gap:** The implementation correctly identified that 5 tools were missing the cap call and extended it to all of them. The orchestrator's synthesis of the two research briefs was clear and the division of labor (multi-result tools pass `chunk_id=None`, `cite_neighbors` passes input `chunk_id`) makes semantic sense.
- **No schema mutation:** The implementation correctly avoided adding Pydantic `Field` constraints that would re-pin `EXPECTED_TOOL_SCHEMA_SHA256`. The cap is enforced in handler body, preserving BP1 byte-stability. This is the right design discipline.
- **Clear docstrings:** Every new `_cap()` helper includes a docstring explaining when it's a no-op, why it exists (forward-compat), and the semantics of the `chunk_id` argument. This is excellent documentation and will help future maintainers understand the intent.
- **Static import check:** The test includes a parametrized check (`test_handler_module_imports_enforce_byte_cap`) that catches refactoring regressions where someone drops the import. This is a solid defensive pattern.
- **Defensive forward-compat:** The milestone correctly recognizes that `get_paper` and `cite_neighbors` are v1 stubs where the cap is a no-op today, but the call is added now so future E11/E12/E09 implementations don't have to remember to add it. This is good forward-planning.
- **Correct cite_neighbors semantics:** The `cite_neighbors._cap()` correctly passes the input `chunk_id` because the parent chunk's neighborhood is the meaningful resource-link target. That implementation is correct.
- **Doc updates accurate:** The security-threat-4-audit.md and security-threat-model-coverage.md edits accurately mark the gap as closed (pending Phase 4 GitHub issue close). The per-tool coverage table is updated correctly.
- **15 new tests:** The test class adds appropriate parametrization and coverage for both under-cap and over-cap paths, even if the over-cap assertion is incomplete. The test structure mirrors the E13_S04 pattern, which is good consistency.
- **All three cache-store paths covered for search_papers:** The implementation correctly identified and patched all three return sites for `search_papers` (Tier-1 hit, Tier-2 hit, miss/compute), not just the miss path. This is thorough.
- **Lemma handler 5 return sites handled:** The `lemma.py` implementation wraps all 5 return sites (4 in FTS5 dispatcher + 1 fallback), not just the fast path. This shows attention to detail.

## Recommended rectification order

1. **F1 (CRITICAL) — Fix the multi-result tool truncation logic.** This is the load-bearing finding. For each of `search_papers`, `find_equation`, `find_lemma_by_name`, and `get_paper`, replace the naive `enforce_byte_cap(payload)` call with custom logic that truncates the result list instead of relying on the missing-path no-op. Estimated ~50–80 LOC per tool (simple loop + size check). High impact; unblocks the cap enforcement.
2. **F2 (MEDIUM) — Add size assertions to existing over-cap tests.** Once F1 is fixed, update the test parametrization in `test_multi_result_cap_fires_on_over_cap` to assert the payload was actually reduced. Estimated ~10 LOC (one assertion per test variant). Low effort; high confidence gain.

---

## Rectification status (filled by Phase 4)

- **F1 (CRITICAL) — FIXED.** Added new helper
  `server.tools.cap_result_list(payload, list_key, chunk_id=None)` that
  iteratively pops trailing rows from `payload[list_key]` until the
  serialized wire size fits under cap. Updated four multi-result
  handlers to use it: `search.py` (`list_key="results"`), `equation.py`
  (`list_key="results"`), `lemma.py` (`list_key="matches"`),
  `citations.py` (`list_key="neighbors"` + input `chunk_id`).
  Updated `paper.py::_cap` to use
  `enforce_byte_cap(payload, body_text_path=("paper", "abstract"))` —
  the abstract is the field most likely to exceed cap in the E11/E12
  metadata schema, and truncating-in-place is correct for a single-row
  envelope. Direct runtime verification confirms the cap actually
  reduces payload size now (e.g. search: 409,788 → 108 bytes;
  paper: 409,764 → 2,260 bytes after abstract truncation to 1024 chars).
- **F2 (MEDIUM) — FIXED.** Updated
  `test_multi_result_cap_fires_on_over_cap` to add the explicit size
  assertion `post_cap_wire_bytes <= cap_bytes` after the
  `body_truncated=True` check. Added the same size assertion to the
  `cite_neighbors` over-cap test. Added a new
  `test_multi_result_cap_trims_trailing_rows` regression guard that
  constructs a 50-row × 10-KB payload and asserts (a) the cap fires,
  (b) the post-cap size is under cap, (c) at least one row survives,
  (d) the survivors are a prefix of the input (tail-truncation
  preserves rank order). Static-import test updated to accept either
  `enforce_byte_cap` or `cap_result_list` as a valid byte-cap entry
  point. Tests in `TestE13S04bCapExtension`: 15 → 18 (+3).
