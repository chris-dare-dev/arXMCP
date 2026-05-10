# E04_S02 Research Brief 1 — MVCC via `dataset.checkout(version=N)`

**Researcher:** Sonnet A (parallel run 1 of 2)
**Date:** 2026-05-08

---

## 1. In-codebase context

### AC1 already satisfied — but the version integer is wrong

`ingest/store.py` line 510:
```python
dataset_version = int(getattr(tbl, "version", 0) or 0)
```
This is executed AFTER `_create_indices(tbl)` is called. The problem: **`create_index` increments the LanceDB dataset version** (confirmed by live test). A write sequence of `merge_insert` + two `create_index` calls produces versions: merge → v2, index₁ → v3, index₂ (or scalar) → v4. `tbl.version` returns the post-index version (e.g. 5 for two writes), not the post-merge version.

Confirmed by running against lancedb 0.30.2 (the venv in this worktree):
```
v_create=1  v_merge1=2  v_after_index1=3  v_merge2=4  v_after_index2=5
checkout(2) → 3 rows   checkout(3) → 3 rows (index-only delta)
checkout(4) → 5 rows   checkout(5) → 5 rows
```

`merge_result.version` (from `MergeResult`) returns the post-merge version (2 and 4 respectively) — the version that represents the data boundary. `tbl.version` returns the post-index version. **AC1 is technically satisfied (it returns an int), but the integer is the post-index version, not the data version.** The correct value to return from `write_chunks` for MVCC purposes is `merge_result.version`, not `tbl.version`.

This is the single most important implementation finding: the existing code returns the WRONG version integer for MVCC pinning.

### `tbl.version` semantics

From lancedb 0.30.2 source (`table.py` line 1927):
```python
@property
def version(self) -> int:
    """Get the current version of the table"""
    return LOOP.run(self._table.version())
```

`tbl.version` reflects the TABLE OBJECT's current version. After `checkout(N)`, `tbl.version` returns N. After `merge_insert`, it returns the post-merge version. After `create_index`, it returns the post-index version. **It is NOT a post-write-only integer.**

### `checkout` API in lancedb 0.30.2

The correct method is `tbl.checkout(version: int)` — **not** `tbl.checkout_version(N)`, not `tbl.as_of(N)`, not a dataset-level call. Confirmed from `table.py` lines 1976–2012:
- `checkout(int)` is an in-place mutation of the table object that pins reads to that version.
- The table returns `count_rows()` reflecting the data at that version.
- `checkout_latest()` returns the table to normal (read-latest) mode.
- Writers must NOT call `checkout` — any write on a checked-out table raises.

The brief's language "`dataset.checkout(version=N)`" (keyword arg) is slightly off — the actual API is positional: `tbl.checkout(N)`.

### Empty table / first version

`db.create_table(name, schema=schema)` creates version 1 (empty table). `checkout(1)` returns 0 rows. The first data-bearing version is 2 (after the first `merge_insert`). **The brief's claim "starting from 1" is correct for the table's existence, but version 1 has 0 rows.** The MVCC test must use `checkout(merge_result.version)`, not `checkout(1)`.

### No symlinks in `var/arxmcp/index/lancedb/`

Confirmed: the directory does not exist at all (`var/arxmcp/index/lancedb/` — `DOES NOT EXIST`). No stale symlink from E01_S06.

### pyproject.toml lancedb pin

```toml
"lancedb>=0.6",
```
Already present. No update needed for E04_S02.

### Module docstring gap — AC5

The current `ingest/store.py` module docstring says:
> "LanceDB returns a new dataset version per write — the writer surfaces that integer to the caller for downstream MVCC pinning (E04_S02)."

But AC5 requires the docstring to state verbatim: "No symlink swaps. LanceDB version int IS the corpus_version. Writers use the current dataset; readers call dataset.checkout(version=N)." The current docstring does not include this. A one-paragraph update is needed.

### `server/__init__.py` and `server/query_encoder.py` conventions

