# Multi-Agent Scout Brief: Observability & Reporting
**Scout run:** 2026q2-observability-reporting  
**Date:** 2026-05-28  
**Scout model:** claude-sonnet-4-6  
**Motivating bug:** `corpus-version.json` `chunk_count` field silently reported 106 while LanceDB held 10298 real rows; nothing flagged the divergence.

---

## 1. TL;DR

Top-3 capabilities to consider: (1) **OTel GenAI MCP semantic conventions** — the spec (v1.39+, development status) defines `mcp.session.id`, `gen_ai.tool.name`, and `isError` span wiring that arXMCP's tracing layer already implements *partially* but does not yet align to the standardized attribute names, creating a compatibility gap with any downstream Phoenix/Datadog scraper that expects those names; (2) **ALTK-style post-tool-result checking** — the emerging pattern of a middleware layer that intercepts tool responses *after execution* to detect "silent errors" (HTTP-200-but-wrong-content failures) maps directly to the motivating bug: a startup-time invariant check that compares `corpus_version.json.chunk_count` against `SELECT COUNT(*) FROM chunks WHERE version=N` would have caught the 106-vs-10298 divergence immediately; (3) **NabaOS-style signed tool receipts** — HMAC-signing tool execution receipts at the server side so the *agent* can detect fabricated or stale tool results maps onto arXMCP's existing `corpus_version` envelope field, which is machine-readable but currently only advisory and unverified.

Main architectural gap: **arXMCP emits `corpus_version` in every envelope but has no mechanism to assert that the persisted metadata (corpus-version.json, BM25 pickle, Kùzu graph) is internally consistent with the live LanceDB row count.** No startup-time invariant check exists, no per-scrape consistency gauge exists, and the `degraded` flag on `/readyz` is set only when LanceDB *fails to open* — not when a metadata field quietly diverges from ground truth.

---

## 2. Multi-agent candidates

### Candidate 1: OTel GenAI MCP Semantic Conventions (v1.39+)

**Name + URL:** OpenTelemetry Semantic Conventions for GenAI/MCP, https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/  
**Year + venue:** 2025–2026 (development status; `semantic-conventions` v1.39–v1.40), OpenTelemetry project  
**What it does:** Standardizes span names, attributes, and event shapes for MCP tool calls, agent orchestration, and GenAI LLM invocations. For MCP specifically: client/server spans follow `{mcp.method.name} {target}` naming; `mcp.session.id` is a Recommended attribute; tool execution spans carry `gen_ai.tool.name` and `gen_ai.tool.call.id`; when `CallToolResult.isError=true` the span's `error.type` SHOULD be `tool_error`. The spec notes that if outer GenAI instrumentation already traces tool execution, MCP instrumentation SHOULD NOT create a duplicate span but add MCP-specific attributes to the existing one.

**What's NEW vs arXMCP today:** arXMCP has OTel tracing via `server/observability/tracing.py` and emits parent spans via `span_tool_call` (server/tools.py:740–790). However, the current span attributes (`mcp.tool_name`, `arxmcp.corpus_version`, `arxmcp.agent_role`, `arxmcp.cache_layer_served`) use arXMCP-private attribute keys, not the OTel-spec `gen_ai.tool.name` and `mcp.session.id` names. Two concrete deltas: (a) `mcp.session.id` should be extracted from the `Mcp-Session-Id` request header (arXMCP has session tracking in `server/session.py` but does not thread it into spans); (b) `isError=true` tool results should flip the span's `error.type` to `tool_error` per spec — currently the wrapper uses a binary `status="ok"|"error"` label on the Prometheus counter but does not propagate into the OTel span. Alignment gap: arXMCP span attributes are not scrape-compatible with Datadog LLM Observability or Phoenix GenAI dashboards that expect OTel standard names.

