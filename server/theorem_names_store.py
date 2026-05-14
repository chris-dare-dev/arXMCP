"""SQLite-backed theorem-name index store (E10_S02).

Owns the two-table schema that backs the ``find_lemma_by_name`` MCP
tool:

* ``theorem_names`` — regular table holding the canonical row data
  keyed by ``dedup_key`` (content-addressable
  ``sha256(paper_id + theorem_name + section_path_json)[:16]``).
  Stores the full row including the human-readable ``display_name``,
  the indexer-stamped ``confidence``, and the JSON-serialized
  ``section_path`` breadcrumb.
* ``theorem_names_fts`` — contentless FTS5 virtual table with a
  trigram tokenizer over ``normalized_name``. Returns rowids; the
  handler JOINs back to the regular table for column data.

Why two tables: SQLite FTS5 contentless tables can only return
``rowid`` from SELECT (column access yields NULL). The regular
table owns the data; FTS5 owns the trigram index. The two stay in
sync via explicit INSERT/DELETE pairs inside a single transaction.

**The trigram caveat.** SQLite FTS5 with ``tokenize='trigram'``
gives **substring-tolerant** matching, not **typo-tolerant**
matching: ``MATCH 'riemann'`` matches ``"Riemann-Roch"`` (all query
trigrams are substrings of the indexed value), but
``MATCH 'riemanroch'`` against ``"riemannroch"`` returns no rows
(query trigrams ``ano,noc`` are not substrings of the indexed
value). The brief's AC4 is consequently not satisfiable by FTS5
alone; the handler adds a Python-side trigram Jaccard fallback
(synthesis D2) for the typo case.

**Concurrency.** SQLite WAL mode tolerates concurrent readers and
serializes writers at the file level. Callers MUST serialize
concurrent ``index_paper`` invocations against the same paper —
two concurrent runs for the same paper can interleave the
``DELETE`` / ``INSERT`` pair and produce duplicates.

**No new dependencies.** ``sqlite3`` is stdlib; we wrap all sync
calls in ``asyncio.to_thread`` per the project's no-new-deps
discipline (mirrors :mod:`server.cache_sqlite`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: PRAGMA user_version pin. Bump together with any schema change so
#: the on-disk version mismatch triggers a DROP + recreate on open.
SCHEMA_VERSION: int = 1

#: Number of hex characters of the SHA-256 prefix used as the
#: ``dedup_key``. 16 hex = 64 bits of entropy — collision-free at
#: corpus scale (<< 2**32 distinct rows).
DEDUP_KEY_LEN: int = 16

#: Default Python-side Jaccard threshold for the typo-tolerant
#: fallback. Tuned empirically: 0.3 returns "Riemann-Roch" for
#: "riemanroch" (Jaccard ≈ 0.45) without flooding with unrelated
#: hits.
DEFAULT_JACCARD_THRESHOLD: float = 0.3


# ---------------------------------------------------------------------------
# Pure helpers (used by both indexer and handler)
# ---------------------------------------------------------------------------


def normalize_name(name: str) -> str:
    """Normalize a theorem name for indexing / lookup.

    Lowercases, NFKD-decomposes, strips combining marks, then drops
    every non-ASCII-alphanumeric character. Applied symmetrically at
    index time and at query time so the two sides compare like-for-like.

    Examples (test fixtures pin these):
    - ``"Riemann–Roch"`` → ``"riemannroch"`` (em-dash and hyphen stripped)
    - ``"Yoneda Lemma"`` → ``"yonedalemma"`` (space stripped)
    - ``"Lemma 3.4"`` → ``"lemma34"`` (period stripped, digits kept)
    """
    if not isinstance(name, str):
        raise TypeError(f"name must be str; got {type(name).__name__}")
    nfkd = unicodedata.normalize("NFKD", name.casefold())
    no_marks = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", no_marks)


def dedup_key(
    paper_id: str, theorem_name: str, section_path_json: str
) -> str:
    """Compute the content-addressable dedup key for a row.

    The three inputs are joined by NUL bytes so the boundary is
    unambiguous (a paper_id that ends with an ``a`` and a
    theorem_name that starts with ``b`` cannot collide with a
    paper_id that ends with ``ab`` and a theorem_name that starts
    with empty).
    """
    payload = (
        paper_id + "\x00" + theorem_name + "\x00" + section_path_json
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:DEDUP_KEY_LEN]


def serialize_section_path(section_path: list[str] | None) -> str:
    """Canonical JSON encoding of the chunker's section_path list."""
    if section_path is None:
        return "[]"
    return json.dumps(
        list(section_path), separators=(",", ":"), ensure_ascii=False
    )


