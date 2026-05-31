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
