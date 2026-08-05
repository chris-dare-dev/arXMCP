# Critique (merged) — ui-uplift-m8

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic, milestone-frontend-ux
**Commit range:** 590acd52577d295fead21b202769623eb75b5f4f..60e7aa0ec9361cb78a641d306cfa1ebe6745b2d5
**Diff stats:** 20 files, 2934 LOC (2617 insertions / 317 deletions); the `feat` commit `0834f95` alone is 11 files, 1385 LOC (1068 / 317)
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H2, H2->H3, M1->M7, M2->M8, M3->M9, M4->M10, M5->M11, M6->M12, M7->M13, M8->M14, L1->L4, L2->L5, L3->L6
> - `milestone-frontend-ux` (frontend.md): H1->H4, M1->M15, M2->M16, M3->M17, L1->L7, L2->L8

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The signature move lands: `.card` is genuinely gone, the
ladder is graded correctly, and — the thing I came to break — the conditional
SC 1.4.11 exemption **holds at every shipped site**, because every boundary
nothing else carries takes `--rule-section` at full weight. I re-derived all
fourteen claimed ratios by an independent OKLab path and every one agrees to
four decimals, including the artifact's own 3.129 headline. The defect is one
step over: the registry retired two `--border on tbody tr:hover` rows on the
stated ground that "no FULL-WEIGHT rule is drawn against the row-hover ground
any more", and `thead th` still draws one — at 3.0401:1, the tightest gated
pair in the product and tighter than the number the artifact publishes.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

Every ratio m8 hand-typed into `tokens.css` and `app.css` reproduces to four decimals against an independent OKLCH→sRGB→WCAG implementation I wrote from the Oklab and CSS Color 4 specs, with one exception (M1), so the milestone's core exposure — manufactured contrast numbers — is largely clean. The load-bearing defect is an inventory one: `--rule-section` still renders against the `tbody tr:hover` ground via the same commit's own `thead th` rule, m8 retired that registry row on the stated ground that "no FULL-WEIGHT rule is drawn against the row-hover ground any more", and the retired pair (3.0401:1) is the registry's true tightest gated pair — so the published Headline now names a looser pair and the artifact's "clears the bar on every ground" claim is unbacked. Nothing fails a gate, the suite is at the exact 8-failure baseline with zero new failures, and ruff is clean.

### milestone-frontend-ux — SHIP-WITH-FIXES

SHIP-WITH-FIXES. The primitive really is gone, the ladder is coherent, and the
decorative exemption — the one judgement the contrast gate cannot make and this
critic can — **holds at all three tinted sites on inspection**: every one has a
genuine second, non-rule cue. The milestone's weakness is not the ladder but what
it declined to rank with it: nine top-level boundaries all take the same top rung,
so the authored `<section>`-vs-`<div>` distinction renders in zero channels and
the notebook detail page becomes a longer undifferentiated column than before.

## Executive summary — milestone-adversary-critic

- [HIGH] The two retired `--border on tbody tr:hover` rows still render: `thead th` carries `--rule-section`, so hovering the first data row puts full-weight `--border` against the hover tint at **3.0401** light / **3.0804** dark. Both are tighter than the published "tightest gated pair … 3.129:1", and the sweep lost its narrowest margin — the exact "nothing fails loudly" hole this milestone closed for `--fg-muted`.
- [MEDIUM] The conditional exemption is the milestone's whole legal posture and **nothing pins which selectors may take a tinted rung**; `TestGradingIsMeasuredNotAsserted` measures ratios only, so a future site where the tint IS the sole cue ships silently.
- [MEDIUM] `.discover-abstract` is a **fourth** `--fg-muted` consumer (`app.css:251`); `tokens.css`, the registry row name and the artifact all enumerate three.
- [MEDIUM] The artifact's m7-sizes paragraph — which m8 edited and claims to have audited — states `.discover-abstract` is 13px (it is `--text-meta`, 11px) and `.discover-title` inherits body 16px (it is `--text-section`, 20px).
- [MEDIUM] Light `input`/`textarea` keep `background: #fff`, so the two renamed `--card-bg` "control ground" rows over-register in light mode and the light `--fg on #fff` pair they absorbed now renders nowhere.
- [MEDIUM] Two of the three lockstep app.css cap comments still read "the file lands at 575 of 600, a 25-line margin". It is **599 of 600, a 1-line margin** — and that comment is what the next milestone reads to decide whether it has room.
- [MEDIUM] `dl.meta` is the weakest exemption: its inter-row whitespace (14.5px) is *smaller* than intra-`dd` line spacing (19.5px), and the Parse-status `dd` carries a 76-char wrapping hint — so whitespace does not carry the grouping there.
- **Diff-size auto-finding deliberately NOT filed.** `state.json` carries `allow_large_diff: true` (the m6/m7/m10 precedent). Arithmetic stated so the omission is auditable: 1385 changed lines in the `feat` commit against a ~450 threshold (3.1x), 1191 authored / 194 generated, 11 files of ~14. The "no partial-but-coherent commit" argument survives challenge — see "What was done well".

## Executive summary — milestone-arxmcp-critic

- [HIGH] `--rule-section` renders on the row-hover ground at **3.0401:1** — the registry's tightest gated pair — and m8 retired that row on a premise its own `thead th { border-block-end: var(--rule-section) }` contradicts; the published Headline now claims 3.129:1.
- [HIGH] Diff is 1385 product/test LOC against a ~450 threshold (3.1×); `implement/scope-exceeded.md` discloses it honestly and the atomicity argument holds.
- [MEDIUM] `app.css:149` publishes **1.1081:1** for the light `th` fill-alone separation; no pair in the stylesheet measures that — the real value is **1.0281**, stated by the same file 27 lines later.
- [MEDIUM] `TestSectioningElementDecision` pins block *counts*, not the per-site `<section>`/`<div>` decisions its failure message claims to pin — proved by swapping both index.html sites, which still passes.
- [MEDIUM] `test_the_ladder_is_horizontal_only` ignores the four-sided `border:` shorthand, so a box primitive can return on structure and pass all four AC#1 guards — proved by mutation.
- [MEDIUM] `--rule-meta`'s SC 1.4.11 exemption argues the dt/dd *pairing* survives, but the rung draws the entry-to-entry boundary, not that pairing.
- [MEDIUM] Two lockstep cap blocks still record "the file lands at 575 of 600, a 25-line margin"; app.css is at 599/600 — the rectify pass has 1 line, and those blocks are where it will look.
- [MEDIUM] The artifact prose paragraph m8 explicitly audited still lists `.discover-abstract` at 13px; `app.css:251` ships it at `--text-meta` = 11px.

