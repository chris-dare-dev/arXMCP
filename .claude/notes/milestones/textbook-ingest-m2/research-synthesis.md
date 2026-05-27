# Research Synthesis — textbook-ingest-m2

**Standard mode dispatch (2× Sonnet in parallel).** Both briefs converged
on the central approach. This synthesis records the orchestrator's
resolution of the two divergence points and the open questions.

Primary inputs:
- [research-brief-1.md](research-brief-1.md) — in-codebase focus
- [research-brief-2.md](research-brief-2.md) — external + failure-mode focus

---

## Scope (verbatim from roadmap)

Add 6 nullable columns to `CHUNKS_SCHEMA_V1` in `ingest/schema.py`:
`source_kind` (default `arxiv`), `license` (default `arxiv-license`),
`chapter`, `page_start`, `page_end`, `textbook_slug`. Extend the
`parser_used` enum with `mineru+latexml`. Bump `corpus_version`.
LanceDB store's idempotent `merge_insert` must round-trip both
arXiv-shaped and textbook-shaped chunks in the same table.

**Acceptance criteria** (verbatim):

1. Textbook chunk with `source_kind=textbook` round-trips all 6 new
   columns with correct types.
2. Existing arXiv chunk reads with documented default values; existing
   fields byte-identical.
3. `corpus_version` N → N+1; pinning tests update in lockstep.
4. `.claude/docs/snippet-contract.md` documents the new columns
   (no `truncated_for_license` enforcement yet — e5's job).
5. `make test` green; chunker tests + chunk-id round-trip + LanceDB
   merge-insert tests passing.

NO MCP surface changes. NO `EXPECTED_TOOL_SCHEMA_SHA256` re-pin
(m3's job).

---

## Load-bearing constraints (from both briefs)

### Existing schema is 14 columns; the count is pinned by test

Both briefs confirm `ingest/schema.py::CHUNKS_SCHEMA_V1` has **14
columns** locked by `tests/test_store.py::test_column_count_matches_brief`
(`assert len(CHUNKS_SCHEMA_V1) == 14`) and
`test_column_names_in_brief_order`. **Both tests fail on the schema
bump and must update in lockstep with the schema constant.**

Current 14 columns (brief order):
`chunk_id`, `paper_id`, `kind`, `section_path`, `theorem_name`,
`theorem_label`, `body_text`, `body_tokens`, `embedding_stmt`,
`embedding_proof`, `embedding_eq`, `chunker_version`,
`embedder_version`, `preamble_ref`.

### `parser_used` does NOT exist on chunks today (R2's catch)

R1 noted that `parser_used` appears on the in-memory `PaperOutcome`
dataclass (`ingest/bulk_ingest.py:286/295`) with values `"ar5iv"`,
`"latexml"`, `None`. R2 confirmed it lives ONLY in the aspirational
`papers` table in `05-storage-and-indexing.md` — there is NO
`papers` LanceDB table physically. So the brief's "extend the
`parser_used` enum" means **add `parser_used` as a NEW column on the
chunks table**, not modify an existing column.

**Decision:** add `parser_used` as a 7th new column (not the 6
the brief listed). Total: 14 → 21 columns. Document the enum
domain: `{ar5iv, latexml, mineru+latexml}` with `None` for failure/
unknown.

### Schema evolution requires `add_columns` migration

R2 surfaced the critical lancedb 0.30.2 contract from
[docs.lancedb.com/tables/schema](https://docs.lancedb.com/tables/schema):

> "When you add new columns to an existing table, all existing rows
> will either be NULL or will be given a default value. This is an
> efficient operation because when we add a new column, instead of
> rewriting the fragment, we add a new data file to the fragment."

API: `tbl.add_columns({"col_name": "<SQL expression>"})`. For
nullable UTF-8: `"cast(NULL as utf8)"`. For nullable int32:
`"cast(NULL as int32)"`. For "arxiv-license" default on the
`license` column: `"cast('arxiv-license' as utf8)"`.

**Critically:** `merge_insert` does NOT auto-evolve. If
`CHUNKS_SCHEMA_V1` has 21 columns and the on-disk table has 14,
sending a 21-column batch will either fail or silently drop the
new columns. The implementer MUST call `add_columns` on the open
table BEFORE `merge_insert`.

### `corpus_version` is emergent from LanceDB MVCC, not a constant

R1 nailed this: `corpus_version` is the LanceDB dataset version
integer written to `corpus-version.json` by
`write_corpus_version_marker`. It is NOT a manually-bumped Python
constant. After the schema-migration `add_columns` call, the next
write naturally produces a higher MVCC version. No `int = N`
literal needs editing. Tests in `test_corpus_version.py` assert
increment semantics, not specific integers — no test breakage.

### `CHUNKER_VERSION` MUST NOT bump (R2's catch)

R2 explicitly warned: bumping `CHUNKER_VERSION` (currently `"v1.1"`)
triggers the partial-re-embed driver to re-process every existing
chunk. Expensive and unnecessary — the chunking ALGORITHM is
unchanged; only the STORAGE schema is extended. Keep
`CHUNKER_VERSION="v1.1"`.

### Cache-invalidation flow (from R2)

[`07-multi-agent-caching.md`](.claude/notes/07-multi-agent-caching.md):

> "Tier 1 — Exact-query (SQLite LRU, 10K entries): key includes
> `corpus_version: int` as a mandatory component; stale entries
> from old corpus versions are unreachable by construction after a
> restart with a new `corpus-version.json`."

Cache invalidation is automatic. No manual flush. BM25 index at
old `var/arxmcp/index/bm25/v<old>/` becomes unreachable; if the
new BM25 index doesn't exist, the server falls back to ANN-only
(FM-2 in R2). BM25 rebuild is NOT in m2 scope — document as a
manual operator step (or future milestone).

---

## Orchestrator design decisions

### D1 — In-place schema update, keep `CHUNKS_SCHEMA_V1` name

Both briefs agree. R1 cites E10_S03 precedent (added `embedding_eq`
without renaming). The constant is imported across tests; rename
would mean cascade edits. In-place update.

### D2 — Add `parser_used` as the 7th column (R2's recommendation)

R1 listed 6 columns; R2 caught that `parser_used` doesn't exist
on the chunks table. The brief says "extend the `parser_used`
enum with `mineru+latexml`" which is only meaningful if
`parser_used` is a column. Resolution: ship 7 new columns
(6 from the brief + `parser_used`). Total 21 columns. Document
the enum domain explicitly in `05-storage-and-indexing.md`.

### D3 — Column types

- `source_kind`: `pa.utf8()`, nullable=True. Runtime guard enforces
  domain `{"arxiv", "textbook"}` in `_build_arrow_table`.
- `license`: `pa.utf8()`, nullable=True. Domain documentary only
  (no runtime enum guard) — future licenses (CC-BY, GFDL) need
  flexibility.
- `chapter`: `pa.utf8()`, nullable=True.
- `page_start`: `pa.int32()`, nullable=True.
- `page_end`: `pa.int32()`, nullable=True.
- `textbook_slug`: `pa.utf8()`, nullable=True.
- `parser_used`: `pa.utf8()`, nullable=True.

Plain `pa.utf8()` matches the existing convention (`kind`,
`chunker_version` are all plain strings, not `pa.dictionary()`).

### D4 — License-default policy (R2's FM-6 mitigation)

R2 flagged the NULL-vs-`"arxiv-license"` ambiguity: existing rows
get NULL, new rows get the default token. Downstream filters
`WHERE license = 'arxiv-license'` would miss old rows.

**Resolution:** use R2's option (b) — when migrating an existing
table via `add_columns`, set `license` with SQL expression
`"cast('arxiv-license' as utf8)"` so existing arXiv rows get the
non-null token. New writes also write `"arxiv-license"` for arXiv
chunks. NULL means "license unknown" reserved for future
non-arXiv-non-textbook content.

For `source_kind`: same pattern — set `"arxiv"` retroactively via
`add_columns` SQL `"cast('arxiv' as utf8)"`. Old rows are arXiv
by definition (no textbook ingestion has happened yet).

For `parser_used`: best-effort `"ar5iv"` for existing rows (the
dominant historical parser). Backfill via SQL expression.

For the 4 textbook-only columns (`chapter`, `page_start`,
`page_end`, `textbook_slug`): NULL for all existing rows
(`"cast(NULL as <type>)"`).

### D5 — `ChunkRecord` extension

Both briefs agree: extend the `ChunkRecord` dataclass in
`ingest/chunker_types.py` (per R2) or wherever the dataclass
lives, with the 7 new fields as optional (`None` defaults). This
keeps `_build_arrow_table`'s row-dict construction clean — read
from `ChunkRecord` attributes uniformly.

### D6 — Migration entry point: `write_chunks` in `ingest/store.py`

Add a one-time migration guard at the top of `write_chunks` (or
wherever `db.open_table` happens) that:

1. Reads `tbl.schema.names`.
2. For each field in `CHUNKS_SCHEMA_V1` absent from the existing
   schema, calls `tbl.add_columns({name: sql_default})` with the
   per-D4 SQL expression.
3. Then proceeds to `merge_insert`.

This is idempotent: subsequent calls find all columns present and
skip. Cost is one `tbl.schema.names` read per `write_chunks` call.

### D7 — Test surface updates

- `tests/test_store.py::test_column_count_matches_brief`: 14 → 21.
- `tests/test_store.py::test_column_names_in_brief_order`: append
  the 7 new names in the documented order.
- New tests:
  - `test_textbook_chunk_roundtrip`: write a `ChunkRecord` with
    `source_kind="textbook"`, `textbook_slug="shimura-varieties"`,
    `chapter="Chapter 1"`, `page_start=1`, `page_end=10`,
    `license="GFDL"`, `parser_used="mineru+latexml"`. Read back.
    Assert all 21 columns survive (AC #1).
  - `test_arxiv_chunk_roundtrip_byte_stable`: write an arXiv-shaped
    `ChunkRecord` (existing fields only); assert post-bump read
    returns the same existing values + default-populated new
    columns (AC #2).
  - `test_schema_migration_idempotent`: simulate writing twice;
    assert second call doesn't re-run `add_columns`.
  - `test_corpus_version_bumps_on_schema_change`: existing pinning
    test already covers this in spirit; verify it passes.

### D8 — Doc updates (AC #4 + R2 flag)

- `.claude/docs/snippet-contract.md`: document the 7 new columns,
  note that `truncated_for_license` flag is deferred to e5 and
  NOT enforced in m2. Cite the enum domains.
- `.claude/notes/05-storage-and-indexing.md`: extend the chunks
  table specification with the 7 new columns. Update the
  `parser_used` enum documentation to live with the chunks table
  (it was previously documentary-only for the papers table).
- Update the stale comment in `ingest/schema.py` ("E04_S02 will
  add a `corpus_version` integer...") — R2 noted this is now
  inaccurate; E04_S02 shipped.

### D9 — Out of scope (explicit deferrals)

- BM25 index rebuild at the new corpus_version: manual operator
  step, not coded in m2. Document in implementation-summary.
- `re_embed.py` extension for textbook chunks: arXiv-only in m2.
- MCP tool envelope edits: m3.
- `EXPECTED_TOOL_SCHEMA_SHA256` re-pin: m3.
- `truncated_for_license` snippet-truncation enforcement: e5.

---

## Files touched in m2

1. `ingest/schema.py` — add 7 columns to `CHUNKS_SCHEMA_V1`,
   update the stale E04_S02 comment.
2. `ingest/store.py` — add `add_columns` migration guard in
   `write_chunks`; update `_build_arrow_table` to populate the 7
   new fields from `ChunkRecord`.
3. `ingest/chunker_types.py` (or wherever `ChunkRecord` lives) —
   add 7 optional fields with `None` defaults.
4. `tests/test_store.py` — bump column-count assertion 14 → 21,
   add new ordered-name entries.
5. New tests:
   - `tests/test_textbook_chunk_storage.py` (or extension to
     `tests/test_store.py`) — round-trip + migration + idempotency.
6. `.claude/docs/snippet-contract.md` — doc the new columns.
7. `.claude/notes/05-storage-and-indexing.md` — extend chunks-table
   spec.

NO touches to: `server/tools.py`, `server/prompts.py`,
`tests/test_server_tool_schema.py`, `tests/test_prompts.py`,
`ingest/identifiers.py` (m1 already shipped), MCP handlers.

---

## Combined failure-mode register

From R2's enumeration + orchestrator extensions:

| # | Trigger | Severity | Mitigation in m2 |
|---|---|---|---|
| FM-1 | Schema drift on existing LanceDB dataset | HIGH | D6 — `add_columns` migration guard |
| FM-2 | BM25 index at old corpus_version stale | HIGH | D9 — documented operator step; server falls back to ANN-only |
| FM-3 | Tier-1/2 SQLite cache returns stale results | MEDIUM | None needed — cache keys include corpus_version (auto-invalidation) |
| FM-4 | `test_column_count_matches_brief` fails | BLOCKING | D7 — update assertion to 21 |
| FM-5 | `re_embed.py` copies rows without new columns | MEDIUM | D9 — out of scope; arXiv-only re-embed in m2 |
| FM-6 | License NULL-vs-`"arxiv-license"` ambiguity | MEDIUM | D4 — backfill via SQL `cast('arxiv-license' as utf8)` |
| FM-7 | `source_kind`-conditional handler reads non-existent column on stale-corpus row | LOW | No handler logic in m2; document for future handlers |
| FM-8 | `_graph_helpers.py` fixture auto-adapts | LOW | Schema-driven; no manual edit needed |
| FM-9 | `CHUNKER_VERSION` accidentally bumped triggering full re-embed | HIGH | D5 — explicit "do NOT bump" in implementation-summary |
| FM-10 | New columns absent from `ChunkRecord` → `KeyError` in `_build_arrow_table` | HIGH | D5 — extend `ChunkRecord` with `None` defaults BEFORE store-writer update |

---

## Open questions (resolved by orchestrator)

R1: zero open questions. R2: 2 open questions.

1. **R2: Does `parser_used` belong in `CHUNKS_SCHEMA_V1`?**
   **Resolved (D2):** YES. Add as 7th new column. The brief's
   "extend the enum" wording only makes sense if the column
   exists.

2. **R2: `merge_insert` behavior with extra source columns in
   lancedb 0.30.2?**
   **Resolved (D6):** ambiguous and avoided by design. The
   `add_columns` migration guard ensures the on-disk schema is
   widened BEFORE `merge_insert` is called, so source columns
   are never "extra." Implementation must include a regression
   test that exercises the migration path against a synthetic
   old-schema table.

---

## External writes required

**None.** Purely local. No `git push`, no PR, no `gh`, no infra
mutation. All changes touch `var/arxmcp/index/lancedb/` and
`var/arxmcp/index/corpus-version.json` on the local workstation.

---

## Orchestrator synthesis note

Two briefs, two divergence points resolved:

- **Column count: 6 vs 7.** R2 was correct — `parser_used` is
  currently absent from `CHUNKS_SCHEMA_V1` despite the brief
  presupposing it's there. Adding it makes the brief coherent.
  Total new columns: 7 (D2).
- **`license` default policy.** R2's FM-6 raised an ambiguity R1
  didn't address. R2's option (b) (SQL backfill) is cleaner and
  resolves the downstream-filter-misses-old-rows risk (D4).

No other divergence. Both briefs agree on:
- In-place `CHUNKS_SCHEMA_V1` update (no rename to V2).
- `nullable=True` on all new columns.
- `add_columns` migration guard in `write_chunks`.
- `CHUNKER_VERSION` stays `"v1.1"`.
- `corpus_version` is emergent from LanceDB MVCC.
- No MCP surface or BP1 changes.
- `.claude/docs/snippet-contract.md` + `05-storage-and-indexing.md`
  documentation updates required.

Ship as drawn.
