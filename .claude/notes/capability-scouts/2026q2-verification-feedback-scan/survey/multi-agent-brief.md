# Multi-Agent Brief — 2026 Q2 Verification-Feedback Scan

**Scout:** multi-agent (capability-scout 2026q2-verification-feedback-scan)
**Date:** 2026-05-22
**Scope:** Multi-agent architectures for mathematics — autoformalization pipelines, retrieval-augmented theorem proving, proof-search agents, agent-harness primitives, and MCP-as-harness-component patterns. Focus on execution-based verification feedback and the `cite_neighbors` tool gap.

---

## 1. TL;DR

The three highest-leverage multi-agent capabilities arXMCP should consider are: **(1)** a Lean kernel verification-trace MCP tool (returning compile/typecheck/proof-state output) so the tactician → fixer loop gets real execution feedback rather than only retrieved grounding context; **(2)** wiring the `cite_neighbors` handler in `server/handlers/citations.py` to the real `server/graph_queries.py` library, enabling proof-chain traversal that every autoformalization pipeline (DSP, DeepSeek-Prover-V2, Goedel-Prover) treats as load-bearing; and **(3)** an adaptive-retrieval (Self-RAG-style) signal that lets agents request retrieval only when the current proof state underspecifies the next tactic, preventing context bloat. The main architectural gap is that arXMCP pre-loads grounding context and retrieves math chunks well, but exposes **no execution-feedback surface** — the tactician and fixer agents receive no Lean kernel output through the MCP tool layer, forcing them to act blind after every tactic attempt.

---

## 2. Multi-Agent Candidates

### Candidate 1 — Draft, Sketch, and Prove (DSP)

**Name + citation:** "Draft, Sketch, and Prove: Guiding Formal Theorem Provers with Informal Proofs." Jiang et al. arXiv:2210.12283. ICLR 2023.

**Year + venue:** 2022/2023 — ICLR 2023.

**What it does:** DSP decomposes autoformalization into three sequential LLM-roles: (1) a *Drafter* produces a natural-language informal proof outline (human or LLM-generated); (2) a *Sketcher* translates the outline into a formal Lean/Isabelle proof sketch — a valid-structure skeleton with `sorry` placeholders mirroring each informal step; (3) an automated *Prover* (e.g. a tactic-search engine) fills each `sorry` independently. The informal proof constrains the prover's search space by providing sub-lemma structure. This improved miniF2F pass rates from ~21% to ~39%. DSP is the direct ancestor of DeepSeek-Prover-V2 and Goedel-Prover's architecture; it is the canonical template the arXMCP consumer pipeline imitates.

**What's NEW vs arXMCP today:** arXMCP's pipeline shape (sketcher → autoformalizer → tactician → fixer, CLAUDE.md §2) is explicitly modeled on DSP. What arXMCP does **not** expose that DSP's architecture demands: (a) a way for the Prover stage to report which `sorry` subgoals succeeded or failed back to the calling agent, and (b) structured premise retrieval at the tactic level (DSP relies on an automated prover that has its own library access; arXMCP's retrieval is upstream of verification, not interleaved with tactic search). The concrete delta: arXMCP should expose a `verify_lean_snippet` tool that returns per-subgoal Lean kernel output (compile errors, proof-state after each tactic, remaining goals) so the tactician and fixer receive the same signal DSP's automated prover uses internally.

**Architectural fit:** New MCP tool — `verify_lean_snippet(code: str, context_imports: list[str]) -> VerificationTrace`. The handler would invoke a local Lean 4 subprocess (via `elan`/`lake` or a compiled Lean binary) and parse stdout/stderr into structured JSON. This is a **net-new tool** with no existing handler; it would live at `server/handlers/lean_verify.py`. No changes to existing tools.

**Cache interaction:** A verification-trace tool call is non-deterministic with respect to the MCP prompt cache if the Lean snippet argument varies between agents. This is expected: it should NOT be cached at BP1/BP2 (those cache the fixed system prompt + tool definitions block). The tool result itself could hit the **Tier-1 exact-query cache** in `server/cache.py` if the same snippet is submitted multiple times (e.g. fixer retry of an unchanged block). Key: `sha256(snippet + context_imports_sorted + lean_version)`. No interaction with BP1/BP2 byte-stability — tool meta descriptions stay frozen (`.claude/notes/07-multi-agent-caching.md` BP1 discipline requires tool *schemas* to be byte-stable, not tool *results*).

**Maturity signal:** Code available (arXiv supplementary + GitHub); subsequent work (DSP+, 2025, arXiv:2506.11487) revives and extends the approach using reasoning models without additional training. High signal — referenced by every major downstream prover paper.

---

### Candidate 2 — DSP+ (Reviving DSP with Reasoning Models)

**Name + citation:** "Reviving DSP for Advanced Theorem Proving in the Era of Reasoning Models." Cao et al. arXiv:2506.11487. 2025.

