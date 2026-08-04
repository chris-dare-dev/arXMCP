# Critique (merged) — ui-uplift-m10

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic, milestone-frontend-ux
**Commit range:** 216aff062f78d44d314b7b33f72d6b836192e0ee..9444a4cf0cb6b17eae8d0e7b2793032eea0e05ec
**Diff stats:** 14 files, 1974 LOC (1841 insertions, 133 deletions; `server/` + `tests/` alone are 274 LOC — 224/50)
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H2, M1->M6, M2->M7, M3->M8, M4->M9, M5->M10, L1->L3
> - `milestone-frontend-ux` (frontend.md): H1->H3, M1->M11, M2->M12, M3->M13, M4->M14, M5->M15, M6->M16, M7->M17, L1->L4, L2->L5

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

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

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The `--fg-muted` derivation is independently re-verified and correct — I re-derived OKLCH→sRGB→WCAG from scratch and got 7.004:1 / 7.015:1 on `--card-bg` and 5.429:1 at the tightest pill (dark `--warn`), matching the published table to within 8-bit quantisation, with every ground the token actually renders on registered at the right floor and none omitted. No axis shows a security, MCP-spec, cache-byte-stability, local-first or no-fork problem, and the packaging boundary already covers both stylesheets. What is left is one reachable common-path defect on the milestone's own headline surface (the abstract is clipped with zero affordance and no route to the full text), a token whose derivation ground the roadmap has already scheduled for retirement, and a coverage predicate that still cannot distinguish a rule from a gesture — the exact failure mode this milestone was chartered to close.

### milestone-frontend-ux — SHIP-WITH-FIXES

**SHIP-WITH-FIXES.** The typographic work is genuinely good — four of discovery finding H3's
five authored rules ship essentially verbatim with correct token substitution, the ban list
was actively consulted rather than nodded at, and AC#4's refusal to manufacture a relevance
line is the right call argued from the data. Two things hold it back: the abstract is now
clamped with no affordance to reveal it and no cue that anything was cut, on the one surface
the console builds for operator judgment; and `--fg-muted` was minted without migrating any of
the eleven greys beside it, which in dark mode puts three distinct secondary-text values in a
single card. Neither is expensive to fix and neither is a wrong direction — they are an
unfinished one.

## Executive summary — milestone-adversary-critic

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

## Executive summary — milestone-arxmcp-critic

- [HIGH] `.discover-abstract` clips 40–85% of the operator's decision evidence with no ellipsis, fade, expand control, or link to the paper — and there is no other place in the console showing that abstract.
- [MEDIUM] `--fg-muted` is solved to 7.00:1 against `--card-bg`; `ui-uplift-m8` (unblocked, lane `next`) explicitly re-roles `--card-bg` away from panel ground, which silently moves every `--fg-muted` consumer onto an unregistered `--bg` pair.
- [MEDIUM] Nothing asserts a single declaration in the nine new rules. `_css_defines_class` matches a `.token` anywhere in the CSS text, so an empty `.foo { }` satisfies AC1 — the m7 bare-`font-size` precedent is unguarded against.
- [MEDIUM] The Discover panel names no ordering basis; the new hairline ladder renders reverse-chronological results in a form that reads as ranked. AC#4 removed the false string but left the implied precedence.
- [MEDIUM] `tokens.css:47` states in the past tense that the product "carried eleven hand-typed greys"; none was migrated, so the product now carries twelve muted values and the shipped comment overstates.
- [MEDIUM] Five `plans/ui-uplift/roadmap.yaml` `links.code` anchors are invalidated by the +77/+22-line growth — third re-anchor needed today. Not fixable from Phase 4 (one-writer rule); route to `/roadmap`.
- [LOW] `.discover-list { list-style: none }` drops list semantics under Safari/VoiceOver; the markup has no compensating `role="list"`.
- [NOTE — not a finding] Gate re-run on this box: **8 failures**, but a different set than the dispatch baseline — 6 × latexml sandbox, 1 × `WindowsPath`, and `test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` (`graph_status` `unavailable` vs `absent`; `var/arxmcp/index/kuzu` is a bootstrapped empty directory). The HuggingFace one passed. Zero relation to this diff; the baseline is 9 environment-bound, not 8.

## Executive summary — milestone-frontend-ux

- [HIGH] `.discover-abstract` hides 40–70% of an arXiv abstract behind `max-height` + `overflow: hidden` with no `…`, no fade, no `<details>`, and no control — the operator deciding whether to Add a paper now has strictly less information than before m10, and no signal that information is missing.
- [MEDIUM] `--fg-muted` is a **twelfth** grey, not a replacement: in dark mode the Discover card renders `.card .hint` at `#b3b9c0` (8.95:1) three lines above `.discover-meta` at `#9fa4a8` (7.04:1), and `--fg-muted` dark sits within a 1.036 luminance ratio of `.card .note`/`.card .empty` `#9ba1a8` — two values too close to be intentional.
- [MEDIUM] `.discover-list { list-style: none }` strips list role in Safari/VoiceOver with no compensating `role="list"`; the results list loses its item count for AT users on the surface where "how many candidates" is the first question.
- [MEDIUM] Candidate titles are `<p class="discover-title">` with `font-weight: 600` and no heading level — "this is a paper title" is conveyed by type treatment alone, and a screen-reader user cannot navigate the list by heading.
- [MEDIUM] BAN-9 (multiple primary CTAs per viewport, on the **must-be-removed** list) is live and unaddressed on the exact surface m10 designed: every candidate row carries a full-accent `Add` button. The implementer's ban audit checked BAN-2/3/7 and UPL-24 but not BAN-9.
- [MEDIUM] The panel discloses no ordering. The list is `sortBy=submittedDate&sortOrder=descending`, and dressing it as bibliography-style search results actively strengthens the "these are ranked by relevance" reading that AC#4 exists to avoid.
- [MEDIUM] H3's abstract/meta size step was dropped — both render at `--text-small` (13px), so the hierarchy is two steps where H3 authored three.
- [MEDIUM] The stylesheet contradicts itself on run size (`:195` "a run is up to 10 rows" vs `:222` "up to 200 candidates a run"); the route passes no `max_results`, so 200 is live, and the ladder plus the `aria-atomic="true"` announcement are both unbounded.

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

