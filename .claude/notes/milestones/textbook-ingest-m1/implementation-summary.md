# Implementation Summary — textbook-ingest-m1

**One-line.** Extended the canonical identifier regexes in
`ingest/identifiers.py` to accept the new `textbook:<slug>` paper_id
and `textbook:<slug>:<16-hex>` chunk_id shapes, closed a second F3-class
`$`→`\Z` bug on `CHUNK_ID_RE`, kept all three copies (chunker, eval-
fixture validator, canonical) in lockstep, and shipped 29 new
identifier tests covering Threat-1 path-traversal injection.

**Commit range.** `461d2a7..<head>` (to be recorded after commit).

---

## Acceptance criteria status

- [x] **AC #1.** Given a valid `textbook:<slug>:<sha>` chunk-id,
      `is_valid_paper_id` returns True for the paper_id form and
      `paper_id_from_chunk_id` returns `textbook:<slug>`.
      Test:
      `tests/test_identifiers.py::TestTextbookIdentifiers::test_paper_id_from_textbook_chunk_id_returns_full_paper_id`
- [x] **AC #2.** ≥5 Threat-1 injection regression tests against the
      composed regex. Shipped: 11 negative tests on
      `is_valid_paper_id` (N1-N11) + 6 negative tests on
      `is_valid_chunk_id` (C1-C6) — 17 path-traversal regression
      tests total, vs ≥5 required.
- [x] **AC #3.** Existing arXiv chunk-id behavior byte-identical.
      Tests:
      `test_arxiv_chunk_id_still_valid_after_m1`,
      `test_paper_id_from_arxiv_chunk_id_unchanged`,
      `test_chunker_pattern_equals_canonical`,
      `test_validator_pattern_equals_canonical`,
      `test_chunk_id_pattern_contains_each_alternative`,
      `test_schema_chunk_id_pattern_matches_canonical`.
- [x] **AC #4.** `ruff check .` clean and the project test suite
      green. 2750+ tests passing. Three failures
      (`TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines`,
      `TestIntegrationRealLatexmlc::test_render_fixture_does_not_leave_log_artifact`,
      `TestToolsSmoke::test_cite_neighbors_wired`) are **pre-existing
      environmental issues** unrelated to m1 (`latexmlc` SIGABRT-class
      crashes on `align.tex` / `frac.tex`; local Kùzu graph file
      state). Verified by `git stash` + re-run on the pre-m1 tree:
      same three failures reproduce.
- [x] **AC #5.** No changes to chunks schema or LanceDB writer.
      `ingest/schema.py` and `ingest/store.py` untouched. The JSON
      Schema at `server/schemas/search_papers_result.json` was
      updated only to mirror the canonical `CHUNK_ID_PATTERN` (single-
      source-of-truth invariant; this is the search-result envelope,
      not the chunks-table column schema).

---

## Files changed

1. **`ingest/identifiers.py`** (+44, -23) — added textbook alternative
   to `_PAPER_ID_FULL_PATTERN` and `PAPER_ID_PATTERN`; restructured
   `CHUNK_ID_PATTERN` to handle dual-prefix chunk-ids with positional
   capture groups and a load-bearing `(?:...)` wrapper; fixed
   `CHUNK_ID_RE` to use `\Z` not `$` (F3 bug class); updated
   `paper_id_from_chunk_id` to return the right group; updated module
   docstring + `is_valid_paper_id` docstring.

2. **`ingest/chunker.py`** (+8, -3) — added textbook alternative to
   `_PAPER_ID_RE` in lockstep with canonical pattern (byte-equality
   lock). Comment notes chunker never PRODUCES textbook paper_ids in
   m1 — the sync is required by the test invariant.

3. **`tools/validate_eval_fixtures.py`** (+10, -3) — same textbook
   alternative + lockstep sync; folded the parallel F3 fix
   (`$`→`\Z`) onto `_CHUNK_ID_RE` as defense-in-depth (validator runs
   on curated input; not a runtime path-traversal surface).

4. **`server/schemas/search_papers_result.json`** (+1, -1) — mirrored
   the new `CHUNK_ID_PATTERN` into the result-row schema. Description
   field updated to reference the dual-prefix shape and the single-
   source-of-truth lock. Pattern uses ECMA-262-compatible
   non-capturing groups (`(?:v\d+)?`) so the schema doubles as
   documentary + machine-validatable.

