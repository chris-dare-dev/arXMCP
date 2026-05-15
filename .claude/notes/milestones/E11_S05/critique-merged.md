# Critique — E11_S05 (merged)

**Critics:** adversary (Opus) + infra-safety (Sonnet)
**Generated:** 2026-05-15 (orchestrator merge)
**Commit range:** 584443a..6d3a1fe
**Verdict:** SHIP-WITH-FIXES (both critics)

## Executive summary (orchestrator)

- Combined: **1 CRITICAL, 3 HIGH, 7 MEDIUM, 5 LOW** (16
  findings).
- **F1 (CRITICAL)** — the restore-drill smoke check hardcodes
  `restore_path / "var" / "arxmcp" / ...` but restic restores
  PRESERVE the absolute-path prefix. On any real restore, the
  LanceDB lands at `<restore>/opt/arxmcp/var/arxmcp/...` (not
  `<restore>/var/arxmcp/...`). The smoke check raises
  `RuntimeError("restored LanceDB missing at ...")` on EVERY
  real drill, blocking Criterion 4 and the cutover. **Tests
  passed because they fabricated the directory layout the
  check expects — they didn't exercise the restic path-prefix
  behavior.**
- **F2 (HIGH)** — AC5 enforces relative regression only, not
  the brief's absolute 0.80 floor. The post-activation
  watchdog can return exit 0 on `ndcg5_mean=0.75` (within the
  10% regression threshold). Read the watchdog's report and
  additionally assert `ndcg5_mean >= NDCG5_MIN`.
- **F3 (HIGH)** — runbook documents `sudo install -m 0400 -o
  root /etc/arxmcp/restic-password` but the systemd unit runs
  as `User=arxmcp`. Mode 0400 + root-owned is unreadable by
  non-root. The template's `[[ -r ]]` guard catches it at
  runtime; the docs set up the failure. Switch to `-o arxmcp
  -g arxmcp`.
- **IS1 (HIGH)** — `cutover.sh` has no flock guard. Two
  concurrent operator invocations can leave the active path
  missing. Add `flock -n .cutover.lock` to the wrapper.
- The other MEDIUMs cluster around the backup wrapper: F4/IS2
  (forget failure suppresses sentinel), F5/IS3 (connectivity
  check is dead code), F8 (no cross-FS preflight), IS4
  (restic exit 3 = partial success treated as fatal). All
  fixable with bounded code changes.
- Two LOWs around the documentation URLs and timestamp
  semantics. F11 + the wider Documentation= URL issue from
  E11_S04 IS3 are not yet fixed — defer to a doc-only commit
  unless the repo goes public.
- The cache discipline + atomic swap + rollback pattern are
  all correct. The major issues are documentation gaps and
  operator-experience details rather than fundamental design
  flaws.

## Severity calibration

| level | meaning | rectification action |
|---|---|---|
| CRITICAL | data loss, security regression, broken invariant | always fix in Phase 4 |
| HIGH | wrong behavior on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC) |
| LOW | style, naming, consistency drift | defer |

## Cross-critic agreement

- **F4 (adversary, MEDIUM) + IS2 (infra-safety, MEDIUM)** —
  both flag the `restic forget` failure suppressing the
  sentinel write. Same fix: write a partial sentinel before
  `forget`, overwrite with the final state after.
- **F5 (adversary, MEDIUM) + IS3 (infra-safety, MEDIUM)** —
  both flag the `ARXMCP_RESTIC_CHECK` opt-in being unreachable.
  Same fix: either always-on or document.

## Findings (full bodies in per-critic files)

See [critique-adversary.md](critique-adversary.md) and
[critique-infra-safety.md](critique-infra-safety.md).

### CRITICAL (1)
- **F1** — restore drill can't locate restored LanceDB on real
  restore (`ops/restore_drill_check.py:40`).

### HIGH (3)
- **F2** — AC5 enforces regression only, not the 0.80 floor
  (`ops/cutover.py:628`).
- **F3** — restic-password mode 0400 root-owned unreadable by
  service user (`ops/restic-env.sh.template:29-31` +
  `docs/ops/backup-restore.md:60-63`).
- **IS1** — `cutover.sh` has no flock guard
  (`ops/cutover.sh:36`).

### MEDIUM (7)
- **F4 + IS2 (cross-critic)** — `restic forget` failure
  suppresses sentinel write (`ops/cron/arxmcp-backup.sh:88-108`).
