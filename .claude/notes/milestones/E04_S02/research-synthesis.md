# E04_S02 Research Synthesis — MVCC via `dataset.checkout(version=N)`

**Sources:** `research-brief-1.md` (Sonnet-A), `research-brief-2.md` (Sonnet-B)
**Status:** convergent on the API. One disagreement on `tbl.version`
vs `merge_result.version` resolved by live test against lancedb 0.30.2
**in favor of the current implementation** (Sonnet-A's recommendation
to switch was based on a partially-correct reading).
**Written:** 2026-05-08

---

## Resolved decisions

### D1. `tbl.checkout(N)` is the correct lancedb 0.30 API

Verified live against lancedb 0.30.2 in the project venv:

- The method is `tbl.checkout(N)` — positional integer, no kwarg
  (the brief's `dataset.checkout(version=N)` language is slightly
  off; ours uses the positional form).
- It mutates the table object **in place** and returns `None`.
- After `tbl.checkout(N)`, `tbl.count_rows()` reflects version N.
- `tbl.checkout_latest()` resets to the live tip.
- Writes against a checked-out table raise `ValueError: ... table
  cannot be modified when a specific version is checked out` —
  LanceDB's own write guard. **No defensive wrapper needed**
  (Sonnet-B's analysis stands).

### D2. The version `write_chunks` returns IS the post-index version, and that's correct

Live test sequence in our `write_chunks`:

```
create_table         → version 1
merge_insert(N rows) → version 2  (== merge_result.version)
create_index(stmt)   → version 3  (skipped if column empty)
create_index(proof)  → version 4  (skipped if column empty)
create_scalar(paper) → version 5  (logged as False on failure)
write_chunks returns → tbl.version == 5
```

**Sonnet-A correctly observed that `tbl.version` ≠ `merge_result.version`
when `_create_indices` runs between** the merge and the version
read. Sonnet-A then recommended switching to `merge_result.version`.

**That recommendation is wrong** for our use case. Reasons:

1. Readers want an **indexed** version. If they pin to
   `merge_result.version` (pre-index), ANN queries fall back to
   brute-force scan. Sonnet-B's experiment confirms LanceDB
   transparently degrades but performance suffers — for a 200K-paper
   corpus that's catastrophic.
2. The post-index version is the natural "ready for queries"
   marker — it represents the dataset state at which both the data
   and the indices needed to query it are in place.
3. Using `tbl.version` insulates `write_chunks`'s callers from
   future changes in `_create_indices` (e.g. adding/removing
   indices) — the returned integer always points to the latest
   version after the entire write_chunks pipeline completes.

**Decision: keep the current `dataset_version = int(getattr(tbl,
"version", 0) or 0)` line.** Add a clarifying comment noting that
`tbl.version` after `_create_indices` IS the post-index version, and
that readers should pin to this for indexed ANN queries.

### D3. `server/corpus.py` shape

```python
"""Read-only LanceDB chunks-table accessor with MVCC version pinning (E04_S02).

No symlink swaps. LanceDB version int IS the corpus_version.
Writers use the current dataset (via ``ingest.store.write_chunks``);
readers call ``open_chunks_table(path, version)`` to pin to a
specific version of the dataset.
"""

import logging
from pathlib import Path

from ingest.schema import CHUNKS_TABLE_NAME

logger = logging.getLogger(__name__)


def open_chunks_table(
    lancedb_path: str | Path,
    version: int | None = None,
) -> "lancedb.table.Table":
    """Open the ``chunks`` table at LanceDB ``version``.

    Closes the AC: returns a read-only handle pinned to ``version``.
    Pass ``version=None`` to open the live tip (latest version).

    Each call returns a FRESH table handle. ``checkout`` mutates the
    table object in place, so passing a shared/cached table to
    ``checkout`` would corrupt other readers' views. Callers that
    want to cache should cache the returned handle, not share the
    intermediate ``open_table`` result.

    Raises ``FileNotFoundError`` if the LanceDB path doesn't exist.
    Raises ``ValueError`` if ``version`` is not a known dataset
    version (LanceDB's own error is re-raised with a clearer message).
    """
    import lancedb  # noqa: PLC0415

    path = Path(lancedb_path)
    if not path.exists():
        raise FileNotFoundError(
            f"LanceDB path does not exist: {path}. "
            f"Run ingest.store.write_chunks first."
        )
    db = lancedb.connect(str(path))
    tbl = db.open_table(CHUNKS_TABLE_NAME)
    if version is not None:
        try:
            tbl.checkout(version)
        except Exception as exc:
            # LanceDB raises a generic Exception/ValueError when the
            # version doesn't exist; re-raise with a clearer message
            # that names the missing version explicitly.
            raise ValueError(
                f"LanceDB version {version} does not exist or is not "
                f"accessible (latest is {tbl.version}); call "
                f"open_chunks_table(...) with a valid version or "
                f"version=None for the live tip"
            ) from exc
    logger.debug(
        "opened chunks table at %s pinned to version %s (live tip = %d)",
        path,
        version if version is not None else "latest",
        tbl.version,
    )
    return tbl
```

Key design points:
- Imports `CHUNKS_TABLE_NAME` from `ingest.schema` — no string
  literal `"chunks"` in `corpus.py`. Mirrors the
  `BGE_M3_COMMIT_SHA` single-source-of-truth pattern from
  `query_encoder.py`.
- Lazy-imports `lancedb` inside the function body — same
  discipline as `ingest.store`.
- Synchronous (LanceDB local mode is synchronous in 0.30.2).
- `version: int | None = None` allows the MCP server to use the
  same function for both pinned and live-tip access.
- Each call opens a fresh table handle — necessary because
  `checkout` mutates in place.
- `Path.exists()` check before `lancedb.connect` so the failure
  mode is a clear `FileNotFoundError` with the path in the
  message.

### D4. `ingest/store.py` docstring update — verbatim AC requirement

The brief AC5 requires the module docstring to state:
> "No symlink swaps. LanceDB version int IS the corpus_version.
> Writers use the current dataset; readers call
> dataset.checkout(version=N)."

Add this paragraph to the existing module docstring. Keep the
existing E03_S01-era documentation; APPEND the AC5 paragraph.

### D5. `tests/test_mvcc.py` shape

```python
"""MVCC tests for the LanceDB chunks dataset (E04_S02)."""

# Use the same _make_corpus / _make_synthetic_embeddings helpers from
# test_store.py — copy them via test fixture / shared helper. (Or
# import via direct module reference, since they're defined in
# test_store.py.)

class TestVersionPinning:
    def test_checkout_pre_and_post_second_write(self, tmp_path):
        # Write 10 chunks, capture version v_a.
        # Write 5 more chunks (different chunk_ids), capture v_b.
        # open_chunks_table(path, v_a).count_rows() == 10
        # open_chunks_table(path, v_b).count_rows() == 15

    def test_checkout_none_returns_latest(self, tmp_path):
        # After two writes, open_chunks_table(path, None) sees the
        # latest data.

    def test_checkout_invalid_version_raises_valueerror(self, tmp_path):
        # write once, capture version. Try open_chunks_table(path, 999).
        # Expect ValueError with a "does not exist" hint.

    def test_checkout_writes_rejected(self, tmp_path):
        # After open_chunks_table(path, v_a), attempting tbl.add([row])
        # raises ValueError. Document LanceDB's built-in guard.

    def test_no_symlinks_under_lancedb_root(self, tmp_path):
        # write once. Path(tmp_path / "lancedb").rglob("*") — no symlinks.

    def test_open_path_does_not_exist_raises(self, tmp_path):
        # FileNotFoundError when path doesn't exist.
```

### D6. Single-source-of-truth scan extension

The existing scan tests cover `ingest/` and parts of `server/`.
Adding `server/corpus.py` introduces a new file the existing scans
already cover (the `BGE_M3_COMMIT_SHA` scan walks `server/`, and
the `pa.schema(` scan walks `ingest/`). One new scan is worth
adding: assert `"chunks"` as a literal does not appear in
`server/corpus.py` (the `CHUNKS_TABLE_NAME` import is the only
allowed reference). Add to `tests/test_mvcc.py::TestSingleSourceOfTruth`.

### D7. No `pyproject.toml` change

`lancedb>=0.6` is the existing pin. The brief suggests "pin
lancedb" but the existing pin is sufficient for this milestone's
scope. A future infra ticket may tighten to `lancedb>=0.30,<1.0`
once we've shipped the full E04 epic; deferring that decision
keeps this milestone focused.

### D8. No symlinks created — already true by absence

`var/arxmcp/index/lancedb/` does not exist on the worktree.
`write_chunks` creates `<lancedb_path>/chunks.lance/` via
LanceDB's native API — never a symlink. AC4 ("No symlinks
created under `var/arxmcp/index/lancedb/`") is satisfied by
construction. Add a regression test that walks the directory
after a write and asserts no `Path.is_symlink()` results.

### D9. HNSW index version semantics

Sonnet-B confirmed experimentally: `checkout(v_old)` followed
by an ANN query falls back to brute-force scan when the index
post-dates the version. LanceDB handles this transparently —
results are correct, performance degrades. Since `write_chunks`
returns the **post-index** version (D2), readers pinning to the
returned version always get an indexed view.

Edge case to document: if a reader pins to a `merge_result.
version` (pre-index, e.g. via the `store-stats.jsonl` log), they
get correct results but slow ANN. This is below the AC threshold
and worth a docstring note in `open_chunks_table` rather than a
guard.

---

## Open questions left to the implementer

- **Should `open_chunks_table` connect to the LanceDB DB on every
  call or cache the connection?** Each call costs ~milliseconds for
  `lancedb.connect`. The MCP server should cache the connection
  and call `open_chunks_table` only on version changes; that's E06
  scope, not ours. For E04_S02, every call connects fresh.
- **Should we add a thin wrapper that returns the version and the
  table together?** Considered, declined. Callers that want both
  can do `tbl.version` after the call. Keeps the API surface
  minimal.

---

## External writes the implementation will require

| Path | Event | Notes |
|---|---|---|
| `ingest/store.py` | source edit | docstring paragraph appending the AC5 statement; clarifying comment on the `dataset_version` resolution line |
| `server/corpus.py` | new file | `open_chunks_table(lancedb_path, version) -> lancedb.Table` |
| `tests/test_mvcc.py` | new file | 6 tests per D5 + D6 |

No `pyproject.toml` change. No new external service. The lancedb
HuggingFace cache is not touched (no model load).
