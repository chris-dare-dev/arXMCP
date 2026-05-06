---
name: milestone-pipeline
description: Execute ONE milestone end-to-end through Research → Implement → Critique → Rectify, dispatching parallel sub-agents per phase and persisting state across compactions. Use when a roadmap milestone (e.g. `E01_S01`) needs to land cleanly with verification, adversarial review, and a hard stop at the external-write boundary. Use after a planning skill has produced milestone IDs, or with an inline `--brief` for ad-hoc work. Do not use for trivial one-line edits or for milestones that have not yet been scoped.
---

# milestone-pipeline

Run ONE milestone end-to-end through four phases: **Research →
Implement → Critique → Rectify**. The skill is the orchestrator. Each
phase dispatches sub-agents in parallel where it pays, and the main
session merges their artifacts directly. State is persisted in a
strict-forward-only state machine so the pipeline survives
compaction, session restart, and `/loop` resumes.

## When to use

- A roadmap milestone needs to land. Invoke with the milestone ID
  (`milestone-pipeline E01_S01`) — Phase 1 grep-extracts the brief
  from `.claude/roadmap/`.
- An ad-hoc piece of work needs the same rigor. Invoke with
  `--brief "..."` instead of an ID.
- Mid-pipeline: re-invoke on the same ID and the skill resumes from
  `state.phase` rather than starting over.

## When not to use

- Trivial edits (one-liners, formatting fixes). Just do them.
- Milestones that haven't been scoped — Phase 1 will produce a thin
  brief and the rest of the pipeline will inherit the thinness.
- Math-content review (sketcher → autoformalizer outputs). The
  project's own [01-mission-and-context.md](.claude/notes/01-mission-and-context.md) notes that an adversarial
  Claude critic is the *least* valuable role for math content. This
  skill critiques **code**, where adversarial review earns its keep.

## Inputs

```
milestone-pipeline <ID> [--brief "text"] [--deep|--single] [--repo-root /path]
```

- `<ID>` — milestone identifier in `EXX_SYY` format (e.g. `E01_S01`)
  or any string for ad-hoc runs.
- `--brief` — inline brief text, overrides roadmap lookup.
- `--deep` — Research mode: 1× Opus instead of 2× Sonnet.
- `--single` — Research mode: 1× Sonnet (small milestones).
- `--repo-root` — override repo-root detection (env var `REPO_ROOT`
  also honored; falls back to `git rev-parse --show-toplevel` and
  then walking up from the script directory).

## The four phases at a glance

| phase | who | parallel? | output |
|---|---|---|---|
| 1 — Research | 2× Sonnet (default), 1× Opus (deep), 1× Sonnet (single) — all `general-purpose` in worktrees | yes (one assistant turn) | `research-brief-N.md` per agent + `research-synthesis.md` (orchestrator-merged) |
| 2 — Implement | inline (orchestrator) OR 1–2× Sonnet `general-purpose` in worktrees OR 1× project specialist | conditional | local commits + `implementation-summary.md` |
| 3 — Critique | adversary (always, Opus) + infra-safety (conditional, Sonnet) + oss-scout (opt-in, Sonnet) | yes (one assistant turn) | `critique-merged.md` (deduped) |
| 4 — Rectify | main session (NOT a sub-agent) | n/a | `rect({ID}): ...` commit |

**Frontend-UX critic is dropped** for arXMCP — no frontend, by design
(see [ROADMAP.md](ROADMAP.md)). Adding it later is purely additive.

## Skill layout

```
.claude/skills/milestone-pipeline/
├── SKILL.md                       # this file — orchestrator only
├── references/
│   ├── agent-prompts.md           # SINGLE SOURCE OF TRUTH for sub-agent prompts
│   ├── state-schema.md            # state.json schema + transitions
│   ├── phase-research.md          # Phase 1 detail
│   ├── phase-implement.md         # Phase 2 detail
│   ├── phase-critique.md          # Phase 3 detail
│   ├── phase-rectify.md           # Phase 4 detail
│   └── critique-format.md         # canonical critique format
└── scripts/
    ├── init-state.sh              # idempotent state init; resume on re-run
    ├── checkpoint.py              # state machine validator + --get/--set
    ├── status.sh                  # human-readable state dump
    └── dedupe-findings.py         # cross-critic agreement detector
```

## Orchestration model — what the orchestrator does

