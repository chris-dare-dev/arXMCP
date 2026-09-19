"""Event-tier unit tests (stage2/arx-a23, WS-A A3 — gaps R1/R8).

Covers :class:`EventRing` (bounded, monotone seq, since_seq cursors),
:class:`EventBus` (topic fan-out, per-client queue caps, drop-oldest,
slow-consumer memory bound — AC-A.14's unit half), the cross-thread
publish path, and the module-level publish helpers.
"""

from __future__ import annotations

import asyncio
import threading

from server.observability import events as ev
from server.observability.events import EventBus, EventRing


class TestEventRing:
    def test_seq_monotone_and_ts_stamped(self) -> None:
        ring = EventRing(10)
        s1 = ring.append({"a": 1})
        s2 = ring.append({"a": 2})
        assert (s1, s2) == (1, 2)
        items, total, latest = ring.snapshot(limit=10)
        assert total == 2 and latest == 2
        assert items[0]["seq"] == 2, "newest first"
        assert "ts" in items[0]

    def test_ring_bound_evicts_oldest_but_seq_survives(self) -> None:
        ring = EventRing(3)
        for i in range(5):
            ring.append({"i": i})
        items, total, latest = ring.snapshot(limit=10)
        assert total == 3 and latest == 5
        assert [e["i"] for e in items] == [4, 3, 2]
        # seq keeps counting past the wrap — a reader detects the gap.
        assert items[-1]["seq"] == 3

    def test_since_seq_cursor(self) -> None:
        ring = EventRing(10)
        for i in range(5):
            ring.append({"i": i})
        items, total, _ = ring.snapshot(limit=10, since_seq=3)
        assert total == 2
        assert [e["seq"] for e in items] == [5, 4]

    def test_pagination(self) -> None:
        ring = EventRing(10)
        for i in range(5):
            ring.append({"i": i})
        items, total, _ = ring.snapshot(limit=2, offset=2)
        assert total == 5
        assert [e["i"] for e in items] == [2, 1]

    def test_unserializable_values_coerced_not_dropped(self) -> None:
        ring = EventRing(4)
        ring.append({"obj": object()})
        items, _, _ = ring.snapshot(limit=1)
        assert isinstance(items[0]["obj"], str)


class TestEventBus:
    def test_topic_fan_out_filters(self) -> None:
        async def _run() -> None:
            bus = EventBus()
            bus.bind_loop(asyncio.get_running_loop())
            logs_sub = bus.subscribe({"logs"})
            all_sub = bus.subscribe({"logs", "requests"})
            bus.publish("requests", {"x": 1})
            bus.publish("logs", {"y": 2})
            assert logs_sub.queue.qsize() == 1
            assert all_sub.queue.qsize() == 2
            topic, payload = logs_sub.queue.get_nowait()
            assert topic == "logs" and payload == {"y": 2}
            bus.unsubscribe(logs_sub)
            bus.unsubscribe(all_sub)
            assert bus.subscriber_count() == 0

        asyncio.run(_run())

    def test_unknown_topic_dropped(self) -> None:
        async def _run() -> None:
            bus = EventBus()
            bus.bind_loop(asyncio.get_running_loop())
            sub = bus.subscribe({"logs"})
            bus.publish("bogus", {"x": 1})
            assert sub.queue.qsize() == 0

        asyncio.run(_run())

    def test_slow_consumer_bounded_with_drop_oldest(self) -> None:
        """AC-A.14: a client that stops reading does not grow server
        memory beyond the queue cap; overflow drops OLDEST and counts
        the drops for the gap marker."""

        async def _run() -> None:
            bus = EventBus(default_queue_cap=8)
            bus.bind_loop(asyncio.get_running_loop())
            sub = bus.subscribe({"requests"})
            for i in range(80):  # 10x the cap, consumer never reads
                bus.publish("requests", {"i": i})
            assert sub.queue.qsize() == 8, "queue must not exceed the cap"
            assert sub.dropped == 72
            # The retained items are the NEWEST 8 (drop-oldest).
            kept = [sub.queue.get_nowait()[1]["i"] for _ in range(8)]
            assert kept == list(range(72, 80))
            assert sub.take_dropped() == 72
            assert sub.dropped == 0, "take_dropped resets the counter"

        asyncio.run(_run())

    def test_publish_without_bound_loop_is_noop(self) -> None:
        bus = EventBus()
        sub_holder = {}

        async def _subscribe() -> None:
            sub_holder["sub"] = bus.subscribe({"logs"})

        asyncio.run(_subscribe())
        # No loop bound — publish silently skips (rings still record).
        bus.publish("logs", {"x": 1})
        assert sub_holder["sub"].queue.qsize() == 0

    def test_cross_thread_publish_lands_via_call_soon_threadsafe(self) -> None:
        async def _run() -> None:
            bus = EventBus()
            bus.bind_loop(asyncio.get_running_loop())
            sub = bus.subscribe({"logs"})

            t = threading.Thread(
                target=bus.publish, args=("logs", {"from": "thread"})
            )
            t.start()
            t.join()
            # The threadsafe callback runs on the next loop tick.
            for _ in range(50):
                if sub.queue.qsize():
                    break
                await asyncio.sleep(0.01)
            assert sub.queue.qsize() == 1
            topic, payload = sub.queue.get_nowait()
            assert payload == {"from": "thread"}

        asyncio.run(_run())


