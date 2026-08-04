# Visual manifest — 2026q3-ui-uplift (captured by the orchestrator)

**Why this file exists:** the `mcp__Claude_Browser__computer{screenshot}` action failed in
this session (`the Browser pane is not displayed, so the page is not compositing frames`).
The orchestrator therefore captured **DOM + computed-style + layout-geometry** evidence
instead of PNGs, live from `http://127.0.0.1:7733`. Treat every number here as tier
**`✓ measured`** (live DOM/CGeometry), NOT `~ inferred`. There are **no PNGs** under
`screenshots/` — score visual questions from geometry + the full CSS source, and say so.

Server: `.venv/Scripts/python.exe -m server.main` via `.claude/launch.json` (`arxmcp-ui`),
`ARXMCP_BOOTSTRAP_MODE=1`, `ARXMCP_LOG_FORMAT=text`. Rendered in a Chromium-family engine,
**`prefers-color-scheme: dark` was ACTIVE** — every color below is the dark-mode branch.

Seeded fixture: notebook `uplift-demo` ("Uplift demo - UI audit fixture") with **6 papers**
(`1908.04187`, `1909.11251`, `2007.03325`, `2103.03144`, `2211.09545`, `2402.14758`), created
by the orchestrator because every pre-existing notebook returned `[]` papers. Delete after the
run: `DELETE /ui/api/notebooks/uplift-demo`.

---

## 0. The whole stylesheet is 371 lines / 52 CSSOM rules

`server/frontend/static/app.css` is the ONLY stylesheet (plus one inline `<style>`).
**52 total CSSOM rules.** Read it end-to-end — it is short enough that every visual
decision in the product is visible in one file.

Assets loaded: `app.css`, `htmx.min.js` (2.0.10, vendored, 0BSD), `json-enc.js`,
one 250-char inline script (`globalViewTransitions` opt-in, gated on reduced-motion).
`favicon.svg`. **No web fonts. No CDN. No build chain.** (CLAUDE.md §4.7.)

## 1. Token set — 8 CSS variables, no scale of any kind

```
--fg #1a1a1a   --bg #f8f8f8   --card-bg #fff   --border #d8d8d8
--accent #1e5b8a   --danger #a3271a   --error-bg #fff4f2
--mono ui-monospace, "SF Mono", Menlo, Consolas, monospace
```
Dark-mode branch (`@media (prefers-color-scheme: dark)`) re-declares 7 of the 8 with
GitHub-Primer values: `--fg #e8e8e8`, `--bg #0d1117`, `--card-bg #161b22`,
`--border #6e7681`, `--accent #58a6ff`, `--danger #f85149`, `--error-bg #2a1a18`.

**What is NOT tokenized** (hardcoded literals scattered through the file):
`#555`, `#666`, `#777`, `#444`, `#f0f0f0`, `#b3b9c0`, `#9ba1a8`, `#c9d1d9`, plus the 8
`.status-badge--*` pill colors (`#e6f4ea`/`#1a7f37`, `#fdf3e2`/`#8a5a00`, `#eef2f7`/`#475569`,
`#0d2818`/`#3fb950`, `#3d2a07`/`#d29922`, `#1c2230`/`#8b949e`, `#3d1216`/`#f85149`).
There is **no spacing scale, no type scale, no radius scale, no elevation scale, no
`--font-sans` token** — the body font stack is inlined in the `body` rule.

## 2. Typography — one system stack, ~6 ad-hoc sizes, zero letter-spacing authored

Body stack: `-apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif`.
Mono stack (`--mono`) is used for `input[type=text|url]`, `.status-badge`, `table code`, `pre.error`.

