# Research Brief — ui-attractive-polish-m5

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T00:00:00Z

## In-codebase context

### Design constitution constraints

`06-mcp-server-design.md` "Browser UI surface":
> "**Hard constraint: no SPA, no Node/npm build chain.** htmx is vendored under `frontend/static/`; templates live under `frontend/templates/`. The MCP tool surface remains the primary agent interface; this console exists alongside it."
> "**Jinja2 autoescape** — the environment is constructed EXPLICITLY with `autoescape=select_autoescape(enabled_extensions=("html","htm","xml"), default_for_string=True)`. Zero `| safe` filters in any template (load-bearing — it is the stored-XSS guard for operator-authored fields like `display_name`)."
> "**CSRF posture** — `SecFetchSiteMiddleware(exempt_prefixes=("/ui",))` admits `Sec-Fetch-Site: same-origin` on `/ui/*` and rejects cross-site."

`CLAUDE.md §4.7` architectural bans:
> "`assert` is BANNED for invariants — Python `-O` strips them. Use `if … raise RuntimeError(…)` instead."
> "**Pure-ASGI middleware required.** `BaseHTTPMiddleware` is project-banned (E06_S01 F1 — it silently no-ops response interception for SSE paths)."
> "**No `anthropic` SDK at runtime.**"

### app.css current state (333 lines, cap at 335 per m4-rect F1)

Current app.css structure (load-bearing for m5 edits):
- Lines 1–33: `:root` tokens + `body { max-width: 980px }` — UPL-19 v1 target is `max-width: clamp(640px, 92vw, 1400px)`
- Lines 108–111: `table` + `th { background: #f0f0f0 }` — UPL-8 v1 needs dark redeclaration
- Lines 144–162: `.status-badge` + 4 modifier classes (--ok, --warn, --ops-warn, --down) — these have hardcoded light-mode hex; UPL-8 v1 remaps them inside the dark `@media` block
- Lines 236–268: `@media (prefers-color-scheme: dark)` block — UPL-8 v1 adds 4 pill remaps + `th` redeclaration here. The m3-rect already added input redeclaration + tertiary-text remaps inside this block.
- Lines 294–333: Two `@media (prefers-reduced-motion: no-preference)` blocks: first (294–310) is the spin keyframe, second (321–333) is the m4 badge-flash + UPL-13 View Transitions duration. The row-fade keyframe for UPL-12 v1 MUST consolidate here.

**Budget:** 333 lines current → cap raises to 365 per roadmap. Budget = 32 lines. Planned: ~4 LOC pill remaps + 1 LOC `th` + ~6 LOC row-fade keyframe + 1 LOC clamp = ~12 LOC CSS. This is well within budget.

**Cap test discipline (F1 from m4-rect):** BOTH `tests/test_ui_m3_dark_and_htmx_feedback.py:475` AND `tests/test_ui_m4_in_place_add_paper.py:626` currently assert `line_count <= 335`. Both MUST be updated in lockstep to `<= 365` when m5 ships.

### Current handler state — critical findings

**`create_notebook` (`POST /ui/api/notebooks`, lines 255–351):**
- Accepts `NotebookCreate(slug, display_name, notebook_kind)` — slug is supplied BY THE OPERATOR in the form field, NOT auto-derived via `slugify()`. The form at `index.html:20` has `<input type="text" name="slug">`. The milestone brief text at line 633 says "create generates the slug server-side from `slugify(notebook_name)` and must re-validate the result" — **THIS IS WRONG** relative to the actual implementation. The handler calls `validate_slug(body.slug)` on the operator-supplied slug directly. No `slugify()` call exists.
- Returns `dict[str, str]` with `{"slug", "display_name", "lancedb_path", "notebook_kind"}`. Currently NO `response_model=None` decorator (the return is a plain dict). The m5 HX-Request branch MUST add `response_model=None` to the decorator (mirrors the m4 `add_paper` precedent at line 504).
- Validation ordering is exemplary: `validate_slug` (line 273) + `notebook_dir` containment check (line 283) + `store.create_notebook` (line 304) + mkdir (line 334) ALL precede the response fork that m5 will add.

