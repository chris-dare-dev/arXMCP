# Implementation summary — E13_S04b

**Milestone:** E13_S04b — Extend 256 KB byte cap to remaining tool handlers
**Implementation base SHA:** `601cb91289d1f483faf3c6a27ddeaa8c0e538650`
**Path:** inline (orchestrator implemented directly in main session)

## One-line summary

Closed Threat 4 partial-coverage gap G1 (GitHub issue #1) by extending
`server.tools.enforce_byte_cap` enforcement to the 5 previously-unenforced
handlers (`search_papers`, `find_equation`, `find_lemma_by_name`,
`get_paper`, `cite_neighbors`) via a per-module `_cap()` helper mirroring
the `definitions.py` precedent. No production-code refactor; no schema
change; no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin.

## Files changed

| File | Change | Why |
|---|---|---|
| `server/handlers/search.py` | MODIFIED | Add `_cap()` helper; call before each of 3 `_build_content_blocks` invocations (Tier-1 hit, Tier-2 hit, miss/compute paths); update module docstring to reflect the cap now enforced |
| `server/handlers/equation.py` | MODIFIED | Add `_cap()` helper; wrap each `return envelope({...})` as `return envelope(_cap({...}))` (2 sites) |
| `server/handlers/lemma.py` | MODIFIED | Same pattern; 5 return sites wrapped |
| `server/handlers/paper.py` | MODIFIED | Same pattern; 2 return sites wrapped (found/not-found) |
| `server/handlers/citations.py` | MODIFIED | Same pattern; 1 return site wrapped; `_cap()` takes `chunk_id` argument (passes through to `enforce_byte_cap`) so the resource_link points to the parent context whose neighborhood was returned |
| `tests/security/test_resource_exhaustion.py` | MODIFIED | New `TestE13S04bCapExtension` class with 15 tests: under-cap pass-through parametrized over 4 multi-result tools; over-cap firing parametrized over the same 4; cite_neighbors under-cap + over-cap (separate because of `chunk_id` arg); static import check parametrized over all 5 modules |
| `.claude/docs/security-threat-4-audit.md` | MODIFIED | Per-tool byte-cap coverage table updated: all 7 tools now ✅ with E13_S04b attribution; future-handler discipline paragraph updated |
| `.claude/docs/security-threat-model-coverage.md` | MODIFIED | Threat 4 summary-table row + per-threat section + Gap-issue triage G1 row all updated to mark the gap closed by E13_S04b |

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| All 7 return-chunk-or-content tools enforce 256 KB cap with identical semantics | ✅ | 5 handler patches calling the shared `server.tools.enforce_byte_cap`; multi-result tools pass `chunk_id=None`; `cite_neighbors` passes the input `chunk_id` for the parent-context resource_link |
| `tests/security/test_resource_exhaustion.py` includes parametrized cap-rejection tests for all five newly-covered tools | ✅ | `TestE13S04bCapExtension::test_multi_result_cap_passes_under_cap_unchanged` (4 tools) + `test_multi_result_cap_fires_on_over_cap` (4 tools) + `test_cite_neighbors_cap_*` (2 tests) + `test_handler_module_imports_enforce_byte_cap` (5 modules) = 15 new tests |
| `pytest tests/security/test_resource_exhaustion.py` passes all cases | ✅ | 46 passed (was 31 before E13_S04b → +15 net) |
| `.claude/docs/security-threat-model-coverage.md` Threat 4 row no longer cites #1; Gap-issue triage table updated | ✅ | Summary-table Gap cell: `(none — closed by E13_S04b, see #1 (closed))`. Per-threat Threat 4 section: `(none) — closed by E13_S04b`. Gap-issue triage G1 row: marked closed with strikethrough |
| `tests/security/test_threat_model_coverage.py` (E13_S10 staleness gate) still passes | ✅ | 21 passed; doc structure preserved (all 7 numbered-threat sections + observability addendum still present; cited test files still exist) |
| GitHub issue #1 closed with a commit reference | ⚠️ **Phase-4 gated** — `gh issue close 1` requires user authorization at the external-write boundary |

## Brief deviations (all resolved by orchestrator synthesis)

1. **Helper extraction was not needed** — `server.tools.enforce_byte_cap` already exists and is single-sourced. The synthesis correctly identified that "reuse not extract" was the smallest viable change. Each handler module gets its own thin `_cap()` wrapper (matching the `definitions.py::_cap` precedent) so the call site is consistent and the per-tool rationale (multi-result vs parent-context, forward-compat for E09/E11/E12) is documented locally.

2. **`chunk_id` argument for multi-result tools** — synthesis chose `None` (omit resource_link) for `search_papers`, `find_equation`, `find_lemma_by_name`, and `get_paper`. The over-cap surface for these is the aggregate response envelope, not a single chunk; pointing the link at "the first row's chunk_id" would mislead. The `body_truncated=True` flag is still set, which is the meaningful signal.

3. **`cite_neighbors` passes input `chunk_id`** — the parent context whose neighborhood is being returned IS the meaningful resource link target. Forward-compat for E09 wire-up: when the Kùzu graph queries become real, the cap will fire on oversized neighborhood responses and the link will point back to the queried parent.

4. **`get_paper` cap is a no-op at v1** — the brief explicitly noted this. V1 returns NULL for abstract/authors/title/year/categories so payloads are tiny. The cap is forward-compat for E11/E12 metadata table (3000+ author lists for ATLAS/CMS papers). Test coverage exercises the over-cap path with a synthetic oversized payload to verify the wire is correct.

5. **`cite_neighbors` cap is also a no-op at v1** — handler is a stub returning empty neighbors. Same forward-compat argument: E09 wire-up will produce real over-cap responses.

## Tests

- **Extended test file:** `tests/security/test_resource_exhaustion.py`
- **New test class:** `TestE13S04bCapExtension` (15 tests, all passing)
  - 4 parametrized under-cap-pass-through tests (search, equation, lemma, paper)
  - 4 parametrized over-cap-fires tests (same 4 tools)
  - 2 cite_neighbors tests (under-cap + over-cap; separate because `_cap` takes a `chunk_id` arg)
  - 5 parametrized static import tests (every newly-covered module's `_cap` exists and references `enforce_byte_cap`)

- **Existing tests verified:** existing `TestByteCapEnforcement` (helper-level tests) and other cap-related tests in the same file all continue to pass (31 → 46 total in this file).

## Project-check status

- `ruff check .` → clean
- `pytest tests/security/test_resource_exhaustion.py` → 46 passed
- `pytest tests/security/test_resource_exhaustion.py tests/security/test_threat_model_coverage.py` → 67 passed (no regressions in the E13_S10 staleness gate)
- Full `pytest` → 2115 passed (was 2100 before → +15 = exactly the new tests). 29 pre-existing Windows-platform failures unchanged.

## External writes required

| Type | Target | Why | Blocking |
|---|---|---|---|
| `gh issue close 1` | `chris-dare-dev/arXMCP#1` | Close the gap-issue with reference to the closing commit | **YES — Phase-4 gated** |

The orchestrator surfaces the issue close at the Phase-4 external-write boundary. On user approval: `gh issue close 1 --reason completed --comment "Closed by E13_S04b: <commit-sha>"`. On user skip: the doc retains the "closed by E13_S04b" wording but the issue stays open on GitHub.

## Anything notable for the critic

1. **Schema impact zero.** No Pydantic `Field` constraint additions. `EXPECTED_TOOL_SCHEMA_SHA256` stays stable. BP1 prompt-cache invariant preserved. The cap is a handler-body-only change.

2. **`get_paper` and `cite_neighbors` caps are forward-compat no-ops** — adversary should evaluate whether the tests adequately exercise the over-cap path even though the production v1 invocation never triggers it. The tests do construct synthetic oversized payloads to exercise the cap wire; this is intentional defensive coverage.

3. **`search.py` has 3 return sites** (Tier-1 cache hit, Tier-2 cache hit, miss/compute). All 3 get the cap. The synthesis was explicit about this; the implementation walked all 3.

4. **`lemma.py` has 5 return sites** (4 in the FTS5 dispatcher + 1 in the in-memory scan fallback). All 5 get the cap.

5. **Static import test** — `test_handler_module_imports_enforce_byte_cap` catches the regression where someone refactors a handler and accidentally drops the cap helper import. The per-handler tests would still pass (because pytest re-imports the module) but the live request path would fail; the static check catches it.

6. **No-fork policy compliance.** Nothing copied from OSS. The `_cap()` wrapper pattern is identical to `definitions.py::_cap` (which has been in the codebase since E10_S01) — explicit precedent reuse.

7. **`EXPECTED_TOOL_SCHEMA_SHA256` was not touched** — tools/list output is unchanged; no re-pin needed.

8. **The cap measurement is on serialized JSON bytes × 2** (wire overhead factor); per the existing `enforce_byte_cap` helper. The synthesis confirmed this is the right measurement point. Tests construct payloads with a 200 KB filler string so the serialized-doubled length comfortably exceeds 256 KB (the doubled 200 KB inner content is 400 KB, well over 256 KB).
