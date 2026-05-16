# E14_S01 Research Brief — Axis 2
## Cross-process metric exposure, sentinel-file inventory, design-note 08 metric inventory

**Researcher:** Axis-2 agent
**Date:** 2026-05-15

---

## 1. The cross-process exposure problem

The MCP server is a FastAPI process that lives for the entire
deployment lifetime. Every cron job — drift detector (E10_S04),
delta loop (E11_S02), re-embed (E11_S03), watchdog (E11_S04),
backup (E11_S05) — is a one-shot subprocess that exits after each
run. Prometheus scrapes `GET /metrics` on the server; the cron
processes are already dead.

The two metrics that defer to E14 both document this explicitly:

`server/metrics.py:177-188` (`LATEXML_DRIFT_DETECTED_COUNTER`):
> "Increments inside the cron process … production exposure via the
> server's `/metrics` endpoint is deferred to E14 … v1 operational
> signal is the cron job's non-zero exit + ERROR log + sentinel file
> at `var/arxmcp/ops/drift-detected.flag`."

`server/metrics.py:194-216` (`EVAL_NDCG5_GAUGE`):
> "Set by `ops/watchdog_eval.run_watchdog` in the watchdog's own
> process … Cross-process exposure … is deferred to E14 — same
> posture as `LATEXML_DRIFT_DETECTED_COUNTER` above."
> "the E14 scrape-time hook that rehydrates this gauge from JSON
> reports MUST cap the exposed labels at the N most-recent versions
> to avoid Prometheus high-cardinality drift."

**E14's load-bearing job** is a scrape-time hook in
`server/health.py::refresh_metrics_from_singleton_state` that reads
sentinel files and rehydrates metrics from JSON reports on every
`/metrics` request. The existing pattern is already established:
`refresh_cache_metrics` (`server/metrics.py:242-263`) is called from
the hook and sets `CACHE_BYTES_GAUGE`. The drift/eval bridge is the
same pattern.

The hook must handle four sentinel paths:

| Sentinel | Action in hook |
|---|---|
| `var/arxmcp/ops/drift-detected.flag` | see §5 — Counter vs Gauge |
| `var/arxmcp/ops/eval-reports/corpus_v<N>-*.json` (most recent per version) | set `EVAL_NDCG5_GAUGE.labels(corpus_version=N)` to `ndcg5_mean` |
| `var/arxmcp/ops/backup-status.json` | set a new backup gauge (see §6) |
| `var/arxmcp/ops/delta-timeout.flag` | set a new `DELTA_TIMEOUT_GAUGE` to 1.0 when present, 0.0 when absent |

---

## 2. Sentinel-file inventory across E10/E11

Full inventory from the runbooks, categorized by scrape-hook use:

### Gauge-source (continuous value the hook can `set()`)

| File | Epic | Value for gauge |
|---|---|---|
| `var/arxmcp/ops/eval-reports/corpus_v<N>-<ts>.json` | E11_S04 | `.ndcg5_mean` field per corpus_version |
| `var/arxmcp/ops/eval-quarantine.flag` | E11_S04 | binary 1/0 (flag present = quarantine active) |
| `var/arxmcp/ops/re-embed-state.json` | E11_S03 | `.status` → `in_progress` vs `complete` → 1.0/0.0 |
| `var/arxmcp/ops/oai-pmh-state.json` | E11_S02 | `.last_run_duration_seconds`, `.last_harvest_date` |
| `var/arxmcp/ops/backup-status.json` | E11_S05 | `.finished_at` (epoch), `.status` (success/partial/failed) |
| `var/arxmcp/ops/restore-drill-passed.flag` | E11_S05 | `.restored_at` epoch |

### Counter-source (event occurred; see §5 for monotonicity)

| File | Epic | Increment signal |
|---|---|---|
| `var/arxmcp/ops/drift-detected.flag` | E10_S04 | drift was detected (content is sentinel + fixture count) |

### Informational-only (no useful metric shape)

| File | Epic | Notes |
|---|---|---|
| `var/arxmcp/ops/parser-failures/bulk.jsonl` | E11_S01 | Append-only JSONL — line count is the metric, but scraping a growing file on every /metrics call is too expensive. Expose via a separate counter that the ingest process increments. Defer. |
| `var/arxmcp/ops/parser-failures/delta.jsonl` | E11_S02 | Same — append-only JSONL. Defer. |
| `var/arxmcp/ops/parser-failures/re-embed.jsonl` | E11_S03 | Same. Defer. |

