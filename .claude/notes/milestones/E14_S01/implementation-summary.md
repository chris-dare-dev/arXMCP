# E14_S01 — implementation summary

## What landed

E14_S01 closes the cross-process `/metrics` exposure deferrals
that were carried forward from E10_S04 (LaTeXML drift), E11_S04
(watchdog nDCG@5), and E11_S05 (backup status). It also wires the
long-deferred request-level / embedder / reranker Prometheus
families that the design constitution (`08-security-observability-ops.md`
§Metrics) names but no module had yet emitted.

## Files changed

| Path | Change | Synthesis ref |
|---|---|---|
| `server/observability/__init__.py` | NEW package | D1 |
| `server/observability/metrics.py` | NEW — `REQUEST_*`, `EMBED_*`, `RERANK_*` families + test-reset helpers | D1, D3, D4 |
| `server/metrics.py` | NEW gauges (`LATEXML_DRIFT_DETECTED_GAUGE`, `EVAL_QUARANTINE_ACTIVE_GAUGE`, `DELTA_TIMEOUT_ACTIVE_GAUGE`, `BACKUP_LAST_SUCCESS_GAUGE`, `BACKUP_STATUS_GAUGE`) + `reset_sentinel_metrics_for_tests`; kept the existing `LATEXML_DRIFT_DETECTED_COUNTER` for the cron's in-process audit path; renamed gauge to `arxmcp_latexml_drift_fixtures` after discovering the Counter name-strip collision | D2, D5 |
| `server/config.py` | NEW `ops_dir: Path = Path("var/arxmcp/ops")` field (overridable via `ARXMCP_OPS_DIR`) so the scrape hook can find the sentinel files cleanly in tests | D8 |
| `server/tools.py` | NEW `_wrap_with_metrics(tool_name, handler)` factory wired in `register_all` — increments `REQUEST_COUNTER`, `REQUEST_INFLIGHT`, `REQUEST_LATENCY`, `RESULT_BYTES` around every handler. `functools.wraps` preserves the signature so FastMCP's input-schema introspection is untouched | D3 |
| `server/query_encoder.py` | `_encode_query_sync` now wraps the BGE-M3 forward pass with `EMBED_CALLS_COUNTER` + `EMBED_LATENCY` (try/finally, outcome label flips ok→error on exception) | D4 |
| `server/retrieval/rerank.py` | `_rerank_sync` wraps the batched cross-encoder forward pass with `RERANK_CALLS_COUNTER` + `RERANK_LATENCY` (same try/finally shape) | D4 |
| `server/health.py` | NEW `refresh_sentinel_metrics(ops_dir)` + `_refresh_eval_ndcg5(reports_dir)`. Called from `refresh_metrics_from_singleton_state` when `resources.config.ops_dir` is set. Implements N=5 most-recent corpus_versions cap with `Gauge.remove(...)` eviction | D5, D6 |
| `tests/test_server_metrics.py` | NEW — 14 tests covering dispatcher wrapper (ok + error + signature preservation), embed counter increment, drift flag (touchfile / JSON body / absent), quarantine + delta-timeout 0/1, backup-status ok→failed exclusivity, eval-ndcg5 latest-report-per-version, label cap (7 versions → 5 kept), and end-to-end `/metrics` exposition parses with `prometheus_client.parser` | D10 |
| `docs/ops/latexml-drift-runbook.md` | Updated to reference the new gauge name + closed the "deferred to E14" callout | D12 |
| `docs/ops/drift-watchdog.md` | Closed the AC3 deferral note (the watchdog → scrape-hook bridge is now wired) | D12 |
| `docs/ops/backup-restore.md` | Added a "Metrics surface (E14_S01)" section with the two new backup gauges + suggested PromQL alert rules | D12 |

## Drift from research synthesis

Three deliberate departures from `research-synthesis.md`, each
documented inline at the change site:

