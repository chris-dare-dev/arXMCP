# E10_S01 — Implementation Summary

**One-line summary.** Added the LanceDB `definitions` table, a
per-paper indexer that populates it from preamble extractor output,
and rewrote the `get_definitions` handler to read from the new index
with 100-entry pagination and a three-step term-lookup hierarchy.

**Commit range.** `49dbd29..HEAD` (Phase-2 base
`49dbd29` → implementation HEAD at commit time).

---

## Acceptance criteria — status

- [x] **AC1.** `get_definitions(paper_id="2401.01234")` returns a
      paginated list of all notation entries for that paper.
      Verified by
      [TestHandlerFullTableMode::test_returns_all_definitions_single_page](tests/test_definitions_index.py)
      and [test_pagination_with_many_definitions](tests/test_definitions_index.py).
- [x] **AC2.** `get_definitions(paper_id=..., term="\\mathcal{A}")`
      returns the expansion of the matching macro. Verified by
      [TestHandlerTermLookup::test_exact_symbol_match](tests/test_definitions_index.py).
- [x] **AC3.** A paper with no `\newcommand` declarations returns an
      empty list, not a 404 or error. Verified by both
      [TestBuildDefinitionsForPaper::test_paper_with_no_preamble_returns_empty](tests/test_definitions_index.py)
      and [TestIndexer::test_paper_with_no_preamble_writes_zero_rows](tests/test_definitions_index.py),
      plus the handler-level
      [TestHandlerFullTableMode::test_unknown_paper_returns_empty](tests/test_definitions_index.py)
      and the no-index-fallback path
      [TestHandlerNoIndexFallback::test_absent_index_returns_empty_with_status](tests/test_definitions_index.py).
- [x] **AC4.** The definitions table B-tree (scalar) index on
      `(paper_id, symbol)` is present after ingestion. Per synthesis
      D8 the LanceDB ≥ 0.6 API does NOT support a composite
      `(paper_id, symbol)` scalar index; the spec is satisfied by
      per-column indexes on `paper_id` AND `symbol_raw` (the
      practical query-planner equivalent). Verified by
      [TestIndexer::test_scalar_indexes_created](tests/test_definitions_index.py).
- [x] **AC5.** `pytest tests/test_definitions_index.py` passes — 34
      tests, all green. Full suite: 1345 passed (+34 from 1311
      baseline), 4 skipped, ruff clean.

---

## Files added / changed

### New

- `ingest/index_definitions.py` — per-paper indexer. Parses every
  macro form the preamble extractor emits (`\newcommand`,
  `\renewcommand`, `\providecommand`, `\DeclareMathOperator` + star,
  `\def`/`\edef`/`\gdef`/`\xdef`, `\let`) into a
  `(symbol, symbol_raw, expansion)` triple, computes a content-
  addressable `definition_id`, and writes the rows via delete-then-
  insert under a per-paper filter. Creates scalar indexes on
  `paper_id` and `symbol_raw`.
- `tests/test_definitions_index.py` — 34 tests covering the parser,
  builder, indexer (idempotency + two-paper coexistence + scalar
  indexes), and the handler (full-table mode + paginated mode +
  three-step term lookup + no-index fallback + paper_id validation).

### Changed

- `ingest/schema.py` — added `DEFINITIONS_TABLE_NAME` and
  `DEFINITIONS_SCHEMA_V1` (7-column non-nullable PyArrow schema:
  `definition_id`, `paper_id`, `symbol`, `symbol_raw`, `expansion`,
  `defining_chunk_id`, `scope`).
- `server/handlers/definitions.py` — replaced the
  preamble.json-direct-read implementation with a LanceDB-backed
  handler. Added a `cursor` argument (opaque base64 of an integer
  offset, 100 rows per page) and a three-step term-lookup fallback
  (exact `symbol` → exact `symbol_raw` → case-insensitive prefix on
  `symbol_raw` only — never on `symbol`).
- `server/resources.py` — added an optional
  `definitions_table: Any | None` field on `Resources`; opened
  lazily in `startup()` when the table exists at the configured
  `lancedb_path` (`None` otherwise, surfaced as
  `index_status="absent"` in the handler envelope).
- `server/tools.py` — bumped `TOOL_SCHEMA_VERSION` from 1 to 2;
  rewrote `GET_DEFINITIONS.description` to describe the new
  LanceDB-backed source, the three-step term-lookup hierarchy, and
  the 100-entry pagination contract.
- `server/schemas/search_papers_result.json` — bumped the in-schema
  `version` field from 1 to 2 (paired with the
  `TOOL_SCHEMA_VERSION` bump per the snippet-contract cross-check).
