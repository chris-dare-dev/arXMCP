# Research Brief — textbook-ingest-m7

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T04:15:00Z

---

## In-codebase context

### ChunkRecord field gap (Open question #1) — RESOLVED: NO GAP

`ingest/chunker_types.py::ChunkRecord` already carries ALL textbook-ingest-m2
columns. Verbatim from the dataclass (lines 174–184):

```python
source_kind: str = field(default="arxiv")
license: str = field(default="arxiv-license")
chapter: str | None = field(default=None)
page_start: int | None = field(default=None)
page_end: int | None = field(default=None)
textbook_slug: str | None = field(default=None)
parser_used: str | None = field(default=None)
```

m7 does NOT need to extend ChunkRecord. No chunker_version bump is required for
the dataclass. Whether `textbook_chunker.py` should bump `CHUNKER_VERSION` or keep
its own version constant is a separate question (see Open questions).

### LaTeXML HTML5 class/tag structure — VERIFIED IN CORPUS

The existing `ingest/chunker.py` already declares the full hierarchy at line 154:

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

Verified in `var/arxmcp/corpus/parsed/1306.2070/index.html` (a real LaTeXML-rendered
document with chapter structure):

```html
<section id="Ch1" class="ltx_chapter">
<h2 class="ltx_title ltx_title_chapter">
<div id="Ch1.S0.Thmlem1" class="ltx_theorem ltx_theorem_conj">
<h6 class="ltx_title ltx_runin ltx_title_theorem">
```

Key findings:
- `ltx_chapter` uses `<section>` tag (same as `ltx_section`) with `class="ltx_chapter"`.
- Chapter title is in `<h2 class="ltx_title ltx_title_chapter">`.
- Theorem/proof divs nest directly inside chapter sections without a mandatory intermediate `ltx_section`.
- The arXiv corpus typically starts at `ltx_section` (no `ltx_chapter`). The existing
  `_extract_section_path` already handles `ltx_chapter` because it checks
  `any(c in _SECTION_DIV_CLASSES for c in classes)` and `ltx_chapter` is in the list.

**Consequence for Q2:** `_extract_section_path` can already walk chapter ancestors. The
existing `_extract_section_chunks` at line 757 also uses `all_section_classes =
_SECTION_DIV_CLASSES` which includes `ltx_chapter`. However, `_extract_section_path`
assigns titles generically; the textbook chunker needs to separately identify WHICH
ancestor is a chapter div to populate the `chapter` field on ChunkRecord. The existing
helper does not return this — the textbook chunker must add a dedicated
`_extract_chapter_label(tag)` that walks ancestors looking for `ltx_chapter`.

**The Stacks Project.** The live stacks.math.columbia.edu site does NOT use LaTeXML.
It uses its own custom rendering with MathJax. The 4-char tags (e.g., `01AB`) are
Stacks-internal identifiers in their own system — not LaTeXML `id` attributes. The
Stacks Project's LaTeXML HTML output shape can only be obtained by running LaTeXML
against their source TeX. The fixture must therefore be **project-original synthetic**
mimicking the LaTeXML output shape — not scraped from the live site. License: GFDL
applies if real Stacks content is quoted; synthetic content avoids this entirely.

### _compute_chunk_id ALWAYS emits `arxiv:` prefix — CRITICAL GAP

**`ingest/chunker.py::_compute_chunk_id` (line 1050) hardcodes `arxiv:` prefix:**

```python
return f"arxiv:{paper_id}:{digest}"
```

For textbook chunks, the required chunk-id form is `textbook:<slug>:<sha>`. The
textbook chunker CANNOT call `_compute_chunk_id` directly — it will produce
`arxiv:textbook:<slug>:<sha>` which is INVALID per `CHUNK_ID_PATTERN` in
`ingest/identifiers.py`. The textbook chunker must either:
1. Pass the paper_id as `textbook:<slug>` and strip the `arxiv:` prefix from the
   returned string (fragile), OR
2. Implement a `_compute_textbook_chunk_id(slug, preamble_text, body_text)` that
   returns `f"textbook:{slug}:{digest}"`.

