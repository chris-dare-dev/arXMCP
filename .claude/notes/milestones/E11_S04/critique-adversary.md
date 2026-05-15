# Critique — E11_S04

**Critic:** adversary
**Generated:** 2026-05-15T00:00:00Z
**Commit range:** 94f74d2..5b3bccf
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- The watchdog's "production path" is `_default_compute_eval`, which
  unconditionally raises `NotImplementedError`. `make watchdog`
  against a populated fixture crashes — the runbook never warns
  operators. This is the load-bearing reason for SHIP-WITH-FIXES.
- AC2 is genuinely verified (degraded → exit 1 + sentinel). AC4
  runbook content is verified. AC1 and AC3 are deferred (AC1
  unconditionally skipped, AC3 strict-XFAIL).
- The implementation summary references a `_check_staging_embedder_versions`-
  style mixing guard at L78 of the summary; **the code does not contain
  that guard.** Summary-vs-code drift.
- The watchdog cannot use the existing `tests/eval/aggregate-<N>.json`
  baselines (different filename pattern + different directory), so
  the first watchdog deployment is always "first run, no baseline" —
  prior eval-gate history doesn't seed regression detection.
- AC1 test is `pytest.skipif(True, reason=...)` — unconditional skip,
  not actually fixture-gated. Honest-but-misleading framing as
  "conditional-skip" in the summary.
- Prometheus label cardinality docstring says "tens at most over the
  lifetime of a deployment"; with a nightly delta loop, distinct
  corpus_versions grow at ~1/day → hundreds within a year.
- The runbook is not linked from the root README, repeating the
  E11_S01/S02/S03 F12 pattern — operators discover it only via the
  Makefile comment or this file's See-also.
- Counts: **0 CRITICAL, 2 HIGH, 4 MEDIUM, 4 LOW.** Highest-risk file:
  `ops/watchdog_eval.py:592-615` (NotImplementedError default path).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, shippable-bug | always fix in Phase 4 |
| HIGH | wrong behavior on common path, load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC) |
| LOW | style, naming, micro-perf | defer |

## Findings

### F1 — `_default_compute_eval` raises NotImplementedError; runbook claims `make watchdog` works

- **Severity:** HIGH
- **Source:** adversary
- **File:** `ops/watchdog_eval.py:592-615`
- **What:** The watchdog's production path is `_default_compute_eval`,
  invoked when no `compute_eval` is passed to `run_watchdog`. It
  raises `NotImplementedError` with the message "The default
  compute_eval requires a populated eval fixture and the live BGE-M3
  model. Set ARXMCP_RUN_REAL_BGE_M3=1 and the surrounding model env
  vars per the eval harness, OR inject a stub `compute_eval` for
  testing." The message tells the operator to set an env var — but
  setting the env var changes nothing; the body of the function
  always raises. `docs/ops/drift-watchdog.md` (Step 2) tells the
  operator to run `make watchdog`, which dispatches via `_cli` and
  `run_watchdog` with no `compute_eval` override — i.e. it crashes
  with `NotImplementedError` the moment the empty-fixture skip path
  is bypassed by a populated fixture.
- **Why it matters:** `make watchdog` is the published operator
  entrypoint. The brief's AC1 ("run watchdog_eval.py against seed
  corpus → JSON report with nDCG@5 ≥ 0.80") is *unimplemented*, not
  fixture-gated. The implementation summary frames AC1 as
  "conditional-skip pending fixture curation"; truth is AC1 is
  conditional-skip AND unimplemented-production-path. Operators who
  curate the fixture per `.claude/docs/eval-curation.md` will hit
  this crash with no prior warning in the runbook.
- **Proposed fix:** Either (a) wire `_default_compute_eval` to the
  existing `tests/eval/test_retrieval_quality.py::_run_hybrid_against_corpus`
  helper via a stable seam in `tests/eval/metrics.py` (the seam can
  remain in `tests/` per synthesis D2 — the import is "tests.eval"),
  OR (b) explicitly document in the runbook Prerequisites that
  "`make watchdog` requires the fixture AND an injected `compute_eval`
  until the production wiring lands in a follow-up; AC1 is not
  exercisable via the CLI at v1." Path (a) is the right answer.
