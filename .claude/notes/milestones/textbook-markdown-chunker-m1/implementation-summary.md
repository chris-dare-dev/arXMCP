# Implementation Summary — textbook-markdown-chunker-m1

**One-line:** New `chunk_textbook_markdown` chunks MinerU markdown directly
(heading + paragraph + token-window, math preserved) — no LaTeXML render — so dense
textbooks yield fine, complete chunks instead of a few truncated section-grain ones.

**Path:** inline. **Commit range:** filled at finalize.

## What landed

- `ingest/textbook_markdown_chunker.py` (NEW): `chunk_textbook_markdown(slug, paper_id)`
  + pure core `_chunk_markdown_impl(slug, paper_id, markdown)`. Reads the cached MinerU
  markdown (`parsed/<flat>/**/auto/*.md`). Heading-stack → `section_path`/`chapter`;
  `$$`-atomic paragraph blocks (parity-merge so a display block spanning a blank line is
  never split); token-budget grouping (target 600 / max 1500, never truncate; oversized
  blocks sentence-split with a math-parity guard); `stmt`/`proof`/`section` kind from the
  first line; a new stmt/proof lead flushes the buffer so proof chunks route to
  `embedding_proof`. Reuses `_compute_textbook_chunk_id`, `_flat_paper_id`,
  `_resolve_notebook_dir` (from `textbook_chunker`), `_ATX_HEADING_RE` (from
  `textbook_renderer`), `tokenize_body`. Constants `TEXTBOOK_MD_CHUNKER_VERSION="tmd0.1"`,
  `TEXTBOOK_MD_PARSER_USED="mineru+markdown"` (separate lineage).
- `ingest/store.py`: added `"mineru+markdown"` to `_ALLOWED_PARSER_USED` (CRITICAL — else
  `write_chunks` raises on every markdown chunk).
- `tools/notebook_textbook_ingest.py`: `--chunker {html,markdown}` flag (default `html`,
  back-compat). `markdown` calls `chunk_textbook_markdown`; the embed→write tail
  (`_build_embed_record`, `write_chunks`) is UNCHANGED.
- `tests/test_textbook_markdown_chunker.py` (NEW, 16 tests): stamping + store-allowlist,
  chunk_id stability + dedup, heading hierarchy + chapter, no-heading-still-chunks,
  stmt/proof/section kinds + Proof split, inline/display math preserved, `$$`-spanning-
  blank-lines atomicity, token-budget grouping, oversized-block split (not truncated).

## Acceptance criteria

- (a) Markdown-native chunker. ✅
- (b) `--chunker` flag wired, HTML default unchanged. ✅
- (c) 16 tests; ruff clean. ✅
- (d) Suite green; only pre-existing Windows symlink failure in touched modules. ✅

## End-to-end proof (real Huybrechts segments)

`chunk_textbook_markdown` on the parsed book segments vs the old HTML chunker:
- `p001-020`: 20 chunks (was 6) — 11 section / 8 proof / 1 stmt
- `p101-120`: **18 chunks (was 0 — recovered the lost segment)**
- `p121-140`: **24 chunks (was 0 — recovered)**
Token sizes bounded (avg ~350-466, max ~640); math preserved (`$$\begin{array}…` intact).
Extrapolates to ~240 chunks for the 241-page book vs 39 via HTML.

## External writes
None — purely local.

## Deviations
- Trailing prose after a proof joins the proof chunk (kept simple to preserve
  multi-paragraph proofs intact rather than fragmenting them at continuation paragraphs).
  Documented in the chunker; the test fixture orders prose before the statement to assert
  the three distinct kinds.

## Downstream (outside commit scope)
Re-chunk the 12 cached Huybrechts segments into `bridgeland-stability-pdfs` via
`notebook_textbook_ingest --chunker markdown`.
