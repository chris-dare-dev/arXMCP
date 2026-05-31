# Multi-Agent Scout Brief: Corpus Integrity & Observability
**Scout run:** corpus-integrity-observability  
**Date:** 2026-05-31  
**Scout model:** claude-sonnet-4-6  
**Motivating bug:** `corpus-version.json` `chunk_count` field silently reported 106 while LanceDB held 10,298 real rows; nothing flagged the divergence until manual inspection during a live cutover.  
**Context note:** The prior scout run `2026q2-observability-reporting` (2026-05-28) produced 16 candidates; milestones m1, m2, m3, e2, e3 subsequently shipped. This brief covers the current post-implementation state, surfaces what remains unaddressed, and adds net-new research from the multi-agent / agentic-RAG lens.

---

## 1. TL;DR

Top-3 multi-agent capabilities to consider: (1) **mcpdiff contract snapshotting** — arXMCP's `tools/list` byte-stability discipline (BP1) already pins tool schemas for cache purposes, but no external snapshot file (`.mcpc.json`) exists for diff-on-deploy review; the same integrity discipline that catches corpus-count divergence should also catch tool-description drift between deployments; (2) **VersionRAG version-graph pattern applied to corpus evolution** — arXMCP's MVCC+corpus-version.json pairs a corpus integer with content, but no component surfaces "what changed between corpus_version N and N+1" — agents asking "did the corpus grow since my last run?" have no answerable query surface; (3) **OTel MCP `mcp.session.id` + corpus snapshot event** — arXMCP instruments OTel spans but does not yet attach `mcp.session.id` (the OTel SemConv v1.39+ standard attribute) to spans, and does not emit a per-session `corpus_snapshot` event that would let Phoenix/Datadog timelines show when corpus counts drift across agent sessions.

Main architectural gap (post m1-m3, e2-e3 implementation): arXMCP has fixed the root-cause bug (marker counts now read from `tbl.count_rows()`) and added startup reconciliation gauges (`arxmcp_corpus_chunk_count_marker` vs `arxmcp_corpus_chunk_count_actual`), a degraded-mode flag for divergence, HNSW unindexed-rows tripwire, and ingest-summary.json + per-run Prometheus gauges. What remains absent is **a change-surface facing the calling agent**: no MCP tool or envelope field tells the agent "the corpus grew by N chunks since your session started" or "here is a digest of the current corpus state that you can compare across turns." The agent sees `corpus_version: int` in every envelope but cannot easily ask the server for a human-readable corpus diff.

---

## 2. Multi-agent candidates

### Candidate 1: mcpdiff — MCP Contract Snapshot and Diff Tool

