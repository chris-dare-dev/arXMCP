# E04 — Vector Store (NEW)

**Epic dependencies:** E02 (chunk JSON with `body_text`, `body_tokens`, `chunk_id`, `chunker_version`), E03 (embedding vectors in `embedding_stmt`, `embedding_proof`).

**Goal:** Define the authoritative LanceDB table schema, manage corpus versions via native MVCC (no manual symlink swaps), propagate a `corpus_version` integer through the ingestion pipeline, and build the BM25 index over `body_tokens`. Together these four milestones constitute the complete on-disk index state that all downstream readers — the MCP server, the eval harness, and the citation graph — pin to a specific version.

**Effort:** ~2 weeks calendar (M+M+S+M across four milestones).

**References:** `05-storage-and-indexing.md` § LanceDB, § Vector + lexical index, § MVCC versioning; `08-security-observability-ops.md` § Caching (corpus_version as cache key); `09-feature-priorities.md` (Tier 0 storage requirements).

---

### E04_S01 — `var/arxmcp/index/lancedb/chunks` table v1 schema

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E02_S04, E03_S01

**Description.** This milestone defines the canonical LanceDB table schema for the `chunks` dataset. The table is created at `var/arxmcp/index/lancedb/chunks` on first ingest and extended via LanceDB's native append/overwrite API on subsequent runs. The schema is the single source of truth for all downstream readers; it must not be altered without a corresponding MVCC version bump.

**Schema (v1):**

| Column | Type | Notes |
|---|---|---|
| `chunk_id` | `string` | `arxiv:<paper_id>:<sha256[:16]>` |
| `paper_id` | `string` | arXiv ID, e.g. `2301.00001` |
| `kind` | `string` | `stmt`, `proof`, `section`, `definition` |
| `section_path` | `list<string>` | Breadcrumb path from document root |
| `theorem_name` | `string` (nullable) | Display name if present |
| `theorem_label` | `string` (nullable) | `\label{}` value if present |
| `body_text` | `string` | Raw chunk body (preamble NOT included) |
| `body_tokens` | `string` | Space-joined BM25 token stream from E02_S03 |
| `embedding_stmt` | `fixed_size_list<float32>[1024]` (nullable) | Set for `kind=stmt` and fallback kinds |
| `embedding_proof` | `fixed_size_list<float32>[1024]` (nullable) | Set for `kind=proof` only |
| `embedding_eq` | `fixed_size_list<float32>[1024]` (nullable) | Reserved; NULL until E10_S03 |
| `chunker_version` | `string` | e.g. `"v1.0"` |
| `embedder_version` | `string` | e.g. `"bge-m3@<sha>"` |
| `preamble_ref` | `string` (nullable) | SHA256[:16] of normalized preamble |

HNSW vector indices are created on `embedding_stmt` and `embedding_proof` with parameters M=16, efConstruction=200, per `05-storage-and-indexing.md` § Vector index. A scalar index is created on `paper_id` for efficient per-paper filtering. No index is created on `embedding_eq` until E10_S03 populates the column.

The table writer module is `ingest/store.py`. It exposes `write_chunks(chunks: list[ChunkRecord], embeddings: EmbedRecord, lancedb_path: str) -> int` which returns the new LanceDB dataset version number. The first call creates the dataset; subsequent calls append or overwrite based on the `chunk_id` key.

**Deliverables.**
- `ingest/store.py` — table creation and upsert logic; `write_chunks()` API
- `ingest/schema.py` — PyArrow schema definition for the `chunks` table (imported by `store.py` and by tests)
- HNSW indices on `embedding_stmt` and `embedding_proof` created after write
- Scalar index on `paper_id`
- `pytest tests/test_store.py` — integration test: write 10 fixture chunks, assert row count, assert schema, assert HNSW index exists

