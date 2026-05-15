# Critique — E11_S02

**Critic:** infra-safety
**Generated:** 2026-05-15T00:00:00Z
**Commit range:** 76f7373..478cd44
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. The infrastructure is functionally correct and safe for a
  single-operator deployment; three issues constrain operator reproducibility
  or create silent misconfiguration risk on multi-operator deployments.
- Finding counts: 0 CRITICAL, 2 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk file: `ops/systemd/arxmcp-delta.service:21` — `ExecStart` is
  hardcoded to `/opt/arxmcp/ops/cron/arxmcp-delta.sh` but the in-unit comment
  only flags `WorkingDirectory` and `User/Group` as operator-substitution
  targets; `ExecStart` is silently left behind if the operator substitutes
  the former without the latter.
- `UV_BIN` defaults to a single-user workstation path
  (`/Users/chris.dare/Library/Python/3.9/bin/uv`). The shell wrapper
  provides an `ARXMCP_UV` escape hatch, which is the right pattern; the
  issue is only documentation, not code.
- The `Documentation=file:/etc/arxmcp/docs/ops/delta-loop.md` URI points to
  a path that does not exist after a standard `cp` install; `journalctl -u
  arxmcp-delta` always reads the `Documentation=` field.
- The reentrancy guard via `flock -n` is per-host; two operators sharing the
  same LanceDB staging tree via NFS can race. Not called out anywhere.
- Systemd hardening is minimal-but-honest for a workstation project; missing
  kernel-level syscall and namespace isolation is a known gap, not a mistake.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — ExecStart hardcode not flagged in operator comment

- **Severity:** HIGH
- **Source:** infra-safety
- **File:** ops/systemd/arxmcp-delta.service:21
- **What:** The in-file comment (`# Operator MUST set WorkingDirectory …
  replace \`arxmcp\` below …`) names `WorkingDirectory` and `User/Group` as
  substitution targets but omits `ExecStart=/opt/arxmcp/ops/cron/arxmcp-delta.sh`.
  An operator who changes `WorkingDirectory=/srv/arxmcp` and `User=myuser`
  without also patching `ExecStart` will get `Unit arxmcp-delta.service
  entered failed state` on the first `systemctl start`.
- **Why it matters:** silently misconfigured systemd units fail at runtime,
  not at install time, breaking the nightly harvest on an otherwise valid
  setup.
- **Proposed fix:** extend the comment block before `WorkingDirectory` to
  read: `# Operator MUST replace /opt/arxmcp in WorkingDirectory, ExecStart,`
  `# and ReadWritePaths — and replace \`arxmcp\` with the actual user/group.`
  Also update the corresponding paragraph in `docs/ops/delta-loop.md` which
  currently reads "replace /opt/arxmcp and the arxmcp user/group" to
  enumerate `ExecStart` explicitly.
- **Regression guard:** add a shell test in `tests/test_ops_systemd.py` that
  parses the service unit and asserts that every occurrence of `/opt/arxmcp`
  appears in a comment line beginning with `# Operator MUST` or in a line
  that the comment block immediately precedes. Alternatively, assert that the
  service file contains exactly N occurrences of `/opt/arxmcp` and that each
  is flagged in the comment.

### IS2 — UV_BIN default is a single-user workstation path

- **Severity:** HIGH
- **Source:** infra-safety
- **File:** ops/cron/arxmcp-delta.sh:36
- **What:** `UV_BIN="${ARXMCP_UV:-/Users/chris.dare/Library/Python/3.9/bin/uv}"`
  names a user-specific macOS Homebrew Python 3.9 installation as the
  fallback. On any other machine — a CI server, a Linux workstation, a
  co-developer's Mac — the fallback path is absent and `flock … uv run`
  exits 127 with a confusing `No such file or directory` rather than `uv not
  found`. The same hardcode exists in `ops/cron/latexml-drift-check.sh:36`
  (pre-existing, not introduced in this diff, but the pattern is now
  replicated).
- **Why it matters:** any second operator or CI environment will see a
  silent flock-wrapped failure with a misleading exit code; the cron mailer
  surfaces `exit 127` but not the root cause.
- **Proposed fix:** replace the fallback with `command -v uv 2>/dev/null ||
  { echo "ERROR: uv not found. Set ARXMCP_UV or install uv." >&2; exit 1; }`
  and drop the hardcoded path entirely. Operators on the primary workstation
  already have `uv` on `PATH` (verified by `make bootstrap`). Add a note to
  `docs/ops/delta-loop.md` Prerequisites that `ARXMCP_UV` overrides the PATH
  lookup.