**Name + URL:** mcpdiff / mcp-contracts, https://github.com/mcp-contracts/mcp-contracts (MIT license)  
**Year + venue:** 2026, community OSS project (not a research paper; blog post: https://medium.com/@binarEx/your-mcp-servers-tool-descriptions-changed-last-night-nobody-noticed-e3ad93cf6bc7)  
**What it does:** CLI tool that captures the complete MCP server interface — every tool with description, input schema, every resource, every prompt — into a `.mcpc.json` snapshot file committed to git. On subsequent runs it compares current vs. baseline and classifies changes as breaking (schema change), warning (description change), or safe. A `contentHash` (SHA-256 of semantic content) enables tampering detection. GitHub Action posts diff as a PR comment. The key motivation: "Tool descriptions are not documentation — they are instructions to the model." A silently changed description can redirect agent behavior without any error signal.

**What's NEW vs arXMCP today:** arXMCP's BP1 discipline (`.claude/notes/07-multi-agent-caching.md` §Property 1) pins `tools/list` byte stability and asserts it via `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py`. This is functionally equivalent to mcpdiff's contentHash for the schema content — but it is test-only and produces no human-readable diff artifact. The gap: when the schema hash drifts (e.g. after adding the `reconcile-marker` tool or modifying a description), the test fails with "hash mismatch" but no diff shows *what* changed at the description level. Concrete delta: generate a `.mcpc.json` snapshot alongside the existing hash pin so `git diff .mcpc.json` gives a semantic description-level diff on any PR or commit.

**Architectural fit:** Dev tooling, not a server change. A `make snapshot-tools` target that serializes `ALL_TOOLS` from `server/tools.py` into `.mcpc.json` (co-located with `CLAUDE.md`, gittracked). The `pytest --update-tool-schema-hash` path already regenerates the hash; extend it to also write `.mcpc.json`. Zero runtime impact; no schema change; no BP1 effect.

**Cache interaction:** None. `.mcpc.json` is a dev-artifact; it is not loaded at runtime. The BP1 hash in `tests/test_server_tool_schema.py` is the runtime integrity mechanism.

**Maturity signal:** Code available on GitHub and npm (MIT). Not a research paper; a production practice. The contentHash approach independently validates arXMCP's existing `EXPECTED_TOOL_SCHEMA_SHA256` pattern.

---

### Candidate 2: VersionRAG — Corpus Version-Graph for Change Tracking

**Name + URL:** VersionRAG, arXiv:2510.08109, https://arxiv.org/abs/2510.08109  
**Year + venue:** October 2025, arXiv cs.IR  
**What it does:** RAG framework for technical documentation that evolves through versioning. Builds a hierarchical graph capturing "version sequences, content boundaries, and changes between document states." Routes queries through specialized paths based on intent: version-sensitive queries ("what changed in v3?"), change-tracking queries ("did the theorem statement change between versions?"), and standard queries. Achieves 90% accuracy on version-sensitive questions vs 58% for naive RAG, 60% accuracy on implicit change detection vs 0-10% for baselines. Uses 97% fewer tokens than GraphRAG during indexing. Benchmarked on VersionQA (100 curated questions across 34 versioned documents).

**What's NEW vs arXMCP today:** arXMCP has MVCC version pinning (every reader pins to a specific LanceDB dataset version), which covers the "read consistency" half of versioning. The missing half: no surface exposes "what changed between corpus_version N and N+1." The fixer agent, re-running the same `search_papers` query after a delta ingest, sees different results but cannot ask "which of these chunks are new since version 5?" Concrete arXMCP delta: arXMCP already logs `rows_inserted` + `rows_updated` per write in `store-stats.jsonl` (WriteStats). A new MCP tool `get_corpus_delta(since_version: int)` could read `store-stats.jsonl` and return aggregate counts of new/updated chunks per paper since the requested version. This is not a graph build (VersionRAG's full approach) but captures the most useful signal with local-first infrastructure already in place.

**Tension with arXMCP philosophy:** VersionRAG builds a graph over document versions; arXMCP avoids graph-of-graphs complexity (Kùzu is already the citation graph, and MVCC is the version mechanism). The lightweight adaptation (read from JSONL, aggregate by version) avoids introducing a new graph structure.

**Architectural fit:** New MCP tool `get_corpus_delta` in `server/handlers/corpus_delta.py`. Reads `var/arxmcp/ops/store-stats.jsonl` (written by `ingest/store.py::_append_store_stats`) and aggregates `rows_inserted` + `rows_updated` per paper since `since_version`. The tool schema adds one entry to `ALL_TOOLS` in `server/tools.py`, requiring `EXPECTED_TOOL_SCHEMA_SHA256` re-pin (CLAUDE.md §9 "Add a new tool").

**Cache interaction:** BP1 impact: adding a tool to `ALL_TOOLS` requires re-pinning `EXPECTED_TOOL_SCHEMA_SHA256` (per CLAUDE.md §9 and `.claude/notes/07-multi-agent-caching.md` §Property 1). The tool result is NOT cached via the 3-tier retrieval cache (it is an ops query, not a retrieval query). Tool addition is a deliberate version bump; the hash re-pin is the gate.

**Maturity signal:** Paper on arXiv; code availability not confirmed at survey time. The core pattern (reading existing `store-stats.jsonl`) is implementable natively without the paper's code.

---

### Candidate 3: OTel MCP Semantic Conventions + `corpus_snapshot` Session Event

