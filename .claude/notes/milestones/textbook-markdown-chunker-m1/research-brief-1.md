# Research Brief — textbook-markdown-chunker-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-06-10T22:45:00Z

## In-codebase context

### `ingest/textbook_chunker.py` — load-bearing patterns to mirror

**TEXTBOOK_CHUNKER_VERSION and TEXTBOOK_PARSER_USED constants:**
```python
TEXTBOOK_CHUNKER_VERSION = "tv0.1"
TEXTBOOK_PARSER_USED = "mineru+latexml"
```
The new chunker must define a separate `TEXTBOOK_MD_CHUNKER_VERSION = "tmd0.1"` and
`TEXTBOOK_MD_PARSER_USED = "mineru+markdown"`. The "tv" vs "tmd" prefix distinguishes
HTML and markdown chunker lineages.

**`_flat_paper_id` function — verbatim:**
```python
def _flat_paper_id(paper_id: str) -> str:
    return paper_id.replace("/", "_").replace(":", "_")
```
Reuse this from `ingest.textbook_chunker` — do not re-implement.

**`_compute_textbook_chunk_id` — verbatim:**
```python
def _compute_textbook_chunk_id(slug: str, preamble_text: str, body_text: str) -> str:
    body_normalized = unicodedata.normalize("NFC", body_text)
    digest = hashlib.sha256(
        (preamble_text + body_normalized).encode("utf-8")
    ).hexdigest()[:16]
    return f"textbook:{slug}:{digest}"
```
Import and call this directly — do NOT duplicate. The m9 `textbook:` prefix invariant is
enforced at write time by `store.py::write_chunks` which asserts `chunk.chunk_id.startswith("textbook:")` when `source_kind="textbook"`.

**ChunkRecord field-stamping loop pattern (from `_chunk_textbook_impl`):**
```python
for chunk in all_chunks:
    chunk.source_kind = "textbook"
    chunk.textbook_slug = slug
    chunk.parser_used = TEXTBOOK_PARSER_USED
    chunk.chunker_version = TEXTBOOK_CHUNKER_VERSION
    chunk.chapter = _chapter_for_chunk(chunk, chapter_titles)
    chunk.page_start = None
    chunk.page_end = None
    chunk.body_tokens = tokenize_body(chunk.body_text)
```
New chunker stamps `TEXTBOOK_MD_PARSER_USED` and `TEXTBOOK_MD_CHUNKER_VERSION` instead.
`page_start/page_end` remain `None` for same reason as HTML path (preamble-decision.md).

**Dedup loop — LOAD-BEARING (m7 FM-4):**
```python
preamble_text = ""
seen: dict[str, str] = {}
deduped_chunks: list[ChunkRecord] = []
for chunk in all_chunks:
    chunk.chunk_id = _compute_textbook_chunk_id(slug, preamble_text, chunk.body_text)
    if chunk.chunk_id in seen:
        if seen[chunk.chunk_id] == chunk.body_text:
            logger.debug("dropping duplicate chunk_id %s", chunk.chunk_id)
            continue
        raise ValueError(f"SHA-256 prefix collision: ...")
    seen[chunk.chunk_id] = chunk.body_text
    deduped_chunks.append(chunk)
```
Replicate this verbatim in the markdown chunker.

### `ingest/store.py` — write-time invariant (CRITICAL FLAG)

**`_ALLOWED_PARSER_USED` = `frozenset({"ar5iv", "latexml", "mineru+latexml"})`**

**CONFLICT: The milestone brief specifies `parser_used="mineru+markdown"` but this
value is NOT in `_ALLOWED_PARSER_USED`. Writing chunks with `parser_used="mineru+markdown"`
raises `ValueError` at `write_chunks` time.** The implementer MUST add `"mineru+markdown"`
to `_ALLOWED_PARSER_USED` in `ingest/store.py`. This is a one-line change but without it
the new chunker produces unchallengeable chunks at the chunking step, then crashes at the
LanceDB write step.

**`body_tokens=None` raises at write time (D8):**
```python
if chunk.body_tokens is None:
    raise ValueError(f"chunk {chunk.chunk_id} has body_tokens=None; ...")
```
Every chunk must have `body_tokens` populated via `tokenize_body(chunk.body_text)` before
calling `write_chunks`.

**m9 prefix invariant:** `chunk.chunk_id.startswith("textbook:")` is enforced when
`source_kind="textbook"`. The markdown chunker satisfies this by calling
`_compute_textbook_chunk_id` which hardcodes the `textbook:` prefix.

