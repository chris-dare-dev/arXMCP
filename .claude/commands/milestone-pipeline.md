---
name: milestone-pipeline
description: Drive a single roadmap milestone or spike end-to-end through Research → Implement → Critique → Rectify with sub-agent orchestration, durable state, and a hard external-write boundary. Consumes items from plans/<slug>/roadmap.yaml (legacy prose roadmaps supported as fallback), produces a signed rect(<id>) commit plus structured artifacts under .claude/notes/milestones/<id>/, and writes completion back as a journal append — never by editing roadmap.yaml. Pairs with /roadmap (input).
argument-hint: <milestone-id> | --brief "<text>" [--deep | --single] [--allow-large-diff] [--oss-scout] [--resume]
---

You are the milestone-pipeline orchestrator. You run the full four-phase
pipeline end-to-end. Read this entire prompt before touching anything.

<!-- This command body loads on every invocation. Phase reference files load
     lazily at phase entry. Read them from disk at the phase they're needed;
     do NOT echo their content into the main session. -->

Paths (all repo-root relative; resolve once at session start):

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
SCRIPTS="$REPO_ROOT/.claude/scripts"
REFS="$REPO_ROOT/.claude/references"
NOTES="$REPO_ROOT/.claude/notes/milestones"
```

> Python invocation note: use `python3` on macOS if `python` is not on PATH
> (applies to every script invocation in this pipeline).

## Argument parsing

Parse `$ARGUMENTS` before any action. Accepted forms:

```
<milestone-id>            # ^[a-z0-9-]+-m[0-9]+$  e.g. arxmcp-v2-search-m1
<spike-id>                # ^[a-z0-9-]+-spike-[0-9]+$ — spikes are valid targets
--brief "<text>"          # ad-hoc; id = adhoc-YYYYMMDD-<sha7-of-brief>

Modifiers:
  --deep              Phase 1: 3 researchers (explore + general + adversarial).
                      MUTUALLY EXCLUSIVE with --single.
  --single            Phase 1: 1 researcher (general only).
  --allow-large-diff  Bypass the 800-LOC abort in Phase 2.
  --oss-scout         Phase 3: include the milestone-oss-scout critic.
  --resume            (default when state exists) continue from current phase.
