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
#:
#: v3→v4 is the textbook-ingest-m6 ADDITIVE migration adding three
#: parse-tracking columns to ``notebooks``: ``parse_status``,
#: ``parse_error``, ``parsed_html_path``. The column-level DEFAULT
#: ``'skipped'`` backfills every existing arxiv-kind row safely;
#: textbook-kind rows MUST be created with an explicit
#: ``parse_status='pending'`` by the route layer.
#:
#: v4→v5 is the notebook-paper-discovery-m1 ADDITIVE migration adding
#: two columns that give a notebook a machine-readable research
#: interest for topic-driven paper discovery (the m2–m4 channels):
#: ``discovery_category`` (an arXiv category code validated at the
#: route layer against ``{math.AG, math.NT, math-ph, hep-th}``) and
#: free-text ``description``. Column-level DEFAULT ``''`` backfills
#: every existing row; the route layer is the validation authority.
#:
#: v5→v6 is the contract-v1 ADDITIVE migration adding ``formal_releases``
#: — arXMCP's PIN to a topic repo's released formalization (ADR-0004:
#: arXMCP holds no registry, only a pin to one, and re-serves its
#: records verbatim). Written by ``tools/formal_release_pin.py``, read
#: by the ``arxmcp://formal/*`` resources. derived-alg-geo-lean #174.
SCHEMA_VERSION: int = 6


