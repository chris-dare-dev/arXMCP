# arXMCP design-system inventory (read this BEFORE proposing changes)

**Purpose:** anchor every proposed upgrade to what arXMCP's `/ui/` operator
console *actually* has today. Without this, scouts will propose Framer Motion
+ shadcn + Tailwind — all of which violate the project's no-Node/no-build-chain
hard constraint.

Loaded by **every scout at Phase 1 start** and by the **synthesizer at Phase 2
start**. Cite specific entries here when surfacing a proposal.

This file is curated by hand from:
- `.claude/notes/06-mcp-server-design.md` §"Browser UI surface" (the canonical
  description of the shipped UI, kept current per the notebook-surface-expansion-m3
  constitution refresh).
- `frontend/templates/{base,index,notebook_detail}.html` (Jinja2 source).
- `frontend/static/app.css` (the SINGLE CSS file; **370 lines** after `ui-attractive-polish-m1..m5`).
- `frontend/static/VENDORED.md` (htmx provenance).

When those change, update here. Drift is expected after milestone deliveries —
flag in your brief if you find divergence.

---

## §9 — House thesis (this overlay's fulfilment of the canon's §9 contract)

`frontend-design-language.md` §9 is product-neutral and declares no thesis — each repo
declares its own here. This is arXMCP's. The `frontend-uplift-art-direction-scout` MUST read
this section BEFORE proposing a thesis or directions (a run without it re-creates the generic
AI dashboard the pipeline exists to prevent). The challenger's Axis 11 enforces it.

> **Ground-truthed 2026-07-10.** §4, §6 and §7 were re-verified against `frontend/static/app.css`
> (370 lines after `ui-attractive-polish-m1..m5`) and the three Jinja2 templates. The reduced-motion
> gate, `:focus-visible` rings, skip-link, dark-mode token block, htmx loading spinner,
> `tabular-nums`, badge-flash / row-fade and View Transitions all **ship today** — §7 lists only
> what is actually still open. Verify against the live file at Phase 1 and flag divergence.

### Visual thesis (one sentence — invariants, not a silhouette)

**arXMCP's `/ui/` is a quiet local instrument panel for a research-corpus daemon: every
notebook's parse state, its freshness, and the server's own operability read as metered,
sourced facts an operator can trust and act on without a second glance.**

Invariants this protects (a run may satisfy them through ANY §8 seed — this is deliberately
NOT a page recipe, per BAN-15):

- **Operational honesty** — the m1 parse-status badge and the m4 operability badge
  (`READY / WARN / DEGRADED / DOWN / ops-warn`) are the trust surface. Semantic color is
  *live state*, never decoration (BAN-11). A reading the operator can't trust is worse than none.
- **Provenance & freshness** — corpus version, the freshness `<time>`, per-paper ids are
  metered facts (`tabular-nums`); the console must reflect the LIVE daemon (the 10s
  `/ui/status-badge` poll), not a stale render.
- **Calm at repeat use** — one operator, loopback, a dense workflow page
  (`notebook_detail.html`). Stillness and scannability beat spectacle. Motion earns its place
  only by naming an orientation / causality / feedback / continuity job (motion-vocabulary §0) —
  there is no quota, and here that job is served by CSS transitions + htmx swap semantics, never
  a JS animation engine.
- **Sovereign minimalism** — 3 pages + 1 fragment, zero build chain, zero runtime egress
  (CLAUDE.md §4.7 / overlay §9 locks). The identity is a deliberately small, self-hosted
  instrument — recognizable by typographic discipline and honest state, not by chrome.

Swap-test: substitute a generic notebook manager or admin dashboard and the sentence collapses —
it is anchored to *parse-state / freshness / daemon-operability as metered readings over a
loopback corpus daemon*, which a generic dashboard does not have. It passes.

### Named anti-references (each mapped to its §5 BAN token)

