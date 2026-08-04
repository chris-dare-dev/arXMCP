# Library scout brief — 2026q3-ui-uplift

**Scope note (read first):** the user's brief asks to "propose new libraries which could
give an interactive feel." arXMCP's answer to that question is constrained by a
non-negotiable rule: **the only allowable "library" import is a single vendored file in
`server/frontend/static/`** (CLAUDE.md §4.7; re-pinned in notebook-surface-expansion-m3/m5;
restated in `arxmcp-design-system.md` §9). npm, a bundler, a CDN `<script src="https://...">`,
and every SPA-framework paradigm (React/Vue/Svelte, Tailwind, shadcn/ui, Radix, Framer
Motion, GSAP, anime.js, TanStack) are automatic Phase-3 BLOCKERs — not because they're bad
libraries, but because `CONTENT_SECURITY_POLICY_UI` (`server/middleware.py:170-177`) has no
`script-src` entry for any external origin (`script-src 'self' 'unsafe-inline'` only — no
`https://cdn...`, no `'unsafe-eval'`), and because the server ships as a single Python wheel
with zero build step (`server/frontend/` is source-served, not compiled). Given that, this
brief answers "what gives arXMCP an interactive feel" from three real levers: **(1)** CSS
platform APIs that reached Baseline in 2024–2026 and do the job frameworks like
Framer Motion/shadcn exist to paper over, at 0 bytes; **(2)** htmx extensions — the one
proven vendoring lane arXMCP already uses (`htmx.min.js`, `json-enc.js`); **(3)** exactly one
single-file vanilla-JS candidate that clears the license bar. Section 6 names the npm-only
libraries a generic scout would reach for and why each is a BLOCKER here.

---

## 1. TL;DR

The three highest-value moves are all **zero-byte CSS**, not libraries: `@container` queries
fix the literal, measured defect in the visual manifest — a 1251px-wide input for a
12-character slug, because every `.card` form field is `width:100%` with no way to react to
the card's own width; a `<dialog>`-based confirm replaces the two `window.confirm()` native
dialogs (`notebook_detail.html:86`, `index.html:111`) that are the single most "unstyled
browser default" moment in the product; and `popover` + CSS anchor positioning turns
`.status-badge__remediation` — which today has **zero CSS rule** and renders as an ugly
491px run-on `<small>` line (visual-manifest §3) — into an actual anchored tooltip. The main
thematic gap is that **arXMCP has zero `transition` properties declared anywhere in
`app.css`** (confirmed by direct read, 370 lines) — every hover, swap, and validation state is
an instant snap or a native browser default, which is exactly what reads as "AI-generated
default stack" to a viewer, and every fix on that axis is available as a CSS API already
Baseline (or `@supports`-gated) in 2026, requiring zero new JS.

---

## 2. Technique candidates

### CSS / native-platform APIs

#### [CAND-1] `@container` (CSS container queries, size)
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@container
- **License:** n/a (browser platform feature)
- **Vendor weight:** 0 bytes
- **Browser baseline:** Chrome 105 (Aug 2022) · Firefox 110 (Feb 2023) · Safari 16 (Sept
  2022). **Baseline Widely Available** (30-month clock closed ~Aug 2025, well before this
  run).
- **What arXMCP could do with it:** `.card` (`app.css:53-59`) is the one layout primitive in
  the product and every form inside it stacks `label { display:block }` +
  `input[type=text|url|file] { width:100% }` (`app.css:74-84`) regardless of how wide the
  card actually renders. Visual-manifest §3 measured the literal defect this causes: a slug
  input ~12 characters long rendered at **1251px wide** on the `/ui/` create-notebook card.
  `container-type: inline-size` on `.card`, plus a `@container (min-width: 480px) { .card
  form { display: grid; grid-template-columns: 1fr 1fr; } }` rule, lets the 4-field
  create-notebook form and the rename/topic forms go two-column on desktop while staying
  single-column at the existing 640px floor — with **zero media query**, because the
  container is the card, not the viewport (the viewport is already `clamp(640px, 92vw,
  1400px)`, so a `@media` breakpoint can't see the card's actual rendered width the way
  `@container` can).
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** none directly (layout, not motion) — but it is the
  prerequisite for `[MOT-13 layout-shift]` to be a *deliberate* transition rather than an
  accidental reflow if a future milestone adds a `transition: grid-template-columns` guard.
- **Risk flags:** none. No CSP interaction (pure CSS). No new audit surface (no JS).
- **Compatibility:** works without npm/Node — it's a stylesheet rule. No CSP interaction.

#### [CAND-2] `:has()` (the CSS relational/parent selector)
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Selectors/has
- **License:** n/a
- **Vendor weight:** 0 bytes
- **Browser baseline:** Chrome 105 (Aug 2022) · Safari 15.4 (Mar 2022) · Firefox 121 (Dec
  2023). **Baseline Widely Available** as of ~June 2026 (Firefox 121 was the last holdout;
  30-month clock closed this year) — genuinely fresh baseline, worth flagging as newly safe.
- **What arXMCP could do with it:** two concrete, citable applications. (a) `tr:has(button.
  htmx-request)` on `table.papers` (`app.css` has no rule for this today) gives the *whole
  row* a busy treatment on the per-paper Remove action (`notebook_detail.html:348-351`)
  instead of only the 32×32px button dimming — useful because the button is one of six
  identical 77×32px "Remove" targets in the table and the row-level cue disambiguates which
  row is in flight. (b) `.card:has(form.htmx-request)` could apply a subtle
  `border-color: var(--accent)` to the whole card during any in-flight submit — currently
  the ONLY in-flight signal is the `.htmx-request` opacity dim + spinner on the button itself
  (`app.css:293-333`), which is easy to miss on a dense page (7 stacked cards, docHeight
  2343px per visual-manifest §3).
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** `[MOT-21 hover-lift]`-adjacent — more precisely this is a
  **feedback**-job primitive (motion-vocabulary §0 jobs test): "your action registered,"
  scoped to the correct row/card rather than only the control.
- **Risk flags:** none functionally, but `:has()` is a genuinely fresh Widely-Available
  entrant (crossed the line only ~2 months before this run) — no fallback needed
  functionally since it degrades to "no extra highlight," but note the freshness in case a
  future staleness re-check finds it slipped.
