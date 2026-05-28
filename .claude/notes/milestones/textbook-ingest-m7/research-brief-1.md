# Research Brief — textbook-ingest-m7

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T03:55:00Z

## In-codebase context

### Open question #1 RESOLVED — ChunkRecord field gap: NO GAP

`ingest/chunker_types.py::ChunkRecord` (lines 48–207, CHUNKER_VERSION = "v1.1") already
carries ALL m2 textbook columns. Verbatim from the dataclass:

```python
source_kind: str = field(default="arxiv")
license: str = field(default="arxiv-license")
chapter: str | None = field(default=None)
page_start: int | None = field(default=None)
page_end: int | None = field(default=None)
textbook_slug: str | None = field(default=None)
parser_used: str | None = field(default=None)
```

The docstring explicitly marks these as "Textbook-specific fields (textbook-ingest-m2).
All optional; the arXiv chunking path leaves them at their defaults." **m7 does NOT need
to extend ChunkRecord or bump chunker_version for field coverage reasons.** The dataclass
is ready. `to_dict()` already serializes all 7 textbook fields.

### Open question #2 RESOLVED — HTML5 structure → granularity mapping

`ingest/chunker.py` defines `_SECTION_DIV_CLASSES` (line 154):

```python
_SECTION_DIV_CLASSES = [
    "ltx_chapter",
    "ltx_section",
    "ltx_subsection",
    "ltx_subsubsection",
    "ltx_paragraph",
    "ltx_subparagraph",
]
```

**`ltx_chapter` is already in this list.** `_extract_section_path(tag)` (line 370) walks
ancestors and includes any element whose classes contain an entry from `_SECTION_DIV_CLASSES`.
`_extract_section_chunks(soup, paper_id, counter)` (line 740) finds all elements matching
any of these classes.

**KEY STRUCTURAL DIFFERENCE for textbooks:** LaTeXML emits `\chapter` as
`<section class="ltx_chapter">` (a `section` tag with `ltx_chapter` class), whereas arXiv
papers typically only use `ltx_section` downward. The existing `_extract_section_path` ALREADY
handles `ltx_chapter` in the ancestor walk. The existing `_extract_section_chunks` finds
`ltx_chapter` elements. However, `_extract_section_chunks` currently emits one `kind="section"`
chunk per section element, with NO granularity distinction between chapter, section, and
subsection. **m7 needs to map granularity levels when populating `chapter`.** The `section_path`
for a theorem inside a chapter will naturally carry the chapter title from `_extract_section_path`;
the `chapter` field specifically needs the chapter-level breadcrumb extracted.

**Concrete approach:** `textbook_chunker.py` can reuse `_extract_section_path` and
`_extract_chunks_from_container` directly. The `chapter` field should be set to the first
breadcrumb entry that comes from an `ltx_chapter` ancestor. Helper to detect whether a
section is chapter-level: check if its CSS class list contains `"ltx_chapter"`.

The heading tags for each level in LaTeXML HTML5:
- `ltx_chapter` → heading `<h1 class="ltx_title ltx_title_chapter">`
- `ltx_section` → heading `<h2 class="ltx_title ltx_title_section">`
- `ltx_subsection` → heading `<h3 class="ltx_title ltx_title_subsection">`

The `_extract_section_path` walker finds titles by looking for children with class containing
`"ltx_title"` — this already works for all levels.

### Open question #3 RESOLVED — Read path + write path

**Read path (confirmed from `textbook_renderer.py`):**
`var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/index.html`
where `flat_paper_id = paper_id.replace("/", "_").replace(":", "_")`.
So `paper_id = "textbook:my-book"` → `flat_paper_id = "textbook_my-book"`.

**Write path decision for chunk JSONs:** The brief proposes
`var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/` (mirroring arXiv's
`corpus/chunks/<paper_id>/`). This is consistent and clean. **No conflict with the
spike-3 isolation contract** — the isolation test (`tests/test_textbook_notebook_isolation.py`)
pins the LanceDB path (`var/arxmcp/notebooks/<slug>/lancedb/`) not the chunk JSON path.
The chunk JSONs are an intermediate artifact; the final store is LanceDB.

