# Critique — ui-uplift-m10 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 216aff062f78d44d314b7b33f72d6b836192e0ee..9444a4cf0cb6b17eae8d0e7b2793032eea0e05ec
**Diff stats:** 14 files, 1974 LOC (1841 insertions, 133 deletions; `server/` + `tests/` alone are 274 LOC — 224/50)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The two owner decisions survive adversarial re-derivation: I re-computed every
`--fg-muted` pair through an independent OKLCH→sRGB→WCAG path and got 7.015 /
7.037 on `--card-bg` and 5.448:1 as the tightest pill (dark `--warn`), matching
the implementer's claims to three decimals, and the 8 new registry rows are
exactly the 8 grounds the token renders on — I found no unregistered ground.
The `max-height: 4.5em` clamp is exactly three line boxes for every root font
size, because `body { line-height: 1.5 }` is unitless and nothing in the
`.card → #discover-results → .discover-list → .discover-candidate` chain
overrides it. What is wrong is durability and honesty at the edges: AC#7's
terminal state has no guard, the new list strips list semantics in WebKit, the
abstract truncates with no affordance, and three rationale/citation surfaces
state things the measurements do not support.

## Executive summary

- [HIGH] AC#7's `_KNOWN_UNSTYLED == {}` is the epic's finish line and nothing
  asserts it — both `TestKnownUnstyledDebtIsSelfCleaning` methods iterate the
  dict and pass vacuously on `{}`, so re-populating it fails no test.
- [MEDIUM] `.discover-list { list-style: none }` is the product's first and
  only such rule, on the product's only `<ul>`, with no `role="list"` — WebKit
  drops list semantics, so VoiceOver stops announcing "list, N items" on the
  one surface built for per-candidate operator judgment.
- [MEDIUM] D2 truncates the abstract with `overflow: hidden` and ships no
  affordance: no ellipsis, no fade, no scroll, no reveal. A sighted operator
  reading three clipped lines has no signal that 800–1500 characters were cut.
- [MEDIUM] `--fg-muted`'s "so nothing gets lighter" rationale is false against
  measurement. The eleven greys span 4.886:1–11.467:1, not a band around 7.00;
  `#444` (9.471) and dark `#c9d1d9` (11.467) lose ~26–39% contrast on
  migration, and even the cited `#555` (7.249) gets lighter, not darker.
- [MEDIUM] The cap assertion message in two of three sibling files now reads
  "over the 600-line cap (revised in ui-uplift-m6 from 400 …)". m6 revised
  400→480; m7's rectify 480→520; m10 520→600. The comment *history* blocks are
  accurate — only the failure string misattributes.
- [MEDIUM] `implement/synthesis.md` cites `app.css:224-228` for a rule at
  282-286 and `app.css:281-298` for one at 316-322 — off by 35–58 lines, i.e.
  landing a Phase-4 reader in an unrelated rule.
- [LOW] The synthesis frontmatter names worktree shas `0edc12a` / `263bdba`
  that are not ancestors of `main`; the landed commits are `b742b59` /
  `55545d7`.
- [LOW] `.status-badge__remediation` — operator prose — stays in the `--mono`
  voice inherited from the pill, one rule away from m10 arguing at length that
  `.topic-description` "stays in the SANS voice — it is operator prose".

**Diff-size auto-finding deliberately NOT filed, so the omission is
auditable.** The whole-diff churn is 1974 LOC, well over the 400-LOC cliff, but
`state.json` carries `"allow_large_diff": true` (an orchestrator-recorded
waiver, the same one m6 and m7 ran under). The arithmetic behind it: 1974 total
= 1700 LOC of `.claude/notes` research/synthesis artifacts + 274 LOC of
`server/` + `tests/`; of the 192-line `ui-contrast-table.md` change, 168 lines
are the generated table's row renumbering. Authored production+test surface is
274 LOC across 8 files.

