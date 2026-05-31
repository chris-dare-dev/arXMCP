# Research Brief — ui-attractive-polish-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T00:00:00Z

---

## In-codebase context

### Hard constraints from CLAUDE.md and design constitution

CLAUDE.md §4.7 (load-bearing, verbatim):

> "No SPA / no Node build chain. Server-rendered Jinja2 only."
> "`assert` is BANNED for invariants"
> "Pure-ASGI middleware required. `BaseHTTPMiddleware` is project-banned"

`06-mcp-server-design.md` §"Browser UI surface" (verbatim):

> "**Hard constraint: no SPA, no Node/npm build chain.** htmx is vendored
> under `frontend/static/`; templates live under `frontend/templates/`."

> "**Jinja2 autoescape** — the environment is constructed EXPLICITLY with
> `autoescape=select_autoescape(enabled_extensions=("html","htm","xml"),
> default_for_string=True)`. Zero `| safe` filters in any template (load-bearing
> — it is the stored-XSS guard for operator-authored fields like `display_name`)."

> "**CSP** — `CONTENT_SECURITY_POLICY_UI` on `/ui/*` pages…"

The current `CONTENT_SECURITY_POLICY_UI` (from `server/middleware.py:170-177`) is:
```
b"default-src 'self'; "
b"script-src 'self' 'unsafe-inline'; "
b"style-src 'self' 'unsafe-inline'; "
b"img-src 'self' data:; "
b"connect-src 'self'; "
b"frame-ancestors 'none'"
```

`img-src 'self' data:` covers `frontend/static/favicon.svg` served at
`/ui/static/favicon.svg` — a `'self'` same-origin path. **No CSP change is
required for UPL-25.** The `<link rel="icon">` is a browser-fetched resource,
not an img element, but browsers use `img-src` (or the `default-src` fallback)
for favicon fetches in most implementations; `'self'` covers `/ui/static/*`.

### Post-m1 `app.css` state (190 lines)

The file is at `frontend/static/app.css`. Key lines for m2:

- Line 87: `button:hover, .button:hover { filter: brightness(1.08); }` — this
  is the UPL-9 target. **The exact rule is `filter: brightness(1.08)` on line 87.**
- Lines 163-172: `:focus-visible` rules (m1, DO NOT TOUCH)
- Lines 174-190: `prefers-reduced-motion` block (m1, DO NOT TOUCH)
- The `skip-link` block is lines 128-153 (m1, DO NOT TOUCH)

There is currently no `font-variant-numeric`, no `.table-wrap`, no `color-mix()`
in `app.css`. All three are new additions for m2.

The `--accent: #1e5b8a` token is the CSS variable from `:root`. There is no
`--accent-hover` token. UPL-9 establishes the `color-mix()` derivation directly
at the hover rule, which is correct — the design system has no separate hover
token today.

### `base.html` footer (m2 touch zone)

Lines 64-88 of `base.html`. The footer currently reads:
```
Loopback only · same-origin only ·
Destructive notebook wipe lives in <code>tools/notebook_purge.py</code> ·
<a href="/healthz">/healthz</a> · <a href="/readyz">/readyz</a> ·
<span id="status-badge" …>
```

There are **4 visible `·` characters** in the footer text (lines 66-68):
1. `Loopback only · same-origin only`
2. `same-origin only ·` (before `Destructive…`)
3. `<code>tools/notebook_purge.py</code> ·` (before `/healthz`)
4. `<a href="/readyz">/readyz</a> ·` (before the status-badge)

The roadmap AC says "5 footer separators" but inspection of the template shows 4
distinct `·` characters between textual segments. The implementer must count
carefully. The milestone brief says "~57-67" — those line numbers are the
pre-m1 template; the post-m1 `base.html` has slightly different lines. Count
from the actual file. **Do NOT wrap interpuncts inside Jinja2 block comments
or conditionals — they must remain static HTML.**

### `index.html` table (m2 touch zone)

The `<table class="notebooks">` is at approximately line 37 of `index.html`
(inside the `{% if not notebooks %}` else branch — only rendered when notebooks
exist). The `<div class="table-wrap">` wrapper must surround the entire `<table>`
element, inside the `{% else %}` block, not around the outer `<section>`.

### `notebook_detail.html` table (m2 touch zone)

The `<table class="papers">` is at approximately line 193 of
`notebook_detail.html`. It is inside a `<section class="card">` and always
rendered (even if papers is empty). The wrapper goes around `<table class="papers">`.
Note: `<tbody id="papers-tbody" aria-live="polite">` is the m1 aria-live target
— the wrapper must not disturb this attribute.

