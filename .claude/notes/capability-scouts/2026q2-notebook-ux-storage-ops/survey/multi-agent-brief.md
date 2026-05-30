# Multi-Agent Capability Scout Brief
# 2026q2 — Notebook UX, Storage, Operability, Packaging
# Scout ID: 2026q2-notebook-ux-storage-ops

**Date:** 2026-05-28
**Scope theme:** Notebook management UX + durable notebook storage + operability + container packaging
**arXMCP current state baseline:** per-notebook LanceDB served by `ARXMCP_NOTEBOOK` (process) or `filters.notebook` (per-call); Jinja2 + htmx human web UI at `/ui`; SQLite notebook metadata in `notebooks.db`; async ingest subprocess with DB-tracked run state; `/healthz` /readyz` `/metrics`; Dockerfile but no compose; 7-tool MCP surface with `EXPECTED_TOOL_SCHEMA_SHA256` pinned.

---

## 1. TL;DR

**Top-3 multi-agent capabilities to consider:**

1. **MCP resource surface for notebooks** — MCP 2025-06-18 defines `resources/list`, `resources/read`, resource URI templates, `resources/subscribe`, and `notifications/resources/list_changed`; arXMCP exposes notebooks only through a human web UI and an env-var process switch. Making notebooks first-class MCP resources would let the agent itself enumerate, select, and watch ingest status without any human UI interaction.

2. **`notifications/tools/list_changed` + agent-driven corpus management tools** — Claude Code v2.1.121+ supports dynamic tool updates via `list_changed` notifications. Adding a small set of notebook-management MCP tools (list/create/status) would let the agent pipeline manage its own corpus lifecycle, but every tool addition forces an `EXPECTED_TOOL_SCHEMA_SHA256` re-pin (BP1 interaction — see §2 entries).

3. **Compose packaging for reproducible local deployment** — Docker Compose with `depends_on: condition: service_healthy` wiring `arxmcp-shim → arxmcp-server` would replace the current bare-Dockerfile + manual-`make up` operator workflow, giving the harness a deterministic corpus-version-pinned boot sequence that matches what production agent deployments expect.

**Main architectural gap:** arXMCP's notebook management is human-UI-only. There is no agent-facing API (MCP tool, MCP resource, or MCP logging notification) to enumerate notebooks, check ingest status, or learn when a newly-added paper is retrievable. The pipeline's sketcher/autoformalizer agents cannot self-direct corpus curation without human mediation.

---

## 2. Multi-agent candidates

---

### Candidate 1 — MCP Resources + Subscriptions (MCP Spec 2025-06-18)

**Name + citation/URL:** MCP Resources specification, modelcontextprotocol.io/specification/2025-06-18/server/resources
**Year + venue:** 2025-06-18, Model Context Protocol specification
**What it does:** The MCP spec defines a `resources` server capability with four sub-features: `resources/list` (paginated, with cursors), `resources/read` (by URI), `resources/templates/list` (parameterized URI templates with RFC 6570), and `resources/subscribe` + `notifications/resources/updated` (push-notify client on resource content change). The `listChanged: true` server capability causes the server to emit `notifications/resources/list_changed` when the resource catalogue changes — for example when a notebook is created or ingest completes. Resource annotations carry `audience` (user vs assistant), `priority` (0–1), and `lastModified` (ISO 8601). Claude Code supports `@server:uri` resource references in prompts and fetches resource content as attachments.

**What's NEW vs arXMCP today:** arXMCP declares `arxmcp://chunks/<chunk_id>`, `arxmcp://papers/<paper_id>`, etc. as resource URIs in `server/tools.py`'s `resource_link` content blocks (see `server/handlers/search.py`), but the server does NOT register the `resources` capability or wire `resources/list` / `resources/read` handlers. Notebooks are wholly absent from the MCP resource surface — they exist only in the human web UI and the process-env switch. A `resources/list` that enumerates notebooks with `arxmcp://notebooks/<slug>` URIs and annotates each with `lastModified` (from `notebooks.db:created_at`) and `priority` (based on ingest status) would let any agent call `resources/list` to discover what corpora are available, then `resources/subscribe` to watch for ingest completion.

**Architectural fit:**
- Net-new: `server/handlers/resources.py` (list + read handlers)
- Net-new: capability advertisement in `server/_mcp_mount.py` at the `initialize` response
- Extend: `server/notebooks_store.py` to provide `list_notebooks()` as the backing query for `arxmcp://notebooks/<slug>` resources
- Optional: `resources/subscribe` handler that polls `IngestTaskTracker.is_running(slug)` and fires `notifications/resources/updated` on state change
- No new tool added → no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin required (resources are a separate capability)

