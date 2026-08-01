"""notebook-surface-expansion-m2 — in-page rename (PATCH) + delete round-trip.

The notebook-detail page now carries an htmx rename form that issues
``PATCH /ui/api/notebooks/{slug}`` (server/routes/notebooks.py::rename_notebook)
updating ``display_name`` via ``NotebooksStore.update_display_name`` (an
``UPDATE``; the column exists at SCHEMA_VERSION 4 → NO migration), returning the
re-rendered ``#display-name-block`` fragment for an ``outerHTML`` swap. The
existing ``DELETE /ui/api/notebooks/{slug}`` is wired in-page behind a confirm.

Security surface (security-reviewer lens, synthesis D4): slug path-traversal →
422; over-long name → 422 (Pydantic); mass-assignment closed (only
``display_name`` accepted); control chars stripped; XSS via ``html.escape`` in
the fragment; 404 on unknown slug.

Seeding mirrors test_notebook_detail_status.py: a store opened on a private
event loop + REST create through the TestClient portal (NO async-lock acquired
on a foreign loop). No model load.
"""

from __future__ import annotations

import asyncio
import html as _html
import re as _re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import router as notebooks_router
from server.routes.ui import router as ui_router
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "server" / "frontend" / "static"


@pytest.fixture
def rd_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Minimal app (notebooks + ui routers + static) + a real NotebooksStore."""
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(
        notebooks_module, "_now_iso", lambda: "2026-05-28T16:00:00+00:00"
    )
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
        with TestClient(app) as c:
            yield c
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


#: m2-rect F1: extract the ``#display-name-block`` <p> element from a render so
#: a test can compare the two renderers (the Jinja template on the GET page vs
#: the ``_display_name_fragment`` f-string in the PATCH response). Non-greedy so
#: it stops at the first ``</p>``; the block has no nested ``</p>``.
_BLOCK_RE: _re.Pattern[str] = _re.compile(
    r'<p\b[^>]*id="display-name-block"[^>]*>(.*?)</p>', _re.S
)


def _extract_block(text: str) -> tuple[str, str]:
    """Return ``(opening_tag, inner_text)`` for the #display-name-block <p>."""
    m = _BLOCK_RE.search(text)
    assert m is not None, f"no #display-name-block <p> in: {text[:200]!r}"
    full = m.group(0)
    opening = full[: full.index(">") + 1]
    return opening, m.group(1)


class TestRendererEquivalence:
    @pytest.mark.parametrize(
        "name",
        ["", "Foo Bar", "Angle <b> & amp", 'Quote " and \''],
    )
    def test_fragment_matches_template_render(self, rd_client, name):
        """m2-rect F1: the #display-name-block is rendered by TWO independent
        paths — the Jinja template (GET page) and ``_display_name_fragment``
        (PATCH response). Pin their equivalence so a future class/id/tag/em-dash
        edit to one side can't silently desync the htmx outerHTML swap.

        Opening tags must be BYTE-identical (tag + class + id + attribute
        order). Inner content must be SEMANTICALLY identical: ``html.escape``
        (fragment) and Jinja autoescape (page) differ only in quote-codepoint
        representation (``&quot;`` vs ``&#34;``), which html.unescape collapses
        to the same character — so compare unescaped."""
        _create_notebook(rd_client, "equiv-nb")
        frag = rd_client.patch(
            "/ui/api/notebooks/equiv-nb", json={"display_name": name}
        )
        assert frag.status_code == 200, frag.text
        page = rd_client.get("/ui/notebooks/equiv-nb")
        assert page.status_code == 200
        frag_open, frag_inner = _extract_block(frag.text)
        page_open, page_inner = _extract_block(page.text)
        assert frag_open == page_open
        assert _html.unescape(frag_inner) == _html.unescape(page_inner)


