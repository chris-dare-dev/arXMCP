"""Tests for the textbook-ingest-m4 PDF upload pre-flight gate.

Coverage matrix:

- TestPdfMagicByteSniff       — AC #1 (non-PDF magic bytes → 415)
- TestPdfPolyglotCheck        — AC #2 (polyglot tail → 415)
- TestPdfFindJavascriptGate   — AC #3 (JS / auto-action entry → 415)
- TestPdfPageCountGate        — AC #4 (>5000 pages → 415)
- TestUploadCapPerKind        — AC #5 (200 MB for textbook; 10 MB for arxiv)
- TestPdfDispatchByKind       — kind-aware dispatch + happy paths
- TestNoForkPolicy            — AC #6 (pdfid.py is not a copy)
- TestRejectionOrder          — fast-first dispatch order (FM-8 regression)

The fixture is shared with test_upload_handler.py — same minimal FastAPI
app with notebooks + ui routers + tmp_path NotebooksStore.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import (
    _ARXIV_UPLOAD_MAX_BYTES,
    _PDF_MAX_PAGE_COUNT,
)
from server.routes.notebooks import (
    router as notebooks_router,
)
from tools import _notebook_common


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(
        notebooks_module, "NOTEBOOKS_BASE", base, raising=False,
    )
    return base


@pytest.fixture
def client(
    tmp_path: Path, notebooks_base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    import asyncio
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        monkeypatch.setattr(
            notebooks_module, "_now_iso",
            lambda: "2026-05-28T00:00:00+00:00",
        )
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _create_textbook_notebook(client: TestClient, slug: str = "tb-nb") -> None:
    r = client.post(
        "/ui/api/notebooks",
        json={"slug": slug, "notebook_kind": "textbook"},
    )
    assert r.status_code == 201, r.text


def _create_arxiv_notebook(client: TestClient, slug: str = "demo-nb") -> None:
    r = client.post(
        "/ui/api/notebooks",
        json={"slug": slug, "notebook_kind": "arxiv"},
    )
    assert r.status_code == 201, r.text


def _minimal_pdf(
    page_count: int = 1,
    extras: bytes = b"",
    tail_marker: bytes = b"",
) -> bytes:
    """Build a syntactically-plausible PDF for upload tests.

    Includes:
    - The %PDF-1.4 magic header.
    - A Catalog + Pages tree with /Count=page_count.
    - Optional extras (JS tokens, multiple /Count fields, etc.).
    - Optional tail_marker appended to the last 1 KB to trigger
      polyglot detection.

    The body is NOT a real PDF a reader would render — it's a
    byte-pattern fixture for the byte-grep checks the m4 preflight
    runs. PyMuPDF (which would parse for real) is NOT a project dep
    in m4 — m5 brings it via MinerU.
    """
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count "
        + str(page_count).encode("ascii")
        + b" >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n"
        + extras
        + b"\nxref\n0 4\nstartxref\n0\n%%EOF\n"
    )
    # Pad to push the tail marker into the last 1 KB window.
    if tail_marker:
        # Append after some padding so the marker is in the tail window.
        body += b" " * 50 + tail_marker
    return body


# ---------------------------------------------------------------------------
# AC #1 — magic-byte sniff
# ---------------------------------------------------------------------------


class TestPdfMagicByteSniff:
    """Textbook-kind uploads with non-PDF magic bytes return 415."""

    def test_html_body_to_textbook_notebook_rejected(
        self, client: TestClient,
    ) -> None:
        _create_textbook_notebook(client)
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("not.pdf", b"<!DOCTYPE html><html></html>",
                            "application/pdf")},
        )
        assert r.status_code == 415, r.text
        assert "%PDF-" in r.json()["detail"]

    def test_zip_body_to_textbook_notebook_rejected(
        self, client: TestClient,
    ) -> None:
        _create_textbook_notebook(client)
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            # PK\x03\x04 = ZIP local-file-header magic
            files={"file": ("not.pdf", b"PK\x03\x04hello-zip",
                            "application/pdf")},
        )
        assert r.status_code == 415

    def test_lowercase_pdf_magic_rejected(
        self, client: TestClient,
    ) -> None:
        """ISO 32000 requires ``%PDF-`` exactly — case-sensitive."""
        _create_textbook_notebook(client)
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("any.pdf", b"%pdf-1.4\nfake",
                            "application/pdf")},
        )
        assert r.status_code == 415

    def test_pdf_magic_at_nonzero_offset_rejected(
        self, client: TestClient,
    ) -> None:
        """ISO 32000 requires the header at offset 0."""
        _create_textbook_notebook(client)
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("any.pdf", b"\x00\x00%PDF-1.4\nfake",
                            "application/pdf")},
        )
        assert r.status_code == 415


# ---------------------------------------------------------------------------
# AC #2 — polyglot tail
# ---------------------------------------------------------------------------


class TestPdfPolyglotCheck:
    def test_pdf_zip_polyglot_rejected(
        self, client: TestClient,
    ) -> None:
        _create_textbook_notebook(client)
        body = _minimal_pdf(tail_marker=b"PK\x05\x06\x00\x00")
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("polyglot.pdf", body, "application/pdf")},
        )
        assert r.status_code == 415
        assert "polyglot" in r.json()["detail"].lower()

    def test_pdf_html_polyglot_rejected(
        self, client: TestClient,
    ) -> None:
        _create_textbook_notebook(client)
        body = _minimal_pdf(tail_marker=b"</html>")
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("polyglot.pdf", body, "application/pdf")},
        )
        assert r.status_code == 415

    def test_pdf_uppercase_html_polyglot_rejected(
        self, client: TestClient,
    ) -> None:
        """Polyglot detection is case-insensitive on HTML markers."""
        _create_textbook_notebook(client)
        body = _minimal_pdf(tail_marker=b"</HTML>")
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("polyglot.pdf", body, "application/pdf")},
        )
        assert r.status_code == 415

    def test_zip_cd_outside_tail_window_passes(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """DOCUMENTED LIMITATION: a ZIP CD relocated more than 1 KB
        from the file end bypasses the tail check. m5 sandbox is the
        backstop. This test LOCKS the limitation so a future tighten-
        ing of the window surfaces here.
        """
        _create_textbook_notebook(client)
        # ZIP CD in mid-file (>1 KB from EOF), padded so the actual
        # EOF tail is clean.
        body = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n"
            b"PK\x05\x06\x00\x00"  # mid-file ZIP CD
            + b"\x00" * 2048  # 2 KB padding pushes the CD outside the 1 KB tail
            + b"\nxref\n0 4\nstartxref\n0\n%%EOF\n"
        )
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("sneaky.pdf", body, "application/pdf")},
        )
        # The current m4 implementation accepts this (limitation
        # documented in security-pdf-sandbox.md). m5 catches it.
        assert r.status_code == 201, (
            f"unexpected rejection — if this test starts failing, "
            f"the m4 polyglot check was tightened. Update "
            f".claude/docs/security-pdf-sandbox.md accordingly. "
            f"Response: {r.text}"
        )


# ---------------------------------------------------------------------------
# AC #3 — JavaScript / auto-action detection
# ---------------------------------------------------------------------------


class TestPdfFindJavascriptGate:
    @pytest.mark.parametrize(
        "token",
        ["/JS", "/JavaScript", "/OpenAction", "/AA",
         "/Launch", "/SubmitForm", "/ImportData"],
    )
    def test_each_dangerous_token_rejected(
        self, client: TestClient, token: str,
    ) -> None:
        _create_textbook_notebook(client)
        body = _minimal_pdf(
            extras=token.encode("ascii") + b" (action)\n",
        )
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("malicious.pdf", body, "application/pdf")},
        )
        assert r.status_code == 415, (
            f"token {token!r} not rejected; response: {r.text}"
        )
        assert "active-content" in r.json()["detail"]


# ---------------------------------------------------------------------------
# AC #4 — page-count probe
# ---------------------------------------------------------------------------


class TestPdfPageCountGate:
    def test_pdf_under_cap_accepted(
        self, client: TestClient,
    ) -> None:
        _create_textbook_notebook(client)
        body = _minimal_pdf(page_count=100)
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("ok.pdf", body, "application/pdf")},
        )
        assert r.status_code == 201, r.text

    def test_pdf_at_cap_accepted(
        self, client: TestClient,
    ) -> None:
        _create_textbook_notebook(client)
        body = _minimal_pdf(page_count=_PDF_MAX_PAGE_COUNT)
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("ok.pdf", body, "application/pdf")},
        )
        assert r.status_code == 201, r.text

    def test_pdf_over_cap_rejected(
        self, client: TestClient,
    ) -> None:
        _create_textbook_notebook(client)
        body = _minimal_pdf(page_count=_PDF_MAX_PAGE_COUNT + 1)
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("huge.pdf", body, "application/pdf")},
        )
        assert r.status_code == 415, r.text
        assert "5000" in r.json()["detail"] or "page" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# AC #5 — per-kind upload cap
# ---------------------------------------------------------------------------


class TestUploadCapPerKind:
    """The 200 MB envelope at the middleware layer + the 10 MB
    handler-level enforcement for arxiv-kind notebooks. Per the
    synthesis D3 mechanism.
    """

    def test_arxiv_body_at_cap_accepted(
        self, client: TestClient,
    ) -> None:
        _create_arxiv_notebook(client)
        # Body just under the 10 MB cap.
        body = (
            b"<!DOCTYPE html><html><body>"
            + b"x" * (_ARXIV_UPLOAD_MAX_BYTES - 200)
            + b"</body></html>"
        )
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("big.html", body, "text/html")},
        )
        assert r.status_code == 201, r.text[:200]

    def test_arxiv_body_over_cap_rejected_413(
        self, client: TestClient,
    ) -> None:
        _create_arxiv_notebook(client)
        # 11 MB body — over the 10 MB arxiv cap.
        body = (
            b"<!DOCTYPE html>"
            + b"x" * (_ARXIV_UPLOAD_MAX_BYTES + 1024)
        )
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("huge.html", body, "text/html")},
        )
        assert r.status_code == 413, r.text[:200]
        assert "exceeds" in r.json()["detail"].lower()
        assert "arxiv-kind" in r.json()["detail"]

    def test_textbook_body_over_arxiv_cap_accepted(
        self, client: TestClient,
    ) -> None:
        """A textbook notebook accepts bodies larger than the arxiv
        cap (10 MB). Use 12 MB — over arxiv cap, under 200 MB envelope.
        Body is a valid minimal PDF padded to the target size.
        """
        _create_textbook_notebook(client)
        body = _minimal_pdf(extras=b" " * (_ARXIV_UPLOAD_MAX_BYTES + 1024))
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("big.pdf", body, "application/pdf")},
        )
        assert r.status_code == 201, r.text[:200]


# ---------------------------------------------------------------------------
# Kind dispatch + happy paths
# ---------------------------------------------------------------------------


class TestPdfDispatchByKind:
    def test_textbook_pdf_happy_path(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        _create_textbook_notebook(client)
        body = _minimal_pdf(page_count=5)
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("book.pdf", body, "application/pdf")},
        )
        assert r.status_code == 201, r.text[:200]
        # File lands at <notebook>/pdfs/<flat_paper_id>.pdf
        pdf_path = (
            notebooks_base / "tb-nb" / "pdfs" / "textbook_my-book.pdf"
        )
        assert pdf_path.exists()
        assert pdf_path.read_bytes() == body

    def test_arxiv_html_happy_path_unchanged(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """The existing m8 ar5iv upload path still works for arxiv
        notebooks — no regression from m4's kind dispatch."""
        _create_arxiv_notebook(client)
        body = b"<!DOCTYPE html><html><body>hi</body></html>"
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("ar5iv.html", body, "text/html")},
        )
        assert r.status_code == 201, r.text[:200]
        # File lands at <notebook>/ar5iv/<flat_paper_id>.html
        html_path = (
            notebooks_base / "demo-nb" / "ar5iv" / "2604.26204.html"
        )
        assert html_path.exists()

    def test_pdf_uploaded_to_arxiv_notebook_rejected(
        self, client: TestClient,
    ) -> None:
        """An arxiv notebook expects HTML; uploading a PDF body to it
        falls through to the HTML magic-byte sniff and is rejected
        with 422 (NOT 415, because the arxiv route still uses the
        original m8 wording)."""
        _create_arxiv_notebook(client)
        body = _minimal_pdf()
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("wrong.pdf", body, "application/pdf")},
        )
        assert r.status_code == 422, r.text

    def test_html_to_textbook_uses_pdf_pipeline(
        self, client: TestClient,
    ) -> None:
        """A textbook notebook never uses the HTML magic-byte sniff —
        it ALWAYS runs the PDF preflight. An HTML upload is rejected
        with 415 (PDF magic-byte path), not 422 (HTML magic-byte path).
        """
        _create_textbook_notebook(client)
        body = b"<!DOCTYPE html><html></html>"
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("notpdf.html", body, "text/html")},
        )
        assert r.status_code == 415


