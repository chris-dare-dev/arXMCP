# E14_S02 — implementation summary

## What landed

E14_S02 ships OpenTelemetry distributed tracing across the MCP
server: one parent span per JSON-RPC `tools/call` with child
spans for the BGE-M3 embed forward pass, the LanceDB ANN query,
and the BGE-reranker-v2-m3 cross-encoder pass. Tracing is
disabled by default; setting `ARXMCP_OTEL_ENDPOINT` enables export
to a Phoenix sidecar (or any OTLP/gRPC collector).

## Files changed

| Path | Change | Synthesis ref |
|---|---|---|
| `pyproject.toml` | adds `opentelemetry-api>=1.41,<2`, `opentelemetry-sdk>=1.41,<2`, `opentelemetry-exporter-otlp-proto-grpc>=1.41,<2` | D12 |
| `uv.lock` | re-pinned via `uv lock` (+ ~10 OTel transitive deps; grpcio, protobuf, importlib-metadata) | D12 |
| `server/config.py` | NEW `otel_endpoint: str \| None = None` field; required by the `_scan_unknown_arxmcp_env_vars` validator | finding 2 |
| `server/observability/__init__.py` | docstring covers both `metrics` (E14_S01) and `tracing` (E14_S02) submodules | D1 |
| `server/observability/tracing.py` | NEW — `setup_tracing`, `shutdown_tracing`, `_probe_endpoint`, ContextVars (`current_session_id`, `current_agent_role`, `current_cache_layer`), `span_tool_call`, `span_embed`, `span_ann`, `span_bm25`, `span_rerank`, `span_summarize`, `set_cache_layer`, `reset_tracing_for_tests` | D1-D5, D9, D10 |
| `server/middleware.py` | NEW pure-ASGI `TracingContextMiddleware` (reads `Mcp-Session-Id` + `Arxmcp-Agent-Role` → ContextVars) | D3 |
| `server/main.py` | `setup_tracing(config)` in lifespan before `Resources.startup`; `shutdown_tracing()` after `resources.shutdown()`; `TracingContextMiddleware` registered as innermost middleware | D2, D3 |
| `server/tools.py` | rename `_wrap_with_metrics` → `_wrap_with_observability` (kept `_wrap_with_metrics` as alias for backward-compat); wraps every handler in `span_tool_call(...)` with `corpus_version` + `k` extracted from kwargs | D1 |
| `server/query_encoder.py` | wraps the BGE-M3 forward pass in `span_embed(model="bge-m3", revision=BGE_M3_COMMIT_SHA)` | D4 |
| `server/retrieval/rerank.py` | wraps the BGE-reranker-v2-m3 batched forward pass in `span_rerank(...)` | D4 |
| `server/handlers/search.py` | imports `span_ann` + `set_cache_layer`; wraps LanceDB ANN call in `span_ann(k=k)`; calls `set_cache_layer("tier1"|"tier2")` on a cache hit | D4, D6 |
| `tests/test_tracing.py` | NEW — 22 tests covering D2 (setup/disabled/idempotent/probe), D3 (ContextVar plumbing + middleware), D4 (child spans), D6 (cache-layer enum) | D8 |
| `tests/test_session_caps.py` | relax `test_f7_middleware_order_session_cap_inside_request_body_size_limit` from full-list-equality to a relative-ordering check; the F7 invariant (SessionCap INSIDE RequestBodySizeLimit) is preserved | follow-on |
| `.claude/notes/08-security-observability-ops.md` | §Tracing rewritten: cache-layer enum → `tier1\|tier2\|tier3\|miss`; port 4317 (gRPC) confirmed; `_agent_role` header documented; disabled-by-default semantics documented | D6, D11 |
| `.claude/docs/observability-tracing.md` | NEW operator-facing reference: enable instructions, attribute catalog, security note, failure-mode behavior, Phoenix Docker recipe | D11 |

## Drift from research synthesis (deliberate)

