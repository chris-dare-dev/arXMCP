# Research Brief — textbook-ingest-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-27T00:00:00Z

## In-codebase context

### `ingest/schema.py` — current CHUNKS_SCHEMA_V1

The schema currently has **14 columns** in this exact order:
`chunk_id`, `paper_id`, `kind`, `section_path`, `theorem_name`, `theorem_label`,
`body_text`, `body_tokens`, `embedding_stmt`, `embedding_proof`, `embedding_eq`,
`chunker_version`, `embedder_version`, `preamble_ref`.

Load-bearing conventions observed:
- Required fields use `nullable=False`; optional fields use `nullable=True`.
- All enum-shaped columns (`kind`) are `pa.utf8()` — plain strings, NOT
  `pa.dictionary(...)`. Runtime guards enforce the enum domain (see
  `_ALLOWED_KINDS` in `store.py`).
- `embedding_eq` was reserved with `nullable=True` and a comment:
  `"The embedder NEVER populates this; every row written by E03_S01 has embedding_eq=None."`
  This is the precedent for "reserved but nullable" columns.

**CRITICAL: `TestSchemaContract.test_column_count_matches_brief` asserts
`len(CHUNKS_SCHEMA_V1) == 14` verbatim.** Adding 6 columns bumps this to 20.
This test MUST be updated in lockstep. Similarly,
`test_column_names_in_brief_order` asserts an exact ordered list of 14 names.

### `ingest/store.py` — merge_insert path and default-value handling

`_build_arrow_table` assembles rows as dicts, then calls
`pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)`. New columns
that the dict does NOT include will receive `None` values when PyArrow builds
the table — but ONLY if the column is declared `nullable=True` in the schema.
If any new column is `nullable=False`, the `from_pylist` call will raise
`ArrowInvalid` for rows that omit it.

**The key mechanical question: does LanceDB auto-null-fill existing rows on
the dataset when the schema gains new nullable columns?** The answer is NO —
LanceDB's `merge_insert(on="chunk_id").when_matched_update_all()` only updates
rows with explicitly provided data. The EXISTING ROWS on disk retain the
old schema (no new columns). LanceDB ≥ 0.11 supports schema evolution via
`alter_columns` / `add_columns` on an open table, but the current codebase
does NOT use this API. The current flow is: open (or create) the table once
per `write_chunks` call, then `merge_insert`. A schema upgrade path must
be added explicitly.

**corpus_version storage:** The `corpus-version.json` file under the LanceDB
path holds the integer version (= LanceDB dataset version after post-index
step). `write_corpus_version_marker` writes it atomically. The server reads
it at startup via `server.corpus.read_corpus_version()`. The Tier-1 cache key
includes `corpus_version` as a component — old entries become unreachable by
hash construction after a bump. BM25 index is versioned under
`var/arxmcp/index/bm25/v{corpus_version}/`.

**Readers that gate on corpus_version:**
- `server.cache_sqlite.derive_tier1_key` — includes `corpus_version` in key
- `server.cache.RetrievalCache.__init__` — receives and pins `corpus_version`
- `ingest.bm25_indexer.build_bm25_index` — partitions BM25 index by version dir
- `server.corpus.open_chunks_table` — reads version from `corpus-version.json`
- `server.health.CORPUS_VERSION_GAUGE` — Prometheus gauge

The corpus_version bump is purely mechanical: the new version is the LanceDB
dataset version returned by the NEXT `write_chunks` call that writes to the
updated schema dataset. **The bump is not a constant** — it emerges from LanceDB
MVCC integers. Tests in `test_corpus_version.py` that assert "version increments
on second write" will remain valid since they don't pin a specific integer.

### `ingest/bulk_ingest.py` — `parser_used` current values

The only runtime `parser_used` assignments found are:
- `outcome.parser_used = "ar5iv"` (line 286)
- `outcome.parser_used = "latexml"` (line 295)
- `None` (failure / skip path)

