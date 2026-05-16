# E14_S02 — Research Brief 1 (in-codebase context)

Researcher: in-codebase. Scope: load-bearing repo constraints,
existing wiring, prior decisions. External docs: skipped (researcher 2).

## 1. In-codebase context

### 1.1 Design constitution — load-bearing quotes

`.claude/notes/08-security-observability-ops.md` §Tracing (lines 146-158)
is the entire ground-truth requirement set:

> OpenTelemetry traces exported to a configurable endpoint
> (`ARXMCP_OTEL_ENDPOINT`). One span per JSON-RPC request; child
> spans for embed, vector-search, rerank, summarize. Span attributes
> include:
> - `mcp.session_id`
> - `mcp.tool_name`
> - `arxmcp.cache_layer_served` (`exact` / `semantic` / `rerank` / `miss`)
> - `arxmcp.corpus_version`
> - `arxmcp.k`
> - `arxmcp.agent_role` (passed in tool args by the orchestrator)

Note: the design note uses `exact / semantic / rerank / miss`; the
brief uses `tier1 / tier3 / miss`. Both refer to the same Tier-1 /
Tier-2 / Tier-3 / miss enumeration. The implementer must standardize
to ONE — I recommend `tier1 / tier2 / tier3 / miss` because the
existing Prometheus surface (`server/metrics.py::TIER_1`, `TIER_2`,
`TIER_3`) already uses those strings as the `layer` label. Reusing
them prevents a Phoenix/Grafana correlation gap.

`.claude/notes/06-mcp-server-design.md` line 313:
> `GET /metrics` — Prometheus exposition format. See [08-security-observability-ops.md].

— note `/metrics` is the only observability endpoint that note
mentions. There is NO explicit "JSON-RPC span boundary" guidance in
note 06; the boundary is implicit in §"Server lifecycle" (startup →
yield → shutdown) and the determinism contract (one `result` per
`tools/call`).

`.claude/notes/07-multi-agent-caching.md` lines 38-49 (Property 1 —
byte-stable tool defs):
> A casual edit to a tool description blows every sub-agent's cache.

**Tracing must NOT touch the wire `tools/list` response or
`structuredContent`.** OTel `traceparent` is a request header /
internal context concern; spans live in the OTLP export channel.
Adding a `trace_id` field to `structuredContent` would invalidate
the E06_S06 byte-stability hash (`EXPECTED_TOOL_SCHEMA_SHA256`). Do
not do it.

Note 07 also makes `_agent_role` cost explicit: adding it as a
**first-class** parameter on every tool's input schema bumps the
rendered `tools/list` bytes → bumps `TOOL_SCHEMA_VERSION`
(`server/tools.py:73`) → invalidates BP1 across every existing
agent prefix. Schema bump is acceptable when justified, but should
be a deliberate one-shot rather than a per-milestone drift.
**Recommendation:** make `_agent_role` a `Mcp-Session-Id`-adjacent
HTTP header (e.g. `Arxmcp-Agent-Role`) or read it from the JSON-RPC
body via the same middleware-level inspection `SessionCapMiddleware`
already does (`server/middleware.py:842-857`). Avoid bumping
TOOL_SCHEMA_VERSION for an optional attribute the brief says is
"documented in the tool schema but not required."

### 1.2 Server lifespan + middleware structure

`server/main.py:262-316` — the lifespan factory:

1. `Resources.startup(config)` (line 283) — builds the embedder,
   reranker, semaphores, LanceDB handle, **and the cache singleton**
   (set_cache is called inside Resources.startup).
2. `set_resources(resources)` (line 296) — registers the global
   handler-accessible singleton.
3. `async with mcp_server.session_manager.run(): yield` (line 304) —
   FastMCP's SSE/JSON-RPC dispatch opens here.
4. Shutdown: `asyncio.wait_for(resources.shutdown(), timeout=30.0)`.

