# Research Brief — textbook-ingest-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-27T21:45:00Z

## In-codebase context

### Design notes applying to this milestone

**`05-storage-and-indexing.md`** — authoritative schema reference. The existing
`chunks` table design note does NOT list `source_kind`, `license`, `chapter`,
`page_start`, `page_end`, or `textbook_slug`. Adding them requires this note
to be updated alongside the schema constant. No design note FORBIDS adding
columns to the chunks table, but the schema comment in `ingest/schema.py` is
explicit:

> "Schema mutations require a corresponding MVCC version bump. E04_S02 will
> add a `corpus_version` integer to the dataset metadata; for now the schema
> is treated as immutable and any change forces a manual table re-creation.
> See `05-storage-and-indexing.md` § 'MVCC versioning' for the operational
> handshake."

This comment is stale — E04_S02 shipped, MVCC via dataset version integer is
live. The statement is still load-bearing for the operational guidance: any
new column that breaks existing readers requires a version bump. The 6 new
columns are all nullable with defaults, so EXISTING readers that do not know
about the new columns continue to read NULL/default for those fields — no
crash. But `corpus_version` in `corpus-version.json` must still increment
because the schema constant changes (cache keys include `corpus_version`).

**`07-multi-agent-caching.md`** — the cache key contract:

> "Tier 1 — Exact-query (SQLite LRU, 10K entries): key includes `corpus_version: int`
> as a mandatory component; stale entries from old corpus versions are
> unreachable by construction after a restart with a new `corpus-version.json`."

The corpus_version bump is mandatory. It propagates through: `corpus-version.json`
→ server startup → retrieval cache key → BM25 index version directory
(`var/arxmcp/index/bm25/v<N>/`). Old BM25 pickle at v<N> is NOT automatically
invalidated — the BM25 indexer must be re-run against the new corpus version.

**`ingest/schema.py` line 81:** `CHUNKS_SCHEMA_V1` is declared as a `pa.schema`
with **14 columns** (locked by `tests/test_store.py::test_column_count_matches_brief`
at line 146: `assert len(CHUNKS_SCHEMA_V1) == 14`). This milestone adds 6
columns, making the new count 20. **The test at line 146 WILL FAIL after the
schema change.** The implementer must update this assertion.

**`ingest/store.py::_build_arrow_table`** — builds rows as `dict` literals that
list every column explicitly, then calls `pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)`.
After the schema update, the row dict must include the 6 new columns (with
`None` defaults for arXiv rows). Omitting a column from the dict does NOT
error at `pa.Table.from_pylist` time — PyArrow fills missing dict keys with
null — but only if the column is declared `nullable=True`. All 6 new columns
must be declared `nullable=True`.

**`ingest/store.py::_build_arrow_table` line 283:** empty-input fast path uses
`pa.Table.from_pylist([], schema=CHUNKS_SCHEMA_V1)` — this will automatically
pick up the new schema constant with no change needed.

**`tests/_graph_helpers.py` line 140–144:** `_populate_chunks_table` iterates
`for field in CHUNKS_SCHEMA_V1` to build payload columns. This is schema-driven;
it will automatically pick up new columns. New nullable columns will default to
`None` lists, which is correct.

**`tests/test_intra_paper_refs.py` line 83** and **`tests/test_theorem_names.py`
line 501** both use `CHUNKS_SCHEMA_V1` for fixture LanceDB tables — these are
schema-driven and will auto-adapt. No manual edits needed unless they assert
a specific column count.

**`ingest/chunker_types.py::ChunkRecord`** — does NOT contain `source_kind`,
`license`, `chapter`, etc. The implementer must either add them to `ChunkRecord`
or handle them at the `_build_arrow_table` boundary. Given that textbook chunks
come from a different ingest path (MinerU), adding them to `ChunkRecord` as
optional fields (with `None` defaults) is the clean path — `store.py` then
reads them from the `ChunkRecord` when present. This is the approach this
brief recommends.

**`ingest/chunker_types.py::CHUNKER_VERSION = "v1.1"`** — the milestone brief
says to bump `corpus_version` not `CHUNKER_VERSION`. These are different:
`CHUNKER_VERSION` is the chunking algorithm version stamped on each row;
`corpus_version` is the LanceDB dataset version integer in `corpus-version.json`.
Bumping `CHUNKER_VERSION` would trigger the re-embed driver for all existing
rows (expensive and unnecessary). **Do NOT bump `CHUNKER_VERSION` for this
milestone.** The corpus_version bump happens automatically as a side effect of
the next `write_chunks` call.

