"""get_paper's chunk scan reads only the columns the reply is built from.

The chunks table carries two 1024-float vector columns. get_paper reports a
row count, the section count and two version strings, so a scan that
returns every column moves ~14 KB per row it never looks at, for up to
10,000 rows on every call. The table here is a real LanceDB table wrapped
so the test can see which columns each scan returned.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import lancedb
import pytest

from server.handlers.paper import handle_get_paper
from server.tools import reset_resources_for_tests, set_resources
from tests._graph_helpers import build_synthetic_lancedb

_PAPER = "2401.00001"


class _RecordingQuery:
    """Delegates to a LanceDB query builder; records each scan's columns."""

    def __init__(self, inner: Any, scans: list[list[str]]) -> None:
        self._inner = inner
        self._scans = scans

    def __getattr__(self, name: str) -> Any:
        method = getattr(self._inner, name)

        def call(*args: Any, **kwargs: Any) -> Any:
            result = method(*args, **kwargs)
            if name == "to_arrow":
                self._scans.append(result.column_names)
                return result
            self._inner = result
            return self

        return call


class _RecordingTable:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.scans: list[list[str]] = []

    def search(self, *args: Any, **kwargs: Any) -> _RecordingQuery:
        return _RecordingQuery(self._inner.search(*args, **kwargs), self.scans)

    def count_rows(self, *args: Any, **kwargs: Any) -> int:
        return self._inner.count_rows(*args, **kwargs)


@pytest.fixture
def chunks(tmp_path: Path):
    rows = [
        {"chunk_id": f"arxiv:{_PAPER}:{i:016x}", "paper_id": _PAPER,
         "kind": "stmt", "section_path": [section, "sub"],
         "chunker_version": "cv-7", "embedder_version": "ev-3",
         "embedding_stmt": [0.5] * 1024}
        for i, section in enumerate(["1 Intro", "2 Main", "2 Main"])
    ]
    rows.append(
        {"chunk_id": "arxiv:2401.00002:0000000000000000",
         "paper_id": "2401.00002", "kind": "stmt", "section_path": ["9 Other"],
         "embedding_stmt": [0.5] * 1024}
    )
    path = build_synthetic_lancedb(tmp_path / "lancedb", rows)
    table = _RecordingTable(lancedb.connect(str(path)).open_table("chunks"))

    class _Config:
        result_byte_cap = 256 * 1024

    class _CorpusInfo:
        version = 1

    class _Resources:
        config = _Config()
        corpus_info = _CorpusInfo()
        chunks_table = table
        paper_metadata_store = None

    set_resources(_Resources())  # type: ignore[arg-type]
    yield table
    reset_resources_for_tests()


def test_reply_is_built_from_a_projected_scan(chunks: _RecordingTable) -> None:
    reply = asyncio.run(handle_get_paper(paper_id=_PAPER))

    assert reply["found"] is True
    assert reply["paper"]["chunk_count"] == 3
    assert reply["paper"]["section_count"] == 2
    assert reply["paper"]["chunker_version"] == "cv-7"
    assert reply["paper"]["embedder_version"] == "ev-3"

    assert len(chunks.scans) == 1
    assert sorted(chunks.scans[0]) == [
        "chunker_version", "embedder_version", "section_path",
    ]


def test_a_paper_past_the_old_row_cap_is_counted_in_full(
    tmp_path: Path,
) -> None:
    n = 10_050
    rows = [
        {"chunk_id": f"textbook:big:{i:016x}", "paper_id": "textbook:big",
         "kind": "stmt", "section_path": [f"Ch {i % 12}"],
         "chunker_version": "tmd0.1", "embedder_version": "ev-3",
         "source_kind": "textbook"}
        for i in range(n)
    ]
    path = build_synthetic_lancedb(tmp_path / "lancedb", rows)

    class _Config:
        result_byte_cap = 256 * 1024

    class _CorpusInfo:
        version = 1

    class _Resources:
        config = _Config()
        corpus_info = _CorpusInfo()
        chunks_table = lancedb.connect(str(path)).open_table("chunks")
        paper_metadata_store = None

    set_resources(_Resources())  # type: ignore[arg-type]
    try:
        reply = asyncio.run(handle_get_paper(paper_id="textbook:big"))
    finally:
        reset_resources_for_tests()

    assert reply["found"] is True
    assert reply["paper"]["chunk_count"] == n
    assert reply["paper"]["section_count"] == 12


def test_unknown_paper_still_reports_not_found(chunks: _RecordingTable) -> None:
    reply = asyncio.run(handle_get_paper(paper_id="2401.09999"))

    assert reply["found"] is False
    assert reply["paper"] is None
