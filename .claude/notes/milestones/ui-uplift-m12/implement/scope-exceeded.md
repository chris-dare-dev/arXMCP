---
milestone_id: "ui-uplift-m12"
phase: "implement"
threshold_loc: 450
threshold_files: 14
observed_loc_total: 848
observed_files: 7
work_state: "complete — nothing deferred"
---

# Scope exceeded — ui-uplift-m12

The dispatch set a ~450-LOC / ~14-file stop line. The diff is **848 changed
lines across 7 files**, i.e. ~1.9× the LOC threshold and half the file
threshold. The numbers below are measured, not estimated, and split so the
overrun is not overstated *or* understated.

## The real numbers

Measured at the commit, against base `6f5cbbc`.

| file | + | − | churn |
|---|---|---|---|
| `server/frontend/templates/notebook_detail.html` | 169 | 66 | **235** |
| `tests/test_ui_m12_corpus_before_machinery.py` (**new**) | 489 | 0 | **489** |
| `tests/test_ui_m8_rule_ladder.py` | 35 | 1 | 36 |
| `server/frontend/static/app.css` | 30 | 1 | 31 |
| `tests/test_ui_m4_in_place_add_paper.py` | 24 | 5 | 29 |
| `tests/test_ui_m3_dark_and_htmx_feedback.py` | 17 | 3 | 20 |
| `tests/test_ui_m5_create_remove_in_place.py` | 6 | 2 | 8 |
| **total** | **770** | **78** | **848** |

### The split that matters

- **124 lines are pure RELOCATION, not authored content.** 62 lines of the
  papers `<section>` are byte-identical on both sides of the diff — the move
  from last position to second is the milestone, and git counts it twice.
  Verified by set-comparison of added vs deleted lines, not by eyeball.
- **489 lines are the NEW GUARD FILE.** No production behaviour; 30 test
  functions / 44 parametrized cases covering AC#1–AC#5 plus the two blockers
  the milestone inherits (ladder reachability, disclosure class scoping) and
  the empty-state copy.
- **Authored non-test change is 142 lines** — 111 in the template
  (107 new + 4 replaced, excluding the relocation) and 31 in `app.css`.
- **93 lines are the four sibling-test edits** (three cap raises + two
  re-decided assertions), which D2 required to land in this same commit.
- **No generated artifact is in this diff.** `.claude/docs/ui-contrast-table.md`
  was regenerated and came back byte-identical, so unlike ui-uplift-m10 the
  total is not inflated by a re-rendered table.

**Honest reading:** the milestone's own hand-written product change is ~142
lines. The overrun is carried by the new guard file and by git double-counting
a block move.

## Why the abort protocol was not followed literally

The protocol says "commit partial-but-coherent work". **There is no
partial-but-coherent state here**, for the same structural reason
ui-uplift-m8 recorded in the implementer's lessons file:

- The reorder alone fails `TestSectioningElementDecision.DECIDED` (order
  changed), fails the ladder (the five moved blocks leave `main`'s child list
  and lose rule + margin + padding), and ships a page whose empty state points
  the wrong way.
- The `<details>` alone overruns the app.css cap at 598/600, which is red in
  three test files simultaneously.
- Step 4 of the protocol forbids committing over a red gate.

So the minimum coherent unit is: reorder + disclosure + ladder repair + cap
raise + the m8 order re-decision + the copy fix + guards. That is what shipped.
Splitting it would have produced a red intermediate commit, which the protocol
forbids more strongly than it forbids the overrun.

## What was trimmed before accepting the overrun

Not nothing — the first pass was measurably larger and was cut deliberately:

- The new guard file went **612 → 489 lines** by condensing docstrings that
  restated rationale already recorded at the decision site, and collapsing the
  section banners.
- The template's three comment blocks were cut ~14 lines; the `app.css` block
  ~9 lines.
- **Indentation was refused**, saving ~380 lines of pure whitespace churn.
  The five moved `<div>`s stay at column 0, which is *also* the better
  decision on the merits — see the synthesis: indenting them would have
  dropped five of the seven per-site element records out of
  `TestSectioningElementDecision`'s view.

No guard, no acceptance criterion and no recorded decision was dropped to hit
a number. Trimming further would have started deleting the record, which is
the failure mode this track has hit repeatedly.

## What remains (nothing)

All five acceptance criteria are implemented and guarded; both owner decisions
(D1, D2) are implemented and recorded; all five named risks are addressed;
`ruff` is clean and the suite shows zero new failures. **Nothing is deferred
into a follow-up.**

Items deliberately out of scope and named in the synthesis rather than left
implicit: the `index.html` half (v1, hard-paired with UPL-21), hoisting
`#ingest-status` out of the disclosure (brief-2 §5.3's alternative), the
papers `<h2>` row-count drift on `beforeend` (pre-existing, m13), and the
`ui-uplift-m11` target-date inversion (a roadmap defect for `/roadmap`, not
for Phase 2).
