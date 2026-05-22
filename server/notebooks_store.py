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
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

#: NotebooksStore schema version. Bumping triggers DROP-AND-RECREATE
#: on next open (acceptable for the UI surface — the data lives on
#: disk under ``var/arxmcp/notebooks/<slug>/`` and can be re-imported
#: via ``tools/notebook_init.py`` + paper-paste from the UI). When
#: bumping, also bump the schema docstring above.
SCHEMA_VERSION: int = 1


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
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
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
        """Return all notebook rows ordered by ``created_at DESC``."""
        async with self._lock:
            def _query() -> list[dict[str, str]]:
                rows = self._conn.execute(
                    "SELECT slug, display_name, lancedb_path, created_at "
                    "FROM notebooks ORDER BY created_at DESC, slug ASC"
                ).fetchall()
                return [
                    {
                        "slug": r[0], "display_name": r[1],
                        "lancedb_path": r[2], "created_at": r[3],
                    }
                    for r in rows
                ]
            return await asyncio.to_thread(_query)

    async def get_notebook(self, slug: str) -> dict[str, str] | None:
        """Return one notebook row by slug, or ``None`` if absent."""
        async with self._lock:
            def _query() -> dict[str, str] | None:
                row = self._conn.execute(
                    "SELECT slug, display_name, lancedb_path, created_at "
                    "FROM notebooks WHERE slug = ?",
                    (slug,),
                ).fetchone()
                if row is None:
                    return None
                return {
                    "slug": row[0], "display_name": row[1],
                    "lancedb_path": row[2], "created_at": row[3],
                }
            return await asyncio.to_thread(_query)

    async def create_notebook(
        self,
        slug: str,
        display_name: str,
        lancedb_path: str,
        created_at: str,
    ) -> None:
        """Insert a notebook row. Raises :class:`sqlite3.IntegrityError`
        on duplicate slug — the REST handler catches and translates to
        HTTP 409 (FM-5).
        """
        async with self._lock:
            def _insert() -> None:
                self._conn.execute(
                    "INSERT INTO notebooks "
                    "(slug, display_name, lancedb_path, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (slug, display_name, lancedb_path, created_at),
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


__all__ = [
    "NotebooksStore",
    "SCHEMA_VERSION",
]
