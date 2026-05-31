# Research Brief — ui-attractive-polish-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T02:15:00Z

---

## In-codebase context

### Files touched by this milestone

- `frontend/static/app.css` (126 lines; AC budget: ≤ 165 after m1)
- `frontend/templates/base.html` (71 lines)
- `frontend/templates/notebook_detail.html` (218 lines)
- `frontend/templates/index.html` (63 lines; NOT listed in AC but `#notebook-list`
  is a swap target — see open questions)

### Codebase invariants confirmed by reading

**From `06-mcp-server-design.md` § "Browser UI surface":**
> "Zero `| safe` filters in any template (load-bearing — it is the stored-XSS guard for operator-authored fields like `display_name`)."
> "Hard constraint: no SPA, no Node/npm build chain."

**From `06-mcp-server-design.md` § "Security posture":**
> "Jinja2 autoescape — the environment is constructed EXPLICITLY with `autoescape=select_autoescape(enabled_extensions=('html','htm','xml'), default_for_string=True)`."

Neither of these is touched by this milestone (pure CSS + 5 ARIA attribute additions + 1 HTML line), but they are the reason the template work must remain attribute-only with no `| safe` introduction.

**From `CLAUDE.md §4.7`:**
> "`assert` is BANNED for invariants… `BaseHTTPMiddleware` is project-banned… No `anthropic` SDK at runtime."
None of these patterns are at risk in a pure-CSS/template-attribute milestone.

### What exists today

`app.css` currently has:
- 5 `pre.error[aria-live="polite"]` error regions (lines 28, 39, 103, 132, 154 of notebook_detail.html; line 28 of index.html)
- **Zero** `prefers-reduced-motion`, `:focus-visible`, `aria-live` on success-swap targets, or skip-link
- `button.hover { filter: brightness(1.08) }` at line 87 — the brightness-filter hover will be clamped by UPL-1's `transition-duration: 0.01ms` if any transition is attached (but this rule has no `transition` property today, so the clamp has no immediate effect; it future-proofs against one being added)

`base.html:47` — `<body>` currently has NO children before `<header>`. The skip-link insert is the FIRST child of `<body>` per the AC.

`base.html:53` — `<main>` has no `id` or `tabindex` today.

`base.html:65-67` — `<span id="status-badge">` uses `hx-swap="outerHTML"`. **This is load-bearing for the F3 failure mode below.**

`notebook_detail.html:15` — `<p class="display-name" id="display-name-block">` also uses `hx-swap="outerHTML"` (from the rename form at line 28-30). Same F3 concern.

`notebook_detail.html:161-168` — `<div id="ingest-status">` uses `hx-swap="outerHTML"`. Same F3 concern.

`notebook_detail.html:180` — `<tbody id="papers-tbody">` uses `hx-swap="beforeend"` (upload form) and is NOT itself an htmx target with outerHTML. `aria-live` on a `<tbody>` is valid; the AT will announce new rows added.

### Constraint conflicts with milestone brief

**No hard conflicts found.** The milestone brief is consistent with the design constitution. The `tests/test_ui_html_pages.py` test suite exercises the routes but does NOT assert on specific HTML attributes — adding `aria-live`, `aria-atomic`, `tabindex="-1"`, or `id="main"` to templates will not break any existing test.

The brief states `#display-name-block` is at `notebook_detail.html:15` and `#ingest-status` at `:161` and `#papers-tbody` at `:180`. Reading the actual file confirms these are accurate at the time of writing (lines 15, 161, 180 respectively). However, as other milestones land, line numbers shift. **Do not cite line numbers in CSS; cite element IDs.**

---

## Prior decisions and lessons

- `ca2c274` — most recent commit is `chore(notes)` for verification-feedback-m4. No CSS or template changes in the recent log; this milestone starts from a clean baseline.
- `be099b3` — last non-chore before that was landing startup-ux uplift briefs, confirming this is the first a11y-baseline work on the frontend.
- `state.json` for this milestone is in `research-running` phase. No prior implementation or rectification artifacts exist.

**From agent-memory (loaded):**
- notebook-surface-expansion-m1: `jinja2.Environment` explicitly constructed with autoescape. Zero `| safe` filters. Never introduce `| safe`.
- notebook-surface-expansion-m4: `SecFetchSiteMiddleware` blocks cross-path htmx XHR unless the endpoint is under `exempt_prefixes`. `/ui/status-badge` is already under `/ui/` so the 10s poll is safe with no exempt-prefix change.