## Executive summary — milestone-frontend-ux

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

**H1 — Retired hover rows still render; artifact's tightest pair is wrong** (HIGH)

**Where:** `tests/test_ui_contrast.py:371`
**Anchor:** `# -- light --border's real binding groun`
**What:** The block retires both `--border on tbody tr:hover` rows because "no FULL-WEIGHT rule is drawn against the row-hover ground any more — the row rule dropped to `--rule-row`", but `thead th { border-block-end: var(--rule-section) }` (`app.css:151`) is full weight and sits directly on the boundary of the first `tbody` row, so hovering that row puts `--border` against the hover tint at **3.0401:1** (light) and **3.0804:1** (dark).
**Why it matters:** Those are the tightest gated pairs in the entire sweep — tighter than the `3.129:1` the generated headline publishes as "Tightest gated pair" — so the artifact ships a false number, and the pair closest to the SC 1.4.11 floor is no longer gated at all, which is precisely the silent-regression class ("passes every row while missing its own derivation") that this milestone congratulates itself for closing on `--fg-muted`.
**Proposed fix:** Restore the two rows with a corrected reason: `_p(_m, "--rule-section under thead, over the tbody tr:hover tint", "--border", ROW_HOVER, NONTEXT)`. Replace the retirement paragraph's second bullet — the true statement is that the *per-row* full-weight rule is gone, not that the ground has no full-weight rule; `thead th` retains one on row 1 of both tables. Regenerate the artifact (`python -m tests.test_ui_contrast --update`) so the headline picks up 3.040:1.
**Regression-guard:** Extend `test_ui_m8_rule_ladder.py::TestGradingIsMeasuredNotAsserted::test_the_section_rung_clears_sc_1411_on_every_ground` to iterate `("--bg", "--card-bg", ROW_HOVER)` rather than the two token grounds, asserting `>= 3.0` for each — that fails today at 3.0401 only if the tint moves, which is the point.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage / repo-gate compliance

**H2 — Retired row-hover rule pair is the registry's tightest, and still renders** (HIGH)

**Where:** `tests/test_ui_contrast.py:378`
**Anchor:** `#      * no FULL-WEIGHT rule is drawn ag`
**What:** m8 retired the two `--border on tbody tr:hover` registry rows on the stated ground that "no FULL-WEIGHT rule is drawn against the row-hover ground any more — the row rule dropped to `--rule-row`", but the same commit adds `thead th { border-block-end: var(--rule-section) }` (`app.css:151`), and `--rule-section` *is* `1px solid var(--border)` — under `border-collapse: collapse` that collapsed border is the boundary directly above the first `tbody` row, so it renders against the hover tint whenever that row is hovered.
**Why it matters:** Measured with the repo's own helper, `--border` on `ROW_HOVER` is **3.0401:1** light / 3.0804:1 dark — tighter than the 3.1292:1 pair the regenerated Headline now names as "Tightest gated pair", so the published artifact understates the console's real SC 1.4.11 margin, the pair is gated by nothing, and `tokens.css:142`'s "Clears SC 1.4.11 on every ground it is drawn against" plus the artifact's observation-6 "clears the bar on every ground" are both unbacked; this is the partial-inventory failure the module docstring names as how three AA failures shipped.
**Proposed fix:** Re-register both rows under the ladder's name — `_p(_m, "--rule-section under thead, over the tbody tr:hover tint", "--border", ROW_HOVER, NONTEXT)` — and replace the retirement comment with the corrected reason (the `th` fill row was renamed, the hover row was not retired). Extend `tests/test_ui_m8_rule_ladder.py:241`'s ground loop to include `ROW_HOVER` so the guard's name `..._on_every_ground` becomes true. Regenerate with `python -m tests.test_ui_contrast --update`; the Headline will revert to naming the hover pair.
**Regression-guard:** Add `test_every_rule_token_site_has_a_registry_row` in `tests/test_ui_contrast.py`, modelled on the existing `test_every_faded_css_rule_has_a_registry_row`: derive each `border-*: var(--rule-*)` selector from `app.css` and assert a `PAIRS` row exists for every ground that selector renders against. No such derived guard exists today, which is why the hover ground went missing by hand.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**H3 — Implementation diff is 3.1x the dispatch threshold** (HIGH)

**Where:** no specific file
**What:** The 11 product/test files carry 1068 insertions / 317 deletions = 1385 changed lines against the brief's ~450-LOC threshold; the full range including milestone notes is 20 files / 2934 LOC.
**Why it matters:** A diff this size exceeds what a Phase-3 critic can review line-by-line, which is the standing reason the threshold exists.
**Proposed fix:** No code change. `implement/scope-exceeded.md` already records the real numbers, the 1191-authored / 194-generated split, and the argument that deleting a CSS primitive has no partial-but-coherent commit (nine markup sites, the rule sheet, the token sheet, four named guards, the BAN-R2 gate and the registry must move together or the suite is red). I verified all three claims and they hold; the expected Phase-4 disposition is "acknowledged, record complete", not a rewrite.
**Regression-guard:** None — this is a process finding, and the required disclosure artifact is present.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**H4 — Nine identical top boundaries; the section/div rank renders nowhere** (HIGH)

**Where:** `server/frontend/static/app.css:60`
**Anchor:** `main > :where(section, div) + :where(sec`
**What:** One rule serves all nine top-level boundaries at the same weight, rhythm and inline bleed, so the milestone's per-site `<section>` (focal content region) vs `<div>` (job form) decision has no rendered, semantic or navigational consequence, and the two focal regions are ranked exactly like the six forms.
**Why it matters:** On notebook detail — seven of the nine blocks — a reader gets no signal that "Papers in this notebook" is the point of the page while "Upload ar5iv HTML" is a tool, and because the boundary grew from `.card`'s 3rem (1rem padding + 1rem margin + 1rem padding, plus a box) to 4rem (2rem margin + 2rem padding, one hairline), the corpus moved roughly 96px further down a page where the discovery already measured the papers table at y=1823–2343; the deleted card at least drew a container edge, so this is the "undifferentiated column" outcome the roadmap warned about, arriving through rhythm rather than through missing type.
**Proposed fix:** Give the ladder a second top-level step rather than a second `.lede`, which is UPL-5's. Add a `main > section` treatment that the six `<div>`s do not get — e.g. `main > section > h2 { font-size: var(--text-title) }` reusing the existing token, or a `padding-block-start: 3rem` on `main > :where(section) + …` so the two content regions open with visibly more air than a form does. Either is a few lines, needs no new token, and makes the D2 table's own claim ("the page's focal content region") true in the one channel a reader uses. **Do not reach for the discovery's own answer here** — collapsing the five mutation forms into a native `<details>` "Manage" region below the corpus is triangulated across three discovery briefs but is explicitly owned by `ui-uplift-m12`, whose summary already names the "measured 1823px scroll" this milestone lengthens. So the fix wanted from m8 is an interim *ranking* device, not the reorder; and whichever is chosen, record the deferral at the rule in `app.css:60` the way every other deferral in this stylesheet is recorded, so the next reader does not read the uniformity as unfinished.
**Regression-guard:** Extend `tests/test_ui_m8_rule_ladder.py` with a test asserting that at least one declaration distinguishes `main > section` from `main > div` — i.e. that the D2 decision has a rendered consequence — and pin the count of top-level `<section>` elements per template so a later edit cannot flatten them back.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

