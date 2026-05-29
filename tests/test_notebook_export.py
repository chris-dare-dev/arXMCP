"""notebook-surface-expansion-m6 — portable export bundle (tar + manifest).

``GET /ui/api/notebooks/{slug}/export`` streams a USTAR tar of one notebook for
backup/move (`server/routes/notebooks.py::export_notebook`). Load-bearing
properties pinned here: (a) the manifest allowlists safe fields only — NO
``lancedb_path`` / ``parsed_html_path`` / ``parse_error`` (host-path / internal-
state info-leak class, m4 D3 + m6 synthesis D3); (b) the tar bytes are
**byte-deterministic** across two exports of the same notebook (USTAR + zeroed
``mtime/uid/gid/uname/gname`` + sorted-by-name members); (c) no cross-notebook
leak (only the requested slug's rows appear); (d) per-member preflight skips
symlinks / non-files / over-long names; (e) the route is exempted from the
``BodySizeCapMiddleware`` 256 KB response cap.

Seeding mirrors the m2 ``tests/test_notebook_rename_delete.py`` pattern: a
private-loop ``NotebooksStore`` + REST seed through the TestClient portal +
direct on-disk file placement in the monkeypatched ``NOTEBOOKS_BASE``.
"""

from __future__ import annotations

import asyncio
import io
import json
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.main import _is_exempt_path
from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import router as notebooks_router
from tools import _notebook_common


@pytest.fixture
def exp_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path]]:
    """Yield ``(client, notebooks_base)`` — a minimal app with the notebooks
    router mounted, the NOTEBOOKS_BASE monkeypatched to ``tmp_path/notebooks``,
    and a live private-loop store wired on ``app.state.notebooks_store``."""
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(
        notebooks_module, "_now_iso", lambda: "2026-05-29T00:00:00+00:00"
    )
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        with TestClient(app) as c:
            yield c, base
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _create_notebook(
    client: TestClient, slug: str, *, display_name: str = "", kind: str = "arxiv"
) -> None:
    r = client.post(
        "/ui/api/notebooks",
        json={"slug": slug, "display_name": display_name, "notebook_kind": kind},
    )
    assert r.status_code in (200, 201), r.text


def _seed_asset(base: Path, slug: str, rel: str, body: bytes) -> Path:
    """Place an on-disk asset under ``<base>/<slug>/<rel>``."""
    p = base / slug / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return p


def _open_tar(content: bytes) -> tarfile.TarFile:
    return tarfile.open(fileobj=io.BytesIO(content), mode="r:")


def _read_member(tar: tarfile.TarFile, name: str) -> bytes:
    f = tar.extractfile(name)
    assert f is not None, f"missing member {name!r}"
    return f.read()


class TestExportHappyPath:
    def test_export_streams_tar_with_manifest_and_assets(
        self, exp_client
    ) -> None:
        client, base = exp_client
        _create_notebook(client, "alpha-nb", display_name="Alpha")
        # paper rows (the manifest carries them; on-disk files separately)
        client.post(
            "/ui/api/notebooks/alpha-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2401.00001"},
        )
        # an on-disk asset under <slug>/
        _seed_asset(base, "alpha-nb", "ar5iv/2401.00001.html", b"<html>hi</html>")
        r = client.get("/ui/api/notebooks/alpha-nb/export")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/x-tar"
        assert 'filename="alpha-nb.tar"' in r.headers["content-disposition"]
        assert int(r.headers["content-length"]) == len(r.content)
        with _open_tar(r.content) as tar:
            names = tar.getnames()
            assert "manifest.json" in names
            assert "alpha-nb/ar5iv/2401.00001.html" in names
            manifest = json.loads(_read_member(tar, "manifest.json"))
        assert manifest["format_version"] == 1
        assert manifest["slug"] == "alpha-nb"
        assert manifest["notebook"]["slug"] == "alpha-nb"
        assert manifest["notebook"]["display_name"] == "Alpha"
        assert manifest["notebook"]["notebook_kind"] == "arxiv"
        # m6 D3: allowlist omits the absolute-path + internal-state fields.
        assert "lancedb_path" not in manifest["notebook"]
        assert "parsed_html_path" not in manifest["notebook"]
        assert "parse_error" not in manifest["notebook"]
        # papers are sorted by paper_id (deterministic).
        assert [p["paper_id"] for p in manifest["papers"]] == ["2401.00001"]

    def test_export_with_no_on_disk_dir_returns_manifest_only(
        self, exp_client
    ) -> None:
        """A freshly created notebook with NO on-disk assets exports just the
        manifest — still a valid bundle (no 500)."""
        client, _ = exp_client
        _create_notebook(client, "fresh-nb")
        r = client.get("/ui/api/notebooks/fresh-nb/export")
        assert r.status_code == 200
        with _open_tar(r.content) as tar:
            names = tar.getnames()
        assert names == ["manifest.json"]