**Tool-schema re-pinning:** Not required. This milestone adds no MCP tools and touches no `server/tools.py::ALL_TOOLS`. `EXPECTED_TOOL_SCHEMA_SHA256` is UNCHANGED.

**macOS segfault guard:** `tests/conftest.py::KMP_DUPLICATE_LIB_OK=TRUE` is NOT touched by this milestone.

---

## External sources

### `prefers-reduced-motion` — MDN (verified 2026-05-31)
**Baseline Widely Available** since January 2020. Chrome 74, Firefox 63, Safari 10.1.
The universal `*, *::before, *::after` block is the canonical (Andy Bell / MDN) pattern. It clamps `animation-duration`, `animation-iteration-count`, `transition-duration` to `0.01ms`. The AC also requires `animation-delay` and `transition-delay` per the challenger's MINOR finding — MDN confirms these are the exhaustive set of timing properties.

### `:focus-visible` — MDN (verified 2026-05-31)
**Baseline Widely Available** since March 2022. Chrome 86, Firefox 85, Safari 15.4.
The `@supports not selector(:focus-visible)` fallback exists but no browser in arXMCP's target (Chrome on macOS) needs it. The pattern `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }` clears WCAG AA non-text contrast (3:1) for `--accent: #1e5b8a` on `--card-bg: #fff` (dark blue on white).

**WCAG SC 2.4.7 Focus Visible (Level AA):** "Any keyboard operable user interface has a mode of operation where the keyboard focus indicator is visible." W3C Understanding doc lists "C45: Using CSS :focus-visible" as a sufficient technique.

### `aria-live` — MDN (verified 2026-05-31)
`polite` = announced at next graceful opportunity (end of sentence). `assertive` = interrupts immediately. For htmx success swaps (rename confirmation, ingest status, new paper row), `polite` is the canonical choice per WAI-ARIA Authoring Practices — never interrupt for non-critical updates.

`aria-atomic="true"` = re-read the ENTIRE live region on any change. Required on `#status-badge` because the badge is a composite string ("READY · corpus v645 · 2 notebooks") — without `aria-atomic`, AT may announce only the changed substring.

**htmx 2.0.10 behavior confirmed:** htmx does NOT automatically set `aria-busy="true"` on swap targets. The `htmx-request`, `htmx-swapping`, `htmx-settling`, `htmx-added` classes are applied to elements as CSS hooks, but ARIA live-region announcement is entirely the author's responsibility.

### `tabindex="-1"` — MDN (verified 2026-05-31)
Makes an element programmatically focusable (via `element.focus()` or following a fragment anchor href="#main") but excludes it from Tab order. Required on `<main id="main">` so the skip-link's `href="#main"` actually moves keyboard focus into the main content area. Without `tabindex="-1"`, clicking the skip-link on some browsers scrolls to the element but does NOT set keyboard focus, so Tab thereafter returns to the top.

### WCAG references
- **SC 2.4.1 Bypass Blocks (Level A):** "A mechanism is available to bypass blocks of content that are repeated on multiple web pages." The skip-link (G1 technique: adding a link at the top directing users to main content) directly satisfies this. Level A = foundational.
- **SC 2.4.7 Focus Visible (Level AA):** Satisfied by `:focus-visible`. Sufficient technique C45.
- **SC 2.3.3 Animation from Interactions (Level AAA):** `prefers-reduced-motion` satisfies this AAA criterion. However, the roadmap frames this as an "AA baseline by 2026 design systems" — accurate for practical purposes even though the spec level is AAA.

### WebAIM G1 Skip Navigation
Canonical pattern: visually hide off-screen with CSS (NOT `display:none` / `visibility:hidden` — those remove from keyboard nav), reveal on `:focus-visible`. Use `position: absolute; left: -9999px; top: auto;` default, `position: fixed; left: 1rem; top: 1rem; z-index: 9999;` on focus. The milestone AC specifies `position: absolute; left: 1rem; top: 1rem` on focus — acceptable; add `z-index` to ensure visibility above header.