Option 2 is correct. The hash discipline (SHA-256 prefix, NFC normalization) is
reusable but the prefix construction must be done separately.

### Write path: notebook-scoped chunks directory (Open question #3)

`ingest/textbook_parser.py` produces `MinerUResult` with `content_list_path` pointing
to `<output_dir>/<pdf_stem>/auto/<pdf_stem>_content_list.json`. The HTML5 output
from m6 is at `var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/index.html`.

The brief proposes chunk JSONs at `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/`.
This mirrors the arXiv layout (`corpus/chunks/<paper_id>/`) but under the notebook
subtree. The isolation test at `tests/test_textbook_notebook_isolation.py` uses
`lancedb_path` isolation via `ingest.store.write_chunks` — it does NOT constrain the
chunk JSON write path. The chunk JSON write path is orthogonal to the LanceDB path.

`flat_paper_id = paper_id.replace("/", "_").replace(":", "_")` so
`textbook:shimura-varieties` → `textbook_shimura-varieties`.

### page_start / page_end source (Open question #4) — PAGE INFO IS LOST

The `content_list.json` artifact (confirmed from
`/tmp/mineru-smoke-direct/milne-introduction-to-shimura-varieties/auto/...`) carries
`page_idx` per block:

```json
{"type": "text", "text": "Introduction", "text_level": 2, "bbox": [...], "page_idx": 1}
```

**However**, the m6 pipeline runs LaTeXML on MinerU's markdown output, producing
`index.html`. This HTML5 file contains NO `page_idx` attributes — page numbering is a
MinerU concept that is not preserved through the LaTeXML rendering step. There is NO
mechanism in the current m6 pipeline to carry page metadata from `content_list.json`
into the LaTeXML HTML5. Therefore: **`page_start`/`page_end` must be NULL in m7's v0
ChunkRecords.** Flag the gap; the m8 implementer would need to either parse
`content_list.json` directly or correlate section headings between the two formats.

### spike-3 isolation contract

`tests/test_textbook_notebook_isolation.py` (6 tests) pins:
- Textbook chunks written to `var/arxmcp/notebooks/<slug>/lancedb/` NEVER appear
  in `var/arxmcp/index/lancedb/` (the arXiv corpus).
- `ingest.store.DEFAULT_LANCEDB_PATH` resolves under `var/arxmcp/index` — an
  accidental call without an explicit `lancedb_path` writes to the ARXIV corpus and
  triggers the `source_kind` enum guard there.

**Implication for m7:** `chunk_textbook` MUST accept `lancedb_path` as an explicit
argument and pass it to `write_chunks`. Omitting it is the exact spike-3 regression
the isolation test is designed to catch.

### No BP1 / tool-schema change — confirmed

The textbook chunker is pure ingest-side (not MCP server-side). Adding
`ingest/textbook_chunker.py` touches ZERO files in `server/tools.py` or handler
registration. `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning.

### Three-copy byte-equality lock

`ingest/identifiers.py::_PAPER_ID_FULL_PATTERN`, `ingest/chunker.py::_PAPER_ID_RE`,
and `tools/validate_eval_fixtures.py::_PAPER_ID_RE` are locked byte-equal by
`tests/test_identifiers.py::test_chunker_pattern_equals_canonical`. m7 adds no new
paper_id alternatives so this lock is unaffected.

---

## Prior decisions and lessons

From MEMORY.md (textbook-ingest-m1 entry):
> `CHUNK_ID_RE` uses `$` not `\Z` — was fixed in m1. Current `ingest/identifiers.py`
> (verified) uses `\Z` correctly. m7 must not regress this.

From MEMORY.md (three-copy sync pattern):
> Any change to arXiv alternatives must propagate to all three files. m7 adds NO new
> alternative; textbook form already in all three files. Lock intact.

From git log: `03bdcbe chore(notes): finalize textbook-ingest-m6 state -> complete` is
the most recent m6 commit. m6 shipped the notebook HTML5 pipeline (MinerU+LaTeXML).
m7 is the first consumer of that output.

From `ingest/chunker.py::_extract_section_chunks` (line 777):
```python
# Stop at theorem-like environments — they're handled above
if any(_THEOREM_CLASS_RE.match(c) for c in child_classes):
    break
