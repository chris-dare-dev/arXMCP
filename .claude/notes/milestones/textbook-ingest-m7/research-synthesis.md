# Research Synthesis — textbook-ingest-m7

**Orchestrator merge** of `research-brief-1.md` (in-codebase) and `research-brief-2.md` (external + failure-mode). The two briefs AGREE on every load-bearing point; the only divergence is a cosmetic version-string choice (resolved in §D1).

## Resolved — all 6 brief open questions (both researchers concur)

1. **ChunkRecord field gap: NONE.** `ingest/chunker_types.py::ChunkRecord` already carries all 7 m2 textbook columns (`source_kind`, `license`, `chapter`, `page_start`, `page_end`, `textbook_slug`, `parser_used`), all optional with arXiv defaults. `to_dict()` serializes them with `sort_keys=True` (golden-fixture determinism is free). **m7 does NOT extend ChunkRecord and does NOT bump `CHUNKER_VERSION`.**

2. **HTML5 → granularity mapping.** `ingest/chunker.py::_SECTION_DIV_CLASSES` (line 154) ALREADY includes `ltx_chapter`. LaTeXML emits `\chapter` as `<section class="ltx_chapter">` with `<h2 class="ltx_title ltx_title_chapter">` (verified by brief-2 against the real corpus file `var/arxmcp/corpus/parsed/1306.2070/index.html`). `_extract_section_path` already walks chapter ancestors. **What's missing: a dedicated `_extract_chapter_label(tag)` helper that walks ancestors for the `ltx_chapter` div and pulls its title for `ChunkRecord.chapter`** — the existing path walker returns a generic breadcrumb, not the chapter label specifically.
   - v0 granularity cut: `ltx_chapter` → populate `chapter`; `ltx_section`/`ltx_subsection`/`ltx_subsubsection` → section-level. NO definition/exercise levels (challenger F2 Won't-list).

3. **Read path / write path.** Read: `var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/index.html` (`flat_paper_id = paper_id.replace("/","_").replace(":","_")`). Write chunk JSONs: `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/` (mirrors arXiv `corpus/chunks/<paper_id>/` but notebook-scoped). The chunk-JSON path is orthogonal to spike-3's LanceDB isolation contract.

4. **page_start/page_end: NULL in m7.** MinerU's `content_list.json` carries `page_idx` per block, but the m6 Strategy-A pipeline (markdown → LaTeX → LaTeXML HTML5) does NOT propagate page metadata into `index.html`. No code currently reads `content_list_path` for page info. v0 leaves the columns NULL; the chunker carries a `# m8: populate from content_list.json correlation` comment as the future hook.

5. **chunker_version: separate constant (see §D1 for the exact string).** A textbook-only chunker change must NOT trigger arXiv corpus re-embedding (which a `CHUNKER_VERSION` bump in `chunker_types.py` would force via `tests/test_re_embed.py::TestChunkerVersionFreeze`). Define a module-level constant in `textbook_chunker.py`.

6. **Golden fixture: project-original synthetic HTML5.** Both researchers independently concluded: the live Stacks Project does NOT use LaTeXML (custom MathJax renderer; the 4-char tags are Stacks-internal), so a "pre-parsed Stacks chapter" fixture would require running LaTeXML against their GPL+GFDL source — impractical + license-encumbering for a committed fixture. Synthesize HTML5 mimicking the verified LaTeXML `ltx_chapter`/`ltx_section`/`ltx_theorem`/`ltx_proof` shape. Precedent: `.claude/docs/chunker-fixtures.md` — "all 10 fixtures are hand-crafted HTML (not LaTeXML output)."

## D1 (COSMETIC) — TEXTBOOK_CHUNKER_VERSION string

- Brief-1: `"v0.1"`. Brief-2: `"tv1.0"`.
- **Resolution: `"tv0.1"`** — combines brief-2's distinct `t`-prefix (visually separates textbook chunks from arXiv `v1.1` in any version-grouped query) with brief-1's v0 signal (this is the v0 cut; book/chapter/section only, no definition/exercise). Pin this verbatim in the golden-fixture expected JSON.

## LOAD-BEARING implementation constraints (from both briefs)

These are NOT optional — each is a verified gap or a failure-mode mitigation:

1. **Do NOT call `_compute_chunk_id`.** `ingest/chunker.py:1050` hardcodes `return f"arxiv:{paper_id}:{digest}"`. Calling it with `paper_id="textbook:my-book"` produces `arxiv:textbook:my-book:<sha>` — INVALID per `CHUNK_ID_PATTERN`. Implement `_compute_textbook_chunk_id(slug, preamble_text, body_text) -> f"textbook:{slug}:{digest}"` reusing the SAME hash discipline (NFC normalize → UTF-8 → sha256 → 16-hex). Verify output passes `ingest/identifiers.py::is_valid_chunk_id`.

2. **Do NOT call `_resolve_preamble_doc`.** It resolves `var/arxmcp/corpus/preamble/<paper_id>...` (the arXiv preamble store) — wrong tree for textbooks, and the `:` in `textbook:slug` is an invalid path byte. Use `preamble_text = ""` in v0 with a `# TODO(m8): per-chapter preamble inheritance` comment.

3. **Implement the dedup loop (brief-2 FM-4 — load-bearing).** `_chunk_paper_impl` (chunker.py:940-960) keeps a `seen: dict[chunk_id -> ...]` and drops legitimate duplicates. WITHOUT it, two textbook sections with identical body text + empty preamble produce the SAME `textbook:<slug>:<sha>` chunk-id → the second JSON OVERWRITES the first on disk → silent chunk loss. The textbook chunker MUST replicate this dedup discipline. Empty-preamble v0 makes collisions MORE likely (no preamble entropy to disambiguate), so this is not theoretical.

4. **`lancedb_path` is a REQUIRED arg (brief-2 FM-5 — spike-3 regression).** If m7 wires a LanceDB write, `chunk_textbook` must take `lancedb_path` explicitly (not optional-with-default) and pass it to `ingest.store.write_chunks`. Omitting it writes to the shared arXiv corpus (`DEFAULT_LANCEDB_PATH` under `var/arxmcp/index/`) — the exact spike-3 regression. **HOWEVER** — m7's scope (per the brief) is "emit ChunkRecords + write chunk JSONs; embedding/LanceDB-write is downstream." So m7 may NOT call `write_chunks` at all. If it doesn't, this constraint is moot for m7 but the isolation regression test still asserts the boundary. Decision: **m7 writes chunk JSONs only, does NOT write to LanceDB** (matches `chunk_paper`'s contract — `chunk_paper` writes JSONs, a separate embed step loads LanceDB). The isolation test stays green because m7 touches no LanceDB path.

5. **No-crash on missing chapter structure (brief-2 FM-1).** A textbook compiled with `article` class (no `\chapter`) emits only `ltx_section`. `chapter = None` is a valid state. DEBUG-log "no chapter structure detected", continue. Test the no-chapter input.

6. **Cross-chapter theorem pairing terminates correctly (brief-2 FM-2).** The existing `_is_structural_sibling` breaks the pairing scan at a new `section` element — so a theorem in chapter 1 never pairs with a proof in chapter 2. Correct behavior; assert it in a test (no code change).

7. **Token-budget discipline reused (brief-2 FM-3).** Book/chapter-level chunks can be huge; reuse `_truncate_to_token_budget` exactly as `_extract_section_chunks` does. The WARNING log on truncation is load-bearing operator signal.

8. **Read-path builder, not `PARSED_DIR`.** `_chunk_paper_impl` reads `PARSED_DIR/<paper_id>/index.html` (arXiv tree). The textbook chunker needs its own path builder for the notebook-scoped tree.

## Orchestrator synthesis note — final decisions

1. **Module:** `ingest/textbook_chunker.py`, thin driver reusing chunker.py primitives.
2. **Entry point:** `chunk_textbook(slug: str, paper_id: str) -> list[ChunkRecord]`. Reads notebook-scoped HTML5, writes chunk JSONs to `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/`, returns the records. Resilience envelope mirrors `chunk_paper` (`PER_PAPER_FAILURE_EXCEPTIONS` catch → failure-log row → `[]`; programmer bugs propagate).
3. **Three textbook-specific additions:** `_textbook_html_path(slug, paper_id)` read-path builder; `_compute_textbook_chunk_id(slug, preamble, body)`; `_extract_chapter_label(tag)`.
4. **Reuse verbatim:** `_extract_section_path`, `_extract_chunks_from_container`, `_env_kind`, `_is_theorem_like`, `_window_proof_text`, `_truncate_to_token_budget`, `_count_tokens`, `_is_structural_sibling`. Plus the dedup loop pattern from `_chunk_paper_impl`.
5. **Version:** `TEXTBOOK_CHUNKER_VERSION = "tv0.1"` (module-local). Each ChunkRecord's `chunker_version` set to it. Do NOT touch `chunker_types.py::CHUNKER_VERSION`.
6. **Preamble:** `""` in v0. page_start/page_end: `None`. `parser_used="mineru+latexml"`, `source_kind="textbook"`, `textbook_slug=slug`.
7. **LanceDB:** m7 does NOT write LanceDB (JSON-only, matching `chunk_paper`). Embedding is downstream.
8. **Fixture:** project-original synthetic HTML5 under `tests/fixtures/textbook_chunker/<id>/index.html` + committed `expected.json` (with `tv0.1` pinned). Regeneration runbook under `.claude/docs/textbook-chunker-fixtures.md`.
9. **No BP1 / tool-schema change** (ingest-side only — both confirm).
10. **Three-copy paper_id lock untouched** (m7 adds no new alternative).

## Open questions (after synthesis)

None block implementation. All 6 brief questions resolved; the 8 load-bearing constraints above are the implementer's contract.

## External writes the implementation will require

| type | target | why | blocking? |
|---|---|---|---|
| (none) | | | |

Purely local. Deliverables: `ingest/textbook_chunker.py` (new), `tests/test_textbook_chunker.py` (new), `tests/fixtures/textbook_chunker/` (new fixture + expected.json), `.claude/docs/textbook-chunker-fixtures.md` (new runbook). No git push, no GH issue, no infra mutation, no MCP surface change.

## Size estimate + path

- `ingest/textbook_chunker.py`: ~220 LOC (thin driver + 3 helpers + dedup loop + resilience envelope).
- `tests/test_textbook_chunker.py`: ~280 LOC (structure-detection units, golden-fixture diff, chunk-id round-trip, no-chapter input, cross-chapter pairing assertion, resilience).
- `tests/fixtures/textbook_chunker/`: 1 synthetic HTML5 fixture + expected.json.
- `.claude/docs/textbook-chunker-fixtures.md`: ~40 LOC runbook.

Total ~550 LOC across ~5 files. Borderline INLINE/DELEGATED, but it is ONE coherent module + its tests + fixture — no clean two-part partition. **Recommendation: INLINE.** (Same reasoning as m5: a thin driver + tests is one logical unit; delegating would split the test file from the module.)
