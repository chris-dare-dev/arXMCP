#!/usr/bin/env bash
# E11_S05 nightly restic backup wrapper.
#
# Backs up the corpus (`var/arxmcp/index/lancedb/`,
# `var/arxmcp/index/kuzu/`, `var/arxmcp/corpus/chunks/`) plus
# non-regenerable notebook data (`var/arxmcp/notebooks/` and the
# notebook-metadata DB `var/arxmcp/cache/notebooks.db`) to the
# repository configured in `ops/restic-env.sh`. Applies retention
# (7 daily / 4 weekly / 12 monthly) after the backup completes.
#
# notebook-ops-hardening-m1: the include-list is passed as a
# `--files-from-verbatim -` manifest (printf piped to restic stdin),
# and `notebooks.db` is WAL-checkpointed before the snapshot so the
# file-level copy is self-consistent without -wal/-shm sidecars.
#
# Schedule: nightly at 03:30 (90 min after the delta loop fires)
# via `ops/systemd/arxmcp-backup.{service,timer}` OR a crontab.
#
# See docs/ops/backup-restore.md for the operator workflow.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Resolve uv (no hardcoded paths — E11_S02 IS2 / E11_S04 lessons).
if [ -n "${ARXMCP_UV:-}" ]; then
    UV_BIN="${ARXMCP_UV}"
elif UV_BIN="$(command -v uv 2>/dev/null)"; then
    :
else
    echo "ERROR: uv not found on PATH. Install or set ARXMCP_UV." >&2
    exit 1
fi

# Resolve flock (E11_S04 IS1 — not on macOS by default).
if ! command -v flock >/dev/null 2>&1; then
    echo "ERROR: flock not found on PATH. flock(1) is part of " \
         "util-linux:" >&2
    echo "  macOS: brew install flock" >&2
    echo "  Linux: pre-installed via util-linux" >&2
    exit 1
fi

# Resolve restic.
if ! command -v restic >/dev/null 2>&1; then
    echo "ERROR: restic not found on PATH." >&2
    echo "  macOS: brew install restic" >&2
    echo "  Linux: apt install restic / dnf install restic" >&2
    exit 1
fi

LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.backup.lock"
mkdir -p "$(dirname "${LOCK_PATH}")"

# Acquire the lock BEFORE sourcing the env file. Sourcing
# performs an optional connectivity check; two concurrent
# checkers could race on the repository if we sourced first.
exec flock -n "${LOCK_PATH}" bash -euo pipefail -c '
ENV_FILE="'"${REPO_ROOT}"'/ops/restic-env.sh"
if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: ${ENV_FILE} missing. Copy from " \
         "ops/restic-env.sh.template and fill in." >&2
    exit 1
fi
# Closes adversary F5 / infra-safety IS3: always run the
# connectivity probe in production. The previous opt-in via
# ARXMCP_RESTIC_CHECK was unreachable from the wrapper.
export ARXMCP_RESTIC_CHECK=1
source "${ENV_FILE}"

# Closes chris-dare-dev/arXMCP#202: the sentinel status vocabulary is
# SHARED with the consumer, not re-invented here. This lib is the shell
# half of the contract; server/backup_status.py is the Python half, and
# tests/test_backup_status_vocabulary.py binds them. Previously this
# wrapper emitted "success" and backup_<x>_forget_<y> composites that
# matched NO consumer state, so every run landed in
# arxmcp_backup_status{state="unknown"}.
STATUS_LIB="'"${REPO_ROOT}"'/ops/cron/backup-status-lib.sh"
if [ ! -f "${STATUS_LIB}" ]; then
    echo "ERROR: ${STATUS_LIB} missing. It is the shared status " \
         "vocabulary; refusing to emit an unvalidated status." >&2
    exit 1
fi
source "${STATUS_LIB}"

