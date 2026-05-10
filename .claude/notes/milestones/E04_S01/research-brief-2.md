# E04_S01 Research Brief — Researcher 2

## 1. In-Codebase Context

### pyproject.toml — Missing LanceDB and PyArrow

Confirmed: `pyproject.toml` lists `beautifulsoup4`, `transformers`, `torch`,
`safetensors`, and `numpy` as runtime dependencies. **Neither `lancedb` nor
`pyarrow` appears anywhere in the file.** The implementation MUST add both to
`[project.dependencies]`, with a comment matching the existing commentary
style (e.g., citing E04_S01).

---

### NPZ Output Schema (embedder.py)

`ingest/embedder.py:_write_embeddings_npz` writes four arrays in exact
alphabetical order — load-bearing for BP1 byte-stability (closes F5):

```python
np.savez(
    fh,
    chunk_ids_proof=np.asarray(chunk_ids_proof, dtype=object),  # 1-D str, len N_proof
    chunk_ids_stmt=np.asarray(chunk_ids_stmt, dtype=object),    # 1-D str, len N_stmt
    embedding_proof=embedding_proof,                            # float32 (N_proof, 1024)
    embedding_stmt=embedding_stmt,                              # float32 (N_stmt, 1024)
)
```

Edge case (closes F9): "when a paper has zero proof chunks (or zero stmt chunks),
the corresponding array is written as a `(0, EMBEDDING_DIM)` zero-row array — NOT
omitted from the NPZ." The docstring further states: "Consumers MUST check
`len(chunk_ids_*) > 0` or equivalently `embedding_*.shape[0] > 0` before
iterating, and must NOT rely on key presence (`'embedding_proof' in npz.files`)
as a signal of absence."

The routing rule (embedder.py line 959): `kind == "proof"` → `embedding_proof`;
everything else → `embedding_stmt`. `embedding_eq` is never populated by the
embedder; always NULL.

The sidecar manifest at `var/arxmcp/corpus/embeddings/<paper_id>/embeddings_manifest.json`
carries these four fields (alphabetical, `sort_keys=True`, no timestamps):

```json
{
  "chunker_version": "<EXPECTED_CHUNKER_VERSION>",
  "embedded_chunks": [{"chunk_id": "arxiv:...", "kind": "stmt"}, ...],
  "embedder_version": "<EMBEDDER_VERSION>",
  "paper_id": "2307.01156"
}
```

`embedded_chunks` is written in document order (manifest order), not sorted.
`embedder_version` has the form `bge-m3@<sha8>` (e.g. `bge-m3@5617a9f6`).

---

### Chunk-Side Artifacts (chunker.py)

`_write_chunk_manifest` produces (via atomic tmp + `os.replace`):

```json
{
    "chunker_version": "<CHUNKER_VERSION>",
    "chunks": [
        {"chunk_id": "arxiv:...:<hash>", "kind": "stmt"},
        ...
    ],
    "paper_id": "2307.01156"
}
```

Per-chunk JSONs are at `var/arxmcp/corpus/chunks/<paper_id>/<hash16>.json`.
Their on-disk key set is exactly `ChunkRecord.to_dict()` output — sorted keys,
no timestamps. The filename is `chunk_id.rsplit(":", 1)[-1]` (the 16-hex suffix).

---

### ChunkRecord and PreambleDoc

`ChunkRecord` fields (from `ingest/chunker_types.py`):

- Required: `chunk_id`, `paper_id`, `kind`, `section_path`, `theorem_name`,
  `theorem_label`, `body_text`
- Optional: `body_tokens: str | None`, `preamble_ref: str | None`,
  `chunker_version: str = CHUNKER_VERSION`, `truncated: bool = False`

Note: `body_tokens` is typed `str | None` — a whitespace-joined string, NOT
`list[str]`. This matches the LanceDB schema `string` column directly.

`PreambleDoc` fields: `paper_id`, `source_hash`, `macros`, `preamble_text`,
`preamble_hash`. The `preamble_hash` is `SHA-256(preamble_text)[:16]` — this
is what `ChunkRecord.preamble_ref` stores.

---

### 05-storage-and-indexing.md — Schema Authority

The design doc's `chunks` table is an older draft. The **authoritative v1
schema** is in the E04_S01 milestone brief (`E04-vector-store.md`). The doc
confirms HNSW M=16/efConstruction=200 on both embedding columns, B-tree on
`paper_id`, `embedding_eq` reserved/NULL. No column ordering discipline is
mandated; use document-order matching the milestone table.