**Architectural fit:** Context-engineering change in `server/observability/tracing.py` and `server/tools.py::_wrap_with_observability`. Add `gen_ai.tool.name`, `mcp.session.id` attributes; propagate `isError` to span status. Does NOT require new MCP tool or schema change. BP1/BP2 cache discipline: no impact — span attribute names live entirely in the tracing layer, not in `tools/list` or prompt content.

**Cache interaction:** None. OTel attributes are emitted post-response; they do not touch the `tools/list` byte-stable surface or the prompt cache prefix. Safe per `.claude/notes/07-multi-agent-caching.md`.

**Maturity signal:** Spec is development-status but implemented by Datadog, New Relic, and Phoenix. The attribute names have stabilized enough for production dashboards. No code to copy — it is a spec alignment task.

---

### Candidate 2: ALTK Post-Tool-Result Checking (Silent Error Review)

**Name + URL:** Agent Lifecycle Toolkit (ALTK), arXiv:2603.15473, https://github.com/AgentToolkit/agent-lifecycle-toolkit (Apache-2.0)  
**Year + venue:** October 2025 (IBM Research, CAIS 2026 demonstration track)  
**What it does:** Open-source Python middleware (altk-boost) organized around six lifecycle intervention points: post-user-request, pre-LLM prompt conditioning, post-LLM output processing, pre-tool validation, post-tool result checking, and pre-response assembly. The "Silent Error Review" component intercepts tool results *after* execution and classifies them ACCOMPLISHED / PARTIALLY ACCOMPLISHED / NOT ACCOMPLISHED — designed to catch cases where an API returns HTTP-200 but the payload is semantically wrong or empty. The "JSON Processor" component extracts and validates schema-conformant fields from verbose API outputs. Integrates with ContextForge MCP Gateway (IBM) and Langflow as no-code middleware.

**What's NEW vs arXMCP today:** arXMCP validates inputs at the tool boundary (Pydantic schemas, `MAX_FILTER_ITEMS`, `is_valid_paper_id`) but has no post-result checking layer. The motivating bug — `corpus_version.json.chunk_count=106` while LanceDB held 10298 rows — is precisely the "silent error" ALTK's post-tool-result checker targets: the tool *ran*, returned an envelope that looked valid, and no downstream check flagged the metadata divergence. A concrete arXMCP adaptation: at server startup (in `Resources.startup`), execute a LanceDB COUNT query and compare it against `corpus_version.json.chunk_count`; if they diverge by more than a configurable tolerance, set `resources.degraded` with `reason="chunk_count_diverged"` and emit an ERROR log. This is not per-request overhead — it runs once on startup.

**Architectural fit:** New startup-time invariant check in `server/resources.py::startup()` (approx. after line 100). Does NOT require a new MCP tool. Extend `DegradedState.reason` enum to include `chunk_count_diverged`. The per-scrape `/metrics` path via `health.py::refresh_degraded_mode_metric` would then surface it automatically. BP1/BP2: zero impact — this is a startup invariant, not a schema or description change.

**Cache interaction:** The `degraded` flag feeds `resources.degraded` which already surfaces via `/readyz` and `refresh_degraded_mode_metric`. If the server enters degraded mode, the existing `corpus_version` flow still works: agents still get the integer, but `/readyz` returns 503 and the `arxmcp_degraded_mode_active` gauge fires. Cache keys are not affected. Per `.claude/notes/07-multi-agent-caching.md` §"Failure modes" — degraded mode is surfaced, caching remains a performance layer.

**Maturity signal:** Code on GitHub (Apache-2.0), evaluation on public benchmarks (2025). Paper-plus-code beats paper-only. The Silent Error Review idea maps more cleanly to a startup invariant than to ALTK's runtime middleware model; arXMCP would implement the pattern natively, not import the library (no-fork policy, CLAUDE.md §4.7).

---

### Candidate 3: NabaOS — Signed Tool Receipts for Hallucination Detection

