# Research Synthesis — proof-verify-handler-wiring-m2

**Generated:** 2026-05-21
**Mode:** standard (2 researchers)
**Briefs merged:** `research-brief-1.md`, `research-brief-2.md`

---

## What's getting built (single-sentence)

Add `filters_applied` to the `search_papers` output payload (echoes the **canonical** form of the honored filter, **absent when no filter**), declared in `server/schemas/search_papers_result.json` as an optional property, applied on all three cache paths (Tier-1 hit, Tier-2 hit, miss) via a `_inject_filters_applied` helper paralleling the existing `_restamp_degraded` pattern. Bump `TOOL_SCHEMA_VERSION` 8→9, re-pin two hashes (`EXPECTED_TOOL_SCHEMA_SHA256`, `EXPECTED_BP1_SHA256`), and add a `CHANGES.md` entry covering m1 and m2 under `## Unreleased`.

## Load-bearing constraints (verbatim)

From `server/handlers/search.py:460-472` (current payload construction — m2 surgery site):

```python
payload: dict[str, Any] = {
    "embed_model": "bge-m3",
    # F5: explicit warning about proof-chunk exclusion at v1.
    "excluded_kinds": ["proof"],
    "filter_warnings": filter_warnings,
    "next_cursor": None,    # v1: no pagination
    "results": rows,
    "retrieval_mode": "dense_only",
}
```

From `server/tools.py::envelope` (BP1 byte-stability):
> "Wrap a tool's payload with the canonical result envelope. Adds `corpus_version` (sourced from the live Resources) and sorts the dict alphabetically (BP1 byte-stability)."

From `server/schemas/search_papers_result.json` (the structural gate):
- `"additionalProperties": false` at the top level — any field in the live response NOT in `properties` causes `jsonschema.validate` to fail.
- `"version": 8` — must equal `TOOL_SCHEMA_VERSION` per `tests/test_snippet_contract.py::TestSchemaVersionPin`.

From `tests/test_snippet_contract.py::TestSchemaConformance::test_schema_validates_real_search_response` — the binding test that catches m2 if `filters_applied` is added to handler output but NOT to the schema.

From `07-multi-agent-caching.md` Property 2:
> "Every result is deterministic for `(query, filters, k, corpus_version)`. … JSON keys serialized in alphabetical order."

## Resolved disagreements

### Disagreement 1: Echo all canonical keys or only SUPPORTED_FILTER_KEYS — **SUPPORTED_FILTER_KEYS only**

- **R-1 position:** Echo only the keys in `SUPPORTED_FILTER_KEYS` from `canonical_filters` (i.e. `{"paper_id": canonical_filters["paper_id"]}`). Unsupported keys go to `filter_warnings`, not `filters_applied`.
- **R-2 position:** Echo the full `canonical_filters` wholesale (would include any unknown keys that survived the canonicalize step).

**Resolution: R-1's approach wins.** Two reasons:
1. **Semantic clarity.** `filters_applied` should mean "what we actually used to scope retrieval." Unknown keys are NOT applied — they're ignored and warned about. Reflecting them in `filters_applied` would lie about server behavior.
2. **Symmetry with `filter_warnings`.** Each unrecognized key surfaces exactly once, in `filter_warnings`. `filters_applied` is the dual — only honored keys. Two non-overlapping views of the filter input.

Concrete shape:
```python
applied: dict[str, Any] = {
    k: canonical_filters[k]
    for k in SUPPORTED_FILTER_KEYS
    if k in canonical_filters
} if canonical_filters is not None else None
```

### Disagreement 2: AC #4 says "output payload is not in BP1-hashed surface" — **AC #4 IS WRONG**

Both researchers caught this independently. The truth:
- The payload CONTENT itself is not part of BP1.
- BUT `TOOL_SCHEMA_VERSION` is in per-tool `_meta` ⊂ `ALL_TOOLS` ⊂ `tools/list` ⊂ BP1.
- Bumping the schema version 8→9 (required by `TestSchemaVersionPin` for the schema-file `"version": 9`) drifts `EXPECTED_BP1_SHA256`.

