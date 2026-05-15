#!/usr/bin/env bash
# E11_S04 drift-watchdog cron wrapper.
#
# Runs `ops/watchdog_eval.py` against the staging LanceDB to
# detect retrieval-quality regression. Schedule this AFTER the
# nightly delta loop (`ops/cron/arxmcp-delta.sh`) — the watchdog
# refuses to run if re-embed is still in progress.
#
# Operator install (Linux/systemd or macOS/cron):
#
#   # crontab — fires at 02:30 (30 min after the 02:00 delta).
#   30 2 * * *  /path/to/arxmcp/ops/cron/arxmcp-watchdog.sh
#
# `flock -n` guarantees only one watchdog runs at a time.
#
# See docs/ops/drift-watchdog.md for the operator workflow,
# threshold tuning, and quarantine procedure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Resolve `uv` from PATH; ARXMCP_UV overrides. Closes E11_S02 IS2
# pattern — the prior wrapper hardcoded a workstation-specific
# path which broke on any other host.
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

# Closes E11_S04 IS1: `flock(1)` is part of `util-linux` and is NOT
# present on macOS by default. Without this guard, the cron wrapper
# fails silently to cron with exit 127. Detect early with an
# actionable error.
if ! command -v flock >/dev/null 2>&1; then
    echo "ERROR: flock not found on PATH. flock(1) is part of " \
         "util-linux:" >&2
    echo "  macOS: brew install flock  (or: brew install util-linux)" >&2
    echo "  Linux: pre-installed via util-linux (apt/dnf/pacman)" >&2
    exit 1
fi

LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.watchdog.lock"
mkdir -p "$(dirname "${LOCK_PATH}")"

exec flock -n "${LOCK_PATH}" \
    "${UV_BIN}" run python -m ops.watchdog_eval "$@"
