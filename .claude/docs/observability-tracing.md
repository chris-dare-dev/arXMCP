# OpenTelemetry tracing (E14_S02)

The MCP server emits one parent OTel span per JSON-RPC tool call
with child spans for embed / ANN / rerank. This file is the
operator's reference for enabling tracing, the attribute catalog,
and the cache-layer enum that ties trace spans to Prometheus
metric labels.

---

## Enabling tracing

Tracing is **disabled by default**. Set `ARXMCP_OTEL_ENDPOINT` to
enable it:

```bash
export ARXMCP_OTEL_ENDPOINT="http://127.0.0.1:4317"
make up
```

When unset, `setup_tracing` returns without registering a
`TracerProvider`. Every `tracer.start_as_current_span(...)` then
takes the OTel SDK's `ProxyTracer` → `NoOpTracer` fast path with
zero allocation; the `_wrap_with_observability` wrapper still
emits Prometheus metrics but no spans.

### Endpoint format

`ARXMCP_OTEL_ENDPOINT` is an OTLP/gRPC URL. The default port is
**4317** (the OTel spec's gRPC default; Phoenix's OTLP intake
matches). The `http://` scheme is decorative — the gRPC exporter
uses it only to decide `insecure_channel` vs `secure_channel`. To
target a TLS-secured collector, use `https://collector.example:4317`
and the gRPC exporter switches to `secure_channel` automatically.

### Phoenix locally

```bash
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest
export ARXMCP_OTEL_ENDPOINT="http://127.0.0.1:4317"
make up
```

Spans appear at `http://127.0.0.1:6006`. Phoenix's
retrieval-quality dashboards are most useful once the
`arxmcp.cache_layer_served` + `arxmcp.k` attributes are populated
(see the attribute catalog below).

---

## Attribute catalog

### Parent span — `mcp.tool_call`

| Attribute | Type | Source | Always set? |
|---|---|---|---|
| `mcp.tool_name` | string | tool registration | yes |
| `mcp.session_id` | string | `Mcp-Session-Id` request header | only when header present |
| `arxmcp.agent_role` | string | `Arxmcp-Agent-Role` request header (see below) | only when header present |
| `arxmcp.corpus_version` | int | the corpus currently bound (set at startup; changes on a #207 rebind) | yes when Resources warm |
| `arxmcp.k` | int | tool kwargs `k=` | yes when the tool accepts `k` |
| `arxmcp.cache_layer_served` | string enum | handler set via `set_cache_layer(...)` | yes (defaults to `"miss"`) |

### Child spans

| Span name | Attributes | Wrap point |
|---|---|---|
| `arxmcp.embed` | `gen_ai.request.model="bge-m3"`, `arxmcp.model.revision=<sha>` | `server/query_encoder.py::_encode_query_sync` |
| `arxmcp.ann` | `arxmcp.k=<k>` | `server/handlers/search.py` (LanceDB ANN call) |
| `arxmcp.bm25` | `arxmcp.k=<k>` | reserved — v1 `search_papers` is dense-only |
| `arxmcp.rerank` | `gen_ai.request.model="bge-reranker-v2-m3"`, `arxmcp.model.revision=<sha>` | `server/retrieval/rerank.py::_rerank_sync` |
| `arxmcp.summarize` | — | reserved — note 07 lines 236-244 permanently dropped the in-server summarizer |

### `arxmcp.cache_layer_served` enum

The OTel attribute uses the same string-typed enum as the
Prometheus `tier=` label on `arxmcp_cache_hits_total`:

| Value | Meaning |
|---|---|
| `tier1` | SQLite exact-match cache hit |
| `tier2` | FAISS cosine ≥0.97 semantic-match hit |
| `tier3` | Rerank-set LRU hit (cross-encoder cache) |
| `miss` | All three tiers missed; full retrieval pipeline ran |

(The `08-security-observability-ops.md` legacy
`exact|semantic|rerank|miss` naming was renamed in lockstep with
E14_S02. The Prometheus-aligned form is the canonical one.)

---

## `Arxmcp-Agent-Role` header

The orchestrator-side agent identity (sketcher / autoformalizer /
tactician / fixer) is passed as an HTTP request header rather
than a JSON-Schema property on every tool, because:

- Adding a JSON-Schema property to all 7 tools would bump
  `TOOL_SCHEMA_VERSION` and invalidate the BP1 prompt-cache for
  every existing agent prefix (per
  `.claude/notes/07-multi-agent-caching.md` Property 1).
- The brief's wording ("documented in the tool schema but not
  required") is interpreted as "the attribute is documented" not
  "a JSON-Schema property must exist."

The orchestrator sets the header per request:

```python
import httpx

resp = httpx.post(
    "http://127.0.0.1:7733/mcp",
    json={"jsonrpc": "2.0", "method": "tools/call", ...},
    headers={
        "Mcp-Session-Id": session_id,
        "Arxmcp-Agent-Role": "sketcher",  # or tactician/fixer/autoformalizer
    },
)
```

`TracingContextMiddleware` reads both headers and copies them
into the `current_session_id` / `current_agent_role` ContextVars;
`span_tool_call` reads from the ContextVars and sets the
attributes.

---

## Security note

**Spans carry `mcp.session_id`. Forwarding spans to an external
SaaS collector would leak session IDs.** The documented default
endpoint is an in-process or sidecar Phoenix container —
`http://127.0.0.1:4317`. If you need to send spans across a
network, audit the path for SaaS integrations and either:

1. Strip `mcp.session_id` at a span processor (write a custom
   `SpanProcessor` that drops the attribute before export), or
2. Use a self-hosted collector that does the redaction
   server-side, or
3. Disable tracing entirely (`unset ARXMCP_OTEL_ENDPOINT`).

The brief's risk note pins this requirement; the v1
implementation enforces it through the default endpoint, not via
code-level redaction.

---

## Failure modes

### Endpoint unreachable at startup

A 1-second TCP probe runs at `setup_tracing(config)` time. If the
endpoint is down, the server logs a single WARN and **still
registers the exporter** — when Phoenix comes up mid-process,
traces flow automatically. The probe never raises.

### Endpoint goes down mid-run

The `BatchSpanProcessor` worker buffers spans up to
`max_queue_size=2048` (OTel SDK default). When the queue fills,
the OLDEST spans are dropped silently. The exporter itself logs
retries via `opentelemetry.sdk.trace.export` at WARN/ERROR.

### Re-calling `setup_tracing`

Idempotent: a second call in the same process logs INFO and
returns without re-registering. The OTel SDK itself warns-and-no-
ops on a second `trace.set_tracer_provider(...)`; we short-
circuit before reaching that point so test fixtures that share a
provider across tests stay clean.

---

## Disabling tracing per-test

Tests that need a clean tracing slate use the module-scoped
`InMemorySpanExporter` fixture in
`tests/test_tracing.py::span_exporter` plus `exporter.clear()`
between tests. See that file for the canonical pattern.

The module-level `tracing_mod._provider_installed` guard can be
flipped with `reset_tracing_for_tests()` when a test specifically
needs to exercise the disabled path.

---

## See also

- `.claude/notes/08-security-observability-ops.md` §Tracing —
  load-bearing requirements.
- `server/observability/tracing.py` — implementation.
- `server/middleware.py::TracingContextMiddleware` —
  header-to-ContextVar plumbing.
- `tests/test_tracing.py` — 22 tests covering the surface.
