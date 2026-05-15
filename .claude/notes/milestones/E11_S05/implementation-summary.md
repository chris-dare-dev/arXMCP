# E11_S05 — Implementation Summary

**One-line summary.** Ship the 200K cutover activation
(`ops/cutover.py` + `cutover.sh` thin wrapper) — an atomic
directory-swap that promotes staging → active gated on 4
criteria — plus the restic backup wrapper, systemd timer pair,
restore drill, and two operator runbooks. Closes H9 ("scale
cutover trigger explicit and measurable").

**Commit range.** `584443a..HEAD`.

---

## Scope reminder

The synthesis re-shaped two brief assumptions:

1. **Activation is a directory swap, NOT a marker rewrite.**
   The brief says "advance `corpus-version.json`"; the truth is
   that the staging marker carries a version integer scoped to
   the staging dataset's filesystem path. Rewriting the active
   marker would point the server at a non-existent LanceDB
   version. Cutover does two `os.rename`s on the same FS:
   `lancedb/` → `lancedb-prev/`, then `lancedb-staging/` →
   `lancedb/`. The staging marker is correct as-is.
2. **Ship Python + bash wrapper.** Brief specifies `.sh`
   deliverable; the heavy logic (JSON parsing, atomic renames,
   HTTP polling, subprocess to watchdog) lives in
   `ops/cutover.py` where it's testable. `ops/cutover.sh` is a
   5-line wrapper that satisfies the deliverable.

---

## Acceptance criteria — status

- [x] **AC1** — `ops/cutover.py` checks all 4 activation criteria
      before advancing. **Verified** by `TestCriterion3...` /
      `TestCriterion4...` / `TestCriterion1...` / `TestCriterion2...`
      (positive + negative paths for each), plus
      `TestRunCutover::test_refuses_when_any_criterion_fails`
      asserting non-zero exit on a missing aggregate file.
- [x] **AC2** — restore drill restores to
      `/tmp/arxmcp-restore-drill/` and passes the smoke test.
      **Verified** via the SCRIPT
      ([ops/restore_drill.sh](ops/restore_drill.sh)) + the
      Python check
      ([ops/restore_drill_check.py](ops/restore_drill_check.py))
      + the unit tests
      ([tests/test_restore_drill.py](tests/test_restore_drill.py))
      that exercise success/failure paths against a synthetic
      LanceDB. End-to-end restic invocation is operator-gated
      (no `requires_restic` marker shipped yet — see follow-up).
- [x] **AC3** — `docs/ops/cutover-runbook.md` enumerates all
      4 criteria + states the rollback time. **Verified** by
      `TestCutoverRunbookContent::test_states_all_four_criteria`
      + `test_states_rollback_time`.
- [x] **AC4** — `/readyz` polling returns 200 within 60s.
      **Verified** by `TestPollReadyz::test_returns_true_on_200`
      and `test_returns_false_on_timeout`. Real-cutover behavior
      is operator-gated.
- [x] **AC5** — post-cutover watchdog reports nDCG@5 ≥ 0.80
      on 200K corpus. **Synthetic test** via
      `TestRunCutover::test_full_swap_when_all_pass` with
      mocked watchdog subprocess. Real-cutover behavior is
      operator-gated.

---

## Files added / changed

### New

- [ops/cutover.py](ops/cutover.py) — activation orchestrator.
  `CriterionResult` + `CutoverError`; 4 criterion checkers +
  `verify_lancedb_integrity`; `perform_directory_swap` +
  `perform_rollback`; `poll_readyz`;
  `run_post_activation_watchdog`; `run_cutover` orchestrator;
  `_cli` with `--dry-run` and `--rollback`.
- [ops/cutover.sh](ops/cutover.sh) — thin bash wrapper
  (resolves `uv` from PATH, no hardcoded `/Users/` paths,
  `exec`'s into `python -m ops.cutover`).
- [ops/restic-env.sh.template](ops/restic-env.sh.template) —
  restic configuration template. Documents `RESTIC_REPOSITORY`,
  `RESTIC_PASSWORD_FILE`, `B2_ACCOUNT_ID`, `B2_ACCOUNT_KEY`;
  refuses sourcing when `RESTIC_REPOSITORY` is empty; opt-in
  connectivity check via `ARXMCP_RESTIC_CHECK=1`.
- [ops/cron/arxmcp-backup.sh](ops/cron/arxmcp-backup.sh) —
  nightly backup wrapper. `flock` reentrancy, `command -v
  uv/flock/restic` guards, atomic `backup-status.json` write,
  `restic forget --prune --keep-daily 7 --keep-weekly 4
  --keep-monthly 12`.
- [ops/systemd/arxmcp-backup.service](ops/systemd/arxmcp-backup.service)
  — oneshot service unit. `TimeoutStartSec=14400` (4h for
  worst-case B2 backups), hardening directives match
  E11_S02's `arxmcp-delta.service`.
- [ops/systemd/arxmcp-backup.timer](ops/systemd/arxmcp-backup.timer)
  — `OnCalendar=*-*-* 03:30:00`, 90min after delta loop.
- [ops/restore_drill.sh](ops/restore_drill.sh) — operator-
  invoked drill script. Picks the most-recent restic snapshot,
  restores to `/tmp/arxmcp-restore-drill/`, runs the smoke
  check, writes the pass flag, cleans up.
- [ops/restore_drill_check.py](ops/restore_drill_check.py) —
  smoke-check Python module. `smoke_check_lancedb` opens the
  restored chunks table + asserts row count > 0;
  `smoke_check_kuzu` opens the citation graph (optional).
  Writes `restore-drill-passed.flag` atomically.
- [docs/ops/cutover-runbook.md](docs/ops/cutover-runbook.md)
  — operator runbook. 4 activation criteria, dry-run +
  procedure, rollback (< 30s), failure modes, state-file
  schema.
- [docs/ops/backup-restore.md](docs/ops/backup-restore.md)
  — restic configuration, retention policy, restore drill,
  catastrophic recovery, tradeoffs (NAS vs B2).
- [tests/test_cutover.py](tests/test_cutover.py) — 36 tests
  for activation criteria, directory swap, rollback,
  /readyz polling, end-to-end run_cutover, Makefile target,
  README links, runbook content.
- [tests/test_backup_wrapper.py](tests/test_backup_wrapper.py)
  — 21 tests for the restic env template, systemd units,
  shell wrapper hygiene, `.gitignore` discipline.
- [tests/test_restore_drill.py](tests/test_restore_drill.py)
  — 18 tests for the restore drill check + script hygiene +
  runbook content.

### Changed

- [Makefile](Makefile) — added `make cutover` target with
  Python version guard + ARGS word-split note.
- [README.md](README.md) — Operations table gains 2 new rows
  (cutover-runbook.md, backup-restore.md).
- [.gitignore](.gitignore) — `ops/restic-env.sh` (the filled
  credential file).

### Not touched

- `server/tools.py`, `ingest/*`, `server/*`,
  `ops/watchdog_eval.py`, hash-anchored tests. No tool
  surface change. `TOOL_SCHEMA_VERSION` stays at 6.

---

## Test results

```
1708 passed, 8 skipped, 1 xfailed in 81.30s
```

- 8 skipped: 4 `requires_model` + 3 `requires_full_corpus` +
  1 AC1 fixture-gated (E11_S04 carryover).
- 1 xfailed: AC3 from E11_S04 (cross-process /metrics
  deferred to E14).
- Net delta: **+75 tests** (1633 → 1708).
- `ruff check .` is clean.

---

## Design landmines (record-of-decision)

1. **Directory swap, not marker rewrite.** Two `os.rename`s
   on same FS. Pre-flight refuses if `lancedb-prev/` already
   exists (rollback lifeline preserved).
2. **No warm-reload path on the server.** Cutover requires
   process restart; `/readyz` polling (60s budget) covers
   AC4.
3. **Rollback = inverse swap.** Not "revert marker" — the
   brief's wording was misleading.
4. **`compute_eval` injection pattern carried forward** —
   watchdog post-activation check is invoked via subprocess
   to keep cutover.py importable without the full server
   stack.
5. **restic password loss is permanent.** Runbook + env
   template warn loudly.
6. **`flock` not on macOS by default** — backup wrapper
   `command -v flock` guard (E11_S04 IS1 lesson).
7. **`command -v uv`, no hardcoded `/Users/` paths**
   (E11_S02 IS2 lesson).
8. **All cron wrappers carry `set -euo pipefail`**, atomic
   `tmp+rename` sentinels, `set -euo pipefail`-propagating
   `exec`s.
9. **Backup wrapper exits non-zero on any restic failure**;
   sentinel write is skipped on failure (consistent with
   E11_S02 + E11_S03 patterns).
10. **Documentation= URLs point at the canonical GitHub
    location**, not install-time `/etc/arxmcp/` paths (E11_S04
    IS3 lesson).
11. **Restore drill smoke check is LIGHT**, not a full server
    run. Catches "is the data readable?" — retrieval quality
    is the watchdog's job.

---

## External writes required at code-ship

**None.** Operator-runtime writes:

- `var/arxmcp/index/lancedb/` ← `os.rename` from staging
  (THE cutover write).
- `var/arxmcp/index/lancedb-prev/` ← rollback snapshot.
- `var/arxmcp/index/lancedb-failed-cutover-<ts>/` on rollback.
- `var/arxmcp/ops/restore-drill-passed.flag`.
- `var/arxmcp/ops/backup-status.json`.
- restic repository writes to NAS or B2 (the actual backup).

---

## Verification against the synthesis "Done-when" checklist

- [x] All 5 brief ACs covered (3 fully + 2 operator-gated with
  synthetic tests).
- [x] Directory swap implemented with rollback safety.
- [x] `lancedb-prev/` preflight check in place.
- [x] `/readyz` polling honors 60s budget.
- [x] Restore drill writes the `restore-drill-passed.flag`
  sentinel atomically.
- [x] Backup wrapper carries `flock`, `command -v
  uv/flock/restic` guards, no hardcoded paths.
- [x] systemd unit hardening directives match E11_S02 pattern.
- [x] Runbooks document all 4 criteria + rollback time + state
  file schemas.
- [x] README Operations table linked.
- [x] `make cutover` target with Python version guard + ARGS
  word-split note.
- [x] No `TOOL_SCHEMA_VERSION` bump.
- [x] `make test` green; ruff clean.

---

## Open follow-ups (NOT this milestone)

- **`requires_restic` pytest marker.** A future commit could
  add a `requires_restic` marker (env-gated:
  `ARXMCP_RUN_RESTORE_DRILL=1`) for an end-to-end test that
  invokes the real restic binary against a test repository.
- **Cross-process /metrics for backup status** (E14). Mirrors
  E11_S04 AC3 deferral.
- **Pre-flight check: `lancedb-failed-cutover-*` accumulation.**
  Multiple failed cutovers leave many `lancedb-failed-cutover-<ts>/`
  directories. A future cleanup could compact them.
- **Automated rollback** is explicitly out of scope per the
  brief (human-in-the-loop). `make cutover ARGS="--rollback"`
  is the manual mechanism.
- **`Wants=arxmcp-delta.service`** chaining for the systemd
  backup unit. v1 ships them independently; an operator can
  add the dependency if they want.

---

## H9 closure

This milestone closes the H9 design finding:

> "200K scale cutover trigger explicit and measurable — nDCG@5
> ≥ 0.80 on the new corpus version (not a vague 'when we feel
> ready'). The rollback plan is concrete and takes < 30
> seconds. Without an explicit trigger and a tested rollback,
> a cutover risks stranding agents on a degraded corpus with
> no recovery path."

The 4 activation criteria (seed eval / staging watchdog /
ingest complete / restore drill) are mechanically checked by
`ops/cutover.py`. The rollback is two `os.rename`s + a server
restart. The Tier-5 cutover trigger in `.claude/TIER-GATES.md`
is now executable, not aspirational.