**Recommendation for v1 scope:** expose gauge-source files for
eval-reports, eval-quarantine, backup-status, and the delta-timeout
sentinel. Skip parser-failures files (too expensive to scrape) and
re-embed-state (low operator value vs. complexity added).

---

## 3. Design-note 08 metric inventory vs. the brief

From `.claude/notes/08-security-observability-ops.md` §Metrics:

**Request-level (per-tool):**
```
arxmcp_request_total{tool, status}           counter
arxmcp_request_latency_seconds{tool, quantile}  summary or histogram
arxmcp_request_inflight{tool}                gauge
arxmcp_result_bytes{tool, quantile}          summary
```

**Cache (matches shipped `server/metrics.py`):**
```
arxmcp_cache_lookups_total{layer}            counter  ✓ shipped
arxmcp_cache_hits_total{layer}               counter  ✓ shipped
arxmcp_cache_evictions_total{layer}          counter  ✓ shipped
arxmcp_cache_bytes{layer}                    gauge    ✓ shipped
```

**Embedder/reranker:**
```
arxmcp_embed_calls_total{model, outcome}     counter  — NOT shipped
arxmcp_embed_latency_seconds{model, quantile} summary — NOT shipped
arxmcp_embed_singleflight_dedup_total        counter  ✓ shipped
arxmcp_rerank_calls_total{model, outcome}    counter  — NOT shipped
```
(Note: design note has no `arxmcp_rerank_latency_seconds` but brief
adds it. The note is older; defer to brief for reranker latency.)

**Ingestion (separate process, different endpoint per design note):**
```
arxmcp_ingest_papers_processed_total{parser, outcome}  counter  — NOT shipped
arxmcp_ingest_paper_duration_seconds{parser, quantile} summary  — NOT shipped
arxmcp_ingest_chunks_written_total                     counter  — NOT shipped
arxmcp_ingest_oai_pmh_lag_seconds                      gauge    — NOT shipped
```

**Spend:**
```
arxmcp_api_spend_usd_total{provider, agent_role}  counter  — NOT shipped
```

**What's in the design note but the brief doesn't mention:**

1. `arxmcp_request_latency_seconds`, `arxmcp_request_inflight`,
   `arxmcp_result_bytes` — full per-request observability. Brief only
   names `arxmcp_request_total`. **Should v1 cover?** Yes — these are
   low-effort additions if the `@track_request` decorator shape is
   already being built. Add them.

2. Ingestion process metrics — design note says "same metrics endpoint
   pattern" for a separate process. The server doesn't run ingest; these
   belong in the ingest process binary, not in `server/health.py`.
   **Defer** — out of E14_S01 scope.

3. `arxmcp_api_spend_usd_total` — no hosted-model fallback at v1. Brief
   explicitly defers to E14_S12. **Defer.**

---

## 4. The scrape-time hook contract

`refresh_metrics_from_singleton_state` is called on every `/metrics`
scrape. Prometheus typically polls every 15 seconds; some setups poll
every 5s. The hook must be:

**Cheap:** File `stat()` is O(1). `json.loads` of a small file
(<1 KB) is negligible. The only potentially-expensive operation is
walking `eval-reports/` to find the most-recent file per corpus
version — this should be a `os.scandir()` pass that touches
only filenames, not file content, then opens the single most-recent
file for each version. With nightly deltas, the directory will
contain at most O(365) files after a year; scandir is fast.

**Idempotent:** Gauge `set()` is idempotent. Counter `inc()` is not
(see §5). Every scrape must produce the same gauge values as the
previous scrape when no sentinel has changed.

**Missing-file graceful:** `os.path.exists()` before any open. A
missing sentinel is the NORMAL case before any cron has run. Absence
means: for a gauge, skip `set()` (gauge retains last value); for a
new `DELTA_TIMEOUT_GAUGE`, explicitly `set(0.0)` when the flag is
absent (binary presence/absence is the signal).

