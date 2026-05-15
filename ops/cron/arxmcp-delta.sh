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

LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.delta.lock"
mkdir -p "$(dirname "${LOCK_PATH}")"

# `flock -n` exits 1 immediately if the lock is held — the
# correct reentrancy signal for cron + systemd. journalctl shows
# the lock contention on Linux; cron mailer surfaces it elsewhere.
exec flock -n "${LOCK_PATH}" \
    "${UV_BIN}" run python -m ingest.oai_delta "$@"
