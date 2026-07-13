# Critique — source-truth-m5 — merged (adversary + arxmcp)

**Critic:** milestone-adversary-critic + milestone-arxmcp-critic (orchestrator-merged, id-remapped)
**Commit range:** 60de766..b92fcc7
**Diff stats:** 4 files, 122 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. **C0 H0** — a small, correct, well-tested serving change. Both critics
independently verified the sensitive parts: the `row.get()` landmine is fully defused (the 2 live
unmigrated `-pdfs` notebooks degrade to explicit null, not a 500 — tested against genuine column
ABSENCE); AC1 "explicit null, not omission" holds at the handler dict AND the FastMCP wire;
`license_ref` is airtight-advisory (never wired into serving — tested); the AC2 schema re-pin is
textbook (17→18, both hash + version-at-hash re-pinned, `test_server_tool_schema.py` green, BP1
verified unaffected + green); `source_span` is an opaque passthrough; commits signed + trailered +
one-writer clean. The 3 findings are cheap hardening: a wire-level regression guard, a naming
disambiguation, and a fixture-docstring fix.

## Executive summary

- [MEDIUM] AC1's "explicit null" is pinned only at the handler-dict level; nothing guards it at the wire-serialization boundary, where it rests on `mcp`'s `convert_result` not passing `exclude_none`. A future `mcp` bump could silently drop every nullable field with the suite still green.
- [MEDIUM] The new `chunk.truncated` (ingest-time provenance) collides semantically with the serving-time `truncated_for_license` / `body_truncated` flags — three "truncated" meanings in one response, can disagree in both directions, no disambiguating comment/doc (cross-critic: adversary + arxmcp).
- [LOW] The fixture docstrings say "26-col"/"21-col" but the fixtures build 16/11 columns — the counts are the real schema-version sizes, not the fixtures' (cross-critic: adversary + arxmcp).
- [CLEAN] Axis 1 cache byte-stability, license_ref advisory, wire null-survival, §4.9 abstention-collapse acknowledged in a code comment, corpus.py untouched — all verified.

## Findings

**M1 — AC1 "explicit null" is unguarded at the wire-serialization boundary** (MEDIUM)

**Where:** `tests/test_handlers_chunk.py:273`
**Anchor:** `def test_unmigrated_notebook_surfaces_ex`
**What:** The new tests assert the 5 fields are key-present with value `None` on the handler's return dict, but the AC1 contract is the wire `structuredContent`, whose null-preservation depends on FastMCP `convert_result` calling `model_dump(mode="json", by_alias=True)` WITHOUT `exclude_none` — an external-library default no test in this diff pins.
**Why it matters:** If a future `mcp` upgrade adds `exclude_none=True` (a common JSON-API default), every nullable field — the 5 source-truth fields plus pre-existing `theorem_name`/`preamble_ref` — would silently drop from the wire, violating AC1 with the whole suite still green.
**Proposed fix:** Add one wire-level test (via `app.state.mcp_server.call_tool("get_chunk", ...)` / the `_call_tool` harness in `tests/test_tools_all.py`) seeding an unmigrated (column-absent) chunk, asserting each of the 5 keys is present in `structuredContent["chunk"]` with value `null` after a `json.dumps`/`loads` round-trip. (Verified live: passes today.)
**Regression-guard:** `tests/test_tools_all.py::...::test_get_chunk_source_truth_fields_explicit_null_on_wire`
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M2 — `chunk.truncated` overloads "truncated" against the serving-time flags** (MEDIUM)