| arXMCP's `/ui/` must never become… | BAN-N | Why it would betray the thesis |
|---|---|---|
| The "generic AI dashboard" — navy shell + neon accents + a "Welcome back" KPI-stat-card grid | BAN-1, BAN-2, BAN-13 | arXMCP is a single-operator instrument, not a persona-greeting SaaS home; a KPI-card opener manufactures metrics the daemon does not have |
| Badge soup — colored status pills scattered decoratively across every row and card | BAN-7, BAN-11 | the parse-status + operability badges are LOAD-BEARING state; multiplying pills dilutes the one signal the operator relies on |
| Marketing spectacle on the dense detail page — parallax / scroll-zoom / WebGL on `notebook_detail.html` | BAN-12 (= AP-1/2/3) | operators want stillness on a dense workflow surface; already an explicit pipeline anti-pattern |
| Same-silhouette borrow — another repo's cockpit shell (a trading dashboard, a platform admin console, or a prior uplift's look) reused as arXMCP's identity | BAN-15 | arXMCP's identity is its own minimal instrument; a borrowed shell is not a thesis |
| Untouched default stack look — one face everywhere, stock radius/border/shadow, no scale contrast | BAN-4 | with only 8 tokens and one CSS file, the discipline IS the design; a default assembly reads as no design |

Concrete "never again" baseline: the §1 canon anti-reference (a fully-templated "command center"
comp scoring 11–12 on §10) is arXMCP's standing negative reference. arXMCP has no SOC-cosplay comp
of its own — its risk is *drift toward* the template as candidates accrete, not an existing bad screen.

### Surface map (every route → class → house direction)

arXMCP has **no S-1 or S-1m surface**: it is loopback-only with no public / login / marketing /
onboarding surface (the Origin + Host + SecFetchSite triple defense replaces browser auth —
overlay §8). **Every surface is S-2 tool.** This is *why* experiential motion (`EXP-*`,
AP-1/2/3/5) is blocked wholesale here and the `frontend-uplift-experiential-scout` is not
dispatched by default — there is no threshold for it to live on.

| Surface | Route / file | Class | House direction |
|---|---|---|---|
| Landing — notebook list + create form | `GET /ui/` · `index.html` | **S-2** | D-A precision instrument: the notebooks table is the work surface; the empty state carries cause + one action (never a hero) |
| Notebook detail — the dense workflow page | `GET /ui/notebooks/{slug}` · `notebook_detail.html` | **S-2** | D-A workbench with a D-B posture lede: parse-status + freshness answer "is this notebook usable?" first; ingest / upload / rename / delete are subordinate; stillness |
| ar5iv paper preview (tight CSP) | `GET /ui/notebooks/{slug}/papers/{paper_id}/preview` | **S-2** | document-view: chrome recedes, the ar5iv HTML is the surface; the tight preview CSP is a constraint to honor, not a bug |
| Operability badge fragment (10s poll) | `GET /ui/status-badge` · `ui_status_badge` | **S-2** | the operability instrument — semantic color = live state ONLY; stable width across state changes (m4 UPL-22) |

House default direction: **D-A (Precision Instrument)** across all four surfaces, with a
**D-B (Editorial Cockpit)** posture-lede permissible on the detail page's top block.
**D-C (Cinematic Threshold) is N/A** — no threshold surface exists. A run may propose a
genuinely new S-2 direction, but it must satisfy the invariants above and clear the
challenger's Axis 11 (BAN-1..15 + §10 rubric).

---

## 1. Stack snapshot (verify against the source files at Phase 1 read)

