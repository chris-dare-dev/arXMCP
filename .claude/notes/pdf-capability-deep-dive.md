# PDF Capability Deep Dive — arXMCP

**Date:** 2026-05-22. Prompted by the operator's `shimura-varieties`
notebook (2 deferred PDFs) and the stated trajectory toward ingesting
math/physics **textbooks** as PDFs. Snapshot of what arXMCP can do
with PDFs today and the honest options going forward.

---

## Executive summary

- arXMCP has **zero runtime PDF ingestion capability**. No `ingest/`
  module reads PDF bytes; no MCP handler accepts a PDF; the m8 upload
  route in `server/routes/notebooks.py` explicitly **rejects `.pdf`**
  at a magic-byte sniff.
- The only PDF artifact in the repo is the `shimura-varieties`
  notebook's `pdf-deferred/manifest.json` ("PDF ingest is not yet
  supported by arXMCP. The bulk_ingest pipeline today only accepts
  pre-parsed HTML... Nougat-based PDF fallback is deferred per E11_S01
  synthesis D2"). Files-on-disk; no machinery reads them.
- The design constitution treats PDF parsing as a load-bearing
  non-goal. `04-parsing-and-chunking.md` lists pypdf/pymupdf/pdfplumber
  as **"Banned from the parser chain"**. Math fidelity is rule #1.
- Nougat was the *designed* last-resort path (the only PDF library in
  the pipeline diagram). It was **deferred** in E11_S01, not killed.
- The operator's textbook trajectory breaks five v1 assumptions: chunk
  unit (chapter vs. theorem), size (hundreds of MB vs. ~MB), per-page
  math density (2–5×), identifier discipline (no arXiv ID), licensing
  (not OA).
- No current local-first PDF→math pipeline matches LaTeXML-on-source
  fidelity. Textbook ingest is **graceful degradation**, not
  fidelity-preserving — frame it that way or don't ship it.
- Three credible paths (S→XL). Recommended: **Path B first**
  (.tex-fetcher, S, 1 milestone) to clear the shimura backlog without
  committing; **Path A second** (Marker+LaTeXML, M, 2–3 milestones)
  if/when source-unavailable textbooks become a real demand. Park
  Path C (full textbook corpus) in `deferred-work-tracker.md`.

---

## 1. Current PDF surface (ledger)

### ✅ At runtime: none

The surface is entirely defensive:

| Touch point | Behavior |
|---|---|
| `server/routes/notebooks.py:483` (`_is_html_bytes`) | Magic-byte sniff. Comment: *"is plenty to disambiguate from binary formats (.exe, .pdf, .zip)"*. Rejects PDF uploads. |
| `server/routes/notebooks.py:127` (`_arxiv_url_to_paper_id`) | Rejects `arxiv.org/pdf/...` URLs (accepts only `/abs/` and `/html/`). |
| `var/arxmcp/notebooks/shimura-varieties/pdf-deferred/manifest.json` | Manual-curation manifest recording 2 PDFs as `deferred_status: "ok"`. **Nothing reads this.** |
| `ingest/bulk_ingest.py:41` (docstring) | *"Nougat PDF fallback is deferred (synthesis D2)."* Ladder is **ar5iv → LaTeXML → skip-and-log**. |

No `pypdf`, `pymupdf`, `pdfplumber`, `marker`, `nougat`, `unstructured`,
or `grobid` in `pyproject.toml`.

### ⚠️ Adjacent capabilities (extension points)

- **HTML upload (m8):** `upload_paper` accepts ar5iv HTML up to 10 MB
  with magic-byte gating. Closest pattern to extend.
- **HTML5+MathML chunker chain:** `ingest/chunker.py` +
  `ingest/preamble.py` consume parsed HTML at
  `var/arxmcp/corpus/parsed/<paper_id>/index.html`. **If a PDF can be
  converted to HTML5+MathML once, the entire downstream chain works
  unmodified.**
- **Per-notebook isolation (m6):** `var/arxmcp/notebooks/<slug>/lancedb/`
  is a clean blast-radius for a textbook-only dataset.

### ❌ Absent

- PDF library deps; PDF magic-byte recognizer; PDF→MathML path.
- Textbook-shaped identifier (the `paper_id` regex in
  `ingest/identifiers.py` is anchored on arXiv ID shapes).
- `license` / `source_kind` columns on the chunks schema.
- PDF-specific entries in `docs/ops/parser-failure-review.md`.

### 🚫 Explicit non-goals per constitution

- **"PDF figure extraction."** `09-feature-priorities.md:152`: *"PDF
  figure extraction. Tier 6 if at all."* Reiterated in
  `deferred-work-tracker.md` with an un-park trigger.
