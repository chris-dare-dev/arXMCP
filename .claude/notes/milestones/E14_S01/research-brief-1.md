# E14_S01 Research Brief — Axis 1: In-Codebase Metric Inventory

**Author:** Research sub-agent A (metric inventory axis)
**Date:** 2026-05-15

---

## 1. What is already in `server/metrics.py`

Full inventory of defined metrics (all in the default single-process Prometheus registry):

| Symbol | Prometheus name | Type | Labels |
|---|---|---|---|
| `CACHE_LOOKUPS_COUNTER` | `arxmcp_cache_lookups_total` | Counter | `tier` |
| `CACHE_HITS_COUNTER` | `arxmcp_cache_hits_total` | Counter | `tier` |
| `CACHE_EVICTIONS_COUNTER` | `arxmcp_cache_evictions_total` | Counter | `tier` |
| `CACHE_BYTES_GAUGE` | `arxmcp_cache_bytes` | Gauge | `tier` |
| `CACHE_PAYLOAD_SKIPS_COUNTER` | `arxmcp_cache_payload_skips_total` | Counter | `reason` |
| `RETRIEVAL_CAP_REJECTIONS_COUNTER` | `arxmcp_retrieval_cap_rejections_total` | Counter | `tool` |
| `LATEXML_DRIFT_DETECTED_COUNTER` | `arxmcp_latexml_drift_detected_total` | Counter | `fixture` |
| `EVAL_NDCG5_GAUGE` | `arxmcp_eval_ndcg5` | Gauge | `corpus_version` |

**Deferred-to-E14 docstrings, verbatim:**

`LATEXML_DRIFT_DETECTED_COUNTER` (line 166–176):
> `**F8 (E10_S04 critique) — production exposure deferred to E14.**`
> `At v1 the only observer of this counter is the test suite... Future operator-facing /metrics exposure will need a scrape-time hook that reads the sentinel file and reflects its presence/count as the counter's value across the server-vs-cron process boundary.`

`EVAL_NDCG5_GAUGE` (line 193–196):
> `Production /metrics exposure of this gauge for the running server process is **deferred to E14** — same posture as LATEXML_DRIFT_DETECTED_COUNTER above. v1 operational signal is the watchdog's JSON report at var/arxmcp/ops/eval-reports/ + the sentinel flag at var/arxmcp/ops/eval-quarantine.flag.`

Also in `server/health.py`, additional existing metrics:

| Symbol | Prometheus name | Type | Labels |
|---|---|---|---|
| `CORPUS_VERSION_GAUGE` | `arxmcp_corpus_version` | Gauge | none |
| `RESOURCE_WARM_GAUGE` | `arxmcp_resources_warm` | Gauge | `resource` |
| `PROCESS_START_TIME_GAUGE` | `arxmcp_process_start_time_seconds` | Gauge | none |
| `EMBED_SINGLEFLIGHT_DEDUP_COUNTER` | `arxmcp_embed_singleflight_dedup_total` | Counter | none |

The `EMBED_SINGLEFLIGHT_DEDUP_COUNTER` is refreshed at scrape time via a delta
pattern in `refresh_metrics_from_singleton_state` (health.py:193–199):
```python
current = get_singleflight_dedup_count()
delta = current - _LAST_DEDUP_COUNT
if delta > 0:
    EMBED_SINGLEFLIGHT_DEDUP_COUNTER.inc(delta)
    _LAST_DEDUP_COUNT = current
```
This is the correct cross-process counter model. The same pattern is what E14
needs for `LATEXML_DRIFT_DETECTED_COUNTER` and `EVAL_NDCG5_GAUGE` — except
those are cross-PROCESS (cron vs. server), not just cross-thread.

---

## 2. What is currently exposed at `/metrics`

The `/metrics` HTTP handler IS already wired. In `server/main.py:413–423`:

```python
metrics_app = make_asgi_app()

async def metrics_wrapper(scope, receive, send):
    resources: Resources | None = getattr(app.state, "resources", None)
    if resources is not None:
        refresh_metrics_from_singleton_state(resources)
    await metrics_app(scope, receive, send)

app.mount("/metrics", metrics_wrapper)
```

