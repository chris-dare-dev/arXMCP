# Research Synthesis — `ui-attractive-polish-m2`

**Generated:** 2026-05-31T03:40:00Z
**Inputs:**
- `.claude/notes/milestones/ui-attractive-polish-m2/research-brief-1.md` (in-codebase context lens)
- `.claude/notes/milestones/ui-attractive-polish-m2/research-brief-2.md` (external sources + failure-mode lens)
- Upstream: `plans/ui-attractive-polish-roadmap.md` `### ui-attractive-polish-m2` section + `.claude/notes/frontend-uplifts/2026-05-ui-polish/artifacts/{synthesis,challenge,final-report}.md`.
- Post-m1 state: commits `c5adff3` (feat) + `dc30b93` (rect) — m1 UPL-1..4 already shipped.

---

## 1. What ships

Five visible-polish items from the 2026-05-ui-polish uplift's RICE-tier-2
candidates (UPL-9, UPL-10, UPL-19 v0, UPL-23, UPL-25). All pure CSS / template
attribute / static-asset additions; zero server code, zero MCP surface impact,
zero CSP impact, zero vendored-asset integrity-test impact.

| UPL | What | Where | Cost |
|---|---|---|---|
| **UPL-10** | `font-variant-numeric: tabular-nums` on `time, .status-badge, dl.meta dd, td code` | `frontend/static/app.css` (~3 LOC) | XS |
| **UPL-19 v0** | `<div class="table-wrap">` wrapping both tables + `.table-wrap { overflow-x: auto }` | `frontend/templates/{index,notebook_detail}.html` + `app.css` (~4 LOC) | XS |
| **UPL-9** | Replace `filter: brightness(1.08)` button-hover with `background: color-mix(in oklab, var(--accent) 88%, white)` | `frontend/static/app.css:87` (1 LOC swap) | XS |
| **UPL-23** | Wrap 5 footer `·` interpuncts in `<span aria-hidden="true">·</span>` | `frontend/templates/base.html` (5 inline spans) | XS |
| **UPL-25** | Add `frontend/static/favicon.svg` + `<link rel="icon">` in `base.html` `<head>` | new SVG file + 1 HTML line | XS |

Total: ~10 LOC of CSS, ~5 template attribute wrappers, 1 new tiny SVG.
Complexity: **S**.

---

## 2. Concrete implementation sketches

### UPL-10 — `tabular-nums`

One CSS rule, placed after the `table code` rule (`app.css:~97`):

```css
time, .status-badge, dl.meta dd, td code {
  font-variant-numeric: tabular-nums;
}
```

The `time` selector covers `<time>` in `index.html` (Created column),
`notebook_detail.html` (Created + Last-indexed + per-paper Added). The
`dl.meta dd` covers any non-`<time>` values in the metadata block. The
`.status-badge` covers the footer operability badge (which has a corpus
version digit) AND the per-notebook parse-status badge. The `td code`
covers paper IDs in the papers table.

System-ui fonts (San Francisco on macOS, Segoe UI on Windows, Noto Sans
on Linux) all ship the `tnum` OpenType feature. **No `font-feature-settings`
fallback needed** (researcher-2 confirmed — the high-level property
suffices; on a platform without `tnum`, graceful degradation to non-tabular
digits is acceptable).

### UPL-19 v0 — `.table-wrap` mobile fix

Add to `app.css`:

```css
.table-wrap { overflow-x: auto; }
```

In `frontend/templates/index.html` (around line 37): wrap `<table class="notebooks">…</table>` in `<div class="table-wrap">…</div>`.

In `frontend/templates/notebook_detail.html` (around line 193): wrap `<table class="papers">…</table>` in `<div class="table-wrap">…</div>` — but the wrapper goes OUTSIDE the `<table>` and INSIDE the `<section class="card">`, so the m1 `aria-live="polite"` on `<tbody id="papers-tbody">` stays untouched.

`overflow-x: auto` produces a scrollbar ONLY when content overflows
(researcher-2 verified vs `overflow-x: scroll`). On macOS / iOS the
scrollbar auto-hides; on Windows the gutter is constant but only visible
when needed. No vertical-scroll interaction.

**Do NOT** ship `body { max-width: min(95vw, 1400px) }` — descoped to v1
per the challenger's MINOR finding on UPL-19. The 980px ceiling stays.

### UPL-9 — `color-mix()` button hover

Replace `app.css:87`:

```css
/* before */
button:hover, .button:hover { filter: brightness(1.08); }

/* after */
button:hover, .button:hover {
  background: color-mix(in oklab, var(--accent) 88%, white);
}
```