### macOS VoiceOver + `aria-live="polite"` + `aria-atomic="true"`
Known behavior: VoiceOver on macOS Safari/Chrome announces `aria-live="polite"` regions reliably when content is inserted into a region that EXISTS in the DOM before the swap. For `outerHTML` swap targets (the F3 concern), the live region is REPLACED, not updated in-place. The new element carries `aria-live` in its markup but the AT's live-region tree must re-attach it. In practice: VoiceOver on macOS Chrome and Safari re-attaches within one announcement cycle and the subsequent swap IS announced. VoiceOver on iOS is less reliable; NVDA/JAWS on Windows are out of scope for this single-operator macOS installation.

---

## Failure-mode analysis

**F1 — UPL-1 universal selector clobbers an intentional future transition**
Trigger: a future implementer adds `transition: color 0.2s` to a success-feedback rule (e.g. UPL-22 flash) and the `prefers-reduced-motion` block clamps it to 0.01ms.
Symptom: the flash is imperceptible under reduced-motion (correct behavior) but the developer is surprised.
Mitigation: the universal block is the canonical approach and the correct behavior. Document in CSS comment that all motion must add `@media (prefers-reduced-motion: no-preference)` guards for any animation INTENDED to survive the clamp. The challenger confirms this is MINOR and the canonical pattern.

**F2 — VoiceOver over-announces `#status-badge` every 10s poll**
Trigger: `aria-live="polite" aria-atomic="true"` on `#status-badge` means every 10s outerHTML swap fires an announcement, even when badge content is unchanged.
Symptom: VoiceOver reads "READY · corpus v645 · 2 notebooks" every 10s — disruptive during a keyboard session.
Mitigation (recommended): make the server-side fragment writer smarter — only include `aria-live` and `aria-atomic` when the status HAS CHANGED from the prior render. The simplest v0 mitigation: accept the over-announcement; the badge swaps even when state is identical, so the announcement is always technically valid. A v1 mitigation: conditionally add/remove `aria-live` based on a state-change sentinel. **For m1, accept the over-announcement and note it as a follow-up.**

**F3 — outerHTML swap replaces the live region, breaking AT attachment**
Trigger: `hx-swap="outerHTML"` on `#display-name-block`, `#ingest-status`, `#status-badge` means the ELEMENT ITSELF is replaced, not just its content. The new element from the server must carry `aria-live` in its markup.
Symptom: if the server-rendered fragment does NOT include `aria-live="polite"` on the replacement element, the live region silently stops announcing after the first swap.
**This is the most critical implementation risk for UPL-3.** For `#display-name-block`, the server renders the fragment via `_display_name_fragment` in `server/routes/notebooks.py`. For `#ingest-status`, the polling fragment is server-rendered. **The implementer MUST add `aria-live="polite"` to BOTH the static template element AND the server-rendered fragment returned by each outerHTML swap handler.** For `#papers-tbody` (which uses `beforeend`, not `outerHTML`), the tbody element is never replaced, so this issue does not apply.
Mitigation: audit every endpoint that returns fragments for `#display-name-block` and `#ingest-status`; add the attribute to the fragment wrapper.

**F4 — `:focus-visible` outline contrasts poorly on `--error-bg` inputs**
Trigger: a focused `<input>` inside an error state (`--error-bg: #fff4f2`) with `var(--accent)` outline. The blue `#1e5b8a` on red-tinted `#fff4f2` background needs verification.
Symptom: the focus ring may pass WCAG AA (3:1 non-text contrast) in theory but feel visually muddy in practice.
Mitigation: the challenger confirmed `2px solid var(--accent)` on `--card-bg` clears WCAG AA. On `--error-bg` the same blue still meets 3:1 (the error background is very light pink; the blue outline has high intrinsic contrast). No immediate action needed.

**F5 — `tabindex="-1"` on `<main>` confuses some AT as a focusable widget**
Trigger: `<main tabindex="-1">` makes `<main>` programmatically focusable. NVDA pre-2024 treats this as a focusable landmark, inserting it into the virtual buffer as a clickable region.
Symptom: NVDA users may find an unexpected focus stop on `<main>` during Browse mode.
Mitigation: This is the standard WCAG-recommended pattern for skip-link targets. macOS VoiceOver is the smoke-test target (per roadmap KR-1); NVDA behavior is out of scope for this operator-level installation. The tabindex="-1" approach is per-spec and accepted.

