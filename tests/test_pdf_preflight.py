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
