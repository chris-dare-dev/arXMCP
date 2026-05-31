# Synthesis — `2026-05-ui-polish`

**Phase:** 2 — Synthesize (main session)
**Date:** 2026-05-30
**Inputs:** 4 Phase-1 briefs + 8 screenshots under
`.claude/notes/frontend-uplifts/2026-05-ui-polish/{discover,screenshots}/`.

---

## 1. Executive summary

The 4 scouts converged on a **single dominant theme**: arXMCP's `/ui/`
operator console is well-scaffolded on the happy path (consistent
`.card` hierarchy, 8-token CSS-variable system, clean htmx swap targets,
calibrated `--accent` blue and `--danger` red) but is **floor-bare on
2026 a11y baselines** (zero `prefers-reduced-motion`, zero
`:focus-visible`, zero `aria-live` on success swaps, no skip-link, no
dark-mode) AND **silently collapses to opaque JSON or visual nothing on
every error / edge path** (silent rename failure, raw-JSON preview
404, raw-JSON SecFetchSite rejection, no htmx-in-flight feedback,
mobile table overflow).

Three classes of work emerge:

1. **Foundational a11y triad + skip-link** — UPL-1 through UPL-4. Zero
   new JS bytes, all pure CSS / 1-line template edits. Every triangulated
   across **4 briefs**. Prerequisites for every other motion / interaction
   candidate. Cost: XS each.
2. **CRITICAL bug-fixes from the live walk** — UPL-5 through UPL-7. The
   visual scout found three operator-trust-eroding failure modes that
   source-readers could not see: silent rename failure, raw-JSON preview
   empty-state, raw-JSON SecFetchSite rejection. Not polish; pre-existing
   bugs in the shipped UI that the uplift surfaces. Cost: S each.
3. **Polish tier (high-triangulation visual + interaction)** — UPL-8
   through UPL-19. Dark mode, `tabular-nums`, htmx-request styling,
   in-place swap conversions, View Transitions, status-pill expansion,
   metadata-strip typing, table-row affordances, empty-state richness,
   per-route H1, mobile responsiveness. Mix of XS/S/M. Pure CSS or
   ≤1 vendored single-file drop each.

The **top thematic shift** is "**make errors visible and a11y baselines
present before any decorative motion**" (visual scout, §1 TL;DR; inspiration
scout §4 themes; current-state §8 themes all converge on this phrasing).

**Top cross-cutting tension** to resolve in Phase 3: dark-mode severity.
Visual scout marks it LOW (G13 — "loopback-only operator console; not a
baseline"); current-state, library, inspiration all mark it HIGH (white-
flash on dark-OS = visible "untouched" signal). Resolution: rank as
**MEDIUM-HIGH** — high-value polish + 2026 SOTA parity, but explicitly
behind the a11y triad and the bug-fix tier.

---

## 2. Triangulation strength

| Brief sources | Count | Candidates |
|---|---|---|
| **4 briefs** (universal — strong signal) | 6 | UPL-1, UPL-2, UPL-3, UPL-4, UPL-8, UPL-10 |
| **3 briefs** (strong) | 1 | UPL-11 |
| **2 briefs** (moderate) | 4 | UPL-9, UPL-12, UPL-13, UPL-17 |
| **1 brief** (weak — flag for challenger scrutiny) | 14 | UPL-5, UPL-6, UPL-7, UPL-14, UPL-15, UPL-16, UPL-18, UPL-19, UPL-20, UPL-21, UPL-22, UPL-23, UPL-24, UPL-25 |

Notes on single-source candidates:
- **UPL-5/6/7** (the visual-scout CRITICAL bug-fixes) are single-source
  because they are evidence-only-visible from a live browser walk — not
  weak signal; **calibrated as CRITICAL by the scout that could see them**.
- **UPL-21** (poll backoff + Page Visibility API) appears only in the
  visual-scout's live network-log evidence — also strong despite single
  source.
- The other single-source candidates are genuine "one scout saw it" and
  deserve challenger scrutiny on whether they survive Phase 4 ranking.

---

## 3. Foundational candidates (surface first; unblock the rest)

These four candidates change every motion / interaction candidate's
sequencing math: they are **prerequisites**, not standalone polish.

| Id | Title | Why foundational |
|---|---|---|
| **UPL-1** | `prefers-reduced-motion` universal gate | Per `motion-vocabulary.md` MOT-NO-5 — any motion that lands without this is an automatic Phase-3 BLOCKER. Prerequisite for UPL-11, UPL-13, UPL-15, UPL-17. |
| **UPL-2** | `:focus-visible` baseline outline ring | WCAG 2.1 AA non-text-contrast prerequisite; the destructive `<button class="danger">` rows TODAY have no visible focus indicator on Safari. Prerequisite for UPL-15 (table-row focus-within affordance) and UPL-12 (in-place htmx swaps that preserve focus). |
| **UPL-3** | `aria-live="polite"` on htmx success swap targets | Required parity with the existing 5 `pre.error[aria-live]` regions. Prerequisite for UPL-5 (rename failure rendering uses an `aria-live` block) and UPL-12 (in-place swap UX needs SR signal). |
| **UPL-4** | Skip-to-main-content link | WCAG 2.1 SC 2.4.1 baseline; prerequisite for any future nav expansion (e.g. notebook switcher, search). |

**Sequencing implication.** Phase 4's prioritizer SHOULD bundle UPL-1
through UPL-4 as a single "a11y baseline pass" milestone (~XS+XS+XS+XS
≈ S) and land it before opening any motion / interaction candidate.

---

## 4. Candidate catalog

Each entry: `### UPL-N — <title>` followed by Category, Size, Evidence
triangulation, Motion primitives, What it is, Why it matters, Sources,
Closest arXMCP analog, Screenshot evidence (when applicable), Sketch,
Open questions.

---

### UPL-1 — Add `prefers-reduced-motion` universal gate to `app.css`

**Category:** Accessibility (FOUNDATIONAL)
**Size:** XS
**Evidence triangulation:** 4 briefs (current-state H1, library A1, inspiration CAND-3, visual G6)
**Motion primitives:** wraps ALL of `[MOT-1..MOT-65]`; guards `[MOT-NO-5]`

**What it is:** add a single `@media (prefers-reduced-motion: reduce)`
block at the bottom of `frontend/static/app.css` that universally caps
animation-duration, transition-duration, and scroll-behavior to
near-zero. Combined with the convention that all future motion
candidates live inside `@media (prefers-reduced-motion: no-preference)
{ … }` blocks.