These are fields on `PaperOutcome`, NOT on `ChunkRecord` or `CHUNKS_SCHEMA_V1`.
**`parser_used` does NOT currently exist as a column in the chunks schema at all.**
The milestone brief adds it as a new column. Adding `"mineru+latexml"` as a third
enum value is the right time to also document `"ar5iv"` and `"latexml"` as the
other two valid values.

### `.claude/notes/05-storage-and-indexing.md` — column evolution rule

The design note states:
> "Schema mutations require a corresponding MVCC version bump."

The note also documents `parser_used` in the `papers` table (metadata), not
in the `chunks` table. So `parser_used` on the chunks table is net-new — no
drift to reconcile with the design note.

### `.claude/notes/07-multi-agent-caching.md` — cache discipline

> "Tier 1 — Exact-query memo... Cache key includes `corpus_version` so a corpus
> bump unreachable-izes every prior entry by hash construction."

A corpus_version bump via schema migration automatically invalidates all Tier-1
entries. No manual cache flush needed. This is the correct behavior for m2.

**BP1 discipline:** The milestone brief explicitly states "NO MCP surface changes
in this milestone (no envelope edits, no schema-hash re-pin — deferred to m3)."
The new columns are NOT exposed in any MCP tool result shape in m2, so
`EXPECTED_TOOL_SCHEMA_SHA256` is NOT re-pinned here. That deferral is correct
and must be preserved — m3 is the designated BP1 checkpoint.

## Prior decisions and lessons

**Git log for `ingest/schema.py` and `ingest/store.py`:**
- `d8ae180` — E10_S03 added `embedding_eq` reserved column to schema; the
  pattern was to declare it nullable with a doc comment explaining it would
  be populated by a future milestone. This is the direct precedent for
  the six new textbook columns.
- `88b9dcc` — E10_S01 added `DEFINITIONS_SCHEMA_V1` and `EQUATIONS_SCHEMA_V1`
  as separate new schemas (not adding to chunks schema). Those went in new
  LanceDB tables, not to the chunks table. Different pattern from m2 which
  extends the existing chunks table.
- `6d12138` — E04_S03 shipped the corpus_version marker. The integer is
  the LanceDB MVCC version, not a manually-bumped constant.

**Lesson from `embedding_eq` reservation (E10_S03):** The column was declared
in schema, the writer hard-codes `"embedding_eq": None` in `_build_arrow_table`,
and tests assert it is nullable. For m2, the six new columns must follow the
same write-path: explicitly include them in the `rows.append({...})` dict in
`_build_arrow_table`, with arXiv-shaped chunks supplying defaults
(`source_kind="arxiv"`, `license="arxiv-license"`, `chapter=None`,
`page_start=None`, `page_end=None`, `textbook_slug=None`) and textbook-shaped
chunks supplying actual values.

**`ChunkRecord` dataclass does NOT yet carry the new fields.** The brief asks
for the LanceDB schema + writer to handle a "textbook-shaped chunk." This means
the m2 implementer must also add the six fields to `ChunkRecord` with appropriate
defaults — otherwise `_build_arrow_table` has no source for those values on
incoming chunks. `CHUNKER_VERSION` will need to be bumped (currently `"v1.1"`)
when `ChunkRecord` gains new fields, since the chunker contract changed.

**CHUNKS_SCHEMA_V1 name stability:** The constant is named `CHUNKS_SCHEMA_V1`.
Adding 6 columns to it while keeping the `V1` name is consistent with E10_S03
precedent (which added `embedding_eq` without renaming). Do NOT rename to
`CHUNKS_SCHEMA_V2` — the constant is imported throughout tests.

## External sources

**LanceDB 0.30.2** (resolved version from `uv.lock`; spec `>=0.6`). LanceDB 0.30
does support `add_columns` and `alter_columns` as Python methods on `LanceTable`,
but the current codebase does NOT call these. The `create_table` call passes
`schema=CHUNKS_SCHEMA_V1` only on the FIRST write; subsequent calls go through
`db.open_table(CHUNKS_TABLE_NAME)` which returns a table tied to the on-disk
schema. If the on-disk schema has 14 columns and the new `CHUNKS_SCHEMA_V1` has
20, `merge_insert` will succeed for NEW rows (PyArrow fills missing nullable
columns with NULL), but existing rows on disk retain the 14-column shape.