This is correct and complete:
- `make_asgi_app()` generates the standard Prometheus text exposition.
- The wrapper fires `refresh_metrics_from_singleton_state` at scrape time,
  which pulls cache-byte gauges and the singleflight-dedup delta.
- `/metrics` is in `_BYTE_CAP_EXEMPT_PREFIXES` so the body-size cap is bypassed.
- `OriginValidationMiddleware` is applied: only loopback Origins pass.
  Since `bind_host` is loopback-only by config (LOOPBACK_HOSTS validation in
  `server/config.py`), a Prometheus scraper on the same host is guaranteed to
  be loopback. No separate exception needed.

**Conclusion: the /metrics HTTP handler is fully wired. This milestone does NOT
need to create an endpoint — it needs to populate the metric families.**

---

## 3. Missing metric families (what the brief requires vs. what exists)

### 3a. Request counters — ENTIRELY ABSENT

`grep -r "arxmcp_request" server/` returns zero results. Required families:
- `arxmcp_request_total{tool, status}`
- `arxmcp_request_latency_seconds{tool}`
- `arxmcp_request_inflight{tool}`
- `arxmcp_result_bytes{tool}`

All four are net-new. The brief says `server/observability/metrics.py` as the
target module; this milestone should create that file (currently the metric
definitions are split across `server/metrics.py` and `server/health.py`).
**Recommendation: do NOT move existing metrics; add new request/embed/rerank
metrics to `server/observability/metrics.py` and import from it.**

### 3b. Embed/rerank counters — PARTIALLY ABSENT

`EMBED_SINGLEFLIGHT_DEDUP_COUNTER` (`arxmcp_embed_singleflight_dedup_total`)
already exists in `server/health.py`. The remaining embed/rerank families are
absent:
- `arxmcp_embed_calls_total{model, outcome}` — new
- `arxmcp_embed_latency_seconds{model}` — new
- `arxmcp_rerank_calls_total{model, outcome}` — new
- `arxmcp_rerank_latency_seconds{model}` — new

The brief's AC says `arxmcp_embed_singleflight_dedup_total` is already
implemented — the brief just needs it present in `/metrics`, which it already is.

### 3c. NDCG gauge — EXISTS with WRONG NAME (Landmine A)

The brief says: `arxmcp_retrieval_ndcg5{corpus_version}`.
The code today has: `arxmcp_eval_ndcg5{corpus_version}` (in `server/metrics.py`).

**Recommendation: keep `arxmcp_eval_ndcg5`. Do NOT rename it.**
Renaming a Prometheus metric name is a one-way door — it breaks any alert rule
or Grafana panel that references the old name. E14_S09 (Grafana dashboard) has
not shipped yet so breakage is bounded, but establishing the wrong precedent
matters. The brief's expected name (`arxmcp_retrieval_ndcg5`) should be treated
as imprecise; the implementation note in the state.json should record the
discrepancy and the decision. The test suite AC that reads
`arxmcp_retrieval_ndcg5` from `/metrics` must be written to accept
`arxmcp_eval_ndcg5` instead — or the brief AC itself must be annotated as
"met by `arxmcp_eval_ndcg5`."

---

## 4. The 7 tool handlers and instrumentation approach

From `server/tools.py::register_all`, the handler map:
```python
handler_by_name = {
    "search_papers": handle_search_papers,     # server/handlers/search.py
    "get_chunk":     handle_get_chunk,          # server/handlers/chunk.py
    "find_equation": handle_find_equation,      # server/handlers/equation.py
    "get_definitions": handle_get_definitions,  # server/handlers/definitions.py
    "find_lemma_by_name": handle_find_lemma_by_name, # server/handlers/lemma.py
    "get_paper":     handle_get_paper,          # server/handlers/paper.py
    "cite_neighbors": handle_cite_neighbors,    # server/handlers/citations.py
}
```

**Instrumentation approach: dispatcher-level wrapper in `register_all`, NOT
per-handler decorator.**

Rationale:
1. The tool name is known at registration time; a dispatcher wrapper in
   `register_all` applies uniformly to all 7 handlers with no per-file edits.
2. Handlers already return `CallToolResult` (not plain dicts); result bytes are
   measurable at the wrapper boundary as `len(json.dumps(result.structuredContent))`.
