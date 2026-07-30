# Implement synthesis — adhoc-20260712-698fead

Kuzu 0.11.3 close-discipline fix applied to the residual `finally: del db`
sites, matching the proven idiom from `adhoc-20260712-955c958` (commit `6c5ff0d`).

## Built (per acceptance criterion)

- **AC1 — sites 1 & 2 nested close.**
  - `server/graph_queries.py:372-386` (`cite_neighbors`, async): added
    `conn = None` before the try; `finally` now closes conn-then-db, nested.
  - `ingest/intra_paper_refs.py:348-397` (`ingest`): same — `conn = None` +
    nested close.
  - Both had `db = kuzu.Database(...)` unconditionally before the try, so no
    db-guard needed. `grep -nE '^\s*del db\s*$'` on both → empty.
- **AC2 — site 3 Option A** (`ops/restore_drill_check.py:140-166`,
  `smoke_check_kuzu`): pre-init BOTH `db = None` and `conn = None`, kept
  `db = kuzu.Database(...)` INSIDE the existing `try/except`, added a `finally`
  guarding BOTH closes with `is not None`. A `kuzu.Database()` open failure
  still surfaces as `RuntimeError("restored Kùzu DB at ... is unreadable: ...")`
  (not `UnboundLocalError`), so `run_check`'s `except RuntimeError` clean
  exit-code-1 contract is preserved (no behavior change).
- **AC3 — regression test** added:
  `tests/test_graph_queries.py::TestCiteNeighborsReopenReleasesLock::test_second_call_same_path_does_not_lock`
  — two `cite_neighbors` calls against the same `kuzudb_path` back-to-back;
  `pytest.fail(...)` on any RuntimeError from the 2nd call (with the lock
  message included), plus identical-result assertions.
- **AC4 — `tests/test_intra_paper_refs.py`**: all 4 `del db` teardowns
  (fixture + `test_emits_self_edge...` + `test_paper_without_refs...` +
  `test_idempotent_re_run`) converted to nested close.
- **AC5 — in-file fixture**: `tests/test_graph_queries.py`'s own `kuzu_db`
  fixture teardown converted too (required so the new test isolates the close
  path cleanly).

## RED/GREEN honesty check (general-brief Finding 4 — verified this session)

Temporarily reverted site 1 to `del db` and ran the new test standalone AND in
the full `test_graph_queries.py` run on CPython 3.11 / Windows: **it passed both
times on the buggy code.** Root cause: `cite_neighbors` binds `db`/`conn` as
locals with no reference cycle, so CPython refcounting frees them at function
return and the lock is released before the second open. The deterministic lock
failure needs a live `Connection` to outlive the reopen (retained traceback, or
a non-refcounting runtime like PyPy) — which the explicit close prevents
regardless. The test is therefore a **behavioral guard** (reopen contract +
close discipline), NOT a deterministic red/green reproduction of the happy path;
the docstring records this. Fix correctness rests on matching the proven
`955c958` deterministic-close idiom + kuzu's documented close-before-db order.
Fix re-applied and verified identical to the pre-experiment backup.

## Files touched (5)
- `server/graph_queries.py` — site 1 (`cite_neighbors`, live MCP path)
- `ingest/intra_paper_refs.py` — site 2 (`ingest` CLI)
- `ops/restore_drill_check.py` — site 3 (`smoke_check_kuzu`, Option A)
- `tests/test_graph_queries.py` — fixture teardown + new regression test class
- `tests/test_intra_paper_refs.py` — 4 teardowns converted

## Deferred / flagged residuals
- `tests/test_proof_chain.py:116` — the ONE remaining kuzu `del db` (a
  `graph_corpus` fixture). Distinct from the LanceDB `del db` at
  `test_proof_chain.py:205` (false positive, must NOT touch). Out of the literal
  brief; folding it in trips the ≥6-file scope gate. Flagged as a fast-follow.
- `ops/restore_drill_check.py` open/query path has no test coverage; a
  corrupt-dir → RuntimeError test would guard the Option A UnboundLocalError
  risk. Optional; not added (keeps the diff to the brief's scope).
- CLAUDE.md §7 "cite_neighbors is a v1 stub" is stale (it's wired to the live
  MCP tool). Doc-only; out of scope.

## external_writes_required
- `git push origin main` — user-authorized at the Phase 4 boundary; NOT
  performed by the pipeline.

## Test deltas
- +1 test (the regression guard). Full Windows suite: 3951 passed, 0 failed,
  0 errors, 92 skipped (incl. 1 xfailed), pytest exit 0.

## Check gate results
- `ruff check .`: PASS (whole repo)
- `pytest` (full Windows suite): PASS — 3951 passed / 0 failed / 0 errors
- POSIX `make test`: NOT RUN — a Windows session cannot exercise the CLAUDE.md
  §4.1 POSIX test authority; logged as an outstanding residual in the commit.
- git status: only the pre-existing (unrelated) dirty files remain after commit;
  my 5 files are fully committed.
