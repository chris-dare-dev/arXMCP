# Critique — source-truth-m5 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 60de766..b92fcc7
**Diff stats:** 4 files, 122 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The milestone is correct and well-tested: all 5 source-truth
fields are surfaced via `row.get()` (no bracket-index 500 landmine), AC1's
"explicit null, not omission" holds at BOTH the handler-dict and the real
FastMCP wire level (empirically confirmed through `call_tool`), `license_ref`
is genuinely advisory (referenced nowhere in serving logic), and AC2's schema
re-pin (17->18, hash + version-at-hash, BP1 unaffected) is green. No CRITICAL
or HIGH findings. Two cheap MEDIUM hardening items remain — a wire-level
regression guard for AC1 and disambiguation of the overloaded `truncated`
field — neither blocks shipping.

## Executive summary

- [MEDIUM] AC1's "explicit null, not omission" is verified only at the handler-dict level; nothing pins it at the wire-serialization boundary, where it silently rests on `mcp`'s `convert_result` not passing `exclude_none`. A future dependency bump could drop every nullable field with zero test failures.
- [MEDIUM] The new `chunk.truncated` (ingest-time statement/STMT_MAX_TOKENS truncation provenance) collides semantically with the top-level serving-time flags `truncated_for_license` / `body_truncated`, can disagree with them in both directions, and ships with no disambiguation doc (the synthesis's optional snippet-contract addendum was skipped).
- [LOW] The `_chunk_arrow_v2` docstring calls the base fixture "the UNMIGRATED 21-col case," but `_chunk_arrow` actually builds an 11-column minimal row — a cosmetic inaccuracy in a comment.
- [OK] The `row.get()` landmine is fully defused: all 5 fields use `row.get()`, and the column-ABSENT (unmigrated-notebook) path is explicitly tested, not just the null-valued path.
- [OK] `license_ref` advisory contract is proven by a test: an OA chunk whose `license_ref="not-allowlisted-open"` still returns its full body.
- [OK] AC2 fully met: `TOOL_SCHEMA_VERSION` 17->18 + v18 changelog, `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned, GET_CHUNK description/inputSchema unchanged, `test_server_tool_schema.py` + `test_prompts.py` green (BP1 untouched, not in diff).
- [OK] Commit is GPG-signed (good sig), carries `Co-Authored-By: Claude Opus 4.8`, subject under 50 chars; one-writer clean (no roadmap.yaml / state.json edit in range).

## Findings

**M1 — AC1 "explicit null" is unguarded at the wire-serialization boundary** (MEDIUM)

**Where:** `tests/test_handlers_chunk.py:273`
**Anchor:** `def test_unmigrated_notebook_surfaces_ex`
**What:** The new tests assert the 5 fields are key-present with value `None` on the handler's return dict, but the actual AC1 contract is the wire `structuredContent`, whose null-preservation depends on FastMCP `convert_result` calling `model_dump(mode="json", by_alias=True)` WITHOUT `exclude_none` (`mcp/server/fastmcp/utilities/func_metadata.py:130`) — an external-library default no test in this diff pins.
**Why it matters:** If a future `mcp` upgrade adds `exclude_none=True` to that dump (a common JSON-API default), every nullable field — the 5 source-truth fields plus pre-existing `theorem_name`/`preamble_ref` — would silently drop from the wire, violating AC1's "explicit null, not omission" with the whole suite still green.
**Proposed fix:** Add one wire-level test using the existing `_call_tool` harness in `tests/test_tools_all.py` (or `app.state.mcp_server.call_tool("get_chunk", ...)`), seeding an unmigrated (column-absent) chunk, and assert each of the 5 keys is present in `structuredContent["chunk"]` with value `null` after a `json.dumps`/`loads` round-trip. (Verified live this passes today: `call_tool` returns `(unstructured, structured)` and all 5 keys survive as `null`.)
**Regression-guard:** `tests/test_tools_all.py::TestToolsSmoke::test_get_chunk_source_truth_fields_explicit_null_on_wire`
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M2 — `chunk.truncated` overloads "truncated" against the serving-time flags** (MEDIUM)

**Where:** `server/handlers/chunk.py:132`
**Anchor:** `"truncated": row.get("truncated"),`
**What:** The response now carries `chunk.truncated` — the m2 ingest-time provenance flag (statement text truncated to `STMT_MAX_TOKENS` at embed time; see `ingest/schema.py:250-255`) — sitting alongside the top-level serving-time flags `truncated_for_license` (line 147) and `body_truncated` (set by `enforce_byte_cap`), with no comment or doc disambiguating the three.
**Why it matters:** The flags can disagree in both directions — a non-OA chunk sliced to 300 chars has `truncated_for_license=true` while `chunk.truncated` may be `false`, and a long-statement chunk has `chunk.truncated=true` while its served body is complete-as-chunked — so a consuming agent that reads `chunk.truncated` to judge "is the body I received complete?" is misled, exactly the kind of evidence-misread the §4.9 trust-language policy exists to prevent.
**Proposed fix:** No behavior change. Add a one-line code comment at the field distinguishing it from the serving flags, and land the synthesis's deferred snippet-contract §h addendum stating that `chunk.truncated` is ingest-grained provenance and that body completeness is governed solely by the (absent-when-false) `body_truncated` / `truncated_for_license` top-level flags.
**Regression-guard:** optional (doc/comment change).
**Source critic:** milestone-adversary-critic
**Source axis:** Trust language (§4.9)

**L1 — Fixture docstring mislabels the 11-col base fixture as "21-col"** (LOW)

**Where:** `tests/test_handlers_chunk.py:70`
**Anchor:** `UNMIGRATED 21-col case — the live`
**What:** `_chunk_arrow_v2`'s docstring describes `_chunk_arrow` as "the UNMIGRATED 21-col case," but `_chunk_arrow` builds only 11 columns; it represents a subset of the pre-v2 schema, not a literal 21-column row.
**Why it matters:** A future reader trusting the comment may believe the fixture reproduces the full unmigrated schema shape when it is a minimal stand-in; harmless today but a latent source of confusion if the fixture is reused.
**Proposed fix:** Reword to "the UNMIGRATED (pre-v2) case — the 5 source-truth columns absent" and drop the specific column count, or note it is a minimal subset.
**Regression-guard:** optional (comment change).
**Source critic:** milestone-adversary-critic
**Source axis:** Test hygiene

## What was done well

- The `row.get()` landmine is fully neutralized: every one of the 5 fields uses `row.get()`, and `test_unmigrated_notebook_surfaces_explicit_null` exercises the genuinely column-ABSENT path (the live `-pdfs` notebooks) — the exact case that would 500 under bracket-indexing — not merely a null-valued column.
- `license_ref` is airtight-advisory: grepping `server/` shows it only in the surfaced dict + changelog prose, never in `is_open_access`/`license_truncated`, and `test_license_ref_is_advisory_not_wired_to_truncation` proves an OA chunk with `license_ref="not-allowlisted-open"` still returns its full body.
- The §4.9 abstention collapse (unmigrated-absent vs hydrated-but-abstained `source_span` both surfacing as bare `null`) is explicitly acknowledged in a code comment (chunk.py:122-127) rather than silently pretended away, matching the synthesis decision.
- AC1 was independently confirmed to hold at the real FastMCP wire level, not just the handler dict — `convert_result` returns structured content and preserves all 5 keys as explicit `null`.
- AC2 schema re-pin is textbook: version bump + a precise v18 changelog entry, both the SHA256 and the version-at-hash anchors updated, and the GET_CHUNK ToolMeta description/inputSchema left byte-identical so BP1 stays valid (verified: `test_prompts.py` green and absent from the diff).
- The v18 changelog comment and commit body correctly predict which pins move (`EXPECTED_TOOL_SCHEMA_SHA256` yes, `EXPECTED_BP1_SHA256` no) and cite the v16 precedent — accurate, not aspirational.
- `source_span` is handled correctly as an opaque server-computed JSON string: passed through un-re-parsed, so there is no double-encoding or trust-elevation concern, and leaving it unwrapped is consistent with the existing unwrapped-metadata convention (`section_path`, `chunk_id`).
- Field ordering in the dict literal is alphabetical, consistent with the `_sort_dict` envelope discipline, and the byte-cap/wrap paths are untouched (the 5 small fields never interact with `_truncate_at_path`, which only touches `("chunk","body_text")`).
- Commit hygiene is clean: GPG-signed with a good signature, `Co-Authored-By: Claude Opus 4.8` trailer, conventional `feat(server):` subject under 50 chars, and no one-writer violation (no roadmap.yaml/state.json edits in range).

Severity counts: C0 H0 M2 L1

## Recommended rectification order

M1, M2, L1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
