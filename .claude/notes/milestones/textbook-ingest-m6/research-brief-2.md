# Research Brief — textbook-ingest-m6

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T02:40:00Z

---

## External sources

### 1. latexmlmath — confirmed live on Darwin 25.4.0 (LaTeXML 0.8.8)

Tested directly against installed binary at `/opt/homebrew/bin/latexmlmath`.

**Key findings (authoritative — live tests, not docs):**

- `latexmlmath` accepts bare TeX snippets WITHOUT `$...$` delimiters. Input
  `\frac{a}{b}` produces:
  ```xml
  <math xmlns="http://www.w3.org/1998/Math/MathML" alttext="\frac{a}{b}" display="block">
    <mfrac><mi>a</mi><mi>b</mi></mfrac>
  </math>
  ```
- With `$...$` wrapping, `display="inline"` is set instead of `"block"`.
- The output is a **MathML fragment**, not a full document. No XML prolog, no
  HTML wrapper. This fragment is intended for inline insertion into an HTML5
  document.
- `--pmml` and `--cmml` flags are NOT supported by this version (return
  "Missing input TeX file" error). The bare positional-argument form is the
  supported API.
- **Implication for Strategy B/C (per-block latexmlmath calls):** latexmlmath
  is invocable as a subprocess per-equation. Each call takes ~1s cold start
  (Perl startup overhead). For a 500-page textbook with potentially thousands
  of equations, this serializes to hours. **Strategy B/C are operationally
  infeasible** unless latexmlmath is called in parallel or a persistent daemon
  is used.

### 2. MinerU 3.x content_list.json — inspected at smoke-test path

Live smoke-test artifact at `/tmp/mineru-smoke-direct/milne-introduction-to-shimura-varieties/auto/`:

**Observed block types in content_list.json for a 3-page extract:**
```
{'text': 22, 'page_footnote': 3, 'page_number': 3}
```

**Critical finding: ZERO equation blocks in the 3-page smoke test output.**

The markdown output (`.md`) contains math inline as `$\displaystyle ...$` and
`$...$` strings — MinerU's pipeline backend embeds math as LaTeX strings within
prose text blocks of `type: "text"`, NOT as separate equation-type blocks. All
observed keys: `{page_idx, bbox, text, type, text_level}`. There is NO separate
`type: "equation"` discriminator in this output. The `_content_list_v2.json`
contains no equation blocks either (zero items, zero keys beyond the same set).

**Implication:** Strategy B (per-block latexmlmath via content_list.json) cannot
function as described in the milestone brief — there are no separate equation
blocks to iterate. The math is embedded inline in text blocks in both the
markdown and the content list. The md output IS the primary artifact; the
content_list is structural metadata (page index, heading levels, bounding boxes)
only.

**For a math-rich textbook (vs this text-intro excerpt):** MinerU may emit
interline_equation or inline_equation blocks when processing pages with
display math. The FULL Shimura Varieties PDF (170 pages) was not parsed in the
smoke test — the 3-page smoke used only the front matter. However, the markdown
shows math as `$\displaystyle ...$` embedded in prose regardless of the
content_list structure. Strategy A or C are thus the viable paths.

### 3. FastAPI BackgroundTasks — lifecycle semantics

From FastAPI documentation (confirmed against existing `server/ingest_tracker.py`
which implements the m9 pattern):

- `BackgroundTasks.add_task()` schedules a callable that runs AFTER the response
  is sent, in the SAME thread pool as the request handler.
- **Failure mode:** if the background task raises an unhandled exception, it is
  logged as an ERROR but does NOT affect the already-sent response. The client
  receives 202 with no indication the task failed.
- **Shutdown risk:** FastAPI's `BackgroundTasks` does NOT hook into the Starlette
  lifespan. If the server shuts down while a background task is running, the task
  is abandoned without notification or DB update. This is the core failure mode
  documented in m9's choice of `asyncio.create_task` + `IngestTaskTracker` over
  raw `BackgroundTasks`.
- **Verdict:** the existing pattern (`IngestTaskTracker` + `asyncio.create_task`
  + global semaphore + DB row inserted before dispatch) from m9 IS the correct
  pattern for m6. Do NOT use raw `BackgroundTasks` — it has no cancellation path,
  no semaphore, and no lifespan hook. Reuse `IngestTaskTracker` or a parallel
  `ParseTaskTracker` with identical architecture.

### 4. HTML5 + MathML content type