YOU (the main session running this skill) are the orchestrator. Per
[addyosmani/agent-skills `references/orchestration-patterns.md`](https://github.com/addyosmani/agent-skills/blob/main/references/orchestration-patterns.md):
"the user (or a slash command) is the orchestrator. Personas do not
invoke other personas." This is **platform-blocked**, not just
convention — sub-agents cannot spawn sub-agents on Claude Code.

**Depth stays at 1.** The skill dispatches Phase-1 sub-agents, then
Phase-2, then Phase-3, then runs Phase 4 directly. No "lifecycle
orchestrator" sub-agent that summarizes between phases — that is the
named anti-pattern (lose nuance, skip checkpoints, double cost).

**Sub-agents return only `{path, status, summary_3_lines}`.** Full
artifacts live on disk. The orchestrator reads them when merging,
never via the message channel. This keeps the orchestrator's context
window flat across phases.

**Parallel fan-out happens in ONE assistant turn.** Two Agent calls
in two consecutive turns serialize. Phase 1 (researchers), Phase 2
(if 2× implementers), and Phase 3 (critics) each issue all their
Agent calls in a single response.

## State

`state.json` lives at
`<repo-root>/.claude/notes/milestones/<ID>/state.json`. Nine phases:
`init → research-running → research-complete → implement-running →
implement-complete → critique-running → critique-complete →
rectify-running → complete`.

Strict-forward-only: `checkpoint.py` refuses backward and skipped
transitions. Atomic writes (temp + rename + fsync + dirfsync; macOS
uses `F_FULLFSYNC`).

Resume: re-running `init-state.sh` on an existing milestone prints
the current phase and exits 0. Re-invoking the skill reads
`state.phase` and jumps to the right phase rather than starting over.

Full schema: see [state-schema.md](references/state-schema.md).

## Anti-pattern guard table

Load-bearing self-discipline. When you catch yourself doing the
left column, stop and read the right column.

| tempting belief | reality |
|---|---|
| "Skip Phase 1, the milestone is small." | Phase 1 also captures the `external_writes_required` list — Phase 4 reads it. Skipping = surprise external writes at the end. |
| "Dispatch the second researcher in the next turn so I can see the first one's summary." | Sequential dispatch defeats parallelism. Both researchers must launch in one assistant turn. |
| "The implementer can also write the critique — they understand the code best." | Self-critique misses ~70% of real findings. Phase 3 critics must be fresh sub-agents. |
| "≥ 40% of CRITICAL findings invalidated on re-verify is fine — I'll just fix the rest." | That's a broken critic prompt. Record the rate and re-tune the axes — don't accept noise. |
| "Bundle the rect commit into the last implementer commit with `--amend`." | Phase 4's commit is a separate, named artifact. Amending hides the rectification record. |
| "I can push now since the user already authorized the milestone." | Authorization is per-event. `git push` is a separate user check. |
| "I'll inflate this finding to CRITICAL to make sure it gets fixed." | Inflate severity once and the calibration table stops working. Use HIGH or fix it inline. |
| "Run a 'summarizer' sub-agent after the critics so the orchestrator gets a clean report." | Meta-orchestrator anti-pattern. Doubles cost, loses nuance. Merge in main session. |
| "Sub-agents can echo their full report back so I have it in context." | They write to a file and return `{path, summary_3_lines}`. The channel stays small; the orchestrator reads on demand. |
| "If a hook fails I can just `--no-verify` and move on." | Hook failure is a real failure. Investigate. Never `--no-verify`. |

## Per-phase quick reference

Each phase has a dedicated reference file. Read ONE per phase entry,
then discard from working memory after writing the phase's output.

- Phase 1 — [phase-research.md](references/phase-research.md)
- Phase 2 — [phase-implement.md](references/phase-implement.md)
- Phase 3 — [phase-critique.md](references/phase-critique.md)
- Phase 4 — [phase-rectify.md](references/phase-rectify.md)

Cross-cutting: [agent-prompts.md](references/agent-prompts.md) is the
single source of truth for every sub-agent prompt — never duplicate
prompt strings inline. [critique-format.md](references/critique-format.md)
is the canonical critique format that `dedupe-findings.py` parses.

## Quick start

```bash
# Initialize (looks up brief in .claude/roadmap/ if present)
.claude/skills/milestone-pipeline/scripts/init-state.sh E01_S01

# Read state
.claude/skills/milestone-pipeline/scripts/checkpoint.py E01_S01 --get phase
.claude/skills/milestone-pipeline/scripts/status.sh E01_S01

# Then invoke the skill (slash command will exist once registered):
#   milestone-pipeline E01_S01
```

## Project conventions this skill respects

- **Conventional commits**, scope reflects subsystem (`server`,
  `ingest`, `shim`, `infra`, `tests`, `skill`).
- **GPG signing** is enabled (`commit.gpgsign=true`). Never
  `--no-gpg-sign`.
- **Co-author trailer**:
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Pre-commit hooks** are honored. Never `--no-verify`.
- **Project check command** is detected per phase entry: prefer
  `make test` once E01_S01 lands a Makefile; fallback
  `ruff check . && pytest -q`.
- **Design constitution**: `.claude/notes/` (11 files) is the source
  of truth for adversary-critic axes. Cite the note filename in any
  finding that derives from it.

## The Anti-pattern C trade-off (read once)

A four-phase chain run by an LLM orchestrator is structurally
[Anti-pattern C in addyosmani's catalog](https://github.com/addyosmani/agent-skills/blob/main/references/orchestration-patterns.md)
("Sequential orchestrator that paraphrases"). Mitigations baked in:

1. **Depth stays at 1** — the slash command directly dispatches each
   phase's sub-agents, no nested orchestrator persona.
2. **No paraphrasing summarizer** between phases — sub-agents return
   `{path, summary_3_lines}` and the orchestrator reads artifacts
   raw at merge time.
3. **User checkpoint at the external-write boundary** in Phase 4.
4. **State persists across the chain** so any phase can be resumed
   without re-paraphrasing from scratch.

This trade-off is documented so future readers understand why a
single-skill pipeline is acceptable here despite the published
guidance against sequential orchestrators.
