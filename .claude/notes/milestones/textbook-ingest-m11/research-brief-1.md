# Research Brief — textbook-ingest-m11

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T18:00:00Z

## In-codebase context

### Design constitution applicability

- `07-multi-agent-caching.md`: BP1 = `{"system": SYSTEM_PROMPT, "tools": _live_tools_payload()}`. The tools payload is `[{"name": t.name, "description": t.description} for t in ALL_TOOLS]`. A GET_CHUNK ToolMeta description change drifts BP1 + EXPECTED_TOOL_SCHEMA_SHA256. m11 does NOT change any tool description (it changes only the result envelope), so BP1 stays stable — but EXPECTED_TOOL_SCHEMA_SHA256 WILL drift if TOOL_SCHEMA_VERSION is bumped (the `_meta.tool_schema_version` appears in the tools/list wire response). The m9 implementation-summary §Deviation is the authoritative lesson: "widening the SEARCH_PAPERS ToolMeta description drifts BP1 in LOCKSTEP with EXPECTED_TOOL_SCHEMA_SHA256. Both must be re-pinned." m11's case is DIFFERENT: GET_CHUNK description is unchanged; only the result-envelope grows `truncated_for_license`. TOOL_SCHEMA_VERSION bump changes only `_meta.tool_schema_version` in the wire tools/list; that drifts EXPECTED_TOOL_SCHEMA_SHA256 but NOT BP1 (BP1 hashes `{name, description}` only, not `_meta`).

- `06-mcp-server-design.md`: 7-tool surface (now 8 with lean_verify). No new tool added. Result-envelope fields are outside the schema hash surface.

- `08-security-observability-ops.md` §Threat 2 (E13_S02): Every retrieved chunk body is wrapped with `<retrieved_chunk>` delimiters AFTER truncation so the delimiter tags are not sliced. m11 inserts INNER-body license-truncation BEFORE the delimiter wrap. See precise ordering below.

### `server/handlers/chunk.py` — exact execution ordering

Current flow (lines 69–125):
1. `raw_body = row["body_text"] or ""` (line 74)
2. `sanitized_body = sanitize_retrieved_text(raw_body)` (line 75)
3. Build `chunk = {..., "body_text": sanitized_body, ...}` (lines 76–87) — does NOT read `license` column
4. `enforce_byte_cap(payload, chunk_id, body_text_path=("chunk", "body_text"))` (lines 100–104)
5. `wrap_retrieved_text(structured["chunk"]["body_text"], kind="chunk")` (lines 113–115)

**m11 must insert license-truncation between steps 3 and 4.**

**Current gap**: `chunk.py::handle_get_chunk` does NOT read the `license` column from the Arrow row. The row dict is built at lines 76–87 without `license`. m11 must add `row["license"] or ""` to the row read and apply `is_open_access(license)` to decide whether to truncate `sanitized_body` to 300 chars before constructing `chunk`.

**Precise insertion point**: After `sanitized_body = sanitize_retrieved_text(raw_body)` (line 75) and BEFORE building `chunk` dict (line 76), the implementer should:
```python
license_val = row.get("license") or ""
if not is_open_access(license_val):
    if len(sanitized_body) > LICENSE_TRUNCATION_CHARS:
        sanitized_body = sanitized_body[:LICENSE_TRUNCATION_CHARS]
        license_truncated = True
    else:
        license_truncated = False
else:
    license_truncated = False
```
Then set `chunk["truncated_for_license"] = license_truncated`. This:
- (a) bounds INNER body to ≤300 chars for non-OA
- (b) happens before `wrap_retrieved_text` so delimiters wrap the already-truncated body
- (c) happens before `enforce_byte_cap` so a non-OA chunk can NEVER surface >300 chars even via the resource_link/byte-cap path (byte-cap truncates to 1024; license truncation to 300 fires first)

**`truncated_for_license` future-flag verbatim quotes:**
- `ingest/chunker_types.py:129`: `"Documentary at m2; enforcement of ``truncated_for_license`` flag lands with e5."`
- `ingest/schema.py:165`: `"``truncated_for_license`` snippet truncation enforcement lands with textbook-ingest-e5."`
- `plans/textbook-ingest-roadmap.md:43`: `"[SHOULD] License truncation policy (300 chars + truncated_for_license: true flag) is acceptable to operator for non-OA chunks."`

**`truncated_for_license` is NOT a schema column**. It is a runtime flag in the result envelope only. No LanceDB schema change required.

### `server/schemas/` — no get_chunk result schema exists

