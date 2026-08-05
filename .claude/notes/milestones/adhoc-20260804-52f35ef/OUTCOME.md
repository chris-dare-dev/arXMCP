# Outcome — adhoc-20260804-52f35ef

**Stopped at `research-complete`. No implementation, and none is coming here.**

## What happened

Phase 1 was asked to research building `arXMCP/contract/` — the seven contract
schemas plus `mfc validate` / `mfc lint-schemas` — on the authority of
bridgeland-stab-lean's ADR-0007.

Both researchers independently found that ADR-0007's every positive argument
cites `_pipeline/stage-1-discovery/synthesis/target-architecture.md`, which
does not exist: not in arXMCP, not anywhere under `~/Personal/SourceCode`,
never in arXMCP's git history. Nor do the things it was cited as specifying —
no artifact-type registry, no `GET /bridge/contracts`, no
`.claude/references/bridge/` in `personal-website`, the repo named as the
vendoring precedent. `explore` added the independent contradiction: none of the
seven filled instances carry the `bridge.*` envelope that document is said to
mandate.

## Disposition

ADR-0007 was withdrawn; Q2 was reopened and re-answered as
**`math-formal-contract-lean`** (ADR-0009). **arXMCP gains no `contract/`
directory.** The implementation happens in a repo this pipeline does not
govern.

This milestone is therefore closed as **research-only**. It produced no diff
here and requires none.

## Value delivered

The research phase paid for the whole pipeline run. Had Phase 2 started on
schedule, `arXMCP/contract/` would exist, in the wrong repo, against a
withdrawn decision, and the missing document would have gone on being cited.
The briefs also corrected the milestone brief's own false premise — that the
seven schemas were "copy-pasteable"; only `emission` fully is, and five of
seven must be authored from filled instances.

Artifacts worth keeping: `research/brief-1.md`, `research/brief-2.md`,
`research/synthesis.md`.

## Note for the next run

`isolation: worktree` researchers write their briefs into the worktree, and
untracked files do not propagate back to the main tree. The briefs had to be
copied out of `.claude/worktrees/agent-*/` by hand at fan-in. Worth handling in
the phase-research reference.