**H2 — Discover abstract clipped with no affordance and no route to full text** (HIGH)

**Where:** `server/frontend/static/app.css:231`
**Anchor:** `.discover-abstract { margin: 0.25rem 0 0`
**What:** `max-height: 4.5em; overflow: hidden` hard-clips the abstract at three line boxes with no ellipsis, gradient, `<details>`, scroll container or link to the paper, and the candidate's `paper_id` renders as bare `<code>` (`server/routes/notebooks.py:733`) rather than an anchor — so the console offers no way to read the rest.
**Why it matters:** `abstract_head` is the FULL abstract (`tools/_arxiv_api.py:210` is `" ".join(summary.split())`, 800–1500 chars); three lines at `--text-small` holds ~240 chars at a 640px viewport and ~540 at the 1400px ceiling, so 40–85% of the evidence backing the operator's irreversible "Add" click is invisible with nothing signalling that it was cut — a page that presents partial evidence as if it were whole, on the one surface this milestone exists to make trustworthy (CLAUDE.md §4.9's manufactured-impression standard).
**Proposed fix:** Keep the clamp, add the affordance. Cheapest correct pair, both inside the m10 line budget: (a) a fade mask on the clipped box — `.discover-abstract { -webkit-mask-image: linear-gradient(#000 70%, transparent); mask-image: linear-gradient(#000 70%, transparent); }` (Baseline Widely Available, unlike `line-clamp`, so it clears the same bar m6/m7 applied); and (b) make the identifier a real exit — in `_discover_results_fragment`, `<code><a href="https://arxiv.org/abs/{pid}" rel="noreferrer noopener" target="_blank">{pid}</a></code>` (the URL is already built one line below at `:740`). If the fragment builder is judged out of scope for a CSS milestone, ship (a) alone and file (b).
**Regression-guard:** `tests/test_ui_class_css_coverage.py` (or a new `test_ui_m10_discover.py`) asserting the `.discover-abstract` rule body contains a `mask-image` (or other cue) declaration alongside `overflow: hidden`, so a future edit cannot re-open the silent clip; plus a `test_notebook_api.py` assertion that `_discover_results_fragment` emits an `arxiv.org/abs/` anchor per candidate.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface / trust language (CLAUDE.md §4.9)

**H3 — Abstract truncated with no reveal affordance and no truncation cue** (HIGH)

**Where:** `server/frontend/static/app.css:231`
**Anchor:** `.discover-abstract { margin: 0.25rem 0 0`
**What:** `max-height: 4.5em; overflow: hidden` clips the abstract to three lines with no ellipsis, no fade, no "more" control and no `<details>` disclosure, so an operator cannot read the hidden text or even tell that text was hidden.
**Why it matters:** This is the console's only surface that presents external content for an operator decision (per-candidate Add), and m10 removed reading capability from it — pre-m10 the full abstract rendered; post-m10 roughly 40–70% of an 800–1500-character abstract is unreachable in-console, and because the cut lands cleanly on a line boundary a short abstract and a truncated one are visually indistinguishable.
**Proposed fix:** Make the truncation self-declaring and reversible with zero JS. Change the fragment builder to emit `<details class="discover-abstract"><summary>` + the first sentence, with the full text as the disclosure body — native, keyboard-operable, and it collapses the visual/AT asymmetry the current clamp creates. If markup must stay frozen, the minimum acceptable stopgap is a CSS-only cue that the text continues: keep the clamp, add `position: relative` plus an `::after` gradient fade to `var(--card-bg)` over the last line box, and append a literal "… (abstract truncated)" span to the fragment — but a cue without a reveal is a worse product than a disclosure, so prefer `<details>`. Add `overflow-wrap: anywhere` in the same edit: `overflow: hidden` clips horizontally too, and arXiv abstracts carry inline-math and URL tokens that will not wrap.
**Regression-guard:** `tests/test_ui_class_css_coverage.py` (or a new `tests/test_ui_m10_discover.py`) asserting that whenever `.discover-abstract` carries a `max-height`/`line-clamp`/`overflow: hidden` declaration, the emitted fragment for a long `abstract_head` also contains a `<details>`/`<summary>` pair or a literal truncation marker — i.e. clamping without an affordance fails.
**Source critic:** milestone-frontend-ux
**Source axis:** First-time-user clarity / information density

---

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

