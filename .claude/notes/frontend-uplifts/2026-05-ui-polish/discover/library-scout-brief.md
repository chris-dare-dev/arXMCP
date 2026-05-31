# Library-scout brief — 2026-05-ui-polish

**Scout role:** LIBRARY SCOUT for arXMCP frontend-uplift `2026-05-ui-polish`.
**Date:** 2026-05-30.
**Scope:** vendor-able modern frontend techniques the operator console at
`/ui/` could adopt without violating the no-build-chain lock
(CLAUDE.md §4.7). Only **pure-CSS / native Web APIs**, **htmx extensions
shipped as single-file drops**, and **single-file vanilla-JS micro-libs**.

The user-supplied uplift brief steers the bias explicitly:

> Make arXMCP's /ui/ operator console more attractive and less bare-bones.
> The current surface is 3 Jinja2 templates + a single 126-line CSS file
> + vendored htmx 2.0.10, light-mode-fixed, with 8 CSS variables and zero
> prefers-reduced-motion / focus-visible / aria-live / skip-link discipline.
> Bias toward foundational a11y baselines first […], then visual polish via
> pure-CSS APIs / native Web APIs / vendored single-file drops only.

That bias is honored below — the **C-tier (a11y baselines)** candidates land
at zero new JS and zero new vendor bytes, and any decorative motion is gated
behind them.

---

## 1. TL;DR

Top-3 techniques worth adopting (ranked by leverage per byte):

1. **The a11y-baseline CSS triad** — `prefers-reduced-motion` gate +
   `:focus-visible` outline + `aria-live` region on htmx swap targets +
   skip-link. **Zero new JS, zero vendored bytes** — pure CSS plus three
   one-line template edits. Closes 4 of `arxmcp-design-system.md` §7's
   underdeveloped items in one milestone, and is a prerequisite for every
   other motion candidate below (per `motion-vocabulary.md` MOT-NO-5).
2. **`@media (prefers-color-scheme: dark)` token block + `color-mix()`** —
   native dark-mode without inventing a parallel token system; derives hover /
   subtle-border tints from the existing 8 vars. **Zero new JS, ~30 CSS
   lines.** `color-mix()` reached Baseline Widely Available 2025-11-09.
3. **htmx `class-tools` + `loading-states` extensions** — two vendored single
   files (~2.2 KB + ~4.8 KB un-minified, 0BSD) that unlock `[MOT-50
   htmx-swap-fade]` + `[MOT-13 skeleton-shimmer]` + `[MOT-33
   icon-spin-on-action]` on the four swap targets we already have
   (`#status-badge`, `#display-name-block`, `#ingest-status`, paper-row swaps)
   without writing per-event JS.

Main thematic gap in arXMCP's frontend toolkit: the console has **zero of the
four a11y baselines** that modern (2025–2026 Baseline) APIs make trivial —
no `prefers-reduced-motion` gate, no `:focus-visible` styling, no `aria-live`
on htmx swap targets, no skip-link. Pure-CSS APIs reaching Baseline
Widely-Available in 2025–2026 (`:has()`, `color-mix()`, `popover` attribute,
container queries, View Transitions same-document) close most of the
underdeveloped surfaces in `arxmcp-design-system.md` §7 **with zero new
JS files**, which keeps the open UI security audit
(`chris-dare-dev/arXMCP#9`) from widening.

---

## 2. Technique candidates

### Category A — Pure-CSS / native Web APIs (zero vendor bytes)

#### A1. `prefers-reduced-motion` gate