**Why it matters:** `motion-vocabulary.md` MOT-NO-5 makes any future
animation without this gate an automatic Phase-3 BLOCKER. Adopting the
gate now unblocks the rest of the catalog.

**Sources:**
- Current-state critic H1: `app.css` has zero `@media (prefers-reduced-
  motion: …)` blocks.
- Library scout A1: `prefers-reduced-motion` Baseline Widely Available
  since Chrome 74 / Safari 10.1 / Firefox 63.
- Inspiration scout CAND-3: WCAG 2.1 SC 2.3.3; every 2026 design
  system gates motion (Linear, Vercel, Stripe, Primer).
- Visual scout G6: today there's no motion to gate; tomorrow becomes
  blocking the moment ANY motion lands.

**Closest arXMCP analog today:** `frontend/static/app.css` (no current
analog).

**Sketch:** ~6 lines at the bottom of `app.css`:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```
Pure CSS, zero JS, zero new vendored asset.

**Open questions:** none.

---

### UPL-2 — Add `:focus-visible` baseline ring to interactive elements

**Category:** Accessibility (FOUNDATIONAL)
**Size:** XS
**Evidence triangulation:** 4 briefs (current-state H2, library A2, inspiration CAND-2, visual G4)
**Motion primitives:** `[MOT-34 focus-visible-glow]` baseline

**What it is:** add `:focus-visible` outline-ring rules to `button`,
`.button`, `a`, `input`, `select`, `textarea`, `[tabindex]` using the
existing `--accent` token. Pair with a quiet
`:focus:not(:focus-visible) { outline: none; }` reset so mouse clicks
don't show the ring.

**Why it matters:** Safari ≥16 drops the browser-default outline on
`<a class="button">` entirely (current-state H2 + visual G4 both
confirm); the `--danger` destructive buttons have no visible
keyboard-focus indicator. WCAG 2.1 SC 2.4.7 baseline.

**Sources:**
- Current-state H2: `app.css:55-87` defines no `:focus` or
  `:focus-visible`; `index.html:48` `<a class="button">Open</a>`
  affected on Safari.
- Library A2: Baseline Widely Available since Chrome 86 / Safari
  15.4 / Firefox 85.
- Inspiration CAND-2: cited by Primer, WebAIM, Vercel Geist as table
  stakes.
- Visual G4: live Tab walk captured browser-default rings only;
  `ss_2425vi5r1` shows low-contrast blue ring on red `--danger` button.

**Closest arXMCP analog today:** `--accent` token exists at `app.css:4-13`
but is unused for focus.

**Sketch:** ~8 lines appended to `app.css`:
```css
button:focus-visible, .button:focus-visible,
input:focus-visible, a:focus-visible,
select:focus-visible, textarea:focus-visible,
[tabindex]:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: 4px;
}
button.danger:focus-visible { outline-color: var(--fg); }
:focus:not(:focus-visible) { outline: none; }
```
Pure CSS, zero JS.

**Open questions:** none.

---

### UPL-3 — Add `aria-live="polite"` to htmx success swap targets

**Category:** Accessibility (FOUNDATIONAL)
**Size:** XS
**Evidence triangulation:** 4 briefs (current-state H4, library A3, inspiration CAND-5, visual G11)
**Motion primitives:** none (semantic).

**What it is:** add `aria-live="polite"` (and `aria-atomic="true"` on the
status-badge) to the existing htmx success swap targets — match the
parity already on the 5 `pre.error[aria-live]` regions.

**Why it matters:** the 5 error `<pre>`s are correctly announced;
successes (rename completion, ingest poll transitions, paper-row
appends, status-badge state flips) are SR-silent. The m4 footer status-
badge in particular flips silently from READY → DEGRADED → WARN → DOWN
every 10s with no SR signal — a screen-reader operator gets zero
liveness signal.

**Sources:**
- Current-state H4: enumerates 5 missing `aria-live` regions
  (`#display-name-block`, `#ingest-status`, `#papers-tbody`,
  `#status-badge`, `#notebook-list`).
- Library A3: htmx's canonical pairing per `htmx.org/examples/aria-live`.
- Inspiration CAND-5: WAI-ARIA Authoring Practices documents
  `aria-live="polite" aria-relevant="additions text"` as the canonical
  swap-target pairing.
- Visual G11: only `pre#rename-error[aria-live]` exists today; all
  other swap targets are SR-silent.

**Closest arXMCP analog today:** `pre#rename-error[aria-live="polite"]`
in `notebook_detail.html:39` is the seed.

**Sketch:** five attribute additions across two templates:
- `notebook_detail.html:15` — add `aria-live="polite"` to `#display-name-block`.
- `notebook_detail.html:161` — add `aria-live="polite"` to `#ingest-status`.
- `notebook_detail.html:180` — add `aria-live="polite"` to `#papers-tbody`.
- `base.html:65` — add `aria-live="polite" aria-atomic="true"` to `#status-badge`.
- `index.html:41` — add `aria-live="polite"` to `#notebook-list` (after UPL-12 wires it).

Zero CSS, zero JS.

**Open questions:** should the badge use `aria-live="polite"` or
`aria-live="off"` until state changes? (default polite is correct;
`aria-atomic="true"` ensures the whole `DEGRADED | corpus v…` string
is announced as one unit.)

---

### UPL-4 — Add skip-to-main-content link

**Category:** Accessibility (FOUNDATIONAL)
**Size:** XS
**Evidence triangulation:** 4 briefs (current-state M7, library A4, inspiration CAND-8, visual G5)
**Motion primitives:** none.

**What it is:** prepend a `<a class="skip-link" href="#main">` as the
first child of `<body>` in `base.html`; add `id="main" tabindex="-1"`
to the existing `<main>`; visually-hidden CSS rule that reveals on
`:focus-visible`.

**Why it matters:** WCAG 2.1 SC 2.4.1; cheapest a11y win available; pre-
requisite for any future header / nav expansion.

**Sources:**
- Current-state M7: `base.html:47-52` has no skip-link.
- Library A4: WebAIM canonical pattern.
- Inspiration CAND-8: cited by every WCAG-AA dev tool.
- Visual G5: DOM snapshot confirms first focusable element is the
  header `<h1>` link.

**Closest arXMCP analog today:** no current analog.

**Sketch:** 1 HTML line + 5 CSS lines:
```html
<!-- base.html, first child of <body> -->
<a class="skip-link" href="#main">Skip to main content</a>
<!-- and on existing <main>: -->
<main id="main" tabindex="-1">
```
```css
.skip-link { position: absolute; left: -9999px; top: 0; }
.skip-link:focus-visible {
  left: 1rem; top: 1rem; z-index: 1000;
  padding: 0.5rem 1rem;
  background: var(--accent); color: #fff;
  border-radius: 4px;
}
```

