# `state.json` schema and transition rules

Documents the milestone-pipeline state machine. The scripts
(`milestone-pipeline-init-state.sh`, `milestone-pipeline-checkpoint.py`) are
the enforcement; this file documents intent. Read it only when you need a
field the scripts don't already cover.

## File location

`<repo-root>/.claude/notes/milestones/<id>/state.json`

Atomic writes only: `checkpoint.py` writes temp + rename in the same
directory as the target. Direct edits are forbidden — they break the
atomicity assumption and get clobbered by the next script run. Read fields
via `checkpoint.py <id> --get <field>`; write via `--set` / `--append`.

`state.json` is ephemeral (gitignore it). The `*.md` artifacts under
`research/`, `implement/`, `critique/`, `rectify/` are committed — durable
evidence that outlasts state.

## Phases (forward-only, single-step, no skips)

```
init
  → research-running  → research-complete
  → implement-running → implement-complete
  → critique-running  → critique-complete
  → rectify-running   → complete
```

`checkpoint.py <id> <next-phase>` refuses backward transitions and skipped
phases. There is no rollback flag: when a phase must be redone (stale
critique, aborted implementation), surface to the user; re-dispatch happens
within the current phase, never by rewinding state. Scope-exceeded is a
sub-agent RETURN STATUS, not a phase — the pipeline stays in
`implement-running` and the user decides.

## Top-level fields

| Field | Type | Purpose |
|---|---|---|
| `id` | string | `<slug>-mN`, `<slug>-spike-N`, or `adhoc-YYYYMMDD-<sha7>`. |
| `created_at` / `updated_at` | UTC RFC3339 | Set by init / every write. |
| `phase` | enum | One of the 9 phases above. |
| `phase_history` | array of `{phase, at}` | Append-only; written by `checkpoint.py`. |
| `milestone_brief` | string | The resolved brief Phase 1 receives. |
| `brief_source` | string | `inline`, `roadmap <path>`, `legacy-prose <path>`, or `""` (unresolved) — from `resolve-brief.py`'s `source:` line. |
| `research_mode` | enum | `standard` / `single` / `deep`. |
| `oss_scout_requested` | bool | Persisted from `--oss-scout` (resume-safe; Phase 3 reads state, not argv). |
| `allow_large_diff` | bool | Persisted from `--allow-large-diff`. |
| `research_briefs` | array of paths | One entry per returned researcher brief. |
| `research_synthesis` | string \| null | Path to `research/synthesis.md`. |
| `implementation_path` | `inline` \| `delegated` \| null | Decided at Phase 2 entry. |
| `implementation_plan` | string \| null | Path to plan artifact (inline path only). |
| `implementation_base` | string \| null | Git SHA at Phase 2 start (diff anchor). |
| `implementation_commit_range` | string \| null | `<base>..<head>`. |
| `implementation_commits` | array of SHAs | Appended as commits land. |
| `implementation_branch` | string \| null | `null` for inline / main-only repos. |
| `external_writes_required` | array of strings | Set from Phase 1 brief-2; read by the Phase 4 boundary. E.g. `git push origin main`. |
| `critique_path` | string \| null | `critique/dedup.md` once merged. |
| `critics_run` | array of agent names | For the audit trail + rect-commit `Reviewed-by:` trailers. |
| `critique_finding_counts` | `{critical, high, medium, low}` | Grepped from dedup.md severity headers. |
| `rectification_commit` | string \| null | SHA of the `rect(<id>): ...` commit. |
| `fixed_findings` / `deferred_findings` | arrays of finding ids | E.g. `["C1", "H2"]`. |
| `invalidated_findings` | array of finding ids | Anchor-not-found / code-no-longer-matches / superseded. |
| `regression_tests_added` | array of paths | Test files touched by the rect commit. |
| `external_writes_authorized` | array of strings | Items the user explicitly approved. |
| `external_writes_completed` | array of strings | Items performed or explicitly skipped — the canonical "no longer pending" set. |

## Transitions and side effects

| From → To | Side effects required first |
|---|---|
| `init → research-running` | Preflight passed; lock held; brief resolved into state (source in `brief_source`); `in_progress` journal event recorded (roadmap-tracked ids). |
| `research-running → research-complete` | All researchers returned `complete`; `research/synthesis.md` written; `external_writes_required` set. |
| `research-complete → implement-running` | `implementation_base` + `implementation_path` recorded. |
| `implement-running → implement-complete` | Repo check gates green; commits recorded; `implement/synthesis.md` written. Scope-exceeded stays HERE and surfaces. |
| `implement-complete → critique-running` | Critic set computed (adversary + matching overlays + optional oss-scout); output paths pre-allocated. |
| `critique-running → critique-complete` | All critics returned; `critique/dedup.md` merged + deduped; counts + `critics_run` set. |
| `critique-complete → rectify-running` | Nothing else — re-verification happens inside Phase 4. |
| `rectify-running → complete` | Rect commit landed + recorded; `rectify/summary.md` written; `done` journal event appended via `record-progress.py` (NEVER a roadmap.yaml edit); `external_writes_required ⊆ external_writes_completed`; lock released. |

## Progress write-back (one-writer rule)

Execution progress lives in `plans/<slug>/progress/agent.jsonl` — append-only
JSON lines written ONLY by `milestone-pipeline-record-progress.py`. The
pipeline never edits `roadmap.yaml` item status and never ticks checkboxes in
prose roadmaps; the plan file belongs to the roadmap phase agents. The vault
compiler folds plan ⊕ journal downstream. Legacy-prose milestones have no
journal — `record-progress.py` warns and no-ops for them.

## Atomic write idiom

```python
def atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")  # SAME DIR — load-bearing
    tmp.write_text(data)
    os.replace(tmp, path)
```

`tempfile.NamedTemporaryFile()` defaults to a different filesystem on some
platforms, degrading rename to copy+unlink. Always create the temp file in
the target's parent directory.

## Locking (one milestone at a time)

`.claude/notes/milestones/.lock` contains `<pid>:<milestone-id>:<created-at>`.
`init-state.sh` takes and checks it: same-id → proceed (resume); different id
with a live pid → refuse; different id with a dead pid → instruct
`init-state.sh <held-id> --release-lock`. The orchestrator releases the lock
at `complete`. Never `rm` it directly. Multi-milestone parallelism is
intentionally unsupported (shared git state, shared gates, orchestrator
readability).
