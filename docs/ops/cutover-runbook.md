---
project: arxmcp
type: doc
tags:
- project/arxmcp
- type/doc
- authorship/agent-generated
authorship: agent-generated
---

# 200K cutover runbook (E11_S05)

**Use when:** the staging LanceDB at
`var/arxmcp/index/lancedb-staging/` is fully ingested (E11_S01),
optionally re-embedded (E11_S03), and the drift watchdog
(E11_S04) has not raised a quarantine alert. This runbook walks
the operator through promoting staging to active.

> **Activation = atomic directory swap, NOT marker rewrite.**
> The staging and active LanceDB datasets live at different
> filesystem paths; their internal version integers are dataset-
> scoped, not interchangeable. The cutover does two `os.rename`
> calls on the same filesystem (POSIX-atomic):
> 1. `lancedb/` → `lancedb-prev/` (rollback snapshot).
> 2. `lancedb-staging/` → `lancedb/` (promote).
> No marker rewrite — the staging `corpus-version.json` is
> correct as-is, and after rename it sits where the server
> expects it.

> **Rollback = inverse swap + restart, < 30 seconds.**
> See "Rollback" below.

---

## Activation criteria — all 4 must pass

`ops/cutover.py` checks these in order. Any failure refuses the
cutover with an actionable message.

### C1 — Seed-corpus nDCG@5 ≥ 0.80 (Tier-1 exit gate)

**What:** the currently-active corpus has previously passed the
E07_S04 retrieval-quality gate. Concretely:
`var/arxmcp/ops/eval/aggregate-<active_version>.json` exists
and reports `ndcg5_mean >= 0.80`.

**How to satisfy:** run `make eval` against the active seed
corpus. The aggregate file is written automatically.

### C2 — Watchdog on staging passes (no regression)

**What:** the most-recent E11_S04 watchdog report at the
staging corpus version reports `ndcg5_mean >= 0.80` AND
`alert_triggered=false`, AND `var/arxmcp/ops/eval-quarantine.flag`
is absent.

**How to satisfy:** run `make watchdog` after staging is ready
(re-embed complete, if applicable). Investigate any quarantine
flag before retrying; clear it via
`make watchdog ARGS="--clear-quarantine"`.

### C3 — Ingest complete (E11_S01/S03)

**What:** if `var/arxmcp/ops/re-embed-state.json` exists, its
`status` must be `complete` or `complete_with_failures`. Absent
file is acceptable (the bulk-ingest path that never went
through re-embed). Plus a `count_rows() > 0` integrity probe on
the staging LanceDB.

**How to satisfy:** finish any in-progress re-embed (E11_S03).
Verify `make ingest` produced rows; the integrity probe runs
automatically.

### C4 — Restore drill passed

**What:** `var/arxmcp/ops/restore-drill-passed.flag` is present
and reports `smoke_check=passed`.

**How to satisfy:** run `ops/restore_drill.sh` once before
cutover. The drill restores the most-recent restic snapshot to
`/tmp/arxmcp-restore-drill/`, runs a lightweight LanceDB +
Kùzu integrity check, writes the flag, and cleans up. See
[backup-restore.md](backup-restore.md) for the full restore
procedure.

---

## Prerequisites

* **Python ≥3.11** with the project venv (`make bootstrap`).
* **`uv` on PATH** (the cutover wrapper resolves via
  `command -v uv`).
* **The active LanceDB exists** at `var/arxmcp/index/lancedb/`
  with a valid `corpus-version.json`.
* **The staging LanceDB exists** at
  `var/arxmcp/index/lancedb-staging/` with a valid
  `corpus-version.json`.
* **No `lancedb-prev/` from a prior failed cutover.** The
  cutover refuses if `var/arxmcp/index/lancedb-prev/` already
  exists. Inspect, then move or remove it before retrying.
* **All 4 activation criteria** have been satisfied per the
  procedures above.

---

## Procedure

### Step 1 — Dry-run the criteria check

```bash
make cutover ARGS="--dry-run"
```

Prints `PASS`/`FAIL` per criterion. Resolve any FAIL before
proceeding.

### Step 2 — Stop the MCP server

```bash
# systemd:
sudo systemctl stop arxmcp-server.service

# or whatever stop mechanism you use in dev:
# pkill -f "python -m server.main"
```

### Step 3 — Run the cutover

```bash
make cutover
```

The script:
1. Re-checks all 4 criteria (defense-in-depth).
2. Performs the atomic directory swap.
3. Asks the operator to restart the MCP server.
4. Polls `/readyz` for 60s (AC4).
5. Runs the post-activation watchdog (AC5).

