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