# ---------------------------------------------------------------------------
# AC #6 — no-fork vendoring
# ---------------------------------------------------------------------------


class TestNoForkPolicy:
    """The pdfid module must be a fresh implementation, not a copy
    of upstream source. Verify by structural inspection.
    """

    def test_pdfid_module_is_small(self) -> None:
        """A fresh implementation in arXMCP style is ≤ 200 LOC.
        Didier Stevens' original pdfid is ~1500 LOC (CLI + XML output
        + ZIP-aware reading + many features arXMCP doesn't need).
        A file >300 LOC would be suspect.
        """
        from pathlib import Path
        repo_root = Path(__file__).parent.parent
        pdfid_path = repo_root / "tools" / "security" / "pdfid.py"
        line_count = len(pdfid_path.read_text().splitlines())
        assert 30 <= line_count <= 200, (
            f"tools/security/pdfid.py is {line_count} LOC — outside "
            f"the [30, 200] band. Below 30 may indicate a missing "
            f"feature; above 200 may indicate a vendored upstream "
            f"copy (no-fork policy violation)."
        )

    def test_pdfid_module_has_no_didier_stevens_blocks(self) -> None:
        """If `pdfid.py` literally lifted Didier Stevens' source, it
        would contain his copyright header or his function naming
        (``PDFiD``, ``cPDFDate``). Verify these substrings are absent.
        """
        from pathlib import Path
        repo_root = Path(__file__).parent.parent
        src = (repo_root / "tools" / "security" / "pdfid.py").read_text()
        # Source-text fingerprints from the upstream tool.
        forbidden = (
            "PDFiD",        # the upstream class name
            "cPDFDate",     # an upstream helper class
            "Didier Stevens Suite",  # the upstream readme name
        )
        for needle in forbidden:
            assert needle not in src, (
                f"tools/security/pdfid.py contains {needle!r} — looks "
                f"like a copy of upstream source (no-fork policy "
                f"violation)"
            )

    def test_security_readme_documents_vendoring(self) -> None:
        """The tools/security/README.md must document the no-fork
        discipline and credit the upstream algorithm.
        """
        from pathlib import Path
        repo_root = Path(__file__).parent.parent
        readme = (repo_root / "tools" / "security" / "README.md").read_text()
        # Must mention the no-fork policy AND the upstream credit.
        assert "no-fork" in readme.lower()
        assert "Didier Stevens" in readme


