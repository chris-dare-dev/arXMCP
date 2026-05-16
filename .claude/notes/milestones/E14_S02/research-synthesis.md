# E14_S02 — Research synthesis (orchestrator-merged)

**Sources:** [research-brief-1.md](research-brief-1.md) (in-codebase, 385 LOC) +
[research-brief-2.md](research-brief-2.md) (external + OTel API, 347 LOC).

The two researchers converged on every load-bearing decision. The
synthesis below captures the merged scope, decisions (D1–D12), and
the forced cross-file changes the implementer must touch.

---

## 1. Headline findings

1. **Pre-existing OTel surface: zero.** No imports, no deps, no
   tracer-provider setup. Greenfield within
   `server/observability/` (a 2-file package landed by E14_S01).
2. **`_scan_unknown_arxmcp_env_vars` is load-bearing.** The startup
   validator at `server/main.py:232-253` rejects any undeclared
   `ARXMCP_*` env var; **`server/config.py::Config` MUST add an
   `otel_endpoint: str | None = None` field** before
   `ARXMCP_OTEL_ENDPOINT` can be set. Skipping this one-line edit
   blocks the entire milestone.
3. **`_wrap_with_metrics` is the natural composition point** for
   the parent span. Both researchers recommend extending the existing
   `server/tools.py` wrapper rather than introducing a second
   wrapper or per-handler decorators. The wrapper already uses
   `functools.wraps` (preserves FastMCP signature introspection)
   and already has the `try/finally` shape we need for span
   end-on-error.
4. **`session_id` does NOT currently reach handler code.**
   `SessionCapMiddleware` reads `Mcp-Session-Id` and consumes it at
   the middleware layer; handlers see only their JSON-RPC args.
   The cleanest plumbing is a **`ContextVar` set by a thin
   middleware**, read by `span_tool_call()`. ~30 LOC.
5. **OTel `ProxyTracer` is the right "tracing disabled" idiom.**
   Per Brief 2 §2.5: if `set_tracer_provider()` is never called,
   every `tracer.start_as_current_span(...)` takes the no-op fast
   path. Do NOT register a `NoOpTracerProvider` — that allocates
   infrastructure for nothing.
6. **OTLP/gRPC on 4317 is correct.** Brief's
   `http://localhost:4317` is the SDK's literal default for the
   gRPC exporter (the `http://` scheme decorates `insecure=True`).
   Phoenix consumes OTLP/gRPC natively on 4317. The constitution
   note 08 says `4318` (HTTP) which is wrong; the constitution
   note must be updated in lockstep with this milestone.
7. **AsyncIO context propagation is automatic.** `opentelemetry.context`
   uses `contextvars.ContextVar`, which propagates across `await`
   boundaries without manual `context.attach`/`detach`. The only
   gotcha is `asyncio.create_task` which captures context at
   creation; no current code path inside `_wrap_with_metrics` uses
   `create_task` inside the span.
8. **InMemorySpanExporter + SimpleSpanProcessor is the canonical
   test fixture.** Brief 2 §2.7. One module-scoped fixture +
   `exporter.clear()` between tests; do NOT re-instantiate the
   provider (`set_tracer_provider` warns-and-no-ops on second
   call in a process).
9. **Cache-layer enum drift between brief and constitution.**
   Note 08 says `exact|semantic|rerank|miss`; the brief says
   `tier1|tier3|miss`; the Prometheus surface already uses
   `tier="1"|"2"|"3"`. Resolution below (D6).
10. **`docs/observability/tracing.md` violates the project
    doc-layout rule.** Per CLAUDE.md §1 only operator-facing docs
    linked from the root README live under `docs/`. Tracing
    config is operator-internal. Resolution: ship at
    `.claude/docs/observability-tracing.md`.
11. **`_agent_role` would bump TOOL_SCHEMA_VERSION** if added as a
    first-class JSON-Schema property on every tool. The brief
    says "documented in the tool schema but not required" which
    we interpret as "the attribute name is documented" not "a
    JSON-Schema property must exist." Resolution below (D7).