#: Module-level so a SYNC CLI can reach the migration ladder.
#:
#: It used to be a closure inside ``NotebooksStore.open``, which meant the
#: only way to migrate this file was to construct an async store. Two CLIs
#: could not, and wrote the ``notebooks`` table by raw ``sqlite3`` instead:
#: ``tools/notebook_restore.py`` (:227, :302, :320) and, once contract-v1
#: landed, the release pinner. Neither touched ``user_version``, so rows they
#: wrote sat in a file the v0->v1 block below would DROP on the next server
#: start -- the migration is guarded by ``current_version < 1`` and a
#: raw-sqlite writer leaves that at 0 forever. ``tools/notebook_list_offline.py``
#: already carries the read-side half of this lesson (its m2 critique F2).
#:
#: A writer must call this; a READER must not (it migrates), and should open
#: ``mode=ro`` the way the offline lister does.
def open_sync(db_path: Path) -> sqlite3.Connection:
    """Open + migrate ``notebooks.db``, synchronously. Returns the connection.

    Same PRAGMAs and the same migration ladder :meth:`NotebooksStore.open`
    applies, because it IS the one :meth:`NotebooksStore.open` applies.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        check_same_thread=False,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    # Durability (notebook-ops-hardening-m2): notebooks.db holds
    # user-authored, NON-regenerable state (notebook membership,
    # uploaded-paper provenance), so it earns full crash durability.
    #   synchronous=FULL: in WAL mode, NORMAL can roll back the last
    #     committed transaction on power loss; FULL adds a WAL sync
    #     after every commit -> ACID-durable across power loss.
    #   fullfsync=ON: macOS only. Forces a true fcntl(F_FULLFSYNC)
    #     instead of the kernel's deferrable fsync (same neutered-fsync
    #     theme as CLAUDE.md gotcha #9). This is CONNECTION-scoped (it
    #     does NOT persist to a fresh connection), so it must be set
    #     here, on every open; setting it once and re-opening is a
    #     silent no-op. On Linux (the prod-container target) F_FULLFSYNC
    #     does not exist; SQLite falls back to plain fsync, which with
    #     synchronous=FULL is already durable — so fullfsync is a no-op
    #     there and harms nothing; durability in prod rests on FULL+fsync.
    #     (cache_sqlite.py / theorem_names_store.py stay NORMAL on
    #     purpose: regenerable caches, not correctness state.)
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA fullfsync=ON")
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
    # v3 -> v4: textbook-ingest-m6 ADDITIVE migration. Three
    # parse-tracking columns on the ``notebooks`` table:
    #
    # - ``parse_status`` — enum
    #   ``{skipped, pending, running, complete, failed}``.
    #   Column-level DEFAULT ``'skipped'`` so existing arxiv-
    #   kind rows backfill correctly. The route handler
    #   explicitly sets ``parse_status='pending'`` when
    #   creating a textbook-kind notebook.
    # - ``parse_error`` — HTML-escaped tail of any subprocess
    #   stderr captured at the parse-task boundary.
    # - ``parsed_html_path`` — relative path under
    #   ``var/arxmcp/notebooks/<slug>/parsed/`` to the
    #   rendered ``index.html``. Empty until the parse task
    #   reports complete.
    if current_version < 4:
        conn.execute(
            "ALTER TABLE notebooks ADD COLUMN parse_status "
            "TEXT NOT NULL DEFAULT 'skipped'"
        )
        conn.execute(
            "ALTER TABLE notebooks ADD COLUMN parse_error "
            "TEXT NOT NULL DEFAULT ''"
        )
        conn.execute(
            "ALTER TABLE notebooks ADD COLUMN parsed_html_path "
            "TEXT NOT NULL DEFAULT ''"
        )
        conn.execute("PRAGMA user_version = 4")
    # v4 -> v5: notebook-paper-discovery-m1 ADDITIVE migration.
    # Two columns on ``notebooks`` give a notebook a machine-
    # readable research interest for topic-driven paper discovery
    # (m2-m4): ``discovery_category`` (an arXiv category code,
    # validated at the route layer against
    # {math.AG, math.NT, math-ph, hep-th}) and free-text
    # ``description``. Column-level DEFAULT '' backfills every
    # existing row in O(1) (no row-rewrite).
    #
    # Unlike the v1->v4 blocks (each a single ALTER), v4->v5 adds
    # TWO columns. A crash BETWEEN the two ALTERs would leave the
    # DB half-migrated (``user_version`` still 4 but
    # ``discovery_category`` already present), so the next open
    # re-runs the block and the first ALTER raises
    # ``sqlite3.OperationalError: duplicate column name``,
    # crash-looping the daemon at startup. Wrap the two ALTERs +
    # the version bump in an explicit BEGIN/COMMIT so the whole
    # step is atomic and re-runnable. The connection is
    # ``isolation_level=None`` (autocommit), so the transaction
    # MUST be opened explicitly.
    if current_version < 5:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "ALTER TABLE notebooks ADD COLUMN "
                "discovery_category TEXT NOT NULL DEFAULT ''"
            )
            conn.execute(
                "ALTER TABLE notebooks ADD COLUMN "
                "description TEXT NOT NULL DEFAULT ''"
            )
            conn.execute("PRAGMA user_version = 5")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    # v5 -> v6: contract-v1 ADDITIVE migration.
    # ``formal_releases`` is arXMCP's PIN to a topic repo's
    # released formalization. ADR-0004: arXMCP hosts no
    # registry -- it holds a pin to one and re-serves its
    # records verbatim, and it may DOWNGRADE a trust axis from
    # its own fresher resolution while having no code path that
    # raises one.
    #
    # The big artifacts are NOT in here. ``declarations.json``
    # is 16 MB at v0.1.0 and ``lean-emission.json`` 36 MB, and
    # this file is the one the durability comment above calls
    # user-authored non-regenerable state at synchronous=FULL.
    # Those live under ``asset_dir`` on disk, digest-pinned;
    # the columns hold the small artifacts the resources
    # actually serve.
    #
    # ``digest_provenance`` is a column rather than a boolean
    # because it names WHICH root of trust the pin rests on,
    # and 4.9 rule 1 forbids collapsing that into a pass/fail
    # token. See ``tools/formal_release_pin.py``.
    if current_version < 6:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS formal_releases ("
                "  slug              TEXT NOT NULL,"
                "  repo              TEXT NOT NULL,"
                "  tag               TEXT NOT NULL,"
                "  tag_object_sha    TEXT NOT NULL,"
                "  commit_sha        TEXT NOT NULL,"
                "  registry_id       TEXT NOT NULL,"
                "  registry_sha256   TEXT NOT NULL,"
                "  env_digest        TEXT NOT NULL,"
                "  digest_provenance TEXT NOT NULL,"
                "  asset_dir         TEXT NOT NULL DEFAULT '',"
                "  bundle_json       TEXT NOT NULL,"
                "  registry_json     TEXT NOT NULL,"
                "  resolution_json   TEXT,"
                "  review_json       TEXT,"
                "  withdrawals_json  TEXT,"
                "  withdrawals_tag   TEXT,"
                "  pinned_at         TEXT NOT NULL,"
                "  PRIMARY KEY (slug, repo),"
                "  FOREIGN KEY (slug) REFERENCES notebooks(slug) "
                "    ON DELETE CASCADE"
                ")"
            )
            conn.execute("PRAGMA user_version = 6")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return conn


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

        The migration ladder lives in :func:`open_sync` at module scope so
        the sync CLIs that write this file run it too; see that docstring
        for what went wrong while they could not.
        """
        conn = await asyncio.to_thread(open_sync, db_path)
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

        textbook-ingest-m3 added ``notebook_kind``; textbook-ingest-m6
        added ``parse_status`` + ``parse_error`` + ``parsed_html_path``.
        Existing notebook.db rows are backfilled by the v2→v3 and v3→v4
        SQLite DEFAULT migrations (arxiv-kind → ``parse_status='skipped'``).
        """
        async with self._lock:
            def _query() -> list[dict[str, str]]:
                rows = self._conn.execute(
                    "SELECT slug, display_name, lancedb_path, "
                    "created_at, notebook_kind, parse_status, "
                    "parse_error, parsed_html_path, "
                    "discovery_category, description "
                    "FROM notebooks ORDER BY created_at DESC, slug ASC"
                ).fetchall()
                return [
                    {
                        "slug": r[0], "display_name": r[1],
                        "lancedb_path": r[2], "created_at": r[3],
                        "notebook_kind": r[4],
                        "parse_status": r[5],
                        "parse_error": r[6],
                        "parsed_html_path": r[7],
                        "discovery_category": r[8],
                        "description": r[9],
                    }
                    for r in rows
                ]
            return await asyncio.to_thread(_query)

    async def get_notebook(self, slug: str) -> dict[str, str] | None:
        """Return one notebook row by slug, or ``None`` if absent.

        textbook-ingest-m3: ``notebook_kind`` included.
        textbook-ingest-m6: ``parse_status`` + ``parse_error`` +
        ``parsed_html_path`` included.
        """
        async with self._lock:
            def _query() -> dict[str, str] | None:
                row = self._conn.execute(
                    "SELECT slug, display_name, lancedb_path, "
                    "created_at, notebook_kind, parse_status, "
                    "parse_error, parsed_html_path, "
                    "discovery_category, description "
                    "FROM notebooks WHERE slug = ?",
                    (slug,),
                ).fetchone()
                if row is None:
                    return None
                return {
                    "slug": row[0], "display_name": row[1],
                    "lancedb_path": row[2], "created_at": row[3],
                    "notebook_kind": row[4],
                    "parse_status": row[5],
                    "parse_error": row[6],
                    "parsed_html_path": row[7],
                    "discovery_category": row[8],
                    "description": row[9],
                }
            return await asyncio.to_thread(_query)

    async def create_notebook(
        self,
        slug: str,
        display_name: str,
        lancedb_path: str,
        created_at: str,
        notebook_kind: str = "arxiv",
        parse_status: str | None = None,
        discovery_category: str = "",
        description: str = "",
    ) -> None:
        """Insert a notebook row. Raises :class:`sqlite3.IntegrityError`
        on duplicate slug — the REST handler catches and translates to
        HTTP 409 (FM-5).

        notebook-paper-discovery-m1: ``discovery_category`` +
        ``description`` default to ``''`` so existing callers that don't
        supply them keep empty topic metadata. The route layer's
        ``_validate_discovery_category`` enforces the
        ``{math.AG, math.NT, math-ph, hep-th, ''}`` domain before the
        call reaches this writer; this method does no validation.

        textbook-ingest-m3: ``notebook_kind`` default ``"arxiv"`` so
        existing callers that don't supply it keep arXiv-corpus
        semantics. The route layer's ``NotebookCreate`` Pydantic model
        enforces the ``{arxiv, textbook}`` enum domain before the call
        reaches this writer.

        textbook-ingest-m6: ``parse_status`` defaults to ``None``, in
        which case the SQLite column-level DEFAULT (``'skipped'``)
        applies — correct for arxiv-kind. The route handler explicitly
        passes ``parse_status='pending'`` for textbook-kind so the
        upload-route's parse-task scheduler observes the right initial
        state.
        """
        async with self._lock:
            def _insert() -> None:
                if parse_status is None:
                    self._conn.execute(
                        "INSERT INTO notebooks "
                        "(slug, display_name, lancedb_path, created_at, "
                        " notebook_kind, discovery_category, description) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (slug, display_name, lancedb_path, created_at,
                         notebook_kind, discovery_category, description),
                    )
                else:
                    self._conn.execute(
                        "INSERT INTO notebooks "
                        "(slug, display_name, lancedb_path, created_at, "
                        " notebook_kind, parse_status, "
                        " discovery_category, description) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (slug, display_name, lancedb_path, created_at,
                         notebook_kind, parse_status,
                         discovery_category, description),
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

    async def update_display_name(self, slug: str, display_name: str) -> bool:
        """Rename a notebook (notebook-surface-expansion-m2).

        Single-column ``UPDATE notebooks SET display_name = ?``. The
        ``display_name`` column already exists at ``SCHEMA_VERSION 4``
        (``TEXT NOT NULL DEFAULT ''``) — NO migration. An empty string
        is a valid value (clears the name). Returns ``True`` if a row
        was updated, ``False`` if the slug is unknown (handler → 404),
        mirroring :meth:`delete_notebook` / :meth:`update_parse_status`.

        The route layer is the single source of truth for input
        validation (Pydantic ``max_length=256`` + control-char strip);
        this method does no escaping (the fragment renderer
        html-escapes at output time — m2 synthesis D1/D4).
        """
        async with self._lock:
            def _update() -> bool:
                cur = self._conn.execute(
                    "UPDATE notebooks SET display_name = ? WHERE slug = ?",
                    (display_name, slug),
                )
                return cur.rowcount > 0
            return await asyncio.to_thread(_update)

    async def update_topic(
        self,
        slug: str,
        discovery_category: str,
        description: str,
    ) -> bool:
        """Update a notebook's topic metadata (notebook-paper-discovery-m1).

        Two-column ``UPDATE notebooks SET discovery_category = ?,
        description = ?``. Both columns exist at ``SCHEMA_VERSION 5``
        (``TEXT NOT NULL DEFAULT ''``). Empty strings are valid (clear
        the topic). Returns ``True`` if a row was updated, ``False`` if
        the slug is unknown (handler → 404), mirroring
        :meth:`update_display_name`.

        The route layer is the single source of truth for input
        validation (``_validate_discovery_category`` for the category
        enum, Pydantic ``max_length`` for the free-text description);
        this method does no escaping (the fragment renderer
        html-escapes at output time, mirroring
        :meth:`update_display_name`).
        """
        async with self._lock:
            def _update() -> bool:
                cur = self._conn.execute(
                    "UPDATE notebooks SET "
                    "discovery_category = ?, description = ? "
                    "WHERE slug = ?",
                    (discovery_category, description, slug),
                )
                return cur.rowcount > 0
            return await asyncio.to_thread(_update)

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


    # ------------------------------------------------------------------
    # Parse-status (textbook-ingest-m6)
    # ------------------------------------------------------------------

    #: Terminal-state values for the ``parse_status`` column.
    PARSE_STATUS_SKIPPED: str = "skipped"
    PARSE_STATUS_PENDING: str = "pending"
    PARSE_STATUS_RUNNING: str = "running"
    PARSE_STATUS_COMPLETE: str = "complete"
    PARSE_STATUS_FAILED: str = "failed"

    async def update_parse_status(
        self,
        slug: str,
        status: str,
        *,
        parse_error: str | None = None,
        parsed_html_path: str | None = None,
    ) -> bool:
        """Update the parse-status columns for a notebook.

        ``parse_error`` and ``parsed_html_path`` are ``None``-passable
        so callers can update one column without disturbing the others;
        ``None`` leaves the existing value untouched. Returns ``True``
        if a row was updated, ``False`` if the slug is unknown.

        textbook-ingest-m6 contract: the route layer pre-escapes
        ``parse_error`` content (the storage layer is the single
        source of truth for "stderr_tail is already safe-to-render
        HTML" per the m9 ingest_tracker precedent).
        """
        async with self._lock:
            def _update() -> bool:
                # Build the UPDATE dynamically so ``None`` arguments
                # leave the existing column value alone.
                sets: list[str] = ["parse_status = ?"]
                params: list[object] = [status]
                if parse_error is not None:
                    sets.append("parse_error = ?")
                    params.append(parse_error)
                if parsed_html_path is not None:
                    sets.append("parsed_html_path = ?")
                    params.append(parsed_html_path)
                params.append(slug)
                cur = self._conn.execute(
                    f"UPDATE notebooks SET {', '.join(sets)} WHERE slug = ?",
                    tuple(params),
                )
                return cur.rowcount > 0
            return await asyncio.to_thread(_update)

    async def has_running_parse(self, slug: str) -> bool:
        """Cross-restart fallback for the 409 collision check.

        Mirrors :meth:`has_running_ingest`. Used by the upload route
        to refuse a second textbook parse for the same slug while
        the first is still running — paired with the in-memory
        ``ParseTaskTracker.is_running(slug)`` for live-process checks.
        """
        async with self._lock:
            def _check() -> bool:
                row = self._conn.execute(
                    "SELECT 1 FROM notebooks "
                    "WHERE slug = ? AND parse_status = ? LIMIT 1",
                    (slug, self.PARSE_STATUS_RUNNING),
                ).fetchone()
                return row is not None
            return await asyncio.to_thread(_check)

    async def mark_orphaned_parses_failed(
        self,
        message: str,
    ) -> int:
        """Mark every ``parse_status='running'`` row as ``failed``
        with ``parse_error=message``.

        Called at lifespan startup (textbook-ingest-m6 FM-4): if the
        daemon died mid-parse the previous task's done-callback never
        fired and the row would stay ``running`` forever; mark it as
        ``failed`` before the new daemon accepts uploads for the same
        slug.

        Returns the number of rows updated.

        Mirrors the contract of :meth:`mark_orphaned_runs_failed`:
        ``message`` is HTML-escaped before storage so the
        ``parse_error`` column is always safe-to-render HTML at the
        boundary.

        Note: unlike the ingest counterpart, parses do not have a
        per-row ``started_at`` timestamp (the parse-status fields
        live on the notebooks row, not a separate runs table); the
        recovery sweep matches ALL ``running`` rows unconditionally.
        This is safe because the lifespan startup runs BEFORE the
        new ParseTaskTracker accepts any new parse — any in-flight
        ``running`` row is by definition orphaned.
        """
        async with self._lock:
            def _update() -> int:
                safe_message = html.escape(message)
                cur = self._conn.execute(
                    "UPDATE notebooks SET "
                    "  parse_status = ?, "
                    "  parse_error = ? "
                    "WHERE parse_status = ?",
                    (
                        self.PARSE_STATUS_FAILED,
                        safe_message,
                        self.PARSE_STATUS_RUNNING,
                    ),
                )
                return cur.rowcount
            return await asyncio.to_thread(_update)


    # ------------------------------------------------------------------
    # Formal releases (contract-v1; derived-alg-geo-lean #174)
    # ------------------------------------------------------------------

    async def upsert_formal_release(self, row: dict[str, str | None]) -> None:
        """Write (or replace) the pin for ``(slug, repo)``.

        ``INSERT OR REPLACE``: one pin per notebook per topic repo, and
        re-pinning to a newer tag REPLACES rather than accumulates. Keeping
        both would leave two answers to "what does this notebook serve", and
        the resource would have to choose -- which is the operator's decision,
        expressed by which tag they pinned.

        The caller (``tools/formal_release_pin.py``) owns every verification;
        this method owns none. That split is deliberate: a store method that
        re-checked digests would be a second, weaker gate that a future caller
        might rely on instead of the real one.
        """
        async with self._lock:
            def _write() -> None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO formal_releases ("
                    "  slug, repo, tag, tag_object_sha, commit_sha,"
                    "  registry_id, registry_sha256, env_digest,"
                    "  digest_provenance, asset_dir, bundle_json,"
                    "  registry_json, resolution_json, review_json,"
                    "  withdrawals_json, withdrawals_tag, pinned_at"
                    ") VALUES ("
                    "  :slug, :repo, :tag, :tag_object_sha, :commit_sha,"
                    "  :registry_id, :registry_sha256, :env_digest,"
                    "  :digest_provenance, :asset_dir, :bundle_json,"
                    "  :registry_json, :resolution_json, :review_json,"
                    "  :withdrawals_json, :withdrawals_tag, :pinned_at"
                    ")",
                    row,
                )
            await asyncio.to_thread(_write)

    async def get_formal_release(self, slug: str) -> dict[str, str | None] | None:
        """The pin for ``slug``, or ``None`` when this notebook pins nothing.

        ``None`` is the ordinary case and not an error: most notebooks have no
        formalization, and the ``arxmcp://formal/{notebook}`` resource says so
        rather than 404-ing, because "this corpus has no formalization" is an
        answer.
        """
        async with self._lock:
            def _query() -> dict[str, str | None] | None:
                cur = self._conn.execute(
                    f"SELECT {_FORMAL_COLUMNS} FROM formal_releases "
                    "WHERE slug = ? ORDER BY repo LIMIT 1",
                    (slug,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return dict(zip(_FORMAL_COLUMNS.split(", "), row, strict=True))
            return await asyncio.to_thread(_query)

    async def list_formal_releases(self) -> list[dict[str, str | None]]:
        """Every pin, ordered by ``(slug, repo)``."""
        async with self._lock:
            def _query() -> list[dict[str, str | None]]:
                cur = self._conn.execute(
                    f"SELECT {_FORMAL_COLUMNS} FROM formal_releases "
                    "ORDER BY slug, repo"
                )
                names = _FORMAL_COLUMNS.split(", ")
                return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
            return await asyncio.to_thread(_query)


#: Selected explicitly rather than with ``*`` so a future ALTER cannot silently
#: change the shape every reader unpacks.
_FORMAL_COLUMNS = (
    "slug, repo, tag, tag_object_sha, commit_sha, registry_id, "
    "registry_sha256, env_digest, digest_provenance, asset_dir, bundle_json, "
    "registry_json, resolution_json, review_json, withdrawals_json, "
    "withdrawals_tag, pinned_at"
)


__all__ = [
    "NotebooksStore",
    "SCHEMA_VERSION",
    "open_sync",
]
