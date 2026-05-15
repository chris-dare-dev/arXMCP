#!/usr/bin/env bash
# Daily LaTeXML drift detector (E10_S04).
#
# Renders 5 fixture .tex files through latexmlc, extracts MathML
# via BeautifulSoup, and diffs against the checked-in baselines at
# tests/fixtures/latexml-drift/. On drift, writes
# var/arxmcp/ops/drift-detected.flag, logs ERROR to stderr, and
# exits non-zero so the cron mailer / systemd-timer reports the
# failure.
#
# Usage:
#   ops/cron/latexml-drift-check.sh           # check; exit 0 = ok, 1 = drift
#   ops/cron/latexml-drift-check.sh --update-fixtures
#
# Crontab entry:
#   30 2 * * *  /path/to/arxmcp/ops/cron/latexml-drift-check.sh
#
# Requirements:
#   - `latexmlc` on PATH (`brew install latexml` / `apt install latexml`)
#   - uv + the project's virtualenv at <repo-root>/.venv
#
# See docs/ops/latexml-drift-runbook.md for the recovery procedure
# when drift is detected.

set -euo pipefail

# Resolve repo root from this script's location so the cron can
# invoke it via an absolute symlink without needing a working
# directory pin.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Prefer the project's pinned uv-managed venv. Operators can
# override by exporting ARXMCP_UV before invoking this script.
UV_BIN="${ARXMCP_UV:-/Users/chris.dare/Library/Python/3.9/bin/uv}"

exec "${UV_BIN}" run python -m ops.drift_check "$@"
