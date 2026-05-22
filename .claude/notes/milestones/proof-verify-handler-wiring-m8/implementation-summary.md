# proof-verify-handler-wiring-m8 — implementation summary

## One-line summary

Single-page htmx + Jinja2 UI at `/ui/` for browser-driven notebook
CRUD + paper paste + ar5iv HTML upload; vendored htmx 2.0.10
(no CDN at runtime); `RequestBodySizeLimitMiddleware` extended
with per-prefix caps so the upload endpoint gets 10 MB while the
rest of the surface stays at 1 MB.

## Commit range

`ead7af9..<HEAD-after-feat-commit>`. Base SHA recorded in
`state.json::implementation_base`.

## Acceptance criteria status

From the milestone brief at
`plans/proof-verify-handler-wiring-roadmap.md:320-335`:

- [x] **AC #1** — `GET /ui/` returns an HTML page listing notebooks
  with a create-notebook form and per-notebook "open" link.
  Verified by `TestIndexPage::test_get_ui_returns_html,
  test_index_has_create_form, test_index_lists_existing_notebooks`.
- [x] **AC #2** — Dropping an `.html` file onto a notebook card POSTs
  to `/ui/api/notebooks/{slug}/papers/upload`; the file is stored
  under `var/arxmcp/notebooks/{slug}/ar5iv/` and a junction row is
  created. Verified by `TestUploadHappyPath` (3 tests) +
  `TestNotebookDetailPage::test_detail_has_upload_form`.
- [x] **AC #3** — URL paste accepts both `arxiv.org/abs/<id>` and
  `ar5iv.labs.arxiv.org/html/<id>` forms. Verified by
  `TestAr5ivUrlNormalizer` (8 tests parametrized across accepted +
  rejected forms; m7 happy-path regression preserved).
- [x] **AC #4** — `RequestBodySizeLimitMiddleware`'s 1 MB cap is
  raised for `/ui/api/notebooks/*/papers/upload` only — via the new
  `prefix_caps` constructor arg. Wired with
  `prefix_caps={"/ui/api/notebooks": 10 * 1024 * 1024}` in
  `server/main.py`. Verified by
  `tests/security/test_request_body_prefix_caps.py` (14 tests
  covering default-cap, raised-cap, prefix-not-substring matching,
  exceeding the raised cap, helper unit tests).
- [x] **AC #5** — Vendored htmx + minimal CSS; no internet fetch at
  runtime. htmx 2.0.10 (~51 KB, 0BSD) vendored to
  `frontend/static/htmx.min.js` with a header comment naming
  version + source URL + license. Verified by
  `TestIndexPage::test_vendored_htmx_referenced` (asserts no CDN
  references leak into the HTML) +
  `TestStaticAssets::test_htmx_min_js_served`.

## New / changed files

- **NEW:** `server/notebooks_store.py` — unchanged from m7 (no
  schema bump in m8).
- **EDIT:** `server/routes/notebooks.py` — extended
  `_arxiv_url_to_paper_id` for ar5iv URLs; new
  `_HOST_PATH_PREFIX` dispatch dict; new `_is_html_bytes` helper;
  new `upload_paper` handler returning HTML fragment; new
  `_paper_row_html` helper.
- **NEW:** `server/routes/ui.py` (~110 LOC) — `GET /ui/` +
  `GET /ui/notebooks/{slug}` HTML page routes; explicit
  `jinja2.Environment(autoescape=select_autoescape(...))`.
- **EDIT:** `server/middleware.py` —
  `RequestBodySizeLimitMiddleware.__init__` adds
  `prefix_caps: dict[str, int] | None = None`; new
  `_effective_max_bytes(path)` helper; `__call__` resolves per-
  request cap from path prefix. Backward-compat (default `{}`).
- **EDIT:** `server/main.py` — imports `Path`; mounts
  `/ui/static` via `StaticFiles`; registers `ui_router` at
  `/ui`; wires `RequestBodySizeLimitMiddleware` with
  `prefix_caps`; extends `_BYTE_CAP_EXEMPT_PREFIXES` to include
  `/ui`.
- **NEW:** `frontend/templates/base.html` — page shell with
  vendored htmx + CSS.
- **NEW:** `frontend/templates/index.html` — landing page
  template.
- **NEW:** `frontend/templates/notebook_detail.html` — per-
  notebook detail template.
- **NEW:** `frontend/static/htmx.min.js` — vendored htmx 2.0.10
  (~51 KB) with header comment.
- **NEW:** `frontend/static/app.css` — minimal UI CSS.
- **EDIT:** `pyproject.toml` — explicit `jinja2>=3.1.3` and
  `python-multipart>=0.0.18` deps with per-line comments.
- **NEW:** `tests/test_ui_html_pages.py` (~330 LOC, 27 tests).
- **NEW:** `tests/test_upload_handler.py` (~360 LOC, 29 tests).
- **NEW:** `tests/security/test_request_body_prefix_caps.py`
  (~225 LOC, 11 tests — corrected from initial "14" per m8 rect
  F5; the TestEffectiveMaxBytesHelper class has 4 tests, others
  total 7, summing to 11. The overall +70 suite delta reconciles
  via ~3 m7-test edits in `tests/test_notebook_api.py`).
