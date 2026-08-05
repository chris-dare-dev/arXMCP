# Critique (merged) — ui-uplift-m12

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic, milestone-frontend-ux
**Commit range:** 6f5cbbc0be184e65a9ba39d4a4199d9b1971879c..75f325595acbfbf8ecf0492be92fe2edda484175
**Diff stats:** 11 files (7 code/test + 4 pipeline artifacts), 1304 LOC changed (848 in the 7 code/test files)
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H2, M1->M6, M2->M7, M3->M8, M4->M9, M5->M10, L1->L3, L2->L4, L3->L5
> - `milestone-frontend-ux` (frontend.md): H1->H3, M1->M11, M2->M12, M3->M13, L1->L6, L2->L7, L3->L8, L4->L9

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

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

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The reorder itself is correct and unusually well evidenced: the ladder repair really does reach all three regions, the bare-`open` mechanism survives mutation, every relocated form is byte-identical in action, method, encoding and `hx-disabled-elt`, and six of the eight arXMCP axes are untouched and clean. One HIGH stands: AC#3's "the cue cannot drift from the fragment by construction" is false in time and the page ends visibly self-contradicting on the exact flow AC#2 forces the disclosure open for — demonstrated live, not argued. The rest are MEDIUM test-surface and tier-sequencing gaps: the new "ladder REACHABILITY" guard was mutation-proven to measure rule existence rather than reachability, and two constraints the milestone declared for its own successors (m13's swap ban, m11's empty-state ownership) shipped with no mechanical enforcement and one active conflict.

### milestone-frontend-ux — SHIP-WITH-FIXES

**SHIP-WITH-FIXES.** The reorder does what it claims: the papers table is the
second region on the page, above every mutation control, and the disclosure is a
real progressive-disclosure region rather than a hidden-functionality trap —
it is forced open in every state except a completed ingest, and the empty-state
copy names it by the label the operator actually sees. One HIGH stands in the
way: an operator who collapses the disclosure during a run loses the ingest
success/failure surface entirely, with no visible recovery, which is the exact
failure class AC#2 exists to prevent, reachable one click after page load. Three
MEDIUMs are cheap: the new `<summary>` is the only interactive element on the
page outside the authored focus-ring system, region 3 is absent from heading
navigation, and nothing near the corpus points to the machinery once the
disclosure closes over an unbounded papers table.

## Executive summary — milestone-adversary-critic

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

## Executive summary — milestone-arxmcp-critic

- [HIGH] The `<summary>` state cue is a page-load snapshot with no out-of-band refresh; after a watched ingest settles the page reads `ingest running` above a fragment reading `Status: success`. Reproduced live against the real routes.
- [MEDIUM] `TestRuleLadderReachesEveryRegion` is a text-existence check over `app.css`, not a reachability check: one wrapper `<div>` inside `<details>` strips rule + margin + padding from all five relocated blocks with every guard green (mutation-proven).
- [MEDIUM] The template's "HARD CONSTRAINT ... no swap may target the `<details>` or any ancestor" is prose only. Wrapping the disclosure in the exact swapped `aria-live` wrapper m13's roadmap prescribes leaves every m12 guard passing.
- [MEDIUM] `TestSectioningElementDecision` now measures column-0 blocks while its field comment and both failure messages still say "top-level blocks" — after m12 there are three top-level blocks, not seven.
- [MEDIUM] m12's empty-state guard hard-pins the copy to name "Manage this notebook" — i.e. to be a pointer to a form elsewhere on the page — which `ui-uplift-m11` AC#1 explicitly forbids. The guard blocks its own declared successor.
- [MEDIUM] m12 shifted `app.css` by +29 lines and `notebook_detail.html` by +103, invalidating `links.code` anchors on 12 roadmap items. Owned by `/roadmap`, not Phase 4.
- [LOW] Three cap tests record "the file lands at 635 of 680"; `app.css` is 627 lines.
- Axes clean and verified: cache byte-stability, math fidelity, MCP spec compliance, local-first, no-fork, and the security posture of all five relocated forms.

## Executive summary — milestone-frontend-ux

- **[HIGH]** Collapsing the disclosure mid-ingest silently kills the run's only
  status and error surface — the poll keeps firing into a `display:none` region,
  the `aria-live` announcement is suppressed with it, and the `<summary>` cue is a
  page-load snapshot that never updates. `failed` + `stderr_tail` becomes
  unreachable without a reload the page never suggests.
- **[MEDIUM]** `<summary>` — the sole entry point to all five mutation forms —
  is not in `app.css:450`'s `:focus-visible` ring list, nor in
  `test_ui_a11y_baselines.py`'s enumeration of it. It falls back to the UA ring
  while every other control on the page carries `2px solid var(--accent)`.
- **[MEDIUM]** Region 3 has no heading and no accessible name. The summary renders
  at `--text-section` (20px, identical to every `h2`) but is a `role=button`, so
  heading-list navigation jumps from "Papers in this notebook" straight into
  "Topic & discovery" with no boundary — and the heading list changes shape
  depending on whether the disclosure is open.