**`ingest/re_embed.py`** — the partial re-embed driver copies embedding vectors
for unchanged chunk_ids. It does `to_arrow(filter=...)` to copy rows. After this
schema change, copied rows will be missing the 6 new columns (they will be
present in the on-disk LanceDB but only at their null/default values — the new
columns are written as part of the original ingest, not the re-embed). The
re-embed driver does NOT need modification because it copies from the staging
table, which will already have the new schema if the staging ingest was run
with the updated store code.

**`ingest/bm25_indexer.py` line 114:** BM25 index directory is
`BM25_INDEX_ROOT / f"v{corpus_version}"`. After a corpus_version bump, the
BM25 index at the old version is stale (it doesn't error, it just won't be
loaded by the server if the server reads the new corpus_version from the
marker). The BM25 index must be rebuilt against the new corpus version.

**No MCP surface changes** — the milestone brief is explicit. No changes to
`server/tools.py::ALL_TOOLS`. `EXPECTED_TOOL_SCHEMA_SHA256` must NOT be
re-pinned. The server does NOT change.

### Pinned versions

- **lancedb: 0.30.2** (from `uv.lock`)
- **pyarrow: 24.0.0** (from `uv.lock`)

### **FLAG: 05-storage-and-indexing.md does not list the new columns**

**The `chunks` table specification in `05-storage-and-indexing.md` must be
updated to include the 6 new columns and the `parser_used` enum extension.
The design constitution is the authoritative source; if the spec note lags
the code, future researchers will be confused.** This is not a contradiction
— the note predates this milestone — but it must be updated in the same commit.

## Prior decisions and lessons

From git log: m1 shipped in commits f187af4 + aec3a12 + 68c77c8. The
textbook chunk_id regex (`textbook:<slug>:...`) is live in
`ingest/identifiers.py`. The `ChunkRecord` dataclass has NOT yet been extended
for textbook-specific fields — that is exactly what this milestone adds.

From `MEMORY.md` memory entry `textbook-ingest-m1`:
> `ingest/identifiers.py::CHUNK_ID_RE` uses `$` (not `\Z`) anchor — a known
> F3-class bug. Not the concern of this milestone, but must not be worsened.

The `parser_used` enum extension mentioned in the brief (`mineru+latexml`) has
no existing home in the codebase. The `05-storage-and-indexing.md` `papers`
table lists `parser_used enum {ar5iv, latexml_local, nougat}` — this lives in
a table that has not been physically implemented yet (the `papers` table is
a design-note artifact; no `papers` LanceDB table exists). The `parser_used`
field does NOT appear in `CHUNKS_SCHEMA_V1`. The milestone brief says "extend
the parser_used enum with mineru+latexml" — the implementer should add a
`parser_used` column to `CHUNKS_SCHEMA_V1` (nullable, default None or "ar5iv")
since it is not currently present. This is consistent with the source_kind
column being the discriminator.

## External sources

### LanceDB 0.30.2 schema evolution

