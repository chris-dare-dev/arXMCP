# Textbook preamble decision (textbook-ingest-m8, OQ-1)

**Decision:** PDF-sourced textbook chunks carry a **permanently empty
preamble** (`preamble_text = ""`, `preamble_ref = None`). This is the
correct steady state, NOT a v0 placeholder. The textbook chunker
(`ingest/textbook_chunker.py`) builds no preamble extractor and the
m7 `# TODO(m8): per-chapter preamble inheritance` marker is retired.

## Why the roadmap's "per-chapter preamble inheritance" does not apply

The e3 epic outcome (`.claude/roadmap/textbook-ingest-roadmap.md`) reads:
*"Per-chapter preamble inheritance works (textbook-shaped, not
paper-shaped)."* That outcome was written before the PDF-vs-`.tex`
ingest tension was understood. m8 research (both
`research-brief-1.md` and `research-brief-2.md`, independently and
confidently) resolved it as **structurally inapplicable** to the
shipped ingest path.

### The arXiv preamble lever — what it actually does

`ingest/preamble.py::extract_preamble` reads a paper's **root `.tex`
source** under `var/arxmcp/corpus/raw/<paper_id>/` and extracts every
`\newcommand` / `\def` / `\DeclareMathOperator` / `\let` macro
definition into a deterministic `preamble.json`. The embedder
(`ingest/embedder.py`) prepends that `preamble_text` to each chunk's
body before BGE-M3 encoding, so the model sees a macro definition
(`\newcommand{\F}{\mathbb{F}}`) alongside body math that references it
(`\F`). Per `04-parsing-and-chunking.md` this is "the single biggest
retrieval-quality lever after macro expansion" — **because it expands
UNEXPANDED author macros that survive into the arXiv chunk body_text.**

### Why the PDF→MinerU path has nothing to inherit

The textbook ingest path is **PDF → MinerU → markdown → LaTeXML
HTML5** (m5 + m6). At every step, author macros are already gone:

1. **MinerU reads a rendered PDF.** By the time a textbook is a PDF,
   `\F` has been typeset to the glyph 𝔽. MinerU's extraction emits the
   *rendered* form (`\mathbb{F}`), never the author macro `\F`. There
   is no `\newcommand` in MinerU's output — there is no macro layer in
   a rendered PDF to recover.
2. **m6's `main.tex` is an inert envelope.** `textbook_renderer.py`
   wraps MinerU's markdown in `\documentclass{article}
   \usepackage{amsmath,amssymb} \begin{document} … \end{document}`.
   That wrapper has zero author macros — it exists only to give
   `latexmlc` a compilable document. It is NOT a preamble source.
3. **No `.tex` source tree.** `extract_preamble` resolves
   `var/arxmcp/corpus/raw/<paper_id>/` (the arXiv raw tree) and raises
   `FileNotFoundError` otherwise. Textbook PDFs live under
   `var/arxmcp/notebooks/<slug>/` with no `.tex` anywhere.

So a textbook chunk's `body_text` is ALREADY in canonical, fully-
expanded form. Prepending a preamble would add nothing — there are no
unexpanded macros for it to define.

### Why not synthesize a preamble (reading c)

Synthesizing a "common notation" preamble from frequency heuristics or
an LLM pass was rejected: it is non-deterministic across runs (MinerU
version, notation ordering), which violates the BP1 byte-stability
contract (`07-multi-agent-caching.md`). The constitution explicitly
rejects contextual-retrieval-style synthesis for the same reason.

## What a future `.tex`-source textbook path would do

If a later epic adds an ingest path that takes a textbook's **`.tex`
source** (e.g. the Stacks Project or Milne's notes, both distributed
as `.tex`), per-chapter (really book-global; see below) preamble
inheritance becomes real: that path would call
`ingest.preamble.extract_preamble` (or a textbook-shaped variant) on
the source `.tex` and stamp `preamble_ref` on textbook chunks.

Note from m8 research-brief-2: in practice, well-structured LaTeX
textbooks define macros **book-globally** in a single master preamble,
not per-chapter (LaTeX requires macros defined before first use;
chapter `\input` files carry content, not macro definitions). So even
the `.tex`-source path would be book-level preamble inheritance, not
truly "per-chapter" — the roadmap's "per-chapter" framing overstates
the real structure.

## Related deferrals (also NOT m8, also NOT in the e3 outcome)

- **`page_start` / `page_end` correlation.** MinerU's
  `content_list.json` carries a `page_idx` per block, but that metadata
  is lost in the markdown→LaTeX→LaTeXML render — the HTML5 the chunker
  reads has no page attributes. Populating the page columns would
  require correlating `content_list.json` blocks back onto rendered
  chunks, a separate future item. The columns stay `None`.

## Cross-references

- `ingest/textbook_chunker.py` — the empty-preamble decision is encoded
  in `_chunk_textbook_impl` with a pointer to this doc.
- `ingest/preamble.py` — the arXiv `.tex`-source preamble extractor.
- `.claude/notes/04-parsing-and-chunking.md` §Preamble extraction.
- `.claude/notes/milestones/textbook-ingest-m8/research-synthesis.md` §OQ-1.