### `ingest/chunker_types.py` — ChunkRecord fields

Required (no defaults) positional: `chunk_id`, `paper_id`, `kind`, `section_path`
(list[str]), `theorem_name` (str|None), `theorem_label` (str|None), `body_text`.
Defaulted: `body_tokens=None`, `preamble_ref=None`, `chunker_version=CHUNKER_VERSION`,
`truncated=False`, `source_kind="arxiv"`, `license="arxiv-license"`, `chapter=None`,
`page_start=None`, `page_end=None`, `textbook_slug=None`, `parser_used=None`.
No `__post_init__` validation exists — all field invariants are enforced by `store.py`.
`body_tokens` annotation is `str | None` (whitespace-joined token string, NOT `list[str]`).

### `ingest/tokenizer.py` — `tokenize_body` signature

```python
def tokenize_body(body_text: str) -> str:
```
Returns a whitespace-joined token **string** (not list, not count). Called with the
markdown `body_text` including `$...$` math — the tokenizer strips `$` delimiters
internally (`text = text.replace("$", " ")`) so LaTeX math in body_text is handled.
NFC-normalization is applied internally. This is the correct tool for token-budget
enforcement: call `len(tokenize_body(text).split())` to count tokens.

### `tools/notebook_textbook_ingest.py` — proof/stmt routing (single source)

**`_build_embed_record` routing — verbatim:**
```python
embed_inputs.append(_build_embed_input("", chunk.body_text))
routing.append(
    "embedding_proof" if chunk.kind == "proof" else "embedding_stmt"
)
```
This is the single source for routing. The markdown chunker must classify chunks as
`kind="proof"` (for Proof environments) or anything else (routes to `embedding_stmt`).
No change to `_build_embed_record` is needed — it already handles any chunk list.

The `--chunker {html,markdown}` flag adds a branch in `ingest_textbook_paper` that calls
either `chunk_textbook(slug, paper_id)` or `chunk_textbook_markdown(slug, paper_id)`.
The embed→write tail is unchanged.

### `ingest/textbook_renderer.py` — ATX heading matcher (reuse)

```python
_ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
```
Import and reuse this regex. The comment notes: "a space/tab after the `#` run is
REQUIRED so a stray `#hashtag` mid-prose is NOT a heading (FM-2). Trailing `#`
(closed-ATX style) is consumed and discarded (FM-4)." The new chunker does NOT need
`_escape_heading_title` — that function escapes headings for LaTeX conversion; the
markdown chunker uses heading text directly as breadcrumb strings.

### `ingest/embedder.py` — `_build_embed_input` (LaTeX-in-text is fine)

```python
def _build_embed_input(preamble_text: str, body_text: str) -> str:
    combined = (preamble_text + "\n\n" + body_text if preamble_text else body_text)
    return unicodedata.normalize("NFC", combined)
```
`body_text` is passed raw (with `$...$` math). BGE-M3 sees LaTeX tokens as subword
units — this is consistent with arXiv chunks which also carry unexpanded math as text.
The markdown chunker's `body_text` = markdown (with `$...$`) is fine for embedding.

### MinerU markdown path

The markdown files are at:
`notebooks/<slug>/parsed/<flat_paper_id>/**/auto/<stem>.md`

Confirmed from `var/arxmcp/notebooks/bridgeland-stability-pdfs/parsed/0912.0043/0912.0043/auto/0912.0043.md`. The glob pattern is `nb_dir / "parsed" / flat_id / "**" / "auto" / "*.md"`.

## Prior decisions and lessons

**m8 OQ-1 — preamble permanently empty:** `preamble_text = ""` and `preamble_ref = None`
for all PDF-sourced textbook chunks. See `.claude/docs/textbook-preamble-decision.md`.
"MinerU emits math already expanded at the PDF-render level, so there are no author
macros to inherit." This applies equally to the markdown chunker.

**textbook-md-heading-sectioning-m1 (commit 243019f):** Added `_convert_markdown_headings_to_latex` in `textbook_renderer.py` to convert ATX headings to `\section{}` commands before LaTeXML. This is the HTML path. The markdown chunker BYPASSES this conversion entirely — it reads ATX headings directly from the raw markdown. No conflict.

**textbook-render-robustness-m1 (commit 75dcd19):** Added configurable LaTeXML timeout and `_sanitize_math_balance`. No bearing on the markdown chunker (which does not invoke LaTeXML at all).