class TestExportDeterminism:
    def test_two_exports_byte_identical(self, exp_client) -> None:
        """THE load-bearing AC: two exports of the same notebook + assets
        produce byte-identical tar streams (USTAR + normalized TarInfo + sorted
        member order). If this fails, a TarInfo drift slipped in."""
        client, base = exp_client
        _create_notebook(client, "det-nb", display_name="Det")
        client.post(
            "/ui/api/notebooks/det-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2401.00010"},
        )
        client.post(
            "/ui/api/notebooks/det-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2401.00020"},
        )
        _seed_asset(base, "det-nb", "ar5iv/a.html", b"A")
        _seed_asset(base, "det-nb", "ar5iv/b.html", b"B")
        r1 = client.get("/ui/api/notebooks/det-nb/export")
        r2 = client.get("/ui/api/notebooks/det-nb/export")
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.content == r2.content


class TestNoCrossNotebookLeak:
    def test_manifest_contains_only_requested_slug_rows(
        self, exp_client
    ) -> None:
        client, base = exp_client
        _create_notebook(client, "alpha-nb", display_name="Alpha")
        _create_notebook(client, "beta-nb", display_name="Beta")
        client.post(
            "/ui/api/notebooks/alpha-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2401.00111"},
        )
        client.post(
            "/ui/api/notebooks/beta-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2401.00222"},
        )
        # m6-rect F3: ALSO seed on-disk assets under BOTH notebooks. Without
        # this the original test passed vacuously because no <slug>/... member
        # was ever generated for either; the "no leak" claim was trivial.
        _seed_asset(base, "alpha-nb", "ar5iv/a.html", b"ALPHA-ASSET")
        _seed_asset(base, "beta-nb", "ar5iv/b.html", b"BETA-ASSET")
        r = client.get("/ui/api/notebooks/alpha-nb/export")
        assert r.status_code == 200
        with _open_tar(r.content) as tar:
            names = tar.getnames()
            manifest = json.loads(_read_member(tar, "manifest.json"))
        assert manifest["slug"] == "alpha-nb"
        assert manifest["notebook"]["slug"] == "alpha-nb"
        assert [p["paper_id"] for p in manifest["papers"]] == ["2401.00111"]
        # No beta-nb data in alpha-nb's bundle — the real assertion (no member
        # name starts with beta-nb/) and the alpha-nb members ARE present.
        assert "alpha-nb/ar5iv/a.html" in names
        assert not any(n.startswith("beta-nb/") for n in names)
        body = r.content
        assert b"beta-nb" not in body
        assert b"2401.00222" not in body
        assert b"BETA-ASSET" not in body


class TestErrorCases:
    def test_malformed_slug_422(self, exp_client) -> None:
        client, _ = exp_client
        r = client.get("/ui/api/notebooks/BADSLUG/export")
        assert r.status_code == 422

    def test_unknown_slug_404(self, exp_client) -> None:
        client, _ = exp_client
        r = client.get("/ui/api/notebooks/ghost-nb/export")
        assert r.status_code == 404


