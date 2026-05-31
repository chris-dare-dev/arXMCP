# Critique — ui-attractive-polish-m1

**Critic:** adversary
**Generated:** 2026-05-30T19:30:00Z
**Commit range:** `924d5ad..c5adff3`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES — the load-bearing finding (outerHTML-aria-live trap) is
  closed across all 6 server-fragment sites and guarded by load-bearing
  regression tests; remaining findings are all peripheral (doc accuracy +
  one missing aria-atomic parity).
- Finding counts: **0 CRITICAL, 0 HIGH, 2 MEDIUM, 3 LOW**.
- Highest-risk file:line: `frontend/static/app.css:166`
  (`[tabindex]:focus-visible` matches `<main id="main" tabindex="-1">` —
  audited and verified intentional, the focus ring on `<main>` is the
  WebAIM-recommended confirmation that the skip-link landed; no fix needed).
- All 6 outerHTML-replacement sites (5 server fragments + the badge poll)
  carry `aria-live`; the 4 `_ingest_status_fragment` branches are each
  covered by a unit test calling the helper directly (not substring
  matches on a template). The endpoint test for `/ui/status-badge` goes
  through TestClient.
- The 5 pre-existing `pre.error[aria-live="polite"]` regions were NOT
  touched; the `pre.error:empty { display: none }` rule was NOT touched.
  Verified by diff inspection.
- No new vendored assets, no submodules, no MCP-tool surface touched,
  `EXPECTED_TOOL_SCHEMA_SHA256` unchanged (verified — no edits to
  `server/tools.py` or `server/prompts.py`).
- Implementation-summary inaccuracy: CSS budget overshoot is reported as
  "186 lines" but the actual on-disk line count is **190 lines** — minor
  doc drift, not a code defect.
- `aria-atomic="true"` parity gap between the badge fragment (which has
  it) and the 4 ingest-status branches (which don't) — defensible but
  worth surfacing.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — `aria-atomic` parity gap on ingest-status fragments

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/routes/notebooks.py:1380,1394,1405,1418`
  (the 4 `_ingest_status_fragment` branches: `none`/`running`/`success`/`failed`)
- **What:** The status-badge fragment in `server/routes/ui.py:269` carries
  both `aria-live="polite"` AND `aria-atomic="true"` (with an inline
  comment justifying the atomic flag as reading the WHOLE composite
  string). The 4 `_ingest_status_fragment` branches carry only
  `aria-live="polite"` — no `aria-atomic`. The ingest-status div content
  is itself a composite string ("Status: success · Finished … · Run #42 ·
  Logs"), and on outerHTML swap the WHOLE element is replaced. Without
  `aria-atomic="true"` the AT defaults to `false`, which under the WAI-ARIA
  spec announces only the changed nodes — and when the entire element is
  replaced, AT behavior varies by implementation (some announce
  everything, some announce nothing because there is no DOM-diff-able
  "change" — the whole subtree is a new element).
- **Why it matters:** The synthesis explicitly converged on
  `aria-live="polite"` parity for ALL 6 sites, but the parity argument
  applies equally to `aria-atomic`. A future operator running VoiceOver
  may hear the badge changes (atomic-true) but not the ingest status
  transitions (atomic-default) — exactly the kind of inconsistency that
  the m1 milestone was supposed to eliminate. The implementation
  summary's "Manual VoiceOver smoke-test NOT performed in pipeline" line
  means this gap would surface as a regression at first manual test.
- **Proposed fix:** Add `aria-atomic="true"` to the 4 branches in
  `_ingest_status_fragment` so they parity-match the badge fragment.
  Same edit shape as the existing `aria-live="polite"` insertions:
  ```python
  f'<div id="ingest-status" data-status="none" '
  f'aria-live="polite" aria-atomic="true" ...'
  ```
  Update the static template at `notebook_detail.html:173` to also carry
  `aria-atomic="true"`. ~5 LOC.
- **Regression guard:** Extend each `test_ingest_status_fragment_*_includes_aria_live`
  test in `tests/test_ui_a11y_baselines.py:274,287,300,313` to also assert
  `'aria-atomic="true"' in out`. 4 new asserts.

### F2 — CSS line count reported as 186 but actually 190

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/notes/milestones/ui-attractive-polish-m1/implementation-summary.md:30`
- **What:** The implementation summary's AC checkbox for the
  "≤ 165 lines" CSS budget says "**Actual: 186 lines.**" The on-disk
  `frontend/static/app.css` is 190 lines (`wc -l` confirms). Five-line
  doc drift on a number the summary itself uses to justify the overshoot.
- **Why it matters:** The implementation-summary is the post-milestone
  artifact future agents read to decide whether to revisit the overshoot.
  Reporting 186 when the file is 190 makes the "shipped within reasonable
  bounds" reasoning subtly wrong (the gap is 25, not 21). Recurring
  pattern in this repo's milestone summaries (see prior
  `bp1-description-vs-handler-validator-drift` and `security-doc-drift`
  memories): doc-says-X-code-does-Y is a HIGH-frequency rectifier finding,
  even when the magnitude is small. Caught now, the cost is one number
  fix; caught at the next CSS budget audit, it becomes "wait, was the
  baseline 186 or 190?".