**Use ONLY `background`** — researcher-2's correctness finding:
the base `button, .button` rule has `border: none`, so a
`border-color: …` clause has no visual effect without first adding
`border-style` / `border-width`. The simpler `background`-only swap
is the right call.

`in oklab` is the perceptually-uniform color space — MDN explicitly
recommends it over `srgb` for color mixing ("srgb produces poorer
results such as overly dark or grayish mixes"). Baseline
Widely-Available since 2023 (MDN); fully supported on Chris's browsers
(Chrome on macOS, Safari ≥18). **No `filter: brightness()` fallback**
— per researcher-1, "the operator controls their browser" and adding
the fallback would reintroduce the imprecise filter pattern.

WCAG AA contrast on `--bg: #f8f8f8`: `--accent` `#1e5b8a` passes AA at
~5:1; the 88% mix toward white reduces resting-contrast slightly but
hover states are transient and WCAG 1.4.3 only requires the
resting/focus state to meet threshold. Identical visual semantic to
the prior `filter: brightness(1.08)`.

### UPL-23 — Footer interpunct `aria-hidden`

In `frontend/templates/base.html` (lines 57–59 post-m1), the footer
contains exactly **5** `·` (U+00B7) characters (researcher-2 verified
by line-level scan):
- Line 57: `Loopback only · same-origin only ·` — 2 dots
- Line 58: `…tools/notebook_purge.py</code> ·` — 1 dot
- Line 59: `…/healthz</a> · …/readyz</a> ·` — 2 dots

Replace each bare `·` with `<span aria-hidden="true">·</span>`. Five
inline spans, no other changes. Static HTML — no server-fragment
implication, no aria-live interaction (the m1 lesson about
outerHTML-swap-aria-live does NOT apply here).

### UPL-25 — Favicon SVG

Create `frontend/static/favicon.svg` (~200 bytes; researcher-1 cited
≤300):

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect width="32" height="32" rx="6" fill="#1e5b8a"/>
  <text x="16" y="22" text-anchor="middle"
        font-family="-apple-system,system-ui,sans-serif"
        font-weight="700" font-size="16" fill="#fff">aX</text>
</svg>
```

The `#1e5b8a` color is the `--accent` token's hex value, **hardcoded
because favicons render in browser-tab context outside the page CSS**,
so `var(--accent)` would not resolve (researcher-1's load-bearing
correctness finding — both researchers converged on this). The exact
design ("aX" vs "arX" vs a plain rounded rect) is implementer's call;
keep it simple, ≤ 300 bytes.

Add to `frontend/templates/base.html` `<head>` (after the existing
`<link rel="stylesheet">` line):

```html
<link rel="icon" href="/ui/static/favicon.svg" type="image/svg+xml">
```

CSP `img-src 'self' data:` already permits this — confirmed by both
researchers reading `server/middleware.py:170-177`. No CSP change. The
`StaticFiles` mount at `/ui/static/` already serves `frontend/static/`.

`SecFetchSiteMiddleware` exempts `Sec-Fetch-Site: none` (browser-
initiated, no document context — which is how the favicon fetch fires),
so the `/favicon.ico → 403` noise disappears as the browser now fetches
`/ui/static/favicon.svg` instead. Researcher-2 verified the middleware
exemption logic.

**Do NOT** add the favicon to `frontend/static/VENDORED.md` —
researcher-2 confirmed VENDORED.md is for third-party vendored assets
only. The favicon is hand-authored. The existing
`tests/test_vendored_assets_integrity.py` only pins `htmx.min.js`; it
does NOT auto-scan the directory and is unaffected by the new SVG.

---

## 3. Disagreements resolved

### D1: Interpunct count — 4 (r1) vs 5 (r2)

**Resolution: 5.** Researcher-2's line-level scan of `base.html:57-59`
counts 5 explicit `·` characters; researcher-1 counted "between
segments" and missed the trailing `·` before the status badge.
Implementer will verify by `grep -c '·' frontend/templates/base.html`
or by reading lines 57-59 directly.

### D2: UPL-9 `border-color` clause

**Resolution: drop it.** Researcher-2's technical correctness finding:
the base button rule has `border: none`, so a `border-color` on hover
has zero visual effect. Use ONLY `background: color-mix(…)`. If a
future milestone wants a hover border, that requires a base-rule
change first.

### D3: `color-mix()` Baseline date

**Resolution: doesn't matter.** Researcher-1 cites 2025-11-09 (Newly
Available) and researcher-2 cites May 2023 (Widely Available). The
practical answer: fully supported on Chris's actual browser (Chrome /
Safari on macOS). No fallback strategy needed either way. Documented
note: the library-scout brief from the uplift cited 2025-11-09 for the
Baseline-Widely-Available threshold; both dates are accurate for
different Baseline tiers.

