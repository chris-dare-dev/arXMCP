# Research Brief — proof-verify-handler-wiring-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-21T23:45:00Z

---

## In-codebase context

### Design notes that apply

- `07-multi-agent-caching.md` §Property 2: "JSON keys serialized in alphabetical order."
  The `envelope()` helper in `server/tools.py:310-318` calls `_sort_dict(payload)` which
  "Recursively re-build `d` with alphabetically sorted keys." Any new payload key must
  be considered in this alphabetical ordering for byte-stability.
- `06-mcp-server-design.md` — 7-tool surface; `search_papers` is one of them.
- `agent-conventions.md §7` — tool-schema re-pinning rule: adding/modifying a MCP tool
  MUST re-pin `EXPECTED_TOOL_SCHEMA_SHA256`. However, m2 is adding to the **output
  payload**, NOT to the MCP tool input schema. See the critical finding below.

### Current payload construction (verbatim, `server/handlers/search.py:460-472`)

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
if miss_degraded_reasons:
    payload["degraded"] = True
    payload["degraded_reasons"] = miss_degraded_reasons
structured = envelope(payload)
```

Alphabetical key ordering after `envelope()` sorts: `corpus_version`, `degraded`
(conditional), `degraded_reasons` (conditional), `embed_model`, `excluded_kinds`,
`filter_warnings`, `next_cursor`, `results`, `retrieval_mode`.

The new key `filters_applied` falls between `filter_warnings` and `next_cursor`
alphabetically. It should be inserted at that position in the `payload` dict literal
(ordering in the dict literal doesn't matter for correctness because `_sort_dict`
re-orders, but for readability, place it logically near `filter_warnings`).

### `_canonicalize_filters` from m1 (verbatim, `server/handlers/search.py:194-221`)

```python
SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id"})

