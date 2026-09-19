"""``/api/v1`` observability read-APIs (stage2/arx-a23, WS-A A3).

Implements the query surface for finding 09 §2.E gaps R1–R3, R7, R8:

- ``GET  /api/v1/requests``       — request-event ring, paged (R1; AC-A.11)
- ``GET  /api/v1/logs/tail``      — post-redaction log ring snapshot (R2; AC-A.12)
- ``GET  /api/v1/sessions``       — read-only session registry snapshot
  with cap-remaining (R3/R7; AC-A.13)
- ``GET  /api/v1/ingest-events``  — additive ingest/parse stage events (R4)
- ``GET  /api/v1/tool-calls``     — the append-only audit store, paged
  (the authz-trail consumer of the A2 store)
- ``GET  /api/v1/events/stream``  — ONE multiplexed SSE endpoint
  (topics: logs / requests / sessions / ingest) with per-client queue
  caps and drop-oldest semantics (R8; AC-A.14). Interface Artifact
  IF-2 for WS-B.

Everything here is **read-only, loopback-bound, JSON (or SSE), and
in-scope for the issue-#9 security-audit amendment** (WS-0 owns the
draft). Redaction is preserved at source — the log ring only ever
sees records that already passed ``RedactionFilter`` (handler-level
install; see ``logging_setup.install_ring_buffer_handler``), and this
module never re-derives from raw.

Polling is the retained degraded mode (AC-A.14): every SSE topic has
a GET twin; a consumer that never opens the stream loses liveness,
not data (the rings are the source of truth; ``since_seq`` cursors
make polling gap-free within ring capacity).

SSE frame format (IF-2)::

    event: <topic>
    data: {"seq": N, ...}

    : keepalive          (comment frame every ~15 s of silence)
    event: gap
    data: {"dropped": N} (explicit marker after drop-oldest overflow)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from server.observability import events as ev

logger = logging.getLogger(__name__)

router = APIRouter(tags=["observability"])

#: Mirrors ``server.routes.api_v1.API_V1_FORMAT_VERSION`` — every JSON
#: body on the /api/v1 surface carries it (imported constant would
#: create a routes→routes dependency for one int; duplicating with a
#: paired test is the house pattern for cross-module pins).
FORMAT_VERSION: int = 1

_MAX_PAGE_LIMIT: int = 500
_DEFAULT_PAGE_LIMIT: int = 100

#: Seconds of silence after which the SSE generator emits a keepalive
#: comment frame (proxies + browsers drop idle connections).
SSE_KEEPALIVE_SECONDS: float = 15.0


def _page_envelope(
    items: list[dict[str, Any]], *, total: int, limit: int, offset: int,
    latest_seq: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
    if latest_seq is not None:
        body["latest_seq"] = latest_seq
    return body


# ---------------------------------------------------------------------------
# R1 — request events
# ---------------------------------------------------------------------------


@router.get("/requests")
async def list_request_events(
    limit: int = Query(default=_DEFAULT_PAGE_LIMIT, ge=1, le=_MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    since_seq: int | None = Query(default=None, ge=0),
) -> dict[str, Any]:
    """Last-N request events, newest first (gap R1; AC-A.11).

    ``since_seq`` returns only events strictly newer than the cursor —
    the polling degraded mode's gap-free catch-up (within ring
    capacity; a seq jump larger than the ring means events aged out).
    """
    items, total, latest_seq = ev.REQUEST_EVENTS.snapshot(
        limit=limit, offset=offset, since_seq=since_seq
    )
    return _page_envelope(
        items, total=total, limit=limit, offset=offset, latest_seq=latest_seq
    )


# ---------------------------------------------------------------------------
# R2 — log tail (snapshot half; the SSE topic is the live half)
# ---------------------------------------------------------------------------


@router.get("/logs/tail")
async def logs_tail(
    limit: int = Query(default=_DEFAULT_PAGE_LIMIT, ge=1, le=_MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    since_seq: int | None = Query(default=None, ge=0),
    level: str | None = Query(default=None),
) -> dict[str, Any]:
    """Snapshot of the in-process log ring (gap R2; AC-A.12).

    Every record here passed ``RedactionFilter`` BEFORE entering the
    ring (handler-level filter — the ordering contract in
    ``logging_setup``). ``level`` filters case-insensitively on the
    record's level name (a facet, not a query language).
    """
    # Over-fetch when a level filter applies, then trim: the ring
    # snapshot is cheap (list copy) and level-filtered pagination
    # over a 2K ring does not warrant an indexed store.
    fetch_limit = limit if level is None else ev.LOG_EVENTS.maxlen
    items, total, latest_seq = ev.LOG_EVENTS.snapshot(
        limit=fetch_limit, offset=0 if level else offset, since_seq=since_seq
    )
    if level is not None:
        wanted = level.strip().upper()
        items = [e for e in items if str(e.get("level", "")).upper() == wanted]
        total = len(items)
        items = items[offset : offset + limit]
    return _page_envelope(
        items, total=total, limit=limit, offset=offset, latest_seq=latest_seq
    )


# ---------------------------------------------------------------------------
# R3/R7 — session registry snapshot
# ---------------------------------------------------------------------------


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(default=_DEFAULT_PAGE_LIMIT, ge=1, le=_MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Read-only projection of the MCP session registry with per-cap
    remaining counts (gaps R3/R7; AC-A.13). The registry itself stays
    module-private in :mod:`server.session` — this endpoint serializes
    a point-in-time copy and never mutates state."""
    from server.session import snapshot_sessions  # noqa: PLC0415

    rows = snapshot_sessions()
    return _page_envelope(
        rows[offset : offset + limit],
        total=len(rows), limit=limit, offset=offset,
    )


