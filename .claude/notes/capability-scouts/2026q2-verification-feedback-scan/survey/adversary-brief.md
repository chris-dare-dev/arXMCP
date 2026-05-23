# Adversary Brief — 2026q2 Verification-Feedback Scan

**Scout role:** Current-state adversary  
**Generated:** 2026-05-22  
**Scope:** Execution-feedback and verification surfaces; `cite_neighbors` MCP tool gap; adjacent capability gaps in the sketcher → autoformalizer → tactician → fixer consumer

---

## 1. Executive summary

arXMCP v1 is a credible retrieval substrate for grounding the pre-verification roles (sketcher, autoformalizer, tactician). Its core failure for the stated consumer is structural: the system never closes the verification-feedback loop. The Lean kernel is explicitly named as the intended critic, but no mechanism exists — not even a stub, a design doc, or an un-parking trigger — to route execution output from a Lean process back through the MCP surface to the fixer agent. The `cite_neighbors` MCP tool, acknowledged as a v1 stub since E09, remains unwired seven milestones later despite the underlying library (`server/graph_queries.py`) being fully operational. Adjacent gaps compound the problem: the `get_paper` tool returns null metadata fields (authors, title, abstract, year), there is no Mathlib-to-arXiv alignment surface, and the eval harness that should gate retrieval quality changes has no curated queries against which nDCG@5 can actually be measured.

Highest-severity gaps: **Lean kernel verification-feedback loop absent** (HIGH); **`cite_neighbors` MCP tool wired to dead stub** (HIGH); **`get_paper` returns null metadata** (HIGH). Total: 0 CRITICAL, 3 HIGH, 4 MEDIUM, 3 LOW.

---

## 2. Critical gaps

None. arXMCP shipped a coherent retrieval infrastructure and its stated v1 scope does not claim to provide execution feedback. The absence of Lean integration is a documented design deferral (E14_S06), not an unacknowledged regression. Inflating this to CRITICAL would misrepresent the project's stated scope.

---

## 3. High gaps

### H1 — Lean kernel verification-feedback loop absent from MCP surface

**Severity:** HIGH

**What comparable systems / SOTA expects:**
Every 2025-class autoformalization system that operates in the sketcher → tactician → fixer pattern uses a Lean REPL or process with proof-state output as a first-class feedback channel to the fixer agent. DeepSeek-Prover-V2 (arXiv:2504.21801) and Goedel-Prover both structure RL training around the accept/reject signal from Lean's kernel. LeanDojo (CMU/Caltech, on the repo's own prior-art list at `.claude/notes/10-references-and-prior-art.md`) exposes tactic-level proof state to Python so that retrieval-augmented LLMs can interact step-by-step. Kimina-Prover (arXiv:2504.11354) interleaves natural-language scratchpad with Lean tactic streams and filters on kernel output. A 2026 reviewer of a research-math retrieval server explicitly designed to support this pipeline would expect at minimum a `verify_lean` or `lean_kernel_query` MCP tool that accepts a Lean 4 snippet and returns the compile/typecheck/proof-state output from a local Lean process.

**What arXMCP has today:**
Nothing. The design constitution (`.claude/notes/01-mission-and-context.md` line 127) states "if we add a 'critic' tool, it's a thin wrapper around Lean kernel output, not a free-running LLM," which acknowledges the need. E14_S06 (`.claude/roadmap/E14-observability-ops.md` line 236) parks "Lean 4 toolchain integration (LeanDojo bindings)" as Tier 7 / v2 deferred with un-park trigger "a dedicated v2 design document exists." The superseded note at `.claude/notes/09-feature-priorities.md` line 135 places it as Tier 7. There is no tool, no stub, no handler file, no `server/handlers/lean_verify.py`, and no design document. Searching `server/` and `ingest/` for `lean`, `LeanDojo`, `proof_state`, or `tactic` finds zero production code (only comments mentioning Lean as the intended critic).

