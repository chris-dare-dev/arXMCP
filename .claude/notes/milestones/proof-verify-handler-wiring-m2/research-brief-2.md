# Research Brief — proof-verify-handler-wiring-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-21T23:45:00Z

## In-codebase context

### Design constitution notes that apply

**`07-multi-agent-caching.md` — Property 2 (load-bearing):**
> "Every result is deterministic for `(query, filters, k, corpus_version)`. … JSON keys serialized in alphabetical order."

**`07-multi-agent-caching.md` — Property 1:**
> "Pin tool JSON schemas. Sort properties alphabetically at serialization time. Freeze descriptions as constants in source. A casual edit to a tool description blows every sub-agent's cache."

`server/tools.py::envelope` calls `_sort_dict(payload)` which recursively sorts all dict keys alphabetically. `_build_content_blocks` uses `json.dumps(structured, indent=2, sort_keys=True, ensure_ascii=False)`. These two serialization paths BOTH enforce alphabetical key order. `filters_applied` (starts with 'f') sorts between `filter_warnings` (f-i) and `next_cursor` (n). Alphabetical order: `corpus_version`, `degraded`, `degraded_reasons`, `embed_model`, `excluded_kinds`, `filter_warnings`, **`filters_applied`**, `next_cursor`, `results`, `retrieval_mode`. This is correct and requires no special handling — `envelope()` + `_sort_dict()` handle it automatically.

**`server/schemas/search_papers_result.json` — `additionalProperties: false` (CRITICAL constraint):**
The top-level schema object has `"additionalProperties": false` with exactly 7 properties listed in `properties` (corpus_version, embed_model, excluded_kinds, filter_warnings, next_cursor, results, retrieval_mode) and all 7 in `required`. `filters_applied` is NOT currently in `properties`. Adding it to the handler output without updating the schema will cause `test_snippet_contract.py::TestSchemaConformance::test_schema_validates_real_search_response` to FAIL with jsonschema `AdditionalProperties` validation error.

**Pre-existing schema violation (FLAG):** The handler already emits `degraded` and `degraded_reasons` fields (lines 469–471 of `server/handlers/search.py`) when `r.degraded is not None`. Neither field exists in `server/schemas/search_papers_result.json`. `jsonschema.validate` FAILS on these fields (verified empirically). The live test passes only because `r.degraded is None` in test fixtures. **This is a pre-existing schema gap that m2 must not make worse, and ideally should note in its CHANGES.md entry.**

**`TOOL_SCHEMA_VERSION` is currently 8** (set in m1 for input schema changes). The per-tool `_meta: {"tool_schema_version": 8}` is in ALL_TOOLS. `tests/test_snippet_contract.py::TestSchemaVersionPin` cross-checks that `schema["version"] == TOOL_SCHEMA_VERSION`. Currently both are 8. Adding `filters_applied` to the output shape is an OUTPUT schema change — it requires bumping `schema["version"]` in `search_papers_result.json`, which in turn requires bumping `TOOL_SCHEMA_VERSION` in `server/tools.py`.

**`EXPECTED_TOOL_SCHEMA_SHA256` (BP1 impact):** The BP1 hash covers `tools/list` wire bytes, which are derived from `ALL_TOOLS` (tool names + input schemas + descriptions). The OUTPUT schema file is NOT part of `tools/list`. Bumping `TOOL_SCHEMA_VERSION` from 8→9 DOES appear in `ALL_TOOLS` (via per-tool `_meta: {"tool_schema_version": 9}`) and therefore DOES change `tools/list` bytes and WILL invalidate `EXPECTED_TOOL_SCHEMA_SHA256`. The implementer MUST run `pytest --update-tool-schema-hash` and re-pin `EXPECTED_BP1_SHA256` in `tests/test_prompts.py`.

