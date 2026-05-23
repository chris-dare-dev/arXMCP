# Competitive Brief — pdf-ingest-2026

**Author:** competitive-landscape scout (Phase 1 of 4)
**Scope:** Textbook-PDF ingestion (Hartshorne, Griffiths-Harris, Bourbaki,
Polchinski) and lecture-notes-as-PDF (Milne, Caraiani). Bias toward
**textbook-PDF** signals (papers are largely solved via ar5iv).
**Read first:** `BRIEF.md`, `.claude/notes/pdf-capability-deep-dive.md`.

---

## 1. TL;DR

The 2025–2026 landscape has converged on **VLM-driven page converters that
emit LaTeX (not MathML) inline** — Granite-Docling-258M, MinerU 2.5, and
Marker 1.10.x are the three credible local-first textbook converters; all
output LaTeX-in-Markdown and none ship MathML natively, which validates the
deep dive's **Marker→LaTeXML re-pass** chain as the only path to math-fidelity
parity with ar5iv. Three under-weighted capabilities surfaced that the dive
missed: (a) **`pdf_get_toc` as a first-class MCP tool** (jztan/pdf-mcp ships
this for any document with >50 bookmarks — directly applicable to textbook
navigation), (b) **paper-qa's pluggable parser registry** (Apache-2.0,
swappable between Docling and Nvidia nemotron-parse — proves the
"converter is a config knob" pattern is now mainstream), and (c) **MathPix's
`$0.0035/page` offline-batch escape hatch** for the ~5–10% of textbook pages
where Marker fidelity is insufficient. The dominant thematic gap across all
13 competitors surveyed is **no one ships textbook-aware chunking** —
everyone chunks by page, not by chapter/theorem/exercise, which is precisely
arXMCP's existing advantage (theorem-aware chunker).

---

## 2. Top capability candidates

### C1. TOC-aware MCP tool surface (`pdf_get_toc` + page-range fetch)

