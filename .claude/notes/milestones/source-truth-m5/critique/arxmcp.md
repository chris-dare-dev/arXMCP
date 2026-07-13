# Critique — source-truth-m5 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 60de766..b92fcc7
**Diff stats:** 4 files, +122/-3 LOC
**Critique format version:** 1.0

## Verdict

SHIP. This is a small, correct, well-tested serving-surface change that surfaces
the 5 m2 chunks-schema-v2 fields through `get_chunk`, handles the live `-pdfs`
unmigrated-notebook landmine correctly (`row.get()`, not `row[...]`), and re-pins
the `tools/list` byte-stability hash cleanly. All required gates are empirically
green (test_prompts.py + test_server_tool_schema.py + test_handlers_chunk.py +
the wire-level get_chunk path), and the two findings below are LOW comment/doc
clarity nits that do not block ship.

## Executive summary

- [LOW] The new `chunk.truncated` field (ingest-time provenance) sits alongside
  the serving-time `truncated_for_license` and `body_truncated` flags with no
  disambiguating comment — three distinct "truncated" semantics in one response.
- [LOW] The `_chunk_arrow_v2` / `_chunk_arrow` fixture docstrings claim "26-col" /
  "21-col" but the fixtures actually carry 16 / 11 columns — the counts describe
  the real schema versions, not the fixtures, and read as literal-but-false.
- Axis 1 (cache byte-stability, PRIMARY): CLEAN — hash + version-at-hash both
  re-pinned to 18, consistent, and `test_live_tools_match_pinned_hash` is green;
  GET_CHUNK ToolMeta byte-identical; BP1 (`test_prompts.py`) unaffected + green.
- Axis 8 (test surface): CLEAN — the unmigrated test genuinely exercises column
  ABSENCE (11-col fixture), not merely a null value; abstained-null and
  advisory-license_ref cases both covered.
- Axis 4 (MCP surface): CLEAN — 5 additive backward-compatible fields, no input-
  schema change, no new tool; wire-level null-survival proven by the identical
  `envelope()` path (get_paper null-field wire tests at test_tools_all.py:438).
- Axis 3 (security) / Axis 6 (tier sequencing): CLEAN — `license_ref` is advisory
  and NOT wired into `is_open_access`/`license_truncated` (no premature m4
  cutover); `source_span` is an opaque passthrough string, never re-parsed.

## Findings

**L1 — `chunk.truncated` not comment-disambiguated from the two serving-truncation flags** (LOW)

**Where:** `server/handlers/chunk.py:132`
**Anchor:** `"truncated": row.get("truncated"),`
**What:** The new `chunk.truncated` (ingest-time body-truncation provenance from the m2 column) shares a stem with the top-level `truncated_for_license` (chunk.py:147) and `body_truncated` (set by `enforce_byte_cap`), but has no adjacent comment explaining it is a different, ingest-grained concept.
**Why it matters:** A consuming agent that sees `chunk.truncated: false` could wrongly infer the served `body_text` is complete, when it may still be license-truncated or byte-capped at serving time — three "truncated" meanings coexist in one payload. The milestone brief explicitly asked this be "at least comment-disambiguated."
**Proposed fix:** Add one line above line 132, e.g. `# source-truth-m5: INGEST-time provenance (was the stored body token-capped at chunk time) — distinct from the serving-time truncated_for_license / body_truncated flags below.`
**Regression-guard:** (optional for LOW) none required; a doc-only change.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 8 — test/response-surface clarity

**L2 — Fixture docstrings state column counts the fixtures do not have** (LOW)

**Where:** `tests/test_handlers_chunk.py:68`
**Anchor:** `"""A HYDRATED (26-col) chunks-table Arrow`
**What:** `_chunk_arrow_v2`'s docstring says "HYDRATED (26-col)" and calls `_chunk_arrow` "the UNMIGRATED 21-col case", but the fixtures actually build 16 columns (11 base + 5) and 11 columns respectively — the 26/21 numbers are the real on-disk schema-version sizes, not the synthetic fixtures'.
**Why it matters:** In a repo this precise, a maintainer counting fixture columns against the docstring finds a mismatch and may distrust the fixture or waste time reconciling it. The test logic is correct — only the parenthetical counts mislead.
**Proposed fix:** Reword to reference the schema state rather than a literal count, e.g. "represents the HYDRATED (v2 / 26-col schema) case" and "the UNMIGRATED (pre-v2 / 21-col schema) case — the live `-pdfs` notebooks", making clear the number is the schema's, not the fixture's.
**Regression-guard:** (optional for LOW) none required; a doc-only change.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 8 — test surface

## What was done well

- **The landmine is handled exactly right.** All 5 fields use `row.get(<col>)`, not `row[<col>]` (chunk.py:113,116,128-132), so a chunk served from the 2 live unmigrated `-pdfs` notebooks (2,831 rows, columns structurally absent) degrades to explicit null instead of a KeyError/500. This is a real live-corpus fix, not future-proofing.
- **The unmigrated regression test guards ABSENCE, not just null.** `test_unmigrated_notebook_surfaces_explicit_null` reuses the 11-column `_chunk_arrow` fixture (columns genuinely missing from `arrow.column_names`), so `_arrow_first_row` omits them and `row.get()` → None is exercised against true column-absence — the precise KeyError landmine.
- **The hash re-pin is correct and empirically verified.** Both `EXPECTED_TOOL_SCHEMA_SHA256` (→ 5189d7a6…) and `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` (→ 18) were updated consistently; `pytest tests/test_server_tool_schema.py` is green, which asserts `live_hash == pinned_hash` AND `live_version == pinned_version == 18` — the pin matches the live serialization, not a stale value.
- **Version-driven re-pin, no description drift.** The GET_CHUNK `ToolMeta` description and inputSchema are byte-identical (the diff touches only the `TOOL_SCHEMA_VERSION` constant + changelog comment); the hash moved solely via the `_meta.tool_schema_version` echo on all 8 tools — exactly the v16 precedent.
- **BP1 confirmed unaffected empirically.** `tests/test_prompts.py` is green post-change; `EXPECTED_BP1_SHA256` (hashes only {name, description}) was correctly left untouched — verified, not assumed.
- **`license_ref` is correctly advisory.** It is surfaced as a distinct namespaced field and is NOT wired into `is_open_access`/`license_truncated`; `test_license_ref_is_advisory_not_wired_to_truncation` proves an OA chunk with `license_ref="not-allowlisted-open"` still returns its full body — no premature source-truth-m4 cutover.
- **§4.9 trust discipline honored.** The abstained-`source_span` vs unmigrated-absent null collapse is acknowledged explicitly in a code comment (chunk.py:118-127) rather than silently, and `license_ref` carries the 3-way `license_status` value rather than a bare "verified" token.
- **`source_span` is an opaque passthrough.** The JSON-string column is placed into the response verbatim via `row.get()` and never `json.loads`'d or trusted as structure at serving time — no injection/escaping surface introduced.
- **`server/corpus.py` correctly untouched.** The row read has no `.select()` projection, so surfacing new columns needed zero corpus-layer change — the diff stays a pure handler dict-literal edit + version bump + test re-pin.
- **Alphabetical key ordering preserved** in the `chunk = {...}` literal (license_ref after license, printed_number after preamble_ref, source_* after section_path, truncated after theorem_name), keeping the file-internal convention and matching the schema declaration order.

Severity counts: C0 H0 M0 L2

## Recommended rectification order

L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
