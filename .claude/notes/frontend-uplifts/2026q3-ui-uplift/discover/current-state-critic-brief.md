> **Standing correction to `arxmcp-design-system.md` §4/§7:** that overlay's §9 drift note already
> flags this, but re-stating for anyone skimming this brief in isolation — `ui-attractive-polish-m1..m5`
> shipped the `prefers-reduced-motion` universal gate, `:focus-visible` rings, the skip-link, the
> `prefers-color-scheme: dark` token remap, htmx `.htmx-request` loading states + spinner,
> `tabular-nums`, badge-flash / row-fade / View Transitions, and 12 `aria-live` regions on the detail
> page. None of that is re-flagged below as a net-new gap. Every finding here was verified against the
> LIVE `server/frontend/static/app.css` (371 lines / 52 CSSOM rules, read end-to-end) and the live
> route handlers, not against the stale gap tables in the reference overlays.

# Current-state critique — arXMCP `/ui/` operator console (2026q3-ui-uplift)

**Critic:** frontend-uplift-current-state-critic
**Scope:** `server/frontend/templates/{base,index,notebook_detail}.html`, `server/frontend/static/app.css`,
`server/routes/ui.py`, `server/routes/notebooks.py` (fragment-returning handlers).
**Evidence tiers:** every finding below is `✓ code` (file:line, this session) or `✓ live` (the
orchestrator's `visual-manifest.md` DOM/computed-style capture at `http://127.0.0.1:7733`, dark-mode
branch active). No `~ inferred` claims — where I could not verify a claim against the live file I
dropped it rather than guess.

---

## 1. Executive summary

Zero CRITICAL findings — arXMCP's `/ui/` is a 3-template, 371-line-CSS loopback console where nothing
I found actually breaks operator function; every gap is a **finish** gap, not a **works** gap. The
sharpest problems are, in order: **(1) `.status-badge__remediation` has no CSS rule anywhere in the
stylesheet**, so the ONE load-bearing trust signal (the operability badge) degrades into a 491px
unstyled run-on line at exactly the moment — a DEGRADED/DOWN state — an operator needs it to read
clearly; **(2) `<select>` and `<textarea>` carry zero base styling** (only appearing in the shared
`:focus-visible` selector list), so 4 form controls across both create/topic forms render as raw OS
widgets next to hand-styled siblings; **(3) the Discover-papers candidate list (`.discover-*`, 5
classes) has zero CSS**, so the one feature that produces new content renders as a bare bulleted list;
**(4) `notebook_detail.html` has no focal element** — 7 same-radius, same-border, same-shadow-none
`.card`s stack the actual content (the papers table) at y=1823px, below six input forms; and **(5) an
8-token, no-scale-of-any-kind design system** leaves ~12 hardcoded greys and 8 hardcoded status-pill
colors outside the token system, doubling the maintenance surface every dark-mode edit touches. The
user's "tailwind + shadcn" premise does not hold — there is no utility-class framework or component
library anywhere in the codebase — but the code is its own flavor of generic: a hand-rolled,
explicitly Primer-cloned dark palette (the in-file comment says so) stitched onto a bespoke light
palette, sharing one binary border-radius (4px/6px), zero `box-shadow`, and zero authored
`letter-spacing` anywhere in the file.

## 2. Critical gaps

None. Rationale: this is a loopback-only, single-operator, 3-page console with explicit autoescape,
a tight CSP, and every interactive control still reachable and legible even in its unstyled states
(browser UA defaults for `select`/`textarea` are ugly, not broken; the unstyled badge remediation
text is still readable, just laid out badly). Per the severity rubric, CRITICAL is reserved for gaps
that break first use — nothing here does. The findings below that come closest (H2, H3) are rated
HIGH, not CRITICAL, specifically because they degrade trust/finish rather than function.

## 3. High gaps

### H1 — `.status-badge__remediation` has no CSS rule — the trust signal breaks exactly when it matters

- **Severity:** HIGH
- **Affected routes/templates:** `server/routes/ui.py:297-337` (`_build_remediation_block`, builds
  `<small class="status-badge__remediation">`), consumed by `ui_status_badge` (`server/routes/ui.py:235-294`);
  rendered in `base.html:88-91` footer badge and polled every 10s. `server/frontend/static/app.css` —
  grepped end-to-end, **zero** `.status-badge__remediation` rule exists.
