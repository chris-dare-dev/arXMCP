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
* Retention policy (7 daily / 4 weekly / 12 monthly,
  `--group-by host`).
* The pre-cutover restore drill (`ops/restore_drill.sh`), which now
  runs `restic check --read-data-subset=5%` then verifies the restore.
* Catastrophic full-restore procedure.

**What is backed up** (the `--files-from-verbatim -` manifest in
`ops/cron/arxmcp-backup.sh`):

* `var/arxmcp/index/lancedb/`, `var/arxmcp/index/kuzu/`,
  `var/arxmcp/corpus/chunks/` — corpus + indices (re-buildable, but slow).
* `var/arxmcp/notebooks/` — **user data** (notebook-ops-hardening-m1):
  uploaded PDFs, `papers.txt` / `queries.json`, the per-notebook LanceDB
  store + `lancedb-prev-*` rollback targets. Non-regenerable in practice.
* `var/arxmcp/cache/notebooks.db` — notebook metadata
  (notebook-ops-hardening-m1). **Exception** to the "caches are not backed
  up" rule; WAL-checkpointed (`PRAGMA wal_checkpoint(TRUNCATE)` via
  `ops/checkpoint_notebooks_db.py`) before the snapshot.

**Excluded** (regenerable): `*/cache/retrieval.db` (global + per-notebook
query caches), `*.lock`, `*.tmp`, `lancedb-staging-tmp`.

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

3. **Create the password file** — owned by the SERVICE user
   (the value of `User=` in `ops/systemd/arxmcp-backup.service`),
   NOT root. A root-owned mode-0400 file is unreadable by any
   non-root user, including the `arxmcp` service user.
   ```bash
   # Linux production (service user = "arxmcp"):
   sudo install -m 0400 -o arxmcp -g arxmcp /dev/stdin \
       /etc/arxmcp/restic-password <<< "your-strong-password-here"

   # macOS dev (you are the service user — plain owner):
   install -m 0400 /dev/stdin ~/.config/arxmcp/restic-password \
       <<< "your-strong-password-here"
   ```
   Point `RESTIC_PASSWORD_FILE` at the resulting path.

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

### Restic prune vs LanceDB MVCC version directories (E14_S05)

`restic forget --prune` operates on RESTIC SNAPSHOTS — it
removes snapshot pointers and (with `--prune`) the dedup'd data
blocks they uniquely reference. **It NEVER touches the live
`${ARXMCP_DATA_DIR}/index/lancedb/` directory.**

