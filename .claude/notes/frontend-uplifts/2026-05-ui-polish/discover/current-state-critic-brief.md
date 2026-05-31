# Current-state critic brief — `2026-05-ui-polish`

**Critic:** frontend-uplift-current-state-critic
**Date:** 2026-05-30
**Surface critiqued:** `frontend/templates/{base,index,notebook_detail}.html`
(3 files), `frontend/static/app.css` (126 lines, 8 CSS variables),
`server/routes/ui.py::ui_status_badge`, vendored `frontend/static/htmx.min.js`.
**Constraint floor:** CLAUDE.md §4.7 — pure CSS, vanilla JS, or vendored
single-file drops only. No npm, no Node, no SPA, no React/Tailwind/Framer.
Anything else is an automatic Phase-3 BLOCKER.

---

## 1. Executive summary

The console has **shipped correctness** and a coherent visual vocabulary
(`.card`, `.status-badge--{ok,warn,ops-warn,down}`, the m1 freshness signal,
the m4 footer badge) but is **floor-bare on the 2026 accessibility baselines
every comparable research-tool console clears**: `app.css` carries **zero**
`@media (prefers-reduced-motion: reduce)`, **zero** `:focus-visible` rules,
**zero** dark-mode tokens, and **zero** `aria-live` regions on the *success*
htmx swap targets (only the 5 inline error `<pre>`s are announced). The
detail page has multiple **`location.reload()`** post-mutation handlers
(index.html:14, notebook_detail.html:94) which discard htmx's whole "swap
without reload" affordance, producing a noticeable flash an operator notices
on every Create / Add-paper action. The "no-preview" affordance at
notebook_detail.html:200-202 is a bare `<span class="hint">` styled
identically to text, with NO disabled-button visual semantics — the operator
cannot tell at a glance which papers have previews.

Highest-severity gaps, in order: (1) **missing `prefers-reduced-motion`
gate** — categorical a11y regression and a prerequisite for any future motion
candidate; (2) **missing `:focus-visible` rules** — browser-default focus
rings are inconsistent across Safari/Chrome/Firefox and disappear entirely
on the `<a class="button">` "Open" link on Safari; (3) **no
`prefers-color-scheme: dark` handling** — the page is light-mode-fixed and
flashes white at every operator on a dark-mode OS; (4) **`aria-live`
asymmetry** — errors are announced, successes are not; the m4 status-badge
flips silently from READY→DEGRADED every 10s with no SR signal; (5) **no
`tabular-nums` on the freshness `<time>` + count fields** — values
jitter horizontally on every htmx poll.

---

## 2. Critical gaps

None. On a 3-page loopback-only single-operator surface there is no visual
gap that breaks the operator on first use. Calibrating honestly — every gap
below is HIGH or lower.

---

## 3. High gaps

