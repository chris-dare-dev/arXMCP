# Critique — E11_S05

**Critic:** infra-safety
**Generated:** 2026-05-15T00:00:00Z
**Commit range:** 584443a..6d3a1fe
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. IS1 is the most significant finding: `ops/cutover.sh`
  has no `flock` guard, meaning two concurrent operator invocations (even
  accidental) can double-swap the `lancedb/` directory tree and leave the
  system in an unrecoverable state without manual inspection.
- 0 CRITICAL, 1 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk file: `ops/cutover.sh` (no lock + IS1), compounded by
  `ops/cutover.py::perform_directory_swap` (no internal guard).
- Cross-axis pattern: sentinel write ordering issues appear in both
  `ops/cron/arxmcp-backup.sh` (IS2) and the restore drill (IS4 edge case);
  a general "write the sentinel BEFORE the cleanup/retention step, with
  partial-status fields" convention would close all three.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — `cutover.sh` has no flock guard against concurrent invocations

- **Severity:** HIGH
- **Source:** infra-safety
- **File:** ops/cutover.sh:36
- **What:** `ops/cutover.sh` `exec`s directly into `python -m ops.cutover`
  with no `flock` guard. Two concurrent operator invocations (typo, tmux
  split, or systemd accidental trigger) would both pass the criterion checks
  (identical state at that instant), both call `perform_directory_swap`, and
  the second invocation's first rename (`lancedb/ → lancedb-prev/`) would
  fail with `CutoverError("refusing to overwrite existing rollback path")`
  — but only if the first invocation already completed step 1. If the two
  invocations interleave between steps 1 and 2 of the first swap, the
  active path ends up missing entirely (both renames on different invocations
  may conflict), leaving the server without a readable corpus path.
- **Why it matters:** The atomic directory swap in `perform_directory_swap`
  has a two-rename window with no internal locking; the Python module itself
  documents this. An operator double-invocation turns the 200K cutover into
  a data-availability incident (server fails `/readyz`, no active corpus).
- **Proposed fix:** Add a `flock` wrapper in `ops/cutover.sh` before the
  `exec` call, using the same lock-file pattern as `ops/cron/arxmcp-backup.sh`:

  ```bash
  LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.cutover.lock"
  mkdir -p "$(dirname "${LOCK_PATH}")"
  exec flock -n "${LOCK_PATH}" \
      "${UV_BIN}" run python -m ops.cutover "$@"
  ```

  Alternatively, document in `docs/ops/cutover-runbook.md` that the operator
  MUST verify no other cutover process is running (e.g. `fuser
  .cutover.lock`) before proceeding — but the shell-level guard is
  preferable.
- **Regression guard:** Add a test in `tests/test_cutover.py` that calls
  `perform_directory_swap` twice concurrently via `threading.Thread` and
  asserts the second call raises `CutoverError`. Alternatively, add a
  comment-level test verifying `ops/cutover.sh` contains the string `flock`.

---

### IS2 — `restic forget` failure suppresses sentinel write; operator has no record of backup success

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** ops/cron/arxmcp-backup.sh:88
- **What:** In the inner `bash -euo pipefail -c '...'` block, `restic forget
  --prune` runs at line 88 BEFORE the atomic sentinel write (`mv
  "${TMP_STATUS}" "${STATUS_FILE}"`) at line 108. If `restic forget` exits
  non-zero (e.g. network blip to B2, corrupted lock file, B2 rate-limit),
  `set -euo pipefail` aborts the inner shell and the sentinel is never
  written. The backup DID succeed and the snapshot exists, but the operator
  has no `backup-status.json` record of it.
- **Why it matters:** The restore drill (C4) relies on `backup-status.json`
  to confirm a recent backup exists. A forget-only failure silently looks
  identical to "backup never ran", which may prevent the cutover from
  proceeding. The actual data is safe, but the operator cannot distinguish
  the two cases without querying `restic snapshots` manually.
- **Proposed fix:** Write a partial sentinel immediately after the backup
  (before `forget`), then overwrite with the final status after `forget`
  succeeds:

  ```bash
  # After extracting SNAPSHOT_ID:
  cat > "${TMP_STATUS}" <<EOF
  { ..., "status": "backup_complete_forget_pending", "snapshot_id": "${SNAPSHOT_ID}" }
  EOF
  mv "${TMP_STATUS}" "${STATUS_FILE}"

  restic forget --prune ...

  # Overwrite with final status:
  cat > "${TMP_STATUS}" <<EOF
  { ..., "status": "success", "snapshot_id": "${SNAPSHOT_ID}" }
  EOF
  mv "${TMP_STATUS}" "${STATUS_FILE}"
  ```

  Alternatively, capture `restic forget` exit code with `|| true` and record
  `"forget_status": "failed"` in the sentinel.