1. **`_wrap_with_metrics` alias retained.** D1 specified a clean
   rename. After implementing the rename, the imports in
   `tests/test_server_metrics.py` and the docstring references
   in handler files would have required cascading edits. Instead
   the new function is `_wrap_with_observability` and the old
   name is kept as a module-private alias (`_wrap_with_metrics =
   _wrap_with_observability`). Zero behavioural impact; readers
   see both names and can grep either.

2. **`Arxmcp-Agent-Role` is a header, NOT a JSON-Schema
   property.** This was D7's resolution against the brief's
   literal "documented in the tool schema." Adopting the header
   keeps `TOOL_SCHEMA_VERSION` pinned at 6 and avoids invalidating
   the BP1 prompt-cache for every existing agent prefix per
   `07-multi-agent-caching.md` Property 1. The header semantics
   are documented in `.claude/docs/observability-tracing.md`.

3. **No `docs/observability/tracing.md`.** The brief named that
   path; CLAUDE.md §1's strict doc-layout rule reserves `docs/`
   for operator-facing docs linked from the root README. Tracing
   config is operator-internal — landed at
   `.claude/docs/observability-tracing.md` (matches
   `.claude/docs/model-policy.md` / `.claude/docs/orchestrator-rules.md`
   precedent).

## Test count delta

* Pre-milestone: 1739 passed, 8 skipped, 1 xfailed (from
  end-of-E14_S01 baseline).
* Post-feat: 1761 passed (+22 from `tests/test_tracing.py`).
* Post-rect: 1778 passed (+17 regression guards covering F1, F2,
  F4, F7, F10, F11, F14 from the adversary critique).
* `ruff check .` — clean.

## Acceptance criteria status

- [x] `pytest tests/test_tracing.py` passes: `search_papers`
  produces a parent span with child spans for embed + ANN +
  rerank — verified by
  `TestChildSpans::test_search_papers_full_hierarchy_embed_ann_then_parent`.
  (BM25 child not asserted; v1 `search_papers` is dense-only.)
- [x] Parent span has all 6 documented attributes set (including
  `arxmcp.cache_layer_served`) — verified by
  `TestParentSpan::test_span_tool_call_emits_one_parent_with_required_attributes`.
- [x] `model.revision` on embed child span matches
  `BGE_M3_COMMIT_SHA` — verified by
  `TestChildSpans::test_span_embed_records_model_revision`. (The
  attribute name shipped as `arxmcp.model.revision`; OTel has no
  stable `model.revision` semconv — see D5.)
- [x] OTel endpoint unreachable → server continues operating;
  WARN logged once — verified by
  `TestSetupTracing::test_unreachable_endpoint_logs_warn_does_not_crash`.
- [x] `ARXMCP_OTEL_ENDPOINT` unset → tracing disabled (no-op
  exporter); no error — verified by
  `TestSetupTracing::test_otel_endpoint_unset_disables_tracing_silently`.

## What this milestone does NOT cover

* **Phoenix integration** — E14_S03 (a separate milestone). The
  default endpoint targets Phoenix's OTLP intake, but no UI
  wiring or saved-view shipping happens here.
* **Langfuse orchestrator-side tracing** — E14_S11. The brief's
  Risk note explicitly defers cross-system trace correlation.
* **Sampling configuration** — out of scope per the brief; all
  spans are exported in v1. Sampling lands in Tier-6.
* **`Mcp-Session-Id` redaction at export** — the security note
  pushes operators to keep the default endpoint loopback-only;
  custom span processors that redact the attribute before export
  are an operator concern, not a server concern.

## Metric + span family inventory after E14_S02

Spans now emitted:

* `mcp.tool_call{tool, session_id, agent_role, corpus_version, k, cache_layer_served}` (parent)
* `arxmcp.embed{gen_ai.request.model, arxmcp.model.revision}` (child)
* `arxmcp.ann{arxmcp.k}` (child)
* `arxmcp.bm25{arxmcp.k}` (forward-compat, no caller in v1)
* `arxmcp.rerank{gen_ai.request.model, arxmcp.model.revision}` (child)
* `arxmcp.summarize` (forward-compat, permanently no caller per note 07)

Metric families from prior milestones unchanged; the existing
Prometheus surface and this span surface are now both populated
from the same `_wrap_with_observability` chokepoint.
