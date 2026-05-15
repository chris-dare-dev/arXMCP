# E11_S05 Research Brief — Axis 2: Backup / Restore / Systemd

**Researcher axis:** backup/restore (restic) operations + systemd unit discipline + restore drill semantics.
**Peer axis (brief-1):** cutover mechanics + activation criteria.
**Date:** 2026-05-15

---

## 1. restic Toolkit Overview

**Version pin:** require `restic >= 0.16`. The 0.16 series introduced
JSON progress output and the `--compression` flag; 0.17 (current as of
2026) adds zstd by default. Version guard in `ops/restic-env.sh.template`:

```bash
RESTIC_MIN_VERSION="0.16.0"
```

**Install:**
- macOS: `brew install restic` (Homebrew ships 0.17.x as of 2026).
- Debian/Ubuntu: `apt install restic` (package exists in Debian bookworm+;
  may trail upstream — prefer the GitHub release binary pinned at 0.17.x
  for production).
- Other Linux: `dnf install restic` (Fedora), `pacman -S restic` (Arch),
  or download the static binary from `https://github.com/restic/restic/releases`.

**Repository backends — both must work:**

| Backend | `RESTIC_REPOSITORY` value | Extra env vars |
|---|---|---|
| Local NAS (bind-mount) | `/mnt/nas/arxmcp` | none |
| Backblaze B2 | `b2:arxmcp-backups:` | `B2_ACCOUNT_ID`, `B2_ACCOUNT_KEY` |

**All required env vars:**
```
RESTIC_REPOSITORY      # required; validated non-empty at script start
RESTIC_PASSWORD_FILE   # path to a file containing the repository password
B2_ACCOUNT_ID          # only required when backend is b2:
B2_ACCOUNT_KEY         # only required when backend is b2:
```

**Credential handling discipline:**
- `ops/restic-env.sh.template` is committed (no creds, placeholder comments).
- `ops/restic-env.sh` (operator-filled) is gitignored. Add to `.gitignore`:
  ```
  ops/restic-env.sh
  ```
- `RESTIC_PASSWORD_FILE` points to a file (e.g. `/etc/arxmcp/restic-password`)
  that contains ONLY the password (no trailing newline required; restic strips
  whitespace). Never set `RESTIC_PASSWORD` directly in the env — process lists
  expose it.

**Encryption:** restic encrypts all repository data at rest using AES-256-CTR
with HMAC-SHA256 authentication. The encryption key is derived from the
password via scrypt. **Losing the password = permanent data loss** — there is
no recovery path. Document this in the operator runbook with emphasis.

**First-time repository initialization:**
```bash
source ops/restic-env.sh
restic init
```
For B2: the bucket must exist and the account key must have
`readFiles`, `writeFiles`, `deleteFiles` capabilities on the bucket.

---

## 2. `ops/restic-env.sh.template` Shape

This file is sourced by `ops/cron/arxmcp-backup.sh` before invoking restic.
It is a bash script, not a dotenv file — the sourcing wrapper uses
`source ops/restic-env.sh` with `set -euo pipefail` already active in the
caller.

**Key structural decisions:**

1. **Empty `RESTIC_REPOSITORY` guard.** If the operator forgets to fill in
   the template, the backup silently succeeds against a misconfigured or
   non-existent repository. Guard at source time:
   ```bash
   if [[ -z "${RESTIC_REPOSITORY:-}" ]]; then
       echo "ERROR: RESTIC_REPOSITORY is not set in ops/restic-env.sh" >&2
       echo "  Edit ops/restic-env.sh from the template and set the" >&2
       echo "  RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE variables." >&2
       exit 1
   fi
   ```

2. **restic binary check.** `command -v restic` with an actionable error.
   Unlike `uv`, restic is not language-specific — it must be on the system
   PATH. No `ARXMCP_RESTIC` override is needed (the binary is stable and
   typically in `/usr/bin/restic` or `/opt/homebrew/bin/restic`).

