"""Tests for the pre-backup WAL checkpoint helper (notebook-ops-hardening-m1).

The helper folds notebooks.db's WAL into the main file before a restic
backup so the file-level copy is self-consistent. The load-bearing
invariant (F1 from the m1 adversary critique): a checkpoint BLOCKED by a
concurrent reader must report a degraded status (``busy``), NOT be silently
treated as a clean capture — because committed frames then remain only in
the un-backed-up ``-wal`` and a main-file-only copy is malformed-on-restore.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ops.checkpoint_notebooks_db import CLEAN_STATUSES, checkpoint


def _wal_db_with_frames(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    finally:
        conn.close()


class TestCheckpointHappyPath:
    def test_ok_truncates_wal(self, tmp_path):
        db = tmp_path / "notebooks.db"
        _wal_db_with_frames(db)
        # Leave fresh frames in the WAL via a second connection.
        c = sqlite3.connect(str(db))
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("INSERT INTO t VALUES (2)")
        c.commit()
        c.close()
        status = checkpoint(db)
        assert status == "ok"
        assert status in CLEAN_STATUSES
        wal = Path(str(db) + "-wal")
        assert (not wal.exists()) or wal.stat().st_size == 0
        # Data intact in the main file.
        c2 = sqlite3.connect(str(db))
        rows = c2.execute("SELECT x FROM t ORDER BY x").fetchall()
        c2.close()
        assert rows == [(1,), (2,)]

    def test_absent_db(self, tmp_path):
        assert checkpoint(tmp_path / "nope.db") == "absent"

    def test_non_wal_db_is_clean(self, tmp_path):
        db = tmp_path / "plain.db"
        c = sqlite3.connect(str(db))
        c.execute("PRAGMA journal_mode=DELETE")  # not WAL
        c.execute("CREATE TABLE t (x)")
        c.commit()
        c.close()
        # A non-WAL DB has no -wal sidecar, so the main file is already
        # self-consistent: the checkpoint is a harmless no-op and returns a
        # CLEAN status ("ok" — busy=0 — or "no-wal" on some builds).
        assert checkpoint(db) in CLEAN_STATUSES


class TestCheckpointBusyIsDegraded:
    """F1: a reader holding an open txn must force a degraded status, and
    the main-file-only copy taken in that state must be unreadable —
    proving why the wrapper must NOT treat ``busy`` as clean."""

    def test_busy_reader_blocks_truncate(self, tmp_path):
        db = tmp_path / "notebooks.db"
        _wal_db_with_frames(db)
        reader = sqlite3.connect(str(db))
        writer = sqlite3.connect(str(db))
        try:
            # Reader holds an open read transaction against a snapshot.
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM t").fetchall()
            # Writer commits a NEW frame into the WAL.
            writer.execute("INSERT INTO t VALUES (2)")
            writer.commit()
            # Checkpoint cannot truncate while the reader holds its txn.
            status = checkpoint(db, attempts=2, delay_s=0.0)
            assert status == "busy"
            assert status not in CLEAN_STATUSES
            # The committed frame remains only in the -wal.
            wal = Path(str(db) + "-wal")
            assert wal.exists() and wal.stat().st_size > 0
        finally:
            reader.close()
            writer.close()

    def test_main_file_only_copy_after_busy_is_not_a_faithful_capture(
        self, tmp_path
    ):
        """The danger F1 names: copying ONLY the main file (what the manifest
        does on the clean path) after a BUSY checkpoint is never a faithful
        capture. Depending on how many frames were partially folded before
        the reader blocked the checkpoint, the main-only copy is either
        MALFORMED (partial fold → raises) or STALE (zero fold → opens but is
        missing the last committed row). Either way it is NOT the live state
        — which is exactly why the wrapper backs up the sidecars + marks the
        backup partial on a degraded checkpoint."""
        import shutil

        db = tmp_path / "notebooks.db"
        _wal_db_with_frames(db)
        reader = sqlite3.connect(str(db))
        writer = sqlite3.connect(str(db))
        try:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM t").fetchall()
            writer.execute("INSERT INTO t VALUES (2)")
            writer.commit()
            assert checkpoint(db, attempts=1, delay_s=0.0) == "busy"
            # Copy MAIN FILE ONLY (no -wal/-shm), as a naive backup would.
            main_only = tmp_path / "main_only.db"
            shutil.copyfile(str(db), str(main_only))
        finally:
            reader.close()
            writer.close()
        # The live DB has rows {1, 2}. The main-only copy must FAIL to be a
        # faithful capture: either malformed-on-open, or stale (missing 2).
        try:
            c = sqlite3.connect(str(main_only))
            try:
                rows = c.execute("SELECT x FROM t ORDER BY x").fetchall()
            finally:
                c.close()
        except sqlite3.DatabaseError:
            return  # malformed — not a faithful capture (acceptable outcome)
        assert rows != [(1,), (2,)], (
            "main-only copy unexpectedly matched the live DB after a busy "
            "checkpoint — the danger this guard pins did not reproduce"
        )


class TestCheckpointLockedReturnsStatus:
    """F2: a sqlite error must map to a defined status, not propagate —
    the helper's "exit 0 on a reachable DB" contract."""

    def test_directory_in_place_of_db_returns_locked(self, tmp_path):
        # A directory at the db path exists() == True but sqlite cannot
        # open it -> OperationalError -> mapped to "locked", not raised.
        fake = tmp_path / "notebooks.db"
        fake.mkdir()
        status = checkpoint(fake, attempts=2, delay_s=0.0)
        assert status == "locked"
        assert status not in CLEAN_STATUSES
