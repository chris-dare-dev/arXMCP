# Challenge — `2026-05-ui-polish`

**Phase:** 3 — Challenge (frontend-uplift-challenger sub-agent)
**Date:** 2026-05-30
**Inputs:** synthesis catalog (25 candidates UPL-1..UPL-25) + 4 Phase-1 briefs.
**10-axis checklist applied:** no-build-chain, `prefers-reduced-motion`,
a11y regression, vendored weight, CSP, mobile, token discipline, effort
honesty, motion anti-patterns, sequencing.

---

## 1. Executive summary

**0 BLOCKER · 3 MAJOR · 8 MINOR · 14 NONE.** The synthesis is honest about
arXMCP's stack locks — no candidate proposes an npm-installable library
(synthesis §6 explicitly parks Tailwind/React/shadcn/Framer/Alpine), so the
automatic-BLOCKER trapdoor never fires. The genuine cost-side concerns are
concentrated in **(a)** the three CRITICAL bug-fixes (UPL-5, UPL-7, UPL-12)
which each widen the open UI security-audit surface (`chris-dare-dev/arXMCP#9`)
without that audit being a prerequisite, and **(b)** a few candidates whose
diagnostic story or effort sizing doesn't survive ground-checking against the
actual templates (UPL-5's claim that the JSON-shim produces a mis-shaped
PATCH body is contradicted by `notebook_detail.html:26-40` + `base.html:18-44`
— the rename form has exactly one named input, so the shim emits exactly
`{"display_name": "..."}` which IS the `NotebookRename` shape; the silent-
failure must originate elsewhere).

The dominant cross-cutting theme is **sequencing rigor**: UPL-1
(`prefers-reduced-motion` gate) and UPL-2 (`:focus-visible`) are correctly
identified as prerequisites for every motion / interaction candidate, but
several motion candidates (UPL-11, UPL-13, UPL-15, UPL-17, UPL-22) cite the
gate inside their sketch rather than declaring a hard dependency edge in
their Open-Questions block — Phase 4 prioritization MUST treat UPL-1/UPL-2
as a single landing pad that ships before any other motion-bearing
candidate, or the rectifier protocol will surface MOT-NO-5 violations.

---

## 2. BLOCKER findings

*(None.)* No candidate in the synthesis proposes an npm-installable
library, framework SPA, or build-chain artifact. CLAUDE.md §4.7 is intact.
Synthesis §6 explicitly enumerates the rejection set (Tailwind / shadcn /
Framer Motion / Recharts / Zustand / TanStack / Vite / Vue / Svelte /
Next.js / React / Alpine.js / picocss). This is the honest verdict — do
not manufacture a BLOCKER to look adversarial.

---

## 3. MAJOR findings

### UPL-5 — Fix silent rename failure (CRITICAL bug)

- **Severity:** MAJOR
- **Objections:**
  - **Effort honesty (axis 8):** The synthesis sketch claims three
    "independent" fixes are all required. Ground-checking against
    `frontend/templates/notebook_detail.html:26-40` and
    `frontend/templates/base.html:18-44`: the rename form has exactly ONE
    named input (`<input name="display_name">`) and the base.html
    JSON-shim collects `evt.detail.parameters` into a plain JSON object,
    so the actual emitted body is `{"display_name": "<value>"}` — which
    IS the canonical `NotebookRename` body shape per
    `server/routes/notebooks.py:215-226`. The 422 cause must be
    elsewhere (e.g. control-character strip on display-name producing
    422, or a downstream validator, or the swap target
    `#display-name-block` having gone stale across a prior swap). Fix
    (1) in the sketch ("audit shim against every PATCH/POST route") may
    be chasing a phantom; the real reproducer evidence (visual G1's
    `curl PATCH` comparison) isn't quoted enough to know.
  - **CSP impact + UI-audit surface (axis 5):** Sketch fix (1) touches
    the inline JSON-shim — that's modifying load-bearing inline JS
    inside the `'unsafe-inline'` allowance and explicitly widens
    `chris-dare-dev/arXMCP#9`. The synthesis flags it; that's good. But
    if the diagnostic is wrong (above), the audit-widening change is
    unnecessary risk.
  - **Effort honesty (axis 8) cont.:** Three independent fixes + an
    audit pass of every PATCH/POST route + a CSS rule revert + a new
    422-array unwrap path is realistically a MEDIUM (M), not the S the
    catalog claims. Three coupled changes touching the shim, the
    handler, and the CSS rule together is exactly the work shape that
    historically grew to a notebook-surface-expansion-m1-equivalent S/M.