- **Proposed fix:** Update implementation-summary.md:30 to read
  "**Actual: 190 lines.** Overshot the 165 budget by ~25 lines because
  …" — and round the second paragraph's "~21 lines" to "~25 lines".
- **Regression guard:** N/A (doc-only). Optionally add a
  `tests/test_ui_css_budget.py` that asserts `(FRONTEND_STATIC /
  "app.css").read_text().count("\n") <= <new_budget>` so the next
  overshoot is loud at test time — but that's a m2-scope question
  (CSS budget enforcement was not in m1's brief).

### F3 — `[tabindex]:focus-visible` over-broad (audited, not a defect)

- **Severity:** LOW
- **Source:** adversary
- **File:** `frontend/static/app.css:166`
- **What:** The `:focus-visible` selector list ends with
  `[tabindex]:focus-visible`, which matches ANY element with a `tabindex`
  attribute. Today the only `tabindex` in the project is
  `<main id="main" tabindex="-1">` (verified by `grep -rn 'tabindex'
  frontend/ server/routes/`). When the skip-link is activated, focus
  moves to `<main>` which then receives the `2px solid var(--accent)`
  outline.
- **Why it matters:** This is INTENTIONAL — WebAIM G1 specifies that
  keyboard users should see a visual confirmation when focus lands in
  `<main>` after a skip-link activation. But it is also a foot-gun for
  future milestones: any new `tabindex="-1"` element (a programmatically-
  focusable modal, a `tabindex="0"` widget) will get the same
  full-width outline ring, which may not be desired (e.g. a tabindex
  on a `<dl>` row would draw a multi-line ring across the grid).
- **Proposed fix:** No code change recommended — the current behavior is
  the WebAIM-recommended outcome. Optional: add a comment at app.css:166
  noting that `[tabindex]:focus-visible` currently matches only `<main>`
  and that future tabindex additions should consider whether the ring
  shape is appropriate. Or narrow the selector to
  `main[tabindex]:focus-visible` for explicitness.
- **Regression guard:** Already covered by
  `test_focus_visible_rule_covers_all_interactive_selectors` (asserts
  the selector is present).

### F4 — Manual VoiceOver + keyboard-walk gates not executed in pipeline

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/notes/milestones/ui-attractive-polish-m1/implementation-summary.md:27-28`
- **What:** The implementation summary itself flags that both KR-1
  manual gates (Tab-walk verifying the `--accent` ring on every
  interactive element, VoiceOver smoke-test confirming announcements
  fire on rename + badge poll) were NOT executed in-pipeline. The
  structural regression tests (`TestUPL3*Fragment*`) prove the server
  emits the right attributes, but cannot prove a screen reader
  ACTUALLY speaks them.
- **Why it matters:** This is a known pipeline limitation, not a critic
  finding per se — but worth flagging in the critique chain so the
  rectifier doesn't accidentally mark the milestone "complete" without
  Chris's manual gate. Per agent-conventions, "deferred without
  tracking" is a named anti-pattern; the implementation summary defers
  the gate to Chris but does not file a tracking issue at
  `chris-dare-dev/arXMCP`.
- **Proposed fix:** No code change. Two options:
  (a) implementation-summary.md adds an explicit "open-followups" line
  pointing at a manual checklist (no GitHub issue needed, since this is
  Chris-only); or
  (b) the rectifier files a GitHub issue at `chris-dare-dev/arXMCP` with
  the 5-line checklist (badge poll, rename swap, ingest status
  transitions, skip-link Tab order, focus-ring on each interactive
  control). Option (a) is the cheaper move.
- **Regression guard:** N/A (manual gate).

### F5 — Skip-link `top: 1rem` may overlap footer status badge under tiny viewport

- **Severity:** LOW
- **Source:** adversary
- **File:** `frontend/static/app.css:144-145`
- **What:** When focused, the skip-link uses `position: fixed; left:
  1rem; top: 1rem` and z-index 9999. On a sufficiently small viewport
  (or with browser zoom) the header is below the skip-link's reveal
  position. The visually-revealed link partially covers the
  `<h1>` "arXMCP notebooks" link. Same overlap concern applies to the
  footer status-badge if the viewport is < ~400px tall (the footer
  scrolls into the top-left area).
- **Why it matters:** Minor cosmetic. Doesn't break a11y — the skip-link
  IS supposed to be visually prominent — but the overlap on the H1 may
  visually surprise an operator. WebAIM canonical pattern is exactly
  this shape so the overlap is accepted-practice, not a defect.
- **Proposed fix:** None for m1. If a future milestone wants polished
  small-viewport behavior, add `box-shadow: 0 2px 6px rgba(0,0,0,0.15)`
  to `.skip-link:focus-visible` to visually separate it from the
  underlying H1.
- **Regression guard:** N/A.

## What was done well

- **Load-bearing finding closed at every site.** All 6 outerHTML-replaced
  fragments carry `aria-live` on the swap result: `_display_name_fragment`
  (server/routes/notebooks.py:411), the 4 branches of
  `_ingest_status_fragment` (1380, 1394, 1405, 1418), and the badge
  fragment (server/routes/ui.py:269). The synthesis's enumerated audit
  list was followed exactly.
- **Tests exercise the actual code paths, not template substrings.**
  `TestUPL3DisplayNameFragmentAriaLive` calls `_display_name_fragment(...)`
  directly; `TestUPL3IngestStatusFragmentAriaLive` calls each of the 4
  branches with realistic kwargs; `TestUPL3StatusBadgeEndpoint` goes
  through FastAPI TestClient. These are the load-bearing regression
  guards the synthesis called for — a future refactor that silently
  drops the attribute from a fragment branch will fail loudly.
- **The synthesis's D2 (skip-link `fixed` vs `absolute`) was correctly
  resolved in favor of `fixed`** with z-index 9999, per the WCAG-intent
  argument (viewport-stable regardless of scroll).
- **The synthesis's D3 (`aria-relevant` defer) was correctly honored —**
  no `aria-relevant` attribute added; relies on AT defaults
  (`additions text`).
- **Inline comments justify the WHY of every block.** Each of the 4
  new CSS sections in app.css and each server-fragment edit has an
  inline `/* ui-attractive-polish-m1 (UPL-N): … */` block that cites
  the research-synthesis section by §number. Future-agent legibility
  is high.
- **`pre.error` regions untouched.** Diff verifies the 5 pre-existing
  `pre.error[aria-live="polite"]` regions and the
  `pre.error:empty { display: none }` CSS rule were not modified
  (synthesis explicitly required this — touching them would have
  conflicted with the existing error-display contract).
- **`button.danger:focus-visible` correctly uses `var(--danger)` with
  `outline-offset: 3px`** — researcher-2's destructive-control
  visibility-against-red-fill argument was adopted verbatim.
- **`:focus:not(:focus-visible) { outline: none }` reset present** —
  mouse clicks don't draw the keyboard-focus ring, matching the
  `:focus-visible` contract.
- **`html.escape` boundary preserved** — the server-fragment changes
  added only static literal attribute strings (`'aria-live="polite"
  aria-atomic="true"'`), no new operator-controlled interpolation.
  No XSS surface widening (Axis 3 verified clean).
- **MCP / cache-stability surface entirely untouched** — diff confirms
  `server/tools.py`, `server/prompts.py`, `tests/test_server_tool_schema.py`,
  `tests/test_prompts.py` are all in zero hunks. `EXPECTED_TOOL_SCHEMA_SHA256`
  unchanged. No BP1/BP2 cache discipline risk (Axis 1 verified clean).

## Recommended rectification order

1. **F1 (`aria-atomic` parity)** — 5-LOC edit + 4-assert test extension.
   Highest leverage because it closes the parity gap the synthesis
   implicitly intended; cheap to ship.
2. **F2 (CSS line count doc fix)** — 1-line edit to implementation-summary.md.
   Trivial; ship in the rectifier pass for hygiene.
3. F4 (manual gate tracking) — optional one-liner in implementation-summary.md.
   Skip unless Chris flags it.
4. F3 + F5 — defer (LOW; intentional behavior + canonical pattern,
   respectively).

## Rectification status

- F1 — fixed in `server/routes/notebooks.py` `_ingest_status_fragment` (4 branches: none/running/success/failed gained `aria-atomic="true"`) + `frontend/templates/notebook_detail.html:163` (placeholder gained `aria-atomic="true"`). Regression guards: extended `TestUPL3IngestStatusFragmentAriaLive` (4 tests now also assert `aria-atomic="true"`) + renamed/extended `TestUPL3StaticTemplateAriaLive::test_ingest_status_template_has_aria_live_and_aria_atomic`.
- F2 — fixed in `.claude/notes/milestones/ui-attractive-polish-m1/implementation-summary.md` — line count corrected from "186" to "190"; "~21 lines" overshoot corrected to "~25 lines". Regression guard: N/A (doc-only). The adversary suggested a `tests/test_ui_css_budget.py` for future enforcement; deferred as out-of-scope for m1 (the milestone's brief did not include CSS-budget assertion infrastructure).
- F3 — deferred (LOW; INTENTIONAL per WebAIM G1 — the `[tabindex]:focus-visible` over-broad selector is the canonical way to confirm focus landed in `<main>` after a skip-link activation; today the only tabindex in the project is `<main id="main" tabindex="-1">`; future tabindex additions can narrow if needed).
- F4 — deferred (LOW; manual VoiceOver + Tab-walk gates require a human at a macOS keyboard. The implementation-summary already names them as Chris-prerequisite for declaring KR-1 met; the rectifier did not file a GitHub issue per the adversary's option (a) preference — the chris-only nature makes a tracker overhead).
- F5 — deferred (LOW; the skip-link `position: fixed; left: 1rem; top: 1rem` overlap with the H1 on small viewports is the WebAIM canonical pattern — accepted-practice, not a defect. The optional `box-shadow` polish is parking-lot for a future visual-polish milestone, not m1).