3. **Dry connectivity check (not a full backup):**
   ```bash
   restic snapshots --json >/dev/null
   ```
   This hits the repository and verifies credentials without reading any
   backup data. Runs at template-source time only if `ARXMCP_RESTIC_CHECK`
   is set — by default the wrapper sources the env file and proceeds; the
   check is opt-in so that CI can source the template without a live
   repository.

4. **B2 conditional.** Export `B2_ACCOUNT_ID` / `B2_ACCOUNT_KEY` only when
   the repository URI starts with `b2:`. This avoids confusing error
   messages when the backend is local NAS.

**Template file path:** `ops/restic-env.sh.template` (committed).
**Filled instance:** `ops/restic-env.sh` (gitignored — add to `.gitignore`).

---

## 3. Systemd Unit Shape

**`ops/systemd/arxmcp-backup.service`** — oneshot unit.

Mirror `ops/systemd/arxmcp-delta.service` exactly, with these differences:
- `Description=arXMCP restic nightly backup`
- `ExecStart=/opt/arxmcp/ops/cron/arxmcp-backup.sh`
- `TimeoutStartSec=14400` — 4 hours. Rationale: ~135GB to local 1Gbit NAS
  is 18-30 min under ideal conditions; B2 is bandwidth-bound (a 100Mbit
  upstream link pushes ~135GB in ~3 hours). 4 hours is defense-in-depth
  without triggering on worst-case B2 runs. The delta timer is already
  capped at 2 hours (`arxmcp-delta.service TimeoutStartSec=7200`); the
  backup needs a wider window because the data volume is an order of
  magnitude larger than a single-day delta.
- `ReadWritePaths=`: restic needs **read** access to the backed-up corpus
  paths (`/opt/arxmcp/var/arxmcp/index/lancedb/`,
  `/opt/arxmcp/var/arxmcp/index/kuzu/`,
  `/opt/arxmcp/var/arxmcp/corpus/chunks/`) and **write** access only to
  `var/arxmcp/ops/` (for the sentinel) and the NAS mount point (for local
  backend). With `ProtectSystem=strict`, the NAS mount must be listed in
  `ReadWritePaths` explicitly if it is under `/mnt/` (systemd's strict
  mode covers `/usr`, `/boot`, `/etc`; NAS mounts under `/mnt/` are
  readable but NOT writable without an explicit `ReadWritePaths` entry).
  Use:
  ```
  ReadWritePaths=/opt/arxmcp/var /mnt/nas
  ```
  For B2 backend, omit the NAS path; traffic exits via the network stack
  which `ProtectSystem=strict` does not block.
- Retain all hardening directives: `ProtectSystem=strict`, `ProtectHome=true`,
  `NoNewPrivileges=true`, `PrivateTmp=true`.

**`ops/systemd/arxmcp-backup.timer`** — nightly trigger.

- `OnCalendar=*-*-* 03:30:00`
- `Persistent=true`, `RandomizedDelaySec=300`.
- Rationale for 03:30: the delta timer fires at 02:00; with
  `RandomizedDelaySec=300` (up to +5min jitter) it starts by 02:05. The
  delta loop runs ≤ 90 min (E11_S02 budget), finishing by ~03:35 on a
  warm day. The re-embed (E11_S03) can add another 30-45 min on a cold
  start. Watchdog (E11_S04) runs at 02:30 (30 min after delta) and takes
  < 5 min. **On a normal night the pipeline is: delta 02:00→03:30,
  re-embed overlapping or absent, watchdog 02:30→02:35.** Backup at
  03:30 gives delta + re-embed the full window they need and avoids
  competing disk I/O.

  The E11_S02 timer comment in `ops/systemd/arxmcp-delta.timer` mentions
  "restic at 04:10" as a prior cadence — 03:30 is slightly more
  aggressive but safe given the 4-hour `TimeoutStartSec`. If the operator
  uses B2 and a slow upstream link, they should shift to 04:00.

