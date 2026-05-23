# Research-Frontier Brief — 2026-Q2 Verification-Feedback Scan

**Scout:** research-frontier  
**Run ID:** 2026q2-verification-feedback-scan  
**Date:** 2026-05-22  
**Scope:** Execution-feedback loops for Lean autoformalization pipelines; closing the `cite_neighbors` tool gap; adjacent retrieval advances.

---

## 1. TL;DR

Top-3 methods to prioritize: (1) the **Lean 4 REPL JSON protocol** (`leanprover-community/repl`) as a zero-dependency stdin/stdout interface for exposing compile-errors, proof-state, and sorry-goals to arXMCP's MCP tool surface; (2) **LeanSearch v2's embedding-reranker-plus-reasoning-cycle architecture** (arXiv:2605.13137) as a directly adoptable pattern for the `cite_neighbors` gap — its sketch-retrieve-reflect loop and open benchmark give arXMCP a tested template for Lean-premise retrieval; (3) the **Graph-Augmented Premise Selection** approach of Petrovčič et al. (arXiv:2510.23637), which layers a GNN over the existing Kùzu citation-dependency graph to improve premise recall by 25%+ over embedding-only baselines.  
The main thematic shift: the community has converged on **execution feedback from a live Lean kernel as the critical signal** — not LLM self-critique — and is building lightweight structured interfaces (JSON REPL, REPL-as-subprocess) rather than heavyweight training-loop wrappers.

---

## 2. Method Candidates

### 2.1 Lean 4 REPL JSON Protocol (leanprover-community/repl)

**Method name:** Lean 4 REPL — stdin/stdout JSON interface to Lean's type checker and tactic engine  
**Year + author:** 2023–2025; leanprover-community contributors (maintained alongside mathlib4)  
**Primary citation:** https://github.com/leanprover-community/repl (MIT license; no arXiv paper — the technical interface is documented in the README and used extensively by LeanDojo, DeepSeek-Prover, APOLLO, and LeanTree)  
**Summary:** A minimal Lean 4 package (`lake exe repl`) that wraps Lean's kernel with a JSON-over-stdin/stdout protocol. Each submitted declaration or tactic receives a structured JSON response containing: error messages with severity and source position, proof-state as a list of goal strings (`"goal": "⊢ Nat"`), unsolved sorry locations including the expected type, and optionally a serialized environment snapshot (`.olean` "pickle"). The design is deliberately minimal — it is the subprocess backbone used by every recent execution-feedback prover (DeepSeek-Prover-V1.5, APOLLO, LeanTree, Seed-Prover). Adding an arXMCP MCP tool (`lean_verify`) that spawns this REPL as a subprocess, forwards a tactic block, and returns the structured JSON response to the fixer agent is a bounded implementation task.  
**Compute footprint:** CPU-only; no GPU, no model weight download. Lean compilation is I/O- and CPU-bound; a typical tactic round-trip takes 0.5–5 seconds depending on library imports. The REPL supports environment pickling so subsequent turns re-use a pre-compiled state.  
**Implementation complexity:** ~150–250 LOC for a new `server/handlers/lean_verify.py` wrapping `asyncio.create_subprocess_exec`; JSON parsing of the response schema; error normalization to the MCP envelope. No new Python dependency beyond stdlib. Reference impl: https://github.com/leanprover-community/repl (MIT).  
**arXMCP fit:** Net-new MCP tool `lean_verify` in `server/handlers/`. The tactician and fixer agents call `lean_verify` with a tactic block; the response populates the `proof_state`, `errors`, and `goals_remaining` fields. Closes the "real execution feedback" gap described in CLAUDE.md §7 (known stubs / deferrals). Does not require LanceDB or Kùzu changes.  
**Maturity signal:** Used as the subprocess backend in DeepSeek-Prover-V1.5 (arXiv:2408.08152, 2024, widely cited), APOLLO (arXiv:2505.05758, 2025), LeanTree (arXiv:2507.14722, 2025), and Seed-Prover 1.5 (arXiv:2512.17260, 2025). The protocol is de-facto standard for programmatic Lean 4 interaction as of early 2026. MIT license; actively maintained alongside mathlib4.

---

### 2.2 LeanSearch v2 — Embedding-Reranker Pipeline with Reasoning Cycles

