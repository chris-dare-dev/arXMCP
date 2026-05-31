"""Tests for ``onboarding-uplift-m3`` REST endpoints + UI badge tooltip.

Covers:

- AC1 — ``POST /ui/api/admin/repair-registry``: walk, classify, register.
- AC2 — ``POST /ui/api/notebooks/{slug}/reconcile-marker``: recount,
  atomic rewrite, idempotent, byte-identical at canonical steady state.
- AC3 — ``GET /ui/api/notebooks/{slug}/health``: drift status
  classification (ok / drift / no_marker / malformed_marker).
- AC5 — ``/ui/status-badge`` remediation block: static ``<small>``
  block visible only on non-pass status, names check + Make command,
  NO raw paths.
- AC8 — BP1/BP2 byte-stability cross-check (new endpoints under
  ``/ui/api/``; no MCP tool surface touch).

The tests build a minimal FastAPI app per the existing
``tests/test_notebook_api.py`` pattern: tmp_path for both
``notebooks.db`` and the ``NOTEBOOKS_BASE`` walk root. We exercise the
real ``NotebooksStore`` (no mocking) but stub the LanceDB recount path
where needed so the tests can run without a real lancedb dataset.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import router as notebooks_router
from tools import _notebook_common

# ===========================================================================
# Shared fixtures
# ===========================================================================


@pytest.fixture
def notebooks_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base)
    return base


@pytest.fixture
def client(
    tmp_path: Path,
    notebooks_base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Minimal FastAPI app + tmp_path-scoped NotebooksStore (m2 F3
    test-isolation pattern; m3 inherits)."""
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        monkeypatch.setattr(
            notebooks_module,
            "_now_iso",
            lambda: "2026-05-31T00:00:00+00:00",
        )
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _seed_marker(
    lance_dir: Path,
    *,
    chunk_count: int = 100,
    paper_count: int = 5,
    version: int = 1,
) -> None:
    """Write a valid corpus-version.json to ``lance_dir`` (creates the
    directory if missing)."""
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
# AC1 — POST /ui/api/admin/repair-registry
# ===========================================================================


class TestRepairRegistry:
    def test_empty_base_dir_returns_all_buckets_empty(self, client):
        """When ``NOTEBOOKS_BASE`` is empty (just-created tmp_path), the
        endpoint returns an all-empty response — not an error."""
        rv = client.post("/ui/api/admin/repair-registry")
        assert rv.status_code == 200
        body = rv.json()
        assert body == {
            "registered": [],
            "already_registered": [],
            "skipped_no_marker": [],
            "skipped_malformed_marker": [],
        }

    def test_registers_orphan_dir_with_valid_marker(
        self, client, notebooks_base
    ):
        """Cardinal AC1: an on-disk dir with a valid marker that is
        NOT in notebooks.db gets registered via NotebooksStore."""
        (notebooks_base / "alpha-nb").mkdir()
        _seed_marker(notebooks_base / "alpha-nb" / "lancedb")

        rv = client.post("/ui/api/admin/repair-registry")
        assert rv.status_code == 200
        body = rv.json()
        assert body["registered"] == ["alpha-nb"]
        assert body["already_registered"] == []

        # And the row is now visible via the canonical list endpoint.
        rv2 = client.get("/ui/api/notebooks")
        slugs = [r["slug"] for r in rv2.json()]
        assert "alpha-nb" in slugs

    def test_idempotent_second_run_classifies_already_registered(
        self, client, notebooks_base
    ):
        """AC1 idempotency: second invocation reports the slug as
        already_registered (zero new INSERTs)."""
        (notebooks_base / "beta-nb").mkdir()
        _seed_marker(notebooks_base / "beta-nb" / "lancedb")

        client.post("/ui/api/admin/repair-registry")
        rv = client.post("/ui/api/admin/repair-registry")
        body = rv.json()
        assert body["registered"] == []
        assert body["already_registered"] == ["beta-nb"]

    def test_skips_dir_with_no_marker(self, client, notebooks_base):
        """A dir without ``lancedb/corpus-version.json`` lands in
        ``skipped_no_marker`` (not an error — operator hasn't ingested
        yet)."""
        (notebooks_base / "gamma-nb").mkdir()
        # No marker.

        rv = client.post("/ui/api/admin/repair-registry")
        body = rv.json()
        assert body["registered"] == []
        assert body["skipped_no_marker"] == ["gamma-nb"]

    def test_skips_malformed_marker(self, client, notebooks_base):
        """A dir with a malformed JSON marker lands in
        ``skipped_malformed_marker``. The walk MUST continue (other
        dirs still get registered)."""
        bad_dir = notebooks_base / "bad-nb" / "lancedb"
        bad_dir.mkdir(parents=True)
        (bad_dir / "corpus-version.json").write_text("not valid json {")

        good_dir = notebooks_base / "good-nb" / "lancedb"
        _seed_marker(good_dir)

        rv = client.post("/ui/api/admin/repair-registry")
        body = rv.json()
        assert body["skipped_malformed_marker"] == ["bad-nb"]
        # Walk continued — good-nb got registered.
        assert body["registered"] == ["good-nb"]

    def test_ignores_symlinks(self, client, notebooks_base, tmp_path):
        """Symlinks at slug positions are ignored (defense against
        path-traversal abuse — also handled in ``notebook_dir``)."""
        target = tmp_path / "elsewhere"
        target.mkdir()
        try:
            (notebooks_base / "symlink-nb").symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")

        rv = client.post("/ui/api/admin/repair-registry")
        body = rv.json()
        assert "symlink-nb" not in body["registered"]

    def test_ignores_invalid_slug_dirs(self, client, notebooks_base):
        """Dirs with names that fail ``validate_slug`` (uppercase,
        leading hyphen, etc.) are silently skipped."""
        (notebooks_base / "INVALID").mkdir()  # uppercase rejected
        _seed_marker(notebooks_base / "INVALID" / "lancedb")

        rv = client.post("/ui/api/admin/repair-registry")
        body = rv.json()
        # Doesn't appear in ANY bucket (silently filtered before
        # the walk reaches the marker-read step).
        assert "INVALID" not in body["registered"]
        assert "INVALID" not in body["already_registered"]
        assert "INVALID" not in body["skipped_no_marker"]
        assert "INVALID" not in body["skipped_malformed_marker"]


