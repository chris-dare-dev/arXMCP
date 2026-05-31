# Research synthesis — ui-attractive-polish-m5

**Orchestrator:** milestone-pipeline main session
**Generated:** 2026-05-31
**Source briefs:** `research-brief-1.md` (in-codebase-first), `research-brief-2.md` (external + failure-modes)
**Both briefs:** status `ok` (R1) / `partial` (R2; "partial" due to remove_paper scope flag — resolved here)

---

## Implementation scope (synthesis-authoritative; supersedes the brief where flagged)

The m5 bundle is **5 concrete items**, ordered by risk ascending:

| # | Item | Surface | Files | Risk |
|---|---|---|---|---|
| 1 | **m4-F3** (form `this.reset()`) | 1 attr on add-paper form | `notebook_detail.html` | None |
| 2 | **UPL-19 v1** (wider clamp) | 1 CSS rule | `app.css` body | None |
| 3 | **UPL-8 v1** (dark-mode pill remap + `th` dark redeclaration) | 5 CSS rules inside existing dark `@media` block | `app.css` | Low (contrast-verified) |
| 4 | **UPL-12 v1 create-notebook** (in-place htmx swap) | `_notebook_row_html` helper + content-negotiation + template attrs + tbody rename | `server/routes/notebooks.py`, `frontend/templates/index.html` | Medium |
| 5 | **UPL-12 v1 remove-notebook** (htmx row-removal with 204→200 for HX-Request) | content-negotiation + template attrs + row-fade keyframe | `server/routes/notebooks.py`, `frontend/templates/index.html`, `app.css` | Medium-High |
| 6 | **Cap-test lockstep** | both cap tests | `tests/test_ui_m3_dark_and_htmx_feedback.py`, `tests/test_ui_m4_in_place_add_paper.py` | None |

Implement in this order (m4-F3 → UPL-19 → UPL-8 → UPL-12 create → UPL-12 remove → cap-tests).

---

## Critical resolutions (where the brief or one researcher was wrong)

### C1 — Slug derivation: NO `slugify()` exists

The milestone brief says (line 633 of the roadmap):
> "create generates the slug server-side from `slugify(notebook_name)` and must re-validate the result"

**R1 verified this against actual code: WRONG.** `create_notebook` (`server/routes/notebooks.py:251-351`) accepts `NotebookCreate(slug, display_name, notebook_kind)` — slug is operator-supplied via the `<input type="text" name="slug">` field at `index.html:20`. The handler calls `validate_slug(body.slug)` directly. No `slugify()` exists.

**Resolution:** Implement per actual code. The `_notebook_row_html` fragment interpolates `body.slug` (the validated operator-supplied slug), `body.display_name`, `body.notebook_kind`, and a server-generated `created_at = _now_iso()`. Do NOT introduce a `slugify()` call.

### C2 — `#notebook-list` → `#notebooks-tbody` rename required

Both R1 and R2 confirmed: `index.html:48` currently uses `<tbody id="notebook-list">`, but the AC says `hx-target="#notebooks-tbody"`. **Resolution: RENAME to `#notebooks-tbody`** for consistency with `#papers-tbody` (the m4 pattern). Add `aria-live="polite"` to the renamed tbody (mirrors m1 UPL-3 swap-target pattern).

**Search for any test that pins the old ID before renaming:** `grep -rn "notebook-list" tests/`. If matches exist, update them in the same commit.

### C3 — 204 vs 200 for HX-Request DELETE (htmx behavior confirmed by docs)

R2 quoted the vendored `htmx.min.js` config:
```
{code:"204",swap:false}
{code:"[23]..",swap:true}
```

htmx 2.0.10 **skips the swap on 204**. To make `hx-swap="outerHTML"` actually remove the row, the HX-Request branch must return **200 with empty body**. The JSON branch stays 204 (existing tests at `tests/test_notebook_api.py:139` + `tests/test_notebook_rename_delete.py:256` send no `HX-Request` header and remain on 204 → no breakage).

