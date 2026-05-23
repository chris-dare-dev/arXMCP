# Challenge — 2026q2-verification-feedback-scan

**Role:** CHALLENGER (Phase 3)
**Generated:** 2026-05-22
**Source catalog:** `.claude/notes/capability-scouts/2026q2-verification-feedback-scan/artifacts/synthesis.md`
**References:** CLAUDE.md, `.claude/notes/07-multi-agent-caching.md`, `.claude/milestone-pipeline/references/critique-format.md`, 5 scout briefs

---

## 1. Executive summary

Of the 14 catalog candidates, **1 draws BLOCKER**, **4 draw MAJOR**, **5 draw MINOR**, and **4 draw NONE**. The single BLOCKER (CAND-3, Kùzu fork migration) is not a kill — it is a redesign: the `git+https://` dependency pin introduces a supply-chain Threat-6 surface that the synthesis underweights, and the fork's PyPI availability must be confirmed before any pin. The dominant MAJOR theme is **sequencing omission**: CAND-4, CAND-6, CAND-11, and CAND-15 all carry hard sequencing dependencies on upstream candidates that the catalog lists as "open questions" rather than explicit DAG edges, meaning Phase 4 could accidentally schedule them ahead of their prerequisites. The second cross-cutting theme is **MCP tool-surface cost undercount**: every candidate that adds or modifies a tool requires re-pinning `EXPECTED_TOOL_SCHEMA_SHA256` and — when the tool returns result rows — auditing `.claude/docs/snippet-contract.md` compliance; several candidates treat this as a footnote rather than a concrete implementation tax.

---

## 2. BLOCKER findings

---

### CAND-3 — Migrate Kùzu to the Vela-Engineering maintained fork

**Severity: BLOCKER**

**Objections:**

- **Axis 5 (Local-first / supply-chain) + Axis 2 (No-fork policy adjacent):** The OSS-trends brief explicitly recommends the pin `kuzu @ git+https://github.com/Vela-Engineering/kuzu`. A `git+https://` dependency in `pyproject.toml` is a live source-code fetch at every `pip install` / `uv sync`. This directly activates the Threat-6 supply-chain surface that E13 specifically hardened against (`CLAUDE.md §8 gotcha 2` and E13 security audit). A `git+` pin fetches from a URL the project does not control; a force-push to the fork's `master` branch injects arbitrary code into arXMCP's dependency tree. E13 created concrete mitigations for supply-chain risk; this change would create a new unmitigated instance of the same threat class.

- **Axis 8 (Effort honesty):** The synthesis labels this XS and claims "no code changes required beyond the pin." This is only true if (a) the Vela fork is on PyPI under the `kuzu` package name with a stable version tag, and (b) the Python binding API is genuinely identical to 0.11.3. Neither is confirmed in the synthesis or the OSS-trends brief. The brief says "appears pip-installable as `kuzu` (same package name as upstream)" — "appears" is not confirmation. If the fork is PyPI-published at a stable tag, the risk collapses; if it is not, the XS effort estimate hides a non-trivial supply-chain audit.

- **Axis 8 (Effort honesty) — continued:** Vela-Engineering/kuzu has 32 stars and an unknown release cadence beyond "last commit 2026-05-19." The OSS-trends brief itself flags "abandonment risk is real if Vela Partners loses interest." Migrating arXMCP's citation graph foundation to a 32-star fork of an archived project, with no confirmed PyPI release, trades one known-stable risk (archived upstream) for an unknown-trajectory risk.

**Recommended redesign (not kill):** Before scheduling this as a milestone task, confirm two things: (1) Is `Vela-Engineering/kuzu` available on PyPI with a pinnable semver tag (e.g. `kuzu==0.11.4`)? If yes, the pin becomes `kuzu==0.11.4` — no `git+` URL, no supply-chain concern, and the BLOCKER reduces to MINOR. (2) Does the full `tests/_graph_helpers.py` synthetic fixture suite pass against the fork version in a test branch? Condition the milestone on both confirmations. If PyPI availability cannot be confirmed, the correct action is to document the migration path in `.claude/roadmap/E14-observability-ops.md` as a tracked item rather than executing it now — `kuzu==0.11.3` remains functional and the E13 security posture is preserved.

