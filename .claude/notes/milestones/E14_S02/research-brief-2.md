# E14_S02 — Research Brief 2 (External Context + OTel API Surface)

## 1. In-codebase context (light pass)

**Pre-existing OTel surface in the codebase: effectively zero.**

`grep -rn "opentelemetry\|otel\|tracing" server/ pyproject.toml .claude/notes`
finds three relevant non-test hits:

- `.claude/notes/08-security-observability-ops.md` §"Tracing" — the
  authoritative requirements. **Quoted** (lines 146-158):
  > "OpenTelemetry traces exported to a configurable endpoint
  > (`ARXMCP_OTEL_ENDPOINT`). One span per JSON-RPC request; child
  > spans for embed, vector-search, rerank, summarize. Span attributes
  > include: `mcp.session_id`, `mcp.tool_name`,
  > `arxmcp.cache_layer_served` (`exact` / `semantic` / `rerank` /
  > `miss`), `arxmcp.corpus_version`, `arxmcp.k`, `arxmcp.agent_role`."
  Note the cache-layer enum here uses `exact|semantic|rerank|miss`,
  while the brief uses `tier1|tier3|miss`. **Drift to resolve in
  Implement.** Recommend the brief's `tierN|miss` form; it matches
  the 3-tier cache in `server/cache.py`.
- `server/main.py` line 238 docstring already mentions
  `ARXMCP_OTEL_ENDPOINT` as "documented-but-unimplemented" — the env-var
  was reserved during E06_S01.
- `server/observability/` exists, contains only `metrics.py`. New
  `tracing.py` slots in beside it cleanly.

No OTel deps in `pyproject.toml`. No `opentelemetry-*` imports anywhere.
This is greenfield within an already-laid-out directory.

Handler files that need wrapping: `server/handlers/{search,chunk,
citations,definitions,equation,lemma,paper}.py` — 7 files matching the
7-tool surface.

---

## 2. External sources (the bulk)

### 2.1 OpenTelemetry Python SDK — version + dep matrix

Per PyPI (verified 2026-04-24 release):
**`opentelemetry-exporter-otlp` 1.41.1**, Python ≥3.9, Apache-2.0, Prod/Stable.
The `opentelemetry-api` and `opentelemetry-sdk` packages release in
lockstep at the same `1.x` minor and have done so since the 1.0 cut.

PyPI says verbatim of `opentelemetry-exporter-otlp`:
> "installs all supported OpenTelemetry Collector Exporters... users
> should install the specific package once they've determined their
> preferred serialization and protocol method"

**Minimum dep set for E14_S02:**

```toml
"opentelemetry-api>=1.41,<2",
"opentelemetry-sdk>=1.41,<2",
"opentelemetry-exporter-otlp-proto-grpc>=1.41,<2",
```

Pin to `>=1.41,<2` — the 1.x line is API-stable; 2.x is not yet on the
horizon (the GenAI semconv being marked "Development" suggests further
1.x churn before 2.0). Do **not** pull the umbrella
`opentelemetry-exporter-otlp` — it transitively installs both gRPC and
HTTP exporters and grpcio is already ~5 MB; we want the smaller surface.

### 2.2 OTLP transport: gRPC vs HTTP, port 4317 ambiguity

Per the OTLP spec, verbatim:
> "The default network port for OTLP/gRPC is 4317."
> "The default network port for OTLP/HTTP is 4318."

The brief's `http://localhost:4317` is a **near-typo** but works in
practice: the gRPC exporter accepts URLs with the `http://` scheme and
treats it as "insecure gRPC, no TLS." From the gRPC exporter source
(verified):
> `self._endpoint = endpoint or environ.get(OTEL_EXPORTER_OTLP_ENDPOINT,
> "http://localhost:4317")`