**Resolution:** Keep `status_code=HTTP_204_NO_CONTENT` on the `@router.delete` decorator. Add `request: Request` + `response_model=None` to the handler. The HX-Request branch returns `Response(status_code=200, content=b"")` BEFORE the existing `return None`. Mirror m4's `add_paper` content-negotiation pattern exactly.

### C4 — Pill contrast: R2 is correct; R1's approximations were off

**DISAGREEMENT:** R1 computed quick approximations and flagged 3 of 4 pairs as borderline-failing. R2 computed using the canonical WCAG 2.1 sRGB-linearization formula and confirmed all 4 pairs PASS.

R2's contrast table (re-verified against WebAIM Contrast Checker formula):

| Badge | BG | Text | Text contrast | Verdict |
|---|---|---|---|---|
| `--ok` | `#0d2818` | `#3fb950` | **6.20:1** | ✅ PASS |
| `--warn` | `#3d2a07` | `#d29922` | **5.43:1** | ✅ PASS |
| `--ops-warn` | `#1c2230` | `#8b949e` | **5.17:1** | ✅ PASS |
| `--down` | `#3d1216` | `#f85149` | **4.83:1** | ✅ PASS |

**Resolution:** Use the brief's proposed palette unchanged. R1's quick approximations didn't apply sRGB-to-linear gamma correction; R2's full formula is authoritative.

**Insurance:** Add a regression test (`TestUPL8V1DarkModePillContrast`) that programmatically computes contrast for each pill via the WCAG formula and asserts ≥ 4.5:1. If a future edit lowers any pair below threshold, the test catches it.

### C5 — `remove_paper` is OUT OF SCOPE

The roadmap brief text under UPL-12 v1 (remove-notebook) says:
> "the remove-button HTML in both `index.html` (notebooks list) AND `notebook_detail.html` (per-paper remove)"

**R2 verified this against actual code: the per-paper remove button at `notebook_detail.html:250-256` already uses a JS `this.closest('tr').remove()` pattern on 204** — it does NOT use `location.reload()`. The "three legacy `location.reload()` flows" the roadmap enumerates are: add-paper (m4 converted), create-notebook (m5), **delete-notebook** (m5, the notebook-level delete). The per-paper remove is on a different pattern entirely.