**Cache interaction:** Adding `resources` capability does NOT change the `tools/list` response byte content. BP1 is safe. If a `resource_link` is returned inside a tool result's `content` array (already done in `search_papers`), the link URI must be deterministic — which it already is since chunk URIs are content-addressable. The `listChanged` notification fires outside the tools call chain and has no effect on BP1/BP2 prompt-cache breakpoints. See `.claude/notes/07-multi-agent-caching.md` §"Property 1: Tool definitions are byte-stable".

**Maturity signal:** Spec-normative. Claude Code v2.1.121+ supports `@server:uri` resource references in prompts. Production deployment confirmed in Claude Code docs (code.claude.com/docs/en/mcp §"Use MCP resources"). The `subscribe` feature has an open feature-request in the opencode project (github.com/anomalyco/opencode/issues/12092), suggesting mainstream harness support is 3–6 months behind the spec.

---

### Candidate 2 — MCP Logging Notifications for Ingest Progress (MCP Spec 2025-06-18)

**Name + citation/URL:** MCP Logging + Progress specifications, modelcontextprotocol.io/specification/2025-06-18/server/utilities/logging, modelcontextprotocol.io/specification/2025-06-18/basic/utilities/progress
**Year + venue:** 2025-06-18, Model Context Protocol specification
**What it does:** The MCP `logging` capability lets a server emit `notifications/message` with syslog-level severity (`debug`, `info`, `notice`, `warning`, `error`, `critical`, `alert`, `emergency`), a logger name, and arbitrary JSON-serializable data. The `progress` primitive lets a request include a `progressToken` in `_meta`; the server then emits `notifications/progress` with `progress`, `total`, and `message` fields (progress value must increase monotonically). Together these give an agent real-time visibility into a long-running server operation such as an ingest subprocess, without polling.

**What's NEW vs arXMCP today:** arXMCP currently provides ingest status only via HTTP polling of `GET /ui/api/notebooks/{slug}/ingest-status` (a human-UI endpoint) — there is no MCP-native signal. An agent that triggers ingest via a future notebook-management tool has no way to learn when indexing completes except by repeatedly calling a status-query tool. Emitting `notifications/message` with `logger="ingest"` and structured `data={slug, status, papers_done, papers_total}` from `IngestTaskTracker._run_ingest_subprocess()` (at `server/ingest_tracker.py:193`) would give any connected MCP client a push-delivered ingest feed. The `progress` primitive is a stronger contract: an ingest tool call that returns a `progressToken` could drive real-time `progress: N / total: M` notifications as each paper is parsed and embedded.

**Architectural fit:**
- Extend: `server/ingest_tracker.py:_run_ingest_subprocess` to emit `notifications/message` at `info` level on subprocess stdout lines (already captured via `PIPE`)
- Extend: `server/_mcp_mount.py` to advertise `logging: {}` in the `initialize` response capabilities
- Optional: wire `progressToken` through a future notebook-management tool so agents get fine-grained ingest progress
- No tool surface change → no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin required

**Cache interaction:** `notifications/message` and `notifications/progress` are server-sent notifications, not tool results. They do not appear in tool result blocks and have no effect on BP1/BP2 prompt-cache prefixes. However, if an agent inserts logging content into its conversation history (which a well-designed agent should not do for cache reasons), that would drift the prefix. The harness must not insert log notifications into the message history. See `.claude/notes/07-multi-agent-caching.md` §"Property 2: Tool result payloads are canonicalized".

**Maturity signal:** Spec-normative. The `logging` capability is widely implemented (FastMCP supports it natively). The `progress` primitive is spec-normative but harness support is uneven — Claude Code honors `notifications/progress` for heartbeat purposes and resets per-request timeouts on receipt, but does not display progress values in the terminal UI.

---

### Candidate 3 — MCP tools/list `listChanged` + Notebook Management Tools (MCP Spec 2025-06-18)

**Name + citation/URL:** MCP `tools/list` `listChanged` capability, modelcontextprotocol.io/specification/2025-06-18/server/tools; Claude Code dynamic tool update support, code.claude.com/docs/en/mcp §"Dynamic tool updates"
**Year + venue:** 2025-06-18 spec; Claude Code v2.1.121+ (2026)
**What it does:** The MCP tools capability includes `listChanged: true`, allowing a server to emit `notifications/tools/list_changed` when its tool set changes. Claude Code v2.1.121+ handles these notifications and refreshes the tool set without disconnecting. Combined with `tools/list outputSchema` (also 2025-06-18), tools can declare a JSON Schema for their structured return value, enabling harness-side validation. This enables dynamic tool surfaces: a server that starts with 7 tools could, after corpus initialization, emit `list_changed` and expose additional notebook-specific tools.

