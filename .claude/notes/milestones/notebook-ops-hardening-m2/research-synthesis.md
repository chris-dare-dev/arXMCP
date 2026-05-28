# Research Synthesis — notebook-ops-hardening-m2

**Milestone:** Notebook commits survive power loss; LanceDB format is pinned
**Mode:** standard (2× Sonnet, parallel)
**Sources:** research-brief-1.md (SQLite-durability focus), research-brief-2.md
(LanceDB-format-pin focus, 88 live tool calls)

---

## TL;DR — what to build

Two independent, purely-local changes:

1. **SQLite durability** — in `server/notebooks_store.py::_open_sync` (lines 116–117),
   change `PRAGMA synchronous=NORMAL` → `FULL` and ADD `PRAGMA fullfsync=ON`. One
   regression test reads both pragmas back **from the store's own connection**
   (`store._conn`), asserting `synchronous == 2` and `fullfsync == 1`.

2. **LanceDB format pin** — on each `db.create_table(...)` call (3 sites), pass
   `storage_options={"new_table_data_storage_version": "stable"}`. Add a pin-rationale
   comment in `pyproject.toml`. A test asserts the create path receives the option.

No MCP surface change. No BP1 / tool-schema-hash re-pin. No external writes.

---

## Part 1 — SQLite durability (both briefs AGREE)

### Edit site (verbatim, lines 110–121 of `server/notebooks_store.py`)

```python
def _open_sync() -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        check_same_thread=False,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # ← change to FULL, add fullfsync=ON
    # FM-7: FK enforcement is per-connection ...
    conn.execute("PRAGMA foreign_keys = ON")
```

There is **exactly one** sqlite3 connection open in `notebooks_store.py`: `_open_sync()`
inside the async `NotebooksStore.open()` classmethod. It is cached as `self._conn` and
lives for the whole server lifetime. So a one-time pragma set at open is correct and
sufficient — no per-call connection churn.

**The delta:**
```python
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")     # was NORMAL — durable across power loss
    conn.execute("PRAGMA fullfsync=ON")          # macOS: force F_FULLFSYNC, not neutered fsync
    conn.execute("PRAGMA foreign_keys = ON")
```

### LIVE-VERIFIED pragma semantics (Darwin 25.4.0, Python 3.12 via uv)

| pragma | after set | scope | persists to a fresh connection? |
|---|---|---|---|
| `synchronous=FULL` | reads back `2` | **database-scoped** | YES (reads `2`) |
| `fullfsync=ON` | reads back `1` | **connection-scoped** | **NO — reads `0`** |

**This is the load-bearing test-design fact.** `fullfsync` does NOT persist to disk;
a fresh `sqlite3.connect(db_path)` reads it back as `0`. The regression test therefore
**MUST** read `fullfsync` from the same connection the store opened
(`store._conn.execute("PRAGMA fullfsync")`), NOT from a new connection. (Contrast: the
existing `tests/test_notebook_api.py` lines 1122–1142 `user_version` test uses a
*separate* connection — that works only because `user_version` is database-scoped.)

### Durability rationale (SQLite docs, verbatim)

> "A transaction committed in WAL mode with synchronous=NORMAL might roll back following
> a power loss or system crash." … "In WAL mode when synchronous is FULL, an additional
> sync operation of the WAL file happens after each transaction commit … helps ensure
> that transactions are durable across a power loss."

`fullfsync` is the macOS mechanism that turns the sync into a true `fcntl(F_FULLFSYNC)`
rather than the kernel's deferrable `fsync` (the same neutered-fsync theme as CLAUDE.md
gotcha #9). Together `WAL + FULL + fullfsync=ON` = ACID-durable on macOS.

### Scope decision — what stays NORMAL (recorded)

