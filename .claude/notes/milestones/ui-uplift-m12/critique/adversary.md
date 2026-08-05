# Critique — ui-uplift-m12 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 6f5cbbc0be184e65a9ba39d4a4199d9b1971879c..75f325595acbfbf8ecf0492be92fe2edda484175
**Diff stats:** 11 files (7 code/test + 4 pipeline artifacts), 1304 LOC changed (848 in the 7 code/test files)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The reorder is correct, the AC#2 open-predicate is provably complete against the store's closed
`running`/`success`/`failed` vocabulary plus the route-synthesised `none`, and the D2-escape
argument holds against every swap on the page. One acceptance criterion is demonstrably unmet:
AC#4's second clause ("no swap silently lands out of view") was fixed for the two template forms
and missed for the third `beforeend` swap into `#papers-tbody`, which the Discover-results
fragment emits from *inside* the disclosure at `server/routes/notebooks.py:752`. The remaining
findings are guard-coverage and record-accuracy gaps, all cheap; the 848-LOC diff exceeds the
400-LOC auto-finding threshold but `state.json` carries `allow_large_diff: true` as at m6/m7/m8/m10,
so that mandatory HIGH is deliberately **not** filed — stated here so the omission is auditable.

## Executive summary

- [HIGH] The Discover-results "Add" button appends to `#papers-tbody` with a bare
  `hx-swap="beforeend"` from inside the disclosure — the exact invisible-success failure AC#4
  names, and the exact fix m12 applied to the other two forms. The synthesis's claim that "the two
  `beforeend` forms are the whole of it" is a false exhaustiveness claim.
- [MEDIUM] AC#1's operative half — the table "visible without scrolling" — has no test and no
  documented verification. Every AC#1 guard is a source-ORDER proxy (`DETAIL.index(a) < index(b)`),
  and the milestone's own thesis is a pixel number (y=1823 of 2343) that was never re-measured.
- [MEDIUM] The summary cue is a page-LOAD snapshot, so after an in-page "Ingest now" the page can
  read `Manage this notebook — ingest success` (or `none`) while a run is live. The synthesis
  records only the harmless direction (stale `running` over a settled body).
- [MEDIUM] All three lockstep cap comments say "the file lands at 635 of 680". `app.css` is **627**
  lines (598 base + 29). The synthesis has 627 right; the three shipped guards do not.
- [MEDIUM] `TestSectioningElementDecision`'s name, docstring, `EXPECTED` comment and three failure
  messages all still say "top-level blocks" about seven blocks of which five are no longer
  top-level (the page has three). I do **not** agree it is a keep-passing update — the structural
  property is genuinely measured by `TestManageDisclosureNesting` — but the guard is now pinned to
  an indentation convention protected only by prose.
- [MEDIUM] The "HARD CONSTRAINT for later milestones — no swap may target the `<details>` or any
  ancestor of it" is recorded in a template comment and guarded by nothing, in a repo with no CI
  and no code review (§4.1). m13 is named in that same comment as the near-miss.
- [LOW] `challenge.md:107` is cited three times (template, synthesis, brief-2) for the cue string;
  the string is at `challenge.md:115-116`. Every other discovery citation in the milestone verifies.
- [LOW] `list-style-position: outside` on `.manage-disclosure > summary` is unexplained; it is
  copied from m10's `.discover-abstract > summary`, whose justification (`overflow: hidden` +
  `max-height` clipping an inside marker) does not transfer.

## Findings

**H1 — Discover-results "Add" appends into a target now above it, with no `show:`** (HIGH)