**M6 — `--fg-muted` derived against a ground ui-uplift-m8 is scheduled to retire** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:66`
**Anchor:** `--fg-muted: oklch(45.706% 0.014 250);`
**What:** The token's 7.00:1 target, its only two canvas-ground registry rows, and the explicit refusal to register a `--bg` pair are all pinned to `--card-bg` as *panel* ground, but `plans/ui-uplift/roadmap.yaml:327-352` (`ui-uplift-m8`, lane `next`, `depends_on: [m6, m7]` — both shipped) deletes `.card` and states as AC#2 that `--card-bg`'s successor role is "control ground for inputs and table headers, **not panel ground** — because three dark-mode rules still depend on it."
**Why it matters:** The day m8 lands, `.discover-meta` and `.topic-description` render on `--bg` with no registry row for that pair, which is precisely the binding-ground omission `.claude/docs/ui-contrast-table.md` was built to prevent — and m10 has written into both `tokens.css:55-57` and the published artifact that no such row exists *because the pair does not render*, so the omission will read as deliberate rather than stale. (I measured the post-m8 ratios: 6.804:1 light, 7.688:1 dark — no AA failure, so nothing will fail loudly; the record just goes quietly wrong. m8's "three dark-mode rules" count is now four.)
**Proposed fix:** One comment line in `tokens.css` beneath the GROUND paragraph naming the coupling explicitly — "`ui-uplift-m8` re-roles `--card-bg` off panel ground; when it lands, `--fg-muted`'s consumers move to `--bg` (measured 6.80:1 light / 7.69:1 dark, still AAA-adjacent) and the registry needs the `--fg-muted on --bg` rows added, not the card rows edited." Optionally add the two `--bg` rows now as m8-forward pairs with that reason in the Site column, which the registry's Site-column convention already supports.
**Regression-guard:** N/A (documentation coupling); the durable guard belongs in `ui-uplift-m8`'s acceptance criteria — add "`--fg-muted`'s registry rows are re-grounded" to m8's AC#2 list via `/roadmap`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing / math fidelity

**M7 — BAN-R2's predicate still cannot tell a rule from a gesture** (MEDIUM)

**Where:** `tests/test_ui_class_css_coverage.py:119`
**Anchor:** `_KNOWN_UNSTYLED: dict[str, str] = {}`
**What:** With the deferral list emptied, AC1 is advertised as binding "unconditionally", but the predicate behind it is unchanged: `_css_defines_class` (`:311`) is `re.compile(r"\." + classname + r"(?![\w-])")` over comment-stripped text, so `.foo { }` — or `.foo` inside any declaration value — satisfies it, and I confirmed by grep that **no test in the suite asserts any declaration** for the nine classes m10 landed (`display`, `max-height`, `color`, `font-family` all unpinned).
**Why it matters:** m7 shipped `.status-badge__remediation` as a bare `font-size` pin that satisfied AC#5's letter while leaving discovery H1's inline run-on defect on screen for a full milestone — that is the documented precedent, and emptying the list makes the predicate the *only* remaining check, so the same class of gesture now passes with no deferral entry to make it visible. Concretely, `display: block` at `:317` is the single declaration that fixes H1 and nothing would fail if it were deleted; `.topic-block` at `:241` is one `margin` declaration and would pass identically as `{}`.
**Proposed fix:** Add a small derived companion in the same test module: for each token in `_all_emissions()`, locate its rule body in the comment-stripped CSS and assert the body is non-empty and contains at least one declaration outside `{margin, padding}` — plus a per-class pin for the two load-bearing declarations this milestone shipped (`.status-badge__remediation` contains `display: block`; `.discover-meta` contains `var(--fg-muted)`). ~25 LOC, no new file.
**Regression-guard:** `tests/test_ui_class_css_coverage.py::TestEveryEmittedClassHasARuleOrExemption::test_every_rule_is_substantive` — asserts `.status-badge__remediation`'s body contains `display: block`, and fails on an empty or margin-only body for any emitted class.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M8 — Discover panel discloses no ordering basis; the styled ladder reads as ranked** (MEDIUM)

**Where:** `server/routes/notebooks.py:746`
**Anchor:** `f'<p class="hint">{len(candidates)} new`
**What:** The results are strictly reverse-chronological (`tools/_arxiv_api.py:156` pins `sortBy=submittedDate&sortOrder=descending`), but neither the panel hint nor the fragment says so; m10 then rendered them as a top-to-bottom hairline ladder, which is the visual form a ranked list takes.
**Why it matters:** AC#4's deliverable was the *absence* of a manufactured relevance claim, and the string was correctly refused — but an unlabelled ordered list carries the same implication structurally, and CLAUDE.md §4.9 treats a manufactured impression as the same defect as a manufactured string. An operator who reads the first candidate as the best match is reading a submission date. (The CSS itself is clean here — no `:first-child` privilege, no ordinal, no chip, no "top results" heading, no aria-label implying rank; verified.)
**Proposed fix:** Six words in the string m10's own fragment already builds: `f'<p class="hint">{len(candidates)} new candidate(s), newest first — results are not saved; click Discover to re-run.</p>'`. This is the honest half of the "panel-level query disclosure" the implement synthesis deferred, at one line rather than a query-echo redesign.
**Regression-guard:** `tests/test_notebook_api.py` — assert the discover fragment's hint contains an ordering disclosure ("newest first") and, negatively, contains none of `relevan`, `match score`, `rank`, `best`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** trust language (CLAUDE.md §4.9)