| Layer | What | Why it constrains proposals |
|---|---|---|
| Server | FastAPI + uvicorn on `127.0.0.1:7733` (loopback-only; non-loopback rejected at config parse) | The same uvicorn process serves `/mcp` AND `/ui/`. No separate frontend process exists. |
| Templates | Jinja2 (autoescape ON, explicitly constructed in `server/routes/ui.py:85-92`) | Server-rendered HTML. NO SPA. NO client-side routing. NO React. |
| Interactivity | htmx 2.0.10 (vendored at `frontend/static/htmx.min.js`, 0BSD) | Loaded once in `base.html`. Mutations target HTML fragments returned by `/ui/api/*`. A small JSON-shim in `base.html:18-44` converts htmx form bodies to JSON for POST/PUT/PATCH. |
| Style | A SINGLE ~370-line `frontend/static/app.css` | NO Tailwind, NO PostCSS, NO `@theme` block. CSS custom properties + plain class selectors only. |
| Static delivery | FastAPI `StaticFiles` mounted at `/ui/static/` | Vendored htmx + the CSS file. NO npm, NO node_modules. |
| Build chain | **NONE** | **Hard constraint, CLAUDE.md §1, §4.7, re-pinned in notebook-surface-expansion-m3 + m5.** "no SPA, no Node/npm build chain." Recommending any npm-installable React/Vite/Next/Tailwind/Storybook library is an automatic BLOCKER in Phase 3. |
| Tests for the UI | `tests/test_ui_html_pages.py` + the m1/m2/m3 detail-page suites + `test_constitution_ui_claims.py` (the doc-grep guard) | Asserts the rendered HTML contains expected substrings; no Playwright in CI. |

## 2. Templates (the inventory the visual scout walks)

| File | Renders | Routes that use it |
|---|---|---|
| `frontend/templates/base.html` | Layout shell: `<head>` (CSS link + vendored htmx + 27-line JSON-shim) + header + `{% block content %}` + footer with the live operability badge | extended by both pages |
| `frontend/templates/index.html` | Landing: create-notebook form + table of notebooks (slug / display name / created / Open + Remove buttons) | `GET /ui/` |
| `frontend/templates/notebook_detail.html` | Per-notebook detail: `<dl class="meta">` with parse-status badge + freshness line + rename form + Delete button + URL-paste form + drag-drop PDF/ar5iv upload card + ingest trigger + live `#ingest-status` poll fragment + papers table with Preview/Remove buttons | `GET /ui/notebooks/{slug}` |

There are **NO** per-component files (no React/Vue/Svelte directory), no Storybook
stories, no design-tokens module, no design-system package.

## 3. The "page set" (the visual scout's default routes — and the totality)

Unlike a typical SPA scope, arXMCP's UI is small. The default visual-scout
page set is **3 routes + 1 polling fragment**:

| Route | Method | Template | Notes |
|---|---|---|---|
| `/ui/` | GET | `index.html` | Landing — notebook list + create form. Empty state matters (`{% if not notebooks %}<p class="empty">…`). |
| `/ui/notebooks/{slug}` | GET | `notebook_detail.html` | The dense page. Needs a seeded notebook + papers to be visually meaningful. |
| `/ui/notebooks/{slug}/papers/{paper_id}/preview` | GET | (no template; direct-serves ar5iv HTML under a tight CSP) | The ar5iv preview tab. Tight `CONTENT_SECURITY_POLICY_PREVIEW` + `<meta http-equiv="refresh">` strip. Visual scout MUST treat its CSP as constraint, not bug. |
| `/ui/status-badge` | GET | (HTML fragment; built in `ui_status_badge`) | Polled every 10s by `base.html:65-67`. The visual scout sees this as the footer badge. |

If `--pages` is supplied via the CLI, override the default. A seeded notebook
+ paper is REQUIRED for `/ui/notebooks/{slug}/papers/{paper_id}/preview` —
the visual scout's preflight should seed via `POST /ui/api/notebooks` +
`POST /ui/api/notebooks/{slug}/papers` if the target deployment is empty.

## 4. CSS variables (the actual "design tokens")

**Verified against `frontend/static/app.css` on 2026-07-10.** Line numbers drift — re-read at the
Phase 1 read.

Declared at `:root` (`app.css:4–16`), with a dark override at `app.css:242`. **Eight custom
properties. That is the entire token system** — the file carries 15 `--x:` declarations in total
(the 8 light ones plus the 7 the dark block re-declares) and no tokens live anywhere else. A
proposal that introduces a new token adds it here; it does not invent a parallel system.

