# E14_S04 — Infra-safety critique

Scope: commit range `028cd35..99e1949` (single commit
`feat(ops): daily/weekly/quarterly ops cadence + cron + systemd (E14_S04)`).

The diff matches the infra-safety trigger: a `Makefile` change (two new
`PHONY` targets) plus the new `ops/cron/` and `ops/systemd/` files. This
critique evaluates cron-wrapper hygiene, systemd-unit hardening, Makefile
discipline, secrets management, and lockfile-path hygiene.

---

## What was done well

- **All three new cron wrappers use `set -euo pipefail` at the top** —
  `ops/cron/arxmcp-daily-report.sh:25`,
  `ops/cron/arxmcp-parser-failures-weekly.sh:21`,
  `ops/cron/arxmcp-quarterly-drill.sh:18`. Errexit + nounset + pipefail
  is the floor for any wrapper that cron will fire on a stale shell.
- **Every wrapper resolves `uv` via the project's canonical preflight
  pattern** (`ARXMCP_UV` override → `command -v uv` → actionable error
  message) — `ops/cron/arxmcp-daily-report.sh:31-41`,
  `ops/cron/arxmcp-parser-failures-weekly.sh:27-36`. Matches the
  existing `arxmcp-delta.sh` / `arxmcp-backup.sh` template.
- **All wrappers gate on `flock(1)` availability with a macOS-aware
  remediation hint** — e.g. `ops/cron/arxmcp-daily-report.sh:44-50`
  prints `brew install flock` for macOS and the util-linux note for
  Linux before exiting 1. This is exactly the short-circuit the brief
  asked for.
- **All wrappers `mkdir -p $(dirname "${LOCK_PATH}")` BEFORE flock-ing**
  — `ops/cron/arxmcp-daily-report.sh:52-55`,
  `ops/cron/arxmcp-parser-failures-weekly.sh:46-49`,
  `ops/cron/arxmcp-quarterly-drill.sh:35-38`. This defends against the
  fresh-checkout / pre-bootstrap cron-fires-first failure mode.
- **All three new wrappers are 0755** (verified via `ls -la
  ops/cron/`). Cron will refuse non-executable shebangs silently.
- **Lockfile paths are globally unique across all six cron wrappers**
  (verified: `.backup.lock`, `.daily-report.lock`, `.delta.lock`,
  `.parser-failures-weekly.lock`, `.quarterly-drill.lock`,
  `.watchdog.lock` — six paths, six wrappers, zero collisions). No
  cross-job interlock corruption is possible.
- **All four new systemd `.service` units use `Type=oneshot` and the
  full hardening trio** (`ProtectSystem=strict`, `ProtectHome=true`,
  `NoNewPrivileges=true`, `PrivateTmp=true`) with a tight
  `ReadWritePaths=/opt/arxmcp/var`. Verified at
  `ops/systemd/arxmcp-daily-report.service:14,33-37`,
  `ops/systemd/arxmcp-parser-failures-weekly.service:7,19-23`,
  `ops/systemd/arxmcp-quarterly-drill.service:9,19-23`,
  `ops/systemd/arxmcp-watchdog.service:15,25-29`.
- **All four `.service` units explicitly set `User=`, `Group=`,
  `WorkingDirectory=`, `StandardOutput=journal`, `StandardError=journal`,
  and a job-appropriate `TimeoutStartSec=`** (300s for daily-report,
  600s for parser-failures + watchdog, 30s for quarterly-drill — sized
  to the actual workload).
- **All four `.timer` units pin `Persistent=true`, explicit `UTC` in
  `OnCalendar=`, `Unit=` referencing the matching `.service`, and
  `RandomizedDelaySec=` (60s for quarterly-drill, 120s for the
  others)** — `ops/systemd/arxmcp-daily-report.timer:10-14`,
  `ops/systemd/arxmcp-parser-failures-weekly.timer:10-14`,
  `ops/systemd/arxmcp-quarterly-drill.timer:13-16`,
  `ops/systemd/arxmcp-watchdog.timer:14-18`. Thundering-herd guarded.
- **The Makefile additions are idempotent and propagate exit codes**
  (`Makefile:187-209`) — both new targets are pure `$(PYTHON) -m
  tools.<x> $(ARGS)` invocations, with the project's standard
  `MIN_PY_MINOR` preflight (matches the `assert sys.version_info`
  pattern used by all 11 existing targets). No `sudo`, no shelling
  out, no side-effect hidden from the user. Help text is added at
  `Makefile:19-20`.
- **The quarterly-drill rationale is documented inline in the
  `.timer`** (`ops/systemd/arxmcp-quarterly-drill.timer:4-8`) —
  daily-fires-with-Python-short-circuit is preferred over
  monthly `OnCalendar=*-01,04,07,10-*` because the 7-day lookahead
  conflicts with the monthly trigger semantics. Good engineering
  judgment captured at the point of decision.

---

## Findings

### IS1 — MEDIUM — `arxmcp-cron.cron` lacks an explicit `/opt/arxmcp`-substitution warning

**File:** `ops/cron/arxmcp-cron.cron:1-31`

The crontab fragment hard-codes `/opt/arxmcp/ops/cron/...` for all six
job lines (lines 15, 18, 21, 24, 27, 31). The header (lines 1-12) tells
the operator to install with `crontab ops/cron/arxmcp-cron.cron` — a
full destructive replace — but does NOT instruct them to first
substitute the install prefix to match their actual checkout path.

An operator who clones to `/home/ops/arxmcp` and runs the install
command verbatim gets a crontab that references nonexistent paths, with
the failure mode being "cron mails MAILTO root every entry, every
day" — i.e. silent until log spam accumulates.