**Resolution:** m5 scope for UPL-12 v1 remove is **ONLY the notebook-level `DELETE /ui/api/notebooks/{slug}`** (i.e. the remove-notebook button in `index.html`). The per-paper remove button at `notebook_detail.html:250-256` STAYS on its existing JS-`.closest()` pattern — converting it is a separate concern (NOT m5 scope; not roadmap'd).

### C6 — `hx-target="closest tr"` ancestor hazard

R2 flagged: `notebook_detail.html:83` has a DELETE NOTEBOOK button inside `<div class="notebook-actions">` — **NOT inside a `<tr>`**. `hx-target="closest tr"` would silently no-op (no `<tr>` ancestor exists). This button currently uses `hx-on::htmx:after-request="if(event.detail.successful) window.location.href='/ui/'"` (a navigation, not a reload) — it's a different flow.

**Resolution:** Do NOT apply `hx-target="closest tr"` to the delete-notebook button at `notebook_detail.html:83`. That button keeps its existing `window.location.href` navigation (it makes sense — deleting the currently-viewed notebook should navigate away, not just remove a row). Only the remove-notebook button INSIDE the notebooks-index `<tbody>` (i.e. in `index.html`) gets the row-removal pattern.

### C7 — `ops-warn` border color: simplify to single-color uniformly

R2 flagged that the light-mode `--ops-warn` rule uses a separate border (`#94a3b8`) from the text (`#475569`), while the other 3 pills use text=border. The brief's dark-mode proposal reuses text=border for all 4.

**Resolution:** In dark mode, use text=border uniformly for all 4 pills (single-color simplification). Both colors pass SC 1.4.11 (≥ 3:1 vs background) per R2's contrast table. Consistency outweighs matching the light-mode anomaly.

### C8 — Row-fade keyframe placement: consolidate into existing block

Both researchers agree: the row-fade keyframe MUST go inside the EXISTING second `@media (prefers-reduced-motion: no-preference)` block at `app.css:321-333` (where m4's badge-flash + UPL-13 View Transitions duration already live). Do NOT open a third reduced-motion block.

**Selector:** `tr.htmx-swapping` (the swap target IS the `<tr>` via `hx-target="closest tr"`, so htmx adds the class directly to the row).

**Animation:** `animation: row-fade-out 200ms ease-out; animation-fill-mode: forwards;` — the `forwards` fill-mode keeps opacity at 0 during the settle phase so the row doesn't flash back before removal.

**Keyframe:** `@keyframes row-fade-out { from { opacity: 1; } to { opacity: 0; } }`.

---

## Spike-2 pre-flight checklist — applies TWICE in m5

The 13-item checklist from `.claude/notes/ui-attractive-polish-spike-2.md` is re-applied to both new fragment endpoints. The adversary critic will verify each item.

**Validation ordering precedent (load-bearing):** From m4 critique "what was done well": every Spike-2 pre-flight item that says "validation runs BEFORE the response fork" actually does — `validate_slug` → notebook-exists → ... → THEN the HX-Request branch. **The HTML branch must not be reachable on any invalid input.** m5 mirrors this for BOTH new endpoints.

**Specific m5 ordering:**
- `create_notebook`: `validate_slug(body.slug)` → notebook_dir containment → `store.create_notebook` → mkdir → THEN HX-Request fork.
- `delete_notebook`: `validate_slug(slug)` → `store.get_notebook` → `store.delete_notebook` → THEN HX-Request fork.

**Per-value `html.escape()` in `_notebook_row_html`:** mirror `_paper_row_html` exactly. No `Markup(...)`, no `| safe`. The XSS payload test (`display_name = '<img src=x onerror=alert(1)>'`) is a load-bearing test in m5's new test file.

---

## Implementation plan (authoritative)

### Files touched

```
server/routes/notebooks.py                    (+~80/-5)   _notebook_row_html helper; create_notebook + delete_notebook content-negotiation
frontend/templates/index.html                 (+~6/-4)    tbody rename + aria-live; create form attrs; remove buttons attrs
frontend/templates/notebook_detail.html       (+1/-0)     m4-F3 form this.reset()
frontend/static/app.css                       (+~12/-1)   UPL-19 body clamp; UPL-8 v1 4 pill remaps + th dark; row-fade keyframe in existing block
tests/test_ui_m5_create_remove_in_place.py    (NEW ~500)  ~35 tests across 8 classes
tests/test_ui_m3_dark_and_htmx_feedback.py    (+1/-1)     cap raise 335 → 365 (lockstep)
tests/test_ui_m4_in_place_add_paper.py        (+1/-1)     cap raise 335 → 365 (lockstep)
```

Estimated total: ~600 LOC additions across 7 files; well under the 500-LOC delegated-path threshold → **INLINE implementation path**.

### Test file structure (mirror m4's 7-class pattern)

`tests/test_ui_m5_create_remove_in_place.py`:

1. `TestUPL12V1NotebookRowHtml` (4 tests) — `_notebook_row_html` value escaping (slug, display_name, kind XSS payloads).
2. `TestUPL12V1CreatePreFlightChecklist` (6 tests) — Spike-2 13-item gate mechanically exercised for create.
3. `TestUPL12V1CreateTemplateChanges` (4 tests) — tbody rename + aria-live + form attrs + negative-regression on `location.reload`.
4. `TestUPL12V1DeletePreFlightChecklist` (5 tests) — Spike-2 13-item gate mechanically exercised for delete; specifically the 204 vs 200 fork, the 204 path preservation for JSON, validate_slug ordering.
5. `TestUPL12V1DeleteTemplateChanges` (3 tests) — remove buttons `hx-target="closest tr"` + `hx-swap="outerHTML swap:200ms"`; the delete-notebook button at `notebook_detail.html:83` UNCHANGED.
6. `TestUPL8V1DarkModePillContrast` (5 tests) — programmatic WCAG contrast verification for all 4 pill pairs (this is the C4 insurance test); each pill has its dark-mode rule present in the dark `@media` block; `th { background }` dark redeclaration present.
7. `TestUPL19V1BodyClamp` (2 tests) — `body { max-width: clamp(640px, 92vw, 1400px) }` present; `980px` no longer in body rule.
8. `TestM4F3FormReset` (2 tests) — `this.reset()` attribute present on add-paper form; m4's `location.reload` negative-regression still passes.
9. `TestCrossMilestoneSafety` (4 tests) — m1/m2/m3/m4 surfaces unchanged; `app.css` line count ≤ 365 (cap-test lockstep).

### `_notebook_row_html` schema (matching the existing notebooks-index `<thead>`)

Read `frontend/templates/index.html` around the tbody to confirm the column order before coding. Expected schema (5 columns, mirroring the existing rendered template — verify):

```html
<tr data-slug="{escape(slug)}">
  <td>{escape(slug)}</td>
  <td>{escape(display_name)}</td>
  <td>{escape(notebook_kind)}</td>
  <td>{escape(created_at)}</td>
  <td><a href="/ui/notebooks/{escape(slug)}">Open</a></td>
</tr>
```

**Per the m4 pattern:** NO Remove button in the immediate post-create row. The next page-load restores the standard Remove affordance via the rendered template. This matches m4's "added" Actions cell rationale.

**Do NOT interpolate `lancedb_path`** — it's a host-path leak per `06-mcp-server-design.md`. The JSON branch keeps returning it (existing behavior); the HTML branch must NOT include it.

### `delete_notebook` content-negotiation pattern

```python
@router.delete(
    "/notebooks/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # m5: union return (Response | None)
)
async def delete_notebook(
    slug: str,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),
) -> Response | None:
    validate_slug(slug)  # MUST precede the fork
    # ... existing get_notebook 404 + store.delete_notebook ...
    if request.headers.get("hx-request") == "true":
        # htmx 2.0.10 skips swap on 204; return 200 empty so
        # hx-swap="outerHTML" actually removes the row.
        return Response(status_code=status.HTTP_200_OK, content=b"")
    return None  # FastAPI infers 204 from decorator
```

### Row-fade keyframe (consolidates into existing block at app.css:321-333)

```css
@media (prefers-reduced-motion: no-preference) {
  /* ... existing UPL-22 badge-flash + UPL-13 View Transitions ... */

  /* ui-attractive-polish-m5 (UPL-12 v1): row-fade for in-place
     notebook removal. htmx adds .htmx-swapping to the swap target
     (the <tr>) during the swap:200ms delay; animation-fill-mode:
     forwards keeps opacity at 0 through the settle phase so the
     row doesn't flash back before removal. Selector matches
     hx-target="closest tr" + hx-swap="outerHTML swap:200ms" on
     the remove-notebook button in index.html. */
  tr.htmx-swapping {
    animation: row-fade-out 200ms ease-out;
    animation-fill-mode: forwards;
  }
  @keyframes row-fade-out {
    from { opacity: 1; }
    to   { opacity: 0; }
  }
}
```

### `app.css` line budget pre-computation

- Current: 333 lines (post-m4-rect).
- UPL-19 v1: +0 lines (1-line replacement).
- UPL-8 v1: +5 lines (4 pill remaps + 1 `th` redeclaration, all inside existing dark block).
- UPL-12 v1 row-fade: +9 lines (selector + 2 animation properties + keyframe block).
- **Total m5: ~+14 lines → 347 lines.** Cap raised to 365 leaves ~18 lines headroom.

### Cap-test update text (both files)

Update the assertion AND the docstring trajectory in BOTH:

- `tests/test_ui_m3_dark_and_htmx_feedback.py::TestCrossMilestoneSafety::test_app_css_under_soft_cap` — 335 → 365 with docstring update.
- `tests/test_ui_m4_in_place_add_paper.py::TestCrossMilestoneSafety::test_app_css_under_revised_soft_cap` — 335 → 365 with docstring update.

The docstring chain MUST stay in sync. Per m4-rect F1: "future cap raises MUST move BOTH this test AND the m3 cap test in lockstep."

---

## Open questions (deduped + resolved)

| ID | Question | Resolution |
|---|---|---|
| Q1 | `delete_notebook` 204 vs HX-Request 200 | C3 above — 204 default decorator unchanged; HX-Request branch returns 200 empty body. |
| Q2 | `#notebook-list` vs `#notebooks-tbody` | C2 above — RENAME to `#notebooks-tbody`; grep tests/ first to catch any pin. |
| Q3 | Slug derivation in create_notebook | C1 above — operator-supplied via form field; NO `slugify()`. Brief was wrong. |
| Q4 | Row-fade keyframe placement | C8 above — consolidate into existing `@media (prefers-reduced-motion: no-preference)` block. |
| Q5 | Pill contrast verification | C4 above — R2's full-formula computation is authoritative; use brief's palette unchanged + add programmatic regression test. |
| Q6 | `ops-warn` dark border color | C7 above — single-color (text=border) uniformly across all 4 pills in dark mode. |
| Q7 | `remove_paper` (per-paper) scope | C5 above — OUT OF SCOPE; per-paper remove keeps its JS-`.closest()` pattern. |
| Q8 | `hx-target="closest tr"` on delete-notebook button (no `<tr>` ancestor) | C6 above — that button keeps its `window.location.href` navigation; only the remove-notebook button INSIDE the index tbody gets the row-removal pattern. |

**No remaining open questions.**

---

## External writes required

| type | target | why | blocking phase |
|---|---|---|---|
| `git_push` | `origin/main` | Land feat + rect (if any) + chore(notes) finalize triple per CLAUDE.md §4.3 | Phase 4 user gate per §4.4 |

(R1 listed this; R2 said none — R2's "none" referred to non-git external writes. Git push is always per-event authorized; surface to Chris at Phase 4.)

---

## Orchestrator synthesis note

**Divergences resolved:**
- **R1 vs R2 on pill contrast** — R2's full WCAG sRGB-linearization formula is authoritative; R1's approximations skipped gamma correction. Used R2's table.
- **Brief vs actual code on slugify** — actual code wins (no `slugify()`); the brief's wording was inaccurate. Documented as C1.
- **Brief vs actual code on remove_paper scope** — actual code wins (per-paper remove uses JS-`.closest()`, not `location.reload()`); scoped m5 to notebook-level remove only. Documented as C5.
- **Brief vs actual code on `#notebooks-tbody` ID** — RENAME the existing `#notebook-list` to `#notebooks-tbody` to match the AC and m4 naming convention. Documented as C2.

**Insurance baked in:**
- Programmatic WCAG contrast test for all 4 pill pairs (so a future palette change can't silently regress; resolves the R1/R2 contrast disagreement permanently).
- Both cap-tests updated in lockstep with cross-reference docstrings.
- The 204-vs-200 fork is documented in both the handler comment AND a dedicated regression test.

**Risk posture:** Two new fragment endpoints, both following m4's precedent mechanically. The highest-risk piece is `delete_notebook`'s 204→200 content-negotiation; mitigation is verification that the existing 204 tests (`test_notebook_api.py:139`, `test_notebook_rename_delete.py:256`) still pass unchanged (they send no `HX-Request` header).
