"""Shared backup-status vocabulary — the ONE definition of the status
tokens the backup wrapper writes into ``var/arxmcp/ops/backup-status.json``
and the ``/metrics`` + ``/status`` readers consume.

Closes ``chris-dare-dev/arXMCP#202``. Before this module the producer
(``ops/cron/arxmcp-backup.sh``) emitted ``"success"`` plus composites
like ``"backup_partial_forget_failed"``, while the consumer
(``server/health.py``) declared ``("ok", "failed", "running",
"unknown")``. The two sets were **disjoint**: no value the producer
could emit was a member of the consumer's enum, so a perfect backup
routed to ``arxmcp_backup_status{state="unknown"}`` and the ``ok`` cell
was pinned at 0.0 forever. The F4 guard in
:func:`server.health.refresh_sentinel_metrics` — installed against
exactly this "emit-mismatched-string wrapper bug" — was correct and had
nothing to fire against but every single run.

The shell half of the vocabulary lives in
``ops/cron/backup-status-lib.sh``. The two halves are bound by
``tests/test_backup_status_vocabulary.py``, which asserts set-equality
and drives the real shell decision function through
:func:`server.health.refresh_sentinel_metrics`. There is deliberately
**no runtime coupling** — no file parse, no import from ``ops/``: the
nightly cron path must not gain a new failure mode just to share four
strings, and the local test suite is this project's authority
(CLAUDE.md §4.1).

Keep this module stdlib-only and import-light — ``server/health.py``
imports it at module scope.
"""

from __future__ import annotations

#: A fully clean run: the snapshot was taken AND retention was applied.
#: The only state that advances the last-success freshness clock.
BACKUP_STATE_OK: str = "ok"

#: A snapshot exists but the run was not fully clean — ``restic backup``
#: exited 3 (some files unreadable), the ``notebooks.db`` WAL checkpoint
#: came back degraded, or ``restic forget`` failed. Recoverable data was
#: captured, so this is NOT ``failed``; it is also NOT a success, so it
#: does NOT advance the freshness clock (see :data:`FRESHNESS_ADVANCING_STATES`).
BACKUP_STATE_PARTIAL: str = "partial"

#: No usable snapshot came out of this run.
BACKUP_STATE_FAILED: str = "failed"

#: A run is in flight — the wrapper writes this in the two-phase sentinel
#: after the snapshot lands but before ``restic forget`` returns.
BACKUP_STATE_RUNNING: str = "running"

#: Consumer-owned catch-all. The producer MUST NOT emit this; it is what
#: an unrecognised, corrupted, or future token classifies to so that a
#: producer/consumer drift regression lights a cell instead of silently
#: zeroing every state. ``ArXMCPBackupStatusUnknown`` alerts on it.
BACKUP_STATE_UNKNOWN: str = "unknown"

#: Every token the producer is allowed to write to ``status``.
EMITTABLE_STATES: frozenset[str] = frozenset(
    {
        BACKUP_STATE_OK,
        BACKUP_STATE_PARTIAL,
        BACKUP_STATE_FAILED,
        BACKUP_STATE_RUNNING,
    }
)

#: Every ``arxmcp_backup_status{state=...}`` label cell, in a stable
#: order. Superset of :data:`EMITTABLE_STATES` by exactly
#: :data:`BACKUP_STATE_UNKNOWN`. Used to zero the inactive cells so
#: exactly one is 1.0 at a time.
BACKUP_STATES: tuple[str, ...] = (
    BACKUP_STATE_OK,
    BACKUP_STATE_PARTIAL,
    BACKUP_STATE_FAILED,
    BACKUP_STATE_RUNNING,
    BACKUP_STATE_UNKNOWN,
)

#: States that may advance ``arxmcp_backup_last_success_timestamp_seconds``.
#: Deliberately just ``ok`` — the metric is named *last success*, and a
#: ``partial`` run is explicitly not one. Closes ``chris-dare-dev/arXMCP#203``:
#: the reader previously set the gauge from ``finished_at`` BEFORE looking at
#: the status at all, so a failed run advanced the freshness clock and
#: suppressed ``ArXMCPBackupStale`` — the backup alerting surface reported
#: healthy precisely while backups were broken.
FRESHNESS_ADVANCING_STATES: frozenset[str] = frozenset({BACKUP_STATE_OK})


def classify_backup_state(raw: object) -> str:
    """Map a raw ``status`` value read off ``backup-status.json`` onto a
    known label cell.

    Anything that is not a recognised emittable token — a missing key, a
    non-string, a corrupted value, or a token from a future wrapper —
    classifies as :data:`BACKUP_STATE_UNKNOWN` rather than being dropped
    on the floor. Callers are expected to log a WARNING on that outcome.
    """
    if isinstance(raw, str) and raw in EMITTABLE_STATES:
        return raw
    return BACKUP_STATE_UNKNOWN


def advances_freshness(state: str) -> bool:
    """Whether ``state`` may move the last-success freshness clock.

    Pass the output of :func:`classify_backup_state`, never a raw payload
    value — an unrecognised token must never be mistaken for a success.
    """
    return state in FRESHNESS_ADVANCING_STATES


__all__ = [
    "BACKUP_STATES",
    "BACKUP_STATE_FAILED",
    "BACKUP_STATE_OK",
    "BACKUP_STATE_PARTIAL",
    "BACKUP_STATE_RUNNING",
    "BACKUP_STATE_UNKNOWN",
    "EMITTABLE_STATES",
    "FRESHNESS_ADVANCING_STATES",
    "advances_freshness",
    "classify_backup_state",
]
