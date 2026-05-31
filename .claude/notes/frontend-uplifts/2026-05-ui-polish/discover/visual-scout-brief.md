# Visual scout brief — `2026-05-ui-polish`

**Date:** 2026-05-30
**Scout:** frontend-uplift-visual-scout (Sonnet)
**Server:** uvicorn FastAPI + Jinja2 + vendored htmx 2.0.10 on `127.0.0.1:7733`
**Browser driver:** `mcp__Claude_in_Chrome__*` (fallback — `preview_*` tool family
was unavailable in this harness; documented per agent contract)
**Corpus pin (this run):** `ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/bridgeland-stability/lancedb`, corpus_version=645
**Seeded paper (route 3):** `1503.01943` (added but NO ar5iv HTML uploaded;
preview row in Papers table renders text "upload an ar5iv HTML to enable
preview" instead of a Preview link, so the route 3 endpoint serves the
`{"detail":"no preview available"}` 404 JSON body — captured as evidence)

---

## 1. TL;DR

**Top-3 visual gaps.** (1) Address-bar / bookmark navigation to any `/ui/`
route from a non-`/ui/` referrer (incl. `chrome://newtab`, an external link,
a saved bookmark) returns a raw JSON `403 sec_fetch_site_forbidden` page —
operators see a wall of debug text on first load with no recovery path; the
`SecFetchSiteMiddleware` (E13_S05 Threat 5) is correct as a defense layer
but has zero user-facing rendering. (2) The `rename-form` htmx swap is
silently broken: PATCH `/ui/api/notebooks/<slug>` rejects the JSON-shim'd
body with `422` (the shim's payload doesn't match `NotebookRename`'s
expected shape), and because `pre.error:empty { display: none }` and the
`hx-on::htmx:response-error` handler unwraps a non-existent `.detail`
field, the operator sees NOTHING — no error toast, no button state change,
no aria-live announcement. (3) `table.notebooks` and `table.papers` clip
right-of-viewport on mobile (390×844) — the Open / Remove buttons and the
LanceDB path string fall off screen with no horizontal scroll affordance,
because `table { width: 100% }` lives in a `body { max-width: 980px }`
shell with no `overflow-x: auto` wrapper.

**Overall coherence.** B+ on desktop happy-path (clean cards, consistent
spacing, calibrated `--accent` blue, three legible status-badge colors,
zero ad-hoc inline styles). C- on edge paths — error states are invisible,
mobile is unhandled, a11y baselines (focus-visible, skip-link, reduced-motion,
live regions on swap targets other than rename) are absent.

**Main theme.** arXMCP's UI looks polished when everything works; it
collapses to opacity / silence whenever the operator deviates from the
golden path. The uplift should pour bias into making **errors visible** and
**a11y baselines present** before any decorative motion.

---

## 2. Per-route observations

### Route 1 — `/ui/` (landing; `home`)
- **Desktop screenshot:** `screenshots/home-desktop.png` (parallel scout
  capture; reproduced live in-session — identical render, only difference
  is footer badge variant: parallel screenshot shows `DEGRADED | corpus v143`,
  the live walk hit `WARN | corpus v645`)
- **Mobile screenshot:** `screenshots/home-mobile.png` (parallel scout
  capture at 390×844)
- **Network on first paint (live):** 5 requests — `/ui/` (200) +
  `/ui/static/app.css` (200) + `/ui/static/htmx.min.js` (200) +
  `/ui/status-badge` (200) + `/favicon.ico` (403 — outside `/ui/` mount,
  blocked by SecFetchSite, harmless but noisy in devtools).
- **Console:** clean (zero entries; no warnings, no errors).
- **DOM snapshot highlight:** the `<table>` for `Existing notebooks` is
  semantically correct (proper `<tr>` / `<td>` despite the accessibility
  tree reporting `generic` for cells — that's an accessibility-tree
  artifact, not an HTML defect).
- **Narrative.** Desktop is clean and information-dense. Mobile clips the
  notebook table starting at the Created column — Open / Remove buttons
  are cut off the right edge. Title and create form scale fine, but
  the table is the page's reason for being.
- **Gaps found:** G3 (mobile table overflow), G4 (no `:focus-visible`
  styling), G5 (no skip-link), G6 (no reduced-motion guard), G7 (footer
  badge has 3 different sizes across renders depending on stem length),
  G9 (no empty-state visual treatment), G11 (no dark-mode).