**TEXTBOOK_CHUNKER_VERSION separation principle (textbook_chunker.py docstring):**
"TEXTBOOK_CHUNKER_VERSION is SEPARATE from chunker_types.CHUNKER_VERSION so a textbook-only change never forces arXiv corpus re-embedding." Apply the same logic: `TEXTBOOK_MD_CHUNKER_VERSION = "tmd0.1"` is separate from both `CHUNKER_VERSION` ("v1.1") and `TEXTBOOK_CHUNKER_VERSION` ("tv0.1") so neither arXiv nor HTML-path textbook chunks are affected.

**No tool-schema touch:** The milestone explicitly says no MCP tool surface change. `EXPECTED_TOOL_SCHEMA_SHA256` remains unchanged.

**Windows dev path:** `tests` via `.venv/Scripts/python.exe -m pytest`. No POSIX-specific file ops in the new module (no `os.getpgid`, no symlinks). Path ops via `pathlib.Path`.

**KMP_DUPLICATE_LIB_OK=TRUE** in `tests/conftest.py` — load-bearing; do not remove.

## External sources

None relevant. This milestone is purely local Python. The MCP spec and prompt-caching docs are not touched (no tool-schema change, no server-surface change). The markdown format is standard ATX (CommonMark compatible); no external spec is needed beyond what is observable in the existing `_ATX_HEADING_RE` and the live MinerU output files.

## Recommendation

**Implement as a new module `ingest/textbook_markdown_chunker.py`** (not added to `textbook_chunker.py`) to keep the HTML and markdown paths fully isolated. Expose `chunk_textbook_markdown(slug, paper_id) -> list[ChunkRecord]` as the public API, mirroring `chunk_textbook`.

**Algorithm for paragraph grouping + oversized-block split:**

1. **Read heading hierarchy:** Scan lines with `_ATX_HEADING_RE`. Track a stack of
   `(depth, title)` pairs. When a heading is encountered at depth `d`, pop all stack
   entries with depth >= `d`, then push `(d, title)`. The current `section_path` is
   `[t for (_, t) in stack]`. The `chapter` field = first depth-1 or depth-2 heading
   in the stack (the nearest `#` or `##` ancestor).

2. **$$-atomic paragraph splitting:** Before splitting on blank lines, merge any
   paragraph block that contains an open `$$` (odd count of `$$` delimiters) with
   the next block until the `$$` pair is closed. A `$$...$$` that spans multiple
   blank-separated lines is NOT broken. Track parity of `$$` occurrences across
   block-accumulation.

3. **Token-budget grouping:** Group consecutive paragraph blocks into a chunk while
   `len(tokenize_body(accumulated).split()) <= 600`. When adding the next block would
   exceed 1500 tokens, flush the current accumulation first, then start the oversized
   block in a new chunk. An oversized single block (> 1500 tokens) is split at
   sentence boundaries (`(?<=[.!?])\s+` after a non-math sentence-end) or at `$$`
   block boundaries. Never truncate.

4. **Kind classification (per chunk, not per block):** After grouping blocks into a
   chunk, classify based on the first non-empty line: regex
   `^(Theorem|Lemma|Proposition|Corollary|Definition|Remark|Example)[\s\.\d]` (case-
   insensitive, optionally preceded by `**`) → `kind="stmt"`. `^(Proof)[\s\.\d]` or
   `^(\*\*Proof)` → `kind="proof"`. Else `kind="section"`. Use `"stmt"` not
   `"statement"` to match the existing ChunkRecord kind vocabulary from
   `chunker_types.py` ("stmt" and "proof" are the matched-pair kinds; "section" is
   prose).

5. **No-heading case:** If the markdown has no ATX headings at all, treat the entire
   content as `section_path=[]`, `chapter=None`, and apply token-budget grouping to
   all paragraph blocks.

## Failure-mode analysis (7 modes)

**(i) $$...$$  spanning blank-line boundaries.**
Trigger: MinerU emits a display-math block with a blank line between the opening `$$`
and the equation body. Naive blank-line split breaks the `$$` block, producing an
unterminated `$$` in one chunk and an orphaned `$$` in the next.
Mitigation: Track a `$$`-parity counter during block accumulation. When the count of
`$$` tokens in the accumulated buffer is odd, continue accumulating the next block
regardless of blank line — the `$$` pair is still open. Only flush when parity is even.
**Concrete implementation:** iterate candidate blocks; if `buffer.count("$$") % 2 == 1`,
append next block and continue.

