# Phase 3 — Critique

**State precondition:** `state.phase == "implement-complete"`.

**State postcondition:** `state.phase == "critique-complete"`,
`state.critique_path` set, `state.critics_run` populated,
`state.critique_finding_counts` set.

## Step-by-step

1. Read once at phase start:
   - This file
   - `references/critique-format.md`
   - `references/agent-prompts.md` (extract critic prompts)
2. Compute the diff scope:
   ```bash
   git diff --name-only {state.implementation_commit_range}
   ```
3. Pick which critics fire:
   - **Adversary** — always fires.
   - **Infra-safety** — fires if any path matches the regex below.
   - **OSS-scout** — fires only on user request, or if the synthesis
     flagged the milestone as "active research area."
   - **Frontend-UX** — never fires on arXMCP (no frontend).
4. Update state to `critique-running`:
   ```bash
   checkpoint.py {ID} critique-running
   ```
5. Compute output paths:
   ```
   <repo-root>/.claude/notes/milestones/{ID}/critique-adversary.md
   <repo-root>/.claude/notes/milestones/{ID}/critique-infra-safety.md   # conditional
   <repo-root>/.claude/notes/milestones/{ID}/critique-oss-scout.md      # conditional
   ```
6. **Dispatch ALL critics in ONE assistant turn.** Sequential
   dispatch defeats parallelism.
7. Each critic returns `{path, status, summary}`. Read from disk.
8. Merge into a single critique:
   ```
   <repo-root>/.claude/notes/milestones/{ID}/critique-merged.md
   ```
   Merge rules: concatenate all critics' "Findings" sections (with
   their original IDs preserved — `F<n>` adversary, `IS<n>`
   infra-safety, `OS<n>` oss-scout). Combine "What was done well"
   bullets verbatim. Write a unified executive summary in the
   orchestrator's voice.
9. Run dedupe:
   ```bash
   scripts/dedupe-findings.py <repo-root>/.claude/notes/milestones/{ID}/critique-merged.md
   ```
   This emits a `## Cross-critic agreement` section. Findings flagged
   by ≥ 2 critics within 5 lines of the same file deserve top
   rectification priority.
10. Persist state and advance:
    ```bash
    checkpoint.py {ID} --set 'critique_path="<abs path to critique-merged.md>"'
    checkpoint.py {ID} --set 'critics_run=[{...},{...}]'
    checkpoint.py {ID} --set 'critique_finding_counts={"critical":N,"high":N,"medium":N,"low":N}'
    checkpoint.py {ID} critique-complete
    ```

## Infra-path detection regex

```
^(infra/|\.github/workflows/|Dockerfile|docker-compose(\.[^/]+)?\.ya?ml|Makefile)
```

If `git diff --name-only` returns at least one path matching this
regex, dispatch infra-safety. Otherwise skip.

## Adversary critic axes (project-specific)

Eight axes, all from `.claude/notes/`. The full list is in the
adversary-critic prompt at `references/agent-prompts.md`. Summary:

| # | axis | source note |
|---|---|---|
| 1 | cache byte-stability | `07-multi-agent-caching.md` |
| 2 | math fidelity | `01-mission-and-context.md`, `04-parsing-and-chunking.md` |
| 3 | security threat-model | `08-security-observability-ops.md` |
| 4 | MCP 2025-06-18 spec compliance | `06-mcp-server-design.md` |
| 5 | local-first + Docker constraint | `01-mission-and-context.md`, ROADMAP |
| 6 | tier sequencing | `.claude/roadmap/` |
| 7 | no-fork policy | `.claude/notes/README.md` |
| 8 | test surface | brief acceptance criteria |

## Hard rules

- **Single assistant turn for parallel dispatch.**
- **Critics do not see the implementer's summary as "ground truth."**
  They read the diff and the brief. The implementer's narrative is
  optional context, not the contract.
- **The Implementer NEVER writes the critique.** Self-critique misses
  ~70% of real findings. If Phase 2 used a `delegated` implementer,
  the adversary critic must NOT be the same `general-purpose` agent
  identity — Claude Code spawns a fresh sub-agent per Agent call, so
  this is satisfied by construction. But: do not paste the
  implementer's notes into the critic prompt.
- **Critic verdicts are advisory.** The orchestrator chooses the
  rectification order. Don't auto-apply a critic's "Recommended
  rectification order" without re-evaluating it.

## Cross-critic agreement

Findings flagged by ≥ 2 critics within 5 lines of the same file are
high-signal: that region of code drew attention from independent
prompts. Phase 4's rectification order should put cross-critic
agreement findings first, regardless of severity ordering.

## The 40% invalidation watch

`state.invalidated_findings` (filled in Phase 4) is the meta-metric
for critic prompt health. ≥ 40% of a single critic's CRITICAL + HIGH
findings invalidated by the re-verify gate signals a broken prompt.
Phase 4 records the rate; Phase 3's job is to ensure the format is
parseable so Phase 4 can compute it.

## Don'ts

- Don't run a "summarizer" sub-agent between critics and the merge.
  That's the meta-orchestrator anti-pattern. Merge in main session.
- Don't echo critique content through the message channel. Read the
  files when needed.
- Don't drop the "What was done well" sections at merge time. They
  signal the critic is calibrated. Empty = re-dispatch.
- Don't auto-fire OSS-scout. It runs only on explicit request.
