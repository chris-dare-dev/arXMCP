"""Handlers read LanceDB on a worker thread, never on the event loop.

The server runs one event loop for every MCP tool, the operator console and
the health probes. A LanceDB read made directly in an ``async def`` stalls
all of them for as long as the read takes. These tests wrap a real table and
record the thread each read runs on.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import lancedb
import pytest

from arxmcp.server.handlers.chunk import handle_get_chunk, read_chunk_in_full
from arxmcp.server.handlers.lemma import handle_find_lemma_by_name
from arxmcp.server.handlers.paper import handle_get_paper
from arxmcp.server.tools import reset_resources_for_tests, set_resources
from tests._graph_helpers import build_synthetic_lancedb

_PAPER = "2401.00001"
_CHUNK = f"arxiv:{_PAPER}:{0:016x}"


class _RecordingQuery:
    def __init__(self, inner: Any, threads: list[threading.Thread]) -> None:
        self._inner = inner
        self._threads = threads

    def __getattr__(self, name: str) -> Any:
        method = getattr(self._inner, name)

        def call(*args: Any, **kwargs: Any) -> Any:
            result = method(*args, **kwargs)
            if name in ("to_arrow", "to_list", "to_pandas"):
                self._threads.append(threading.current_thread())
                return result
            self._inner = result
            return self

        return call


class _RecordingTable:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.threads: list[threading.Thread] = []

    def search(self, *args: Any, **kwargs: Any) -> _RecordingQuery:
        return _RecordingQuery(self._inner.search(*args, **kwargs), self.threads)

    def count_rows(self, *args: Any, **kwargs: Any) -> int:
        self.threads.append(threading.current_thread())
        return self._inner.count_rows(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.fixture
def table(tmp_path: Path):
    rows = [
        {
            "chunk_id": f"arxiv:{_PAPER}:{i:016x}",
            "paper_id": _PAPER,
            "kind": "stmt",
            "section_path": ["1 Intro"],
            "theorem_name": "Riemann-Roch" if i == 0 else None,
            "body_text": "Let X be a curve.",
        }
        for i in range(3)
    ]
    path = build_synthetic_lancedb(tmp_path / "lancedb", rows)
    recording = _RecordingTable(lancedb.connect(str(path)).open_table("chunks"))

    class _Config:
        result_byte_cap = 256 * 1024

    class _CorpusInfo:
        version = 1

    class _Resources:
        config = _Config()
        corpus_info = _CorpusInfo()
        chunks_table = recording
        paper_metadata_store = None
        theorem_names_db = None

    set_resources(_Resources())  # type: ignore[arg-type]
    yield recording
    reset_resources_for_tests()


def _off_loop(table: _RecordingTable) -> None:
    assert table.threads, "the handler made no LanceDB read"
    loop_thread = threading.main_thread()
    assert all(t is not loop_thread for t in table.threads)


def test_get_chunk_reads_off_the_loop(table: _RecordingTable) -> None:
    reply = asyncio.run(handle_get_chunk(chunk_id=_CHUNK, include_referenced=True))
    assert reply["found"] is True
    _off_loop(table)


def test_batched_get_chunk_reads_off_the_loop(table: _RecordingTable) -> None:
    reply = asyncio.run(handle_get_chunk(chunk_id=[_CHUNK]))
    assert reply["chunks"][0]["found"] is True
    _off_loop(table)


def test_chunk_resource_reads_off_the_loop(table: _RecordingTable) -> None:
    reply = asyncio.run(read_chunk_in_full(_CHUNK))
    assert reply["found"] is True
    _off_loop(table)


def test_get_paper_reads_off_the_loop(table: _RecordingTable) -> None:
    reply = asyncio.run(handle_get_paper(paper_id=_PAPER))
    assert reply["paper"]["chunk_count"] == 3
    _off_loop(table)


def test_lemma_fallback_reads_off_the_loop(table: _RecordingTable) -> None:
    reply = asyncio.run(handle_find_lemma_by_name(name="riemann"))
    assert reply["retrieval_mode"] == "in_memory_scan_fallback"
    assert [m["paper_id"] for m in reply["matches"]] == [_PAPER]
    _off_loop(table)


def test_lemma_fallback_scans_only_named_rows(tmp_path: Path) -> None:
    from arxmcp.server.handlers.lemma import _scan_named_rows

    rows = [
        {"chunk_id": f"arxiv:{pid}:{i:016x}", "paper_id": pid, "kind": "stmt",
         "theorem_name": name}
        for i, (pid, name) in enumerate([
            ("2401.00001", "Riemann-Roch"),
            ("2401.00001", None),
            ("2401.00002", "Serre duality"),
            ("2401.00002", None),
        ])
    ]
    path = build_synthetic_lancedb(tmp_path / "lancedb", rows)
    tbl = lancedb.connect(str(path)).open_table("chunks")

    assert sorted(_scan_named_rows(tbl, None).column("theorem_name").to_pylist()) == [
        "Riemann-Roch", "Serre duality",
    ]
    scoped = _scan_named_rows(tbl, "2401.00002")
    assert scoped.column("paper_id").to_pylist() == ["2401.00002"]
    assert _scan_named_rows(tbl, "2401.09999").num_rows == 0
