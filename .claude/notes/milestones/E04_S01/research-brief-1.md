# E04_S01 Research Brief 1 — `chunks` LanceDB Table v1 Schema

## 1. In-Codebase Context

### ChunkRecord fields (source: `ingest/chunker_types.py`)

`ChunkRecord` has these fields directly mappable to the schema:
`chunk_id`, `paper_id`, `kind`, `section_path`, `theorem_name` (nullable),
`theorem_label` (nullable), `body_text`, `body_tokens` (str|None, defaulting
None), `preamble_ref` (nullable), `chunker_version` (default
`CHUNKER_VERSION`), and a `truncated: bool` field (NOT in the LanceDB schema —
omit it from the Arrow schema but note it to implementers).

`CHUNKER_VERSION = "v1.0"` is the single source of truth in
`ingest/chunker_types.py`. Already imported as `EXPECTED_CHUNKER_VERSION`
in `ingest/embedder.py` — the alias pattern must be replicated in
`ingest/store.py` and `ingest/schema.py`.

### NPZ layout and what `EmbedRecord` must be (source: `ingest/embedder.py`)

The NPZ at `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz` always
contains exactly four arrays in **alphabetical key order** (BP1 discipline,
E03_S01 F5):
- `chunk_ids_proof` — 1-D str array, length N_proof
- `chunk_ids_stmt` — 1-D str array, length N_stmt
- `embedding_proof` — float32, shape `(N_proof, 1024)`; zero-row sentinel when N_proof == 0
- `embedding_stmt` — float32, shape `(N_stmt, 1024)`; zero-row sentinel when N_stmt == 0

`EMBEDDING_DIM = 1024` and `EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"` are
exported from `ingest/embedder.py`.

The `embeddings_manifest.json` sidecar carries `{chunker_version, embedder_version,
embedded_chunks: [{chunk_id, kind}], paper_id}`. The embedder doc says: "Each entry
carries the chunk's kind so E04_S01 can reconstruct the routing without re-reading
the chunk JSONs."

**Conclusion:** `EmbedRecord` is undefined; `write_chunks` must read the NPZ from
disk (using `EMBEDDINGS_DIR / paper_id / EMBEDDINGS_NPZ_NAME`). The `embeddings`
parameter in the brief's signature is a placeholder. Recommend defining:

```python
@dataclass
class EmbedRecord:
    chunk_ids_stmt: list[str]
    chunk_ids_proof: list[str]
    embedding_stmt: np.ndarray   # shape (N_stmt, 1024), float32
    embedding_proof: np.ndarray  # shape (N_proof, 1024), float32
    embedder_version: str        # from sidecar or EMBEDDER_VERSION
```

This is populated by calling `np.load(npz_path, allow_pickle=False)` and reading
the four arrays. `write_chunks` should accept a pre-loaded `EmbedRecord` (not a
file path) so tests can inject synthetic embeddings without touching disk.

### `embedder_version` and Threat 6 (08-security-observability-ops.md)