**`_canonicalize_filters`** (lines 195–221 of `server/handlers/search.py`) transforms `{"paper_id": "x"}` → `{"paper_id": ["x"]}` and sorts the list. The canonical form is used for all cache key computation. The original (pre-canonicalize) `filters` variable is preserved for `filter_warnings` reflection (comment at line 310). There are two valid choices for `filters_applied` content — see Failure Mode 4 below.

**Cache paths:** `filters_applied` must be injected on ALL code paths (Tier-1 hit, Tier-2 hit, cache miss). The cached payload stored at miss time will NOT contain `filters_applied` (because the cache stores the generic envelope). On cache hit, the handler re-stamps `degraded` via `_restamp_degraded` — a parallel pattern must inject `filters_applied`. Without this, cached results lack the field, breaking AC #1.

## Prior decisions and lessons

**git log (recent):**
```
0555ea2 chore(notes): mark E13_S04b external writes as completed
60d3672 chore(notes): append milestone-researcher memory for E13_S09/S10/S04b
93ea2ae chore(notes): finalize E13_S04b state -> complete
bfb796c rect(server,tests,docs): close 1 CRITICAL+1 MEDIUM from E13_S04b critique
874db28 feat(server,tests,docs): extend 256 KB byte cap to all tools (E13_S04b)
```

No m1 commit visible in the last 20 — m1 may have landed earlier or is in flight. The `state.json` for m2 is in `research-running` phase.

**`test_snippet_contract.py::TestPayloadShape::test_no_unexpected_fields`** (line 143) checks that result rows have no extra fields beyond the allowed 6. This row-level test does NOT check envelope-level fields, so `filters_applied` at the envelope level doesn't trigger it.

**`test_snippet_contract.py::TestSchemaConformance::test_schema_validates_real_search_response`** (line 304) calls `jsonschema.validate(instance=sc, schema=schema)` — this IS the test that will fail if `filters_applied` is added to the envelope without adding it to `properties` in the schema file. In normal (non-degraded) test runs, `sc` won't contain `degraded`/`degraded_reasons`, so the pre-existing bug stays latent.

**CHANGES.md format:** epic-grain entries under `## Unreleased` header. No m1 or proof-verify entries exist yet in CHANGES.md — the `## Unreleased` section currently has only the "Doc-layout consolidation" entry from 2026-05-10. m2 must add the first proof-verify entry.

## External sources

**JSON Schema draft-07 `additionalProperties: false` semantics:** When `additionalProperties: false` is set, the validator rejects any instance property whose name is not listed in the `properties` keyword (or matches a `patternProperties` pattern). A new optional field that should be ALLOWED must be declared in `properties` even if not in `required`. Making a field absent-by-default (not in `required`) means the schema ALLOWS it absent, ALLOWS it present if the instance provides it, but only if it is in `properties`.

**MCP spec (2025-06-18):** The `structuredContent` field in `CallToolResult` is described as an object whose shape is tool-defined. The spec imposes no constraints on which fields may appear in that object — per-tool custom fields are fully permissible. There is no spec-level prohibition on adding `filters_applied` to the search_papers output.

No Anthropic prompt-caching doc pull needed for this milestone — the BP1 concern is resolved by the in-codebase analysis above.

## Failure-mode analysis

**FM-1 — Schema validation failure on filtered call.**
- Trigger: `filters_applied` added to handler output but NOT added to `search_papers_result.json::properties`.
- Symptom: `test_snippet_contract.py::TestSchemaConformance::test_schema_validates_real_search_response` fails with `jsonschema.ValidationError: Additional properties are not allowed ('filters_applied' was unexpected)`. This fires on EVERY call with a filter — easily caught in tests if filter-path is exercised.
- Mitigation: Add `filters_applied` to `properties` (as optional — not in `required`) in `search_papers_result.json`. Bump `schema["version"]` to 9 and `TOOL_SCHEMA_VERSION` to 9 in lockstep. Re-pin `EXPECTED_TOOL_SCHEMA_SHA256`.