- **[MEDIUM]** `store.list_papers()` is uncapped and the disclosure sits below the
  whole table. On a 50-paper notebook (the size `tools/seed-papers.txt` implies)
  the only machinery affordance is ~2400px down — further than the ~1740px scroll
  the milestone exists to remove, in the opposite direction, with no anchor,
  sticky, or in-table entry point.
- **[LOW]** `<code>` inside the summary drops to `--text-small` (13px) against the
  20px the rule deliberately authors for size parity — the m7
  element-rule-overrides-inherited-size lesson recurring at a new site.
- **[LOW]** `list-style-position: outside` is the one declaration in the new rule
  with no recorded reason, and it hangs a 20px-font marker into `body`'s 16px
  padding.
- **[GOOD]** The authored strings were recovered from `.claude/` rather than
  invented, AC#5's false "Chromium-only" premise was corrected at both sites, and
  `show:` was verified against `htmx.config.scrollBehavior: "instant"` so it adds
  no un-gated motion. This is the cleanest milestone in the track's record.

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

**H2 — Summary state cue drifts from the ingest fragment it claims to share** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:258`
**Anchor:** `  <summary>Manage this notebook — ingest <c`
**What:** The cue is rendered once at page load from `latest_run.status` and nothing updates it, so once the 2s poll settles the run the summary and the fragment display contradictory states on the same open page.
**Why it matters:** CLAUDE.md §4.9 forbids a surface asserting a trust/state token the record contradicts; here the page asserts `ingest running` directly above `Status: success`, and the assertion is manufactured by construction on the exact flow AC#2 forces the disclosure open to support. Reproduced against the real `ui_router` + `notebooks_router`: page load emitted `<details class="manage-disclosure" open>` with `<summary>Manage this notebook — ingest <code>running</code></summary>`; after the row moved to `success`, `GET /ui/api/notebooks/{slug}/ingest/latest` returned HTTP 286 `Status: success · Finished …` while the summary in the DOM was unchanged. `grep -rn "hx-swap-oob" server/routes server/frontend/templates` is empty — there is no mechanism that could refresh it. The claim "so the cue cannot drift from the fragment by construction" at `notebook_detail.html:235` and the unqualified restatement at `tests/test_ui_m12_corpus_before_machinery.py:288` are both false as written; only the *source row* cannot drift, not the *rendered value*.
**Proposed fix:** Wrap the token — `<summary>Manage this notebook — ingest <code id="manage-cue">{{ … }}</code></summary>` — and have `_ingest_status_fragment` (`server/routes/notebooks.py`) append `<code id="manage-cue" hx-swap-oob="true">{status}</code>` so every poll refreshes both readers from one response. If an oob swap is unwanted for v0, drop the status token from the summary entirely and keep only the authored label; a cue that can be wrong is worse than no cue. Either edit is ≤10 LOC, and the "cannot drift by construction" sentences at both sites must be corrected in the same commit.
**Regression-guard:** `tests/test_ui_m12_corpus_before_machinery.py::TestSummaryStateCue::test_the_cue_does_not_outlive_the_run` — render at `running`, UPDATE the row to `success`, request `/ui/api/notebooks/{slug}/ingest/latest`, and assert the fragment carries an oob update whose text equals the fragment's own status (or, under the drop-the-token fix, that no state token appears in the rendered `<summary>` at any of the four states).
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage — trust language (CLAUDE.md §4.9)

**H3 — Collapsing the disclosure hides the ingest error path with no recovery** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:472`
**Anchor:** `  <div id="ingest-status"`
**What:** `#ingest-status` polls every 2s from *inside* the disclosure, so an operator who clicks the `<summary>` shut during a run keeps the poll firing into a non-rendered subtree — no visible status, no `aria-live` announcement (content of a closed `<details>` is excluded from the accessibility tree), and the `<summary>` cue at `:258` is a page-LOAD snapshot that will keep reading `running` after the run has finished or failed.
**Why it matters:** The failed-ingest branch carries `stderr_tail` — the most operationally important error in the product per the discovery's own UPL-10 framing — and one click makes it unreachable for the rest of the session, with the only recovery being a page reload the page never suggests; AC#2's forced-open predicate is evaluated at render time only, so it cannot re-open a disclosure the operator closed.
**Proposed fix:** Make the cue live instead of a snapshot, zero new JS: give the cue its own element inside the summary (`<span id="ingest-cue" hx-swap-oob="true">`) and have `_ingest_status_fragment` (`server/routes/notebooks.py:2354+`) emit an out-of-band copy on every poll branch. The `<summary>` is always rendered even when the disclosure is shut, so a collapsed operator still sees `ingest failed` / `ingest success` change under them, and the existing forced-open predicate then only has to handle first paint. Alternative, larger: hoist `#ingest-status` out of the disclosure entirely (brief-2 §5.3, recorded as the road not taken), which dissolves the failure class rather than mitigating it.
**Regression-guard:** `tests/test_ui_m12_corpus_before_machinery.py::TestDisclosureOpenState` — add a case asserting `_ingest_status_fragment` emits an OOB cue element for all four states, plus a template assertion that the summary's status text is a swap target rather than a bare Jinja interpolation.
**Source critic:** milestone-frontend-ux
**Source axis:** Error states

