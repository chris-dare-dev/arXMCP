"""Tests for the E11_S05 restore drill smoke check.

Pure unit tests with synthetic LanceDB / Kùzu (no restic
invocation; the drill SCRIPT calls restic, the CHECK module
operates on a path on disk).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ops.restore_drill_check import (
    run_check,
    smoke_check_kuzu,
    smoke_check_lancedb,
    smoke_check_notebooks,
    write_pass_sentinel,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _seed_notebook_tree(
    root: Path, *, slug: str = "shimura", with_db: bool = True, pdfs: int = 1
) -> Path:
    """Build a restic-restore-shaped tree: an absolute source prefix under
    ``root`` containing var/arxmcp/cache/notebooks.db + uploaded PDFs.
    Returns the notebooks.db path (even if not created)."""
    import sqlite3

    prefix = root / "opt" / "arxmcp" / "var" / "arxmcp"
    cache = prefix / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    db_path = cache / "notebooks.db"
    if with_db:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE notebooks (slug TEXT PRIMARY KEY, "
                "display_name TEXT)"
            )
            conn.execute(
                "INSERT INTO notebooks VALUES (?, ?)", (slug, "Shimura")
            )
            conn.commit()
        finally:
            conn.close()
    pdfdir = prefix / "notebooks" / slug / "pdfs"
    pdfdir.mkdir(parents=True, exist_ok=True)
    for i in range(pdfs):
        (pdfdir / f"paper{i}.pdf").write_bytes(b"%PDF-1.5 synthetic " + bytes([i]))
    return db_path


# ---------------------------------------------------------------------------
# write_pass_sentinel
# ---------------------------------------------------------------------------


class TestWritePassSentinel:
    def test_writes_atomic_json_with_required_fields(self, tmp_path):
        flag = tmp_path / "drill.flag"
        write_pass_sentinel(
            flag_path=flag,
            snapshot_id="abc12345",
            restore_path=tmp_path / "restore",
            lancedb_row_count=1000,
            kuzu_paper_count=42,
        )
        payload = json.loads(flag.read_text())
        assert payload["smoke_check"] == "passed"
        assert payload["snapshot_id"] == "abc12345"
        assert payload["lancedb_row_count"] == 1000
        assert payload["kuzu_paper_count"] == 42

    def test_handles_kuzu_absent(self, tmp_path):
        flag = tmp_path / "drill.flag"
        write_pass_sentinel(
            flag_path=flag,
            snapshot_id="abc12345",
            restore_path=tmp_path / "restore",
            lancedb_row_count=1000,
            kuzu_paper_count=None,
        )
        payload = json.loads(flag.read_text())
        assert payload["kuzu_paper_count"] is None


# ---------------------------------------------------------------------------
# smoke_check_lancedb
# ---------------------------------------------------------------------------


class TestSmokeCheckLancedb:
    def test_raises_when_lancedb_dir_missing(self, tmp_path):
        with pytest.raises(RuntimeError, match="missing"):
            smoke_check_lancedb(tmp_path / "restore")

    def test_passes_with_mocked_table(self, tmp_path):
        """Synthetic: stub read_corpus_version + open_chunks_table
        so the smoke check verifies the integration shape without
        a real LanceDB."""
        lancedb = tmp_path / "var" / "arxmcp" / "index" / "lancedb"
        lancedb.mkdir(parents=True)
        (lancedb / "corpus-version.json").write_text(
            json.dumps({"version": 7, "chunker_version": "v1.0",
                        "embedder_version": "bge-m3@x"})
        )

        class _FakeInfo:
            version = 7

        class _FakeTable:
            def count_rows(self):
                return 1234

        with (
            patch(
                "server.corpus.read_corpus_version",
                return_value=_FakeInfo(),
            ),
            patch(
                "server.corpus.open_chunks_table",
                return_value=_FakeTable(),
            ),
        ):
            rows = smoke_check_lancedb(tmp_path)
        assert rows == 1234

    def test_raises_when_zero_rows(self, tmp_path):
        lancedb = tmp_path / "var" / "arxmcp" / "index" / "lancedb"
        lancedb.mkdir(parents=True)
        (lancedb / "corpus-version.json").write_text(
            json.dumps({"version": 7, "chunker_version": "v1.0",
                        "embedder_version": "bge-m3@x"})
        )

        class _FakeInfo:
            version = 7

        class _FakeTable:
            def count_rows(self):
                return 0

        with (
            patch(
                "server.corpus.read_corpus_version",
                return_value=_FakeInfo(),
            ),
            patch(
                "server.corpus.open_chunks_table",
                return_value=_FakeTable(),
            ),
            pytest.raises(RuntimeError, match="zero rows"),
        ):
            smoke_check_lancedb(tmp_path)

    def test_finds_lancedb_under_absolute_path_prefix(self, tmp_path):
        """Closes adversary F1: restic restores preserve the
        absolute source path under --target. The check must
        find the LanceDB even when it's nested deep under
        ``<restore>/opt/arxmcp/var/arxmcp/index/lancedb`` rather
        than at the previously-hardcoded
        ``<restore>/var/arxmcp/index/lancedb``."""
        # Simulate the post-restore layout for a backup of
        # /opt/arxmcp/var/arxmcp/index/lancedb restored to
        # tmp_path.
        deep = tmp_path / "opt" / "arxmcp" / "var" / "arxmcp" / "index" / "lancedb"
        deep.mkdir(parents=True)
        (deep / "corpus-version.json").write_text(
            json.dumps(
                {
                    "version": 42,
                    "chunker_version": "v1.0",
                    "embedder_version": "bge-m3@x",
                }
            )
        )

        class _FakeInfo:
            version = 42

        class _FakeTable:
            def count_rows(self):
                return 999

        with (
            patch(
                "server.corpus.read_corpus_version",
                return_value=_FakeInfo(),
            ),
            patch(
                "server.corpus.open_chunks_table",
                return_value=_FakeTable(),
            ),
        ):
            rows = smoke_check_lancedb(tmp_path)
        assert rows == 999


# ---------------------------------------------------------------------------
# smoke_check_kuzu
# ---------------------------------------------------------------------------


class TestSmokeCheckKuzu:
    def test_returns_none_when_kuzu_dir_absent(self, tmp_path):
        # No kuzu directory at all.
        assert smoke_check_kuzu(tmp_path) is None


# ---------------------------------------------------------------------------
# run_check end-to-end
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# smoke_check_notebooks (notebook-ops-hardening-m1)
# ---------------------------------------------------------------------------


class TestSmokeCheckNotebooks:
    def test_found_with_pdfs(self, tmp_path):
        _seed_notebook_tree(tmp_path, pdfs=2)
        found, pdf_count = smoke_check_notebooks(tmp_path)
        assert found is True
        assert pdf_count == 2

    def test_absent_is_not_an_error(self, tmp_path):
        """A pre-m1 snapshot (no notebooks.db) must NOT fail the drill."""
        found, pdf_count = smoke_check_notebooks(tmp_path)
        assert found is False
        assert pdf_count == 0

    def test_pdfs_counted_even_without_db(self, tmp_path):
        _seed_notebook_tree(tmp_path, with_db=False, pdfs=3)
        found, pdf_count = smoke_check_notebooks(tmp_path)
        assert found is False
        assert pdf_count == 3

    def test_found_via_absolute_path_prefix(self, tmp_path):
        """rglob discovery must find notebooks.db under the restic absolute
        source prefix (the F1-closure pattern), not only at the root."""
        _seed_notebook_tree(tmp_path, pdfs=1)
        # db lives at tmp/opt/arxmcp/var/arxmcp/cache/notebooks.db
        found, _ = smoke_check_notebooks(tmp_path)
        assert found is True

    def test_corrupt_db_raises(self, tmp_path):
        """A notebooks.db that exists but fails integrity_check is a real
        backup failure → RuntimeError (caught by run_check as exit 1)."""
        db_path = _seed_notebook_tree(tmp_path, with_db=True, pdfs=0)
        # Corrupt the file: overwrite the SQLite header with garbage.
        db_path.write_bytes(b"this is not a sqlite database at all" * 4)
        with pytest.raises(RuntimeError, match="integrity_check"):
            smoke_check_notebooks(tmp_path)


class TestRunCheck:
    def test_success_writes_sentinel(self, tmp_path):
        lancedb = tmp_path / "var" / "arxmcp" / "index" / "lancedb"
        lancedb.mkdir(parents=True)
        (lancedb / "corpus-version.json").write_text(
            json.dumps({"version": 42, "chunker_version": "v1.0",
                        "embedder_version": "bge-m3@x"})
        )

        class _FakeInfo:
            version = 42

        class _FakeTable:
            def count_rows(self):
                return 500

        with (
            patch(
                "server.corpus.read_corpus_version",
                return_value=_FakeInfo(),
            ),
            patch(
                "server.corpus.open_chunks_table",
                return_value=_FakeTable(),
            ),
        ):
            flag = tmp_path / "drill.flag"
            rc = run_check(
                restore_path=tmp_path,
                snapshot_id="xyz98765",
                flag_path=flag,
            )
        assert rc == 0
        assert flag.is_file()
        payload = json.loads(flag.read_text())
        assert payload["smoke_check"] == "passed"
        assert payload["snapshot_id"] == "xyz98765"
        assert payload["lancedb_row_count"] == 500

    def test_failure_exits_nonzero_no_sentinel(self, tmp_path):
        # No LanceDB directory at all → smoke check raises.
        flag = tmp_path / "drill.flag"
        rc = run_check(
            restore_path=tmp_path,
            snapshot_id="zzz",
            flag_path=flag,
        )
        assert rc == 1
        assert not flag.is_file()

    def test_sentinel_carries_notebook_fields(self, tmp_path):
        """notebook-ops-hardening-m1: run_check threads the notebook smoke
        check into the sentinel (notebooks_db_found + notebook_pdf_count)."""
        lancedb = tmp_path / "var" / "arxmcp" / "index" / "lancedb"
        lancedb.mkdir(parents=True)
        (lancedb / "corpus-version.json").write_text(
            json.dumps({"version": 1, "chunker_version": "v1",
                        "embedder_version": "bge-m3@x"})
        )
        _seed_notebook_tree(tmp_path, pdfs=2)

        class _FakeInfo:
            version = 1

        class _FakeTable:
            def count_rows(self):
                return 7

        with (
            patch("server.corpus.read_corpus_version",
                  return_value=_FakeInfo()),
            patch("server.corpus.open_chunks_table",
                  return_value=_FakeTable()),
        ):
            flag = tmp_path / "drill.flag"
            rc = run_check(
                restore_path=tmp_path,
                snapshot_id="nb000001",
                flag_path=flag,
            )
        assert rc == 0
        payload = json.loads(flag.read_text())
        assert payload["notebooks_db_found"] is True
        assert payload["notebook_pdf_count"] == 2


# ---------------------------------------------------------------------------
# Restore-drill shell script hygiene
# ---------------------------------------------------------------------------


class TestRestoreDrillScript:
    script = REPO_ROOT / "ops" / "restore_drill.sh"

    def test_script_exists_and_executable(self):
        assert self.script.is_file()
        assert os.access(self.script, os.X_OK)

    def test_set_euo_pipefail(self):
        text = self.script.read_text(encoding="utf-8")
        assert "set -euo pipefail" in text

    def test_no_hardcoded_user_path(self):
        text = self.script.read_text(encoding="utf-8")
        assert "/Users/" not in text

    def test_writes_pass_flag(self):
        text = self.script.read_text(encoding="utf-8")
        assert "restore-drill-passed.flag" in text

    def test_invokes_restore_drill_check(self):
        text = self.script.read_text(encoding="utf-8")
        assert "ops.restore_drill_check" in text

    def test_runs_read_data_subset_check(self):
        """notebook-ops-hardening-m1: the drill verifies pack-file
        integrity via restic check --read-data-subset=5%."""
        text = self.script.read_text(encoding="utf-8")
        assert "restic check --read-data-subset=5%" in text

    def test_parses_under_bash_n(self):
        import shutil
        import subprocess as _sp

        bash = shutil.which("bash")
        if bash is None:  # pragma: no cover
            pytest.skip("bash not on PATH")
        result = _sp.run(
            [bash, "-n", str(self.script)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Backup-restore runbook content
# ---------------------------------------------------------------------------


class TestBackupRestoreRunbook:
    runbook = REPO_ROOT / "docs" / "ops" / "backup-restore.md"

    def test_runbook_exists(self):
        assert self.runbook.is_file()

    def test_documents_retention_policy(self):
        text = self.runbook.read_text(encoding="utf-8")
        # Synthesis: 7 daily, 4 weekly, 12 monthly.
        assert "7 daily" in text.lower() or "--keep-daily 7" in text
        assert "4 weekly" in text.lower() or "--keep-weekly 4" in text
        assert "12 monthly" in text.lower() or "--keep-monthly 12" in text

    def test_warns_about_password_loss(self):
        text = self.runbook.read_text(encoding="utf-8")
        assert (
            "password" in text.lower()
            and ("loss" in text.lower() or "unrecoverable" in text.lower())
        )

    def test_documents_restore_drill(self):
        text = self.runbook.read_text(encoding="utf-8")
        assert "restore drill" in text.lower() or "restore_drill" in text
        assert "restore-drill-passed.flag" in text

    def test_documents_notebook_backup_scope(self):
        """notebook-ops-hardening-m1: the runbook must list the notebook
        data + metadata paths now in scope."""
        text = self.runbook.read_text(encoding="utf-8")
        assert "var/arxmcp/notebooks" in text
        assert "notebooks.db" in text


# ---------------------------------------------------------------------------
# Design-note (08-security-observability-ops.md) coverage
# ---------------------------------------------------------------------------


class TestSecurityNoteBackupSection:
    note = REPO_ROOT / ".claude" / "notes" / "08-security-observability-ops.md"

    def test_note_lists_notebook_paths_and_exception(self):
        """notebook-ops-hardening-m1 AC: the design note's backup section
        lists the notebook paths and calls out notebooks.db as the
        EXCEPTION to the cache-exclusion policy."""
        text = self.note.read_text(encoding="utf-8")
        assert "var/arxmcp/notebooks/" in text
        assert "notebooks.db" in text
        assert "EXCEPTION" in text
        # retrieval.db must remain documented as excluded
        assert "retrieval.db" in text


# ---------------------------------------------------------------------------
# Real restic round-trip (opt-in; notebook-ops-hardening-m1 AC G/W/T)
# ---------------------------------------------------------------------------


@pytest.mark.requires_restic
class TestResticNotebookRoundTrip:
    """The faithful realization of the AC: a notebook (uploaded PDF +
    notebooks.db row) survives a real backup -> wipe -> restore cycle
    byte-for-byte. Opt-in (restic is not installed by default) via
    `pytest -m requires_restic` AND ARXMCP_RUN_RESTIC_TESTS=1."""

    def test_pdf_and_db_row_round_trip(self, tmp_path):
        import hashlib
        import os as _os
        import shutil
        import sqlite3
        import subprocess as _sp

        if _os.environ.get("ARXMCP_RUN_RESTIC_TESTS") != "1":
            pytest.skip("set ARXMCP_RUN_RESTIC_TESTS=1 to run restic tests")
        restic = shutil.which("restic")
        if restic is None:
            pytest.skip("restic not installed")

        # 1. Synthetic notebook: an uploaded PDF + a notebooks.db row.
        src = tmp_path / "src"
        nbdir = src / "var" / "arxmcp" / "notebooks" / "demo" / "pdfs"
        nbdir.mkdir(parents=True)
        pdf = nbdir / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.5\n" + _os.urandom(2048) + b"\n%%EOF")
        cache = src / "var" / "arxmcp" / "cache"
        cache.mkdir(parents=True)
        db = cache / "notebooks.db"
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE notebooks (slug TEXT, display_name TEXT)")
        conn.execute("INSERT INTO notebooks VALUES ('demo', 'Demo')")
        conn.commit()
        conn.close()

        # 2. WAL checkpoint BEFORE capturing the baseline sha (mirrors the
        #    backup wrapper; the -wal/-shm sidecars are NOT backed up).
        from ops.checkpoint_notebooks_db import checkpoint
        assert checkpoint(db) in ("ok", "no-wal")
        pdf_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        db_sha = hashlib.sha256(db.read_bytes()).hexdigest()

        # 3. restic init + backup via the --files-from-verbatim - manifest.
        repo = tmp_path / "repo"
        env = {**_os.environ, "RESTIC_REPOSITORY": str(repo),
               "RESTIC_PASSWORD": "test"}
        _sp.run([restic, "init"], env=env, check=True,
                capture_output=True, text=True)
        manifest = f"{pdf}\n{db}\n".encode()
        _sp.run([restic, "backup", "--files-from-verbatim", "-"],
                env=env, input=manifest, check=True,
                capture_output=True)

        # 4. Wipe the source.
        shutil.rmtree(src)
        assert not pdf.exists()

        # 5. Restore latest.
        restore = tmp_path / "restore"
        _sp.run([restic, "restore", "latest", "--target", str(restore)],
                env=env, check=True, capture_output=True, text=True)

        # 6. Byte-for-byte assertions via the rglob smoke check helpers.
        from ops.restore_drill_check import _locate_notebooks_db
        restored_db = _locate_notebooks_db(restore)
        assert restored_db is not None
        assert hashlib.sha256(restored_db.read_bytes()).hexdigest() == db_sha
        restored_pdfs = list(restore.rglob("paper.pdf"))
        assert len(restored_pdfs) == 1
        assert (
            hashlib.sha256(restored_pdfs[0].read_bytes()).hexdigest()
            == pdf_sha
        )
        # 7. The restored DB row is intact.
        rconn = sqlite3.connect(str(restored_db))
        try:
            rows = rconn.execute(
                "SELECT slug, display_name FROM notebooks"
            ).fetchall()
        finally:
            rconn.close()
        assert rows == [("demo", "Demo")]
