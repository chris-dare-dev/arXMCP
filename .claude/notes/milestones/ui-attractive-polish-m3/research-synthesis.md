# Research Synthesis — `ui-attractive-polish-m3`

**Generated:** 2026-05-31T04:55:00Z
**Inputs:**
- `.claude/notes/milestones/ui-attractive-polish-m3/research-brief-1.md` (in-codebase context lens; found `--border #30363d` WCAG failure + danger-ring opacity issue)
- `.claude/notes/milestones/ui-attractive-polish-m3/research-brief-2.md` (external sources + failure-mode lens; found button-text WCAG failure on dark `--accent`)
- Roadmap: `plans/ui-attractive-polish-roadmap.md` § `### ui-attractive-polish-m3` (uncommitted m3 section from the recent `/roadmap` re-invocation)
- Post-m2 state: m1 (`c5adff3`) + m2 (`672ad81`+`4f1f664`+`fdd28d4`) shipped on `origin/main`. m1+m2 regression tests at `tests/test_ui_a11y_baselines.py` (23) + `tests/test_ui_m2_polish.py` (18) = 41 must continue passing.

---

## 1. What ships

Two e3 polish items bundled into one CSS pass + 8 template attribute additions:

| UPL | What | Where | Cost |
|---|---|---|---|
| **UPL-8 v0** | `@media (prefers-color-scheme: dark) { :root { … } }` block re-declaring all 8 base tokens with GitHub-Primer-anchored dark values | `frontend/static/app.css` (~18 LOC) | S |
| **UPL-11** | CSS rules for htmx's auto-applied `htmx-request` class (button dim + spinner, spin animation gated by `prefers-reduced-motion: no-preference`) + `hx-disabled-elt` attribute additions on 8 htmx-bound elements | `frontend/static/app.css` (~22 LOC) + `frontend/templates/{index,notebook_detail}.html` (8 attr additions) | S |

Total: ~40 LOC CSS + 8 attribute additions + 1 new test file (~20 tests).
Complexity: **M** (CSS straightforward; manual cross-browser theme verification + VoiceOver smoke-test are the largest time slices).

---

## 2. Load-bearing corrections (NOT in the original roadmap AC)

Both researchers found correctness issues neither the original uplift synthesis nor the m3 roadmap section caught. The implementer MUST adopt these resolutions or the adversary critic will flag them as HIGH:

### C1. `--border #30363d` fails WCAG SC 1.4.11 (3:1 non-text contrast) — researcher-1

Calculated contrast for the GitHub-Primer-canonical dark border:
- `--border #30363d` on `--bg #0d1117` → **1.55:1** (fails 3:1)
- `--border #30363d` on `--card-bg #161b22` → **1.42:1** (fails 3:1)

The `--border` token applies to `.card`, input fields, table cells, and `.status-badge`
— all UI component visual indicators where SC 1.4.11 applies.

**Resolution: use `--border: #6e7681`** (4.12:1 on `--bg`; passes 3:1 with margin). This
deviates slightly from canonical Primer (`#30363d`) but Primer itself uses different tokens
for decorative-separator-borders vs interactive-element-borders; arXMCP has only one
`--border` token, so it must clear the stricter non-text threshold. `#6e7681` is still on
the Primer grey scale, just one stop lighter.

### C2. White button text on `#58a6ff` (`--accent` in dark) fails WCAG SC 1.4.3 (4.5:1 text contrast) — researcher-2

Calculated contrast for the existing `button { color: #fff; background: var(--accent); }`
rule, in dark mode:
- `#fff` text on `#58a6ff` → **~3.1:1** (fails 4.5:1 at 14px / "small text" classification)

In light mode (`--accent #1e5b8a`), `#fff` text → ~6.8:1 (passes comfortably). The dark-mode
flip inverts the relationship.

**Resolution: add `button, .button { color: #0d1117; }` inside the `@media (prefers-color-scheme:
dark)` `:root` block.** Dark text (`#0d1117`) on `#58a6ff` → **~7.2:1** (passes
comfortably).

### C3. `--danger`-button focus ring at 0.6 opacity falls below WCAG SC 1.4.11 — researcher-1

When a keyboard user activates a `<button class="danger">` via Enter, the button gains
BOTH `:focus-visible` (m1 — `outline: 2px solid var(--danger); outline-offset: 3px`)
AND `.htmx-request` (m3 — `opacity: 0.6`). The opacity applies to the entire stacking
context including the outline:
- `--danger` ring at 0.6 opacity on `--card-bg` (light or dark) → **~2.57:1** (fails 3:1)