- **Regression guard:** add a `shellcheck` annotation or a test that
  `grep -n '/Users/' ops/cron/arxmcp-delta.sh` returns empty; this prevents
  personal paths from re-entering the cron wrappers.

### IS3 — Documentation= URI points to a non-existent install-time path

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** ops/systemd/arxmcp-delta.service:9
- **What:** `Documentation=file:/etc/arxmcp/docs/ops/delta-loop.md` specifies
  a path that does not exist after the documented `sudo cp
  ops/systemd/arxmcp-delta.service /etc/systemd/system/` install. The repo's
  operator doc lives at `docs/ops/delta-loop.md` relative to the checkout;
  nothing in the install runbook creates `/etc/arxmcp/` or symlinks to it.
  `journalctl --cat-follows=1 -u arxmcp-delta.service` prints the
  `Documentation=` value; operators who click it get a `file not found`
  error.
- **Why it matters:** misleads operators looking for recovery instructions
  during an incident, which is exactly when the Documentation= URI is most
  valuable.
- **Proposed fix:** either (a) change `Documentation=` to a URL such as
  `Documentation=https://github.com/…/docs/ops/delta-loop.md` (points to a
  canonical location regardless of install path), or (b) add one line to the
  install instructions in `docs/ops/delta-loop.md` that creates the symlink:
  `sudo mkdir -p /etc/arxmcp/docs/ops && sudo ln -s \$(pwd)/docs/ops/delta-loop.md
  /etc/arxmcp/docs/ops/delta-loop.md`. Option (a) is simpler.
- **Regression guard:** no automated test is practical (it's a URI
  reachability check); document the intent in the install runbook and accept
  a one-time review.

### IS4 — Reentrancy guard does not protect multi-operator / NFS deployments

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** ops/cron/arxmcp-delta.sh:39
- **What:** `flock -n "${LOCK_PATH}"` serializes concurrent runs on a single
  host but the lock file is at `var/arxmcp/ops/.delta.lock` relative to the
  checkout. Two operators who mount the same LanceDB staging tree via NFS
  (or two systemd units on separate machines targeting a shared NFS
  `var/`) have separate lock files and can race on the LanceDB single-writer
  constraint enforced in `ingest/store.py`.
- **Why it matters:** `ingest/store.py` documents the single-writer
  invariant for the staging dataset; a concurrent write path violates it and
  can corrupt the staging LanceDB.
- **Proposed fix:** add a one-sentence caveat to `docs/ops/delta-loop.md`
  (Prerequisites or a new "Single-writer constraint" warning box):
  "The `flock -n` guard serializes concurrent runs on the same host only.
  Do not run the delta loop from two hosts targeting the same staging
  LanceDB; the LanceDB single-writer constraint (ingest/store.py) is not
  NFS-safe."
- **Regression guard:** documentation-only fix; no automated test needed.

### IS5 — Missing `make delta` target creates Makefile gap vs E11_S01 pattern

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** Makefile:1
- **What:** E11_S01 added `make ingest` as the one-shot operator entry point
  for the bulk harvester. E11_S02 ships `ops/cron/arxmcp-delta.sh` as the
  equivalent entry point for the delta loop, but the Makefile has no
  corresponding `make delta` target. The `make help` output lists `make
  ingest` but not the delta loop.
- **Why it matters:** new operators following the pattern established by
  `make ingest` will not discover the delta loop from `make help`; the
  discoverability gap is especially visible because `docs/ops/delta-loop.md`
  does not cross-reference `make delta` (because the target does not exist).
- **Proposed fix:** add a `make delta` target that invokes
  `./ops/cron/arxmcp-delta.sh $(ARGS)` and update `.PHONY` and `make help`
  accordingly. This mirrors the `make ingest` pattern exactly.
- **Regression guard:** `grep -q '^delta:' Makefile` in a smoke test or CI
  lint step.

### IS6 — Timer fires in local time; ops cadence doc specifies UTC start

- **Severity:** LOW
- **Source:** infra-safety
- **File:** ops/systemd/arxmcp-delta.timer:12
- **What:** `OnCalendar=*-*-* 02:00:00` fires at 02:00 in the systemd
  clock's local timezone (not UTC). The timer unit comment says "The 02:00
  slot matches the project's daily ops cadence … OAI-PMH starts at 00:00
  UTC." A US Pacific operator (UTC-8) fires at 10:00 UTC — 10 hours after
  the OAI-PMH window opens — which is harmless because the delta harvester
  harvests by date, not by a race against the endpoint. However, the comment
  implies the 02:00 slot is chosen for UTC proximity, which is true only for
  UTC+0/+2 operators.
