# E11_S04 — Research Synthesis

Merged from [research-brief-1.md](research-brief-1.md) (codebase
mechanics: `score_and_write` import path, LATEXML_DRIFT_DETECTED
precedent, LanceDB staging plumbing) and
[research-brief-2.md](research-brief-2.md) (operations + threshold
validity: σ_mean analysis, sentinel pattern, integration with
re-embed-state.json).

The briefs converge tightly. One important divergence: the
**default threshold**. Brief 2 demonstrates the 5% brief-specified
value is statistically unsound at 20 queries (~1.2σ; ~44 false
alarms/year). Brief 1 cites the brief verbatim. Resolution below.

---

## 1. Headline findings (consensus)

| # | finding | resolution |
|---|---|---|
| 1 | **`score_and_write` from `tests/eval/test_retrieval_quality.py` is pytest-free and directly importable.** The hybrid runner `_run_hybrid_against_corpus` likewise has no pytest dep at function level (only calls `pytest.fail` for fixture-malformed errors). | Import directly; do NOT subprocess to pytest. Replace `pytest.fail` paths with `RuntimeError`. Honor the metrics.py `TODO(E11_S04)` to relocate `tests/eval/metrics.py` → `eval/metrics.py` so production code (`ops/watchdog_eval.py`) does not import from `tests.*`. |
| 2 | **Cross-process /metrics exposure is deferred to E14** (matches `LATEXML_DRIFT_DETECTED_COUNTER` precedent in `server/metrics.py` F8). | v1: watchdog is a one-shot script. `EVAL_NDCG5_GAUGE` lives in `server/metrics.py` but is only test-process-live. Production `/metrics` reads the JSON report at scrape time as a follow-up in E14. AC3 in the brief is marked **deferred-via-XFAIL** to track the gap. |
| 3 | **Quarantine = staging-path discipline + a sentinel flag.** Staging IS quarantine by E11_S02 + E11_S03 design — the active `corpus-version.json` is never advanced by the delta or re-embed loops. The watchdog adds a `eval-quarantine.flag` that E11_S05's cutover script reads to refuse promotion. | Sentinel: `var/arxmcp/ops/eval-quarantine.flag`. Mirrors `delta-timeout.flag` (E11_S02) and `drift-detected.flag` (E10_S04). Cleared via `--clear-quarantine` or manual deletion. |
| 4 | **The 5% brief-specified threshold is statistically unsound.** At 20 queries σ_mean ≈ 0.034 (assuming per-query σ ≈ 0.15); a 5% regression from 0.80 = 0.04 absolute = ~1.2σ. ~12% false-positive rate per run → ~44 false alarms/year. | **Default threshold: 10%** (≈ 2.4σ, ~0.8%/run false-positive rate). The brief's 5% remains the documented OPERATIVE GOAL once the fixture is larger; the env var `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT` lets the operator tighten. Runbook documents the σ table and the rationale. |
| 5 | **Eval fixture is a 0-query stub today** (`tests/eval/fixtures/queries.json` has `"queries": []`). The watchdog must run cleanly against an empty fixture without crashing. | Empty fixture → skip the entire run with INFO log, exit 0. < 10 queries (`MIN_QUERIES_FOR_REGRESSION_CHECK`) → compute the metric (still writes report) but skip the regression alert (sets `regression_vs_prev = null`, `alert_triggered = false`). AC1 ("nDCG@5 ≥ 0.80 against seed") is not verifiable until the fixture is curated — same shape as E11_S01 AC1/E11_S02 AC4 deferrals. |
| 6 | **Watchdog integration: separate cron, dependency on re-embed-state.json.** | Separate cron at 02:30 (delta fires at 02:00). Watchdog reads `var/arxmcp/ops/re-embed-state.json` (NOT a `re-embed-progress.json`); refuses to run if `status != "complete"` and exits 0 silently. |
| 7 | **Watchdog comparison baseline = most-recent prior report** at `var/arxmcp/ops/eval-reports/`. First run has no prior → `regression_vs_prev = null`, `alert_triggered = false`. Stale or unreadable prior → same fallback (corrupt file is not a regression). | Treats `json.JSONDecodeError` and `KeyError` the same as "no prior report". |
| 8 | **`--resume` is not meaningful** — watchdog is short-lived (10–30s on seed corpus). | NO `--resume` flag (closes E11_S01 F3 lesson). |
| 9 | **No tool-schema changes.** No new MCP tools. | `TOOL_SCHEMA_VERSION` stays at 6. No hash repins. |
| 10 | **The "consecutive alerts" suggestion from Brief 2 is deferred.** A two-run guard halves false-alarm rate but adds complexity; defer to ops experience after the fixture is curated. | Synthesis D7. The report JSON carries a `consecutive_alert_count` field that starts at 1 and increments on each alert, but the quarantine flag is written on the first alert. |