### m1 touch points — DO NOT re-touch

From the m1 implementation summary:

- `app.css:127-153` — `.skip-link` and `.skip-link:focus-visible` rules (UPL-4)
- `app.css:156-172` — `:focus-visible` rules (UPL-2)
- `app.css:174-190` — `@media (prefers-reduced-motion: reduce)` block (UPL-1)
- `base.html:48-61` — skip-link element + `<main id="main" tabindex="-1">` (UPL-4)
- `base.html:74-86` — `aria-live="polite" aria-atomic="true"` on `#status-badge` (UPL-3)
- `notebook_detail.html:15` — `aria-live="polite"` on `#display-name-block` (UPL-3)
- `notebook_detail.html:161` — `aria-live="polite"` on `#ingest-status` (UPL-3)
- `notebook_detail.html:203` — `aria-live="polite"` on `#papers-tbody` (UPL-3)

**m2 MUST NOT remove, modify, or re-order any of these m1 additions.**

### `tests/test_vendored_assets_integrity.py` — favicon.svg scope

This test ONLY pins `htmx.min.js` via `EXPECTED_HTMX_SHA256` and the
`TestVendoredHtmxIntegrity` class. It does not enumerate `frontend/static/`
automatically. A hand-authored `favicon.svg` does NOT trigger this test.

The roadmap AC says: "If updated, `tests/test_vendored_assets_integrity.py`
continues to pass." Since the test only pins `htmx.min.js` and does NOT
auto-scan the directory, adding `favicon.svg` requires NO change to this test
and does not break it. `VENDORED.md` also does NOT need updating — that
manifest covers third-party vendored assets, not project-authored files
(confirmed by the `### app.css` section which says "Project-authored, not
vendored. No hash recorded.").

### `test_status_endpoint.py` — UPL-10 safety

The status endpoint test asserts on badge CSS class names (`status-badge--ok`,
`status-badge--warn`, etc.) and on `id="status-badge"` and `hx-get` attributes.
It does NOT assert on CSS properties of the badge. Adding
`font-variant-numeric: tabular-nums` to `.status-badge` in `app.css` is a
CSS-only change; the test renders HTML fragments and checks string content,
not computed CSS. **UPL-10 does not break `test_status_endpoint.py`.**

### `test_ui_a11y_baselines.py` — m2 safety

This test reads `app.css`, `base.html`, and `notebook_detail.html` as strings
and asserts specific substrings. Adding new CSS rules and wrapping tables
in `<div class="table-wrap">` does NOT disturb any of the 23 existing assertions:

- No test checks the absence of `tabular-nums` or `color-mix()`.
- No test checks the exact table element structure (no wrapper-breaks-test risk).
- The `aria-live` assertions look for attribute strings in bounded regions of
  the template — the `#papers-tbody` assertion is `idx = NOTEBOOK_DETAIL_HTML.index('id="papers-tbody"')` followed by `assert 'aria-live="polite"' in attrs`. Adding a `<div class="table-wrap">` BEFORE the `<table>` does not affect the `<tbody>` attribute substring check.

### `SecFetchSiteMiddleware` — favicon 403 root cause

The `GET /favicon.ico` 403 is triggered because the browser requests
`/favicon.ico` (NOT under `/ui/`). `SecFetchSiteMiddleware` is configured with
`exempt_prefixes=("/ui",)` — paths NOT under `/ui/` fall into the
`Sec-Fetch-Site: none`-only allowed path. A browser fetch for `/favicon.ico`
from a page at `http://127.0.0.1:7733/ui/` carries `Sec-Fetch-Site: same-origin`
(the browser fetches the favicon as a side-effect of loading the page, treated
as a same-origin subresource fetch). This hits the non-exempt path and 403s.

The UPL-25 fix — `<link rel="icon" href="/ui/static/favicon.svg">` — redirects
the browser's favicon fetch to `/ui/static/favicon.svg` (under `/ui/`, therefore
exempt). The `StaticFiles` mount at `/ui/static/` is already covered by the
`/ui` carve-out per `server/main.py:750`: "Mount inside the /ui subtree so the
SecFetchSite carve-out covers it without a separate exemption." This is the
correct fix — no SecFetchSite or CSP change required.

---

## Prior decisions and lessons

### Recent git log