There is NO `server/schemas/get_chunk_result.json` file. Only `search_papers_result.json` (version 15) and `lean_verify_result.json` (version 15) exist. The get_chunk handler returns `envelope(structured)` with no separate JSON Schema file. This means:
- m11 adds `truncated_for_license` to the result envelope with no JSON Schema to update
- `TOOL_SCHEMA_VERSION` must be bumped (currently 15 → 16) to signal the result-shape change
- `EXPECTED_TOOL_SCHEMA_SHA256` re-pin required (because `_meta.tool_schema_version` in wire tools/list changes)
- Both `search_papers_result.json` and `lean_verify_result.json` `version` fields must be bumped (16) as they echo `TOOL_SCHEMA_VERSION`
- `EXPECTED_BP1_SHA256` NOT affected (GET_CHUNK description unchanged; BP1 hashes `{name, description}` only)

### `search_papers` snippets — license column not read

`server/handlers/search.py::_arrow_to_rows` reads columns: `chunk_id`, `paper_id`, `section_path`, `theorem_name`, `theorem_label`, `body_text`, `_distance`, `source_kind`. The `license` column is NOT read. The `_snippet` helper truncates to 150 chars (already under 300). The brief's "research should decide" on whether non-OA search snippets should also carry `truncated_for_license`:

**Recommendation**: DO add `truncated_for_license` to search_papers result rows for transparency, but the flag value is informational only (150 chars is under 300 so `body_text` is never actually truncated further). This requires reading `license` from the Arrow result, applying `is_open_access`, and setting `truncated_for_license=true` if `is_open_access==False` — even though the 150-char snippet is not further truncated. The flag signals to agents that full body retrieval via `get_chunk` will be truncated. This requires adding `license` to `_arrow_to_rows`, updating `search_papers_result.json` with `truncated_for_license: boolean` per row, and updating the snippet-contract doc.

**Conflict flag**: The brief says "research to decide." The `search_papers` schema (`server/schemas/search_papers_result.json`) tracks `TOOL_SCHEMA_VERSION` in its `version` and `$id` fields. Adding a `truncated_for_license` per-row field to `search_papers_result.json` IS a result-shape change that version bump must reflect (already being bumped for TOOL_SCHEMA_VERSION 15→16). But ADDING it to the per-row shape means the schema's `required` array may or may not include it. Recommendation: make `truncated_for_license` optional (not in `required`) in `search_papers_result.json` so older clients are unaffected.

### `server/tools.py` — current TOOL_SCHEMA_VERSION

`TOOL_SCHEMA_VERSION: int = 15` (line 147). The comment trail shows:
- v14: textbook-ingest-m9 (SEARCH_PAPERS description edit for source_kind)
- v15: textbook-ingest-m9 rectification (filters inputSchema Field description fix)

m11 bumps to v16. GET_CHUNK description is unchanged; the bump reflects the result-envelope shape change.

### `is_open_access` helper — placement

