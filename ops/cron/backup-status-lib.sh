# shellcheck shell=bash
# arXMCP backup-status vocabulary — the SHELL half of the shared contract.
#
# The Python half is server/backup_status.py. The two are bound by
# tests/test_backup_status_vocabulary.py, which asserts set-equality of the
# tokens declared here against server.backup_status.EMITTABLE_STATES, and
# drives arxmcp_backup_final_status below through
# server.health.refresh_sentinel_metrics to prove no emitted value can
# classify as "unknown".
#
# Closes chris-dare-dev/arXMCP#202. This file did not exist before: the
# wrapper emitted "success" and composites of the form
# backup_<phase>_forget_<phase>, and NO consumer state matched any of them,
# so every run — including a perfect one — landed in
# arxmcp_backup_status{state="unknown"} while {state="ok"} stayed 0.0.
#
# Sourced by ops/cron/arxmcp-backup.sh. Pure declarations plus two pure
# functions; no side effects at source time, so it is safe to source from a
# test harness — which is how the tests drive the REAL decision logic rather
# than a Python re-implementation of it.

# The tokens the producer may write to the sentinel "status" field. The
# consumer additionally owns "unknown" as its catch-all for anything outside
# this set; the producer never writes it.
ARXMCP_BACKUP_STATE_OK="ok"
ARXMCP_BACKUP_STATE_PARTIAL="partial"
ARXMCP_BACKUP_STATE_FAILED="failed"
ARXMCP_BACKUP_STATE_RUNNING="running"

# arxmcp_backup_final_status <backup_phase_status> <forget_phase_status>
#
# Collapse the two phase outcomes into the single token the sentinel "status"
# field carries. Both arguments use the vocabulary above.
#
# Only "ok" advances arxmcp_backup_last_success_timestamp_seconds
# (server.backup_status.FRESHNESS_ADVANCING_STATES), so anything short of a
# fully clean run MUST NOT report ok — that is the #203 half of the defense.
# The per-phase detail stays readable in the sentinel backup_status /
# forget_status fields; it is deliberately NOT folded back into this token,
# because a composite string is what broke the enum in the first place.
arxmcp_backup_final_status() {
    local backup_phase="$1"
    local forget_phase="$2"

    if [ "${backup_phase}" = "${ARXMCP_BACKUP_STATE_FAILED}" ]; then
        # No usable snapshot; the forget outcome is irrelevant.
        printf '%s\n' "${ARXMCP_BACKUP_STATE_FAILED}"
    elif [ "${backup_phase}" = "${ARXMCP_BACKUP_STATE_OK}" ] &&
        [ "${forget_phase}" = "${ARXMCP_BACKUP_STATE_OK}" ]; then
        printf '%s\n' "${ARXMCP_BACKUP_STATE_OK}"
    else
        # Snapshot exists but the run was not clean: restic exit 3, a
        # degraded notebooks.db WAL checkpoint, or a failed retention pass.
        printf '%s\n' "${ARXMCP_BACKUP_STATE_PARTIAL}"
    fi
}

# arxmcp_backup_prior_last_success <status_file> <ok_token>
#
# Echo the timestamp of the last SUCCESSFUL run as recorded by the sentinel
# already on disk, or nothing when there has never been one. Never fails:
# a missing, unreadable, truncated, or malformed sentinel yields the empty
# string, because the caller runs under `set -euo pipefail` and a backup
# must not abort over its own bookkeeping.
#
# This is the producer half of the #202/#203 FOLLOW-UP. The sentinel records
# only the most recent run, and the consumer's freshness gauge is process
# state rehydrated from it at each /metrics scrape. So a server restart while
# the latest run was failed/partial left `arxmcp_backup_last_success_
# timestamp_seconds` at 0.0 with nothing able to advance it: ArXMCPBackupStale
# fired immediately, with an age computed from epoch 0. Fail-loud in the right
# direction, but the number was meaningless. Carrying the value forward on
# EVERY sentinel the wrapper writes — including the failed/partial/running
# ones — makes the last-good time durable across both a restart and a run of
# failures.
#
# Resolution order:
#   1. `last_success_at` from the prior sentinel — already carried forward.
#   2. `finished_at`, but ONLY when the prior `status` was ok. This is the
#      upgrade path: sentinels written before this field existed have no
#      `last_success_at`, and #203 is exactly why `finished_at` cannot be
#      trusted on its own (the wrapper stamps it on every run that reaches
#      the end, success or not).
#
# The value is shape-validated against the wrapper's own `date -u
# +%Y-%m-%dT%H:%M:%SZ` output before being echoed. It is interpolated into a
# JSON string literal by the caller, so anything else — a stray quote from a
# hand-edited sentinel, a non-string, a null — must not reach the heredoc.
arxmcp_backup_prior_last_success() {
    local status_file="${1:-}"
    local ok_token="${2:-}"

    [ -n "${status_file}" ] || return 0
    [ -f "${status_file}" ] || return 0

    python3 - "${status_file}" "${ok_token}" <<'ARXMCP_PY' || return 0
import json
import re
import sys

_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _stamp(value):
    if isinstance(value, str) and _STAMP.fullmatch(value):
        return value
    return None


try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        prior = json.load(fh)
except Exception:
    prior = None

carried = None
if isinstance(prior, dict):
    carried = _stamp(prior.get("last_success_at"))
    if carried is None and prior.get("status") == sys.argv[2]:
        carried = _stamp(prior.get("finished_at"))

print(carried or "")
ARXMCP_PY
}