### Step 4 — Start the MCP server

While `make cutover` polls `/readyz`, start the server in
another terminal:

```bash
# systemd:
sudo systemctl start arxmcp-server.service

# or dev:
make up
```

### Step 5 — Confirm post-activation health

`make cutover` runs the post-activation watchdog against the
now-active LanceDB and exits 0 if `nDCG@5 ≥ 0.80`. If it exits
non-zero, inspect the watchdog's JSON report at
`var/arxmcp/ops/eval-reports/`.

---

## Rollback (< 30 seconds)

If problems are detected after activation (agent quality
regression, MCP server instability, unexpected latency),
rollback is two atomic renames + a server restart:

```bash
# Step 1: stop the server.
sudo systemctl stop arxmcp-server.service

# Step 2: inverse swap.
make cutover ARGS="--rollback"
# Internally:
#   os.rename("lancedb/", "lancedb-failed-cutover-<ts>/")
#   os.rename("lancedb-prev/", "lancedb/")

# Step 3: restart the server.
sudo systemctl start arxmcp-server.service
```

**Total wall-clock < 30 seconds.** Two renames on a local
filesystem are microseconds; the rest is BGE-M3 warm-up (~5-30s
on warm HF cache).

The failed-cutover state is preserved at
`var/arxmcp/index/lancedb-failed-cutover-<timestamp>/` for
forensic inspection.

---

## Failure modes

### `lancedb-prev/` already exists

A prior cutover failed and left the rollback snapshot in place.
The cutover refuses with an actionable error. Investigate
(maybe rename to `lancedb-prev-investigation-<date>/`) before
retrying.

### `/readyz` does not return 200 within 60s

BGE-M3 cold load can take ~30s on first invocation. If the
server is still warming, increase the timeout:
`make cutover ARGS="--readyz-timeout 120"`. If the server is
crashing, inspect logs and roll back.

### Post-activation watchdog reports regression

This shouldn't happen if Criterion 2 passed (the watchdog ran
against staging before the swap). If it does, roll back and
investigate. The watchdog's report at
`var/arxmcp/ops/eval-reports/` documents the regression.

### Mid-cutover crash

If `cutover.py` dies between the two `os.rename` calls, the
active path is briefly missing. The window is microseconds in
practice. If you find an inconsistent state on the next run,
manually rename the directories to restore one of:
- `lancedb-staging/` is intact → re-run `make cutover`.
- `lancedb-prev/` is intact → rename to `lancedb/` (rollback).

---

## State files this milestone reads

| Path | Source | Read for |
|---|---|---|
| `var/arxmcp/index/lancedb/corpus-version.json` | E04_S03 + E11_S01 | C1 (seed version) |
| `var/arxmcp/index/lancedb-staging/corpus-version.json` | E11_S01-S03 | C2 (staging version), integrity probe |
| `var/arxmcp/ops/eval/aggregate-<N>.json` | E05/E07_S04 | C1 (seed nDCG@5) |
| `var/arxmcp/ops/eval-reports/corpus_v<N>-*.json` | E11_S04 | C2 (staging watchdog) |
| `var/arxmcp/ops/eval-quarantine.flag` | E11_S04 | C2 (watchdog refuse) |
| `var/arxmcp/ops/re-embed-state.json` | E11_S03 | C3 (re-embed complete) |
| `var/arxmcp/ops/restore-drill-passed.flag` | E11_S05 | C4 (drill passed) |

---

## See also

* [ops/cutover.py](../../ops/cutover.py) — the activation
  module.
* [ops/cutover.sh](../../ops/cutover.sh) — bash wrapper.
* [docs/ops/backup-restore.md](backup-restore.md) — restic
  configuration + restore drill.
* [docs/ops/drift-watchdog.md](drift-watchdog.md) — the
  watchdog that gates C2.
* [.claude/notes/05-storage-and-indexing.md](../../.claude/notes/05-storage-and-indexing.md) — LanceDB MVCC contract.
* [.claude/notes/06-mcp-server-design.md](../../.claude/notes/06-mcp-server-design.md) — server index stability (lines 346-354).
* [.claude/TIER-GATES.md](../../.claude/TIER-GATES.md) — Tier-5
  cutover gate definition.
* [.claude/notes/milestones/E11_S05/research-synthesis.md](../../.claude/notes/milestones/E11_S05/research-synthesis.md) — D1-D15 rationale.
