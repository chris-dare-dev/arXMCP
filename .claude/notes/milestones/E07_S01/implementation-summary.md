# E07_S01 — Implementation summary

**One-line:** Phase-1 BM25 retrieval — `BM25Phase` class loads E04_S04's `bm25.pkl` artifact (auto-builds if missing), file-safety-checks before `pickle.load`, returns top-200 candidates plus filter warnings.

## Files

### NEW: `server/retrieval/__init__.py` + `server/retrieval/bm25.py` (~430 LOC)

`BM25Phase` class with:
- **`startup(lancedb_path, corpus_version) -> BM25Phase`** (async classmethod) — production entry point. Off-loads to default executor; resolves the per-version artifact path; auto-builds if missing (closes E04_S04 H1); file-safety-checks both files (closes E04_S04 TODO(E07)); validates corpus_size == len(chunk_ids); returns ready instance.
- **`query(text, filters=None, top_n=200) -> tuple[list[tuple[str,float]], list[str]]`** (sync) — tokenizes via `ingest.tokenizer.tokenize_body` (parity with index-time); scores via `BM25Okapi.get_scores` (read-only after construction, safe under concurrent readers); over-fetches `top_n * 4` when a supported filter is present; post-filters by `paper_id`; returns `(candidates, filter_warnings)`.

Two new error classes:
- `BM25IndexUnavailableError(RuntimeError)` — pickle missing AND auto-build failed.
- `BM25IndexUnsafeError(BM25IndexUnavailableError)` — pickle exists but ownership mismatch OR world-writable. Subclass so a single `except` clause in `Resources.startup` catches both.

Module constants:
- `DEFAULT_TOP_N = 200`
- `OVER_FETCH_FACTOR = 4`
- `SUPPORTED_FILTER_KEYS = frozenset({"paper_id"})`
- `DEFERRED_FILTER_KEYS = frozenset({"categories", "year_min", "year_max", "authors", "include_withdrawn"})`

### MODIFIED: `server/resources.py`

Added `bm25_phase: Any | None = None` field on the `Resources` dataclass. Inserted step 4b in `Resources.startup`: `await BM25Phase.startup(lancedb_path, corpus_info.version)`. Failure raises `BM25IndexUnavailableError` which propagates through the lifespan's broad `except Exception` and produces a FATAL log + `/readyz` never opens.

### NEW: `tests/retrieval/__init__.py` + `tests/retrieval/test_bm25.py` (~470 LOC, 39 tests)

Test classes:
- **`TestKnownGoodQueries`** (8 tests) — 5 hand-crafted target queries (`étale cohomology`, `\Spec \mathrm{Pic}`, `Hilbert spectral`, `H_1 fundamental group`, `\partial \mathbb{Z}`) each asserting the top result is the expected chunk + a 500ms time-budget assertion (5 calls, max), chunk_id format validation, and existence in LanceDB.
- **`TestFilters`** (9 tests) — brief AC #2 reinterpreted: unsupported filter keys (`categories`, `year_min`, `year_max`, `authors`, `include_withdrawn`) surface as `filter_warnings`; the supported `paper_id` filter actually narrows the result set (string OR list of strings); unknown keys emit a warning naming the legal sets.
- **`TestTopNCap`** (4 tests) — `DEFAULT_TOP_N == 200`, length ≤ requested cap, length ≤ default cap, `top_n=0` rejected.
- **`TestFileSafetyCheck`** (4 tests, POSIX-only) — safe file passes; world-writable rejected with `BM25IndexUnsafeError`; missing file raises `BM25IndexUnavailableError`; `BM25IndexUnsafeError` is a subclass of `BM25IndexUnavailableError`.
- **`TestAutoBuild`** (3 tests) — auto-builds when artifact missing; warm-start uses existing artifact (mtime unchanged); build failure raises `BM25IndexUnavailableError`.
- **`TestTokenizationParity`** (3 tests) — raw `\Spec` matches indexed `Spec`; `\mathrm{Pic}` matches `mathrm_Pic`; punctuation-only query returns empty.
- **`TestArtifactIntegrity`** (1 test) — misaligned (corpus_size, chunk_ids) pair rejected at load.
- **`TestReturnShape`** (4 tests) — return is `tuple[list[tuple[str,float]], list[str]]`; candidates sorted descending by score.
- **`TestConcurrentReaders`** (1 test) — 32 concurrent threads return identical results (validates `BM25Okapi` thread-safety claim).
- **`TestAsyncStartup`** (1 test) — `await BM25Phase.startup(...)` returns a working `BM25Phase`.
- **`TestCorruptPickleHandling`** (1 test) — corrupted pickle bytes raise during load (does not silently produce a working phase).

