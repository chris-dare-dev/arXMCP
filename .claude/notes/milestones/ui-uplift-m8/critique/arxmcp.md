# Critique — ui-uplift-m8 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 590acd52577d295fead21b202769623eb75b5f4f..60e7aa0ec9361cb78a641d306cfa1ebe6745b2d5
**Diff stats:** 20 files, 2934 LOC (11 product/test files = 1385 LOC; 9 files are milestone notes)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

Every ratio m8 hand-typed into `tokens.css` and `app.css` reproduces to four decimals against an independent OKLCH→sRGB→WCAG implementation I wrote from the Oklab and CSS Color 4 specs, with one exception (M1), so the milestone's core exposure — manufactured contrast numbers — is largely clean. The load-bearing defect is an inventory one: `--rule-section` still renders against the `tbody tr:hover` ground via the same commit's own `thead th` rule, m8 retired that registry row on the stated ground that "no FULL-WEIGHT rule is drawn against the row-hover ground any more", and the retired pair (3.0401:1) is the registry's true tightest gated pair — so the published Headline now names a looser pair and the artifact's "clears the bar on every ground" claim is unbacked. Nothing fails a gate, the suite is at the exact 8-failure baseline with zero new failures, and ruff is clean.

## Executive summary

- [HIGH] `--rule-section` renders on the row-hover ground at **3.0401:1** — the registry's tightest gated pair — and m8 retired that row on a premise its own `thead th { border-block-end: var(--rule-section) }` contradicts; the published Headline now claims 3.129:1.
- [HIGH] Diff is 1385 product/test LOC against a ~450 threshold (3.1×); `implement/scope-exceeded.md` discloses it honestly and the atomicity argument holds.
- [MEDIUM] `app.css:149` publishes **1.1081:1** for the light `th` fill-alone separation; no pair in the stylesheet measures that — the real value is **1.0281**, stated by the same file 27 lines later.
- [MEDIUM] `TestSectioningElementDecision` pins block *counts*, not the per-site `<section>`/`<div>` decisions its failure message claims to pin — proved by swapping both index.html sites, which still passes.
- [MEDIUM] `test_the_ladder_is_horizontal_only` ignores the four-sided `border:` shorthand, so a box primitive can return on structure and pass all four AC#1 guards — proved by mutation.
- [MEDIUM] `--rule-meta`'s SC 1.4.11 exemption argues the dt/dd *pairing* survives, but the rung draws the entry-to-entry boundary, not that pairing.
- [MEDIUM] Two lockstep cap blocks still record "the file lands at 575 of 600, a 25-line margin"; app.css is at 599/600 — the rectify pass has 1 line, and those blocks are where it will look.
- [MEDIUM] The artifact prose paragraph m8 explicitly audited still lists `.discover-abstract` at 13px; `app.css:251` ships it at `--text-meta` = 11px.

## Findings

**H1 — Retired row-hover rule pair is the registry's tightest, and still renders** (HIGH)

