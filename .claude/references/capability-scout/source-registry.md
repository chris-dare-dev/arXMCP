# Capability-scout source registry

**Purpose:** the curated list of sources each scout reaches for first.  Update here when a new venue / repo / system proves valuable.

This file is loaded by individual scouts at Phase 1 start (NOT by the main session at command-load time).  Keep entries one-line-per-source so a scout can grep this file for relevant rows when it has a narrow topic.

arXMCP is a **local-first MCP server** that exposes a research-mathematics arXiv corpus (`math.AG`, `math.NT`, `math-ph`, `hep-th`) to a multi-agent Claude **sketcher → autoformalizer → tactician → fixer** pipeline.  Every source class below is scoped to that mission: retrieval quality, math-aware ingestion, the MCP tool surface, agent-harness context engineering, the citation graph, and verification/proof tooling.

---

## Comparable systems (retrieval / MCP / math-search product capability)

| System | URL | Why it matters | Notable capabilities to study |
|---|---|---|---|
| arxiv-mcp-server (community) | https://github.com/blazickjp/arxiv-mcp-server | The obvious point of comparison — an MCP server over arXiv | Tool surface, search ergonomics, paper-fetch flow (study-only — no-fork) |
| Semantic Scholar / S2 API | https://www.semanticscholar.org/product/api | Large-scale scholarly graph + retrieval API | Citation graph depth, TLDR snippets, embeddings (SPECTER2), bulk endpoints |
| zbMATH Open | https://zbmath.org/ | Open abstracting/indexing service for pure math | Math-aware search, MSC classification, formula search |
| arXiv full-text + ar5iv | https://ar5iv.labs.arxiv.org/ | HTML rendering of arXiv LaTeX (theorem structure preserved) | LaTeXML output as structured HTML, theorem/proof DOM |
| LeanSearch / Loogle / Moogle | https://leansearch.net/ , https://loogle.lean-lang.org/ | Search over Lean mathlib statements | Natural-language → formal-statement retrieval, type-directed search |
| nLab | https://ncatlab.org/ | Community math wiki with dense cross-linking | Concept-graph navigation, definition density |
| Connected Papers / ResearchRabbit | https://www.connectedpapers.com/ | Citation-graph exploration UIs | Neighborhood expansion, prior/derivative-work framing |
| Elicit / Consensus | https://elicit.com/ | LLM-over-literature research assistants | Claim extraction, evidence synthesis, retrieval-then-read flows |
| Context7 (doc-MCP) | https://github.com/upstash/context7 | An MCP server serving versioned docs to coding agents | MCP packaging, freshness model, snippet contracts |

**How to mine these:** each scout WebFetches the system's public docs / API reference / changelog — focus on the *capability surface* (what an agent can ask for and what it gets back), not marketing.  arXMCP has no UI, so UI/UX is NOT the axis — the axis is "what retrieval / tool / context capability does a comparable system expose that arXMCP doesn't."

---

## Research-frontier venues (arXiv + journals + workshops)

| Venue | URL pattern | Coverage |
|---|---|---|
| arXiv cs.IR (Information Retrieval) | https://arxiv.org/list/cs.IR/recent | Dense/sparse retrieval, reranking, RAG — most directly applicable |
| arXiv cs.CL (Computation & Language) | https://arxiv.org/list/cs.CL/recent | Embeddings, long-context, retrieval-augmented generation |
| arXiv cs.LG (Machine Learning) | https://arxiv.org/list/cs.LG/recent | Embedding-model training, contrastive methods |
| arXiv cs.AI (Artificial Intelligence) | https://arxiv.org/list/cs.AI/recent | Agentic systems, tool-use, planning |
| arXiv cs.LO (Logic in CS) | https://arxiv.org/list/cs.LO/recent | Autoformalization, proof assistants, formal verification |
| arXiv cs.DL (Digital Libraries) | https://arxiv.org/list/cs.DL/recent | Scientific-document processing, citation analysis |
| arXiv math.HO (History & Overview) | https://arxiv.org/list/math.HO/recent | Surveys; math-knowledge-organization papers land here |
| ACL / EMNLP / SIGIR / NeurIPS / ICLR proceedings | https://aclanthology.org/ , https://dl.acm.org/conference/sigir | Peer-reviewed retrieval + NLP + ML work |
| AITP (AI for Theorem Proving) | http://aitp-conference.org/ | The dedicated venue for LLM × formal mathematics |
| Journal of Automated Reasoning | https://www.springer.com/journal/10817 | Formal-methods + proof-automation research (abstract-only) |

**Time-window discipline:** scouts cite work from the **last 24 months** by default.  Older work only when it is genuinely foundational (e.g. BM25, RRF, ColBERT, the original BGE/E5 papers) AND not already documented in `.claude/notes/10-references-and-prior-art.md`.

---

## OSS / GitHub trends (retrieval infra + math tooling)

