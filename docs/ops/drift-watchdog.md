# Drift watchdog runbook (E11_S04)

**Use when:** the nightly delta loop (`make delta`) or a partial
re-embed (`make re-embed`) has written a new staging LanceDB
corpus version, and the operator wants automated retrieval-
quality regression detection before promoting that staging
dataset to active via the E11_S05 cutover.

> **Staging-path discipline.** The watchdog reads the staging
> LanceDB at `var/arxmcp/index/lancedb-staging/`. The active
> `corpus-version.json` is NEVER touched. Staging IS quarantine;
> the watchdog's sentinel file
> `var/arxmcp/ops/eval-quarantine.flag` is the signal E11_S05's
> cutover script reads to refuse promotion.

> **No automated scheduling beyond the cron.** The watchdog is
> human-initiated OR cron-scheduled (per §"Scheduling" below).
> There is no daemon process; the gauge metric is in-process
> only and dies when the watchdog exits.

> **`/metrics` exposure deferred to E14.** The `arxmcp_eval_ndcg5`
> Prometheus gauge is defined in `server/metrics.py` but is only
> populated in the watchdog's own process. Cross-process
> exposure (so the running MCP server can serve the gauge at
> `/metrics`) is E14's work — matches the
> `LATEXML_DRIFT_DETECTED_COUNTER` precedent.

---

## What the watchdog does

1. Reads `var/arxmcp/ops/re-embed-state.json` (if present). If
   `status="in_progress"`, the watchdog **skips silently and exits 0**.
   This avoids running against a half-finished staging dataset.
2. Reads the staging `corpus-version.json` to determine the
   target `corpus_version` integer.
3. Loads `tests/eval/fixtures/queries.json` (the hand-labeled
   eval fixture).
4. Runs the E07 hybrid retrieval pipeline (BM25 + ANN + RRF, with
   the reranker if `ARXMCP_ENABLE_RERANK=true`) for every query.
5. Computes nDCG@5 per query and the mean across queries.
6. Searches `var/arxmcp/ops/eval-reports/` for the most-recent
   prior report with `corpus_version < target`.
7. Computes the one-directional relative regression:
   `regression_pct = (prev_ndcg5 - new_ndcg5) / prev_ndcg5 * 100`.
   An IMPROVEMENT never alerts.
8. If `regression_pct > threshold_pct`, writes
   `var/arxmcp/ops/eval-quarantine.flag` and exits 1.
9. Always writes a JSON report at
   `var/arxmcp/ops/eval-reports/corpus_v<N>-<ts>.json`.

---

## Threshold tuning

**Default: 10% relative regression.** The brief targets 5% as a
long-term goal; the watchdog ships at 10% because 5% is below the
noise floor at small fixture sizes.

The override env var is `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT`
(or the `--threshold-pct` CLI flag).

### Statistical rationale

Per-query nDCG@5 in this corpus has rough σ ≈ 0.15 (typical for
retrieval evaluation). The standard deviation of the mean at N
queries is σ_mean = σ / √N. A 5% regression from a baseline of
0.80 is **0.04 absolute** — compare to:

| Fixture size N | σ_mean (approx) | Z-score for 5% drop | False-positive rate per run |
|---|---|---|---|
| 4 | 0.075 | 0.53 | 30% |
| 10 | 0.047 | 0.85 | 20% |
| 20 | 0.034 | 1.18 | 12% |
| 50 | 0.021 | 1.89 | 3% |

At 20 queries, the 5% threshold fires ~44 times/year (in a nightly
cron). A 10% threshold at 20 queries fires ~3 times/year — within
the operator's investigative budget.

**Tighten to 5% only after the fixture exceeds 50 queries.**

### Fixture-size policy

The watchdog handles small fixtures gracefully:

* **0 queries** — the watchdog skips the entire run with an INFO
  log and exits 0.
* **< 10 queries** — the watchdog computes the metric (for
  visibility in the JSON report) but skips the regression alert.
  `regression_vs_prev=null`, `alert_triggered=false`,
  `underpowered=true`.
* **≥ 10 queries** — full regression check.

