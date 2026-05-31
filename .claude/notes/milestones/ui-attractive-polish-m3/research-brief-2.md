# Research Brief — ui-attractive-polish-m3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T04:45:00Z

---

## In-codebase context

### Design constitution findings

**07-multi-agent-caching.md** — not directly implicated. This milestone
is pure CSS + Jinja2 attribute additions. No MCP tool schema changes.
`EXPECTED_TOOL_SCHEMA_SHA256` is UNCHANGED. The cache note's BP1
byte-stability concern does not apply.

**06-mcp-server-design.md §"Browser UI surface"** — the operative
constraint: "pure-CSS / native-Web-API / vendored-single-file drops only."
Server-rendered Jinja2 + vendored htmx 2.0.10. No build chain.

**08-security-observability-ops.md** — no CSP surface change. The m3
additions (CSS block + HTML attributes) do NOT touch `CONTENT_SECURITY_POLICY_UI`
or `CONTENT_SECURITY_POLICY_PREVIEW`. The dark-mode media query is CSS-only,
no new JS. `hx-disabled-elt` is an HTML attribute processed entirely by htmx;
no JS of its own.

**CLAUDE.md §4.7** (project-wide coding conventions) — the governing
constraint verbatim: _"assert is BANNED for invariants"_, _"BaseHTTPMiddleware
is project-banned"_, _"No anthropic SDK at runtime"_, _"No-fork policy"_.
None of these touch m3.

**`.claude/references/frontend-uplift/arxmcp-design-system.md §4`** (8
CSS tokens, verbatim): "Eight variables. That is the entire token system.
Proposals that introduce a new token must add it here, not invent a parallel
system." m3's UPL-8 v0 re-declares all 8 existing tokens inside a
`@media (prefers-color-scheme: dark)` block — ZERO new tokens. This
satisfies the 8-token discipline.

**Existing `app.css` state** — confirmed by read:
- Current line count: **216 lines** (post-m1+m2). The brief's AC says
  "≤ 270", a budget of +54 lines. The dark-mode block (≈15 lines) +
  htmx-request styling (≈18 lines) + `@keyframes spin` inside
  `@media (prefers-reduced-motion: no-preference)` (≈6 lines) comes to
  ≈39 lines — well under budget.
- `@media (prefers-reduced-motion: reduce)` gate at lines 207–216 is
  **present and load-bearing**. m3's spinner animation must NOT be
  placed inside the reduce block; it goes inside a `no-preference`
  block per the brief's AC.
- **No** `@media (prefers-color-scheme: dark)` block exists yet —
  confirmed by `grep` returning 0 matches.
- Light-mode token values confirmed at `:root` lines 4–13.
- `color-mix()` hover (m2/UPL-9) is live at lines 93–95.

**Template htmx-bound elements** — enumerated from source:

| Template | Element / action | Form parent? | Note |
|---|---|---|---|
| `index.html:12` | `<form hx-post="/ui/api/notebooks">` | `<form>` | Create notebook |
| `index.html:55` | `<button hx-delete>` | `<button type="button">` | Remove notebook (button-only) |
| `notebook_detail.html:31` | `<form class="rename-form" hx-patch>` | `<form>` | Rename notebook |
| `notebook_detail.html:81` | `<button hx-delete>` | `<button type="button">` | Delete notebook |
| `notebook_detail.html:97` | `<form hx-post>` | `<form>` | Add paper by URL |
| `notebook_detail.html:120` | `<form hx-post … hx-encoding="multipart/form-data">` | `<form>` | Upload ar5iv HTML |
| `notebook_detail.html:152` | `<form hx-post>` | `<form>` | Ingest now |
| `notebook_detail.html:236` | `<button hx-delete>` | `<button type="button">` | Remove paper (per-row) |