---

## 4. `ops/cron/arxmcp-backup.sh` — Shell Wrapper

Mirror `ops/cron/arxmcp-watchdog.sh` exactly for the preamble, then add
backup-specific logic.

**Critical structural decisions:**

1. **flock guard.** Lock file: `var/arxmcp/ops/.backup.lock`.
   `flock` check same as watchdog (E11_S04 IS1 lesson — macOS does not
   have `flock` natively; `brew install util-linux` or `brew install flock`).

2. **Source order:** `source ops/restic-env.sh` MUST happen AFTER the
   lock is acquired. The env file performs a connectivity check (if
   `ARXMCP_RESTIC_CHECK=1`); running it before flock means two concurrent
   backup processes both pass the check and then race on the repository.

3. **Exclude list for `restic backup`:**
   - `.lock` files (`--exclude '*.lock'`)
   - `lancedb-staging-tmp/` (partial writes; E11_S03 staging directory)
   - `*.tmp` (atomic-rename temporaries used by the store writer)
   - `corpus-version.json.tmp` (E11_S05 cutover atomic write pattern)

4. **Retention: run `restic forget --prune` AFTER backup**, not before.
   Running it before risks pruning a snapshot that the current-run delta
   depends on for incremental dedup; running it after means the repository
   is clean post-backup. Policy: `--keep-daily 7 --keep-weekly 4
   --keep-monthly 12`. This matches the brief verbatim and is a standard
   operational minimum for a research corpus.

5. **Sentinel write:** `var/arxmcp/ops/backup-status.json` — atomic
   tmp+rename, same as `re-embed-state.json` and `eval-quarantine.flag`
   patterns. Schema:
   ```json
   {
     "status": "success",
     "snapshot_id": "<restic snapshot short ID>",
     "started_at": "<ISO 8601 UTC>",
     "finished_at": "<ISO 8601 UTC>",
     "paths_backed_up": [
       "/opt/arxmcp/var/arxmcp/index/lancedb/",
       "/opt/arxmcp/var/arxmcp/index/kuzu/",
       "/opt/arxmcp/var/arxmcp/corpus/chunks/"
     ],
     "repository": "<RESTIC_REPOSITORY with creds redacted>"
   }
   ```
   Capture the snapshot ID from `restic backup --json` output; parse it
   with `jq -r '.snapshot_id'` (or Python `json.loads` — prefer jq in
   the shell wrapper for the same reason the delta wrapper uses Python for
   logic-heavy work and bash for glue).

6. **Paths backed up** are relative to the deployment root, not hardcoded
   absolute paths. Use `${REPO_ROOT}/var/arxmcp/...` so the unit works on
   both `/opt/arxmcp` (production) and the developer workstation checkout.

---

## 5. Restore Drill

**Where the drill lives:** `ops/restore_drill.sh`. This is an operator-
initiated script, not a cron unit. It is invoked manually once before the
200K cutover.

**Drill procedure (in order):**

```
1. Pick most-recent restic snapshot:
     SNAPSHOT_ID=$(restic snapshots --json | jq -r 'last | .short_id')

2. Restore to /tmp/arxmcp-restore-drill/:
     restic restore "${SNAPSHOT_ID}" --target /tmp/arxmcp-restore-drill/

3. Run the lightweight smoke check:
     python -m ops.restore_drill_check \
       --restore-path /tmp/arxmcp-restore-drill/

4. If the smoke check exits 0, write the passed flag:
     var/arxmcp/ops/restore-drill-passed.flag

5. Remove the restore directory:
     rm -rf /tmp/arxmcp-restore-drill/
```

**`ops/restore_drill_check.py` — the smoke check module.**

Does NOT import `pytest`. Not a test. Designed to be called as
`python -m ops.restore_drill_check --restore-path <path>`. Logic:

