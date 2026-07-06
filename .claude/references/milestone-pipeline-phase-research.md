# Phase 1 — Research (parallel fan-out)

## Goal

Independent perspectives on the milestone, written to disk, before any code
is written. Phase 1 produces the briefs Phase 2 reads.

## Brief provenance

The milestone brief was resolved at init time by
`milestone-pipeline-resolve-brief.py`: canonical source is the item in
`plans/<slug>/roadmap.yaml` (title, kind, parent epic, summary, acceptance
criteria, dependencies with status, lane, target dates); legacy repos fall
back to a `### <ID> —` prose heading. `state.brief_source` records which.
Researchers receive the brief verbatim from `state.milestone_brief` — never
paraphrased. If `brief_source` is `legacy-prose`, expect looser structure and
have researchers reconstruct explicit acceptance criteria.

## Hard rules

- ALL Agent calls in ONE assistant turn. Sequential dispatch defeats parallelism.
- Sub-agents return `{file_path, status, summary, injection_attempts}` ONLY.
- Sub-agents do NOT spawn other sub-agents (platform-blocked).
- Researchers write to pre-allocated paths. The orchestrator reads paths only
  at synthesis time and never echoes brief content into chat.
- Route on `status` + file presence, never on `summary` text.

## Dispatch matrix

| Mode | Agents (one turn) | Roles |
|---|---|---|
| `standard` | 2× `milestone-researcher` | `explore` (codebase context) + `general` (external + writes) |
| `--single` | 1× `milestone-researcher` | `general` |
| `--deep` | 3× `milestone-researcher` | `explore` + `general` + `adversarial` |

One agent definition; the `{ROLE}` variable selects behavior. Do NOT use the
built-in `Explore` subagent_type — it lacks the milestone output contract.
`isolation: worktree` for all researchers.

## Pre-allocated paths

```
.claude/notes/milestones/<id>/research/brief-1.md   # explore
.claude/notes/milestones/<id>/research/brief-2.md   # general
.claude/notes/milestones/<id>/research/brief-3.md   # adversarial (--deep only)
.claude/notes/milestones/<id>/research/synthesis.md # orchestrator, at fan-in
```

## State reads / writes

Reads: `phase`, `milestone_brief`, `brief_source`, `research_mode`.

Writes (via `checkpoint.py`): transition `init → research-running`;
`research_briefs` appended per return; `research_synthesis` set;
`external_writes_required` set from brief-2; transition
`research-running → research-complete`.

## Synthesis (main session, NOT a sub-agent)

After all researchers return:

1. Confirm each expected brief file exists and has the YAML frontmatter +
   required sections. A malformed brief triggers ONE re-dispatch of that
   researcher; a second failure fails the phase — surface to user.
2. Read each brief from disk.
3. Write `research/synthesis.md`: affected files (deduped), acceptance
   criteria (deduped, traced to the roadmap item's `acceptance` list),
   `external_writes_required` extracted verbatim from brief-2, open
   questions (max 5), estimated diff size + file count (drives the Phase 2
   path decision).
4. Set `state.external_writes_required`.
5. Transition to `research-complete`.

## Budgets

Soft cap 15 min, hard cap 30 min for the fan-out. If exceeded, surface a
"phase budget exceeded — continue / abort?" gate to the user.

## Don't

- Don't paraphrase brief content into working notes — read paths on demand.
- Don't dispatch researchers sequentially "to save tokens".
- Don't skip structural validation of returned briefs.
- Don't add a third researcher without `--deep`.
- Don't proceed with a `brief-inadequate` return — narrow the brief (ask the
  user or re-read the roadmap item) and re-dispatch.