The isolation test's final assertion is structural: `write_chunks` must receive an explicit
`lancedb_path = NOTEBOOKS_BASE / slug / "lancedb"` (not the default). The textbook chunker
must pass this explicitly. The test
`test_default_lancedb_path_distinct_from_notebook_paths` pins that DEFAULT_LANCEDB_PATH
is NOT under `/notebooks/` — so a bug that omits `lancedb_path` writes to the shared arXiv
corpus (caught by source_kind enum guard). The chunk JSONs path choice does NOT affect LanceDB isolation.

### Open question #4 RESOLVED — page_start/page_end source

MinerU's `content_list.json` carries a `page_idx` field per content block (0-indexed page
number). However, the LaTeXML HTML5 output (`index.html`) produced by `textbook_renderer.py`
(Strategy A) does NOT propagate page metadata — it re-renders the markdown as LaTeX and then
through LaTeXML; page boundaries are lost in the markdown → LaTeX → HTML5 pipeline.

**No code in the current codebase reads `content_list_path` for page metadata.** The
`MinerUResult` dataclass exposes `content_list_path: Path` but it is only used to confirm
the file exists (location of outputs). The renderer only reads `markdown_path`.

**Recommendation: page columns stay NULL in m7.** Flag the `content_list_path` in the
`chunk_textbook` entry point as a future hook for page-range extraction if a future
milestone adds pre-HTML content_list parsing before the LaTeXML round-trip.

### Open question #5 RESOLVED — chunker_version for textbook chunker

`CHUNKER_VERSION = "v1.1"` in `ingest/chunker_types.py` is the shared version string.
The docstring explicitly says: "Bump this constant in lockstep with any change to chunking
strategy." The versioning note in `04-parsing-and-chunking.md` confirms a version bump
triggers re-embedding.

**Recommendation:** Use a separate `TEXTBOOK_CHUNKER_VERSION = "v0.1"` constant in
`ingest/textbook_chunker.py` (NOT in `chunker_types.py`). Set
`chunk.chunker_version = TEXTBOOK_CHUNKER_VERSION` on textbook chunks. This way:
- Textbook chunks are distinguishable from arXiv chunks by version string.
- A textbook-only chunker change does NOT trigger arXiv corpus re-embedding.
- The existing `tests/test_re_embed.py::TestChunkerVersionFreeze` regression guard covers
  CHUNKER_VERSION in `chunker_types.py` — do not modify that file.
- Golden fixtures for m7 commit `TEXTBOOK_CHUNKER_VERSION = "v0.1"` in their expected JSON.

### Open question #6 RESOLVED — Stacks Project fixture provenance

**Use project-original synthetic HTML that MIMICS the LaTeXML output shape.** The
`.claude/docs/chunker-fixtures.md` explicitly establishes the precedent: "all 10 fixtures
are hand-crafted HTML (not LaTeXML output)" specifically to avoid LaTeXML version drift and
external content dependency. The same rationale applies here. A CC-BY-SA attribution header
in a committed test fixture creates a license obligation on every downstream user.

Synthesize HTML matching LaTeXML's `ltx_chapter` / `ltx_section` structure with realistic
math content (using `<math alttext="...">` wrappers) without copying actual Stacks Project
prose. The fixture lands under `tests/fixtures/textbook_chunker/`.

### Primitive callability from `textbook_chunker.py`

All the following functions in `ingest/chunker.py` are directly callable from a sibling
module (they are module-level functions, not methods, with no arXiv-specific assumptions
in their signatures):

| Primitive | Signature | Reusable as-is? |
|---|---|---|
| `_extract_section_path(tag)` | `(Tag) -> list[str]` | YES — uses `_SECTION_DIV_CLASSES` which includes `ltx_chapter` |
| `_extract_section_chunks(soup, paper_id, counter)` | `(BeautifulSoup, str, list[int]) -> list[ChunkRecord]` | PARTIAL — emits `chunk_id = f"arxiv:{paper_id}:idx{idx}"` placeholder; OK pre-SHA pass |
| `_extract_chunks_from_container(container, paper_id, counter, depth)` | `(Tag, str, list[int], int) -> list[ChunkRecord]` | YES — paper_id agnostic |
| `_env_kind(env_name)` | `(str) -> str` | YES |
| `_is_theorem_like(env_name)` | `(str) -> bool` | YES |
| `_window_proof_text(proof_text)` | `(str) -> list[str]` | YES |
| `_truncate_to_token_budget(text, max_tokens)` | `(str, int) -> tuple[str, bool]` | YES |
| `_compute_chunk_id(paper_id, preamble_text, body_text)` | `(str, str, str) -> str` | YES but HARDCODES `arxiv:` prefix |
| `_resolve_preamble_doc(paper_id)` | `(str) -> PreambleDoc | None` | PARTIAL — works only for arXiv-style paper_ids, will fail for `textbook:*` |