**Where `setup_tracing()` belongs:** BEFORE step 1 (or between 1
and 2). The TracerProvider has to be globally installed before any
component that emits spans runs. Specifically it must be installed
before `mcp_server.session_manager.run()` because the very first
`tools/call` we want to trace happens immediately after that point.
Symmetrically, `shutdown_tracing()` (force-flush the BatchSpanProcessor)
must run AFTER `resources.shutdown()` returns so in-flight spans get
exported before tini delivers SIGTERM.

`server/main.py:232-253` has a `_scan_unknown_arxmcp_env_vars`
validator that **explicitly rejects undeclared `ARXMCP_*`**, with the
docstring naming `ARXMCP_OTEL_ENDPOINT` as the canonical example of
a documented-but-not-implemented var that silently slips through
pydantic-settings. Landing `ARXMCP_OTEL_ENDPOINT` MUST declare it on
`server/config.py::Config` (line 179 §Observability is the obvious
home) or the scan rejects it at startup. **This is a one-line edit
the implementer cannot skip.**

### 1.3 Tool-call wrap point — `_wrap_with_metrics`

`server/tools.py:393-457` defines `_wrap_with_metrics(tool_name,
handler)` — the **single chokepoint** where every tool handler is
wrapped at registration time (line 498). The wrapper:

- increments `REQUEST_INFLIGHT.labels(tool=tool_name)` on entry,
  decrements in `try/finally`;
- times wall-clock with `time.perf_counter()`;
- records `REQUEST_COUNTER`, `REQUEST_LATENCY`, `RESULT_BYTES`.

**This is exactly the right place to add tracing.** Wrap the
metrics-wrapped handler in a span context manager (or interleave
metrics + span in one closure). The pattern:

```python
@functools.wraps(handler)
async def _traced_and_tracked(*args, **kwargs):
    with span_tool_call(tool_name) as span:
        # the existing metrics try/finally body
        ...
```

**Composability:** the metrics wrapper uses `functools.wraps` so
FastMCP's `inspect.signature` introspection still sees the original
handler signature (test pinned at
`tests/test_server_metrics.py:212-224`). Span wrapping must also use
`functools.wraps`. Two ways to compose: (a) one combined
`_wrap_with_metrics_and_tracing` closure, or (b) `_wrap_with_tracing(_wrap_with_metrics(handler))`.
**I recommend (a)** — fewer closure frames, single place to record
`cache_layer_served` once both inner and outer telemetry have run.
The latency timer can be reused for the span end too.

### 1.4 Session-id plumbing — does NOT flow to handlers today

`server/middleware.py:801-828` shows where `mcp-session-id` is read
from headers — inside `SessionCapMiddleware`. **The session id is
consumed at the middleware layer and never passed to the handler
function.** Handler signatures in `server/handlers/*.py` accept ONLY
the tool's JSON-RPC arguments (e.g.
`handle_search_papers(query, level, k, filters, cursor)`).

There is no FastMCP `Context` object threaded through the handlers
today (no `from mcp.server.fastmcp import Context` import anywhere in
`server/handlers/`).

**This is the single biggest design knob the implementer faces.**
Three options, in increasing intrusiveness:

1. **ContextVar.** `server/observability/tracing.py` exposes a
   `current_session_id: ContextVar[str | None]`. A new ASGI
   middleware (or an extension of `SessionCapMiddleware`) sets it
   on each request; `span_tool_call()` reads it. This is the
   smallest blast-radius — zero handler-signature changes. Works
   cleanly with asyncio (`ContextVar` propagates across `await`).
2. **FastMCP `Context` parameter.** Add `ctx: Context` to every
   handler signature; FastMCP injects it automatically by type
   annotation. Cleaner long-term but it (a) modifies all 7 handlers,
   (b) bumps the rendered `tools/list` only if the param is
   non-internal (FastMCP convention is `ctx`/`Context`-typed args
   are NOT exposed in the schema — verify).
