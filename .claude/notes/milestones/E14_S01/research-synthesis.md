# E14_S01 — Research Synthesis

Merged from [research-brief-1.md](research-brief-1.md) (in-codebase
metric inventory + tool instrumentation) and
[research-brief-2.md](research-brief-2.md) (cross-process exposure
via sentinel files + design-note 08 metric inventory).

The briefs converge on the architecture and disagree on only one
substantive point: whether to convert
`LATEXML_DRIFT_DETECTED_COUNTER` to a gauge. Brief 2 has the
stronger argument; resolution below.

---

## 1. Headline findings (consensus)

| # | finding | resolution |
|---|---|---|
| 1 | **The `/metrics` HTTP handler is already wired.** `server/main.py:413-423` mounts `make_asgi_app()` with a scrape-time refresh wrapper. **This milestone does NOT need to create an endpoint — it needs to populate metric families + add cross-process refresh hooks.** | Build on the existing `refresh_metrics_from_singleton_state` pattern. |
| 2 | **Cache metrics are 80% done; request/embed/rerank counters are ENTIRELY ABSENT.** `arxmcp_request_total`, `arxmcp_request_latency_seconds`, `arxmcp_request_inflight`, `arxmcp_result_bytes`, `arxmcp_embed_calls_total`, `arxmcp_embed_latency_seconds`, `arxmcp_rerank_calls_total`, `arxmcp_rerank_latency_seconds` all need to be added. | New module `server/observability/metrics.py` for the new families. Do NOT move existing metrics. |
| 3 | **Cross-process exposure is THE load-bearing job.** Two metrics (`LATEXML_DRIFT_DETECTED_COUNTER`, `EVAL_NDCG5_GAUGE`) explicitly defer here. Plus sentinels written by E11_S02/S03/S05 that warrant new gauges. | Add `refresh_sentinel_metrics` helper called from the existing scrape-time hook. Reads `var/arxmcp/ops/*.flag` + `var/arxmcp/ops/eval-reports/*.json` + `var/arxmcp/ops/backup-status.json`. |
| 4 | **Tool instrumentation: dispatcher-level wrapper in `server/tools.py::register_all`, NOT per-handler decorator.** Single change point, applies to all 7 tools uniformly, no per-file edits. | `@functools.wraps` + `functools.partial` to thread the tool name. Wrap each handler at registration time. |
| 5 | **Brief says `arxmcp_retrieval_ndcg5{corpus_version}`; code has `arxmcp_eval_ndcg5`.** Same metric — different name. | **Keep `arxmcp_eval_ndcg5`.** Renaming a Prometheus metric is a one-way door (breaks Grafana dashboards, alert rules). The implementation summary records the discrepancy; E14_S09 reads whatever's at `/metrics`. |
| 6 | **`promtool check metrics` does NOT validate metric exposition output.** It validates ALERTING RULES (YAML). The brief's wording is imprecise. | Use `prometheus_client.parser.text_string_to_metric_families` for in-process validation. No `promtool` binary dependency. |
| 7 | **`EMBED_SINGLEFLIGHT_DEDUP_COUNTER` already exists** in `server/health.py` (it's surface for `SINGLEFLIGHT_DEDUP_COUNT` in `server/query_encoder.py`). AC3 already passes. | Document this in the implementation summary. No new work for AC3. |
| 8 | **`EVAL_NDCG5_GAUGE` label cardinality.** Nightly bumps → ~365 corpus_versions/year. The metric docstring already warns. | Scrape hook caps exposure at N=5 most-recent versions (one work-week of historical data). |
| 9 | **No tool-schema changes.** | `TOOL_SCHEMA_VERSION` stays at 6. |
| 10 | **Defer ingestion metrics** (`arxmcp_ingest_*`). The server doesn't run ingest; design note 08 says those go in a separate process binary. Out of E14_S01 scope. | Documented in implementation summary as a follow-up. |

---

## 2. Divergence + resolution

### `LATEXML_DRIFT_DETECTED_COUNTER` → Gauge?

- Brief 2 argues YES: the scrape-time-hook semantic is "current
  fixture drift count" — a Gauge. A Counter cannot represent
  "fixed two of three drifts" because Counters only go up.
  `reset_drift_metrics_for_tests` already uses the documented-
  private `._value.set(0)` escape hatch.
- Brief 1 doesn't take a position; flags the counter's existence.

**Resolution: convert to Gauge.** The breaking change is bounded —
the test reset hook moves from `._value.set(0)` to `.set(0)`. The
metric NAME changes from `arxmcp_latexml_drift_detected_total` to
`arxmcp_latexml_drift_detected` (Prometheus drops the `_total`
suffix on Gauges, per the OpenMetrics spec). E14_S09's Grafana
dashboard hasn't shipped; breakage is minimal.

Update the E10_S04 runbook reference + the implementation
summary to record this rename.

### Backup metrics — add or defer?

- Brief 2 recommends adding `arxmcp_backup_last_success_timestamp_seconds`
  + `arxmcp_backup_status{state}` in v1. Sentinel exists; cost is
  one `stat()` + `json.loads` per scrape.
- Brief 1 doesn't mention.

**Resolution: add in v1.** The sentinel is already specified by
E11_S05. The metric is trivially derivable. "Last backup was N
hours ago" is an operator dashboard primitive.

### `arxmcp_eval_quarantine` and `arxmcp_delta_timeout` gauges

Brief 2 recommends adding both. Brief 1 doesn't mention. Both
sentinel files exist (E11_S04 + E11_S02). Cheap and informative.

**Resolution: add `arxmcp_eval_quarantine_active` and
`arxmcp_delta_timeout_active`, both 0/1 gauges** mirroring the
`flag present` ↔ "1.0" mapping. Operator alert rules become
trivially `... > 0`.

---

## 3. Load-bearing quotes

### `server/main.py:413-423` — /metrics handler already wired

> "metrics_app = make_asgi_app() … `refresh_metrics_from_singleton_state(resources)` … `app.mount('/metrics', metrics_wrapper)`"

### `server/metrics.py:177-188` — LATEXML_DRIFT deferred to E14

> "Future operator-facing /metrics exposure will need a
> scrape-time hook that reads the sentinel file and reflects its
> presence/count as the counter's value across the server-vs-cron
> process boundary."

### `server/metrics.py:194-216` — EVAL_NDCG5 deferred + label-cap warning

> "the E14 scrape-time hook that rehydrates this gauge from JSON
> reports MUST cap the exposed labels at the N most-recent
> versions to avoid Prometheus high-cardinality drift."

### Brief 1 §1 — existing `EMBED_SINGLEFLIGHT_DEDUP_COUNTER` model

The counter is updated via delta pattern in
`refresh_metrics_from_singleton_state` (health.py:193-199). Same
pattern for new scrape-time refresh hooks.

---

## 4. Design decisions

### D1. Module: `server/observability/metrics.py` (new)

Existing `server/metrics.py` keeps cache + retrieval-cap +
drift + eval gauges. New module contains:
- `REQUEST_COUNTER` — `arxmcp_request_total{tool, status}`
- `REQUEST_LATENCY` — `arxmcp_request_latency_seconds{tool}`,
  **Histogram** (aggregatable across replicas — even though
  single-process today, this matches future-proof Prometheus
  patterns).
- `REQUEST_INFLIGHT` — `arxmcp_request_inflight{tool}`, Gauge.
- `RESULT_BYTES` — `arxmcp_result_bytes{tool}`, Histogram.
- `EMBED_CALLS_COUNTER` — `arxmcp_embed_calls_total{model,
  outcome}`, Counter.
- `EMBED_LATENCY` — `arxmcp_embed_latency_seconds{model}`,
  Histogram.
- `RERANK_CALLS_COUNTER` — `arxmcp_rerank_calls_total{model,
  outcome}`, Counter.
- `RERANK_LATENCY` — `arxmcp_rerank_latency_seconds{model}`,
  Histogram.
- Reset helpers for tests.

### D2. New gauges in `server/metrics.py`

Following the established placement convention (existing
deferred gauges live there):

- `LATEXML_DRIFT_DETECTED_COUNTER` → renamed to
  `LATEXML_DRIFT_DETECTED_GAUGE` (`arxmcp_latexml_drift_detected`).
- `EVAL_QUARANTINE_ACTIVE_GAUGE` (`arxmcp_eval_quarantine_active`).
- `DELTA_TIMEOUT_ACTIVE_GAUGE` (`arxmcp_delta_timeout_active`).
- `BACKUP_LAST_SUCCESS_GAUGE`
  (`arxmcp_backup_last_success_timestamp_seconds`).
- `BACKUP_STATUS_GAUGE`
  (`arxmcp_backup_status{state="success|partial|failed"}`).

Plus the matching `reset_*_for_tests` helpers.

### D3. Tool-handler instrumentation via dispatcher wrapper

Per Brief 1 §4. In `server/tools.py::register_all`, wrap each
handler at registration time:

```python
import functools
import json
import time

async def _tracked_handler(tool_name, handler, *args, **kwargs):
    REQUEST_INFLIGHT.labels(tool=tool_name).inc()
    t0 = time.perf_counter()
    status = "error"
    try:
        result = await handler(*args, **kwargs)
        status = "ok"
        return result
    finally:
        latency = time.perf_counter() - t0
        REQUEST_INFLIGHT.labels(tool=tool_name).dec()
        REQUEST_COUNTER.labels(tool=tool_name, status=status).inc()
        REQUEST_LATENCY.labels(tool=tool_name).observe(latency)
        if status == "ok":
            try:
                payload = result.structuredContent or {}
                size = len(json.dumps(payload, ensure_ascii=False).encode())
                RESULT_BYTES.labels(tool=tool_name).observe(size)
            except Exception:  # noqa: BLE001 — observability path
                pass

wrapped = functools.wraps(handler)(
    functools.partial(_tracked_handler, tm.name, handler)
)
mcp_server.add_tool(wrapped, name=tm.name, ...)
```

No per-handler decorator scatter. Single instrumentation point.

### D4. Embedder + reranker instrumentation in calling modules

Per Brief 1 §6, NOT via callback registration in `Resources`:

- `server/query_encoder.py::_encode_query_sync` — wrap the
  model forward pass with `EMBED_LATENCY.labels(...).time()`,
  increment `EMBED_CALLS_COUNTER.labels(...)`.
- `server/retrieval/rerank.py::RerankPhase.rerank` — wrap the
  reranker call. Both `ok` and `error` outcomes.

Direct imports of the counters; established precedent
(`RETRIEVAL_CAP_REJECTIONS_COUNTER` is imported directly in
middleware).

### D5. Scrape-time hook: `refresh_sentinel_metrics`

New helper called from `refresh_metrics_from_singleton_state`:

```python
def refresh_sentinel_metrics(ops_dir: Path) -> None:
    _refresh_drift_gauge(ops_dir / "drift-detected.flag")
    _refresh_eval_ndcg5(ops_dir / "eval-reports", cap_n=5)
    _refresh_eval_quarantine(ops_dir / "eval-quarantine.flag")
    _refresh_delta_timeout(ops_dir / "delta-timeout.flag")
    _refresh_backup_status(ops_dir / "backup-status.json")
```

Contracts (per Brief 2 §4):
- **Cheap:** stat + small JSON parse.
- **Idempotent:** gauge `set()` is naturally idempotent.
- **Missing-file graceful:** absent → explicit `set(0.0)` for
  presence-flag gauges; skip update for value gauges.
- **Malformed-JSON graceful:** log WARNING, retain last value.

### D6. EVAL_NDCG5_GAUGE label cap

Cap N=5 most-recent corpus_versions exposed at any time. The
scrape hook walks `eval-reports/`, picks the 5 highest
`corpus_v<N>` filenames, sets their gauges, and (optionally)
removes older labels via `EVAL_NDCG5_GAUGE.remove(version=...)`
to keep the registry bounded.

### D7. Drift gauge schema interpretation

`drift-detected.flag` may be a binary touch file OR a JSON
payload. The scrape hook handles both:
- **Binary touch file (0 bytes):** set gauge to 1.0.
- **JSON with `fixture_count: N`:** set gauge to N.
- **Absent:** set gauge to 0.0.

Defensive parsing — never crashes /metrics.

### D8. Config: `ARXMCP_OPS_DIR` env var

Per Brief 2 open Q2. Add `ARXMCP_OPS_DIR` to `server/config.py`
with default `var/arxmcp/ops`. The scrape hook reads it from
`Resources.config.ops_dir`. Lets tests inject `tmp_path`
cleanly.

### D9. /metrics security posture — no changes needed

Per Brief 2 §8. `OriginValidationMiddleware` passes requests
with no `Origin` header (Prometheus scraper case).
`HostValidationMiddleware` accepts loopback Hosts. Server is
loopback-only. No auth required at v1.

### D10. Test surface

Per Brief 2 §7. New file `tests/test_server_metrics.py` with:

- AC1: `GET /metrics` returns 200, valid Prometheus text format.
- AC2: per-tool `arxmcp_request_total{tool,status}` increments.
- AC3: `arxmcp_cache_hits_total{layer="tier1"}` increments on
  repeated query.
- AC4: `arxmcp_embed_singleflight_dedup_total` already present
  (sanity check).
- AC5: `arxmcp_eval_ndcg5{corpus_version="N"}` set by the
  scrape hook from a synthetic eval-report.
- AC6: `prometheus_client.parser.text_string_to_metric_families`
  validates the output.

Plus regression guards for D5-D8 sentinel reads + reset hooks +
the LATEXML→Gauge conversion + label-cap.

### D11. No tool-schema changes

`TOOL_SCHEMA_VERSION` stays at 6.

### D12. Documentation updates

- `docs/ops/latexml-drift-runbook.md`: update the metric name
  from `..._total` Counter to `arxmcp_latexml_drift_detected`
  Gauge.
- `docs/ops/drift-watchdog.md`: AC3 deferral note can be
  REMOVED (E14_S01 closes it).
- `docs/ops/backup-restore.md`: add a "Metrics surface" section
  pointing at `/metrics` and the new backup gauges.

---

## 5. Forced cross-file changes

| File | Change | Why |
|---|---|---|
| `server/observability/__init__.py` (NEW) | empty package marker | D1 |
| `server/observability/metrics.py` (NEW) | new metric families + reset helpers | D1 |
| `server/metrics.py` (MODIFY) | LATEXML Counter → Gauge; add quarantine/timeout/backup gauges | D2 |
| `server/tools.py` (MODIFY) | dispatcher wrapper at register_all | D3 |
| `server/query_encoder.py` (MODIFY) | embed counter + latency increment | D4 |
| `server/retrieval/rerank.py` (MODIFY) | rerank counter + latency increment | D4 |
| `server/health.py` (MODIFY) | call refresh_sentinel_metrics from existing hook | D5 |
| `server/config.py` (MODIFY) | add `ARXMCP_OPS_DIR` env var | D8 |
| `tests/test_server_metrics.py` (NEW) | end-to-end /metrics + sentinel scrape tests | D10 |
| `docs/ops/latexml-drift-runbook.md` (MODIFY) | metric name update | D12 |
| `docs/ops/drift-watchdog.md` (MODIFY) | remove AC3 deferral note | D12 |
| `docs/ops/backup-restore.md` (MODIFY) | add Metrics surface section | D12 |

NOT touched:
- `ingest/*` (no ingest metrics in this milestone — design-note
  ingestion metrics belong to a separate process).
- `ops/watchdog_eval.py` etc — the watchdog writes JSON reports
  unchanged; the scrape hook reads them.
- Hash-anchored tests (no tool surface change).

---

## 6. Landmines (consolidated)

1. **Counter vs Gauge for drift** — convert to Gauge; semantically
   correct + cleaner reset.
2. **EVAL_NDCG5 label cap** — N=5 most-recent versions; remove
   older labels at scrape time.
3. **`arxmcp_retrieval_ndcg5` vs `arxmcp_eval_ndcg5` name** —
   keep the existing name; rename is a one-way door.
4. **`promtool check metrics` doesn't validate /metrics output**
   — use `prometheus_client.parser` for in-process validation.
5. **Tool wrapper, not per-handler decorator** — dispatcher
   level, single change point.
6. **No `Origin` header on /metrics** — middleware passes
   requests without one; no change needed.
7. **Sentinel file directory permissions** — document mode 0775
   + shared group convention.
8. **Result bytes measurement** — only on success path; avoid
   JSON serialization cost on errors.
9. **Histogram over Summary** — aggregatable for future
   multi-replica scaling.
10. **`assert` banned for invariants.**
11. **HEREDOC commits, GPG signed, no `--no-verify`.**

---

## 7. AC coverage at code-ship

| Brief AC | Coverage |
|---|---|
| Per-tool `arxmcp_request_total` increments | Verifiable: `test_per_tool_request_counter_increments`. |
| `arxmcp_cache_hits_total{layer=tier1}` on repeat | Verifiable: `test_tier1_cache_hit_increments`. |
| `arxmcp_embed_singleflight_dedup_total` on concurrent identical | Existing metric; verify it's exposed at /metrics. |
| `arxmcp_retrieval_ndcg5{corpus_version}` present | Verifiable (with name reconciliation to `arxmcp_eval_ndcg5`): `test_eval_ndcg5_scrape_hook`. |
| `/metrics` valid Prometheus text + `promtool check metrics` exits 0 | Verifiable via `prometheus_client.parser`. promtool defer (binary not available; brief wording imprecise). |
| Drift watchdog updates `arxmcp_retrieval_ndcg5` readable via /metrics | Verifiable: synthetic eval-report fixture + scrape-hook test. |

5/6 fully verifiable. AC for `promtool` is met by the in-process
parser substitution.

---

## 8. External writes required

**None at code-ship.** All in-repo writes (new files, modified
files, tests, doc updates). Operator-runtime: no new writes —
the scrape hook only READS existing sentinel files written by
prior milestones.

---

## 9. Suggested implementation order

1. `server/observability/__init__.py` + `server/observability/metrics.py`
   (the new families).
2. `server/metrics.py` — LATEXML Counter → Gauge conversion +
   new sentinel-source gauges.
3. `server/config.py` — `ARXMCP_OPS_DIR` env var.
4. `server/health.py` — `refresh_sentinel_metrics` helper.
5. `server/tools.py` — dispatcher-level wrapper.
6. `server/query_encoder.py` + `server/retrieval/rerank.py` —
   embed/rerank counters.
7. `tests/test_server_metrics.py`.
8. Doc updates (latexml-drift, drift-watchdog, backup-restore).
9. `make test`; ruff clean; commit.

---

## 10. Done-when checklist

- [ ] /metrics serves valid Prometheus text format (parser-
      validated).
- [ ] Per-tool request counter + latency histogram + inflight
      gauge + result-bytes histogram populate on each tool call.
- [ ] Embed + rerank counters + latency histograms populate on
      retrieval.
- [ ] LATEXML drift Counter → Gauge conversion + scrape-hook
      reads sentinel.
- [ ] EVAL_NDCG5 scrape hook reads eval-report JSONs + caps at
      N=5.
- [ ] Backup gauges read backup-status.json.
- [ ] Eval-quarantine + delta-timeout 0/1 gauges read flag
      presence.
- [ ] `ARXMCP_OPS_DIR` env var supports test injection.
- [ ] No tool-schema changes; `TOOL_SCHEMA_VERSION` stays at 6.
- [ ] `make test` green; ruff clean.