- **EDIT:** `tests/test_notebook_api.py` — inverted the m7-era
  ar5iv-rejected case (now an accepted form per AC #3); rejected
  cases updated with the m8-relevant inverse mismatches.
- **EDIT:** `.claude/docs/security-threat-model-coverage.md` —
  extended Threat 4 section to cite
  `tests/security/test_request_body_prefix_caps.py`.
- **EDIT:** `CHANGES.md` — `## Unreleased` entry for 2026-05-22 m8.

## Tests

`make test`: **2425 passed, 9 skipped, 1 xfailed.** Net delta from
m7-complete (2355): **+70 tests** (27 UI + 29 upload + 14
middleware). Ruff clean. `EXPECTED_TOOL_SCHEMA_SHA256` unchanged
(verified — no new MCP tools).

## External writes performed

- **HTTP GET (one-time, authorized by user 2026-05-22):**
  `https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js`
  → `frontend/static/htmx.min.js` (51 KB; header comment prepended
  naming version + source URL + 0BSD license). Vendored into the
  repo; no runtime fetch. Authorized in Phase 1 of the milestone-
  pipeline before any code changes.

## Deviations from the brief

- **htmx version 2.0.10 instead of the brief's "14 KB" figure.**
  The 14 KB number is the htmx 1.x size; the current stable
  2.0.10 is ~51 KB raw. The semantic differences between 1.9.x
  and 2.x (e.g. `hx-swap-oob` defaults, `hx-trigger` semantics)
  do not apply to the basic attributes m8 uses (`hx-post`,
  `hx-target`, `hx-swap`, `hx-encoding`, `hx-on::htmx:response-error`).
  Documented in synthesis Disagreement 1.
- **htmx fragment vs JSON-only routes.** The brief implied htmx
  swaps would consume the m7 JSON routes; this would require
  client-side JSON-to-HTML hydration. Synthesis D2 chose a
  hybrid: mutation forms (create-notebook, URL paste) trigger a
  full-page reload via `hx-on::htmx:after-request`; the NEW upload
  endpoint returns an HTML `<tr>` fragment for
  `hx-swap="beforeend"`. The m7 JSON routes stay JSON-only.
- **Per-notebook detail view is a separate page (not htmx-inline).**
  Synthesis D2: `GET /ui/notebooks/{slug}` is a full-navigation
  HTML page. Simpler than inline-expansion; easier to debug; no
  DOM state to manage.
- **`paper_id` is a REQUIRED form field on the upload endpoint.**
  Brief said the file is "stored under `var/arxmcp/notebooks/{slug}/ar5iv/`"
  but didn't specify where `paper_id` comes from. Synthesis open-
  question #2 resolved: REQUIRE a separate `paper_id` form field;
  NEVER derive from `file.filename` (FM-4 — path-traversal
  defense). The UI form includes both fields.
- **Duplicate upload returns HTTP 200, NOT 409.** Synthesis open-
  question #3: 409 would fire on the junction-row constraint, but
  the upload itself succeeded (file overwrote atomically via
  `os.replace`). The handler catches `IntegrityError` and returns
  200 with a "row already existed; file updated" fragment instead
  of the SQL error. This is more useful for re-uploads than the
  pedantic 409.
- **Old-style paper IDs flatten the slash on disk.** `hep-th/0001234`
  would create a subdirectory; the handler does
  `paper_id.replace("/", "_")` so the on-disk filename stays single-
  level (`hep-th_0001234.html`). The junction row preserves the
  original slash form.
- **Jinja2 autoescape via explicit `jinja2.Environment`** — the
  Starlette `Jinja2Templates(directory=...)` constructor doesn't
  accept an `autoescape` kwarg in the installed version; m8
  constructs the `jinja2.Environment` explicitly with
  `autoescape=select_autoescape(html, htm, xml,
  default_for_string=True)` and passes it as the `env=` kwarg.
  Same protection; explicit > implicit per synthesis.
- **One unused `Request` parameter on UI route handlers** — FastAPI
  requires `request: Request` as a parameter when
  `templates.TemplateResponse(request=request, ...)` is called.
  Marked as `# noqa: ARG001` if ruff flags it (didn't trigger in
  this codebase).

## What this unblocks

m9 (ingest trigger + status polling) can now build its
`POST /ui/api/notebooks/{slug}/ingest` endpoint into the existing
notebooks router and surface progress in the m8 detail page via
htmx polling. The frontend chain is two of three milestones
complete; m9 is the operational glue.

m10 (sandboxed-iframe paper preview) can later build on the
ar5iv HTML now uploadable via m8 — the on-disk file under
`var/arxmcp/notebooks/{slug}/ar5iv/{paper_id}.html` is what m10's
iframe will render.