**Where:** `server/routes/notebooks.py:752`
**Anchor:** `' hx-target="#papers-tbody" hx-swap="be`
**What:** `_discover_results_fragment` emits one `<form … hx-target="#papers-tbody" hx-swap="beforeend">` per candidate, and that fragment is swapped into `#discover-results` **inside** the `<details>` — so after m12's reorder it appends a row into a tbody that now sits above the disclosure, with no `show:` modifier to bring the append point into view.
**Why it matters:** This is precisely AC#4's second clause ("no swap silently lands out of view"): the operator's primary discovery→corpus action succeeds while the screen does not move, and because `#papers-tbody` carries `aria-live` the defect is sighted-only — the same class m12 fixed at `notebook_detail.html:386` and `:416` and stopped one swap short of. The Discover panel is the tallest content on the page (a candidate list with abstracts), so the append point is further off-screen here than for either form that was fixed.
**Proposed fix:** Change the fragment's swap to `hx-swap="beforeend show:#papers-tbody:bottom"` — the same string the two template forms now carry. No test currently pins the bare `hx-swap="beforeend"` string for this fragment (the only two hits are `tests/test_ui_m5_create_remove_in_place.py:391`, which is index.html's `#notebooks-tbody` form, and the already-re-decided m4 assertion), so this is a one-line change. Then extend `TestSwapTargetsStillResolve::test_the_beforeend_swaps_scroll_their_append_point_into_view` to cover the server-rendered fragment as a third case, and correct the synthesis sentence "the two `beforeend` forms are the whole of it".
**Regression-guard:** A new case in `tests/test_ui_m12_corpus_before_machinery.py::TestSwapTargetsStillResolve` that renders `_discover_results_fragment` with one synthetic candidate and asserts every `hx-target="#papers-tbody"` in the *fragment* carries `show:#papers-tbody`; derive the scan from the fragment's output, not from a hard-coded string, so a fourth append site cannot be added silently.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M1 — AC#1's "visible without scrolling" half is never measured or documented** (MEDIUM)

