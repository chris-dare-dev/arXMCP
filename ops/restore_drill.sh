#!/usr/bin/env bash
# E11_S05 restore drill — operator-invoked once before the 200K
# cutover. Restores the most-recent restic snapshot to a
# scratch directory, runs the lightweight smoke check, and
# writes the pass sentinel that cutover.sh consumes (C4).
#
# Usage:
#   ops/restore_drill.sh
#
# On success, writes var/arxmcp/ops/restore-drill-passed.flag
# and cleans up /tmp/arxmcp-restore-drill/. On failure, leaves
# the restore directory in place for forensics.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [ -n "${ARXMCP_UV:-}" ]; then
    UV_BIN="${ARXMCP_UV}"
elif UV_BIN="$(command -v uv 2>/dev/null)"; then
    :
else
    echo "ERROR: uv not found on PATH." >&2
    exit 1
fi

if ! command -v restic >/dev/null 2>&1; then
    echo "ERROR: restic not found on PATH." >&2
    exit 1
fi

ENV_FILE="${REPO_ROOT}/ops/restic-env.sh"
if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: ${ENV_FILE} missing. Copy from " \
         "ops/restic-env.sh.template and fill in." >&2
    exit 1
fi
# shellcheck disable=SC1090
source "${ENV_FILE}"

RESTORE_PATH="${ARXMCP_RESTORE_DRILL_PATH:-/tmp/arxmcp-restore-drill}"
FLAG_PATH="${REPO_ROOT}/var/arxmcp/ops/restore-drill-passed.flag"

mkdir -p "$(dirname "${FLAG_PATH}")"

# notebook-ops-hardening-m1: verify pack-file integrity before the
# restore. --read-data-subset=5% randomly reads 5% of pack data and
# confirms it is unmodified since write (a structural-only `restic check`
# does not read pack bytes). With `set -euo pipefail` a non-zero exit
# here aborts the drill — a failed integrity check IS a drill failure.
echo "Verifying repository integrity (restic check --read-data-subset=5%)..."
restic check --read-data-subset=5%

# Pick the most-recent snapshot via restic's --json output and
# Python (no jq dep).
SNAPSHOT_ID="$(restic snapshots --json | python3 -c \
    'import json,sys; print(json.loads(sys.stdin.read())[-1]["short_id"])')"

if [ -z "${SNAPSHOT_ID}" ]; then
    echo "ERROR: no snapshots in repository ${RESTIC_REPOSITORY}" >&2
    exit 1
fi

echo "Restoring snapshot ${SNAPSHOT_ID} to ${RESTORE_PATH}..."
rm -rf "${RESTORE_PATH}"
mkdir -p "${RESTORE_PATH}"
restic restore "${SNAPSHOT_ID}" --target "${RESTORE_PATH}"

echo "Running smoke check..."
"${UV_BIN}" run python -m ops.restore_drill_check \
    --restore-path "${RESTORE_PATH}" \
    --snapshot-id "${SNAPSHOT_ID}" \
    --flag-path "${FLAG_PATH}"

echo "Drill complete. Cleaning up ${RESTORE_PATH}."
rm -rf "${RESTORE_PATH}"
echo "Wrote ${FLAG_PATH}"
