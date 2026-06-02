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

    def test_json_encoding_extension_present(self, client: TestClient) -> None:
        """ui-htmx-json-fix-m1: the base template loads the json-enc htmx
        extension and the create-notebook form opts into it via
        ``hx-ext="json-enc"``.

        This REPLACES the former ``test_json_encoding_shim_present``, which
        pinned the old inline ``htmx:configRequest`` shim. That shim set
        ``evt.detail.body`` — a hook htmx 2.0.10 does NOT read — so the
        create-notebook / add-paper forms sent an EMPTY body and the JSON
        routes returned 422 in a real browser (the JSON-direct test suite
        never caught it). The fix moves serialization into a proper htmx
        extension (``frontend/static/json-enc.js``, an ``encodeParameters``
        hook) attached per-form. Pin the load-bearing pieces:
          - the extension script is loaded from /ui/static/ (no CDN)
          - it is loaded AFTER htmx.min.js (so htmx.defineExtension exists)
          - the create-notebook form carries hx-ext="json-enc"
        A regression that drops any of these reintroduces the empty-body
        422 in the browser even while the JSON-direct tests stay green."""
        r = client.get("/ui/")
        body = r.text
        # The extension is vendored locally, not from a CDN.
        assert "/ui/static/json-enc.js" in body
        # Load order: htmx must come before json-enc (defineExtension needs htmx).
        assert body.index("/ui/static/htmx.min.js") < body.index(
            "/ui/static/json-enc.js"
        ), "json-enc.js must load AFTER htmx.min.js"
        # The create-notebook form opts into the extension.
        assert 'hx-ext="json-enc"' in body
        # The old broken hook must be gone (it set evt.detail.body, ignored
        # by htmx 2.x). Match the ASSIGNMENT, not prose mentions.
        assert "evt.detail.body =" not in body


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


# ---------------------------------------------------------------------------
# m8 rect F2 — CSP header on UI surface
# ---------------------------------------------------------------------------


class TestCSPHeaderOnUiSurface:
    """m8 rect F2: ``Content-Security-Policy`` is added to every
    response under /ui/* via ``SecurityHeadersMiddleware``. The
    policy is scoped to the UI surface — /mcp and other paths get
    no CSP (they're JSON-only and don't load scripts).

    NOTE: the minimal test fixture in this file does NOT wire the
    SecurityHeadersMiddleware (it builds a bare FastAPI app for
    speed). These tests build a separate fixture that includes the
    middleware so the header presence can be asserted directly.
    """

    def _client_with_security_headers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        notebooks_base_dir: Path,
    ) -> Iterator[TestClient]:
        import asyncio

        from server.middleware import SecurityHeadersMiddleware
        db_path = tmp_path / "csp_test.db"
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
            # Add the security middleware (the only middleware that
            # matters for this test — the other tests bypass it for
            # speed since middleware isn't on their critical path).
            app.add_middleware(SecurityHeadersMiddleware)
            with TestClient(app) as c:
                yield c
            loop.run_until_complete(store.close())
        finally:
            loop.close()

    def test_csp_header_on_ui_index(
        self, tmp_path: Path, notebooks_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for client in self._client_with_security_headers(
            tmp_path, monkeypatch, notebooks_base,
        ):
            r = client.get("/ui/")
            assert r.status_code == 200
            csp = r.headers.get("content-security-policy", "")
            assert "default-src 'self'" in csp
            assert "script-src 'self'" in csp
            assert "frame-ancestors 'none'" in csp

    def test_csp_header_on_ui_api(
        self, tmp_path: Path, notebooks_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The /ui/api/* JSON routes are also under /ui/* so they
        get the CSP. Harmless for JSON responses (browsers ignore
        CSP on application/json) but consistent."""
        for client in self._client_with_security_headers(
            tmp_path, monkeypatch, notebooks_base,
        ):
            r = client.get("/ui/api/notebooks")
            assert "content-security-policy" in {
                k.lower() for k in r.headers
            }

    def test_csp_header_absent_on_non_ui_path(
        self, tmp_path: Path, notebooks_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A path outside /ui/* (no such route in this test app —
        triggers a 404 from FastAPI) MUST NOT get the CSP header.
        Confirms the prefix-match form is correct."""
        for client in self._client_with_security_headers(
            tmp_path, monkeypatch, notebooks_base,
        ):
            r = client.get("/some/other/path")
            # 404 (no such route), but the middleware fires on every
            # response — assert the CSP header is NOT present.
            assert "content-security-policy" not in {
                k.lower() for k in r.headers
            }

    def test_csp_header_absent_on_uiother_prefix(
        self, tmp_path: Path, notebooks_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Prefix-match form (NOT substring): /uiOTHER must NOT get
        the CSP, parallel to the m7 SecFetchSite FM-3 closure."""
        for client in self._client_with_security_headers(
            tmp_path, monkeypatch, notebooks_base,
        ):
            r = client.get("/uiOTHER/foo")
            assert "content-security-policy" not in {
                k.lower() for k in r.headers
            }


# ---------------------------------------------------------------------------
# m8 rect F4 — narrowed _BYTE_CAP_EXEMPT_PREFIXES
# ---------------------------------------------------------------------------


class TestNarrowedByteCapExemptPrefixes:
    """m8 rect F4: the response-body cap exemption was narrowed from
    `/ui` to `/ui/static`. Verify the exempt-path helper still
    classifies /ui/static/* as exempt but `/ui/api/notebooks` and
    `/ui/notebooks/<slug>` as NOT exempt."""

    def test_static_path_is_exempt(self) -> None:
        from server.main import _is_exempt_path
        assert _is_exempt_path("/ui/static/htmx.min.js") is True
        assert _is_exempt_path("/ui/static/app.css") is True

    def test_api_path_is_not_exempt(self) -> None:
        from server.main import _is_exempt_path
        assert _is_exempt_path("/ui/api/notebooks") is False
        assert _is_exempt_path("/ui/api/notebooks/foo/papers") is False

    def test_html_page_path_is_not_exempt(self) -> None:
        from server.main import _is_exempt_path
        assert _is_exempt_path("/ui/notebooks/demo-nb") is False
        assert _is_exempt_path("/ui/") is False

    def test_existing_exempt_paths_still_exempt(self) -> None:
        from server.main import _is_exempt_path
        assert _is_exempt_path("/healthz") is True
        assert _is_exempt_path("/readyz") is True
        assert _is_exempt_path("/metrics") is True
        assert _is_exempt_path("/mcp") is True
        assert _is_exempt_path("/mcp/foo") is True

    def test_uiother_path_not_exempt(self) -> None:
        """Prefix-match form — /uiOTHER/static must NOT match /ui/static."""
        from server.main import _is_exempt_path
        assert _is_exempt_path("/uiOTHER/static/htmx.min.js") is False
