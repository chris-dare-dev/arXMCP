# E11_S04 Research Brief 2 — Operational surface, threshold validity, integration

**Axis:** Operational surface, threshold-validity, integration with
E11_S02 + E11_S03 pipelines.
**Date:** 2026-05-15  **Status:** Research-running

---

## 1. 5% relative regression threshold — statistical validity

**Bottom line: the 5% threshold is UNUSABLE today and only marginally
sound at 20 queries. Surface this loud to the implementer.**

### Current state (as of code-ship)

`tests/eval/fixtures/queries.json` is an **empty stub** — `"queries": []`.
The fixture is confirmed by reading the live file:

```json
{"schema_version":"1.0","chunker_version":"v1.0",
 "created_at":"2026-05-08","queries":[]}
```

Zero queries. σ_mean is undefined. The AC that reads "watchdog_eval.py
against seed corpus → JSON report with nDCG@5 ≥ 0.80" is **not
verifiable today at all** — not as a skip, not as an XFAIL. The eval
fixture curation is a manual human-curator deliverable (`.claude/docs/
eval-curation.md` §prerequisites); no code can substitute for it.

### At 4 queries (minimum plausible near-term state)

If the fixture reaches 4 queries (the minimum the validator might
accept — the runbook targets 20), σ_mean = 0.15/√4 ≈ 0.075. A 5%
relative regression from 0.80 = 0.04 absolute. Detecting 0.04 with
σ_mean ≈ 0.075 means a signal-to-noise ratio of ~0.53 — far below the
conventional 2σ threshold for a meaningful alert. **False-alarm rate at
this fixture size is unacceptably high.**

### At 20 queries (target fixture state)

σ_mean = 0.15/√20 ≈ 0.034. A 5% regression from 0.80 = 0.04 absolute.
That's ~1.2σ — marginally above noise. False-positive probability
(one-tailed Gaussian) ≈ 12%. In a nightly cron firing ~365 times/year,
expect ~44 false alarms per year at the 5% threshold with 20 queries.

### Recommendations (in priority order)

**Recommendation A (preferred):** Ship with `--threshold-pct` defaulting
to **10%** (not 5%). A 10% regression from 0.80 = 0.08 absolute = 2.4σ
at 20 queries (false-positive rate ≈ 0.8%). The runbook documents the
statistical rationale and lets operators tighten once the fixture grows.
The `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT` env var means operators can
tune without a code change.

**Recommendation B (belt-and-suspenders add-on):** Require 2 consecutive
alerting runs before writing `eval-quarantine.flag`. Halves the false-
alarm rate with no fixture growth needed. Implement as a lightweight
counter in the JSON report's `"consecutive_alerts"` field.

**Do NOT** ship an AC that claims "nDCG@5 ≥ 0.80 verified against seed
corpus" — the fixture is empty and this assertion would be untrue.
See §6 for the recommended conditional-skip test strategy.

---

## 2. Integration with E11_S02 + E11_S03 pipelines

### What E11_S02 left at the boundary

The delta loop (`ingest/oai_delta.py`) writes to
`var/arxmcp/index/lancedb-staging/` and exits. The shell wrapper
`ops/cron/arxmcp-delta.sh` acquires a `flock` on `.delta.lock` and
delegates all arguments through to `oai_delta._cli`. No post-step
hook exists in the wrapper today — it is a clean extension point.

### What E11_S03 left at the boundary

`ingest/re_embed.py` writes an atomic state file:
`var/arxmcp/ops/re-embed-state.json`. The status field walks
`"in_progress"` → `"complete"` | `"complete_with_failures"`. This is
the canonical "re-embed is done" sentinel.

### Integration design (RECOMMENDATION)

**Option A — watchdog as a post-step in `arxmcp-delta.sh`.**

Append after the `exec flock` call:

```bash
exec flock -n "${LOCK_PATH}" bash -c '
    "${UV_BIN}" run python -m ingest.oai_delta "$@"
    "${UV_BIN}" run python -m ops.watchdog_eval
' -- "$@"
```

Advantage: single daily cron entry; watchdog always sees the freshest
staging after a completed delta run.
Disadvantage: delta + re-embed can take 90+ min; adding the watchdog
(~10–30s on seed corpus) is fine, but if re-embed is also in the
chain the cron becomes a multi-hour serial pipeline.

**Option B — separate cron, fires 30 min after the delta timer.**

```
0  2  * * *   ops/cron/arxmcp-delta.sh
30 2  * * *   ops/cron/arxmcp-watchdog.sh    # separate wrapper
```

Disadvantage: the watchdog must poll for the re-embed sentinel; it runs
blind if the delta is still in progress.

**Recommended: Option B for operational clarity**, BUT the watchdog
reads the `re-embed-state.json` sentinel and **refuses to run if
`status != "complete"`**. This avoids false alarms against a partial
staging dataset.

Concretely, `ops/watchdog_eval.py` at startup should:

```python
re_embed_state = json.loads(
    (ops_dir / "re-embed-state.json").read_text()
)
if re_embed_state.get("status") not in ("complete", "complete_with_failures"):
    sys.exit(0)  # staging not ready; skip silently, log INFO
```