So `http://localhost:4317` IS the SDK's own default for gRPC. The scheme
is decorative — the gRPC client uses it only to decide
`insecure_channel` vs `secure_channel`. Keep the brief's
`ARXMCP_OTEL_ENDPOINT=http://localhost:4317` literally as the default.

**Recommendation: gRPC, not HTTP.** Phoenix's OTLP intake also defaults
to gRPC on 4317 (confirmed below), and gRPC's bidirectional streaming
gives lower export latency. HTTP/protobuf would be the right call only
if we expected to traverse a corporate proxy.

### 2.3 OTel semantic conventions for AI/ML/GenAI

Status (verified at semconv-registry/gen-ai/): **the entire GenAI
section is marked "Development" (experimental).** Key names:

- `gen_ai.request.model` — model name on a request. **Development.**
- `gen_ai.response.model` — model that produced the response. **Development.**
- `gen_ai.operation.name` — e.g. `chat`, `embeddings`. **Development.**
- `gen_ai.system` — **deprecated**, replaced by `gen_ai.provider.name`.

**There is no stable `model.revision` attribute** in OTel semconv —
neither in GenAI nor in the broader registry. The brief's
`model.revision` is a clean, short, project-private name. Adopting
`gen_ai.request.model` for the model name and `arxmcp.model.revision`
for the commit SHA is a defensible split: the model name is semconv,
the SHA is project-specific.

**Recommendation on attribute namespace:**

| Attribute | Namespace | Rationale |
|---|---|---|
| `mcp.session_id` | `mcp.*` | MCP-protocol-level identifier. |
| `mcp.tool_name` | `mcp.*` | Same. The brief uses this; keep it. |
| `arxmcp.cache_layer_served` | `arxmcp.*` | Project-specific cache topology. |
| `arxmcp.corpus_version` | `arxmcp.*` | Project-specific. |
| `arxmcp.k` | `arxmcp.*` | Project-specific. |
| `arxmcp.agent_role` | `arxmcp.*` | Project-specific (Sketcher/Tactician/etc.). |
| `gen_ai.request.model` (embed/rerank child spans) | semconv | Standard name. |
| `arxmcp.model.revision` (embed/rerank child spans) | `arxmcp.*` | No semconv equivalent. |

Don't try to be pure-semconv — GenAI is still experimental and
under-specified for "retrieval pipeline with multiple embedders."
Project-local namespaces are the right call.

### 2.4 Phoenix (Arize) — the default localhost target

Verified at `arize.com/docs/phoenix/self-hosting/configuration`:

> "Accepts traces in OpenTelemetry OTLP format (Protobuf)" on port 4317
> with the env var `PHOENIX_GRPC_PORT` defaulting there. HTTP UI on
> port 6006 via `PHOENIX_PORT`.

So `localhost:4317` is exactly correct for a Phoenix container started
with default ports. No wire-format adapter needed — Phoenix consumes
OTLP/gRPC natively.

### 2.5 No-op exporter pattern — the right idiom

Verified by reading
`opentelemetry-python/.../api/src/opentelemetry/trace/__init__.py`:
when `set_tracer_provider()` has **not** been called, `get_tracer()`
returns a `ProxyTracer` whose `_tracer` property defaults to
`NoOpTracer`. Quoted:
> "if self._real_tracer: return self._real_tracer; if _TRACER_PROVIDER:
> ...; return self._noop_tracer"

**Therefore the right "tracing disabled" pattern is: skip
`set_tracer_provider()` entirely.** Do NOT register a `TracerProvider`
with a no-op exporter — that allocates infra for nothing. Just:

```python
if not config.otel_endpoint:
    logger.info("ARXMCP_OTEL_ENDPOINT unset; tracing disabled")
    return
# else: set up TracerProvider + BatchSpanProcessor + OTLP exporter
```

Every `tracer.start_as_current_span(...)` call in unwrapped code then
takes the `NoOpTracer` fast path — zero allocations, zero attribute
recording. This is **strictly better** than registering a
`NoOpTracerProvider`.