---

## 4. Open questions remaining (none blocking)

1. **Exact SVG favicon design.** Both researchers say "implementer's
   choice." Lock in the rounded-rect-with-"aX"-text design above
   (~200 bytes); alternatives are equivalent.
2. **Line-count budget recalibration.** The roadmap AC's "`≤ 175`" is
   stale (predates m1's 190-line landing). Researcher-2 recommends
   `≤ 200` as the realistic m2 budget. Adopt; record the doc drift in
   the implementation-summary's deviations section.
3. **`favicon.svg` and the `VENDORED.md` boundary.** Both confirmed:
   hand-authored asset, not vendored → no VENDORED.md update.

No items block implementation.

---

## 5. Confirmed NOT in scope

- m1 sites (`.skip-link`, `:focus-visible`, `prefers-reduced-motion`,
  the 5 `aria-live` attributes) are untouched. Verified by both
  researchers — zero overlap.
- `body { max-width: min(95vw, 1400px) }` — descoped to a v1 per the
  challenger.
- New CSP directives — `img-src 'self' data:` already covers the SVG
  favicon.
- New token additions — UPL-9 uses `color-mix()` inline; no
  `--accent-hover` token introduced (would require updating the design-
  system reference per its "no parallel system" rule).
- Tool-schema repinning — m2 touches zero MCP code.
- `frontend/static/htmx.min.js` — unchanged; `EXPECTED_HTMX_SHA256`
  pin holds.
- m1 regression tests (`tests/test_ui_a11y_baselines.py`) — must
  continue passing. m2 adds new tests but does NOT modify any m1
  assertion.

---

## 6. Recommended implementation order

1. **UPL-10** (`tabular-nums`) — one CSS line. Isolated, no template touch.
2. **UPL-19 v0** (`.table-wrap`) — one CSS line + 2 template wrapper edits.
3. **UPL-9** (`color-mix()`) — swap one CSS line.
4. **UPL-23** (interpunct `aria-hidden`) — 5 inline spans in `base.html`.
5. **UPL-25** (favicon) — new SVG file + 1 `<link>` in `base.html` head.
6. **Regression tests** — add `tests/test_ui_m2_polish.py` (new file) OR
   extend `tests/test_ui_a11y_baselines.py` with m2 assertions:
   - `font-variant-numeric: tabular-nums` present in `app.css`
   - `color-mix(in oklab` present in `app.css`
   - `filter: brightness(1.08)` ABSENT in `app.css` (regression guard for
     the replacement)
   - `.table-wrap {` rule + `overflow-x: auto` in `app.css`
   - Both templates contain `class="table-wrap"` wrapping their tables
   - `base.html` contains 5 occurrences of `<span aria-hidden="true">·</span>`
   - `frontend/static/favicon.svg` exists + parses as XML
   - `base.html` `<head>` contains `<link rel="icon"` with `favicon.svg`
7. `make test` (via `uv run`) — confirm 23 m1 tests still pass + new m2 tests pass.

I'll add the m2 tests as a new file `tests/test_ui_m2_polish.py` rather than
extending `test_ui_a11y_baselines.py` — the m2 surface is conceptually distinct
(visible polish, not a11y baselines) and a separate file keeps the test names
auditable per-milestone.

---

## 7. External writes

| type | target | why |
|---|---|---|
| `git_push` | `origin/main` | Land the feat + rect (if any) + chore commit triple per CLAUDE.md §4.3. Per-event authorization (CLAUDE.md §4.4) at the Phase-4 external-write gate. |

No GitHub issues, no infra, no third-party API calls. Single push.

---

## 8. Orchestrator synthesis note

The two researcher briefs converged strongly on all 5 UPLs. The three
disagreements (D1 interpunct count, D2 border-color inertness, D3
`color-mix()` baseline date) all resolved on concrete grounds:
researcher-2's empirical line-level scan settles D1; researcher-2's
"base rule has border:none, so border-color is inert" settles D2;
D3 doesn't matter for the implementation.

The load-bearing correctness findings — *neither* of which appears in
the roadmap AC — are:
1. **The SVG favicon must use the hex `#1e5b8a` (not `var(--accent)`)**
   because external SVG files don't inherit page CSS at favicon render
   time. Both researchers converged on this.
2. **The `body { max-width: clamp(…) }` expansion stays descoped to v1**
   per the challenger — only the `.table-wrap` wrapper ships in m2 v0.

The implementer is ready to proceed inline (small, well-scoped, ~10 LOC
production + ~30 LOC tests).

*End of synthesis.*
