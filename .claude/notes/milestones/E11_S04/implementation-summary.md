# E11_S04 — Implementation Summary

**One-line summary.** Ship `ops/watchdog_eval.py` — a cron-
schedulable drift watchdog that runs the E05 hybrid retrieval
eval against the STAGING LanceDB, compares the nDCG@5 mean
against the most-recent prior eval report, and writes a
`eval-quarantine.flag` sentinel if regression exceeds the
configured threshold. Includes `arxmcp_eval_ndcg5` Prometheus
gauge (in-process at v1; cross-process exposure deferred to
E14), `ops/cron/arxmcp-watchdog.sh` wrapper with `flock`,
`make watchdog` target, and the operator runbook with the
σ-vs-threshold table.

**Commit range.** `94f74d2..HEAD`.

---

## Scope reminder

The synthesis re-shaped the brief along two axes (see
[research-synthesis.md](research-synthesis.md) D1–D15):

1. **Default threshold 10%, not the brief's 5%.** At 20 queries
   σ_mean ≈ 0.034; a 5% regression from 0.80 is ~1.2σ —
   below noise, ~44 false alarms/year. 10% is ~2.4σ at 20
   queries (~3 false alarms/year). The env var
   `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT` lets the operator
   tighten once the fixture grows past 50 queries. The runbook
   documents the σ table.
2. **AC3 (`/metrics` endpoint) is XFAIL-deferred to E14.** The
   watchdog is a one-shot cron process; its in-process
   Prometheus gauge vanishes on exit. Cross-process exposure
   requires E14's scrape-time hook — same posture as
   `LATEXML_DRIFT_DETECTED_COUNTER` (E10_S04 F8).

---

## Acceptance criteria — status

- [ ] **AC1** — seed corpus → nDCG@5 ≥ 0.80.
      **Conditional-skip.** Test exists at
      [tests/test_watchdog_eval.py::test_ac1_seed_corpus_ndcg5](tests/test_watchdog_eval.py)
      but is `pytest.skipif`'d because
      `tests/eval/fixtures/queries.json` is the v1 stub (0
      queries per CLAUDE.md §7). Skip becomes a
      `requires_model`-marked integration test once curation
      lands per `.claude/docs/eval-curation.md`. Same shape as
      E11_S01 AC1 / E11_S02 AC4 deferrals.
- [x] **AC2** — degraded retrieval → exit non-zero +
      quarantine flag. **Verified** by
      [TestRunWatchdog::test_degraded_retrieval_alerts_and_writes_flag](tests/test_watchdog_eval.py):
      synthetic 0.80 → 0.60 baseline → 25% regression at 10%
      threshold → exit 1, flag written with corpus_version +
      regression_pct.
- [ ] **AC3** — `arxmcp_eval_ndcg5{corpus_version="N"}` at
      `/metrics`. **XFAIL — cross-process exposure deferred to
      E14**, per the LATEXML_DRIFT precedent. The in-process
      gauge IS set (verified by
      [TestEvalNdcg5Gauge::test_gauge_populated_after_run](tests/test_watchdog_eval.py));
      production /metrics requires E14's scrape-time hook to
      rehydrate from the JSON report.
- [x] **AC4** — runbook states 5% threshold + quarantine
      procedure. **Verified** by
      [TestRunbookContent](tests/test_watchdog_eval.py) — runbook
      names `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT`, 10% default
      + 5% long-term target, `eval-quarantine.flag`, and
      `E11_S05` cutover dependency.

---

## Files added / changed

### New

- [ops/watchdog_eval.py](ops/watchdog_eval.py) — the watchdog
  driver. `WatchdogReport` dataclass, `evaluate_regression`
  one-directional math, `find_prior_report` lookup with corrupt-
  file tolerance, `_re_embed_blocks_run` E11_S03 integration
  gate, `_check_staging_embedder_versions`-style mixing guard,
  `_write_quarantine_flag` + `_clear_quarantine_flag`,
  `_write_report` atomic JSON, `run_watchdog` orchestrator with
  a `compute_eval` injection seam for tests, `_cli`.
- [ops/cron/arxmcp-watchdog.sh](ops/cron/arxmcp-watchdog.sh) —
  shell wrapper with `flock -n var/arxmcp/ops/.watchdog.lock`
  reentrancy guard + `command -v uv` lookup (E11_S02 IS2
  pattern; no hardcoded `/Users/` path).
- [docs/ops/drift-watchdog.md](docs/ops/drift-watchdog.md) —
  operator runbook. Includes the σ-vs-threshold table,
  scheduling options (separate cron at 02:30 recommended),
  quarantine investigation checklist + clearance procedure,
  E11_S05 cutover dependency, state-file schemas.
- [tests/test_watchdog_eval.py](tests/test_watchdog_eval.py) —
  35 passing tests + 1 conditional-skip (AC1) + 1 XFAIL (AC3
  E14 deferral). Covers all 4 ACs + 12 regression guards
  (regression math, threshold validation, prior-report lookup
  with corrupt-file tolerance, first-run baseline absence,
  underpowered fixture, re-embed gate, dry-run, quarantine
  flag writes/clears, in-process gauge, Makefile + runbook
  content, wrapper hygiene).

### Changed

- [server/metrics.py](server/metrics.py) — added
  `EVAL_NDCG5_GAUGE` (labeled by `corpus_version`) with the
  same "deferred-to-E14" deferral docstring as
  `LATEXML_DRIFT_DETECTED_COUNTER`. Added
  `reset_eval_metrics_for_tests()` mirroring
  `reset_drift_metrics_for_tests()`. Added to `__all__`.
