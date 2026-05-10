# E04_S01 Research Synthesis — `chunks` LanceDB table v1 schema

**Sources:** `research-brief-1.md` (Sonnet-A), `research-brief-2.md` (Sonnet-B)
**Status:** convergent. One minor divergence (HNSW small-dataset behavior)
resolved in favor of Researcher B's more precise reading.
**Written:** 2026-05-08

---

## Resolved decisions (both briefs agree)

### D1. `pyproject.toml` adds `lancedb` + `pyarrow` to runtime dependencies

Confirmed: neither dependency is currently listed. Add both with
explanatory comments matching the existing style:

```toml
"lancedb>=0.6",
"pyarrow>=14.0",
```

### D2. `EmbedRecord` is a new dataclass — defined in this milestone

The brief's signature `write_chunks(chunks: list[ChunkRecord], embeddings:
EmbedRecord, lancedb_path: str) -> int` references `EmbedRecord` but never
defines it. Concrete shape (single source of truth in
`ingest/schema.py`):

```python
@dataclass
class EmbedRecord:
    """Embedding payload for one or more papers, ready to write to LanceDB.

    The four ``*_ids`` / ``*_proof`` lists are the row-aligned outputs of
    the embedder's NPZ store; concatenating multiple per-paper NPZs into
    one ``EmbedRecord`` is the responsibility of the caller (a future
    pipeline driver).
    """
    chunk_ids_stmt: list[str]      # aligned with embedding_stmt rows
    embedding_stmt: np.ndarray     # shape (sum_N_stmt, EMBEDDING_DIM), float32
    chunk_ids_proof: list[str]     # aligned with embedding_proof rows
    embedding_proof: np.ndarray    # shape (sum_N_proof, EMBEDDING_DIM), float32
    embedder_version: str          # e.g. "bge-m3@5617a9f6"
```

A companion `load_embed_record(paper_id) -> EmbedRecord | None` lives in
`ingest/store.py` and reads `embeddings.npz` + sidecar for one paper —
useful for tests and for a future driver. Raises if NPZ is present but
sidecar is missing/corrupt (mirrors E03_S02 F1: verify-the-artifact
discipline).

### D3. Schema lives in `ingest/schema.py`; `store.py` imports it

```python
# ingest/schema.py
from ingest.embedder import EMBEDDING_DIM
import pyarrow as pa
from dataclasses import dataclass
import numpy as np

CHUNKS_TABLE_NAME = "chunks"

