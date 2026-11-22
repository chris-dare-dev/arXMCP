"""Ids returned by a notebook-scoped search resolve in the follow-up tools.

``search_papers(filters={"notebook": slug})`` returns chunk and paper ids
from that notebook's own chunks table. The documented next step is
``get_chunk`` (or ``get_paper`` / ``cite_neighbors``) on one of those ids;
given the same notebook, it must read the same table and echo the same
``corpus_version``. Without a notebook those tools read the shared corpus,
which does not hold the notebook's ids.

Real LanceDB tables throughout: one shared corpus, one notebook.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

from arxmcp.ingest.schema import CHUNKS_SCHEMA_V1

_SHARED_VERSION = 101
_NOTEBOOK_VERSION = 369
_NOTEBOOK = "bridgeland-stability"
_NB_PAPER = "0705.3794"
_NB_CHUNK = f"arxiv:{_NB_PAPER}:0123456789abcdef"
_SHARED_CHUNK = "arxiv:2401.00001:fedcba9876543210"


def _row(chunk_id: str, paper_id: str, body: str) -> dict[str, Any]:
    names = CHUNKS_SCHEMA_V1.names
    row: dict[str, Any] = dict.fromkeys(names)
    row.update(
        chunk_id=chunk_id,
        paper_id=paper_id,
        kind="theorem",
        section_path=["1"],
        body_text=body,
        body_tokens=body,
        embedding_stmt=[0.1] * 1024,
        chunker_version="test",
        embedder_version="test",
        source_kind="arxiv",
        license="arxiv-license",
    )
    return row


def _table(path: Path, rows: list[dict[str, Any]]) -> Any:
    import lancedb

    return lancedb.connect(str(path)).create_table(
        "chunks", data=pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)
    )


@pytest.fixture
def two_corpora(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from arxmcp.server.resources import CorpusNotIngestedError
    from arxmcp.server.tools import reset_resources_for_tests, set_resources

    shared = _table(
        tmp_path / "shared", [_row(_SHARED_CHUNK, "2401.00001", "shared body")]
    )
    notebook = _table(
        tmp_path / "nb", [_row(_NB_CHUNK, _NB_PAPER, "Bridgeland stability body")]
    )
    kuzu = tmp_path / "kuzu"
    kuzu.mkdir()

    class _Sem:
        async def __aenter__(self) -> _Sem:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

    class _Resources:
        def __init__(self) -> None:
            self.config = SimpleNamespace(
                query_embed_provider="local",
                result_byte_cap=256 * 1024,
                kuzu_path=kuzu,
                lancedb_path=tmp_path / "shared",
            )
            self.chunks_table = shared
            self.corpus_info = SimpleNamespace(version=_SHARED_VERSION)
            self.degraded = None
            self.embed_semaphore = _Sem()
            self.paper_metadata_store = None

        async def notebook_table(self, slug: str) -> tuple[Any, Any]:
            if slug != _NOTEBOOK:
                raise CorpusNotIngestedError(f"notebook {slug!r}: not ingested")
            return notebook, SimpleNamespace(version=_NOTEBOOK_VERSION)

    set_resources(_Resources())  # type: ignore[arg-type]
    monkeypatch.setattr("arxmcp.server.handlers.search.get_cache", lambda: None)

    async def _encode(_query: str) -> np.ndarray:
        return np.full(1024, 0.1, dtype=np.float32)

    monkeypatch.setattr("arxmcp.server.handlers.search.encode_query", _encode)
    yield {"shared": shared, "notebook": notebook}
    reset_resources_for_tests()


def _notebook_search_hit() -> dict[str, Any]:
    from arxmcp.server.handlers.search import handle_search_papers

    res = asyncio.run(
        handle_search_papers(query="stability", filters={"notebook": _NOTEBOOK}, k=5)
    )
    sc = res.structuredContent
    assert sc["corpus_version"] == _NOTEBOOK_VERSION
    (hit,) = sc["results"]
    return hit


def test_get_chunk_finds_a_notebook_search_hit(two_corpora) -> None:
    from arxmcp.server.handlers.chunk import handle_get_chunk

    hit = _notebook_search_hit()
    out = asyncio.run(handle_get_chunk(chunk_id=hit["chunk_id"], notebook=_NOTEBOOK))
    assert out["found"] is True
    assert out["chunk"]["chunk_id"] == _NB_CHUNK
    assert "Bridgeland stability body" in out["chunk"]["body_text"]
    assert out["corpus_version"] == _NOTEBOOK_VERSION


def test_get_chunk_batch_reads_the_notebook(two_corpora) -> None:
    from arxmcp.server.handlers.chunk import handle_get_chunk

    out = asyncio.run(
        handle_get_chunk(chunk_id=[_NB_CHUNK, _SHARED_CHUNK], notebook=_NOTEBOOK)
    )
    assert [c["found"] for c in out["chunks"]] == [True, False]
    assert out["corpus_version"] == _NOTEBOOK_VERSION


def test_get_chunk_without_notebook_reads_the_shared_corpus(two_corpora) -> None:
    from arxmcp.server.handlers.chunk import handle_get_chunk

    miss = asyncio.run(handle_get_chunk(chunk_id=_NB_CHUNK))
    assert miss["found"] is False
    assert miss["corpus_version"] == _SHARED_VERSION
    hit = asyncio.run(handle_get_chunk(chunk_id=_SHARED_CHUNK))
    assert hit["found"] is True
    assert hit["corpus_version"] == _SHARED_VERSION


def test_get_paper_finds_a_notebook_search_hit(two_corpora) -> None:
    from arxmcp.server.handlers.paper import handle_get_paper

    hit = _notebook_search_hit()
    out = asyncio.run(handle_get_paper(paper_id=hit["paper_id"], notebook=_NOTEBOOK))
    assert out["found"] is True
    assert out["paper"]["chunk_count"] == 1
    assert out["corpus_version"] == _NOTEBOOK_VERSION

    shared = asyncio.run(handle_get_paper(paper_id=_NB_PAPER))
    assert shared["found"] is False
    assert shared["corpus_version"] == _SHARED_VERSION


def test_cite_neighbors_resolves_chunks_in_the_notebook(
    two_corpora, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The graph is shared; chunk ids are resolved in the caller's corpus."""
    from arxmcp.server.handlers import citations
    from arxmcp.server.handlers.citations import handle_cite_neighbors

    seen: list[Any] = []

    async def _graph(chunk_id: str, **kwargs: Any) -> list[Any]:
        seen.append(kwargs["chunks_table"])
        return []

    monkeypatch.setattr(citations, "cite_neighbors", _graph)
    out = asyncio.run(handle_cite_neighbors(chunk_id=_NB_CHUNK, notebook=_NOTEBOOK))
    assert out["graph_status"] == "present"
    assert out["corpus_version"] == _NOTEBOOK_VERSION
    assert seen == [two_corpora["notebook"]]


@pytest.mark.parametrize(
    ("module", "handler", "kwargs"),
    [
        ("chunk", "handle_get_chunk", {"chunk_id": _NB_CHUNK}),
        ("paper", "handle_get_paper", {"paper_id": _NB_PAPER}),
        ("citations", "handle_cite_neighbors", {"chunk_id": _NB_CHUNK}),
    ],
    ids=["get_chunk", "get_paper", "cite_neighbors"],
)
def test_bad_notebooks_are_clean_tool_errors(
    two_corpora, module: str, handler: str, kwargs: dict[str, Any]
) -> None:
    """Never a silent answer from the shared corpus."""
    import importlib

    handle = getattr(importlib.import_module(f"arxmcp.server.handlers.{module}"), handler)
    with pytest.raises(ValueError, match="not a valid notebook slug"):
        asyncio.run(handle(**kwargs, notebook="../etc"))
    with pytest.raises(ValueError, match="not-a-real-nb"):
        asyncio.run(handle(**kwargs, notebook="not-a-real-nb"))
