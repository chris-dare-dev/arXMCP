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
SNAPSHOT_JSON="$(restic backup \
    --exclude "*.lock" \
    --exclude "*.tmp" \
    --exclude "lancedb-staging-tmp" \
    --json \
    "${BACKUP_PATHS[@]}" \
    | tail -n 1)"

# Extract the snapshot ID via python (avoids a `jq` dep).
SNAPSHOT_ID="$(echo "${SNAPSHOT_JSON}" | python3 -c \
    "import json,sys; print(json.loads(sys.stdin.read())[\"snapshot_id\"][:8])")"

FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Apply retention policy AFTER the backup, not before.
restic forget --prune \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 12

# Write the sentinel atomically.
cat > "${TMP_STATUS}" <<EOF
{
  "finished_at": "${FINISHED_AT}",
  "paths_backed_up": [
    "'"${REPO_ROOT}"'/var/arxmcp/index/lancedb",
    "'"${REPO_ROOT}"'/var/arxmcp/index/kuzu",
    "'"${REPO_ROOT}"'/var/arxmcp/corpus/chunks"
  ],
  "repository": "${RESTIC_REPOSITORY}",
  "snapshot_id": "${SNAPSHOT_ID}",
  "started_at": "${STARTED_AT}",
  "status": "success"
}
EOF
mv "${TMP_STATUS}" "${STATUS_FILE}"

echo "restic backup complete: snapshot=${SNAPSHOT_ID}"
'
