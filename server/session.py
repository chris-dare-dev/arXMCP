"""Per-session state for retrieval cap enforcement (E08_S04).

Tracks the number of `search_papers` and `get_chunk` calls per MCP
session (keyed by `Mcp-Session-Id`). The :class:`SessionCapMiddleware`
in `server/middleware.py` consults this state on every `tools/call`
request and short-circuits with `RETRIEVAL_CAP_REACHED` once a cap
is reached.

**Why per-session, why these caps.** The brief (E08_S04 Rule 2):
*"The server enforces a per-session hard cap: maximum 3 retrieval
rounds (calls to `search_papers`) and maximum 4 chunks materialized
(calls to `get_chunk`). These caps prevent runaway retrieval loops
and bound the token budget."* The MCP `Mcp-Session-Id` is the
canonical key: it is server-issued (`uuid4().hex`) and the
`StreamableHTTPSessionManager` validates it on every request — a
client cannot spoof a different session's counter.

**In-memory only.** Counters reset on server restart. The brief is
explicit; per the project's caching note: *"Caching is performance,
not correctness."* The cap is a defensive ceiling, not a security
contract.

**LRU eviction at 10K sessions.** Long-running servers accumulate
abandoned session entries. We bound growth at 10K (matches the
Tier-1 cache convention) by evicting the oldest entries on insert
(keyed by `created_at`).

**Thread-/concurrency safety.** Each :class:`SessionState` carries
its own `asyncio.Lock`. Concurrent tool calls from the same session
serialize on this lock for the counter increment; sessions DO NOT
serialize on each other (the registry-level operations use a
separate lock and are O(1)).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Final

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cap constants — module-level so tests can monkeypatch lower values
# ---------------------------------------------------------------------------

#: Maximum number of `search_papers` tool calls per MCP session.
#: The brief AC: *"A session that calls `search_papers` four times
#: receives `RETRIEVAL_CAP_REACHED` on the fourth call."* So the
#: cap is 3 successful calls; the 4th is rejected.
MAX_SEARCH_PAPERS_CALLS: int = 3

#: Maximum number of `get_chunk` tool calls per MCP session.
#: The brief AC: *"A session that calls `get_chunk` five times
#: receives `RETRIEVAL_CAP_REACHED` on the fifth call."* So the
#: cap is 4 successful calls; the 5th is rejected.
MAX_GET_CHUNK_CALLS: int = 4

#: Hard cap on the registry size. LRU eviction kicks in when adding
#: a new session would exceed this. Matches the Tier-1 cache cap.
MAX_REGISTRY_SIZE: int = 10_000

#: Tool names that participate in cap accounting. Other tools
#: (`get_definitions`, `find_lemma_by_name`, `get_citations`,
#: `find_equation`) are not counted — their token impact is small
#: and the brief does not name them.
TOOLS_WITH_CAPS: Final[dict[str, str]] = {
    "search_papers": "search_papers",
    "get_chunk": "get_chunk",
}


# ---------------------------------------------------------------------------
# SessionState dataclass
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    """Per-MCP-session retrieval-cap counters.

    A new instance is created lazily on first observation of a new
    `mcp-session-id`. The instance lives in the module-level
    registry until evicted (LRU at 10K sessions, or explicit reset
    via :func:`reset_session_state_for_tests`).
    """

    session_id: str
    search_count: int = 0
    chunk_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    #: Per-session lock guarding counter increments. Concurrent tool
    #: calls from the same session (e.g., a single agent fanning two
    #: `get_chunk` calls in parallel) serialize on this lock.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# ---------------------------------------------------------------------------
# Module-level registry — singleton, dict-of-SessionState
# ---------------------------------------------------------------------------

#: The session registry. ``OrderedDict`` so we can LRU-evict via
#: ``popitem(last=False)``. Insertion order matches creation time.
_SESSIONS: OrderedDict[str, SessionState] = OrderedDict()

#: Registry-level lock guarding the dict structure (lookups +
#: inserts + evictions). Operations under this lock are O(1) so it
#: never contends meaningfully.
_REGISTRY_LOCK: asyncio.Lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_or_create_session(session_id: str) -> SessionState:
    """Return the :class:`SessionState` for ``session_id``, creating
    a fresh one if it does not exist.

    Updates ``last_seen_at`` on every call. Triggers LRU eviction
    when the registry is full.
    """
    async with _REGISTRY_LOCK:
        existing = _SESSIONS.get(session_id)
        if existing is not None:
            existing.last_seen_at = time.time()
            # Move to the end (most-recently-used) so LRU eviction
            # picks the genuinely-oldest unused entry.
            _SESSIONS.move_to_end(session_id)
            return existing

        # New session — evict if at cap. ``popitem(last=False)``
        # removes the least-recently-used entry.
        while len(_SESSIONS) >= MAX_REGISTRY_SIZE:
            evicted_id, _evicted = _SESSIONS.popitem(last=False)
            logger.info(
                "SessionState registry full (cap=%d); evicting "
                "least-recently-used session %s...",
                MAX_REGISTRY_SIZE, evicted_id[:16],
            )

        new_state = SessionState(session_id=session_id)
        _SESSIONS[session_id] = new_state
        return new_state


async def check_and_increment(
    state: SessionState, tool_name: str
) -> tuple[bool, int, int]:
    """Atomically check the cap for ``tool_name`` and, if not
    exceeded, increment the per-session counter.

    Returns ``(allowed, new_count, limit)``:

    - ``allowed=True``: the call is within the cap; ``new_count`` is
      the post-increment value (the call has been "spent" against
      the cap), ``limit`` is the configured cap.
    - ``allowed=False``: the call is OVER the cap; ``new_count`` is
      the rejected attempt count (current count + 1, NOT
      incremented in the state — i.e. ``state.search_count`` stays
      at the cap value and the rejection is at attempt
      ``cap + N``).

    The function holds the per-session lock for the entire
    check+increment so two concurrent calls from the same session
    cannot both pass the check before either increments.

    ``tool_name`` is matched against :data:`TOOLS_WITH_CAPS`. Any
    name not in that dict short-circuits to ``(True, 0, 0)`` — no
    cap accounting for non-retrieval tools.
    """
    if tool_name not in TOOLS_WITH_CAPS:
        return True, 0, 0

    async with state.lock:
        if tool_name == "search_papers":
            limit = MAX_SEARCH_PAPERS_CALLS
            current = state.search_count
            if current >= limit:
                # Over cap — reject. Return the attempted count
                # without incrementing (so the caller can report
                # how many attempts have happened).
                return False, current + 1, limit
            state.search_count += 1
            return True, state.search_count, limit
        elif tool_name == "get_chunk":
            limit = MAX_GET_CHUNK_CALLS
            current = state.chunk_count
            if current >= limit:
                return False, current + 1, limit
            state.chunk_count += 1
            return True, state.chunk_count, limit
        else:
            # Defensive: TOOLS_WITH_CAPS lists this name but the
            # branch is missing. Shouldn't happen.
            return True, 0, 0


def get_session_count() -> int:
    """Return the current number of tracked sessions (for tests +
    debug)."""
    return len(_SESSIONS)


def reset_session_state_for_tests() -> None:
    """Test hook — drop every tracked session.

    Used by the autouse `_reset_session_state_for_tests` fixture in
    `tests/conftest.py` so each test starts with an empty registry.
    Mirrors :func:`server.cache.reset_cache_for_tests` discipline.
    """
    _SESSIONS.clear()


__all__ = [
    "MAX_GET_CHUNK_CALLS",
    "MAX_REGISTRY_SIZE",
    "MAX_SEARCH_PAPERS_CALLS",
    "TOOLS_WITH_CAPS",
    "SessionState",
    "check_and_increment",
    "get_or_create_session",
    "get_session_count",
    "reset_session_state_for_tests",
]