STATUS_FILE="'"${REPO_ROOT}"'/var/arxmcp/ops/backup-status.json"
TMP_STATUS="${STATUS_FILE}.tmp"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Closes the #202/#203 follow-up documented in docs/ops/backup-restore.md.
# The sentinel records only the MOST RECENT run, and the consumers freshness
# gauge is process state rehydrated from it at each /metrics scrape — so a
# server restart while the latest run was failed/partial started the gauge at
# 0.0 with nothing able to advance it, and ArXMCPBackupStale fired with an age
# measured from epoch 0. Read the prior sentinel BEFORE overwriting it and
# carry the last-good timestamp into every sentinel this run writes, including
# the failed/partial/running ones. See arxmcp_backup_prior_last_success in the
# shared lib for the resolution order and why finished_at alone is not enough.
#
# Emitted as a JSON literal so "never yet succeeded" is null, not "" — a
# consumer must be able to tell "no successful backup on record" apart from a
# malformed field. The read is best-effort: `|| true` keeps a bookkeeping
# hiccup from aborting the backup itself under set -euo pipefail.
PRIOR_LAST_SUCCESS="$(arxmcp_backup_prior_last_success \
    "${STATUS_FILE}" "${ARXMCP_BACKUP_STATE_OK}" || true)"
if [ -n "${PRIOR_LAST_SUCCESS}" ]; then
    PRIOR_LAST_SUCCESS_JSON="\"${PRIOR_LAST_SUCCESS}\""
else
    PRIOR_LAST_SUCCESS_JSON="null"
fi

# notebook-ops-hardening-m1: include non-regenerable user data.
#   - notebooks/ (whole subtree): uploaded PDFs (pdf-deferred/, pdfs/),
#     papers.txt, queries.json, the per-notebook LanceDB embedding store,
#     and lancedb-prev-* rollback targets. Included despite LanceDB being
#     nominally regenerable because re-embedding (MinerU + LaTeXML +
#     BGE-M3) is expensive and the uploaded PDFs are the ONLY source copy.
#     The per-notebook query cache (cache/retrieval.db) IS regenerable and
#     is excluded below.
#   - cache/notebooks.db: notebook metadata. An EXCEPTION to the general
#     "var/arxmcp/cache/ is not backed up" policy: it is user-authored
#     state, not a regenerable cache (retrieval.db stays excluded). See
#     .claude/notes/08-security-observability-ops.md.
BACKUP_PATHS=(
    "'"${REPO_ROOT}"'/var/arxmcp/index/lancedb"
    "'"${REPO_ROOT}"'/var/arxmcp/index/kuzu"
    "'"${REPO_ROOT}"'/var/arxmcp/corpus/chunks"
    "'"${REPO_ROOT}"'/var/arxmcp/notebooks"
    "'"${REPO_ROOT}"'/var/arxmcp/cache/notebooks.db"
)

# notebook-ops-hardening-m1 (CRITICAL): TRUNCATE-checkpoint the
# notebooks.db WAL before the snapshot so the file-level copy is
# self-consistent without -wal/-shm sidecars. The helper retries on a
# busy checkpoint. Only a CLEAN status (ok/absent/no-wal) means the main
# file alone is safe to back up. A residual busy/locked status (a reader
# held an open transaction through all retries) means committed frames
# remain ONLY in the un-backed-up -wal: a main-file-only copy taken then
# is stale OR malformed-on-restore (live-verified: "database disk image
# is malformed"). So on a degraded status we (a) ALSO back up the
# -wal/-shm sidecars for this run so the captured set can recover, and
# (b) force backup_status=partial so the sentinel flags it and `forget`
# retains the prior good snapshot. stderr is NOT discarded — the helper
# diagnostics must reach the cron/journal log.
NOTEBOOKS_DB="'"${REPO_ROOT}"'/var/arxmcp/cache/notebooks.db"
CHECKPOINT_STATUS="$(python3 "'"${REPO_ROOT}"'/ops/checkpoint_notebooks_db.py" "${NOTEBOOKS_DB}" || echo error)"
CHECKPOINT_DEGRADED=0
case "${CHECKPOINT_STATUS}" in
    ok|absent|no-wal) ;;
    *)
        CHECKPOINT_DEGRADED=1
        echo "WARN: notebooks.db WAL checkpoint status=${CHECKPOINT_STATUS}; committed frames may remain only in the un-backed-up -wal, so the captured notebooks.db alone may be stale OR corrupt-on-restore. Backing up the -wal/-shm sidecars too and marking this backup partial." >&2
        for SIDECAR in "${NOTEBOOKS_DB}-wal" "${NOTEBOOKS_DB}-shm"; do
            if [ -f "${SIDECAR}" ]; then
                BACKUP_PATHS+=("${SIDECAR}")
            fi
        done
        ;;
