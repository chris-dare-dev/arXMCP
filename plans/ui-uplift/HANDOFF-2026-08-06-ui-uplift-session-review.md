---
project: ui-uplift
type: handoff
status: complete
authorship: agent-generated
handoff_kind: review
date: 2026-08-06
companion: HANDOFF-2026-08-06-ui-uplift-continuation.md
roadmap: plans/ui-uplift/roadmap.yaml
reviewer_target: opus
review_status: requested
milestones_covered:
- ui-uplift-m6
- ui-uplift-m7
- ui-uplift-m8
- ui-uplift-m10
- ui-uplift-m11
- ui-uplift-m12
- ui-uplift-m13
tags:
- project/ui-uplift
- type/handoff
- authorship/agent-generated
- handoff/review
- review/requested
- project/arxmcp
aliases:
- "ui-uplift — review handoff (2026-08-06)"
---

# HANDOFF (REVIEW) — ui-uplift session, 2026-08-06

> **Audience:** a high-effort reviewer session. **Goal:** independently scrutinise everything
> below against the diffs — correctness, safety, and specifically whether the "done" claims are
> honest. Companion: [[HANDOFF-2026-08-06-ui-uplift-continuation]].
>
> This session BEGAN as the response to an external principal-engineer review (ChatGPT-5.6 Sol)
> of the previous one. That review's seven findings were all reproduced and are all closed. Treat
> this document as the next link in that chain, not as a fresh claim of correctness.

## 0. TL;DR — what this session did

`origin/main` `54f3cd3` → **`e8f149d`** (20 commits).

- **arXMCP#382 reopened and re-closed.** The round-1 fix left a second hole; a third, in the
  scope-command branches, was found here and was in nobody's report.
- **ui-uplift-m12 rectified in full** — 3 of 25 findings closed → 25 of 25, gate exits 0.
- **Four external-review findings** against CLOSED milestones (m6, m7, m8, m10) fixed.
- **A `/roadmap` pass** — 39 stale line anchors re-resolved to literal anchors, m11 rescheduled,
  a lint added.
- **ui-uplift-m13 run end-to-end** and complete.
- **ui-uplift-m11 shipped, critiqued DO-NOT-SHIP, and REVERTED.**
- **arXMCP#383 filed and fixed** — every `hx-on` handler in the console had been dead for months.

## 1. arXMCP#382 — the axiom audit, round 2

**Commit:** `99c856b`. **Files:** `server/handlers/lean_verify.py`,
`tests/test_handlers_lean_verify.py`, `CLAUDE.md` §4.10.

`_declaration_names` counted sites with `.match()`, which returns at most once per physical line.
Lean reads COMMANDS, not lines. Verified against real `leanprover/lean4:v4.29.0`:
`def harmless : Nat := 1 axiom evil : False` registers both, and the extractor returned
`(['harmless'], True)` → the record read **`clean` with a live axiom in it**.

A second instance, in nobody's report: the `namespace`/`section`/`end` branches consumed their
line and `continue`d, so a declaration behind a scope command was never counted. `end N axiom evil
: False` and `section axiom evil2 : False` both confirmed live.

### What to SCRUTINIZE

- The fix counts every start-, whitespace- or `]`-preceded declaration keyword. **Find a Lean
  form that still slips past it.** Over-counting is safe (it can only move `complete` True→False);
  under-counting is the bug. String-literal interiors are masked in `_strip_comments` — check that
  masking cannot itself hide a real declaration.
- CLAUDE.md §4.10's table is pinned by `test_claude_md_table_matches_live_behavior`. Verify the
  two new rows are measured, not transcribed.

## 2. ui-uplift-m12 — 22 findings closed

**Commits:** `f235443`, `e8d2056`. Register: 25 fixed, 0 open, 0 deferred.

Six findings (M4, M5, M6, M7, M8, M9) were **one defect wearing six hats**: a structural invariant
asserted, then checked with a regex over CSS or template text. All were mutation-proven false by
the original critics. They now assert against a real element tree built with `html.parser`.