| Variable | Light | Dark (`:242`) | Purpose |
|---|---|---|---|
| `--fg` | `#1a1a1a` | `#e8e8e8` | Foreground text |
| `--bg` | `#f8f8f8` | `#0d1117` | Page background |
| `--card-bg` | `#fff` | `#161b22` | Card / panel background |
| `--border` | `#d8d8d8` | `#6e7681` | Subtle borders |
| `--accent` | `#1e5b8a` | `#58a6ff` | Links, primary accent (the brand colour) |
| `--danger` | `#a3271a` | `#f85149` | Destructive buttons + the m4 `status-badge--down` |
| `--error-bg` | `#fff4f2` | `#2a1a18` | Error-message background |
| `--mono` | system mono stack | *(not re-declared — theme-independent)* | Numbers, code spans, slugs |

**Dark mode SHIPPED** (`ui-attractive-polish-m3`). `@media (prefers-color-scheme: dark)` at
`app.css:242` re-declares seven of the eight. There is no toggle and no persisted preference — the
page follows the OS, which is the right posture for a loopback operator console.

**`color-scheme: light dark` (`app.css:10`) is load-bearing and is NOT a token.** Without it the
browser's UA-styled internals — form-control internals, scrollbars, the default focus ring, the
caret, native `<select>` dropdowns — stay light-mode even after the page tokens flip
(`ui-attractive-polish-m3-rect` F3). Don't delete it while "tidying" `:root`.

**Contrast, computed rather than asserted** (WCAG 2.1 relative luminance). Every pair clears AA in
both themes; the tightest is dark `--danger` on `--card-bg`:

| Pair | on `--bg` | on `--card-bg` |
|---|---|---|
| light `--fg` | 16.39:1 | 17.40:1 |
| light `--accent` | 6.77:1 | 7.20:1 |
| light `--danger` | 6.91:1 | 7.34:1 |
| dark `--fg` | 15.45:1 | 14.12:1 |
| dark `--accent` | 7.49:1 | 6.85:1 |
| dark `--danger` | 5.65:1 | **5.16:1** |

Re-run these before any colour change — a token tweak that drops a pair below 4.5:1 is a Phase-3
BLOCKER.

## 5. CSS classes (the actual "component primitives")

All defined in the single `frontend/static/app.css`. Cite by class name
when proposing changes.

### Layout / structural
- `.card` — bordered + padded panel (the dominant visual unit)
- `.breadcrumb` — back-link strip
- `header h1` + `header .subtitle` — the page title block

### Forms
- `<form>` (the bare element; CSS targets descendants directly)
- `pre.error` / `<pre id="…-error" class="error">` — error display for htmx response errors

### Tables
- `table.notebooks` — the index list
- `table.papers` — the per-notebook paper list

### Buttons
- `<button class="danger">` — destructive (delete buttons)
- `<a class="button">` — primary CTAs styled as buttons

### Live state (m1 + m4)
- `.status-badge` + `.status-badge--ok` / `.status-badge--warn` / `.status-badge--down` —
  used for both the notebook parse-status badge (m1) AND the footer operability
  badge (m4). Three modal states; consistent visual language.
- `.hint` — secondary explanatory text
- `.empty` — centered, italic, muted empty-state message (`#666`, AA-clean in light;
  `#9ba1a8` dark override). Styles BOTH the notebooks `<td colspan="4">` row and the papers `<p>`
  (`.card .empty`, `app.css:64`)
- `.display-name` — the notebook-detail name `<p>` (m2; also the htmx swap target `#display-name-block`)
- `.rename-form` (m2)
- `.notebook-actions` (m2 — the Delete-button row)

## 6. Accessibility posture (current state)

- **Jinja2 autoescape is ON** and load-bearing (the XSS guard for operator-
  authored fields like `display_name`). Zero `| safe` filters anywhere.
  Hand-built HTML fragments use `html.escape()` per value (the `_paper_row_html`,
  `ui_status_badge`, `_display_name_fragment` pattern).
- **CSP** — `CONTENT_SECURITY_POLICY_UI` on `/ui/*` pages + tighter
  `CONTENT_SECURITY_POLICY_PREVIEW` on the ar5iv preview. Both with
  `frame-ancestors 'none'`. The UI CSP allows `script-src 'self' 'unsafe-inline'`
  (htmx + the inline JSON-shim).
