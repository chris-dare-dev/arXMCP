#!/usr/bin/env bash
# Daily ops metrics report (E14_S04).
#
# Scrapes the running MCP server's /metrics endpoint, renders a
# markdown report to var/arxmcp/ops/daily-reports/<YYYY-MM-DD>.md,
# and optionally emails it when MAIL_TO/MAIL_FROM/SMTP_HOST are set.
#
# Usage:
#   ops/cron/arxmcp-daily-report.sh                 # nightly default
#   ops/cron/arxmcp-daily-report.sh --dry-run --fixture <path>
#
# Crontab entry (macOS or Linux fallback):
#   0 5 * * *  /path/to/arxmcp/ops/cron/arxmcp-daily-report.sh
#
# systemd unit (Linux primary): see
# ops/systemd/arxmcp-daily-report.{service,timer}.
#
# Reentrancy: `flock -n` acquires an exclusive lock on
# var/arxmcp/ops/.daily-report.lock. If a previous run is still
# active, this script exits 1 immediately.
#
# See docs/ops/daily-ops-cadence.md for the full schedule + alert
# thresholds.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Resolve `uv` from PATH; explicit ARXMCP_UV wins.
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

# flock(1) preflight (macOS warning).
if ! command -v flock >/dev/null 2>&1; then
    echo "ERROR: flock not found on PATH. flock(1) is part of " \
         "util-linux:" >&2
    echo "  macOS: brew install flock  (or: brew install util-linux)" >&2
    echo "  Linux: pre-installed via util-linux (apt/dnf/pacman)" >&2
    exit 1
fi

LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.daily-report.lock"
mkdir -p "$(dirname "${LOCK_PATH}")"

exec flock -n "${LOCK_PATH}" \
    "${UV_BIN}" run python -m tools.daily_metrics_report "$@"
