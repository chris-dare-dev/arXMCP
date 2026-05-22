"""Tests for the m8 htmx + Jinja2 UI pages.

Coverage matrix:

- TestIndexPage              — AC #1 (landing page + create form + notebook list)
- TestNotebookDetailPage     — per-notebook detail (paper list + paste + upload)
- TestStaticAssets           — vendored htmx + CSS served from /ui/static/
- TestStaticPathTraversal    — Starlette StaticFiles built-in defense
- TestAr5ivUrlNormalizer     — AC #3 (ar5iv URL form accepted in addition to arxiv.org)
- TestAutoescape             — Jinja2 autoescape on display_name (XSS defense)

The fixture pattern mirrors ``tests/test_notebook_api.py``: build a
minimal FastAPI app with the notebooks + ui routers + a real
NotebooksStore against tmp_path SQLite. Adds a static mount for
``frontend/static/`` so the htmx/CSS assertions can fire.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import (
    _arxiv_url_to_paper_id,
)
from server.routes.notebooks import (
    router as notebooks_router,
)
from server.routes.ui import router as ui_router
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "frontend" / "static"


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    return base


@pytest.fixture
def client(
    tmp_path: Path, notebooks_base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Minimal FastAPI app with the m7 + m8 routers + static mount."""
    import asyncio
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        app.mount(
            "/ui/static",
            StaticFiles(directory=str(FRONTEND_STATIC)),
            name="ui-static",
        )
        monkeypatch.setattr(
            notebooks_module, "_now_iso",
            lambda: "2026-05-22T16:00:00+00:00",
        )
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# AC #1 — Landing page
# ---------------------------------------------------------------------------


