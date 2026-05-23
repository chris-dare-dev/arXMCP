# Comparative Landscape Brief — 2026 Q2 Verification-Feedback Scan

**Scout role:** Comparative Landscape Scout
**Scope:** Execution-based verification feedback for the sketcher → autoformalizer → tactician → fixer pipeline; `cite_neighbors` MCP tool completion; adjacent capabilities.
**Date:** 2026-05-22

---

## 1. TL;DR

The three capabilities most worth adopting are: **(1) a Lean kernel interaction tool** (LeanDojo-style `run_tac` loop) that passes structured `TacticState / ProofFinished / LeanError` feedback directly into the MCP tool surface; **(2) a SPECTER2 paper-similarity endpoint** (Semantic Scholar pattern) that gives the fixer agent a single-hop "retrieve papers like this failed proof state" call; and **(3) completing the `cite_neighbors` MCP wiring** by surfacing S2's `references` field as a fallback enrichment layer when the local Kùzu graph is sparse.

The dominant thematic gap: arXMCP treats Lean as an out-of-band oracle that the agent calls manually, whereas every high-performing 2026 autoformalization system (DeepSeek-Prover-V2, LeanCopilot, ReProver/LeanDojo) has made Lean kernel output a **first-class structured return value** that flows back into the same context window as retrieval results — arXMCP's MCP surface has no tool that returns proof state or compile-error text.

---

## 2. Top Capability Candidates

### C1 — Lean tactic-execution tool with structured proof-state return

**Capability name:** Lean kernel interaction tool (tactic executor + proof-state MCP tool)

**Source system:** LeanDojo (lean-dojo/LeanDojo, MIT license)

**Public evidence:** https://leandojo.readthedocs.io/en/latest/ — `lean_dojo.interaction.dojo` module documents `Dojo.run_tac(tactic_state, tactic) -> TacticState | ProofFinished | LeanError | ProofGivenUp`. `TacticState` carries `pp` (pretty-printed goals), `goals: list[Goal]`, and an opaque `id`. `LeanError` carries an `error: str`. `ProofFinished` carries `tactic_state_id`. The interaction loop is a `repl` tactic inside Lean that reads tactics from a POSIX pipe and writes results back.

**Capability angle:** The fixer agent currently has no MCP tool that tells it *why* the proof failed. A `run_lean_tactic` tool that accepts `(lean_src: str, tactic: str) -> {status: "ok"|"error"|"done", goals: [...], error: str|null}` closes this gap: the fixer can read the goal stack, pick a relevant lemma via `search_papers`, and retry in one loop without an external shell call.

**Technical angle:** Requires a running Lean 4 process on the same workstation (or a subprocess managed by the MCP server lifespan). LeanDojo wraps the `repl` tactic; the MCP server would manage the subprocess lifecycle. Key risk: Lean 4 startup latency (~5–15 s cold); mitigated by keeping a warm Lean REPL process open across tool calls. Subprocess isolation is also a security surface (Threat-1 analogue: tactic input must be sanitised). License: MIT — ideas are freely adoptable under the no-fork policy.

**Cross-reference to arXMCP:** No analog. The closest file is `server/handlers/citations.py` (stub), but there is no `run_lean` handler anywhere in `server/handlers/`. The mission note (`.claude/notes/01-mission-and-context.md` §"Lean Copilot / LeanDojo") names LeanDojo as infrastructure-of-reference but arXMCP has not built toward it. `CLAUDE.md §7` lists no Lean-interaction stub.

---

### C2 — SPECTER2 paper-embedding similarity query

**Capability name:** Dense paper-similarity lookup via pre-computed 1024-dim embeddings

**Source system:** Semantic Scholar Academic Graph API (S2AG) — https://www.semanticscholar.org/product/api

