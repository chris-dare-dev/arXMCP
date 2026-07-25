"""agent-platform-t-semantic-identifiers (#84) — row title/year join.

Covers the enrichment helper against a REAL PaperMetadataStore (in a
tmp SQLite), so the version-normalization, LRU one-read-per-distinct,
null-safety, and Threat-2 wrapping are all exercised end to end.
"""

from __future__ import annotations

import asyncio

import pytest

from server.metadata_enrich import enrich_rows_with_titles
from server.paper_metadata_store import PaperMetadataRecord, PaperMetadataStore


def _run(coro):
    return asyncio.run(coro)


def _record(paper_id: str, title: str, year: int) -> PaperMetadataRecord:
    return PaperMetadataRecord(
        paper_id=paper_id,  # UNVERSIONED, per the store contract
        title=title,
        authors=("A. Author",),
        abstract="an abstract",
        year=year,
        categories=("math.AG",),
        primary_category="math.AG",
        published="2024-01-01",
        fetched_at="2024-01-02",
    )


@pytest.fixture
def store(tmp_path):
    s = _run(PaperMetadataStore.open(tmp_path / "paper_metadata.db"))
    _run(s.upsert_records([
        _record("math/0212237", "Stable Maps and Quantum Cohomology", 2002),
        _record("2401.00001", "A Paper With No Year", 0),  # year==0 sentinel
    ]))
    yield s
    _run(s.close())


class TestTitleJoin:
    def test_versioned_row_id_resolves_unversioned_record(self, store):
        """The store is keyed unversioned; a row paper_id with a vN
        suffix must still find its record (the highest-severity trap)."""
        rows = [{"paper_id": "math/0212237v1", "chunk_id": "c1"}]
        _run(enrich_rows_with_titles(store, rows))
        assert rows[0]["title"] is not None
        assert "Stable Maps" in rows[0]["title"]
        assert rows[0]["year"] == 2002

    def test_title_is_sanitized_and_wrapped(self, store):
        """Threat 2: title is arXiv-authored text, wrapped like snippet."""
        rows = [{"paper_id": "math/0212237", "chunk_id": "c1"}]
        _run(enrich_rows_with_titles(store, rows))
        assert "<retrieved_chunk" in rows[0]["title"]

    def test_year_zero_maps_to_null(self, store):
        rows = [{"paper_id": "2401.00001", "chunk_id": "c1"}]
        _run(enrich_rows_with_titles(store, rows))
        assert rows[0]["title"] is not None  # title present
        assert rows[0]["year"] is None       # but year==0 -> null

    def test_absent_paper_is_null_safe(self, store):
        rows = [{"paper_id": "9999.99999", "chunk_id": "c1"}]
        _run(enrich_rows_with_titles(store, rows))
        assert rows[0]["title"] is None
        assert rows[0]["year"] is None

    def test_store_none_is_null_safe(self):
        rows = [{"paper_id": "math/0212237", "chunk_id": "c1"}]
        _run(enrich_rows_with_titles(None, rows))
        assert rows[0] == {"paper_id": "math/0212237", "chunk_id": "c1",
                           "title": None, "year": None}

    def test_idempotent_skips_rows_with_title(self, store):
        rows = [{"paper_id": "math/0212237", "title": "PRESET", "year": 1999}]
        _run(enrich_rows_with_titles(store, rows))
        assert rows[0]["title"] == "PRESET"  # untouched
        assert rows[0]["year"] == 1999

    def test_every_row_gets_both_keys(self, store):
        """Byte-stability: title AND year present on every row regardless
        of hit/miss, so the response shape never varies."""
        rows = [
            {"paper_id": "math/0212237", "chunk_id": "c1"},
            {"paper_id": "9999.99999", "chunk_id": "c2"},
        ]
        _run(enrich_rows_with_titles(store, rows))
        for row in rows:
            assert "title" in row
            assert "year" in row


class TestOneReadPerDistinct:
    def test_distinct_ids_read_once_via_lru(self, store, monkeypatch):
        """Many rows sharing a paper_id must issue ONE store.get, and a
        repeat query must hit the LRU (zero further gets)."""
        calls = {"n": 0}
        real_get = store.get

        async def _counting_get(pid):
            calls["n"] += 1
            return await real_get(pid)

        monkeypatch.setattr(store, "get", _counting_get)

        rows = [
            {"paper_id": "math/0212237", "chunk_id": f"c{i}"} for i in range(5)
        ] + [
            {"paper_id": "math/0212237v1", "chunk_id": "cv"},  # same, versioned
            {"paper_id": "2401.00001", "chunk_id": "cd"},
        ]
        _run(enrich_rows_with_titles(store, rows))
        # 2 distinct normalized ids -> 2 reads (not 7).
        assert calls["n"] == 2

        # A second response for the same papers: LRU is warm -> 0 reads.
        calls["n"] = 0
        rows2 = [{"paper_id": "math/0212237", "chunk_id": "x"}]
        _run(enrich_rows_with_titles(store, rows2))
        assert calls["n"] == 0