- **Suggested scope adjustment:**
  - **v0:** reproduce the 422 with `curl PATCH` AND with the live
    htmx-form submission side-by-side. Capture the actual emitted
    payload via Network inspector. Confirm OR refute the shim-payload-
    mis-shape diagnostic BEFORE coding fix (1).
  - **v0 (regardless of (1)):** ship fix (2) — error-handler unwrap
    for FastAPI's `{detail: [...]}` array shape (the
    `.detail || t` collapses an array to `[object Object]` which a
    naive string-coerce drops). This fix is cheap (one JS expression
    in the `hx-on::htmx:response-error` attribute), independent, and
    addresses the user-visible silence regardless of root cause.
  - **v0:** ship fix (3) — drop `pre.error:empty { display: none }`
    from `app.css:110` + add `min-height: 1.2em` (already on the
    `pre.error` rule per `app.css:108`; verify min-height alone is
    enough without the `:empty { display:none }`).
  - **v1:** the broader JSON-shim audit, IF the v0 reproducer confirms
    the shape-mismatch diagnostic.
  - **Re-size to M, not S.**

### UPL-7 — HTML-render the `SecFetchSiteMiddleware` rejection (CRITICAL bug)

- **Severity:** MAJOR
- **Objections:**
  - **CSP impact + UI-audit surface (axis 5):** This candidate proposes
    Accept-header / UA-sniff content-negotiation INSIDE the Threat-5
    DNS-rebinding-defense middleware (`server/middleware.py::SecFetch
    SiteMiddleware`). Threat 5 is a SHIPPED defense from E13_S05; any
    code path that returns differential body content based on
    `Accept: text/html` from inside that middleware is exactly the
    kind of change the deferred UI security audit
    (`chris-dare-dev/arXMCP#9`) needs to greenlight FIRST — not in
    parallel. The synthesis notes "verify in the security audit" as an
    Open Question; that's not strong enough.
  - **A11y / sequencing (axis 10):** The HTML escape-hatch page would
    extend `base.html` (per the sketch), so it inherits the htmx
    script and the JSON-shim — but the rejection happens on the FIRST
    request, before the htmx-bound script has run. A static landing
    page is fine; the synthesis isn't wrong about that. But the
    "Continue to arXMCP notebooks" same-origin POST/GET will only
    succeed if the user-agent re-issues with `Sec-Fetch-Site:
    same-origin` — verify the form action triggers that header (it
    SHOULD, but it's the load-bearing assumption and isn't called out).
  - **Effort honesty (axis 8):** Sized S; realistic given the middleware
    surgery + new template + audit-coordination overhead is at least
    S, possibly M. The audit-coordination wait is the schedule killer,
    not the LOC.
- **Suggested scope adjustment:**
  - **v0:** ship a much smaller change — instead of HTML-vs-JSON
    content-negotiation IN the middleware, add a separate FastAPI
    exception handler that catches the rejection sentinel and renders
    HTML when `Accept: text/html` is present, leaving the middleware
    untouched. This is the standard FastAPI pattern (`@app.exception_
    handler`) and isolates the new HTML path from the security-critical
    middleware.
  - **v1:** the full content-negotiation refactor, post-audit.
  - **Re-size to M** if the v0 exception-handler split is taken;
    actually closer to S/M.

### UPL-12 — Convert `location.reload()` flows to in-place htmx swaps