- **F5 + IS3 (cross-critic)** — connectivity check opt-in
  never fires (`ops/restic-env.sh.template:63`).
- **F6** — `--lancedb-staging-path <active>` naming abuse leaks
  into report (`ops/cutover.py:638-644`).
- **F7** — mid-cutover crash recovery is operator-improvised
  (`docs/ops/cutover-runbook.md:205-213`).
- **F8** — cross-filesystem swap not preflight-checked
  (`ops/cutover.py:506`).
- **IS4** — `restic backup` exit 3 (partial success) treated as
  fatal (`ops/cron/arxmcp-backup.sh:73`).

### LOW (5)
- **F9** — restore-drill picks most-recent snapshot without
  tag filtering.
- **F10** — `test_full_swap_when_all_pass` doesn't capture
  operator-message ordering.
- **F11** — Documentation= URL points at potentially private
  repo (E11_S04 IS3 repeat).
- **IS5** — `ops/restic-env.sh` permissions not enforced.
- **IS6** — `FINISHED_AT` timestamp captured before `forget`.

## What was done well (merged)

- Atomic directory swap with pre-flight `lancedb-prev/`
  existence check.
- Rollback is exact inverse of activation.
- Cache discipline preserved (`TOOL_SCHEMA_VERSION` untouched).
- C2 watchdog absolute-floor enforcement at staging is
  correctly strict (though AC5 inherits a weaker version — F2).
- Quarantine-flag posture is correct: cutover REFUSES, never
  auto-clears.
- systemd hardening matches E11_S02 baseline.
- `flock`, `command -v` guards, `set -euo pipefail`
  propagation through `exec flock -n ... bash -euo pipefail -c
  '...'` correctly structured.
- Doc-layout discipline clean; 2 runbooks linked from README.
- `set -euo pipefail` everywhere; atomic sentinel writes
  (tmp+rename).