3. **Read from `scope` inside an ASGI wrapper around FastMCP.**
   Brittle; FastMCP's `streamable_http_app()` is its own ASGI sub-app
   so the scope you see at the FastAPI layer is the parent scope, not
   per-tools-call.

**Recommendation: option 1 (ContextVar) + a new middleware that
extracts `mcp-session-id` from the headers and sets the var.** Total
code: ~30 LOC. The `_wrap_with_metrics` chokepoint reads the var
when starting the span. The new middleware sits NEXT TO
`SessionCapMiddleware` (or extends it — both read the same header)
in the `add_middleware` call chain in `server/main.py:368-398`.

### 1.5 Where `cache_layer_served` is decided

`server/cache.py::RetrievalCache.lookup_search` returns
`(payload, hit_tier)` where `hit_tier ∈ {"1", "2", ""}` (`TIER_1`,
`TIER_2`, empty for miss). `server/handlers/search.py:113-138`
calls `lookup_search` twice (Tier-1 only, then Tier-1+2 after
embedding) and **discards `_hit_tier`** today (line 114, 130).

For tracing, the handler needs to bubble the `hit_tier` (or "tier3"
when the rerank path hits the Tier-3 LRU, or "miss") up to the
span. Two clean options:

- **Set the attribute directly on the active span from inside the
  handler:** `tracing.set_attribute("arxmcp.cache_layer_served",
  ...)`. Requires the tracing module to expose a `set_attribute`
  helper that reads `trace.get_current_span()` so handlers don't
  import `opentelemetry` directly (one-import policy).
- **Return it via the handler return tuple:** invasive; changes 7
  handler signatures.

**Recommendation: the first option.** The span_tool_call context
manager sets it to `"miss"` on entry; handlers call
`tracing.set_cache_layer("tier1")` (or `tier2` / `tier3`) when they
detect the hit. The on-entry default + late override is what OTel's
attribute model supports natively.

### 1.6 Existing observability subpackage conventions

`server/observability/__init__.py` (8 lines) is just a docstring.
`server/observability/metrics.py` (245 LOC) is the template
`tracing.py` should match:

- Module-level constants for everything name-related (counter names,
  TTL constants).
- Public functions only; no classes unless needed.
- A `reset_*_for_tests()` helper that mirrors
  `reset_request_metrics_for_tests` (line 206) — for OTel that's a
  span-exporter reset + `TracerProvider.shutdown()` between tests.
- `__all__` at the bottom listing the public surface.

Imports inside `_encode_query_sync` are LAZY (`server/query_encoder.py:266`)
to avoid an import-time cycle with `server.observability.metrics`.
The same lazy-import discipline applies to `server.observability.tracing`
when imported from `query_encoder` / `rerank`.

### 1.7 Natural child-span wrap points

- **embed:** `server/query_encoder.py::_encode_query_sync` lines
  282-295 already have a `t0 = time.perf_counter()` and a try/finally
  for the EMBED_CALLS_COUNTER. Wrap this block in `span_embed()`.
  The model identity is the existing module-level
  `BGE_M3_COMMIT_SHA` re-export — set it as `model.revision` on
  the child span.
- **vector-search / ANN:** `server/handlers/search.py:143-147`
  (`r.chunks_table.search(query_vec, ...).limit(...).to_arrow()`)
  is the LanceDB call. Wrap with `span_ann()` (the brief lumps
  this under "vector-search").
- **BM25:** `server/retrieval/bm25.py` exists; not used by the v1
  `search_papers` handler (the design note says BM25 + RRF lands
  in E07; the v1 handler is dense-only — `server/handlers/search.py:142`).
  Span helper should still exist for E07 readiness, but the
  acceptance criterion "a `search_papers` call produces a parent
  span with child spans for embed + ANN + rerank" must NOT require
  a BM25 child today (the dense-only path produces only embed + ANN).
  Read the AC carefully and pin the test to the actual emitted
  set.