**Public evidence:** Live API call to `https://api.semanticscholar.org/graph/v1/paper/arXiv:2504.21801?fields=embedding` confirmed: the `embedding.vector` field returns a 1024-float array. The S2AG product page confirms "SPECTER2 embeddings" are available as a field on every paper. The Datasets API (`/api-docs/datasets`) provides bulk S2AG JSON archives. Rate limit: 1 req/s authenticated, shared pool unauthenticated.

**Capability angle:** When the fixer agent has a failing proof state, it can encode the natural-language description of the failed subgoal (or the Lean error message) and retrieve papers whose SPECTER2 embedding is nearest. This is a cross-corpus similarity signal that the local BGE-M3 corpus cannot provide for papers not yet ingested. It also enables the `cite_neighbors` handler to enrich sparse local graphs with S2 citation data.

**Technical angle:** Requires an outbound HTTPS call at tool-invocation time — conflicts with arXMCP's local-first / offline-capable design principle (`.claude/notes/01-mission-and-context.md` §"Design philosophy" point 4). Mitigation: make the S2 fetch an optional enrichment path with a `ARXMCP_S2_API_KEY` env var; return a `source: "s2_remote"` flag so the agent knows the result is not from the local corpus. SPECTER2 embedding model weights are also publicly available (huggingface.co/allenai/specter2) under Apache-2.0 — the local embedding pipeline could be extended to produce SPECTER2-compatible vectors, enabling purely local cross-corpus comparison if papers are bulk-ingested from S2AG datasets.

**Cross-reference to arXMCP:** Closest existing thing: `server/retrieval/` ANN pipeline over BGE-M3 `embedding_stmt` column (`server/corpus.py`, `ingest/embedder.py`). The existing retrieval pipeline is local-only. S2AG `embedding` field is a new enrichment source not present in arXMCP today.

---

### C3 — Citation-graph enrichment via S2 `references` field (1-hop, remote)

**Capability name:** Remote 1-hop reference list as `cite_neighbors` fallback

**Source system:** Semantic Scholar Academic Graph API + blazickjp/arxiv-mcp-server (MIT license)

**Public evidence:** S2AG confirmed: `references` field on `GET /graph/v1/paper/{id}` returns array of `{paperId, title}` objects. The community arxiv-mcp-server ships a `citation_graph` tool (README, no listed license at the tool level) that calls S2 for `references` and `citing papers` and returns them without requiring local download. Live evidence of field shape: `citations[]` objects contain `{paperId, title}` confirmed via the 2504.21801 S2 call.

**Capability angle:** The `cite_neighbors` MCP tool is a v1 stub returning `neighbors: []` (CLAUDE.md §7). When the local Kùzu graph is sparse (50-paper seed corpus), a remote S2 `references` call gives the fixer/tactician agent real citation data for any arXiv paper, not just ingested ones. The pattern: stub handler checks Kùzu first; if empty, falls back to S2 references API; marks `source: "s2_remote"` in each neighbor record.

**Technical angle:** The stub-to-real wiring requires: (1) unblocking the F2 path-validation contract (`CLAUDE.md §7`; `server/handlers/citations.py:22` comment), (2) adding an S2 HTTP client call behind a feature flag, (3) extending `CitationNeighbor` to carry a `source_system` field. Medium complexity. The existing `server/graph_queries.py` library is fully wired; only the MCP boundary (`server/handlers/citations.py`) is the gap. License note: Semantic Scholar API is free for non-commercial use; ToS allows derivative works.

**Cross-reference to arXMCP:** Direct stub analog: `server/handlers/citations.py` (the entire file is the stub). The library side `server/graph_queries.py` is real and tested. `ingest/graph_ingest.py` already calls OpenAlex — S2 would be a second enrichment source following the same pattern as `ingest/inspire_ingest.py`.

---

### C4 — Type-directed and pattern-based Lean declaration search (Loogle-style)

**Capability name:** Lean type-directed / subexpression-pattern theorem search

**Source system:** Loogle (loogle.lean-lang.org) — no separate license stated for the web service; the underlying Lean/Mathlib corpus is Apache-2.0