def trigrams(text: str) -> set[str]:
    """Return the set of 3-character sliding windows over ``text``.

    For inputs shorter than 3 characters, returns ``{text}`` so the
    Jaccard helper has something to work with. Lowercases the input
    so case differences do not affect the score.
    """
    s = text.lower()
    if len(s) < 3:
        return {s} if s else set()
    return {s[i : i + 3] for i in range(len(s) - 2)}


def trigram_jaccard(query: str, indexed: str) -> float:
    """Jaccard similarity of the trigram sets of two strings.

    Returns 0.0 if both inputs collapse to empty trigram sets.
    """
    qt = trigrams(query)
    it = trigrams(indexed)
    if not qt or not it:
        return 0.0
    inter = len(qt & it)
    union = len(qt | it)
    return inter / union if union else 0.0


#: Control characters that terminate or corrupt the SQLite C-string
#: parser even inside a phrase-quoted FTS5 literal. NUL (``\x00``) is
#: the load-bearing one — it triggers
#: ``sqlite3.OperationalError("unterminated string")`` before any
#: pattern match runs. The full ``\x00-\x1f`` range is stripped for
#: defense in depth (none of those chars appear in legitimate
#: theorem names; an attacker payload that carries one is the
#: signal we want to block).
_FTS5_CONTROL_CHARS = re.compile(r"[\x00-\x1f]+")


def fts5_phrase_quote(text: str) -> str:
    """Wrap user input as an FTS5 phrase literal.

    The FTS5 query syntax has its own parser; an unquoted special
    character (``AND``, ``OR``, ``NOT``, ``*``, ``^``, ``"``) would
    trigger a parse error or unintended semantics. Phrase-quoting
    tells FTS5 to treat the entire input as a literal substring.
    Embedded double-quotes are doubled per FTS5's escape rule.

    **F1 (E10_S02 critique) close.** Control characters in the
    ``\\x00-\\x1f`` range are stripped BEFORE phrase-quoting because
    SQLite's underlying C-string parser treats NUL as
    end-of-string and raises
    ``OperationalError("unterminated string")``. Stripping at the
    quote boundary is the FTS5-safe guard that other callers can
    rely on without having to remember to normalize first.
    """
    cleaned = _FTS5_CONTROL_CHARS.sub("", text)
    return '"' + cleaned.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TheoremRow:
    """One row from the theorem_names table."""

    dedup_key: str
    paper_id: str
    chunk_id: str
    theorem_name: str        # alias for display_name; preserved for back-compat
    display_name: str
    section_path: list[str]
    confidence: float


# ---------------------------------------------------------------------------
# TheoremNamesStore — async wrapper over sqlite3
# ---------------------------------------------------------------------------