esac

# Run the backup. The include-list is a --files-from-verbatim -
# manifest (one literal path per line on stdin via printf) per the
# notebook-ops-hardening-m1 AC. --files-from-verbatim is include-only;
# exclusions stay as separate --exclude flags. */cache/retrieval.db
# drops the regenerable per-notebook query cache.
#
# Closes infra-safety IS4: capture the restic exit code
# explicitly. restic exits 3 on PARTIAL success (some files
# unreadable, e.g. hot LanceDB compaction). Treat exit 3 as
# partial — sentinel records "status: partial" so the
# operator can distinguish it from total failure.
set +e
SNAPSHOT_JSON="$(printf "%s\n" "${BACKUP_PATHS[@]}" | restic backup \
    --files-from-verbatim - \
    --exclude "*.lock" \
    --exclude "*.tmp" \
    --exclude "lancedb-staging-tmp" \
    --exclude "*/cache/retrieval.db" \
    --json \
    | tail -n 1)"
RESTIC_BACKUP_EXIT=$?
set -e
if [ "${RESTIC_BACKUP_EXIT}" -ne 0 ] && [ "${RESTIC_BACKUP_EXIT}" -ne 3 ]; then
    echo "ERROR: restic backup failed (exit ${RESTIC_BACKUP_EXIT})" >&2
    # Closes chris-dare-dev/arXMCP#202 (second half): emit a FAILED
    # sentinel before exiting. Previously this path exited without
    # writing anything, so the sentinel kept yesterdays values and
    # arxmcp_backup_status{state="failed"} could never become 1.0 —
    # the state was unreachable, which made any alert on it dead.
    # Nothing was captured, so paths_backed_up is empty and there is
    # no snapshot id.
    FAILED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    cat > "${TMP_STATUS}" <<EOF
{
  "backup_status": "${ARXMCP_BACKUP_STATE_FAILED}",
  "finished_at": "${FAILED_AT}",
  "forget_status": null,
  "last_success_at": ${PRIOR_LAST_SUCCESS_JSON},
  "paths_backed_up": [],
  "repository": "${RESTIC_REPOSITORY}",
  "restic_backup_exit": ${RESTIC_BACKUP_EXIT},
  "snapshot_id": null,
  "started_at": "${STARTED_AT}",
  "status": "${ARXMCP_BACKUP_STATE_FAILED}"
}
EOF
    mv "${TMP_STATUS}" "${STATUS_FILE}"
    exit "${RESTIC_BACKUP_EXIT}"
fi

