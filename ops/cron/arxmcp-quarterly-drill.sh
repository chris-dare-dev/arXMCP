#!/usr/bin/env bash
# Quarterly restore-drill reminder wrapper (E14_S04).
#
# Runs daily; the underlying tools/quarterly_drill_reminder.sh
# short-circuits unless we're within 7 days of the next quarter
# mark. When in-range, writes a flag to
# var/arxmcp/ops/reminders/quarterly-drill-<YYYY>-Q<N>.flag.
#
# Usage:
#   ops/cron/arxmcp-quarterly-drill.sh
#   ops/cron/arxmcp-quarterly-drill.sh --dry-run
#
# Crontab entry (daily at 00:00 UTC):
#   0 0 * * *  /path/to/arxmcp/ops/cron/arxmcp-quarterly-drill.sh
#
# systemd unit: see ops/systemd/arxmcp-quarterly-drill.{service,timer}.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# flock not strictly required (the reminder is idempotent: it
# refuses to overwrite an existing flag) but kept for consistency
# with the other ops cron wrappers.
if ! command -v flock >/dev/null 2>&1; then
    echo "ERROR: flock not found on PATH. flock(1) is part of " \
         "util-linux:" >&2
    echo "  macOS: brew install flock  (or: brew install util-linux)" >&2
    echo "  Linux: pre-installed via util-linux (apt/dnf/pacman)" >&2
    exit 1
fi

LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.quarterly-drill.lock"
mkdir -p "$(dirname "${LOCK_PATH}")"

exec flock -n "${LOCK_PATH}" \
    "${REPO_ROOT}/tools/quarterly_drill_reminder.sh" "$@"