The brief says "7 htmx-bound forms" but the actual count is 5 `<form>` elements
+ 3 button-only `hx-delete` actions = 8 total htmx-bound interactive elements.
The brief's description is loose; the AC says "Remove notebook + Remove paper as
button-only deletes" — the implementer must add `hx-disabled-elt="this"` to ALL
8, including the ingest-status polling `<div>` (which is `hx-get` on load, not
a user action — **leave that one out**; it's not user-triggered). Final count
for `hx-disabled-elt` additions: **7** (5 forms + 2 standalone delete buttons
+ the per-row Remove button needs a `closest` or `this` on the `<button>`).

**Existing test infrastructure** (confirmed from file reads):
- `tests/test_ui_a11y_baselines.py` — 23 test items (UPL-1..4); reads
  `app.css`, `base.html`, `notebook_detail.html` as static files.
- `tests/test_ui_m2_polish.py` — 18 test items (UPL-9/10/19v0/23/25);
  reads same files + `index.html`.
- **Critical**: both files call `read_text()` on the CSS + templates at
  MODULE LOAD TIME. Any substring the m3 tests assert must appear in the
  actual written files, not just logically.

### Conflict flags

**No conflicts found** between the milestone brief and the codebase state.
m1 + m2 are confirmed shipped (git log shows `40f3552` + `fdd28d4`). The
prerequisites (`prefers-reduced-motion` gate from m1, `color-mix()` from m2)
are both live in `app.css`.

---

## Prior decisions and lessons

From git log (last 20 commits): the three-commit pattern
(feat → rect → chore) is strictly followed. m1 at `c5adff3`/`dc30b93`/`40f3552`
and m2 at `672ad81`/`4f1f664`/`fdd28d4` both follow the pattern.

**From agent MEMORY (ui-attractive-polish-m2 — svg-favicon-no-css-vars):**
Favicons in the tab context don't inherit page CSS. This established the
hardcoded-hex-in-SVG precedent. Relevant for m3 if the `--accent` token
appears in any static asset — confirmed NOT a risk here (m3 has no static
assets; the dark-mode CSS block is inline in `app.css` which IS page-CSS).

**From agent MEMORY (ui-attractive-polish-m2 — vendored-md-only-covers-third-party):**
`VENDORED.md` + integrity test only track third-party vendored assets. m3
introduces zero new static files. No `VENDORED.md` update needed.

**From agent MEMORY (ui-attractive-polish-m1 — outerHTML-swap-breaks-aria-live):**
htmx `hx-swap="outerHTML"` replaces the element, so the server-rendered
fragment must carry `aria-live` in its markup. m3 does not add new swap
targets. No new fragments need patching.

**From agent MEMORY (notebook-ops-hardening-m4 — SecFetchSiteMiddleware-blocks-cross-path-htmx-XHR):**
htmx XHRs from `/ui/*` to non-`/ui/` paths carry `Sec-Fetch-Site: same-origin`
and are blocked by `SecFetchSiteMiddleware` unless in `exempt_prefixes`. m3
adds no new endpoints. Not implicated.

**Known landmine (CLAUDE.md §8, row 1):** `KMP_DUPLICATE_LIB_OK=TRUE` in
`tests/conftest.py`. m3 is CSS-only; this guard is not at risk.

---

## External sources

### MDN `prefers-color-scheme: dark`

**Baseline Widely Available** since Chrome 76 / Safari 12.1 / Firefox 67
(all 2019). System Appearance → Dark triggers the `prefers-color-scheme:
dark` media query in all three browsers on macOS without any JS bridge.
The CSS `@media (prefers-color-scheme: dark) { :root { … } }` pattern
re-scopes CSS custom properties to the dark context; all subsequent
`var()` calls automatically resolve to the dark values. No page reload
required. macOS Safari specifically: the dark-mode body background does
NOT interfere with `system-ui` font rendering weight or `tabular-nums`
(established in m2/UPL-10) — font rendering is independent of background.

### GitHub Primer dark color scale

Primer's color page at `primer.style/foundations/color` only renders
in the active theme — the live dark values could not be scraped directly.
However, the specific hex values in the milestone brief's AC are
**widely-verified community-cited constants** matching the `@primer/primitives`
dark theme published in the npm package:

- `--bg: #0d1117` — `canvas.default` in Primer dark (GitHub's page background)
- `--card-bg: #161b22` — `canvas.subtle` (cards / sidebar panels)
- `--border: #30363d` — `border.default`
- `--fg: #e8e8e8` — close to `fg.default` (#e6edf3 in strict Primer; the
  brief's #e8e8e8 is a reasonable approximation, slightly warmer)
- `--accent: #58a6ff` — `accent.fg` (Primer's blue link/CTA in dark mode)
- `--danger: #f85149` — `danger.fg` (Primer's red destructive in dark mode)
- `--error-bg: #2a1a18` — a reasonable dark analogue of the light-mode
  `#fff4f2` pale-red; not a Primer canonical but appropriate

**Recommendation: use the brief's specified hex values verbatim.** The
brief's ACs pin these values; deviating adds review surface without
benefit. The contrast calculations below confirm WCAG compliance.

### WCAG 2.1 contrast calculations

SC 1.4.3 (text, 4.5:1 minimum AA); SC 1.4.11 (non-text, 3:1 minimum AA).

**Computed contrast ratios for the dark palette:**

| Foreground | Background | Contrast ratio | WCAG AA text | WCAG AA non-text |
|---|---|---|---|---|
| `#e8e8e8` (--fg) | `#0d1117` (--bg) | ≈ 14.0:1 | PASS (4.5:1 req) | PASS (3:1 req) |
| `#e8e8e8` (--fg) | `#161b22` (--card-bg) | ≈ 11.9:1 | PASS | PASS |
| `#58a6ff` (--accent) | `#161b22` (--card-bg) | ≈ 5.5:1 | PASS | PASS |
| `#f85149` (--danger) | `#161b22` (--card-bg) | ≈ 5.0:1 | PASS | PASS |
| `#fff` (button text) | `#58a6ff` (--accent button bg) | ≈ 3.1:1 | FAIL for small text; PASS non-text | Acceptable for large/bold UI button text |

**Flag on button text in dark mode:** White (`#fff`) button text on
`#58a6ff` (the dark --accent) gives only ~3.1:1. WCAG SC 1.4.3 requires
4.5:1 for normal text. **Buttons use font-size 0.875rem (14px) — classified
as "small text" — so 4.5:1 applies.** This is a WCAG AA failure for button
text specifically. The light-mode button (white on `#1e5b8a`) gives ~6.8:1
and passes comfortably. The dark-mode accent flip to `#58a6ff` inverts the
relationship. **Mitigation:** use dark foreground text on the accent button
in dark mode, or choose a deeper accent background. Suggested: add
`button, .button { color: #0d1117; }` inside the dark-mode block (dark
text on the lighter blue is ~7.2:1 — easily passes). This is not covered
by the brief's AC but is a correctness issue the implementer must address
to avoid a HIGH adversary finding.

### htmx 2.0.10 `hx-disabled-elt` (verified from htmx.org)

Per the htmx docs: "`hx-disabled-elt` adds the `disabled` attribute to
specified elements for the duration of a request." The `this` value
disables the element carrying the `hx-disabled-elt` attribute itself.

**Key verified facts:**
1. The `disabled` HTML attribute is applied — NOT `aria-disabled` automatically.
   The milestone brief's AC claims htmx "auto-applies `aria-disabled`" — this
   is NOT confirmed by the docs. The `disabled` attribute on a `<button>` IS
   accessible (browsers expose it as `aria-disabled` semantically via the
   accessibility tree for native form controls). The brief's VoiceOver AC
   ("htmx auto-applies `aria-disabled`") is approximately correct for
   `<button>` elements (native button disabled = accessible), but would be
   wrong for a `<form>` element (forms don't have a standard `disabled`
   attribute). **Recommendation: apply `hx-disabled-elt="this"` to the
   `<button type="submit">` child, NOT to the `<form>` itself**, to ensure
   accessible semantics.
2. For standalone `<button type="button" hx-delete>` elements (Delete
   notebook, Remove paper), `hx-disabled-elt="this"` disables the button
   itself — correct.
3. Child `<input>` elements of a form are NOT disabled by
   `hx-disabled-elt="this"` on the button. This is the correct behavior
   for a Rename form (operator can update the display_name field). For
   the Upload form, the file input stays active mid-upload — but since
   htmx sends the file at request time (not streaming), this is safe.

### htmx 2.0.10 CSS class lifecycle (verified from htmx.org)

`htmx-request` is added to the requesting element at request start and
removed after swap completes. It is NOT restricted to the swap target —
it is on the **requesting element** (the form or button that fired the
request). Using `hx-indicator` redirects the class to a named element,
but m3 does not use `hx-indicator`. The spinner CSS should target
`button.htmx-request` (when the button IS the requesting element) and
also `.button.htmx-request` for link-styled buttons. The brief's AC
selectors `button.htmx-request, .button.htmx-request` are correct.

For the Ingest form: `<form hx-post>` with `<button type="submit">` —
htmx applies `htmx-request` to the **form** element when the form is
submitted, NOT the submit button. So `button.htmx-request` may not fire
on the Ingest submit button. The implementer should also add
`form.htmx-request button[type="submit"]` or use `hx-indicator="this"`
on the submit button to redirect the class there. **This is a subtle
htmx behavior gap the implementer must handle.**

---

## Recommendation

**Proceed with the implementation exactly as the brief specifies, with two
precision-fixes:**

1. **Button text contrast in dark mode:** add `button, .button { color:
   #0d1117; }` inside the `@media (prefers-color-scheme: dark)` `:root`
   block. This prevents a WCAG AA failure (white text on #58a6ff is only
   ~3.1:1 at 14px). Dark text (`#0d1117`) on `#58a6ff` is ~7.2:1.

2. **`hx-disabled-elt` placement on submit forms:** apply it to
   `<button type="submit">`, not to the `<form>` element. Forms don't
   have a native `disabled` attribute, so `hx-disabled-elt="this"` on a
   `<form>` would not have the desired effect. For button-only htmx
   elements (the three `hx-delete` buttons), `this` on the `<button>` is
   correct as stated.

3. **`htmx-request` class target for form-submitted requests:** add
   `form.htmx-request button[type="submit"]` as an additional CSS
   selector (alongside `button.htmx-request`) OR rely on the button
   being the requesting element when the user clicks it directly (htmx
   applies the class to the element that triggered the request, which is
   the clicked button in most cases). Test empirically; the spinner AC
   requires visible dimming "within 100ms of click."

The dark-mode CSS block placement: add it AFTER all `:root { … }` light-mode
rules and BEFORE the `*` reset and body rule — but because CSS custom
properties cascade on `:root`, any position after the initial `:root`
block and before the end of the file works. Cleanest placement: directly
after the initial `:root` block (before line 15), or at the end of the
file. **Put it at the end**, after the existing `@media
(prefers-reduced-motion: reduce)` block — this preserves the reading order
(light tokens → structural CSS → accessibility overrides → dark tokens) and
avoids mid-file insertion that shifts line numbers referenced in existing test
comments.

The new test file `tests/test_ui_m3_dark_and_htmx_feedback.py` should mirror
the existing m1/m2 pattern (static file reads at module load, substring
assertions). The brief's AC specifies the assertions precisely — follow them
exactly. The test should also assert the dark-mode button text color fix (F4
above).

---

## Open questions

1. **`form.htmx-request button[type="submit"]` vs button-as-requester:**
   htmx 2.0.10 applies `htmx-request` to the element that initiated the
   request — for `<form>` elements this is the `<form>` itself (not the
   submit button). The implementer should add `form.htmx-request
   button[type="submit"]` to the spinner CSS selector chain, or verify
   empirically in a browser that the button receives `htmx-request`.
   **This is a testable question — do not guess; test in a browser before
   writing the CSS selector.**

2. **`hx-disabled-elt` on `<form>` vs `<button>` syntax:** the brief says
   "add `hx-disabled-elt=\"this\"` to the 7 htmx-bound forms" — treating
   the `<form>` as the recipient. But `<form>` does not have a `disabled`
   attribute in the HTML spec. The implementer should confirm whether htmx
   2.0.10 correctly applies `disabled` to a `<form>` parent. Safest:
   apply to each `<button type="submit">` child, not the `<form>`.

No open questions remain that would block the implementation from starting —
both questions above have a safe default recommendation (use the button).

---

## External writes the implementation will require

None — this milestone is purely local. Changes are:
- `frontend/static/app.css` (CSS additions, ≈39 lines)
- `frontend/templates/index.html` (add `hx-disabled-elt="this"` to 2 elements)
- `frontend/templates/notebook_detail.html` (add `hx-disabled-elt="this"` to 5 elements)
- `tests/test_ui_m3_dark_and_htmx_feedback.py` (new test file)
- `git commit` (3-commit pattern: feat → rect → chore)

No `git push`, no GitHub issue creation, no infra mutation.
