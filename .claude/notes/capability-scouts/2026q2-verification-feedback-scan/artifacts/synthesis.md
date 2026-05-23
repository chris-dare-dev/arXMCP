# Synthesis — Opportunity Catalog — 2026q2-verification-feedback-scan

**Phase 2 deliverable.** Built from 5 survey briefs (comparative, research-frontier, oss-trends, multi-agent, adversary).
**Date:** 2026-05-22

---

## 1. Executive summary

The five scouts converged hard. **14 distinct candidates** survive synthesis across six of the seven taxonomy categories (no standalone Agent-harness candidate — see §4). Two categories dominate: **Verification / proof tooling** and **Citation graph**, which is exactly where the scout brief pointed. The headline finding is unambiguous and 5-way triangulated: arXMCP is an excellent *retrieval substrate* but exposes **no execution-feedback surface** — every one of its 7 MCP tools returns retrieved or pre-computed content, none returns Lean kernel output. Every scout independently named a `lean_verify` tool as the #1 capability, and every scout independently named wiring the `cite_neighbors` stub as the highest-leverage near-zero-risk move. The dominant *tension*: the roadmap parks Lean integration as a v2 / Tier-7 item (`E14_S06`), while the 2026 SOTA has fully converged on the Lean kernel as the universal feedback oracle — the deferral is increasingly load-bearing. The dominant *anti-pattern* the adversary names is "stub persistence" — infrastructure ships, wiring defers indefinitely (`cite_neighbors`, `get_paper` metadata, the eval fixture).

## 2. Triangulation strength

- **4 candidates have 3+ brief sources (strong signal):** CAND-1 (5 briefs), CAND-2 (4), CAND-5 (4), CAND-6 (3).
- **6 candidates have 2 sources:** CAND-3, CAND-4, CAND-8, CAND-12, CAND-13, CAND-14, CAND-15 (7 — see note).
- **4 candidates have 1 source (weak — flag for challenger scrutiny):** CAND-7, CAND-9, CAND-10, CAND-11.

(CAND-1 and CAND-2 are the only candidates surfaced by the outward-looking scouts *and* the adversary — the strongest possible signal: an external SOTA expectation that matches an internal documented gap.)

## 3. Candidate catalog

---

### CAND-1 — Add a Lean kernel verification-trace MCP tool (`lean_verify`)

**Category:** Verification / proof tooling
**Size:** M
**Evidence triangulation:** 5 briefs (comparative ✓, research-frontier ✓, oss-trends ✓, multi-agent ✓, adversary ✓)

**What it is:** A new MCP tool that accepts a Lean 4 snippet (plus context imports) and returns structured kernel output — compilation status, error messages with severity + source position, current proof state / remaining goals, and `sorry` locations. Backed by a managed local Lean 4 subprocess speaking the `leanprover-community/repl` stdin/stdout JSON protocol.

**Why it matters:** arXMCP's whole reason for existing is to ground a sketcher → autoformalizer → tactician → fixer pipeline, yet the tactician and fixer act *blind* after every tactic attempt — they receive retrieved context but never the verifier's verdict. This single tool converts arXMCP from a context-enrichment substrate into a full agent-harness component. It is also exactly what the project's own constitution anticipates: `.claude/notes/01-mission-and-context.md` says "if we add a 'critic' tool, it's a thin wrapper around Lean kernel output, not a free-running LLM."

