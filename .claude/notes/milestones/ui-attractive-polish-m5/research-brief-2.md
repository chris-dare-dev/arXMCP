# Research Brief — ui-attractive-polish-m5

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T17:45:00Z

## External sources

### htmx 2.0.10 swap mechanics (vendored `frontend/static/htmx.min.js`)

**`hx-swap="outerHTML swap:200ms"` timing and `.htmx-swapping` class:**
From the htmx docs (https://htmx.org/attributes/hx-swap/): the `swap:Nms` modifier delays the actual DOM replacement by N ms. During this delay htmx applies `htmx-swapping` to the target element. The CSS keyframe for row-fade MUST target `.htmx-swapping tr` (or the `<tr>` element directly when that IS the swap target) with `animation-fill-mode: forwards` so the element remains at opacity 0 during the settle phase. The `prefers-reduced-motion: no-preference` gate is the canonical pattern from m1/m2/m3/m4.

**`hx-target="closest tr"` — canonical CSS-selector extended syntax:**
The htmx docs confirm `closest <CSS selector>` is the idiomatic relative-ancestor selection in htmx 2.x. For a `<button>` INSIDE a `<td>` INSIDE a `<tr>`, `closest tr` correctly walks up the DOM. **HAZARD:** the remove button in `index.html` is inside a `<td>` inside a `<tr>` — `closest tr` works. In `notebook_detail.html` the remove-paper `<button>` is also inside a `<td>` inside a `<tr>` — same, correct. But the DELETE NOTEBOOK button in `notebook_detail.html` (line 83) is inside a `<div class="notebook-actions">` which is NOT inside any `<tr>` — that button must NOT get `hx-target="closest tr"` (no `<tr>` ancestor exists; htmx would either error or silently no-op).

**`htmx:beforeSwap` event:**
htmx 2.x fires `htmx:beforeSwap` but the m4 adversary confirmed "no obsolete `htmx:beforeSwap` wrapper anywhere in the diff." The m4 regression test (`test_no_obsolete_htmx_beforeswap_wrapper_added`) guards this. m5 must not reintroduce any `htmx:beforeSwap` handler.

**DELETE body serialization:**
The vendored `htmx.min.js` config includes:
```
methodsThatUseUrlParams:["get","delete"]
```
This means htmx encodes DELETE parameters in the URL (not the request body). The `base.html` JSON shim at line 28 confirms: `if (verb !== 'post' && verb !== 'put' && verb !== 'patch') return;` — it explicitly skips DELETE. For `DELETE /ui/api/notebooks/{slug}`, the slug is a path parameter, so no body serialization occurs at all. The shim is NOT a concern for delete flows.

**200 empty body + `hx-swap="outerHTML"` — CRITICAL FINDING:**
The vendored `htmx.min.js` `responseHandling` config contains:
```
{code:"204",swap:false}
{code:"[23]..",swap:true}
```
This means htmx 2.0.10 processes a **204** response with `swap:false` (no swap occurs). A **200** response with empty body is matched by `[23]..,swap:true` — htmx WILL attempt the swap. `hx-swap="outerHTML"` on a 200+empty-body replaces the target element with empty content, effectively removing it. **This is the intended mechanism for row removal.** The brief's requirement (return 200 empty body for HX-Request, 204 for non-htmx) is correct.

**htmx:beforeSwap event chain for the m4 regression test:**
The m4 test `test_no_obsolete_htmx_beforeswap_wrapper_added` is still enforced. m5 must not add `htmx:beforeSwap` anywhere.

### WCAG SC 1.4.3 (text contrast) and SC 1.4.11 (non-text contrast)

Contrast ratios computed using the WCAG 2.1 relative luminance formula:

| Badge | BG | Text | Text contrast | Border contrast vs BG | Border contrast vs canvas (#0d1117) |
|---|---|---|---|---|---|
| `--ok`       | `#0d2818` | `#3fb950` | **6.20:1** ✓ | 6.20:1 ✓ | 7.45:1 ✓ |
| `--warn`     | `#3d2a07` | `#d29922` | **5.43:1** ✓ | 5.43:1 ✓ | 7.50:1 ✓ |
| `--ops-warn` | `#1c2230` | `#8b949e` | **5.17:1** ✓ | 5.17:1 ✓ | 6.15:1 ✓ |
| `--down`     | `#3d1216` | `#f85149` | **4.83:1** ✓ | 4.83:1 ✓ | 5.65:1 ✓ |

All 4 pairs pass SC 1.4.3 (≥4.5:1). All pass SC 1.4.11 (≥3:1) for the border (border-color equals text color). The brief's proposed palette is confirmed compliant without modification.

**FLAG: ops-warn border color.** The existing light-mode `--ops-warn` rule uses a SEPARATE border color (`border-color: #94a3b8`; NOT the text color `#475569`). The dark-mode proposal implicitly reuses the text color for both. The implementer should decide: match the light-mode pattern (separate border) or simplify to single-color (consistent with the other three pills). Either passes SC 1.4.11.

### CSS `clamp()` baseline status

`clamp()` is **Widely Available** per MDN, with broad support since July 2020 across all modern browsers. No polyfill needed. `clamp(640px, 92vw, 1400px)` is a straightforward implementation.

### `prefers-reduced-motion: no-preference` keyframe gating

This pattern is canonical in this codebase (m1/m2/m3/m4 all follow it). The row-fade keyframe MUST be placed inside the existing `@media (prefers-reduced-motion: no-preference)` block (currently `app.css:321`). The m4 pattern consolidated UPL-22 + UPL-13 into a single such block — m5's row-fade keyframe should follow the same consolidation to minimize LOC.

---

## In-codebase context

### `06-mcp-server-design.md` — Browser UI surface (load-bearing)

> "**REST / htmx API — `server/routes/notebooks.py` (mounted at `/ui/api/`):**
> `GET /ui/api/notebooks` — list; `POST /ui/api/notebooks` — create;
> `DELETE /ui/api/notebooks/{slug}` — metadata-only delete...
> `GET/POST/DELETE /ui/api/notebooks/{slug}/papers[/{paper_id}]` — paper list / add-by-URL / remove"

New fragment endpoints (content-negotiation branch in `create_notebook` + `delete_notebook`) are explicitly within the documented REST surface. No design note prohibits adding content-negotiation branches to existing handlers.

### Design constraint: Jinja2 autoescape + zero `| safe` filters

From `06-mcp-server-design.md`: "Jinja2 autoescape — the environment is constructed EXPLICITLY with `autoescape=select_autoescape(...)`. Zero `| safe` filters in any template (load-bearing — it is the stored-XSS guard for operator-authored fields like `display_name`)."

The new `_notebook_row_html` helper MUST use `html.escape()` on every interpolated value (same as `_paper_row_html` in m4). The milestone brief confirms this.

### `create_notebook` current return

`server/routes/notebooks.py:251-351`: `create_notebook` returns `dict[str, str]` with `{slug, display_name, lancedb_path, notebook_kind}`. For the HX-Request branch, the `_notebook_row_html` fragment renders `<tr data-slug=...><td>slug</td><td>display_name</td><td>created_at</td><td><a>Open</a><button>Remove</button></td></tr>`. Note: `lancedb_path` should NOT appear in the fragment (host-path leak — see `06-mcp-server-design.md` note on `lancedb_path` info-leak for MCP resources).

### `delete_notebook` — 204 tests ARE breaking if not handled carefully

**CRITICAL CONFLICT:** `tests/test_notebook_api.py:139` asserts `r.status_code == 204`. `tests/test_notebook_rename_delete.py:256` also asserts 204. The m5 change introduces content-negotiation: HX-Request → 200+empty, non-htmx → 204. These existing tests hit the endpoint WITHOUT the `HX-Request: true` header → they remain on the 204 branch → **no change required to existing tests**. The 200 path is NEW; the 204 path is preserved. The implementer MUST NOT change `status_code=HTTP_204_NO_CONTENT` on the existing path.

### `#notebook-list` vs `#notebooks-tbody` — CONFLICT in milestone brief

The milestone brief AC says: `hx-target="#notebooks-tbody"` on the create-notebook form. But `index.html:48` shows `<tbody id="notebook-list">` (NOT `#notebooks-tbody`). **The tbody ID must be updated to `id="notebooks-tbody"` in `index.html`, OR the AC target corrected to `#notebook-list`.** The brief's WCAG pattern (`aria-live="polite"` on the tbody) still applies regardless of which ID wins. This is an inconsistency to flag.

### Cap test chain — BOTH tests must move in lockstep

`tests/test_ui_m4_in_place_add_paper.py:626` asserts `<= 335`. `tests/test_ui_m3_dark_and_htmx_feedback.py` has a corresponding `<= 335` cap test. The m4-rect F1 docstring at line 621-624 states explicitly: "If a future milestone raises the cap again, BOTH this test AND tests/test_ui_m3_dark_and_htmx_feedback.py::TestCrossMilestoneSafety::test_app_css_under_soft_cap must move in lockstep — the two caps MUST agree." m5 must update BOTH to `<= 365`.

### m4-F3 exact deferred-finding text

From `critique-adversary.md` (m4), F3 rectification status:
> "**F3 (LOW) — DEFERRED.** Form `this.reset()` after successful in-place swap is a minor UX polish; deferred to a future m5 follow-on (out of m4 scope). The 409 conflict the operator may hit on double-submit is non-destructive (no data loss)."

The proposed attribute (from F3 body): `hx-on::htmx:after-request="if(event.detail.successful) this.reset()"`. The m4 negative-regression test `test_add_paper_form_no_longer_uses_location_reload` only asserts `location.reload` absence — adding `this.reset()` is compatible.

### `notebook_detail.html:83-89` — DELETE NOTEBOOK button scope

The delete-notebook button in `notebook_detail.html` at line 83 is inside `<div class="notebook-actions">`, NOT inside a `<tr>`. This button triggers `DELETE /ui/api/notebooks/{slug}`. The m5 brief is only converting the remove-paper button (which IS inside `<tr>`) to `hx-target="closest tr" hx-swap="outerHTML swap:200ms"`. The delete-notebook button correctly stays with `hx-on::htmx:after-request="if(event.detail.successful) window.location.href='/ui/'"` — this is NOT in scope for the row-removal pattern.

---

## Prior decisions and lessons

From `MEMORY.md` (auto-injected):

- **`outerHTML` swap loses open state** (m3): `hx-swap="outerHTML"` replaces the element; `aria-live` must appear in BOTH the static template AND any server-rendered fragment. For the create-notebook `beforeend` swap, the `#notebooks-tbody` element is NOT replaced — only the new row is added — so `aria-live="polite"` in the static template is sufficient (mirrors m1/m4 pattern).

- **`htmx-request` class on form not button** (m3): CSS for the in-flight spinner uses `form.htmx-request button[type="submit"]` selector chain. The existing m3 styling already covers new forms; m5 creates NO new forms (the create-notebook form is pre-existing). No new CSS needed for in-flight feedback on the create-notebook form.

- **`hx-disabled-elt` form vs button** (m3): `hx-disabled-elt="this"` on a `<form>` silently no-ops. The create-notebook form already has `hx-disabled-elt="find button"` (correct). The remove-notebook button already has `hx-disabled-elt="this"` (correct — a `<button>`, not a `<form>`).

- Git log: `efd8d36 chore(plans): shape ui-attractive-polish-m5 + restate KR5 cap` is the roadmap shaping commit. `df58b27 rect(server,tests): close 2 MEDIUM + 1 LOW from m4 critique` shows F1/F2 closed, F3 deferred. Current state: m4 is complete (state.json for m4 is `phase: complete`); m5 is `research-running`.

---

## Failure-mode analysis (grounded in `08-security-observability-ops.md`)

**Mode A — stored XSS via `_notebook_row_html` display_name interpolation:**
*Trigger:* operator creates a notebook with `display_name = '<img src=x onerror=alert(1)>'`; HX-Request branch renders it. *Symptom:* unescaped HTML executes in browser. *Mitigation:* `_notebook_row_html` MUST call `html.escape()` on every argument before interpolation (per m4's `_paper_row_html` precedent). Jinja2 autoescape only covers `.html` template rendering, NOT server-side f-string assembly. The Spike-2 checklist AC includes an XSS payload test — this is mechanically enforced.

**Mode B — existing 204 tests break on `delete_notebook` content-negotiation:**
*Trigger:* implementer changes `status_code=HTTP_204_NO_CONTENT` to `HTTP_200_OK` unconditionally, or adds a content-negotiation branch that changes the 204 path. *Symptom:* `test_notebook_api.py:139` and `test_notebook_rename_delete.py:256` fail. *Mitigation:* content-negotiation is added as a NEW branch: `if request.headers.get("hx-request") == "true": return Response(status_code=200)` AFTER the existing 204 path — the default return remains `None` (FastAPI infers 204). The DELETE handler signature must be changed from `-> None` to a union type (like m4's `add_paper`). `response_model=None` must be added.

**Mode C — `hx-target="closest tr"` on delete-notebook button (no `<tr>` ancestor):**
*Trigger:* implementer applies the remove-row pattern to the delete-notebook button in `notebook_detail.html:83` which lives in `<div class="notebook-actions">`, not a `<tr>`. *Symptom:* htmx silently no-ops; no visible feedback. *Mitigation:* The delete-notebook button's `hx-on::htmx:after-request` navigation (`window.location.href='/ui/'`) must remain unchanged. Only the two remove buttons that ARE inside `<tr>` elements get the `hx-target="closest tr"` treatment.

**Mode D — row-fade keyframe fires before/after the swap window:**
*Trigger:* `animation-fill-mode: forwards` missing from the row-fade keyframe; or the keyframe targets `.htmx-swapping` but the selector does not match the `<tr>` element that IS the htmx swap target. *Symptom:* row flashes back to full opacity after the 200ms delay before disappearing (jarring). *Mitigation:* The swap target IS the `<tr>` (via `hx-target="closest tr"`), so htmx adds `htmx-swapping` directly to the `<tr>`. CSS selector `tr.htmx-swapping` with `animation-fill-mode: forwards; animation: row-fade-out 200ms ease-out;` is correct. The `animation-duration` must match the `swap:200ms` modifier.

**Mode E — UPL-19 clamp upper bound and reading rhythm:**
*Trigger:* `clamp(640px, 92vw, 1400px)` — at 1527px viewport (27" 2560-wide monitor at 2x scaling), `92vw = 1404px`, clamped to `1400px`. At 16px base font with monospace table cells, 1400px ≈ ~87ch table width, not 70ch as the brief estimates (70ch at 16px is ~1120px; 1400px / 16px ≈ 87.5 average chars). *Symptom:* paper-ID and display-name cells feel very wide at maximum width; reading rhythm degrades. *Mitigation:* The brief's wording applies `clamp(640px, 92vw, 1400px)` to `body { max-width }`, affecting the whole page. The table is inside `.table-wrap { overflow-x: auto }` (from m2), so it won't overflow. The reading rhythm concern is a design taste trade-off; the brief explicitly accepts it for this milestone. The `1400px ≈ 70ch` estimate is wrong (assumes 20px body font), but the trade-off decision stands.

**Mode F — UPL-8 v1 dark `@media` selector specificity mismatch:**
*Trigger:* inside `@media (prefers-color-scheme: dark)`, the implementer adds `.status-badge--ok { ... }` without checking whether the original light-mode rules at `app.css:159-162` carry the same specificity (they do — no ID selectors, no `!important`). *Symptom:* dark-mode override silently loses to light-mode rule due to source order. *Mitigation:* Both the light and dark declarations have the same single-class specificity (0,1,0). The dark `@media` block appears AFTER the light rules (line 236+), so source order ensures the dark block wins when the `@media` matches. Correct as designed.

**Mode G — m4-F3 `this.reset()` test ordering:**
*Trigger:* `this.reset()` clears the input on the client after a successful POST; the m4 negative-regression test only checks server-side HTML. *Symptom:* test passes but the JavaScript behavior is not exercised. *Mitigation:* The test for m4-F3 is a template assertion (`'this.reset()' in form_block`, per m4 critique F3 proposed fix). No test-ordering issue; the JS is never invoked by the test client — only the template attribute presence is verified. Fine.

**Mode H — cap-test drift if only ONE of the two cap tests is updated:**
*Trigger:* implementer updates `test_ui_m4_in_place_add_paper.py` cap from 335 → 365 but forgets `test_ui_m3_dark_and_htmx_feedback.py`. *Symptom:* the m3 cap test (still at 335) fails because `app.css` is ~343 lines. *Mitigation:* The m4-rect F1 docstring explicitly states both must move in lockstep. The implementer must update BOTH cap tests. m5 should update both to `<= 365`.

**Mode I — CSS budget pre-computation:**
Estimated additions: 5 lines (UPL-8 v1 dark pill remaps + th) + 5 lines (row-fade keyframe + selector) + 0 net (UPL-19 replacement). Total: 333 + ~10 = ~343 lines. The 365-line cap has ~22 lines of headroom. No risk of blowing the cap unless the implementer adds verbose CSS comments.

---

## Recommendation

Implement all m5 work items in the following order:

1. **m4-F3 first** (1 template line; zero risk; closes a deferred finding immediately).
2. **UPL-8 v1** (CSS-only; add 5 declarations inside the existing dark `@media` block at `app.css:236`; use the confirmed-compliant palette from the contrast table above).
3. **UPL-19 v1** (1-line `max-width` replacement; no tests required beyond the existing layout test, if any).
4. **UPL-12 v1 create-notebook** (add `_notebook_row_html` helper + content-negotiation branch in `create_notebook`; update `index.html` create-form to `hx-target="#notebooks-tbody" hx-swap="beforeend"`; rename `id="notebook-list"` to `id="notebooks-tbody"` on the `<tbody>` in `index.html`; add `aria-live="polite"` to the tbody).
5. **UPL-12 v1 remove-notebook** (add content-negotiation branch to `delete_notebook` returning 200+empty for HX-Request; update the remove button in `index.html` to `hx-target="closest tr" hx-swap="outerHTML swap:200ms"`; add row-fade keyframe to `app.css` in the existing `prefers-reduced-motion: no-preference` block).
6. **Update BOTH cap tests** to `<= 365`.

The 204-vs-200 content-negotiation is the highest-risk change. Prefer the pattern: add `Request` to `delete_notebook`'s signature, add `response_model=None`, add a content-negotiation branch that returns `Response(status_code=200, content=b"")` BEFORE the existing `return None`, and keep `status_code=HTTP_204_NO_CONTENT` as the default decorator. Do NOT change `remove_paper` (the per-paper delete) — it already uses a JS `.closest('tr').remove()` pattern on 204. The brief only covers the notebook-level delete for the row-removal htmx pattern.

---

## Open questions

1. **`#notebook-list` vs `#notebooks-tbody` ID:** The milestone brief's AC refers to `hx-target="#notebooks-tbody"` but `index.html:48` uses `id="notebook-list"`. The implementer must pick one and update both the template AND any test that asserts the ID. The brief's `#notebooks-tbody` is the better choice (more explicit), but requires renaming the existing `id="notebook-list"` in `index.html`.

2. **`ops-warn` dark border color:** The light-mode `--ops-warn` uses a separate border color (`#94a3b8`, not the text `#475569`). The brief proposes reusing the text `#8b949e` as both border and text in dark mode. The implementer should decide: (a) single-color simplification (all 4 pills use text=border, uniform pattern) or (b) match the light-mode pattern (separate, more specific border for ops-warn). Both pass SC 1.4.11. Recommendation: simplify to single-color for all 4 pills in dark mode — consistency outweighs the light-mode analogy.

3. **`remove_paper` (per-paper DELETE) conversion:** The brief's AC says remove buttons in `notebook_detail.html` (both index AND detail) should use the htmx row-removal pattern. The existing remove-paper button at `notebook_detail.html:250-256` already uses a JS `this.closest('tr').remove()` pattern on 204 — this is the "per-paper" remove, NOT the "notebook" remove. The brief's UPL-12 v1 text is ambiguous about whether `remove_paper` also gets converted from JS-`.closest()` to native htmx `hx-target="closest tr" hx-swap="outerHTML"`. If so, `remove_paper` must also return 200+empty for HX-Request (currently 204 always). This could break `test_notebook_api.py:315` and `:331`. **My recommendation: scope UPL-12 v1 remove to ONLY `delete_notebook` (notebook-level); leave `remove_paper` on its existing JS pattern.** The brief's ambiguity should be resolved before implementation.

---

## External writes the implementation will require

None — this milestone is purely local. All changes are to `server/routes/notebooks.py`, `frontend/templates/index.html`, `frontend/templates/notebook_detail.html`, `frontend/static/app.css`, and a new `tests/test_ui_m5_create_remove_in_place.py`. No git push, no GitHub PR, no issue creation, no infra mutation.
