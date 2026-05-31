"""Tests for the m3 server-down CLI fallbacks
(``tools/notebook_repair_registry.py`` and
``tools/notebook_reconcile_marker.py``).

These back the ``make repair-registry`` and ``make reconcile``
recipes' server-down branches. They mirror the server-up REST
endpoints' behavior — identical drift-classification, same atomic
rewrite pattern, same registry-write discipline (m2 critique F1
lesson: route every write through ``NotebooksStore.create_notebook``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from server.notebooks_store import NotebooksStore


def _seed_marker(
    lance_dir: Path,
    *,
    chunk_count: int = 100,
    paper_count: int = 5,
    version: int = 1,
) -> None:
    lance_dir.mkdir(parents=True, exist_ok=True)
    marker = {
        "chunk_count": chunk_count,
        "chunker_version": "v1.1",
        "created_at": "2026-05-31T00:00:00Z",
        "embedder_version": "bge-m3@5617a9f6",
        "paper_count": paper_count,
        "version": version,
    }
    (lance_dir / "corpus-version.json").write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True) + "\n"
    )


# ===========================================================================
# tools/notebook_repair_registry.py
# ===========================================================================


class TestNotebookRepairRegistryCLI:
    def test_empty_notebooks_base_exits_clean(self, tmp_path, capsys):
        from tools.notebook_repair_registry import main

        notebooks_base = tmp_path / "notebooks"
        notebooks_base.mkdir()
        db_path = tmp_path / "notebooks.db"

        rc = main(db_path=db_path, notebooks_base=notebooks_base)
        assert rc == 0
        out = capsys.readouterr().out
        assert "registered=0" in out
        assert "already_registered=0" in out

    def test_registers_orphan_on_disk_dir(self, tmp_path, capsys):
        from tools.notebook_repair_registry import main

        notebooks_base = tmp_path / "notebooks"
        notebooks_base.mkdir()
        db_path = tmp_path / "notebooks.db"
        # Pre-seed an on-disk dir with a valid marker but NO SQLite row.
        (notebooks_base / "alpha-nb").mkdir()
        _seed_marker(notebooks_base / "alpha-nb" / "lancedb")

        rc = main(db_path=db_path, notebooks_base=notebooks_base)
        assert rc == 0
        out = capsys.readouterr().out
        assert "registered=1" in out

        # The row is now in the DB.
        loop = asyncio.new_event_loop()
        try:
            store = loop.run_until_complete(NotebooksStore.open(db_path))
            try:
                rows = loop.run_until_complete(store.list_notebooks())
            finally:
                loop.run_until_complete(store.close())
        finally:
            loop.close()
        slugs = [r["slug"] for r in rows]
        assert "alpha-nb" in slugs

    def test_classifies_no_marker_and_malformed(
        self, tmp_path, capsys
    ):
        """Walk classification: no-marker dirs go in
        ``skipped_no_marker``; malformed JSON dirs go in
        ``skipped_malformed_marker``. Walk continues past both."""
        from tools.notebook_repair_registry import main

        notebooks_base = tmp_path / "notebooks"
        notebooks_base.mkdir()
        db_path = tmp_path / "notebooks.db"

        # No marker.
        (notebooks_base / "empty-nb").mkdir()
        # Malformed marker.
        bad = notebooks_base / "bad-nb" / "lancedb"
        bad.mkdir(parents=True)
        (bad / "corpus-version.json").write_text("{ not json")
        # Valid marker — should still be registered (walk continues).
        good = notebooks_base / "good-nb" / "lancedb"
        _seed_marker(good)

        rc = main(db_path=db_path, notebooks_base=notebooks_base)
        assert rc == 0
        out = capsys.readouterr().out
        assert "registered=1" in out  # good-nb
        assert "skipped_no_marker=1" in out
        assert "skipped_malformed_marker=1" in out

    def test_idempotent_re_run(self, tmp_path, capsys):
        from tools.notebook_repair_registry import main

        notebooks_base = tmp_path / "notebooks"
        notebooks_base.mkdir()
        db_path = tmp_path / "notebooks.db"
        (notebooks_base / "beta-nb").mkdir()
        _seed_marker(notebooks_base / "beta-nb" / "lancedb")

        main(db_path=db_path, notebooks_base=notebooks_base)
        capsys.readouterr()  # discard
        rc = main(db_path=db_path, notebooks_base=notebooks_base)
        assert rc == 0
        out = capsys.readouterr().out
        assert "already_registered=1" in out
        assert "registered=0" in out


# ===========================================================================
# tools/notebook_reconcile_marker.py
# ===========================================================================


class TestNotebookReconcileMarkerCLI:
    def test_requires_slug_or_shared_flag(self, capsys):
        from tools.notebook_reconcile_marker import main

        rc = main([])
        assert rc == 1
        err = capsys.readouterr().err
        assert "pass a slug" in err.lower() or "shared" in err.lower()

    def test_mutually_exclusive_slug_and_shared(self, capsys):
        from tools.notebook_reconcile_marker import main

        rc = main(["foo-slug", "--shared"])
        assert rc == 1

    def test_invalid_slug_rejected(self, capsys):
        from tools.notebook_reconcile_marker import main

        rc = main(["INVALID-CAPS"])
        assert rc == 1
        err = capsys.readouterr().err.lower()
        assert "invalid" in err or "slug" in err

    def test_no_marker_returns_nonzero(self, tmp_path, capsys):
        """If the marker is absent the CLI MUST exit non-zero with a
        ``run make ingest first`` hint."""
        from tools.notebook_reconcile_marker import main

        # We rely on the slug NOT existing under the real
        # NOTEBOOKS_BASE — use a unique high-entropy slug.
        rc = main(["m3-cli-test-noexist-zz"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "no corpus-version.json" in err
        assert "make ingest" in err

    def test_recounts_and_rewrites_via_stub(
        self, tmp_path, capsys, monkeypatch
    ):
        """End-to-end test of the reconcile path with a stubbed recount.
        Verifies: chunk_count + paper_count updated; created_at
        preserved (D4); byte-identical at the canonical steady state."""
        from tools import notebook_reconcile_marker as mod

        # Build a tmp lancedb dir with a poisoned marker.
        lance = tmp_path / "lancedb"
        _seed_marker(
            lance, chunk_count=99, paper_count=1, version=42
        )

        # Stub the recount and the path lookup.
        def fake_recount(_lance_path, *, version):
            return 5266, 12

        def fake_notebook_lancedb_path(slug, *, base=None):
            return lance

        monkeypatch.setattr(mod, "_recount_lancedb", fake_recount)
        monkeypatch.setattr(
            mod, "notebook_lancedb_path", fake_notebook_lancedb_path
        )

        rc = mod.main(["valid-slug"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "before=99" in out
        assert "after=5266" in out
        assert "drift_resolved=5167" in out

        # Marker on disk has the new counts.
        healed = json.loads(
            (lance / "corpus-version.json").read_text()
        )
        assert healed["chunk_count"] == 5266
        assert healed["paper_count"] == 12
        # D4: created_at preserved.
        assert healed["created_at"] == "2026-05-31T00:00:00Z"
        assert healed["version"] == 42

    def test_byte_identical_at_canonical_steady_state(
        self, tmp_path, monkeypatch
    ):
        """After the first reconcile converts the marker to canonical
        form, a second reconcile produces a BYTE-IDENTICAL file (D4 /
        FM-10)."""
        from tools import notebook_reconcile_marker as mod

        lance = tmp_path / "lancedb"
        _seed_marker(lance, chunk_count=10, paper_count=2, version=5)

        def fake_recount(_lance_path, *, version):
            return 10, 2

        def fake_notebook_lancedb_path(slug, *, base=None):
            return lance

        monkeypatch.setattr(mod, "_recount_lancedb", fake_recount)
        monkeypatch.setattr(
            mod, "notebook_lancedb_path", fake_notebook_lancedb_path
        )

        mod.main(["valid-slug"])
        bytes_1 = (lance / "corpus-version.json").read_bytes()
        mod.main(["valid-slug"])
        bytes_2 = (lance / "corpus-version.json").read_bytes()
        assert bytes_1 == bytes_2

    def test_shared_flag_routes_to_global_lancedb(
        self, tmp_path, monkeypatch, capsys
    ):
        """``--shared`` reconciles ``var/arxmcp/index/lancedb/`` (not a
        per-notebook path)."""
        from tools import notebook_reconcile_marker as mod

        shared = tmp_path / "index" / "lancedb"
        _seed_marker(shared, chunk_count=1, paper_count=1, version=1)

        monkeypatch.setattr(mod, "_SHARED_LANCEDB_PATH", shared)

        def fake_recount(_lance_path, *, version):
            return 42, 7

        monkeypatch.setattr(mod, "_recount_lancedb", fake_recount)

        rc = mod.main(["--shared"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[shared]" in out

        healed = json.loads(
            (shared / "corpus-version.json").read_text()
        )
        assert healed["chunk_count"] == 42
        assert healed["paper_count"] == 7