**What a credible v1 fill-in would look like:**
A `lean_verify` MCP tool that spawns or communicates with a persistent Lean 4 REPL process (LeanDojo's `LeanServer` or the standalone `lean-repl` from `leanprover-community/repl`). The handler accepts a `snippet: str` of Lean 4 code, submits it to the subprocess, and returns structured output: `{"status": "ok"|"error", "messages": [...], "proof_state": "<tactic-state-string>|null", "elapsed_ms": int}`. The fixer agent receives structured error output from Lean rather than having to infer failure from silence. The tool is gated behind `ARXMCP_ENABLE_LEAN=false` (off by default, matching the `ARXMCP_ENABLE_RERANK` pattern) so the server starts cleanly on machines without a Lean toolchain. The key design constraint is that Lean process management belongs in a sidecar or subprocess, NOT as an in-process Python call — Lean is a separate OS process and its stderr/stdout carry the verification signal.

**Architecture-lock interaction:**
The no-anthropic-SDK-at-runtime rule (CLAUDE.md §4.7) does not apply here. The pure-ASGI middleware rule means the handler must not block the event loop — the Lean subprocess call must go through `asyncio.to_thread` or `asyncio.create_subprocess_exec`. No-fork policy says "no code lifted from existing repos," which is satisfied by wrapping the REPL protocol, not copying it. Adding this tool requires re-pinning `EXPECTED_TOOL_SCHEMA_SHA256` per CLAUDE.md §9 step 4.

**Why this hasn't been fixed yet:**
Explicitly parked at Tier 7 (E14_S06). The project philosophy — correctly — identifies Lean integration as a v2 concern that requires a dedicated design document. The deferral is principled, not neglect. The gap is HIGH rather than CRITICAL because arXMCP's v1 scope is explicitly a retrieval substrate, not an execution engine.

---

### H2 — `cite_neighbors` MCP tool wired to a dead stub seven milestones after the library shipped

**Severity:** HIGH

**What comparable systems / SOTA expects:**
Citation-graph traversal is table stakes for any 2026 research-math retrieval server. PaperQA2 (`github.com/Future-House/paper-qa`, on arXMCP's prior-art list) uses citation chains as a first-class retrieval primitive. The `kyrylo-gr/lookup-arxiv-mcp` project (also on the prior-art list) adds Semantic Scholar citation enrichment as its primary differentiator. Any user of the sketcher → autoformalizer workflow who wants to pull in cited lemmas cannot do so through the MCP surface today — they must call `server.graph_queries.cite_neighbors` directly in Python, which is only available to developers, not to agents.

**What arXMCP has today:**
The library `server/graph_queries.py::cite_neighbors` (shipped E09_S03, tested, async-safe, direction-filtered, deduped, 500ms performance-gated) is fully functional. The Kùzu citation graph is populated by `ingest/graph_ingest.py` (OpenAlex), `ingest/inspire_ingest.py` (INSPIRE-HEP), and `ingest/intra_paper_refs.py`. The MCP handler `server/handlers/citations.py` is a v1 stub (lines 1–93) that returns `{"neighbors": [], "infrastructure_status": "deferred"}` for every input. CLAUDE.md §7 documents this explicitly. The proof-chain workflow doc (`.claude/docs/proof-chain-workflow.md`) explicitly notes the wiring is deferred and instructs agents to "call the library directly." The stub has been in place through milestones E09 through the seven `proof-verify-handler-wiring` milestones (m1–m7), none of which closed this gap — those milestones wired `search_papers` filters, added notebook scaffolding, and built a UI REST layer.

**What a credible v1 fill-in would look like:**
The handler needs to call `await server.graph_queries.cite_neighbors(chunk_id, depth, direction, max_results, kuzudb_path, lancedb_path)` and serialize the resulting `list[CitationNeighbor]` into the established envelope format. The path-validation contract flagged in the library's own docstring (F2 from E09_S03: "The MCP-tool wrapper MUST NOT pass agent-supplied JSON arguments through to either path — derive them from Resources / Config instead") is satisfied by reading paths from `get_resources()` rather than from handler arguments. The `CitationNeighbor` dataclass already has all the fields needed (`chunk_id`, `paper_id`, `edge_kind`, `hop_distance`, `source`, `confidence`). The direction enum mismatch between the handler (`"citers"`, `"cited"`, `"co_cited"`, `"co_citing"`, `"depends_on"`) and the library (`"cites"`, `"cited_by"`, `"depends_on"`) needs a mapping layer or a handler-side enum re-alignment. The byte cap helper `cap_result_list` is already plumbed for this handler (`_cap` in `server/handlers/citations.py` line 23–48).

**Architecture-lock interaction:**
No hard rules are violated. The Resources singleton provides the Kùzu and LanceDB paths (satisfying the path-validation contract). Adding real data to an existing handler does not change the tool schema, so `EXPECTED_TOOL_SCHEMA_SHA256` does not need re-pinning unless the description string changes.

**Why this hasn't been fixed yet:**
The E09_S03 critique flagged the F2 path-validation contract as blocking handler wiring: "handler-wiring is deferred to a future milestone where the path-validation contract can be formalized at the boundary." The seven subsequent `proof-verify-handler-wiring` milestones addressed different parts of the system (filters, notebook UI). The deferred status is a prioritization choice that has outlasted its justification — the path-validation issue is straightforward to resolve and the library is ready.

---

### H3 — `get_paper` returns null metadata fields (authors, title, abstract, year, categories)

**Severity:** HIGH

**What comparable systems / SOTA expects:**
Every comparable arXiv retrieval server returns paper metadata. The `blazickjp/arxiv-mcp-server` (arXMCP's most-starred reference) returns title, authors, abstract, and year as first-class fields. The fixer agent in the consumer pipeline uses `get_paper` to build citation context for retrieved proofs — a result with null authors, null title, and null abstract is not actionable. An autoformalizer agent that retrieved `cite_neighbors` results (once H2 is closed) would call `get_paper` on each neighbor to understand what the cited paper is about; null metadata forces a separate search-and-filter query, consuming the 3-round MCP budget.

**What arXMCP has today:**
`server/handlers/paper.py` (docstring, lines 1–18) documents: "authors, title, abstract, year, categories → null (not in the v1 schema)." CLAUDE.md §7 confirms: "`get_paper` returns NULL for `authors`/`title`/`abstract`/`year`/`categories` — no `papers` metadata table at v1." The handler synthesizes chunk_count, section_count, chunker_version, and embedder_version from the chunks table — these are ingest-process metadata, not paper-content metadata. The design notes at `.claude/notes/01-mission-and-context.md` line 122 identify the fixer's need for "version-diff (v1 vs v3 of the same paper)," which requires paper-level metadata.

**What a credible v1 fill-in would look like:**
OpenAlex already ingests paper metadata during `ingest/graph_ingest.py` — title, authors, year, and abstract are available from the OpenAlex `/works` API response. INSPIRE-HEP provides the same for hep-th/math-ph. A `papers` table in the Kùzu DB (or a separate SQLite sidecar) populated at ingest time would be the minimal addition. The `get_paper` handler then reads from this table instead of synthesizing from chunks. The alternative — adding columns to the LanceDB `chunks` table — is heavier (requires re-embed + re-ingest) but would unify the storage path. The arXiv OAI-PMH metadata already captured by the delta loop (E11_S02) carries title/authors/abstract in the OAI record and could backfill the table without an additional API call.

**Architecture-lock interaction:**
Adding a metadata table to Kùzu would not conflict with the no-fork, pure-ASGI, or caching rules. The handler change does not alter the tool schema (description string references "null until a real papers metadata table lands" — updating this would require a schema hash re-pin). The BP1/BP2 byte-stability rule means the tool description must be updated atomically with the hash re-pin.

**Why this hasn't been fixed yet:**
The design positions this as an E11/E12 deliverable ("until a real papers metadata table lands (E11/E12)"). E11 shipped the bulk ingest orchestrator but the metadata table was not scoped into the milestone. E12 was folded into E11. The Kùzu schema (`ingest/kuzudb_schema.py`) stores only `paper_id` and `cites` edges; it does not store title, authors, or abstract.

---

## 4. Medium gaps

### M1 — Eval harness has no curated queries; nDCG@5 gate cannot actually fire

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
A retrieval system claiming Tier-2 production readiness should have a functioning quality gate. The E05 eval harness design is sound, but without curated queries the gate is ceremonially open — any retrieval change can ship without measurable regression evidence. BEIR-style evaluation (Thakur et al., arXiv:2104.08663) and the LoTTE benchmark (Santhanam et al.) establish that domain-specific test sets are the minimum for credible retrieval evaluation.

**What arXMCP has today:**
The harness (E05, `tests/eval/`) is shipped and `make eval` runs. The 20-query fixture referenced in CLAUDE.md §7 ("still being hand-labeled per `.claude/docs/eval-curation.md`") is still empty — CLAUDE.md §10's troubleshooting table says "`make eval` skipped — `tests/eval/fixtures/queries.json` is still an empty stub." The Tier-0 → Tier-1 gate (`pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70`) cannot pass or fail if the fixture has no queries. The `.claude/docs/retrieval-quality-report.md` is labeled "PRELIMINARY."

**What a credible v1 fill-in would look like:**
Hand-label 20 queries against the 50-paper math.AG seed corpus following the curation runbook (`.claude/docs/eval-curation.md`). Each query needs a list of relevant chunk_ids (at least one per query). The labeled set then makes `make eval` meaningful and gates retrieval changes. The curation runbook exists; the work is execution, not design.

**Architecture-lock interaction:**
None. The eval fixture is test data, not server code. No hard rules apply.

**Why this hasn't been fixed yet:**
Hand-curation is tedious and requires domain knowledge. The runbook exists but no milestone has been scoped to actually complete the labeling.

---

### M2 — No Mathlib-to-arXiv alignment tool; tactician agent has no formal library grounding

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
Systems targeting Lean 4 proofwriting (LeanDojo, Lean Copilot, DeepSeek-Prover-V2) all include a mechanism for grounding retrieved informal lemmas in the formal library. The Lean 4 Mathlib library (400K+ lines of formalized mathematics) is the canonical target for the autoformalizer; an agent that retrieves an informal statement from arXMCP needs to know whether a corresponding Mathlib lemma exists, and if so, what its exact Lean name is. Without this mapping, the tactician must guess Mathlib lemma names and suffer repeated sorry/compile-error cycles.

**What arXMCP has today:**
`find_lemma_by_name` (E10_S02) does FTS5 + Jaccard matching against the theorem-name index built from the arXMCP corpus. It does NOT cross-reference Mathlib. E14_S06 (`.claude/roadmap/E14-observability-ops.md` line 238) parks "Mathlib lookup" as Tier 7 / v2 deferred, gated behind Lean integration. The deferred note acknowledges "maps arXMCP theorem-name hits to Mathlib lemma names." No mapping table, no cross-reference index, and no `mathlib_lookup` tool exists anywhere in the server or ingest pipeline.

**What a credible v1 fill-in would look like:**
A Mathlib declaration index — a SQLite table built offline from `mathlib4` source by extracting theorem/lemma/definition names and their informal descriptions — could be bundled as a static artifact alongside the corpus (similar to the definitions table). A `mathlib_lookup` tool would accept a theorem name (or a set of keywords from a retrieved arXMCP chunk) and return matching Mathlib declarations with their fully-qualified Lean names. This does not require a running Lean process; it is a text-search problem over a pre-built index. The Mathlib4 repository exports declaration metadata; tools like `mathlib4-search` (based on exact-match + semantic search over the `@[doc string]` annotations) are already available in the ecosystem.

**Architecture-lock interaction:**
Adding a new tool requires re-pinning `EXPECTED_TOOL_SCHEMA_SHA256`. The no-fork rule permits building an indexer from Mathlib4 source without lifting code. The local-first principle is respected (offline index, no runtime API call).

**Why this hasn't been fixed yet:**
Scoped as Tier 7 (v2 deferred), gated behind Lean integration. The design correctly observes that Mathlib lookup is most valuable when a Lean REPL is present to use the results. Without H1 closed, M2 has low standalone utility.

---

### M3 — `search_papers` BM25 path does not run over proof chunks; dual-column RRF incomplete

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
The tactician agent's primary retrieval mode is proof-chunk retrieval — finding how a similar lemma was proved, not just that its statement exists. The E07 hybrid retrieval was designed to address this via dual-column ANN (embedding_stmt + embedding_proof) fused with RRF. A retrieval system for a proof-writing pipeline that only indexes statement embeddings in its ANN path is structurally incomplete for the tactician's workload.

**What arXMCP has today:**
The `SEARCH_PAPERS` tool description (server/tools.py line 154) explicitly warns: "WARNING: v1 indexes statement chunks only — proof chunks are not retrievable until E07's dual-column RRF lands." The ANN call in `server/handlers/search.py` searches over `embedding_stmt` only. The `embedding_proof` column is populated in LanceDB (E03_S01 dual-column encoding), but the retrieval handler does not query it. The BM25 path (E07_S01) indexes `body_tokens` which does include proof text, so BM25 covers proof content — but the ANN path does not, and ANN dominates precision in the hybrid pipeline.

**What a credible v1 fill-in would look like:**
The existing `server/retrieval/rrf.py` (E07_S02) implements Reciprocal Rank Fusion and was designed for dual-ANN + BM25 fusion. Extending `handle_search_papers` to issue a second ANN query over `embedding_proof` (with the same query vector, same prefilter, over-fetching k*3) and pass both result sets through RRF alongside BM25 is the intended E07 design. The `level` parameter already controls deduplication; a proof-chunk result and a statement-chunk result for the same paper would deduplicate at the `level='paper'` stage. The main cost is that the over-fetch multiplier doubles memory pressure on the ANN call.

**Architecture-lock interaction:**
No hard rules violated. The schema already has `embedding_proof`; no re-ingest is needed. The retrieval change does not affect the tool schema (description update would require hash re-pin but the description already says "dual-column RRF lands in E07").

**Why this hasn't been fixed yet:**
The tool description notes it as deferred to "E07's dual-column RRF." E07 shipped BM25 + single-column ANN + reranker; the dual-column extension was not completed. The milestone (`E07_S04`) in `.claude/roadmap/README.md` is listed as SHIPPED but the tool description contradicts this — the nDCG@5 gate presumably passed on statement-only ANN, and the dual-column extension was not considered a gate blocker.

---

### M4 — No paper version-diff tool; fixer cannot compare v1 vs v3 statement/proof changes

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
arXiv papers are frequently revised; v1 often has the cleaner statement, v3 the corrected proof (`.claude/notes/01-mission-and-context.md` line 122 names this as an explicit fixer need). Systems that retrieve specific theorem versions without awareness of revision history will surface incorrect or superseded lemma statements to the autoformalizer. Academic paper retrieval systems that handle arXiv content (e.g., Semantic Scholar's version-aware metadata) track revision history as a first-class attribute.

**What arXMCP has today:**
The chunker (`ingest/chunker.py`) stamps `chunker_version` and `embedder_version` per chunk but not arXiv version (`v1`, `v2`, `v3`). The LanceDB schema (`ingest/schema.py`) has no `arxiv_version` column. `get_paper` returns null for most metadata. The OAI-PMH delta loop (E11_S02) fetches updated paper versions but the updated version replaces the previous ingest — there is no mechanism to retain both v1 and v3 of the same paper in the corpus for comparison. No `get_paper_versions` tool or `version_diff` tool exists.

**What a credible v1 fill-in would look like:**
The arXiv `/e-print/<id>v<N>` endpoint provides specific version downloads. Storing a `arxiv_version` column on each chunk (populated at ingest time from the download URL) would allow `search_papers` to filter by version. A minimal `get_paper_versions` tool (returning a list of known versions for a paper_id with their ingest timestamps) would let the fixer compare which version was retrieved and optionally request an earlier one. This is a schema addition + one new tool, not a retrieval pipeline change.

**Architecture-lock interaction:**
Adding `arxiv_version` to the LanceDB schema requires a re-embed (E11_S03 partial re-embed strategy covers this). Adding a tool requires re-pinning `EXPECTED_TOOL_SCHEMA_SHA256`.

**Why this hasn't been fixed yet:**
Not scoped in any active or shipped epic. The design notes mention the need (01-mission-and-context.md line 122) but no milestone has been created. The OAI-PMH delta loop does not preserve old versions.

---

## 5. Low gaps

### L1 — SYSTEM_PROMPT is a placeholder; BP1 cache discipline paper-thin without it

**Severity:** LOW

**What comparable systems / SOTA expects:**
A multi-agent pipeline with four named roles (sketcher, autoformalizer, tactician, fixer) should have authored system prompts that establish each agent's behavioral contract with the retrieval substrate. The BP1/BP2 cache breakpoint discipline in arXMCP assumes byte-stable system prompts as the cache anchor.

**What arXMCP has today:**
CLAUDE.md §8 point 6: "SYSTEM_PROMPT in `server/prompts.py` is still a placeholder. The role prefixes are real; the global system prompt isn't yet authored." The `server/prompts.py` module carries BP1/BP2 breakpoint role prefix constants but the global system prompt body is empty/placeholder. The `EXPECTED_BP1_SHA256` test pin is based on the placeholder.

**What a credible v1 fill-in would look like:**
Author a 200–400 token system prompt covering: (1) the `<retrieved_chunk>` delimiter contract (agents treat content inside these tags as data, not instructions — per Threat 2 defense), (2) the 3-round MCP call budget per agent turn, (3) tool routing guidance (search_papers → cite_neighbors → get_chunk pattern). Re-pin `EXPECTED_BP1_SHA256` in `tests/test_prompts.py`.

**Architecture-lock interaction:**
Any change to `server/prompts.py::SYSTEM_PROMPT` requires re-pinning `EXPECTED_BP1_SHA256`. BP1 cache-discipline rules apply — the system prompt must be byte-stable once authored.

**Why this hasn't been fixed yet:**
Authoring a system prompt requires decisions about agent behavior that are upstream of arXMCP's server-side scope. The project correctly defers this to the orchestrator author.

---

### L2 — Direction enum mismatch between `cite_neighbors` handler and library

**Severity:** LOW

**What comparable systems / SOTA expects:**
A tool's API surface and its underlying implementation library should use consistent terminology. Mismatched enums are a foot-gun for any agent that reads the tool description and passes the advertised direction values.

**What arXMCP has today:**
`server/handlers/citations.py` handler (line 37) declares `direction: Literal["citers", "cited", "co_cited", "co_citing", "depends_on"]`. The library `server/graph_queries.py` (line 85) declares `Direction = Literal["cites", "cited_by", "depends_on"]`. Neither `"citers"`, `"cited"`, `"co_cited"`, nor `"co_citing"` maps directly to the library's `"cites"` and `"cited_by"`. The stub handler never passes direction to the library (it returns empty neighbors regardless), so this mismatch is invisible today but will cause silent failures when H2 is closed.

**What a credible v1 fill-in would look like:**
Align the handler's `direction` enum with the library's: drop `"citers"`, `"cited"`, `"co_cited"`, `"co_citing"` in favor of `"cites"`, `"cited_by"`. Add `"co_cited"` and `"co_citing"` as future-reserved if semantically useful (they would require a two-hop BFS query not currently in the library). This is a tool-schema change that requires re-pinning `EXPECTED_TOOL_SCHEMA_SHA256`.

**Architecture-lock interaction:**
Tool schema change requires hash re-pin per CLAUDE.md §9.

**Why this hasn't been fixed yet:**
The stub never exercises the library, so the mismatch has no runtime consequence. No one has had reason to notice it.

---

### L3 — Kùzu archived 2025-10-10; no migration path documented beyond a pointer

**Severity:** LOW

**What comparable systems / SOTA expects:**
A dependency on an archived library with no active maintainers is a known technical debt item. Production graph databases with active development (Neo4j embedded, ArangoDB embedded, or the Kùzu community forks mentioned in CLAUDE.md) are available.

**What arXMCP has today:**
CLAUDE.md §8 point 2: "Kùzu was archived 2025-10-10. We pin `kuzu==0.11.3` exactly (the last stable, MIT). Future fork migration (`Kineviz/bighorn` or `Vela-Engineering/kuzu`) is tracked but out of scope." The Kùzu pin is correct and the citation graph is functional. No migration plan or timeline exists beyond "tracked but out of scope."

**What a credible v1 fill-in would look like:**
Evaluate `Kineviz/bighorn` or `Vela-Engineering/kuzu` for API compatibility with `kuzu==0.11.3`. If compatible, add a migration note to E14_S06. If not, document the migration effort as a concrete scoped task rather than an open pointer.

**Architecture-lock interaction:**
None until a migration is actually undertaken. Swapping the graph DB would require testing all Cypher queries in `server/graph_queries.py` against the new backend.

**Why this hasn't been fixed yet:**
`kuzu==0.11.3` works. The project correctly defers migration until there is a functional reason to migrate.

---

## 6. What arXMCP does well

- **Math fidelity is genuinely better than comparable tools.** LaTeXML-first parsing with macro expansion before embedding directly addresses the core failure mode of every other arXiv MCP server (PyPDF equation mangling). The preamble extractor and dual-column chunker (theorem/proof split at ≤512 tokens) are principled design choices backed by the E03 and E07 eval work.
- **The 3-tier retrieval cache with BP1/BP2 byte-stability discipline is architecturally sound.** The insight that prompt-cache reuse requires deterministic tool result bytes — and that this demands version-pinned corpus reads, sorted JSON keys, and no-timestamp results — is not obvious and is correctly implemented end-to-end.
- **Security hardening is unusually thorough for a single-developer local tool.** E13 produced 10 milestones covering path-traversal (Threat 1), prompt injection (Threat 2), LaTeXML sandbox (Threat 3), resource exhaustion (Threat 4), DNS rebinding (Threat 5), supply-chain (Threat 6), and TLS pinning (Threat 7). The `wrap_retrieved_text` delimiter escaping and `is_valid_chunk_id` / `is_valid_paper_id` boundary checks are consistently applied.
- **The milestone-pipeline 4-phase protocol (research → implement → critique → rectify) produces measurable quality.** The adversary critique findings tracked across milestones (with explicit rectification commits and regression test additions) represent a disciplined development process that has caught real bugs before they shipped.
- **The `find_lemma_by_name` tool with FTS5 trigram + Jaccard fallback is directly useful for the tactician.** The three-step lookup (exact → trigram → fuzzy) with paper_id scoping is the right design for lemma-name resolution in a math corpus where authors use non-standard terminology.
- **The observability surface (Prometheus + OTel + Phoenix) is ship-quality for a v1 local tool.** Per-tool latency histograms, cache-layer metrics, and agent-role tracing (sketcher/autoformalizer/tactician/fixer roles surfaced as span attributes) give operators clear visibility into pipeline behavior.

---

## 7. Themes

**The retrieval substrate is solid; the execution-feedback loop is missing by design, but the design decision is increasingly load-bearing.** Every architectural choice in arXMCP — deterministic bytes, retrieval caps, 3-round budgets — was made in anticipation of a Lean REPL in the loop. The more milestones that ship without Lean integration, the more the design begins to look like a retrieval server without a consumer, rather than a substrate waiting for a well-defined integration point.

**Stub persistence is the dominant failure mode across the gap landscape.** The `cite_neighbors` handler has been a stub through seven milestones. The `get_paper` metadata fields have been null through fourteen epics. The eval fixture has been empty since E05. In each case, the underlying infrastructure (Kùzu graph, OAI-PMH metadata, eval harness) is real; only the wiring step is missing. This pattern — infrastructure ships, wiring defers indefinitely — is the project's characteristic anti-pattern. The proof-verify milestones (m1–m7) that ran concurrently with this scan focused on the notebook UI surface rather than closing any of the three high-priority stubs.

**The consumer pipeline's information needs are well-understood but not yet served at the MCP boundary.** The design notes articulate clearly that the fixer needs version-diff context, the autoformalizer needs Mathlib cross-references, and the tactician needs proof-chunk retrieval. All three remain gaps. The project has correctly deferred some of these (Lean integration, Mathlib lookup) as v2 concerns, but the dual-column ANN and version-diff gaps are within v1's scope and have no active milestone closing them.
