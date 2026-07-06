"""Tests for ``server.paper_metadata_store`` (paper-metadata-m1).

Covers the t-store-schema acceptance (double-init no-op; additive +
atomic + re-runnable migration) and m1 AC2 (cold store reopen serves
metadata WITHOUT touching the LanceDB chunks table). All tests run on
``tmp_path`` SQLite files; async methods are driven via ``asyncio.run``
(the ``test_discover_for_notebook.py`` convention).
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
from pathlib import Path

import pytest

import server.paper_metadata_store as store_mod
from server.paper_metadata_store import (
    SCHEMA_VERSION,
    PaperMetadataRecord,
    PaperMetadataStore,
)


def _record(paper_id: str = "math/0212237", **overrides) -> PaperMetadataRecord:
    fields: dict = {
        "paper_id": paper_id,
        "title": "Stability conditions on triangulated categories",
        "authors": ("Tom Bridgeland",),
        "abstract": "This paper introduces the notion of a stability condition.",
        "year": 2002,
        "categories": ("math.AG", "math.CT"),
        "primary_category": "math.AG",
        "published": "2002-12-18T00:00:00Z",
        "fetched_at": "2026-07-05T00:00:00+00:00",
    }
    fields.update(overrides)
    return PaperMetadataRecord(**fields)


def _user_version(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


async def _open_write_close(db_path: Path, records: list[PaperMetadataRecord]) -> int:
    store = await PaperMetadataStore.open(db_path)
    try:
        return await store.upsert_records(records)
    finally:
        await store.close()


class TestStoreSchema:
    """t-store-schema: init twice → second run is a no-op with an
    unchanged schema-version row; migrations additive + re-runnable."""

    def test_double_init_is_noop(self, tmp_path: Path) -> None:
        db_path = tmp_path / "paper_metadata.db"
        asyncio.run(_open_write_close(db_path, [_record()]))
        version_after_first = _user_version(db_path)
        if version_after_first != SCHEMA_VERSION:
            raise AssertionError(
                f"first init left user_version={version_after_first}"
            )

        async def _reopen() -> tuple[int, PaperMetadataRecord | None]:
            store = await PaperMetadataStore.open(db_path)
            try:
                return await store.row_count(), await store.get("math/0212237")
            finally:
                await store.close()

        count, rec = asyncio.run(_reopen())
        # Second init: rows survive, version row untouched.
        assert count == 1
        assert rec is not None
        assert rec.title.startswith("Stability conditions")
        assert _user_version(db_path) == version_after_first == SCHEMA_VERSION

    def test_migration_is_rerunnable_without_data_loss(self, tmp_path: Path) -> None:
        """A file whose user_version lags its tables (the crash-window
        shape the atomic BEGIN/COMMIT prevents) must re-migrate cleanly:
        CREATE TABLE IF NOT EXISTS is a no-op and rows survive."""
        db_path = tmp_path / "paper_metadata.db"
        asyncio.run(_open_write_close(db_path, [_record()]))
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 0")
        conn.close()

        async def _reopen_count() -> int:
            store = await PaperMetadataStore.open(db_path)
            try:
                return await store.row_count()
            finally:
                await store.close()

        assert asyncio.run(_reopen_count()) == 1
        assert _user_version(db_path) == SCHEMA_VERSION

    def test_migration_never_drops_tables(self) -> None:
        """Additive-migration guard: the Tier-1 DROP-AND-RECREATE
        pattern must never appear in this store's source."""
        source = inspect.getsource(store_mod)
        assert "DROP TABLE" not in source


class TestUpsertAndRead:
    def test_upsert_is_idempotent_replace(self, tmp_path: Path) -> None:
        db_path = tmp_path / "paper_metadata.db"

        async def _scenario() -> tuple[int, PaperMetadataRecord | None]:
            store = await PaperMetadataStore.open(db_path)
            try:
                await store.upsert_records([_record(title="old title")])
                await store.upsert_records([_record(title="new title")])
                return await store.row_count(), await store.get("math/0212237")
            finally:
                await store.close()

        count, rec = asyncio.run(_scenario())
        assert count == 1
        assert rec is not None
        assert rec.title == "new title"

    def test_get_absent_returns_none(self, tmp_path: Path) -> None:
        async def _scenario() -> PaperMetadataRecord | None:
            store = await PaperMetadataStore.open(tmp_path / "m.db")
            try:
                return await store.get("2307.99999")
            finally:
                await store.close()

        assert asyncio.run(_scenario()) is None

    def test_round_trips_authors_and_categories(self, tmp_path: Path) -> None:
        rec_in = _record(
            paper_id="0708.2247",
            authors=("A. Bayer", "E. Macrì"),
            categories=("math.AG", "math.SG", "hep-th"),
        )

        async def _scenario() -> PaperMetadataRecord | None:
            store = await PaperMetadataStore.open(tmp_path / "m.db")
            try:
                await store.upsert_records([rec_in])
                return await store.get("0708.2247")
            finally:
                await store.close()

        rec = asyncio.run(_scenario())
        assert rec is not None
        assert rec.authors == ("A. Bayer", "E. Macrì")
        assert rec.categories == ("math.AG", "math.SG", "hep-th")
        assert rec.year == 2002

    def test_hydrated_paper_ids_requires_title_and_authors(
        self, tmp_path: Path,
    ) -> None:
        """The backfill's idempotency gate: empty-title / empty-author
        rows are NOT hydrated, so a re-run retries them."""

        async def _scenario() -> set[str]:
            store = await PaperMetadataStore.open(tmp_path / "m.db")
            try:
                await store.upsert_records([
                    _record(paper_id="2303.07061"),
                    _record(paper_id="2307.00001", title=""),
                    _record(paper_id="2307.00002", authors=()),
                ])
                return await store.hydrated_paper_ids()
            finally:
                await store.close()

        assert asyncio.run(_scenario()) == {"2303.07061"}


class TestColdReopen:
    """m1 AC2: after a process restart + cold reopen, metadata is
    served without touching the chunks table."""

    def test_cold_reopen_serves_metadata_without_chunks_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "notebooks" / "bridgeland-stability" / "paper_metadata.db"
        asyncio.run(
            _open_write_close(
                db_path,
                [_record(), _record(paper_id="0708.2247", title="Second paper")],
            )
        )

        # Simulate the restart-with-no-corpus environment: ANY LanceDB
        # connection attempt raises. There is also no chunks table on
        # disk anywhere under tmp_path.
        lancedb = pytest.importorskip("lancedb")

        def _boom(*_a, **_kw):
            raise RuntimeError(
                "chunks table touched on the metadata read path"
            )

        monkeypatch.setattr(lancedb, "connect", _boom)

        async def _cold_read() -> tuple[
            PaperMetadataRecord | None, PaperMetadataRecord | None,
        ]:
            store = await PaperMetadataStore.open(db_path)
            try:
                return await store.get("math/0212237"), await store.get("0708.2247")
            finally:
                await store.close()

        rec1, rec2 = asyncio.run(_cold_read())
        assert rec1 is not None and rec1.title and rec1.authors
        assert rec2 is not None and rec2.title == "Second paper"

    def test_store_module_has_no_chunks_table_dependency(self) -> None:
        """Structural regression: the store must stay self-contained —
        no LanceDB / corpus / chunks-table imports on any code path."""
        source = inspect.getsource(store_mod)
        assert "import lancedb" not in source
        assert "server.corpus" not in source
        assert "chunks_table" not in source
