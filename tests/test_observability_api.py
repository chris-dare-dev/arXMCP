"""Observability read-API tests (stage2/arx-a23, WS-A A3).

Coverage map (acceptance criteria → test class):

  AC                                                    Test class
  ────────────────────────────────────────────────────────────────────
  AC-A.11 GET /api/v1/requests serves R1 events;
          a tool call lands in the buffer                TestRequestsEndpoint
  AC-A.12 /api/v1/logs/tail serves POST-redaction
          records (handler-ordering proof)               TestLogsTailRedaction
  AC-A.13 GET /api/v1/sessions read-only snapshot
          with cap-remaining                             TestSessionsEndpoint
  AC-A.14 SSE multiplexing, queue caps, drop-oldest,
          gap markers; polling retained                  TestSseStream
  AC-A.15 ingest stage events additive                   TestIngestEventsEndpoint
  (A2)    GET /api/v1/tool-calls audit reader            TestToolCallsEndpoint
  R5      phase timings ride the request event           TestPhaseTimings
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.observability import events as ev
from server.observability.logging_setup import (
    install_ring_buffer_handler,
    remove_ring_buffer_handler,
)
from server.routes.observability import router as obs_router
from server.routes.observability import sse_event_generator


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(obs_router, prefix="/api/v1")
    return TestClient(app)


class TestFormatVersionParity:
    def test_pinned_to_the_api_v1_constant(self) -> None:
        """The observability router duplicates the /api/v1
        format_version int (avoiding a routes->routes import); this
        pin is the paired drift guard its comment promises."""
        from server.routes.api_v1 import API_V1_FORMAT_VERSION
        from server.routes.capabilities import (
            FORMAT_VERSION as CAP_FORMAT_VERSION,
        )
        from server.routes.observability import (
            FORMAT_VERSION as OBS_FORMAT_VERSION,
        )

        assert OBS_FORMAT_VERSION == API_V1_FORMAT_VERSION
        assert CAP_FORMAT_VERSION == API_V1_FORMAT_VERSION


# ---------------------------------------------------------------------------
# AC-A.11 — request events
# ---------------------------------------------------------------------------


class TestRequestsEndpoint:
    def test_empty_ring_serves_empty_page(self) -> None:
        r = _client().get("/api/v1/requests")
        assert r.status_code == 200
        body = r.json()
        assert body["format_version"] == 1
        assert body["items"] == []
        assert body["total"] == 0
        assert body["latest_seq"] == 0

    def test_tool_call_appears_in_buffer(self) -> None:
        """AC-A.11: a tool call made during the test appears in the
        buffer — through the REAL ``_wrap_with_observability`` seam
        (the register_all wrapper), not a synthetic append."""
        from server.tools import _wrap_with_observability

        async def fake_handler(query: str, k: int = 5) -> dict:
            return {"results": [], "corpus_version": 1}

        wrapped = _wrap_with_observability("search_papers", fake_handler)
        asyncio.run(wrapped(query="bridgeland stability", k=5))

        r = _client().get("/api/v1/requests")
        body = r.json()
        assert body["total"] == 1
        event = body["items"][0]
        assert event["tool"] == "search_papers"
        assert event["status"] == "ok"
        assert event["k"] == 5
        assert event["latency_ms"] >= 0
        assert event["cache_layer"] in ("tier1", "tier2", "tier3", "miss")
        assert event["profile"] == "default"
        assert "result_bytes" in event

    def test_error_calls_recorded_with_error_code(self) -> None:
        from server.tools import _wrap_with_observability

        async def boom(query: str) -> dict:
            raise ValueError("bad input")

        wrapped = _wrap_with_observability("search_papers", boom)

        async def _run() -> None:
            import contextlib

            with contextlib.suppress(ValueError):
                await wrapped(query="x")

        asyncio.run(_run())
        body = _client().get("/api/v1/requests").json()
        assert body["items"][0]["status"] == "error"
        assert body["items"][0]["error_code"] == "ValueError"

    def test_since_seq_polling_cursor(self) -> None:
        # seq is process-monotone (survives ring clears by design, so
        # cursors from before a wrap detect the gap) — use the REAL
        # seq values, exactly as a polling client would.
        seqs = [
            ev.publish_request_event(
                {"tool": "get_chunk", "status": "ok", "i": i}
            )
            for i in range(4)
        ]
        body = _client().get(f"/api/v1/requests?since_seq={seqs[1]}").json()
        assert body["total"] == 2
        assert [e["i"] for e in body["items"]] == [3, 2]
        assert body["latest_seq"] == seqs[3]


# ---------------------------------------------------------------------------
# AC-A.12 — log tail redaction ordering
# ---------------------------------------------------------------------------


class TestLogsTailRedaction:
    def test_redactable_field_absent_from_tail_at_info(self, caplog) -> None:
        """Emit a log WITH a redactable field through a normal child
        logger; the tail output must be the REDACTED form — proving
        the RedactionFilter runs on the ring handler (the R2 ordering
        contract)."""
        install_ring_buffer_handler()
        try:
            with caplog.at_level(logging.INFO):
                logging.getLogger("server.test.redaction").info(
                    "search served", extra={"query": "SECRET-QUERY-TEXT"},
                )
        finally:
            remove_ring_buffer_handler()

        body = _client().get("/api/v1/logs/tail").json()
        assert body["total"] >= 1
        record = next(
            e for e in body["items"] if e.get("message") == "search served"
        )
        assert "query" not in record, (
            "redactable field leaked into the log ring — RedactionFilter "
            "ordering is broken (AC-A.12)"
        )
        assert record["level"] == "INFO"

    def test_debug_records_keep_sensitive_fields(self, caplog) -> None:
        """At DEBUG the operator explicitly opted into full disclosure
        (the RedactionFilter's documented level gate)."""
        install_ring_buffer_handler()
        try:
            with caplog.at_level(logging.DEBUG):
                logging.getLogger("server.test.redaction").debug(
                    "debug detail", extra={"query": "visible-at-debug"},
                )
        finally:
            remove_ring_buffer_handler()
        body = _client().get("/api/v1/logs/tail").json()
        record = next(
            e for e in body["items"] if e.get("message") == "debug detail"
        )
        assert record.get("query") == "visible-at-debug"

    def test_level_facet_filter(self, caplog) -> None:
        install_ring_buffer_handler()
        try:
            with caplog.at_level(logging.INFO):
                logging.getLogger("server.test.facets").info("info line")
                logging.getLogger("server.test.facets").warning("warn line")
        finally:
            remove_ring_buffer_handler()
        body = _client().get("/api/v1/logs/tail?level=warning").json()
        messages = [e.get("message") for e in body["items"]]
        assert "warn line" in messages
        assert "info line" not in messages

    def test_install_is_idempotent(self) -> None:
        import logging as _logging

        from server.observability.logging_setup import RingBufferLogHandler

        h1 = install_ring_buffer_handler()
        h2 = install_ring_buffer_handler()
        try:
            assert h1 is h2
            ring_handlers = [
                h for h in _logging.getLogger().handlers
                if isinstance(h, RingBufferLogHandler)
            ]
            assert len(ring_handlers) == 1
            # The redaction filter is attached at install time.
            from server.observability.log_filter import RedactionFilter

            assert any(isinstance(f, RedactionFilter) for f in h1.filters)
        finally:
            remove_ring_buffer_handler()


# ---------------------------------------------------------------------------
# AC-A.13 — session snapshot
# ---------------------------------------------------------------------------


class TestSessionsEndpoint:
    def test_snapshot_reports_caps_remaining_and_roles(self) -> None:
        from server.session import (
            check_both_caps,
            get_or_create_session,
            note_session_role,
        )

        sid = "abcdef0123456789abcdef0123456789"

        async def _run() -> None:
            state = await get_or_create_session(sid)
            await check_both_caps(state, "search_papers")
            await check_both_caps(state, "search_papers")
            await check_both_caps(state, "get_chunk")
            await note_session_role(sid, "sketcher")

        asyncio.run(_run())
        body = _client().get("/api/v1/sessions").json()
        assert body["total"] == 1
        row = body["items"][0]
        assert row["session_id_prefix"] == sid[:16]
        assert row["roles_seen"] == ["sketcher"]
        assert row["counts"]["search_papers"] == 2
        assert row["caps"]["search_papers"] == {
            "limit": 3, "used": 2, "remaining": 1,
        }
        assert row["caps"]["get_chunk"]["remaining"] == 3
        assert row["hourly"]["used"] == 3
        assert row["hourly"]["limit"] == 1000

    def test_profile_cap_overrides_reflected_in_snapshot(self) -> None:
        from server.session import check_both_caps, get_or_create_session

        sid = "1234567890abcdef1234567890abcdef"

        async def _run() -> None:
            state = await get_or_create_session(sid)
            await check_both_caps(
                state, "search_papers", per_tool_limits={"search_papers": 5}
            )

        asyncio.run(_run())
        row = _client().get("/api/v1/sessions").json()["items"][0]
        assert row["caps"]["search_papers"]["limit"] == 5
        assert row["caps"]["search_papers"]["remaining"] == 4

    def test_registry_stays_module_private(self) -> None:
        """The endpoint serves a projection; mutating the response
        must not touch the registry (read-only contract)."""
        from server.session import get_or_create_session, get_session_count

        sid = "feedfacefeedfacefeedfacefeedface"
        asyncio.run(get_or_create_session(sid))
        client = _client()
        body = client.get("/api/v1/sessions").json()
        body["items"][0]["counts"]["search_papers"] = 999
        again = client.get("/api/v1/sessions").json()
        assert again["items"][0]["counts"]["search_papers"] == 0
        assert get_session_count() == 1


# ---------------------------------------------------------------------------
# AC-A.15 — ingest stage events endpoint
# ---------------------------------------------------------------------------


class TestIngestEventsEndpoint:
    def test_stage_events_served_with_slug_filter(self) -> None:
        ev.publish_ingest_stage_event(
            kind="ingest", slug="nb-a", stage="preflight", phase="finished",
            run_id=7,
        )
        ev.publish_ingest_stage_event(
            kind="parse", slug="nb-b", stage="mineru", phase="started",
        )
        client = _client()
        body = client.get("/api/v1/ingest-events").json()
        assert body["total"] == 2
        body = client.get("/api/v1/ingest-events?slug=nb-a").json()
        assert body["total"] == 1
        assert body["items"][0]["stage"] == "preflight"
        assert body["items"][0]["run_id"] == 7


# ---------------------------------------------------------------------------
# Audit reader
# ---------------------------------------------------------------------------


class TestToolCallsEndpoint:
    def test_503_when_store_unbound(self) -> None:
        r = _client().get("/api/v1/tool-calls")
        assert r.status_code == 503

    def test_serves_audit_rows(self, tmp_path: Path) -> None:
        from server.audit import (
            ToolCallAuditStore,
            ToolCallRecord,
            set_audit_store,
        )

        async def _seed() -> ToolCallAuditStore:
            store = await ToolCallAuditStore.open(tmp_path / "a.db")
            await store.append(ToolCallRecord(
                tool="search_papers", outcome="ok", profile="default",
            ))
            return store

        store = asyncio.run(_seed())
        set_audit_store(store)
        try:
            body = _client().get("/api/v1/tool-calls").json()
            assert body["total"] == 1
            assert body["items"][0]["tool"] == "search_papers"
        finally:
            set_audit_store(None)
            asyncio.run(store.close())


# ---------------------------------------------------------------------------
# AC-A.14 — the multiplexed SSE stream
# ---------------------------------------------------------------------------


class TestSseStream:
    def test_unknown_topic_is_422(self) -> None:
        r = _client().get("/api/v1/events/stream?topics=bogus")
        assert r.status_code == 422
        assert "bogus" in r.json()["detail"]

    def test_generator_emits_ready_event_and_keepalive_frames(self) -> None:
        async def _run() -> None:
            ev.bind_event_loop(asyncio.get_running_loop())
            sub = ev.BUS.subscribe({"logs", "requests"})
            ev.BUS.publish("logs", {"message": "hello"})
            gen = sse_event_generator(sub, keepalive_seconds=0.05)
            try:
                ready = await gen.__anext__()
                assert ready.startswith("event: ready\n")
                assert '"logs"' in ready and '"requests"' in ready
                frame = await gen.__anext__()
                assert frame.startswith("event: logs\n")
                assert '"message": "hello"' in frame
                # Queue drained → next frame is the keepalive comment.
                keepalive = await gen.__anext__()
                assert keepalive == ": keepalive\n\n"
            finally:
                await gen.aclose()
            assert ev.BUS.subscriber_count() == 0, (
                "generator close must unsubscribe (no leaked queues)"
            )

        asyncio.run(_run())

    def test_generator_multiplexes_topics_on_one_stream(self) -> None:
        async def _run() -> None:
            ev.bind_event_loop(asyncio.get_running_loop())
            sub = ev.BUS.subscribe(ev.TOPICS)
            ev.BUS.publish("requests", {"tool": "get_chunk"})
            ev.BUS.publish("ingest", {"stage": "mineru"})
            ev.BUS.publish("sessions", {"session_id_prefix": "ab"})
            gen = sse_event_generator(sub, keepalive_seconds=0.05)
            try:
                await gen.__anext__()  # ready
                names = [
                    (await gen.__anext__()).split("\n", 1)[0]
                    for _ in range(3)
                ]
                assert names == [
                    "event: requests", "event: ingest", "event: sessions",
                ]
            finally:
                await gen.aclose()

        asyncio.run(_run())

    def test_gap_marker_emitted_after_drop_oldest(self) -> None:
        async def _run() -> None:
            ev.configure_event_tier(sse_queue_cap=4)
            try:
                ev.bind_event_loop(asyncio.get_running_loop())
                sub = ev.BUS.subscribe({"requests"})
                for i in range(10):  # overflow: 6 drops
                    ev.BUS.publish("requests", {"i": i})
                gen = sse_event_generator(sub, keepalive_seconds=0.05)
                try:
                    await gen.__anext__()  # ready
                    gap = await gen.__anext__()
                    assert gap.startswith("event: gap\n")
                    assert '"dropped": 6' in gap
                    first_kept = await gen.__anext__()
                    assert '"i": 6' in first_kept, "oldest were dropped"
                finally:
                    await gen.aclose()
            finally:
                ev.configure_event_tier(sse_queue_cap=ev.DEFAULT_QUEUE_CAP)

        asyncio.run(_run())

    def test_polling_endpoints_remain_the_degraded_mode(self) -> None:
        """AC-A.14: polling stays functional — every SSE topic has a
        GET twin serving the same data."""
        client = _client()
        ev.publish_request_event({"tool": "search_papers", "status": "ok"})
        ev.publish_ingest_stage_event(
            kind="ingest", slug="nb", stage="run", phase="started",
        )
        assert client.get("/api/v1/requests").json()["total"] == 1
        assert client.get("/api/v1/ingest-events").json()["total"] == 1
        assert client.get("/api/v1/sessions").status_code == 200
        assert client.get("/api/v1/logs/tail").status_code == 200


# ---------------------------------------------------------------------------
# R5 — phase timings ride the request event
# ---------------------------------------------------------------------------


class TestPhaseTimings:
    def test_child_span_seams_record_phase_ms_without_otel(self) -> None:
        """The embed/ann child-span helpers time their bodies into the
        request event even with tracing disabled (no OTel endpoint) —
        the R5 'always-on lightweight phase timing' requirement."""
        from server.observability.tracing import span_ann, span_embed
        from server.tools import _wrap_with_observability

        async def handler(query: str) -> dict:
            with span_embed("bge-m3", "deadbeef"):
                await asyncio.sleep(0.01)
            with span_ann(k=5):
                await asyncio.sleep(0.01)
            return {"ok": True}

        wrapped = _wrap_with_observability("search_papers", handler)
        asyncio.run(wrapped(query="q"))
        items, _, _ = ev.REQUEST_EVENTS.snapshot(limit=1)
        phases = items[0].get("phases_ms")
        assert phases is not None
        assert phases["embed"] >= 5
        assert phases["ann"] >= 5