```
40f3552 chore(notes): finalize ui-attractive-polish-m1 state -> complete
dc30b93 rect(server,tests,notes): close F1, F2 from ui-attractive-polish-m1 critique
c5adff3 feat(server,frontend): foundational a11y baselines (ui-attractive-polish-m1)
924d5ad chore(plans,notes): land ui-attractive-polish planning artifacts
```

m1 shipped at `c5adff3` with a rectifier pass at `dc30b93`. The m1 critique
produced F1 (missing `aria-atomic` on ingest-status fragments) and F2 (budget
doc-drift). Both were closed.

### Agent-memory pattern: outerHTML-swap-breaks-aria-live

From MEMORY.md: "htmx `hx-swap='outerHTML'` REPLACES the element — the new
element from the server must carry `aria-live` in its markup or the live region
silently stops announcing after the first swap." This was the load-bearing m1
research finding. **m2 does not add any new outerHTML swap targets or server
fragments, so this pattern does not apply to m2's scope.** The UPL-23 aria-hidden
addition is to static `base.html` — there is no server-fragment involvement.

### Three-commit-per-milestone pattern (CLAUDE.md §4.3)

m2 will produce:
1. `feat(frontend): visible polish layer (ui-attractive-polish-m2)`
2. `rect(frontend): close <N> findings from ui-attractive-polish-m2 critique`
3. `chore(notes): finalize ui-attractive-polish-m2 state -> complete`

### Tool-schema re-pinning — NOT required

This milestone is pure frontend (CSS, HTML templates, new SVG file). No changes
to `server/tools.py::ALL_TOOLS`, no MCP tool schema changes. `EXPECTED_TOOL_SCHEMA_SHA256`
is unchanged.

### `KMP_DUPLICATE_LIB_OK=TRUE` — NOT at risk

`tests/conftest.py` is not touched by this milestone. The macOS segfault guard
remains in place.

---

## External sources

### MDN `font-variant-numeric: tabular-nums`

Baseline: Widely Available (all major browsers since 2015+). The `tnum` OpenType
feature is supported by `-apple-system, system-ui, BlinkMacSystemFont, "Segoe UI"` —
all fonts in the `body` font stack. Rendering is the same for digits 0-9 on
system-ui fonts on macOS (SF Pro), Windows (Segoe UI), and Linux (Noto Sans / DejaVu).
CSS selectors for m2: `time, .status-badge, dl.meta dd, td code`.

### MDN `color-mix(in oklab, ...)`

Baseline 2025-11-09 (Newly Available — Safari 18.2+, Chrome 111+, Firefox 113+).
On macOS 15 (Safari 18+) this is supported. The `in oklab` color space is more
perceptually uniform than `in srgb`; it produces a hover shade that looks
visually consistent regardless of hue. Verified against MDN Baseline status.

