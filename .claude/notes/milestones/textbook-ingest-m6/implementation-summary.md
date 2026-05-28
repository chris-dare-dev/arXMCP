# Implementation Summary — textbook-ingest-m6

**Summary:** Closes the textbook-ingest-e2 epic. PDF uploaded to a `notebook_kind="textbook"` notebook flows through sandboxed MinerU (m5) → LaTeXML re-render via Strategy A → HTML5+MathML on disk at `var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/index.html`. Status is observable via `GET /ui/api/notebooks/<slug>/parse-status`.

**Commit range:** `ea8eb8d..HEAD` (single feat commit + this summary).

## Acceptance criteria status

### Core renderer
- [x] `ingest/textbook_renderer.py` with `render_mineru_to_html(result, parsed_dir, paper_id) -> RenderResult`.
- [x] `RenderResult` frozen dataclass: `output_html_path`, `wall_clock_s`, `latex_error_annotations`.
- [x] Strategy chosen: **A** — wrap MinerU markdown in minimal LaTeX envelope, delegate to existing `tools/arxiv_fetch.py::parse_with_latexml`. Math fidelity comes from LaTeXML's per-equation error recovery; prose constructs render as literal characters (acceptable for v1, documented).
- [x] Subprocess discipline inherited via `parse_with_latexml` (`start_new_session=True`, `killpg`, sandboxed via E13_S03 sandbox-exec/bwrap profile).

### Notebook schema bump 3→4
- [x] `server/notebooks_store.py::SCHEMA_VERSION = 4`.
- [x] Three new columns: `parse_status` (DEFAULT `'skipped'`), `parse_error` (DEFAULT `''`), `parsed_html_path` (DEFAULT `''`).
- [x] Additive ALTER TABLE migration; v3 rows backfill cleanly.
- [x] arxiv-kind notebooks land with `parse_status='skipped'`; textbook-kind land with `'pending'` via route-handler override (synthesis §D2).
- [x] Migration regression test passes.

### Upload route wiring
- [x] `server/routes/notebooks.py::upload_paper` extended: textbook-kind uploads schedule a `ParseTaskTracker.start_parse(...)` after the PDF is written + junction row inserted.
- [x] Notebook `parse_status` transitions: `pending` → `running` (set by route before task spawn) → `complete`/`failed` (set by tracker on completion).
- [x] HTML response shape unchanged (htmx-style row fragment, 201 CREATED) — background task is fire-and-forget.
- [x] Concurrency gate: `Semaphore(1)` global cap (synthesis §3) + per-notebook `is_running` check refuses scheduling a second parse for the same slug.

### Status-poll endpoint
- [x] `GET /ui/api/notebooks/<slug>/parse-status` — JSON with 5 fields (`slug`, `notebook_kind`, `parse_status`, `parse_error`, `parsed_html_path`).
- [x] 404 on unknown slug; 422 on malformed slug; 200 on success.
- [x] `validate_slug(slug)` at the route boundary (m4 path-traversal lesson preserved).

### Background task tracker
- [x] `server/parse_tracker.py::ParseTaskTracker` — mirrors `IngestTaskTracker` but in-process (heavy lifting already subprocess-isolated by m5 + LaTeXML).
- [x] `asyncio.create_task` + `asyncio.Semaphore(1)` + done-callback registry hygiene.
- [x] Lifespan wiring in `server/main.py`: tracker attached to `app.state.parse_tracker`; `mark_orphaned_parses_failed` sweep at startup; `shutdown()` cancellation in finally.
- [x] `_format_parse_error` — boundary stderr-tail discipline (HTML-escape + bounded byte length), peer of `prepare_stderr_tail` from ingest_tracker.