**What's NEW vs arXMCP today:** arXMCP's 7-tool surface is static and hard-pinned by `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py`. Adding notebook-management tools (`list_notebooks`, `get_notebook_status`, `trigger_ingest`) would let the agent pipeline self-direct corpus curation. The concrete gap: an agent currently cannot learn what notebooks exist, whether ingest is running, or what papers are indexed without going through the human web UI. Three targeted read-only tools would close this: (1) `list_notebooks` → returns slugs + ingest status from `NotebooksStore`; (2) `get_notebook_status` → returns latest ingest run state from `notebook_ingest_runs`; (3) a read-only view into indexed paper count per notebook.

**Architectural fit:**
- New tools: `server/handlers/notebooks_mcp.py` (list + status, no write operations v1)
- Extend: `server/tools.py::ALL_TOOLS` (3 new `ToolMeta` entries)
- MANDATORY re-pin: `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` via `pytest --update-tool-schema-hash` — this is the most load-bearing consequence. See CLAUDE.md §9 "Add a new tool to the MCP surface".
- Extends BP1 prefix byte content → every sub-agent's prompt cache is invalidated on next cold start. This is acceptable if tool additions are batched (avoid adding 1 tool at a time).

**Cache interaction:** Any tool added to `ALL_TOOLS` changes the `tools/list` response bytes, invalidating BP1 for all agents on the next `tools/list` fetch. This is the highest-cost interaction in arXMCP's caching architecture. Mitigation: batch all notebook-management tools into a single schema bump; re-pin once; let all agents repopulate their caches in the following session. See `.claude/notes/07-multi-agent-caching.md` §"Property 1: Tool definitions are byte-stable" and CLAUDE.md §9 step 4. The `listChanged` notification itself does not affect cache — it triggers a `tools/list` re-fetch, but the new hash becomes the new stable BP1 anchor.

**Maturity signal:** `listChanged` is spec-normative and Claude Code v2.1.121+ implements it. Gemini CLI has an open issue for it (github.com/google-gemini/gemini-cli/issues/13850). The `outputSchema` field on tools is new in 2025-06-18 and arXMCP does not yet use it — but it offers a concrete improvement path for structured-result validation at the harness layer.

---

### Candidate 4 — Docker Compose with `service_healthy` Dependency Chain

**Name + citation/URL:** Docker Compose `depends_on: condition: service_healthy`, docs.docker.com/reference/compose-file/services/#depends_on; Docker MCP Toolkit, docs.docker.com/ai/mcp-catalog-and-toolkit/toolkit/; mcp-compose (phildougherty), github.com/phildougherty/mcp-compose
**Year + venue:** Docker Compose v2 (2024–2025 current spec); Docker MCP Toolkit GA late 2025
**What it does:** Docker Compose `depends_on` with `condition: service_healthy` delays the start of dependent services until the health check of their dependency passes. For arXMCP this means the shim container or any agent container would not attempt MCP tool calls until `GET http://arxmcp-server:7733/readyz` returns HTTP 200 — i.e., until BGE-M3, LanceDB, and the reranker are all warm. The `mcp-compose` project adds MCP-specific orchestration on top, including a unified HTTP gateway that translates stdio servers to HTTP and pools connections. Docker Compose volumes provide corpus data persistence across container restarts.

**What's NEW vs arXMCP today:** arXMCP ships a `Dockerfile.server` (multi-stage, non-root, tini, HEALTHCHECK on `/readyz`) but no `compose.yaml`. The shim (`shim/arxmcp_shim.py`) already probes `/readyz` before the first tool call, but this is a per-process check with no cross-container orchestration. A `compose.yaml` with:
- `arxmcp-server` service: `healthcheck: test: ["CMD", "curl", "-f", "http://localhost:7733/readyz"]` + volume mount for `var/arxmcp/`
- `arxmcp-shim` (optional): `depends_on: arxmcp-server: condition: service_healthy`
- Named volume: `arxmcp-corpus: driver: local` → mounted to `/var/arxmcp` in the server container

would give operators a one-command reproducible deployment (`docker compose up`) that correctly sequences BGE-M3 warmup before any agent is allowed to call tools. It also enables corpus portability: export the named volume, move to a new workstation, restore — the same corpus version is pinned.

**Architectural fit:**
- Net-new: `docker/compose.yaml` (or `compose.yaml` at repo root) — follows CLAUDE.md §5 layout (Dockerfile already in `docker/`)
- Extend: `infra/README.md` (placeholder currently references E14 docker-compose)
- No server code change required; the `/readyz` endpoint already exists in `server/health.py`
- No BP1/BP2 interaction (packaging, not tool surface)