1. Locate the restored LanceDB at `<path>/var/arxmcp/index/lancedb/`.
   Open the `chunks` table using `server.corpus.open_chunks_table`.
2. Assert row count > 0 (`if tbl.count_rows() == 0: raise RuntimeError(...)`).
3. Run a hard-coded ANN query (`embedding_stmt` vector — use a stored
   zero-vector or a random unit vector; we only need the table to be
   readable, not to return high-quality results).
4. Assert the query returns at least 1 result.
5. Verify the Kùzu DB opens at `<path>/var/arxmcp/index/kuzu/` (open
   connection, run `MATCH (p:Paper) RETURN count(p) LIMIT 1`).
6. Exit 0 on success, exit 1 with a clear error message on failure.

**Recommendation: ship the lighter smoke check, not a full server run.**

Full server smoke (start FastAPI, wait for `/readyz`, call `search_papers`
via HTTP) requires ports, BGE-M3, the full Python stack, and a warm-up
window. For a restore drill the question is "is the data intact?", not
"is the retrieval quality good?". The lighter check (open LanceDB, count
rows, ANN-probe, open Kùzu) catches:
- Truncated/corrupt LanceDB write.
- Missing or corrupt Kùzu DB.
- Incorrect restore path (data landed in the wrong subdirectory).

It does NOT catch BGE-M3 encode issues (those are caught by the watchdog
eval, not the restore drill). Document both options in the runbook and
explain why the lighter path ships.

**Sentinel for AC2 in the cutover.sh:** `ops/cutover.sh` (brief-1 axis)
reads `var/arxmcp/ops/restore-drill-passed.flag`. If absent, cutover
refuses. Schema:
```json
{
  "snapshot_id": "<restic short ID>",
  "restored_at": "<ISO 8601 UTC>",
  "smoke_check": "passed",
  "restore_path": "/tmp/arxmcp-restore-drill/",
  "lancedb_row_count": <N>,
  "kuzu_paper_count": <N>
}
```

---

## 6. `docs/ops/backup-restore.md` Runbook Structure

Mirror the section structure of `docs/ops/drift-watchdog.md` (headings,
admonition boxes, no numbered front matter). Sections:

1. **Scope.** What this runbook covers: restic configuration, first-time
   setup, nightly scheduling, retention, restore drill, catastrophic
   recovery. What it does NOT cover: cutover activation (see
   `cutover-runbook.md`).

2. **Prerequisites.**
   - `restic >= 0.16` on PATH.
   - `flock` (util-linux) on PATH.
   - `jq` on PATH (for snapshot ID parsing in the backup wrapper).
   - `ops/restic-env.sh` filled in from the template.
   - For B2 backend: bucket exists; key has `readFiles`, `writeFiles`,
     `deleteFiles`.

3. **First-time setup.**
   - Copy `ops/restic-env.sh.template` → `ops/restic-env.sh`, fill creds.
   - `restic init` to initialize the repository.
   - Test: `restic snapshots` (should list zero snapshots; exit 0).
   - Password file: create at `/etc/arxmcp/restic-password` (root-owned,
     mode 0400). Point `RESTIC_PASSWORD_FILE` at it.

4. **Scheduling.** Enable the systemd timer:
   ```bash
   sudo cp ops/systemd/arxmcp-backup.{service,timer} /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now arxmcp-backup.timer
   ```
   cron fallback: `30 3 * * * /opt/arxmcp/ops/cron/arxmcp-backup.sh`.

5. **Retention policy.** 7 daily / 4 weekly / 12 monthly. Rationale:
   7 daily = full week of point-in-time recovery for ingest bugs that
   silently corrupt the corpus. 4 weekly = one month of course-grained
   recovery. 12 monthly = one year of historical snapshots; the citation
   graph evolves slowly and a 6-month-old snapshot may be the only
   recovery path after a catastrophic NAS failure.

6. **Restore drill procedure.** Step-by-step invocation of
   `ops/restore_drill.sh`. Expected output. Sentinel location.

