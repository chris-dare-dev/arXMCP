"""A notebooks.db migration step either lands whole or not at all.

The store's connection is autocommit, so a step whose statements are not
wrapped in one transaction can stop half-applied: a column present while
``user_version`` still names the old schema. The next open then re-runs the
step, hits ``duplicate column name`` and the server cannot start. These tests
stop a step partway and check what the following open sees.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from arxmcp.corpus import notebooks_store
from arxmcp.corpus.notebooks_store import SCHEMA_VERSION, open_notebooks_db


def _version(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def _notebook_columns(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            row[1] for row in conn.execute("PRAGMA table_info(notebooks)")
        }
    finally:
        conn.close()


def test_a_step_that_fails_midway_rolls_back_and_the_next_open_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "notebooks.db"
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    class _FailsOnSecondParseColumn(sqlite3.Connection):
        """Fails the v3 -> v4 step after its first ALTER has run."""

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            opened.append(self)

        def execute(self, sql, *args):
            if "ADD COLUMN parse_error" in sql:
                raise sqlite3.OperationalError("injected: process died here")
            return super().execute(sql, *args)

    with monkeypatch.context() as m:
        m.setattr(
            notebooks_store.sqlite3,
            "connect",
            lambda *a, **kw: real_connect(
                *a, factory=_FailsOnSecondParseColumn, **kw
            ),
        )
        try:
            with pytest.raises(sqlite3.OperationalError, match="injected"):
                open_notebooks_db(db_path)
        finally:
            for conn in opened:
                conn.close()

    # The failed step left nothing behind: still v3, and none of the
    # step's columns, including the one whose ALTER did run.
    assert _version(db_path) == 3
    columns = _notebook_columns(db_path)
    assert "notebook_kind" in columns
    assert not {"parse_status", "parse_error", "parsed_html_path"} & columns

    # A notebook written while the file sits at v3 survives the retry.
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO notebooks (slug, display_name, lancedb_path, "
            "created_at) VALUES ('kept', 'Kept', '/x', '2026-01-01')"
        )
        conn.commit()
    finally:
        conn.close()

    conn = open_notebooks_db(db_path)
    try:
        row = conn.execute(
            "SELECT slug, parse_status, discovery_category FROM notebooks"
        ).fetchall()
    finally:
        conn.close()
    assert row == [("kept", "skipped", "")]
    assert _version(db_path) == SCHEMA_VERSION