5. **`tests/test_identifiers.py`** (+187, -3) — relaxed the literal-
   substring assertion (`PAPER_ID_PATTERN in CHUNK_ID_PATTERN`) to
   per-alternative containment with v-suffix-capturing-form
   normalization (`test_chunk_id_pattern_contains_each_alternative`);
   added `TestTextbookIdentifiers` with 9 positive cases (including
   round-trip + byte-stability for arXiv shapes) + 11 negative
   path-traversal cases on `is_valid_paper_id` + 6 negative path-
   traversal cases on `is_valid_chunk_id` + 1 explicit ValueError
   test on `paper_id_from_chunk_id`.

**Test delta:** +29 new tests in `tests/test_identifiers.py`
(`TestTextbookIdentifiers` class, 28 methods, plus the new
`test_chunk_id_pattern_contains_each_alternative` replacing the
substring test). `tests/test_snippet_contract.py` unchanged in count;
its `test_schema_chunk_id_pattern_matches_canonical` continues to
pass against the updated schema and canonical.

---

## Deviations from the brief

1. **Folded the parallel `$`→`\Z` fix on `CHUNK_ID_RE`** into m1.
   The brief permitted this (it called out the F3 bug class
   explicitly); the synthesis confirmed D4. Defense-in-depth.
2. **Folded the parallel `$`→`\Z` fix on
   `tools/validate_eval_fixtures._CHUNK_ID_RE`** as a no-runtime-impact
   hygiene fix. Same bug class, ≤ 1 char change, no semantic effect
   on curated eval fixtures.
3. **Used positional capture groups** instead of Python-style named
   groups `(?P<…>)` in `CHUNK_ID_PATTERN`. Originally the synthesis
   prescribed named groups; mid-implementation I realized this
   breaks the single-source-of-truth lock against the JSON Schema
   pattern (ECMA-262 named-group syntax differs from Python's). The
   positional form keeps the canonical and schema in byte-lockstep.
4. **Relaxed the `PAPER_ID_PATTERN in CHUNK_ID_PATTERN` substring
   invariant.** The dual-prefix `CHUNK_ID_PATTERN` no longer has the
   PAPER_ID_PATTERN inner as a literal substring (v-suffix
   capturing-vs-non-capturing differences). Replaced with a
   per-alternative containment assertion that normalizes the
   v-suffix form before substring check.
5. **Updated `server/schemas/search_papers_result.json`'s `chunk_id`
   pattern** to mirror the new canonical. Outside the literal m1 brief
   ("identifiers only") but the byte-equality-lock test
   (`test_schema_chunk_id_pattern_matches_canonical`) exists
   specifically to keep them in sync. Not updating the schema would
   have broken that test; the choice was forced.

---

## New / changed test paths

- `tests/test_identifiers.py` (modified — +187 LOC, +29 tests, 1
  existing test renamed/rewritten)
- `tests/test_snippet_contract.py` (unchanged — existing test passes
  against new schema)

---

## External writes required

**None.** Purely local. No `git push`, no PR, no `gh` invocation, no
infra mutation, no external API call. Phase 4 will commit the rect
+ chore commits locally; whether to push is a separate user decision.

---

## Pre-existing failures observed (not from m1)

Recorded for transparency; the milestone is responsible for none of
these:

| Test | Failure | Root cause |
|---|---|---|
| `TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines` | `latexmlc exited -6 on align.tex` | `latexmlc` SIGABRT on this workstation; pre-m1 reproducible |
| `TestIntegrationRealLatexmlc::test_render_fixture_does_not_leave_log_artifact` | `latexmlc exited -6 on frac.tex` | same |
| `TestToolsSmoke::test_cite_neighbors_wired` | Kùzu graph_status `unavailable` (expected `absent`) | Local `var/arxmcp/index/kuzu` directory state; pre-m1 reproducible |

Verified via `git stash` + re-run on the pre-m1 tree: same three
failures, identical messages.

---

## Next milestone hint

`textbook-ingest-m2` ships the LanceDB chunks-schema columns
(`source_kind`, `license`, `chapter`, `page_start`, `page_end`,
`textbook_slug`, `parser_used` enum extension) + the corpus_version
bump. m1's identifier regex is the upstream prerequisite — m2 can
now write textbook-shaped chunk-ids without touching identifier
validation again.

`textbook-ingest-m3` does the BP1 cache-invalidation checkpoint
(`EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` re-pin +
`notebook_kind: "textbook"` field on m6 schema). Note that m1's
schema-pattern update is NOT yet a BP1 surface (the result schema
is not part of the tools/list hash); m3 re-pinning will pick up
any incidental drift then.