- **Severity:** MAJOR
- **Objections:**
  - **CSP impact + UI-audit surface (axis 5):** "Note: widens the UI
    security audit surface" is already in the synthesis sketch. The
    weight of THIS candidate's audit-surface-widening is much greater
    than UPL-5 or UPL-7 alone, because it touches THREE server-side
    fragment endpoints (create-notebook, add-paper, remove-notebook)
    AND introduces a content-negotiation pattern (`HX-Request: true`
    → fragment; else JSON) that becomes a NEW pattern other features
    will copy. New fragment endpoints = new XSS vectors if any path
    forgets `html.escape()`. The existing fragment-returning sites
    (`_paper_row_html`, `_display_name_fragment`, `ui_status_badge`)
    use hand-built `html.escape()` per-value — a new Jinja2 fragment
    template (`_notebook_row.html`) shifts the discipline to autoescape;
    that's consistent with the rest of the templates but the audit
    has to confirm it.
  - **Effort honesty (axis 8):** Sized M. Realistic given (a) three
    flows, (b) new Jinja2 fragment template, (c) `HX-Trigger` /
    `HX-Redirect` header plumbing, (d) per-fragment test coverage
    parity with the existing m1/m2 detail-page suites. M is
    defensible but tight.
  - **Sequencing (axis 10):** UPL-3 (`aria-live` on swap targets)
    is correctly identified as a prerequisite for UPL-12, but UPL-11
    (`htmx-request` styling) is ALSO a prerequisite — without
    in-flight visual feedback, the now-non-reloading flow has even
    less affordance than the reload flow it replaces (no white flash =
    no signal whatsoever). The sequencing diagram should be
    UPL-1 → UPL-3 → UPL-11 → UPL-12, not UPL-1 → UPL-3 → UPL-12.
- **Suggested scope adjustment:**
  - **v0:** convert ONE flow first (add-paper, since the m8 upload
    card at `notebook_detail.html:118-120` already uses the
    `hx-target="#papers-tbody" hx-swap="beforeend"` pattern — so the
    add-paper conversion shares the existing target and is the
    smallest delta). Land that, observe, iterate.
  - **v1:** convert create-notebook + remove-notebook after v0 ships.
  - Force the dependency edge: UPL-12 cannot land before UPL-1, UPL-3,
    AND UPL-11.

---

## 4. MINOR findings

### UPL-1 — `prefers-reduced-motion` universal gate

- **Severity:** MINOR
- **Objections:**
  - **A11y nuance (axis 3):** The universal `*, *::before, *::after`
    selector with `!important` is a known foot-gun: it overrides every
    future intentional transition, including ones a future implementer
    might want to KEEP under reduced-motion (e.g. instant `display:
    none` opacity transition is a feature, not a bug; clobbering it
    to 0.01ms is theoretically a no-op but actually triggers a
    micro-transition event that some screen-reader / browser combos
    log). The sketch is the **canonical pattern** (cited from
    Andy-Bell / WCAG guidance), so this is genuinely a MINOR objection,
    but the sketch should ALSO add `transition-delay` and
    `animation-delay` overrides to be exhaustive — otherwise staggered
    reveals (e.g. UPL-3-style `stagger-reveal` if it ever lands) leak
    delay even with duration clamped.
- **Suggested scope adjustment:** add two lines to the sketch:
  `animation-delay: 0.01ms !important; transition-delay: 0.01ms
  !important;` for completeness.

### UPL-2 — `:focus-visible` baseline ring

- **Severity:** MINOR
- **Objections:**
  - **Token discipline (axis 7):** Sketch uses `var(--accent)` for the
    outline — correct. But `button.danger:focus-visible { outline-
    color: var(--fg); }` introduces visually quiet focus on the
    destructive button, which is arguably the OPPOSITE of what
    keyboard users want — destructive controls deserve the LOUDEST
    focus indicator. Consider `outline-color: var(--danger)` plus
    `outline-offset: 3px` to push the ring outside the red fill so it
    remains visible against the red background.
  - **A11y contrast (axis 3):** `2px solid var(--accent)` on `--card-bg`
    is the design-system blue on white — clears WCAG AA non-text 3:1.
    Confirm on `--error-bg` (the form-error background) where focus
    rings on inputs nested inside an error region need a different
    contrast story.
- **Suggested scope adjustment:** flip `button.danger:focus-visible`
  outline-color to `--danger` (or to `--fg` only AFTER a real screen
  walkthrough confirms the muted ring is acceptable).

### UPL-8 — `prefers-color-scheme: dark` token pair

