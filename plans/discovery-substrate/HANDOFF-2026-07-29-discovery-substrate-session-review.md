---
handoff_kind: review
date: 2026-07-29
companion: HANDOFF-2026-07-29-discovery-substrate-continuation.md
roadmap: plans/discovery-substrate/roadmap.yaml
reviewer_target: opus
review_status: requested
milestones_covered:
- discovery-substrate-e1
- discovery-substrate-e2
- discovery-substrate-e3
- discovery-substrate-e4
- discovery-substrate-e5
tags:
- handoff/review
- review/requested
aliases:
- discovery-substrate — review handoff (2026-07-29)
---

# HANDOFF (REVIEW) — discovery-substrate session, 2026-07-29

> **Audience:** a high-effort Opus review session. **Goal:** independently scrutinize what this
> session shipped — correctness, safety, whether the "done" claims are honest, and the program
> direction. This is a REVIEW handoff (find problems); the companion
> ([[HANDOFF-2026-07-29-discovery-substrate-continuation]]) is for the next builder.
>
> **Reviewer, read this first:** the session that produced this work also wrote this handoff. It
> is self-assessment and should be treated as an interested party's account. The strongest single
> reason to audit it is §3 — three claims where the session corrected *itself* mid-flight, which
> establishes that its first answers were wrong at least three times.

## 0. TL;DR — what this session did

| # | Work | Repo(s) | Key SHAs | State |
|---|---|---|---|---|
| 1 | Architecture review — 8 readers → 8 refuters → 3 judges | arXMCP | — (analysis only) | 110 findings |
| 2 | Discovery capability gap analysis — 6 lenses → screen → 2 judges | arXMCP | — | 26 capabilities |
| 3 | `discovery-substrate` roadmap authored via the 4-phase pipeline | arXMCP | `f854e97` | 23 issues #211–233 |
| 4 | Board remediation — labels, milestones, fields, views | arXMCP | `82b6e44` | 3→22 labels in use |
| 5 | Registry `type:milestone` fix + fleet sync | claude-registry + 7 | `7ededf6` | 9 repos labelled |
| 6 | Co-author trailer de-hardcoding | registry + 3 | `591fc16`, `54183b6`, `a8268aa`, `da7e4d8` | 5 repos correct |
| 7 | 3 unrecorded roadmaps materialized create-and-closed | arXMCP | `6b9b8c9` | #234–275 |
| 8 | 11 legacy prose plans archived | arXMCP | `8a2a228` | `plans/` roadmap/1-only |
| 9 | Scans filed; 102 residual findings filed | arXMCP | `974ca5c` | #12, 102 issues |

16 signed commits across 8 repos, all pushed. `origin/main == 974ca5c`.

## 1. Where to point the audit first

**A. The `discovery-substrate` roadmap rests on unmeasured priors.** Every RICE score is
`c=0.5` except e5. The two judges disagreed at the root and nothing settled it. The roadmap was
authored anyway, and its lane assignments encode one judge's view. **Is authoring a 23-item
roadmap before the measurement (#378) defensible, or should the roadmap have been held?** The
session's own answer — file the measurement as the blocking next step — may be rationalization.

**B. The 102 residual findings were filed by the same process that produced them.** No
independent pass confirmed they are all real, non-duplicate, or correctly severity-calibrated. The
refuters verified the *reader* findings; the 32 refuter-found ones were **verified by nobody**.
Spot-check those 32 hardest — they are labelled in each issue body.

**C. The architecture review's synthesis agents never ran** (spend limit). Its completeness
section is the session's own account of its own gaps. **What did nobody look at?** `tools/` (36
files, 11.9k LOC), the Makefile's ~32 KB of targets, `infra/`, `server/schemas/` were never opened.

**D. Severity calibration.** Everything was scaled to "single-user local-first OSS tool". That
scaling is load-bearing across 111 filed issues and was applied by the same judgement that wrote
them. If it is wrong, it is wrong 111 times.

**E. No test suite was run.** `ruff` clean, pytest *collection* clean, 161 doc-placement tests
pass. The full suite was never executed this session despite 16 commits landing.

## 2. Specific claims worth trying to break

| Claim | Where | How to attack |
|---|---|---|
| Backup is broken at 4 layers and has never run | #202, #203 | Verify `_BACKUP_STATES` vs `FINAL_STATUS` yourself; confirm `var/arxmcp/ops/backup-status.json` truly absent |
| Tier-2 cache serves `k=5` payload for `k=50` | #204 | The comment claims the embedding disambiguates `k`. Confirm it cannot. Write the failing test |
| `axiom h : False` returns `status=ok` | #205 | grep returned 0 hits for any axiom audit — but *run it* against the live kernel |
| All 42 items in 3 roadmaps were terminal | `6b9b8c9` | Journals were the evidence. Were epics/tasks *inferred* rather than journaled? (Yes — check the inference) |
| All 11 legacy plans complete | `8a2a228` | `proof-verify-handler-wiring-m5` has **no state.json**; completeness was read off its own heading |
| The 21 `M` entries are permanent, not debt | continuation §1 | Verify the clean-filter mechanism rather than taking it on trust |

## 3. Corrections the session made to itself (audit these hardest)

A process that corrected itself three times probably did not catch a fourth.

1. **"The counterexamples came from search over objects."** Wrong. Batyrev was literature
   synthesis on an existing Kiem–Li 2004 closed form; Tao states the Jacobian example was not
   brute-forceable. This **demoted the CAS-bridge proposal** — a ranking change driven by a
   correction, so the corrected ranking deserves scrutiny.
2. **"The `formal-conjectures` join is novel."** Retracted. R5's 2026‑07‑11 census already scoped
   it and R7-KR1 owns it. The root cause was not knowing arXMCP has **three** planning layers
   (issues / `plans/*/roadmap.yaml` / `.claude/roadmap-briefs/R0–R7`). **Ask what else was
   proposed without checking layer 3.**
3. **"78 findings, 69 residual."** Wrong by 45% — the true total is 110, because the 32
   refuter-found findings were omitted from the count. **A counting error of that size in the
   headline number suggests checking the other headline numbers.**

Full record: `.claude/notes/scans/review-corrections-2026-07-29.md`.

## 4. Judgement calls a reviewer may reverse

- **102 findings filed individually** rather than batched. Board 274 → 376. Defensible or noise?
- **42 issues created-and-closed** purely for historical record (#234–275). Worth it?
- **Legacy plans moved to `.claude/roadmap/`** rather than a new archive dir — forced by a
  registry-synced glob. Correct, or should the registry have changed instead?
- **~30 historical references deliberately left pointing at old paths.** Preserving dated records
  over grep-cleanliness. Same call made for the `Claude Fable 5` critique notes.
- **`lean-repl-observability-m1` left in `rectify-running`.** Deference to a concurrent session, or
  leaving a known-broken state machine?
- **Co-author trailer deviation.** 8 commits used `Claude Opus 5` against docs demanding other
  models. The session then changed the docs. Right order?

## 5. What was NOT done

- Full `make test` — not run.
- No independent completeness pass on the architecture review.
- The `source-truth` tombstone validator failure — diagnosed, deliberately not fixed.
- The 32 refuter-found findings — never adversarially verified.
- `agent-ready` labels — never applied; the pipeline-queue view relies on lane + `type:milestone`.
- Per-area board views — one template documented, not created.

*Where to resume building: [[HANDOFF-2026-07-29-discovery-substrate-continuation]].*
