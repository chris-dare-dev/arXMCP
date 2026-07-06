# Phase 2 — Implement (sequential)

## Goal

A single coherent implementation satisfying the roadmap item's acceptance
criteria, with the repo's check gates green and clean conventional commits.

## Decision tree

After reading `research/synthesis.md`, decide the path BEFORE writing code:

```
estimated diff ≤ 300 LOC AND ≤ 5 files AND no novel architecture
  → inline (main session writes)

estimated diff 300–800 LOC OR > 5 files OR novel architecture
  → delegated (1× milestone-implementer in a worktree)

estimated diff > 800 LOC
  → ABORT. Surface to user: split into sub-milestones via /roadmap,
    or re-run with --allow-large-diff.
```

Phase 2 has only `inline` and `delegated` — no specialist build paths.

## Mid-flight scope checks

Both paths re-check after each significant edit:

```bash
git diff --stat <BASE_SHA>..HEAD | tail -1
```

If LOC ≥ 350 OR files ≥ 6: STOP. Commit partial-but-coherent progress with
subject `feat(<scope>): partial — milestone <id> scope exceeded`, write
`implement/scope-exceeded.md`, leave the phase at `implement-running`, and
surface to the user. Scope-exceeded is a return status, not a phase.
**Never silently lane-switch inline ↔ delegated** — restarting in delegated
mode is a deliberate user decision after surfacing.

## Check gates (end of phase)

The consuming repo's CLAUDE.md defines the canonical gates (build, tests,
linters) — run every gate that touches the diff. All applicable gates green
is the contract for Phase 3 to start; a red gate is a blocker, never a
warning. Always: `git status --porcelain` empty after the final commit.

## Hard rules

- Conventional commits: `<type>(<scope>): <subject>`, imperative, ≤ 50 chars
  after the prefix, no period. Types/scopes per the repo's CLAUDE.md.
- Co-author trailer per the repo's CLAUDE.md on every commit.
- Honor signing + hooks: NEVER `--no-verify`, NEVER `--no-gpg-sign`, never
  `--amend` a pushed commit. Unresponsive signing infra = abort, not bypass.
- Branching per the repo's CLAUDE.md. Main-only repos: delegated implementers
  `git checkout main` inside the worktree (worktrees share refs) and cite the
  rule in their synthesis; aborted work goes to the worktree branch instead.
- One-writer rule: the implementation NEVER touches `plans/*/roadmap.yaml`
  status or progress journals.
- `external_writes_required` must be populated in state by end of phase — the
  research value carried forward plus anything new the implementation
  introduced.

## State reads / writes

Reads: `phase`, `research_synthesis`, `external_writes_required`,
`allow_large_diff`.

Writes (via `checkpoint.py`): transition `research-complete →
implement-running`; `implementation_base`; `implementation_path`;
`implementation_plan` (inline path); `implementation_commit_range`;
`implementation_commits` appended per commit; `implementation_branch`
(delegated, when not main-only); transition `implement-running →
implement-complete`.

## Synthesis — `implement/synthesis.md`

Written by the orchestrator (inline) or the implementer (delegated; the
orchestrator then sanity-checks it):

```markdown
# Implement synthesis — <id>

## Built
- <bullet per acceptance criterion: how satisfied, file:line>

## Branching note
<branch commits landed on, citing the repo CLAUDE.md rule>

## Files touched
- <path> — <one-line role>

## Deferred
- <what the milestone deliberately left out>

## external_writes_required
- <list, or []>

## Test deltas
- <test files added/changed>

## Check gate results
- <gate>: PASS / SKIP (reason)
- git status: clean
```

## Don't

- Don't switch lanes mid-flight. Abort, surface, let the user decide.
- Don't use `--allow-large-diff` past 800 LOC without recording why in
  `implement/scope-exceeded.md`.
- Don't skip a gate because "it's slow".
- Don't let a delegated implementer soldier on with an inadequate brief —
  `brief-inadequate` is a return status; route it back to Phase 1.
- Don't write any critique content in Phase 2 — the critic runs next and
  must be independent.