**Where:** `tests/test_ui_contrast.py:378`
**Anchor:** `#      * no FULL-WEIGHT rule is drawn ag`
**What:** m8 retired the two `--border on tbody tr:hover` registry rows on the stated ground that "no FULL-WEIGHT rule is drawn against the row-hover ground any more — the row rule dropped to `--rule-row`", but the same commit adds `thead th { border-block-end: var(--rule-section) }` (`app.css:151`), and `--rule-section` *is* `1px solid var(--border)` — under `border-collapse: collapse` that collapsed border is the boundary directly above the first `tbody` row, so it renders against the hover tint whenever that row is hovered.
**Why it matters:** Measured with the repo's own helper, `--border` on `ROW_HOVER` is **3.0401:1** light / 3.0804:1 dark — tighter than the 3.1292:1 pair the regenerated Headline now names as "Tightest gated pair", so the published artifact understates the console's real SC 1.4.11 margin, the pair is gated by nothing, and `tokens.css:142`'s "Clears SC 1.4.11 on every ground it is drawn against" plus the artifact's observation-6 "clears the bar on every ground" are both unbacked; this is the partial-inventory failure the module docstring names as how three AA failures shipped.
**Proposed fix:** Re-register both rows under the ladder's name — `_p(_m, "--rule-section under thead, over the tbody tr:hover tint", "--border", ROW_HOVER, NONTEXT)` — and replace the retirement comment with the corrected reason (the `th` fill row was renamed, the hover row was not retired). Extend `tests/test_ui_m8_rule_ladder.py:241`'s ground loop to include `ROW_HOVER` so the guard's name `..._on_every_ground` becomes true. Regenerate with `python -m tests.test_ui_contrast --update`; the Headline will revert to naming the hover pair.
**Regression-guard:** Add `test_every_rule_token_site_has_a_registry_row` in `tests/test_ui_contrast.py`, modelled on the existing `test_every_faded_css_rule_has_a_registry_row`: derive each `border-*: var(--rule-*)` selector from `app.css` and assert a `PAIRS` row exists for every ground that selector renders against. No such derived guard exists today, which is why the hover ground went missing by hand.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**H2 — Implementation diff is 3.1x the dispatch threshold** (HIGH)

**Where:** no specific file
**What:** The 11 product/test files carry 1068 insertions / 317 deletions = 1385 changed lines against the brief's ~450-LOC threshold; the full range including milestone notes is 20 files / 2934 LOC.
**Why it matters:** A diff this size exceeds what a Phase-3 critic can review line-by-line, which is the standing reason the threshold exists.
**Proposed fix:** No code change. `implement/scope-exceeded.md` already records the real numbers, the 1191-authored / 194-generated split, and the argument that deleting a CSS primitive has no partial-but-coherent commit (nine markup sites, the rule sheet, the token sheet, four named guards, the BAN-R2 gate and the registry must move together or the suite is red). I verified all three claims and they hold; the expected Phase-4 disposition is "acknowledged, record complete", not a rewrite.
**Regression-guard:** None — this is a process finding, and the required disclosure artifact is present.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M1 — app.css publishes a th-separation ratio that matches no pair** (MEDIUM)

**Where:** `server/frontend/static/app.css:149`
**Anchor:** `   leaving the boundary on a fill alone `
**What:** The AC#3 rationale states the header boundary was "carried by a fill at 1.1081 light / 1.0948 dark"; the dark figure is correct (`--card-bg` vs `--bg` = 1.0948) but nothing in the stylesheet measures 1.1081 — `--card-bg` vs `--bg` light is **1.0281** and the retired `#f0f0f0` vs `--bg` is 1.0778.
**Why it matters:** A hand-typed contrast number with no source is the exact defect `tests/test_ui_contrast.py`'s docstring cites as precedent ("a comment in app.css came to state a ratio that was ~20% wrong"), and this file states the correct 1.0281 for the same surface 27 lines later, so the stylesheet now contradicts itself about its own AC#3 justification.
**Proposed fix:** Change `1.1081 light` to `1.0281 light` at `app.css:149`, and correct the same figure where `implement/synthesis.md` repeats it. The AC#3 argument gets stronger, not weaker — a 1.0281 separation is a worse boundary than 1.1081, so no decision changes.
**Regression-guard:** Optional — extend `test_no_ratio_is_typed_outside_a_generated_region` (currently scoped to the artifact) to also scan `app.css`/`tokens.css` comments and require every 4-decimal ratio to reproduce against `_ui_color.contrast_ratio`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M2 — Section/div guard pins counts, not the per-site decisions it claims** (MEDIUM)