# Extract the snapshot ID via python (avoids a `jq` dep).
SNAPSHOT_ID="$(echo "${SNAPSHOT_JSON}" | python3 -c \
    "import json,sys; print(json.loads(sys.stdin.read())[\"snapshot_id\"][:8])")"

# Closes adversary F4 / infra-safety IS2: write a PARTIAL
# sentinel before invoking forget. Without this, a forget
# failure aborts the script (set -euo pipefail) and the
# operator sees yesterdays sentinel — no record of todays
# successful backup. The two-phase write surfaces partial
# success.
BACKUP_STATUS="${ARXMCP_BACKUP_STATE_OK}"
if [ "${RESTIC_BACKUP_EXIT}" -eq 3 ]; then
    BACKUP_STATUS="${ARXMCP_BACKUP_STATE_PARTIAL}"
fi
# notebook-ops-hardening-m1 F1: a degraded WAL checkpoint means notebooks.db
# was not cleanly captured (sidecars were added, but force partial so the
# operator sees it and forget keeps the prior good snapshot).
if [ "${CHECKPOINT_DEGRADED}" -eq 1 ]; then
    BACKUP_STATUS="${ARXMCP_BACKUP_STATE_PARTIAL}"
fi
cat > "${TMP_STATUS}" <<EOF
{
  "last_success_at": ${PRIOR_LAST_SUCCESS_JSON},
  "paths_backed_up": [
    "'"${REPO_ROOT}"'/var/arxmcp/index/lancedb",
    "'"${REPO_ROOT}"'/var/arxmcp/index/kuzu",
    "'"${REPO_ROOT}"'/var/arxmcp/corpus/chunks",
    "'"${REPO_ROOT}"'/var/arxmcp/notebooks",
    "'"${REPO_ROOT}"'/var/arxmcp/cache/notebooks.db"
  ],
  "repository": "${RESTIC_REPOSITORY}",
  "restic_backup_exit": ${RESTIC_BACKUP_EXIT},
  "snapshot_id": "${SNAPSHOT_ID}",
  "started_at": "${STARTED_AT}",
  "status": "${ARXMCP_BACKUP_STATE_RUNNING}",
  "backup_status": "${BACKUP_STATUS}"
}
EOF
mv "${TMP_STATUS}" "${STATUS_FILE}"

# Apply retention policy AFTER the backup, not before. If
# forget fails, the partial sentinel above remains as the
# durable record of the backups success.
set +e
# notebook-ops-hardening-m1: --group-by host (not the default
# host,paths). When the include-list changes, the default groups
# pre-change and post-change snapshots into separate paths-groups, each
# getting its own 7/4/12 window. --group-by host keeps a single unified
# retention window as the manifest evolves.
restic forget --prune \
    --group-by host \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 12
RESTIC_FORGET_EXIT=$?
set -e

# Closes infra-safety IS6: capture FINISHED_AT after the
# forget step so the sentinel reflects the actual end of
# the operation, not just the backup phase.
FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

FORGET_STATUS="${ARXMCP_BACKUP_STATE_OK}"
if [ "${RESTIC_FORGET_EXIT}" -ne 0 ]; then
    FORGET_STATUS="${ARXMCP_BACKUP_STATE_FAILED}"
fi

# Overwrite with the final status. backup_status and forget_status are
# preserved as separate fields so a partial backup, and which phase caused
# it, remain visible to the operator.
#
# Closes chris-dare-dev/arXMCP#202: the single status token comes from the
# SHARED vocabulary via the shared decision function. It used to be built
# by string interpolation here as backup_<x>_forget_<y>, which no consumer
# state could ever match. The per-phase detail must stay in the per-phase
# fields, never folded back into this token.
FINAL_STATUS="$(arxmcp_backup_final_status "${BACKUP_STATUS}" "${FORGET_STATUS}")"

# The ONLY place the carried last-success timestamp advances: a fully clean
# run, which is the same gate as server.backup_status.FRESHNESS_ADVANCING_
# STATES. Anything short of ok re-emits the prior value unchanged, so the age
# of the last GOOD backup keeps growing and ArXMCPBackupStale can still fire —
# it just now fires with a meaningful age instead of one measured from epoch 0.
if [ "${FINAL_STATUS}" = "${ARXMCP_BACKUP_STATE_OK}" ]; then
    LAST_SUCCESS_JSON="\"${FINISHED_AT}\""
else
    LAST_SUCCESS_JSON="${PRIOR_LAST_SUCCESS_JSON}"
fi

cat > "${TMP_STATUS}" <<EOF
{
  "backup_status": "${BACKUP_STATUS}",
  "finished_at": "${FINISHED_AT}",
  "forget_status": "${FORGET_STATUS}",
  "last_success_at": ${LAST_SUCCESS_JSON},
  "paths_backed_up": [
    "'"${REPO_ROOT}"'/var/arxmcp/index/lancedb",
    "'"${REPO_ROOT}"'/var/arxmcp/index/kuzu",
    "'"${REPO_ROOT}"'/var/arxmcp/corpus/chunks",
    "'"${REPO_ROOT}"'/var/arxmcp/notebooks",
    "'"${REPO_ROOT}"'/var/arxmcp/cache/notebooks.db"
  ],
  "repository": "${RESTIC_REPOSITORY}",
  "restic_backup_exit": ${RESTIC_BACKUP_EXIT},
  "restic_forget_exit": ${RESTIC_FORGET_EXIT},
  "snapshot_id": "${SNAPSHOT_ID}",
  "started_at": "${STARTED_AT}",
  "status": "${FINAL_STATUS}"
}
EOF
mv "${TMP_STATUS}" "${STATUS_FILE}"

if [ "${FINAL_STATUS}" = "${ARXMCP_BACKUP_STATE_OK}" ]; then
    echo "restic backup complete: snapshot=${SNAPSHOT_ID}"
else
    echo "restic backup ${FINAL_STATUS}: backup=${BACKUP_STATUS}" \
         "forget=${FORGET_STATUS} snapshot=${SNAPSHOT_ID}" >&2
fi
'