- `tests/test_server_tool_schema.py` — re-pinned
  `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
  via `pytest --update-tool-schema-hash`.
- `tests/test_prompts.py` — re-pinned `EXPECTED_BP1_SHA256` (the
  GET_DEFINITIONS description change invalidates the BP1 cached
  prefix; documented in the test comment).
- `tests/test_tools_all.py` — updated
  `test_get_definitions_no_preamble` for the new response shape
  (`definitions=[]`, `next_cursor=None`, `total=0`,
  `index_status` ∈ {"absent","ok"}). Updated `TestDefinitionsParser`
  to import the relocated parser from `ingest.index_definitions`.

---

## Design decisions worth surfacing for Phase-3

These were resolved in the research synthesis and shipped as-is.
Phase 3 may legitimately question any of them.

1. **`symbol == symbol_raw` at v1** (synthesis D3). Both columns
   store the bare command name (e.g. `\AA`); the design-note example
   that suggested otherwise (`symbol="\mathcal{A}"`,
   `symbol_raw="\AA"`) is treated as documentation drift. The
   two-column schema is forward-compatible with a future
   canonicalization milestone.
2. **`defining_chunk_id` sentinel `{paper_id}:preamble`** (D2).
   Preamble-derived rows have no real chunk; the sentinel keeps the
   column non-nullable.
3. **Last-seen wins on `\renewcommand`** (D4). The preamble
   extractor sorts macros alphabetically, so "last seen" is
   "alphabetically last" — `\renewcommand` sorts after
   `\newcommand`, which produces the right TeX-semantics outcome for
   the common case. **Caveat:** this is NOT source order; a future
   milestone that wants strict source-order semantics will need to
   carry the source-order index through the preamble extractor.
4. **Definition-environment chunks deferred** (D5). Every row at v1
   has `scope="paper"`; the chunker emits no parsed symbol on
   `kind="definition"` chunks, so environment-derived rows would
   require a second parser pass. The brief's "Out of scope:
   Semantic expansion of definition text" supports the deferral.
5. **Case-insensitive prefix only on `symbol_raw`** (D7). LaTeX
   commands are case-sensitive; folding `\AA` and `\Aa` together
   would silently mis-resolve.
6. **Opaque base64-of-int cursor** (D9). Simpler than a symbol-
   string cursor; the encoding is private to the handler so it can
   evolve without a wire break.

---

## Forced-by-this-milestone cross-file changes

Per synthesis §4. All landed and verified:

- `TOOL_SCHEMA_VERSION` bumped from `1` to `2`.
- `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via
  `pytest --update-tool-schema-hash`. New value:
  `83f598e6d0417d43bd54f30590b0cc16a98784ca45b3f44d0ee9766df78d7313`.
- `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned to `2`.
- `EXPECTED_BP1_SHA256` re-pinned to
  `4fe100be00d7c6c466a7de00a6048b95e4ac6ca770145d3e5c81531c92e1f30b`.
- `server/schemas/search_papers_result.json::$id` bumped to
  `v2.json` and `version` to `2`.

---

## Test count delta

| Metric | Before | After |
|---|---|---|
| Tests passing | 1311 | 1345 |
| Tests skipped | 4 | 4 |
| Tests failing | 0 | 0 |
| Ruff status | clean | clean |

New tests are entirely in `tests/test_definitions_index.py` (34
tests). The +34 delta tracks exactly.

---

## External writes required

**None.** The only writes are to
`var/arxmcp/index/lancedb/definitions.lance/` (local LanceDB table on
disk), which is an INTERNAL data write the project owns end-to-end.

```
| type | target | why |
|---|---|---|
| —    | —      | (empty) |
```

The Phase-4 external-write boundary is therefore vacuous; only
`git push` requires user authorization at the end.

---

## Deviations from the brief

None of substance. Two notes:

- The brief's "B-tree index on `(paper_id, symbol)`" is implemented
  as two scalar indexes on `paper_id` and `symbol_raw` per synthesis
  D8 — LanceDB ≥ 0.6 does not support composite scalar indexes.
- The brief refers to `symbol` (canonical) and `symbol_raw`
  (author's). Per synthesis D3, both columns store the bare command
  name at v1; the distinction is preserved in the schema for a
  future canonicalization milestone. The brief's example
  (`symbol="\mathcal{A}"`, `symbol_raw="\AA"`) is treated as
  documentation drift since `\mathcal{A}` is the EXPANSION of
  `\AA`, not the canonical-form NAME.