```
This `break` means section prose extraction stops at the FIRST theorem. For textbook
chapters with dense theorem content, this is appropriate but means large sections with
theorems at the top will emit minimal prose section chunks. The textbook implementer
should be aware of this behavior.

`CHUNKER_VERSION` is "v1.1" (defined in `chunker_types.py`). If the textbook chunker
shares this constant, bumping it for textbook changes would force re-embedding ALL
arXiv chunks. Recommendation: define a separate `TEXTBOOK_CHUNKER_VERSION = "tv1.0"`
constant in `ingest/textbook_chunker.py` and use it for textbook ChunkRecords.

---

## External sources

### LaTeXML HTML5 class hierarchy (verified via CSS + live corpus files)

From `ltx-report.css` (LaTeXML source, `lib/LaTeXML/resources/CSS/ltx-report.css`):
Hierarchical classes: `.ltx_part`, `.ltx_chapter`, `.ltx_section`, `.ltx_subsection`,
`.ltx_subsubsection`, `.ltx_paragraph`, `.ltx_subparagraph`. All are `<section>`
elements in HTML5.

Title heading hierarchy: chapter → `<h2>`, section → `<h3>`, subsection → `<h4>`,
etc. (verified: `1306.2070/index.html` shows `<h2 class="ltx_title ltx_title_chapter">`).

**Granularity mapping for m7 v0:**
- `ltx_chapter` → granularity "book/chapter" → populate `chapter` field
- `ltx_section`, `ltx_subsection` → granularity "section"
- `ltx_subsubsection` → granularity "section" (same level for v0; definition/exercise
  level deferred per F2)

### Stacks Project

The live stacks.math.columbia.edu does NOT use LaTeXML — it uses a custom rendering
engine with MathJax. The 4-char tags (01AB, etc.) are Stacks-internal and not
transferable to a LaTeXML fixture. The Stacks Project source is at
`https://github.com/stacks/stacks-project` under GPL + GFDL. Running LaTeXML against
a Stacks chapter would produce a representative fixture, but that is NOT practical for
a committed test fixture (requires LaTeXML + the Stacks source checkout).

