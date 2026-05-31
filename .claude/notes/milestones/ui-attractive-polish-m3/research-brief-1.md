# Research Brief — ui-attractive-polish-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T00:00:00Z

---

## In-codebase context

### Design constitution — applicable notes

**`06-mcp-server-design.md` § "Browser UI surface"** (load-bearing verbatim):
> "**loopback-only, server-rendered Jinja2 + htmx operator console** ships with the server.
> It is an operator convenience for notebook management — NOT a general-purpose research
> front-end, and NOT an SPA. **Hard constraint: no SPA, no Node/npm build chain.** htmx
> is vendored under `frontend/static/`; templates live under `frontend/templates/`. The
> MCP tool surface remains the primary agent interface; this console exists alongside it."

**CLAUDE.md §4.7** (load-bearing verbatim):
> "`assert` is BANNED for invariants — Python `-O` strips them."
> "Pure-ASGI middleware required. `BaseHTTPMiddleware` is project-banned."
> "No `anthropic` SDK at runtime."

Doc-placement rule (CLAUDE.md §1, `agent-conventions.md §6`): new Markdown goes under
`.claude/`. The test file (`tests/test_ui_m3_dark_and_htmx_feedback.py`) is code, not
Markdown — it belongs under `tests/`.

**`07-multi-agent-caching.md`**: m3 modifies no tool definitions, no prompt schemas, and
no server-side endpoint. No `EXPECTED_TOOL_SCHEMA_SHA256` re-pin is required. The BP1/BP2
cache breakpoints in `server/prompts.py` are untouched.

### Current `frontend/static/app.css` state (post-m2, 216 lines)

Key load-bearing facts:

1. **`app.css:4-13`** — 8 `:root` tokens defined: `--fg: #1a1a1a`, `--bg: #f8f8f8`,
   `--card-bg: #fff`, `--border: #d8d8d8`, `--accent: #1e5b8a`, `--danger: #a3271a`,
   `--error-bg: #fff4f2`, `--mono: ui-monospace, ...`.
2. **`app.css:87-95`** — m2's `color-mix()` button hover rule (UPL-9) already live.
3. **`app.css:149-152`** — `.status-badge--ok/--warn/--ops-warn/--down` hardcoded color
   pills (NOT using CSS tokens). Per the v0/v1 split, these stay light-mode in m3.
4. **`app.css:104`** — `th { background: #f0f0f0; }` hardcoded. Per the v0/v1 split, this
   also stays light-mode (table-header dark surface descoped to v1).
5. **`app.css:200-216`** — `@media (prefers-reduced-motion: reduce)` universal gate (UPL-1),
   covering all 6 timing properties. This is the INVERSE of the gate m3's spin animation
   needs: the spinner must be inside `@media (prefers-reduced-motion: no-preference)`.
6. **`app.css:189-198`** — `:focus-visible` rules using `var(--accent)` for all interactive
   elements; `button.danger:focus-visible` uses `var(--danger)`. When `--accent` is
   rebound to `#58a6ff` (dark mode), focus rings will automatically update — no additional
   rules needed.

Current line count: 216. Budget for m3: +~50 lines (dark block ~15 lines +
htmx-request block ~20 lines + spin keyframe + media wrapper ~15 lines) = ~266 total.
Milestone AC cap is 270. Comfortable within the 300-line CLAUDE.md soft cap.

### htmx-bound form elements — full inventory

All 8 htmx-bound elements across both templates:

| # | File | Line | Element | Method | AC label |
|---|---|---|---|---|---|
| 1 | `index.html:12` | `<form hx-post=/ui/api/notebooks>` | POST | Create notebook |
| 2 | `index.html:55` | `<button hx-delete=.../{{ nb.slug }}>` | DELETE | Remove notebook (per row) |
| 3 | `notebook_detail.html:31` | `<form hx-patch=.../{{ notebook.slug }}>` | PATCH | Rename |
| 4 | `notebook_detail.html:81` | `<button hx-delete=.../{{ notebook.slug }}>` | DELETE | Delete notebook |
| 5 | `notebook_detail.html:97` | `<form hx-post=.../papers>` | POST | Add paper by URL |
| 6 | `notebook_detail.html:120` | `<form hx-post=.../papers/upload>` | POST | Upload ar5iv HTML |
| 7 | `notebook_detail.html:152` | `<form hx-post=.../ingest>` | POST | Ingest now |
| 8 | `notebook_detail.html:235` | `<button hx-delete=.../{{ p.paper_id }}>` | DELETE | Remove paper (per row) |

The milestone brief says "7 htmx-bound `<form>` elements" — the actual count is **5 `<form>`
elements + 3 `<button>` elements = 8 total htmx triggers**. The brief's "7" appears to
conflate the index "Remove notebook" and detail "Delete notebook" as one.