- **rerank:** `server/retrieval/rerank.py` — the cross-encoder
  forward pass. Wrap with `span_rerank()`; `BGE_RERANKER_COMMIT_SHA`
  is the existing module constant for `model.revision`.
- **summarize:** `server/notes/07-multi-agent-caching.md` (lines
  236-244) is explicit: **the summarizer is PERMANENTLY DROPPED.**
  The brief mentions it ("summarize (Haiku API call when configured)")
  but there is no summarizer in the v1 code. `span_summarize()` can
  ship as an unused helper for forward-compat, but the test must
  not require it to fire.

### 1.8 Test pattern reference

`tests/test_server_metrics.py:182-191` is the proven pattern for
"in-process telemetry harness." For OTel the analog is:

```python
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
```

`InMemorySpanExporter` + `SimpleSpanProcessor` is the **in-process**
exporter — no network at all. Tests can install it as the
`TracerProvider`'s only processor, run the handler, then read
`exporter.get_finished_spans()`. This is also the answer to the
"how do we test the unreachable-endpoint path without binding a
port" open question: don't try; install a no-op or
InMemorySpanExporter and assert the WARN log fires via `caplog`.

`pyproject.toml` does NOT currently declare any OTel deps. The
implementer adds (verify exact names with researcher 2's external
brief):
- `opentelemetry-api`
- `opentelemetry-sdk`
- `opentelemetry-exporter-otlp-proto-grpc` (matches the brief's
  default `http://localhost:4317` which is OTLP/gRPC, NOT
  OTLP/HTTP — the design note's `http://localhost:4318` was HTTP;
  the brief switched to 4317/gRPC).

Pin a recent stable; the OTel API has been ABI-stable since 1.0.

## 2. Prior decisions and lessons

`.claude/notes/HANDOFF.md` (2026-05-10) is the post-E09 + doc-
consolidation snapshot. No tracing-specific carryover.

`git log` shows the most recent observability work is **E14_S01**
(commits `d20d190` / `5bc0785` / `7aeac51`, just before this
session) — that landed the Prometheus surface and built the
`server/observability/` subpackage `tracing.py` will live inside.
**The wrapper pattern in `server/tools.py::_wrap_with_metrics` is
fresh and battle-tested; reuse it.** The adversary critic was
well-calibrated on E14_S01 (0% HIGH-invalidation rate per HANDOFF),
so the patterns it adopted are durable.

**E06_S01 critique-adversary.md line 176** referenced
`ARXMCP_OTEL_ENDPOINT` as the canonical "documented-but-not-
implemented env var" — `_scan_unknown_arxmcp_env_vars` was added
explicitly to catch the typo that wouldn't fire when E14_S02
finally lands. Implementer must add the field to `Config`.

**Note 08 docker-compose snippet (lines 261-264)** uses
`ARXMCP_BIND_HOST=0.0.0.0` and was deliberately overridden by
E06_S01 (see `server/config.py:19-26`). No analog problem for
OTel: `ARXMCP_OTEL_ENDPOINT` is a string with no validator
constraint other than "starts with `http://` or `https://`"; the
spec wants `4317`/gRPC inside `127.0.0.1` Docker network. Document
the localhost-only default in `docs/observability/tracing.md`.

**Doc placement:** the brief says
`docs/observability/tracing.md`. Per `CLAUDE.md` §1 (the strict
root-MD layout rule) docs at `docs/observability/` are only
permitted if linked from the root `README.md`. Today `docs/` holds
only `install.md`. **Two options:** (a) put the tracing doc under
`.claude/docs/tracing.md` (matches the existing per-feature
internal-reference pattern — `.claude/docs/model-policy.md`,
`.claude/docs/orchestrator-rules.md`); (b) honor the brief
literally and accept that the root README must grow an Operations
link to `docs/observability/`. **Recommendation: (a).** Tracing
config is an operator-internal concern, not user-facing arXMCP
documentation; this matches the doc-layout consolidation precedent.
Researcher 2's external brief may have a contrary view; merge step
should pick one.