class TestPublishHelpers:
    def test_publish_request_event_hits_ring_and_bus(self) -> None:
        async def _run() -> None:
            ev.bind_event_loop(asyncio.get_running_loop())
            sub = ev.BUS.subscribe({"requests"})
            seq = ev.publish_request_event({"tool": "search_papers", "status": "ok"})
            assert seq == 1
            items, total, _ = ev.REQUEST_EVENTS.snapshot(limit=5)
            assert total == 1 and items[0]["tool"] == "search_papers"
            assert sub.queue.qsize() == 1
            _, payload = sub.queue.get_nowait()
            assert payload["seq"] == 1

        asyncio.run(_run())

    def test_bus_frame_matches_ring_record_shape(self) -> None:
        """IF-2 shape parity (Stage-2 integration regression): the SSE
        frame for a published event must be the SAME record the ring
        stores - seq AND ts included. Pre-fix, publishers re-built the
        bus payload from the caller's unstamped dict, so live frames
        lacked ``ts`` while the polling GET twin served it; the SPA's
        log/request rows crashed formatting the missing timestamp on
        the real merged server (found by the live mandated E2E)."""

        async def _run() -> None:
            ev.bind_event_loop(asyncio.get_running_loop())
            sub = ev.BUS.subscribe({"logs", "requests", "ingest"})

            ev.publish_log_event({"level": "INFO", "message": "hello"})
            ev.publish_request_event({"tool": "get_chunk", "status": "ok"})
            ev.publish_ingest_stage_event(
                kind="ingest", slug="nb-p", stage="preflight",
                phase="finished",
            )

            rings = {
                "logs": ev.LOG_EVENTS,
                "requests": ev.REQUEST_EVENTS,
                "ingest": ev.INGEST_EVENTS,
            }
            assert sub.queue.qsize() == 3
            while not sub.queue.empty():
                topic, frame = sub.queue.get_nowait()
                stored = rings[topic].snapshot(limit=1)[0][0]
                assert frame == stored, (
                    f"{topic}: SSE frame diverged from ring record "
                    f"(frame: {frame} / stored: {stored})"
                )
                assert isinstance(frame.get("ts"), float), (
                    f"{topic}: frame missing the ts stamp"
                )

        asyncio.run(_run())

    def test_publish_ingest_stage_event_shape(self) -> None:
        seq = ev.publish_ingest_stage_event(
            kind="parse", slug="nb-a", stage="mineru", phase="started",
            paper_id="textbook:hartshorne",
        )
        assert seq == 1
        items, _, _ = ev.INGEST_EVENTS.snapshot(limit=5)
        e = items[0]
        assert e["kind"] == "parse"
        assert e["stage"] == "mineru"
        assert e["phase"] == "started"
        assert e["paper_id"] == "textbook:hartshorne"

    def test_configure_event_tier_resizes(self) -> None:
        ev.configure_event_tier(
            request_ring_size=17, log_ring_size=13, sse_queue_cap=9
        )
        try:
            assert ev.REQUEST_EVENTS.maxlen == 17
            assert ev.LOG_EVENTS.maxlen == 13
            assert ev.INGEST_EVENTS.maxlen == 13
            assert ev.BUS.default_queue_cap == 9
        finally:
            ev.configure_event_tier(
                request_ring_size=ev.DEFAULT_REQUEST_RING_SIZE,
                log_ring_size=ev.DEFAULT_LOG_RING_SIZE,
                sse_queue_cap=ev.DEFAULT_QUEUE_CAP,
            )
