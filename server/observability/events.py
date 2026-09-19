"""In-process observability event tier (stage2/arx-a23, WS-A A3).

Closes the load-bearing half of finding 09 §2.E: the server records
rich telemetry but exposes none of it to a browser. This module adds
the missing **query surface primitives**:

- :class:`EventRing` — a bounded, thread-safe ring buffer with a
  monotone sequence number. Two instances ship as module singletons:
  :data:`REQUEST_EVENTS` (gap R1 — per-request records, populated
  from the existing ``register_all`` wrapper + ContextVars) and
  :data:`LOG_EVENTS` (gap R2 — the ring the
  :class:`server.observability.logging_setup.RingBufferLogHandler`
  feeds, POST-``RedactionFilter``).
- :class:`EventBus` — the single multiplexed fan-out for the SSE
  endpoint (gap R8). Topics: ``logs`` / ``requests`` / ``sessions`` /
  ``ingest``. Per-subscriber bounded queues with **drop-oldest**
  semantics: a slow or stalled consumer can never grow server memory
  beyond ``queue max size`` items (AC-A.14); drops are counted per
  subscriber so the stream can emit an explicit gap marker instead of
  silently losing continuity.
- Publish helpers for the four topics, including the additive
  ingest/parse **stage events** (gap R4).

**Threading model.** Appends and publishes may originate off the
event loop (the stdlib logging handler emits from arbitrary threads;
``asyncio.to_thread`` workers log too). ``EventRing`` therefore uses
a ``threading.Lock``; ``EventBus.publish`` routes cross-thread
publishes through ``loop.call_soon_threadsafe`` onto the loop the
lifespan bound via :func:`bind_event_loop`. When no loop is bound
(early startup, plain unit tests) the ring still records — only the
live fan-out is skipped. Ring reads are lock-snapshot copies.

**Polling stays the degraded mode** (AC-A.14): every ring is served
by a plain paged GET endpoint in
:mod:`server.routes.observability`; SSE is an enhancement, never a
requirement.

**Nothing here touches the MCP surface** — no tools, no ``tools/list``
bytes, BP1 intact (the corpus-integrity roadmap explicitly killed a
``get_corpus_status`` TOOL for this exact reason; this event tier is
the sanctioned alternative).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default ring capacities (finding 09 R1 sizes the request ring at
#: 5–10 K). Overridden at lifespan time from ``Config`` via
#: :func:`configure_event_tier`.
DEFAULT_REQUEST_RING_SIZE: int = 5000
DEFAULT_LOG_RING_SIZE: int = 2000

#: Default per-subscriber SSE queue cap (AC-A.14). Small enough that
#: a stalled browser tab holds < ~1 MB of queued JSON; large enough
#: that a healthy consumer never drops under bursty logs.
DEFAULT_QUEUE_CAP: int = 256

#: The closed topic vocabulary of the multiplexed stream (IF-2).
TOPICS: frozenset[str] = frozenset({"logs", "requests", "sessions", "ingest"})

TOPIC_LOGS: str = "logs"
TOPIC_REQUESTS: str = "requests"
TOPIC_SESSIONS: str = "sessions"
TOPIC_INGEST: str = "ingest"

#: Canonical ingest/parse stage vocabulary (gap R4; AC-A.15). The
#: linear ``preflight → mineru → latexml → chunk → embed → index``
#: stepper maps to what each pipeline actually exposes today:
#: the textbook parse pipeline emits live ``mineru`` / ``latexml``
#: stage events (the daemon awaits those two phases directly); the
#: notebook-ingest subprocess is opaque mid-run (one Python process,
#: per-paper fetch→chunk→embed loops), so its ``chunk`` / ``embed``
#: / ``index`` stage completions are emitted at run completion from
#: the parsed run summary. All additive — the tri-state rows and the
#: 2 s htmx poll are untouched.
INGEST_STAGES: tuple[str, ...] = (
    "preflight", "mineru", "latexml", "chunk", "embed", "index",
)


def _utc_ms() -> float:
    """Wall-clock seconds with ms precision (JSON-friendly float)."""
    return round(time.time(), 3)


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce arbitrary payload values to JSON-serializable form
    (``default=str``, the :class:`JsonFormatter` discipline: a
    formatter/publisher must never drop an event because one field
    was exotic)."""
    try:
        return json.loads(json.dumps(payload, default=str, sort_keys=True))
    except (TypeError, ValueError):
        # Pathological (circular refs): degrade to repr-level record.
        return {"unserializable_event": repr(payload)[:512]}