The fixture currently has 0 queries (per CLAUDE.md §7). Run the
curation workflow at
[.claude/docs/eval-curation.md](../../.claude/docs/eval-curation.md)
to populate it before the watchdog can produce a meaningful
signal.

---

## Prerequisites

* **The staging LanceDB must exist** with a valid
  `corpus-version.json` at `var/arxmcp/index/lancedb-staging/`
  (created by `make ingest` / `make delta` / `make re-embed`).
* **`var/arxmcp/ops/re-embed-state.json` is either absent
  or `status="complete"`.** A `status="in_progress"` state file
  causes the watchdog to skip.
* **`uv`** on `PATH` (the cron wrapper resolves it via
  `command -v uv`; `ARXMCP_UV` overrides).
* **The eval fixture** at `tests/eval/fixtures/queries.json`
  should be populated. An empty fixture causes a silent skip.
* **`ARXMCP_RUN_REAL_BGE_M3=1`** if running the full retrieval
  pipeline with the real BGE-M3 model.

> **Concurrent invocations.** The cron wrapper's
> `flock -n var/arxmcp/ops/.watchdog.lock` prevents duplicate
> runs on the same host. Two hosts sharing the same staging
> LanceDB are **safe from a data perspective** (LanceDB MVCC
> supports concurrent reads; the watchdog never writes to the
> LanceDB), but both instances will independently emit alert
> reports and quarantine flags for the same corpus version. For
> operational clarity, prefer a single watchdog host.

> **`flock(1)` is util-linux.** It is NOT included on macOS by
> default — install with `brew install flock` (or
> `brew install util-linux`) before enabling the cron entry. The
> wrapper checks `command -v flock` and exits 1 with an
> actionable error if it's missing.

---

## Procedure

### Step 1 — Dry-run to inspect the metric without writes

```bash
make watchdog ARGS="--dry-run"
```

Prints the JSON report to stdout; writes no files, never sets
the quarantine flag. Use this to inspect a metric reading without
committing it to the historical record.

### Step 2 — Real run

```bash
make watchdog
```

On success (no regression beyond threshold): exit 0; a JSON
report is appended to `var/arxmcp/ops/eval-reports/`.

On regression: exit 1; the report is written AND
`var/arxmcp/ops/eval-quarantine.flag` is written. The cron mailer
or systemd `OnFailure=` picks up the non-zero exit.

### Step 3 — When an alert fires

The quarantine flag at `var/arxmcp/ops/eval-quarantine.flag` is a
JSON file with the offending corpus version + regression metric:

```json
{
  "corpus_version": 42,
  "ndcg5_baseline": 0.821,
  "ndcg5_current": 0.601,
  "regression_pct": 26.8,
  "threshold_pct": 10.0,
  "flagged_at": "2026-05-15T02:31:04Z",
  "report_path": "var/arxmcp/ops/eval-reports/corpus_v42-...json"
}
```

Investigation checklist:

1. **Open the report** at `report_path`. Look at `ndcg5_per_query`
   for outliers — is one query catastrophically wrong, or is
   the regression evenly spread?
2. **Check the staging corpus** for data-quality issues — partial
   ingest, parser regression, embedder version mismatch.
3. **Check the fixture freshness** — did the latest chunker bump
   change the `chunk_id`s that the fixture expects?
4. **Compare against a clean baseline** — re-run the watchdog
   against a prior known-good staging snapshot.

### Step 4 — Clearing the quarantine flag

After investigation, clear the flag manually:

```bash
make watchdog ARGS="--clear-quarantine"
```

(Or `rm var/arxmcp/ops/eval-quarantine.flag` directly.)

**The quarantine flag is the only thing standing between the
operator and E11_S05's cutover.** Once it's cleared, the cutover
script will permit promoting the staging dataset.

---

## Scheduling

Two options. **Option B (separate cron) is recommended** for
operational clarity.

### Option A — Post-step in `arxmcp-delta.sh`

Append the watchdog call after the delta loop completes. The
cron entry stays a single line; the watchdog runs immediately
after a successful delta.

### Option B — Separate cron at 02:30 (recommended)

```
# crontab
0  2 * * *  /path/to/arxmcp/ops/cron/arxmcp-delta.sh
30 2 * * *  /path/to/arxmcp/ops/cron/arxmcp-watchdog.sh
```

