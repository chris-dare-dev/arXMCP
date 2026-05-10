"""Tier-1 SQLite persistence (E08_S03).

Tier 1 of the 3-tier retrieval cache is a SQLite-backed exact-query
memo with a 1-hour TTL and a 10K-row cap. The SQLite file persists
across server restarts so Tier-1 entries survive process restarts
within their TTL window. On startup, unexpired rows are loaded into
the in-process LRU mirror that ``server/cache.py`` maintains.

**File layout** lives under ``Config.cache_db_path`` (default
``var/arxmcp/cache/retrieval.db``). Parent directory is created at
``Resources.startup()`` time.

**WAL mode** is enabled at connection time — concurrent readers
during a write are safe (the test fixture and the cache writer can
hit the same file). ``PRAGMA synchronous=NORMAL`` is set because a
cache failure mode is "stale read" not "data loss" — losing the
last few writes on a crash is acceptable per the design constitution
(``.claude/notes/07-multi-agent-caching.md``: *"Cache layer crash /
OOM → Fall through to recompute; log; alert."*).

**Schema versioning.** A ``PRAGMA user_version`` integer guards the
schema. On startup, if the on-disk ``user_version`` is less than
:data:`SCHEMA_VERSION`, the table is dropped and recreated. This is
acceptable for a cache (loss = miss, never correctness failure).

**Async via stdlib.** Stdlib ``sqlite3`` is sync; we offload all
calls via ``asyncio.to_thread`` to keep the event loop unblocked.
This keeps the project's no-new-deps discipline intact (``aiosqlite``
would have been a thin wrapper around the same pattern).

**Corpus-version key invariant.** Every row carries a
``corpus_version`` integer column AND its hash key includes the
corpus version. So a stale entry from corpus_version=N is unreachable
by a corpus_version=N+1 query (the hash is different) AND can be
explicitly purged via :meth:`Tier1Store.purge_other_corpus_versions`
on startup if disk-pressure becomes a concern.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Schema version. Bump this integer (and DROP the table on read)
#: when the schema changes. The on-disk ``PRAGMA user_version`` is
#: compared against this value at open time.
SCHEMA_VERSION: int = 1

#: Hard cap on Tier-1 row count. Per the brief: "SQLite-backed LRU
#: cache, maximum 10,000 entries". Eviction policy: drop the oldest
#: rows by ``expires_at ASC`` when the cap is exceeded on insert.
MAX_ROWS: int = 10_000

#: Default TTL in seconds (1 hour per the brief).
DEFAULT_TTL_SECONDS: float = 3600.0


# ---------------------------------------------------------------------------
# Key derivation (canonical, byte-stable)
# ---------------------------------------------------------------------------


def canonical_query_form(query: str) -> str:
    """Return the canonical form of a query for cache-key derivation.

    Per the brief and ``.claude/notes/07-multi-agent-caching.md``:
    *"canonical_form(query) is query.strip() only — do NOT lowercase,
    do NOT strip punctuation. \\'etale and étale produce different
    lexical matches."*

    The two-key normalization rule (load-bearing): the cache LOOKUP
    key may use aggressive normalization; the actual query passed
    to BM25 / embedder MUST be unchanged. This function returns
    ONLY the lookup-key form.
    """
    return query.strip()


def derive_tier1_key(
    query: str,
    filters: dict[str, Any] | None,
    k: int,
    corpus_version: int,
    *,
    level: str | None = None,
) -> str:
    """Build the Tier-1 cache key.

    The brief specifies the key as
    ``sha256(canonical_form(query) + filters_json + k + corpus_version)``
    but ``search_papers`` accepts an additional ``level`` argument
    (``"theorem" | "section" | "paper"``) whose value materially
    changes the result shape (dedup-by-paper, dedup-by-section, or
    no dedup). Caching across distinct ``level`` values is a
    correctness bug — same query, k, filters, corpus_version but
    different ``level`` produces a DIFFERENT result envelope. We
    therefore include ``level`` as a fifth, optional component of
    the key. ``level=None`` (legacy / non-search-tool callers) is
    encoded distinctly from any string value so a future caller
    that omits the kwarg cannot collide with one that passes it.

    Returned as a 64-character lowercase hex string. The
    ``corpus_version`` integer is mandatory — an old entry keyed to
    one version is unreachable from a later version because the
    hash differs.

    ``filters=None`` is treated as ``{}`` for hash stability — the
    same query with no filters and the same query with explicit
    ``filters={}`` MUST hit the same cache entry.
    """
    canonical = canonical_query_form(query)
    filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))
    # ``level=None`` encodes as the literal string "None" — distinct
    # from any tool-argument string ("theorem", "section", "paper").
    level_token = "None" if level is None else level
    payload = (
        f"{canonical}|{filters_json}|{k}|{corpus_version}|{level_token}"
    ).encode()
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Tier1Store — sync SQLite operations behind asyncio.to_thread
# ---------------------------------------------------------------------------


class Tier1Store:
    """SQLite-backed Tier-1 persistence.

    All public methods are ``async`` and offload sync SQLite I/O to
    the default executor via :func:`asyncio.to_thread`. Construct
    via the :meth:`open` async classmethod which performs the
    schema-version check + WAL pragmas before returning.

    Thread safety: the underlying ``sqlite3.Connection`` is single-
    threaded by default; we serialize access via an internal
    ``asyncio.Lock`` to ensure ``to_thread`` calls do not race on
    the same connection. WAL mode plus serialized writes is the
    documented safe configuration.
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
    async def open(cls, db_path: Path) -> Tier1Store:
        """Open (or create) the SQLite file at ``db_path`` and apply
        WAL + schema migration.

        Idempotent — calling ``open`` against an existing file at the
        current :data:`SCHEMA_VERSION` is a no-op beyond opening the
        connection.
        """
        # Ensure parent directory exists. Cheap; called on every open.
        db_path.parent.mkdir(parents=True, exist_ok=True)

        def _open_sync() -> sqlite3.Connection:
            conn = sqlite3.connect(
                str(db_path),
                isolation_level=None,  # autocommit; we manage transactions
                check_same_thread=False,  # we serialize via asyncio.Lock
            )
            # WAL: concurrent readers OK; one writer at a time. Per
            # SQLite docs, WAL is the recommended mode for cache use.
            conn.execute("PRAGMA journal_mode=WAL")
            # synchronous=NORMAL: SQLite flushes at checkpoint
            # boundaries, not on every commit. Safe for a cache where
            # losing the last few writes on a crash is a miss, not a
            # correctness failure.
            conn.execute("PRAGMA synchronous=NORMAL")

            # Schema-version check + migration.
            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if current_version < SCHEMA_VERSION:
                logger.info(
                    "Tier1Store: schema version %d → %d; dropping existing "
                    "table at %s (cache loss = miss, no correctness impact)",
                    current_version,
                    SCHEMA_VERSION,
                    db_path,
                )
                conn.execute("DROP TABLE IF EXISTS tier1_cache")
                conn.execute(
                    "CREATE TABLE tier1_cache ("
                    "  key            TEXT PRIMARY KEY,"
                    "  value          BLOB NOT NULL,"
                    "  expires_at     REAL NOT NULL,"
                    "  corpus_version INTEGER NOT NULL"
                    ")"
                )
                conn.execute(
                    "CREATE INDEX idx_tier1_expires "
                    "ON tier1_cache(expires_at)"
                )
                conn.execute(
                    "CREATE INDEX idx_tier1_corpus_version "
                    "ON tier1_cache(corpus_version)"
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
                    logger.exception("Tier1Store.close: ignoring close error")

            await asyncio.to_thread(_close_sync)

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    async def get(self, key: str, *, now: float | None = None) -> bytes | None:
        """Return the value blob for ``key``, or ``None`` if absent
        or expired.

        Expired rows are deleted lazily on read (the
        ``expires_at < now`` check + DELETE is atomic per the WAL
        connection's autocommit mode).
        """
        now = now if now is not None else time.time()

        async with self._lock:
            def _get_sync() -> bytes | None:
                row = self._conn.execute(
                    "SELECT value, expires_at FROM tier1_cache WHERE key = ?",
                    (key,),
                ).fetchone()
                if row is None:
                    return None
                value, expires_at = row
                if expires_at < now:
                    # TTL expired; delete and treat as miss. This is
                    # the "lazy eviction" path tracked by
                    # CACHE_EVICTIONS_COUNTER from the cache layer.
                    self._conn.execute(
                        "DELETE FROM tier1_cache WHERE key = ?", (key,)
                    )
                    return None
                return bytes(value)

            return await asyncio.to_thread(_get_sync)

    async def put(
        self,
        key: str,
        value: bytes,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        corpus_version: int,
        now: float | None = None,
    ) -> int:
        """Insert or replace the row for ``key``. Returns the count
        of evicted rows (zero or more) when the table is over the
        :data:`MAX_ROWS` cap after the insert.

        ``corpus_version`` is stored as a separate column for
        operational queries (e.g. purging stale corpus_version rows)
        even though it is also baked into the ``key`` hash.
        """
        now = now if now is not None else time.time()
        expires_at = now + ttl_seconds

        async with self._lock:
            def _put_sync() -> int:
                self._conn.execute(
                    "INSERT OR REPLACE INTO tier1_cache "
                    "(key, value, expires_at, corpus_version) VALUES (?, ?, ?, ?)",
                    (key, value, expires_at, corpus_version),
                )
                # Eviction: if we're over the cap, delete the oldest
                # rows by expires_at ASC. Bounded work per insert.
                count = self._conn.execute(
                    "SELECT COUNT(*) FROM tier1_cache"
                ).fetchone()[0]
                if count > MAX_ROWS:
                    overflow = count - MAX_ROWS
                    self._conn.execute(
                        "DELETE FROM tier1_cache WHERE key IN ("
                        "  SELECT key FROM tier1_cache "
                        "  ORDER BY expires_at ASC LIMIT ?"
                        ")",
                        (overflow,),
                    )
                    return overflow
                return 0

            return await asyncio.to_thread(_put_sync)

    async def load_all_unexpired(
        self, *, now: float | None = None
    ) -> list[tuple[str, bytes, float]]:
        """Return ``[(key, value, expires_at), ...]`` for every
        unexpired row. Used at server startup to rehydrate the
        in-process LRU mirror.

        Expired rows are NOT returned (the in-process mirror should
        not start with already-stale entries) but ALSO not deleted
        here — the next ``get(expired_key)`` will lazy-evict them.
        Bulk cleanup is :meth:`purge_expired`.
        """
        now = now if now is not None else time.time()

        async with self._lock:
            def _load_sync() -> list[tuple[str, bytes, float]]:
                rows = self._conn.execute(
                    "SELECT key, value, expires_at FROM tier1_cache "
                    "WHERE expires_at >= ?",
                    (now,),
                ).fetchall()
                return [(k, bytes(v), e) for k, v, e in rows]

            return await asyncio.to_thread(_load_sync)

    async def purge_expired(self, *, now: float | None = None) -> int:
        """Delete every row with ``expires_at < now``. Returns the
        count of deleted rows. Optional housekeeping — TTL is also
        enforced lazily on read."""
        now = now if now is not None else time.time()

        async with self._lock:
            def _purge_sync() -> int:
                cur = self._conn.execute(
                    "DELETE FROM tier1_cache WHERE expires_at < ?", (now,)
                )
                return cur.rowcount

            return await asyncio.to_thread(_purge_sync)

    async def purge_other_corpus_versions(self, keep_version: int) -> int:
        """Delete every row whose ``corpus_version != keep_version``.

        Optional housekeeping at startup — entries from other corpus
        versions are already unreachable by hash construction (their
        keys differ from any new query's key) but they consume disk.
        Calling this method drops the disk usage to active-corpus
        entries only.

        Returns the count of deleted rows.
        """
        async with self._lock:
            def _purge_sync() -> int:
                cur = self._conn.execute(
                    "DELETE FROM tier1_cache WHERE corpus_version != ?",
                    (keep_version,),
                )
                return cur.rowcount

            return await asyncio.to_thread(_purge_sync)

    async def row_count(self) -> int:
        """Return the current number of rows in the table."""
        async with self._lock:
            def _count_sync() -> int:
                return self._conn.execute(
                    "SELECT COUNT(*) FROM tier1_cache"
                ).fetchone()[0]

            return await asyncio.to_thread(_count_sync)


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "MAX_ROWS",
    "SCHEMA_VERSION",
    "Tier1Store",
    "canonical_query_form",
    "derive_tier1_key",
]