- **"OCR of pre-2007 scanned arXiv papers."** Listed under
  `deferred-work-tracker.md` **Explicit non-goals** (not Tier 6):
  *"OCR quality on math content is too poor for the math-fidelity
  contract to survive."*

---

## 2. Constitutional constraints (verbatim)

### PyPDF/PyMuPDF/pdfplumber banned from primary chain

From `.claude/notes/04-parsing-and-chunking.md:40-47`:

> - **Marker** (`https://github.com/VikParuchuri/marker`): faster than
>   Nougat, similar quality tradeoffs. Keep on hand as Nougat
>   alternative if Nougat installation breaks; otherwise skip.
> - **GROBID**: strong for metadata and reference extraction; equation
>   extraction is weak (emits MathML approximations).
> - **Pure pypdf / pymupdf / pdfplumber**: mangle math. **Banned from
>   the parser chain.** Useful only for low-stakes metadata fallback.

### LaTeXML is the required primary parser

`04-parsing-and-chunking.md:8-13` makes ar5iv (pre-rendered LaTeXML
HTML5+MathML) the primary path, LaTeXML the cache-miss path, Nougat
the last resort. README hard constraint #4 (line 157):

> **Math fidelity over retrieval recall.** LaTeXML + MathML; never
> PyPDF as a primary parser.

`milestone-adversary.md:119` makes this enforceable at review:

> - PyPDF used as primary parser (LaTeXML is the required primary;
>   PyPDF drops math entirely)

### Math fidelity over coverage (the motivating philosophy)

From `.claude/notes/01-mission-and-context.md:42-45`:

> Every existing arXiv MCP server ... treats papers as plain text via
> `pypdf` or similar. **This destroys LaTeX equations.** For papers in
> math.AG, math.NT, hep-th, math-ph, the equations *are the content*.
> Stripping them with PyPDF leaves an embedder seeing garbled glyphs
> and mangled subscripts.

And lines 131-132:

> 1. **Math fidelity over coverage.** Better to index 50,000 papers
>    with macros expanded and equations preserved than 500,000 with
>    PyPDF mangling.

### No-fork policy

`CLAUDE.md §4.7 line 197`:

> - **No-fork policy.** Nothing lifted from existing `arxiv-mcp`
>   repos. Use ideas, not code.

Applies to the PyPDF-based MCP-server ecosystem (blazickjp, daheepk,
etc.) — read tool surfaces, not code.

### Threat model

`.claude/notes/08-security-observability-ops.md` covers Threat 3
(**LaTeXML on hostile source**). No PDF carve-out exists because PDFs
aren't a parser input today. Any PDF ingest path must extend the model:

- Polyglot files (PDF+JAR, PDF+HTML).
- Embedded JavaScript (PDFs can carry JS — must reject at parse time).
- Decompression bombs (object trees that explode at unpack).
- Resource exhaustion (deeply nested objects, billion-laugh-style).
- Glyph forgery via embedded fonts mis-mapping symbols.

Current `REQUEST_BODY_MAX_BYTES = 1 MB` (`server/middleware.py:129`)
and the m8 10-MB upload carve-out are both two orders of magnitude
below 50–100 MB textbook PDFs. The 256-KB inline response cap
(`enforce_byte_cap` in `server/tools.py`) is unaffected — chunks are
small — but operator must know the upload-cap delta.

### Nougat was deferred, not killed

`.claude/notes/milestones/E11_S01/research-synthesis.md:17`:

> **Nougat is heavy and out of practical scope at v1.** 1.2B-param
> Vision Transformer, ~5 GB model download, GPU-dependent throughput.
> ... **Defer Nougat to a follow-up.** v1 fallback ladder: ar5iv →
> LaTeXML → skip + log.

---

## 3. Textbook-specific concerns

### Size
ar5iv HTML for a math.AG paper is ~200 KB; m8 cap is 10 MB. Textbooks
ship as 20–500 MB PDFs (Hartshorne, Griffiths-Harris, Bourbaki).
The 1-MB request cap, 10-MB upload cap, and 256-KB inline response
cap all need textbook-mode carve-outs. The inline-response cap is
fine — chunks are small — but uploads aren't.

### Structure
The v1 chunker is **theorem-aware**: it pairs theorem/lemma/proposition
with the following proof. Textbooks need **book / chapter /
theorem-or-definition-or-exercise**. Exercises are *unsolved* (no
proof to pair with) yet are first-class retrieval targets for the
autoformalizer. Definitions are far more central. Index and TOC are
navigation artifacts papers don't have.

### Math density
70–95% math content on a typical Bourbaki / Hatcher / Lang page —
2–5× a research paper. Flattening to glyphs throws away most of the
page. Scanned older works require math-OCR, which is the
constitution's named non-goal.

