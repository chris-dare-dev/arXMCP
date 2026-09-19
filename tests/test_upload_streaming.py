"""Streamed-to-disk uploads — bounded memory (stage2/arx-a45, AC-A.17).

Two layers under test:

1. ``RequestBodySizeLimitMiddleware``'s eager pre-read now spools to a
   ``SpooledTemporaryFile`` (rolls to disk past 1 MB) and replays the
   body to the inner app in bounded chunks, instead of holding the
   drained events in a Python list. Every pre-arx-a45 semantic is
   pinned here: byte-identical replay, mid-stream 413, disconnect
   passthrough, empty-body final event.
2. The upload route handler copies the multipart part to its ``.tmp``
   destination in ``_UPLOAD_COPY_CHUNK_BYTES`` chunks (never
   ``await file.read()`` of the whole body), enforcing the per-kind
   cap mid-copy.

The named AC-A.17 test uploads a PDF at the 200 MB envelope scale
through the REAL route + middleware via a raw ASGI driver (the body
is generated chunk-by-chunk — no client-side buffering pollutes the
measurement) and asserts process RSS growth stays under the stated
bound.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.middleware import (
    PREREAD_REPLAY_CHUNK_BYTES,
    RequestBodySizeLimitMiddleware,
)
from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import _UPLOAD_COPY_CHUNK_BYTES
from server.routes.notebooks import router as notebooks_router
from tools import _notebook_common

# ---------------------------------------------------------------------------
# RSS measurement (Windows-first; POSIX fallback; skip elsewhere)
# ---------------------------------------------------------------------------


def _peak_rss_bytes() -> int | None:
    """Return the process peak working-set / RSS in bytes, or None
    when the platform offers no cheap probe (test then skips)."""
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):  # noqa: N801 — Win32 struct name
            _fields_ = [
                ("cb", wt.DWORD),
                ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        # Explicit argtypes matter on 64-bit: without them ctypes
        # marshals HANDLE/pointer args as 32-bit ints and the call
        # fails with ok=0. K32GetProcessMemoryInfo is the kernel32
        # export (Win7+) — no psapi.dll load needed.
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = k32.K32GetProcessMemoryInfo
        fn.argtypes = [
            wt.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wt.DWORD,
        ]
        fn.restype = wt.BOOL
        k32.GetCurrentProcess.restype = wt.HANDLE
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        ok = fn(
            k32.GetCurrentProcess(), ctypes.byref(counters), counters.cb,
        )
        return int(counters.PeakWorkingSetSize) if ok else None
    try:
        import resource  # POSIX only

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is KB on Linux, bytes on macOS.
        return peak if sys.platform == "darwin" else peak * 1024
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Raw ASGI driver (no client-side body buffering)
# ---------------------------------------------------------------------------


def _run_asgi_post(app, path: str, headers, body_chunks) -> tuple[int, bytes]:
    """POST ``body_chunks`` (an iterator of bytes) to ``app`` at
    ``path``, feeding one http.request event per chunk. Returns
    ``(status, response_body)``."""

    async def _drive() -> tuple[int, bytes]:
        chunk_iter = iter(body_chunks)
        exhausted = {"done": False}

        async def receive() -> dict:
            if exhausted["done"]:
                return {"type": "http.disconnect"}
            try:
                chunk = next(chunk_iter)
            except StopIteration:
                exhausted["done"] = True
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": True,
            }

        status_box: dict[str, int] = {}
        body_parts: list[bytes] = []

        async def send(event: dict) -> None:
            if event["type"] == "http.response.start":
                status_box["status"] = event["status"]
            elif event["type"] == "http.response.body":
                body_parts.append(event.get("body", b""))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "root_path": "",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 51234),
            "server": ("127.0.0.1", 7733),
        }
        await app(scope, receive, send)
        return status_box.get("status", 0), b"".join(body_parts)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_drive())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Middleware replay semantics (spooled pre-read)
# ---------------------------------------------------------------------------


def _make_echo_len_app(collected: dict):
    """Minimal ASGI app: drains the request body, records it, and
    replies 200 with the byte count."""

    async def app(scope, receive, send):
        body = b""
        events = []
        while True:
            event = await receive()
            events.append(
                (event["type"], event.get("more_body", False))
            )
            if event["type"] == "http.disconnect":
                break
            body += event.get("body", b"")
            if not event.get("more_body", False):
                break
        collected["body"] = body
        collected["events"] = events
        payload = str(len(body)).encode("ascii")
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({
            "type": "http.response.body", "body": payload,
            "more_body": False,
        })

    return app


class TestSpooledPrereadReplay:
    def test_small_body_replayed_byte_identical(self):
        collected: dict = {}
        mw = RequestBodySizeLimitMiddleware(
            _make_echo_len_app(collected), max_bytes=1024 * 1024,
        )
        status, resp = _run_asgi_post(
            mw, "/echo", [(b"content-type", b"application/json")],
            [b'{"k": 1}'],
        )
        assert status == 200
        assert collected["body"] == b'{"k": 1}'

    def test_large_multi_event_body_replayed_byte_identical(self):
        # 5 MB in 512 KB wire events — past the 1 MB spool threshold,
        # so the body rolls to disk and replays re-chunked. The inner
        # app must still see the exact bytes.
        collected: dict = {}
        mw = RequestBodySizeLimitMiddleware(
            _make_echo_len_app(collected),
            max_bytes=16 * 1024 * 1024,
        )
        pattern = bytes(range(256)) * 2048  # 512 KB, position-varying
        chunks = [pattern for _ in range(10)]
        status, _ = _run_asgi_post(mw, "/echo", [], chunks)
        assert status == 200
        assert collected["body"] == pattern * 10
        # Replay is re-chunked at the bounded replay size: the inner
        # app saw multiple http.request events, none oversized.
        request_events = [
            e for e in collected["events"] if e[0] == "http.request"
        ]
        assert len(request_events) >= (5 * 1024 * 1024) // (
            PREREAD_REPLAY_CHUNK_BYTES
        )

    def test_empty_body_yields_single_final_event(self):
        collected: dict = {}
        mw = RequestBodySizeLimitMiddleware(
            _make_echo_len_app(collected), max_bytes=1024,
        )
        status, resp = _run_asgi_post(mw, "/echo", [], [])
        assert status == 200
        assert collected["body"] == b""
        assert collected["events"][0] == ("http.request", False)

    def test_over_cap_chunked_body_rejected_413_mid_stream(self):
        collected: dict = {}
        mw = RequestBodySizeLimitMiddleware(
            _make_echo_len_app(collected), max_bytes=1024,
        )
        status, resp = _run_asgi_post(
            mw, "/echo", [], [b"x" * 600, b"y" * 600],
        )
        assert status == 413
        assert b"payload_too_large" in resp
        # Inner app never ran.
        assert "body" not in collected

    def test_disconnect_mid_body_replays_partial_then_disconnect(self):
        collected: dict = {}
        mw = RequestBodySizeLimitMiddleware(
            _make_echo_len_app(collected), max_bytes=1024 * 1024,
        )

        async def _drive():
            events = iter([
                {"type": "http.request", "body": b"abc", "more_body": True},
                {"type": "http.disconnect"},
            ])

            async def receive():
                return next(events)

            sent = []

            async def send(event):
                sent.append(event)

            scope = {
                "type": "http", "http_version": "1.1", "method": "POST",
                "scheme": "http", "path": "/echo", "raw_path": b"/echo",
                "root_path": "", "query_string": b"", "headers": [],
                "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 2),
            }
            await mw(scope, receive, send)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_drive())
        finally:
            loop.close()
        # Partial body delivered with more_body=True, then disconnect.
        assert collected["body"] == b"abc"
        assert collected["events"][-1][0] == "http.disconnect"
        for etype, more in collected["events"][:-1]:
            assert etype == "http.request"
            assert more is True


# ---------------------------------------------------------------------------
# Upload route: chunked reads + RSS bound at the 200 MB envelope
# ---------------------------------------------------------------------------


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(
        notebooks_module, "NOTEBOOKS_BASE", base, raising=False,
    )
    return base


@pytest.fixture
def upload_app(
    tmp_path: Path, notebooks_base: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple]:
    """(wrapped_app, inner_client, notebooks_base) with the real
    200 MB prefix carve-out in front — the production upload stack
    minus unrelated middlewares."""
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        monkeypatch.setattr(
            notebooks_module, "_now_iso",
            lambda: "2026-07-04T00:00:00+00:00",
        )
        wrapped = RequestBodySizeLimitMiddleware(
            app,
            prefix_caps={"/ui/api/notebooks": 200 * 1024 * 1024},
        )
        with TestClient(app) as inner_client:
            yield wrapped, inner_client, notebooks_base
        loop.run_until_complete(store.close())
    finally:
        loop.close()


_BOUNDARY = b"arxa45boundary1234"


def _multipart_chunks(
    paper_id: str, pdf_size_bytes: int, wire_chunk: int = 1024 * 1024,
):
    """Generate a multipart/form-data body chunk-by-chunk without
    ever materializing the PDF in memory."""
    prologue = (
        b"--" + _BOUNDARY + b"\r\n"
        b'Content-Disposition: form-data; name="paper_id"\r\n\r\n'
        + paper_id.encode("ascii") + b"\r\n"
        b"--" + _BOUNDARY + b"\r\n"
        b'Content-Disposition: form-data; name="file"; '
        b'filename="big.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n"
    )
    epilogue = b"\r\n--" + _BOUNDARY + b"--\r\n"
    header = b"%PDF-1.4\n"
    yield prologue + header
    remaining = pdf_size_bytes - len(header)
    filler = b"0" * wire_chunk
    while remaining > 0:
        piece = min(remaining, wire_chunk)
        yield filler[:piece]
        remaining -= piece
    yield epilogue


_MULTIPART_HEADERS = [
    (b"content-type", b"multipart/form-data; boundary=" + _BOUNDARY),
    (b"host", b"testserver"),
]


class TestUploadStreamedToDisk:
    #: AC-A.17 stated bound: RSS growth while ingesting an upload at
    #: the 200 MB envelope must stay under this. True streaming needs
    #: only chunk-sized buffers (~a few MB); the bound leaves 50x
    #: headroom for allocator slack while sitting far below the
    #: ~190 MB (or 2x that, with copies) a buffered implementation
    #: would show.
    RSS_GROWTH_BOUND_BYTES = 100 * 1024 * 1024
    #: Upload size for the named test — at the 200 MB envelope
    #: (minus multipart overhead headroom).
    UPLOAD_SIZE_BYTES = 190 * 1024 * 1024

    def test_rss_bounded_at_200mb_envelope(self, upload_app):
        """The named AC-A.17 test. Peak-RSS delta measured around a
        190 MB PDF upload driven through the real middleware + route
        via raw ASGI (body generated chunkwise; no client buffer).

        Caveat (documented): the probe is the process-wide peak
        working set, so a prior test in the same process that peaked
        higher can mask growth. Run standalone for the sharpest
        signal; under the full suite the assertion remains sound
        (it can only under-report, never false-alarm).
        """
        wrapped, inner_client, notebooks_base = upload_app
        peak_before = _peak_rss_bytes()
        if peak_before is None:
            pytest.skip("no RSS probe on this platform")

        r = inner_client.post(
            "/ui/api/notebooks",
            json={"slug": "big-tb", "notebook_kind": "textbook"},
        )
        assert r.status_code == 201, r.text

        status, resp = _run_asgi_post(
            wrapped,
            "/ui/api/notebooks/big-tb/papers/upload",
            _MULTIPART_HEADERS,
            _multipart_chunks("textbook:big-book", self.UPLOAD_SIZE_BYTES),
        )
        peak_after = _peak_rss_bytes()
        assert status == 201, resp[:500]

        target = (
            notebooks_base / "big-tb" / "pdfs" / "textbook_big-book.pdf"
        )
        assert target.is_file()
        assert target.stat().st_size == self.UPLOAD_SIZE_BYTES
        # No stray .tmp survived the promotion.
        assert not list((notebooks_base / "big-tb" / "pdfs").glob("*.tmp"))

        growth = peak_after - peak_before
        assert growth < self.RSS_GROWTH_BOUND_BYTES, (
            f"peak RSS grew {growth / 1024 / 1024:.1f} MB during a "
            f"{self.UPLOAD_SIZE_BYTES / 1024 / 1024:.0f} MB upload — "
            f"exceeds the stated AC-A.17 bound "
            f"({self.RSS_GROWTH_BOUND_BYTES / 1024 / 1024:.0f} MB); "
            f"the body is being buffered, not streamed"
        )

    def test_arxiv_over_cap_streams_to_413_and_cleans_tmp(self, upload_app):
        """Per-kind 10 MB cap fires MID-COPY for arxiv-kind uploads;
        the .tmp is unlinked and no partial artifact survives."""
        wrapped, inner_client, notebooks_base = upload_app
        r = inner_client.post(
            "/ui/api/notebooks",
            json={"slug": "small-ax", "notebook_kind": "arxiv"},
        )
        assert r.status_code == 201, r.text

        def _html_chunks(total: int):
            first = b"<!DOCTYPE html><html>"
            yield (
                b"--" + _BOUNDARY + b"\r\n"
                b'Content-Disposition: form-data; name="paper_id"\r\n\r\n'
                b"2604.11111\r\n"
                b"--" + _BOUNDARY + b"\r\n"
                b'Content-Disposition: form-data; name="file"; '
                b'filename="a.html"\r\n'
                b"Content-Type: text/html\r\n\r\n" + first
            )
            remaining = total - len(first)
            filler = b"z" * (1024 * 1024)
            while remaining > 0:
                piece = min(remaining, len(filler))
                yield filler[:piece]
                remaining -= piece
            yield b"\r\n--" + _BOUNDARY + b"--\r\n"

        status, resp = _run_asgi_post(
            wrapped,
            "/ui/api/notebooks/small-ax/papers/upload",
            _MULTIPART_HEADERS,
            _html_chunks(12 * 1024 * 1024),
        )
        assert status == 413, resp[:300]
        ar5iv_dir = notebooks_base / "small-ax" / "ar5iv"
        if ar5iv_dir.is_dir():
            assert list(ar5iv_dir.iterdir()) == []

    def test_handler_reads_upload_in_bounded_chunks(self, upload_app):
        """AC-A.17 'chunked reads': the handler consumes the multipart
        part via bounded read(size) calls — never one whole-body
        read() (the pre-arx-a45 shape)."""
        wrapped, inner_client, notebooks_base = upload_app
        r = inner_client.post(
            "/ui/api/notebooks",
            json={"slug": "chunk-ax", "notebook_kind": "arxiv"},
        )
        assert r.status_code == 201, r.text

        read_sizes: list[int | None] = []
        import starlette.datastructures as ds

        original_read = ds.UploadFile.read

        async def recording_read(self, size=-1):
            read_sizes.append(size)
            return await original_read(self, size)

        html = b"<!DOCTYPE html><html><body>" + b"a" * (3 * 1024 * 1024)
        from unittest.mock import patch

        with patch.object(ds.UploadFile, "read", recording_read):
            status, resp = _run_asgi_post(
                wrapped,
                "/ui/api/notebooks/chunk-ax/papers/upload",
                _MULTIPART_HEADERS,
                iter([
                    b"--" + _BOUNDARY + b"\r\n"
                    b'Content-Disposition: form-data; name="paper_id"'
                    b"\r\n\r\n2604.22222\r\n"
                    b"--" + _BOUNDARY + b"\r\n"
                    b'Content-Disposition: form-data; name="file"; '
                    b'filename="a.html"\r\n'
                    b"Content-Type: text/html\r\n\r\n" + html +
                    b"\r\n--" + _BOUNDARY + b"--\r\n",
                ]),
            )
        assert status == 201, resp[:300]
        # Every handler read was bounded; a whole-body read would
        # appear as size -1 (or None).
        handler_reads = [s for s in read_sizes if s is not None]
        assert handler_reads, "no reads recorded"
        assert all(
            s != -1 and s <= _UPLOAD_COPY_CHUNK_BYTES for s in handler_reads
        ), f"unbounded read sizes observed: {read_sizes!r}"
        # A 3 MB part at a 1 MB chunk size needs several reads.
        assert len(handler_reads) >= 3


# ---------------------------------------------------------------------------
# Streaming preflight ≡ bytes preflight (differential, incl. window
# boundaries)
# ---------------------------------------------------------------------------


class TestPreflightFileEquivalence:
    """``_run_pdf_preflight_file`` must reach the same verdict as the
    in-memory reference ``_run_pdf_preflight`` — including for tokens
    that straddle a scan-window boundary (shrunken window so the
    overlap logic is actually exercised)."""

    @pytest.mark.parametrize(
        "payload_builder",
        [
            # clean PDF — both accept.
            lambda pad: b"%PDF-1.4\n" + b"A" * pad + b"\n%%EOF",
            # /JavaScript token in the middle — both reject (415).
            lambda pad: (
                b"%PDF-1.4\n" + b"A" * pad
                + b"/JavaScript (x)" + b"B" * pad + b"\n%%EOF"
            ),
            # oversized declared page count — both reject.
            lambda pad: (
                b"%PDF-1.4\n" + b"A" * pad
                + b"/Count 99999 " + b"B" * pad + b"\n%%EOF"
            ),
            # polyglot tail marker — both reject.
            lambda pad: b"%PDF-1.4\n" + b"A" * pad + b"PK\x05\x06",
            # not a PDF at all — both reject.
            lambda pad: b"<!DOCTYPE html>" + b"A" * pad,
        ],
    )
    def test_verdicts_match_across_window_boundaries(
        self, tmp_path, monkeypatch, payload_builder,
    ):
        from fastapi import HTTPException

        from server.routes.notebooks import (
            _run_pdf_preflight,
            _run_pdf_preflight_file,
        )

        # Shrink the scan window so multi-window logic runs even on
        # tiny payloads; sweep pads around the window size so tokens
        # land before/on/after the boundary.
        monkeypatch.setattr(
            notebooks_module, "_SCAN_WINDOW_BYTES", 256,
        )
        window = 256
        for pad in (
            0, 1, window - 70, window - 65, window - 64, window - 63,
            window - 12, window - 1, window, window + 1, 2 * window - 5,
        ):
            payload = payload_builder(pad)
            path = tmp_path / "probe.pdf"
            path.write_bytes(payload)

            def _verdict(fn, arg):
                try:
                    fn(arg)
                except HTTPException as e:
                    return e.status_code, e.detail
                return None

            ref = _verdict(_run_pdf_preflight, payload)
            streamed = _verdict(_run_pdf_preflight_file, path)
            assert streamed == ref, (
                f"pad={pad}: streamed verdict {streamed!r} != "
                f"reference {ref!r}"
            )
