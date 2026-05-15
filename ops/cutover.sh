#!/usr/bin/env bash
# E11_S05 cutover activation wrapper.
#
# Thin wrapper around `python -m ops.cutover`. The heavy logic
# (JSON parsing, atomic renames, HTTP polling, subprocess to
# watchdog) lives in Python where it can be unit-tested.
#
# Usage:
#   ops/cutover.sh                       # full cutover
#   ops/cutover.sh --dry-run             # check criteria, no swap
#   ops/cutover.sh --rollback            # inverse swap
#   ops/cutover.sh --skip-post-activation
#
# See docs/ops/cutover-runbook.md for the operator workflow,
# the 4 activation criteria, and the rollback procedure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Resolve `uv` from PATH; ARXMCP_UV overrides (E11_S02 IS2
# pattern — no hardcoded /Users/ path).
if [ -n "${ARXMCP_UV:-}" ]; then
    UV_BIN="${ARXMCP_UV}"
elif UV_BIN="$(command -v uv 2>/dev/null)"; then
    :
else
    echo "ERROR: uv not found on PATH. Install via your package " \
         "manager (brew install uv / apt install uv) or set " \
         "ARXMCP_UV=<absolute path to uv>." >&2
    exit 1
fi

# Closes infra-safety IS1: cutover is human-initiated, but two
# concurrent invocations (tmux split, retry typo, systemd
# accidental trigger) can interleave between the two os.rename
# calls in perform_directory_swap and leave the active path
# missing. flock -n closes the window.
if ! command -v flock >/dev/null 2>&1; then
    echo "ERROR: flock not found on PATH. flock(1) is part of " \
         "util-linux:" >&2
    echo "  macOS: brew install flock" >&2
    echo "  Linux: pre-installed via util-linux" >&2
    exit 1
fi

LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.cutover.lock"
mkdir -p "$(dirname "${LOCK_PATH}")"

exec flock -n "${LOCK_PATH}" \
    "${UV_BIN}" run python -m ops.cutover "$@"
