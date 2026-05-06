# 01 — Mission and Research Context

## The problem we are solving

A solo developer wants to run multi-agent Claude Code pipelines that attack
research-level mathematics problems. The agent roles parallel a code-review pipeline
they already use:

| Code pipeline role | Math pipeline role | What it does |
|---|---|---|
| Researcher (Opus) | Sketcher | Reads relevant prior work; produces a natural-language proof outline |
| Implementer (Sonnet) | Autoformalizer + Tactician | Translates the sketch to Lean 4 with `sorry` placeholders, then fills each subgoal |
| Adversarial critic (Sonnet) | Lean kernel | Verifies the proof; in math the LLM critic is structurally weak — Lean is the real critic |
| Fixer (Sonnet) | Fixer | Reads Lean's error message, retries with retrieval over similar lemmas |

Every Claude agent in this pipeline needs deep background context — definitions,
prior lemmas, related theorems, conventions in subfields like algebraic geometry or
hep-th. Without that context the agents produce nonsense at every stage. **arXMCP is
the substrate that gives every agent in the pipeline grounded access to a
research-math arXiv corpus.**

## Why math is structurally different from code

The code pipeline works because each agent has access to the same oracle: the test
suite. In math the only equivalent oracle is a proof assistant (Lean 4, Coq,
Isabelle). An LLM critic without one is just another LLM with the same blind spots —
the multi-agent debate literature confirms this empirically. Du et al.'s "Improving
Factuality and Reasoning via Multi-Agent Debate" and follow-ups show debate gives
modest gains on grade-school math and stalls on hard problems because agents converge
on shared mistakes ("echo chambers"). Process reward models (Math-Shepherd, "Let's
Verify Step-by-Step") help on olympiad-level arithmetic but don't transfer to
research mathematics where step-level correctness becomes subjective.

**Practical consequence: the adversarial critic role in a math pipeline is the
*least* valuable LLM role.** Lean's kernel error message is a better critic than
another Claude. The valuable roles all live *upstream* of verification — and they
all depend on having relevant prior work loaded.

## Why current arXiv-context tools fail for research math

Every existing arXiv MCP server (blazickjp/arxiv-mcp-server, daheepk/arxiv-paper-mcp,
forks thereof) treats papers as plain text via `pypdf` or similar. **This destroys
LaTeX equations.** For papers in math.AG, math.NT, hep-th, math-ph, the equations
*are the content*. Stripping them with PyPDF leaves an embedder seeing garbled glyphs
and mangled subscripts.

The deeper failure: existing tools also do not handle author-local macros. A paper
that does `\newcommand{\AA}{\mathcal{A}}` in the preamble and uses `\AA` 400 times
in the body looks, to a naive embedder, like noise. Two papers using the same
notation differently become indistinguishable. A retrieval system that doesn't
expand macros is structurally incapable of answering "find me papers about étale
cohomology" because half the papers write `\acute{e}tale`, `\'etale`, or
`\mathrm{\'et}` via custom macros.

## The Claude-ecosystem gap that motivates building this

NotebookLM lets a Gemini user drop a folder of PDFs and get grounded retrieval
across them via vector search. Anthropic does **not** ship a managed equivalent:

- **Claude Projects** (claude.ai web): stuffs files into context with prompt caching
  applied. Capped at roughly the model's context window. Not retrieval over
  millions of tokens; it's a bigger system prompt. Not accessible from Claude Code
  or the Messages API.
- **Anthropic Files API**: opaque-blob storage. Reference by `file_id`; the model
  sees an attachment. No chunking, no embedding, no similarity search.
- **No vector-store endpoint** (OpenAI ships `vector_stores`; Anthropic does not).
  Anthropic's stance is explicitly "bring your own retriever."

The recommended path inside the Claude ecosystem is therefore: build a local vector
DB, expose it via MCP, register the MCP in `~/.claude.json` so every agent — main
thread, sub-agents, skills — sees the same tool. **arXMCP is that build.**

## Survey of frontier math systems (for design awareness, not direct use)

These systems inform the pipeline shape arXMCP supports. They are not dependencies.

- **AlphaProof + AlphaGeometry 2** (DeepMind, IMO 2024 silver-medal). Two-component
  pipeline: a Gemini-derived autoformalizer translates natural-language problems
  into Lean, then an AlphaZero-style search agent attempts proofs, with RL from
  successful proof traces. Crucially **not just an LLM** — a search tree with Lean
  as the verifier-in-the-loop.
- **DeepSeek-Prover-V2** (April 2025, open weights; 7B and 671B). Subgoal
  decomposition: DeepSeek-V3 writes an informal sketch with `sorry`s in Lean 4, the
  prover model fills each `sorry`, successful chains feed RL training. The closest
  open-weights analogue to a researcher → implementer pattern. arXiv:2504.21801.
- **Goedel-Prover / Goedel-Prover-V2** (Princeton). Open expert-iteration: generate
  Lean proofs, filter by Lean kernel, fine-tune on accepted ones. The cleanest
  reference codebase for the prover-verifier loop.
- **Kimina-Prover** (Numina + Moonshot, April 2025). Qwen-based, Lean 4, RL-trained.
  Notable for "formal reasoning patterns": interleaved natural-language scratchpad
  and Lean tactics in one stream, then filtered by Lean.
- **Lean Copilot / LeanDojo** (CMU/Caltech). Infrastructure rather than a frontier
  model. LeanDojo exposes Lean's proof state to Python so retrieval-augmented LLMs
  can interact tactic-by-tactic. Most academic prover papers use LeanDojo as the
  harness.
- **Harmonic — Aristotle**. Closed system, claimed >90% on miniF2F. Architecture
  not published. Treat as research-stage with strong results but limited
  transparency.
- **Terence Tao's equational-theories project**. Distributed Lean formalization with
  LLM-assisted tactic suggestion. The most credible *deployed* human-in-the-loop
  multi-agent math workflow today and the closest real-world template for the
  pipeline arXMCP serves.

## Benchmarks worth knowing

- **miniF2F** (high-school + olympiad, Lean): mostly saturated by mid-2025.
- **PutnamBench** (Putnam problems in Lean): much harder, far from solved.
- **ProofNet** (undergraduate textbook theorems): standard test for autoformalization.
- **FrontierMath** (Epoch AI, research-grade): scores still in single digits as of
  late 2025. **This is where arXMCP's target users operate.** Don't expect full
  automation; build a power tool for a human-in-the-loop.

## Implication for the pipeline arXMCP serves

- Different agent roles want different retrieval granularities:
  - **Sketcher** wants paper abstracts and section summaries.
  - **Autoformalizer** wants theorem statements with their context (definitions,
    notation).
  - **Tactician** wants theorem+proof chunks plus exact lemma-name lookup over
    Mathlib-style symbols.
  - **Fixer** wants display-equation similarity and version-diff (v1 vs v3 of the
    same paper, since v1 often has the cleaner statement and v3 has the corrected
    proof).
- The retrieval system therefore needs **hierarchical indexing** — not a single flat
  chunk store. (See [04-parsing-and-chunking.md](04-parsing-and-chunking.md).)
- Adversarial critique by an LLM is a low-priority feature. If we add a "critic"
  tool, it's a thin wrapper around Lean kernel output, not a free-running LLM.

## Design philosophy

1. **Math fidelity over coverage.** Better to index 50,000 papers with macros
   expanded and equations preserved than 500,000 with PyPDF mangling.
2. **Determinism over cleverness.** Every byte the MCP server returns must be
   reproducible bit-for-bit across calls — this is what enables prompt-cache reuse
   across agents (see [07-multi-agent-caching.md](07-multi-agent-caching.md)).
3. **Single source of truth for the corpus.** One ingestion pipeline, one storage
   layer, one MCP server process. The "shared NotebookLM substrate" property
   collapses if any agent ever sees a different view.
4. **Local-first.** No paid cloud services in the critical path. The system must
   work offline once seeded.
5. **Power tool, not autopilot.** v1 makes a single mathematician + their agent
   pipeline materially more productive. v1 does NOT try to fully automate
   research-math proof discovery — that's the FrontierMath frontier and not a
   solved problem.