**Malformed-JSON graceful:** Wrap every `json.loads` in
`try/except (json.JSONDecodeError, OSError, KeyError)`. On exception:
log at WARNING level with the path; leave the metric at its last value.
Never let a hand-edited file crash `/metrics`.

---

## 5. Counter monotonicity — opinionated recommendation

`LATEXML_DRIFT_DETECTED_COUNTER` is defined as a `Counter`.
The drift-check cron runs daily and writes a sentinel. Each run may
flag 0–N fixtures. The scrape-time hook reads this.

**Option A** (count flagged fixtures, `inc(count - current)`): requires
tracking previous-count state across scrapes (module-level variable).
Race-prone if the sentinel is rewritten mid-scrape. Complex.

**Option B** (convert to Gauge): `LATEXML_DRIFT_DETECTED_GAUGE.set(N)`
where N = number of currently-flagged fixtures. Simpler, semantically
correct ("how many fixtures are drifted right now"), and
`_currently flagged_` is the operator signal anyway (not a cumulative
count). The existing test reset hook (`reset_drift_metrics_for_tests`)
can just call `.set(0)` on the gauge.

**Option C** (timestamp-based dedup): stateful, adds complexity,
fragile under clock adjustments.

**Recommendation: convert `LATEXML_DRIFT_DETECTED_COUNTER` to
`LATEXML_DRIFT_DETECTED_GAUGE` in E14_S01.** The metric was defined as
a Counter because that's how the cron's *own* in-process view works
(each fixture diff is one event). But the scrape-time bridge changes
the semantics: the server reads a sentinel file that reflects the
current state, not a stream of events. A Gauge accurately models
"N fixtures are currently in drift state." The runbook at
`docs/ops/latexml-drift-runbook.md` already frames it as "how many
fixtures have drifted" rather than "how many times drift was detected."

The AC test that references `._value.set(0)` in
`reset_drift_metrics_for_tests` (`server/metrics.py:300-306`) will
need to change to `.set(0)` on the gauge — a minor mechanical update.
Document this breaking change in the milestone's implementation notes.

---

## 6. Backup status gauge — recommendation: add in v1

`var/arxmcp/ops/backup-status.json` (E11_S05) is a small JSON file
written nightly. Its schema (from `docs/ops/backup-restore.md:249-261`)
has `finished_at`, `status` (success/partial/failed), `snapshot_id`.

**Recommend adding two metrics:**

```
arxmcp_backup_last_success_timestamp_seconds  gauge
    # Unix epoch of the last successful backup run.
    # Stays at previous value until next success (Prometheus staleness
    # is 5 minutes; a missed nightly backup becomes visible as
    # `now() - arxmcp_backup_last_success_timestamp_seconds > 86400`).

arxmcp_backup_status{state}  gauge (exclusive, 0/1)
    # Labels: state="success", state="partial", state="failed"
    # Exactly one label is 1.0 at any time. When file is absent: all 0.
```

These are stable Prometheus patterns. The backup-status file is
authoritative; the scrape hook reads it. Cost is one `stat()` + one
`json.loads` per scrape. This is the same cost as the eval-reports
hook. **Do not defer** — `backup-status.json` is already specified by
E11_S05, the metric is trivially derivable, and "last backup was N
hours ago" is an operator dashboard primitive.

---

## 7. Test surface

`tests/eval/test_metrics.py` tests **retrieval-quality metric math**
(nDCG, recall), NOT the Prometheus `/metrics` endpoint. There is no
`tests/test_server_metrics.py` yet; it needs to be created.

**Strategy:** new file `tests/test_server_metrics.py`. Do NOT
modify `tests/eval/test_metrics.py`.

**Test cases to add:**

1. `GET /metrics` returns 200 and `Content-Type: text/plain; version=0.0.4`.
2. `arxmcp_cache_lookups_total`, `arxmcp_cache_hits_total`,
   `arxmcp_cache_evictions_total`, `arxmcp_cache_bytes` all present.
3. `arxmcp_embed_singleflight_dedup_total` present.
4. `arxmcp_corpus_version` present with a float value.
5. Scrape-time hook reads a synthetic eval-report JSON from `tmp_path`
   and sets `arxmcp_eval_ndcg5{corpus_version="42"}` to the report's
   `ndcg5_mean`. The test uses a monkeypatched `ops_dir` fixture.
