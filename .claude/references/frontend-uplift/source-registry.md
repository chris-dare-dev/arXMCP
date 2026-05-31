# Frontend-uplift source registry

**Purpose:** the curated list of sources each scout reaches for first. Update
here when a new platform / technique / pattern proves valuable across runs.
Loaded by individual scouts at Phase 1 start.

Keep entries one-line-per-source so a scout can grep this file when narrowing
focus.

**arXMCP framing:** the operator console is a local-first, loopback-only,
single-user Jinja2+htmx surface with **no Node/npm build chain** (CLAUDE.md
§4.7). Sources here are calibrated to that reality: inspiration biased toward
research/scholarly + dev-tool UIs (NOT marketing/finance/SaaS), libraries
biased toward pure-CSS APIs + htmx extensions + vendor-able single-file drops
(NOT npm-installable React libs — those are automatic Phase-3 BLOCKERs).

---

## 1. Visual / motion / interaction inspiration (2026 SOTA)

Studied by the **inspiration-scout** (and skimmed by the **visual-scout**).

### 1a — Scholarly / research / publication platforms (arXMCP's actual domain)

| Platform | URL | Why it matters | Notable patterns to study |
|---|---|---|---|
| arXiv | https://arxiv.org/ | The corpus arXMCP indexes; the canonical mathematical-paper-list UI | Compact paper-list rows, abstract-truncation, ID + version display, classification badges |
| ar5iv | https://ar5iv.labs.arxiv.org/ | HTML5 + MathML renderings of arXiv (arXMCP's preview source) | MathML rendering, navigation, footnote/reference handling, dense-citation patterns |
| zbMATH Open | https://zbmath.org/ | Math abstracting + reviewing service | MSC classification surfacing, author/journal facets, dense-tabular search results |
| Mathematical Reviews / MathSciNet | https://mathscinet.ams.org/ | Reference for mathematical-document discovery UX | Citation graph view, classification taxonomy, search-refinement chips |
| Distill.pub (archive) | https://distill.pub/ | Best-in-class scholarly/explainable visual essays | Interactive figures, two-column body + margin asides, dense scholarly typography with breathing room |
| Quanta Magazine | https://www.quantamagazine.org/ | Scholarly-adjacent typography + figure layout | Reading-progress affordances, section navigation, header-image tone |
| Observable (notebooks) | https://observablehq.com/ | Live-computational-document UI | Cell-based document model, inline plots, run-state indicators |
| Google NotebookLM | https://notebooklm.google.com/ | Source-grounded LLM chat tool — direct competitor space | Source-list sidebar, citation chips, "ground in sources" patterns |
| Quarto / RStudio pubs | https://quarto.org/ | Scientific-document rendering | Cross-references, footnote treatment, code-output choreography |

### 1b — Dev-tool / operator-console / power-user UX

| Platform | URL | Why it matters | Notable patterns to study |
|---|---|---|---|
| Linear | https://linear.app/ | Best-in-class B2B SaaS visual language | Inertial scroll, command-palette ergonomics, smart-list density, micro-animation tempo |
| Stripe Docs | https://docs.stripe.com/ | Reference for technical documentation + sidebar nav | Sticky-header-with-scroll-progress, language-tab persistence, inline copy-to-clipboard |
| Vercel Dashboard | https://vercel.com/dashboard | Deploy/observability dashboard SOTA | Skeleton choreography, status pills, tab-driven detail panels, real-time log streaming |
| GitHub (issues / PRs / Actions) | https://github.com/ | Reference for dense list+detail dev-tool UI | Timeline/activity feeds, label chips, list-row hover states, command palette |
| Raycast | https://www.raycast.com/ | Best-in-class command palette + keyboard-driven flow | Cmd-K patterns, settings density, single-window dev-tool surface |
| Sublime Text / Zed | https://zed.dev/ | Local-first single-user dev tools — closest mode-of-operation analogue to arXMCP | Status-bar density, panel composition, no-auth-no-multitenancy patterns |
| Figma (left nav + canvas chrome) | https://www.figma.com/ | Operator console with dense affordances | Left-nav discipline, status-bar information density, real-time presence indicators |
| Datadog (dashboards) | https://www.datadoghq.com/ | Operator observability + status display | Live-value tick patterns, status-color discipline, dense-metric layout |