7. **Full restore procedure (catastrophic recovery).** Steps:
   - Stop MCP server.
   - `restic restore latest --target /var/arxmcp-restored/`.
   - Verify with `ops/restore_drill_check.py`.
   - Move/symlink restored data into place.
   - Update `corpus-version.json` to match the restored snapshot's version.
   - Restart MCP server; hit `/readyz`.

8. **Failure modes.**
   - Network drop mid-backup: restic is resumable; re-run the backup wrapper.
     The in-progress snapshot is marked `incomplete` and cleaned up by
     `restic forget --prune`.
   - Password loss: data is permanently unrecoverable. Mitigation: store
     the password in a password manager AND print a hard copy. Document
     the password file path and the passphrase separately.
   - Full disk (NAS or B2 quota): `restic backup` exits non-zero; the
     sentinel write is skipped (bash `set -euo pipefail` propagates the
     failure). The systemd unit enters `failed` state; `journalctl -u
     arxmcp-backup` surfaces the restic error. Remediation: free space or
     increase quota, then re-run manually.

9. **State file schema.** `backup-status.json` and
   `restore-drill-passed.flag` field definitions (as documented in §4
   and §5 above).

10. **Tradeoffs.** Local NAS vs B2:
    - NAS: faster (1Gbit LAN vs upstream bandwidth); zero egress cost;
      single failure domain (if the NAS dies, backup is gone too).
    - B2: geographically resilient; ~$6/TB/month storage + egress; requires
      an account key and network access. Recommended for production; NAS
      is acceptable for a single-workstation research setup.

---

## 7. Test Surface

**Principle:** cannot invoke restic without a repository. Mock at the
subprocess boundary.

**`tests/test_backup_wrapper.py`** — three test classes:

`TestEnvTemplate`:
- Read `ops/restic-env.sh.template` as text; assert `RESTIC_REPOSITORY`
  appears; assert `RESTIC_PASSWORD_FILE` appears; assert no literal
  credential values (regex: `[A-Za-z0-9]{30,}` in a value position is a
  smell — flag as test warning, not hard failure, because the template
  may legitimately contain placeholder strings).
- Assert the file is NOT executable by default (mode check) — the operator
  sources it; it is not run directly.

`TestSystemdUnit`:
- Read `ops/systemd/arxmcp-backup.service` as text; assert
  `TimeoutStartSec=14400`; assert `ProtectSystem=strict`; assert
  `ProtectHome=true`; assert `NoNewPrivileges=true`; assert `Type=oneshot`.
- Read `ops/systemd/arxmcp-backup.timer` as text; assert
  `OnCalendar=*-*-* 03:30:00`; assert `Persistent=true`.

`TestShellWrapper`:
- Read `ops/cron/arxmcp-backup.sh` as text; assert `set -euo pipefail`;
  assert `.backup.lock` appears (lock file pattern); assert
  `restic backup` appears; assert `restic forget --prune` appears;
  assert `backup-status.json` appears.
- Assert no hardcoded `/opt/arxmcp` or `/Users/chris.dare` paths (any
  path component that starts with a known username is a red flag).

**`tests/test_restore_drill.py`** — two test classes:

`TestSentinelWrite`:
- Mock `subprocess.run` for restic calls (snapshot list + restore).
- Mock `ops.restore_drill_check` to return success.
- Call `restore_drill.run_drill(restore_path=tmp_path)`.
- Assert `var/arxmcp/ops/restore-drill-passed.flag` exists and parses as
  valid JSON with `smoke_check == "passed"`.

`TestRestoreDrillCheck`:
- Use a synthetic LanceDB (same `_graph_helpers.py` pattern from E09_S04).
- Call `restore_drill_check.run_check(restore_path=synthetic_path)`.
- Assert exit 0 on valid data; assert non-zero exit on empty table.