**Acceptance criteria.**
- [ ] Table created at `var/arxmcp/index/lancedb/chunks` on first `write_chunks` call.
- [ ] Schema matches the v1 column list above exactly (column names, types, nullability).
- [ ] HNSW indices exist on `embedding_stmt` and `embedding_proof` after a write.
- [ ] `embedding_eq` is present in schema and null on all rows written by E03_S01.
- [ ] `write_chunks` is idempotent on duplicate `chunk_id`: second write updates existing row, no duplicate rows.
- [ ] Integration test: 10 chunks written, `lancedb.connect(...).open_table("chunks").count_rows()` returns 10.
- [ ] PyArrow schema definition is imported from a single `schema.py` module — not re-defined inline.

**Out of scope.** MVCC version pinning by readers (E04_S02). BM25 index (E04_S04). `corpus_version` marker file (E04_S03).

**Risk notes.**
- **Closes H3** (dual-column schema is the final structural fix): `embedding_stmt` and `embedding_proof` as separate nullable columns enforce the dual-encoding contract at the storage layer. A single `embedding` column (as in the superseded E01_S06) could not enforce which chunks have been encoded in which modality.
- Nullable columns for `embedding_eq` must be declared in PyArrow as `pa.field("embedding_eq", pa.list_(pa.float32(), 1024), nullable=True)` — omitting nullability would cause Arrow errors on insertion.

**Labels.** `area:storage`, `kind:feature`, `tier:0`.

---

### E04_S02 — MVCC via `dataset.checkout(version=N)`

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E04_S01

**Description.** LanceDB exposes a native versioning mechanism: every `write` operation on a dataset creates a new integer version (starting from 1). Readers can pin a specific version by calling `dataset.checkout(version=N)`, which returns a read-only view of the dataset as it existed after version N was written. This mechanism is the correct way to implement concurrent read-write safety; manual symlink swaps (`lancedb/current → lancedb/v0003/`) are explicitly prohibited.

This milestone wires the MVCC mechanism into the ingestion pipeline. Each `write_chunks` call (E04_S01) returns the new dataset version number. This version is written to the `corpus-version.json` marker file (E04_S03). The MCP server reads this version on startup and passes it to `dataset.checkout(version=N)` before issuing any ANN queries. The eval harness (E05) does the same.