**Mining heuristic:** WebFetch each platform's **public marketing / docs / changelog**
pages. Avoid auth-walled UI screenshots (hard to verify). Cite public assets.

---

## 2. Vendor-able frontend techniques (animation, motion, interaction)

Studied by the **library-scout**. arXMCP's no-build-chain lock means everything
here must be either **(a) a pure-CSS / native-Web API**, **(b) an htmx extension
that drops in as a single vendored file**, or **(c) a vanilla-JS micro-lib that
ships as a single static file** consumable from `<script src="…">`.

**Off-limits (automatic Phase-3 BLOCKER):** any library requiring npm /
package.json / a bundler / a build step — i.e. anything from the React /
Tailwind / shadcn / Framer / Recharts / Zustand ecosystem.

### 2a — Pure-CSS / native Web APIs (arXMCP's primary candidate surface)

| Technique | URL | Browser baseline | Why study it |
|---|---|---|---|
| View Transitions API (same-document) | https://developer.mozilla.org/en-US/docs/Web/API/View_Transitions_API | Chrome / Safari (widely available); FF dev | Smooth transitions between page states without a SPA |
| `animation-timeline: scroll()` | https://developer.mozilla.org/en-US/docs/Web/CSS/animation-timeline | Chrome / Safari 26 (widely available); FF behind flag | Bundle-free scroll-driven animation |
| `:has()` selector | https://developer.mozilla.org/en-US/docs/Web/CSS/:has | Widely available | Conditional styling without JS class flipping |
| Container queries (`@container`) | https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_containment/Container_queries | Widely available | Responsive components without window-driven media queries |
| Anchor positioning (`anchor()`) | https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_anchor_positioning | Chrome / Edge; FF / Safari incoming | Native popover positioning without floating-ui |
| `popover` attribute | https://developer.mozilla.org/en-US/docs/Web/API/Popover_API | Widely available | Modal / popover affordances without modal-library deps |
| `prefers-reduced-motion` | https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion | Widely available | The a11y motion gate; required on every new animation |
| `prefers-color-scheme` | https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-color-scheme | Widely available | Native dark-mode detection |
| `color-mix()` | https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/color-mix | Widely available | Token-based palette derivation without preprocessor |
| `:focus-visible` | https://developer.mozilla.org/en-US/docs/Web/CSS/:focus-visible | Widely available | Keyboard-only focus rings without polyfills |
| `tabular-nums` (font-variant-numeric) | https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric | Widely available | Aligned numbers in timestamp / count cells |
| `aria-live` regions | https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Attributes/aria-live | Widely available | Announce htmx swap completions to screen readers |

### 2b — htmx extensions (single-file vendor drops)

The htmx extensions catalogue at https://htmx.org/extensions/ ships each
extension as a single JS file that can be vendored alongside `htmx.min.js`.
License: typically 0BSD or BSD-2-Clause (verify per file).

| Extension | URL | What it adds |
|---|---|---|
| class-tools | https://htmx.org/extensions/class-tools/ | CSS class transitions (add/remove/swap on htmx events) |
| loading-states | https://htmx.org/extensions/loading-states/ | Request-state styling (htmx-request class management) |
| morphdom | https://htmx.org/extensions/morphdom-swap/ | Smoother DOM swaps by diffing rather than replacing |
| response-targets | https://htmx.org/extensions/response-targets/ | Per-response-code swap targets (e.g. errors to a different element) |
| head-support | https://htmx.org/extensions/head-support/ | Coordinate `<head>` updates across swaps |

### 2c — Vanilla-JS micro-libs that ship as single files (no bundler)

Most modern frontend libs assume a bundler. Vendor-able single-file options
are narrower but exist. The library-scout should evaluate based on actual
file-on-disk weight, not bundlephobia (bundlephobia measures package-tree
weight; arXMCP only uses the static file).

| Lib | URL | License | Why study |
|---|---|---|---|
| picocss | https://picocss.com/ | MIT | Minimal CSS framework, single file — alternative styling base |
| sortable.js | https://github.com/SortableJS/Sortable | MIT | Drag-reorder for lists/tables without a framework |
| Alpine.js | https://alpinejs.dev/ | MIT | Tiny declarative-attribute reactivity — overlaps with htmx but covers client-state |

(All of the above must be evaluated against arXMCP's existing htmx-2.0.10
baseline; redundancy with htmx is the most common rejection reason.)

