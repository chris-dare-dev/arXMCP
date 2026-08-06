"""``operator_settings`` SQLite-backed key-value store
(``onboarding-uplift-m2``).

Co-resident with the ``notebooks`` and ``notebook_papers`` tables in
``var/arxmcp/cache/notebooks.db``. Stores **operator preferences** that
both the long-running server AND short-lived CLI tools need to read +
write — today: ``contact_email`` (the arXiv polite-pool User-Agent
value the CLI fetch tools require). Future keys: wizard
dismissal-state, last-ingest timestamp, etc.

**Design (per m2 synthesis §1 + D1):**

The store lives in the SAME ``notebooks.db`` file as
:class:`server.notebooks_store.NotebooksStore`, but is **migration-
independent**. ``NotebooksStore`` owns ``PRAGMA user_version`` for its
own table evolution (currently v4); ``OperatorSettingsStore`` uses an
**in-table** ``__schema_version__`` sentinel row in
``operator_settings`` to track its own schema independently. The two
stores share the file, the WAL pragmas, the durability discipline, and
nothing else — neither needs the other to have run first.

This is the m2 synthesis §3 D1 resolution: requiring
``NotebooksStore.open()`` before ``OperatorSettingsStore.open()`` would
be a layering violation (CLI tools open this store cold without ever
instantiating ``NotebooksStore``). The in-table sentinel also makes
"accidentally clobbering ``NotebooksStore``'s ``user_version``" a
structural impossibility — this module has no ``PRAGMA user_version``
line at all.

**Dual API:**

- :class:`OperatorSettingsStore` — async ``get`` / ``set`` / ``delete``
  for server-context callers (mirrors :class:`NotebooksStore`'s shape:
  async classmethod ``open``, internal ``asyncio.Lock``, one cached
  ``sqlite3.Connection``).
- Module-level **synchronous** helpers: :func:`get_setting`,
  :func:`set_setting`, :func:`get_contact_email`. Each opens its own
  short-lived ``sqlite3.Connection``, applies the durability pragmas,
  and closes — safe to call from synchronous CLI tools without any
  asyncio event-loop hazard.

**Durability** (m2 synthesis FM-1 / FM-2 / FM-4):

Inherits all four ``notebooks.db`` connection pragmas from
:class:`NotebooksStore._open_sync`:
``journal_mode=WAL``, ``synchronous=FULL``, ``fullfsync=ON``,
``isolation_level=None`` (explicit BEGIN/COMMIT). Plus
``busy_timeout=5000`` (5s) to absorb WAL writer contention when the
server is mid-write on ``notebooks_papers`` and the CLI is writing
``operator_settings``.

**PII discipline** (m2 synthesis §3 D6 / FM-4):

The first stored key is ``contact_email`` — operator-identifiable.
:meth:`OperatorSettingsStore.open` (and the sync helpers) chmod
``notebooks.db`` to ``0o600`` IF the file did not previously exist.
A pre-existing file's perms are NEVER retroactively tightened
(operators may intentionally set perms; surprise behaviour would be
worse than the marginal hardening).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from server.application_paths import ApplicationPaths, legacy_source_path

logger = logging.getLogger(__name__)


#: Current ``operator_settings``-table schema version. Tracked
#: independently from :data:`server.notebooks_store.SCHEMA_VERSION`
#: via an in-table ``__schema_version__`` row (NOT
#: ``PRAGMA user_version`` — see module docstring). Incrementing this
#: requires appending a ``current < N`` migration block in
#: :func:`_apply_migrations`.
SCHEMA_VERSION: int = 1

#: Sentinel-row key used to track the ``operator_settings`` table's
#: own schema version inside the table itself. Reserved — must NOT
#: be set / read via the public API (``get``/``set``/``delete`` will
#: refuse it).
_SCHEMA_VERSION_KEY: str = "__schema_version__"

#: Default ``notebooks.db`` path resolution — mirrors
#: :class:`server.config.Config`'s default. CLI tools that don't have
#: a ``Config`` available pass this directly to the sync helpers.
DEFAULT_DB_PATH: Path = legacy_source_path("notebooks_db")
_LEGACY_DEFAULT_DB_PATH = DEFAULT_DB_PATH

#: SQLite ``busy_timeout`` in milliseconds — 5 s window before
#: ``database is locked`` raises. Matches Python's
#: ``sqlite3.connect(timeout=...)`` default per Python 3.12 docs.
_BUSY_TIMEOUT_MS: int = 5000

#: Keys that the public API refuses (reserved for internal
#: bookkeeping). Today: just the schema-version sentinel.
_RESERVED_KEYS: frozenset[str] = frozenset({_SCHEMA_VERSION_KEY})


def _resolve_db_path(db_path: Path | None) -> Path:
    if db_path is not None:
        return db_path
    if DEFAULT_DB_PATH != _LEGACY_DEFAULT_DB_PATH:
        return DEFAULT_DB_PATH
    return ApplicationPaths.resolve().notebooks_db


# ---------------------------------------------------------------------------
# Internal: pragma setup + migration (shared by async + sync paths)
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    """ISO-8601 UTC stamp matching the rest of ``notebooks.db``'s
    timestamps (per :class:`NotebooksStore`'s ``created_at`` /
    ``added_at`` convention)."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply the four connection-scoped pragmas every ``notebooks.db``
    handle MUST set (m2 synthesis §2 — load-bearing facts).

    Mirrors :func:`server.notebooks_store.NotebooksStore.open._open_sync`
    verbatim — diverging here would silently degrade durability on the
    CLI-side connection. Comments preserved from there:

    - ``journal_mode=WAL``: enables concurrent reader (server) +
      writer (CLI).
    - ``synchronous=FULL``: in WAL mode, NORMAL can roll back the last
      committed transaction on power loss; FULL adds a WAL sync after
      every commit → ACID-durable.
    - ``fullfsync=ON``: macOS only. Forces ``fcntl(F_FULLFSYNC)``
      instead of the kernel's deferrable fsync. Connection-scoped (does
      NOT persist), so it MUST be set on every open. Linux no-ops
      this (no F_FULLFSYNC); durability there rests on FULL + plain
      fsync.
    - ``busy_timeout=5000``: 5-second wait window for WAL writer
      contention (m2 synthesis FM-1). Without this, a CLI write
      against a server-busy DB raises ``OperationalError`` immediately.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA fullfsync=ON")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Create / migrate the ``operator_settings`` table to the current
    :data:`SCHEMA_VERSION`.

    Uses the **in-table** ``__schema_version__`` sentinel row instead of
    ``PRAGMA user_version`` (which is file-scoped and owned by
    :class:`NotebooksStore`). Idempotent — calling against a current-
    version table is a no-op.
    """
    # v0 -> v1: initial create. ``CREATE TABLE IF NOT EXISTS`` is
    # idempotent — a re-run against an existing table is a no-op. The
    # subsequent INSERT OR IGNORE seeds the sentinel if (and only if)
    # this is the first migration to write the table.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS operator_settings ("
        "  key         TEXT PRIMARY KEY,"
        "  value       TEXT NOT NULL,"
        "  updated_at  TEXT NOT NULL"
        ")"
    )

    row = conn.execute(
        "SELECT value FROM operator_settings WHERE key = ?",
        (_SCHEMA_VERSION_KEY,),
    ).fetchone()
    current_version = int(row[0]) if row else 0

    if current_version < SCHEMA_VERSION:
        logger.info(
            "OperatorSettingsStore: schema version %d -> %d",
            current_version,
            SCHEMA_VERSION,
        )

    # v0 -> v1: no additional columns; the table itself IS v1. Future
    # migration blocks land here per the m2 synthesis pattern:
    #     if current_version < 2:
    #         conn.execute("ALTER TABLE operator_settings ADD COLUMN ...")
    #     # then unconditionally bump the sentinel below.

    if current_version < SCHEMA_VERSION:
        # ``INSERT OR REPLACE`` doubles as the v0-seed and any
        # subsequent-version bump. The sentinel row is NOT exposed by
        # the public API (see ``_RESERVED_KEYS``) so this is a closed
        # in-table invariant.
        conn.execute(
            "INSERT OR REPLACE INTO operator_settings "
            "(key, value, updated_at) VALUES (?, ?, ?)",
            (_SCHEMA_VERSION_KEY, str(SCHEMA_VERSION), _utc_iso()),
        )


def _open_sync(db_path: Path) -> sqlite3.Connection:
    """Open a fresh synchronous connection to ``db_path`` with the full
    pragma + migration stack applied. The caller owns the connection
    and MUST ``close()`` it.

    On first file creation, the file is created with mode ``0o600``
    via an atomic ``os.open(..., O_CREAT | O_EXCL, 0o600)`` — the file
    holds the operator's email (PII). Pre-existing files are NEVER
    retroactively chmodded (m2 synthesis §3 D6 — operators may have
    set perms intentionally; silent tightening would be a surprise).

    **m2 critique F6 rectification (MEDIUM).** The prior implementation
    did ``path.exists()`` → ``sqlite3.connect`` → conditional chmod,
    which had a TOCTOU race: between the ``exists()`` check and the
    ``connect`` (which auto-creates), another process could pre-create
    the file with different perms, after which our chmod would
    retroactively tighten an existing file — violating the D6
    promise. The atomic ``O_CREAT | O_EXCL`` pattern eliminates the
    race: either WE create the file with 0o600, or it pre-existed
    (``EEXIST`` raised) and we don't touch its perms.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic create-with-mode (m2 critique F6): O_EXCL means the call
    # fails with FileExistsError if the file already exists; the mode
    # arg is applied by the kernel during create. The fd we get back
    # is immediately closed — sqlite3.connect then re-opens via its
    # own path (we couldn't reuse the fd anyway — SQLite owns its
    # connection lifecycle).
    file_created_by_us = False
    try:
        fd = os.open(
            str(db_path),
            os.O_RDWR | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(fd)
        file_created_by_us = True
    except FileExistsError:
        # File pre-existed — leave perms alone per D6.
        pass

    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        check_same_thread=False,
    )
    _apply_pragmas(conn)
    _apply_migrations(conn)

    if not file_created_by_us:
        return conn
    # Belt-and-braces: on platforms where the umask interferes with
    # O_CREAT's mode arg (some exotic filesystems do), explicitly
    # chmod to 0o600. No-op on the happy path where O_EXCL already
    # gave us the right mode.
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        logger.exception(
            "OperatorSettingsStore: chmod 0o600 on %s failed; "
            "operator should verify perms manually",
            db_path,
        )
    return conn


