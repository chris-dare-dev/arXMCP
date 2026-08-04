---
project: discovery-substrate
type: handoff
status: complete
authorship: agent-generated
handoff_kind: continuation
date: 2026-07-29
companion: HANDOFF-2026-07-29-discovery-substrate-session-review.md
roadmap: plans/discovery-substrate/roadmap.yaml
resume_target: any
tags:
- project/discovery-substrate
- type/handoff
- authorship/agent-generated
- handoff/continuation
- project/arxmcp
aliases:
- discovery-substrate — continuation handoff (2026-07-29)
---

# CONTINUATION HANDOFF — discovery-substrate (2026-07-29)

> **Audience:** a fresh session picking up `discovery-substrate`. The companion review handoff
> ([[HANDOFF-2026-07-29-discovery-substrate-session-review]]) covers *what shipped and why* —
> THIS doc says **exactly where to resume**. Roadmap: `plans/discovery-substrate/roadmap.yaml`.
>
> **Program goal:** give arXMCP a representation of the negative in two of its three directions —
> retrieve the literature's own recorded negatives from a precision-measured mining substrate, and
> compute one through a Lean refutation lane — while paying the fidelity debt where ingest already
> produced signal that serving discards.

> [!warning] Do not start `discovery-substrate-m1` yet.
> The RESUME-HERE step below is **not** the roadmap's first milestone. It is a 4-owner-day
> measurement (**#378**) that decides whether this roadmap's ordering is right at all. Every score
> in the analysis that produced this roadmap is a *prior, not a measurement*, and the two
> adversarial judges disagreed at the root. Running m1 first is not wrong — it is *unfalsifiable*.

## 1. Current state (as of this handoff)

| Milestone | Status |
|---|---|
| **#378 discovery-backtest (P2)** | ⬜ **← RESUME HERE** — filed, not started, `gate:owner` |
| `discovery-substrate-m1` — sentence layer, marker table, lexicon format, sampler | ⬜ next (lane `now`, #216) |
| `discovery-substrate-m2` — boundary markers reachable, precision published | ⬜ blocked on m1 + spike-1 (#217) |
| `discovery-substrate-spike-1` — lexicon precision dry run, 50 hand-scored matches | ⬜ lane `now` (#224) |
| `discovery-substrate-spike-2/3` — figure asset-kind scan, equations-table materialization | ⬜ lane `now` (#225, #226) |
| `discovery-substrate-m3..m8` | ⬜ lane `next` — fidelity debt, Lean hygiene, refutation lane |

Live facts, as of `974ca5c` (pushed; `origin/main == HEAD`, 0 ahead):

- **Board:** 377 issues, 12 milestones. `plans/` holds roadmap/1 directories only.
- **Nothing in this roadmap has been implemented.** All 23 items (#211–233) are open and unstarted.
- **`make test` was NOT run this session.** `ruff check .` is clean and pytest *collection* is
  clean; the full suite was never executed. Treat green as unverified.
- Working tree carries **23 `M` entries that are permanent** — the Obsidian stamper writes
  frontmatter, the clean filter strips it, so `status` says modified while `diff` is empty. They
  cannot be committed away. Do not "fix" them.

## 2. RESUME HERE — #378, the discovery backtest

**Goal:** find out whether arXMCP could have reached a *known, dated* published result from a
corpus frozen before that result's date — and record, per ingredient, which of four things was
true.

**Already decided (do not relitigate):**

- Three cases, ~1 owner-day each. Fewer is not enough to exclude; more is not affordable.
- **The ingredient decomposition is committed to git BEFORE the harness runs.** This is the
  hindsight-bias control and it is the entire validity of the exercise. Decompose from the
  *published account only*.
- The four verdicts are fixed: `reachable-in-k-calls` / `present-but-unretrievable` /
  `absent-from-corpus` / `unanswerable-by-current-surface`.
- Results are recorded as a dated, scoped census per `.claude/docs/evidence-ledger-standard.md`
  (Accepted 2026-07-12) — **extend it with a claim class, never fork a second schema.**

**Why the four verdicts are the deliverable, not the pass/fail:** they map onto four *different*
investments. `present-but-unretrievable` argues for the mining substrate (this roadmap).
`unanswerable-by-current-surface` argues for new tool surface. `absent-from-corpus` argues for
ingest breadth and says nothing about retrieval at all. Today those are indistinguishable, which
is precisely why 31 proposals were ranked on argument.

**A suggested first case,** because its mechanism is unusually legible: the Batyrev stringy-Hodge
counterexample (Satriano–Usatine, arXiv:2607.19184, 2026‑07‑21). Its ingredients are a moduli
space `M₀` (rank-2 semistable bundles, trivial determinant, genus-3 curve), the product with `ℙ¹`,
and — the load-bearing one — **an existing closed-form stringy E-function from Kiem–Li 2004**. Ask
whether a corpus frozen 2026‑07‑01 could have surfaced that formula given the conjecture. That
single question is a sharper test of this roadmap's thesis than any of its own acceptance criteria.

**Gate:** `gate:owner`. The 3 decompositions (~3 of the 4 days) are mathematical reading and are
not automatable. Do not hand them to an agent.

## 3. Definition of done for #378

- [ ] 3 ingredient lists committed **before** any harness run (check `git log` order — this is
      auditable and should be audited)
- [ ] Per-ingredient verdicts recorded from the fixed four-token vocabulary
- [ ] A written verdict on the judges' disagreement: objects/compute axis, mining/hygiene axis, or
      neither is supported
- [ ] Census recorded per the evidence-ledger standard, with the **scope stated honestly** — n=3
      can *exclude*, it cannot *rank* six themes
- [ ] `plans/discovery-substrate/progress/agent.jsonl` appended
- [ ] The roadmap's lane assignments revisited **in light of the result** — that is the point of
      running it

## 4. Remaining epics / milestones

- **e1 (m1, m2, spike-1) — span substrate + first measured lexicon.** The prerequisite nine
  separate proposals each silently assumed. Ships sentence ids, ONE shared markers table, the
  lexicon YAML format, and a precision sampler. **Gate to advance:** spike-1 hand-scores 50
  matches; if per-class precision misses the bar *committed before scoring*, e2 is not funded.
- **e2 — the remaining miners as data files.** Only becomes cheap once e1 exists. Deliberately
  lane `later`: its shape depends on spike-1's precision number, so specifying it now would be
  fiction.
- **e3 (m3, m4, m5) — fidelity debt.** Figure lane (1,483 in-math TikZ across 120/173 papers),
  corpus-wide notation view (661/3,429 divergent symbols), `ascii_form` (written as `""` at both
  call sites). Each scope-set by a Wave-0 measurement, not assumption.
- **e4 (m7, m8) — the Lean refutation lane.** `plausible` is installed and unreachable.
  **Externally gated** on R3-m1/m2/m5/m7; spike-4 measures the cold-vs-warm `import Mathlib` gap
  against the 30 s timeout. Do not promote to `now` on schedule pressure.
- **e5 (m6) — formal-result hygiene.** Library identity on every Lean result (grep for
  `mathlib_rev`/`toolchain` over the 42 KB handler returns **0**). RICE-ranked #1 at 6.4 — S-sized
  with a *verified* defect, so `c=0.8` where everything else sits at the 0.5 no-evidence default.
  **Must ride the next batched `TOOL_SCHEMA_VERSION` re-pin (W1 / `agent-platform-e2`)** — do not
  mint a separate re-pin.

## 5. Cross-cutting follow-ups (landmines)

1. **`source-truth/roadmap.yaml` fails its own validator** — `tombstones` check, pre-existing, not
   introduced by the materialization. Three registry-synced artifacts contradict each other:
   `roadmap.md` Iron rule 2 says a dropped item *keeps* its entry; `roadmap-validate.py:238` says
   it must not; `roadmap-to-github.py` *needs* it present or a tombstone can never reach the board.
   The converter's requirement is operative. **Fleet-level decision, not a local fix.**
2. **`lean-repl-observability-m1`'s `state.json` reads `rectify-running`** although its close-out
   triple landed (`8844bd4` → `101bd4f` → `54232e0`). `milestone-pipeline-status.sh` will report it
   in-flight forever. Another session's artifact — left uncorrected deliberately.
3. **`--backfill-done` closes `done` but not `dropped`.** #261/#266 were created open and closed by
   hand as *not planned*. Bites again on the next tombstone-bearing roadmap.
4. **102 residual architecture findings are filed (#12) but unowned.** 34 high, 54 medium, 14 low.
   Nine higher-severity ones are separately under #7.
5. **Concurrent sessions push to this repo.** Two rebases were needed this session. Always
   `git fetch` + check file overlap before pushing; never `checkout --` another session's
   uncommitted work.
6. **The registry converter fix must not be re-broken.** `type:milestone` now lives in
   `claude-registry` (`7ededf6`), synced to 7 consumers. Editing the local synced copy creates
   drift and `sync-repos.py --check` will flag it.

## 6. Environment / resume notes

- **Python:** `.venv/Scripts/python.exe` on this Windows box. The `uv run` guidance in CLAUDE.md
  §4.5 references a macOS path that does not exist here.
- **Tests:** `ruff check .` clean at `974ca5c`. Full pytest **not run** — do this before trusting
  any "green" claim.
- **Board:** project #3 `arXMCP - Delivery`, 12 views. `Pipeline queue` (view 8) is the runnable
  set: `is:open label:"type:milestone" lane:"Now" -label:blocked`.
- **Brief resolution:** archived prose tracks now live in `.claude/roadmap/*.md`, which is inside
  `milestone-pipeline-resolve-brief.py`'s legacy glob — `/milestone-pipeline <old-id>` still works.
- **Views and group-by are web-UI only** — GitHub exposes no `createProjectV2View` mutation.

## 7. Key values you'll need

    origin/main            974ca5c  (0 ahead, GPG-signed)
    roadmap                plans/discovery-substrate/roadmap.yaml   (23 items, phase complete)
    issues                 #211–#233   (this roadmap)
    RESUME HERE            #378        (discovery backtest, gate:owner)
    milestone #7           Boundary hardening — 9 verified must-fixes
    milestone #8           Discovery substrate — this roadmap
    milestone #12          Architecture review residual findings — 102 items
    architecture review    .claude/notes/scans/architecture-review-2026-07-29.md
    capability analysis    .claude/notes/scans/discovery-capability-gap-analysis-2026-07-29.md
    corrections record     .claude/notes/scans/review-corrections-2026-07-29.md
    evidence-ledger std    .claude/docs/evidence-ledger-standard.md   (Accepted 2026-07-12)

*Full review of what shipped: [[HANDOFF-2026-07-29-discovery-substrate-session-review]].*