class TestIndexPage:
    def test_get_ui_returns_html(self, client: TestClient) -> None:
        r = client.get("/ui/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "<!DOCTYPE html>" in r.text or "<html" in r.text

    def test_index_has_create_form(self, client: TestClient) -> None:
        r = client.get("/ui/")
        body = r.text
        # AC #1: create-notebook form
        assert 'name="slug"' in body
        assert 'hx-post="/ui/api/notebooks"' in body

    def test_index_lists_existing_notebooks(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.get("/ui/")
        assert r.status_code == 200
        body = r.text
        assert "demo-nb" in body
        # AC #1: per-notebook "open" link
        assert 'href="/ui/notebooks/demo-nb"' in body

    def test_empty_state_when_no_notebooks(self, client: TestClient) -> None:
        r = client.get("/ui/")
        body = r.text
        assert "No notebooks yet" in body or "(0)" in body or "0)" in body

    def test_vendored_htmx_referenced(self, client: TestClient) -> None:
        """AC #5: htmx loaded from /ui/static/, not a CDN."""
        r = client.get("/ui/")
        body = r.text
        assert '/ui/static/htmx.min.js' in body
        # And NOT any CDN reference (no unpkg.com, jsdelivr, cdnjs).
        for cdn in ("unpkg.com", "jsdelivr", "cdnjs.cloudflare"):
            assert cdn not in body, f"CDN reference leaked: {cdn}"


# ---------------------------------------------------------------------------
# Per-notebook detail page
# ---------------------------------------------------------------------------


class TestNotebookDetailPage:
    def test_get_notebook_detail(self, client: TestClient) -> None:
        client.post(
            "/ui/api/notebooks",
            json={"slug": "demo-nb", "display_name": "Demo NB"},
        )
        r = client.get("/ui/notebooks/demo-nb")
        assert r.status_code == 200
        body = r.text
        assert "demo-nb" in body
        assert "Demo NB" in body

    def test_detail_has_url_paste_form(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.get("/ui/notebooks/demo-nb")
        body = r.text
        assert 'name="arxiv_url"' in body
        assert 'hx-post="/ui/api/notebooks/demo-nb/papers"' in body

    def test_detail_has_upload_form(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.get("/ui/notebooks/demo-nb")
        body = r.text
        # AC #2: drag-drop upload card → multipart upload endpoint
        assert 'hx-post="/ui/api/notebooks/demo-nb/papers/upload"' in body
        assert 'hx-encoding="multipart/form-data"' in body
        assert 'name="paper_id"' in body
        assert 'name="file"' in body

    def test_detail_404_on_missing_notebook(self, client: TestClient) -> None:
        r = client.get("/ui/notebooks/nope")
        assert r.status_code == 404

    def test_detail_422_on_malformed_slug(self, client: TestClient) -> None:
        r = client.get("/ui/notebooks/UPPER")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Static asset serving (AC #5)
# ---------------------------------------------------------------------------


class TestStaticAssets:
    def test_htmx_min_js_served(self, client: TestClient) -> None:
        r = client.get("/ui/static/htmx.min.js")
        assert r.status_code == 200
        # The vendored file starts with a comment header naming the
        # version (m8 implementation discipline).
        body = r.text
        assert "htmx 2.0.10" in body
        assert "0BSD" in body
        # And the actual htmx code follows.
        assert "function" in body  # htmx exports a function

    def test_css_served(self, client: TestClient) -> None:
        r = client.get("/ui/static/app.css")
        assert r.status_code == 200
        assert "text/css" in r.headers["content-type"]

    def test_static_404_on_missing_asset(self, client: TestClient) -> None:
        r = client.get("/ui/static/does-not-exist.js")
        assert r.status_code == 404


class TestStaticPathTraversal:
    """Starlette StaticFiles has built-in path-traversal defense via
    ``os.path.commonpath`` after ``realpath`` resolution. These
    tests pin that protection so a future refactor of the mount
    can't accidentally regress it."""

    def test_path_traversal_via_dotdot_blocked(
        self, client: TestClient,
    ) -> None:
        # The HTTP layer normalizes /../ in URLs differently than the
        # filesystem layer, but Starlette's StaticFiles guards both.
        # A traversal attempt resolves to a path outside the static
        # dir → 404.
        r = client.get("/ui/static/../config.py")
        assert r.status_code in (
            # Starlette's response when the path normalization
            # collapses to something outside the static dir.
            404, 403,
        )
        # Whatever the status, the response MUST NOT contain the
        # contents of config.py — assert defensively.
        body = r.text
        assert "ARXMCP" not in body  # config.py contains ARXMCP_ vars


# ---------------------------------------------------------------------------
# AC #3 — ar5iv URL accepted by the normalizer
# ---------------------------------------------------------------------------


class TestAr5ivUrlNormalizer:
    """m8 AC #3 extends the m7 normalizer to accept
    ``ar5iv.labs.arxiv.org/html/<id>`` in addition to
    ``arxiv.org/abs/<id>``."""

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://ar5iv.labs.arxiv.org/html/2604.26204", "2604.26204"),
            ("http://ar5iv.labs.arxiv.org/html/2604.26204", "2604.26204"),
            ("https://ar5iv.labs.arxiv.org/html/2604.26204v3", "2604.26204v3"),
            ("https://ar5iv.labs.arxiv.org/html/hep-th/0001234", "hep-th/0001234"),
            ("https://ar5iv.labs.arxiv.org/html/2604.26204/", "2604.26204"),
        ],
    )
    def test_ar5iv_forms_accepted(
        self, url: str, expected: str,
    ) -> None:
        assert _arxiv_url_to_paper_id(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            # Wrong path prefix for ar5iv host
            "https://ar5iv.labs.arxiv.org/abs/2604.26204",
            # Wrong path prefix for arxiv.org host
            "https://arxiv.org/html/2604.26204",
            # arxiv.org with /pdf/ still rejected (m7 behavior)
            "https://arxiv.org/pdf/2604.26204.pdf",
            # Subdomain that isn't in the whitelist
            "https://www.arxiv.org/abs/2604.26204",
            # ar5iv subdomain typo
            "https://ar5iv.labs.arxiv.com/html/2604.26204",
        ],
    )
    def test_invalid_forms_still_rejected(self, url: str) -> None:
        assert _arxiv_url_to_paper_id(url) is None

    def test_arxiv_org_still_works(self) -> None:
        """Regression: m7's arxiv.org/abs/ path MUST keep working."""
        result = _arxiv_url_to_paper_id("https://arxiv.org/abs/2604.26204")
        assert result == "2604.26204"

    def test_url_paste_via_api_accepts_ar5iv(
        self, client: TestClient,
    ) -> None:
        """End-to-end: posting an ar5iv URL to the m7 paste endpoint
        now succeeds (m7 would have returned 422 before m8)."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://ar5iv.labs.arxiv.org/html/2604.26204"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["paper_id"] == "2604.26204"


# ---------------------------------------------------------------------------
# Jinja2 autoescape (FM defense)
# ---------------------------------------------------------------------------


class TestAutoescape:
    """The display_name field has no slug regex — a notebook named
    ``<script>alert(1)</script>`` would be XSS without autoescape.
    Jinja2Templates(autoescape=True) is explicit in the UI route
    (m8 synthesis)."""

    def test_display_name_html_is_escaped(self, client: TestClient) -> None:
        client.post(
            "/ui/api/notebooks",
            json={
                "slug": "xss-nb",
                "display_name": "<script>alert(1)</script>",
            },
        )
        r = client.get("/ui/")
        body = r.text
        # The raw <script> tag MUST NOT appear in the rendered HTML.
        assert "<script>alert(1)</script>" not in body
        # The escaped form MUST appear (proves the value was rendered,
        # just safely).
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