# ---------------------------------------------------------------------------
# Rejection order — fast checks fire BEFORE expensive ones
# ---------------------------------------------------------------------------


class TestRejectionOrder:
    """FM-8 regression guard. The 5 rejection vectors run in
    fast-first order per synthesis D5: magic-byte → polyglot → JS
    → page-count. A garbage body that fails multiple checks should
    surface the CHEAPEST check's error message — not the most
    expensive.
    """

    def test_non_pdf_body_with_lots_of_dangerous_content_fails_at_magic_byte(
        self, client: TestClient,
    ) -> None:
        """An HTML body containing ``/JS`` token + a ``</html>`` tail
        marker should still fail at the magic-byte sniff (5-byte
        read) — NOT at the JS detection or polyglot tail check."""
        _create_textbook_notebook(client)
        body = (
            b"<!DOCTYPE html>\n"
            b"/JS /JavaScript /OpenAction\n"
            b"</html>"
        )
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("garbage", body, "application/pdf")},
        )
        assert r.status_code == 415
        # The detail mentions %PDF- (magic-byte) — NOT JS / polyglot.
        assert "%PDF-" in r.json()["detail"]


# ---------------------------------------------------------------------------
# m4 rect F3 — </body> polyglot marker test
# ---------------------------------------------------------------------------