From [docs.lancedb.com/tables/schema](https://docs.lancedb.com/tables/schema):

> "When you add new columns to an existing table, all existing rows will either
> be NULL or will be given a default value. This is an efficient operation because
> when we add a new column, instead of rewriting the fragment, we add a new data
> file to the fragment."

The API is `table.add_columns({"new_col": "cast(NULL as utf8)"})` where the
value is a SQL expression. For nullable UTF-8 string: `"cast(NULL as utf8)"`.
For nullable int32: `"cast(NULL as int32)"`.

**Critically:** schema evolution via `add_columns` does NOT happen automatically
when `write_chunks` is called with a wider schema. `db.create_table(name, schema=CHUNKS_SCHEMA_V1)`
creates the table with the schema; if the table already exists, `db.open_table`
is called instead and the existing on-disk schema is used. An existing LanceDB
table with the old 14-column schema will NOT automatically gain the 6 new
columns just because `CHUNKS_SCHEMA_V1` was updated.

**This is the central migration risk.** The `write_chunks` function must detect
schema drift (old on-disk schema vs new constant) and call `tbl.add_columns(...)`
for each missing column BEFORE attempting `merge_insert`. Otherwise, `merge_insert`
will fail (input batch has 20 columns, table has 14) or silently drop the new
columns.

From the web search (Lance v0.16.1 / recent lancedb): `merge_insert` with a
source that has MORE columns than the target table FAILS unless the table
schema is first updated. Sub-schema insert (FEWER columns in source) works
as of recent versions.

### PyArrow 24.0.0

No breaking changes in PyArrow 24 relevant to nullable column declaration or
`pa.schema` construction. The `nullable=True` pattern used throughout
`CHUNKS_SCHEMA_V1` is stable API since PyArrow 0.x.

### Anthropic prompt-caching docs

Not relevant to this milestone — no MCP surface changes, no tool schema changes,
no BP1 re-pin needed.

## Failure modes (7 enumerated)

**FM-1: Schema drift on existing LanceDB dataset (HIGH)**
Trigger: `write_chunks` called after updating `CHUNKS_SCHEMA_V1` against an
existing on-disk table. `merge_insert` receives a 20-column Arrow batch against
a 14-column LanceDB table.
Symptom: LanceDB raises `ArrowInvalid: Schema mismatch` or silently drops the
6 new columns depending on lancedb version behavior.
Mitigation: `write_chunks` must call `tbl.add_columns` for each column present
in `CHUNKS_SCHEMA_V1` but absent from `tbl.schema`. Pattern:
```python
existing_names = set(tbl.schema.names)
for field in CHUNKS_SCHEMA_V1:
    if field.name not in existing_names:
        tbl.add_columns({field.name: _null_sql_for(field.type)})
```
This must run BEFORE `merge_insert`.

**FM-2: BM25 index serves stale corpus version (HIGH)**
Trigger: corpus_version bumps (new `corpus-version.json` written) but BM25
index under `var/arxmcp/index/bm25/v<old>/` is not rebuilt.
Symptom: server loads BM25 index keyed on old corpus_version; BM25 hits the
wrong row set; BM25 phase returns wrong chunk_ids.
Mitigation: the milestone brief only bumps the schema and corpus_version. The
BM25 index rebuild is not in scope here but the implementing test must assert
that `build_bm25_index` is called (or document it as a manual post-step). Cited
from `07-multi-agent-caching.md`: old corpus_version keys are unreachable by
construction, so BM25 at old version is simply not used; the server falls back
to ANN-only if the new BM25 index does not exist.

**FM-3: Tier-1/2 SQLite cache returns stale results (MEDIUM)**
Trigger: server restarts with new corpus_version after schema bump; old
SQLite cache entries have old corpus_version in their keys.
Symptom: none — old keys become dead by construction (see `07-multi-agent-caching.md`
"Stale entry served after corpus version bump: Cache keys include corpus_version;
old keys are dead by construction"). This is handled automatically.
Mitigation: None needed; cache isolation is already implemented.

**FM-4: `test_column_count_matches_brief` fails (BLOCKING)**
Trigger: adding 6 columns to `CHUNKS_SCHEMA_V1` makes `len(CHUNKS_SCHEMA_V1) == 20`
but the test at `tests/test_store.py:146` asserts `== 14`.
Symptom: `make test` fails immediately.
Mitigation: update the assertion and its inline comment in lockstep with the
schema constant. This is the canary test for schema drift.

**FM-5: `re_embed.py` copies rows without new columns (MEDIUM)**
Trigger: partial re-embed run after m2 schema change copies embedding rows
from an old-schema LanceDB version (pre-m2) into a new staging table.
Symptom: copied rows land in the staging table with NULL for `source_kind`
etc. This is CORRECT behavior for arXiv rows (default is `source_kind=None`
until explicitly overridden). However if the re-embed driver was extended to
handle textbook rows, it would need to explicitly copy those columns too.
Mitigation: m2 scope is arXiv-only for re-embed; document that re-embed of
textbook chunks is out of scope.

**FM-6: License field ambiguity — NULL vs "arxiv-license" default (MEDIUM)**
Trigger: existing arXiv rows written before m2 have NULL for `license`; new
arXiv rows written after m2 have `license="arxiv-license"` (if that is the
chosen default). A downstream handler filtering `WHERE license = 'arxiv-license'`
misses old rows.
Mitigation: either (a) set `license` default to NULL for all rows (arXiv and
textbook) and document that NULL means "arXiv default license", or (b) run
`tbl.add_columns({"license": "cast('arxiv-license' as utf8)"})` so existing
rows get the string. Option (b) is cleaner for downstream filtering.
**Recommendation: use option (b) — SQL expression sets "arxiv-license" for
all existing rows.**

**FM-7: `source_kind`-conditional logic in handlers reads non-existent column
on rows from a reader pinned to an old corpus version (LOW)**
Trigger: server reads a LanceDB version that pre-dates the schema migration,
then handler checks `row["source_kind"]`.
Symptom: `KeyError` or Arrow `FieldNotFound` on `source_kind` access.
Mitigation: this milestone adds NO handler logic — the brief is explicit "NO
MCP surface changes." Any future handler that reads `source_kind` must guard
with `row.get("source_kind")` or handle the case where old-version rows lack
the column. Document this in the column's schema comment.

**FM-8: `_graph_helpers.py` fixture builder iterates CHUNKS_SCHEMA_V1 fields
but tests build the fixture table with the old schema in memory (LOW)**
Trigger: test that creates a LanceDB fixture BEFORE the schema migration file
is applied in the test suite.
Symptom: fixture table has 14 columns, handler under test expects 20.
Mitigation: `_graph_helpers.py:_populate_chunks_table` is schema-driven
(`for field in CHUNKS_SCHEMA_V1`); it auto-adapts. No manual edit needed.

## Recommendation

**Implement as two coordinated changes:**

1. In `ingest/schema.py`: add the 6 new columns to `CHUNKS_SCHEMA_V1` (all
   `nullable=True`). Add `parser_used` as a 7th new column (nullable, `pa.utf8()`).
   Rename the constant to `CHUNKS_SCHEMA_V2` and keep `CHUNKS_SCHEMA_V1` as a
   deprecated alias (preferred) OR update the constant in-place and update all
   imports. In-place update is simpler and avoids alias confusion.
   Column defaults in `_build_arrow_table`: arXiv rows get
   `source_kind="arxiv"`, `license="arxiv-license"`, `chapter=None`,
   `page_start=None`, `page_end=None`, `textbook_slug=None`,
   `parser_used="ar5iv"`.

2. In `ingest/store.py::write_chunks`: add an explicit schema-migration step
   that runs `tbl.add_columns` for any column in `CHUNKS_SCHEMA_V1` absent
   from the on-disk table schema. This guards both forward-migration of the
   existing corpus AND new installations.

3. In `ingest/chunker_types.py::ChunkRecord`: add the 6 fields as optional
   with `None` defaults so textbook ingest paths (future milestone m3+) can
   populate them without a separate wrapper. `_build_arrow_table` reads them.

4. Update `tests/test_store.py::test_column_count_matches_brief` to assert
   `len(CHUNKS_SCHEMA_V1) == 21` (14 original + 6 new + 1 parser_used).

5. Update `05-storage-and-indexing.md` to document the new columns.

6. Update `snippet-contract.md` to document the new columns per the AC.

Do NOT bump `CHUNKER_VERSION`. Do NOT touch the MCP server. Do NOT re-pin
`EXPECTED_TOOL_SCHEMA_SHA256`.

Rationale for in-place update (vs `CHUNKS_SCHEMA_V2`): the milestone brief
says "NO MCP surface changes" and the server imports `CHUNKS_SCHEMA_V1` only
for fixture-creation in tests — it reads from LanceDB via `tbl.to_arrow()`,
not by constructing rows against the schema constant at query time. An in-place
update with the schema migration guard in `write_chunks` is the minimal diff.

## Open questions

1. **Does the `parser_used` field belong in `CHUNKS_SCHEMA_V1`?** The milestone
   brief says "extend the parser_used enum" but `parser_used` does NOT currently
   exist in `CHUNKS_SCHEMA_V1` (it lives only in the aspirational `papers`
   table in `05-storage-and-indexing.md`). The implementer must decide: add
   `parser_used` to the chunks table, or defer it to the future `papers` table.
   This brief recommends adding it to the chunks table as a nullable column —
   it is the only way to track parse provenance at the chunk level without a
   papers table.

2. **`merge_insert` behavior with extra source columns in lancedb 0.30.2.**
   The web search found documentation stating "you can omit fields from the
   schema" for sub-schema inserts, but it does NOT state behavior for a SOURCE
   with MORE columns than the TARGET table. The schema migration guard in
   `write_chunks` (calling `add_columns` before `merge_insert`) is the safe
   path and avoids this ambiguity entirely. The implementer should write a
   unit test that exercises `merge_insert` against an old-schema table to
   confirm behavior experimentally.

## External writes the implementation will require

None — this milestone is purely local. No git push to external repos, no
tickets, no infra mutations. The corpus_version bump in `corpus-version.json`
is a local file under `var/` (gitignored).

Sources:
- [Schema and Data Evolution - LanceDB](https://docs.lancedb.com/tables/schema)
- [Schema Evolution - Lance documentation](https://lancedb.github.io/lance/introduction/schema_evolution.html)
- [Add columns to a table - LanceDB](https://docs.lancedb.com/api-reference/data/add-columns-to-a-table)