- **Compatibility:** works without npm/Node; no CSP interaction.

#### [CAND-3] `:user-valid` / `:user-invalid`
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Selectors/:user-invalid
- **License:** n/a
- **Vendor weight:** 0 bytes
- **Browser baseline:** Chrome 119 (Nov 2023, unprefixed) · Firefox (long-standing, since
  Firefox 88, 2021) · Safari 16.5 (May 2023). **Baseline Widely Available** as of ~May 2026
  (Chrome 119 was the last holdout for the unprefixed standard form).
- **What arXMCP could do with it:** `app.css` has **zero validation-state styling anywhere**
  — not even a `:invalid` rule. Seven forms carry native constraint attributes today
  (`required`, `minlength`/`maxlength`, `pattern="[a-z][a-z0-9-]{2,30}"` on the slug field
  at `index.html:31-32`, `type="url"` on the paste-URL field) but none of them render
  differently when the constraint fails. `:user-invalid` (fires only AFTER the user has
  interacted — unlike `:invalid`, which fires on page load for a `required` empty field and
  is famously the wrong default) on `input[type=text],input[type=url]` with a
  `border-color: var(--danger)` and `outline` echo gives the slug-pattern field, in
  particular, its first-ever inline validation cue instead of relying purely on the server's
  422 JSON round-tripped through `hx-on::htmx:response-error` into `pre#*-error`
  (`notebook_detail.html:37`, `:124`, `:170`, `:208`, `:267`; `index.html:27`).
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** `[MOT-45 validation-shake]` if paired with a
  `prefers-reduced-motion`-gated `transform` micro-shake keyframe (cheap, ~10 lines,
  matches the existing `@keyframes` pattern at `app.css:332`/`:348`/`:366`) — or none if kept
  to a static border-color change, which is the more conservative, house-thesis-aligned
  choice (the "quiet instrument panel" thesis in `arxmcp-design-system.md` §9 favors
  static color-as-signal over motion-as-signal where either serves the job).
- **Risk flags:** none. Zero new JS, zero CSP surface. Genuinely fresh baseline (~3 months
  old at time of writing) — worth a note in the synthesizer's staleness tracking.
- **Compatibility:** works without npm/Node; no CSP interaction.

#### [CAND-4] `field-sizing: content`
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/field-sizing
- **License:** n/a
- **Vendor weight:** 0 bytes
- **Browser baseline:** Chrome 123 (Mar 2024) · Edge 123. Reached **Baseline Newly Available
  on 2026-06-16** per the Baseline dashboard — **NOT Widely Available yet** (Firefox/Safari
  status still catching up as of this run). **Explicit fallback required.**
- **What arXMCP could do with it:** the ONLY multi-line control in the entire product is
  `<textarea name="description" maxlength="512" rows="2">` (`index.html:57-58`,
  `notebook_detail.html:139-140`, the topic/keywords field) — and `app.css`'s form-control
  selector list (`app.css:74`) does not even mention `textarea`, so it renders with zero
  custom styling at a fixed 2-row height regardless of how much of the 512-char budget the
  operator has typed. `field-sizing: content` (with `max-height` capped via
  `field-sizing:content; min-height: 2lh; max-height: 8lh`) auto-grows the box as text is
  typed, replacing the fixed 2-row crop with a naturally-sized field.
- **Fallback story:** the existing `rows="2"` HTML attribute is ALREADY the fallback — browsers
  without `field-sizing` support simply keep the static 2-row box (today's current behavior,
  not a regression). Wrap the CSS in `@supports (field-sizing: content) { textarea {
  field-sizing: content; } }` so unsupported browsers see zero change.
- **arXMCP positioning:** use-pure-CSS-API (with `@supports` gate).
- **Motion primitives unlocked:** none named — this is a layout affordance, not motion; do
  not force a `[MOT-13]` citation where none is earned (motion-vocabulary §0's jobs test
  cuts both ways).
- **Risk flags:** baseline gap — Firefox/Safari support unconfirmed as of this run; MUST ship
  behind `@supports`. Zero CSP/security surface.
- **Compatibility:** works without npm/Node; no CSP interaction; degrades safely.