6. Scrape-time hook reads a synthetic `drift-detected.flag` (a JSON file
   with `fixture_count: 3`) and sets `arxmcp_latexml_drift_detected`
   gauge to 3.0.
7. Missing sentinel files → `/metrics` still returns 200 (no crash).
8. Malformed JSON sentinel file → `/metrics` returns 200 with a warning
   log but the metric is NOT updated (retains previous value).
9. `arxmcp_backup_last_success_timestamp_seconds` reads from
   `backup-status.json` and exposes the `finished_at` epoch.

**Reset hooks:** each test that sets gauge values calls
`reset_eval_metrics_for_tests()` and `reset_drift_metrics_for_tests()`
in its teardown (or uses `autouse=False` per-test reset via a fixture).
The new backup gauge and delta-timeout gauge need similar reset
functions added to `server/metrics.py`.

**Note on `promtool check metrics`:** the brief says
"`promtool check metrics` exits 0." This validates metric
*name format* and exposition syntax, not alerting rules.
A test that shells out to `promtool` is fine as a slow/optional test
(gate it behind an env var like `ARXMCP_RUN_PROMTOOL_CHECK=1`).
Do not make it a mandatory test-suite gate without confirming
`promtool` is available in the CI environment.

---

## 8. `/metrics` endpoint security

From `server/middleware.py::OriginValidationMiddleware`:
> "Requests without an `Origin` header pass through (CLI tools and
> the stdio shim do not set `Origin`; the spec permits this)."

A Prometheus scraper (e.g. `prometheus.io/scrape: "true"`) issues a
plain `GET /metrics` with no `Origin` header. Under
`OriginValidationMiddleware`, this passes through without a 403.
**No code change required.**

However, `HostValidationMiddleware` (`server/middleware.py:378-449`)
DOES check the `Host` header for all paths including `/metrics`, and
accepts `127.0.0.1`, `localhost`, `::1`, and `testserver`. A
Prometheus scraper configured to scrape `http://127.0.0.1:7733/metrics`
sends `Host: 127.0.0.1:7733` which passes the host-validation
check. **No issue.**

Authentication: design note 08 does NOT require auth on `/metrics` for
v1. The server is loopback-only; the only clients are localhost
processes. No change needed.

**Landmine E:** if a Prometheus scraper is configured to scrape via
`localhost` hostname without specifying the port in the `Host` header
(e.g. `Host: localhost`), the middleware accepts it because `localhost`
is in `LOOPBACK_HOST_HEADER_HOSTS`. If the scraper sends
`Host: prometheus.example.com`, it gets 421. This is a configuration
issue, not a code defect — document in the milestone notes.

---

## Landmine Synthesis

**A. Counter vs Gauge for drift detection (critical).**
Convert `LATEXML_DRIFT_DETECTED_COUNTER` to
`LATEXML_DRIFT_DETECTED_GAUGE`. The scrape-time-hook semantic is
"current fixture drift count" — a Gauge. A Counter cannot represent
"three fixtures are drifted; operator fixed two; now one is drifted"
because the Counter can only go up. The existing `reset_drift_metrics_for_tests`
uses the documented `._value.set(0)` private escape hatch; a Gauge
uses the public `.set(0)` API. This is a cleaner break.

**B. EVAL_NDCG5_GAUGE label cardinality.**
With nightly corpus bumps, `corpus_version` grows linearly. The metric
docstring explicitly flags this: "the E14 scrape-time hook… MUST cap
the exposed labels at the N most-recent versions." Recommend N=5 (five
most-recent corpus versions). Rationale: a Prometheus alert on
retrieval drift only needs to compare the current version to the
previous; five gives four historical data points for trend analysis
without unbounded growth.

**C. "Drift watchdog updates arxmcp_retrieval_ndcg5" AC wording.**
The E11_S04 watchdog is a subprocess; it cannot update a gauge in the
running server. The correct description is: "The drift watchdog writes
`var/arxmcp/ops/eval-reports/corpus_v<N>-<ts>.json`; the scrape-time
hook in E14_S01 reads the most-recent report and sets
`arxmcp_eval_ndcg5{corpus_version=N}` to the report's `ndcg5_mean`."
The AC is a design-intent imprecision, not a code defect.

