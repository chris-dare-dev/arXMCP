# Visual scout brief — 2026q3-ui-uplift

**Evidence-tier notice (read before anything else):** this run had **no browser-preview
tool available** (grant was `Bash, Read, Grep, Glob, Write` only; ToolSearch /
`preview_*` / `Claude_in_Chrome` were explicitly withheld). **There are NO PNG
screenshots under `screenshots/` — the directory is confirmed empty.** All visual
findings below are built from two sources: (1) the orchestrator's
`discover/visual-manifest.md` — live-measured DOM geometry, computed styles, and
tap-target dimensions from an actual rendered session (tier **`✓ measured`**), and
(2) my own direct reads of `server/frontend/static/app.css` (371 lines, the entire
stylesheet) and the three Jinja2 templates, cross-verified against live `curl` calls
to `http://127.0.0.1:7733` (tier **`✓ code`**/`✓ measured`, timings all <10ms, no
4xx/5xx on any walked route). Per the hard rule "no screenshot → no finding," every
gap below is anchored to a specific measured pixel value, a specific CSS rule (or its
absence, confirmed by `grep`), or specific HTML markup — never a subjective visual
impression that geometry can't support. Nothing here is `~ inferred`.

**Preview route (`/ui/notebooks/{slug}/papers/{paper_id}/preview`) was NOT walked.**
All 6 papers in the seeded `uplift-demo` notebook were added via `POST
.../papers` (URL paste), which does not store on-disk ar5iv HTML — `has_preview`
is `false` for all of them, and `curl` confirms `GET .../preview` correctly
returns `404 {"detail":"no preview available"}` (verified live). I checked every
other notebook in this deployment (`bridgeland-stability`,
`bridgeland-stability-pdfs`, `fourier-duality`, `fourier-duality-pdfs`,
`my-notebook`) for a paper with a working preview link and found none — the
`bridgeland-stability*` notebooks in particular have 0 papers via the `/ui/api`
surface in this live deployment (their large corpora were ingested directly into
LanceDB in a different session, bypassing the per-notebook papers metadata
store). Per the task's "do not create or delete notebooks" instruction I did not
upload a file to force a preview into existence. **This is a correct 404, not a
broken page** — I am not filing it as a CRITICAL "unrenderable page" finding — but
it IS a real evidence gap: the preview surface (document-view, tight CSP, "chrome
recedes" per the design system's house direction) is un-audited this run. Flagged
for a follow-up pass with an uploaded fixture.

---

## TL;DR

The single biggest visual gap is **information architecture on `/ui/notebooks/{slug}`**:
the page stacks seven identically-weighted `.card` panels in a single column, six of
them input forms, so the papers table — the only actual corpus content on the page —
starts at `y=1823` of a `2343px` document, more than **2× a 900px viewport's worth of
scrolling below the fold**, dead last after Meta/Rename/Delete, Topic, Discover,
Add-by-URL, Upload, and Ingest. The second-biggest gap is genuine **visual sameness**:
every one of those seven cards (plus every card on `/ui/`) shares the exact same
`border-radius:6px`, 1px `--border`, zero `box-shadow` (confirmed absent from all 371
lines of `app.css`), zero `transition` property outside the reduced-motion clamp, and
one effective typographic step (`h2` at 17.6px vs body 16px — a 1.10× ratio the eye
can't register, so hierarchy is carried by weight alone) — this flat, undifferentiated,
default-bordered-box assembly is exactly the arXMCP design system's own named
anti-reference (BAN-4, "untouched default stack look... with only 8 tokens and one
CSS file, the discipline IS the design; a default assembly reads as no design") and is
the most legitimate reading of "looks AI-generated / standard shadcn feel" in the
current UI. Overall visual-coherence rating: **credible but flat** — nothing is broken,
contrast is genuinely well-measured (not asserted), dark mode and reduced-motion are
correctly gated everywhere they appear, but the product currently has one visual
register (quiet) with no second register (a legible "this is the important thing"
signal), which is a real cost on the one page (`notebook_detail.html`) that has seven
competing sections.

## Per-route observations

### `/ui/` (landing) — walked via manifest geometry + live `curl`

Two cards stacked in a single column at 1440×900: "Create notebook" (a 4-field form,
`y=124` to `y=490`) above "Existing notebooks (5)" (a 4-column table, `~y=510` to
`~y=803`). `docHeight` is a modest 987px — this route does NOT have the IA problem the
detail page has, because there's only one form and it's genuinely the primary action
for a first-time operator. `curl` confirms 200 OK, 248 lines of HTML, ~2.7ms TTFB.

Gaps found:
- Oversized form inputs (1251px wide for short values) — see MEDIUM-3.
- No table-row hover feedback — see cross-route pattern.
- Card sameness (create-form card and passive-list card read identically) — see HIGH-2.

Screenshots: **none** (see evidence-tier notice). Geometry table: manifest §3
"`/ui/` (landing)".

### `/ui/notebooks/uplift-demo` (detail) — walked via manifest geometry + live `curl`

The dense workflow page: seven `.card` sections in one column, `docHeight 2343px` at
desktop, `2976px` at mobile (390 CSS px). This is where the IA and sameness gaps
concentrate — see CRITICAL-1 and HIGH-1/2/3 below. `curl` confirms 200 OK; the papers
table itself renders correctly (6 rows, 49px row height, no overflow at desktop; scrolls
internally via `.table-wrap` on mobile with zero page-level horizontal overflow).

Gaps found:
- Papers table buried at y=1823 after 6 forms — CRITICAL-1.
- 7 identically-weighted cards, zero elevation, zero hierarchy signal — HIGH-2.
- Zero `hx-indicator` across 9 htmx elements; thin in-flight feedback for
  multi-second calls (Discover, Ingest) — HIGH-3.
- Native `window.confirm()` for both destructive actions (Delete notebook, Remove
  paper) — HIGH-4.
- 12 `aria-live="polite"` regions on one page (verified: 11 in
  `notebook_detail.html` + 1 inherited from `base.html`'s footer badge — grep
  cross-check matches the manifest's measured count exactly) — MEDIUM-2.
- `#ingest-status` swaps (2s poll) carry zero visual settle signal, unlike the
  footer badge's `badge-flash` — MEDIUM-4.
- Tap targets under 44px everywhere: every button 32px tall, `<select>` 19px tall
  — HIGH-5 (mobile).

Screenshots: **none** (see evidence-tier notice). Geometry table: manifest §3
"`/ui/notebooks/uplift-demo` (detail)".

### `/ui/notebooks/uplift-demo/papers/{paper_id}/preview` — NOT walked

No paper in the live deployment has stored ar5iv HTML (see evidence-tier notice
above). `curl` confirms the route responds correctly (`404`,
`{"detail":"no preview available"}`) for all 6 seeded papers — this is correct
behavior, not a broken page. No findings filed for this route this run; recommend
a follow-up pass with a paper uploaded via the "Upload ar5iv HTML" card so the
preview's actual chrome (or lack thereof, per design-system §7 "the ar5iv preview
route has no shared chrome... the absence of a way back is a real UX gap") can be
visually audited.

Screenshots: none captured (route not reachable with current fixture data).

### `/ui/status-badge` (htmx fragment) — walked via manifest + live `curl`

`curl` confirms the raw fragment: a 491×22px `<span>` at `min-width:14ch`, mono
12px, polling `every 10s`, correctly carrying `aria-live="polite" aria-atomic="true"`
on every server-rendered response (I re-fetched it live and the attributes are
present — this is NOT a one-time SSR-only claim, the poll target itself emits them,
which is the correct pattern per the template's own inline comment warning about
exactly this failure mode). One structural gap: `.status-badge__remediation`
(the `<small>` sub-element carrying "status non-pass — see docs/install.md
troubleshooting") has no CSS rule anywhere in `app.css` — it inherits bare `<small>`
UA styling and renders inline, so the whole badge becomes a 491px-wide run-on
line instead of a pill + a distinct caption line. See MEDIUM-1.

Screenshots: none (see evidence-tier notice).

---

## Critical gaps

### CRITICAL-1 — Papers table is the last thing on the page, six forms deep

- **Route affected:** `/ui/notebooks/{slug}` (detail)
- **Screenshot evidence:** none — geometry is manifest §3, cross-verified live via
  `curl http://127.0.0.1:7733/ui/notebooks/uplift-demo` (200 OK, template order
  matches `notebook_detail.html` source order exactly: meta/rename/delete →
  topic → discover → add-by-URL → upload → ingest → papers).
- **What an operator sees:** Opening any notebook to check on its papers — almost
  certainly the single most common reason to open this page — puts the papers
  table at `y=1823` of a `2343px` document. At the standard 1440×900 viewport the
  operator sees, in order: notebook meta + rename + delete controls (`y=161–519`),
  a topic-editing form (`y=535–845`), a discovery-search form (`y=861–1055`), an
  add-by-URL form (`y=1071–1282`), an ar5iv-upload form (`y=1297–1603`), and an
  ingest-trigger form (`y=1620–1807`) — **six consecutive input surfaces, zero
  corpus content** — before the "Papers in this notebook (6)" table appears at
  all. An operator has to scroll past more than two full 900px screens of forms to
  see a single paper ID. This is not a hypothetical scroll cost: it inverts the
  page's own stated priority. The template's own comments describe parse-status +
  freshness as the thing that "answers 'is this notebook usable?'" — that lives in
  card 1, correctly — but the papers themselves, the actual answer to "what's in
  this notebook," is buried under every mutating control the page offers.
- **What 2026 SOTA would look like:** Reorder so the papers table (the primary
  content) sits immediately after the meta/status card, with the five
  mutation forms (Topic, Discover, Add-by-URL, Upload, Ingest) collapsed into a
  secondary "Manage" region — either a `<details>`-based disclosure (native HTML,
  zero JS, already reduced-motion-safe) or a tab strip using
  **[MOT-16 tab-content-swap]** (a vanilla-JS `hidden`-attribute toggle is
  sufficient; no library needed — arXMCP's own `htmx.config.globalViewTransitions`
  pattern in `base.html:38-44` already demonstrates the project's appetite for
  small vanilla-JS conveniences gated on reduced-motion). If the five-forms-stacked
  layout is kept for now, at minimum the papers table should be pulled directly
  under the meta card and the forms pushed below it — a template reorder with zero
  new CSS.
- **Severity:** CRITICAL. This is the one finding in the brief that crosses from
  "flat" into "actively works against the operator's most common task" — every
  dev-tool comparator (GitHub file browser, Linear issue list, Vercel deployment
  list) puts the primary content-of-interest above secondary settings/mutation
  forms, and arXMCP inverts that on its single dense page.
- **Closest existing arXMCP pattern:** `frontend/templates/notebook_detail.html`
  (the `{% block content %}` section-ordering, lines 8–361 — the papers `<section
  class="card">` is literally the last one in source order, lines 300–361); no CSS
  change needed for the reorder, only template restructuring.

---

## High gaps

### HIGH-1 — Card sameness: zero visual hierarchy between primary and secondary surfaces

- **Route affected:** `/ui/`, `/ui/notebooks/{slug}` (both routes; worst on detail)
- **Screenshot evidence:** none — confirmed via direct read of `app.css:53-59`
  (`.card` rule) applied identically to every `<section class="card">` in both
  templates (2 on `/ui/`, 7 on the detail page) and via `grep -n "box-shadow"
  server/frontend/static/app.css` returning **zero matches** across all 371 lines.
- **What an operator sees:** Every `.card` — the primary "Create notebook" form,
  the passive "Existing notebooks" list, the notebook's own identity/status block,
  five different mutation forms, and the papers table — renders with the identical
  `border: 1px solid var(--border); border-radius: 6px; padding: 1rem 1.25rem;
  margin-bottom: 1rem` and no `box-shadow` anywhere in the stylesheet. There is no
  silhouette difference between "this is the thing you came here to read" (the
  papers table, the notebook's parse-status) and "this is a form you might use
  once" (Topic, Discover, Upload). Combined with a near-imperceptible type scale
  (`h2` 17.6px vs body 16px, a 1.10× step — hierarchy is carried entirely by
  font-weight, 700 vs 400, not size) the page reads as a uniform stack of gray
  boxes.
- **What 2026 SOTA would look like:** Give the content-bearing card(s) — papers
  table, notebook meta/status — one differentiator the CSS system doesn't already
  spend elsewhere: e.g. a 2px `border-left: 2px solid var(--accent)` accent stripe
  (uses the existing `--accent` token, no new token invented, per design-system
  §10's citation discipline) OR a subtle background lift using `color-mix(in
  oklab, var(--card-bg) 97%, var(--fg))` (the exact color-mix pattern already used
  for `button:hover` at `app.css:106`, so it's an idiom already in the codebase,
  not a new technique). Pair with **[MOT-21 hover-lift]** on interactive cards
  (translate-y + a very small shadow — the FIRST `box-shadow` in the file, used
  deliberately rather than omitted entirely) so hovering the notebook row on `/ui/`
  gives tactile feedback. This directly answers the user's "looks AI-generated"
  complaint: the fix is not more chrome, it's ONE differentiator applied
  selectively, which is what shadcn/Tailwind defaults conspicuously don't do
  (every `<Card>` instance looks the same unless a consumer overrides it — arXMCP
  hasn't overridden it anywhere).
- **Severity:** HIGH — this is a comparator-level gap (every mature dev-tool
  console differentiates primary/secondary surfaces) and it is the most direct,
  honest answer to the "standard tailwind+shadcn feel" half of the brief: it's not
  that arXMCP added shadcn, it's that arXMCP's single hand-rolled `.card` class
  behaves exactly like an un-styled shadcn `<Card>` — same silhouette everywhere,
  no accent, no elevation, no weight variation.
- **Closest existing arXMCP pattern:** `.card` at `app.css:53-59`;
  `color-mix(in oklab, ...)` idiom already present at `app.css:106`
  (`button:hover`); `--accent` token at `app.css:15`. Design-system anti-reference:
  `arxmcp-design-system.md` BAN-4 ("Untouched default stack look... a default
  assembly reads as no design").

### HIGH-2 — Zero `hx-indicator`: thin in-flight feedback for multi-second operations

- **Route affected:** `/ui/notebooks/{slug}` (detail — Discover, Ingest, Upload
  specifically)
- **Screenshot evidence:** none — confirmed by grepping every template file for
  `hx-indicator`: zero matches in `index.html`, `notebook_detail.html`, or
  `base.html` (the only match anywhere in the repo is the string
  `indicatorClass` inside the vendored, unmodified `htmx.min.js` config object —
  i.e. the library supports the attribute but it is never actually set on any
  element). Manifest §4 independently confirms this ("`hx-indicator` is set on
  ZERO elements") against the live-rendered DOM.
- **What an operator sees:** Nine `hx-*`-bearing elements on the detail page (7
  forms + 2 poll targets); the ONLY in-flight signal available on any of them is
  the global `.htmx-request { opacity:.6; cursor:wait }` rule plus a small
  `::after` spinner glued to the submitting button (`app.css:293-333`). For a
  quick PATCH (rename, topic save) this is adequate. For **Discover** (a live
  round-trip to the arXiv Atom API) and **Ingest** (spawns a background
  subprocess, then polls every 2s) the only visible change during the wait is one
  button dimming to 60% opacity — the rest of the page, including the section
  where results will eventually land (`#discover-results`, `#ingest-status`),
  stays static and unlabeled. An operator triggering Discover on a slow network
  has no way to distinguish "still searching" from "the button click didn't
  register" beyond staring at one 80×32px button.
- **What 2026 SOTA would look like:** An explicit `hx-indicator` targeting the
  results region itself (not just the button) paired with **[MOT-8
  shimmer-skeleton]** — a placeholder row or two rendered into
  `#discover-results` the moment the request fires, replaced by real results on
  swap. Pure CSS (a `background: linear-gradient(...)` shimmer keyed to a
  `@keyframes` already-gated pattern identical to the existing `spin` and
  `badge-flash` keyframes at `app.css:317-370` — no new animation infrastructure,
  just a third gated keyframe following the exact pattern already established).
  For Ingest specifically, since it's a genuinely long-running background
  subprocess, a short status line ("Ingest started — checking every 2s…") inside
  `#ingest-status` before the first poll resolves would close the gap without any
  library.
- **Severity:** HIGH — Discover and Ingest are the two operations on this page
  with real network/subprocess latency (not sub-100ms local writes), and both
  currently get the same minimal feedback as the instant PATCH operations.
- **Closest existing arXMCP pattern:** `.htmx-request` opacity/spinner rule at
  `app.css:293-333`; the `badge-flash`/`row-fade-out` keyframe pattern at
  `app.css:335-370` is the template to extend, not replace.

### HIGH-3 — Native `window.confirm()` breaks the themed instrument-panel visual thesis

- **Route affected:** `/ui/notebooks/{slug}` (Delete notebook, Remove paper),
  `/ui/` (Remove notebook)
- **Screenshot evidence:** none — confirmed by direct read of
  `notebook_detail.html:86` (`hx-confirm="Delete notebook '{{ notebook.slug }}'?
  ..."`), `notebook_detail.html:350` (Remove paper), and `index.html:111` (Remove
  notebook) — all three destructive actions route through htmx's `hx-confirm`
  attribute, which htmx implements as a bare browser-native `window.confirm()`
  call (confirmed against the vendored `htmx.min.js` behavior; there is no custom
  confirm dialog markup anywhere in either template).
- **What an operator sees:** Clicking any of the three destructive buttons pops
  the browser's own unstyled system confirm dialog — plain OS chrome, system font,
  no relationship to any of the 8 CSS custom properties this console otherwise
  uses consistently. In the dark-mode session this manifest was captured in
  (`prefers-color-scheme: dark` active, confirmed by the manifest's measured
  `--fg #e8e8e8` / `--bg #0d1117` values), this is the single moment in the entire
  product where the operator sees a bright, light-themed native dialog flash
  against the dark instrument-panel background — the opposite of the "quiet
  local instrument panel" thesis this codebase otherwise defends carefully (dark
  mode itself, `color-scheme: light dark` at `app.css:10`, contrast pairs computed
  rather than asserted per the design system §4).
- **What 2026 SOTA would look like:** Replace `hx-confirm` with an in-page
  two-stage button pattern reusing the existing `.danger` class — first click
  swaps the button label to "Confirm delete?" (a plain `htmx.on('click', ...)`
  vanilla-JS toggle, or even a `<details>`/`radio` CSS-only trick for the
  non-htmx case), second click within a short window fires the real
  `hx-delete`. No new token, no new library — `.danger` already exists
  (`app.css:108`). For non-catastrophic removals (Remove paper, which is
  reversible by re-adding the URL) consider **[MOT-50 undo-toast]** instead of a
  confirm gate entirely — remove immediately, show a themed toast with "Removed
  — Undo" for a few seconds. This is exactly the class of change the motion
  vocabulary's anti-pattern table treats as in-budget on S-2 surfaces (it's a
  feedback job, not decoration).
- **Severity:** HIGH — three of the highest-consequence interactions in the
  product (delete, delete, remove) are the only three moments the UI's own visual
  language (dark mode, tokens, typography) doesn't apply at all.
- **Closest existing arXMCP pattern:** `button.danger` at `app.css:108`;
  `hx-confirm` usage at `notebook_detail.html:86,350` and `index.html:111`.

### HIGH-4 — Tap targets under 44px on the densest, most form-heavy mobile page

- **Route affected:** `/ui/notebooks/{slug}` (mobile, 390×844)
- **Screenshot evidence:** none — manifest §3 "Mobile" table, live-measured:
  every `button` is **32px tall** (Rename 77×32, Delete notebook 131×32, Save
  topic 91×32, Discover 80×32, Add 53×32, Upload 72×32, Ingest now 95×32, and
  **six separate 77×32 "Remove" buttons** in the papers table), `select` is
  **19px tall**, `input[type=text|url]` is 33px tall.
- **What an operator sees:** On a phone, every actionable control on the page's
  busiest surface is meaningfully smaller than the WCAG 2.5.8 (AAA) / Apple HIG
  44pt minimum tap target — the `<select>` at 19px is especially small, well
  under half the recommended minimum, on a page that already asks for six
  distinct form submissions. The six 77×32px "Remove" buttons sit in a table
  column immediately next to a `<time>` element and a "Preview" link/span, so a
  slightly-off tap risks hitting an adjacent row's control on a destructive
  action.
- **What 2026 SOTA would look like:** Raise `button`/`.button` padding at a
  mobile breakpoint (`padding: 0.6rem 0.85rem` gets close to 40px+ without a new
  token) and give `select` explicit `padding` (currently it inherits no rule at
  all in `app.css` — there is no `select { }` block, so it renders at native UA
  height, which is exactly the 19px measured). A `@media (max-width: 480px)`
  block bumping interactive-element `min-height: 44px` closes this without
  touching desktop density.
- **Severity:** HIGH — this is a comparator gap every mature mobile-aware
  dev-tool console clears (WCAG 2.5.8 is an established, machine-checkable bar),
  and it concentrates on the page's most destructive-action-dense surface.
- **Closest existing arXMCP pattern:** `button, .button` at `app.css:87-98`
  (no responsive variant exists); `select` has **no dedicated rule anywhere** in
  `app.css` (confirmed — only `input[type="text|url|file"]` is styled), so it is
  entirely un-styled UA chrome, which explains the 19px height.

---

## Medium gaps

### MEDIUM-1 — Status-badge remediation caption has no CSS rule, renders as a run-on line

- **Route affected:** `/ui/status-badge` (footer fragment, present on every page)
- **Screenshot evidence:** none — confirmed live: `curl
  http://127.0.0.1:7733/ui/status-badge` returns
  `<span ... class="status-badge status-badge--ops-warn" ...><small
  class="status-badge__remediation">status non-pass — see docs/install.md
  troubleshooting</small></span>`; `grep -n "status-badge__remediation"
  server/frontend/static/app.css` returns zero matches.
- **What an operator sees:** The badge itself is correctly styled (a 491×22px
  mono pill, `min-width:14ch` for stable width across states, per m4 UPL-22).
  But `.status-badge__remediation` — the human-readable "what do I do about
  this" text — has no rule at all, so it inherits bare `<small>` UA defaults and
  renders inline immediately after the badge label with no visual separation:
  the whole thing reads as one long run-on string rather than "pill, then a
  distinct caption."
- **What 2026 SOTA would look like:** A small rule making
  `.status-badge__remediation` a `display: block` line with `color: #555`
  (dark override `#b3b9c0`, matching the existing `.hint` pattern at
  `app.css:62` and its dark redeclaration at `app.css:271`) and a touch of
  `margin-top`. No new token, reuses the `.hint` color idiom exactly.
- **Severity:** MEDIUM — cosmetic but visible on literally every page load
  whenever the daemon is in a non-`READY` state (which this live session
  currently is — `ops-warn`, "awaiting first ingest").
- **Closest existing arXMCP pattern:** `.status-badge` at `app.css:152-168`;
  `.card .hint` color idiom at `app.css:62` / dark override `app.css:271`.

### MEDIUM-2 — 12 `aria-live="polite"` regions on one page, 7 of them empty error `<pre>`s

- **Route affected:** `/ui/notebooks/{slug}` (detail)
- **Screenshot evidence:** none — cross-verified two ways: manifest §4
  ("12 `aria-live="polite"` regions on one page... 7 of them empty `<pre
  class="error">`") and my own `grep -n "aria-live="
  server/frontend/templates/notebook_detail.html` filtered to real HTML
  attributes (not Jinja comment prose), which returns **11** matches in
  `notebook_detail.html` + **1** inherited from the footer badge in
  `base.html` (which every page extends) = **12**, matching the manifest
  exactly.
- **What an operator sees:** This isn't purely visual, but it's a state-legibility
  gap the brief explicitly asks about: every one of the page's 7 forms carries
  its own `<pre id="…-error" class="error" aria-live="polite">` (empty until a
  4xx response fills it) PLUS the content regions (`#display-name-block`,
  `#topic-block`, `#discover-results`, `#papers-tbody`, `#ingest-status`, footer
  badge) also announce. A screen-reader operator submitting the Ingest form gets
  the ingest-status live region announcing AND, separately, an empty error
  `<pre>` that never fires unless there's a failure — 12 independently-live
  regions is a lot of surface for one page to manage without one of them going
  stale or double-announcing during a fast sequence of swaps (e.g. Add paper
  clearing the URL input while the tbody also announces the new row).
- **What 2026 SOTA would look like:** Consolidate the 7 per-form error `<pre>`s
  into fewer live regions where forms are adjacent (e.g. one shared error region
  per card rather than one for the button AND one implicitly for the
  content-swap target), or demote the error `<pre>`s to `aria-live="assertive"`
  scoped ONLY when non-empty (they're currently empty 99% of the time and still
  counted as live regions by AT). This is a scope-reduction exercise, not a new
  feature.
- **Severity:** MEDIUM — compounds specifically on this one page (not
  cross-route), but it's real: 12 is a high count for a single-screen workflow.
- **Closest existing arXMCP pattern:** the `<pre id="…-error" class="error"
  aria-live="polite">` pattern repeats 7× verbatim across
  `notebook_detail.html` (lines 46, 61(in index.html), 143, 174, 217, 247, 271).

### MEDIUM-3 — Oversized form inputs relative to their expected content

- **Route affected:** `/ui/` (Create notebook), `/ui/notebooks/{slug}` (all 7
  form cards)
- **Screenshot evidence:** none — manifest §3: "Form inputs render **1251px
  wide** — a slug field ~12 characters long is given a 1251px input." Confirmed
  by `app.css:74-76`: `input[type="text"], input[type="url"], input[type="file"]
  { display:block; width:100%; ... }` — every text input is `width:100%` of its
  parent `.card`, which is itself `1293px` wide at 1440px viewport (per body's
  `clamp(640px, 92vw, 1400px)` at `app.css:37`).
- **What an operator sees:** A slug field expecting `bridgeland-stability`
  (≈20 characters) renders at 1251px — the input box is roughly 60× wider than
  its expected content. This isn't broken, but it reads as an un-tuned default
  (`width:100%` applied uniformly with no `max-width` override per field type),
  and it's part of why the page feels like an un-styled form-generator output
  rather than a hand-tuned instrument.
- **What 2026 SOTA would look like:** A `max-width` on short-content fields
  (slug, paper ID, discovery category select) — e.g. `input[name="slug"],
  input[name="paper_id"] { max-width: 32ch }` — while leaving genuinely
  long-content fields (arXiv URL, topic/description textarea) at `100%`. No new
  token; a targeted selector addition to the existing input rule block.
- **Severity:** MEDIUM — a quality-of-life / polish gap that recurs across every
  form on both routes, but doesn't block or confuse any workflow.
- **Closest existing arXMCP pattern:** `input[type="text"], input[type="url"],
  input[type="file"]` at `app.css:74-85`.

### MEDIUM-4 — `#ingest-status` swaps carry no visual settle signal

- **Route affected:** `/ui/notebooks/{slug}` (Ingest card, 2s poll)
- **Screenshot evidence:** none — confirmed by reading `app.css:335-370`: the
  `badge-flash` keyframe is scoped to `.status-badge.htmx-settling` only; there
  is no equivalent rule for `#ingest-status` or any other `.htmx-settling`
  target. `notebook_detail.html:288-297` shows `#ingest-status` polls every 2s
  via `hx-trigger` on the div... (actually trigger is on load; the *returned*
  fragment for a running ingest re-adds its own `every 2s` trigger per the
  manifest's htmx table) and swaps `outerHTML` with no accompanying visual cue
  beyond the raw text change.
- **What an operator sees:** While an ingest run is in progress, the status text
  updates every 2 seconds, but nothing on screen signals "this just refreshed" —
  contrast with the footer badge, which gets a genuine `badge-flash` pulse on
  every settle. An operator has to actively re-read the text to notice a change
  rather than catching a peripheral flash.
- **What 2026 SOTA would look like:** Extend the existing `badge-flash` keyframe
  (already `prefers-reduced-motion`-gated at `app.css:344`) to
  `#ingest-status.htmx-settling` — this is a one-selector addition to an
  already-shipped, already-correct pattern, not new motion infrastructure. Cite
  **[MOT-2 slide-up]** as an alternative if a stronger cue is wanted for the
  terminal success/failure state specifically.
- **Severity:** MEDIUM — a genuine but low-cost feedback gap, confined to one
  card on one route.
- **Closest existing arXMCP pattern:** `.status-badge.htmx-settling` /
  `badge-flash` at `app.css:344-351`.

---

## Low gaps

### LOW-1 — No table-row hover feedback on either data table

- **Route affected:** `/ui/` (notebooks table), `/ui/notebooks/{slug}` (papers
  table)
- **Screenshot evidence:** none — confirmed by `grep -n ":hover"
  server/frontend/static/app.css`: the only `:hover` rule in the entire file is
  `button:hover, .button:hover` (`app.css:105-107`); there is no `tr:hover` or
  `table.notebooks tr:hover` / `table.papers tr:hover` rule anywhere.
- **What an operator sees:** Moving the mouse down either table gives zero
  positional feedback until the cursor lands directly on a button or link — no
  row highlight to confirm "this is the row I'm about to act on" before
  clicking Remove.
- **What 2026 SOTA would look like:** A one-line `tr:hover { background:
  color-mix(in oklab, var(--card-bg) 95%, var(--fg)) }` — the same `color-mix`
  idiom already used at `app.css:106`, applied to table rows. Instant (no
  `transition`) is fine and consistent with the rest of the file's snap-state
  hovers; adding a `transition: background 100ms` would also close cross-route
  pattern XR-2 below if the team wants to address both at once.
- **Severity:** LOW — single-surface paper-cut, no workflow impact.
- **Closest existing arXMCP pattern:** `button:hover, .button:hover` at
  `app.css:105-107`.

### LOW-2 — Footer diagnostic links have sub-44px tap height on mobile

- **Route affected:** `/ui/notebooks/{slug}`, `/ui/` (footer, both routes)
- **Screenshot evidence:** none — manifest §3 "Mobile" table: footer
  `/healthz` measures 48×17px, `/readyz` measures 44×17px.
- **What an operator sees:** The two diagnostic footer links clear the 44px
  width minimum but fall well short on height (17px) on a touch viewport.
- **What 2026 SOTA would look like:** `footer a { display:inline-block;
  padding: 0.5rem 0; }` to pad the vertical hit area without changing the
  visible line height.
- **Severity:** LOW — these are low-frequency diagnostic links (health checks),
  not primary workflow actions.
- **Closest existing arXMCP pattern:** `footer a` at `app.css:48`.

### LOW-3 — No responsive type ramp

- **Route affected:** `/ui/notebooks/{slug}`, `/ui/` (mobile, both routes)
- **Screenshot evidence:** none — manifest §3 "Mobile": "`h1` stays **32px** —
  no responsive type ramp." Confirmed: `header h1` at `app.css:43` has no
  `@media` override anywhere in the file.
- **What an operator sees:** At 390px viewport width with 16px body padding
  unchanged from desktop (`app.css:29`), a 32px `h1` occupies a much larger
  fraction of the available width than on desktop — no imbalance severe enough
  to break layout (confirmed no horizontal overflow at mobile per the manifest),
  but the type scale doesn't adapt.
- **What 2026 SOTA would look like:** A `clamp(24px, 6vw, 32px)` on `header h1`
  — zero new tokens, a drop-in replacement for the hardcoded `32px`.
- **Severity:** LOW — cosmetic; the page remains fully usable and non-overflowing
  at mobile widths per the manifest's own measurement.
- **Closest existing arXMCP pattern:** `header h1` at `app.css:43`; the `clamp()`
  idiom is already used at `app.css:37` for `body { max-width }`, so this is
  the same technique applied one rule up.

---

## Cross-route patterns

1. **Zero elevation, anywhere.** `grep -n "box-shadow" server/frontend/static/app.css`
   returns no matches across all 371 lines — every card, button, and table on
   both routes is flat. This is the structural root of HIGH-1 (card sameness)
   and the honest core of the "looks default/AI-generated" complaint: a total
   absence of elevation isn't wrong on its own (many disciplined flat-design
   systems do this deliberately), but paired with an equally flat type scale and
   a single card silhouette, it removes every tool the CSS has for signaling
   "this matters more."

2. **Zero `transition` property outside the reduced-motion clamp.** `grep -n
   "transition"` finds only the two `transition-duration: 0.01ms !important`
   lines inside the `prefers-reduced-motion: reduce` block (`app.css:227,229`) —
   there is no `transition:` declaration anywhere that would apply during normal
   (non-reduced-motion) use. Every hover, including the one `button:hover`
   color-mix rule, is an instant snap rather than an eased shift. This is
   consistent, not a bug, but it means the 4 keyframe animations (spin,
   badge-flash, row-fade-out, view-transitions) are the ONLY eased motion in the
   entire product — everything else state-changes instantly. A future uplift
   adding `transition: background 100ms` (citing `MOT-24 hover-color-shift`,
   staying inside the `duration-fast` (100ms) token band per motion-vocabulary
   §9) to `button`, `.card` (if HIGH-1's hover-lift lands), and a new `tr:hover`
   rule would unify this cheaply, all still governed by the existing universal
   `prefers-reduced-motion` clamp with no additional gating needed.

3. **One effective typographic step, repeated on every route.** `h1` (32px) is
   the only size that reads as clearly different from body text; `h2`
   (17.6px) vs body (16px) is a 1.10× ratio carried entirely by `font-weight`
   (700 vs 400). This shows up identically on `/ui/` ("Create notebook" h2 vs
   its own label text) and on every one of the 7 cards on the detail page.
   It's the same root cause as HIGH-1, just at the type level rather than the
   container level.

4. **Reduced-motion + dark-mode discipline IS consistent cross-route — genuinely
   good, worth calling out positively rather than as a gap.** All 4 keyframe
   animations that exist are correctly scoped inside `@media
   (prefers-reduced-motion: no-preference)`, and the universal clamp at
   `app.css:223-232` catches anything future work adds. This consistency is real
   engineering discipline and should not be disturbed by any HIGH-1/HIGH-2
   motion additions — every proposal above explicitly reuses the existing gating
   pattern rather than introducing a new one.

5. **The "primary vs. secondary" ordering problem is not unique to CRITICAL-1's
   page — it's a pattern.** On `/ui/notebooks/{slug}`, five separate mutation
   forms (Topic, Discover, Add-by-URL, Upload, Ingest) all sit between the
   notebook's status card and its papers table, in an order that mirrors
   template authorship history (the milestone comments in the file — m1, m2,
   paper-discovery-m1/m4, m4, m9 — read as the literal order features were
   shipped in, not a deliberate information-architecture decision). This is
   the same underlying cause as CRITICAL-1, worth noting as a pattern rather
   than five separate findings.

---

## What arXMCP does well visually

- **Contrast is computed, not asserted, and holds in both themes.** The design
  system's own §4 table shows every `--fg`/`--accent`/`--danger` pair against
  both `--bg` and `--card-bg` clearing WCAG AA in light AND dark mode, with the
  tightest pair (dark `--danger` on `--card-bg`, 5.16:1) still comfortably above
  the 4.5:1 floor. This is real design-engineering rigor for an 8-token system.
- **`prefers-reduced-motion` is honored with real discipline, not lip service.**
  A universal clamp (`app.css:223-232`) PLUS every individual keyframe
  additionally scoped inside `@media (prefers-reduced-motion: no-preference)`
  (`app.css:317`, `344`) is belt-and-suspenders correctness that most production
  apps skip.
- **`tabular-nums` is applied precisely where it matters and nowhere else** —
  `time`, `.status-badge`, `dl.meta dd`, `td code` (`app.css:133-135`) — exactly
  the surfaces that swap numeric values on an htmx poll, and not blanket-applied
  everywhere. This is the kind of detail that's easy to skip and easy to
  over-apply; arXMCP got the scope right.
- **Mobile table containment genuinely works.** The manifest confirms zero
  horizontal page overflow at 390px viewport width despite a 4-column papers
  table — `.table-wrap { overflow-x: auto }` (`app.css:125`) does its job; the
  scroll is contained to the table, not the page.
  contained.
- **Accessibility scaffolding (skip-link, `:focus-visible`, live regions) is
  present and load-bearing, not decorative.** The skip-link targets a real
  `tabindex="-1"` `<main>` (correct pattern per MDN/WebAIM), focus rings widen
  appropriately on the one busy destructive button
  (`button.danger.htmx-request:focus-visible`), and `aria-live` regions
  genuinely re-emit their attributes across htmx swaps (verified live via curl
  on `/ui/status-badge`) rather than only working on first paint.
- **The whole visual system is genuinely auditable in one sitting** — 371 lines,
  8 tokens, 3 templates, 52 CSSOM rules. Nothing found in this brief required
  archaeology; every claim traces to a specific line. That smallness is itself
  a defensible design choice for a loopback single-operator console, and it's
  the honest reason most of the findings above are HIGH/MEDIUM rather than
  CRITICAL — the product is flat and under-differentiated, not broken.