### What to SCRUTINIZE

- `TestStructuralInvariantsHoldInTheRenderedTree` and `TestRegionThreeIsNamedAndReachable` —
  **5 mutations were verified to fail them.** Find a sixth that should fail and does not.
- The **AC#1 amendment** in `roadmap.yaml`. The AC text was moved rather than the form, on the
  argument that the milestone's own summary already scoped it to "the FIVE mutation forms". Judge
  whether that is a legitimate correction or a milestone editing its own exam paper.
- `TestCapCommentsCarryNoAbsoluteLineCount` — it found two more stale counts on its first run.
  Check the allow-list for past-tense records is not a loophole.

## 3. The four external-review findings (m6, m7, m8, m10)

**Commits:** `c98cff5`, `6e27da1`, `8a14df1`, `75666d1`.

- **m6** — the rejected inset-overlay contrast range was wrong (3.044–3.902 over "seven"; truth is
  3.044–**4.311** over **eight**). Root cause was structural: the numbers were allow-listed as
  un-driftable "historical" values when they are recomputed from live tokens. Now a GENERATED
  region.
- **m8** — `TestExemptionIsConditionalPerSite` proved none of what it claimed. Rewritten;
  **6 of 6 injected regressions caught**.
- **m7** — a false CSS claim in FOUR places (the review found three). Custom properties resolve
  through the cascade; declaration order across sheets is irrelevant.
- **m10** — the abstract was rendered twice at full length; `<summary>` is now a bounded lede.

### What to SCRUTINIZE

- **I reported the m6 10% fill-tint claim as also wrong, then corrected myself** — I had computed
  it against the wrong model. Re-derive both models independently and confirm the final table.
- m8's `_selector_subjects` parses CSS selectors with regex. Find a selector shape it mis-parses.

## 4. ui-uplift-m13 — live-region hygiene

**Commits:** `73d5ef9`, `2fdd74b`, `e8f149d`. Register: 4 fixed, 0 deferred.

The rule m1 established (*the swap result must re-declare the region*) is correct for a
user-triggered swap and wrong for a timer. m13 split the rule on that axis. Its own critique found
`#status-badge` had the identical defect at 10s on every page — that was NOT in the ACs.

### What to SCRUTINIZE

- **The whole milestone rested on regions that could not receive text** (see §6). The `<output>`
  migration and the `.error:empty` fix were unverifiable until `d53e284` landed — a milestone
  whose value was gated on a bug nobody had found yet. **Judge whether m13 should have been
  called complete in that state.**
- Finding **M2** is now CLOSED with browser evidence (`e8f149d`): six empty `<output>` blocks at
  height 0px, padding 0px, transparent background. Verify the measurement rather than the claim.

## 5. ui-uplift-m11 — shipped, then REVERTED

**Commits:** `3338b43` (shipped), `672e799` (critique), `a2f7cad` (revert).

**This is the most important section for a reviewer.** Two critics returned two independent
CRITICALs.

- **C1 — the commit disarmed five guards while its body claimed each reconciliation was made
  "deliberately, not blanket-updated".** The new form sat earlier in document order than the real
  Add-by-URL form, and five guards resolve "the add-paper form" by first match. Mutating the real
  form's `hx-swap` to `innerHTML` — repealing m12 AC#4 — left all 518 UI tests green.
- **The design premise was false and checkable in seconds.** "The papers empty state is the one
  case with no other reachable control" — the Manage disclosure renders `open` on every first-run
  notebook, exactly when the empty state shows.

The revert was verified, not assumed: the C1 mutation fails two guards on the reverted tree.

### What to SCRUTINIZE

- **Was reverting right, or was rectifying cheaper?** 27 findings on a false premise argued for
  revert; a reviewer may disagree.
- The revert deliberately KEPT the roadmap count correction (four→three) and the notes tree, and
  dropped the AC narrowing. **Check that split is coherent** and that no orphan reference to the
  reverted code survives.

