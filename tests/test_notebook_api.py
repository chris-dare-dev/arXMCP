"""Tests for the /ui/api/notebooks REST surface (m7).

Coverage matrix:

- TestNotebookCrud                 — AC #1, AC #3 (create, list, delete, idempotency)
- TestSlugValidation               — FM-2 (path-traversal regex defense)
- TestPaperAdd                     — AC #2 (arxiv URL normalization + validation)
- TestPaperListAndRemove           — junction list/single-row delete
- TestArxivUrlNormalizer           — direct unit tests of _arxiv_url_to_paper_id
- TestForeignKeyCascade            — FM-7 (ON DELETE CASCADE for notebook_papers)
- TestPostAfterDelete              — AC #3 belt-and-braces (re-create after delete)
- TestNotebooksStorePersistence    — Tier1Store-pattern parity (close + reopen)

Approach: build a minimal FastAPI app with just the notebooks router
+ a real NotebooksStore against a tmp_path SQLite. Avoids the full
``create_app`` lifespan (which loads BGE-M3 + LanceDB and is too heavy
for unit tests). Mirrors how ``tests/tools/test_validate_notebook_fixtures.py``
keeps its surface tight.
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
    _arxiv_url_to_paper_id,
)
from server.routes.notebooks import (
    router as notebooks_router,
)
from tools import _notebook_common

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect NOTEBOOKS_BASE so create_notebook writes inside tmp_path."""
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
    """Build a minimal FastAPI app + real NotebooksStore on tmp_path.

    Uses a per-fixture event loop because the project's convention
    is ``asyncio.run()`` per call site rather than pytest-asyncio.
    A prior test in the suite may have run + closed its own loop,
    so ``asyncio.get_event_loop()`` raises ``RuntimeError`` here on
    Python 3.12. ``asyncio.new_event_loop()`` + explicit close on
    teardown is the project's own pattern.
    """
    import asyncio
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        # Deterministic timestamp for test assertion stability.
        monkeypatch.setattr(
            notebooks_module, "_now_iso",
            lambda: "2026-05-22T03:00:00+00:00",
        )
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Notebook CRUD (AC #1, AC #3)
# ---------------------------------------------------------------------------


class TestNotebookCrud:
    def test_initial_list_is_empty(self, client: TestClient) -> None:
        r = client.get("/ui/api/notebooks")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_notebook(self, client: TestClient) -> None:
        r = client.post(
            "/ui/api/notebooks",
            json={"slug": "demo-nb", "display_name": "Demo notebook"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["slug"] == "demo-nb"
        assert body["display_name"] == "Demo notebook"
        assert "lancedb_path" in body
        assert body["lancedb_path"].endswith("demo-nb/lancedb")

    def test_create_then_list_returns_row(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.get("/ui/api/notebooks")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["slug"] == "demo-nb"
        assert rows[0]["display_name"] == ""  # default
        assert rows[0]["created_at"] == "2026-05-22T03:00:00+00:00"

    def test_duplicate_slug_returns_409(self, client: TestClient) -> None:
        """AC #1: idempotent on duplicate slug — HTTP 409."""
        r1 = client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        assert r1.status_code == 201
        r2 = client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        assert r2.status_code == 409
        assert "already exists" in r2.json()["detail"]

    def test_create_makes_on_disk_directory(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        assert (notebooks_base / "demo-nb").is_dir()

    def test_delete_removes_row(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.delete("/ui/api/notebooks/demo-nb")
        assert r.status_code == 204
        r2 = client.get("/ui/api/notebooks")
        assert r2.json() == []

    def test_delete_metadata_only_leaves_dir(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """AC #3: DELETE is metadata-only; on-disk dir survives."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        nb_dir = notebooks_base / "demo-nb"
        assert nb_dir.is_dir()
        client.delete("/ui/api/notebooks/demo-nb")
        assert nb_dir.is_dir(), (
            "DELETE /ui/api/notebooks/<slug> must be metadata-only — "
            "the on-disk directory MUST survive (m7 brief deletion "
            "semantics; on-disk wipe is tools/notebook_purge.py's job)"
        )

    def test_delete_nonexistent_returns_404(
        self, client: TestClient,
    ) -> None:
        r = client.delete("/ui/api/notebooks/nope")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Slug validation (FM-2)
# ---------------------------------------------------------------------------


class TestSlugValidation:
    @pytest.mark.parametrize(
        "bad_slug",
        [
            "../etc/passwd",   # path traversal
            "/absolute",       # leading slash
            "UPPER",           # uppercase
            "with space",      # space
            "with$shell",      # shell metachar
            "ab",              # too short (regex requires 3+)
            "a" * 32,          # too long (regex caps at 31)
            "-leading-hyphen", # leading hyphen
        ],
    )
    def test_create_rejects_bad_slug(
        self, client: TestClient, bad_slug: str,
    ) -> None:
        # Bypass pydantic's min_length check by using the longest cases;
        # for the ones that don't, the SLUG_RE check is what we want.
        r = client.post(
            "/ui/api/notebooks", json={"slug": bad_slug},
        )
        # Either 422 (pydantic field validation) or 422 (slug regex).
        assert r.status_code == 422, (
            f"slug={bad_slug!r} should have been rejected; got "
            f"{r.status_code}: {r.text}"
        )

    def test_delete_rejects_bad_slug(self, client: TestClient) -> None:
        r = client.delete("/ui/api/notebooks/../etc/passwd")
        # The path collapses at the HTTP layer; we expect 404 (no
        # such route) OR 422. Either way, NOT a 200 / 204.
        assert r.status_code in (404, 422), r.text


# ---------------------------------------------------------------------------
# Paper add (AC #2)
# ---------------------------------------------------------------------------


class TestPaperAdd:
    def test_add_paper_happy_path(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.26204"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body == {"slug": "demo-nb", "paper_id": "2604.26204"}

    def test_add_paper_to_missing_notebook_returns_404(
        self, client: TestClient,
    ) -> None:
        r = client.post(
            "/ui/api/notebooks/nope/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.26204"},
        )
        assert r.status_code == 404

    def test_add_paper_with_malformed_url_returns_422(
        self, client: TestClient,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://example.com/not-arxiv"},
        )
        assert r.status_code == 422

    def test_add_duplicate_paper_returns_409(
        self, client: TestClient,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        url = "https://arxiv.org/abs/2604.26204"
        r1 = client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": url},
        )
        assert r1.status_code == 201
        r2 = client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": url},
        )
        assert r2.status_code == 409

    def test_add_paper_with_version_suffix(
        self, client: TestClient,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.26204v3"},
        )
        assert r.status_code == 201
        assert r.json()["paper_id"] == "2604.26204v3"

    def test_add_paper_old_style_id(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/hep-th/0001234"},
        )
        assert r.status_code == 201
        assert r.json()["paper_id"] == "hep-th/0001234"


# ---------------------------------------------------------------------------
# Paper list + single-row delete
# ---------------------------------------------------------------------------


class TestPaperListAndRemove:
    def test_list_papers_empty_notebook(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.get("/ui/api/notebooks/demo-nb/papers")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_papers_missing_notebook_returns_404(
        self, client: TestClient,
    ) -> None:
        r = client.get("/ui/api/notebooks/nope/papers")
        assert r.status_code == 404

    def test_list_papers_after_add(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.26204"},
        )
        r = client.get("/ui/api/notebooks/demo-nb/papers")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["paper_id"] == "2604.26204"

    def test_remove_paper(self, client: TestClient) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.26204"},
        )
        r = client.delete(
            "/ui/api/notebooks/demo-nb/papers/2604.26204",
        )
        assert r.status_code == 204
        r2 = client.get("/ui/api/notebooks/demo-nb/papers")
        assert r2.json() == []

    def test_remove_old_style_paper_id(
        self, client: TestClient,
    ) -> None:
        """Path syntax {paper_id:path} accepts embedded slashes."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/hep-th/0001234"},
        )
        r = client.delete(
            "/ui/api/notebooks/demo-nb/papers/hep-th/0001234",
        )
        assert r.status_code == 204

    def test_remove_nonexistent_paper_returns_404(
        self, client: TestClient,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.delete(
            "/ui/api/notebooks/demo-nb/papers/9999.99999",
        )
        assert r.status_code == 404

    def test_remove_paper_invalid_id_returns_422(
        self, client: TestClient,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.delete(
            "/ui/api/notebooks/demo-nb/papers/not-a-paper-id",
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# _arxiv_url_to_paper_id direct unit tests (FM-4)
# ---------------------------------------------------------------------------


class TestArxivUrlNormalizer:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://arxiv.org/abs/2604.26204", "2604.26204"),
            ("http://arxiv.org/abs/2604.26204", "2604.26204"),
            ("https://arxiv.org/abs/2604.26204v3", "2604.26204v3"),
            ("https://arxiv.org/abs/hep-th/0001234", "hep-th/0001234"),
            ("https://arxiv.org/abs/2604.26204/", "2604.26204"),  # trailing /
        ],
    )
    def test_accepted_forms(
        self, url: str, expected: str,
    ) -> None:
        assert _arxiv_url_to_paper_id(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "",                                                # empty
            "https://example.com/abs/2604.26204",              # wrong host
            "https://www.arxiv.org/abs/2604.26204",            # www subdomain
            "https://arxiv.org/pdf/2604.26204.pdf",            # pdf path
            # NOTE: m8 (proof-verify-handler-wiring-m8) extended the
            # normalizer to ALSO accept ar5iv URLs. The m7-era reject
            # case for `https://ar5iv.labs.arxiv.org/html/<id>` is
            # now a happy-path case — covered by
            # tests/test_ui_html_pages.py::TestAr5ivUrlNormalizer.
            "https://ar5iv.labs.arxiv.org/abs/2604.26204",     # wrong prefix for ar5iv host
            "https://arxiv.org/html/2604.26204",               # wrong prefix for arxiv host
            "https://arxiv.org/abs/NOT-A-PAPER-ID",            # invalid id
            "https://arxiv.org/abs/2604.26204X",               # extra suffix
            "ftp://arxiv.org/abs/2604.26204",                  # wrong scheme
            "https://arxiv.org/",                              # no /abs/ prefix
            "https://arxiv.org/abs/",                          # empty paper_id
            "not-a-url",                                       # not a URL
        ],
    )
    def test_rejected_forms(self, url: str) -> None:
        assert _arxiv_url_to_paper_id(url) is None

    def test_non_string_input_returns_none(self) -> None:
        assert _arxiv_url_to_paper_id(None) is None  # type: ignore[arg-type]
        assert _arxiv_url_to_paper_id(123) is None  # type: ignore[arg-type]

    def test_trailing_newline_in_url_is_stripped_by_urlparse(
        self,
    ) -> None:
        """Python's ``urllib.parse.urlparse`` strips ASCII control
        characters (newline / CR / tab) from URLs before parsing,
        so ``https://arxiv.org/abs/2604.26204\\n`` resolves to the
        clean ``2604.26204``. The m1-rect-F3 ``\\Z``-anchor hardening
        on ``is_valid_paper_id`` still protects against trailing-
        newline attacks on the RAW paper_id (e.g. if someone called
        ``add_paper(slug, paper_id, ...)`` directly bypassing the
        URL layer), but at the URL layer the newline is already
        neutralized.

        This test pins the observation so a future ``urllib`` change
        that ALTERS this behavior (e.g. preserves the newline in
        the path component) would surface here, prompting an
        explicit ``str.strip()`` in the normalizer."""
        from ingest.identifiers import is_valid_paper_id

        result = _arxiv_url_to_paper_id(
            "https://arxiv.org/abs/2604.26204\n"
        )
        # urlparse stripped the newline before the normalizer saw it.
        assert result == "2604.26204"

        # Defense-in-depth: a raw paper_id with a trailing newline
        # IS rejected by the upstream validator.
        assert is_valid_paper_id("2604.26204\n") is False


# ---------------------------------------------------------------------------
# Foreign key cascade (FM-7)
# ---------------------------------------------------------------------------


class TestForeignKeyCascade:
    def test_delete_notebook_cascades_papers(
        self, client: TestClient,
    ) -> None:
        """FM-7: DELETE FROM notebooks WHERE slug=X cascades to
        notebook_papers via ON DELETE CASCADE + PRAGMA foreign_keys=ON."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.26204"},
        )
        client.post(
            "/ui/api/notebooks/demo-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/0712.1083"},
        )
        # Sanity: papers are there
        r = client.get("/ui/api/notebooks/demo-nb/papers")
        assert len(r.json()) == 2

        # Delete the notebook → cascade should drop the papers
        client.delete("/ui/api/notebooks/demo-nb")

        # Recreate the notebook (now empty)
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.get("/ui/api/notebooks/demo-nb/papers")
        assert r.status_code == 200
        assert r.json() == [], (
            "FK ON DELETE CASCADE did not fire — junction rows survived "
            "the parent notebook deletion. Check PRAGMA foreign_keys=ON."
        )


# ---------------------------------------------------------------------------
# AC #3 belt-and-braces
# ---------------------------------------------------------------------------


class TestPostAfterDelete:
    def test_can_recreate_slug_after_delete(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """AC #3: subsequent POST with the same slug succeeds even
        though the on-disk dir survived the previous DELETE."""
        r1 = client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        assert r1.status_code == 201
        client.delete("/ui/api/notebooks/demo-nb")
        # On-disk dir survives
        assert (notebooks_base / "demo-nb").is_dir()
        # POST again must succeed (FM-9: mkdir(exist_ok=True))
        r2 = client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        assert r2.status_code == 201, r2.text


# ---------------------------------------------------------------------------
# m7 rect F3 — mkdir-failure rollback
# ---------------------------------------------------------------------------


class TestMkdirFailureRollback:
    """m7 rect F3: if ``Path.mkdir`` raises after the SQLite INSERT
    has committed, the row must be rolled back so a retry isn't
    stuck on a permanent 409 ("already exists") despite the on-disk
    side being broken."""

    def test_mkdir_failure_rolls_back_sqlite_row(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from pathlib import Path as _Path
        original_mkdir = _Path.mkdir

        call_count = {"n": 0}

        def _failing_mkdir(self, *args, **kwargs):
            # Only fail on the per-notebook directory create —
            # let the test harness's earlier tmp_path mkdir
            # (notebooks_base fixture) succeed.
            if self.name == "demo-nb":
                call_count["n"] += 1
                raise OSError("simulated disk-full")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(_Path, "mkdir", _failing_mkdir)

        r = client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        assert r.status_code == 500, r.text
        assert "mkdir failed" in r.json()["detail"]
        assert call_count["n"] == 1

        # Crucially: the SQLite row was rolled back. A subsequent
        # GET must show an empty list (NOT a leftover row).
        monkeypatch.undo()
        r2 = client.get("/ui/api/notebooks")
        assert r2.status_code == 200
        assert r2.json() == [], (
            "F3 rollback did not fire — SQLite row survived a "
            "mkdir failure. A retry would now get 409 forever."
        )

        # And a fresh POST must succeed (proving retry-after-fix
        # actually works).
        r3 = client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        assert r3.status_code == 201, r3.text


# ---------------------------------------------------------------------------
# NotebooksStore persistence (Tier1Store parity)
# ---------------------------------------------------------------------------


class TestNotebooksStorePersistence:
    """Verifies the open/close pattern survives a process restart
    (i.e., data persists in SQLite, not in-memory only)."""

    def test_data_survives_reopen(self, tmp_path: Path) -> None:
        import asyncio
        db_path = tmp_path / "notebooks.db"

        async def _run() -> list[dict[str, str]]:
            s1 = await NotebooksStore.open(db_path)
            await s1.create_notebook(
                slug="demo-nb",
                display_name="Demo",
                lancedb_path="/tmp/x",
                created_at="2026-05-22T00:00:00+00:00",
            )
            await s1.close()

            s2 = await NotebooksStore.open(db_path)
            rows = await s2.list_notebooks()
            await s2.close()
            return rows

        rows = asyncio.run(_run())
        assert len(rows) == 1
        assert rows[0]["slug"] == "demo-nb"

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        import asyncio
        db_path = tmp_path / "notebooks.db"

        async def _run() -> None:
            s = await NotebooksStore.open(db_path)
            await s.close()
            await s.close()  # second close must not raise

        asyncio.run(_run())


# ===========================================================================
# textbook-ingest-m3 — notebook_kind field tests
# ===========================================================================


class TestNotebookKind:
    """m3 — ``notebook_kind`` field on the m6 notebook schema.

    Acceptance: notebook created with ``notebook_kind="textbook"`` round-
    trips through SQLite; arXiv-flavor notebooks default to
    ``"arxiv"``. Pydantic pattern validation rejects garbage.
    """

    def test_default_notebook_kind_is_arxiv(
        self, client: TestClient,
    ) -> None:
        """Create without supplying notebook_kind → default ``arxiv``."""
        r = client.post(
            "/ui/api/notebooks",
            json={"slug": "demo-nb", "display_name": "demo"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["notebook_kind"] == "arxiv"

        # And the persisted row matches.
        rows = client.get("/ui/api/notebooks").json()
        assert rows[0]["notebook_kind"] == "arxiv"

    def test_textbook_kind_round_trip(
        self, client: TestClient,
    ) -> None:
        """Create with notebook_kind=textbook → persisted, surfaced."""
        r = client.post(
            "/ui/api/notebooks",
            json={
                "slug": "shimura-varieties",
                "display_name": "Shimura varieties",
                "notebook_kind": "textbook",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["notebook_kind"] == "textbook"

        rows = client.get("/ui/api/notebooks").json()
        assert len(rows) == 1
        assert rows[0]["notebook_kind"] == "textbook"

    def test_invalid_notebook_kind_rejected(
        self, client: TestClient,
    ) -> None:
        """Pydantic pattern rejects anything outside the enum domain."""
        r = client.post(
            "/ui/api/notebooks",
            json={
                "slug": "demo-nb",
                "notebook_kind": "freeform-garbage",
            },
        )
        # FastAPI/Pydantic returns 422 on pattern validation failure.
        assert r.status_code == 422, r.text

    def test_each_valid_kind_accepted(
        self, client: TestClient,
    ) -> None:
        """Both members of the enum must be accepted."""
        for i, kind in enumerate(["arxiv", "textbook"]):
            r = client.post(
                "/ui/api/notebooks",
                json={
                    "slug": f"notebook-{i}",
                    "notebook_kind": kind,
                },
            )
            assert r.status_code == 201, r.text
            assert r.json()["notebook_kind"] == kind


class TestParseStatusInitialState:
    """textbook-ingest-m6 — initial parse_status semantics on create.

    arxiv-kind notebooks inherit the column-level SQLite DEFAULT
    ('skipped'). textbook-kind notebooks land with the route-handler
    override 'pending' so the upload route's parse-task scheduler
    observes the right initial state.
    """

    def test_arxiv_kind_lands_skipped(
        self, client: TestClient,
    ) -> None:
        client.post(
            "/ui/api/notebooks",
            json={"slug": "demo-nb", "notebook_kind": "arxiv"},
        )
        r = client.get("/ui/api/notebooks/demo-nb/parse-status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["notebook_kind"] == "arxiv"
        assert body["parse_status"] == "skipped"
        assert body["parse_error"] == ""
        assert body["parsed_html_path"] == ""

    def test_textbook_kind_lands_pending(
        self, client: TestClient,
    ) -> None:
        client.post(
            "/ui/api/notebooks",
            json={"slug": "sv-textbook", "notebook_kind": "textbook"},
        )
        r = client.get("/ui/api/notebooks/sv-textbook/parse-status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["notebook_kind"] == "textbook"
        assert body["parse_status"] == "pending"
        assert body["parse_error"] == ""
        assert body["parsed_html_path"] == ""


class TestParseStatusRoute:
    """textbook-ingest-m6 — GET /parse-status endpoint coverage."""

    def test_unknown_slug_404(self, client: TestClient) -> None:
        r = client.get("/ui/api/notebooks/no-such-slug/parse-status")
        assert r.status_code == 404, r.text
        assert "not found" in r.json()["detail"]

    @pytest.mark.parametrize(
        "bad_slug",
        ["UPPER", "with space", "with.dot", "ends-", "-starts"],
    )
    def test_malformed_slug_422(
        self, client: TestClient, bad_slug: str,
    ) -> None:
        r = client.get(f"/ui/api/notebooks/{bad_slug}/parse-status")
        assert r.status_code in (404, 422), r.text  # 404 if FastAPI
        # routed missing-resource first; 422 if the validate_slug
        # check fired. Either is acceptable; the key contract is
        # NOT 200 for an invalid slug.

    def test_response_shape_minimal(self, client: TestClient) -> None:
        """Verify the JSON keys we promise in the parse-status contract."""
        client.post(
            "/ui/api/notebooks",
            json={"slug": "test-nb", "notebook_kind": "textbook"},
        )
        r = client.get("/ui/api/notebooks/test-nb/parse-status")
        assert r.status_code == 200
        body = r.json()
        # The five documented fields are present.
        assert set(body.keys()) == {
            "slug", "notebook_kind",
            "parse_status", "parse_error", "parsed_html_path",
        }


#: Minimal valid-enough PDF body that passes the m4 pre-flight gate:
#: magic bytes %PDF-, no polyglot tail, no JS tokens, 0 declared pages.
_MINIMAL_PDF = b"%PDF-1.4\nminimal test pdf body for m6 upload tests\n%%EOF\n"


class TestTextbookUploadSchedulesParse:
    """textbook-ingest-m6 F2 — the upload→schedule path.

    The default ``client`` fixture never sets ``app.state.parse_tracker``;
    this class builds its own client with a mock tracker so the
    route's parse-dispatch branch is actually exercised (F2 gap).
    """

    def _client_with_tracker(
        self, tmp_path: Path, notebooks_base: Path,
        monkeypatch: pytest.MonkeyPatch, tracker: object | None,
    ) -> Iterator[TestClient]:
        import asyncio
        from unittest.mock import MagicMock

        db_path = tmp_path / "notebooks.db"
        loop = asyncio.new_event_loop()
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        if tracker is not None:
            app.state.parse_tracker = tracker
        app.include_router(notebooks_router, prefix="/ui/api")
        monkeypatch.setattr(
            notebooks_module, "_now_iso",
            lambda: "2026-05-28T03:00:00+00:00",
        )
        client = TestClient(app)
        client._arxmcp_loop = loop  # type: ignore[attr-defined]
        client._arxmcp_store = store  # type: ignore[attr-defined]
        _ = MagicMock  # keep import referenced for readers
        return client

    def test_upload_schedules_parse_and_flips_running(
        self, tmp_path: Path, notebooks_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import MagicMock

        tracker = MagicMock()
        tracker.is_running.return_value = False
        client = self._client_with_tracker(
            tmp_path, notebooks_base, monkeypatch, tracker,
        )
        try:
            with client:
                client.post(
                    "/ui/api/notebooks",
                    json={"slug": "sv-book", "notebook_kind": "textbook"},
                )
                r = client.post(
                    "/ui/api/notebooks/sv-book/papers/upload",
                    data={"paper_id": "textbook:sv-book"},
                    files={"file": ("book.pdf", _MINIMAL_PDF, "application/pdf")},
                )
                assert r.status_code == 201, r.text
                # The tracker was asked to schedule exactly one parse.
                tracker.start_parse.assert_called_once()
                _, kwargs = tracker.start_parse.call_args
                assert kwargs["slug"] == "sv-book"
                assert kwargs["paper_id"] == "textbook:sv-book"
                assert kwargs["output_dir"].name == "_mineru"
                assert kwargs["parsed_dir"].name == "parsed"
                # parse_status flipped pending → running.
                status_r = client.get("/ui/api/notebooks/sv-book/parse-status")
                assert status_r.json()["parse_status"] == "running"
        finally:
            client._arxmcp_loop.run_until_complete(  # type: ignore[attr-defined]
                client._arxmcp_store.close()  # type: ignore[attr-defined]
            )
            client._arxmcp_loop.close()  # type: ignore[attr-defined]

    def test_parse_tracker_absent_keeps_pending(
        self, tmp_path: Path, notebooks_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """F2 second branch: parse_tracker is None → 201, PDF on disk,
        parse_status stays 'pending' (degraded but non-fatal)."""
        client = self._client_with_tracker(
            tmp_path, notebooks_base, monkeypatch, tracker=None,
        )
        try:
            with client:
                client.post(
                    "/ui/api/notebooks",
                    json={"slug": "sv2-book", "notebook_kind": "textbook"},
                )
                r = client.post(
                    "/ui/api/notebooks/sv2-book/papers/upload",
                    data={"paper_id": "textbook:sv2-book"},
                    files={"file": ("b.pdf", _MINIMAL_PDF, "application/pdf")},
                )
                assert r.status_code == 201, r.text
                # PDF landed on disk.
                pdf = notebooks_base / "sv2-book" / "pdfs" / "textbook_sv2-book.pdf"
                assert pdf.is_file()
                # Status unchanged — still pending (no tracker to flip it).
                status_r = client.get("/ui/api/notebooks/sv2-book/parse-status")
                assert status_r.json()["parse_status"] == "pending"
        finally:
            client._arxmcp_loop.run_until_complete(  # type: ignore[attr-defined]
                client._arxmcp_store.close()  # type: ignore[attr-defined]
            )
            client._arxmcp_loop.close()  # type: ignore[attr-defined]

    def test_has_running_parse_refuses_second_schedule(
        self, tmp_path: Path, notebooks_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """F4: even when the in-memory tracker reports is_running=False
        (e.g. cross-restart), a DB row already at parse_status='running'
        must block a second schedule via has_running_parse."""
        from unittest.mock import MagicMock

        tracker = MagicMock()
        tracker.is_running.return_value = False  # in-memory says idle
        client = self._client_with_tracker(
            tmp_path, notebooks_base, monkeypatch, tracker,
        )
        try:
            with client:
                client.post(
                    "/ui/api/notebooks",
                    json={"slug": "sv3-book", "notebook_kind": "textbook"},
                )
                # Flip the DB row to 'running' directly (simulating an
                # orphaned cross-restart row OR a concurrent parse).
                client._arxmcp_loop.run_until_complete(  # type: ignore[attr-defined]
                    client._arxmcp_store.update_parse_status(  # type: ignore[attr-defined]
                        "sv3-book", "running",
                    )
                )
                r = client.post(
                    "/ui/api/notebooks/sv3-book/papers/upload",
                    data={"paper_id": "textbook:sv3-book"},
                    files={"file": ("b.pdf", _MINIMAL_PDF, "application/pdf")},
                )
                assert r.status_code == 201, r.text
                # The DB fallback blocked the second schedule.
                tracker.start_parse.assert_not_called()
        finally:
            client._arxmcp_loop.run_until_complete(  # type: ignore[attr-defined]
                client._arxmcp_store.close()  # type: ignore[attr-defined]
            )
            client._arxmcp_loop.close()  # type: ignore[attr-defined]


class TestParseStatusStoreLayer:
    """textbook-ingest-m6 — NotebooksStore parse-status methods.

    Covers update_parse_status, has_running_parse, and the
    mark_orphaned_parses_failed lifespan-startup sweep.
    """

    def test_update_parse_status_persists(
        self, tmp_path: Path,
    ) -> None:
        """update_parse_status writes the three fields; read-back via
        get_notebook reflects the update."""
        import asyncio

        db_path = tmp_path / "notebooks.db"

        async def _run() -> dict[str, str]:
            store = await NotebooksStore.open(db_path)
            try:
                await store.create_notebook(
                    slug="test-nb",
                    display_name="t",
                    lancedb_path="/tmp/test-nb/lancedb",
                    created_at="2026-05-28T00:00:00+00:00",
                    notebook_kind="textbook",
                    parse_status="pending",
                )
                updated = await store.update_parse_status(
                    "test-nb", "complete",
                    parse_error="",
                    parsed_html_path="/some/parsed/index.html",
                )
                assert updated is True
                row = await store.get_notebook("test-nb")
            finally:
                await store.close()
            return row

        row = asyncio.run(_run())
        assert row["parse_status"] == "complete"
        assert row["parse_error"] == ""
        assert row["parsed_html_path"] == "/some/parsed/index.html"

    def test_update_parse_status_unknown_slug_returns_false(
        self, tmp_path: Path,
    ) -> None:
        import asyncio

        db_path = tmp_path / "notebooks.db"

        async def _run() -> bool:
            store = await NotebooksStore.open(db_path)
            try:
                return await store.update_parse_status(
                    "nonexistent-slug", "complete",
                )
            finally:
                await store.close()

        assert asyncio.run(_run()) is False

    def test_has_running_parse_true_when_running(
        self, tmp_path: Path,
    ) -> None:
        import asyncio

        db_path = tmp_path / "notebooks.db"

        async def _run() -> tuple[bool, bool]:
            store = await NotebooksStore.open(db_path)
            try:
                await store.create_notebook(
                    slug="nb-running",
                    display_name="r",
                    lancedb_path="/tmp/nb-running/lancedb",
                    created_at="2026-05-28T00:00:00+00:00",
                    notebook_kind="textbook",
                    parse_status="pending",
                )
                before = await store.has_running_parse("nb-running")
                await store.update_parse_status(
                    "nb-running", "running",
                )
                after = await store.has_running_parse("nb-running")
            finally:
                await store.close()
            return before, after

        before, after = asyncio.run(_run())
        assert before is False  # 'pending' is not 'running'
        assert after is True

    def test_mark_orphaned_parses_failed_flips_running_to_failed(
        self, tmp_path: Path,
    ) -> None:
        import asyncio

        db_path = tmp_path / "notebooks.db"

        async def _run() -> dict[str, str]:
            store = await NotebooksStore.open(db_path)
            try:
                # Seed a notebook + flip it to 'running'.
                await store.create_notebook(
                    slug="nb-orphan",
                    display_name="o",
                    lancedb_path="/tmp/nb-orphan/lancedb",
                    created_at="2026-05-28T00:00:00+00:00",
                    notebook_kind="textbook",
                    parse_status="running",  # pre-orphan
                )
                # Sweep.
                recovered = await store.mark_orphaned_parses_failed(
                    message="server restarted mid-parse",
                )
                assert recovered == 1
                row = await store.get_notebook("nb-orphan")
            finally:
                await store.close()
            return row

        row = asyncio.run(_run())
        assert row["parse_status"] == "failed"
        # message is HTML-escaped.
        assert "server restarted mid-parse" in row["parse_error"]

    def test_mark_orphaned_parses_skips_non_running(
        self, tmp_path: Path,
    ) -> None:
        """The sweep MUST NOT touch rows in 'skipped', 'pending',
        'complete', or 'failed' states — only 'running'."""
        import asyncio

        db_path = tmp_path / "notebooks.db"

        async def _run() -> int:
            store = await NotebooksStore.open(db_path)
            try:
                for slug, ps in [
                    ("arxiv-nb", None),  # → 'skipped' via DEFAULT
                    ("tb-pending", "pending"),
                    ("tb-complete", "complete"),
                    ("tb-failed", "failed"),
                ]:
                    await store.create_notebook(
                        slug=slug,
                        display_name=slug,
                        lancedb_path=f"/tmp/{slug}/lancedb",
                        created_at="2026-05-28T00:00:00+00:00",
                        notebook_kind=("arxiv" if slug == "arxiv-nb"
                                       else "textbook"),
                        parse_status=ps,
                    )
                recovered = await store.mark_orphaned_parses_failed(
                    message="sweep test",
                )
            finally:
                await store.close()
            return recovered

        assert asyncio.run(_run()) == 0


class TestNotebookKindMigration:
    """m3 — SQLite ALTER TABLE migration backfills pre-m3
    ``notebooks.db`` rows with ``notebook_kind='arxiv'``.

    Regression: opening a v2 database (created before m3) and bumping
    it to v3 must NOT drop existing rows; existing rows must read with
    ``notebook_kind == "arxiv"`` via SQLite DEFAULT.
    """

    def test_v2_to_v3_migration_backfills_arxiv(
        self, tmp_path: Path,
    ) -> None:
        import asyncio
        import sqlite3

        db_path = tmp_path / "notebooks.db"

        async def _seed_v2_and_query_v3() -> dict[str, str]:
            # Build a v2 schema directly to simulate a pre-m3 database
            # on disk. Replicates the v1→v2 migration path exactly so
            # the row schema matches what an existing operator's db
            # file would look like.
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute("PRAGMA user_version = 0")
                conn.execute(
                    "CREATE TABLE notebooks ("
                    "  slug          TEXT PRIMARY KEY,"
                    "  display_name  TEXT NOT NULL DEFAULT '',"
                    "  lancedb_path  TEXT NOT NULL,"
                    "  created_at    TEXT NOT NULL"
                    ")"
                )
                conn.execute(
                    "INSERT INTO notebooks "
                    "(slug, display_name, lancedb_path, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "legacy-nb",
                        "Legacy",
                        "/tmp/legacy/lancedb",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                conn.execute("PRAGMA user_version = 2")
                conn.commit()
            finally:
                conn.close()

            # Now open via NotebooksStore — the v2→v3 migration runs.
            store = await NotebooksStore.open(db_path)
            try:
                rows = await store.list_notebooks()
                assert len(rows) == 1, "legacy row must survive migration"
                return rows[0]
            finally:
                await store.close()

        row = asyncio.run(_seed_v2_and_query_v3())
        assert row["slug"] == "legacy-nb"
        assert row["notebook_kind"] == "arxiv", (
            "legacy rows must backfill notebook_kind='arxiv' "
            "via SQLite DEFAULT during the v2→v3 ALTER TABLE"
        )

    def test_v3_schema_user_version_set(
        self, tmp_path: Path,
    ) -> None:
        """After NotebooksStore.open on a fresh DB, PRAGMA user_version
        is the CURRENT SCHEMA_VERSION (5 after notebook-paper-discovery-m1)."""
        import asyncio
        import sqlite3

        db_path = tmp_path / "notebooks.db"

        async def _open_close() -> int:
            store = await NotebooksStore.open(db_path)
            try:
                conn = sqlite3.connect(str(db_path))
                try:
                    cur = conn.execute("PRAGMA user_version")
                    return int(cur.fetchone()[0])
                finally:
                    conn.close()
            finally:
                await store.close()

        version = asyncio.run(_open_close())
        assert version == 5

    def test_v1_to_v3_migration_runs_both_blocks(
        self, tmp_path: Path,
    ) -> None:
        """m3 rect F2 regression guard.

        Most pessimistic legacy path: a v1 database that pre-dates m9's
        ``notebook_ingest_runs`` table. ``NotebooksStore.open`` must run
        BOTH the v1→v2 ALTER (creating ``notebook_ingest_runs``) AND
        the v2→v3 ALTER (adding ``notebook_kind``) in sequence on the
        same connection.
        """
        import asyncio
        import sqlite3

        db_path = tmp_path / "notebooks.db"

        async def _run() -> dict[str, object]:
            # Seed a v1 schema directly (notebooks + notebook_papers
            # tables only; no notebook_ingest_runs).
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    "CREATE TABLE notebooks ("
                    "  slug          TEXT PRIMARY KEY,"
                    "  display_name  TEXT NOT NULL DEFAULT '',"
                    "  lancedb_path  TEXT NOT NULL,"
                    "  created_at    TEXT NOT NULL"
                    ")"
                )
                conn.execute(
                    "CREATE TABLE notebook_papers ("
                    "  slug      TEXT NOT NULL,"
                    "  paper_id  TEXT NOT NULL,"
                    "  added_at  TEXT NOT NULL,"
                    "  PRIMARY KEY (slug, paper_id)"
                    ")"
                )
                conn.execute(
                    "INSERT INTO notebooks "
                    "(slug, display_name, lancedb_path, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "v1-legacy",
                        "v1 legacy",
                        "/tmp/v1/lancedb",
                        "2025-12-01T00:00:00+00:00",
                    ),
                )
                conn.execute("PRAGMA user_version = 1")
                conn.commit()
            finally:
                conn.close()

            # Open via NotebooksStore — both migrations should run.
            store = await NotebooksStore.open(db_path)
            try:
                rows = await store.list_notebooks()
            finally:
                await store.close()

            # Verify final state.
            conn = sqlite3.connect(str(db_path))
            try:
                version = int(
                    conn.execute("PRAGMA user_version").fetchone()[0]
                )
                # notebook_ingest_runs exists (v2 migration ran).
                ingest_runs_present = bool(
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE "
                        "type='table' AND name='notebook_ingest_runs'"
                    ).fetchone()
                )
                # notebook_kind column exists (v3 migration ran).
                cols = [
                    r[1]
                    for r in conn.execute(
                        "PRAGMA table_info(notebooks)"
                    ).fetchall()
                ]
            finally:
                conn.close()

            return {
                "version": version,
                "ingest_runs_present": ingest_runs_present,
                "cols": cols,
                "rows": rows,
            }

        result = asyncio.run(_run())
        assert result["version"] == 5
        assert result["ingest_runs_present"] is True
        assert "notebook_kind" in result["cols"]
        # textbook-ingest-m6 columns also present after v3→v4.
        assert "parse_status" in result["cols"]
        assert "parse_error" in result["cols"]
        assert "parsed_html_path" in result["cols"]
        # notebook-paper-discovery-m1 columns present after v4→v5.
        assert "discovery_category" in result["cols"]
        assert "description" in result["cols"]
        # The legacy row's m3 column backfilled to 'arxiv'.
        rows = result["rows"]
        assert len(rows) == 1
        assert rows[0]["slug"] == "v1-legacy"
        assert rows[0]["notebook_kind"] == "arxiv"
        # textbook-ingest-m6 column-level DEFAULT backfills correctly:
        # legacy arxiv-kind rows land as 'skipped', NOT 'pending'.
        assert rows[0]["parse_status"] == "skipped"
        assert rows[0]["parse_error"] == ""
        assert rows[0]["parsed_html_path"] == ""

    def test_open_is_idempotent_against_v3(
        self, tmp_path: Path,
    ) -> None:
        """m3 rect F4 regression guard.

        Re-opening a v3 database must not re-run any migration block
        (each block guards with ``if current_version < N:``). Confirms
        that all three ``if`` blocks short-circuit on a v3 connection
        — defensive against a future contributor swapping ``CREATE
        TABLE IF NOT EXISTS`` for the destructive form.
        """
        import asyncio
        import sqlite3

        db_path = tmp_path / "notebooks.db"

        async def _open_close_open() -> tuple[int, list[str], int, list[str]]:
            # First open: fresh DB → v3.
            store = await NotebooksStore.open(db_path)
            try:
                await store.create_notebook(
                    slug="idempotency-test",
                    display_name="Idempotency test",
                    lancedb_path="/tmp/idemp/lancedb",
                    created_at="2026-05-27T00:00:00+00:00",
                    notebook_kind="textbook",
                )
            finally:
                await store.close()

            conn = sqlite3.connect(str(db_path))
            try:
                v_first = int(
                    conn.execute("PRAGMA user_version").fetchone()[0]
                )
                cols_first = sorted(
                    r[1]
                    for r in conn.execute(
                        "PRAGMA table_info(notebooks)"
                    ).fetchall()
                )
            finally:
                conn.close()

            # Second open: existing v3 DB.
            store = await NotebooksStore.open(db_path)
            try:
                rows = await store.list_notebooks()
            finally:
                await store.close()

            conn = sqlite3.connect(str(db_path))
            try:
                v_second = int(
                    conn.execute("PRAGMA user_version").fetchone()[0]
                )
                cols_second = sorted(
                    r[1]
                    for r in conn.execute(
                        "PRAGMA table_info(notebooks)"
                    ).fetchall()
                )
            finally:
                conn.close()
            assert len(rows) == 1
            return v_first, cols_first, v_second, cols_second

        v1, c1, v2, c2 = asyncio.run(_open_close_open())
        assert v1 == 5 and v2 == 5
        # Schema byte-stable across re-opens.
        assert c1 == c2, (
            f"notebooks columns drifted across re-open: "
            f"first={c1!r} second={c2!r}"
        )
        # m3 rect F4: notebook_kind survived re-open without
        # re-running the v3 ALTER.
        assert "notebook_kind" in c2


# ---------------------------------------------------------------------------
# notebook-paper-discovery-m1: v4→v5 migration + topic metadata
# ---------------------------------------------------------------------------


class TestV4ToV5Migration:
    """notebook-paper-discovery-m1 — additive v4→v5 migration adds
    ``discovery_category`` + ``description`` with empty-string defaults.
    """

    def test_v4_to_v5_backfills_empty_topic(self, tmp_path: Path) -> None:
        """A pre-m1 (v4) row backfills to empty topic fields, survives the
        migration, and the DB lands at user_version 5."""
        import asyncio
        import sqlite3

        db_path = tmp_path / "notebooks.db"

        async def _seed_v4_and_query_v5() -> tuple[dict[str, str], int]:
            conn = sqlite3.connect(str(db_path))
            try:
                # Full v4 notebooks shape (all 8 columns present).
                conn.execute(
                    "CREATE TABLE notebooks ("
                    "  slug             TEXT PRIMARY KEY,"
                    "  display_name     TEXT NOT NULL DEFAULT '',"
                    "  lancedb_path     TEXT NOT NULL,"
                    "  created_at       TEXT NOT NULL,"
                    "  notebook_kind    TEXT NOT NULL DEFAULT 'arxiv',"
                    "  parse_status     TEXT NOT NULL DEFAULT 'skipped',"
                    "  parse_error      TEXT NOT NULL DEFAULT '',"
                    "  parsed_html_path TEXT NOT NULL DEFAULT ''"
                    ")"
                )
                conn.execute(
                    "CREATE TABLE notebook_papers ("
                    "  slug      TEXT NOT NULL,"
                    "  paper_id  TEXT NOT NULL,"
                    "  added_at  TEXT NOT NULL,"
                    "  PRIMARY KEY (slug, paper_id)"
                    ")"
                )
                conn.execute(
                    "INSERT INTO notebooks "
                    "(slug, display_name, lancedb_path, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "legacy-v4",
                        "Legacy v4",
                        "/tmp/legacy/lancedb",
                        "2026-02-01T00:00:00+00:00",
                    ),
                )
                conn.execute("PRAGMA user_version = 4")
                conn.commit()
            finally:
                conn.close()

            store = await NotebooksStore.open(db_path)
            try:
                rows = await store.list_notebooks()
                assert len(rows) == 1, "legacy row must survive migration"
                row = rows[0]
            finally:
                await store.close()

            conn = sqlite3.connect(str(db_path))
            try:
                version = int(
                    conn.execute("PRAGMA user_version").fetchone()[0]
                )
            finally:
                conn.close()
            return row, version

        row, version = asyncio.run(_seed_v4_and_query_v5())
        assert version == 5
        assert row["slug"] == "legacy-v4"
        assert row["discovery_category"] == "", (
            "legacy rows must backfill discovery_category='' via the "
            "v4→v5 ALTER TABLE DEFAULT"
        )
        assert row["description"] == ""

    def test_v4_to_v5_is_idempotent(self, tmp_path: Path) -> None:
        """Re-opening a v5 DB does not re-run the v4→v5 block (which would
        raise ``duplicate column name``); the BEGIN/COMMIT block is
        re-runnable and columns are byte-stable across re-opens."""
        import asyncio
        import sqlite3

        db_path = tmp_path / "notebooks.db"

        async def _open_twice() -> tuple[int, list[str], int, list[str]]:
            store = await NotebooksStore.open(db_path)
            await store.close()
            conn = sqlite3.connect(str(db_path))
            try:
                v1 = int(conn.execute("PRAGMA user_version").fetchone()[0])
                c1 = sorted(
                    r[1] for r in conn.execute(
                        "PRAGMA table_info(notebooks)"
                    ).fetchall()
                )
            finally:
                conn.close()
            # Second open: existing v5 DB — must NOT crash.
            store = await NotebooksStore.open(db_path)
            await store.close()
            conn = sqlite3.connect(str(db_path))
            try:
                v2 = int(conn.execute("PRAGMA user_version").fetchone()[0])
                c2 = sorted(
                    r[1] for r in conn.execute(
                        "PRAGMA table_info(notebooks)"
                    ).fetchall()
                )
            finally:
                conn.close()
            return v1, c1, v2, c2

        v1, c1, v2, c2 = asyncio.run(_open_twice())
        assert v1 == 5 and v2 == 5
        assert c1 == c2
        assert "discovery_category" in c2
        assert "description" in c2


class TestNotebookTopicMetadata:
    """notebook-paper-discovery-m1 — create + edit topic metadata via the
    REST surface; validation, round-trip persistence, and XSS-safety."""

    def test_create_with_topic_roundtrips(self, client: TestClient) -> None:
        r = client.post(
            "/ui/api/notebooks",
            json={
                "slug": "bridgeland",
                "display_name": "Bridgeland",
                "discovery_category": "math.AG",
                "description": "Bridgeland stability on K3 surfaces",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["discovery_category"] == "math.AG"
        # FM-4 + FM-5: persisted and surfaced via list_notebooks.
        rows = client.get("/ui/api/notebooks").json()
        assert rows[0]["discovery_category"] == "math.AG"
        assert rows[0]["description"] == "Bridgeland stability on K3 surfaces"

    def test_create_empty_category_allowed(self, client: TestClient) -> None:
        """FM-1: an empty discovery_category is valid (not specified)."""
        r = client.post(
            "/ui/api/notebooks",
            json={"slug": "no-cat", "discovery_category": ""},
        )
        assert r.status_code == 201, r.text
        assert r.json()["discovery_category"] == ""

    def test_create_invalid_category_422(self, client: TestClient) -> None:
        r = client.post(
            "/ui/api/notebooks",
            json={"slug": "bad-cat", "discovery_category": "math.QQ"},
        )
        assert r.status_code == 422, r.text
        assert "discovery_category" in r.json()["detail"]

    def test_patch_topic_updates_both_fields(
        self, client: TestClient,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.patch(
            "/ui/api/notebooks/demo-nb/topic",
            json={
                "discovery_category": "math.NT",
                "description": "L-functions",
            },
        )
        assert r.status_code == 200, r.text
        # Fragment echoes the new values (html-escaped).
        assert "math.NT" in r.text
        assert "L-functions" in r.text
        assert 'id="topic-block"' in r.text
        # Persisted: get_notebook via list reflects the update.
        rows = client.get("/ui/api/notebooks").json()
        assert rows[0]["discovery_category"] == "math.NT"
        assert rows[0]["description"] == "L-functions"

    def test_patch_topic_invalid_category_422(
        self, client: TestClient,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.patch(
            "/ui/api/notebooks/demo-nb/topic",
            json={"discovery_category": "cs.LO", "description": ""},
        )
        assert r.status_code == 422, r.text

    def test_patch_topic_unknown_slug_404(
        self, client: TestClient,
    ) -> None:
        r = client.patch(
            "/ui/api/notebooks/ghost/topic",
            json={"discovery_category": "", "description": "x"},
        )
        assert r.status_code == 404, r.text

    def test_patch_topic_escapes_description(
        self, client: TestClient,
    ) -> None:
        """FM-2: the returned fragment html-escapes a hostile description;
        no raw <script> reaches the swap target."""
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.patch(
            "/ui/api/notebooks/demo-nb/topic",
            json={
                "discovery_category": "",
                "description": "<script>alert(1)</script>",
            },
        )
        assert r.status_code == 200, r.text
        assert "<script>" not in r.text
        assert "&lt;script&gt;" in r.text
