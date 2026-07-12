"""Tests for ``server.operator_settings`` (``onboarding-uplift-m2``).

Covers the m2 acceptance criteria for the new SQLite-backed key-value
store:

- AC9-a: schema-sentinel round trip + reopen idempotency.
- AC9-b: sync + async API parity.
- AC8 / synthesis FM-2: the in-table ``__schema_version__`` sentinel
  does NOT clobber ``PRAGMA user_version`` (which ``NotebooksStore``
  owns); the two stores coexist on the same ``notebooks.db`` file
  without crossing migration tracks.
- synthesis §3 D6 / FM-4: ``chmod 0o600`` applied on first file
  create; NOT applied retroactively.
- synthesis FM-1: WAL + busy_timeout discipline lets a CLI write
  succeed while a server-side connection is open against the same
  file.

These tests run by default in ``make test`` — no model load, no real
Lean / LaTeXML / arXiv hits; all path-local SQLite ops on ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

from server.operator_settings import (
    DEFAULT_DB_PATH,
    SCHEMA_VERSION,
    OperatorSettingsStore,
    delete_setting,
    get_contact_email,
    get_setting,
    set_setting,
)


def _run(coro):
    """Mirror the project test convention (cf. test_notebook_api.py)."""
    return asyncio.run(coro)


# ===========================================================================
# Synchronous API
# ===========================================================================


class TestSyncRoundTrip:
    def test_get_against_missing_file_returns_none(self, tmp_path: Path):
        """A CLI may call ``get_setting`` before any ``make init`` has
        ever populated the store; an absent file must NOT be a
        ``FileNotFoundError`` (would crash the priority-chain in
        ``tools/_notebook_common.py::resolve_contact_email``)."""
        db = tmp_path / "absent.db"
        assert get_setting("contact_email", db_path=db) is None
        # And the call DID NOT create the file as a side effect.
        assert not db.exists()

    def test_set_then_get_persists(self, tmp_path: Path):
        db = tmp_path / "notebooks.db"
        set_setting("contact_email", "me@example.com", db_path=db)
        assert get_setting("contact_email", db_path=db) == "me@example.com"

    def test_set_is_idempotent(self, tmp_path: Path):
        db = tmp_path / "notebooks.db"
        set_setting("contact_email", "a@x", db_path=db)
        set_setting("contact_email", "b@x", db_path=db)
        set_setting("contact_email", "b@x", db_path=db)
        assert get_setting("contact_email", db_path=db) == "b@x"

    def test_delete_returns_true_only_on_first_call(self, tmp_path: Path):
        db = tmp_path / "notebooks.db"
        set_setting("contact_email", "x@y", db_path=db)
        assert delete_setting("contact_email", db_path=db) is True
        assert delete_setting("contact_email", db_path=db) is False
        assert get_setting("contact_email", db_path=db) is None

    def test_delete_against_missing_file_returns_false(self, tmp_path: Path):
        assert delete_setting("contact_email", db_path=tmp_path / "no.db") is False

    def test_empty_value_permitted(self, tmp_path: Path):
        """Operators sometimes clear a pref (e.g. for environments where
        the env-var path should take over). Empty string must round-trip
        cleanly; ``None`` is reserved for ``delete_setting``."""
        db = tmp_path / "notebooks.db"
        set_setting("contact_email", "", db_path=db)
        assert get_setting("contact_email", db_path=db) == ""

    def test_get_contact_email_helper(self, tmp_path: Path):
        """``get_contact_email`` is the canonical reader the ``ingest/``
        modules call directly (synthesis §3 D3 — avoids
        ``ingest/ → tools/`` cross-import)."""
        db = tmp_path / "notebooks.db"
        assert get_contact_email(db) is None
        set_setting("contact_email", "ce@y", db_path=db)
        assert get_contact_email(db) == "ce@y"


class TestSyncKeyValidation:
    def test_non_string_key_rejected(self, tmp_path: Path):
        with pytest.raises(TypeError, match="must be str"):
            get_setting(42, db_path=tmp_path / "x.db")  # type: ignore[arg-type]

    def test_empty_key_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="non-empty"):
            set_setting("", "x", db_path=tmp_path / "x.db")

    def test_schema_version_key_is_reserved(self, tmp_path: Path):
        """``__schema_version__`` is the in-table sentinel for
        :data:`SCHEMA_VERSION`; the public API MUST refuse it so callers
        can't accidentally rewrite it and break migration tracking
        (m2 synthesis FM-2)."""
        db = tmp_path / "notebooks.db"
        with pytest.raises(ValueError, match="reserved"):
            set_setting("__schema_version__", "999", db_path=db)
        with pytest.raises(ValueError, match="reserved"):
            get_setting("__schema_version__", db_path=db)
        with pytest.raises(ValueError, match="reserved"):
            delete_setting("__schema_version__", db_path=db)

    def test_non_string_value_rejected(self, tmp_path: Path):
        with pytest.raises(TypeError, match="must be str"):
            set_setting("k", 42, db_path=tmp_path / "x.db")  # type: ignore[arg-type]


# ===========================================================================
# Async API parity with sync
# ===========================================================================


class TestAsyncAPIParity:
    def test_async_set_get_delete_round_trip(self, tmp_path: Path):
        db = tmp_path / "notebooks.db"

        async def _go():
            store = await OperatorSettingsStore.open(db)
            try:
                assert await store.get("k") is None
                await store.set("k", "v")
                assert await store.get("k") == "v"
                assert await store.delete("k") is True
                assert await store.delete("k") is False
                assert await store.get("k") is None
            finally:
                await store.close()

        _run(_go())

    def test_async_and_sync_share_data(self, tmp_path: Path):
        """A value written via the sync API must be readable via the
        async API and vice versa — both back onto the same
        ``operator_settings`` table in the same SQLite file."""
        db = tmp_path / "notebooks.db"
        set_setting("contact_email", "sync@example.com", db_path=db)

        async def _go():
            store = await OperatorSettingsStore.open(db)
            try:
                assert await store.get("contact_email") == "sync@example.com"
                await store.set("contact_email", "async@example.com")
            finally:
                await store.close()

        _run(_go())
        assert get_setting("contact_email", db_path=db) == "async@example.com"


# ===========================================================================
# Schema sentinel + coexistence with NotebooksStore
# ===========================================================================


class TestSchemaSentinel:
    def test_sentinel_row_seeded_on_first_open(self, tmp_path: Path):
        """``_apply_migrations`` writes the sentinel on first create
        and is idempotent against reopen — verified directly via
        sqlite3 (the public API refuses the reserved key)."""
        db = tmp_path / "notebooks.db"
        # First open via the sync path triggers the migration.
        set_setting("x", "y", db_path=db)
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT value FROM operator_settings "
                "WHERE key = '__schema_version__'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None and int(row[0]) == SCHEMA_VERSION

    def test_user_version_NOT_touched_by_operator_settings(
        self, tmp_path: Path
    ):
        """The m2 synthesis §3 D1 cardinal correctness point: this
        module MUST NOT touch ``PRAGMA user_version`` — that's
        ``NotebooksStore``'s migration tracker, and clobbering it would
        re-run the v0→v4 sequence and risk data loss on the
        ``notebooks`` table (synthesis FM-2)."""
        db = tmp_path / "notebooks.db"
        # First populate via OperatorSettingsStore alone.
        set_setting("contact_email", "x@y", db_path=db)
        conn = sqlite3.connect(str(db))
        try:
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        # OperatorSettingsStore must NEVER have called PRAGMA
        # user_version = N; the file's user_version stays 0 (default).
        assert user_version == 0, (
            f"OperatorSettingsStore set user_version={user_version}; "
            f"this would clobber NotebooksStore's migration tracker "
            f"and risk data loss on the notebooks table (synthesis FM-2)"
        )

    def test_coexists_with_notebooks_store_on_same_file(
        self, tmp_path: Path
    ):
        """Both stores open the SAME ``notebooks.db`` file and neither
        crashes nor corrupts the other's data — the cardinal
        independence guarantee from m2 synthesis §3 D1."""
        from server.notebooks_store import NotebooksStore

        db = tmp_path / "notebooks.db"

        # Open NotebooksStore first — its v0->v4 migration runs and
        # PRAGMA user_version goes to 4. Then OperatorSettingsStore
        # opens the same file; its in-table sentinel goes to 1
        # without touching user_version.
        async def _go():
            notebooks = await NotebooksStore.open(db)
            try:
                ops = await OperatorSettingsStore.open(db)
                try:
                    await ops.set("contact_email", "x@y")
                    assert await ops.get("contact_email") == "x@y"
                finally:
                    await ops.close()
            finally:
                await notebooks.close()

        _run(_go())

        # Verify both schema trackers ended up correct on the same file.
        conn = sqlite3.connect(str(db))
        try:
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            sentinel = conn.execute(
                "SELECT value FROM operator_settings "
                "WHERE key = '__schema_version__'"
            ).fetchone()
            # NotebooksStore owns PRAGMA user_version. Assert against the
            # live constant so a future schema bump (e.g. v4→v5 in
            # notebook-paper-discovery-m1) doesn't break this cross-store
            # coupling test.
            from server.notebooks_store import (
                SCHEMA_VERSION as NOTEBOOKS_SCHEMA_VERSION,
            )
            assert user_version == NOTEBOOKS_SCHEMA_VERSION
            assert sentinel is not None
            assert int(sentinel[0]) == SCHEMA_VERSION
            # And both tables are intact.
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "notebooks" in tables
            assert "operator_settings" in tables
        finally:
            conn.close()

    def test_reopen_after_migration_is_a_noop(self, tmp_path: Path):
        """Second open against a current-version file is idempotent;
        the sentinel row count stays at 1, the ``updated_at`` of the
        sentinel does NOT churn on every open."""
        db = tmp_path / "notebooks.db"
        set_setting("k", "v", db_path=db)
        # Snapshot the sentinel's updated_at after first open.
        conn = sqlite3.connect(str(db))
        try:
            row1 = conn.execute(
                "SELECT updated_at FROM operator_settings "
                "WHERE key = '__schema_version__'"
            ).fetchone()
        finally:
            conn.close()

        # Reopen via the sync path (no migration churn expected).
        get_setting("k", db_path=db)
        conn = sqlite3.connect(str(db))
        try:
            row2 = conn.execute(
                "SELECT updated_at FROM operator_settings "
                "WHERE key = '__schema_version__'"
            ).fetchone()
            sentinel_count = conn.execute(
                "SELECT COUNT(*) FROM operator_settings "
                "WHERE key = '__schema_version__'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert row1 == row2, (
            "sentinel updated_at changed across reopen — migration "
            "block is running on every open instead of just on version "
            "drift"
        )
        assert sentinel_count == 1


# ===========================================================================
# PII discipline: chmod 0o600 on first create
# ===========================================================================


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX file modes; Windows ACLs are out of scope",
)
class TestChmodOnFirstCreate:
    def test_first_create_chmod_0600(self, tmp_path: Path):
        """m2 synthesis §3 D6 / FM-4: the file holds operator email
        (PII); chmod 0o600 on FIRST create. Today's notebooks.db
        default perm is 0o644 (world-readable on default umask); this
        new store explicitly tightens it."""
        db = tmp_path / "notebooks.db"
        set_setting("contact_email", "x@y", db_path=db)
        mode = stat.S_IMODE(db.stat().st_mode)
        assert mode == 0o600, (
            f"first-create chmod 0o600 not applied; got 0o{mode:o}"
        )

    def test_pre_existing_file_perms_NOT_retroactively_changed(
        self, tmp_path: Path
    ):
        """The synthesis §3 D6 constraint: pre-existing files are
        NEVER retroactively chmodded. Operators may have set perms
        intentionally; silent tightening is a surprise."""
        db = tmp_path / "notebooks.db"
        # Pre-create the file with a deliberately permissive mode.
        db.touch()
        db.chmod(0o644)
        # Now use the store; the file already existed, so chmod must
        # NOT fire.
        set_setting("contact_email", "x@y", db_path=db)
        mode = stat.S_IMODE(db.stat().st_mode)
        assert mode == 0o644, (
            f"pre-existing file was retroactively chmodded to "
            f"0o{mode:o}; expected 0o644 unchanged"
        )


# ===========================================================================
# DEFAULT_DB_PATH is the expected canonical location
# ===========================================================================


class TestDefaults:
    def test_default_db_path_matches_var_arxmcp_cache(self):
        """The CLI helpers default to the same path Config uses for
        the notebooks DB. Drift between the two would silently store
        operator prefs in a different file than the server's reader."""
        # .as_posix() normalizes the separator so the logical-path check
        # holds on Windows (str(Path) yields backslashes there).
        assert DEFAULT_DB_PATH.as_posix() == "var/arxmcp/cache/notebooks.db"