No `is_open_access` or license allowlist exists anywhere in the codebase. m11 must define it. Recommended location: `server/licensing.py` (new file, small). This keeps it importable by both `chunk.py` and (if the brief's search_papers flag is implemented) `search.py` without creating a circular import.

### Known license tier values from the codebase and milestone brief

From `ingest/chunker_types.py:114–128` and the milestone brief:
- Open-access: `"arxiv-license"`, `"CC-BY"`, `"CC-BY-SA"`, `"CC0"`, `"public-domain"`, `"GFDL"`
- Non-OA (truncate): `"author-distributed"`, `"copyrighted"`, `""` (empty), `None`/`NULL`
- `"no explicit license"`: non-OA (fail closed)

The `ingest/schema.py:165` comment confirms: `"license is free-text — domain is documentary, not validated."` No enforcement exists at write time. Fail-closed policy on unrecognized/empty values is load-bearing.

## Prior decisions and lessons

**m9 implementation-summary §Deviation (critical):**
> "The synthesis (following BOTH researchers) claimed EXPECTED_BP1_SHA256 was UNAFFECTED. That was wrong. BP1 hashes the byte-region 'system prompt + live ALL_TOOLS' so widening the SEARCH_PAPERS ToolMeta description drifts BP1 in LOCKSTEP with EXPECTED_TOOL_SCHEMA_SHA256."

m11's lesson from m9: since m11 does NOT change any ToolMeta description (GET_CHUNK description stays the same), BP1 is truly unaffected this time. The `_live_tools_payload()` in `test_prompts.py:464` returns `[{"name": t.name, "description": t.description} for t in ALL_TOOLS]` — no `_meta`, no inputSchema. Only a description change drifts BP1.

**Re-pin scope for m11 (firm):**
- `TOOL_SCHEMA_VERSION`: 15 → 16 (bump required — result-shape change is convention)
- `EXPECTED_TOOL_SCHEMA_SHA256`: re-pin (because `_meta.tool_schema_version` in wire tools/list changes)
- `EXPECTED_BP1_SHA256`: NO re-pin (GET_CHUNK description unchanged)
- `search_papers_result.json["version"]`: 15 → 16 (global echo of TOOL_SCHEMA_VERSION)
- `lean_verify_result.json["version"]`: 15 → 16 (global echo of TOOL_SCHEMA_VERSION)

**m9 memory entry**: TWO copies of `SUPPORTED_FILTER_KEYS` (bm25.py + search.py). m11 does NOT touch filter keys, so this is not a concern.

**assert banned**: `if … raise RuntimeError(…)` required throughout.

**`BaseHTTPMiddleware` banned**: m11 adds no middleware, no concern.

**macOS segfault guard**: `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` — m11 does not touch conftest.py.

**Recent git log**: Latest commit `a7da3f0` closes textbook-ingest-m10 (doc pass). m10 state is `complete`. m11 is the last milestone; closes e5 and the textbook-ingest epic.

## External sources

The OA-allowlist policy aligns with standard copyright semantics:
- `CC-BY`, `CC-BY-SA`, `CC0` (Creative Commons): explicitly permit redistribution with attribution.
- `public-domain`: no copyright restriction.
- `GFDL` (GNU Free Documentation License): permits redistribution in modified and unmodified form. Used by Stacks Project.
- `arxiv-license` (arXiv non-exclusive distribution license): permits ArXiv to distribute but does NOT grant downstream redistribution rights. The arXiv license page states it grants only "non-exclusive and irrevocable license to distribute." This is borderline. However, since arXiv is the intended use-case corpus and the project's seed corpus is 100% arXiv, classifying `arxiv-license` as open-access preserves existing behavior (no truncation regression for existing corpus). The brief explicitly lists it in the recommended allowlist.
- `author-distributed` / `no explicit license` / empty: no redistribution rights. Must truncate.

No MCP spec changes relevant to m11 — the `CallToolResult` shape (`structuredContent` + `content` blocks) is unchanged. No external sources needed for this milestone.

## Recommendation

**Implement license-truncation in `get_chunk` and add informational flag to `search_papers` snippets.**

1. Create `server/licensing.py` with `is_open_access(license: str | None) -> bool` and `LICENSE_TRUNCATION_CHARS = 300`. OA allowlist: `{"arxiv-license", "CC-BY", "CC-BY-SA", "CC0", "public-domain", "GFDL"}` (exact-string match, case-sensitive, fail-closed: anything not in the set → non-OA).

2. In `server/handlers/chunk.py`, insert license truncation between the `sanitize_retrieved_text` call (line 75) and the `chunk` dict construction (starting line 76). Read `license` from the Arrow row; apply `is_open_access`; truncate `sanitized_body` to 300 chars and set `license_truncated = True` if non-OA. Add `"truncated_for_license": license_truncated` to the `chunk` dict.

3. In `server/handlers/search.py::_arrow_to_rows`, read `license` from the Arrow result (same defensive pattern as `source_kind` — check `"license" in arrow.schema.names`), apply `is_open_access`, and add `"truncated_for_license": not is_open_access(license_val)` to each row. The 150-char snippet content is never further truncated (already under 300).

4. Bump `TOOL_SCHEMA_VERSION` 15 → 16. Re-pin `EXPECTED_TOOL_SCHEMA_SHA256`. DO NOT re-pin `EXPECTED_BP1_SHA256`. Bump `search_papers_result.json` and `lean_verify_result.json` version fields to 16 (global echo). Add `truncated_for_license` as an optional boolean property to `search_papers_result.json` result item schema.

5. Update `.claude/docs/snippet-contract.md` §(f) to document the license-truncation policy and `truncated_for_license` flag.

6. Tests: `is_open_access` unit tests (every allowlist member, empty, None, unknown, case variants); `get_chunk` truncation tests (OA chunk full body, non-OA chunk ≤300 chars + flag, unknown/empty → truncate, composes with byte-cap: non-OA body never exceeds 300 via byte-cap path); `search_papers` flag tests (non-OA row has `truncated_for_license=true`, OA row has `false`).

**Rationale for `server/licensing.py`**: avoids circular imports; gives the helper a clear home that is importable by any handler; keeps `chunk.py` and `search.py` from each defining their own allowlist copy.

**The OA policy is safe to ship as documented default.** The roadmap `[SHOULD]` assumption (`plans/textbook-ingest-roadmap.md:43`) says it is "acceptable to operator." The fail-closed posture (unknown → truncate) is conservative and matches user expectations for copyright compliance. No operator sign-off required beyond what the roadmap already captures.

## Open questions

No open questions — implementation can proceed on the above recommendation.

## External writes the implementation will require

None — this milestone is purely local.