**Resolution: add `button.danger.htmx-request:focus-visible { outline-width: 3px; }`.**
A wider ring at 0.6 opacity is visually equivalent to a thinner ring at full opacity. 1 LOC.

### C4. `hx-disabled-elt="this"` on `<form>` is semantically wrong — BOTH researchers

The HTML `disabled` attribute is **non-standard on `<form>` elements** — browsers do NOT
propagate it to child inputs/buttons. Per htmx 2.0.10 docs, `hx-disabled-elt="this"` adds
the `disabled` HTML attribute to the named element only. On a `<form>`, this has no
browser-enforced effect on keyboard Enter double-fire.

**Resolution:**
- **For the 5 `<form>` elements:** apply `hx-disabled-elt="find button"` (NOT `"this"`).
  This targets the first descendant button — the submit button — which htmx marks `disabled`
  for the request duration. Native button-disabled IS accessibility-tree-correct and
  Enter-non-fireable.
- **For the 3 standalone `<button>` elements** (Remove notebook in `index.html`,
  Delete notebook in `notebook_detail.html`, Remove paper in `notebook_detail.html`):
  apply `hx-disabled-elt="this"`. Button IS the htmx requester; `this` is correct.

### C5. htmx-request CSS selectors for form-submitted requests — researcher-2

htmx applies `htmx-request` to the element carrying the `hx-*` attribute — for a
`<form hx-post>`, that's the FORM, NOT the submit button. So a bare `button.htmx-request`
selector won't dim the submit button when the user submits a form.

**Resolution: combined selector chain** —
`form.htmx-request button[type="submit"], button.htmx-request, .button.htmx-request`
— covers both form-triggered (form has class, descendant button matches) and
button-triggered (button has class directly) cases.

---

## 3. Concrete implementation sketches

### Dark mode block (UPL-8 v0 + C1 + C2)

