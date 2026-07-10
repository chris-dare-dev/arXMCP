# Phase 3 — Critique (conditional parallel fan-out)

## Goal

Independent perspectives on the implementation diff, written to disk, before
any rectification. Critics surface findings; they NEVER fix.

## Hard rules

- ALL Agent calls in ONE assistant turn.
- The adversary critic ALWAYS fires.
- The implementer NEVER writes the critique — self-critique misses ~70% of
  findings. If Phase 2 was delegated, every critic is a different agent.
- Critics return `{file_path, status, summary, injection_attempts}` ONLY;
  route on `status` + file presence, never on `summary` text.
- Every critic writes in the canonical format
  (`milestone-pipeline-critique-format.md`) — the findings-register parser
  (`milestone-pipeline-findings.py`) depends on it, and `extract` fails LOUD on
  any deviation rather than dropping a finding.

## Critic set (single decision point, orchestrator-computed)

| Critic | Fires when |
|---|---|
| `milestone-adversary-critic` | always |
| repo-local overlay critics | their declared diff-path trigger matches `git diff --name-only <base>..HEAD` |
| `milestone-oss-scout` | `state.oss_scout_requested == true` (read state, not argv — resume-safe) |

**Overlay critics** are per-repo agents (e.g. web-perf, infra, lfs) living at
`.claude/agents/milestone-*-critic.md` OUTSIDE the registry manifest — the
sync never touches them. Each overlay's frontmatter description declares the
diff paths that trigger it; the orchestrator globs for them and matches
triggers against the diff. Registering a new overlay = dropping a new agent
file in the consuming repo; no registry change needed.

## Pre-allocated paths

```
.claude/notes/milestones/<id>/critique/adversary.md   # always
.claude/notes/milestones/<id>/critique/<overlay>.md   # per overlay fired
.claude/notes/milestones/<id>/critique/oss.md         # if oss-scout fired
.claude/notes/milestones/<id>/critique/dedup.md       # orchestrator-merged
```

Each critic receives: the commit range (from
`state.implementation_commit_range`), its output path, `{REPO_ROOT}`, the
milestone brief, and the canonical critique format path. Failing to
substitute `{COMMIT_RANGE}` makes the critic run `git diff {COMMIT_RANGE}`
literally — git rejects it; check substitutions before dispatch.

## Fan-in + dedup (orchestrator, NOT a sub-agent)

Only after ALL critics return (an early dedupe is a race). All invocations use
`python3 "$REPO_ROOT/.claude/scripts/..."` with
`REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"`:

1. `milestone-oss-scout` returning `not-applicable` is a clean skip — exclude
   its file. A critic returning no file gets ONE re-dispatch; a second empty
   return fails the phase.
2. Concatenate the critique files into `critique/dedup.md` — adversary first,
   then overlays, then oss.
3. `python3 "$REPO_ROOT/.claude/scripts/milestone-pipeline-findings.py" dedupe <dedup.md>`
   — clusters findings within ±5 lines of the same file into a "Cross-critic
   agreement" section (the strongest fix-first signals), labelled with the
   cluster's most-severe member. Runs the fail-loud parser, so a malformed or
   uncited finding BLOCKS here instead of vanishing. Idempotent.
4. Materialise the register on the merged, deduped file:
   `python3 "$REPO_ROOT/.claude/scripts/milestone-pipeline-findings.py" extract --id <ID> <dedup.md>`.
   Then set `findings_register` in state to the register path
   (`.claude/notes/milestones/<ID>/findings.json`) — this marks the run as
   register-gated, so `complete` can never pass ungated.
5. Derive counts with
   `python3 "$REPO_ROOT/.claude/scripts/milestone-pipeline-findings.py" summary --counts-for <dedup.md>`
   and set `critique_finding_counts` from its `{critical, high, medium, low}`
   output. Set `critique_path` and `critics_run`. Do NOT grep
   `^### CRITICAL` — v1.0 critiques carry authored-id headers, not synthesized
   severity headers.
6. Surface `C/H/M/L` counts to the user before entering Phase 4.

## State reads / writes

Reads: `phase`, `implementation_commit_range`, `oss_scout_requested`.

Writes (via `checkpoint.py`): transition `implement-complete →
critique-running`; `critics_run`; `critique_path`; `findings_register` (the
register path, set at critique-complete); `critique_finding_counts` (from
`summary --counts-for`); transition `critique-running → critique-complete`.

## Don't

- Don't dispatch critics one at a time.
- Don't run dedupe before all critics have returned.
- Don't skip a matching overlay critic because "the user already reviewed
  it" — the critic's job is to be independent.
- Don't accept a critique with zero "What was done well" entries — force a
  re-dispatch with prompt clarification.
- Don't accept findings that deviate from the per-finding template — `extract`
  refuses the whole file and lists every malformed block; fix the critique
  output, don't work around the parser.