- **Severity:** MINOR
- **Objections:**
  - **Vendored weight / scope creep (axis 4 + 8):** ~30 lines of CSS
    is the synthesis estimate. Realistic. But it pulls in
    `color-mix()` (UPL-9) as a hard dep, status-pill remapping (3
    modifier classes), and the table-header dark surface — by the
    time the implementer adds dark-mode counterparts for `.empty`,
    `.hint`, `.note`, `pre.error`, `.breadcrumb`, the freshness time-
    grey `color: #555`, the footer `color: #666`, and the table-header
    `background: #f0f0f0`, it's 60-80 lines. That keeps the file
    under the 300-line guidance (axis 4) — fine — but the synthesis
    "~30 lines" undercounts by 2-3x.
  - **A11y regression (axis 3):** Hard-coded dark-mode values
    (`#1c2026`, `#a8d4a8`, `#b8d4f0`, `#f1a098`, `#e8c98a`) violate
    the 8-token discipline (axis 7) — those become NEW tokens by
    accident. Either promote them to named CSS custom properties
    OR justify the hard-coded values as one-shot derivations.
- **Suggested scope adjustment:**
  - **v0:** dark-mode the 8 base tokens only. Skip the status-pill
    remapping for v0 (the badge keeps light-mode contrast in dark
    mode, which is visually inconsistent but a11y-safe).
  - **v1:** ship the status-pill remapping + table-header + freshness
    color. Decide v1 whether to promote `#1c2026` etc. to new
    named tokens (e.g. `--card-bg-elevated`).
  - Re-size to S (v0) / M (v1).

### UPL-11 — Adopt `htmx-request` styling on in-flight buttons

- **Severity:** MINOR
- **Objections:**
  - **Sequencing (axis 10):** Sketch wraps the spinner `::after` in
    `@media (prefers-reduced-motion: no-preference)` — correct, but
    the `opacity: 0.6; pointer-events: none; cursor: wait;` triplet
    should land UNCONDITIONALLY (those are signal, not motion). Only
    the `animation: spin` should be gated. The current sketch puts
    everything inside the no-preference block, so reduced-motion
    users get NO in-flight signal at all — that's a regression vs.
    the current "no signal" state, technically the same, but the
    point of UPL-11 IS the signal.
  - **A11y (axis 3):** Spinner `::after` with `content: ""` is invisible
    to screen readers — correct (the live-region announcement comes
    from UPL-3). But `pointer-events: none` on a button while still
    being keyboard-focusable means a keyboard user can Tab to it and
    fail to activate it without any feedback. Add `aria-busy="true"`
    via htmx's auto-applied attribute (htmx adds it automatically in
    2.x — confirm against `htmx.org/docs/#hx-disabled-elt` and the
    `requesting` class semantics) OR explicitly via `hx-disabled-elt
    ="this"` on each form.
- **Suggested scope adjustment:**
  - Move `opacity / pointer-events / cursor: wait` OUTSIDE the
    `prefers-reduced-motion: no-preference` block. Keep `animation:
    spin` inside.
  - Add `hx-disabled-elt="this"` to each `<button>` for keyboard a11y
    parity. Test once with VoiceOver / NVDA before shipping.

### UPL-13 — View Transitions API on htmx swaps

- **Severity:** MINOR
- **Objections:**
  - **CSP impact (axis 5):** Sketch adds 6 LOC to the existing inline
    `<script>` in `base.html`. Inside the existing `'unsafe-inline'`
    allowance — no CSP widening, correct. But `htmx.swap()` is the
    canonical re-entry per htmx 2.0.10 docs; the sketch's
    `e.preventDefault()` + `htmx.swap(target, response, swapSpec)`
    pattern needs verification against the **exact** htmx 2.0.10 API
    (the function signature changed between 1.x and 2.x). The
    synthesis flags this as an Open Question — keep it open.
  - **Sequencing (axis 10):** Depends on UPL-1 (synthesis correctly
    cites this) AND should probably land AFTER UPL-12 (in-place
    swaps), since reload flows produce no fragment-swap event for
    `startViewTransition` to wrap. The synthesis doesn't surface
    this ordering — Phase 4 prioritizer should treat UPL-13 as
    post-UPL-12.
  - **Motion-vocabulary anti-pattern (axis 9):** None — View
    Transitions API is the canonical 2026 pattern. `[MOT-52]` is the
    correct primitive.