1. **`LATEXML_DRIFT_DETECTED_COUNTER` retained alongside the new gauge.**
   D2 specified "convert Counter → Gauge". After implementing the
   rename, grep revealed `ops/drift_check.py` and 5 tests in
   `tests/test_drift_check.py` import the counter directly for
   the cron's in-process audit purpose. Renaming would have
   forced cascading test edits AND removed a legitimate
   in-process audit signal. Resolution: keep the Counter for the
   cron, add the Gauge for the server's scrape-hook bridge.
   The two metric families have different semantics (Counter:
   "drifts seen since cron-process start, per fixture";
   Gauge: "current count of drifted fixtures, rehydrated from
   the sentinel file"). Both have a place.

2. **Gauge name is `arxmcp_latexml_drift_fixtures`, not
   `arxmcp_latexml_drift_detected`.** `prometheus_client` strips
   the conventional `_total` suffix when registering the time
   series, so the existing Counter's bare name is
   `arxmcp_latexml_drift_detected` — which would collide with
   a Gauge of the same name (raises `ValueError` at import).
   Renaming to `arxmcp_latexml_drift_fixtures` keeps the
   metric-family namespace clear. The runbook update reflects
   the new name.

3. **`EVAL_NDCG5_GAUGE` name not renamed to `arxmcp_retrieval_ndcg5`.**
   Brief 1 (the in-codebase researcher) caught that the
   epic-prose name `arxmcp_retrieval_ndcg5` does not match the
   already-shipped `arxmcp_eval_ndcg5`. Keeping the existing
   name is a one-way door avoided — renaming would break any
   ops dashboard that already references the existing metric.
   The synthesis acknowledged this; D10's AC5 verbiage in the
   actual test (`test_eval_ndcg5_picks_latest_report_per_version`)
   uses the real name.

## Test count delta

* Pre-milestone: 1733 passed, 8 skipped, 1 xfailed (from
  end-of-E11_S05 baseline).
* Post-feat: +14 new tests in `tests/test_server_metrics.py`.
* Post-rect (after F1+F2+F4+F5+F7 regression guards): 1739
  passed, 8 skipped, 1 xfailed — total 20 tests in the new
  metrics test file.
* `ruff check .` — clean.

## What this milestone does NOT cover

* **Tracing.** OTel spans are still future work; this milestone
  is metrics-only per the brief's scope.
* **Cardinality cap on `arxmcp_request_*` tool label.** The tool
  name space is bounded by the registered tool list (7 today),
  so a static N=7 cap is implicit. Adding dynamic enforcement is
  out of scope until the tool surface starts taking external
  string input (it does not today — handler names are static at
  registration).
* **Per-route exemption for `/healthz`/`/readyz`.** Those routes
  do not increment the per-tool counters (they aren't FastMCP
  tools); only the byte-cap exemption in `server/main.py` already
  handles them.

## Metric family inventory after E14_S01

For the operator's reference — the metric names now exposed at
`/metrics`:

* `arxmcp_request_total{tool, status}` — per-tool invocation count
* `arxmcp_request_latency_seconds{tool}` (histogram)
* `arxmcp_request_inflight{tool}` (gauge)
* `arxmcp_result_bytes{tool}` (histogram, ok-path only)
* `arxmcp_embed_calls_total{model, outcome}` — BGE-M3 forward pass count
* `arxmcp_embed_latency_seconds{model}` (histogram)
* `arxmcp_rerank_calls_total{model, outcome}` — BGE-reranker call count
* `arxmcp_rerank_latency_seconds{model}` (histogram)
* `arxmcp_latexml_drift_fixtures` (gauge, sentinel-sourced)
* `arxmcp_eval_ndcg5{corpus_version}` (gauge, capped at 5 labels)
* `arxmcp_eval_quarantine_active` (gauge)
* `arxmcp_delta_timeout_active` (gauge)
* `arxmcp_backup_last_success_timestamp_seconds` (gauge)
* `arxmcp_backup_status{state}` (gauge, exclusive)

Plus the previously-shipped families from `server/health.py` and
`server/metrics.py` (corpus_version, resource_warm, process_start,
embed_singleflight_dedup, cache_*, retrieval_cap_rejections).