class TestRename:
    def test_rename_happy_path_returns_swapped_fragment(self, rd_client):
        """AC1: PATCH updates display_name and returns the re-rendered
        #display-name-block fragment (htmx outerHTML swap), and the new name
        persists on the detail page."""
        _create_notebook(rd_client, "alpha-nb", display_name="Old Name")
        r = rd_client.patch(
            "/ui/api/notebooks/alpha-nb", json={"display_name": "New Name"}
        )
        assert r.status_code == 200, r.text
        assert 'id="display-name-block"' in r.text
        assert "New Name" in r.text
        # Persisted: the detail page now renders the new name.
        d = rd_client.get("/ui/notebooks/alpha-nb")
        assert d.status_code == 200
        assert "New Name" in d.text
        assert "Old Name" not in d.text

    def test_rename_to_empty_clears_to_em_dash(self, rd_client):
        """D5: an empty display_name is valid (clears the name → renders as —)."""
        _create_notebook(rd_client, "beta-nb", display_name="Has Name")
        r = rd_client.patch(
            "/ui/api/notebooks/beta-nb", json={"display_name": ""}
        )
        assert r.status_code == 200, r.text
        assert "—" in r.text  # em dash placeholder
        assert "Has Name" not in r.text

    def test_rename_malformed_slug_422(self, rd_client):
        """D4: a slug failing validate_slug (uppercase) → 422, before any
        store write. This is the path-traversal defense boundary."""
        r = rd_client.patch(
            "/ui/api/notebooks/BadSlug", json={"display_name": "x"}
        )
        assert r.status_code == 422

    def test_rename_over_long_name_422(self, rd_client):
        """D4: a 257-char display_name → 422 via Pydantic Field(max_length=256),
        before the handler body runs."""
        _create_notebook(rd_client, "gamma-nb")
        r = rd_client.patch(
            "/ui/api/notebooks/gamma-nb", json={"display_name": "x" * 257}
        )
        assert r.status_code == 422

    def test_rename_max_len_name_accepted(self, rd_client):
        """Boundary: exactly 256 chars is accepted (off-by-one guard)."""
        _create_notebook(rd_client, "delta-nb")
        r = rd_client.patch(
            "/ui/api/notebooks/delta-nb", json={"display_name": "y" * 256}
        )
        assert r.status_code == 200, r.text

    def test_rename_nonexistent_slug_404(self, rd_client):
        """D4: a valid-format but absent slug → 404 (update returns False)."""
        r = rd_client.patch(
            "/ui/api/notebooks/ghost-nb", json={"display_name": "x"}
        )
        assert r.status_code == 404

    def test_rename_strips_control_chars(self, rd_client):
        """D4 (brief-2 FM-3): NUL / newlines / tabs are stripped before storage
        (single-line field; log-injection defense). The stored + rendered value
        is the de-controlled string."""
        _create_notebook(rd_client, "ctrl-nb")
        r = rd_client.patch(
            "/ui/api/notebooks/ctrl-nb",
            json={"display_name": "Hel\x00lo\n\tWorld\x7f"},
        )
        assert r.status_code == 200, r.text
        assert "HelloWorld" in r.text
        assert "\x00" not in r.text
        assert "\n\t" not in r.text
        # Persisted de-controlled on the detail page too.
        d = rd_client.get("/ui/notebooks/ctrl-nb")
        assert "HelloWorld" in d.text

    def test_rename_escapes_html_xss(self, rd_client):
        """D4: a <script> display_name is html.escape'd in the fragment — no
        raw tag reaches the client (stored-XSS defense; never `| safe`)."""
        _create_notebook(rd_client, "xss-nb")
        r = rd_client.patch(
            "/ui/api/notebooks/xss-nb",
            json={"display_name": "<script>alert(1)</script>"},
        )
        assert r.status_code == 200, r.text
        assert "<script>" not in r.text
        assert "&lt;script&gt;" in r.text
        # Detail-page render is autoescaped too.
        d = rd_client.get("/ui/notebooks/xss-nb")
        assert "<script>alert(1)</script>" not in d.text

    def test_rename_ignores_mass_assignment(self, rd_client):
        """D4: extra body fields (slug/notebook_kind/parse_status) are ignored —
        only display_name is mutated. The original slug is untouched and no new
        notebook is conjured."""
        _create_notebook(rd_client, "mass-nb", display_name="orig", kind="arxiv")
        r = rd_client.patch(
            "/ui/api/notebooks/mass-nb",
            json={
                "display_name": "renamed",
                "slug": "evil-nb",
                "notebook_kind": "textbook",
                "parse_status": "failed",
            },
        )
        assert r.status_code == 200, r.text
        assert "renamed" in r.text
        # Original slug still resolves; the injected "evil-nb" was never created.
        assert rd_client.get("/ui/notebooks/mass-nb").status_code == 200
        assert rd_client.get("/ui/notebooks/evil-nb").status_code == 404
        listing = rd_client.get("/ui/api/notebooks").json()
        slugs = {nb["slug"] for nb in listing}
        assert "mass-nb" in slugs
        assert "evil-nb" not in slugs


class TestDelete:
    def test_delete_round_trip_list_omits_it(self, rd_client):
        """AC2: deleting a notebook removes it; the list re-renders without it
        while a sibling notebook survives."""
        _create_notebook(rd_client, "keep-nb")
        _create_notebook(rd_client, "drop-nb")
        r = rd_client.delete("/ui/api/notebooks/drop-nb")
        assert r.status_code == 204
        listing = rd_client.get("/ui/api/notebooks").json()
        slugs = {nb["slug"] for nb in listing}
        assert "drop-nb" not in slugs
        assert "keep-nb" in slugs

    def test_delete_malformed_slug_422(self, rd_client):
        """The DELETE path-traversal boundary: an invalid slug → 422."""
        r = rd_client.delete("/ui/api/notebooks/BadSlug")
        assert r.status_code == 422

    def test_delete_nonexistent_slug_404(self, rd_client):
        r = rd_client.delete("/ui/api/notebooks/ghost-nb")
        assert r.status_code == 404


class TestDetailPageWiring:
    def test_detail_page_renders_rename_form_and_delete(self, rd_client):
        """The detail page carries the htmx rename form (hx-patch to this
        notebook) + the swap target + the in-page Delete button."""
        _create_notebook(rd_client, "wiring-nb", display_name="Wiring")
        r = rd_client.get("/ui/notebooks/wiring-nb")
        assert r.status_code == 200
        assert 'hx-patch="/ui/api/notebooks/wiring-nb"' in r.text
        assert 'id="display-name-block"' in r.text
        assert 'hx-target="#display-name-block"' in r.text
        assert "Delete notebook" in r.text
        assert 'hx-delete="/ui/api/notebooks/wiring-nb"' in r.text
