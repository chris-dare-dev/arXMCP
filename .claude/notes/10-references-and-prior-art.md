# 10 — References and Prior Art

Projects, papers, and protocol specs that informed the design. Read these
before making non-trivial design changes.

## Protocol and platform docs

- **MCP Specification 2025-06-18 — Overview**
  `https://modelcontextprotocol.io/specification/2025-06-18`
  Source of truth for transport, tool surface, resource surface, and security
  obligations.
- **MCP Specification — Transports**
  `https://modelcontextprotocol.io/specification/2025-06-18/basic/transports`
  Read closely; the stdio-vs-HTTP distinction is foundational for arXMCP.
- **MCP Specification — Tools**
  `https://modelcontextprotocol.io/specification/2025-06-18/server/tools`
  Result shape, `resource_link` semantics, output schemas, security MUSTs.
- **MCP Specification — Progress**
  `https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/progress`
  Heartbeat semantics; do not confuse with streaming results (which the spec
  does not provide for tool calls).
- **Anthropic prompt caching**
  `https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching`
  TTLs, breakpoint count, pricing, cache key semantics. **Verify all
  numeric claims here against the live doc** — training-knowledge values
  may be out of date.
- **Anthropic Files API**
  `https://docs.anthropic.com/en/docs/build-with-claude/files`
- **Anthropic Citations**
  `https://docs.anthropic.com/en/docs/build-with-claude/citations`
- **MCP server registry**
  `https://github.com/modelcontextprotocol/registry`
  Community-maintained list of available MCP servers.

## Existing arXiv-MCP servers (steal ideas, don't fork)

- `https://github.com/blazickjp/arxiv-mcp-server` — most-starred reference.
  Tools: `search_papers`, `download_paper`, `list_papers`, `read_paper`. Uses
  PyMuPDF for parsing; **mangles math.** Useful for tool-surface inspiration.
- `https://github.com/daheepk/arxiv-paper-mcp` — light wrapper around
  arXiv Atom API. Search-only. Useless for full-text.
- `https://github.com/prashalruchiranga/arxiv-mcp-server` — fork of
  blazickjp; minor differences.
- `https://github.com/kyrylo-gr/lookup-arxiv-mcp` — adds Semantic Scholar
  enrichment to arXiv search. Citation-graph-adjacent ideas.
- **PaperQA2's MCP mode** — `https://github.com/Future-House/paper-qa`
  ships an MCP server in `paperqa.agents.mcp`. The most serious agent loop
  we've seen for paper retrieval. Tuned for biology/chemistry but the
  evidence-pipelining pattern (`gather → summarize → answer`) is the
  pattern arXMCP imitates for tool-result shape.

## Math agent systems (motivate the pipeline)

- **AlphaProof + AlphaGeometry 2** (DeepMind, 2024)
  `https://deepmind.google/discover/blog/ai-solves-imo-problems-at-silver-medal-level/`
  IMO 2024 silver medal. Two-component pipeline: autoformalizer + AlphaZero
  search over Lean tactic states.
- **DeepSeek-Prover-V2** (April 2025, open weights)
  `https://github.com/deepseek-ai/DeepSeek-Prover-V2`
  arXiv:2504.21801. Subgoal decomposition: V3 writes informal sketch with
  `sorry`s, prover model fills each `sorry`, RL on successful chains. The
  closest open template for the pipeline arXMCP serves.
- **Goedel-Prover / V2** (Princeton, 2024–25)
  `https://github.com/Goedel-LM/Goedel-Prover`
  Cleanest reference codebase for prover-verifier loops.
- **Kimina-Prover** (Numina + Moonshot, April 2025)
  arXiv:2504.11354. Qwen-based, Lean 4, RL-trained. Interleaved
  natural-language + Lean tactic stream.
- **LeanDojo** — `https://leandojo.org`,
  `https://github.com/lean-dojo/LeanDojo`
  Python access to Lean's proof state. Critical infra for any future
  arXMCP-Lean integration.