- **a11y/motion/token conflicts:** The parent `<span>` correctly carries `aria-live="polite"
  aria-atomic="true"` (shipped, m1/m4 — don't re-flag), so a screen-reader user still hears the
  remediation text. The break is purely visual: `<small>` gets zero custom styling, so it inherits
  inline flow instead of rendering as a caption block under the pill. Live-measured (visual-manifest
  §3): the fragment renders **491×22px**, a single run-on line, when a healthy badge renders at
  `min-width: 14ch` (`app.css:163`) as a compact pill.
- **What 2026 SOTA expects:** Every comparator that ships a live-status chip (Grafana alert
  annotations, Vercel deployment-status pills, GitHub Actions run badges) visually demotes the
  secondary remediation/detail text below the primary status token — smaller size, muted color,
  block-level, never inline-concatenated into the same line as the label.
- **What a credible v1 fill-in looks like:** A single new CSS rule block for `.status-badge__remediation`
  — `display: block`, a step down in `font-size` from the parent's `0.75rem`, a muted color drawn from
  the existing greys (ideally promoted to a token per H4/M-token-debt, not a fresh hardcoded value),
  and enough top margin/line-height to read as a caption, not a continuation. Pure CSS, zero JS, zero
  CSP impact — this is the cheapest fix in the whole brief.
- **Why this hasn't been fixed yet:** `_build_remediation_block` shipped in `onboarding-uplift-m3`
  (per the in-code attribution at `ui.py:280-286`) as a scoped AC5 deliverable — the acceptance
  criterion was "operator sees an actionable hint," which the raw HTML text satisfies; the CSS pass to
  make it *look* like a pill+caption instead of a run-on line was out of that milestone's scope and no
  later milestone picked it up.

### H2 — `select` and `textarea` carry zero base styling

- **Severity:** HIGH
- **Affected routes/templates:** `index.html:47-53` (`discovery_category` select, `description`
  textarea), `notebook_detail.html:129-135` (`discovery_category` select), `notebook_detail.html:139-140`
  (`description` textarea). `server/frontend/static/app.css` — `select` and `textarea` appear in
  exactly ONE place in the entire file, the shared `:focus-visible` selector list at line 207; there
  is no base `select { … }` or `textarea { … }` rule anywhere.
- **a11y/motion/token conflicts:** Live-measured (visual-manifest §3, mobile 390px): `select` renders
  **19px tall** vs. the hand-styled `input[type=text|url]` at **33px** — a visible height mismatch
  inside the same form row, and well under the WCAG 2.5.8 (AAA) / Apple HIG 44px tap-target guidance.
  `:focus-visible` still applies correctly (shipped, m1 — the ring itself is fine); the gap is the
  resting state.
- **What 2026 SOTA expects:** Every hand-rolled form in the reference set (Linear settings, GitHub
  issue forms, Vercel project settings) applies the SAME border/radius/padding treatment across every
  control type in a form — `input`, `select`, and `textarea` read as one family. A form where two of
  four control types are bare OS widgets next to two that are custom-styled is the single most common
  "someone started a design pass and didn't finish it" tell, independent of any framework.
- **What a credible v1 fill-in looks like:** Extend the existing `input[type="text"], input[type="url"],
  input[type="file"] { … }` rule (`app.css:74-84`) to also match `select, textarea` — same border,
  radius, padding, background, `font-family: inherit` (this also fixes textarea's browser-default
  monospace-vs-system-stack mismatch). `textarea` additionally needs `resize: vertical` and the
  existing `--mono` treatment applied to `input[type=text|url]` should NOT extend to it (topic/keyword
  text is prose, not a slug). Pure CSS, one rule extension, zero new tokens required.
- **Why this hasn't been fixed yet:** Both `<select>` instances were added by `notebook-paper-discovery-m1`
  and the `<textarea>` by the same milestone (per the in-template attribution comments) — a
  behavior-focused milestone (topic metadata plumbing) that never touched `app.css`. No later
  milestone's scope included "style the form controls the discovery milestone added."

### H3 — `.discover-*` fragment classes have zero CSS — the content-producing feature renders as a bare list

- **Severity:** HIGH
- **Affected routes/templates:** `server/routes/notebooks.py:705-753` (`_discover_results_fragment`) —
  emits `<ul class="discover-list"><li class="discover-candidate"><p class="discover-title">…
  <p class="discover-meta">… <p class="discover-abstract">…`. `server/frontend/static/app.css` —
  grepped end-to-end, **zero** rules for any of `.discover-list`, `.discover-candidate`,
  `.discover-title`, `.discover-meta`, `.discover-abstract`.
- **a11y/motion/token conflicts:** The wrapping `#discover-results` div correctly carries
  `aria-live="polite" aria-atomic="true"` (shipped) so the swap is announced. The visual gap is pure
  layout: with no styling, `<ul>` renders with default browser list-item bullets and margins, so a
  discovered paper's title/id/date/abstract render as one bulleted, unindented block — no visual
  distinction between the arXiv id, the submission date, and the abstract lead, and no separation
  between candidates beyond the bullet glyph.
- **What 2026 SOTA expects:** arXiv-search-result UIs (arxiv.org's own search results, Semantic
  Scholar, ar5iv) all give a result card a title/meta/abstract type hierarchy — title weighted, meta
  muted+mono for the id, abstract truncated in body text. This is the ONE surface in the console that
  presents externally-sourced content for operator judgment (per-candidate Add decisions), and it is
  the least-styled surface in the file.
- **What a credible v1 fill-in looks like:** Five small rules reusing existing tokens: `.discover-list
  { list-style: none; padding: 0 }`, `.discover-candidate { border-bottom: 1px solid var(--border);
  padding: 0.75rem 0 }` (matching the existing `.card` border language), `.discover-title { font-weight:
  600 }`, `.discover-meta { color: <the same muted grey H4 proposes tokenizing>; font-family: var(--mono);
  font-size: 0.8rem }` (this also gets `tabular-nums` for free per the existing `time, … { }` selector
  if `<time>` stays as the element), `.discover-abstract { font-size: 0.875rem; color: var(--fg) }`.
  Zero JS, zero new classes beyond what the handler already emits.
- **Why this hasn't been fixed yet:** `notebook-paper-discovery-m4` (the milestone that added
  `_discover_results_fragment`) was scoped to the arXiv-Atom driver + dedup + XSS-safe fragment
  rendering — the CSS pass was not in that milestone's acceptance criteria and, like H2, no later
  milestone's scope named it.