---

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

**M6 — The "ladder REACHABILITY" guard measures rule existence, not reachability** (MEDIUM)

**Where:** `tests/test_ui_m12_corpus_before_machinery.py:435`
**Anchor:** `    def test_the_disclosure_takes_the_section_r`
**What:** Both assertions in `TestRuleLadderReachesEveryRegion` are regexes over the comment-stripped `app.css` text, so they pin that two selectors exist and carry the right token but never evaluate either selector against the markup that must match it.
**Why it matters:** The class docstring states it exists because "m8's guards check the ladder's tokens and its horizontality, never its coverage" — but coverage is exactly what it still does not check, so the risk the milestone identified as its most dangerous stays open one structural edit away. Mutation-proven, in-memory, without touching the repo: inserting `<div class="manage-inner">` immediately after the `<summary>` and closing it before `</details>` makes `.manage-disclosure > div + div` match nothing (a single div child has no adjacent div sibling), stripping rule, margin AND padding from all five relocated blocks — and `m12.section_rung`, `m12.nested_rung`, `m12.three_regions`, `m12.forms_inside`, `m8.DECIDED` and `m8.h2_openers` all still pass. The same gap runs upward: nothing pins that the `<details>` is a direct child of `<main>`, which the `main >` combinator equally requires. For contrast, the guard is not vacuous — it caught 4 of 6 CSS mutations, including reverting the selector to `+ section`, deleting the nested rung, and downgrading it to `--rule-meta`.
**Proposed fix:** Add one structural assertion beside the two CSS ones, derived from the template rather than the stylesheet: parse the rendered page and assert (a) the `<details class="manage-disclosure">` element's parent is `<main id="main">`, and (b) every element carrying a mutation form's `hx-*` marker is a *direct* child of the disclosure. Both are cheap over the existing `detail_client` fixture and are what "reachability" actually names.
**Regression-guard:** `tests/test_ui_m12_corpus_before_machinery.py::TestRuleLadderReachesEveryRegion::test_the_selectors_reach_the_rendered_markup` — must fail on the wrapper-div mutation above and on re-parenting the disclosure.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M7 — The hard constraint declared for ui-uplift-m13 is enforced by nothing** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:46`
**Anchor:** `      the swapped subtree. HARD CONSTRAINT for`
**What:** The template records "no swap may target the `<details>` or any ancestor of it" and names m13 as the near-miss, but no test asserts it; `TestSwapTargetsStillResolve` only checks that every `hx-target` id exists.
**Why it matters:** `ui-uplift-m13` `depends_on: [ui-uplift-m12]` and its roadmap summary prescribes exactly the violating shape — "Move `aria-live` onto a stable never-swapped wrapper." Mutation-proven: wrapping the disclosure in `<div id="live-wrap" aria-live="polite" hx-trigger="every 2s" hx-target="#live-wrap" hx-swap="outerHTML">` leaves all ten m12/m8 template guards green while destroying and recreating the `<details>` every 2 seconds — the server-rendered `open` state snaps back on every tick, which is precisely the `onboarding-uplift-m3` D2 failure this milestone's note claims to have escaped. The constraint is correct and the shipped markup honours it today (no current `hx-target` on the page resolves to an ancestor of the disclosure); only the enforcement is missing.
**Proposed fix:** In `TestSwapTargetsStillResolve`, resolve each `hx-target="#id"` against the rendered page and assert no such element contains the `<details class="manage-disclosure">`, plus assert the `<details>` itself carries no `id` and no `hx-` attribute. ~12 lines using the existing `detail_client` fixture.
**Regression-guard:** `tests/test_ui_m12_corpus_before_machinery.py::TestSwapTargetsStillResolve::test_no_swap_targets_the_disclosure_or_an_ancestor`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M8 — TestSectioningElementDecision names "top-level blocks" but now measures column-0 blocks** (MEDIUM)

**Where:** `tests/test_ui_m8_rule_ladder.py:371`
**Anchor:** `    EXPECTED = {"index.html": (1, 2), "notebo`
**What:** The extractor is `^<(section|div)>` and the five relocated `<div>`s are nested inside the `<details>` while remaining at column 0, so `EXPECTED["notebook_detail.html"] == (2, 7)` and `DECIDED`'s seven entries now describe five nested blocks plus two top-level sections, while the field comment at :370 still reads "expected top-level block count" and both failure messages still say "top-level blocks".
**Why it matters:** The page has THREE top-level blocks after m12; a guard whose name and message assert a property it no longer measures is the recorded `vacuous-test-kept-as-documentation` family this repo has hit at m6, m8 and m10, and a reader trusting the message will conclude the reorder was not performed. It is not vacuous — the ordered per-site element record is real and did catch the reorder — but it is now silently coupled to source indentation, which `EXPECTED`'s own comment does not say (only `DECIDED`'s does).
**Proposed fix:** Rename the tuple's second field to "expected column-0 block count" at :370, amend the two failure messages in `test_block_element_split_is_as_decided` and `test_every_block_still_opens_with_its_heading` to say "column-0 blocks", and note the indentation coupling at `EXPECTED` rather than only at `DECIDED`. The alternative — widening the extractor to `^<(section|div|details)` and adding `details` to `DECIDED` — is also correct but changes the record shape and costs more.
**Regression-guard:** optional (message-only change; the existing per-site assertion is what carries the decision).
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M9 — m12's empty-state guard pins a property ui-uplift-m11 AC#1 forbids** (MEDIUM)

