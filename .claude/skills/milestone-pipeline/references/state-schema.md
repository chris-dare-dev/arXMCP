# `state.json` schema and transitions

The orchestrator's persistent record for one milestone. Lives at:

```
<repo-root>/.claude/notes/milestones/<ID>/state.json
```

**One state file per milestone.** Single-writer (the orchestrator). Atomic
writes only — never edit by hand mid-run; use `checkpoint.py`.

## State machine

Nine phases, strict-forward-only:

```
init
  → research-running
    → research-complete
      → implement-running
        → implement-complete
          → critique-running
            → critique-complete
              → rectify-running
                → complete
```

`checkpoint.py` enforces:

- **No backward transitions.** `complete → init` is refused.
- **No skipped transitions.** `research-complete → critique-running` is refused.
- **One step at a time only.** Always `+1` phase.

This is forward replay by construction. Crash, compaction, or session
restart = re-invoke the skill, read `state.phase`, jump to the right phase.

## Top-level fields

Every field is rewritten by the orchestrator (or its sub-agents reporting
back). Keys are alphabetical when serialized.

| field | type | written by | meaning |
|---|---|---|---|
| `id` | string | init | milestone identifier (e.g. `E01_S01` or arbitrary) |
| `created_at` | ISO-8601 UTC | init | first init time |
| `updated_at` | ISO-8601 UTC | every write | last mutation |
| `phase` | enum (9) | `checkpoint.py` | current phase |
| `phase_history` | array | `checkpoint.py` | `{phase, entered_at, left_at}` rows; `left_at` of current phase is `null` |
| `milestone_brief` | string | init | full text of the milestone (from `--brief`, `--brief-from`, or auto-discovery) |
| `brief_source` | string | init | path to the source file the brief was extracted from (empty if `--brief` inline). Audit trail. |
| `research_mode` | enum | Phase 1 | `standard` (2× Sonnet), `deep` (1× Opus), `single` (1× Sonnet) |
| `research_briefs` | array | Phase 1 | `[{agent_id, brief_path, summary}]` from each researcher |
| `research_synthesis` | path or null | Phase 1 | path to merged-brief file (orchestrator-written) |
| `implementation_path` | enum | Phase 2 | `inline`, `delegated`, or `specialist` |
| `implementation_specialist` | string or null | Phase 2 | specialist agent name (only when `path=specialist`) |
| `implementation_base` | sha | Phase 2 start | base commit before any work |
| `implementation_commit_range` | string | Phase 2 end | `<base>..<head>` |
| `implementation_commits` | array of sha | Phase 2 end | every commit in the range |
| `implementation_branch` | string | Phase 2 | branch name where work landed |
| `external_writes_required` | array | Phase 1+2 | `[{type, target, why, blocking}]` — populated by Researcher and refined by Implementer |
| `critique_path` | path or null | Phase 3 | merged critique file |
| `critics_run` | array | Phase 3 | `[{critic, output_path, summary}]` per critic dispatched |
| `critique_finding_counts` | object | Phase 3 | `{critical, high, medium, low}` |
| `rectification_commit` | sha or null | Phase 4 | the single rect commit |
| `fixed_findings` | array of id | Phase 4 | finding IDs (`F1`, `H2`, …) addressed |
| `deferred_findings` | array of id | Phase 4 | finding IDs explicitly deferred (with reason in commit body) |
| `invalidated_findings` | array of id | Phase 4 | finding IDs the re-verify gate stripped |
| `regression_tests_added` | array of path | Phase 4 | new/updated test paths gating the fix |
| `external_writes_authorized` | bool | Phase 4 | flips `true` only on explicit user OK |
| `external_writes_completed` | bool | Phase 4 | flips `true` only after the writes happened |

## `external_writes_required` row schema

```json
{
  "type": "git_push|gh_issue|gh_pr|infra_apply|...",
  "target": "origin/main|github.com/owner/repo#issues|...",
  "why": "human explanation, one sentence",
  "blocking": true
}
```

Phase 4 reads this list and surfaces it to the user verbatim before
asking for authorization. `complete` is unreachable while
`external_writes_required` is non-empty AND
`external_writes_authorized` is `false` AND the user has not explicitly
chosen "skip external writes for this milestone."

## Reading and writing

```bash
# transition (validated)
checkpoint.py E01_S01 research-running

# read a field
checkpoint.py E01_S01 --get phase
checkpoint.py E01_S01 --get critique_finding_counts

# write a field (JSON value parsed)
checkpoint.py E01_S01 --set 'critique_finding_counts={"critical":0,"high":2,"medium":1,"low":4}'
checkpoint.py E01_S01 --set 'implementation_path="delegated"'
```

`--set` accepts a JSON value; if parsing fails, the value is stored as
a literal string (so `--set 'note=something simple'` works).

Atomic writes: temp file in same directory → `fsync` → `rename(2)` →
parent-directory `fsync`. macOS uses `F_FULLFSYNC`. Concurrent writers
are not supported and not protected against — the orchestrator is the
single writer.

## Don'ts

- **Don't edit `state.json` by hand mid-run.** A torn write or a stale
  `phase` cascades through every subsequent phase decision.
- **Don't store sub-agent brief / critique CONTENT in state.json.**
  Only paths and 3-line summaries. The conversation channel and the
  state file both stay tiny; large artifacts live in their own files
  next to `state.json`.
- **Don't use `state.json` as a coordination channel between
  sub-agents.** They each write to their declared output path. The
  orchestrator merges. Sub-agents do not read each other's state.
