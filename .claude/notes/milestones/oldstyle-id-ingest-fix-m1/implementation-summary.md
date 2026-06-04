# Implementation Summary — oldstyle-id-ingest-fix-m1

**One-line:** Fix old-style arXiv id (`math/0212237`) ingest — create the
embedded `<subject>/` cache subdir, and stop an old-style id from aborting
the whole notebook batch — plus three regression tests.

**Path:** inline (orchestrator, main session). 2 production files + 2 test
files; ~30 LOC including tests. No novel architecture, no specialist domain.

**Commit range:** `<feat-base>..<feat-head>` (recorded in state.json after commit)

## Production changes (already in working tree from the bug-fix session)

- `ingest/ar5iv_fetch.py::try_cache()` — `cache_dir.mkdir(...)` →
  `cache_path.parent.mkdir(...)`. Old-style ids embed a `/`, so
  `cache_path = cache_dir / f"{paper_id}.html"` resolves to
  `cache_dir/math/0212237.html`; the `math/` subdir is `cache_path.parent`,
  which the old code never created → `FileNotFoundError` on
  `cache_path.write_text(...)` on a fresh tree. New-style ids unaffected
  (`cache_path.parent == cache_dir`). Sibling `parsed_paper_dir.mkdir(...)`
  was already correct.
- `tools/notebook_fetch.py::run()` — wrapped
  `fetch_raw_tex_if_missing(paper_id, CORPUS_RAW_DIR)` in `try/except
  ValueError → recovered = False`. The chain `fetch_raw_tex_if_missing →
  fetch_eprint → validate_paper_id` raises `ValueError` on old-style ids by
  design (new-style-only regex), and that exception is NOT in
  `fetch_raw_tex_if_missing`'s documented envelope, so it escaped and
  aborted the entire batch with a traceback. Degrades to `raw_tex_missing`,
  which the module docstring defines as covering "all non-OK raw-tex
  outcomes." `validate_paper_id` itself is deliberately left unchanged
  (same decision as E09_S02 F2).

## Acceptance criteria status

- [x] Regression test: old-style id writes cache + parsed files into a
  nested subject subdir — `tests/test_ar5iv_fetch.py::TestOldStyleId::test_old_style_id_creates_subject_subdir`.
  Verified to FAIL on pre-fix code (FileNotFoundError).
- [x] Regression test: old-style id in a `papers.txt` batch does not abort
  the run and is counted as `raw_tex_missing` —
  `tests/test_notebook_fetch.py::TestNotebookFetchRun::test_old_style_id_does_not_abort_run`.
  Verified to FAIL on pre-fix code (unhandled ValueError escapes `run()`).
- [x] Bonus guard: on-disk cache short-circuit works through the subject
  subdir — `tests/test_ar5iv_fetch.py::TestOldStyleId::test_old_style_id_local_cache_hit`.
- [x] `ruff check .` clean.
- [x] Full pytest suite: failure SET byte-identical to clean `main`
  (69 pre-existing Windows-platform failures on this workstation; 0 added,
  0 removed by this change). My new tests pass. macOS/Linux reference
  platform unaffected (change uses a `/` subdir, never a `:`).

## New / changed test paths

- `tests/test_ar5iv_fetch.py` (added `TestOldStyleId`, 2 tests)
- `tests/test_notebook_fetch.py` (new file, 1 test)

## External writes required

None — purely local. (`git push` remains a separate per-event user
authorization at the Phase 4 boundary.)

## Deviations from the brief

None. The brief's recommendation was followed: mock at the
`fetch_raw_tex_if_missing` boundary; `raw_tex_missing` is the correct
bucket; no `validate_paper_id` change.