Re-ingestion after a `chunker_version` bump (e.g. from `"v1.0"` to `"v1.1"`) works as follows: the ingestion pipeline appends new-version rows to the LanceDB dataset, creating a new dataset version N+1. Old rows with `chunker_version="v1.0"` are not deleted immediately — they are still accessible via `dataset.checkout(version=N)`. A compaction job (outside this milestone's scope; noted in E11) can GC old versions after readers have migrated.

Writers must not call `dataset.checkout(version=N)` — checkout is read-only. Writers always operate on the current (latest) dataset version via the standard LanceDB write API. This distinction is documented in `ingest/store.py`'s module docstring.

There are no manual symlinks in `var/arxmcp/index/lancedb/`. If a symlink exists from E01_S06's superseded v0001 directory convention, it is ignored (the LanceDB native path is `var/arxmcp/index/lancedb/chunks`, not a versioned subdirectory).

**Deliverables.**
- Updated `ingest/store.py` — `write_chunks` returns `int` (new dataset version)
- `server/corpus.py` — `open_chunks_table(lancedb_path: str, version: int) -> lancedb.Table` (wraps `dataset.checkout`)
- `pytest tests/test_mvcc.py` — test: write v1, then write v2 (adding one row), verify `checkout(1)` returns old row count and `checkout(2)` returns new row count

**Acceptance criteria.**
- [ ] `write_chunks` returns the new LanceDB dataset version integer on each call.
- [ ] `open_chunks_table(path, version=1)` returns the dataset as it was after the first write.
- [ ] `open_chunks_table(path, version=2)` returns the dataset after the second write.
- [ ] No symlinks created under `var/arxmcp/index/lancedb/` by any ingest or server code.
- [ ] Module docstring in `ingest/store.py` states: "No symlink swaps. LanceDB version int IS the corpus_version. Writers use the current dataset; readers call dataset.checkout(version=N)."
- [ ] MVCC test passes: write 10 chunks (v1), write 5 more (v2), assert checkout(v1).count == 10 and checkout(v2).count == 15 (or reflects LanceDB's actual append semantics).

**Out of scope.** Version GC / compaction (E11). BM25 index versioning (E04_S04 follows the same convention but independently). Reader version-pinning in the MCP server (E06, Sonnet B, uses `open_chunks_table`).

**Risk notes.**
- **Closes MEDIUM: symlink atomic swap.** The critique flagged that symlink swaps are non-atomic on most filesystems (POSIX `rename(2)` is atomic but symlink-repoint is not on some OS/FS combinations). LanceDB's built-in MVCC is atomic and crash-safe; this milestone eliminates the entire class of problem.
- LanceDB's `checkout` API may use different method names across versions (e.g. `as_of` in some releases). Pin the LanceDB version in `pyproject.toml` and verify the API name in tests.

**Labels.** `area:storage`, `kind:feature`, `tier:0`.

---

### E04_S03 — `corpus_version` marker file and cache invalidation contract

**Status:** NEW
**Tier:** 0
**Effort:** S
**Dependencies:** E04_S01, E04_S02

**Description.** Each ingestion run writes a JSON marker file at `var/arxmcp/index/lancedb/corpus-version.json` capturing the complete state of the current corpus version. The MCP server reads this file on startup to determine which LanceDB dataset version to pin, and uses the `corpus_version` integer as a cache namespace key for all server-side caches (implemented in E08_S03 by Sonnet B).

**Marker file schema:**
```json
{
  "version": 3,
  "chunker_version": "v1.0",
  "embedder_version": "bge-m3@abc1234",
  "created_at": "2026-05-06T12:34:56Z",
  "paper_count": 50,
  "chunk_count": 847
}
```

The `version` field is the LanceDB dataset version integer returned by `write_chunks`. It is the primary key used by the MCP server and eval harness to call `dataset.checkout(version=N)`. The `chunker_version` and `embedder_version` fields are informational and also used to invalidate caches: any cache entry keyed on an older `(corpus_version, chunker_version, embedder_version)` tuple is stale.

The cache invalidation contract (specified here for Sonnet B to implement in E08_S03): server-side caches MUST include `corpus_version` in their cache keys. When the MCP server starts and reads a new `corpus-version.json` with a higher `version` than its last-seen value, it clears all in-process caches keyed on the old version. This prevents stale cache hits after a corpus update without requiring a server restart.

The marker file is written atomically: the ingestion script writes to `corpus-version.json.tmp` and then renames to `corpus-version.json`. On POSIX, `rename(2)` is atomic; on Windows, a two-step copy-and-rename is used (documented in the module).

**Deliverables.**
- `ingest/store.py` — `write_corpus_version_marker(lancedb_path: str, version: int, chunker_version: str, embedder_version: str, paper_count: int, chunk_count: int)` function
- `var/arxmcp/index/lancedb/corpus-version.json` — written on each ingest run
- `server/corpus.py` — `read_corpus_version(lancedb_path: str) -> CorpusVersionInfo` dataclass
- Cache contract comment in `server/corpus.py`: "Downstream caches (E08_S03) must include corpus_version in their keys."
- `pytest tests/test_corpus_version.py` — test: write marker, read it back, assert fields match

**Acceptance criteria.**
- [ ] `corpus-version.json` is written on every successful ingest run.
- [ ] `version` field matches the LanceDB dataset version returned by `write_chunks`.
- [ ] File write is atomic (tmp + rename).
- [ ] `read_corpus_version` reads and deserializes the marker file into a typed dataclass.
- [ ] Cache contract comment is present in `server/corpus.py`.
- [ ] Test: write two successive ingest runs, assert `version` increments.

**Out of scope.** Server-side cache implementation (E08_S03, Sonnet B). Cache eviction logic (Sonnet B). BM25 index versioning (E04_S04).

**Risk notes.**
- **Closes MEDIUM: corpus_version cache invalidation.** This milestone specifies the marker file contract and the cache key inclusion requirement. Sonnet B implements the server-side cache in E08_S03 and must honor the contract defined here. Any change to the marker file schema should be treated as a breaking contract change.

**Labels.** `area:storage`, `kind:feature`, `tier:0`.

---

### E04_S04 — BM25 index over `body_tokens`

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E02_S03, E04_S01, E04_S02, E04_S03

**Description.** Build a per-corpus-version BM25 index over the `body_tokens` field of all chunks. The BM25 index is stored on disk at `var/arxmcp/index/bm25/v<N>/` where `N` is the LanceDB corpus version. A pure Python implementation is used — either the `rank_bm25` library (BM25Okapi class) or a 30-line custom implementation using standard BM25 formula. No Rust, no Tantivy, no custom analyzer. Standard English tokenization (split on whitespace, lowercase, no stemming) is applied over the `body_tokens` field — because `body_tokens` has already been pre-tokenized by E02_S03 into a math-aware representation, a simple whitespace split is all that BM25 needs.

The BM25 index is built by reading all rows from the pinned LanceDB corpus version: `SELECT chunk_id, body_tokens FROM chunks WHERE body_tokens IS NOT NULL`. The `body_tokens` string for each chunk is split on whitespace to produce the token list. The BM25 corpus is the collection of these token lists, one per chunk. The chunk_id list (aligned with the BM25 corpus) is also persisted so that BM25 scores can be mapped back to chunk_ids.

Persistence format: the BM25 corpus state is serialized to `var/arxmcp/index/bm25/v<N>/bm25.pkl` using Python's `pickle` (or `joblib` for larger corpora). The aligned chunk_id list is stored as `var/arxmcp/index/bm25/v<N>/chunk_ids.json`. Both files must be present for a BM25 index to be considered valid for version N.

The BM25 indexer is exposed as `ingest/bm25_indexer.py` with API `build_bm25_index(lancedb_path: str, corpus_version: int) -> None`. The MCP server loads the BM25 index lazily on first lexical query (E07, Sonnet B).

**Deliverables.**
- `ingest/bm25_indexer.py` — `build_bm25_index(lancedb_path: str, corpus_version: int) -> None`
- `var/arxmcp/index/bm25/v<N>/bm25.pkl` — serialized BM25 state
- `var/arxmcp/index/bm25/v<N>/chunk_ids.json` — aligned chunk_id list
- `pytest tests/test_bm25.py` — test: build BM25 index from 20 fixture chunks, query "Spec mathrm_Pic", assert top result is the expected chunk

**Acceptance criteria.**
- [ ] BM25 index built from all non-null `body_tokens` rows in the pinned corpus version.
- [ ] `bm25.pkl` and `chunk_ids.json` are written to `var/arxmcp/index/bm25/v<N>/`.
- [ ] BM25 query over "Spec mathrm_Pic" returns the chunk containing those tokens with highest BM25 score.
- [ ] Building the index is idempotent: re-running on the same corpus version is a no-op if files already exist.
- [ ] Module docstring states: "Standard Python BM25 over pre-tokenized body_tokens. No Tantivy, no custom analyzer. See H4 remediation."
- [ ] BM25 index build time for 50 papers logged to `var/arxmcp/ops/bm25-stats.jsonl`.

**Out of scope.** Hybrid BM25 + ANN fusion at query time (E07, Sonnet B). BM25 index GC of old versions (E11). LaTeX-aware stemming (deferred; pure whitespace split over pre-tokenized `body_tokens` is sufficient at Tier 0).

**Risk notes.**
- **Closes H4 fully** (in combination with E02_S03): E02_S03 produced `body_tokens` via a Python regex pre-tokenizer; this milestone indexes those tokens with standard BM25. The fictional Tantivy LaTeX analyzer is never referenced again. The module docstring records this closure.
- `pickle` serialization is acceptable for Tier-0 corpus size (50 papers, ~1K chunks, BM25 index is a few MB). At Tier-5 scale (200K papers), the indexer must be replaced with a scalable solution (noted in E11); `pickle` is explicitly an in-process optimization, not a production indexing architecture.

**Labels.** `area:storage`, `kind:feature`, `tier:0`.