**Gate baseline verified independently, not taken on trust.** I ran the full
suite at HEAD (`.venv/bin/python -m pytest -q --tb=no -p no:warnings`): **8
failures, all pre-existing and environment-bound** — 6 × `sandbox-exec` latexml
containment/wiring, 1 × `WindowsPath` on darwin, and
`test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` (the
network-flaky HuggingFace download the implementer observed passing). Zero new
failures. The implementer's "7-failure observation of an 8-failure baseline"
reading is correct.

## Findings

**H1 — AC#7's empty `_KNOWN_UNSTYLED` has no guard; both self-cleaning tests are vacuous** (HIGH)

**Where:** `tests/test_ui_class_css_coverage.py:119`
**Anchor:** `_KNOWN_UNSTYLED: dict[str, str] = {}`
**What:** AC#7 requires the deferral list to be EMPTY and the docstring calls empty "the intended terminal state", but no test asserts it — `test_known_unstyled_entries_are_still_actually_emitted` (`:550`) and `test_known_unstyled_entries_are_still_actually_unstyled` (`:586`) both comprehend over the dict and therefore pass vacuously on `{}`, and `_offenders` consumes it as a silent exemption set.
**Why it matters:** The epic's stated finish line is "BAN-R2's AC1 binds unconditionally from then on"; I verified empirically that adding one entry to that dict makes a genuinely unstyled emitted class produce zero offenders and zero failing tests, and this repo has no PRs, no reviewer and no CI (§4.1), so the one-line re-opening has no gate at all — which is exactly the escape-hatch risk ui-uplift-m9's finding M2 raised and m10 answered only by rewording an error string.
**Proposed fix:** Add one assertion mirroring the three cap tests' "deliberate raise" discipline, e.g. in `TestKnownUnstyledDebtIsSelfCleaning`: `assert _KNOWN_UNSTYLED == {}, "empty since ui-uplift-m10 — re-populating re-opens BAN-R2 debt this epic closed; if you genuinely need a dated deferral, edit THIS assertion in the same commit and name the owning milestone"`. That makes re-population a two-site, deliberate act instead of a one-line silence, at the cost of 4 lines and no new test surface.
**Regression-guard:** `tests/test_ui_class_css_coverage.py::TestKnownUnstyledDebtIsSelfCleaning::test_known_unstyled_is_empty` — fails the moment the dict is non-empty.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M1 — `list-style: none` with no `role="list"` strips list semantics in WebKit** (MEDIUM)

**Where:** `server/frontend/static/app.css:209`
**Anchor:** `.discover-list { list-style: none; margi`
**What:** This is the product's first and only `list-style` declaration, applied to its only `<ul>` (`server/routes/notebooks.py:748`), and WebKit removes the `list` / `listitem` accessibility roles from a list whose markers are removed — so VoiceOver stops announcing "list, 10 items" and loses item-by-item list navigation.
**Why it matters:** `#discover-results` is the one surface presenting external content for a per-candidate Add decision, the fragment already carries deliberate `aria-live="polite" aria-atomic="true"` work, and this diff silently trades a screen-reader affordance for a visual one on exactly that surface — the same class of regression the m7 `<code>`-in-`<h2>` cascade was.
**Proposed fix:** Add `role="list"` to the `<ul>` in `_discover_results_fragment` — `f'<ul class="discover-list" role="list">{"".join(rows)}</ul>'`. That is the canonical fix (it restores the role WebKit dropped without changing any other engine) and is a 14-character markup edit; note it does mean the milestone's "shipped no markup change" claim in `implement/synthesis.md:242` no longer holds and should be amended in the same pass. A pure-CSS alternative exists (`list-style-type: ""` keeps the marker box) but is less well supported than `role="list"`.
**Regression-guard:** Assert in the existing UI fragment tests that `_discover_results_fragment` emits `<ul` and `role="list"` together whenever `.discover-list` carries `list-style: none` in `app.css` — a derived pairing check, so a future removal of one without the other fails.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M2 — the abstract clamp hides 800–1500 chars with no affordance and no reveal** (MEDIUM)