3. A per-handler `@track_request("search_papers")` decorator requires 7
   identical decorator applications across 7 files; a dispatcher wrapper is
   one change.
4. The existing `RETRIEVAL_CAP_REJECTIONS_COUNTER` fires in
   `SessionCapMiddleware` — BEFORE FastMCP dispatches. The wrapper fires AFTER
   FastMCP dispatches but BEFORE the tool result is serialized to SSE. This is
   the right plane for per-tool latency, result-bytes, and inflight counters.

The dispatcher wrapper shape (pseudo):
```python
import functools, time
async def _tracked(tool_name, handler, *args, **kwargs):
    REQUEST_INFLIGHT.labels(tool=tool_name).inc()
    t0 = time.perf_counter()
    try:
        result = await handler(*args, **kwargs)
        status = "ok"
    except Exception:
        status = "error"
        raise
    finally:
        latency = time.perf_counter() - t0
        REQUEST_INFLIGHT.labels(tool=tool_name).dec()
        REQUEST_COUNTER.labels(tool=tool_name, status=status).inc()
        REQUEST_LATENCY.labels(tool=tool_name).observe(latency)
    # result_bytes: measure structured payload AFTER result returns
    if hasattr(result, 'structuredContent') and result.structuredContent:
        try:
            b = len(json.dumps(result.structuredContent).encode())
            RESULT_BYTES.labels(tool=tool_name).observe(b)
        except Exception:
            pass
    return result
```

Then in `register_all`:
```python
wrapped = functools.wraps(handler)(functools.partial(_tracked, tm.name, handler))
mcp_server.add_tool(wrapped, name=tm.name, ...)
```

**Result bytes counter — measurement location (Landmine G).** Measuring
`json.dumps(structuredContent)` inside the wrapper is cheap for this workload
(results are bounded by 256 KB cap). The `BodySizeCapMiddleware` already does
this measurement for capping; de-duplicating the measurement is acceptable.
The alternative (measuring at the FastAPI middleware level) cannot distinguish
per-tool because the middleware has no MCP tool context. Dispatcher wrapper wins.

---

## 5. Singleflight dedup counter increment point

In `server/query_encoder.py::encode_query` (lines 326–332):
```python
inflight_fut = _inflight.get(key)
if inflight_fut is not None:
    with _dedup_count_lock:
        SINGLEFLIGHT_DEDUP_COUNT += 1
    result = await asyncio.shield(inflight_fut)
    return result.copy()
```

`SINGLEFLIGHT_DEDUP_COUNT` is already incremented at the correct location. The
`EMBED_SINGLEFLIGHT_DEDUP_COUNTER` Prometheus Counter in `health.py` is fed by
the delta pattern at scrape time. This is already correct.

