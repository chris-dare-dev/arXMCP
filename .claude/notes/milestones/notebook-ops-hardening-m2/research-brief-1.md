# Research Brief — notebook-ops-hardening-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T17:21:30Z

---

## In-codebase context

### Connection factory: ONE factory, ONE connection, per-server lifetime

`server/notebooks_store.py` has exactly one place where a `sqlite3.Connection` is
opened: the `_open_sync()` inner function inside `NotebooksStore.open()` (async
classmethod). There is no module-level connection, no second factory, no context manager
that opens-and-closes on every call. The connection is cached as `self._conn` in the
`NotebooksStore` instance and lives for the entire server lifetime. The pattern is
identical to `server/cache_sqlite.py::Tier1Store.open`.

**Verbatim connection-open code (lines 110–121):**

```python
def _open_sync() -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        check_same_thread=False,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # ← must change to FULL
    # FM-7: FK enforcement is per-connection in SQLite (default
    # OFF). MUST set before any DELETE on the notebooks table
    # for the cascade to fire.
    conn.execute("PRAGMA foreign_keys = ON")
```

The pragma change is a two-line delta at lines 116–117 inside `_open_sync`. There are no
other connection opens in `notebooks_store.py`.

### `cache_sqlite.py` — correctly stays at NORMAL

`server/cache_sqlite.py` lines 244–248 set `synchronous=NORMAL` with an explicit
rationale comment already in the source:

> "synchronous=NORMAL: SQLite flushes at checkpoint boundaries, not on every commit.
> Safe for a cache where losing the last few writes on a crash is a miss, not a
> correctness failure."

This rationale cites `.claude/notes/07-multi-agent-caching.md` §Failure modes:
"Cache layer crash / OOM → Fall through to recompute; log; alert. Caching is
performance, not correctness." The Tier-1 cache is entirely regenerable from the corpus.
The milestone brief says NORMAL may stay — confirmed correct, the decision is already
documented in the source.

### `theorem_names_store.py` — same NORMAL, NOT in scope

`server/theorem_names_store.py` line 235 also sets `synchronous=NORMAL`. The theorem-
names table is regenerable via `python -m ingest.index_theorem_names` (the source at
line 242–250 warns on DROP-and-recreate). The milestone brief is silent on this store.
**Do NOT upgrade it in this milestone** — it is regenerable cache, same as Tier-1. A
future audit can scope it in; do not widen scope here.

### `fullfsync` is connection-scoped, not database-scoped

**LIVE VERIFICATION on this machine (macOS Darwin 25.4.0, Python 3.12 via uv):**

```
In-memory: synchronous=2, fullfsync=1
Conn1 (after set): synchronous=2, fullfsync=1
Conn2 (fresh, same file): synchronous=2, fullfsync=0  ← KEY FINDING
Conn3 (WAL+FULL+fullfsync): journal_mode=wal, synchronous=2, fullfsync=1
```

**`synchronous=FULL` yields integer `2`.** `fullfsync=1` after `PRAGMA fullfsync=ON`.
**Both are connection-scoped, not database-scoped.** A fresh connection to the SAME
FILE reads back `synchronous=2` (persists) but `fullfsync=0` (does NOT persist). This
means `PRAGMA fullfsync=ON` MUST be set on every new connection; it cannot be set once
and relied on at re-open. Since `NotebooksStore` opens exactly one connection at
lifespan startup and holds it for the server lifetime, setting it inside `_open_sync`
is the correct and sufficient location. The regression test must NOT open a separate
sqlite3 connection to read back `fullfsync` — it must call through the
`NotebooksStore.open()` API and read the pragma on the SAME connection, or use the
existing `_conn` attribute on the returned store.

### `synchronous=FULL` in WAL mode — durability guarantee