The cron timer for the watchdog should be documented in the runbook
with a clear dependency note: "fires 30 min after the delta; requires
re-embed to have completed first."

**There is no `re-embed-progress.json`** in the E11_S03 shipping files —
the state file is `re-embed-state.json`. The implementer should use that
exact path.

---

## 3. Prometheus metric exposure — cross-process problem

Reading `server/metrics.py` (the full file), the established pattern for
cross-process metrics in this codebase is:

> **E10_S04 precedent (LATEXML_DRIFT_DETECTED_COUNTER, lines 163–188):**
> "Production exposure via the server's `/metrics` endpoint is deferred
> to E14. The v1 operational signal is the cron job's non-zero exit +
> ERROR log + sentinel file at `var/arxmcp/ops/drift-detected.flag`."

The E10_S04 team explicitly deferred cross-process metric exposure to E14
and left the counter object in `metrics.py` alive only for the test suite.
The same pattern applies here identically.

**Recommendation: Defer `/metrics` exposure to E14. Do not implement
cross-process metric bridging in E11_S04.**

v1 operational surface:

1. `ops/watchdog_eval.py` writes `var/arxmcp/ops/eval-reports/<version>.json`
   with the nDCG@5 value in a machine-readable field.
2. Add `EVAL_NDCG5_GAUGE` to `server/metrics.py` — object exists, counter
   is live in-process for the test suite, but production `/metrics`
   exposure reads the JSON report file only at E14.
3. AC3 ("metric at /metrics") is marked `@pytest.mark.xfail(reason=
   "cross-process metric exposure deferred to E14")`  — exactly the
   pattern used in E10_S04's AC3.

The drift-counter object and `reset_drift_metrics_for_tests()` in
`metrics.py` are the template. Copy that exact pattern.

---

## 4. Quarantine semantics — what does the watchdog actually guard?

The E11_S02 implementation summary (§scope reminder, point 1) confirms:

> "The active `corpus-version.json` is NOT advanced; activation is E11_S05."

Staging IS quarantine by design. The watchdog therefore doesn't need to
prevent an advance — it only needs to signal to E11_S05's cutover script
that this staging version should NOT be promoted.

**Recommended sentinel:** `var/arxmcp/ops/eval-quarantine.flag`

JSON content (mirrors `delta-timeout.flag` and `drift-detected.flag`):

```json
{
  "corpus_version": 42,
  "ndcg5_baseline": 0.821,
  "ndcg5_current": 0.601,
  "regression_pct": 26.8,
  "threshold_pct": 10.0,
  "consecutive_alerts": 2,
  "flagged_at": "2026-05-15T02:31:04Z",
  "cleared_by": null
}
```

E11_S05's cutover script should check for this file and refuse promotion
if present (`cleared_by` is null). The operator clears it by running:
`python -m ops.watchdog_eval --clear-quarantine` (sets `cleared_by`
to the operator username + timestamp) or by manual deletion.

The `--dry-run` flag must never write or clear this flag — dry-run
computes the metric, prints, and exits 0 regardless of the alert
condition.

---

## 5. Runbook `docs/ops/drift-watchdog.md` — structure prescription

Mirror all four existing ops runbooks. Required section order:

1. **Scope** — what problem this solves; relationship to delta loop and
   cutover (one paragraph, reference E11_S05 explicitly).
2. **Prerequisites** — `re-embed-state.json` must be `status=complete`;
   `var/arxmcp/ops/eval-reports/` directory exists; eval fixture present
   (conditional note: watchdog skips gracefully if fixture is empty).
3. **Integration with the delta loop** — two scheduling options (post-step
   vs separate cron) with explicit recommendation.
4. **Threshold tuning** — document the statistical rationale for 10%
   default; show the σ_mean table at query counts 4/10/20/50; give
   the `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT` override.
5. **What to do when the alert fires** — quarantine flag location,
   clearing procedure, escalation checklist (check staging corpus for
   data quality issues, check embedder version mismatch, check fixture
   staleness).
6. **State file schema** — both `eval-reports/<version>.json` (report)
   and `eval-quarantine.flag` (sentinel) with field-by-field
   description.
7. **Runbook grep test** — at minimum the following strings must appear
   for the test at `tests/test_watchdog_eval.py::TestRunbookContent`:
   - `"10%"` or `"10 percent"` (threshold stated)
   - `"eval-quarantine.flag"` (sentinel named)
   - `"E11_S05"` (cutover dependency called out)
   - `"consecutive"` (multi-run guard described)

---

## 6. Test surface — what is actually verifiable at code-ship?

### AC1: seed corpus → nDCG@5 ≥ 0.80

**NOT verifiable today.** The fixture is empty. Strategy:

```python
@pytest.mark.skipif(
    len(load_fixture()["queries"]) < 20,
    reason="eval fixture has < 20 queries; AC1 requires full curation"
)
def test_ac1_seed_corpus_ndcg5():
    ...
```