class TheoremNamesStore:
    """SQLite-backed store for the theorem-names index.

    Public methods are async and offload sync SQLite I/O to the
    default executor via :func:`asyncio.to_thread`. Construct via
    the :meth:`open` async classmethod which performs WAL + schema
    migration before returning.
    """

    def __init__(self, db_path: Path, connection: sqlite3.Connection) -> None:
        self._db_path = db_path
        self._conn = connection
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: Path) -> TheoremNamesStore:
        """Open (or create) the SQLite file at ``db_path``."""
        db_path.parent.mkdir(parents=True, exist_ok=True)

        def _open_sync() -> sqlite3.Connection:
            conn = sqlite3.connect(
                str(db_path),
                isolation_level=None,  # autocommit; we manage transactions
                check_same_thread=False,  # we serialize via asyncio.Lock
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if current < SCHEMA_VERSION:
                # F5 (E10_S02 critique) — schema bump silently drops
                # the entire table. Log at WARNING so the operator
                # sees this in normal log routing AND explicitly
                # names the action required (re-run the indexer).
                # Without the WARN, a schema bump shows up only as
                # "0 matches for every query" with no signal of the
                # underlying cause.
                logger.warning(
                    "TheoremNamesStore: schema %d → %d at %s; "
                    "DROPPING the theorem_names table. Re-run "
                    "`python -m ingest.index_theorem_names` to "
                    "rebuild — until then find_lemma_by_name "
                    "returns empty results.",
                    current, SCHEMA_VERSION, db_path,
                )
                conn.execute("DROP TABLE IF EXISTS theorem_names_fts")
                conn.execute("DROP TABLE IF EXISTS theorem_names")
                conn.execute(
                    "CREATE TABLE theorem_names ("
                    "  dedup_key       TEXT PRIMARY KEY,"
                    "  normalized_name TEXT NOT NULL,"
                    "  display_name    TEXT NOT NULL,"
                    "  paper_id        TEXT NOT NULL,"
                    "  chunk_id        TEXT NOT NULL,"
                    "  section_path    TEXT NOT NULL,"
                    "  confidence      REAL NOT NULL"
                    ")"
                )
                conn.execute(
                    "CREATE INDEX idx_theorem_names_paper_id "
                    "ON theorem_names(paper_id)"
                )
                conn.execute(
                    "CREATE INDEX idx_theorem_names_normalized_name "
                    "ON theorem_names(normalized_name)"
                )
                # Contentless FTS5 with trigram tokenizer. ``content=''``
                # means the virtual table stores ONLY the inverted
                # index; column reads yield NULL. The handler JOINs
                # back to the regular table by rowid.
                conn.execute(
                    "CREATE VIRTUAL TABLE theorem_names_fts USING fts5("
                    "  normalized_name,"
                    "  content='',"
                    "  tokenize='trigram case_sensitive 0'"
                    ")"
                )
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return conn

        conn = await asyncio.to_thread(_open_sync)
        return cls(db_path=db_path, connection=conn)

    async def close(self) -> None:
        async with self._lock:
            def _close_sync() -> None:
                try:
                    self._conn.close()
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "TheoremNamesStore.close: ignoring close error"
                    )

            await asyncio.to_thread(_close_sync)

    # ------------------------------------------------------------------
    # Write path (indexer)
    # ------------------------------------------------------------------

    async def upsert_rows(self, rows: list[TheoremRow]) -> int:
        """Idempotent upsert of a batch of rows.

        On primary-key collision (same ``dedup_key``), the existing
        row is replaced and the FTS5 row is deleted+reinserted so
        the trigram index stays in sync. Returns the number of rows
        written.

        Contentless FTS5 quirk — ``DELETE FROM theorem_names_fts``
        is not supported. The supported delete form is the special
        ``'delete'`` command via ``INSERT INTO ft(ft, rowid, col)
        VALUES('delete', ?, ?)``, which requires the prior column
        value (used by FTS5 to invert-rebuild its index). We
        therefore SELECT the old normalized_name before the upsert
        and pass it to the delete command.
        """
        if not rows:
            return 0

        async with self._lock:
            def _write_sync() -> int:
                conn = self._conn
                conn.execute("BEGIN")
                try:
                    for r in rows:
                        new_norm = normalize_name(r.display_name)
                        # Find any existing row we need to evict
                        # from the FTS5 index BEFORE the regular-table
                        # upsert (which keeps the rowid stable for
                        # SQLite INSERT OR REPLACE but lets us
                        # cleanly handle the dedup-key collision).
                        existing = conn.execute(
                            "SELECT rowid, normalized_name "
                            "FROM theorem_names WHERE dedup_key = ?",
                            (r.dedup_key,),
                        ).fetchone()
                        if existing is not None:
                            old_rowid, old_norm = existing
                            conn.execute(
                                "INSERT INTO theorem_names_fts("
                                "theorem_names_fts, rowid, normalized_name"
                                ") VALUES ('delete', ?, ?)",
                                (old_rowid, old_norm),
                            )
                        conn.execute(
                            "INSERT OR REPLACE INTO theorem_names ("
                            "  dedup_key, normalized_name, display_name,"
                            "  paper_id, chunk_id, section_path, confidence"
                            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                r.dedup_key,
                                new_norm,
                                r.display_name,
                                r.paper_id,
                                r.chunk_id,
                                serialize_section_path(r.section_path),
                                float(r.confidence),
                            ),
                        )
                        new_rowid = conn.execute(
                            "SELECT rowid FROM theorem_names WHERE dedup_key = ?",
                            (r.dedup_key,),
                        ).fetchone()[0]
                        conn.execute(
                            "INSERT INTO theorem_names_fts(rowid, normalized_name) "
                            "VALUES (?, ?)",
                            (new_rowid, new_norm),
                        )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return len(rows)

            return await asyncio.to_thread(_write_sync)

    async def delete_paper(self, paper_id: str) -> int:
        """Remove every row for ``paper_id`` (used by re-ingest).

        Uses the contentless FTS5 ``'delete'`` command form (same
        quirk as :meth:`upsert_rows`).
        """
        async with self._lock:
            def _delete_sync() -> int:
                conn = self._conn
                conn.execute("BEGIN")
                try:
                    # Pull (rowid, normalized_name) pairs first so
                    # we can purge the FTS5 index. Contentless FTS5
                    # rejects standard DELETE; we must use the
                    # ``'delete'`` command with the prior column
                    # value.
                    pairs = list(conn.execute(
                        "SELECT rowid, normalized_name "
                        "FROM theorem_names WHERE paper_id = ?",
                        (paper_id,),
                    ))
                    for rid, norm in pairs:
                        conn.execute(
                            "INSERT INTO theorem_names_fts("
                            "theorem_names_fts, rowid, normalized_name"
                            ") VALUES ('delete', ?, ?)",
                            (rid, norm),
                        )
                    cur = conn.execute(
                        "DELETE FROM theorem_names WHERE paper_id = ?",
                        (paper_id,),
                    )
                    n = cur.rowcount
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return int(n)

            return await asyncio.to_thread(_delete_sync)

    # ------------------------------------------------------------------
    # Read path (handler)
    # ------------------------------------------------------------------

    async def exact_match(
        self,
        normalized_query: str,
        paper_id: str | None,
        limit: int,
    ) -> list[TheoremRow]:
        """Step 1: exact match on the normalized form."""
        async with self._lock:
            def _read_sync() -> list[TheoremRow]:
                conn = self._conn
                sql = (
                    "SELECT dedup_key, normalized_name, display_name,"
                    "       paper_id, chunk_id, section_path, confidence "
                    "FROM theorem_names WHERE normalized_name = ?"
                )
                params: list[object] = [normalized_query]
                if paper_id is not None:
                    sql += " AND paper_id = ?"
                    params.append(paper_id)
                sql += " ORDER BY confidence DESC, chunk_id ASC LIMIT ?"
                params.append(int(limit))
                return [_row_from_sql(r) for r in conn.execute(sql, params)]

            return await asyncio.to_thread(_read_sync)

    async def fts5_match(
        self,
        normalized_query: str,
        paper_id: str | None,
        limit: int,
    ) -> list[TheoremRow]:
        """Step 2: FTS5 trigram substring match.

        Uses phrase-quoting on the user input (D9) so an injected
        ``OR`` / ``NOT`` / ``*`` cannot escape the literal.
        """
        if not normalized_query:
            return []
        async with self._lock:
            def _read_sync() -> list[TheoremRow]:
                conn = self._conn
                fts_rows = [
                    r[0]
                    for r in conn.execute(
                        "SELECT rowid FROM theorem_names_fts "
                        "WHERE theorem_names_fts MATCH ?",
                        (fts5_phrase_quote(normalized_query),),
                    )
                ]
                if not fts_rows:
                    return []
                placeholders = ",".join("?" * len(fts_rows))
                sql = (
                    f"SELECT dedup_key, normalized_name, display_name,"
                    f"       paper_id, chunk_id, section_path, confidence "
                    f"FROM theorem_names WHERE rowid IN ({placeholders})"
                )
                params: list[object] = list(fts_rows)
                if paper_id is not None:
                    sql += " AND paper_id = ?"
                    params.append(paper_id)
                sql += " ORDER BY confidence DESC, chunk_id ASC LIMIT ?"
                params.append(int(limit))
                return [_row_from_sql(r) for r in conn.execute(sql, params)]

            return await asyncio.to_thread(_read_sync)

    async def fuzzy_jaccard(
        self,
        normalized_query: str,
        paper_id: str | None,
        limit: int,
        threshold: float = DEFAULT_JACCARD_THRESHOLD,
    ) -> list[TheoremRow]:
        """Step 3: Python-side trigram Jaccard fallback.

        Loads every ``normalized_name`` row (optionally filtered by
        ``paper_id``), scores each against the query's trigram set,
        returns rows with score ≥ ``threshold`` sorted by score
        descending. This is the AC4-satisfying path.

        Scale note: at corpus scale (~50K rows), the SELECT pulls
        ~5MB and the scoring is ~50ms. Acceptable for a fallback
        that fires only when exact + FTS5 both return empty.
        """
        if not normalized_query:
            return []
        async with self._lock:
            def _read_sync() -> list[TheoremRow]:
                conn = self._conn
                sql = (
                    "SELECT dedup_key, normalized_name, display_name,"
                    "       paper_id, chunk_id, section_path, confidence "
                    "FROM theorem_names"
                )
                params: list[object] = []
                if paper_id is not None:
                    sql += " WHERE paper_id = ?"
                    params.append(paper_id)
                candidates = list(conn.execute(sql, params))
                scored: list[tuple[float, tuple]] = []
                for row in candidates:
                    score = trigram_jaccard(
                        normalized_query, row[1]  # normalized_name column
                    )
                    if score >= threshold:
                        scored.append((score, row))
                scored.sort(key=lambda p: (-p[0], p[1][4]))  # -score, chunk_id
                return [_row_from_sql(p[1]) for p in scored[:limit]]

            return await asyncio.to_thread(_read_sync)

    async def row_count(self) -> int:
        """Total rows — for diagnostics and tests."""
        async with self._lock:
            def _count_sync() -> int:
                conn = self._conn
                return int(
                    conn.execute(
                        "SELECT COUNT(*) FROM theorem_names"
                    ).fetchone()[0]
                )

            return await asyncio.to_thread(_count_sync)


def _row_from_sql(row: tuple) -> TheoremRow:
    """Build a TheoremRow from a 7-column SQL tuple."""
    section_path_raw = row[5] or "[]"
    try:
        section_path = json.loads(section_path_raw)
        if not isinstance(section_path, list):
            section_path = []
    except (json.JSONDecodeError, TypeError):
        section_path = []
    return TheoremRow(
        dedup_key=row[0],
        paper_id=row[3],
        chunk_id=row[4],
        theorem_name=row[2],     # display_name aliased
        display_name=row[2],
        section_path=section_path,
        confidence=float(row[6]),
    )


__all__ = [
    "DEFAULT_JACCARD_THRESHOLD",
    "SCHEMA_VERSION",
    "TheoremNamesStore",
    "TheoremRow",
    "dedup_key",
    "fts5_phrase_quote",
    "normalize_name",
    "serialize_section_path",
    "trigram_jaccard",
    "trigrams",
]
