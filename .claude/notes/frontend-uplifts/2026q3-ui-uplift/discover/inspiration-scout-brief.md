# Inspiration scout brief — 2026q3-ui-uplift

**Scope note (premise correction):** the uplift brief asks what looks "AI-generated and unoriginal
in terms of the standard tailwind + shadcn UI feel" — but arXMCP's `/ui/` has **neither Tailwind
nor shadcn**. It is a single hand-rolled 371-line `frontend/static/app.css` file whose dark-mode
branch is a documented GitHub-Primer clone (`--fg #e8e8e8` / `--bg #0d1117` / `--accent #58a6ff`
etc. — see `visual-manifest.md` §1). The genericness the user is reacting to is real, but its
source is "8 tokens, no scale, no shadow, one card silhouette repeated 7×" rather than a stock
component library. This changes the fix: instead of ripping out Tailwind/shadcn (there is none to
rip out), the fix is (a) *information-architecture* discipline borrowed from tools that already
solve "dense list + dense detail + live status" well, and (b) *extending the Primer vocabulary
arXMCP already half-adopted* rather than importing a new one. On the "new libraries for an
interactive feel" ask: given CLAUDE.md §4.7 (no npm, no build chain, vendored single-file drops
only — already re-verified in `arxmcp-design-system.md` §9), the correct answer is **zero new
libraries**. Every pattern below is achievable with vanilla JS (`<details>`, native `<dialog>`,
`:focus-within`, `keydown` listeners) and CSS reusing the 8 existing tokens + the `.status-badge`
family — the same posture as the existing htmx-only stack.

## 1. TL;DR

