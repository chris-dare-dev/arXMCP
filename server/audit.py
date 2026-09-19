"""Append-only ``tool_calls`` audit store (stage2/arx-a23, WS-A A2).

One row per MCP tool call — allowed, errored, capability-denied, or
cap-rejected (AC-A.9). The store is simultaneously the authz audit
trail and an observability event source (target-architecture §6:
"one store, two consumers").

Design:

- **Dedicated SQLite file** (``Config.audit_db_path``, default
  ``var/arxmcp/cache/tool_calls.db``) — NOT ``notebooks.db``. Audit
  appends fire on every tool call; co-residing with the notebooks
  store would put a hot writer on the operator-CRUD file. WAL +
  ``busy_timeout`` pragmas mirror
  :mod:`server.operator_settings` — the shared durability discipline.
- **Append-only API.** The only mutation is :meth:`ToolCallAuditStore.append`;
  the only deletion is the internal ring-bound trim (oldest rows
  beyond ``max_rows`` — AC-A.9: "insert N+1 over the cap evicts
  oldest"). There is no update, no user-facing delete.
- **Sanitize-passed text.** The optional ``args_summary`` (a bounded
  digest of the call arguments — today: the query string) passes
  through :func:`sanitize_audit_text` before storage: absolute-path
  prefixes are redacted to ``var/arxmcp/`` (the
  :mod:`server.ingest_tracker` FM-4 discipline), the Threat-2 literal
  injection markers are stripped unconditionally (unlike the
  env-gated retrieval sanitizer — an audit row is at-rest operator
  data, so always-on costs nothing), and the result is truncated.
- **Session ids are stored as 16-char prefixes**, matching the
  logging discipline in :class:`server.middleware.SessionCapMiddleware`
  (``session_id[:16]``); the full id never lands at rest.
- **Token values never appear here** (AC-A.10) — the writer only ever
  receives profile NAMES from
  :data:`server.capabilities.current_profile_name`.
- **Failure discipline:** the module-level :func:`append_tool_call`
  never raises into a request path — a failed audit write logs WARN
  and returns ``False``. Observability code must never take the
  server down; the append is also skipped (returns ``False``) when
  no store is bound (tests without a lifespan; early startup).

The file is chmod'd 0o600 on first creation (query digests are
operator-adjacent data) via the same atomic ``O_CREAT | O_EXCL``
pattern as :func:`server.operator_settings._open_sync`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default row cap for the ring bound. Mirrors the 10K session-registry
#: / Tier-1 cache convention. Overridden by ``Config.audit_max_rows``.
DEFAULT_MAX_ROWS: int = 10_000

#: Outcome vocabulary — frozen; tests and consumers switch on these.
OUTCOME_OK: str = "ok"
OUTCOME_ERROR: str = "error"
OUTCOME_DENIED: str = "denied"
OUTCOME_CAP: str = "cap"

#: Bound on the stored ``args_summary`` text, in characters (post-
#: sanitize truncation).
ARGS_SUMMARY_MAX_CHARS: int = 256

#: Stored session-id prefix length — matches the middleware's
#: ``session_id[:16]`` log discipline.
SESSION_ID_PREFIX_LEN: int = 16

#: SQLite busy_timeout, ms — mirrors ``operator_settings``.
_BUSY_TIMEOUT_MS: int = 5000

#: Absolute-path prefix scrub, str domain — the peer of
#: ``server.parse_tracker._ABS_PATH_PREFIX_RE`` (same pattern, same
#: FM-4 rationale). Replaces everything from the first path separator
#: up to and including ``var/arxmcp/`` with the bare relative form.
_ABS_PATH_PREFIX_RE: re.Pattern[str] = re.compile(
    r"[/\\][\w /\\.\-]*?var[/\\]arxmcp[/\\]"
)

#: Threat-2 literal injection markers stripped from audit text
#: unconditionally. Same byte-literal list as
#: :mod:`server.observability.sanitize` (which is env-gated for the
#: RETRIEVAL path; the audit path is always-on — see module docstring).
_INJECTION_LITERALS: tuple[str, ...] = (
    "<|system|>",
    "[INST]",
    "<|im_start|>",
)


def sanitize_audit_text(text: str, max_chars: int = ARGS_SUMMARY_MAX_CHARS) -> str:
    """Sanitize free text bound for an audit row.

    Pipeline (order matters, mirroring
    :func:`server.ingest_tracker.prepare_stderr_tail`):
    1. redact absolute-path prefixes down to ``var/arxmcp/``;
    2. strip the Threat-2 literal injection markers;
    3. truncate to ``max_chars``.

    No HTML escape: audit rows are served as JSON (the ``/api/v1``
    surface), never interpolated into templates.
    """
    text = _ABS_PATH_PREFIX_RE.sub("var/arxmcp/", text)
    for literal in _INJECTION_LITERALS:
        text = text.replace(literal, "")
    return text[:max_chars]


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


# ---------------------------------------------------------------------------
# Row shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """One audit row, pre-insert. Field set per AC-A.9 + target-arch §6."""

    tool: str
    outcome: str  # ok | error | denied | cap
    profile: str
    ts: str | None = None  # ISO-8601 UTC; None = stamp at append
    request_id: str | None = None
    session_id: str | None = None  # full id accepted; prefix stored
    role: str | None = None
    notebook: str | None = None
    latency_ms: float | None = None
    cache_tier: str | None = None
    result_bytes: int | None = None
    error_code: str | None = None
    args_summary: str | None = None  # sanitized at append


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def _open_sync(db_path: Path) -> sqlite3.Connection:
    """Open + migrate the audit DB (atomic 0o600 create; WAL pragmas).

    Mirrors :func:`server.operator_settings._open_sync` — see that
    docstring for the TOCTOU rationale on the O_EXCL create."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        fd = os.open(str(db_path), os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        created = True
    except FileExistsError:
        pass
    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tool_calls ("
        "  id            INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  ts            TEXT NOT NULL,"
        "  request_id    TEXT,"
        "  session_id    TEXT,"
        "  profile       TEXT NOT NULL,"
        "  role          TEXT,"
        "  tool          TEXT NOT NULL,"
        "  notebook      TEXT,"
        "  latency_ms    REAL,"
        "  cache_tier    TEXT,"
        "  result_bytes  INTEGER,"
        "  outcome       TEXT NOT NULL,"
        "  error_code    TEXT,"
        "  args_summary  TEXT"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_calls_id_desc ON tool_calls(id DESC)"
    )
    if created:
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            logger.exception("audit store: chmod 0o600 on %s failed", db_path)
    return conn


