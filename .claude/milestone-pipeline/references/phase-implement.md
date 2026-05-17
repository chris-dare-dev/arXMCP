# Phase 2 — Implement

**State precondition:** `state.phase == "research-complete"`.

**State postcondition:** `state.phase == "implement-complete"`,
`state.implementation_path` set, `state.implementation_commit_range` set,
`state.implementation_commits` populated, project check command green.

## Step-by-step

1. Read once at phase start:
   - This file
   - `state.research_synthesis` (the merged brief — full read)
   - `references/agent-prompts.md` (only if path is `delegated`)
2. Pick the implementation path using the decision tree below.
3. Record the choice and the base commit:
   ```bash
   checkpoint.py {ID} --set 'implementation_path="inline"'  # or delegated/specialist
   checkpoint.py {ID} --set 'implementation_base="<sha>"'
   ```
4. Transition: `checkpoint.py {ID} implement-running`.
5. Execute the chosen path (below).
6. Run the project check command (detect order below). Must be green
   before exit. If not green, do not advance state — debug, fix, retry.
7. Persist results and transition:
   ```bash
   checkpoint.py {ID} --set 'implementation_branch="<branch>"'
   checkpoint.py {ID} --set 'implementation_commits=["<sha1>","<sha2>"]'
   checkpoint.py {ID} --set 'implementation_commit_range="<base>..<head>"'
   checkpoint.py {ID} --set 'external_writes_required=[...]'  # refined from research
   checkpoint.py {ID} implement-complete
   ```

## Decision tree

```
size? size = LOC + files-touched estimate from research synthesis
├── ≤ 500 LOC across ≤ 5 files
│   AND no novel architecture
│   AND no specialist match
│   → INLINE: main session implements directly.
├── matches a specialist agent's domain (helm, security, etc.)
│   AND the project has the specialist
│   → SPECIALIST: dispatch ONE specialist agent. NO worktree —
│     specialists work in the main repo.
│   (Note: arXMCP currently has NO specialist agents. This path is
│    reserved for future and unused on this project today.)
└── otherwise
    → DELEGATED: dispatch 1–2 general-purpose Sonnet implementers in
      worktrees with assigned branches. If 2, partition the work along
      a clean module boundary; the orchestrator merges branches at the
      end.
```

## Project check command — detect order

Try in this order; first hit wins:

```bash
if [ -f Makefile ] && grep -qE '^(test|check):' Makefile; then
    make test    # E01_S01 will land 'make test'; until then this fails through
fi
ruff check . && pytest -q   # bootstrap fallback (Python 3.11+, ruff, pytest)
```

Once E01_S01 lands a Makefile, `make test` becomes the canonical command.
The skill should re-detect on every Phase 2 entry — don't cache the
choice across runs.

## Inline path

The orchestrator (main session) reads the synthesis, edits files,
writes/updates tests, runs the check command, commits. One commit per
logical unit of work. Conventional commits, GPG signed, never
`--no-verify`. Co-author trailer:
`Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

## Delegated path

1. Pick a branch name: `milestone/{ID}` (or `milestone/{ID}-part1`,
   `milestone/{ID}-part2` if partitioning).
2. Spawn implementers in `isolation: worktree`. Each gets the
   Implementer prompt from `agent-prompts.md` with substitutions.
3. Implementer's output:
   - One or more local commits on the assigned branch
   - `implementation-summary.md` at the declared path
   - Returns `{path, status, summary}` only
4. Orchestrator merges branches (if more than one) in the main repo,
   re-runs the check command, and records the final commit range.

If TWO implementers run in parallel they MUST be dispatched in one
assistant turn (same rule as Phase 1).

## Specialist path

Dispatch ONE specialist agent (matched by milestone shape) directly in
the main repo — no worktree, because specialists usually need to read
project context across files the worktree might not contain.

This path is unused on arXMCP today (no specialist agents exist). It
remains documented so adding a specialist is a one-line dispatch
change rather than a redesign.

## Hard rules

- **Acceptance criteria are the contract.** Every checkbox in the
  milestone brief either gets a verifiable artifact or stays unchecked
  with a written reason in `implementation-summary.md`.
- **Tests are not optional.** New code → new tests. Bug fix →
  regression test that fails on the old code, passes on yours.
- **Project check command must exit 0 before phase advance.**
- **Conventional commits, GPG signed.** Never `--no-verify`. Hook
  failure is a real failure to investigate.
- **Stop at the external-write boundary.** No `git push`, no
  `gh issue create`, no infra apply. Phase 4 gates that.
- **External writes the milestone requires** are written to
  `state.external_writes_required`. The orchestrator surfaces this list
  to the user in Phase 4. Set it in this phase even if Phase 1 already
  populated it — your final list wins.

## Don'ts

- Don't introduce abstractions the milestone doesn't require. Three
  similar lines beats a premature helper.
- Don't add backwards-compatibility shims for code paths the milestone
  is the first to introduce.
- Don't ship half-done implementations. If an acceptance criterion
  can't be met, leave it unchecked and explain — don't fake it with a
  TODO.
- Don't push to remotes. That's Phase 4's call, gated on user OK.