**CRITICAL: `_compute_chunk_id` hardcodes `arxiv:` prefix.** Line 1050:
`return f"arxiv:{paper_id}:{digest}"`. For textbook chunks the id form is
`textbook:<slug>:<sha>`, not `arxiv:textbook:<slug>:<sha>`. The textbook chunker MUST
NOT call `_compute_chunk_id` directly. It must implement its own `_compute_textbook_chunk_id`
that returns `f"textbook:{slug}:{digest}"` using the same SHA logic.

**`_extract_section_chunks` emits `arxiv:` placeholder IDs internally.** The placeholder
is overwritten in the SHA pass in `_chunk_paper_impl` — same pattern must happen in the
textbook chunker.

### Three-copy byte-equality lock

From `ingest/identifiers.py` and MEMORY.md: `_PAPER_ID_FULL_PATTERN`, `ingest/chunker.py:_PAPER_ID_RE`,
and `tools/validate_eval_fixtures.py:_PAPER_ID_RE` are byte-equal. The textbook alternative
`r"|^textbook:[a-z][a-z0-9-]{2,30}\Z"` is already in all three. m7 adds NO new paper_id
alternative — it uses the existing `textbook:<slug>` form. **The three-copy lock is not
disturbed by m7.**

The `CHUNK_ID_PATTERN` in `identifiers.py` already accepts `textbook:<slug>:<16-hex>`:
`(textbook:[a-z][a-z0-9-]{2,30}):[0-9a-f]{16}`. The `CHUNK_ID_RE` uses `\Z` not `$`
(m1 fix). m7 must verify chunk-ids pass `is_valid_chunk_id()` from `identifiers.py`.

### Key schema constraint from `schema.py`

`CHUNKS_SCHEMA_V1` has `page_start: pa.int32(), nullable=True` and `page_end: pa.int32(),
nullable=True`. Textbook chunks with NULL page_start/end will write cleanly. `source_kind`
is `nullable=True`; the store guard (`_ALLOWED_SOURCE_KINDS`) enforces `"textbook"` is
a valid value. `parser_used` is `nullable=True` — `"mineru+latexml"` is the documented
enum value.

### No BP1 / tool-schema change

The brief confirms: "No BP1 / tool-schema change (the chunker is ingest-side, not
MCP-surface)." Verified: `ingest/textbook_chunker.py` is a new ingest module. No
changes to `server/tools.py::ALL_TOOLS`. `EXPECTED_TOOL_SCHEMA_SHA256` is NOT re-pinned.

## Prior decisions and lessons

- **m1–m3 decisions:** ChunkRecord m2 fields are in the dataclass (confirmed). The
  `textbook:<slug>` paper_id form and `textbook:<slug>:<16-hex>` chunk_id form are
  in `identifiers.py` and the three-copy lock.
- **m5/m6:** MinerU 3.2.0 pipeline is operational. The HTML5 output is at
  `var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/index.html`. Strategy A (wrap
  as LaTeX → latexmlc → HTML5) was chosen; page metadata is not preserved post-render.
- **chunker-fixtures.md establishes the fixture pattern:** synthetic HTML, `tempfile`,
  patch `_resolve_preamble_doc` to None, write `expected.json`. The m7 fixture runbook
  mirrors this exactly.
- **CHUNKER_VERSION = "v1.1"** after embedder-truncation-m1 bump. Do NOT modify
  `chunker_types.py` for the textbook module; use a module-local
  `TEXTBOOK_CHUNKER_VERSION` constant.
- **`assert` is BANNED** — use `if ... raise RuntimeError(...)`.
- **`KMP_DUPLICATE_LIB_OK=TRUE`** in `tests/conftest.py` is load-bearing. The textbook
  chunker imports from `ingest.chunker` (which lazily loads BGE-M3 tokenizer). Do not
  remove this guard.