# ===========================================================================
# AC2 — POST /ui/api/notebooks/{slug}/reconcile-marker
# ===========================================================================


class TestReconcileMarker:
    @pytest.fixture
    def stub_recount(self, monkeypatch):
        """Stub ``_recount_notebook_lancedb`` to return a fixed
        ``(chunks, papers)`` tuple — avoids needing a real LanceDB
        dataset in the test."""

        def factory(chunks: int, papers: int):
            def stub(_lance_path, *, version):
                return (chunks, papers)

            monkeypatch.setattr(
                notebooks_module,
                "_recount_notebook_lancedb",
                stub,
            )

        return factory

    def test_404_when_notebook_not_registered(
        self, client, notebooks_base
    ):
        """The slug must exist in notebooks.db before reconcile can
        run — otherwise the response 404s with a clear message."""
        rv = client.post(
            "/ui/api/notebooks/unknown-slug/reconcile-marker"
        )
        assert rv.status_code == 404
        assert "not registered" in rv.json()["detail"]

    def test_422_when_marker_absent(
        self, client, notebooks_base
    ):
        """Notebook scaffolded but never ingested — return 422 with a
        clear ``run make ingest first`` hint."""
        # Register via the canonical path.
        rv = client.post(
            "/ui/api/notebooks",
            json={"slug": "scaffolded-nb", "display_name": "S"},
        )
        assert rv.status_code == 201
        # NO marker created — dir might not even exist.

        rv = client.post(
            "/ui/api/notebooks/scaffolded-nb/reconcile-marker"
        )
        assert rv.status_code == 422
        assert "make ingest" in rv.json()["detail"]

    def test_422_when_marker_malformed(
        self, client, notebooks_base
    ):
        """A malformed marker → 422 with operator-investigation hint."""
        rv = client.post(
            "/ui/api/notebooks",
            json={"slug": "broken-nb", "display_name": "B"},
        )
        assert rv.status_code == 201
        lance = notebooks_base / "broken-nb" / "lancedb"
        lance.mkdir(parents=True)
        (lance / "corpus-version.json").write_text("{ truncated")

        rv = client.post(
            "/ui/api/notebooks/broken-nb/reconcile-marker"
        )
        assert rv.status_code == 422
        assert "malformed" in rv.json()["detail"]

    def test_recounts_and_rewrites_marker(
        self, client, notebooks_base, stub_recount
    ):
        """Cardinal AC2: drift-poisoned marker → reconcile recounts
        + rewrites with the TRUE counts. ``drift_resolved`` matches
        the delta. ``created_at`` preserved from the read marker."""
        rv = client.post(
            "/ui/api/notebooks",
            json={"slug": "drift-nb", "display_name": "Drift"},
        )
        assert rv.status_code == 201
        lance = notebooks_base / "drift-nb" / "lancedb"
        _seed_marker(lance, chunk_count=99, paper_count=1, version=42)
        stub_recount(chunks=5266, papers=12)

        rv = client.post("/ui/api/notebooks/drift-nb/reconcile-marker")
        assert rv.status_code == 200
        body = rv.json()
        assert body["before"] == {"chunk_count": 99, "paper_count": 1}
        assert body["after"] == {
            "chunk_count": 5266,
            "paper_count": 12,
        }
        assert body["drift_resolved"] == 5266 - 99

        # And the marker file on disk reflects the healed counts.
        healed = json.loads(
            (lance / "corpus-version.json").read_text()
        )
        assert healed["chunk_count"] == 5266
        assert healed["paper_count"] == 12
        # Synthesis §3 D4: created_at preserved from the read marker.
        assert healed["created_at"] == "2026-05-31T00:00:00Z"
        assert healed["version"] == 42

    def test_byte_identical_idempotency_at_steady_state(
        self, client, notebooks_base, stub_recount
    ):
        """m3 synthesis §3 D4 / FM-10: after the first reconcile
        converts a marker to canonical form, a second reconcile against
        the SAME drift state produces a BYTE-IDENTICAL file."""
        rv = client.post(
            "/ui/api/notebooks",
            json={"slug": "idem-nb", "display_name": "I"},
        )
        assert rv.status_code == 201
        lance = notebooks_base / "idem-nb" / "lancedb"
        _seed_marker(lance, chunk_count=10, paper_count=2, version=5)
        stub_recount(chunks=10, papers=2)

        # Run 1 — converts to canonical form.
        client.post("/ui/api/notebooks/idem-nb/reconcile-marker")
        bytes_1 = (lance / "corpus-version.json").read_bytes()
        # Run 2 — must be byte-identical.
        client.post("/ui/api/notebooks/idem-nb/reconcile-marker")
        bytes_2 = (lance / "corpus-version.json").read_bytes()
        assert bytes_1 == bytes_2, (
            "marker bytes diverged across reconcile runs — D4 violation"
        )

    def test_422_when_slug_invalid(self, client):
        rv = client.post(
            "/ui/api/notebooks/INVALID-SLUG/reconcile-marker"
        )
        assert rv.status_code == 422