**`delete_notebook` (`DELETE /ui/api/notebooks/{slug}`, lines 354–386):**
- Returns `None` with HTTP 204 No Content (per `@router.delete(..., status_code=status.HTTP_204_NO_CONTENT)` at line 354 + `return None` at line 386).
- The brief's AC says "returns 200 with empty body when `HX-Request: true`; JSON branch remains 204 No Content." To achieve this, the handler must change its return type + add `response_model=None` + the content-negotiation fork. The 204→200 switch for HX-Request clients is necessary because **htmx ignores 204 responses** (it only processes 200/2xx with a body or swap targets).
- `validate_slug` is called at line 371 before any store access — correct ordering.

**`_paper_row_html` helper (lines 1609–1678):**
- Extended in m4 with `has_preview: bool = True`; uses `html.escape()` for every interpolated value. This is the blueprint for the new `_notebook_row_html` helper m5 adds.
- **The Actions cell says "added" (not "uploaded") post-m4 rect D2 resolution.** The `_notebook_row_html` helper for m5 should have NO Remove button in the immediate post-create row (mirrors the m4 pattern: "the next page-load restores the standard Remove affordance").

### index.html current state

- The create-notebook form at lines 12–30 uses `hx-on::htmx:after-request="if(event.detail.successful) location.reload()"` — UPL-12 v1's first target.
- The remove-notebook button at line 60 uses `hx-on::htmx:after-request="if(event.detail.successful) location.reload()"` — UPL-12 v1's second target.
- **The tbody currently has `id="notebook-list"` (line 48), NOT `id="notebooks-tbody"`**. The create-notebook fragment swap must target `#notebook-list`. The AC says "Add `aria-live="polite"` to the tbody" — this means renaming or at minimum adding `aria-live="polite"` to the existing `id="notebook-list"` tbody. The AC also says the form gets `hx-target="#notebooks-tbody"` — this requires renaming the tbody id from `notebook-list` to `notebooks-tbody` (naming consistency with `#papers-tbody` in notebook_detail.html). **This is a non-trivial template change that must be done consistently.**

### notebook_detail.html m4-F3 target

The add-paper form at `notebook_detail.html:99–113` already has `hx-target="#papers-tbody"` + `hx-swap="beforeend"` (from m4). It currently lacks `hx-on::htmx:after-request="if(event.detail.successful) this.reset()"`. The m4 critique F3 confirmed this is compatible with the existing negative-regression test (which only asserts `location.reload` is absent, not the absence of all after-request hooks).

### Spike-2 pre-flight checklist — applies TWICE in m5

The 13-item checklist from `ui-attractive-polish-spike-2.md` applies to BOTH `POST /ui/api/notebooks` (create) AND `DELETE /ui/api/notebooks/{slug}` (remove). Load-bearing items specific to m5:
- "The fragment renderer interpolates ONLY validated, escaped, server-controlled values — never raw request body or header values." For create, the `_notebook_row_html` fragment values are: `slug` (from `body.slug` post-`validate_slug`), `display_name` (from `body.display_name`, needs `html.escape()`), `notebook_kind` (from `body.notebook_kind`, server-validated via Pydantic pattern `^(arxiv|textbook)$`), `created_at` (from `_now_iso()`, server-generated).
- For remove, the response is an EMPTY 200 body (no fragment interpolation needed — htmx uses `hx-target="closest tr" hx-swap="outerHTML swap:200ms"` to remove the row entirely).

## Prior decisions and lessons

### m4-rect F1 (MEDIUM — cap drift): both cap tests must move together

From `critique-adversary.md` F1: "future cap raises MUST move BOTH this test AND the m3 cap test in lockstep." Current values: both at `<= 335`. m5 must raise BOTH to `<= 365`.

### m4 `response_model=None` pattern (lines 502–504)

FastAPI raises `Invalid args for response field` when a handler returns `HTMLResponse | dict`. Fix: `@router.post(..., response_model=None)`. Apply to both `create_notebook` and `delete_notebook` decorators in m5.

### m4 validation ordering precedent

From m4 critique "what was done well": "validation runs BEFORE the response fork... `validate_slug` → notebook exists → ... → THEN the HX-Request branch. The HTML branch cannot be reached on any invalid input." This ordering is MANDATORY for m5's two new endpoints.

### m3-rect WCAG discipline (load-bearing for UPL-8 v1 pill colors)