**Method name:** LeanSearch v2 — global premise retrieval with iterative sketch-retrieve-reflect  
**Year + author:** 2026; Guoxiong Gao, Zeming Sun, Jiedong Jiang, Yutong Wang, Jingda Xu, Peihao Wu, Bryan Dai, Bin Dong  
**Primary citation:** arXiv:2605.13137 (2026); code: https://github.com/frenzymath/LeanSearch-v2 (license not confirmed in abstract; check repo before adopting)  
**Summary:** Addresses global premise retrieval — finding scattered Mathlib lemmas needed anywhere in a proof, not just near the goal. Two modes: (a) a standard embedding-reranker pipeline over a "hierarchy-informalized Mathlib corpus" (LaTeX-style doc strings converted to natural-language prose), achieving nDCG@10 = 0.62 vs. 0.53 baseline without domain fine-tuning; (b) a reasoning mode that iterates sketch-retrieve-reflect cycles, producing 20% proof success vs. 16% for the next-best system when slotted into a prover loop. The corpus construction — converting formal Lean 4 declarations to natural-language-aligned text — is directly analogous to arXMCP's existing BGE-M3 dual-column encoding of body_text (statement) and proof_text (proof window), but applied to the Mathlib side rather than the arXiv side.  
**Compute footprint:** Standard mode: one embedding model + one reranker (GPU for encoding, CPU for inference is feasible at research scale). Reasoning mode: adds LLM calls for sketch generation; heavier but bounded by a fixed number of reflect cycles.  
**Implementation complexity:** The embedding-reranker standard mode is ~200 LOC of integration code once the hierarchy-informalized corpus exists; the reasoning cycle is a new agent-side orchestration pattern. The corpus preprocessing (hierarchy → NL prose) is the dominant engineering cost (~400–600 LOC). Reference impl open-sourced at the repository above.  
**arXMCP fit:** Standard mode informs improvements to `server/retrieval/` and `ingest/embedder.py` — specifically the value of hierarchy-aware corpus preprocessing before embedding. The sketch-retrieve-reflect cycle is an agent-side pattern (outside arXMCP's server) but arXMCP's `cite_neighbors` + `search_papers` toolchain is what would feed it. Most directly: wiring the real `cite_neighbors` MCP tool (currently a v1 stub, CLAUDE.md §7) so the Mathlib side of the proof chain can be navigated.  
**Maturity signal:** Published May 2026; code open-sourced; live API at leansearch.net; directly benchmarked against ReProver and other premise retrievers. High-signal: paper + code + live service + benchmark.

---

### 2.3 Graph-Augmented Premise Selection (Petrovčič et al.)

**Method name:** Graph-augmented premise selection — GNN over Lean dependency graph combined with text embeddings  
**Year + author:** 2025; Job Petrovčič, David Eliecer Narvaez Denis, Ljupčo Todorovski  
**Primary citation:** arXiv:2510.23637 (2025); no code repository confirmed in abstract  
**Summary:** Combines dense text embeddings of Lean formalizations with a heterogeneous graph neural network that models two edge types: (a) state-premise edges (which premises are referenced in which proof states) and (b) premise-premise edges (which premises cite or use each other). The GNN propagates relational information so that premises with strong structural proximity to the current proof state are promoted even when lexical/semantic similarity is low. Achieves >25% improvement over ReProver (the pure-retrieval baseline) on the LeanDojo Benchmark. The insight directly applies to arXMCP's existing Kùzu citation graph: the `cites` and `depends_on` edge types in `server/graph_queries.py` are precisely the "premise-premise" and "state-premise" signals this method exploits, but they are not currently fed into the retrieval ranking.  
**Compute footprint:** Requires training or fine-tuning a GNN over the Lean dependency graph. At mathlib-corpus scale this is a one-time GPU training job (~hours); at arXMCP's 50-paper seed corpus the graph is small enough for CPU-only GNN inference. A pre-trained GNN checkpoint would be needed for production.  
**Implementation complexity:** ~500–800 LOC for a GNN wrapper that ingests Kùzu edge triples and re-ranks LanceDB ANN candidates. No reference impl confirmed. Requires PyTorch Geometric or DGL. Moderate complexity — the GNN training pipeline is the hard part; the inference re-ranking integration is straightforward once the model exists.  
**arXMCP fit:** `server/retrieval/` re-ranking phase (Phase 3, `server/retrieval/rerank.py`) could add a GNN re-ranking sub-phase that queries the Kùzu graph for structural neighborhood and blends those scores with BGE-reranker scores. The Kùzu schema and `server/graph_queries.py` already expose the edge data needed.  
**Maturity signal:** Single paper, no confirmed code release; +25% benchmark result is strong. Methodology is reproducible given LeanDojo as a baseline. Medium maturity — strong result, lacks OSS impl.

---

### 2.4 APOLLO — Lean-Compiler-Error-Guided Iterative Proof Repair

**Method name:** APOLLO — LLM+Lean collaboration with compiler-error isolation and targeted resampling  
**Year + author:** 2025; Azim Ospanov, Farzan Farnia, Roozbeh Yousefzadeh  
**Primary citation:** arXiv:2505.05758 (2025)  
**Summary:** APOLLO implements an iterative repair cycle: (1) LLM generates a Lean 4 proof; (2) Lean compilation identifies syntax errors, type-check failures, and unsolved goals; (3) an agent isolates the failing sub-lemmas and remaining goals from the compiler output; (4) the LLM is re-invoked only on the specific failing goals with a small sampling budget (top-K), rather than regenerating the whole proof; (5) automated solvers handle solvable sub-problems; (6) the process iterates until the proof closes or budget is exhausted. The key architectural insight for arXMCP: **exposing structured compiler feedback — specifically goal state, failing lemma identity, and error type — as distinct fields in the MCP tool response** enables the fixer agent to perform targeted resampling rather than blind whole-proof retry. APOLLO achieves state-of-the-art results while reducing sampling from thousands to hundreds.  
**Compute footprint:** LLM-dependent (model calls dominate). Lean compilation: CPU-only subprocess, same as REPL above. No additional GPU requirement beyond whatever model the agent uses.  
**Implementation complexity:** The structured feedback extraction (error type → goal_id → failed_lemma_id) is ~100–150 LOC of Lean REPL output parsing; the MCP tool response schema extension is the design decision. The retry orchestration lives in the agent, not in arXMCP's server. Low implementation complexity for the server side.  
**arXMCP fit:** Informs the schema design of the proposed `lean_verify` MCP tool (see §2.1). The critical output fields are: `proof_state: list[GoalRecord]`, `errors: list[ErrorRecord]` (with `severity`, `position`, `message`), `sorry_goals: list[SorryRecord]`, `compilation_success: bool`. arXMCP's tool would return these; the fixer agent implements the APOLLO repair logic.  
**Maturity signal:** arXiv 2025; benchmark results competitive with DeepSeek-Prover-V1.5. Medium-high maturity — paper + benchmark; no confirmed OSS impl of the full pipeline, but the Lean REPL subprocess (§2.1) is the only arXMCP-side dependency.

---

### 2.5 Process-Driven Autoformalization in Lean 4 (Lu et al.)

**Method name:** Process-Supervised Verifier (PSV) for autoformalization — Lean compiler feedback as a process-level training signal  
**Year + author:** 2024; Jianqiao Lu, Yingjia Wan, Zhengying Liu, Yinya Huang, and 9 others  
**Primary citation:** arXiv:2406.01940 (2024); introduces the FormL4 benchmark  
**Summary:** Introduces a Process-Supervised Verifier (PSV) that uses Lean 4 compiler feedback (compilation success/failure, error messages, type-check outcomes) as step-level supervision rather than binary final-proof reward. The FormL4 benchmark provides 3,000+ Lean 4 autoformalization examples with process-level annotations. For arXMCP this matters in two ways: (a) it validates the value of structured compiler feedback as a signal (motivating the `lean_verify` tool schema), and (b) the FormL4 benchmark data could inform which autoformalization patterns arXMCP's autoformalizer agent encounters most, guiding what kinds of premise context arXMCP should pre-load.  
**Compute footprint:** PSV training requires GPU (fine-tuning a verifier model on FormL4). At inference time the PSV is a classifier — lightweight. The Lean compiler subprocess is CPU-only as in §2.1.  
**Implementation complexity:** For arXMCP: the PSV training is out of scope. The FormL4 benchmark and the compiler-feedback schema design are the relevant artifacts. ~0 additional LOC on arXMCP's server; the value is in benchmark data and schema design guidance.  
**arXMCP fit:** Informs `lean_verify` tool schema design (§2.1, §2.4). The types of errors captured in FormL4 annotations map directly to which JSON fields arXMCP should expose in the MCP response. Not a new module — context for schema decisions.  
**Maturity signal:** arXiv 2024; FormL4 benchmark public; cited in subsequent autoformalization work. Solid maturity for schema guidance purposes.

---

### 2.6 2D Matryoshka Embeddings for Adaptive Retrieval

**Method name:** 2D Matryoshka Representation Learning (2D-MRL) — joint training across layer depth and embedding dimensionality  
**Year + author:** 2024; Shuai Wang, Shengyao Zhuang, Bevan Koopman, Guido Zuccon  
**Primary citation:** arXiv:2411.17299 (2024); related: Arctic-Embed 2.0 (arXiv:2412.04506, 2024)  
**Summary:** Standard Matryoshka Representation Learning (MRL) allows a single embedding model to produce vectors of varying dimensionality by truncation, without re-training. The 2D extension adds a second axis: which transformer layer to read from. A single 2D-MRL model can serve queries at (layer=6, dim=256) for fast filtering and (layer=12, dim=1024) for full-quality ranking — a natural fit for arXMCP's 3-tier cache design. The BGE-M3 model arXMCP already uses has a standard MRL variant (from FlagEmbedding); moving to a 2D-MRL fine-tune or switching to a 2D-MRL-pretrained model (e.g., Arctic-Embed 2.0) would enable arXMCP's Tier-1 semantic cache to use shorter vectors for fast approximate matching, reducing cache lookup latency.  
**Compute footprint:** Training requires a GPU fine-tune (one training job). Inference: pure algorithm — standard forward pass with early-exit at the target layer/dimension. No additional model download beyond the chosen base model.  
**Implementation complexity:** ~50–100 LOC change to `ingest/embedder.py` to emit both a short-dim (Tier-1 cache) and full-dim (Tier-2 ANN) vector per chunk. Schema change to `ingest/schema.py` (add `embedding_short` column). Compatible with LanceDB. Reference impl: sentence-transformers supports MRL truncation natively (Apache-2.0 license); BGE-M3's FlagEmbedding also supports it (MIT license).  
**arXMCP fit:** `ingest/embedder.py` (dual-resolution emit) + `ingest/schema.py` (new column) + `server/cache.py` (Tier-1 uses short-dim FAISS index). Replaces arXMCP's current single-resolution BGE-M3 output.  
**Maturity signal:** Reproducibility study (arXiv:2411.17299) confirms the technique; Arctic-Embed 2.0 ships it in production (Snowflake, Apache-2.0); sentence-transformers and FlagEmbedding provide OSS implementations. High practical maturity.

---

### 2.7 HERMES — Interleaved Informal+Formal Reasoning with Lean Checkpoints

**Method name:** HERMES — hybrid informal/formal math reasoning with intermediate Lean verification steps  
**Year + author:** 2025; Azim Ospanov, Zijin Feng, Jiacheng Sun, Haoli Bai, Xin Shen, Farzan Farnia  
**Primary citation:** arXiv:2511.18760 (2025); code open-sourced per abstract  
**Summary:** HERMES alternates between free-form chain-of-thought reasoning (the sketcher/autoformalizer role) and formal Lean verification checkpoints (the tactician/fixer role). A memory module maintains proof continuity across the full chain. Intermediate formal checking prevents "reasoning drift" — accumulated informal errors that compound into an unsound proof. Achieves 67% accuracy improvement on AIME'25 while using 80% fewer inference FLOPs compared to reward-only methods. For arXMCP the architectural lesson is that the MCP server should expose verification feedback at intermediate checkpoints, not only at whole-proof completion — the `lean_verify` tool should support incremental tactic submission, not just whole-proof batch submission. This aligns with the REPL's command/tactic mode split (§2.1).  
**Compute footprint:** LLM-dependent for the informal reasoning passes. Lean verification is CPU-only subprocess. The memory module is a structured context accumulator (in-memory, no GPU).  
**Implementation complexity:** The HERMES agent loop is an agent-side concern outside arXMCP's server. arXMCP's contribution is a `lean_verify` tool that supports both batch (submit full proof) and incremental (submit one tactic, get current goal state) modes. Incremental mode adds ~50 LOC to the handler.  
**arXMCP fit:** Motivates the `lean_verify` tool's tactic-mode design (§2.1 incremental path). The memory module pattern informs how arXMCP's retrieval context (pre-loaded premises, definitions) should be structured across a multi-turn proof session — relevant to the 3-tier cache discipline (`.claude/notes/07-multi-agent-caching.md`).  
**Maturity signal:** arXiv 2025; code open-sourced; AIME'25 benchmarks. Strong maturity signal — concrete benchmark + reproducible code.

---

### 2.8 ReProver / LeanDojo — Retrieval-Augmented Theorem Proving Baseline

**Method name:** ReProver — retrieval-augmented tactic generation with premise retrieval over Lean libraries  
**Year + author:** 2023; Kaiyu Yang, Aidan M. Swope, Alex Gu, Rahul Chalamala, et al. (NeurIPS 2023)  
**Primary citation:** arXiv:2306.15626 (2023); code: https://github.com/lean-dojo/LeanDojo (MIT license)  
**Summary:** LeanDojo provides the Python infrastructure to interact with Lean 4 (extract proof states, run tactics, retrieve premises from Mathlib). ReProver is an LLM tactic generator that retrieves relevant premises from Mathlib using a retrieval model before generating each tactic. This is the foundational system that all 2024–2026 work (LeanSearch v2, Graph-Augmented Premise Selection, APOLLO, LeanTree) is built on or benchmarked against. Although published in 2023, it is not in arXMCP's prior-art notes (`.claude/notes/10-references-and-prior-art.md` cites LeanDojo and LeanCopilot but not ReProver itself), and the LeanDojo v4.20.0 release (June 2024) added "check proof" functionality and `build_deps` caching that are directly useful for arXMCP's `lean_verify` implementation.  
**Compute footprint:** LeanDojo: CPU-only for Lean interaction. ReProver: GPU for premise embedding and tactic generation. The premise retrieval component alone can run CPU-only with a pre-built index.  
**Implementation complexity:** LeanDojo's Python API wraps the Lean REPL subprocess with a higher-level interface. Adopting it (rather than raw REPL JSON) would reduce arXMCP's `lean_verify` implementation to ~100 LOC. MIT license. The tradeoff: LeanDojo is a non-trivial dependency (Lean 4 + lake + mathlib build).  
**arXMCP fit:** `server/handlers/lean_verify.py` could use LeanDojo's `Dojo` context manager to interact with Lean rather than managing the REPL subprocess directly. The LeanDojo premise extraction pipeline also provides a model for how arXMCP could eventually index Mathlib chunks (a net-new corpus alongside the arXiv corpus).  
**Maturity signal:** NeurIPS 2023; widely cited; MIT license; actively maintained; used by DeepSeek-Prover, APOLLO, LeanTree, Seed-Prover. Very high maturity — the standard infrastructure for Lean 4 agent integration.

---

### 2.9 FoVer — Formal-Verification-Derived Process Reward Model Training Data

**Method name:** FoVer — PRM training data synthesis via formal verifiers (Z3, Isabelle), transferable to NL reasoning  
**Year + author:** 2025; Ryo Kamoi, Yusen Zhang, Nan Zhang, and others  
**Primary citation:** arXiv:2505.15960 (2025)  
**Summary:** FoVer uses formal verification tools (Z3, Isabelle) to automatically generate step-level correctness labels for reasoning chains — eliminating human annotation and repeated LLM sampling. The trained Process Reward Model generalizes from formal math domains to informal NL reasoning (NLI, BBH) because step-level logical discipline transfers. For arXMCP this is relevant not as a direct implementation but as evidence that **execution feedback from formal verifiers (including Lean's kernel) is a reliable training signal for process-level judgment** — reinforcing the design decision to expose Lean kernel feedback rather than relying on LLM self-scoring. It also suggests arXMCP could generate evaluation labels for the `make eval` fixture (CLAUDE.md §7) by running chunks through formal verification where possible.  
**Compute footprint:** Z3/Isabelle verification: CPU-only, fast. PRM training: GPU fine-tune (one-time). Inference: lightweight classifier.  
**Implementation complexity:** Relevance to arXMCP is indirect — no new server module. The connection is to the eval harness: using formal verifier verdicts as ground truth for the `tests/eval/fixtures/queries.json` curation. ~0 arXMCP LOC; high value for eval quality.  
**arXMCP fit:** Informs the eval fixture curation process (`.claude/docs/eval-curation.md`). Not a retrieval module change.  
**Maturity signal:** arXiv 2025; benchmark results on MATH, NLI, BBH; no confirmed code release but methodology is straightforward.

---

### 2.10 SAFE — Step-Aware Formal Verification of NL Reasoning Steps

**Method name:** SAFE — retrospective step-aware formal verification using Lean 4 to detect reasoning hallucinations  
**Year + author:** 2025; Chengwu Liu, Ye Yuan, Yichun Yin, Yan Xu, and others  
**Primary citation:** arXiv:2506.04592 (2025); introduces FormalStep benchmark (30,809 examples)  
**Summary:** SAFE translates each step in an LLM's chain-of-thought into a formal Lean 4 statement and attempts to prove it, using compilation/verification outcome as a hallucination detector. For arXMCP this demonstrates a different use of the Lean kernel: not as a tactic executor for proof search but as a **claim verifier for informal reasoning steps** produced by the sketcher. The FormalStep benchmark (30,809 formalized math claims) is a publicly available dataset that could augment arXMCP's eval fixtures or inform chunk quality signals — a high-quality formalized claim in a retrieved chunk provides stronger grounding signal than an informally stated one.  
**Compute footprint:** Lean compilation: CPU-only subprocess (same as §2.1). The formalization step requires LLM calls (to translate NL claim → Lean statement). No additional GPU beyond the model.  
**Implementation complexity:** For arXMCP's server: a `lean_check_claim` tool variant that accepts a natural-language claim + Lean context and returns a verification verdict would be ~100 LOC layered on the base `lean_verify` handler (§2.1). The FormalStep dataset is available for benchmark use.  
**arXMCP fit:** Extends the `lean_verify` tool family with a claim-verification mode. Directly serves the fixer agent when it needs to audit an intermediate sketcher claim before formalizing it. Also informs chunk quality scoring in `ingest/`.  
**Maturity signal:** arXiv 2025; FormalStep benchmark of 30,809 examples; code publicly available per abstract. Strong maturity signal.

---

## 3. Sources Reviewed

| Venue | URL Pattern | Papers Scanned | High-Signal |
|---|---|---|---|
| arXiv cs.LO (Logic in CS) | arxiv.org/list/cs.LO/ | ~25 (Jan 2025 listing + targeted searches) | Yes — 8 high-signal papers |
| arXiv cs.AI (Artificial Intelligence) | arxiv.org/search/?query=lean+proof+... | ~15 papers via targeted search | Yes — 4 high-signal |
| arXiv cs.IR (Information Retrieval) | arxiv.org/search/?query=colbert+late+... | ~12 papers via targeted search | Partial — retrieval methods not math-specific |
| arXiv cs.CL (Computation & Language) | arxiv.org/search/?query=autoformalization+... | ~10 papers | Yes — autoformalization cluster |
| arXiv cs.LG (Machine Learning) | arxiv.org/search/?query=matryoshka+... | ~8 papers | Partial — embedding methods |
| LeanDojo GitHub releases | github.com/lean-dojo/LeanDojo/releases | v2.0.0–v4.20.0 changelog | Yes — v4.20.0 "check proof" feature |
| leanprover-community/repl | github.com/leanprover-community/repl | README + protocol spec | Yes — canonical Lean REPL interface |
| LeanSearch v2 | github.com/frenzymath/LeanSearch-v2 | arXiv:2605.13137 | Yes — directly applicable |
| DeepSeek-Prover-V1.5 | arxiv.org/abs/2408.08152 | Full abstract | Yes — RL from proof assistant feedback |
| APOLLO | arxiv.org/abs/2505.05758 | Full abstract | Yes — error-guided iterative repair |
| HERMES | arxiv.org/abs/2511.18760 | Full abstract | Yes — interleaved informal/formal |
| Graph-augmented premise | arxiv.org/abs/2510.23637 | Full abstract | Yes — GNN over dependency graph |
| 2D Matryoshka | arxiv.org/abs/2411.17299 | Full abstract | Partial — general retrieval, not math-specific |
| Process-Driven Autoformalization | arxiv.org/abs/2406.01940 | Full abstract | Yes — compiler feedback schema |
| FoVer | arxiv.org/abs/2505.15960 | Full abstract | Partial — eval fixture relevance |
| SAFE | arxiv.org/abs/2506.04592 | Full abstract | Yes — claim verification pattern |
| LEMUR | arxiv.org/abs/2601.21853 | Full abstract | Low — general retrieval optimization |
| Col-Bandit | arxiv.org/abs/2602.02827 | Full abstract | Low — general ColBERT optimization |
| RT-RAG | arxiv.org/abs/2601.11255 | Full abstract | Low — general multi-hop QA |
| GNN-RAG | arxiv.org/abs/2405.20139 | Full abstract | Low — KG QA, not math-specific |
| HyperRAG | arxiv.org/abs/2602.14470 | Full abstract | Low — hypergraph QA, not math-specific |

---

## 4. Themes

**Convergence on kernel-as-critic.** Every high-output 2024–2026 prover system (DeepSeek-Prover-V1.5, APOLLO, HERMES, LeanTree, Seed-Prover 1.5) uses Lean's compiler/type-checker as the authoritative correctness signal. The community has decisively moved away from LLM self-critique toward execution feedback — the same framing in arXMCP's "Lean kernel is the better critic" design note (`.claude/notes/01-mission-and-context.md`). arXMCP is architecturally aligned with this convergence; the gap is that the tool surface has not yet exposed kernel feedback.

**Premise retrieval specialization.** The retrieval problem for theorem proving is no longer treated as generic IR: the 2024–2026 literature (LeanSearch v2, Graph-Augmented Premise Selection, ReProver follow-ons) has converged on a specialized sub-problem — retrieving the right Mathlib premises for the current proof state — and the winning architectures combine text embeddings with structural graph signals (dependency edges, state-premise co-occurrence). This is exactly the `cite_neighbors` + `search_papers` combination arXMCP's proof-chain workflow (`.claude/docs/proof-chain-workflow.md`) envisions but has not yet fully wired.

**Execution-feedback loop design is the key engineering decision.** Papers differ mainly in how they structure the feedback loop: whole-proof batch (DeepSeek-Prover-V1.5), targeted sub-goal resampling (APOLLO), incremental tactic mode (LeanTree, HERMES), or retrospective claim verification (SAFE). The Lean 4 REPL JSON protocol (§2.1) supports all of these modes; arXMCP's `lean_verify` tool design should expose enough structure for the consumer agent to choose the loop style.

**Matryoshka embeddings maturing for production.** Standard 1D MRL (dimension truncation) is now shipping in Arctic-Embed 2.0 and jina-embeddings-v3 with strong benchmark support. The 2D extension (layer + dim) is a research-grade improvement that adds architectural flexibility. arXMCP's BGE-M3 embedder already has MRL support via FlagEmbedding; exploiting it for dual-resolution cache lookup is a low-LOC win.

---

## 5. Already in arXMCP / Already Considered

- **BGE-M3 dual-column embedding** (`ingest/embedder.py`): already ships statement + proof embeddings; no separate claim: already has BGE-M3.
- **BM25 + ANN + RRF hybrid retrieval** (`server/retrieval/bm25.py`, `ann.py`, `rrf.py`): fully shipped in E07. The "hybrid dense/sparse" framing is already implemented.
- **BGE-reranker-v2-m3 cross-encoder** (`server/retrieval/rerank.py`): Phase-3 reranker already implemented; gated on `ARXMCP_ENABLE_RERANK`.
- **3-tier retrieval cache** (`server/cache.py`, `server/cache_sqlite.py`): already shipped in E08; Tier-2 uses FAISS in-memory.
- **Citation graph (Kùzu)** (`ingest/kuzudb_schema.py`, `server/graph_queries.py`): graph is real and queryable. The `cite_neighbors` MCP tool handler (`server/handlers/citations.py`) is the v1 stub.
- **LeanDojo / LeanCopilot** (`.claude/notes/10-references-and-prior-art.md` lines 69–76): already studied. LeanDojo v4.20.0 features (§2.8) are an incremental update, not a new discovery.
- **ColBERT-v2 / late interaction** (`.claude/notes/10-references-and-prior-art.md` line 163): already noted as "Tier 6 / v1.5" candidate. Col-Bandit and LEMUR are efficiency improvements on a method already deprioritized.
- **Theorem-aware chunker** (`ingest/chunker.py`): LaTeXML-based structural chunker already shipped in E02.
- **SPECTER2 / citation-aware embeddings** (`.claude/notes/10-references-and-prior-art.md` line 155): already noted. No 2024–2026 SPECTER follow-on found in scan.
- **Draft-Sketch-Prove / subgoal decomposition** (`.claude/notes/10-references-and-prior-art.md` line 83): already referenced. DeepSeek-Prover-V2 extends this; already in prior art (line 60).
- **Standard Matryoshka MRL** (`.claude/notes/10-references-and-prior-art.md`): NOT explicitly listed, but BGE-M3 supports it via FlagEmbedding. The 2D extension (§2.6) is novel relative to what arXMCP tracks.
- **SAFE / FormalAlign**: NOT in prior-art notes; surfaced as new.
- **APOLLO / HERMES**: NOT in prior-art notes; surfaced as new.
- **LeanSearch v2**: NOT in prior-art notes; surfaced as new.
- **leanprover-community/repl JSON protocol**: referenced indirectly via LeanDojo, but the direct protocol docs and "REPL-as-subprocess" design pattern are not explicitly captured.

---

## 6. Out of Scope / Parking Lot

| Paper / System | Rejection Reason |
|---|---|
| **RT-RAG** (arXiv:2601.11255) — Reasoning in Trees for multi-hop QA | Multi-hop QA over text corpora; decomposition method does not adapt to formal proof chain structure. Not implementable without a text QA evaluation harness arXMCP does not have. |
| **GNN-RAG** (arXiv:2405.20139) — GNN for knowledge graph QA | Targets Freebase/KGQA benchmarks, not mathematical citation or theorem dependency graphs. Low signal for arXMCP's specific graph structure. |
| **HyperRAG** (arXiv:2602.14470) — Hypergraph RAG | N-ary relations over general KGs; no math-domain validation; requires hypergraph DB infrastructure not in arXMCP's stack. |
| **Col-Bandit** (arXiv:2602.02827) — Late-interaction token pruning | Optimization for ColBERT which arXMCP treats as Tier-6/v1.5. No value until ColBERT is actually adopted. |
| **LEMUR** (arXiv:2601.21853) — Learned multi-vector speedup | Same: depends on adopting multi-vector (ColBERT-style) retrieval first. Out of scope for the current pipeline. |
| **jina-embeddings-v3** (arXiv:2409.10173) — Task LoRA embeddings | Task LoRA adapters require fine-tuning infra arXMCP does not have. BGE-M3 already covers the retrieval axis. |
| **Arctic-Embed 2.0** (arXiv:2412.04506) | Good model but not math-specific; switching base embedder requires full re-embed + eval. The 2D-MRL technique (§2.6) is the transferable insight, not the specific model. |
| **Event-B Agent** (arXiv:2605.17475) — Formal model synthesis/repair | Event-B / B-method, not Lean 4. Architecture is analogous but the tool surface is domain-specific. |
| **SMART-SLIC RAG** (arXiv:2410.02721) — Domain RAG with KG+vector | Targets malware/anomaly detection text; not math or formal-proof retrieval. Low transfer value. |
| **StepChain GraphRAG** (arXiv:2510.02827) — BFS reasoning over KGs | General KG question answering; no formal math or Lean integration. |
| **Formal Theorem Proving by Rewarding LLMs Hierarchically** (arXiv:2411.01829) | Training-side RL paper; no new MCP tool or retrieval contribution. Interesting for agent design but out of server scope. |
| **Retrieval-Augmented TLAPS Proof Generation** (arXiv:2501.03073) | TLA+ not Lean; methodology is basic RAG without execution feedback loop. |
| **FormalAlign** (arXiv:2410.10135) — Alignment evaluation | Evaluates NL↔formal alignment but does not feed execution feedback back into the generation loop. Lower priority than PSV (§2.5). |
| **CktFormalizer** (arXiv:2605.07782) — Circuit formalization | Hardware domain (circuit representations in Lean 4); not math domain. The Lean compilation error pattern is the same, already captured in §2.1 and §2.4. |
| **LIR Workshop Position Paper** (arXiv:2511.00444) | Workshop overview, no technical content beyond signaling that late-interaction retrieval is maturing — captured in theme §4. |