class TestPdfBodyPolyglot:
    """m4 rect F3 regression guard. ``_POLYGLOT_TAIL_MARKERS`` includes
    ``</body>`` as a defense-in-depth marker for partial-HTML
    polyglots (a PDF that's also a partial HTML doc ending in
    ``</body>`` without the outer ``</html>``). Without a test, the
    third marker is dead code in the test surface.
    """

    def test_pdf_with_body_closing_tag_rejected(
        self, client: TestClient,
    ) -> None:
        _create_textbook_notebook(client)
        body = _minimal_pdf(tail_marker=b"</body>")
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("polyglot.pdf", body, "application/pdf")},
        )
        assert r.status_code == 415
        assert "polyglot" in r.json()["detail"].lower()

    def test_pdf_with_uppercase_body_tag_rejected(
        self, client: TestClient,
    ) -> None:
        """Case-insensitive matching (the tail is lowercased before
        comparison)."""
        _create_textbook_notebook(client)
        body = _minimal_pdf(tail_marker=b"</BODY>")
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("polyglot.pdf", body, "application/pdf")},
        )
        assert r.status_code == 415


# ---------------------------------------------------------------------------
# m4 rect F4 — >200 MB middleware envelope test
# ---------------------------------------------------------------------------


class TestMiddlewareEnvelope:
    """m4 rect F4 regression guard. The AC #5 row "250 MB textbook
    → 413" is enforced by ``server/main.py::prefix_caps`` and is
    NOT tested by ``TestUploadCapPerKind`` (which uses 10 MB+1 KB
    body sizes). This test exercises the middleware envelope
    rejection directly.

    The test must use the production-equivalent middleware stack —
    the existing fixture only loads the notebooks router without
    `RequestBodySizeLimitMiddleware`. The simplest approach: assert
    the middleware constant rather than buffer 201 MB into memory
    (which would slow the test suite for a regression that's
    config-driven, not code-driven).
    """

    def test_middleware_envelope_is_200_mb(self) -> None:
        """Lock the prefix_caps value at 200 MB — the AC #5 envelope.
        A regression that lowered this value would silently reduce
        the textbook upload ceiling without triggering any other
        test failure.
        """
        from server.main import create_app

        # Inspect the middleware stack — find RequestBodySizeLimitMiddleware
        # and assert its prefix_caps. create_app is the production-
        # equivalent entry point so this catches a regression in
        # actual deployment.
        app = create_app()
        middleware_stack = app.user_middleware
        size_limit_mw = None
        for mw in middleware_stack:
            if mw.cls.__name__ == "RequestBodySizeLimitMiddleware":
                size_limit_mw = mw
                break
        assert size_limit_mw is not None, (
            "RequestBodySizeLimitMiddleware not in middleware stack"
        )
        prefix_caps = size_limit_mw.kwargs.get("prefix_caps", {})
        # textbook-ingest-m4: /ui/api/notebooks envelope is 200 MB.
        # AC #5: 250 MB body → 413; this constant IS what enforces it.
        notebooks_cap = prefix_caps.get("/ui/api/notebooks")
        assert notebooks_cap == 200 * 1024 * 1024, (
            f"/ui/api/notebooks middleware envelope is "
            f"{notebooks_cap} bytes (expected 200 MB). m4 AC #5 "
            f"requires 200 MB to allow textbook PDFs."
        )