**M9 — Token comment claims a grey migration that did not happen** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:47`
**Anchor:** `token, so the product carried eleven han`
**What:** The comment justifies `--fg-muted` in the past tense — "the product **carried** eleven hand-typed greys (#555/#666/#6f6f6f/#444 …) — the exact hand-picked-value stitch m6 existed to end" — and `.claude/docs/ui-contrast-table.md:174` repeats "the eleven hand-typed greys it exists to replace"; none was migrated. All eleven are still live at `app.css:42, 44, 45, 65, 70, 71, 72, 141` and the dark remaps at `:457-459`.
**Why it matters:** The product now carries twelve muted values instead of eleven, and the two places a future author reads the derivation both imply the stitch is closed. The implement synthesis discloses the deferral honestly, but the synthesis is not what ships — `tokens.css` is. A supporting claim is also false as written: "`#555` on the light card is 7.25:1, so nothing gets lighter" — `--fg-muted` measures 7.004:1, so the two `#555` consumers and `#444` (9.471:1) would all get lighter on migration.
**Proposed fix:** Two clauses in the same comment: change "carried" to "carries", and append "— NOT yet migrated onto this token; the eleven literals at `app.css:42/44/45/65/70/71/72/141` and the dark remaps at `:457-459` are a tracked follow-up, so today the product carries twelve muted values, not one." Same edit in the contrast-table paragraph. Drop or correct the "nothing gets lighter" clause.
**Regression-guard:** Optional. A derived check would be `test_ui_contrast.py` asserting the count of distinct achromatic hex literals in `app.css` is non-increasing across milestones.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity (derivation record accuracy)

**M10 — Five roadmap `links.code` anchors invalidated by the stylesheet growth** (MEDIUM)

**Where:** `plans/ui-uplift/roadmap.yaml:190`
**Anchor:** `code: ["server/frontend/static/app.css:6`
**What:** `app.css` grew 498 → 575 (a 58-line block inserted at 187, a 19-line block at ~302) and `tokens.css` 157 → 179 (+21 at 46, +1 at 162), so five anchors now resolve to unrelated text. Verified line-by-line against `216aff0`: `app.css:267-270` (line 190) was the UPL-27 `.status-badge--ok` note, now mid-comment about `<time>`/`tnum`; `app.css:412-436` (line 532) was the `.htmx-request` in-flight rule, now the `prefers-reduced-motion` reset; `app.css:478-481` (line 572) was the `::view-transition-old/new(root)` duration override, now the four dark pill literals; `tokens.css:132-157` (lines 118 and 301) was the dark `:root` block, now the type-scale comment tail (the block is 153-179).
**Why it matters:** This is the third re-anchor needed today, and three of the five now point at *plausible-looking but wrong* CSS rather than at nothing — a reader following `app.css:478-481` for a view-transition claim lands on status pills and cannot tell the anchor rotted.
**Proposed fix:** Re-anchor via `/roadmap`: `app.css:267-270`→`344-347`, `app.css:412-436`→`412-436` re-derived (the `.htmx-request` rule is now at `489-513`), `app.css:478-481`→`555-558`, `tokens.css:45-62`→`45-72`, `tokens.css:132-157`→`153-179`. **Not fixable in Phase 4** — the one-writer rule reserves `plans/ui-uplift/roadmap.yaml` to `/roadmap`; record this as a `/roadmap` hand-off in the rectify summary rather than editing the file.
**Regression-guard:** N/A (planning artifact, external writer). The durable fix is line-free anchors (`server/frontend/static/app.css` + a selector name), which the m10 row itself already uses.
**Source critic:** milestone-arxmcp-critic
**Source axis:** tier sequencing

**M11 — `--fg-muted` adds a twelfth grey instead of replacing any; dark mode now shows three secondary greys per card** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:162`
**Anchor:** `    --fg-muted: oklch(71.512% 0.008 250)`
**What:** The token is minted and consumed by three m10 surfaces, but none of the eleven hand-typed greys was migrated, so `--fg-muted` now coexists with them on the same cards — in dark mode `.card .hint` renders `#b3b9c0` (8.95:1 on `--card-bg`) and `.discover-meta` renders `#9fa4a8` (7.04:1) inside one `<section class="card">`, while `.card .note`/`.card .empty` at `#9ba1a8` (6.79:1) is within a 1.036 luminance ratio of `--fg-muted` — a difference no reader can resolve and no author can have intended.
**Why it matters:** The milestone's stated purpose for the token is coherence, and shipping it un-migrated inverts that: the Discover card previously had one secondary voice per element role and now has two visibly different ones (8.95:1 vs 7.04:1 is a real dark-mode step), plus a near-duplicate pair, so the product reads as less systematic than before the token existed. Light mode hides this — `#555` vs `#51585f` is a 1.033 ratio — so the regression is dark-mode-only, which is exactly where this track's regressions keep landing.
**Proposed fix:** Migrate in the same track, not "someday": point `.card .hint`, `header .subtitle`, `dl.meta dt`, `.card .empty` and `.card .note` at `var(--fg-muted)` and delete the matching entries from the dark-mode remap rule at `app.css:456-458` (they become inert once the light rule uses a mode-aware token — that is the whole point of minting one). `.card .display-name` (`#444`/`#c9d1d9`) is a *primary* value, not a muted one, and should go to `var(--fg)` rather than `--fg-muted`. If a full migration is too wide for a rectify, migrate at minimum the two greys that render inside the Discover and Topic cards — `.card .hint` and `.card .empty` — since those are the ones now sitting adjacent to `--fg-muted`.
**Regression-guard:** Extend `tests/test_ui_contrast.py` or the token test with an assertion that no `color:` declaration in `app.css` outside the `.status-badge--*` pill family uses a literal hex — the pills are the documented v1 exception; everything else must go through a token.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