### H4 — No focal element on `notebook_detail.html`; content sits below six equal-weight forms

- **Severity:** HIGH
- **Affected routes/templates:** `notebook_detail.html` — 7 `<section class="card">` blocks (lines 8,
  94, 147, 181, 221, 251, 300). Live-measured (visual-manifest §3, 1440×900): all 7 cards share
  identical `border-radius: 6px`, identical `1px` border, identical `box-shadow: none`, identical
  `padding: 1rem 1.25rem`, identical `margin-bottom: 1rem`, identical 1293px width. The papers table
  — card #7, the actual notebook content — starts at **y=1823px** in a **2343px** document; only
  cards 1–3 (all input/metadata forms) are visible above the 900px fold.
- **a11y/motion/token conflicts:** None directly — this is a hierarchy finding, not an a11y violation.
  It does interact with H2/H3: the operator scrolls past two unstyled form controls (H2) and reaches
  an unstyled candidate list (H3) before ever seeing the papers they came to manage.
- **What 2026 SOTA expects:** `frontend-design-language.md` §6 names this directly: "ONE focal
  element per view — a lede module (2–3× the visual weight) answering the view's core question in 5
  seconds; supporting modules are visibly subordinate. Max 2 card sizes per view." This is also
  literally BAN-5 ("equal visual weight across all panels — no lede, no focal element") from the same
  canon's §5 ban list, and the arXMCP house thesis (`arxmcp-design-system.md` §9) itself says the
  detail page should read as "a workbench with a … posture lede: parse-status + freshness answer 'is
  this notebook usable?' first" — the live page does not deliver that ordering; it delivers metadata
  form → topic form → discover form → add-by-url form → upload form → ingest form → papers table.
- **What a credible v1 fill-in looks like:** Without introducing a grid framework, this is achievable
  as an ordering + weight change within the existing single-column layout: promote the papers table
  (or a compact papers-table + freshness summary) above the input forms, and/or give the metadata card
  (parse-status + freshness + rename/delete) a visually distinct treatment — e.g. a slightly larger
  `padding`/`font-size` step and NOT sharing the identical card recipe with the five action forms
  below it — using only the existing `.card` class plus one new modifier class, no new dependency.
- **Why this hasn't been fixed yet:** Each of the 7 cards landed in a separate milestone
  (`notebook-surface-expansion-m1/m2`, `notebook-paper-discovery-m1/m4`, `ui-attractive-polish-m4`,
  m9/m10 ingest+upload) that each correctly used the one layout primitive available (`.card`) for its
  own scoped feature. No milestone owned "the page as a whole" — the accretion is the natural result
  of feature-at-a-time delivery against a one-component design system, not a mistake in any single
  milestone.

### H5 — Correcting the "tailwind + shadcn" premise: this is a hand-rolled GitHub-Primer clone, not shadcn-generic

- **Severity:** HIGH (as a finding about *why* the console reads as generic — the user's brief asked
  for this diagnosis explicitly)
- **Affected routes/templates:** `server/frontend/static/app.css` end-to-end.
- **a11y/motion/token conflicts:** n/a — this is a provenance/authorship finding, not an a11y one.
- **Evidence the premise is wrong:** There is no Tailwind (`grep` for utility-class patterns like
  `flex`, `gap-`, `text-`, `p-` prefixes returns nothing — every class in the templates is a
  hand-named semantic class: `.card`, `.hint`, `.status-badge`); there is no shadcn/Radix — no
  component directory, no `cn()` helper, no CVA variants, nothing resembling the shadcn `Button`/`Card`
  primitive shape. `arxmcp-design-system.md` §1 confirms: "NO Tailwind, NO PostCSS, NO `@theme` block."
- **What IS actually generic, precisely named:** (a) the dark-mode token block's own in-file comment
  says it explicitly: "`re-declares the 8 base tokens with GitHub-Primer-anchored values`"
  (`app.css:234-241`) — the dark palette is a deliberate, documented Primer clone (`#0d1117`
  canvas.default, `#161b22` canvas.subtle, `#58a6ff` accent.fg, `#f85149` danger.fg are GitHub's exact
  values); (b) the light-mode palette is a DIFFERENT, bespoke source (`--accent: #1e5b8a`, a muted
  blue-grey with no named provenance) — so the two themes are stitched from two different design
  sources sharing one token schema, not one authored system with two renderings; (c) a binary
  border-radius system — every rounded element is either `4px` (buttons/inputs/badges/error-boxes/
  skip-link, 7 occurrences) or `6px` (`.card` only, 1 occurrence) — `app.css:56,81,94,142,155,194,211`;
  (d) `box-shadow` appears **zero times** in the 371-line file — no elevation language exists at all;
  (e) `letter-spacing` appears **zero times** — no typographic authorship beyond size/weight; (f) one
  effective type step in the whole product — `h1` (32px) → card `h2` (17.6px) is a real 1.82× jump,
  but `h2` → body (16px) is only 1.10×, so h2/body contrast is carried entirely by `font-weight`
  (700 vs 400), not by scale (visual-manifest §2). This is BAN-4's invariant ("untouched default stack
  look … no modification") realized through a *different* stack than the ban's literal wording (Inter
  + Lucide + shadcn) — the tell transfers even though the named library doesn't apply here.