**Cache interaction:** None. Docker Compose is infrastructure; it has no effect on the MCP `tools/list` byte content or prompt-cache breakpoints. The corpus_version pinning in `server/corpus.py` (via `corpus-version.json`) is the application-layer mechanism; Docker volumes are the persistence layer underneath it.

**Maturity signal:** Docker Compose `service_healthy` pattern is standard and widely used. Docker MCP Toolkit is GA (late 2025) and supports volume mounting. `mcp-compose` is an open-source project with STDIO→HTTP proxy capability but is not production-grade. The Compose pattern itself is the durable recommendation; `mcp-compose` is a study-only reference.

---

### Candidate 5 — MCP Initialization `instructions` Field for Agent Corpus Orientation

**Name + citation/URL:** MCP lifecycle `initialize` response `instructions` field, modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
**Year + venue:** 2025-06-18, Model Context Protocol specification
**What it does:** The MCP `initialize` response can include an optional `instructions` field: a string that tells the connecting client (agent) how to use the server. This is the server-side analogue of the agent's system prompt — a single opportunity for the server to orient any freshly-connected agent before the first tool call. Claude Code's "Tool Search" feature (default-on as of v2.1.121) uses this field to decide when to surface the server's tools; the spec says "Optional instructions for the client." It is distinct from per-tool `description` fields — it describes the server as a whole, its corpus context, its notebook topology.

**What's NEW vs arXMCP today:** arXMCP's `SYSTEM_PROMPT` in `server/prompts.py:6` is explicitly noted as "still a placeholder" in CLAUDE.md §8 gotcha 6. The `initialize` response in `server/_mcp_mount.py` currently does not set `instructions`. A well-crafted `instructions` value would tell the connecting agent: "This server hosts a research-mathematics corpus. Active notebooks: [list from NotebooksStore]. Corpus version: N. Use `search_papers` with `filters.notebook` to scope queries." Since `instructions` is returned at `initialize`, it is fetched once per session and does not appear in `tools/list` — it is NOT part of the BP1 cache key. It IS part of the agent's system prompt context for the session.

**Architectural fit:**
- Extend: `server/_mcp_mount.py` — populate `instructions` in the `initialize` response from `NotebooksStore.list_notebooks()` + `corpus_version`
- Extend: `server/prompts.py` — author the `SYSTEM_PROMPT` constant that was previously a placeholder; this fires the `EXPECTED_BP1_SHA256` re-pin in `tests/test_prompts.py`
- Low cost: no new tools, no resource handlers, no schema change

**Cache interaction:** The `instructions` field is returned at connection time and is outside the `tools/list` byte content. It does NOT affect `EXPECTED_TOOL_SCHEMA_SHA256`. It IS part of the session-level system prompt, and if an agent includes it verbatim in the messages array, it participates in BP1 prompt-cache logic. Crucially: `instructions` content that varies per-connection (e.g., includes a live notebook list) would be session-unique and would break BP1 cache hits across different sessions. Recommendation: keep `instructions` static or near-static (a version-pinned corpus description, not a live notebook enumeration). Dynamic notebook state should be surfaced via `resources/list`, not `instructions`. See `.claude/notes/07-multi-agent-caching.md` §"Property 1" and `.claude/notes/prompts-bp-discipline.md` for the BP1/BP2 breakpoint placement doc.

**Maturity signal:** Spec-normative. Claude Code's Tool Search feature specifically uses `instructions` to decide when to emit `ToolSearch` calls — making it practically high-value for discoverability. No code required beyond a string constant authoring decision.

---

### Candidate 6 — NotebookLM Enterprise API Pattern: CRUD + Async Ingest Status

**Name + citation/URL:** NotebookLM Enterprise Notebooks API, docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/api-notebooks; Add and manage data sources API, docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/api-notebooks-sources
**Year + venue:** 2025 (GA), Google Cloud NotebookLM Enterprise
**What it does:** The NotebookLM Enterprise API exposes a full CRUD surface for notebook management: `notebooks.create`, `notebooks.get`, `notebooks.listRecentlyViewed`, `notebooks.batchDelete`, `notebooks.share`. The source management sub-API handles async source ingestion — text, Google Docs, URLs — with sources typically becoming queryable within 5–30 seconds after `add_source`. The API also integrates with Google Agentspace so agents can search notebook titles and retrieve information as a structured data store. This is the most production-deployed equivalent of what arXMCP's notebook layer is building.

