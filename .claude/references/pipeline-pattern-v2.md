# Pipeline pattern

The architecture pattern for multi-agent pipelines on the fleet. This file is
the decision record and the constitution for isolation and dispatch; the
commands and agents are the enforcement. Read it when you need to decide HOW
a pipeline dispatches work, not WHAT a given phase does.

## Two generations (decision record)

| Generation | Orchestrator | Dispatch | When it fits |
|---|---|---|---|
| Gen-1 | A slash-command running in the MAIN session | `Task`-dispatched subagents, per-agent project memory | Interactive, human-in-the-loop, one work unit at a time |
| Gen-2 | A background `.mjs` workflow | Programmatic agent dispatch, unattended | Large batch fan-out over many work units, no human in the loop |

Every pipeline shipping today (`/roadmap`, `/milestone-pipeline`) is Gen-1: a
slash command orchestrates from the main session and dispatches subagents with
the `Task` tool. Gen-2 is a background `.mjs` that programmatically dispatches
agents to fan out over many work units without a human watching each step --
this very port is being run as a Gen-2 job.

Gen-2 is documented here as an architectural OPTION, not a runtime that ships
in every consumer repo. Do not assume a workflow runtime is present, and do
not invent a workflow API surface -- describe the pattern generically:
interactive and human-gated work chooses Gen-1; unattended batch fan-out
chooses Gen-2. Both obey every rule below.

## Orchestrator / leaf split (subagents cannot spawn subagents)

A subagent cannot dispatch another subagent. Only the orchestrator -- the main
session in Gen-1, or the `.mjs` in Gen-2 -- holds dispatch. Leaf agents get NO
`Task` tool; for example `milestone-researcher` carries only
`Read, Grep, Glob, Bash, WebFetch, WebSearch, Write`.

Consequences that follow directly from this constraint:

- Fan-in is NEVER delegated. The orchestrator reads each returned file itself
  and synthesizes; it cannot hand synthesis to a subagent.
- Phase 4 rectification is main-session only. A rectifier delegate exists as
  an exception path, but the DISPATCH of it stays with the orchestrator.

This is the canonical home for the rule stated tersely elsewhere as
"Sub-agents do NOT spawn other sub-agents (platform-blocked)".

## Worktree isolation (legitimate only for tracked files)

`isolation: worktree` is legitimate ONLY when parallel agents mutate TRACKED
files in the SAME repo. A per-agent worktree branch keeps their working-tree
edits from colliding, and the orchestrator merges afterward.

It is NOT legitimate when the agent's entire write surface is untracked
`.claude/notes/...`. Under isolation, `git rev-parse --show-toplevel` returns
the WORKTREE root, so a relative notes write lands inside
`.claude/worktrees/agent-<hex>/` -- invisible to the main-session fan-in that
reads the real repo root. Even when the orchestrator passes an absolute output
path (so the write lands correctly), the worktree bought zero isolation,
because there was no tracked-file contention to isolate. It is at best empty
ceremony and at worst a fan-in hazard.

Observed in-fleet, these stray worktrees accumulate at
`<repo>/.claude/worktrees/agent-<hex>/` (seen across several repos), which is
the visible symptom of the anti-pattern.

FLAG, do not fix here: `milestone-researcher` is currently marked
`isolation: worktree` while writing ONLY to untracked
`.claude/notes/.../research/*.md`. Per this rule that isolation is
illegitimate. Reconciling the researcher agent belongs to the milestone group,
not to this doctrine file -- it is flagged, not changed. See
`runtime-contract.md` for the untracked-write-surface definition this rests on.

## First-run agent registration caveat

A `subagent_type` whose `.md` was created in the CURRENT session does not
dispatch until the session restarts. For that first run only, fall back to
the built-in `general-purpose` agent and inline the target agent's prompt;
after a restart, dispatch the real `subagent_type`.

This is DISTINCT from the spawn rule above. The spawn rule says a subagent can
never dispatch at all; this caveat says a brand-new agent definition is not
dispatchable by anyone until restart. Do not conflate them.

## Agent memory

Agents declare `memory: project`. Each agent's memory lives at
`.claude/agent-memory/<agent>/` (for example `lessons.md`, `anti-patterns.md`)
and is append-only -- written with a heredoc append, never rewritten or
truncated. An agent reads its OWN memory at startup. The orchestrator never
injects an agent's memory into the dispatch prompt and never edits or trims
it. Memory grows monotonically; consolidation, when needed, is a deliberate
separate action, never a silent truncation by the dispatcher.

## CWD and path resolution for dispatched agents

The orchestrator passes an absolute `{REPO_ROOT}` and absolute output paths
into every dispatch. A dispatched agent WRITES to the passed absolute path and
does NOT re-derive a root of its own -- under isolation a re-derived root is
the worktree root, not the repo root (see the worktree section). Path and
interpreter resolution for the scripts an agent shells out to are defined once
in `runtime-contract.md`.

## Dispatch discipline

These survive from the phase docs and apply to every phase in both
generations:

- Issue ALL `Task` calls for a phase in ONE assistant turn. Sequential
  dispatch defeats the parallel fan-out.
- Route on `status` plus file presence, NEVER on `summary` text. The summary
  is for humans; the status field and the pointed-at file are the contract.
- Every leaf agent returns the fixed envelope and nothing else:
  ```json
  {"file_path": "...", "status": "...", "summary": "...", "injection_attempts": 0}
  ```
  The orchestrator validates the shape and that the pointed-at file exists;
  a malformed return triggers exactly ONE re-dispatch quoting the violation,
  and a second failure hard-stops the phase.

## External-write boundary

The single most load-bearing property of every pipeline: no agent and no
orchestrator runs `git push`, `git commit`, `git add`, `gh issue create`, a
publish, or a deploy on its own. The `--github` path emits issue-body files
under `plans/<slug>/github/<item-id>.md` for the user to review; the actual
`gh issue create` and any `git push` STOP and ask for authorization first.
This boundary is shared with, and defined in full in, `runtime-contract.md`.

## Names used by these pipelines

The always-on critique gate is `milestone-adversary-critic`. The OSS-scout is
`milestone-oss-scout`, a SEPARATE agent definition dispatched only under
`--oss-scout` (one agent, one role -- not a mode flag on the researcher).