**FM-2 — Schema version drift: schema file bumped but TOOL_SCHEMA_VERSION not bumped (or vice versa).**
- Trigger: Bumping schema `"version": 9` in the JSON file but forgetting `TOOL_SCHEMA_VERSION: int = 9` in `server/tools.py`, or vice versa.
- Symptom: `test_snippet_contract.py::TestSchemaVersionPin::test_schema_version_matches_tool_schema_version` fails asserting `schema["version"] != TOOL_SCHEMA_VERSION`.
- Mitigation: Both bumps are mandatory and must be atomic in the same commit. Note: `TOOL_SCHEMA_VERSION` bump also changes `_meta` embedded in ALL_TOOLS, changing `tools/list` bytes, invalidating `EXPECTED_TOOL_SCHEMA_SHA256`. Run `pytest --update-tool-schema-hash` AFTER both bumps.

**FM-3 — `filters_applied` absent on cache-hit paths (Tier-1 and Tier-2).**
- Trigger: Implementer adds `filters_applied` to the miss-path `payload` dict (line ~460 in search.py) but forgets to inject it on the Tier-1 hit path (line ~350) and Tier-2 hit path (line ~386).
- Symptom: AC #1 passes for uncached calls but FAILS for cached repeat calls. A test that calls `search_papers` twice with the same filter will see the field on call 1 but not call 2. Subtle — most tests don't repeat the same query twice.
- Mitigation: Introduce a `_restamp_filters_applied(cached_payload, canonical_filters)` helper parallel to `_restamp_degraded`. Apply it on Tier-1 and Tier-2 hit paths, using `canonical_filters` (already computed before cache lookup at line 312). Alternatively, do NOT store `filters_applied` in the cached payload and always inject it post-cache (same approach as `_restamp_degraded`). The `_restamp_*` pattern is the established pattern in this codebase.

**FM-4 — Echo form: original vs. canonical (which form to put in `filters_applied`).**
- Trigger: AC #1 says `"filters_applied": {"paper_id": [...]}` — the list form. Caller may have supplied a str (e.g. `{"paper_id": "2401.01234"}`). Should `filters_applied` echo `{"paper_id": ["2401.01234"]}` (canonicalized) or `{"paper_id": "2401.01234"}` (original)?
- Symptom: If original form is echoed, `filters_applied` is non-deterministic (str vs list) and doesn't match AC #1's list-form. If canonicalized form is echoed, caller sees their str coerced to a list — this is a behavioral disclosure but technically correct and more useful for verification.
- Recommendation: **Echo the canonicalized form** (`canonical_filters`). Rationale: (a) AC #1 explicitly shows list form `{"paper_id": [...]}` even for single IDs; (b) the canonicalized form is what was ACTUALLY used for retrieval — it matches what `_build_paper_id_predicate` executed; (c) it is deterministic and cache-stable; (d) `canonical_filters` is already computed at line 312 and available throughout the handler.

**FM-5 — `filters_applied` absent vs. null for no-filter case — cache key and JSON serialization divergence.**
- Trigger: AC #2 says "absent or null". These serialize differently: `null` → `"filters_applied": null` in JSON (present key); absent → key omitted entirely. `json.dumps(struct, sort_keys=True)` on a payload with `filters_applied: null` produces a different byte sequence than on one without the key — breaking the "byte-stable for same inputs" contract from `07-multi-agent-caching.md` Property 2 for the content[0].text block.
- Symptom: If `filters_applied: null` is always present (even when no filter), it adds ~22 bytes to every unfiltered call's response. It also pollutes the schema's `required` list if added there, forcing the field to be present always.
- Recommendation: **Use absent (omit the key entirely) when no filter is applied.** Rationale: `07-multi-agent-caching.md` states "JSON keys serialized in alphabetical order" — omitting vs. null produces different byte sequences. The no-filter response should be byte-identical to pre-m2 responses (preserving cache hits for all existing calls). Only introduce the key when a filter was actually applied. The JSON Schema optional approach (in `properties` but not `required`) supports this cleanly. The schema-validation test will pass whether the field is absent or present-with-value, as long as it is in `properties`.

