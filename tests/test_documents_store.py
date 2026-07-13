"""Tests for ``server.documents_store`` (source-truth-m1).

Mirrors ``tests/test_paper_metadata_store.py``: the schema-idempotency
acceptance (double-init no-op; additive + atomic + re-runnable
migration; never drops tables), upsert/read round-trips, the revision
PRIMARY KEY, the raw-source abstention marker round-trip, and the
cold-reopen self-containment (no chunks-table dependency). All tests run
on ``tmp_path`` SQLite files; async methods are driven via
``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
from pathlib import Path

import pytest

import server.documents_store as store_mod
from server.documents_store import (
    DOCUMENTS_SCHEMA_VERSION,
    RAW_SOURCE_STATUS_PRESENT,
    RAW_SOURCE_STATUS_UNAVAILABLE,
    DocumentRecord,
    DocumentsStore,
)


def _record(
    work_id: str = "0708.2247",
    arxiv_version: str = "",
    **overrides,
) -> DocumentRecord:
    fields: dict = {
        "work_id": work_id,
        "arxiv_version": arxiv_version,
        "raw_source_sha256": "a" * 64,
        "raw_source_status": RAW_SOURCE_STATUS_PRESENT,
        "parse_artifact_sha256": "b" * 64,
        "chunker_version": "v1.1",
        "parser_used": None,
        "latexml_version": None,
        "fetched_at": "2026-07-12T00:00:00+00:00",
        "license_uri": "http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
        "license_status": "not-allowlisted-open",
        "status": "active",
    }
    fields.update(overrides)
    return DocumentRecord(**fields)


def _abstention_record(work_id: str = "math/0212237") -> DocumentRecord:
    """An old-style row: NULL raw checksum + 'unavailable' status, but a
    real parse-artifact checksum (present for all id shapes)."""
    return _record(
        work_id=work_id,
        raw_source_sha256=None,
        raw_source_status=RAW_SOURCE_STATUS_UNAVAILABLE,
        parse_artifact_sha256="c" * 64,
        license_uri=None,
        license_status="unknown",
    )


def _user_version(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


async def _open_write_close(db_path: Path, records: list[DocumentRecord]) -> int:
    store = await DocumentsStore.open(db_path)
    try:
        return await store.upsert_records(records)
    finally:
        await store.close()


class TestStoreSchema:
    """init twice -> second run is a no-op with an unchanged
    schema-version row; migrations additive + re-runnable."""

    def test_double_init_is_noop(self, tmp_path: Path) -> None:
        db_path = tmp_path / "documents.db"
        asyncio.run(_open_write_close(db_path, [_record()]))
        version_after_first = _user_version(db_path)
        if version_after_first != DOCUMENTS_SCHEMA_VERSION:
            raise AssertionError(
                f"first init left user_version={version_after_first}"
            )

        async def _reopen() -> tuple[int, DocumentRecord | None]:
            store = await DocumentsStore.open(db_path)
            try:
                return await store.row_count(), await store.get("0708.2247")
            finally:
                await store.close()

        count, rec = asyncio.run(_reopen())
        assert count == 1
        assert rec is not None
        assert rec.license_status == "not-allowlisted-open"
        assert _user_version(db_path) == version_after_first == DOCUMENTS_SCHEMA_VERSION

    def test_migration_is_rerunnable_without_data_loss(self, tmp_path: Path) -> None:
        """A file whose user_version lags its tables (the crash-window
        shape the atomic BEGIN/COMMIT prevents) must re-migrate cleanly:
        CREATE TABLE IF NOT EXISTS is a no-op and rows survive."""
        db_path = tmp_path / "documents.db"
        asyncio.run(_open_write_close(db_path, [_record()]))
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 0")
        conn.close()

        async def _reopen_count() -> int:
            store = await DocumentsStore.open(db_path)
            try:
                return await store.row_count()
            finally:
                await store.close()

        assert asyncio.run(_reopen_count()) == 1
        assert _user_version(db_path) == DOCUMENTS_SCHEMA_VERSION

    def test_migration_never_drops_tables(self) -> None:
        """Additive-migration guard: the DROP-AND-RECREATE pattern must
        never appear in this store's source."""
        source = inspect.getsource(store_mod)
        assert "DROP TABLE" not in source


