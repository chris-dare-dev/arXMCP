"""Tests for the m10 paper preview route + browse-table Preview link.

Coverage matrix (driven by the m10 research synthesis):

- TestPreviewHappyPath         — AC #1: HTML body + exact CSP bytes
- TestPreviewScriptIsolation   — AC #3: ``<script>`` in stored HTML is
                                 served as-is BUT CSP forbids execution
                                 (header-contract assertion; the
                                 browser-side enforcement is the
                                 actual mechanism)
- TestPreviewExternalImgBlocked — AC #4: img-src 'self' data: present
                                  (header-contract assertion)
- TestPreviewMissing           — 404 with generic body when HTML absent
- TestPreviewPaperIdValidation — 422 on traversal / malformed paper_id
- TestPreviewSlugValidation    — 422 on malformed slug
- TestSearchOrder              — notebook-scoped wins over corpus-global
- TestCorpusFallback           — corpus-global used when notebook-scoped absent
- TestBrowseTableLinkConditional — Preview link rendered iff has_preview

Fixture pattern matches ``tests/test_ui_html_pages.py``: minimal
FastAPI app with the m7 (notebooks) + m8 (ui) routers + SecurityHeaders
middleware (so we can verify the broader m8 CSP is OVERRIDDEN by the
m10 handler's tighter CSP). The notebooks_base / corpus_parsed
fixtures monkeypatch the shared :mod:`tools._notebook_common`
constants to point at tmp_path so the search-order tests can plant
files at both locations.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.middleware import (
    CONTENT_SECURITY_POLICY_PREVIEW,
    SecurityHeadersMiddleware,
)
from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes import ui as ui_module
from server.routes.notebooks import router as notebooks_router
from server.routes.ui import router as ui_router
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    return base


@pytest.fixture
def corpus_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "corpus" / "parsed"
    base.mkdir(parents=True)
    monkeypatch.setattr(_notebook_common, "CORPUS_PARSED_DIR", base)
    # The ui module imports CORPUS_PARSED_DIR at module load, so we
    # also need to patch the name as imported into ui_module.
    monkeypatch.setattr(ui_module, "CORPUS_PARSED_DIR", base, raising=False)
    return base


@pytest.fixture
def client(
    tmp_path: Path,
    notebooks_base: Path,
    corpus_parsed: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Minimal FastAPI app with notebooks + ui routers + SecurityHeaders.

    The SecurityHeadersMiddleware is included so we can prove the
    handler's tight CSP wins over the middleware's broader /ui/* CSP
    (m10 synthesis A4 — idempotency override mechanism).
    """
    import asyncio
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        app.add_middleware(SecurityHeadersMiddleware)
        monkeypatch.setattr(
            notebooks_module, "_now_iso",
            lambda: "2026-05-22T16:00:00+00:00",
        )
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _plant_notebook_html(
    notebooks_base: Path, slug: str, paper_id: str, body: bytes
) -> Path:
    """Create the slug dir + ar5iv subdir, write the flat HTML file."""
    flat = paper_id.replace("/", "_")
    ar5iv_dir = notebooks_base / slug / "ar5iv"
    ar5iv_dir.mkdir(parents=True, exist_ok=True)
    path = ar5iv_dir / f"{flat}.html"
    path.write_bytes(body)
    return path


def _plant_corpus_html(
    corpus_parsed: Path, paper_id: str, body: bytes
) -> Path:
    """Create the corpus-parsed subdir + index.html for ``paper_id``."""
    paper_dir = corpus_parsed / paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    path = paper_dir / "index.html"
    path.write_bytes(body)
    return path


# ---------------------------------------------------------------------------
# AC #1 — Happy path
# ---------------------------------------------------------------------------