- **Lean Copilot** — `https://github.com/lean-dojo/LeanCopilot`
  In-editor Lean assistant. Reference for what tools an autoformalizer
  agent uses.
- **Tao equational-theories project** — `https://teorth.github.io/equational_theories`
  The most credible deployed multi-agent math workflow today. Worth
  studying for what "good enough to ship" looks like.

## Foundational math-LLM papers

- **Draft-Sketch-Prove** (Jiang et al., ICLR 2023) — arXiv:2210.12283.
  The three-role pipeline ancestor of every modern subgoal-decomposition
  prover.
- **Lean-STaR** (Lin et al., 2024) — arXiv:2407.10040. Interleaves NL
  thoughts with Lean tactics during training.
- **Autoformalization with LLMs** (Wu et al., NeurIPS 2022) — arXiv:2205.12615.
  Original demonstration that frontier LLMs can translate competition
  statements into Isabelle/Lean.
- **ProofNet** (Azerbayev et al.) — arXiv:2302.12433. Standard benchmark for
  autoformalization at undergraduate level.
- **Let's Verify Step-by-Step** (Lightman et al., 2023) — arXiv:2305.20050.
  Process reward models. Important context for *why an LLM critic doesn't
  work for research math*.
- **Math-Shepherd** (Wang et al., 2023) — arXiv:2312.08935. PRM for math.
- **Improving Factuality and Reasoning via Multi-Agent Debate** (Du et al.,
  2023) — arXiv:2305.14325. The original debate paper.
- **Prover-Verifier Games** (Kirchner et al., OpenAI, 2024) —
  arXiv:2407.13692. Game-theoretic framing of prover/verifier.

## Benchmarks

- **miniF2F** — `https://github.com/openai/miniF2F`
  High-school + olympiad theorems formalized in Lean/Isabelle/HOL Light.
  Largely saturated by mid-2025.
- **PutnamBench** — `https://github.com/trishullab/PutnamBench`
  Putnam problems in Lean. Far harder; mostly unsolved.
- **FrontierMath** (Epoch AI) — `https://epoch.ai/frontiermath`
  Research-grade problems. Single-digit completion as of late 2025. **The
  regime arXMCP's target users operate in.**
- **ProofNet** — `https://github.com/zhangir-azerbayev/ProofNet`

## Parsing and document conversion

- **LaTeXML** — `https://github.com/brucemiller/LaTeXML`,
  `https://math.nist.gov/~BMiller/LaTeXML/`
  The primary parser. Read the manual.
- **ar5iv** — `https://ar5iv.labs.arxiv.org`
  Pre-rendered LaTeXML output for most of arXiv. Hosted as a project of
  arXiv Labs.
- **arXiv HTML view** — `https://arxiv.org/html/<id>` (gradually replacing
  ar5iv).
- **Nougat** — `https://github.com/facebookresearch/nougat`
  Vision-transformer PDF→markdown. Last-resort parser.
- **Marker** — `https://github.com/VikParuchuri/marker`
  Faster alternative to Nougat. Active development.
- **GROBID** — `https://github.com/kermitt2/grobid`
  Strong for metadata + reference extraction; weak on equations.
- **pylatexenc** — `https://github.com/phfaist/pylatexenc`
  Tokenizer / walker for LaTeX. Useful for chunk segmentation.

## Storage and indexing

- **LanceDB** — `https://github.com/lancedb/lancedb`,
  `https://lancedb.github.io/lancedb/`
  Embedded vector + scalar + full-text database. Primary store.
- **Kùzu** — `https://github.com/kuzudb/kuzu`,
  `https://kuzudb.com/`
  Embedded graph database. Cypher. Citation graph.
- **Tantivy** — `https://github.com/quickwit-oss/tantivy`
  Rust BM25 / inverted index. Powers LanceDB's full-text search.
- **Qdrant** — `https://github.com/qdrant/qdrant`
  Vector search server. Backup pick if LanceDB hits a ceiling.
- **FAISS** — `https://github.com/facebookresearch/faiss`
  Used in-memory for the Tier-2 semantic-cache index.

