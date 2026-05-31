# Inspiration-scout brief — 2026-05-ui-polish

**Scout:** frontend-uplift-inspiration-scout
**Date:** 2026-05-30
**Uplift ID:** 2026-05-ui-polish
**Phase:** 1 — Discover
**Scope summary:** make arXMCP's loopback-only `/ui/` operator console
(3 Jinja2 templates + 126-line CSS + vendored htmx 2.0.10, light-mode-fixed,
zero `prefers-reduced-motion` / `:focus-visible` / `aria-live` / skip-link
discipline) more attractive and less bare-bones. Biased toward foundational
a11y baselines first, then visual polish via pure-CSS APIs / native Web APIs
/ vendored single-file drops only. **Hard constraint:** CLAUDE.md §4.7 no
npm / no Node / no SPA / no bundler.

---

## 1. TL;DR

The top-3 patterns worth borrowing — in priority order — are (1) **the
scholarly metadata strip** (the `<dl class="meta">` block in
`notebook_detail.html:41-69` is arXMCP's closest analogue to ar5iv's
author-affiliation-classification strip and Linear's issue-detail metadata,
but it currently reads as a bare definition list rather than a typed
"properties strip"); (2) **the a11y-baseline triad** of `:focus-visible`
+ `prefers-reduced-motion` gate + `aria-live` regions on the existing
`#display-name-block`, `#ingest-status`, `#papers-tbody` swap targets,
all of which arXMCP omits today and all of which are zero-cost
pure-CSS / native-API additions; and (3) **htmx-native loading-state
choreography** — the `htmx-request` / `htmx-swapping` / `htmx-settling`
class hooks already fire on every `hx-post` / `hx-patch` / `hx-delete` in
`notebook_detail.html` (rename form, URL paste, upload card, ingest
trigger, Delete buttons) but the CSS doesn't react to any of them, so
operators get zero visual feedback between click and the page-reload that
follows. The unifying thematic shift: **every dense-info operator surface
on the 2026 SOTA list — ar5iv, arXiv abstract pages, Linear, Vercel,
Raycast, Stripe Docs, Distill — converges on a "live, scannable, quietly
animated, keyboard-honest" tone**, and arXMCP today expresses none of it
because the CSS is purely static and treats htmx as a black box.

---

## 2. Pattern candidates

### CAND-1 — Scholarly metadata strip (typed properties, not bare `<dl>`)

- **Source platform:** arXiv abstract page (e.g. `arxiv.org/abs/<id>`),
  ar5iv paper header, zbMATH entry header.
- **Public evidence:**
  - arXiv abstract layout: `https://arxiv.org/abs/2604.00001` (the
    metadata strip — submission timeline, MSC classification tags,
    license badge, action buttons "View PDF / HTML / TeX Source" — all
    rendered as a *visually-typed properties block*, not a generic
    definition list).
  - ar5iv header (also rendered via the same scholarly conventions):
    `https://ar5iv.labs.arxiv.org/`.
- **What makes it good:** scholarly metadata uses (a) **chip / pill
  styling on classification tags** so they stand out as distinct typed
  values rather than free-text strings, (b) **monospace for identifiers**
  (arXiv ID, DOI, version) so they read as machine-typed not prose, and
  (c) **prominent action-button row** (PDF / HTML / TeX Source on arXiv;
  these are the "verbs" of the page). The result is a strip that an
  operator scans in <1s rather than reading line-by-line. Today
  `notebook_detail.html:41-69` puts `lancedb_path`, `created_at`, parse
  status, and last-indexed all into a 2-column `<dl>` with no typing
  cues — the parse-status badge is the *only* visually-typed value in
  the whole strip.
- **Motion vocabulary primitives:** none required (this is static
  styling); optionally `[MOT-14 data-tick-flash]` on the "Last
  indexed" `<time>` when an ingest finishes.
- **Where it would fit in arXMCP:**
  - `frontend/templates/notebook_detail.html:41-69` — the `<dl
    class="meta">` block. Wrap each `<dd>` value in a typed span
    (`.meta-value--mono` for the path, `.meta-value--time` for
    timestamps, the existing `.status-badge` for parse status). Add
    `tabular-nums` (see CAND-7) on timestamps.
  - `frontend/static/app.css:90-92` — extend the existing
    `dl.meta` rule with `.meta-value--mono { font-family:
    var(--mono); }` and `.meta-value--time { font-variant-numeric:
    tabular-nums; color: #444; }`. Zero new tokens; uses existing
    `--mono`.
- **arXMCP-positioning:** operator-surface only (arXMCP has no
  marketing surface; the README is the only public face).

### CAND-2 — Universal `:focus-visible` baseline ring