The systemd `.service` files DO warn about this
(`ops/systemd/arxmcp-daily-report.service:15-19` —
"Operator MUST substitute these placeholders before enabling"). The
crontab fragment should have a parallel warning in its header.

**Fix:** prepend the header (around line 3) with something like:

```cron
# BEFORE INSTALLING: substitute `/opt/arxmcp` below for the absolute
# path of your arXMCP checkout (e.g. with: sed -i 's#/opt/arxmcp#'"$PWD"'#g'
# ops/cron/arxmcp-cron.cron). Without this substitution, all six jobs
# resolve to nonexistent paths and cron will email MAILTO=root for every
# missed fire.
```

### IS2 — MEDIUM — Recommended SMTP-secret drop-in pattern not documented

**Files:** `ops/systemd/arxmcp-daily-report.service:39-48`,
`docs/ops/daily-ops-cadence.md:82-87`

The service unit and the cadence doc both tell the operator they can
set `MAIL_TO` / `MAIL_FROM` / `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS`
"in a systemd drop-in or `/etc/default/arxmcp`" — but neither artifact
shows the recommended pattern. The risk surface here is that an
operator follows the prose literally and writes `SMTP_PASS=...` into
the `.service` file (which is world-readable in `/etc/systemd/system/`
by default) or into a non-0600 `/etc/default/arxmcp`.

For the daily-report wrapper specifically, the right pattern is:

```ini
# /etc/systemd/system/arxmcp-daily-report.service.d/10-mail.conf
[Service]
EnvironmentFile=/etc/arxmcp/mail.env       # owner root:arxmcp, mode 0640
```

with `/etc/arxmcp/mail.env` (mode 0640, owner `root:arxmcp`) holding
the key=value lines. That keeps `SMTP_PASS` off the world-readable
unit file path and out of `systemctl cat`.

**Fix:** add a 5-line "recommended secret-handling pattern" block to
`docs/ops/daily-ops-cadence.md` after line 87, showing the drop-in +
0640 envfile pattern. Optionally repeat the snippet in a comment in
`ops/systemd/arxmcp-daily-report.service` around line 46.

This is MEDIUM rather than HIGH because (a) the worst case here is
SMTP credential exposure to local users on the ops host, not remote
egress, and (b) the daily-report email is a notification path, not
the data egress path. But the canonical drop-in pattern should be
spelled out at least once in the operator-facing docs.

### IS3 — LOW — `arxmcp-quarterly-drill.sh` flock guard wins on misleading framing

**File:** `ops/cron/arxmcp-quarterly-drill.sh:24-26`

The wrapper comment says:

```
# flock not strictly required (the reminder is idempotent: it
# refuses to overwrite an existing flag) but kept for consistency
# with the other ops cron wrappers.
```

The wrapper THEN treats missing `flock(1)` as a fatal error (line
27-33: prints `ERROR: flock not found ... exit 1`). The framing
"not strictly required" is in tension with the implementation
"exits 1 if flock is missing." A reader who believes the comment
literally is going to be surprised when their macOS box without
`brew install flock` exits 1 from a job the comment said was
flock-optional.

**Fix:** soften the comment to "flock is treated as mandatory for
consistency with the other ops wrappers, even though the reminder
itself is idempotent." Either consistent-strict (current behavior)
OR flock-optional (would need `if command -v flock; then exec
flock -n ...; else exec ...; fi`) is defensible — pick one and have
the comment match.

---

## Verdict

The infra footprint is solid: hardening flags are uniformly applied,
lockfile-path hygiene is correct across all six wrappers, journal
capture is in place, `Persistent=true` covers the missed-fire
scenario, and the Makefile targets follow the project's existing
discipline (idempotent, `MIN_PY_MINOR` gated, exit-code-clean).

Two MEDIUM findings (IS1, IS2) cluster around operator-substitution
discoverability: the cron fragment doesn't warn about `/opt/arxmcp`,
and the SMTP-secret drop-in pattern is referenced but not shown.
Neither blocks landing — they're documentation deltas that an operator
will hit during first-install and can be patched in a follow-up. One
LOW finding (IS3) is a comment-vs-behavior inconsistency in the
quarterly-drill wrapper.

No CRITICAL or HIGH findings. No container-escape, no privilege
escalation, no secrets-leak in the diff itself, no missing flock, no
exit-code-swallowing.

**Recommendation: land as-is and queue the three findings as a follow-up
docs commit (`docs(ops): document /opt/arxmcp substitution + SMTP-secret
drop-in pattern`).**

---

## Rectification status

- **IS1** (MEDIUM — crontab substitution warning): fixed. Added
  a BEFORE-INSTALLING header block to
  `ops/cron/arxmcp-cron.cron` showing the `sed | crontab`
  one-liner for the operator's actual checkout path. The
  failure mode (cron mails MAILTO=root every entry) is now
  documented inline.
- **IS2** (MEDIUM — SMTP-secret drop-in pattern): fixed. Added
  the §"Recommended secret-handling pattern" subsection under
  §"Email opt-in" in `docs/ops/daily-ops-cadence.md` showing the
  systemd 10-mail.conf drop-in + the mode-0640
  `/etc/arxmcp/mail.env` envfile pattern. The doc now also
  notes that SMTP failures don't crash the cron run (the
  F2 rectification).
- **IS3** (LOW — quarterly-drill flock comment): fixed. Updated
  the comment in `ops/cron/arxmcp-quarterly-drill.sh` to
  explicitly say flock is treated as mandatory for consistency
  with the other ops wrappers, eliminating the
  "not strictly required" framing that conflicted with the
  fail-on-missing-flock behavior below it.
