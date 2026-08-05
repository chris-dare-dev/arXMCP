# Critique — ui-uplift-m8 — milestone-frontend-ux

**Critic:** milestone-frontend-ux
**Commit range:** 590acd52577d295fead21b202769623eb75b5f4f..60e7aa0ec9361cb78a641d306cfa1ebe6745b2d5
**Diff stats:** 20 files, 2934 LOC (4 frontend source files: `app.css`, `tokens.css`, both templates)
**Critique format version:** 1.0
Severity counts: C0 H1 M3 L2

**Verification limitation, stated plainly and up front.** `create_app()` needs an
ingested corpus, so no page was rendered and **nothing in this review saw the
milestone's output**. That matters more here than in any prior milestone in this
track: the entire deliverable of ui-uplift-m8 is a visual re-composition — nine
boxes replaced by rhythm and three 1px rule weights — and every judgement below
is reasoned from CSS, markup and measured ratios, not from a screen. The
implementer recorded the same limitation at `implement/synthesis.md` "Not
verified in a browser"; this critique does not lift it.

## Verdict

SHIP-WITH-FIXES. The primitive really is gone, the ladder is coherent, and the
decorative exemption — the one judgement the contrast gate cannot make and this
critic can — **holds at all three tinted sites on inspection**: every one has a
genuine second, non-rule cue. The milestone's weakness is not the ladder but what
it declined to rank with it: nine top-level boundaries all take the same top rung,
so the authored `<section>`-vs-`<div>` distinction renders in zero channels and
the notebook detail page becomes a longer undifferentiated column than before.

## Executive summary

- [HIGH] All nine top-level boundaries take the same `--rule-section`; the
  per-site `<section>`/`<div>` decision renders in no channel — not visually, not
  in the a11y tree, not in the heading outline. On notebook detail the corpus is
  ranked identically to a one-button upload form and sits ~96px further down than
  before the milestone.
- [MEDIUM] `--rule-section` and `--rule-row` are adjacent in every table and
  differ only by a tint step at a shared 1px width and shared `solid` style — the
  research rejected thickness grading for being imperceptible, and lightness at
  1px carries the same risk it was chosen to avoid. Unverifiable at source level.
- [MEDIUM] The zero-paper state on notebook detail now renders a full-weight,
  filled, micro-caps table header over an empty `<tbody>`; AC#3's `thead th`
  upgrade sharpened it, and `index.html` solves the same problem differently.
- [MEDIUM] AC#1's radius guard reads only the **last** selector of a comma list
  and counts `[tabindex]` as a control — but the product's only `[tabindex]` is
  `<main>`, the most structural element there is.
- [LOW] Ladder terminators are inconsistent: `.discover-candidate:last-child`
  suppresses its rule; the last `tbody td` and last `dl.meta` row do not.
- [LOW] `.discover-title` is an `<h3>` rendered at the `<h2>` step, a live
  hierarchy inversion inside the one panel that has three heading levels.
- [POSITIVE] The exemption audit is exhaustive against the stylesheet and every
  claim in it that I could check independently is true, including the
  `art-direction-scout-brief` grant for the badge pill and the UPL-5 ownership of
  the deferred `.lede`.

## Findings

**H1 — Nine identical top boundaries; the section/div rank renders nowhere** (HIGH)