- **Why it matters:** cosmetic but could mislead a UTC-8 operator who trusts
  the comment and wonders why their 02:00 run is 10 hours "late".
- **Proposed fix:** either add `[Timer]\nAccuracySec=1us` and
  `OnCalendar=*-*-* 02:00 UTC` to fix the timezone, or rephrase the comment
  to "02:00 local time — the harvest window is date-based; UTC proximity is
  not required."
- **Regression guard:** none needed; comment clarification only.

### IS7 — Systemd unit missing defense-in-depth hardening directives

- **Severity:** LOW
- **Source:** infra-safety
- **File:** ops/systemd/arxmcp-delta.service:30
- **What:** The unit has `ProtectSystem=strict`, `ProtectHome=true`,
  `NoNewPrivileges=true`, `PrivateTmp=true` — a reasonable minimum for a
  workstation project. Missing directives that systemd-analyze security would
  flag: `ProtectKernelTunables=true`, `ProtectKernelModules=true`,
  `ProtectControlGroups=true`, `RestrictNamespaces=true`,
  `RestrictSUIDSGID=true`, `LockPersonality=true`, and
  `SystemCallFilter=@system-service`. Without them,
  `systemd-analyze security arxmcp-delta.service` returns a C or D rating.
- **Why it matters:** for a single-operator workstation project these gaps
  are acceptable; for a multi-tenant or shared server they are a meaningful
  attack-surface expansion.
- **Proposed fix:** add the missing directives in a `# Extended hardening
  (recommended for server deployments)` comment block so operators can
  opt-in without surprises. No Python regressions expected; `uv run` does
  not need kernel module loading or SUID.
- **Regression guard:** none needed; this is an optional hardening expansion.

## What was done well

- `set -euo pipefail` is present and correct in `ops/cron/arxmcp-delta.sh`;
  the script fails fast on any unset variable or command error.
- `SCRIPT_DIR / REPO_ROOT` resolution via `${BASH_SOURCE[0]}` is the correct
  portable pattern for cron invocations where `$0` may be mangled.
- `mkdir -p "$(dirname "${LOCK_PATH}")"` before `flock` guarantees the lock
  directory exists on first run; no operator pre-seeding required.
- `exec flock -n …` correctly replaces the shell process so the PID tracked
  by systemd is the `uv run` process, not a wrapper shell.
- `ARXMCP_UV` environment variable override is documented in both the script
  header and `docs/ops/delta-loop.md`, providing a clean escape hatch for
  non-default installations.
- `Type=oneshot` is the correct systemd service type for a finite,
  cron-driven job; `forking` or `simple` would be wrong here.
- `Persistent=true` on the timer ensures a missed 02:00 run (machine off)
  fires at next boot rather than being silently dropped.
- `RandomizedDelaySec=300` provides 5-minute jitter — good practice even for
  a single-host setup (avoids thundering herd if the project is ever
  distributed).
- `TimeoutStartSec=7200` provides a 2-hour hard stop at the systemd level,
  giving 30 minutes of margin beyond the Python 90-minute soft budget — a
  genuine defense-in-depth layer.
- `docs/ops/delta-loop.md` is substantive: it documents prerequisites,
  smoke-test procedure, scheduling instructions for both systemd and cron,
  latency budget, failure modes, and state-file schema. This is well above
  the minimum for ops runbooks.

## Recommended rectification order

1. **IS2** — Replace hardcoded `UV_BIN` fallback with `command -v uv` guard;
   highest operator-reproducibility impact, 3-line change in the shell
   wrapper.
2. **IS1** — Extend the in-service-file operator comment to name `ExecStart`
   and `ReadWritePaths` as substitution targets; update `delta-loop.md` to
   match.
3. **IS3** — Change `Documentation=` URI to a URL or add the symlink step to
   the install runbook; low effort, high incident-response value.
4. **IS4** — Add one-sentence NFS / multi-host single-writer caveat to
   `docs/ops/delta-loop.md`; documentation only.
5. **IS5** — Add `make delta` target to Makefile; mirrors `make ingest`
   pattern, ~5 lines.
6. **IS6** and **IS7** — Low severity; address only if time allows.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