---

## 3. MAJOR findings

---

### CAND-4 — Syntax-check and incremental-checkpoint modes on `lean_verify`

**Severity: MAJOR**

**Objections:**

- **Axis 10 (Sequencing dependencies):** CAND-4 depends entirely on CAND-1. The synthesis acknowledges this ("depends entirely on CAND-1") but classifies CAND-4 as size S — a separate catalog entry with its own t-shirt size. The Phase 4 prioritization pass could rank CAND-4 favorably on its own merits and schedule it ahead of, or in parallel with, CAND-1, which would produce zero deliverable value. The catalog should flag this as a hard DAG edge: CAND-4 is unschedulable until CAND-1 is complete and the REPL subprocess architecture is proven.

- **Axis 4 (MCP tool-surface contract):** The `mode: Literal["full","syntax_only","incremental"]` parameter is a schema change to the `lean_verify` tool — or a schema definition at v0 if CAND-1 includes it. The synthesis raises "build this into CAND-1's v1 schema, or ship CAND-1 with `mode="full"` only and add modes later" as an open question. From the cache-discipline perspective (`.claude/notes/07-multi-agent-caching.md` Property 1), adding modes later is a second `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. The synthesis correctly notes folding it in is cheaper, but leaves the decision open. The Phase 4 scheduler needs a concrete answer before scoping either candidate.

- **Axis 8 (Effort honesty):** The `incremental` mode — "accepts a `proof_state_id` + a single tactic and uses the REPL's tactic mode" — requires server-side session state: the REPL subprocess must be kept alive between calls, keyed by `Mcp-Session-Id`, with proof-state IDs persisted per session. This is not a thin handler; it is a stateful session-scoped subprocess pool (`server/session.py` extension + new lifecycle in `server/main.py`). The size S label understates this. The `syntax_only` mode is genuinely S-sized; the `incremental` mode is M-sized by itself. The synthesis blends them into one S entry.

**Suggested scope adjustment:** Split CAND-4 into two explicit milestones: (a) CAND-4a: `mode="syntax_only"` folded into CAND-1's v1 schema at zero extra cost — ship it with CAND-1. (b) CAND-4b: `mode="incremental"` as a follow-on M-sized milestone that depends on CAND-1 shipping and the REPL session-pool design being proven. Represent this DAG dependency explicitly in Phase 4.

---

### CAND-6 — Proof-state-conditioned retrieval (`search_by_proof_state`)

**Severity: MAJOR**

**Objections:**

- **Axis 10 (Sequencing dependencies):** The synthesis states "strongly coupled to CAND-1 (the proof state comes from `lean_verify`). Low standalone value before CAND-1." This is accurate, but the synthesis still lists CAND-6 as a stand-alone M-sized candidate in the catalog without flagging the DAG edge as a scheduling constraint. An agent has no live proof state to feed into `search_by_proof_state` until CAND-1 exists. Standalone value is not just "low" — it is essentially zero, because the distinguishing feature of CAND-6 over the existing `search_papers` is that the query is a Lean goal string rather than a natural-language string, and Lean goal strings only exist in arXMCP's context if CAND-1 is running.

- **Axis 7 (Retrieval-quality regression):** The BM25 tokenizer (`ingest/tokenizer.py`) has not been tested against Lean 4 term syntax. The synthesis and comparative brief both flag this: "Does the BM25 tokenizer reject Lean 4 term syntax as out-of-vocabulary? Needs a regression fixture." The synthesis lists this as an open question. However, a regression on Lean-goal queries would not just be a CAND-6 failure — if the same tokenizer handles Lean-goal queries differently from math-LaTeX queries, the BM25 path could produce garbage for any mixed-syntax query. Before CAND-6 is scheduled, a Lean-goal BM25 tokenizer regression fixture should be added to `tests/` as a pre-work item (callable under `make eval` or a separate marker).

- **Axis 3 (Prompt-cache discipline):** The synthesis sketches a "new route tag in `server/router.py`." The query router (`server/router.py` + `server/router_patterns.yaml`) is part of the BP2 context — a new `RouteTag` changes the branching logic that assigns `model_selector` outputs. Any change to the router patterns should be reviewed for BP2 byte-stability implications (`.claude/notes/07-multi-agent-caching.md` Property 2 + `server/prompts.py` role-prefix breakpoints). The synthesis does not flag this interaction.

**Suggested scope adjustment:** Gate CAND-6 on CAND-1 in the Phase 4 DAG (hard dependency, not preference). Add the Lean-goal BM25 tokenizer regression fixture as a pre-work task before CAND-6 implementation begins — this fixture doubles as a CAND-14 complement. The router-tag change should be reviewed for cache-discipline impact before merging.

---

### CAND-11 — `retrieval_confidence` sufficiency signal in the result payload

**Severity: MAJOR**

**Objections:**

- **Axis 10 (Sequencing dependencies):** The synthesis explicitly states "Calibrating the threshold needs the eval fixture (CAND-14) curated first, or it is an uncalibrated guess." This is a hard dependency that the catalog lists as an open question rather than a DAG constraint. If CAND-11 ships before CAND-14, the `retrieval_confidence` field will be derived from an uncalibrated threshold, producing values that are structurally valid but semantically meaningless. An agent that acts on an uncalibrated confidence signal may make worse decisions than if no signal were present.

- **Axis 4 (MCP tool-surface contract):** Adding `retrieval_confidence: float` to the search result payload is an additive schema change requiring `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. The synthesis notes this. Additionally, the new field must be audited against `.claude/docs/snippet-contract.md` — specifically, the `structuredContent` shape in `server/schemas/search_papers_result.json` is the frozen contract; adding a field is a version bump that requires updating the JSON Schema file, the test `tests/test_snippet_contract.py`, and the schema hash pin. The synthesis treats this as a one-liner ("re-pin EXPECTED_TOOL_SCHEMA_SHA256; update snippet-contract.md") but the audit surface is the full snippet-contract machinery, not just the hash.