# ---------------------------------------------------------------------------
# textbook-ingest-m10 (e5) — malformed/negative Content-Length on the
# upload PATH, under the raised 200 MB prefix carve-out
# ---------------------------------------------------------------------------


class TestUploadPathContentLengthGuards:
    """e5 / textbook-ingest-m10. ``RequestBodySizeLimitMiddleware``
    rejects a malformed or negative Content-Length with 400 BEFORE
    prefix-cap resolution AND before routing — so the
    ``/ui/api/notebooks`` upload path inherits that smuggling-signal
    guard even though m4 raised its prefix cap to 200 MB. The bare
    ``client`` fixture above does NOT mount the middleware (its 413s
    come from the route handler), so this class builds an app WITH the
    middleware. test_security.py covers the same guard on ``/healthz``;
    this pins it for the upload path specifically — closing the AC's
    "malformed/missing content-length edge cases" requirement for the
    carve-out path: malformed + negative C-L → 400 (a guard); a MISSING
    C-L → benign pass-through to the route (NOT a 400), pinned by
    ``test_missing_content_length_passes_middleware_to_route``.
    """

    @pytest.fixture
    def mw_client(
        self, notebooks_base: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Iterator[TestClient]:
        import asyncio

        from server.middleware import RequestBodySizeLimitMiddleware

        db_path = tmp_path / "notebooks.db"
        loop = asyncio.new_event_loop()
        try:
            store = loop.run_until_complete(NotebooksStore.open(db_path))
            app = FastAPI()
            app.state.notebooks_store = store
            # Mirror the production prefix carve-out (server/main.py).
            app.add_middleware(
                RequestBodySizeLimitMiddleware,
                prefix_caps={"/ui/api/notebooks": 200 * 1024 * 1024},
            )
            app.include_router(notebooks_router, prefix="/ui/api")
            with TestClient(app) as c:
                yield c
            loop.run_until_complete(store.close())
        finally:
            loop.close()

    def test_malformed_content_length_rejected_400(
        self, mw_client: TestClient,
    ) -> None:
        r = mw_client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            content=b"hi",
            headers={
                "Content-Length": "not-an-integer",
                "Content-Type": "application/octet-stream",
            },
        )
        assert r.status_code == 400, r.text[:200]
        assert r.json()["error"] == "malformed_content_length"

    def test_negative_content_length_rejected_400(
        self, mw_client: TestClient,
    ) -> None:
        r = mw_client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            content=b"hi",
            headers={
                "Content-Length": "-100",
                "Content-Type": "application/octet-stream",
            },
        )
        assert r.status_code == 400, r.text[:200]
        assert r.json()["error"] == "malformed_content_length"

    def test_missing_content_length_passes_middleware_to_route(
        self, mw_client: TestClient,
    ) -> None:
        """e5/m10 rect F3: a MISSING Content-Length is a benign
        pass-through, NOT a guard. The middleware skips the C-L block
        (``content_length_b is None``) and falls through to the eager
        pre-read; a tiny body reaches the route rather than tripping
        the malformed/negative-C-L 400. Sent as an iterator body so
        httpx uses Transfer-Encoding: chunked (no Content-Length
        header). Pins the pass-through contract so a future change that
        spuriously 400s a chunked upload trips here."""
        r = mw_client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            content=iter([b"hi"]),  # iterator → chunked, no Content-Length
            headers={"Content-Type": "application/octet-stream"},
        )
        # The middleware must NOT have rejected with its malformed/
        # negative-Content-Length 400 — missing C-L is pass-through.
        body = (
            r.json()
            if r.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        assert body.get("error") != "malformed_content_length", r.text[:200]


# ---------------------------------------------------------------------------
# textbook-ingest-m10 (e5) rect — doc-to-code symbol contract guards
# (F1 page-count symbol; F2 JS-token count). Pin the
# .claude/docs/security-pdf-sandbox.md snippets to the real code so the
# next drift trips a test instead of silently mis-documenting the
# defense.
# ---------------------------------------------------------------------------


class TestSecurityDocSymbolContract:
    """e5/m10 rect F1+F2. The security-pdf-sandbox.md code snippets must
    name the symbols that actually exist. These guards do NOT parse the
    doc — they assert the code-side contract the doc's prose commits to,
    so a rename/refactor that diverges from the doc surfaces here."""

    def test_page_count_symbol_is_declared_byte_scan_not_pymupdf(self) -> None:
        """F1: the doc page-count snippet documents
        ``_pdf_declared_page_count(pdf_bytes)`` (a /Count byte-regex),
        NOT a ``_pdf_page_count(pdf_path)`` PyMuPDF probe. Pin both the
        real symbol's presence and the wrong symbol's absence."""
        assert hasattr(notebooks_module, "_pdf_declared_page_count"), (
            "security-pdf-sandbox.md documents _pdf_declared_page_count; "
            "it must exist in server.routes.notebooks"
        )
        assert not hasattr(notebooks_module, "_pdf_page_count"), (
            "the doc no longer documents a _pdf_page_count PyMuPDF probe; "
            "if this symbol reappears, the doc snippet must be revisited"
        )

    def test_dangerous_pdf_names_is_the_documented_seven_token_set(self) -> None:
        """F2: the threat-table JS row enumerates 7 active-content
        tokens; pin DANGEROUS_PDF_NAMES to exactly that set so adding a
        token forces a doc update."""
        from tools.security.pdfid import DANGEROUS_PDF_NAMES

        expected = frozenset({
            "/JS", "/JavaScript", "/OpenAction", "/AA",
            "/Launch", "/SubmitForm", "/ImportData",
        })
        assert expected == DANGEROUS_PDF_NAMES, (
            "DANGEROUS_PDF_NAMES drifted from the 7-token set documented "
            "in .claude/docs/security-pdf-sandbox.md (threat table + "
            "'Caps enforced' section) — update the doc in lockstep"
        )


# ---------------------------------------------------------------------------
# m4 rect F6 — DB-call ordering lock
# ---------------------------------------------------------------------------


class TestDbCallOrdering:
    """m4 rect F6 regression guard. Post-m4, the upload handler
    calls ``store.get_notebook(slug)`` BEFORE validating paper_id
    format (pre-m4 the validation was first). The new ordering
    means an invalid paper_id with a VALID slug triggers a DB
    query before rejection. The slug regex bounds this — but the
    new ordering is undocumented in the route's flow comments,
    so this test locks the contract.
    """

    def test_invalid_paper_id_does_not_skip_db_lookup(
        self, client: TestClient,
    ) -> None:
        """The DB call happens; the per-kind paper_id check rejects
        after. With a non-existent slug, the DB returns None and the
        route returns 404 BEFORE the paper_id check runs — so the
        paper_id error isn't seen.
        """
        # Slug doesn't exist; paper_id is invalid; expect 404 (not
        # 422 for the bad paper_id).
        r = client.post(
            "/ui/api/notebooks/nonexistent/papers/upload",
            data={"paper_id": "definitely-not-valid"},
            files={"file": ("any.pdf", b"%PDF-1.4\nbody",
                            "application/pdf")},
        )
        # 404 = "notebook not found" — the DB lookup happened and
        # returned None BEFORE the paper_id check ran.
        assert r.status_code == 404, r.text

    def test_invalid_paper_id_with_valid_slug_returns_422(
        self, client: TestClient,
    ) -> None:
        """With a valid (existing) slug, the DB lookup succeeds and
        the paper_id check runs next. An invalid paper_id surfaces
        as 422 — proving the ordering: slug→DB→paper_id→content.
        """
        _create_textbook_notebook(client)
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "definitely:not:valid:textbook:slug"},
            files={"file": ("any.pdf", b"%PDF-1.4\nbody",
                            "application/pdf")},
        )
        # 422 = "paper_id not valid" — the DB lookup succeeded
        # (notebook exists), then paper_id validation rejected.
        assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# m4 rect F7 — /Count regex limitation lock
