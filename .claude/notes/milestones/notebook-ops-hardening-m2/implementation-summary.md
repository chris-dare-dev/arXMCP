# Implementation Summary — notebook-ops-hardening-m2

**One-liner:** `notebooks.db` now opens with `synchronous=FULL` + `fullfsync=ON`
(crash-durable, user-authored state), and every LanceDB `create_table` pins the
on-disk format via `storage_options={"new_table_data_storage_version": "stable"}`.

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline (orchestrator, main session).

---

## What landed

### SQLite crash durability (`server/notebooks_store.py`)
`_open_sync()` (the single, lifetime-cached `notebooks.db` connection) now sets
`PRAGMA synchronous=FULL` + `PRAGMA fullfsync=ON` (was `NORMAL`, no fullfsync). A
block comment explains the why: `notebooks.db` holds user-authored, non-regenerable
state; `WAL + NORMAL` can roll back the last committed transaction on power loss;
`fullfsync` is the macOS mechanism (`F_FULLFSYNC`) that defeats the kernel's
deferrable `fsync`, and it is **connection-scoped** so it must be set on every open.

### LanceDB on-disk format pin
- New shared constant `ingest/schema.py::LANCE_STORAGE_OPTIONS =
  {"new_table_data_storage_version": "stable"}` with a comment documenting the
  silent-drop gotcha on the bare `data_storage_version` kwarg (lancedb 0.30.2).
- Wired into all 3 `db.create_table(...)` sites: `ingest/store.py` (chunks),
  `ingest/index_equations.py` (equations), `ingest/index_definitions.py`
  (definitions).
- `pyproject.toml`: pin-rationale comment next to `lancedb>=0.6` (upper bound
  intentionally NOT tightened this milestone).

### Tests (`tests/test_notebook_durability.py`, new — 11 tests)
- `TestNotebookStoreDurabilityPragmas` — G/W/T: after a committed write,
  `synchronous == 2 (FULL)` and `fullfsync == 1`, read from `store._conn`;
  WAL preserved; and a test proving `fullfsync` does NOT persist to a fresh
  connection (locks the test-design rationale).
- `TestDurabilityScope` — source guards: `cache_sqlite.py` stays `NORMAL`
  (regenerable cache); `notebooks_store.py` uses `FULL` + `fullfsync`.
- `TestLanceFormatPin` — constant value; a runtime spy proving `write_chunks`
  passes the pin to `create_table`; a pinned table reads back; a parametrized
  source guard that all 3 sites pin and none uses the bare dropped kwarg.

---

## Acceptance criteria status

- [x] **`notebooks_store.py` durable conn uses `synchronous=FULL` + `fullfsync=ON`;
  regression test asserts both.** `_open_sync` edited; `test_synchronous_full_and_
  fullfsync_on_after_committed_write` asserts both off `store._conn`.
- [x] **`cache_sqlite.py` may stay NORMAL — decision recorded.** Recorded in the
  synthesis + code comment + locked by `test_cache_sqlite_stays_normal`. (Also held
  `theorem_names_store.py` at NORMAL — regenerable; out of scope.)
- [x] **LanceDB writes pass an explicit storage version; pyproject.toml pin-rationale
  comment.** Realized as `storage_options={"new_table_data_storage_version":
  "stable"}` on all 3 `create_table` sites + `LANCE_STORAGE_OPTIONS` constant +
  pyproject comment. (See deviation #1.)
- [x] **G/W/T: after a committed write, `synchronous == 2` and `fullfsync == 1`.**
  Covered by the regression test.

---

## Deviations from the brief

1. **Mechanism + edit sites (LanceDB half).** The AC literally says "pass an explicit
   `data_storage_version`" and names `tools/_notebook_common.py` as an edit site.
   Live verification (research-brief-2, 88 tool calls) showed: (a) the bare
   `data_storage_version` kwarg is **silently dropped** by
   `LanceDBConnection.create_table` in lancedb 0.30.2 — it never reaches the Rust
   layer; the working form is `storage_options={"new_table_data_storage_version":
   "stable"}`; (b) `_notebook_common.py` has **no** `create_table` (it is a path
   helper; notebook writes route through `ingest/store.py::write_chunks`). The actual
   sites are the 3 `create_table` calls in `ingest/{store,index_equations,
   index_definitions}.py`. This faithfully realizes the AC's intent (durable on-disk
   format pin), confirmed live before commit (`create_table` accepts the option and
   the table reads back).

2. **Scope held tight.** `theorem_names_store.py` is intentionally NOT upgraded
   (regenerable cache, brief silent on it). `lancedb` upper bound NOT tightened.

---

## Test surface

- New: `tests/test_notebook_durability.py` (11 tests).
- Re-ran affected modules green: `test_store.py`, `test_notebook_api.py`,
  `test_definitions_index.py`, `test_embed_equations.py`, `test_equation_index.py`,
  `test_extract_equations.py`.

## External writes required

**None.** Purely local. (Push at finalize is per-event authorized by the user.)