The watchdog reads `re-embed-state.json` and skips if re-embed is
still in progress. A 30-minute gap is typically enough for the
seed-corpus delta + re-embed; tune for the full corpus.

### systemd alternative (not shipped — scope decision)

The repo deliberately ships only the cron wrapper for the
watchdog. Unlike the delta loop (E11_S02), which runs as an
`OnCalendar=` timer service with hardened containment, the
watchdog is short-lived (~30s) and human-initiated OR cron-
invoked. Adding a full `.service` + `.timer` pair would
duplicate the E11_S02 unit shape with no operational benefit
beyond the systemd journal integration already provided by
cron + mailer.

If you prefer systemd anyway, mirror
`ops/systemd/arxmcp-delta.{service,timer}` but chain the timer
correctly:

- `After=arxmcp-delta.service` (watchdog runs AFTER delta, not
  concurrent).
- `Wants=arxmcp-delta.service` on the watchdog **TIMER unit
  only**, NOT the service unit itself. Putting `Wants=` on the
  service can deadlock under failure.

---

## E11_S05 cutover dependency

The E11_S05 cutover script (when shipped) MUST check
`var/arxmcp/ops/eval-quarantine.flag` before promoting
`lancedb-staging/` → active `lancedb/`. The flag's presence
means refuse promotion. This is the contract this milestone
establishes.

The flag is durable across process restarts. The cutover script
must NOT clear it; only the operator clears it.

---

## State file schemas

### `var/arxmcp/ops/eval-reports/corpus_v<N>-<ts>.json`

```json
{
  "alert_triggered": false,
  "corpus_version": 42,
  "fixture_path": "tests/eval/fixtures/queries.json",
  "fixture_query_count": 20,
  "ndcg5_mean": 0.82,
  "ndcg5_per_query": [{"query_id": "q01", "ndcg5": 0.95}, ...],
  "notes": [],
  "prior_ndcg5_mean": 0.81,
  "prior_report_path": "var/arxmcp/ops/eval-reports/corpus_v41-...",
  "query_count": 20,
  "recall10_mean": 0.74,
  "regression_pct": -1.23,
  "regression_vs_prev": 0.01,
  "rerank_enabled": false,
  "threshold_pct": 10.0,
  "timestamp": "2026-05-15T02:31:04Z",
  "underpowered": false
}
```

### `var/arxmcp/ops/eval-quarantine.flag`

(Shown above in §Step 3.)

---

## Failure modes

### Staging LanceDB missing

The watchdog raises `RuntimeError` with a clear message pointing
at `make ingest` / `make delta`. Exit non-zero.

### Eval fixture missing or malformed JSON

Watchdog raises with a pointer to
`.claude/docs/eval-curation.md`. A corrupt fixture is a setup
error, not a runtime skip.

### Prior report corrupt or unreadable

Watchdog logs a WARNING and treats this run as the first run
(no baseline). No alert. The new report is written and becomes
the next run's baseline.

### Re-embed in progress

Watchdog skips silently (exit 0). Operator should run the
watchdog after `make re-embed` completes.

---

## See also

* [ops/watchdog_eval.py](../../ops/watchdog_eval.py) — the driver module.
* [ops/cron/arxmcp-watchdog.sh](../../ops/cron/arxmcp-watchdog.sh) — cron wrapper with flock.
* [docs/ops/delta-loop.md](delta-loop.md) — the nightly delta (E11_S02).
* [docs/ops/re-embed-runbook.md](re-embed-runbook.md) — partial re-embed (E11_S03).
* [.claude/docs/eval-curation.md](../../.claude/docs/eval-curation.md) — fixture curation workflow.
* [.claude/docs/retrieval-quality-report.md](../../.claude/docs/retrieval-quality-report.md) — preliminary nDCG@5 numbers.
* [.claude/TIER-GATES.md](../../.claude/TIER-GATES.md) — Tier-5 cutover gate; the watchdog is the operative trigger.
* [.claude/notes/milestones/E11_S04/research-synthesis.md](../../.claude/notes/milestones/E11_S04/research-synthesis.md) — design rationale + D1-D15.
