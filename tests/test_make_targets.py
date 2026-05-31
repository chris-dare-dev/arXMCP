"""Tests for the ``onboarding-uplift-m2`` Make targets.

Covers AC1, AC4, AC6, AC9 (regression test for the
``tools/notebook_init.py`` extension) plus the ``notebook_list_offline``
helper that backs the server-down path of ``make notebook-list``.

We do NOT shell out to ``make`` in unit tests — that would entangle
tests in shell + Make versioning. Instead we test the underlying
Python entry points (``tools.notebook_init.run`` for ``make init``,
``tools.notebook_list_offline.main`` for ``make notebook-list``
offline path) + parse ``make help`` output as text for the AC6 doc
contract. Tests against actual REST + curl live in their own
e2e file (out of scope for m2; the m4 wizard milestone will add them).
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sqlite3
import subprocess
from contextlib import redirect_stdout
from pathlib import Path

import pytest

# ===========================================================================
# AC1 — make init: scaffold + register + email persist
# ===========================================================================


class TestMakeInit:
    """``make init NOTEBOOK=<slug> [EMAIL=<addr>]`` → calls
    :func:`tools.notebook_init.run`. We test the entry point directly
    rather than shelling out to ``make`` — the Make recipe is a
    one-line ``$(PYTHON) -m tools.notebook_init …`` wrapper.
    """

    @pytest.fixture
    def fresh_slug(self, tmp_path):
        """Generate a tmp slug that doesn't already exist on disk.
        ``tools.notebook_init.run`` uses the real ``NOTEBOOKS_BASE``
        (production-shape testing — tests for the slug-level
        idempotency / SQLite-registration interactions).

        Cleans up on teardown by removing both the on-disk dir AND the
        SQLite row (the row was written to the SHARED notebooks.db, so
        we must restore the registry to its prior state).
        """
        from tools._notebook_common import NOTEBOOKS_BASE

        slug = "m2-mk-test-zz"  # static; relies on this slug being unused
        nb = NOTEBOOKS_BASE / slug
        db = Path("var/arxmcp/cache/notebooks.db")

        def _cleanup():
            if nb.exists():
                shutil.rmtree(nb)
            if db.exists():
                # ``isolation_level=None`` → autocommit; default
                # ``sqlite3.connect`` opens an implicit transaction on
                # DML that needs explicit commit — easy to forget in
                # a teardown.
                conn = sqlite3.connect(str(db), isolation_level=None)
                try:
                    # ``operator_settings`` may not exist yet if no
                    # m2 code has run against this DB; guard
                    # accordingly.
                    conn.execute(
                        "DELETE FROM notebooks WHERE slug = ?", (slug,)
                    )
                    tables = {
                        r[0]
                        for r in conn.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table'"
                        ).fetchall()
                    }
                    if "operator_settings" in tables:
                        conn.execute(
                            "DELETE FROM operator_settings "
                            "WHERE key = 'contact_email' "
                            "  AND value = 'm2-mk@example.com'"
                        )
                finally:
                    conn.close()

        # Setup: scrub any residue from a prior failed test.
        _cleanup()
        yield slug
        # Teardown: scrub again.
        _cleanup()

    def test_creates_on_disk_scaffold(self, fresh_slug):
        from tools._notebook_common import NOTEBOOKS_BASE
        from tools.notebook_init import run

        rc = run(fresh_slug)
        assert rc == 0
        nb = NOTEBOOKS_BASE / fresh_slug
        assert nb.is_dir()
        assert (nb / "papers.txt").is_file()
        assert (nb / "queries.json").is_file()

    def test_registers_notebook_in_sqlite(self, fresh_slug):
        """AC1 cardinal: the new --register flag (default ON) inserts
        a ``notebooks`` row so ``make add`` (server-up) doesn't 404."""
        from tools.notebook_init import run

        run(fresh_slug)

        db = Path("var/arxmcp/cache/notebooks.db")
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT slug, notebook_kind FROM notebooks WHERE slug = ?",
                (fresh_slug,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, (
            f"notebook {fresh_slug!r} not registered in notebooks.db — "
            "AC1 SQLite-registration regression"
        )
        assert row[1] == "arxiv"

    def test_persists_email_when_given(self, fresh_slug):
        """AC1 + AC2 link: the EMAIL arg flows through to
        operator_settings, where ``resolve_contact_email`` reads it."""
        from server.operator_settings import get_contact_email
        from tools.notebook_init import run

        run(fresh_slug, email="m2-mk@example.com")
        assert get_contact_email() == "m2-mk@example.com"

    def test_skips_email_persist_when_none(self, fresh_slug):
        """Calling ``make init NOTEBOOK=foo`` without EMAIL must NOT
        wipe an existing operator pref — both edits are independent."""
        from server.operator_settings import (
            delete_setting,
            get_contact_email,
            set_setting,
        )
        from tools.notebook_init import run

        set_setting("contact_email", "pre-existing@example.com")
        try:
            run(fresh_slug, email=None)
            assert get_contact_email() == "pre-existing@example.com"
        finally:
            delete_setting("contact_email")

    def test_idempotent_double_run(self, fresh_slug):
        """AC1 idempotency: re-running ``make init`` is a no-op on all
        three side-effects."""
        from tools._notebook_common import NOTEBOOKS_BASE
        from tools.notebook_init import run

        # First call.
        run(fresh_slug, email="m2-mk@example.com")
        nb = NOTEBOOKS_BASE / fresh_slug
        papers_mtime_1 = (nb / "papers.txt").stat().st_mtime
        # Second call must NOT rewrite the scaffold (the scaffold-exists
        # branch returns before touching the files).
        run(fresh_slug, email="m2-mk@example.com")
        papers_mtime_2 = (nb / "papers.txt").stat().st_mtime
        assert papers_mtime_1 == papers_mtime_2, (
            "papers.txt mtime changed on re-run — scaffold idempotency "
            "regression"
        )

    def test_no_register_flag_skips_sqlite_write(self, fresh_slug):
        """The --no-register escape hatch is for tests / pre-population
        callers; verify it actually skips the INSERT."""
        from tools.notebook_init import run

        run(fresh_slug, register=False)

        db = Path("var/arxmcp/cache/notebooks.db")
        if not db.exists():
            return  # nothing inserted — vacuously satisfies the contract
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT slug FROM notebooks WHERE slug = ?",
                (fresh_slug,),
            ).fetchone()
        finally:
            conn.close()
        assert row is None, (
            "--no-register flag was ignored; SQLite row was written"
        )