**Where:** `tests/test_ui_m12_corpus_before_machinery.py:485`
**Anchor:** `        assert LABEL in copy, (`
**What:** The guard requires the papers empty state to contain the literal `"Manage this notebook"` — i.e. to be a pointer to a form elsewhere on the page — while `ui-uplift-m11` (which `depends_on: [ui-uplift-m12]` and owns empty-state copy) has as AC#1 "states a cause and offers one actual control, **not a pointer to a form elsewhere on the page**."
**Why it matters:** m12 has hard-pinned the exact property its declared successor exists to remove, so m11 cannot satisfy its own first acceptance criterion without failing an m12 guard. The test's own docstring already concedes "m11 owns empty-state copy … so it revisits the voice," which makes the strength of the assertion an oversight rather than a decision.
**Proposed fix:** Keep the first half — `assert "above" not in copy`, which is the FACT m12 corrected and which m11 cannot legitimately reverse — and relax the second to a direction-agnostic form (e.g. the copy names some affordance reachable on the page) or drop it with an inline note that m11 re-decides the wording. ~4 LOC.
**Regression-guard:** the retained `assert "above" not in copy` is the durable half; it fails on the pre-m12 string and is unaffected by m11's rewrite.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M10 — m12 invalidated links.code anchors on 12 roadmap items** (MEDIUM)

**Where:** `plans/ui-uplift/roadmap.yaml:552`
**Anchor:** `      code: ["server/frontend/static/app.css:`
**What:** `app.css` grew 598 → 627 with all 30 added lines inserted at 64–94, so every `links.code` anchor at line ≥ 64 is off by exactly +29; `notebook_detail.html` grew 381 → 484 with the reorder, invalidating its anchors too.
**Why it matters:** These anchors are what a Phase-0 dispatch hands an implementer, and in this track a milestone that cannot find its authored source is the documented root cause of m7/m8/m10 inventing values (research/synthesis.md, "the finding that explains three prior milestones"). Verified by reading both revisions: `ui-uplift-m16` `app.css:83-93` meant `input[type="text"], input[type="url"], input[type="file"] {` and now lands inside m12's comment block; `ui-uplift-m15` `app.css:512-536` meant the `.htmx-request` in-flight rules and now lands in the dark-mode grey remap; `ui-uplift-m21` `app.css:97-110` meant `input[name="slug"] …` and now lands on the `h2` comment; `ui-uplift-m18` `notebook_detail.html:43` meant the rename form's error handler and now lands in m12's note. Also affected: m1 (`372-375`), m4 (`108-113`), m5 (`202`), m7 (`71`), m8 (`64-65`), m14 (`notebook_detail.html:99`), m17 (`578-581`), m20 (`54-89`), and m12's own `notebook_detail.html:14-381`.
**Proposed fix:** Owned by `/roadmap` under the one-writer rule — **do not edit `plans/ui-uplift/roadmap.yaml` in Phase 4.** Re-resolve every `links.code` anchor in the `ui-uplift` plan against the current tree in a `/roadmap` pass; prefer symbol- or selector-shaped anchors (`app.css .manage-disclosure`) over line numbers for files this epic keeps rewriting.
**Regression-guard:** optional here; the durable fix is a `/roadmap` lint that resolves every `links.code` line range and fails when the cited span no longer contains the item's own tag.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M11 — The new `<summary>` is outside the authored `:focus-visible` ring system** (MEDIUM)

**Where:** `server/frontend/static/app.css:450`
**Anchor:** `button:focus-visible, .button:focus-visi`
**What:** The ring list is `button, .button, input, a, select, textarea, [tabindex]` — `summary` is absent, so the milestone's new control (and m10's `.discover-abstract > summary`) falls back to the UA default ring instead of `2px solid var(--accent)` at `outline-offset: 2px`.
**Why it matters:** `<summary>` is the only keyboard-reachable gate to all five mutation forms; it is the one control on the page whose focus state is unauthored, and `tests/test_ui_a11y_baselines.py::test_focus_visible_rule_covers_all_interactive_selectors` enumerates the list by hand, so the omission is invisible to the guard that exists for exactly this class of gap.
**Proposed fix:** Add `summary:focus-visible,` to the selector list at `app.css:450-455` (one token, no new rule, no cap pressure) and add `"summary:focus-visible"` to the `test_focus_visible_rule_covers_all_interactive_selectors` tuple. Check the ring against `--bg` for SC 1.4.11 3:1 — `--accent` already clears it as the button ring, so no contrast artifact regeneration is needed.
**Regression-guard:** `tests/test_ui_a11y_baselines.py::TestFocusVisible::test_focus_visible_rule_covers_all_interactive_selectors` with `summary:focus-visible` added to the enumerated list.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