**(ii) MinerU tables (`| a | b |`), images (`![](...)`), code fences (`` ``` ``), `\tag{N}`.**
Trigger: Real MinerU output contains these constructs (confirmed in 0912.0043.md).
Tables and code fences are NOT math; their `|`, backtick, and other characters will
pass through `tokenize_body` harmlessly (the tokenizer's regex only extracts known math
patterns). Images (`![]`) carry no semantic math content. `\tag{N}` is a LaTeX tag
inside `$$` — it will be kept verbatim in `body_text`. Recommendation: keep all as
literal text in `body_text`. Do NOT attempt to strip or interpret them — that risks
losing content. The BGE-M3 model has been trained on diverse text and handles markdown
table characters as noise tokens gracefully.

**(iii) Single paragraph/proof exceeding 1500 tokens with no sentence boundary.**
Trigger: A dense display-math proof consisting of a single long `$$...$$` block with
minimal prose around it. There is no `.`/`?`/`!` sentence break inside the block.
Mitigation: After exhausting sentence-boundary splits, fall back to `$$`-block boundary
splitting. If a single `$$...$$` atom is itself > 1500 tokens (extremely rare), emit it
as its own chunk with `truncated=False` (it is complete, just large). Never truncate.
The 1500-token max is a guideline, not a hard truncation threshold.

**(iv) chunk_id collisions on boilerplate bodies.**
Trigger: Two chunks in the same book with identical `body_text` (e.g. two "Proof. QED."
chunks, or repeated section header boilerplate like "This chapter..."). Since
`preamble_text=""` and `slug` is fixed, the SHA is purely over `body_text`.
Mitigation: The dedup loop (identical to the HTML path) silently drops the second chunk
when `body_text` matches. If the body is identical but semantically distinct (different
sections), the collision means one is dropped — acceptable for boilerplate. The
chunk_id is content-addressable by design; this is documented behavior from m7 FM-4.

**(v) Spurious `#` mid-content.**
Trigger: MinerU emits `# FOURIER-MUKAI TRANSFORMS` as a chapter heading at a point
where the section-grain counter is 0 — treating a formatted chapter title as a new
heading mid-document.
Mitigation: `_ATX_HEADING_RE` already requires a space after `#`, so `#hashtag` is
safe. Spurious ALL-CAPS headings are valid ATX headings by MinerU convention and will
correctly reset the breadcrumb stack at depth 1. The breadcrumb is best-effort — a
spurious heading produces a short single-block chunk for the heading text, then normal
flow resumes. No special mitigation needed.

**(vi) Chunk mixes a statement body + its proof.**
Trigger: A theorem statement ends with no blank line before "Proof." — the token budget
groups them into one block.
Mitigation: When kind classification detects the first line is `Theorem/Lemma/...` but
the chunk body also contains a `Proof.` paragraph, classify as `kind="stmt"` (the
statement is the primary content; the proof is appended). This is not ideal but is
consistent with the m7 HTML path's behavior for short proofs included in section prose.
Alternatively, scan for a `Proof.` boundary within a block group and split there. The
recommendation: apply a secondary split at `^Proof[\.\s]` within block accumulation
before flushing, producing separate stmt + proof chunks when the pattern is detected.

**(vii) Segment starting mid-section (no parent heading).**
Trigger: Each of the 12 Huybrechts segments is a standalone MinerU markdown file
starting at page N. A segment starting mid-chapter has no `#` heading at the top.
Mitigation: `section_path=[]`, `chapter=None` for all chunks in that segment until the
first heading is encountered. This is acceptable — it mirrors the HTML chunker's
behavior for flat/article-class documents ("`chapter=None` on all chunks" branch).
The brief explicitly acknowledges this: "per-segment vs whole-book: a segment starting
mid-section has no parent heading -> breadcrumb is null (acceptable?)." Answer: yes,
acceptable. Document in the function docstring.

## Open questions

**No open questions — implementation can proceed on the above recommendation.**

Note: `_ALLOWED_PARSER_USED` expansion in `store.py` is a required change that the brief
does not explicitly call out but is mandatory for the LanceDB write path to accept
`parser_used="mineru+markdown"`. This is a constraint, not an open question.

## External writes the implementation will require

None — this milestone is purely local.