- **Regression guard:** Add `tests/test_watchdog_eval.py::test_default_compute_eval_runs_end_to_end`
  marked `requires_model`, that runs `_cli([])` against the seed
  corpus and asserts a JSON report at `var/arxmcp/ops/eval-reports/`.
  Skip until the fixture is curated; **fail** rather than skip when
  `ARXMCP_RUN_REAL_BGE_M3=1` is set.

### F2 — Implementation summary claims a "mixing guard" the code does not have

- **Severity:** HIGH
- **Source:** adversary
- **File:** `.claude/notes/milestones/E11_S04/implementation-summary.md:80`
- **What:** The summary's "Files added / changed → New" bullet for
  `ops/watchdog_eval.py` lists "`_check_staging_embedder_versions`-style
  mixing guard" among the implemented features. `grep -n
  'check_staging\|mixing\|embedder_version' ops/watchdog_eval.py`
  returns no hits. The watchdog reads the staging `corpus-version.json`
  for the integer `version` field only; it does NOT validate that
  the staging dataset's `embedder_version` matches the embedder it
  would use to embed query texts (if it ever does — see F1: it doesn't
  even embed queries yet).
- **Why it matters:** The summary is the single source of truth the
  rectifier and the next milestone (E11_S05) consult. A summary that
  documents non-existent invariants is worse than one that documents
  none — the next milestone trusts the line and proceeds assuming
  the guard exists. Especially load-bearing here because E11_S03's
  partial re-embed explicitly produces mixed-embedder windows; a
  watchdog that doesn't refuse to compare across embedder bumps
  will trip false alerts at every embedder bump.
- **Proposed fix:** Either implement the guard (read
  `staging/corpus-version.json::embedder_version` and refuse to run
  if it differs from the prior baseline report's `embedder_version`)
  or strike the bullet from the summary. The fix takes ~15 LOC plus
  one test; recommend implementing rather than striking, because the
  embedder-bump false-alert scenario is real.
- **Regression guard:** Add `tests/test_watchdog_eval.py::test_embedder_version_mismatch_aborts`
  that writes a staging marker with `embedder_version="bge-m3@bbbbbbbb"`
  and a prior report with `embedder_version="bge-m3@aaaaaaaa"`,
  asserts an explicit refuse-to-compare exit path. (Currently the
  prior-report schema doesn't carry `embedder_version` — add it.)

### F3 — AC1 test is `skipif(True)`, not actually fixture-gated

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_watchdog_eval.py:512-523`
- **What:** `test_ac1_seed_corpus_ndcg5` decorates with
  `@pytest.mark.skipif(True, reason=...)`. The `True` is a literal —
  the test ALWAYS skips, regardless of fixture state. The reason
  string describes a fixture-curation gate, but no fixture check
  exists. Compare to a real fixture-gated skip:
  `@pytest.mark.skipif(_fixture_query_count() < 20, reason=...)`.
- **Why it matters:** When the operator curates the fixture per
  `.claude/docs/eval-curation.md`, this test should automatically
  *de-skip* and run. As written, it requires a human to edit the
  decorator. The summary calls this "conditional-skip"; it's not —
  it's an unconditional skip with a misleading reason string. This
  is exactly the kind of dead test that rots and gets forgotten.
- **Proposed fix:** Replace `True` with a fixture-query-count predicate
  + `requires_model` mark:
  ```python
  @pytest.mark.requires_model
  @pytest.mark.skipif(
      _fixture_query_count(DEFAULT_FIXTURE_PATH) < 20,
      reason="AC1: requires populated 20-query fixture",
  )
  ```
  Then implement the body (which depends on F1 — until
  `_default_compute_eval` works, the test body can't assert
  anything real).
- **Regression guard:** Add a meta-test
  `test_ac1_skip_condition_is_real` that builds a tmp 0-query
  fixture and a tmp 25-query fixture, monkeypatches
  `DEFAULT_FIXTURE_PATH`, and confirms the skip predicate returns
  `True` then `False` respectively. The point is that the skip
  condition is a function, not a literal.

