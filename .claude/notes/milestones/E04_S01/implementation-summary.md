# E04_S01 Implementation Summary

**Commit:** `db0a4de` — `feat(ingest): LanceDB chunks table v1 schema + writer (E04_S01)`
**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 4 (3 new, 1 modified)
**Net diff:** +1260 / 0

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `ingest/schema.py` | NEW | `CHUNKS_TABLE_NAME`, `CHUNKS_SCHEMA_V1`, `EmbedRecord` dataclass with `__post_init__` invariant checks |
| `ingest/store.py` | NEW | `write_chunks`, `load_embed_record`, `WriteStats`, `_build_arrow_table`, `_create_indices`, `_append_store_stats` |
| `tests/test_store.py` | NEW | 28 tests across 10 classes — schema contract, single-source-of-truth, EmbedRecord constructor, table creation, row count, idempotency, indices, embedding routing, validation guards, store stats, load_embed_record round-trip |
| `pyproject.toml` | modified | adds `lancedb>=0.6`, `pyarrow>=14.0` |

## Decisions exercised from research-synthesis.md

| Decision | Where it landed |
|---|---|
| D1 lancedb + pyarrow added | pyproject.toml deps with explanatory comments |
| D2 EmbedRecord dataclass + __post_init__ invariants | ingest/schema.py:EmbedRecord |
| D3 Schema in ingest/schema.py imported by store.py | ingest/schema.py:CHUNKS_SCHEMA_V1 |
| D4 Single-source-of-truth (EMBEDDING_DIM imported, no stray literals) | covered by existing scan tests + new TestSingleSourceOfTruth |
| D5 merge_insert(on="chunk_id") upsert | ingest/store.py:write_chunks |
| D6 IVF_HNSW_SQ(m=16, ef_construction=200) via direct kwargs (lancedb 0.30 API) | _create_indices |
| D7 NPZ alignment validation | _build_arrow_table — raises if chunks missing from EmbedRecord |
| D8 body_tokens=None raises | _build_arrow_table — D8 guard |
| D9 Zero-row sentinel handling | natural — empty zip iterations leave embedding_*=None |
| D10 Write-stats JSONL log | _append_store_stats → var/arxmcp/ops/store-stats.jsonl |
| D11 Real LanceDB on tmp_path; no model load | tests use np.random for synthetic vectors |

## Test results

- 435 passed, 2 skipped (1 pre-existing + 1 env-gated BGE-M3 integration)
- ruff clean
- 28 new tests in tests/test_store.py

## Acceptance-criteria mapping

| Brief criterion | Test |
|---|---|
| Table created on first write | `TestTableCreation.test_first_write_creates_table` |
| Schema matches v1 column list exactly | `TestSchemaContract.*` (5 tests) |
| HNSW indices on `embedding_stmt` + `embedding_proof` | `TestIndices.test_hnsw_indices_created_after_write` |
| `embedding_eq` present + null on rows | `TestEmbeddingRouting.test_embedding_eq_null_on_all_rows` |
| Idempotent on duplicate chunk_id | `TestIdempotency.test_second_write_no_duplicates` + `test_second_write_updates_existing_row` |
| 10 chunks → count_rows() == 10 | `TestRowCount.test_ten_chunks_count_rows_eq_ten` |
| Schema imported from a single schema.py module | `TestSingleSourceOfTruth.test_store_imports_schema_does_not_redefine` |

## API surface drift handled defensively

- `lancedb.connect().list_tables()` returns a `ListTablesResponse` in 0.30 (was a plain list in 0.6); the code uses `getattr(obj, "tables", obj)` to accept both.
- `tbl.create_index(config=HnswSq(...))` was removed in 0.30; the new direct-kwarg form `create_index(vector_column_name=..., index_type="IVF_HNSW_SQ", m=16, ef_construction=200, replace=True)` is now used. The whole call is wrapped in a `try/except` so a future API change surfaces as a logged WARNING rather than a hard failure of the entire write.

## Out-of-scope (deferred per brief)

- MVCC version pinning by readers — E04_S02
- BM25 index over `body_tokens` — E04_S04
- `corpus_version` marker file — E04_S03
- Equation embedding population (`embedding_eq`) — E10_S03
- A pipeline driver that calls `chunk_paper → embed_paper → write_chunks` for the corpus — E04_S03 likely

## Notable design choices for the critic

- The `lancedb` and `pyarrow` packages are real runtime deps, not test-only. The integration test creates a real LanceDB on `tmp_path` (~10ms per test) — no mocking.
- `_build_arrow_table` validates row-alignment (D7) and `body_tokens` non-None (D8) BEFORE the LanceDB write so a failure produces a clear `ValueError` rather than a confusing PyArrow / Lance internal error.
- The `EmbedRecord.__post_init__` validation is a second layer of defense — even if a future caller bypasses `_build_arrow_table` directly, malformed records can't survive construction.
- `WriteStats.indices_created` records WHICH indices succeeded — partial-index state is observable in ops logs rather than silently masked.
- `_atomic_write_json` in store.py is currently unused but kept for future side-files. Reviewable choice to leave it dead-but-discoverable vs. delete.