**Open questions:** none.

---

### UPL-5 — Fix silent rename failure (CRITICAL bug)

**Category:** Interaction (BUG FIX)
**Size:** S
**Evidence triangulation:** 1 brief (visual G1) — single-source because evidence-only-from-live-walk
**Motion primitives:** none (correctness fix); pairs with UPL-3 (aria-live).

**What it is:** the htmx `rename-form` PATCH to
`/ui/api/notebooks/<slug>` returns 422 because the JSON-shim's payload
doesn't match `NotebookRename`'s expected shape; the
`hx-on::htmx:response-error` handler unwraps a missing `.detail` field
and assigns an empty string to `pre#rename-error`, which is then
hidden by the `pre.error:empty { display: none }` rule. Operators see
total silence on a rejected rename.

**Why it matters:** operator types a new display name, clicks Rename,
sees no feedback, assumes it worked. CRITICAL trust erosion.

**Sources:**
- Visual G1: live walk reproduced — `PATCH /ui/api/notebooks/bridgeland-stability`
  → 422; `pre#rename-error.textContent === ""`; UI silent; verified via
  `curl PATCH` that the canonical JSON body DOES rename correctly.

**Closest arXMCP analog today:** `notebook_detail.html:30-39` (rename
form); `app.css:99-110` (error styling); `base.html:18-44` (the
JSON-shim).

**Screenshot evidence:** `screenshots/notebooks-bridgeland-stability-desktop.png`
+ live captures `ss_9969f6djd` (button at submit-time, pre-422) and
`ss_1595ueybh` (2s later, pixel-identical — no error visible).

**Sketch:** three independent fixes; all required:
1. **Fix the JSON-shim payload shape** in `base.html:18-44` so PATCH
   sends `{"display_name": "<new>"}` — match `NotebookRename` Pydantic
   model. (Audit the shim against every PATCH/POST route, not just
   rename.)
2. **Fix the error-handler unwrap** for FastAPI's 422 validation-error
   shape `{detail: [{loc, msg, type}, …]}` — extract `detail[0].msg`
   when `detail` is an array.
3. **Reserve vertical space** for empty `pre.error` so the error
   region doesn't collapse on the success → error → re-submit path —
   drop `pre.error:empty { display: none }` from `app.css:110`
   (current-state L5 cross-cite) and rely on `min-height: 1.2em`.

Note: this widens the UI security audit surface (`chris-dare-dev/arXMCP#9`)
in (1) by touching the inline JSON-shim — flag the audit explicitly.

**Open questions:** are there other JSON-shim mis-mappings on the
add-paper / upload / ingest routes? Audit before shipping (visual scout
implies the shim is rename-specific but didn't exhaustively test).

---

### UPL-6 — HTML-render the `/preview` empty-state (CRITICAL bug)

**Category:** Interaction (BUG FIX)
**Size:** S
**Evidence triangulation:** 1 brief (visual G2) — single-source because evidence-only-from-live-walk
**Motion primitives:** `[MOT-1 fade-in]` on the empty-state card (gated by UPL-1).

**What it is:** `/ui/notebooks/<slug>/papers/<id>/preview` returns
`JSONResponse({"detail": "no preview available"}, 404)` when the paper
has no uploaded ar5iv HTML — Chrome renders this as raw black-on-white
JSON via its default JSON viewer, with no arXMCP branding, no back-link,
no upload instruction.

**Why it matters:** the route is reachable from inside the app (papers-
table Preview link) and via deep-link / bookmark. The miss-path is
"black wall of debug JSON" — breaks first-load trust.

**Sources:**
- Visual G2: `screenshots/notebooks-bridgeland-stability-papers-preview-desktop.png`
  and `…-mobile.png` (both show raw JSON viewer).
- Current-state implicitly: `.empty` class exists; can be reused.

**Closest arXMCP analog today:** `.card` + `.empty` + the `base.html`
chrome already cover the rendering need; just need a thin Jinja2
template (`preview_missing.html`) extending `base.html`.

**Screenshot evidence:** `screenshots/notebooks-bridgeland-stability-papers-preview-{desktop,mobile}.png`.

**Sketch:** add a `frontend/templates/preview_missing.html` template
extending `base.html` with a breadcrumb (`← back to <slug>`) + a
`.card.empty` explaining "No ar5iv HTML uploaded yet — head to the
notebook's *Upload ar5iv HTML* card." Change the preview-route handler
in `server/routes/notebooks.py` to render this template on the 404 path
(content-negotiate on `Accept: text/html` — JSON clients keep getting
the JSON body).

**Open questions:** does this widen the preview-route CSP? The
`preview_missing.html` would inherit `CONTENT_SECURITY_POLICY_UI` (the
looser one), not `CONTENT_SECURITY_POLICY_PREVIEW` (the tight one) —
verify with the security audit.

---

### UPL-7 — HTML-render the `SecFetchSiteMiddleware` rejection (CRITICAL bug)

**Category:** Interaction (BUG FIX)
**Size:** S
**Evidence triangulation:** 1 brief (visual G3) — single-source because evidence-only-from-live-walk
**Motion primitives:** none.

**What it is:** ALL `/ui/*` routes return raw-JSON
`{"error":"sec_fetch_site_forbidden", …}` when the request's
`Sec-Fetch-Site` header is not `none` — i.e. any address-bar nav from
chrome://newtab, any external referrer (Slack / email / bookmark from
a non-`/ui/` page). The defense is correct (Threat 5 — DNS-rebinding
mitigation); the rendering is not.

**Why it matters:** every operator who bookmarks `/ui/notebooks/…` and
clicks it the next morning gets unintelligible JSON. The defense path
needs an HTML escape hatch — a server-rendered "Continue to arXMCP
notebooks" landing page that triggers a same-origin nav.

**Sources:**
- Visual G3: live walk captured 3 separate Sec-Fetch-Site rejection
  pages — `ss_4286hwuko`, `ss_6343wkdjz`, `ss_7100o6f9d`.

**Closest arXMCP analog today:** `server/middleware.py::SecFetchSiteMiddleware`
(E13_S05 Threat 5).

**Sketch:** UA-sniff / Accept-header-negotiate in the middleware. For
browser clients (`Accept: text/html`), render an HTML page extending
`base.html` with a `.card` explaining the rejection and a primary-CTA
`<form method="GET" action="/ui/">Continue to arXMCP notebooks</form>`
button (same-origin POST will succeed because the browser is now the
referrer). For non-HTML clients (curl, API), keep the JSON body. Pair
with UPL-25 (favicon fix) since the favicon 403 has the same root
cause.