- [Makefile](Makefile) — added `make watchdog` target with
  the Python version guard pattern + `ARGS` word-split warning
  comment (E11_S03 IS1 lesson). `.PHONY` updated.

### Not touched

- `server/tools.py`, `ingest/store.py`, `ingest/oai_delta.py`,
  `ingest/re_embed.py`, hash-anchored tests. No tool surface
  change. `TOOL_SCHEMA_VERSION` stays at 6.
- `tests/eval/metrics.py` was NOT relocated (synthesis D2 noted
  this as optional — minimizing scope). The watchdog imports
  nothing from `tests.eval.*` in its production path because
  it uses a `compute_eval` injection seam.

---

## Test results

```
1620 passed, 8 skipped, 1 xfailed in 80.14s
```

- 8 skipped: 4 `requires_model` + 3 `requires_full_corpus` + 1
  AC1 fixture-gated.
- 1 xfailed: AC3 (cross-process /metrics exposure deferred to
  E14).
- Net delta: **+35 tests** (1585 → 1620).
- `ruff check .` is clean.

---

## Design landmines (record-of-decision)

1. **5% threshold is statistically unsound at 20 queries.**
   Synthesis D4: ship 10% default. Runbook documents the σ
   table.
2. **Empty fixture (v1 state)** → silent skip with INFO log,
   exit 0. The watchdog cannot fabricate a regression signal
   from zero queries.
3. **Underpowered fixture (< 10 queries)** → compute metric
   (for visibility) but suppress the regression alert.
   `regression_vs_prev=null`, `alert_triggered=false`,
   `underpowered=true`.
4. **First-run baseline absence** → no alert. Corrupt prior
   report (`JSONDecodeError`, missing `ndcg5_mean`) treated
   identically — a regression check against garbage is worse
   than no check.
5. **Re-embed in progress** → silent skip. Synthesis D6:
   watchdog reads `var/arxmcp/ops/re-embed-state.json` and
   refuses to run if `status="in_progress"`.
6. **Cross-process /metrics exposure** is E14's work. The
   in-process gauge is set; AC3 is XFAIL.
7. **Quarantine = sentinel flag**, not modifying any LanceDB
   marker. Staging-path discipline (E11_S02 + E11_S03) means
   the active `corpus-version.json` is never advanced; the
   watchdog adds an explicit refuse-to-promote signal for
   E11_S05.
8. **Threshold validation** at parse time: numeric, >0, ≤100.
   Reject pathological values up front.
9. **No `--resume` flag** (E11_S01 F3 lesson — watchdog is
   short-lived, resume is not meaningful).
10. **No hardcoded `/Users/` paths** in the shell wrapper
    (E11_S02 IS2 lesson).
11. **`make watchdog`** carries the Python version guard +
    `ARGS` word-split note (E11_S01 IS1 / E11_S03 IS1
    lessons).
12. **`compute_eval` injection seam** keeps the production
    pipeline live-importable without forcing tests to mock the
    full retrieval stack.

---

## External writes required at code-ship

**None.** Operator runtime writes:
- `var/arxmcp/ops/eval-reports/corpus_v<N>-<ts>.json` per run
- `var/arxmcp/ops/eval-quarantine.flag` on alert
- `var/arxmcp/ops/.watchdog.lock` (flock)

All local; no pushes, PRs, tickets, third-party API calls.

---

## Verification against the synthesis "Done-when" checklist

- [x] All 4 brief ACs covered (AC1 fixture-gated skip; AC3 E14
  XFAIL; AC2 + AC4 fully verified).
- [x] Watchdog refuses to run if `re-embed-state.json` reports
  in-progress.
- [x] First-run + corrupt-prior-report fallback in place.
- [x] Underpowered-fixture skip path tested.
- [x] `EVAL_NDCG5_GAUGE` declared with the E14 deferral
  docstring.
- [x] `eval-quarantine.flag` sentinel pattern in place.
- [x] `make watchdog` target with Python version guard.
- [x] `ops/cron/arxmcp-watchdog.sh` with `command -v uv`
  lookup + `flock`.
- [x] Runbook covers all sections from synthesis Brief 2 §5.
- [x] No tool-schema changes.
- [x] `make test` green; ruff clean.

---

## Open follow-ups (NOT this milestone)

- **E11_S05 cutover.** The cutover script reads the
  `eval-quarantine.flag` to refuse promotion. The contract is
  established by this milestone; the cutover logic itself
  ships in E11_S05.
- **`/metrics` cross-process exposure** for `arxmcp_eval_ndcg5`.
  E14's scrape-time hook reads the most-recent JSON report on
  every scrape and rehydrates the gauge. Pattern identical to
  `LATEXML_DRIFT_DETECTED_COUNTER`.
- **20-query fixture curation.** AC1 is conditional-skipped
  pending the operator's curation per
  `.claude/docs/eval-curation.md`. Once landed, the skip
  becomes a `requires_model` integration test.
- **`tests/eval/metrics.py` → `eval/metrics.py` relocation**
  (synthesis D2). Optional; the watchdog doesn't import from
  `tests.*` today because it uses the injection seam.
- **Multi-run consecutive-alert guard** (Brief 2 §1, Option B).
  Halves false-alarm rate at small fixture sizes. Defer until
  ops experience demonstrates the need.
