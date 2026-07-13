---
milestone_id: "source-truth-spike-4"
date: "2026-07-13"
roadmap_track: "R1-source-truth"
assumption_tested: >-
  Given a snapshot copy of the live LanceDB dir, the five-column v2 migration
  (source-truth-e2) dry-runs via the ingest/store.py::_migrate_chunks_schema_if_needed
  pattern and extends cleanly in place before touching the live table.
injection_attempts: 0
verdict: "clean-in-place-except-source_span-struct-needs-schema-form-add_columns"
---

# source-truth-spike-4 — chunks-schema v2 migration dry-run (5 source-truth-e2 columns)

## Question (roadmap acceptance criterion, verbatim)

> Given a snapshot copy of the live LanceDB dir, when the five-column v2 migration
> dry-runs via the ingest/store.py::_migrate_chunks_schema_if_needed pattern, then the
> outcome (clean in-place extension or a required fallback) is recorded before touching
> the live table.

The 5 new columns (source-truth-e2, per
`.claude/notes/milestones/source-truth-m1/research/brief-2.md:42-45`): `source_revision_id`
(str), `source_span` (str/struct — DOM anchor + char offsets into parsed HTML),
`truncated` (bool), `printed_number` (str), `license_ref` (str). All nullable/defaulted.

## Headline result

**4 of 5 columns ride `_migrate_chunks_schema_if_needed`'s existing SQL-expression
mechanism completely unmodified.** The 5th, `source_span`, only does if it stays a JSON
string. **If `source_span` is typed as a genuine struct (as the source-truth-m1 brief's
"DOM anchor + char offsets" language implies), the exact `dict[str,str]` SQL-cast call
the current helper uses hard-fails at DataFusion's SQL parser** — confirmed with the
literal error below — **but `add_columns`'s sibling schema-based overload
(`pa.Field`/`pa.Schema`, no SQL involved) adds the same struct column cleanly, in place,
with zero new data files.** This is a one-column mechanism branch, not a fallback to a
full rewrite, re-embed, or index rebuild.

---

## Method

**LanceDB version:** `lancedb==0.30.2`, `pyarrow==24.0.0` (both confirmed installed in
`.venv`, matching the version pinned in `ingest/schema.py`'s docstring comment at
`LANCE_STORAGE_OPTIONS`).

**The migration mechanism (grounded in `ingest/store.py`):**

- `write_chunks` (store.py:797) opens or creates the `chunks` table, and — only on the
  open-existing-table branch (store.py:843-851) — calls
  `_migrate_chunks_schema_if_needed(tbl)` (store.py:330-411) before every write.
- The helper reads `tbl.schema.names`, diffs against `CHUNKS_SCHEMA_V1.names`
  (`ingest/schema.py`), and for each missing column calls
  `tbl.add_columns({name: sql_expr})` where `sql_expr` comes from the
  `_TEXTBOOK_MIGRATION_DEFAULTS` dict (store.py:319-327) — a `dict[str, str]` of SQL
  expressions evaluated per existing row by LanceDB's DataFusion-based SQL layer. Any
  column missing a default entry raises `RuntimeError` (fail loud, store.py:360-367).
- A follow-up loop (store.py:395-403) calls
  `tbl.alter_columns({"path": name, "nullable": True})` for any newly-added column whose
  inferred nullability doesn't match `CHUNKS_SCHEMA_V1` — needed historically because
  m2's non-null literal defaults (`cast('arxiv' as string)`) infer `nullable=False`.
- **`add_columns` actually accepts two different input shapes** (confirmed via
  `inspect.signature`/docstring on the installed `lancedb.table.Table.add_columns`):
  1. `Dict[str, str]` — SQL expressions, evaluated per row (the form
     `_migrate_chunks_schema_if_needed` uses today).
  2. `pa.Field | List[pa.Field] | pa.Schema` — declares new columns of the given Arrow
     type directly; LanceDB null-initializes them with **no SQL evaluation at all**.
  This second form is the fallback this spike exercises for the struct case below.