## 3. External sources

Out of scope per task framing. Researcher 2 covers:
- OpenTelemetry Python SDK API surface
- `BatchSpanProcessor` vs `SimpleSpanProcessor` semantics + the
  "fail silently on unreachable endpoint" guarantee
- OTLP/gRPC vs OTLP/HTTP exporter choice for `localhost:4317` vs
  `4318`
- `opentelemetry-instrumentation-fastapi` / `httpx` (do we want
  auto-instrumentation alongside our manual spans?)
- Phoenix's expected OTLP receiver flavor (E14_S03 follow-on)

## Open questions

1. **`_agent_role` source-of-truth.** Tool-schema bump (visible,
   schema-version bump, BP1 invalidation once) vs header
   (`Arxmcp-Agent-Role`) vs body inspection in a middleware vs
   tool-arg with FastMCP's underscore-prefix-hides-from-schema
   convention (does FastMCP have one? verify). I lean header. The
   merge step must pick exactly one.
2. **Span boundary on the metrics wrapper.** Single combined
   `_wrap_with_metrics_and_tracing` closure vs two stacked wrappers.
   I lean combined.
3. **Session-id plumbing.** ContextVar vs FastMCP `Context` arg.
   I lean ContextVar.
4. **`cache_layer_served` enum.** Note 08 says
   `exact / semantic / rerank / miss`; brief says
   `tier1 / tier3 / miss`. I recommend `tier1 / tier2 / tier3 / miss`
   (matches existing Prometheus label) — but pin the choice before
   writing the test.
5. **OTLP exporter flavor.** gRPC (4317) vs HTTP (4318). Brief
   says gRPC; note 08 says HTTP. gRPC is the OTLP default; pick gRPC
   and update note 08 in the same commit.
6. **Unreachable-endpoint test.** Probably swap exporter for
   InMemorySpanExporter and assert WARN log. Researcher 2 should
   confirm OTel's SDK behavior on `BatchSpanProcessor` connection
   errors (does the SDK itself log WARN, or do we wrap?).
7. **`docs/observability/tracing.md` placement.** `docs/` vs
   `.claude/docs/`. Per CLAUDE.md I lean `.claude/docs/tracing.md`.
8. **Existing test count delta.** 1311 → ~1320 expected; the
   tracing test file is the only new file likely to add ≥4 cases
   (parent-span existence, child-span existence, attribute
   presence, unreachable-endpoint resilience, disabled-mode
   no-op).

## External writes the implementation will require

- **`pyproject.toml`**: add `opentelemetry-api`,
  `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`.
  Local edit only; no PyPI / index mutation. `uv.lock` re-pin via
  `uv lock`.
- **`server/config.py`**: declare `otel_endpoint: str | None = None`
  on `Config` so `_scan_unknown_arxmcp_env_vars` doesn't reject
  `ARXMCP_OTEL_ENDPOINT`. Local edit.
- **`.claude/notes/08-security-observability-ops.md`**: update the
  port (`4318` → `4317`) and `cache_layer_served` enum to match the
  shipped values. Or document the divergence as deliberate. Local
  edit.
- **`CLAUDE.md` §3 (status snapshot table)**: E14_S02 row from
  PENDING → SHIPPED at milestone close. Local edit.
- **`.claude/notes/HANDOFF.md`**: post-milestone snapshot. Local
  edit.
- **Local commits on `main`** per CLAUDE.md §4.1 ("All work lands
  on `main` directly"). User push authorization required per-event
  per CLAUDE.md §4.4.

**Nothing requires a remote API call, no PR creation, no infra
mutation. Everything stays in this single-user workstation.**