**Public evidence:** https://loogle.lean-lang.org/ — confirmed five query modes: (1) constant name (`Real.sin`), (2) name substring (`"differ"`), (3) subexpression pattern (`_ * (_ ^ _)`) with named metavariables (`?a`), (4) main conclusion (`|- tsum _ = _ * tsum _`), (5) type filter (`⊢ (_ : Prop)`). Multiple filters combinable with commas. Results include declaration name and Lean type. Interface: web UI + VSCode extension + CLI + `#loogle` Zulip bot. No documented REST API for external agent calls.

**Capability angle:** The tactician agent currently retrieves chunks from the arXiv corpus via `search_papers` and `find_lemma_by_name`. Neither can answer "find a Mathlib lemma whose conclusion has the shape `|- ∀ n : ℕ, f n < g n`." A `search_mathlib` MCP tool backed by Loogle-style type-directed search would give the tactician direct access to Mathlib declarations, complementing arXMCP's arXiv-paper retrieval.

**Technical angle:** Loogle has no public REST API (confirmed from UI inspection). Three paths: (1) screen-scrape Loogle's web endpoint (fragile, not recommended); (2) run Loogle locally against a local Mathlib4 build (Apache-2.0, ~2 GB build); (3) implement a lightweight BM25+type-pattern index over the Mathlib4 declaration set, which is available as a JSON export from the `leanprover-community/mathlib4` repo. Path (2) is most robust but adds a large local dependency. License: Mathlib4 is Apache-2.0 — ideas freely adoptable.

**Cross-reference to arXMCP:** Closest existing: `server/handlers/` `find_lemma_by_name` handler (in-memory substring scan over ingested chunks, `CLAUDE.md §7`). That handler covers arXiv-paper chunks, not Mathlib declarations. No `search_mathlib` tool exists. `ingest/` has no Mathlib ingest path.

---

### C5 — Proof-state goal serialization for retrieval (ReProver premise-selection pattern)

**Capability name:** Goal-conditioned premise retrieval (proof-state as retrieval query)

**Source system:** ReProver / LeanDojo (NeurIPS 2023; Yang et al.; MIT license). ArXiv: arXiv:2306.15626 (confirmed abstract page).

**Public evidence:** LeanDojo documentation confirms `TacticState.pp` (pretty-printed goals) and `TacticState.goals: list[Goal]` as the primary retrieval-query surface. ReProver encodes the concatenation of `(proof state, goal)` as a retrieval query against a premise corpus. The `parse_goals` module parses raw Lean goal output into structured `Goal` objects. The system's premise retrieval step is analogous to arXMCP's `search_papers` but queries over Lean declarations rather than paper chunks.