**The copy:** used `robocopy` (not the brief's literal `cp -r`) — the live dir is 11 GB
across 3,330 dirs / 10,422 files (`data/` 794.8 MB / 811 files; `_indices/` ~11 GB / 4,122
files — the HNSW + scalar indices; `_versions/` 57 MB; `_transactions/` 11 MB), and a
POSIX `cp -r` through Git Bash over that many small files on NTFS is materially slower
than Windows' native robocopy. Functionally equivalent full-tree copy; noted here as a
deliberate substitution, not a scope deviation.

```
robocopy <live>\lancedb <scratch>\lancedb /E /R:2 /W:1 /NFL /NDL /NP
  Dirs :  3330  Files : 10422  Bytes : 10.871 g   FAILED: 0   Mismatch: 0   ~30s
```

Verified the copy: table opens, **21 columns** (matches `CHUNKS_SCHEMA_V1`), **row count
15,106** (matches live `corpus-version.json`'s `chunk_count`), **MVCC version 4434**
(matches live). Duplicated this verified copy into two more scratch working copies
(`lancedb_string/`, `lancedb_struct/`) for two isolated experiments, keeping the first
copy (`lancedb/`) pristine/never-migrated as an integrity-diff reference.

**Two experiments**, each against its own scratch copy:

- **`string`** — all 5 columns via the exact `dict[str,str]` SQL-expression mechanism,
  `source_span` typed `utf8` (a JSON-string column).
- **`struct`** — the 4 scalars via the identical SQL mechanism; `source_span` typed as a
  genuine `pa.struct([dom_anchor: utf8, char_start: int32, char_end: int32])` — a
  *representative placeholder* shape per brief-2.md's "DOM anchor + char offsets into the
  parsed HTML" (the final source-truth-e2 field-level spec wasn't available to this
  spike; the point is the migration mechanism, not the exact field names).

Script: `dry_run_migration.py` (scratch), refuses to run against any path that doesn't
contain a `scratchpad` path component (belt-and-suspenders live-dir guard). A separate
`verify_integrity.py` cross-checks row counts, distinct `chunk_id` counts, embedding
bit-identity, and MVCC version history across the pristine base copy and both migrated
copies.

## Dry-run result

### Experiment "string" — clean in-place extension, zero errors

5 sequential `tbl.add_columns({name: "cast(NULL as <type>)"})` calls, one MVCC version
each: `4434 → 4435 → 4436 → 4437 → 4438 → 4439` (0.09–0.28s per call, ~0.7s total).

```
add_columns({'source_revision_id': 'cast(NULL as string)'})   -> v4435  0.28s
add_columns({'truncated': 'cast(NULL as boolean)'})            -> v4436  0.11s
add_columns({'printed_number': 'cast(NULL as string)'})        -> v4437  0.09s
add_columns({'license_ref': 'cast(NULL as string)'})           -> v4438  0.09s
add_columns({'source_span': 'cast(NULL as string)'})           -> v4439  0.13s
```

- Schema: **21 → 26 columns**, all 5 new names present.
- Row count: **15,106 → 15,106**, unchanged. Distinct `chunk_id` count also 15,106 (no
  duplication).
- Nullability: **all 5 columns inferred `nullable=True` directly** from the
  `cast(NULL as ...)` expression — the `alter_columns` fix-up loop fired 0/5 times. This
  *differs* from the m2 precedent (non-null `'arxiv'`/`'arxiv-license'` literals needed
  the explicit fix-up); here it's a correct no-op every time because all 5 new columns
  are NULL-defaulted per the brief.
- Sample rows (3 pre-existing rows) read back after migration: all 5 new columns are
  `None`; `embedding_stmt`/`embedding_proof` lengths unchanged (1024 for the populated
  column of the dual-encoding pair, `None` for the other) — existing data intact.
- **Disk cost: `chunks.lance/data/` is byte-for-byte IDENTICAL before/after** —
  833,408,013 bytes, 811 files, **0 new files, 0-byte delta**. Only `_versions/` (+194
  KB, 5 new manifests) and `_transactions/` (+93 KB, 5 new transaction records) grew.
  This is cheaper than the "new data file appended per fragment" language in
  `ingest/schema.py`'s docstring describes for the general case: because every value is
  NULL, Lance records the column as pure schema/manifest metadata with no physical
  null-bitmap payload.

**Verdict: clean in-place extension.** Matches the production mechanism exactly — this
is literally what happens if `_TEXTBOOK_MIGRATION_DEFAULTS` grows 5 more entries and
`CHUNKS_SCHEMA_V1` grows 5 more fields, no other code changes.

### Experiment "struct" — 4/5 clean, `source_span` needs the fallback call form

The 4 scalars: identical clean result to the string experiment (`4434 → 4438`, 0/4
nullability fix-ups needed).

**`source_span` attempt 1 — SQL cast-to-struct**, mirroring
`_migrate_chunks_schema_if_needed` verbatim with
`"cast(NULL as struct(dom_anchor string, char_start int, char_end int))"`:
**FAILS.** Exact error:

```
RuntimeError: lance error: Invalid user input: Error parsing statement:
SELECT cast(NULL as struct(dom_anchor string, char_start int, char_end int)) FROM t
(sql parser error: Expected: ), found: (),
C:\Users\runneradmin\.cargo\registry\src\index.crates.io-1949cf8c6b5b557f\lance-datafusion-4.0.0\src\sql.rs:113:22
```

DataFusion's SQL parser (the engine behind LanceDB's `dict[str,str]` `add_columns` path)
rejects the `struct(field type, ...)` cast-type syntax outright — a hard parser-level
failure, not a data or runtime issue, and not specific to this particular 3-field shape
(the parser never gets past tokenizing `struct(...)` as a type name). **The table was
left completely unaffected by the failed call** — still 25 columns, still version 4438;
no orphaned or partial version was created.