**CRITICAL — `hx-disabled-elt="this"` semantics differ for `<form>` vs `<button>`:**
The `disabled` attribute on a `<form>` element is non-standard HTML. Browsers do NOT
propagate `form.disabled` to child inputs or buttons. Setting `hx-disabled-elt="this"` on
a `<form>` adds `disabled` to the form element only — which has no browser-enforced effect
on keyboard Enter double-fire. For the 5 `<form>` elements, the correct value is
`hx-disabled-elt="find button"` (or `"find button[type=submit]"`), which targets the
submit button inside the form. For the 3 standalone `<button>` elements, `"this"` IS
correct.

### m2 critique patterns (F1/F2/F3) as precedent

- **F1 (MEDIUM):** regression guards must use `APP_CSS_NO_COMMENTS` (comment-stripped CSS),
  not raw `APP_CSS`, so documentation comments containing the asserted substring don't
  produce false-clean results. Pattern: `test_filter_brightness_removed` in
  `test_ui_m2_polish.py` is the established model.
- **F2 (MEDIUM):** implementation-summary line-count claims must match `wc -l` output. The
  m3 implementation summary should record the final actual count, not the AC estimate.
- **F3 (MEDIUM):** any new project-authored static asset should be listed in
  `frontend/static/VENDORED.md` as "Project-authored, not vendored. No hash recorded."
  m3 adds no new static asset (dark mode is CSS-only; htmx-request is CSS-only).

### Existing test suite baseline

- `tests/test_ui_a11y_baselines.py` — 23 tests (m1). **Must all pass after m3.**
- `tests/test_ui_m2_polish.py` — 16 tests (m2), corrected to 18 after m2-rect F1+F3 fixes.
  **Must all pass after m3.**
- New file for m3: `tests/test_ui_m3_dark_and_htmx_feedback.py`.

m3 must not modify any assertion in the 41 existing tests. The most fragile adjacency:
`test_body_max_width_980px_preserved` (m2 F1-fixed version) uses a body-scoped regex — m3's
dark mode block will not affect the body rule and won't trip it.

### `.status-badge--*` modifier colors — v0/v1 split

`app.css:149-152` hardcodes: `--ok: #e6f4ea/#1a7f37`, `--warn: #fdf3e2/#8a5a00`,
`--ops-warn: #eef2f7/#475569`, `--down: var(--error-bg)/var(--danger)`. On dark `--card-bg`
`#161b22`, these light-mode pill backgrounds become a dark-on-dark collision for `--ok`
and `--warn` (dark `#161b22` card under a `#e6f4ea` pill). The UPL-8 v0/v1 split explicitly
accepts this: the pills keep light-mode contrast (the pill BG is light, the pill text is
dark — so the pill is INTERNALLY consistent, just contrast-jarring against the dark card).
The milestone brief confirms: "visually inconsistent but a11y-safe."

---

## Prior decisions and lessons

### From git log

Recent commits confirm m1 (`c5adff3`) landed the `prefers-reduced-motion` gate and the
`:focus-visible` rules; m2 (`672ad81`) landed the `color-mix()` adoption and tabular-nums.
Both are on `origin/main`. The m2-rect commit (`4f1f664`) fixed F1/F2/F3.

Key m1 commit: `c5adff3 feat(server,frontend): foundational a11y baselines (ui-attractive-polish-m1)`.
This IS the commit adding the `@media (prefers-reduced-motion: reduce)` block at `app.css:200-216`.
The inverse gate (`@media (prefers-reduced-motion: no-preference)`) that m3's spin needs is
NOT yet in the file — m3 introduces it fresh.

### From m1 implementation-summary

> "Per motion-vocabulary.md MOT-NO-5, any future animation that omits the no-preference gate
> is now a Phase-3 BLOCKER."

This is the anchor for m3's spinner: the `animation: spin` MUST be inside
`@media (prefers-reduced-motion: no-preference)`. The `opacity`, `pointer-events`, and
`cursor` properties are NOT animation/motion — they are unconditional per the milestone brief
("signal, not motion").

### VENDORED.md pattern

m3 adds no new static assets (no SVG, no JS file). `VENDORED.md` does not need updating.
`tests/test_vendored_assets_integrity.py` is unaffected.

### macOS segfault guard

`tests/conftest.py` `KMP_DUPLICATE_LIB_OK=TRUE` is untouched — m3 touches no ML libraries.

### Kùzu version pin

Not touched by m3.

---

## External sources

### `prefers-color-scheme` — Baseline status

MDN confirms: **Baseline Widely Available** since January 2020. Works in Chrome, Safari,
Firefox on macOS. No edge cases for the use pattern in this milestone (`:root` token
rebinding in a `@media` block). The behavior is identical on macOS Safari and Chrome.

### WCAG 2.1 contrast ratios — verified for the proposed dark palette

