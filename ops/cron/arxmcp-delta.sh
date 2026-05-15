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

# Prefer the project's pinned uv-managed venv. Operators can
# override by exporting ARXMCP_UV before invoking this script.
UV_BIN="${ARXMCP_UV:-/Users/chris.dare/Library/Python/3.9/bin/uv}"

LOCK_PATH="${REPO_ROOT}/var/arxmcp/ops/.delta.lock"
mkdir -p "$(dirname "${LOCK_PATH}")"

# `flock -n` exits 1 immediately if the lock is held — the
# correct reentrancy signal for cron + systemd. journalctl shows
# the lock contention on Linux; cron mailer surfaces it elsewhere.
exec flock -n "${LOCK_PATH}" \
    "${UV_BIN}" run python -m ingest.oai_delta "$@"