- **Suggested scope adjustment:**
  - Add explicit dependency edge: UPL-13 lands AFTER UPL-1, UPL-3,
    UPL-11, UPL-12.
  - Spike the `htmx.swap()` signature against vendored
    `frontend/static/htmx.min.js` BEFORE committing — if the call
    shape is wrong, the swap won't re-enter and the UI will silently
    stop functioning on every htmx interaction. This is a regression
    risk worth one hour of verification time.

### UPL-19 — Mobile responsiveness baseline

- **Severity:** MINOR
- **Objections:**
  - **Mobile-considered (axis 6):** Synthesis correctly cites visual
    G3 screenshots AND current-state M5 (`app.css:25` hard-coded
    `max-width: 980px`). But `body { max-width: min(95vw, 1400px) }`
    expanding the desktop width to 1400px is a separate axis from
    the mobile table-wrap fix — bundling them risks regressing the
    visual rhythm of the operator console at 27"+ monitors where
    the 980px ceiling is a deliberate readability choice (long
    line lengths hurt scanning). Test 1400px on a real wide monitor
    before shipping.
  - **Effort honesty (axis 8):** Sized S. Realistic. But "responsive
    table" is a deceptively-large rabbit hole — what about the
    `<dl class="meta">` block on mobile (currently `grid-template-
    columns: max-content 1fr` which works at narrow widths but
    visually compresses)? The candidate scoped explicitly to table
    overflow; if Phase 4 wants the broader responsive pass, re-scope.
- **Suggested scope adjustment:**
  - **v0:** ship JUST the `.table-wrap { overflow-x: auto }` wrappers
    (the actual mobile-overflow bug-fix).
  - **v1:** the `body { max-width: min(95vw, 1400px) }` expansion,
    after verifying on a 27"+ display that long-line readability
    doesn't regress.
  - Re-size to XS (v0) / S (v0+v1).

### UPL-21 — Poll backoff + Page Visibility API on `#ingest-status`