From m3 critique-merged.md: m3-rect F1 (HIGH) showed `#e8e8e8` on `#fff` = 1.22:1 (fail). m3-rect F2 (MEDIUM) showed `#444` on `#161b22` = 1.78:1, `#555` on `#0d1117` = 2.49:1. **The m5 adversary WILL check each of the 4 proposed pill color pairs** against WCAG SC 1.4.3 (4.5:1 text) and SC 1.4.11 (3:1 non-text border). The dark background context is `--bg #0d1117` / `--card-bg #161b22`.

### `_display_name_fragment` precedent (lines 401–421)

The rename handler uses `html.escape(display_name)` explicitly (line 417) for the outerHTML-swap fragment. The `_notebook_row_html` helper must do the same for every field including `display_name`.

### htmx 204 response handling

htmx does NOT trigger `hx-swap` for 204 No Content responses. The remove-notebook endpoint currently returns 204. For the HX-Request branch, the handler must return 200 with an EMPTY body so htmx performs `hx-target="closest tr" hx-swap="outerHTML"` and removes the row. The JSON branch stays 204.

### `hx-swap="outerHTML swap:200ms"` for row-fade

The 200ms `swap:` modifier gives htmx time to apply a CSS transition before the element is removed. The row-fade keyframe (`@keyframes row-fade { from { opacity: 1 } to { opacity: 0 } }`) must be gated by `@media (prefers-reduced-motion: no-preference)`. Per m4's consolidation pattern, it should join the EXISTING second `@media (prefers-reduced-motion: no-preference)` block at lines 321–333 (where badge-flash and View Transitions duration already live) — not a separate block.

## External sources

### WCAG SC 1.4.3 contrast verification for proposed UPL-8 v1 pill colors

Using the WCAG 2.1 contrast formula (relative luminance). Background for all pills: their own pill `bg` color.

Proposed pairs (text on pill background):
- `--ok`: `#3fb950` text on `#0d2818` bg. L(`#3fb950`) ≈ 0.186; L(`#0d2818`) ≈ 0.005. Ratio ≈ (0.186+0.05)/(0.005+0.05) ≈ 4.29:1. **BORDERLINE — may fail 4.5:1.** Primer Dark success.fg = `#3fb950` is 4.5:1 on Primer canvas `#0d1117`; the darker `#0d2818` pill bg may drop below 4.5. **Flag for verification before commit.** Alternative: `#56d364` (GitHub green on dark) gives ~5.3:1 on `#0d2818`.
- `--warn`: `#d29922` text on `#3d2a07` bg. L(`#d29922`) ≈ 0.185; L(`#3d2a07`) ≈ 0.004. Ratio ≈ 4.35:1. **May marginally fail 4.5:1.** Use `#e3b341` (Primer attention.fg) for ~5.1:1. Flag for verification.
- `--ops-warn`: `#8b949e` text on `#1c2230` bg. L(`#8b949e`) ≈ 0.252; L(`#1c2230`) ≈ 0.016. Ratio ≈ (0.252+0.05)/(0.016+0.05) ≈ 4.58:1. **PASSES** SC 1.4.3.
- `--down`: `#f85149` text on `#3d1216` bg. L(`#f85149`) ≈ 0.160; L(`#3d1216`) ≈ 0.004. Ratio ≈ (0.160+0.05)/(0.004+0.05) ≈ 3.89:1. **FAILS** 4.5:1. Use `#ff7b72` (Primer danger.fg light) for ~5.5:1 on `#3d1216`. Flag.

**Recommendation:** Before commit, verify all 4 pairs using the WebAIM Contrast Checker. The `--ok` and `--warn` pairs from the brief are Primer-derived but the darker pill backgrounds lower the ratios close to the threshold. `--down` with `#f85149` clearly fails. Safer: use `#56d364` / `#e3b341` / `#8b949e` / `#ff7b72` for `ok/warn/ops-warn/down` text — all are Primer Dark-canonical and tested.

### htmx 2.0.10 swap modifier syntax

The `swap:200ms` modifier in `hx-swap="outerHTML swap:200ms"` is standard htmx 2.x — it sets the swap delay, giving CSS time to run a transition before the DOM mutation. Confirmed in htmx docs. The `settle:100ms` modifier is for post-swap settlement; not needed here.

### CSS `clamp()` baseline

`clamp(min, preferred, max)` is Baseline Widely Available (2023+). `clamp(640px, 92vw, 1400px)` is a drop-in for `max-width: 980px`. No fallback needed for arXMCP's Chrome+Safari+Firefox target.

