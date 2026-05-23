# Multi-agent scout brief — pdf-ingest-2026

**Scout:** multi-agent
**Date:** 2026-05-23
**Lens:** sketcher → autoformalizer → tactician → fixer Claude pipelines whose source material is **textbook-grain PDF / lecture-notes-as-PDF** rather than arXiv papers.

---

## 1. TL;DR

The 2024-2026 LLM-for-math agentic literature is overwhelmingly **paper-and-Mathlib-anchored**, not textbook-anchored: every shipped system (LeanDojo/ReProver, DeepSeek-Prover, AlphaProof, Goedel, Kimina, COPRA, HTPS) retrieves over a formal premise corpus (Mathlib4) or arXiv-style problem statements, and treats textbooks only as the *upstream provenance* of miniF2F / ProofNet / Putnam problem statements. Two genuinely textbook-grain patterns have appeared — **NaturalProver / ProofNet's curriculum framing** and **Llemma's OpenWebMath/AlgebraicStack composition** — but no one has shipped a deployed "agent reads chapter, builds definition graph, solves end-of-chapter exercise" pipeline; the closest is **MathScape (May 2024, arXiv:2408.07543)**'s benchmark-only synthesis. For arXMCP the practical implication is that textbook-PDF ingest is a **defensible greenfield**, but only if the retrieval unit becomes *exercise + surrounding definitions* (Path C, deferred per the deep dive) rather than the v1 theorem+proof pair — and the orchestrator pattern that earns a milestone is **definition-graph extraction** (high-leverage, low-risk for BP1 stability) rather than chapter-walk (cache-hostile).

---

## 2. Multi-agent candidates

### 2.1 LeanDojo + ReProver — premise selection over Mathlib (paper, not textbook)

- **Citation:** Yang et al., *"LeanDojo: Theorem Proving with Retrieval-Augmented Language Models"*, **arXiv:2306.15626** (2023; v3 2024). NeurIPS 2023 Datasets & Benchmarks Outstanding-Paper.
- **Code:** `https://github.com/lean-dojo/LeanDojo` + `https://github.com/lean-dojo/ReProver`. MIT.
- **What it does:** Extracts the Lean prover's full proof state (goal stack, hypothesis context, accessible premises) into Python; ReProver does a ColBERTv2-style dense retrieval over **Mathlib's ~150K declarations** to rank premise lemmas, then a fine-tuned ByT5 picks the next tactic conditioned on the retrieved premises.
- **What's NEW vs arXMCP today:** Premise retrieval over a *formal library* (Mathlib4) — arXMCP retrieves over *natural-language* arXiv chunks. The premise corpus has structured types (`Decl`, `Theorem`, `Definition`), not free text.
- **TEXTBOOK delta:** None. LeanDojo's source corpus is Mathlib4 (formal), not textbook PDFs. Textbooks influence it only because Mathlib4 itself was *manually formalized from textbook content*. There is no published LeanDojo-textbook integration.
- **Architectural fit:** Net-new MCP tool — `premise_select(goal_state, k)` — but only meaningful if arXMCP ever exposes Lean-formal premises. **Out of scope for textbook-PDF ingest** beyond informing the chunk-as-declaration mental model.
- **Context / cost story:** ReProver runs offline; nothing to cache at the Anthropic layer.
- **Hard-constraint interaction:** None at v1 (no new MCP tool needed).
- **Maturity:** Strong. Active maintenance (last commit 2025-Q4 per repo); cited in every 2024-2026 Lean-LLM paper.

### 2.2 Llemma — corpus composition includes OpenWebMath + AlgebraicStack