**Name + URL:** "Tool Receipts, Not Zero-Knowledge Proofs: Practical Hallucination Detection for AI Agents," arXiv:2603.10060, https://arxiv.org/abs/2603.10060  
**Year + venue:** March 2026, arXiv (no confirmed code repo found at survey time)  
**What it does:** NabaOS proposes that every tool execution runtime generates an HMAC-signed receipt capturing the actual tool result. The LLM agent cannot forge this receipt. When the agent subsequently cites the tool result (e.g., "the corpus has 10298 chunks"), the verifier cross-references the claim against the HMAC receipt. Classifies claims by epistemic source (direct tool output, inference, ungrounded opinion). Achieves 94.2% hallucination detection, 87.6% count-misstatement detection, <15ms overhead per response. Evaluated on NyayaVerifyBench (1,800 scenarios, 6 hallucination types).

**What's NEW vs arXMCP today:** arXMCP already returns `corpus_version` in every tool envelope (server/tools.py::envelope). The receiving agent can trust that integer at request time — but nothing prevents the agent from *citing* a stale or misremembered version in a subsequent turn. A lightweight adaptation: arXMCP could include a deterministic `corpus_integrity_token` field in the envelope — a SHA-256 of `(corpus_version, chunk_count_at_startup, bm25_index_version, kuzu_schema_version)`. The agent can carry this token forward; if a fixer or tactician sub-agent sees a different token on a later call, it knows the substrate has changed mid-session. This is NOT full HMAC signing (arXMCP runs no LLM and has no key management problem) but the *pattern* — surfacing a machine-verifiable digest of substrate state in every envelope — is directly applicable.

**Tension with arXMCP philosophy:** NabaOS requires a verifier outside the LLM; arXMCP's philosophy (CLAUDE.md §2) is that valuable roles live upstream of verification, and verification is done by the Lean kernel. The NabaOS model does not conflict with this because the "verifier" here is a lightweight hash check at the tool envelope layer, not another LLM playing adversary. No tension.

**Architectural fit:** Envelope change in `server/tools.py::envelope()`. Add `corpus_integrity_token: str` field. The field is computed once at startup from `CorpusVersionInfo` fields and is byte-stable per call (no randomness). Does NOT change `tools/list` schema (the `envelope` helper adds fields to the result payload, not the input schema). BP1 cache discipline: `tools/list` byte-stability is about `{name, description}` per tool — the result envelope structure is NOT hashed for BP1. Per `.claude/notes/07-multi-agent-caching.md` §"Tool result shape" — the envelope changes are safe as long as they are deterministic.

**Cache interaction:** Adding a deterministic `corpus_integrity_token` to every envelope is safe: it is the same value for every call within a session (the server pins `corpus_version` at startup and never auto-upgrades). It will become part of `tool_result` content blocks in the agent prompt, which means two agents calling the same query will see identical tokens → shared cache hit preserved. See `.claude/notes/07-multi-agent-caching.md` §"Property 2: Tool result payloads are canonicalized."

**Maturity signal:** Paper-only at survey time (no code repo confirmed). The HMAC-signing mechanism is described but no reference implementation published. The *pattern* (integrity digest in envelope) is independently implementable. Lower maturity than ALTK.

---

### Candidate 4: SagaLLM — Inter-Agent State Consistency Validation

**Name + URL:** "SagaLLM: Context Management, Validation, and Transaction Guarantees for Multi-Agent LLM Planning," arXiv:2503.11951, VLDB Endowment Vol. 18, 2025, https://arxiv.org/abs/2503.11951  
**Year + venue:** 2025, VLDB (top database venue — paper-with-publication, code not confirmed open)  
**What it does:** SagaLLM integrates the database Saga transaction pattern with multi-agent LLM planning. Its core mechanism is an *independent validation agent* that checks inter-agent state consistency at critical junctures — cross-stage alignment between what agent A computed and what agent B consumed. Implements modular checkpointing so that if validation fails, the system can roll back to the last good checkpoint. Specifically designed to catch cases where sub-agents share a mutable substrate (context, memory, tool results) and one agent's writes are consumed incorrectly by another.