### 2.6 AsyncIO + OTel context propagation

`opentelemetry.context` uses Python's `contextvars.ContextVar`, which
**does** propagate across `await` boundaries automatically (asyncio
copies the current context into each scheduled coroutine). The
documented gotcha is `asyncio.create_task(...)`: it captures the
current context **at creation time** (not at first await), which is
usually what you want but can surprise you if you create the task
inside a span and end the span before the task runs.

For the search pipeline (embed → ANN → BM25 → rerank), all sub-ops are
sequential `await`s under the parent span — context propagation is
automatic and no manual `context.attach` / `context.detach` is needed.

### 2.7 Test harness: `InMemorySpanExporter` + `SimpleSpanProcessor`

Verified API:

```python
# opentelemetry.sdk.trace.export.in_memory_span_exporter
class InMemorySpanExporter:
    def __init__(self) -> None: ...
    def get_finished_spans(self) -> tuple[ReadableSpan, ...]: ...
    def clear(self) -> None: ...

# opentelemetry.sdk.trace.export
class SimpleSpanProcessor:
    def __init__(self, span_exporter, *, meter_provider=None): ...
```

Canonical test fixture:

```python
@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    exporter.clear()
```

**Gotcha:** `set_tracer_provider()` warns-and-no-ops on second call in
a process. Use module-scoped fixtures and reset via `exporter.clear()`,
not by re-instantiating the provider. Tests that need isolation should
each fetch `exporter.get_finished_spans()` and assert their own slice.

### 2.8 Failure mode: endpoint unreachable

**OTLP/gRPC `OTLPSpanExporter` connects lazily on first export, not at
init.** Constructor only validates URL syntax. If the endpoint is down,
the `BatchSpanProcessor` worker will log retries via
`opentelemetry.sdk.trace.export` (Python `logging` at WARN/ERROR) and
**will not crash the host process** — the export queue is drained best-
effort. After the queue overflows (`max_queue_size=2048` default), new
spans are dropped silently.

To meet the brief's "WARN logged once at startup, never crashes":
recommend a non-blocking probe in `setup_tracing()` — a 1-second TCP
connect to the endpoint host:port. If it fails, log WARN once and
**still register the exporter** (so when Phoenix comes up mid-run,
traces flow). Or: just register the exporter, let the SDK's own
retry-logging do the work, and document the behavior. The probe is
cleaner; pick the probe.

### 2.9 MCP spec on tracing

The MCP 2025-06-18 spec (verified) **says nothing** about
`traceparent` headers, W3C Trace Context, or OpenTelemetry context
propagation across JSON-RPC. The spec covers: JSON-RPC 2.0 envelopes,
capability negotiation, lifecycle, consent. Tracing is entirely an
implementation concern.

**Consequence:** the parent span is rooted in the FastAPI request
handler (we own it); there is no inbound `traceparent` to honor or
propagate from the Claude Code client side. If/when the orchestrator
gains its own tracing (E14_S11 Langfuse), we'll need to extract
`traceparent` from a custom MCP-meta header — but that is out of scope
for E14_S02.

---

## 3. Recommendations

### 3.1 `pyproject.toml` adds

```toml
# opentelemetry-{api,sdk}: tracing core for E14_S02. Pinned to the
#   1.x line; 1.41+ has stable GenAI bindings (though the GenAI
#   semconv itself is still "Development"-stability).
"opentelemetry-api>=1.41,<2",
"opentelemetry-sdk>=1.41,<2",
# opentelemetry-exporter-otlp-proto-grpc: gRPC-only exporter; we
#   target Phoenix on localhost:4317. The umbrella ``-exporter-otlp``
#   would also pull the HTTP exporter we don't use.
"opentelemetry-exporter-otlp-proto-grpc>=1.41,<2",
```

### 3.2 `setup_tracing()` shape (~30 lines)