- **Regression guard:** No automated test is feasible for this script path
  without a live restic repository. Add a comment in the script noting the
  ordering constraint and verify in the backup-restore runbook.

---

### IS3 — `ARXMCP_RESTIC_CHECK` connectivity opt-in is never set by the backup wrapper; the check is effectively dead code in production

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** ops/restic-env.sh.template:63
- **What:** `ops/restic-env.sh.template` gates a `restic snapshots`
  connectivity check on `ARXMCP_RESTIC_CHECK=1`. Neither
  `ops/cron/arxmcp-backup.sh` nor `ops/restore_drill.sh` sets this variable
  before sourcing the env file. The connectivity check therefore never fires
  in any production or drill invocation.
- **Why it matters:** Silent credential misconfiguration (wrong B2 key, wrong
  bucket name, NAS not mounted) goes undetected until `restic backup` itself
  fails — which, per IS2, may leave no sentinel record. The opt-in was
  presumably intended to fire on first-time setup; without a call site, it
  is unreachable.
- **Proposed fix:** Either (a) remove the `ARXMCP_RESTIC_CHECK` conditional
  and always run `restic snapshots` as a pre-flight in `arxmcp-backup.sh`
  (before the `flock`-protected exec), or (b) document explicitly in
  `ops/restic-env.sh.template` and the runbook that the operator MUST run
  `ARXMCP_RESTIC_CHECK=1 source ops/restic-env.sh` once during initial setup
  and that the variable is never set by the automated scripts.
- **Regression guard:** Shell-level: add `grep -q 'ARXMCP_RESTIC_CHECK'
  ops/cron/arxmcp-backup.sh` to a Makefile `lint-ops` target, or remove
  the feature entirely.

---

### IS4 — `restic backup` exit 3 (partial success) is treated as total failure; no sentinel written for a valid snapshot

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** ops/cron/arxmcp-backup.sh:73
- **What:** `restic backup` exits with code 3 when some source files could
  not be read (e.g. open file handles on hot LanceDB compaction files, stale
  `.lock` files not excluded). The inner `bash -euo pipefail` treats exit 3
  as fatal, aborts before extracting `SNAPSHOT_ID`, and never writes the
  sentinel. A valid (partial) snapshot exists in the restic repository, but
  `backup-status.json` shows no record of it.
- **Why it matters:** For the corpus paths in this project (LanceDB + Kùzu),
  exit 3 during an active ingest run is plausible. The operator sees a missed
  backup when the backup DID land a usable snapshot. The C4 restore-drill
  criterion may block cutover based on stale or absent sentinel data.
- **Proposed fix:** Use an explicit exit-code check rather than `set -e` on
  the restic invocation:

  ```bash
  restic backup ... --json "${BACKUP_PATHS[@]}" | tail -n 1 > "${TMP_SNAP}" \
      ; RESTIC_EXIT=$?
  if [ "${RESTIC_EXIT}" -ne 0 ] && [ "${RESTIC_EXIT}" -ne 3 ]; then
      echo "ERROR: restic backup failed (exit ${RESTIC_EXIT})" >&2
      exit 1
  fi
  SNAPSHOT_JSON="$(cat "${TMP_SNAP}")"
  ```

  Set `"status": "partial"` in the sentinel when exit code is 3, so the
  operator can distinguish partial from full backups.
- **Regression guard:** No live restic test is feasible. Add a script-level
  comment citing the restic exit-code table (`man restic` exit codes 0, 1, 3)
  and document the edge case in the runbook.

---

### IS5 — `ops/restic-env.sh` permissions not enforced programmatically; world-readable B2 credentials risk

- **Severity:** LOW
- **Source:** infra-safety
- **File:** ops/restic-env.sh.template:29
- **What:** The template documents `RESTIC_PASSWORD_FILE` at mode 0400 but
  does not document (or enforce) the mode of the filled `ops/restic-env.sh`
  itself. If the operator copies the template and fills in `B2_ACCOUNT_KEY`
  without restricting permissions, `ls -la ops/restic-env.sh` shows 0644
  (world-readable). The backup wrapper (`arxmcp-backup.sh`) has no mode
  check before sourcing the file.
- **Why it matters:** B2 account keys can be used to read or delete all
  objects in the bucket if they lack bucket-level restrictions. A
  world-readable credentials file on a shared system is a latent credential
  exposure.
- **Proposed fix:** Add a mode check in `arxmcp-backup.sh` before `source
  "${ENV_FILE}"`:

  ```bash
  if [[ "$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || stat -f '%A' "${ENV_FILE}")" != "600" ]]; then
      echo "WARNING: ${ENV_FILE} should be mode 0600 or 0400." >&2
  fi
  ```

  Also add a note in the template: `# Recommended: chmod 0600 ops/restic-env.sh after filling in.`