- **Canonical reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion
- **License:** N/A (CSS spec)
- **Vendor weight:** 0 bytes
- **Browser baseline:** Widely Available (Chrome 74 / Safari 10.1 / Firefox 63)
- **What arXMCP could do with it:** wrap any new `transition` / `animation` /
  `@keyframes` in `@media (prefers-reduced-motion: no-preference) { … }`,
  AND add the universal opt-out reset
  `@media (prefers-reduced-motion: reduce) { *, *::before, *::after {
  animation-duration: 0.01ms !important; transition-duration: 0.01ms
  !important; } }` at the end of `frontend/static/app.css`. Closes
  `arxmcp-design-system.md` §7 bullet 1.
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** **prerequisite** for all of MOT-1…MOT-65.
  Specifically guards MOT-NO-5 ("continuous animation without
  prefers-reduced-motion fallback").
- **Risk flags:** none. No CSP impact, no autoescape impact, zero new JS to
  audit.
- **Compatibility with arXMCP:** native CSS, no Node, no htmx interaction.

#### A2. `:focus-visible` outline rings

- **Canonical reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/:focus-visible
- **License:** N/A
- **Vendor weight:** 0 bytes
- **Browser baseline:** Widely Available (Chrome 86 / Safari 15.4 / Firefox 85)
- **What arXMCP could do with it:** add a single rule —
  `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px;
  border-radius: 2px; }` — applied to `button, .button, a, input, [tabindex]`.
  Closes `arxmcp-design-system.md` §7 bullet 2. Uses the existing `--accent`
  token (§4).
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** MOT-34 (`focus-visible-glow`) baseline.
- **Risk flags:** none; this is a WCAG 2.1 AA prerequisite, not a regression.
- **Compatibility with arXMCP:** native CSS.

#### A3. `aria-live` polite region + `<output>` for htmx swap announcements

- **Canonical reference:** https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Attributes/aria-live
- **License:** N/A
- **Vendor weight:** 0 bytes
- **Browser baseline:** Widely Available (universal in screen readers since
  early 2010s).
- **What arXMCP could do with it:** add a single
  `<div id="sr-announce" aria-live="polite" aria-atomic="true"
  class="visually-hidden"></div>` to `base.html` after `<main>`. Use the
  existing htmx `hx-on::after-swap="..."` attribute (no per-event JS file)
  on the four swap targets (`#status-badge`, `#display-name-block`,
  `#ingest-status`, paper-row swaps in `notebook_detail.html`) to inject a
  short status sentence. Closes `arxmcp-design-system.md` §7 bullet
  "no live-region announcements."
- **arXMCP positioning:** use-pure-CSS-API + native ARIA.
- **Motion primitives unlocked:** none directly; a11y enabler.
- **Risk flags:** the `hx-on:` family of htmx attributes counts as inline
  event handlers from a CSP perspective — but the existing
  `CONTENT_SECURITY_POLICY_UI` already includes `script-src 'self'
  'unsafe-inline'` for the existing JSON-shim in `base.html:18-44`, so this
  costs nothing in CSP terms. Flag for `chris-dare-dev/arXMCP#9` only
  insofar as we are using more of the inline-script surface we already
  permit (no widening).
- **Compatibility with arXMCP:** uses existing htmx 2.0.10 attribute set.

#### A4. Skip-to-main-content link

- **Canonical reference:** https://www.w3.org/WAI/WCAG21/Techniques/general/G1
- **License:** N/A
- **Vendor weight:** 0 bytes
- **Browser baseline:** Widely Available (universal).
- **What arXMCP could do with it:** prepend
  `<a class="skip-link" href="#main">Skip to main content</a>` to
  `base.html:47` and add `id="main"` to the existing `<main>` at
  `base.html:52`. Add CSS rule for `.skip-link` that visually hides
  off-screen until `:focus`. Closes `arxmcp-design-system.md` §7 bullet 3.
- **arXMCP positioning:** use-pure-CSS-API + 2 template lines.
- **Motion primitives unlocked:** none.
- **Risk flags:** none.
- **Compatibility with arXMCP:** native CSS + plain HTML.

#### A5. `@media (prefers-color-scheme: dark)` token block

- **Canonical reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-color-scheme
- **License:** N/A
- **Vendor weight:** 0 bytes
- **Browser baseline:** Widely Available (Chrome 76 / Safari 12.1 / Firefox 67).
- **What arXMCP could do with it:** add an `@media (prefers-color-scheme:
  dark) { :root { … } }` block that re-declares all 8 vars from
  `app.css:4-13`. Stays inside §4's token discipline (no parallel system).
  Closes `arxmcp-design-system.md` §7 bullet "no dark-mode" and the
  light-mode flash the user-supplied brief calls out.
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** none.
- **Risk flags:** the four `.status-badge--*` rules at `app.css:123-126`
  hard-code light-mode hex (`#e6f4ea`, `#fdf3e2`, `#eef2f7`) — they need a
  dark-mode mirror. Easy with `color-mix()` (A6).
- **Compatibility with arXMCP:** native CSS only.

#### A6. `color-mix()` for derived shades

- **Canonical reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/color-mix
- **License:** N/A
- **Vendor weight:** 0 bytes
- **Browser baseline:** **Baseline Widely Available since 2025-11-09**
  (Chrome 111 / Safari 16.2 / Firefox 113). [Source:
  web.dev / web-platform-dx / MDN.]
- **What arXMCP could do with it:** derive hover-state colors and the
  dark-mode status-badge surfaces from the existing 8 tokens instead of
  hardcoding them. Pairs with A5 to halve the maintenance cost of dark mode.
  E.g. button hover becomes `background: color-mix(in oklab, var(--accent)
  90%, white);` — replacing the imprecise `filter: brightness(1.08)` at
  `app.css:87`.
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** none directly; supports A5 dark-mode hue
  derivation.
- **Risk flags:** none — pure CSS, falls back gracefully on unsupported
  browsers (rules with `color-mix()` get dropped, prior `background:
  var(--accent)` survives).
- **Compatibility with arXMCP:** native CSS only.

#### A7. `tabular-nums` (`font-variant-numeric`) on timestamps & counts

- **Canonical reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric
- **License:** N/A
- **Vendor weight:** 0 bytes
- **Browser baseline:** Widely Available.
- **What arXMCP could do with it:** add `font-variant-numeric: tabular-nums;`
  to `dl.meta dd` (freshness `<time>`), `table.papers td` (paper counts /
  rows), and `.status-badge` (when a digit ever lands inside it). Closes
  `arxmcp-design-system.md` §7 bullet "no `tabular-nums`."
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** none.
- **Risk flags:** none.
- **Compatibility with arXMCP:** native CSS only.

#### A8. View Transitions API (same-document) + htmx integration

- **Canonical reference:** https://developer.mozilla.org/en-US/docs/Web/API/View_Transitions_API
- **License:** N/A
- **Vendor weight:** 0 bytes
- **Browser baseline:** Baseline Newly Available — Chrome 111 / Safari 18 /
  Firefox 144 (`caniuse.com/view-transitions` reports ~89.9 % global usage).
  Same-document only; cross-document still landing.
- **What arXMCP could do with it:** add
  `document.addEventListener('htmx:beforeSwap', e => {
  if (document.startViewTransition) document.startViewTransition(() =>
  htmx.swap(e.detail.target, e.detail.serverResponse, e.detail.swapSpec)); })`
  inline (~5 LOC, lives in `base.html` alongside the existing JSON-shim) to
  cross-fade `#ingest-status` and `#display-name-block` swaps. Closes
  `arxmcp-design-system.md` §7 bullet "View Transitions API." Pairs with
  MOT-50 (`htmx-swap-fade`) + MOT-52 (`view-transitions-api`).
- **arXMCP positioning:** use-pure-CSS-API (with ~5 LOC inline glue).
- **Motion primitives unlocked:** MOT-50, MOT-52.
- **Risk flags:** **fallback story is the API's own** — the `if
  (document.startViewTransition)` guard makes Firefox <144 degrade to the
  current default htmx swap with no visual transition (acceptable). Inline
  script uses existing `'unsafe-inline'` CSP allowance; no widening.
- **Compatibility with arXMCP:** native + 5 LOC inline glue. No vendor file.

#### A9. `:has()` parent selector

- **Canonical reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/:has
- **License:** N/A
- **Vendor weight:** 0 bytes
- **Browser baseline:** **Baseline Widely Available as of approximately
  2026-06** (became Newly Available 2023-12 with Firefox 121; the 30-month
  Widely-Available threshold lands within weeks). Today (2026-05-30) it
  sits just inside Newly Available — by m4/m5 of any uplift roadmap it will
  be Widely Available.
- **What arXMCP could do with it:** drive the index-row state styling
  declaratively — e.g. `tr:has(td.empty) { opacity: 0.5; }` for empty
  notebooks; `.card:has(pre.error:not(:empty)) { border-color: var(--danger);
  }` to color the error card without JS class-flipping. Closes
  `arxmcp-design-system.md` §7's broader "no declarative state styling"
  opportunity.
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** enables MOT-30 (`lift-on-hover`) and
  MOT-32 (`border-on-hover`) variants without JS.
- **Risk flags:** at today's date (`:has()` Baseline Newly Available, not yet
  fully Widely Available) — use only as progressive enhancement; never as a
  load-bearing layout primitive.
- **Compatibility with arXMCP:** native CSS only.

#### A10. `popover` attribute (native popover / modal)

- **Canonical reference:** https://developer.mozilla.org/en-US/docs/Web/API/Popover_API
- **License:** N/A
- **Vendor weight:** 0 bytes
- **Browser baseline:** **Baseline Widely Available since 2025-04** (Chrome
  114 / Safari 17 / Firefox 125). [Source: web.dev.]
- **What arXMCP could do with it:** replace any future modal need (e.g. the
  Delete-confirm for notebook removal at `notebook_detail.html`'s Delete
  button, currently bare) with `<button popovertarget="confirm-delete">`
  + `<dialog id="confirm-delete" popover>`. Native light-dismiss + Esc
  handling, no JS, no positioning lib.
- **arXMCP positioning:** use-pure-CSS-API + native HTML.
- **Motion primitives unlocked:** MOT-4 (`scale-in`) + MOT-5
  (`slide-from-edge`).
- **Risk flags:** none directly; needs `prefers-reduced-motion` gate (A1)
  before any entrance animation.
- **Compatibility with arXMCP:** native HTML attribute; no vendor file.

### Category B — htmx extensions (single-file vendor drops)

All three below are single JS files in the
`bigskysoftware/htmx-extensions` repo. Each vendors alongside
`frontend/static/htmx.min.js` and gets registered with `hx-ext="…"` on the
target element (or `<body>`). The repo's license file at
`/blob/main/LICENSE` was inaccessible via WebFetch in this session — **before
vendoring, the implementer MUST confirm the LICENSE is permissive (0BSD /
MIT / BSD-2)** and pin a SHA to `frontend/static/VENDORED.md`. Per htmx
convention and the core htmx.min.js's 0BSD posture, 0BSD is the expected
outcome — but the verify-before-vendor step is non-negotiable.

#### B1. `htmx-ext-class-tools`

- **Canonical reference:** https://htmx.org/extensions/class-tools/
- **License:** likely 0BSD (verify before vendor — see note above).
- **Vendor weight:** **~2.2 KB un-minified** (`unpkg.com/htmx-ext-class-tools@2.0.2/class-tools.js`).
  Min+gz: ~1 KB.
- **Browser baseline:** identical to htmx 2.x (Chrome 90+ / Safari 14+ /
  Firefox 90+).
- **What arXMCP could do with it:** declaratively add/remove CSS classes on
  htmx events via a `classes` attribute (e.g. `classes="add fade-in:0.5s"`).
  Powers MOT-50 (`htmx-swap-fade`) on `#status-badge` (`base.html:65`),
  `#display-name-block` (the m2 rename swap target), `#ingest-status`
  (`notebook_detail.html`), and paper-row swaps — without per-event JS.
- **arXMCP positioning:** vendor-as-single-file (extends, doesn't replace
  htmx).
- **Motion primitives unlocked:** MOT-50, MOT-1 (`fade-in`), MOT-3
  (`stagger-reveal` via `animation-delay`).
- **Risk flags:** new JS file → widens the open UI security audit
  (`chris-dare-dev/arXMCP#9`) by ~2 KB of bigskysoftware-authored code.
  Same provenance as the htmx core already vendored.
- **Compatibility with arXMCP:** native to htmx; no Node.

#### B2. `htmx-ext-loading-states`

- **Canonical reference:** https://htmx.org/extensions/loading-states/
- **License:** likely 0BSD (verify before vendor).
- **Vendor weight:** **~4.8 KB un-minified.** Min+gz: ~1.5 KB.
- **Browser baseline:** identical to htmx 2.x.
- **What arXMCP could do with it:** declaratively style request-in-flight
  states via `data-loading` attributes on the target element. Powers
  MOT-13 (`skeleton-shimmer`) on the ingest trigger button + the upload
  card + the rename form. Currently htmx requests just "sit there"
  (cited explicitly in `arxmcp-design-system.md` §7 bullet "no skeleton /
  loading affordance"). With this extension the ingest button could show
  `data-loading-class-remove="button" data-loading-class="button-busy"`
  and CSS does the rest.
- **arXMCP positioning:** vendor-as-single-file.
- **Motion primitives unlocked:** MOT-13, MOT-33 (`icon-spin-on-action`
  via CSS).
- **Risk flags:** new JS file → audit-widening; ~4.8 KB.
- **Compatibility with arXMCP:** native to htmx.

#### B3. `htmx-ext-response-targets`

- **Canonical reference:** https://htmx.org/extensions/response-targets/
- **License:** likely 0BSD (verify before vendor).
- **Vendor weight:** **~2.8 KB un-minified.** Min+gz: ~1.2 KB.
- **Browser baseline:** identical to htmx 2.x.
- **What arXMCP could do with it:** route error responses to a different
  swap target than success. arXMCP currently uses the
  `<pre id="…-error" class="error">` pattern with manual swap targets;
  this extension lets `hx-target-error="#display-name-error"` ride alongside
  `hx-target="#display-name-block"`. Tightens the error-message UX on the
  rename / URL-paste / upload flows without rewriting handlers.
- **arXMCP positioning:** vendor-as-single-file.
- **Motion primitives unlocked:** none directly; UX-correctness primitive.
- **Risk flags:** new JS file → audit-widening; ~2.8 KB.
- **Compatibility with arXMCP:** native to htmx.

### Category C — Vanilla-JS single-file vendor (only one candidate clears the bar)

#### C1. `idiomorph` + `idiomorph-ext` htmx integration

- **Canonical reference:** https://github.com/bigskysoftware/idiomorph
- **License:** **0BSD** (verified — same as htmx core).
- **Vendor weight:** **~3.3 KB min+gz** (per upstream README). Un-minified:
  ~12 KB.
- **Browser baseline:** identical to htmx 2.x.
- **What arXMCP could do with it:** replace the default htmx `outerHTML`
  swap on `#display-name-block` and the paper-row swaps with a
  morph-based diff. Avoids the focus-loss + scroll-jump that occurs when
  the user has tabbed into a form field mid-swap. Latest release: v0.7.4
  (2025-09-29). The `dist/idiomorph-ext.min.js` bundle ships htmx
  integration in one file.
- **arXMCP positioning:** vendor-as-single-file.
- **Motion primitives unlocked:** complements MOT-50 + MOT-52 (smoother
  swaps when View Transitions aren't available).
- **Risk flags:** ~3.3 KB gz is ≪ the existing htmx 2.0.10 baseline
  (~14 KB gz). Adds a 4th vendored asset to audit; same provenance as
  htmx core.
- **Compatibility with arXMCP:** drop-in htmx extension.

### Category D — Native a11y primitives already considered above

Section D was rolled into A1–A4 — there is no separate vendor candidate
in the a11y space worth surfacing. The "native a11y" surface for arXMCP
**is** pure CSS / native HTML, by virtue of the no-build-chain lock.

---

## 3. Sources reviewed

| Technique / source | URL | License | Vendor weight | Baseline | Recommended tier |
|---|---|---|---|---|---|
| `prefers-reduced-motion` | https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion | N/A | 0 | Widely Available | **C (a11y baseline)** |
| `:focus-visible` | https://developer.mozilla.org/en-US/docs/Web/CSS/:focus-visible | N/A | 0 | Widely Available | **C (a11y baseline)** |
| `aria-live` regions | https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Attributes/aria-live | N/A | 0 | Widely Available | **C (a11y baseline)** |
| Skip-link (G1) | https://www.w3.org/WAI/WCAG21/Techniques/general/G1 | N/A | 0 | Widely Available | **C (a11y baseline)** |
| `prefers-color-scheme` | https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-color-scheme | N/A | 0 | Widely Available | B (polish) |
| `color-mix()` | https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/color-mix | N/A | 0 | Widely Available (2025-11-09) | B (polish) |
| `tabular-nums` | https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric | N/A | 0 | Widely Available | B (polish) |
| View Transitions API | https://developer.mozilla.org/en-US/docs/Web/API/View_Transitions_API | N/A | 0 (5 LOC inline glue) | Newly Available (2024–2026) | B (polish) |
| `:has()` | https://developer.mozilla.org/en-US/docs/Web/CSS/:has | N/A | 0 | Newly→Widely Available (~2026-06) | B (polish) |
| `popover` attribute | https://developer.mozilla.org/en-US/docs/Web/API/Popover_API | N/A | 0 | Widely Available (2025-04) | B (future) |
| `htmx-ext-class-tools` | https://htmx.org/extensions/class-tools/ | 0BSD (verify) | ~2.2 KB un-min / ~1 KB min+gz | (htmx 2.x baseline) | A (vendor) |
| `htmx-ext-loading-states` | https://htmx.org/extensions/loading-states/ | 0BSD (verify) | ~4.8 KB un-min / ~1.5 KB min+gz | (htmx 2.x baseline) | A (vendor) |
| `htmx-ext-response-targets` | https://htmx.org/extensions/response-targets/ | 0BSD (verify) | ~2.8 KB un-min / ~1.2 KB min+gz | (htmx 2.x baseline) | A (vendor) |
| `idiomorph` | https://github.com/bigskysoftware/idiomorph | **0BSD** (verified) | ~3.3 KB min+gz | (htmx 2.x baseline) | A (vendor, optional) |

Tier legend: **C** = a11y prerequisite; **B** = polish (pure-CSS, no new
vendor file); **A** = vendor a single file (audit-widening).

---

## 4. Themes

1. **The pure-CSS APIs reaching Baseline Widely-Available in 2025–2026 close
   ~5 of the 7 high-value `arxmcp-design-system.md` §7 gaps with ZERO new
   JS.** A1–A4 (reduced-motion, focus-visible, aria-live, skip-link) are the
   non-negotiable a11y baseline; A5–A7 (dark mode via `prefers-color-scheme`
   + `color-mix()`, `tabular-nums`) are polish that respects the §4 8-token
   discipline. None of these widen the open UI security audit
   (`chris-dare-dev/arXMCP#9`).
2. **The htmx-extension catalogue is the only vendored route that survives
   the no-build-chain lock.** All three B-candidates are single files
   <5 KB un-minified, registered via `hx-ext=` on the target element, with
   the same authoring provenance (`bigskysoftware`) as the htmx core
   already vendored. Each one of B1–B3 adds <2 KB to the audit surface.
3. **No npm-installable library cleared the bar.** Alpine.js, picocss,
   sortable.js, GSAP, Framer Motion, Auto-Animate — all considered, all
   rejected (see §6). arXMCP's stack is small enough that vanilla CSS +
   htmx + 5 LOC of inline View-Transitions glue covers every motion
   primitive in `motion-vocabulary.md` §1–§6 that's appropriate for an
   operator console.
4. **The a11y triad is itself the prerequisite for every motion candidate.**
   MOT-NO-5 (`continuous animation without prefers-reduced-motion fallback`)
   makes A1 a precondition for B1, B2, A8, A10. The natural milestone shape
   is "C-tier first, B-tier second, A-tier last."

---

## 5. arXMCP already has

- **htmx 2.0.10** — vendored at `frontend/static/htmx.min.js` (0BSD, SHA
  pinned in `VENDORED.md` + `tests/test_vendored_assets_integrity.py`).
  Current latest is 2.0.x (semver-stable); a bump-to-latest could ride along
  with any of B1–B3, since the integrity test already pins re-vendor
  procedure.
- **8 CSS variables** at `app.css:4-13` — the entire token system; §4 of
  `arxmcp-design-system.md`. No parallel system to invent.
- **Inline `htmx:configRequest` JSON-shim** at `base.html:18-44` — uses the
  existing `'unsafe-inline'` CSP allowance; new inline glue (e.g. the
  View-Transitions wrapper from A8) costs nothing additional in CSP terms.
- **Native CSS-only existing classes** — `.card`, `.status-badge`,
  `.empty`, `.hint`, `.display-name`, `.rename-form`, `.notebook-actions`,
  `dl.meta`, `table.papers`, `table.notebooks`, `pre.error` —
  cited in `arxmcp-design-system.md` §5.
- **htmx-native CSS hooks** (`htmx-request`, `htmx-swapping`, `htmx-settling`)
  — **not currently used** but available without any vendoring (these are
  built into htmx core, not extensions). Worth highlighting as a
  zero-cost preflight before vendoring B2 (`loading-states`).

**Upgrades worth flagging:**

- htmx 2.0.10 → latest 2.x — non-urgent; ride along with a B-candidate
  vendor.
- Lifting `htmx-request` class styling into `app.css` (zero new vendor
  bytes) is a cheaper first step than vendoring B2; the implementer should
  evaluate whether B2's per-element opt-in attributes justify the
  extra vendor file.

---

## 6. Out of scope / parking lot

Techniques considered but rejected. The npm-installable items below are
**automatic Phase-3 BLOCKERs** per CLAUDE.md §4.7 + the §9.1 architectural
lock in `arxmcp-design-system.md`.

| Technique / lib | Rejection reason |
|---|---|
| **Tailwind CSS** (any version) | Build chain required (PostCSS + JIT). **Automatic Phase-3 BLOCKER.** |
| **shadcn/ui** | React + npm + Tailwind — triple-violation. **Automatic Phase-3 BLOCKER.** |
| **Framer Motion** | npm + React. **Automatic Phase-3 BLOCKER.** |
| **GSAP** (Pro tier) | npm + commercial license tier; even the free tier ships as ESM expecting a bundler. **Automatic Phase-3 BLOCKER.** |
| **Recharts / Chart.js / Plotly** | npm + framework-coupled; arXMCP has no charts surface. **Automatic Phase-3 BLOCKER.** |
| **Zustand / TanStack Query** | npm + React-centric client-state libs — arXMCP has no client state worth managing (htmx is the answer). **Automatic Phase-3 BLOCKER.** |
| **React / Vue / Svelte / Next.js / Vite** | SPA / build chain. **Automatic Phase-3 BLOCKER (CLAUDE.md §4.7).** Re-pinned in m3/m5. |
| **Alpine.js** (MIT, ~7 KB gz, single-file vanilla-JS) | Overlaps with htmx — htmx already covers the server-driven interactivity surface; adding Alpine would invite client-state divergence. Re-evaluate only if arXMCP grows a genuine client-state surface (it doesn't have one today). |
| **picocss** (MIT, ~10 KB gz, single-file CSS framework) | Replaces, not extends, the existing `app.css` token system. arXMCP's 8-token system is intentional (§4 discipline); swapping it for picocss's vocabulary loses curatorial control. |
| **sortable.js** (MIT, ~12 KB gz, single-file vanilla-JS drag-reorder) | No drag-reorder surface in arXMCP today (paper-row ordering is server-determined). Park for future "reorder papers within a notebook" feature; re-surface then. Cited as the canonical example in `motion-vocabulary.md` MOT-40. |
| **Auto-Animate** (MIT, ~3 KB gz, single-file) | Conflicts with htmx's swap lifecycle — it tries to animate DOM mutations that htmx already controls. Use htmx's own `htmx-swapping`/`htmx-settling` hooks + the View Transitions API (A8) instead. |
| **htmx-ext-multi-swap** | No use case in arXMCP today — every swap target is single-element. Re-surface if a swap ever needs to update two fragments atomically. |
| **htmx-ext-head-support** | No `<head>` mutation requirement in arXMCP today. The 3-template surface doesn't need it. |
| **htmx-ext-morphdom-swap** | Superseded by idiomorph (C1) per the bigskysoftware repo's own README; do not vendor both. |
| **`animation-timeline: scroll()`** | Surfaced in `source-registry.md` §2a + `motion-vocabulary.md` MOT-20/MOT-24. **Not Baseline** (Firefox still flag-gated as of 2026-05-30). For an operator console where MOT-NO-2 (`parallax on the operator console`) is already an anti-pattern, no eligible surface justifies the fallback story. Park; revisit when Firefox ships scroll-driven animations on by default. |
| **CSS Anchor Positioning (`anchor()`)** | Surfaced in `source-registry.md` §2a. **Not yet Baseline** (Firefox / Safari behind in 2026); the `popover` attribute (A10) covers arXMCP's only conceivable popover need (Delete-confirm) without anchor positioning. Revisit when arXMCP grows a richer tooltip/menu surface. |
| **Container queries (`@container`)** | Baseline Widely Available, but arXMCP's `body { max-width: 980px; … }` layout has only one meaningful breakpoint surface — the existing approach is sufficient. Park as a future tool for the notebook-detail dense card grid if it grows. |

---

## Lessons appended to scout memory

Appended a one-line lesson to
`.claude/agent-memory/frontend-uplift-library-scout/lessons.md`.