- **Source platform:** WebAIM, MDN, Primer (GitHub design system),
  Vercel Geist.
- **Public evidence:**
  - MDN: `https://developer.mozilla.org/en-US/docs/Web/CSS/:focus-visible`
    (Baseline Widely Available, March 2022, all modern browsers).
  - WCAG 2.1 SC 1.4.11 (non-text contrast 3:1) is the binding spec.
  - Primer foundations: `https://primer.style/foundations/color` (focus
    ring is one of Primer's named pattern-layer tokens).
- **What makes it good:** `:focus-visible` (vs `:focus`) suppresses the
  ring on mouse clicks but shows it on Tab navigation — solves the
  "designers hate focus rings / a11y demands focus rings" tension
  without compromise. Costs ~6 lines of CSS for the entire site.
  arXMCP today has **zero** `:focus-visible` styling — browser-default
  outlines only, which on macOS Safari is a thin grey ring on form
  inputs and *nothing* on `<button>` / `<a class="button">` elements,
  i.e. arXMCP's destructive Delete / Remove buttons have NO visible
  keyboard-focus indicator. That is a categorical a11y regression.
- **Motion vocabulary primitives:** `[MOT-34 focus-visible-glow]` —
  cited in motion-vocabulary.md §4 as a baseline gap.
- **Where it would fit in arXMCP:**
  - `frontend/static/app.css` (append after the
    `.status-badge--down` rule at line 126). Single global block
    targeting `:focus-visible` on `a`, `button`, `input`, `select`,
    `textarea`, plus an explicit-override for `.button` / `.danger`
    using `outline: 2px solid var(--accent); outline-offset: 2px;`
    (already the recommended pattern in the design-system §7).
- **arXMCP-positioning:** operator-surface (a11y baseline; non-negotiable).

### CAND-3 — `prefers-reduced-motion` global gate (prerequisite)

- **Source platform:** WCAG 2.1, MDN, every 2026 design system worth
  citing (Linear, Vercel, Stripe, GitHub Primer all gate motion).
- **Public evidence:**
  - MDN:
    `https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion`
    (Baseline Widely Available since Jan 2020).
  - WCAG 2.1 SC 2.3.3 (Animation from Interactions, AAA — but the
    media query is widely treated as AA-baseline by 2026 design
    systems).
- **What makes it good:** the standard pattern is to put all
  transitions / animations INSIDE `@media (prefers-reduced-motion:
  no-preference) { … }` so that operators with motion sensitivity
  (vestibular disorders) get a still UI by default. arXMCP today
  has zero `@media (prefers-reduced-motion: …)` blocks AND no
  animations either — but as soon as ANY uplift candidate lands a
  transition (CAND-4, CAND-5, CAND-9, CAND-10 all introduce one),
  the gate becomes a prerequisite. **Adopting the gate is itself
  the lowest-effort candidate in this brief and unblocks the
  others.**
- **Motion vocabulary primitives:** wraps ALL of `[MOT-1
  fade-in]`, `[MOT-3 stagger-reveal]`, `[MOT-13 skeleton-shimmer]`,
  `[MOT-50 htmx-swap-fade]`. Cited as `[MOT-NO-5
  continuous-animation-without-prefers-reduced-motion-fallback]` in
  motion-vocabulary §8.
- **Where it would fit in arXMCP:**
  - `frontend/static/app.css` — establish a single
    `@media (prefers-reduced-motion: no-preference) { … }` block
    near the top, immediately after `:root` (after line 13). All
    subsequent transition / animation candidates live inside this
    block.
- **arXMCP-positioning:** operator-surface (a11y prerequisite for
  every other motion candidate).

### CAND-4 — htmx-request / htmx-swapping loading-state choreography

- **Source platform:** htmx core CSS hooks (no extension needed) +
  the official `loading-states` htmx extension as an optional richer
  layer.
- **Public evidence:**
  - htmx CSS classes:
    `https://htmx.org/docs/#css_classes` documents the canonical
    `htmx-request` / `htmx-swapping` / `htmx-settling` /
    `htmx-added` classes that htmx applies during a request
    lifecycle.
  - Optional vendored extension:
    `https://htmx.org/extensions/` (loading-states extension —
    single-file vendor drop, paired with class-tools and
    response-targets).
- **What makes it good:** every `hx-post` / `hx-patch` / `hx-delete`
  in `notebook_detail.html` already gets the `htmx-request` class
  applied automatically — but `app.css` has zero rules targeting
  it. So clicking "Ingest now", "Rename", "Add", "Upload", "Remove"
  produces NO visual feedback between click and the
  `location.reload()` callback that follows ~500ms later. SOTA dev
  tools (Vercel, Linear, Raycast) all show *immediate* button state
  changes on click — even a 200ms button-dim is enough to make a
  click feel acknowledged. arXMCP today has nothing.
- **Motion vocabulary primitives:** `[MOT-13 skeleton-shimmer]`
  (optional), `[MOT-33 icon-spin-on-action]` (the ingest button
  while in flight), `[MOT-50 htmx-swap-fade]` (the
  `#display-name-block`, `#ingest-status`, `#papers-tbody` swap
  targets).
- **Where it would fit in arXMCP:**
  - `frontend/static/app.css` — append `button.htmx-request {
    opacity: 0.65; cursor: progress; }` plus a tiny inline-SVG
    spinner appended via `::after` (CSS-only, no JS). All gated by
    CAND-3.
  - Optional: vendor `htmx-ext-loading-states.js` (single file,
    BSD-2-Clause, ~3 KB min+gz per htmx-extensions index) into
    `frontend/static/` and add `hx-ext="loading-states"` to
    `<body>` for richer control (e.g. disabling the form during
    upload).
- **arXMCP-positioning:** operator-surface; pair with CAND-9 for
  cohesive click-to-resolution choreography.

### CAND-5 — `aria-live` regions on htmx swap targets

- **Source platform:** MDN, WAI-ARIA Authoring Practices, every
  modern SPA-style app that does in-place updates (the canonical
  htmx + a11y pattern).
- **Public evidence:**
  - MDN:
    `https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Attributes/aria-live`
    (Baseline Widely Available; `aria-live="polite"` is the
    default recommendation for content swaps).
  - The article's "HTMX Fragment Swaps" section explicitly
    documents `aria-live="polite" aria-relevant="additions text"`
    as the canonical pairing.
- **What makes it good:** htmx swaps the `#display-name-block`
  (rename), `#ingest-status` (every 2s), and `#papers-tbody`
  (upload appends a row) entirely silently to screen readers
  today. `index.html:28` already uses `aria-live="polite"` on
  `#create-error` (which is correct), but the OTHER swap targets
  don't. Adding `aria-live="polite"` to the existing swap-target
  IDs in `notebook_detail.html` costs 4 attribute additions, zero
  CSS, and gives screen-reader operators parity with sighted
  operators.
- **Motion vocabulary primitives:** none (purely semantic).
- **Where it would fit in arXMCP:**
  - `frontend/templates/notebook_detail.html:15` — add
    `aria-live="polite"` to `#display-name-block`.
  - `frontend/templates/notebook_detail.html:161-168` — add
    `aria-live="polite"` to `#ingest-status` (especially
    important — the 2s poll is the most "alive" surface and
    screen readers see nothing).
  - `frontend/templates/notebook_detail.html:180` — add
    `aria-live="polite"` to `#papers-tbody` so that after a
    successful upload (which `beforeend`-swaps a new `<tr>`),
    screen readers announce the new paper.
- **arXMCP-positioning:** operator-surface (a11y baseline).

### CAND-6 — `prefers-color-scheme` dark-mode pairing

- **Source platform:** Linear, Vercel Geist, Zed, Stripe Docs,
  GitHub Primer — every 2026 operator dashboard ships dark mode by
  default. Zed marketing-page testimonial: "deep backgrounds with
  bright text, reducing eye strain during extended coding
  sessions" (`https://zed.dev/`).
- **Public evidence:**
  - MDN:
    `https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-color-scheme`
    (Baseline Widely Available).
  - Primer foundations: `https://primer.style/foundations/color`
    (semantic naming pattern — `--fgColor-danger` is the same
    token in light AND dark mode, with different concrete values).
  - Vercel Geist: `https://vercel.com/design/colors` (10-color
    scale with paired light/dark values).
- **What makes it good:** arXMCP operators very likely use
  dark-mode IDEs / terminals / Slack — landing on a light-mode UI
  is a visible flash and a small but visible "this is a toy"
  signal. The native pattern (no JS, no toggle, no user prefs
  storage) is `@media (prefers-color-scheme: dark) { :root { … } }`
  with a second token-block at `:root`. That preserves the
  8-variable token system from §4 of the design-system doc
  (`--fg`, `--bg`, `--card-bg`, `--border`, `--accent`,
  `--danger`, `--error-bg`, `--mono`) — same names, different
  values. The four `.status-badge--*` rules at app.css:123-126 use
  hardcoded colors (`#e6f4ea`, `#1a7f37`, etc.) and would need
  dark-mode pairs too.
- **Motion vocabulary primitives:** none (token swap; no
  motion).
- **Where it would fit in arXMCP:**
  - `frontend/static/app.css:4-13` — keep the light-mode tokens
    at `:root`. Add a parallel
    `@media (prefers-color-scheme: dark) { :root { --fg: #e8e8e8;
    --bg: #0d1117; --card-bg: #161b22; --border: #30363d;
    --accent: #58a6ff; --danger: #f85149; --error-bg: #2a1a18;
    --mono: …; } }` block. Dark palette anchored to GitHub
    Primer's dark scale (proven a11y-compliant).
  - `frontend/static/app.css:96` — the `th { background:
    #f0f0f0; }` hardcoded color needs to become `var(--th-bg)`
    or move inside the dark block.
  - `frontend/static/app.css:123-126` — the four
    `.status-badge--*` rules need dark pairs (the existing
    light-mode greens/yellows have low contrast on a dark
    background).
- **arXMCP-positioning:** operator-surface (high-impact polish; OS
  flash on session start is the most visible "untouched" signal).

### CAND-7 — `tabular-nums` on timestamps and counts

- **Source platform:** Vercel dashboard (log timestamps), Linear
  (issue counts), Stripe Docs (HTTP status codes), every modern
  scholarly-publication site rendering DOIs / arXiv IDs / dates.
- **Public evidence:**
  - MDN:
    `https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric`
    (Baseline Widely Available since Jan 2020). The `tabular-nums`
    value gives all digits equal width.
  - Vercel marketing snippet shows log entries like
    `APR 26 15:54:21.12` — that alignment is impossible without
    `tabular-nums`.
- **What makes it good:** arXMCP renders `<time>{{
  notebook.created_at }}</time>` in two table columns
  (`index.html:46`, `notebook_detail.html:184`) plus a freshness
  `<time>` line (`notebook_detail.html:63`). All in the body font,
  all jittery. Operators scanning a paper-list table to find "the
  one added yesterday at ~2pm" need vertical-aligned digits. Costs
  1 CSS rule.
- **Motion vocabulary primitives:** none.
- **Where it would fit in arXMCP:**
  - `frontend/static/app.css` — append `time, td code,
    .meta-value--time { font-variant-numeric: tabular-nums; }` (or
    attach to the `<time>` element directly — works on the system
    font stack arXMCP uses since modern system fonts ship the
    `tnum` feature).
- **arXMCP-positioning:** operator-surface.

### CAND-8 — Skip-to-main-content link

- **Source platform:** WebAIM, WAI-ARIA Authoring Practices, every
  WCAG 2.1 AA site.
- **Public evidence:**
  - WebAIM: `https://webaim.org/techniques/skipnav/` ("Make the
    skip link one of the first items keyboard users access via
    Tab; visually-hidden by default, visible on focus").
- **What makes it good:** arXMCP's header has 1 `<a>` (the
  "arXMCP notebooks" home link in `base.html:49`) + the badge in
  the footer is `hx-get`-driven and won't trap focus, so the
  Tab-burden today is small. BUT: as soon as a hypothetical
  future candidate adds a top nav with notebook switcher / search
  / settings, the skip-link becomes the prerequisite a11y gate.
  Cost: ~6 lines of CSS + 1 line of HTML in `base.html`. Ship now
  even though the surface is small — it's a cheap signal of "this
  site cares about keyboard users" and unblocks every future nav
  expansion.
- **Motion vocabulary primitives:** `[MOT-1 fade-in]` (optional,
  on the slide-down focus reveal); honors CAND-3.
- **Where it would fit in arXMCP:**
  - `frontend/templates/base.html:47` — `<body>` first child
    becomes `<a class="skip-link" href="#main">Skip to main
    content</a>`. The existing `<main>` at `base.html:52` gets
    `id="main"`.
  - `frontend/static/app.css` — append `.skip-link { position:
    absolute; left: -9999px; } .skip-link:focus-visible { left:
    1rem; top: 1rem; z-index: 100; background: var(--accent);
    color: #fff; padding: 0.5rem 1rem; border-radius: 4px; }`.
- **arXMCP-positioning:** operator-surface (a11y baseline).

### CAND-9 — View Transitions API on htmx swaps

- **Source platform:** native browser API (Chrome + Safari widely
  available; Firefox in dev). Most-cited as the "SPA-feel without
  a SPA" 2026 pattern.
- **Public evidence:**
  - MDN:
    `https://developer.mozilla.org/en-US/docs/Web/API/View_Transitions_API`
    (Baseline status varies — same-document is Widely Available in
    Chrome/Safari; Firefox graceful-degrades to a no-op `if
    (document.startViewTransition)` check).
- **What makes it good:** the View Transitions API takes any DOM
  mutation wrapped in `document.startViewTransition(() => { … })`
  and renders a snapshot crossfade between old and new states.
  Pairs with htmx via the `htmx:beforeSwap` event — wrap the swap
  in `document.startViewTransition` and the rename, ingest-status
  poll, paper-row-append, and paper-row-delete all get a smooth
  ~200ms crossfade for free. Zero vendor weight (native). Where
  unsupported (Firefox today), the swap behaves exactly as it
  does now — no regression. The current swaps look "janky"
  (insta-replace with no animation); this is the canonical 2026
  fix.
- **Motion vocabulary primitives:** `[MOT-52
  view-transitions-api]` directly; subsumes `[MOT-50
  htmx-swap-fade]`. Gated by CAND-3.
- **Where it would fit in arXMCP:**
  - `frontend/templates/base.html:18-45` — the existing JSON-shim
    script block is the right home for a second tiny listener.
    A proper integration needs the htmx-recommended pattern (use
    `htmx:beforeSwap` to capture, then call
    `document.startViewTransition` around the actual swap; check
    htmx 2.x docs for exact event/API). The audit-widening
    impact is non-zero (adds ~5 lines of inline JS to
    `base.html`) — flag for the UI security audit at
    `chris-dare-dev/arXMCP#9`.
- **arXMCP-positioning:** operator-surface (high polish, low cost,
  audit-widening flag).

### CAND-10 — Card lift-on-hover + border-on-hover for the notebook tile list

- **Source platform:** Linear (issue tiles), Vercel (project
  cards), Raycast (extension cards in the gallery), GitHub
  (repo-list rows).
- **Public evidence:**
  - Raycast extension grid (visible on `https://www.raycast.com/`)
    — repeating card pattern with thumbnail+title+description,
    hover lifts and shifts border.
  - Linear's general design language emphasizes "smart-list
    density, micro-animation tempo" (source-registry §1b).
- **What makes it good:** arXMCP's notebook list at
  `index.html:37-60` is rendered as `<table class="notebooks">` —
  purely-tabular, no hover affordance, the entire row is one big
  inert rectangle with two clickable elements (`<a
  class="button">Open</a>` and `<button class="danger">Remove</button>`).
  Operators clicking through ~10 notebooks in a session need
  *some* scanability cue. The minimal pattern: `tr:hover {
  background: <subtle> }` + `tr:focus-within { outline: 2px solid
  var(--accent); }` (the whole row reacts when one of its
  children is keyboard-focused). Gives "this row is selectable"
  feel without adding any new DOM. Could also extend to
  `notebook_detail.html:180` `#papers-tbody` rows.
- **Motion vocabulary primitives:** `[MOT-30 lift-on-hover]`
  (light variant — no `translateY`, just background+border on a
  table row); `[MOT-32 border-on-hover]`. Gated by CAND-3.
- **Where it would fit in arXMCP:**
  - `frontend/static/app.css:94-97` — extend the table rules:
    `tbody tr { transition: background 120ms ease; } tbody
    tr:hover { background: color-mix(in srgb, var(--accent) 6%,
    transparent); } tbody tr:focus-within { outline: 2px solid
    var(--accent); outline-offset: -2px; }`. Uses `color-mix()`
    (Baseline Widely Available) so no new tokens needed.
- **arXMCP-positioning:** operator-surface.

### CAND-11 — Status-pill discipline extended to notebook kind / ingest run-state

- **Source platform:** Vercel deployment dashboard
  (Ready/Building/Error pills), Linear (issue-status pills),
  GitHub (workflow-run status). All converge on the same
  vocabulary.
- **Public evidence:**
  - Vercel Geist: `https://vercel.com/design/colors` (the
    "10-color scale" + dashboard log examples showing tier
    classification with hyper-readable pill styling).
  - Linear's status-row patterns (visible on
    `https://linear.app/`).