`server/__init__.py` is empty (1 line). `server/query_encoder.py` uses synchronous public API with an async outer layer (`async def encode_query`). `server/corpus.py` should follow the same pattern: synchronous `open_chunks_table(lancedb_path, version)` calling `db.open_table(...)` then `tbl.checkout(version)` — all LanceDB local ops are synchronous in 0.30.2. No `async/await` needed.

### conftest.py autouse fixture

`tests/conftest.py` patches `ingest.store.STORE_STATS_PATH` autouse for all tests. This applies to `test_mvcc.py` automatically — the MVCC test will write store-stats to `tmp_path` without any extra fixture. Clean.

### F3 from E04_S01 critique and index versions

The critique flagged that `create_index` rebuilds on every write. Now confirmed: each `create_index` also produces a new dataset version. The MVCC boundary for data is the `merge_result.version`, not the post-index version. The HNSW index is always built on top of the LATEST data version — `checkout(v_data)` gives read access to the rows at that data version but uses the current index (or no index if checkout predates an index). This is acceptable: checkout for MVCC read-safety is about row-level isolation, not index pinning.

---

## 2. Prior decisions and lessons

### The `dataset_version` resolution bug

The synthesis (D5) says: "return `result.version`" — this was the correct decision from the start. The implementation (landed in `rect(E04_S01)`) switched to `tbl.version` with a comment "stable attribute since lancedb 0.6+". The comment is accurate but the choice is wrong for MVCC: `tbl.version` after `_create_indices` is the post-index version, not the data version.

Fix: change `ingest/store.py` line 510 to:
```python
# Use merge_result.version (set on the merge_insert path) or fall back
# to tbl.version when no rows were written (empty-input path).
dataset_version = merge_result.version if arrow_table.num_rows > 0 else tbl.version
```
This correctly returns the data-boundary version for the MVCC handshake.

### Single-source-of-truth scan tests

- `test_chunker_ids.py` scans `ingest/` for `"v1.0"` — no new `"v1.0"` in `server/corpus.py`, safe.
- `test_query_encoder.py` scans `ingest/` and `server/` for the BGE SHA literal — `corpus.py` doesn't touch BGE SHA, safe.
- `test_store.py::TestSingleSourceOfTruth::test_store_imports_schema_does_not_redefine` scans `store.py` for `pa.schema(` — no change there.

`server/corpus.py` is a NEW file in `server/`. No existing scan test will catch a stray `CHUNKS_TABLE_NAME` redefinition in `server/corpus.py` — it must import from `ingest.schema`. The brief's "single source of truth" discipline applies to all new files.

### `test_mvcc.py` and merge_insert upsert semantics

`TestMixedInsertAndUpdate.test_first_n_then_n_plus_m` (in `test_store.py`) writes 5 then 5+3 and asserts `count_rows() == 8`. That's the latest version. For MVCC: after write 1 (5 rows, `merge_result.version=v1`), after write 2 (8 rows, `merge_result.version=v2`), `checkout(v1)` sees 5 and `checkout(v2)` sees 8. The brief's AC says "write 10 (v1), write 5 more (v2), assert checkout(v1).count == 10 and checkout(v2).count == 15" — since merge_insert UPSERTS, write 2 of 5 new chunks produces 10+5=15 total rows (all distinct chunk_ids). This is consistent.

---

## 3. External sources — lancedb 0.30.2 MVCC API (verified from venv)

### Confirmed correct API call

