# Implementation Summary — textbook-ingest-m7

**Summary:** Hierarchical textbook chunker (`ingest/textbook_chunker.py`) — the e3 spine. Reads m6's notebook-scoped HTML5+MathML, emits ChunkRecords at book/chapter/section granularity (reusing the existing chunker primitives for theorem/proof pairing), tags them `source_kind="textbook"` with chapter labels, and writes notebook-scoped chunk JSONs. Golden-fixture diff test against a synthetic two-chapter document.

**Commit range:** `03bdcbe..HEAD` (single feat commit + this summary).

## Acceptance criteria status

### Core chunker module
- [x] `ingest/textbook_chunker.py` with `chunk_textbook(slug, paper_id) -> list[ChunkRecord]`. Resilience envelope mirrors `chunk_paper` (`PER_PAPER_FAILURE_EXCEPTIONS` catch → failure-log row → `[]`; programmer bugs propagate; validation outside the envelope).
- [x] Detects book/chapter/section via the shared `_SECTION_DIV_CLASSES` (which already includes `ltx_chapter`). New `_collect_chapter_titles` + `_chapter_for_chunk` map each chunk to its chapter breadcrumb (robust to a `\part` above the chapter — matches against the known chapter-title set, not positional).
- [x] Emits ChunkRecords tagged `source_kind="textbook"`, `chapter=<label or None>`, `textbook_slug=slug`, `parser_used="mineru+latexml"`, `chunker_version="tv0.1"`.
- [x] Reuses theorem/proof pairing primitives verbatim (`_extract_chunks_from_container`, `_extract_section_chunks`) — no reimplementation. Cross-chapter pairing terminates correctly (verified: Ch1 theorem pairs with Ch1 proof, not Ch2's).
- [x] Deterministic chunk-ids via `_compute_textbook_chunk_id` → `textbook:<slug>:<sha>` (NOT the arXiv `_compute_chunk_id` which hardcodes `arxiv:`). Round-trips through `is_valid_chunk_id`.
- [x] Write path notebook-scoped: `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/<hash>.json` + `chunk_manifest.json`. Does NOT write LanceDB (JSON-only, matching `chunk_paper`'s contract — keeps spike-3 isolation untouched).

### Golden fixtures
- [x] `tests/fixtures/textbook_chunker/two-chapter-book/index.html` — synthetic LaTeXML-shaped HTML5 (2 chapters × 1 section, theorem+proof + lemma+proof pairs, chapter prose, inline MathML). Project-original (no Stacks Project content — the live Stacks site uses MathJax not LaTeXML; synthetic avoids license + version-drift).
- [x] `expected.json` committed (6 chunks). Golden-diff test asserts byte-equality.
- [x] Regeneration runbook at `.claude/docs/textbook-chunker-fixtures.md`.

### Tests (26, all always-run)
- [x] Path builders, `_compute_textbook_chunk_id` (prefix, round-trip, determinism, NFC).
- [x] `_collect_chapter_titles` (finds chapters / empty when none).
- [x] Golden-fixture diff + 7 structural assertions (6 chunks, kinds, textbook tags, chapter labels, NULL pages, valid chunk-ids, cross-chapter pairing, JSON written).
- [x] No-chapter input (FM-1: flat article-class → chapter=None, no crash).
- [x] Dedup (FM-4: identical body → one chunk, no overwrite).
- [x] Resilience (missing HTML → `[]` + failure log; invalid slug → ValueError; invalid paper_id → ValueError).

### Out of scope (deferred)
- Per-chapter preamble inheritance — m8 (v0 uses empty preamble; `# TODO(m8)` marker in code).
- ProofNet metadata schema mapping — m8.
- `page_start`/`page_end` population — page metadata lost in m6's markdown→LaTeX→LaTeXML render; stays NULL in v0 (`# TODO(m8)` marker).
- Definition/exercise chunk levels — e3-v1 (challenger F2 Won't-list).
- LanceDB write + embedding — downstream (m7 emits ChunkRecords + JSONs only).
- `search_papers` surfacing — e4.

## Files changed
- `ingest/textbook_chunker.py` (NEW, ~310 LOC)
- `tests/test_textbook_chunker.py` (NEW, ~310 LOC)
- `tests/fixtures/textbook_chunker/two-chapter-book/index.html` + `expected.json` (NEW)
- `.claude/docs/textbook-chunker-fixtures.md` (NEW runbook)

## External writes required
None — purely local.

## Test counts
- `make test`: **3029 passed, 29 skipped, 1 xfailed, 3 pre-existing failures** (latexmlc SIGABRT + Kùzu graph DB path — unchanged from m6). +26 m7 tests over the 3003 m6 baseline.

## Deviations from the brief
- Both researchers + synthesis converged; no design deviations. Version string resolved to `"tv0.1"` (synthesis §D1). The single-source-of-truth guard (`test_chunker_ids.py`) initially caught a `"v1.1"` literal in a code comment — reworded to a descriptive reference (the guard forbids quoting the arXiv version literal outside `chunker_types.py`).
