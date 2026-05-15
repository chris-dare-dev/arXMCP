# Critique — E11_S05

**Critic:** adversary
**Generated:** 2026-05-15T00:00:00Z
**Commit range:** 584443a..6d3a1fe
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: the restore drill's smoke-check path is
  wrong for any real `restic restore`, so Criterion 4 cannot succeed
  end-to-end in production despite green unit tests.
- Counts: 1 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk file: `ops/restore_drill_check.py:40` —
  hardcodes `restore_path / "var" / "arxmcp" / ...` ignoring the
  absolute-path prefix that restic captures and restores.
- Cross-axis pattern: AC fidelity drift. AC5 ("post-activation
  watchdog nDCG@5 ≥ 0.80") is satisfied by a watchdog that only
  enforces relative regression, not an absolute floor; a regression
  to 0.75 within the 10% default threshold would silently pass AC5.
- Install/runtime mismatch: `restic-password` mode 0400 root-owned
  is unreadable by `User=arxmcp` in the systemd unit. The template's
  `[ -r ]` guard fires at runtime; the docs set up the failure.
- Cache discipline preserved (`TOOL_SCHEMA_VERSION` untouched, no
  tool surface change). Doc-layout discipline clean. Hardening of
  systemd unit matches the E11_S02 baseline.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Restore drill cannot locate restored LanceDB on real restore

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** ops/restore_drill_check.py:40
- **What:** `smoke_check_lancedb` constructs
  `lancedb_path = restore_path / "var" / "arxmcp" / "index" / "lancedb"`.
  But the backup wrapper feeds restic absolute paths
  (`${REPO_ROOT}/var/arxmcp/index/lancedb`, etc.), and `restic
  restore --target X` reconstructs the absolute prefix under X. After
  `restic restore <id> --target /tmp/arxmcp-restore-drill/`, the
  real lancedb lives at
  `/tmp/arxmcp-restore-drill<REPO_ROOT>/var/arxmcp/index/lancedb`
  (e.g. `/tmp/arxmcp-restore-drill/opt/arxmcp/var/arxmcp/index/lancedb`
  for the canonical `/opt/arxmcp` install, or
  `/tmp/arxmcp-restore-drill/Users/chris.dare/.../var/arxmcp/index/lancedb`
  for local dev). The smoke check raises
  `RuntimeError("restored LanceDB missing at <wrong-path>")` and
  Criterion 4 fails on every drill, blocking the cutover the
  milestone is supposed to enable.
- **Why it matters:** the unit tests pass because they fabricate the
  LanceDB at `tmp_path / "var" / "arxmcp" / ...` directly — they do
  not exercise the restic path-prefix behavior. The catastrophic-
  recovery section of `backup-restore.md` (line 190) acknowledges
  the prefix exists by telling the operator to `mv
  /var/arxmcp-restored/opt/arxmcp/var/arxmcp/index/lancedb ...` —
  contradicting what the drill assumes. The H9 closure depends on a
  working drill; this finding invalidates AC2 and AC4 end-to-end.
- **Proposed fix:** in `ops/restore_drill.sh`, pass restic
  `--include /var/arxmcp/index/lancedb` to scope the restore (or use
  `--strip-components` if a stable prefix). Alternatively, in
  `ops/restore_drill_check.py`, search for `corpus-version.json`
  under `restore_path` via `rglob` and resolve the LanceDB root
  from its parent. Same change for the Kùzu path. Document the
  resolution behavior in `backup-restore.md` so the catastrophic-
  recovery example matches.
- **Regression guard:** add a test that lays out a synthetic restore
  tree with the absolute-path prefix (e.g.
  `tmp_path / "opt" / "arxmcp" / "var" / "arxmcp" / "index" /
  "lancedb"`) and asserts `smoke_check_lancedb(tmp_path)` succeeds.
  Without this test the prefix bug reappears silently.

### F2 — AC5 enforces regression, not the ≥ 0.80 absolute floor

- **Severity:** HIGH
- **Source:** adversary
- **File:** ops/cutover.py:628 (`run_post_activation_watchdog`)
- **What:** AC5 in the brief is "post-cutover watchdog nDCG@5 ≥
  0.80". The implementation invokes `python -m ops.watchdog_eval
  --lancedb-staging-path <active>` and accepts `returncode == 0` as
  PASS. The watchdog (E11_S04) only flips to non-zero when a
  **relative regression** exceeds the threshold (`evaluate_regression`
  in `ops/watchdog_eval.py:198`). With the default
  `DEFAULT_REGRESSION_THRESHOLD_PCT = 10.0` and a prior C2 baseline
  of 0.83, a post-activation nDCG of 0.75 has regression_pct ≈ 9.6%
  — under threshold — and the watchdog exits 0. AC5 reports PASS
  even though `nDCG@5 < 0.80`.
- **Why it matters:** the brief's bright-line gate is an absolute
  floor, not a regression bound. The synthesis frames C2 as the
  upstream check (which DOES enforce 0.80 absolutely in
  `check_criterion_2_watchdog`), but AC5's stated job is the
  post-activation re-verification — exactly the place where a stray
  config drift or env-var difference between staging and the active
  path could land you at sub-floor quality and still report green.
  This is the H9 trigger; a soft AC5 invalidates the "explicit and
  measurable" framing.
- **Proposed fix:** after the watchdog subprocess returns, read the
  freshly-written report from `var/arxmcp/ops/eval-reports/` (or
  parse it from `--dry-run` JSON stdout) and additionally assert
  `ndcg5_mean >= NDCG5_MIN`. Treat watchdog exit 0 PLUS report
  `ndcg5_mean >= 0.80` as PASS; either condition alone is FAIL.
- **Regression guard:** add a unit test that stubs
  `run_post_activation_watchdog`'s subprocess to write a watchdog
  report with `ndcg5_mean=0.75, alert_triggered=False` and asserts
  `run_cutover` returns 1 — locks the absolute-floor enforcement
  in place.

### F3 — restic-password mode 0400 root-owned unreadable by service user

- **Severity:** HIGH
- **Source:** adversary
- **File:** ops/restic-env.sh.template:29-31 and
  docs/ops/backup-restore.md:60-63
- **What:** the template + runbook tell the operator to install the
  password file with `sudo install -m 0400 -o root /dev/stdin
  /etc/arxmcp/restic-password`. The systemd unit at
  `ops/systemd/arxmcp-backup.service:24` runs as `User=arxmcp`. A
  mode-0400 file owned by root is **unreadable** by any non-root
  user; the `arxmcp` service user has no read permission. The
  template's `[[ ! -r "${RESTIC_PASSWORD_FILE}" ]]` guard correctly
  catches it at first run, but the install path documented in the
  runbook is guaranteed-broken on Linux.
- **Why it matters:** the operator follows the documented setup,
  enables the timer, and the FIRST nightly backup fails with a
  non-obvious "password file not readable" error in `journalctl`.
  On macOS dev (`User=...` typically a personal user owning the
  password file) this hides because the password file is read by
  the human. The runbook implies "test connectivity" works because
  the operator runs `source ops/restic-env.sh` interactively — as a
  user that CAN read root-owned 0400. The mismatch only appears
  under systemd.
- **Proposed fix:** in `docs/ops/backup-restore.md` and
  `ops/restic-env.sh.template`, document either (a) mode 0440 with
  group ownership matching the service group, or (b) mode 0400
  owned by `arxmcp:arxmcp` (not root) and a note that no other
  non-root user can read it. Update the install snippet:
  `sudo install -m 0400 -o arxmcp -g arxmcp /dev/stdin
  /etc/arxmcp/restic-password`.
- **Regression guard:** add a test (or shellcheck-style line check)
  that the template's documented `install` command's `-o` argument
  matches the `User=` in `arxmcp-backup.service`. A simple grep
  pinning the two together prevents silent drift.

### F4 — `restic forget --prune` failure leaves backup-status.json stale silent

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ops/cron/arxmcp-backup.sh:88-108
- **What:** the wrapper executes `restic backup ... | tail -n 1`,
  then `restic forget --prune --keep-daily 7 ...`, then writes
  `backup-status.json` with `status: "success"`. Under
  `set -euo pipefail`, a non-zero `restic forget` aborts BEFORE the
  sentinel is written. So a partial-success run (backup OK,
  retention failed because of a transient B2 outage or a stale
  lock) leaves yesterday's sentinel in place. An operator
  monitoring `backup-status.json.finished_at` would not notice the
  retention failure; the repo accumulates snapshots past the
  intended retention horizon (eventual disk-quota failure).
- **Why it matters:** the milestone explicitly chose retention as
  a brief deliverable. Leaving retention failures invisible
  defeats the point. The runbook's "Full disk" failure mode says
  "the systemd unit enters `failed` state" — true ONLY when
  systemd's journal is also being watched. There's no separate
  signal in the sentinel JSON.
- **Proposed fix:** split into two restic calls with separate exit
  status capture, then write the sentinel with three statuses:
  `success`, `backup_ok_retention_failed`, `failed`. Or: write a
  "backup-only" sentinel after the backup succeeds, and a
  "retention-status" sentinel separately. Either way the sentinel
  surfaces partial-success states that systemd-level monitoring
  misses.
- **Regression guard:** add a wrapper test that simulates restic
  failure (script substitution + `PATH` injection in a tmp dir)
  and asserts the sentinel reflects the partial state.

### F5 — Connectivity check opt-in via env never fires in production

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ops/restic-env.sh.template:63 and
  ops/cron/arxmcp-backup.sh
- **What:** `restic-env.sh.template` gates the
  `restic snapshots --json` connectivity check on
  `ARXMCP_RESTIC_CHECK=1`. The backup wrapper sources the env file
  but never sets that variable. The check therefore only runs when
  the operator manually exports it during interactive setup.
  Nightly runs skip the connectivity probe entirely. The first
  signal of a broken repository is the actual `restic backup`
  invocation failing several minutes in — diagnostically noisier
  than a 1-second probe.
- **Why it matters:** the synthesis cites D5 as the operator-
  experience goal; a connectivity probe that never auto-fires
  is wasted code. It exists, the tests assert it exists, but the
  wrapper bypasses it.
- **Proposed fix:** either (a) have the wrapper export
  `ARXMCP_RESTIC_CHECK=1` before sourcing, gated on a separate
  ARXMCP env var if the operator wants to disable; or (b) make the
  check default-on and use the env var to disable. Document
  whichever direction in `backup-restore.md`.
- **Regression guard:** add a backup-wrapper test that asserts the
  effective `restic snapshots` is actually invoked when sourcing
  the env file via the wrapper.

### F6 — `--lancedb-staging-path <active>` naming abuse leaks into reports

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ops/cutover.py:638-644
- **What:** the post-activation watchdog is launched with
  `--lancedb-staging-path <active_path>`. The watchdog's argparse
  help text says "Staging LanceDB path (read-only)". The freshly-
  written report at `var/arxmcp/ops/eval-reports/corpus_v<N>-*.json`
  records the path verbatim, so a later operator inspecting the
  report sees a `lancedb-staging-path` field pointing at the active
  data — confusing for forensic review of a regression after
  rollback.
- **Why it matters:** the milestone's value is operator clarity
  around the cutover boundary. Re-purposing a "staging" argument
  for active-path eval blurs the boundary in the very artifacts
  meant to document it.
- **Proposed fix:** rename the watchdog CLI arg to
  `--lancedb-path` (with a back-compat alias for
  `--lancedb-staging-path` if you must) OR add a
  `--mode={pre,post}-cutover` flag that the watchdog records in
  the report. The cutover script then calls `--mode=post-cutover
  --lancedb-path <active>`.
- **Regression guard:** assert in a unit test that a watchdog
  report written in `post-cutover` mode includes a discriminator
  field.

### F7 — Mid-cutover crash recovery is operator-improvised, not automated

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/ops/cutover-runbook.md:205-213, ops/cutover.py
- **What:** if `cutover.py` dies between the two `os.rename` calls,
  the active path is briefly missing. The runbook tells the
  operator to "manually rename the directories to restore one of:
  - lancedb-staging/ is intact → re-run; - lancedb-prev/ is intact →
  rename to lancedb/". But cutover.py's pre-flight check at
  `perform_directory_swap` REFUSES when `lancedb-prev/` already
  exists. The recommended recovery action (re-running cutover)
  thus fails closed; the operator must read code to learn the
  manual `mv` command. No `--recover` or `--force-resume` flag
  exists.
- **Why it matters:** the milestone's brief promises < 30s
  rollback. Mid-cutover crash is rare but recoverable only by
  hand-typing two `mv` commands. The pre-flight check protects
  against overwriting a prior rollback snapshot, but it also
  blocks the documented recovery path. An operator under pressure
  may rename the wrong way.
- **Proposed fix:** add a `--resume-after-crash` subcommand to
  `ops/cutover.py` that detects the inconsistent state (active
  missing, both lancedb-prev/ and lancedb-staging/ present, or
  lancedb-staging/ already renamed into place mid-flight) and
  guides the operator to a safe completion. Alternatively,
  document the specific `mv` commands in the runbook (not just
  prose) so the recovery is copy-pasteable.
- **Regression guard:** synthetic test that lays out an
  inconsistent on-disk state and asserts the recovery flag picks
  the right direction.

### F8 — Cross-filesystem swap not preflight-checked

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ops/cutover.py:506 (`perform_directory_swap`),
  docs/ops/cutover-runbook.md
- **What:** `os.rename` raises `OSError: [Errno 18] EXDEV: Invalid
  cross-device link` when source and target span filesystems. The
  docstring documents "POSIX-atomic on the same filesystem" but
  no preflight verifies it. In Docker (E14-pending) the operator
  may bind-mount `var/arxmcp/index/lancedb-staging` to a host
  path different from `var/arxmcp/index/lancedb` — the cutover
  blows up only after the C1-C4 checks all pass. The error message
  is a raw OSError, not the actionable `CutoverError` the rest of
  the orchestrator emits.
- **Why it matters:** Docker deployments are an explicit local-
  first constraint of the project. The cutover's atomicity
  guarantee silently degrades to "best-effort + crash". The brief
  pursues a 30s rollback that assumes both paths are on the same
  FS.
- **Proposed fix:** preflight: `os.stat(active_path).st_dev ==
  os.stat(staging_path.parent).st_dev`. Raise `CutoverError` with
  an actionable message if they differ. Document the check in
  `cutover-runbook.md` and call it out in the Docker section of
  the future E14 work.
- **Regression guard:** unit test that asserts
  `perform_directory_swap` raises `CutoverError` on a mocked
  `os.stat` returning different `st_dev` values for the two
  paths.

### F9 — Restore-drill script doesn't honor staging path-resolution drift

- **Severity:** LOW
- **Source:** adversary
- **File:** ops/restore_drill.sh:50-52
- **What:** the script picks "the most-recent" snapshot via
  `restic snapshots --json | python3 -c '...[-1]["short_id"]'`.
  But restic's `snapshots` order is not guaranteed by timestamp
  (it's by creation order in the repository index, which usually
  but not always matches wall-clock). On a multi-host restic
  repository (the operator backed up two machines into the same
  repo), the most-recent snapshot may belong to a different host,
  not the arXMCP corpus. The smoke check then opens random data.
- **Why it matters:** single-workstation deployments are the
  primary target so this is unlikely to fire in practice. Worth
  flagging because the drill is operator-gated; a misbehaving
  drill puts the cutover in a "looks green but isn't" state.
- **Proposed fix:** filter to snapshots tagged with arXMCP
  (`restic snapshots --tag arxmcp --json`) and have the backup
  wrapper add the tag at backup time
  (`restic backup --tag arxmcp ...`).
- **Regression guard:** none required at this severity.

### F10 — TestRunCutover swap test mocks /readyz but not server-state

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_cutover.py:504-549
- **What:** `test_full_swap_when_all_pass` mocks `poll_readyz` to
  return True. The actual `os.rename` calls run against tmp_path.
  The test asserts the final filesystem state (active has
  `NEW-data`, rollback has `OLD-data`) — good. But the test does
  NOT verify the operator-message ordering (the script prints
  "restart the MCP server" BEFORE polling readyz, which is the
  one place the operator could trigger an out-of-order restart).
  No regression guard on the message-order contract.
- **Why it matters:** the runbook (line 130) tells the operator
  to start the server "while make cutover polls /readyz, in
  another terminal". If a future refactor moves the print AFTER
  the poll (or removes the operator instruction), the runbook
  silently drifts. Catch the contract in a test.
- **Proposed fix:** capture stdout in `test_full_swap_when_all_pass`
  via `capsys` and assert the "restart" message appears before
  the readyz-poll start log. Cheap to add; locks the operator
  contract.
- **Regression guard:** the `capsys` assertion is itself the
  guard.

### F11 — Documentation= URL points at a not-yet-public repo

- **Severity:** LOW
- **Source:** adversary
- **File:** ops/systemd/arxmcp-backup.service:9,
  ops/systemd/arxmcp-backup.timer:10
- **What:** both unit files reference
  `https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/...`.
  The repository may not be public yet, in which case
  `systemctl status` shows a documentation URL that 404s for any
  non-owner operator. E11_S04 had the same finding (IS3); this
  milestone repeats it.
- **Why it matters:** `systemctl status` is the first place a
  troubleshooting operator looks. A 404 documentation URL is
  worse than no URL (signals carelessness).
- **Proposed fix:** until the repo is public, point `Documentation=`
  at the in-repo file path: `file:///opt/arxmcp/docs/ops/
  backup-restore.md` with a comment that says to update on
  publication. Alternatively, omit `Documentation=` entirely.
- **Regression guard:** none.

## What was done well

- Atomic directory swap with a pre-flight `lancedb-prev/`
  existence check is the right pattern; the synthesis correctly
  refused the brief's "rewrite marker" framing.
- Rollback is the exact inverse of activation — two renames,
  preserved failed state — and is reachable via
  `make cutover ARGS="--rollback"`.
- Cache discipline preserved: no tool surface change,
  `TOOL_SCHEMA_VERSION` untouched, no `server/` files modified.
- C2 (watchdog absolute-floor enforcement at staging) is correctly
  strict; the regression check at `< NDCG5_MIN` is the load-bearing
  gate, even though AC5 inherits a weaker version (see F2).
- Quarantine-flag posture is correct: cutover REFUSES on flag
  presence, never auto-clears. `_clear_quarantine_flag` is
  reachable only through the watchdog CLI as intended.
- systemd unit hardening matches the E11_S02 baseline (Protect*,
  NoNewPrivileges, PrivateTmp, ReadWritePaths) with a justified
  4h TimeoutStartSec.
- `flock`, `command -v` guards, `set -euo pipefail` propagation
  through the `exec flock -n ... bash -euo pipefail -c '...'` is
  correctly structured.
- Doc-layout discipline clean: two runbooks in `docs/ops/`, both
  linked from `README.md` Operations table.
- Argparse defaults are `Path` typed; injection points are
  controlled. (Single-user trust model.)
- Test count delta +75 is honest about what's tested (file-content
  + synthetic) vs what's operator-gated (restic + live server).

## Recommended rectification order

1. **F1** (restore-drill path resolution) — CRITICAL, blocks the
   entire H9 closure. Touch `ops/restore_drill_check.py` +
   `ops/restore_drill.sh` + test. Likely 30-50 LOC.
2. **F3** (password-file permissions doc) — HIGH and trivially
   docs-only. Fix before any operator follows the runbook.
3. **F2** (AC5 absolute-floor enforcement) — HIGH; the load-bearing
   gate that justifies the milestone's existence. Touch
   `ops/cutover.py::run_post_activation_watchdog` + new test.
4. **F4** (retention failure surfacing) — MEDIUM; one of the
   two retention deliverables doesn't have a monitoring path.
   Bash-level fix; touch the wrapper.
5. **F8** (cross-FS preflight) — MEDIUM; cheap to add, prevents
   confused Docker debugging later.
6. **F6** (`--lancedb-staging-path` naming) — MEDIUM; rename or
   add a mode discriminator; touch the watchdog CLI.
7. **F5** (connectivity-check auto-fire) — MEDIUM; toggle the
   default-on direction in template + wrapper.
8. **F7** (mid-cutover recovery automation) — MEDIUM; document
   the manual `mv` commands at minimum.
9. **F10** (test message-ordering contract) — LOW; cheap test.
10. **F9** (drill snapshot selection) — LOW; one-line restic tag
    fix in the wrapper + drill script.
11. **F11** (Documentation= URL) — LOW; deferrable.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
