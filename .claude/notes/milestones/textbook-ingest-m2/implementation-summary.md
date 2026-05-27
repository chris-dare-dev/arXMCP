# Implementation Summary — textbook-ingest-m2

**One-line.** Added 7 textbook-aware columns to `CHUNKS_SCHEMA_V1`
(now 21 cols), extended `ChunkRecord` + `_build_arrow_table` to
populate them, added an in-place schema-migration guard for pre-m2
chunks tables, and shipped 9 new round-trip / migration / enum-guard
regression tests. NO MCP surface or BP1 changes (m3's job).

**Commit base.** `8804544` (after the parallel
`embedder-truncation-m1` family landed). Note: my `ingest/schema.py`
and `ingest/chunker_types.py` edits were absorbed into the
`embedder-truncation-m1` rect commit (26c04fa) while the working
tree was mixed; m2's `feat` commit therefore carries only the
remaining writer + migration + tests + docs deltas.

---

## Acceptance criteria status

- [x] **AC #1.** Given a textbook chunk with `source_kind=textbook`,
      When written then read, Then all 6 new columns survive round-
      trip with correct types.
      Test: `tests/test_store.py::TestTextbookChunkRoundtrip::test_textbook_chunk_all_columns_survive_roundtrip`
      Verifies all 7 m2 columns (the 6 from the brief + `parser_used`
      promoted from `PaperOutcome` per synthesis D2).
- [x] **AC #2.** Given an existing arXiv chunk, When read after the
      schema bump, Then all new columns are present with the
      documented defaults and existing fields are byte-identical.
      Tests:
      `TestArxivChunkByteStableAfterSchemaBump::test_arxiv_chunk_defaults_populated_via_chunkrecord`
      (new writes get `source_kind="arxiv"` / `license="arxiv-license"`
      via ChunkRecord defaults);
      `TestSchemaMigrationGuard::test_migration_adds_seven_columns_with_arxiv_defaults`
      (legacy 14-col rows get the same defaults via SQL backfill —
      FM-6 mitigation).
- [x] **AC #3.** Given the chunks table at `corpus_version=N`,
      When the bump lands, Then the new version is `N+1` and existing
      tests pinning corpus_version are updated in lockstep.
      Verified: corpus_version is emergent from LanceDB MVCC integers
      (per synthesis D6 + R1's brief); no constants pinning specific
      integers needed updates. Existing `tests/test_corpus_version.py`
      tests assert increment semantics only and continue to pass.
- [x] **AC #4.** `.claude/docs/snippet-contract.md` updated to
      document the new columns (snippet-rendering semantics unchanged
      for textbook chunks — `truncated_for_license` flag NOT enforced
      yet; e5's job). Section (f) added.
- [x] **AC #5.** `make test` green; chunker tests + chunk-id round-
      trip + LanceDB merge-insert tests passing. 2787 tests passed,
      26 skipped, 1 xfailed. Six pre-existing environmental failures
      verified via `git stash` reproduction (3 parser-fidelity-fixture-
      dir-missing + 2 `latexmlc` SIGABRT + 1 `cite_neighbors` Kùzu
      state).

---

## Files changed in m2 feat commit

The schema + ChunkRecord + test column-count delta was captured by
`embedder-truncation-m1`'s rect commit (26c04fa) while the working
tree was mixed during the parallel sessions. The m2 feat commit
carries only the remaining work:

1. **`ingest/store.py`** (+92, -2)
   - Added `_ALLOWED_SOURCE_KINDS = frozenset({"arxiv", "textbook"})`
     and a runtime guard in `_build_arrow_table` against
     `source_kind` typos.
   - Extended the row-dict in `_build_arrow_table` to populate the 7
     m2 columns from `ChunkRecord` attributes
     (`chunk.source_kind`, `chunk.license`, `chunk.chapter`,
     `chunk.page_start`, `chunk.page_end`, `chunk.textbook_slug`,
     `chunk.parser_used`).
   - New `_TEXTBOOK_MIGRATION_DEFAULTS` dict of SQL expressions for
     in-place column additions.
   - New `_migrate_chunks_schema_if_needed(tbl)` helper that detects
     schema drift and calls `tbl.add_columns(...)` for each m2 column
     absent from the on-disk table. Idempotent.
   - Wired into `write_chunks` immediately after `db.open_table(...)`.

2. **`tests/test_store.py`** (+267)
   - `_make_textbook_chunk(slug, ...)` helper for round-trip tests.
   - `TestTextbookChunkRoundtrip` — AC #1.
   - `TestArxivChunkByteStableAfterSchemaBump` — AC #2.
   - `TestMixedCorpusInSameTable` — arXiv + textbook chunks coexist
     cleanly in the same LanceDB table.
   - `TestSourceKindEnumGuard` — write-time `_ALLOWED_SOURCE_KINDS`
     guard catches typos.
   - `TestSchemaMigrationGuard` — three tests:
     `test_migration_adds_seven_columns_with_arxiv_defaults`,
     `test_migration_is_idempotent`,
     `test_migration_unhandled_column_raises`.

3. **`.claude/docs/snippet-contract.md`** (+44)
   - New section (f) "Storage-layer columns from textbook-ingest-m2"
     documenting the 7 new columns, their types, arXiv/textbook
     defaults, and the BP1 cache discipline note (m3 re-pins, not m2).

4. **`.claude/notes/05-storage-and-indexing.md`** (+34)
   - Inline update under `### Table: chunks` documenting the 7 new
     columns + the in-place migration mechanism + the
     `_ALLOWED_SOURCE_KINDS` enum guard.

5. **`.claude/notes/milestones/textbook-ingest-m2/`** (new dir)
   - research-brief-1.md, research-brief-2.md, research-synthesis.md,
     state.json (pipeline state).

---

## Deviations from the brief

1. **Added `parser_used` as a 7th column** (the brief listed 6).
   Per R2's catch + synthesis D2: the brief says "extend the
   `parser_used` enum" but `parser_used` doesn't currently exist on
   the chunks table. Adding it makes the brief coherent.

2. **`license` backfill via SQL `cast('arxiv-license' as string)`**
   (the brief left default behavior unspecified). Per R2's FM-6 +
   synthesis D4: backfilling existing rows with the explicit token
   (vs leaving NULL) preserves downstream filter semantics
   (`WHERE license = 'arxiv-license'` finds every arXiv row, old
   and new).

3. **Did NOT bump `CHUNKER_VERSION`** (still `"v1.1"`). Per R2 +
   synthesis D5: bumping `CHUNKER_VERSION` would trigger the
   partial-re-embed driver to re-process every existing chunk. The
   chunking ALGORITHM is unchanged in m2; only the STORAGE schema
   is extended.

4. **Did NOT touch `re_embed.py`** (textbook re-embed is out of scope
   per synthesis D9). Documented for a future textbook-specific
   re-embed milestone.

5. **Did NOT rebuild the BM25 index at the new corpus_version**
   (synthesis D9). Manual operator step; the server falls back to
   ANN-only if the new BM25 index doesn't exist (cache discipline
   from `07-multi-agent-caching.md`).

---

## New / changed test paths

- `tests/test_store.py` (+267 LOC, +9 new tests across 5 new test
  classes: `TestTextbookChunkRoundtrip`,
  `TestArxivChunkByteStableAfterSchemaBump`,
  `TestMixedCorpusInSameTable`, `TestSourceKindEnumGuard`,
  `TestSchemaMigrationGuard`).

Test count: 39 → 48 in `test_store.py`. Project-wide: 2787 passing
(was 2778 pre-m2 on top of the embedder-truncation baseline).

---

## External writes required

**None.** Purely local — all changes touch `ingest/`, `tests/`, and
`.claude/`. No `git push`, no PR, no `gh` invocation, no infra
mutation, no external API call. Phase 4 will commit the rect + chore
commits locally; whether to push is a separate user decision.

---

## Pre-existing failures observed (not from m2)

Recorded for transparency; the milestone is responsible for none of
these. All six reproduced on `git stash` against the pre-m2 tree:

| Test | Failure | Root cause |
|---|---|---|
| `tests/eval/test_parser_fidelity.py::TestFixtureStructure::test_class_dir_exists[hartshorne-style]` | `is_dir()` returns False | Parser-fidelity-eval fixture dir not populated locally; pre-m2 |
| `tests/eval/test_parser_fidelity.py::TestFixtureStructure::test_class_dir_exists[griffiths-harris-style]` | same | same |
| `tests/eval/test_parser_fidelity.py::TestFixtureStructure::test_class_dir_exists[milne-style]` | same | same |
| `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines` | `latexmlc exited -6 on align.tex` | `latexmlc` SIGABRT on this workstation |
| `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_render_fixture_does_not_leave_log_artifact` | `latexmlc exited -6 on frac.tex` | same |
| `tests/test_tools_all.py::TestToolsSmoke::test_cite_neighorbs_wired` | Kùzu graph_status `unavailable` (expected `absent`) | Local `var/arxmcp/index/kuzu` state; pre-m1 |

---

## Next milestone hint

`textbook-ingest-m3` is the **BP1 cache-invalidation checkpoint**:
single coordinated rect-style commit that re-pins
`EXPECTED_TOOL_SCHEMA_SHA256` (in `tests/test_server_tool_schema.py`)
AND `EXPECTED_BP1_SHA256` (in `tests/test_prompts.py`) AND adds the
`notebook_kind: "textbook"` field to the m6 notebook schema in
`server/routes/notebooks.py`. The 21-column chunks-table schema is
ready to be exposed to the MCP surface in m3; m4 (cross-corpus
`source_kind` filter on `search_papers`) follows.