| Element | size | weight | line-height | letter-spacing | color |
|---|---|---|---|---|---|
| `h1` | 32px | 700 | 48px | **normal** | `--fg` |
| `header p.subtitle` | 14.4px (`0.9rem`) | 400 | 21.6px | normal | `#b3b9c0` |
| `main h2` (card title) | 17.6px (`1.1rem`) | 700 | 26.4px | normal | `--fg` |
| body / `td` | 16px / 14.4px | 400 | 24px / 21.6px | normal | `--fg` |
| `th` | 14.4px | 600 | 21.6px | normal | `--fg` |
| `button` | 14px (`0.875rem`) | 400 | normal | normal | `#0d1117` on `--accent` |
| `input[type=text]` | 15.2px (`0.95rem`) | 400 | normal | normal | `--fg`, **`--mono`** |
| `.status-badge` | 12px (`0.75rem`) | 600 | 18px | normal | per-modifier |

Ratio between `h1` (32) and card `h2` (17.6) is **1.82×** — then `h2` → body (16) is
**1.10×**. There is effectively **one typographic step** in the whole product; the h2/body
contrast is carried by weight (700 vs 400), not size. `font-variant-numeric: tabular-nums`
IS applied to `time, .status-badge, dl.meta dd, td code` (good, keep it).

## 3. Layout geometry — measured at 1440×900

`body { padding: 1rem; max-width: clamp(640px, 92vw, 1400px); margin-inline: auto }`
→ at 1440 the content column is **1325px wide**, inner content 1293px. Everything is
**one full-bleed column**. No grid, no sidebar, no two-column split anywhere.

### `/ui/` (landing) — `docHeight 987px`
| Region | y | h | notes |
|---|---|---|---|
| `header` | 16 | 84 | h1 + subtitle, 1px bottom border |
| `.card` "Create notebook" | 124 | 366 | 4 fields stacked, all `width:100%` |
| `.card` "Existing notebooks (5)" | ~510 | ~293 (table) | 4-col table: Slug / Display name / Created / (actions) |
| `footer` | 929 | 42 | links + `.status-badge` |

Form inputs render **1251px wide** — a slug field ~12 characters long is given a
1251px input. `button[type=submit]` "Create" is **67×32px**.

### `/ui/notebooks/uplift-demo` (detail) — `docHeight 2343px`, **7 stacked `.card`s**
| # | Card `h2` | y | h | controls |
|---|---|---|---|---|
| 1 | `uplift-demo` (meta + rename + delete) | 161 | 358 | 3 |
| 2 | Topic & discovery | 535 | 310 | 3 |
| 3 | Discover papers | 861 | 194 | 1 |
| 4 | Add paper by URL | 1071 | 211 | 2 |
| 5 | Upload ar5iv HTML | 1297 | 306 | 3 |
| 6 | Ingest | 1620 | 187 | 1 |
| 7 | **Papers in this notebook (6)** | **1823** | 414 | 0 |

**Above the 900px fold: cards 1–3 (all controls). The papers table — the actual corpus
content — starts at y=1823, dead last, after six input forms.** All 7 cards are the same
width (1293px), same `border-radius: 6px`, same 1px border, same `padding: 1rem 1.25rem`,
same `margin-bottom: 1rem`. **`box-shadow` is `none` on every element in the product.**
Papers-table row height 49px; the table does not overflow at desktop.

### Mobile (viewport 390 CSS px; engine reported `innerWidth` 439)
`docHeight 2976px`. **No horizontal page overflow** (`.table-wrap` works — papers table
scrolls internally, `scrollWidth 386 > clientWidth 316`). `body { padding: 16px }` is
unchanged from desktop. `h1` stays **32px** — no responsive type ramp.

**Tap targets under 44px** (WCAG 2.5.8 AAA / Apple HIG 44pt), measured:
every `button` is **32px tall** (Rename 77×32, Delete notebook 131×32, Save topic 91×32,
Discover 80×32, Add 53×32, Upload 72×32, Ingest now 95×32, **6× Remove 77×32**);
`select` is **19px tall**; `input[type=text|url]` 33px; `a "← All notebooks"` 20px;
footer `/healthz` 48×17, `/readyz` 44×17.