**What's NEW vs arXMCP today:** The NotebookLM pattern is evidence that "notebook as a managed resource" is the right abstraction for LLM-serving systems — not just a human UI concern. The specific delta for arXMCP: NotebookLM's `add_source` returns quickly and sources become queryable async; arXMCP's ingest is fully async (via `IngestTaskTracker`) but there is NO agent-facing API to add a paper and watch it become retrievable. The pattern to adopt: an MCP tool `add_paper_to_notebook(notebook_slug, arxiv_id)` that (a) adds the paper to `notebook_papers`, (b) optionally triggers a delta-ingest, and (c) returns a resource URI that can be subscribed to (Candidate 1) or polled (Candidate 2) for ingest completion.

**Architectural fit:**
- This is primarily a design-pattern reference, not a direct dependency
- Informs the shape of future MCP tools for notebook management (Candidate 3)
- Architecture-lock note: NotebookLM Enterprise is a cloud service that calls LLMs server-side — arXMCP must NOT replicate this pattern. arXMCP is a tool provider; LLM calls live in the calling agent.
- No immediate code change; validates the direction of Candidates 1–3

**Cache interaction:** N/A (reference pattern only). Any notebook-management tool added following this pattern would carry the same `EXPECTED_TOOL_SCHEMA_SHA256` consequence as Candidate 3.

**Maturity signal:** Production GA (Google Cloud, 2025). REST API with well-defined CRUD semantics. Not open-source; study for shape only per CLAUDE.md §4.7 no-fork policy.

---

### Candidate 7 — gnosis-mcp: Self-Hosted Doc-Search MCP with Health + Resource Listing

**Name + citation/URL:** gnosis-mcp, github.com/nicholasglazer/gnosis-mcp; gnosismcp.com
**Year + venue:** 2025, open-source (license: MIT per PyPI listing)
**What it does:** gnosis-mcp is a zero-config local MCP server for searchable documentation. It exposes 9 tools (6 read, 3 write with `GNOSIS_MCP_WRITABLE=true`): `search_docs`, `get_doc`, `get_related`, `search_git_history`, `get_context`, `get_graph_stats`, `upsert_doc`, `delete_doc`, `update_metadata`. It uses SQLite + BM25 + ONNX local embeddings fused via RRF. Critically, it exposes: (a) a `gnosis://docs` MCP resource that lists all indexed documents with path, title, category, chunk count; (b) a `GET /health` REST endpoint returning version + document/chunk counts; and (c) a `gnosis-mcp check` CLI command for verifying DB connectivity. This is the closest open-source analogue to arXMCP's notebook layer.

**What's NEW vs arXMCP today:** Three concrete deltas: (1) gnosis exposes indexed content as a live MCP resource (`gnosis://docs`) — arXMCP has no equivalent; agents must infer what's indexed from search results. (2) gnosis's `get_graph_stats` tool returns corpus topology (orphans, hubs, relation distribution) — arXMCP has no corpus-health tool. (3) gnosis's `/health` REST endpoint returns document + chunk counts that both the operator and agent can query for corpus sanity checking — arXMCP's `/healthz` returns only process liveness; `/readyz` returns model warmup; there is no "N papers, M chunks indexed" signal in any HTTP endpoint.

**Architectural fit:**
- Informs: adding a `gnosis://docs`-equivalent MCP resource at `arxmcp://notebooks` (Candidate 1)
- Informs: adding a `get_corpus_stats` read-only MCP tool (candidate for Candidate 3 batch)
- Extend: `server/health.py` — add corpus document/chunk count to `/readyz` response JSON (or a new `/stats` endpoint) — no tool surface change, no BP1 interaction
- Study-only: no-fork policy; gnosis is MIT-licensed