---

**M12 — `list-style: none` removes list semantics in Safari/VoiceOver with no `role="list"`** (MEDIUM)

**Where:** `server/frontend/static/app.css:209`
**Anchor:** `.discover-list { list-style: none; margi`
**What:** WebKit deliberately drops the implicit `list` role from a `<ul>` whose `list-style` is `none`, and the fragment emits `<ul class="discover-list">` with no explicit `role="list"`, so VoiceOver stops announcing "list, N items" and stops offering list navigation.
**Why it matters:** m10 introduced this — before the rule, the list had bullets and kept its semantics. On a results surface the item count and "item 3 of 12" position are the primary scanning affordance for a non-visual operator, and the only remaining count is the `.hint` sentence at the top of a region that is announced atomically.
**Proposed fix:** Emit `<ul class="discover-list" role="list">` in `_discover_results_fragment` (`server/routes/notebooks.py:748`). One attribute, no CSS change, no behaviour change for sighted users. The CSS-only alternative — `list-style-type: ""` instead of `none`, which preserves the role in WebKit — is available but less legible to the next reader; prefer the explicit role and keep the comment naming why.
**Regression-guard:** Assert in the fragment test that a rendered candidate list contains `role="list"` whenever `app.css` declares `list-style: none` on `.discover-list` — a derived pairing, like the tabular-nums scope test.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

---

**M13 — Candidate titles carry no heading level; "title" is conveyed by font-weight alone** (MEDIUM)

**Where:** `server/routes/notebooks.py:732`
**Anchor:** `                f'<p class="discover-tit`
**What:** Each candidate's title is a `<p>` distinguished only by `font-weight: 600` at inherited body size, so the results list has no heading structure and the title/meta/abstract hierarchy m10 built is available to sighted readers only.
**Why it matters:** Screen-reader users cannot jump between candidates by heading, which on a list that can run to 200 rows is the difference between scannable and linear; and "information conveyed by type treatment alone" is the accessibility failure mode this milestone's own thesis (a typographic hierarchy) makes most likely.
**Proposed fix:** Change the emitted element to `<h3 class="discover-title">` — the enclosing `<section class="card">` already owns an `<h2>`, so `h3` is the correct level and no other heading in the fragment competes. Add `font-size: inherit` to the existing `.discover-title` rule so the UA `h3` size does not override the deliberate no-size-step decision; `margin: 0` and `font-weight: 600` are already declared, so the rendered result is byte-identical to today.
**Regression-guard:** Assert the fragment emits a heading element (not `<p>`) for `.discover-title`, and that `app.css` pins `font-size: inherit` on it so the rendered size does not drift when the element changes.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

---

**M14 — BAN-9 (multiple primary CTAs per viewport) ships unaddressed on the surface m10 designed** (MEDIUM)

**Where:** `server/frontend/static/app.css:210`
**Anchor:** `.discover-candidate { padding: 0.75rem 0`
**What:** Every candidate row carries a full-accent `<button type="submit">Add</button>` inheriting the single `button { background: var(--accent); color: #fff }` rule, so a viewport showing six candidates shows six primary CTAs — BAN-9, which `final-report.md:67-68` puts on the **must be removed** list — and the milestone's ban audit enumerated BAN-2, BAN-3, BAN-7 and UPL-24 but not BAN-9.
**Why it matters:** `challenge.md:881` scores BAN-9 at 0 in the target state on the strength of "UPL-1's disclosure collapses five forms" — that projection is about the detail page's *forms* and never accounted for a per-row CTA on an unbounded list, so the score is optimistic exactly here. A ladder of accent fills also fights D-1's thesis directly: the Ledger Sheet is a continuous record carried by hairlines, and six saturated buttons are the loudest thing on it.
**Proposed fix:** Give the row action a secondary tier inside m10's own rules — no markup change, no new token: `.discover-candidate button { background: transparent; color: var(--accent); border: 1px solid var(--border); }` plus `.discover-candidate button:hover { background: color-mix(in oklab, var(--card-bg) 92%, var(--accent)); }`, reusing the `color-mix` idiom already at `app.css:132`. The `:focus-visible` ring and the `.htmx-request` loading state both still apply because they are keyed on `button`, not on the fill. Verify the new text/ground pair in `tests/test_ui_contrast.py` (accent on `--card-bg` is 6.20:1-ish in light; register both modes rather than assuming).
**Regression-guard:** Register the `.discover-candidate button` foreground/ground pair in `tests/test_ui_contrast.py::PAIRS` for both modes so the secondary tier cannot regress below SC 1.4.3.
**Source critic:** milestone-frontend-ux
**Source axis:** Experiential motion & distinctiveness (ban-list adherence)

---

**M15 — The panel discloses no ordering, and bibliography styling makes it read as relevance-ranked** (MEDIUM)