Calculated via WCAG relative luminance formula against the 7 proposed dark values:

| Pair | Ratio | Threshold | Result |
|---|---|---|---|
| `--fg #e8e8e8` on `--bg #0d1117` | 15.45:1 | 4.5:1 (text SC 1.4.3) | PASS |
| `--fg #e8e8e8` on `--card-bg #161b22` | 14.12:1 | 4.5:1 (text SC 1.4.3) | PASS |
| `--accent #58a6ff` on `--bg #0d1117` | 7.49:1 | 3:1 (non-text SC 1.4.11) | PASS |
| `--danger #f85149` on `--bg #0d1117` | 5.65:1 | 3:1 (non-text SC 1.4.11) | PASS |
| `--border #30363d` on `--bg #0d1117` | **1.55:1** | 3:1 (non-text SC 1.4.11) | **FAIL** |
| `--border #30363d` on `--card-bg #161b22` | **1.42:1** | 3:1 (non-text SC 1.4.11) | **FAIL** |

**`--border` fails SC 1.4.11 (3:1) at #30363d.** The border is used on `.card`, input
fields, table cells (`th`/`td`), and `.status-badge`. Input-field borders are UI component
visual indicators — SC 1.4.11 applies. However: the milestone's AC is scoped to "WCAG AA
non-text contrast (≥ 3:1) for `--fg` on `--bg` and `--fg` on `--card-bg`" only — the
border token is not in the AC's verification scope. Still, the adversary critic will flag it.