From the SQLite docs (https://www.sqlite.org/pragma.html, accessed 2026-05-28):

> "In WAL mode when synchronous is FULL, an additional sync operation of the WAL file
> happens after each transaction commit. The extra WAL sync following each transaction
> helps ensure that transactions are durable across a power loss. ... FULL is atomic,
> consistent, isolated, and durable (ACID) in WAL mode."

> "WAL mode does lose durability [with synchronous=NORMAL]. A transaction committed
> in WAL mode with synchronous=NORMAL might roll back following a power loss or system
> crash."

This confirms the brief's concern: `WAL + NORMAL` on macOS means a committed notebook
write can be lost on power loss. `WAL + FULL + fullfsync=ON` provides ACID durability
including on macOS (where `fsync` is neutered but `F_FULLFSYNC` is not).

### Design constitution: no durability clause found

Neither `.claude/notes/05-storage-and-indexing.md` nor `.claude/notes/07-multi-agent-
caching.md` nor `.claude/notes/08-security-observability-ops.md` contains any
constraint on `synchronous` or `fullfsync` pragmas. The roadmap at
`plans/notebook-ops-hardening-roadmap.md` §ASSUME explicitly states:
"`synchronous=FULL` + `fullfsync=ON` on the low-write `notebooks.db` has negligible
perf impact."

### LanceDB `data_storage_version` — DEPRECATED in 0.30.x, approach changes

**LIVE VERIFICATION (lancedb 0.30.2 installed):**

```python
# create_table signature excerpt:
data_storage_version: Optional[str] = None  # default "stable"
# Docstring: "Deprecated. Set `storage_options` when connecting to the database
#  and set `new_table_data_storage_version` in the options."
```

The `data_storage_version` parameter on `db.create_table()` is **deprecated** as of
lancedb 0.30.x. The modern API pins format version via `storage_options` at
`lancedb.connect()` time:

```python
db = lancedb.connect(str(path), storage_options={"new_table_data_storage_version": "stable"})
```

`data_storage_version` defaults to `"stable"` when `None` (confirmed from source).
The default is already the stable format. However, lancedb 0.30.x also uses
`enable_v2_manifest_paths` (deprecated, default False = v1 paths) vs the
`new_table_enable_v2_manifest_paths` storage option. On this install, newly created
tables have `uses_v2_manifest_paths() == True` (observed in testing), suggesting the
default is now v2 manifest paths.

**Implication for `ingest/store.py`:** The `write_chunks` function calls
`lancedb.connect(str(target_path))` at line 812 with no `storage_options`. The current
behavior relies on the lancedb default (stable format). A future `uv`/`pip` upgrade
that changes the default would silently alter the on-disk format. The correct fix is
to pass `storage_options={"new_table_data_storage_version": "stable"}` to the
`lancedb.connect()` call in `write_chunks` (and in `_notebook_common.py` if it has
a separate connect call). Check `tools/_notebook_common.py` for any direct
`lancedb.connect()` call.

**`tools/_notebook_common.py`:** From grep: this file defines `notebook_lancedb_path`
(a path helper) but does not appear to have a `lancedb.connect()` call of its own — the
actual write goes through `write_chunks` in `ingest/store.py`. Verify at implementation
time.

### Existing test pattern for PRAGMA assertions

From `tests/test_notebook_api.py` lines 1122–1142, the established pattern is:

```python
async def _open_close() -> int:
    store = await NotebooksStore.open(db_path)
    try:
        conn = sqlite3.connect(str(db_path))  # ← SEPARATE connection reads user_version
        try:
            cur = conn.execute("PRAGMA user_version")
            return int(cur.fetchone()[0])
        finally:
            conn.close()
    finally:
        await store.close()
```

**IMPORTANT:** The `PRAGMA user_version` test pattern opens a SEPARATE sqlite3 connection
to read it back because `user_version` IS a database-scoped pragma (persists to disk).
For `fullfsync`, this pattern would return `0` (wrong) because `fullfsync` is
connection-scoped. The regression test for this milestone MUST read `fullfsync` on the
SAME connection that `NotebooksStore` opened, not a fresh one. The correct approach:

Option A: Expose a test-only method on `NotebooksStore` that returns pragma values via
`self._conn.execute("PRAGMA fullfsync")`.

Option B: Accept that both pragmas are returned from the SAME store's connection — call
`NotebooksStore.open()`, then call a helper or directly access `store._conn` in the
test.

**Recommend Option B** (direct `store._conn` access in the test) to avoid adding a
test-only method to production code. The test is already in the `tests/` module and
can access private attributes. All other PRAGMA reads in this test file use a separate
connection — but that works for `user_version` (persisted). The test docstring must
document why `fullfsync` cannot be read from a fresh connection.

---

## Prior decisions and lessons

- Recent git log shows `corpus-integrity-observability-m1` (2 commits ago) landed
  changes to `ingest/store.py`. The `write_chunks` function was modified for
  `tbl.count_rows()` (O(1) marker counts). Implementation must not interfere with this.
- The three-commit pattern for this milestone: `feat(server)` + `rect(server)` +
  `chore(notes)`.
- No existing test asserts `synchronous` or `fullfsync` pragmas anywhere in `tests/`.
  This is a new test pattern. Mirror the `asyncio.run()` + `NotebooksStore.open()` style
  in `tests/test_notebook_api.py`.
- `assert` is banned for invariants (CLAUDE.md §4.7) — use `if ... raise RuntimeError`.
  Tests must use `assert` for test assertions (that is fine), not in production code.
- `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` is load-bearing — do not remove.
- The milestone is purely a server pragma change + one new test + a lancedb connect
  call change + `pyproject.toml` comment. Does NOT touch `server/tools.py::ALL_TOOLS`,
  so `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning.

---

## External sources

- **SQLite PRAGMA synchronous** (https://www.sqlite.org/pragma.html#pragma_synchronous):
  "WAL mode does lose durability [with NORMAL]. A transaction committed in WAL mode
  with synchronous=NORMAL might roll back following a power loss or system crash."
  "FULL (2) is ACID in WAL mode." Verified live.
- **SQLite PRAGMA fullfsync** (https://www.sqlite.org/pragma.html#pragma_fullfsync):
  "Only Mac OS X supports F_FULLFSYNC." The pragma is the mechanism that forces macOS
  to issue a true `fcntl(F_FULLFSYNC)` rather than the neutered `fsync` that the OS
  can defer. Connection-scoped (confirmed by live test on Darwin 25.4.0).
- **lancedb 0.30.2** (installed): `data_storage_version` parameter on `create_table`
  is deprecated. Default is `"stable"` per docstring. Modern pin uses
  `storage_options={"new_table_data_storage_version": "stable"}` at connect time.
  Live-tested: `uses_v2_manifest_paths()` returns `True` for newly created tables.

---

## Recommendation

**For the SQLite half:** Add `conn.execute("PRAGMA fullfsync=ON")` immediately after
`conn.execute("PRAGMA synchronous=FULL")` at lines 116–117 in `_open_sync` inside
`NotebooksStore.open()`. No other files need to change for the SQLite half. Write a
single synchronous test in `tests/test_notebook_api.py` (or a new
`tests/test_notebooks_store.py`) that:
1. Calls `asyncio.run(NotebooksStore.open(tmp_path / "notebooks.db"))`
2. Reads `PRAGMA synchronous` and `PRAGMA fullfsync` directly from `store._conn`
   (NOT from a fresh sqlite3 connection — `fullfsync` is connection-scoped and will
   read back as `0` from a new connection)
3. Asserts `synchronous == 2` and `fullfsync == 1`

**For the LanceDB half:** Change `lancedb.connect(str(target_path))` in
`write_chunks` (`ingest/store.py` line 812) to:
```python
db = lancedb.connect(str(target_path), storage_options={"new_table_data_storage_version": "stable"})
```
Add a comment to `pyproject.toml` near the `lancedb>=0.6` dependency explaining that
`"stable"` is the explicit format pin (do NOT upgrade to `"legacy"` — stable is the
modern default since 0.21+; this comment makes the pin intent visible). Do NOT use the
deprecated `data_storage_version` kwarg on `create_table` — it emits deprecation
warnings and is removed in future versions. **First verify** that `tools/_notebook_common.py`
has no independent `lancedb.connect()` call; if it does, apply the same storage_options
there.

---

## Open questions

1. **Does `tools/_notebook_common.py` have an independent `lancedb.connect()` call?**
   The grep results show it defines path helpers and imports `write_chunks`, but the
   implementer must confirm at implementation time. If yes, add `storage_options` there
   too.

2. **lancedb `open_table` — does it need `storage_options` too?** `write_chunks` also
   calls `db.open_table(CHUNKS_TABLE_NAME)` for existing tables. The storage format is
   set at CREATE time and is immutable per-dataset; `open_table` reads whatever format
   is on disk. No change to `open_table` is needed for existing datasets.

These are quick verifications, not blockers — the implementer resolves them in 5 minutes
with a grep. Both are expected-to-be-false (no change needed), but must be confirmed.

---

## External writes the implementation will require

None — this milestone is purely local.

- No git push (push is per-event authorized by the user)
- No GitHub issue / PR creation
- No infra mutation
- No external API call