## Embedding models

- **BAAI/bge-m3** — `https://huggingface.co/BAAI/bge-m3`
  Default v1 embedder.
- **intfloat/e5-mistral-7b-instruct** —
  `https://huggingface.co/intfloat/e5-mistral-7b-instruct`
  Stronger but heavier. v1.5 candidate.
- **BAAI/bge-reranker-v2-m3** —
  `https://huggingface.co/BAAI/bge-reranker-v2-m3`
  Default v1 reranker.
- **Voyage AI** — `https://www.voyageai.com`
  Hosted embedders; `voyage-3` and `voyage-3-large`. Use only for query-time
  encoding if at all.
- **SPECTER2** (Allen AI) —
  `https://huggingface.co/allenai/specter2`
  Citation-aware scientific paper embeddings. Useful baseline.
- **ColBERTv2** — `https://github.com/stanford-futuredata/ColBERT`
  Late-interaction retrieval. Tier 6 / v1.5.

## Citation graph data sources

- **OpenAlex** — `https://openalex.org`,
  `https://docs.openalex.org/`
  Free, fully open, monthly snapshots, ~100K rps polite-pool.
  Math-AG / math-NT citation backbone.
- **INSPIRE-HEP** — `https://inspirehep.net/api/literature`,
  `https://inspirehep.net/info/hep/api`
  Free, ~15 rps, structured. hep-th / math-ph backbone.
- **Semantic Scholar Academic Graph** —
  `https://api.semanticscholar.org`,
  `https://www.semanticscholar.org/product/api`
  Free with key. Backup data source.
- **Crossref** — `https://www.crossref.org/documentation/retrieve-metadata/rest-api/`
  DOI metadata. Supplementary.

## Ingestion sources

- **Academic Torrents** — `https://academictorrents.com`
  Search "arxiv". Seed source.
- **arXiv OAI-PMH endpoint** — `http://export.arxiv.org/oai2`
  `https://info.arxiv.org/help/oa/index.html`
- **arXiv API ToU** — `https://info.arxiv.org/help/api/tou.html`
  Rate limits and politeness rules.
- **arXiv bulk data documentation** —
  `https://info.arxiv.org/help/bulk_data.html`
- **arXiv `/e-print/`** — `https://arxiv.org/e-print/<paper_id>`
  Source tarball endpoint.

## Observability

- **Phoenix (Arize)** — `https://github.com/Arize-ai/phoenix`
  Retrieval-eval views. v1 default.
- **Langfuse** — `https://langfuse.com`,
  `https://github.com/langfuse/langfuse`
  End-to-end LLM call tracing.
- **Helicone** — `https://www.helicone.ai`
  LLM-side proxy.
- **OpenTelemetry** — `https://opentelemetry.io`
  Tracing standard. Use for both server internals and ingestion.

## Security and isolation

- **restic** — `https://restic.net`,
  `https://github.com/restic/restic`
  Backup tool. Encrypted, deduped, S3-compatible.
- **safetensors** — `https://github.com/huggingface/safetensors`
  Safe model weight format. Refuse `.bin` / pickle.

## Inspirational systems (ideas only)

- **PaperQA2 evidence pipelining** — adopt the
  `gather → summarize → answer` decomposition.
- **OpenAI Vector Stores design** — server-side chunking + auto-attribute
  + ranker. Keep chunking and ranking server-side; don't ship raw text.
- **ColBERT-v2 / late interaction** — for long technical chunks.
- **Vespa tiered ranking** — first-phase BM25, second-phase ANN, third-phase
  reranker. Maps onto our three cache tiers.
- **Cohere RAG `documents` field** — pass retrievals as structured
  documents, not concatenated text. Anthropic supports this via `<document>`
  XML tags in system prompts.

## Reference clients

- `https://github.com/lukasschwab/arxiv.py` — Python arXiv API client. Read
  for ideas; do not import (it doesn't do what we need).
- `https://github.com/langchain-ai/langchain` — `ArxivLoader`. Naive but
  readable.