- **What 2026 SOTA expects:** `frontend-design-language.md` §6 (the S-2 instrument-language spec) asks
  for a two-voice type system with real scale contrast (meta 11-12px / body 14-16px / section 20-24px
  / title 28-40px) and ONE elevation method (hairline OR soft shadow, never both, never neither) — the
  current system has the hairline (borders exist) but no scale contrast beyond the single h1 jump.
- **What a credible v1 fill-in looks like:** This is a token/scale-authorship problem, not a rewrite:
  add 2-3 intermediate type steps (e.g. a `--text-sm`/`--text-base`/`--text-lg` set covering the
  14/16/20px range already latent in the ad-hoc rem values), and decide ONE elevation language
  (given zero `box-shadow` today, staying hairline-only and using a slightly heavier/tinted border on
  the one card that becomes the H4 lede is the lowest-risk path — no new visual language to learn).
  Neither requires a new dependency; both are pure `:root` token additions plus selector reuse.
- **Why this hasn't been fixed yet:** The dark-mode block deliberately anchored to Primer as a
  *known-good, pre-vetted-for-contrast* source (the in-file WCAG math citations throughout
  `ui-attractive-polish-m3` show real contrast-engineering effort went into THAT choice) — it was a
  reasonable shortcut for shipping AA-clean dark mode fast, not an accident. Nobody has since gone
  back to ask whether the light-mode palette and the Primer-derived dark palette add up to one
  authored system, because no milestone's scope was "product-wide visual identity."

## 4. Medium gaps

### M1 — htmx interaction-state debt: zero `hx-indicator`, chatty `aria-live`, native `window.confirm()`

- **Severity:** MEDIUM
- **Affected routes/templates:** All 9 `hx-*` elements on `notebook_detail.html` (visual-manifest §4
  table) — `grep -rn "hx-indicator"` across `server/frontend/templates/` and `server/routes/` returns
  **zero** matches. Destructive delete: `index.html:111` and `notebook_detail.html:86`, both
  `hx-confirm="…"` → native `window.confirm()`. `aria-live` count on `notebook_detail.html` alone: 11
  code occurrences (lines 20, 46, 109, 143, 174, 176, 217, 247, 271, 290, 322) + 1 more in `base.html:89`
  (the footer badge, present on every page) = 12 live regions on one rendered page; of the 11 on the
  detail template, 6 are empty `<pre class="error">` placeholders at first paint (lines 46, 143, 174,
  217, 247, 271).
- **a11y/motion/token conflicts:** In-flight feedback relies entirely on the auto-applied
  `.htmx-request` class (`app.css:293-333`, shipped and correctly reduced-motion-gated — don't
  re-flag the spinner itself). Because there is no `hx-indicator`, ONLY the element that literally
  carries the `hx-*` attribute gets the opacity/cursor/spinner treatment — a `<form hx-post>` and its
  submit button both get it (the combined selector at `app.css:302-304` handles that specific case),
  but the two `hx-trigger="every Ns"` polling elements (`#ingest-status` at 2s, `#status-badge` at 10s)
  have NO distinct "just refreshed" affordance beyond the already-shipped `badge-flash`/nothing — the
  2s ingest poll has no flash-on-update at all today. Separately: 6 `aria-live` regions announcing
  nothing (empty at first paint) is not itself a violation, but combined with the 2s ingest poll
  re-triggering its OWN `aria-live` region on every swap (even a same-content "still running" swap),
  a screen-reader user mid-ingest gets an announcement roughly every 2 seconds for the run's duration
  — this is a real over-announcement risk the shipped `aria-live` work established presence for but
  never throttled.
- **What 2026 SOTA expects:** htmx's own documented pattern (`hx-indicator` pointing at a shared
  spinner element, or `aria-busy` toggling) is the standard fix for "which element is loading" clarity;
  for the chatty-poll problem, the standard accessible pattern is to only update `aria-live` content
  when the STATUS actually changes (e.g. compare `data-status` before replacing), not on every poll
  tick regardless of content delta.
- **What a credible v1 fill-in looks like: (destructive-confirm half)** Replacing `window.confirm()`
  with an in-page confirm (native `<dialog>` element, CSP-clean, zero new JS beyond an
  `hx-on::htmx:confirm` handler swap) would visually match the console's own language instead of
  dropping into OS chrome — but this is exactly the kind of change that **adds JS surface**, so flag
  it for the open UI security audit (`chris-dare-dev/arXMCP#9`) rather than treating it as a free
  win. **(polling half)** A cheap, audit-neutral fix: only re-render `aria-live` content when
  `data-status` changes server-side (the fragment builder already branches on `status` — a same-status
  response could omit the announcement-worthy text delta), pure server-side logic, zero new JS.