**What's NEW vs arXMCP today:** The sketcher → autoformalizer → tactician → fixer pipeline in arXMCP's consumer passes tool results forward across agent turns. If a fixer consumes a `chunk_id` returned by the autoformalizer but the corpus has been updated between turns (e.g., delta ingest mid-session), the fixer's `get_chunk` call returns different bytes than the autoformalizer saw. arXMCP's cache already mitigates this via `corpus_version` key invalidation (07-multi-agent-caching.md §"Tier 1"). The SagaLLM delta: it would validate that the `corpus_version` echoed in the fixer's tool result matches the version the autoformalizer used — if not, flag the inconsistency *to the orchestrator* rather than silently serving a different corpus slice.

**Tension:** SagaLLM's validation agent is an LLM-based component; arXMCP has a hard rule: no `anthropic` SDK at runtime (CLAUDE.md §4.7). The adaptation for arXMCP is therefore rule-based, not LLM-based: a version-mismatch check in the orchestrator (or a server-side session guard) that refuses to serve results from a new corpus version if the session was started on an older one. This is a simpler, CLAUDE-compliant analogue of SagaLLM's validation agent.

**Architectural fit:** Two paths: (a) server-side: `server/session.py` could record `corpus_version_at_session_start` and the `search_papers` handler could return an additional `session_corpus_mismatch: true` flag if the live version has advanced since session start — the orchestrator can then decide whether to continue or restart the session; (b) orchestrator-side (outside arXMCP): the consuming agent checks `corpus_version` in each tool result and aborts if it drifts. Path (a) is the pure arXMCP tool — it requires a new field in the session state and a check in handlers. Not a new MCP tool; an envelope augmentation.

**Cache interaction:** A `session_corpus_mismatch` flag in the envelope would be `false` for all normal sessions; it would only become `true` when the corpus is updated mid-session (rare event). Because `false` is the common case, cache hit rates are unaffected: the deterministic `false` value is byte-stable across all calls in a normal session. See `.claude/notes/07-multi-agent-caching.md` §"Property 2".

**Maturity signal:** Published in VLDB — peer-reviewed, top venue. Code availability not confirmed at survey time. Pattern (per-session corpus-version guard) is independently implementable.

---

### Candidate 5: MCPAgentBench — Benchmarking MCP Tool Use in Agents

**Name + URL:** "MCPAgentBench: A Real-world Task Benchmark for Evaluating LLM Agent MCP Tool Use," arXiv:2512.24565, https://arxiv.org/abs/2512.24565  
**Year + venue:** December 2025 (v3: January 2026), arXiv; code open-source  
**What it does:** A benchmark of 841 tasks and 20,000+ MCP tools from real-world MCP servers (MCP Marketplace, GitHub, HuggingFace), with a dynamic sandbox that injects distractor tools to test selection discrimination. Measures task completion rate, execution efficiency, and agent failure modes under complex multi-step tool invocations. Revealed significant performance differences across GPT-4, Claude 3.5/3.7, and Qwen-based models.

**What's NEW vs arXMCP today:** The benchmark reveals that agents exposed to noisy tool lists (many tools, some irrelevant) fail disproportionately at *tool selection*, not task reasoning. arXMCP's 8-tool surface is deliberately small — the BP1 cache incentive (CLAUDE.md §6, note 07) also incentivizes a minimal tool list. MCPAgentBench's finding validates this design: a small, high-precision tool surface is better for agent reliability than a large flat tool catalog. The gap: arXMCP has no agent-facing benchmark data on its own tool surface — no reported success/failure rates for the sketcher or autoformalizer sub-agent on the 8 tools. The benchmark methodology is a template for adding per-tool reliability telemetry (task completion rate per tool, per agent role).