- **Severity:** MINOR
- **Objections:**
  - **Effort honesty (axis 8):** Sized S. The synthesis Open Question
    flags the core risk: htmx 2.0.10's `hx-trigger="every 2s
    [condition]"` may not actually support conditional intervals
    (the htmx docs cite `every <interval>` and `[condition]` as
    separate features; combined behavior needs verification). If
    they don't compose, the implementer has to either (a) use
    `HX-Trigger` response header to swap the trigger dynamically
    server-side (more complex), or (b) write a small inline-JS
    Page-Visibility listener (CSP-safe but adds 10-15 LOC of inline
    JS to `base.html`'s shim block).
  - **CSP impact (axis 5):** Approach (b) — adding inline JS — fits
    within the existing `'unsafe-inline'` allowance, so no CSP
    widening. Approach (a) is purely server-side, no client CSP
    impact. Both are fine.
- **Suggested scope adjustment:**
  - Spike the htmx conditional-interval feature against vendored
    htmx 2.0.10 BEFORE committing. If it doesn't work, document the
    fallback choice (a vs b) in the milestone brief.
  - The "30s poll when complete" backoff is the high-value part;
    the Page-Visibility pause is incremental polish on top. Phase 4
    could ship the backoff alone first.

### UPL-22 — Footer badge fixed-width + flash-on-swap

- **Severity:** MINOR
- **Objections:**
  - **Token discipline (axis 7):** Sketch's flash keyframe uses
    `color-mix(in oklab, var(--accent) 30%, transparent)` for the
    `from` state — depends on UPL-9 (color-mix() adoption). Without
    UPL-9, this is one of three sites that hard-code the OKLAB
    color-mix call without justification. Synthesis doesn't surface
    that UPL-22 has an implicit UPL-9 dependency.
  - **Motion-vocabulary (axis 9):** `[MOT-14 data-tick-flash]` is
    the right primitive. `[MOT-10 breathing-glow]` on the OK state
    is marked "optional" — keep it optional, not v1. Continuous
    glow on the operator footer is exactly the "ambient" motion
    that the motion-vocabulary §8 cautions against on operator
    consoles (MOT-NO-2 by analogy — parallax-equivalent ambient
    motion).
- **Suggested scope adjustment:**
  - Drop the optional `[MOT-10 breathing-glow]` for v1 entirely.
  - Force the dependency edge: UPL-22's flash keyframe requires
    UPL-9 (color-mix) to land first, or rewrite the keyframe to
    use hex literals (which violates axis 7 — so keep UPL-9 as the
    sequenced prerequisite).
  - Otherwise ship as proposed.

---

## 5. Clean candidates (NONE / no objections)

These 14 candidates draw a `NONE` verdict — each is well-scoped, well-cited,
no axis violation, effort sizing plausible, and stack-fit verified:

- **UPL-3** — `aria-live="polite"` on htmx success swap targets.
  Pure semantic / attribute additions; matches the parity gap with
  existing `pre#rename-error[aria-live]`. Zero CSS, zero JS, zero
  effort risk. Sequencing depends only on the swap targets existing
  (they do).
- **UPL-4** — Skip-to-main-content link. WCAG SC 2.4.1 canonical
  pattern, 1 HTML line + 5 CSS lines, no axis issue.
- **UPL-6** — HTML-render the `/preview` empty-state. Reuses
  existing `.card` + `.empty` + `base.html` chrome via a new
  Jinja2 template (`preview_missing.html`); content-negotiates on
  `Accept: text/html` so JSON clients are unaffected. CSP note in
  the synthesis (the looser UI CSP vs the tight preview CSP) is
  the correct flag — the v0 sketch keeps the broader UI chrome
  for the empty-state, which is the right call. The optional
  `[MOT-1 fade-in]` is correctly gated by UPL-1.
- **UPL-9** — `color-mix()` adoption. Native Baseline Widely
  Available since 2025-11-09; replaces imprecise
  `filter: brightness(1.08)`; supports UPL-8 dark-mode derivations.
  XS, no axis violation.
- **UPL-10** — `tabular-nums` on timestamps + counts. One CSS rule,
  eliminates horizontal jitter, no axis concerns.
- **UPL-14** — Status-pill discipline extension to notebook-kind +
  ingest run-state. Reuses existing `.status-badge--*` vocabulary;
  documenting the existing 4th `--ops-warn` modifier in the design-
  system reference is the correct doc-drift fix.
- **UPL-15** — Table-row hover + focus-within. Uses `color-mix()`
  (sequenced post-UPL-9); 4 CSS lines; correct `outline-offset: -2px`
  to avoid double-ring conflict with inner button focus.
- **UPL-16** — Scholarly metadata-strip typing on `<dl class="meta">`.
  Pure CSS spans, pairs with UPL-10's `tabular-nums`, no axis issue.
- **UPL-17** — Richer empty-state cards. Templates + ~8 CSS lines
  for `.preview--disabled`; correctly scoped to v1 (no SVG
  illustration). `[MOT-1 fade-in]` correctly gated.
- **UPL-18** — Per-route H1 specialization. Two template edits,
  Jinja2 `{% block %}` is the canonical pattern.
- **UPL-20** — Disabled-Preview affordance. Subsumed under UPL-17 in
  synthesis; clean candidate either way. Ship as part of UPL-17 OR
  separately — Phase 4's call.
- **UPL-23** — Micro-a11y cleanups (footer `·`). 5 spans,
  `aria-hidden="true"` is the canonical pattern, zero axis risk.
- **UPL-24** — Cosmetic CSS micro-polish bundle. Three small fixes;
  the `input[name="display_name"]` monospace override is a legit
  m1/m2 footnote; the active-state `filter: brightness(0.92)` is
  fine; the vendor-stamp comment update is doc hygiene.
- **UPL-25** — favicon + `/favicon.ico` 403 fix. Pair with UPL-7;
  cleans devtools / server-log noise. Single static asset under
  `frontend/static/` is within the no-build-chain envelope.

---

## 6. Cross-cutting concerns

### 6.1 Sequencing rigor (axis 10)

The synthesis correctly identifies UPL-1 → UPL-2 → UPL-3 → UPL-4 as the
foundational a11y triad. But several downstream candidates have **implicit
dependencies** that the synthesis doesn't surface as hard edges:

- **UPL-13 (View Transitions) depends on UPL-12 (in-place swaps).**
  Reload flows produce no swap event for `startViewTransition` to wrap.
- **UPL-12 depends on UPL-11 (in-flight styling).** Without in-flight
  signal, the new no-reload flow has LESS affordance than the reload
  flow it replaces.
- **UPL-15, UPL-22 depend on UPL-9 (color-mix).** Both sketches use
  `color-mix(in srgb / oklab, ...)` for derived shades.
- **UPL-8 (dark-mode) implicitly depends on UPL-9.** The dark-mode
  status-pill backgrounds use `color-mix()` derivations.

Phase 4's prioritization SHOULD render this DAG explicitly:

```
UPL-1 ─┐
UPL-2 ─┼─→ everything else
UPL-3 ─┤
UPL-4 ─┘

UPL-9 ─→ UPL-8, UPL-15, UPL-22
UPL-11 ─→ UPL-12 ─→ UPL-13
UPL-3 ─→ UPL-12
```

### 6.2 UI-audit surface widening (axis 5)

THREE candidates widen `chris-dare-dev/arXMCP#9` (the deferred UI security
audit): UPL-5 (touches the inline JSON-shim), UPL-7 (touches the Threat-5
DNS-rebinding middleware), UPL-12 (introduces three new server-side
fragment endpoints). The synthesis acknowledges this for UPL-5 and UPL-12;
UPL-7's audit-coordination is undersized as an Open Question. Phase 4
should EITHER bundle these three with an explicit "audit-coordination
required" badge AND a documented sequencing edge to the audit landing,
OR descope UPL-7's middleware surgery to a separate FastAPI exception
handler (per the MAJOR finding above) to minimize the audit-coordination
load.

### 6.3 Diagnostic confidence on the CRITICAL bug-fixes

UPL-5's root-cause diagnostic (JSON-shim mis-shapes the PATCH body) is
contradicted by ground-checking the live templates: the rename form has
exactly one named input, and the shim collects-into-JSON, so the emitted
body should be exactly `{"display_name": "..."}` — which IS the
`NotebookRename` shape. The 422 must originate elsewhere. The visual
scout's evidence is described as "live walk reproduced ... PATCH 422,
`pre#rename-error.textContent === ""`" but doesn't quote the actual
emitted-body payload (which the Network inspector would have shown). The
v0 work for UPL-5 should be **reproduce + capture the emitted body**
before coding any fix to the shim. The error-handler unwrap fix and the
CSS `:empty` revert are correct regardless of root cause — those are the
v0 safe ships.

### 6.4 Effort sizing drift

UPL-5 (S → M), UPL-7 (S → M post-redesign), UPL-8 (S → S+M for v0+v1),
UPL-19 (S → XS+S for v0+v1) all benefit from a v0/v1 split. Phase 4's
RICE Effort cost should price the SMALLEST shippable v0, not the
full sketch.

### 6.5 Motion-vocabulary anti-patterns (axis 9)

The synthesis is clean on anti-patterns: §6 explicitly parks
auto-rotating spotlight (MOT-NO-3), magnetic-cursor (MOT-NO-4),
confetti (MOT-NO-7), parallax (MOT-NO-2). The catalog candidates
themselves avoid MOT-NO-1 (bouncy easing on status data — UPL-22's
flash uses `ease-out`, not elastic), MOT-NO-5 (universal-gate
prerequisite UPL-1), MOT-NO-6 (no npm), MOT-NO-7 (no
confetti), MOT-NO-8 (delete flows have no motion). Two notes:
**UPL-22's optional `[MOT-10 breathing-glow]` on the OK state** drifts
toward ambient operator-console motion — recommend dropping (per the
MINOR finding above). **UPL-14's optional `[MOT-10 breathing-glow]` on
the running-ingest pill** is the right surface for ambient motion (it
IS the "live state" signal it's modeling), so it's acceptable — keep
it optional, ship without by default.

---

## 7. Recommended kill list

**None.** All 25 candidates have a defensible v0/v1 path. The MAJOR-rated
three (UPL-5, UPL-7, UPL-12) need scope adjustment, not killing. The
MINOR-rated eight (UPL-1, UPL-2, UPL-8, UPL-11, UPL-13, UPL-19, UPL-21,
UPL-22) need small sketch revisions or dependency-edge declarations,
not killing.

The synthesis's §6 already kills the candidates that needed killing
(SPA migration, Tailwind, magnetic-cursor on operator buttons,
confetti, etc.). The frontend-uplift-challenger's role here is to
calibrate Phase 4's effort/dependency view — and the verdict is that
the catalog is operationally sound.

*End of challenge.*
