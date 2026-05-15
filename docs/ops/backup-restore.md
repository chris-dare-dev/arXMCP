# Backup/restore runbook (E11_S05)

**Use when:** configuring the nightly restic backup, running
the pre-cutover restore drill, or recovering from a
catastrophic data loss.

> **Losing the restic password = PERMANENT DATA LOSS.** restic
> encrypts all repository data at rest; the encryption key is
> derived from `RESTIC_PASSWORD_FILE` via scrypt. There is no
> recovery path if the password is lost. Store the password in
> a password manager AND a hard copy.

---

## Scope

This runbook covers:

* restic configuration (`ops/restic-env.sh.template` →
  `ops/restic-env.sh`).
* First-time repository initialization (`restic init`).
* Nightly scheduling via systemd timer or cron.
* Retention policy (7 daily / 4 weekly / 12 monthly).
* The pre-cutover restore drill (`ops/restore_drill.sh`).
* Catastrophic full-restore procedure.

It does NOT cover the cutover activation itself — see
[cutover-runbook.md](cutover-runbook.md).

---

## Prerequisites

| Binary | Why | Install |
|---|---|---|
| `restic` ≥ 0.16 | The backup tool | macOS: `brew install restic`. Debian/Ubuntu: `apt install restic`. Other: GitHub release binary. |
| `flock` (util-linux) | Reentrancy guard in the cron wrapper | macOS: `brew install flock`. Linux: pre-installed. |
| `uv` | Project Python runner | `brew install uv` or similar. |
| Python 3 | Snapshot ID parsing | system Python is fine; the wrapper uses `python3 -c` for one-liners. |

Plus an initialized restic repository (NAS path or B2 bucket)
and a password file at `/etc/arxmcp/restic-password` (root-
owned, mode 0400).

---

## First-time setup

1. **Copy the template:**
   ```bash
   cp ops/restic-env.sh.template ops/restic-env.sh
   ```
   `ops/restic-env.sh` is gitignored — the actual creds never
   land in source control.

2. **Edit `ops/restic-env.sh`** to set `RESTIC_REPOSITORY` and,
   for B2 backend, `B2_ACCOUNT_ID` / `B2_ACCOUNT_KEY`.

3. **Create the password file:**
   ```bash
   sudo install -m 0400 -o root /dev/stdin /etc/arxmcp/restic-password <<< "your-strong-password-here"
   ```

4. **Initialize the repository (one-time):**
   ```bash
   source ops/restic-env.sh
   restic init
   ```
   For B2: ensure the bucket exists and the account key has
   `readFiles`, `writeFiles`, `deleteFiles` capabilities.

5. **Test connectivity:**
   ```bash
   ARXMCP_RESTIC_CHECK=1 source ops/restic-env.sh
   restic snapshots
   ```
   Should print zero snapshots and exit 0.

---

## Scheduling

### Linux (systemd, primary)

```bash
sudo cp ops/systemd/arxmcp-backup.{service,timer} /etc/systemd/system/
# Edit the .service file: replace /opt/arxmcp paths + arxmcp
# user/group with your actual values (see comments in the unit).
sudo systemctl daemon-reload
sudo systemctl enable --now arxmcp-backup.timer
```

Inspect:
```bash
systemctl list-timers arxmcp-backup.timer
journalctl -u arxmcp-backup.service -n 200
```

### macOS / Linux fallback (cron)

```
# crontab — fires at 03:30 (90 min after the 02:00 delta).
30 3 * * *  /absolute/path/to/arxmcp/ops/cron/arxmcp-backup.sh
```

---

## Retention policy

`restic forget --prune --keep-daily 7 --keep-weekly 4
--keep-monthly 12` after every backup.

| Tier | Count | Rationale |
|---|---|---|
| Daily | 7 | Full week of point-in-time recovery for ingest bugs that silently corrupt the corpus. |
| Weekly | 4 | One month of course-grained recovery. |
| Monthly | 12 | One year of historical snapshots — citation graph evolves slowly; a 6-month-old snapshot may be the only recovery path after a catastrophic NAS failure. |

Total disk footprint (dedup-aware): typically 2-3× a single
backup's size. For a ~135GB corpus → ~270-400GB on the
repository.

---

## Restore drill (before cutover)

The pre-cutover drill is the gate for Criterion 4 of E11_S05's
cutover. It verifies the backup is RESTORABLE — not just that
`restic backup` exited 0.

```bash
ops/restore_drill.sh
```

What it does:

1. Picks the most-recent restic snapshot.
2. Restores to `/tmp/arxmcp-restore-drill/`.
3. Runs `python -m ops.restore_drill_check` against the
   restored data:
   * Opens the LanceDB chunks table; asserts row count > 0.
   * Opens the Kùzu citation graph (optional — passes if
     directory absent).
4. On success, writes
   `var/arxmcp/ops/restore-drill-passed.flag` with the
   snapshot ID + timestamp.
5. Cleans up `/tmp/arxmcp-restore-drill/`.