**D. Sentinel-file directory permissions.**
`var/arxmcp/ops/` is written by cron processes (possibly running as
the system `arxmcp` user) and read by the server process. Recommend
mode `0775` on the directory with group `arxmcp` so both service user
and cron user (both in group `arxmcp`) can read and write. The
`docker-compose.yml` in design note 08 has separate users for server
and ingest; a shared group is the correct POSIX primitive. Document in
the implementation runbook.

**E. Origin header on /metrics.**
No issue: `OriginValidationMiddleware` passes requests with no
`Origin` header (the Prometheus scraper case). Document explicitly.

**F. Reset hooks for tests.**
New metrics added in E14_S01 (`DELTA_TIMEOUT_GAUGE`,
`BACKUP_LAST_SUCCESS_GAUGE`, `BACKUP_STATUS_GAUGE`) must each have a
`reset_*_for_tests()` function in `server/metrics.py` following
the existing pattern (`reset_cache_metrics_for_tests`,
`reset_drift_metrics_for_tests`, `reset_eval_metrics_for_tests`).

**G. Backup metrics.**
Include in v1. The sentinel file is already specified; the scrape hook
is cheap. Deferred metrics leave a gap in the operator dashboard that
is easily closed here.

---

## Open Questions

1. **`drift-detected.flag` schema:** the runbook says it's both a
   "sentinel" and contains fixture information. What is the exact JSON
   schema? Is it `{"fixture_count": N, "fixtures": [...]}` or just a
   touch file? The implementation must be defensive — if it's a touch
   file (0 bytes), presence = 1 fixture is not knowable; use 1.0.

2. **`ARXMCP_OPS_DIR` config variable:** should the ops directory path
   be configurable via env var (for tests)? Currently hardcoded to
   `var/arxmcp/ops/`. A config variable like `ARXMCP_OPS_DIR` would
   let tests monkeypatch cleanly without `tmp_path` tricks. Recommend
   adding to `server/config.py`.

3. **`/metrics` sub-app wiring:** `server/health.py` says `/metrics`
   is "mounted as a sub-ASGI app via `prometheus_client.make_asgi_app()`
   from `server/main` rather than registered here as a route." The scrape-
   time hook must be inserted between the ASGI mount and the prometheus
   app. How is it currently wired? Confirm `server/main.py` has a
   thin middleware that calls `refresh_metrics_from_singleton_state`
   before forwarding to the prometheus ASGI sub-app.

4. **Gauge staleness for eval-quarantine:** `eval-quarantine.flag` is
   present when quarantine is active and absent when cleared. The gauge
   should be `set(1.0)` when present and `set(0.0)` when absent. Is a
   Prometheus gauge of 0.0 for "no quarantine" semantically clear
   enough for an alert rule, or should it be a label-valued metric?
   Recommend 0/1 gauge — simpler alert rule (`> 0` fires).

---

## External Writes the Implementation Will Require

1. **`server/metrics.py`:**
   - Convert `LATEXML_DRIFT_DETECTED_COUNTER` → `LATEXML_DRIFT_DETECTED_GAUGE`.
   - Add `EVAL_QUARANTINE_GAUGE`, `DELTA_TIMEOUT_GAUGE`,
     `BACKUP_LAST_SUCCESS_GAUGE`, `BACKUP_STATUS_GAUGE`.
   - Add reset functions for each new gauge.

2. **`server/health.py`:**
   - Add `refresh_sentinel_metrics(ops_dir: Path, resources: Resources)`
     helper called from `refresh_metrics_from_singleton_state`.
   - Implement the four scrape-time reads (drift, eval-reports, backup,
     delta-timeout) with the contracts specified in §4.

3. **`server/config.py`:**
   - Add `ARXMCP_OPS_DIR` env var (default `var/arxmcp/ops`).

4. **`tests/test_server_metrics.py`:**
   - New file with the 9 test cases enumerated in §7.

5. **`tests/eval/test_metrics.py`:**
   - No changes (this file tests retrieval math, not Prometheus).

6. **`docs/ops/latexml-drift-runbook.md`:**
   - Update the metric name from `arxmcp_latexml_drift_detected_total`
     (Counter) to `arxmcp_latexml_drift_detected` (Gauge) and note the
     scrape-time-hook bridge.