_ROW_COLUMNS = (
    "id", "ts", "request_id", "session_id", "profile", "role", "tool",
    "notebook", "latency_ms", "cache_tier", "result_bytes", "outcome",
    "error_code", "args_summary",
)


class ToolCallAuditStore:
    """Async append-only audit store. Shape mirrors
    :class:`server.operator_settings.OperatorSettingsStore` (async
    classmethod ``open``, internal lock, ``asyncio.to_thread`` SQL)."""

    def __init__(
        self, db_path: Path, connection: sqlite3.Connection, max_rows: int
    ) -> None:
        self._db_path = db_path
        self._conn = connection
        self._max_rows = max(1, int(max_rows))
        self._lock = asyncio.Lock()

    @classmethod
    async def open(
        cls, db_path: Path, *, max_rows: int = DEFAULT_MAX_ROWS
    ) -> ToolCallAuditStore:
        conn = await asyncio.to_thread(_open_sync, db_path)
        return cls(db_path=db_path, connection=conn, max_rows=max_rows)

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._conn.close)

    async def append(self, record: ToolCallRecord) -> int:
        """Insert one row; trim the ring; return the new row id."""
        ts = record.ts or _utc_iso()
        session_prefix = (
            record.session_id[:SESSION_ID_PREFIX_LEN]
            if record.session_id
            else None
        )
        args_summary = (
            sanitize_audit_text(record.args_summary)
            if record.args_summary
            else None
        )

        def _insert() -> int:
            cur = self._conn.execute(
                "INSERT INTO tool_calls "
                "(ts, request_id, session_id, profile, role, tool, notebook,"
                " latency_ms, cache_tier, result_bytes, outcome, error_code,"
                " args_summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ts,
                    record.request_id,
                    session_prefix,
                    record.profile,
                    record.role,
                    record.tool,
                    record.notebook,
                    record.latency_ms,
                    record.cache_tier,
                    record.result_bytes,
                    record.outcome,
                    record.error_code,
                    args_summary,
                ),
            )
            row_id = int(cur.lastrowid or 0)
            # Ring bound: evict oldest rows beyond max_rows. Keyed on
            # the monotone AUTOINCREMENT id, so "oldest" is exact.
            self._conn.execute(
                "DELETE FROM tool_calls WHERE id <= "
                "(SELECT MAX(id) FROM tool_calls) - ?",
                (self._max_rows,),
            )
            return row_id

        async with self._lock:
            return await asyncio.to_thread(_insert)

    async def tail(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return the newest rows first (id DESC), paged."""

        def _query() -> list[dict[str, Any]]:
            cur = self._conn.execute(
                "SELECT id, ts, request_id, session_id, profile, role, tool,"
                " notebook, latency_ms, cache_tier, result_bytes, outcome,"
                " error_code, args_summary "
                "FROM tool_calls ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            return [dict(zip(_ROW_COLUMNS, row, strict=True)) for row in cur.fetchall()]

        async with self._lock:
            return await asyncio.to_thread(_query)

    async def count(self) -> int:
        def _query() -> int:
            row = self._conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()
            return int(row[0])

        async with self._lock:
            return await asyncio.to_thread(_query)


# ---------------------------------------------------------------------------
# Module singleton (lifespan-bound, mirrors server.tools.set_resources)
# ---------------------------------------------------------------------------

_AUDIT_STORE: ToolCallAuditStore | None = None


def set_audit_store(store: ToolCallAuditStore | None) -> None:
    """Bind (or unbind with ``None``) the live audit store."""
    global _AUDIT_STORE
    _AUDIT_STORE = store


def get_audit_store() -> ToolCallAuditStore | None:
    return _AUDIT_STORE


def reset_audit_store_for_tests() -> None:
    set_audit_store(None)


async def append_tool_call(record: ToolCallRecord) -> bool:
    """Best-effort append — the ONLY entry point request paths use.

    Returns ``True`` when a row landed; ``False`` when no store is
    bound or the write failed (WARN logged). Never raises.
    """
    store = _AUDIT_STORE
    if store is None:
        return False
    try:
        await store.append(record)
    except Exception:  # noqa: BLE001 — audit must never break a request
        logger.warning(
            "tool_calls audit append failed (tool=%s outcome=%s); "
            "the call itself is unaffected",
            record.tool, record.outcome, exc_info=True,
        )
        return False
    return True


__all__ = [
    "ARGS_SUMMARY_MAX_CHARS",
    "DEFAULT_MAX_ROWS",
    "OUTCOME_CAP",
    "OUTCOME_DENIED",
    "OUTCOME_ERROR",
    "OUTCOME_OK",
    "SESSION_ID_PREFIX_LEN",
    "ToolCallAuditStore",
    "ToolCallRecord",
    "append_tool_call",
    "get_audit_store",
    "reset_audit_store_for_tests",
    "sanitize_audit_text",
    "set_audit_store",
]