12. **Summarizer span is forward-compat only.** Note 07 lines
    236-244 permanently dropped the in-server summarizer; the v1
    `search_papers` handler is dense-only (no BM25, no Haiku).
    Ship `span_bm25` and `span_summarize` helpers as no-op-safe
    helpers; pin the AC test to "embed + ANN + rerank" — the
    actual emitted set for the v1 dense pipeline.

---

## 2. Decisions

### D1. Wrap point — extend `_wrap_with_metrics`

Rename `_wrap_with_metrics` → `_wrap_with_observability` (single
chokepoint that emits BOTH Prometheus metrics AND an OTel span per
tool call). The body becomes:

```python
def _wrap_with_observability(tool_name: str, handler: Any) -> Any:
    @functools.wraps(handler)
    async def _instrumented(*args: Any, **kwargs: Any) -> Any:
        REQUEST_INFLIGHT.labels(tool=tool_name).inc()
        t0 = time.perf_counter()
        status = "error"
        result: Any = None
        # Start parent span — NoOpTracer fast-path if tracing
        # disabled (D2). session_id is read from ContextVar (D3).
        with span_tool_call(
            tool_name,
            session_id=current_session_id.get(None),
            agent_role=current_agent_role.get(None),
        ) as span:
            try:
                result = await handler(*args, **kwargs)
                status = "ok"
                return result
            finally:
                # ... existing metric increments
                if span is not None:  # span_tool_call may yield None when disabled
                    span.set_attribute("arxmcp.cache_layer_served",
                                       current_cache_layer.get("miss"))
```

`tests/test_server_metrics.py` references the old name in exactly
two places — update both. No external callers (`_wrap_with_metrics`
is module-private).

### D2. `setup_tracing()` shape — Brief 2 §3.2

```python
def setup_tracing(config: Config) -> None:
    if not config.otel_endpoint:
        logger.info("tracing.disabled.no_endpoint")
        return  # ProxyTracer → NoOpTracer fast-path
    if not _probe_endpoint(config.otel_endpoint, timeout_s=1.0):
        logger.warning(
            "tracing.endpoint_unreachable; will retry on first export",
            extra={"endpoint": config.otel_endpoint},
        )
        # Fall through — register exporter anyway so traces flow
        # when Phoenix comes up mid-process.
    resource = Resource.create({
        "service.name": "arxmcp-server",
        "service.version": "0.1.0",  # bump when project versions
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=config.otel_endpoint, insecure=True)
        )
    )
    trace.set_tracer_provider(provider)
    logger.info(
        "tracing.enabled", extra={"endpoint": config.otel_endpoint}
    )
```

Called from `server/main.py::create_app` lifespan factory BEFORE
`Resources.startup()` so embedder/reranker warm-up spans are also
traced. `shutdown_tracing()` (force-flush) runs AFTER
`resources.shutdown()` returns.

### D3. Session-id + agent-role plumbing — ContextVar + middleware

`server/observability/tracing.py` exposes three ContextVars:

```python
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)
current_agent_role: ContextVar[str | None] = ContextVar("current_agent_role", default=None)
current_cache_layer: ContextVar[str] = ContextVar("current_cache_layer", default="miss")
```

A new pure-ASGI middleware `TracingContextMiddleware` (pattern
matches `BodySizeCapMiddleware`, NOT `BaseHTTPMiddleware` — the
project ban from E06_S01 F1):

```python
async def __call__(self, scope, receive, send):
    if scope["type"] != "http":
        return await self.app(scope, receive, send)
    headers = {k.decode(): v.decode() for k, v in scope["headers"]}
    sid_token = current_session_id.set(headers.get("mcp-session-id"))
    role_token = current_agent_role.set(headers.get("arxmcp-agent-role"))
    cache_token = current_cache_layer.set("miss")
    try:
        return await self.app(scope, receive, send)
    finally:
        current_session_id.reset(sid_token)
        current_agent_role.reset(role_token)
        current_cache_layer.reset(cache_token)
```

Handlers update `current_cache_layer` when a cache hit is detected:
`current_cache_layer.set("tier1")` (or `"tier2"`/`"tier3"`).
The wrapper reads it just-in-time in the `finally` block so the
parent-span attribute reflects the actual served path.