# ===========================================================================
# AC3 — GET /ui/api/notebooks/{slug}/health
# ===========================================================================


class TestNotebookHealth:
    @pytest.fixture
    def stub_recount(self, monkeypatch):
        def factory(chunks: int, papers: int):
            def stub(_lance_path, *, version):
                return (chunks, papers)

            monkeypatch.setattr(
                notebooks_module,
                "_recount_notebook_lancedb",
                stub,
            )

        return factory

    def test_404_unknown_slug(self, client):
        rv = client.get("/ui/api/notebooks/unknown/health")
        assert rv.status_code == 404

    def test_status_no_marker(self, client, notebooks_base):
        client.post(
            "/ui/api/notebooks",
            json={"slug": "fresh-nb", "display_name": "F"},
        )
        rv = client.get("/ui/api/notebooks/fresh-nb/health")
        assert rv.status_code == 200
        body = rv.json()
        assert body["status"] == "no_marker"
        assert body["marker_chunk_count"] is None
        assert body["detail"] and "make ingest" in body["detail"]

    def test_status_malformed_marker(self, client, notebooks_base):
        client.post(
            "/ui/api/notebooks",
            json={"slug": "mal-nb", "display_name": "M"},
        )
        lance = notebooks_base / "mal-nb" / "lancedb"
        lance.mkdir(parents=True)
        (lance / "corpus-version.json").write_text("nope")

        rv = client.get("/ui/api/notebooks/mal-nb/health")
        assert rv.status_code == 200
        body = rv.json()
        assert body["status"] == "malformed_marker"
        assert body["detail"] and "investigate" in body["detail"]

    def test_status_ok_when_in_sync(
        self, client, notebooks_base, stub_recount
    ):
        client.post(
            "/ui/api/notebooks",
            json={"slug": "synced-nb", "display_name": "S"},
        )
        lance = notebooks_base / "synced-nb" / "lancedb"
        _seed_marker(lance, chunk_count=100, paper_count=5, version=7)
        stub_recount(chunks=100, papers=5)

        rv = client.get("/ui/api/notebooks/synced-nb/health")
        body = rv.json()
        assert body["status"] == "ok"
        assert body["drift"] == 0
        assert body["detail"] is None
        assert body["corpus_version"] == 7

    def test_status_drift_when_marker_disagrees(
        self, client, notebooks_base, stub_recount
    ):
        client.post(
            "/ui/api/notebooks",
            json={"slug": "drift2-nb", "display_name": "D"},
        )
        lance = notebooks_base / "drift2-nb" / "lancedb"
        _seed_marker(lance, chunk_count=100, paper_count=5, version=7)
        stub_recount(chunks=5266, papers=12)

        rv = client.get("/ui/api/notebooks/drift2-nb/health")
        body = rv.json()
        assert body["status"] == "drift"
        assert body["marker_chunk_count"] == 100
        assert body["actual_chunk_count"] == 5266
        assert body["drift"] == 5266 - 100
        # Detail line names the Make remediation command.
        assert "make reconcile" in body["detail"]
        assert "drift2-nb" in body["detail"]


