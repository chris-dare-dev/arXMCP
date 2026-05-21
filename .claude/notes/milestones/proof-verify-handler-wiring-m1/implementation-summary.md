# m1 — Implementation Summary

**One-line summary.** `search_papers` now honors `filters={"paper_id": [...]}` end-to-end via a LanceDB `.where("paper_id IN (...)", prefilter=True)` predicate threaded into the ANN call. Helper functions defend against malformed input (per-element `is_valid_paper_id`, length cap, single-quote escape). The legacy "filters arg deferred to E07_S04" blanket warning is replaced with per-unrecognized-key warnings.

**Commit range.** `904db00..<HEAD>` (single feat commit).

**Implementation path.** INLINE (orchestrator implemented directly per synthesis recommendation; small surface, no novel architecture).

## Acceptance criteria status

| # | Acceptance criterion | Status | Verification |
|---|---|---|---|
| 1 | Filter scopes results to filter set | ✓ | `test_filter_applied_when_paper_id_present` + end-to-end smoke test against 39-paper bridgeland notebook (top-5 = `['0712.1083', '0705.3794', '0712.1083', '0712.1083', '0712.1083']`, 0 violations) |
| 2 | No-filter byte-identical to pre-m1 dense-only | ✓ | `test_no_filter_no_where_call` — `.where()` is not called when `filters=None` |
| 3 | Malformed filter → clear error (not 500) | ✓ | 6 tests (`test_empty_paper_id_list_raises_clear_error`, `test_malformed_paper_id_raises_clear_error`, etc.) — all raise `ValueError` with descriptive messages |
| 4 | `EXPECTED_TOOL_SCHEMA_SHA256` unchanged | ✓ | `tests/test_server_tool_schema.py` continues to pass — all validation is handler-body, not Pydantic. `MAX_PAPER_ID_FILTER_ITEMS` is a module-level constant (not a Field constraint). |
| 5 | New tests under `tests/test_search_filter.py` | ✓ | 27 tests covering AC #1-#3 + all 9 failure modes from synthesis |
| 6 | `make test` green | ✓ | 2230 passed, 9 skipped, 1 xfailed (up from 2203 baseline; +27 m1 tests) |

## New / changed files

**Modified:**
- `server/handlers/search.py` — added `MAX_PAPER_ID_FILTER_ITEMS=100`, `SUPPORTED_FILTER_KEYS=frozenset({"paper_id"})`, `_escape_paper_id_literal()`, `_build_paper_id_predicate()`. Threaded `paper_id_predicate` computation BEFORE cache lookup; `.where(predicate, prefilter=True)` chained between `.search()` and `.limit()`. Filter-warnings block rewritten to emit per-unrecognized-key warnings instead of a blanket "deferred" message. ~90 LOC net.
- `tests/test_tools_all.py` — updated `test_search_accepts_filters_arg` to assert the new per-key warning format. Legacy test was written for pre-m1 F6 behavior; m1 closes that behavior so the assertion text needed updating.

**New:**
- `tests/test_search_filter.py` — 27 tests across 4 test classes (`TestBuildPaperIdPredicate`, `TestHandlerFilterWiring`, `TestCacheKeyDistinguishesFilterSets`, plus a top-level `test_supported_filter_keys_matches_expected`). Mocks the LanceDB `.search().where().limit().to_arrow()` chain via a `_FakeSearchBuilder` and installs a fake Resources via `set_resources()` so `envelope()` finds a stub. Tests follow the project's `asyncio.run()` pattern (no `pytest-asyncio` in this repo).

**Milestone-pipeline artifacts:**
- `.claude/notes/milestones/proof-verify-handler-wiring-m1/research-brief-1.md`
- `.claude/notes/milestones/proof-verify-handler-wiring-m1/research-brief-2.md`
- `.claude/notes/milestones/proof-verify-handler-wiring-m1/research-synthesis.md`
- `.claude/notes/milestones/proof-verify-handler-wiring-m1/state.json`

## External writes required

None. Handler-body change + tests only. Phase 4 has no external-write gate to fire.

## Deviations from the brief