**Name + URL:** OTel GenAI MCP SemConv, https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/ (v1.40, April 2026, Development status)  
**Year + venue:** 2025–2026, OpenTelemetry project  
**What it does:** Standardizes span attributes for MCP tool calls: `mcp.session.id` (Recommended, maps to `Mcp-Session-Id` header), `gen_ai.tool.name` (Conditionally Required), `mcp.protocol.version` (Recommended, e.g. `2025-06-18`), `error.type: tool_error` when `CallToolResult.isError=true`. No corpus/resource versioning attributes are defined — the spec covers the MCP protocol layer, not application-level state.

**What's NEW vs arXMCP today:** Two concrete gaps: (a) arXMCP's `span_tool_call` context manager (`server/observability/tracing.py`) uses arXMCP-private attribute keys (`mcp.tool_name`, `arxmcp.corpus_version`) but does not emit the standardized `mcp.session.id` from the `Mcp-Session-Id` request header. `server/session.py` tracks session caps but does not thread session IDs into span context. Phoenix/Datadog dashboards expecting `mcp.session.id` cannot group tool calls by session. (b) No per-session `corpus_snapshot` custom event is emitted when a new session opens. The specific delta motivating the original bug: if the server emitted a Phoenix span event at session-open carrying `{chunk_count: N, corpus_version: V, bm25_index_version: str}`, the timeline would show drift across sessions — the 106-vs-10298 divergence would have been visible as a session-to-session count change in the Phoenix UI.

**Tension:** None. Both gaps are pure additions to the tracing layer; they do not touch `tools/list`, prompt content, or retrieval results.

**Architectural fit:** (a) `server/observability/tracing.py` — add `mcp.session.id` attribute extraction; `server/tools.py::_wrap_with_observability` — pass session header into span. (b) New `emit_corpus_snapshot_event(session_id, chunk_count, corpus_version)` helper in `server/observability/tracing.py`; called from the MCP session-open path or first tool call per session. Resources' `startup_chunk_count` and `corpus_info.version` are already cached — zero per-call overhead.

**Cache interaction:** Span attributes are emitted post-response; no cache impact. Safe per `.claude/notes/07-multi-agent-caching.md`.

**Maturity signal:** Spec document (v1.40). Implemented by Datadog, New Relic, Elastic APM, and Phoenix. arXMCP already integrates Phoenix (E14_S04). No new dependency required.

---

### Candidate 4: LeanAgent Dynamic Database — Corpus Versioning for Lifelong Learning

**Name + URL:** LeanAgent, arXiv:2410.06209, https://github.com/lean-dojo/LeanAgent (MIT license), ICLR 2025  
**Year + venue:** 2025, ICLR (published proceedings)  
**What it does:** Lifelong learning framework for Lean theorem proving. Core mechanism: a "dynamic database" that appends new theorems from new repositories without retracing everything from scratch, using progressive training over one epoch to prevent catastrophic forgetting. The database tracks curriculum order (sorted by difficulty), premise corpora per repository, and theorem-proof pairs as the agent encounters new repositories. Proved 162 theorems previously unproved by humans across 23 Lean repositories.

**What's NEW vs arXMCP today:** LeanAgent's dynamic database embodies the "incremental corpus growth with integrity" pattern arXMCP needs to develop. Specifically: LeanAgent's database is queried at training time to check what premises are accessible for a given theorem (program analysis on Lean code), so the retriever never suggests premises that are not in scope. The arXMCP parallel: `search_papers` today has no awareness of which chunks belong to which corpus version — a searcher does not know whether its results predate or postdate the most recent delta ingest. The LeanAgent pattern would manifest as: per-ingest-run tagging of newly ingested chunk IDs, queryable via `get_corpus_delta(since_version=N)` so the fixer agent can tell the autoformalizer "these 47 chunks are new since your search." This is precisely the `get_corpus_delta` tool sketched in Candidate 2.