The flag is what cutover.py reads for C4. Without it, the
cutover refuses.

The smoke check is intentionally LIGHT — open LanceDB, count
rows, open Kùzu. It does NOT start the full MCP server (BGE-M3
warm-up + FastAPI would add ~30s without catching anything the
light check misses). Retrieval-quality regression is the
watchdog's (E11_S04) job, not the drill's.

---

## Full restore (catastrophic recovery)

When the active corpus is unrecoverable (disk failure, ransomware,
"I `rm -rf`'d the wrong directory"):

```bash
# 1. Stop the MCP server.
sudo systemctl stop arxmcp-server.service

# 2. Source restic env.
source ops/restic-env.sh

# 3. Pick a snapshot. List recent ones:
restic snapshots --json | python3 -c \
  'import json, sys; [print(s["short_id"], s["time"], s["paths"][0]) for s in json.loads(sys.stdin.read())[-10:]]'

# 4. Restore. The corpus paths under the snapshot live at
#    /opt/arxmcp/var/... (or wherever the backup wrapper
#    captured them).
restic restore <SNAPSHOT_ID> --target /var/arxmcp-restored/

# 5. Verify with the drill check (use the actual restored path):
python -m ops.restore_drill_check \
    --restore-path /var/arxmcp-restored \
    --snapshot-id <SNAPSHOT_ID> \
    --flag-path /tmp/manual-restore-check.flag

# 6. Move/symlink restored data into place.
#    The exact path depends on how the snapshot was captured
#    (relative or absolute). Typical:
sudo mv /var/arxmcp-restored/opt/arxmcp/var/arxmcp/index/lancedb \
        /opt/arxmcp/var/arxmcp/index/lancedb

# 7. Restart MCP server.
sudo systemctl start arxmcp-server.service

# 8. Hit /readyz and verify the corpus version.
curl -fsS http://127.0.0.1:7733/readyz
```

---

## Failure modes

### Network drop mid-backup

restic is resumable. Re-run `ops/cron/arxmcp-backup.sh`
manually. The in-progress snapshot is marked incomplete and
cleaned up by the next `restic forget --prune`.

### Password loss

Data is permanently unrecoverable. Mitigation: store the
password in a password manager AND print a hard copy. Document
the password file path and the passphrase separately so a
future operator can find both halves.

### Full disk (NAS or B2 quota)

`restic backup` exits non-zero; the sentinel write is skipped
(bash `set -euo pipefail` propagates the failure). The systemd
unit enters `failed` state; `journalctl -u arxmcp-backup`
surfaces the restic error. Remediation: free space or increase
quota, then re-run manually.

### Lock file stale

If a previous backup process crashed mid-run, `flock -n` may
indicate the lock is held. The lock file at
`var/arxmcp/ops/.backup.lock` is just a sentinel; deleting it
is safe if no `arxmcp-backup` process is actually running.

---

## State file schema

### `var/arxmcp/ops/backup-status.json`

```json
{
  "finished_at": "2026-05-15T03:51:12Z",
  "paths_backed_up": [
    ".../var/arxmcp/index/lancedb",
    ".../var/arxmcp/index/kuzu",
    ".../var/arxmcp/corpus/chunks"
  ],
  "repository": "/mnt/nas/arxmcp",
  "snapshot_id": "abc12345",
  "started_at": "2026-05-15T03:30:00Z",
  "status": "success"
}
```

### `var/arxmcp/ops/restore-drill-passed.flag`

```json
{
  "kuzu_paper_count": 50,
  "lancedb_row_count": 1234,
  "restore_path": "/tmp/arxmcp-restore-drill",
  "restored_at": "2026-05-15T04:00:00Z",
  "smoke_check": "passed",
  "snapshot_id": "abc12345"
}
```

---

## Tradeoffs

| | Local NAS | Backblaze B2 |
|---|---|---|
| Speed | 1Gbit LAN (~18 min for 135GB) | Bandwidth-bound (~3h on 100Mbit) |
| Egress cost | $0 | ~$10/TB egress |
| Geographic resilience | Single failure domain (NAS dies, backup gone) | Resilient |
| Cost | NAS hardware | ~$6/TB/month storage |
| Setup complexity | Lower | Account + bucket + key |

Recommend NAS for single-workstation research. Recommend B2 (or
B2 + NAS) for production / shared deployments.

---

## See also

* [ops/restic-env.sh.template](../../ops/restic-env.sh.template)
* [ops/cron/arxmcp-backup.sh](../../ops/cron/arxmcp-backup.sh)
* [ops/restore_drill.sh](../../ops/restore_drill.sh)
* [ops/restore_drill_check.py](../../ops/restore_drill_check.py)
* [ops/systemd/arxmcp-backup.service](../../ops/systemd/arxmcp-backup.service)
* [ops/systemd/arxmcp-backup.timer](../../ops/systemd/arxmcp-backup.timer)
* [docs/ops/cutover-runbook.md](cutover-runbook.md) — consumes
  the restore-drill flag.
