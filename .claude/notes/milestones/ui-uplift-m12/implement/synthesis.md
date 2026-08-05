---
milestone_id: "ui-uplift-m12"
phase: "implement"
phase2_path: "delegated"
implementation_base: "6f5cbbc0be184e65a9ba39d4a4199d9b1971879c"
external_writes_required:
  - "git push origin main"
status: "complete-with-scope-overrun"
injection_attempts: 0
---

# Implement synthesis — ui-uplift-m12 (UPL-1, corpus before machinery, v0)

Scope overrun is recorded separately in `implement/scope-exceeded.md` with the
real numbers and the authored / relocated split. The milestone itself is
COMPLETE and every gate is green; nothing was deferred to make the number fit.

## Built

### AC#1 — the papers table is visible without scrolling past any mutation form

`server/frontend/templates/notebook_detail.html` now emits three regions in
the authored order (`art-direction-scout-brief.md:372`): the record `<section>`
(identity + state), the papers `<section>` (the corpus), then one
`<details class="manage-disclosure">` carrying the five mutation forms in the
authored sequence Topic → Discover → Add-by-URL → Upload → Ingest. The papers
section moved from LAST in source order to second.

**AC#1 is implemented under a NARROWED reading, and this is D1.** The AC says
"without scrolling past **any** input form". There are **SIX** forms on this
page, not the five the roadmap counts: the sixth is `form.rename-form`, inside
the leading identity `<section>`, and it **stays**. Renaming is part of the
record's identity — it belongs with the slug and the metadata that lead the
page — and moving it would pull a control out of the `<section>` landmark
ui-uplift-m8 deliberately created. So the criterion shipped is **"no MUTATION
form above the table"**: rename edits the record's label, not the corpus.

The narrowing is recorded in three places so it cannot decay into an accident:
the template's own m12 note (§2), this synthesis, and
`TestCorpusPrecedesMachinery::test_the_rename_form_stays_above_the_table_and_this_is_recorded`,
which asserts BOTH that rename is above the table AND that the template still
says why. An unrecorded narrowing of an AC is indistinguishable from failing it.

Guards: `tests/test_ui_m12_corpus_before_machinery.py::TestCorpusPrecedesMachinery`
(five parametrized order assertions, one per mutation form; the three-region
count; the rename narrowing) and `TestManageDisclosureNesting`.

### AC#2 — non-terminal or failed ⇒ the disclosure is OPEN

`notebook_detail.html` — the disclosure open tag:

```jinja
<details class="manage-disclosure"{% if not latest_run or latest_run.status != 'success' %} open{% endif %}>
```

The attribute is emitted **BARE**. `open="false"` renders a `<details>` OPEN —
HTML boolean attributes are presence-based — so conditional emission of the
attribute itself is the only correct form. The predicate is *open unless
`success`*, which covers three of `_ingest_status_fragment`'s four branches:
`none` and `running` both keep polling every 2s, and `failed` is terminal but
carries the stderr tail the operator has to read.

Guards: `TestDisclosureOpenState` renders the real page through a FastAPI
TestClient for all four states — three asserting `open` is present, one
asserting it is absent, and a fourth parametrized over ALL FOUR asserting the
string `open=` never appears. A test that only checks the open case does not
catch the `open="false"` inversion; this one does. A source-level companion
pins that the Jinja form is conditional emission of a bare attribute.

### AC#3 — a state cue from the same row the ingest fragment reads

`<summary>Manage this notebook — ingest <code>{{ latest_run.status if latest_run else 'none' }}</code></summary>`

- **Label and cue form are the AUTHORED strings**, recovered from the
  discovery tree rather than invented: `"Manage this notebook"`
  (`art-direction-scout-brief.md:428-430`) and the cue shape
  `"Manage this notebook — ingest running"` (`challenge.md:107`). Both were
  dropped by the roadmap summary. BAN-10 scores 0 on this page and the
  discovery calls that a strength to protect.
- **Same row, by construction.** `server/routes/ui.py:461` passes `latest_run`
  from `store.get_latest_ingest_run(slug)` — the identical method the polling
  endpoint calls at `server/routes/notebooks.py:2283`. No new query, no new
  store method, no route change.
- **Plain text, not a pill and not a heading.** Browsers that map `<summary>`
  to `role=button` treat its children as presentational, so a cue riding the
  accessible NAME is the only form announced by every AT pairing. A status
  pill would also have been BAN-7 (badge soup, currently 0 on this page).
- The `<code>` voice matches the same datum's other rendering at "Last
  indexed" — m7's rectify exists because two paths for one value disagreed.