---

**M12 — Region 3 is absent from heading navigation and has no accessible name** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:258`
**Anchor:** `  <summary>Manage this notebook — ingest`
**What:** The summary is styled at `--text-section` — byte-identical to `h2` (`app.css:100`) — but is a `role=button`, so the page's third region contributes nothing to the heading list; a screen-reader user navigating by heading goes "Papers in this notebook (N)" → "Topic & discovery" with no signal that they entered a different region, and the heading list silently gains or loses five entries depending on the disclosure's open state.
**Why it matters:** The milestone's whole thesis is that the page now has three legible regions; two of them are announceable and the third is only announceable to someone who tabs rather than navigates by heading, which inverts the region hierarchy for the AT users the reorder is supposed to help most. The implementer's reason for *not* nesting an `<h2>` inside `<summary>` is correct (role=button makes children presentational) — the gap is that no alternative was put in its place.
**Proposed fix:** Do not add a heading. Name the group instead: `id="manage-summary"` on the `<summary>` and `aria-labelledby="manage-summary"` on the `<details>` — HTML-AAM maps `<details>` to `role=group`, so this gives the region an announced name on entry at zero structural cost, does not touch m8's `^<(section|div)>` record view, and reuses the same id M3's anchor needs.
**Regression-guard:** `tests/test_ui_m12_corpus_before_machinery.py::TestManageDisclosureNesting` — assert the rendered `<details>` carries `aria-labelledby` resolving to an existing `id` on its own `<summary>`.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

---

**M13 — Nothing near the corpus points to the machinery, over an uncapped table** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:150`
**Anchor:** `  <h2>Papers in this notebook ({{ papers`
**What:** `server/routes/ui.py:437` calls `store.list_papers(slug)` with no limit and the template renders every row, so the `<summary>` — the only affordance for adding, discovering, uploading or ingesting once a notebook has ingested successfully — sits below the entire table; the pointer to it exists only in the `{% if not papers %}` empty state at `:159`, i.e. exactly when it is least needed.
**Why it matters:** The milestone was justified by a measured ~1740px scroll to the corpus; a 50-paper notebook (`tools/seed-papers.txt` ships 50 ids) puts the machinery ~2400px below the fold with no anchor, no sticky affordance and no in-table entry point — the scroll was inverted rather than removed, and no milestone artifact records the large-corpus case.
**Proposed fix:** One anchor, zero CSS: give the disclosure `id="manage"` (the same id M2 needs) and add `<a href="#manage">Manage this notebook</a>` to the papers `<section>` beside the `<h2>` at `:150`, so the entry point is adjacent to the corpus in every state. Note in the template that this is deliberately a link and not a duplicated control, so it cannot drift into a second primary CTA (BAN-9).
**Regression-guard:** Optional (MEDIUM) — a render assertion that the papers `<section>` contains an `href="#…"` resolving to the disclosure's `id`.
**Source critic:** milestone-frontend-ux
**Source axis:** Discoverability

---

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

**L3 — The three cap tests record app.css at 635 lines; it is 627** (LOW)

**Where:** `tests/test_ui_m3_dark_and_htmx_feedback.py:648`
**Anchor:** `        # The file lands at 635 of 680.`
**What:** All three lockstep cap comments state "the file lands at 635 of 680" (m3:648, m4:745, m5:858) while `wc -l server/frontend/static/app.css` is 627 — the number `implement/synthesis.md` itself reports.
**Why it matters:** The raise history in these comments is the argument a future milestone reads before raising the cap a fifth time; an 8-line error in the "headroom used" figure is small but it is the one number the comment exists to carry, and the trim that created it happened after the comments were written.
**Proposed fix:** Replace `635` with `627` in the three comments.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L4 — ui-uplift-m11's target window ends 11 days before the milestone it depends on** (LOW)

**Where:** `plans/ui-uplift/roadmap.yaml:428`
**Anchor:** `    target_end: 2026-09-15`
**What:** `ui-uplift-m11` has `target_start 2026-09-08 / target_end 2026-09-15` and `depends_on: [ui-uplift-m12]`, while `ui-uplift-m12` runs `2026-09-08 → 2026-09-26`.
**Why it matters:** The research synthesis flagged this as an unverified brief-2 claim and told Phase 2 to leave it alone; it is now confirmed by reading `roadmap.yaml` directly, so it should stop being carried as unconfirmed. It also makes m11's own AC#2 ("this ships WITH it") unsatisfiable as written now that m12 has shipped alone — m12 handled the consequence correctly by fixing the one false string, but the AC text is stale.
**Proposed fix:** `/roadmap`-owned, not Phase 4: move m11's window after m12's `target_end`, and re-word m11 AC#2 from "ships WITH it" to "ships after it, and re-decides the interim copy m12 shipped".
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**L5 — Two ladder declaration sets are unguarded and can be emptied silently** (LOW)