class TestPreflightSafety:
    def test_symlink_under_slug_dir_is_skipped_and_warned(
        self, exp_client, caplog
    ) -> None:
        """m6 D5: a symlink under ``<slug>/`` is NOT embedded as a SYMTYPE
        member (would be a zip-slip-class vector for m7); it is skipped + a
        WARNING is emitted for ops review."""
        import logging

        client, base = exp_client
        _create_notebook(client, "sym-nb")
        # a real file the export should include
        _seed_asset(base, "sym-nb", "ar5iv/real.html", b"real")
        # plant a symlink under <slug>/ pointing elsewhere
        target = base / "elsewhere.html"
        target.write_bytes(b"outside")
        (base / "sym-nb" / "ar5iv" / "danger.html").symlink_to(target)
        with caplog.at_level(logging.WARNING, logger="server.routes.notebooks"):
            r = client.get("/ui/api/notebooks/sym-nb/export")
        assert r.status_code == 200
        with _open_tar(r.content) as tar:
            names = tar.getnames()
        assert "sym-nb/ar5iv/real.html" in names
        assert "sym-nb/ar5iv/danger.html" not in names
        assert any(
            "skipping symlink" in rec.message for rec in caplog.records
        )


class TestByteCapExemption:
    def test_export_path_is_exempt_but_other_notebook_paths_are_not(
        self,
    ) -> None:
        """m6 synthesis D1 + m6-rect F2: the BodySizeCap exemption is
        SEGMENT-EXACT — only ``/ui/api/notebooks/<slug>/export`` (exactly 5
        segments after the leading ``/``) is exempt. Every other notebook-API
        path stays under the 256 KB response cap as defense-in-depth."""
        assert _is_exempt_path("/ui/api/notebooks/alpha-nb/export") is True
        assert _is_exempt_path("/ui/api/notebooks/x/export") is True
        # Non-export notebook routes remain CAPPED.
        assert _is_exempt_path("/ui/api/notebooks") is False
        assert _is_exempt_path("/ui/api/notebooks/alpha-nb") is False
        assert _is_exempt_path("/ui/api/notebooks/alpha-nb/papers") is False
        # An unrelated path that ends with /export elsewhere is NOT exempt
        # (the exemption requires BOTH the notebooks prefix AND the suffix).
        assert _is_exempt_path("/ui/api/export") is False

    def test_multi_segment_export_path_not_exempt(self) -> None:
        """m6-rect F2: a hypothetical future multi-segment sub-route ending
        in ``/export`` does NOT inherit the exemption (would have been
        over-exempted by the prior path-suffix check)."""
        # A hypothetical per-paper sub-bundle route.
        assert (
            _is_exempt_path(
                "/ui/api/notebooks/alpha-nb/papers/2401.00001/export"
            )
            is False
        )
        # A deeper sub-route.
        assert (
            _is_exempt_path("/ui/api/notebooks/alpha-nb/sub/export") is False
        )