**Where:** `server/frontend/static/app.css:231`
**Anchor:** `.discover-abstract { margin: 0.25rem 0 0`
**What:** `max-height: 4.5em; overflow: hidden` clips the abstract at exactly three lines with no ellipsis, no fade, no scrollbar and no expand control, so the third line simply stops mid-sentence and nothing distinguishes a truncated abstract from a short one.
**Why it matters:** The comment's own premise is that `abstract_head` is the FULL abstract (800–1500 chars), so on essentially every candidate the operator is shown a fraction of the evidence with no signal that a fraction is what they are seeing — and this milestone's headline argument for refusing a relevance line (AC#4) is operational honesty under CLAUDE.md §4.9, which cuts the same way here: the sighted-mouse operator gets neither the screen-reader path nor the copy-paste path the comment relies on as mitigation.
**Proposed fix:** Cheapest honest fix is one token: `overflow-y: auto` instead of `overflow: hidden`, which both signals the overflow (scrollbar/overscroll) and reveals it, costs zero lines and zero JS, and is Baseline widely available. If a scroll region inside a page is unwanted, the alternative within the line budget is a `mask-image: linear-gradient(#000 70%, transparent)` fade on the same rule, which signals truncation even though it does not reveal. Either way, record which was chosen and why in the existing comment, since the current comment argues the *cut position* is honest without addressing whether the *hiding* is.
**Regression-guard:** Optional (MEDIUM). If taken: assert `.discover-abstract`'s rule contains a truncation affordance token (`overflow-y: auto` or `mask-image`) alongside `max-height`, so a future edit cannot silently revert to a bare `overflow: hidden`.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M3 — "so nothing gets lighter" is false against the greys it names** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:60`
**Anchor:** `     already occupied (#555 on the light c`
**What:** The 7.00:1 target is justified as "the measured band the greys it replaces already occupied (#555 on the light card is 7.25:1), so nothing gets lighter"; measured independently, the eleven legacy greys span **4.886:1 to 11.467:1** on their real grounds, and migrating them onto `--fg-muted` (7.015 light / 7.037 dark) makes `#444` (9.471→7.015), dark `#c9d1d9` (11.467→7.037) and dark `#b3b9c0` (8.948→7.037) substantially lighter — as does the cited `#555` itself (7.249→7.015).
**Why it matters:** This is the load-bearing derivation rationale for the milestone's highest-risk artefact, repeated verbatim in `implement/synthesis.md:162-165` and in softened form in the published artifact (`ui-contrast-table.md:175-179`), and it is precisely the "comment states a ratio that does not hold" defect m6's own critique caught — a future milestone doing the deferred grey migration will read this as clearance it does not have.
**Proposed fix:** Replace the parenthetical with the measured range and the honest consequence, e.g. "the eleven greys it exists to replace span 4.89:1–11.47:1 on their own grounds; 7.00 sits inside that range but is *lighter* than `#444` (9.47), dark `#c9d1d9` (11.47) and dark `#b3b9c0` (8.95), so the deferred migration is a contrast trade at those three sites and must be measured, not assumed." Mirror the correction in `implement/synthesis.md` and in the artifact's non-generated paragraph. No token value changes.
**Regression-guard:** Optional (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M4 — the 600-line cap's failure message attributes the raise to m6** (MEDIUM)

**Where:** `tests/test_ui_m3_dark_and_htmx_feedback.py:628`
**Anchor:** `            f"(revised in ui-uplift-m6 from `
**What:** The assertion string now reads "over the 600-line cap (revised in ui-uplift-m6 from 400 for the OKLCH token family + --dur-* tokens …)", but git shows m6 (`8ee611e`) revised 400→480, m7's rectify (`f4b6bb1`) revised 480→520, and m10 (`b742b59`) revised 520→600 for eight class rules — the same string is wrong the same way at `tests/test_ui_m4_in_place_add_paper.py:729`.
**Why it matters:** The comment blocks above the assertion record the history correctly and were left byte-unchanged (which the synthesis rightly calls out as the m7-rectify lesson), but the *message* is what a future agent reads at the moment the cap trips, and it hands them a provenance and a rationale belonging to a different milestone — this is the third raise in three milestones, so the audit trail on why the cap moves is the only thing making it a discipline rather than a formality.
**Proposed fix:** Two-line edit in each of the two files: "over the 600-line cap (400→480 in ui-uplift-m6 for the OKLCH token family + --dur-* tokens; 480→520 in ui-uplift-m7's rectify post tokens-split; 520→600 in ui-uplift-m10 for the eight UPL-9 class rules — see the comment above for the merits of each)."
**Regression-guard:** Optional (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M5 — implement synthesis cites app.css lines off by up to 58** (MEDIUM)

**Where:** `.claude/notes/milestones/ui-uplift-m10/implement/synthesis.md:50`
**Anchor:** `existing tabular-nums rule at `app.css:2`
**What:** Three of the synthesis's four `app.css` citations do not resolve in the post-diff tree: the tabular-nums rule is cited at `224-228` and lives at `282-286`; the remediation block is cited at `281-298` (`:87`) and lives at `316-322`; the discover rules are cited at `213-232` (`:25`) and live at `209-231`; D2 is cited at `:232` (`:196`) and lives at `231`. Only the `.topic-*` cite (`241-243`) is correct.
**Why it matters:** `app.css:224-228` in the shipped file is the middle of the `.discover-abstract` rationale comment, not the tabular rule — a Phase-4 rectifier or a future milestone navigating by these lands in unrelated code, and this is the same "a doc authored in the same commit as the code can be stale at birth" defect caught at `verification-contract-m1`.
**Proposed fix:** Re-resolve all four citations against the post-diff tree and correct them in place: `app.css:209-231` (discover rules), `app.css:282-286` (tabular-nums rule), `app.css:316-322` (remediation block), `app.css:231` (D2). `tokens.css:47-66` should read `46-66` — the comment block opens at 46.
**Regression-guard:** Optional (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L1 — synthesis frontmatter names commits unreachable from main** (LOW)

**Where:** `.claude/notes/milestones/ui-uplift-m10/implement/synthesis.md:7`
**Anchor:** `  - "0edc12a feat(server): style Discover`
**What:** The frontmatter `commits:` list and the `Diff size` section (`:331`) name `0edc12a` / `263bdba`, which exist as objects but are not ancestors of `main`; the orchestrator's rebase landed them as `b742b59` / `55545d7`, which is what `state.json.implementation_commits` correctly records.
**Why it matters:** The synthesis is the durable per-milestone evidence artifact, and its own "Branching note" predicts the rebase — so the shas were accurate when written and are wrong now, which is the harder failure to notice later.
**Proposed fix:** Update the two shas in the frontmatter and the one in the `Diff size` heading to the landed values, and note in the Branching section that the rebase completed (the section currently reads as an open instruction to the orchestrator).
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L2 — remediation prose stays in the mono voice one rule from the sans argument** (LOW)

**Where:** `server/frontend/static/app.css:316`
**Anchor:** `.status-badge__remediation {`
**What:** m10 "finishes" this selector with four new declarations and argues explicitly at `app.css:236-240` that `.topic-description` "stays in the SANS voice — it is operator prose", yet the remediation block — full sentences such as "corpus version marker drift" — renders in `--mono` inherited from `.status-badge` and sits in the tabular-nums scope, with no note saying that was considered.
**Why it matters:** Not a defect on its own (the block does name check identifiers and `make` commands, which is a genuine steelman, and the mono inheritance predates m10), but the milestone applied the two-voice discipline to one of its two new prose surfaces and not the other, so the next milestone has no record of which way the precedent runs. Flagging as uncertain rather than asserting the voice is wrong.
**Proposed fix:** Either add one clause to the existing comment recording that the mono voice is deliberate here because the lines carry check names and `make` commands, or set `font-family: -apple-system, system-ui, …`/a sans token on the rule. The comment is the cheaper and probably correct option.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

## What was done well

- **The colour maths holds under an independent re-derivation.** I implemented
  OKLCH→LMS→linear-sRGB→8-bit→WCAG from Bottosson's matrices without touching
  `tests/_ui_color.py` and reproduced every claim: light `--fg-muted` `#51585f`
  at 7.015:1, dark `#9fa4a8` at 7.037:1, and the tightest new pill at 5.448:1
  (dark `--warn`) — the comment's "5.45:1" is exact, not rounded in its favour.
- **The 8 new registry rows are the right 8, and the omissions are right too.**
  Every ground `--fg-muted` renders on is registered: two `--card-bg` rows
  (`.discover-meta`, `.topic-description`, both inside `<section class="card">`
  — verified in `notebook_detail.html:101,155`) and six pill rows. The `ok` pill
  is correctly absent because `_build_remediation_block` returns `""` for it,
  and `--bg` is correctly absent because no consumer sits on the canvas. I
  probed the unregistered `--bg` grounds anyway (6.823 / 7.704) — no hidden
  failure lurking behind the omission.
- **D2's clamp is exact, not approximately exact.** `body { line-height: 1.5 }`
  is unitless and nothing in the ancestor chain overrides it, so 4.5em against
  `--text-small` is three line boxes at *any* root font size (13px → 3 × 19.5px
  = 58.5px = 4.5em). The cut genuinely lands on a boundary, and `* { box-sizing:
  border-box }` with zero padding makes the content-box reading safe.
- **The `_KNOWN_UNSTYLED` closure is real, not cosmetic.** I ran the extractor
  rather than reading it: 17 real emissions, zero offenders with the dict forced
  empty; a class named only inside a CSS comment does *not* satisfy the check
  (comments are stripped before matching, so the new `tokens.css:56` comment
  naming `.topic-description` cannot self-satisfy); and a synthetic new unstyled
  class in `server/routes/` is caught with the new message.
- **AC#4's deliverable is a genuine, recorded absence.** No relevance, score,
  rank or "why this matched" string exists anywhere in `server/frontend/` or
  `server/routes/` — the only hits are the refusal itself. The refusal is
  written into the stylesheet where the next milestone will read it, with the
  three independent reasons (Atom namespace, `sortBy=submittedDate`,
  `DiscoveryCandidate`'s four fields), which is the right place for it.
- **Both m7 derived guards genuinely extend to the new rules.**
  `TestRectifyTabularNumsScope` sees `.discover-meta` as an exact selector
  string in both the mono set and the tabular set (the in-place append, not a
  second rule, is what makes that true), and `TestRectifyCrossFileTokenIntegrity`
  resolves `var(--fg-muted)` against both the light and dark `:root` blocks.
  Neither passes vacuously.
- **The ban list held.** No per-candidate coloured chip (BAN-7 /
  `challenge.md:879`), no state-history strip (UPL-24 / `final-report.md:407`),
  no icon, no card grid — `grep` over the new CSS and the fragment builder finds
  the ban names only in the comments explaining the refusals.
- **The cap raise is lockstepped and the history blocks were not falsified.**
  All three sibling files moved in the same commit; git confirms the recorded
  history (m6 400→480 at `8ee611e`, m7 kept 480, m7-rectify 480→520 at
  `f4b6bb1`) is accurate and byte-unchanged — only the failure *message*
  misattributes (M4). The file lands at 575 of 600, a real 25-line margin.
- **Commit hygiene is clean across all four commits:** `%G?` = `G` on every
  one, `Co-Authored-By: Claude Opus 5` present on every one, conventional
  subjects under 50 chars after the type prefix, no `plans/*/roadmap.yaml`
  touched, and the declared external write (`git push origin main`) was
  declared and NOT performed — `origin/main` is still at `216aff0`.
- **The synthesis's self-reported gaps are unusually honest** and every one I
  checked was accurately characterised: the AC#3 guard gap, the template half of
  BAN-R2, the un-migrated greys, and the 7-vs-8 baseline reading all matched
  what I found independently.

Severity counts: C0 H1 M5 L2

## Recommended rectification order

H1, M1, M2, M3, M4, M5, L1, L2