```python
def setup_tracing(config: Config) -> None:
    endpoint = config.otel_endpoint  # ARXMCP_OTEL_ENDPOINT
    if not endpoint:
        logger.info("tracing.disabled.no_endpoint")
        return  # ProxyTracer → NoOpTracer

    # Best-effort probe (1s TCP connect).
    if not _probe_endpoint(endpoint, timeout=1.0):
        logger.warning("tracing.endpoint_unreachable", extra={"endpoint": endpoint})
        # Fall through; register anyway so traces flow when Phoenix wakes.

    resource = Resource.create({
        "service.name": "arxmcp-server",
        "service.version": __version__,
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("tracing.enabled", extra={"endpoint": endpoint})
```

`span_tool_call(name, session_id, **attrs)` is a thin
`contextmanager` over `tracer.start_as_current_span(name)` that sets
the 6 required attributes; `span_embed` / `span_rerank` /
`span_summarize` set `gen_ai.request.model` +
`arxmcp.model.revision` as child spans.

### 3.3 Wiring location

Call `setup_tracing(config)` at the **top** of the lifespan (before
`Resources.startup()`), so the embedder-load + LanceDB-warm spans are
themselves traced. Place an `@asynccontextmanager`-decorated
`traced_request` middleware that wraps each `/mcp` request in a parent
span, then sub-handlers add child spans via the `span_embed` /
`span_rerank` helpers.

### 3.4 Tests

`tests/test_tracing.py` — module-scoped `InMemorySpanExporter` fixture;
one test per acceptance criterion:
1. `test_search_papers_emits_parent_span_with_embed_and_ann_children`.
2. `test_parent_span_has_six_required_attributes`.
3. `test_embed_child_span_carries_bge_m3_commit_sha_as_model_revision`.
4. `test_otel_endpoint_unset_disables_tracing_silently` —
   `setup_tracing(Config(otel_endpoint=None))` returns, no provider
   registered, `trace.get_tracer(...).start_as_current_span(...)` is a
   no-op.
5. `test_otel_endpoint_unreachable_logs_warn_does_not_crash` —
   `caplog` asserts one WARN, app continues.

---

## Open questions

- **Cache-layer enum naming drift.** The constitution
  (`08-security-observability-ops.md`) says `exact|semantic|rerank|miss`;
  the brief says `tier1|tier3|miss`. Recommend the brief — the codebase
  cache is 3-tier — but the constitution note should be updated in
  lockstep with this milestone's PR.
- **`_agent_role` schema documentation.** The brief says "documented in
  the tool schema but not required." Should this go into all 7 tool
  schemas via `tools.py::ALL_TOOLS` (which triggers the
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pin), or kept out-of-band?
  Recommend in-schema with an optional, documented `_agent_role`
  property; bite the schema-hash re-pin once.
- **Span name conventions.** Use `mcp.tool_call` for parent +
  `arxmcp.embed` / `arxmcp.ann` / `arxmcp.bm25` / `arxmcp.rerank` /
  `arxmcp.summarize` for children? Or follow the GenAI semconv
  `gen_ai.operation.name` value (e.g. `embeddings`)? Recommend the
  former (project-local, low-churn).

## External writes the implementation will require

**Zero beyond local `main` commits.** Specifically:
- `pyproject.toml` dep adds (`opentelemetry-{api,sdk,
  exporter-otlp-proto-grpc}`) — local edit.
- `uv lock` regen — local file.
- New `server/observability/tracing.py` + edits to 7 handlers + new
  `tests/test_tracing.py` + `.claude/docs/observability-tracing.md`
  (per the project's doc-placement rule; the brief's path
  `docs/observability/tracing.md` violates the root-`docs/` rule — see
  CLAUDE.md §1).
- No external account creation, no SaaS provisioning, no DNS, no
  GitHub Actions changes. Phoenix is an optional local Docker container
  the operator runs themselves (not in scope for this milestone).
