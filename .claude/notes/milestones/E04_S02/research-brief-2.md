# E04_S02 Research Brief 2 — MVCC via `dataset.checkout(version=N)`

---

## 1. In-codebase context

### `ingest/store.py` — the version-resolution line

At line 510 of `ingest/store.py`:

```python
dataset_version = int(getattr(tbl, "version", 0) or 0)
```

**Is `tbl.version` the POST-write version?** Yes — confirmed experimentally.
After `merge_insert(...).execute(data)` returns, `tbl.version` is already the
newly minted version number. With lancedb 0.30.2 installed in `.venv`:

- `db.create_table(...)` → `tbl.version == 1`
- First `merge_insert` → `tbl.version == 2`
- Second `merge_insert` → `tbl.version == 3`
- `checkout(2).count_rows()` returns 2 (the first-write row count)

So `dataset_version` in `write_chunks` is the post-write version, not the
version the table was opened at. The comment on that line is therefore accurate:
"Resolve the new dataset version." The `or 0` fallback is defensive; in practice
`tbl.version` is always a positive integer after the write.

### `server/__init__.py`

The file is **1 line** (empty or whitespace only). `server/corpus.py` is a
straightforward sibling addition — no `__init__.py` changes required.

### `server/query_encoder.py` — conventions to replicate

The docstring shape: module-level, multi-paragraph, references milestone IDs
(`E03_S03`), cites 08-security-observability-ops.md threats by number, and uses
bold labels for subsections (e.g. `**GIL release rationale**`). Every public
function has a concise one-sentence summary followed by a `Closes Fn from …`
cross-reference pattern. Imports are grouped: stdlib → numpy → project-internal,
with `lancedb` as a `noqa: PLC0415` lazy import inside the function body.

The lazy-import pattern (not used in `query_encoder.py` itself for numpy but
used in `write_chunks` for lancedb) should be replicated in `open_chunks_table`
— import `lancedb` inside the function body.

The `BGE_M3_COMMIT_SHA` single-source-of-truth rule (imported from
`ingest.embedder`, never redeclared) is the model for the
`CHUNKS_TABLE_NAME` rule in `corpus.py`: import from `ingest.schema`, never
re-declare the string `"chunks"`.

### `05-storage-and-indexing.md` — MVCC discipline

The document is explicit:

> Manual symlink swaps (`current -> v0007`) are **explicitly prohibited** under
> the new design. Use LanceDB's native MVCC mechanism instead.

And in the daily ops cadence at 04:05 UTC:

> Update `corpus-version.json` atomically (no symlink swap; see E04_S02 in
> roadmap/E04-vector-store.md)

The storage doc also describes the fallback under `08-security-observability-ops.md`:

> LanceDB corrupt on restart → Fall back to previous dataset version via
> `dataset.checkout(version=N-1)` (see E04_S02 in roadmap); alert. No symlink swap.

There is **no `corpus-version.json` writer in E04_S01** — the store writes
`store-stats.jsonl` which records `lancedb_version`. E04_S02's scope is
`open_chunks_table`; the `corpus-version.json` write is a reader-pinning concern
deferred to E06.

### `08-security-observability-ops.md` — concurrency and observability hooks

Threat 1 (path traversal) applies to any function accepting a filesystem path
from untrusted input. The `arxmcp.corpus_version` OTel span attribute is listed
among required child-span attributes; `open_chunks_table` is the function that
resolves the version, making it the natural place to log `corpus_version`.
The MVCC layer is cited under failure modes: no additional locking is required.

### `var/arxmcp/index/lancedb/`

The directory **does not exist** (`ls` returns `DIRECTORY_NOT_FOUND`). No
symlink from E01_S06 was created here; the AC "No symlinks under
`var/arxmcp/index/lancedb/`" is already satisfied by absence.

### `pyproject.toml` — lancedb pin

```toml
"lancedb>=0.6",
```

This is a **lower-bound-only pin**, not an exact pin. The risk note in the
brief ("verify the API name in tests") is real. The installed version in `.venv`
is `0.30.2`. The `>=0.6` lower bound covers both old (`table.version`) and the
0.30 API. The brief asks to "pin lancedb" — but `pyproject.toml` currently uses
`>=`. An exact pin (`lancedb==0.30.2`) would be more defensive; that is a call
for the implementer, not a blocker.

---

## 2. Prior decisions and lessons

### `_validate_paper_id` discipline and path traversal for `lancedb_path`

`open_chunks_table(lancedb_path: str, version: int)` accepts a filesystem path
from the caller. In the MCP server (E06), `lancedb_path` will come from a
config value, not from tool input — so it is trusted. However, the validated
pattern (E03_S02 F13, E04_S01 F1) is: any function that interpolates a
caller-supplied string into a path must validate it. Recommendation: **do not
validate `lancedb_path` with a regex** (it is a structured directory path, not
an arXiv ID), but DO `Path(lancedb_path).resolve()` and assert it is under an
expected root if called from an untrusted context. For E04_S02 scope, a simple
`Path(lancedb_path).exists()` check with a clear `FileNotFoundError` is
sufficient and avoids silent path confusion.

### Atomic-write discipline

`open_chunks_table` is read-only. No atomicity concern.

### "Verify the artifact, not the audit trail" (E03_S02 F1, E04_S01 F1)

Should `open_chunks_table` verify the version exists before calling
`tbl.checkout(version)`? Experimentally: calling `tbl.checkout(999)` on a
3-version table raises an exception from LanceDB. Trusting LanceDB's error is
sufficient here — there is no "audit trail" to verify against. **Do not add a
pre-check.** The pattern is: call `tbl.checkout(version)`, let LanceDB raise
if the version is absent, and convert the LanceDB exception into a
`ValueError` with a clear message (`f"version {version} does not exist ..."`).

