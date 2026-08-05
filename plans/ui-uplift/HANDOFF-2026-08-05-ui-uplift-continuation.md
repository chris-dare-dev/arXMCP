---
project: ui-uplift
type: handoff
status: complete
authorship: agent-generated
handoff_kind: continuation
date: 2026-08-05
companion: HANDOFF-2026-08-05-ui-uplift-session-review.md
roadmap: plans/ui-uplift/roadmap.yaml
resume_target: any
tags:
- project/ui-uplift
- type/handoff
- authorship/agent-generated
- handoff/continuation
- project/arxmcp
aliases:
- ui-uplift — continuation handoff (2026-08-05)
---

# CONTINUATION HANDOFF — ui-uplift (2026-08-05)

> **Audience:** a fresh session picking up ui-uplift. The companion review handoff
> ([[HANDOFF-2026-08-05-ui-uplift-session-review]]) covers *what shipped and why* — THIS doc
> says **exactly where to resume and what is left**. Roadmap: `plans/ui-uplift/roadmap.yaml`.
>
> The review handoff opens by noting no continuation doc existed and calling that a smell.
> An external principal-engineer review (ChatGPT-5.6 Sol) independently reached the same
> finding. This closes it.

## 0. Resume state in one paragraph

`ui-uplift-m12` is at **`rectify-running`** and is **NOT complete**. Its findings register
holds 25 findings: **3 fixed** (H1, H2, M2), **22 open**. The completion gate
(`milestone-pipeline-findings.py gate ui-uplift-m12`) exits 3 on **H3**, the one open HIGH.
Nothing about m12 may be described as done, and the milestone must not advance to
`complete`, until H3 is fixed, deferred, or invalidated through the sanctioned writer.

## 1. What changed after the review handoff was written

The review handoff was written, reviewed externally, and then acted on. Two things landed
that it does not describe:

### arXMCP#382 — reopened and re-closed (round 2)

The review found that the round-1 fix, which the handoff presents as closed, left a second
hole. `_declaration_names` counted declaration sites with `.match()`, which returns at most
once per physical line — but **Lean reads commands, not lines**. Verified against real
`leanprover/lean4:v4.29.0`:

```
def harmless : Nat := 1 axiom evil : False
-->  'harmless' does not depend on any axioms
     'evil' depends on axioms: [evil]
```

Pre-fix the extractor returned `(['harmless'], True)` and the record read **`clean` with a
live `axiom` inside it**. The `namespace` / `section` / `end` branches were the same hole:
they consumed their line and `continue`d, so a declaration behind a scope command was never
counted at all (`end N axiom evil : False` and `section axiom evil2 : False` both register
their axiom — both confirmed live).

Fixed by counting **every** start-, whitespace- or `]`-preceded declaration keyword on the
line before any branch can `continue` past it, plus masking string-literal interiors in
`_strip_comments` so prose in a string cannot manufacture a phantom site. 11 unit
regressions + 1 wire-level regression in `tests/test_handlers_lean_verify.py`
(`TestMultipleDeclarationsOnOnePhysicalLine`). CLAUDE.md §4.10 rule 3's measured table gained
two rows and is still pinned by `test_claude_md_table_matches_live_behavior`.

**The standing lesson, and why this bullet exists:** every revision of this parser has failed
by assuming a shape — first "an `in` combinator", then "a line is a declaration". Over-counting
sites is free; it can only move `complete` True -> False. When in doubt, count.

### m12 H2/M2 — closed behaviourally, not just in the comment