CHUNKS_SCHEMA_V1 = pa.schema([
    pa.field("chunk_id",        pa.utf8(),                          nullable=False),
    pa.field("paper_id",        pa.utf8(),                          nullable=False),
    pa.field("kind",            pa.utf8(),                          nullable=False),
    pa.field("section_path",    pa.list_(pa.utf8()),                nullable=False),
    pa.field("theorem_name",    pa.utf8(),                          nullable=True),
    pa.field("theorem_label",   pa.utf8(),                          nullable=True),
    pa.field("body_text",       pa.utf8(),                          nullable=False),
    pa.field("body_tokens",     pa.utf8(),                          nullable=False),
    pa.field("embedding_stmt",  pa.list_(pa.float32(), EMBEDDING_DIM), nullable=True),
    pa.field("embedding_proof", pa.list_(pa.float32(), EMBEDDING_DIM), nullable=True),
    pa.field("embedding_eq",    pa.list_(pa.float32(), EMBEDDING_DIM), nullable=True),
    pa.field("chunker_version", pa.utf8(),                          nullable=False),
    pa.field("embedder_version",pa.utf8(),                          nullable=False),
    pa.field("preamble_ref",    pa.utf8(),                          nullable=True),
])
```

The column order is the brief's table order. `EMBEDDING_DIM` is imported
from `ingest.embedder` — we do NOT redefine the literal `1024`.

### D4. Single-source-of-truth discipline (extends existing scan tests)

The existing scan tests:
- `tests/test_chunker_ids.py::TestSingleVersionDefinition::test_v1_0_literal_count_in_ingest_package`
  scans `ingest/` for `"v1.0"` literals.
- `tests/test_query_encoder.py::TestSingleSourceOfTruth::test_sha_literal_appears_exactly_once_across_ingest_and_server`
  scans the SHA literal across `ingest/` and `server/`.

These already cover the new `ingest/schema.py` and `ingest/store.py` —
adding either file with a stray `"v1.0"` or SHA literal will FAIL the
existing tests. No new scan tests required for those literals; we add
a fresh scan for `EMBEDDING_DIM = 1024` only if the implementation
inadvertently introduces a stray `1024` literal in the new files.

The `CHUNKER_VERSION` import follows the embedder's
`as EXPECTED_CHUNKER_VERSION` precedent — but `schema.py` doesn't need
the alias; it stores the raw `chunker_version` value passed in by the
caller (which comes from `ChunkRecord.chunker_version`). No literal
in the schema.

### D5. Idempotent upsert via `merge_insert`

```python
result = (
    tbl.merge_insert(on="chunk_id")
       .when_matched_update_all()
       .when_not_matched_insert_all()
       .execute(arrow_table)
)
return result.version  # int — LanceDB dataset version
```

Confirmed: matches the brief's "second write updates existing row, no
duplicate rows" requirement. No unique index needed; LanceDB's
`merge_insert` keys on the `on=` column.

The known LanceDB bug #3177 (silent merge_insert failure with scalar
index on the match column) does NOT apply here — our scalar index is
on `paper_id`, not `chunk_id`.

### D6. HNSW index: `lancedb.index.HnswSq(m=16, ef_construction=200)`

```python
tbl.create_index(
    "embedding_stmt",
    config=lancedb.index.HnswSq(m=16, ef_construction=200),
)
tbl.create_index(
    "embedding_proof",
    config=lancedb.index.HnswSq(m=16, ef_construction=200),
)
tbl.create_scalar_index("paper_id")  # default BTREE
```

LanceDB does NOT expose bare HNSW; it's always wrapped in IVF (the
canonical `IVF_HNSW_SQ`). For small corpora, `num_partitions` defaults
to `num_rows // 1_048_576` which auto-promotes to 1, so HNSW with
`m=16, ef_construction=200` builds correctly even on a 10-row test
(Researcher B's reading; resolves the small-dataset divergence).

If the LanceDB version installed during implementation lacks the
`HnswSq` config class (older API), fall back to the string form:
`tbl.create_index("embedding_stmt", index_type="IVF_HNSW_SQ", m=16,
ef_construction=200)`. The implementer should confirm the API at code
time.

**Defensive guard:** wrap each `create_index` call in a `try/except` that
logs a WARNING + skips on failure. This protects against:
- Future LanceDB API drift in HNSW config knobs
- Truly empty tables (zero rows)
- Unexpected failure modes

The integration test asserts the index EXISTS via `tbl.list_indices()`
after a 10-row write; if the guard skipped, the test fails clearly
with the warning surfaced.

### D7. NPZ alignment validation (closes the F4-from-E03_S02 analogue)

Before writing, `write_chunks` must validate:

```python
npz_ids = set(embeddings.chunk_ids_stmt) | set(embeddings.chunk_ids_proof)
chunk_ids = {c.chunk_id for c in chunks}
missing = chunk_ids - npz_ids
if missing:
    raise ValueError(
        f"chunks missing from EmbedRecord (no embedding vector): {missing}"
    )
```

Mirrors E03_S02's `_ChunkFileMissingError` — fail loudly rather than
silently insert NULL-embedding rows that would poison ANN results.

Extra `npz_ids` not in `chunk_ids` are tolerated (orphans GC'd by
E04_S02), matching the orphan-tolerance discipline from E03_S02 F7.

### D8. `body_tokens is None` raises

`ChunkRecord.body_tokens: str | None` allows None for legacy chunks
pre-E02_S03. The schema column is `string` non-nullable. The store
raises `ValueError` if any chunk has `body_tokens is None` rather
than coercing to `""`. E02_S03 has shipped, so any chunk produced by
the current pipeline has `body_tokens` populated; a None here is a
real bug.

### D9. Routing: zero-row sentinel handling

The NPZ may contain `(0, 1024)` zero-row sentinel arrays for papers
with zero proof chunks (or vice versa). The store iterates
`zip(chunk_ids_*, embedding_*)` so empty sentinels produce zero
iterations — correctly leaving `embedding_proof=None` for stmt-only
chunks. No special case needed.

### D10. Write-stats JSONL log (mirrors embed-stats.jsonl)

`var/arxmcp/ops/store-stats.jsonl` — append-mode JSONL line per
`write_chunks` call carrying:

```json
{
  "chunk_count": 10,
  "elapsed_s": 0.234,
  "lancedb_version": 5,
  "rows_inserted": 7,
  "rows_updated": 3
}
```

Sorted keys (BP1). The `lancedb_version` is the integer return value —
useful for debugging which write produced which dataset version.

### D11. Test strategy: real LanceDB on `tmp_path`

The integration test creates a real LanceDB on `tmp_path`, writes 10
synthetic chunks with random float32 embeddings, asserts row count =
10, schema matches `CHUNKS_SCHEMA_V1`, both HNSW indices exist, and
the second write of the same 10 chunks still produces 10 rows
(idempotency).

Synthetic embeddings: `numpy.random.default_rng(seed).random((10,
EMBEDDING_DIM)).astype(numpy.float32)` — no model load. The test does
NOT import `ingest.embedder` directly to avoid lazy-loading the
2.3 GB model.

`tmp_path` is the standard pytest fixture; LanceDB writes Lance files
under the directory tree it manages. Cleanup is automatic.

---

## Implementation order

1. `ingest/schema.py` — `CHUNKS_TABLE_NAME`, `CHUNKS_SCHEMA_V1`, `EmbedRecord`.
2. `ingest/store.py` — `write_chunks`, `load_embed_record`, helper to assemble Arrow rows, write-stats logger.
3. `pyproject.toml` — add `lancedb>=0.6`, `pyarrow>=14.0`.
4. `tests/test_store.py` — integration test (10 chunks), schema assertion, HNSW index assertion, idempotency assertion, NPZ-alignment failure mode, body_tokens-None failure mode.

---

## Open questions (deferred to implementation)

- **Schema migration path.** A future `chunker_version` bump → schema
  may need new columns. Out of scope for E04_S01; E04_S02 handles
  MVCC. Document in `schema.py` docstring.
- **Concurrent writers.** LanceDB has its own MVCC; two concurrent
  `write_chunks` calls produce two new dataset versions. Document this
  in the module docstring (POSIX-atomicity + LanceDB MVCC layered).
- **Embedding nullability when chunk_id is in BOTH stmt and proof.** The
  embedder routes by kind, so a chunk can be in stmt OR proof, never
  both. Validate this invariant in `write_chunks`: raise if any
  chunk_id appears in both lists.

---

## External writes the implementation will require

| Path | Event | Notes |
|---|---|---|
| `pyproject.toml` | source edit | adds `lancedb>=0.6` + `pyarrow>=14.0` |
| `ingest/schema.py` | new file | PyArrow schema + EmbedRecord dataclass |
| `ingest/store.py` | new file | write_chunks + load_embed_record + index helpers |
| `tests/test_store.py` | new file | integration test |
| `var/arxmcp/index/lancedb/chunks/` | runtime | created by lancedb on first write_chunks call |
| `var/arxmcp/ops/store-stats.jsonl` | runtime | append-mode write-stats log |

No third-party API calls. No model download. The HuggingFace cache
populated by E03_S01 is not touched (the store doesn't load any model).

The first `pip install` after this milestone lands will pull the
LanceDB + PyArrow wheels (~30-60 MB combined). That's a one-time cost
per developer environment.