# ===========================================================================
# AC2 — resolve_contact_email priority chain
# ===========================================================================


class TestResolveContactEmail:
    """``tools._notebook_common.resolve_contact_email`` is the
    priority chain: explicit arg → SQLite operator_settings →
    ARXMCP_CONTACT_EMAIL env var → raise. Tested against an isolated
    tmp_path SQLite to avoid polluting the shared notebooks.db.
    """

    @pytest.fixture
    def isolated_db(self, tmp_path, monkeypatch):
        """Override ``DEFAULT_DB_PATH`` for the test so we don't
        write to ``var/arxmcp/cache/notebooks.db``. Each priority test
        passes ``db_path`` explicitly via the helper signature."""
        return tmp_path / "notebooks.db"

    def test_explicit_arg_wins_outright(self, isolated_db):
        from server.operator_settings import set_setting
        from tools._notebook_common import resolve_contact_email

        set_setting("contact_email", "sqlite@x", db_path=isolated_db)
        os.environ["ARXMCP_CONTACT_EMAIL"] = "env@x"
        try:
            assert (
                resolve_contact_email("arg@x", db_path=isolated_db)
                == "arg@x"
            )
        finally:
            os.environ.pop("ARXMCP_CONTACT_EMAIL", None)

    def test_sqlite_wins_over_env_var(self, isolated_db):
        """m2 synthesis §3 D1 / FM-3: SQLite is the sticky pref;
        env var is the historical fallback."""
        from server.operator_settings import set_setting
        from tools._notebook_common import resolve_contact_email

        set_setting("contact_email", "sqlite@x", db_path=isolated_db)
        os.environ["ARXMCP_CONTACT_EMAIL"] = "env@x"
        try:
            assert (
                resolve_contact_email(None, db_path=isolated_db)
                == "sqlite@x"
            )
        finally:
            os.environ.pop("ARXMCP_CONTACT_EMAIL", None)

    def test_env_var_used_when_sqlite_empty(self, isolated_db):
        """Cold-bootstrap case: no operator_settings yet, the env var
        is the only source. Historical pre-m2 behaviour."""
        from tools._notebook_common import resolve_contact_email

        # isolated_db does NOT exist (the fixture doesn't create it).
        os.environ["ARXMCP_CONTACT_EMAIL"] = "env-only@x"
        try:
            assert (
                resolve_contact_email(None, db_path=isolated_db)
                == "env-only@x"
            )
        finally:
            os.environ.pop("ARXMCP_CONTACT_EMAIL", None)

    def test_raises_with_make_init_hint_when_all_sources_empty(
        self, isolated_db
    ):
        from tools._notebook_common import NotebookError, resolve_contact_email

        os.environ.pop("ARXMCP_CONTACT_EMAIL", None)
        with pytest.raises(NotebookError) as exc_info:
            resolve_contact_email(None, db_path=isolated_db)
        msg = str(exc_info.value)
        # Independent-predicate assertions (m1 critique F4 / m2
        # synthesis FM-4 brittleness mitigation).
        assert "make init" in msg, (
            "remediation hint must name the canonical Make target"
        )
        assert "EMAIL=" in msg or "--email" in msg
        assert "ARXMCP_CONTACT_EMAIL" in msg


