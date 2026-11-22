"""The notebook page's Discover view lives at a URL.

Discover is the console swap that changes what the operator is looking at
without storing anything. Its form pushes a URL into history when the results
swap in, and that URL must render the full page with a discovery run already
in the panel. Otherwise reload drops the results, and Back or Forward lands on
a page that is not the one that was there.

These tests read the pushed URL out of the rendered page and then load it, so
the attribute and the route are checked against each other rather than each
against a hand-copied string. No live arXiv call is made:
``arxmcp.ingest.arxiv_api._fetch_url`` is replaced in every test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arxmcp.corpus import notebooks as _notebook_common
from arxmcp.corpus.notebooks_store import NotebooksStore
from arxmcp.ingest import arxiv_api as _arxiv_api
from arxmcp.server.routes import notebooks as notebooks_module
from arxmcp.server.routes.notebooks import router as notebooks_router
from arxmcp.server.routes.ui import router as ui_router
from tests.test_discover_route import _feed

_THREE = [
    ("2307.00001", "First on stability", "2023-07-01T00:00:00Z"),
    ("2307.00002", "Second on moduli", "2023-07-02T00:00:00Z"),
    ("2307.00003", "Third on K3 surfaces", "2023-07-03T00:00:00Z"),
]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(tmp_path / "notebooks.db"))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


@pytest.fixture
def arxiv(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Serve ``_THREE`` from the fake arXiv and record every fetch."""
    calls: list[str] = []

    def _fetch(url, contact_email=None):
        calls.append(url)
        return _feed(_THREE)

    monkeypatch.setattr(_arxiv_api, "_fetch_url", _fetch)
    return calls


def _make_notebook(client: TestClient, slug: str = "bridgeland", **topic: str) -> None:
    body = {"slug": slug, "discovery_category": "math.AG",
            "description": "Bridgeland stability", **topic}
    r = client.post("/ui/api/notebooks", json=body)
    assert r.status_code == 201, r.text


class _Page(HTMLParser):
    """Collects attributes by element id, the text inside one id, and
    every attribute name/value pair seen."""

    def __init__(self, text_of: str = "") -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str | None]] = {}
        self.attrs: list[tuple[str, str | None]] = []
        self.forms: list[dict[str, str | None]] = []
        self.titles: list[str] = []
        self._text_of = text_of
        self._depth = 0
        self._in_title = False
        self.text = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.attrs.extend(attrs)
        if tag == "form":
            self.forms.append(d)
        if "id" in d:
            self.by_id[d["id"] or ""] = d
        if self._depth:
            self._depth += 1
        elif self._text_of and d.get("id") == self._text_of:
            self._depth = 1
        self._in_title = tag == "h3"

    def handle_endtag(self, tag):
        if self._depth:
            self._depth -= 1
        self._in_title = False

    def handle_data(self, data):
        if self._depth:
            self.text += data
        if self._in_title:
            self.titles.append(data)


def _parse(html: str, text_of: str = "") -> _Page:
    p = _Page(text_of)
    p.feed(html)
    return p


def _pushed_url(client: TestClient, slug: str = "bridgeland") -> str:
    page = _parse(client.get(f"/ui/notebooks/{slug}").text)
    (discover_form,) = [
        f for f in page.forms
        if f.get("hx-post") == f"/ui/api/notebooks/{slug}/discover"
    ]
    url = discover_form.get("hx-push-url")
    assert url and url.startswith(f"/ui/notebooks/{slug}"), url
    return url


def _is_full_page(html: str) -> bool:
    page = _parse(html)
    return {"main", "papers-tbody", "discover-results"} <= page.by_id.keys()


class TestThePushedUrlRestoresTheView:

    def test_a_direct_load_renders_the_full_page_with_results(self, client, arxiv):
        _make_notebook(client)
        r = client.get(_pushed_url(client))
        assert r.status_code == 200
        assert _is_full_page(r.text)
        titles = _parse(r.text).titles
        assert titles == [title for _pid, title, _date in _THREE]

    def test_it_shows_what_the_discover_button_showed(self, client, arxiv):
        _make_notebook(client)
        button = client.post("/ui/api/notebooks/bridgeland/discover")
        assert button.status_code == 200
        page = client.get(_pushed_url(client))
        assert _parse(page.text).titles == _parse(button.text).titles

    def test_the_page_size_matches_the_button(self, client, monkeypatch):
        many = [(f"2307.{i:05d}", f"Paper {i}", f"2023-07-{1 + i % 28:02d}T00:00:00Z")
                for i in range(1, 41)]
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url", lambda url, contact_email=None: _feed(many),
        )
        _make_notebook(client)
        button = _parse(client.post("/ui/api/notebooks/bridgeland/discover").text)
        page = _parse(client.get(_pushed_url(client)).text)
        assert page.titles == button.titles
        assert 0 < len(page.titles) < len(many)

    def test_an_htmx_history_restore_gets_the_full_page(self, client, arxiv):
        """On a history-cache miss htmx re-requests the URL with these headers
        and swaps the response into <body>; a fragment would blank the page."""
        _make_notebook(client)
        r = client.get(
            _pushed_url(client),
            headers={"HX-Request": "true", "HX-History-Restore-Request": "true"},
        )
        assert r.status_code == 200
        assert _is_full_page(r.text)
        assert _parse(r.text).titles

    def test_candidate_metadata_stays_escaped(self, client, monkeypatch):
        hostile = [("2307.00009", "&lt;script&gt;alert(1)&lt;/script&gt;",
                    "2023-07-09T00:00:00Z")]
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url", lambda url, contact_email=None: _feed(hostile),
        )
        _make_notebook(client)
        r = client.get(_pushed_url(client))
        assert "<script>alert(1)" not in r.text
        assert _parse(r.text).titles == ["<script>alert(1)</script>"]


class TestFailuresRenderThePage:
    """A failed run is shown in the panel on a 200 page: htmx restores a
    history entry only from a 2xx response."""

    def test_an_unreachable_arxiv_is_reported_in_the_panel(self, client, monkeypatch):
        def _down(url, contact_email=None):
            raise OSError("connection refused")

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _down)
        _make_notebook(client)
        r = client.get(_pushed_url(client))
        assert r.status_code == 200
        assert _is_full_page(r.text)
        error = _parse(r.text, text_of="discover-error").text
        assert "discovery failed" in error
        assert _parse(r.text).titles == []

    def test_a_notebook_without_a_topic_is_reported_in_the_panel(self, client, arxiv):
        _make_notebook(client, slug="untopiced", discovery_category="")
        r = client.get(_pushed_url(client, "untopiced"))
        assert r.status_code == 200
        assert _is_full_page(r.text)
        assert _parse(r.text, text_of="discover-error").text.strip()
        assert arxiv == []


class TestThePlainPage:

    @pytest.mark.parametrize("query", ["", "?discover=0", "?discover=yes"])
    def test_does_not_run_discovery(self, client, arxiv, query):
        _make_notebook(client)
        r = client.get(f"/ui/notebooks/bridgeland{query}")
        assert r.status_code == 200
        assert arxiv == []
        assert _parse(r.text).titles == []
        assert _parse(r.text, text_of="discover-error").text == ""

    def test_disables_the_htmx_snapshot_cache(self, client, arxiv):
        """A snapshot taken before an Add would bring back a paper list that
        is no longer true; with the cache off htmx re-renders from the server."""
        _make_notebook(client)
        page = _parse(client.get("/ui/notebooks/bridgeland").text)
        assert ("hx-history", "false") in page.attrs
