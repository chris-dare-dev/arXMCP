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

`state.json` is ephemeral (gitignore it). So is the findings register
`.claude/notes/milestones/<id>/findings.json` — derived, disposable state
rebuilt from the critiques by `milestone-pipeline-findings.py extract`. The
`*.md` artifacts under `research/`, `implement/`, `critique/`, `rectify/` are
committed — durable evidence that outlasts state.

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
| `critique_files` | array of paths | One path per critic that fired (e.g. `critique/adversary.md`). Required at `critique-complete`. |
| `critique_finding_counts` | `{critical, high, medium, low}` \| null | DERIVED — not hand-maintained (see below). Seeded `null` ("never recorded"). |
| `findings_register` | string \| null | Repo-relative path to the findings register written by Phase 3's `extract` (canonical: `.claude/notes/milestones/<id>/findings.json`). The "new-format run" marker; `null` = legacy/ad-hoc run that never had a register. |
| `rectification_commit` | string \| null | SHA of the `rect(<id>): ...` commit. |
| `fixed_findings` / `deferred_findings` | arrays of finding ids | DERIVED from the register (see below). E.g. `["C1", "H2"]`. |
| `invalidated_findings` | array of finding ids | DERIVED — anchor-not-found / code-no-longer-matches / superseded. |
| `regression_tests_added` | array of paths | Test files touched by the rect commit. |
| `external_writes_authorized` | array of strings | Items the user explicitly approved (array, not a bool). |
| `external_writes_completed` | array of strings | Items performed or explicitly skipped — the canonical "no longer pending" set. |

## Transitions and side effects

| From → To | Side effects required first |
|---|---|
| `init → research-running` | Preflight passed; lock held; brief resolved into state (source in `brief_source`); `in_progress` journal event recorded (roadmap-tracked ids). |
| `research-running → research-complete` | All researchers returned `complete`; `research/synthesis.md` written; `external_writes_required` set. **Gate:** `research_briefs` (non-empty) + `research_mode` (enum) recorded first. |
| `research-complete → implement-running` | `implementation_base` + `implementation_path` recorded. |
| `implement-running → implement-complete` | Repo check gates green; commits recorded; `implement/synthesis.md` written. Scope-exceeded stays HERE and surfaces. **Gate:** `implementation_base` + `implementation_commit_range` recorded first. |
| `implement-complete → critique-running` | Critic set computed (adversary + matching overlays + optional oss-scout); output paths pre-allocated. |
| `critique-running → critique-complete` | All critics returned; `critique/dedup.md` merged + deduped. **Gate:** `critique_path`, `critics_run`, `critique_files`, `critique_finding_counts`, `findings_register` all recorded first. |
| `critique-complete → rectify-running` | Nothing else — re-verification happens inside Phase 4. |
| `rectify-running → complete` | Rect commit landed + recorded; `rectify/summary.md` written; `done` journal event appended via `record-progress.py` (NEVER a roadmap.yaml edit); lock released. **Gate:** `rectification_commit` set; the external-write ledger balances (see below); the findings gate passes (no open CRITICAL/HIGH). |

## Evidence gates (why a transition refuses)

`checkpoint.py` enforces phase ORDER *and* evidence. A gated transition refuses
until its required fields are `--set` first, correctly typed, and (for enums)
in-vocabulary — the drift-guard for the class of runs that reached `complete`
with research / implementation / critique evidence never recorded. A placeholder
string smuggled into a list/dict field via `--set`'s plain-string fallback does
NOT pass the type check. See the **Gate** column above for the per-transition
requirements.

`critique_finding_counts` seeds `null`, not `{critical:0,…}`. `null` means
"never recorded"; an all-zero dict is a *non-empty* value that would defeat the
empty-refusal, letting a run with unrecorded counts slip through. A genuine
zero-findings run sets the real all-zero dict.

## Derived fields (do not hand-maintain)

`critique_finding_counts`, `fixed_findings`, `deferred_findings`, and
`invalidated_findings` are DERIVED from the findings register, not authored by
hand. Read them from `milestone-pipeline-findings.py` (`summary --counts-for`
for the counts, `summary --field <status>` for the id lists) rather than
`--set`ting them independently — hand edits drift from the register the gate
actually reads.

## External-write ledger (array model) and the complete gate

`external_writes_required`, `external_writes_completed`, and
`external_writes_authorized` are ALL arrays of the same string tokens (e.g.
`git push origin main`) — authorization is recorded per item, not as a single
bool. At `complete`, the ledger must balance:

- every `external_writes_required` entry appears in `external_writes_completed`
  (performed or explicitly skipped), AND
- every `external_writes_required` entry appears in `external_writes_authorized`
  (the user approved it — authorization must be recorded, not merely performed).

An empty `external_writes_required` means there is nothing to authorize and the
ledger balances trivially. A plain string (not an array) in any of the three
refuses: it would iterate per-character and false-pass the balance check.

## Findings gate at `complete` (one authority)

The `complete` transition subprocess-invokes
`milestone-pipeline-findings.py gate <id>` — the gate logic lives in ONE
authority and is never re-implemented in `checkpoint.py`. The findings script
locates the register itself (`.claude/notes/milestones/<id>/findings.json`) and
exits 3 on any open CRITICAL/HIGH (refuse); MEDIUM/LOW are deferrable (a
non-blocking note). Because that gate no-ops on a missing register,
`checkpoint.py` enforces the "new-format run" rule itself: if `findings_register`
is set but the register file is absent, `complete` refuses (extract was skipped
or the register was lost). A `null` marker is a legacy/ad-hoc run — the gate
runs only if the register happens to exist (defense in depth), else it is
skipped. See `milestone-pipeline-findings-schema.md` for the register format.

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