def _canonicalize_filters(
    filters: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize semantically-identical filter inputs so the cache
    sees a stable key.
    ...
    Normalizations applied:
    1. ``str`` paper_id value → one-element ``list``.
    2. ``list`` paper_id values are sorted (deterministic order).

    Returns ``None`` unchanged when filters is None.
    """
    if filters is None:
        return None
    out: dict[str, Any] = dict(filters)
    pid = out.get("paper_id")
    if isinstance(pid, str):
        out["paper_id"] = [pid]
    elif isinstance(pid, list):
        out["paper_id"] = sorted(pid)
    return out
```

**Echo of canonical vs. original form:** AC #1 says "echoing the filter." The
`canonical_filters` variable (output of `_canonicalize_filters(filters)`) is what was
actually used in the LanceDB `.where()` predicate. It is also what was stored in the
cache key. The echo MUST use the canonical form — using the original caller-supplied
form would misrepresent what was actually applied (e.g. if caller passed
`{"paper_id": "2604.26204"}` as a str, the echo should show
`{"paper_id": ["2604.26204"]}` since that's what the filter applied). The canonical form
also strips unknown keys from the `paper_id` normalization path (unknown keys remain
in `out` via `dict(filters)` — implementer must decide whether to echo ALL keys from
canonical or ONLY supported keys). Recommendation: echo only the keys in
`SUPPORTED_FILTER_KEYS` from canonical_filters (i.e. `{"paper_id": canonical_filters["paper_id"]}`),
so unsupported keys don't appear in `filters_applied` (they appear in `filter_warnings`
already).

### `search_papers_result.json` — the JSON Schema (at repo root `server/schemas/`)

Current state at v8 (`$id`: `.../v8.json`):
- `"additionalProperties": false` at the **top level** (envelope level).
- `"version": 8` — must equal `server.tools.TOOL_SCHEMA_VERSION` (pinned by
  `tests/test_snippet_contract.py::TestSchemaVersionPin`).
- `filters_applied` is NOT in the schema's `properties` dict.
- `degraded` is also NOT in the schema — it's conditionally emitted, and the test
  fixture (`warm_app`) does not trigger degraded mode, so
  `test_schema_validates_real_search_response` passes today.

**CRITICAL FINDING: Adding `filters_applied` to the payload WILL break
`test_schema_validates_real_search_response` unless `filters_applied` is declared in
the JSON schema OR the field is only emitted when `filters` is non-None and the test
does not pass filters.** The test calls `_search(warm_app, k=3)` with no filters
argument. Checking `_search` fixture behavior:

If `filters_applied` is emitted as `None` or absent when no filters are passed
(per AC #2: "absent or null"), and the test's `_search` uses no filters, the schema
validation test passes without schema changes. However, if the test ever calls with
filters, it would fail. The safest path: declare `filters_applied` in the JSON schema
as `{"type": ["object", "null"]}` so it validates in both cases.

### `tests/test_snippet_contract.py` — does it pin bytes via SHA?

No SHA hash of `search_papers_result.json` bytes is pinned in `test_snippet_contract.py`.
The file references the schema at `SCHEMA_PATH` but does NOT compute `sha256()` on the
file bytes. The binding tests are:
1. `TestSchemaVersionPin::test_schema_version_matches_tool_schema_version` — asserts
   `schema["version"] == TOOL_SCHEMA_VERSION`.
2. `TestSchemaConformance::test_schema_validates_real_search_response` — runs jsonschema
   `validate(instance=sc, schema=schema)`. Since the top-level schema has
   `additionalProperties: false`, any field in the live response not in `properties` fails.

**Conclusion:** m2 must add `filters_applied` to the JSON schema's `properties` dict.
Because the schema `version` must equal `TOOL_SCHEMA_VERSION`, and `TOOL_SCHEMA_VERSION`
was bumped to 8 by m1's rect, m2 requires ANOTHER bump: schema → v9,
`TOOL_SCHEMA_VERSION` → 9, and re-pinning of `EXPECTED_TOOL_SCHEMA_SHA256` and
`EXPECTED_BP1_SHA256`. This contradicts AC #4 ("tests/test_server_tool_schema.py
continues to pass — output payload is not in the BP1-hashed surface").

**Flag: AC #4 is WRONG.** The BP1 hash IS tied to `TOOL_SCHEMA_VERSION` via the
`_meta` field on each tool (`"tool_schema_version": TOOL_SCHEMA_VERSION`). Bumping
`TOOL_SCHEMA_VERSION` (required by `TestSchemaVersionPin`) will drift `EXPECTED_BP1_SHA256`.
The AC claim that "output payload is not in the BP1-hashed surface" is technically true
for payload content — but `TOOL_SCHEMA_VERSION` flows into tool `_meta`, which IS in BP1.

### `CHANGES.md` current state

The file opens with `## Unreleased` at line 14. There is NO "proof-verify-handler-wiring"
epic header anywhere in the file — m6 shipped notebook scaffolding but never added a
CHANGES.md entry. m2 must introduce the first "proof-verify-handler-wiring" header
(or add under "Unreleased" — see recommendation).

### `envelope()` alphabetical sort

Per `server/tools.py:310-318` verbatim: "sorts the dict alphabetically (BP1
byte-stability)." `_sort_dict` applies to the full payload. `filters_applied` (if
included) will be sorted between `filter_warnings` and `next_cursor`.

---

## Prior decisions and lessons

### m1 rect precedent for version bumping

m1's rect commit `5838d4b` bumped `TOOL_SCHEMA_VERSION` 7→8, re-pinned
`EXPECTED_TOOL_SCHEMA_SHA256` via `pytest --update-tool-schema-hash`, re-pinned
`EXPECTED_BP1_SHA256` in `tests/test_prompts.py:619`, and bumped
`search_papers_result.json` version 7→8 + `$id`. The reason was a Field description
change (not output shape change). m2's change IS an output shape change, so the same
chain applies with even stronger justification.

### `degraded` is a precedent for NOT declaring optional fields in the schema

The `degraded` field is conditionally emitted by the handler but NOT in the JSON schema.
This works because the test fixture doesn't trigger degradation. m2 could follow the
same pattern for `filters_applied` (omit from schema, only emit when non-null, rely on
test fixture not passing filters) — but this leaves a gap where schema validation
would silently fail if a future test ever passes filters. The cleaner approach is to
declare `filters_applied` as `{"type": ["object", "null"]}` in the schema.

### Filter warnings use canonical_filters variable

Per m1's F4 rect comment in `5838d4b`: "Original `filters` is preserved for the
filter_warnings reflection block (caller ordering preserved)." The `filter_warnings`
already uses `set(filters)` (the original, not canonical). For `filters_applied`, the
implementer should use `canonical_filters` — the variable already exists in scope at
payload construction time.

---

## External sources

The MCP spec (2025-06-18) confirms: arXMCP does NOT register an `outputSchema` in the
tool definition at the MCP protocol level. The spec says "If an output schema is
provided: Servers MUST provide structured results that conform to this schema." Since
we do not declare `outputSchema` in the MCP tool registration, the spec places NO
constraint on additional payload fields from the protocol perspective. The binding
constraint is purely project-internal: `test_schema_validates_real_search_response`.

---

## Recommendation

**Implement `filters_applied` as a canonical-form echo, declare it in the JSON schema,
and bump TOOL_SCHEMA_VERSION 8→9 with a full hash re-pin chain.**

Concretely:

1. In `server/handlers/search.py`, add to the `payload` dict:
   ```python
   "filters_applied": {
       k: canonical_filters[k]
       for k in SUPPORTED_FILTER_KEYS
       if canonical_filters is not None and k in canonical_filters
   } if canonical_filters is not None else None,
   ```
   This echoes only the honored keys in canonical (sorted) form. When no filters, emits
   `None`. Fits alphabetically between `filter_warnings` and `next_cursor`.

2. In `server/schemas/search_papers_result.json`:
   - Bump `"version"` to `9` and `"$id"` to `.../v9.json`.
   - Add `"filters_applied"` to `"properties"` as:
     ```json
     "filters_applied": {
       "description": "Echo of the filter actually honored by this call (canonical form). Absent or null when no filters were passed. Only contains keys from SUPPORTED_FILTER_KEYS (currently: paper_id). The paper_id list is sorted and coerced to list[str] per _canonicalize_filters.",
       "type": ["object", "null"]
     }
     ```
   - Do NOT add to `"required"` (it's optional/conditional).

3. In `server/tools.py`, bump `TOOL_SCHEMA_VERSION` from `8` to `9`.

4. Re-pin `EXPECTED_TOOL_SCHEMA_SHA256` via `pytest --update-tool-schema-hash`.

5. Re-pin `EXPECTED_BP1_SHA256` in `tests/test_prompts.py:619`.

6. Add to `CHANGES.md` under `## Unreleased`, a new subsection:
   ```
   ### proof-verify-handler-wiring (in progress)
   - **m1** — paper_id filter wiring: `filters={"paper_id":[...]}` now scopes LanceDB
     ANN query via `.where()` predicate. `retrieval_mode` stays `"dense_only"` (filters
     narrow the candidate scope, not the pipeline phase).
   - **m2** — `filters_applied` echo field in `search_papers` payload; downstream agents
     can verify scoping without re-parsing filter_warnings.
   ```

Use canonical (sorted, coerced-to-list) form for the echo, NOT the original caller
form. Reasoning: the echo should represent what the server actually applied; the
canonical form is the cache key form; using caller form would create an inconsistency.

---

## Open questions

**AC #4 conflict with TOOL_SCHEMA_VERSION bump:** The brief states "tests/test_server_tool_schema.py
continues to pass — output payload is not in the BP1-hashed surface." This is a
misleading claim. While the payload content itself is not in BP1, `TOOL_SCHEMA_VERSION`
flows into tool `_meta` which IS in BP1. The implementer MUST bump `TOOL_SCHEMA_VERSION`
to satisfy `TestSchemaVersionPin` (which checks `schema["version"] == TOOL_SCHEMA_VERSION`),
and that bump will drift `EXPECTED_BP1_SHA256`. AC #4 should be read as "the payload
CONTENT is not hashed" — not that no hash re-pinning is needed.

**Recommendation:** treat AC #4 as satisfied once `EXPECTED_TOOL_SCHEMA_SHA256` and
`EXPECTED_BP1_SHA256` are both re-pinned. No open question blocks implementation.

No other open questions — implementation can proceed on the above recommendation.

---

## External writes the implementation will require

None — this milestone is purely local. Changes: `server/handlers/search.py`,
`server/schemas/search_papers_result.json`, `server/tools.py`,
`tests/test_server_tool_schema.py` (hash re-pin), `tests/test_prompts.py` (BP1 re-pin),
`CHANGES.md`. All local. No git push, no GitHub issue, no infra mutation required.
