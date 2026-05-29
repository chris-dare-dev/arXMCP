"""notebook-surface-expansion-m7 — restore CLI + m6→m7 export→restore round-trip.

Covers ``tools/notebook_restore.py``:

- **Happy-path round-trip** — seed source via the m6 fixture, GET the export tar,
  restore_bundle() into a FRESH (separate) base + db, verify the notebook +
  papers + asset bytes match.
- **Malicious-tar matrix** (m7 D1 Layer 1 pre-pass) — absolute path, `..`
  traversal, SYMTYPE / LNKTYPE / DEVTYPE / FIFOTYPE members, members not under
  the manifest slug — every one rejected with NotebookError; the target dir is
  NEVER created (no partial extraction).
- **Manifest contract** (m7 D3) — format_version mismatch / missing manifest /
  bad slug / slug ≠ member prefix.
- **--force semantics** (m7 D2) — existing DB row without --force rejected;
  with --force succeeds (DB row overwritten); existing ON-DISK dir is rejected
  unconditionally (even with --force).
- **CLI wrapper** — main() exit codes (0 success, 1 failure).
"""

from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import router as notebooks_router
from tools import _notebook_common
from tools.notebook_restore import (
    _RESTORE_SUPPORTED_FORMATS,
    NotebookError,
    main,
    restore_bundle,
)

# ---------------------------------------------------------------------------
# Source fixture (mirrors the m6 test pattern — a server we can export from).
# ---------------------------------------------------------------------------


@pytest.fixture
def source_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path, Path]]:
    """A source server fixture yielding ``(client, source_base, source_db)`` —
    a live notebooks store + REST router from which we can GET an m6 bundle."""
    base = tmp_path / "src-notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(
        notebooks_module, "_now_iso", lambda: "2026-05-29T00:00:00+00:00"
    )
    db_path = tmp_path / "src-notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        with TestClient(app) as c:
            yield c, base, db_path
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _seed_source(client: TestClient, base: Path, slug: str) -> None:
    r = client.post(
        "/ui/api/notebooks",
        json={"slug": slug, "display_name": f"Display-{slug}", "notebook_kind": "arxiv"},
    )
    assert r.status_code in (200, 201), r.text
    r = client.post(
        f"/ui/api/notebooks/{slug}/papers",
        json={"arxiv_url": "https://arxiv.org/abs/2401.00111"},
    )
    assert r.status_code in (200, 201), r.text
    asset = base / slug / "ar5iv" / "2401.00111.html"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"<html>ROUND-TRIP-PAYLOAD</html>")


