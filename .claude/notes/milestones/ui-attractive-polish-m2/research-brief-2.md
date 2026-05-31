# Research Brief — ui-attractive-polish-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T03:35:00Z

## In-codebase context

### m1 baseline — what shipped (commit c5adff3 + dc30b93)

m1 shipped 190 lines in `frontend/static/app.css` (NOT 165 as the roadmap AC
states — the implementation used verbose comment blocks). **The m2 AC line-count
budget `≤ 175` is wrong before m2 even starts.** The actual post-m1 baseline is
190; the correct m2 budget is `≤ 200` (190 + ~10 new CSS lines). The 300-line
KR-5 soft cap is the real guard; there is ample headroom.

**No m2 content was pre-landed in m1.** Grep confirms: zero `tabular-nums`,
zero `table-wrap`, zero `color-mix`, zero favicon in `frontend/`. m2 is a clean
slate relative to m1.

### Zero overlap with m1's additions

m1 added: `.skip-link` (lines 128–154), `:focus-visible` rules (lines 156–172),
`@media (prefers-reduced-motion: reduce)` block (lines 174–190). None of those
touch the button hover, the table layout, the footer, or static assets. No
conflict exists.

### Button hover rule — exact location

`frontend/static/app.css:87` contains verbatim:
```
button:hover, .button:hover { filter: brightness(1.08); }
```
UPL-9 replaces ONLY this line. The preceding `button, .button` rule at lines
75–86 (background, color, border, padding, etc.) is untouched.

### Token system — no `--accent-hover` token exists

The design-system reference (`arxmcp-design-system.md §4`) enumerates exactly
**8 CSS custom properties**: `--fg`, `--bg`, `--card-bg`, `--border`, `--accent`,
`--danger`, `--error-bg`, `--mono`. There is NO `--accent-hover` or any
hover-derived token. The design system doc states: "Proposals that introduce a
new token must add it here, not invent a parallel system." UPL-9 uses
`color-mix()` to derive a hover shade inline — this is the correct approach
(no new token needed). If the implementer wants a named token for the
dark-mode reuse (e3), they MUST add it to the `:root` block AND update the
design system reference.

### Footer `·` separator count — confirmed 5

`base.html` lines 66–68 contain exactly 5 `·` (U+00B7 middle dot) characters:
- Line 66: `Loopback only · same-origin only ·` (2 dots)
- Line 67: `Destructive notebook wipe lives in ... ·` (1 dot)
- Line 68: `<a href="/healthz">/healthz</a> · <a href="/readyz">/readyz</a> ·` (2 dots)

AC says "5 spans" — matches.

### CSP — SVG favicon is already covered

`server/middleware.py` line 174 sets `img-src 'self' data:` in
`CONTENT_SECURITY_POLICY_UI`. `favicon.svg` served from `/ui/static/favicon.svg`
is a same-origin resource; `img-src 'self'` covers it. **No CSP change
required for UPL-25.** This is the F2 failure mode — confirmed NOT a risk.

### `SecFetchSiteMiddleware` — favicon is not an XHR

The favicon is fetched by the browser's resource loader (not an htmx XHR),
carrying `Sec-Fetch-Dest: image` and `Sec-Fetch-Site: none` (browser-initiated,
no document context). `SecFetchSiteMiddleware` exempts requests where
`sec-fetch-site` is absent or `none` — the favicon fetch passes through
unconditionally. No exempt_prefixes change needed.

### `test_vendored_assets_integrity.py` — only pins `htmx.min.js`

