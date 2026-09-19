"""``get_paper`` ↔ per-notebook metadata-store wiring (paper-metadata m1→m2).

The Stage-2/3 integration reconciled two duplicate paper-metadata
implementations onto m1's per-notebook :class:`PaperMetadataStore` and
ported the ``get_paper`` overlay (previously arx-a45's central-store
overlay) onto it. These tests pin that wiring — the coverage the retired
``tests/test_paper_metadata.py`` §5 used to give, adapted to the
per-notebook store + the server-side notebook resolver:

- store-hit → ``metadata_status="notebook_metadata_store"`` with the real
  title/authors/abstract/year/categories (+primary_category/published);
- degraded fallback → ``metadata_status="synthesized_from_chunks"`` with
  NULL identity fields (the preserved v1 behavior — also pinned by
  ``tests/test_tools_all.py::test_get_paper_synthesized``);
- metadata-row-without-chunks → ``found: true, chunk_count: 0``;
- version-suffix normalization (query ``…v2`` resolves the unversioned row
  the m1 backfill keyed);
- resolver picks the right notebook across several on-disk notebooks.

Offline throughout: the chunks table is a fake Arrow-returning stand-in,
the per-notebook SQLite lives in ``tmp_path`` with ``NOTEBOOKS_BASE``
redirected there, and the store is seeded through the real
:class:`PaperMetadataStore` async API (each ``asyncio.run`` opens its own
connection + lock, so no lock crosses event loops).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pyarrow as pa
import pytest

import tools._notebook_common as _notebook_common
from server.paper_metadata_store import (
    PAPER_METADATA_DB_FILENAME,
    PaperMetadataRecord,
    PaperMetadataStore,
)

_TITLE = "Stability conditions on synthetic fixture surfaces"
_AUTHORS = ("A. Fixture", "B. Second")
_ABSTRACT = "We construct stability conditions on a synthetic surface."


# ---------------------------------------------------------------------------
# Fakes (mirror the retired arx-a45 get_paper harness)
# ---------------------------------------------------------------------------


def _empty_chunks_arrow() -> pa.Table:
    return pa.table({
        "section_path": pa.array([], type=pa.list_(pa.string())),
        "chunker_version": pa.array([], type=pa.string()),
        "embedder_version": pa.array([], type=pa.string()),
    })


def _one_chunk_arrow() -> pa.Table:
    return pa.table({
        "section_path": pa.array([["1 Intro"]], type=pa.list_(pa.string())),
        "chunker_version": pa.array(["v1.1"], type=pa.string()),
        "embedder_version": pa.array(["bge-m3"], type=pa.string()),
    })


class _FakeChunksTable:
    def __init__(self, arrow: pa.Table) -> None:
        self._arrow = arrow

    def search(self):  # noqa: ANN201
        return self

    def where(self, *_a, **_k):  # noqa: ANN201
        return self

    def limit(self, _n):  # noqa: ANN201
        return self

    def to_arrow(self) -> pa.Table:
        return self._arrow


def _install_fake_resources(arrow: pa.Table) -> None:
    from server.config import Config
    from server.tools import set_resources

    class _FakeCorpusInfo:
        version = 1

    class _FakeResources:
        config = Config()
        corpus_info = _FakeCorpusInfo()
        chunks_table = _FakeChunksTable(arrow)

    set_resources(_FakeResources())


def _seed_notebook_store(
    base: Path, slug: str, record: PaperMetadataRecord
) -> None:
    """Create ``base/<slug>/paper_metadata.db`` and upsert ``record``.

    Runs in its own event loop and fully closes the store before
    returning, so the connection + asyncio.Lock never outlive this call
    (the handler opens a fresh connection in its own loop).
    """
    nb_dir = base / slug
    nb_dir.mkdir(parents=True, exist_ok=True)
    db_path = nb_dir / PAPER_METADATA_DB_FILENAME

    async def _run() -> None:
        store = await PaperMetadataStore.open(db_path)
        try:
            await store.upsert_records([record])
        finally:
            await store.close()

    asyncio.run(_run())


def _record(paper_id: str = "2603.90001") -> PaperMetadataRecord:
    return PaperMetadataRecord(
        paper_id=paper_id,
        title=_TITLE,
        authors=_AUTHORS,
        abstract=_ABSTRACT,
        year=2026,
        categories=("math.AG", "math.NT"),
        primary_category="math.AG",
        published="2026-03-01T00:00:00Z",
        fetched_at="2026-07-05T00:00:00Z",
    )


def _call_get_paper(paper_id: str, arrow: pa.Table) -> dict:
    from server.handlers.paper import handle_get_paper

    async def _run() -> dict:
        _install_fake_resources(arrow)
        return await handle_get_paper(paper_id=paper_id)

    return asyncio.run(_run())


@pytest.fixture(autouse=True)
def _redirect_notebooks_base(tmp_path, monkeypatch):
    """Point NOTEBOOKS_BASE at tmp_path so the handler's resolver
    (iter_notebook_slugs + notebook_paper_metadata_db_path) enumerates
    only test notebooks."""
    base = tmp_path / "notebooks"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    return base


# ---------------------------------------------------------------------------
# Store-hit path
# ---------------------------------------------------------------------------


class TestGetPaperStoreHit:
    def test_store_hit_with_chunks(self, _redirect_notebooks_base):
        _seed_notebook_store(_redirect_notebooks_base, "alg-geom", _record())
        result = _call_get_paper("2603.90001", _one_chunk_arrow())

        assert result["found"] is True
        assert result["metadata_status"] == "notebook_metadata_store"
        paper = result["paper"]
        assert paper["title"] == _TITLE
        assert paper["authors"] == list(_AUTHORS)
        assert paper["abstract"] == _ABSTRACT
        assert paper["year"] == 2026
        assert paper["categories"] == ["math.AG", "math.NT"]
        # Richer m1 fields surfaced additively.
        assert paper["primary_category"] == "math.AG"
        assert paper["published"] == "2026-03-01T00:00:00Z"
        # Chunk synthesis is still real.
        assert paper["chunk_count"] == 1
        assert paper["section_count"] == 1
        assert paper["chunker_version"] == "v1.1"
        assert paper["embedder_version"] == "bge-m3"

    def test_metadata_row_without_chunks_is_found(
        self, _redirect_notebooks_base
    ):
        _seed_notebook_store(_redirect_notebooks_base, "alg-geom", _record())
        result = _call_get_paper("2603.90001", _empty_chunks_arrow())

        assert result["found"] is True
        assert result["metadata_status"] == "notebook_metadata_store"
        assert result["paper"]["chunk_count"] == 0
        assert result["paper"]["title"] == _TITLE

    def test_version_suffix_is_normalized(self, _redirect_notebooks_base):
        # Backfill keys the row UNVERSIONED; a versioned query must still
        # resolve it (server-side strip_id_version parity).
        _seed_notebook_store(_redirect_notebooks_base, "alg-geom", _record())
        result = _call_get_paper("2603.90001v2", _one_chunk_arrow())

        assert result["found"] is True
        assert result["metadata_status"] == "notebook_metadata_store"
        assert result["paper"]["title"] == _TITLE

    def test_resolver_finds_paper_across_multiple_notebooks(
        self, _redirect_notebooks_base
    ):
        # Two notebooks; only the second holds the paper. The resolver
        # must enumerate past the empty one and find the row.
        _seed_notebook_store(
            _redirect_notebooks_base, "aaa-other",
            _record(paper_id="1234.56789"),
        )
        _seed_notebook_store(
            _redirect_notebooks_base, "zzz-target", _record()
        )
        result = _call_get_paper("2603.90001", _one_chunk_arrow())

        assert result["found"] is True
        assert result["metadata_status"] == "notebook_metadata_store"
        assert result["paper"]["title"] == _TITLE


# ---------------------------------------------------------------------------
# Degraded / fallback path
# ---------------------------------------------------------------------------


class TestGetPaperSynthesizedFallback:
    def test_no_notebooks_synthesizes(self, _redirect_notebooks_base):
        # No notebook dirs at all → synthesized fallback with real chunks.
        result = _call_get_paper("2603.90001", _one_chunk_arrow())

        assert result["found"] is True
        assert result["metadata_status"] == "synthesized_from_chunks"
        assert result["paper"]["title"] is None
        assert result["paper"]["authors"] is None
        assert result["paper"]["primary_category"] is None
        assert result["paper"]["chunk_count"] == 1

    def test_store_present_but_paper_absent_stays_synthesized(
        self, _redirect_notebooks_base
    ):
        _seed_notebook_store(_redirect_notebooks_base, "alg-geom", _record())
        # A different paper — store exists, row does not.
        result = _call_get_paper("2401.00001", _one_chunk_arrow())

        assert result["found"] is True
        assert result["metadata_status"] == "synthesized_from_chunks"
        assert result["paper"]["title"] is None

    def test_no_row_no_chunks_not_found(self, _redirect_notebooks_base):
        _seed_notebook_store(_redirect_notebooks_base, "alg-geom", _record())
        result = _call_get_paper("9999.99999", _empty_chunks_arrow())

        assert result["found"] is False
        assert result["metadata_status"] == "synthesized_from_chunks"
        assert result["paper"] is None