**Tension with arXMCP philosophy:** MCPAgentBench focuses on the agent side; arXMCP is a server. No tension. MCPAgentBench validates arXMCP's small-tool-surface design choice.

**Architectural fit:** No code change required. The benchmark methodology informs: (a) adding a `retrieval_success: bool` flag to search_papers results (did the agent actually find a relevant chunk, or did it retry?) as a signal to the orchestrator; (b) adding per-tool `invocation_count` and `agent_role_at_call` labels to existing Prometheus counters so operators can identify which agent role drives which tool's error rate. Both are small additions to `server/tools.py::_wrap_with_observability`.

**Cache interaction:** Adding labels to Prometheus counters does not touch `tools/list` byte stability or prompt cache prefix. Safe.

**Maturity signal:** Code open-source (v3 Jan 2026). Active development. Real-world MCP server inventory is credible.

---

### Candidate 6: Arize Phoenix + OTel — RAG Retrieval Quality Evaluation

**Name + URL:** Arize Phoenix, https://github.com/Arize-ai/phoenix (MIT license)  
**Year + venue:** Ongoing (latest major release 2025); integrated with arXMCP in E14_S04  
**What it does:** Open-source LLM observability platform built on OTel. For RAG pipelines: traces each retrieval call as a child span with relevance scores, chunk IDs retrieved, and reranker scores. Evaluates faithfulness, relevance, hallucination detection. Emits per-query nDCG and MRR estimates when ground-truth labels are available. Supports online evaluation on sampled production traffic.

**What's NEW vs arXMCP today:** arXMCP already integrates Phoenix in E14_S04 (CLAUDE.md §3 — "Phoenix integration"). The gap exposed by the motivating bug: arXMCP's Phoenix integration traces tool calls but does NOT trace the corpus-state-at-call-time (chunk_count, bm25_index_version, kuzu_loaded). The concrete delta: add a `corpus_snapshot` event to each Phoenix trace root (one event per agent session, not per tool call) carrying `{chunk_count: N, bm25_version: str, kuzu_paper_count: N}` queried live at session open. If those values drift across sessions, Phoenix's timeline view will show the drift. This closes the observability gap with a single server-startup query rather than a new per-call overhead.

**Tension:** None — Phoenix is already integrated.

**Architectural fit:** Change in `server/observability/tracing.py` — when a new MCP session begins (on `mcp.session.id` header arrival), emit a Phoenix custom event `corpus_snapshot` with live counts from LanceDB and Kùzu. Query is: `lancedb.count_rows_at_version(corpus_version)` + `kuzu.execute("MATCH (p:Paper) RETURN count(p)")`. Per `.claude/notes/07-multi-agent-caching.md` — not a cache-invalidating path.

**Cache interaction:** Session-open events are emitted to Phoenix out-of-band; they do not modify the MCP response. No cache impact.

**Maturity signal:** Code on GitHub (MIT), active production use. Widely referenced in 2025-2026 agent observability literature. Already integrated in arXMCP — zero new dependency.

---

### Candidate 7: OTel MCP Session Tracking + `isError` Propagation

**Name + URL:** "Semantic conventions for Model Context Protocol (MCP)," https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/ (OTel v1.39+)  
**Year + venue:** 2025–2026, OpenTelemetry project (development status)  
**What it does:** Extends the GenAI span model specifically for MCP. Adds `mcp.session.id` as a Recommended attribute (maps to the `Mcp-Session-Id` request header); adds `mcp.method.name` as Required; specifies that when `CallToolResult.isError=true`, the span's `error.type` SHOULD be set to `tool_error`. Tool execution spans are compatible with `execute_tool` GenAI spans — if both are present, merge attributes rather than creating duplicate spans.