# ---------------------------------------------------------------------------
# EventRing
# ---------------------------------------------------------------------------


class EventRing:
    """Bounded ring of JSON-safe dict events with a monotone ``seq``.

    Thread-safe (``threading.Lock``): appends may come from any
    thread (logging handlers). ``seq`` starts at 1 and never resets
    while the ring is live, so ``since_seq`` cursors survive ring
    wraps — a reader that fell behind detects the gap by the seq
    jump. (:meth:`clear`, a test-only hook with no production
    caller, restarts the counter for inter-test hermeticity.)
    """

    def __init__(self, maxlen: int) -> None:
        self._maxlen = max(1, int(maxlen))
        self._items: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._seq = itertools.count(1)

    @property
    def maxlen(self) -> int:
        return self._maxlen

    def append(self, event: dict[str, Any]) -> int:
        """Append (stamping ``seq`` + ``ts`` if absent); return seq."""
        return self.append_record(event)["seq"]

    def append_record(self, event: dict[str, Any]) -> dict[str, Any]:
        """Append and return the STAMPED stored record (seq + ts).

        Stage-2 integration fix (IF-2 shape parity): publishers must
        fan out the exact record the ring stores — the pre-integration
        code re-built the SSE payload from the caller's UNSTAMPED
        dict, so live frames lacked the ``ts`` the polling twin
        serves, and the SPA's log/request rows crashed formatting an
        undefined timestamp on the real server (caught by the live
        mandated E2E re-run on the integration branch).
        """
        safe = _json_safe(event)
        with self._lock:
            seq = next(self._seq)
            safe["seq"] = seq
            safe.setdefault("ts", _utc_ms())
            self._items.append(safe)
            if len(self._items) > self._maxlen:
                # One-in-one-out in steady state — the slice form only
                # does real work after a maxlen re-configure.
                del self._items[: len(self._items) - self._maxlen]
            return safe

    def snapshot(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        since_seq: int | None = None,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Return ``(items_newest_first, total_in_ring, latest_seq)``.

        ``since_seq`` filters to events strictly newer than the
        cursor (polling catch-up); ``limit``/``offset`` page the
        newest-first view.
        """
        with self._lock:
            items = list(self._items)
        latest_seq = items[-1]["seq"] if items else 0
        if since_seq is not None:
            items = [e for e in items if e["seq"] > since_seq]
        items.reverse()  # newest first
        total = len(items)
        return items[offset : offset + limit], total, latest_seq

    def clear(self) -> None:
        """Reset to pristine state — items AND the ``seq`` counter.

        Test-tier hook (its only callers are
        :func:`reset_event_tier_for_tests` via the autouse conftest
        fixture): cursor monotonicity is a live-process property, but
        tests assert absolute ``seq`` values and must be hermetic in
        any collection order — a cleared ring restarts ``seq`` at 1.
        Verified regression: the full-suite alphabetical order runs
        ``test_observability_api`` (which publishes events) before
        ``test_observability_events``; with an item-only clear the
        latter's ``seq == 1`` asserts fail.
        """
        with self._lock:
            self._items.clear()
            self._seq = itertools.count(1)


# ---------------------------------------------------------------------------
# EventBus — multiplexed fan-out with bounded per-client queues
# ---------------------------------------------------------------------------


@dataclass
class Subscription:
    """One SSE client's view of the bus."""

    topics: frozenset[str]
    queue: asyncio.Queue  # items: (topic, payload_dict)
    dropped: int = 0
    _id: int = field(default=0)

    def take_dropped(self) -> int:
        """Return-and-reset the drop counter (the stream turns a
        non-zero value into an explicit gap-marker frame)."""
        n = self.dropped
        self.dropped = 0
        return n


class EventBus:
    """Topic fan-out with per-subscriber bounded queues, drop-oldest.

    ``publish`` is safe from any thread once :meth:`bind_loop` has
    run; before that it is a counted no-op (the rings still record —
    polling remains complete).
    """

    def __init__(self, *, default_queue_cap: int = DEFAULT_QUEUE_CAP) -> None:
        self._default_queue_cap = default_queue_cap
        self._subscribers: dict[int, Subscription] = {}
        self._next_id = itertools.count(1)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    @property
    def default_queue_cap(self) -> int:
        return self._default_queue_cap

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        """Bind the serving event loop (lifespan startup) or unbind
        with ``None`` (shutdown / tests)."""
        self._loop = loop

    def subscribe(
        self, topics: frozenset[str] | set[str], *, queue_cap: int | None = None
    ) -> Subscription:
        cap = queue_cap if queue_cap is not None else self._default_queue_cap
        sub = Subscription(
            topics=frozenset(topics),
            queue=asyncio.Queue(maxsize=max(1, cap)),
        )
        with self._lock:
            sub._id = next(self._next_id)
            self._subscribers[sub._id] = sub
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            self._subscribers.pop(sub._id, None)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Fan ``payload`` out to every subscriber of ``topic``.

        Never blocks, never raises into the caller. Cross-thread
        publishes hop onto the bound loop via
        ``call_soon_threadsafe``; on-loop publishes dispatch inline.
        """
        if topic not in TOPICS:
            logger.debug("EventBus.publish: unknown topic %r dropped", topic)
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._dispatch(topic, payload)
        else:
            try:
                loop.call_soon_threadsafe(self._dispatch, topic, payload)
            except RuntimeError:
                # Loop shut down between the check and the call.
                return

    def _dispatch(self, topic: str, payload: dict[str, Any]) -> None:
        with self._lock:
            subs = [s for s in self._subscribers.values() if topic in s.topics]
        for sub in subs:
            try:
                sub.queue.put_nowait((topic, payload))
            except asyncio.QueueFull:
                # Drop-oldest (AC-A.14): evict the head, count the
                # drop, enqueue the new item. The queue size is the
                # hard memory bound per client.
                with contextlib.suppress(asyncio.QueueEmpty):  # pragma: no cover — racy edge
                    sub.queue.get_nowait()
                sub.dropped += 1
                with contextlib.suppress(asyncio.QueueFull):  # pragma: no cover — racy edge
                    sub.queue.put_nowait((topic, payload))


# ---------------------------------------------------------------------------
# Module singletons + configuration
# ---------------------------------------------------------------------------

REQUEST_EVENTS: EventRing = EventRing(DEFAULT_REQUEST_RING_SIZE)
LOG_EVENTS: EventRing = EventRing(DEFAULT_LOG_RING_SIZE)
INGEST_EVENTS: EventRing = EventRing(DEFAULT_LOG_RING_SIZE)
BUS: EventBus = EventBus()


def configure_event_tier(
    *,
    request_ring_size: int | None = None,
    log_ring_size: int | None = None,
    sse_queue_cap: int | None = None,
) -> None:
    """Re-size the module singletons from ``Config`` (lifespan
    startup, BEFORE any traffic). Re-creating the rings drops any
    pre-startup contents — acceptable: nothing user-visible has
    happened yet."""
    global REQUEST_EVENTS, LOG_EVENTS, INGEST_EVENTS, BUS
    if request_ring_size is not None and request_ring_size != REQUEST_EVENTS.maxlen:
        REQUEST_EVENTS = EventRing(request_ring_size)
    if log_ring_size is not None:
        if log_ring_size != LOG_EVENTS.maxlen:
            LOG_EVENTS = EventRing(log_ring_size)
        if log_ring_size != INGEST_EVENTS.maxlen:
            INGEST_EVENTS = EventRing(log_ring_size)
    if sse_queue_cap is not None and sse_queue_cap != BUS.default_queue_cap:
        old = BUS
        BUS = EventBus(default_queue_cap=sse_queue_cap)
        BUS.bind_loop(old._loop)


def bind_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Bind (or unbind) the serving loop on the live bus."""
    BUS.bind_loop(loop)


def reset_event_tier_for_tests() -> None:
    """Test hook — clear rings, drop subscribers, unbind the loop."""
    REQUEST_EVENTS.clear()
    LOG_EVENTS.clear()
    INGEST_EVENTS.clear()
    with BUS._lock:
        BUS._subscribers.clear()
    BUS.bind_loop(None)


# ---------------------------------------------------------------------------
# Publish helpers (the seams the rest of the server calls)
# ---------------------------------------------------------------------------


def publish_request_event(event: dict[str, Any]) -> int:
    """Record one per-request event (gap R1) and fan it out.

    Called from ``server.tools._wrap_with_observability`` on every
    tool call, and from the capability / session-cap middlewares on
    short-circuited calls (status ``denied`` / ``cap``) so the
    requests surface shows the whole truth. Never raises.
    """
    try:
        record = REQUEST_EVENTS.append_record(event)
        BUS.publish(TOPIC_REQUESTS, dict(record))
        return record["seq"]
    except Exception:  # noqa: BLE001 — observability must never break requests
        logger.debug("publish_request_event failed", exc_info=True)
        return 0


def publish_log_event(event: dict[str, Any]) -> int:
    """Record one post-redaction log record (gap R2). Called ONLY by
    :class:`server.observability.logging_setup.RingBufferLogHandler`.
    Never raises (the handler additionally guards with handleError)."""
    record = LOG_EVENTS.append_record(event)
    BUS.publish(TOPIC_LOGS, dict(record))
    return record["seq"]


def publish_session_event(event: dict[str, Any]) -> None:
    """Fan out a session-registry delta (topic ``sessions``; gap R3's
    live half). Not ring-buffered — the authoritative snapshot is
    ``GET /api/v1/sessions``; the SSE topic is a change notification."""
    try:
        BUS.publish(TOPIC_SESSIONS, _json_safe(event))
    except Exception:  # noqa: BLE001
        logger.debug("publish_session_event failed", exc_info=True)


def publish_ingest_stage_event(
    *,
    kind: str,
    slug: str,
    stage: str,
    phase: str,
    run_id: int | None = None,
    paper_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> int:
    """Record one ingest/parse stage event (gap R4; AC-A.15).

    ``kind``: ``"ingest"`` (notebook ingest run) or ``"parse"``
    (textbook PDF parse). ``stage``: one of :data:`INGEST_STAGES` or
    the run-level pseudo-stages ``"run"`` / ``"queue"``. ``phase``:
    ``"started" | "finished" | "failed"``. Additive only — no
    existing consumer reads this ring. Never raises.
    """
    event: dict[str, Any] = {
        "kind": kind,
        "slug": slug,
        "stage": stage,
        "phase": phase,
    }
    if run_id is not None:
        event["run_id"] = run_id
    if paper_id is not None:
        event["paper_id"] = paper_id
    if detail:
        event["detail"] = detail
    try:
        record = INGEST_EVENTS.append_record(event)
        BUS.publish(TOPIC_INGEST, dict(record))
        return record["seq"]
    except Exception:  # noqa: BLE001
        logger.debug("publish_ingest_stage_event failed", exc_info=True)
        return 0


__all__ = [
    "BUS",
    "DEFAULT_LOG_RING_SIZE",
    "DEFAULT_QUEUE_CAP",
    "DEFAULT_REQUEST_RING_SIZE",
    "INGEST_EVENTS",
    "INGEST_STAGES",
    "LOG_EVENTS",
    "REQUEST_EVENTS",
    "TOPICS",
    "TOPIC_INGEST",
    "TOPIC_LOGS",
    "TOPIC_REQUESTS",
    "TOPIC_SESSIONS",
    "EventBus",
    "EventRing",
    "Subscription",
    "bind_event_loop",
    "configure_event_tier",
    "publish_ingest_stage_event",
    "publish_log_event",
    "publish_request_event",
    "publish_session_event",
    "reset_event_tier_for_tests",
]
