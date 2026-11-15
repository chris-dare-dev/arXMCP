"""``get_paper`` summarizes a paper's chunk rows from the chunks table."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import lancedb
import pyarrow as pa
import pytest

from ingest.schema import CHUNKS_SCHEMA_V1, EMBEDDING_COLUMN_NAMES
from server.handlers.paper import handle_get_paper
from server.tools import reset_resources_for_tests, set_resources


def _row(paper_id: str, n: int, section: str) -> dict:
    row = {field.name: None for field in CHUNKS_SCHEMA_V1}
    row.update(
        chunk_id=f"{paper_id}#c{n}",
        paper_id=paper_id,
        kind="theorem",
        section_path=[section, f"{section}.{n}"],
        body_text="x" * 500,
        body_tokens="x",
        embedding_stmt=[0.1] * 1024,
        chunker_version="chunker-v9",
        embedder_version="embedder-v4",
    )
    return row


class _RecordingTable:
    """Hands queries to a real LanceDB table and keeps what they fetched."""

    def __init__(self, table):
        self._table = table
        self.fetched: list[pa.Table] = []

    def search(self, *args, **kwargs):
        builder = self._table.search(*args, **kwargs)
        real_to_arrow = builder.to_arrow

        def to_arrow(*a, **k):
            result = real_to_arrow(*a, **k)
            self.fetched.append(result)
            return result

        builder.to_arrow = to_arrow
        return builder


@pytest.fixture
def chunks_table(tmp_path):
    rows = [_row("2401.00001", n, s) for n, s in enumerate(["1", "1", "2"])]
    rows.append(_row("2401.00002", 0, "1"))
    db = lancedb.connect(str(tmp_path / "lancedb"))
    table = db.create_table(
        "chunks", data=pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)
    )
    recording = _RecordingTable(table)
    set_resources(
        SimpleNamespace(
            chunks_table=recording,
            corpus_info=SimpleNamespace(version=3),
            config=SimpleNamespace(result_byte_cap=256 * 1024),
            paper_metadata_store=None,
        )
    )
    yield recording
    reset_resources_for_tests()


def test_summarizes_the_papers_rows(chunks_table):
    out = asyncio.run(handle_get_paper("2401.00001"))

    paper = out["paper"]
    assert out["found"] is True
    assert paper["chunk_count"] == 3
    assert paper["section_count"] == 2
    assert paper["chunker_version"] == "chunker-v9"
    assert paper["embedder_version"] == "embedder-v4"


def test_unknown_paper_is_not_found(chunks_table):
    out = asyncio.run(handle_get_paper("2401.09999"))

    assert out["found"] is False


def test_reads_no_embedding_or_body_columns(chunks_table):
    """Each embedding is 1024 floats per row; a summary needs neither
    them nor the body text."""
    asyncio.run(handle_get_paper("2401.00001"))

    (fetched,) = chunks_table.fetched
    leaked = set(fetched.column_names) & {*EMBEDDING_COLUMN_NAMES, "embedding_eq", "body_text"}
    assert leaked == set()