# ---------------------------------------------------------------------------
# R4 — ingest/parse stage events (polling twin of the `ingest` topic)
# ---------------------------------------------------------------------------


@router.get("/ingest-events")
async def list_ingest_events(
    limit: int = Query(default=_DEFAULT_PAGE_LIMIT, ge=1, le=_MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    since_seq: int | None = Query(default=None, ge=0),
    slug: str | None = Query(default=None),
) -> dict[str, Any]:
    """Additive ingest/parse stage events (gap R4; AC-A.15). The
    legacy tri-state poll surfaces are untouched — this ring is a new,
    parallel read model."""
    fetch_limit = limit if slug is None else ev.INGEST_EVENTS.maxlen
    items, total, latest_seq = ev.INGEST_EVENTS.snapshot(
        limit=fetch_limit, offset=0 if slug else offset, since_seq=since_seq
    )
    if slug is not None:
        items = [e for e in items if e.get("slug") == slug]
        total = len(items)
        items = items[offset : offset + limit]
    return _page_envelope(
        items, total=total, limit=limit, offset=offset, latest_seq=latest_seq
    )


# ---------------------------------------------------------------------------
# Audit-store reader (A2's `tool_calls`, the authz-trail consumer)
# ---------------------------------------------------------------------------


@router.get("/tool-calls")
async def list_tool_calls(
    limit: int = Query(default=_DEFAULT_PAGE_LIMIT, ge=1, le=_MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Newest-first page over the append-only ``tool_calls`` audit
    store (AC-A.9's read side). 503 while the store is not yet bound
    (startup) — a probe-friendly signal, not an error state."""
    from server.audit import get_audit_store  # noqa: PLC0415

    store = get_audit_store()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="tool_calls audit store is not available yet (startup)",
        )
    rows = await store.tail(limit=limit, offset=offset)
    total = await store.count()
    return _page_envelope(rows, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# R8 — the ONE multiplexed SSE endpoint
# ---------------------------------------------------------------------------


def _sse_frame(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, sort_keys=True, default=str)}\n\n"


async def sse_event_generator(
    sub: ev.Subscription,
    *,
    keepalive_seconds: float = SSE_KEEPALIVE_SECONDS,
):
    """Yield SSE frames from one subscription until the client
    disconnects (generator close) — factored out of the route so
    tests can drive it directly without a streaming HTTP client.

    Emits: an initial ``ready`` frame naming the subscribed topics
    (and the current ring cursors, so a client can immediately poll
    any gap); one frame per bus item; a ``gap`` frame whenever the
    subscriber's drop-oldest counter is non-zero; ``: keepalive``
    comments during silence.
    """
    try:
        yield _sse_frame(
            "ready",
            {
                "topics": sorted(sub.topics),
                "cursors": {
                    "requests": ev.REQUEST_EVENTS.snapshot(limit=0)[2],
                    "logs": ev.LOG_EVENTS.snapshot(limit=0)[2],
                    "ingest": ev.INGEST_EVENTS.snapshot(limit=0)[2],
                },
            },
        )
        while True:
            try:
                topic, payload = await asyncio.wait_for(
                    sub.queue.get(), timeout=keepalive_seconds
                )
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            dropped = sub.take_dropped()
            if dropped:
                # Drop-oldest fired while this client lagged: name the
                # gap explicitly (finding 09 L1 error-state design).
                yield _sse_frame("gap", {"dropped": dropped})
            yield _sse_frame(topic, payload)
    finally:
        ev.BUS.unsubscribe(sub)


@router.get("/events/stream")
async def events_stream(
    topics: str = Query(default="logs,requests,sessions,ingest"),
) -> StreamingResponse:
    """The single multiplexed live stream (gap R8; AC-A.14; IF-2).

    ``topics`` is a comma-separated subset of
    ``logs,requests,sessions,ingest``; unknown names are a 422 (a
    typo'd topic silently delivering nothing would be a debugging
    trap). Per-client queue cap + drop-oldest are enforced in
    :class:`server.observability.events.EventBus` — a stalled
    consumer's server-side footprint is bounded by the queue cap.

    The response is exempt from ``BodySizeCapMiddleware`` (the stream
    is unbounded by design — see the segment-exact carve-out in
    ``server/main.py::_is_exempt_path``; flagged for the issue-#9
    scope amendment).
    """
    requested = frozenset(
        t.strip() for t in topics.split(",") if t.strip()
    )
    if not requested:
        requested = ev.TOPICS
    unknown = requested - ev.TOPICS
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"unknown SSE topic(s) {sorted(unknown)}; valid topics: "
                f"{sorted(ev.TOPICS)}"
            ),
        )
    sub = ev.BUS.subscribe(requested)
    return StreamingResponse(
        sse_event_generator(sub),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Defensive: some reverse proxies buffer without this.
            # Loopback-only today, but the header costs nothing.
            "X-Accel-Buffering": "no",
        },
    )


__all__ = [
    "FORMAT_VERSION",
    "SSE_KEEPALIVE_SECONDS",
    "router",
    "sse_event_generator",
]