Round 1 corrected the false "the cue cannot drift from the fragment by construction" comment
and deliberately kept the page-load snapshot, recording it as an owner-accepted tradeoff. On
re-review the owner's decision was **fix it properly**. `_ingest_status_fragment` now appends
a top-level `<code id="ingest-state-cue" hx-swap-oob="true">` carrying that branch's own
literal token, so every response that re-renders the body re-renders the cue: the 2s poll
(H2's direction), the terminal 286 that stops it, and the 202 that starts a run in-page
(M2's sharper direction). Guarded by `TestSummaryCueIsRefreshedOutOfBand`, including a
top-level-position guard — a **nested** `hx-swap-oob` is inert and fails exactly like the
original bug.

## 2. Resume here — ranked

1. **m12 H3** — the only open HIGH and the only thing the gate blocks on. "Collapsing the
   disclosure hides the ingest error path with no recovery." Note that the m12 rectify
   round-2 work above changes its shape: hoisting live ingest status out of the disclosure
   would close H3 and was the review's suggested remedy for H2/M2 as well. Consider whether
   the OOB cue already partially satisfies it before re-implementing.
2. **The AC#1 contradiction — OWNER DECISION REQUIRED, do not resolve unilaterally.**
   `notebook_detail.html` declares AC#1 narrowed to "no mutation form above the table", but
   the canonical AC at `plans/ui-uplift/roadmap.yaml:455` still reads "without scrolling past
   any input form", and `form.rename-form` is above the table. One of the two must move.
   The template's rationale (rename belongs with the record's identity) is defensible; it is
   still a narrowing of a canonical AC that the roadmap does not record. **m12 must not be
   completed with the contradiction intact.**
3. **The 12 remaining open MEDIUMs and 9 LOWs** — `findings.py summary ui-uplift-m12` is the
   live list; do not work from any copy of it in prose, including this one.

## 3. External review findings NOT yet actioned

The external review raised four beyond #382 and m12 H2/M2. All were independently reproduced
and confirmed; none is fixed. They are recorded here because they are **not** in any milestone
findings register — m6, m7, m8 and m10 are all closed milestones.

| Sev | Milestone | Finding | Disposition |
|---|---|---|---|
| MEDIUM | m10 | `server/routes/notebooks.py` puts the identical `abstract_head` in both `<summary>` and `<p>` of `details.discover-abstract` — an 800–1500 char disclosure control | Use a bounded label ("Show abstract") or a short lede in `<summary>`; add a guard that summary != body and that the control name is bounded |
| MEDIUM | m8 | `TestExemptionIsConditionalPerSite`'s `TINTED_SITES` is a hand-maintained dict of free-text cues. The guard skips selectors absent from CSS, never validates the cue string, and accepts any padding/margin declaration including `padding: 0` | Keep the exemptions (defensible by inspection); replace free-text proof with exact selector existence, positive spacing, and rendered-DOM assertions |
| LOW | m7 | `base.html`, `tokens.css` and `test_ui_m7_type_scale.py` all assert custom properties "must be declared before the rules that `var()` them". **False** — custom properties resolve through the cascade and computed value; defining stylesheet order is irrelevant | Keep the link order as convention; delete the load-bearing claim and stop enforcing order as correctness |
| LOW | m6 | `.claude/docs/ui-contrast-table.md:258` states the rejected inset alternative spans 3.044:1–3.902:1 across "all seven" pills; independent recomputation gives 3.044:1–**4.311:1** over eight rendered variants | Correct the artifact or regenerate the rejected-alternative numbers. The shipped `border-color` flash remains the right decision either way — only the measurement is wrong |

**Not independently re-derived by this session:** the m6 contrast arithmetic. Everything else
in that table was reproduced against the working tree before being recorded.

## 4. Do not repeat these

- **A finding is not "fixed" when only its documentation is corrected.** m12 H2/M2 were marked
  `fixed` for a comment correction while the behaviour persisted; the register's own resolution
  text admitted it ("the defect was the claim, not the tradeoff"). If a tradeoff is being
  accepted, the status is `deferred` with the owner's sign-off — never `fixed`.
- **Do not commit a milestone checkpoint without its register.** `dfa3b1e` recorded
  `phase: implement-complete` with no critics and no `findings.json` in the tree, while the
  real critique, register and `rectify-running` state sat dirty and untracked. A checkpoint
  that omits the register claims less work AND less remaining work than is real.
- **`.claude/notes/milestones/.lock` is runtime state**, now gitignored. It names a PID on one
  box. Leave it on disk during a run; never commit it.

## 5. Verification at this handoff

- `tests/test_handlers_lean_verify.py` — 155 passed, 12 skipped.
- `tests/test_ui_m12_corpus_before_machinery.py` — 58 passed.
- `ruff check .` — clean.
- Full suite — see the commit that lands this file; re-run rather than trusting this line,
  per CLAUDE.md §3's standing warning about hand-maintained counts.
- **Not pushed.** Per CLAUDE.md §4.4 push is per-event authorization; the commits on `main`
  are local until the owner authorizes each push.