- **Axis 9 (Value density):** The value proposition assumes agents will act on the confidence signal to decide whether to re-query. However, arXMCP's architecture philosophy (CLAUDE.md §2, "valuable LLM roles live upstream of verification") places retrieval-quality judgment in the agent, not the server. A confidence signal derived from the BGE-reranker score is already implicit in the `score` field. The added value of a separately named `retrieval_confidence` float depends entirely on whether agent prompts are authored to consult it — and those prompts don't yet exist (`server/prompts.py` is a placeholder per CLAUDE.md §8 gotcha 6). Shipping a confidence field before the system prompt that instructs agents how to use it inverts the delivery order.

**Suggested scope adjustment:** Block CAND-11 on CAND-14 (hard DAG dependency) and on the `server/prompts.py` system prompt authoring (presently parking-lot item L1 in the adversary brief). Only schedule CAND-11 after (a) the eval fixture provides a calibration basis and (b) the system prompt establishes how agents should interpret the confidence signal. The schema change is genuinely additive, so the implementation cost is low once the prerequisites exist.

---

### CAND-15 — Dual-resolution / Matryoshka embeddings for the Tier-1 cache

**Severity: MAJOR**

**Objections:**

- **Axis 8 (Effort honesty):** The synthesis labels this L and acknowledges "a *full* 2D-MRL benefit needs a model fine-tune." However, even the "truncation-only" v1 path ("smaller" per the synthesis) requires a full corpus re-embed. At 50 papers in the seed corpus this is tractable, but the synthesis does not estimate the re-embed cost for the full corpus, and the partial re-embed driver (E11_S03 strategy) is the mechanism that must be used. This is not a blocker but it means the "v1 could be truncation-only (smaller)" framing needs a concrete estimate: how long does a full re-embed of the seed corpus take with BGE-M3 MRL truncation, and what is the storage delta for `embedding_short` alongside the existing 1024-d vectors?