**M1 — The conditional exemption has no derived site guard** (MEDIUM)

**Where:** `tests/test_ui_m8_rule_ladder.py:235`
**Anchor:** `class TestGradingIsMeasuredNotAsserted:`
**What:** The class name promises the grading is measured rather than asserted, and it does measure the ratios — but the load-bearing half of the SC 1.4.11 argument is the per-site condition ("only if nothing depends on them to perceive a group"), and nothing pins the set of selectors permitted to consume `--rule-row` / `--rule-meta`.
**Why it matters:** The exemption is conditional by the implementer's own framing; a later milestone adding `border-block-end: var(--rule-row)` to a surface where the tint IS the sole cue would ship a sub-3:1 structural boundary with a green suite and an EXEMPT registry row already in place to cover it — the audit is prose, so it cannot go stale loudly.
**Proposed fix:** Mirror the pattern already used two classes away (`TestCardBgSuccessorRole.EXPECTED_CONSUMERS`) and the radius guard's `allowed_exceptions`: pin a dict `TINTED_RUNG_SITES = {"tbody td": "<tr> semantics + column alignment", ".discover-candidate": "<li> in ul[role=list] + per-item <h3> + 1.5rem padding", "dl.meta dt": "...", "dl.meta dd": "..."}`, regex every rule declaring `var(--rule-row|--rule-meta)` out of `APP_CSS_NO_COMMENTS`, and fail on any selector not in the dict — so adding a site forces re-doing the audit.
**Regression-guard:** `test_ui_m8_rule_ladder.py::TestGradingIsMeasuredNotAsserted::test_every_tinted_rung_site_was_audited`.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**M2 — `.discover-abstract` is a fourth `--fg-muted` consumer, enumerated nowhere** (MEDIUM)

**Where:** `tests/test_ui_contrast.py:242`
**Anchor:** `    _p(_m, ".discover-meta / .topic-desc`
**What:** `app.css:251` sets `color: var(--fg-muted)` on `.discover-abstract`, but the registry row name, the `tokens.css` `--fg-muted` comment ("the third consumer, `.status-badge__remediation`") and the artifact's `--fg-muted` paragraph all enumerate exactly three consumers and omit it.
**Why it matters:** No ratio moves — `.discover-abstract` grounds on `--bg` like the other two, so 7.0176/7.7040 already covers it — but the document's own stated failure mode is "a rendered pair that is missing", and this is the milestone that made "a row named for a selector that no longer exists is the registry rotting in place" its discipline; the inverse rot is the same defect. It also renders at `--text-meta` (11px), the smallest text in the product, which is where an enumeration miss matters most.
**Proposed fix:** Rename the row to `".discover-meta / .discover-abstract / .topic-description --fg-muted"`, and add `.discover-abstract` to the consumer list in `tokens.css` (the `GROUND — --bg` paragraph) and to the artifact's `--fg-muted` "Its ground moved" paragraph. Three string edits.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M3 — The artifact's m7-sizes paragraph is false on two counts after m8 edited it** (MEDIUM)

**Where:** `.claude/docs/ui-contrast-table.md:126`
**Anchor:** `Sizes under the m7 scale, for the record`
**What:** The paragraph lists `.discover-abstract` under "small 13px" — `app.css:251` puts it on `var(--text-meta)` (11px) — and says "body 16px (which `.discover-title` inherits, carrying its hierarchy on `font-weight: 600` rather than a size step)", while `app.css:231` gives `.discover-title` `font-size: var(--text-section)` (20px).
**Why it matters:** m8's synthesis claims this exact region was "audited and updated" as one of five stale prose regions fixed, and the diff shows m8 editing this very sentence to strip `.card ` prefixes — so the audit ran over two false statements and left them, in the document the repo treats as the published record of what renders at what size. This is the fifth consecutive milestone (m6, m7, m7-rectify, m10, m8) in which hand-written prose outside the generated markers went stale.
**Proposed fix:** Move `.discover-abstract` from the "small 13px" list to the "meta 11px" list, and move `.discover-title` from the "body 16px" clause to the "section 20px" clause alongside `h2`. Both drifted in m10's rectify pass, not in m8 — but m8 edited the sentence.
**Regression-guard:** optional; consider extending `test_no_ratio_is_typed_outside_a_generated_region`'s sibling to derive the size lists from `app.css` rather than trusting prose.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M4 — Light input/textarea are `#fff`, so two renamed `--card-bg` rows over-register** (MEDIUM)

**Where:** `tests/test_ui_contrast.py:189`
**Anchor:** `    _p(_m, "th / input / textarea text on`
**What:** The row is registered for both modes and its comment says it "absorbs the old light 'typed text on #fff' / 'th text on #f0f0f0' literal rows, both of which now reference the token" — but only `th` moved; `app.css:86` and `app.css:108` keep `background: #fff` on light `input` and `textarea`, and only the dark block overrides to `var(--card-bg)`. The sibling row at `:204` repeats the claim ("only a control whose own fill is `--card-bg` — input/textarea/th — reads against this ground").
**Why it matters:** In light mode the row registers a pair that does not render, and the pair that *does* render (`--fg` on `#fff`, 16.9512:1) was dropped from the sweep with it — over-registration and under-registration in a single edit, both of which the artifact's Method section names as the same class of error. The milestone's own Deferred list states plainly that light inputs stay on `#fff`, so the two artifacts contradict each other inside one commit.
**Proposed fix:** Split the row: keep `th / input / textarea text on --card-bg [control ground]` for `dark` only, and add `_p("light", "th text on --card-bg [control ground]", "--fg", "--card-bg", TEXT)` plus `_p("light", "input/textarea typed text on #fff", "--fg", WHITE, TEXT)`. Narrow the `:204` focus-ring row's comment the same way (light input/textarea rings sit on `#fff`, and `outline-offset: 2px` puts the ring on the page ground regardless). Regenerate the artifact.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M5 — app.css cap comments still say "575 of 600, a 25-line margin"; it is 599 of 600** (MEDIUM)

