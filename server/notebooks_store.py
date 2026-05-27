"""SQLite-backed persistence for the per-notebook UI surface.

Sibling to :mod:`server.cache_sqlite` — same async-over-sync pattern
(``asyncio.to_thread`` + ``asyncio.Lock`` + WAL mode). The DB file
lives at :data:`server.config.Config.notebooks_db_path` (default
``var/arxmcp/cache/notebooks.db`` — sibling to ``cache_db_path`` per
the m7 brief). Stored as a SEPARATE file from the Tier-1 cache so a
schema-version bump on either side does not trigger the OTHER's
DROP-AND-RECREATE migration (FM-6 from m7 synthesis).

Schema:

.. code-block:: sql

    CREATE TABLE notebooks (
        slug           TEXT PRIMARY KEY,
        display_name   TEXT NOT NULL DEFAULT '',
        lancedb_path   TEXT NOT NULL,
        created_at     TEXT NOT NULL  -- ISO-8601 UTC
    );

    CREATE TABLE notebook_papers (
        slug           TEXT NOT NULL,
        paper_id       TEXT NOT NULL,
        added_at       TEXT NOT NULL,
        PRIMARY KEY (slug, paper_id),
        FOREIGN KEY (slug) REFERENCES notebooks(slug) ON DELETE CASCADE
    );

``PRAGMA foreign_keys = ON`` is set per-connection so the cascading
delete fires on ``DELETE FROM notebooks WHERE slug=?`` (SQLite default
is OFF; FK enforcement is a per-connection setting, not a DB-file
setting). FM-7 closure.

The deletion contract for the REST surface is **metadata-only**: a
``DELETE FROM notebooks`` strips the metadata rows + cascades the
junction, but the on-disk LanceDB / BM25 / ar5iv assets under
``var/arxmcp/notebooks/<slug>/`` are NOT touched. Destructive on-disk
wipe is the explicit job of ``tools/notebook_purge.py <slug>``. This
mirrors the milestone brief's deletion semantics (resolved 2026-05-21).
"""

from __future__ import annotations

import asyncio
import html
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

#: NotebooksStore schema version. v0→v1 is the initial create
#: (DROP-AND-RECREATE; fires only on a fresh / empty DB). v1→v2
#: is the m9 ADDITIVE migration adding ``notebook_ingest_runs``
#: WITHOUT dropping existing tables — notebook metadata MUST
#: survive schema bumps (the original DROP-AND-RECREATE-on-bump
#: pattern from Tier1Store is appropriate for a cache where loss
#: is a miss, NOT correctness; for notebook metadata it would be
#: data loss). When adding a new version: append a new
#: ``if current_version < N:`` block in ``_open_sync`` using
#: ``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE`` and bump
#: SCHEMA_VERSION; do NOT drop existing tables.
SCHEMA_VERSION: int = 3