**Where:** `tests/test_ui_m12_corpus_before_machinery.py:156`
**Anchor:** `def test_the_papers_table_precedes_every`
**What:** Every AC#1 guard is a source-ORDER assertion (`DETAIL.index('<tbody id="papers-tbody"') < DETAIL.index(marker)`), which proves the table precedes the forms but says nothing about whether it is reachable without scrolling — the criterion's actual words and the epic's entire justification (a measured y=1823 of a 2343px document).
**Why it matters:** The record section that still leads the page carries an `<h2>`, a display-name `<p>`, a full rename form (label + input + button + `pre.error`), a four-row `<dl class="meta">` and a delete button, under base.html's header — and no post-change y for the papers `<h2>` exists in the template, the synthesis, the scope-exceeded note or any test. The milestone's headline claim ("roughly one viewport") is carried forward from the roadmap summary unverified, so a future regression that grows the masthead cannot be distinguished from the shipped state.
**Proposed fix:** Add a short "measured after" paragraph to `implement/synthesis.md` § AC#1 giving either a browser-measured y for the papers `<h2>` or an explicit derivation from `app.css` + `tokens.css` (header + breadcrumb + record-section box model + the section rung's `2rem + 2rem`), stated against a named viewport height. No browser harness exists in this repo, so a documented derivation is the available form of the "documented verification" the acceptance axis asks for.
**Regression-guard:** Optional at MEDIUM. If a number is recorded, pin the contributing box-model declarations (`header` margin/padding, the section rung's `2rem` pair, `.rename-form` presence) so a later milestone that inflates the masthead has to re-open the recorded figure.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M2 — Summary cue can read `success`/`none` while a run started in-page is live** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:258`
**Anchor:** `<summary>Manage this notebook — ingest `
**What:** The cue renders `latest_run.status` at page LOAD only, while "Ingest now" swaps `#ingest-status` in place — so the sequence *load with `success` (disclosure closed) → expand → Ingest now → collapse* leaves the page reading `Manage this notebook — ingest success` with a run actively polling underneath; the `none` first-run path is identical and more common.
**Why it matters:** AC#2's stated purpose is that the 2s poll "would otherwise poll invisibly for a whole run", and this is the one reachable path where the cue actively asserts that nothing is happening — the failure direction the AC exists to prevent. The synthesis's recorded residual (`synthesis.md:91-93`) documents only the opposite, harmless direction (a stale `running` over a settled body), so the record understates the defect rather than disclosing it.
**Proposed fix:** Cheapest correct v0: amend the recorded residual in both the template's m12 note and `implement/synthesis.md` § AC#3 to state the `success`/`none`-over-live-run direction explicitly. The real fix, if wanted now rather than at m13: have `_ingest_status_fragment` emit an out-of-band `<span id="manage-cue" hx-swap-oob="true">` carrying the same token, and move the cue text into that span — one row, one writer, still no new query.
**Regression-guard:** Optional at MEDIUM. If the OOB fix is taken, assert every branch of `_ingest_status_fragment` emits the `hx-swap-oob` cue span (derive over the branches, do not enumerate them) so a fifth branch cannot ship without it.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M3 — Three lockstep cap comments claim 635 lines; `app.css` is 627** (MEDIUM)

**Where:** `tests/test_ui_m3_dark_and_htmx_feedback.py:648`
**Anchor:** `# The file lands at 635 of 680.`
**What:** `tests/test_ui_m3_dark_and_htmx_feedback.py:648`, `tests/test_ui_m4_in_place_add_paper.py:745` and `tests/test_ui_m5_create_remove_in_place.py:858` all record "635"; `wc -l server/frontend/static/app.css` is 627 (598 at base `6f5cbbc`, +29), which is what `implement/synthesis.md:161` correctly says.
**Why it matters:** The headroom is the whole content of a cap decision — the record says 45 lines of slack when the truth is 53, the largest margin any raise in this track has granted (m10 took 520→600 with the file at 575, i.e. 25). The number a future agent reads when arguing the fifth raise is wrong in the direction that makes this one look tighter than it was. This is the third consecutive occurrence of the same pattern (m7 wrote "471 to ~400" at 478; m8 wrote "575 of 600" at 599), which is why it is worth the 3 lines.
**Proposed fix:** Replace "635" with "627" in all three comments. While there: both assert MESSAGES rebuild the raise chain and both omit m7's 480→520 — `test_ui_m3` reads "m6: 400->480 …; m10: 520->600 …; m12: 600->680" and `test_ui_m4` reads "m6 400->480, then m10 520->600, then m12 600->680". m12 re-published that incomplete chain when it appended its own hop, so insert "m7: 480->520" in both.
**Regression-guard:** Optional at MEDIUM. A derived assertion — parse the integer out of the comment and compare it to the live `line_count` the test already computes — would end this recurrence permanently and costs about four lines in the m3 test.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M4 — `TestSectioningElementDecision` still says "top-level" and is now pinned to indentation** (MEDIUM)

**Where:** `tests/test_ui_m8_rule_ladder.py:371`
**Anchor:** `EXPECTED = {"index.html": (1, 2), "note`
**What:** After m12, five of the seven blocks the `^<(section|div)>` extractor finds are children of `<details>`, not of `main` — the page has three top-level blocks — yet `:370`'s comment ("expected top-level block count"), the class docstring, and the failure messages at `:437`, `:453` and `:473` all still say "top-level blocks", and the guard's ordering is now derived from the five DIVs staying at column 0.
**Why it matters:** Two separate costs. (a) A future failure prints `notebook_detail.html: 2 <section> of 7 top-level blocks`, which is false, and sends the reader looking for a structure that does not exist. (b) Indenting the nested DIVs is the natural thing any agent or formatter would do, and doing it collapses `_blocks()` to `["section", "section"]` and fails the guard with a message naming the wrong cause — the only thing preventing that is a prose paragraph, in a repo with no CI and no code review (§4.1). **I do not agree this is the m8 keep-passing pattern**: the re-decision is transcribed with a per-site reason exactly as m8's own rectify (M8) requires, `EXPECTED` is honestly unchanged at `(2, 7)` because no element decision changed, and the structural property the orchestrator worried about *is* measured — `TestManageDisclosureNesting` asserts all five forms inside the disclosure and the table outside it, and `test_the_page_lands_three_regions_not_seven_blocks` pins `["section", "section", "details"]`. A DIV moving in or out of the disclosure fails those. The defect is that the m8 guard now measures "blocks at column 0" while claiming to measure "top-level blocks", and nothing defends the column-0 premise.
**Proposed fix:** Rename the vocabulary in place — "top-level blocks" → "column-0 blocks (five of which are nested inside the Manage disclosure since m12)" in the docstring, the `:370` comment and the three f-strings — and add one assertion to `TestManageDisclosureNesting` that the five mutation `<div>`s are emitted at column 0, so the premise the m8 guard now rests on is itself pinned rather than only explained.
**Regression-guard:** `tests/test_ui_m12_corpus_before_machinery.py::TestManageDisclosureNesting::test_the_mutation_divs_stay_at_column_zero` — assert `len(re.findall(r"^<div>", DETAIL, re.M)) == 5`, with the failure message naming `TestSectioningElementDecision` as the guard that depends on it.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

**M5 — The "hard constraint for m13" is recorded in a comment and enforced by nothing** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:47`
**Anchor:** `the swapped subtree. HARD CONSTRAINT for`
**What:** The m12 note establishes "no swap may target the `<details>` or any ancestor of it" as the invariant that lets m12 escape `onboarding-uplift-m3` §3 D2's rejection of `<details>`, and names m13 — which moves `aria-live` onto "a stable never-swapped wrapper" — as the near-miss; nothing in the 489-line guard file, or anywhere else, asserts it.
**Why it matters:** I verified the claim holds today (the six `hx-target`s are `#display-name-block`, `#topic-block`, `#discover-results`, `#papers-tbody` ×2 and `#ingest-status` ×2; base.html's `#status-badge` swaps itself inside `<header>`, outside `<main>`), so the escape is real. But if m13 picks the `<details>` or `<main>` as its stable wrapper and swaps it, AC#2's mechanism dies silently — `open` re-renders from the server predicate on every poll and the disclosure snaps to the page-load state every 2s. Under §4.1's no-PR/no-CI posture a comment is not a constraint; the m10 lesson recorded exactly this ("an unconditional binding lasts one line-edit").
**Proposed fix:** Add a guard that scans the rendered detail page for every `hx-target` value and asserts none of them selects the `<details>`, `<main>`, `<body>` or any element containing the disclosure — plus that no element carrying `hx-swap="outerHTML"` is an ancestor of it. Derive the ancestor set from the rendered markup rather than listing ids, so a new target is covered on arrival. About 15 lines.
**Regression-guard:** `tests/test_ui_m12_corpus_before_machinery.py::TestManageDisclosureNesting::test_no_swap_targets_the_disclosure_or_an_ancestor`, with the failure message quoting the m3-D2 history so the next agent reads why before deleting it.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**L1 — `challenge.md:107` cite is wrong; the cue string is at 115-116** (LOW)

**Where:** `server/frontend/templates/notebook_detail.html:223`
**Anchor:** `form "Manage this notebook — ingest runn`
**What:** The cue string `"Manage this notebook — ingest running"` is at `.claude/notes/frontend-uplifts/2026q3-ui-uplift/artifacts/challenge.md:115-116`; line 107 is an Axis-11 distinctiveness sentence about shipping-history ordering. The wrong cite appears in the shipped template, in `implement/synthesis.md:77`, and originates upstream in `research/brief-2.md:106`.
**Why it matters:** Every other discovery citation in this milestone verifies exactly — `art-direction-scout-brief.md:372` (the anatomy), `:434` (BAN-2, 7 cards → 3 regions), `challenge.md:98-104` (the empty-state harm), `final-report.md:393-394` (the v1/UPL-21 pairing) — so the one wrong one is more likely to be trusted, and it sits in a production file where the next agent will follow it.
**Proposed fix:** `challenge.md:107` → `challenge.md:115-116` at all three sites. The label cite `art-direction-scout-brief.md:428-430` is off by one at the tail (the phrase wraps 430-431) and can be widened to `:429-431` in the same pass.
**Regression-guard:** Not required at LOW.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L2 — `list-style-position: outside` is unexplained and its m10 justification does not transfer** (LOW)

**Where:** `server/frontend/static/app.css:93`
**Anchor:** `.manage-disclosure > summary { margin-bl`
**What:** The 23-line comment above this rule justifies the class scoping, the marker's preservation, the AC#5 refusal and the `--text-section` choice, but never `list-style-position: outside`; it is copied from `.discover-abstract > summary` (`:284`), where it is required because that rule sets `overflow: hidden` + `max-height: 4.5em` and an inside marker would be clipped. `.manage-disclosure > summary` sets neither.
**Why it matters:** Flagged with explicit uncertainty — I could not construct a confirmed counterexample without a browser. The hypothesis is that at viewports below the `clamp(640px, 92vw, 1400px)` floor, `body { padding: 1rem }` is the entire space left of the content box, and an outside marker at `--text-section` (the largest summary size on the page) may render at negative x and be clipped by the viewport, which would remove the affordance this milestone argues is "the ONLY channel that communicates open/closed" in Firefox + VoiceOver. `TestDisclosureRulesAreClassScoped::test_the_marker_is_kept_on_every_summary` forbids `list-style: none`, `list-style-type: none` and `display: block` — it does not cover the one declaration m12 added that touches the marker.
**Proposed fix:** Either drop the declaration (the UA default `inside` is what `<summary>` ships with and nothing here needs otherwise), or keep it and add one clause to the comment stating it is visual parity with `.discover-abstract > summary` rather than an inherited requirement. If kept, extend the marker guard to assert the summary declares no `overflow`/`max-height` that would need it.
**Regression-guard:** Not required at LOW.
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

## What was done well

- **The AC#2 mechanism is airtight and I could not break it.** The store's vocabulary is exactly
  `running`/`success`/`failed` (`server/notebooks_store.py:572-574`), every writer uses the
  constants, and the route synthesises `none` for the no-row case — so `not latest_run or
  latest_run.status != 'success'` covers the complete vocabulary, and any *unknown* value falls
  open, which is the fail-safe direction. `get_latest_ingest_run` returns a plain `dict`, so
  Jinja's getattr→`__getitem__` fallback resolves `.status`, and the guards drive it through a real
  `TestClient` with real rows for all four states rather than asserting on the template string.
- **The `open="false"` footgun is guarded from the correct side.** `test_open_is_never_a_valued_attribute`
  is parametrized over all four states and asserts the substring `open=` never appears — a test
  that only checked the open case would pass on the inversion, and this one names that in its own
  docstring.
- **The D2-escape argument is true, and I checked it exhaustively rather than taking it.** I traced
  every `hx-target` on the rendered page plus base.html's self-swapping `#status-badge`: nothing
  targets the `<details>` or an ancestor, so `onboarding-uplift-m3` §3 D2's rejection genuinely
  does not reach m12. (Its *durability* is M5, not its truth.)
- **The ladder-reachability guard is real and would fail if the declarations were removed.**
  `TestRuleLadderReachesEveryRegion` checks the section rung's selector actually contains `details`
  *and* that its body carries `var(--rule-section)`, and the nested rung's body carries
  `var(--rule-row)` + `border-block-start` with no `border-inline`. The margin/padding half is
  covered too, from the other side: m8's `test_no_tinted_site_relies_on_the_rule_alone` requires
  spacing on every enumerated tinted site, and `.manage-disclosure > div + div` was correctly added
  to `TINTED_SITES` with its second cue.
- **The scope accounting is honest and independently reproduces.** I re-derived the relocation claim
  by multiset-comparing added against deleted lines in the template diff: exactly **62** lines are
  byte-identical on both sides, so 124 of the 848 are git double-counting a block move — the number
  the note states, not a rounded one. 142 authored + 489 guard file + 93 sibling edits + 124
  relocation = 848 exactly.
- **The D2 raise histories were APPENDED, not blanket-replaced** — the falsification m7's rectify
  committed did not recur. All three files preserve their prior text verbatim (m3's m8-held
  paragraph, m4's "593 of 600 (m8 rectify M5/M11)", m5's "file lands at 575") and add the m12 hop
  after it. Only the *number inside* the new paragraph is wrong (M3).
- **The AC#5 refusal corrects the roadmap instead of repeating it.** The roadmap's stated reason
  ("`::details-content` … Chromium-only") is false, the milestone says so at both sites, and
  re-grounds the refusal on Newly-not-Widely — the same bar m6 used for `light-dark()`, m7 for
  `text-wrap: balance` and m10 for `line-clamp`. `TestNoExpandAnimation` runs over
  comment-stripped CSS, so the rationale text cannot satisfy the guard that forbids its own terms.
- **D1 is a disclosed narrowing, not a redefinition to fit what shipped.** All three claimed
  recording sites exist and I verified each: the template's m12 note §2 (`:29-37`),
  `implement/synthesis.md:29-42`, and
  `test_the_rename_form_stays_above_the_table_and_this_is_recorded`, which pins *both* directions —
  that rename is above the table AND that the template still carries the sentence explaining why.
  The bidirectional assertion is the part that makes it honest.
- **Commit hygiene is clean across all three commits:** `%G? = G` on each, `Co-Authored-By: Claude
  Opus 5` present on each, conventional subjects under 50 chars after the prefix, no
  `plans/*/roadmap.yaml` touched, and `origin/main` is still at `54f3cd3` — the declared
  `git push origin main` was not performed.
- **The gate claim reproduces exactly.** I re-ran the full suite independently in this checkout
  (`.venv/bin/python -m pytest -q`): **exactly 8 failures, zero new** — 6 × `test_latexml_sandbox`
  (no `bwrap` on darwin), 1 × `test_win32_bat_invoked_via_perl` (`WindowsPath` on darwin), and
  `test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired`. That last one is the whole of the
  difference between the dispatch's 8 and the implementer's 7, and the implementer's explanation is
  correct: it is local `var/` state, absent in a worktree. The claim that pytest's final `N passed`
  line is not emitted in this environment also reproduced — it is genuinely absent from my run's
  output, so refusing to quote an invented pass total was the right call, not an evasion.

Severity counts: C0 H1 M5 L2

## Recommended rectification order

H1, M3, M5, M4, M2, M1, L1, L2
