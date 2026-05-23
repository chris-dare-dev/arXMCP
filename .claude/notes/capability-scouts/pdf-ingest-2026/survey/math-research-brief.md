# Math-Research Scout Brief — pdf-ingest-2026

**Scout:** math-research (Phase-1 #2 of 5).
**Date:** 2026-05-23.
**Scope:** Research-mathematics retrieval / corpus-design /
autoformalization algorithms gaining momentum in 2024–2026 that
arXMCP could plausibly adopt **for textbook-PDF ingestion specifically**.
Cross-checked against `pdf-capability-deep-dive.md` so this extends the
dive rather than duplicating it.

---

## 1. TL;DR

The 2024–2026 math-PDF-extraction literature has consolidated around
**VLM-based parsers (MinerU2.5, olmOCR2, PaddleOCR-VL, Granite-Docling)
that materially out-score Marker / Nougat on Character-Detection-Matching
(CDM)**, with formal benchmarks (OmniDocBench CVPR-2025, the December
2025 math-formula-extraction benchmark) now letting Path-A be chosen on
numbers rather than vibes. The autoformalization community has converged
on **textbook-aware data (ProofNet 371 problems, MathPile's 9.5B-token
Textbooks slice, MMA's 88k NL/Lean pairs)** but treats raw-PDF ingest as
an upstream-someone-else problem — and the consistent finding is that
**Mathlib + def-graph + premise-selection beats raw textbook PDFs** when
the goal is autoformalization. For arXMCP, the highest-leverage net-new
ideas are **(a) CDM as a Tier-1 fidelity gate, (b) late-chunking for the
preamble-prepend pattern, (c) graph-augmented premise selection on the
existing Kùzu store, and (d) the LemmaBench / "Autoformalization in the
Wild" definition-grounding pattern** for any textbook-derived chunk.

---

## 2. Algorithm / method candidates

### 2.1 MinerU 2.5 (decoupled VLM PDF parser with CDM-graded math)

- **Name:** MinerU2.5; companion benchmark **OmniDocBench**; companion
  metric **CDM (Character Detection Matching)**.
- **Year / authors:** Wang, Bin et al. — MinerU 2.5 technical report
  (2025); OmniDocBench (Ouyang et al., CVPR 2025); CDM (Wang et al.,
  CVPR 2025).
- **Primary citation:** MinerU original arXiv:2409.18839 (Sep 2024),
  MinerU 2.5 technical report Oct 2025; OmniDocBench arXiv:2412.07626;
  CDM arXiv:2409.03643.
- **Plain-English summary:** Two-stage VLM. Stage I does layout
  analysis on page thumbnails (NaViT + Patch Merger + LLM head). Stage
  II runs targeted high-resolution recognition on native-resolution
  crops. Math equations are routed to UniMERNet (ResNet/Swin + Transformer)
  trained with seq2seq cross-entropy on LaTeX tokens, plus an "Atomic
  Decomposition & Recombination" (ADR) divide-and-conquer for compound
  formulas. Reports **96.4 CDM on SCE / 90.6 CDM on LaTeX-80M**,
  4 SOTA + 1 second-best across OmniDocBench's 7 tasks. Beats Marker
  and Nougat by a large margin on math-heavy pages.
- **Compute footprint:** GPU-preferred for throughput; CPU possible but
  slow. Local-first compatible (model weights downloadable; not a
  hosted-only service). ~3B parameter regime.
- **Implementation complexity:** Use as **subprocess CLI** (`mineru`
  binary, Apache-style permissive license per public README — the
  project's stated 2025 relicense lowered the barrier for both
  community and commercial use; confirm at commit time). NOT a "few
  hundred LOC" reimplementation — depend on the upstream package as
  a subprocess.
- **Math-content fidelity:** Emits **LaTeX for inline + display
  formulas** + Markdown for prose + HTML for tables. Does NOT emit
  MathML directly — downstream LaTeXML pass required to land on the
  HTML5+MathML contract that arXMCP's chunker consumes. Macro expansion
  works *only* on what's syntactically expressible in the OCR output:
  if the original PDF was compiled from `\newcommand{\AA}{\mathcal{A}}`
  + `\AA`, MinerU sees the rendered glyph and can only emit
  `\mathcal{A}` — i.e., **macros are pre-expanded at render time**;
  the per-paper notation table in arXMCP is empty for MinerU-sourced
  chunks (since the macros are baked into the PDF). This matches
  Marker's behavior; it is a fundamental limitation of any PDF-OCR path
  versus source-fetcher.
- **arXMCP fit:** Net-new `ingest/pdf_mineru.py` driver, called
  *before* the existing LaTeXML stage to emit LaTeX-markdown; output
  feeds `ingest/chunker.py` unmodified. Sits at the same point as
  `pdf_marker.py` in Path A of the deep dive (file refs:
  `pdf-capability-deep-dive.md:283-301`). **Stronger numerical case
  than Marker as of late 2025.** Consider replacing Marker as the Path-A
  primary; keep Marker as fallback. Document `parser_used:
  "mineru+latexml"` on the chunks schema.
- **Maturity signal:** opendatalab/MinerU is the top-trending PDF
  parser on GitHub through 2025; large community; multiple releases;
  Mathpix-class on Chinese, MinerU best on English per OmniDocBench
  v1.5 leaderboard updated March 2026.

### 2.2 olmOCR / olmOCR 2 (Allen AI, fully open VLM for academic PDFs)

- **Name:** olmOCR, olmOCR 2.
- **Year / authors:** Allen Institute for AI — olmOCR (Soldaini et al.,
  Feb 2025), olmOCR 2 (Oct 2025).
- **Primary citation:** arXiv:2502.18443 (olmOCR); arXiv:2510.19817
  (olmOCR 2 — "Unit Test Rewards for Document OCR").
- **Plain-English summary:** olmOCR is a VLM trained specifically to
  linearize PDFs into LLM-ingestible text, with an explicit "preserve
  reading order across multi-column pages" objective. olmOCR 2 adds
  **RLVR (reinforcement learning with verifiable rewards) keyed on
  unit-test cases** — for each document the trainer asserts a set of
  binary unit tests ("the formula on page 3 must contain `\partial`",
  "the table on page 7 must have 4 columns") and the model is rewarded
  on test-pass rate rather than edit distance. olmOCR-Bench is 7,000+
  test cases across 1,400 docs.
- **Compute footprint:** 7B model (`olmOCR-2-7B-1025`). GPU required
  for practical throughput. Apache-2.0 weights AND code AND data —
  fully open including training corpus. Local-first compatible.
- **Implementation complexity:** depend on `allenai/olmocr` package
  (CLI subprocess). License is **Apache-2.0** — no GPL boundary
  concerns, unlike Marker.
- **Math-content fidelity:** strong on multi-column scientific
  layouts; the unit-test reward scheme means equation fidelity is
  explicitly measured and rewarded during training (this is what
  Nougat lacked). Emits Markdown + LaTeX-for-math. No MathML.
- **arXMCP fit:** Alternative to MinerU 2.5 with the **license
  advantage** (Apache-2.0 vs MinerU's permissive-but-verify). For
  arXMCP's no-fork policy and the GPL-boundary concern flagged in
  `pdf-capability-deep-dive.md:301`, **olmOCR 2 is the strongest
  drop-in for the Path-A primary parser.** Same insertion point as
  MinerU — `ingest/pdf_olmocr.py` → LaTeXML → existing chunker.
  Tag chunks `parser_used: "olmocr2+latexml"`.
- **Maturity signal:** released Oct 2025; cited by Olmo 3 release
  Nov 2025; active development from a credible research lab (Ai2);
  bench public and reproducible.

### 2.3 Granite-Docling 258M (IBM, AAAI 2025) + Docling framework

- **Name:** Docling (toolkit); Granite-Docling-258M (the VLM).
- **Year / authors:** IBM Research (Auer et al.) — initial Docling
  paper accepted AAAI 2025; Granite-Docling-258M model released 2025.
- **Primary citation:** IBM Research publications page (Docling AAAI
  2025); GitHub `docling-project/docling`.
- **Plain-English summary:** Modular toolkit. Layout analysis uses
  **DocLayNet-trained RT-DETR**; table structure via **TableFormer**;
  a **Code Formula Model** processes equation images into LaTeX. The
  framework exports to multiple targets including HTML, which uses
  **MathML for equations** when the formula module fires. Granite-Docling
  is a 258M-parameter VLM (very small) released under Apache 2.0.
- **Compute footprint:** Granite-Docling-258M runs comfortably on CPU
  or a single mid-range GPU. The full Docling toolkit's
  TableFormer + RT-DETR can run CPU-only. **The smallest credible
  VLM-class parser in this list.**
- **Implementation complexity:** Python package; subprocess or in-process.
  MIT-licensed toolkit + Apache-2.0 model. No GPL concern.
- **Math-content fidelity:** **Only candidate that emits MathML in
  HTML export natively** (Code Formula Model → LaTeX → MathML in HTML
  output path). Quality is lower than MinerU 2.5 / olmOCR 2 on dense
  research-grade math, but the **MathML emission saves a LaTeXML pass**.
  Comparable to Marker on standard scientific PDFs; weaker on Bourbaki/
  Polchinski-grade math density.
- **arXMCP fit:** **The "skip-LaTeXML" optimization candidate.** If
  Granite-Docling's HTML5+MathML output passes arXMCP's chunker
  directly (testable in a 1-day spike), the pipeline is one stage
  shorter than Marker→LaTeXML or MinerU→LaTeXML. New module
  `ingest/pdf_docling.py`. Tag chunks `parser_used: "docling"`.
  **Worth a fidelity-comparison spike against MinerU2.5+LaTeXML and
  olmOCR2+LaTeXML on the same 20-paper sample.**
- **Maturity signal:** AAAI 2025 acceptance; top trending GitHub
  repo Nov 2024; 100+ releases since Aug 2025; 37k+ GitHub stars;
  IBM-backed long-term support signal.

### 2.4 Character Detection Matching (CDM) as the fidelity gate metric

- **Name:** Character Detection Matching (CDM).
- **Year / authors:** Wang et al., CVPR 2025.
- **Primary citation:** arXiv:2409.03643 — "Image Over Text: Transforming
  Formula Recognition Evaluation with Character Detection Matching."
- **Plain-English summary:** Replaces BLEU and edit-distance for formula
  recognition. Renders the *predicted* LaTeX back to an image, detects
  the characters in both predicted and ground-truth renders, and matches
  them via Hungarian assignment on bounding-box features. This gives a
  metric that's **invariant to LaTeX expression diversity** — `\frac{a}{b}`
  and `a/b` rendering to the same glyph stack score equivalently.
  Adopted by OmniDocBench (CVPR 2025), MinerU 2.5, PaddleOCR-VL.
- **Compute footprint:** Pure-CPU evaluation. ~hundreds of LOC reference
  impl. No GPU. No model.
- **Implementation complexity:** small — a few hundred LOC if implemented
  from scratch; reference impls available in OmniDocBench repo
  (`opendatalab/OmniDocBench`, Apache-2.0 license).
- **Math-content fidelity:** N/A — it's the metric, not a producer.
- **arXMCP fit:** **Tier-1 promotion gate for any new parser path.**
  arXMCP already has eval gates (`make eval`, nDCG@5, Recall@10). Add
  a CDM-based gate to `tests/eval/` (or a separate `tests/parsers/`
  bench) that compares any new parser's MathML/LaTeX output against an
  ar5iv ground-truth on a held-out 20-paper sample. **This is the
  numerical answer to the "is Path A better than Path B" question** —
  the deep dive recommends Path B first because no fidelity numbers
  exist; CDM gives us the number. Net-new module under
  `tests/parsers/cdm.py` or `tools/cdm_eval.py`. Maps onto
  `.claude/TIER-GATES.md` discipline.
- **Maturity signal:** CVPR 2025; adopted by every serious 2025 PDF
  parser bench; reference impl in opendatalab/OmniDocBench.

### 2.5 Late Chunking (Jina, 2024) for preamble-prepend embedding

- **Name:** Late Chunking.
- **Year / authors:** Günther et al. (Jina AI), Sep 2024.
- **Primary citation:** arXiv:2409.04701 — "Late Chunking: Contextual
  Chunk Embeddings Using Long-Context Embedding Models."
- **Plain-English summary:** Standard chunking embeds each chunk
  independently → loses cross-chunk context. Late chunking instead
  encodes the **entire long document** through a long-context embedder
  once, then **mean-pools token embeddings within chunk boundaries** to
  derive per-chunk vectors. Result: each chunk's embedding "knows
  about" the surrounding sentences (esp. preambles, definitions
  introduced earlier in the document) without the chunk text itself
  having to repeat them. Validated on Jina's V3 long-context model;
  applicable to any long-context embedder including BGE-M3
  (8k-token context).
- **Compute footprint:** Same model, same hardware. The change is
  in **how** you call the embedder — one long forward pass per chapter
  / per document instead of N short ones. Net throughput is
  **lower** (long forward = O(n²) attention) but quality goes up.
- **Implementation complexity:** ~50 LOC additional pre-processing in
  `ingest/embedder.py`. Open reference impl in `jinaai/late-chunking`
  (Apache-2.0).
- **Math-content fidelity:** N/A directly — but materially relevant
  for **textbook chunking** where definitions in Chapter 1 are
  referenced throughout the book. Late chunking lets a Chapter 7 lemma
  chunk's embedding *implicitly* incorporate Chapter 1's definition of
  the symbol it uses, even if the chunk text doesn't repeat it. **This
  is a direct alternative / complement to arXMCP's existing "preamble
  prepended to every chunk" pattern** (`04-parsing-and-chunking.md` Rule 2)
  for the textbook case where the "preamble" is the entire prior text.
- **arXMCP fit:** `ingest/embedder.py` modification, gated behind
  `chunker_version` bump. Particularly attractive for the textbook
  path because **a textbook is a single long contextually coherent
  document**, unlike the arXiv paper corpus where each paper is its
  own context. Net-new wiring; existing per-paper-preamble logic
  preserved for arXiv path. Mark chunks `embedding_method:
  "late_chunked_v1"` for cache discipline.
- **Maturity signal:** in production at Jina; cited 200+ times by
  May 2026; replicated by Anthropic prompt-cache writeups; Apache-2.0
  reference impl.

### 2.6 Autoformalization in the Wild — definition grounding

- **Name:** "Autoformalization in the Wild" + LemmaBench.
- **Year / authors:** ~Feb 2025, multiple authors — paper assesses
  LLMs on real-world mathematical definitions from arXiv and Wikipedia.
- **Primary citation:** arXiv:2502.12065 — "Autoformalization in the
  Wild: Assessing LLMs on Real-World Mathematical Definitions";
  arXiv:2602.24173 — "LemmaBench: A Live, Research-Level Benchmark."
- **Plain-English summary:** Tests LLM autoformalization on
  **research-grade mathematical definitions** (not just olympiad
  statements). Finds that **definition-grounding** — passing the LLM
  the formal definitions of each undefined symbol in the prompt —
  yields up to **+16% on self-correction and +43% reduction in
  undefined-symbol errors** vs the baseline. This is exactly the
  problem arXMCP's `definitions` table + `get_definitions` tool was
  built to solve (`05-storage-and-indexing.md:91-104`).
- **Compute footprint:** N/A (methodology paper).
- **Implementation complexity:** the algorithmic ideas are small:
  before any autoformalization call, traverse the definition graph
  from the target theorem 2–3 hops, include all reachable definitions
  in the prompt. The existing arXMCP `get_definitions` tool surface
  + `cite_neighbors` library are the building blocks.
- **Math-content fidelity:** N/A (downstream of parsing).
- **arXMCP fit:** **Two new patterns:**
  (a) **Definition-graph expansion at autoformalizer-tool-call time.**
  The autoformalizer agent's `get_definitions(symbol)` call should
  recursively expand to "definitions referenced by this definition,
  bounded depth 3", not just direct definitions. Belongs in
  `server/handlers/definitions.py` (existing) +
  `server/graph_queries.py` (new helper `definition_closure(symbol_id,
  depth=3)`). Mirrors the existing `cite_neighbors` library pattern.
  (b) **Textbook definitions are the killer-app data source for this
  expansion.** A research paper assumes 80% of the definitions; a
  textbook *contains* them. Strong argument that textbook ingest's
  **highest-value output is the definitions table**, not the prose
  chunks. Suggests a textbook-ingest milestone scope where definition
  extraction is the M1 deliverable and prose-chunk retrieval is M2.
- **Maturity signal:** Active research line; benchmark in active
  curation (LemmaBench); cited by ProofBridge and the autoformalization
  survey arXiv:2505.23486.

### 2.7 Graph-augmented premise selection (ReProver successors)

- **Name:** Graph-augmented premise selection / "Combining Textual
  and Structural Information for Premise Selection in Lean."
- **Year / authors:** late 2025.
- **Primary citation:** arXiv:2510.23637 — "Combining Textual and
  Structural Information for Premise Selection in Lean."
- **Plain-English summary:** ReProver (LeanDojo) does **text-only
  dense retrieval** over Mathlib lemma statements. This 2025 paper
  shows a **GNN over a heterogeneous dependency graph of Mathlib
  declarations** combined with dense text embeddings **beats ReProver
  by >25% on LeanDojo Benchmark**. Companion paper SciLib-GRC21
  builds a materialised RDF knowledge graph of Mathlib via the SciLib
  ontology for tactic-categorised lemma hints.
- **Compute footprint:** GNN inference is cheap; dense embedder is
  the standard load. Local-first compatible.
- **Implementation complexity:** Reference impl in the paper repo;
  needs Mathlib graph (analogue: arXMCP's Kùzu store). Several
  hundred LOC for the GNN side; the dense side already exists.
- **Math-content fidelity:** N/A (downstream of parsing).
- **arXMCP fit:** **Directly applicable to arXMCP's Kùzu citation
  graph.** arXMCP already has CITES + PROVES edges
  (`05-storage-and-indexing.md:208-227`). Adding a **definition-graph
  GNN reranker** on top of the existing Phase-3 BGE-reranker
  (`server/retrieval/rerank.py`) would mirror this work. Modest LOC,
  high leverage. Belongs in `server/retrieval/` as a new
  `graph_rerank.py` stage gated behind an env var like the existing
  `ARXMCP_ENABLE_RERANK`.
- **Maturity signal:** Oct 2025 publication; bench results on
  LeanDojo; reference impl in submission artifact.

### 2.8 ColPali / ColQwen2 — late-interaction visual retrieval (parking-lot for now)

- **Name:** ColPali; ColQwen2; ColSmol.
- **Year / authors:** Faysse et al., July 2024 (ColPali, ICLR 2025);
  ColQwen2 / ColSmol 2025.
- **Primary citation:** arXiv:2407.01449 — "ColPali: Efficient
  Document Retrieval with Vision Language Models."
- **Plain-English summary:** Skip OCR entirely. Render each PDF page
  to an image, encode patches with a VLM (PaliGemma 3B for ColPali,
  Qwen2-VL for ColQwen2), retrieve via late-interaction MaxSim over
  patch embeddings. Sets SOTA on the ViDoRe benchmark, beats text-RAG
  on **visually-rich** documents (figures, tables, diagrams).
- **Compute footprint:** VLM-class storage cost (~10× single-vector
  retrieval; explicitly comparable to ColBERT-v2 cost noted in
  arXMCP `05-storage-and-indexing.md:298-306`). GPU strongly preferred
  for ingest; query-time can be CPU-acceptable.
- **Implementation complexity:** `illuin-tech/colpali` Apache-2.0
  reference impl. Vector store needs to support patch-level
  embeddings; LanceDB can do this with per-page collections.
- **Math-content fidelity:** **interesting wildcard** — ColPali
  preserves visual structure including formula glyphs and figures
  *without OCR*, so it could in principle retrieve "the page with the
  commutative diagram that looks like this" — exactly the TikZ-cd
  problem flagged as deferred in arXMCP. But: cannot produce LaTeX /
  MathML output, so a retrieved chunk is **just a page image** — not
  ingestible by the existing prose chunker / embedder / definitions
  table. The whole downstream chain becomes "fetch page image →
  separate Marker / olmOCR pass" — a parallel pipeline.
- **arXMCP fit:** **Parking-lot for v1, candidate for a v2 "visual
  textbook retrieval" milestone.** Would justify the chapter-walk /
  exercise-as-target / definition-graph patterns called out in BRIEF.md
  §4. Tag as Tier-5+ in `.claude/TIER-GATES.md` — same tier as
  ColBERT-v2. Mention in roadmap as the long-horizon answer to "how
  does arXMCP eventually handle Hartshorne's figures."
- **Maturity signal:** ICLR 2025; ColQwen2 leaderboard-leading on
  ViDoRe v2; production-ready per multiple 2025 writeups.

### 2.9 HiChunk + HiCBench (hierarchical-chunking benchmark)

- **Name:** HiChunk + HiCBench.
- **Year / authors:** Sep 2025 (multiple authors).
- **Primary citation:** arXiv:2509.11552 — "HiChunk: Evaluating and
  Enhancing Retrieval-Augmented Generation with Hierarchical Chunking."
- **Plain-English summary:** Most chunking benchmarks evaluate on
  *response quality* — confounded by everything downstream. HiCBench
  isolates **chunking quality** specifically via manually-annotated
  hierarchical chunk points in long documents. HiChunk is the
  reference method: produces nested chunk hierarchies, retrieval can
  query at any granularity, response quality wins consistently.
- **Compute footprint:** LLM-assisted chunking (~one call per ~10
  pages); CPU-acceptable thereafter.
- **Implementation complexity:** Reference impl in paper repo
  (license — check at adoption time; not flagged as GPL in any survey
  I've seen).
- **Math-content fidelity:** N/A directly, but the **hierarchical
  chunk hierarchy maps cleanly onto the textbook book/chapter/section/
  theorem-or-exercise structure** that BRIEF.md and the deep dive
  flag as the chunking-strategy gap.
- **arXMCP fit:** **Directly motivates a textbook-aware chunker.**
  arXMCP's existing `chunker.py` is theorem-aware; for textbooks,
  add a parallel `textbook_chunker.py` that emits a hierarchical
  chunk tree compatible with `chunks.level` enum extension (existing
  values: `paper | section | theorem`; add `book | chapter | exercise
  | definition`). Schema bump per the chunker-versioning discipline
  (`04-parsing-and-chunking.md:186-193`). New chunker_version `v2.0`
  reserved for "textbook-aware".
- **Maturity signal:** Sep 2025 publication; benchmark available;
  the broader "hierarchical chunking" theme is dominant in the 2025
  RAG-chunking literature (multiple papers; NVIDIA's 7-strategy bench
  found page-level chunking is the best naive baseline but
  hierarchical wins on structured docs).

### 2.10 MathPile / OpenMathInstruct corpus design — textbook as data signal

- **Name:** MathPile (data); OpenMathInstruct-2 (data); ProofNet
  (benchmark).
- **Year / authors:** MathPile — Wang, Z. et al., NeurIPS 2024
  Datasets & Benchmarks; OpenMathInstruct-2 (Toshniwal et al., 2024).
- **Primary citation:** arXiv:2312.17120 (MathPile);
  arXiv:2410.01560-ish (OpenMathInstruct-2); arXiv:2302.12433 (ProofNet).
- **Plain-English summary (across the three):** The pretraining /
  evaluation corpora for the strongest open math LLMs as of 2025
  (DeepSeek-Math, DeepSeek-Prover-V2, Llemma) explicitly include a
  **Textbooks slice** alongside arXiv, ProofWiki, StackExchange.
  MathPile is ~9.5B tokens, with Textbooks one of four components.
  ProofNet's 371 problems are sourced from **undergraduate textbook
  exercises**. MMA generated 88k NL/Lean pairs from LeanDojo-extracted
  formal statements. **Empirical signal: every credible 2024-2025 math
  LLM training pipeline treats textbooks as a first-class corpus
  component.** Nobody publishes the textbook-PDF→training-token
  pipeline in detail — that's the gap in the public record.
- **Compute footprint:** N/A (corpora, not models).
- **Implementation complexity:** N/A.
- **Math-content fidelity:** N/A. Note: MathPile's data card mentions
  preprocessing/cleaning/deduplication but does not publish the
  PDF-extraction pipeline used for the Textbooks slice. (This is the
  honest answer to BRIEF.md Q3 "has anyone settled on a canonical
  textbook ingest pipeline" — **no, the leading datasets are
  ad-hoc-cleaned.**)
- **arXMCP fit:** **Signal, not algorithm.** The signal is: every
  serious 2025 math system treats textbooks as a corpus component,
  so the textbook-ingest investment is on-trend, not contrarian.
  Specifically supports the BRIEF §3 question — autoformalization
  community wants textbooks as source, has not settled on a canonical
  ingest pipeline, and treats raw extracted text as good enough
  *for training data* (which has different fidelity requirements
  than research-mathematician retrieval). **For arXMCP's
  mathematician-in-the-loop use case, the fidelity bar is higher**;
  CDM-graded MinerU 2.5 / olmOCR 2 + LaTeXML is the answer the
  literature does not provide.
- **Maturity signal:** MathPile NeurIPS 2024 acceptance; downloaded
  by every major math-LLM training run since.

---

## 3. Sources reviewed

| Venue / URL pattern | Papers / repos scanned | High-signal? |
|---|---|---|
| arxiv.org (cs.CL, cs.IR, cs.LG, cs.LO) | OmniDocBench 2412.07626, CDM 2409.03643, UniMERNet 2404.15254, MinerU 2409.18839, olmOCR 2502.18443, olmOCR2 2510.19817, ColPali 2407.01449, Late Chunking 2409.04701, HiChunk 2509.11552, MathPile 2312.17120, ProofNet 2302.12433, DeepSeek-Prover-V2 2504.21801, Autoformalization-in-the-Wild 2502.12065, Graph-augmented premise selection 2510.23637, READOC 2409.05137, Math-formula-extraction benchmark 2512.09874 | **YES** for all listed |
| github.com (datalab-to/marker, opendatalab/MinerU, opendatalab/OmniDocBench, opendatalab/UniMERNet, allenai/olmocr, docling-project/docling, illuin-tech/colpali, lean-dojo/ReProver, jinaai/late-chunking) | repo metadata + release notes + license files | **YES** — license + maintenance signals |
| NeurIPS 2024 D&B track | MathPile data card | **YES** |
| CVPR 2025 | OmniDocBench, CDM | **YES** |
| AAAI 2025 | Docling | **YES** |
| ICLR 2025 | ColPali | **YES** |
| EMNLP 2025 / ACL 2025 findings | Hierarchical Document Refinement (2025.acl-long.176), Towards Advanced Math Reasoning (2025.emnlp-main.628), READOC (2025.findings-acl.1128) | **YES** for chunking; SOFT for math-reasoning |
| Survey paper | "Autoformalization in the Era of Large Language Models: A Survey" arXiv:2505.23486 | **YES** — confirms def-grounding theme |
| Vendor blogs (Jina, Datalab, IBM Research, Ai2 newsletter) | Late-chunking writeup, Marker release tweets, Granite-Docling blog, July-2025 Ai2 newsletter | **MEDIUM** — useful for "is this maintained" but discount hype |

---

## 4. Themes (what's gaining momentum)

**(a) VLM-based PDF parsers have eclipsed Marker / Nougat on math
fidelity in 2024-2026, with CDM as the consensus metric.** MinerU 2.5
(96.4 CDM SCE), olmOCR 2 (Apache-2.0, RLVR-trained), Granite-Docling
(IBM, MathML-native) all post-date the deep dive's snapshot and all
out-score Marker on the formal benchmarks. The Marker recommendation
in `pdf-capability-deep-dive.md:220-230` is **2025-vintage and
arguably stale** as a primary; it's defensible as the lower-bound
alternative.

**(b) The autoformalization community is consolidating on Mathlib +
def-graph + premise-selection — textbook PDF ingest is treated as an
upstream problem they outsource.** ProofNet (textbook exercises),
MMA (88k NL/Lean), Lean-STaR, MathPile's Textbooks slice all use
*already-extracted* text, not raw PDFs. The graph-augmented premise
selection work (arXiv:2510.23637) is the strongest evidence that
**arXMCP's existing Kùzu graph + definitions table is the right place
to invest** if the goal is autoformalizer support. Definition-grounding
(arXiv:2502.12065) is a +16-43% lever that arXMCP can implement on
the existing definitions surface today, independent of any PDF work.

**(c) Hierarchical chunking is the consensus answer for long-document
RAG, with the textbook book/chapter/section/exercise hierarchy as the
canonical motivating example.** HiChunk, late chunking, GraphRAG's
community hierarchies all point the same direction. arXMCP's
theorem-aware chunker is ahead of the curve for papers; a parallel
textbook-aware chunker fits the same shape.

**(d) Visual document retrieval (ColPali / ColQwen2) is a real second
front but not yet ripe for arXMCP's fidelity contract.** Page-image
late-interaction beats text-RAG on visually-rich docs but doesn't
produce MathML — incompatible with arXMCP's downstream chunker /
embedder / definitions chain. Park for v2 with a clean un-park
trigger ("commutative diagrams become a load-bearing user need").

---

## 5. Already in arXMCP / already considered

- **Theorem-aware chunker (theorem + proof pairing):** shipped in E02;
  source `ingest/chunker.py:1-N`; design rule
  `.claude/notes/04-parsing-and-chunking.md:75-82` ("Rule 1: Theorem +
  proof are one chunk"). Do NOT propose duplicating.
- **Per-paper preamble prepended to embedding:** shipped E02_S02;
  `ingest/preamble.py`; design `.claude/notes/04-parsing-and-chunking.md:84-91`.
  Late chunking (§2.5 above) is a **complement** — it makes the
  preamble-as-context idea apply across **arbitrarily-long
  prior text** (entire textbook), not just the per-paper preamble.
- **Three-level hierarchical index (paper/section/theorem):**
  shipped; `.claude/notes/04-parsing-and-chunking.md:108-117`. HiChunk
  (§2.9 above) **extends** this with explicit book / chapter /
  exercise levels for the textbook path.
- **Per-paper notation/definition table + `get_definitions`:**
  shipped E10_S01; `server/handlers/definitions.py`,
  `ingest/index_definitions.py`,
  `.claude/notes/05-storage-and-indexing.md:91-104`. The autoformalization-
  in-the-wild work (§2.6 above) is the **literature confirmation** that
  this is the right shape; suggests a recursive expansion helper.
- **Kùzu citation graph + `cite_neighbors`:** shipped E09;
  `server/graph_queries.py`, `ingest/kuzudb_schema.py`,
  `.claude/notes/05-storage-and-indexing.md:166-227`. The
  graph-augmented premise selection literature (§2.7 above) is the
  reference design for adding a GNN reranker over this existing graph.
- **BGE-M3 dual-column embedder, BGE-reranker-v2-m3:** shipped E03 +
  E07_S03; `ingest/embedder.py`, `server/retrieval/rerank.py`.
  Cross-checked: none of the surveyed embedders (Jina-V3 for late
  chunking, Qwen2-VL for ColQwen2) propose replacing BGE-M3 wholesale;
  they propose **augmenting** with new pipelines.
- **ar5iv HTML cache → LaTeXML → "Nougat deferred":**
  `.claude/notes/04-parsing-and-chunking.md:8-30`; Nougat's
  deferral is upheld (it's unmaintained); the **named successor in
  the literature is olmOCR 2 + MinerU 2.5 + Granite-Docling**, not
  Nougat.
- **Marker mentioned as Nougat alternative, ranked behind LaTeXML on
  source:** `.claude/notes/04-parsing-and-chunking.md:40-43`;
  `pdf-capability-deep-dive.md:220-230` upgrades Marker to recommended
  Path-A primary. **This brief argues for replacing Marker as the
  recommendation with olmOCR 2 or MinerU 2.5 + LaTeXML** (better
  licensed in olmOCR 2's case; better math fidelity per CDM in MinerU
  2.5's case; Marker remains a fallback). The deep dive's
  Path-A scope (M, 2-3 milestones) is unchanged — only the parser
  identity shifts.
- **ColBERTv2 reserved for v1.5 long-chunk handling:**
  `.claude/notes/05-storage-and-indexing.md:298-306`. ColPali /
  ColQwen2 (§2.8 above) sit at the same v1.5+ tier as visual-retrieval
  successors.
- **Equation embeddings (TED equation index):** shipped E10_S03 +
  `ingest/embed_equations.py`, `ingest/extract_equations.py`,
  `server/handlers/equation.py`, `server/retrieval/equations.py`. The
  UniMERNet equation-recognition pipeline (§2.1 above) is the *parser*
  for equations — the existing arXMCP equation-embedding work assumes
  equations have already been extracted as LaTeX/MathML.

---

## 6. Out of scope / parking lot

- **Mathpix as primary parser** — closed, hosted, per-page pricing.
  Same disqualification as `pdf-capability-deep-dive.md:240-243`.
  Possible one-time offline batch exception for high-value
  textbooks if MinerU / olmOCR fidelity falls short on a specific text.
- **PaddleOCR-VL** (arXiv:2601.21957) — strong on OmniDocBench v1.5
  but PaddlePaddle dependency adds a 2GB toolchain footprint that's
  hostile to arXMCP's single-workstation contract. Skip unless
  per-page numbers materially beat MinerU/olmOCR (so far they don't —
  92.16 overall, 91.80 formula-CDM, comparable to MinerU 2.5).
- **DeepSeek-OCR-3B** — strong but newer than olmOCR 2 and less
  field-tested. Track for 2026 H2 re-eval. Park.
- **GraphRAG (Microsoft)** as a *replacement* for arXMCP's retrieval
  stack — overkill, would replace the entire retrieval surface for
  marginal benefit on a corpus where citation edges already exist.
  The "community summaries" idea is interesting for *paper-level
  abstracts of theorem clusters* but is a v3+ feature. Park.
- **NaturalProver / earlier autoformalizer corpora** — predates the
  24-month window; already covered in
  `.claude/notes/10-references-and-prior-art.md`. No textbook-ingest
  signal that's not already captured by ProofNet + MathPile.
- **MathVista / MathVerse / We-Math** (visual-math reasoning
  benchmarks) — these test **VLM math reasoning**, not PDF parsing.
  Out of scope for ingest; arXMCP doesn't ship a VLM. Park as
  reference for any future visual-retrieval milestone.
- **TikZ-cd → graph reconstruction** — no published 2024-2026 paper
  found. The problem is recognized (referenced in BRIEF.md §4) but the
  research community hasn't published a credible automated solution.
  Stays on arXMCP's deferred list per the existing
  `.claude/notes/09-feature-priorities.md` tier-6 stance.
- **SciDef / SciLib-GRC21** — directly relevant to definition
  extraction but specific to RDF / ontology contracts that don't fit
  arXMCP's Kùzu schema. Useful for **ideas** (definition graph =
  first-class extracted structure) but not as code.
- **OCR of pre-2007 scanned arXiv** — explicit non-goal per the
  deep-dive constitution; respected here.
- **PDF figure extraction** — explicit Tier-6 non-goal; respected.

---

## Sources (URLs cited)

- arXiv:2409.18839 (MinerU) — https://arxiv.org/pdf/2409.18839
- arXiv:2412.07626 (OmniDocBench) — https://arxiv.org/html/2412.07626v1
- arXiv:2409.03643 (CDM) — https://arxiv.org/pdf/2409.03643
- arXiv:2404.15254 (UniMERNet) — https://arxiv.org/abs/2404.15254
- arXiv:2502.18443 (olmOCR) — https://arxiv.org/pdf/2502.18443
- arXiv:2510.19817 (olmOCR 2) — https://arxiv.org/pdf/2510.19817
- arXiv:2407.01449 (ColPali) — https://arxiv.org/abs/2407.01449
- arXiv:2409.04701 (Late Chunking) — https://arxiv.org/abs/2409.04701
- arXiv:2509.11552 (HiChunk) — https://arxiv.org/html/2509.11552v2
- arXiv:2312.17120 (MathPile) — https://arxiv.org/abs/2312.17120
- arXiv:2302.12433 (ProofNet) — https://arxiv.org/pdf/2302.12433
- arXiv:2504.21801 (DeepSeek-Prover-V2) — https://arxiv.org/abs/2504.21801
- arXiv:2502.12065 (Autoformalization in the Wild) — https://arxiv.org/pdf/2502.12065
- arXiv:2510.23637 (Graph-augmented premise selection) — https://arxiv.org/pdf/2510.23637
- arXiv:2505.23486 (Autoformalization Survey) — https://arxiv.org/html/2505.23486v1
- arXiv:2409.05137 (READOC) — https://arxiv.org/html/2409.05137v1
- arXiv:2512.09874 (Math formula extraction benchmark Dec 2025) — https://arxiv.org/pdf/2512.09874
- OmniDocBench repo — https://github.com/opendatalab/OmniDocBench
- MinerU repo — https://github.com/opendatalab/mineru
- olmocr repo — https://github.com/allenai/olmocr
- docling repo — https://github.com/docling-project/docling
- marker repo — https://github.com/datalab-to/marker
- ColPali repo — https://github.com/illuin-tech/colpali
- Late-chunking writeup — https://jina.ai/news/late-chunking-in-long-context-embedding-models/
- Granite-Docling overview — https://www.ibm.com/granite/docs/models/docling
- LeanSearch v2 — https://arxiv.org/html/2605.13137v2
- LeanExplore — https://arxiv.org/html/2506.11085v1
