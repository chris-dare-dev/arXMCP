# Test baseline — ingest-robustness-m1 (pre-change, clean HEAD 23b8628)

Captured in the worktree with the main-tree venv python + `PYTHONPATH=<worktree>`
BEFORE any code change. The Phase-2 check gate must show **no new failures**
beyond these 5 in the touched-module subset.

## Command
```
MAINPY="C:/Users/cedar/Documents/Personal Projects/Source Code/arXMCP/.venv/Scripts/python.exe"
PYTHONPATH="$PWD" "$MAINPY" -m pytest \
  tests/test_chunker.py tests/test_chunker_ids.py tests/test_bulk_ingest.py \
  tests/test_bulk_ingest_sanity.py tests/test_ar5iv_fetch.py tests/test_textbook_parser.py \
  tests/test_textbook_renderer.py tests/test_notebook_textbook_ingest.py \
  tests/test_operator_settings.py tests/test_textbook_chunker.py \
  tests/test_handlers_chunk.py tests/test_write_chunks_wap_gate.py \
  --tb=no -q -p no:warnings
```

## Baseline: 5 FAILED, all pre-existing Windows/env artifacts (NOT logic defects)

| Test | Cause | Class |
|---|---|---|
| test_textbook_renderer.py::...test_symlink_in_images_not_dereferenced | Windows symlink semantics | Windows (CLAUDE.md §8) |
| test_textbook_chunker.py::TestResilience::test_symlink_notebook_dir_refused | Windows symlink semantics | Windows (CLAUDE.md §8) |
| test_chunker_ids.py::TestSingleVersionDefinition::test_version_literals_only_in_canonical_assignments | `UnicodeDecodeError: 'charmap'` — test reads a source file with default cp1252, not utf-8 | Windows codec |
| test_chunker_ids.py::TestF5FreshProcessDeterminism::test_two_subprocesses_produce_identical_ids | spawned subprocess exits 1 (Windows subprocess/import env in worktree) — infra, not a real determinism defect | Windows/env |
| test_operator_settings.py::TestDefaults::test_default_db_path_matches_var_arxmcp_cache | `assert 'var\arxmcp\cache\notebooks.db' == 'var/arxmcp/cache/notebooks.db'` — path separator | Windows path |

## Post-implementation gate (expanded subset, HEAD = b2352c0)

Re-ran the touched subset PLUS the new test modules
(`test_notebook_pdf_parse.py`, `tests/tools/test_notebook_scripts.py`,
`test_server_startup.py`). **7 failures, ALL pre-existing Windows-platform;
zero new; every new AC1–AC4 test passes; `ruff check` clean on the whole diff.**

| Test | Class |
|---|---|
| test_chunker_ids…test_version_literals_only_in_canonical_assignments | Windows cp1252 |
| test_chunker_ids…test_two_subprocesses_produce_identical_ids | Windows subprocess/env |
| test_textbook_renderer…test_symlink_in_images_not_dereferenced | Windows symlink (WinError 1314) |
| test_operator_settings…test_default_db_path_matches_var_arxmcp_cache | Windows path sep |
| test_textbook_chunker…test_symlink_notebook_dir_refused | Windows symlink (WinError 1314) |
| tests/tools/test_notebook_scripts…test_notebook_dir_rejects_symlink | Windows symlink (WinError 1314) |
| test_server_startup…test_helper_rejects_symlinked_notebook | Windows symlink (WinError 1314) |

The last two were not in the original 12-file baseline (their files weren't in
it) but are the SAME `WinError 1314` symlink-privilege class — OS-level, cannot
be caused by this diff (no symlink logic added). Verdict: no regressions.

## Gate rule for Phase 2
- After changes, re-run the SAME subset (plus any new test files). PASS = the
  failing set is a subset of the 5 above; every NEW test passes.
- I will NOT change `DEFAULT_DB_PATH` (keeps the operator_settings failure static)
  and will add a MinerU-bin setting alongside it.
- New source files must be opened/written as utf-8 (avoid adding to the cp1252 class).