- **Axis 7 (Retrieval-quality regression):** Adding `embedding_short` as a Tier-1/Tier-2 cache lookup key changes the cache hit/miss behavior for near-duplicate queries. If the short (256-d) vector produces a different nearest-centroid than the full (1024-d) vector, a Tier-2 semantic cache hit under the old scheme becomes a miss under the new scheme. This is not a retrieval regression in the nDCG@5 sense — it is a cache-behavior change that reduces cache effectiveness for queries where 256-d and 1024-d embeddings disagree on nearest-centroid. The synthesis does not surface this as a risk.

- **Axis 9 (Value density):** The stated benefit — "shrinks the Tier-2 FAISS cache ~4× and cuts cache-lookup latency" — is a performance optimization on a 50-paper seed corpus where the FAISS cache is tiny and lookup latency is already negligible. The optimization becomes load-bearing at scale (hundreds or thousands of papers), but at the current corpus size it addresses a non-problem. The L effort label, corpus re-embed cost, and near-zero value at current scale make this the lowest-value-density candidate in the catalog.

**Suggested scope adjustment:** Defer to v2 / a dedicated optimization epic. Add a concrete "evaluate this when corpus grows past N papers" trigger condition in `.claude/roadmap/` (analogous to the E14_S06 un-park trigger pattern). The `embedding_short` column can be added to `ingest/schema.py` as a reserved NULL column now (following the `embedding_eq` pattern, CLAUDE.md §7) if future-proofing is desired, at zero re-embed cost. Full MRL truncation or fine-tune should not be scheduled until the corpus is large enough that the cache-lookup latency improvement is measurable.

---

## 4. MINOR findings

---

### CAND-1 — Add a Lean kernel verification-trace MCP tool (`lean_verify`)

**Severity: MINOR**

**Objections:**

- **Axis 1 (Architecture-lock compatibility):** The synthesis correctly identifies the subprocess model as the only viable approach (pure-ASGI rule means no blocking event-loop calls; `asyncio.create_subprocess_exec` is the correct primitive). One detail the synthesis leaves implicit: the Lean subprocess must not be started in a synchronous lifespan path; it must be awaited within the async `lifespan` context in `server/main.py`. The synthesis says "Gate behind `ARXMCP_ENABLE_LEAN=false` by default" — this is correct, but the lifespan must conditionally skip subprocess startup when the flag is false. If the flag check is not in the lifespan and the subprocess start is deferred to the first tool call, a cold-start race condition exists between concurrent requests. This is a v1-implementation detail, not a design flaw.

- **Axis 4 (MCP tool-surface contract):** Adding `lean_verify` to `server/tools.py::ALL_TOOLS` requires re-pinning `EXPECTED_TOOL_SCHEMA_SHA256`. The synthesis notes this. The result schema (`{status, messages:[{severity,position,text}], proof_state, goals_remaining, sorry_goals, compilation_success}`) contains no `snippet` field, so the 150-char snippet contract (`.claude/docs/snippet-contract.md`) does not apply. The schema pin is the full obligation here, and it is correctly identified.

- **Axis 5 (Local-first):** The synthesis is correct that the Lean process is local. No network egress. No non-loopback bind. The security surface (arbitrary Lean code execution in a subprocess) is correctly flagged as a "Threat-3 analogue." The synthesis should specify that the same sandbox discipline used for LaTeXML (E13_S03) — subprocess resource limits, timeout enforcement, no filesystem writes outside the designated temp directory — must be applied to the Lean subprocess. A concrete reference to E13_S03's sandbox spec as the implementation template would strengthen the milestone brief.