The formula `color-mix(in oklab, var(--accent) 88%, white)` mixes 88% of
`--accent` (#1e5b8a, a blue) with 12% white in oklab space. For WCAG AA:
`--accent` (#1e5b8a) on white `--card-bg` (#fff) passes AA (contrast ~5.0:1).
The hover state blends toward white, REDUCING contrast slightly from the resting
state; the hover is a transient state and WCAG 1.4.3 does not require hover
states to meet the threshold independently (only resting/focus states). The
existing `filter: brightness(1.08)` also lightens the button, so this is
a direct equivalent. A secondary `border-color: color-mix(in oklab, var(--accent)
80%, var(--fg))` per the AC suggestion adds a subtle border emphasis.

### MDN `overflow-x: auto`

Baseline: Widely Available. No compatibility concern. Applying `.table-wrap
{ overflow-x: auto }` enables horizontal scrolling of the table only when
content overflows. `min-height` is not needed — the container naturally takes
the table height; no jump occurs on horizontal-only overflow because
`overflow-y` defaults to `visible` (then computed as `auto` when `overflow-x`
is set, per CSS spec). On macOS/iOS, scrollbars only appear when content
overflows, so there is no visual jump in the non-overflow case.

### MDN `aria-hidden="true"` on decorative characters

ARIA spec (ARIA 1.2 §6.6.1) — `aria-hidden="true"` removes the element and its
subtree from the accessibility tree. Wrapping `·` in
`<span aria-hidden="true">·</span>` means VoiceOver and other ATs skip the
interpunct entirely. This is the correct pattern for purely decorative separators.

### SVG favicon (`<link rel="icon" type="image/svg+xml">`)

SVG favicons are supported in all modern browsers (Chrome 80+, Firefox 41+,
Safari 12+, Edge 80+). Using `type="image/svg+xml"` is the correct MIME type
declaration. The browser requests the favicon from the `href` attribute URL —
`/ui/static/favicon.svg` — which is served by FastAPI's `StaticFiles` at the
`/ui/static/` mount (already in place). The SVG at `/ui/static/favicon.svg` is
a `'self'` same-origin resource covered by `img-src 'self'` in the CSP. **No
CSP change is required.**

Note: SVGs used as favicons cannot reference CSS variables (`var(--accent)`)
because browser tab rendering of favicons does not inherit the page's CSS.
The fill color must be a hardcoded hex in the SVG: `fill="#1e5b8a"` (matching
`--accent`).

---

## Recommendation

**Implement m2 exactly as specified in the roadmap AC.** No architectural
uncertainty exists. Concrete choices the implementer should lock:

1. **UPL-9 color-mix formula:** use `background: color-mix(in oklab, var(--accent) 88%, white)`. Optionally add `border-color: color-mix(in oklab, var(--accent) 80%, var(--fg))` on the same rule for visual depth. Remove `filter: brightness(1.08)` entirely.

2. **UPL-10 selector:** `time, .status-badge, dl.meta dd, td code { font-variant-numeric: tabular-nums; }` as one CSS rule. The `dl.meta dd` targets the Created/Last-indexed values; `td code` targets paper IDs in tables; `time` targets all `<time>` elements; `.status-badge` targets the footer operability badge. This single rule covers all jitter-prone numeric surfaces.

3. **UPL-19 v0 wrapper:** add `<div class="table-wrap">` + `</div>` around `<table class="notebooks">` in `index.html` and around `<table class="papers">` in `notebook_detail.html`. CSS: `.table-wrap { overflow-x: auto; }`. Do NOT add `body { max-width: min(95vw, 1400px) }` (descoped to v1).

4. **UPL-23 interpuncts:** there are **4** `·` characters in the current `base.html` footer (lines 66-68 post-m1). Each gets wrapped as `<span aria-hidden="true">·</span>`. Count carefully from the actual file — the brief says 5 but the template shows 4 visible separators.

5. **UPL-25 favicon SVG:** create `frontend/static/favicon.svg` with a simple 32×32 SVG using `fill="#1e5b8a"` (the `--accent` hex). A `<rect width="32" height="32" rx="4" fill="#1e5b8a"/>` or a minimal 2-letter "arX" monogram both work. Target ≤300 bytes. Add the `<link rel="icon" href="/ui/static/favicon.svg" type="image/svg+xml">` to `base.html` `<head>` (after the `<link rel="stylesheet">`). **Do NOT use `var(--accent)` in the SVG** — favicons render in browser tab context where CSS custom properties are not inherited.

6. **Regression test:** add a new `tests/test_ui_m2_polish.py` (or extend `test_ui_a11y_baselines.py`) covering:
   - `font-variant-numeric: tabular-nums` appears in `app.css`
   - `color-mix(in oklab` appears in `app.css` (replacing `filter: brightness`)
   - `.table-wrap {` appears in `app.css`
   - `overflow-x: auto` appears in `app.css`
   - Both templates contain `class="table-wrap"`
   - `aria-hidden="true"` appears on `·` in `base.html`
   - `favicon.svg` exists in `frontend/static/`
   - `<link rel="icon"` with `favicon.svg` appears in `base.html`

---

## Open questions

1. **Interpunct count (UPL-23):** the roadmap AC says "5 footer separators" but
   the current `base.html` (post-m1) contains 4 literal `·` characters at lines
   66-68. The brief's "~57-67" line range references the pre-m1 template. The
   implementer MUST count from the actual file, not the brief. If the count is 4,
   wrap 4. The test should assert the exact count found in the actual template.
   **This is not blocking — just count from the file.**

2. **`color-mix()` browser support gate:** Baseline 2025-11-09 (Newly Available).
   This is 6 months behind Widely Available. On the loopback-only, single-operator
   surface where Chris controls the browser (macOS Safari 18+ / Chrome latest),
   this is fine. The implementation should NOT add a `filter: brightness()` fallback
   — that would reintroduce the pattern being replaced and the operator controls
   their browser. **Not blocking — proceed without a fallback.**

No open questions that block implementation. All choices above are fully grounded.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| `git push` | `origin/main` | Land the feat + rect + chore commit triple per CLAUDE.md §4.3. Per-event authorization (CLAUDE.md §4.4) — Chris must authorize at the Phase-4 gate. |

None beyond the standard single push. No GitHub issue creation, no infra
mutation, no third-party API calls.