**Where:** `server/routes/notebooks.py:746`
**Anchor:** `            f'<p class="hint">{len(candi`
**What:** The results are reverse-chronological (`tools/_arxiv_api.py:156-157` pins `sortBy=submittedDate&sortOrder=descending`) but the panel copy says only "N new candidate(s) — results are not saved", and the new styling makes the list look like arXiv/Semantic Scholar search results, which readers know to be relevance-ranked by default.
**Why it matters:** AC#4 correctly refused to *state* a relevance the data cannot support; this leaves the panel free to *imply* one. An operator who reads the top rows first because "the best matches are at the top" is acting on a rank the feed never produced, and the only evidence to the contrary is a mono, muted, 13px timestamp on the second line of each entry.
**Proposed fix:** Amend the existing `.hint` string to name the ordering — e.g. `f'{len(candidates)} new candidate(s), newest first — results are not saved; click Discover to re-run.'`. Three words, one f-string, no new element, no manufactured evidence: it states the ordering the driver actually applied. Both research briefs proposed this as the honest alternative to a relevance line, and the implement synthesis declined it purely on line budget, which a rectify does not have.
**Regression-guard:** Assert the discover fragment's hint text contains an ordering disclosure whenever the driver's query pins a `sortBy`, so the copy and the query cannot drift apart.
**Source critic:** milestone-frontend-ux
**Source axis:** Microcopy

---

**M16 — H3's abstract/meta size step was dropped; the hierarchy is two steps, not three** (MEDIUM)

**Where:** `server/frontend/static/app.css:219`
**Anchor:** `.discover-meta { margin: 0.25rem 0 0 0; `
**What:** H3 authored `.discover-meta` at `0.8rem` (12.8px) and `.discover-abstract` at `0.875rem` (14px) — distinct steps — and m10 collapsed both onto `--text-small` (13px), so meta and abstract now differ only by family and colour, not size.
**Why it matters:** The milestone's single deliverable is a typographic hierarchy, and the collapse means a candidate reads as two type levels (16px title, 13px everything-else) rather than the three H3 designed; the abstract, which is the content the operator actually judges, is now the same size as the identifier line above it and smaller than the surrounding body text.
**Proposed fix:** Restore the step by removing `font-size: var(--text-small)` from `.discover-abstract` so it inherits `--text-body` (16px) — this is closer to H3's 0.875rem than 13px is, matches the "abstract in body text" that H3's SOTA paragraph describes, and the clamp arithmetic survives unchanged because `4.5em` and the unitless inherited `line-height: 1.5` both scale with the element's own font-size (4.5 × 16 = 72px = 3 × 24px). The alternative — dropping `.discover-meta` to `--text-meta` (11px) — is worse: 11px muted mono for an operator-read identifier is below where this track has been willing to go.
**Regression-guard:** Optional (MEDIUM). If added: assert `.discover-abstract`'s computed step is strictly larger than `.discover-meta`'s in the stylesheet.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

---

**M17 — The run size is 200, not 10; the stylesheet contradicts itself and both the ladder and the live-region announcement are unbounded** (MEDIUM)

**Where:** `server/routes/notebooks.py:748`
**Anchor:** `            f'<ul class="discover-list">`
**What:** `app.css:195` justifies omitting a per-row chip with "a run is up to 10 rows" while `app.css:222` says "up to 200 candidates a run"; the route calls `discover_for_notebook_async(store, slug, contact_email=...)` with no `max_results`, so the `= 200` default (`tools/discover_for_notebook.py:69`) is what ships, and the fragment renders every candidate with no cap, no pagination and no "showing N of M".
**Why it matters:** At ~150px per styled candidate, 200 rows is a ~30,000px unbroken ladder with the only count (`.hint`) scrolled off the top — and because `#discover-results` carries `aria-live="polite" aria-atomic="true"` (`notebook_detail.html:183`, re-emitted by the fragment), the whole thing is announced as one utterance, which with the full abstracts deliberately retained in the DOM is an unskippable wall of speech. The clamp comment presents "the full text stays in the DOM… it is what a screen reader announces" as an accessibility benefit; under `aria-atomic="true"` it is the opposite, and the sighted operator sees three lines while the AT user hears all of it.
**Proposed fix:** Two independent, cheap steps. (1) Correct the false premise: fix the `:195` comment to say 200 and re-check the BAN-7 reasoning against that number rather than against 10. (2) Bound the surface: pass an explicit `max_results` from the route (20–30 is a sane operator page) and state the truncation in the hint copy — "showing the 25 newest of N". A bounded list also bounds the atomic announcement, which is the cheapest available fix for the announcement problem short of restructuring the live region.
**Regression-guard:** Optional (MEDIUM). If added: assert the route passes an explicit `max_results` rather than relying on the driver default, so a driver-side default change cannot silently re-open a 200-row render.
**Source critic:** milestone-frontend-ux
**Source axis:** Information density

---

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

**L3 — `list-style: none` drops list semantics under Safari/VoiceOver** (LOW)