**Year + venue:** 2025 — arXiv preprint (cs.AI), June 2025.

**What it does:** DSP+ shows that *no additional training* is needed if you orchestrate off-the-shelf reasoning models carefully. Key innovations over DSP: (1) fine-grained neuro-symbolic error correction — sketch lines containing Lean syntactic errors are *masked per predefined rules* before being passed to the prover, rather than propagating bad structure; (2) symbolic search (Aesop) is tightly integrated with step provers at the Prove phase; (3) reasoning model outputs (thinking tokens, proof references) are stripped before the Sketch stage. Result: 80.7% miniF2F, 32.8% ProofNet, 24 PutnamBench problems — competitive with RL-trained systems. This is the closest current architecture to what arXMCP's downstream pipeline would implement.

**What's NEW vs arXMCP today:** DSP+ has an explicit *sketch-validation step* that filters syntactic errors before the prover sees them. arXMCP has no equivalent — it returns retrieved context but cannot validate Lean syntax inline. Concrete delta: a lightweight `syntax_check_lean(sketch: str) -> SyntaxCheckResult` tool (distinct from full kernel verification) would let the Autoformalizer self-correct sketches before passing to the Tactician. This is cheaper than full verification and could be a sidecar to the `verify_lean_snippet` tool.

**Architectural fit:** Either a second thin MCP tool (`syntax_check_lean`) or a `mode` parameter on `verify_lean_snippet`. Net-new capability block at `server/handlers/lean_verify.py` if combined with Candidate 1.

**Cache interaction:** Same as Candidate 1 — tool *result* is snippet-dependent, not cacheable at BP1/BP2. The syntax check result for a given sketch string is deterministic given the same Lean toolchain version; cache key should include `lean_toolchain_version` to invalidate correctly on toolchain upgrades. Consistent with `.claude/notes/07-multi-agent-caching.md` Tier-1 exact-query discipline.

**Maturity signal:** Code not yet released at submission time (June 2025 preprint). Benchmark results are strong but reproducibility is unconfirmed. Medium signal — watch for GitHub release.

---

### Candidate 3 — LeanDojo / ReProver

**Name + citation:** "LeanDojo: Theorem Proving with Retrieval-Augmented Language Models." Yang et al. arXiv:2306.15626. NeurIPS 2023 (oral, Datasets & Benchmarks track). Code: `https://github.com/lean-dojo/LeanDojo` (MIT license).

**Year + venue:** 2023 — NeurIPS 2023.

**What it does:** LeanDojo is the dominant infrastructure layer for LLM × Lean interaction. It exposes: (1) **proof state extraction** from any Lean 4 repo — the current goal, hypotheses, and available premises at each tactic step; (2) **programmatic tactic execution** — submit a tactic string, receive the resulting proof state or error; (3) **premise selection benchmark** — 98,734 Lean 4 theorems with fine-grained annotations of which premises were used, enabling retrieval model training. ReProver (the companion model) uses a ByT5 encoder to embed proof states → retrieve relevant Mathlib lemmas → feed retrieved premises + current proof state into a tactic generator. The retrieve → verify loop runs tactic-by-tactic.

**What's NEW vs arXMCP today:** arXMCP retrieves chunks from an arXiv corpus (research papers, not a formal library); LeanDojo retrieves from Mathlib (the verified formal library). These are complementary, not competing. The concrete delta: arXMCP could add a `get_mathlib_premise(query: str) -> list[MathlibEntry]` tool backed by a local LeanDojo-style index of Mathlib docstrings and theorem statements. This gives the Tactician formal-library lookup alongside informal arXiv context. Additionally, LeanDojo's `LeanDojo.interact()` Python API is the canonical interface for the `verify_lean_snippet` tool (Candidate 1) — it handles subprocess lifecycle, proof-state parsing, and tactic error reporting.

**Architectural fit:** Two components: (a) a Mathlib premise index (new ingest path, new `get_mathlib_premise` MCP tool at `server/handlers/mathlib.py`); (b) use LeanDojo as the subprocess backend for `verify_lean_snippet` rather than raw `lean --stdin`. The LeanDojo Python package (PyPI) is MIT-licensed and could be imported under the no-fork policy (it is a library import, not a fork). The no-fork policy in CLAUDE.md §8 reads "Nothing lifted from existing `arxiv-mcp` repos" — LeanDojo is not an arxiv-mcp repo; it is a proof-assistant interaction library. Confirm with project owner before importing.

**Cache interaction:** LeanDojo's `interact()` call is stateful per proof session (it maintains a running Lean subprocess). The MCP request model is stateless per call. The handler must manage subprocess lifecycle carefully — either one subprocess per call (clean, expensive) or a session-scoped subprocess pool (efficient, but requires `Mcp-Session-Id` routing). The per-session retrieval caps in `server/session.py` already track `Mcp-Session-Id`; a subprocess pool keyed on the same header is the natural extension. This is **cache-adjacent** but does not touch BP1/BP2 prompt-cache bytes. The Tier-1 exact-query cache can cache verification results for a given `(snippet, lean_version, mathlib_version)` key.