**Pytest marker:** `requires_restic` — gated by env var
`ARXMCP_RUN_RESTORE_DRILL=1`. The smoke-check test uses synthetic data
and does NOT require the marker. Only the end-to-end drill (which calls
real restic against a real repository) gets `requires_restic`.

---

## Open Questions

1. **`jq` as a dependency.** The backup wrapper uses `jq` to parse the
   restic JSON output for the snapshot ID. `jq` is not a declared
   prerequisite in any existing runbook. Add it to the Prerequisites
   section, or replace it with a Python one-liner:
   `python3 -c "import json,sys; print(json.load(sys.stdin)[-1]['short_id'])"`.
   The Python path avoids a new binary dependency and is consistent with
   the project's Python-heavy ops scripts.

2. **`ops/restic-env.sh.template` sourced vs executed.** The template
   itself does not contain a shebang (it is not executed; it is sourced).
   Should the file be named `ops/restic-env.sh.template` (current plan)
   or `ops/restic.env.template` (more conventional dotenv naming)? The
   `.sh.template` suffix makes explicit that it is bash syntax, which is
   correct since it uses `[[ ]]` syntax. Keep `.sh.template`.

3. **NAS mount persistence.** The systemd backup service needs the NAS
   mount active before it runs. Should `arxmcp-backup.service` declare
   `Requires=mnt-nas.mount` and `After=mnt-nas.mount`? This is
   site-specific. Recommend documenting the pattern in the runbook with
   a placeholder and leaving the shipped unit without the `Requires=`
   line (the backup wrapper will fail cleanly if the NAS is unmounted
   because `restic backup` will exit non-zero, which `set -euo pipefail`
   propagates to systemd `failed` state).

4. **Restore drill frequency.** The brief says "once before the 200K
   cutover". Should the drill be added to the systemd schedule (e.g.
   monthly)? Out of scope per the brief, but document a cron template
   in the runbook for operators who want periodic drills.

---

## External Writes the Implementation Requires

| Type | Target | Why |
|---|---|---|
| File write (committed) | `ops/restic-env.sh.template` | Operator configuration template — committed to repo |
| File write (committed) | `ops/cron/arxmcp-backup.sh` | Nightly backup shell wrapper — committed to repo |
| File write (committed) | `ops/systemd/arxmcp-backup.service` | systemd service unit — committed to repo |
| File write (committed) | `ops/systemd/arxmcp-backup.timer` | systemd timer unit — committed to repo |
| File write (committed) | `ops/restore_drill.sh` | Restore drill operator script — committed to repo |
| File write (committed) | `ops/restore_drill_check.py` | Restore smoke-check Python module — committed to repo |
| File write (committed) | `docs/ops/backup-restore.md` | Operator runbook — committed to repo |
| File write (committed) | `tests/test_backup_wrapper.py` | Unit tests for the above — committed to repo |
| File write (committed) | `tests/test_restore_drill.py` | Unit tests for the restore drill — committed to repo |
| .gitignore mutation | `ops/restic-env.sh` line in `.gitignore` | Prevent credential file from being committed |
| **Operator-runtime write** | NAS path or B2 bucket | Actual backup data — NOT a code-ship action; requires an initialized restic repository on operator hardware. This is the external write the code enables, not performs. |
| **Operator-runtime write** | `/etc/arxmcp/restic-password` | Password file on the production host — operator action at deploy time |
| **Operator-runtime write** | `var/arxmcp/ops/backup-status.json` | Written at runtime by the backup wrapper; gitignored under `var/` |
| **Operator-runtime write** | `var/arxmcp/ops/restore-drill-passed.flag` | Written at runtime by the restore drill; gitignored under `var/` |

**The backup itself is operator-runtime, not code-ship.** The implementation
ships configuration, scripts, and tests. The act of running `restic backup`
against a live repository with ~135GB of data requires operator hardware,
a configured repository, and an authorized credential file. This is
explicitly NOT part of the code-ship gate.