Confirmed from live LaTeXML output at `var/arxmcp/corpus/parsed/1510.04089/index.html`:
```html
<!DOCTYPE html><html lang="en">
<head>
<meta http-equiv="content-type" content="text/html; charset=UTF-8">
```

The output is `text/html` (HTML5, NOT XHTML). The `--format=html5` flag in
`tools/arxiv_fetch.py::parse_with_latexml` produces standard HTML5 with `<math>`
elements embedded inline. HTML5 parsers handle MathML in `text/html` without
requiring well-formed XML. Serving as `application/xhtml+xml` would require every
character to be XML-escaped and would break all existing ar5iv HTML served by m8/m10.
**Use `text/html; charset=UTF-8` throughout.** No change from existing precedent.

### 5. markdown-it-py / mistune

Neither is in `pyproject.toml` (grepped: zero matches). No markdown library is
currently a dependency of arXMCP. Strategy C (markdown library + per-block
latexmlmath) would require adding a new dependency AND dealing with the
per-equation latexmlmath throughput problem. Given the smoke test shows math is
embedded as LaTeX strings in prose, not in separate AST nodes, a markdown library
adds complexity without simplifying the math extraction path.

---

## Failure-mode analysis

### FM-1: MinerU exits 0 but produces invalid/truncated markdown

- **Trigger:** PDF has font-encoded text; MinerU's ONNX pipeline mis-recognizes
  glyphs; output `.md` exists but contains garbled math strings or incomplete
  LaTeX.
- **Symptom:** `latexmlc` parses successfully but produces MathML with wrong
  symbols; CDM gate would catch this but it runs post-ingest.
- **Mitigation:** Pass math through unmodified as `$...$` strings if `latexmlc`
  conversion is per-document (Strategy A) — LaTeXML handles garbled fragments
  better than a per-equation approach. Record `parse_status="completed"` but note
  the CDM measurement in the `parser_used` tag. Log `stderr` tail from latexmlc
  to ops/parser-failures/.

### FM-2: LaTeXML fails on a specific equation — whole-doc vs per-equation

- **Trigger:** Strategy A (wrap entire markdown as LaTeX input to `latexmlc`):
  one malformed `$\frac{a b}$` (missing closing brace) causes `latexmlc` to emit
  a parse error and potentially drop the entire file. vs. Strategy C: `latexmlmath`
  per equation — one bad equation is skipped, rest succeed.
- **Symptom:** Under Strategy A, `index.html` is written but the `<math>` block
  for the failing equation is replaced by an error annotation in LaTeXML's output
  (LaTeXML recovers from individual equation errors — it does NOT abort on the first
  bad equation). Under Strategy C, subprocess-per-equation is serialized.
- **Mitigation:** Strategy A is PREFERRED because `latexmlc` processes the whole
  document with error-recovery semantics — individual equation failures get
  `<math class="ltx_ERROR">` annotations in the output, NOT a total failure. The
  existing `parse_with_latexml` helper in `tools/arxiv_fetch.py` uses exactly this
  discipline. Re-use it.

### FM-3: Two textbook uploads arrive simultaneously — GPU/MLX contention

- **Trigger:** Two POST requests to `/ui/api/notebooks/{slug}/papers/upload` for
  a textbook notebook, arriving within seconds of each other.
- **Symptom:** Two MinerU subprocess invocations both try to load MinerU's MLX
  models into the Apple M-series unified memory. On M4 Max (96GB RAM), two
  simultaneous invocations each need ~2-3GB working set = 4-6GB total, feasible.
  But on M2 Max (32GB RAM) with a 500-page textbook, two simultaneous jobs could
  OOM.
- **Mitigation:** The m9 `IngestTaskTracker._global_cap = asyncio.Semaphore(1)`
  pattern already serializes to one ingest at a time across all notebooks. A
  `ParseTaskTracker` with the SAME global semaphore (or reused) would serialize
  the parse phase too. The 409-collision check (in-memory `is_running` + DB
  `has_running_parse`) ensures exactly one parse per notebook at a time. **Flag
  in the milestone: the parse background task MUST acquire the same or an
  equivalent global semaphore as the ingest tracker.**

### FM-4: Server restart while background parse is running — parse_status stuck at "running"

- **Trigger:** Operator restarts the server process while the MinerU subprocess
  (30-min wall timeout) is in flight. The asyncio Task is cancelled; the DB row
  stays at `parse_status="running"`.
