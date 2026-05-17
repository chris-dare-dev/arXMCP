#!/usr/bin/env bash
# Nightly OAI-PMH delta loop (E11_S02).
#
# Harvests the previous day's new/updated papers from arXiv's
# OAI-PMH endpoint and feeds them into ingest_one_paper (chunker +
# embedder + staging LanceDB write).
#
# Usage:
#   ops/cron/arxmcp-delta.sh                 # nightly default
#   ops/cron/arxmcp-delta.sh --from=2026-05-01 --until=2026-05-14
#   ops/cron/arxmcp-delta.sh --dry-run
#
# Crontab entry (macOS or Linux fallback):
#   0 2 * * *  /path/to/arxmcp/ops/cron/arxmcp-delta.sh
#
# systemd unit (Linux primary): see ops/systemd/arxmcp-delta.{service,timer}.
#
# Reentrancy: `flock -n` acquires an exclusive lock on
# var/arxmcp/ops/.delta.lock. If a previous run is still active,
# this script exits 1 immediately. systemd records this as a
# failed unit; cron mailer surfaces the same.
#
# See docs/ops/delta-loop.md for the operator workflow + the
# 90-minute budget alert semantics.

set -euo pipefail

# Resolve repo root from this script's location so the cron can
# invoke it via an absolute symlink without needing a working
# directory pin.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Resolve `uv` from the operator's PATH; explicit ARXMCP_UV
# override wins. Closes IS2 from the E11_S02 critique — the prior
# fallback was a single-user macOS path that broke on every other
# machine.
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

# Closes E11_S04 IS1 (pre-existing gap in this wrapper): `flock(1)`
# is part of `util-linux` and is NOT present on macOS by default.
# Without this guard, the cron wrapper fails silently to cron with
# exit 127. Detect early with an actionable error.
if ! command -v flock >/dev/null 2>&1; then
    echo "ERROR: flock not found on PATH. flock(1) is part of " \
         "util-linux:" >&2
    echo "  macOS: brew install flock  (or: brew install util-linux)" >&2
    echo "  Linux: pre-installed via util-linux (apt/dnf/pacman)" >&2
    exit 1
fi

# E14_S05 D5 + F2 rectification — early-exit when the
# ingest-paused sentinel is present. Failure mode 7 (Disk full)
# writes this sentinel via the server's scrape-time hook;
# operators can also write it manually
# (`python -m tools.ingest_sentinel write --reason=maintenance`).
# The cron skips the run and exits 0 so cron-mailer doesn't spam
# the operator with errors during a known pause.
#
# F2 (E14_S05 adversary): resolve the sentinel path with the SAME
# precedence as ``tools.ingest_sentinel._resolve_sentinel_path``
# — ``ARXMCP_DATA_DIR`` env var wins, fallback to the repo-root
# default. Previously the cron hardcoded ``${REPO_ROOT}/var/arxmcp``
# while the server's refresh hook used ``config.data_dir``
# (which honors ARXMCP_DATA_DIR), so a production deployment with
# ``ARXMCP_DATA_DIR=/var/lib/arxmcp`` silently broke the cron-side
# check.
DATA_DIR="${ARXMCP_DATA_DIR:-${REPO_ROOT}/var/arxmcp}"
PAUSE_FLAG="${DATA_DIR}/ops/ingest-paused"
if [ -e "${PAUSE_FLAG}" ]; then
    # IS2 (E14_S05 infra-safety): the python3 fallback chain
    # below is a soft-fail (cron exits 0 with reason=unknown if
    # python3 is missing). Cron environments on minimal Linux
    # distros may lack /usr/bin/python3; if you see "unknown"
    # reasons in the cron-mailer output, install python3.
    if command -v python3 >/dev/null 2>&1; then
        REASON="$(python3 -c 'import json, sys; \
print(json.load(open(sys.argv[1])).get("reason", "unknown"))' \
"${PAUSE_FLAG}" 2>/dev/null || echo "malformed_sentinel")"
    else
        REASON="unknown_python3_missing"
    fi
    echo "INFO: ingest paused (reason=${REASON}); skipping delta " \
         "run. Clear with: python -m tools.ingest_sentinel clear" >&2
    exit 0
fi

LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.delta.lock"
mkdir -p "$(dirname "${LOCK_PATH}")"

# `flock -n` exits 1 immediately if the lock is held — the
# correct reentrancy signal for cron + systemd. journalctl shows
# the lock contention on Linux; cron mailer surfaces it elsewhere.
exec flock -n "${LOCK_PATH}" \
    "${UV_BIN}" run python -m ingest.oai_delta "$@"
