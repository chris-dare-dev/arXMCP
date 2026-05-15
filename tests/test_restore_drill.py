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
    write_pass_sentinel,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


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

    def test_raises_when_marker_missing(self, tmp_path):
        # The directory exists but the marker doesn't.
        lancedb = tmp_path / "var" / "arxmcp" / "index" / "lancedb"
        lancedb.mkdir(parents=True)
        with pytest.raises(RuntimeError, match="corpus-version.json"):
            smoke_check_lancedb(tmp_path)

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