`tbl.checkout(N)` — in-place, synchronous. NOT `checkout_version`, NOT `as_of`, NOT via underlying lance dataset. The parameter is positional (no `version=` kwarg in the signature despite the brief's `dataset.checkout(version=N)` language).

### Version numbering (verified by running against installed lancedb 0.30.2)

| Operation | Version produced |
|---|---|
| `db.create_table(name, schema=schema)` | 1 (empty rows) |
| `merge_insert.execute(rows)` → first write | 2 |
| `create_index(...)` after first write | 3 |
| `merge_insert.execute(rows)` → second write | 4 |
| `create_index(...)` after second write | 5 |

`checkout(1)` → 0 rows. `checkout(2)` → N rows. `checkout(3)` → N rows (index-only). `checkout(4)` → N+M rows. Data boundaries are at `merge_result.version` values (2, 4), not at post-index values (3, 5).

### `tbl.version` reflects current pinned version

After `tbl.checkout(2)`, `tbl.version` returns 2. After `tbl.checkout_latest()`, it returns the latest (5). Not a post-write-only integer.

### `merge_result.version`

`MergeResult` has attributes: `version`, `num_inserted_rows`, `num_updated_rows`, `num_deleted_rows`, `num_attempts`. `merge_result.version` is the post-merge version integer — the data boundary. This is what `write_chunks` should return.

### HNSW index and versions

Indices are versioned independently from data writes. `checkout(v_data)` gives row access at that version; the HNSW index is always current. A checked-out table at version 2 can still use ANN queries — it uses the latest index, which is valid (it was built on a superset of the rows at version 2, so the index covers all v2 rows).

---

## Open questions

1. **`tbl.version` vs `merge_result.version` — which to return from `write_chunks`?** Opinion: return `merge_result.version`. The data boundary is what readers need for MVCC pinning; the post-index version is an implementation detail of the writer. The MVCC test will use `checkout(merge_result.version)`, so the test will anchor to the right boundary.

2. **`open_chunks_table` return type — `lancedb.Table` or something else?** Return `lancedb.Table` (the standard type). It supports `count_rows()`, `to_arrow()`, and ANN via `tbl.search(...)`. The checkout is in-place; callers should treat the returned object as read-only (documented in the function docstring). Return type annotation: `lancedb.table.Table` (the abstract base; the concrete subclass in local mode is `LanceTable`).

3. **Does eval harness (E05_S01) call `open_chunks_table` synchronously?** Yes — LanceDB's local API is fully synchronous in 0.30.2. `open_chunks_table` does not need to be `async`.

4. **Empty-table edge case — `checkout(0)` or `checkout(1)`?** Version 0 does not exist (versions start at 1). `checkout(1)` returns the empty table (0 rows after `create_table` before any write). The MVCC test should not call `checkout(0)` — it will raise a LanceDB error. The `write_chunks` empty-input path returns `tbl.version` (which is 1 if the table was just created). A caller storing version=1 and later calling `checkout(1)` will see 0 rows — this is correct behavior and should be documented.

5. **The brief AC says `checkout(v1).count == 10 AND checkout(v2).count == 15`.** With the corrected version logic (`merge_result.version` not `tbl.version`): write 10 chunks → `mr1.version=2` (data at v2: 10 rows); write 5 more distinct chunks → `mr2.version=4` (data at v4: 15 rows). So the test must use `checkout(2)` and `checkout(4)`, not `checkout(1)` and `checkout(2)`. OR: the test captures `v1 = write_chunks(...)` and `v2 = write_chunks(...)` and asserts `checkout(v1).count == 10, checkout(v2).count == 15`. This is the correct pattern — don't hardcode 1/2.

---

## External writes the implementation will require

| Path | Action | Notes |
|---|---|---|
| `ingest/store.py` | Edit line 510 | Return `merge_result.version` not `tbl.version`; also update module docstring for AC5 |
| `server/corpus.py` | New file | `open_chunks_table(lancedb_path, version) -> lancedb.Table`; imports `CHUNKS_TABLE_NAME` from `ingest.schema` |
| `tests/test_mvcc.py` | New file | Write 10 + 5, capture both returned versions, assert checkout(v1)==10 and checkout(v2)==15 |
| `pyproject.toml` | No change | `lancedb>=0.6` already present |

The `_create_indices` result merging the version into `dataset_version` also needs updating: currently `dataset_version = int(getattr(tbl, "version", 0) or 0)` happens AFTER `_create_indices` which bumps `tbl.version` by 1 or 2. The fix is to capture `merge_result.version` on the merge path and use that.