### Identifiers
The chunk-id contract (`04-parsing-and-chunking.md` rule 6) is
`arxiv:<paper_id>:<sha>`. Textbooks have no arXiv ID. Options:
- **ISBN-based** (`isbn:<isbn13>:<sha>`) — fails for lecture notes.
- **DOI-based** — fails for most lecture notes.
- **Slug-based** (`textbook:<slug>:<sha>`) — handles all three flavors
  (published, course-notes, hand-typeset). Recommended.

Requires regex update to `ingest/identifiers.py` and a `source_kind`
column on the chunks schema so handlers can distinguish.

### Licensing
arXiv content is mostly arXiv-licensed or CC-BY
(`03-ingestion-pipeline.md:25`). **Textbooks usually are not.** A
`license` column becomes load-bearing; non-OA snippets must respect
a fair-use truncation (~300 chars + `truncated_for_license: true`).
Restic retention may need separate rules for non-OA chunks.

---

## 4. OSS / library landscape (math-fidelity assessment, 2026)

**No local-first PDF→math pipeline matches LaTeXML-on-source.** This is
the honest framing. Relative ranking:

### Marker (vikparuchuri/marker) — recommended primary
- **License:** GPL-3 (changed from MIT in 2024). Subprocess isolation
  keeps arXMCP MIT — same pattern as `latexmlc`.
- **Local-first:** yes; CPU or GPU; Apple Silicon MPS supported.
- **Math fidelity:** strongest local-first option. Emits LaTeX inline
  (`$...$`, `$$...$$`) — feed back through LaTeXML for HTML5+MathML.
- **Throughput:** ~1–3 pages/sec on M2 Max; 10–20 pages/sec on RTX
  4090. ~5 min for a 500-page textbook on a workstation GPU.
- **Maintenance:** actively maintained (Datalab); monthly releases.
- **Weakness:** handwritten symbols, custom TikZ degrade; ~5–10% of
  equations wrong on dense pages.

### Nougat (Meta) — skip
MIT, but v0.1.17 (Feb 2024) is the last release. Effectively
unmaintained. Math fidelity is comparable to Marker on arxiv-style
papers, **significantly worse** on textbook layouts (multi-column,
marginalia) which are out-of-distribution. If Marker didn't exist this
would be the answer; it does, so skip.

### Mathpix — disqualified at runtime
Best math-OCR fidelity on the market, hand-engineered for math, used
by publishers. **Hosted** (violates local-first); per-page pricing.
Possible as a one-time offline batch exception for high-value
textbooks where Marker fidelity isn't enough.

### Unstructured.io — wrong tool
Generic PDF parser; math handling equivalent to PyPDF.

### PyMuPDF / pdfplumber / pypdf — banned for primary
Already named in the constitution. Legitimate role only as metadata
fallback (page count, embedded-text sniffing). PyMuPDF is the safe
pick for that role (AGPL, fine for internal use).

### LaTeXML against .tex source IF available
For **course-notes-as-PDF** (Milne, Caraiani, many lecture notes),
authors often publish .tex. Where source exists, **the existing
LaTeXML path is strictly better than any PDF parser.** A textbook
ingest pipeline should always check upstream .tex first.

### Recommendation
**Marker → LaTeX-markdown → LaTeXML → HTML5+MathML.** This keeps the
downstream chunker/embedder/LanceDB chain untouched. Tag chunks with
`parser_used: "marker+latexml"` alongside existing `ar5iv` /
`latexml-on-source` values so the math-fidelity tier is visible to
consumers — sketchers and autoformalizers can de-prioritize
Marker-sourced chunks for high-stakes claims.

---

## 5. Recommended architectural paths (opinionated)

### Path A — Notebook-scoped PDF ingest via Marker→LaTeXML (size M)

**Shape.** `notebook_kind: "textbook"` flag on m6 schema. Textbook
notebooks accept PDF uploads (prefix cap raised to 200 MB on the
notebook upload route only), run Marker → LaTeXML, then the existing
chunker. Writes to **per-notebook** LanceDB
(`var/arxmcp/notebooks/<slug>/lancedb/`), **never** the arXiv corpus.

**Why this scope.** Honors math fidelity (math survives through MathML),
no retrofit to arXiv corpus contract, uses existing per-notebook
isolation. Notebook-scoped = single-slug blast radius.

**Changes:**
- `pyproject.toml`: `marker-pdf` as optional extra (`[pdf]`).
- `server/routes/notebooks.py`: gate PDF acceptance on
  `kind == "textbook"`.
- New `ingest/pdf_marker.py`: drive Marker subprocess, re-invoke
  LaTeXML, write parsed HTML, reuse chunker.