For `server/resources.py::Singleflight.run` (the reranker's singleflight), the
`self._dedup_count` attribute already tracks fast-path hits but is NOT currently
wired to any Prometheus counter. If `arxmcp_rerank_calls_total{outcome="dedup"}`
is desired, the increment should go here. However, the brief names
`arxmcp_rerank_calls_total{model, outcome}` as a general call counter (not
specifically dedup) — the dedup signal for the reranker is implicit in the
difference between `calls_total{outcome="ok"}` and actual forward-pass counts.

---

## 6. Embedder/reranker callbacks via `resources.py`

The `Resources.startup` method:
- BGE-M3: loaded at step 3 via `await loop.run_in_executor(None, _get_model)`.
  The actual INFERENCE path for queries goes through `server/query_encoder.py::encode_query`.
- Reranker: loaded at step 4 via `_load_reranker_or_raise()`, stored as
  `resources.reranker_model`. Inference goes through `server/retrieval/rerank.py::RerankPhase.rerank`.

**The brief's `arxmcp_embed_calls_total` is the SERVER's inference path, NOT
the ingest path.** Confirmed: `ingest/embedder.py::embed_paper` is the batch
ingest path (different process in production); `server/query_encoder.py::encode_query`
is the MCP-serving path. The metric must be in the server's encoder.

**Recommended callback approach:**
- For the embedder: import `arxmcp_embed_calls_total` in `server/query_encoder.py`
  and increment INSIDE `_encode_query_sync` (the executor-thread function).
  The latency timer wraps the `model(**encoded)` call. No callbacks needed.
- For the reranker: import `arxmcp_rerank_calls_total` in
  `server/retrieval/rerank.py::RerankPhase.rerank` and increment there.

The closure-registered-on-Resources approach would work but adds indirection.
Direct import in the calling module is simpler and has established precedent
(`RETRIEVAL_CAP_REJECTIONS_COUNTER` is imported directly in `middleware.py`).

---

## 7. `@track_request` decorator shape

As established in section 4, the preferred implementation is a dispatcher-level
wrapper, not a decorator. The wrapper MUST:
1. Be async-aware: `async def _tracked(tool_name, handler, *args, **kwargs)`.
2. Use `try/finally` so failures still record `status=error` and decrement
   `REQUEST_INFLIGHT`.
3. Capture result bytes from `result.structuredContent` after the handler
   returns (inside the finally block or after the try block on success).
4. Use `time.perf_counter()` (monotonic, sub-millisecond resolution) not
   `time.time()`.
5. Avoid JSON serialization cost on the error path (only measure bytes on `ok`).

---

## 8. `promtool check metrics` — Landmine E (brief wording imprecise)

`promtool check metrics` validates a **rules file** (alerting or recording
rules in YAML), NOT the `/metrics` text exposition output. The brief's wording
is imprecise.

The correct way to validate `/metrics` text output in a test:
```python
from prometheus_client.parser import text_string_to_metric_families
body = await client.get("/metrics")
list(text_string_to_metric_families(body.text))  # raises on malformed output
```
This uses only `prometheus_client` (already a dependency) and requires no
external binary. **Do NOT add `promtool` as a test dependency** — it would
require a Go binary in the dev environment and is overkill for this single
assertion.

`promtool` is confirmed not installed in the dev environment (`which promtool`
returns empty). Use `prometheus_client.parser` instead.

---

## Open Questions

1. **Module structure:** Should new request/embed/rerank metrics go in a new
   `server/observability/metrics.py` (as the brief says) or extend the existing
   `server/metrics.py`? The brief's module name implies a new package. Recommend
   the new path for clean separation; existing tests importing
   `server.metrics.*` are unaffected.

2. **Histogram vs. Summary for latency:** The brief uses
   `arxmcp_request_latency_seconds{tool}` without specifying. Prometheus
   `Histogram` (with default `le` buckets) is preferred over `Summary` for
   latency because histograms are aggregatable across replicas (even though
   this is single-process today). Recommend `Histogram`.

3. **Label cardinality for `EVAL_NDCG5_GAUGE`.** The docstring warns about
   unbounded `corpus_version` growth (~365/year). The E14 scrape-time hook
   must cap at the N most-recent versions (recommend N=7 — one week of nightly
   runs). This is not just a note — it must be in the implementation.

4. **Sentinel file for `LATEXML_DRIFT_DETECTED_COUNTER`.** The scrape hook
   must read `var/arxmcp/ops/drift-detected.flag` to know how many drift
   events the cron process has seen. The flag is binary (present/absent), not
   a count. The counter should be set to 1 if present, 0 if absent — or the
   sentinel should be changed to a count file. Which is it?

---

## External Writes the Implementation Will Require

1. **New file:** `server/observability/__init__.py` (empty package marker).
2. **New file:** `server/observability/metrics.py` — the four request counter/
   histogram/gauge families + embedder/reranker families.
3. **Modify:** `server/tools.py::register_all` — dispatcher wrapper applied to
   all 7 handlers.
4. **Modify:** `server/query_encoder.py::_encode_query_sync` — embed call
   counter + latency.
5. **Modify:** `server/retrieval/rerank.py::RerankPhase.rerank` — rerank call
   counter + latency.
6. **Modify:** `server/health.py::refresh_metrics_from_singleton_state` —
   add scrape-time hooks for `LATEXML_DRIFT_DETECTED_COUNTER` (read sentinel
   file) and `EVAL_NDCG5_GAUGE` (read most-recent N eval-report JSONs).
7. **New file:** `tests/test_metrics.py` — per-tool increment assertions +
   prometheus_client.parser validation of `/metrics` response body.
