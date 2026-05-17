#!/usr/bin/env bash
# Quarterly restore-drill reminder (E14_S04).
#
# Cron schedule: runs daily at 00:00 UTC. The script short-circuits
# unless the operator is within 7 days of the next quarter mark
# (2026-04-01, 2026-07-01, 2026-10-01, 2027-01-01, ...). When in-
# range, writes a reminder flag to
# var/arxmcp/ops/reminders/quarterly-drill-<YYYY>-Q<N>.flag with
# the runbook reference + the exact `ops/restore_drill.sh`
# invocation.
#
# Usage:
#   tools/quarterly_drill_reminder.sh
#   tools/quarterly_drill_reminder.sh --dry-run
#
# --dry-run enables `set -x` early and skips the file write so the
# acceptance criterion test path is deterministic.
#
# Why a daily cron + script short-circuit (and NOT a monthly
# OnCalendar=*-01,04,07,10-* pattern):
#   * The monthly pattern fires on the 1st but our reminder needs
#     a 7-day lookahead — we want the operator to see the flag a
#     week BEFORE the quarter mark, not on the day-of.
#   * Daily fire + Python-based date math is robust to leap years,
#     timezone changes, and DST without depending on `date`
#     behaviour differences between BSD (macOS) and GNU (Linux).

set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
    set -x
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Compute days-to-next-quarter via stdlib Python (portable across
# macOS BSD `date` and GNU `date`). Returns the tuple
# (days_until, year, quarter) — quarter ∈ {1,2,3,4}.
#
# ``datetime.timezone.utc`` is used instead of ``datetime.UTC``
# (3.11+) so the script works under the macOS system python3
# (3.9) when an operator runs it outside the `uv run` cron
# wrapper for debugging.
read -r DAYS_UNTIL NEXT_YEAR NEXT_QUARTER <<<"$(python3 - <<'PY'
import datetime as _dt

now = _dt.datetime.now(_dt.timezone.utc).date()
year = now.year
marks = [
    _dt.date(year, 1, 1),
    _dt.date(year, 4, 1),
    _dt.date(year, 7, 1),
    _dt.date(year, 10, 1),
    _dt.date(year + 1, 1, 1),  # for late-Q4 lookahead
]
next_mark = min(m for m in marks if m > now)
days_until = (next_mark - now).days
qmap = {1: 1, 4: 2, 7: 3, 10: 4}
quarter = qmap[next_mark.month]
print(f"{days_until} {next_mark.year} {quarter}")
PY
)"

# Short-circuit unless we're within the 7-day lookahead window.
if [ "${DAYS_UNTIL}" -gt 7 ] || [ "${DAYS_UNTIL}" -lt 0 ]; then
    if [ "${DRY_RUN}" -eq 0 ]; then
        # Quiet on the cron-mailer path; the reminder is opt-in,
        # not an alert. Single INFO log to stderr is the discipline
        # used by ops/cron/arxmcp-delta.sh under the same condition.
        echo "INFO: ${DAYS_UNTIL} days until next quarter (${NEXT_YEAR}-Q${NEXT_QUARTER}); no reminder needed yet." >&2
    fi
    exit 0
fi

# In-range. Write the reminder flag. Idempotent: if it already
# exists, don't overwrite (preserves the original write-time
# stamp + the operator's any-additions).
REMINDER_DIR="${REPO_ROOT}/var/arxmcp/ops/reminders"
REMINDER_PATH="${REMINDER_DIR}/quarterly-drill-${NEXT_YEAR}-Q${NEXT_QUARTER}.flag"

if [ "${DRY_RUN}" -eq 1 ]; then
    echo "DRY-RUN: would write reminder to ${REMINDER_PATH}"
    echo "DRY-RUN: T-${DAYS_UNTIL} days until ${NEXT_YEAR}-Q${NEXT_QUARTER}"
    exit 0
fi

mkdir -p "${REMINDER_DIR}"
if [ -f "${REMINDER_PATH}" ]; then
    echo "INFO: reminder already present at ${REMINDER_PATH}" >&2
    exit 0
fi

cat > "${REMINDER_PATH}" <<EOF
arXMCP restore-drill reminder — ${NEXT_YEAR}-Q${NEXT_QUARTER}
============================================================
Due by: $(python3 -c "from datetime import date; q = ${NEXT_QUARTER}; y = ${NEXT_YEAR}; print(date(y, [None, 1, 4, 7, 10][q], 1).isoformat())")
T-${DAYS_UNTIL} days remaining.

Runbook: docs/ops/backup-restore.md §Restore drill

Procedure:
  cd ${REPO_ROOT}
  ops/restore_drill.sh

Success criteria (also written to a separate flag):
  var/arxmcp/ops/restore-drill-passed.flag (consumed by
  ops/cutover.py + tools/cutover.py to confirm DR readiness
  before a corpus_version cutover).

This reminder is generated daily by
tools/quarterly_drill_reminder.sh; the cron entry lives at
ops/cron/arxmcp-quarterly-drill.sh. The reminder file is NOT
auto-deleted after the drill — clean up manually with
``rm var/arxmcp/ops/reminders/quarterly-drill-*.flag``.
EOF

echo "INFO: wrote reminder to ${REMINDER_PATH}" >&2