---

## 3. arXMCP codebase orientation (read first by every scout)

| Path | What it is |
|---|---|
| `/CLAUDE.md` (root) | Top-level project conventions; §4.7 architectural locks (no-build-chain, pure-ASGI, no-anthropic-SDK, no-fork, no-`assert`) |
| `.claude/notes/06-mcp-server-design.md` § "Browser UI surface" | The canonical description of the shipped UI (notebook-surface-expansion-m3 keeps this current) |
| `frontend/templates/base.html` | Layout shell + footer + htmx JSON-shim |
| `frontend/templates/index.html` | Landing — notebook list + create form |
| `frontend/templates/notebook_detail.html` | Detail — paper list + URL paste + upload + ingest + rename + delete |
| `frontend/static/app.css` | THE single CSS file (~126 lines, 8 CSS variables) |
| `frontend/static/VENDORED.md` | Vendored-asset provenance (currently just htmx 2.0.10, 0BSD) |
| `server/routes/ui.py` | Route handlers + the explicit Jinja2 autoescape construction |
| `.claude/references/frontend-uplift/arxmcp-design-system.md` | Token + class + page-set inventory (the curated digest of the above) |

The **current-state-critic** owns end-to-end traversal of these. Other scouts
skim them, then focus externally.

---

## 4. Default page set (the visual scout's canonical walk)

When `pages_to_walk` is empty, the visual scout walks **3 routes + 1 fragment**
— arXMCP's UI is small by design:

1. `/ui/` — landing (notebook list + create form)
2. `/ui/notebooks/<seeded-slug>` — detail (paper list, URL paste, upload, ingest, rename, delete)
3. `/ui/notebooks/<seeded-slug>/papers/<paper_id>/preview` — ar5iv preview (under tight CSP)
4. `/ui/status-badge` — htmx fragment (the footer-badge poll)

For each, the visual scout captures:
- A **viewport screenshot** at 1440×900
- A **mobile screenshot** at 390×844 (iPhone 12 viewport — single-user loopback may de-prioritize mobile; flag explicitly in the brief either way)
- A **DOM snapshot** of the primary content section
- A **console-log dump** (errors / warnings)
- A **network-request summary** (high-latency or failed requests)

User override via `--pages "/foo,/bar"` replaces this list verbatim.

If the target deployment is empty, the visual scout MUST seed a notebook + paper
via `POST /ui/api/notebooks` + `POST /ui/api/notebooks/<slug>/papers` before
walking routes 2 and 3.

---

## 5. Hard rules (every scout)

- **No npm-installable libraries.** Recommending React / Tailwind / shadcn /
  Framer Motion / Recharts / Zustand / TanStack etc. is an **automatic
  Phase-3 BLOCKER**. CLAUDE.md §4.7 is a hard project lock.
- **License citation** is mandatory for every vendor-able file or pure-CSS
  spec referenced.
- **Vendor weight** cited when proposing a new vendored single-file (cite the
  un-minified file size + estimated min+gz weight, not bundlephobia tree weights).
- **Browser-baseline check** is non-negotiable for native APIs — anything not
  in MDN "Baseline Widely-Available" needs an explicit fallback story.
- **Token discipline:** the entire token system is the 8 CSS variables in
  `frontend/static/app.css:4-13` (`--fg`, `--bg`, `--card-bg`, `--border`,
  `--accent`, `--danger`, `--error-bg`, `--mono`). Don't invent a parallel
  system; extend this one (or propose adding new variables here explicitly).
- **`prefers-reduced-motion` discipline:** every animation proposal MUST cite
  the `@media (prefers-reduced-motion: no-preference)` gate. arXMCP's CSS
  currently has NO such block — establishing one is itself a candidate.
- **Accessibility-first:** proposals that regress WCAG 2.1 AA contrast,
  keyboard-nav, screen-reader semantics get downgraded in priority.
- **No vendor-blog hype.** Weight a source by primary evidence (MDN, spec,
  changelog, GitHub release notes). Marketing pages alone are weak signal.
- **No code in briefs.** Scouts write briefs; implementation happens later
  via `/milestone-pipeline`.
- **The UI security audit is OPEN** (`chris-dare-dev/arXMCP#9`). Anything
  that adds JS or expands the CSP surface should be flagged as audit-widening.