### D4. Child spans — `span_embed`, `span_rerank`, `span_ann`, `span_bm25`, `span_summarize`

All five helpers are thin `@contextmanager` wrappers over
`tracer.start_as_current_span(name)`. Names:

| helper | span name | attributes |
|---|---|---|
| `span_embed` | `arxmcp.embed` | `gen_ai.request.model="bge-m3"`, `arxmcp.model.revision=<SHA>` |
| `span_ann` | `arxmcp.ann` | `arxmcp.k=<k>` (passed by handler) |
| `span_bm25` | `arxmcp.bm25` | `arxmcp.k=<k>` |
| `span_rerank` | `arxmcp.rerank` | `gen_ai.request.model="bge-reranker-v2-m3"`, `arxmcp.model.revision=<SHA>` |
| `span_summarize` | `arxmcp.summarize` | reserved (no caller in v1) |

Wrap points (Brief 1 §1.7):

- `span_embed` — inside `server/query_encoder.py::_encode_query_sync`
  around the `with torch.no_grad(): output = model(**encoded)` block.
- `span_ann` — inside `server/handlers/search.py` around the
  `r.chunks_table.search(query_vec, ...).limit(k).to_arrow()` call.
- `span_rerank` — inside `server/retrieval/rerank.py::_rerank_sync`
  around the `model(**inputs).logits` forward pass.

### D5. Attribute namespace — `mcp.*` + `arxmcp.*` + selective semconv

Per Brief 2 §2.3:

| attribute | namespace | rationale |
|---|---|---|
| `mcp.session_id` | `mcp.*` | MCP protocol identifier |
| `mcp.tool_name` | `mcp.*` | Same |
| `arxmcp.cache_layer_served` | `arxmcp.*` | project-specific |
| `arxmcp.corpus_version` | `arxmcp.*` | project-specific |
| `arxmcp.k` | `arxmcp.*` | project-specific |
| `arxmcp.agent_role` | `arxmcp.*` | project-specific |
| `gen_ai.request.model` | OTel GenAI semconv (experimental) | model name on embed/rerank child |
| `arxmcp.model.revision` | `arxmcp.*` | no semconv equivalent for commit SHA |

Don't try to be pure-semconv — GenAI is still "Development"-stability.

### D6. Cache-layer enum — `tier1|tier2|tier3|miss`

Resolution of the constitution-vs-brief drift (finding 9):

- Note 08 says `exact|semantic|rerank|miss` (legacy naming from
  pre-3-tier-cache era).
- Brief says `tier1|tier3|miss` (incomplete enumeration; ignores
  `tier2`).
- Prometheus surface `server/metrics.py::CACHE_HITS_COUNTER` uses
  labels `tier=1|2|3` (numeric tier as string).

Adopted enumeration on the OTel attribute:
**`tier1 | tier2 | tier3 | miss`** (string-typed, matches
Prometheus + brief). This requires:

- Updating `.claude/notes/08-security-observability-ops.md` to the
  new enum (Forced cross-file change, §3).
- Note in `.claude/docs/observability-tracing.md` mapping the
  enum to the cache implementation.

### D7. `_agent_role` — header, NOT JSON-Schema property

Brief says "documented in the tool schema but not required."
Interpretation: the *attribute is documented*, NOT *a JSON-Schema
property exists on every tool*. Adding `_agent_role` as a property
on all 7 tools bumps `TOOL_SCHEMA_VERSION` (E06_S06's byte-
stability hash) and invalidates BP1 prompt-cache across every
existing agent prefix (`.claude/notes/07-multi-agent-caching.md`
Property 1).

**Resolution:**

- Operator sends `Arxmcp-Agent-Role: sketcher` (or `tactician` /
  `fixer` / `autoformalizer`) as an HTTP request header.
- `TracingContextMiddleware` reads it into `current_agent_role`
  ContextVar.
- `span_tool_call` sets `arxmcp.agent_role` from the ContextVar.
- Documented in `.claude/docs/observability-tracing.md`.
- TOOL_SCHEMA_VERSION stays at 6. EXPECTED_TOOL_SCHEMA_SHA256 NOT
  re-pinned.

