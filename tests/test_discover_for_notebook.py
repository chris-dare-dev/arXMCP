"""Unit tests for ``tools.discover_for_notebook`` (notebook-paper-discovery-m3).

The arXiv HTTP layer is mocked via ``monkeypatch.setattr(_arxiv_api, "_fetch_url", …)``
(the m2 / graph_ingest pattern) so NO live arXiv call happens in CI. Each test opens
a real ``NotebooksStore`` on a ``tmp_path`` SQLite, seeds the notebook + junction
rows, and drives the async core directly via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from pathlib import Path

import pytest

from server.notebooks_store import NotebooksStore
from tools import _arxiv_api
from tools.discover_for_notebook import (
    DiscoveryCandidate,
    discover_for_notebook_async,
)


def _feed(entries: list[tuple[str, str, str]]) -> bytes:
    """Build an Atom feed. ``entries`` = list of (paper_id, title, published)."""
    body = "".join(
        f"<entry>"
        f"<id>http://arxiv.org/abs/{pid}v1</id>"
        f"<title>{title}</title>"
        f"<published>{published}</published>"
        f"<summary>abstract describing {pid} at length for the head field</summary>"
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
    ("2307.00001", "First paper on stability", "2023-07-01T00:00:00Z"),
    ("2307.00002", "Second paper on moduli", "2023-07-02T00:00:00Z"),
    ("2307.00003", "Third paper on K3 surfaces", "2023-07-03T00:00:00Z"),
]

_NOOP_SLEEP = lambda _s: None  # noqa: E731 — test stub


async def _seed_store(
    db_path: Path,
    *,
    slug: str = "bridgeland",
    category: str = "math.AG",
    description: str = "Bridgeland stability",
    papers: tuple[str, ...] = (),
) -> NotebooksStore:
    store = await NotebooksStore.open(db_path)
    await store.create_notebook(
        slug=slug,
        display_name="Bridgeland",
        lancedb_path=str(db_path.parent / slug / "lancedb"),
        created_at="2026-05-31T00:00:00+00:00",
        discovery_category=category,
        description=description,
    )
    for i, pid in enumerate(papers):
        await store.add_paper(slug, pid, f"2026-05-31T00:00:0{i}+00:00")
    return store


class TestDiscoverHappyPath:
    def test_returns_new_and_dedups_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed(_THREE),
        )

        async def _run() -> list[DiscoveryCandidate]:
            # Notebook already contains the first feed paper -> it must be deduped.
            store = await _seed_store(
                tmp_path / "notebooks.db", papers=("2307.00001",),
            )
            try:
                return await discover_for_notebook_async(
                    store, "bridgeland", sleep=_NOOP_SLEEP,
                )
            finally:
                await store.close()

        out = asyncio.run(_run())
        # AC: >=1 candidate, 0 already-present papers.
        assert [c.paper_id for c in out] == ["2307.00002", "2307.00003"]
        assert "2307.00001" not in {c.paper_id for c in out}
        # title + submitted_date are populated (the m3 Candidate extension).
        assert out[0].title == "Second paper on moduli"
        assert out[0].submitted_date == "2023-07-02T00:00:00Z"
        assert out[0].abstract_head.startswith("abstract describing 2307.00002")

    def test_dedup_handles_versioned_existing_paper(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # rect F1: the URL-paste route stores VERSIONED ids (e.g. 2307.00001v2);
        # parse_atom_feed strips the suffix, so dedup must normalise the stored
        # side or the paper is silently re-proposed every run.
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed(_THREE),
        )

        async def _run() -> list[DiscoveryCandidate]:
            store = await _seed_store(tmp_path / "notebooks.db")
            # Simulate URL-paste adding a versioned id for the first feed paper.
            await store.add_paper(
                "bridgeland", "2307.00001v2", "2026-05-31T00:00:00+00:00",
            )
            try:
                return await discover_for_notebook_async(
                    store, "bridgeland", sleep=_NOOP_SLEEP,
                )
            finally:
                await store.close()

        out = asyncio.run(_run())
        # 2307.00001v2 in the junction matches 2307.00001 from the feed -> deduped.
        assert [c.paper_id for c in out] == ["2307.00002", "2307.00003"]

    def test_deterministic_across_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed(_THREE),
        )

        async def _run() -> tuple[list[str], list[str]]:
            store = await _seed_store(tmp_path / "notebooks.db")
            try:
                a = await discover_for_notebook_async(
                    store, "bridgeland", sleep=_NOOP_SLEEP,
                )
                b = await discover_for_notebook_async(
                    store, "bridgeland", sleep=_NOOP_SLEEP,
                )
                return [c.paper_id for c in a], [c.paper_id for c in b]
            finally:
                await store.close()

        a, b = asyncio.run(_run())
        assert a == b == ["2307.00001", "2307.00002", "2307.00003"]

    def test_all_deduped_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed(_THREE),
        )

        async def _run() -> list[DiscoveryCandidate]:
            store = await _seed_store(
                tmp_path / "notebooks.db",
                papers=("2307.00001", "2307.00002", "2307.00003"),
            )
            try:
                return await discover_for_notebook_async(
                    store, "bridgeland", sleep=_NOOP_SLEEP,
                )
            finally:
                await store.close()

        # All candidates already present -> empty list, NOT an error.
        assert asyncio.run(_run()) == []


class TestDiscoverGuards:
    def test_unknown_slug_raises(self, tmp_path: Path) -> None:
        async def _run() -> None:
            store = await NotebooksStore.open(tmp_path / "notebooks.db")
            try:
                await discover_for_notebook_async(
                    store, "ghost", sleep=_NOOP_SLEEP,
                )
            finally:
                await store.close()

        with pytest.raises(ValueError, match="not found"):
            asyncio.run(_run())

    def test_empty_category_raises(self, tmp_path: Path) -> None:
        async def _run() -> None:
            store = await _seed_store(tmp_path / "notebooks.db", category="")
            try:
                await discover_for_notebook_async(
                    store, "bridgeland", sleep=_NOOP_SLEEP,
                )
            finally:
                await store.close()

        with pytest.raises(ValueError, match="discovery_category"):
            asyncio.run(_run())

    def test_empty_category_does_not_call_arxiv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Guard must fire BEFORE any HTTP call (FM-a).
        calls: list[str] = []
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: calls.append(url) or _feed([]),
        )

        async def _run() -> None:
            store = await _seed_store(tmp_path / "notebooks.db", category="")
            try:
                await discover_for_notebook_async(
                    store, "bridgeland", sleep=_NOOP_SLEEP,
                )
            finally:
                await store.close()

        with pytest.raises(ValueError):
            asyncio.run(_run())
        assert calls == []


class TestDiscoverQuery:
    def test_keywords_flow_into_quoted_abs_clause(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, str] = {}

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            captured["url"] = url
            return _feed(_THREE)

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)

        async def _run() -> None:
            store = await _seed_store(
                tmp_path / "notebooks.db", description="Bridgeland stability",
            )
            try:
                await discover_for_notebook_async(
                    store, "bridgeland", sleep=_NOOP_SLEEP,
                )
            finally:
                await store.close()

        asyncio.run(_run())
        qs = urllib.parse.parse_qs(
            urllib.parse.urlparse(captured["url"]).query
        )["search_query"][0]
        assert qs == 'cat:math.AG AND abs:"Bridgeland stability"'

    def test_blank_description_is_category_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, str] = {}

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            captured["url"] = url
            return _feed(_THREE)

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)

        async def _run() -> None:
            store = await _seed_store(tmp_path / "notebooks.db", description="")
            try:
                await discover_for_notebook_async(
                    store, "bridgeland", sleep=_NOOP_SLEEP,
                )
            finally:
                await store.close()

        asyncio.run(_run())
        qs = urllib.parse.parse_qs(
            urllib.parse.urlparse(captured["url"]).query
        )["search_query"][0]
        assert qs == "cat:math.AG"

    def test_single_page_no_sleep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []
        sleeps: list[float] = []
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: (calls.append(url), _feed(_THREE))[1],
        )

        async def _run() -> None:
            store = await _seed_store(tmp_path / "notebooks.db")
            try:
                await discover_for_notebook_async(
                    store, "bridgeland", max_results=200, sleep=sleeps.append,
                )
            finally:
                await store.close()

        asyncio.run(_run())
        assert len(calls) == 1  # only export.arxiv.org, one request
        assert sleeps == []  # no inter-page sleep for max_results <= 2000