---

## 2. Load-bearing quotes

### `tests/eval/test_retrieval_quality.py` — score_and_write is the reusable export

> "The aggregate file is the drift-detection baseline for E11_S04."
> (module docstring at the cold-start matrix)

### `server/metrics.py` — F8 LATEXML_DRIFT_DETECTED_COUNTER precedent

> "Production exposure via the server's `/metrics` endpoint is
> deferred to E14 (observability/ops). The v1 operational signal
> is the cron job's non-zero exit + ERROR log + sentinel file."

### `.claude/TIER-GATES.md` — Tier-5 cutover gate

> "Drift watchdog stable: the latest scheduled nDCG@5 measurement
> (per E11_S04's drift watchdog) is within 5% of the previous
> baseline."

(The TIER-GATES.md uses 5% — synthesis decision D4 ships 10% as
the default; the gate's 5% becomes a long-term aspiration once
the fixture grows past 20 queries. Runbook documents the gap.)

### E11_S03 sentinel path (verified — Brief 1 was wrong)

The E11_S03 state file is at
`var/arxmcp/ops/re-embed-state.json`. There is NO
`re-embed-progress.json` written by the production code path —
that name appears only in the staging-LanceDB sentinel
(`re-embed-progress.json` at
`var/arxmcp/index/lancedb-staging/re-embed-progress.json`). Both
exist; the watchdog reads `re-embed-state.json` for the
operational status.

---

## 3. Divergence + resolution

### Default threshold: 5% (brief) vs 10% (Brief 2 statistical argument)

- Brief 1: keep the brief's 5%.
- Brief 2: statistical analysis shows 5% at 20 queries is ~1.2σ,
  too noisy; recommend 10%.

**Resolution:** Default to **10%**. Rationale:
- A watchdog firing 44 times/year (the 5% false-alarm rate
  estimate) trains operators to dismiss alerts. Loud alerts
  must be rare enough to investigate.
- The 5% gate in `TIER-GATES.md` is a Tier-5 PROMOTION criterion,
  not an alert threshold. The promotion gate runs against a
  larger curated sample; the watchdog runs nightly on whatever's
  curated.
- The env var `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT` lets the
  operator tighten to 5% once the fixture grows past 50 queries.

The runbook documents the σ-vs-threshold table so operators
understand the trade-off.

### Brief 1's `re-embed-progress.json` vs Brief 2's `re-embed-state.json`

Both files exist:
- `var/arxmcp/ops/re-embed-state.json` — operational status
  (`status: in_progress | complete | complete_with_failures`).
- `var/arxmcp/index/lancedb-staging/re-embed-progress.json` —
  staging-side companion (closes E11_S03 F2).

**Watchdog reads `var/arxmcp/ops/re-embed-state.json`** (the
operational state file). Brief 1 was looking at the staging-side
sentinel which is intended for E11_S05's cutover gate.

---

## 4. Design decisions

### D1. Module: `ops/watchdog_eval.py`

Mirror the E10_S04 `ops/drift_check.py` pattern. Public functions:

- `WatchdogReport` dataclass (the JSON-serializable per-run
  artifact).
- `WatchdogSummary` dataclass (the in-memory aggregate).
- `compute_eval_for_staging(...)` — opens staging LanceDB at
  pinned version, runs `_run_hybrid_against_corpus` logic
  in-process, calls `score_and_write` for the per-query rows.
- `find_prior_report(...)` — picks the most-recent JSON report
  with corpus_version < target; handles
  missing/corrupt/older-than-staging edge cases.
- `evaluate_regression(prev_ndcg5, new_ndcg5, threshold_pct)` —
  pure math; returns `(regression_pct, alert_triggered)`. Brief
  formula: `regression_pct = (prev - new) / prev * 100`.
- `_write_quarantine_flag(...)` and `_clear_quarantine_flag(...)`.
- `run_watchdog(...)` — top-level orchestrator.
- `_cli(...)` — argparse + dispatch.

### D2. Reuse `score_and_write` + `tests/eval/metrics.py` — relocate

Move `tests/eval/metrics.py` → `eval/metrics.py` per its own
`TODO(E11_S04)`. Update the existing import in
`tests/eval/test_retrieval_quality.py`. The watchdog imports
`from eval.metrics import ndcg_at_k, recall_at_k`. Production
code does NOT import from `tests.*` anymore.

`score_and_write` stays in `tests/eval/test_retrieval_quality.py`
for now (it has a `tests/` import path of its own, and moving it
out is broader than this milestone). The watchdog imports it via
`from tests.eval.test_retrieval_quality import score_and_write`.
The `tests/eval/__init__.py` makes the import legal; the
`pyproject.toml` already treats `tests/` as a top-level package
for collection. This is acceptable as a transitional state —
production code reading from a `tests/` path is logged as a
**follow-up** in the implementation summary; full
"`tests.eval.test_retrieval_quality` is not import-safe from
production" rectification is a separate milestone.

(If the implementer prefers a cleaner cut: copy
`score_and_write` into `ops/watchdog_eval.py` as a private helper
and avoid the `tests.*` import altogether. Either path is
defensible.)

### D3. Staging-path discipline

The watchdog reads STAGING:
```python
staging_info = read_corpus_version(
    lancedb_path=DEFAULT_LANCEDB_STAGING_PATH
)
tbl = open_chunks_table(
    lancedb_path=DEFAULT_LANCEDB_STAGING_PATH,
    version=staging_info.version,
)
```
The active marker is never touched.

### D4. Default threshold: 10% (NOT the brief's 5%)

Per §3 resolution. Env var:
- `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT` overrides the default.
- Validation at parse time: numeric, `> 0`, `<= 100`. Default
  10.0.

The runbook documents the σ-vs-threshold table and the rationale.

### D5. Quarantine sentinel: `var/arxmcp/ops/eval-quarantine.flag`

JSON content (closes E11_S03's sentinel pattern):

```json
{
  "corpus_version": 42,
  "ndcg5_baseline": 0.821,
  "ndcg5_current": 0.601,
  "regression_pct": 26.8,
  "threshold_pct": 10.0,
  "flagged_at": "2026-05-15T02:31:04Z",
  "report_path": "var/arxmcp/ops/eval-reports/corpus_v42-20260515T023104.json"
}
```

E11_S05's cutover script reads the flag; presence (with no
`cleared_by`-style human override) means refuse promotion. `--clear-quarantine`
deletes the file. `--dry-run` never touches it.

### D6. Watchdog refuses to run if re-embed isn't complete

```python
state = json.loads(
    (REPO_ROOT / "var/arxmcp/ops/re-embed-state.json").read_text()
)
if state.get("status") not in ("complete", "complete_with_failures"):
    logger.info("re_embed status=%s; skipping watchdog", state.get("status"))
    return 0  # silent skip
```

If `re-embed-state.json` is absent, the watchdog still runs (the
staging path can exist without a re-embed having happened — e.g.
the seed corpus is in `lancedb-staging/` for the smoke test).
Only an EXPLICITLY non-complete status causes skip.

### D7. Comparison baseline + first-run handling

`find_prior_report` walks `var/arxmcp/ops/eval-reports/` for
JSON files matching `corpus_v<N>-*.json` with N < staging
version. Picks the highest N. First-ever run: no prior →
`regression_vs_prev=null`, `alert_triggered=false`.

`json.JSONDecodeError` and `KeyError` on the prior report are
caught and treated as "no prior report" — corrupt history is
not a regression signal.

### D8. CLI flags

```
--corpus-version=<int>           # default: from staging marker
--lancedb-staging-path=<path>    # default: var/arxmcp/index/lancedb-staging
--report-dir=<path>              # default: var/arxmcp/ops/eval-reports
--threshold-pct=<float>          # default: env or 10.0
--fixture-path=<path>            # default: tests/eval/fixtures/queries.json
--dry-run                        # compute + print; no writes
--clear-quarantine               # delete the quarantine flag and exit
```

NO `--resume`. NO `--from-corpus-version` (the comparison is
auto-discovered).

### D9. Report file format

`var/arxmcp/ops/eval-reports/corpus_v<N>-<YYYYMMDDTHHMMSS>.json`:

```json
{
  "corpus_version": 42,
  "ndcg5_mean": 0.821,
  "recall10_mean": 0.91,
  "ndcg5_per_query": [{"query_id": "q01", "ndcg5": 0.95}, ...],
  "query_count": 20,
  "regression_vs_prev": -0.04,
  "regression_pct": 5.0,
  "alert_triggered": false,
  "prior_report_path": "var/arxmcp/ops/eval-reports/corpus_v41-...",
  "prior_ndcg5_mean": 0.823,
  "threshold_pct": 10.0,
  "rerank_enabled": false,
  "fixture_path": "tests/eval/fixtures/queries.json",
  "fixture_query_count": 20,
  "timestamp": "2026-05-15T02:31:04Z",
  "underpowered": false
}
```

`underpowered=true` when `query_count < MIN_QUERIES_FOR_REGRESSION_CHECK`
(10). In that case `alert_triggered` is forced to `false` and
`regression_vs_prev = null`.

### D10. Server-side metric: defined but not live-updated

In `server/metrics.py`:

```python
EVAL_NDCG5_GAUGE: Gauge = Gauge(
    "arxmcp_eval_ndcg5",
    "Latest watchdog nDCG@5 measurement per corpus version. "
    "v1: cron-only signal; cross-process /metrics exposure is "
    "deferred to E14 (matches LATEXML_DRIFT_DETECTED_COUNTER "
    "precedent).",
    labelnames=["corpus_version"],
)
```

The gauge object exists; tests can poke it. Production /metrics
exposure is E14's work — same pattern as LATEXML_DRIFT_DETECTED.

### D11. Cron wrapper: `ops/cron/arxmcp-watchdog.sh`

Mirror `ops/cron/arxmcp-delta.sh` (E11_S02). `flock` guard on
`var/arxmcp/ops/.watchdog.lock`. `command -v uv` lookup (E11_S02
IS2 lesson — no hardcoded paths). Operator scheduling: separate
cron at 02:30. Runbook documents both this AND the Option-A
post-step alternative.

### D12. `Makefile` target: `make watchdog`

Mirror `make ingest` / `make delta` / `make re-embed` patterns.
Python version guard. ARGS pass-through with the word-split
warning comment.

### D13. Runbook: `docs/ops/drift-watchdog.md`

Mirror E11_S01–S03 + E10_S04 structure. Required content per
Brief 2 §5:
- Scope + relationship to delta loop + E11_S05.
- Prerequisites (re-embed status, fixture, eval-reports dir).
- Integration: 2 scheduling options + recommendation.
- Threshold tuning with σ table at q=4/10/20/50.
- What-to-do-when-alert-fires.
- State file + sentinel schemas.
- Concurrent-invocations warning (E11_S03 IS2 lesson).
- "No automated scheduling beyond the cron" (E11_S03 IS3 lesson).

### D14. Test surface

Per Brief 2 §6:
- **AC1** (seed → nDCG@5 ≥ 0.80): conditional skip when fixture
  query_count < 20.
- **AC2** (degraded → exit non-zero): synthetic via monkeypatch.
- **AC3** (metric at /metrics): XFAIL pending E14, with the
  pattern matching LATEXML_DRIFT_DETECTED's deferral.
- **AC4** (runbook content): grep tests for "10%",
  "eval-quarantine.flag", "E11_S05".

Plus regression guards:
- `test_refuses_if_re_embed_not_complete` (D6).
- `test_first_run_no_prior_report_no_alert` (D7).
- `test_corrupt_prior_report_treated_as_no_prior` (D7).
- `test_underpowered_fixture_skips_regression_check` (Headline #5).
- `test_dry_run_no_writes` (D5).
- `test_clear_quarantine_flag` (D5).
- `test_threshold_pct_validation` (D4 — non-numeric, ≤0, >100).
- `test_regression_pct_math_one_directional` (Headline #3 — the
  formula).

### D15. No tool-schema changes

`TOOL_SCHEMA_VERSION` stays at 6.

---

## 5. Forced cross-file changes

| File | Change | Why |
|---|---|---|
| `ops/watchdog_eval.py` (NEW) | Core driver + CLI | D1, D3–D10 |
| `ops/cron/arxmcp-watchdog.sh` (NEW) | flock wrapper | D11 |
| `Makefile` (MODIFY) | Add `make watchdog` target with guard | D12 |
| `docs/ops/drift-watchdog.md` (NEW) | Operator runbook | D13 |
| `tests/test_watchdog_eval.py` (NEW) | All ACs + regression guards | D14 |
| `server/metrics.py` (MODIFY) | Add `EVAL_NDCG5_GAUGE` + reset helper | D10 |
| `eval/metrics.py` (NEW) + `tests/eval/metrics.py` (DELETE) | Relocation per `TODO(E11_S04)` | D2 — optional but cleaner |
| `tests/eval/test_retrieval_quality.py` (MODIFY) | Update import after relocation | D2 |

NOT touched: `server/tools.py`, hash-anchored tests,
`ingest/store.py`, `ingest/oai_delta.py`, `ingest/re_embed.py`.

---

## 6. Landmines (consolidated)

1. **Fixture is empty today.** Watchdog must work cleanly with
   `queries: []`; AC1 conditional-skips until curation.
2. **Cross-process /metrics is E14.** Don't claim it works at v1.
3. **`re-embed-state.json` is the canonical status file** (NOT
   `re-embed-progress.json`).
4. **5% is too tight for 20 queries.** Default to 10%.
5. **First-run baseline absence → no alert.** Corrupt prior
   report treated identically.
6. **Staging-path discipline.** Active marker never read.
7. **No `--resume` flag** (E11_S01 F3 lesson).
8. **No `/Users/`-hardcoded paths in the shell wrapper** (E11_S02
   IS2 lesson).
9. **`make watchdog` carries the Python version guard + ARGS
   word-split note** (E11_S01 IS1 / E11_S02 IS1 / E11_S03 IS1
   lessons).
10. **HEREDOC commits, GPG signed, no `--no-verify`.**
11. **`assert` banned for invariants** — use `if ... raise
    RuntimeError`.

---

## 7. AC coverage at code-ship

| Brief AC | Coverage at code-ship |
|---|---|
| AC1: seed → nDCG@5 ≥ 0.80 | Conditional skip when fixture < 20 queries. Test is in place; gates the Tier-5 cutover. |
| AC2: degraded → exit non-zero | Fully verifiable; synthetic monkeypatch test. |
| AC3: metric at /metrics | XFAIL — cross-process exposure deferred to E14 (LATEXML_DRIFT precedent). |
| AC4: runbook 5% + quarantine | Fully verifiable via grep test on runbook content. Note: runbook documents 10% default with 5% as the long-term target. |

---

## 8. External writes required

**None at code-ship.** Operator runtime writes:
- `var/arxmcp/ops/eval-reports/<corpus_v>-<ts>.json` per run
- `var/arxmcp/ops/eval-quarantine.flag` on alert
- (Optional) `EVAL_NDCG5_GAUGE` populated in the in-test
  Prometheus registry.

No pushes, PRs, tickets, infra mutations, third-party API
calls.

---

## 9. Suggested implementation order

1. `eval/metrics.py` relocation (optional but recommended).
2. `server/metrics.py` — add `EVAL_NDCG5_GAUGE` +
   `reset_eval_metrics_for_tests()`.
3. `ops/watchdog_eval.py` — module + CLI.
4. `tests/test_watchdog_eval.py` — all ACs + regression guards.
5. `ops/cron/arxmcp-watchdog.sh` — flock wrapper.
6. `Makefile` — `make watchdog` target.
7. `docs/ops/drift-watchdog.md` — operator runbook.
8. `make test` (full suite); ruff clean; commit.

---

## 10. Done-when checklist

- [ ] All 4 brief ACs covered (AC1 conditional-skip, AC3 XFAIL,
  AC2 + AC4 fully verifiable).
- [ ] Watchdog refuses to run if `re-embed-state.json` reports
  in-progress.
- [ ] First-run + corrupt-prior-report fallback in place.
- [ ] Underpowered-fixture skip path tested.
- [ ] `EVAL_NDCG5_GAUGE` declared with the E14 deferral docstring.
- [ ] `eval-quarantine.flag` sentinel pattern in place.
- [ ] `make watchdog` target with Python version guard.
- [ ] `ops/cron/arxmcp-watchdog.sh` with `command -v uv` lookup +
  `flock`.
- [ ] Runbook covers all sections in §5 of Brief 2.
- [ ] No tool-schema changes.
- [ ] `make test` green; ruff clean.