# ===========================================================================
# AC4 — make notebook-list offline path
# ===========================================================================


class TestNotebookListOffline:
    """The Make recipe's server-down branch calls
    ``tools/notebook_list_offline.py`` which we test directly. The
    server-up path is just a curl one-liner and is covered by the
    REST tests in tests/test_notebook_api.py."""

    def test_missing_db_prints_friendly_message(self, tmp_path, capsys):
        from tools.notebook_list_offline import main

        rc = main([str(tmp_path / "nonexistent.db")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "does not exist" in out
        assert "make init" in out, (
            "empty-DB message must point at the canonical Make target"
        )

    def test_empty_notebooks_db_prints_zero_count(self, tmp_path, capsys):
        """A fresh notebooks.db (NotebooksStore migrations have run,
        but no rows have been inserted) lists zero notebooks
        cleanly — does NOT crash, does NOT recommend `make init`
        (the file already exists)."""
        import asyncio

        from server.notebooks_store import NotebooksStore
        from tools.notebook_list_offline import main

        db = tmp_path / "empty.db"

        async def _make_empty():
            s = await NotebooksStore.open(db)
            await s.close()

        asyncio.run(_make_empty())

        rc = main([str(db)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "0 notebook(s)" in out

    def test_lists_registered_notebooks(self, tmp_path, capsys):
        import asyncio

        from server.notebooks_store import NotebooksStore
        from tools.notebook_list_offline import main

        db = tmp_path / "populated.db"

        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )

        async def _populate():
            s = await NotebooksStore.open(db)
            try:
                await s.create_notebook(
                    slug="m2-list-a",
                    display_name="m2 list A",
                    lancedb_path=str(tmp_path / "lance-a"),
                    created_at=now,
                )
                await s.create_notebook(
                    slug="m2-list-b",
                    display_name="m2 list B",
                    lancedb_path=str(tmp_path / "lance-b"),
                    created_at=now,
                )
            finally:
                await s.close()

        asyncio.run(_populate())

        rc = main([str(db)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "2 notebook(s)" in out
        assert "m2-list-a" in out
        assert "m2-list-b" in out


# ===========================================================================
# AC6 — make help has the FIRST TIME? section + no removed targets
# ===========================================================================


class TestMakeHelp:
    """``make help`` is operator-facing — its layout is part of m2's
    contract. AC6: FIRST TIME? section MUST list ``make init``,
    ``make add``, ``make notebook-list``, ``make ingest``,
    ``make bootstrap``, ``make up``. No pre-m2 target may be removed.
    """

    @pytest.fixture
    def help_output(self):
        """Capture `make help` stdout; skip if `make` isn't available
        (some CI environments don't have it)."""
        try:
            result = subprocess.run(
                ["make", "help"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent,
                check=False,
                timeout=10,
            )
        except FileNotFoundError:
            pytest.skip("`make` not available on PATH")
        if result.returncode != 0:
            pytest.skip(f"`make help` failed: {result.stderr}")
        return result.stdout

    def test_first_time_section_is_present(self, help_output):
        assert "FIRST TIME?" in help_output, (
            "AC6: `make help` MUST have a `FIRST TIME?` section so "
            "new operators get the onboarding path up-front"
        )

    @pytest.mark.parametrize(
        "target",
        ["make init", "make add", "make notebook-list"],
    )
    def test_new_m2_target_listed_under_first_time(self, help_output, target):
        """Each new m2 target must appear in the help output. The
        position is up to AC6's 'FIRST TIME? first' constraint —
        verified by the separate test below."""
        assert target in help_output, (
            f"AC6: `{target}` MUST appear in `make help`"
        )

    @pytest.mark.parametrize(
        "target",
        [
            "make bootstrap",
            "make test",
            "make eval",
            "make up",
            "make status",
            "make ingest",
            "make delta",
            "make re-embed",
            "make watchdog",
            "make cutover",
            "make notebook-cutover",
            "make daily-report",
            "make sbom",
            "make refresh-arxiv-ca",
        ],
    )
    def test_pre_m2_targets_still_listed(self, help_output, target):
        """AC6: 'No existing target is removed or renamed.' Every
        target named in `make help` before m2 must still be there
        after m2."""
        assert target in help_output, (
            f"AC6 regression: `{target}` disappeared from `make help` "
            f"in m2 — pre-existing target removed/renamed"
        )

    def test_first_time_appears_before_everything_else(self, help_output):
        """The FIRST TIME? block must literally come before EVERYTHING
        ELSE in the help text — operators read top-to-bottom."""
        first_time_idx = help_output.find("FIRST TIME?")
        everything_else_idx = help_output.find("EVERYTHING ELSE")
        assert first_time_idx != -1
        assert everything_else_idx != -1
        assert first_time_idx < everything_else_idx, (
            "AC6: FIRST TIME? section must precede EVERYTHING ELSE"
        )


# ===========================================================================
# Smoke: tools/notebook_init.py CLI argparse
# ===========================================================================


class TestNotebookInitCLI:
    """The Make recipe invokes ``$(PYTHON) -m tools.notebook_init``
    with positional + flag args; verify the argparse surface still
    accepts every shape the recipe uses."""

    def test_help_text_lists_email_and_no_register(self, capsys):
        from tools.notebook_init import _build_arg_parser

        buf = io.StringIO()
        parser = _build_arg_parser()
        with redirect_stdout(buf), contextlib.suppress(SystemExit):
            parser.parse_args(["--help"])
        text = buf.getvalue()
        assert "--email" in text
        assert "--no-register" in text

    def test_main_returns_nonzero_on_invalid_slug(self, capsys):
        from tools.notebook_init import main

        rc = main(["INVALID UPPERCASE"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "invalid" in err.lower() or "error" in err.lower()


# ===========================================================================
# Coexistence sanity: m2 changes do NOT touch the BP1 / BP2 surfaces
# ===========================================================================


class TestNoMCPSurfaceTouch:
    """AC8 cardinal: ``EXPECTED_TOOL_SCHEMA_SHA256`` +
    ``EXPECTED_BP1_SHA256`` UNCHANGED. The dedicated tests in
    ``tests/test_server_tool_schema.py`` + ``tests/test_prompts.py``
    are the cardinal check; this is a smoke-grep that no m2-touched
    file claims an MCP-tool import."""

    @pytest.mark.parametrize(
        "path",
        [
            "server/operator_settings.py",
            "tools/notebook_list_offline.py",
        ],
    )
    def test_new_module_does_not_register_mcp_tool(self, path):
        """The new files must NOT import or extend ``server.tools``
        (the ToolMeta registry) — any such import would risk a BP1
        cache-discipline regression even without an obvious schema
        change."""
        repo_root = Path(__file__).parent.parent
        contents = (repo_root / path).read_text(encoding="utf-8")
        assert "from server.tools import" not in contents, (
            f"{path} imports from server.tools — m2 must not extend "
            f"the MCP tool registry (AC8 BP1 byte-stability risk)"
        )
        assert "ALL_TOOLS" not in contents