**CONFLICT FLAGGED:** The brief says "m7 uses the existing per-paper preamble resolution
as a v0 fallback." **`_resolve_preamble_doc(paper_id)` calls `extract_preamble(paper_id)`
which reads `PREAMBLE_DIR/<paper_id>/preamble.json`**. For `paper_id = "textbook:my-book"`,
the preamble dir would be `var/arxmcp/corpus/preamble/textbook:my-book/preamble.json`.
This path cannot exist (the colon makes it an invalid filesystem path on macOS and the
arXiv corpus path is wrong for textbooks). The textbook chunker should use empty preamble
in v0 (treat `preamble_text = ""`), not call `_resolve_preamble_doc`. M8's per-chapter
preamble inheritance replaces this.

## External sources

LaTeXML HTML5 sectioning conventions for `\chapter`:

LaTeXML wraps `\chapter{Foo}` as:
```html
<section class="ltx_chapter" id="Chx">
  <h1 class="ltx_title ltx_title_chapter">Chapter 1. Foo</h1>
  ...
</section>
```

`\section{Bar}` produces:
```html
<section class="ltx_section" id="Sx.y">
  <h2 class="ltx_title ltx_title_section">1.1. Bar</h2>
  ...
</section>
```

This is confirmed by the existing `_SECTION_DIV_CLASSES` list in `ingest/chunker.py` (the
project already encodes these class names as an authoritative list). The existing code
treats `section` as the HTML5 tag for all LaTeXML sectioning levels. No external source
needed beyond what is already in the codebase.

## Recommendation

Implement `ingest/textbook_chunker.py` with these design choices:

1. **Do NOT call `_compute_chunk_id`** — it hardcodes `arxiv:`. Implement
   `_compute_textbook_chunk_id(slug, preamble_text, body_text)` returning
   `f"textbook:{slug}:{sha256(...)[:16]}"` with identical NFC + UTF-8 discipline.

2. **Use empty preamble in v0** (`preamble_text = ""`). Do NOT call
   `_resolve_preamble_doc` — it will fail on `paper_id = "textbook:*"`. Add a
   comment: `# TODO(m8): replace with per-chapter preamble inheritance`.

3. **Use `TEXTBOOK_CHUNKER_VERSION = "v0.1"` as a module-level constant** in
   `textbook_chunker.py`, NOT in `chunker_types.py`. Set each `ChunkRecord.chunker_version`
   to this value.

4. **Set `page_start = None, page_end = None`** always in m7. Flag with a comment pointing
   to `MinerUResult.content_list_path` as the future hook.

5. **`chunk` field**: extract the `ltx_chapter` ancestor title from `_extract_section_path`
   output — it's the outermost breadcrumb where the ancestor has class `ltx_chapter`.

6. **Write chunk JSONs to** `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/`
   (mirroring arXiv's `corpus/chunks/<paper_id>/`), with `flat_paper_id` computed the
   same way as the renderer.

7. **Golden fixture**: project-original synthetic HTML5 with `ltx_chapter`, `ltx_section`,
   and at least one `ltx_theorem_theorem` + `ltx_proof` pair. Store under
   `tests/fixtures/textbook_chunker/<fixture_id>/index.html`.

8. **Resilience**: mirror `PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError,
   FileNotFoundError)` from `chunker.py`. Log failure to
   `var/arxmcp/notebooks/<slug>/ops/chunk-failures.log` (analogous to `chunk.log`).

## Open questions

All 6 brief open questions are resolved above. Summary:

1. ChunkRecord fields — NO GAP, all m2 fields already in the dataclass.
2. HTML5 structure — `_SECTION_DIV_CLASSES` already has `ltx_chapter`; existing helpers
   are reusable with the `_compute_chunk_id` exception.
3. Read/write paths — confirmed; chunk JSONs under notebook-scoped `chunks/` dir.
4. page_start/page_end — NULL in m7; content_list metadata is not propagated through
   the LaTeXML render.
5. chunker_version — use separate `TEXTBOOK_CHUNKER_VERSION = "v0.1"` in the new module.
6. Fixture provenance — project-original synthetic HTML, no Stacks Project content.

**One implementation-blocking issue flagged:** `_resolve_preamble_doc` will fail for
textbook paper_ids. Use empty preamble in v0 (see conflict flag above).

**No open questions — implementation can proceed on the above recommendation.**

## External writes the implementation will require

None — this milestone is purely local. No git push, PR, ticket, or infra mutation.
`ingest/textbook_chunker.py` is a new ingest module with no MCP surface change.