**Recorded residual:** the cue is a page-LOAD snapshot while the fragment
refreshes every 2s, so a long run can show `running` in the summary over a
settled body. Same row, different read times — accepted for v0.

Guards: `TestSummaryStateCue` (rendered label + cue for all four states;
`latest_run` is the cue's source; both route modules still call
`get_latest_ingest_run`; the two renderings share the mono voice).

### AC#4 — every moved `hx-target` resolves, and no swap lands out of view

All six targets resolve unconditionally (`hx-target="#id"` goes through
`querySelector`, which ignores DOM position and `<details>` open-state). The
AC's real content is its second clause, and the two `beforeend` forms are the
whole of it: both target `#papers-tbody`, which the reorder moves from *below*
them to *above* the disclosure they now live in.

Both now carry `hx-swap="beforeend show:#papers-tbody:bottom"`. The swap KIND
is unchanged; htmx's `show:` modifier scrolls the append point into view, costs
zero CSS lines and adds no dependency. `:bottom` is both the just-added row and
the table edge nearest the disclosure, so the form stays near the viewport.
This is a **sighted-only** fix — the tbody's `aria-live` always announced —
which is exactly why no existing test caught it.

`tests/test_ui_m4_in_place_add_paper.py:367`'s exact-string assertion
`'hx-swap="beforeend"' in form_block` no longer holds and was **re-decided, not
deleted**: it now asserts the swap's first token is `beforeend` (the thing
UPL-12 v0 decided) plus the m12 `show:` requirement, with the reason recorded
inline.

`hx-ext="json-enc"` is preserved on all four JSON forms and rename;
`hx-encoding="multipart/form-data"` on Upload is deliberately NOT normalised.

Guards: `TestSwapTargetsStillResolve` — every `#id` target on the rendered page
exists; both `beforeend` forms carry `show:`; the encodings are untouched.

### AC#5 — no expand animation is claimed or budgeted

Nothing was added. **The roadmap's stated reason is WRONG and is not repeated
anywhere in this milestone.** `::details-content` is **not** Chromium-only: it
is Baseline **newly** across all engines since 2025-09-16 (Chrome 131,
Firefox 143, Safari 18.4, WPT 1.0). Only `interpolate-size` / `calc-size()` are
Chromium-only. AC#5 stands on **Newly-not-Widely** — Widely lands 2028-03-16 —
the same basis on which m6 refused `light-dark()`, m7 refused
`text-wrap: balance` and m10 refused `line-clamp`. The corrected reason is
recorded at both sites (`app.css` and the template), because asserting
"Chromium-only" in a 2026-09 commit would be a checkable falsehood.

The discovery still contains the LOSING side of its own argument — seven live
lines in `synthesis.md` and `art-direction-scout-brief.md` assign
`[MOT-15 accordion-expand]` to UPL-1. `challenge.md` and `final-report.md`
killed it; those two are the record, and the guard says so.

Guards: `TestNoExpandAnimation` — four parametrized absence assertions over
**comment-stripped** `app.css` (`interpolate-size`, `calc-size(`,
`::details-content`, `allow-discrete`), no `transition`/`animation` in any
`.manage-disclosure` rule, and an explicit assertion that m10's
`max-height: 4.5em` clamp is a CLAMP and must not be "harmonised" into a
transition.

## Owner decisions implemented

**D1 — rename stays in the identity block.** Implemented and recorded above;
AC#1 narrowed to MUTATION forms, in the template, here, and in a test.

**D2 — the app.css cap raised in lockstep, 600 → 680.** All three sibling files
moved in the same commit, each **appending** to the raise history it records
rather than being blanket-replaced (m6 400→480, m7 480→520, m10 520→600, now
m12 600→680). `tests/test_ui_m3_dark_and_htmx_feedback.py` carries the merits
argument; the other two point at it, matching how m10's raise was documented.
`app.css` lands at **627 of 680**. `tokens.css` is untouched at 289/290 — m12
mints no token, and the file's rules-forbidden guard makes it the wrong home
anyway.

## The five named risks — what was done about each

1. **Bare `open`.** Emitted via `{% if %}open{% endif %}`. Pinned by a
   render test over all four states asserting `open=` never appears.
