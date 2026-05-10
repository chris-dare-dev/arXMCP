# E03_S02 Implementation Summary

**Commit:** `6f183be` — `feat(ingest): idempotent re-embed with sidecar manifest (E03_S02)`
**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 2 (1 new test file, 1 modified embedder)
**Net diff:** +1021 / −1

## Decisions exercised from research-synthesis.md

| Synthesis decision | Where it landed |
|---|---|
| D1 NPZ-first adaptation | docstring + skip path uses sidecar JSON, never LanceDB |
| D2 `EXPECTED_CHUNKER_VERSION = CHUNKER_VERSION` (alias) | line 86–93 of `embedder.py`: `from ingest.chunker_types import CHUNKER_VERSION as EXPECTED_CHUNKER_VERSION` |
| D3 POSIX-atomic restatement | module docstring "Idempotent re-embed (E03_S02)" section |
| D4 Populate `EmbedStats.chunks_skipped` | wired in `_embed_paper_impl` skip branch |
| D5 Corpus-level "all up to date" log | `embed_corpus` post-loop block, info level |
| D6 Sidecar `embeddings_manifest.json` (option (b)) | new `_write_embeddings_manifest`, `_read_embeddings_manifest`, `_paper_is_up_to_date` |
| D7 Sidecar schema (alphabetical, no timestamps) | `_write_embeddings_manifest` body |
| D8 Whole-paper rewrite on any change | skip is paper-level; if any chunk fails any condition, re-encode everything for that paper |
| D9 Five named tests | `tests/test_embedder_idempotent.py` (19 tests across 7 classes) |
| D10 Mock model in tests | `_fake_model_factory` reused with `call_count` counter |

## Test results

- 371 passed, 1 skipped (the skip is pre-existing; unrelated)
- 19 new tests across 7 classes in `tests/test_embedder_idempotent.py`
- ruff clean
- `tests/test_chunker_ids.py::test_v1_0_literal_count_in_ingest_package`
  remains green — the alias adds no new `"v1.0"` literals to `ingest/`

## Acceptance-criteria mapping

| Brief criterion | Test |
|---|---|
| Re-running on unchanged corpus writes 0 rows + logs "all up to date" | `TestZeroWritesOnRerun.test_second_run_is_zero_writes` + `test_run_summary_includes_chunks_skipped` |
| Mismatched `chunker_version` forces re-embed | `TestVersionMismatchForcesReembed.test_chunker_version_mismatch_forces_reembed` |
| New chunks since last embed are embedded | `TestNewChunkPath.test_new_chunk_is_embedded_others_skipped` |
| `EXPECTED_CHUNKER_VERSION` defined exactly once | `TestSingleSourceOfTruth.test_expected_chunker_version_is_alias` (object identity) + the existing global v1.0-literal regression in `test_chunker_ids.py` |
| Concurrent processes don't corrupt | `TestConcurrency.test_concurrent_writes_do_not_corrupt` |

## Out-of-scope (deferred per brief)

- MVCC version management (E04_S02) — orphan-vector GC, schema migrations
- BM25 index re-build on chunker_version bump (E04_S04)
- GPU acceleration (E11)
- Chunk-level partial NPZ updates — `np.savez` does not support
  appending to a ZIP archive; whole-paper rewrites are the simplest
  correct semantics. A future optimization could read existing
  vectors from the NPZ and merge with newly-encoded ones, but the
  brief acceptance criteria are met by paper-level idempotency.

## Additive correctness improvement beyond the brief

The brief literally only requires gating skip on `chunker_version`. We
also gate on `embedder_version` because a `BGE_M3_COMMIT_SHA` bump
produces vectors in a different embedding space, and silently mixing
old + new vectors would poison cosine-similarity ranking. This is
documented in `_paper_is_up_to_date`'s docstring and exercised by
`test_embedder_version_mismatch_forces_reembed`.

## File-level changes

### `ingest/embedder.py` (+228 / −1)

- Module docstring: new "Idempotent re-embed (E03_S02)" section
  documenting the sidecar handshake and POSIX-atomic concurrency.
- New import: `EXPECTED_CHUNKER_VERSION` aliased from
  `chunker_types.CHUNKER_VERSION`.
- New helpers: `EMBEDDINGS_MANIFEST_NAME`, `_write_embeddings_manifest`,
  `_read_embeddings_manifest`, `_paper_is_up_to_date`.
- `_embed_paper_impl`: pre-flight skip via `_paper_is_up_to_date`;
  sidecar write after NPZ write.
- `embed_corpus`: corpus-level "all up to date" info log.
- `_append_run_summary`: aggregate `chunks_skipped` field.

### `tests/test_embedder_idempotent.py` (NEW, 1021 LOC)

7 test classes, 19 tests. The fake-model factory carries a
`call_count` counter so skip-path tests can assert the model was
never invoked.