**Tension with arXMCP philosophy:** LeanAgent requires training a custom retriever on the growing corpus; arXMCP uses a pre-trained BGE-M3 model without fine-tuning. The LeanAgent insight about "progressive training to prevent forgetting" does not directly apply. What applies is the database design: make new additions auditable and queryable by the agent, not just by the operator.

**Architectural fit:** The dynamic-database idea maps to enriching `store-stats.jsonl` with per-version chunk-ID sets and exposing that via a new MCP tool. No model training required. Net-new handler, not a cross-cutting refactor.

**Cache interaction:** No impact on BP1/BP2. A `get_corpus_delta` tool result is not cached via the retrieval cache (ops query; not embedding-based). Tool schema addition requires BP1 hash re-pin.

**Maturity signal:** Code on GitHub (MIT), published at ICLR 2025 (top venue). Active: 162 novel proofs is a strong maturity signal. The specific database mechanism is not the part being borrowed — only the "make incremental additions auditable to the agent" design principle.

---

### Candidate 5: SoK Agentic RAG — Corpus State Divergence as Systemic Risk

**Name + URL:** SoK: Agentic Retrieval-Augmented Generation, arXiv:2603.07379, https://arxiv.org/abs/2603.07379  
**Year + venue:** March 2026, arXiv cs.IR (survey / SoK paper)  
**What it does:** Systematization-of-Knowledge survey covering agentic RAG architectures, taxonomy, evaluation, and open research directions. Models agentic RAG as a finite-horizon POMDP with explicit control policies. Identifies "severe systemic risks inherent to autonomous loops" including: **compounding hallucination propagation** (an agent that cites a stale chunk propagates the error to downstream agents), **memory poisoning** (an agent writes to shared persistent memory using outdated corpus state), **retrieval misalignment** (the retrieval substrate's state changes between agent calls, breaking the agent's implicit "same corpus" assumption), and **cascading tool-execution vulnerabilities** (one tool's bad output becomes the input to the next). Proposes "trajectory evaluation" as a research direction for detecting these failure modes.

**What's NEW vs arXMCP today:** The "retrieval misalignment" failure mode directly names the bug class motivating this scout: the corpus changes between agent calls but the agent has no mechanism to detect this. arXMCP's current mitigation (the `corpus_version: int` field in every envelope) is the right primitive but is only advisory — the agent must choose to notice a version change. The SoK identifies two patterns arXMCP lacks: (a) **corpus-version assertion at the harness layer** — the orchestrator should refuse to combine tool results from different corpus versions in the same reasoning chain (this is the "SagaLLM session corpus guard" from the prior scout run); (b) **trajectory evaluation** — golden-query traces locked to a specific corpus version, run periodically, to detect when the corpus has drifted enough to change retrieval results. arXMCP's `make eval` harness partially covers this for retrieval quality (nDCG@5 fixture) but does not lock the fixture to a specific corpus version.

**Tension:** The SoK positions LLM-based evaluation as the solution to retrieval misalignment; arXMCP's philosophy (CLAUDE.md §2) is that LLM critique is structurally weak. The applicable subset of the SoK is the architecture observations, not the LLM-evaluation prescriptions. The corpus-version assertion belongs in the orchestrator (outside arXMCP) or as a session guard (server/session.py), not as an LLM-facing tool.

**Architectural fit:** (a) `server/session.py` — record `corpus_version_at_session_start`; add `session_corpus_mismatch: bool` to the result envelope when the live version has advanced mid-session. (b) `tests/eval/` — extend the eval fixture runner to record `corpus_version` alongside nDCG@5 so golden-trajectory results are version-stamped. Both are net additions; no cross-cutting refactor.

**Cache interaction:** `session_corpus_mismatch: false` is the common case; it is byte-stable across all calls in a normal session. The rare `true` case (corpus updated mid-session) does not degrade the common-case cache hit rate. Safe per `.claude/notes/07-multi-agent-caching.md` §Property 2.

**Maturity signal:** Survey paper; no code artifacts. SoK papers at major venues have high signal-to-noise — the failure-mode taxonomy is derived from prior work. The "retrieval misalignment" concept independently validates the motivating bug's framing.

---

### Candidate 6: MLOps Data Drift Detection Patterns — Persisted Count vs. Ground Truth

**Name + URL:** Evidently AI (open-source), https://github.com/evidentlyai/evidently (Apache-2.0); production ML monitoring best practices from MLOps literature (e.g. EvidentlyAI blog, Google ML Crash Course §"Production ML Systems")  
**Year + venue:** Ongoing (2025 production MLOps consensus pattern); not a single paper  
**What it does:** Production ML monitoring establishes the pattern: for any derived aggregate (row count, feature distribution, model accuracy), the system should expose BOTH the derived value AND a corresponding "ground truth" measurement, with an alert when they diverge beyond a configurable tolerance. The specific pattern relevant here is **training-serving skew checks** — comparing the distribution assumed at training/index time against what is actually present in the live store. Applied to arXMCP: the marker's `chunk_count` is the "assumed" value; `tbl.count_rows()` is the ground-truth value. arXMCP now has BOTH (post m1/m2 implementation). The MLOps pattern extends to alerting: a divergence > T% triggers a degraded-mode or alarm — which arXMCP also implemented (m2, `chunk_count_diverged` reason in `DegradedState`).

**What's NEW vs arXMCP today:** The m1–m3 implementation covers the core pattern. What the production MLOps literature adds that arXMCP does not yet have: (a) **tolerance-parameterized alerts** — arXMCP's `chunk_count_diverged` degraded mode triggers on ANY divergence (even 1 row off, which could happen if a concurrent external write lands between `merge_insert` and `count_rows()`). MLOps practice uses a configurable tolerance window (e.g. "warn if > 5% drift, degrade if > 20%"). (b) **Time-series trending** — rather than a one-time startup check, arXMCP could emit `arxmcp_corpus_chunk_count_actual` at each ingest completion (not just at server startup) so Prometheus tracks the growth curve. `ingest-summary.json` partially covers this; wiring `INGEST_LAST_RUN_CHUNKS` to Grafana makes it visible as a trend.

**Tension:** None — this is an ops pattern, not a model capability. Consistent with local-first, single-workstation constraints.

**Architectural fit:** (a) Tolerance parameter: `ARXMCP_CHUNK_COUNT_DIVERGENCE_TOLERANCE_PCT` env var consumed by `server/resources.py::startup()` around line 584 (the divergence check block). A float in `[0.0, 1.0]`; default 0.0 (current behavior, any divergence triggers degraded mode). (b) Trend: `INGEST_LAST_RUN_CHUNKS` (already implemented in `server/metrics.py`) + a Grafana dashboard query — zero new server code.

**Cache interaction:** Config-only change in `server/resources.py`; no `tools/list` or prompt cache impact.

**Maturity signal:** Production consensus pattern; not a paper. Evidently AI is widely deployed (100+ metrics, Apache-2.0). The tolerance-threshold pattern is standard enough to be in Google's ML Crash Course.

---

### Candidate 7: FlorDB — Hindsight Logging for ML Pipeline Metadata Audits

**Name + URL:** "Flow with FlorDB: Incremental Context Maintenance for the Machine Learning Lifecycle," arXiv:2408.02498, https://arxiv.org/abs/2408.02498  
**Year + venue:** August 2024, arXiv cs.LG / UC Berkeley  
**What it does:** System that enables "hindsight logging" — adding log statements to ML pipelines post-hoc without rerunning jobs, and querying log metadata as a relational database. The key design: every `logger.info(...)` call with structured fields is captured as a column in a pivoted relational view, enabling SQL queries across multiple pipeline runs. Supports incremental query execution — only new runs since the last query are scanned. Addresses the problem that ML engineers don't know what metadata they'll need until after they discover a bug.

**What's NEW vs arXMCP today:** arXMCP's `write_chunks_complete` event (implemented in m1, `ingest/store.py:961-969`) emits a structured log with `event`, `corpus_version`, `chunk_count`, `paper_count`. This is exactly the FlorDB pattern — structured log field as a queryable column. What arXMCP lacks is the **relational query layer over the JSONL** that would let an operator (or test) run: `SELECT corpus_version, chunk_count, paper_count FROM store-stats WHERE created_at > '2026-05-28'` and immediately see whether any write recorded a suspicious count. FlorDB would enable this; without it, auditing `store-stats.jsonl` requires `jq` scripting. The concrete delta for arXMCP: a `tools/query_store_stats.py` CLI utility (or a `make audit` target) that pivots `store-stats.jsonl` and `var/arxmcp/ops/ingest-summary.json` into a human-readable table comparing per-paper chunk counts against the final marker.

**Tension with arXMCP philosophy:** FlorDB is a full system requiring installation; arXMCP is local-first. The applicable pattern is "treat your structured JSONL logs as queryable tables" — implementable with `jq` or `duckdb` inline on the existing files, not a new dependency. The FlorDB insight motivates the design; arXMCP would implement the query natively.

**Architectural fit:** `tools/query_store_stats.py` — new dev utility that reads `var/arxmcp/ops/store-stats.jsonl` and `ingest-summary.json` and prints a per-paper chunk-count audit table. No server change; no schema change; no test impact. Could also be implemented as a `make audit` Makefile target using `jq`.

**Cache interaction:** Dev utility, not server code. No cache impact.

**Maturity signal:** Paper on arXiv (UC Berkeley); code at https://github.com/ucbrise/flor (BSD-3-Clause). The hindsight logging concept has been cited in ML systems literature (2024–2025). arXMCP would use the design principle natively, not the library (no-fork policy).

---

### Candidate 8: Agentic Harness Engineering — Observability-Driven Evolution

**Name + URL:** "Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses," arXiv:2604.25850  
**Year + venue:** April 2026, arXiv cs.AI  
**What it does:** Framework that uses an evolving agent to automatically refine harness components through three observability mechanisms: (1) component observability — make each editable harness element representable and reversible; (2) experience observability — convert raw trajectory data into digestible evidence the agent can learn from; (3) decision observability — pair each modification with a falsifiable prediction. Improved Terminal-Bench 2 from 69.7% → 77.0% over ten iterations. Positions "falsifiable contracts" as the core pattern for reliable agent harnesses.

**What's NEW vs arXMCP today:** The "falsifiable contracts" framing is the most applicable concept. arXMCP's existing observability (Prometheus gauges, `/readyz` degraded body, structured JSONL logs) provides the raw signal but no automated evolution loop. The specific delta: arXMCP's retrieval cache tier metrics (`cache_hits_total`, `cache_lookups_total` per layer) are exposed at `/metrics` but no alert rule or test validates that cache hit rates stay above a floor when the corpus version is stable. A Prometheus alerting rule `arxmcp_retrieval_cache_hit_rate{layer="tier1"} < 0.3 for 5m` would be a "falsifiable contract" on the retrieval cache — if hit rates drop without a corpus version change, something is wrong (cache key collision, TTL regression, or corpus fragmentation). This pattern is instrumentable with the current metrics infrastructure.

**Tension:** The paper advocates LLM-driven harness evolution; arXMCP explicitly excludes LLMs from the server runtime (CLAUDE.md §4.7). The applicable pattern is the non-LLM observability mechanism: "falsifiable contracts over instrumented components." The LLM-evolution loop is irrelevant to arXMCP's server design.

**Architectural fit:** Alert rules in a Prometheus rule file (e.g. `infra/alerts.yml`) referencing existing metrics. Zero server code change. Can also be expressed as `make check-cache-health` using `promtool` or a simple curl against `/metrics`.

**Cache interaction:** None. Alert rules are evaluated by Prometheus, not by the server.

**Maturity signal:** Paper on arXiv (April 2026). No confirmed code. The observability-mechanism concepts (component/experience/decision observability) are independently implementable and do not require the paper's code.

---

## 3. Sources reviewed

| Paper / framework | URL | Year | Code available | High-signal |
|---|---|---|---|---|
| mcpdiff / mcp-contracts | https://github.com/mcp-contracts/mcp-contracts | 2026 | YES (MIT, npm) | YES |
| VersionRAG | https://arxiv.org/abs/2510.08109 | 2025 | Not confirmed | YES (pattern) |
| OTel GenAI MCP SemConv v1.40 | https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/ | 2025–2026 | N/A (spec) | YES |
| LeanAgent (ICLR 2025) | https://arxiv.org/abs/2410.06209 + https://github.com/lean-dojo/LeanAgent | 2025 | YES (MIT) | YES |
| SoK Agentic RAG | https://arxiv.org/abs/2603.07379 | 2026 | N/A (survey) | YES |
| Evidently AI MLOps patterns | https://github.com/evidentlyai/evidently | 2025 | YES (Apache-2.0) | YES |
| FlorDB (UC Berkeley) | https://arxiv.org/abs/2408.02498 + https://github.com/ucbrise/flor | 2024 | YES (BSD-3-Clause) | YES |
| Agentic Harness Engineering | https://arxiv.org/abs/2604.25850 | 2026 | Not confirmed | MEDIUM |
| LeanDojo / ReProver | https://leandojo.org/ | 2023–2024 | YES (MIT) | LOW (not observability-focused) |
| ALTK Agent Lifecycle Toolkit | https://arxiv.org/abs/2603.15473 | 2025 | YES (Apache-2.0) | MEDIUM (covered by prior scout) |
| SagaLLM | https://arxiv.org/abs/2503.11951 | 2025 | Not confirmed | MEDIUM (covered by prior scout) |
| MCPAgentBench | https://arxiv.org/abs/2512.24565 | 2025–2026 | YES | LOW (covered by prior scout) |
| BPD multi-agent corruption monitoring | https://arxiv.org/abs/2510.19420 + https://github.com/ChengcanWu/BPD | 2025 | YES | LOW (adversarial agents, not corpus metadata) |
| Logging Smells in ML Code | https://arxiv.org/abs/2601.05540 | 2026 | Study-only | LOW (proposed study, no findings yet) |
| Agentic RAG survey | https://arxiv.org/abs/2501.09136 | 2025 | N/A (survey) | LOW (general RAG, not integrity-specific) |

---

## 4. Architectural alignment

Map each candidate to current arXMCP code (post m1–m3, e2–e3 implementation):

- **mcpdiff contract snapshot (Candidate 1):** `server/tools.py::ALL_TOOLS` + `tests/test_server_tool_schema.py` — net-new `.mcpc.json` snapshot artifact, not a code change. The `pytest --update-tool-schema-hash` path in CLAUDE.md §9 step 4 is the natural place to add `.mcpc.json` generation. Zero runtime impact.

- **VersionRAG / get_corpus_delta (Candidate 2):** Net-new `server/handlers/corpus_delta.py` + one entry in `server/tools.py::ALL_TOOLS`. Reads `var/arxmcp/ops/store-stats.jsonl` (already written by `ingest/store.py::_append_store_stats`). Re-pins `EXPECTED_TOOL_SCHEMA_SHA256` per BP1 discipline.

- **OTel `mcp.session.id` + corpus snapshot (Candidate 3):** `server/observability/tracing.py` — add `mcp.session.id` attribute; `server/tools.py::_wrap_with_observability` — pass session header. Separate new `emit_corpus_snapshot_event` helper calling `resources.startup_chunk_count` (already available). Resources instance accessible from app state.

- **LeanAgent dynamic-DB pattern (Candidate 4):** Design insight only — motivates the `get_corpus_delta` tool (Candidate 2). No separate code artifact; feeds Candidate 2's specification.

- **SoK Agentic RAG / session corpus guard (Candidate 5):** (a) `server/session.py` — record `corpus_version_at_session_start` alongside existing per-session caps (line ~90 where session state is initialized). (b) Handler envelope: add advisory `session_corpus_mismatch: bool` field when live version has advanced. (c) `tests/eval/` — extend `fixture/queries.json` to record `corpus_version` alongside golden-query expected results.

- **MLOps tolerance threshold (Candidate 6):** `server/resources.py::startup()` around the divergence check block (line 584+). Add `ARXMCP_CHUNK_COUNT_DIVERGENCE_TOLERANCE_PCT` config var via `server/config.py`. No test change required; existing divergence tests can parameterize tolerance.

- **FlorDB hindsight-log audit (Candidate 7):** Net-new `tools/query_store_stats.py` dev utility or `make audit` Makefile target. Reads existing `var/arxmcp/ops/store-stats.jsonl` + `ingest-summary.json`. No server change; no schema change.

- **Agentic Harness falsifiable contracts (Candidate 8):** Net-new `infra/alerts.yml` Prometheus rule file. References existing metrics: `arxmcp_retrieval_cache_hits_total`, `arxmcp_retrieval_cache_lookups_total`, `arxmcp_corpus_chunk_count_marker`, `arxmcp_corpus_chunk_count_actual`. Zero server code change.

---

## 5. Themes

The multi-agent observability literature in 2025–2026 converges on **"metadata-state divergence as a first-class failure mode"** — not just "did the tool error?" but "is the tool's reported state consistent with ground truth?" This framing validates arXMCP's post-m1/m2 implementation but also reveals the next gap: the current fix is entirely **server-side and operator-facing** (Prometheus gauges, degraded `/readyz`, JSONL audit log), while the calling agent has no actionable signal when the corpus evolves between its calls. The emerging pattern is to expose corpus-change information *to the agent* via versioned diffs (`get_corpus_delta`) and session-level corpus snapshots (OTel events), closing the loop from "the server knows the corpus changed" to "the agent can ask what changed and adapt." A secondary theme: **falsifiable contracts** — the agentic harness engineering literature is converging on the idea that every instrumented component should have a testable invariant (cache hit floor, count-divergence tolerance, version-schema hash pin), not just a metric. arXMCP has several of these (tool schema hash, startup reconciliation check) but lacks the alert-rule layer that would make them actionable without manual dashboard inspection.

---

## 6. Out of scope / parking lot

- **BPD multi-agent corruption monitoring (arXiv:2510.19420):** Detects adversarial agents injecting misleading information via signed directed graphs. Rejected: addresses adversarial multi-agent systems, not corpus metadata divergence. Out of scope for this bug class.

- **ALTK Agent Lifecycle Toolkit (arXiv:2603.15473):** Covered exhaustively by the prior scout run (2026-05-28); Candidate 2 in that run's brief. The startup-invariant pattern from ALTK has shipped in corpus-integrity-observability-m2. No residual delta.

- **SagaLLM (arXiv:2503.11951):** Session corpus guard concept noted here as Candidate 5 (via SoK Agentic RAG lens). Full SagaLLM treatment covered by prior scout. No new delta.

- **NabaOS tool receipts (arXiv:2603.10060):** Corpus integrity token pattern covered by prior scout (multi-agent Candidate 3). Not yet implemented; the pattern remains valid but the paper has no code and ranks behind the implemented items.

- **Logging smells in ML code (arXiv:2601.05540):** Submitted January 2026 as a proposed study; no findings published. Low-signal until results land.

- **LeanDojo / ReProver corpus integrity:** LeanDojo's premise-accessibility analysis is about *semantic* corpus integrity (which premises are logically accessible for a given theorem) rather than *metadata* integrity (whether persisted counts match the live store). Out of scope for the motivating bug class.

- **Evidently AI drift detection (distribution-level):** Evidently's full statistical drift detection (Wasserstein distance, PSI, KS tests) operates on feature distributions, not on row counts. The simpler tolerance-threshold pattern (Candidate 6) captures the arXMCP-relevant subset without the dependency.

- **FrontierMath / AutoFormalization pipeline corpus build:** The Draft-Sketch-Prove pipeline and DeepSeek-Prover-V2 corpus build do not expose corpus manifest integrity patterns relevant to the motivating bug; they operate over curated hand-verified datasets, not incrementally ingested rolling corpora.