**`source_span` attempt 2 (fallback) — schema-based `add_columns`:**
`tbl.add_columns(pa.field("source_span", pa.struct([...]), nullable=True))`.
**Succeeds cleanly:** one more MVCC version (`4438 → 4439`), `nullable=True` already
correct (no further fix-up needed), 25 → 26 columns.

Row count, distinct-`chunk_id` count, sample-row content, and disk-footprint checks for
this copy are identical to the string experiment: 15,106 rows unchanged, `data/`
byte-for-byte identical to the pristine base, only `_versions/`/`_transactions/` grew
(same ~194 KB / ~93 KB for 5 versions).

**Verdict: clean in-place extension via a fallback CALL FORM, not a fallback to a
rewrite.** The struct column still lands as a cheap, additive, metadata-only schema
change — it just can't go through the literal `dict[str,str]` SQL-expression call
`_migrate_chunks_schema_if_needed` uses today. It needs the sibling
`add_columns(pa.Field(...))` form for that one column.

### Integrity cross-check (`verify_integrity.py`, pristine base vs. both migrated copies)

- `row_count` / distinct `chunk_id` count: **15,106 / 15,106** in all three (`lancedb`
  base @v4434, `lancedb_string` @v4439, `lancedb_struct` @v4439).
- 5 sampled rows (3 `stmt`-kind + 2 `proof`-kind chunks, so both embedding columns are
  exercised): `embedding_stmt` / `embedding_proof` vectors are **bit-identical**
  (`np.array_equal`, float32) between the pristine base and both migrated copies —
  `add_columns` did not perturb existing embedding data.
- MVCC version history `4434 → 4439` (6 entries) on both migrated copies, one version per
  successful `add_columns` call; the failed struct-SQL-cast attempt left no version /
  transaction trace at all.

## Column-type notes

The 4 pure-scalar columns (`source_revision_id` str, `truncated` bool, `printed_number`
str, `license_ref` str) are unambiguous: `cast(NULL as string)` / `cast(NULL as
boolean)` both work via the exact existing mechanism in both experiments — nothing
column-specific to report.

**`source_span` is the one column where the string-vs-struct decision has a measured
mechanism impact:**