**Where:** `tests/test_ui_m8_rule_ladder.py:352`
**Anchor:** `        sections = len(_re.findall(r"^<s`
**What:** `test_block_element_split_is_as_decided` asserts `(sections, sections + divs) == (want_sections, want_blocks)`, so it constrains only how many of each element exist; I swapped index.html's Create block to `<section>` and its Existing-notebooks block to `<div>` and the assertion still yields `(1, 2)` and passes.
**Why it matters:** The failure message says "The split is a recorded per-site judgement (implement/synthesis.md), not a default — changing it means re-deciding it", which the check does not enforce; D2 is described in the implement synthesis as the milestone's most judgement-heavy call, and `ui-uplift-m12` (`depends_on: [ui-uplift-m8]`) is an explicit detail-page reorder that will touch exactly these blocks.
**Proposed fix:** Pin the ordered element sequence rather than the counts, e.g. assert `_re.findall(r"^<(section|div)>", markup, flags=_re.M) == ["div", "section"]` for index.html and `["section", "div", "div", "div", "div", "div", "section"]` for notebook_detail.html, keyed to the synthesis table's nine rows.
**Regression-guard:** The rewritten assertion itself — it fails on the swap above, which the current one does not.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M3 — Horizontal-only guard ignores the border shorthand, so the box can return** (MEDIUM)