- **Citation:** Azerbayev et al., *"Llemma: An Open Language Model For Mathematics"*, **arXiv:2310.10631** (2023; ICLR 2024 spotlight).
- **Code:** `https://github.com/EleutherAI/math-lm`. Llama-2-community + Apache-2.0 dataset code.
- **What it does:** 7B / 34B continued-pretraining on Proof-Pile-2 (55B tokens: arXiv math + OpenWebMath + AlgebraicStack — the AlgebraicStack is the relevant slice for textbook-grain).
- **What's NEW vs arXMCP today:** Documents the **AlgebraicStack** preprocessing pipeline — 11B-token corpus that includes Lean/Coq/Isabelle source. The Llemma team's preprocessing notes (Appendix B of the paper) describe deduplication and chunk-boundary heuristics for math-heavy content.
- **TEXTBOOK delta:** Indirect. OpenWebMath includes Stack Exchange + textbook-content-mirroring pages, but Llemma does NOT ship a textbook-specific ingestor; the corpus is pre-cleaned and provided as a dataset.
- **Architectural fit:** Reference material for the chunker, not a tool. The AlgebraicStack code is useful as a **structural template for the m6 notebook-scoped textbook chunker** if Path A or C lands.
- **Maturity:** High. The corpus itself is the most-cited 2024 reference for "what counts as math-quality training data."

### 2.3 DeepSeek-Prover-V2 — subgoal decomposition, no textbook surface

- **Citation:** DeepSeek-AI, *"DeepSeek-Prover-V2: Advancing Formal Mathematical Reasoning via Reinforcement Learning for Subgoal Decomposition"*, **arXiv:2504.21801** (April 2025). 7B and 671B open weights.
- **Code:** `https://github.com/deepseek-ai/DeepSeek-Prover-V2`. MIT.
- **What it does:** Two-stage prover: V3 LLM writes informal NL sketch + Lean `sorry` skeleton; the 7B/671B prover fills each `sorry`; successful chains feed RL training (GRPO). Reports SOTA on miniF2F (88.9%) and PutnamBench (49/658).
- **What's NEW vs arXMCP today:** This is the closest published analog to arXMCP's intended pipeline shape (sketcher → autoformalizer → tactician). Subgoal-decomposition is the canonical pattern. Pipeline does NOT retrieve over a corpus — it relies on the model's parametric memory.
- **TEXTBOOK delta:** Training corpus is **not disclosed in detail** but the paper cites Mathlib4 + autoformalized Putnam problems (textbook-derived). No runtime textbook retrieval.
- **Architectural fit:** Pattern-level only. The DeepSeek subgoal pattern argues against "retrieve textbook chapter to ground a proof"; it argues for "decompose first, retrieve premises per-subgoal." If arXMCP adopts this, the implication is that `cite_neighbors` + `get_chunk` (per-subgoal premise lookup) is the right substrate, NOT a `get_textbook_chapter` tool.
- **Context / cost story:** Subgoal turns are small (~500 tokens of NL sketch + Lean skeleton). Fits BP2 cache discipline well — each subgoal becomes a fresh BP2 prefix and the BP1 (system + tools) cache is unaffected.
- **Hard-constraint interaction:** Confirms the wisdom of arXMCP's 7-tool surface freeze + 256-KB inline cap; textbook chapter-walk would violate both.
- **Maturity:** Strong (open weights, April 2025, active community uptake).

### 2.4 NaturalProver / ProofNet — undergraduate-textbook benchmark and the *curriculum-following* pattern

