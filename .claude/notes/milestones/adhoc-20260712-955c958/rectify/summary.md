# Rectify summary — adhoc-20260712-955c958

Phase 4 ran INLINE in the main session (deviation from trigger-3 delegation,
justified: 0 CRITICAL/HIGH for a delegate to fix-with-guards; both MEDIUMs
needed main-session actions a rectifier is barred from — a CLAUDE.md
scope-boundary doc edit and a spawn_task tracking action; the Phase-3 critics
already supplied the independent review).

## Findings register: C0 H0 M2 L2

### Fixed
- **M1 (doc drift)** — re-verified real against live `CLAUDE.md:92`: the
  committed 2026-07-12 Windows census listed the 8 kuzu re-open tests as
  GUARDED and "kuzu close-discipline" as an open follow-up, both falsified by
  the feat commit. FIX: reconciled the census — 8 tests moved GUARDED
  (26→18) / skipped (99→91) to passing (3915→3923); the follow-up line
  rewritten to RESOLVED with a pointer to this milestone + the 3 residual
  del db sites. Landed in rect commit `d818582`.
- **M2 (out-of-scope residual, untracked)** — re-verified real: `del db`
  survives at `server/graph_queries.py:379` (live cite_neighbors path),
  `ingest/intra_paper_refs.py:388`, and `ops/restore_drill_check.py`. FIX
  (per both critics: track, do NOT widen the surgical commit): spawned
  follow-up task **task_959b2bf4** covering all 3 sites + a double-call
  cite_neighbors regression test. No code change in this commit.

### Deferred (LOW)
- **L1 (duplication)** — ~27× nested-close block repetition is correct +
  uniform; a `_close_kuzu` helper refactor exceeds the surgical 6-file scope.
  Deferred to a later cleanup.
- **L2 (POSIX residual)** — POSIX `make test` cannot run from this Windows
  session; it is the CLAUDE.md §4.1 authority and the new explicit-close path
  runs on POSIX for the first time. USER ACTION: run `make test` on
  macOS/Linux before pushing.

### Invalidated
- None (0% invalidation — both findings re-verified against live code).

## Regression guards
- `tests/test_graph_ingest.py` + `tests/test_inspire_ingest.py` — the 8
  unskipped close-and-reopen tests are the regression coverage for the core
  fix (they fail on Windows without the production close-discipline change).
  Verified: 76 pass, 0 skipped.

## Rect commit
- `d818582` — `rect(repo): close M1+M2 from adhoc-20260712-955c958`
  (GPG-signed; CLAUDE.md only; Reviewed-by trailers for both critics).

## Pipeline state: rectify-running (NOT "complete")
The required external write `git push origin main` was DEFERRED by the user at
the boundary (they chose to verify POSIX first). The push was NOT performed and
NOT authorized-to-run, so the external-write ledger is intentionally unbalanced
and the milestone is deliberately left at `rectify-running` rather than forced
to a misleading `complete`. Lock released so the pipeline is free.

## Outstanding USER-OWNED actions (in order)
1. Run `make test` (ruff + pytest) on macOS/Linux (POSIX authority, §4.1).
2. If green, `git push origin main` (publishes exactly 2 commits: feat
   6c5ff0d + rect d818582; origin re-fetched and current).
3. Optionally start task_959b2bf4 (the 3 residual del db sites + regression test).
