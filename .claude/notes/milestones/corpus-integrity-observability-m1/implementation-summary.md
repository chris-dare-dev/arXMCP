# Implementation Summary — corpus-integrity-observability-m1

**One-line:** `corpus-version.json` marker now derives `chunk_count` /
`paper_count` from the COMMITTED LanceDB table (not the in-flight per-paper
`chunks` batch), so the marker is correct after multi-paper runs. Closes task #26.

**Commit range:** `630112407cf79582899f1e859bbda10885c99151..<HEAD>` (this feat commit)

**Implementation path:** INLINE (orchestrator, main session) — 2 files, ~24 LOC
in `ingest/store.py` + 3 regression tests in `tests/test_store.py`. Purely local.

## What landed

`ingest/store.py::write_chunks` marker-write block (~L899–928): replaced

```python
paper_count = len({c.paper_id for c in chunks})
write_corpus_version_marker(..., paper_count=paper_count, chunk_count=len(chunks))
```

with table-derived counts (approach A from the synthesis):

```python
chunk_count = tbl.count_rows()                                   # O(1) Lance fragment metadata
paper_count = len(set(tbl.to_arrow().select(["paper_id"])["paper_id"].to_pylist()))
write_corpus_version_marker(..., paper_count=paper_count, chunk_count=chunk_count)
```

The marker write STAYS inside `write_chunks` (per-call), not moved once-per-run.
`version` is unchanged (`dataset_version = tbl.version`). `WriteStats.chunk_count`
is unchanged (`len(chunks)`, per-batch — scout CAND-8, out of scope).

## Acceptance criteria (synthesis §5)

1. ✅ **Marker counts == live table after a multi-paper run.** `chunk_count ==
   tbl.count_rows()` and `paper_count ==` distinct-`paper_id` count of the
   committed table. Verified by all 3 new tests.
2. ✅ **AC-2 (relaxed per §4): counts reflect cumulative table, not last batch;
   write stays in `write_chunks` (per-call).** Implemented exactly. The roadmap's
   original "marker written once per run" phrasing was REJECTED by both
   researchers (breaks single-call notebook callers — FM-4 CRITICAL; opens a
   crash gap — FM-1; introduces MVCC skew — FM-3). Documented as a deviation
   below.
3. ✅ **Regression test that FAILS on pre-fix code.**
   `TestCorpusVersionMarkerReconciliation::test_marker_reflects_table_after_per_paper_writes`
   does 2 single-paper `write_chunks` calls to one `lancedb_path` and asserts
   `chunk_count == 5` / `paper_count == 2`. Verified to FAIL on pre-fix
   `ingest/store.py` (`AssertionError: assert 2 == 5`) via `git stash` of the
   store.py change with the test retained; PASSES on the fix.
4. ✅ **X-gates: `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED;
   no `CHUNKER_VERSION` bump; suite green.** No server-surface change. The
   schema-hash and BP1-hash tests pass in the full run (not in the failure list).
   `CHUNKER_VERSION` untouched.

## New / changed test paths

- `tests/test_store.py` — new `class TestCorpusVersionMarkerReconciliation` with 3
  tests (first tests in the suite to READ the marker file — closes scout CAND-5a /
  the absent-marker-reader gap):
  - `test_marker_reflects_table_after_per_paper_writes` (the regression — fails
    pre-fix)
  - `test_single_call_multi_paper_marker_correct` (single-call path stays correct)
  - `test_reingest_marker_is_idempotent` (upsert path stays correct)

## Test results

- New tests: 3 passed.
- Pre-fix verification: `test_marker_reflects_table_after_per_paper_writes` fails
  with `assert 2 == 5` on HEAD `ingest/store.py` (the exact production bug shape).
- Full suite: only the 3 known pre-existing ENVIRONMENTAL failures, none touching
  `write_chunks` / the marker:
  - `test_drift_check.py::TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines`
    — `latexmlc` exits -6 (SIGABRT) locally.
  - `test_drift_check.py::TestIntegrationRealLatexmlc::test_render_fixture_does_not_leave_log_artifact`
    — same `latexmlc` binary crash.
  - `test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` — local Kùzu db
    path is a directory (`unavailable` vs `absent`).
- `ruff check ingest/store.py tests/test_store.py` clean.

## Deviation from the brief's design

- **Roadmap m1 said "move `write_corpus_version_marker` out of the per-paper loop
  to once-per-run." This was NOT done — deliberately.** Both researchers
  independently rejected it: it breaks single-call callers (`notebook_textbook_ingest`
  and every test that calls `write_chunks` once — FM-4 CRITICAL), opens a
  mid-run crash gap (FM-1), and introduces an MVCC version-skew window (FM-3).
  The "once per run" phrasing was a *means* (to dodge an O(N²) per-paper scan), not
  the *end*. The end — "marker counts == live table counts after a multi-paper
  run" — is met by keeping the per-call write and reading cumulative table counts.
  The O(N)-per-call distinct-`paper_id` scan is negligible at the seed/notebook
  scale that runs this path today (tens of papers, ≤10K rows); a
  caller-maintained running set is the documented escalation if a 200K-paper bulk
  run (scoped-out E11/E12) ever needs it.

## External writes required

**None** — purely local (`ingest/store.py` + `tests/test_store.py`). No git push,
PR, infra, or third-party API.
