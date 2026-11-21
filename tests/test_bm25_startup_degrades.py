"""A BM25 index that cannot be built must not keep the server from serving.

The phase loads only with ``ARXMCP_BM25_PHASE=on``, so every config here
turns it on. No served tool reads the BM25 phase: ``search_papers`` runs the dense route
and reports ``retrieval_mode="dense_only"`` either way. The index lives inside
the dataset, so a read-only dataset mount is enough to make its auto-build
fail. These tests drive the REAL ``BM25Phase.startup`` against a BM25 root
that cannot be created, through both places the process binds a corpus.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest


def _rows(start: int, count: int) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": f"c{i}",
            "paper_id": f"p{i}",
            "kind": "section",
            "section_path": ["1"],
            "theorem_name": None,
            "theorem_label": None,
            "body_text": "body",
            "body_tokens": "body",
            "embedding_stmt": [0.1] * 1024,
            "embedding_proof": None,
            "embedding_eq": None,
            "chunker_version": "test",
            "embedder_version": "test",
            "preamble_ref": None,
        }
        for i in range(start, start + count)
    ]


def _write_marker(lance: Path, *, version: int, chunk_count: int) -> None:
    from ingest.embedder import EMBEDDER_VERSION

    (lance / "corpus-version.json").write_text(
        json.dumps(
            {
                "version": version,
                "chunker_version": "test",
                "embedder_version": EMBEDDER_VERSION,
                "created_at": "2026-08-23T00:00:00Z",
                "paper_count": chunk_count,
                "chunk_count": chunk_count,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def unbuildable_bm25(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import lancedb
    import pyarrow as pa

    import server.cache as cache_mod
    import server.query_encoder as qe_mod
    import server.resources as res_mod
    from ingest.schema import CHUNKS_SCHEMA_V1
    from server.config import Config

    lance = tmp_path / "lancedb"
    table = lancedb.connect(str(lance)).create_table(
        "chunks", data=pa.Table.from_pylist(_rows(0, 3), schema=CHUNKS_SCHEMA_V1)
    )
    _write_marker(lance, version=1, chunk_count=3)

    # A regular file where the BM25 root's parent directory should be, so
    # the auto-build cannot create its output directory.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        res_mod, "open_chunks_table_with_fallback", lambda **_kw: (table, None)
    )
    monkeypatch.setattr(cache_mod, "set_cache", lambda _c: None)
    monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
    monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())

    cfg = Config(
        lancedb_path=lance,
        notebooks_db_path=tmp_path / "nb.db",
        cache_db_path=tmp_path / "cache.db",
        bm25_index_root=blocker / "bm25",
        enable_rerank=False,
        bm25_phase="on",
    )
    return {"cfg": cfg, "table": table, "lance": lance}


def test_startup_serves_without_an_unbuildable_bm25_index(
    unbuildable_bm25: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    from server.resources import Resources

    with caplog.at_level("WARNING"):
        resources = asyncio.run(Resources.startup(unbuildable_bm25["cfg"]))
    try:
        assert resources.bm25_phase is None
        assert resources.bm25_phase_state == "unavailable"
        assert resources.chunks_table is not None
        assert resources.corpus_info is not None
        assert resources.corpus_info.version == 1
        assert any(
            "BM25 phase unavailable" in record.getMessage()
            for record in caplog.records
            if record.levelname == "WARNING"
        ), "an operator must be told why the phase is missing"
    finally:
        asyncio.run(resources.shutdown())


def test_rebind_lands_without_an_unbuildable_bm25_index(
    unbuildable_bm25: dict[str, Any],
) -> None:
    """A fresh ingest must become visible even when BM25 cannot be built.

    The boot builds BM25 for v1 normally; only the v2 build is blocked, so
    this exercises the rebind on its own.
    """
    import pyarrow as pa

    from ingest.schema import CHUNKS_SCHEMA_V1
    from server.config import Config
    from server.resources import Resources

    lance = unbuildable_bm25["lance"]
    bm25_root = lance.parent / "bm25"
    cfg = Config(
        lancedb_path=lance,
        notebooks_db_path=lance.parent / "nb.db",
        cache_db_path=lance.parent / "cache.db",
        bm25_index_root=bm25_root,
        enable_rerank=False,
        bm25_phase="on",
    )

    async def _scenario() -> tuple[bool, int, Any, str]:
        resources = await Resources.startup(cfg)
        try:
            if resources.bm25_phase is None:
                raise RuntimeError("the v1 boot must build BM25 for real")
            if resources.bm25_phase_state != "warm":
                raise RuntimeError("a loaded v1 phase must report warm")
            unbuildable_bm25["table"].add(
                pa.Table.from_pylist(_rows(3, 3), schema=CHUNKS_SCHEMA_V1)
            )
            # A regular file where the v2 index directory would go.
            (bm25_root / "v2").write_text("", encoding="utf-8")
            _write_marker(unbuildable_bm25["lance"], version=2, chunk_count=6)
            landed = await resources.refresh_corpus_if_stale(force=True)
            if resources.corpus_info is None:
                raise RuntimeError("rebind left the instance unbound")
            return (
                landed,
                resources.corpus_info.version,
                resources.bm25_phase,
                resources.bm25_phase_state,
            )
        finally:
            await resources.shutdown()

    landed, version, bm25_phase, state = asyncio.run(_scenario())
    assert landed is True
    assert version == 2
    assert bm25_phase is None
    assert state == "unavailable"
