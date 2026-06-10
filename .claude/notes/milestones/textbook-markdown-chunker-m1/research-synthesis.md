# Research Synthesis — textbook-markdown-chunker-m1

Single-mode. Source: [research-brief-1.md](research-brief-1.md). Decisions locked.

## Module + API
- New module `ingest/textbook_markdown_chunker.py`, public
  `chunk_textbook_markdown(slug, paper_id) -> list[ChunkRecord]` (mirrors `chunk_textbook`).
- Constants: `TEXTBOOK_MD_CHUNKER_VERSION = "tmd0.1"`, `TEXTBOOK_MD_PARSER_USED =
  "mineru+markdown"` (separate lineage from the HTML "tv0.1"/"mineru+latexml").
- Reuse (import, don't duplicate): `_flat_paper_id`, `_compute_textbook_chunk_id`,
  `_resolve_notebook_dir`/notebook-dir resolution from `ingest.textbook_chunker`;
  `_ATX_HEADING_RE` from `ingest.textbook_renderer`; `tokenize_body` from
  `ingest.tokenizer`.

## CRITICAL — required store.py change
- Add `"mineru+markdown"` to `_ALLOWED_PARSER_USED` in `ingest/store.py` or
  `write_chunks` raises `ValueError`. (Brief didn't list it; it's mandatory.)

## ChunkRecord contract
- Required positional: `chunk_id, paper_id, kind, section_path (list[str]),
  theorem_name (str|None), theorem_label (str|None), body_text`.
- Stamp: `source_kind="textbook"`, `textbook_slug=slug`,
  `parser_used=TEXTBOOK_MD_PARSER_USED`, `chunker_version=TEXTBOOK_MD_CHUNKER_VERSION`,
  `chapter=<nearest #/## ancestor>`, `page_start/page_end=None`, `preamble_ref=None`,
  `body_tokens=tokenize_body(body_text)` (a STRING; None crashes write).
- `kind` vocabulary: **`"stmt"` / `"proof"` / `"section"`** (NOT "statement").
- `chunk_id = _compute_textbook_chunk_id(slug, "", body_text)`; dedup loop verbatim
  (drop identical body_text; raise on prefix collision w/ different body).

## Algorithm
1. Heading stack: on `_ATX_HEADING_RE` match at depth d, pop entries depth≥d, push
   (d,title). `section_path` = titles in stack; `chapter` = nearest depth-1/2 title.
2. `$$`-atomic accumulation: while accumulated buffer has odd `$$` count, keep
   appending the next block (a `$$…$$` spanning blank lines is NOT split).
3. Token-budget grouping: accumulate paragraph blocks while
   `len(tokenize_body(buf).split()) <= 600` (target); flush before a block would push
   past 1500 (max). Oversized single block → split at sentence (`(?<=[.!?])\s+`) or `$$`
   boundaries; never truncate (`truncated=False`; this is the m12 defect being fixed).
4. Secondary `^Proof[.\s]` split within a group → separate stmt + proof chunks.
5. Kind per chunk from first non-empty line:
   `^(\*\*)?(Theorem|Lemma|Proposition|Corollary|Definition|Remark|Example)` → `stmt`;
   `^(\*\*)?Proof` → `proof`; else `section`. (proof routes embedding_proof via the
   UNCHANGED `_build_embed_record` single source.)
6. No-heading markdown → `section_path=[]`, `chapter=None`, still chunks all blocks
   (fixes the p101-140 0-chunk case). Segment starting mid-section → null breadcrumb
   until first heading (acceptable; document it).

## Wiring
- Add `--chunker {html,markdown}` to `tools/notebook_textbook_ingest.py` (default
  `html`). Branch in `ingest_textbook_paper`: markdown → `chunk_textbook_markdown`.
  Embed→write tail (`_build_embed_record`, `write_chunks`) UNCHANGED.

## Tests (pure-Python, markdown fixtures)
heading→section_path/chapter; token-budget grouping; oversized-block split (not
truncate); `$$` spanning blank lines stays atomic; `$…$`/`$$…$$` preserved byte-for-byte;
stmt/proof/section kind; chunk_id stable + dedup; no-heading markdown still yields
chunks. Plus a store.py test that `mineru+markdown` parser_used is accepted.

## Open questions / External writes
None / none.