**Where:** `server/frontend/static/app.css:209`
**Anchor:** `.discover-list { list-style: none; margin`
**What:** WebKit removes list semantics from a `<ul>` whose `list-style` is `none`, so VoiceOver stops announcing "list, N items" and item position; the emitted markup (`server/routes/notebooks.py:748`) carries no compensating `role="list"`.
**Why it matters:** A screen-reader operator loses the candidate count and position cues on the one surface that presents external content for judgement — a regression relative to the UA-bulleted list m10 replaced. No WCAG SC is failed, hence LOW.
**Proposed fix:** `<ul class="discover-list" role="list">` in `_discover_results_fragment`. One attribute; no CSS change.
**Regression-guard:** Optional — `tests/test_notebook_api.py` asserting `role="list"` on the discover `<ul>`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L4 — `.topic-category`'s label renders at full `--fg` while its value is muted, inverting the product's label/value convention** (LOW)

**Where:** `server/frontend/static/app.css:242`
**Anchor:** `.topic-category { margin: 0; font-size: `
**What:** `.topic-category` sets no `color`, so the literal label text "Discovery category:" inherits `--fg` (16:1 light, `#d7dbe0` dark) while the operator's own topic prose in `.topic-description` directly beneath it is `--fg-muted` — and the product's other label pattern, `dl.meta dt`, is muted.
**Why it matters:** In a block m10 authored in one edit, the boilerplate label outranks the content it labels, and the same block now carries three text colours in four lines (hint, label at `--fg`, description at `--fg-muted`).
**Proposed fix:** Add `color: var(--fg-muted)` to `.topic-category` so the label matches `dl.meta dt`'s role; the `<code>` value inside it keeps its own treatment and stays the emphasised element. Register the resulting pair in `tests/test_ui_contrast.py` (it is the same token on the same card ground already measured, so this is a row, not a new solve).
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

---

**L5 — The 3-line clamp silently depends on an inherited `line-height` nothing asserts** (LOW)

**Where:** `server/frontend/static/app.css:231`
**Anchor:** `.discover-abstract { margin: 0.25rem 0 0`
**What:** `max-height: 4.5em` yields exactly three line boxes only because `body { line-height: 1.5 }` (`app.css:23`) is unitless and inherits as a multiplier; the rule itself declares no `line-height`, and nothing in the suite pins the coupling.
**Why it matters:** Any future `line-height` on `.card`, `.discover-candidate` or `.discover-abstract` — or a switch to a unit-bearing value — converts the currently clean boundary cut into a partial glyph row, which is the specific failure the implementer's comment claims the design avoids. The claim is correct today; it is just undefended.
**Proposed fix:** Declare `line-height: 1.5` on `.discover-abstract` itself so the clamp's two halves live in one rule, and extend the comment to say the two numbers are coupled (4.5 = 3 × 1.5) rather than leaving the reader to reconstruct it from `body`.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

## What was done well

### From milestone-adversary-critic

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

### From milestone-arxmcp-critic

- **The contrast math is right and I could not break it.** Re-deriving OKLCH→OKLab→linear sRGB→WCAG independently gives 7.004:1 (light) and 7.015:1 (dark) on `--card-bg` against the claimed 7.00 target, and every pill ground clears the 4.5:1 text floor: light warn 6.552, ops-warn 6.409, down 6.384; dark warn 5.429 (the claimed tightest), ops-warn 6.300, down 6.418. The 5.43-vs-5.45 gap is 8-bit quantisation, not an error.
- **Every ground the token renders on is registered, and no ground that does not render was padded in.** I traced all three consumers to their DOM ancestry — `.discover-meta` and `.topic-description` are inside `<section class="card">` on both emitters, and `_classify_status_badge` provably returns only `{ok, warn, ops-warn, down}` so the remediation caption can never land on a background-less base badge. The `ok` pill is correctly excluded because `_build_remediation_block` returns `""` for it. The refusal to register a non-rendering `--bg` pair is the correct discipline, not an omission.
- **The `4.5em` = three line boxes claim holds exactly.** `body { line-height: 1.5 }` is unitless (`app.css:23`), so it resolves against `.discover-abstract`'s own `--text-small`; nothing between `body` and the `<p>` re-sets it. The clamp lands on a line boundary as claimed.
- **AC#4 was refused for the right reason and the reasoning was written into the artifact that ships.** The Atom feed carries no rank in either namespace, the driver pins `sortBy=submittedDate`, and `DiscoveryCandidate` has nowhere to hold a score — three independent checks, all of which I re-verified. The CSS itself adds no `:first-child` privilege, no ordinal, no chip, no icon and no rank-implying label.
- **Three m9 doc-drift findings closed in place rather than deferred**, and the corrected premise for `_css_defines_class` is the true one: the file really does mix bare, compound, element-qualified, comma-grouped and `@media`-nested selectors, and I confirmed comment stripping is sound (zero residual `/*`, comment-only tokens absent, all nine classes matching real rules).
- **The cap raise was done the way the cap tests ask for it** — 520→600 in all three siblings in one commit, historical rationale byte-preserved, merits argued once and cross-referenced, landing at 575 with a 25-line margin instead of m7's 2.
- **Packaging, local-first and no-fork are clean and stayed clean.** No `@font-face`, no `@import`, no `url()`, no CDN, no network fetch anywhere in the diff; the CSP and `_CSP_UI_PREFIXES` are untouched; `pyproject.toml`'s `"server.frontend.static" = ["*.css", ...]` glob plus `tests/test_wheel_packaging.py:222/231` and `tools/wheel_install_check.py:119/125` already cover both stylesheets by name, so the growth ships.
- **Cache byte-stability is untouched by construction** — `server/tools.py`, `server/prompts.py`, every handler and the whole MCP surface are outside the diff, and nothing in the repo hashes or byte-compares the served static asset set, so there is no re-pin obligation.
- **The implement synthesis under-claims rather than over-claims.** It flags its own diff overrun instead of rounding it down, names the browser render as unverified, and lists the unmigrated greys and the missing AC#3 guard as deferrals — three of my findings are sharpened versions of things it disclosed rather than things it hid.