# ===========================================================================
# AC5 — /ui/status-badge remediation block
# ===========================================================================


class TestStatusBadgeRemediation:
    """The badge tooltip is a unit-tested helper rather than a live
    HTTP integration test — the badge route requires an entire
    server-startup ``Resources`` to be reachable, which is heavier
    than this milestone's unit scope. The helper ``_build_remediation_block``
    is the cardinal contract from synthesis §3 D2.
    """

    def test_ok_status_returns_empty_block(self):
        from server.routes.ui import _build_remediation_block

        block = _build_remediation_block({"checks": {}}, css="ok")
        assert block == ""

    def test_warn_status_names_failing_check_and_make_command(self):
        from server.routes.ui import _build_remediation_block

        report = {
            "checks": {
                "corpus:version": [{"status": "warn"}],
            }
        }
        block = _build_remediation_block(report, css="warn")
        # Contract: contains the check name AND the remediation Make
        # command (FM-6: NO raw paths).
        assert "corpus version" in block.lower()
        assert "make reconcile" in block
        # Cardinal FM-6 negative assertion: no raw paths leak.
        assert "var/arxmcp" not in block
        # Structural: it's a static <small> block, NOT a <details>.
        assert "<small" in block
        assert "<details" not in block

    def test_notebooks_count_check_names_repair_registry(self):
        from server.routes.ui import _build_remediation_block

        report = {
            "checks": {
                "notebooks:count": [{"status": "fail"}],
            }
        }
        block = _build_remediation_block(report, css="warn")
        assert "make repair-registry" in block

    def test_backup_time_check_is_ops_side_remediation(self):
        from server.routes.ui import _build_remediation_block

        report = {
            "checks": {
                "backup:time": [{"status": "warn"}],
            }
        }
        block = _build_remediation_block(report, css="ops-warn")
        assert "backup" in block.lower()
        # Ops-side checks do NOT name `make reconcile` (which would be
        # the wrong remediation for backup staleness).
        assert "make reconcile" not in block

    def test_multiple_failing_checks_each_get_a_line(self):
        from server.routes.ui import _build_remediation_block

        report = {
            "checks": {
                "corpus:version": [{"status": "warn"}],
                "backup:time": [{"status": "warn"}],
            }
        }
        block = _build_remediation_block(report, css="warn")
        # Two checks → at least two <br>-separated lines.
        assert block.count("<br>") >= 1

    def test_pass_status_emits_no_block_when_no_checks_fail(self):
        from server.routes.ui import _build_remediation_block

        report = {
            "checks": {
                "corpus:version": [{"status": "pass"}],
            }
        }
        # css="ok" short-circuits before inspection.
        block = _build_remediation_block(report, css="ok")
        assert block == ""


# ===========================================================================
# AC8 — BP1/BP2 byte-stability cross-check
# ===========================================================================


class TestNoMCPSurfaceTouch:
    """The 3 new REST endpoints + the badge tooltip live under
    ``/ui/`` and ``/ui/api/``, NOT the MCP ``/mcp/`` surface. The
    dedicated tests in ``tests/test_server_tool_schema.py`` +
    ``tests/test_prompts.py`` are the cardinal hash invariants; this
    is a structural grep that no new m3 file claims an MCP-tool
    import."""

    @pytest.mark.parametrize(
        "path",
        [
            "tools/notebook_repair_registry.py",
            "tools/notebook_reconcile_marker.py",
        ],
    )
    def test_new_module_does_not_register_mcp_tool(self, path):
        repo_root = Path(__file__).parent.parent
        contents = (repo_root / path).read_text(encoding="utf-8")
        assert "from server.tools import" not in contents, (
            f"{path} imports from server.tools — m3 must not extend "
            f"the MCP tool registry (AC8 BP1 byte-stability risk)"
        )
        assert "ALL_TOOLS" not in contents