**Sources:**
- Comparative scout: C1 (LeanDojo `run_tac` structured `TacticState/ProofFinished/LeanError`), C9 (persistent REPL resource).
- Research-frontier scout: 2.1 (`leanprover-community/repl` JSON protocol, ~150–250 LOC), 2.4 (APOLLO's structured error-isolation schema).
- OSS-trends scout: 2.1 (`leanprover-community/repl`, Apache-2.0, 203★, CPU-only, subprocess-safe).
- Multi-agent scout: C1 (`verify_lean_snippet` — "the single change that moves arXMCP from substrate to harness component"), C5 (DeepSeek-Prover-V2 closed loop).
- Adversary scout: H1 (HIGH — "Lean kernel verification-feedback loop absent from MCP surface").

**Closest arXMCP analog (today):** No analog. No `server/handlers/lean_verify.py`; grep of `server/` + `ingest/` for `lean`/`proof_state`/`tactic` finds zero production code. Parked at `.claude/roadmap/E14-observability-ops.md` E14_S06 as Tier-7/v2, un-park trigger: "a dedicated v2 design document exists."

**Sketch:** New `server/handlers/lean_verify.py`. Spawn `lake exe repl` via `asyncio.create_subprocess_exec` (pure-ASGI rule: must not block the event loop). Write one JSON command, read one JSON response, map `messages` + `sorries` (proof-state + errors) into the MCP envelope. Gate behind `ARXMCP_ENABLE_LEAN=false` by default (mirrors the `ARXMCP_ENABLE_RERANK` pattern) so the server starts cleanly without a Lean toolchain. Lean is a system dependency, not a pip dep — guard with a `requires_lean_repl` pytest marker and return a graceful error when the binary is absent. Register in `server/tools.py::ALL_TOOLS`; re-pin `EXPECTED_TOOL_SCHEMA_SHA256` (`CLAUDE.md §9`). Result schema (from APOLLO/FormL4): `{status, messages:[{severity,position,text}], proof_state, goals_remaining, sorry_goals, compilation_success}`.

**Open questions:**
- Subprocess-per-call (clean, ~1–5 s elaboration cost) vs a session-scoped warm REPL pool keyed on `Mcp-Session-Id` (efficient, stateful, more surface). The warm pool pairs with CAND-12.
- Use raw `leanprover-community/repl` JSON or the LeanDojo Python API as the backend? LeanDojo would cut handler LOC ~2× but adds a heavy dependency (Lean 4 + lake + a mathlib build). The no-fork policy permits a *library import* — but confirm with the owner; a thin native wrapper of the REPL protocol is the more local-first-aligned choice.
- Security: tactic input is arbitrary Lean code executed in a subprocess — needs the same sandbox discipline as the E13 LaTeXML sandbox (Threat-3 analogue).

---

### CAND-2 — Wire the `cite_neighbors` MCP handler to the live `graph_queries` library

**Category:** Citation graph
**Size:** S
**Evidence triangulation:** 4 briefs (comparative ✓, oss-trends ✓, multi-agent ✓, adversary ✓)

**What it is:** Replace the v1 stub body in `server/handlers/citations.py` (which returns `{neighbors: [], infrastructure_status: "deferred"}` for every call) with a real call to the already-shipped, already-tested `server/graph_queries.py::cite_neighbors` library, so agents can traverse the Kùzu citation graph through the MCP surface.

**Why it matters:** This is the single highest-leverage / lowest-risk item in the entire catalog. The library shipped in E09_S03 — async-safe, direction-filtered, deduped, 500 ms performance-gated, with passing tests in `tests/test_proof_chain.py`. Only the ~40-line MCP boundary is missing. It unblocks the entire proof-chain workflow (`.claude/docs/proof-chain-workflow.md`) — the fixer following a citation chain from a paper chunk to its cited lemmas. The adversary's verdict: a stub that has outlasted its justification through seven milestones.

**Sources:**
- Comparative scout: C3 (cite_neighbors completion + optional S2 remote fallback).
- OSS-trends scout: theme + 2.2 ("the citation-graph stub is a dependency problem, not a design problem").
- Multi-agent scout: C8 ("the highest-leverage / lowest-risk change in the entire candidate set").
- Adversary scout: H2 (HIGH — "wired to a dead stub seven milestones after the library shipped").

**Closest arXMCP analog (today):** `server/handlers/citations.py` IS the stub. `server/graph_queries.py` IS the real library. `CLAUDE.md §7` documents the deferral explicitly.

**Sketch:** In `server/handlers/citations.py`, call `await server.graph_queries.cite_neighbors(chunk_id, direction, depth, max_results=limit, kuzudb_path=..., lancedb_path=...)`, wrap results via `envelope(...)`, apply the existing `_cap(...)`. Honor the F2 path-validation contract (E09_S03 critique): derive `kuzudb_path`/`lancedb_path` from `get_resources()`/Config, **never** from agent-supplied JSON. Fix the direction-enum mismatch (adversary L2): handler advertises `citers/cited/co_cited/co_citing/depends_on`; library accepts `cites/cited_by/depends_on` — add a mapping layer or re-align the handler enum (the latter re-pins the schema hash). No schema change if the description string is unchanged.

**Open questions:**
- Re-align the handler's `direction` enum to the library's (drops `co_cited`/`co_citing`, which the library does not implement) — or keep them as future-reserved and 400 on unsupported values? The former re-pins `EXPECTED_TOOL_SCHEMA_SHA256`.
- Cache key for `cite_neighbors` results should include a `graph_version` string (analogous to `corpus_version`) so graph re-ingest invalidates stale entries.

---

### CAND-3 — Migrate Kùzu to the Vela-Engineering maintained fork

**Category:** Citation graph
**Size:** XS
**Evidence triangulation:** 2 briefs (oss-trends ✓, adversary ✓)

**What it is:** Re-pin the `kuzu` dependency from the archived `kuzu==0.11.3` (upstream archived 2025-10-10) to `Vela-Engineering/kuzu` — an actively maintained MIT-licensed fork (last commit 2026-05-19) that preserves the 0.11.3 API and Python bindings.

**Why it matters:** The citation graph (CAND-2's foundation) currently sits on an archived, unmaintained dependency. The fork is API-compatible, so `ingest/kuzudb_schema.py`, `ingest/graph_ingest.py`, and `server/graph_queries.py` should need no code changes — only the pin. De-risks every citation-graph candidate.

**Sources:**
- OSS-trends scout: 2.2 (Vela-Engineering/kuzu, MIT, 32★, 2026-05-19; Kineviz/bighorn as a weaker fallback).
- Adversary scout: L3 (LOW — "Kùzu archived; no migration path documented beyond a pointer").

**Closest arXMCP analog (today):** `pyproject.toml` pin `kuzu==0.11.3`; `CLAUDE.md §8 point 2` tracks the fork question as "out of scope."

**Sketch:** Change the `pyproject.toml` pin. Run the full suite, especially the synthetic Kùzu fixtures in `tests/_graph_helpers.py`, in a test branch before cutover. If the fork is not on PyPI under the `kuzu` name, a `git+https://` pin is needogged against the no-fork policy — note: the no-fork policy forbids *lifting code*, not *depending on a maintained library*; a dependency pin is fine, but a `git+` pin adds supply-chain surface (E13 Threat-6) so prefer a PyPI release if one exists.

**Open questions:**
- Is the Vela fork published to PyPI, or only installable via `git+https://`? A `git+` pin is a supply-chain consideration.
- The fork's headline change is concurrent multi-writer support — arXMCP's graph is append-only at ingest, read-only at query, so this is continuity value, not feature value. Confirm no single-writer assumptions were broken.

---

### CAND-4 — Add syntax-check and incremental-checkpoint modes to `lean_verify`

**Category:** Verification / proof tooling
**Size:** S
**Evidence triangulation:** 2 briefs (research-frontier ✓, multi-agent ✓)

**What it is:** Two cheaper sub-modes on the CAND-1 tool: (a) a `syntax_only` mode that elaborates a sketch and reports syntactic errors without full kernel verification (DSP+'s per-rule error masking); (b) an `incremental` mode that submits one tactic against a held proof-state ID and returns the resulting goal state (HERMES checkpoints, the REPL's tactic-mode).

**Why it matters:** The autoformalizer wants to self-correct a sketch's syntax *before* the tactician spends a full verification cycle on it; the tactician wants per-tactic checkpoints rather than whole-proof batch verification. Both are loop-style choices the consumer agent should be able to make.

**Sources:**
- Research-frontier scout: 2.7 (HERMES interleaved informal/formal with intermediate Lean checkpoints).
- Multi-agent scout: C2 (DSP+ sketch-validation step — "masks syntactic errors before the prover sees them").

**Closest arXMCP analog (today):** None — depends entirely on CAND-1.

**Sketch:** A `mode: Literal["full","syntax_only","incremental"]` parameter on the `lean_verify` tool. `syntax_only` short-circuits after elaboration; `incremental` accepts a `proof_state_id` + a single tactic and uses the REPL's tactic mode. Cache keys must include `lean_toolchain_version`.

**Open questions:**
- Build this into CAND-1's v1 schema, or ship CAND-1 with `mode="full"` only and add modes later (a second schema-hash re-pin)? Folding it in from the start is cheaper.

---

### CAND-5 — Mathlib premise/declaration search tool (`search_mathlib`)

**Category:** Retrieval quality
**Size:** M
**Evidence triangulation:** 4 briefs (comparative ✓, research-frontier ✓, multi-agent ✓, adversary ✓)

**What it is:** A new MCP tool that retrieves Lean 4 Mathlib declarations (theorem/lemma/definition names + statements + docstrings) by natural-language query, type-pattern, or proof-goal. Backed by a pre-built offline index over `mathlib4` declaration metadata — no running Lean process required for the search itself.

**Why it matters:** The tactician/autoformalizer need *formal-library* grounding, not only *informal arXiv* grounding. Today `find_lemma_by_name` searches only the arXiv corpus; the tactician must guess Mathlib lemma names and suffer repeated `sorry`/compile-error cycles. Every frontier prover (LeanDojo/ReProver, LeanSearch v2, DeepSeek-Prover) treats Mathlib premise retrieval as load-bearing.

**Sources:**
- Comparative scout: C4 (Loogle-style type-directed / subexpression-pattern Lean declaration search).
- Research-frontier scout: 2.2 (LeanSearch v2 — hierarchy-informalized Mathlib corpus, embedding-reranker, nDCG@10 0.62; arXiv:2605.13137).
- Multi-agent scout: C3 + C6 (LeanDojo/ReProver premise-selection; `get_mathlib_premise`).
- Adversary scout: M2 (MEDIUM — "no Mathlib-to-arXiv alignment tool; tactician has no formal-library grounding").

**Closest arXMCP analog (today):** `find_lemma_by_name` (FTS5 + Jaccard over the *arXiv* corpus, `E10_S02`) — does not cross-reference Mathlib. No Mathlib ingest path. Parked at E14_S06 Tier-7.

**Sketch:** One-time offline indexer extracts declaration metadata from `mathlib4` source into a static artifact (SQLite or a LanceDB table) bundled alongside the corpus, mirroring the definitions index (E10_S01). Reuse the existing BGE-M3 embedder + LanceDB ANN for a semantic mode; optionally add a Loogle-style type-pattern mode. New `server/handlers/search_mathlib.py`; schema re-pin. The LeanSearch v2 "hierarchy-informalized" preprocessing (formal declaration → NL-aligned prose before embedding) is the corpus-construction pattern to lift as an idea.

**Open questions:**
- Mathlib is a *parallel corpus* — does arXMCP's scope expand to host it, or is `search_mathlib` a separate concern? (Scope-expansion tension — see §4.)
- Type-directed pattern search (Loogle) needs a real Lean elaborator; the semantic mode does not. v1 could be semantic-only.

---

### CAND-6 — Proof-state-conditioned retrieval (`search_by_proof_state`)

**Category:** Retrieval quality
**Size:** M
**Evidence triangulation:** 3 briefs (comparative ✓, research-frontier ✓, multi-agent ✓)

**What it is:** A retrieval mode (new tool or a `mode=` on `search_papers`) that takes a serialized Lean proof goal (`⊢` expression + hypotheses) as the query, rather than a natural-language string, and retrieves chunks whose theorem statements match it.

**Why it matters:** ReProver's core insight — retrieval conditioned on the *current proof state*, not the original NL query. Once CAND-1 exists, the tactician has a live goal at every step; feeding it straight into retrieval is a zero-turn precision win over translating the goal to English first.

**Sources:**
- Comparative scout: C5 (ReProver premise-selection pattern; goal `pp` string as the query).
- Research-frontier scout: theme §4 + 2.8 (ReProver retrieval conditioned on proof state).
- Multi-agent scout: C6 (`search_by_proof_state(goal, hypotheses)`).

**Closest arXMCP analog (today):** `search_papers` (`server/handlers/search.py`) takes NL queries. `ingest/tokenizer.py` (math-aware BM25 tokenizer) is untested on Lean 4 term syntax.

**Sketch:** New route tag in `server/router.py`; query preprocessing normalizes Lean goal syntax (whitespace, anonymous-variable renaming `α✝`→`α`). Reuses the `embedding_stmt` ANN path. Add a Lean-goal test fixture for the BM25 tokenizer.

**Open questions:**
- Does the BM25 tokenizer reject Lean 4 term syntax as out-of-vocabulary? Needs a regression fixture.
- Strongly coupled to CAND-1 (the proof state comes from `lean_verify`). Low standalone value before CAND-1.

---

### CAND-7 — Complete the dual-column proof-chunk RRF (index `embedding_proof` in the ANN path)

**Category:** Retrieval quality
**Size:** S
**Evidence triangulation:** 1 brief (adversary ✓) — weak, but a documented incomplete feature

**What it is:** Extend `handle_search_papers` to issue a second ANN query over the `embedding_proof` column and fuse it (via the existing `server/retrieval/rrf.py`) with the statement-ANN and BM25 result sets — completing the dual-column hybrid retrieval E07 was designed for.

**Why it matters:** The tactician's primary retrieval need is *how a similar lemma was proved*, not just that its statement exists. The `SEARCH_PAPERS` tool description itself warns "v1 indexes statement chunks only — proof chunks are not retrievable until E07's dual-column RRF lands." The `embedding_proof` column is already populated; only the retrieval handler doesn't query it.

**Sources:**
- Adversary scout: M3 (MEDIUM — "`search_papers` BM25 path does not run over proof chunks; dual-column RRF incomplete").

**Closest arXMCP analog (today):** `server/handlers/search.py` ANN call queries `embedding_stmt` only; `server/retrieval/rrf.py` exists and was designed for this fusion; `embedding_proof` is populated (E03_S01).

**Sketch:** Add a second ANN query over `embedding_proof` (same query vector, over-fetch k×3), pass both result sets + BM25 through `rrf.py`. The `level` parameter already deduplicates at the paper level. Update the tool description (schema-hash re-pin).

**Open questions:**
- `E07_S04` is marked SHIPPED in the roadmap but the tool description contradicts it — confirm whether dual-column was descoped deliberately or dropped.
- Doubling the ANN over-fetch raises memory pressure — measure against the eval harness.

---

### CAND-8 — `get_paper` metadata table (authors / title / abstract / year / categories)

**Category:** Ingestion / parsing
**Size:** M
**Evidence triangulation:** 2 briefs (comparative ✓, adversary ✓)

**What it is:** Populate a real paper-metadata store (a Kùzu `papers` table or a SQLite sidecar) at ingest time so `get_paper` returns actual authors/title/abstract/year/categories instead of `null`.

**Why it matters:** `get_paper` today returns null for every content metadata field (`CLAUDE.md §7`). The fixer uses `get_paper` to build citation context; null metadata is not actionable and forces extra search queries against the 3-round MCP budget. This becomes acutely necessary once CAND-2 lands — agents will call `get_paper` on every citation neighbor.

**Sources:**
- Comparative scout: C6 (TLDR snippet field — metadata enrichment, adjacent).
- Adversary scout: H3 (HIGH — "`get_paper` returns null metadata fields").

**Closest arXMCP analog (today):** `server/handlers/paper.py` synthesizes only ingest-process metadata (chunk_count, chunker_version). `ingest/kuzudb_schema.py` stores only `paper_id` + `cites` edges.

**Sketch:** OpenAlex (`ingest/graph_ingest.py`) and INSPIRE-HEP (`ingest/inspire_ingest.py`) already fetch title/authors/year/abstract — capture them into a `papers` table during the existing enrichment pass. The OAI-PMH delta loop (E11_S02) carries the same fields and can backfill. `get_paper` reads from the table. Optionally add a `tldr` field (comparative C6 — from S2's TLDR endpoint, an outbound call; see §4 local-first tension).

**Open questions:**
- Kùzu `papers` table vs SQLite sidecar vs LanceDB columns (the last needs a re-embed)? The Kùzu table is lightest.
- Tool description references "null until a real papers table lands" — updating it re-pins the schema hash.

---

### CAND-9 — Citation-graph re-ranking via a GNN over Kùzu edges

**Category:** Retrieval quality
**Size:** L
**Evidence triangulation:** 1 brief (research-frontier ✓) — weak

**What it is:** A graph-neural-network re-ranking sub-phase that propagates structural signal from the Kùzu citation/dependency graph (premise-premise and state-premise edges) to promote structurally-proximate chunks the embedding similarity alone would miss.

**Why it matters:** Petrovčič et al. (arXiv:2510.23637) report >25% premise-recall improvement over ReProver by blending text embeddings with a GNN over the dependency graph. arXMCP already *has* the edge data (`server/graph_queries.py` `cites`/`depends_on`) — it just isn't fed into ranking.

**Sources:**
- Research-frontier scout: 2.3 (Graph-Augmented Premise Selection, arXiv:2510.23637).

**Closest arXMCP analog (today):** `server/retrieval/rerank.py` (BGE cross-encoder Phase-3 reranker) — no graph signal. Kùzu edges exist but are unused for ranking.

**Sketch:** A GNN re-ranking sub-phase in `server/retrieval/` that queries Kùzu for the structural neighborhood of ANN candidates and blends GNN scores with the BGE-reranker score. Needs PyTorch Geometric or DGL, and a one-time GNN training job. No confirmed OSS reference impl.

**Open questions:**
- Heavy: ~500–800 LOC + a GNN training pipeline + a new ML dependency. Is the +25% worth an L-sized effort at a 50-paper seed corpus where the graph is tiny?
- Depends on CAND-2/CAND-3 (a healthy citation graph) being solid first.

---

### CAND-10 — Migrate BM25 to LanceDB's native FTS tokenizer (retire the rank-bm25 pickle)

**Category:** Ingestion / parsing
**Size:** M
**Evidence triangulation:** 1 brief (oss-trends ✓) — weak

**What it is:** Replace `ingest/bm25_indexer.py`'s separate `rank-bm25` pickle artifact with LanceDB's native model-backed FTS index, plugging arXMCP's math-aware regex tokenizer (`ingest/tokenizer.py`) in as a custom tokenizer.

**Why it matters:** Eliminates the most operationally fragile part of the pipeline — a pickle index decoupled from LanceDB's MVCC lifecycle — and unblocks scalar-filter pushdown in hybrid search (BM25 + ANN + filter in one query plan).

**Sources:**
- OSS-trends scout: 2.4 (LanceDB native model-backed FTS tokenizers, v0.32.0+).

**Closest arXMCP analog (today):** `ingest/bm25_indexer.py` (per-corpus-version pickle); `server/retrieval/bm25.py` (loads the pickle).

**Sketch:** Migrate to `lancedb.Table.create_fts_index(tokenizer=...)`; update `server/retrieval/bm25.py` to query via `table.search(...).where(...)`. Retire the pickle path.

**Open questions:**
- The native FTS tokenizer API is in LanceDB's Python *beta* channel (v0.33.x) — a careful version bump + regression test is needed before a production pin. Pure infrastructure work with no agent-facing capability gain; lower urgency than the verification/citation candidates.

---

### CAND-11 — `retrieval_confidence` sufficiency signal in the result payload

**Category:** MCP tool surface
**Size:** S
**Evidence triangulation:** 1 brief (multi-agent ✓) — weak

**What it is:** Add a calibrated `retrieval_confidence: float` field (0.0–1.0) to each search result, distinct from the existing ranking `score` — signalling how well the chunk actually answers the query, so the agent can decide whether to re-query.

**Why it matters:** Self-RAG's insight, adapted to a no-LLM-at-runtime server: the server returns a *sufficiency* signal; a pre-existing LLM agent uses it to decide whether to re-retrieve. Reduces wasted MCP-budget round-trips.

**Sources:**
- Multi-agent scout: C7 (Self-RAG adaptive retrieval, output-side signal only).

**Closest arXMCP analog (today):** Search results carry a ranking `score`; no contextual-sufficiency field.

**Sketch:** In `server/handlers/search.py`, derive `retrieval_confidence` from the normalized BGE-reranker score relative to a calibrated threshold. Additive field; re-pin `EXPECTED_TOOL_SCHEMA_SHA256`; update `.claude/docs/snippet-contract.md`.

**Open questions:**
- Calibrating the threshold needs the eval fixture (CAND-14) curated first, or it is an uncalibrated guess.

---

### CAND-12 — MCP progress notifications for long-running tools

**Category:** MCP tool surface
**Size:** S
**Evidence triangulation:** 2 briefs (comparative ✓, oss-trends ✓)

**What it is:** Thread the MCP context through tool handlers and emit `report_progress()` notifications during long-running calls — primarily `lean_verify` (5–30 s elaboration) and deep `cite_neighbors` traversals.

**Why it matters:** Without progress notifications a 5–30 s Lean call looks like a hang; the calling agent stalls or times out. The MCP Python SDK arXMCP already depends on supports this today.

**Sources:**
- Comparative scout: C8 (`ctx.report_progress`).
- OSS-trends scout: 2.5 (MCP Python SDK progress notifications + structured tool output).

**Closest arXMCP analog (today):** Handlers (`server/handlers/*.py`) are context-free `async def` functions; `server/tools.py` registration passes no `ctx`.

**Sketch:** Add `ctx: Context` to handler signatures and the `server/tools.py` registration wiring; emit progress in `lean_verify`. Within the existing `mcp>=1.27,<2` pin. Pairs naturally with CAND-1.

**Open questions:**
- Touching every handler signature is a structural refactor — sequence it with CAND-1 rather than as a standalone change.
- Benefit is zero if the calling client ignores `notifications/progress`.

---

### CAND-13 — Paper version-awareness + version-diff tool

**Category:** Ingestion / parsing
**Size:** M
**Evidence triangulation:** 2 briefs (comparative ✓, adversary ✓)

**What it is:** Record the arXiv version (`v1`/`v2`/`v3`) on each chunk and add a `get_paper_versions` tool so the fixer can see which version it retrieved and request another.

**Why it matters:** `.claude/notes/01-mission-and-context.md` names this explicitly as a fixer need — "v1 often has the cleaner statement, v3 the corrected proof." Today the OAI-PMH delta loop *overwrites* the old version on re-ingest; both are never retained.

**Sources:**
- Comparative scout: C7 (arXiv version-pinned IDs, `/e-print/{id}vN`).
- Adversary scout: M4 (MEDIUM — "no paper version-diff tool").

**Closest arXMCP analog (today):** `ingest/schema.py` has no `arxiv_version` column; `tools/arxiv_fetch.py` fetches e-print LaTeX without recording the version.

**Sketch:** Add an `arxiv_version` column (`ingest/schema.py`) populated from the download URL; new `get_paper_versions` tool. Chunk-level v1-vs-v3 structural diff is the harder, optional second step. Schema column add implies a partial re-embed (E11_S03 strategy covers it); new tool re-pins the schema hash.

**Open questions:**
- Retaining multiple versions of the same paper roughly doubles per-paper storage — acceptable at corpus scale?
- The structural diff (not just version listing) is materially harder; v1 could be version-listing only.

---

### CAND-14 — Curate the 20-query eval fixture

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 2 briefs (adversary ✓, research-frontier ✓)

**What it is:** Hand-label the 20-query eval fixture (`tests/eval/fixtures/queries.json`) against the 50-paper math.AG seed corpus, so `make eval` and the nDCG@5 gate can actually fire.

**Why it matters:** The eval harness shipped in E05 but the fixture is an empty stub — the Tier-0→Tier-1 quality gate is "ceremonially open." Any retrieval change (CAND-6, CAND-7, CAND-9, CAND-10, CAND-15) can ship today with **no measurable regression evidence**. This candidate is a prerequisite for credibly evaluating half the catalog.

**Sources:**
- Adversary scout: M1 (MEDIUM — "eval harness has no curated queries; nDCG@5 gate cannot fire").
- Research-frontier scout: 2.9 (FoVer — using formal-verifier verdicts as ground-truth labels).

**Closest arXMCP analog (today):** `tests/eval/` harness exists; `tests/eval/fixtures/queries.json` is an empty stub; `.claude/docs/eval-curation.md` is the runbook.

**Sketch:** Execute the curation runbook — 20 queries, each with ≥1 relevant `chunk_id`. Pure execution, not design. FoVer suggests formal-verifier verdicts could partially automate label generation, but hand-labeling 20 against a 50-paper corpus is tractable directly.

**Open questions:**
- Requires math-domain judgement — best done by the project owner or with owner review, not fully autonomously.

---

### CAND-15 — Dual-resolution / Matryoshka embeddings for the Tier-1 cache

**Category:** Retrieval quality
**Size:** L
**Evidence triangulation:** 2 briefs (research-frontier ✓, oss-trends ✓)

**What it is:** Emit a short-dimension (e.g. 256-d) embedding alongside the full 1024-d BGE-M3 vector so the Tier-1/Tier-2 cache can do fast approximate matching on short vectors while final ANN uses full vectors.

**Why it matters:** Shrinks the Tier-2 FAISS cache ~4× and cuts cache-lookup latency, with minimal recall loss — a natural fit for arXMCP's 3-tier cache design.

**Sources:**
- Research-frontier scout: 2.6 (2D Matryoshka representation learning, arXiv:2411.17299).
- OSS-trends scout: 2.9 (Sentence-Transformers v5 Matryoshka support).

**Closest arXMCP analog (today):** `ingest/embedder.py` emits single-resolution 1024-d BGE-M3; `server/cache.py` Tier-2 FAISS uses full vectors.

**Sketch:** BGE-M3 supports MRL truncation via FlagEmbedding; emit `embedding_short` (`ingest/schema.py` column) + use it for Tier-1 cache lookup. A *full* 2D-MRL benefit needs a model fine-tune (the L cost).

**Open questions:**
- Standard MRL truncation is cheap; the 2D (layer+dim) variant needs a fine-tune. v1 could be truncation-only (smaller).
- A new `embedding_short` column implies a full re-embed of the corpus.

---

## 4. Cross-cutting tensions

1. **Roadmap deferral vs SOTA convergence (CAND-1, CAND-5).** The roadmap parks Lean integration *and* Mathlib lookup at Tier-7/v2 (`E14_S06`), un-park trigger "a dedicated v2 design document exists." Every one of the five scouts independently rates Lean verification feedback as the #1 capability *now*. The deferral is principled (it is a real v2-scope decision, not neglect) — but the 2026 SOTA has fully converged on the Lean kernel as the universal oracle, and the adversary's framing is sharp: "the more milestones ship without Lean integration, the more the design looks like a retrieval server without a consumer." Phase 4 must decide whether CAND-1 *is* the v2 design-document trigger.

2. **"Lean kernel is the better critic" — apparent contradiction, actually alignment.** arXMCP's constitution says invest *upstream* of verification and avoid an LLM critic. CAND-1 adds a *verification* surface — but it is a thin wrapper around the Lean *kernel*, not an LLM critic. `.claude/notes/01-mission-and-context.md` explicitly blesses exactly this ("if we add a 'critic' tool, it's a thin wrapper around Lean kernel output"). So CAND-1 *honors* the philosophy rather than violating it. Worth stating plainly so the challenger doesn't mis-flag it.

3. **Local-first vs remote enrichment.** Semantic Scholar / SPECTER2 / S2-TLDR (comparative C2/C3/C6) and the arXiv API offer high-value enrichment requiring outbound calls — a tension with arXMCP's offline-capable, local-first principle. The resolution comparable systems use (Context7, blazickjp): a hybrid model — local-corpus-first, remote-enrichment behind an env-var flag, `source: "remote"` marked in the envelope. This catalog keeps the S2-remote pieces *folded into* CAND-2 (optional fallback) and CAND-8 (optional TLDR), not as standalone candidates, precisely because the local-first tension caps their priority.

4. **Scope expansion: Mathlib as a parallel corpus (CAND-5).** arXMCP is an *arXiv-corpus* server. CAND-5 introduces a second, structurally different corpus (Lean 4 declarations vs LaTeX theorem chunks). The agent-facing tool surface unifies them, but ingestion, schema, and storage diverge. Phase 4 should weigh whether this is in arXMCP's mission or a sibling project.

5. **The eval fixture is a prerequisite, not a peer (CAND-14).** Five candidates (CAND-6, 7, 9, 10, 15) change retrieval behavior; none can be credibly evaluated until CAND-14 curates the fixture. CAND-14 is small but *sequencing-critical* — it gates the evidence base for half the catalog.

## 5. What's already in flight

- **`E14_S06`** (`.claude/roadmap/E14-observability-ops.md`) parks both Lean toolchain integration (→ CAND-1) and Mathlib lookup (→ CAND-5) as Tier-7/v2 deferrals. These candidates are not new ideas — they are the roadmap's own parked items, and CAND-1 is a strong candidate to *be* the "v2 design document" that un-parks them.
- The adversary notes seven recent `proof-verify-handler-wiring` milestones (m1–m7) ran concurrently and wired `search_papers` filters + notebook UI — they did **not** touch CAND-2/CAND-8/CAND-14, so there is no overlap to re-litigate, but it confirms the "stub persistence" pattern.
- `E07_S04` is marked SHIPPED yet the `search_papers` description still says dual-column RRF is pending (→ CAND-7) — a roadmap/code inconsistency Phase 4 should flag.

## 6. Parking lot

- **SYSTEM_PROMPT authoring** (adversary L1) — real gap, but server `prompts.py` system-prompt content is an orchestrator-author decision, upstream of arXMCP's server-capability scope. Track as a doc task, not a scout candidate.
- **ICL query embeddings / bge-en-icl** (oss-trends 2.7) — a 7B+ model; ~10–30× CPU-inference latency on a workstation without GPU. Future model-swap concern, not near-term.
- **Iterative-widening HNSW scan** (oss-trends 2.8, pgvector pattern) — a micro-optimization of the existing ANN over-fetch; real but low-value relative to the catalog, and only matters under heavy scalar filtering.
- **`batch_search` / CodeAct pattern** (multi-agent C10) — the benefit (fewer round-trips) accrues to the agent, not the server; an MCP tool addition with marginal server-side value. Revisit if MCP-budget pressure becomes measured.
- **ReAct / Reflexion compatibility** (multi-agent C9) — surfaced as a *no-change validation*: arXMCP's deterministic results + BP1/BP2 caching + `id_canon.py` already satisfy these patterns. Not a candidate; a confirmation.
- **`has_lean_proof` filter, MSC-classification filter** (multi-agent C4, comparative C10) — both depend on `search_papers`'s `filters` argument (currently accepted-but-ignored) and on data that doesn't exist yet (verified-proof tracking; parsed MSC codes). Fold into a future "search filters" milestone once CAND-8's metadata work establishes the pattern.
- **AlphaProof MCTS / multi-agent debate / Process Reward Models** (multi-agent parking lot) — all require an LLM (and often a value model) at runtime, violating the no-`anthropic`-SDK-at-runtime architecture lock, and the LLM-critic ones contradict the "Lean kernel is the better critic" philosophy. Correctly rejected by the scouts; already in `.claude/notes/10-references-and-prior-art.md` as context.
- **S2 remote enrichment as a standalone capability** — not parked so much as *folded*: it lives inside CAND-2 (citation fallback) and CAND-8 (TLDR), gated by the local-first tension (§4.3).