The single highest-value borrow is **NotebookLM's "Discover sources"** flow (annotated
relevance blurb + one-click import) — it is arXMCP's own "Discover papers" card, already shipped
by a scholarly-AI tool at a major vendor, proving the pattern is legible to researchers, not just
SaaS operators. The main thematic shift arXMCP should adopt is **progressive disclosure over
uniform-card stacking**: every dense operator surface reviewed (Linear's 2026 refresh, GitHub's
ActionList/Blankslate primitives, Vercel's redesigned deployment list) demotes secondary/rare
controls visually so the primary object of the page — issues, deployments, sources, papers — reads
first, which is the exact fix for `notebook_detail.html`'s 7 visually-identical cards burying the
papers table at y=1823px. A secondary theme is **status as a first-class, historical signal, not
just a snapshot**: Grafana's state-timeline and Datadog's monitor-history graphs both show *recent
state over time*, not just "current state," which arXMCP's badge and ingest-status surfaces
currently discard on every poll.

## 2. Pattern candidates

### P1 — De-emphasized secondary controls ("structure felt, not seen")
- **Pattern name:** Progressive disclosure of rare-use forms
- **Source platform:** Linear (2026 interface refresh)
- **Public evidence:** https://linear.app/now/behind-the-latest-design-refresh
- **What makes it good:** Linear's own write-up of its refresh states the design principle
  directly — "don't compete for attention you haven't earned" — and describes concretely
  de-emphasizing the sidebar ("a few notches dimmer") and reducing icon/border visual weight so
  the content an operator is actually working on reads first. It names the exact failure mode
  arXMCP has: every element at equal visual weight is functionally the same as no hierarchy.
- **Motion vocabulary primitives:** `[MOT-15 accordion-expand]` (native `<details>`/`<summary>`,
  CSS-only, no JS)
- **Where it fits arXMCP:** `frontend/templates/notebook_detail.html` — the "Add paper by URL"
  card (lines 181–219) and "Upload ar5iv HTML" card (lines 221–249) are used far less often per
  session than the papers table itself. Wrapping the rarely-touched cards in `<details>` (closed
  by default, `open` attribute settable via a `localStorage` "operator left it open" convenience —
  optional) pulls the "Papers in this notebook" section (currently y=1823, per
  `visual-manifest.md` §3's 7-card table) up by ~500px without deleting any control.
- **arXMCP-positioning:** operator-surface only (no marketing surface exists today).

### P2 — Dense, grouped list with inline status
- **Pattern name:** Grouped-by-status dense list row
- **Source platform:** Vercel dashboard
- **Public evidence:** https://vercel.com/changelog/redesigned-deployments-list
- **What makes it good:** the changelog entry itself names the three moves — "a denser layout, so
  you can see more deployments at once," "environments are now grouped with statuses," and
  "branches and commits easier to scan." It is a direct precedent for solving arXMCP's own
  `table.notebooks` gap: today's list (`index.html`) shows only slug / display name / created,
  and — per `arxmcp-design-system.md` §7 — never surfaces the `kind` field (`arxiv` vs
  `textbook`) that the server already tracks, forcing an operator to open every notebook to
  triage which kind it is.
- **Motion vocabulary primitives:** none — this is a static layout-density change, no animation
  job is served (motion-vocabulary §0 jobs test: adding a column is not an entry/exit/state-change
  event).
- **Where it fits arXMCP:** `frontend/templates/index.html` `table.notebooks` (lines 79–121,
  header row at 82). Add a `kind` chip column reusing the `.status-badge` class family (see P4)
  and surface `parse_status` / last-indexed inline so the list alone answers "is this notebook
  usable" without a click-through.
- **arXMCP-positioning:** operator-surface.

### P3 — Blankslate: empty state with icon + heading + one action
- **Pattern name:** Structured empty-state component (Blankslate)
- **Source platform:** GitHub Primer design system
- **Public evidence:** https://primer.style/components/blankslate/
- **What makes it good:** Primer's own component docs define the anatomy precisely — visual
  (icon), heading, description, and a `PrimaryAction` — "to tell users why content is missing"
  and give them exactly one next step. arXMCP's current empty states (`.empty` class,
  `app.css:64`) are italic centered grey text with **zero icon and zero action affordance**, which
  is the textbook Blankslate anti-pattern the component was built to replace.
- **Motion vocabulary primitives:** none required — the job test doesn't demand animation for a
  static empty message; keep it static per the calm-at-repeat-use invariant
  (`arxmcp-design-system.md` §9).
- **Where it fits arXMCP:** `.card .empty` (`app.css:64`) styles four distinct empty states —
  `index.html:86` ("No notebooks yet. Create one above."), `notebook_detail.html:177`
  ("No discovery run yet — click Discover above."), `notebook_detail.html:303` ("No papers yet.
  Add one above."), and the `#ingest-status` initial "Loading ingest status…" at
  `notebook_detail.html:296`. Each already carries a *cause* in its copy — Blankslate's
  contribution is pairing that copy with a small inline SVG icon (reuse the existing
  `favicon.svg` provenance pattern, `base.html:14`) and turning the implied action ("click
  Discover above") into an actual anchor/button so the empty state is one click, not a
  scroll-and-find.
- **arXMCP-positioning:** operator-surface.

### P4 — State-label / status-chip vocabulary extension
- **Pattern name:** Semantic status label reused across surfaces
- **Source platform:** GitHub Primer design system
- **Public evidence:** https://primer.style/components/state-label/
- **What makes it good:** Primer's State label docs enumerate a small closed set of semantic
  colors (draft=gray, open=green, closed=purple/red, merged=purple, unavailable=gray) reused
  identically everywhere a state appears — exactly arXMCP's existing `.status-badge--{ok,warn,
  ops-warn,down}` discipline (`app.css:152–168`, dark remap `:286–289`). This is the single
  lowest-risk borrow in this brief: arXMCP's dark palette is *already* Primer-anchored
  (`visual-manifest.md` §1), so extending the same 4-state chip family to a 5th use (notebook
  `kind`) adds zero new tokens and zero new colors — it is applying a rule the project already
  follows, not importing a foreign one.
- **Motion vocabulary primitives:** none.
- **Where it fits arXMCP:** `.status-badge` classes (`app.css:150–168`) — add a `kind` chip
  (e.g. `status-badge--arxiv` / `status-badge--textbook`, reusing the existing `--ops-warn` slate
  palette for one and adding one more Primer-anchored pair) to `index.html`'s notebook row
  (line 90, next to `<code>{{ nb.slug }}</code>`) and to `notebook_detail.html`'s
  `<h2><code>{{ notebook.slug }}</code></h2>` (line 9) — closing the exact gap
  `arxmcp-design-system.md` §7 names: "`index.html` references [kind] 0×."
- **arXMCP-positioning:** operator-surface.

### P5 — Annotated-relevance discovery cards with one-click import
- **Pattern name:** Discover-and-annotate source recommendation
- **Source platform:** Google NotebookLM ("Discover sources")
- **Public evidence:** https://blog.google/technology/google-labs/notebooklm-discover-sources/
- **What makes it good:** this is the closest domain analogue found in this scout pass — a
  scholarly-research tool solving the *identical* workflow arXMCP's "Discover papers" card
  exists for. NotebookLM's post describes the UX precisely: the operator "describes what you're
  interested in," the tool "presents up to 10 source recommendations, each with an annotated
  summary explaining its relevance to your topic," and "with one click, you can import these
  sources." That an AI research-notebook product at Google ships this exact shape (topic → ranked
  candidates with a stated reason → one-click add) is strong validation that dense researchers,
  not just SaaS operators, respond well to it.
- **Motion vocabulary primitives:** `[MOT-1 fade-in]` for the results group as a whole on arrival
  — explicitly **not** `[MOT-3 stagger-reveal]`, because motion-vocabulary §8 AP-3 flags
  stagger-reveal above 8 items as a BLOCKER on S-2 surfaces and NotebookLM's own candidate count
  ("up to 10") can exceed that.
- **Where it fits arXMCP:** `notebook_detail.html` "Discover papers" card (lines 147–179),
  specifically the `#discover-results` target (line 176, currently just
  `<p class="hint">No discovery run yet…</p>`). Each returned candidate should render as a row
  with the paper title, a one-line "why this matches your topic" string (arXMCP already has the
  `discovery_category` + free-text `description` topic fields, `index.html:45–58`, to generate
  this from), and an inline "Add" button — turning a bare result list into the same
  recommend-with-reason shape.
- **arXMCP-positioning:** operator-surface (this is arguably the single most "domain-native"
  candidate in the brief — it borrows from arXMCP's own product category).

### P6 — Job status icon + monospace log tail
- **Pattern name:** Run-status icon with live log stream
- **Source platform:** GitHub Actions
- **Public evidence:** https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/monitoring-workflows/using-the-visualization-graph
  (icon-per-job pattern) + the documented `status`/`conclusion` enum
  (`queued`/`in_progress`/`completed` × `success`/`failure`/`cancelled`/…, per GitHub REST API
  docs surfaced via search on `docs.github.com/articles/about-status-checks`).
- **What makes it good:** GitHub's own visualization docs describe the minimal version of this
  pattern plainly — "an icon to the left of the job name indicates the status of the job." The
  closed enum (queued → in_progress → completed+conclusion) maps almost one-to-one onto
  arXMCP's own ingest-run lifecycle already described in prose at `notebook_detail.html:253–261`
  ("queued -> running -> complete/failed," per the comment at lines 275–276), but the *rendered*
  surface today is plain aria-live text with no icon.
- **Motion vocabulary primitives:** `[MOT-28 spinner]` — already shipped in `app.css:317–332`
  (`.htmx-request::after` + `@keyframes spin`) for the *button*; this candidate reuses the same
  keyframe for the *status icon* rather than introducing a new one.
- **Where it fits arXMCP:** `#ingest-status` (`notebook_detail.html:288–297`), which polls
  `every 2s` per `visual-manifest.md` §4. Prepend a status icon reusing the existing
  `.status-badge--{ok,warn,down}` colors (`app.css:165–168`) to the `data-status` attribute
  already present on the div (line 289), and render any ingest subprocess output inside a
  `<pre>`/`<code>` block in `--mono` rather than the current plain text — the token already
  exists, it's just not applied to this element.
- **arXMCP-positioning:** operator-surface.

### P7 — State-history strip (status over time, not just latest)
- **Pattern name:** State-timeline / uptime-history ticks
- **Source platform:** Grafana (state timeline panel) + Datadog (monitor status page)
- **Public evidence:** https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/state-timeline/
  and https://www.datadoghq.com/blog/monitor-alert-status/
- **What makes it good:** Grafana's docs describe state regions whose "length indicates the
  duration or frequency of a state within a given time range"; Datadog's monitor-status blog
  frames the same idea operationally — "the first place to start your investigation" is the
  history, not the current value alone. Both tools treat *recent state history* as the primary
  signal, which is exactly what arXMCP's footer badge and ingest-status div currently throw away:
  both surfaces show only the LATEST poll result (`visual-manifest.md` §3's badge fragment, §4's
  htmx table), with no memory of the run before it.
- **Motion vocabulary primitives:** `[MOT-26 tooltip-fade]` for a per-tick hover detail (reduced-
  motion gated, per the universal clamp already at `app.css:223`).
- **Where it fits arXMCP:** a lightweight horizontal strip of small colored ticks (reusing the
  four existing `.status-badge--*` colors verbatim, no new tokens) placed above `#ingest-status`
  (`notebook_detail.html:288`) showing the last N ingest runs, and optionally a compressed
  version next to the footer `#status-badge` (`base.html:88–91`). This is additive to, not a
  replacement of, the existing single-state badge.
- **arXMCP-positioning:** operator-surface.

### P8 — Keyboard-first command palette
- **Pattern name:** Cmd-K / `/` command palette
- **Source platform:** Raycast (canonical exemplar); the same pattern is independently confirmed
  shipping on Linear, Vercel, GitHub, and Slack per the search survey below.
- **Public evidence:** https://www.raycast.com (product homepage — "keyboard-first command
  palette... your hands stay on the keyboard").
- **What makes it good:** this is not a novel proposal — `arxmcp-design-system.md` §7 already
  names the exact gap: "No keyboard-shortcut affordances — zero `keydown`/`accesskey` handlers
  anywhere. `/` or Cmd-K to focus the URL-paste input would mirror the Linear/Raycast
  operator-console pattern." This scout pass confirms the pattern's ubiquity across every
  operator-console competitor reviewed and its zero-dependency feasibility: a native `<dialog>`
  element (Baseline-available, no library) plus a `keydown` listener under the existing CSP
  (`script-src 'self' 'unsafe-inline'`) is sufficient.
- **Motion vocabulary primitives:** `[MOT-4 scale-in]` for the dialog mount (native `<dialog>`
  `::backdrop` + a CSS transition, mirroring "Radix Dialog default" in spirit without the Radix
  dependency — motion-vocabulary §1 already lists Radix Dialog as the exemplar for this token,
  the primitive itself is dependency-free).
- **Where it fits arXMCP:** `base.html` (no current `<script>` beyond the JSON-shim and the view-
  transitions opt-in, lines 17–45) — add a `keydown` listener for `/` (when focus is not already
  in a text input) opening a `<dialog>` that fuzzy-filters either notebook slugs (on `index.html`)
  or jumps focus to one of the six named inputs on `notebook_detail.html` (rename, topic,
  discover, add-by-URL, upload, ingest).
- **arXMCP-positioning:** operator-surface (this is THE canonical operator-console pattern —
  arXMCP's single-operator, repeat-use posture is exactly Raycast's target user).

### P9 — Persistent identity strip on the bare reading surface
- **Pattern name:** Sticky metadata/breadcrumb strip on a chrome-less document view
- **Source platform:** arXiv (HTML-format rollout) + Semantic Scholar (paper detail density)
- **Public evidence:** https://blog.arxiv.org/2023/12/21/accessibility-update-arxiv-now-offers-papers-in-html-format/
  and https://www.semanticscholar.org/product
- **What makes it good:** arXiv's own blog post frames the HTML reading surface as something a
  reader accesses "right under the PDF link" on the abstract page — the identity/metadata context
  is never fully abandoned even when the reading surface itself (the paper body) is bare. This is
  the precedent for arXMCP's own gap: `arxmcp-design-system.md` §7 states plainly that the ar5iv
  preview route "direct-serves ar5iv HTML under a tight CSP and extends no template, so it
  inherits no header, no skip-link, and no badge... the absence of a way back is a real UX gap."
- **Motion vocabulary primitives:** none — `position: sticky` is layout, not animation; no
  orientation/causality/feedback/continuity job needs motion here.
- **Where it fits arXMCP:** `GET /ui/notebooks/{slug}/papers/{paper_id}/preview` (no template,
  served directly per `arxmcp-design-system.md` §3). Inject a minimal sticky top strip — outside
  the tight `CONTENT_SECURITY_POLICY_PREVIEW` body, added by the FastAPI handler before the ar5iv
  HTML — carrying "← {slug}" + the `paper_id` in `--mono`, matching the `.breadcrumb` styling
  already defined at `app.css:50–51` and used on `notebook_detail.html:6`.
- **arXMCP-positioning:** operator-surface. (Note: this route currently opens in a new tab
  (`target="_blank"`, `notebook_detail.html:335–337`), so "way back" here means closing the tab
  or navigating in-tab, not literally retracing steps — the strip should make both obvious.)

### P10 — Row-level hover-reveal trailing actions *(proposes new token MOT-52)*
- **Pattern name:** Hover/focus-revealed row actions
- **Source platform:** Linear (row-hover progressive disclosure) + GitHub Primer ActionList
  (trailing-action anatomy)
- **Public evidence:** https://primer.style/components/action-list/ (ActionList "Trailing
  Action: a secondary interactive element... that triggers actions separate from the main item
  selection") and the Linear design-pattern survey (search-aggregated, LogRocket +
  925studios coverage of the 2025–2026 refresh) — "hovering over an issue row causes additional
  actions to appear."
- **What makes it good:** it directly targets a measured problem: `visual-manifest.md` §3 records
  every Remove button rendered at a fixed 77×32px **always visible** in every row of both tables
  (6× on the papers table alone). Revealing destructive row actions only on hover/focus reduces
  per-row visual noise (fewer red buttons competing for attention on a page whose thesis is "calm
  at repeat use," `arxmcp-design-system.md` §9) while keeping the action one interaction away.
- **Motion vocabulary primitives:** **proposes a new token, `[MOT-52 hover-reveal-actions]`**
  (not yet in `frontend-uplift-motion-vocabulary.md` — §1–§7 has no "action visible only on
  row hover/focus" primitive; the closest existing token, `MOT-26 tooltip-fade`, is for
  tooltip content, not an actionable button). Definition: an interactive control's default state
  is `opacity: 0` inside a hover/focus-capable row; it becomes `opacity: 1` on
  `tr:hover, tr:focus-within` (a CSS-only, ~100ms `duration-fast` transition per
  motion-vocabulary §9 token discipline). **This scout did NOT write it into the shared canon
  file directly** — `frontend-uplift-motion-vocabulary.md` is registry-hash-tracked
  (`.claude/.registry-manifest.json`) and editing a SYNCED file outside the sync mechanism risks
  a hash mismatch; the synthesizer/reviewer should promote it if adopted, mirroring how the
  art-direction REF-N entries are "minted only by human promotion" (source-registry §7).
- **Where it fits arXMCP:** `table.papers` rows (`notebook_detail.html:322–357`) and
  `table.notebooks` rows (`index.html:88–117`). **Hard a11y requirement, non-negotiable**:
  `:focus-within` MUST accompany `:hover` in the selector, or this REGRESSES keyboard
  accessibility relative to arXMCP's current always-visible buttons — a hover-only reveal would
  make the Remove action invisible to a keyboard-only or switch-device operator, which is a
  direct violation of the `arxmcp-design-system.md` §6 accessibility posture this project has
  otherwise been careful about (24 `aria-live` regions, explicit `:focus-visible` rings, a
  skip-link). Flag this as a Phase-3 BLOCKER condition if a future candidate proposes hover-only
  without the focus-within twin.
- **arXMCP-positioning:** operator-surface.

### P11 — Clickable status indicator that discloses detail (not just a tooltip)
- **Pattern name:** Click-to-expand diagnostic disclosure
- **Source platform:** Zed editor
- **Public evidence:** https://zed.dev/docs/diagnostics
- **What makes it good:** Zed's own docs state the pattern plainly — the project-wide
  error/warning count lives in the status bar, and "if you click this indicator... you'll open
  the project diagnostics multi-buffer," while a lighter hover already shows "a popover for the
  currently active diagnostic." This is the local-first, single-operator analogue named in the
  brief's domain-4 sourcing instruction (a tool where the user IS the operator, no auth/
  multi-tenant) — closest in spirit to arXMCP's own footer badge, which today only exposes detail
  via the HTML `title` attribute (`visual-manifest.md` §3: "WARN | awaiting first ingest" as a
  bare tooltip string).
- **Motion vocabulary primitives:** `[MOT-15 accordion-expand]` for the disclosure panel (reuse
  of the same primitive as P1 — one disclosure mechanism, two applications).
- **Where it fits arXMCP:** `#status-badge` (`base.html:88–91`). The badge already carries the
  remediation caption inline (`status-badge__remediation`, per `visual-manifest.md` §3, currently
  un-styled and rendering as a run-on line) — wrapping the remediation text in a `<details>`
  disclosure triggered by the badge itself, rather than relying solely on a `title` tooltip
  (which is invisible to touch and to most screen readers), makes the WARN/DEGRADED/DOWN
  remediation guidance actually discoverable.
- **arXMCP-positioning:** operator-surface.

## 3. Sources reviewed

| Platform | URL | What was actually read | High-signal? |
|---|---|---|---|
| Linear | `linear.app/now/behind-the-latest-design-refresh` | Full fetch — de-emphasis/hierarchy principles, icon reduction, palette warming | **Yes** |
| Linear (survey) | LogRocket + 925studios blog posts (search-aggregated) | Search summaries on row density + hover-reveal actions | Yes (corroborating, not primary) |
| Vercel | `vercel.com/changelog/redesigned-deployments-list` | Full fetch — density/grouping/scan claims | **Yes** |
| GitHub Primer | `primer.style/components/action-list/` | Full fetch — anatomy (leading visual, description, trailing action/visual, groups, states) | **Yes** |
| GitHub Primer | `primer.style/components/blankslate/` | Full fetch — empty-state anatomy + usage guidance | **Yes** |
| GitHub Primer | `primer.style/components/state-label/` (via search) | Search summary — closed color-state enum | **Yes** |
| GitHub Actions | `docs.github.com/.../using-the-visualization-graph` | Full fetch — job-icon + dependency-line pattern (log-viewer detail not available in this doc) | Yes (partial) |
| GitHub Actions | REST API `status`/`conclusion` enum (search-aggregated from `docs.github.com`) | Search summary — the closed status vocabulary | Yes |
| Google NotebookLM | `blog.google/technology/google-labs/notebooklm-discover-sources/` | Full fetch — Discover flow, annotated recommendations, one-click import | **Yes (highest-signal single source)** |
| Grafana | `grafana.com/docs/.../state-timeline/` | Search summary — state-region/history semantics | Yes |
| Datadog | `datadoghq.com/blog/monitor-alert-status/` | Search summary — "start investigation from history" framing | Yes |
| Raycast | `raycast.com` | Search-aggregated (product tagline + Cmd-K survey) | Yes (pattern ubiquity, not deep read) |
| Zed | `zed.dev/docs/diagnostics` | Search-confirmed public docs — click-to-expand + hover-popover | **Yes** |
| arXiv blog | `blog.arxiv.org/2023/12/21/accessibility-update-arxiv-now-offers-papers-in-html-format/` | Search summary — HTML-reading-surface rollout, "right under the PDF link" placement | Yes |
| Semantic Scholar | `semanticscholar.org/product` + `semanticscholar.org/faq` | Search summary — TL;DR + influential-citations feature descriptions | Partial (not template-mapped directly; informs P9) |
| Stripe | Moesif/Medium/Apidog teardown posts on `docs.stripe.com` 3-column layout | Search-aggregated | **No** — three-column API-reference layout has no analogous surface in arXMCP (no reference-doc page); parked |
| Observable | `observablehq.com/documentation/notebooks/` + arXiv paper on InterLink | Search summary — reactive cell model, side-by-side text/code layout | **No** — arXMCP has no executable-cell surface; the InterLink side-by-side idea doesn't map to a fixed-form operator console |

## 4. Themes

Every dense-info tool surveyed (Linear, Vercel, GitHub Primer/Actions) converges on **visual
hierarchy as the primary lever**, not new components: de-emphasize secondary chrome, group by
status, reveal rare actions on demand — none of it requires a new dependency. The
scholarly-adjacent sources (NotebookLM, arXiv, Semantic Scholar) converge on **treating the
"why" alongside the "what"** — an annotated relevance blurb next to a candidate, a persistent
identity strip alongside bare reading content — which maps unusually well onto arXMCP because
arXMCP already collects the raw material (topic/description fields, parse status, freshness
timestamps) but doesn't yet surface the *reasoning*, only the *result*. The operator-console
sources (Raycast, Zed, GitHub Actions/Primer state-label) converge on **status as something you
interrogate, not just glance at** — click-to-expand, hover-reveal, and history-over-snapshot are
all variations of "the badge is an entry point, not the whole answer," which is exactly the shape
arXMCP's footer badge and ingest-status poll are missing today.

## 5. Cross-reference to arXMCP

- **`frontend/templates/notebook_detail.html:181–219` and `:221–249`** (Add-by-URL / Upload
  cards) — wrap in `<details>` per **P1**.
- **`frontend/templates/index.html:79–121`** (`table.notebooks`) — add grouped `kind`/status
  columns per **P2**; add the `kind` chip itself per **P4**.
- **`server/frontend/static/app.css:64`** (`.card .empty`) and its four call sites
  (`index.html:86`, `notebook_detail.html:177,296,303`) — Blankslate icon+action per **P3**.
- **`server/frontend/static/app.css:150–168`** (`.status-badge` family) — extend with a `kind`
  modifier per **P4**; reuse verbatim (no new colors) for the history strip in **P7**.
- **`frontend/templates/notebook_detail.html:147–179`**, `#discover-results` at line 176 —
  annotated-recommendation rows per **P5**.
- **`frontend/templates/notebook_detail.html:288–297`** (`#ingest-status`) — status icon +
  `--mono` log rendering per **P6**; history strip above it per **P7**.
- **`frontend/templates/base.html`** (no `<script>` beyond lines 17–45) — add a `keydown`
  listener + native `<dialog>` command palette per **P8**.
- **`GET /ui/notebooks/{slug}/papers/{paper_id}/preview`** route (no template;
  `arxmcp-design-system.md` §3) — inject sticky breadcrumb strip reusing `.breadcrumb`
  (`app.css:50–51`) per **P9**.
- **`frontend/templates/notebook_detail.html:322–357`** (`table.papers` rows) and
  **`index.html:88–117`** (`table.notebooks` rows) — hover/focus-reveal trailing actions per
  **P10** (proposes `MOT-52`, NOT written to the shared canon this run — see P10's note).
- **`frontend/templates/base.html:88–91`** (`#status-badge`) — click-to-expand remediation
  disclosure per **P11**, reusing `.status-badge__remediation` (currently unstyled, per
  `visual-manifest.md` §3).

## 6. Out of scope / parking lot

- **Stripe's 3-column API-reference layout** — no analogous "prose + runnable code" reference
  surface exists in arXMCP; parked as a non-fit rather than a candidate.
- **Observable's reactive-cell notebook model** — arXMCP's `/ui/` has no executable-cell surface
  and inventing one would be a scope explosion into a different product; parked.
- **Any multi-user / account pattern** — none of the sources' auth, team-switcher, workspace-
  picker, or sharing/collaboration affordances apply; arXMCP is single-operator, loopback-only,
  with no session/account model (`arxmcp-design-system.md` §9 "no S-1/S-1m surface"). Explicitly
  excluded per the dispatch brief.
- **Semantic Scholar's citation-graph visualization** — genuinely interesting for a *future*
  `cite_neighbors` UI surface (the MCP tool exists server-side per CLAUDE.md §6, but has no `/ui/`
  presentation today) — out of scope for THIS uplift because no template currently renders
  citation data; flagging for a future brief rather than proposing speculative UI for a route
  that doesn't exist.
- **Any build-chain-requiring library** (Framer Motion, Radix, shadcn, cmdk, Sonner, Vaul, etc.
  from the source-registry §2 component-library list) — CLAUDE.md §4.7 / `arxmcp-design-system.md`
  §9 hard-block; every candidate in §2 above was deliberately re-derived to its zero-dependency
  vanilla-JS/native-HTML equivalent instead of citing the library that inspired it.
- **GitHub Actions' full log-viewer UX** (collapsible step groups, timestamp gutters,
  search-within-log) — the visualization-graph doc fetched didn't surface these details and
  arXMCP's ingest subprocess output is comparatively small; the minimal icon+`--mono` version
  (P6) is the right-sized borrow, not the full log viewer.

---

**Sources reviewed:** 18 platform touches (11 full fetches, 7 search-aggregated). **Candidates
surfaced:** 11 (P1–P11), one new motion-vocabulary token proposed (`MOT-52`, not committed to the
shared canon — see P10).