Append at the END of `frontend/static/app.css` (after the `prefers-reduced-motion` block,
per researcher-2's placement recommendation):

```css
/* ui-attractive-polish-m3 (UPL-8 v0): @media prefers-color-scheme: dark
   re-declares the 8 base tokens with GitHub-Primer-anchored values. The
   .status-badge--{ok,warn,ops-warn,down} hardcoded colors (app.css:149-152)
   and the th { background: #f0f0f0 } hardcoded table-header (app.css:104)
   are explicitly DESCOPED to v1 per the challenger's UPL-8 v0/v1 split —
   they stay light-mode, internally consistent (light bg + dark text) but
   contrast-jarring against a dark card. Acceptable for v0. */
@media (prefers-color-scheme: dark) {
  :root {
    --fg: #e8e8e8;        /* ~14:1 on --bg, ~12:1 on --card-bg */
    --bg: #0d1117;        /* Primer canvas.default */
    --card-bg: #161b22;   /* Primer canvas.subtle */
    --border: #6e7681;    /* C1: Primer #30363d fails SC 1.4.11 (1.55:1);
                             #6e7681 passes (4.12:1). One stop lighter
                             on the Primer grey scale. */
    --accent: #58a6ff;    /* Primer accent.fg */
    --danger: #f85149;    /* Primer danger.fg */
    --error-bg: #2a1a18;  /* Dark analogue of light #fff4f2 */
    /* --mono unchanged */
  }

  /* C2: White button text on #58a6ff gives only ~3.1:1 — fails SC 1.4.3
     for 14px text. Dark text on #58a6ff gives ~7.2:1. Restore contrast. */
  button, .button { color: #0d1117; }
}
```

### htmx-request loading-state CSS (UPL-11 + C3 + C5)

Append after the dark-mode block:

```css
/* ui-attractive-polish-m3 (UPL-11): htmx auto-applies .htmx-request to the
   element with the hx-* attribute during the request lifecycle. For form-
   triggered requests the FORM gets the class; for button-triggered requests
   the BUTTON gets it. Selector chain (C5) covers both: form-descendant
   submit button OR direct button-as-requester. Opacity/cursor are UNCONDITIONAL
   (signal, not motion — per challenger m1 UPL-11 finding); only the spin
   animation is gated by prefers-reduced-motion: no-preference. */
form.htmx-request button[type="submit"],
button.htmx-request,
.button.htmx-request {
  opacity: 0.6;
  pointer-events: none;
  cursor: wait;
}

/* C3: --danger focus ring at 0.6 opacity (mid-htmx-request) on --card-bg
   falls to ~2.57:1 — fails SC 1.4.11 3:1. Widening the ring to 3px at the
   reduced opacity visually compensates (preserves perceptible focus). */
button.danger.htmx-request:focus-visible { outline-width: 3px; }

@media (prefers-reduced-motion: no-preference) {
  form.htmx-request button[type="submit"]::after,
  button.htmx-request::after,
  .button.htmx-request::after {
    content: "";
    display: inline-block;
    width: 0.8em;
    height: 0.8em;
    margin-left: 0.5em;
    border: 2px solid currentColor;
    border-right-color: transparent;
    border-radius: 50%;
    vertical-align: middle;
    animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
}
```

### `hx-disabled-elt` attribute additions (UPL-11 part 2, C4-corrected)

Per the C4 resolution:

| # | File | Line | Element | Attribute |
|---|---|---|---|---|
| 1 | `index.html:~12` | `<form hx-post=...>` Create notebook | `hx-disabled-elt="find button"` |
| 2 | `index.html:~55` | `<button hx-delete>` Remove notebook (per-row) | `hx-disabled-elt="this"` |
| 3 | `notebook_detail.html:~31` | `<form hx-patch=...>` Rename | `hx-disabled-elt="find button"` |
| 4 | `notebook_detail.html:~81` | `<button hx-delete>` Delete notebook | `hx-disabled-elt="this"` |
| 5 | `notebook_detail.html:~97` | `<form hx-post=...>` Add paper by URL | `hx-disabled-elt="find button"` |
| 6 | `notebook_detail.html:~120` | `<form hx-post=...>` Upload ar5iv HTML | `hx-disabled-elt="find button"` |
| 7 | `notebook_detail.html:~152` | `<form hx-post=...>` Ingest now | `hx-disabled-elt="find button"` |
| 8 | `notebook_detail.html:~235` | `<button hx-delete>` Remove paper (per-row) | `hx-disabled-elt="this"` |

**Total: 8 attribute additions** (5 forms with `find button`, 3 standalone buttons with
`this`). The roadmap brief's "7 forms" was a loose count — actual is 5 forms + 3 buttons.

**DO NOT** add `hx-disabled-elt` to the `#ingest-status` polling `<div>` — that's
`hx-trigger="load"` / `every 2s`, not user-triggered, and per researcher-1 there's a
known htmx 2.0.0+ issue where `hx-disabled-elt` + `hx-trigger="load"` doesn't re-enable.

---

## 4. Disagreements resolved

### D1: htmx-request CSS selector chain

- **r1**: `form.htmx-request button, button.htmx-request` (any descendant button)
- **r2**: `form.htmx-request button[type="submit"], button.htmx-request` (only submit type)

**Resolution: r2 wins.** The submit button is the operational target; non-submit child
buttons (none currently exist in arXMCP, but defensive) shouldn't get the spinner. Use
r2's selector.

### D2: Dark `--border` value

- **r1**: `#30363d` fails 1.55:1; suggests `#484f58` (2.28:1, still fails) OR `#6e7681` (4.12:1, passes).
- **r2**: silently used `#30363d` from the brief.

**Resolution: use `#6e7681`.** The 4.12:1 contrast is the only one that cleanly passes
SC 1.4.11 with margin. `#484f58` (r1's alternative) still fails. Slight Primer deviation
worth the WCAG compliance.

### D3: htmx-request class on form-submitted requests

- **r1**: htmx applies to "the triggering element (form or button)" — ambiguous.
- **r2**: explicitly verified htmx applies to the form (not the button) for form-submitted requests.

**Resolution: r2's verification is precise.** Use the combined selector chain that handles
both cases (per C5).

### D4: External writes — 1 push vs 0

- **r1**: 1 push to origin/main (CLAUDE.md §4.3 three-commit pattern).
- **r2**: "None — this milestone is purely local" (LOCAL commits, no push needed).

**Resolution: r1 wins.** Same as the m1/m2 rationale — CLAUDE.md §4.4 treats `git push`
as a per-event external write; the pipeline cannot reach `complete` while
`external_writes_required` lists an unauthorized push. Record 1 external write.

---

## 5. Open questions remaining (none blocking)

1. **`hx-disabled-elt="find button"` behavior on Upload form** (research has multipart). Researcher-2 notes that for an in-flight multipart upload, the file input stays active mid-upload — but since htmx sends the file at request time (not streaming), this is safe. The submit button is disabled correctly. **Not blocking.**
2. **Manual cross-browser theme verification** (Chrome + Safari on macOS, Settings → Appearance → Dark/Light toggle) — NOT automatable. Flagged for Chris pre-KR-2; structural assertion (the `@media (prefers-color-scheme: dark)` block exists and redeclares all 8 vars) is automated in the new test file.
3. **Status badge pills + `th` table header in dark mode** are intentionally LEFT light-mode (descoped to a v1 follow-on per challenger). Visually inconsistent but a11y-safe. Add CSS comment explicitly noting the v0/v1 boundary.

---

## 6. Confirmed NOT in scope

- m1 sites (`.skip-link`, `:focus-visible`, `prefers-reduced-motion`, the 5 `aria-live` attributes) — untouched. m1's `var(--accent)`-based focus rings automatically benefit from the dark `--accent` re-binding without code change.
- m2 sites (`tabular-nums`, `.table-wrap`, color-mix hover, footer aria-hidden, favicon SVG) — untouched. The m2 `color-mix(in oklab, var(--accent) 88%, white)` hover may produce a near-white button hover in dark mode (~95% white); accept for v0 — adjusting would require splitting hover-light from hover-dark via another `@media (prefers-color-scheme: dark)` rule, which adds complexity for marginal value.
- Status-pill color remap + `th` dark-header — descoped to v1.
- Tool-schema repinning — m3 touches zero MCP code.
- `htmx.min.js` — unchanged; `EXPECTED_HTMX_SHA256` pin holds.
- New CSP directives — none required (dark mode = inline CSS via existing `'unsafe-inline'`; htmx-request CSS = same; `hx-disabled-elt` = inline attribute).
- New vendored assets / `VENDORED.md` update — none.
- m1 + m2 regression tests — m3 adds new file, modifies zero existing assertions.

---

## 7. Recommended implementation order

1. **Dark mode block** at end of `app.css` (UPL-8 v0 + C1 + C2 corrections inline).
2. **htmx-request loading-state CSS** appended after (UPL-11 + C3 + C5 corrections inline).
3. **`hx-disabled-elt` attribute additions** — 8 changes per C4 resolution (5 forms get `find button`, 3 standalone buttons get `this`).
4. **New regression test file** `tests/test_ui_m3_dark_and_htmx_feedback.py` — patterned after `test_ui_m2_polish.py` (read `APP_CSS_NO_COMMENTS`, regex-scope assertions). Assert:
   - Dark mode block exists + redeclares all 8 vars (use regex-pinned to the `@media (prefers-color-scheme: dark)` block).
   - `--border` uses `#6e7681` (the C1 corrected value).
   - `button, .button { color: #0d1117; }` exists inside the dark block (C2 correction).
   - htmx-request CSS rules exist with the combined selector chain (C5 correction).
   - Spin keyframe is INSIDE `prefers-reduced-motion: no-preference` block (m1 lesson).
   - `button.danger.htmx-request:focus-visible { outline-width: 3px; }` exists (C3 correction).
   - All 5 `<form>` elements have `hx-disabled-elt="find button"`.
   - All 3 standalone `<button>` htmx triggers have `hx-disabled-elt="this"`.
   - Final `app.css` line count ≤ 270 (per the roadmap AC).
5. **`make test` green** via `uv run` (m1's 23 + m2's 18 + m3's new tests all pass).
6. **Implementation-summary** at `.claude/notes/milestones/ui-attractive-polish-m3/implementation-summary.md` records final `wc -l app.css` count + flags the manual cross-browser theme verification as a Chris-only KR-2 gate.

I'll add the m3 tests as a new file `tests/test_ui_m3_dark_and_htmx_feedback.py` (not extending the m1/m2 files — keep per-milestone test files auditable).

---

## 8. External writes

| type | target | why |
|---|---|---|
| `git_push` | `origin/main` | Land the chore(plans) pre-step (the uncommitted roadmap doc m3 edits from `/roadmap`) + feat + rect (if any) + chore triple per CLAUDE.md §4.3. Per-event authorization (CLAUDE.md §4.4) at the Phase-4 external-write gate. |

No GitHub issues, no infra, no third-party API calls. Single push (covering up to 4 commits at gate time).

---

## 9. Orchestrator synthesis note

The two researcher briefs converged on the implementation shape but diverged on which
WCAG failures to flag — researcher-1 found `--border` + danger-focus-ring; researcher-2
found button-text-on-dark-`--accent`. **Three independent WCAG-AA failures total**, all
addressable inline with the implementation. The roadmap's m3 AC did not anticipate any
of them — they're load-bearing corrections that promote the milestone's effective
quality from "v0 ships but a future adversary critique reveals AA gaps" to "v0 ships
WCAG-clean within the v0 scope."

The C4 `hx-disabled-elt` semantic correction (use `find button` on forms, not `this`) was
flagged BY BOTH researchers independently — strongest signal in the brief.

This synthesis is the authoritative implementation contract — the roadmap AC's looser
phrasing ("`hx-disabled-elt=\"this\"` on the 7 forms" + "GitHub-Primer-anchored values"
without specific hexes verified) gives way to the synthesis's precise resolutions
(C1-C5). The implementer should treat this file as the source of truth.

*End of synthesis.*
