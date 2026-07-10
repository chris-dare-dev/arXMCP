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
- `frontend/static/app.css` (the SINGLE CSS file; 126 lines).
- `frontend/static/VENDORED.md` (htmx provenance).

When those change, update here. Drift is expected after milestone deliveries —
flag in your brief if you find divergence.

---

## §9 — House thesis (this overlay's fulfilment of the canon's §9 contract)

`frontend-design-language.md` §9 is product-neutral and declares no thesis — each repo
declares its own here. This is arXMCP's. The `frontend-uplift-art-direction-scout` MUST read
this section BEFORE proposing a thesis or directions (a run without it re-creates the generic
AI dashboard the pipeline exists to prevent). The challenger's Axis 11 enforces it.

> **Drift note (2026-07):** §4's "126 lines" and §7's "underdeveloped" gap list PRE-DATE the
> `ui-attractive-polish-m1..m5` milestones. `frontend/static/app.css` is now ~370 lines and
> already ships: the `prefers-reduced-motion` universal gate, `:focus-visible` rings, the
> skip-link, `@media (prefers-color-scheme: dark)` token re-declaration, htmx `.htmx-request`
> loading states + spinner, `tabular-nums`, the badge-flash + row-fade + View-Transitions
> polish. **Do not re-propose those as net-new gaps** — verify against the live file at Phase 1.
> A human should refresh §4/§7 of this overlay; the fold that added this §9 deliberately did not
> rewrite the inventory.

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
| Style | A SINGLE 126-line `frontend/static/app.css` | NO Tailwind, NO PostCSS, NO `@theme` block. CSS custom properties + plain class selectors only. |
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

Defined at `:root` in `frontend/static/app.css:4-13`. **Eight variables. That is
the entire token system.** Proposals that introduce a new token must add it
here, not invent a parallel system.

| Variable | Default | Purpose |
|---|---|---|
| `--fg` | `#1a1a1a` | Foreground text |
| `--bg` | `#f8f8f8` | Page background |
| `--card-bg` | `#fff` | Card / panel background |
| `--border` | `#d8d8d8` | Subtle borders |
| `--accent` | `#1e5b8a` (blue) | Links, primary accent (the brand color) |
| `--danger` | `#a3271a` (red) | Destructive buttons + the m4 `status-badge--down` |
| `--error-bg` | `#fff4f2` (pale red) | Error message background |
| `--mono` | system mono stack | Numbers, code spans, slugs |

There is currently **no dark-mode theme** and **no `prefers-color-scheme`
handling**. Theming is an open candidate surface (see §7 below).

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
- `.empty` — empty-state message
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
- **`prefers-reduced-motion`** — **NOT currently honored.** The CSS has zero
  `@media (prefers-reduced-motion: reduce)` blocks today. Adding it is a
  legitimate candidate (low cost, high accessibility win).
- **Focus rings** — browser defaults only; no explicit `:focus-visible` styling
  in `app.css`. Another candidate.
- **Skip-link** — none. Probably less critical for a 3-page surface, but flag.
- **Color contrast** — `--accent` on `--bg` and `--danger` on `--bg` both clear
  WCAG AA; spot-check before any color change.

The `/ui/api/*` surface has NOT been security-audited end-to-end (E13 scope-out;
tracked at `chris-dare-dev/arXMCP#9`). Any uplift candidate that adds JS or
changes CSP must be flagged for that audit.

## 7. What's UNDERDEVELOPED (candidate surface)

The discovery scouts will likely converge on a subset of these — surface them
prominently if your scan finds confirming evidence. **Every proposal here must
land in pure CSS / vanilla JS / vendored htmx-extension form** (no Node, no npm,
no React).

- **`prefers-reduced-motion` is not honored** — add the universal reduced-motion
  block + `@media` guards on any transitions.
- **No focus-visible styling** — browser default outlines only; consistent
  `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }`
  would be a high-leverage a11y win.
- **No skip-link** — landing + detail page lack a skip-to-main affordance.
- **No dark-mode** — `prefers-color-scheme: dark` is unaddressed. Adding a
  second token block at `:root` (under `@media (prefers-color-scheme: dark)`)
  is the in-stack way.
- **No empty-state illustration / micro-interaction** — `.empty` is a one-line
  paragraph; could be richer.
- **No skeleton / loading affordance** — htmx requests just sit there; adding
  `htmx-request` class-based styling for a spinner or skeleton would help.
- **No live-region announcements** — htmx fragment swaps (e.g. the rename
  success swap) don't announce to screen readers. `aria-live` regions could
  bridge.
- **View Transitions API** — supported in modern browsers (`document.startViewTransition`)
  and works WITHOUT any framework. Could land smooth swaps on the rename and
  ingest-status transitions.
- **htmx CSS-only transitions** — `htmx-swapping` / `htmx-settling` hooks exist
  and arXMCP doesn't use them. Low-cost polish.
- **No `tabular-nums` on metric/timestamp values** — the freshness `<time>`
  and paper-count would benefit.
- **No keyboard-shortcut affordances** — Cmd-K / `/` to focus the URL-paste
  input would mirror operator-console patterns from Linear / Raycast.
- **No theme respect for the host OS** — the page is light-mode-fixed; an
  operator on a dark-mode system gets a flash.
- **No visual differentiation between `arxiv`-kind and `textbook`-kind notebooks
  in the list** — the index just shows slug + display name.

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
