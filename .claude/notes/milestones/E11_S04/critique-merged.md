# Critique — E11_S04 (merged)

**Critics:** adversary (Opus) + infra-safety (Sonnet)
**Generated:** 2026-05-15 (orchestrator merge)
**Commit range:** 94f74d2..5b3bccf
**Verdict:** SHIP-WITH-FIXES (both critics)

## Executive summary (orchestrator)

- Combined: **0 CRITICAL, 3 HIGH, 6 MEDIUM, 5 LOW** (14 findings;
  IS5 was self-invalidated by infra-safety on re-read).
- **F1 (HIGH)** — `_default_compute_eval` unconditionally raises
  `NotImplementedError`. `make watchdog` against a populated
  fixture crashes; the runbook never warns. The production CLI
  is non-functional out of the box — the watchdog only works
  with an injected `compute_eval` (test path).
- **F2 (HIGH)** — implementation-summary claims a
  `_check_staging_embedder_versions` mixing guard the code does
  NOT have. Summary-vs-code drift. Either implement the guard
  (~15 LOC, real value: prevents false alerts at embedder bumps)
  or strike the bullet.
- **IS1 (HIGH)** — `flock` is NOT available by default on macOS.
  The cron wrapper assumes it's on PATH; macOS operators see
  `exit 127` with no diagnostic. Same pre-existing gap in
  E11_S02's wrapper (the lesson never landed). Add `command -v
  flock` guard + Prerequisites note in both wrappers + both
  runbooks.
- Cross-critic agreement: **F9 + IS2** — runbook not linked
  from root README. Same drift pattern flagged across
  E11_S01/S02/S03 and never rectified. This rectification will
  fix the unlinked-runbook gap for all 4 E11 + E10 runbooks at
  once.
- AC2 is genuinely verified (degraded → exit 1 + flag). AC4
  runbook content is verified. AC1 is deferred but the test is
  `skipif(True)` — unconditional skip, not fixture-gated (F3).
  AC3 is XFAIL-deferred to E14 (correct posture).
- Prometheus label cardinality docstring claims "tens"; reality
  is hundreds/year (F6). Important to fix before E14 reads the
  docstring as the contract.
- The `evaluate_regression` math is correct; the 10%/5%
  statistical reasoning is sound; the operator-facing runbook
  is the most detailed in the repo. The infrastructure mistakes
  cluster around "production path is unimplemented" and "docs
  don't match code".

## Severity calibration

| level | meaning | rectification action |
|---|---|---|
| CRITICAL | data loss, security regression, broken invariant | always fix in Phase 4 |
| HIGH | wrong behavior on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC) |
| LOW | style, naming, consistency drift | defer |

## Cross-critic agreement

- **F9 (adversary, LOW) + IS2 (infra-safety, MEDIUM)** — runbook
  unlinked from root README. Upgrade to MEDIUM per infra-safety
  severity; the fix addresses all 4 E11 + E10 runbooks at once.

## Findings (full bodies in per-critic files)

See [critique-adversary.md](critique-adversary.md) and
[critique-infra-safety.md](critique-infra-safety.md). Severity
index:

### HIGH (3)
- **F1** — `_default_compute_eval` raises NotImplementedError;
  CLI crashes (`ops/watchdog_eval.py:592-615`).
- **F2** — summary claims mixing guard the code lacks
  (`.claude/notes/milestones/E11_S04/implementation-summary.md:80`).
- **IS1** — `flock` not on macOS PATH; no prerequisite check
  (`ops/cron/arxmcp-watchdog.sh:42` + E11_S02's wrapper).

### MEDIUM (6)
- **F3** — AC1 test is `skipif(True)` — unconditional, not
  fixture-gated (`tests/test_watchdog_eval.py:512-523`).
- **F4** — existing `aggregate-<N>.json` baselines ignored
  (`ops/watchdog_eval.py:268-315`).
- **F5** — `find_prior_report` catches `OSError` too broadly
  (`ops/watchdog_eval.py:301`).
- **F6** — Prometheus label-cardinality docstring claim "tens"
  doesn't match reality (`server/metrics.py:200-202`).
- **IS2** — README unlinks 4 E11 runbooks (cross-critic with F9).
- **IS3** — runbook defers systemd unit creation without
  explaining scope decision (`docs/ops/drift-watchdog.md`).

### LOW (5)
- **F7** — `return 0 if cleared else 0` tautology.
- **F8** — `--clear-quarantine` ignores `--quarantine-flag-path`
  (no such CLI flag).
- **F9** — runbook not linked from README (cross-critic, upgraded
  via IS2).
- **F10** — re-embed status whitelist is open-ended; invert.
- **IS4** — concurrent-invocation warning overstates hazard
  (reads are safe; duplicate alert emission is the real issue).
- **IS5** — INVALIDATED on re-inspection (Makefile `help` IS
  consistent).

## What was done well (merged)

- `evaluate_regression` math is correct and well-tested.
- 10%-vs-5% statistical reasoning is sound and documented.
- Atomic JSON writes via tmp+rename in `_write_report` and
  `_write_quarantine_flag`.
- `flock -n` reentrancy guard (modulo macOS `flock` availability
  per IS1).
- `command -v uv` + `ARXMCP_UV` override — E11_S02 IS2 lesson
  internalized.
- Empty / underpowered / first-run / corrupt-prior fallbacks all
  exit 0 with clear log lines.
- `reset_eval_metrics_for_tests` + autouse fixture; tests
  don't poison each other's gauge state.
- `TOOL_SCHEMA_VERSION` untouched at 6.
- AC4 runbook content anchored by three required assertions, not
  one giant grep.
- The runbook is the most detailed ops document in the repo.

## Recommended rectification order (orchestrator)

1. **F1** (HIGH) — Wire `_default_compute_eval` to the real
   eval pipeline via `tests.eval.test_retrieval_quality.
   _run_hybrid_against_corpus` + `score_and_write`. Document
   "requires_model" gating in the runbook.
2. **F2** (HIGH) — Either implement the mixing guard OR strike
   the bullet from the implementation summary. **Recommend
   implement** (real value: prevents false alerts at embedder
   bumps; ~15 LOC).
3. **IS1** (HIGH) — Add `command -v flock` guard to BOTH
   `ops/cron/arxmcp-watchdog.sh` AND `ops/cron/arxmcp-delta.sh`
   (pre-existing gap). Add Prerequisites note to runbooks.
4. **IS2 + F9** (MEDIUM cross-critic) — Link all 5 ops runbooks
   from root README. One commit closes a 4-milestone drift.
5. **F3** (MEDIUM) — Replace `skipif(True)` with a real
   fixture-query-count predicate.
6. **F4** (MEDIUM) — Add `find_prior_aggregate_baseline()`
   fallback OR strike the misleading comment in
   `test_retrieval_quality.py:537-538`. Picking the simpler:
   add the fallback (small standalone helper).
7. **F5** (MEDIUM) — Narrow `OSError` catch to
   `(JSONDecodeError, ValueError)`.
8. **F6** (MEDIUM) — Refactor `EVAL_NDCG5_GAUGE` to unlabeled +
   add `EVAL_LAST_CORPUS_VERSION_GAUGE` (idiomatic for "latest
   measurement" semantics). Or update docstring to match
   reality.
9. **IS3** (MEDIUM) — Revise runbook's systemd-alternative
   section to explain the scope decision and correct dependency
   chaining direction.
10. **F10** (LOW) — Invert re-embed-status predicate to whitelist
    in-progress states.
11. **F7** (LOW) — Replace tautology with explicit comment.
12. **F8** (LOW) — Add `--quarantine-flag-path` CLI flag.
13. **IS4** (LOW) — Revise concurrent-invocation callout to
    accurately describe duplicate-alert hazard.

## Rectification status (filled by Phase 4)

- **F1** (HIGH) — fixed by wiring `_default_compute_eval` to
  `tests.eval.test_retrieval_quality._run_hybrid_against_corpus`
  via lazy imports (`server.config.Config`, `server.corpus.open_chunks_table`,
  `server.query_encoder.encode_query`). The production CLI now
  runs end-to-end against the real retrieval pipeline when
  `ARXMCP_RUN_REAL_BGE_M3=1` is set. AC1 is unblocked once the
  20-query fixture lands.
- **F2** (HIGH) — fixed by adding
  `_read_staging_embedder_version` + `_check_embedder_version_mixing`
  + persisting `embedder_version` on `WatchdogReport`. The
  watchdog now refuses to compare across embedder bumps (note
  attached to the report; alert suppressed). Regression guards:
  `TestEmbedderVersionMixingGuard::test_embedder_mismatch_suppresses_alert`,
  `test_report_carries_embedder_version`.
- **IS1** (HIGH) — fixed by adding `command -v flock` guards to
  BOTH `ops/cron/arxmcp-watchdog.sh` AND
  `ops/cron/arxmcp-delta.sh` (the pre-existing E11_S02 gap).
  Runbook gained a Prerequisites note pointing macOS operators
  at `brew install flock`. Regression guards:
  `TestShellWrapperFlockGuard::test_watchdog_wrapper_guards_flock`,
  `test_delta_wrapper_guards_flock`.
- **F3** (MEDIUM) — fixed by replacing `pytest.skipif(True, ...)`
  with `pytest.skipif(_fixture_query_count(...) < 20, ...)`.
  AC1 now de-skips automatically once the fixture has ≥20
  queries. Regression guard:
  `test_ac1_skip_condition_is_real`.
- **F4** (MEDIUM) — **deferred** to a follow-up doc commit. The
  watchdog's `find_prior_report` and the harness's
  `score_and_write` write to different directories with
  different filename patterns. Bootstrap-from-aggregate fallback
  adds ~30 LOC and is not load-bearing for code-ship (first-run
  no-baseline behavior is correct; the runbook documents it).
- **F5** (MEDIUM) — fixed by narrowing the catch in
  `find_prior_report` to `json.JSONDecodeError` only. OSError
  now propagates (setup error, not a "no prior report" signal).
  Regression guard:
  `TestFindPriorReportOSError::test_permission_error_propagates`.
- **F6** (MEDIUM) — fixed by updating the
  `EVAL_NDCG5_GAUGE` docstring to accurately describe the
  growth rate (~365 distinct corpus_versions/year with a
  nightly delta loop, not "tens") and to direct E14's
  scrape-time hook to cap the exposed label set.
- **IS2 + F9** (MEDIUM cross-critic) — fixed by replacing the
  README Operations one-runbook reference with a 5-row table
  linking every E10/E11 ops runbook. Regression guard:
  `TestReadmeRunbookLinks::test_all_ops_runbooks_linked`.
- **IS3** (MEDIUM) — fixed by rewriting the drift-watchdog
  runbook's "systemd alternative" section. The new text
  explains the scope decision (watchdog is short-lived; cron
  is sufficient) and documents the correct dependency chaining
  for operators who choose to DIY a systemd unit pair.
  Regression guard:
  `TestRunbookSystemdExplanation::test_explains_scope_decision`.
- **F7** (LOW) — fixed by removing the
  `return 0 if cleared else 0` tautology in `_cli`; the
  no-op call now returns 0 directly with an explicit comment.
- **F8** (LOW) — fixed by adding `--quarantine-flag-path` to
  the CLI; threaded through to both `run_watchdog` and
  `_clear_quarantine_flag`. Regression guard:
  `TestCliQuarantineFlagPath::test_clear_quarantine_with_explicit_path`.
- **F10** (LOW) — fixed by inverting `_re_embed_blocks_run` to
  whitelist known in-progress states
  (`{"in_progress","starting","interrupted"}`). An unknown
  status string now runs the watchdog instead of silently
  skipping. Regression guards:
  `TestReEmbedStateWhitelist::test_unknown_status_runs_anyway`,
  `test_starting_status_skips`.
- **IS4** (LOW) — fixed by rewriting the concurrent-invocations
  callout in the runbook. The new text states that concurrent
  READS are safe (LanceDB MVCC) and that the actual hazard is
  duplicate alert emission, not data corruption. Regression
  guard:
  `TestRunbookConcurrentReadSafe::test_describes_safe_concurrent_reads`.
- **IS5** — invalidated on re-inspection (no action needed).
