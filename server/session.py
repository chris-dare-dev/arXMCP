"""Per-session state for retrieval cap enforcement (E08_S04).

Tracks the number of `search_papers` and `get_chunk` calls per MCP
session (keyed by `Mcp-Session-Id`). The :class:`SessionCapMiddleware`
in `server/middleware.py` consults this state on every `tools/call`
request and short-circuits with `RETRIEVAL_CAP_REACHED` once a cap
is reached.

**Why per-session, why these caps.** Originally the E08_S04 brief
(Rule 2): *"maximum 3 retrieval rounds … and maximum 4 chunks
materialized. These caps prevent runaway retrieval loops and bound
the token budget."* The MCP `Mcp-Session-Id` is the canonical key: it
is server-issued (`uuid4().hex`) and the
`StreamableHTTPSessionManager` validates it on every request — a
client cannot spoof *another* session's counter.

**These caps are cost control, NOT a security boundary**
(agent-platform-m1). The distinction is load-bearing and was blurred
by the original framing:

- A client cannot spoof *another* session's counter, but it does not
  need to. Two bypasses, both **known, admitted, and unpatched**:
  **(b)** rotating to a fresh server-issued id resets both counters
  to zero at no cost. That one is inherent to per-session accounting
  without client identity; closing it needs an authentication axis
  this loopback-only server does not have.

  A previous **(a)** claimed that omitting `Mcp-Session-Id` skips
  cap enforcement outright. **That is not reachable** (issue #474):
  the MCP layer rejects a session-less `tools/*` call with HTTP 400
  ("Missing session ID") before `SessionCapMiddleware` is consulted,
  so the middleware's own "if absent, skip" branch is dead for the
  paths the cap protects. Measured, not argued. The claim is removed
  rather than softened because a security comment that overstates an
  attack path sends the next maintainer to defend something that is
  already closed, and lends false weight to the one bypass that IS
  real.
- The actual anti-abuse control is the per-session hourly ceiling
  (:data:`MAX_CALLS_PER_HOUR`, E13_S04 Threat 4), which covers ALL
  tools rather than the two tracked here. It shares the same
  rotate-the-session-id bypass.
- Therefore: raising these caps does **not** widen a security
  boundary, because they were never one. It trades a larger
  per-session token budget for not rejecting legitimate interactive
  work. The Threat-4 posture is unchanged — see
  ``.claude/docs/security-threat-4-audit.md``.

**In-memory only.** Counters reset on server restart. Per the
project's caching note: *"Caching is performance, not correctness."*

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
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Final

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cap constants — module-level so tests can monkeypatch lower values
# ---------------------------------------------------------------------------

#: Maximum number of `search_papers` tool calls per MCP session.
#: The cap is N successful calls; the (N+1)th is rejected.
#:
#: **agent-platform-m1 (D4-R07): raised 3 -> 30.** The legacy value
#: came from the E08_S04 brief AC (*"a session that calls
#: `search_papers` four times receives `RETRIEVAL_CAP_REACHED` on the
#: fourth call"*), which was written for a scripted 2-round
#: proof-chain fan-out, not for interactive use. Three searches is
#: below the floor of a single real research question, so the cap was
#: firing on legitimate work rather than on runaway loops.
#:
#: Overridable via ``ARXMCP_MAX_SEARCH_PAPERS_CALLS`` — see
#: :func:`configure_caps`.
MAX_SEARCH_PAPERS_CALLS: int = 30

#: Maximum number of `get_chunk` tool calls per MCP session.
#: **agent-platform-m1: raised 4 -> 100**, same rationale.
#: Overridable via ``ARXMCP_MAX_GET_CHUNK_CALLS``.
MAX_GET_CHUNK_CALLS: int = 100

#: Hard cap on the registry size. LRU eviction kicks in when adding
#: a new session would exceed this. Matches the Tier-1 cache cap.
MAX_REGISTRY_SIZE: int = 10_000

#: Tool names that participate in cap accounting. Other tools
#: (`get_definitions`, `find_lemma_by_name`, `cite_neighbors`,
#: `find_equation`) are not counted — their token impact is small
#: and the brief does not name them.
TOOLS_WITH_CAPS: Final[dict[str, str]] = {
    "search_papers": "search_papers",
    "get_chunk": "get_chunk",
}

# ---------------------------------------------------------------------------
# E13_S04 — Hourly rate-limit constants (Threat 4)
# ---------------------------------------------------------------------------

#: Sliding-window length in seconds for the hourly rate limit.
#: Pinned at one hour per the design note in
#: `.claude/notes/08-security-observability-ops.md` § Threat 4:
#: *"max 1000 per hour. Configurable."*
HOURLY_WINDOW_SECONDS: int = 3600

#: Maximum tool calls per hour per session — applies to ALL tools,
#: not just the retrieval-tracked ones in :data:`TOOLS_WITH_CAPS`.
#: An adversary in a retry loop calling any tool 1500 times in an
#: hour is the Threat-4 surface this cap closes (E13_S04 D1).
#: Per the design note: *"max 1000 per hour."*
MAX_CALLS_PER_HOUR: int = 1000


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
    #: Sliding window of timestamps for ALL tool calls in the last
    #: :data:`HOURLY_WINDOW_SECONDS`. Used by
    #: :func:`check_hourly_rate_limit` (E13_S04 Threat 4) to enforce
    #: the 1000/hour cap across every tool name. Entries older than
    #: the window are pruned lazily on each access. Bounded above by
    #: ``MAX_CALLS_PER_HOUR + a small fudge`` — the rejection path
    #: does NOT append, so the deque cannot exceed ``MAX_CALLS_PER_HOUR``
    #: in steady state.
    call_timestamps: deque[float] = field(default_factory=deque)


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


async def check_both_caps(
    state: SessionState,
    tool_name: str,
    now: float | None = None,
    n: int = 1,
) -> tuple[str, int, int]:
    """Atomically check the per-tool retrieval cap AND the hourly
    rate limit under a SINGLE lock acquisition (E13_S04 F1 rect).

    Neither counter is mutated if EITHER cap rejects the call.
    Resolves the budget-leak bug where the previous middleware
    incremented ``state.search_count`` on per-tool allow, then
    rejected the same call on hourly cap — leaving the retrieval
    budget spent on a request that never executed retrieval work.

    Returns ``(verdict, current_count, limit)`` where ``verdict`` is
    one of:

    - ``"allowed"`` — both caps passed; per-tool counter incremented
      (for ``search_papers``/``get_chunk``); hourly timestamp
      appended. ``current_count`` is the hourly count after the
      append; ``limit`` is :data:`MAX_CALLS_PER_HOUR`.
    - ``"per_tool_rejected"`` — per-tool cap is at limit. NEITHER
      counter mutated. ``current_count`` is the per-tool
      attempted count; ``limit`` is the per-tool cap.
    - ``"hourly_rejected"`` — per-tool cap allows but hourly cap is
      at limit. NEITHER counter mutated. ``current_count`` is the
      hourly attempted count; ``limit`` is
      :data:`MAX_CALLS_PER_HOUR`.

    The two existing functions :func:`check_and_increment` and
    :func:`check_hourly_rate_limit` remain available for unit tests
    and for code paths that need only one cap. ``SessionCapMiddleware``
    uses this compound function exclusively to avoid the F1 budget
    leak.

    ``n`` is the number of per-tool units this call consumes
    (agent-platform-t-batch-chunk-fetch, #83): a batched ``get_chunk``
    of N ids costs N against the per-tool cap, not 1, so a caller cannot
    escape the retrieval budget by folding many fetches into one request.
    The batch is accounted WHOLESALE: if ``count + n`` would exceed the
    limit the entire batch is rejected (no partial serve), consistent
    with the single-call semantics. The hourly cap stays request-grained
    (a batch is one request = one timestamp) — it bounds request rate,
    which a single batched call does not inflate.
    """
    if now is None:
        now = time.time()

    async with state.lock:
        # --- Step 1: per-tool retrieval cap (no mutation yet) ---
        per_tool_limit = 0
        per_tool_count = 0
        if tool_name == "search_papers":
            per_tool_limit = MAX_SEARCH_PAPERS_CALLS
            per_tool_count = state.search_count
            if per_tool_count + n > per_tool_limit:
                return "per_tool_rejected", per_tool_count + n, per_tool_limit
        elif tool_name == "get_chunk":
            per_tool_limit = MAX_GET_CHUNK_CALLS
            per_tool_count = state.chunk_count
            if per_tool_count + n > per_tool_limit:
                return "per_tool_rejected", per_tool_count + n, per_tool_limit
        # Tools not in TOOLS_WITH_CAPS have no per-tool cap; fall
        # through to the hourly check.

        # --- Step 2: hourly rate limit (prune old, no mutation yet) ---
        cutoff = now - HOURLY_WINDOW_SECONDS
        while state.call_timestamps and state.call_timestamps[0] < cutoff:
            state.call_timestamps.popleft()
        hourly_count = len(state.call_timestamps)
        if hourly_count >= MAX_CALLS_PER_HOUR:
            return "hourly_rejected", hourly_count + 1, MAX_CALLS_PER_HOUR

        # --- Step 3: BOTH passed — commit BOTH atomically ---
        if tool_name == "search_papers":
            state.search_count += n
        elif tool_name == "get_chunk":
            state.chunk_count += n
        state.call_timestamps.append(now)
        return "allowed", hourly_count + 1, MAX_CALLS_PER_HOUR


async def check_hourly_rate_limit(
    state: SessionState, now: float | None = None
) -> tuple[bool, int, int]:
    """Atomically check the hourly rate limit and, if allowed,
    record the call.

    E13_S04 Threat-4 closure. Distinct axis from
    :func:`check_and_increment`:

    - `check_and_increment` enforces per-TOOL lifetime caps
      (`MAX_SEARCH_PAPERS_CALLS=3`, `MAX_GET_CHUNK_CALLS=4`) for
      retrieval-loop containment. Covers 2 of 7 tools.
    - This function enforces a per-SESSION rolling-hour cap
      (`MAX_CALLS_PER_HOUR=1000`) for resource-exhaustion
      containment. Covers ALL tools.

    Both checks fire on every `tools/call` request through
    :class:`server.middleware.SessionCapMiddleware`; the request is
    allowed only if BOTH return ``allowed=True``.

    **Sliding window via deque.** ``state.call_timestamps`` is a
    deque of float timestamps. Each call prunes entries older than
    ``now - HOURLY_WINDOW_SECONDS`` from the left, then either
    appends (allowed) or returns the rejection without appending.

    **Returns** ``(allowed, current_count_or_attempt, limit)``:

    - ``allowed=True``: post-prune count is < cap. Timestamp
      appended. ``current_count`` is the post-append count.
    - ``allowed=False``: post-prune count is >= cap. Timestamp
      NOT appended (the rejection does not consume cap budget).
      ``current_count`` is the attempted count (current + 1).

    Args:
        state: The session's :class:`SessionState`.
        now: Optional explicit wall-clock seconds (for tests).
            Defaults to ``time.time()``.

    Returns:
        ``(allowed, current_count_or_attempt, limit)``.
    """
    if now is None:
        now = time.time()
    async with state.lock:
        # Prune timestamps older than the rolling window.
        cutoff = now - HOURLY_WINDOW_SECONDS
        while state.call_timestamps and state.call_timestamps[0] < cutoff:
            state.call_timestamps.popleft()

        current = len(state.call_timestamps)
        limit = MAX_CALLS_PER_HOUR
        if current >= limit:
            # Over cap — reject without consuming budget. The
            # attempted-count (current + 1) is what the caller
            # reports back to the agent for observability.
            return False, current + 1, limit

        state.call_timestamps.append(now)
        return True, current + 1, limit


def configure_caps(config: Any) -> None:
    """Apply the operator-configured per-tool caps from ``config``
    (agent-platform-m1).

    Called once from ``server.main.create_app`` after ``Config`` is
    resolved. Rebinding the module globals — rather than threading the
    limits through :func:`check_both_caps`'s signature — is deliberate:
    :data:`MAX_SEARCH_PAPERS_CALLS` and :data:`MAX_GET_CHUNK_CALLS` are
    read as globals inside the cap functions precisely so tests can
    ``monkeypatch.setattr`` them, and that contract predates this
    milestone. Same mechanism, one more writer.

    ``config`` is typed loosely to keep :mod:`server.session` free of a
    :mod:`server.config` import — session state is imported by
    middleware on a hot path and has no other config coupling.

    Not idempotent-by-value across differing configs: the last caller
    wins. Only ``create_app`` calls it, and a process builds one app.
    """
    global MAX_SEARCH_PAPERS_CALLS, MAX_GET_CHUNK_CALLS
    MAX_SEARCH_PAPERS_CALLS = config.max_search_papers_calls
    MAX_GET_CHUNK_CALLS = config.max_get_chunk_calls
    logger.debug(
        "session caps configured: search_papers=%d get_chunk=%d",
        MAX_SEARCH_PAPERS_CALLS,
        MAX_GET_CHUNK_CALLS,
    )


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
    "HOURLY_WINDOW_SECONDS",
    "MAX_CALLS_PER_HOUR",
    "MAX_GET_CHUNK_CALLS",
    "MAX_REGISTRY_SIZE",
    "MAX_SEARCH_PAPERS_CALLS",
    "TOOLS_WITH_CAPS",
    "SessionState",
    "check_and_increment",
    "check_both_caps",
    "check_hourly_rate_limit",
    "configure_caps",
    "get_or_create_session",
    "get_session_count",
    "reset_session_state_for_tests",
]
