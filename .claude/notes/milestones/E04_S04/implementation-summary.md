# E04_S04 Implementation Summary

**Commit:** `61ed46c` — `feat(ingest): BM25 index over body_tokens (E04_S04)`
**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 4 (2 new, 2 modified)
**Net diff:** +893 / 0

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `ingest/bm25_indexer.py` | NEW | `build_bm25_index()`, `BM25Stats` dataclass, atomic-write helpers, naming constants, H4 docstring |
| `tests/test_bm25.py` | NEW | 14 tests across 8 classes |
| `tests/conftest.py` | modified | new `_patched_bm25_stats_path` autouse fixture |
| `pyproject.toml` | modified | adds `rank-bm25>=0.2` |

## Decisions exercised from research-synthesis.md

| Decision | Where it landed |
|---|---|
| D1 `rank_bm25` (BM25Okapi defaults) | `ingest/bm25_indexer.py:184` |
| D2 module name `bm25_indexer.py` | matches brief verbatim |
| D3 constants in `bm25_indexer.py`, not `store.py` | `BM25_DIR_NAME` etc. |
| D4 read via `server.corpus.open_chunks_table` | `ingest/bm25_indexer.py:172` |
| D5 trust caller's `corpus_version` | docstring documents this |
| D6 atomic writes for both files | `_atomic_write_bytes` + `_atomic_write_text` |
| D7 idempotent skip — both files must be `is_file()` | `ingest/bm25_indexer.py:158-167` |
| D8 empty corpus raises ValueError | `ingest/bm25_indexer.py:177-180` |
| D9 Threat 1 deferral block | `build_bm25_index` docstring |
| D10 pickle security paragraph | module docstring |
| D11 `bm25-stats.jsonl` mirroring store-stats | `_append_bm25_stats` |
| D12 H4 sentence verbatim in docstring | locked by `TestModuleContract.test_docstring_h4_remediation_sentence` |
| D13 curated `body_tokens` test fixtures | `_curated_corpus()` helper |
| D14 conftest autouse fixture | `tests/conftest.py:46` |

## Test results

- 503 passed, 2 skipped (1 pre-existing + 1 env-gated BGE-M3 integration)
- ruff clean
- 14 new tests in `tests/test_bm25.py`

## Acceptance-criteria mapping

| Brief criterion | Test |
|---|---|
| BM25 built from non-null body_tokens in pinned version | `TestBuildIndex.test_writes_pkl_and_chunk_ids` (uses `open_chunks_table`) |
| `bm25.pkl` + `chunk_ids.json` written | `TestBuildIndex.test_writes_pkl_and_chunk_ids` |
| Query "Spec mathrm_Pic" returns target chunk top-1 | `TestQueryAccuracy.test_query_spec_mathrm_pic_returns_target_chunk` |
| Idempotent re-run | `TestIdempotency.test_rerun_is_skipped_when_files_exist` |
| Module docstring has H4 remediation sentence | `TestModuleContract.test_docstring_h4_remediation_sentence` |
| Build time logged to `bm25-stats.jsonl` | `TestStatsLogging.test_stats_line_appended_on_build` |

## Notable design choices for the critic

- **Curated test fixtures** rather than full chunker pipeline. The brief's query "Spec mathrm_Pic" cannot match the actual `tokenize_body("\\mathrm{Spec}")` output (which produces `"mathrm_Spec"`). The test uses hand-crafted `body_tokens` strings to control the exact tokens. Documented in `TestQueryAccuracy` docstring + the test file's module docstring.
- **`BM25_INDEX_ROOT` is monkey-patched in tests** to redirect into `tmp_path`. `BM25_STATS_PATH` is auto-patched via `tests/conftest.py`. No tests pollute the developer's `var/` tree.
- **`_atomic_write_bytes` and `_atomic_write_text` are local to `bm25_indexer.py`** rather than hoisted into a shared utility. The pattern is repeated in `preamble.py`, `embedder.py`, `store.py`, and now `bm25_indexer.py` — extracting it is a separate housekeeping commit (matches E04_S02 F11's "if a future side-file needs atomic writes, copy from `preamble._write_preamble_json`").
- **Single-source-of-truth scan** locks both the named constants AND the `f"v{N}"` literal: the directory-naming pattern lives in exactly one function (`_bm25_version_dir`).
- **`pickle.HIGHEST_PROTOCOL`** for the BM25 pickle. Reduces file size; no portability concern (we control both writer and reader).
- **chunk_ids.json written FIRST** (text), then `bm25.pkl` (binary). A crash between the two leaves a partial state that the next run rebuilds (idempotent skip checks BOTH files via `is_file()`).

## Out-of-scope (deferred per brief)

- Hybrid BM25 + ANN fusion at query time — E07 (Sonnet B)
- BM25 index GC of old versions — E11
- LaTeX-aware stemming — deferred (whitespace split over pre-tokenized body_tokens is sufficient at Tier 0)
