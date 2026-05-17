#!/usr/bin/env bash
# Weekly parser-failures review (E14_S04).
#
# Aggregates var/arxmcp/ops/parser-failures/*.{log,jsonl} into an
# ISO-week markdown report at
# var/arxmcp/ops/reports/parser-failures-<YYYY>-W<NN>.md.
#
# Usage:
#   ops/cron/arxmcp-parser-failures-weekly.sh      # default: last week
#   ops/cron/arxmcp-parser-failures-weekly.sh --week 2026-W19
#
# Crontab entry (Sun 06:00 UTC):
#   0 6 * * 0  /path/to/arxmcp/ops/cron/arxmcp-parser-failures-weekly.sh
#
# systemd unit: see
# ops/systemd/arxmcp-parser-failures-weekly.{service,timer}.
#
# See docs/ops/parser-failure-review.md for the human triage
# workflow + must-act thresholds.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

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

if ! command -v flock >/dev/null 2>&1; then
    echo "ERROR: flock not found on PATH. flock(1) is part of " \
         "util-linux:" >&2
    echo "  macOS: brew install flock  (or: brew install util-linux)" >&2
    echo "  Linux: pre-installed via util-linux (apt/dnf/pacman)" >&2
    exit 1
fi

LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.parser-failures-weekly.lock"
mkdir -p "$(dirname "${LOCK_PATH}")"

exec flock -n "${LOCK_PATH}" \
    "${UV_BIN}" run python -m tools.parser_failures_report "$@"
