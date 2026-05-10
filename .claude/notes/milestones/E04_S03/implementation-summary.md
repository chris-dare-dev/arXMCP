# E04_S03 Implementation Summary

**Commit:** `6d12138` — `feat(ingest): corpus_version marker file + cache contract (E04_S03)`
**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 3 (1 new, 2 modified)
**Net diff:** +657 / −3

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `ingest/store.py` | modified | `write_corpus_version_marker()` function + auto-call from `write_chunks` after `_append_store_stats`; new `CORPUS_VERSION_MARKER_NAME` constant; new top-level `os`, `uuid`, `contextlib`, `datetime` imports |
| `server/corpus.py` | modified | `CorpusVersionInfo` dataclass + `read_corpus_version()` function; cache-invalidation contract paragraph in module docstring |
| `tests/test_corpus_version.py` | NEW | 18 tests across 6 classes |

## Decisions exercised from research-synthesis.md

| Decision | Where it landed |
|---|---|
| D1 Auto-call `write_corpus_version_marker` from `write_chunks` | `ingest/store.py` — after `_append_store_stats`, wrapped in `try/except OSError` |
| D2 Parameters per brief (not auto-import) | `write_corpus_version_marker` signature matches brief verbatim |
| D3 Atomic write via tmp + os.replace | inside `write_corpus_version_marker` — copies preamble.py pattern |
| D4 `created_at` retained, lenient `from_dict` | `CorpusVersionInfo.from_dict(data)` uses `data.get("created_at", "")` |
| D5 `created_at` format `"%Y-%m-%dT%H:%M:%SZ"` | `datetime.now(timezone.utc).strftime(...)` |
| D6 `read_corpus_version` returns `None` on absent, raises on corrupt | `server/corpus.py` |
| D7 Default path symmetry | both reader and writer accept `lancedb_path: str \| Path \| None = None` |
| D8 `paper_count`/`chunk_count` derived in `write_chunks` | `len({c.paper_id for c in chunks})` and `len(chunks)` |
| D9 `CorpusVersionInfo` dataclass with `to_dict`/`from_dict` | `server/corpus.py` |
| D10 Cache contract paragraph in `server/corpus.py` docstring | landed verbatim per brief's "Downstream caches (E08_S03) must include corpus_version in their keys." |
| D11 5 test classes covering all ACs | 6 classes, 18 tests |

## Test results

- 480 passed, 2 skipped (1 pre-existing + 1 env-gated BGE-M3 integration)
- ruff clean
- 18 new tests in `tests/test_corpus_version.py`

## Acceptance-criteria mapping

| Brief criterion | Test |
|---|---|
| `corpus-version.json` written on every successful ingest run | `TestWriteOnIngest.test_marker_written_on_every_successful_ingest` |
| `version` matches `write_chunks` return | `TestWriteOnIngest.test_marker_written_on_every_successful_ingest` |
| Atomic write (tmp + rename) | `TestAtomicWrite.test_no_tmp_files_after_successful_write` + `test_tmp_filename_includes_pid_and_uuid` |
| `read_corpus_version` returns typed dataclass | `TestReadMarker.test_round_trip_via_writer_and_reader` |
| Cache contract comment in `server/corpus.py` | `TestCacheContract.test_corpus_module_docstring_states_cache_contract` |
| Two ingest runs → version increments | `TestVersionIncrements.test_marker_version_increments_across_runs` |

## Out-of-scope (deferred per brief)

- Server-side cache implementation — E08_S03 (Sonnet B)
- BM25 index versioning — E04_S04
- Cache eviction logic — Sonnet B

## Notable design choices for the critic

- **`created_at` is debug-only and outside BP1.** The marker file is a runtime config artifact read by the MCP server at startup — it never enters the prompt cache or tool-result payloads. Two consecutive ingest runs of an unchanged corpus will produce different marker bytes (the timestamp differs) but this is intentional: the version integer is what readers and caches care about, and that increments only on actual write_chunks calls.
- **`from_dict` is lenient on `created_at` only.** Other fields (`version`, `chunker_version`, `embedder_version`, `paper_count`, `chunk_count`) raise `KeyError` if absent. Tests cover both leniency and strictness.
- **Marker write failure does NOT abort the ingest.** A `try/except OSError` wraps the call in `write_chunks` — the LanceDB write has already succeeded; a missing marker is recoverable (server falls back to live-tip pinning via `open_chunks_table(path, version=None)`).
- **Single-source-of-truth: `CORPUS_VERSION_MARKER_NAME`** is defined once in `ingest/store.py` and imported by `server/corpus.py`. Neither module contains the bare string `"corpus-version.json"`.
- **Reader contract:** absent → `None`; corrupt → `ValueError`. Mirrors the discipline established by `embedder._read_embeddings_manifest` and `preamble._read_existing_preamble`.
- **No `pyproject.toml` change.** All imports are stdlib (`datetime`, `os`, `uuid`, `contextlib`, `json`, `dataclasses`).