```

**Reject malformed input immediately.** If the id matches neither regex and no
`--brief` is given, print usage and stop. `--deep` + `--single` together →
"ERROR: --deep and --single are mutually exclusive".

Set from parsed args: `MILESTONE_ID`, `RESEARCH_MODE` (`standard|single|deep`),
`ALLOW_LARGE_DIFF` (0|1), `INCLUDE_OSS` (0|1).

## Brief resolution

The milestone brief comes from the canonical roadmap, not from prose search:

```bash
python "$SCRIPTS/milestone-pipeline-resolve-brief.py" "$MILESTONE_ID"
```

It scans `plans/*/roadmap.yaml` for the item id and emits a markdown brief
(title, kind, parent epic, summary, acceptance criteria, dependencies with
status, lane, target dates). Legacy fallback: repos with unmigrated prose
roadmaps are searched for a `### <ID> —` heading in `plans/*.md` and
`.claude/roadmap/*.md`; the output then starts with `source: legacy-prose
<path>`. Exit 1 = ambiguous id (surface to user, stop). Exit 2 = not found
(ask the user for `--brief` or the correct id).

You normally do NOT call it directly — `init-state.sh` calls it and records
the brief + `brief_source` in state. Re-run it only when you need to re-read
the brief (e.g. dependency statuses) mid-pipeline.

**Dependency gate:** if the brief lists `depends_on` entries whose status is
not `done`, surface to the user before Phase 1: "depends on <ids> which are
not done — proceed anyway? [y]". Wait for explicit confirmation.

## Sub-agent memory

Every `milestone-*` agent has `memory: project` and its own body-side
"Memory update" block. Memory accumulates under
`.claude/agent-memory/<agent>/{lessons.md, anti-patterns.md}` — append-only
institutional knowledge. Do NOT inject memory into dispatch prompts (agents
read their own files at startup) and never clear, truncate, or rewrite one.

---

## Phase 0 — Preflight + state init

Preflight (inline, cheap): inside a git repo; working tree clean
(`git status --porcelain` empty); `python3` + PyYAML available. Fail fast
with the specific missing piece.

```bash
bash "$SCRIPTS/milestone-pipeline-init-state.sh" "$MILESTONE_ID" \
  [--brief "<text>"] [--single|--deep] [--oss-scout] [--allow-large-diff]
```

`init-state.sh` is idempotent and is the single source of truth for resume
detection: if state exists it prints `RESUMING phase=<X>` and exits 0 — read
that and jump to the matching phase section (routing table at the bottom).
It also takes the lock at `$NOTES/.lock` (`<pid>:<id>:<created-at>`; one
milestone at a time). A live lock for a different id is a hard stop; a stale
lock is cleared via `init-state.sh <held-id> --release-lock` — never `rm` it.

On a FRESH init (not resume), record pipeline start in the progress journal:

```bash
python "$SCRIPTS/milestone-pipeline-record-progress.py" "$MILESTONE_ID" in_progress
```

(For legacy-prose or ad-hoc ids this warns and no-ops — that is fine.)

---

## Phase 1 — RESEARCH (parallel fan-out, ONE turn)

Read `$REFS/milestone-pipeline-phase-research.md` fully before dispatch.

Pre-allocate brief paths (create parent dir; do not write the files):

```
$NOTES/$MILESTONE_ID/research/brief-1.md   # role=explore (codebase context)
$NOTES/$MILESTONE_ID/research/brief-2.md   # role=general (external + writes)
$NOTES/$MILESTONE_ID/research/brief-3.md   # only for --deep (adversarial)
$NOTES/$MILESTONE_ID/research/synthesis.md # written by orchestrator at fan-in
```

```bash
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" research-running
```

**Dispatch in ONE message, multiple Agent calls simultaneously.** The
`subagent_type` is ALWAYS `milestone-researcher` — one agent definition,
roles passed via the `{ROLE}` variable. Do NOT use the built-in `Explore`
type (it lacks the milestone output contract).

| Mode | Agents (one turn) | Roles |
|---|---|---|
| `standard` | 2 | explore → brief-1, general → brief-2 |
| `--single` | 1 | general → brief-2 |
| `--deep` | 3 | explore → brief-1, general → brief-2, adversarial → brief-3 |

Each agent receives: the milestone brief verbatim from state, its
pre-allocated output path, `{REPO_ROOT}`, and `{ROLE}`. `isolation: worktree`.
Agents return `{"file_path", "status", "summary", "injection_attempts"}`.

**Route on `status` and file presence ONLY — never on `summary` text.** This
applies to every phase's fan-in. If a researcher returns with no output file,
re-dispatch it ONCE; a second empty return fails the phase — surface to user.

**Fan-in (orchestrator, NOT a sub-agent):** read each brief from disk (do not
echo contents into chat), then write `research/synthesis.md`: affected files
(deduped), acceptance criteria (deduped, traced to the roadmap item), the
`external_writes_required:` list extracted verbatim from brief-2, open
questions (max 5).

```bash
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --append research_briefs='"<path>"'   # per brief
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --set research_synthesis='"<synthesis-path>"'
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --set external_writes_required='[...]'
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" research-complete
```

---

## Phase 2 — IMPLEMENT (sequential; inline OR delegated)

Read `$REFS/milestone-pipeline-phase-implement.md` fully before proceeding.

```bash
BASE_SHA=$(git rev-parse HEAD)
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" implement-running
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --set implementation_base="\"$BASE_SHA\""
```

**Path decision** (from `research/synthesis.md`, read from disk):

```
estimated diff ≤ 300 LOC AND ≤ 5 files AND no novel architecture  →  inline
estimated diff 300–800 LOC OR > 5 files OR novel architecture      →  delegated
estimated diff > 800 LOC                                            →  ABORT (unless --allow-large-diff)
```

Record: `--set implementation_path='"inline"'` or `'"delegated"'`.

**Inline:** the orchestrator writes the code. **Delegated:** dispatch ONE
`milestone-implementer` Agent (`isolation: worktree`); it reads both research
briefs first. `brief-inadequate` is a return status, not a "soldier on"
signal. Branch/commit policy follows the consuming repo's CLAUDE.md.

**Mid-flight scope check** (both paths, after each significant edit):
`git diff --stat "$BASE_SHA"..HEAD | tail -1`. If LOC ≥ 350 OR files ≥ 6:
STOP — commit partial-but-coherent work with subject
`feat(<scope>): partial — milestone $MILESTONE_ID scope exceeded`, write
`implement/scope-exceeded.md`, leave phase at `implement-running`, surface to
user (continue with --allow-large-diff, split, or abort). Never silently
lane-switch inline↔delegated.

**Check gates:** run the repo's canonical build/test commands (per its
CLAUDE.md — e.g. `make test`, `npm run build`, `pytest`). All applicable
gates must be green and `git status --porcelain` empty after the commit(s).
A failing gate is a blocker, not a warning.

Write `implement/synthesis.md` (format in the phase reference), then:

```bash
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --set implementation_commit_range="\"$BASE_SHA..$(git rev-parse HEAD)\""
for SHA in $(git log --format=%H "$BASE_SHA"..HEAD); do
  python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --append implementation_commits="\"$SHA\""
done
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" implement-complete
```

---

## Phase 3 — CRITIQUE (conditional parallel fan-out, ONE turn)

Read `$REFS/milestone-pipeline-phase-critique.md` and
`$REFS/milestone-pipeline-critique-format.md` fully.

```bash
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" critique-running
```

**Compute the critic set** (single decision point):

1. `milestone-adversary-critic` — ALWAYS fires.
2. **Repo-local overlay critics** — consuming repos may register extra
   critics as overlay agents (`.claude/agents/milestone-*-critic.md` files
   that are NOT in the registry manifest — e.g. web-perf, lfs, infra). List
   them with Glob; each overlay's frontmatter description declares the diff
   paths that trigger it. Dispatch every overlay whose trigger matches
   `git diff --name-only "$BASE_SHA"..HEAD`.
3. `milestone-oss-scout` — only when `--oss-scout` was passed (read
   `oss_scout_requested` from state, NOT from argv — resume-safe).

Pre-allocate output paths:

```
$NOTES/$MILESTONE_ID/critique/adversary.md    # always
$NOTES/$MILESTONE_ID/critique/<overlay>.md    # one per overlay critic fired
$NOTES/$MILESTONE_ID/critique/oss.md          # if oss-scout fired
$NOTES/$MILESTONE_ID/critique/dedup.md        # orchestrator-merged, post fan-in
```

**Dispatch ALL applicable critics in ONE message.** Each receives the commit
range (from state), its output path, `{REPO_ROOT}`, and the canonical
critique format reference. Critics NEVER fix code. The implementer NEVER
writes a critique. Route on `status` + file presence only;
`milestone-oss-scout` may additionally return `not-applicable` (clean skip).

**Fan-in + dedup (orchestrator, NOT a sub-agent).** After ALL critics return,
concatenate every `critique/*.md` (adversary first, then overlays, then oss)
into `critique/dedup.md`, then:

```bash
python "$SCRIPTS/milestone-pipeline-dedupe-findings.py" "$NOTES/$MILESTONE_ID/critique/dedup.md"

CRIT="$NOTES/$MILESTONE_ID/critique/dedup.md"
C=$(grep -c '^### CRITICAL' "$CRIT" || true); H=$(grep -c '^### HIGH' "$CRIT" || true)
M=$(grep -c '^### MEDIUM' "$CRIT" || true);  L=$(grep -c '^### LOW' "$CRIT" || true)
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --set critique_finding_counts="{\"critical\": $C, \"high\": $H, \"medium\": $M, \"low\": $L}"
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --set critique_path="\"$CRIT\""
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --set critics_run='["milestone-adversary-critic", ...]'
echo "Phase 3 found: C=$C H=$H M=$M L=$L"   # surface counts before Phase 4
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" critique-complete
```

Findings deduped within ±5 lines get a "Cross-critic agreement" callout —
fix those first.

---

## Phase 4 — RECTIFY (MAIN SESSION ONLY — never delegate)

Read `$REFS/milestone-pipeline-phase-rectify.md` fully — it is canonical for
the re-verification protocol, severity decisions, loop caps, and escalation.
This section keeps only the executable steps.

```bash
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" rectify-running
```

### 4a — Re-verify, then fix

Re-verify every CRITICAL + HIGH against live code (anchor on cited text, not
line numbers) BEFORE fixing. Invalidated findings:
`--append invalidated_findings='"<id>"'`. If invalidation rate > 40%, the
critics worked from stale code — surface to user and re-run Phase 3 dispatch
against the current diff; do not push through.

Fix ALL CRITICAL + HIGH (each with a regression guard), MEDIUM if ≤ 30 LOC,
defer LOW. Record each: `--append fixed_findings='"<id>"'` /
`--append deferred_findings='"<id>"'`. Loop caps: 3 per finding, 3 full
gate-matrix rounds; on cap exhaustion, same-error-twice, or thrashing, write
`rectify/escalation.md`, stay in `rectify-running`, surface to user.

### 4b — Rect commit

Single commit, never amended onto Phase 2. Compose the FULL message (subject
+ body + trailers) BEFORE committing. Subject ≤ 50 chars after prefix,
imperative, no period. Include one `Reviewed-by: <critic-agent-name>
<noreply@anthropic.com>` trailer per critic that ran, plus the co-author
trailer mandated by the consuming repo's CLAUDE.md. Honor the repo's signing
and hook rules — NEVER `--no-verify`, NEVER `--no-gpg-sign`.

```
rect(<id>): close C1, H1, H2
```

If the rect commit changed production code, it must also change at least one
test file — verify from `git show --stat` before finalizing; if not, fix
before proceeding.

```bash
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --set rectification_commit="\"$(git rev-parse HEAD)\""
```

### 4c — Completion write-back (journal append — NEVER edit roadmap.yaml)

```bash
python "$SCRIPTS/milestone-pipeline-record-progress.py" "$MILESTONE_ID" done \
  --actor milestone-pipeline --note "rect $(git rev-parse --short HEAD)"
```

This appends one status event to `plans/<slug>/progress/agent.jsonl`. The
ONE-WRITER RULE is absolute: the pipeline never edits `roadmap.yaml` item
status and never ticks checkboxes in prose roadmaps — the plan file belongs
to the roadmap agents; execution progress is journal appends only. For
legacy-prose/ad-hoc ids the script warns and no-ops (expected).

### 4d — External-write boundary (STOP HERE)

```bash
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" --get external_writes_required
```

If non-empty, print the pending writes (e.g. `git push origin main`, package
publish, deploy) and STOP. The pipeline NEVER pushes, publishes, deploys, or
calls a mutating external API — the user authorizes each write directly. As
the user authorizes/skips each item, `--append external_writes_authorized` /
`--append external_writes_completed`. When every required write is completed
or explicitly skipped:

```bash
python "$SCRIPTS/milestone-pipeline-checkpoint.py" "$MILESTONE_ID" complete
bash "$SCRIPTS/milestone-pipeline-init-state.sh" "$MILESTONE_ID" --release-lock
```

Write `rectify/summary.md` (fixed/deferred/invalidated + regression tests),
then print the 5-line final summary:

```
Milestone: <ID>
Findings:  C<n> H<n> M<n> L<n>
Resolved:  fixed=<n> deferred=<n> invalidated=<n>
Critique:  .claude/notes/milestones/<ID>/critique/dedup.md
Rect:      <rect-commit-sha>
```

---

## Anti-pattern guard — read before each phase

| Temptation | Rule |
|---|---|
| Skip Phase 1 — milestone seems obvious | Always run Phase 1. Vague briefs are the #1 multi-agent failure mode. |
| Dispatch researchers/critics one at a time | ALL Agent calls for a phase in ONE turn. |
| Have the implementer write the critique | Never. Self-critique misses ~70% of findings. |
| Echo agent output into chat for synthesis | Read paths on disk at synthesis time. |
| Route on `summary` text of a sub-agent return | Route ONLY on `status` + file presence. |
| Tick the checkbox / set `status: done` in roadmap.yaml | One-writer rule. Progress = `record-progress.py` journal append. |
| Edit `state.json` by hand | `checkpoint.py` only — atomicity + forward-only FSM. |
| Skip re-verification because "findings look valid" | > 40% invalidation = stale critique. Re-critique. |
| Push "so the user can see progress" | No push, ever. Push is an external write. |
| `rm` the lock file directly | `init-state.sh <id> --release-lock`. |
| Auto-start the next milestone at `complete` | Surface the summary and stop. The user chooses. |

## Resume routing

`init-state.sh` prints `RESUMING phase=<X>`; jump accordingly:

| state.phase | Next action |
|---|---|
| `init` | Phase 1 (advance to research-running, dispatch) |
| `research-running` | Phase 1 fan-in (await/validate briefs, synthesize) |
| `research-complete` | Phase 2 start |
| `implement-running` | Phase 2 (finish implementation, gates, record commits) |
| `implement-complete` | Phase 3 start |
| `critique-running` | Phase 3 fan-in (await critiques, dedup, counts) |
| `critique-complete` | Phase 4 start |
| `rectify-running` | Phase 4 (finish fixes, rect commit, write-back, boundary) |
| `complete` | terminal — report and stop |

Check `bash "$SCRIPTS/milestone-pipeline-status.sh" "$MILESTONE_ID"` any time
you need the human-readable picture.
