# Research Brief — textbook-ingest-m6

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T03:00:00Z

---

## In-codebase context

### e2 outcome statement (verbatim, from `plans/textbook-ingest-roadmap.md` §textbook-ingest-e2)

> "Operator-uploaded PDF (≤200 MB per textbook notebook) flows through a
> sandboxed MinerU 2.5 subprocess [now 3.2.0 per B1], then the existing
> LaTeXML pass, then writes parsed HTML5+MathML to
> `var/arxmcp/notebooks/<slug>/parsed/<paper-or-textbook-id>/index.html`."

This is the binding functional contract for the milestone.

### What m5 shipped — the contract m6 consumes

`ingest/textbook_parser.py::MinerUResult` is a frozen dataclass with:
- `output_dir: Path`
- `markdown_path: Path` — MinerU's primary text artifact (LaTeX-flavored markdown)
- `content_list_path: Path` — block-level JSON with `text_type` and `text` fields
- `stdout: str`, `stderr: str` — tail-truncated to 8 KB
- `wall_clock_s: float`

`run_mineru_sandboxed(pdf_path, output_dir, *, timeout_s=None) -> MinerUResult` is
the public entry point. It does NOT run LaTeXML — that is entirely m6's job.

### parse_with_latexml — the existing LaTeXML pattern

`tools/arxiv_fetch.py::parse_with_latexml(main_tex, parsed_dir, paper_id)` expects
`main_tex: Path` pointing to a `.tex` file. It invokes `latexmlc` as:

```
["latexmlc", "<main_tex.name>", f"--dest={out_html}", "--format=html5"]
```

with `cwd=main_tex.parent`. **It does not accept markdown.** The sandbox wrapper
(`_build_sandbox_cmd`) applies the macOS `sandbox-exec` / Linux `bwrap` profile. The
output lands at `parsed_dir / paper_id / "index.html"`.

`latexmlc` is a **LaTeX compiler**. Feeding it a `.md` file that contains `$$...$$`
math blocks will not work without a wrapper that makes the content look like LaTeX.

### latexmlmath — per-math-block renderer

`latexmlmath` (ships as part of the LaTeXML package) takes a single LaTeX math
expression on stdin or as a CLI argument and emits MathML. It is MUCH lighter than
`latexmlc` (no document parse phase), but outputs MathML fragments only — no HTML
skeleton. Would be invoked once per math block in Strategy B.

### Strategy A/B/C analysis — load-bearing constraint

**Strategy A:** Wrap MinerU's markdown as a `.tex` document → `latexmlc` once.

This requires constructing a LaTeX wrapper document from markdown. MinerU's markdown
uses `$...$` and `$$...$$` for math (standard LaTeX inline/display math syntax). A
minimal wrapper would be:
```
\documentclass{article}
\begin{document}
<markdown_content>
\end{document}
```
But `latexmlc` does not understand markdown prose (`## Section`, `**bold**`, links,
etc.) — it is a LaTeX compiler. It would fail on every non-LaTeX markdown construct.
**Strategy A is not viable without a markdown→LaTeX pre-processor that converts prose
constructs to LaTeX equivalents — that is substantial scope.**

**Strategy B:** Walk `content_list.json`, extract math blocks, render each via
`latexmlmath`, reassemble HTML+MathML.

This is viable but introduces N subprocess calls (one per math block in a 500-page
textbook could be thousands of `latexmlmath` invocations). The HTML skeleton (prose,
structure) would need to come from a separate markdown-to-HTML pass (e.g. the stdlib
`markdown` library). Each `latexmlmath` call requires the subprocess discipline from
`_run_subprocess_with_pgkill`. Math fidelity is high (LaTeXML math engine). **Viable
but high-complexity, many subprocesses, and `content_list.json` block count can be large.**

**Strategy C:** Use a markdown library (e.g. `markdown-it-py`, already in project deps
via `transformers` v4 transitive) to convert the bulk of the markdown to HTML, then
post-process `$...$` / `$$...$$` blocks via `latexmlmath` per block.