This is a deliberate deviation from the brief wording; rationale
recorded in implementation-summary §"Drift from brief".

### D8. Test surface — `tests/test_tracing.py`

5 acceptance-criteria tests + 4 regression guards:

```
TestParentSpan
  test_search_papers_emits_parent_span_with_embed_and_ann_children
  test_parent_span_has_all_six_required_attributes
  test_parent_span_records_error_status_on_handler_raise
TestChildSpans
  test_embed_child_span_carries_bge_m3_commit_sha
  test_rerank_child_span_carries_reranker_commit_sha
TestSetupTracing
  test_otel_endpoint_unset_disables_tracing_silently
  test_otel_endpoint_unreachable_logs_warn_does_not_crash
  test_setup_tracing_idempotent_on_re_call  # set_tracer_provider warns-no-ops
TestContextVarPlumbing
  test_session_id_header_flows_through_to_parent_span
  test_agent_role_header_flows_through_to_parent_span
  test_cache_layer_handler_update_reflects_in_parent_span
```

Pattern: module-scoped `InMemorySpanExporter` fixture +
`exporter.clear()` between tests (Brief 2 §2.7). The
`test_otel_endpoint_unreachable_logs_warn_does_not_crash` test
asserts via `caplog.records` filter on the WARN message.

### D9. Lazy imports inside hot loops

`opentelemetry.trace.get_tracer(...)` and
`tracer.start_as_current_span` calls are O(1) on the no-op path,
but Brief 1 §1.6 notes the lazy-import discipline applied to
embed/rerank instrumentation in E14_S01. Apply the same to
`server.observability.tracing` from `query_encoder.py` and
`rerank.py` — both modules already lazy-import their metric
families. No top-level OTel imports in the hot path.

### D10. Probe pattern for unreachable endpoint

`_probe_endpoint(endpoint: str, timeout_s: float) -> bool`:

```python
def _probe_endpoint(endpoint: str, timeout_s: float = 1.0) -> bool:
    from urllib.parse import urlparse  # noqa: PLC0415
    import socket  # noqa: PLC0415
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4317
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except (OSError, ConnectionRefusedError):
        return False
```

1-second TCP connect. Probe runs ONCE at startup. Failure logs a
single WARN; the exporter is still registered so traces flow when
Phoenix wakes mid-process. Closes the "WARN logged once" AC.

### D11. Documentation placement

Ship at `.claude/docs/observability-tracing.md` (NOT
`docs/observability/tracing.md` as the brief says). Per CLAUDE.md
§1 only operator-facing docs linked from the root README live
under `docs/` — tracing config is operator-internal.

Content:

- Architecture diagram (1 paragraph + ASCII)
- Attribute catalog (D5 table)
- Cache-layer enum mapping (D6)
- `Arxmcp-Agent-Role` header documentation (D7)
- OTLP/gRPC default port + Phoenix integration pointer
- Security note: localhost-only default (per brief Risk note —
  session_ids in spans must not be forwarded to external SaaS)

### D12. `pyproject.toml` dep additions

```toml
"opentelemetry-api>=1.41,<2",
"opentelemetry-sdk>=1.41,<2",
"opentelemetry-exporter-otlp-proto-grpc>=1.41,<2",
```

Plus regenerate `uv.lock` via `uv lock` (single local-file
mutation).

---

## 3. Forced cross-file changes