**Cache interaction:** Adding a `get_corpus_stats` tool would require `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. The `/readyz` extension would not. Prefer extending `/readyz` for operator operability; expose corpus stats to agents via a resource endpoint rather than a new tool to avoid the BP1 cost.

**Maturity signal:** Active GitHub project, PyPI-published (`pip install gnosis-mcp`), MIT license, recent benchmark documentation showing nDCG@10 = 0.87. Code available; design patterns are concrete. No production citations beyond the repo's own documentation.

---

### Candidate 8 — Claude Code MCP Operability Contract: `/mcp`, `listChanged`, reconnect

**Name + citation/URL:** Claude Code MCP documentation, code.claude.com/docs/en/mcp; Claude Code v2.1.121+ release notes
**Year + venue:** 2025–2026, Anthropic Claude Code
**What it does:** Claude Code v2.1.121+ defines a concrete operability contract between a local MCP server and the Claude agent harness: (1) `/mcp` panel shows tool count per server and flags servers that advertise `tools` capability but expose zero tools; (2) `list_changed` notifications are supported — the harness refreshes capabilities without disconnect; (3) exponential-backoff reconnect (5 attempts, 1s/2s/4s/8s/16s) for HTTP servers; (4) `MCP_TIMEOUT` env var for startup timeout; (5) `alwaysLoad: true` flag in `.mcp.json` to preload a specific server's tools synchronously on session start (vs the default deferred tool search); (6) `_meta["anthropic/maxResultSizeChars"]` annotation on tool definitions raises the per-tool result size cap. Additionally, `MCP_TOOL_TIMEOUT` env var sets a per-server per-call wall-clock limit. The `initialize` response's `instructions` field is actively used by Tool Search to decide when to surface the server's tools.

**What's NEW vs arXMCP today:** arXMCP does not advertise `tools: { listChanged: true }` in its `initialize` response — it cannot signal tool set changes to connected agents even when notebook-management tools are later added without restart. The `_meta["anthropic/maxResultSizeChars"]` annotation is not used on any of the 7 tools — large `get_chunk` results (full theorem bodies can exceed 10K tokens) risk being silently truncated or disk-offloaded by the harness. The `alwaysLoad: true` flag in `.mcp.json` gives arXMCP an explicit control knob: because arXMCP tools are always needed in a math pipeline session, declaring `alwaysLoad: true` would guarantee they load at session start rather than being deferred by Tool Search.

**Architectural fit:**
- Extend: `server/_mcp_mount.py` — advertise `tools: { listChanged: true }` in `initialize` response (zero runtime cost; enables future dynamic updates)
- Extend: `server/tools.py::ALL_TOOLS` — add `_meta["anthropic/maxResultSizeChars"]` annotations to `get_chunk` and `find_equation` tools (these return large content). Adding `_meta` fields does NOT change the JSON Schema visible to the LLM — it is harness-metadata only. Verify whether this counts as a byte-stable change for `EXPECTED_TOOL_SCHEMA_SHA256`.
- Docs: `docs/install.md` — document `alwaysLoad: true` in the `.mcp.json` registration example

**Cache interaction:** Adding `_meta` fields to tool definitions in `tools/list` response WOULD change the byte content of `tools/list`, requiring `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. This is mandatory per CLAUDE.md §9 step 4. Adding `tools: { listChanged: true }` to the `initialize` capabilities response does NOT affect `tools/list` byte content — the capabilities are in the `initialize` result, not the `tools/list` result. Separate requests, separate hashes. See `.claude/notes/07-multi-agent-caching.md` §"Property 1".

**Maturity signal:** Production-confirmed Claude Code behavior, fully documented at code.claude.com. All features verified via official Claude Code docs (v2.1.121+, 2026). No paper citation required — this is first-party harness behavior.

---

### Candidate 9 — Agentic RAG Survey: Shared Knowledge Base Stewardship Gap

**Name + citation/URL:** "Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG," arXiv:2501.09136 (Yang et al., January 2025)
**Year + venue:** January 2025, arXiv cs.IR
**What it does:** Comprehensive taxonomy of agentic RAG architectures across single-agent and multi-agent configurations. Covers: reflection, planning, tool-use, multi-agent collaboration, specialized retrieval agents, parallel processing, and Agentic Document Workflows (ADW). The survey's multi-agent section describes specialized retrieval agents that handle different data sources with parallel queries, and notes that agents "communicate and share intermediate results."

**What's NEW vs arXMCP today:** The survey identifies a gap that directly applies to arXMCP: it covers retrieval workflows extensively but NOT corpus governance — the pattern of an agent adding a document, waiting for it to be indexed, and then retrieving it. This absence is diagnostic: there is no widely-studied framework pattern for "agent-driven corpus update → ingest status → retrieval." arXMCP's ingest tracker + `notebook_ingest_runs` DB table constitutes a partial implementation of a pattern the research community has not yet named or formalized. The concrete implication: arXMCP is ahead of the research literature on this specific sub-problem, and the right architectural direction (async ingest subprocess + DB-tracked state + agent-queryable status) is sound.

**Architectural fit:**
- Primarily a validation reference — confirms arXMCP's current design is correct
- Informs: the absence of a published standard for corpus-management APIs means arXMCP should design its own simple pattern rather than waiting for an emerging standard
- Reinforces: Candidate 1 (resources), Candidate 2 (logging), and Candidate 3 (notebook-management tools) are the right building blocks

**Cache interaction:** Reference only. No direct cache interaction.

**Maturity signal:** arXiv preprint, January 2025. Paper available; no code repository cited. Primarily useful as a gap analysis confirming arXMCP's direction.

---

## 3. Sources reviewed