**Where:** `tests/test_ui_m3_dark_and_htmx_feedback.py:631`
**Anchor:** `        # The file lands at 575 of 600, `
**What:** m8 grew `app.css` 595 → 599, but the raise-history blocks that the three lockstep cap tests carry were not updated: `test_ui_m3_dark_and_htmx_feedback.py:631` still reads "The file lands at 575 of 600, a 25-line margin: deliberately more than the 2 lines m7 left itself and had to rectify", and `test_ui_m5_create_remove_in_place.py:854` still reads "file lands at 575". `test_ui_m7_type_scale.py:447` additionally still calls it "app.css's 480-line cap".
**Why it matters:** These comment blocks exist precisely so a future milestone can decide whether to raise on the merits, and they now assert 24 lines of headroom that do not exist. The m8 synthesis itself flags "the rectify pass has 1 line to work with" — the number is known and simply was not propagated to the place a rectifier will read. m10's rectify already had to trim comments to fit under this cap once.
**Proposed fix:** Update both "lands at 575" sentences to "lands at 599 of 600 after `ui-uplift-m8` — 1 line of headroom; the next milestone that needs room must raise deliberately, and the split hatch is spent", and fix `test_ui_m7_type_scale.py:447`'s stale "480-line cap" to 600. Note also, for the record, that the cap discipline was only nominally held: `app.css` grew 4 lines while `tokens.css` grew 80 and took a 200 → 290 raise, so the pressure moved rather than being resisted — the tokens.css raise is well-argued, but the "app.css NOT raised, m10's precedent followed" framing overstates what was withstood.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift / repo-gate compliance

**M6 — `dl.meta`'s exemption: whitespace is inverted and `<dl>` semantics are unverified under `display: grid`** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:153`
**Anchor:** `  --rule-meta: 1px dotted color-mix(in `
**What:** The `--rule-meta` exemption claims "`<dl>` semantics and a two-column grid carry the dt/dd pairing, so deleting the rule changes no grouping". Measured from the shipped rules: `dl.meta dt, dl.meta dd` take `padding-block: 0.25rem` with `gap: 0`, so inter-row glyph separation is ~14.5px, while intra-`dd` line spacing at `--text-small`/1.5 is 19.5px — **whitespace runs the wrong way**, and the Parse-status `dd` (`notebook_detail.html:70`) carries a 76-character hint that will wrap. That leaves the `dt` column and `<dl>` semantics as the only cues, and `dl.meta` sets `display: grid` on the `<dl>` with no `role` counterpart.
**Why it matters:** I judge the exemption to survive — the `dt` in column one is a real, strong second cue, so I am **not** calling this rung load-bearing — but the justification as written names two supports of which one (`<dl>` semantics under a changed `display`) is the same class the repo already had to patch: `notebooks.py:775-777` adds `role="list"` because "`list-style:none` strips the list role in WebKit/VoiceOver (critique M1/M12)". No equivalent check was recorded for `<dl>` + `display: grid`, and no browser saw this page.
**Proposed fix:** Either (a) verify the `<dl>` exposure in WebKit and record the result in the token comment, or (b) apply the repo's own established mitigation and note it, and in either case replace the "two-column grid" claim with the accurate one — the `dt` in column one is the cue, not the whitespace, which is 14.5px against 19.5px. Cheapest honest fix is a comment correction plus a `role` on `dl.meta` if (a) cannot be run.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M7 — app.css publishes a th-separation ratio that matches no pair** (MEDIUM)

**Where:** `server/frontend/static/app.css:149`
**Anchor:** `   leaving the boundary on a fill alone `
**What:** The AC#3 rationale states the header boundary was "carried by a fill at 1.1081 light / 1.0948 dark"; the dark figure is correct (`--card-bg` vs `--bg` = 1.0948) but nothing in the stylesheet measures 1.1081 — `--card-bg` vs `--bg` light is **1.0281** and the retired `#f0f0f0` vs `--bg` is 1.0778.
**Why it matters:** A hand-typed contrast number with no source is the exact defect `tests/test_ui_contrast.py`'s docstring cites as precedent ("a comment in app.css came to state a ratio that was ~20% wrong"), and this file states the correct 1.0281 for the same surface 27 lines later, so the stylesheet now contradicts itself about its own AC#3 justification.
**Proposed fix:** Change `1.1081 light` to `1.0281 light` at `app.css:149`, and correct the same figure where `implement/synthesis.md` repeats it. The AC#3 argument gets stronger, not weaker — a 1.0281 separation is a worse boundary than 1.1081, so no decision changes.
**Regression-guard:** Optional — extend `test_no_ratio_is_typed_outside_a_generated_region` (currently scoped to the artifact) to also scan `app.css`/`tokens.css` comments and require every 4-decimal ratio to reproduce against `_ui_color.contrast_ratio`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M8 — Section/div guard pins counts, not the per-site decisions it claims** (MEDIUM)

**Where:** `tests/test_ui_m8_rule_ladder.py:352`
**Anchor:** `        sections = len(_re.findall(r"^<s`
**What:** `test_block_element_split_is_as_decided` asserts `(sections, sections + divs) == (want_sections, want_blocks)`, so it constrains only how many of each element exist; I swapped index.html's Create block to `<section>` and its Existing-notebooks block to `<div>` and the assertion still yields `(1, 2)` and passes.
**Why it matters:** The failure message says "The split is a recorded per-site judgement (implement/synthesis.md), not a default — changing it means re-deciding it", which the check does not enforce; D2 is described in the implement synthesis as the milestone's most judgement-heavy call, and `ui-uplift-m12` (`depends_on: [ui-uplift-m8]`) is an explicit detail-page reorder that will touch exactly these blocks.
**Proposed fix:** Pin the ordered element sequence rather than the counts, e.g. assert `_re.findall(r"^<(section|div)>", markup, flags=_re.M) == ["div", "section"]` for index.html and `["section", "div", "div", "div", "div", "div", "section"]` for notebook_detail.html, keyed to the synthesis table's nine rows.
**Regression-guard:** The rewritten assertion itself — it fails on the swap above, which the current one does not.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M9 — Horizontal-only guard ignores the border shorthand, so the box can return** (MEDIUM)

