#!/usr/bin/env bash
# E11_S05 nightly restic backup wrapper.
#
# Backs up the corpus (`var/arxmcp/index/lancedb/`,
# `var/arxmcp/index/kuzu/`, `var/arxmcp/corpus/chunks/`) to the
# repository configured in `ops/restic-env.sh`. Applies retention
# (7 daily / 4 weekly / 12 monthly) after the backup completes.
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

STATUS_FILE="'"${REPO_ROOT}"'/var/arxmcp/ops/backup-status.json"
TMP_STATUS="${STATUS_FILE}.tmp"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

BACKUP_PATHS=(
    "'"${REPO_ROOT}"'/var/arxmcp/index/lancedb"
    "'"${REPO_ROOT}"'/var/arxmcp/index/kuzu"
    "'"${REPO_ROOT}"'/var/arxmcp/corpus/chunks"
)

# Run the backup. Exclude transient artifacts.
#
# Closes infra-safety IS4: capture restic's exit code
# explicitly. restic exits 3 on PARTIAL success (some files
# unreadable, e.g. hot LanceDB compaction). Treat exit 3 as
# partial — sentinel records "status: partial" so the
# operator can distinguish it from total failure.
set +e
SNAPSHOT_JSON="$(restic backup \
    --exclude "*.lock" \
    --exclude "*.tmp" \
    --exclude "lancedb-staging-tmp" \
    --json \
    "${BACKUP_PATHS[@]}" \
    | tail -n 1)"
RESTIC_BACKUP_EXIT=$?
set -e
if [ "${RESTIC_BACKUP_EXIT}" -ne 0 ] && [ "${RESTIC_BACKUP_EXIT}" -ne 3 ]; then
    echo "ERROR: restic backup failed (exit ${RESTIC_BACKUP_EXIT})" >&2
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
BACKUP_STATUS="success"
if [ "${RESTIC_BACKUP_EXIT}" -eq 3 ]; then
    BACKUP_STATUS="partial"
fi
cat > "${TMP_STATUS}" <<EOF
{
  "paths_backed_up": [
    "'"${REPO_ROOT}"'/var/arxmcp/index/lancedb",
    "'"${REPO_ROOT}"'/var/arxmcp/index/kuzu",
    "'"${REPO_ROOT}"'/var/arxmcp/corpus/chunks"
  ],
  "repository": "${RESTIC_REPOSITORY}",
  "restic_backup_exit": ${RESTIC_BACKUP_EXIT},
  "snapshot_id": "${SNAPSHOT_ID}",
  "started_at": "${STARTED_AT}",
  "status": "backup_complete_forget_pending",
  "backup_status": "${BACKUP_STATUS}"
}
EOF
mv "${TMP_STATUS}" "${STATUS_FILE}"

# Apply retention policy AFTER the backup, not before. If
# forget fails, the partial sentinel above remains as the
# durable record of the backups success.
set +e
restic forget --prune \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 12
RESTIC_FORGET_EXIT=$?
set -e

# Closes infra-safety IS6: capture FINISHED_AT after the
# forget step so the sentinel reflects the actual end of
# the operation, not just the backup phase.
FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

FORGET_STATUS="success"
if [ "${RESTIC_FORGET_EXIT}" -ne 0 ]; then
    FORGET_STATUS="failed"
fi

# Overwrite with the final status. backup_status is preserved
# so a partial backup remains visible even after forget OK.
FINAL_STATUS="success"
if [ "${BACKUP_STATUS}" != "success" ] || [ "${FORGET_STATUS}" != "success" ]; then
    FINAL_STATUS="backup_${BACKUP_STATUS}_forget_${FORGET_STATUS}"
fi
cat > "${TMP_STATUS}" <<EOF
{
  "backup_status": "${BACKUP_STATUS}",
  "finished_at": "${FINISHED_AT}",
  "forget_status": "${FORGET_STATUS}",
  "paths_backed_up": [
    "'"${REPO_ROOT}"'/var/arxmcp/index/lancedb",
    "'"${REPO_ROOT}"'/var/arxmcp/index/kuzu",
    "'"${REPO_ROOT}"'/var/arxmcp/corpus/chunks"
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

if [ "${FINAL_STATUS}" = "success" ]; then
    echo "restic backup complete: snapshot=${SNAPSHOT_ID}"
else
    echo "restic backup partial: status=${FINAL_STATUS} snapshot=${SNAPSHOT_ID}" >&2
fi
'
