"""TRUNCATE-checkpoint notebooks.db WAL before a restic backup.

notebook-ops-hardening-m1.

``notebooks.db`` runs in WAL mode (``journal_mode=WAL`` +
``synchronous=FULL`` + ``fullfsync=ON`` from notebook-ops-hardening-m2),
so at any instant three files exist on disk: ``notebooks.db``,
``notebooks.db-wal``, ``notebooks.db-shm``. A file-level restic snapshot
that captures only ``notebooks.db`` — or captures all three
non-atomically — can restore a database that is BEHIND the last committed
transaction, **or unreadable (malformed) on open** when committed frames
remain only in the ``-wal``.

Running ``PRAGMA wal_checkpoint(TRUNCATE)`` immediately before the backup
folds every committed WAL frame into the main database file and zeroes the
WAL, so ``notebooks.db`` is self-consistent on its own — the backup
manifest then needs only ``notebooks.db``.

But a TRUNCATE checkpoint can be BLOCKED by a concurrent reader holding an
open read transaction: it returns ``busy=1`` WITHOUT truncating the WAL,
leaving the latest committed frame only in the (un-backed-up) ``-wal``. A
main-file-only copy taken in that state is malformed-on-restore
(live-verified: ``database disk image is malformed``). So we RETRY a few
times, and the caller MUST treat a residual ``busy``/``locked`` as a
degraded capture (back up the sidecars too + mark the backup partial) —
NOT as a clean snapshot.

Safe to run while the server is live: WAL mode permits many readers plus a
single checkpointer, and this runs as a separate process opening its own
connection. The backup fires at 03:30 (idle window), so a busy checkpoint
is uncommon but real.

Exit code is always 0 on a reachable DB (status is reported on stdout);
diagnostics go to stderr; a usage error returns 64. The caller inspects
the printed status string.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

# PRAGMA wal_checkpoint returns (busy, log, checkpointed):
#   busy != 0  -> a concurrent reader blocked a full checkpoint; the WAL
#                 was NOT truncated and committed frames remain in -wal.
_BUSY_COLUMN = 0

_DEFAULT_ATTEMPTS = 3
_DEFAULT_DELAY_S = 2.0

# Statuses the CALLER may treat as a clean, self-consistent main file.
CLEAN_STATUSES = frozenset({"ok", "absent", "no-wal"})


def checkpoint(
    db_path: Path,
    *,
    attempts: int = _DEFAULT_ATTEMPTS,
    delay_s: float = _DEFAULT_DELAY_S,
) -> str:
    """TRUNCATE-checkpoint the WAL of ``db_path``, retrying on busy.

    Returns a status string:
      - ``"absent"``  — the DB file does not exist (fresh install); no-op.
      - ``"ok"``      — checkpoint completed; WAL folded + truncated.
      - ``"no-wal"``  — the pragma returned no row (not in WAL mode).
      - ``"busy"``    — a concurrent reader blocked a full checkpoint on
                        every attempt; the WAL still holds committed frames.
                        The caller MUST NOT treat this as a clean capture.
      - ``"locked"``  — a sqlite error (locked/permission/corrupt) on every
                        attempt; same degraded handling as ``busy``.

    Only ``CLEAN_STATUSES`` (ok/absent/no-wal) mean the main file alone is
    safe to back up. ``busy``/``locked`` are degraded.
    """
    if not db_path.exists():
        return "absent"
    last = "busy"
    for attempt in range(1, attempts + 1):
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            # A locked/permission/corrupt DB raises rather than returning a
            # busy row. Map to a defined status so the documented "exit 0 on
            # a reachable DB" contract holds and the caller can react.
            last = "locked"
            print(
                f"checkpoint_notebooks_db: attempt {attempt}/{attempts} "
                f"sqlite error: {exc}",
                file=sys.stderr,
            )
        else:
            if row is None:
                return "no-wal"
            if row[_BUSY_COLUMN] == 0:
                return "ok"
            last = "busy"
            print(
                f"checkpoint_notebooks_db: attempt {attempt}/{attempts} "
                f"busy (wal_checkpoint returned {row}); a reader is holding "
                f"an open transaction",
                file=sys.stderr,
            )
        if attempt < attempts:
            time.sleep(delay_s)
    return last


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: checkpoint_notebooks_db.py <path-to-notebooks.db>",
            file=sys.stderr,
        )
        return 64
    print(checkpoint(Path(argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