- **As a JSON string (`utf8`):** behaves identically to the 4 scalars —
  `cast(NULL as string)` works, no code-path change needed beyond one more
  `_TEXTBOOK_MIGRATION_DEFAULTS`-style dict entry. Design-level tradeoff (not proven by
  this spike, just flagged): callers must `json.loads`/`json.dumps` the span anchor on
  every read/write, and LanceDB can't push a predicate down into the span's sub-fields
  (e.g. "chunks whose span starts after char N") — it's opaque to the query engine.
- **As a genuine struct (`{dom_anchor, char_start, char_end}`):** the SQL-expression path
  `_migrate_chunks_schema_if_needed` uses today hard-fails at the DataFusion SQL parser
  for *any* struct-typed cast — this isn't a quirk of the particular 3-field shape tried
  here; the parser rejects the `struct(...)` type syntax before it ever reaches
  execution, so it would reject any struct schema the same way. The fix is mechanical,
  not exploratory: route this one column through `add_columns`'s other accepted input
  shape (a bare `pa.Field`/`pa.Schema`) while every other column keeps going through the
  SQL-dict path. Both forms are the same underlying LanceDB `add_columns` primitive;
  neither triggers a table rewrite, re-embed, or index rebuild — confirmed empirically:
  `_indices/` (the ~11 GB HNSW + scalar index tree) was never touched by either
  experiment, and `data/` grew by 0 bytes in both.
- Practical note for m2's implementer (not decided by this spike, out of scope): if
  `get_chunk`/`search_papers` ever need to filter or project into `source_span`'s
  sub-fields, the struct typing is worth the one-column mechanism branch; if
  `source_span` is always read/written whole (client parses the JSON blob), the string
  form is strictly simpler and needs zero migration-code changes at all.

## Implication for m2

**4 of the 5 columns (`source_revision_id`, `truncated`, `printed_number`,
`license_ref`) ride `_migrate_chunks_schema_if_needed` completely unchanged** — m2 can
extend `_TEXTBOOK_MIGRATION_DEFAULTS` with 4 more `cast(NULL as ...)` entries and add the
matching fields to `CHUNKS_SCHEMA_V1`, exactly mirroring the textbook-ingest-m2
precedent. **`source_span` needs one mechanism-level branch, not a data fallback:** if
it's declared as a struct (as brief-2.md's "DOM anchor + char offsets" language implies),
the migration helper must special-case that single column to call
`tbl.add_columns(pa.field("source_span", <struct_type>, nullable=True))` instead of
routing it through the same `dict[str,str]` SQL loop as the other four — a small,
well-understood diff (split the "missing" set into SQL-eligible vs. schema-eligible, and
dispatch accordingly), **not** a full-table rewrite, **not** a re-embed, and **not** an
index rebuild. If m2 instead stores `source_span` as an opaque JSON string, no branch is
needed at all — the existing single-loop mechanism handles all 5 columns verbatim, and
this dry-run *is* m2's migration code, unmodified. Either way, the existing
`alter_columns` nullability fix-up loop stays as a correct defensive no-op here (all 5
new columns infer `nullable=True` from their NULL defaults, unlike m2's non-null
`'arxiv'`/`'arxiv-license'` backfills), and the on-disk cost is negligible — roughly
200–300 KB of new manifest/transaction metadata for 15,106 rows × 5 columns, zero new
data files, zero index rebuild, well under a second of wall time.

## Safety confirmation

This spike operated exclusively on scratch copies under
`scratchpad/spike4/` (`lancedb/` pristine reference, `lancedb_string/` and
`lancedb_struct/` the two experiment copies — all produced by `robocopy` FROM the live
dir, never the reverse). No code in this spike ever called `lancedb.connect(...)` /
`open_table(...)` against the live path, and the dry-run script hard-refuses to run
against any directory whose path doesn't contain a `scratchpad` component. Verified
byte-for-byte before/after this spike: `var/arxmcp/notebooks/bridgeland-stability/lancedb/`
is unchanged — same total size (11 G), same file counts (811 in `data/`, 4,122 in
`_indices/`), same `corpus-version.json` content (`"version": 4434`, `"chunk_count":
15106`), same `chunks.lance/` directory mtime (Jun 3 22:16, predating this session
entirely). **The live table was left completely untouched.**
