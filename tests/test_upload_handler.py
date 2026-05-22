"""Tests for the m8 ar5iv HTML upload endpoint (AC #2 + FM-2/4/5).

Coverage matrix:

- TestUploadHappyPath        — AC #2 happy path; HTML fragment response
- TestMagicByteSniff         — FM-2 (non-HTML upload rejected)
- TestFilenameSanitization   — FM-4 (file.filename NEVER used for disk path)
- TestAtomicWrite            — FM-5 (idempotent overwrite via os.replace)
- TestPaperIdValidation      — FM-4 (paper_id is validated; not from filename)
- TestNotebookExistence      — 404 if notebook absent
- TestEmptyFile              — 422 on empty payload

The fixture is shared with test_ui_html_pages.py — the same minimal
FastAPI app with notebooks + ui routers + tmp_path NotebooksStore.
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
    _is_html_bytes,
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
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
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
            lambda: "2026-05-22T16:00:00+00:00",
        )
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _minimal_html(body: str = "Hello") -> bytes:
    return f"<!DOCTYPE html>\n<html><body>{body}</body></html>".encode()


# ---------------------------------------------------------------------------
# Happy path (AC #2)
# ---------------------------------------------------------------------------


class TestUploadHappyPath:
    def test_upload_creates_file_and_junction_row(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("ar5iv.html", _minimal_html(), "text/html")},
        )
        assert r.status_code == 201, r.text

        # Response is an HTML fragment (htmx hx-swap="beforeend").
        assert "text/html" in r.headers["content-type"]
        body = r.text
        assert "<tr" in body
        assert "2604.26204" in body

        # File landed on disk under ar5iv/.
        ar5iv_dir = notebooks_base / "demo-nb" / "ar5iv"
        assert (ar5iv_dir / "2604.26204.html").is_file()

        # Junction row exists.
        r2 = client.get("/ui/api/notebooks/demo-nb/papers")
        rows = r2.json()
        assert len(rows) == 1
        assert rows[0]["paper_id"] == "2604.26204"

    def test_upload_with_version_suffix(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204v3"},
            files={"file": ("any.html", _minimal_html(), "text/html")},
        )
        assert r.status_code == 201
        assert (notebooks_base / "demo-nb" / "ar5iv" / "2604.26204v3.html").is_file()

    def test_upload_old_style_paper_id_flattens_slash(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """Old-style IDs (``hep-th/0001234``) have a slash that
        would create a subdirectory; the handler replaces it with
        an underscore so the on-disk filename stays single-level."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "hep-th/0001234"},
            files={"file": ("any.html", _minimal_html(), "text/html")},
        )
        assert r.status_code == 201
        # Flattened: slash → underscore.
        assert (
            notebooks_base / "demo-nb" / "ar5iv" / "hep-th_0001234.html"
        ).is_file()
        # Sanity: NO subdirectory was created.
        assert not (notebooks_base / "demo-nb" / "ar5iv" / "hep-th").exists()


# ---------------------------------------------------------------------------
# FM-2: magic-byte sniff
# ---------------------------------------------------------------------------


