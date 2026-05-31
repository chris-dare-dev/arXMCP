"""Tests for POST /ui/api/notebooks/{slug}/discover (notebook-paper-discovery-m4).

Builds a minimal FastAPI app with the notebooks router + a real NotebooksStore on
a tmp_path SQLite (the test_notebook_api.py pattern), seeds notebooks via the REST
endpoints, and monkeypatches ``tools._arxiv_api._fetch_url`` so NO live arXiv call
happens in CI. Focus: the propose→confirm panel fragment, XSS-escaping of untrusted
arXiv metadata, dedup, and clean error handling (never a 500).
"""

from __future__ import annotations

import urllib.error
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import router as notebooks_router
from tools import _arxiv_api, _notebook_common


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    return base


@pytest.fixture
def client(
    tmp_path: Path, notebooks_base: Path, monkeypatch: pytest.MonkeyPatch,
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
            notebooks_module, "_now_iso", lambda: "2026-05-31T00:00:00+00:00",
        )
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _feed(entries: list[tuple[str, str, str]]) -> bytes:
    """``entries`` = list of (paper_id, title, published)."""
    body = "".join(
        f"<entry>"
        f"<id>http://arxiv.org/abs/{pid}v1</id>"
        f"<title>{title}</title>"
        f"<published>{published}</published>"
        f"<summary>abstract for {pid} long enough for the head</summary>"
        f"<author><name>A. Author</name></author>"
        f'<arxiv:primary_category term="math.AG"/>'
        f"</entry>"
        for pid, title, published in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:arxiv="http://arxiv.org/schemas/atom">'
        f"{body}</feed>"
    ).encode()


_THREE = [
    ("2307.00001", "First on stability", "2023-07-01T00:00:00Z"),
    ("2307.00002", "Second on moduli", "2023-07-02T00:00:00Z"),
    ("2307.00003", "Third on K3 surfaces", "2023-07-03T00:00:00Z"),
]


def _make_notebook(
    client: TestClient, slug: str = "bridgeland",
    *, category: str = "math.AG", description: str = "Bridgeland stability",
) -> None:
    r = client.post(
        "/ui/api/notebooks",
        json={"slug": slug, "discovery_category": category, "description": description},
    )
    assert r.status_code == 201, r.text


class TestDiscoverHappyPath:
    def test_renders_candidates(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed(_THREE),
        )
        _make_notebook(client)
        r = client.post("/ui/api/notebooks/bridgeland/discover")
        assert r.status_code == 200, r.text
        assert 'id="discover-results"' in r.text
        assert 'aria-live="polite"' in r.text
        # title + abstract rendered
        assert "Second on moduli" in r.text
        assert "abstract for 2307.00002" in r.text
        # Add mini-form posts to the existing /papers route with the paper URL
        assert 'hx-post="/ui/api/notebooks/bridgeland/papers"' in r.text
        assert 'value="https://arxiv.org/abs/2307.00002"' in r.text

    def test_dedups_existing_paper(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed(_THREE),
        )
        _make_notebook(client)
        # Record 2307.00001 in the notebook via the existing add-paper route.
        add = client.post(
            "/ui/api/notebooks/bridgeland/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2307.00001"},
        )
        assert add.status_code == 201, add.text
        r = client.post("/ui/api/notebooks/bridgeland/discover")
        assert r.status_code == 200, r.text
        # The already-present paper is filtered out; the others remain.
        assert 'value="https://arxiv.org/abs/2307.00001"' not in r.text
        assert 'value="https://arxiv.org/abs/2307.00002"' in r.text

    def test_empty_result_renders_friendly_state(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed([]),
        )
        _make_notebook(client)
        r = client.post("/ui/api/notebooks/bridgeland/discover")
        assert r.status_code == 200, r.text
        assert "No new candidates" in r.text
        assert 'id="discover-results"' in r.text


class TestDiscoverSecurity:
    def test_escapes_hostile_title(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # FM-A: arXiv title/abstract are untrusted; the f-string fragment must
        # html.escape them so a <script> payload renders inert. arXiv delivers a
        # title containing markup XML-escaped on the wire (&lt;script&gt;…),
        # which defusedxml decodes to the TEXT "<script>alert(1)</script>" — the
        # fragment must then re-escape it in the HTML output.
        hostile = [
            ("2307.09999", "&lt;script&gt;alert(1)&lt;/script&gt;", "2023-07-09T00:00:00Z"),
        ]
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed(hostile),
        )
        _make_notebook(client)
        r = client.post("/ui/api/notebooks/bridgeland/discover")
        assert r.status_code == 200, r.text
        assert "<script>alert(1)</script>" not in r.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text


class TestDiscoverErrors:
    def test_unconfigured_notebook_422_not_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Guard fires before any HTTP call; no _fetch_url needed, but stub it to
        # prove it is never reached.
        called: list[str] = []
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: called.append(url) or _feed([]),
        )
        _make_notebook(client, category="")  # no discovery_category
        r = client.post("/ui/api/notebooks/bridgeland/discover")
        assert r.status_code == 422, r.text
        assert "discovery_category" in r.json()["detail"]
        assert called == []

    def test_unknown_slug_404(self, client: TestClient) -> None:
        r = client.post("/ui/api/notebooks/ghost/discover")
        assert r.status_code == 404, r.text

    def test_bad_slug_422(self, client: TestClient) -> None:
        r = client.post("/ui/api/notebooks/UPPER/discover")
        assert r.status_code == 422, r.text

    def test_arxiv_failure_502_not_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom(url: str, contact_email: str | None = None) -> bytes:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _boom)
        _make_notebook(client)
        r = client.post("/ui/api/notebooks/bridgeland/discover")
        assert r.status_code == 502, r.text
        assert "discovery failed" in r.json()["detail"]