**F6 — skip-link `.skip-link:focus-visible` requires `:focus-visible` to be defined first**
Trigger: if the CSS `@supports not selector(:focus-visible)` fallback is needed (no current arXMCP browser) or if the `:focus-visible` UPL-2 block is placed AFTER the skip-link block in app.css.
Symptom: skip-link uses `:focus-visible` to reveal itself; if the spec-ordering matters for a future refactor, the skip-link rule might not fire.
Mitigation: place the `.skip-link` rule and the `:focus-visible` selector rule in the same block or ensure skip-link rule is self-contained (`a.skip-link:focus-visible { ... }`). No dependency on ordering in CSS specificity terms — both `:focus-visible` selectors apply independently.

**F7 — Jinja2 template attribute injection risk**
Trigger: the milestone adds string attributes (`aria-live="polite"`, `aria-atomic="true"`) to static Jinja2 template elements. These are static strings, not `{{ variable }}` interpolations.
Symptom: None. These are safe string literals.
Mitigation: None needed. The existing autoescape policy is unchanged.

---

## Recommendation

**Implement all four UPL items in a single commit touching two files: `app.css` and the three templates (`base.html`, `notebook_detail.html`, `index.html`).**

Specific implementation choices:
1. **UPL-1:** Universal block at END of `app.css`. Include all six properties named in AC: `animation-duration`, `animation-iteration-count`, `transition-duration`, `animation-delay`, `transition-delay`, `scroll-behavior`. All set to `0.01ms !important` (or `1` for `iteration-count`). `scroll-behavior: auto` for the scroll property.
2. **UPL-2:** Single selector block `button, .button, a, input, select, textarea, [tabindex] { outline: 2px solid var(--accent); outline-offset: 2px; }` under `:focus-visible`. Separate `button.danger:focus-visible { outline-color: var(--danger); outline-offset: 3px; }`. Then `:focus:not(:focus-visible) { outline: none; }`.
3. **UPL-3:** Add `aria-live="polite"` to the STATIC template elements (`#display-name-block`, `#ingest-status`, `#papers-tbody`). Add `aria-live="polite" aria-atomic="true"` to `#status-badge` in `base.html`. **Critically: also add the attributes to the SERVER-RENDERED fragments** for `#display-name-block` (in `server/routes/notebooks.py::_display_name_fragment`) and `#ingest-status` (in the polling fragment handler). Failing to do this breaks the live region after the first outerHTML swap.
4. **UPL-4:** Insert `<a class="skip-link" href="#main">Skip to main content</a>` as the VERY FIRST child of `<body>` in `base.html`. Add `id="main" tabindex="-1"` to `<main>`. CSS rule: off-screen by default (`position: absolute; left: -9999px; top: auto; width: 1px; height: 1px; overflow: hidden;`); revealed on `:focus-visible` (`position: fixed; left: 1rem; top: 1rem; width: auto; height: auto; z-index: 9999; padding: 0.5rem 1rem; background: var(--accent); color: #fff; border-radius: 4px; text-decoration: none;`).

The recommendation uses `position: fixed` (not `absolute`) for the revealed skip-link to ensure it appears in the viewport regardless of scroll position — critical for accessibility.

---

## Open questions

1. **Server-rendered fragment audit for outerHTML targets:** The implementer must verify which server-side handlers return the HTML fragment that replaces `#display-name-block` and `#ingest-status`, and add `aria-live` to those fragments. This is the highest-risk item and is NOT purely a template edit. Expected location: `server/routes/notebooks.py`. Needs a read of that file before implementation starts.

2. **`index.html` UPL-3 scope:** The AC explicitly names only 3 targets in `notebook_detail.html` + 1 in `base.html`. The `#notebook-list` tbody in `index.html` is a swap target but is NOT listed in the AC for m1 (it awaits UPL-12 in e4). Confirm the scope is intentionally limited to the 4 targets named in the AC.

3. **`z-index` for skip-link:** The milestone AC says `left: 1rem; top: 1rem` but does not specify `z-index`. The `<header>` element has `border-bottom` and may visually overlap a `position: absolute` skip-link on focus. Use `position: fixed; z-index: 9999` to guarantee visibility above all other content.

---

## External writes the implementation will require

None — this milestone is purely local. Pure CSS + HTML template attribute additions. No git push, no GitHub issues, no infrastructure changes. The note at `plans/ui-attractive-polish-roadmap.md` says "No UPL-5/6/7 bug-fix work inside THIS roadmap" — confirmed. The note about GitHub tickets says "not requested (no --github flag)."