**Where:** `server/frontend/static/app.css:60`
**Anchor:** `main > :where(section, div) + :where(sec`
**What:** One rule serves all nine top-level boundaries at the same weight, rhythm and inline bleed, so the milestone's per-site `<section>` (focal content region) vs `<div>` (job form) decision has no rendered, semantic or navigational consequence, and the two focal regions are ranked exactly like the six forms.
**Why it matters:** On notebook detail — seven of the nine blocks — a reader gets no signal that "Papers in this notebook" is the point of the page while "Upload ar5iv HTML" is a tool, and because the boundary grew from `.card`'s 3rem (1rem padding + 1rem margin + 1rem padding, plus a box) to 4rem (2rem margin + 2rem padding, one hairline), the corpus moved roughly 96px further down a page where the discovery already measured the papers table at y=1823–2343; the deleted card at least drew a container edge, so this is the "undifferentiated column" outcome the roadmap warned about, arriving through rhythm rather than through missing type.
**Proposed fix:** Give the ladder a second top-level step rather than a second `.lede`, which is UPL-5's. Add a `main > section` treatment that the six `<div>`s do not get — e.g. `main > section > h2 { font-size: var(--text-title) }` reusing the existing token, or a `padding-block-start: 3rem` on `main > :where(section) + …` so the two content regions open with visibly more air than a form does. Either is a few lines, needs no new token, and makes the D2 table's own claim ("the page's focal content region") true in the one channel a reader uses. **Do not reach for the discovery's own answer here** — collapsing the five mutation forms into a native `<details>` "Manage" region below the corpus is triangulated across three discovery briefs but is explicitly owned by `ui-uplift-m12`, whose summary already names the "measured 1823px scroll" this milestone lengthens. So the fix wanted from m8 is an interim *ranking* device, not the reorder; and whichever is chosen, record the deferral at the rule in `app.css:60` the way every other deferral in this stylesheet is recorded, so the next reader does not read the uniformity as unfinished.
**Regression-guard:** Extend `tests/test_ui_m8_rule_ladder.py` with a test asserting that at least one declaration distinguishes `main > section` from `main > div` — i.e. that the D2 decision has a rendered consequence — and pin the count of top-level `<section>` elements per template so a later edit cannot flatten them back.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