| Paper / framework / spec | URL | Year | Code available | High-signal? |
|---|---|---|---|---|
| MCP Resources spec (2025-06-18) | modelcontextprotocol.io/specification/2025-06-18/server/resources | 2025 | SDK (python-sdk, TypeScript) | YES |
| MCP Logging spec (2025-06-18) | modelcontextprotocol.io/specification/2025-06-18/server/utilities/logging | 2025 | SDK | YES |
| MCP Progress spec (2025-06-18) | modelcontextprotocol.io/specification/2025-06-18/basic/utilities/progress | 2025 | SDK | YES |
| MCP Tools spec (2025-06-18) | modelcontextprotocol.io/specification/2025-06-18/server/tools | 2025 | SDK | YES |
| MCP Lifecycle spec (2025-06-18) | modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle | 2025 | SDK | YES |
| MCP Roots spec (2025-06-18) | modelcontextprotocol.io/specification/2025-06-18/client/roots | 2025 | SDK | LOW (client-side only) |
| Claude Code MCP docs (v2.1.121+) | code.claude.com/docs/en/mcp | 2026 | Anthropic product | YES |
| MCP 2026 Roadmap | blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/ | 2026 | N/A | YES (gap analysis) |
| NotebookLM Enterprise API | docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/api-notebooks | 2025 | No (cloud API) | YES (pattern ref) |
| gnosis-mcp | github.com/nicholasglazer/gnosis-mcp | 2025 | YES (MIT) | YES |
| Context7 MCP | github.com/upstash/context7 | 2025 | YES (MIT) | MEDIUM |
| OpenAI Vector Store MCP | github.com/jezweb/openai-vector-assistant-mcp | 2025 | YES (MIT) | MEDIUM |
| mcp-compose | github.com/phildougherty/mcp-compose | 2025 | YES (unknown license) | MEDIUM |
| Docker MCP Toolkit | docs.docker.com/ai/mcp-catalog-and-toolkit/toolkit/ | 2025 | Partial (Docker product) | MEDIUM |
| Agentic RAG Survey (arXiv:2501.09136) | arxiv.org/abs/2501.09136 | 2025 | No | MEDIUM (gap validator) |
| A-RAG (arXiv:2602.03442) | arxiv.org/abs/2602.03442 | 2026 | Partial | LOW (retrieval, not mgmt) |
| mcp-agent (lastmile-ai) | github.com/lastmile-ai/mcp-agent | 2025 | YES (Apache-2.0) | LOW (harness lifecycle only) |
| PulseMCP client capability gap | pulsemcp.com/posts/mcp-client-capabilities-gap | 2025 | No | MEDIUM |
| Docker Compose healthcheck patterns | docs.docker.com/reference/compose-file/services/#healthcheck | 2025 | N/A (standard) | YES |

---

## 4. Architectural alignment

Each candidate mapped to arXMCP's current shape:

| Candidate | arXMCP file:line / net-new | Type |
|---|---|---|
| C1: MCP Resources + Subscriptions | Net-new `server/handlers/resources.py`; extend `server/_mcp_mount.py` (capabilities); `server/notebooks_store.py::list_notebooks` already provides the backing query | Net-new handler + capability |
| C2: MCP Logging for Ingest Progress | Extend `server/ingest_tracker.py:193::_run_ingest_subprocess` to emit MCP notifications; extend `server/_mcp_mount.py` to advertise `logging: {}` | Extend existing infrastructure |
| C3: `listChanged` + Notebook Management Tools | Net-new `server/handlers/notebooks_mcp.py`; extend `server/tools.py::ALL_TOOLS`; MANDATORY `tests/test_server_tool_schema.py` re-pin | New tools (high BP1 cost) |
| C4: Docker Compose packaging | Net-new `docker/compose.yaml`; extend `infra/README.md`; no server code change | Infrastructure |
| C5: `initialize` `instructions` field | Extend `server/_mcp_mount.py::initialize_handler`; extend `server/prompts.py` (author `SYSTEM_PROMPT`) → fires `tests/test_prompts.py::EXPECTED_BP1_SHA256` re-pin | Low-cost capability extension |
| C6: NotebookLM API pattern | Reference only; informs Candidates 1–3 | Design pattern |
| C7: gnosis-mcp patterns | Extend `server/health.py` — add chunk/paper count to `/readyz` JSON; informs C1 (resources); study-only for tools | Extend health endpoint |
| C8: Claude Code operability contract | Extend `server/_mcp_mount.py` (`tools: {listChanged: true}` in capabilities); extend `server/tools.py` (`_meta["anthropic/maxResultSizeChars"]`); extend `docs/install.md` (alwaysLoad) | Protocol compliance + docs |
| C9: Agentic RAG survey gap | Reference only; validates arXMCP's ingest-tracker design direction | Gap validation |