This is the practical path: one fast markdown-to-HTML pass for prose, then a bounded
number of `latexmlmath` calls only for the math blocks. `markdown-it-py` is already
in `uv.lock` (via `transformers 4.57.6`). Math block count in a typical
math textbook chapter is O(100–500), not O(10000). **Strategy C is the recommended
path** — it reuses an already-present dep, makes the prose conversion trivial, and
confines subprocess calls to actual math content. It does NOT require `latexmlc`.

**CONFLICT FLAG:** The e2 outcome statement says "then the existing LaTeXML pass."
Strategy C does NOT pass the full document through `latexmlc`. It uses `latexmlmath`
(a LaTeXML utility) per math block. The e2 outcome was written before the
markdown-cannot-be-fed-to-latexmlc reality was confirmed. This is a spec drift: the
spirit (LaTeXML math rendering) is preserved, the letter (latexmlc single pass) is
not. **The implementer must acknowledge this in the implementation summary.**

### Notebook schema — current state (SCHEMA_VERSION = 3)

`server/notebooks_store.py::SCHEMA_VERSION = 3` (line 68). The comment at line 67
is verbatim load-bearing: "do NOT drop existing tables." The v2→v3 migration used
`ALTER TABLE notebooks ADD COLUMN notebook_kind TEXT NOT NULL DEFAULT 'arxiv'`.
The v3→v4 migration MUST follow the same ADDITIVE pattern: `ALTER TABLE ... ADD COLUMN`
for each of `parse_status`, `parse_error`, `parsed_html_path`.

Default values matter for backfill:
- `parse_status DEFAULT 'skipped'` — existing arXiv-kind rows land as skipped
- `parse_error DEFAULT ''`
- `parsed_html_path DEFAULT ''`

**CONFLICT FLAG:** The brief says `parse_status DEFAULT 'pending'` for the column
definition but then says arxiv-kind rows land as `'skipped'`. These are incompatible —
a single `DEFAULT 'pending'` at the column level will backfill ALL existing rows
(which are arXiv kind) as `'pending'` not `'skipped'`. The correct design is:
`DEFAULT 'skipped'` at the column level (so existing rows backfill correctly), then
the route handler explicitly sets `parse_status='pending'` when creating a new
textbook-kind notebook. The CREATE path already knows `notebook_kind` and can set
the right value.

### Upload route — existing m4 PDF write path

`server/routes/notebooks.py::upload_paper` (line 700) already handles textbook PDF
uploads:
- Runs `_run_pdf_preflight(content)` for textbook-kind notebooks
- Writes to `nb_dir / "pdfs" / f"{flat_paper_id}.pdf"` (atomic `.tmp` + `os.replace`)
- Inserts junction row via `store.add_paper(...)`

m6 must extend this handler (or the `create_notebook` handler for the textbook case)
to schedule the background parse task. The brief says the 202 response with
`parse_status_url` comes from the upload handler, not the notebook creation handler.

**CRITICAL ROUTING NOTE:** The `upload_paper` route is currently at:
`POST /ui/api/notebooks/{slug}/papers/upload`
The parse-status endpoint is:
`GET /ui/api/notebooks/{slug}/parse-status`
This is correct — under `notebooks_router` at `/ui/api` prefix, not under `/ui/api/notebooks/{slug}/papers`.

### Background task mechanism — existing precedent

The project already has a production background-task pattern: `server/ingest_tracker.py`
uses `asyncio.create_task` + `asyncio.create_subprocess_exec` + `asyncio.Semaphore(1)`.
The pattern is documented at `server/ingest_tracker.py:8-39`.

FastAPI `BackgroundTasks` is request-scoped and does NOT prevent the response from
being returned — the task runs after the response is sent. However, there is a
critical failure mode: if the ASGI server is shut down while a background task is
running, FastAPI `BackgroundTasks` does NOT guarantee the task completes. The
project's existing `IngestTaskTracker` solves this via:
1. `asyncio.create_task` (lives on the event loop, not request-scoped)
2. `app.state.ingest_tracker` — persists across requests
3. `done_callback` for DB row update
4. `shutdown()` method in the lifespan for graceful cancel

