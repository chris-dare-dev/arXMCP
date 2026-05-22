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
            "https://ar5iv.labs.arxiv.org/html/2604.26204",    # ar5iv (m8 scope)
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
