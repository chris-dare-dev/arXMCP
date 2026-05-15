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

exec "${UV_BIN}" run python -m ops.cutover "$@"
