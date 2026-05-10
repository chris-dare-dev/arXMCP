# E04_S02 Implementation Summary

**Commit:** `b9d6b13` — `feat(server): MVCC version pinning via dataset.checkout (E04_S02)`
**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 3 (2 new, 1 modified)
**Net diff:** +431 / 0

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `server/corpus.py` | NEW | `open_chunks_table(lancedb_path, version)` — read-only handle pinned via `tbl.checkout(N)` |
| `tests/test_mvcc.py` | NEW | 10 tests across 6 classes |
| `ingest/store.py` | modified | Module docstring gains "MVCC handshake (E04_S02)" paragraph carrying the AC5 sentence verbatim; dataset_version comment explains post-index vs post-merge |

## Decisions exercised from research-synthesis.md

| Decision | Where it landed |
|---|---|
| D1 `tbl.checkout(N)` is the correct API (lancedb 0.30) | `server/corpus.py:open_chunks_table` |
| D2 `tbl.version` returns the post-index version — keep it (not `merge_result.version`) | `ingest/store.py` clarifying comment + docstring paragraph |
| D3 `server/corpus.py` shape per the synthesis sketch | landed verbatim |
| D4 AC5 docstring sentence | `ingest/store.py` "MVCC handshake" paragraph |
| D5 6 named tests | `tests/test_mvcc.py` (split into 10 individual tests for clarity) |
| D6 Single-source-of-truth scan | `TestSingleSourceOfTruth.test_corpus_imports_table_name_does_not_redefine` |
| D7 No `pyproject.toml` change | confirmed |
| D8 No symlinks created | `TestNoSymlinks.test_no_symlinks_under_lancedb_root` |
| D9 HNSW + checkout interaction documented | `server/corpus.py` module docstring |

## Test results

- 456 passed, 2 skipped (1 pre-existing + 1 env-gated BGE-M3 integration)
- ruff clean
- 10 new tests in `tests/test_mvcc.py`

## Acceptance-criteria mapping

| Brief criterion | Test |
|---|---|
| `write_chunks` returns int | `TestVersionIsInt.test_write_chunks_returns_int` |
| `open_chunks_table(path, v_a).count == 10` | `TestVersionPinning.test_checkout_pre_and_post_second_write` |
| `open_chunks_table(path, v_b).count == 15` | `TestVersionPinning.test_checkout_pre_and_post_second_write` |
| No symlinks under `var/arxmcp/index/lancedb/` | `TestNoSymlinks.test_no_symlinks_under_lancedb_root` |
| Module docstring states the AC5 sentence | `TestDocstringContract.test_store_docstring_states_mvcc_handshake` |
| MVCC test passes (10/v1, 15/v2) | `TestVersionPinning.test_checkout_pre_and_post_second_write` |

## Notable design choices

- **Live-tested API.** Before writing `server/corpus.py` I ran a small experiment against lancedb 0.30.2 to verify the `checkout` API name, version-numbering semantics (1-indexed, `create_table` produces version 1), and that `tbl.version` after a full `write_chunks` is the post-index version. Verbatim output captured in `research-synthesis.md`.
- **Researcher disagreement resolved.** Sonnet-A recommended switching from `tbl.version` to `merge_result.version`. Sonnet-B confirmed the in-place mutation semantics. The live test broke the tie: `tbl.version` after `write_chunks` is the post-index version, which IS what we want for indexed-ANN MVCC pinning. The `merge_result.version` is the pre-index version — readers pinning to it would silently get brute-force ANN. Kept the current code.
- **No defensive write-rejection wrapper** on the returned table. LanceDB's own write guard raises `ValueError` on writes after `checkout`; adding a wrapper would be redundant complexity.
- **Each call returns a fresh handle.** `checkout` mutates in place, so a shared table passed to `checkout` would corrupt other readers. The function opens a fresh handle every call. Server-layer caching (E06) caches the *returned* handle, not the intermediate `open_table` result.
- **Synchronous API.** LanceDB local mode is fully synchronous in 0.30.2; `open_chunks_table` is a regular `def`, not `async def`.

## Out-of-scope (deferred per brief)

- Version GC / compaction — E11
- BM25 index versioning — E04_S04 (independent of vector-store MVCC)
- Reader version-pinning in the MCP server — E06 (uses `open_chunks_table`)
- `corpus-version.json` marker file write — E04_S03
