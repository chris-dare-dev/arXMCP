"""The notebook page's papers table is split into ``?page=N`` pages.

Rows are seeded straight into the store with distinct ``added_at`` stamps,
so the store's ``added_at DESC`` order is known and each page's rows can be
named exactly. A bad ``page`` value is clamped, never an error: the route is
reached by clicking links, and a stale link should land on a real page.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arxmcp.corpus import notebooks as _notebook_common
from arxmcp.corpus.notebooks_store import NotebooksStore
from arxmcp.server.routes import notebooks as notebooks_module
from arxmcp.server.routes import ui as ui_module
from arxmcp.server.routes.notebooks import router as notebooks_router
from arxmcp.server.routes.ui import router as ui_router

_SLUG = "paging"
_SIZE = ui_module._PAPERS_PAGE_SIZE


def _paper_id(i: int) -> str:
    return f"2401.{i:05d}"


def _newest_first(n: int) -> list[str]:
    """Paper ids in the order the page lists them: the highest index was
    added last, so it comes first."""
    return [_paper_id(i) for i in range(n - 1, -1, -1)]


@pytest.fixture
def make_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[int], TestClient]]:
    """Return a factory: ``make_client(n)`` serves a notebook holding ``n``
    papers, ``2401.00000`` added first."""
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    loop = asyncio.new_event_loop()
    store = loop.run_until_complete(NotebooksStore.open(tmp_path / "notebooks.db"))
    clients: list[TestClient] = []

    def _make(n: int) -> TestClient:
        async def _seed() -> None:
            await store.create_notebook(
                _SLUG,
                "Paging",
                str(base / _SLUG / "lancedb"),
                "2024-01-01T00:00:00Z",
            )
            for i in range(n):
                await store.add_paper(
                    _SLUG,
                    _paper_id(i),
                    f"2024-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
                )

        loop.run_until_complete(_seed())
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    try:
        yield _make
    finally:
        for client in clients:
            client.__exit__(None, None, None)
        loop.run_until_complete(store.close())
        loop.close()


class _Page(HTMLParser):
    """Collects the table's paper ids, the pager's links and the heading."""

    def __init__(self) -> None:
        super().__init__()
        self.paper_ids: list[str] = []
        self.pager: dict[str, str] = {}
        self.pager_text = ""
        self.has_pager = False
        self._in_pager = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "tr" and d.get("data-paper-id"):
            self.paper_ids.append(d["data-paper-id"] or "")
        if tag == "nav" and d.get("aria-label") == "Papers pages":
            self.has_pager = True
            self._in_pager = True
        if self._in_pager and tag == "a" and d.get("rel"):
            self.pager[d["rel"] or ""] = d.get("href") or ""

    def handle_endtag(self, tag):
        if tag == "nav":
            self._in_pager = False

    def handle_data(self, data):
        if self._in_pager:
            self.pager_text += data


def _get(client: TestClient, query: str = "") -> tuple[_Page, str]:
    r = client.get(f"/ui/notebooks/{_SLUG}{query}")
    assert r.status_code == 200, r.text
    page = _Page()
    page.feed(r.text)
    return page, r.text


def _href(page: int) -> str:
    return f"/ui/notebooks/{_SLUG}?page={page}"


#: Two full pages and a partial third, so first, middle and last differ.
_N = 2 * _SIZE + 7


class TestPages:
    def test_page_size_is_a_positive_constant(self) -> None:
        assert isinstance(_SIZE, int) and _SIZE > 0

    def test_first_page_is_the_default(self, make_client) -> None:
        client = make_client(_N)
        page, html = _get(client)
        assert page.paper_ids == _newest_first(_N)[:_SIZE]
        assert page.pager == {"next": _href(2)}
        assert f"Page 1 of 3 · papers 1–{_SIZE} of {_N}" in page.pager_text
        # The heading counts the notebook, not the page.
        assert f"Papers in this notebook ({_N})" in html

    def test_explicit_page_one_matches_the_default(self, make_client) -> None:
        client = make_client(_N)
        assert _get(client, "?page=1")[0].paper_ids == _get(client)[0].paper_ids

    def test_middle_page(self, make_client) -> None:
        client = make_client(_N)
        page, _ = _get(client, "?page=2")
        assert page.paper_ids == _newest_first(_N)[_SIZE : 2 * _SIZE]
        assert page.pager == {"prev": _href(1), "next": _href(3)}
        assert f"Page 2 of 3 · papers {_SIZE + 1}–{2 * _SIZE} of {_N}" in page.pager_text

    def test_last_page_is_partial(self, make_client) -> None:
        client = make_client(_N)
        page, _ = _get(client, "?page=3")
        assert page.paper_ids == _newest_first(_N)[2 * _SIZE :]
        assert len(page.paper_ids) == 7
        assert page.pager == {"prev": _href(2)}
        assert f"Page 3 of 3 · papers {2 * _SIZE + 1}–{_N} of {_N}" in page.pager_text

    def test_pages_cover_every_paper_once(self, make_client) -> None:
        client = make_client(_N)
        seen = [pid for n in (1, 2, 3) for pid in _get(client, f"?page={n}")[0].paper_ids]
        assert seen == _newest_first(_N)

    def test_exactly_one_page_has_no_pager(self, make_client) -> None:
        client = make_client(_SIZE)
        page, _ = _get(client)
        assert page.paper_ids == _newest_first(_SIZE)
        assert not page.has_pager

    def test_one_past_a_full_page_gets_a_second_page(self, make_client) -> None:
        client = make_client(_SIZE + 1)
        page, _ = _get(client, "?page=2")
        assert page.paper_ids == [_paper_id(0)]
        assert page.pager == {"prev": _href(1)}


class TestBadPageValuesAreClamped:
    @pytest.mark.parametrize("value", ["4", "99", "100000000000000000000000"])
    def test_past_the_end_is_the_last_page(self, make_client, value) -> None:
        client = make_client(_N)
        assert _get(client, f"?page={value}")[0].paper_ids == _newest_first(_N)[2 * _SIZE :]

    @pytest.mark.parametrize("value", ["0", "-1", "-99"])
    def test_below_one_is_the_first_page(self, make_client, value) -> None:
        client = make_client(_N)
        assert _get(client, f"?page={value}")[0].paper_ids == _newest_first(_N)[:_SIZE]

    @pytest.mark.parametrize("value", ["abc", "", "2.5", "1e3", "%00", "2;drop"])
    def test_non_numeric_is_the_first_page(self, make_client, value) -> None:
        client = make_client(_N)
        page, _ = _get(client, f"?page={value}")
        assert page.paper_ids == _newest_first(_N)[:_SIZE]

    def test_repeated_page_uses_the_last_value(self, make_client) -> None:
        # Starlette keeps the last of a repeated query key; this pins that
        # the route goes along with it rather than failing.
        client = make_client(_N)
        page, _ = _get(client, "?page=3&page=2")
        assert page.paper_ids == _newest_first(_N)[_SIZE : 2 * _SIZE]


class TestEmptyNotebook:
    def test_empty_notebook_renders_its_empty_state(self, make_client) -> None:
        client = make_client(0)
        page, html = _get(client)
        assert page.paper_ids == []
        assert not page.has_pager
        assert "No papers yet." in html
        assert "Papers in this notebook (0)" in html

    @pytest.mark.parametrize("value", ["1", "2", "0", "abc"])
    def test_any_page_of_an_empty_notebook_is_the_empty_page(
        self,
        make_client,
        value,
    ) -> None:
        client = make_client(0)
        page, html = _get(client, f"?page={value}")
        assert page.paper_ids == []
        assert not page.has_pager
        assert "No papers yet." in html


class TestOtherViewsStillWork:
    def test_missing_notebook_is_still_an_html_404(self, make_client) -> None:
        client = make_client(0)
        r = client.get("/ui/notebooks/nope-not-here?page=2")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("text/html")

    def test_the_json_route_still_returns_every_row(self, make_client) -> None:
        client = make_client(_N)
        r = client.get(f"/ui/api/notebooks/{_SLUG}/papers")
        assert r.status_code == 200
        assert [row["paper_id"] for row in r.json()] == _newest_first(_N)

    def test_the_tbody_swap_target_survives_on_every_page(self, make_client) -> None:
        client = make_client(_N)
        for n in (1, 2, 3):
            assert 'id="papers-tbody"' in _get(client, f"?page={n}")[1]