def _check_key(key: str) -> None:
    """Reject reserved keys + non-string keys at the public-API
    boundary. The schema-version sentinel must never be writable from
    outside this module."""
    if not isinstance(key, str):
        raise TypeError(
            f"operator_settings key must be str, got {type(key).__name__}"
        )
    if key in _RESERVED_KEYS:
        raise ValueError(
            f"operator_settings key {key!r} is reserved for internal use"
        )
    if not key:
        raise ValueError("operator_settings key must be non-empty")


# ---------------------------------------------------------------------------
# Synchronous module-level API (for CLI tools — no asyncio dependency)
# ---------------------------------------------------------------------------


def get_setting(
    key: str, db_path: Path | None = None
) -> str | None:
    """Read a single setting; return ``None`` if the key is absent
    OR the underlying file doesn't exist yet (CLI may run before
    ``make init`` has ever populated the store).

    Opens a fresh connection, reads one row, closes. Safe to call
    repeatedly from CLI loops; the WAL + busy_timeout discipline
    means a concurrent server writer doesn't crash the CLI."""
    db_path = _resolve_db_path(db_path)
    _check_key(key)
    if not db_path.exists():
        return None
    conn = _open_sync(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM operator_settings WHERE key = ?",
            (key,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def set_setting(
    key: str, value: str, db_path: Path | None = None
) -> None:
    """Upsert a setting. ``INSERT OR REPLACE`` is idempotent on
    repeated calls; ``updated_at`` is rewritten each call so callers
    can audit when an operator pref was last changed.

    Empty-string values are permitted (operators sometimes clear a
    pref); ``None`` is not — call :func:`delete_setting` to remove."""
    db_path = _resolve_db_path(db_path)
    _check_key(key)
    if not isinstance(value, str):
        raise TypeError(
            f"operator_settings value must be str, got {type(value).__name__}"
        )
    conn = _open_sync(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO operator_settings "
            "(key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, _utc_iso()),
        )
    finally:
        conn.close()


def delete_setting(
    key: str, db_path: Path | None = None
) -> bool:
    """Remove a setting; return ``True`` if a row was deleted,
    ``False`` if the key was already absent. Safe to call against a
    missing DB file."""
    db_path = _resolve_db_path(db_path)
    _check_key(key)
    if not db_path.exists():
        return False
    conn = _open_sync(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM operator_settings WHERE key = ?",
            (key,),
        )
        return cur.rowcount > 0
    finally:
        conn.close()


def get_contact_email(
    db_path: Path | None = None,
) -> str | None:
    """Convenience reader for the canonical ``contact_email`` key.

    Importable directly by ``ingest/`` modules
    (``ingest/inspire_ingest.py``, ``ingest/graph_ingest.py``) without
    requiring the ``tools._notebook_common`` import path — avoids the
    ``ingest/ → tools/`` cross-package import direction the m2
    synthesis §3 D3 flagged."""
    return get_setting("contact_email", db_path)


def get_mineru_bin(
    db_path: Path | None = None,
) -> str | None:
    """Convenience reader for the persisted ``mineru_bin`` path.

    Importable directly by ``ingest/textbook_parser.py`` (mirrors
    :func:`get_contact_email`) so the MinerU Stage-1 parser can resolve its
    binary without an ``ARXMCP_MINERU_BIN`` export on every shell — and
    without the ``ingest/ → tools/`` cross-package import direction. Persisted
    via ``make init MINERU_BIN=…`` / ``tools/notebook_init.py --mineru-bin``
    (ingest-robustness-m1 AC3). Returns ``None`` when unset (or the store
    does not exist yet)."""
    return get_setting("mineru_bin", db_path)


# ---------------------------------------------------------------------------
# Asynchronous class API (for server-context callers)
# ---------------------------------------------------------------------------


class OperatorSettingsStore:
    """Async wrapper around ``operator_settings`` for server callers.

    Mirrors :class:`server.notebooks_store.NotebooksStore`'s shape —
    open via :meth:`open` (async classmethod), all public methods are
    ``async`` and offload SQL via :func:`asyncio.to_thread`, serialized
    through an internal ``asyncio.Lock`` so the cached
    single-threaded ``sqlite3.Connection`` is never raced.

    Server callers should prefer this over the module-level sync
    helpers when they're already in an event-loop context; the sync
    helpers are for CLI tools that run before / outside an event loop.
    """

    def __init__(
        self,
        db_path: Path,
        connection: sqlite3.Connection,
    ) -> None:
        self._db_path = db_path
        self._conn = connection
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: Path | None = None) -> OperatorSettingsStore:
        """Open (or create) the SQLite file at ``db_path``. Applies the
        full pragma + migration stack. Idempotent against a
        current-version file."""

        db_path = _resolve_db_path(db_path)

        def _open() -> sqlite3.Connection:
            return _open_sync(db_path)

        conn = await asyncio.to_thread(_open)
        return cls(db_path=db_path, connection=conn)

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._conn.close)

    async def get(self, key: str) -> str | None:
        _check_key(key)

        def _read() -> str | None:
            row = self._conn.execute(
                "SELECT value FROM operator_settings WHERE key = ?",
                (key,),
            ).fetchone()
            return row[0] if row else None

        async with self._lock:
            return await asyncio.to_thread(_read)

    async def set(self, key: str, value: str) -> None:
        _check_key(key)
        if not isinstance(value, str):
            raise TypeError(
                f"operator_settings value must be str, "
                f"got {type(value).__name__}"
            )

        def _write() -> None:
            self._conn.execute(
                "INSERT OR REPLACE INTO operator_settings "
                "(key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, _utc_iso()),
            )

        async with self._lock:
            await asyncio.to_thread(_write)

    async def delete(self, key: str) -> bool:
        _check_key(key)

        def _delete() -> bool:
            cur = self._conn.execute(
                "DELETE FROM operator_settings WHERE key = ?",
                (key,),
            )
            return cur.rowcount > 0

        async with self._lock:
            return await asyncio.to_thread(_delete)