class TestPreviewHappyPath:
    def test_returns_html_with_tight_csp(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """Stored HTML served verbatim with exact-bytes preview CSP."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        body = b"<!DOCTYPE html><html><body><p>theorem 1</p></body></html>"
        _plant_notebook_html(notebooks_base, "demo-nb", "2604.26204", body)

        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 200, r.text
        assert "text/html" in r.headers["content-type"]
        assert r.content == body

        # Exact-bytes CSP assertion (byte-stable constant discipline).
        assert (
            r.headers["content-security-policy"]
            == CONTENT_SECURITY_POLICY_PREVIEW.decode("ascii")
        )

    def test_csp_overrides_middleware_ui_csp(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """The handler's tight CSP wins over SecurityHeadersMiddleware's
        broader /ui/* CSP via the ``not in existing`` idempotency check
        (m10 synthesis A4)."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        _plant_notebook_html(
            notebooks_base, "demo-nb", "2604.26204", b"<html></html>",
        )
        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        # The broad m8 UI CSP contains ``script-src 'self' 'unsafe-inline'``.
        # The preview CSP MUST NOT contain ``'unsafe-inline'`` for scripts.
        assert "'unsafe-inline'" in csp  # only for style-src
        assert "script-src 'none'" in csp
        # The preview CSP does NOT include ``connect-src`` (the m8 UI
        # CSP has ``connect-src 'self'``); if the middleware's broader
        # CSP had been merged or appended this would fail.
        assert "connect-src" not in csp

    def test_response_includes_referrer_policy_no_referrer(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """F7 closure (m10 adversary critique): if the preview tab
        somehow navigates to an external site, suppress the Referer
        header so the user's notebook slug doesn't leak to attackers."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        _plant_notebook_html(
            notebooks_base, "demo-nb", "2604.26204",
            b"<html></html>",
        )
        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 200
        assert r.headers.get("referrer-policy") == "no-referrer"


# ---------------------------------------------------------------------------
# F1 — meta-refresh stripping
# ---------------------------------------------------------------------------


class TestMetaRefreshStripped:
    """F1 closure (m10 adversary critique): the direct-serve route
    shape (synthesis D1) has no CSP3 directive that blocks navigation
    via ``<meta http-equiv="refresh">``. The handler strips the tag
    from served bytes before constructing the response.
    """

    @pytest.mark.parametrize(
        "meta_tag",
        [
            b'<meta http-equiv="refresh" content="0;url=https://evil.example/">',
            b'<META HTTP-EQUIV=refresh CONTENT="5;url=//attacker/">',
            b"<meta http-equiv = refresh content='0;url=http://attacker'>",
            b"<meta http-equiv='REFRESH' content='3'>",
        ],
    )
    def test_meta_refresh_stripped_from_served_html(
        self, client: TestClient, notebooks_base: Path, meta_tag: bytes,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        body = (
            b"<!DOCTYPE html><html><head>"
            + meta_tag
            + b"</head><body>safe content</body></html>"
        )
        _plant_notebook_html(notebooks_base, "demo-nb", "2604.26204", body)
        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 200
        # The meta-refresh tag must be ABSENT from the served body.
        assert meta_tag not in r.content
        # The substitution marker is present (operator-debug aid).
        assert b"meta-refresh stripped" in r.content
        # Non-refresh body content is preserved verbatim.
        assert b"safe content" in r.content

    def test_legit_meta_tags_are_preserved(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """Only meta-refresh is stripped — charset/viewport/etc remain."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        body = (
            b"<!DOCTYPE html><html><head>"
            b'<meta charset="utf-8">'
            b'<meta name="viewport" content="width=device-width">'
            b'<meta property="og:title" content="Some paper">'
            b"</head><body>x</body></html>"
        )
        _plant_notebook_html(notebooks_base, "demo-nb", "2604.26204", body)
        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 200
        # All three legit meta tags survive verbatim.
        assert b'<meta charset="utf-8">' in r.content
        assert b'<meta name="viewport"' in r.content
        assert b'<meta property="og:title"' in r.content
        # No stripping marker (no meta-refresh in the input).
        assert b"meta-refresh stripped" not in r.content


# ---------------------------------------------------------------------------
# AC #3 — Script in stored HTML is not executed (CSP-by-inspection)
# ---------------------------------------------------------------------------


class TestPreviewScriptIsolation:
    def test_script_tag_served_verbatim_but_csp_blocks_execution(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """A paper containing ``<script>alert(1)</script>`` returns the
        tag verbatim but the response CSP ``script-src 'none'`` blocks
        the browser from executing it.

        We assert the header contract (what we control); the actual
        execution-blocking is the browser's job per CSP3.
        """
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        body = (
            b"<!DOCTYPE html><html><body>"
            b"<script>alert(1)</script>"
            b"<p>after script</p>"
            b"</body></html>"
        )
        _plant_notebook_html(notebooks_base, "demo-nb", "2604.26204", body)
        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 200
        # The script tag IS in the response (we don't strip content).
        assert b"<script>alert(1)</script>" in r.content
        # The CSP prevents execution.
        csp = r.headers["content-security-policy"]
        assert "script-src 'none'" in csp


# ---------------------------------------------------------------------------
# AC #4 — External img source blocked by img-src 'self' data:
# ---------------------------------------------------------------------------


class TestPreviewExternalImgBlocked:
    def test_csp_restricts_img_src_to_self_and_data(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        body = (
            b"<!DOCTYPE html><html><body>"
            b'<img src="https://example.com/track.png">'
            b"</body></html>"
        )
        _plant_notebook_html(notebooks_base, "demo-nb", "2604.26204", body)
        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        assert "img-src 'self' data:" in csp
        # default-src 'none' is the umbrella for fetch directives but
        # img-src explicitly overrides — exfil to example.com is blocked.
        assert "default-src 'none'" in csp


# ---------------------------------------------------------------------------
# 404 — missing HTML
# ---------------------------------------------------------------------------


class TestPreviewMissing:
    def test_404_when_html_absent(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        # No HTML planted; route should 404.
        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 404
        # Generic body — must not leak filesystem path.
        assert "no preview available" in r.text
        assert str(notebooks_base) not in r.text
        assert ".html" not in r.text


# ---------------------------------------------------------------------------
# Path-traversal & malformed input
# ---------------------------------------------------------------------------


class TestPreviewPaperIdValidation:
    @pytest.mark.parametrize(
        "bad_id",
        [
            "../etc/passwd",
            "2604.26204%0Afoo",  # URL-encoded newline (m1-rect-F3 \Z anchor)
            "2604.26204;%20rm%20-rf%20/",  # URL-encoded shell metachars
            "not-an-arxiv-id",
            "2604.26204%00null",  # URL-encoded NUL byte
        ],
    )
    def test_rejects_malformed_paper_id(
        self, client: TestClient, bad_id: str,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        # ``{paper_id:path}`` accepts slashes; the is_valid_paper_id
        # guard rejects them post-routing. All malformed IDs must
        # surface as 422 (validator rejection) or 404 (FastAPI
        # routing rejection). F3 closure (m10 adversary critique):
        # tightened from ``!= 200`` — 5xx (server crash) would
        # silently pass the old assertion and hide a real bug.
        r = client.get(
            f"/ui/notebooks/demo-nb/papers/{bad_id}/preview",
        )
        assert r.status_code in (404, 422), (
            f"unexpected status {r.status_code}: {r.text}"
        )
        # Belt-and-braces: also assert no SERVER-SIDE filesystem-path
        # leak in the response body. (User-supplied input being echoed
        # back in a 422 detail is standard FastAPI behavior and is not
        # a leak — the forbidden tokens here are the server's own var/
        # tree and notebook layout roots.)
        assert "/var/arxmcp/" not in r.text
        assert "notebooks/demo-nb/ar5iv/" not in r.text

    def test_traversal_attempt_returns_422_via_validator(
        self, client: TestClient,
    ) -> None:
        """F2 closure (m10 adversary critique): the OLD test issued
        ``client.get("/ui/notebooks/demo-nb/papers/../etc/preview")``
        which httpx silently normalized RFC 3986 dot-segments OUT
        of the wire payload — the literal ``../`` never reached the
        server, so the assertion passed on a different code path
        than the validator chain it claimed to verify.

        Fixed: URL-encode the traversal segments so httpx leaves
        them intact. The route's ``is_valid_paper_id`` guard now
        actually fires.
        """
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        # %2F is the URL-encoded form of '/'; httpx does NOT decode
        # these before send. The path-segment is delivered to the
        # server as ``..%2Fetc%2Fpasswd`` and FastAPI's routing
        # passes it through ``{paper_id:path}`` to the handler. The
        # handler's is_valid_paper_id check then rejects because
        # ``..`` is not a valid arXiv ID prefix.
        r = client.get(
            "/ui/notebooks/demo-nb/papers/..%2Fetc%2Fpasswd/preview"
        )
        assert r.status_code == 422, (
            f"expected 422 from is_valid_paper_id rejection, got "
            f"{r.status_code}: {r.text}"
        )
        # No SERVER-SIDE filesystem leak. (The 422 detail legitimately
        # echoes the user's malformed input — that's standard FastAPI
        # validation-error behavior and is NOT a leak.) The forbidden
        # tokens are the server's own var/ tree and notebook layout
        # roots.
        assert "/var/arxmcp/" not in r.text
        assert "notebooks/demo-nb/ar5iv/" not in r.text

    def test_is_valid_paper_id_rejects_traversal_directly(self) -> None:
        """F2 closure: route-independent test of the validator itself.

        Calls ``is_valid_paper_id`` directly with traversal-style
        inputs to prove the regex rejects them. This pins the
        contract to the validator function so a future refactor of
        the route layer cannot silently regress the security
        boundary.
        """
        from ingest.identifiers import is_valid_paper_id

        bad_inputs = [
            "../etc/passwd",
            "..",
            "../../etc",
            "2604.26204/../../etc",
            "/etc/passwd",
        ]
        for s in bad_inputs:
            assert not is_valid_paper_id(s), (
                f"is_valid_paper_id({s!r}) returned True — security gap"
            )


class TestPreviewSlugValidation:
    def test_rejects_malformed_slug(self, client: TestClient) -> None:
        r = client.get(
            "/ui/notebooks/BAD-CAPS/papers/2604.26204/preview"
        )
        assert r.status_code == 422

    def test_rejects_slug_with_path_chars(self, client: TestClient) -> None:
        r = client.get(
            "/ui/notebooks/..%2Fetc/papers/2604.26204/preview"
        )
        # 404 or 422 — both are safe (FastAPI routing decodes %2F
        # behaviour varies; either way, no traversal succeeds).
        assert r.status_code in (404, 422)


# ---------------------------------------------------------------------------
# Search-order semantics (m10 synthesis A1)
# ---------------------------------------------------------------------------


class TestSearchOrder:
    def test_notebook_scoped_wins_over_corpus_global(
        self,
        client: TestClient,
        notebooks_base: Path,
        corpus_parsed: Path,
    ) -> None:
        """Both paths exist on disk; the notebook-scoped HTML is served."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        nb_body = b"<html><body>FROM-NOTEBOOK</body></html>"
        corpus_body = b"<html><body>FROM-CORPUS</body></html>"
        _plant_notebook_html(notebooks_base, "demo-nb", "2604.26204", nb_body)
        _plant_corpus_html(corpus_parsed, "2604.26204", corpus_body)

        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 200
        assert r.content == nb_body
        assert b"FROM-NOTEBOOK" in r.content
        assert b"FROM-CORPUS" not in r.content


class TestCorpusFallback:
    def test_corpus_used_when_notebook_missing(
        self,
        client: TestClient,
        notebooks_base: Path,
        corpus_parsed: Path,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        corpus_body = b"<html><body>FROM-CORPUS</body></html>"
        _plant_corpus_html(corpus_parsed, "2604.26204", corpus_body)

        r = client.get("/ui/notebooks/demo-nb/papers/2604.26204/preview")
        assert r.status_code == 200
        assert r.content == corpus_body
        assert b"FROM-CORPUS" in r.content

    def test_old_style_paper_id_corpus_fallback(
        self,
        client: TestClient,
        notebooks_base: Path,
        corpus_parsed: Path,
    ) -> None:
        """Old-style IDs like hep-th/0001234 nest naturally in
        corpus/parsed/<paper_id>/index.html.

        F4 closure (m10 adversary critique): also asserts the tight
        CSP is applied to the old-style path — the v2 server is
        built for the math-ph / hep-th category, so this boundary
        MUST hold for those IDs.
        """
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        corpus_body = b"<html><body>OLD-STYLE-OK</body></html>"
        _plant_corpus_html(corpus_parsed, "hep-th/0001234", corpus_body)

        r = client.get(
            "/ui/notebooks/demo-nb/papers/hep-th/0001234/preview"
        )
        assert r.status_code == 200
        assert r.content == corpus_body
        # F4: CSP boundary holds for old-style IDs.
        assert (
            r.headers["content-security-policy"]
            == CONTENT_SECURITY_POLICY_PREVIEW.decode("ascii")
        )

    def test_old_style_paper_id_notebook_scoped(
        self,
        client: TestClient,
        notebooks_base: Path,
    ) -> None:
        """Old-style IDs with ``/`` are flattened to ``_`` for the
        notebook-scoped on-disk filename (m8 contract preserved).

        F4 closure (m10 adversary critique): also asserts CSP.
        """
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        nb_body = b"<html><body>OLD-STYLE-NB</body></html>"
        # Plant with the flattened form on disk.
        flat = "hep-th_0001234"
        ar5iv_dir = notebooks_base / "demo-nb" / "ar5iv"
        ar5iv_dir.mkdir(parents=True, exist_ok=True)
        (ar5iv_dir / f"{flat}.html").write_bytes(nb_body)

        r = client.get(
            "/ui/notebooks/demo-nb/papers/hep-th/0001234/preview"
        )
        assert r.status_code == 200
        assert r.content == nb_body
        # F4: CSP boundary holds for old-style IDs.
        assert (
            r.headers["content-security-policy"]
            == CONTENT_SECURITY_POLICY_PREVIEW.decode("ascii")
        )


# ---------------------------------------------------------------------------
# Browse-table Preview link conditional rendering (AC #2)
# ---------------------------------------------------------------------------


class TestBrowseTableLinkConditional:
    def test_preview_link_when_html_exists(
        self,
        client: TestClient,
        notebooks_base: Path,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.26204"},
        )
        # Plant the HTML so has_preview is True.
        _plant_notebook_html(
            notebooks_base, "demo-nb", "2604.26204",
            b"<html><body>x</body></html>",
        )
        r = client.get("/ui/notebooks/demo-nb")
        assert r.status_code == 200
        body = r.text
        # Live anchor present.
        assert (
            '<a href="/ui/notebooks/demo-nb/papers/2604.26204/preview"'
            in body
        )
        assert 'target="_blank"' in body
        assert 'rel="noopener"' in body

    def test_preview_tooltip_when_html_absent(
        self,
        client: TestClient,
        notebooks_base: Path,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.26204"},
        )
        # No HTML planted; the row should render a tooltip <span>.
        r = client.get("/ui/notebooks/demo-nb")
        assert r.status_code == 200
        body = r.text
        # No live anchor for THIS paper's preview.
        assert (
            '<a href="/ui/notebooks/demo-nb/papers/2604.26204/preview"'
            not in body
        )
        # F6 closure (m10 adversary critique): actionable tooltip text
        # directing the operator to the upload card. The old
        # "no preview available" string left the user at a dead end.
        assert (
            'title="upload an ar5iv HTML to enable preview"' in body
        )
        # The text "Preview" is still present (column header + the
        # span content) — both are valid.
        assert "Preview" in body


# ---------------------------------------------------------------------------
# Upload fragment carries the Preview link too (m8 upload contract)
# ---------------------------------------------------------------------------


class TestUploadFragmentPreviewLink:
    def test_upload_fragment_includes_preview_anchor(
        self, client: TestClient,
    ) -> None:
        """After upload, the htmx-appended row carries a live Preview
        link (the file is now on disk, so has_preview is True)."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={
                "file": (
                    "ar5iv.html",
                    b"<!DOCTYPE html><html><body>x</body></html>",
                    "text/html",
                ),
            },
        )
        assert r.status_code == 201, r.text
        body = r.text
        assert (
            '<a href="/ui/notebooks/demo-nb/papers/2604.26204/preview"'
            in body
        )
        assert 'target="_blank"' in body
        assert 'rel="noopener"' in body


# ---------------------------------------------------------------------------
# stage3/cross-r1 — byte-cap exemption for the stored-doc preview
# ---------------------------------------------------------------------------


class TestPreviewByteCapExemption:
    """The preview route serves verbatim ar5iv/LaTeXML HTML, which for
    real papers routinely exceeds the 256 KiB inline-response cap
    (BodySizeCapMiddleware). Before the fix, the entry point of the D7
    stored-document MathML track dead-ended on a raw JSON 413 for real
    content (the mandated E2E's own 1.78 MB paper reproduces it).

    The other preview tests build a MINIMAL app WITHOUT the byte-cap
    middleware (that is exactly why the hermetic gate missed this), so
    this class drives the FULL ``create_app()`` stack — the same one the
    daemon runs — with a >256 KiB stored fixture. It would FAIL before
    ``_is_exempt_path`` learned the preview route (raw 413
    ``payload_too_large``)."""

    OVER_CAP_HTML = (
        b"<!DOCTYPE html><html><body>"
        + (b"<p>theorem body with MathML</p>" * 12000)
        + b"</body></html>"
    )  # ~372 KB > 262144

    def _real_app_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> TestClient:
        from server.config import Config
        from server.main import create_app

        monkeypatch.setenv("ARXMCP_LANCEDB_PATH", str(tmp_path / "lancedb-empty"))
        monkeypatch.delenv("ARXMCP_ALLOWED_ORIGINS", raising=False)
        monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
        monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
        return TestClient(create_app(Config()))

    def test_over_cap_preview_not_413_new_style_id(
        self, tmp_path: Path, corpus_parsed: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A >256 KiB stored preview (new-style arXiv id) must be served,
        not 413'd, through the real create_app() middleware stack."""
        assert len(self.OVER_CAP_HTML) > 262144, "fixture must exceed the cap"
        _plant_corpus_html(corpus_parsed, "0705.3794", self.OVER_CAP_HTML)
        client = self._real_app_client(tmp_path, monkeypatch)
        r = client.get("/ui/notebooks/e2e-live/papers/0705.3794/preview")
        assert r.status_code != 413, (
            f"preview 413'd on a {len(self.OVER_CAP_HTML)}-byte stored paper "
            f"— the D7 stored-doc math track dead-ends on real content; "
            f"body={r.text[:200]!r}"
        )
        assert r.status_code == 200, r.text
        assert r.content == self.OVER_CAP_HTML

    def test_over_cap_preview_not_413_old_style_id(
        self, tmp_path: Path, corpus_parsed: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Old-style ids (``math/0211159`` — the route's ``paper_id:path``
        converter, an extra path segment) also clear the cap."""
        _plant_corpus_html(corpus_parsed, "math/0211159", self.OVER_CAP_HTML)
        client = self._real_app_client(tmp_path, monkeypatch)
        r = client.get("/ui/notebooks/e2e-live/papers/math/0211159/preview")
        assert r.status_code != 413, r.text[:200]
        assert r.status_code == 200, r.text

    def test_over_cap_non_preview_ui_json_still_capped(
        self, tmp_path: Path, corpus_parsed: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Defense-in-depth: the exemption is preview-only. A JSON route
        under /ui/api that somehow returned >256 KiB must STILL trip the
        cap — the exemption must not bleed onto sibling notebook routes.
        We assert the helper directly (no oversized JSON route exists to
        exercise live)."""
        from server.main import _is_exempt_path

        # The preview route is exempt; a sibling export/JSON path is not.
        assert _is_exempt_path(
            "/ui/notebooks/e2e-live/papers/0705.3794/preview"
        )
        assert not _is_exempt_path(
            "/ui/notebooks/e2e-live/papers/0705.3794/export"
        )
        assert not _is_exempt_path("/ui/api/notebooks/e2e-live/papers")
        assert not _is_exempt_path("/ui/notebooks/e2e-live/preview")


# ---------------------------------------------------------------------------
# stage3/arx-server-r2 — non-hosted stylesheet <link>s are repointed at a
# same-origin baseline so the browser stops 404ing them as application/json
# ---------------------------------------------------------------------------


#: A realistic stored-ar5iv <head>: the three absolute stylesheet links
#: ar5iv emits (each 404s as application/json on this daemon — nothing is
#: mounted at /assets/), plus a MathJax loader <script> and a font-preload
#: link that MUST survive the rewrite untouched. Body carries a MathML
#: node (the native-render surface the CSP intentionally leaves working).
_STORED_AR5IV_HTML = (
    b"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
    b"<meta charset=\"utf-8\">\n"
    b'<link media="all" rel="stylesheet" href="/assets/ar5iv-fonts.0.8.4.css">\n'
    b'<link media="all" rel="stylesheet" href="/assets/ar5iv.0.8.4.css">\n'
    b'<link media="all" rel="stylesheet" href="/assets/ar5iv-site.0.2.2.css">\n'
    b'<link rel="preload" as="font" type="font/woff2" '
    b'href="/assets/latinmodern-math.woff2" crossorigin>\n'
    b'<script src="/assets/ar5iv-mathjax.js" defer></script>\n'
    b"</head>\n<body><article class=\"ltx_document\">"
    b'<math class="ltx_Math" display="inline"><mi>X</mi></math>'
    b"</article></body></html>"
)


class TestPreviewStylesheetRewrite:
    """The stored ar5iv / arxiv-native HTML links absolute stylesheet
    paths the daemon does NOT host (``/assets/*.css``,
    ``/static/browse/*/css/*.css``). Each 404s with
    ``content-type: application/json`` — so the browser refuses it
    ('Refused to apply style ... its MIME type application/json is not a
    supported stylesheet MIME type'), logs 3 console errors per stored
    paper, and the document renders with UA-default (unstyled) typography.

    The handler rewrites those non-hosted stylesheet ``<link>`` hrefs to
    the same-origin vendored baseline ``/ui/static/preview.css`` (which
    the tight preview CSP ``style-src 'self'`` allows and which the
    static mount serves as ``text/css``).

    Drives the FULL ``create_app()`` stack (same as the byte-cap class)
    so the assertions exercise the real static mount + middleware — the
    minimal-app fixtures elsewhere in this file do not mount
    ``/ui/static`` or ``/assets``. Before the fix these tests FAIL: the
    served body still carries ``/assets/*.css`` links and a probe of one
    such path returns 404 ``application/json``.
    """

    def _real_app_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> TestClient:
        from server.config import Config
        from server.main import create_app

        monkeypatch.setenv("ARXMCP_LANCEDB_PATH", str(tmp_path / "lancedb-empty"))
        monkeypatch.delenv("ARXMCP_ALLOWED_ORIGINS", raising=False)
        monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
        monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
        return TestClient(create_app(Config()))

    def test_assets_css_probe_404s_as_json_without_a_mount(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Root-cause pin: the daemon hosts nothing at ``/assets/``, so
        the ar5iv stylesheet path the stored HTML references 404s with a
        JSON body — the exact MIME the browser rejects. This asserts the
        server-side half of the finding independent of the rewrite; it
        stays true (the mount is deliberately never added) and documents
        WHY the rewrite is necessary."""
        client = self._real_app_client(tmp_path, monkeypatch)
        r = client.get("/assets/ar5iv.0.8.4.css")
        assert r.status_code == 404
        assert "application/json" in r.headers.get("content-type", "")

    def test_stored_stylesheet_links_repointed_new_style_id(
        self, tmp_path: Path, corpus_parsed: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The served preview no longer references any ``/assets/*.css``;
        all three are repointed at ``/ui/static/preview.css`` — which the
        static mount serves 200 as ``text/css`` (a stylesheet MIME the
        browser accepts under the tight ``style-src 'self'`` CSP)."""
        _plant_corpus_html(corpus_parsed, "0705.3794", _STORED_AR5IV_HTML)
        client = self._real_app_client(tmp_path, monkeypatch)

        r = client.get("/ui/notebooks/e2e-live/papers/0705.3794/preview")
        assert r.status_code == 200, r.text
        body = r.content
        # No non-hosted stylesheet path survives (these 404'd as JSON).
        assert b"/assets/ar5iv-fonts.0.8.4.css" not in body
        assert b"/assets/ar5iv.0.8.4.css" not in body
        assert b"/assets/ar5iv-site.0.2.2.css" not in body
        # All three now point at the same-origin baseline.
        assert body.count(b"/ui/static/preview.css") == 3

        # And that baseline is actually served with a stylesheet MIME.
        css = client.get("/ui/static/preview.css")
        assert css.status_code == 200, css.text
        assert "text/css" in css.headers.get("content-type", "")

    def test_native_browse_stylesheet_repointed(
        self, tmp_path: Path, corpus_parsed: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The arxiv-native render family (fetch-ladder rung 1) links
        ``/static/browse/<ver>/css/*.css`` — same non-hosted problem,
        same repoint. (native fixture head; ingest/ar5iv_fetch.py)."""
        native = (
            b"<!DOCTYPE html><html><head>"
            b'<link rel="stylesheet" '
            b'href="/static/browse/0.3.4/css/latexml_styles.css"/>'
            b"</head><body><article class=\"ltx_document\">x</article>"
            b"</body></html>"
        )
        _plant_corpus_html(corpus_parsed, "0705.3794", native)
        client = self._real_app_client(tmp_path, monkeypatch)
        r = client.get("/ui/notebooks/e2e-live/papers/0705.3794/preview")
        assert r.status_code == 200, r.text
        assert b"/static/browse/" not in r.content
        assert r.content.count(b"/ui/static/preview.css") == 1

    def test_rewrite_scope_leaves_script_and_font_and_csp_intact(
        self, tmp_path: Path, corpus_parsed: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Scope discipline: the rewrite touches ONLY ``.css`` stylesheet
        links. The MathJax ``<script src="/assets/...js">`` (its blocking
        is an intentional ``script-src 'none'`` effect, explicitly NOT the
        finding) and the ``/assets/*.woff2`` font-preload are left
        verbatim, and the tight preview CSP header is unchanged."""
        _plant_corpus_html(corpus_parsed, "0705.3794", _STORED_AR5IV_HTML)
        client = self._real_app_client(tmp_path, monkeypatch)
        r = client.get("/ui/notebooks/e2e-live/papers/0705.3794/preview")
        assert r.status_code == 200, r.text
        body = r.content
        # MathJax loader script + its /assets/ src survive untouched.
        assert b'<script src="/assets/ar5iv-mathjax.js" defer></script>' in body
        # Font-preload link (a .woff2, not a .css) is NOT rewritten.
        assert b'href="/assets/latinmodern-math.woff2"' in body
        # The exact tight preview CSP still wins (no widening).
        assert (
            r.headers["content-security-policy"]
            == CONTENT_SECURITY_POLICY_PREVIEW.decode("ascii")
        )


class TestPreviewStylesheetRewriteRegex:
    """Route-independent contract for the rewrite regex, pinning the
    substitution to the module constant so a future refactor of the
    handler cannot silently regress the boundary (same discipline as
    ``test_is_valid_paper_id_rejects_traversal_directly`` above)."""

    def _rewrite(self, raw: bytes) -> bytes:
        from server.routes.ui import (
            _PREVIEW_STYLESHEET_HREF,
            _PREVIEW_STYLESHEET_LINK_RE,
        )

        return _PREVIEW_STYLESHEET_LINK_RE.sub(
            rb"\g<1>" + _PREVIEW_STYLESHEET_HREF + rb"\g<2>", raw,
        )

    @pytest.mark.parametrize(
        "link",
        [
            b'<link media="all" rel="stylesheet" href="/assets/ar5iv.0.8.4.css">',
            b'<link rel="stylesheet" href="/static/browse/0.3.4/css/x.css"/>',
            b'<link rel="stylesheet" href="/assets/a.css" />',      # self-closing
            b'<link href="/assets/a.css" rel="stylesheet">',        # href first
            b"<link rel='stylesheet' href='/assets/a.css'>",        # single quotes
            b'<LINK REL="stylesheet" HREF="/assets/a.css">',        # uppercase
        ],
    )
    def test_rewrites_non_hosted_css_links(self, link: bytes) -> None:
        out = self._rewrite(link)
        assert b"/ui/static/preview.css" in out
        assert b"/assets/" not in out or b"/assets/a.css" not in out
        assert b"/static/browse/" not in out

    def test_self_closing_slash_is_preserved(self) -> None:
        out = self._rewrite(
            b'<link rel="stylesheet" href="/assets/a.css" />'
        )
        assert out.rstrip().endswith(b"/>")

    def test_multiple_links_each_rewritten(self) -> None:
        out = self._rewrite(
            b'<link rel="stylesheet" href="/assets/a.css">'
            b'<link rel="stylesheet" href="/assets/b.css">'
        )
        assert out.count(b"/ui/static/preview.css") == 2

    @pytest.mark.parametrize(
        "link",
        [
            b'<link rel="preload" as="font" href="/assets/x.woff2">',  # not .css
            b'<link rel="modulepreload" href="/assets/x.js">',         # not .css
            b'<link rel="stylesheet" href="data:text/css,body{}">',    # data uri
            b'<link rel="stylesheet" href="/ui/static/app.css">',      # already ok
            b'<link rel="stylesheet" href="styles.css">',              # relative
            b'<link rel="stylesheet" href="https://cdn.example/x.css">',  # remote
        ],
    )
    def test_leaves_out_of_scope_links_untouched(self, link: bytes) -> None:
        assert self._rewrite(link) == link