**Recommendation:** Use the `IngestTaskTracker` pattern (asyncio.create_task on
app.state), not FastAPI `BackgroundTasks`. Reason: MinerU takes 30 seconds to 30
minutes; request-scope BackgroundTasks are not designed for long-running tasks and
have unclear behavior under reload.

### MCP tool surface impact

m6 adds no new MCP tools and changes no tool schemas. The new `parse_status` columns
are on the `notebooks` SQLite table, not on `chunks` (LanceDB) or `ALL_TOOLS`.
**`EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning** unless the implementer
makes a tool schema change. The `TOOL_SCHEMA_VERSION` is currently 13 (from m3 rect).
Confirm: `server/tools.py` has no reference to notebook parse_status.

**BP1 discipline:** `server/prompts.py::SYSTEM_PROMPT` is unchanged; the BP1 hash
will not drift from adding a notebook status endpoint. No re-pin needed for BP1
unless the system prompt is edited.

### textbook_id derivation

From `ingest/identifiers.py`: the textbook paper_id form is `textbook:<slug>` where
`<slug>` matches `[a-z][a-z0-9-]{2,30}` (line 62). The upload handler already
constructs `flat_paper_id = paper_id.replace("/", "_").replace(":", "_")` for
on-disk paths (line 882 of `server/routes/notebooks.py`). So `textbook:my-book`
maps to the on-disk subdirectory `textbook_my-book/`. The output path for the renderer
should be `nb_dir / "parsed" / flat_paper_id / "index.html"` — consistent with the
existing `flat_paper_id` convention in the upload handler.

### subprocess discipline — exact pattern to mirror

`tools/cdm_eval.py::_run_subprocess_with_pgkill` (lines 333–382):

```python
proc = subprocess.Popen(
    list(cmd), cwd=str(cwd),
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, start_new_session=True, env=env,
)
try:
    stdout, stderr = proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired:
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=5)
    raise
