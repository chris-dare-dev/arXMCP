"""SQLite-backed per-notebook paper metadata store (paper-metadata-m1).

Holds real paper identity (title / authors / abstract / year /
categories) hydrated from the arXiv Atom API, so ``get_paper`` (m2)
can stop synthesizing NULLs from the chunks table. The store is
SELF-CONTAINED: it never imports or touches LanceDB — the m1
acceptance requires metadata to be served after a cold reopen
without touching the chunks table.

**Placement (m1 open decision A/B → B).** One SQLite file PER
NOTEBOOK at ``var/arxmcp/notebooks/<slug>/paper_metadata.db``
(:data:`PAPER_METADATA_DB_FILENAME`), NOT a v5→v6 table in the
central ``notebooks.db``:

- arXiv metadata is REGENERABLE (re-run the backfill), so it does
  not belong in the ``synchronous=FULL`` + ``fullfsync=ON``
  non-regenerable ``notebooks.db``; it takes the ``NORMAL``
  durability tier of :mod:`server.cache_sqlite` /
  :mod:`server.theorem_names_store`.
- Per-notebook files match the fork-C isolation precedent
  (``lancedb/``, ``index/bm25/``, ``cache/retrieval.db``) and keep
  the CLI-writer / server-reader split off the daemon's live
  central DB.
- m1 stays fully additive: no ``NotebooksStore`` schema bump, no
  lockstep edits to the tests that pin its ``SCHEMA_VERSION``.

**Pattern.** Async-over-sync SQLite exactly like
:mod:`server.notebooks_store`: ``asyncio.to_thread`` + an
``asyncio.Lock`` serializing a single ``sqlite3.Connection``,
``open()`` async classmethod, ``PRAGMA user_version`` versioning
with strictly ADDITIVE migrations. The v0→v1 block is wrapped in
an explicit BEGIN/COMMIT (the connection is autocommit) so a crash
mid-migration can never leave ``user_version`` behind the tables —
the named failure mode from the notebooks_store v4→v5 precedent.

``title`` / ``authors`` use empty-value defaults (``''`` / ``'[]'``)
rather than SQL NULLs; "non-NULL title AND authors" in the m1
acceptance maps to "non-empty" here. ``authors`` / ``categories``
are JSON arrays. ``fetched_at`` is the per-row hydration marker the
research brief prescribed (field coverage across ID shapes is
API-dependent; design defensively).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: PaperMetadataStore schema version. v0→v1 is the initial ADDITIVE
#: create (``CREATE TABLE IF NOT EXISTS``; nothing is ever dropped —
#: the Tier-1 DROP-AND-RECREATE pattern is explicitly NOT used, per
#: the t-store-schema acceptance). When adding version N: append a
#: new ``if current_version < N:`` block in ``_open_sync`` wrapped
#: in BEGIN/COMMIT, and bump this constant.
SCHEMA_VERSION: int = 1

#: File name of the per-notebook metadata DB, sibling to the
#: notebook's ``papers.txt``. m2's server open path and the m1
#: backfill CLI both derive the full path as
#: ``<notebook_dir>/<PAPER_METADATA_DB_FILENAME>``.
PAPER_METADATA_DB_FILENAME: str = "paper_metadata.db"


@dataclass(frozen=True)
class PaperMetadataRecord:
    """One hydrated paper-metadata row.

    ``paper_id`` is UNVERSIONED with the old-style archive prefix
    intact (``math/0212237``, never ``0212237`` or
    ``math/0212237v1``) — the t-atom-mapper round-trip contract.
    ``year == 0`` means "unparseable ``<published>``" (mirrors the
    ``Candidate.submitted_year`` convention in ``tools/_arxiv_api``).
    """

    paper_id: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    year: int
    categories: tuple[str, ...]
    primary_category: str
    published: str
    fetched_at: str
    source: str = "arxiv-atom"


class PaperMetadataStore:
    """Async-over-sync SQLite store for per-notebook paper metadata.

    Construct via :meth:`open`. All public methods are ``async`` and
    offload SQL I/O via :func:`asyncio.to_thread`, serialized through
    an internal ``asyncio.Lock`` (single-threaded connection, never
    raced) — the :class:`server.notebooks_store.NotebooksStore`
    pattern.
    """

    #: Bound on the :meth:`get_cached` LRU. At ~a few hundred bytes per
    #: cached record, 4096 distinct papers is well under a MB — and the
    #: enrichment consumer (search/cite rows) touches at most k≤50 +
    #: neighbor-limit distinct ids per call.
    _GET_LRU_CAP: int = 4096

    def __init__(self, db_path: Path, connection: sqlite3.Connection) -> None:
        self._db_path = db_path
        self._conn = connection
        self._lock = asyncio.Lock()
        #: agent-platform-t-semantic-identifiers (#84): bounded LRU for
        #: the row-enrichment title/year join. Keyed by the (caller-
        #: normalized, unversioned) paper_id — safe for the single shared
        #: store; if per-notebook stores are ever added, the key must
        #: gain the notebook dimension (the LRU lives on the store
        #: instance precisely so that stays a per-store concern).
        self._get_lru: OrderedDict[str, PaperMetadataRecord | None] = OrderedDict()

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    @classmethod
    async def open(cls, db_path: Path) -> PaperMetadataStore:
        """Open (or create) the SQLite file at ``db_path``.

        Idempotent: opening a current-version file is a no-op beyond
        the connection PRAGMAs — the ``user_version`` row is left
        untouched (t-store-schema acceptance).
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)

        def _open_sync() -> sqlite3.Connection:
            conn = sqlite3.connect(
                str(db_path),
                isolation_level=None,  # autocommit; migrations open explicit txns
                check_same_thread=False,  # serialized via asyncio.Lock
            )
            conn.execute("PRAGMA journal_mode=WAL")
            # Regenerable state (re-run the backfill driver) → NORMAL,
            # the cache_sqlite / theorem_names_store durability tier.
            # notebooks.db's FULL+fullfsync is for NON-regenerable state.
            conn.execute("PRAGMA synchronous=NORMAL")

            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if current_version < SCHEMA_VERSION:
                logger.info(
                    "PaperMetadataStore: schema version %d -> %d at %s",
                    current_version, SCHEMA_VERSION, db_path,
                )
            # v0 -> v1: initial ADDITIVE create. Wrapped in an explicit
            # BEGIN/COMMIT (autocommit connection) so the CREATEs + the
            # user_version bump apply atomically — a crash between the
            # statements can never strand a half-migrated file that
            # errors on the next open (the notebooks_store v4→v5
            # crash-loop precedent).
            if current_version < 1:
                conn.execute("BEGIN")
                try:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS paper_metadata ("
                        "  paper_id         TEXT PRIMARY KEY,"
                        "  title            TEXT NOT NULL DEFAULT '',"
                        "  authors          TEXT NOT NULL DEFAULT '[]',"
                        "  abstract         TEXT NOT NULL DEFAULT '',"
                        "  year             INTEGER NOT NULL DEFAULT 0,"
                        "  categories       TEXT NOT NULL DEFAULT '[]',"
                        "  primary_category TEXT NOT NULL DEFAULT '',"
                        "  published        TEXT NOT NULL DEFAULT '',"
                        "  fetched_at       TEXT NOT NULL,"
                        "  source           TEXT NOT NULL DEFAULT 'arxiv-atom'"
                        ")"
                    )
                    conn.execute("PRAGMA user_version = 1")
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
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
                        "PaperMetadataStore.close: ignoring close error"
                    )
            await asyncio.to_thread(_close_sync)

    # ------------------------------------------------------------------
    # Write path (backfill CLI / ingest hook)
    # ------------------------------------------------------------------

    async def upsert_records(self, records: list[PaperMetadataRecord]) -> int:
        """Idempotent upsert of a batch of rows in one transaction.

        ``INSERT OR REPLACE`` keyed by ``paper_id`` — re-running the
        backfill over already-hydrated rows converges to the same
        state (t-backfill-driver acceptance). Returns rows written.
        """
        if not records:
            return 0
        async with self._lock:
            def _write_sync() -> int:
                conn = self._conn
                conn.execute("BEGIN")
                try:
                    for r in records:
                        conn.execute(
                            "INSERT OR REPLACE INTO paper_metadata ("
                            "  paper_id, title, authors, abstract, year,"
                            "  categories, primary_category, published,"
                            "  fetched_at, source"
                            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                r.paper_id,
                                r.title,
                                json.dumps(list(r.authors), ensure_ascii=False),
                                r.abstract,
                                int(r.year),
                                json.dumps(list(r.categories), ensure_ascii=False),
                                r.primary_category,
                                r.published,
                                r.fetched_at,
                                r.source,
                            ),
                        )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return len(records)
            return await asyncio.to_thread(_write_sync)

    # ------------------------------------------------------------------
    # Read path (m2 get_paper handler / backfill skip logic)
    # ------------------------------------------------------------------

    _SELECT_COLUMNS = (
        "paper_id, title, authors, abstract, year, categories, "
        "primary_category, published, fetched_at, source"
    )

    async def get(self, paper_id: str) -> PaperMetadataRecord | None:
        """Return the row for ``paper_id`` or ``None`` if absent."""
        async with self._lock:
            def _query() -> PaperMetadataRecord | None:
                row = self._conn.execute(
                    f"SELECT {self._SELECT_COLUMNS} "  # noqa: S608 — constant columns
                    "FROM paper_metadata WHERE paper_id = ?",
                    (paper_id,),
                ).fetchone()
                return None if row is None else _record_from_row(row)
            return await asyncio.to_thread(_query)

    async def get_cached(self, paper_id: str) -> PaperMetadataRecord | None:
        """LRU-cached :meth:`get` for row enrichment (#84).

        The caller passes an already version-normalized id (the store is
        keyed unversioned). Bounds DB reads to one per distinct paper_id
        across a response and keeps repeated queries warm. Cache is
        performance, not correctness: a row backfilled out-of-band after
        an entry is cached is served stale until eviction — the same
        posture as the retrieval cache, and acceptable because the
        null-safe consumer degrades a miss to ``title: null`` anyway.
        """
        if paper_id in self._get_lru:
            self._get_lru.move_to_end(paper_id)
            return self._get_lru[paper_id]
        record = await self.get(paper_id)
        self._get_lru[paper_id] = record
        if len(self._get_lru) > self._GET_LRU_CAP:
            self._get_lru.popitem(last=False)
        return record

    async def hydrated_paper_ids(self) -> set[str]:
        """paper_ids whose title AND authors are non-empty.

        The backfill driver's idempotency gate: rows that exist but
        carry empty title/authors (defensive-write leftovers) are NOT
        counted, so a re-run retries them instead of silently keeping
        a hole in the ≥95% acceptance budget.
        """
        async with self._lock:
            def _query() -> set[str]:
                rows = self._conn.execute(
                    "SELECT paper_id FROM paper_metadata "
                    "WHERE title != '' AND authors != '[]'"
                ).fetchall()
                return {r[0] for r in rows}
            return await asyncio.to_thread(_query)

    async def row_count(self) -> int:
        """Total rows — diagnostics and tests."""
        async with self._lock:
            def _count() -> int:
                return int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM paper_metadata"
                    ).fetchone()[0]
                )
            return await asyncio.to_thread(_count)


def _record_from_row(row: tuple) -> PaperMetadataRecord:
    """Build a record from a 10-column SQL tuple, tolerating bad JSON."""
    return PaperMetadataRecord(
        paper_id=row[0],
        title=row[1] or "",
        authors=_json_str_tuple(row[2]),
        abstract=row[3] or "",
        year=int(row[4] or 0),
        categories=_json_str_tuple(row[5]),
        primary_category=row[6] or "",
        published=row[7] or "",
        fetched_at=row[8] or "",
        source=row[9] or "arxiv-atom",
    )


def _json_str_tuple(raw: str | None) -> tuple[str, ...]:
    """Decode a JSON array column into a tuple of strings.

    Malformed JSON (hand-edited file, partial write on a NORMAL-
    durability crash) degrades to ``()`` rather than raising — the
    row then reads as not-hydrated and the backfill repairs it.
    """
    if not raw:
        return ()
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value)


__all__ = [
    "PAPER_METADATA_DB_FILENAME",
    "PaperMetadataRecord",
    "PaperMetadataStore",
    "SCHEMA_VERSION",
]