1. **"Update the cache key to include the filter set"** — the brief's instruction is wrong; both researchers independently verified the cache key ALREADY includes `filters` via `canonical_key_components` (`json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))`). No cache layer change needed. Cache-correctness regression tests added under `TestCacheKeyDistinguishesFilterSets` to pin this behavior.

2. **"New unit test under `tests/handlers/test_search_filter.py` (or equivalent)"** — placed at `tests/test_search_filter.py` (flat layout), matching the existing project convention (`tests/test_snippet_contract.py`, `tests/test_tools_all.py`, etc.). The brief's `tests/handlers/` would have required a new package + `__init__.py`. The brief explicitly allowed "or equivalent."

3. **`prefilter=True`** — synthesis-resolved disagreement. Use `prefilter=True` (R-2's recommendation) instead of relying on LanceDB's default behavior (R-1's reading of the spike). Three reasons: semantics safety (postfilter would give too few results on small filter sets), codebase convention (all other ANN+predicate callsites use `prefilter=True`), spike-1 didn't disprove `prefilter=True` (its 5/39 filter ratio wasn't a discriminating test).

## Failure modes covered (synthesis FM-1 through FM-9)

| FM | Coverage |
|---|---|
| FM-1 (injection) | `is_valid_paper_id` regex (FIRST) + single-quote escape (ALWAYS). Tests: `test_injection_attempt_rejected_by_regex`, `test_escape_function_doubles_single_quotes`. |
| FM-2 (empty list) | `_build_paper_id_predicate` raises `ValueError("must not be empty")`. Tests: `test_empty_list_raises_value_error`, `test_empty_paper_id_list_raises_clear_error`. |
| FM-3 (str→list coercion) | `isinstance(paper_id_value, str)` branch in helper. Tests: `test_single_string_is_coerced_to_list`, `test_string_paper_id_coerced_to_one_element`. |
| FM-4 (oversized list) | `MAX_PAPER_ID_FILTER_ITEMS=100` constant + len-check. Tests: `test_oversized_list_raises_value_error`, `test_exactly_max_items_accepted`, `test_oversized_paper_id_list_raises`. |
| FM-5 (all malformed) | `[pid for pid in paper_ids if not is_valid_paper_id(pid)]` + raise. Tests: `test_malformed_id_raises_with_first_invalid_named`, `test_all_malformed_raises`, `test_malformed_paper_id_raises_clear_error`. |
| FM-6 (cache key) | Already handled by `canonical_key_components`; tests pin behavior. Tests: `test_canonical_filter_fingerprint_distinct_per_filter_set`, `test_canonical_filter_fingerprint_no_filter_distinct`. |
| FM-7 (nonexistent paper_id) | Returns empty Arrow → empty results. Test: `test_nonexistent_paper_id_returns_empty`. |
| FM-8 (`prefilter=True`) | Wired into the `.where()` call. Test: `test_filter_applied_when_paper_id_present` asserts `kwargs == {"prefilter": True}`. |
| FM-9 (unrecognized-key warning) | `set(filters) - SUPPORTED_FILTER_KEYS` loop. Tests: `test_unknown_filter_key_surfaced_as_warning`, `test_only_paper_id_filter_no_warnings`. |

## What needs Phase 3 critique attention

- **`set_resources()` test pattern** — m1's test fixture is the first to use `set_resources()` directly outside `warm_app` integration tests. Worth confirming this doesn't leak state between tests (the fixture has `reset_resources_for_tests()` in teardown).
- **Filter-warnings ordering** — the new per-key warnings are sorted via `sorted(set(filters) - SUPPORTED_FILTER_KEYS)`. If multiple unknown keys are present, ordering is alphabetical. Worth confirming this matches BP1 byte-stability discipline.
- **Empty filter dict (`{}`) vs `None` semantics** — both go through "no filter" path. The handler-body check is `if filters and "paper_id" in filters:` — an empty dict fails truthiness AND lacks the key, so it's handled correctly. Worth a critique scan for the corner case `filters={"paper_id": None}` (which would hit the helper and raise on non-str-non-list).
- **Test fixture isolation** — `_FakeResources` doesn't implement every Resources attribute; if any code path the handler doesn't currently take (e.g. degraded fallback) were exercised, tests would fail with `AttributeError`. Acceptable for unit tests of the m1 surface; flagged for future-proofing.