- **Why this hasn't been fixed yet:** `ui-attractive-polish-m1` shipped `aria-live` PRESENCE as its
  scoped AC (screen readers must hear SOMETHING on swap); throttling frequency/content-delta was never
  named as a follow-up. `hx-indicator` wasn't part of any milestone's stated scope — the `.htmx-request`
  CSS-only approach (`ui-attractive-polish-m3`) was judged sufficient for the two forms it was designed
  around (submit buttons) and nobody has since audited it against the two polling elements.

### M2 — Ingest-failure `<pre>` stderr tail is unstyled, inconsistent with the app's own error pattern

- **Severity:** MEDIUM
- **Affected routes/templates:** `server/routes/notebooks.py:2376-2389` (`_ingest_status_fragment`,
  `status == "failed"` branch) — emits a bare `<pre>{stderr_tail}</pre>` (note: NOT `<pre class="error">`).
  Every OTHER error surface in the console — `create-error`, `rename-error`, `topic-error`,
  `discover-error`, `paste-error`, `upload-error`, `ingest-error` — uses `<pre class="error">`
  (`app.css:137-148`: tinted `--error-bg` background, `--danger` text color, rounded corners). The
  ingest subprocess's stderr tail, arguably the single most operationally important error an operator
  will read in this console (a failed corpus ingest), gets none of that treatment.
- **a11y/motion/token conflicts:** No contrast failure — the bare `<pre>` inherits `currentColor`, so
  it stays legible in both themes — but the visual *alarm* signal (the tinted background + danger
  color every other error gets) is absent specifically on the highest-stakes error.
- **What 2026 SOTA expects:** Consistent error-affordance language across a product — CI tools (GitHub
  Actions log viewers, Vercel build logs) visually distinguish a failed-run stderr block from
  successful output with the same treatment used everywhere else the tool signals failure.
- **What a credible v1 fill-in looks like:** Change `f"<pre>{stderr_pre}</pre>"` to
  `f'<pre class="error">{stderr_pre}</pre>'` (or reuse the class directly on the wrapping element) —
  a one-line change reusing the EXISTING `pre.error` rule; zero new CSS.
- **Why this hasn't been fixed yet:** The ingest-status fragment predates the `pre.error` pattern
  becoming the house convention for htmx error surfaces (the `-error` `<pre>` ids were added
  form-by-form across several milestones); the ingest failure path was written to just show the raw
  stderr text and nobody has since reconciled it with the pattern that emerged around it.

### M3 — Tap targets under the 44px guidance across the whole console

- **Severity:** MEDIUM
- **Affected routes/templates:** Every `button` on both pages. Live-measured (visual-manifest §3,
  mobile 390px): every `button` computed **32px tall** — Rename 77×32, Delete notebook 131×32, Save
  topic 91×32, Discover 80×32, Add 53×32, Upload 72×32, Ingest now 95×32, and all 6 `Remove` buttons
  at 77×32. `select` at 19px (also H2). `input[type=text|url]` at 33px.
- **a11y/motion/token conflicts:** WCAG 2.5.8 (Target Size, AAA — not a binding AA failure, but the
  Apple HIG 44pt guidance both cite the same number) is missed by every interactive control in the
  console. This compounds specifically on mobile, where `body { padding: 1rem }` stays identical to
  desktop (M4) and the same 32px buttons sit in the same dense single-column layout.
- **What 2026 SOTA expects:** A console built loopback-only for one operator on presumably a desktop
  workstation has a legitimate argument that 44px targets matter less than on a touch surface — but
  the console DOES serve a mobile viewport correctly today (`.table-wrap` overflow handling, a
  viewport meta tag) without a matching tap-target pass, which is an inconsistent commitment: the
  layout was made mobile-*capable* without being made mobile-*comfortable*.
- **What a credible v1 fill-in looks like:** Bump the `button, .button` rule's `padding` (`app.css:87-98`,
  currently `0.4rem 0.85rem`) to something nearer `0.6rem 1rem`, which lands close to 40-44px depending
  on font metrics — pure CSS, no new token, though it does interact with H4's card-density decisions
  (a taller button in a dense form changes the vertical rhythm of every card).