**What's NEW vs arXMCP today:** arXMCP's `span_tool_call` context manager (server/observability/tracing.py) does not read `mcp.session.id` from the incoming request context. The session tracker in `server/session.py` tracks caps but does not thread session IDs into span context. Concrete delta: when a tool call is dispatched, extract `Mcp-Session-Id` from the request headers and attach it as `mcp.session.id` to the current OTel span. This enables Phoenix/Datadog dashboards to group all tool calls for one agent session into a single trace tree — which is exactly the observability needed to detect "the autoformalizer got corpus_version=5 but the fixer got corpus_version=6 in the same session."

**Architectural fit:** `server/observability/tracing.py` — add `mcp.session.id` attribute extraction. `server/tools.py::_wrap_with_observability` — pass session header value into span. This is a one-line change per instrument point but requires threading the request context through the handler chain. The handlers already receive FastMCP context; `Mcp-Session-Id` is available in `request.headers`. Not a new tool; not a schema change; not a BP1 impact.

**Cache interaction:** None. Span attributes are emitted after response is complete.

**Maturity signal:** Spec document, no separate code. Attribute alignment is straightforward.

---

### Candidate 8: GradNormIR — OOD Corpus Detection for Dense Retrievers

**Name + URL:** "When Should Dense Retrievers Be Updated in Evolving Corpora? Detecting Out-of-Distribution Corpora Using GradNormIR," arXiv:2506.01877, https://arxiv.org/abs/2506.01877  
**Year + venue:** June 2025 (submitted), arXiv cs.IR  
**What it does:** Unsupervised method using gradient norms to detect when a document collection has drifted out-of-distribution relative to a dense retrieval model (BGE-M3 in arXMCP's case). Signals when re-indexing is needed to prevent retrieval failures in evolving corpora. Addresses the class of bug where a new batch of papers is ingested but the embedding model's training distribution no longer covers the new content well.

**What's NEW vs arXMCP today:** arXMCP's LaTeXML drift detector (E10_S04) catches *parser-level* drift (LaTeXML output format changes). GradNormIR catches *embedding-model-level* drift (the BGE-M3 model no longer represents the new corpus documents well). arXMCP has no such signal today. The delta: after each OAI-PMH delta ingest cycle, run GradNormIR on the newly ingested chunk embeddings; if the gradient-norm distribution signals OOD, emit a `WARN` log and set the `drift-detected.flag` sentinel (which already feeds `LATEXML_DRIFT_DETECTED_GAUGE` in `server/health.py`). This reuses the existing sentinel infrastructure to surface embedding-level drift alongside parser-level drift.

**Tension:** GradNormIR requires access to the embedding model's gradient computation — not just forward pass inference. arXMCP uses BGE-M3 via FlagEmbedding and runs inference only; gradient access requires model internals. This is a non-trivial technical prerequisite. If BGE-M3 is loaded in FP16 on CPU, gradient computation may be expensive. The pattern is sound; the implementation cost is non-trivial. Flag as "medium-term investigation" rather than immediate delta.

**Architectural fit:** `ingest/` pipeline — new post-ingest check step, not a server-side change. Would interact with the `drift-detected.flag` sentinel written by `ingest/` and read by `server/health.py::refresh_sentinel_metrics`. No MCP tool change; no schema change; no BP1 impact.

**Cache interaction:** None. Drift detection is a background ingest-time signal.

**Maturity signal:** Paper on arXiv (June 2025); code availability not confirmed at survey time. The gradient-norm approach is algorithmically sound but requires verification against BGE-M3's specific API.

---

## 3. Sources reviewed

| Paper / framework | URL | Year | Code available | High-signal |
|---|---|---|---|---|
| OTel GenAI MCP SemConv | https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/ | 2025–2026 | N/A (spec) | YES |
| ALTK Agent Lifecycle Toolkit | https://arxiv.org/abs/2603.15473 + https://github.com/AgentToolkit/agent-lifecycle-toolkit | 2025 | YES (Apache-2.0) | YES |
| NabaOS Tool Receipts | https://arxiv.org/abs/2603.10060 | 2026 | No confirmed repo | MEDIUM |
| SagaLLM | https://arxiv.org/abs/2503.11951 | 2025 | Not confirmed open | MEDIUM |
| MCPAgentBench | https://arxiv.org/abs/2512.24565 | 2025–2026 | YES (open-source) | YES |
| Arize Phoenix | https://github.com/Arize-ai/phoenix | 2025 | YES (MIT) | YES |
| OTel GenAI Client Spans | https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/ | 2025–2026 | N/A (spec) | YES |
| OTel MCP SemConv (method names) | https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/ | 2025–2026 | N/A (spec) | YES |
| GradNormIR | https://arxiv.org/abs/2506.01877 | 2025 | Not confirmed | MEDIUM |
| PROV-AGENT | https://arxiv.org/abs/2508.02866 | 2025 | Near real-time open-source (IEEE e-Science 2025) | LOW (not local-first) |
| MCP tool descriptions "smells" | https://arxiv.org/abs/2602.14878 | 2026 | Not confirmed | LOW (tool surface design, not observability) |
| Tool invocation failure taxonomy | https://arxiv.org/abs/2601.16280 | 2025 | Not confirmed | LOW (agent-side, not server-side) |
| DeepSeek-Prover-V2 | https://arxiv.org/abs/2504.21801 | 2025 | YES (open weights) | LOW (pipeline architecture, not observability) |
| MCP-AgentBench (2509.09734) | https://arxiv.org/abs/2509.09734 | 2025 | YES | LOW (redundant with MCPAgentBench) |
| Freshprobe data freshness | https://github.com/Sudhan30/freshprobe | 2025 | YES | LOW (not math-domain specific) |
| MAIF artifact provenance | https://arxiv.org/abs/2511.15097 | 2025 | Not confirmed | LOW (heavyweight provenance framework) |

---

## 4. Architectural alignment

Map each candidate to current arXMCP code:

- **OTel GenAI MCP SemConv (Candidate 1):** `server/observability/tracing.py` — add `gen_ai.tool.name`, `mcp.session.id` attributes; `server/tools.py::_wrap_with_observability` (lines 680–790) — propagate `isError` to span `error.type`. Net change to existing code; no net-new files.

- **ALTK startup invariant (Candidate 2):** `server/resources.py::startup()` — add LanceDB row count check vs `corpus_version.json.chunk_count` after corpus open (around line 100). Extend `server/corpus.py::DegradedState` reason enum. `server/health.py::refresh_degraded_mode_metric` already surfaces `degraded.reason` — zero change needed there.

- **NabaOS corpus_integrity_token (Candidate 3):** `server/tools.py::envelope()` (line 399) — add `corpus_integrity_token: str` field computed from `sha256(corpus_version || chunk_count || bm25_hash || kuzu_schema_version)`. Computed once in `Resources.startup`, stored as an attribute on `Resources`. Zero per-call overhead.

- **SagaLLM session corpus guard (Candidate 4):** `server/session.py` — add `corpus_version_at_session_start: int` to the session record. `server/handlers/search.py` (and other handlers) — compare current `corpus_info.version` against the session's pinned version; if diverged, add `session_corpus_mismatch: true` to the envelope. Note: this flag is purely advisory — it does not block the response.

- **MCPAgentBench per-role telemetry (Candidate 5):** `server/tools.py::_wrap_with_observability` (lines 710–716) — extract `agent_role` from the `Mcp-Agent-Role` header (if present) and label `REQUEST_COUNTER` with it. This makes the existing `arxmcp_tool_requests_total` counter per-role aware, enabling per-role failure rate dashboards.

- **Arize Phoenix corpus_snapshot event (Candidate 6):** `server/observability/tracing.py` — new `emit_corpus_snapshot_event(session_id, chunk_count, bm25_version, kuzu_paper_count)` helper; call from the MCP session-open path in `server/main.py::lifespan` or from the first tool call within a new session.

- **OTel `mcp.session.id` (Candidate 7):** `server/observability/tracing.py` — thread `Mcp-Session-Id` from request headers into the span context. Requires the handlers to pass `request.headers` through to `span_tool_call`. Currently `span_tool_call` takes `tool_name`, `corpus_version`, `k` — add `session_id: str | None = None` parameter.

- **GradNormIR embedding drift (Candidate 8):** `ingest/` pipeline, net-new file `ingest/embedding_drift.py`. Calls after OAI-PMH delta ingest. Writes to `drift-detected.flag` sentinel consumed by `server/health.py::refresh_sentinel_metrics` (line 308). No server-side changes required.

---

## 5. Themes

The agentic observability literature in 2025–2026 converges on four related patterns: (1) **metadata-state divergence as a first-class failure mode** — not just "did the tool error?" but "is the tool's reported state consistent with ground truth?" — a class of bug that standard APM (latency, error rate) is blind to; (2) **lifecycle intervention points** — the ALTK/SagaLLM framing of six lifecycle stages (pre-tool, post-tool, pre-response) is becoming the standard vocabulary for where to insert validation, paralleling the shift from "log and hope" to "check and refuse"; (3) **OTel standardization as the convergence layer** — the GenAI/MCP semantic conventions are still in development but are already being implemented by Datadog, New Relic, and Phoenix; any new observability work in arXMCP should align to these attribute names to remain compatible with the emerging standard scraping ecosystem; (4) **envelope-level trust signals** — the agent-harness literature is beginning to expect tool results to carry not just data but machine-verifiable provenance (version integers, integrity digests) that the orchestrator can assert on, closing the loop from "the server says it returned X" to "the server cryptographically committed to having returned X."

---

## 6. Out of scope / parking lot

- **PROV-AGENT (arXiv:2508.02866):** W3C PROV-based provenance framework for agentic workflows. Rejected: requires an external provenance store; not local-first; operational overhead exceeds the bug's severity. The simpler `corpus_integrity_token` pattern (Candidate 3) covers the same ground with zero new infrastructure.

- **MAIF (arXiv:2511.15097):** Artifact-Centric Agentic Paradigm with formal provenance. Rejected: heavyweight framework requiring model integration; architecture-lock conflict (requires the server to participate in a provenance chain that the LLM interacts with). Not local-first.

- **Freshprobe (GitHub):** CLI/MCP server that probes external endpoints for cache staleness. Rejected: designed for external HTTP endpoints, not internal LanceDB row counts. The motivating bug is an *internal* divergence, not an external staleness signal.

- **MCP tool description smells (arXiv:2602.14878):** Found 97.1% of MCP tool descriptions contain at least one antipattern. Rejected for this scout: it is a description-quality signal, not an observability/integrity signal. Potentially relevant for a future tool-description review milestone.

- **Tool invocation failure taxonomy (arXiv:2601.16280):** 12-category taxonomy for tool-use failures. Rejected: taxonomy is agent-side (model failure to invoke tools correctly), not server-side (tool server serving incorrect state). Out of scope for the motivating bug.

- **LangSmith / Datadog LLM Observability:** Mature platforms but cloud-SaaS-first; arXMCP is local-first. The OTel GenAI SemConv (Candidate 1) is the alignment work that lets arXMCP remain compatible with these platforms if an operator chooses to route telemetry to them, without creating a dependency.

- **Reflexion / ReAct (agent harness primitives):** Foundational patterns already covered in prior capability-scout runs; do not add new observability/integrity capabilities relevant to this specific scout scope.

- **DeepSeek-Prover-V2 subgoal decomposition:** Proof-pipeline architecture, not observability. Relevant to a future scout on pipeline architecture; out of scope here.
