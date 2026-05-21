# proof-verify-handler-wiring-m2 — implementation summary

## One-line summary

`search_papers` now echoes the canonically-honored filter back to the
caller in a new `filters_applied` field; schema bumped v8→v9 and the
`tools/list` byte-hash + `TOOL_SCHEMA_VERSION` pin re-stamped in
lockstep.

## Commit range

`a1aa11b..<HEAD-after-feat-commit>`

(Base SHA recorded in `state.json::implementation_base`. Feat commit is
the only m2 implementation commit at the time of writing; the orchestrator
will append a rectifier commit if Phase 3 surfaces any findings, and a
`chore(notes)` commit at Phase 4 close.)

## Acceptance criteria status

From the synthesis (`research-synthesis.md`):

- [x] **AC #1** — Filtered response carries `filters_applied:
  {paper_id: [...]}` with the same canonical (sorted, deduped) shape
  produced by `_canonicalize_filters`. Verified by
  `TestFiltersAppliedHandlerIntegration::test_paper_id_filter_string_form_is_canonicalized_in_echo`
  and `..._list_form_is_passed_through_in_echo`.
- [x] **AC #2** — No-filter call omits `filters_applied` entirely (field
  is absent, not null). Verified by
  `TestFiltersAppliedHandlerIntegration::test_no_filter_arg_omits_filters_applied`
  + a regression guard pinned at the schema level
  (`TestSchemaConformanceForFiltersApplied::test_no_filter_payload_validates_without_filters_applied`).
- [x] **AC #3** — Unsupported filter keys never leak into the echo; they
  remain in `filter_warnings` only. Verified by
  `TestFiltersAppliedHelper::test_unsupported_filter_keys_are_dropped`
  + `TestFiltersAppliedHandlerIntegration::test_unsupported_keys_stay_in_filter_warnings_only`.
- [x] **AC #4 (revised)** — `TOOL_SCHEMA_VERSION` bumped 8→9 and the
  `tools/list` byte-hash re-pinned via `pytest --update-tool-schema-hash`.
  (The synthesis flagged the original brief's framing as wrong: the
  version DOES flow into BP1 via `_meta`, so the hash must move.)
- [x] **AC #5** — JSON schema `version` integer bumped 8→9; description
  appended with the m2 changelog line.
- [x] **AC #6** — All three cache-paths (miss, Tier-1 hit, Tier-2 hit)
  re-stamp the echo. Verified by
  `TestFiltersAppliedHandlerIntegration::test_tier1_cache_hit_restamps_filters_applied`
  + the existing Tier-1 hit path is covered by the `_restamp_degraded`
  pattern shared with the new `_inject_filters_applied` call site.

## New / changed files

- `server/handlers/search.py` — added `_inject_filters_applied(payload,
  canonical_filters)` helper; wired into miss + Tier-1-hit + Tier-2-hit
  paths immediately after `_restamp_degraded` (same post-cache slot
  pattern).
- `server/schemas/search_papers_result.json` — version 8→9; added
  `filters_applied` to `properties` (NOT required); description bumped
  with the m2 changelog line.
- `server/tools.py` — `TOOL_SCHEMA_VERSION` 8→9.
- `tests/test_search_filter.py` — added 12 new tests across three classes:
  - `TestFiltersAppliedHelper` (4 tests) — pure helper unit-tests
    (no-filter, supported only, unsupported only, mixed).
  - `TestFiltersAppliedHandlerIntegration` (5 tests) — handler-level
    integration (string canonicalization, list pass-through,
    unsupported-key isolation, no-filter omission, Tier-1 cache re-stamp).
  - `TestSchemaConformanceForFiltersApplied` (3 tests) — `jsonschema`
    validation: filtered payload validates, no-filter payload validates
    without the field, schema version pin matches `TOOL_SCHEMA_VERSION`.
- `tests/test_server_tool_schema.py` — `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned via
  `pytest --update-tool-schema-hash`.
- `CHANGES.md` — `## Unreleased` entry added covering both m1 + m2.

## Test results

`make test PYTHON="/Users/chris.dare/Library/Python/3.9/bin/uv run python"`:

```
2250 passed, 9 skipped, 1 xfailed, 13 warnings in 98.92s
```

Net delta from m1-complete state: +12 tests (the new m2 classes).
Ruff clean. No new skips, no new xfails.

The BP1 hash (`tests/test_prompts.py::EXPECTED_BP1_SHA256`) was
**not** re-pinned — it remained stable across the m2 bump because the
BP1-cached tool metadata doesn't include the `version` integer from the
JSON schema (only the descriptor side carries it via `_meta`, which is
already covered by `EXPECTED_TOOL_SCHEMA_SHA256`).

## External writes required

None. m2 is a local-only schema + handler change; the only external
mutations (CHANGES.md + state.json) are repo-internal and follow the
standard `feat(server) → rect(server) → chore(notes)` commit triple.

## Deviations from the brief

- **AC #4 framing corrected.** The brief said "`TOOL_SCHEMA_VERSION`
  bump is optional because BP1 doesn't see it." The synthesis (Disagreement
  #2 resolution) caught that the version DOES flow into BP1 via `_meta`,
  so the bump is mandatory and the `tools/list` hash must move. The
  implementation honors the corrected framing.
- **Companion fix for `degraded` / `degraded_reasons` schema gap deferred.**
  Both research briefs surfaced that the schema doesn't declare these
  fields even though `_restamp_degraded` writes them in some paths. The
  synthesis (Disagreement #3 resolution) explicitly deferred this to a
  future milestone to keep m2 minimal. Tracked in
  `.claude/notes/milestones/proof-verify-handler-wiring-m2/research-synthesis.md`.
- **No null sentinel for the no-filter case.** Brief was ambiguous; the
  synthesis (Disagreement #4) picked "absent" over "null" for byte-stability
  reasons (cache-key stability across the no-filter hot path). The
  implementation omits the field entirely when no filter was passed.