- **Why this hasn't been fixed yet:** The console's primary/only tested viewport during development
  has been desktop; the mobile pass (`ui-attractive-polish-m2`'s `.table-wrap` overflow fix) targeted
  the specific breakage (horizontal scroll clipping the Preview/Remove column) rather than a general
  touch-target audit.

### M4 — No responsive type or spacing ramp between desktop and mobile

- **Severity:** MEDIUM
- **Affected routes/templates:** `server/frontend/static/app.css:23-40` (the `body` rule). Live-measured
  (visual-manifest §3): `h1` stays fixed at **32px** at a 390px viewport; `body { padding: 1rem }` is
  identical desktop and mobile.
- **a11y/motion/token conflicts:** None directly — 32px `h1` at 390px width is still legible, just
  proportionally larger relative to the viewport than it reads on desktop.
- **What 2026 SOTA expects:** A `clamp()`-based fluid type scale (the same technique already used for
  `max-width: clamp(640px, 92vw, 1400px)` at `app.css:37`, so the codebase already has the pattern in
  hand) is the standard 2026 approach — no media query needed, no new dependency.
- **What a credible v1 fill-in looks like:** `h1 { font-size: clamp(1.5rem, 4vw + 1rem, 2rem) }` in the
  same idiom as the existing body-width clamp; same for `body`'s padding if a tighter mobile margin is
  wanted. Zero new tokens, zero JS.
- **Why this hasn't been fixed yet:** `ui-attractive-polish-m5`'s UPL-19 v1 clamp was scoped
  specifically to the table-width ceiling (per its in-file attribution comment); nobody has since
  extended the same clamp technique to typography.

### M5 — Raw ISO timestamps, not humanized (flagged with an explicit calibration caveat)

- **Severity:** MEDIUM
- **Affected routes/templates:** `index.html:92` (`<time>{{ nb.created_at }}</time>`),
  `notebook_detail.html:50,70` (`created_at`, `latest_run.finished_at`/`started_at`),
  `notebook_detail.html:326` (`<time>{{ p.added_at }}</time>`).
- **a11y/motion/token conflicts:** `tabular-nums` (shipped) keeps the digits aligned, which mitigates
  scan-friction, but the values render as raw machine timestamps (presumably ISO 8601) rather than
  a humanized or relative form.
- **Calibration caveat — do not over-weight this finding:** the arXMCP house thesis
  (`arxmcp-design-system.md` §9) explicitly frames freshness as "metered, sourced facts" the operator
  should trust "without a second glance" — an exact timestamp arguably serves that better than a fuzzy
  relative string ("3 days ago" hides exactly the precision the thesis wants). This is included as a
  MEDIUM candidate for Phase 2 to weigh, not a confirmed defect.
- **What 2026 SOTA expects:** Most 2026 dev-tool consoles pair a relative label with an exact
  timestamp in a `title` attribute (best of both) — GitHub's `<relative-time>` custom element is the
  canonical pattern, though that specific element is a vendored web component and would need
  evaluating against the no-build-chain / audit-widening constraints before proposing it directly.
- **What a credible v1 fill-in looks like:** Out of scope to sketch further here given the calibration
  caveat above — Phase 2 should decide whether "metered fact" (keep raw) or "scannable fact" (humanize)
  better serves the thesis before proposing an implementation.
- **Why this hasn't been fixed yet:** Every `<time>` element was added by the milestone that shipped
  its surrounding feature (m1 for freshness, m8 for paper rows) with the raw ISO value as the
  simplest correct implementation; no milestone's scope included timestamp formatting as a UX
  question.

### M6 — `notebook_kind` (arxiv vs. textbook) is not surfaced on the landing page

- **Severity:** MEDIUM
- **Affected routes/templates:** `index.html` — grepped for `notebook_kind`/`.kind`, **zero**
  occurrences. `notebook_detail.html:63` — exactly ONE reference (`{% if notebook.notebook_kind ==
  'arxiv' %}`), used only to conditionally show the parse-status hint text, not as a visible label.
  (Correction to `arxmcp-design-system.md` §7, which claims 3 references on the detail page and 0 on
  the index — the live file has exactly 1 on the detail page and 0 on the index; the overlay's count
  is stale but its underlying claim — that the index never surfaces `kind` — still holds.)
- **a11y/motion/token conflicts:** None.
- **What 2026 SOTA expects:** A console managing two structurally different notebook types (arxiv
  vs. textbook, each with different available actions — e.g. `parse_status` is meaningful only for
  textbook notebooks) should let the operator distinguish them from the list view, not require
  opening each notebook to discover which kind it is.
- **What a credible v1 fill-in looks like:** A small text label or the existing `.status-badge`
  visual language reused as a kind indicator in the notebooks table's Slug or Display-name column —
  the design-system overlay itself suggests this reuse (§7: "A `.status-badge`-style chip would reuse
  the existing three-state visual language rather than inventing one"). Caution: adding a 3rd/4th
  badge flavor to the index table risks BAN-7 badge-soup if not scoped tightly (one chip per row,
  not decorative repetition).
- **Why this hasn't been fixed yet:** `notebook_kind` is a `notebooks.py`/store-level field consumed
  by the detail page's conditional hint logic; the index/landing table was written before
  multi-kind notebooks existed as a concept and nobody has revisited its column set since.

## 5. Low gaps

### L1 — ar5iv preview route has no shared console chrome (softer than the design-system overlay implies)

- **Severity:** LOW
- **Affected routes/templates:** `server/routes/ui.py:482-628` (`ui_paper_preview`) — direct-serves
  raw `content_bytes` from disk with no Jinja2 template wrapping, so it inherits no header, no
  skip-link, and no operability badge.
- **a11y/motion/token conflicts:** None new — the tight `CONTENT_SECURITY_POLICY_PREVIEW`
  (`server/middleware.py:218-226`) is a deliberate, documented constraint (blocks scripts, `<base>`
  hijack, form-action exfiltration), not a bug, and should stay as-is.
- **Correction to `arxmcp-design-system.md` §7:** that overlay frames "the absence of a way back" as
  "a real UX gap." Checked against the live markup: the Preview link
  (`notebook_detail.html:335-337`) opens with `target="_blank" rel="noopener"` — a NEW tab, not an
  in-place navigation — so the operator's original notebook-detail tab is untouched and "closing the
  tab" is the natural, always-available way back. The gap that remains is narrower: visual/brand
  discontinuity (the preview tab has no favicon-adjacent identity, no indication it's part of the
  arXMCP console) rather than a navigational dead-end.
- **What 2026 SOTA expects:** Minimal — most tools that open external/untrusted content in a new tab
  (GitHub's raw-file view, for instance) accept the discontinuity as correct given the trust boundary;
  arXMCP's CSP rationale is the same shape.
- **What a credible v1 fill-in looks like:** If Phase 2 wants to close even the narrow gap, a
  same-origin `<link rel="icon">` already applies automatically (the favicon is domain-scoped, not
  page-scoped) — verify it renders in the tab before treating this as unaddressed at all. Likely a
  non-finding once verified live in a browser.
- **Why this hasn't been fixed yet:** The m10 preview route was scoped as "document-view: chrome
  recedes, the ar5iv HTML is the surface" per the design-system overlay's own surface map — the
  chrome-free choice may be intentional, not an oversight.

### L2 — Unused CSS hook classes (harmless, but a discipline tell)

- **Severity:** LOW
- **Affected routes/templates:** `notebook_detail.html:31` (`class="rename-form"`), `:82`
  (`class="notebook-actions"`), `:109` (`class="topic-block"`), `:119` (`class="topic-form"`).
  `server/frontend/static/app.css` — none of these four classes has a dedicated rule.
- **a11y/motion/token conflicts:** None — these wrap elements that already receive correct styling via
  bare-element selectors (`form`, `label`, `input`, `button`), so nothing renders broken.
- **What 2026 SOTA expects:** n/a — this is a code-hygiene observation, not a user-facing gap.
- **What a credible v1 fill-in looks like:** Not a fix-worthy item on its own; only relevant if Phase 2
  wants a semantic hook for scoped styling (e.g. giving the rename form a different layout from the
  topic form) — in which case these classes are already in place and free to use.
- **Why this hasn't been fixed yet:** These are forward-looking hooks left in place by the milestones
  that added them (m2, m2, discovery-m1, discovery-m1) in case per-form styling was ever needed; it
  hasn't been yet, so the hooks sit unused. Not a regression, just latent capacity.

## 6. a11y + motion-safe + token conflicts found in code

- **`server/routes/ui.py:336` builds `<small class="status-badge__remediation">` — `server/frontend/static/app.css` has NO matching rule anywhere in the 371-line file.** (H1)
- **`server/frontend/static/app.css:207` is the ONLY line mentioning `select` or `textarea`** (inside the shared `:focus-visible` selector list) — no base styling rule for either element exists, affecting `index.html:47-53,57-58` and `notebook_detail.html:129-135,139-140`. (H2)
- **`server/routes/notebooks.py:730-744` emits `.discover-candidate/.discover-title/.discover-meta/.discover-abstract/.discover-list`** — none has a CSS rule. (H3)
- **`server/routes/notebooks.py:2310-2389` (`_ingest_status_fragment`) sets `data-status="none|running|success|failed"` on `#ingest-status`** — `app.css` has zero `[data-status]` selectors, so the attribute is inert for styling; the `failed` branch's `<pre>{stderr_tail}</pre>` (line 2380) is not `pre.error`, so it gets none of the `--error-bg`/`--danger` error treatment every other error surface gets. (M2)
- **Zero `hx-indicator` attributes** across `server/frontend/templates/` and `server/routes/` (grep-confirmed) — all in-flight feedback depends on the `.htmx-request` auto-class (`app.css:293-333`, itself correctly reduced-motion-gated), which does not cover the two polling elements' "just refreshed" state distinctly from their "in-flight" state. (M1)
- **11 `aria-live="polite"` regions in `notebook_detail.html`** (lines 20, 46, 109, 143, 174, 176, 217, 247, 271, 290, 322) **+ 1 in `base.html:89`** = 12 on one rendered page; 6 are empty `<pre class="error">` at first paint (lines 46, 143, 174, 217, 247, 271). The 2s ingest poll (`server/routes/notebooks.py`, `hx-trigger="every 2s"` in the `running` branch of `_ingest_status_fragment`) re-announces its `aria-live` region on every tick regardless of whether the status text actually changed. (M1)
- **`index.html:111` and `notebook_detail.html:86`** — destructive delete uses `hx-confirm` → native `window.confirm()`, not a styled in-page dialog; any replacement would add JS surface and should be flagged for the open UI audit (`chris-dare-dev/arXMCP#9`). (M1)
- **Token bypass** — hardcoded greys at `app.css:45,47,48,62,63,64,65,111,116` (light mode) and `app.css:271,272,273` (dark mode: `#b3b9c0`, `#9ba1a8`, `#c9d1d9`) plus 8 hardcoded status-pill colors at `app.css:165-168` (light) and `:286-289` (dark) — none reference the 8-variable `:root` token set, so every dark-mode edit requires syncing two literal-color call sites instead of one token edit (the in-file comment at `app.css:268-269` — "remap hardcoded tertiary-text greys" — already documents this exact debt as a known-accepted cost). (H1/H5, cross-referenced)
- **Motion audit result: clean.** Every keyframe/transition in the file (`spin`, `badge-flash`, `row-fade-out`, the View Transitions duration override) sits inside `@media (prefers-reduced-motion: no-preference)`, and the universal `reduce` clamp (`app.css:223-232`) is present and correctly unconditional. No violation found — noted explicitly since the brief was asked to check this specifically.
- **CSP posture for Phase 2 (not a violation, a constraint record):** `CONTENT_SECURITY_POLICY_UI` (`server/middleware.py:170-177`) already allows `script-src 'self' 'unsafe-inline'` and `style-src 'self' 'unsafe-inline'` — inline `<style>` blocks, `style="…"` attributes, and additional `hx-on::*` inline handlers are all ALREADY permitted without a CSP change. A new same-origin vendored single-file JS drop (the htmx precedent) is also covered by `script-src 'self'` without a CSP edit. What is NOT permitted without a CSP change: any external/CDN script or style origin, `unsafe-eval` (explicitly rejected per `arxmcp-design-system.md` §8), or any origin outside `'self'`. Independent of CSP legality, **any new JS — even same-origin and CSP-clean — widens the surface the OPEN UI security audit (`chris-dare-dev/arXMCP#9`) will eventually need to cover**; Phase 2 candidates that add JS should say so explicitly rather than let it pass silently.

## 7. What arXMCP does well visually

- **The a11y foundation is genuinely solid and complete for what it covers** — `prefers-reduced-motion` universal gate, `:focus-visible` rings (including the widened destructive-button variant), the skip-link + focusable `<main>`, full dark-mode token remap with `color-scheme: light dark` so UA-styled controls follow, and `aria-live`/`aria-atomic` presence on every htmx swap target. This is more a11y investment than most 3-page internal tools ever receive, and every piece I checked was implemented correctly, not just present.
- **Jinja2 autoescape is explicit and load-bearing, not incidental** — the environment is constructed with `select_autoescape(...)` by name rather than relying on a framework default, and a repo-wide check shows zero `| safe` filters anywhere; every hand-built HTML fragment (`_paper_row_html`, `ui_status_badge`, `_display_name_fragment`, `_discover_results_fragment`) applies `html.escape()` per interpolated value. This is a deliberate, documented security posture, not an accident of the templating choice.
- **htmx is vendored with clear provenance and used correctly for its actual job** — a single-file 0BSD-licensed drop with a documented `VENDORED.md`, used for real partial-page swaps (in-page rename/delete, live status polling) rather than as decoration; the `json-enc` extension fix and the `globalViewTransitions` opt-in are both correctly scoped, defer-loaded, and gated on `prefers-reduced-motion`.
- **The status-badge shared CSS surface (m4) is a genuinely reusable pattern** — one `.status-badge`/`.status-badge--{ok,warn,ops-warn,down}` vocabulary serves both the per-notebook parse-status badge and the footer operability badge, with a stable `min-width: 14ch` so the footer doesn't reflow across state changes. This is exactly the kind of small, consistent primitive a larger design system would formalize — it already exists here informally.
- **The in-page rename/delete htmx-swap pattern (m2) replaced a `location.reload()` flow with real partial updates**, and the swap targets correctly stay outside the swapped element so the surrounding form/controls survive — a genuinely more modern interaction pattern than a full-page reload, implemented without any framework.
- **The tight per-response CSP on the ar5iv preview route is a real, carefully-reasoned security decision, not a leftover default** — `default-src 'none'` with every fetch/document/navigation directive named explicitly, a documented MathJax-vs-safety tradeoff, and a `<meta http-equiv="refresh">` strip — this is more security engineering than most internal-tool preview panes receive.
- **The `color-mix(in oklab, …)` hover treatment (m2)** is a small but genuinely 2026-current CSS technique — perceptually uniform color mixing over the older `filter: brightness()` approach — applied correctly and with a documented rationale in the source comment.

## 8. Themes

Nearly every HIGH/MEDIUM finding in this brief traces to the same root cause: **feature milestones
shipped complete, tested, secure behavior and left CSS as an afterthought scoped to "does it render,"
not "does it look finished."** `.status-badge__remediation`, `.discover-*`, `select`/`textarea`, and
the ingest-failure `<pre>` are all cases where a milestone correctly built the HTML/behavior and
correctly secured it (autoescape, `html.escape`, validated inputs) but never circled back to `app.css`
— because no milestone's acceptance criteria named "style this." The design-token debt (H5) is the
architectural version of the same pattern: the dark-mode milestone solved dark-mode contrast
correctly and completely, but by anchoring to a pre-vetted external palette (GitHub Primer) rather
than extending the light-mode system's own tokens outward, leaving two palettes stitched together
under one 8-variable schema instead of one authored system. The information-architecture gap (H4) is
the page-level version of the same accretion: seven independently-correct milestones each added one
`.card`, and nothing has ever owned "the page as a whole." None of this reads as carelessness — the
security and correctness discipline visible in every commit (§7) is real — it reads as a codebase
where **finish-level visual polish has never been a milestone's job description**, which is exactly
the gap this uplift exists to close.