class NotebooksStore:
    """SQLite-backed notebook + paper junction persistence.

    Construct via :meth:`open` (async classmethod). All public methods
    are ``async`` and offload SQL I/O via :func:`asyncio.to_thread`,
    serialized through an internal ``asyncio.Lock`` so the underlying
    single-threaded ``sqlite3.Connection`` is never raced.
    """

    def __init__(
        self,
        db_path: Path,
        connection: sqlite3.Connection,
    ) -> None:
        self._db_path = db_path
        self._conn = connection
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    @classmethod
    async def open(cls, db_path: Path) -> NotebooksStore:
        """Open (or create) the SQLite file at ``db_path``.

        Applies WAL + ``PRAGMA foreign_keys = ON`` + the schema-version
        check. Idempotent — calling :meth:`open` against a current-
        version file is a no-op beyond opening the connection.
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)

        def _open_sync() -> sqlite3.Connection:
            conn = sqlite3.connect(
                str(db_path),
                isolation_level=None,
                check_same_thread=False,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            # FM-7: FK enforcement is per-connection in SQLite (default
            # OFF). MUST set before any DELETE on the notebooks table
            # for the cascade to fire.
            conn.execute("PRAGMA foreign_keys = ON")

            current_version = conn.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            if current_version < SCHEMA_VERSION:
                logger.info(
                    "NotebooksStore: schema version %d -> %d at %s",
                    current_version, SCHEMA_VERSION, db_path,
                )
            # v0 -> v1: initial create (notebooks + notebook_papers).
            # Destructive create — runs only on a fresh DB where the
            # tables don't yet exist; CREATE TABLE (without IF NOT
            # EXISTS) plus the preceding DROP IF EXISTS preserves
            # the original safety on empty DBs.
            if current_version < 1:
                conn.execute("DROP TABLE IF EXISTS notebook_papers")
                conn.execute("DROP TABLE IF EXISTS notebooks")
                conn.execute(
                    "CREATE TABLE notebooks ("
                    "  slug          TEXT PRIMARY KEY,"
                    "  display_name  TEXT NOT NULL DEFAULT '',"
                    "  lancedb_path  TEXT NOT NULL,"
                    "  created_at    TEXT NOT NULL"
                    ")"
                )
                conn.execute(
                    "CREATE TABLE notebook_papers ("
                    "  slug      TEXT NOT NULL,"
                    "  paper_id  TEXT NOT NULL,"
                    "  added_at  TEXT NOT NULL,"
                    "  PRIMARY KEY (slug, paper_id),"
                    "  FOREIGN KEY (slug) REFERENCES notebooks(slug) "
                    "    ON DELETE CASCADE"
                    ")"
                )
                conn.execute(
                    "CREATE INDEX idx_notebook_papers_slug "
                    "ON notebook_papers(slug)"
                )
                conn.execute("PRAGMA user_version = 1")
            # v1 -> v2: m9 ADDITIVE migration. notebook_ingest_runs
            # stores per-ingest-trigger run state. CREATE TABLE IF
            # NOT EXISTS (NOT a destructive recreate) preserves all
            # existing notebook + paper rows. m9 DEVIATION from the
            # original Tier1Store-style DROP-AND-RECREATE — that
            # pattern is acceptable for caches (miss, not data
            # loss) but NOT for notebook metadata.
            if current_version < 2:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS notebook_ingest_runs ("
                    "  id           INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "  slug         TEXT NOT NULL,"
                    "  status       TEXT NOT NULL,"
                    "  started_at   TEXT NOT NULL,"
                    "  finished_at  TEXT,"
                    "  exit_code    INTEGER,"
                    "  stderr_tail  TEXT,"
                    "  FOREIGN KEY (slug) REFERENCES notebooks(slug) "
                    "    ON DELETE CASCADE"
                    ")"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_runs_slug "
                    "ON notebook_ingest_runs(slug, id DESC)"
                )
                conn.execute("PRAGMA user_version = 2")
            # v2 -> v3: textbook-ingest-m3 ADDITIVE migration.
            # ``notebook_kind`` distinguishes arXiv-corpus notebooks
            # (the historical default) from textbook-corpus notebooks
            # that will carry MinerU-parsed chunks once e2 + e3 ship.
            # SQLite ``ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT
            # 'arxiv'`` backfills every existing row in O(1) (no
            # row-rewrite) and preserves the "no data loss on
            # migration" invariant the v1→v2 ADDITIVE pattern
            # established. The route layer's Pydantic
            # ``NotebookCreate.notebook_kind`` field enforces the
            # ``{arxiv, textbook}`` enum domain at the write path.
            if current_version < 3:
                conn.execute(
                    "ALTER TABLE notebooks ADD COLUMN notebook_kind "
                    "TEXT NOT NULL DEFAULT 'arxiv'"
                )
                conn.execute("PRAGMA user_version = 3")
            return conn

        conn = await asyncio.to_thread(_open_sync)
        return cls(db_path=db_path, connection=conn)

    async def close(self) -> None:
        """Close the SQLite connection. Safe to call multiple times."""
        async with self._lock:
            def _close_sync() -> None:
                try:
                    self._conn.close()
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "NotebooksStore.close: ignoring close error"
                    )
            await asyncio.to_thread(_close_sync)

    # ------------------------------------------------------------------
    # Notebooks
    # ------------------------------------------------------------------

    async def list_notebooks(self) -> list[dict[str, str]]:
        """Return all notebook rows ordered by ``created_at DESC``.

        textbook-ingest-m3 added ``notebook_kind`` to the row dict;
        existing notebook.db rows are backfilled to ``"arxiv"`` by the
        v2→v3 SQLite DEFAULT migration.
        """
        async with self._lock:
            def _query() -> list[dict[str, str]]:
                rows = self._conn.execute(
                    "SELECT slug, display_name, lancedb_path, "
                    "created_at, notebook_kind "
                    "FROM notebooks ORDER BY created_at DESC, slug ASC"
                ).fetchall()
                return [
                    {
                        "slug": r[0], "display_name": r[1],
                        "lancedb_path": r[2], "created_at": r[3],
                        "notebook_kind": r[4],
                    }
                    for r in rows
                ]
            return await asyncio.to_thread(_query)

    async def get_notebook(self, slug: str) -> dict[str, str] | None:
        """Return one notebook row by slug, or ``None`` if absent.

        textbook-ingest-m3: ``notebook_kind`` included in the dict.
        """
        async with self._lock:
            def _query() -> dict[str, str] | None:
                row = self._conn.execute(
                    "SELECT slug, display_name, lancedb_path, "
                    "created_at, notebook_kind "
                    "FROM notebooks WHERE slug = ?",
                    (slug,),
                ).fetchone()
                if row is None:
                    return None
                return {
                    "slug": row[0], "display_name": row[1],
                    "lancedb_path": row[2], "created_at": row[3],
                    "notebook_kind": row[4],
                }
            return await asyncio.to_thread(_query)

    async def create_notebook(
        self,
        slug: str,
        display_name: str,
        lancedb_path: str,
        created_at: str,
        notebook_kind: str = "arxiv",
    ) -> None:
        """Insert a notebook row. Raises :class:`sqlite3.IntegrityError`
        on duplicate slug — the REST handler catches and translates to
        HTTP 409 (FM-5).

        textbook-ingest-m3: ``notebook_kind`` default ``"arxiv"`` so
        existing callers that don't supply it keep arXiv-corpus
        semantics. The route layer's ``NotebookCreate`` Pydantic model
        enforces the ``{arxiv, textbook}`` enum domain before the call
        reaches this writer.
        """
        async with self._lock:
            def _insert() -> None:
                self._conn.execute(
                    "INSERT INTO notebooks "
                    "(slug, display_name, lancedb_path, created_at, "
                    " notebook_kind) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (slug, display_name, lancedb_path, created_at,
                     notebook_kind),
                )
            await asyncio.to_thread(_insert)

    async def delete_notebook(self, slug: str) -> bool:
        """Delete the metadata row (cascades to ``notebook_papers``).

        Returns ``True`` if a row was deleted, ``False`` if no such
        slug existed. Does NOT touch on-disk
        ``var/arxmcp/notebooks/<slug>/`` assets — that is the explicit
        job of ``tools/notebook_purge.py`` (m6).
        """
        async with self._lock:
            def _delete() -> bool:
                cur = self._conn.execute(
                    "DELETE FROM notebooks WHERE slug = ?", (slug,)
                )
                return cur.rowcount > 0
            return await asyncio.to_thread(_delete)

    # ------------------------------------------------------------------
    # Papers (junction table)
    # ------------------------------------------------------------------

    async def list_papers(self, slug: str) -> list[dict[str, str]]:
        """Return junction rows for ``slug`` ordered by ``added_at DESC``.

        Returns an empty list if the notebook has no papers OR does
        not exist — callers check ``get_notebook(slug)`` first if
        404-vs-empty distinction matters.
        """
        async with self._lock:
            def _query() -> list[dict[str, str]]:
                rows = self._conn.execute(
                    "SELECT paper_id, added_at FROM notebook_papers "
                    "WHERE slug = ? ORDER BY added_at DESC, paper_id ASC",
                    (slug,),
                ).fetchall()
                return [{"paper_id": r[0], "added_at": r[1]} for r in rows]
            return await asyncio.to_thread(_query)

    async def add_paper(
        self,
        slug: str,
        paper_id: str,
        added_at: str,
    ) -> None:
        """Insert a junction row. Raises :class:`sqlite3.IntegrityError`
        on duplicate (slug, paper_id) — handler catches → HTTP 409.
        Also raises if the parent notebook doesn't exist (FK violation).
        """
        async with self._lock:
            def _insert() -> None:
                self._conn.execute(
                    "INSERT INTO notebook_papers "
                    "(slug, paper_id, added_at) VALUES (?, ?, ?)",
                    (slug, paper_id, added_at),
                )
            await asyncio.to_thread(_insert)

    async def remove_paper(self, slug: str, paper_id: str) -> bool:
        """Delete a single junction row.

        Returns ``True`` if a row was deleted, ``False`` if absent.
        """
        async with self._lock:
            def _delete() -> bool:
                cur = self._conn.execute(
                    "DELETE FROM notebook_papers "
                    "WHERE slug = ? AND paper_id = ?",
                    (slug, paper_id),
                )
                return cur.rowcount > 0
            return await asyncio.to_thread(_delete)

    # ------------------------------------------------------------------
    # Ingest runs (proof-verify-handler-wiring-m9)
    # ------------------------------------------------------------------

    #: Terminal-state values for the ``status`` column.
    INGEST_STATUS_RUNNING: str = "running"
    INGEST_STATUS_SUCCESS: str = "success"
    INGEST_STATUS_FAILED: str = "failed"

    async def insert_ingest_run(
        self,
        slug: str,
        started_at: str,
    ) -> int:
        """Insert a new ``running`` ingest-run row for ``slug``.

        Returns the new ``run_id``. The row exists BEFORE the
        background task is spawned (FM-7 from m9 synthesis) so the
        first polling request after the trigger never 404s.
        """
        async with self._lock:
            def _insert() -> int:
                cur = self._conn.execute(
                    "INSERT INTO notebook_ingest_runs "
                    "(slug, status, started_at) VALUES (?, ?, ?)",
                    (slug, self.INGEST_STATUS_RUNNING, started_at),
                )
                return int(cur.lastrowid)
            return await asyncio.to_thread(_insert)

    async def update_ingest_run(
        self,
        run_id: int,
        *,
        status: str,
        finished_at: str,
        exit_code: int | None,
        stderr_tail: str | None,
    ) -> None:
        """Update a run row with terminal-state values.

        Called from the ingest task's done callback. ``status`` MUST
        be one of ``success`` / ``failed`` — never ``running``
        (the row is already in that state from :meth:`insert_ingest_run`).
        ``stderr_tail`` should be the redacted + HTML-escaped
        ``var/arxmcp/``-relative tail (m9 FM-3 + FM-4 closure).
        """
        async with self._lock:
            def _update() -> None:
                self._conn.execute(
                    "UPDATE notebook_ingest_runs SET "
                    "  status = ?, finished_at = ?, "
                    "  exit_code = ?, stderr_tail = ? "
                    "WHERE id = ?",
                    (status, finished_at, exit_code, stderr_tail, run_id),
                )
            await asyncio.to_thread(_update)

    async def get_latest_ingest_run(
        self,
        slug: str,
    ) -> dict[str, str | int | None] | None:
        """Return the most recent ingest-run row for ``slug``, or
        ``None`` if no run has ever been triggered."""
        async with self._lock:
            def _query() -> dict[str, str | int | None] | None:
                row = self._conn.execute(
                    "SELECT id, slug, status, started_at, "
                    "       finished_at, exit_code, stderr_tail "
                    "FROM notebook_ingest_runs WHERE slug = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (slug,),
                ).fetchone()
                if row is None:
                    return None
                return {
                    "id": row[0], "slug": row[1], "status": row[2],
                    "started_at": row[3], "finished_at": row[4],
                    "exit_code": row[5], "stderr_tail": row[6],
                }
            return await asyncio.to_thread(_query)

    async def has_running_ingest(self, slug: str) -> bool:
        """Cross-restart fallback for the 409 collision check.

        The in-memory ``IngestTaskTracker`` is the primary source
        of truth for live processes; this DB fallback catches the
        case where the daemon was restarted while a row was still
        ``running`` (the FM-5 startup-recovery should have cleared
        it, but defense-in-depth in case recovery hasn't run yet).
        """
        async with self._lock:
            def _check() -> bool:
                row = self._conn.execute(
                    "SELECT 1 FROM notebook_ingest_runs "
                    "WHERE slug = ? AND status = ? LIMIT 1",
                    (slug, self.INGEST_STATUS_RUNNING),
                ).fetchone()
                return row is not None
            return await asyncio.to_thread(_check)

    async def mark_orphaned_runs_failed(
        self,
        cutoff_iso: str,
        message: str,
    ) -> int:
        """Mark every ``running`` row whose ``started_at`` is older
        than ``cutoff_iso`` as ``failed`` with the given message.

        Called at lifespan startup (m9 FM-5 closure): if the daemon
        died mid-ingest the previous task's done-callback never
        fired and the row would stay ``running`` forever; mark it
        as failed before the new daemon accepts ingest triggers
        for the same slug.

        Returns the number of rows updated.

        m9 rect F3: ``message`` is HTML-escaped before storage. The
        ``stderr_tail`` column is interpolated raw into a ``<pre>``
        element by ``_ingest_status_fragment`` (the
        ``prepare_stderr_tail`` pipeline pre-escapes its output);
        this method extends the same contract to the recovery
        message so the storage layer is the single source of truth
        for "stderr_tail is already safe-to-render HTML".
        """
        async with self._lock:
            def _update() -> int:
                safe_message = html.escape(message)
                cur = self._conn.execute(
                    "UPDATE notebook_ingest_runs SET "
                    "  status = ?, "
                    "  finished_at = ?, "
                    "  exit_code = -1, "
                    "  stderr_tail = ? "
                    "WHERE status = ? AND started_at < ?",
                    (
                        self.INGEST_STATUS_FAILED,
                        cutoff_iso,
                        safe_message,
                        self.INGEST_STATUS_RUNNING,
                        cutoff_iso,
                    ),
                )
                return cur.rowcount
            return await asyncio.to_thread(_update)


__all__ = [
    "NotebooksStore",
    "SCHEMA_VERSION",
]
