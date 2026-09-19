"""Stage-3 regression: legacy-ui-detail-page-blocks-event-loop-then-413s.

The ``GET /ui/notebooks/{slug}`` HTML detail page used to fetch EVERY
junction row, ``stat()`` two files per paper, and Jinja-render the whole
table inline on the event loop. Two harms followed at scale:

1. **413 cliff.** Once the rendered HTML crossed the 256 KiB
   :class:`server.main.BodySizeCapMiddleware` response cap (~300–450
   rows — only ~2.5x the biggest live notebook), the page was rejected
   413 *after* the entire render had been computed and buffered. The
   work was burned and the operator saw an error page.

2. **Event-loop block.** The O(n) render + O(n) blocking ``stat()``
   syscalls ran on the single-process server's event loop, so one
   operator browser tab could freeze every concurrent request —
   including the MCP tool surface the multi-agent pipeline depends on.

The fix is server-side pagination (``?page=N``,
:data:`server.routes.ui._DETAIL_PAGE_SIZE` rows/page) with the per-page
stat loop moved off the event loop. These tests pin:

- a notebook far past the old cliff (2000 rows) renders **200, not 413**,
  with the response comfortably under the cap and only one page of rows;
- the ``LIMIT``/``OFFSET`` is real (page N shows page-N rows, no overlap);
- the total count + nav are correct and the header shows the *total*, not
  the page length;
- the event loop is not blocked: a concurrent request completes while a
  large detail page is being served.

The fixture mirrors ``tests/test_notebook_detail_status.py`` (minimal
app: notebooks + ui routers + static) but ALSO wraps the app in the real
:class:`~server.main.BodySizeCapMiddleware` at the production 256 KiB cap
so the 413 path is exercised end-to-end (the bug was invisible without
the middleware in the stack). Seeding is a raw sqlite3 INSERT (WAL mode →
visible to the store's reads) so we never touch the store's asyncio.Lock
from this loop. No model load.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from server.config import DEFAULT_RESULT_BYTE_CAP
from server.main import BodySizeCapMiddleware
from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import router as notebooks_router
from server.routes.ui import _DETAIL_PAGE_SIZE
from server.routes.ui import router as ui_router
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "frontend" / "static"


@pytest.fixture
def capped_detail_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path]]:
    """Minimal ui+notebooks app wrapped in the REAL 256 KiB response cap.

    Yields ``(client, db_path)`` so a test can bulk-INSERT junction rows.
    """
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        app.mount(
            "/ui/static",
            StaticFiles(directory=str(FRONTEND_STATIC)),
            name="ui-static",
        )
        # The exact middleware + cap create_app() wires (server/main.py).
        # Without it the 413 path is not in the stack and the regression
        # is invisible — that is precisely how the bug shipped green.
        app.add_middleware(BodySizeCapMiddleware, byte_cap=DEFAULT_RESULT_BYTE_CAP)
        with TestClient(app) as c:
            yield c, db_path
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _seed_notebook(db_path: Path, slug: str, n_papers: int) -> None:
    """Create ``slug`` (arxiv kind) and ``n_papers`` junction rows.

    Paper ids are stable + unique + valid new-style arXiv ids so the
    detail handler's ``is_valid_arxiv_paper_id`` preview annotation runs
    for real (it short-circuits before any stat for invalid ids).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO notebooks "
            "(slug, display_name, notebook_kind, lancedb_path, created_at, "
            " parse_status) VALUES (?, ?, 'arxiv', ?, ?, 'skipped')",
            (slug, slug, str(db_path.parent / slug / "lancedb"),
             "2026-01-01T00:00:00Z"),
        )
        rows = [
            (
                slug,
                # new-style YYMM.NNNNN — unique, valid, monotonically-timed
                f"25{(i // 10000) % 12 + 1:02d}.{i:05d}",
                # zero-padded added_at so ORDER BY added_at DESC is a clean,
                # predictable reverse-of-insertion order for offset checks
                f"2026-01-01T{i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z",
            )
            for i in range(n_papers)
        ]
        conn.executemany(
            "INSERT INTO notebook_papers (slug, paper_id, added_at) "
            "VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


class TestPaginationBoundsTheResponse:
    def test_huge_notebook_renders_200_not_413(self, capped_detail_client):
        """The core regression. 2000 papers is ~4.4x the old ~450-row 413
        cliff and ~16x the biggest live notebook. Before the fix this GET
        returned HTTP 413 (BodySizeCapMiddleware) after rendering the whole
        >256 KiB table; after the fix it returns 200 with one bounded page.
        """
        client, db_path = capped_detail_client
        _seed_notebook(db_path, "huge-nb", 2000)

        r = client.get("/ui/notebooks/huge-nb")

        assert r.status_code == 200, (
            f"expected 200, got {r.status_code} "
            f"({len(r.content)} bytes) — the detail page regressed to the "
            "render-everything-then-413 behaviour"
        )
        # Response stays well under the production cap.
        assert len(r.content) < DEFAULT_RESULT_BYTE_CAP, (
            f"rendered {len(r.content)} bytes >= cap {DEFAULT_RESULT_BYTE_CAP}"
        )
        # Only one page of rows is rendered, never all 2000.
        rendered = r.text.count("data-paper-id=")
        assert rendered == _DETAIL_PAGE_SIZE, (
            f"expected {_DETAIL_PAGE_SIZE} rows on page 1, got {rendered}"
        )
        # The heading still tells the operator the TRUE total.
        assert "(2000)" in r.text
        # Pagination nav is present for a multi-page notebook.
        assert 'class="pagination"' in r.text

    def test_second_page_shows_different_rows(self, capped_detail_client):
        """LIMIT/OFFSET is real: page 2 renders the next slice with no
        overlap with page 1 (guards an off-by-page / ignored-offset bug)."""
        client, db_path = capped_detail_client
        _seed_notebook(db_path, "paged-nb", 250)

        r1 = client.get("/ui/notebooks/paged-nb?page=1")
        r2 = client.get("/ui/notebooks/paged-nb?page=2")
        assert r1.status_code == 200 and r2.status_code == 200

        ids1 = set(re_paper_ids(r1.text))
        ids2 = set(re_paper_ids(r2.text))
        assert len(ids1) == _DETAIL_PAGE_SIZE
        assert len(ids2) == _DETAIL_PAGE_SIZE
        assert ids1.isdisjoint(ids2), "page 1 and page 2 rows overlap"

    def test_last_partial_page_and_nav_bounds(self, capped_detail_client):
        """250 papers @100/page → 3 pages; the last page holds the
        remaining 50 and offers Prev but not Next."""
        client, db_path = capped_detail_client
        _seed_notebook(db_path, "tail-nb", 250)

        r = client.get("/ui/notebooks/tail-nb?page=3")
        assert r.status_code == 200
        assert r.text.count("data-paper-id=") == 50
        assert "page 3 of 3" in r.text
        # Prev link present, Next disabled on the last page.
        assert 'rel="prev"' in r.text
        assert 'rel="next"' not in r.text

    def test_page_past_end_is_empty_but_ok(self, capped_detail_client):
        """A hand-typed ?page=99 on a small notebook must not 500/413 — it
        renders an empty page with a way back, and the total is still shown."""
        client, db_path = capped_detail_client
        _seed_notebook(db_path, "small-nb", 5)

        r = client.get("/ui/notebooks/small-nb?page=99")
        assert r.status_code == 200
        assert r.text.count("data-paper-id=") == 0
        assert "(5)" in r.text  # true total still shown
        assert "Jump to the last page" in r.text

    def test_small_notebook_has_no_pagination_nav(self, capped_detail_client):
        """A notebook that fits on one page renders no pagination nav
        (no behaviour change for the common small case)."""
        client, db_path = capped_detail_client
        _seed_notebook(db_path, "tiny-nb", 3)

        r = client.get("/ui/notebooks/tiny-nb")
        assert r.status_code == 200
        assert r.text.count("data-paper-id=") == 3
        assert 'class="pagination"' not in r.text
        assert "(3)" in r.text


class TestEventLoopNotBlocked:
    def test_concurrent_request_completes_during_large_detail_render(
        self, capped_detail_client
    ):
        """The detail page must not monopolise the event loop. We fire a
        concurrent GET against a cheap route (the notebooks JSON list) from
        a second thread while the large detail page is served, and assert
        both complete promptly. Before the fix the O(n) render + O(n)
        blocking stat() loop ran inline on the loop; the bounded page +
        ``asyncio.to_thread`` stat loop keep the loop responsive.

        This is a coarse liveness assertion, not a micro-benchmark — it
        asserts the concurrent call returns and the whole interleaving
        stays far under the multi-second freeze the finding measured.
        """
        client, db_path = capped_detail_client
        _seed_notebook(db_path, "busy-nb", 2000)

        import threading

        results: dict[str, int] = {}

        def hit_list() -> None:
            rr = client.get("/ui/api/notebooks")
            results["list"] = rr.status_code

        t0 = time.perf_counter()
        th = threading.Thread(target=hit_list)
        th.start()
        r_detail = client.get("/ui/notebooks/busy-nb")
        th.join(timeout=10.0)
        elapsed = time.perf_counter() - t0

        assert not th.is_alive(), "concurrent list request never returned"
        assert results.get("list") == 200
        assert r_detail.status_code == 200
        # Generous ceiling: the finding measured multi-second (14 s) freezes
        # at scale; a bounded page must be nowhere near that.
        assert elapsed < 5.0, f"interleaved requests took {elapsed:.1f}s"


def re_paper_ids(html: str) -> list[str]:
    import re

    return re.findall(r'data-paper-id="([^"]+)"', html)