```

This is the exact shape the `render_mineru_to_html` subprocess calls must use.

### `security-pdf-sandbox.md` lockstep doc

`ingest/textbook_parser.py` docstring says: "`.claude/docs/security-pdf-sandbox.md`
updated in lockstep." m6 adds a new subprocess (`latexmlmath`) — **the implementer
MUST update `.claude/docs/security-pdf-sandbox.md`** to document the renderer
subprocess. Pattern established by m4 F2 and m5 F2 findings: lockstep doc updates
are a recurring adversary target — do not miss this.

---

## Prior decisions and lessons

### git log context

Commits since m5 landed:
- `ea8eb8d` — chore(notes): finalize textbook-ingest-m5 state
- `4617c9a` — rect(ingest): close 7 of 9 textbook-ingest-m5 adversary findings
- `b0bf74c` — feat(ingest): sandboxed MinerU subprocess driver (textbook-ingest-m5)

m5 rect closed 7 of 9 findings. 2 remaining: F8 (tautology test) and F9 (RLIMIT_AS
WARN log test). These are pre-existing.

### Recurring anti-pattern from m4 and m5

The adversary has flagged "stale docstring" / "lockstep doc miss" in BOTH m4 F2 and
m5 F2. This is a named pattern in the project memory. **Any new subprocess added in
m6 MUST be documented in `.claude/docs/security-pdf-sandbox.md` in the same commit.**

### m5 concurrency decision (load-bearing)

`server/ingest_tracker.py` uses `asyncio.Semaphore(1)` — the project already decided
that global concurrency cap = 1 for subprocess-based background tasks. m6 should
follow the same pattern for MinerU + renderer to avoid GPU/MLX memory pressure on
Apple Silicon.

### m9 background task pattern (most recent precedent)

The ingest trigger added in m9 (`server/routes/notebooks.py::trigger_ingest`) uses
`IngestTaskTracker.start_ingest()` — not `FastAPI.BackgroundTasks`. The milestone
brief's mention of `FastAPI BackgroundTasks` is aspirational; the codebase's established
pattern is `asyncio.create_task` via the tracker.

### Schema migration pattern

From `server/notebooks_store.py` docstring (line 60-67, verbatim):
> "v1→v2 is the m9 ADDITIVE migration adding ``notebook_ingest_runs``
> WITHOUT dropping existing tables — notebook metadata MUST
> survive schema bumps (the original DROP-AND-RECREATE-on-bump
> pattern from Tier1Store is appropriate for a cache where loss
> is a miss, NOT correctness; for notebook metadata it would be
> data loss). When adding a new version: append a new
> ``if current_version < N:`` block in ``_open_sync`` using
> ``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE`` and bump
> SCHEMA_VERSION; do NOT drop existing tables."

### macOS segfault guard

`tests/conftest.py::KMP_DUPLICATE_LIB_OK=TRUE` is present and must not be touched.

### Banned patterns check

- No `assert` for invariants — use `if ... raise RuntimeError`
- No `BaseHTTPMiddleware`
- No `import anthropic`
- No `"claude-opus"` in server source
- New Markdown must go under `.claude/` not `server/`, `ingest/`, etc.
- `docs/install.md` updates are permitted (user-facing docs)

---

## External sources

### latexmlmath behavior (LaTeXML package)

`latexmlmath` accepts LaTeX math expressions and emits MathML. Invocation:
```
latexmlmath --pmml '$\frac{a}{b}$'
```
or via stdin. Returns a `<math>` element. Ships as part of the same `latexml` package
that provides `latexmlc`, so `requires_latexmlc` already covers this binary.

### FastAPI BackgroundTasks failure modes

FastAPI `BackgroundTasks` runs tasks synchronously (blocking) in the same thread pool
as the ASGI event loop after the response is sent. For long-running (30 min) CPU-bound
subprocess tasks: (a) it blocks the worker process from handling new requests while
the subprocess runs if the task is synchronous, (b) it cannot be gracefully cancelled
on server shutdown. The project's `asyncio.create_task` + `asyncio.create_subprocess_exec`
pattern is already the proven alternative for this use case.

### MinerU content_list.json structure

Based on the `_locate_outputs` code and MinerU 3.x documentation, `content_list.json`
contains a list of blocks with structure:
```json
{"type": "text", "text": "...", "text_type": "text"}
{"type": "text", "text": "$\\frac{a}{b}$", "text_type": "equation"}
{"type": "image", "img_path": "..."}
```
Math blocks have `text_type == "equation"` (display) or inline equations embedded
in prose blocks. Strategy C (markdown library + latexmlmath per math block) is
cleaner because `markdown-it-py` handles the block extraction from the `.md` file
directly, and inline/display math delimiters (`$...$`, `$$...$$`) are unambiguous.

---

## Recommendation

**Use Strategy C: `markdown-it-py` for prose HTML conversion + `latexmlmath` per
math block for MathML injection.**

Reasoning:
1. `latexmlc` does not accept markdown — feeding it the MinerU `.md` file requires
   constructing a full LaTeX wrapper document, which is ~500 LOC of markdown→LaTeX
   conversion that has no test coverage and would be a new source of bugs.
2. `latexmlmath` ships with the same `latexml` package, so `requires_latexmlc` covers
   both binaries with no new marker.
3. `markdown-it-py` is already in `uv.lock` (transitive from `transformers 4.57.6`).
   No new dependency to add.
4. Math blocks from MinerU's markdown use `$...$` / `$$...$$` delimiters — standard,
   parseable by a math-aware markdown extension.
5. Strategy B (per-block `latexmlmath` without markdown-it-py) requires manually
   reassembling the HTML skeleton from `content_list.json` blocks — more error-prone
   than letting a markdown library handle prose rendering.

**Background task:** Use the existing `IngestTaskTracker` pattern (`asyncio.create_task`
on `app.state.parse_tracker`), NOT FastAPI `BackgroundTasks`. Create a new
`ParseTaskTracker` (or extend `IngestTaskTracker`) with `asyncio.Semaphore(1)` for
global serialization. Wire it into the lifespan like the ingest tracker.

**textbook_id:** Use `flat_paper_id` derived from the `paper_id` form already in
the upload handler (`paper_id.replace("/", "_").replace(":", "_")`). For a textbook
notebook, `paper_id = "textbook:<slug>"` maps to `flat_paper_id = "textbook_<slug>"`.
This is path-safe, already validated by `is_valid_paper_id`, and consistent with
the existing on-disk layout.

**Server restart recovery:** Implement option (a) — a startup sweep that marks
`parse_status='running'` rows older than N minutes as `failed`. The exact same
pattern is already in `NotebooksStore.mark_orphaned_runs_failed()` (line 467).
Reuse that method or write an equivalent `mark_orphaned_parses_failed()`.

**Atomic write:** Yes. Write to `index.html.tmp` then `os.replace()` to `index.html`.
Same pattern as the existing upload handler at line 888–890.

**MinerU output_dir retention:** Retain the raw MinerU output tree after rendering.
It lives under `nb_dir / "parsed" / flat_paper_id /` (same subtree as `index.html`).
The disk cost is bounded by the file system and is manageable for a single-workstation
deployment. Operators can run `tools/notebook_purge.py` to clean up. No auto-cleanup.

**HTML5 structure:** Minimal wrapper. Include a `<head>` with `<title>` from the PDF
filename stem, a `<meta charset="utf-8">`, and `<meta name="generator" content="arXMCP/mineru+latexmlmath">`. No MathJax CDN script (local-first constraint;
LaTeXML output is native MathML, readable without JS by modern browsers). The
existing ar5iv HTML is the model.

**Concurrency:** Serialize. `asyncio.Semaphore(1)` — same as ingest tracker. On
Apple Silicon with MLX acceleration, a second concurrent MinerU invocation would
double MLX memory usage and risk OOM. One parse at a time is correct.

---

## Open questions

1. **A/B/C strategy:** **Strategy C** (see Recommendation above). No open question.

2. **Background task mechanism:** **`asyncio.create_task` via a `ParseTaskTracker`
   on `app.state`**, not FastAPI `BackgroundTasks`. No open question.

3. **Concurrency policy:** **Serialize** (`asyncio.Semaphore(1)`). No open question.

4. **Server restart recovery:** **Implement startup sweep** (option a). Re-use
   `mark_orphaned_runs_failed()` pattern. No open question.

5. **MinerU output_dir retention:** **Retain**. No auto-cleanup. No open question.

6. **HTML5 structure:** **Minimal wrapper** (no MathJax). See Recommendation. One
   open sub-question: does `latexmlmath` need `--pmml` or `--cmml` for the right
   output format? Default is Presentation MathML (correct for our use case). Use
   `--format=pmml` explicitly to be safe.

7. **textbook_id derivation:** **`flat_paper_id = paper_id.replace("/","_").replace(":",
   "_")`** — the form already used by the upload handler. No open question.

8. **Atomic write:** **Yes, `index.html.tmp` + `os.replace()`**. No open question.

**Residual open question:** Does `markdown-it-py` (the version in the current lock,
pulled transitively from `transformers 4.57.6`) support a `dollarmath` or equivalent
plugin for `$...$` detection? If not, the implementer must use a regex split on
`$...$` / `$$...$$` delimiters before passing text blocks to `latexmlmath`. This is
a 15-minute implementation question, not a blocker — either approach works. **Resolve
at implementation time.**

---

## External writes the implementation will require

None — this milestone is purely local. `git push` deferred to user authorization at
end of pipeline per CLAUDE.md §4.4.