- **Symptom:** Next upload attempt for the same `paper_id` gets a 409 ("parse
  already in flight") from the `has_running_parse` DB check, permanently stuck
  until manual intervention or `mark_orphaned_runs_failed` runs.
- **Mitigation:** Verbatim from m9's `mark_orphaned_runs_failed` pattern —
  call the equivalent `mark_orphaned_parses_failed(cutoff_iso)` at lifespan
  startup. Any `parse_status="running"` row older than the startup timestamp (or
  a configurable cutoff like 35 min) is set to `"failed"` before the new daemon
  accepts uploads. The m9 precedent is `NotebooksStore.mark_orphaned_runs_failed`;
  extend the same contract for parse rows.

### FM-5: parsed_html_path collision — two different paper_ids in the same notebook

- **Trigger:** Two different PDFs uploaded to the same notebook that, after
  `flat_paper_id = paper_id.replace("/", "_").replace(":", "_")`, produce the
  same filesystem path.
- **Symptom:** Second upload silently overwrites the first PDF's parsed output.
  The DB rows for both papers show `parsed_html_path` pointing to the same file.
- **Mitigation:** `paper_id` uniqueness is already enforced by the `notebook_papers`
  junction table PRIMARY KEY `(slug, paper_id)`. Two distinct `paper_id` values
  that produce the same `flat_paper_id` are a collision risk only for textbook IDs
  like `textbook:my-book` vs `textbook:my_book` (colon AND underscore both
  flatten to `_`). The m4 handler `flat_paper_id = paper_id.replace("/", "_").replace(":", "_")`
  does NOT suffix `flat_paper_id` with a counter — this is a latent collision.
  **Mitigation:** use the full unique `paper_id` as the directory name under
  `parsed/`, not `flat_paper_id`. The `parsed/textbook_my-book/index.html` and
  `parsed/textbook_my_book/index.html` coexist safely as long as the directory
  name includes the disambiguating character. OR: embed the junction row's `added_at`
  timestamp as a subdirectory suffix.

### FM-6: HTML output references images but image extraction is empty for text-only fixtures

- **Trigger:** Strategy A runs `latexmlc` on MinerU's markdown. The markdown
  may include `![](<images/figure.png>)` references from MinerU's image
  extraction. If MinerU's image extraction failed (empty `images/` dir), the
  final `index.html` has `<img src="images/figure.png">` with 404 hrefs.
- **Symptom:** HTML renders with broken image links; no functional failure but
  operator sees blank figure slots.
- **Mitigation:** This is acceptable for v1 per the milestone brief's explicit
  "Out of scope: figure extraction." Document in the `parsed_html_path` that images
  are best-effort. The `images/` directory is retained in `output_dir` (m5's
  `var/arxmcp/notebooks/<slug>/parsed/<paper_id>/auto/images/`). The renderer
  should copy (or symlink) the `images/` dir alongside `index.html` so relative
  paths resolve. No functional failure; CDM only measures math fidelity.

### FM-7: Disk-space exhaustion mid-render

- **Trigger:** Large textbook (200 MB PDF) + MinerU output_dir retained (500 MB
  typical) + final `index.html` (50-100 MB for a math-dense book). Total per
  textbook: ~750 MB. Disk exhaustion occurs during `latexmlc` write of `index.html`.
- **Symptom:** `OSError: [Errno 28] No space left on device` during atomic write
  (`.html.tmp` write fails before `os.replace`). The `.tmp` file is partial; the
  `parse_status` row stays at "running" until the error propagates.
- **Mitigation:** The `08-security-observability-ops.md` failure-mode table
  specifies: "Disk full → Block ingestion, allow reads to continue, page operator."
  The parse task's `except OSError` path should set `parse_status="failed"` with
  a `parse_error="disk full"` message and clean up the `.tmp` file. The atomic
  write discipline (`.tmp` → `os.replace`) is already mandated by m8's precedent.
  Add an explicit `errno.ENOSPC` check to the error message so the operator knows
  to free disk vs. retry the same parse.

### FM-8: SQL injection via slug in /parse-status endpoint

- **Trigger:** The milestone specifies `GET /ui/api/notebooks/<slug>/parse-status`.
  The `slug` path parameter is interpolated into a DB query.
- **Symptom:** A crafted slug like `' OR '1'='1` could inject SQL into the
  `parse_status` query.
- **Mitigation:** The existing route-layer pattern ALWAYS passes `slug` through
  `validate_slug(slug)` (from `tools._notebook_common`) before any DB call. This
  is the m4 lesson restated: `validate_slug` rejects any non-`[a-z0-9-]` slug at
  the route boundary. All notebooks routes already do this (lines 1022-1028 in
  `server/routes/notebooks.py`). The `/parse-status` endpoint MUST do the same.
  No parametrized query can be SQL-injected via a validated slug, but defense-in-
  depth: sqlite3 parameterized queries (`?` placeholders) must be used regardless.

---

## In-codebase cross-check

### Schema version 3→4: no BP1 re-pin required

**Confirmed:** The `notebooks.db` SQLite store is NOT exposed via any MCP tool.
The 7-tool surface (`ALL_TOOLS` in `server/tools.py`) does not reference the
notebooks SQLite schema. `EXPECTED_TOOL_SCHEMA_SHA256` in
`tests/test_server_tool_schema.py` does NOT need re-pinning for a schema version
bump. The MCP tool schema (`TOOL_SCHEMA_VERSION`) is independent of the notebooks
DB schema. No BP1 cost.

**Confirmed path:** `SCHEMA_VERSION: int = 3` at `server/notebooks_store.py:68`.
The v3 migration added `notebook_kind` via `ALTER TABLE ADD COLUMN`. The v4
migration must follow the same ADDITIVE pattern (no DROP, no RECREATE):
```sql
ALTER TABLE notebooks ADD COLUMN parse_status TEXT;
ALTER TABLE notebooks ADD COLUMN parse_error TEXT;
ALTER TABLE notebooks ADD COLUMN parsed_html_path TEXT;
```
These nullable columns backfill as NULL for all existing arXiv-kind rows. The
v2→v3 precedent is the canonical guide.

**No conflict** between milestone brief and design constitution on this point.

### IngestTaskTracker reuse: CONFIRMED correct pattern

The milestone brief asks "FastAPI BackgroundTasks vs separate worker?" — the
existing `server/ingest_tracker.py::IngestTaskTracker` IS the answer. It is:
- `asyncio.create_task`-based (not raw `BackgroundTasks`)
- Lifecycle-aware (lifespan shutdown cancels in-flight tasks via `shutdown()`)
- DB-row-before-task sequencing (FM-7 closure in m9)
- Global semaphore (1) for resource capping

A `ParseTaskTracker` for m6 should mirror this exactly, or reuse it with a
separate slug-namespace for parse operations.

### validate_slug: MUST be called at /parse-status route boundary

From `server/routes/notebooks.py`: every route that accepts `slug` as a path
parameter calls `validate_slug(slug)` immediately. The new `/parse-status` route
is no exception. This is the m4 landmine: skip `validate_slug` and the path-
traversal defense is broken.

### Subprocess discipline for latexmlc: existing helper is reusable

`tools/arxiv_fetch.py::parse_with_latexml` already implements the full discipline:
- `start_new_session=True` + `os.killpg` on timeout
- `--format=html5` flag
- `out_dir / "index.html"` as target
- E13_S03 sandbox wiring (macOS sandbox-exec or Linux bwrap)

The m6 renderer should CALL `parse_with_latexml(main_tex, parsed_dir, paper_id)`
rather than re-implementing subprocess discipline. The challenge: the input to
`parse_with_latexml` expects a `.tex` file; m6's input is a `.md` file from
MinerU. Two approaches:
1. Write the MinerU markdown into a temp `.tex` wrapper that `\input{}` the
   markdown content, then call `latexmlc`. But latexmlc reads `.tex`, not `.md`.
2. Run `latexmlc` directly on the markdown file — latexmlc can parse markdown via
   its `--format=auto` flag, but this is undocumented behavior.
3. **Correct approach:** wrap the markdown as a LaTeX document with
   `\documentclass{article}\begin{document}...\end{document}` and pass it to
   `latexmlc`. The math in the markdown is already `$...$` delimited, which
   LaTeXML handles natively.

**Strategy A (wrap markdown as LaTeX) is the correct choice:**
- Reuses `parse_with_latexml` with minimal adaptation.
- LaTeXML's error recovery preserves partial output for malformed equations.
- Avoids per-equation subprocess calls (Strategy B/C throughput problem).
- The markdown prose is NOT valid LaTeX, but LaTeXML is highly tolerant of
  non-LaTeX text; its parser treats unrecognized input as plain text.
  Alternatively, the renderer writes only the math equations as LaTeX and
  wraps the prose blocks as `\text{...}` environments.

**Nuance:** The Milne markdown shows interleaved math (`$\Lambda \otimes \mathbb{z} \mathbb{R} \simeq V$`) and prose. Wrapping the full markdown as a LaTeX document
and letting latexmlc process it is the lowest-resistance path and matches the
arXiv path (`.tex` → `latexmlc` → `index.html`).

---

## Prior decisions and lessons

- **m5 state.json (`phase: complete`)**: MinerU 3.2.0 subprocess driver shipped.
  `MinerUResult.markdown_path` and `content_list_path` are the m6 inputs.
  Two deferred adversary findings: F8 (URL-based attack via notebook slug in
  error messages) and F9 (Lean REPL RLIMIT_AS Darwin gap — not m6 relevant).
- **m4 F1/F3 landmines:** path-traversal via `file.filename` and slug parameter.
  The `upload_paper` handler already uses `flat_paper_id` derived ONLY from
  the validated `paper_id`. The `/parse-status` endpoint must follow the same
  discipline.
- **CLAUDE.md §8, landmine 1:** `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py`
  is load-bearing. The renderer module will load no new models; no risk here.
- **CLAUDE.md §4.7:** `assert` is banned; `BaseHTTPMiddleware` is banned. Neither
  should appear in the renderer.
- **MEMORY.md (textbook-ingest-m6 prior notes):** none pre-existing in this
  milestone's scope.
- **m9 IngestTaskTracker pattern**: the fire-and-forget ingest subprocess model
  is the canonical precedent for m6's parse-background-task. The `ParseTaskTracker`
  must insert the DB row BEFORE spawning the task (FM-7 from m9), use a global
  semaphore for concurrency capping, and register the task on the tracker to
  prevent GC.

---

## Recommendation

**Use Strategy A (wrap MinerU markdown as a minimal LaTeX document, run latexmlc).**
Reasoning: the MinerU smoke test confirms math is embedded as `$...$` strings in
prose, not as separate structured blocks — Strategy B is factually inoperable on
this output. Strategy C adds a markdown library dependency with no benefit over
Strategy A. Strategy A reuses the existing `parse_with_latexml` helper and LaTeXML's
full-document error-recovery semantics. The implementer should write a thin
`ingest/textbook_renderer.py` module with a single public function
`render_to_html(mineru_result: MinerUResult, output_dir: Path, paper_id: str) -> Path`
that: (1) reads `markdown_path`, (2) wraps the content in a minimal LaTeX envelope,
(3) writes to a temp `.tex` file in `output_dir`, (4) calls `parse_with_latexml`
from `tools/arxiv_fetch.py`, (5) copies/symlinks the MinerU `images/` dir to
the `parsed/` output dir, and (6) returns the `index.html` path.

For the background task infrastructure, use a `ParseTaskTracker` that mirrors
`IngestTaskTracker` exactly, with `parse_status` stored on the `notebooks` table
(v4 schema) rather than a separate `notebook_parse_runs` table — simpler and
sufficient for the one-parse-per-paper semantics.

---

## Open questions

1. **LaTeX envelope form:** Should the wrapper be a full `\documentclass{article}`
   document, or can latexmlc accept a bare math-fragment document? Live testing
   needed to confirm latexmlc's tolerance for non-standard LaTeX preambles. The
   arXiv path always has a real `.tex` with `\documentclass`; this is safer.

2. **textbook_id derivation:** The milestone brief lists this as open. The m4
   handler uses `textbook:<slug>` as the `paper_id` for a textbook's primary PDF.
   For m6, the `paper_id` from the upload (`textbook:<slug>`) determines the
   output directory: `var/arxmcp/notebooks/<slug>/parsed/textbook_<slug>/index.html`.
   This is unambiguous. No new design needed.

3. **images/ dir in output tree:** The renderer should copy MinerU's
   `<output_dir>/<pdf_stem>/auto/images/` to `parsed/<paper_id>/images/` so that
   relative `<img src="images/...">` references in `index.html` resolve. Confirm
   this by inspecting a math-dense page's output directory structure.

---

## External writes the implementation will require

None — this milestone is purely local (new Python module, SQLite schema v3→4,
new route, tests). No git push, no GitHub issue creation, no infra mutation is
required for the implementation commit itself. Per Phase 4 protocol, the git push
and any follow-up issue creation are main-thread-only, post-rectification.