The corruption-fallback contract in
[`docs/ops/failure-modes.md`](failure-modes.md#lancedb-corruption)
depends on LanceDB's own MVCC version directories
(`_versions/<v>.manifest`, `_data/...`) remaining ON DISK after
an ingest writes a new version. Restic's prune cannot affect
that because restic does not own the live filesystem path.

The hazard would be `ingest/store.py` calling
`dataset.cleanup_old_versions()` — which it does NOT today. The
in-tree contract (verified by grep against the ingest tree):
LanceDB version dirs are append-only and never reclaimed in v1.
If a future milestone introduces version reclamation, it MUST
preserve N-1 to keep the fallback target alive — document this
explicitly in that milestone's brief.

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
  "backup_status": "ok",
  "finished_at": "2026-05-15T03:51:12Z",
  "forget_status": "ok",
  "last_success_at": "2026-05-15T03:51:12Z",
  "paths_backed_up": [
    ".../var/arxmcp/index/lancedb",
    ".../var/arxmcp/index/kuzu",
    ".../var/arxmcp/corpus/chunks",
    ".../var/arxmcp/notebooks",
    ".../var/arxmcp/cache/notebooks.db"
  ],
  "repository": "/mnt/nas/arxmcp",
  "restic_backup_exit": 0,
  "restic_forget_exit": 0,
  "snapshot_id": "abc12345",
  "started_at": "2026-05-15T03:30:00Z",
  "status": "ok"
}
```

#### Status vocabulary

`status` is the single token the `/metrics` and `/status` readers
consume. It is **shared**, not per-file: the producer half lives in
[`ops/cron/backup-status-lib.sh`](../../ops/cron/backup-status-lib.sh)
and the consumer half in
[`server/backup_status.py`](../../server/backup_status.py), bound by
`tests/test_backup_status_vocabulary.py`.

| `status` | Meaning | Advances `last_success`? |
|---|---|---|
| `ok` | Snapshot taken **and** retention applied. | yes |
| `partial` | A snapshot exists but the run was not clean — `restic backup` exit 3, a degraded `notebooks.db` WAL checkpoint, or a failed `restic forget`. | no |
| `failed` | No usable snapshot; `restic backup` hard-failed. `snapshot_id` is `null` and `paths_backed_up` is empty. | no |
| `running` | Two-phase sentinel: snapshot landed, `forget` still in flight. Carries no `finished_at`. | no |

`unknown` is a **consumer-only** cell. The wrapper never writes it; the
server routes any unrecognised token there and logs a WARNING, which is
what `ArXMCPBackupStatusUnknown` alerts on.

The "advances `last_success`" column above is about `last_success_at`,
which every sentinel carries — a `failed` / `partial` / `running` run
re-states the value the prior run left rather than dropping it. Only an
`ok` run replaces it with its own `finished_at`. `null` means no
successful backup is on record at all. See "Metrics surface" below.

Which phase degraded a `partial` run is read off the separate
`backup_status` and `forget_status` fields — deliberately not folded
back into `status`. Composite tokens of the form
`backup_<x>_forget_<y>` were the arXMCP#202 bug: they matched no
consumer state, so every run — including a perfect one — classified as
`unknown` and `arxmcp_backup_status{state="ok"}` sat at 0.0 forever.

### `var/arxmcp/ops/restore-drill-passed.flag`

```json
{
  "kuzu_paper_count": 50,
  "lancedb_row_count": 1234,
  "notebook_pdf_count": 2,
  "notebooks_db_found": true,
  "restore_path": "/tmp/arxmcp-restore-drill",
  "restored_at": "2026-05-15T04:00:00Z",
  "smoke_check": "passed",
  "snapshot_id": "abc12345"
}
```

`notebooks_db_found` is `false` (not an error) when restoring a pre-m1
snapshot taken before notebooks entered backup scope, or on a fresh install
with no notebooks. `notebook_pdf_count` counts uploaded PDFs found under the
restored `notebooks/` subtree.

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

## Metrics surface (E14_S01)

The MCP server's `/metrics` endpoint exposes two backup gauges,
rehydrated at scrape time from `var/arxmcp/ops/backup-status.json`:

| Metric | Type | Meaning |
|---|---|---|
| `arxmcp_backup_last_success_timestamp_seconds` | Gauge | Unix epoch of the last **successful** backup, taken from the sentinel's `last_success_at`. `0` until the first successful backup runs. |
| `arxmcp_backup_status{state="ok"\|"partial"\|"failed"\|"running"\|"unknown"}` | Gauge | Exclusive 1.0 on the current state. All cells are `0` until the first backup runs. |

The freshness gauge is gated on `status`, so a failed or partial run
leaves it where the last good backup put it and its age keeps growing.
Before arXMCP#203 the reader stamped it from `finished_at` *before*
looking at `status` at all — a nightly backup could fail indefinitely
while `ArXMCPBackupStale` stayed silent, because the failing runs kept
moving the clock forward.

**The last-good time survives a restart.** The freshness gauge is still
process state rehydrated from the sentinel, and the sentinel still
records only the *most recent* run — but the wrapper now carries a
`last_success_at` field forward onto **every** sentinel it writes,
including the `failed` / `partial` / `running` ones. So a server restart
taken while the latest run is broken rehydrates the gauge to the real
last-good timestamp instead of starting at `0`, and `ArXMCPBackupStale`
fires (when it should) with a meaningful age. `/status`'s `backup:time`
check reads the same field, and reports both facts at once: that the
latest run did not succeed, *and* how long ago the last one that did was.

Mechanics: `ops/cron/arxmcp-backup.sh` reads the prior sentinel before
overwriting it (`arxmcp_backup_prior_last_success` in
[`ops/cron/backup-status-lib.sh`](../../ops/cron/backup-status-lib.sh)),
preferring the prior `last_success_at` and falling back to the prior
`finished_at` only when that run's `status` was `ok` — the upgrade path
for sentinels written before the field existed. The value advances only
on a clean run, the same gate as `FRESHNESS_ADVANCING_STATES`. It is
`null` until the first success, which a consumer must read as "no
successful backup on record" rather than as a timestamp.

Two residual notes for triage. A sentinel written by a pre-`last_success_at`
wrapper carries no history, so the first run after the upgrade reports
`null` unless that older sentinel happened to be `ok`; the next clean run
seeds the chain. And the field is a *record of*, not a *proof of*, a
snapshot — `restic snapshots` remains the ground truth if you suspect the
sentinel itself.

Shipped alert rules live in
[`infra/prometheus/alerts.yml`](../../infra/prometheus/alerts.yml):
`ArXMCPBackupStale` (freshness), plus `ArXMCPBackupFailed`,
`ArXMCPBackupPartial`, and `ArXMCPBackupStatusUnknown` on the status
metric itself. Triage from the state cell:

```promql
# No clean backup in 48h (freshness — catches a silently dead cron too)
(time() - arxmcp_backup_last_success_timestamp_seconds) > 172800

# Most recent run produced no snapshot
arxmcp_backup_status{state="failed"} == 1

# Snapshot exists but the run was not clean — read backup_status /
# forget_status in the sentinel to see which phase degraded
arxmcp_backup_status{state="partial"} == 1

# The wrapper wrote a token the server does not recognise: the
# producer and consumer vocabularies have drifted apart again
arxmcp_backup_status{state="unknown"} == 1
```

Refresh happens on every `/metrics` scrape via
`server.health.refresh_sentinel_metrics(ops_dir)` — no scrape
race with the cron's atomic write to `backup-status.json`
(rename is atomic on POSIX).

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
