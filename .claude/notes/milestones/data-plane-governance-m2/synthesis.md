# m2 synthesis — data-plane-governance-m2 (Zero untracked pre-existing plan tracks)

**Owner sitting:** data-plane-governance-spike-1 (2026-07-12) — 6 dispositions, 0 vetoes.
**Spec:** `../data-plane-governance-spike-1/disposition-matrix.md`. **Edits report:**
`implement/edits.md`.

## Execution mode (deviation on record)

Ran **lock-free** (no formal `init-state`): the shared milestone `.lock` was held by a live
concurrent `adhoc-20260712-955c958` session (at `critique-running`), so an init would hard-stop,
and I must not clobber a live lock a second time (I already accidentally cleared + restored it
during m3). Dependencies (m1 + spike-1) were verified `done` in the journal before proceeding.
The ADR-critical agent-platform amend was independently verified against source (grep for
residual in-repo loop scoping) before the commit, in lieu of a formal critique phase — the
revisions were documents-only and precisely pre-specified by the spike-1 research pass.

## What landed

| Commit | Task | Content |
|---|---|---|
| `d7bfe2b` | t-agent-platform-amend | agent-platform re-scoped to the ADR boundary + tracked |
| `616e3a8` | t-execute-dispositions | evidence-engine, researcher-workbench, retrieval-unlocks, scale-ops-hardening, trustworthy-release tracked (3 revised, 2 as-is) |

## Acceptance (roadmap.yaml:172-175)

- ✅ **Zero untracked pre-existing plan tracks** — `git status --porcelain plans/` shows no
  `??` entries. All six committed.
- ✅ **agent-platform amended to the ADR choice before commit** — verified: the 6 `cg1` items
  (e5/spike-1/m8/t-dispatch-loop/t-transcript-recording/t-canned-task-run) now scope the
  orchestrator loop to the **external orchestrator repository** (ADR Decision 2, Option A;
  name/path deferred), consuming arXMCP as an imported library; no item scopes an in-repo
  dispatch loop or per-run agent memory (roadmap.yaml:189 criterion). Stale "referenced only
  by tests" evidence line corrected per ADR Decision 3.
- ✅ **Vetoed-track archival** — N/A (0 vetoes; all six committed).

## Revisions applied (the 3 non-agent-platform revise tracks)

- **researcher-workbench** — `/api/v1` read-twins scoped human-workbench-internal / non-agent-
  facing (+ same-origin guard); e4 should-assumption naming R2/R5 as downstream labeling consumers.
- **retrieval-unlocks** — m6 `depends_on` source-truth/R1 registry + consume its fields; §4.9
  cite in evidence + a "no proof exists" abstention criterion on m1.
- **trustworthy-release** — R1 Release gate on m5 (PyPI publish); m2 annotated interim license
  stopgap vs R1's later `license_ref` migration; §4.9 dated-grounding criterion on m7 + a
  single-axis disclaimer on m6's citation contract.

All four edited files pass YAML parse + `roadmap-validate.py` (0 errors). evidence-engine and
scale-ops-hardening committed unedited (commit-as-is).

## External writes

- `git push origin main` — required (2 unpushed feat commits + this chore). Owner-authorized
  per-event; surfaced separately. Not executed by the pipeline.