**Where:** `tests/test_ui_m8_rule_ladder.py:184`
**Anchor:** `                r"border-(?:left|right|i`
**What:** The guard matches only `border-left` / `border-right` / `border-inline-start` / `border-inline-end`; appending `main > section { border: 1px solid var(--border); }` to the comment-stripped `app.css` leaves the guard finding zero vertical edges and passing, even though that declaration draws all four sides.
**Why it matters:** Its own message is "vertical edges found … the box was deleted on purpose", and AC#1's four guards are the only defence of "no `.card` primitive remains" — a square, differently-named box using the shorthand passes `test_no_stylesheet_declares_a_card_rule` (not named `.card`), `test_structure_carries_no_border_radius` (no radius), `test_card_bg_is_no_longer_a_panel_ground` (no `--card-bg`) and this one, so the primitive can return under another name with every AC#1 guard green.
**Proposed fix:** Also scan `border:` shorthands and fail any whose selector is not a control, reusing the `is_control` predicate already written at `tests/test_ui_m8_rule_ladder.py:124`. The five existing shorthands (`input`, `textarea`, `button.button-quiet`, `.status-badge`, the spinner's `border: 2px solid currentColor`) are all controls or the enumerated circle, so the tightened guard passes today.
**Regression-guard:** The tightened guard, verified against the `main > section { border: 1px solid var(--border) }` mutation above, which must fail.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M4 — rule-meta's SC 1.4.11 exemption argues a boundary the rung does not draw** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:153`
**Anchor:** `  --rule-meta: 1px dotted color-mix(in o`
**What:** The exemption reads "whose dt/dd pairing is carried by `<dl>` semantics and by a two-column grid: delete the rule and the grouping is unchanged, which is the test this exemption has to pass" — but `dl.meta dt, dl.meta dd { border-block-end: var(--rule-meta) }` draws a horizontal line under each row, separating metadata entry N from entry N+1; it never draws the dt↔dd boundary, which is a vertical edge the ladder forbids by design.
**Why it matters:** CLAUDE.md §4.9 makes a published exemption a trust claim, and this one passes its stated test by answering about a boundary the rung does not render; the boundary it *does* render sits in a `gap: 0` grid with only `padding-block: 0.25rem` per side, so the argument that something else carries it is never actually made. `--rule-row`'s `tbody td` leg leans on "column alignment", which is also weaker for row separation than for column separation.
**Proposed fix:** Restate the exemption against the real boundary — entry-to-entry grouping is carried by the `font-weight: 500` dt occupying column 1 of every row plus `<dl>` dt/dd semantics — or give `dl.meta` a row `gap` so proximity carries it and the rule is genuinely ornamental. The same edit should sharpen `_META_WHY` in `tests/test_ui_contrast.py`, which carries the identical wording into the published artifact.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M5 — Lockstep cap blocks record a 25-line app.css margin that is now 1** (MEDIUM)

**Where:** `tests/test_ui_m3_dark_and_htmx_feedback.py:631`
**Anchor:** `        # The file lands at 575 of 600, `
**What:** Two of the three lockstep app.css cap blocks still say the file "lands at 575 of 600, a 25-line margin" (and `tests/test_ui_m5_create_remove_in_place.py:854` repeats "file lands at 575"); m8 took app.css from 595 to **599** of 600.
**Why it matters:** `implement/scope-exceeded.md` names "app.css at 599 of 600 — 1 line of headroom for the rectify pass" as the second thing a reviewer should check, and the rectifier's natural lookup is exactly these cap blocks — which will tell it there are 25 lines. m8 updated the tokens.css cap block's recorded figure (`tests/test_ui_m7_type_scale.py:465` correctly says 599) and left the two app.css ones stale.
**Proposed fix:** Update both comments to "the file lands at 599 of 600, a 1-line margin (ui-uplift-m8)". Two comment lines, no assertion change; the 600 cap itself is correctly unchanged in all three files.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M6 — Audited artifact prose still puts .discover-abstract at 13px; it ships at 11px** (MEDIUM)

**Where:** `.claude/docs/ui-contrast-table.md:130`
**Anchor:** `` `.discover-abstract` and the `.topic-cat ``
**What:** The m7 size inventory lists `.discover-abstract` under "small 13px", but `app.css:251` sets `font-size: var(--text-meta)` = 11px — moved there by m10's own rectify (`68e622d`, critique M16) without updating this paragraph.
**Why it matters:** m8's synthesis claims "The hand-written prose outside the generated markers was audited and updated … Five regions fixed", and this is one of the five regions it edited (it corrected `.card h2` → `h2` and `.card .display-name` → `.display-name` in the same paragraph) — so the audit ran over the stale sentence and did not catch it, which is the fourth consecutive milestone this prose has gone stale in.
**Proposed fix:** Move `.discover-abstract` from the "small 13px" list to the "meta 11px" list at `.claude/docs/ui-contrast-table.md:126-127`, alongside `th`, `.status-badge` and `.status-badge__remediation`.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M7 — Roadmap links.code anchors are stale after the app.css/tokens.css rewrite** (MEDIUM)

**Where:** `plans/ui-uplift/roadmap.yaml:435`
**Anchor:** `      code: ["server/frontend/static/app`
**What:** I resolved all 39 line-anchored `links.code` refs against the working tree; m8's rewrite (app.css 595→599 with ~29 lines deleted and ~5 added; tokens.css 198→278) invalidated most of them. Named examples: `ui-uplift-m11` "Author the four empty states" → `app.css:71` is now `label {` (`.empty` is at :68) and `index.html:86` is inside a Jinja comment (the empty-state row is :99); `ui-uplift-m7` → `tokens.css:154-169` now points at m8's `--rule-meta` DECORATIVE block rather than the type scale; `ui-uplift-m15` → `app.css:509-533` is the dark pill literals, not the in-flight block (now :513-537); `ui-uplift-m17` → `app.css:575-578` is a comment, not `::view-transition-*` (:579-582); `ui-uplift-m8`'s own `app.css:50-56` starts on a blank line.
**Why it matters:** These anchors are what the next milestone's researcher opens first, and the m8 research synthesis already records the roadmap dropping authored design three milestones running; a mis-anchored `links.code` is the same class of misdirection.
**Proposed fix:** Re-anchor via `/roadmap`, **not** Phase 4 — `plans/` is the roadmap command's tree under the one-writer rule, so the rectifier must not edit it. Record this as a `/roadmap` follow-up. A durable fix is to replace line ranges with symbol or selector anchors (e.g. `app.css#.empty`) so an edit above them cannot rot them.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M8 — Nothing guards that the block ladder actually applies between adjacent blocks** (MEDIUM)

**Where:** `server/frontend/static/app.css:60`
**Anchor:** `main > :where(section, div) + :where(sec`
**What:** The ladder uses the adjacent-sibling combinator, so any non-`section`/`div` element inserted as a direct child of `<main>` between two blocks silently removes the rule at that seam. `test_the_block_ladder_uses_the_section_weight` only checks the rule exists and names `--rule-section`; `test_every_block_still_opens_with_its_heading` counts `^<section>`/`^<div>` and would not notice an interposed element.
**Why it matters:** The pattern already exists — `notebook_detail.html:6` is `<nav class="breadcrumb">` as a top-level `main` child, harmless only because it is first — and three pending milestones target this region: `ui-uplift-m12` (reorder the detail page, `depends_on: [ui-uplift-m8]`), `ui-uplift-m20` (a posture lede) and `ui-uplift-m11` (empty states). With `.card` gone the ladder is the sole structural device, so a silently-dropped seam removes the only grouping cue between two blocks.
**Proposed fix:** Either widen the selector to `main > * + :where(section, div)` so an interposed element cannot break the chain, or add a derived guard that parses each template's top-level `main` children and asserts the number of adjacent `(section|div)` → `(section|div)` transitions equals `blocks - 1` per page (1 for index.html, 6 for notebook_detail.html).
**Regression-guard:** The transition-count guard above, which must fail when a `<p>` is interposed between two top-level blocks.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**L1 — .discover-abstract is a fourth --fg-muted consumer, named as three** (LOW)

**Where:** `tests/test_ui_contrast.py:242`
**Anchor:** `    _p(_m, ".discover-meta / .topic-desc`
**What:** `app.css` has four `color: var(--fg-muted)` consumers — `.discover-meta` (:238), `.discover-abstract` (:251), `.topic-description` (:281), `.status-badge__remediation` (:355) — but the registry site string, the `tokens.css` derivation comment and the implement synthesis all enumerate three.
**Why it matters:** `.discover-abstract` grounds on `--bg` exactly like the two named canvas consumers, so the measured pair is covered and no ratio is missing — this is an inventory-naming gap, not a math gap, but the site string is what ships into the published artifact.
**Proposed fix:** Rename the row to `.discover-meta / .discover-abstract / .topic-description --fg-muted` and correct the "two of three consumers" phrasing in `tokens.css:56-62`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**L2 — Truncated assertion message in the --card-bg successor-role guard** (LOW)

**Where:** `tests/test_ui_m8_rule_ladder.py:308`
**Anchor:** `        assert rules, "--card-bg has no c`
**What:** The emptiness guard's message ends mid-sentence: `"--card-bg has no consumers left at all — AC#2 asks for "`.
**Why it matters:** This is the anti-vacuity assertion for the whole class; if it ever fires, the message tells the reader nothing about what AC#2 asks for. Separately, the per-consumer check uses substring matching against `{"th", "input", "tbody tr:hover"}`, so any selector containing the letters `th` (e.g. `.theorem`, `.path`, `.author`) would satisfy it.
**Proposed fix:** Complete the sentence ("…AC#2 asks for a successor role, not for the token to be orphaned") and match consumer leaves exactly rather than by substring.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L3 — Artifact observation list is source-ordered 1, 2, 4, 6, 5, 3** (LOW)

**Where:** `.claude/docs/ui-contrast-table.md:281`
**Anchor:** `6. **Two of the rule ladder's three rung`
**What:** The "Known non-blocking observations" list carries source numbers in the order 1, 2, 4, 6, 5, 3 after m8 inserted its observation 6 mid-list.
**Why it matters:** Markdown renumbers ordered lists on render, so the rendered numbers will not match the source numbers that `implement/synthesis.md` cross-references ("observations 2 and 4", "New observation 6"), making the cross-references unresolvable for a reader of the published page.
**Proposed fix:** Reorder the list items to match their numbers, or drop the explicit numbering and cross-reference by title.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

## What was done well

- **The published ratios are real.** I re-derived the OKLCH→OKLab→linear-sRGB→WCAG chain independently from the Ottosson and CSS Color 4 specs without touching `tests/_ui_color.py`, and every hand-typed figure in `tokens.css` and `app.css` — 3.3123 / 3.6762 / 3.4054 / 3.3580, 2.5332 / 2.6766 / 2.3251 / 2.2428, 1.9596 / 1.9591, the 70% row 2.2192 / 2.2856, 7.0176, 7.7039, 3.0401 → 2.9533, and the three dark grey re-grounds 9.7962 / 7.4339 / 12.5532 — reproduces exactly against the repo helper. My continuous-math implementation lands ~0.01 lower throughout because the repo quantizes to the 8-bit hex a browser paints, which is the more defensible convention and is documented as such. Only M1 is unsourced.
- **The AC#1 guard is genuinely comment-proof.** Both templates carry `class="card"` inside Jinja comments documenting the removal, and `test_no_template_carries_the_card_class` strips `{# … #}` before scanning, so the comments would make it *fail*, not pass. I re-introduced a real `class="card"` into the stripped markup and the guard caught it. The fragment-builder half closes the second emitter that the template check cannot see.
- **`TestGradingIsMeasuredNotAsserted` measures.** It calls `contrast_ratio` on resolved hexes rather than asserting a string, and it asserts in *both* directions — the section rung clears 3:1 and the tinted rungs are genuinely under it, so a tint creeping back over the bar (which would mean the ladder had collapsed onto one weight while still claiming to be graded) fails loudly. Its only defect is the missing ground in H1.
- **The `--rule-` allow-list entry was added with its own dead-entry guard.** `test_the_non_colour_allow_list_has_no_dead_entries` requires every prefix to match a live token, so the m7 `--text-*` trap the research flagged was hit and properly closed rather than papered over with a broad "skip non-colours" predicate.
- **The `.discover-candidate` exemption holds under inspection.** `server/routes/notebooks.py:731` emits `<li class="discover-candidate">` inside `<ul class="discover-list" role="list">` with a per-item `<h3 class="discover-title">` — and the explicit `role="list"` is what preserves list semantics under `list-style: none` in Safari/VoiceOver, so "an AT announces it from the element" is true rather than assumed.
- **`--fg-muted` was re-solved against its real ground and given a guard the registry floor cannot provide.** `test_fg_muted_meets_its_own_stated_target_on_its_real_ground` gates the token's own 7.00:1 AAA derivation, which the 4.5 registry rows never would — closing m10's critique M6 exactly as recorded. The refusal to re-solve dark *down* to 7.00 is argued rather than defaulted.
- **The gate baseline is exactly as stated.** I reproduced 8 failures — 6 × `test_latexml_sandbox.py`, 1 × `test_arxiv_fetch.py::test_win32_bat_invoked_via_perl`, 1 × `test_cite_neighbors_wired` — with zero new failures and `ruff check .` clean. I confirmed the last one is local state, not a flake: `var/arxmcp/index/kuzu/` exists but is empty, so `graph_status` returns `unavailable` where the test expects `absent`.
- **Axes 1, 3, 4, 5 and 7 are verified clean.** No `server/tools.py`, `server/prompts.py` or handler bytes moved, so cache byte-stability and MCP spec compliance are untouched; the template diff is element-name and comment churn only, with no `| safe`, no new attributes and no script change; `tokens.css` and `app.css` remain explicitly pinned by `tests/test_wheel_packaging.py:222,231` and neither sheet contains `@import`, `url(`, `@font-face` or any URL, so local-first holds; `pyproject.toml`, `uv.lock` and requirements are untouched, so no-fork holds.
- **The line-budget decision was made first and argued.** The `tokens.css` 200→290 raise records its merits at the assertion, m10's precedent against a fourth `app.css` raise was followed, and the ladder's rationale lives once in `tokens.css` rather than being repeated at each of the four rule sites — which is why `app.css` landed at 599 rather than needing its own raise.
- **Every one of the four named guards was fixed to its original intent, not deleted.** `test_card_h2_is_edited_not_shadowed` now checks both that the size sits on the winning rule and that nothing outranks it, so the m7 shadowing bug cannot be re-admitted by dropping to a bare-`h2` match.

Severity counts: C0 H2 M8 L3

## Recommended rectification order

H1, M1, M3, M2, M5, M6, M4, L1, L2, L3, M8, M7, H2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