**Maturity signal:** Code available, active maintenance, integrated into LeanProgress (TMLR 2025), used by ReProver, DSP, Goedel-Prover, and most academic prover papers as infrastructure. Very high signal.

---

### Candidate 4 — Goedel-Prover (Expert-Iteration Loop)

**Name + citation:** "Goedel-Prover: A Frontier Model for Open-Source Automated Theorem Proving." Lin et al. arXiv:2502.07640. 2025. Code: `https://github.com/Goedel-LM/Goedel-Prover` (MIT license).

**Year + venue:** 2025 — arXiv (cs.LG), February 2025.

**What it does:** Goedel-Prover operationalizes the expert-iteration loop for theorem proving: (1) convert informal math to Lean 4 formal statements at scale (800K+); (2) train a prover on those statements; (3) use the prover to prove previously unsolvable statements; (4) add newly-proven statements to the training set; (5) repeat. Each generation proves statements the previous could not. The feedback signal is the Lean kernel — a statement is added to training only if Lean verifies the proof. The loop achieves 57.6% miniF2F with SFT, 60%+ with DPO. Open weights + code + dataset.

**What's NEW vs arXMCP today:** The expert-iteration loop itself is a training technique, not an inference pattern — arXMCP does not train models, so this is not directly applicable. However, the Goedel-Prover codebase is the cleanest reference implementation for the *verify-then-store* pattern: every proof attempt that succeeds at Lean verification gets stored in a retrievable knowledge base. arXMCP's citation graph (`server/graph_queries.py`) could be extended with a *proof-success index*: chunk IDs whose corresponding Lean proofs have been verified by the kernel. The fixer could query "give me chunks whose proof was kernel-verified" (a new `direction` in `cite_neighbors` or a new `filter` on `search_papers`). This does not require arXMCP to run training; it requires tracking which arXiv chunks have associated verified Lean proofs.

**Architectural fit:** New filter parameter on `search_papers` (the `filters` argument is currently ignored, CLAUDE.md §7) — `filters={"has_lean_proof": true}`. The ingest pipeline would need a `has_lean_proof: bool` column in the LanceDB chunks table. This is a storage-layer extension, not a new tool. Medium effort, high value for the fixer role.

**Cache interaction:** A boolean filter on an existing search tool is fully compatible with existing BP1/BP2 discipline. The Tier-1 cache key already includes `filters_json` (`server/cache.py` Tier-1 key spec in `.claude/notes/07-multi-agent-caching.md`); the new filter would be a new key variant. No BP1/BP2 byte-stability impact.

**Maturity signal:** Code available, open weights, active citation in 2025 literature. High signal.

---

### Candidate 5 — DeepSeek-Prover-V2 (Subgoal Decomposition + RL)

**Name + citation:** "DeepSeek-Prover-V2: Advancing Formal Mathematical Reasoning via Reinforcement Learning for Subgoal Decomposition." Ren et al. arXiv:2504.21801. 2025. Code: `https://github.com/deepseek-ai/DeepSeek-Prover-V2`.

**Year + venue:** 2025 — arXiv (cs.CL), April 2025.

**What it does:** DeepSeek-Prover-V2 extends DSP with RL. DeepSeek-V3 writes an informal proof with explicit Lean 4 `sorry` placeholders (the "sketch with subgoals" format). A prover model (671B or 7B) attempts each `sorry` independently. Successful fills are chained and fed back as RL training signal. The key insight: the *chain-of-subgoal structure* from the informal sketch is preserved in Lean 4 syntax, so the prover sees both the local subgoal and the surrounding context. Achieves 88.9% miniF2F, 49/658 PutnamBench. The 7B model is practical for local deployment.

**What's NEW vs arXMCP today:** DeepSeek-Prover-V2 operates in a closed loop where the LLM sees Lean output after each subgoal attempt. arXMCP exposes no such loop. Concrete delta: the fixer agent needs both (a) the Lean error for a failed `sorry` and (b) similar successful proofs of analogous subgoals. arXMCP can provide (b) via `search_papers` and `find_lemma_by_name`; it cannot provide (a) today. The `verify_lean_snippet` tool (Candidate 1) closes this gap directly. Additionally, DeepSeek-Prover-V2 uses a `sorry`-count metadata field ("how many subgoals remain") that a `get_chunk` tool extension could expose for math chunks that have been autoformalizer-processed.