**Recommendation (Open question #6):** Use project-original synthetic HTML5 that
mimics the LaTeXML output shape confirmed above. This avoids all license questions
and makes the fixture stable across LaTeXML version changes.

### MinerU content_list.json page metadata

The smoke-test artifact at
`/tmp/mineru-smoke-direct/milne-introduction-to-shimura-varieties/auto/..._content_list.json`
confirms: each block carries `"page_idx": <int>` (zero-indexed). Page 0 has the title,
page 1 the introduction, etc. **This data is NOT propagated through the LaTeXML HTML5**
generated from MinerU's markdown output. The HTML5 file has no `data-page` or
equivalent attribute. Page metadata is lost in the current m6 pipeline.

---

## Failure modes

### FM-1: Textbook parsed as flat HTML (no chapter structure)
**Trigger:** Textbook source has no `\chapter` (lecture notes, monograph compiled with
article class), so LaTeXML emits only `ltx_section` elements.
**Symptom:** `chunk_textbook` finds no `ltx_chapter` ancestors; `chapter` field on all
ChunkRecords is `None`. Chunks still emit correctly as section chunks.
**Mitigation:** The chunker must NOT crash when `ltx_chapter` is absent. Use
`chapter = None` as a valid state. Emit a DEBUG log "no chapter structure detected"
and continue. Tests must cover the no-chapter input case.

### FM-2: Theorem spanning a chapter boundary (malformed nesting)
**Trigger:** A theorem's `<div class="ltx_theorem_*">` closes before the
`</section class="ltx_chapter">` closes, but its matching `<div class="ltx_proof">`
is a sibling in a DIFFERENT chapter's section.
**Symptom:** `_extract_chunks_from_container` scans siblings within one container; the
proof in a different chapter's container is never found. Result: theorem is emitted as
an unmatched `stmt` chunk (no proof paired), the proof is emitted as an orphan `proof`
chunk.
**Mitigation:** The existing `_is_structural_sibling` check (which breaks pairing at
a new `section` element) will correctly terminate the pairing scan at the chapter
boundary. This is correct behavior — cross-chapter pairing is semantically wrong. No
code change needed; a test should assert this behavior explicitly.

### FM-3: Token budget explosion — large textbook chapters
**Trigger:** A textbook chapter introduction runs 5000+ tokens (e.g., Shimura varieties
introduction with extensive motivational prose).
**Symptom:** `_truncate_to_token_budget(prose, STMT_MAX_TOKENS)` sets `truncated=True`
and emits a WARNING log. The chunk is emitted with truncated body — math fidelity is
degraded but no crash.
**Mitigation:** This is EXISTING behavior from `_extract_section_chunks`. The textbook
chunker should apply the same `_truncate_to_token_budget` discipline. The WARNING
log is load-bearing for operator awareness. Token budget constants (STMT_MAX_TOKENS =
1920, PROOF_MAX_TOKENS = 1856) are already generous post-embedder-truncation-m1.

### FM-4: chunk-id collision — same body in different chapters, empty preamble
**Trigger:** Two textbook sections contain identical prose (e.g., "Proof: Follows from
the definitions.") AND the per-chapter preamble is empty (m7 v0 always uses
empty preamble or the per-paper fallback).
**Symptom:** Both sections produce `textbook:<slug>:<same_sha>`. The deduplication
in `_chunk_paper_impl` (which drops legitimate duplicates) is in the ARXIV chunker,
not the textbook chunker. If the textbook chunker does not include equivalent
deduplication logic, the second chunk with the same ID will OVERWRITE the first chunk
JSON on disk (same filename `<hash_suffix>.json`), silently losing a chunk.
**Mitigation:** The textbook chunker MUST implement the same
`seen: dict[str, str]` deduplication loop as `_chunk_paper_impl` (lines 940–960 of
`chunker.py`). This is a required copy, not optional.

### FM-5: Notebook-scope write path regression (spike-3)
**Trigger:** `chunk_textbook` is called without an explicit `lancedb_path`, or an
incorrect default causes the LanceDB write to go to `var/arxmcp/index/lancedb/`.
**Symptom:** Textbook chunks appear in `search_papers` results for arXiv queries;
`source_kind` enum guard in `ingest.store` rejects them if the LanceDB schema enforces
arXiv-only `source_kind` at the shared-corpus path.
**Mitigation:** Make `lancedb_path` a required positional argument to `chunk_textbook`
(not optional with a default). The isolation regression test in
`tests/test_textbook_notebook_isolation.py` would catch this at CI time.

### FM-6: Golden-fixture non-determinism
**Trigger:** `to_dict()` returns dict keys in insertion order (Python 3.7+), but if any
code path mutates a ChunkRecord field after the initial construction, field ordering
could drift between runs. Also: if `chunker_version` for the textbook chunker is not a
module-level constant but derived at runtime (e.g., from a timestamp or package
version), golden JSON will differ.
**Mitigation:** `ChunkRecord.to_dict()` already sorts keys alphabetically (verified:
line 188 uses `sort_keys=True` in `json.dumps`). The `textbook_chunker.py` must define
`TEXTBOOK_CHUNKER_VERSION = "tv1.0"` as a module-level constant and never compute it
dynamically. The golden fixture regeneration runbook (analogous to
`.claude/docs/chunker-fixtures.md`) must document how to regenerate deterministically.

---

## In-codebase cross-check

**Does the existing chunker assume arXiv-paper structure in a way that would silently
mis-chunk a textbook?**

1. `_compute_chunk_id` hardcodes `arxiv:` prefix. **CONFIRMED CONFLICT.** Textbook
   chunker cannot call it directly (see above). Must implement
   `_compute_textbook_chunk_id`.

2. `_chunk_paper_impl` reads from `PARSED_DIR / paper_id / "index.html"` which
   resolves to `var/arxmcp/corpus/parsed/<paper_id>/index.html` — the ARXIV path.
   The textbook read path is `var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/index.html`.
   The textbook chunker must use a different path builder.

3. `_extract_section_chunks` starts section prose collection at the first child of
   the `ltx_section` (or `ltx_chapter`) and breaks at the first theorem. For textbook
   chapters that begin immediately with a theorem (no prose introduction), this
   produces an empty prose chunk (below `MIN_SECTION_TEXT_CHARS = 80`). That chunk
   is correctly dropped. No crash; correct behavior.

4. `_extract_section_path` handles `ltx_chapter` correctly — it checks
   `any(c in _SECTION_DIV_CLASSES for c in classes)` and `ltx_chapter` is in
   `_SECTION_DIV_CLASSES`. The section_path for a theorem inside a chapter will
   include the chapter title as the outermost element. The textbook chunker must
   ADDITIONALLY extract the chapter label from this path or from a dedicated helper
   to populate `ChunkRecord.chapter`.

**No other structural assumption in `chunker.py` breaks on textbook HTML.**
The theorem/proof pairing logic (`_extract_chunks_from_container`) is pure structural
and not arXiv-specific. The `_THEOREM_ENV_KINDS` dict is LaTeXML-agnostic. The
`_is_structural_sibling` check is correct for any LaTeXML HTML5 document.

---

## Recommendation

**Build `ingest/textbook_chunker.py` as a thin driver that reuses `chunker.py`
primitives, with three textbook-specific additions:**

1. A read-path builder using the notebook-scoped HTML path.
2. `_compute_textbook_chunk_id(slug, preamble_text, body_text)` that emits
   `textbook:<slug>:<digest>` (same hash discipline, different prefix).
3. `_extract_chapter_label(tag)` that walks ancestors for `ltx_chapter` and extracts
   the chapter title for `ChunkRecord.chapter`.

The textbook chunker should define `TEXTBOOK_CHUNKER_VERSION = "tv1.0"` as its own
constant, separate from `CHUNKER_VERSION` ("v1.1"), to prevent arXiv re-embedding on
textbook-chunker changes.

For the golden fixture (Open question #6): use **project-original synthetic HTML5**
mimicking LaTeXML output. The Stacks Project live site does not use LaTeXML and
running LaTeXML against its TeX source is impractical for a committed fixture. Synthetic
HTML avoids license questions and is fully stable across LaTeXML version changes.

page_start/page_end: leave NULL in m7 v0. Document the gap explicitly with a
`# m8: populate from content_list.json correlation` comment in the chunker.

---

## Open questions

1. **chunker_version strategy.** Recommend: define `TEXTBOOK_CHUNKER_VERSION = "tv1.0"`
   in `textbook_chunker.py`, separate from `CHUNKER_VERSION`. This prevents arXiv
   re-embed on textbook-only changes. The golden-fixture diff test must pin this value.

2. **Does `chunk_textbook` write chunk JSONs to disk, or only return in-memory records?**
   The brief says "operator can run it via CLI" — it should write JSON analogously to
   `chunk_paper`. Write path: `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/`.
   This is notebook-scoped and distinct from the shared corpus path. Recommend: always
   write JSONs (same side-effect contract as `chunk_paper`); also return the list.

3. **Preamble resolution in v0.** `_resolve_preamble_doc(paper_id)` calls
   `ingest.preamble.extract_preamble(paper_id)` which looks up
   `var/arxmcp/corpus/preamble/<paper_id>.json` — the ARXIV preamble store. For
   `paper_id="textbook:shimura-varieties"`, this will raise `FileNotFoundError`
   (caught by the preamble failure envelope) and return empty preamble. This is the
   correct m7 v0 behavior. The m8 per-chapter preamble inheritance hooks in here.
   No open question: empty preamble is the v0 contract; flag with a comment.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no GitHub issue, no infra mutation.
The milestone brief confirms: "No BP1 / tool-schema change (the chunker is ingest-side,
not MCP-surface)."
