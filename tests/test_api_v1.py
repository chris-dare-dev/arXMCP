"""Tests for the /api/v1 JSON-only operator surface (stage2/arx-a1, WS-A A1).

Coverage matrix (acceptance-criteria.md AC-A.1 + AC-A.2 runtime half):

- TestJsonOnlyContract     — AC-A.1: HX-Request: true receives the IDENTICAL
                             JSON body as a request without it, on every
                             route the legacy surface forks on.
- TestFormatVersion        — every JSON response carries format_version.
- TestPagination           — limit/offset envelope + stable ordering on the
                             two list endpoints.
- TestNotebookCrudV1       — create/list/delete/rename/topic parity with the
                             legacy JSON semantics (409 dup, 404 missing,
                             422 slug/category).
- TestPapersV1             — add/list/remove + upload (created vs
                             updated_existing translation).
- TestIngestV1             — trigger (202 JSON, 409 collision) + latest
                             (none/running/terminal as plain-200 JSON — no
                             HTTP 286 on this surface).
- TestAdminAndDiagnostics  — repair-registry / reconcile-marker(422 no
                             marker) / health / parse-status / export
                             (binary + X-Arxmcp-Format-Version header).

Harness: minimal FastAPI app + real NotebooksStore on tmp_path — the
``tests/test_notebook_api.py`` pattern (no lifespan, no model loads).
Both routers are mounted so the JSON-parity tests can diff the two
surfaces directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.api_v1 import API_V1_FORMAT_VERSION
from server.routes.api_v1 import router as api_v1_router
from server.routes.notebooks import router as notebooks_router
from tools import _notebook_common

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeIngestTracker:
    """Records start_ingest calls; never spawns a subprocess."""

    def __init__(self) -> None:
        self.started: list[dict] = []
        self._running: set[str] = set()

    def is_running(self, slug: str) -> bool:
        return slug in self._running

    def start_ingest(self, *, slug, run_id, store, now_iso_provider):
        self.started.append({"slug": slug, "run_id": run_id})
        self._running.add(slug)


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect NOTEBOOKS_BASE so create_notebook writes inside tmp_path."""
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    return base


@pytest.fixture
def harness(
    tmp_path: Path, notebooks_base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict]:
    """Minimal app with BOTH surfaces mounted + fake ingest tracker.

    Per-fixture event loop — the project's asyncio.run-per-call-site
    convention (see tests/test_notebook_api.py for the rationale).
    """
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        tracker = _FakeIngestTracker()
        app.state.ingest_tracker = tracker
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(api_v1_router, prefix="/api/v1")
        monkeypatch.setattr(
            notebooks_module, "_now_iso",
            lambda: "2026-07-04T00:00:00+00:00",
        )
        with TestClient(app) as c:
            yield {"client": c, "store": store, "tracker": tracker, "loop": loop}
        loop.run_until_complete(store.close())
    finally:
        loop.close()


@pytest.fixture
def client(harness: dict) -> TestClient:
    return harness["client"]


def _mk(client: TestClient, slug: str, **extra) -> None:
    r = client.post("/api/v1/notebooks", json={"slug": slug, **extra})
    if r.status_code != 201:
        raise RuntimeError(f"fixture create failed: {r.status_code} {r.text}")


# ---------------------------------------------------------------------------
# AC-A.1 — JSON-only: HX-Request must NOT fork the response
# ---------------------------------------------------------------------------