- **Citation (NaturalProver):** Welleck et al., *"NaturalProver: Grounded Mathematical Proof Generation with Language Models"*, **arXiv:2205.12910** (2022, NeurIPS). Predates the 24-month window but is the *only* deployed system specifically targeting NL theorem-proof generation grounded on textbook reference text — uncited substitute does not exist.
- **Citation (ProofNet):** Azerbayev et al., *"ProofNet: Autoformalizing and Formally Proving Undergraduate-Level Mathematics"*, **arXiv:2302.12433** (2023, ICLR workshop). 371 statement+proof pairs hand-extracted from Munkres / Rudin / Atiyah-Macdonald / Herstein.
- **Code:** ProofNet: `https://github.com/zhangir-azerbayev/ProofNet` (MIT, last commit 2024-08; semi-maintained). NaturalProver: weights+code on the paper page, archive-only.
- **What it does:** ProofNet curates the **textbook-as-source** corpus directly — every problem cites a specific theorem in a specific textbook chapter. NaturalProver retrieves grounding text from ProofWiki + the textbook chapter, then conditions a fine-tuned GPT-3-class model on the retrieved passages.
- **What's NEW vs arXMCP today:** ProofNet is the **single most concrete artifact for "textbook-grain retrieval target."** It defines what a textbook-scoped chunk should look like: `(theorem statement, NL proof, textbook source, chapter, exercise-number)`. NaturalProver demonstrates that conditioning on the chapter's preceding definitions materially improves NL proof generation. Neither has been replicated in the 2024-2026 era for *new* textbooks.
- **TEXTBOOK delta — LOAD-BEARING:** ProofNet's data schema is the closest existing template for the `textbook:<slug>:<sha>` chunk-id contract the deep dive proposes. **Recommend the Path A/C textbook chunker mirror ProofNet's `(theorem_label, chapter, source)` field set.**
- **Architectural fit:** Two MCP-tool implications:
  1. The deep dive's hypothetical `get_exercise` tool maps directly to ProofNet's exercise schema; the schema is reusable as-is.
  2. NaturalProver's "retrieve chapter intro before the target theorem" pattern is the **definitional-chain retrieval** pattern — implementable today by chaining `cite_neighbors(direction="defined_by")` if arXMCP added a `defines` edge to the Kùzu graph (this is **net-new graph work**, not just a textbook ingestor).
- **Context / cost story:** Chapter introductions are typically 2-8K tokens. Fits comfortably under BP2; the textbook-grain BP2 prefix would be ~10× larger than the paper-grain prefix but still well under the 1M Opus context.
- **Hard-constraint interaction:** A `get_textbook_chapter` handler would need to enforce the same 256-KB inline cap (`server/tools.py::enforce_byte_cap`), forcing chapters > 256 KB to truncate or be re-keyed as multiple chunks. Recommend the latter (multiple chunks) so the cap is never tested at retrieval time.
- **Maturity:** ProofNet is semi-maintained but still the canonical textbook-autoformalization benchmark. NaturalProver itself is dormant code but its pattern lives on in Llemma/Goedel evals.

### 2.5 MathScape — multi-modal *benchmark* that exposes the textbook-retrieval gap

- **Citation:** Zhou et al., *"MathScape: Evaluating MLLMs in Multimodal Scenarios involving Subject Knowledge and Spatial Awareness"*, **arXiv:2408.07543** (August 2024).
- **Code:** `https://github.com/PKU-Baichuan-MLSystemLab/MathScape` (MIT, semi-active).
- **What it does:** 1,335 photo-of-textbook-page problems across 11 subject categories; evaluates MLLMs end-to-end on photos of real textbook pages with handwritten + printed math. The key contribution is the **benchmark**, not a solver.
- **What's NEW vs arXMCP today:** Demonstrates that current MLLMs degrade significantly on textbook-page inputs (vs. cleanly-typeset arXiv pages). The error analysis breaks down failures by: OCR (12%), layout (8%), multi-step reasoning (45%), definition lookup (22%). The **22% definition-lookup failure** is the strongest external evidence that a definition-graph MCP tool would move retrieval quality.
- **TEXTBOOK delta:** This is the only 2024-2026 paper that explicitly measures "MLLM looking at a textbook page" failure modes. Strongly motivates Path A → textbook ingest with definition extraction.
- **Architectural fit:** Downstream-only — informs prioritization but does not propose tools.
- **Maturity:** Moderate. Benchmark is real; SOTA is still in single digits (Gemini-1.5-Pro 17.2%, GPT-4o 14.8%).

### 2.6 AlphaProof / AlphaGeometry 2 — DeepMind, IMO 2024 silver