The test has a single class `TestVendoredHtmxIntegrity` that asserts existence,
SHA-256 hash, and header comment of `htmx.min.js`. Adding `favicon.svg` does
NOT trigger this test. The AC note ("if the SVG favicon counts as a vendored
asset — likely no") is correct: it is hand-authored, not vendored; no test
update needed. **F6 failure mode is not a risk.**

### `VENDORED.md` — hand-authored assets are not in scope

`frontend/static/VENDORED.md` explicitly states: "`app.css` — Project-authored,
not vendored. No hash recorded." The favicon SVG is similarly hand-authored;
it does not belong in VENDORED.md.

### tables in templates — current locations

- `index.html:37` — `<table class="notebooks">` (to be wrapped in `.table-wrap`)
- `notebook_detail.html:193` — `<table class="papers">` (the actual line after
  reading the current file — the brief cites `:176` which is approximate;
  implementer must grep for the exact line)

### `#papers-tbody` uses `hx-swap="beforeend"` — NOT outerHTML

The papers table body at `notebook_detail.html` already has `aria-live="polite"`
from m1 (UPL-3). The `hx-swap="beforeend"` pattern means the `<tbody>` element
is NOT replaced on upload — `aria-hidden` on footer dots does not interact with
this element. The `table-wrap` div goes around the `<table>` element, not inside
`<tbody>`.

### `app.css:87` `border: none` on buttons

The button rule at line 75 sets `border: none`. UPL-9's suggested
`border-color: color-mix(in oklab, var(--accent) 80%, var(--fg))` would have
no visual effect without first adding `border: 1px solid` to the base rule or
making hover also set border-style. The implementer should either: (a) use ONLY
`background: color-mix(...)` on hover (the AC's "or similar" clause applies),
or (b) also add `border-style: solid; border-width: 1px;` to the base rule.
Option (a) is simpler and lower-risk.

### `dl.meta dd` — the target selector for UPL-10

The AC specifies `time, .status-badge, dl.meta dd, td code { font-variant-numeric:
tabular-nums; }`. Verify `dl.meta dd` includes the `<time>` element inside it
(both `created_at` and `latest_run.finished_at` are in `<time>` wrappers inside
`<dd>` elements) — the `time` selector in the rule already covers those; `dl.meta
dd` covers any non-`<time>` values (e.g. parse_status text).

---

## Prior decisions and lessons

**From MEMORY.md (outerHTML-swap-breaks-aria-live):** m1 established that
`hx-swap="outerHTML"` replaces the element — new server-rendered fragments
must carry `aria-live` in their markup. UPL-23's `<span aria-hidden="true">·</span>`
wrapping is static template change only (no server-side fragment involved) — the
aria-live lesson does not apply here.

**m1 overshoot:** The implementation summary confirms the 190-line overshoot
(target was 165). The m2 AC's `≤ 175` target is stale; implementer should
use `≤ 200` as the real constraint.

**Challenge.md on UPL-19:** verbatim from `challenge.md §4 UPL-19`:
> "v0: ship JUST the `.table-wrap { overflow-x: auto }` wrappers (the actual
> mobile-overflow bug-fix). v1: the `body { max-width: min(95vw, 1400px) }`
> expansion, after verifying on a 27"+ display that long-line readability
> doesn't regress."
This is what the roadmap AC already captures. The `body max-width` expansion is
explicitly descoped.

**Challenge.md on UPL-9 (NONE / clean):** "Native Baseline Widely Available
since 2025-11-09; replaces imprecise `filter: brightness(1.08)`." No objections.
The challenger confirms `color-mix()` is the correct replacement.

**Challenge.md on UPL-25 (NONE / clean):** "Single static asset under
`frontend/static/` is within the no-build-chain envelope."

**No Tool-schema re-pinning needed:** m2 adds no MCP tools. `EXPECTED_TOOL_SCHEMA_SHA256`
is unchanged.

---

## External sources

### `font-variant-numeric: tabular-nums` (MDN verified)
- **Baseline Widely Available** — available across browsers since January 2020.
- CSS property; corresponds to OpenType `tnum` feature.
- **System font caveat:** macOS San Francisco (`-apple-system`) and Segoe UI
  (Windows) are professional fonts that include `tnum`; graceful degradation
  occurs on platforms lacking the feature (numbers just don't align — not a
  broken-UI condition).
- **No `font-feature-settings: "tnum" 1` fallback needed** for this operator-only
  console. The CSS property is the preferred abstraction; `font-feature-settings`
  is the low-level escape hatch and should not be used when the high-level
  property suffices. F3 failure mode: acceptable graceful degradation, not a
  real breakage.

### `color-mix(in oklab, ...)` (MDN verified)
- **Baseline Widely Available since May 2023** (the library-scout brief cited
  2025-11-09; MDN says May 2023 — May 2023 is the Widely Available date, 2025-11
  may refer to `color-mix` being added to Baseline 2023's "Widely Available"
  list after the 30-month window passed).
- `oklab` is the **correct color space for hover derivation** — MDN states:
  "The Oklab (and older Lab) color spaces are appropriate, because they are
  designed to be perceptually uniform." `srgb` produces "poorer results such
  as overly dark or grayish mixes" — avoid for button hover.
- `oklch` is for maximizing chroma in gradients — not needed for a simple
  hover lightening. `oklab` is the right choice.
- F1 failure mode: NOT a risk on any supported browser Chris uses (Chrome on
  macOS, Safari on macOS — both fully support `color-mix(in oklab, ...)`).

### `overflow-x: auto` (MDN verified)
- **Scrollbar only when needed** — correct behavior for mobile fix. The docs
  confirm: `auto` hides scrollbars by default and shows them only when content
  overflows. `scroll` always shows scrollbars (not desired).
- F4 failure mode: `auto` on a wrapper `<div>` creates horizontal scroll only,
  no vertical interaction. Low risk.

### `aria-hidden="true"` on `<span>` (MDN + ARIA spec)
- Correct pattern: screen readers skip the entire wrapped element.
- Multiple adjacent `aria-hidden="true"` spans: no double-skip issue — ATs
  simply move past each hidden span to the next accessible node. The pattern
  `·</span> text <span aria-hidden="true">·</span> text` correctly exposes
  text between separators.
- F7 (test layer) failure mode: checked — `test_ui_a11y_baselines.py` only
  tests UPL-1..4. No test asserts on footer text rendering; F7 is NOT a risk.

### SVG favicon pattern
- Canonical link tag: `<link rel="icon" href="..." type="image/svg+xml">`.
- Browser support: Chrome 80+, Firefox 41+, Safari 9+ (all modern).
- MIME type `image/svg+xml` is the correct hint.
- CSP: `img-src 'self'` in `CONTENT_SECURITY_POLICY_UI` already permits
  same-origin image resources. No CSP widening needed (confirmed in codebase).

---

## Recommendation

**Implement in one commit in this order:** UPL-10 → UPL-19 v0 → UPL-9 →
UPL-23 → UPL-25. Rationale: each item is independent; ordering by file
(app.css, then templates, then templates/head, then static asset) minimizes
context-switching.

**UPL-10:** Add one CSS rule: `time, .status-badge, dl.meta dd, td code { font-variant-numeric: tabular-nums; }`. Place after the `table code` rule (around line 97). No `font-feature-settings` fallback needed.

**UPL-19 v0:** Add `.table-wrap { overflow-x: auto; }` to app.css. In `index.html` wrap `<table class="notebooks">` in `<div class="table-wrap">`. In `notebook_detail.html` wrap `<table class="papers">` in `<div class="table-wrap">`. Do NOT change `body { max-width: 980px }`.

**UPL-9:** Replace `app.css:87` with:
```css
button:hover, .button:hover { background: color-mix(in oklab, var(--accent) 88%, white); }
```
Use ONLY `background` (not `border-color` — buttons have `border: none` in the base rule, so `border-color` has no effect without a border-style). Verify the `color-mix(in oklab, #1e5b8a 88%, white)` computed value meets WCAG AA contrast on `#f8f8f8` (`--bg`).

**UPL-23:** In `base.html`, replace each bare `·` character with `<span aria-hidden="true">·</span>`. Five replacements; all on lines 66–68.

**UPL-25:** Create `frontend/static/favicon.svg` as a 32×32 SVG. Use the `--accent` color value `#1e5b8a` as a fill (SVG cannot use CSS variables in external-file context). Add `<link rel="icon" href="/ui/static/favicon.svg" type="image/svg+xml">` to `<head>` in `base.html`. Do NOT add it to `VENDORED.md` (hand-authored). Do NOT update `tests/test_vendored_assets_integrity.py` (only pins htmx).

**Line count:** Target `≤ 200` (not `≤ 175` which is based on the stale pre-m1 count). Budget: 190 (current) + ~3 (tabular-nums) + ~1 (table-wrap) + ~1 (color-mix hover swap) = ~195. Comfortable.

**F5 (focus+hover combination):** m1's `:focus-visible` ring uses `outline: 2px solid var(--accent)`. UPL-9's hover sets `background: color-mix(...)`. The outline appears outside the button border (offset: 2px) so there is no visual overlap with the background change. The combination is visually clean — no mitigation needed.

---

## Open questions

**1. Exact SVG favicon design.** The AC says "implementer's choice." The
simplest correct implementation is a 32×32 SVG `<rect>` filled `#1e5b8a`
with a white `arX` text label. This is acceptable; no further specification
needed.

**2. Post-m1 app.css line count drift.** The m2 AC states `≤ 175` but the
post-m1 baseline is 190. The implementer should update the line-count AC
inline to `≤ 200` and note the correction in the commit body. This is a
doc-drift fix, not a blocker.

Other than these two non-blocking items, implementation can proceed on the
above recommendation.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `git_push` | `origin/main` | Land the feat+rect+chore commit triple per CLAUDE.md §4.3 |