**Open questions:** does this weaken the Threat 5 defense? No — the
rejection happens regardless; only the response body changes by
Content-Type. Verify in the security audit.

---

### UPL-8 — Add `prefers-color-scheme: dark` token pair

**Category:** Color/theme
**Size:** S
**Evidence triangulation:** 4 briefs (current-state H3, library A5, inspiration CAND-6, visual G13)
**Motion primitives:** none.

**What it is:** add a parallel `@media (prefers-color-scheme: dark) {
:root { … } }` block in `app.css` that re-declares all 8 vars from
lines 4-13 with dark-mode values. Pair the `.status-badge--*` colors
at lines 123-126 with dark-mode equivalents (the current `#e6f4ea`
green-bg fails contrast on dark). Use `color-mix()` (UPL-9) to derive
the dark badge surfaces from the same base tokens.

**Why it matters:** operators run dark-mode IDEs / terminals / Slack;
arXMCP's light-mode flash on session start reads as "untouched."
arXiv.org itself ships dark mode since 2024; ar5iv has it since launch;
Linear, Vercel, Sentry, Grafana, Phoenix all honor `prefers-color-scheme`
natively. Stays inside the §4 8-token discipline (same names, different
values).

**Sources:**
- Current-state H3: `app.css:4-13` has no dark variant.
- Library A5+A6: Baseline Widely Available; `color-mix()` Baseline
  Widely Available since 2025-11-09.
- Inspiration CAND-6: cites Primer's semantic-token pattern + Vercel
  Geist 10-color scale + Zed's dark-by-default execution.
- Visual G13: severity LOW (op-only loopback); others mark HIGH.

**Closest arXMCP analog today:** `:root` block at `app.css:4-13`.

**Sketch:** ~30 lines of CSS:
```css
@media (prefers-color-scheme: dark) {
  :root {
    --fg: #e8e8e8;
    --bg: #0d1117;
    --card-bg: #161b22;
    --border: #30363d;
    --accent: #58a6ff;
    --danger: #f85149;
    --error-bg: #2a1a18;
    /* --mono unchanged */
  }
  th { background: #1c2026; }
  .status-badge--ok { background: color-mix(in oklab, var(--accent) 25%, transparent); color: #a8d4a8; }
  .status-badge--warn { background: color-mix(in oklab, #d29922 30%, transparent); color: #e8c98a; }
  .status-badge--ops-warn { background: color-mix(in oklab, var(--accent) 15%, transparent); color: #b8d4f0; }
  .status-badge--down { background: color-mix(in oklab, var(--danger) 25%, transparent); color: #f1a098; }
}
```
Anchored to GitHub Primer's dark scale (proven a11y-compliant).

**Open questions:**
- Does the preview-route's CSP allow the inline `@media` declaration? Yes — it's pure CSS, no `style-src` concerns.
- Should we also adopt a `data-theme="dark"` override for operators who want to force dark? Out of scope for v1; revisit if requested.

**Cross-cutting tension to resolve in Phase 3:** visual scout marks
this LOW; library+inspiration+current-state mark HIGH. Resolution: rank
as **MEDIUM-HIGH** in Phase 4 — high SOTA-parity value, but explicitly
ranks below UPL-1..4 (a11y prerequisite) and UPL-5..7 (CRITICAL bugs).

---

### UPL-9 — Adopt `color-mix()` for derived shades

**Category:** Color/theme (supports UPL-8)
**Size:** XS
**Evidence triangulation:** 2 briefs (library A6, inspiration CAND-6 as dep)
**Motion primitives:** none.

**What it is:** replace the imprecise `filter: brightness(1.08)` button-
hover at `app.css:87` with `background: color-mix(in oklab, var(--accent)
90%, white);`. Use the same pattern for derived border / hover / focus
surfaces, halving the maintenance cost of UPL-8's dark-mode tokens.

**Why it matters:** native, zero-vendor, Baseline Widely Available since
2025-11-09; pairs naturally with UPL-8.

**Sources:**
- Library A6: cited Baseline + the exact `filter: brightness(1.08)`
  replacement.
- Inspiration CAND-6 status-badge derivation depends on it.

**Closest arXMCP analog today:** `app.css:87` `filter: brightness(1.08)`.

