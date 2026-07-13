"""SQLite-backed per-notebook documents registry (source-truth-m1).

The per-REVISION provenance registry: for every ingested arXiv revision
it records the raw-source + parse-artifact checksums, the chunker /
parser version stamps, the OAI-PMH-hydrated license URI + an advisory
3-way ``license_status``, a ``fetched_at`` marker, and an
active/withdrawn/superseded ``status``. ``get_chunk`` does NOT read this
store in m1 (chunks-schema v2 + tool surfacing are m2/m5); the only
writer is :mod:`tools.notebook_documents_backfill`.

**Placement.** Mirrors :mod:`server.paper_metadata_store` EXACTLY: one
SQLite file PER NOTEBOOK at
``var/arxmcp/notebooks/<slug>/documents.db``
(:data:`DOCUMENTS_DB_FILENAME`), a SIBLING of ``paper_metadata.db``.
The data is REGENERABLE (re-run the backfill), so it takes the
``synchronous=NORMAL`` durability tier, NOT the ``FULL``+``fullfsync``
tier of the non-regenerable central ``notebooks.db``.

**Pattern.** Async-over-sync SQLite exactly like
:mod:`server.paper_metadata_store` /
:mod:`server.notebooks_store`: ``asyncio.to_thread`` + an
``asyncio.Lock`` serializing a single ``sqlite3.Connection``, an
``open()`` async classmethod, ``PRAGMA user_version`` versioning with
strictly ADDITIVE migrations. The v0->v1 create is wrapped in an
explicit BEGIN/COMMIT (the connection is autocommit) so a crash
mid-migration can never leave ``user_version`` behind the tables — the
named failure mode from the notebooks_store v4->v5 precedent.

**Identity.** The registry is the FIRST store in this codebase that
retains a REVISION identity, not just a WORK identity. ``work_id`` is
the UNVERSIONED arXiv id with the old-style archive prefix intact
(``math/0212237``, never ``0212237`` or ``math/0212237v1``);
``arxiv_version`` is the concrete ``vN`` when the membership record
carried one, or the empty string ``''`` when it did not (a bare work
id — the common case, since ``papers.txt`` lines are unversioned and
the OAI-PMH ``arXiv`` metadata format surfaces no version number). The
PRIMARY KEY is ``(work_id, arxiv_version)`` so distinct revisions of one
work are distinct rows. The empty-string convention is "abstention, not
silence": it is an explicit "no version specified in the membership
record", never a silently-dropped column.

**Abstention markers (source-truth-m1 OWNER DECISIONS).**

- ``raw_source_sha256`` is NULL with ``raw_source_status='unavailable'``
  for old-style papers that have no raw source on disk
  (``var/arxmcp/corpus/raw/`` has no letter-prefixed dirs — they hit the
  ar5iv cache and never persisted a local ``.tex`` tree). The
  parse-artifact checksum (from ``parsed/<id>/index.html``, present for
  ALL) is still computed. "Abstention, not silence" — the NULL always
  travels with an explicit status reason.
- ``latexml_version`` is NULL: the local ``latexmlc`` build version is
  not captured anywhere in the repo today (no ``--version`` probe on the
  render path), and ar5iv's server-side LaTeXML version is opaque. The
  column exists for m2 to populate; m1 stores NULL rather than inventing
  a value.
- ``parser_used`` is NULL in m1: ``ChunkRecord.parser_used`` exists in
  ``ingest/chunker_types.py`` but is not promoted to a queryable column
  until m2, so there is no per-paper on-disk signal to read. NULL, not a
  guess.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: DocumentsStore schema version. v0->v1 is the initial ADDITIVE create
#: (``CREATE TABLE IF NOT EXISTS``; nothing is ever dropped — the
#: Tier-1 DROP-AND-RECREATE pattern is explicitly NOT used). When adding
#: version N: append a new ``if current_version < N:`` block in
#: ``_open_sync`` wrapped in BEGIN/COMMIT, and bump this constant.
DOCUMENTS_SCHEMA_VERSION: int = 1

#: File name of the per-notebook documents registry DB, a sibling of
#: ``paper_metadata.db`` under ``var/arxmcp/notebooks/<slug>/``. The
#: backfill CLI derives the full path as
#: ``<notebook_dir>/<DOCUMENTS_DB_FILENAME>``.
DOCUMENTS_DB_FILENAME: str = "documents.db"

#: ``status`` column vocabulary. "withdrawn" is hydrated from the
#: OAI-PMH ``<header status="deleted">`` signal (verb-independent, the
#: same signal ``ingest/oai_delta.py`` already parses). "superseded" has
#: NO existing extraction signal (it would need ``arXivRaw``'s
#: ``<version>`` history, unparsed in this repo) and is a reserved value
#: m1 never writes — every registered, non-withdrawn revision is
#: "active".
DOCUMENT_STATUS_ACTIVE: str = "active"
DOCUMENT_STATUS_WITHDRAWN: str = "withdrawn"
DOCUMENT_STATUS_SUPERSEDED: str = "superseded"

#: ``raw_source_status`` column vocabulary — the abstention marker. A
#: row with ``raw_source_status='unavailable'`` carries a NULL
#: ``raw_source_sha256`` BY DESIGN (the old-style raw-source gap), and a
#: re-run must not treat that NULL as a defect to repair.
RAW_SOURCE_STATUS_PRESENT: str = "present"
RAW_SOURCE_STATUS_UNAVAILABLE: str = "unavailable"


@dataclass(frozen=True)
class DocumentRecord:
    """One per-revision provenance row in the documents registry.

    ``work_id`` is UNVERSIONED with the old-style archive prefix intact
    (``math/0212237``). ``arxiv_version`` is the concrete ``vN`` when the
    membership record carried one, else ``''`` (unversioned membership).
    ``raw_source_sha256`` is NULL exactly when
    ``raw_source_status == 'unavailable'`` (the old-style abstention
    marker). ``parser_used`` / ``latexml_version`` are NULL in m1 (see
    the module docstring).
    """

    work_id: str
    arxiv_version: str
    raw_source_sha256: str | None
    raw_source_status: str
    parse_artifact_sha256: str | None
    chunker_version: str
    parser_used: str | None
    latexml_version: str | None
    fetched_at: str
    license_uri: str | None
    license_status: str
    status: str


class DocumentsStore:
    """Async-over-sync SQLite store for the per-notebook documents registry.

    Construct via :meth:`open`. All public methods are ``async`` and
    offload SQL I/O via :func:`asyncio.to_thread`, serialized through an
    internal ``asyncio.Lock`` (single-threaded connection, never raced)
    — the :class:`server.paper_metadata_store.PaperMetadataStore`
    pattern.
    """

    def __init__(self, db_path: Path, connection: sqlite3.Connection) -> None:
        self._db_path = db_path
        self._conn = connection
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    @classmethod
    async def open(cls, db_path: Path) -> DocumentsStore:
        """Open (or create) the SQLite file at ``db_path``.

        Idempotent: opening a current-version file is a no-op beyond the
        connection PRAGMAs — the ``user_version`` row is left untouched.
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)

        def _open_sync() -> sqlite3.Connection:
            conn = sqlite3.connect(
                str(db_path),
                isolation_level=None,  # autocommit; migrations open explicit txns
                check_same_thread=False,  # serialized via asyncio.Lock
            )
            conn.execute("PRAGMA journal_mode=WAL")
            # Regenerable state (re-run the backfill driver) -> NORMAL,
            # the cache_sqlite / paper_metadata_store durability tier.
            conn.execute("PRAGMA synchronous=NORMAL")

            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if current_version < DOCUMENTS_SCHEMA_VERSION:
                logger.info(
                    "DocumentsStore: schema version %d -> %d at %s",
                    current_version, DOCUMENTS_SCHEMA_VERSION, db_path,
                )
            # v0 -> v1: initial ADDITIVE create. Wrapped in an explicit
            # BEGIN/COMMIT (autocommit connection) so the CREATE + the
            # user_version bump apply atomically — a crash between the
            # statements can never strand a half-migrated file (the
            # notebooks_store v4->v5 crash-loop precedent).
            if current_version < 1:
                conn.execute("BEGIN")
                try:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS documents ("
                        "  work_id               TEXT NOT NULL,"
                        "  arxiv_version         TEXT NOT NULL DEFAULT '',"
                        "  raw_source_sha256     TEXT,"
                        "  raw_source_status     TEXT NOT NULL DEFAULT 'unavailable',"
                        "  parse_artifact_sha256 TEXT,"
                        "  chunker_version       TEXT NOT NULL DEFAULT '',"
                        "  parser_used           TEXT,"
                        "  latexml_version       TEXT,"
                        "  fetched_at            TEXT NOT NULL,"
                        "  license_uri           TEXT,"
                        "  license_status        TEXT NOT NULL DEFAULT 'unknown',"
                        "  status                TEXT NOT NULL DEFAULT 'active',"
                        "  PRIMARY KEY (work_id, arxiv_version)"
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
                        "DocumentsStore.close: ignoring close error"
                    )
            await asyncio.to_thread(_close_sync)

    # ------------------------------------------------------------------
    # Write path (backfill CLI)
    # ------------------------------------------------------------------

    async def upsert_records(self, records: list[DocumentRecord]) -> int:
        """Idempotent upsert of a batch of rows in one transaction.

        ``INSERT OR REPLACE`` keyed by ``(work_id, arxiv_version)`` — a
        re-run over already-registered revisions converges to the same
        state. Returns rows written.
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
                            "INSERT OR REPLACE INTO documents ("
                            "  work_id, arxiv_version, raw_source_sha256,"
                            "  raw_source_status, parse_artifact_sha256,"
                            "  chunker_version, parser_used, latexml_version,"
                            "  fetched_at, license_uri, license_status, status"
                            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                r.work_id,
                                r.arxiv_version,
                                r.raw_source_sha256,
                                r.raw_source_status,
                                r.parse_artifact_sha256,
                                r.chunker_version,
                                r.parser_used,
                                r.latexml_version,
                                r.fetched_at,
                                r.license_uri,
                                r.license_status,
                                r.status,
                            ),
                        )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return len(records)
            return await asyncio.to_thread(_write_sync)

    # ------------------------------------------------------------------
    # Read path (backfill idempotency gate / coverage report)
    # ------------------------------------------------------------------

    _SELECT_COLUMNS = (
        "work_id, arxiv_version, raw_source_sha256, raw_source_status, "
        "parse_artifact_sha256, chunker_version, parser_used, "
        "latexml_version, fetched_at, license_uri, license_status, status"
    )

    async def get(
        self, work_id: str, arxiv_version: str = ""
    ) -> DocumentRecord | None:
        """Return the row for ``(work_id, arxiv_version)`` or ``None``."""
        async with self._lock:
            def _query() -> DocumentRecord | None:
                row = self._conn.execute(
                    f"SELECT {self._SELECT_COLUMNS} "  # noqa: S608 — constant columns
                    "FROM documents WHERE work_id = ? AND arxiv_version = ?",
                    (work_id, arxiv_version),
                ).fetchone()
                return None if row is None else _record_from_row(row)
            return await asyncio.to_thread(_query)

    async def registered_keys(self) -> set[tuple[str, str]]:
        """``(work_id, arxiv_version)`` pairs already registered.

        The backfill driver's idempotency gate. Every persisted row is a
        successful registration (rows are written ONLY on a successful
        OAI-PMH response — a transient fetch failure writes NO row so a
        re-run retries it), so plain existence is the gate; unlike
        ``paper_metadata_store`` there is no empty-field leftover to
        exclude.
        """
        async with self._lock:
            def _query() -> set[tuple[str, str]]:
                rows = self._conn.execute(
                    "SELECT work_id, arxiv_version FROM documents"
                ).fetchall()
                return {(r[0], r[1]) for r in rows}
            return await asyncio.to_thread(_query)

    async def all_records(self) -> list[DocumentRecord]:
        """Every row, for the coverage report. Ordered by PK for
        deterministic output."""
        async with self._lock:
            def _query() -> list[DocumentRecord]:
                rows = self._conn.execute(
                    f"SELECT {self._SELECT_COLUMNS} "  # noqa: S608 — constant columns
                    "FROM documents ORDER BY work_id, arxiv_version"
                ).fetchall()
                return [_record_from_row(r) for r in rows]
            return await asyncio.to_thread(_query)

    async def row_count(self) -> int:
        """Total rows — diagnostics and tests."""
        async with self._lock:
            def _count() -> int:
                return int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM documents"
                    ).fetchone()[0]
                )
            return await asyncio.to_thread(_count)


def _record_from_row(row: tuple) -> DocumentRecord:
    """Build a record from a 12-column SQL tuple."""
    return DocumentRecord(
        work_id=row[0],
        arxiv_version=row[1] or "",
        raw_source_sha256=row[2],
        raw_source_status=row[3] or RAW_SOURCE_STATUS_UNAVAILABLE,
        parse_artifact_sha256=row[4],
        chunker_version=row[5] or "",
        parser_used=row[6],
        latexml_version=row[7],
        fetched_at=row[8] or "",
        license_uri=row[9],
        license_status=row[10] or "unknown",
        status=row[11] or DOCUMENT_STATUS_ACTIVE,
    )


__all__ = [
    "DOCUMENTS_DB_FILENAME",
    "DOCUMENTS_SCHEMA_VERSION",
    "DOCUMENT_STATUS_ACTIVE",
    "DOCUMENT_STATUS_SUPERSEDED",
    "DOCUMENT_STATUS_WITHDRAWN",
    "RAW_SOURCE_STATUS_PRESENT",
    "RAW_SOURCE_STATUS_UNAVAILABLE",
    "DocumentRecord",
    "DocumentsStore",
]