- **What makes it good:** arXMCP *already* has the
  `.status-badge` + `.status-badge--ok|warn|ops-warn|down`
  vocabulary (`app.css:114-126`) — but uses it in only two
  places: the parse-status badge (`notebook_detail.html:52`) and
  the footer operability badge (`base.html:65-67`). The
  notebook-kind ("arxiv" vs "textbook") and the ingest run-state
  (`latest_run.status` shown as bare `.hint` text at
  `notebook_detail.html:64`) are typed enums that should ALSO be
  pills — same vocabulary, same accessibility properties.
  Underdeveloped per design-system §7: "no visual differentiation
  between `arxiv`-kind and `textbook`-kind notebooks in the
  list".
- **Motion vocabulary primitives:** none required; optionally
  `[MOT-10 breathing-glow]` on a `running`-state ingest pill (the
  one running poll). Gated by CAND-3.
- **Where it would fit in arXMCP:**
  - `frontend/templates/index.html:43-46` — add a column or
    inline-pill on each notebook row showing `nb.notebook_kind`
    using the existing `.status-badge` classes (with a new
    `--ops-info` modifier if a neutral-blue is wanted; or reuse
    `--ops-warn` for "textbook" since that's the more-config
    case).
  - `frontend/templates/notebook_detail.html:63-65` — wrap
    `{{ latest_run.status }}` in `<span class="status-badge
    status-badge--{{ ingest_status_css }}">…</span>`. Add the
    template-helper in `server/routes/ui.py` (mirroring the
    existing `parse_status_css`).
  - `frontend/static/app.css:114-126` — extend the
    `.status-badge--*` set if additional states are needed
    (e.g. `--info` for `arxiv`-kind).