- `ops/restic-env.sh.template`'s `return 1 2>/dev/null || exit
  1` handles both sourced and executed.
- Argparse defaults are `Path` typed.
- Python heavy logic + thin bash wrapper layering correct.

## Recommended rectification order

1. **F1** (CRITICAL) — Fix the restore drill path resolution.
   Either use `rglob` to find `corpus-version.json` under the
   restore root, OR pass `--include` to restic to scope the
   restore. Add a regression test laying out the absolute-path
   prefix.
2. **F2** (HIGH) — Read the post-activation watchdog's report
   and assert `ndcg5_mean >= NDCG5_MIN` in addition to the
   subprocess exit code.
3. **F3** (HIGH) — Fix the password-file install instructions
   to use `-o arxmcp -g arxmcp` (or mode 0440 with group
   ownership). Update runbook + template.
4. **IS1** (HIGH) — Add `flock -n .cutover.lock` to
   `ops/cutover.sh`. Single-line addition.
5. **F4+IS2** (MEDIUM cross-critic) — Two-phase sentinel:
   `backup_complete_forget_pending` after backup, `success`
   after forget.
6. **F8** (MEDIUM) — `perform_directory_swap` preflight check
   that `st_dev` matches between active and staging.
7. **F5+IS3** (MEDIUM cross-critic) — Remove the
   `ARXMCP_RESTIC_CHECK` opt-in and always run the
   connectivity probe in the wrapper.
8. **F6** (MEDIUM) — Defer. Renaming a CLI flag on
   `ops/watchdog_eval.py` is non-trivial (back-compat for
   E11_S04). Document the naming in the runbook for now.
9. **F7** (MEDIUM) — Document the recovery `mv` commands in
   the cutover runbook (not just prose). A `--recover` flag
   is over-engineering for a rare crash path.
10. **IS4** (MEDIUM) — Explicit `restic backup` exit-code
    handling: treat exit 3 as `"status": "partial"` in the
    sentinel.
11. **IS5** (LOW) — Add a mode-check warning before sourcing
    `restic-env.sh`. Document in the template.
12. **IS6** (LOW) — Move `FINISHED_AT` capture after `restic
    forget`.
13. **F9, F10, F11** — Defer per critic recommendations.

## Rectification status (filled by Phase 4)

- **F1** (CRITICAL) — fixed by replacing the hardcoded
  `restore_path / "var" / "arxmcp" / ...` with two helpers:
  `_locate_lancedb_root` (rglob for `corpus-version.json`) and
  `_locate_kuzu_root` (rglob for `kuzu/` directory under
  `index/`). Restore drill now works regardless of the
  absolute-path prefix restic preserves. Regression guard:
  `TestSmokeCheckLancedb::test_finds_lancedb_under_absolute_path_prefix`
  lays out a synthetic `tmp/opt/arxmcp/var/arxmcp/index/lancedb`
  layout (the realistic restic restore shape) and asserts the
  smoke check succeeds.
- **F2** (HIGH) — fixed by reading the watchdog's report from
  `report_dir` after the subprocess exits and asserting
  `ndcg5_mean >= NDCG5_MIN` in addition to `returncode == 0`.
  Underpowered runs (`ndcg5_mean=null`, `underpowered=true`)
  pass-by-skip. Regression guards:
  `TestPostActivationAbsoluteFloor` (4 sub-tests covering
  low-ndcg-fails, high-ndcg-passes, subprocess-nonzero-fails,
  underpowered-passes).
- **F3** (HIGH) — fixed by updating both
  `ops/restic-env.sh.template` and
  `docs/ops/backup-restore.md` to install the password file
  OWNED by the service user (`-o arxmcp -g arxmcp`), not root.
  Macros for both Linux production and macOS dev. Regression
  guard: `TestPasswordFilePermsDocumentation::test_template_documents_service_user_install`
  + `test_runbook_documents_service_user_install`.
- **IS1** (HIGH) — fixed by adding a `flock -n .cutover.lock`
  guard to `ops/cutover.sh`. Includes the `command -v flock`
  preflight (E11_S04 IS1 pattern). Regression guard:
  `TestCutoverShellWrapperFlock::test_wrapper_acquires_flock`.
- **F4 + IS2** (MEDIUM cross-critic) — fixed by two-phase
  sentinel write in `ops/cron/arxmcp-backup.sh`. A partial
  sentinel `status: "backup_complete_forget_pending"` is
  written immediately after the backup succeeds; the final
  status is written after `restic forget`. Forget failure no
  longer suppresses the backup's record. Regression guard:
  `TestBackupWrapperRectifications::test_two_phase_sentinel`.
- **F5 + IS3** (MEDIUM cross-critic) — fixed by exporting
  `ARXMCP_RESTIC_CHECK=1` in the backup wrapper before
  sourcing `ops/restic-env.sh`. The connectivity probe now
  fires on every nightly run. Regression guard:
  `TestBackupWrapperRectifications::test_connectivity_check_always_on`.
- **F8** (MEDIUM) — fixed in `perform_directory_swap` with an
  `os.stat(*.st_dev)` preflight check across active, staging,
  and rollback parent. Mismatch raises `CutoverError` with an
  actionable message. Regression guard:
  `TestCrossFilesystemSwapRefused::test_refuses_when_active_and_staging_span_filesystems`.
- **IS4** (MEDIUM) — fixed by explicit `restic backup` exit-
  code capture (`set +e ... RESTIC_BACKUP_EXIT=$? ... set -e`).
  Exit 3 (partial success) is treated as `backup_status:
  "partial"` in the sentinel rather than aborting the script.
  Regression guard:
  `TestBackupWrapperRectifications::test_restic_exit_3_handled_as_partial`.
- **IS6** (LOW) — fixed by moving the `FINISHED_AT` capture
  to AFTER the `restic forget` step. Sentinel now reflects the
  end of the whole operation, not just the backup phase.
- **F6** (MEDIUM) — deferred. Renaming a CLI flag on
  `ops/watchdog_eval.py` is non-trivial (E11_S04 back-compat
  for tests + cron). Runbook documents the naming.
- **F7** (MEDIUM) — deferred. The cutover-runbook documents
  the manual `mv` recovery commands; a `--recover` flag is
  over-engineering for a rare crash path.
- **F9** (LOW) — deferred. Single-workstation deployments are
  the primary target; multi-host restic with mixed tags is
  out of scope.
- **F10** (LOW) — deferred. Operator-message-ordering capture
  is a niche regression guard.
- **F11** (LOW) — deferred (same posture as E11_S04 IS3).
  The `Documentation=` URL stays as-is; a future doc-only
  commit can revisit when the repo's visibility is settled.
- **IS5** (LOW) — deferred. Mode-check warning for
  `ops/restic-env.sh` permissions can land as a doc note in a
  follow-up commit.