2. **`app.css:64-65` is a DIRECT-CHILD selector.** Confirmed and repaired
   deliberately, not worked around. `main > :where(section, div) + section`
   was rewritten **in place** to
   `main > :where(section, div) + :where(section, details)` (0 net lines) so
   the disclosure takes the section rung as a peer region, and a nested rung
   `.manage-disclosure > div + div` restores `--rule-row` to the five moved
   blocks. **A guard shipped with it** —
   `TestRuleLadderReachesEveryRegion` asserts both halves and their rungs,
   because m8's guards check the ladder's tokens and horizontality but never
   its *coverage*, and that absence is why the break was invisible.
   The nested rung also had to be enumerated in
   `TestExemptionIsConditionalPerSite.TINTED_SITES` with its second cue — m8's
   own M1 guard caught it on first run, which is the guard doing its job.
3. **`server/routes/ui.py:280-286`'s prior rejection of `<details>`.**
   Answered at the site, in the template's m12 note §3: onboarding-uplift-m3
   D2 refused a disclosure that would have been INSIDE the swapped element, so
   every `outerHTML` poll destroyed and recreated it. In m12 the polled element
   `#ingest-status` is strictly NESTED inside the disclosure and the
   `<details>` is never a swap target nor inside one, so `open` is never in the
   swapped subtree. The note also records the hard constraint this creates for
   later milestones — **no swap on this page may target the `<details>` or any
   ancestor of it** — and names m13 (which moves `aria-live` onto "a stable
   never-swapped wrapper") as the near-miss.
4. **`TestSectioningElementDecision.DECIDED` pins document ORDER.** Updated as
   a **recorded re-decision with a reason per site**, transcribed the way m8's
   own entry was, not silently re-sorted. `EXPECTED` is unchanged at `(2, 7)`:
   the element decisions are all unchanged, only their order moved.
   `test_every_block_still_opens_with_its_heading` needed no change — all seven
   blocks still open with `<h2>`.
5. **`notebook_detail.html:322`.** Fixed. `"No papers yet. Add one above."` →
   `"No papers yet. Add one from \"Manage this notebook\" below."` — it names
   the affordance the operator has to open, which is what keeps this
   progressive disclosure on the legitimate side of the line. `ui-uplift-m11`
   (UPL-21) still owns empty-state voice and will revisit it; this fixes the
   FACT so the interim page does not lie. Guarded by
   `TestEmptyStateCopyIsNotWrong`. The page's two other "above" strings
   (`Topic & discovery above`, `click Discover above`) refer to siblings whose
   relative order is unchanged inside the disclosure and remain correct.

## A decision the briefs did not make: the five DIVs stay at column 0

Indenting the five moved `<div>`s inside the `<details>` would have dropped
five of the seven per-site element records out of `TestSectioningElementDecision`'s
`^<(section|div)>` view, leaving `DECIDED` as `["section", "section"]`. m8's
own rectify note says *"a decision recorded as a total is not a recorded
decision"*. Keeping them at column 0 preserves all seven ordered per-site
records, and `TestManageDisclosureNesting` pins separately — and explicitly —
that each is inside the disclosure and that the papers table is not. That is
strictly more guarded than indentation would have been. It also avoided roughly
380 lines of pure whitespace churn.

## Deliberately NOT done

- **`#ingest-status` was NOT hoisted out of the disclosure** (brief-2 §5.3's
  alternative). It dissolves AC#2's failure class rather than mitigating it,
  but it moves the region boundary the authored anatomy drew and AC#2/AC#3 both
  presuppose the cue-plus-forced-open design. Recorded as the road not taken;
  it belongs to whoever owns the "state as metered facts" masthead (UPL-5), not
  to m12.
- **A conditional poll gated on `details.open`** (`hx-trigger="every 2s [cond]"`)
  — the other alternative brief-1 named. Rejected for the same reason: AC#2
  specifies the forced-open mechanism.
- **No new token, no new colour pair.** The disclosure reuses `--rule-section`,
  `--rule-row`, `--text-section` and the inherited `--fg`/`--bg`. The contrast
  artifact was regenerated (`uv run python -m tests.test_ui_contrast --update`)
  and is **byte-identical** — 101 pairs, unchanged.
- **No icon.** The native `::marker` triangle is kept (BAN-3 is at 0 and the
  product has zero icons); removing it would also break state announcement in
  VoiceOver + Firefox, where the triangle's direction is the only channel.
- **No `name` attribute** on the disclosure — a shared name opts disclosures
  into exclusive-accordion grouping, and `.discover-abstract` disclosures now
  nest two levels inside this one.
- **The papers `<h2>` row count still does not update on a `beforeend` swap.**
  Pre-existing drift, now observable rather than hidden. Left to `ui-uplift-m13`
  and named in the template.
- **`index.html` untouched** — v0 is the detail page only; the index half is
  hard-paired with UPL-21 per `final-report.md:393-394`.

## Branching note

Commits landed on the **worktree branch `worktree-agent-a3dd54e5846f68c82`**,
NOT on `main`. `CLAUDE.md` §4.1 puts all work directly on `main`, and the agent
protocol says to `git checkout main` first — git refuses:

```
fatal: 'main' is already used by worktree at '/Users/chris.dare/Personal/SourceCode/arXMCP'
```

The shared checkout holds `main`, so the policy is mechanically unavailable
from here. **The orchestrator must rebase / fast-forward this branch onto
`main`.** The worktree was fast-forwarded to `main` before any edit, so HEAD's
parent is exactly the declared `implementation_base`
`6f5cbbc0be184e65a9ba39d4a4199d9b1971879c`. `main` may have moved since.

## Files touched

| path | role |
|---|---|
| `server/frontend/templates/notebook_detail.html` | the milestone — reorder into three regions, the disclosure, the open predicate + state cue, the `show:` modifiers, the empty-state copy, and the three recorded re-decisions |
| `server/frontend/static/app.css` | ladder extended to the third region (in-place selector edit) + nested rung + class-scoped summary rule; 598 → 627 |
| `tests/test_ui_m12_corpus_before_machinery.py` | **new** — m12's guards for AC#1–AC#5 plus ladder reachability, class scoping and the empty-state copy |
| `tests/test_ui_m8_rule_ladder.py` | `DECIDED` re-decided with a reason per site; the new tinted-rung site enumerated with its second cue |
| `tests/test_ui_m3_dark_and_htmx_feedback.py` | app.css cap 600 → 680 (merits argued here) |
| `tests/test_ui_m4_in_place_add_paper.py` | app.css cap 600 → 680; the `beforeend` assertion re-decided for the `show:` modifier |
| `tests/test_ui_m5_create_remove_in_place.py` | app.css cap 600 → 680 |

Not edited, though load-bearing: `server/routes/notebooks.py` (fragment builder
+ poll endpoint), `server/routes/ui.py` (template context), `tokens.css`,
`.claude/docs/ui-contrast-table.md` (regenerated, no delta).

## external_writes_required

```
["git push origin main"]
```

Declared, **not performed**. Push is per-event authorization under
`CLAUDE.md` §4.4 and this agent may not push under any circumstances.

## Test deltas

- **Added:** `tests/test_ui_m12_corpus_before_machinery.py` — 30 test
  functions / 44 parametrized cases across 8 classes.
- **Changed:** `tests/test_ui_m8_rule_ladder.py` (one record re-decided, one
  site enumerated), `tests/test_ui_m4_in_place_add_paper.py` (one assertion
  re-decided, cap), `tests/test_ui_m3_dark_and_htmx_feedback.py` (cap),
  `tests/test_ui_m5_create_remove_in_place.py` (cap).
- **Removed:** none.

## Check gate results

- `ruff check .` — **PASS** (clean).
- `pytest` (full suite, this worktree) — **7 failures, all pre-existing and
  environment-bound; ZERO new.** Measured, not assumed:
  - 6 × `tests/security/test_latexml_sandbox.py` — macOS has no `bwrap`;
    `latexmlc` exits `rc=-6` and the wiring test sees a `bwrap` argv.
  - 1 × `tests/test_arxiv_fetch.py::TestParseWithLatexml::test_win32_bat_invoked_via_perl`
    — `NotImplementedError: cannot instantiate 'WindowsPath' on your system`.
  - **The dispatch's count was 8; the observed count is 7.** The difference is
    `test_cite_neighbors_wired`, which the dispatch itself notes PASSES inside
    a git worktree because a worktree has no `var/` tree. It passed here. This
    is the same correction ui-uplift-m8 recorded — measure the baseline in the
    worktree rather than inheriting the shared checkout's count, or a real new
    failure hides inside the allowance.
- Targeted UI suites (m2, m3, m4, m5, m7, m8, m12, a11y, contrast, class-CSS
  coverage, htmx-json contract, html-pages, notebook-detail-status,
  m3-endpoints) — **all green**.
- **No pass/skip totals are quoted, deliberately.** pytest's final count line
  (`N failed, M passed, …`) is not emitted in this environment — reproduced on
  a single-file run, so it is not a truncation artifact of the full run. The
  failure list above is enumerated exactly from `short test summary info`
  across two independent full runs; `pytest --collect-only -q` reports **4919**
  collected before opt-in deselection. Quoting an invented pass count would be
  worse than reporting the number that was actually observable.
- `git status --porcelain` — **empty** after the commit.