- **`prefers-reduced-motion`** — **honored.** A universal reduce gate at `app.css:223`, and every
  animation lives inside `@media (prefers-reduced-motion: no-preference)` (`:317`, `:344`).
  Caveat: the *JS* opt-in for view transitions (`base.html:38–44`) is evaluated once at
  `DOMContentLoaded` and does not listen for a `change` event — see §7.
- **Focus rings** — **explicit.** A `:focus-visible` baseline ring (`ui-attractive-polish-m1`,
  UPL-2), `.skip-link:focus-visible` at `app.css:184`, and a widened 3px ring on a busy destructive
  button (`button.danger.htmx-request:focus-visible`).
- **Skip-link** — **present.** `base.html:52` targets `<main id="main" tabindex="-1">`
  (`base.html:61`); `tabindex="-1"` makes `<main>` programmatically focusable without adding it to
  the Tab order.
- **Live regions** — 24 `aria-live="polite"` regions across the three templates, so htmx fragment
  swaps announce.
- **Colour contrast** — every `--fg` / `--accent` / `--danger` pair clears WCAG AA on both `--bg`
  and `--card-bg`, in **both** themes. Measured table in §4. The tightest pair is dark `--danger`
  on `--card-bg` at 5.16:1 — re-run the numbers before any colour change.

The `/ui/api/*` surface has NOT been security-audited end-to-end (E13 scope-out;
tracked at `chris-dare-dev/arXMCP#9`). Any uplift candidate that adds JS or
changes CSP must be flagged for that audit.

## 7. What's UNDERDEVELOPED (candidate surface)

Re-derived 2026-07-10 against `app.css` + the three templates. **Every proposal here must land in
pure CSS / vanilla JS / vendored htmx-extension form** (no Node, no npm, no React).

### Already SHIPPED — do NOT re-propose as net-new gaps

The `ui-attractive-polish-m1..m5` milestones closed most of the original list. Verify against the
live file before contradicting this table.

| Was listed as missing | Where it now lives |
|---|---|
| `prefers-reduced-motion` not honored | Universal reduce gate at `app.css:223`; every animation additionally sits inside `@media (prefers-reduced-motion: no-preference)` (`:317`, `:344`). (`m1`, UPL-1) |
| No `:focus-visible` styling | Baseline outline ring (`m1`, UPL-2); `.skip-link:focus-visible` at `:184`; `button.danger.htmx-request:focus-visible` widens to 3px |
| No skip-link | `base.html:52` → `<main id="main" tabindex="-1">` at `base.html:61` (`m1`, UPL-4) |
| No dark mode / no OS theme respect | `@media (prefers-color-scheme: dark)` at `app.css:242`, plus `color-scheme: light dark` at `:10` so UA-styled controls follow (`m3`, + `m3-rect` F3) |
| No skeleton / loading affordance | htmx's auto-applied `.htmx-request` drives a `::after` spinner (`@keyframes spin`, `app.css:332`) on submit buttons |
| No live-region announcements | 24 `aria-live="polite"` regions across the three templates |
| View Transitions API unused | `base.html:38–44` sets `htmx.config.globalViewTransitions = true`; `::view-transition-old(root)` / `-new(root)` are duration-capped to 200 ms at `app.css:352` |
| htmx CSS-only transitions unused | `.status-badge.htmx-settling` → `badge-flash`; `.htmx-swapping` → `row-fade-out` for in-place row removal (`m5`, UPL-12) |
| No `tabular-nums` | `font-variant-numeric: tabular-nums` at `app.css:134` (`m2`, UPL-10) |

### Genuinely open

**a11y / correctness**
- **The View-Transitions gate is evaluated once.** `base.html:38–44` reads
  `matchMedia('(prefers-reduced-motion: reduce)')` inside `DOMContentLoaded` and never listens for
  `change`. An operator who enables reduced-motion mid-session keeps view transitions until reload.
  The CSS gates react correctly; only the JS opt-in is sticky.