- **Regression guard:** None required for LOW; document in the runbook.

---

### IS6 — `FINISHED_AT` timestamp captured before `restic forget`; sentinel timestamp semantics are off

- **Severity:** LOW
- **Source:** infra-safety
- **File:** ops/cron/arxmcp-backup.sh:85
- **What:** `FINISHED_AT` is captured at line 85, immediately after the
  backup but before `restic forget --prune` (lines 88–91). The sentinel's
  `finished_at` field therefore represents "backup completed" not "entire
  operation (backup + retention) completed". If `restic forget` takes
  several minutes on a large repository, the `finished_at` timestamp is
  misleading.
- **Why it matters:** Operators reading `backup-status.json` to understand
  when the backup window closed may underestimate the actual impact window.
  Low severity because the difference is typically seconds to minutes, and
  the backup itself is the critical operation.
- **Proposed fix:** Move the `FINISHED_AT` capture to after `restic forget`:

  ```bash
  restic forget --prune ...
  FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  ```

  Or add a separate `forget_finished_at` field.
- **Regression guard:** None required for LOW.

---

## What was done well

- `set -euo pipefail` is present in all three shell scripts (`cutover.sh`,
  `ops/cron/arxmcp-backup.sh`, `ops/restore_drill.sh`), including the inner
  `bash -euo pipefail -c '...'` invocation in `arxmcp-backup.sh` (line 53).
- `command -v uv/flock/restic` dependency guards are present and produce
  actionable error messages in all scripts that require them.
- `${BASH_SOURCE[0]}`-based `SCRIPT_DIR` / `REPO_ROOT` resolution is used
  consistently across all three scripts; no hardcoded absolute paths.
- The `exec flock -n "${LOCK_PATH}" bash -euo pipefail -c '...'` pattern in
  `arxmcp-backup.sh` correctly acquires the lock BEFORE sourcing the env
  file, preventing a race on the optional connectivity check.
- `restic forget --prune` runs AFTER backup completes, not before, so
  retention policy never prunes the just-created snapshot.
- The sentinel (`backup-status.json`) is written atomically via `cat > tmp +
  mv tmp dst`; no partially-written JSON is ever visible to readers.
- `ops/restic-env.sh.template`'s `return 1 2>/dev/null || exit 1` pattern
  correctly handles both sourced and directly-executed invocations.
- `ops/restic-env.sh` is in `.gitignore`; the template (with no credentials)
  is committed at a safe 0644 mode.
- The systemd unit (`arxmcp-backup.service`) ships `ProtectSystem=strict`,
  `ProtectHome=true`, `NoNewPrivileges=true`, `PrivateTmp=true`, and the
  operator substitution comment block is explicit about EVERY placeholder
  (WorkingDirectory, ExecStart, User, Group, ReadWritePaths).
- `arxmcp-backup.timer` has `Persistent=true` and `RandomizedDelaySec=300`,
  matching the defensive posture of the E11_S02 delta-loop timer.
- The `Makefile`'s `cutover:` target correctly adds Python version guard,
  `make help` advertisement with E11_S05 reference, and `$(ARGS)`
  pass-through; it is in `.PHONY`.
- `ops/cutover.py` defers all heavy logic (JSON parsing, atomic renames,
  HTTP polling) to Python where it can be unit-tested; the shell wrapper is a
  thin `exec` relay — exactly the right layering.

## Recommended rectification order

1. **IS1** — Add `flock -n .cutover.lock` to `ops/cutover.sh` before the
   `exec`. Highest blast radius; concurrent cutover can leave the corpus
   path in an ambiguous state and IS1 is on the human-initiated critical
   path for the 200K promotion.
2. **IS2** — Write a partial sentinel (`status: backup_complete_forget_pending`)
   after backup and before `restic forget`; overwrite with final status after
   forget. Closes the operator visibility gap before the first real 200K
   backup fires.
3. **IS4** — Capture `restic backup` exit code explicitly; treat exit 3 as
   partial success and record in sentinel. Depends on IS2 sentinel structure
   (write partial → forget → overwrite) so fix after IS2.
4. **IS3** — Either remove the unreachable `ARXMCP_RESTIC_CHECK` branch or
   add a call site in `arxmcp-backup.sh`. Cheap; 5 LOC change.
5. **IS5** — Add a mode check / warning before `source "${ENV_FILE}"` and
   update the template comment. Cheap; 3 LOC.
6. **IS6** — Move `FINISHED_AT` capture to after `restic forget`. One-line
   change; lowest priority.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
