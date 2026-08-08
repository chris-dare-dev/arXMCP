---
handoff_kind: continuation
date: 2026-08-05
companion: HANDOFF-2026-08-05-ui-uplift-session-review.md
roadmap: plans/ui-uplift/roadmap.yaml
resume_target: any
tags:
- handoff/continuation
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

`ui-uplift-m12` is **`complete`**. Its register holds 25 findings: **25 fixed**, **0
deferred**, **0 open**, and `milestone-pipeline-findings.py gate ui-uplift-m12` exits 0.

The two `/roadmap`-owned deferrals were closed by a `/roadmap` pass on 2026-08-05. **M10** —
all 39 line-number anchors in `plans/ui-uplift/roadmap.yaml` were re-resolved to
`path#<literal>` form; the damage was worse than filed (twelve pointed at unrelated comment
blocks, several written the same day), and each item's intended target was re-derived from
its own title and summary. **L4** — `ui-uplift-m11` moved to start at `ui-uplift-m12`'s
`target_end`, its AC#2 amended from the now-unsatisfiable "ships WITH it", and the six
milestones whose `state.json` reads `complete` were finally given `status: done` in the
roadmap, which only tracked m1–m5.

Both are guarded by `tests/test_roadmap_links_resolve.py` — repo-local, because
`.claude/scripts/roadmap-validate.py` is registry-synced and must not be edited here.

**One deliberate exception to the one-writer rule is on the record:** `roadmap.yaml` *was*
edited in Phase 4, for AC#1's text only, on explicit owner instruction — an
acceptance-criterion correction resolving a contradiction with the shipped page, not an
anchor re-resolution. It is annotated in the AC's own comment.

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

1. **`ui-uplift-m13`** (live-region hygiene) is next by `depends_on`. **Read
   `notebook_detail.html`'s HARD CONSTRAINT note before starting it.** m13's roadmap summary
   prescribes "Move `aria-live` onto a stable never-swapped wrapper", which is exactly the
   shape that kills m12's AC#2 mechanism — a swap targeting the `<details>` or any ancestor
   re-renders `open` from the server predicate every 2s and the disclosure snaps back. That
   is now **enforced**, not just documented
   (`TestStructuralInvariantsHoldInTheRenderedTree`), so m13 will fail loudly rather than
   silently. The guard's failure message quotes the history.
2. **`ui-uplift-m11`** owns empty-state copy and its AC#1 forbids "a pointer to a form
   elsewhere on the page". m12 used to hard-pin exactly that property; the guard was relaxed
   to a direction-agnostic form (M9), so m11 is now free to satisfy its own AC. The durable
   half — the copy must not point *upward* — is retained and m11 cannot legitimately reverse
   it.

`findings.py summary ui-uplift-m12` is the live register; do not work from any copy of it in
prose, including this one.

## 3. External review findings against CLOSED milestones — ALL FOUR FIXED

The external review raised four beyond #382 and m12 H2/M2, against milestones (m6, m7, m8,
m10) that are closed and have no findings register to hold them. All four were independently
reproduced and then **fixed on 2026-08-05**. Recorded here because there is nowhere else.

| Sev | Milestone | Finding | Resolution |
|---|---|---|---|
| MEDIUM | m10 | `server/routes/notebooks.py` put the identical `abstract_head` in both `<summary>` and `<p>` of `details.discover-abstract`. A `<summary>` is the disclosure's accessible NAME and `abstract_head` is the untruncated abstract (800–1500 chars), so the control was named with a whole abstract and — since `[open]` releases the clamp — opening it rendered that abstract twice | `_abstract_lede()` bounds the summary to 120 chars on a word boundary, ellipsis only when text was actually cut, `"Abstract"` when there is none. Body keeps the full text once. Four guards incl. summary != body and no-duplicate over the real builder |
| MEDIUM | m8 | `TestExemptionIsConditionalPerSite` proved none of what it claimed: it `continue`d past selectors absent from the CSS, never asserted anything about the cue string, tested `"tbody" in selector` as proof of table semantics, and accepted `padding: 0` | Rewritten. Cues are a closed vocabulary of checkable KINDS, not prose; selectors must exist verbatim and still paint a rung; spacing values are parsed and required positive; structural claims are proved by walking element ancestry in the shipped templates. **Mutation-tested: 6 of 6 injected regressions caught**, including the two the review demonstrated |
| LOW | m7 | `base.html`, `tokens.css`, `test_ui_m7_type_scale.py` **and a fourth site the review did not find** (`test_ui_html_pages.py`) asserted custom properties "must be declared before the rules that `var()` them". False — they resolve through the cascade at computed-value time | Claim deleted in all four places; link order kept and documented as convention. Both order guards renamed and reduced to asserting both sheets are linked. The real failure mode (a 404 collapsing every `var()`) keeps its own guard |
| LOW | m6 | `ui-contrast-table.md` stated the rejected inset alternative spans 3.044:1–3.902:1 across "all seven" pills | Confirmed wrong by independent recomputation: **3.044:1–4.311:1 over eight** variants. "Seven" counted only the literal pills and dropped token-sourced light `--down`; `3.902:1` is light `--ok`, not the maximum. Now a GENERATED region — the numbers had been allow-listed as un-driftable "historical" values, which was the actual defect, since a rejected alternative is recomputed from live tokens |

**Two things the review did not catch, found while fixing these:**

- The same doc's "6 of 8 pill texts under 4.5:1" for the *shipped-then-rectified* 30% fill
  tint matches neither ground on current tokens (`--bg` gives 5 of 8, `--card-bg` gives 7 of
  8). Its companion `3.095:1` was measured against `--card-bg`, the ground the badge had
  before `ui-uplift-m8` deleted `.card`. Both annotated; the live figure is now generated.
- The m7 claim had a **fourth** site, `tests/test_ui_html_pages.py`.

**Corrected mid-session, for the record:** an earlier note in this session said m6's 10% fill
tint claim was also wrong. It is not — that figure was computed against the wrong model (inset
over the pill instead of replacement over the page ground). The 10% tint clears 4.5:1 on all
eight variants and was rejected on visibility, exactly as the artifact said.

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