### F4 — Existing eval-gate `aggregate-<N>.json` baselines are ignored

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `ops/watchdog_eval.py:268-315` (`find_prior_report`)
- **What:** `find_prior_report` scans only the watchdog's own
  `report_dir` for files matching `corpus_v<N>-<ts>.json`. The
  existing eval harness (`tests/eval/test_retrieval_quality.py::score_and_write`)
  writes `aggregate-<corpus_version>.json` to a *different* directory.
  The two filename patterns + directories don't overlap.
- **Why it matters:** On the operator's *first* watchdog deployment,
  there's no baseline — the regression check is silently disabled
  for the first nightly run (note: "first run; no regression baseline
  available"). This is correct behavior in isolation, but the
  watchdog could have bootstrapped from the existing harness's
  history. More importantly, the docstring at
  `tests/eval/test_retrieval_quality.py:537-538` claims "The
  aggregate file is the drift-detection baseline that E11_S04's
  watchdog will compare against on a schedule" — that claim is now
  false. Either fix the watchdog to read the aggregate files, or
  fix the comment.
- **Proposed fix:** Add a `find_prior_aggregate_baseline(...)` fallback
  invoked when `find_prior_report(...)` returns `None`. It scans
  `tests/eval/results/aggregate-*.json` (or wherever
  `score_and_write` writes) and treats it as the corpus_version
  baseline. Alternatively, strike the misleading comment in
  `test_retrieval_quality.py:537-538`.
- **Regression guard:** `test_falls_back_to_aggregate_baseline` —
  write only an `aggregate-41.json` (not a watchdog `corpus_v41-...`),
  run watchdog at version 42 with `compute_eval` stub at 0.60,
  assert alert fires.

### F5 — `find_prior_report` swallows `OSError` (too broad)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `ops/watchdog_eval.py:301`
- **What:** The except clause catches `(json.JSONDecodeError, OSError)`
  and treats the file as "no prior report". `OSError` covers:
  `PermissionError`, `FileNotFoundError` (race after `iterdir`),
  `IsADirectoryError`, AND filesystem-level errors like `ENOSPC` on
  read of a partial write. A `PermissionError` is a *configuration*
  problem (operator has the watchdog running under the wrong user,
  e.g. cron under `nobody` vs. a setup that wrote reports as the
  operator user), not a "no prior report" signal.
- **Why it matters:** Silently treating a permissions misconfiguration
  as "first run" means *every* nightly watchdog run discards the
  baseline and shows zero regressions — completely defeats the
  watchdog's purpose. Worse: the operator sees a clean JSON report
  and assumes everything is fine.
- **Proposed fix:** Narrow to `(json.JSONDecodeError, ValueError)`.
  Let `OSError` propagate — if reading the directory failed earlier
  at `iterdir`, that already would have raised. The watchdog can
  legitimately not function without read access to its own report
  directory; that's a setup error, not a runtime skip.
- **Regression guard:** `test_find_prior_report_permission_error_propagates` —
  use `chmod 000` (or `monkeypatch.setattr(Path, "read_text",
  lambda *_: raise PermissionError())`) and assert the watchdog
  raises rather than logging-and-continuing.

### F6 — Prometheus label cardinality docstring claims "tens", reality is hundreds/year

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/metrics.py:200-202`
- **What:** The `EVAL_NDCG5_GAUGE` docstring says "Each label
  cardinality is bounded by the number of distinct corpus_version
  integers the watchdog has run against — tens at most over the
  lifetime of a deployment." With a nightly delta loop bumping
  staging's corpus_version each day (or each batch within a day,
  depending on how E11_S05 cuts over), the label space grows
  linearly with time. Over a year that's ~365; over 3 years
  ~1095. While that's still within prometheus_client safety, it's
  emphatically not "tens".
- **Why it matters:** This becomes load-bearing when E14 wires the
  cross-process exposure. A scrape-time hook that rehydrates the
  gauge has to decide which labels to expose; a docstring claiming
  "tens" pushes the E14 implementer toward an unbounded label set,
  which is the Prometheus high-cardinality anti-pattern.
- **Proposed fix:** Either (a) replace the gauge with a single-valued
  Gauge plus a separate `arxmcp_eval_last_corpus_version` integer
  Gauge (most idiomatic for "the latest measurement" semantics), or
  (b) keep the label but update the docstring to say "bounded by
  the number of corpus_versions the watchdog has measured; the
  scrape-time hook (E14) MUST cap at the N most-recent versions
  via a configurable retention window." Recommend (a).
- **Regression guard:** N/A for docstring; if (a) is adopted,
  `test_gauge_is_unlabeled` checks the metric has no labelnames.

### F7 — Tautological `return 0 if cleared else 0` in `--clear-quarantine`

- **Severity:** LOW
- **Source:** adversary
- **File:** `ops/watchdog_eval.py:694`
- **What:** `return 0 if cleared else 0` is a tautology — both
  branches return 0. The comment "absent is also success" explains
  the intent, but the code form looks like a typo waiting to be
  edited in the wrong direction.
- **Why it matters:** Style + maintainer-confusion. Some operators
  might want exit-1 when the flag wasn't actually cleared (to
  distinguish "I cleared something" from "nothing to clear"). The
  current code commits to "always 0" without saying so.
- **Proposed fix:** `return 0  # absent flag is also success (intentional)`.
- **Regression guard:** N/A (style fix).

### F8 — `--clear-quarantine` ignores `--report-dir` / has no `--quarantine-flag-path`

- **Severity:** LOW
- **Source:** adversary
- **File:** `ops/watchdog_eval.py:679-694`
- **What:** The CLI exposes `--report-dir` and `--lancedb-staging-path`
  but no `--quarantine-flag-path`. `--clear-quarantine` always
  operates on `DEFAULT_QUARANTINE_FLAG_PATH`. An operator running
  the watchdog against a non-default tree (e.g. for an integration
  test) cannot clear that tree's quarantine flag via the CLI.
  Tests work around this with monkeypatch (line 556-559); operators
  cannot.
- **Why it matters:** Consistency between programmatic-test and
  CLI surfaces. Programmatic tests use `quarantine_flag_path=`
  routinely; CLI cannot. A power-operator following the test
  patterns will be surprised.
- **Proposed fix:** Add `--quarantine-flag-path` to the CLI; thread
  through to both `run_watchdog` and `_clear_quarantine_flag`.
  ~5 LOC change.
- **Regression guard:** `test_cli_quarantine_flag_path_override` —
  pass `--quarantine-flag-path=<tmp>`, run `--clear-quarantine`,
  confirm the tmp flag is the one targeted.

### F9 — Runbook not linked from root README (F12 pattern repeats)

- **Severity:** LOW
- **Source:** adversary
- **File:** `README.md` (absence) + `docs/ops/drift-watchdog.md`
- **What:** Per CLAUDE.md §1: "docs/ — ONLY user-facing documentation
  referenced by the root README.md." The drift-watchdog runbook is
  not referenced from `README.md` or `docs/install.md`. This is
  the documented F12 pattern from E11_S01/S02/S03 — runbooks land
  in `docs/ops/` but never get linked.
- **Why it matters:** Doc-layout discipline is load-bearing in this
  repo. A file in `docs/ops/` that no one references should either
  move to `.claude/docs/` (agent-internal) or be linked from the
  README (operator-facing). The current placement claims operator-
  facing while practicing agent-internal.
- **Proposed fix:** Add a "Operations runbooks" section to
  `README.md` linking `docs/ops/bulk-ingest-runbook.md`,
  `docs/ops/delta-loop.md`, `docs/ops/re-embed-runbook.md`,
  `docs/ops/drift-watchdog.md`, `docs/ops/latexml-drift-runbook.md`.
  Address all four E11/E10 milestones in one stroke.
- **Regression guard:** `tests/test_readme_links_runbooks` — assert
  the README text contains the string `docs/ops/drift-watchdog.md`.

### F10 — Re-embed state-file `status` whitelist is open-ended

- **Severity:** LOW
- **Source:** adversary
- **File:** `ops/watchdog_eval.py:242-243`
- **What:** `_re_embed_blocks_run` returns `True` for any status
  value not in `(None, "complete", "complete_with_failures")`.
  If E11_S03's re-embed module ever introduces a new terminal
  status (e.g. `"complete_with_warnings"`, `"aborted_by_operator"`),
  the watchdog will silently skip every nightly run until someone
  updates the whitelist.
- **Why it matters:** Cross-module coupling via stringly-typed
  state. The watchdog can't tell apart "re-embed is in progress"
  from "re-embed used a status string I don't recognize". A safer
  inversion: whitelist the IN-PROGRESS statuses, default to running.
- **Proposed fix:** Invert the predicate:
  `return status in ("in_progress", "starting", "interrupted")`
  (whichever statuses E11_S03 actually emits to mean "still
  running"). Default-to-run is the right risk posture; the cost
  of running against a half-finished staging dataset is one false
  alert, not data corruption.
- **Regression guard:** `test_re_embed_unknown_status_runs` —
  write a state file with `{"status": "novel_status_value"}` and
  assert the watchdog does NOT skip.

## What was done well

- **`evaluate_regression` math is correct and well-tested.** The
  one-directional `(prev - new) / prev * 100` formula, the
  `prev_ndcg5 <= 0` divide-by-zero guard, and the explicit
  "improvements never alert" contract are all covered by
  `TestEvaluateRegression` with four targeted tests.
- **The 10%-vs-5% statistical reasoning is sound and documented.**
  Synthesis D4's σ-table is reproduced in the runbook with a
  defensible threshold-vs-noise-floor table; the operator can see
  why the brief's 5% is aspirational. This is exactly the kind of
  numerate decision that justifies overriding a brief.
- **Atomic JSON writes via tmp+rename in `_write_report` and
  `_write_quarantine_flag`.** No half-written sentinels possible
  even if the cron is killed mid-flush.
- **`flock -n` reentrancy guard in the cron wrapper.** Closes the
  two-watchdogs-on-the-same-LanceDB race documented in the runbook;
  matches E11_S02's pattern.
- **No hardcoded `/Users/` paths in the wrapper.** `command -v uv`
  + `ARXMCP_UV` override — the E11_S02 IS2 lesson is internalized.
- **Empty-fixture / underpowered-fixture / first-run / corrupt-prior
  fallback paths all silently exit 0 with clear log lines** rather
  than fabricating regression signals. The summary's "design
  landmines" §1-§5 are all defensibly handled.
- **`reset_eval_metrics_for_tests` + autouse fixture** matches the
  E10_S04 `reset_drift_metrics_for_tests` pattern; tests cannot
  poison each other's gauge state.
- **`TOOL_SCHEMA_VERSION` untouched at 6.** Watchdog adds nothing
  to the MCP tool surface — BP1 cache discipline preserved per
  `.claude/notes/07-multi-agent-caching.md`. (Cache axis is N/A
  exactly as the brief said it should be.)
- **AC4 runbook content is well-anchored** with the three required
  assertions (env-var name, 10%/5% thresholds, `eval-quarantine.flag`,
  E11_S05 dependency) checked by individual tests rather than one
  giant grep.

## Recommended rectification order

1. **F1** (wire `_default_compute_eval` or document its absence) —
   highest leverage; everything else is moot if the production
   CLI crashes. Implementing the wiring also unblocks F3.
2. **F2** (mixing-guard summary-vs-code drift) — pick a side
   (implement or strike) before the rectifier commit lands so
   E11_S05 reads truth. Implementing is preferred.
3. **F3** (real fixture-gated skip) — depends on F1; once
   `_default_compute_eval` works, the skip predicate can use a
   real fixture-query-count check.
4. **F4** (existing `aggregate-<N>.json` baseline fallback) —
   small standalone fix that unblocks operators with prior eval
   history. Or strike the misleading comment in
   `test_retrieval_quality.py:537-538`.
5. **F5** (narrow the `OSError` catch) — one-line change with a
   regression guard.
6. **F6** (docstring cardinality claim or refactor to unlabeled
   Gauge) — important before E14 reads this doc as the contract.
7. **F10** (invert re-embed status predicate) — one-line risk-
   posture inversion.
8. **F8** (`--quarantine-flag-path` CLI flag) — small consistency
   fix; defer if other findings consume budget.
9. **F9** (link runbook from README) — cleanup that addresses all
   four E10/E11 milestones at once; could be folded into a single
   "docs(repo): link ops runbooks from README" commit.
10. **F7** (tautology cleanup) — pure style; defer.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