---

### 08-security-observability-ops.md — Threat 6

Threat 6 applies to model loading; `ingest/store.py` loads no model. Relevant
operability note: follow the `embed-stats.jsonl` pattern and emit a write-stats
JSONL line per call (duration, row count, version returned).

---

### var/arxmcp/index/lancedb/ — Does It Exist?

`ls var/arxmcp/index/` returns "DOES NOT EXIST." The directory does not exist.
`write_chunks` must call `Path(lancedb_path).mkdir(parents=True, exist_ok=True)`
before `lancedb.connect()`. This is consistent with `EMBEDDINGS_DIR` handling
in the embedder.

---

## 2. Prior Decisions and Lessons

### EmbedRecord Parameter Shape

The brief names `EmbedRecord` but never defines it. The NPZ + sidecar together
constitute the per-paper embedding state. The recommended concrete dataclass:

```python
@dataclass
class EmbedRecord:
    paper_id: str
    chunk_ids_stmt: list[str]   # aligned with embedding_stmt rows
    embedding_stmt: np.ndarray  # shape (N_stmt, 1024), float32
    chunk_ids_proof: list[str]  # aligned with embedding_proof rows
    embedding_proof: np.ndarray # shape (N_proof, 1024), float32
    embedder_version: str       # e.g. "bge-m3@5617a9f6"
```

The store assembles this by loading `embeddings.npz` (four arrays, alphabetical
order) and the sidecar for `embedder_version`. Chunks with `chunk_id` in
`chunk_ids_stmt` get `embedding_stmt[i]` set and `embedding_proof` NULL; chunks
in `chunk_ids_proof` get `embedding_proof[j]` set and `embedding_stmt` NULL.
Chunks in neither list (zero-row sentinel) keep both NULL. This directly maps
to the `embedding_eq = NULL` rule: the embedder never populates it, so every
row written by E03_S01 has `embedding_eq=None`.

---

### Single-Source-of-Truth Scan Analogue

`tests/test_chunker_ids.py::TestSingleVersionDefinition` scans the `ingest/`
package for literal `"v1.0"` occurrences, allowing exactly one in `chunker_types.py`
and one in `tokenizer.py`. `tests/test_query_encoder.py::TestSingleSourceOfTruth`
asserts that `BGE_M3_COMMIT_SHA` is imported, not redefined.

**Recommendation:** `tests/test_store.py` should include an analogous
`TestSingleSourceOfTruth` class that verifies:
1. The PyArrow schema constant is imported from `ingest.schema`, not re-defined
   in `store.py` or any test file.
2. The `CHUNKS_TABLE_NAME = "chunks"` string literal lives only in `schema.py`
   (or `store.py`), preventing drift if the table is renamed.
3. `EMBEDDING_DIM = 1024` is imported from `ingest.embedder`, not re-stated.

---

### Atomic-Write Pattern vs LanceDB MVCC

The project uses `os.replace` + tmp + UUID for all file writes. LanceDB's own
write path is already MVCC-safe and crash-safe at the Lance dataset layer;
there is no need to wrap `tbl.merge_insert(...).execute(data)` in an additional
`os.replace` layer. The `write_chunks` function should:
1. `mkdir(parents=True, exist_ok=True)` for the LanceDB path before connect.
2. Use `lancedb.connect(lancedb_path)` + `db.create_table(..., exist_ok=True)`
   + `tbl.merge_insert(on="chunk_id").when_matched_update_all().when_not_matched_insert_all().execute(arrow_table)`.
3. Capture the returned version from the result object (`merge_result.version`).

No additional filesystem atomicity wrapper is needed or appropriate.

---

### F4 Manifest-vs-Chunk-File Consistency (from E03_S02)

E03_S02 introduced `_ChunkFileMissingError` to surface cases where a manifest
entry references a chunk JSON that doesn't exist on disk. The same lesson
applies here: if a `chunk_id` is present in the embeddings sidecar's
`embedded_chunks` list but absent from the NPZ's `chunk_ids_stmt` and
`chunk_ids_proof` arrays, the store has an alignment bug.

**Recommended guard in `write_chunks`:** After loading the NPZ, assert:

```python
npz_ids = set(chunk_ids_stmt) | set(chunk_ids_proof)
sidecar_ids = {e["chunk_id"] for e in sidecar["embedded_chunks"]}
# Every chunk passed to write_chunks must have an embedding
missing = {c.chunk_id for c in chunks} - npz_ids
if missing:
    raise ValueError(f"chunks missing from NPZ: {missing}")
```

This mirrors the `_ChunkFileMissingError` pattern: fail loudly rather than
silently write NULL-embedding rows that would poison ANN results.

---

## 3. External Sources

### LanceDB Python API — Verified Calls

**Connect:**
```python
db = lancedb.connect(uri)  # returns DBConnection; uri is a path string
```

**Create table (create-if-not-exists):**
```python
tbl = db.create_table("chunks", schema=arrow_schema, exist_ok=True)
```
The `mode` parameter accepts `"create"` (raises if exists) or `"overwrite"`.
For idempotent first-write behavior, use `exist_ok=True` (preferred) or
`mode="create_if_not_exists"` — both are present in lancedb ≥0.6.

**Merge-insert (upsert by chunk_id):**
```python
(
    tbl.merge_insert(on="chunk_id")
       .when_matched_update_all()
       .when_not_matched_insert_all()
       .execute(arrow_table)
)
```
Returns a `MergeResult` with a `.version` attribute (integer). Known bug
lancedb#3177: `merge_insert` fails silently after `optimize()` if a scalar
index exists on the *match* column. The scalar index lives on `paper_id`, not
`chunk_id`, so this is safe.

**HNSW vector index:**
```python
tbl.create_index(
    "embedding_stmt",
    config=lancedb.index.HnswSq(
        m=16,
        ef_construction=200,
    ),
)
```
In lancedb Python, the canonical HNSW knobs are exposed through
`lancedb.index.HnswSq` (IVF_HNSW_SQ), `HnswPq` (IVF_HNSW_PQ), or
`HnswFlat` (IVF_HNSW_FLAT). The parameters `m` and `ef_construction` map
directly to the design doc's M=16/efConstruction=200 spec. `num_partitions`
defaults to `num_rows // 1,048,576`, which for a small corpus (10–50 chunks)
evaluates to 0 and is automatically promoted to 1. The index type is
`IVF_HNSW_SQ`, NOT bare HNSW — LanceDB does not expose bare HNSW as a
top-level index; it is always embedded inside IVF partitions.

**Scalar index:** `tbl.create_scalar_index("paper_id")` — BTREE default, correct
for high-cardinality string column. No `index_type` kwarg needed.

**Row count:** `tbl.count_rows()` returns int.

**Version:** `merge_result.version` (int); also `tbl.version` property and
`tbl.list_versions()`.

---

### PyArrow Fixed-Size List for 1024-dim Embeddings

The correct invocation is:
```python
pa.list_(pa.float32(), 1024)  # FixedSizeListType, not pa.list_(pa.float32())
```

**Nullable embedding field:**
```python
pa.field("embedding_stmt", pa.list_(pa.float32(), 1024), nullable=True)
```
The roadmap doc explicitly notes: "omitting nullability would cause Arrow errors
on insertion" — this is the `Risk notes` item.

**Non-nullable string field:**
```python
pa.field("chunk_id", pa.utf8(), nullable=False)
```

The full schema (14 columns, document order from milestone table):
```python
CHUNKS_SCHEMA_V1 = pa.schema([
    pa.field("chunk_id",        pa.utf8(),                    nullable=False),
    pa.field("paper_id",        pa.utf8(),                    nullable=False),
    pa.field("kind",            pa.utf8(),                    nullable=False),
    pa.field("section_path",    pa.list_(pa.utf8()),          nullable=False),
    pa.field("theorem_name",    pa.utf8(),                    nullable=True),
    pa.field("theorem_label",   pa.utf8(),                    nullable=True),
    pa.field("body_text",       pa.utf8(),                    nullable=False),
    pa.field("body_tokens",     pa.utf8(),                    nullable=False),
    pa.field("embedding_stmt",  pa.list_(pa.float32(), 1024), nullable=True),
    pa.field("embedding_proof", pa.list_(pa.float32(), 1024), nullable=True),
    pa.field("embedding_eq",    pa.list_(pa.float32(), 1024), nullable=True),
    pa.field("chunker_version", pa.utf8(),                    nullable=False),
    pa.field("embedder_version",pa.utf8(),                    nullable=False),
    pa.field("preamble_ref",    pa.utf8(),                    nullable=True),
])
```