class TestMagicByteSniff:
    @pytest.mark.parametrize(
        "head, expected",
        [
            (b"<!DOCTYPE html>\n", True),
            (b"<!doctype html>", True),
            (b"<html>", True),
            (b"<HTML lang=", True),
            (b"  \n<!DOCTYPE html>", True),  # leading whitespace ok
            (b"\xef\xbb\xbf<!DOCTYPE", True),  # BOM + html
            (b"", False),
            (b"#!/bin/sh\n", False),
            (b"\x89PNG\r\n\x1a\n", False),  # PNG magic
            (b"%PDF-1.4\n", False),
            (b"PK\x03\x04", False),  # ZIP
            (b"MZ", False),  # Windows EXE
            (b'{"json": true}', False),
            (b"<svg xmlns=", False),  # SVG isn't HTML
            (b"<?xml version", False),
        ],
    )
    def test_is_html_bytes(self, head: bytes, expected: bool) -> None:
        assert _is_html_bytes(head) is expected

    def test_upload_rejects_non_html(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            # Crafted PDF that lies about its Content-Type and extension.
            files={"file": ("ar5iv.html", b"%PDF-1.4\nfake pdf", "text/html")},
        )
        assert r.status_code == 422
        assert "does not appear to be HTML" in r.text

    def test_upload_rejects_renamed_executable(
        self, client: TestClient,
    ) -> None:
        """A .exe file renamed to .html with a forged Content-Type
        MUST still be rejected (extension alone is insufficient)."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={
                "file": ("malware.html", b"MZ\x90\x00\x03\x00", "text/html"),
            },
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# FM-4: filename sanitization (path-traversal defense)
# ---------------------------------------------------------------------------


class TestFilenameSanitization:
    def test_dotdot_in_filename_does_not_escape_dir(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """A multipart upload with filename=``../../../etc/passwd``
        must NOT write outside the notebook's ar5iv/ subdir. The
        handler derives the on-disk filename from ``paper_id``
        EXCLUSIVELY, so file.filename is irrelevant for safety."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={
                "file": (
                    "../../../etc/passwd",  # malicious filename
                    _minimal_html(),
                    "text/html",
                ),
            },
        )
        assert r.status_code == 201
        # The file landed at the SAFE derived path, not /etc/passwd.
        assert (
            notebooks_base / "demo-nb" / "ar5iv" / "2604.26204.html"
        ).is_file()
        # And there is NO file at the malicious path.
        assert not Path("/etc/passwd-fake-test-marker").exists()
        # Nor anywhere outside the notebook ar5iv/ dir.
        all_files = [
            str(p) for p in notebooks_base.rglob("*") if p.is_file()
        ]
        for f in all_files:
            assert "demo-nb/ar5iv" in f, (
                f"file landed outside the ar5iv dir: {f}"
            )

    def test_filename_with_shell_metachars_ignored(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """A filename containing shell metacharacters must not affect
        the on-disk path (which is derived from paper_id)."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={
                "file": (
                    "file;rm -rf /.html",
                    _minimal_html(),
                    "text/html",
                ),
            },
        )
        assert r.status_code == 201
        # Safe path; shell metachars from filename never reached the FS.
        assert (
            notebooks_base / "demo-nb" / "ar5iv" / "2604.26204.html"
        ).is_file()


# ---------------------------------------------------------------------------
# FM-5: atomic write + idempotent overwrite
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_no_tmp_file_remains_after_success(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("a.html", _minimal_html(), "text/html")},
        )
        ar5iv_dir = notebooks_base / "demo-nb" / "ar5iv"
        files = list(ar5iv_dir.iterdir())
        assert len(files) == 1
        assert files[0].name == "2604.26204.html"
        # No .tmp leftover.
        assert not (ar5iv_dir / "2604.26204.html.tmp").exists()

    def test_duplicate_upload_overwrites_file_returns_200(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """Re-uploading the same paper_id updates the file on disk
        (idempotent) and returns 200 (NOT 409) because the upload
        itself succeeded — the junction row already existed."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r1 = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("a.html", _minimal_html("first"), "text/html")},
        )
        assert r1.status_code == 201

        r2 = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("a.html", _minimal_html("second"), "text/html")},
        )
        assert r2.status_code == 200
        assert "existing row" in r2.text or "updated" in r2.text

        # File on disk was overwritten.
        content = (
            notebooks_base / "demo-nb" / "ar5iv" / "2604.26204.html"
        ).read_bytes()
        assert b"second" in content
        assert b"first" not in content


# ---------------------------------------------------------------------------
# Paper-ID and notebook validation
# ---------------------------------------------------------------------------


class TestPaperIdValidation:
    def test_invalid_paper_id_returns_422(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "NOT-A-PAPER-ID"},
            files={"file": ("a.html", _minimal_html(), "text/html")},
        )
        assert r.status_code == 422
        assert "not a valid arXiv id" in r.text

    def test_missing_paper_id_field_returns_422(
        self, client: TestClient,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            files={"file": ("a.html", _minimal_html(), "text/html")},
        )
        assert r.status_code == 422

    def test_trailing_newline_paper_id_rejected(
        self, client: TestClient,
    ) -> None:
        """m1-rect-F3 hardening inheritance: a paper_id with a
        trailing newline must be rejected by the form-field validator."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204\n"},
            files={"file": ("a.html", _minimal_html(), "text/html")},
        )
        assert r.status_code == 422


class TestNotebookExistence:
    def test_404_on_missing_notebook(self, client: TestClient) -> None:
        r = client.post(
            "/ui/api/notebooks/nope/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("a.html", _minimal_html(), "text/html")},
        )
        assert r.status_code == 404


class TestEmptyFile:
    def test_empty_file_rejected(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers/upload",
            data={"paper_id": "2604.26204"},
            files={"file": ("empty.html", b"", "text/html")},
        )
        assert r.status_code == 422
        assert "empty" in r.text.lower()