**Where:** `server/frontend/static/app.css:93`
**Anchor:** `.manage-disclosure > summary { margin-block-`
**What:** Mutation-proven misses: emptying `.manage-disclosure > summary` entirely, and stripping `margin-block-start`/`padding-block-start` from the top-level section rung at :67, both leave every m12 and m8 guard green.
**Why it matters:** The summary rule carries the `font-size: var(--text-section)` size parity the milestone argued for at length (region parity without wrapping an `<h2>` inside a `role=button`) and the `cursor: pointer` affordance, and neither is pinned anywhere. The section rung's 2rem rhythm miss is inherited from m8 rather than introduced here, so it is the weaker half. The nested rung's spacing IS covered, by m8's `TestExemptionIsConditionalPerSite::test_no_tinted_site_relies_on_the_rule_alone`.
**Proposed fix:** Extend `TestRuleLadderReachesEveryRegion` (or `TestDisclosureRulesAreClassScoped`) with an assertion that `.manage-disclosure > summary` declares `font-size: var(--text-section)` and `cursor: pointer`, and that the `main > … + :where(section, details)` rule declares both `margin-block-start` and `padding-block-start`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L6 — `<code>` in the summary drops to 13px against the authored 20px** (LOW)

**Where:** `server/frontend/static/app.css:324`
**Anchor:** `code, time { font-family: var(--mono); f`
**What:** The element-level rule sets an absolute `font-size: var(--text-small)` (13px), so the state token inside `<summary>` renders at 13px inside a label the m12 rule deliberately sets to `--text-section` (20px) "for size parity with the other regions" — the parity the comment claims holds for the label text and not for the datum the cue exists to show.
**Why it matters:** This is the m7 lesson recurring verbatim at a new site (an element rule with an absolute size silently overriding every context it nests inside); it is not obviously wrong here — a 13px mono token beside a 20px label is arguably the two-voice scale working — but it was not checked, and the same rule is why `<h2><code>{{ notebook.slug }}</code></h2>` at `:54` renders the page's primary identifier below body size.
**Proposed fix:** Decide it rather than inherit it. Either add `.manage-disclosure > summary code { font-size: inherit; }` if the cue should match the label, or record in the m12 CSS comment that the 20px/13px step is the intended two-voice pairing so the next milestone does not "fix" it. No token change either way.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

---

**L7 — `list-style-position: outside` is unrecorded and hangs the marker into body padding** (LOW)

**Where:** `server/frontend/static/app.css:93`
**Anchor:** `.manage-disclosure > summary { margin-bl`
**What:** In a milestone that records a reason for every declaration and every refusal, this is the one declaration with none; it moves the disclosure marker out of the summary's content box so the label aligns with the `h2`s above, and the only space it has to hang into is `body { padding: 1rem }` (`app.css:21`) — `main` has no padding rule of its own.
**Why it matters:** At `--text-section` (20px) the UA `disclosure-closed` marker plus its gap is close to 16px, so at narrow viewports the triangle may sit at or past x=0 and clip — **unverified, and unverifiable in this review** because no page was composited; the concrete defect that IS verified is the missing rationale, which is what lets a later milestone delete or "harmonise" it without knowing it carries the label's alignment.
**Proposed fix:** Record the reason in the existing m12 comment block (one line: "`outside` so the label aligns with the sibling `h2`s; the marker hangs into `body`'s 1rem"). If a browser check shows clipping at 375px, add `padding-inline-start: 1.25rem` to the summary and drop back to the default position.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Mobile / narrow-viewport

---

**L8 — The state cue duplicates a datum already rendered in the masthead** (LOW)

**Where:** `server/frontend/templates/notebook_detail.html:123`
**Anchor:** `        <span class="hint">(ingest <code`
**What:** `latest_run.status` is now rendered twice on one page in the same `<code>` voice — once in the masthead's "Last indexed" row and again in the disclosure summary — and both are page-load reads of the same row, so they can never disagree but always repeat.
**Why it matters:** The masthead is the region this critique's axis 1 asks to justify itself, and it currently ends with a destructive Delete button and a metadata list that the disclosure summary now partially restates; repeating the same token 130 lines apart adds density without adding a fact (BAN-R3's neighbourhood), and UPL-5's posture lede — which owns this masthead — will have to resolve the duplication anyway.
**Proposed fix:** Leave both for now and record the overlap in the m12 template note so `ui-uplift-m11`/UPL-5 inherits the decision rather than rediscovering it. If one goes, the masthead's is the redundant copy: "Last indexed `<time>`" already carries the freshness fact, and the run *outcome* belongs next to the control that produces it.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Information density

---

**L9 — The "seven blocks to three regions" claim is stated unconditionally but is state-dependent** (LOW)