- **`server/cache_sqlite.py` (Tier-1 retrieval cache)** stays `synchronous=NORMAL`.
  Its source already carries the rationale: *"Safe for a cache where losing the last few
  writes on a crash is a miss, not a correctness failure."* Entirely regenerable from the
  corpus per `.claude/notes/07-multi-agent-caching.md` ("Caching is performance, not
  correctness"). **Do NOT upgrade.**
- **`server/theorem_names_store.py` (line 235)** also stays `NORMAL`. Regenerable via
  `python -m ingest.index_theorem_names`. The brief is silent on it; **do NOT widen
  scope** — a future audit can scope it in.

Only `notebooks.db` holds user-authored, non-regenerable state (notebook membership,
uploaded-paper provenance), so only it earns FULL durability.

### Test design (recommended)

Add a focused test (new `tests/test_notebooks_store.py`, or extend
`tests/test_notebook_api.py`):
1. `store = asyncio.run(NotebooksStore.open(tmp_path / "notebooks.db"))`
2. Read `PRAGMA synchronous` and `PRAGMA fullfsync` **from `store._conn`**.
3. Assert `synchronous == 2` and `fullfsync == 1`.
4. Docstring explains WHY a fresh connection cannot be used for `fullfsync`
   (connection-scoped) — prevents a future maintainer from "simplifying" it into a
   broken separate-connection read.

`assert` in TESTS is fine; the `assert`-ban is for production invariants only.

---

## Part 2 — LanceDB format pin (briefs DIVERGE; resolved)

### The divergence

| | brief-1 | brief-2 (deeper: 88 tool calls) |
|---|---|---|
| **Where** | `storage_options` on `lancedb.connect()` (store.py:812) | `storage_options` on `db.create_table()` (3 sites) |
| **Sites** | store.py + maybe `_notebook_common.py` | store.py:825, index_equations.py:66, index_definitions.py:333 |
| **`_notebook_common.py`** | "verify if it has a connect call" | confirmed **no create_table** — path helper only |

### Orchestrator resolution → adopt brief-2 (create_table-level, 3 sites)

Reasons:
1. **Live-verified to reach the Rust layer.** Brief-2 confirmed
   `db.create_table(..., storage_options={"new_table_data_storage_version": "stable"})`
   passes the option to the Rust extension. Brief-1's connect-level placement was inferred,
   not verified.
2. **`new_table_data_storage_version` is semantically a table-creation option** — placing
   it on `create_table` matches its name and intent, and pins *every* new table regardless
   of which connection created it.
3. **CRITICAL correctness fact (brief-2):** the bare `data_storage_version="stable"` kwarg
   is **silently dropped** by `LanceDBConnection.create_table` in lancedb 0.30.2 — accepted
   in the signature but never forwarded to `LanceTable.create`, and never reaches Rust.
   Using it would be a no-op that *looks* correct. The roadmap AC literally says
   "pass an explicit `data_storage_version`" — **we deviate from that literal wording**
   and use `storage_options={"new_table_data_storage_version": "stable"}`, which is the
   only form that actually works in the installed version. (Deviation recorded below.)

### Edit sites (verbatim, verified on disk this session)

```
ingest/store.py:825          tbl = db.create_table(CHUNKS_TABLE_NAME, schema=CHUNKS_SCHEMA_V1)
ingest/index_equations.py:66     return db.create_table(EQUATIONS_TABLE_NAME, schema=EQUATIONS_SCHEMA_V1)
ingest/index_definitions.py:333  return db.create_table(DEFINITIONS_TABLE_NAME, schema=DEFINITIONS_SCHEMA_V1)
```

`ingest/store.py:825` is the single write-path for BOTH the global corpus LanceDB and the
per-notebook LanceDB (both route through `write_chunks`), so pinning it covers the notebook
storage goal. `_notebook_common.py` has no `create_table` (the brief's AC mention of it is
satisfied vacuously). `re_embed.py` routes staging writes through `write_chunks` → Site 1.

### Installed-version facts (live-verified)

- **lancedb 0.30.2** (`uv.lock`: ARM64 macOS wheel). `pyproject.toml` pin is open-ended
  `"lancedb>=0.6"`.
- **`lance` (pylance) is NOT a standalone import** — bundled inside `lancedb._lancedb`.
- **Default when omitted == `"stable"`** → on-disk Lance format major 3, minor 0 (verified
  by reading the 16-byte file trailer). So the pin makes today's implicit default explicit;
  it does not change current bytes.
- **Existing datasets are unaffected.** `storage_options` on `create_table` only governs
  NEW tables; existing tables take the `open_table` path. `merge_insert` appends data files
  in the table's existing format. No corruption risk, no migration.

### pyproject.toml

Add a pin-rationale comment next to `"lancedb>=0.6"`: the storage format is explicitly
pinned to `"stable"` at every `create_table` so a `uv`/`pip` upgrade can't silently migrate
the on-disk format under a pinned reader. Do **NOT** tighten the upper bound (`<0.31`) in
this milestone — that's a separate decision (FM-E mitigation) if a format regression is
ever observed.

### Test design

A real-LanceDB test (mirroring existing `tests/test_store.py` real-LanceDB tests): write a
table via the pinned path and assert it reads back successfully (proves the pin doesn't
break writes). For asserting the option is actually passed, prefer a spy/monkeypatch on
`db.create_table` (deterministic, fast, no model load) asserting the call receives
`storage_options={"new_table_data_storage_version": "stable"}`. Avoid the brittle 16-byte
trailer read in the test.

---

## Failure modes (from brief-2, condensed)

- **FM-A** uv-upgrade default bump → reader/writer skew. Mitigation: explicit pin survives
  upgrade; visible in pyproject.toml. MVCC integer (`corpus-version.json`) is
  format-independent.
- **FM-B** pinning a rejected value → write crash. Mitigation: pin `"stable"` (documented
  default, can't be removed without major break).
- **FM-C** existing unpinned datasets + new pinned writes → break old reads. Mitigation:
  tested live — no break; create_table options affect new tables only.
- **FM-E** `"stable"` alias meaning shifts in a future release. Mitigation: pyproject.toml
  comment makes intent visible; reader gets a clear lancedb error (not silent corruption);
  upper-bound tightening deferred.
- **FM-F** the silent-drop trap (see resolution above) — code comment must cite it so a
  maintainer doesn't "fix" it back to the deprecated kwarg.

---

## Acceptance criteria → verifiable artifacts

| AC | Artifact |
|---|---|
| `notebooks_store.py` durable conn uses `synchronous=FULL` + `fullfsync=ON`; regression test asserts both | 2-line edit in `_open_sync` + new test reading from `store._conn` |
| `cache_sqlite.py` may stay NORMAL — decision recorded | recorded above (regenerable cache); no edit |
| LanceDB writes pass explicit storage version; pyproject.toml pin-rationale comment | 3 `create_table` edits + pyproject comment + spy test |
| G/W/T: after a committed write, `synchronous == 2` and `fullfsync == 1` | the SQLite regression test |

---

## Deviations from the brief (recorded)

1. **AC wording vs reality.** AC says "pass an explicit `data_storage_version`" and lists
   `tools/_notebook_common.py` as an edit site. Live verification (brief-2) shows: (a) the
   bare `data_storage_version` kwarg is silently dropped in lancedb 0.30.2 — the working
   mechanism is `storage_options={"new_table_data_storage_version": "stable"}`; (b)
   `_notebook_common.py` has no `create_table` (path helper only). Actual edit sites are the
   3 `create_table` calls in `ingest/store.py`, `ingest/index_equations.py`,
   `ingest/index_definitions.py`. This is a faithful realization of the AC's intent
   (durable on-disk format pin), not a scope change.

2. **Scope held tight.** `theorem_names_store.py` is intentionally NOT upgraded (regenerable
   cache, brief is silent on it). No upper-bound tighten on lancedb.

---

## Open questions

- **Resolved by brief-2:** `_notebook_common.py` has no independent connect/create_table —
  no edit there. `open_table` needs no storage_options (format is immutable per dataset).
- No remaining blockers. Implementation can proceed inline (small: 2 prod files +
  pyproject.toml + 1–2 test files, < 5 files, well under 500 LOC).

## External writes the implementation will require

**None.** Purely local: `server/notebooks_store.py`, `ingest/store.py`,
`ingest/index_equations.py`, `ingest/index_definitions.py`, `pyproject.toml`, tests.
No git push (push is per-event authorized), no GitHub issue/PR, no infra, no 3rd-party API.

---

## Orchestrator synthesis note

The two briefs agreed fully on the SQLite half and diverged on the LanceDB half. The
divergence was resolved in favor of brief-2's `create_table`-level placement because it was
live-verified to reach the Rust layer and it surfaced the silent-drop trap that brief-1's
inferred connect-level approach would not have caught. Both briefs independently confirmed:
zero external writes, no MCP/BP1 impact, and that `cache_sqlite.py` correctly stays NORMAL.