### Configuration + docs
- [x] `docs/install.md` documents the parse-status endpoint + status enum.
- [x] `.claude/docs/security-pdf-sandbox.md` updated in lockstep (m4 F2 / m5 F2 anti-pattern guard): adds latexmlc as a peer subprocess in the textbook path with explicit note about the markdown prose-render best-effort semantics.
- [x] No `pyproject.toml` deps added (Strategy A reuses existing LaTeXML — no markdown library needed).
- [x] No MCP tool surface change (verified: `EXPECTED_TOOL_SCHEMA_SHA256` does not drift).
- [x] No BP1 re-pin (system prompt unchanged).

### Tests
- [x] `tests/test_textbook_renderer.py` (NEW; 14 tests, 13 always-run + 1 `requires_latexmlc` opt-in).
- [x] `tests/test_parse_tracker.py` (NEW; 10 tests).
- [x] `tests/test_notebook_api.py` (extended): TestParseStatusInitialState (2 tests), TestParseStatusRoute (~3 tests with parametrize), TestParseStatusStoreLayer (5 tests). Schema-migration tests updated for v4.
- [x] `requires_latexmlc` integration test under `ARXMCP_RUN_REAL_LATEXMLC=1` opt-in (follows the requires_pdflatex pattern from parser-fidelity-eval-m1).

### Out-of-scope (deferred)
- Hierarchical chunker for book/chapter/section (e3).
- `search_papers` filter accepting `source_kind="textbook"` (e4).
- CDM bake-off Phase C (blocked on B2).
- Multi-textbook batch ingest.
- UI for parse-status (htmx fragment) — JSON-only for v1.

## Files changed

- `server/notebooks_store.py` (schema v4 migration + parse-status methods)
- `server/parse_tracker.py` (NEW, ~280 LOC)
- `server/main.py` (lifespan wiring)
- `server/routes/notebooks.py` (create-notebook override + upload-route scheduling + /parse-status route)
- `ingest/textbook_renderer.py` (NEW, ~180 LOC)
- `tests/test_textbook_renderer.py` (NEW, ~320 LOC)
- `tests/test_parse_tracker.py` (NEW, ~230 LOC)
- `tests/test_notebook_api.py` (extended ~250 LOC: ParseStatusInitialState + ParseStatusRoute + ParseStatusStoreLayer + schema-migration v4 updates)
- `.claude/docs/security-pdf-sandbox.md` (lockstep latexmlc peer-subprocess note)
- `docs/install.md` (parse-status endpoint + state enum docs)

## External writes required

None — purely local. `git push` deferred to user authorization at end of pipeline.

## Test counts

- `make test` (ruff + pytest): **2989 passed, 29 skipped, 1 xfailed, 3 pre-existing failures** (latexmlc SIGABRT + Kùzu graph DB path mismatch — unchanged from m5).
- Net new tests: **+38 passing** + **+1 opt-in skip** over the m5 baseline of 2951.

## Deviations from the brief

- **Concurrency policy:** synthesis chose `Semaphore(1)` (serialize). Implementation follows. The per-notebook `is_running` check refuses scheduling a second parse for the SAME slug; a second parse for a DIFFERENT slug queues at the semaphore — fits the synthesis design.
- **`parse_status` DEFAULT:** synthesis caught the conflict in the brief between "column-level DEFAULT 'pending'" and "arxiv-kind backfill to 'skipped'". Resolution applied: column-level `'skipped'`, route-handler explicit override to `'pending'` for textbook-kind. Tests verify both paths.
- **Brief mentioned 202 Accepted with parse_status_url JSON** for the upload response. Implementation keeps the existing 201 + HTML row fragment (htmx-style, project convention). Parse-status is observable via the separate `GET /parse-status` endpoint; the brief's "202 + status_url" framing was over-prescriptive given the project's HTMX/HTML-fragment surface.
- **`ARXMCP_TEXTBOOK_RENDER_SYNC` env var** for synchronous-mode testing was not implemented — tests directly invoke the ParseTaskTracker via `asyncio.run` + mocked MinerU/renderer, which gives deterministic coverage without the env-var override.