### `/ui/status-badge` (htmx fragment, polls `every 10s`)
```html
<span id="status-badge" class="status-badge status-badge--ops-warn" aria-live="polite"
      aria-atomic="true" hx-get="/ui/status-badge" hx-trigger="every 10s"
      hx-swap="outerHTML" title="WARN | awaiting first ingest">WARN | awaiting first ingest<small
      class="status-badge__remediation">status non-pass — see docs/install.md troubleshooting</small></span>
```
Rendered 491×22px, `min-width: 14ch`, mono 12px. Note `.status-badge__remediation` has
**no CSS rule of its own** anywhere in `app.css` — it inherits `<small>` UA styling and
renders inline, so the badge is a 491px-wide run-on line, not a pill + caption.

## 4. htmx surface — 9 hx-* elements on the detail page, 0 `hx-indicator`

| tag | verb | target | swap | trigger | confirm |
|---|---|---|---|---|---|
| form | hx-patch | `#display-name-block` | outerHTML | — | — |
| button | hx-delete | — | — | — | `window.confirm` text |
| form | hx-patch | `#topic-block` | outerHTML | — | — |
| form | hx-post | `#discover-results` | outerHTML | — | — |
| form | hx-post | `#papers-tbody` | beforeend | — | — |
| form | hx-post | `#papers-tbody` | beforeend | — | — |
| form | hx-post | `#ingest-status` | outerHTML | — | — |
| div | hx-get | `#ingest-status` | outerHTML | **every 2s** | — |
| span | hx-get | (self) | outerHTML | **every 10s** | — |

**`hx-indicator` is set on ZERO elements.** In-flight feedback comes only from the
CSS `.htmx-request { opacity: .6; cursor: wait }` rule + a `::after` spinner.
Destructive confirm is a **native `hx-confirm` `window.confirm()` dialog**, not an
in-page affordance.

**12 `aria-live="polite"` regions on one page** (7 of them empty `<pre class="error">`).
Every one of them announces on swap — an over-announcing screen-reader surface, and
the `2s` ingest poll + `10s` badge poll both swap into live regions.

## 5. Motion inventory — 4 keyframe/transition effects, all correctly gated

1. `@keyframes spin` — `.htmx-request::after` 0.6s linear infinite (gated `no-preference`)
2. `@keyframes badge-flash` — `.status-badge.htmx-settling` 400ms ease-out (gated)
3. `@keyframes row-fade-out` — `tr.htmx-swapping` 200ms ease-out forwards (gated)
4. `::view-transition-old(root)/-new(root)` — `animation-duration: 200ms` (gated)

Plus one non-keyframe: `button:hover { background: color-mix(in oklab, var(--accent) 88%, white) }`.
**There is not a single `transition` property declared in the file** — hover is an instant
snap. The universal `prefers-reduced-motion: reduce` clamp IS present and correct.

## 6. Accessibility facilities already SHIPPED (do not re-propose as net-new)

- `.skip-link` → `<main id="main" tabindex="-1">` (WCAG 2.4.1)
- `:focus-visible` 2px `--accent` outline ring on every interactive element,
  `--danger` at `outline-offset:3px` for `button.danger`, `:focus:not(:focus-visible)` reset
- `prefers-reduced-motion: reduce` universal clamp
- `prefers-color-scheme: dark` full token remap + input/badge/th dark overrides
- `color-scheme: light dark` declared (UA controls auto-darken)
- `.table-wrap { overflow-x: auto }` mobile table containment
- `font-variant-numeric: tabular-nums` on swapping numerics
- `aria-live="polite"` + `aria-atomic="true"` on the status badge
- `<meta name="viewport" content="width=device-width, initial-scale=1">`

## 7. Console / network

No console errors or warnings observed on `/ui/` or `/ui/notebooks/<slug>`.
No 4xx/5xx on page load. API note (for anyone scripting the console): the JSON bodies are
`{"slug","display_name"}` for `POST /ui/api/notebooks` and **`{"arxiv_url": ...}`** (not
`url`) for `POST /ui/api/notebooks/{slug}/papers`.