**Where:** `server/frontend/templates/notebook_detail.html:257`
**Anchor:** `<details class="manage-disclosure"{% if `
**What:** The open predicate is "open unless `success`", so on every notebook that has never been ingested (`latest_run is None`) and on every failed or running one, the default render still presents all seven headed blocks stacked — the reduction to three visible regions is only realised after a successful ingest, and neither the template note, the implement synthesis, nor the BAN-2 recovery says so.
**Why it matters:** The `none` arm is the weak one: the stated justification is that "`none` and `running` both still poll every 2s", but a `none` poll can never transition without an action taken *inside* the disclosure, so forcing it open buys nothing that first-paint ordering does not already give — and it is the arm that costs the milestone its BAN-2 payload on exactly the first-run page the discovery cared about most. The ladder still ranks the inner blocks at `--rule-row` under one `--rule-section` region, so this is a claim-precision defect, not a layout one.
**Proposed fix:** Keep the predicate (open-on-first-run is the right call for an empty notebook) and fix the record: state in the m12 template note that the three-region *render* is the post-`success` state and that first run deliberately trades it for immediate access to the forms. If the predicate is ever narrowed to AC#2's literal wording (non-terminal or failed), the empty-state copy at `:159` becomes the only pointer and M3's anchor becomes mandatory rather than cheap.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

## What was done well

### From milestone-adversary-critic

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

### From milestone-arxmcp-critic

- **The `open` mechanism is right and is tested against the way it fails.** `{% if %}open{% endif %}` emits the bare attribute, and `test_open_is_never_a_valued_attribute` runs over all four states rather than only the open case — the `open="false"`-renders-open inversion is caught, and my mutation replacing the conditional with a valued attribute was caught by both the source-level and render-level guards.
- **The ladder repair is real and mutation-resistant where it counts.** Folding `details` into the existing `+ section` rung at zero net lines, plus the nested `--rule-row` rung, is the correct structural answer; reverting the selector to `+ section`, deleting the nested rung, or downgrading it to `--rule-meta` are all caught, and the nested rung's spacing is caught by m8's own tinted-site guard.
- **Every relocated form is byte-identical in its security-relevant posture.** A set-comparison of the diff's added vs deleted lines shows exactly three true deletions (the empty-state string, one `hx-swap` value, one comment); all five mutation forms kept their `hx-post`/`hx-patch` action, `hx-ext="json-enc"` or `hx-encoding="multipart/form-data"`, and `hx-disabled-elt`, and no inline handler, no fetch and no CSP change was introduced.
- **AC#3's same-row claim is true at the source level and I verified it independently.** `server/routes/ui.py:461` and `server/routes/notebooks.py:2283` both call `store.get_latest_ingest_run(slug)`; the guard that pins both call sites is a genuine cross-module assertion, not a restatement.
- **The `show:` modifier is correct against the vendored library, not against the docs.** Reading `htmx.min.js` 2.0.10's `hx-swap` parser confirms `show:#papers-tbody:bottom` splits to `show="bottom"`, `showTarget="#papers-tbody"` and resolves to `scrollIntoView({block:"end"})` — the fix works and adds zero CSS and zero dependencies.
- **AC#5's stated reason was corrected rather than repeated.** `::details-content` really is Baseline newly across all engines since 2025-09-16; refusing the animation on Newly-not-Widely instead of on a false "Chromium-only" claim keeps the refusal from being argued away by one browser release, and the correction is recorded at both sites plus the guard.
- **The scope overrun is measured, split and honest.** `implement/scope-exceeded.md` separates the 124 relocation lines git double-counts, the 489-line guard file and the 142 lines of authored product change, and records what was trimmed to get there — including the deliberate refusal to indent, which saved ~380 lines of whitespace churn and preserved five per-site records.
- **The AC#1 narrowing is recorded in three places, which is the correct handling of a narrowed criterion.** Rename staying in the identity `<section>` is defensible on the merits and is pinned in the template, the synthesis and a test rather than left as a silent gap.
- **Six of the eight arXMCP axes are verifiably untouched, and the packaging boundary held.** `server/tools.py`, `server/prompts.py`, `tests/test_server_tool_schema.py`, `tests/test_prompts.py`, `pyproject.toml`, `server/middleware.py`, `server/config.py` and `server/routes/` all have empty diffs; no asset set is hashed, no dependency moved, nothing was vendored or lifted; no new asset file was added and both stylesheets remain enumerated in `tests/test_wheel_packaging.py:222,231` and `tools/wheel_install_check.py:119,125`.
- **The zero-new-failures claim reproduces exactly.** A full `pytest` run at `75f3255` in this checkout returned precisely the eight environment-bound failures the dispatch names — six `tests/security/test_latexml_sandbox.py` (no `bwrap` on macOS, `rc=-6`), one `WindowsPath` on darwin, and `test_cite_neighbors_wired` failing `'unavailable' == 'absent'` because this checkout's `var/arxmcp/index/kuzu` is a directory. Zero new. The synthesis's other observation reproduces too: pytest emits no final count line in this environment.

### From milestone-frontend-ux

