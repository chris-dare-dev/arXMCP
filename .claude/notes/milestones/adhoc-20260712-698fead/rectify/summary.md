# Rectify summary — adhoc-20260712-698fead

Critique of feat `463b870`: **C0 H0 M2 L3** (2 critics: milestone-adversary-critic
+ milestone-arxmcp-critic; both SHIP-WITH-FIXES). Invalidation rate: 0%.

## Fixed (rect `f61cb8b`, test-only)

- **M1 + M2** (MEDIUM, cross-critic agreement) — the reopen regression test
  passes even on pre-fix `del db` under CPython refcounting (locals free at
  return), so it did not deterministically guard the revert. Added
  `tests/test_graph_queries.py::TestCiteNeighborsReopenReleasesLock::test_cite_neighbors_closes_conn_then_db`
  — a spy that monkeypatches `kuzu.Database.close` / `kuzu.Connection.close`
  and asserts `cite_neighbors` closes conn-then-db. **Verified RED on reverted
  `del db`** (`closed == []` ≠ `["conn","db"]`), GREEN on the fix. The reopen
  test is kept as a behavioral / non-refcounting-runtime companion.
- **L1 + L3** (LOW, cross-critic agreement) — converted the last kuzu `del db`
  of the family, the `graph_corpus` fixture at `tests/test_proof_chain.py:116`,
  to the same nested conn-then-db explicit close. Repo-wide, **zero kuzu
  `del db` remain**. The `del db` at `:212` is a LanceDB handle (`lancedb.connect`)
  and was correctly left untouched.

## Deferred

- **L2** (LOW) — the unconditional `db.close()` in the inner `finally` at sites
  1/2 could in principle mask an in-flight exception if `db.close()` itself
  raised. Deferred: this is inherent to the proven `adhoc-20260712-955c958`
  idiom used across all 8 sites; wrapping `db.close()` in try/except for a
  theoretical, low-likelihood close-time error would break idiom consistency.
  Accept-as-is per the finding's own "Acceptable to leave as-is" note.

## Invalidated

- None (0% invalidation rate).

## Regression tests added / changed
- `tests/test_graph_queries.py` — deterministic spy test (M1/M2 guard).
- `tests/test_proof_chain.py` — fixture teardown converted (L1/L3), removing
  the retained-connection leak.

## Verification (this Windows workstation)
- `ruff check .`: clean (whole repo, post-feat).
- Full suite after feat: 3951 passed, 0 failed, 0 errors, 92 skipped.
- After rect: `tests/test_graph_queries.py` + `tests/test_proof_chain.py`
  green (53 passed); new spy test RED↔GREEN verified.
- **POSIX `make test` (the CLAUDE.md §4.1 test authority) is NOT run** — a
  Windows session cannot exercise it; it remains the user's outstanding
  re-verification step (noted in both commit messages).

## Commits
- feat: `463b870` — close kuzu handles at residual del-db sites (5 files, signed)
- rect: `f61cb8b` — close M1,M2,L1,L3 (2 test files, signed)

## Pending external write (Phase 4 boundary — NOT performed by the pipeline)
- `git push origin main` — local `main` is 12 commits ahead of `origin/main`
  (my 2 + 10 from concurrent sessions). Awaiting explicit user authorization.