Threat 6 says: "Pin model commit SHAs in configuration (`BAAI/bge-m3@<sha>`),
not just names." `EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"` is the
LanceDB column value — it records the 8-char prefix of the 40-char SHA. The full
SHA is in `EmbedStats.bge_m3_commit_sha`. The schema column stores the short form;
the SHA literal lives only in `ingest/embedder.py`.

### HNSW parameters (05-storage-and-indexing.md)

"HNSW on `embedding_stmt` (M=16, efConstruction=200). HNSW on `embedding_proof`
(M=16, efConstruction=200)." Scalar index on `paper_id`. No index on
`embedding_eq`.

### BP1 byte-stability (07-multi-agent-caching.md)

"Cache key is the hash of the exact prefix bytes." For LanceDB write paths, this
doesn't impose ordering constraints on the Arrow schema itself, but the `schema.py`
module must define a single ordered `pa.schema([...])` — column order must not vary
across runs. Recommend alphabetical column order within logical groups to mirror
the NPZ discipline.

### pyproject.toml

`lancedb` is **NOT** listed. `pyarrow` is **NOT** listed. `numpy>=1.24` IS listed.
Both `lancedb` and `pyarrow` must be added to `[project.dependencies]`.

---

## 2. Prior Decisions and Lessons

### NPZ alphabetical-keys discipline (E03_S01 F5)

"Closes F5 from the E03_S01 critique — `np.savez` writes archive members in kwargs
insertion order, so file bytes are deterministic only if the kwargs order is fixed;
alphabetical matches the BP1-byte-stability discipline." The LanceDB schema does
not need a same-type alphabetical ordering, but `schema.py` MUST define the column
list as a fixed literal in source — never constructed from a dict or unsorted
iterable. The milestone brief's explicit ordered table is the canonical order;
implement that exact order.

### `EXPECTED_CHUNKER_VERSION` alias pattern (E03_S02)

`embedder.py` does `from ingest.chunker_types import CHUNKER_VERSION as
EXPECTED_CHUNKER_VERSION`. `schema.py` / `store.py` must follow the same pattern:
import `CHUNKER_VERSION` from `ingest.chunker_types` (do NOT define a new literal).
Import `EMBEDDER_VERSION` and `EMBEDDING_DIM` from `ingest.embedder`.

### BGE_M3_COMMIT_SHA single-source scan (test_query_encoder.py)

`tests/test_query_encoder.py::TestSingleSourceOfTruth::test_sha_literal_appears_exactly_once_across_ingest_and_server`
scans `ingest/` and `server/` for the 40-char SHA literal and asserts exactly one
hit in `embedder.py`. Adding `ingest/store.py` or `ingest/schema.py` that copies
the literal would **break** this existing test. Both new files must import from
`ingest.embedder`, not define the literal. Same for `"v1.0"` — the scan in
`test_chunker_ids.py::TestSingleVersionDefinition` covers all of `ingest/`; do
not hard-code `"v1.0"` in `store.py` or `schema.py`.

### F1 analogue from E03_S02 (sidecar-without-NPZ skip)

E03_S02 F1: a sidecar present but NPZ missing caused false skip. Analogous concern
for `write_chunks`: if `chunk_manifest.json` lists N chunk_ids but the NPZ has
fewer rows (N_stmt + N_proof < N), some chunks have no embedding vectors. The
`_write_embeddings_npz` docstring explicitly states zero-row sentinel arrays are
written, not absent keys — so a mismatch means corpus corruption. `write_chunks`
MUST validate: `set(chunk_ids_stmt) | set(chunk_ids_proof) == set(c.chunk_id for
c in chunks)`. Raise a `ValueError` on mismatch rather than silently inserting
null-vector rows for the unembedded chunks.

---

## 3. External Sources

### LanceDB Python client — version and API

`lancedb` 0.20.x (current stable as of 2026-05). Pin `lancedb>=0.20,<1.0` in
`pyproject.toml`. Key API surface:

- `lancedb.connect(uri)` → `LanceDBConnection`
- `conn.create_table(name, schema=pa_schema)` → `Table` (first call, creates on disk)
- `conn.open_table(name)` → `Table` (subsequent calls)
- `tbl.merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all().execute(data)` — upsert by `chunk_id`. This is idempotent: second call with same `chunk_id` updates rather than duplicates. No unique index is required by LanceDB; `merge_insert` uses the key column as the match predicate.
- `tbl.create_index("embedding_stmt", config=lancedb.index.HnswSq(m=16, ef_construction=200))` or similar — see note below.
- `tbl.create_scalar_index("paper_id", index_type="BTREE")` — creates a B-tree scalar index.
- `tbl.count_rows()` → `int`
- `tbl.schema` → `pa.Schema`

**HNSW index parameter warning:** LanceDB's public API uses `IVF_HNSW_SQ` or
`HnswSq` (not bare `HNSW`) in 0.14+. The config class is
`lancedb.index.HnswSq(m=16, ef_construction=200)` passed to `create_index`. The
older string API (`index_type="IVF_HNSW_PQ"`) is available but deprecated. Verify
against the installed version's docs — pin the version to avoid API drift. The
05-storage-and-indexing.md note says M=16, efConstruction=200; use these exactly.

**HNSW training threshold:** LanceDB's IVF_HNSW_SQ requires at least 256 rows
to train IVF centroids (the IVF partitioning step). With only 10 fixture rows in
the integration test, `create_index` will raise unless the implementation catches
this and defers index creation. Recommend: after `write_chunks`, attempt index
creation but wrap in a try/except that logs a warning and skips rather than
raising when row count is below the training threshold. Document the threshold
in a `_MIN_ROWS_FOR_HNSW = 256` constant in `store.py`.

**Merge-insert idempotency:** `merge_insert` with `.when_matched_update_all()
.when_not_matched_insert_all()` is the canonical LanceDB upsert. It is idempotent
on duplicate `chunk_id` keys. No unique index is needed; LanceDB does not enforce
uniqueness constraints like SQL — the upsert semantics are correct by construction.

### PyArrow schema for the v1 table

```python
import pyarrow as pa