### Single-source-of-truth drift candidates

`server/corpus.py` will reference the `chunks` table by name. The existing
scan test (`test_chunker_ids.py`, `test_query_encoder.py`) enforces that
`BGE_M3_COMMIT_SHA` is not re-declared. The analogous rule: **import
`CHUNKS_TABLE_NAME` from `ingest.schema`** — never write the string literal
`"chunks"` in `server/corpus.py`. This should be covered by a companion scan
in `tests/test_mvcc.py` or `tests/test_store.py`. Add a scan assertion:
`grep` that `corpus.py` does not contain the bare string `"chunks"` as a
literal (only the imported constant is allowed).

---

## 3. External sources — LanceDB 0.30 checkout API

All results confirmed against lancedb 0.30.2 in the project `.venv`.

### Method name

`tbl.checkout(version)` is the correct method. It exists and works.

### Mutates in-place or returns a new Table?

`tbl.checkout(v1)` **mutates the table object in place and returns `None`**.
After `checkout(v1)`, `tbl.count_rows()` reflects v1, and `tbl.version`
reports v1. To return to the latest version: `tbl.checkout_latest()` (also
exists and returns `None`).

Implication for `open_chunks_table`: the function must **open a fresh table
handle** (via `db.open_table(CHUNKS_TABLE_NAME)`), call `.checkout(version)` on
it, and return that handle. Do NOT call `checkout` on the shared table reference
used by other readers — that would mutate their view.

### Write-rejection after checkout

Confirmed: after `tbl.checkout(v1)`, any write attempt raises:

```
ValueError: Invalid input, table cannot be modified when a specific version is checked out
```

This is LanceDB's own write guard. No wrapper is needed for defense-in-depth —
LanceDB already rejects writes.

### Version numbering — 1-indexed or 0-indexed?

**1-indexed.** `db.create_table(...)` creates version `1`. The first
`merge_insert` creates version `2`. There is no version `0`.

### HNSW index version semantics after `checkout`

Experimentally: `tbl.checkout(v1)` followed by `.search(query_vec).limit(1)`
**succeeds and returns results** even when v1 pre-dates any `create_index` call.
LanceDB falls back to a brute-force scan when the HNSW index does not exist in
the checked-out version's manifest. This is transparent to the caller — results
are correct, performance degrades.

Critical implication: if a reader pins to an early version (before the
`create_index` call), ANN queries will do a full scan. For our MVCC test
(`test_mvcc.py`), this means `count_rows` assertions will pass; ANN assertions
against old versions will also return correct results (brute-force) but slowly.
For E06's server pinning, the version pinned at startup should be one that has
an HNSW index (i.e., `write_chunks` always calls `_create_indices` before
returning the version). This is already guaranteed by `ingest/store.py`'s write
path. No additional AC needed here, but it is worth documenting.

---

## Open questions

1. **Should `open_chunks_table` accept `version: int | None` with `None` =
   "latest"?** The brief mandates `version: int`, but `None`-default would let
   the MCP server call it without knowing the version (useful at E06). Opinion:
   add `version: int | None = None`; when `None`, skip `checkout` and return the
   live table handle. This costs nothing and avoids a second function.

2. **Path validation for `lancedb_path`.** For E04_S02 scope, a
   `Path(lancedb_path).resolve()` existence check is sufficient. Full path-traversal
   defense belongs at the MCP-tool input layer (E06), not here.

3. **HNSW index versioning.** When `checkout(v_old)` runs an ANN query, LanceDB
   uses brute-force scan if the index was created in a later version. Correct
   results, degraded performance. Callers should pin to a version that includes
   the HNSW build (guaranteed by `write_chunks` always calling `_create_indices`).
   Document in `open_chunks_table` docstring.

4. **Should `open_chunks_table` wrap the table in a write-rejection proxy?**
   No. LanceDB already raises `ValueError` on writes to a checked-out table.
   Defense-in-depth here is redundant and adds complexity with no benefit.

5. **`tbl.checkout` mutates in place — concurrency concern.** If the server
   holds one table handle and calls `checkout` on it, concurrent queries against
   that handle will see the pinned version. This is correct and safe — but it
   means `open_chunks_table` must return a **per-call fresh handle**, not a
   shared one. The server (E06) should cache the handle, not call
   `open_chunks_table` on every request.

---

## External writes this implementation requires

1. **`server/corpus.py`** — new file. Exports `open_chunks_table(lancedb_path,
   version=None) -> lancedb.Table`. Imports `CHUNKS_TABLE_NAME` from
   `ingest.schema`. Lazy-imports `lancedb` inside the function body. Contains a
   module-level docstring following the `query_encoder.py` shape.

2. **`tests/test_mvcc.py`** — new file. Writes 10 chunks (captures `v_a`),
   writes 5 more (captures `v_b`), asserts `open_chunks_table(path, v_a)
   .count_rows() != open_chunks_table(path, v_b).count_rows()`. Also asserts
   that no write to `v_a` table succeeds (confirming checkout write guard).

3. **`ingest/store.py` docstring update** — one-line addition to the module
   docstring stating: "No symlink swaps. LanceDB version int IS the
   corpus_version. Writers use the current dataset; readers call
   `dataset.checkout(version=N)`." (The brief's exact required wording.)

4. **`pyproject.toml`** — `lancedb>=0.6` is already present. Consider tightening
   to `lancedb>=0.30` to match the tested API surface; an exact pin to `0.30.2`
   is optional but reduces API-drift risk.