#### [CAND-5] `<dialog>` element (native modal) replacing `window.confirm()`
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/dialog
- **License:** n/a
- **Vendor weight:** 0 bytes CSS + ~10-15 lines of inline vanilla JS (`dialog.showModal()` /
  `.close()` — already permitted under the existing CSP's `script-src 'self'
  'unsafe-inline'`, the same clause that already allows `base.html:38-45`'s inline script).
- **Browser baseline:** Chrome 37 (2014) · Firefox 98 (Mar 2022) · Safari 15.4 (Mar 2022).
  **Baseline Widely Available** since ~Sept 2024 — long-safe, oldest and safest candidate in
  this brief.
- **What arXMCP could do with it:** the two destructive actions in the product —
  delete-notebook (`notebook_detail.html:84-87`) and remove-paper
  (`notebook_detail.html:348-351`), plus the third at `index.html:106-114` (remove-notebook
  from the list) — all fire `hx-confirm`, which is htmx's wrapper around the browser's
  native, unstyled `window.confirm()` modal. This is arguably the single most
  "un-designed" moment in the whole console: it renders with the OS chrome, ignores every
  CSS token (`--danger`, `--card-bg`, `--border`), and is the literal opposite of "crafted."
  Replacing it with an in-page `<dialog>` styled via `::backdrop { background: color-mix(in
  oklab, var(--fg) 40%, transparent); }` and the existing `.card` visual language turns a
  jarring OS-chrome interruption into an on-brand confirm surface — a genuine, concrete
  answer to the user's "looks AI-generated / unoriginal" complaint, at LITERAL zero
  dependency cost. htmx's `hx-confirm` attribute can be swapped for a small
  `htmx:confirm` event listener (documented htmx pattern) that opens the `<dialog>` instead
  and calls `event.detail.issueRequest()` on confirm — no library needed, htmx core already
  ships the hook.
- **arXMCP positioning:** use-pure-CSS-API + inline vanilla JS (pattern-lift, no vendor file).
- **Motion primitives unlocked:** `[MOT-4 scale-in]` for the dialog mount via
  `@starting-style` (see CAND-8 below for the entrance-transition primitive) — but a static,
  non-animated `<dialog>` is ALSO a complete, valid ship of this candidate; motion is
  optional polish, not the point.
- **Risk flags:** widens the UI security-audit surface slightly (new JS event listener path)
  — flag for `chris-dare-dev/arXMCP#9`. `::backdrop` + `<dialog>` do NOT bypass
  `frame-ancestors 'none'` or autoescape; the dialog body is still Jinja2-templated with
  autoescape ON, so no new XSS surface if the confirm text stays server-templated the way it
  is today (`notebook_detail.html:86`'s confirm string already interpolates
  `{{ notebook.slug }}` inside a Jinja2 `hx-confirm=""` attribute — moving that same string
  into `<dialog>` body markup keeps identical escaping behavior).
- **Compatibility:** works without npm/Node; `script-src 'self' 'unsafe-inline'` already
  covers the required inline JS; no CSP change needed.

#### [CAND-6] `popover` attribute + CSS anchor positioning (`anchor-name` / `position-anchor` / `anchor()`)
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/API/Popover_API/Using ·
  https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Anchor_positioning/Using
- **License:** n/a
- **Vendor weight:** 0 bytes
- **Browser baseline:** `popover` — Chrome 114 (2023) · Firefox 132 (Oct 2024) · Safari 17
  (2023). **Baseline Newly Available** (last-holdout Firefox 132 closed the cross-browser set
  Oct 2024; 30-month Widely-Available line lands ~Apr 2027 — NOT yet Widely Available).
  Anchor positioning — Chrome 125 (2024) · Firefox 132 (Oct 2024) · Safari 18.2 (Dec 2024).
  **Baseline Newly Available** (Widely-Available line ~June 2027). Both need `@supports`
  gating; both degrade gracefully (an un-anchored, non-popover fallback is simply the current
  static `<small>` behavior).
- **What arXMCP could do with it:** this is the most concrete UI *bug* this brief found, not
  just a gap. `.status-badge__remediation` (the footer operability badge's remediation text,
  e.g. "status non-pass — see docs/install.md troubleshooting") has **NO CSS rule anywhere in
  `app.css`** — it inherits raw `<small>` UA styling and renders inline, producing (per
  visual-manifest §3, measured live) a **491px-wide run-on line**, not the pill + caption it
  visually should be. `popover="auto"` on the remediation `<small>` (triggered by
  `popovertarget` on the badge `<span>`, or via `:hover`/`:focus-within` using the CSS
  `::backdrop`-free lightweight popover mode) + `anchor-name`/`position-anchor` to pin it
  directly under the badge turns a broken run-on line into an actual anchored tooltip —
  without a single line of positioning JavaScript (no `getBoundingClientRect()`, no
  Popper.js, no Floating UI — which is exactly the class of library this API set exists to
  make unnecessary).
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** `[MOT-26 tooltip-fade]` — the popover's native
  `@starting-style`-driven show/hide transition (built into the Popover API's `display:
  none ↔ [popover]` interpolation model) serves the orientation job ("where did this
  explanatory text come from") for free.
- **Risk flags:** both features are Newly-Available, not Widely-Available — MUST ship behind
  `@supports selector(:popover-open)` (or equivalent feature-detection) with the current
  broken-but-functional `<small>` behavior as the fallback (not zero risk of regression if
  the CSS is unconditional — must be gated).
- **Compatibility:** works without npm/Node; no CSP interaction (native browser API, not a
  script).

#### [CAND-7] `text-wrap: balance`
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/text-wrap-style
- **License:** n/a
- **Vendor weight:** 0 bytes
- **Browser baseline:** Chrome 114 (2023) · Firefox 121 (Dec 2023) · Safari 17.5 (May 2024).
  **Baseline Newly Available**, crossing to **Widely Available on ~2026-11-13** (per the
  Safari 17.5 shipping date + 30 months) — 3 months short of the line at time of writing;
  safe to ship behind no gate since the fallback (`text-wrap: wrap`, today's default) is
  visually harmless.
- **What arXMCP could do with it:** visual-manifest §2 measured that arXMCP has "effectively
  one typographic step" — `h1` at 32px and `.card h2` at 17.6px are the only two heading
  sizes, with zero letter-spacing and zero deliberate line-break control anywhere. `h1`
  ("arXMCP notebooks") and every `.card h2` title ("Create notebook", "Papers in this
  notebook (6)") are short enough that a viewport-width-triggered ragged last line (e.g. one
  orphaned word) is a real, if minor, "not quite crafted" tell. `text-wrap: balance` on `h1,
  .card h2` is a one-line, zero-risk typographic polish.
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** none (typography, not motion).
- **Risk flags:** none — `text-wrap: pretty` (the paragraph-orphan-control sibling) is
  explicitly NOT recommended alongside this: Firefox has not shipped it as of this run, and
  arXMCP has no long-form paragraph copy that would benefit (the `.hint`/`.note` strings are
  1-2 short sentences).
- **Compatibility:** works without npm/Node; no CSP interaction.

#### [CAND-8] Cross-document View Transitions (`@view-transition { navigation: auto; }`)
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/API/View_Transition_API/Using#cross-document_view_transitions
- **License:** n/a
- **Vendor weight:** 0 bytes
- **Browser baseline:** Chrome/Edge 126 (2024) · Safari 18 (2024) · **Firefox: NOT shipped**
  as of this run (was "expected in 2026" per multiple trackers, unconfirmed landed). **NOT
  Baseline** — Chromium+Safari only.
- **What arXMCP could do with it:** `arxmcp-design-system.md` §7 names this exact gap
  verbatim as "genuinely open": `base.html:38-45`'s `htmx.config.globalViewTransitions =
  true` covers htmx-fragment swaps only; a full page navigation — e.g. clicking "Open" on a
  notebook row (`index.html:94`, a bare `<a href="/ui/notebooks/{{ nb.slug }}"
  class="button">`) — gets an instant, unstyled document swap. The one-line
  `@view-transition { navigation: auto; }` at-rule in `app.css` opts every same-origin
  navigation into the browser's default crossfade, reusing the SAME `::view-transition-old/
  -new(root)` 200ms duration cap already declared at `app.css:352-355` for the htmx-swap
  case — one rule serves both.
- **Fallback story:** the `@view-transition` at-rule is a genuine no-op in unsupported
  browsers (Firefox simply ignores the unknown at-rule and navigates instantly, today's
  exact behavior) — this is the safest possible progressive-enhancement shape, no
  `@supports` gate even needed.
- **arXMCP positioning:** use-pure-CSS-API.
- **Motion primitives unlocked:** `[MOT-14 shared-element-transition]` / `[MOT-36
  route-fade]` — continuity job (motion-vocabulary §0): "the same instrument, a different
  notebook's data now showing."
- **Risk flags:** must stay inside the existing `prefers-reduced-motion: no-preference` gate
  block (`app.css:344`) alongside the htmx view-transition rule — **do not** let it leak
  outside that block, or it becomes the second sticky reduced-motion gap (see §5/§6 on the
  existing `base.html:38-45` JS gate that only evaluates once).
- **Compatibility:** works without npm/Node; no CSP interaction; genuinely safe no-op
  fallback on Firefox.

#### [CAND-9] `light-dark()` — lower priority, DX-only win
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Values/color_value/light-dark
- **License:** n/a
- **Vendor weight:** 0 bytes
- **Browser baseline:** Firefox 120 (Nov 2023) · Chrome 123 (Mar 2024) · Safari 17.5 (May
  2024). **Baseline Newly Available**, crossing to **Widely Available on 2026-11-13** — 3
  months short at time of writing.
- **What arXMCP could do with it:** `:root` (`app.css:11-18`) declares 8 custom properties;
  `@media (prefers-color-scheme: dark)` (`app.css:242-291`) re-declares 7 of them plus 6 more
  ad-hoc dark-only overrides (button text color, input bg/color, 4 status-badge pairs, `th`
  background) — ~50 lines of parallel light/dark declarations. `light-dark(#1a1a1a, #e8e8e8)`-
  style inline pairing at each token's single declaration site would let `:root` carry both
  values in one line each, collapsing the duplicated block. This is a maintainability/DX win
  (fewer places a future color change has to land twice), not a new user-facing affordance —
  rank it below CAND-1..8.
- **arXMCP positioning:** use-pure-CSS-API. Requires `color-scheme: light dark` to already
  be declared (it is, `app.css:10` — load-bearing, don't touch) for `light-dark()` to resolve
  correctly.
- **Motion primitives unlocked:** none.
- **Risk flags:** a full token-system rewrite mid-milestone risks the WCAG contrast
  re-verification `arxmcp-design-system.md` §4 demands on ANY token change ("Re-run these
  before any colour change — a token tweak that drops a pair below 4.5:1 is a Phase-3
  BLOCKER") — treat as a refactor-only candidate for a dedicated milestone, not a drive-by.
- **Compatibility:** works without npm/Node; no CSP interaction.

### htmx extensions (single-file vendored drops — the PROVEN lane)

arXMCP already vendors `htmx.min.js` 2.0.10 (0BSD) and hand-authors `json-enc.js` in the same
directory, so this category is not hypothetical — it is the one path with a working
precedent. **Important correction to the license-lookup default:** the `htmx-extensions`
GitHub repo carries no repo-root `LICENSE` file and no `license` field in `package.json` or
on the npm registry (verified live, 2026-08-03, via `registry.npmjs.org` for
`htmx-ext-loading-states`/`htmx-ext-response-targets`/`htmx-ext-preload`, all `null`) — BUT
**each individual extension subdirectory carries its own `LICENSE` file**, and every one
checked (`loading-states`, `response-targets`, `preload`, `class-tools`) is **BSD Zero
Clause (0BSD)**, the same license as the already-vendored `htmx.min.js`. The per-extension
`LICENSE` file is the citable grant — cite `src/<ext>/LICENSE`, not the repo root or
`package.json`, when pinning provenance in a future `VENDORED.md` entry.

#### [CAND-10] `loading-states` extension
- **Reference:** https://htmx.org/extensions/loading-states/ ·
  https://github.com/bigskysoftware/htmx-extensions/tree/main/src/loading-states
- **License:** 0BSD (`src/loading-states/LICENSE`, verified 2026-08-03)
- **Vendor weight:** 5,551 bytes unminified source (as vendored — no minified build is
  published in the repo, so arXMCP would vendor it as-is, matching the plain, unminified
  style of the in-repo `json-enc.js`). Estimated gzip ~2.0 KB (no official minified/gzipped
  artifact exists to cite directly — this is an estimate from typical JS gzip ratios,
  flagged as such per the honesty requirement).
- **Browser baseline:** n/a (JS library, not a browser feature) — runs on anything htmx 2.x
  runs on.
- **What arXMCP could do with it:** direct, named answer to a measured gap — visual-manifest
  §4 confirms **`hx-indicator` is set on ZERO elements** across all 9 `hx-*` interactions on
  `notebook_detail.html`. `loading-states` adds declarative `data-loading`,
  `data-loading-class`, `data-loading-disable`, `data-loading-path` attributes so
  in-flight state can target elements OTHER than the requesting one — e.g. dim the entire
  `#ingest-status` card while `POST .../ingest` is in flight (`notebook_detail.html:262-268`),
  not just the submit button, which is the CAND-2 `:has()` idea implemented as a
  purpose-built extension instead of a hand-rolled selector.
- **arXMCP positioning:** vendor-as-single-file — OR pattern-lift. Given `[CAND-2]`
  (`:has()`) already covers the "whole-card busy state" job at 0 bytes with no new JS audit
  surface, **recommend `:has()` first; reach for `loading-states` only if a job appears that
  `:has()` genuinely cannot express** (e.g. path-scoped loading states across DIFFERENT
  targets during ONE request, which `:has()` cannot do declaratively).
- **Motion primitives unlocked:** `[MOT-28 spinner]` (already served by `app.css:317-333`),
  extends to whole-region dimming.
- **Risk flags:** new JS file = new UI security-audit surface
  (`chris-dare-dev/arXMCP#9`). Depends on htmx internals (`htmx.defineExtension`) the same
  way `json-enc.js` does — low but non-zero coupling to htmx 2.x internal API stability
  across future htmx upgrades.
- **Compatibility:** works without npm/Node (single `<script src>` tag, same pattern as
  `htmx.min.js`); `script-src 'self'` already covers a same-origin vendored file — no CSP
  change needed.

#### [CAND-11] `response-targets` extension
- **Reference:** https://htmx.org/extensions/response-targets/ ·
  https://github.com/bigskysoftware/htmx-extensions/tree/main/src/response-targets
- **License:** 0BSD (`src/response-targets/LICENSE`, verified 2026-08-03)
- **Vendor weight:** 3,740 bytes unminified source. Estimated gzip ~1.3 KB (estimate, no
  published minified artifact).
- **Browser baseline:** n/a (JS library).
- **What arXMCP could do with it:** the EXACT same inline JS one-liner is hand-duplicated
  **six times** across the two templates: `hx-on::htmx:response-error="document.
  getElementById('<x>-error').textContent = (function(t){try{return JSON.parse(t).detail||t;
  }catch(e){return t;}})(event.detail.xhr.responseText)"` at `notebook_detail.html:37`,
  `:124`, `:170`, `:208`, `:267` and `index.html:27`. `response-targets` replaces every one
  of these with a declarative `hx-target-4xx="#<x>-error"` / `hx-target-5xx="#<x>-error"`
  attribute pair, deleting ~450 characters of repeated inline JS per form (6 forms) and
  removing the fragile hand-rolled `JSON.parse(...).detail||t` fallback chain from being
  duplicated six times with six chances to drift.
- **arXMCP positioning:** vendor-as-single-file. This is the strongest htmx-extension
  candidate in the brief — it removes existing duplicated code rather than adding a new
  affordance, which is the safest kind of dependency to take.
- **Motion primitives unlocked:** none (error-routing, not motion) — pairs naturally with a
  future `[MOT-45 validation-shake]` on the error target if CAND-3 lands.
- **Risk flags:** new JS file = new UI security-audit surface. The error text still flows
  through the SAME `pre.error` `textContent` assignment pattern (not `innerHTML`), so no new
  XSS surface — `response-targets` only changes which element htmx swaps the response INTO,
  not how the content is inserted.
- **Compatibility:** works without npm/Node; no CSP change needed (same-origin vendored
  file).

#### [CAND-12] `preload` extension
- **Reference:** https://htmx.org/extensions/preload/ ·
  https://github.com/bigskysoftware/htmx-extensions/tree/main/src/preload
- **License:** 0BSD (`src/preload/LICENSE`, verified 2026-08-03)
- **Vendor weight:** 14,099 bytes unminified source — the largest of the extensions
  reviewed here (viewport/idle-callback + mouseover/mousedown/touchstart preload-trigger
  logic accounts for the size). Estimated gzip ~4.5 KB (estimate). **This is the one
  extension in this brief that needs to justify its weight against the existing htmx
  baseline (~14 KB gz)** per the hard rule — at ~4.5 KB gz estimated it clears the >20 KB
  gz justification bar, but it is nearly 3x heavier than `response-targets`, so rank it
  BELOW CAND-10/11.
- **Browser baseline:** n/a (JS library).
- **What arXMCP could do with it:** `index.html:94`'s "Open" link
  (`<a href="/ui/notebooks/{{ nb.slug }}" class="button">Open</a>`) is a bare, non-htmx
  navigation — the single most-clicked control in the product (it's the only way into the
  dense detail page). `hx-ext="preload"` + `preload="mousedown"` on that link fires the GET
  for `/ui/notebooks/{slug}` on mousedown rather than on click-release, shaving the
  network round-trip off the perceived latency of the console's core navigation path. Pairs
  well with CAND-8 (cross-document view transitions) — a preloaded, transitioned navigation
  is the closest arXMCP can get to an SPA-smooth feel without an SPA.
- **arXMCP positioning:** vendor-as-single-file.
- **Motion primitives unlocked:** none directly — an enabler for CAND-8's transition to
  feel instant rather than merely animated.
- **Risk flags:** new JS file = new UI security-audit surface. Preloading on `mousedown`
  fires a real GET request before the user commits to the click — negligible risk on a
  loopback-only, same-origin, read-only navigation (`/ui/notebooks/{slug}` is idempotent
  GET), but note it explicitly since "fires network requests before user intent is
  confirmed" is exactly the kind of behavior a security audit should see documented, not
  discovered.
- **Compatibility:** works without npm/Node; `connect-src 'self'` already covers same-origin
  preload GETs — no CSP change needed.

### Single-file vendor JS (non-htmx-extension)

#### [CAND-13] idiomorph (`idiomorph-ext.min.js`, htmx-integrated build)
- **Reference:** https://github.com/bigskysoftware/idiomorph
- **License:** 0BSD (repo-root `LICENSE`, verified 2026-08-03 — same license text as the
  already-vendored `htmx.min.js`, same author/org, bigskysoftware)
- **Vendor weight:** `idiomorph-ext.min.js` is **10,153 bytes minified** (verified via the
  GitHub Contents API, 2026-08-03). No pre-built `.gz` artifact exists for the `-ext`
  bundle specifically, but the core `idiomorph.min.js.gz` (9,703 bytes minified → 3,350
  bytes gzipped, a ~34% ratio) is a directly measured sibling build; applying the same ratio
  to the 10,153-byte `-ext` build estimates **~3.5 KB gzipped**. This clears the >20 KB gz
  justification bar easily and sits well under the existing 14 KB gz `htmx.min.js` baseline.
- **Browser baseline:** n/a (JS library; works anywhere htmx 2.x runs).
- **What arXMCP could do with it:** htmx's default `outerHTML`/`innerHTML` swap fully
  replaces DOM nodes on every fragment update — which is why `app.css:344-370` needs
  hand-authored `row-fade-out` / `badge-flash` keyframes keyed to htmx's `.htmx-swapping`/
  `.htmx-settling` lifecycle classes just to make a replacement feel like a transition rather
  than a flash. `idiomorph` (via `hx-swap="morph"` once the extension is loaded) diffs the
  incoming HTML against the existing DOM and patches only what changed, which means CSS
  transitions on unchanged attributes (e.g. a `transition: background-color 150ms` on
  `.status-badge` for the `htmx-settling` state) would animate smoothly through the DOM
  node's OWN continuity instead of needing a keyframe animation keyed to a full-replace
  event. Concretely: the `#display-name-block` rename swap (`notebook_detail.html:20`,
  target of the form at `:31-46`) and `#topic-block` swap (`:119-145`) are both
  outerHTML-replace today — morph-swapping them would let a future `transition:
  background-color` on `.display-name` fade in a "just changed" highlight using the SAME DOM
  node, which a full-replace swap cannot do (a freshly-inserted node has no "before" state
  to transition FROM).
- **arXMCP positioning:** vendor-as-single-file. This is the single strongest non-CSS
  candidate in the brief, given it shares the same license and author as the already-trusted
  `htmx.min.js` and directly extends a swap mechanism arXMCP already leans on for its motion
  system (`.htmx-swapping`/`.htmx-settling`).
- **Motion primitives unlocked:** `[MOT-13 layout-shift]`, and unlocks a genuinely NEW
  motion primitive not yet in the vocabulary — **continuity-preserving attribute
  transitions across an htmx swap** (the DOM node persists; the keyframe workaround pattern
  at `app.css:344-370` becomes unnecessary for in-place-attribute-change cases specifically,
  though it remains correct for true insert/remove cases like the papers-table row
  add/remove, which morph doesn't change).
- **Risk flags:** new JS file = new UI security-audit surface. Morph-based swapping means the
  library, not the server template, decides which DOM nodes are patched vs. replaced —
  worth an explicit note for the audit that this does NOT change the autoescape/XSS boundary
  (the SOURCE HTML is still the same Jinja2-autoescaped server response; idiomorph only
  changes how that already-safe HTML string gets applied to the live DOM, node-patch vs.
  node-replace). Migrating existing `outerHTML swap:200ms` targets to `morph` would also
  require re-verifying the `row-fade-out`/`badge-flash` keyframes still fire correctly (morph
  may not add `.htmx-swapping`/`.htmx-settling` the same way outerHTML does) — flag as a
  Phase-2 regression-test item, not a blocker.
- **Compatibility:** works without npm/Node (single `<script src>`, same pattern as
  `htmx.min.js`); no CSP change needed (same-origin vendored file, `script-src 'self'`).

### Native a11y / MDN-baseline closes-the-gap

#### [CAND-14] `<output>` element for htmx-swap announcements (pattern-lift, not a library)
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/output
- **License:** n/a
- **Vendor weight:** 0 bytes (an HTML element choice, not a script)
- **Browser baseline:** universal — HTML5 forms element, supported since ~2011 in every
  engine. **Baseline Widely Available**, oldest-safe entry in this brief.
- **What arXMCP could do with it:** `<output>` carries an **implicit `role="status"` +
  implicit `aria-live="polite"`** — it is the semantically-correct element for exactly what
  arXMCP is hand-building today with 24 explicit `aria-live="polite"` attributes scattered
  across three templates (per `arxmcp-design-system.md` §6). Swapping the htmx-fragment
  targets that are pure status text (`#display-name-block`, `#topic-block`,
  `#ingest-status`) from `<p>`/`<div>` + manual `aria-live="polite"` to `<output>` removes the
  manual attribute (fewer chances the swap-fragment/template pair drifts out of sync — the
  EXACT failure mode `notebook_detail.html:16-19`'s own comment warns about: "the swap
  REPLACES this element, so the returned fragment MUST also carry the attribute"). This does
  NOT apply to the papers `<tbody>` (a list, correctly `aria-live="polite"` on a `<tbody>`,
  not an `<output>` candidate) or `pre.error` (correctly a live alert region, not a status
  output) — scope it to the 2-3 single-value status swaps only.
- **arXMCP positioning:** pattern-lift (element choice, not a vendored dependency).
- **Motion primitives unlocked:** none — semantic correctness, not motion.
- **Risk flags:** none. Zero CSP/security impact — pure markup semantics.
- **Compatibility:** works without npm/Node; no CSP interaction.

#### [CAND-15] `prefers-reduced-motion` `change`-listener fix (pattern-lift)
- **Reference:** https://developer.mozilla.org/en-US/docs/Web/API/MediaQueryList/change_event
- **License:** n/a
- **Vendor weight:** ~4 lines of inline vanilla JS (delta from the existing
  `base.html:38-45` block, not a new file)
- **Browser baseline:** `matchMedia`/`change` event — universal, Baseline Widely Available
  for a decade+.
- **What arXMCP could do with it:** `arxmcp-design-system.md` §7 names this exact gap as
  "genuinely open": `base.html:38-45` reads `matchMedia('(prefers-reduced-motion:
  reduce)')` once inside `DOMContentLoaded` and sets `htmx.config.globalViewTransitions`
  accordingly — but never registers a `.addEventListener('change', ...)` on the
  `MediaQueryList`, so an operator who flips their OS reduced-motion setting mid-session
  keeps view transitions until a full page reload. The CSS-side gates (`app.css:223`,
  `:317`, `:344`) react live because `@media` re-evaluates continuously; only this one JS
  read is stuck. A 4-line `change` listener closes the gap completely.
- **arXMCP positioning:** pattern-lift (fix to existing inline script, zero new file).
- **Motion primitives unlocked:** none — this is an a11y-correctness fix, not a new motion
  primitive; it makes the EXISTING view-transition motion (already shipped) correctly
  responsive to a live accessibility preference change.
- **Risk flags:** none — strictly closes a gap, adds no new attack surface (same inline
  script block, same CSP clause already in use).
- **Compatibility:** works without npm/Node; already covered by `script-src 'self'
  'unsafe-inline'`.

### Considered, deliberately NOT given a full entry (kept brief — see §6 for full rejections)

- **`animation-timeline: scroll()`/`view()`** — Baseline-blocked by Firefox since Sept 2025
  (per live Baseline dashboard check this run); `arxmcp-design-system.md`'s house thesis
  explicitly bans scroll-driven spectacle on the dense S-2 workflow surface (BAN-12). One
  narrow legitimate fit exists — a `view()`-timeline reading-progress indicator on the ar5iv
  preview route (a document-view surface, not the dense workflow page) — but the Firefox gap
  plus the weak thesis fit rank it below every CAND above. Not given a full entry; revisit if
  Firefox ships it.
- **`@property` (typed custom properties)** — Baseline Newly Available (Firefox 128, July
  2024; Widely-Available line ~Jan 2027). Only identified use is typing `--accent` as
  `<color>` so `badge-flash` interpolates through color space rather than a binary swap — a
  marginal, unmeasurable-in-practice win given `badge-flash` already reads correctly via
  `color-mix()`. Parked.
- **`interpolate-size: allow-keywords`** — too new to cite a stable multi-browser baseline
  date as of this run (Chrome-only in most trackers consulted); explicitly NOT recommended
  for production reliance. Watch-list only.
- **Self-hosted `--mono` font subset (e.g. JetBrains Mono, OFL-1.1)** — investigated per the
  dispatch brief's point 4. Full-charset `JetBrainsMono-Regular.woff2` is **92,380 bytes**
  (measured live via the GitHub Contents API, 2026-08-03) — a hand-subsetted build (Basic
  Latin + digits only, via `fonttools pyftsubset`, no ligature alternates) would land
  meaningfully lower based on typical subsetting ratios, but **no actual subsetted artifact
  was produced or measured this run** — citing a firm number here would violate the vendor-
  weight-honesty rule. The house thesis's "zero font files today, `-apple-system` stack"
  posture (`arxmcp-design-system.md` §0/§1) is a deliberate choice, not an oversight, and the
  ONLY motivating gap (`tabular-nums` rendering consistency across OS mono-font fallbacks)
  is already served by `font-variant-numeric: tabular-nums` (`app.css:133-135`), which every
  system mono font in the stack (SF Mono/Consolas/Menlo) honors. **Not recommended** — flag
  as considered-and-rejected, not a candidate.

---

## 3. Sources reviewed

| Technique | URL | License | Vendor weight | Baseline | Tier |
|---|---|---|---|---|---|
| `@container` | developer.mozilla.org/…/@container | n/a | 0 B | Widely Available (~Aug 2025) | **Recommend** |
| `:has()` | developer.mozilla.org/…/:has | n/a | 0 B | Widely Available (~June 2026) | **Recommend** |
| `:user-valid`/`:user-invalid` | developer.mozilla.org/…/:user-invalid | n/a | 0 B | Widely Available (~May 2026) | **Recommend** |
| `field-sizing: content` | developer.mozilla.org/…/field-sizing | n/a | 0 B | Newly Available (2026-06-16) | Recommend w/ `@supports` |
| `<dialog>` | developer.mozilla.org/…/dialog | n/a | 0 B + ~15 LOC inline JS | Widely Available (~Sept 2024) | **Recommend (top pick)** |
| `popover` + anchor positioning | developer.mozilla.org/…/Popover_API | n/a | 0 B | Newly Available (popover ~Apr 2027 WA line; anchor ~June 2027 WA line) | Recommend w/ `@supports` |
| `text-wrap: balance` | developer.mozilla.org/…/text-wrap-style | n/a | 0 B | Newly Available (WA 2026-11-13) | Recommend, no gate needed |
| Cross-doc View Transitions | developer.mozilla.org/…/View_Transition_API | n/a | 0 B | NOT Baseline (no Firefox) | Recommend, safe no-op fallback |
| `light-dark()` | developer.mozilla.org/…/light-dark | n/a | 0 B | Newly Available (WA 2026-11-13) | Parked (DX-only refactor) |
| `loading-states` | htmx.org/extensions/loading-states | 0BSD | 5,551 B src / ~2.0 KB gz (est.) | n/a | Consider after `:has()` |
| `response-targets` | htmx.org/extensions/response-targets | 0BSD | 3,740 B src / ~1.3 KB gz (est.) | n/a | **Recommend (top htmx-ext pick)** |
| `preload` | htmx.org/extensions/preload | 0BSD | 14,099 B src / ~4.5 KB gz (est.) | n/a | Recommend, lower priority (weight) |
| `idiomorph` (idiomorph-ext) | github.com/bigskysoftware/idiomorph | 0BSD | 10,153 B min / ~3.5 KB gz (est.) | n/a | **Recommend (top vendor-JS pick)** |
| `<output>` element | developer.mozilla.org/…/output | n/a | 0 B | Widely Available (universal) | Recommend |
| reduced-motion `change` listener | developer.mozilla.org/…/change_event | n/a | ~4 LOC | Widely Available (universal) | Recommend (bug fix) |
| `animation-timeline: scroll()/view()` | developer.mozilla.org/…/animation-timeline | n/a | 0 B | NOT Baseline (Firefox flag-gated) | Parked |
| `@property` | developer.mozilla.org/…/@property | n/a | 0 B | Newly Available (WA ~Jan 2027) | Parked |
| `interpolate-size` | developer.mozilla.org/…/interpolate-size | n/a | 0 B | Not yet trackable cross-browser | Parked (watch-list) |
| JetBrains Mono subset | github.com/JetBrains/JetBrainsMono | OFL-1.1 | 92,380 B full charset (subset unmeasured) | n/a | Rejected |

---

## 4. Themes

**CSS APIs that reached Baseline in 2022–2026 close most of arXMCP's underdeveloped-surface
list at zero JS bytes** — `@container` fixes the measured 1251px-input layout defect,
`:has()` and `:user-invalid` add feedback/validation states the stylesheet has literally
never had (`app.css` has zero `:invalid` rules and zero `transition` properties in 370
lines), and `<dialog>` replaces the single most "un-designed" moment in the product (native
`window.confirm()`) for free. **A second, smaller theme: htmx extensions are the correct lane
for anything that needs to be genuinely stateful across a request lifecycle** (loading
paths, response-target routing) rather than purely presentational — but `response-targets`'s
value here is specifically that it DELETES existing duplicated code (6 copies of the same
inline JS) rather than adding new surface, which is the safest kind of dependency to accept.
**A third theme, worth flagging to the synthesizer explicitly: several strong candidates
(`popover`, anchor positioning, `field-sizing`, `light-dark()`) are "Newly Available" in
2026, not yet "Widely Available"** — real, shippable, and correctly `@supports`-gated, but
the synthesizer should not conflate a marketing blog's loose "Baseline 2026!" framing with
MDN's stricter Widely-Available bar; this brief cites the actual 30-month-clock dates where
findable, and flags the ones still short of the line.

---

## 5. arXMCP already has

Vendored / native today (`server/frontend/static/`, verified against `VENDORED.md` +
direct file reads, 2026-08-03):

- **`htmx.min.js` 2.0.10** (0BSD) — confirmed via `registry.npmjs.org/htmx.org/latest`
  this run: **2.0.10 IS the current latest published version.** No upgrade candidate exists
  — do not propose one.
- **`json-enc.js`** — project-authored (not vendored), implementing htmx 2.x's
  `encodeParameters` hook. Deliberately in-repo rather than vendored, per its own header
  comment, "so there is no unverifiable upstream version to pin." This exact reasoning is
  precedent for the license-provenance note on the htmx-extensions candidates above (§2) —
  arXMCP has already made this call once.
- **`favicon.svg`** — project-authored SVG, not vendored.
- **View Transitions (same-document, htmx-swap)** — `base.html:38-45` +
  `app.css:352-355`, gated on `prefers-reduced-motion`. Worth a note: Firefox 144 completed
  the cross-browser set for SAME-document view transitions very recently (per live search
  this run) — arXMCP's existing usage just became Baseline Newly Available across all three
  engines, having previously run ahead of Firefox support. No action needed; noted for
  context.
- **`:focus-visible`, skip-link, dark-mode token block, `prefers-reduced-motion` universal
  gate, `tabular-nums`, `color-mix()` hover, `color-scheme: light dark`** — all SHIPPED
  (`ui-attractive-polish-m1..m5`); confirmed present by direct read of `app.css` this run.
  **Do not re-propose any of these as net-new** — `arxmcp-design-system.md` §7's "Already
  SHIPPED" table is accurate as of this run.
- **CSS custom properties (8 tokens)** at `:root` (`app.css:4-19`) + dark override
  (`:242-291`) — the entire token system. Any new token this brief's candidates introduce
  (none require one) would need to land here, not a parallel system.

---

## 6. Out of scope / parking lot

The user asked for libraries that give an "interactive feel" in the vocabulary of
Tailwind/shadcn — here is why each of the automatic-BLOCKER npm libraries a generic scout
would name is off the table, named explicitly so the user has a direct answer:

| Library | Why it's a BLOCKER here |
|---|---|
| **React / Vue / Svelte** | Requires an SPA architecture + a build step; arXMCP is server-rendered Jinja2 with zero client-side routing (CLAUDE.md §4.7, `arxmcp-design-system.md` §9 lock #1). |
| **Tailwind CSS / PostCSS** | Requires a build chain to compile utility classes; `app.css` is hand-authored and shipped as-is, no compile step exists in the deploy path. |
| **shadcn/ui** | Copy-paste components ARE React + Tailwind under the hood — inherits both blockers above; also requires Radix as a runtime dependency (npm-installable). |
| **Radix UI Primitives** | npm-installable React components; no React runtime exists here. |
| **Framer Motion** (`motion/react`) | npm-installable, React-only (`motion/react` import path), ~40 KB min+gz — both the framework dependency AND the CDN-free constraint (`script-src` has no external origin) rule it out. |
| **GSAP / anime.js / Motion One** | All are npm-installable (or require a `<script src="https://cdn...">` for non-bundled use, which `CONTENT_SECURITY_POLICY_UI`'s `script-src 'self' 'unsafe-inline'` blocks outright — no external origin is allow-listed). A vendored single-file copy of one of these is theoretically CSP-legal, but the motion-jobs test (motion-vocabulary §0) doesn't currently name a job any of arXMCP's CANDs above can't already serve with native CSS transitions/keyframes — no motion gap exists that justifies a ~14-70 KB gz animation ENGINE on an S-2 tool surface where the house thesis (`arxmcp-design-system.md` §9) explicitly favors "CSS transitions + htmx swap semantics, never a JS animation engine." |
| **TanStack Table / TanStack Query** | npm-installable; the console has no client-side data-fetching layer to manage — htmx fragment swaps ARE the state-sync mechanism already. |
| **cmdk / Raycast-style command palette libs** | npm-installable (React), AND arguably the wrong solve — `arxmcp-design-system.md` §7's actual named gap is "`/` or Cmd-K to focus the URL-paste input," a ONE-element focus jump, not a searchable multi-command palette. A ~10-line vanilla `keydown` listener (0 bytes, pattern-lift, not a library) solves the named gap; a full command-palette library would be scope creep against the "quiet instrument panel" house thesis (BAN-1: no manufactured chrome). Not proposed as a CAND above because it's a JS pattern, not a library decision — flagging here so the synthesizer doesn't independently reach for `cmdk`. |
| **Sonner / toast libraries** | npm-installable; also a thesis mismatch — arXMCP's existing `aria-live` regions + inline `pre.error` blocks already serve the "did my action work" job inline, next to the control that triggered it. A floating toast stack would be a NEW UI region the "badge soup" anti-pattern (`arxmcp-design-system.md` BAN-7/BAN-11) explicitly warns against for the operability badge; the same reasoning extends to a general toast system. |
| **Lucide / Phosphor icon sets** | Typically consumed via an npm package or a webfont/icon-font CDN; a single-file inline SVG sprite IS technically vendor-able, but no icon gap was identified in this pass — arXMCP's UI is currently text-label-only buttons (Rename/Delete/Save/Discover/Add/Upload/Remove), which fits the "quiet instrument, typographic discipline, not chrome" thesis. Not proposed. |
| **`morphdom` (via `htmx-ext-morphdom-swap`)** | Investigated and rejected in favor of `idiomorph` (CAND-13): `morphdom-swap.js` itself is only 596 bytes because it's a thin wrapper requiring the separate `morphdom` core library to be vendored as a SECOND file — `idiomorph` ships as one self-contained 10,153-byte minified file with the same 0BSD license as the rest of the htmx family (same author). One file beats two for the same job. |
| **anime.js as the "sanctioned default" per the flat `frontend-uplift-motion-vocabulary.md` §0/§10** | That canon is a cross-repo, React-project-oriented default and does NOT apply here — `arxmcp-design-system.md` §9's house thesis explicitly overrides it for this repo: "Motion earns its place only by naming a job... served by CSS transitions + htmx swap semantics, never a JS animation engine." Flagging explicitly because the flat canon's §2/§10 tables (read per this run's Phase-1 instructions) are the GENERIC pipeline registry, not arXMCP-specific — every library named there (Tailwind, Radix, shadcn, Tremor, Framer Motion, GSAP, anime.js, Lucide, Phosphor, Sonner, Vaul, cmdk, TanStack Table/Query, React Aria) is npm-installable and is an automatic Phase-3 BLOCKER for this repo without exception. The overlay doc (`arxmcp-design-system.md`) is the authority a run in THIS repo must follow. |