CHUNKS_SCHEMA_V1 = pa.schema([
    pa.field("chunk_id",        pa.utf8(),                      nullable=False),
    pa.field("paper_id",        pa.utf8(),                      nullable=False),
    pa.field("kind",            pa.utf8(),                      nullable=False),
    pa.field("section_path",    pa.list_(pa.utf8()),            nullable=False),
    pa.field("theorem_name",    pa.utf8(),                      nullable=True),
    pa.field("theorem_label",   pa.utf8(),                      nullable=True),
    pa.field("body_text",       pa.utf8(),                      nullable=False),
    pa.field("body_tokens",     pa.utf8(),                      nullable=False),
    pa.field("embedding_stmt",  pa.list_(pa.float32(), 1024),   nullable=True),
    pa.field("embedding_proof", pa.list_(pa.float32(), 1024),   nullable=True),
    pa.field("embedding_eq",    pa.list_(pa.float32(), 1024),   nullable=True),
    pa.field("chunker_version", pa.utf8(),                      nullable=False),
    pa.field("embedder_version",pa.utf8(),                      nullable=False),
    pa.field("preamble_ref",    pa.utf8(),                      nullable=True),
])
```

`pa.list_(pa.float32(), 1024)` creates `fixed_size_list<float32>[1024]` in Arrow.
The milestone brief's risk note is explicit: "Nullable columns for `embedding_eq`
must be declared as `pa.field(..., nullable=True)` — omitting nullability causes
Arrow errors on insertion."

Note: `body_tokens` is `nullable=False` in the schema but `ChunkRecord.body_tokens`
is `str | None`. The implementer must coerce `None` to `""` (empty string) or
raise an error on chunks without `body_tokens`. Given the field's E02_S03 origin,
any chunk written post-E02_S03 has a non-None `body_tokens`; legacy chunks should
be rejected, not silently coerced.

### `pyarrow` version

`pyarrow>=14.0` is a safe pin; LanceDB 0.20.x requires pyarrow >=14. Add to
`[project.dependencies]`.

---

## Open Questions

1. **What is the `EmbedRecord` shape?** Recommend the dataclass above. The brief's
   `write_chunks(chunks, embeddings, lancedb_path)` signature implies `embeddings`
   is a pre-loaded record, not a path. The implementation should expose a companion
   `load_embed_record(paper_id) -> EmbedRecord | None` that reads the NPZ and
   sidecar, so callers do not touch NPZ internals.

2. **Who orchestrates "read chunks + read NPZ + write LanceDB"?** The embedder
   writes NPZ; no existing module calls `write_chunks`. The brief scopes E04_S01
   to defining the table and the write API; the corpus driver that stitches
   chunk-load + NPZ-load + `write_chunks` is not yet built. The integration test
   can bypass this by calling `write_chunks` directly with synthetic fixtures.
   A follow-on milestone (or the acceptance test itself) must document where the
   orchestration lives — likely a `ingest_corpus()` entrypoint in `ingest/store.py`
   or a separate `ingest/pipeline.py`.

3. **HNSW index creation timing and row threshold.** LanceDB IVF_HNSW_SQ requires
   ~256 rows minimum. The integration test writes only 10 rows. Recommend: call
   `create_index` after every `write_chunks`, catch the "not enough rows" exception,
   log `WARNING` at debug level, and skip. The test should assert the index EXISTS
   on a full corpus (>256 rows) but the 10-row test should assert a warning was
   emitted rather than asserting index existence.

4. **Idempotency mechanism.** `merge_insert(...).when_matched_update_all()
   .when_not_matched_insert_all()` is confirmed as the correct pattern. The
   acceptance criterion "second write updates existing row, no duplicate rows" is
   satisfied by LanceDB's upsert semantics; verify in the integration test by
   writing 10 chunks, then writing the same 10 chunks again, and asserting
   `count_rows() == 10`.

5. **Do tests need real LanceDB on disk?** Yes — the acceptance criteria require
   a real `lancedb.connect(...)` to a `tmp_path`. LanceDB's embedded mode writes
   Lance files under a directory; a `tmp_path` fixture is appropriate. Expected
   runtime for 10 rows: <1 second (no model loading, just Arrow + Lance I/O).
   The test should NOT import `ingest.embedder` (which triggers lazy model load).

---

## External Writes the Implementation Will Require

1. **`pyproject.toml` additions:** `lancedb>=0.20,<1.0` and `pyarrow>=14.0` in
   `[project.dependencies]`. Also add `lancedb` and `pyarrow` to `[project.optional-dependencies].dev`
   if tests are the primary consumer (but both are runtime deps, so `dependencies`
   is correct).

2. **New source files:**
   - `ingest/schema.py` — PyArrow schema definition (no other content).
   - `ingest/store.py` — `write_chunks`, `load_embed_record`, index creation helpers.

3. **New test file:** `tests/test_store.py` — integration test using `tmp_path`.
   Must import `CHUNKS_SCHEMA_V1` from `ingest.schema` and validate returned schema
   against it. Must NOT redefine `"v1.0"` or the BGE_M3_COMMIT_SHA literal inline.

4. **Directory creation:** `var/arxmcp/index/lancedb/` created by
   `lancedb.connect(lancedb_path)` on first call; no explicit `mkdir` needed. The
   `chunks` table directory is created by `conn.create_table(...)`.

5. **Existing test scan guards** — `tests/test_chunker_ids.py::TestSingleVersionDefinition`
   and `tests/test_query_encoder.py::TestSingleSourceOfTruth` will scan the new
   `ingest/schema.py` and `ingest/store.py`. Any introduction of the `"v1.0"` or
   BGE_M3_COMMIT_SHA literal in those files will break those tests. The
   implementation MUST import, not re-define.