For the AC "given an existing arXiv chunk, when read after schema bump, then
all new columns are present with documented defaults" — this requires the
implementer to call `tbl.add_columns(...)` ONCE when the old table is opened
and the new columns are absent. The guard should be: check if `source_kind` is
absent from `tbl.schema.names`, and if so, call `add_columns` with default
expressions. This is a one-time migration, not an ongoing re-write.

**No external vendor doc needed** — lancedb 0.30.2 `add_columns` API is
available in-process; PyArrow nullable column defaults via `from_pylist` are
well-established behavior.

## Recommendation

**Approach:** Add the 6 new columns to `CHUNKS_SCHEMA_V1` as `nullable=True`
`pa.utf8()` (for string cols) and `pa.int32()` (for page_start/page_end), add
corresponding fields to `ChunkRecord` with default values, update
`_build_arrow_table` to always include all 6 fields in the row dict, add a
one-time LanceDB `add_columns` migration in `write_chunks` (called when opening
an existing table that lacks `source_kind`), bump `CHUNKER_VERSION` to `"v1.2"`,
and update the lockstep tests.

**`source_kind` encoding:** Use `pa.utf8()` (plain string), NOT `pa.dictionary()`.
Rationale: every other enum-shaped column in this schema (`kind`, `chunker_version`)
is plain `pa.utf8()`. LanceDB scalar indexes don't support dictionary columns
(noted in `ingest/schema.py` docstring for `DEFINITIONS_SCHEMA_V1`). Runtime guard
in `_build_arrow_table` enforces the domain `{"arxiv", "textbook"}`.

**`license` default token:** Use `"arxiv-license"` as specified. No canonical
arXiv license string exists in the codebase (searched CHANGES.md, ingest/,
server/ — no hits). The brief's proposed token is the right choice for a
placeholder that is clearly arXiv-scoped. When real arXiv license strings land
(e.g. `"http://arxiv.org/licenses/nonexclusive-distrib/1.0/"`) they can replace
this token in a future milestone.

**`parser_used` values to document:** `"ar5iv"`, `"latexml"`, `"mineru+latexml"`.
The column should be nullable (`None` means ingest failure / unknown). Null and
`None` are the same at the LanceDB layer.

**`textbook_slug` redundancy with `paper_id`:** Keep the redundancy intentionally.
`paper_id = "textbook:shimura-varieties"` encodes provenance but is opaque in
WHERE-clause filters. `textbook_slug = "shimura-varieties"` enables simple scalar
index queries (`WHERE textbook_slug = ?`) without string-splitting. The storage
overhead is negligible. Add a `create_scalar_index("textbook_slug", replace=True)`
call in `_create_indices` (best-effort, like the existing `paper_id` index).

**`corpus_version` bump mechanics:** No manual bump constant exists. The bump
emerges naturally: after the `add_columns` migration runs on the existing table,
the next `merge_insert` write creates a new LanceDB MVCC version which is then
written to `corpus-version.json`. Any test that pins a specific corpus_version
integer (there are none found — `test_corpus_version.py` only asserts
increment semantics, not specific integers) would need updating, but none exist.

**MVCC migration in `write_chunks`:** Before `merge_insert`, after `db.open_table`,
check: `if "source_kind" not in set(tbl.schema.names): tbl.add_columns(...)`.
Pass default expressions as PyArrow scalar arrays. This is a one-time per-table
migration; subsequent calls will find all columns present and skip the branch.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one area where the implementer must make a judgment call is the exact
`pa.Table.add_columns` API usage in lancedb 0.30.2 — it accepts a dict of
`{column_name: pyarrow.ChunkedArray}`. The implementer should verify the
exact call signature against the installed version, but this is a
lancedb-version lookup, not a design decision.

## External writes the implementation will require

None — this milestone is purely local. No `git push`, PR, ticket, infra
mutation, or third-party API call. The corpus_version bump and LanceDB
migration happen entirely within `var/arxmcp/index/lancedb/` on the
local workstation.