**Architectural fit:** Primarily motivates Candidate 1 (`verify_lean_snippet`). The `sorry`-count metadata field is a future `get_chunk` extension (`include_subgoal_count` flag — deferred since `get_chunk`'s `include_referenced` + `include_equations` flags are already reserved stubs, CLAUDE.md §7).

**Cache interaction:** No new cache considerations beyond Candidate 1. The DeepSeek-Prover-V2 RL loop is a training concern, not an inference concern for arXMCP.

**Maturity signal:** Code available, open weights (7B and 671B), strong benchmarks. Very high signal. Already in `.claude/notes/10-references-and-prior-art.md` as a motivating system.

---

### Candidate 6 — ReProver / LeanDojo Retrieval (Premise Selection as MCP Tool)

**Name + citation:** "LeanDojo: Theorem Proving with Retrieval-Augmented Language Models" — see Candidate 3 for full citation. ReProver is the retrieval-augmented prover component. `https://github.com/lean-dojo/ReProver` (MIT license).

**Year + venue:** 2023 — NeurIPS 2023. ReProver repo continuously maintained through 2025.

**What it does:** ReProver implements the tactic-level retrieve-verify loop: given a proof state (current goal + hypotheses), retrieve the most relevant Mathlib premises using a ByT5 encoder, then generate a tactic using the concatenation `[retrieved premises] + [proof state]`. The retriever is trained with hard negatives from program analysis — premises that are *accessible* but *not used* in the actual proof. Best-first search over the tactic tree with Lean verification at each node. The loop is: retrieve → generate tactic → verify → update proof state → re-retrieve.

**What's NEW vs arXMCP today:** arXMCP retrieves from arXiv informal papers; ReProver retrieves from Mathlib formal library. These fill different context slots. The critical architectural delta: ReProver's retrieval is conditioned on the **current proof state** (Lean's `⊢` goal expression), not on the original query. arXMCP has no tool that accepts a proof state as input and retrieves relevant formal lemmas. A new `search_by_proof_state(goal: str, hypotheses: list[str]) -> list[ChunkResult]` tool would let the Tactician retrieve math chunks whose theorem statements syntactically or semantically match the current Lean goal. This is a specialization of `search_papers` with proof-state parsing.

**Architectural fit:** New tool `search_by_proof_state` or a new `mode` parameter on `search_papers`. The embedding path would reuse `embedding_stmt` columns (already indexed on theorem statements); the query would be the Lean `⊢` expression after normalization. This is a **context-engineering change** primarily in `server/handlers/search.py` plus a new route tag in `server/router.py`. The Lean goal expression may require tokenizer adjustments in `ingest/tokenizer.py` for BM25.

**Cache interaction:** The proof state is highly dynamic (changes after every tactic), so Tier-1 exact-query cache hit rates will be low. Tier-2 semantic cache (cosine > 0.97) may help for structurally similar goals. The tool result is deterministic for `(goal_canonical, hypotheses_sorted, k, corpus_version)`; canonical form should normalize Lean whitespace and variable names (e.g. `α` vs `α✝`). BP1/BP2 unaffected — adding a new tool increments the `tools/list` hash but this is an intentional schema bump per CLAUDE.md §9.

**Maturity signal:** Code available, MIT license, integrated with LeanDojo, used in 2024–2025 literature. High signal.

---

### Candidate 7 — Self-RAG (Adaptive Retrieval via Reflection Tokens)

**Name + citation:** "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection." Asai et al. arXiv:2310.11511. 2023.

**Year + venue:** 2023 — arXiv (cs.CL).

**What it does:** Self-RAG trains an LLM to emit special *reflection tokens* that signal: (a) whether retrieval is needed at the current generation step; (b) whether retrieved passages are relevant; (c) whether the generated output is grounded in the retrieved passages. Instead of always retrieving, the model retrieves *on-demand*. This adaptive retrieval reduced hallucination while maintaining or improving task accuracy across diverse benchmarks, and made the model "controllable during inference" — callers can constrain the reflection-token distribution to enforce or suppress retrieval.

**What's NEW vs arXMCP today:** arXMCP's retrieval is driven by the agent issuing explicit tool calls — there is no mechanism for the server to *signal* to an agent that a retrieved chunk warrants re-retrieval or is insufficient. Self-RAG's insight is that the server's response could include a `retrieval_confidence` or `sufficiency_score` field that the calling agent uses to decide whether to re-query. arXMCP's snippet contract (`server/tools.py`, `.claude/docs/snippet-contract.md`) returns a `score` field but that is a retrieval ranking score, not a contextual sufficiency signal. Concrete delta: add a `retrieval_confidence` field to the structured result payload indicating how well the retrieved chunk matches the posed query (based on the reranker score relative to a calibrated threshold). This is a low-cost extension to the existing result shape.

**Architectural fit:** Context-engineering change in `server/handlers/search.py` — add a `retrieval_confidence: float` to the result row alongside the existing `score` field. The value is `normalized_reranker_score > threshold` (0.0–1.0). Agents can use this to decide whether to issue a follow-up `search_papers` call with a refined query. No new MCP tool required; no BP1/BP2 impact if the field is added with a default null value in the frozen schema (schema bump required — re-pin `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py`).

**Tension with arXMCP philosophy:** Self-RAG requires training the LLM to emit reflection tokens — arXMCP runs NO LLM at runtime (CLAUDE.md §4.7). The Self-RAG *training* is irrelevant; what arXMCP can borrow is the *output-side signal* — returning a calibrated confidence score that a pre-existing LLM agent can use to decide to re-retrieve. No architecture conflict.

**Cache interaction:** `retrieval_confidence` is a function of `(query, retrieved_chunk, reranker_score)`; it is deterministic and included in the cached result payload. No new cache dimension needed. Compatible with `.claude/notes/07-multi-agent-caching.md` Tier-1/Tier-3 discipline.

**Maturity signal:** Code available (HuggingFace model + eval scripts). Well-cited; widely referenced in retrieval literature. Medium-high signal for the specific adaptation proposed here.

---

### Candidate 8 — `cite_neighbors` Tool Wire-Up (Citation Proof Chain)

**Name + citation:** This is not an external paper; it is an arXMCP-internal gap. The `cite_neighbors` MCP tool handler (`server/handlers/citations.py`) is a v1 stub that returns `{neighbors: [], infrastructure_status: "deferred"}` for every call (CLAUDE.md §7). The underlying library `server/graph_queries.py` is real and fully implemented (E09_S03), passing tests in `tests/test_proof_chain.py`.

**Year + venue:** Internal — E09 shipped (CLAUDE.md §3 status table, E09 ✅).

**What it does (what it *should* do):** `cite_neighbors(chunk_id, direction, depth)` traverses the Kùzu citation graph to return papers that cite, are cited by, or depend on (intra-paper `\ref{}` chain) a given chunk. This is the core of the *proof-chain workflow* (`.claude/docs/proof-chain-workflow.md`) — the Fixer agent uses it to find papers that cite the same result, potentially containing alternative proofs or corrected statements. The library supports five directions: `cites`, `cited_by`, `co_cited`, `co_citing`, `depends_on`. The stub handler only validates `chunk_id` format and returns empty.

**What's NEW vs arXMCP today (the gap):** The only missing piece is the handler body: calling `await server.graph_queries.cite_neighbors(chunk_id, direction=direction, depth=depth, max_results=limit, kuzudb_path=config.kuzudb_path, lancedb_path=config.lancedb_path)` and mapping `CitationNeighbor` dataclass results to the MCP envelope format. The F2 path-validation contract from the E09_S03 critique (referenced in `server/graph_queries.py` line 346) must be honored: `kuzudb_path` and `lancedb_path` must be derived from `config`, not from agent-supplied JSON. This is a small, high-value implementation task.

**Architectural fit:** Implementation change in `server/handlers/citations.py` — replace the stub body with a call to `server.graph_queries.cite_neighbors(...)`, wrap results in `envelope(...)`, apply `_cap(...)`. No new tools, no schema changes. The handler's input schema is already registered and byte-stable.

**Cache interaction:** `cite_neighbors` results are deterministic for `(chunk_id, direction, depth, limit, kuzudb_version)`; Tier-1 exact-query cache applies directly. Cache key should include a `graph_version` string (analogous to `corpus_version` for the vector store) so citation graph updates invalidate stale entries. This is consistent with `.claude/notes/07-multi-agent-caching.md` Tier-1 discipline. No BP1/BP2 impact — the tool is already registered in `ALL_TOOLS`.

**Maturity signal:** Internal implementation task; no external paper. The library is tested and passes `tests/test_proof_chain.py`. Zero external risk. High-value, low-effort.

---

### Candidate 9 — ReAct + Reflexion (Agent-Harness Primitives)

**Name + citation:**
- "ReAct: Synergizing Reasoning and Acting in Language Models." Yao et al. arXiv:2210.03629. ICLR 2023.
- "Reflexion: Language Agents with Verbal Reinforcement Learning." Shinn et al. arXiv:2303.11366. NeurIPS 2023.

**Year + venue:** 2022/2023.

**What it does:** ReAct interleaves *thought* (chain-of-thought reasoning) and *action* (tool calls) in a single generation stream — the agent reasons about what to retrieve, calls the tool, observes the result, then reasons about the next action. Reflexion extends this with a *reflection* step: after a failed attempt (e.g. a failed tactic), the agent writes a verbal self-critique into an episodic memory buffer, then retries. Reflexion achieved 91% on HumanEval (coding) by accumulating reflections across retries. Both papers treat the tool server as a stateless oracle that returns observations — the reasoning and memory live in the LLM agent, not the server.

**What's NEW vs arXMCP today:** These patterns define what the downstream pipeline agents (Tactician, Fixer) are *architecturally expected to do*. arXMCP's role as the tool server is to: (a) return deterministic, byte-stable results so that ReAct thought-action-observation sequences can share cache prefixes across agent retries; (b) return enough structured context (snippet + chunk_id + score) that Reflexion's verbal reflection can cite specific evidence ("the retrieved chunk `arxiv:2401.12345:a1b2c3d4...` stated X, but the Lean kernel said Y — the discrepancy is..."). arXMCP's current result shape supports this. The missing piece is the Lean kernel output in the observation stream — without `verify_lean_snippet`, Reflexion-style verbal self-critique of a proof attempt has no ground truth to reflect against.

**Architectural fit:** These are agent-side primitives; arXMCP does not implement them. The relevant arXMCP implication is: (a) tool results must be deterministic for ReAct chain caching (already ensured by `.claude/notes/07-multi-agent-caching.md` Property 2); (b) the Reflexion episodic buffer will accumulate tool results — arXMCP should return `chunk_id` + `paper_id` in every result so the agent's reflection can precisely cite the evidence used. Already satisfied by the snippet contract (`.claude/docs/snippet-contract.md`).

**Cache interaction:** ReAct/Reflexion are heavy users of the BP2 cache breakpoint (end of problem statement). Each retry adds a new tool call + observation block to the agent's context. Tool-use ID canonicalization (`.claude/notes/07-multi-agent-caching.md` "The cache-killer") is critical: if the orchestrator normalizes IDs before composing the next retry's context, the cache hit rate on the static prefix stays high. Already implemented in `server/orchestrator/id_canon.py`.

**Maturity signal:** Both papers widely cited; ReAct and Reflexion are foundational agent patterns implemented in every major agent framework (LangChain, LlamaIndex, Claude Code's agentic loop). High maturity. No new code needed in arXMCP.

---

### Candidate 10 — CodeAct (Executable Code as Unified Action Space)

**Name + citation:** "Executable Code Actions Elicit Better LLM Agents." Wang et al. arXiv:2402.01030. ICML 2024. Code: available open-source.

**Year + venue:** 2024 — ICML 2024.

**What it does:** CodeAct replaces structured JSON tool calls with Python code that the agent writes and executes directly. An interpreter runs the code; stdout/stderr flows back into the agent's context as the next observation. The agent can compose multiple tool calls into one code block, dynamically construct arguments, and self-debug across turns. Up to 20% improvement over JSON-format tool-use on 17 LLM evaluations. The 7K-example CodeActInstruct fine-tuning dataset (multi-turn Python-interpreter interactions) enables smaller models to adopt this pattern.

**What's NEW vs arXMCP today:** arXMCP exposes MCP tools with JSON-schema inputs — the calling agent issues structured tool calls, not free-form Python. CodeAct's insight is that an agent writing `results = search_papers("étale cohomology", k=10); filtered = [r for r in results if r['score'] > 0.8]` in a Python REPL is more flexible than separate tool calls. However, arXMCP's MCP interface cannot become a Python REPL without violating the MCP protocol contract. The relevant adaptation: arXMCP could expose a *batch tool call* mode (a single MCP tool that accepts a JSON list of sub-queries and returns a list of result sets). This reduces round-trips for an agent that would otherwise issue 4–5 sequential `search_papers` calls. The MCP spec supports this pattern via the `tools/call` method — no protocol extension needed.

**Architectural fit:** New `batch_search` MCP tool (`server/handlers/batch_search.py`) accepting `queries: list[SearchQuery]` and returning `list[SearchResult]`. This is schema-additive and does not modify existing tools. Alternatively, add a `batch: bool` parameter to `search_papers`. Note: a new tool bumps the `tools/list` hash and requires re-pinning `EXPECTED_TOOL_SCHEMA_SHA256` (CLAUDE.md §9).

**Tension with arXMCP philosophy:** CodeAct requires the *agent* to run a Python interpreter alongside its LLM calls. arXMCP does not need to change; the agent changes. The only arXMCP implication is ensuring tool results are Python-friendly (they already are — JSON with deterministic keys). No architecture-lock conflict (arXMCP runs no LLM at runtime; the CodeAct interpreter lives in the agent, not the server).

**Cache interaction:** A `batch_search` tool introduces a new cache key space: `sha256(sorted_query_list + filters_list + k_list + corpus_version)`. The Tier-1 cache can handle this if each sub-query result is also individually cached. BP1 is unaffected. BP2 may be affected if the batch result is long — ensure batch results use the same snippet contract (≤150 chars per result) to keep the total result payload small enough that downstream turns don't overflow the context window. See `.claude/notes/07-multi-agent-caching.md` "Tool-result shape" section.

**Maturity signal:** Code available; ICML 2024; implemented in OpenHands (formerly OpenDevin). High signal. The `batch_search` adaptation is an arXMCP-specific inference, not a direct port.

---

## 3. Sources Reviewed

| Paper / Framework | URL | Year | Code Available | High-Signal |
|---|---|---|---|---|
| Draft, Sketch, and Prove (Jiang et al.) | arXiv:2210.12283 | 2022 | Yes | Yes |
| DSP+ (Cao et al.) | arXiv:2506.11487 | 2025 | Not yet | Yes (watch) |
| LeanDojo / ReProver (Yang et al.) | arXiv:2306.15626 / github.com/lean-dojo | 2023 | Yes (MIT) | Yes |
| Goedel-Prover (Lin et al.) | arXiv:2502.07640 / github.com/Goedel-LM | 2025 | Yes (MIT) | Yes |
| DeepSeek-Prover-V2 (Ren et al.) | arXiv:2504.21801 / github.com/deepseek-ai | 2025 | Yes | Yes |
| Lean Copilot / LeanCopilot | github.com/lean-dojo/LeanCopilot | 2023–2025 | Yes (MIT) | Yes |
| LeanProgress (George et al.) | arXiv:2502.17925 / TMLR 2025 | 2025 | Yes (integrated into LeanDojo-v2) | Yes |
| ProofNet (Azerbayev et al.) | arXiv:2302.12433 | 2023 | Yes | Medium |
| ReAct (Yao et al.) | arXiv:2210.03629 | 2022 | Yes | Yes |
| Reflexion (Shinn et al.) | arXiv:2303.11366 | 2023 | Yes | Yes |
| CodeAct (Wang et al.) | arXiv:2402.01030 | 2024 | Yes | Yes |
| Self-RAG (Asai et al.) | arXiv:2310.11511 | 2023 | Yes | Medium |
| MCP Architecture Specification | modelcontextprotocol.io/docs/concepts/architecture | 2024–2025 | N/A | Yes |
| AlphaProof / AlphaGeometry (DeepMind) | deepmind.google blog | 2024 | No (closed) | Yes (context only) |
| Kimina-Prover (Numina) | arXiv:2504.11354 | 2025 | Partial | Medium |
| arXMCP `server/handlers/citations.py` | internal | 2025 | Yes (stub) | Yes |
| arXMCP `server/graph_queries.py` | internal | 2025 | Yes (real) | Yes |

---

## 4. Architectural Alignment

Each candidate mapped to arXMCP's current shape:

- **Candidate 1 — `verify_lean_snippet` tool:** Net-new. No existing file. Would land at `server/handlers/lean_verify.py` + registration in `server/tools.py::ALL_TOOLS` + schema re-pin in `tests/test_server_tool_schema.py`. Requires Lean 4 binary accessible at server startup (new env var `ARXMCP_LEAN_BIN` in `server/config.py`). LeanDojo Python package as subprocess backend (see Candidate 3).

- **Candidate 2 — DSP+ sketch validation:** Shares implementation with Candidate 1 — a `mode=syntax_only` parameter on `verify_lean_snippet` that short-circuits full kernel verification. Zero additional files if Candidate 1 is implemented first.

- **Candidate 3 — LeanDojo as backend:** Not a standalone tool. Acts as the subprocess backend for Candidate 1. Requires adding `leandojo` to `pyproject.toml` (MIT license, compatible with project's no-fork policy since it is a library import, not a code copy). Lean version pinning (`ARXMCP_LEAN_TOOLCHAIN` env var) needed alongside `ARXMCP_LEAN_BIN`. Subprocess lifecycle management is new territory; `server/lean_session.py` would be the natural home.

- **Candidate 4 — `has_lean_proof` filter (Goedel-Prover pattern):** Schema extension to `ingest/schema.py` (new boolean column `has_lean_proof`). Filter honored in `server/handlers/search.py` where the `filters` argument is currently ignored (CLAUDE.md §7 known stub). Closes one of the deferred `filters` stubs. No new tool.

- **Candidate 5 — DeepSeek-Prover-V2 subgoal context:** Motivates Candidate 1 architecture. No direct arXMCP change beyond `verify_lean_snippet`. Future: `include_subgoal_count` parameter in `server/handlers/chunk.py::handle_get_chunk` (deferred alongside existing reserved flags, CLAUDE.md §7).

- **Candidate 6 — `search_by_proof_state` tool:** Net-new tool or `mode` parameter on `search_papers`. Would route through `server/router.py` as a new `RouteTag.VERIFICATION` tag. Query preprocessing in `server/retrieval/` would need Lean goal normalization (whitespace + anonymous variable renaming). `server/handlers/search.py` already contains the retrieval dispatch logic.

- **Candidate 7 — `retrieval_confidence` field:** Additive change to result payload in `server/tools.py::envelope(...)` and `server/handlers/search.py`. Reranker score normalization logic in `server/retrieval/rerank.py`. Schema bump requires re-pinning `EXPECTED_TOOL_SCHEMA_SHA256` and updating `.claude/docs/snippet-contract.md`.

- **Candidate 8 — `cite_neighbors` wire-up:** Implementation change in `server/handlers/citations.py` only (replace stub body). Library `server/graph_queries.py` is complete. Tests already exist in `tests/test_proof_chain.py`. No schema changes. This is the highest-leverage / lowest-risk change in the entire candidate set.

- **Candidate 9 — ReAct / Reflexion:** Agent-side primitives. No arXMCP code change. Confirms existing design choices (deterministic results, BP1/BP2 caching, `chunk_id` in every result row, `server/orchestrator/id_canon.py`). Acts as a validation that arXMCP's current architecture is already ReAct/Reflexion-compatible.

- **Candidate 10 — `batch_search` tool (CodeAct pattern):** Net-new tool at `server/handlers/batch_search.py`. Schema bump required. Medium effort; lower priority than Candidates 1 and 8.

---

## 5. Themes

**Lean kernel as the universal feedback signal.** Every frontier math-proving system — DSP, DSP+, DeepSeek-Prover-V2, Goedel-Prover, LeanDojo/ReProver — closes its tactic loop against the Lean kernel. This is not an architectural trend to watch; it is an established convergence. arXMCP is the outlier: it provides retrieval context upstream of verification but no execution feedback downstream. Closing this gap (Candidates 1–2) is the single change that moves arXMCP from a context-enrichment substrate to a full harness component in the pipeline.

**Formal library retrieval is complementary to informal paper retrieval.** The frontier provers retrieve from Mathlib (formal, verified); arXMCP retrieves from arXiv (informal, research-level). There is no competition — both signals are useful, at different stages. The Sketcher/Autoformalizer needs arXiv informal context to generate plausible Lean structure; the Tactician needs Mathlib formal premises to fill subgoals. Candidates 3 and 6 would add the formal-library retrieval dimension without replacing informal retrieval.

**Retrieval conditioned on proof state is the tactic-level analogue of query-conditioned retrieval.** Just as Self-RAG conditions retrieval on the current generation step, ReProver conditions retrieval on the current Lean proof state (`⊢` goal). arXMCP's `search_papers` takes a natural-language query; a `search_by_proof_state` tool taking a Lean goal expression would let the Tactician retrieve directly against the formal context rather than translating the goal to English first. This is a precision improvement, not a capability addition.

**The citation graph proof chain is the highest-leverage near-term move.** The `cite_neighbors` wire-up (Candidate 8) is a one-function implementation task against a completed library, with no external dependencies, no schema changes, and complete test coverage already written. It unlocks the proof-chain workflow (`.claude/docs/proof-chain-workflow.md`) and gives the Fixer agent a mechanism that every production math-formalization workflow (Tao's equational-theories project, Mathlib PR workflows) relies on. It should be shipped before any other candidate.

---

## 6. Out of Scope / Parking Lot

- **AlphaProof MCTS search.** DeepMind's AlphaZero-style tree search over Lean tactic states is not applicable: it requires training a value function over proof states, which is a full ML training pipeline. arXMCP runs no training. Rejected: architecture-lock conflict (requires LLM + value model at runtime, violates CLAUDE.md §4.7).

- **Multi-agent debate / adversarial LLM critique** (Du et al. 2023 arXiv:2305.14325; Prover-Verifier Games, Kirchner et al. 2024 arXiv:2407.13692). The "Lean kernel is the better critic" framing (`.claude/notes/01-mission-and-context.md`) explicitly deprioritizes LLM adversarial critique of math content. These papers are documented in `.claude/notes/10-references-and-prior-art.md` as context; they are not candidates for implementation. Rejected: contradicts design philosophy — named tension documented per hard rules.

- **Process Reward Models** (Let's Verify Step-by-Step, Lightman et al. 2023 arXiv:2305.20050; Math-Shepherd, Wang et al. 2023). PRMs provide step-level LLM scoring that is useful for olympiad-level arithmetic but does not transfer to research math (documented in `.claude/notes/01-mission-and-context.md`). Additionally, training or hosting a PRM requires an LLM at runtime. Rejected: same philosophy violation + architecture-lock conflict.

- **LLM summarization of retrieved chunks** (Haiku-generated summaries). Permanently dropped in E06_S04 (`.claude/notes/07-multi-agent-caching.md` "Tool-result shape" update). Any re-introduction of server-side summarization conflicts with BP1 cache discipline and is banned per the design constitution. Rejected: already settled design decision.

- **Kimina-Prover interleaved NL+Lean stream.** The interleaved scratchpad pattern (natural-language reasoning interleaved with Lean tactics in one token stream) is a training choice for the model, not an inference-time tool pattern. arXMCP cannot implement this without running an LLM at runtime. Rejected: architecture-lock conflict.

- **REMEMBERER / RLEM (long-term experience memory for agents).** arXMCP is a tool provider, not an agent; the episodic memory buffer belongs in the calling agent. Rejected: out of server scope.

- **Toolformer (Schick et al. 2023).** Self-supervised tool-use training. arXMCP runs no training. Rejected: not applicable.

- **Lean-STaR interleaved NL thoughts.** Same rejection reason as Kimina-Prover — training technique, not an inference-time server capability.

- **FrontierMath as a new eval benchmark.** Worth tracking for measuring pipeline quality against research-grade targets (`.claude/notes/01-mission-and-context.md`), but not a server capability. Parked: consider for the next eval-harness epic (E05 follow-up).