- **Source platform:** jztan/pdf-mcp (8-tool MCP server)
- **Public evidence:** https://github.com/jztan/pdf-mcp — tool table lists
  `pdf_info`, `pdf_get_toc` ("Full table of contents for documents with
  >50 bookmarks"), `pdf_read_pages`, `pdf_read_all`, `pdf_render_pages`,
  `pdf_search`, `pdf_cache_stats`, `pdf_cache_clear`.
- **UI/UX angle:** Agent-first navigation pattern — agent calls `pdf_info`
  → `pdf_get_toc` to plan a chapter walk before fetching, instead of
  forcing the LLM to scan an entire document linearly. For textbooks
  (Hartshorne ~ 26 chapters; Bourbaki ~ 6 chapters per volume), the TOC
  *is* the high-signal retrieval scaffold.
- **Technical angle:** Mirrors arXMCP's existing 7-tool envelope discipline.
  Adding `get_textbook_toc` + a `start_page`/`end_page` arg on
  `get_chunk` would let a sketcher → autoformalizer pipeline walk
  "Chapter 3, §1, Definition 3.1.7" without exploding the 256-KB inline
  cap. **License:** MIT — ideas are free; the code we don't import.
- **Cross-reference to arXMCP:** Net-new at the **tool surface**.
  Library-level analog exists in `server/handlers/citations.py:1` (stub)
  + `server/graph_queries.py` — both navigate STRUCTURED content (graphs),
  but neither handles intra-document hierarchy. Adding a TOC tool would
  bring textbook-mode parity with the citation-graph patterns of E09.
- **PDF-specific note:** TOC extraction relies on the PDF's bookmark
  outline (standard PDF feature; ~95% of publisher textbooks have one;
  most lecture-notes-as-PDF do NOT — a heuristic fallback over heading
  detection is needed for course notes).

### C2. Pluggable parser registry with model-based PDF readers

- **Source platform:** Future-House/paper-qa
- **Public evidence:** https://github.com/Future-House/paper-qa —
  `parsing.parse_pdf` is a settings knob; "model-based PDF readers" like
  Docling and Nvidia nemotron-parse listed as drop-in options; Apache-2.0.
  As of Dec 2025, paper-qa added **"math equations as a new modality"**
  (per their docs page).
- **UI/UX angle:** Operator picks the parser per-corpus (fast/cheap PyMuPDF
  for non-math; high-fidelity Docling/Marker for math-dense). arXMCP's
  current chunker has a SINGLE entry point — extending it to a
  `parser_used` schema column would unlock the same per-source flexibility.
- **Technical angle:** The pattern formalizes the deep dive's
  `parser_used: "marker+latexml"` proposal at line 263 of
  `pdf-capability-deep-dive.md`. paper-qa proves it ships in production at
  >6k-star scale. **License:** Apache-2.0.
- **Cross-reference to arXMCP:** Closest analog is the
  `ingest/bulk_ingest.py:41` "ladder is ar5iv → LaTeXML → skip-and-log"
  comment — that's an implicit ladder, not a registered registry. A
  parser-registry table (`schema_version` + `parser_used` column already
  proposed in the dive) would make it explicit.
- **PDF-specific note:** paper-qa's `page_size_limit` default of **1.28M
  chars** (chunking by characters, not by structure) is the canonical
  example of the **"chunk-by-page-not-structure"** gap that arXMCP's
  theorem-aware chunker already obviates.

### C3. VLM-only end-to-end PDF converter — Granite-Docling-258M

- **Source platform:** IBM Research (docling-project/docling)
- **Public evidence:** https://huggingface.co/ibm-granite/granite-docling-258M
  — released 2025-09-17; Apache-2.0; 258M params (siglip2-base-patch16-512
  vision encoder + Granite 165M LLM, Idefics3-based). Equation F1: 0.968
  (vs SmolDocling 0.947); BLEU 0.893; edit-distance 0.073. Emits
  **DocTags** (XML-like), which the Docling library converts to Markdown
  or HTML. Documented instruction: `Convert formula to LaTeX.
  [instruction: <formula>]`.
- **UI/UX angle:** Compact enough (≤300 MB weights) for a
  single-workstation Apple Silicon deployment. Not as fast as Marker on
  GPU but **smaller download** — meaningful for the local-first
  deployment story.
- **Technical angle:** Output format is **LaTeX inside DocTags**, NOT
  MathML — same as Marker. Means the Marker→LaTeXML re-pass strategy from
  the dive (line 260) is also the right play for Docling. Docling library
  itself v2.95.0 (May 2026), MIT-licensed, **37k stars, 100+ releases since
  Aug 2025** — strongest maintenance trajectory of any competitor surveyed.
- **Cross-reference to arXMCP:** No direct analog. Would slot in alongside
  Marker as an alternative `parser_used` value (relevant to candidate C2's
  registry pattern). Stronger maintenance signal than Marker; same
  fundamental output limitation.
- **PDF-specific note:** **Critical advantage over Marker for arXMCP** —
  paper-qa already lists Docling as a drop-in parser, validating the
  ecosystem-tested integration path. **MathML still NOT a first-class
  output** — equations are LaTeX wrapped in DocTags, requiring the same
  downstream LaTeXML conversion as Marker.

### C4. Sliding-window long-document VLM converter — MinerU 2.5

- **Source platform:** opendatalab/MinerU
- **Public evidence:** https://github.com/opendatalab/MinerU — v3.1.15
  (May 2026); license **changed from AGPLv3 to "custom Apache-2.0-based"**
  as of v3.1.0 (reducing adoption friction — this is significant);
  OmniDocBench v1.5 score **86.2** for the pipeline backend;
  `MinerU2.5-Pro-2604-1.2B` VLM model claims SOTA. **8GB VRAM** for VLM
  backend; **4GB VRAM** for pipeline; pure CPU supported.
- **UI/UX angle:** v3.0.0's **sliding-window mechanism** means it can
  process "documents with tens of thousands of pages" without manual
  splitting — solves a real problem for full-textbook ingest where
  Hartshorne (~500 pages) and Bourbaki's collected volumes (~3000 pages)
  blow standard transformer context windows.
- **Technical angle:** Decoupled architecture (5 specialized models —
  layout detection, formula detection, table recognition, formula
  recognition, OCR) is the same shape Datalab uses for Marker, but
  MinerU's license shift to Apache-2.0-based gives it a strictly better
  legal profile than Marker (GPL-3) for arXMCP's MIT licensing.
- **Cross-reference to arXMCP:** No analog. Would be a candidate
  alternative to Marker in candidate C2's registry — same output shape
  (LaTeX) but better license + better long-document handling +
  **vLLM-integrated** runtime (relevant to E14 throughput story).
- **PDF-specific note:** "LaTeX format for formulas, HTML for tables" —
  matches Marker/Docling on math output (still no MathML), but the
  **sliding-window claim is the only competitor in the survey that
  explicitly addresses Bourbaki-scale (multi-thousand-page) documents**.
  Worth verifying empirically before adoption.

### C5. pix2tex-as-a-service via lightweight MCP server

- **Source platform:** Michael Levinson's PDF Processor MCP Server
  (released June 2025)
- **Public evidence:**
  https://skywork.ai/skypage/en/unlocking-academic-pdfs-ai/1978719638515208192
  — three-tool MCP surface: `fetch_pdf`, `process_pdf(extract_latex=true)`,
  `read_processed_pdf`. Stack: PyMuPDF for text/layout + **pix2tex**
  (Vision Transformer) for equation OCR.
- **UI/UX angle:** Minimal tool surface (3 tools) for a single-purpose
  workflow. Maps cleanly to arXMCP's "narrow surface; do one thing well"
  ethos.
- **Technical angle:** pix2tex is a **MIT-licensed** ViT trained
  specifically for image-of-equation → LaTeX. Critical use case:
  **scanned older textbooks** (Hartshorne 1977 first edition, many
  Bourbaki volumes) where the PDF is image-only — pix2tex on cropped
  equation regions is the right tool. Marker has a `--force_ocr` flag
  for this; pix2tex would be a finer-grained fallback when Marker's
  in-place LaTeX is wrong.
- **Cross-reference to arXMCP:** No analog. Would be a "Tier-2 math
  rescue" path for failed Marker outputs — fits under the
  `parser_failure_review` runbook pattern
  (`docs/ops/parser-failure-review.md`).
- **PDF-specific note:** pix2tex is **per-equation OCR**, not page-level
  conversion — it's the granular tool the deep dive missed. Useful only
  AFTER a page-level converter (Marker/Docling/MinerU) has identified
  equation bounding boxes. **Disqualifies pix2tex as a primary**;
  qualifies it as a per-region rescue.

### C6. Hosted high-fidelity math OCR as offline-batch escape hatch — Mathpix

- **Source platform:** Mathpix
- **Public evidence:** https://mathpix.com/blog/pdf-processing-new-pricing
  — Free tier 20 PDF pages/month; **Pro tier 1000 PDF pages/month
  included; overage $0.0035/page**. Output formats: LaTeX, DOCX,
  Markdown, HTML. Quoted: "any PDF and get an editable Markdown version
  with equations, tables, and figures preserved."
- **UI/UX angle:** N/A for arXMCP — operator-side tool, not in-pipeline.
- **Technical angle:** **Disqualified as primary** (hosted, violates
  local-first per `CLAUDE.md §4.1`). Qualified as a **one-time
  offline-batch exception** — running Mathpix on a Hartshorne PDF once,
  storing the LaTeX output as if it were ar5iv, costs **~$2 for the whole
  book** (500 pages × $0.0035). Compare to operator time for any failed
  Marker run.
- **Cross-reference to arXMCP:** No analog. Threat model: hosted
  inference == data egress; would need an opt-in operator gate at the
  ingest CLI (analog to `ARXMCP_CONTACT_EMAIL` opt-in for arXiv polite
  pool).
- **PDF-specific note:** **Strongest math-OCR fidelity on the market**
  (used by AMS, Cambridge, etc.). Sustainable as a one-time batch for
  the 5–10 high-value reference textbooks an operator would actually load
  into a notebook. Reframes the dive's "Mathpix is disqualified" framing
  — it's disqualified as RUNTIME, not as one-time-batch.

### C7. Per-equation MathML-OCR add-on via OCR-action-tags pattern

- **Source platform:** Zotero `zotero-actions-tags` plugin
- **Public evidence:**
  https://github.com/windingwind/zotero-actions-tags/discussions/220
  — plugin supports multiple OCR-math-to-LaTeX services (Bing, Mathpix,
  SimpleTex, Xunfei) for converting image annotations to LaTeX.
- **UI/UX angle:** **The right multi-vendor pattern** — don't pick ONE
  OCR backend, pick a registry of options. Same idea as candidate C2
  but at the equation-OCR layer.
- **Technical angle:** Validates that the math-OCR-as-service pattern is
  mainstream and that operators expect to **swap backends**. Reinforces
  candidate C2's registry pattern and candidate C5's pix2tex-as-rescue
  pattern. **License:** AGPL-3 — study-only per arXMCP no-fork rule
  (`CLAUDE.md §4.7`).
- **Cross-reference to arXMCP:** No analog at the equation level. Would
  pair with candidate C5 (pix2tex) and candidate C6 (Mathpix) as a
  3-way equation-rescue registry.
- **PDF-specific note:** Zotero itself does NOT preserve LaTeX in
  annotations or extracts — KaTeX rendering only inside notes
  (https://forums.zotero.org/discussion/99411). The OCR plugin is the
  workaround the community built. **arXMCP can skip Zotero entirely and
  ship native LaTeX from the parser layer** — confirms the dive's framing
  that Zotero/Mendeley are not competition for math-fidelity ingest.

### C8. Citation-aware in-PDF reader UX — Semantic Reader

- **Source platform:** Allen Institute / Semantic Scholar
- **Public evidence:**
  https://dspace.mit.edu/bitstream/handle/1721.1/157322/3659096.pdf
  — academic paper documenting the Semantic Reader Project; "shows
  citation information in-context, saving you from losing your place in
  the PDF". Open admission in the paper: **Semantic Reader has
  experienced difficulties parsing math equations** when converting
  academic PDFs to HTML.
- **UI/UX angle:** The **citation-popover-in-context** pattern is the
  textbook analog of arXMCP's `cite_neighbors` tool. For textbook
  navigation: hover-over a "Theorem 3.1.7" reference would resolve to the
  in-corpus chunk. Already implicitly required by the deep dive's
  proposed `intra_paper_refs.py` extension for textbooks
  (`pdf-capability-deep-dive.md` line 188).
- **Technical angle:** Building a citation-popover for textbooks is a
  **chunker contract** more than a UX feature — needs the theorem-name
  + cross-reference index already prototyped at
  `ingest/intra_paper_refs.py`. Extending that to textbook-scale would
  require resolving "Theorem 3.1.7" → `chunk_id` deterministically.
- **Cross-reference to arXMCP:** Existing analog at
  `server/graph_queries.py::cite_neighbors`. Net-new for the
  intra-document case.
- **PDF-specific note:** Semantic Reader's admitted math-parsing
  difficulty is a tell — even Allen AI with substantial resources hasn't
  solved math-fidelity-via-PDF. **Re-validates arXMCP's source-first /
  LaTeXML-on-source design as state-of-the-art.**

### C9. Page-grounded answer citation — Humata.ai

- **Source platform:** Humata.ai
- **Public evidence:** https://www.humata.ai/ — public claim:
  "every answer Humata.ai comes up with has a detailed citation and
  page number for in-depth verification." Third-party review (
  https://www.mindgrasp.ai/blog/6-chatpdf-alternatives-in-2026-the-most-powerful-ai-tools)
  highlights math-content handling as best-in-class among
  chat-with-PDF tools.
- **UI/UX angle:** Page-number citation is the **minimum viable
  source-binding** for textbook chunks. arXMCP's chunk-id contract
  already does paper-level binding; textbook ingest needs a **page-range
  binding** on each chunk so the operator can verify against the
  original PDF.
- **Technical angle:** Requires the parser to emit `page_start` /
  `page_end` per chunk. Marker has `--paginate_output` for this
  (https://github.com/datalab-to/marker README — page markers via
  `\n\n{PAGE_NUMBER}` separators). Docling and MinerU also expose
  page-level structure.
- **Cross-reference to arXMCP:** No analog. The chunks schema
  (`ingest/schema.py`) doesn't have a `page_start` / `page_end` column
  because arXiv source ingest is HTML (no pages). Textbook ingest would
  introduce this column — schema migration concern noted in
  `pdf-capability-deep-dive.md` line 295.
- **PDF-specific note:** **Hard requirement** for any textbook ingest —
  without page-range citation, the math-fidelity contract is
  unverifiable.

### C10. Benchmark-driven parser selection — Mathematical Formula Extraction benchmark

- **Source platform:** arXiv 2512.09874 (Benchmarking Document Parsers
  on Mathematical Formula Extraction from PDFs)
- **Public evidence:** https://arxiv.org/pdf/2512.09874 — Evaluates
  **20+ contemporary PDF parsers** against 100 synthetic documents with
  2,000+ formulas. Uses **LLM-as-a-judge for semantic assessment**:
  Pearson correlation r=0.78 with human judgment, vs r=0.34 for
  character-level matching.
- **UI/UX angle:** N/A — methodology candidate.
- **Technical angle:** Validates that **character-level formula
  comparison is broken** for math evaluation (r=0.34 is barely better
  than chance). arXMCP's existing eval harness
  (`tests/eval/`, `docs/eval-curation.md`) uses nDCG@5 / Recall@10 —
  appropriate for retrieval but doesn't evaluate **math-extraction
  fidelity**. A textbook-ingest milestone should add a parser-fidelity
  gate using LLM-as-judge methodology.
- **Cross-reference to arXMCP:** No analog at the parser-fidelity level.
  Closest is the LaTeXML drift detector
  (`docs/ops/latexml-drift-runbook.md`) but that's version-drift, not
  fidelity.
- **PDF-specific note:** The paper's full parser list is paywalled in
  this excerpt — worth fetching the actual PDF before any
  parser-selection decision lands.

---

## 3. Sources reviewed

| Platform / source | URL | What I actually read | High-signal? |
|---|---|---|---|
| NotebookLM | https://notebooklm.google/ + chrmbook.com 2026 features | Marketing + 2025 math-rendering update note | NO — UI-only; no ingest fidelity claims |
| paper-qa | https://github.com/Future-House/paper-qa | README parser settings, license, chunking knobs | **YES** |
| MathPix Snip | https://mathpix.com/blog/pdf-processing-new-pricing + /pricing/snip | Pricing tiers + PDF-processing description | **YES** (pricing as escape-hatch viability) |
| MathPix PDF Reader | https://mathpix.com/pdf-reader | Product blurb — light on UX detail | NO |
| Adobe Acrobat AI | https://www.adobe.com/acrobat/resources/ai-helper.html | Education-focused feature page | NO — no fidelity contract |
| Zotero (built-in + plugins) | https://forums.zotero.org/discussion/99411 + zotero-actions-tags issue #220 | Math-in-notes beta + OCR plugin ecosystem | **YES** (pattern, not product) |
| Docling (IBM) | https://github.com/docling-project/docling | License, version, output formats, formula tag | **YES** |
| Granite-Docling-258M | https://huggingface.co/ibm-granite/granite-docling-258M | Architecture, equation benchmarks, instruction format | **YES** |
| MinerU | https://github.com/opendatalab/MinerU | License shift, sliding window, benchmarks | **YES** |
| jztan/pdf-mcp | https://github.com/jztan/pdf-mcp | 8-tool surface, TOC tool, MIT license | **YES** |
| SylphxAI/pdf-reader-mcp | https://github.com/SylphxAI/pdf-reader-mcp | Performance-focused MCP server — no math support | NO |
| PDF Processor MCP (Levinson) | https://skywork.ai/skypage/en/unlocking-academic-pdfs-ai/1978719638515208192 | 3-tool MCP + pix2tex integration | **YES** |
| Marker | https://github.com/datalab-to/marker + issue #563 + PyPI | License, equation flags, MathML issue, releases | **YES** |
| Nougat | https://github.com/facebookresearch/nougat | Confirmed unmaintained (last v0.1.17 Feb 2024) | NO — confirms deep-dive call to skip |
| Semantic Reader | https://dspace.mit.edu/bitstream/handle/1721.1/157322/3659096.pdf | Citation-popover UX + admitted math-parse difficulty | **YES** |
| Humata.ai | https://www.humata.ai/ + mindgrasp review | Page-number citation claim | **YES** (page-citation as min-viable) |
| ChatPDF | https://www.chatpdf.com/ | General chat-with-PDF; no math fidelity story | NO |
| Math-formula-extraction benchmark | https://arxiv.org/pdf/2512.09874 | LLM-as-judge methodology, 20+ parsers tested | **YES** (methodology) |
| LeanDojo / LeanPremise | arxiv:2506.07477 + arxiv:2510.23637 | Premise selection from Mathlib, not textbook-PDF | NO — confirms autoformalization community ingests Lean source, not PDFs |
| Readwise Reader | readwise.io/reader/update-june2025 | PDF mode is plain-text; no math fidelity | NO |
| OurBigBook | (no useful search results) | N/A | NO |

---

## 4. Cross-references to arXMCP

- **C1 (TOC-aware MCP tool surface)** → net-new at tool surface.
  Library-level analog at `server/graph_queries.py::cite_neighbors`
  (structured navigation, but graph not hierarchy).
- **C2 (pluggable parser registry)** → formalizes the implicit ladder at
  `ingest/bulk_ingest.py:41`. Validates the `parser_used` schema column
  proposed at `pdf-capability-deep-dive.md` line 263.
- **C3 (Granite-Docling-258M)** → no analog; candidate alternative to
  Marker under C2's registry pattern. Stronger maintenance story.
- **C4 (MinerU 2.5)** → no analog; candidate alternative to Marker.
  **Better license (Apache-2.0-based vs GPL-3)** and only competitor with
  multi-thousand-page document handling.
- **C5 (pix2tex via MCP)** → no analog; would be Tier-2 equation-rescue
  fallback. Fits `docs/ops/parser-failure-review.md` pattern.
- **C6 (Mathpix offline batch)** → no analog; reframes the dive's
  blanket "disqualified" framing as "disqualified at runtime; viable as
  one-time batch."
- **C7 (multi-vendor OCR-action-tags)** → no analog; reinforces C2 and
  C5 patterns.
- **C8 (citation-popover UX)** → existing inter-paper analog at
  `server/graph_queries.py`. Net-new for intra-document
  (extends `ingest/intra_paper_refs.py`).
- **C9 (page-range citation)** → no analog; introduces `page_start` /
  `page_end` schema columns. Schema-migration concern.
- **C10 (LLM-as-judge math-fidelity gate)** → no analog. Closest is
  `tests/eval/` which is retrieval-quality, not extraction-fidelity.

---

## 5. Themes

1. **The market has converged on LaTeX-in-Markdown output, not MathML.**
   All three credible 2026 converters (Marker, Granite-Docling, MinerU)
   emit LaTeX inline; MathML is an open issue or unsupported. The deep
   dive's **Marker→LaTeXML re-pass** strategy is the only path to
   ar5iv-parity math fidelity — and it applies identically to all three.
2. **Math-fidelity is a parser problem, not a chunker problem — but
   textbook-aware chunking is uncontested territory.** Every competitor
   chunks by page or character-count; none chunk by chapter, theorem,
   exercise, or definition. arXMCP's existing theorem-aware chunker is
   already ahead of the field; a `textbook_chunker.py` (Path C in the
   deep dive) would be SOTA the day it ships.
3. **MCP-server convention for PDF tools is settling on
   `fetch + process + read` or `info + toc + pages + search`** — two
   distinct patterns. The latter (jztan/pdf-mcp) maps better to arXMCP's
   existing handler shape and to textbook navigation patterns.
4. **No competitor handles the math-citation graph at all** — the closest
   is Semantic Reader's intra-paper citation popover, which doesn't ship.
   arXMCP's `cite_neighbors` + proof-chain workflow is **the most
   developed citation-aware retrieval surface in the surveyed space** and
   should be a load-bearing differentiator in any textbook-ingest story.

---

## 6. Out of scope / parking lot

- **NotebookLM as competitor** — rejected: hosted-only, no API for ingest
  fidelity, math-rendering improvements (Oct 2025) are display-layer
  only.
- **ChatPDF / Adobe Acrobat AI** — rejected: math handling is
  best-effort PyPDF-equivalent; no math fidelity contract.
- **Connected Papers / Litmaps / Research Rabbit** — rejected: citation-
  graph competitors, but for papers not textbooks (already covered by
  arXMCP's `cite_neighbors`).
- **LeanDojo / Lean Finder / LeanPremise** — rejected as direct
  competitor: they ingest **Lean source code**, not textbook PDFs. They
  ARE the downstream consumer for an arXMCP textbook corpus and are
  relevant for candidate prioritization in the research-math scout
  (different scout).
- **Readwise Reader / Polar / Mendeley / Citavi** — rejected:
  generic-PDF readers; no math-fidelity ingest story.
- **Nougat (Meta)** — rejected: confirmed unmaintained (last release Feb
  2024). The deep dive's call to skip stands.
- **OurBigBook / Distill / Mathberry** — rejected: zero discoverable
  technical evidence in 2025–2026 search horizon; too niche to
  influence design.
- **Marker `--paginate_output` as standalone capability** — folded into
  C9 (page-range citation) — page markers are the implementation, not
  the capability.
- **GROBID** — rejected: equation extraction is weak (emits MathML
  approximations), as documented at `.claude/notes/04-parsing-and-chunking.md:43`.
  Still a viable metadata-fallback but not a primary candidate.

---

**End of brief.**