class TestPreflightAdditional:
    """m6-rect F4: cover the preflight branches the original test surface
    missed — over-long names (the F1 HIGH regression), control chars in
    names, and a slug-level symlink → 422."""

    def test_filename_too_long_for_ustar_is_skipped_not_500(
        self, exp_client, caplog
    ) -> None:
        """m6-rect F1 regression: a 150-char single-segment filename exceeds
        USTAR's 100-char ``name`` field. Pre-rect, the preflight admitted it
        (constant was 255) and ``tar.addfile`` raised ValueError → 500. Post-
        rect, the preflight gates at 100 → skipped + WARN, export returns 200."""
        import logging

        client, base = exp_client
        _create_notebook(client, "long-nb")
        # one normal file that MUST make it in
        _seed_asset(base, "long-nb", "ar5iv/short.html", b"short")
        # one over-long file that MUST be skipped (single segment, no slash
        # for USTAR's name/prefix split to rescue it).
        long_name = "x" * 150 + ".html"
        _seed_asset(base, "long-nb", long_name, b"too long")
        with caplog.at_level(logging.WARNING, logger="server.routes.notebooks"):
            r = client.get("/ui/api/notebooks/long-nb/export")
        assert r.status_code == 200  # NOT 500
        with _open_tar(r.content) as tar:
            names = tar.getnames()
        assert "long-nb/ar5iv/short.html" in names
        assert not any(long_name in n for n in names)
        assert any(
            "USTAR limit" in rec.message or "control chars" in rec.message
            for rec in caplog.records
        )

    def test_filename_with_control_char_is_skipped(
        self, exp_client, caplog
    ) -> None:
        """m6-rect F4: a filename with a control character (e.g. \\x01) is
        skipped + WARN — never embedded as a tar member."""
        import logging

        client, base = exp_client
        _create_notebook(client, "ctrl-nb")
        # Sneak a control byte into the on-disk filename (file system allows
        # most control chars on POSIX; we plant it directly).
        bad = base / "ctrl-nb" / "ar5iv" / "danger\x01.html"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"bad")
        _seed_asset(base, "ctrl-nb", "ar5iv/clean.html", b"clean")
        with caplog.at_level(logging.WARNING, logger="server.routes.notebooks"):
            r = client.get("/ui/api/notebooks/ctrl-nb/export")
        assert r.status_code == 200
        with _open_tar(r.content) as tar:
            names = tar.getnames()
        assert "ctrl-nb/ar5iv/clean.html" in names
        # the control-char file must not be in the tar
        assert not any("\x01" in n for n in names)
        assert any(
            "control chars" in rec.message or "USTAR limit" in rec.message
            for rec in caplog.records
        )

    def test_slug_level_symlink_returns_422(self, exp_client) -> None:
        """m6-rect F4: if ``<base>/<slug>`` is ITSELF a symlink,
        ``notebook_dir(slug)`` raises ``NotebookError`` → 422 (the existing
        Threat-1 path-traversal guard). Previously untested."""
        client, base = exp_client
        # Create the slug row in the DB (so 404-on-unknown doesn't short-circuit).
        _create_notebook(client, "sym-nb")
        # Replace the slug dir with a symlink pointing elsewhere. The store
        # row stays valid; only the on-disk dir is tampered.
        slug_dir = base / "sym-nb"
        # Drop the dir created by _create_notebook (if it exists) and replace
        # with a symlink to a different location.
        import shutil

        if slug_dir.exists():
            shutil.rmtree(slug_dir)
        target = base / "elsewhere"
        target.mkdir(exist_ok=True)
        slug_dir.symlink_to(target)
        r = client.get("/ui/api/notebooks/sym-nb/export")
        assert r.status_code == 422


class TestManifestNullCoercion:
    def test_null_parse_status_serializes_as_empty_string(
        self, exp_client
    ) -> None:
        """m6-rect F5: a notebook row with ``parse_status = NULL`` (legacy
        arxiv notebooks pre-textbook-ingest-m6) serializes as ``""``, not
        ``null`` — the manifest schema is "string, possibly empty"."""
        client, _ = exp_client
        _create_notebook(client, "nullps-nb")
        # The DB column defaults to 'skipped' so the happy path returns a
        # string; the None-coercion behavior is exhaustively unit-tested in
        # ``test_build_manifest_coerces_none_to_empty`` below by passing a
        # synthetic notebook dict directly to the builder.
        r = client.get("/ui/api/notebooks/nullps-nb/export")
        assert r.status_code == 200
        with _open_tar(r.content) as tar:
            manifest = json.loads(_read_member(tar, "manifest.json"))
        # parse_status is always a string in the manifest, never None.
        assert isinstance(manifest["notebook"]["parse_status"], str)

    def test_build_manifest_coerces_none_to_empty(self) -> None:
        """Direct unit test on the helper: ``parse_status: None`` becomes
        ``""`` in the manifest (m6-rect F5)."""
        from server.routes.notebooks import _build_export_manifest

        notebook = {
            "slug": "x-nb", "display_name": "X",
            "notebook_kind": "arxiv", "created_at": "2026-05-29",
            "parse_status": None,
        }
        b = _build_export_manifest(notebook, [], "x-nb")
        m = json.loads(b)
        assert m["notebook"]["parse_status"] == ""
        assert not isinstance(m["notebook"]["parse_status"], type(None))