def _init_target_db(db_path: Path) -> None:
    """Open + close a NotebooksStore on the target DB to provision the schema
    (the same migrations the runtime server applies on startup)."""
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _read_target_rows(db_path: Path, slug: str) -> tuple[dict | None, list[dict]]:
    """Read the notebook row + papers rows directly via sqlite3 (avoids the
    asyncio.Lock-on-foreign-loop hazard for a synchronous test assertion)."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT slug, display_name, lancedb_path, created_at, "
            "notebook_kind, parse_status FROM notebooks WHERE slug = ?",
            (slug,),
        )
        row = cur.fetchone()
        nb = None
        if row:
            nb = {
                "slug": row[0], "display_name": row[1],
                "lancedb_path": row[2], "created_at": row[3],
                "notebook_kind": row[4], "parse_status": row[5],
            }
        cur = conn.execute(
            "SELECT paper_id, added_at FROM notebook_papers WHERE slug = ? "
            "ORDER BY paper_id",
            (slug,),
        )
        papers = [{"paper_id": r[0], "added_at": r[1]} for r in cur.fetchall()]
    finally:
        conn.close()
    return nb, papers


# ---------------------------------------------------------------------------
# Helpers for the malicious-bundle matrix.
# ---------------------------------------------------------------------------


_GOOD_SLUG = "good-nb"
_GOOD_MANIFEST: dict = {
    "format_version": 1,
    "notebook": {
        "slug": _GOOD_SLUG,
        "display_name": "Good",
        "notebook_kind": "arxiv",
        "created_at": "2026-05-29T00:00:00+00:00",
        "parse_status": "skipped",
    },
    "papers": [],
    "slug": _GOOD_SLUG,
}


def _det_tarinfo(name: str, size: int = 0) -> tarfile.TarInfo:
    ti = tarfile.TarInfo(name=name)
    ti.size = size
    ti.mtime = 0
    ti.uid = 0
    ti.gid = 0
    ti.uname = ""
    ti.gname = ""
    ti.mode = 0o644
    ti.type = tarfile.REGTYPE
    return ti


def _write_tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
    with tarfile.open(path, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for ti, data in members:
            if data is None:
                tar.addfile(ti)  # for sym/hardlink/device/FIFO members
            else:
                tar.addfile(ti, io.BytesIO(data))


def _manifest_member(manifest: dict) -> tuple[tarfile.TarInfo, bytes]:
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ti = _det_tarinfo("manifest.json", size=len(body))
    return ti, body


# ---------------------------------------------------------------------------
# Happy-path round-trip.
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_export_restore_round_trip_into_fresh_deployment(
        self, source_env, tmp_path
    ) -> None:
        """THE epic-e3 AC: source notebook + papers + on-disk asset go through
        the export route, then restore_bundle into a SEPARATE fresh base+db, and
        the notebook is fully readable on the target (rows match, asset bytes
        match)."""
        client, src_base, _src_db = source_env
        _seed_source(client, src_base, "round-nb")
        r = client.get("/ui/api/notebooks/round-nb/export")
        assert r.status_code == 200
        bundle = tmp_path / "round-nb.tar"
        bundle.write_bytes(r.content)
        # Fresh deployment (separate base + db).
        tgt_base = tmp_path / "tgt-notebooks"
        tgt_db = tmp_path / "tgt-notebooks.db"
        _init_target_db(tgt_db)
        report = restore_bundle(
            bundle, notebooks_base=tgt_base, db_path=tgt_db, force=False
        )
        assert report.slug == "round-nb"
        assert report.paper_count == 1
        assert report.asset_count >= 1
        # DB rows match expectations.
        nb, papers = _read_target_rows(tgt_db, "round-nb")
        assert nb is not None
        assert nb["slug"] == "round-nb"
        assert nb["display_name"] == "Display-round-nb"
        assert nb["notebook_kind"] == "arxiv"
        # lancedb_path is DERIVED from the target base, NOT the source path.
        assert nb["lancedb_path"] == str(tgt_base / "round-nb" / "lancedb")
        assert "/src-notebooks/" not in nb["lancedb_path"]
        assert [p["paper_id"] for p in papers] == ["2401.00111"]
        # The on-disk asset reproduces byte-for-byte.
        restored = tgt_base / "round-nb" / "ar5iv" / "2401.00111.html"
        assert restored.is_file()
        assert restored.read_bytes() == b"<html>ROUND-TRIP-PAYLOAD</html>"


# ---------------------------------------------------------------------------
# Malicious-bundle matrix (D1 Layer 1 pre-pass).
# ---------------------------------------------------------------------------


class TestMaliciousBundle:
    def _assert_rejected(
        self, bundle: Path, tgt_base: Path, tgt_db: Path
    ) -> NotebookError:
        """Restore must raise NotebookError; the target slug dir must NOT have
        been created (the pre-pass aborts BEFORE any extraction); AND
        (m7-rect F4) the DB must be UNCHANGED (no half-committed transaction)."""
        _init_target_db(tgt_db)
        with pytest.raises(NotebookError) as exc:
            restore_bundle(
                bundle, notebooks_base=tgt_base, db_path=tgt_db, force=False
            )
        assert not (tgt_base / _GOOD_SLUG).exists()
        # m7-rect F4: the DB must not carry a half-committed row.
        conn = sqlite3.connect(str(tgt_db))
        try:
            n_nb = conn.execute(
                "SELECT COUNT(*) FROM notebooks WHERE slug = ?",
                (_GOOD_SLUG,),
            ).fetchone()[0]
            n_papers = conn.execute(
                "SELECT COUNT(*) FROM notebook_papers WHERE slug = ?",
                (_GOOD_SLUG,),
            ).fetchone()[0]
        finally:
            conn.close()
        assert n_nb == 0, (
            f"DB carries {n_nb} notebooks row(s) for {_GOOD_SLUG!r} after "
            f"rejection — restore_bundle leaked a DB write before aborting."
        )
        assert n_papers == 0, (
            f"DB carries {n_papers} paper row(s) for {_GOOD_SLUG!r} after "
            f"rejection."
        )
        return exc.value

    def test_absolute_path_member_rejected(self, tmp_path) -> None:
        bundle = tmp_path / "evil.tar"
        bad = _det_tarinfo("/etc/passwd", size=1)
        _write_tar(bundle, [_manifest_member(_GOOD_MANIFEST), (bad, b"x")])
        err = self._assert_rejected(bundle, tmp_path / "tgt", tmp_path / "tgt.db")
        assert "absolute" in str(err).lower()

    def test_dotdot_traversal_rejected(self, tmp_path) -> None:
        bundle = tmp_path / "evil.tar"
        bad = _det_tarinfo("good-nb/../escape.html", size=1)
        _write_tar(bundle, [_manifest_member(_GOOD_MANIFEST), (bad, b"x")])
        err = self._assert_rejected(bundle, tmp_path / "tgt", tmp_path / "tgt.db")
        assert ".." in str(err) or "traversal" in str(err).lower()

    def test_symlink_member_rejected(self, tmp_path) -> None:
        """m7-rect F5: pin Layer 1's specific 'sym/hardlink' message — so a
        future refactor that weakens ``_safe_member`` doesn't pass silently on
        Layer 2 (PEP 706 ``filter='data'``) alone."""
        bundle = tmp_path / "evil.tar"
        sym = _det_tarinfo("good-nb/sym")
        sym.type = tarfile.SYMTYPE
        sym.linkname = "/etc/passwd"
        sym.size = 0
        _write_tar(bundle, [_manifest_member(_GOOD_MANIFEST), (sym, None)])
        err = self._assert_rejected(bundle, tmp_path / "tgt", tmp_path / "tgt.db")
        assert "sym/hardlink" in str(err).lower()  # Layer 1's message

    def test_hardlink_member_rejected(self, tmp_path) -> None:
        bundle = tmp_path / "evil.tar"
        hl = _det_tarinfo("good-nb/link")
        hl.type = tarfile.LNKTYPE
        hl.linkname = "good-nb/target"
        hl.size = 0
        _write_tar(bundle, [_manifest_member(_GOOD_MANIFEST), (hl, None)])
        err = self._assert_rejected(bundle, tmp_path / "tgt", tmp_path / "tgt.db")
        assert "sym/hardlink" in str(err).lower()  # Layer 1's message

    def test_device_member_rejected(self, tmp_path) -> None:
        bundle = tmp_path / "evil.tar"
        dev = _det_tarinfo("good-nb/dev")
        dev.type = tarfile.CHRTYPE
        dev.size = 0
        _write_tar(bundle, [_manifest_member(_GOOD_MANIFEST), (dev, None)])
        err = self._assert_rejected(bundle, tmp_path / "tgt", tmp_path / "tgt.db")
        assert "device" in str(err).lower() or "fifo" in str(err).lower()

    def test_member_not_under_slug_rejected(self, tmp_path) -> None:
        """A member named under a DIFFERENT slug prefix is rejected (the
        manifest-slug coupling guard)."""
        bundle = tmp_path / "evil.tar"
        bad = _det_tarinfo("other-nb/file.html", size=1)  # not under good-nb/
        _write_tar(bundle, [_manifest_member(_GOOD_MANIFEST), (bad, b"x")])
        err = self._assert_rejected(bundle, tmp_path / "tgt", tmp_path / "tgt.db")
        assert "good-nb" in str(err) or "prefix" in str(err).lower()


# ---------------------------------------------------------------------------
# Manifest contract (D3).
# ---------------------------------------------------------------------------


class TestManifestContract:
    def test_format_version_mismatch_rejected(self, tmp_path) -> None:
        bad_manifest = dict(_GOOD_MANIFEST, format_version=99)
        bundle = tmp_path / "v99.tar"
        _write_tar(bundle, [_manifest_member(bad_manifest)])
        _init_target_db(tmp_path / "tgt.db")
        with pytest.raises(NotebookError) as exc:
            restore_bundle(
                bundle,
                notebooks_base=tmp_path / "tgt",
                db_path=tmp_path / "tgt.db",
            )
        assert "format_version" in str(exc.value)
        assert str(_RESTORE_SUPPORTED_FORMATS) in str(exc.value)

    def test_missing_manifest_rejected(self, tmp_path) -> None:
        bundle = tmp_path / "no-manifest.tar"
        only = _det_tarinfo("good-nb/file.html", size=1)
        _write_tar(bundle, [(only, b"x")])
        _init_target_db(tmp_path / "tgt.db")
        with pytest.raises(NotebookError) as exc:
            restore_bundle(
                bundle,
                notebooks_base=tmp_path / "tgt",
                db_path=tmp_path / "tgt.db",
            )
        assert "manifest" in str(exc.value).lower()

    def test_bad_slug_in_manifest_rejected(self, tmp_path) -> None:
        bad_manifest = dict(
            _GOOD_MANIFEST,
            slug="BADSLUG",
            notebook=dict(_GOOD_MANIFEST["notebook"], slug="BADSLUG"),
        )
        bundle = tmp_path / "bad-slug.tar"
        _write_tar(bundle, [_manifest_member(bad_manifest)])
        _init_target_db(tmp_path / "tgt.db")
        with pytest.raises(NotebookError) as exc:
            restore_bundle(
                bundle,
                notebooks_base=tmp_path / "tgt",
                db_path=tmp_path / "tgt.db",
            )
        assert "slug" in str(exc.value).lower()

    def test_symtype_manifest_json_rejected(self, tmp_path) -> None:
        """m7-rect F3: a SYMTYPE ``manifest.json`` member is rejected by
        ``_read_manifest``'s early guard BEFORE ``tar.extractfile`` is called
        (which would silently follow the intra-archive symlink and parse an
        attacker-chosen JSON body). Defense-in-depth for the ordering smell:
        ``_safe_member`` runs LATER, so the early guard is what closes this
        class on the consumer side."""
        bundle = tmp_path / "evil.tar"
        sym = _det_tarinfo("manifest.json")
        sym.type = tarfile.SYMTYPE
        sym.linkname = "other.json"
        sym.size = 0
        _write_tar(bundle, [(sym, None)])
        tgt_db = tmp_path / "tgt.db"
        _init_target_db(tgt_db)
        with pytest.raises(NotebookError) as exc:
            restore_bundle(
                bundle,
                notebooks_base=tmp_path / "tgt",
                db_path=tgt_db,
            )
        assert "manifest" in str(exc.value).lower()
        assert "sym/hardlink" in str(exc.value).lower()

    def test_manifest_top_slug_disagrees_with_notebook_slug(self, tmp_path) -> None:
        bad_manifest = dict(
            _GOOD_MANIFEST,
            notebook=dict(_GOOD_MANIFEST["notebook"], slug="other-nb"),
        )
        bundle = tmp_path / "mismatch.tar"
        _write_tar(bundle, [_manifest_member(bad_manifest)])
        _init_target_db(tmp_path / "tgt.db")
        with pytest.raises(NotebookError) as exc:
            restore_bundle(
                bundle,
                notebooks_base=tmp_path / "tgt",
                db_path=tmp_path / "tgt.db",
            )
        assert "notebook.slug" in str(exc.value)


# ---------------------------------------------------------------------------
# --force semantics (D2).
# ---------------------------------------------------------------------------


class TestForceSemantics:
    def _build_minimal_bundle(self, tmp_path: Path) -> Path:
        bundle = tmp_path / "ok.tar"
        _write_tar(bundle, [_manifest_member(_GOOD_MANIFEST)])
        return bundle

    def test_existing_db_row_without_force_rejected(self, tmp_path) -> None:
        """The minimal bundle has no <slug>/ members, so the first restore
        creates the DB row but NO on-disk slug dir. A second restore without
        --force is then rejected by the DB-row guard (not the on-disk guard)."""
        bundle = self._build_minimal_bundle(tmp_path)
        tgt_base = tmp_path / "tgt"
        tgt_db = tmp_path / "tgt.db"
        _init_target_db(tgt_db)
        restore_bundle(
            bundle, notebooks_base=tgt_base, db_path=tgt_db, force=False
        )
        # No <slug>/ members → no slug dir on disk; the DB guard fires cleanly.
        assert not (tgt_base / _GOOD_SLUG).exists()
        with pytest.raises(NotebookError) as exc:
            restore_bundle(
                bundle, notebooks_base=tgt_base, db_path=tgt_db, force=False
            )
        assert "already exists in DB" in str(exc.value)
        assert "--force" in str(exc.value)

    def test_existing_db_row_with_force_overwrites(self, tmp_path, capsys) -> None:
        bundle = self._build_minimal_bundle(tmp_path)
        tgt_base = tmp_path / "tgt"
        tgt_db = tmp_path / "tgt.db"
        _init_target_db(tgt_db)
        restore_bundle(
            bundle, notebooks_base=tgt_base, db_path=tgt_db, force=False
        )
        capsys.readouterr()  # discard any output from the first restore
        # With --force, the DB row is replaced (DELETE + INSERT cascades).
        report = restore_bundle(
            bundle, notebooks_base=tgt_base, db_path=tgt_db, force=True
        )
        assert report.forced is True
        nb, _ = _read_target_rows(tgt_db, _GOOD_SLUG)
        assert nb is not None
        # m7-rect F2: --force MUST emit a stderr WARN before the DELETE
        # (precedent: tools/notebook_purge.py — "--force does NOT silence
        # the warning"). The line names the slug + paper count.
        err = capsys.readouterr().err
        assert "WARN" in err
        assert "--force" in err
        assert _GOOD_SLUG in err
        assert "paper(s)" in err

    def test_force_warning_lists_pre_existing_paper_count(
        self, tmp_path, capsys
    ) -> None:
        """m7-rect F2 regression guard: the WARN line correctly enumerates
        the count of papers that the cascade is about to destroy. Seed two
        papers into the existing slug via the source server, then
        --force-restore an EMPTY-papers bundle and assert ``2 paper(s)`` in
        the WARN."""
        bundle = self._build_minimal_bundle(tmp_path)
        tgt_base = tmp_path / "tgt"
        tgt_db = tmp_path / "tgt.db"
        _init_target_db(tgt_db)
        # First restore (no force): inserts the row with 0 papers.
        restore_bundle(
            bundle, notebooks_base=tgt_base, db_path=tgt_db, force=False
        )
        # Add two papers directly to the target DB before --force-restore.
        conn = sqlite3.connect(str(tgt_db))
        try:
            conn.executemany(
                "INSERT INTO notebook_papers (slug, paper_id, added_at) "
                "VALUES (?, ?, ?)",
                [
                    (_GOOD_SLUG, "2401.00001", "2026-05-29T00:00:00+00:00"),
                    (_GOOD_SLUG, "2401.00002", "2026-05-29T00:00:00+00:00"),
                ],
            )
            conn.commit()
        finally:
            conn.close()
        capsys.readouterr()
        restore_bundle(
            bundle, notebooks_base=tgt_base, db_path=tgt_db, force=True
        )
        err = capsys.readouterr().err
        assert "2 paper(s)" in err

    def test_existing_on_disk_dir_rejected_even_with_force(self, tmp_path) -> None:
        """m7 D2: on-disk clobber is REFUSED unconditionally. --force is for
        the DB row only."""
        bundle = self._build_minimal_bundle(tmp_path)
        tgt_base = tmp_path / "tgt"
        (tgt_base / _GOOD_SLUG).mkdir(parents=True)
        (tgt_base / _GOOD_SLUG / "stowaway.html").write_bytes(b"keep me")
        tgt_db = tmp_path / "tgt.db"
        _init_target_db(tgt_db)
        with pytest.raises(NotebookError) as exc:
            restore_bundle(
                bundle, notebooks_base=tgt_base, db_path=tgt_db, force=True
            )
        assert "already exists" in str(exc.value)
        assert "notebook_purge" in str(exc.value)
        # The pre-existing file must NOT have been touched.
        assert (tgt_base / _GOOD_SLUG / "stowaway.html").read_bytes() == b"keep me"


# ---------------------------------------------------------------------------
# CLI wrapper smoke.
# ---------------------------------------------------------------------------


class TestCLI:
    def test_main_success_exit_code(self, tmp_path, capsys) -> None:
        bundle = tmp_path / "ok.tar"
        _write_tar(bundle, [_manifest_member(_GOOD_MANIFEST)])
        tgt_base = tmp_path / "tgt"
        tgt_db = tmp_path / "tgt.db"
        _init_target_db(tgt_db)
        rc = main([
            str(bundle),
            "--notebooks-base", str(tgt_base),
            "--db", str(tgt_db),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "restored" in out
        assert _GOOD_SLUG in out

    def test_main_force_flag_plumbed_through(self, tmp_path, capsys) -> None:
        """m7-rect F6: assert the argparse ``--force`` flag actually plumbs to
        ``restore_bundle(force=True)`` end-to-end — closes the wiring gap (a
        future typo like ``force=args.foce`` would slip past the Python-level
        tests that call ``restore_bundle()`` directly)."""
        bundle = tmp_path / "ok.tar"
        _write_tar(bundle, [_manifest_member(_GOOD_MANIFEST)])
        tgt_base = tmp_path / "tgt"
        tgt_db = tmp_path / "tgt.db"
        _init_target_db(tgt_db)
        # First restore without --force.
        rc1 = main([
            str(bundle),
            "--notebooks-base", str(tgt_base),
            "--db", str(tgt_db),
        ])
        assert rc1 == 0
        capsys.readouterr()  # discard first-pass output
        # Second restore needs --force — wired through argparse.
        rc2 = main([
            str(bundle),
            "--notebooks-base", str(tgt_base),
            "--db", str(tgt_db),
            "--force",
        ])
        assert rc2 == 0
        captured = capsys.readouterr()
        # The F2 stderr WARN confirms --force reached _restore_db_rows.
        assert "WARN" in captured.err
        assert "--force" in captured.err
        # The success print on stdout carries the "--force; DB row overwritten" tag.
        assert "--force" in captured.out

    def test_main_failure_exit_code(self, tmp_path, capsys) -> None:
        bundle = tmp_path / "missing-manifest.tar"
        only = _det_tarinfo("good-nb/file.html", size=1)
        _write_tar(bundle, [(only, b"x")])
        tgt_db = tmp_path / "tgt.db"
        _init_target_db(tgt_db)
        rc = main([
            str(bundle),
            "--notebooks-base", str(tmp_path / "tgt"),
            "--db", str(tgt_db),
        ])
        assert rc == 1
        err = capsys.readouterr().err
        assert "error" in err.lower()
        assert "manifest" in err.lower()