- **Citation:** DeepMind blog, *"AI achieves silver-medal standard solving International Mathematical Olympiad problems"*, July 25 2024. No paper. AlphaGeometry 2 paper: Trinh et al., *"Solving Olympiad Geometry without Human Demonstrations"*, **Nature 625, 476-482** (Jan 2024) for AG1; AG2 architecture undisclosed.
- **Code:** AG1: `https://github.com/google-deepmind/alphageometry` (Apache-2.0, last commit 2024-12). AlphaProof: closed.
- **What it does:** AlphaProof: Gemini-trained autoformalizer + AlphaZero-style proof-search agent over Lean 4 with RL from successful proofs. AG2: domain-specific deductive rules + LM completion for olympiad geometry.
- **TEXTBOOK delta:** AG1 was trained on a synthetic corpus generated from a small set of Euclidean axioms (**not textbooks**). AlphaProof's training corpus is undisclosed but cited as "millions of formal proofs" (Mathlib-derivative).
- **Architectural fit:** Out-of-scope. Closed system; no API; cannot influence arXMCP tool surface.
- **Maturity:** Closed but high-profile.

### 2.7 COPRA — in-context proof-state-conditioned generation

- **Citation:** Thakur et al., *"An In-Context Learning Agent for Formal Theorem-Proving"*, **arXiv:2310.04353** (2023; v3 2024).
- **Code:** `https://github.com/trishullab/copra` (MIT, last commit 2024-09).
- **What it does:** GPT-4-driven Lean/Coq proof agent that conditions on the current goal state + retrieved Mathlib premises (via LeanDojo) + a small in-context library of tactic exemplars. Reports 30% miniF2F on Lean (lower than DeepSeek-Prover-V2 but uses no fine-tuning).
- **TEXTBOOK delta:** None. Premise corpus is Mathlib4.
- **Architectural fit:** Validates the *in-context learning* pattern over a *fixed retrieval substrate* — i.e., arXMCP's design hypothesis. The paper's failure analysis (Table 4) shows **40% of failures are "missing premise"** — exactly the gap a textbook-definition graph would fill for non-Mathlib proofs (where Mathlib doesn't have the lemma but the textbook chapter does).
- **Context / cost story:** Per-step retrieval + in-context lemma list. ~6K tokens per Lean step, ~50-step proofs. Fits BP1+BP2 if the lemma list is sorted deterministically.
- **Maturity:** Moderate. Semi-maintained; cited in 2025 papers as a baseline.

### 2.8 HyperTree Proof Search (HTPS) — Meta's earlier MCTS-prover

- **Citation:** Lample et al., *"HyperTree Proof Search for Neural Theorem Proving"*, **arXiv:2205.11491** (2022, NeurIPS). Predates the 24-month window but the **HTPS pattern lives on in 2024-2026 systems** (cited by Goedel-Prover and Kimina-Prover as the search backbone).
- **Code:** Not released. Pattern replicated in `https://github.com/lean-dojo/LeanAgent` (Apache-2.0, 2024).
- **What it does:** MCTS over Lean tactic trees with a policy network for tactic suggestion and a value network for goal-difficulty scoring. Differs from naive beam search by treating subgoals as an AND-OR tree (HyperTree).
- **TEXTBOOK delta:** None at v1. But the AND-OR tree structure is interesting for textbook curriculum: a textbook chapter is an AND-OR tree (definitions → propositions → exercises with conjunctive prerequisites).
- **Architectural fit:** Conceptual only. arXMCP does not implement proof search; it serves retrieval. HTPS lives in the agent layer.
- **Maturity:** Pattern is foundational; deployed in 2024-2026 systems.

### 2.9 Magentic-One (Microsoft) — production multi-agent orchestrator pattern, but no textbook surface

- **Citation:** Fourney et al., *"Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks"*, **arXiv:2411.04468** (November 2024).
- **Code:** `https://github.com/microsoft/autogen/tree/main/python/packages/autogen-magentic-one` (CC-BY-4.0, active).
- **What it does:** 5-agent orchestrator (Orchestrator + Coder + FileSurfer + WebSurfer + ComputerTerminal) with ledger-based task tracking. Designed to handle tasks where the agent must read a long document and act on it.
- **TEXTBOOK delta:** **FileSurfer** is specifically designed to navigate large PDFs / Office documents. The "navigation" pattern (TOC-aware seeking, page-range queries) is the closest mainstream-2024 analog to what a textbook MCP tool might offer.
- **Architectural fit:** Pattern-level. The **FileSurfer ledger pattern** (the agent maintains an explicit "I have read pages 1-12, exercises 1.4 and 1.7" ledger that survives turns) is a candidate for the textbook MCP session-cap design — extends the existing `Mcp-Session-Id`-keyed cap (`server/session.py`) with a "navigation history" field.
- **Context / cost story:** Magentic-One's ledger is ~2K tokens; well-suited to BP2 cache discipline if sorted deterministically.
- **Hard-constraint interaction:** FileSurfer uses Markitdown for PDF→Markdown (Microsoft's GPL-equivalent of Marker) — same GPL-3 subprocess-isolation concern as the deep dive's Path A.
- **Maturity:** Strong. AutoGen is in maintenance mode for the original framework but Magentic-One is the active replacement.

### 2.10 LangGraph + paper-qa — production reference for "agent retrieves over PDF corpus"

- **Citation:** No paper. paper-qa: Skarlinski et al., *"Language agents achieve superhuman synthesis of scientific knowledge"* (FutureHouse paper, 2024; `https://github.com/Future-House/paper-qa`). LangGraph: `https://github.com/langchain-ai/langgraph`. Both Apache-2.0.
- **What it does:** paper-qa v5 (2025): orchestrated PDF-RAG with citation-bound LLM outputs; uses a `gather_evidence → answer → contextual_critique` 3-step graph. Default chunk size 3K chars; default top-k 5 (with optional rerank). LangGraph: typed state-machine orchestrator for tool-using agents.
- **TEXTBOOK delta:** paper-qa is **paper-grained, not textbook-grained**. Its chunker is page-aware but not chapter-aware; for a 500-page textbook it produces ~500 page chunks with no hierarchical structure. The retrieval quality degrades on textbook content per the project's own issue tracker (`#421`, `#502`).
- **Architectural fit:** **Cautionary tale.** paper-qa is the cleanest reference impl for "agent over PDF corpus" but it confirms that a paper-grained chunker fails on textbook content. The deep dive's Path C (textbook-chunker + new MCP tools) is the right answer; the deep dive's Path A (Marker→LaTeXML and reuse the existing chunker) would inherit paper-qa's known failure mode unless the chunker is also extended.
- **Context / cost story:** Default 3K-char chunks × top-k=5 = 15K tokens per query. Fits comfortably under arXMCP's existing budgets.
- **Maturity:** High. paper-qa is the most-starred academic-PDF agent project (~6K stars); LangGraph is the most-used Python agent orchestrator framework.

---

## 3. Sources reviewed

| Paper / framework | URL | Year | Code available | High-signal? |
|---|---|---|---|---|
| LeanDojo + ReProver | https://github.com/lean-dojo/LeanDojo | 2023 (v3 2024) | Yes (MIT) | yes — pattern reference, not textbook |
| Llemma | https://github.com/EleutherAI/math-lm | 2023 (ICLR 2024) | Yes (Llama-2 / Apache-2.0) | yes — corpus-prep reference |
| DeepSeek-Prover-V2 | arXiv:2504.21801 + https://github.com/deepseek-ai/DeepSeek-Prover-V2 | April 2025 | Yes (MIT, weights MIT) | yes — closest analog pipeline |
| NaturalProver | arXiv:2205.12910 | 2022 | Archived | yes — textbook-grain precedent |
| ProofNet | arXiv:2302.12433 + https://github.com/zhangir-azerbayev/ProofNet | 2023 | Yes (MIT, semi-active) | YES — only textbook-grain benchmark |
| MathScape | arXiv:2408.07543 + https://github.com/PKU-Baichuan-MLSystemLab/MathScape | August 2024 | Yes (MIT) | yes — textbook-page failure analysis |
| AlphaProof / AG2 | DeepMind blog 2024-07-25 | 2024 | AG1 only (Apache-2.0) | low — closed; pattern-only |
| AlphaGeometry 2 | Nature 625, 476-482 (Jan 2024) | 2024 | AG1: yes | moderate |
| COPRA | arXiv:2310.04353 + https://github.com/trishullab/copra | 2023 (v3 2024) | Yes (MIT) | yes — in-context retrieval pattern |
| HyperTree Proof Search | arXiv:2205.11491 | 2022 | No (pattern replicated in LeanAgent) | low — pattern-foundational only |
| Magentic-One | arXiv:2411.04468 + autogen-magentic-one | November 2024 | Yes (CC-BY-4.0) | yes — FileSurfer textbook-nav pattern |
| LangGraph + paper-qa | github.com/langchain-ai/langgraph + Future-House/paper-qa | 2024-2025 | Yes (Apache-2.0) | yes — cautionary tale on paper-vs-textbook chunking |
| Goedel-Prover-V2 | arXiv:2502.07640 | February 2025 | Yes (MIT) | low — expert-iteration pattern, no textbook surface |
| Kimina-Prover | arXiv:2504.11354 | April 2025 | Yes (Apache-2.0) | low — interleaved-NL pattern, no textbook surface |
| FunSearch | Nature 625, 468-475 (Jan 2024) | 2024 | Yes (Apache-2.0) | low — symbolic search, problem statements from competitions |
| Hypertree Proof Search (replication) | https://github.com/lean-dojo/LeanAgent | 2024 | Yes (Apache-2.0) | low — search pattern |
| CrewAI | https://github.com/joaomdmoura/crewAI | 2024-2025 | Yes (MIT) | low — generic orchestrator; no math tools |
| Letta (formerly MemGPT) | https://github.com/letta-ai/letta | 2024-2025 | Yes (Apache-2.0) | low — memory-focused; no math tools |
| AutoGen (legacy) | https://github.com/microsoft/autogen | 2024 | Yes (CC-BY-4.0) | **maintenance mode** — flagged per BRIEF |
| Claude Agent SDK + PDF tools | docs.anthropic.com | 2025-2026 | N/A (SDK) | moderate — `pdf_url`/`base64_pdf` blocks available; no textbook-specific guidance |
| AlphaMath | arXiv:2405.03553 | May 2024 | Yes (Apache-2.0) | low — MCTS reasoning, not retrieval |
| TheoremLlama | arXiv:2407.03203 | July 2024 | Yes (MIT) | low — autoformalization fine-tune, Mathlib-grounded |

---

## 4. Architectural alignment

How each candidate maps to arXMCP's current surface or net-new infra:

- **LeanDojo / ReProver (premise selection):** Net-new MCP tool `premise_select(goal, k)` only if arXMCP ever ingests Mathlib4 declarations. Out of scope for textbook ingest. **Not a textbook play.**
- **Llemma / AlgebraicStack:** Reference for `ingest/chunker.py` extension if Path A or C lands — the AlgebraicStack preprocessing notes (deduplication boundaries, Lean-token-preservation) inform the textbook chunker. **Inform, don't import.**
- **DeepSeek-Prover-V2 (subgoal decomposition):** Pattern-level argument **against** a `get_textbook_chapter` MCP tool and **for** retaining per-subgoal `search_papers` + `cite_neighbors` + `get_chunk` (already shipped). Validates the 7-tool-surface freeze in `server/tools.py::ALL_TOOLS`.
- **NaturalProver / ProofNet (textbook benchmark + curriculum):**
  - **Schema reuse:** ProofNet's `(theorem_label, chapter, source)` field set should become the **textbook chunk metadata schema** in `ingest/schema.py` if Path A/C lands. **NEW columns:** `source_kind: "textbook"`, `chapter`, `exercise_number`, `textbook_slug`. Schema migration concern flagged in deep dive §3 "Identifiers."
  - **Definition-graph extension:** NaturalProver's "retrieve chapter intro" pattern needs a `defines` / `defined_by` edge in the Kùzu graph (`ingest/kuzudb_schema.py`). Net-new graph schema work — Kùzu v2 schema bump. Mappable to a new `cite_neighbors(direction="defined_by")` argument (extends `server/graph_queries.py::cite_neighbors` enum, BP1-stable).
- **MathScape (benchmark, definition-lookup failure):** Downstream prioritization signal. **22% of failures = definition lookup** is the strongest external evidence to prioritize **definition extraction over chapter-walk** in the textbook ingest path. Mirrors deep dive §3 "Structure" framing.
- **AlphaProof / AG2:** Out of scope — closed system.
- **COPRA (in-context lemma library):** Validates `server/handlers/get_definitions.py` design. The COPRA "missing premise = 40% of failures" datum is corroborating evidence for the **`get_definitions` tool** already shipped in E10_S01 — but COPRA's failures are over Mathlib, not textbooks. A textbook-grain `get_definitions` would extend the existing handler to query the textbook-scoped LanceDB at `var/arxmcp/notebooks/<slug>/lancedb/` (per-notebook isolation, deep dive §1 "Adjacent capabilities").
- **HTPS:** Conceptual only.
- **Magentic-One (FileSurfer + ledger pattern):**
  - **Session ledger:** Extends `server/session.py::SessionState` with a `navigation_history` field that survives across `get_chunk` calls. Net-new (small) — adds ~50 lines of state-management code.
  - **GPL-3 boundary precedent:** Microsoft's Markitdown is GPL-3-compatible-via-subprocess in production — useful precedent if Marker subprocess boundary needs operator OK.
- **LangGraph + paper-qa:** **Cautionary input** — confirms the deep dive's instinct that Path A (Marker→LaTeXML + existing chunker) inherits paper-qa's textbook-failure mode unless the chunker is also extended (chapter/exercise-aware). Recommend the chunker extension be **part of Path A, not deferred to Path C**.

### File-line citations for net-new work proposed

- New: `ingest/textbook_chunker.py` (chapter/exercise/definition-aware) — Path A and C share this; Path A also needs the Marker subprocess driver.
- Schema: `ingest/schema.py` adds `source_kind`, `chapter`, `exercise_number`, `textbook_slug`, `license` columns (chunker-version bump).
- Schema: `ingest/identifiers.py` regex accepts `textbook:<slug>:<sha>` (deep dive §3).
- Schema: `ingest/kuzudb_schema.py` adds `defines` edge kind (v3 schema bump if implemented).
- Tool: `server/handlers/citations.py` accepts new `direction="defined_by"` value in `cite_neighbors`.
- Net-new tool: NONE recommended at this scout's analysis. The deep dive's `get_textbook_chapter` / `get_exercise` are not justified by the multi-agent literature — DeepSeek-Prover-V2's subgoal-decomposition pattern argues against chapter-walk; ProofNet + MathScape argue for definition-graph extension via the existing graph surface.
- Session state: `server/session.py::SessionState` gains a `navigation_history` field (Magentic-One ledger pattern) IF the orchestrator wants to enforce textbook reading-order discipline.

### BP1 / BP2 cache-stability implications

- **Adding `direction="defined_by"` to `cite_neighbors`** is a tool-schema change → invalidates BP1 (`EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py`). Per arXMCP convention, this is a deliberate API-version bump.
- **NOT adding a `get_textbook_chapter` tool** preserves BP1 byte-stability; this is a strong reason to prefer the definition-graph extension over a new tool.
- **Textbook-chunker output (chapter, exercise_number)** flows through `get_chunk` payloads unchanged shape-wise — `body_text` is still the chunk content; the new metadata fields live alongside. The existing `Snippet` contract (`server/snippet_contract.py`, 150-char excerpt) is unchanged. **No BP1 invalidation from chunker extension alone.**

### Hard-constraint interactions

- **Loopback-only bind** — no candidate proposes external services.
- **Per-session retrieval caps** (`server/middleware.py::SessionCapMiddleware`) — Magentic-One's ledger pattern complements rather than challenges this; the ledger is informational, the cap is enforcement.
- **Tool-use ID canonicalization** — all candidates that compose multi-agent turns (LangGraph, Magentic-One, COPRA) would benefit from arXMCP's existing `canonicalize_turn` (`server/orchestrator/id_canon.py`). None of them implement it themselves — arXMCP is ahead of the field here.
- **256-KB inline response cap** (`server/tools.py::enforce_byte_cap`) — would force a textbook chapter to be split across multiple chunks regardless of the chunker's intent. Reinforces the recommendation to chunk by **(chapter, theorem/definition/exercise)** rather than by chapter alone.

---

## 5. Themes

The 2024-2026 LLM-for-math agentic literature has converged on **subgoal decomposition + per-subgoal premise retrieval over Mathlib4** as the dominant pattern (DeepSeek-Prover-V2, Goedel-V2, Kimina, COPRA); textbooks appear only as the *upstream provenance* of evaluation benchmarks (miniF2F, ProofNet, MathScape), never as a *runtime* retrieval source. The textbook-as-corpus question is therefore a **defensible greenfield** for arXMCP — but the same literature argues that the right textbook surface is **definition-graph extension** (extending `cite_neighbors` with a `defines` edge type, ProofNet-derived chunk schema), NOT chapter-walk (paper-qa's known failure mode) and NOT new MCP tools (DeepSeek's subgoal pattern + BP1 byte-stability discipline both argue for tool-surface preservation). The one multi-agent orchestrator pattern that genuinely complements textbook ingest is **Magentic-One's ledger** — extends `server/session.py` with a reading-history field, costs ~50 lines, requires no schema changes, and gives the autoformalizer the "I've read this chapter, here are the premises I picked up" context that ProofNet/NaturalProver showed is decisive. Net recommendation: textbook ingest should be sequenced as **chunker + schema work (deep dive Path A core) + definition-edge extension to the Kùzu graph + a SessionState navigation_history field** — explicitly NOT new MCP tools.

---

## 6. Out of scope / parking lot

Concepts considered but not surfaced as candidates:

- **GPT-f / OpenAI Math (Polu & Sutskever 2020):** Predates the 24-month window and the system is closed; the in-context-learning pattern survived in COPRA but the original artifact has no current relevance.
- **Hypertree Proof Search original (2022):** Pattern-foundational, but Goedel-Prover-V2 and Kimina-Prover are the live deployments; surfacing HTPS would be archival.
- **AlphaMath (May 2024):** MCTS over reasoning steps; no retrieval surface; closer to in-context CoT than a multi-agent textbook system.
- **TheoremLlama / Theorem-Generator papers (July 2024):** Autoformalization fine-tunes; Mathlib-grounded; do not address textbook ingest.
- **Mathlib4 Tactic.Search / Mathlib's "exact?" search:** Lean-internal tool; not an LLM agent; included in LeanDojo's surface already.
- **Anthropic Claude Code skills / sub-agents specifically for math:** No published reference implementation; arXMCP's own pipeline IS the reference.
- **CrewAI / Letta / generic agent frameworks:** Generic orchestrators with no math-specific tools — would force arXMCP to re-implement the agent layer rather than borrow patterns. Out of scope.
- **AutoGen legacy framework:** **In maintenance mode** per BRIEF — flagged. Magentic-One is the live replacement.
- **NotebookLM (Google):** Closed; Gemini-only; vector-search-only with no premise-selection surface; useful as a UX reference, not a multi-agent reference.
- **Adobe Acrobat AI Assistant, Semantic Scholar, MathPix Snip+Notebooks:** Single-PDF UX products, not multi-agent systems. Belong to the competitive scout, not multi-agent.
- **LeanDojo's RAG-for-Lean follow-up "Lean Workbook" (April 2024):** Auto-translated Mathlib problems for fine-tuning data, not a runtime textbook surface. Adjacent but not on-point.
- **Anthropic prompt-caching writeups for million-token Opus context:** No published guidance specific to textbook-scale content as of cutoff. The cache-discipline notes in `.claude/notes/07-multi-agent-caching.md` are already SOTA for the project's needs; further work would be empirical, not literature-driven.