- `ingest/identifiers.py`: accept `textbook:<slug>:<sha>` chunk-ids.
- New `source_kind` and `license` columns on chunks schema (chunker
  version bump per rule "the normalization layer must be deterministic
  and versioned").
- Threat-model extension: PDF-bomb detection (refuse if uncompressed
  pages > 5000 or any object > 50 MB); JS detection; polyglot
  detection.
- New `docs/ops/textbook-ingest-runbook.md`.

**Effort.** M (2–3 milestones). Marker integration is the meat;
threat-model extension is real work; downstream chunker is untouched.

**Caveats.** Confirm GPL-3-via-subprocess boundary with operator.

### Path B — Source-first textbook helper (size S)

**Shape.** Don't build a PDF parser. Build a **"find the .tex first"**
helper. For every PDF the operator points at, scrape the author's
homepage for `.tex` source. If found, existing LaTeXML path. If not
found, refuse with a clear error: *"Source not available; arXMCP does
not ingest publisher-only PDFs."*

**Why this scope.** Smallest credible path that respects math fidelity.
The 2 PDFs in `pdf-deferred/` are **both** course-notes-as-PDF
(Milne publishes .tex for every note set). **Path B fully solves the
shimura-varieties notebook without building a PDF parser.**

**Changes.**
- `tools/notebook_fetch.py`: `--prefer-source` mode following known
  per-author source URLs (Milne's `jmilne.org/math/xnotes/`, etc.).
- Registry: `tools/textbook_source_registry.json` (author → host).
- Targeted preamble-extractor hardening for textbook .sty vendoring.

**Effort.** S (1 milestone). Fetcher + registry.

**Caveats.** Solves at best ~1/3 of the textbook universe (course
notes from authors who publish source). Hartshorne, Bourbaki, Lang
not addressed.

### Path C — Full PDF-textbook corpus with parallel chunker (size XL)

**Shape.** Textbooks as a first-class second corpus. New
`ingest/textbook_chunker.py` (chapter/exercise/end-notes/TOC-aware),
new LanceDB dataset, new MCP tools (`search_textbooks`,
`get_textbook_chapter`, `get_exercise`). Mathpix online for one-time
batch on high-value textbooks where Marker fidelity isn't enough.

**Why this scope.** Takes the textbook trajectory seriously. Also
*most strongly threatens v1 contract* — parallel chunker, parallel
tool surface, parallel storage. 7-tool MCP surface grows to 10.
`deferred-work-tracker.md` names tool-block bloat (H6 from Phase 3
critique) as a known anti-pattern.

**Effort.** XL (4–6 milestones).

**Caveats.** Probably premature. Revisit only if Path A hits an
evidence-supported ceiling where notebook-scoped storage is the
bottleneck.

### Final recommendation

**Path B first (S, 1 milestone)** to clear the shimura-varieties
backlog without committing to load-bearing infra. **Path A second
(M, 2–3 milestones)** once the operator has a textbook for which
source is unavailable. **Park Path C** in `deferred-work-tracker.md`
with un-park trigger: *"three or more textbook-scoped notebooks in
active use AND a documented retrieval-quality gap that
notebook-scoped LanceDB cannot address."*

---

## 6. Open questions for the operator

1. **Is "textbooks" actually publisher-PDF textbooks, or
   lecture-notes-as-PDF?** This is the Path-A-vs-B pivot. The
   shimura-varieties manifest is the latter (both are course notes); a
   clear signal about Hartshorne / Griffiths-Harris / Bourbaki /
   Polchinski would push toward Path A.
2. **GPL boundary tolerance.** Marker is GPL-3. Subprocess keeps
   arXMCP MIT but operator should OK explicitly.
3. **License / quoting policy.** For non-OA textbooks, max snippet
   length on the MCP surface? Default proposal: 300 chars +
   `truncated_for_license: true` flag.
4. **Storage budget.** Path A could push from ~500 GB to ~750–1000
   GB with 50 textbooks. Acceptable?
5. **Co-mingling.** Should `search_papers` return textbook chunks, or
   should there be a separate `search_textbooks`? Recommendation:
   separate handler, preserves byte-stability of the existing handler's
   schema hash (BP1 prompt-cache discipline,
   `tests/test_server_tool_schema.py`).
6. **Threat-model owner.** Extending the threat model to cover PDF
   inputs is real work and probably wants a dedicated security-tier
   milestone (analogous to E13 series). Operator's tolerance for
   spending a milestone on this before any user-visible feature ships?

---

**End of dive.** When this work moves into a milestone, the un-park
trigger from `deferred-work-tracker.md` for "PDF figure extraction"
does NOT automatically apply — figures remain Tier-6-if-at-all even
after Path A or B ships. PDF *text and math* extraction is a separate
question, and this dive is the case for opening it.