**Sketch:** swap one line; use derived shades throughout UPL-8's dark
block (already inline in UPL-8's sketch).

**Open questions:** none.

---

### UPL-10 — Add `tabular-nums` to timestamps + counts

**Category:** Typography
**Size:** XS
**Evidence triangulation:** 4 briefs (current-state M1, library A7, inspiration CAND-7, visual G12)
**Motion primitives:** none.

**What it is:** add `font-variant-numeric: tabular-nums` to `<time>`
elements, `dl.meta dd code`, `.status-badge`, and `table.notebooks td`
/ `table.papers td` cells holding numeric data. Eliminates horizontal
jitter on htmx swaps that update timestamps or counts.

**Why it matters:** visible jitter every time the badge polls or a
freshness `<time>` updates; the only count that re-renders on operator
action is exactly the value they're watching.

**Sources:** all 4 briefs cite the same gap.

**Closest arXMCP analog today:** `--mono` is applied to code spans but
not to digit-bearing prose.

**Sketch:** one CSS rule:
```css
time, .status-badge, dl.meta dd, td code,
.meta-value--time {
  font-variant-numeric: tabular-nums;
}
```

**Open questions:** none.

---

### UPL-11 — Adopt `htmx-request` styling on in-flight buttons

**Category:** Interaction
**Size:** S
**Evidence triangulation:** 3 briefs (current-state M2, inspiration CAND-4, visual G8) [+ library B2 as optional vendor extension]
**Motion primitives:** `[MOT-13 skeleton-shimmer]`, `[MOT-33 icon-spin-on-action]` (gated by UPL-1)

**What it is:** add CSS rules targeting htmx's auto-applied
`.htmx-request` / `.htmx-swapping` / `.htmx-settling` classes. The
in-flight button visually dims + becomes non-clickable + shows a tiny
CSS-only spinner. Pair with `.htmx-settling` flash on swap targets so
the operator sees that "something just refreshed."

**Why it matters:** every htmx-bound button (≥7 forms) currently looks
identical at click moment and ~400ms later. Operators double-click,
especially on the destructive `Delete` button. Loopback latency is
sub-ms for most operations BUT POST `…/ingest` spawns a subprocess and
upload streams MBs — the slow paths are exactly where the affordance is
most missed.

**Sources:**
- Current-state M2: htmx 2.x docs cite `htmx.org/docs/#requests` for
  `.htmx-request`.
- Inspiration CAND-4: cites htmx core CSS hooks (no extension needed).
- Visual G8: live walk confirmed pixel-identical buttons at submit-time
  and 2s later.
- Library B2 (optional): the `loading-states` htmx extension is a
  ~4.8 KB un-min single-file vendor drop offering richer per-element
  control.

**Closest arXMCP analog today:** htmx 2.0.10 is already vendored; the
`htmx-request` class is auto-applied — `app.css` just doesn't react.

**Sketch:** ~10 CSS lines:
```css
@media (prefers-reduced-motion: no-preference) {
  .htmx-request {
    opacity: 0.6;
    pointer-events: none;
    cursor: wait;
  }
  .htmx-request::after {
    content: ""; display: inline-block;
    width: 0.8em; height: 0.8em; margin-left: 0.5em;
    border: 2px solid currentColor; border-right-color: transparent;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
    vertical-align: middle;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
}
```
Zero new vendored asset. Optional follow-up: vendor `htmx-ext-loading-states`
for per-element opt-in attributes (deferred).

**Open questions:** does the spinner overlap with button text on `Add`,
`Upload`, `Ingest now`? Test by eyeballing in worktree before shipping.

---

### UPL-12 — Convert `location.reload()` flows to in-place htmx swaps

**Category:** Interaction
**Size:** M
**Evidence triangulation:** 2 briefs (current-state H5, visual implicit via G8 + G11)
**Motion primitives:** `[MOT-50 htmx-swap-fade]` (when paired with UPL-13)

**What it is:** convert the three `hx-on::htmx:after-request="if(...)
location.reload()"` flows (Create notebook in `index.html:14`, Add
paper in `notebook_detail.html:94`, Remove notebook in `index.html:52`)
to in-place htmx swaps that match the m2 rename/delete pattern. POST
returns a fragment (`<tr>` for create, `<tr>` for add-paper, empty
response with `HX-Trigger: refresh-list` for remove). The full-page
white flash on every successful create disappears.

**Why it matters:** the m2 rename/delete pattern at
`notebook_detail.html:26-40` is htmx-idiomatic; the legacy flows next
to it use `location.reload()` which discards htmx's entire "swap
without reload" affordance. The visual flash is the most-noticed UX
defect on `/ui/` (every operator notices it once per session).

**Sources:**
- Current-state H5: enumerates the three flows + the m8 upload card
  as the correct pattern (already uses `hx-target="#papers-tbody"
  hx-swap="beforeend"`).
- Visual G8 + G11 indirectly: in-flight feedback + aria-live both
  depend on swap targets staying mounted across the request.

**Closest arXMCP analog today:** `notebook_detail.html:118-120` (the m8
upload card — already converts correctly).

**Sketch:** server-side change + Jinja2 fragment template:
1. Add a fragment template `frontend/templates/_notebook_row.html`
   that renders one `<tr>` for the notebooks table.
2. POST `/ui/api/notebooks` returns the fragment when
   `HX-Request: true` (content-negotiate on the header), JSON otherwise.
3. Modify the create-notebook form to use `hx-target="#notebook-list"
   hx-swap="beforeend"`. Same for add-paper.
4. Remove-notebook returns an empty 204 with `HX-Trigger: list-changed`;
   the form on the index uses `hx-on::htmx:trigger="this.closest('tr').
   remove()"`.

Note: widens the UI security audit surface — flag for
`chris-dare-dev/arXMCP#9`.

**Open questions:** what does Remove return for the detail page (where
the user just deleted the notebook they're viewing)? Redirect to `/ui/`
via `HX-Redirect: /ui/` is the right pattern; the existing pattern
already does this via `location.replace("/ui/")`.

---

### UPL-13 — View Transitions API on htmx swaps

**Category:** Motion
**Size:** S
**Evidence triangulation:** 2 briefs (library A8, inspiration CAND-9)
**Motion primitives:** `[MOT-50 htmx-swap-fade]`, `[MOT-52 view-transitions-api]` (gated by UPL-1)

**What it is:** add ~5 lines of inline JS to `base.html`'s existing
JSON-shim block that wraps htmx swaps in
`document.startViewTransition()` (with `if (document.startViewTransition)`
guard). Smooth ~200ms crossfade on `#display-name-block`,
`#ingest-status`, paper-row appends, paper-row deletes — for free in
Chrome/Safari, no-op fallback in Firefox.

**Why it matters:** current swaps look insta-replace / janky; this is
the canonical 2026 "SPA-feel without a SPA" upgrade. Zero vendor weight
(native API); 5 LOC of inline JS uses the existing `'unsafe-inline'`
CSP allowance — no CSP widening, audit-aware but minimal.

**Sources:**
- Library A8: Baseline Newly Available; ~89.9% global usage; the `if`
  guard pattern is the canonical fallback.
- Inspiration CAND-9: same; cited as "the SPA-feel-without-a-SPA 2026
  pattern."

**Closest arXMCP analog today:** `base.html:18-44` JSON-shim block —
right home for the new listener.

**Sketch:** ~6 lines added inside the existing `<script>` in
`base.html`:
```js
document.body.addEventListener('htmx:beforeSwap', (e) => {
  if (!document.startViewTransition) return;
  e.preventDefault();
  document.startViewTransition(() => {
    htmx.swap(e.detail.target, e.detail.serverResponse, e.detail.swapSpec);
  });
});
```
Plus optional CSS:
```css
@media (prefers-reduced-motion: no-preference) {
  ::view-transition-old(root), ::view-transition-new(root) {
    animation-duration: 200ms;
  }
}
```
**Open questions:** the htmx-recommended pattern; verify against htmx
2.0.10 docs that `htmx.swap()` is the correct re-entry. Test against
the existing m2 rename swap (the highest-fidelity test case).

---

### UPL-14 — Extend status-pill discipline to notebook-kind + ingest run-state

**Category:** Layout
**Size:** S
**Evidence triangulation:** 1 brief (inspiration CAND-11) + visual G15 doc-drift
**Motion primitives:** optional `[MOT-10 breathing-glow]` on a `running` ingest pill (gated by UPL-1).

**What it is:** apply the existing `.status-badge` + `.status-badge--*`
vocabulary to the two typed enums currently rendered as bare text:
- Notebook kind (`arxiv` vs `textbook`) on each row of the index table.
- Ingest run-state (`{{ latest_run.status }}` shown at
  `notebook_detail.html:64`) as a pill.

Also: document the existing 4th `--ops-warn` modifier in
`arxmcp-design-system.md` §5 (visual G15 — current doc lists only 3).

**Why it matters:** arXMCP already invented the right pill vocabulary;
it's just under-used. Operators scanning a notebook list need a
visual signal for "which of these is a textbook-kind notebook" vs an
arxiv one. Vercel/Linear/GitHub converge on this pattern.

**Sources:** inspiration CAND-11 cites Vercel Geist + Linear
status-row patterns.

**Closest arXMCP analog today:** `.status-badge--{ok,warn,ops-warn,down}`
at `app.css:114-126`; used in 2 places, ready for 2 more.

**Sketch:** template edits (index.html and notebook_detail.html) +
helper function in `server/routes/ui.py` (mirroring the existing
`parse_status_css`). Add an `--info` modifier if a neutral-blue is
needed for `arxiv`-kind.

**Open questions:**
- Is there design-system permission for a 5th modifier `--info`? Yes,
  documented as an extensibility path; flag in the arxmcp-design-system.md
  update.
- Does "running"-state ingest need its own breathing-glow? Optional
  follow-up.

---

### UPL-15 — Add table-row hover + focus-within affordance

**Category:** Interaction
**Size:** XS
**Evidence triangulation:** 1 brief (inspiration CAND-10)
**Motion primitives:** light `[MOT-30 lift-on-hover]` (no translateY, just background) + `[MOT-32 border-on-hover]` (gated by UPL-1).

**What it is:** add `tbody tr:hover { background: color-mix(in srgb,
var(--accent) 6%, transparent); }` and `tbody tr:focus-within {
outline: 2px solid var(--accent); outline-offset: -2px; }` to
`app.css`. Operators scanning the notebook table or papers table
get a "this row is selectable" cue.

**Why it matters:** the entire row is one big inert rectangle today
with two clickable elements per row; hover/focus-within fixes
selectability scannability.

**Sources:** inspiration CAND-10 cites Raycast extension grid + Linear's
issue tiles + GitHub's repo list.

**Closest arXMCP analog today:** `app.css:94-97` (existing `table`
rules — extend in place).

**Sketch:** 4 CSS lines. Uses `color-mix()` (UPL-9) so no new tokens.

**Open questions:** does the `:focus-within` outline conflict with the
inner `button:focus-visible` outline? Inset (`outline-offset: -2px`)
on the row avoids double rings; verify visually.

---

### UPL-16 — Scholarly metadata-strip typing on `<dl class="meta">`

**Category:** Typography / Layout
**Size:** S
**Evidence triangulation:** 1 brief (inspiration CAND-1)
**Motion primitives:** optional `[MOT-14 data-tick-flash]` on "Last indexed" `<time>` when an ingest finishes.

**What it is:** the `<dl class="meta">` block at
`notebook_detail.html:41-69` is arXMCP's closest analogue to the
arXiv abstract-page metadata strip / ar5iv header / zbMATH entry
header — but it reads as a bare definition list. Wrap each value in
a typed span (`.meta-value--mono` for paths, `.meta-value--time` for
timestamps, existing `.status-badge` for parse status). Pair with
UPL-10's `tabular-nums`.

**Why it matters:** scholarly tools use chip / monospace / status-pill
typing to make values scannable in <1s; arXMCP currently makes the
operator read the whole `<dl>` line by line.

**Sources:** inspiration CAND-1 cites arXiv abstract pages, ar5iv,
zbMATH.

**Closest arXMCP analog today:** `dl.meta` rules at `app.css:90-92`.

**Sketch:** wrap each `<dd>` in a typed span; add CSS:
```css
.meta-value--mono { font-family: var(--mono); }
.meta-value--time { font-variant-numeric: tabular-nums; color: #555; }
```
~6 lines CSS, 4 template edits.

**Open questions:** none.

---

### UPL-17 — Richer empty-state cards

**Category:** Layout
**Size:** S
**Evidence triangulation:** 2 briefs (inspiration CAND-12, current-state M3 partial — disabled-Preview semantics)
**Motion primitives:** `[MOT-1 fade-in]` on the empty-state card body (gated by UPL-1).

**What it is:** extend the bare `.empty` paragraphs ("No notebooks yet.
Create one above." / "No papers yet. Add one above." / "Loading ingest
status…") into two-step empty-states: explanatory text + sibling
`.hint` with a code-block showing the slug pattern + a "see
install.md" pointer. Pair with the disabled-Preview affordance (current-state M3): add `aria-disabled="true"` + `.preview--disabled` visual
treatment (strikethrough / dim) so operators scan the column and see
which previews are actionable.

**Why it matters:** first-run operator sees no workflow hint; the
disabled-Preview column is uniform-looking and unscannable.

**Sources:**
- Inspiration CAND-12: cites Linear empty-state, GitHub empty-repo
  CTA, Vercel.
- Current-state M3: `.hint` styled identically to text; no disabled
  semantics on `<span class="hint">Preview</span>`.

**Closest arXMCP analog today:** `.empty` class at `app.css:52` + the
`<span class="hint" title="…">Preview</span>` pattern.

**Sketch:** template extensions in `index.html:34-35` and
`notebook_detail.html:174-175` + 200-202 (the Preview hint); ~8 CSS
lines for `.preview--disabled`.

**Open questions:** does the empty-state need an SVG illustration?
Out of scope for v1 (no designer-asset budget); plain copy + hint
ships.

---

### UPL-18 — Per-route H1 specialization

**Category:** Typography / Accessibility
**Size:** XS
**Evidence triangulation:** 1 brief (current-state M6)
**Motion primitives:** none.

**What it is:** make `header h1` content a Jinja2 block
(`{% block header_title %}arXMCP notebooks{% endblock %}`) and override
on the detail page with `arXMCP notebooks — <code>{{ notebook.slug
}}</code>`. SR users navigating by H1 hear which notebook they're on.

**Why it matters:** `<title>` already varies correctly; H1 doesn't.
Every CMS-style operator console specializes the H1.

**Sources:** current-state M6.

**Closest arXMCP analog today:** `base.html:49`.

**Sketch:** 2 template edits.

**Open questions:** none.

---

### UPL-19 — Mobile responsiveness baseline

**Category:** Layout
**Size:** S
**Evidence triangulation:** 1 brief (visual G3, partly current-state M5)
**Motion primitives:** none.

**What it is:** wrap each `<table>` in an `<div class="table-wrap">`
with `overflow-x: auto`; change `body { max-width: 980px }` to
`body { max-width: min(95vw, 1400px) }`. Mobile (390×844) gets
horizontal scroll within the table; wide displays (>27") get more
content width.

**Why it matters:** visual G3 shows tables clipping right-of-viewport
on mobile with no recovery; current-state M5 cites awkward
whitespace on wide displays. Single change addresses both.

**Sources:**
- Visual G3: `screenshots/home-mobile.png`, `screenshots/notebooks-
  bridgeland-stability-mobile.png`.
- Current-state M5: `app.css:25` (hard-coded `max-width: 980px`).

**Closest arXMCP analog today:** `app.css:25`.

**Screenshot evidence:** `home-mobile.png`, `notebooks-bridgeland-stability-mobile.png`.

**Sketch:** add `<div class="table-wrap">` wrappers in two templates;
add CSS:
```css
.table-wrap { overflow-x: auto; }
body { max-width: min(95vw, 1400px); }
```
~3 CSS lines + 2 template edits.

**Open questions:** does the mobile responsiveness justify a deeper
container-query pass? Out of scope for v1; the wrap + clamp pattern is
enough to clear the floor.

---

### UPL-20 — Disabled-Preview affordance

**Category:** Accessibility / Interaction
**Size:** XS
**Evidence triangulation:** 1 brief (current-state M3) — subsumed under UPL-17 but worth a separate ID for tracking

**What it is:** see UPL-17's M3 sub-point. Listed separately so
operators can ship without the empty-state expansion if needed.

**Open questions:** ship as part of UPL-17 or independently? Phase 4's call.

---

### UPL-21 — Poll backoff + Page Visibility API on `#ingest-status`

**Category:** Interaction (perf / battery)
**Size:** S
**Evidence triangulation:** 1 brief (visual G10) — single-source but strong network-log evidence
**Motion primitives:** none.

**What it is:** the `#ingest-status` div polls every 2s indefinitely;
30 reqs/min on an idle page (visual scout captured 12 polls in a 24s
window with no ingest in flight). Switch to backoff:
- Poll every 2s while a run is `running` / `queued`.
- Poll every 30s when the latest run is `complete` / `failed` / no
  runs.
- Pause when `document.hidden === true` (Page Visibility API).

**Why it matters:** quality-of-life; compounds across multiple open
tabs. The Page Visibility API pairs cleanly with the existing
JSON-shim.

**Sources:** visual G10.

**Closest arXMCP analog today:** `notebook_detail.html` ingest-status
polling config.

**Sketch:** htmx 2.x supports `hx-trigger="every 2s [condition]"` with
condition expressions. The server fragment can include an `HX-Trigger`
response header that tells the client "switch to 30s mode." Pair with
a small Page-Visibility listener in `base.html`'s existing inline
script that pauses/resumes via `htmx.trigger(elt, "htmx:abort")` /
`htmx.process(elt)`.

**Open questions:** does the `HX-Trigger` interval-change pattern work
without an htmx extension? Verify against htmx 2.0.10 docs;
alternatively use a server-side `hx-trigger="every {{ poll_interval }}s"`
that switches based on `latest_run.status`.

---

### UPL-22 — Footer badge fixed-width + flash-on-swap

**Category:** Layout / Motion
**Size:** XS (mostly subsumed by UPL-10)
**Evidence triangulation:** 1 brief (visual G7) + current-state M4 (flash-on-swap)
**Motion primitives:** `[MOT-10 breathing-glow]` (optional, on `ok` state) + `[MOT-14 data-tick-flash]` on swap-in (gated by UPL-1).

**What it is:** reserve a `min-width` on `.status-badge` so the footer
doesn't reflow across DEGRADED/WARN/OK/DOWN/ops-warn state changes;
add a brief CSS flash on the `htmx-settling` swap so operators see
"the badge just refreshed."

**Why it matters:** badge reflows every 10s; the polling is silent.
Operators can't tell if the badge value reflects "now" or "5 minutes
ago."

**Sources:** visual G7 + current-state M4.

**Closest arXMCP analog today:** `.status-badge` rules at
`app.css:114-126`.

**Sketch:** ~6 CSS lines:
```css
.status-badge { min-width: 14ch; }
@media (prefers-reduced-motion: no-preference) {
  .status-badge.htmx-settling {
    animation: flash 400ms ease-out;
  }
  @keyframes flash {
    from { background: color-mix(in oklab, var(--accent) 30%, transparent); }
    to { background: transparent; }
  }
}
```

**Open questions:** does `min-width: 14ch` truncate WARN/DOWN
labels? No — `ch` is based on `0` width; 14ch is wider than
`DEGRADED | corpus v999 | 99 notebooks`.

---

### UPL-23 — Micro-a11y cleanups (footer `·` + L4)

**Category:** Accessibility
**Size:** XS
**Evidence triangulation:** 1 brief (current-state L4)

**What it is:** wrap the footer middle-dot separators in `<span
aria-hidden="true">·</span>` so SRs don't read "middle dot" /
"interpunct" between every footer link.

**Why it matters:** footer is noisy on SRs.

**Closest arXMCP analog today:** `base.html:57-67`.

**Sketch:** 5 spans.

**Open questions:** none.

---

### UPL-24 — Cosmetic CSS micro-polish bundle

**Category:** Cross-cutting refactor
**Size:** XS
**Evidence triangulation:** 1 brief (current-state L1 + L2 + L3)

**What it is:** three small fixes bundled:
1. `input[name="display_name"]` shouldn't be monospace — override the
   `app.css:73` broad `input[type="text"]` rule.
2. Add a `button:active, .button:active { filter: brightness(0.92); }`
   press-state (gated by `prefers-reduced-motion: no-preference` for
   the optional translateY).
3. Fix the vendor-stamp comment at `app.css:1-2` to reflect
   accumulated m1+m4 contributions.

**Sketch:** ~6 CSS edits.

**Open questions:** none.

---

### UPL-25 — favicon + `/favicon.ico` 403 fix

**Category:** Layout
**Size:** XS
**Evidence triangulation:** 1 brief (visual G14)

**What it is:** add `<link rel="icon">` in `base.html` pointing to a
1×1 transparent PNG (or simple SVG) under `/ui/static/favicon.svg` so
the browser stops requesting `/favicon.ico` and getting 403s. Pair
with UPL-7's SecFetchSite-render fix.

**Why it matters:** devtools noise; potential server-log noise.

**Closest arXMCP analog today:** no current favicon.

**Sketch:** ~3 lines (one HTML, one static asset, one CSP self-source
check).

**Open questions:** none.

---

## 5. Cross-cutting tensions

1. **Dark mode severity disagreement (UPL-8).** Visual G13 = LOW
   ("loopback-only single-operator; not a baseline"); current-state H3,
   library A5, inspiration CAND-6 = HIGH ("white-flash on dark-OS reads as
   'untouched'"). **Resolution:** Phase 4 ranks as MEDIUM-HIGH —
   high-value SOTA polish, but explicitly behind the a11y triad and the
   bug-fix tier. Reasonable for an arXMCP operator to install in light
   mode if needed; dark-mode is parity, not baseline.

2. **Visual scout's CRITICAL bug-fixes (UPL-5/6/7) vs polish.** The
   visual scout's three CRITICAL findings are not "polish" — they are
   bugs in shipped UI behavior (silent rename, raw-JSON empty state,
   raw-JSON middleware rejection). Phase 4 should rank these ABOVE all
   polish candidates (RICE confidence ceiling: single-source but
   evidence-from-live-walk warrants C=1.0). They could be tracked as
   regular `/milestone-pipeline` work outside the uplift, but bundling
   them keeps the operator-experience improvement coherent.

3. **`location.reload()` conversion (UPL-12) widens the UI security
   audit.** Server-side fragment-rendering is new surface for the open
   `chris-dare-dev/arXMCP#9` audit. Resolution: flag explicitly in the
   milestone brief; the audit covers this independently.

4. **Inspiration scout proposed scholarly metadata-strip styling
   (UPL-16) — current-state critic preferred to bundle a11y triad
   FIRST.** Both are right. Resolution: UPL-1..4 land first as the
   foundational pass; UPL-16 lands next in the polish tier.

5. **The library scout said the htmx-extension licenses need
   pre-vendoring verification** (B1-B3 — class-tools, loading-states,
   response-targets). The current synthesis ranks these as
   optional follow-ups (subsumed under UPL-11's "optional vendor
   extension" + UPL-21's "alternative implementation"). Pre-vendoring
   verification is the Phase-3 (or implementer's) responsibility.

---

## 6. Already considered + rejected

From the briefs' parking-lot sections + scout judgement, the following
candidates were considered but do NOT enter the catalog:

- **Cmd-K command palette** — no global search target yet; defer until
  notebook count grows or a search surface lands.
- **Distill margin asides / two-column scholarly layout** — wrong
  content shape (arXMCP is form-driven, not prose-driven).
- **Quanta-style hero imagery** — no marketing surface.
- **NotebookLM source-list sidebar** — implies chat-with-notebook
  functionality arXMCP doesn't have.
- **Auto-rotating spotlight** — anti-pattern MOT-NO-3.
- **Magnetic-cursor on destructive buttons** — anti-pattern MOT-NO-4.
- **Confetti on ingest success** — anti-pattern MOT-NO-7.
- **Parallax on operator console** — anti-pattern MOT-NO-2.
- **Custom web font (Inter / IBM Plex / Source Serif)** — adds CSP
  `font-src` widening + network fetch; system-ui stack is excellent.
- **picocss** — replaces, doesn't extend, the 8-token discipline.
- **MathJax / KaTeX** — ar5iv preview tab loads pre-rendered HTML.
- **Auth / multi-user / OAuth** — loopback-only design.
- **Tailwind / shadcn / Framer / Recharts / Zustand / TanStack /
  Vite / Vue / Svelte / Next.js / React** — automatic Phase-3 BLOCKER
  per CLAUDE.md §4.7.
- **Alpine.js** — overlaps htmx.
- **sortable.js** — no drag-reorder surface today.
- **htmx-ext-multi-swap / head-support / morphdom-swap** — no use case
  today; morphdom superseded by idiomorph.
- **`animation-timeline: scroll()`** — not yet Baseline Widely
  Available (Firefox flag-gated); operator console has no eligible
  scroll-driven surface anyway.
- **CSS Anchor Positioning** — not yet Baseline; `popover` covers the
  only conceivable need.
- **Container queries** — single breakpoint suffices for v1; revisit
  if card grid grows.
- **idiomorph** — library scout suggested but optional; arXMCP's
  current swap targets are small enough that morphdom-style diffing
  isn't load-bearing. Park.
- **`:has()` declarative state styling** — library scout flagged
  Baseline status as "Newly → Widely Available ~2026-06"; use only as
  progressive enhancement; not a foundational candidate today.
- **`popover` attribute (native popover/modal)** — no Delete-confirm
  surface today uses `hx-confirm`'s browser-default alert(). Park
  until a richer confirmation flow is needed.

---

## 7. Motion-vocabulary index

Map of `[MOT-N]` primitives → candidates that cite them:

| MOT-N | Primitive | Candidates |
|---|---|---|
| MOT-1 | `fade-in` | UPL-6 (empty-state), UPL-17 (empty-state card) |
| MOT-10 | `breathing-glow` | UPL-14 (running ingest pill — optional), UPL-22 (footer badge ok state — optional) |
| MOT-13 | `skeleton-shimmer` | UPL-11 (in-flight buttons) |
| MOT-14 | `data-tick-flash` | UPL-16 (Last indexed flash), UPL-22 (footer badge swap flash) |
| MOT-30 | `lift-on-hover` (light) | UPL-15 (table-row hover) |
| MOT-32 | `border-on-hover` | UPL-15 (table-row focus-within) |
| MOT-33 | `icon-spin-on-action` | UPL-11 (request spinner) |
| MOT-34 | `focus-visible-glow` | UPL-2 (baseline focus rings) |
| MOT-50 | `htmx-swap-fade` | UPL-12 (in-place swaps), UPL-13 (View Transitions) |
| MOT-52 | `view-transitions-api` | UPL-13 |
| MOT-NO-5 | (anti-pattern: continuous motion without reduced-motion gate) | **prevented by UPL-1** — the universal gate |

Every motion-cited candidate honors `prefers-reduced-motion: no-preference`
via UPL-1's adoption as a prerequisite.

---

## 8. Orchestrator synthesis note

- All 4 scouts returned `status: ok`. Total findings: 17 (current-state)
  + 14 (library) + 12 (inspiration) + 15 (visual) = 58 distinct
  observations; deduped to 25 candidates after triangulation.
- 4-brief-source candidates (UPL-1, -2, -3, -4, -8, -10) form the
  highest-confidence Phase-4 anchor.
- Visual scout's 3 CRITICAL findings (UPL-5, -6, -7) are single-source
  by necessity (no other scout could see them) but carry C=1.0
  confidence because of live-walk evidence — the synthesis treats
  these on par with 4-brief candidates for Phase 4 RICE Confidence.
- One soft follow-up: `ensure-preview-up.sh` should additionally check
  that `var/arxmcp/index/lancedb/corpus-version.json` exists before
  declaring preflight green (per visual scout coverage note §9). This
  is meta-tooling, not part of the uplift catalog.

*End of synthesis.*