## Recommendation

**Implement m5 as a single `feat` commit touching 4 files + 1 new test file, in this order:**

1. `server/routes/notebooks.py`: Add `_notebook_row_html(slug, display_name, kind, created_at)` helper (mirrors `_paper_row_html`, per-value `html.escape()`, no Remove button in immediate row). Modify `create_notebook` decorator to add `response_model=None` + change `response_class=HTMLResponse` + add `request: Request` param + capture `created_at = _now_iso()` before store call + add HX-Request fork AFTER all validation gates. Modify `delete_notebook` decorator: add `response_model=None` + change return type to `HTMLResponse | None` + add `request: Request` + HX-Request fork returning `HTMLResponse(status_code=200, content="")`.

2. `frontend/templates/index.html`: Rename `id="notebook-list"` to `id="notebooks-tbody"` + add `aria-live="polite"`. Replace `hx-on::htmx:after-request="if(event.detail.successful) location.reload()"` on the create-notebook form with `hx-target="#notebooks-tbody" hx-swap="beforeend"`. Replace `hx-on::htmx:after-request="if(event.detail.successful) location.reload()"` on remove buttons with `hx-target="closest tr" hx-swap="outerHTML swap:200ms"`.

3. `frontend/templates/notebook_detail.html`: Add `hx-on::htmx:after-request="if(event.detail.successful) this.reset()"` to the add-paper form (m4-F3).

4. `frontend/static/app.css`: (a) Change `body { max-width: 980px }` to `max-width: clamp(640px, 92vw, 1400px)`. (b) Inside dark `@media` block, add 4 pill remaps + `th { background: #161b22 }`. (c) Inside EXISTING second `@media (prefers-reduced-motion: no-preference)` block (lines 321–333), add the `row-fade` keyframe + `.htmx-swapping tr` animation rule.

5. `tests/test_ui_m5_create_remove_in_place.py`: New file mirroring m4's 7-class structure. Update BOTH existing cap tests to `<= 365`.

**Row-fade keyframe placement:** Consolidate into the EXISTING second `@media (prefers-reduced-motion: no-preference)` block at lines 321–333. This keeps all motion under one gate, avoids a third `prefers-reduced-motion: no-preference` block, and matches the m4 adversary's praise for consolidation ("The CSS additions consolidate into a single `@media` block"). Do NOT open a new block.

**`_notebook_row_html` — do NOT add a `_remove_button_html` helper.** The remove button is template-only (in `index.html`, rendered by Jinja2 with autoescape). No server-side helper needed. The fragment for create returns a `<tr>` without a Remove button (mirrors m4's paper row "no Remove button on immediate post-success row" pattern).

## Open questions

1. **`delete_notebook` returns 204 today (confirmed).** The brief's AC says "returns 200 with empty body when `HX-Request: true`". This is correct — the implementation MUST change the 204 to a 200 empty response on the HX-Request branch. FastAPI's `@router.delete(..., status_code=HTTP_204_NO_CONTENT)` sets the default; the HX-Request branch must override with `HTMLResponse(status_code=200, content="")`. Non-HX-Request clients still get 204. Requires `response_model=None` on the decorator.

2. **`index.html` tbody is `id="notebook-list"` today, NOT `id="notebooks-tbody"`.** The AC uses `#notebooks-tbody`. The implementer MUST rename it. Any test that asserts `id="notebook-list"` will fail — search `tests/` for this string and update. Quick grep: `grep -rn "notebook-list" tests/`.

3. **The create-notebook form sends `slug` directly (operator-typed) — NOT derived from `notebook_name` via `slugify()`.** The brief text "create generates the slug server-side from `slugify(notebook_name)`" is a mismatch with the actual code. The real flow: operator types slug in the form, handler calls `validate_slug(body.slug)`. The `_notebook_row_html` must use `body.slug` (the validated slug), not any derived value. **No open question — this is a brief inaccuracy; implement per actual code.**

4. **Row-fade keyframe consolidation.** Recommendation: consolidate into the existing second `@media (prefers-reduced-motion: no-preference)` block (lines 321–333). No open question — the recommendation is clear.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| `git_push` | `origin/main` | Land feat + rect (if any) + chore(notes) finalize triple per CLAUDE.md §4.3. Per-event authorization required per CLAUDE.md §4.4. |