### From milestone-frontend-ux

- **H3's authored design is honoured, not substituted, on four of its five rules.** `.discover-list`, `.discover-candidate` (including the `0.75rem 0` padding and the `1px solid var(--border)` hairline verbatim), `.discover-title { font-weight: 600 }` and `.discover-meta`'s mono+muted treatment all ship as the discovery authored them, with H3's raw `rem` literals correctly translated onto m7's `--text-small` instead of pasted — which is the right call and is exactly the failure mode m7's own critique flagged. The one substitution is the abstract rule (H1/M6).
- **The `:last-child` refinement is a real improvement on H3.** H3's authored `.discover-candidate` would have left a stray hairline against the card's bottom padding; `.discover-candidate:last-child { border-bottom: none }` is a one-line addition that makes the ladder terminate cleanly, and it is the kind of detail that separates a ladder from a table.
- **The truncation arithmetic is correct and I verified it independently.** `4.5em` against the element's own `--text-small` and the unitless inherited `line-height: 1.5` is exactly 3 × 19.5px = 58.5px, so the cut lands on a line-box boundary with no partial glyph row. The refusal of `line-clamp` on Baseline-Limited grounds is consistent with the m6 `light-dark()` and m7 `text-wrap: balance` precedents, and consistency of that bar across milestones is worth more than the individual call.
- **AC#4's absence is argued from the data, three independent ways, and written into the stylesheet.** Refusing to manufacture a relevance basis the arXiv Atom feed does not carry is the correct decision, and recording the refusal at the point of use means the next milestone re-litigates it against evidence rather than against a NotebookLM screenshot. M5 asks for a disclosure of the *real* ordering, which strengthens this decision rather than reversing it.
- **AC#5 was finished rather than met on a technicality.** m7's `font-size` pin satisfied the letter of "a selector exists" while discovery H1's actual defect — an inline `<small>` welded to the side of a 14ch pill — stayed shipped. `display: block` + `margin-top` + `line-height: 1.4` is the caption H1 asked for, and choosing to fix the rendered outcome over the test-visible one is the right instinct.
- **The token was derived, not eyeballed.** `--fg-muted` is OKLCH on the existing brand hue at its own mode's `--fg` chroma, binary-searched against a *named* ground with the ground choice (`--card-bg`, because no consumer sits on the canvas) argued rather than assumed. My own recomputation lands at 7.015:1 light and 7.037:1 dark — the stated targets. M1 is about what was left un-migrated beside it, not about how it was made.
- **The ban list was actively consulted at authoring time.** BAN-2 (card grid), BAN-3 (icons), BAN-7 (per-row chips) and the killed UPL-24 state-history strip are each named in the stylesheet with the reason they were not taken, and I confirmed none of them crept in: there is no chip class, no icon, no grid, no history strip, and no second accent. M4 is a gap in that audit, not an absence of one.
- **The information-density change is a large net win.** Pre-m10 each candidate rendered its full 800–1500-character abstract at 16px in a UA-bulleted list; the styled row is a fraction of that height, which is what makes a multi-candidate run scannable at all. H1 asks for the hidden text to be *recoverable*, not for the clamp to be reverted.
- **`_KNOWN_UNSTYLED` was emptied in the same commit as the CSS**, and the cap raise landed in all three sibling tests with each file's historical rationale byte-preserved — the exact mistake m7's rectify had to catch, avoided deliberately this time.

Severity counts: C0 H3 M17 L5


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **H1, M7** at `tests/test_ui_class_css_coverage.py:119-119` (HIGH): AC#7's empty `_KNOWN_UNSTYLED` has no guard; both self-cleaning tests are vacuous; BAN-R2's predicate still cannot tell a rule from a gesture
- **M1, M12, L3, M14** at `server/frontend/static/app.css:209-210` (MEDIUM): `list-style: none` with no `role="list"` strips list semantics in WebKit; `list-style: none` removes list semantics in Safari/VoiceOver with no `role="list"`; `list-style: none` drops list semantics under Safari/VoiceOver; BAN-9 (multiple primary CTAs per viewport) ships unaddressed on the surface m10 designed
- **H2, H3, M2, L5** at `server/frontend/static/app.css:231-231` (HIGH): Discover abstract clipped with no affordance and no route to full text; Abstract truncated with no reveal affordance and no truncation cue; the abstract clamp hides 800–1500 chars with no affordance and no reveal; The 3-line clamp silently depends on an inherited `line-height` nothing asserts
- **M8, M15, M17** at `server/routes/notebooks.py:746-748` (MEDIUM): Discover panel discloses no ordering basis; the styled ladder reads as ranked; The panel discloses no ordering, and bibliography styling makes it read as relevance-ranked; The run size is 200, not 10; the stylesheet contradicts itself and both the ladder and the live-region announcement are unbounded

## Recommended rectification order

H1, H2, H3, M1, M2, M3, M4, M5, M8, M7, M9, M6, M10, M12, M13, M11, M14, M15, M17, M16, L1, L2, L3, L4, L5

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