**Where:** `tests/test_ui_m8_rule_ladder.py:184`
**Anchor:** `                r"border-(?:left|right|i`
**What:** The guard matches only `border-left` / `border-right` / `border-inline-start` / `border-inline-end`; appending `main > section { border: 1px solid var(--border); }` to the comment-stripped `app.css` leaves the guard finding zero vertical edges and passing, even though that declaration draws all four sides.
**Why it matters:** Its own message is "vertical edges found … the box was deleted on purpose", and AC#1's four guards are the only defence of "no `.card` primitive remains" — a square, differently-named box using the shorthand passes `test_no_stylesheet_declares_a_card_rule` (not named `.card`), `test_structure_carries_no_border_radius` (no radius), `test_card_bg_is_no_longer_a_panel_ground` (no `--card-bg`) and this one, so the primitive can return under another name with every AC#1 guard green.
**Proposed fix:** Also scan `border:` shorthands and fail any whose selector is not a control, reusing the `is_control` predicate already written at `tests/test_ui_m8_rule_ladder.py:124`. The five existing shorthands (`input`, `textarea`, `button.button-quiet`, `.status-badge`, the spinner's `border: 2px solid currentColor`) are all controls or the enumerated circle, so the tightened guard passes today.
**Regression-guard:** The tightened guard, verified against the `main > section { border: 1px solid var(--border) }` mutation above, which must fail.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M10 — rule-meta's SC 1.4.11 exemption argues a boundary the rung does not draw** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:153`
**Anchor:** `  --rule-meta: 1px dotted color-mix(in o`
**What:** The exemption reads "whose dt/dd pairing is carried by `<dl>` semantics and by a two-column grid: delete the rule and the grouping is unchanged, which is the test this exemption has to pass" — but `dl.meta dt, dl.meta dd { border-block-end: var(--rule-meta) }` draws a horizontal line under each row, separating metadata entry N from entry N+1; it never draws the dt↔dd boundary, which is a vertical edge the ladder forbids by design.
**Why it matters:** CLAUDE.md §4.9 makes a published exemption a trust claim, and this one passes its stated test by answering about a boundary the rung does not render; the boundary it *does* render sits in a `gap: 0` grid with only `padding-block: 0.25rem` per side, so the argument that something else carries it is never actually made. `--rule-row`'s `tbody td` leg leans on "column alignment", which is also weaker for row separation than for column separation.
**Proposed fix:** Restate the exemption against the real boundary — entry-to-entry grouping is carried by the `font-weight: 500` dt occupying column 1 of every row plus `<dl>` dt/dd semantics — or give `dl.meta` a row `gap` so proximity carries it and the rule is genuinely ornamental. The same edit should sharpen `_META_WHY` in `tests/test_ui_contrast.py`, which carries the identical wording into the published artifact.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M11 — Lockstep cap blocks record a 25-line app.css margin that is now 1** (MEDIUM)

**Where:** `tests/test_ui_m3_dark_and_htmx_feedback.py:631`
**Anchor:** `        # The file lands at 575 of 600, `
**What:** Two of the three lockstep app.css cap blocks still say the file "lands at 575 of 600, a 25-line margin" (and `tests/test_ui_m5_create_remove_in_place.py:854` repeats "file lands at 575"); m8 took app.css from 595 to **599** of 600.
**Why it matters:** `implement/scope-exceeded.md` names "app.css at 599 of 600 — 1 line of headroom for the rectify pass" as the second thing a reviewer should check, and the rectifier's natural lookup is exactly these cap blocks — which will tell it there are 25 lines. m8 updated the tokens.css cap block's recorded figure (`tests/test_ui_m7_type_scale.py:465` correctly says 599) and left the two app.css ones stale.
**Proposed fix:** Update both comments to "the file lands at 599 of 600, a 1-line margin (ui-uplift-m8)". Two comment lines, no assertion change; the 600 cap itself is correctly unchanged in all three files.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M12 — Audited artifact prose still puts .discover-abstract at 13px; it ships at 11px** (MEDIUM)

**Where:** `.claude/docs/ui-contrast-table.md:130`
**Anchor:** `` `.discover-abstract` and the `.topic-cat ``
**What:** The m7 size inventory lists `.discover-abstract` under "small 13px", but `app.css:251` sets `font-size: var(--text-meta)` = 11px — moved there by m10's own rectify (`68e622d`, critique M16) without updating this paragraph.
**Why it matters:** m8's synthesis claims "The hand-written prose outside the generated markers was audited and updated … Five regions fixed", and this is one of the five regions it edited (it corrected `.card h2` → `h2` and `.card .display-name` → `.display-name` in the same paragraph) — so the audit ran over the stale sentence and did not catch it, which is the fourth consecutive milestone this prose has gone stale in.
**Proposed fix:** Move `.discover-abstract` from the "small 13px" list to the "meta 11px" list at `.claude/docs/ui-contrast-table.md:126-127`, alongside `th`, `.status-badge` and `.status-badge__remediation`.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**M13 — Roadmap links.code anchors are stale after the app.css/tokens.css rewrite** (MEDIUM)

**Where:** `plans/ui-uplift/roadmap.yaml:435`
**Anchor:** `      code: ["server/frontend/static/app`
**What:** I resolved all 39 line-anchored `links.code` refs against the working tree; m8's rewrite (app.css 595→599 with ~29 lines deleted and ~5 added; tokens.css 198→278) invalidated most of them. Named examples: `ui-uplift-m11` "Author the four empty states" → `app.css:71` is now `label {` (`.empty` is at :68) and `index.html:86` is inside a Jinja comment (the empty-state row is :99); `ui-uplift-m7` → `tokens.css:154-169` now points at m8's `--rule-meta` DECORATIVE block rather than the type scale; `ui-uplift-m15` → `app.css:509-533` is the dark pill literals, not the in-flight block (now :513-537); `ui-uplift-m17` → `app.css:575-578` is a comment, not `::view-transition-*` (:579-582); `ui-uplift-m8`'s own `app.css:50-56` starts on a blank line.
**Why it matters:** These anchors are what the next milestone's researcher opens first, and the m8 research synthesis already records the roadmap dropping authored design three milestones running; a mis-anchored `links.code` is the same class of misdirection.
**Proposed fix:** Re-anchor via `/roadmap`, **not** Phase 4 — `plans/` is the roadmap command's tree under the one-writer rule, so the rectifier must not edit it. Record this as a `/roadmap` follow-up. A durable fix is to replace line ranges with symbol or selector anchors (e.g. `app.css#.empty`) so an edit above them cannot rot them.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M14 — Nothing guards that the block ladder actually applies between adjacent blocks** (MEDIUM)

**Where:** `server/frontend/static/app.css:60`
**Anchor:** `main > :where(section, div) + :where(sec`
**What:** The ladder uses the adjacent-sibling combinator, so any non-`section`/`div` element inserted as a direct child of `<main>` between two blocks silently removes the rule at that seam. `test_the_block_ladder_uses_the_section_weight` only checks the rule exists and names `--rule-section`; `test_every_block_still_opens_with_its_heading` counts `^<section>`/`^<div>` and would not notice an interposed element.
**Why it matters:** The pattern already exists — `notebook_detail.html:6` is `<nav class="breadcrumb">` as a top-level `main` child, harmless only because it is first — and three pending milestones target this region: `ui-uplift-m12` (reorder the detail page, `depends_on: [ui-uplift-m8]`), `ui-uplift-m20` (a posture lede) and `ui-uplift-m11` (empty states). With `.card` gone the ladder is the sole structural device, so a silently-dropped seam removes the only grouping cue between two blocks.
**Proposed fix:** Either widen the selector to `main > * + :where(section, div)` so an interposed element cannot break the chain, or add a derived guard that parses each template's top-level `main` children and asserts the number of adjacent `(section|div)` → `(section|div)` transitions equals `blocks - 1` per page (1 for index.html, 6 for notebook_detail.html).
**Regression-guard:** The transition-count guard above, which must fail when a `<p>` is interposed between two top-level blocks.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M15 — Section and row rungs differ only by tint at a shared 1px solid** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:146`
**Anchor:** `  --rule-row: 1px solid color-mix(in okl`
**What:** The two rungs a reader must actually tell apart are adjacent in every table (`thead th` at 3.3123:1 directly above `tbody td` at 2.5332:1) and are identical in width and style, so the entire grading signal is a single lightness step on a 1px line.
**Why it matters:** The research rejected grading by thickness on the grounds that two rungs an operator cannot tell apart is not a ladder — but at 1px a line's perceived weight essentially *is* its lightness, so the chosen axis inherits the same failure mode, and if the step does not read as rank it reads as inconsistent anti-aliasing, which is worse than one weight would have been.
**Proposed fix:** No code change until this is seen. Render `/ui/notebooks/<slug>` at 1440x900 and at 200% zoom in both colour schemes and answer one question: does the rule under `<thead>` read as heavier than the rules under the data rows? If it does, close this and record the check. If it does not, the cheapest repair is to let the top rung differ in more than tint — the `thead th` fill and micro-caps already carry that boundary (four other cues), so the honest move is to *drop* `tbody td` to no rule at all inside a table that already has column alignment, rather than to keep a rung nobody can rank.
**Regression-guard:** Optional for MEDIUM; if the render check is done, record the outcome in `.claude/docs/ui-contrast-table.md` beside the existing EXEMPT rows so a later reader sees a verdict rather than a ratio.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy / experiential distinctiveness

**M16 — Zero-paper state renders a full-weight table header over nothing** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:321`
**Anchor:** `  {% if not papers %}`
**What:** The papers `<table>` always renders because it is the htmx swap target, so with zero papers the section shows a centred italic message followed by a filled, uppercase, micro-caps header row carrying the ladder's *strongest* rule beneath it and an empty `<tbody>`.
**Why it matters:** AC#3 deliberately promoted `thead th` to `--rule-section`, which makes the header the single heaviest horizontal element on the page at exactly the moment there is no data under it, and with the card box gone there is no longer a container edge to explain why an empty header is floating there — a first-time operator reads it as a load failure rather than as an empty notebook. **Scoped deliberately:** `ui-uplift-m11` (UPL-21) owns *authoring* the four empty states with a cause and an action, and that gap is not flagged here; what is flagged is the composition regression m8 itself introduced by raising the rule above an empty body.
**Proposed fix:** Mirror what `index.html` already does correctly — move the empty message into the tbody as a spanning placeholder row (`<tr id="papers-empty"><td colspan="4" class="empty">…</td></tr>`) and drop the separate `<p class="empty">`, so the header always has a body under it and the two pages solve the same problem the same way. The add-paper and upload forms both `hx-swap="beforeend"` into `#papers-tbody`, so they need the same `document.getElementById('papers-empty')?.remove()` hook `index.html:38` already carries on its create form. This is the structural half only and composes with m11 rather than pre-empting it — m11 replaces the copy inside whichever element ends up holding it.
**Regression-guard:** A test asserting `notebook_detail.html` renders no `<tbody>` that can be empty while its `<thead>` is present — or, more simply, that both templates use the placeholder-row idiom, pinned by the presence of an `id` ending `-empty` inside each `<tbody>`.
**Source critic:** milestone-frontend-ux
**Source axis:** Empty states

**M17 — The radius guard checks one selector per rule and calls `<main>` a control** (MEDIUM)

**Where:** `tests/test_ui_m8_rule_ladder.py:123`
**Anchor:** `            leaf = selector.split(",")[-`
**What:** `test_structure_carries_no_border_radius` reduces every rule to the last selector in its comma list before classifying it, and its `is_control` regex admits `[tabindex]` and `:focus-visible` — but the product's only `[tabindex]` is `<main id="main" tabindex="-1">`, so `app.css:428`'s `border-radius: 4px` lands on the page's top-level structural container whenever the skip link moves focus there.
**Why it matters:** This is the guard that makes AC#1's headline geometry claim falsifiable, and it has two holes at once: a radius reintroduced on a structural selector grouped anywhere but last in a comma list is invisible to it (`section, button { border-radius: 8px }` passes, since the `6px` check is a literal string match), and the one structural element that *does* take a radius today is classified as a control by regex — so the milestone's "radius 0 on structure, 4px on controls" reads as true while the largest structural box in the product rounds on keyboard focus.
**Proposed fix:** Iterate every selector in the comma list, not `[-1]`; classify each independently; and drop `[tabindex]` from the control pattern, replacing it with an explicit named exception if `main:focus-visible` is meant to keep its radius. If it is not meant to, `main:focus-visible { border-radius: 0 }` is a one-line fix that makes the thesis literally true. Replace the `"6px" not in found.values()` literal with a check that no non-control selector carries any non-zero radius.
**Regression-guard:** `tests/test_ui_m8_rule_ladder.py::TestCardPrimitiveIsGone::test_structure_carries_no_border_radius` — add a negative case asserting the guard *rejects* a synthetic `section, button { border-radius: 8px }` input, so the comma-list hole cannot silently reopen.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**L1 — The block-ladder rule's specificity is (0,0,1), not the (0,0,0) claimed twice** (LOW)

**Where:** `server/frontend/static/app.css:57`
**Anchor:** `   sheet reads as a spreadsheet" failure`
**What:** The comment says ":where() pins this at (0,0,0)", and `implement/synthesis.md:163` repeats it. `main > :where(section, div) + :where(section, div)` contains the type selector `main`, which contributes (0,0,1); `:where()` contributes zero, so the rule's specificity is (0,0,1).
**Why it matters:** No live conflict — nothing else sets `border-block-start` or `margin-block-start` on those elements — but the stated reasoning ("so deleting `.card` cannot re-open the specificity of the five compounds it dropped to (0,0,1)") is arithmetic that a future author will rely on, and it is off by the one component that matters to the comparison being drawn.
**Proposed fix:** "`:where()` holds both compounds at zero, so the rule's whole specificity is the `main` type selector's (0,0,1)". One-line edit in each of the two places.
**Regression-guard:** n/a.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L2 — AC#3's "before" measurement mixes a pre-m8 light ratio with a post-m8 dark one** (LOW)

**Where:** `.claude/notes/milestones/ui-uplift-m8/implement/synthesis.md:62`
**Anchor:** `**1.1081:1** (light) / **1.0948:1** (dar`
**What:** The sentence describes the *pre-m8* header boundary as "a fill at 1.1081:1 (light) / 1.0948:1 (dark)". Re-derived independently: 1.1081 is `#f0f0f0` against `--card-bg`, which is the correct pre-m8 light figure; 1.0948 is `--card-bg` against `--bg`, which is the **post**-m8 dark figure (pre-m8 dark `th` and the card ground were both `var(--card-bg)`, i.e. 1.0000:1).
**Why it matters:** Only a notes file, and `app.css:176`'s shipped comment carries the correct post-m8 light figure (1.0281, verified). But the pair reads as one measurement of one state and is two measurements of two states.
**Proposed fix:** State the dark pre-m8 figure as 1.0000:1 (identical surfaces) or drop the dark half.
**Regression-guard:** n/a.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L3 — The panel-ground guard matches on a 2-char substring and only the last selector line** (LOW)

**Where:** `tests/test_ui_m8_rule_ladder.py:307`
**Anchor:** `        rules = _re.findall(r"([^{}]+)\`
**What:** `test_card_bg_is_no_longer_a_panel_ground` reduces each matched selector to `selector.strip().splitlines()[-1].strip()` and accepts it if any of `{"th", "input", "tbody tr:hover"}` appears as a substring. Two consequences: a panel ground added on an *earlier* line of a comma-joined selector list is never inspected, and any selector containing the two characters `th` (e.g. `.thumbnail`, `.month`, `.path-display`) passes.
**Why it matters:** This is the guard that enforces "a new panel use re-opens the primitive under another name" — the milestone's own stated defence against `.card` returning by a different route. Both holes are silent.
**Proposed fix:** Split the captured selector on `,`, strip each part, and match against a compiled anchored pattern per role (`^th$`, `^input\b`, `^textarea\b`, `^tbody tr:hover$`) rather than substring membership; assert every comma-part, not just the last line.
**Regression-guard:** optional.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**L4 — .discover-abstract is a fourth --fg-muted consumer, named as three** (LOW)

**Where:** `tests/test_ui_contrast.py:242`
**Anchor:** `    _p(_m, ".discover-meta / .topic-desc`
**What:** `app.css` has four `color: var(--fg-muted)` consumers — `.discover-meta` (:238), `.discover-abstract` (:251), `.topic-description` (:281), `.status-badge__remediation` (:355) — but the registry site string, the `tokens.css` derivation comment and the implement synthesis all enumerate three.
**Why it matters:** `.discover-abstract` grounds on `--bg` exactly like the two named canvas consumers, so the measured pair is covered and no ratio is missing — this is an inventory-naming gap, not a math gap, but the site string is what ships into the published artifact.
**Proposed fix:** Rename the row to `.discover-meta / .discover-abstract / .topic-description --fg-muted` and correct the "two of three consumers" phrasing in `tokens.css:56-62`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**L5 — Truncated assertion message in the --card-bg successor-role guard** (LOW)

**Where:** `tests/test_ui_m8_rule_ladder.py:308`
**Anchor:** `        assert rules, "--card-bg has no c`
**What:** The emptiness guard's message ends mid-sentence: `"--card-bg has no consumers left at all — AC#2 asks for "`.
**Why it matters:** This is the anti-vacuity assertion for the whole class; if it ever fires, the message tells the reader nothing about what AC#2 asks for. Separately, the per-consumer check uses substring matching against `{"th", "input", "tbody tr:hover"}`, so any selector containing the letters `th` (e.g. `.theorem`, `.path`, `.author`) would satisfy it.
**Proposed fix:** Complete the sentence ("…AC#2 asks for a successor role, not for the token to be orphaned") and match consumer leaves exactly rather than by substring.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L6 — Artifact observation list is source-ordered 1, 2, 4, 6, 5, 3** (LOW)

**Where:** `.claude/docs/ui-contrast-table.md:281`
**Anchor:** `6. **Two of the rule ladder's three rung`
**What:** The "Known non-blocking observations" list carries source numbers in the order 1, 2, 4, 6, 5, 3 after m8 inserted its observation 6 mid-list.
**Why it matters:** Markdown renumbers ordered lists on render, so the rendered numbers will not match the source numbers that `implement/synthesis.md` cross-references ("observations 2 and 4", "New observation 6"), making the cross-references unresolvable for a reader of the published page.
**Proposed fix:** Reorder the list items to match their numbers, or drop the explicit numbering and cross-reference by title.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity

**L7 — Ladder terminators are inconsistent across the three rungs** (LOW)

**Where:** `server/frontend/static/app.css:229`
**Anchor:** `.discover-candidate:last-child { border-`
**What:** The `--rule-row` list suppresses its final rule as a deliberate terminator, while the last `tbody td` (same rung) and the last `dl.meta` row (`--rule-meta`) both keep theirs.
**Why it matters:** In a milestone whose entire deliverable is that rule weight is consistent and meaningful, two sites on the same rung ending differently is exactly the "inconsistency bug" reading the thesis is trying to avoid.
**Proposed fix:** Pick one convention and state it at the token. A closing rule on a table and a `<dl>` is defensible (it bounds the block before the next control); the discover list's suppression is defensible too (it is the last thing in its panel). Whichever is chosen, record the rule in `tokens.css` beside `--rule-row` so the next site does not have to guess.
**Regression-guard:** Optional for LOW.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**L8 — `.discover-title` is an `<h3>` at the `<h2>` size step** (LOW)

**Where:** `server/frontend/static/app.css:231`
**Anchor:** `.discover-title { margin: 0; font-size: `
**What:** `.discover-title` sets `--text-section`, the same 20px step the bare `h2` rule uses, so each candidate's `<h3>` renders at its parent block's heading size and differs only by weight (600 vs the UA bold 700).
**Why it matters:** The Discover panel is the one surface with three heading levels, and it is the surface where a reader most needs to see that a candidate is subordinate to the block — this milestone's premise is that m7's type scale and the ladder now carry hierarchy together, and here the scale contributes nothing.
**Proposed fix:** Drop `.discover-title` to `--text-body` and let weight plus the `--rule-row` boundary mark the item, which restores a real step between the block heading and the item heading without minting a token. Introduced by ui-uplift-m10, not by m8 — flagged here because m8 is the milestone asserting the two systems cooperate.
**Regression-guard:** Optional for LOW.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

## What was done well

### From milestone-adversary-critic

- **The D1 exemption is genuinely earned, not asserted.** I audited all seven ladder use sites independently and every boundary that nothing else carries — the nine top-level blocks, `thead`, `header`, `footer` — takes `--rule-section` at full weight, clearing 3:1 on every ground it is drawn against. The tinted rungs go only to `<tr>`, `<li>` and `dl` rows, each of which carries independent element semantics *and* an independent layout cue. The self-refutation the dispatch warned about is avoided: the milestone does not claim page structure is decorative, it claims sub-structure *ranking* inside already-delimited groups is — which is the correct reading of SC 1.4.11.
- **Every claimed ratio survives an independent re-derivation.** I implemented OKLCH→sRGB (Bottosson matrices), oklab `color-mix`, sRGB alpha compositing and WCAG luminance from scratch without importing `tests/_ui_color.py`, and reproduced all fourteen numbers in the D1 table plus `7.0176` / `7.7040` / `6.8230` / `1.0281` / `3.0730` — and the artifact's own `3.129:1` headline to four decimals, which is what let me trust the `3.0401` counter-measurement in H1.
- **The `.discover-candidate` exemption's weakest leg was already patched.** Its `<li>` cue would have been false in WebKit under `.discover-list { list-style: none }`, but `notebooks.py:778` carries `role="list"` from m10's critique — so the audit's first support actually holds, and I could not break that site.
- **AC#2 ∧ AC#3 on `th` resolved exactly right.** The fill survives (`th { background: var(--card-bg) }`) *and* `thead th` gains `--rule-section`; the light `#f0f0f0` literal is gone, which let the dark redeclaration be deleted as dead code so the two modes can no longer disagree. `test_th_background_is_the_token_in_every_mode` asserts both halves including the negative.
- **All four disturbed guards were fixed to their original intent, never deleted.** `test_card_h2_is_edited_not_shadowed` is the best of them: it keeps m7's "the size must sit on the winning rule" and adds the inverse (nothing outranks the bare `h2`), so the shadowing bug cannot be re-admitted by a future compound.
- **`.card .note` was deleted rather than re-homed, with evidence.** `class="note"` is emitted by zero templates and zero fragment builders — I confirmed it — so the rule, its two registry rows and its pinned dark remap were all defending markup that never existed. Removing a dead guard is the harder and correct call.
- **The `--fg-muted` re-solve closes m10's M6 exactly as recorded**, and `test_fg_muted_meets_its_own_stated_target_on_its_real_ground` is the right shape of guard: the registry gates at 4.5, so only a target-aware assertion could catch a token that stops meeting its own derivation. Refusing to re-solve dark *downward* for symmetry is the right call and is argued in the token.
- **The scope overrun was disclosed accurately and the atomicity argument holds.** `scope-exceeded.md`'s 1068/317/11 matches `git diff --shortstat` byte-for-byte, and the authored/generated split (1191/194, 14%) is honest rather than the 2.4x understatement a prior implementer produced. I looked for a coherent partial commit and could not construct one: any subset leaves four named guards red and the console half-styled. The file count stayed inside its bound.
- **Baseline verified independently and exactly.** Full suite at `60e7aa0`: precisely the 8 predicted environment-bound failures (6 × `test_latexml_sandbox`, 1 × `test_win32_bat_invoked_via_perl`, 1 × `test_cite_neighbors_wired`), zero new. `ruff check .` clean. All five commits `%G? = G` with the mandated `Co-Authored-By: Claude Opus 5` trailer; no `plans/*/roadmap.yaml` touched; no external write performed (`git push` declared only).

### From milestone-arxmcp-critic

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

### From milestone-frontend-ux

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

Severity counts: C0 H4 M17 L8


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **M2, L4** at `tests/test_ui_contrast.py:242-242` (MEDIUM): `.discover-abstract` is a fourth `--fg-muted` consumer, enumerated nowhere; .discover-abstract is a fourth --fg-muted consumer, named as three
- **L1, H4, M14** at `server/frontend/static/app.css:57-60` (HIGH): The block-ladder rule's specificity is (0,0,1), not the (0,0,0) claimed twice; Nine identical top boundaries; the section/div rank renders nowhere; Nothing guards that the block ladder actually applies between adjacent blocks
- **L7, L8** at `server/frontend/static/app.css:229-231` (LOW): Ladder terminators are inconsistent across the three rungs; `.discover-title` is an `<h3>` at the `<h2>` size step
- **L3, L5** at `tests/test_ui_m8_rule_ladder.py:307-308` (LOW): The panel-ground guard matches on a 2-char substring and only the last selector line; Truncated assertion message in the --card-bg successor-role guard
- **M3, M12** at `.claude/docs/ui-contrast-table.md:126-130` (MEDIUM): The artifact's m7-sizes paragraph is false on two counts after m8 edited it; Audited artifact prose still puts .discover-abstract at 13px; it ships at 11px
- **M5, M11** at `tests/test_ui_m3_dark_and_htmx_feedback.py:631-631` (MEDIUM): app.css cap comments still say "575 of 600, a 25-line margin"; it is 599 of 600; Lockstep cap blocks record a 25-line app.css margin that is now 1
- **M6, M10** at `server/frontend/static/tokens.css:153-153` (MEDIUM): `dl.meta`'s exemption: whitespace is inverted and `<dl>` semantics are unverified under `display: grid`; rule-meta's SC 1.4.11 exemption argues a boundary the rung does not draw

## Recommended rectification order

H1, H2, H3, H4, M4, M2, M3, M5, M1, M6, M7, M9, M8, M11, M12, M10, M14, M13, M16, M17, M15, L1, L3, L2, L4, L5, L6, L8, L7

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