# ---------------------------------------------------------------------------


class TestPageCountRegexLimitations:
    """m4 rect F7 regression guard. The ``_PDF_COUNT_RE`` regex
    ``/Count\\s+(\\d+)`` requires whitespace between ``/Count`` and
    the integer. PDF allows ``%comment\\n`` between tokens which
    breaks the whitespace match. Documented limitation; this test
    LOCKS the behavior so a future tightening surfaces here.
    """

    def test_count_with_intervening_pdf_comment_misses(
        self, client: TestClient,
    ) -> None:
        """An adversary can hide a large /Count behind a PDF comment.
        The page-count probe regex doesn't account for comments, so
        the value is missed → upload accepts despite the implied
        page count being above the 5000 cap.
        """
        _create_textbook_notebook(client)
        # /Count followed by a PDF %-comment, then the number.
        # This is valid PDF syntax (ISO 32000 §7.2.4) but our regex
        # requires \s+ between /Count and \d+.
        body = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count"
            b"% adversarial comment\n"
            b"9999999"
            b" >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n"
            b"\nxref\n0 4\nstartxref\n0\n%%EOF\n"
        )
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("sneaky.pdf", body, "application/pdf")},
        )
        # Documented limitation: this is currently accepted. m5's
        # MinerU wall-clock timeout is the runtime backstop. If a
        # future tightening of the regex starts rejecting this case,
        # update the docstring at server/routes/notebooks.py
        # _PDF_COUNT_RE accordingly.
        assert r.status_code == 201, (
            "unexpected rejection — if this test starts failing, "
            "the _PDF_COUNT_RE was tightened to accept PDF comments. "
            "Update the F7 limitation docstring."
        )

    def test_counter_prefix_not_false_positive(
        self, client: TestClient,
    ) -> None:
        """Defensive: /Counter (and other /Count-prefixed names) are
        NOT matched. The regex requires \\s+ which prevents the
        substring false-positive class.
        """
        _create_textbook_notebook(client)
        # /Counter 9999999 in the body — should NOT trigger the
        # page-count rejection because /Count\\s+\\d+ doesn't match
        # the longer name /Counter.
        body = _minimal_pdf(
            extras=b"/Counter 9999999\n",
        )
        r = client.post(
            "/ui/api/notebooks/tb-nb/papers/upload",
            data={"paper_id": "textbook:my-book"},
            files={"file": ("ok.pdf", body, "application/pdf")},
        )
        assert r.status_code == 201, r.text