class TestJsonOnlyContract:
    def test_create_ignores_hx_request_header(self, client: TestClient) -> None:
        """The legacy POST /ui/api/notebooks forks to an HTML <tr> on
        HX-Request: true; /api/v1 must return the identical JSON."""
        plain = client.post("/api/v1/notebooks", json={"slug": "nb-plain"})
        hx = client.post(
            "/api/v1/notebooks",
            json={"slug": "nb-hx"},
            headers={"HX-Request": "true"},
        )
        assert plain.status_code == 201
        assert hx.status_code == 201
        assert hx.headers["content-type"].startswith("application/json")
        a, b = plain.json(), hx.json()
        # Identical shape modulo the differing slug values.
        a["slug"] = b["slug"] = "X"
        a["lancedb_path"] = b["lancedb_path"] = "X"
        assert a == b

    def test_legacy_surface_still_forks_on_hx(self, client: TestClient) -> None:
        """Sanity: the strangler leaves /ui/api behavior untouched —
        the union lives THERE, not on /api/v1."""
        r = client.post(
            "/ui/api/notebooks",
            json={"slug": "nb-legacy-hx"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 201
        assert r.headers["content-type"].startswith("text/html")
        assert r.text.startswith("<tr")

    def test_add_paper_ignores_hx_request_header(self, client: TestClient) -> None:
        _mk(client, "nb-papers-hx")
        hx = client.post(
            "/api/v1/notebooks/nb-papers-hx/papers",
            json={"arxiv_url": "https://arxiv.org/abs/0705.3794"},
            headers={"HX-Request": "true"},
        )
        assert hx.status_code == 201
        assert hx.headers["content-type"].startswith("application/json")
        assert hx.json() == {
            "format_version": API_V1_FORMAT_VERSION,
            "slug": "nb-papers-hx",
            "paper_id": "0705.3794",
        }

    def test_delete_is_204_even_with_hx_header(self, client: TestClient) -> None:
        """Legacy DELETE returns 200-empty-body on HX-Request (htmx
        swap semantics); /api/v1 is always 204."""
        _mk(client, "nb-del-hx")
        r = client.delete(
            "/api/v1/notebooks/nb-del-hx", headers={"HX-Request": "true"}
        )
        assert r.status_code == 204
        assert r.content == b""

    def test_get_list_identical_with_hx_header(self, client: TestClient) -> None:
        _mk(client, "nb-list-hx")
        plain = client.get("/api/v1/notebooks")
        hx = client.get("/api/v1/notebooks", headers={"HX-Request": "true"})
        assert plain.json() == hx.json()


# ---------------------------------------------------------------------------
# format_version on every JSON body
# ---------------------------------------------------------------------------


class TestFormatVersion:
    def test_format_version_on_every_json_route(self, client: TestClient) -> None:
        _mk(client, "nb-fv")
        client.post(
            "/api/v1/notebooks/nb-fv/papers",
            json={"arxiv_url": "https://arxiv.org/abs/0705.3794"},
        )
        json_gets = [
            "/api/v1/notebooks",
            "/api/v1/notebooks/nb-fv/papers",
            "/api/v1/notebooks/nb-fv/health",
            "/api/v1/notebooks/nb-fv/parse-status",
            "/api/v1/notebooks/nb-fv/ingest/latest",
        ]
        for path in json_gets:
            body = client.get(path).json()
            assert body.get("format_version") == API_V1_FORMAT_VERSION, path
        assert (
            client.post("/api/v1/admin/repair-registry").json()["format_version"]
            == API_V1_FORMAT_VERSION
        )

    def test_export_carries_header_form(self, client: TestClient) -> None:
        _mk(client, "nb-fv-export")
        r = client.get("/api/v1/notebooks/nb-fv-export/export")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/x-tar"
        assert r.headers["x-arxmcp-format-version"] == str(API_V1_FORMAT_VERSION)


# ---------------------------------------------------------------------------
# Pagination (AC-A.1: list endpoints accept limit/offset, stable order)
# ---------------------------------------------------------------------------


class TestPagination:
    def test_notebook_list_envelope_and_slices(self, client: TestClient) -> None:
        # Same fixed created_at for all rows → ordering falls to the
        # slug ASC tiebreak, which is exactly the stability contract.
        for slug in ("nb-a", "nb-b", "nb-c"):
            _mk(client, slug)

        full = client.get("/api/v1/notebooks").json()
        assert full["total"] == 3
        assert full["limit"] == 100
        assert full["offset"] == 0
        slugs = [row["slug"] for row in full["items"]]
        assert slugs == sorted(slugs), "tiebreak ordering must be slug ASC"

        page = client.get("/api/v1/notebooks?limit=1&offset=1").json()
        assert page["total"] == 3
        assert len(page["items"]) == 1
        assert page["items"][0]["slug"] == slugs[1]

        tail = client.get("/api/v1/notebooks?limit=5&offset=2").json()
        assert [r["slug"] for r in tail["items"]] == slugs[2:]

    def test_papers_list_paginates(self, client: TestClient) -> None:
        _mk(client, "nb-pg")
        for pid in ("0705.3794", "0712.1083"):
            r = client.post(
                "/api/v1/notebooks/nb-pg/papers",
                json={"arxiv_url": f"https://arxiv.org/abs/{pid}"},
            )
            assert r.status_code == 201
        body = client.get("/api/v1/notebooks/nb-pg/papers?limit=1").json()
        assert body["total"] == 2
        assert len(body["items"]) == 1

    def test_limit_bounds_enforced(self, client: TestClient) -> None:
        assert client.get("/api/v1/notebooks?limit=0").status_code == 422
        assert client.get("/api/v1/notebooks?limit=501").status_code == 422
        assert client.get("/api/v1/notebooks?offset=-1").status_code == 422


# ---------------------------------------------------------------------------
# Notebook CRUD parity
# ---------------------------------------------------------------------------


class TestNotebookCrudV1:
    def test_duplicate_slug_409(self, client: TestClient) -> None:
        _mk(client, "nb-dup")
        r = client.post("/api/v1/notebooks", json={"slug": "nb-dup"})
        assert r.status_code == 409

    def test_bad_slug_422(self, client: TestClient) -> None:
        r = client.post("/api/v1/notebooks", json={"slug": "../evil"})
        assert r.status_code == 422

    def test_bad_discovery_category_422(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/notebooks",
            json={"slug": "nb-cat", "discovery_category": "bogus.XX"},
        )
        assert r.status_code == 422

    def test_delete_missing_404(self, client: TestClient) -> None:
        assert client.delete("/api/v1/notebooks/nope").status_code == 404

    def test_rename_returns_json(self, client: TestClient) -> None:
        _mk(client, "nb-rn")
        r = client.patch(
            "/api/v1/notebooks/nb-rn", json={"display_name": "New name"}
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        assert r.json() == {
            "format_version": API_V1_FORMAT_VERSION,
            "slug": "nb-rn",
            "display_name": "New name",
        }

    def test_rename_strips_control_chars(self, client: TestClient) -> None:
        """Parity with the legacy handler's log-injection defense."""
        _mk(client, "nb-rn-ctl")
        r = client.patch(
            "/api/v1/notebooks/nb-rn-ctl", json={"display_name": "a\x00b\nc"}
        )
        assert r.json()["display_name"] == "abc"

    def test_rename_missing_404(self, client: TestClient) -> None:
        r = client.patch("/api/v1/notebooks/nope", json={"display_name": "x"})
        assert r.status_code == 404

    def test_topic_update_returns_json(self, client: TestClient) -> None:
        _mk(client, "nb-topic")
        r = client.patch(
            "/api/v1/notebooks/nb-topic/topic",
            json={"discovery_category": "math.AG", "description": "stability"},
        )
        assert r.status_code == 200
        assert r.json() == {
            "format_version": API_V1_FORMAT_VERSION,
            "slug": "nb-topic",
            "discovery_category": "math.AG",
            "description": "stability",
        }

    def test_topic_bad_category_422(self, client: TestClient) -> None:
        _mk(client, "nb-topic-bad")
        r = client.patch(
            "/api/v1/notebooks/nb-topic-bad/topic",
            json={"discovery_category": "cs.LG", "description": ""},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------


class TestPapersV1:
    def test_add_bad_url_422(self, client: TestClient) -> None:
        _mk(client, "nb-p1")
        r = client.post(
            "/api/v1/notebooks/nb-p1/papers",
            json={"arxiv_url": "https://evil.example/abs/0705.3794"},
        )
        assert r.status_code == 422

    def test_add_duplicate_409(self, client: TestClient) -> None:
        _mk(client, "nb-p2")
        url = {"arxiv_url": "https://arxiv.org/abs/0705.3794"}
        assert client.post("/api/v1/notebooks/nb-p2/papers", json=url).status_code == 201
        assert client.post("/api/v1/notebooks/nb-p2/papers", json=url).status_code == 409

    def test_remove_paper_204_then_404(self, client: TestClient) -> None:
        _mk(client, "nb-p3")
        client.post(
            "/api/v1/notebooks/nb-p3/papers",
            json={"arxiv_url": "https://arxiv.org/abs/0705.3794"},
        )
        assert (
            client.delete("/api/v1/notebooks/nb-p3/papers/0705.3794").status_code
            == 204
        )
        assert (
            client.delete("/api/v1/notebooks/nb-p3/papers/0705.3794").status_code
            == 404
        )

    def test_upload_html_created_then_updated(self, client: TestClient) -> None:
        _mk(client, "nb-up")
        files = {"file": ("p.html", b"<!DOCTYPE html><html></html>", "text/html")}
        r1 = client.post(
            "/api/v1/notebooks/nb-up/papers/upload",
            data={"paper_id": "0705.3794"},
            files=files,
        )
        assert r1.status_code == 201, r1.text
        assert r1.json() == {
            "format_version": API_V1_FORMAT_VERSION,
            "slug": "nb-up",
            "paper_id": "0705.3794",
            "result": "created",
        }
        # Idempotent re-upload: junction row exists; file atomically
        # overwritten → 200 updated_existing (legacy contract).
        r2 = client.post(
            "/api/v1/notebooks/nb-up/papers/upload",
            data={"paper_id": "0705.3794"},
            files=files,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["result"] == "updated_existing"

    def test_upload_non_html_422(self, client: TestClient) -> None:
        _mk(client, "nb-up-bad")
        r = client.post(
            "/api/v1/notebooks/nb-up-bad/papers/upload",
            data={"paper_id": "0705.3794"},
            files={"file": ("p.html", b"\x00\x01binary", "text/html")},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class TestIngestV1:
    def test_trigger_returns_202_json_with_run_id(self, harness: dict) -> None:
        client = harness["client"]
        _mk(client, "nb-ing")
        r = client.post("/api/v1/notebooks/nb-ing/ingest")
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["format_version"] == API_V1_FORMAT_VERSION
        assert body["slug"] == "nb-ing"
        assert body["status"] == "running"
        assert isinstance(body["run_id"], int)
        assert harness["tracker"].started == [
            {"slug": "nb-ing", "run_id": body["run_id"]}
        ]

    def test_trigger_collision_409(self, harness: dict) -> None:
        client = harness["client"]
        _mk(client, "nb-ing2")
        assert client.post("/api/v1/notebooks/nb-ing2/ingest").status_code == 202
        # The fake tracker marks the slug running → second trigger 409s.
        assert client.post("/api/v1/notebooks/nb-ing2/ingest").status_code == 409

    def test_latest_none_then_running(self, harness: dict) -> None:
        client = harness["client"]
        _mk(client, "nb-ing3")
        none_body = client.get("/api/v1/notebooks/nb-ing3/ingest/latest").json()
        assert none_body["status"] == "none"
        assert none_body["terminal"] is False

        client.post("/api/v1/notebooks/nb-ing3/ingest")
        r = client.get("/api/v1/notebooks/nb-ing3/ingest/latest")
        assert r.status_code == 200  # plain 200 — never the htmx 286
        body = r.json()
        assert body["status"] == "running"
        assert body["terminal"] is False
        assert body["started_at"] == "2026-07-04T00:00:00+00:00"

    def test_latest_terminal_state(self, harness: dict) -> None:
        client, store, loop = (
            harness["client"], harness["store"], harness["loop"],
        )
        _mk(client, "nb-ing4")
        run_id = loop.run_until_complete(
            store.insert_ingest_run("nb-ing4", "2026-07-04T00:00:00+00:00")
        )
        loop.run_until_complete(
            store.update_ingest_run(
                run_id,
                status=store.INGEST_STATUS_SUCCESS,
                finished_at="2026-07-04T00:01:00+00:00",
                exit_code=0,
                stderr_tail="",
            )
        )
        body = client.get("/api/v1/notebooks/nb-ing4/ingest/latest").json()
        assert body["status"] == "success"
        assert body["terminal"] is True
        assert body["run_id"] == run_id


# ---------------------------------------------------------------------------
# Admin / diagnostics / export
# ---------------------------------------------------------------------------


class TestAdminAndDiagnostics:
    def test_repair_registry_shape(self, client: TestClient) -> None:
        body = client.post("/api/v1/admin/repair-registry").json()
        for key in (
            "registered", "already_registered",
            "skipped_no_marker", "skipped_malformed_marker",
        ):
            assert key in body

    def test_reconcile_marker_no_marker_422(self, client: TestClient) -> None:
        _mk(client, "nb-rec")
        r = client.post("/api/v1/notebooks/nb-rec/reconcile-marker")
        assert r.status_code == 422

    def test_health_no_marker(self, client: TestClient) -> None:
        _mk(client, "nb-h")
        body = client.get("/api/v1/notebooks/nb-h/health").json()
        assert body["status"] == "no_marker"
        assert body["format_version"] == API_V1_FORMAT_VERSION

    def test_parse_status_arxiv_kind(self, client: TestClient) -> None:
        _mk(client, "nb-ps")
        body = client.get("/api/v1/notebooks/nb-ps/parse-status").json()
        assert body["parse_status"] == "skipped"
        assert body["notebook_kind"] == "arxiv"

    def test_export_returns_valid_tar_with_manifest(
        self, client: TestClient, tmp_path: Path,
    ) -> None:
        import io
        import tarfile

        _mk(client, "nb-ex")
        r = client.get("/api/v1/notebooks/nb-ex/export")
        assert r.status_code == 200
        with tarfile.open(fileobj=io.BytesIO(r.content)) as tar:
            assert "manifest.json" in tar.getnames()