### H1 — Missing `prefers-reduced-motion` gate
- **Severity:** HIGH
- **Affected:** `frontend/static/app.css` (whole file; zero `@media
  (prefers-reduced-motion:*)` blocks). Today's CSS has no transitions or
  animations at all, so the floor is "safe by absence" — but the moment ANY
  motion candidate lands (htmx-swap fade, status-badge pulse, focus-glow,
  ingest-row shimmer) without the gate, the console becomes an a11y
  regression. The motion-vocabulary doc treats this as the prerequisite for
  every other motion primitive (MOT-NO-5 explicitly: "arXMCP's CSS today has
  ZERO `prefers-reduced-motion` blocks — adopting the gate is itself a
  baseline prerequisite candidate").
- **What 2026 SOTA expects:** every comparable research-tool console (arxiv,
  ar5iv, Linear, Sentry, Vercel) ships a top-of-stylesheet
  `@media (prefers-reduced-motion: reduce) { *, *::before, *::after {
  animation-duration: 0.01ms !important; transition-duration: 0.01ms
  !important; … } }` universal-cap block.
- **Sketch:** add a single `@media (prefers-reduced-motion: reduce)` block at
  the bottom of `app.css` clamping animation / transition durations and
  cancelling `scroll-behavior: smooth`. Pure CSS, ~6 lines, zero JS.
- **Why not fixed:** the CSS has been static enough that the gate looked
  "premature"; the moment Phase 2 introduces ANY transition it becomes
  blocking. Frame it as prerequisite, not standalone polish.

### H2 — Missing `:focus-visible` styling on interactive elements
- **Severity:** HIGH
- **Affected:** `frontend/static/app.css:55-87` (label/input/button rules
  define no `:focus` or `:focus-visible`); `frontend/templates/index.html:48`
  (`<a href="/ui/notebooks/{{ nb.slug }}" class="button">Open</a>` — the
  styled-as-button anchor has only the browser-default outline, which Safari
  ≥16 *drops entirely* on `<a>` elements that have `text-decoration: none`
  unless `:focus-visible` is set explicitly); the destructive `<button
  class="danger">` rows (index.html:49-55, notebook_detail.html:76-82,
  notebook_detail.html:205-211); the rename `<button type="submit">` at
  notebook_detail.html:38; the htmx-shim'd inputs throughout.
- **What 2026 SOTA expects:** every WCAG 2.1 AA-conformant operator console
  ships explicit `:focus-visible { outline: 2px solid var(--accent);
  outline-offset: 2px; }` rules. The 8-token design system is ready for it
  (`--accent` already exists). The motion-vocabulary doc names this as
  `[MOT-34 focus-visible-glow]` and explicitly flags it as "the baseline
  gap to close before any decorative motion lands."
- **Sketch:** four selectors in `app.css` — `button:focus-visible,
  .button:focus-visible, input:focus-visible, a:focus-visible` — sharing
  the same `outline: 2px solid var(--accent); outline-offset: 2px;
  border-radius: 4px;` declaration block. Pair with a quiet
  `:focus:not(:focus-visible) { outline: none; }` reset so mouse clicks
  don't show the ring. Pure CSS, ~8 lines.
- **Why not fixed:** invisible-by-default fallback; the operator-as-author
  works mouse-first and never noticed. Surfaces immediately under a keyboard
  audit.

### H3 — No `prefers-color-scheme: dark` handling
- **Severity:** HIGH
- **Affected:** `frontend/static/app.css:4-13` (`:root` block has the 8
  light-mode tokens with no dark-mode counterpart); every operator running a
  dark-mode macOS / GNOME / Windows desktop opening `/ui/` gets a full-screen
  white flash (`--bg: #f8f8f8` against a dark browser chrome).
- **What 2026 SOTA expects:** arxiv.org itself shipped a `prefers-color-scheme:
  dark` block in their main stylesheet in 2024; ar5iv has had one since
  launch; Linear, Vercel, Sentry, Grafana, Phoenix (the OTel tracing UI the
  arXMCP stack already integrates) all honor `prefers-color-scheme` natively.
  arXMCP's design-system inventory §7 explicitly names "No dark-mode" as a
  candidate.
- **Sketch:** a second `@media (prefers-color-scheme: dark) { :root { --fg:
  #e5e5e5; --bg: #0f1419; --card-bg: #181d23; --border: #2a3038; --accent:
  #4a9eda; --danger: #e07a6c; --error-bg: #2a1816; } }` block. Verify the
  `.status-badge--ok / --warn / --ops-warn / --down` colors stay AA-contrast
  against the dark card background (the current `#e6f4ea` `--ok` background
  fails on dark). Pure CSS, ~12 lines, single file edit.
- **Why not fixed:** loopback-only single-operator deployment makes "the
  operator can just switch their OS to light mode" tempting; but the 2026
  baseline is to honor the OS preference, not require the operator to fight
  their setup.

### H4 — `aria-live` asymmetry: errors are announced, successes are not
- **Severity:** HIGH
- **Affected:** `frontend/templates/notebook_detail.html:15`
  (`#display-name-block` is the htmx outerHTML target for the rename success
  swap — NO `aria-live`); `notebook_detail.html:161-168` (`#ingest-status`
  div polls every 2s and swaps in fragments that change from "Loading…" to
  "Queued"/"Running"/"Complete"/"Failed" — NO `aria-live`);
  `notebook_detail.html:180` (`#papers-tbody` is the upload-success swap
  target — NO `aria-live`); `base.html:65-67` (`#status-badge` flips
  silently from READY → DEGRADED → WARN → DOWN every 10s with NO
  `aria-live`); `index.html:41` (`#notebook-list` table body); compare to
  the 5 `pre.error` elements at index.html:28, notebook_detail.html:39, 103,
  132, 154 which all correctly carry `aria-live="polite"`.
- **What 2026 SOTA expects:** htmx 2.x docs explicitly call out `aria-live`
  on swap targets as the canonical SR bridge (htmx.org/examples/aria-live).
  The pattern is to put `aria-live="polite"` on the target div and let htmx
  fragments swap in beneath it. The m4 status-badge in particular changes
  *operational* state silently — an SR-using operator gets zero signal when
  the corpus drifts.
- **Sketch:** add `aria-live="polite"` to `#display-name-block`,
  `#ingest-status`, `#papers-tbody`, `#status-badge`, and `#notebook-list`.
  For the status-badge, ALSO add `aria-atomic="true"` so the whole
  "DEGRADED | corpus v…" string is announced as one unit. Five attribute
  additions across two templates. Zero JS, zero CSS.
- **Why not fixed:** the error-path was the obvious case during the m2 / m8
  builds; the success-path is harder to notice because it works visually.
  An a11y audit would catch this immediately.

### H5 — `location.reload()` on every Create / Add-paper success discards the htmx-swap affordance
- **Severity:** HIGH
- **Affected:** `frontend/templates/index.html:14`
  (`hx-on::htmx:after-request="if(event.detail.successful) location.reload()"`
  after `POST /ui/api/notebooks`); `notebook_detail.html:94` (after `POST
  …/papers` — add by URL); `index.html:52` (after `DELETE
  /ui/api/notebooks/{slug}` — Remove). The m2 in-page rename/delete pattern
  at notebook_detail.html:27-30 + 79 is the *correct* htmx-native pattern
  (swap an outerHTML target) — yet the create/add/remove flows next to it
  on the same page hard-reload. The visual effect is a full-page white flash
  on every successful create-notebook click, which an operator notices
  every single time.
- **What 2026 SOTA expects:** htmx-native operator consoles (the canonical
  Hyperscript demo apps, Bigblueswan, every "htmx + Jinja2" reference repo
  on GitHub from 2024 onward) swap fragments in place. `POST` returns the
  new `<tr>` and htmx `hx-swap="beforeend" hx-target="tbody"` appends it.
  The m8 upload card at notebook_detail.html:116-120 already does this
  correctly (`hx-target="#papers-tbody" hx-swap="beforeend"`); the
  create-notebook and add-by-URL forms next to it do not.
- **Sketch:** modify the index.html create-notebook form to `hx-target="#
  notebook-list" hx-swap="beforeend"` and have `POST /ui/api/notebooks`
  return a single `<tr>` fragment; similarly for `POST .../papers`. The
  REST handlers already return JSON; an htmx-fragment variant (or the
  existing fragment with content negotiation on `HX-Request` header) is the
  v1 fill-in. Pure server-side change + Jinja2 fragment template; zero new
  vendored asset. Note: this *does* widen the UI security audit surface
  (new fragment-rendering paths), so flag for `chris-dare-dev/arXMCP#9`.
- **Why not fixed:** `location.reload()` shipped as the simplest path
  during m7/m8 when the JSON REST contract was the source of truth; the
  m2 rename/delete pattern arrived later and the create/add flows were not
  back-ported. Audit-widening is the soft barrier.

---

## 4. Medium gaps

### M1 — No `tabular-nums` on timestamps and counts
- **Severity:** MEDIUM
- **Affected:** every `<time>` element rendered without `font-variant-numeric`
  — `index.html:46` (`<time>{{ nb.created_at }}</time>` in the table),
  `notebook_detail.html:43` (`Created` row in `<dl class="meta">`),
  `notebook_detail.html:63` (the m1 freshness `<time>{{ latest_run.finished_at
  or latest_run.started_at }}</time>` which is the only value the operator
  *re-reads* at every page load), `notebook_detail.html:184` (per-paper
  `<time>{{ p.added_at }}</time>`); also the count headers (`Existing notebooks
  ({{ notebooks|length }})` at index.html:33, `Papers in this notebook ({{
  papers|length }})` at notebook_detail.html:172) which change value on htmx
  swaps and cause the surrounding text to shift horizontally; and the
  `corpus v… | … notebooks` substring inside the m4 status-badge label which
  re-renders every 10s.
- **What 2026 SOTA expects:** numeric data in dev-tool consoles is monospace
  *or* `font-variant-numeric: tabular-nums` so digits don't shift width when
  values change. arxiv.org, ar5iv, GitHub stats panels, Linear's count badges
  all use tabular figures.
- **Sketch:** add `time, .status-badge, dl.meta dd code { font-variant-numeric:
  tabular-nums; }` to `app.css`. One CSS rule. Pure CSS, zero JS.
- **Why not fixed:** invisible until you watch the page during an active
  ingest poll and notice the digits dance. Once seen, can't be unseen.

### M2 — No `htmx-request` loading affordance on in-flight buttons
- **Severity:** MEDIUM
- **Affected:** every htmx-driven `<button type="submit">` in the templates:
  the Create button (index.html:27), Rename (notebook_detail.html:38), Add
  (notebook_detail.html:102), Upload (notebook_detail.html:131), Ingest now
  (notebook_detail.html:153). htmx 2.x adds `.htmx-request` to the
  requesting element while the request is in flight (htmx.org/docs/#requests);
  `app.css` styles none of this. The operator who hits "Ingest now" with a
  cold subprocess pool sees the button look perfectly normal for ~800ms,
  has no signal that the click registered, and double-clicks.
- **What 2026 SOTA expects:** htmx's idiomatic pattern is
  `.htmx-request { opacity: 0.6; pointer-events: none; }` plus a
  `.htmx-request::after { content: ""; … }` spinner; alternatively the
  `loading-states` htmx extension (vendored single file) gives per-element
  control. The m4 status-badge's polling already shows the operator the
  concept of live updates; the submission buttons should match.
- **Sketch:** add a single CSS rule: `.htmx-request { opacity: 0.6;
  pointer-events: none; cursor: wait; }`; optionally a small CSS-only
  spinner via `::after { animation: spin 0.6s linear infinite; }` (gated
  by `@media (prefers-reduced-motion: no-preference)` per H1). Pure CSS,
  ~10 lines, zero JS, zero new vendored asset.
- **Why not fixed:** loopback latency is sub-millisecond for everything
  except `POST .../ingest` (which spawns a subprocess) and the upload card
  (which streams MBs). The lone slow operations are exactly where the
  affordance is most missed.

### M3 — Detail-page papers table lacks visual differentiation for "no preview" vs "Preview" affordances
- **Severity:** MEDIUM
- **Affected:** `frontend/templates/notebook_detail.html:185-202`. When a
  paper has a stored ar5iv HTML the cell renders `<a href="…">Preview</a>`
  (styled by UA default — blue underline); when it does not, the cell
  renders `<span class="hint" title="…">Preview</span>` which the `.hint`
  rule paints as `color: #555; font-size: 0.875rem;` — a perfectly
  normal-looking text color, not "disabled". On a long papers table the
  operator cannot scan a column of "Preview / Preview / Preview / Preview"
  and tell which are actionable. The tooltip helps but is a hover-only
  affordance — invisible to keyboard and SR users.
- **What 2026 SOTA expects:** disabled-action affordances are visually
  distinct (strikethrough, dimmer color, lock icon) AND announce as
  disabled to SRs (`aria-disabled="true"` + matching CSS, or `role="button"
  aria-disabled="true"`). Dev-tool tables (GitHub Actions logs, GitLab
  pipeline rows, Sentry event lists) consistently use a `.muted`-style
  visual.
- **Sketch:** introduce a `.preview--disabled` class with `color: #999;
  text-decoration: line-through dotted;` (or a CSS `mask` icon prepended);
  add `aria-disabled="true"` to the `<span>`. One template edit + ~3 lines
  CSS. The existing `<span title="…">` accessibility scaffolding stays.
- **Why not fixed:** m10's F6 rectifier added the actionable tooltip text
  but stopped short of the visual disabled state; tooltip alone was deemed
  enough at the time.

### M4 — Footer status-badge polls every 10s with no visible "last checked" or "next poll" affordance
- **Severity:** MEDIUM
- **Affected:** `frontend/templates/base.html:65-67` (the badge `<span>`)
  + `server/routes/ui.py:222-265` (the fragment handler). The polling is
  silent: every 10s the fragment swaps in, possibly flipping label color
  and CSS class without any indication that the value was just refreshed.
  An operator watching the page during an ingest can't tell whether the
  badge said "DEGRADED" 30s ago and now reflects a recovered state, or
  whether the page is stale.
- **What 2026 SOTA expects:** comparable live-updating dev consoles
  (Grafana, Datadog, Phoenix) show a subtle "updated 4s ago" or a tiny
  pulse-on-update affordance. The motion-vocabulary doc names `[MOT-14
  data-tick-flash]` for exactly this case.
- **Sketch:** brief CSS animation triggered by the htmx swap — `.htmx-
  settling { animation: flash 400ms ease-out; }` + `@keyframes flash {
  from { background: var(--accent-faint, #cce0ee); } to { background:
  transparent; } }`, gated by `prefers-reduced-motion: no-preference`.
  Optionally append a `<span class="hint">updated <time
  datetime="…">just now</time></span>` next to the badge (server-side
  timestamp from the fragment, no JS-side clock drift). Pure CSS + one
  template edit; zero new JS.
- **Why not fixed:** the m4 design favored "quiet" — the badge should not
  distract from operator work. A tasteful flash + tabular-num "updated Ns
  ago" is the next step.

### M5 — Hard-coded `max-width: 980px` produces awkward whitespace on wide displays
- **Severity:** MEDIUM
- **Affected:** `frontend/static/app.css:25` (`body { max-width: 980px;
  margin-left: auto; margin-right: auto; }`). On a 27"+ monitor the cards
  consume ~36% of horizontal space; the papers table at the bottom of the
  detail page is then cramped against an unused 1900px of margin while the
  operator has the page open beside a Lean editor or terminal. No
  `clamp(...)` or container-query responsiveness; no min/max widths on the
  table.
- **What 2026 SOTA expects:** modern operator consoles use
  `max-width: clamp(640px, 92vw, 1400px)` or container-query-driven
  layouts (`@container (min-width: 800px) { … }`) — Baseline-widely
  available since 2024. The page's data density allows it to scale.
- **Sketch:** swap `max-width: 980px` for `max-width: min(95vw, 1400px)`
  (or a `clamp()` form); add a CSS container query on `.card` if needed
  to switch the index card layout to a 2-column grid on wider viewports.
  Pure CSS, single line edit + an optional container-query block.
- **Why not fixed:** 980px is the safe-with-everything-else value m8
  shipped; nobody re-measured after the data density grew through m1–m12.

### M6 — Page has no `<h1>` per route; only the global `<h1><a>arXMCP notebooks</a></h1>` in `base.html`
- **Severity:** MEDIUM
- **Affected:** `frontend/templates/base.html:49` (the global header H1
  appears on every page identically); index.html uses `<h2>` for "Create
  notebook" and "Existing notebooks"; notebook_detail.html uses `<h2><code>{{
  notebook.slug }}</code></h2>` at line 9 — but the H1 still says
  "arXMCP notebooks" regardless of which notebook is open. A screen-reader
  user navigating by headings hears "arXMCP notebooks" on every page,
  never "bridgeland-stability — arXMCP" or similar.
- **What 2026 SOTA expects:** the `<title>` already varies correctly
  (notebook_detail.html:3); the H1 should too. The arxiv abstract pages
  do this; ar5iv does this; every CMS-style operator console does this.
- **Sketch:** make the `header h1` content a `{% block header_title
  %}arXMCP notebooks{% endblock %}` and override on the detail page with
  `arXMCP notebooks — <code>{{ notebook.slug }}</code>` (or similar).
  Two template edits, zero CSS, zero JS.
- **Why not fixed:** the global brand-bar shipped first; nobody noticed
  the routes never specialized it.

### M7 — No skip-link from header to `<main>`
- **Severity:** MEDIUM
- **Affected:** `frontend/templates/base.html:47-52`. The page jumps
  straight from `<body>` to `<header><h1>` and a keyboard user must tab
  through the header H1 link before reaching the form on `/ui/` or the
  rename input on the detail page. On the detail page that's only 1 tab
  stop; on a future expanded header it could be more. WCAG 2.1 §2.4.1
  expects a "skip to main content" affordance.
- **What 2026 SOTA expects:** `<a class="skip-link" href="#main">Skip to
  main content</a>` as the first child of `<body>`, visible only when
  focused.
- **Sketch:** add `<a class="skip-link" href="#main">Skip to content</a>`
  immediately after `<body>`, give the `<main>` element `id="main"
  tabindex="-1"`, add `.skip-link { position: absolute; left: -9999px;
  top: 0; } .skip-link:focus { left: 0; padding: 0.5rem 1rem; background:
  var(--accent); color: #fff; z-index: 1000; }` to `app.css`. Pure CSS +
  one template line, ~5 lines total.
- **Why not fixed:** 3-page surface made skip-link feel premature; it is
  the cheapest possible a11y win and 2026 baseline expects it.

---

## 5. Low gaps

### L1 — `input[type="text"]` rule applies `--mono` font-family to all text inputs (app.css:73), but the rename input at `notebook_detail.html:34-35` holds a *display name* (not a slug or code) — monospace is wrong here
- **Severity:** LOW
- **Affected:** `frontend/static/app.css:73` (broad rule) +
  `notebook_detail.html:34-35` (the rename input — `name="display_name"`
  is the only `<input type="text">` whose value is prose).
- **Sketch:** swap the broad rule for a more specific one
  (`input[name="slug"], input[name="paper_id"] { font-family: var(--mono); }`)
  or add `input[name="display_name"] { font-family: inherit; }` as an
  override. Pure CSS, single rule change.
- **Why not fixed:** the rule was added during m8 when slug + paper_id
  were the only text inputs; display_name was added in m2 and inherited
  the rule.

### L2 — `.button` and `<button>` share styles but lack `:active` press-state
- **Severity:** LOW
- **Affected:** `frontend/static/app.css:75-87`. Only `:hover` is styled
  via `filter: brightness(1.08)`; no `:active` for the press state means
  clicking the "Open" link on the index page feels unresponsive on slower
  machines (the page-load latency makes the click feel ignored). Same
  applies to the destructive `.danger` rows during the `hx-confirm`
  dialog dismissal.
- **Sketch:** add `button:active, .button:active { filter:
  brightness(0.92); transform: translateY(1px); }` — gate the transform
  on `prefers-reduced-motion: no-preference`. Pure CSS, ~3 lines.

### L3 — Vendor-stamp comment at top of `app.css:1-2` says "(m8)" but the file has accumulated m1+m4 contributions since
- **Severity:** LOW
- **Affected:** `frontend/static/app.css:1-2`. Cosmetic only.
- **Sketch:** update header comment. Single-line edit.

### L4 — Footer middle-dot separators at base.html:57-67 lack `aria-hidden` so SRs read them aloud as "middle dot"
- **Severity:** LOW
- **Affected:** `frontend/templates/base.html:56-68`. The `·` interpuncts
  read aloud as "middle dot" on VoiceOver and "interpunct" on NVDA,
  making the footer noisy.
- **Sketch:** wrap each `·` in `<span aria-hidden="true">·</span>` or
  switch to flex-gap with no separator characters. Five spans or one
  layout change. Pure HTML / CSS.

### L5 — `pre.error:empty { display: none; }` (app.css:110) creates a small layout shift on the 4xx-then-200 path
- **Severity:** LOW
- **Affected:** `frontend/static/app.css:99-110` + every `<pre id="…-error"
  class="error" aria-live="polite">` in the templates. The empty-collapse
  is a small layout-shift hazard.
- **Sketch:** drop `:empty { display: none }`, keep `min-height: 1.2em`,
  rely on `:empty` being visually-blank (no border-box content). Trade a
  reserved 1.2em strip for layout stability.

---

## 6. a11y + motion-safe + token conflicts found in code

- `frontend/static/app.css` (entire file, 126 lines) — **zero**
  `@media (prefers-reduced-motion: reduce)` blocks. H1.
- `frontend/static/app.css:55-87` — **zero** `:focus-visible` rules on
  `button`, `.button`, `input`, `a`. H2.
- `frontend/static/app.css:4-13` — **no** `@media (prefers-color-scheme:
  dark)` companion to the `:root` token block. H3.
- `frontend/templates/notebook_detail.html:15` — `<p class="display-name"
  id="display-name-block">` is an htmx outerHTML success target with **no**
  `aria-live`. H4.
- `frontend/templates/notebook_detail.html:161-168` — `<div id="ingest-
  status">` is the ingest poll swap target with **no** `aria-live`. H4.
- `frontend/templates/notebook_detail.html:180` — `<tbody id="papers-tbody">`
  is the upload swap target with **no** `aria-live`. H4.
- `frontend/templates/base.html:65-67` — `<span id="status-badge">` polls
  every 10s with **no** `aria-live` / `aria-atomic`. H4.
- `frontend/templates/index.html:41` — `<tbody id="notebook-list">` (the
  create-success target after the H5 fix) lacks `aria-live`. H4.
- `frontend/templates/index.html:14, 52` and `frontend/templates/notebook_
  detail.html:94` — `location.reload()` on success discards htmx-native
  swap behavior. H5.
- `frontend/templates/notebook_detail.html:200-202` — `<span class="hint"
  title="upload an ar5iv HTML to enable preview">Preview</span>` lacks
  `aria-disabled="true"` and any visual disabled affordance. M3.
- `frontend/templates/base.html:49` — global `<h1><a href="/ui/">arXMCP
  notebooks</a></h1>` does not specialize per-route; SRs hear the same H1
  on every page. M6.
- `frontend/templates/base.html` (no skip-link); `<main>` at line 52 has
  no `id` and no `tabindex`. M7.
- `frontend/templates/base.html:57-67` — `·` separators have no
  `aria-hidden="true"`. L4.
- `frontend/static/app.css:73` — `input[type="text"]` blanket-applies
  `--mono`, hitting the `display_name` rename field which should be prose.
  L1.
- `frontend/static/app.css:99-110` — `pre.error:empty { display: none; }`
  combined with `min-height: 1.2em` creates a small layout shift on the
  4xx → re-submit → 200 path. L5.
- No element on either template carries `font-variant-numeric: tabular-nums`
  on the `<time>` / count values that change on htmx swap. M1.

---

## 7. What arXMCP does well visually

- **Jinja2 `autoescape` is explicit + load-bearing** —
  `server/routes/ui.py:85-92` constructs the environment with
  `select_autoescape(enabled_extensions=("html","htm","xml"),
  default_for_string=True)` and the comment explicitly names "explicit >
  implicit." Zero `| safe` filters anywhere in the templates. Stored-XSS
  guard for operator-authored fields like `display_name` holds.
- **htmx is vendored as a single file with provenance documented in
  `frontend/static/VENDORED.md`** — version, license (0BSD), source URL,
  vendored date, SHA-256 pinned by
  `tests/test_vendored_assets_integrity.py`. Sets the bar for any future
  vendored drops.
- **The m4 status-badge shares its CSS surface with the m1 parse-status
  badge** — `app.css:113-126` defines `.status-badge` + 4 modifier
  classes (`--ok / --warn / --ops-warn / --down`) used by both the
  per-notebook parse status (`notebook_detail.html:53`) and the global
  footer operability badge (`base.html:65-67`). Consistent visual
  language for "live state."
- **The m2 in-page rename/delete pattern at `notebook_detail.html:26-40`
  is htmx-idiomatic** — `hx-target="#display-name-block" hx-swap="
  outerHTML"` swaps a stable target in place; the rename form deliberately
  sits OUTSIDE the swap target so it survives. Clean separation. (The
  H5 finding above asks Phase 2 to extend this same pattern to the other
  flows.)
- **The m1 parse-status + freshness signal at `notebook_detail.html:50-69`
  combines a CSS-badge categorical signal (`status-badge--{ok,warn,down}`)
  with a relative timestamp (`Last indexed: <time>…</time> (ingest
  {{ status }})`)** — the operator gets both modality + recency in one
  glance, exactly the pattern dev-tool consoles converge on.
- **The preview-route CSP is tight** —
  `CONTENT_SECURITY_POLICY_PREVIEW` at `server/routes/ui.py:483-484`
  applied per-response (overriding the looser `/ui/*` CSP via the
  middleware's "skip-if-handler-set" hook), plus the m10 F1
  meta-refresh strip at lines 470-478. Untrusted ar5iv HTML is hostile-
  by-default; this surface respects that.

---

## 8. Themes

- **The a11y baselines are uniformly missing — not selectively.** The CSS
  has *no* reduced-motion gate, *no* focus-visible, *no* dark-mode tokens;
  the templates have `aria-live` only on the error path, not the success
  path; there's no skip-link and no per-route H1 specialization. These
  are not gaps that arrived one at a time; they are the shape of a
  surface that shipped correctness-first and never had an a11y audit.
  Phase 2 should bundle them as one synthesis candidate ("a11y baseline
  pass") rather than scattering them across 6+ items.
- **There are two htmx UX patterns coexisting on the same code surface
  — the modern m2 rename/delete in-place-swap pattern, and the legacy
  m7/m8 location.reload() pattern.** Converging both flows on the
  in-place-swap pattern would (a) eliminate the flash an operator sees
  on every create, (b) make the codebase consistent, and (c) re-use
  htmx's `aria-live` + `htmx-request` affordances uniformly.
- **The 8-token CSS-variable system is already the right shape for a
  dark-mode and a focus-ring upgrade** — both proposed fixes consume
  existing tokens (`--accent` for focus rings; the same 8 names
  re-bound under `@media (prefers-color-scheme: dark)` for dark
  theming). Phase 2 should NOT propose a new token system — it should
  extend this one.
- **Every meaningful visual gap can be filled in pure CSS or one
  attribute addition.** Zero candidates require new vendored JS, a new
  build chain, or a new dependency. The constraint floor (CLAUDE.md
  §4.7) does NOT prevent the operator console from reaching the 2026
  baseline; it just requires picking the pure-CSS / Web-API path
  every time.

---

*End of brief.*
