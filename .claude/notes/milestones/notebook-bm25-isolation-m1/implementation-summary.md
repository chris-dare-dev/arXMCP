# Implementation Summary — notebook-bm25-isolation-m1

**One-line summary:** Add per-notebook BM25 index root, isolating fork-C artifacts from shared corpus
**Commit range:** 096be65..f6138a5
**Branch:** main
**Date:** 2026-05-29T00:00:00Z

## Acceptance criteria status

- [x] AC-1: A fork-C server (`ARXMCP_NOTEBOOK=<slug>`) loads/builds its BM25 under
  `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`, NOT the global root — met.
  The `derive_notebook_lancedb_path` validator sets `bm25_index_root = derived.parent / "index" / "bm25"`;
  `BM25Phase.startup` receives it via `resources.py` and passes it down through `_sync_startup`.
- [x] AC-2: The shared (non-notebook) server uses the global `var/arxmcp/index/bm25/v<N>/`,
  unchanged — met. When `notebook is None`, the validator early-returns and `bm25_index_root`
  stays `None`; `_bm25_version_dir(v, index_root=None)` resolves `BM25_INDEX_ROOT` at call time.
  Config test `test_shared_config_has_none_bm25_index_root` asserts `bm25_index_root is None`.
- [x] AC-3: Regression test — two builds at the same version N with different `index_root` resolve
  to non-overlapping artifact paths — met. `TestBM25IndexRootIsolation.test_build_bm25_index_per_root_no_overlap`
  builds two corpora at version 1 under distinct roots and verifies separate `chunk_ids.json` contents.
  `test_version_dirs_differ_with_different_index_roots` asserts the structural guarantee.
- [x] AC-4: The `.notebook_slug` sentinel workaround is removed; `notebook_ingest.py` builds
  under the per-notebook root; docstring updated — met. Sentinel logic (lines 132–157 pre-fix) replaced
  with `bm25_root = nb_dir / "index" / "bm25"` and `build_bm25_index(..., index_root=bm25_root)`.
  Docstring updated to document the per-notebook root and FM-1 auto-build fallback.
- [x] AC-5: `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED; `make test` green
  (the ~40 `BM25_INDEX_ROOT`-monkeypatching tests still pass) — met. No MCP tool, no prompts.py
  change. 3361 tests pass (3 pre-existing failures: latexmlc ×2, cite_neighbors ×1). Ruff clean.

## New and changed files

- `ingest/bm25_indexer.py` — added `index_root: Path | None = None` to `_bm25_version_dir` and
  `build_bm25_index`; `None` resolves `BM25_INDEX_ROOT` lazily at call time (preserves monkeypatch)
- `server/config.py` — added `bm25_index_root: Path | None = None` field; fork-C validator
  `derive_notebook_lancedb_path` sets it to `derived.parent / "index" / "bm25"` (mirroring `cache_db_path`)
- `server/retrieval/bm25.py` — added `bm25_index_root: Path | None = None` to `startup` and
  `_sync_startup`; threaded through both load path (`_bm25_version_dir(v, index_root=...)`) and
  auto-build path (`build_bm25_index(..., index_root=...)`); used `functools.partial` in executor call
- `server/resources.py` — pass `bm25_index_root=config.bm25_index_root` to `BM25Phase.startup`
- `tools/notebook_ingest.py` — removed sentinel workaround; build under `nb_dir / "index" / "bm25"`;
  stale-version warning enumerates per-notebook root; docstring updated for new isolation design

## New and changed tests

- `tests/test_bm25.py` — new class `TestBM25IndexRootIsolation` (3 tests):
  - `test_version_dirs_differ_with_different_index_roots` — structural: same N + different root → different dirs
  - `test_build_bm25_index_per_root_no_overlap` — AC-3 regression: two builds at same N under distinct roots
    produce separate artifact dirs with correct per-notebook chunk_ids (MUST fail on pre-fix code)
  - `test_none_index_root_uses_monkeypatched_global` — FM-6: `index_root=None` resolves patchable global
- `tests/test_server_startup.py` — 3 new tests in `TestNotebookConfig`:
  - `test_shared_config_has_none_bm25_index_root` — AC-2 / FM-4: shared config → `bm25_index_root is None`
  - `test_notebook_derives_per_notebook_bm25_index_root` — AC-1: fork-C → `<slug>/index/bm25`
  - `test_two_notebooks_derive_distinct_bm25_index_roots` — two notebooks at same MVCC → distinct roots
- `tests/tools/test_notebook_scripts.py` — replaced 3 sentinel-based tests with 3 updated ones:
  - `test_ingest_builds_bm25_under_per_notebook_root` — verifies `index_root` passed per-notebook
  - `test_ingest_per_notebook_bm25_root_no_collision` — two notebooks derive different roots
  - `test_ingest_warns_about_stale_bm25_versions` — stale-dir warning uses per-notebook root

## Deviations from the brief

None — implementation follows the brief exactly. The `functools.partial` approach for threading
`bm25_index_root` through `run_in_executor` is the standard Python pattern for adding keyword
args to executor calls (the alternative of adding a 4th positional arg to `_sync_startup` was
chosen to keep the function signature clean with keyword-only semantics at call sites).

## Failure modes mitigated

- **FM-1 (first-boot auto-build):** Documented in `notebook_ingest.py` docstring; `BM25Phase._sync_startup`
  auto-build is the safety net for notebooks migrating from pre-fix runs.
- **FM-4 (shared-corpus regression):** `bm25_index_root: Path | None = None` default + early-return
  in validator when `notebook is None` ensures shared path stays global.
- **FM-6 (monkeypatch preservation):** `None`-default lazy resolution of `BM25_INDEX_ROOT` at call time
  — the conftest autouse `monkeypatch.setattr(bm25_mod, "BM25_INDEX_ROOT", ...)` continues to intercept.
- **FM-7 (sentinel removal):** `.notebook_slug` sentinel logic removed entirely; per-notebook directory
  is the 1:1 isolation; no spurious `NotebookError` from misreading the global path.

## External writes the orchestrator must authorize

None — this milestone is purely local.
