# Critique — ui-uplift-m8 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 590acd52577d295fead21b202769623eb75b5f4f..60e7aa0ec9361cb78a641d306cfa1ebe6745b2d5
**Diff stats:** 20 files, 2934 LOC (2617 insertions / 317 deletions); the `feat` commit `0834f95` alone is 11 files, 1385 LOC (1068 / 317)
**Critique format version:** 1.0

## Verdict

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

## Executive summary

- [HIGH] The two retired `--border on tbody tr:hover` rows still render: `thead th` carries `--rule-section`, so hovering the first data row puts full-weight `--border` against the hover tint at **3.0401** light / **3.0804** dark. Both are tighter than the published "tightest gated pair … 3.129:1", and the sweep lost its narrowest margin — the exact "nothing fails loudly" hole this milestone closed for `--fg-muted`.
- [MEDIUM] The conditional exemption is the milestone's whole legal posture and **nothing pins which selectors may take a tinted rung**; `TestGradingIsMeasuredNotAsserted` measures ratios only, so a future site where the tint IS the sole cue ships silently.
- [MEDIUM] `.discover-abstract` is a **fourth** `--fg-muted` consumer (`app.css:251`); `tokens.css`, the registry row name and the artifact all enumerate three.
- [MEDIUM] The artifact's m7-sizes paragraph — which m8 edited and claims to have audited — states `.discover-abstract` is 13px (it is `--text-meta`, 11px) and `.discover-title` inherits body 16px (it is `--text-section`, 20px).
- [MEDIUM] Light `input`/`textarea` keep `background: #fff`, so the two renamed `--card-bg` "control ground" rows over-register in light mode and the light `--fg on #fff` pair they absorbed now renders nowhere.
- [MEDIUM] Two of the three lockstep app.css cap comments still read "the file lands at 575 of 600, a 25-line margin". It is **599 of 600, a 1-line margin** — and that comment is what the next milestone reads to decide whether it has room.
- [MEDIUM] `dl.meta` is the weakest exemption: its inter-row whitespace (14.5px) is *smaller* than intra-`dd` line spacing (19.5px), and the Parse-status `dd` carries a 76-char wrapping hint — so whitespace does not carry the grouping there.
- **Diff-size auto-finding deliberately NOT filed.** `state.json` carries `allow_large_diff: true` (the m6/m7/m10 precedent). Arithmetic stated so the omission is auditable: 1385 changed lines in the `feat` commit against a ~450 threshold (3.1x), 1191 authored / 194 generated, 11 files of ~14. The "no partial-but-coherent commit" argument survives challenge — see "What was done well".

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

## What was done well

- **The D1 exemption is genuinely earned, not asserted.** I audited all seven ladder use sites independently and every boundary that nothing else carries — the nine top-level blocks, `thead`, `header`, `footer` — takes `--rule-section` at full weight, clearing 3:1 on every ground it is drawn against. The tinted rungs go only to `<tr>`, `<li>` and `dl` rows, each of which carries independent element semantics *and* an independent layout cue. The self-refutation the dispatch warned about is avoided: the milestone does not claim page structure is decorative, it claims sub-structure *ranking* inside already-delimited groups is — which is the correct reading of SC 1.4.11.
- **Every claimed ratio survives an independent re-derivation.** I implemented OKLCH→sRGB (Bottosson matrices), oklab `color-mix`, sRGB alpha compositing and WCAG luminance from scratch without importing `tests/_ui_color.py`, and reproduced all fourteen numbers in the D1 table plus `7.0176` / `7.7040` / `6.8230` / `1.0281` / `3.0730` — and the artifact's own `3.129:1` headline to four decimals, which is what let me trust the `3.0401` counter-measurement in H1.
- **The `.discover-candidate` exemption's weakest leg was already patched.** Its `<li>` cue would have been false in WebKit under `.discover-list { list-style: none }`, but `notebooks.py:778` carries `role="list"` from m10's critique — so the audit's first support actually holds, and I could not break that site.
- **AC#2 ∧ AC#3 on `th` resolved exactly right.** The fill survives (`th { background: var(--card-bg) }`) *and* `thead th` gains `--rule-section`; the light `#f0f0f0` literal is gone, which let the dark redeclaration be deleted as dead code so the two modes can no longer disagree. `test_th_background_is_the_token_in_every_mode` asserts both halves including the negative.
- **All four disturbed guards were fixed to their original intent, never deleted.** `test_card_h2_is_edited_not_shadowed` is the best of them: it keeps m7's "the size must sit on the winning rule" and adds the inverse (nothing outranks the bare `h2`), so the shadowing bug cannot be re-admitted by a future compound.
- **`.card .note` was deleted rather than re-homed, with evidence.** `class="note"` is emitted by zero templates and zero fragment builders — I confirmed it — so the rule, its two registry rows and its pinned dark remap were all defending markup that never existed. Removing a dead guard is the harder and correct call.
- **The `--fg-muted` re-solve closes m10's M6 exactly as recorded**, and `test_fg_muted_meets_its_own_stated_target_on_its_real_ground` is the right shape of guard: the registry gates at 4.5, so only a target-aware assertion could catch a token that stops meeting its own derivation. Refusing to re-solve dark *downward* for symmetry is the right call and is argued in the token.
- **The scope overrun was disclosed accurately and the atomicity argument holds.** `scope-exceeded.md`'s 1068/317/11 matches `git diff --shortstat` byte-for-byte, and the authored/generated split (1191/194, 14%) is honest rather than the 2.4x understatement a prior implementer produced. I looked for a coherent partial commit and could not construct one: any subset leaves four named guards red and the console half-styled. The file count stayed inside its bound.
- **Baseline verified independently and exactly.** Full suite at `60e7aa0`: precisely the 8 predicted environment-bound failures (6 × `test_latexml_sandbox`, 1 × `test_win32_bat_invoked_via_perl`, 1 × `test_cite_neighbors_wired`), zero new. `ruff check .` clean. All five commits `%G? = G` with the mandated `Co-Authored-By: Claude Opus 5` trailer; no `plans/*/roadmap.yaml` touched; no external write performed (`git push` declared only).

Severity counts: C0 H1 M6 L3

## Recommended rectification order

H1, M4, M2, M3, M5, M1, M6, L1, L3, L2
