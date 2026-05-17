# Phase 4 — Rectify

**State precondition:** `state.phase == "critique-complete"`.

**State postcondition:** `state.phase == "complete"`,
`state.rectification_commit` set, `fixed_findings` /
`deferred_findings` / `invalidated_findings` populated,
`regression_tests_added` populated, external writes either
authorized + completed OR explicitly skipped.

**This phase runs in the main orchestrator session, NOT in a sub-agent.**
The Implementer also never writes this — load-bearing isolation.

## Step-by-step

1. Read once at phase start:
   - This file
   - `state.critique_path` (the merged + deduped critique)
2. Update state to `rectify-running`:
   ```bash
   checkpoint.py {ID} rectify-running
   ```
3. **Re-verify every CRITICAL + HIGH finding.** For each:
   - Read the cited `file:line ± 30 lines`.
   - Compare the finding's "What" claim to what's actually in the file.
   - If it no longer matches, mark `invalidated`. Skip.
   - If it still matches, proceed to fix.
4. **Fix CRITICAL + HIGH always.** Fix MEDIUM only if cheap (≤ 30 LOC,
   small test surface). Defer LOW.
5. **Add a regression guard for every CRITICAL + HIGH fix.** Test,
   assertion, or snapshot. The finding must not reappear silently.
6. **Inner loop cap: 3 attempts per finding.** If still failing,
   record under "escalations" in the critique footer and move on.
7. **Outer loop cap: 3 project-check iterations.** Beyond that,
   surface the problem to the user.
8. **Write a single rect commit.** Subject:
   `rect({ID}): close C1, H1, ...` listing every fixed finding by ID.
   Body: per-finding bullet (`F1 — fixed in path/foo.py; regression
   test tests/test_foo.py::test_bar`), then the deferred and
   invalidated lists with reasons. Conventional commits, GPG signed,
   never `--no-verify`.
9. Update the critique file's "Rectification status" footer in place
   (use Edit on the markdown file — one bullet per finding).
10. Persist results:
    ```bash
    checkpoint.py {ID} --set 'rectification_commit="<sha>"'
    checkpoint.py {ID} --set 'fixed_findings=["F1","H1",...]'
    checkpoint.py {ID} --set 'deferred_findings=["L1",...]'
    checkpoint.py {ID} --set 'invalidated_findings=["M2",...]'
    checkpoint.py {ID} --set 'regression_tests_added=["tests/test_foo.py",...]'
    ```
11. **External-write boundary.** Read
    `state.external_writes_required`. If non-empty:
    - Surface the list to the user verbatim, with file paths and
      reasons.
    - Wait for explicit per-event authorization. Authorization once
      ≠ authorization for everything.
    - On approval: perform the writes, then
      `checkpoint.py {ID} --set 'external_writes_authorized=true'`
      and `--set 'external_writes_completed=true'`.
    - On user "skip": set `external_writes_authorized=false`,
      `external_writes_completed=false`, and record the user's
      decision in the rect commit body.
    - The pipeline cannot reach `complete` while this is unresolved.
12. Final transition: `checkpoint.py {ID} complete`.

## Re-verify gate — the load-bearing detail

Before any code change, re-read the cited file:line ± 30 lines and
confirm the finding still applies. Two reasons:

- The implementer may have already addressed the issue in a later
  commit the critic didn't see.
- The critic may have hallucinated the line number.

Record every invalidation in `state.invalidated_findings`. If
≥ 40% of a single critic's CRITICAL + HIGH findings invalidate, the
critic prompt is broken — note this in the rect commit body and the
next run should adjust the critic's axes or re-dispatch with a tighter
brief.

The 40% number is a heuristic — instrument and tune from real runs.
Document a different threshold here once you have data.

## External-write hard stop — exactly what gates

Anything that mutates state outside the local working tree.

| Type | Gated? | Notes |
|---|---|---|
| `git commit` (local) | No | Phase 4 always commits the rect locally |
| `git push origin <branch>` | YES | Per-push user authorization |
| `gh issue create` / `gh pr create` | YES | Project ROADMAP says these are manually triggered |
| `gh pr review --approve` etc. | YES | Any GitHub mutation |
| `helm install`, `kubectl apply` | YES | Infra apply |
| Slack / email / external API call | YES | Anything visible outside the workstation |
| Editing a file outside `{REPO_ROOT}` | YES | Treat as external |

The orchestrator MUST NOT batch-authorize. Each external write event
gets its own user check.

## Hard rules

- **Phase 4 runs in main session.** No "rectifier" sub-agent unless
  explicitly delegated AND it's not the same agent that did Phase 2.
- **Re-verify before fixing.** Always.
- **Single rect commit.** One per pipeline run, no fix-up commits.
- **GPG-signed, conventional, never `--no-verify`.**
- **External-write hard stop.** Authorization is per-event, not per-pipeline.
- **`complete` is unreachable** until external writes are either done
  or explicitly skipped with the user's acknowledgment recorded.

## Don'ts

- Don't auto-skip the re-verify step for "small" findings. The 40%
  metric only works if every CRITICAL + HIGH passes through the gate.
- Don't fold the rect commit into earlier implementation commits via
  `--amend` or rebase. Phase 4's commit is a separate, named artifact.
- Don't push because "the test passed locally." Push is gated.
- Don't mark `external_writes_completed=true` until the writes
  actually happened. Lying to the state machine breaks future replay.
- Don't fix LOW findings just because they're cheap. The rect commit
  stays focused; deferred-with-reason is fine and trackable.