class TestUpsertAndRead:
    def test_upsert_is_idempotent_replace(self, tmp_path: Path) -> None:
        db_path = tmp_path / "documents.db"

        async def _scenario() -> tuple[int, DocumentRecord | None]:
            store = await DocumentsStore.open(db_path)
            try:
                await store.upsert_records([_record(license_status="unknown")])
                await store.upsert_records(
                    [_record(license_status="eligible")]
                )
                return await store.row_count(), await store.get("0708.2247")
            finally:
                await store.close()

        count, rec = asyncio.run(_scenario())
        assert count == 1  # same (work_id, '') PK — replaced, not appended
        assert rec is not None
        assert rec.license_status == "eligible"

    def test_get_absent_returns_none(self, tmp_path: Path) -> None:
        async def _scenario() -> DocumentRecord | None:
            store = await DocumentsStore.open(tmp_path / "d.db")
            try:
                return await store.get("2307.99999")
            finally:
                await store.close()

        assert asyncio.run(_scenario()) is None

    def test_distinct_versions_are_distinct_rows(self, tmp_path: Path) -> None:
        """The revision PRIMARY KEY: same work id + different explicit
        versions are two rows, not a collision."""

        async def _scenario() -> tuple[int, str | None, str | None]:
            store = await DocumentsStore.open(tmp_path / "d.db")
            try:
                await store.upsert_records([
                    _record(work_id="2006.10956", arxiv_version="v1"),
                    _record(
                        work_id="2006.10956",
                        arxiv_version="v2",
                        license_status="eligible",
                    ),
                ])
                r1 = await store.get("2006.10956", "v1")
                r2 = await store.get("2006.10956", "v2")
                return (
                    await store.row_count(),
                    r1.license_status if r1 else None,
                    r2.license_status if r2 else None,
                )
            finally:
                await store.close()

        count, s1, s2 = asyncio.run(_scenario())
        assert count == 2
        assert s1 == "not-allowlisted-open"
        assert s2 == "eligible"

    def test_registered_keys_returns_work_version_pairs(
        self, tmp_path: Path,
    ) -> None:
        async def _scenario() -> set[tuple[str, str]]:
            store = await DocumentsStore.open(tmp_path / "d.db")
            try:
                await store.upsert_records([
                    _record(work_id="0708.2247"),
                    _record(work_id="2006.10956", arxiv_version="v1"),
                    _abstention_record("math/0212237"),
                ])
                return await store.registered_keys()
            finally:
                await store.close()

        assert asyncio.run(_scenario()) == {
            ("0708.2247", ""),
            ("2006.10956", "v1"),
            ("math/0212237", ""),
        }


class TestAbstentionMarker:
    """OWNER DECISION A: the old-style raw-source gap is a documented
    NULL + status reason, NOT a silent hole — and it round-trips."""

    def test_abstention_marker_round_trips(self, tmp_path: Path) -> None:
        async def _scenario() -> DocumentRecord | None:
            store = await DocumentsStore.open(tmp_path / "d.db")
            try:
                await store.upsert_records([_abstention_record("math/0212237")])
                return await store.get("math/0212237")
            finally:
                await store.close()

        rec = asyncio.run(_scenario())
        assert rec is not None
        # raw source: NULL checksum travels WITH the explicit status.
        assert rec.raw_source_sha256 is None
        assert rec.raw_source_status == RAW_SOURCE_STATUS_UNAVAILABLE
        # parse artifact is still computed (present for all id shapes).
        assert rec.parse_artifact_sha256 == "c" * 64
        # NULL version stamps (m1 has no queryable per-paper signal).
        assert rec.parser_used is None
        assert rec.latexml_version is None
        # license gap distinct from the raw gap.
        assert rec.license_uri is None
        assert rec.license_status == "unknown"

    def test_old_style_prefix_preserved_as_work_id(self, tmp_path: Path) -> None:
        async def _scenario() -> tuple[DocumentRecord | None, DocumentRecord | None]:
            store = await DocumentsStore.open(tmp_path / "d.db")
            try:
                await store.upsert_records([_abstention_record("math/0212237")])
                # The versionless, prefix-intact id is the key; the
                # bare number is NOT a valid key.
                return (
                    await store.get("math/0212237"),
                    await store.get("0212237"),
                )
            finally:
                await store.close()

        with_prefix, without_prefix = asyncio.run(_scenario())
        assert with_prefix is not None
        assert without_prefix is None


class TestColdReopen:
    """After a process restart + cold reopen, the registry is served
    without touching the chunks table."""

    def test_cold_reopen_serves_without_chunks_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "notebooks" / "bridgeland-stability" / "documents.db"
        asyncio.run(
            _open_write_close(
                db_path,
                [_record(), _abstention_record("math/0212237")],
            )
        )

        # Simulate the restart-with-no-corpus environment: ANY LanceDB
        # connection attempt raises.
        lancedb = pytest.importorskip("lancedb")

        def _boom(*_a, **_kw):
            raise RuntimeError("chunks table touched on the registry read path")

        monkeypatch.setattr(lancedb, "connect", _boom)

        async def _cold_read() -> tuple[DocumentRecord | None, DocumentRecord | None]:
            store = await DocumentsStore.open(db_path)
            try:
                return (
                    await store.get("0708.2247"),
                    await store.get("math/0212237"),
                )
            finally:
                await store.close()

        rec1, rec2 = asyncio.run(_cold_read())
        assert rec1 is not None and rec1.parse_artifact_sha256
        assert rec2 is not None and rec2.raw_source_status == RAW_SOURCE_STATUS_UNAVAILABLE

    def test_store_module_has_no_chunks_table_dependency(self) -> None:
        """Structural regression: the store stays self-contained — no
        LanceDB / corpus / chunks-table / embedder imports."""
        source = inspect.getsource(store_mod)
        assert "import lancedb" not in source
        assert "server.corpus" not in source
        assert "chunks_table" not in source
        assert "embedder" not in source