**M1 — Section and row rungs differ only by tint at a shared 1px solid** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:146`
**Anchor:** `  --rule-row: 1px solid color-mix(in okl`
**What:** The two rungs a reader must actually tell apart are adjacent in every table (`thead th` at 3.3123:1 directly above `tbody td` at 2.5332:1) and are identical in width and style, so the entire grading signal is a single lightness step on a 1px line.
**Why it matters:** The research rejected grading by thickness on the grounds that two rungs an operator cannot tell apart is not a ladder — but at 1px a line's perceived weight essentially *is* its lightness, so the chosen axis inherits the same failure mode, and if the step does not read as rank it reads as inconsistent anti-aliasing, which is worse than one weight would have been.
**Proposed fix:** No code change until this is seen. Render `/ui/notebooks/<slug>` at 1440x900 and at 200% zoom in both colour schemes and answer one question: does the rule under `<thead>` read as heavier than the rules under the data rows? If it does, close this and record the check. If it does not, the cheapest repair is to let the top rung differ in more than tint — the `thead th` fill and micro-caps already carry that boundary (four other cues), so the honest move is to *drop* `tbody td` to no rule at all inside a table that already has column alignment, rather than to keep a rung nobody can rank.
**Regression-guard:** Optional for MEDIUM; if the render check is done, record the outcome in `.claude/docs/ui-contrast-table.md` beside the existing EXEMPT rows so a later reader sees a verdict rather than a ratio.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy / experiential distinctiveness

**M2 — Zero-paper state renders a full-weight table header over nothing** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:321`
**Anchor:** `  {% if not papers %}`
**What:** The papers `<table>` always renders because it is the htmx swap target, so with zero papers the section shows a centred italic message followed by a filled, uppercase, micro-caps header row carrying the ladder's *strongest* rule beneath it and an empty `<tbody>`.
**Why it matters:** AC#3 deliberately promoted `thead th` to `--rule-section`, which makes the header the single heaviest horizontal element on the page at exactly the moment there is no data under it, and with the card box gone there is no longer a container edge to explain why an empty header is floating there — a first-time operator reads it as a load failure rather than as an empty notebook. **Scoped deliberately:** `ui-uplift-m11` (UPL-21) owns *authoring* the four empty states with a cause and an action, and that gap is not flagged here; what is flagged is the composition regression m8 itself introduced by raising the rule above an empty body.
**Proposed fix:** Mirror what `index.html` already does correctly — move the empty message into the tbody as a spanning placeholder row (`<tr id="papers-empty"><td colspan="4" class="empty">…</td></tr>`) and drop the separate `<p class="empty">`, so the header always has a body under it and the two pages solve the same problem the same way. The add-paper and upload forms both `hx-swap="beforeend"` into `#papers-tbody`, so they need the same `document.getElementById('papers-empty')?.remove()` hook `index.html:38` already carries on its create form. This is the structural half only and composes with m11 rather than pre-empting it — m11 replaces the copy inside whichever element ends up holding it.
**Regression-guard:** A test asserting `notebook_detail.html` renders no `<tbody>` that can be empty while its `<thead>` is present — or, more simply, that both templates use the placeholder-row idiom, pinned by the presence of an `id` ending `-empty` inside each `<tbody>`.
**Source critic:** milestone-frontend-ux
**Source axis:** Empty states

**M3 — The radius guard checks one selector per rule and calls `<main>` a control** (MEDIUM)

**Where:** `tests/test_ui_m8_rule_ladder.py:123`
**Anchor:** `            leaf = selector.split(",")[-`
**What:** `test_structure_carries_no_border_radius` reduces every rule to the last selector in its comma list before classifying it, and its `is_control` regex admits `[tabindex]` and `:focus-visible` — but the product's only `[tabindex]` is `<main id="main" tabindex="-1">`, so `app.css:428`'s `border-radius: 4px` lands on the page's top-level structural container whenever the skip link moves focus there.
**Why it matters:** This is the guard that makes AC#1's headline geometry claim falsifiable, and it has two holes at once: a radius reintroduced on a structural selector grouped anywhere but last in a comma list is invisible to it (`section, button { border-radius: 8px }` passes, since the `6px` check is a literal string match), and the one structural element that *does* take a radius today is classified as a control by regex — so the milestone's "radius 0 on structure, 4px on controls" reads as true while the largest structural box in the product rounds on keyboard focus.
**Proposed fix:** Iterate every selector in the comma list, not `[-1]`; classify each independently; and drop `[tabindex]` from the control pattern, replacing it with an explicit named exception if `main:focus-visible` is meant to keep its radius. If it is not meant to, `main:focus-visible { border-radius: 0 }` is a one-line fix that makes the thesis literally true. Replace the `"6px" not in found.values()` literal with a check that no non-control selector carries any non-zero radius.
**Regression-guard:** `tests/test_ui_m8_rule_ladder.py::TestCardPrimitiveIsGone::test_structure_carries_no_border_radius` — add a negative case asserting the guard *rejects* a synthetic `section, button { border-radius: 8px }` input, so the comma-list hole cannot silently reopen.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**L1 — Ladder terminators are inconsistent across the three rungs** (LOW)

**Where:** `server/frontend/static/app.css:229`
**Anchor:** `.discover-candidate:last-child { border-`
**What:** The `--rule-row` list suppresses its final rule as a deliberate terminator, while the last `tbody td` (same rung) and the last `dl.meta` row (`--rule-meta`) both keep theirs.
**Why it matters:** In a milestone whose entire deliverable is that rule weight is consistent and meaningful, two sites on the same rung ending differently is exactly the "inconsistency bug" reading the thesis is trying to avoid.
**Proposed fix:** Pick one convention and state it at the token. A closing rule on a table and a `<dl>` is defensible (it bounds the block before the next control); the discover list's suppression is defensible too (it is the last thing in its panel). Whichever is chosen, record the rule in `tokens.css` beside `--rule-row` so the next site does not have to guess.
**Regression-guard:** Optional for LOW.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**L2 — `.discover-title` is an `<h3>` at the `<h2>` size step** (LOW)

**Where:** `server/frontend/static/app.css:231`
**Anchor:** `.discover-title { margin: 0; font-size: `
**What:** `.discover-title` sets `--text-section`, the same 20px step the bare `h2` rule uses, so each candidate's `<h3>` renders at its parent block's heading size and differs only by weight (600 vs the UA bold 700).
**Why it matters:** The Discover panel is the one surface with three heading levels, and it is the surface where a reader most needs to see that a candidate is subordinate to the block — this milestone's premise is that m7's type scale and the ladder now carry hierarchy together, and here the scale contributes nothing.
**Proposed fix:** Drop `.discover-title` to `--text-body` and let weight plus the `--rule-row` boundary mark the item, which restores a real step between the block heading and the item heading without minting a token. Introduced by ui-uplift-m10, not by m8 — flagged here because m8 is the milestone asserting the two systems cooperate.
**Regression-guard:** Optional for LOW.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

## What was done well

- **The decorative exemption is real, not asserted — and this is the finding that
  matters most.** I checked all three tinted sites independently and each has a
  genuine second cue: `tbody td` has column alignment plus a button-height row
  box; `.discover-candidate` has a per-item `<h3>` plus 1.5rem of combined
  padding; `dl.meta` has a `max-content` two-column grid with a weighted,
  colour-shifted `<dt>` column whose occupancy distinguishes "new row" from
  "wrapped line". No tinted rule is the sole cue for any grouping. The exemption
  the contrast gate could not judge survives the judgement.
- **The exemption audit is exhaustive against the stylesheet.** I enumerated
  every `--rule-*` consumer in `app.css` and the six-row table in
  `implement/synthesis.md` covers all of them with nothing omitted — the failure
  mode where an audit lists the comfortable sites and skips one did not happen.
- **`dl.meta` row separation improved rather than regressed.** `gap: 0.25rem 1rem`
  became `gap: 0` plus `padding-block: 0.25rem` on both `dt` and `dd`, which
  raises inter-row whitespace from 4px to 8px *and* makes the per-cell borders
  contiguous across the two columns. The comment claims the gap change was
  mechanically necessary for a continuous rule; it was, and it made the spacing
  better as a side effect.
- **No landmark was lost, and the claim to that effect is correct.** All nine
  blocks were unnamed `<section>`s before, which expose `generic`, not `region` —
  so dropping six to `<div>` moved nothing in the accessibility tree, and the
  refusal to mint nine `aria-labelledby` regions is the right call. The `<h2>`
  outline that a screen-reader user actually navigates by is intact on both
  pages, with no skipped levels.
- **Two verifiable claims I expected to be loose turned out to be exact.** The
  badge's surviving pill is genuinely granted by name in the art direction
  ("no rounded pills beyond the single operability badge", and trait 1 names
  "buttons, inputs, the one operability badge"), and the deferred `.lede` really
  does belong to UPL-5 as a separately catalogued DIRECTION-DEFINING item with
  BAN-5 assigned to it in `challenge.md` — the deferral is honest, not a dropped
  requirement dressed up.
- **The `.card X` de-prefixing is behaviourally safe.** Every element carrying
  `hint` / `empty` / `display-name` — including the four inline `<span
  class="hint">` uses inside `<dd>` and `<td>`, and the fragment builders in
  `server/routes/notebooks.py` — was inside a `.card` before, so widening
  `(0,2,0)` to `(0,1,0)` changed which rules win for exactly zero elements.
- **One declaration per rung genuinely serves both colour schemes.** Because the
  tints are `color-mix()` against `var(--border)`/`var(--bg)` and custom
  properties substitute at use time, the mix moves *away* from the ground in both
  modes (lighter in light, darker in dark). Three declarations, not six, with no
  possibility of the two modes drifting — and the reason is written down.
- **`role="list"` on the discover `<ul>` pre-empts the exact WebKit trap this
  milestone would otherwise have walked into**, since `.discover-list` sets
  `list-style: none` and the exemption argument for `--rule-row` leans on `<li>`
  semantics being announced.
- **The stylesheet writes down the lines it deliberately did not change.** The
  `tbody tr:hover` note explaining why it stays on `var(--card-bg)` — and
  explicitly retiring the research's now-obsolete reason for it — is the
  difference between an argued decision and an oversight, and it is the habit
  that made this diff reviewable at source level at all.

## Recommended rectification order

H1, M2, M3, M1, L2, L1