**Recommendation:** Use `--border: #484f58` (2.28:1 — still fails) or **`--border: #6e7681`**
(4.12:1 — passes). GitHub's actual dark-mode border uses `#30363d` for decorative separators
and a different token for interactive-element borders; arXMCP uses one `--border` token for
both. Pick `#484f58` as a pragmatic middle ground (lighter than Primer's dark border but
consistent with the Primer scale, and the brief's v0 scope narrows the AC to fg contrast
only — this is the **implementer's call**).

**Alternatively:** Accept `#30363d` for v0 since the AC explicitly limits contrast
verification to `--fg` on `--bg`/`--card-bg`. Flag the border as an Open Question.

### Focus ring + htmx-request opacity composition (SC 1.4.11)

CSS `opacity: 0.6` applies to the entire element stacking context including its `outline`.
When a button has both `:focus-visible` and `.htmx-request`, the focus ring is rendered at
0.6 opacity:

- `--accent #58a6ff` ring at 0.6 opacity on `--card-bg #161b22`: **3.28:1** — PASSES SC 1.4.11
- `--danger #a3271a` ring at 0.6 opacity on `--card-bg #161b22`: **2.57:1** — FAILS SC 1.4.11

The danger-button focus ring under `opacity: 0.6` falls below the 3:1 threshold. This state
(focused + in-flight) occurs when a keyboard user presses Enter on a danger button. **Fix:**
add `button.danger.htmx-request:focus-visible { outline-width: 3px; }` to compensate for
the opacity reduction (a wider ring at 0.6 opacity is visually equivalent to a thinner ring
at full opacity). This is a 1-line addition.

### htmx 2.0.10 — `hx-disabled-elt` semantics

From htmx docs and confirmed by github.com/bigskysoftware/htmx issues:
- `hx-disabled-elt="this"` adds the HTML `disabled` attribute to the element itself.
- When applied to a `<button>`, `disabled` is a standard HTML attribute — the button becomes
  keyboard-non-activatable and Enter-non-fireable.
- When applied to a `<form>`, `disabled` is **non-standard** — browsers do NOT propagate it
  to child inputs/buttons; no browser-enforced double-fire protection.
- **Correct pattern for `<form>` elements:** `hx-disabled-elt="find button"` — targets the
  first descendant button, which htmx marks `disabled` for the request duration.
- **Known issue (htmx 2.0.0+):** `hx-disabled-elt` in combination with `hx-trigger="load"`
  does not re-enable the element; do not use on the ingest-status polling `<div>`.
- `htmx-request` is auto-applied to the triggering element (the `<form>` or `<button>`),
  removed when the request completes. htmx 2.0.10 applies it to the triggering element,
  not the target.

### htmx CSS class lifecycle

- `htmx-request`: applied to the triggering element at request start, removed at completion.
- `htmx-swapping`: applied to the target before swap.
- `htmx-settling`: applied to the target after swap, removed after settle delay.
- `htmx-added`: applied to newly inserted content before settlement.

For m3, only `htmx-request` is relevant. The spinner selector `button.htmx-request` will
target the `<button type="submit">` inside a form IF that button was the click target, but
for `<form>` elements where the user presses Enter, the form itself receives `htmx-request`.
The CSS selector should be `form.htmx-request button, button.htmx-request` or (simpler)
`.htmx-request button, .htmx-request` — but this has specificity implications.

**Simplest correct approach:** Use `.htmx-request button, button.htmx-request` for the
spinner `::after`. For the opacity/pointer-events, target both form and button:
`form.htmx-request button, button.htmx-request`.

---

## Recommendation

**Implement m3 as a single CSS pass to `frontend/static/app.css` + 8 attribute additions
across `frontend/templates/index.html` and `notebook_detail.html`.**

Specific implementation guidance:

1. **Dark mode block:** Add `@media (prefers-color-scheme: dark) { :root { … } }` with
   exactly the 8 tokens specified in the AC. Use `--border: #484f58` instead of `#30363d`
   as a pragmatic improvement (still Primer-adjacent, avoids the egregious 1.55:1 contrast
   the adversary will flag, and is within the v0 spirit). Mark the status-pill modifiers and
   `th { background: #f0f0f0 }` as explicitly descoped to v1 with a code comment.

2. **htmx-request block:** Use selectors that correctly handle BOTH form-triggered and
   button-triggered requests:
   - `form.htmx-request button, button.htmx-request { opacity: 0.6; pointer-events: none; cursor: wait; }` (unconditional)
   - The `::after` spinner: `form.htmx-request button::after, button.htmx-request::after { … }`
   - Inside `@media (prefers-reduced-motion: no-preference)`: `form.htmx-request button::after, button.htmx-request::after { animation: spin 0.6s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }`
   - Add `button.danger.htmx-request:focus-visible { outline-width: 3px; }` to compensate
     for the 0.6 opacity focus-ring degradation on danger buttons (2.57:1 → visually recoverable).

3. **`hx-disabled-elt` attribute additions:**
   - On the 5 `<form>` elements (Create, Rename, Add paper, Upload, Ingest): use
     `hx-disabled-elt="find button"` (NOT `"this"` — see critical finding above).
   - On the 3 standalone `<button>` elements (Remove notebook in loop, Delete notebook on
     detail, Remove paper in loop): use `hx-disabled-elt="this"`.

4. **Test file:** `tests/test_ui_m3_dark_and_htmx_feedback.py` should follow the m2 test
   patterns (read `APP_CSS_NO_COMMENTS` for structural assertions, use regex block-scoping
   rather than simple `in` checks). Assert:
   - Dark mode block exists and redeclares all 8 tokens.
   - `htmx-request` opacity/pointer-events/cursor rules exist.
   - Spinner `::after` rule exists.
   - Spin keyframe is INSIDE `prefers-reduced-motion: no-preference`.
   - All 5 `<form>` elements have `hx-disabled-elt="find button"`.
   - All 3 standalone `<button>` htmx triggers have `hx-disabled-elt="this"`.

---

## Open questions

**Resolved by this research (no open questions remain — implementation can proceed on the
above recommendation), with the following noted decisions the implementer must make:**

**(a) Status badge pill colors on dark card-bg.** Per the v0/v1 split confirmed in the
milestone brief and in `plans/ui-attractive-polish-roadmap.md`, the `.status-badge--*`
modifiers stay light-mode in v0. The pills will have their own internal contrast (light bg,
dark text) so they meet SC 1.4.3 internally. Their contrast AGAINST the dark `--card-bg` is
not a WCAG violation (SC 1.4.11 non-text contrast applies to the pill's border against the
card, and `.status-badge--down` uses `var(--danger)` border which at `#a3271a` on `#161b22`
is marginal). Accept for v0.

**(b) Table header `th { background: #f0f0f0 }` (app.css:104).** Confirmed descoped to v1
per the challenger UPL-8 v0/v1 split. The hardcoded `#f0f0f0` will show as a light header
stripe in dark mode — jarring but a11y-safe (light bg with dark text keeps its own contrast).
Add a CSS comment marking it as "table-header dark surface descoped to v1".

**(c) `hx-disabled-elt="this"` vs `"find button"` on `<form>` elements.** Resolved above:
use `"find button"` for all 5 `<form>` elements. The milestone brief's wording ("add
`hx-disabled-elt=\"this\"` to the 7 htmx-bound `<form>` elements") is imprecise — the
correct value for form elements is `"find button"`. The brief's AC goal (keyboard a11y
parity, prevent double-fire) is achieved with `"find button"`.

**(d) `button.danger:focus-visible` + `.htmx-request` composition.** Partially resolved:
the focus ring drops to 2.57:1 at 0.6 opacity. Fix with `button.danger.htmx-request:focus-visible { outline-width: 3px; }` (1 LOC addition). Implement this proactively — it is the kind of
finding the adversary critic will flag as MEDIUM or HIGH.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| `git push` | `origin/main` | Land feat + rect + chore triple per CLAUDE.md §4.3 three-commit pattern. Per-event authorization required (CLAUDE.md §4.4). |

No GitHub issue creation, no infra mutation, no third-party API calls.