Note: `body_tokens` is not nullable in the milestone schema — but `ChunkRecord`
declares it `str | None`. The store must coerce `None` to `""` or treat it as
missing; recommend raising if `body_tokens is None` since E02_S03 is a
completed milestone dependency.

---

### HNSW Index Timing and Small-Dataset Behavior

LanceDB's IVF_HNSW_SQ requires enough vectors to train the IVF centroids. For a
10-chunk test dataset: `num_partitions = 10 // 1_048_576 = 0`, auto-promoted to
1. With `num_partitions=1`, IVF training degenerates to a single cluster and
HNSW is built on all 10 vectors — this succeeds without error. The 256-vector
warning is specific to IVF_PQ quantization codebook training; IVF_HNSW_SQ with
1 partition does not require a minimum. The test suite can call `create_index`
on 10 rows without skipping.

---

## Open Questions

**EmbedRecord shape contract.** Recommended: the `@dataclass` above is the
right shape. The store reads NPZ + sidecar directly rather than accepting raw
arrays from the caller; `EmbedRecord` should be a thin loader wrapper. The
`write_chunks` signature should accept `chunks: list[ChunkRecord]` and
`embed_record: EmbedRecord` (not raw numpy). The caller passes pre-loaded
`EmbedRecord` so the store has no I/O coupling to the NPZ path.

**Who calls `write_chunks`?** Recommend a thin pipeline driver
(`tools/ingest.py` or `ingest/ingest_pipeline.py`) that sequences: `chunk_paper`
→ `embed_paper` → build `EmbedRecord` from NPZ + sidecar → `write_chunks`. That
driver is out of scope for E04_S01 (lives in E04_S02/E04_S03). Tests construct
`EmbedRecord` directly.

**HNSW index timing.** Create index after every `write_chunks` call. LanceDB's
`create_index` is idempotent on a table that already has the index (it
rebuilds/updates it). For a 10-chunk test, this succeeds without error (see
above). Do NOT skip index creation in tests — the AC explicitly requires "HNSW
indices exist on `embedding_stmt` and `embedding_proof` after a write."

**Idempotency semantics.** `merge_insert` by `chunk_id` is content-addressable:
if `body_text` changes, the `chunk_id` SHA changes (new row inserted; old row
stays as orphan). E04_S02 GCs orphans. Within a single `chunker_version`, a
re-write of the same `chunk_id` updates all columns (including embeddings) in
place — correct behavior.

**Empty embedding columns.** Zero-row sentinel (`embedding_proof.shape == (0, 1024)`)
→ no proof chunks. Non-proof chunks get `embedding_proof=None` (not zero-vector).
The implementation must iterate `zip(chunk_ids_proof, embedding_proof)` — empty
zip produces nothing, leaving `embedding_proof=None` on all stmt-only rows.

**Test strategy.** Real LanceDB on disk in `tmp_path` (pytest fixture). Do NOT
mock LanceDB — the AC requires `count_rows() == 10` against a real table. Skip
the BGE-M3 model; construct synthetic 1024-dim float32 embeddings in the test.
Use `numpy.random.default_rng(seed).random((10, 1024)).astype(numpy.float32)`.

---

## External Writes the Implementation Will Require

1. **`pyproject.toml`** — add `lancedb>=0.6` and `pyarrow>=14.0` to
   `[project.dependencies]` with explanatory comments matching existing style.
2. **`var/arxmcp/index/lancedb/`** — directory does not exist; created by
   `write_chunks` via `Path(lancedb_path).mkdir(parents=True, exist_ok=True)`.
   Do NOT pre-create in the repo (`.gitignore` already excludes `var/`).
3. **`ingest/schema.py`** — new file; exports `CHUNKS_SCHEMA_V1`, `CHUNKS_TABLE_NAME`,
   and the `EmbedRecord` dataclass (or import `EmbedRecord` from here).
4. **`ingest/store.py`** — new file; exports `write_chunks`.
5. **`tests/test_store.py`** — new file; integration test using `tmp_path`.
6. **`tests/fixtures/store/`** — synthetic chunk JSON fixtures for 10 test
   chunks (or generate programmatically in the test). Prefer programmatic
   generation over fixture files to avoid maintaining 10 JSON files.