## 6. arXMCP#383 — every `hx-on` handler was dead

**Commit:** `d53e284`.

`::` in `hx-on` already expands to `htmx:`, so `hx-on::htmx:response-error` bound
`htmx:htmx:response-error`. Twelve attributes. **No error surface in `/ui/` had ever displayed
anything; no form had ever reset.** Present since the m2/m4/m5 era.

### What to SCRUTINIZE

- **This is the highest-risk change in the session.** It re-arms seven error paths at once, and
  none was observed working. If any handler has a second latent bug, it surfaces now.
- `tests/test_ui_hx_on_event_names.py` derives htmx's normaliser AND event vocabulary from the
  bundle, and pins the transcription so an htmx upgrade fails loudly. **Attack that pin.**
- The `index.html` empty-row removal hook was among the dead ones — and m11's commit body cited it
  as the *working* precedent. Check nothing else in the repo still cites a dead handler as proof.

## 7. Cross-cutting durable gotchas + decisions

1. **The session's defining defect: guards that assert presence, not behaviour.** It recurred five
   times independently. Every guard added or rewritten here was mutation-tested; ask whether that
   discipline is real or performed.
2. **Two real bugs came from outside reviewers, not from self-review.** The one milestone whose
   critique phase was skipped (m11) is the one that had to be reverted. That is the strongest
   evidence in this session for the 4-phase pipeline.
3. **Phases were run INLINE, not via the critic sub-agents,** for m13 and for m11's phases 1–2.
   m11's Phase 3 did use two sub-agents. Where a critique says "inline self-adversarial", read it
   as one pass by the author, not three independent critics.
4. **m11's `state.json` phase history is not chronologically honest** — I advanced it in bulk to
   match reality rather than re-running phases. Timestamps cluster.

## 8. Verification evidence (as of handoff)

- Full suite: **the documented 8 environment-bound failures, no new ones**, re-run after every
  commit. `ruff check .` clean. `roadmap-validate.py` OK; roadmap lint 17 pass.
- `findings.py gate` exits 0 for m12 and m13.
- Mutation testing: m8 6/6, m12 5/5, m13 6/6, #383 1/1 (+control), m11 revert 1/1.
- **A browser pass ran after this section was first written (`e8f149d`), and it corrected a
  claim this document made.** The original text here read "No browser or AT was available" and
  listed every visual claim as derivation. That was FALSE and is the session's own last mistake:
  the preview pane renders `file://` as static snapshots, and I generalised that into "no
  browser", which is what justified deferring m13's M2. Pointing the pane at the real server
  works — see the continuation handoff for the recipe.

  **Now verified against the running server:** arXMCP#383's fix (a real 409 fills
  `#create-error`, a surface that had never displayed anything); m13's M2 (six empty `<output>`
  blocks at height 0px, padding 0px, transparent — in the a11y tree, no visual footprint); and
  the m13/m12 live-region structure in the rendered DOM.

  **Still derivation, and a reviewer should treat it as such:** announcement behaviour (needs a
  real screen reader), m10's abstract lede (needs a live arXiv discovery call), and
  narrow-viewport layout. **Scrutinise how the "no browser" claim survived a whole session
  unchallenged** — it is the same failure shape as everything else this session found: an
  assertion nobody re-tested.

## 9. How to review (repro + response contract)

```bash
cd ~/Personal/SourceCode/arXMCP
git log --oneline 54f3cd3..d53e284
/Users/chris.dare/Library/Python/3.9/bin/uv run --extra dev python -m pytest -q --tb=line
~/.elan/bin/elan run leanprover/lean4:v4.29.0 lean <snippet.lean>   # for §1
```

Please respond with a per-item verdict (SHIP / SHIP-WITH-FIXES / NO-GO), each finding carrying
the command or file:line that reproduces it. **Refute rather than confirm** — the highest-value
output is a claim in this document shown to be false. Two of this session's best findings came
from exactly that, and the previous review's did too.