| Project | URL | License | Why it matters |
|---|---|---|---|
| LanceDB | https://github.com/lancedb/lancedb | Apache-2.0 | arXMCP's vector store — track MVCC, FTS, scalar-index features |
| Qdrant | https://github.com/qdrant/qdrant | Apache-2.0 | Vector DB; hybrid-search + payload-filter patterns worth studying |
| ChromaDB | https://github.com/chroma-core/chroma | Apache-2.0 | Embeddable vector store; single-workstation ergonomics |
| pgvector | https://github.com/pgvector/pgvector | PostgreSQL license | Vector search inside Postgres; HNSW + filter pushdown |
| BGE-M3 / FlagEmbedding | https://github.com/FlagOpen/FlagEmbedding | MIT | arXMCP's embedder family — track dense+sparse+ColBERT multi-vector work |
| Sentence-Transformers | https://github.com/UKPLab/sentence-transformers | Apache-2.0 | Embedding-model tooling; new pooling / matryoshka methods |
| ColBERT / RAGatouille | https://github.com/stanford-futuredata/ColBERT | MIT | Late-interaction retrieval; relevant to math-statement matching |
| Kùzu | https://github.com/kuzudb/kuzu | MIT | arXMCP's citation graph DB (pinned 0.11.3, archived 2025-10-10) — watch for a maintained successor |
| DuckDB | https://github.com/duckdb/duckdb | MIT | In-process analytics; graph + vector extensions emerging |
| LaTeXML | https://github.com/brucemiller/LaTeXML | public domain (Perl) | arXMCP's LaTeX→XML parser — track theorem-aware conversion, drift |
| pandoc | https://github.com/jgm/pandoc | GPL-2.0 | Alternate document converter (study-only — GPL) |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | MIT | Reference for protocol features arXMCP may not yet expose |
| FastMCP | https://github.com/jlowin/fastmcp | Apache-2.0 | Ergonomic MCP-server framework; tool-registration patterns |
| LeanDojo | https://github.com/lean-dojo/LeanDojo | MIT | Programmatic interaction with Lean — proof state, premise selection |
| mathlib4 | https://github.com/leanprover-community/mathlib4 | Apache-2.0 | The Lean math library; the target of arXMCP's autoformalizer consumer |

**License discipline:** every OSS reference cites license verbatim.  Under arXMCP's **no-fork policy** (`CLAUDE.md §8`) nothing is lifted — GPL/AGPL is study-only, and even MIT/Apache code is studied for *ideas*, then implemented natively.

---

## Multi-agent / math-LLM systems and papers (last 24 months)

| Paper / project | Venue | Topic |
|---|---|---|
| ReProver / LeanDojo (Yang et al. 2023+) | NeurIPS | Retrieval-augmented theorem proving — premise selection over a math library |
| Draft-Sketch-Prove (Jiang et al.) | ICLR 2023 | Autoformalization: informal proof → formal sketch → proof — directly mirrors arXMCP's consumer pipeline |
| AlphaProof / AlphaGeometry (DeepMind) | Nature | LLM + search + formal verifier for olympiad mathematics |
| Lean Copilot | GitHub | LLM proof-tactic suggestion inside Lean |
| Autoformalization with LLMs (Wu et al.) | NeurIPS 2022 | Foundational: LLMs translating natural-language math to formal statements |
| CodeAct (Wang et al.) | ICML 2024 | Executable code as a unified LLM action space (the harness-paradigm primitive) |
| ReAct / Reflexion | arXiv | Foundational reasoning+acting and self-critique loops (cite if directly applicable) |
| Agentic / iterative RAG surveys | arXiv cs.IR | Retrieval interleaved with multi-step agent reasoning |
| MCP ecosystem reports | https://modelcontextprotocol.io/ | How agent harnesses consume tool servers — protocol-level trends |

**Survey heuristic:** prioritize work that publishes CODE or a reproducible benchmark — abstract-only papers are weaker evidence for "this is a real capability arXMCP could build."  Weight a source by primary evidence (paper + code + benchmark > paper + code > paper).

---

## arXMCP codebase orientation (read first by every scout)

| Path | What it is | Why a scout reads it |
|---|---|---|
| `CLAUDE.md` | Top-level project conventions | Architecture locks (§4.7), no-fork policy (§8), known stubs (§7), capabilities (§6) |
| `.claude/notes/01-mission-and-context.md` | Why arXMCP exists | The "Lean kernel is the better critic" framing — load-bearing for every candidate |
| `.claude/notes/02-architecture-overview.md` | System shape | What the server already wires together |
| `.claude/notes/05-storage-and-indexing.md` | LanceDB + Kùzu schema rationale | Storage-layer design decisions |
| `.claude/notes/07-multi-agent-caching.md` | THE cache-discipline note | BP1/BP2 prompt-cache constraints |
| `.claude/notes/10-references-and-prior-art.md` | Bibliography of prior art already studied | Don't re-surface what's already considered |
| `.claude/roadmap/README.md` | Authoritative epic index (E01–E14) | What has shipped and what is in flight |
| `server/` | The long-running MCP server | Current tool handlers + retrieval pipeline |
| `ingest/` | Corpus pipeline (chunker → embedder → indices → graph) | Current ingestion capability |
| `pyproject.toml` | Python ≥3.11; dependency pins (per-line comments) | What's pinned today; the baseline for OSS-trend deltas |
| `.claude/notes/milestones/<ID>/` | Per-milestone research + critique artifacts | Recurring failure modes; what each milestone learned |

The **adversary scout** (Phase 1 scout #5) is responsible for end-to-end traversal of these.  The other four scouts do quick orientation reads, then focus their attention externally.

---

## Hard rules (every scout)

- **License citation is mandatory** for every OSS reference.
- **arXiv citation format:** `arXiv:NNNN.NNNNN` + year + 1-sentence finding.  Do NOT invent arXiv IDs — if you cannot verify the id, name the work and link the venue page instead.
- **Time-window:** last 24 months unless the older work is genuinely foundational AND not already documented in `.claude/notes/10-references-and-prior-art.md`.
- **No speculation about arXMCP internals.**  Every "arXMCP already does X" / "arXMCP doesn't do X" claim has a `file:line` citation or a `CLAUDE.md §N` citation.
- **No vendor-blog hype.**  If a source's only evidence is its own marketing page, weight it accordingly.
- **No-fork discipline.**  Surface OSS as *ideas to implement natively*, never as import/vendor targets.
- **Boundary respect:** scouts do NOT write code; they write briefs.