**Suggested scope adjustment:** Before implementation, produce a one-page security sub-design (analogous to E13_S03's Lean sandbox spec) that covers: subprocess timeout, filesystem isolation (read-only except temp dir), memory cap, and error-handling when the subprocess crashes or times out. This is pre-work for the research phase, not a new milestone. The `asyncio.create_subprocess_exec` path is the right call; the lifespan startup ordering and sandbox spec are the v0-cut details to nail.

---

### CAND-2 — Wire `cite_neighbors` MCP handler to the live `graph_queries` library

**Severity: MINOR**

**Objections:**

- **Axis 4 (MCP tool-surface contract):** The synthesis correctly identifies the direction-enum mismatch between the handler (`citers/cited/co_cited/co_citing/depends_on`) and the library (`cites/cited_by/depends_on`) as a choice point. If the handler enum is re-aligned to the library's, the tool schema changes and `EXPECTED_TOOL_SCHEMA_SHA256` must be re-pinned. If a mapping layer is added instead, the schema is unchanged. The synthesis treats this as an open question, but the implementation team must decide before writing the handler: a mapping layer that silently translates `"citers"` → `"cites"` is a foot-gun because the advertised direction name in the tool description would not match the library's name, creating a documentation mismatch future implementers will re-discover. The cleaner path is to re-align the enum and re-pin the hash; the synthesis should state this recommendation rather than leaving it open.

- **Axis 7 (Retrieval-quality regression):** The synthesis mentions adding a `graph_version` cache key component to invalidate stale `cite_neighbors` results after re-ingest. The existing 3-tier retrieval cache in `server/cache.py` uses `corpus_version` as part of the Tier-1 key. The citation graph has its own versioning concern (it is updated by `ingest/graph_ingest.py` independently from the LanceDB corpus). If `cite_neighbors` results are cached under the Tier-1 key without a separate `graph_version` component, a graph re-ingest will not invalidate stale citation results. This is a correctness concern (stale neighbors served after re-ingest), not just a performance concern. The implementation must either (a) add `graph_version` to the Tier-1 key for citation queries, or (b) exclude `cite_neighbors` results from Tier-1 caching. The synthesis flags this as an open question; it should be a concrete implementation requirement.

**Suggested scope adjustment:** The implementation is genuinely S-sized. The two clarifications above — enum re-alignment decision and `graph_version` cache-key addition — are pre-work that should be resolved in the research phase before implementation begins. Neither changes the size estimate. Flag in the milestone brief: direction-enum re-alignment is the recommended path; `graph_version` must be added to the cache key.

---

### CAND-5 — Mathlib premise/declaration search tool (`search_mathlib`)

**Severity: MINOR**

**Objections:**

- **Axis 9 (Value density / scope):** The synthesis correctly identifies the scope-expansion tension: "does arXMCP's scope expand to host [Mathlib], or is `search_mathlib` a separate concern?" The CLAUDE.md §2 scope statement is "local-first MCP server that exposes a research-mathematics arXiv corpus." Adding a second corpus (Mathlib4 Lean declarations) is a scope expansion by definition. The synthesis notes this tension in §4.4 but does not resolve it — Phase 4 must make an explicit scope decision. The CHALLENGER position: CAND-5 is in-scope as a semantic mode (NL → Mathlib declarations via pre-built offline index) and out-of-scope as a type-directed mode (Loogle-style type-pattern search requires a Lean elaborator, which is a runtime Lean dependency that CAND-5 v1 says it avoids). A v1 cut that does only the semantic mode is genuinely M-sized and respects the local-first constraint; the type-directed mode belongs in a CAND-5b dependent on CAND-1.

- **Axis 4 (MCP tool-surface contract):** A new `search_mathlib` tool requires `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. The result rows are Mathlib declarations (name, statement, docstring), not arXiv chunks — they do not carry `chunk_id` or `paper_id` fields. The synthesis should explicitly state that the snippet contract (`.claude/docs/snippet-contract.md`) does NOT apply to `search_mathlib` result rows and that a new result-row schema (and corresponding `server/schemas/search_mathlib_result.json`) must be defined and frozen. This is a concrete deliverable the synthesis omits.

- **Axis 8 (Effort honesty):** The synthesis labels this M and estimates "one-time offline indexer extracts declaration metadata from `mathlib4` source." The Mathlib4 source is ~400K lines of Lean 4 code. Extracting declaration metadata requires either (a) parsing Lean 4 source files with a Lean 4 tool (which needs a local Lean toolchain and a mathlib4 build — itself a 2–4 GB build), or (b) using a pre-exported JSON artifact if one exists. The synthesis cites "LeanSearch v2 'hierarchy-informalized' preprocessing" as the corpus-construction pattern but does not confirm whether a pre-built Mathlib declaration JSON export is readily available or whether arXMCP must generate it. This ambiguity can hide an S-to-L effort swing. Confirm whether `mathlib4-tools` or the LeanSearch v2 artifact pipeline provides a ready-to-download declaration index before committing to the M size.

**Suggested scope adjustment:** v1 = semantic mode only (NL → Mathlib declaration via pre-built index, no Lean elaborator required). Gate the type-directed mode (Loogle-style) on CAND-1 in the Phase 4 DAG. Confirm pre-built declaration index availability before scheduling; if a build step is required, upsize to L.

---

### CAND-7 — Complete the dual-column proof-chunk RRF

**Severity: MINOR**

**Objections:**

- **Axis 7 (Retrieval-quality regression):** The synthesis flags "doubling the ANN over-fetch raises memory pressure" as an open question. This is also a potential nDCG@5 regression surface: the dual-column RRF fuses statement-chunk ANN, proof-chunk ANN, and BM25. Without the curated eval fixture (CAND-14), there is no way to measure whether the fusion improves or regresses nDCG@5 on the math.AG seed corpus. The synthesis correctly identifies CAND-14 as a prerequisite for evaluating retrieval changes, but does not list CAND-7 as having a CAND-14 dependency. It should.

- **Axis 4 (MCP tool-surface contract):** The synthesis notes "Update the tool description (schema-hash re-pin)." This is correct but understates the surface: the `search_papers` tool description currently warns "WARNING: v1 indexes statement chunks only — proof chunks are not retrievable until E07's dual-column RRF lands." Removing that warning and updating the description is a schema hash re-pin that is non-trivial to forget. The implementation checklist must include `pytest --update-tool-schema-hash`.

- **Axis 5 (Internal consistency):** The synthesis notes "`E07_S04` is marked SHIPPED in the roadmap but the tool description contradicts it." This is a roadmap/code inconsistency that should be resolved before CAND-7 begins implementation — confirm whether E07_S04 descoped dual-column RRF deliberately or whether it was an oversight. If it was descoped deliberately, the roadmap entry should be corrected before CAND-7 is scheduled as a new milestone.

**Suggested scope adjustment:** Add CAND-14 as a soft prerequisite (at minimum, create the eval fixture in parallel so a before/after nDCG@5 measurement is possible). Resolve the E07_S04 roadmap inconsistency as a pre-work step (a `chore(notes):` commit). The implementation itself is S-sized and clean.

---

### CAND-8 — `get_paper` metadata table

**Severity: MINOR**

**Objections:**

- **Axis 4 (MCP tool-surface contract):** The synthesis notes "Tool description references 'null until a real papers table lands' — updating it re-pins the schema hash." This is correct. The description change is small but the `EXPECTED_TOOL_SCHEMA_SHA256` re-pin is a mandatory implementation step. Because `get_paper` is an existing tool (not a new one), the re-pin affects the same hash that guards the full `tools/list` byte-stability. All 7 tools' schema bytes are covered by the single `EXPECTED_TOOL_SCHEMA_SHA256`; any description change to any tool re-pins the whole hash. This is load-bearing for BP1 cache discipline (`.claude/notes/07-multi-agent-caching.md` Property 1).

- **Axis 5 (Local-first):** The synthesis mentions an optional `tldr` field populated via S2's TLDR endpoint "an outbound call; see §4 local-first tension." CAND-8 should not include the S2 TLDR enrichment in its v1 scope. The local-first principle is explicit in CLAUDE.md §4.1 and the local-first tension is flagged in synthesis §4.3. The TLDR enrichment belongs in a separate, explicitly opt-in enrichment path (behind an `ARXMCP_S2_API_KEY` env var) that is out of CAND-8's core scope.

**Suggested scope adjustment:** CAND-8 v1 = populate `authors`, `title`, `abstract`, `year`, `categories` from the already-fetched OpenAlex and INSPIRE-HEP data (no new outbound calls). No TLDR field in v1. The Kùzu `papers` table is the right storage choice (lightest, no re-embed). Explicitly exclude S2 TLDR from this milestone scope.

---

### CAND-13 — Paper version-awareness + version-diff tool

**Severity: MINOR**

**Objections:**

- **Axis 7 (Retrieval-quality regression):** Adding an `arxiv_version` column to `ingest/schema.py` requires a partial re-embed (E11_S03 partial re-embed strategy). The synthesis notes this. The retrieval-quality impact of a partial re-embed on the existing nDCG@5 gate needs a before/after measurement — another soft prerequisite on CAND-14. Without the eval fixture, a re-embed that inadvertently changes the embedding alignment (e.g. due to a `model_version` string change in the cache key) could silently degrade retrieval. This is a low-probability risk but the eval fixture is the backstop.

- **Axis 8 (Effort honesty):** The synthesis notes "Retaining multiple versions of the same paper roughly doubles per-paper storage — acceptable at corpus scale?" The 50-paper seed corpus doubles to 100 virtual papers if both v1 and v3 are retained for each; this is fine. At full-corpus scale, the storage implication is non-trivial. The synthesis should bound this with a concrete estimate or an explicit "evaluate at full-corpus scale" trigger, analogous to the CAND-15 pattern. The `get_paper_versions` tool (version listing only) is genuinely S-sized; the version-level structural diff (v1 vs v3 chunk comparison) is M-to-L and the synthesis correctly defers it to an optional second step.

**Suggested scope adjustment:** v1 = `arxiv_version` column on chunks + `get_paper_versions` tool returning version list and ingest timestamps only. No structural diff. New tool requires schema hash re-pin. Structural diff is v2. Recommend adding a storage-estimate note to the milestone brief for the full-corpus scenario.

---

## 5. Clean candidates

- **CAND-9 — Citation-graph re-ranking via GNN over Kùzu edges** (NONE — the synthesis itself correctly weights this as weak-signal (1 source), L-sized, and explicitly dependent on CAND-2/CAND-3 being solid first; the synthesis's own characterization matches what a CHALLENGER would say; no additional objection needed beyond the synthesis's own framing)
- **CAND-10 — Migrate BM25 to LanceDB's native FTS tokenizer** (NONE — correctly identified as beta-channel risk; the synthesis's "careful version bump + regression test" caveat is the right constraint; no architecture-lock issue; effort is M but value is concrete operational simplification)
- **CAND-12 — MCP progress notifications for long-running tools** (NONE — the synthesis correctly notes the structural refactor cost (touching all handler signatures + tools.py registration) and that the benefit is zero if the client ignores notifications; both are real and correctly weighted; no architecture-lock issue; the `mcp>=1.27,<2` pin includes the capability)
- **CAND-14 — Curate the 20-query eval fixture** (NONE — purely execution work following an existing runbook; no architecture-lock issue; no tool-surface change; requires math-domain judgement as noted; correctly sequencing-critical as identified by the synthesis)

---

## 6. Cross-cutting concerns

**CC-1: DAG edges are underspecified across the catalog.** CAND-4 depends on CAND-1 (hard). CAND-6 depends on CAND-1 (hard, near-zero standalone value). CAND-11 depends on CAND-14 (hard, uncalibrated without it). CAND-7, CAND-9, CAND-13, CAND-15 depend on CAND-14 (soft, but nDCG@5 regression evidence is unavailable without it). CAND-9 depends on CAND-2 and CAND-3 (synthesis states this but the catalog does not encode it). Phase 4 must produce an explicit DAG before scheduling.

**CC-2: `EXPECTED_TOOL_SCHEMA_SHA256` re-pin is a recurring undercounted cost.** Candidates that add or modify MCP tools: CAND-1, CAND-2 (if enum re-aligned), CAND-4 (if mode parameter added), CAND-5, CAND-7 (description update), CAND-8 (description update), CAND-11, CAND-13 (new tool). Each re-pin is a `pytest --update-tool-schema-hash` invocation and a deliberate commit. Collectively, scheduling multiple tool-touching candidates in parallel risks hash conflicts. Phase 4 should sequence tool-surface changes to minimize re-pin collisions. Rule of thumb: no more than one open milestone touching `server/tools.py` at a time.

**CC-3: `CAND-14` (eval fixture curation) is the quality gate for half the catalog.** CAND-6, CAND-7, CAND-9, CAND-10, CAND-15 all change retrieval behavior; CAND-11 depends on calibration against the eval fixture. Without CAND-14, five candidates ship without measurable regression evidence. The synthesis §4.5 notes this correctly. Phase 4 should either schedule CAND-14 first or at minimum require it to be in-flight before any retrieval-behavior-changing candidate reaches its implementation phase.

**CC-4: Supply-chain discipline from E13 must be applied to all new external dependencies.** CAND-3 (Kùzu fork), CAND-1 (Lean toolchain system dependency), CAND-5 (Mathlib4 index artifact). Each introduces a new supply-chain surface. E13_S05 (Supply-chain audit) established arXMCP's Threat-6 posture; any new dependency (including `git+` pins and new PyPI packages) should pass through the same checklist before being added to `pyproject.toml`. The CAND-3 BLOCKER is the most acute instance, but CAND-1 (Lean as a system dependency) and CAND-5 (Mathlib4 declaration index as a large offline artifact) share the same concern class.

**CC-5: The `server/prompts.py` system-prompt placeholder is a latent dependency for multiple candidates.** CAND-11 (`retrieval_confidence` signal) and CAND-6 (proof-state-conditioned retrieval) both generate new agent-facing signals that agents must be instructed how to use. Without an authored system prompt, these signals are structurally present but behaviorally invisible. The adversary brief correctly rates this as L1 (LOW) in isolation, but it becomes a MAJOR dependency when multiple new signals are added without instructions.

---

## 7. Recommended kill list

No candidates are recommended for outright kill. The BLOCKER on CAND-3 is a redesign (confirm PyPI availability before scheduling), not a kill. CAND-9 and CAND-15 are correctly deferred by the synthesis itself; the CHALLENGER concurs and recommends keeping them in a v2 backlog rather than removing them from the catalog. All other candidates are shippable with the scope adjustments described above.

**Note on CAND-9 specifically:** The synthesis correctly assesses GNN re-ranking as weak-signal, L-sized, and requiring a healthy citation graph first. At 50 papers, the Kùzu graph is too sparse for GNN training signal; this candidate should be re-evaluated when the corpus reaches 500+ papers. A formal "re-evaluate when corpus > 500 papers" trigger note should be added to the catalog entry in any Phase 4 output.