**FM-6 — Pre-existing `degraded`/`degraded_reasons` schema gap made worse.**
- Trigger: `degraded` and `degraded_reasons` are already emitted by the handler but not in the schema. m2 adds `filters_applied` to the schema. If a reviewer runs `jsonschema.validate` against a degraded response, it now fails on TWO families of undocumented fields.
- Symptom: `test_schema_validates_real_search_response` continues to pass (tests run with `r.degraded = None`) but the schema is provably wrong for degraded calls. The m2 implementer should note this gap in the CHANGES.md entry and ideally add `degraded` and `degraded_reasons` to `properties` (both optional, not in `required`) in the same schema bump.
- Mitigation: Treat as a companion fix in m2 — add `degraded: {type: boolean}` and `degraded_reasons: {items: {type: string}, type: array}` as optional properties in the schema. No behavior change; just schema accuracy.

**FM-7 — CHANGES.md format violation.**
- Trigger: Entry added outside the `## Unreleased` block, or at the wrong grain level (per-commit vs. per-epic-milestone).
- Symptom: Inconsistent changelog; CHANGES.md format check (if it exists) fails. Currently no automated CHANGES.md format gate exists, but the convention is epic-grain bullets under `## Unreleased` with a milestone identifier (e.g. `**proof-verify-handler-wiring-m2**`).
- Mitigation: Add a bullet under `## Unreleased` immediately after the "Doc-layout consolidation" block. Pattern from existing entries: `- **<milestone>** — <one-sentence description>`.

## Recommendation

Add `filters_applied` as an **optional envelope field** (absent when no filter, present with canonicalized value when filter applied), using the `_restamp_*` post-cache-injection pattern. Specifically:

1. Add `filters_applied` to `server/schemas/search_papers_result.json::properties` as optional (type object, not in `required`). Also add `degraded` and `degraded_reasons` as companion optional properties to fix the pre-existing schema gap.
2. Bump `schema["version"]` to 9 and `TOOL_SCHEMA_VERSION` to 9 in lockstep.
3. In `handle_search_papers`, introduce a `_inject_filters_applied(payload, canonical_filters)` helper that adds `"filters_applied": canonical_filters` to the dict if `canonical_filters is not None`, then `_sort_dict` picks it up via `envelope()`.
4. Apply the helper at ALL three code paths: Tier-1 hit (after `_restamp_degraded`), Tier-2 hit (after `_restamp_degraded`), and miss path (before `envelope(payload)` call).
5. Run `pytest --update-tool-schema-hash` to re-pin `EXPECTED_TOOL_SCHEMA_SHA256`.
6. Re-pin `EXPECTED_BP1_SHA256` in `tests/test_prompts.py`.
7. Add CHANGES.md entry under `## Unreleased`.

Do NOT store `filters_applied` in the cached payload (it is caller-specific metadata, not retrieval-specific). Inject it post-cache, always from the live `canonical_filters` variable.

## Open questions

**OQ-1 — Companion fix for `degraded`/`degraded_reasons` schema gap.** Should m2 fix the pre-existing gap (adding `degraded` and `degraded_reasons` to the schema), or leave it for a dedicated follow-up? My recommendation: fix it in m2 since the schema version is already being bumped. But if the adversary finds it high-severity, it becomes a rectification item rather than an in-scope addition.

No other open questions — implementation can proceed on the above recommendation pending OQ-1 resolution.

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no infra mutation.

The schema version bump, EXPECTED_TOOL_SCHEMA_SHA256 re-pin, and EXPECTED_BP1_SHA256 re-pin are all local file edits + test re-runs, not external writes.