**Priority ranking by implementation effort vs delta value:**

1. **C5 (instructions field)** — 1-day effort, zero test changes except prompt hash re-pin, immediate agent discoverability benefit.
2. **C4 (Compose packaging)** — 1-day effort, no code changes, closes the `infra/README.md` placeholder, operator QoL.
3. **C8 (operability contract / listChanged + maxResultSizeChars)** — 0.5-day effort for capabilities; forces `EXPECTED_TOOL_SCHEMA_SHA256` re-pin for `_meta` additions; net improvement to harness behavior.
4. **C1 (resources)** — 2-3 day effort, zero BP1 cost, highest agent-facing capability uplift for corpus visibility.
5. **C2 (logging)** — 1-day effort once C3 (or a future notebook tool) provides the trigger mechanism; zero BP1 cost.
6. **C3 (notebook management tools)** — 2-3 day effort + mandatory BP1 cache invalidation; should be batched with C8 to minimize schema bumps.

---

## 5. Themes

**Theme 1: The MCP spec has matured well beyond what arXMCP currently declares.** The 2025-06-18 spec defines resources (with subscriptions), logging notifications, progress tokens, and the `instructions` field — none of which arXMCP advertises in its `initialize` response. The highest-leverage move is not adding new tools but declaring existing capabilities: `resources`, `logging`, `tools: {listChanged: true}` in the `initialize` response advertises that the server is a first-class participant in the agent ecosystem.

**Theme 2: Agent-facing corpus management is an unsolved problem in the research literature.** The Agentic RAG survey (arXiv:2501.09136) does not cover corpus governance. The NotebookLM API and gnosis-mcp both solve the "list + status" subproblem but neither provides async ingest-status push notifications. arXMCP's existing `IngestTaskTracker` + `notebook_ingest_runs` design is structurally ahead of published patterns — the gap is surfacing this state via MCP rather than only via the human web UI.

**Theme 3: Docker Compose is the expected packaging primitive for local-first MCP servers.** Docker MCP Toolkit (GA late 2025), mcp-compose, and the broader ecosystem have converged on `compose.yaml` with `service_healthy` dependency chains as the operator-facing deployment story. arXMCP's bare Dockerfile without a compose file is the single largest operator experience gap.

**Theme 4: BP1 cache discipline creates a forcing function for tool surface stability.** The `EXPECTED_TOOL_SCHEMA_SHA256` gate means every tool addition incurs a session-wide cache bust for all connected agents. This is load-bearing design pressure toward: (a) using MCP resources instead of tools for read-only corpus enumeration (Candidate 1), and (b) batching all tool additions into single schema bumps (Candidate 3 + Candidate 8 together). The cache discipline is correct and should be maintained.

---

## 6. Out of scope / parking lot

| Concept | Rejection reason |
|---|---|
| MCP `sampling` capability (server-initiated LLM calls) | arXMCP runs NO `anthropic` SDK at runtime (CLAUDE.md §4.7); `sampling` requires the server to call an LLM — direct architecture-lock conflict |
| MCP `elicitation` (server asking user for input mid-task) | arXMCP is a tool provider, not a user-interaction broker; elicitation is for interactive workflows, not batch retrieval pipelines |
| MCP `roots/list` client capability | Client-side: the harness exposes filesystem roots to the server. Not applicable — arXMCP does not need host filesystem access beyond what it already has via env-var config |
| Claude Projects / Anthropic Files API | arXMCP already addresses the gap these fill (see `.claude/notes/01-mission-and-context.md` §"The Claude-ecosystem gap"); no delta |
| `notifications/tools/list_changed` for removing tools | arXMCP's 7-tool surface is stable by design; dynamic tool removal introduces complexity without benefit; `listChanged` is useful only for future notebook-specific tool addition |
| Multi-node / distributed LanceDB corpus | Explicitly out of scope: local-first, single-workstation (CLAUDE.md §4.1); no distributed storage candidates surfaced |
| LlamaIndex / LangChain agentic-RAG frameworks | Require LLM calls at the framework layer; arXMCP is a tool provider not an agent orchestrator; architecture-lock conflict |
| PageIndex (VectifyAI, vectorless RAG) | Interesting retrieval alternative but eliminates the embedding infrastructure arXMCP already ships; not a corpus-management pattern |
| MCP gateway / registry patterns (agentic-community/mcp-gateway-registry) | Enterprise multi-tenant; arXMCP is single-user, loopback-only (CLAUDE.md §4.1); unnecessary complexity |
| OpenAI Assistants v2 file-search (cloud) | Cloud-dependent; violates local-first constraint (CLAUDE.md §2 "Design philosophy" point 4) |