**Where:** `server/handlers/chunk.py:132`
**Anchor:** `"truncated": row.get("truncated"),`
**What:** The response now carries `chunk.truncated` — the m2 ingest-time provenance flag (statement text truncated to `STMT_MAX_TOKENS` at chunk time; `ingest/schema.py:250-255`) — alongside the top-level serving-time flags `truncated_for_license` (chunk.py:147) and `body_truncated` (set by `enforce_byte_cap`), with no comment disambiguating the three.
**Why it matters:** The flags can disagree both directions — a non-OA chunk sliced to 300 chars has `truncated_for_license=true` while `chunk.truncated` may be `false`; a long-statement chunk has `chunk.truncated=true` while its served body is complete-as-chunked. An agent reading `chunk.truncated` to judge "is the body I received complete?" is misled — the §4.9 evidence-misread the trust policy exists to prevent. (The milestone brief asked this be "at least comment-disambiguated"; both critics flagged it.)
**Proposed fix:** No behavior change. Add a one-line comment at the field distinguishing ingest-grained provenance from the serving flags, and land the synthesis's deferred `snippet-contract.md` §h addendum stating body completeness is governed solely by the (absent-when-false) `body_truncated`/`truncated_for_license` top-level flags.
**Regression-guard:** optional (doc/comment change).
**Source critic:** milestone-adversary-critic + milestone-arxmcp-critic
**Source axis:** Trust language (§4.9)

**L1 — Fixture docstrings state column counts the fixtures do not have** (LOW)

**Where:** `tests/test_handlers_chunk.py:68`
**Anchor:** `"""A HYDRATED (26-col) chunks-table Arrow`
**What:** `_chunk_arrow_v2`'s docstring says "HYDRATED (26-col)" and calls `_chunk_arrow` "the UNMIGRATED 21-col case," but the fixtures build 16 columns (11 base + 5) and 11 columns respectively — the 26/21 numbers are the real on-disk schema-version sizes, not the synthetic fixtures'.
**Why it matters:** In a repo this precise, a maintainer counting fixture columns against the docstring finds a mismatch and may distrust the fixture; harmless today but latent confusion. The test logic is correct — only the parenthetical counts mislead.
**Proposed fix:** Reword to reference the schema STATE not a literal count, e.g. "the HYDRATED (v2 / 26-col schema) case" and "the UNMIGRATED (pre-v2 schema) case — the 5 source-truth columns absent, the live `-pdfs` notebooks," making clear the number is the schema's, not the fixture's.
**Regression-guard:** optional (comment change).
**Source critic:** milestone-adversary-critic + milestone-arxmcp-critic
**Source axis:** Test hygiene

## What was done well

- **The `row.get()` landmine is fully neutralized** — all 5 fields use `row.get()`; `test_unmigrated_notebook_surfaces_explicit_null` exercises the genuinely column-ABSENT path (the live `-pdfs` notebooks), the exact case that would 500 under bracket-indexing, not just a null value.
- **`license_ref` is airtight-advisory** — grepping `server/` shows it only in the surfaced dict + changelog, never in `is_open_access`/`license_truncated`; a test proves an OA chunk with `license_ref="not-allowlisted-open"` still returns its full body (no premature m4 cutover).
- **§4.9 abstention collapse acknowledged in a code comment** (chunk.py:118-127) rather than silently — unmigrated-absent vs hydrated-but-abstained `source_span` both → null, stated explicitly.
- **AC1 confirmed at the real FastMCP wire level** — `convert_result` preserves all 5 keys as explicit `null` (verified live via `call_tool`).
- **AC2 re-pin is textbook** — version bump + precise v18 changelog, both `EXPECTED_TOOL_SCHEMA_SHA256` (→5189d7a6…) + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` (→18) updated consistently, GET_CHUNK description/inputSchema byte-identical so BP1 stays valid (`test_prompts.py` green + absent from diff).
- **`source_span` is an opaque passthrough** — never `json.loads`'d or trusted as structure at serving time; no injection/escaping surface.
- **`server/corpus.py` correctly untouched** — the row read has no `.select()`, so surfacing new columns needed zero corpus-layer change.
- **Alphabetical key ordering preserved** in the `chunk = {...}` literal; byte-cap/wrap paths untouched.
- **Commit hygiene clean** — GPG-signed (good sig), `Co-Authored-By: Claude Opus 4.8`, conventional subject <50 chars, no one-writer violation.

Severity counts: C0 H0 M2 L1

## Recommended rectification order

M1, M2, L1