**workflow**
- **No keyboard-shortcut affordances** — zero `keydown` / `accesskey` handlers anywhere. `/` or
  Cmd-K to focus the URL-paste input would mirror the Linear / Raycast operator-console pattern.
  Must be vanilla JS under the existing CSP (`script-src 'self' 'unsafe-inline'`).
- **The index does not differentiate notebook `kind`.** `server/routes/notebooks.py` carries a
  `kind` field (`arxiv` vs `textbook`) and `notebook_detail.html` references it 3×, but
  `index.html` references it **0×** — the list shows only slug + display name. A `.status-badge`-style
  chip would reuse the existing three-state visual language rather than inventing one.

**polish**
- **No cross-document view transition.** `globalViewTransitions` covers htmx swaps; a full
  navigation (clicking *Open* on a notebook row) has none. `@view-transition { navigation: auto; }`
  is the one-line, framework-free way — and it must be reduced-motion gated like everything else.
- **The ar5iv preview route has no shared chrome.** It direct-serves ar5iv HTML under a tight CSP
  and extends no template, so it inherits no header, no skip-link, and no badge. Treat its CSP as a
  constraint, not a bug (§3), but the *absence of a way back* is a real UX gap.

## 8. Patterns ALREADY CONSIDERED AND REJECTED (don't re-propose)

| Pattern | Why rejected |
|---|---|
| SPA migration (Next.js / React / Vue / Svelte) | **CLAUDE.md §4.7 hard constraint.** Repeatedly re-pinned in m3/m5. Not negotiable. |
| Adding Tailwind / PostCSS / a CSS-in-JS lib | Same constraint — no build chain. |
| Adding any npm-installable JS library (Framer Motion, shadcn, Radix, etc.) | Same. The only allowed import is a vendored single-file drop, like the htmx file. |
| `| safe` filter on user-authored fields | Stored-XSS vector. Autoescape is load-bearing (m1/m2 critique footnotes). |
| Reverting Jinja2 templates to bare Python string interpolation | The `wrap_retrieved_text` + autoescape discipline is the project-wide pattern. |
| Browser-side authentication (cookies / session tokens) | Loopback-only design; `SecFetchSiteMiddleware` + `OriginValidationMiddleware` + `HostValidationMiddleware` is the triple defense. |
| Adding `unsafe-eval` to the UI CSP | The current `unsafe-inline` is already a defense compromise; widening further is regression. |
| File uploads bypassing the existing PDF preflight | The `_pdf_*` preflight + Pydantic body bounds are load-bearing security. |

## 9. Architectural locks (CLAUDE.md §4.7 — non-negotiable in any uplift candidate)

These are the project's "Q-locks equivalent." Cite by §4.7 when a candidate
violates one:

1. **No SPA / no Node build chain.** Server-rendered Jinja2 only.
2. **Pure-ASGI middleware required.** `BaseHTTPMiddleware` is project-banned
   (E06_S01 F1: it silently no-ops response interception for SSE paths).
3. **No `anthropic` SDK at runtime in `server/`.** The server is a tool provider.
4. **No-fork policy.** Use ideas from other UIs/repos, not code.
5. **`server/` source NEVER references `claude-opus`.** Model selection lives in
   the calling orchestrator.
6. **`assert` is BANNED for invariants** (Python `-O` strips them; use
   `if … raise RuntimeError(…)`).

## 10. How to anchor a proposal to this file

Every candidate in the synthesis catalog must cite ONE of:

- A specific arXMCP template file (`base.html` / `index.html` / `notebook_detail.html`)
  with line numbers — the closest existing visual surface.
- A CSS variable from §4 to be applied or extended (no inventing parallel tokens).
- A CSS class from §5 to be applied or extended.
- An accessibility constraint from §6 that the proposal will improve OR honor.
- A candidate pattern from §7 (the "underdeveloped" list).
- An architectural lock from §9 that the proposal explicitly respects.

If none of those apply, the proposal is probably not arXMCP-shaped — push back.
And: if a proposal would require ANY npm-installable dependency, it's an
automatic BLOCKER in Phase 3 (the §9.1 lock).