This is a conditional skip, not an XFAIL — the fixture WILL eventually
be populated. The test should be in place and skip gracefully.

### AC2: degraded retrieval → exit non-zero

**Fully verifiable at code-ship.** Synthetic: monkeypatch the
`compute_ndcg5` function to return 0.60 with a previous baseline of
0.80 at 10% threshold (regression = 25%). Assert exit code 1 and that
`eval-quarantine.flag` is written. Easy to implement; no corpus needed.

### AC3: metric at /metrics

**XFAIL — cross-process exposure deferred to E14.** Per §3, mark it:

```python
@pytest.mark.xfail(
    reason="cross-process metric exposure deferred to E14 "
           "(see server/metrics.py LATEXML_DRIFT_DETECTED_COUNTER precedent)"
)
def test_ac3_metric_at_metrics_endpoint():
    ...
```

### AC4: runbook content

**Fully verifiable.** Grep tests against the strings listed in §5.

### Additional unit tests (not in the brief ACs but required)

- `test_refuses_if_re_embed_not_complete`: monkeypatch
  `re-embed-state.json` with `"status": "in_progress"`; assert exit 0
  (skip, not error).
- `test_dry_run_no_writes`: dry-run with alerting condition; assert no
  files written, exit 0.
- `test_consecutive_alerts_threshold`: first run doesn't write flag;
  second run with prior_alerts=1 writes the flag (if B-option chosen).
- `test_report_json_schema`: assert report JSON contains all required
  fields.

---

## 7. CLI surface

Mirror `ingest/oai_delta.py::_cli` shape. Flags:

| Flag | Default | Notes |
|---|---|---|
| `--corpus-version=<int>` | Read from `re-embed-state.json` | Must exist; error if not |
| `--lancedb-staging-path=<path>` | `var/arxmcp/index/lancedb-staging/` | Match E11_S01/S02/S03 |
| `--report-dir=<path>` | `var/arxmcp/ops/eval-reports/` | gitignored; created if absent |
| `--threshold-pct=<float>` | `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT` or 10.0 | NOT 5.0 |
| `--fixture-path=<path>` | `tests/eval/fixtures/queries.json` | Allows override for testing |
| `--dry-run` | False | Compute + print; no writes, no flag, exit 0 |
| `--clear-quarantine` | False | Clears the flag; exits immediately |

**No `--resume` flag** — the watchdog is a read-only, short-lived
computation (10–30s). Resume is not meaningful.

The `--lancedb-staging-path` flag is essential: the eval must run against
staging, NOT the active LanceDB (which has the old corpus version).

---

## Open questions

1. **Baseline source.** Where does the watchdog find the previous nDCG@5
   to compare against? Options: (a) read the most recent `eval-reports/
   <N>.json` for the version before staging, (b) hard-code a
   `ARXMCP_EVAL_NDCG5_BASELINE` env var, (c) compare to the Tier-2 gate
   threshold (0.80) as the hard floor rather than a relative comparison.
   Recommend (a) with (c) as a fallback when no prior report exists (first
   run against a newly bootstrapped corpus).

2. **Report file naming.** `eval-reports/<corpus_version>.json` (integer
   version) or `eval-reports/<corpus_version>-<iso8601>.json`? Multiple
   runs against the same corpus version need not produce separate files if
   the content is deterministic, but a timestamp suffix makes debugging
   easier. Recommend `<corpus_version>-<YYYYMMDDTHHMMSS>.json`.

3. **`test_ac1_seed_corpus_ndcg5` skip message.** The skip message should
   tell the operator exactly what to do to un-skip it (run the curation
   runbook at `.claude/docs/eval-curation.md`). Add this URL to the
   `skipif` reason string.

4. **Cron wrapper naming.** Should the watchdog have its own shell wrapper
   `ops/cron/arxmcp-watchdog.sh` (mirrors `arxmcp-delta.sh`) or be
   invoked directly from crontab? Recommend a wrapper for consistency
   and to document the `flock` guard (the watchdog should NOT run
   concurrently with itself).

5. **E11_S05 coupling.** The implementer must confirm with whoever ships
   E11_S05 that the cutover script checks `eval-quarantine.flag` before
   promoting staging → active. This is a cross-milestone contract; write
   it down in the runbook.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| Local file write | `var/arxmcp/ops/eval-reports/<version>-<ts>.json` | Per-run nDCG@5 report |
| Local file write | `var/arxmcp/ops/eval-quarantine.flag` | Alert sentinel for E11_S05 |
| Source file (in-tree) | `ops/watchdog_eval.py` | New module |
| Source file (in-tree) | `ops/cron/arxmcp-watchdog.sh` | Shell wrapper |
| Source file (in-tree) | `server/metrics.py` | Add `EVAL_NDCG5_GAUGE` + `reset_eval_metrics_for_tests()` |
| Source file (in-tree) | `docs/ops/drift-watchdog.md` | Operator runbook |
| Source file (in-tree) | `tests/test_watchdog_eval.py` | Test suite |
| No external writes | — | No push, no PR, no infra mutation, no third-party API |