- **arXMCP-positioning:** operator-surface.

### CAND-12 — Empty-state richness (illustration optional; copy + CTA mandatory)

- **Source platform:** Linear empty-state inbox illustrations,
  GitHub empty-repo "Initialize this repository" CTA, Vercel
  empty-project state.
- **Public evidence:**
  - Linear's empty-state pattern is widely documented in
    design-blog roundups; canonical primary signal is the Linear
    app itself.
  - Vercel's empty-project state is visible on the marketing
    homepage demo flow.
- **What makes it good:** arXMCP's three empty-states today are
  one-line italic paragraphs — `.empty` class (`app.css:52`):
  "No notebooks yet. Create one above." / "No papers yet. Add one
  above." / "Loading ingest status…" The first-run operator just
  installed arXMCP, opens `/ui/`, sees a 1-line message, has no
  sense of the workflow. A two-step empty-state (`<p>` + a hint
  with a code-block showing the expected slug pattern + a "see
  install.md" link) is cheap and closes the discovery gap.
  **Note:** the design-system §7 candidate list explicitly
  mentions "no empty-state illustration / micro-interaction" —
  flagging here that an SVG illustration is OPTIONAL (requires a
  designer-asset budget arXMCP doesn't have) and the copy+CTA
  upgrade is the actually-deliverable subset.
- **Motion vocabulary primitives:** `[MOT-1 fade-in]` on the
  empty-state body (subtle); gated by CAND-3.
- **Where it would fit in arXMCP:**
  - `frontend/templates/index.html:34-35` — extend the `<p
    class="empty">` with a `<p class="hint">` showing the slug
    pattern + a code-styled example slug.
  - `frontend/templates/notebook_detail.html:174-175` — extend
    similarly with a "drop a PDF on the upload card or paste an
    arXiv URL above" cue.
  - `frontend/static/app.css:52` — extend `.empty` with sibling
    `.empty + .hint` spacing.
- **arXMCP-positioning:** operator-surface (first-run discovery).

---

## 3. Sources reviewed

| Platform | URL | What was actually read | High-signal? |
|---|---|---|---|
| ar5iv (paper render) | `https://ar5iv.labs.arxiv.org/html/2604.00001` | Full page layout — header, author/affiliation strip, citation markers, math rendering | YES (direct domain match) |
| arXiv abstract | `https://arxiv.org/abs/2604.00001` | Metadata strip, action buttons (PDF/HTML/TeX Source), classification tags | YES |
| Distill.pub | `https://distill.pub/2020/communicating-with-interactive-articles/` | Typography, breathing-room density, margin-note pattern | YES |
| Linear (method page) | `https://linear.app/method` | Generic method-page copy — not visual signal; redirected back to source-registry's description | NO (page is copy-heavy, low-visual) |
| Raycast | `https://www.raycast.com/` | Marketing-page extension grid + keyboard-shortcut pattern | MEDIUM |
| Zed | `https://zed.dev/` | Marketing tone, dark-theme execution, density philosophy | MEDIUM (testimonial-driven) |
| Stripe Docs API | `https://docs.stripe.com/api` | Info architecture (not visual specifics) | LOW (text-only excerpt) |
| Observable | `https://observablehq.com/` | Cell-based document model, reactive-cell pattern | MEDIUM |
| Quanta Magazine | `https://www.quantamagazine.org/` | Scholarly-adjacent warmth via whitespace + restraint | MEDIUM |
| Vercel design | `https://vercel.com/design/colors` | Geist 10-color scale, status-pill discipline | YES |
| Primer (GitHub) | `https://primer.style/foundations/color` | Token-pattern semantic naming, focus-ring as named token | YES |
| NotebookLM | `https://notebooklm.google/` | Marketing-page title only — no design specifics | NO (page returned minimal content) |
| Cron | `https://www.cron.com/` | Marketing tagline only — no design specifics | NO (page returned minimal content) |
| Linear blog (scaling design system) | `https://linear.app/blog/scaling-the-linear-design-system` | 404 — page moved/removed | N/A |
| zbMATH | `https://zbmath.org/` | 403 — rate-limited / bot-blocked | N/A (substituted by arxiv.org abstract page) |
| MDN — `:focus-visible` | `https://developer.mozilla.org/en-US/docs/Web/CSS/:focus-visible` | Baseline, CSS recipe, WCAG 1.4.11 contrast spec | YES (spec) |
| MDN — `prefers-reduced-motion` | `https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion` | Baseline, no-preference gate pattern | YES (spec) |
| MDN — `aria-live` | `https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Attributes/aria-live` | Polite vs assertive, htmx swap pairing | YES (spec) |
| MDN — `font-variant-numeric` | `https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric` | `tabular-nums` for table/timestamp alignment | YES (spec) |
| MDN — View Transitions API | `https://developer.mozilla.org/en-US/docs/Web/API/View_Transitions_API` | `document.startViewTransition`, graceful-degrade pattern | YES (spec) |
| WebAIM skip nav | `https://webaim.org/techniques/skipnav/` | Visually-hidden / visible-on-focus pattern | YES |
| htmx extensions | `https://htmx.org/extensions/` | loading-states, class-tools, response-targets, morph, head-support — single-file vendor drops | YES |

---

## 4. Themes

Two themes converged across 2026 SOTA: **(A) "live, scannable, quietly
animated, keyboard-honest" tone** — every dense-info dev tool (Linear,
Vercel, Stripe Docs, Raycast, Zed) and every scholarly platform (arXiv
abstract, ar5iv, Quanta) gives an immediate visual response to every
click (state pills, focus rings, hover lifts, swap crossfades) and
suppresses motion for users who don't want it. arXMCP currently expresses
none of these — the CSS treats htmx as a black box (zero
`htmx-request` styling), and the only "live" surface is the footer
status badge. **(B) Native-platform-API parity is now the expected
baseline**, not a polish-tier upgrade — `:focus-visible`,
`prefers-reduced-motion`, `prefers-color-scheme`, `aria-live`,
`tabular-nums`, View Transitions are all Baseline Widely Available
(many since Jan 2020), all spec-stable, all zero-vendor-weight, and
ignoring them in 2026 reads as neglect rather than minimalism. The
arXMCP-specific synthesis: **borrow scholarly metadata-strip discipline
for the dense detail page, dev-tool status-pill choreography for the
list page, and the a11y-baseline triad as the universal floor that
unblocks everything else.**

---

## 5. Cross-reference to arXMCP (each candidate → specific file:line)

- **CAND-1 (scholarly metadata strip):** `frontend/templates/notebook_detail.html:41-69`
  (`<dl class="meta">`); `frontend/static/app.css:90-92` (extend
  `dl.meta`).
- **CAND-2 (`:focus-visible` baseline):** `frontend/static/app.css`
  append after line 126; targets ALL `button`, `a`, `input`,
  `select`, `textarea` — closes the design-system §7 gap.
- **CAND-3 (`prefers-reduced-motion` gate):** `frontend/static/app.css`
  insert near top after `:root` (after line 13); closes the
  design-system §7 gap; prerequisite for CAND-4, -8, -9, -10, -12.
- **CAND-4 (htmx loading-state CSS):** `frontend/static/app.css`
  append; targets the `htmx-request` class auto-applied on every
  `hx-post` / `hx-patch` / `hx-delete` in
  `frontend/templates/notebook_detail.html:13, 26, 49, 75, 92, 115, 147, 205`
  and `frontend/templates/index.html:13, 49`.
- **CAND-5 (`aria-live` on swap targets):**
  `frontend/templates/notebook_detail.html:15` (`#display-name-block`),
  `:161` (`#ingest-status`), `:180` (`#papers-tbody`). The
  existing `aria-live="polite"` on `#create-error`,
  `#paste-error`, `#upload-error`, `#ingest-error`, `#rename-error`
  is correct — leave alone.
- **CAND-6 (`prefers-color-scheme` dark mode):**
  `frontend/static/app.css:4-13` (extend `:root` with a paired
  dark block); `:96` (`th` background), `:123-126`
  (`.status-badge--*` colors) need dark pairs; closes
  design-system §7 gap.
- **CAND-7 (`tabular-nums`):** `frontend/static/app.css` append
  one rule; targets `<time>` (used in `index.html:46`,
  `notebook_detail.html:43, 63, 184`); closes design-system §7
  gap.
- **CAND-8 (skip-link):** `frontend/templates/base.html:47-52`
  (insert `<a class="skip-link">` as first body child; add
  `id="main"` to existing `<main>`); `frontend/static/app.css`
  append the `.skip-link` rule; closes design-system §7 gap.
- **CAND-9 (View Transitions on htmx swaps):**
  `frontend/templates/base.html:18-45` (extend the existing inline
  script block); audit-widening flag for
  `chris-dare-dev/arXMCP#9`.
- **CAND-10 (table-row hover/focus-within):**
  `frontend/static/app.css:94-97` (extend the existing `table`
  rules); applies to `table.notebooks` (`index.html:37`) and
  `table.papers` (`notebook_detail.html:176`).
- **CAND-11 (status-pill discipline extension):**
  `frontend/templates/index.html:43-46` (notebook-kind pill in the
  list row); `frontend/templates/notebook_detail.html:63-65`
  (ingest-status pill); `server/routes/ui.py` (mirror the
  existing `parse_status_css` template-helper); reuses existing
  `.status-badge` classes from `frontend/static/app.css:114-126`.
- **CAND-12 (empty-state richness):**
  `frontend/templates/index.html:34-35` and
  `frontend/templates/notebook_detail.html:174-175` (extend the
  `.empty` paragraph with a sibling `.hint`); closes design-system
  §7 gap.

---

## 6. Out of scope / parking lot

Patterns considered and **explicitly rejected** for this uplift:

- **Linear / Vercel command palette (Cmd-K).** The design-system §7
  list-row mentions "Cmd-K / `/` to focus the URL-paste input would
  mirror operator-console patterns from Linear / Raycast" — but this
  is a substantial new JS surface (focus-management, modal trap, ESC
  handling) and arXMCP today has 3 pages, no global search target,
  and the URL-paste input is already 1 tab-stop away on the detail
  page. **Defer until either a search/filter surface lands OR the
  notebook count grows past ~20.** Tracked as a future candidate;
  not in this uplift.
- **Distill.pub margin asides / two-column scholarly layout.** Beautiful
  pattern, but arXMCP's body content is form-driven (no long-form prose)
  — there's literally no margin-content to put in the aside. Out of
  scope until a future "help / about" surface exists.
- **Quanta-style hero imagery / illustration.** Marketing-surface pattern.
  arXMCP has no marketing surface; the README is the only public face.
- **NotebookLM source-list sidebar / chat-with-sources pattern.** This
  is the SHAPE arXMCP's MCP tool surface enables for upstream agents,
  but the `/ui/` console is a *notebook-management* tool, not a
  *chat-with-notebook* tool. Borrowing the sidebar style on
  `notebook_detail.html` would imply chat-with-this-notebook
  functionality that doesn't exist.
- **Auto-rotating notebook spotlight / carousel.** Anti-pattern
  `[MOT-NO-3 auto-rotating carousel for notebook content]` from
  motion-vocabulary §8.
- **Magnetic-cursor on Delete / Ingest buttons.** Anti-pattern
  `[MOT-NO-4 magnetic-cursor on operational buttons]` —
  accidental-click risk on destructive actions.
- **Confetti on successful ingest.** Anti-pattern `[MOT-NO-7
  confetti / celebration animations on operator actions]` — wrong
  tone for a research tool.
- **Parallax on the operator console.** Anti-pattern `[MOT-NO-2
  parallax on the operator console]` — motion sickness + zero
  information.
- **Tailwind / shadcn / Radix / Framer Motion / GSAP / Alpine.js
  + Tailwind combo.** All npm-installable; CLAUDE.md §4.7 hard
  block. Auto-BLOCKER in Phase 3.
- **A custom web font (Inter / IBM Plex / Source Serif).** Adds a
  network fetch + CSP `font-src` widening. The current
  `-apple-system, system-ui, …` stack at `app.css:18` is already
  excellent on macOS / Linux / Windows. Out of scope unless an
  operator explicitly asks for a brand-fonted UI.
- **A second vendored single-file CSS framework (picocss).** The
  126-line `app.css` is already smaller than picocss's smallest
  build; replacing the framework is a regression on file weight
  AND on the token system's intentional minimalism. Out of
  scope.
- **MathJax / KaTeX for math rendering.** arXMCP's `/ui/` doesn't
  render math (the ar5iv preview tab loads pre-rendered HTML
  under a tight CSP). Out of scope.
- **Auth / multi-user / OAuth.** Loopback-only design; the
  `SecFetchSiteMiddleware` + `OriginValidationMiddleware` triple
  defense is load-bearing. Re-pinned in design-system §8.

---

**End of brief.**