**Resolution: re-pin both hashes** (m1's rect commit established this pattern). AC #4 should be read as "output payload SHAPE is byte-stable downstream of the version bump," not "no hashes change."

### Disagreement 3: Companion fix for pre-existing `degraded`/`degraded_reasons` schema gap — **DEFER**

R-2 flagged that the handler already emits `degraded` and `degraded_reasons` fields that are NOT in the schema. They argue m2 should fix this in the same schema bump (cheap, since version is already bumping).

**Resolution: defer to a separate chore.** Three reasons:
1. **Scope creep.** m2's brief is `filters_applied` only. Fixing degraded in m2 expands the diff, the test surface, and the rect-commit risk.
2. **No regression.** The degraded gap is pre-existing (E14_S05); test fixtures don't trigger degraded mode so the test passes. Adding `filters_applied` to the schema does NOT make degraded's gap worse — both fields are optional/absent in the test case.
3. **Better commit hygiene.** A `chore(server): close pre-existing degraded/degraded_reasons schema gap` is the right shape for this fix. Bundling it under m2's `feat(server)` mislabels the commit type.

The implementer should note this gap in m2's `implementation-summary.md` "What needs Phase 3 critique attention" so the adversary can prioritize it appropriately (likely MEDIUM).

### Disagreement 4: null vs absent for the no-filter case — **ABSENT** (both researchers agree, made explicit here)

R-2 explicitly argues for ABSENT (omit the key entirely when no filter). R-1 implicitly accepts this in the recommended code shape.

**Resolution: absent.** Two reasons:
1. **Byte-stability.** `filters_applied: null` adds ~22 bytes to every unfiltered call's response, drifting from pre-m2 byte shape on the common path. Absent preserves byte-equivalence for the no-filter case.
2. **Schema flexibility.** JSON Schema with `additionalProperties: false` + field in `properties` but not in `required` cleanly supports both absent and present-with-value. `"type": ["object", "null"]` is unnecessary verbosity — `"type": "object"` is enough.

Concrete shape: in the dict literal, conditional-include via dict-comprehension or only-set-if-truthy.

## Failure modes the implementation must cover (R-2's 7, condensed)

The implementation MUST defend against each. Tests MUST cover at least FM-1, FM-3, FM-4, FM-5.

1. **Schema-validation failure on filtered call** (FM-1) — add `filters_applied` to `properties` before adding to handler.
2. **Version drift** (FM-2) — bump schema `"version"` AND `TOOL_SCHEMA_VERSION` AND `$id` in the same commit; run `pytest --update-tool-schema-hash` AFTER.
3. **`filters_applied` absent on cache-hit paths** (FM-3) — apply on Tier-1 hit, Tier-2 hit, AND miss paths; do NOT store in cached payload (caller-specific metadata).
4. **Echo form: original vs canonical** (FM-4) — canonical (per Disagreement 1).
5. **Absent vs null** (FM-5) — absent (per Disagreement 4).
6. **Pre-existing `degraded`/`degraded_reasons` schema gap** (FM-6) — out of scope; note in impl summary.
7. **CHANGES.md format** (FM-7) — under `## Unreleased`, epic-grain bullets with milestone identifier.

## Implementation sketch

1. **`server/handlers/search.py`:**
   ```python
   def _inject_filters_applied(
       payload: dict[str, Any],
       canonical_filters: dict[str, Any] | None,
   ) -> dict[str, Any]:
       """m2: add ``filters_applied`` echo if any SUPPORTED_FILTER_KEYS
       was honored. Mutates and returns ``payload``. Absent (key not
       set) when no filter was applied — preserves byte-equivalence
       with pre-m2 responses on the common unfiltered path."""
       if canonical_filters is None:
           return payload
       applied = {
           k: canonical_filters[k]
           for k in SUPPORTED_FILTER_KEYS
           if k in canonical_filters
       }
       if applied:
           payload["filters_applied"] = applied
       return payload
   ```

2. Apply on miss path (before `envelope(payload)` call):
   ```python
   payload = _inject_filters_applied(payload, canonical_filters)
   structured = envelope(payload)
   ```

3. Apply on Tier-1 hit path (after `_restamp_degraded`):
   ```python
   structured = _restamp_degraded(cached_payload, base_degraded_reasons)
   structured = _inject_filters_applied(structured, canonical_filters)
   ```

4. Apply on Tier-2 hit path (after `_restamp_degraded`):
   ```python
   structured = _restamp_degraded(cached_payload, tier2_reasons)
   structured = _inject_filters_applied(structured, canonical_filters)
   ```

5. **`server/schemas/search_papers_result.json`:**
   - Bump `"version": 8` → `9`.
   - Bump `"$id": ".../v8.json"` → `.../v9.json`.
   - Add to `"properties"`:
     ```json
     "filters_applied": {
       "description": "Echo of the filter actually honored by this call. Absent when no filter was passed. Only contains keys from SUPPORTED_FILTER_KEYS (currently: paper_id). The paper_id list is sorted and coerced to list[str] per server.handlers.search._canonicalize_filters.",
       "type": "object"
     }
     ```
   - Do NOT add to `"required"` — optional/conditional field.

6. **`server/tools.py`:** bump `TOOL_SCHEMA_VERSION: int = 8` → `9` with a comment line "v9: proof-verify-handler-wiring-m2 — `filters_applied` echo field added to search_papers output schema".

7. **Re-pin** `EXPECTED_TOOL_SCHEMA_SHA256` (via `pytest --update-tool-schema-hash`) and `EXPECTED_BP1_SHA256` (manually with the value from the test failure).

8. **`CHANGES.md`:** under `## Unreleased`, add a `### proof-verify-handler-wiring` block (epic-grain) with sub-bullets for m1 and m2 (m1 doesn't have a CHANGES entry yet — m2 adds both).

## Test surface

New file: `tests/test_search_filter_applied.py` (or extend existing `tests/test_search_filter.py`):

- `test_filters_applied_present_when_filter_honored` — call with `filters={"paper_id":[...]}`, assert `structuredContent["filters_applied"] == {"paper_id": [sorted-ids]}`.
- `test_filters_applied_absent_when_no_filter` — call with `filters=None`, assert `"filters_applied" not in structuredContent`.
- `test_filters_applied_uses_canonical_form` — call with `filters={"paper_id": "x"}` (str), assert `filters_applied == {"paper_id": ["x"]}` (list).
- `test_filters_applied_sorted_form` — call with `filters={"paper_id": ["b","a"]}`, assert `filters_applied["paper_id"] == ["a","b"]`.
- `test_filters_applied_excludes_unsupported_keys` — call with `filters={"paper_id":["x"], "year": 2024}`, assert `filters_applied == {"paper_id": ["x"]}` (year is in filter_warnings, not filters_applied).
- `test_filters_applied_present_on_tier1_cache_hit` — call twice with same filter, assert second response has `filters_applied`.
- `test_filters_applied_present_on_tier2_cache_hit` — same query, different filter (semantic-equiv-key for Tier-2), assert filters_applied present.
- `test_schema_validates_filtered_response` — load schema, build a filtered payload, assert `jsonschema.validate(payload, schema)` passes.

Plus implicit (re-runs after re-pin):
- `tests/test_snippet_contract.py::TestSchemaVersionPin` — schema["version"] == TOOL_SCHEMA_VERSION.
- `tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256` — re-pinned via `--update-tool-schema-hash`.
- `tests/test_prompts.py::EXPECTED_BP1_SHA256` — re-pinned manually.

## Implementation order (recommended)

1. Add `filters_applied` to JSON schema (`server/schemas/search_papers_result.json`) + bump version + $id.
2. Bump `TOOL_SCHEMA_VERSION` in `server/tools.py`.
3. Add `_inject_filters_applied` helper + wire into miss + Tier-1 + Tier-2 paths in `server/handlers/search.py`.
4. Write new tests in `tests/test_search_filter.py` (extend existing file).
5. Run tests; expect schema-hash + BP1-hash failures. Re-pin via `pytest --update-tool-schema-hash` + update `tests/test_prompts.py::EXPECTED_BP1_SHA256` value from the failure message.
6. Run full `make test` until green.
7. Add CHANGES.md entry under `## Unreleased`.

Estimated LOC: ~30 in `search.py` + ~150 in `tests/test_search_filter.py` (extensions) + ~10 schema + 1 LOC `tools.py` + 4 LOC CHANGES.md + 2 hash strings. Total ~200 LOC. Well under INLINE threshold. **Recommended path: INLINE.**

## Orchestrator synthesis note

Both researchers converged on the major architectural choices:
- Canonical-form echo (Disagreement 1: only the SUPPORTED keys subset).
- Schema + TOOL_SCHEMA_VERSION dual-bump with re-pin of both hashes (consensus on AC #4 being misleading).
- Apply on all 3 cache paths via `_inject_filters_applied` paralleling `_restamp_degraded`.
- Absent (not null) for no-filter case.

The single divergence on companion-fix-for-degraded was resolved by deferring out of m2's scope; the implementer should flag it as a follow-up. No blocking open questions.

## Open questions (orchestrator-resolved)

All open questions from both briefs are resolved in the disagreements section. No blockers for implementation.

## External writes the implementation will require

None — purely local. Handler change + schema bump + tests + CHANGES.md + hash re-pins. No git push, no PR, no infra mutation, no third-party API. Phase 4 has no external-write gate to fire.