- **The authored strings were recovered, not invented.** "Manage this notebook"
  (`art-direction-scout-brief.md:428-430`) and the cue form
  (`challenge.md:107`) came out of `.claude/` — the tree `rg` cannot see — which
  breaks the m7/m8/m10 pattern of re-deriving values that were already on disk.
  The research synthesis names the tool blind spot as the root cause rather than
  blaming the implementer, and that diagnosis is correct.
- **AC#5's reason was corrected rather than repeated.** `::details-content` is
  Baseline *newly* across all engines since 2025-09-16, not Chromium-only; the
  refusal now stands on Newly-not-Widely with the m6 `light-dark()` / m7
  `text-wrap: balance` / m10 `line-clamp` precedent named at both sites, and the
  guard asserts absence over **comment-stripped** CSS so the comment explaining
  the refusal cannot satisfy the test that enforces it.
- **The `open` attribute is emitted bare, and the inversion is tested.**
  `open="false"` renders a `<details>` open; `TestDisclosureOpenState` renders all
  four states and asserts the string `open=` never appears, which is the only
  form of that test that catches the bug.
- **The ladder-reachability break was predicted, repaired in place, and guarded.**
  `main >` is a direct-child combinator, so nesting the five blocks silently
  dropped their rule, margin and padding; the fix folded `details` into the
  existing section-rung selector at zero net lines and shipped
  `TestRuleLadderReachesEveryRegion`, closing the coverage gap that made the break
  invisible to m8's token/horizontality guards.
- **`show:#papers-tbody:bottom` is the right fix and adds no motion.** Verified
  against the vendored `htmx.min.js` 2.0.10: `scrollBehavior` defaults to
  `"instant"`, so the scroll needs no `prefers-reduced-motion` gate and does not
  walk into the surface map's wholesale AP-2 block. Zero CSS, zero dependency.
- **The AC#1 narrowing is recorded three times, including in a test that asserts
  the template still says why.** "An unrecorded narrowing of an AC is
  indistinguishable from failing it" is exactly right, and rename staying with the
  record's identity is the correct call on the merits.
- **The empty-state copy is actionable in the state it targets.** It quotes the
  disclosure's visible label, and because a closed `<details>` still renders its
  `<summary>`, the instruction resolves even when the region is shut — which is
  what keeps this progressive disclosure on the legitimate side of the
  dark-pattern line.
- **The summary rule is class-scoped for a stated reason.** A bare `summary`
  selector at (0,0,1) would have out-declared `.discover-abstract > summary`'s
  unset properties and stripped m10's abstract-reveal marker; keeping the native
  `::marker` also preserves the only open/closed channel Firefox + VoiceOver
  exposes.
- **The prior rejection of `<details>` was answered at the site.**
  `onboarding-uplift-m3` D2 refused a disclosure that lived *inside* the swapped
  element; the note explains why nesting the polled element instead escapes that
  reasoning, and writes down the hard constraint it creates for m13 (no swap may
  target the `<details>` or any ancestor).
- **Nothing was added that the ban list forbids.** No new token, no new colour
  pair (contrast artifact regenerated byte-identical at 101 pairs), no icon
  (BAN-3 stays at 0), no status pill for the cue (BAN-7 stays at 0), no
  "Quick Actions"/"Controls" heading (BAN-10 stays at 0), and no `name` attribute
  that would have opted the nested `.discover-abstract` disclosures into
  exclusive-accordion grouping.

Severity counts: C0 H3 M13 L9


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **M7, M5** at `server/frontend/templates/notebook_detail.html:46-47` (MEDIUM): The hard constraint declared for ui-uplift-m13 is enforced by nothing; The "hard constraint for m13" is recorded in a comment and enforced by nothing
- **L9, H2, M2, M12** at `server/frontend/templates/notebook_detail.html:257-258` (HIGH): The "seven blocks to three regions" claim is stated unconditionally but is state-dependent; Summary state cue drifts from the ingest fragment it claims to share; Summary cue can read `success`/`none` while a run started in-page is live; Region 3 is absent from heading navigation and has no accessible name
- **M3, L3** at `tests/test_ui_m3_dark_and_htmx_feedback.py:648-648` (MEDIUM): Three lockstep cap comments claim 635 lines; `app.css` is 627; The three cap tests record app.css at 635 lines; it is 627
- **M4, M8** at `tests/test_ui_m8_rule_ladder.py:371-371` (MEDIUM): `TestSectioningElementDecision` still says "top-level" and is now pinned to indentation; TestSectioningElementDecision names "top-level blocks" but now measures column-0 blocks
- **L2, L5, L7** at `server/frontend/static/app.css:93-93` (LOW): `list-style-position: outside` is unexplained and its m10 justification does not transfer; Two ladder declaration sets are unguarded and can be emptied silently; `list-style-position: outside` is unrecorded and hangs the marker into body padding

## Recommended rectification order

H1, H2, H3, M3, M5, M4, M2, M1, M6, M7, M9, M8, M10, M11, M12, M13, L1, L2, L3, L5, L4, L6, L7, L9, L8

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