## Acceptance criteria

| Brief AC | Reinterpretation | Status | Evidence |
|---|---|---|---|
| `BM25Phase.query("étale cohomology")` non-empty <500ms | unchanged | met | `TestKnownGoodQueries::test_etale_cohomology` + `::test_etale_cohomology_under_500ms` |
| `BM25Phase.query("\\Spec", filters={"categories":...})` returns only math.AG | reinterpreted: surfaces non-empty `filter_warnings` (the chunks table has no `categories` column; deferred to a future `papers` metadata milestone). The `paper_id` filter (a real column) IS honored and narrows results. | met | `TestFilters::test_categories_filter_surfaces_warning` + `::test_paper_id_filter_narrows` |
| Returned list length ≤ 200 | unchanged | met | `TestTopNCap` (4 tests) |
| `chunk_id` values present in LanceDB table | unchanged | met | `TestKnownGoodQueries::test_chunk_ids_present_in_lancedb` |
| `pytest tests/retrieval/test_bm25.py` passes | unchanged | met | 39 passed |

## Deviations from the brief

1. **Filter columns reality.** The brief lists `categories`, `year_min`, `year_max`, `authors`, `include_withdrawn` as filter keys. NONE of those exist on the `chunks` table (verified in `ingest/schema.py:69-118`); the `papers` metadata table planned in E06_S03 brief 1 has not been built. The implementation honors `paper_id` (a real column) and surfaces all other keys as `filter_warnings` — same precedent as `server/handlers/search.py:131-141` (E06_S03 F6 fix). The reinterpreted AC is documented in the table above and in the test class docstring.

2. **Return shape extended.** The brief specified `list[tuple[str, float]]`; we return `tuple[list[tuple[str, float]], list[str]]` so the upstream caller (E07_S02 RRF) receives `filter_warnings` without an extra side-channel call. Documented in `server/retrieval/bm25.py` module docstring and `tests/retrieval/test_bm25.py::TestReturnShape`.

3. **`body_canonical` fallback dropped.** The brief mentions a fallback to "the prose `body_canonical` BM25 index". That column does not exist (the chunks table has `body_text` and `body_tokens`); no separate prose index was ever built. The implementation fails-fast via `BM25IndexUnavailableError` rather than silently degrading. Documented in module docstring.

## What this milestone closes from prior critiques

- **E04_S04 H1**: "`build_bm25_index` has zero production call sites" — `BM25Phase.startup` now invokes it from the server's startup path if the per-version artifact is missing.
- **E04_S04 TODO(E07)** at `ingest/bm25_indexer.py:62-71`: "the loader (in `:mod:`server`) MUST verify file ownership matches process UID and refuse world-writable paths before calling `pickle.load`." `_assert_pickle_file_safe` now enforces both checks before every `pickle.load`. Defense against Threat 6 (`08-security-observability-ops.md`).

## External writes the orchestrator must authorize

None. Purely-internal retrieval milestone. The `--update-tool-schema-hash` flag is unaffected (no tool schema bytes change). The pinned `EXPECTED_TOOL_SCHEMA_SHA256` from E06_S06 remains valid.

## Project check command

`ruff check .` — clean.
`pytest -q` — **831 passed, 3 skipped** (was 792 pre-milestone — +39 from this milestone, no regressions).
