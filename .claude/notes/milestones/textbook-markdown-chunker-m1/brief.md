# textbook-markdown-chunker-m1 — Markdown-native textbook chunker

## PROBLEM

The textbook ingest path chunks via MinerU markdown → LaTeXML → HTML →
`ingest/textbook_chunker.py::chunk_textbook` (section-div extraction). This is
**too coarse and lossy** for dense textbooks, and brittle:

- Only emits a chunk per `ltx_section`/`ltx_subsection` div → for a 241-page book
  (Huybrechts, *Fourier–Mukai Transforms*) it produced **39 chunks for ~200 pages**,
  truncating any section past ~1920 tokens and **dropping all prose not wrapped in a
  section div**.
- Math-dense pages overflow LaTeXML's hard **100-error limit** (`Fatal:too_many_errors`)
  → near-empty render → **0 chunks** (2 of 12 segments / 40 pages lost outright).

The MinerU markdown itself is clean and complete (ATX `#`/`##` headings, paragraph
breaks, `$…$`/`$$…$$` math). Chunking it DIRECTLY sidesteps the LaTeXML render entirely,
captures all content, preserves math, and allows fine token-bounded chunks.

## FIX SCOPE / TASKS

**(a) New markdown-native chunker** — `chunk_textbook_markdown(slug, paper_id)` (new
module `ingest/textbook_markdown_chunker.py`, or a function in `textbook_chunker.py`).
Reads the cached MinerU markdown (locate it under
`notebooks/<slug>/parsed/<flat_paper_id>/**/auto/<stem>.md`; reuse `_flat_paper_id`).
Algorithm:
- Parse ATX headings (`^#{1,6}\s+…`, the same matcher idiom as
  `textbook_renderer._ATX_HEADING_RE`) into a section hierarchy → per-chunk `chapter`
  breadcrumb (nearest `#`/`##` ancestor titles).
- Within each heading's body, group blank-line-separated paragraph blocks into chunks
  up to a token budget (target ~600, hard max ~1500 tokens via the existing
  `ingest.tokenizer`/`tokenize_body`). A single block that alone exceeds the max is
  split at sentence/`$$`-block boundaries — do NOT silently truncate (the m12 truncation
  is the very defect being fixed). Display-math `$$…$$` blocks stay intact within a chunk.
- Preserve `$…$`/`$$…$$` math VERBATIM in `body_text` (BGE-M3 embeds LaTeX-in-text; the
  arXiv chunks already carry math as text — keep parity).
- Best-effort `kind` classification: lines/blocks starting with
  `Theorem|Lemma|Proposition|Corollary|Definition|Remark|Example|Proof` (optionally
  bold `**…**` or numbered `N.N`) → `kind="statement"` (or `"proof"` for `Proof`);
  else `kind="section"`/`"prose"`. The proof/stmt split routes the embedding column
  (`embedding_proof` vs `embedding_stmt`) — keep the SAME single-source routing rule as
  `tools/notebook_textbook_ingest.py::_build_embed_record`.
- Stamp the m7 textbook fields: `source_kind="textbook"`, `textbook_slug=slug`,
  `parser_used` (e.g. `"mineru+markdown"`), a NEW `chunker_version`
  (e.g. `"tmd0.1"` — distinct from the HTML `TEXTBOOK_CHUNKER_VERSION`), `preamble_text=""`
  (m8 OQ-1 — PDF textbooks have no author macros), `page_start/page_end=None`.
- `chunk_id` = the SAME content-addressable scheme
  (`_compute_textbook_chunk_id(slug, preamble="", body_text)`) so the m9
  `textbook:`-prefix ↔ `source_kind` invariant holds and dedup works.

**(b) Wire into ingest** — add a `--chunker {html,markdown}` flag to
`tools/notebook_textbook_ingest.py` (default `html` for back-compat; new path opts in
with `markdown`). The markdown path calls `chunk_textbook_markdown` instead of
`chunk_textbook`; the embed→write tail (`_build_embed_record`, `write_chunks`) is
UNCHANGED. Do NOT regress the existing HTML path or its tests.

**(c) Tests** — markdown fixtures (small synthetic + a trimmed real MinerU sample):
heading hierarchy → breadcrumbs; paragraph grouping respects the token budget;
oversized block is split (not truncated); `$…$`/`$$…$$` math preserved byte-for-byte;
theorem/proof `kind` classification; `chunk_id` content-addressable + stable; empty/no-
heading markdown still yields chunks (the p101-140 case that produced 0 via HTML). Pure-
Python (no MinerU/LaTeXML). Reuse the `ingest/chunker_types.ChunkRecord` contract.

**(d) ruff + full suite green** (~29-66 pre-existing Windows-only failures; prove zero
NEW). Commit per repo conventions; GPG unsigned per known no-key state; never
`--no-verify`.

## CONSTRAINTS / CONTEXT

- Do NOT break the existing HTML chunker (`chunk_textbook`) or `notebook_textbook_ingest`
  default behavior — the markdown chunker is ADDITIVE, opt-in.
- Keep the proof/stmt embedding-column routing as a single source (m12 FM-1: wrong-column
  placement retrieves the wrong body and is NOT caught by `EmbedRecord` validation).
- Windows-native dev; tests via `.venv/Scripts/python.exe -m pytest`. No tool-schema /
  MCP surface touched (`EXPECTED_TOOL_SCHEMA_SHA256` unchanged).
- DOWNSTREAM (after this milestone, OUTSIDE its commit scope): re-chunk the Huybrechts
  book from its 12 cached segment markdowns (concatenate in page order into one
  `textbook:derived-categories` markdown, OR chunk per-segment) via
  `notebook_textbook_ingest --chunker markdown`, into `bridgeland-stability-pdfs`.
  Staging + driver at `var/textbook-staging/` (gitignored), NOT part of this milestone.
- Prior art to mirror: `ingest/textbook_chunker.py` (the m7 HTML chunker — chunk_id,
  source_kind, dedup, ChunkRecord stamping), `tools/notebook_textbook_ingest.py`
  (the embed→write tail + routing), `ingest/textbook_renderer.py` (ATX heading matcher).