| File | Change | Decision |
|---|---|---|
| `server/observability/tracing.py` (NEW) | All tracing helpers + ContextVars | D1-D5, D9, D10 |
| `server/observability/__init__.py` | Add tracing-module references to docstring | D1 |
| `server/config.py` (MODIFY) | Add `otel_endpoint: str \| None = None` field; section: `# --- Observability ---` | finding 2 |
| `server/main.py` (MODIFY) | Call `setup_tracing(config)` in lifespan before `Resources.startup`; add `TracingContextMiddleware` to ASGI stack | D2, D3 |
| `server/middleware.py` (MODIFY) | NEW `TracingContextMiddleware` (pure-ASGI; near `BodySizeCapMiddleware`) | D3 |
| `server/tools.py` (MODIFY) | Rename `_wrap_with_metrics` → `_wrap_with_observability`; wrap handler in `span_tool_call` | D1 |
| `server/query_encoder.py` (MODIFY) | Wrap `_encode_query_sync` forward pass in `span_embed` | D4 |
| `server/retrieval/rerank.py` (MODIFY) | Wrap `_rerank_sync` forward pass in `span_rerank` | D4 |
| `server/handlers/search.py` (MODIFY) | Wrap LanceDB ANN call in `span_ann`; update `current_cache_layer.set(...)` on tier1/tier3 hit | D4, D6 |
| `pyproject.toml` (MODIFY) | Add OTel deps | D12 |
| `uv.lock` (MODIFY) | Re-pin | D12 |
| `tests/test_tracing.py` (NEW) | 11 tests covering D8 surface | D8 |
| `tests/test_server_metrics.py` (MODIFY) | Update `_wrap_with_metrics` references to `_wrap_with_observability` (2 sites) | D1 |
| `.claude/docs/observability-tracing.md` (NEW) | Operator-internal doc | D11 |
| `.claude/notes/08-security-observability-ops.md` (MODIFY) | Update OTLP port (4318→4317), cache-enum (`exact|...` → `tier1|tier2|tier3|miss`) | D6, finding 6 |

---

## 4. Implementation order

1. `pyproject.toml` deps + `uv lock`. Tests cannot collect without
   the OTel imports resolving.
2. `server/config.py` add `otel_endpoint`. Required by the
   env-scan validator.
3. `server/observability/tracing.py` — write the full file
   (`setup_tracing`, ContextVars, span helpers, `_probe_endpoint`).
4. `server/middleware.py` `TracingContextMiddleware`.
5. `server/main.py` — wire `setup_tracing` into lifespan + add
   middleware.
6. `server/tools.py` rename + extend the wrapper.
7. `server/query_encoder.py`, `server/retrieval/rerank.py`,
   `server/handlers/search.py` — child-span wrap points + cache-
   layer set.
8. `tests/test_tracing.py` — write the 11 tests.
9. `tests/test_server_metrics.py` — update the two
   `_wrap_with_metrics` references.
10. `.claude/docs/observability-tracing.md` + note 08 update.
11. `make test` (or `uv run pytest`) clean + `ruff check . `
    clean.
12. Implementation-summary write-up.

---

## 5. Open questions resolved at synthesis time

All seven open questions from Brief 1 + three from Brief 2 are
resolved by the decisions above. None require user input. The
implementer proceeds.

---

## 6. External writes required

**Zero beyond local `main` commits.** Specifically:

- `pyproject.toml` + `uv.lock`: local edits + `uv lock`.
- 3 git commits (feat + rect + chore) per the project
  3-commit-per-milestone pattern.
- `git push origin main` per user authorization (per-event, per
  CLAUDE.md §4.4).

No PyPI uploads. No PR creation. No infra mutation. No external
API calls. The Phoenix container is an OPTIONAL operator-managed
service; not bundled with this milestone.

---

## 7. Risk register (carry into Phase 3)

- **Schema-hash drift.** D1 renames `_wrap_with_metrics` —
  E06_S06's `EXPECTED_TOOL_SCHEMA_SHA256` is the tool surface
  hash, NOT the wrapper-function hash, so D1 does NOT touch it.
  D7 (header-based `_agent_role`) keeps `TOOL_SCHEMA_VERSION` at
  6. Adversary critic should verify this is still pinned.
- **ContextVar isolation in tests.** `set_tracer_provider` is a
  process-global side-effect. Tests must be module-scoped + use
  `exporter.clear()` per Brief 2 §2.7.
- **`_probe_endpoint` startup cost.** 1-second TCP connect on
  every cold start. Documented; acceptable.
- **gRPC pinning vs HTTP fallback.** D12 pins gRPC; if Phoenix
  later defaults to HTTP, the implementer adds the HTTP exporter
  in a follow-up. Out of scope for E14_S02.
- **`_agent_role` brief drift.** D7 deviates from the brief's
  literal wording ("documented in the tool schema") on a
  judgment call — schema-hash stability beats literal
  compliance. Adversary may flag; rationale documented.