**Capability angle:** When the tactician has a current proof state (e.g., from C1's tactic executor), `search_papers` queries are currently natural-language strings typed by the agent. The ReProver pattern substitutes the serialized proof goal as the query: `search_papers(query=lean_goal_pp)`. This requires no new MCP tool — it is a prompting pattern change — but the arXMCP `search_papers` hybrid retrieval pipeline must handle Lean goal syntax gracefully (mixed LaTeX + Lean 4 term syntax). The improvement: zero-turn retrieval augmentation at each tactic step.

**Technical angle:** Low implementation complexity if C1 (tactic executor) is in place: the goal string from `TacticState.pp` is passed directly to `search_papers`. Higher complexity if the hybrid retrieval pipeline rejects Lean 4 syntax as out-of-vocabulary — the BM25 tokenizer (`ingest/tokenizer.py`) uses a math-aware regex pre-tokenizer that should handle Lean keywords but has not been tested on Lean 4 term syntax. A regression test over a small Lean goal fixture would be sufficient validation.

**Cross-reference to arXMCP:** `ingest/tokenizer.py` (math-aware BM25 tokenizer — untested on Lean 4 syntax). `server/handlers/search.py` (the `search_papers` handler — would receive Lean goal strings). No existing test fixture for Lean-goal queries.

---

### C6 — TLDR/snippet generation for retrieved papers

**Capability name:** Model-generated TLDR snippet per paper

**Source system:** Semantic Scholar Academic Graph API (S2AG)

**Public evidence:** Live API call to `GET /graph/v1/paper/arXiv:2504.21801?fields=tldr` confirmed: `tldr.text` = "This work introduces DeepSeek-Prover-V2, an open-source large language model designed for formal th…" (truncated in API response preview). S2AG generates TLDRs for a large fraction of the academic corpus using a fine-tuned summarization model.

**Capability angle:** The sketcher agent currently receives raw chunk text from `search_papers`. An enriched result that includes a one-sentence TLDR for each paper reduces the sketcher's reading load: it can scan TLDRs to identify the 2–3 most relevant papers before fetching full chunks. This is additive to arXMCP's existing snippet contract (`.claude/docs/snippet-contract.md`) — TLDRs are longer (1–3 sentences) than the 150-char snippet, so they would be a separate field rather than a replacement.

**Technical angle:** Requires outbound S2AG call at ingest time (preferred — cache TLDRs in the chunks table) or at query time. Ingest-time approach: add a `tldr` column to the LanceDB `chunks` table schema (`ingest/schema.py`) and populate it from S2AG during `ingest/graph_ingest.py`'s existing OpenAlex+S2 enrichment pass. Zero new MCP tools needed — `get_paper` handler (`server/handlers/paper.py`) can return the `tldr` field alongside existing metadata. Rate limit: S2AG requires API key for sustained ingest use.

**Cross-reference to arXMCP:** `ingest/schema.py` (LanceDB chunks schema — `tldr` column is net-new). `server/handlers/paper.py` (already stubs out metadata fields per CLAUDE.md §7; `tldr` would be one more field). `ingest/graph_ingest.py` (OpenAlex ingest — S2 enrichment would follow the `ingest/inspire_ingest.py` pattern).

---

### C7 — Version-aware paper retrieval (v1 vs v3 delta)

**Capability name:** arXiv paper version history access (multi-version retrieval)

**Source system:** arXiv official API (info.arxiv.org/help/api)

**Public evidence:** https://info.arxiv.org/help/api/user-manual.html — confirmed: the arXiv API supports version-pinned IDs (e.g. `cond-mat/0207270v1`) in query strings. The `<category>` element includes MSC codes when present. The e-print endpoint `https://arxiv.org/e-print/{id}vN` (used by `tools/arxiv_fetch.py`) retrieves the LaTeX tarball for a specific version. The API returns `updated` date for version tracking.

**Capability angle:** Per `.claude/notes/01-mission-and-context.md` §"Implication for the pipeline" (Fixer bullet): "v1 often has the cleaner statement and v3 has the corrected proof." The fixer agent has no tool that says "this chunk is from v2; there is also a v3 — retrieve the diff." A `get_paper_versions` tool that returns `[{version, updated_date, chunk_diff_available}]` would let the fixer explicitly target a version with a corrected proof or a cleaner statement.

**Technical angle:** The `ingest/` pipeline (`ingest/chunker.py`, `ingest/store.py`) currently ingests papers without recording the version number in the LanceDB schema. Adding a `paper_version` column to `ingest/schema.py` and tracking it during `tools/arxiv_fetch.py` fetches is the prerequisite. The e-print endpoint for multi-version fetch is already used by `tools/arxiv_fetch.py` — extending to store `vN` alongside each chunk is low complexity. The diff computation (v1 vs v3 chunk-level) is harder: LaTeXML parses both, then a structural diff is needed.

**Cross-reference to arXMCP:** `ingest/schema.py` (no `paper_version` column today). `tools/arxiv_fetch.py` (fetches e-print LaTeX but does not record version). `server/handlers/paper.py` (`get_paper` returns NULL for most metadata per CLAUDE.md §7 — version would be another nullable field).

---

### C8 — MCP progress notifications for long-running verification calls

**Capability name:** Streaming progress notifications for blocking tool calls

**Source system:** MCP Python SDK (modelcontextprotocol/python-sdk, MIT license)

**Public evidence:** https://github.com/modelcontextprotocol/python-sdk README — confirmed: `ctx.report_progress(progress, total, message)` sends incremental progress notifications to the calling agent during a tool execution. Also confirmed: `send_resource_updated()` for resource-change notifications. The SDK uses request-response with progress reporting as the primary feedback mechanism (no full streaming, but incremental status).

**Capability angle:** A Lean tactic execution tool (C1) may block for 5–30 seconds while Lean compiles. Without progress notifications, the calling agent times out or stalls. `ctx.report_progress` with messages like `"compiling (2/5 goals resolved)"` keeps the agent informed. This is also relevant for bulk citation-graph queries when `cite_neighbors` traverses a large graph.

**Technical angle:** `ctx.report_progress` is already available in the MCP Python SDK used by arXMCP's FastAPI+Streamable-HTTP server. The server's `tools.py` handler registration pattern would need to pass `ctx` (the MCP context) into each handler. Current handlers (`server/handlers/*.py`) are pure `async def handle_*(...)` functions without a context parameter — adding `ctx: Context` as a parameter requires updating all handler signatures and the tool-registration wiring in `server/tools.py`. Medium refactor.

**Cross-reference to arXMCP:** `server/tools.py` (tool registration — no `ctx` parameter passed today). `server/handlers/` (all handlers are context-free). `server/main.py` (FastAPI lifespan — the place to initialize a persistent Lean REPL if C1 is built).

---

### C9 — Lean REPL process management as a persistent MCP resource

**Capability name:** Persistent Lean REPL resource exposed via MCP resource endpoint

**Source system:** MCP Python SDK `@mcp.resource()` pattern + LeanCopilot (lean-dojo/LeanCopilot, MIT license)

**Public evidence:** MCP Python SDK README confirms `@mcp.resource()` decorator for URI-template resource endpoints. LeanCopilot (https://github.com/lean-dojo/LeanCopilot) confirmed: ships a "Python API server" that wraps models and exposes them as external generators/encoders callable from Lean via FFI. The LeanCopilot generator/encoder `TextToText` interface accepts an input string and returns `(output_string[], confidence_score[])`.

**Capability angle:** Lean REPL startup is expensive. If the REPL is a persistent MCP resource (URI: `lean://repl/default`), the tactician agent can acquire it once per session and submit multiple tactics without paying the startup cost each time. The MCP resource model (subscribe / notify / unsubscribe) maps naturally onto a stateful Lean REPL session where each tactic modifies the proof state.

**Technical angle:** Requires the MCP server to manage a subprocess lifecycle across tool calls — a significant architectural addition. The lifespan hook in `server/main.py` is the correct place to initialize the REPL. Resource state (current `TacticState.id`) must be stored server-side and referenced by the client. Security surface: the Lean REPL runs arbitrary Lean code; the server must validate tactic strings before passing them. Complexity: HIGH, but the payoff for C1 is substantially higher if the REPL is warm.

**Cross-reference to arXMCP:** `server/main.py` (FastAPI lifespan — initialization point for subprocess resources). `server/session.py` (per-session caps — the REPL session lifecycle would parallel the MCP session lifecycle). No existing subprocess-resource pattern in the codebase.

---

### C10 — MSC-classification-aware corpus filtering

**Capability name:** Mathematics Subject Classification (MSC) filter on search and retrieval

**Source system:** arXiv API (MSC in `<category>` field, confirmed); zbMATH (OAI-PMH access blocked during this scan, but documented as the primary MSC indexing service for mathematics)

**Public evidence:** arXiv API user manual (https://info.arxiv.org/help/api/user-manual.html) confirms: `<category>` element includes MSC codes when present on a paper. arXiv submission instructions document MSC as an optional field. zbMATH is the authoritative MSC assignment service but its programmatic access was blocked (HTTP 403) during this scan; documented API exists per FIZ Karlsruhe (zbmath.org — the OAI-PMH endpoint requires institutional credentials).

**Capability angle:** The `search_papers` tool has a `filters` parameter that is accepted but ignored (CLAUDE.md §7). MSC code is a natural filter axis for math research: `filters={"msc": "14G35"}` would restrict results to Shimura varieties. This is especially valuable for the autoformalizer, which needs definitions and conventions specific to one subfield. The arXiv API already returns MSC codes in metadata — they could be stored in the chunks table and used as a pre-filter before BM25/ANN retrieval.

**Technical angle:** The arXiv API returns MSC as a free-text `<category>` tag (e.g., `14G35 (primary), 11F80 (secondary)`). Parsing and normalizing these into a structured `msc_codes: list[str]` column in `ingest/schema.py` is low-to-medium complexity. The `search_papers` `filters` stub (`server/handlers/search.py`) already has the parameter — wiring it to a LanceDB WHERE clause on `msc_codes` is the remaining work. The zbMATH enrichment path (fuller MSC assignment) would require institutional access or a bulk OAI-PMH snapshot.

**Cross-reference to arXMCP:** `ingest/schema.py` (no `msc_codes` column). `server/handlers/search.py` (accepts `filters` param but ignores it — CLAUDE.md §7). `tools/arxiv_fetch.py` (fetches arXiv metadata but does not extract MSC from the Atom response).

---

## 3. Sources Reviewed

| System | URL | What was read | High-signal? |
|---|---|---|---|
| blazickjp/arxiv-mcp-server | https://github.com/blazickjp/arxiv-mcp-server | GitHub README — full tool list (search_papers, download_paper, read_paper, list_papers, semantic_search, citation_graph, watch_topic, check_alerts); citation_graph calls S2 for references/citers | YES |
| Context7 (upstash/context7) | https://github.com/upstash/context7 | GitHub README — resolve-library-id + query-docs tools; version-specific snippet contract; real-time freshness model | YES (MCP packaging patterns) |
| Semantic Scholar S2AG | https://www.semanticscholar.org/product/api + live API call | Product page (Academic Graph, Recommendations, Datasets); live `?fields=tldr,embedding,references,citations,externalIds` call on arXiv:2504.21801 — confirmed 1024-dim SPECTER2 vector, tldr.text, references[]{paperId, title} | YES (live-verified) |
| LeanSearch | https://leansearch.net/ | Web UI description — natural-language query to Mathlib4 theorems/definitions; query augmentation; no REST API documented | PARTIAL (no API evidence) |
| Loogle | https://loogle.lean-lang.org/ | Web UI + CLI docs — 5 query modes (constant, name-substring, subexpression-pattern, main-conclusion, type-filter); metavariable patterns; no REST API | YES (query syntax documented) |
| OpenAlex | https://developers.openalex.org/api-entities/works | Works entity schema — cited_by_count, referenced_works, concepts/topics hierarchy, primary_location; 1-hop only confirmed | YES (field schema verified) |
| INSPIRE-HEP | https://inspirehep.net/api/literature | Live API call (author Tao) — arxiv_eprints, citation_count, references (mixed full-objects + $ref URLs), titles, texkeys; no MSC/PACS in sampled response | PARTIAL (no math-specific fields) |
| LeanDojo | https://leandojo.readthedocs.io/ + GitHub README | User guide (repl tactic, Dojo interaction model); API reference module listing; confirmed TacticState/ProofFinished/LeanError/ProofGivenUp class names and fields (pp, goals, id, error, message) | YES (primary docs + confirmed class signatures) |
| LeanCopilot | https://github.com/lean-dojo/LeanCopilot | GitHub README — TextToText generator interface; Python API server; suggest_tactics/search_proof/select_premises tactics; dual-model (local NativeGenerator + ExternalGenerator via API) | YES |
| lean-auto | https://github.com/leanprover-community/lean-auto | GitHub README — Apache-2.0; SMT/TPTP external solver integration; translation pipeline to HOL; rebind interface for custom solvers | PARTIAL (external-solver pattern useful; not directly applicable to fixer loop) |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | README — tool/resource/prompt registration patterns; ctx.report_progress; send_resource_updated; Elicitation; OAuth 2.1 | YES |
| arXiv API | https://info.arxiv.org/help/api/user-manual.html | User manual — Atom 1.0 fields; version-pinned IDs (vN suffix); MSC in `<category>`; no LaTeX source access via API (e-print is a separate endpoint) | YES |
| ar5iv (LaTeXML HTML) | https://ar5iv.labs.arxiv.org/html/2504.21801 | Rendered HTML — equations as PNG images (not MathML) for this paper; heading-based structure; no ltx_theorem CSS classes visible in text extraction | PARTIAL (rendering quality paper-dependent) |
| Moogle | https://moogle.ai/ | Landing page only — "Find theorems, faster"; no API docs accessible | NO (marketing only) |
| Connected Papers | https://connectedpapers.com/ | Landing page only — no API docs | NO (no programmatic evidence) |
| ResearchRabbit | https://researchrabbit.ai/ | Landing page only — no API docs; Zotero sync mentioned | NO (no programmatic evidence) |
| DeepSeek-Prover-V2 | https://arxiv.org/abs/2504.21801 | Abstract — subgoal decomposition; DeepSeek-V3 as informal sketcher; RL training on Lean-accepted proofs; S2 TLDR confirmed for this paper | PARTIAL (architecture confirmed at abstract level) |
| miniF2F / ntptutorial | https://github.com/openai/miniF2F + https://github.com/wellecks/ntptutorial | READMEs — benchmark structure confirmed; implementation details in notebooks not accessible from README | PARTIAL |

---

## 4. Cross-References to arXMCP

- **C1 (Lean tactic executor):** Net-new. No analog in `server/handlers/`. The mission note names LeanDojo as reference infrastructure (`.claude/notes/01-mission-and-context.md`) but no implementation exists.

- **C2 (SPECTER2 similarity):** Extends existing BGE-M3 ANN pipeline (`server/retrieval/`, `ingest/embedder.py`). Net-new as a *remote enrichment path*; the local embedding pipeline is the structural analog.

- **C3 (S2 citation fallback):** Direct stub gap: `server/handlers/citations.py` is the stub; `server/graph_queries.py` is the real library. The F2 path-validation contract note in `server/handlers/citations.py:22` is the blocker; no architectural change needed beyond that and adding an S2 HTTP client.

- **C4 (Loogle-style type search):** Net-new. `server/handlers/` has `find_lemma_by_name` for arXiv corpus chunks (in-memory substring, CLAUDE.md §7 stub note) but no Mathlib-declaration search.

- **C5 (Goal-conditioned premise retrieval):** Prompting pattern, not a new tool. Closest is `search_papers` (`server/handlers/search.py`). Requires testing `ingest/tokenizer.py` against Lean 4 goal syntax.

- **C6 (TLDR snippets):** Extends `ingest/schema.py` and `server/handlers/paper.py`. `get_paper` already stubs metadata fields (CLAUDE.md §7); `tldr` is one more field to populate.

- **C7 (Version-aware retrieval):** Extends `ingest/schema.py` (no `paper_version` column) and `tools/arxiv_fetch.py`. Net-new at the schema level; the fetch machinery exists.

- **C8 (Progress notifications):** Extends `server/tools.py` and all `server/handlers/*.py` to accept MCP context. Structural refactor; the SDK capability is available today.

- **C9 (Persistent Lean REPL resource):** Net-new as an MCP resource. The `server/main.py` lifespan hook is the architectural anchor; no subprocess resource pattern exists today.

- **C10 (MSC filter):** Extends `ingest/schema.py`, `tools/arxiv_fetch.py`, and unblocks the `search_papers` `filters` stub (`server/handlers/search.py`). Closest existing: `filters` param accepted but ignored (CLAUDE.md §7).

---

## 5. Themes

**Lean-as-first-class-feedback-channel.** Every high-performing 2026 autoformalization system has eliminated the boundary between "retrieval context" and "verification output" — LeanDojo's `TacticState`, LeanCopilot's `suggest_tactics`, DeepSeek-Prover-V2's subgoal loop all treat Lean's response as a structured data type flowing back into the same context as retrieved lemmas. arXMCP's current 7-tool surface is entirely retrieval-side; it has no tool that emits proof state.

**The citation-graph stub is a strategic debt, not a minor gap.** C3 is not just about completing a v1 stub: the `cite_neighbors` tool, once wired, enables the tactician to follow the citation chain from a paper chunk to its cited lemmas — the core proof-chain workflow described in `.claude/docs/proof-chain-workflow.md`. The remote S2 fallback makes this usable even before the local Kùzu graph is dense.

**Remote enrichment vs local-first tension.** S2AG (C2, C3, C6) and the arXiv API (C7, C10) offer high-value enrichment that would require outbound calls — a tension with the local-first design principle. The resolution visible across comparable systems (Context7, blazickjp's citation_graph) is a **hybrid model**: local-corpus-first, remote-enrichment-flagged. arXMCP does not yet have this hybrid flag convention in its result envelope.

**Mathlib is a parallel corpus.** Loogle (C4) and the ReProver premise-selection pattern (C5) point to a gap arXMCP has not addressed: the tactician needs Mathlib declarations as well as arXiv paper chunks. These are different corpora with different schemas (Lean 4 declarations vs LaTeX theorem chunks) but both flow into the same `search_papers`-style tool from the agent's perspective.

---

## 6. Out of Scope / Parking Lot

- **Connected Papers neighborhood expansion UI:** No public API found; UI-only product as of this scan. Rejected: no programmatic evidence, no capability an MCP server can expose.

- **ResearchRabbit citation graph:** No public API found; UI-only. Rejected: same reason as Connected Papers.

- **Elicit claim extraction:** HTTP 403 blocked all attempts; no primary technical evidence obtained. Rejected: insufficient primary evidence for a capability claim.

- **lean-auto SMT/TPTP solver integration:** Apache-2.0; the external-solver translation pipeline is interesting but requires deep Lean 4 metaprogramming. Rejected for this scan: the complexity is an order of magnitude higher than C1 (LeanDojo REPL) and the benefit to the fixer loop is narrower.

- **nLab concept-graph navigation:** nLab has no REST API; it is a MediaWiki instance. Concept-graph navigation via wiki links is low-signal for the pipeline. Rejected: no machine-accessible API; wiki-link density is not a retrieval capability.

- **ar5iv theorem-level DOM extraction:** ar5iv renders equations as PNG images (confirmed for arXiv:2504.21801); LaTeXML CSS class structure was not confirmable via text extraction. The arXMCP chunker (`ingest/chunker.py`) already handles the LaTeX source directly, which is more reliable than parsing ar5iv HTML. Rejected: arXMCP's existing LaTeXML path is structurally superior.

- **zbMATH API:** Multiple access attempts returned HTTP 403 or connection refused. The OAI-PMH endpoint requires institutional credentials. MSC data is available via arXiv's own `<category>` field (C10 handles this without zbMATH). Rejected for primary access; parked as secondary enrichment if institutional access is obtained.

- **INSPIRE-HEP MSC/PACS codes:** Sampled live call showed no MSC/PACS codes in the response for the tested record. These fields may exist for math-ph/hep-th papers specifically but were not confirmed in this scan. Parked: worth a targeted INSPIRE query on a known math-ph paper in a future scan.

- **OpenAlex multi-hop citation traversal:** OpenAlex documents only 1-hop `referenced_works` / `cited_by`. Multi-hop requires chained API calls. The local Kùzu graph (once C3 is wired) handles this more efficiently for the ingested corpus. Rejected: Kùzu is the right tool for multi-hop; OpenAlex is the enrichment source for hop-1 when Kùzu is sparse.