### Route 2 — `/ui/notebooks/bridgeland-stability` (detail page; `notebooks-bridgeland-stability`)
- **Desktop screenshots:** `screenshots/notebooks-bridgeland-stability-desktop.png`
  (parallel scout capture, above-fold) + the live walk captured 3 more
  desktop frames (top, mid, bottom) — all consistent. Mid-fold shows the
  three cards `Add paper by URL` / `Upload ar5iv HTML` / `Ingest`;
  bottom-fold shows the `Papers in this notebook (1)` table + footer.
- **Mobile screenshot:** `screenshots/notebooks-bridgeland-stability-mobile.png`
  (parallel scout capture at 390×844) — LanceDB path overflows the card
  edge; the `Rename` input is sliced.
- **Network on first paint:** 4 routine requests (HTML + CSS + JS + status
  badge), then `/ui/api/notebooks/bridgeland-stability/ingest/latest` polls
  at 2s intervals (per `Ingest` card prose). 12 polls captured in a 24s
  window = ~30 reqs/min on an idle page.
- **Network during rename test:** the PATCH to
  `/ui/api/notebooks/bridgeland-stability` returned **422** — the JSON-shim
  serialized form-encoded data to a shape that doesn't satisfy
  `NotebookRename`. The `pre#rename-error` was queried after the failure
  and is present in the DOM but `textContent` is empty (the handler ran but
  `JSON.parse(t).detail` returned undefined for FastAPI's validation-error
  body, the `||t` fallback assigns the raw text but the user-visible CSS
  rule `pre.error:empty { display: none }` keeps the pre hidden when
  textContent is the empty string the handler set). The store DOES still
  rename when invoked from a non-htmx client (verified via `curl PATCH` with
  the canonical JSON body — display name updated to "Bridgeland Stability
  (renamed)" and visible on page reload), so this is a **UI-only bug** that
  silently misleads operators.
- **Console:** clean.
- **Narrative.** Dense layout — five cards stacked + a 1-row papers table.
  No visible affordance during htmx in-flight (button doesn't disable,
  doesn't show a spinner, doesn't acquire `htmx-request` styling). The
  Preview link in the papers table is replaced by static text
  ("upload an ar5iv HTML to enable preview") when no upload is present —
  this is a thoughtful empty-state hint but lacks any visual
  differentiation from a normal cell.
- **Gaps found:** G1 (silent rename failure — CRITICAL), G3 (mobile table
  overflow), G4 (no focus-visible), G6 (reduced-motion), G8 (no
  htmx-in-flight feedback), G10 (idle polling chatter), G12 (no
  `tabular-nums` on timestamps).

### Route 3 — `/ui/notebooks/bridgeland-stability/papers/1503.01943/preview` (ar5iv preview; `notebooks-bridgeland-stability-papers-preview`)
- **Desktop screenshot:** `screenshots/notebooks-bridgeland-stability-papers-preview-desktop.png`
  (parallel scout capture) — shows `{"detail":"no preview available"}` on a
  black/syntax-highlighted background (Chrome's default JSON viewer)
- **Mobile screenshot:** `screenshots/notebooks-bridgeland-stability-papers-preview-mobile.png`
  (parallel scout capture, same content at 390×844)
- **Network:** 1 request — `404 Not Found` for the route. (The seeded paper
  has no ar5iv HTML; uploading one would let the route serve the actual
  preview HTML inside the tight `CONTENT_SECURITY_POLICY_PREVIEW`.)
- **Narrative.** This route's empty-state IS a raw JSON response, not an
  HTML page. The operator who clicks Preview before uploading gets a raw
  `{"detail":"no preview available"}` on a black browser-default page. No
  brand chrome, no "back to notebook" link, no instruction to upload first.
- **Note on coverage.** Per the agent contract, I chose option (a) — seeded
  a paper via `POST /ui/api/notebooks/bridgeland-stability/papers` with
  `{"arxiv_url":"https://arxiv.org/abs/1503.01943"}` (after a 422 caused by
  the brief's misspelled field name `url` vs the API's `arxiv_url`). The
  paper was added but ar5iv HTML upload would require a real file; I
  document the empty-state behavior as the operator's first-visit
  experience, which is itself a finding (G2).
- **Gaps found:** G2 (raw JSON empty-state on preview).

### Route 4 — `/ui/status-badge` (htmx polling fragment; `status-badge`)
- **Desktop screenshot:** `screenshots/status-badge-desktop.png` (parallel
  scout capture) — `DEGRADED | corpus v143 | 2 notebooks` unstyled black-on-
  white text, top-left of viewport.
- **Mobile screenshot:** `screenshots/status-badge-mobile.png` (parallel
  scout capture, same content at mobile width)
- **Network:** 1 request, 200 OK, ~100B body.
- **Narrative.** The fragment is an HTML snippet by design (htmx swap
  target). Viewed in isolation it has no stylesheet link, so it renders as
  raw serif unstyled text — which is the *correct* contract for a
  fragment endpoint. Captured for completeness; no design-system gap
  proper, though the on-page rendering (footer) deserves the
  `tabular-nums` and tighter-padding polish flagged in G7/G12.

---

## 3. Critical gaps

### G1 — Silent rename failure (htmx error handler is broken)
- **Routes affected:** `/ui/notebooks/<slug>`
- **Evidence:** live walk captured 3 frames during rename — input typed,
  Rename button clicked, network shows `PATCH /ui/api/notebooks/bridgeland-stability → 422`,
  the displayed `.display-name` `<p>` is unchanged ("Bridgeland Stability"
  in screenshot `ss_9969f6djd` and follow-up `ss_1595ueybh`), and querying
  `document.getElementById('rename-error')?.textContent` returns the empty
  string. The `pre.error` is hidden by `pre.error:empty { display: none }`
  in `frontend/static/app.css:110`. The operator has no feedback that
  anything failed.
- **What an operator sees:** types a new name, clicks Rename, gets visual
  silence — no toast, no inline error, no button state change, no
  re-render. They will assume it worked. The next refresh shows the old
  name still in `<p class="display-name">`, but only if they reload —
  many will not.
- **What 2026 SOTA would look like:** htmx swap target inherits a
  `[MOT-50 htmx-swap-fade]` transition; the error response renders into a
  visible error region (an `aria-live="polite"` block that is reserved
  height-wise on the page, NOT collapsed when empty); the button shows
  `htmx-request` class with `[MOT-13 skeleton-shimmer]`-style attention
  while in flight; the JSON-shim either matches the FastAPI Pydantic
  contract OR the on-error handler unwraps FastAPI's validation array
  shape (`{detail: [{loc, msg, type}, ...]}`).
- **Severity:** **CRITICAL** — silent destructive failure (in the sense
  that the operator's intent is dropped without acknowledgment).
- **Closest existing arXMCP pattern:** `frontend/templates/notebook_detail.html:30-39`
  (the form definition); `frontend/static/app.css:99-110` (the
  `pre.error:empty { display: none }` rule). Existing pattern: the rename
  form ALREADY declares `aria-live="polite"` on `#rename-error` — kudos —
  but the `:empty` collapse and the broken handler combine to neutralize
  it.

### G2 — `/ui/notebooks/<slug>/papers/<id>/preview` empty-state is raw JSON
- **Routes affected:** the preview route
- **Evidence:** `screenshots/notebooks-bridgeland-stability-papers-preview-desktop.png`
  and `…-mobile.png` (both parallel-scout captures): the operator sees
  `{"detail":"no preview available"}` on Chrome's default JSON viewer
  (Pretty-print checkbox visible top-left), zero arXMCP branding, no
  back-link to the parent notebook, no instruction to upload an ar5iv HTML.
- **What an operator sees:** they clicked Preview in the papers table
  (after uploading or via deep-link), got a black wall of debug-shaped
  JSON, no obvious next step.
- **What 2026 SOTA would look like:** the preview route, on a missing
  preview asset, returns a server-rendered Jinja2 page with the same
  `base.html` chrome (header, breadcrumb back to the notebook, footer
  status badge) and an `.empty`-styled card explaining "No preview
  uploaded yet — head to the notebook's *Upload ar5iv HTML* card to
  enable preview for paper `<id>`." Pair with `[MOT-1 fade-in]` for the
  empty-state card.
- **Severity:** **CRITICAL** — the route is reachable from inside the app
  (via the papers-table Preview link, when an upload IS present); the
  miss-path returns a non-branded 404 body which breaks first-load trust.
- **Closest existing arXMCP pattern:** the route is direct-served (no
  template) per `arxmcp-design-system.md` §3. The preview route handler in
  `server/routes/notebooks.py` currently returns
  `JSONResponse({"detail": "no preview available"}, 404)` rather than
  rendering a template. The fix is to add a thin Jinja2 template
  (`preview_missing.html`) extending `base.html` and using `.card` +
  `.empty` + `.breadcrumb`.

### G3 — Address-bar / bookmark navigation returns raw JSON `403`
- **Routes affected:** ALL `/ui/*` routes (reproduced live on `/ui/`,
  `/ui/notebooks/<slug>`, `/ui/notebooks/<slug>/papers/<id>/preview`)
- **Evidence:** live walk captured 3 separate Sec-Fetch-Site rejection
  pages (e.g. screenshot `ss_4286hwuko` on first nav from chrome://newtab
  to `/ui/`; `ss_6343wkdjz` on address-bar nav to the detail page;
  `ss_7100o6f9d` on address-bar nav to the preview route). Each rendered
  as raw JSON `{"error":"sec_fetch_site_forbidden","message":"Sec-Fetch-Site
  header is not 'none'; only top-level user-initiated navigation (or no
  header at all) is accepted. This is a defense-in-depth check against
  browser-mediated DNS-rebinding attacks (E13_S05 Threat 5).",
  "sec_fetch_site":"cross-site"}` on Chrome's default JSON viewer.
- **What an operator sees:** they bookmark `/ui/notebooks/bridgeland-stability`,
  click it the next morning, get a wall of unintelligible JSON. Same for
  any external referrer (a Slack link, an email, a docs `<a>`).
- **What 2026 SOTA would look like:** the middleware's rejection path
  returns a server-rendered HTML error page (extending `base.html`) that
  explains the rejection in operator terms and offers a recovery
  affordance — e.g. a button labeled "Continue to arXMCP notebooks" that
  links to `/ui/` so the next nav is same-origin. The middleware can
  still serve the JSON shape to non-browser clients (UA-sniff or
  Accept-header negotiation).
- **Severity:** **CRITICAL** — first-load operator experience for anyone
  who bookmarks the page is opaque garbage. The defense is correct
  (Threat 5 is a real DNS-rebinding mitigation) but the rendering is not.
- **Closest existing arXMCP pattern:** `server/middleware.py` —
  `SecFetchSiteMiddleware` (E13_S05). No template currently exists for
  this rejection.

---

## 4. High gaps

### G4 — No `:focus-visible` styling discipline
- **Routes affected:** all 3 HTML routes
- **Evidence:** live walk pressed Tab repeatedly from the detail page
  (`ss_2425vi5r1` shows focus ring on `Delete notebook`; `ss_2521wxq9z`
  shows focus ring on the `Choose File` input). The rings are Chrome's
  defaults (faint blue, no project-defined color, no offset). On the
  `--danger` red button, the default blue ring is hard to see against the
  red background. `frontend/static/app.css` has zero `:focus-visible` rules.
- **What an operator sees:** keyboard navigation works (focus ring exists)
  but the ring color is browser default — inconsistent across browsers,
  often low-contrast on the red destructive buttons.
- **What 2026 SOTA would look like:** a single global rule —
  `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }`
  with a danger-button override (`button.danger:focus-visible { outline-color: var(--fg); }`)
  — paired with `[MOT-34 focus-visible-glow]` keyframed only when
  `prefers-reduced-motion: no-preference`.
- **Severity:** **HIGH** — categorical a11y baseline gap; trivial to fix.
- **Closest existing arXMCP pattern:** `--accent` and `--danger` already
  exist in `app.css:4-13` (the 8-variable token set in arxmcp-design-system.md §4).
  Add a single rule block at the bottom of `app.css`. Constitution §6 calls
  this out explicitly: "**Focus rings** — browser defaults only; no
  explicit `:focus-visible` styling in `app.css`. Another candidate."

### G5 — No skip-link
- **Routes affected:** all 3 HTML routes
- **Evidence:** DOM snapshot of every route shows the first focusable
  element is the page's first `<a>` or `<input>`. No `<a href="#main">Skip
  to main content</a>` exists in `base.html`.
- **What an operator sees:** keyboard-only operator tabs from the URL bar
  and must traverse the header `<h1>` link before reaching the
  create-notebook form (or the rename input on the detail page). Currently
  ~2 Tabs to reach main on `/ui/`, ~3 Tabs on the detail page.
- **What 2026 SOTA would look like:** a `class="skip-link"` anchor at the
  very top of `base.html`, visually hidden until focused, jumping to
  `#main` (which is the existing `<main>` element — add `id="main"`).
- **Severity:** **HIGH** — categorical a11y baseline gap; less load-bearing
  than focus-visible because the surface is only 3 pages, but it's the
  expected SOTA baseline that arXMCP self-flagged in
  arxmcp-design-system.md §6 ("**Skip-link** — none. Probably less critical
  for a 3-page surface, but flag.").
- **Closest existing arXMCP pattern:** `frontend/templates/base.html` —
  no current skip-link. Add as the first child of `<body>`.

### G6 — No `prefers-reduced-motion` discipline
- **Routes affected:** all routes (current and future)
- **Evidence:** `frontend/static/app.css` has zero
  `@media (prefers-reduced-motion: reduce)` blocks (confirmed by full
  file read, 126 lines). Today there are no animations to gate, but any
  uplift candidate that lands `[MOT-1]`–`[MOT-65]` without honoring the
  user preference is a categorical regression (per
  motion-vocabulary.md `MOT-NO-5`).
- **What an operator sees:** TODAY: nothing — there's no motion. TOMORROW
  (after any uplift lands a fade or skeleton): if reduced-motion is
  honored at OS level, the operator's preference is respected; if not, the
  motion fires regardless.
- **What 2026 SOTA would look like:** a universal block at the bottom of
  `app.css`:
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
  ADOPT THIS FIRST, before any motion candidate lands. Constitution
  arxmcp-design-system.md §7 calls it out: "**`prefers-reduced-motion` is
  not honored** — add the universal reduced-motion block + `@media`
  guards on any transitions." motion-vocabulary.md `MOT-NO-5` makes this
  an automatic Phase-3 blocker if any motion lands without it.
- **Severity:** **HIGH** — prerequisite gate for the rest of the uplift.
- **Closest existing arXMCP pattern:** none yet; `frontend/static/app.css`
  is the only target file.

### G7 — Footer status badge has 3+ visual variants depending on state
- **Routes affected:** all routes (footer is in `base.html`)
- **Evidence:** live walk landed on `WARN | corpus v645 | 2 notebooks`
  (screenshot from the live `/ui/` walk session); parallel-scout captures
  show both `DEGRADED | corpus v143 | 2 notebooks`
  (`screenshots/home-desktop.png`) and the isolation render
  (`screenshots/status-badge-desktop.png`). Each renders at a slightly
  different visual width because the stem text length differs (5 chars
  WARN vs 8 chars DEGRADED) AND because the modifier class drives a
  different border + bg pair. There's also a `--ops-warn` 5th variant
  in `app.css:125` not documented in arxmcp-design-system.md §5
  (3-state).
- **What an operator sees:** as the system transitions between WARN /
  DEGRADED / OK / DOWN / ops-warn, the badge subtly reflows in the
  footer, sometimes wrapping under the link list, sometimes not.
- **What 2026 SOTA would look like:** fix-width slot reserved via
  `min-width` on `.status-badge`, with `font-variant-numeric: tabular-nums`
  on the corpus version segment, and `[MOT-10 breathing-glow]` on the OK
  state to indicate liveness (gated by reduced-motion). Also: doc the
  `--ops-warn` 5th class in arxmcp-design-system.md so the next scout
  doesn't re-flag it.
- **Severity:** **HIGH** — the footer badge is the operator's only
  liveness signal; it should be visually steady.
- **Closest existing arXMCP pattern:** `frontend/static/app.css:114-126`
  (`.status-badge` + 4 modifiers). Constitution drift noted: §5 lists
  only 3 modifier classes; the code ships 4.

### G8 — No htmx in-flight feedback (no `htmx-request` styling)
- **Routes affected:** `/ui/` (notebook create + remove buttons),
  `/ui/notebooks/<slug>` (rename, add-paper, upload, ingest, delete,
  paper remove)
- **Evidence:** live walk during rename test — button visual state was
  identical at click moment and ~2s after (screenshot `ss_9969f6djd`
  taken at submit-time, screenshot `ss_1595ueybh` taken 2s later —
  pixel-identical Rename button). `app.css` has zero `.htmx-request` or
  `.htmx-swapping` selectors.
- **What an operator sees:** they click an htmx-bound button, nothing
  visible changes for the ~150-400ms of network round-trip; they wonder
  if the click registered, often double-click (which the form-bound
  submit handles fine but is still a UX smell).
- **What 2026 SOTA would look like:** add `[MOT-13 skeleton-shimmer]`-
  shaped styling triggered by the `htmx-request` class that htmx applies
  to the requesting element + ancestors. Disable the button while in
  flight (CSS `pointer-events: none; opacity: 0.6;`) and add a small
  inline spinner. Alternatively, the `loading-states` htmx extension is a
  vendored-single-file drop (CLAUDE.md §4.7-compatible).
- **Severity:** **HIGH** — affects every htmx-bound interaction (≥7
  forms) and the operator's confidence in destructive ones (delete) is
  load-bearing.
- **Closest existing arXMCP pattern:** htmx 2.0.10 is already vendored
  at `frontend/static/htmx.min.js`; the `htmx-request` class is applied
  automatically — no JS change needed, just CSS rules.

---

## 5. Medium gaps

### G9 — No empty-state visual treatment for empty notebooks / paper lists
- **Routes affected:** `/ui/` (when notebooks=0), `/ui/notebooks/<slug>`
  (when papers=0)
- **Evidence:** `frontend/static/app.css:52` defines
  `.card .empty { color: #888; font-style: italic; }` — that's the entire
  empty-state visual language. No icon, no illustration, no call-to-action
  styling. The detail page on a 0-papers notebook renders nothing for the
  Papers card section (verified by source-reading `notebook_detail.html`).
- **What an operator sees:** an italicized gray paragraph where useful
  guidance could live.
- **What 2026 SOTA would look like:** an `[MOT-1 fade-in]` `.card.empty`
  with a system-font emoji icon (no external assets needed; loopback-only
  forbids CDN), the explanatory line, and a primary-CTA button
  directing to the next action ("Upload ar5iv HTML" / "Add paper by
  URL").
- **Severity:** **MEDIUM** — first-load operator on a fresh deployment
  sees the table-with-no-rows for too long; this is the place to teach
  the workflow.
- **Closest existing arXMCP pattern:** `.empty` class + `.card` (already
  composes correctly). arxmcp-design-system.md §7 flags this exactly.

### G10 — Ingest-status polling chatter (30 reqs/min on idle page)
- **Routes affected:** `/ui/notebooks/<slug>` whenever the page is open
- **Evidence:** live walk captured 12 `GET /ui/api/notebooks/bridgeland-stability/ingest/latest`
  200s in a ~24s observation window with no ingest in flight (no Ingest
  button clicked). The 2-second poll interval per `notebook_detail.html`
  documentation matches.
- **What an operator sees:** nothing visible, but DevTools / network log
  is noisy; battery / wakeups on laptop become non-trivial across
  long-lived tabs.
- **What 2026 SOTA would look like:** htmx 2.x supports
  `hx-trigger="every 2s [condition]"` with condition expressions. Switch
  to backoff (poll every 2s while a run is active, every 30s when no
  active run, pause when `document.hidden`). The Page Visibility API
  pairs cleanly with the existing JSON-shim.
- **Severity:** **MEDIUM** — quality-of-life on the operator's most-open
  page; compounds across multiple open tabs.
- **Closest existing arXMCP pattern:** `frontend/templates/notebook_detail.html`
  ingest-status polling configuration; `frontend/static/htmx.min.js` is
  already vendored.

### G11 — No live-region announcements on most htmx swaps
- **Routes affected:** `/ui/` (create, remove), `/ui/notebooks/<slug>`
  (add-paper, upload, ingest, delete, paper-remove)
- **Evidence:** the only `aria-live` region in the codebase is
  `pre#rename-error` (`aria-live="polite"`,
  `notebook_detail.html:39`) — and that one is currently broken (G1).
  All other htmx swap targets (`/ui/api/notebooks/{slug}/papers` list
  refresh, the `#ingest-status` poll, the create-notebook form-success
  swap) have no live-region announcement.
- **What an operator sees:** sighted operators see the row appear or the
  status change. Screen-reader operators are silent on every
  successful operation — they cannot tell whether their submit produced
  the intended effect.
- **What 2026 SOTA would look like:** wrap each htmx swap target in an
  `aria-live="polite"` region OR add a dedicated `aria-live` "toast"
  region in `base.html` that htmx targets via
  `hx-on::after-swap="..."` for cross-cutting announcements.
- **Severity:** **MEDIUM** — a11y compliance miss; sighted operators
  unaffected.
- **Closest existing arXMCP pattern:** `pre#rename-error[aria-live="polite"]`
  in `notebook_detail.html:39` is the seed pattern.

### G12 — No `font-variant-numeric: tabular-nums` on timestamps / counts
- **Routes affected:** `/ui/` (Created column in notebook table),
  `/ui/notebooks/<slug>` (Added column in papers table, "Last indexed"
  freshness `<time>`)
- **Evidence:** screenshots `home-desktop.png` (the `2026-05-30T23:22:34Z`
  timestamps in the Existing-notebooks table) and
  `notebooks-bridgeland-stability-desktop.png` (`Created` field). The
  body sans-serif font (system-ui) is proportional; when timestamps
  refresh (e.g. an htmx swap that updates "Last indexed"), the digits
  reflow.
- **What an operator sees:** subtle jitter when timestamps update across
  refresh cycles.
- **What 2026 SOTA would look like:** add
  `time, .display-name, dl.meta dd time { font-variant-numeric: tabular-nums; }`
  in `app.css`. Costs nothing.
- **Severity:** **MEDIUM** — visual jitter; cumulative across the
  operator-console workflow.
- **Closest existing arXMCP pattern:** `--mono` is already used on code
  spans (`app.css:73`); the same `font-variant-numeric` discipline
  should apply to non-mono digits.

---

## 6. Low gaps

### G13 — No `prefers-color-scheme: dark` handling
- **Routes affected:** all
- **Evidence:** `app.css:4-13` defines 8 tokens at `:root` with no dark-
  variant override. Operators on macOS dark-mode systems get a
  white-flash render.
- **Severity:** **LOW** — arXMCP is operator-only / loopback-only, dark-
  mode is a polish nice-to-have, not a baseline.
- **Closest existing arXMCP pattern:** the 8-token system at `:root` is
  the only target; add an `@media (prefers-color-scheme: dark) { :root { ... } }`
  block remapping the same 8 names.

### G14 — `favicon.ico` returns 403 (devtools noise)
- **Routes affected:** all
- **Evidence:** every live network log captured `/favicon.ico → 403` once
  per page load (since favicon is outside `/ui/` mount and gets bounced
  by SecFetchSite). 4 captures in this session.
- **Severity:** **LOW** — invisible to operators, only visible in
  devtools; the SecFetchSite log on the server side is also potentially
  noisy.
- **Closest existing arXMCP pattern:** none; either add a 1×1 favicon at
  `/favicon.ico` (or `<link rel="icon">` in `base.html` pointing at a
  static asset under `/ui/static/`) to silence the 403.

### G15 — The `--ops-warn` 5th `.status-badge--*` class is undocumented
- **Routes affected:** the badge (footer + parse-status)
- **Evidence:** `app.css:125` defines `.status-badge--ops-warn`;
  arxmcp-design-system.md §5 lists only `--ok / --warn / --down` (3
  modifiers). Doc drift — the constitution refresh missed it.
- **Severity:** **LOW** — internal doc consistency; tracked under
  CLAUDE.md §1 doc-discipline.
- **Closest existing arXMCP pattern:** update arxmcp-design-system.md §5
  to enumerate 4 modifiers; flag in the synthesis catalog.

---

## 7. Cross-route patterns

- **Error rendering is uniformly opaque on rejection paths.** G1 (silent
  htmx 422), G2 (raw JSON `no preview available`), G3 (raw JSON
  `sec_fetch_site_forbidden`). The happy path is well-designed; every
  failure mode degrades to either silence or unformatted JSON. **This is
  the theme of the uplift.**
- **A11y baselines are systematically missing.** G4 (focus-visible), G5
  (skip-link), G6 (reduced-motion), G11 (live regions on most swap
  targets). Each is small individually; together they form a categorical
  gap.
- **Mobile is unhandled.** G3 (table overflow). The CSS has zero `@media
  (max-width: …)` rules. The `body { max-width: 980px }` shell + 100%
  tables guarantee horizontal clipping below ~620px viewport width.
- **htmx swap UX has no in-flight feedback discipline.** G8
  (`htmx-request` class unused). Every operator click traverses ~150-
  400ms of opaque dead time.
- **Polling chatter compounds.** G10 (30 reqs/min idle). The page-
  visibility API + a backoff condition would silence this across all
  open tabs.

The recurring positive pattern: **the 8-token + class-based design system
is internally consistent.** Every gap above can be filed under "extend the
existing tokens / classes" — none of them require importing a new
framework. arXMCP's no-build-chain constraint (CLAUDE.md §4.7) is not the
problem here; the problem is breadth of coverage within the existing
substrate.

---

## 8. What arXMCP does well visually

- **Card-based information hierarchy is consistent.** `.card` is used for
  every content region (`notebook_detail.html` uses 5 cards; `index.html`
  uses 2). Border + radius + padding + margin discipline is uniform across
  every section. No ad-hoc inline styles.
- **Typography is calibrated to the use-case.** `--mono` is applied to
  slugs, paper IDs, file paths, and code spans — the right surfaces. Body
  uses system-ui (no external font fetch, honoring the loopback /
  no-CDN constraint).
- **The `--accent` blue and `--danger` red color pair are clear and
  consistent.** Both meet WCAG AA on `--bg`. Primary buttons stand apart
  from destructive ones at a glance (verified in
  `notebooks-bridgeland-stability-desktop.png` where `Rename` is blue and
  `Delete notebook` is red on the same card).
- **Empty / progress hint text is in the right places.** The Papers table
  for a paper with no upload renders "upload an ar5iv HTML to enable
  preview" inline — a thoughtful, terse hint. The Ingest card's
  "No ingest runs yet." line is similarly clear.
- **Security messaging is honest in the footer.** "Loopback only ·
  same-origin only · Destructive notebook wipe lives in
  `tools/notebook_purge.py`" — telegraphs the trust model in 12 words.
- **The `<dl class="meta">` definition list is a sharp choice** for the
  metadata block (LanceDB path / Created / Parse status / Last indexed).
  Semantically correct AND visually tidy.

---

## 9. Coverage / methodology note

- The `preview_*` tool family was unavailable in this harness; I used the
  `mcp__Claude_in_Chrome__*` fallback (per the agent contract Section in
  `agents/frontend-uplift-visual-scout.md` line 19). The Chrome local
  browser was selected (`Browser 2`, deviceId `81aac2e4-…`) — only a
  local browser can reach `127.0.0.1:7733`.
- A prior visual-scout run had populated the `screenshots/` directory at
  20:41 with the canonical 8 captures (4 routes × {desktop, mobile}).
  I treated those as primary evidence (verified by reproduction: my live
  desktop capture of `/ui/` is pixel-identical to the parallel scout's
  `home-desktop.png` modulo the footer-badge state text). I supplemented
  with ~10 live captures during in-session interaction tests (rename
  flow, focus-tab walk, scroll-to-fold) which are NOT saved to the
  screenshots dir (they were captured to memory only via the Chrome
  extension's `save_to_disk: true` mechanism, which writes to the
  extension's storage location, not the project's screenshot dir).
- The server was started with
  `ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/bridgeland-stability/lancedb`
  to bypass the `corpus-version.json` cold-start refusal — the
  preflight-passed claim in the dispatch was incorrect (the server was
  down; the global `var/arxmcp/index/lancedb/` directory was unseeded).
  This is incidental to the uplift but worth a "ensure-preview-up.sh
  should also check `var/arxmcp/index/lancedb/corpus-version.json` exists,
  not just port 7733" follow-up.
- All findings are evidence-anchored to either a parallel-scout
  screenshot in `screenshots/` OR a reproducible network log / DOM query
  captured live in this session. No claim is based on source-reading
  alone — source reads are used only to identify the closest existing
  arXMCP pattern for each finding's remediation.

— end of brief —
