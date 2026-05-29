"""TRUNCATE-checkpoint notebooks.db WAL before a restic backup.

notebook-ops-hardening-m1.

``notebooks.db`` runs in WAL mode (``journal_mode=WAL`` +
``synchronous=FULL`` + ``fullfsync=ON`` from notebook-ops-hardening-m2),
so at any instant three files exist on disk: ``notebooks.db``,
``notebooks.db-wal``, ``notebooks.db-shm``. A file-level restic snapshot
that captures only ``notebooks.db`` — or captures all three
non-atomically — can restore a database that is BEHIND the last committed
transaction (silent staleness, no error).

Running ``PRAGMA wal_checkpoint(TRUNCATE)`` immediately before the backup
folds every committed WAL frame into the main database file and zeroes the
WAL, so ``notebooks.db`` is self-consistent on its own — the backup
manifest then needs only ``notebooks.db``, not the ``-wal``/``-shm``
sidecars.

Safe to run while the server is live: WAL mode permits many readers plus a
single checkpointer, and this runs as a separate process opening its own
connection. The backup fires at 03:30 (idle window), so a partial/busy
checkpoint is unlikely; when it does happen we WARN and proceed rather than
fail the backup (a slightly-behind notebooks.db is degraded, not corrupt).

Exit code is always 0 on a reachable DB (status is reported on stdout); a
usage error returns 64. The caller inspects the printed status string.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# PRAGMA wal_checkpoint returns (busy, log, checkpointed):
#   busy != 0  -> another connection held a lock; checkpoint incomplete.
_BUSY_COLUMN = 0


def checkpoint(db_path: Path) -> str:
    """TRUNCATE-checkpoint the WAL of ``db_path``.

    Returns a status string:
      - ``"absent"``  — the DB file does not exist (fresh install); no-op.
      - ``"ok"``      — checkpoint completed; WAL folded + truncated.
      - ``"busy"``    — another connection blocked a full checkpoint; the
                        backup may capture a slightly-stale DB.
      - ``"no-wal"``  — the pragma returned no row (not in WAL mode).
    """
    if not db_path.exists():
        return "absent"
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        conn.close()
    if row is None:
        return "no-wal"
    if row[_BUSY_COLUMN] != 0:
        return "busy"
    return "ok"


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
