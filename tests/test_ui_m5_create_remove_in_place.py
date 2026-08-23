"""ui-attractive-polish-m5 — in-place create + remove + UPL-8 v1 + UPL-19 v1 + m4-F3.

Regression tests for the five m5 items bundled into one milestone:

- **UPL-12 v1 (create-notebook)** — ``POST /ui/api/notebooks`` returns an
  HTML ``<tr>`` fragment when ``HX-Request: true`` (content-negotiation);
  existing JSON branch preserved for curl/non-htmx clients. New
  ``_notebook_row_html`` helper mirrors the m4 ``_paper_row_html``
  precedent (per-value ``html.escape()``; ``lancedb_path`` omitted from
  the HTML branch per the host-path-leak note in
  ``06-mcp-server-design.md``).
- **UPL-12 v1 (remove-notebook)** — ``DELETE /ui/api/notebooks/{slug}``
  returns 200 + empty body when ``HX-Request: true`` so the vendored
  htmx 2.0.10 (which sets ``{code:"204",swap:false}``) actually
  performs the ``hx-swap="outerHTML"`` row removal. The non-htmx path
  keeps the historical 204.
- **UPL-8 v1** — 4 ``.status-badge--*`` modifier classes redeclared
  inside the dark ``@media`` block + a ``th { background: … }`` dark
  redeclaration (``#161b22`` until ui-uplift-m6 pointed it at
  ``var(--card-bg)``, since the literal was a byte-copy of that token).
  All 4 pill pairs verified WCAG-AA-compliant; they are now also covered,
  alongside every other rendered pair, by ``tests/test_ui_contrast.py``.
- **UPL-19 v1** — ``body max-width: 980px`` → ``clamp(640px, 92vw,
  1400px)`` so the papers table breathes on wider monitors.
- **m4-F3** — add-paper form gains
  ``hx-on::htmx:after-request="if(event.detail.successful) this.reset()"``
  so the URL input clears after a successful swap.

The Spike-2 13-item pre-flight checklist applies TWICE in m5 (once per
new fragment endpoint). The test classes below mechanically verify each
checklist item for both create AND delete.
"""

from __future__ import annotations

import asyncio
import re as _re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import (
    _notebook_row_html,
)
from server.routes.notebooks import (
    router as notebooks_router,
)
from server.routes.ui import router as ui_router

# ui-uplift-m6 rectify (critique M5): this file used to define its own
# `_hex_to_rgb` / `_relative_luminance` / `_contrast_ratio` on the 0.03928
# branch threshold, while `tests/_ui_color.py` claimed in its docstring to be
# "the repo's single WCAG-contrast implementation". Two calculators on two
# different thresholds is the precise hazard that module was created to end.
# They could not actually diverge on any hex input (no 8-bit channel falls
# between 0.03928 and the 0.04045 the shared module uses), which is exactly
# why the duplicate could sit here indefinitely without a failing test.
from tests._ui_color import contrast_ratio as _contrast_ratio
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "server" / "frontend" / "static"
FRONTEND_TEMPLATES: Path = REPO_ROOT / "server" / "frontend" / "templates"

APP_CSS: str = (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8")
APP_CSS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", APP_CSS, flags=_re.S)
INDEX_HTML: str = (FRONTEND_TEMPLATES / "index.html").read_text(encoding="utf-8")
NOTEBOOK_DETAIL_HTML: str = (
    FRONTEND_TEMPLATES / "notebook_detail.html"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test fixture (mirrors tests/test_ui_m4_in_place_add_paper.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def m5_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Minimal app (notebooks + ui routers + static) + real NotebooksStore."""
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(
        notebooks_module, "_now_iso", lambda: "2026-05-31T18:00:00+00:00"
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


# ---------------------------------------------------------------------------
# UPL-12 v1 — _notebook_row_html helper (per-value html.escape; XSS test)
# ---------------------------------------------------------------------------


class TestUPL12V1NotebookRowHtml:
    """``_notebook_row_html`` per-value ``html.escape()`` is load-bearing."""

    def test_basic_row_renders_correct_schema(self) -> None:
        out = _notebook_row_html(
            slug="bridgeland",
            display_name="Bridgeland stability",
            notebook_kind="arxiv",
            created_at="2026-05-31T18:00:00+00:00",
        )
        # 4-column schema: Slug / Display name / Created / Actions
        assert '<tr data-slug="bridgeland">' in out
        assert "<td><code>bridgeland</code></td>" in out
        assert "<td>Bridgeland stability</td>" in out
        assert (
            "<td><time>2026-05-31T18:00:00+00:00</time></td>" in out
        )
        # Actions cell: Open link, NO Remove button (m4 precedent —
        # next page-load restores the standard Remove affordance).
        assert (
            '<a href="/ui/notebooks/bridgeland" class="button">Open</a>'
            in out
        )
        assert "Remove" not in out
        assert "hx-delete" not in out

    def test_empty_display_name_renders_em_dash(self) -> None:
        # Mirrors the template's `{{ nb.display_name or "—" }}`.
        for empty in ("", None):
            out = _notebook_row_html(
                slug="nb",
                display_name=empty,
                notebook_kind="arxiv",
                created_at="2026-05-31T18:00:00+00:00",
            )
            assert "<td>—</td>" in out

    def test_lancedb_path_never_leaks_into_fragment(self) -> None:
        # 06-mcp-server-design.md note: lancedb_path is a host-path
        # info-leak; the HTML branch MUST omit it. Verified by absence
        # in the rendered fragment (the helper signature doesn't even
        # accept lancedb_path — defense in depth).
        out = _notebook_row_html(
            slug="nb",
            display_name="x",
            notebook_kind="arxiv",
            created_at="2026-05-31T18:00:00+00:00",
        )
        assert "lancedb_path" not in out
        assert "/var/" not in out
        assert "lancedb" not in out

    def test_all_interpolated_values_html_escaped(self) -> None:
        # Spike-2 pre-flight item #1: server-fragment correctness.
        # Every interpolated value MUST go through html.escape().
        out = _notebook_row_html(
            slug='nb"x',  # HTML-significant in attribute context
            display_name='<img src=x onerror=alert(1)>',  # XSS payload
            notebook_kind="arxiv",
            created_at='ts"&<',  # all three HTML-significant chars
        )
        # XSS payload chars escaped.
        assert "&lt;img" in out
        assert "onerror=alert(1)" in out or "onerror=alert(1)&gt;" in out
        # Raw payload absent.
        assert "<img src=x" not in out
        # The slug's " → &quot;
        assert "&quot;" in out
        # The created_at &<> all escaped.
        assert "&amp;" in out
        assert "&lt;" in out


# ---------------------------------------------------------------------------
# UPL-12 v1 (create) — Spike-2 pre-flight checklist
# ---------------------------------------------------------------------------


class TestUPL12V1CreatePreFlightChecklist:
    """Spike-2 pre-flight checklist applied to ``POST /ui/api/notebooks``."""

    def test_create_hx_request_returns_html_fragment(
        self, m5_client: TestClient
    ) -> None:
        r = m5_client.post(
            "/ui/api/notebooks",
            json={
                "slug": "test-nb",
                "display_name": "Test Notebook",
                "notebook_kind": "arxiv",
            },
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 201, r.text
        assert "text/html" in r.headers.get("content-type", "").lower()
        text = r.text
        assert '<tr data-slug="test-nb">' in text
        assert "<td><code>test-nb</code></td>" in text
        assert "<td>Test Notebook</td>" in text
        # Spike-2 #4: lancedb_path absent from the fragment.
        assert "lancedb_path" not in text

    def test_create_no_hx_request_returns_json(
        self, m5_client: TestClient
    ) -> None:
        # Content-negotiation: absent HX-Request → JSON path preserved.
        # The JSON branch DOES still include lancedb_path for scripted
        # callers (backwards compat).
        r = m5_client.post(
            "/ui/api/notebooks",
            json={
                "slug": "test-json",
                "display_name": "Test JSON",
                "notebook_kind": "arxiv",
            },
        )
        assert r.status_code == 201, r.text
        assert "application/json" in r.headers.get("content-type", "").lower()
        body = r.json()
        assert body["slug"] == "test-json"
        assert body["display_name"] == "Test JSON"
        assert "lancedb_path" in body  # JSON branch DOES leak this
        assert body["notebook_kind"] == "arxiv"

    def test_create_slug_validation_precedes_response_fork(
        self, m5_client: TestClient
    ) -> None:
        # Spike-2 #8: validate_slug runs BEFORE the renderer is reached.
        # A bad slug → 422 BEFORE any fragment can be rendered.
        r = m5_client.post(
            "/ui/api/notebooks",
            json={
                "slug": "INVALID UPPER",
                "display_name": "x",
                "notebook_kind": "arxiv",
            },
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 422, r.text

    def test_create_duplicate_slug_returns_409_no_fragment(
        self, m5_client: TestClient
    ) -> None:
        # First create succeeds.
        m5_client.post(
            "/ui/api/notebooks",
            json={"slug": "dup", "display_name": "x", "notebook_kind": "arxiv"},
        )
        # Second with same slug → 409, NOT a fragment.
        r = m5_client.post(
            "/ui/api/notebooks",
            json={"slug": "dup", "display_name": "x", "notebook_kind": "arxiv"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 409
        assert "<tr" not in r.text

    def test_create_xss_payload_escaped_in_fragment(
        self, m5_client: TestClient
    ) -> None:
        # Spike-2 #4 + test surface: hostile display_name escapes.
        r = m5_client.post(
            "/ui/api/notebooks",
            json={
                "slug": "xss-test",
                "display_name": "<img src=x onerror=alert(1)>",
                "notebook_kind": "arxiv",
            },
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 201, r.text
        text = r.text
        # Escaped form present; raw payload absent.
        assert "&lt;img" in text
        assert "<img src=x" not in text

    def test_create_hx_request_case_sensitive_check(
        self, m5_client: TestClient
    ) -> None:
        # m4 precedent: only HX-Request="true" exactly (lowercased by
        # Starlette as "hx-request" header lookup). Other values fall
        # through to JSON.
        r = m5_client.post(
            "/ui/api/notebooks",
            json={"slug": "case-test", "display_name": "x", "notebook_kind": "arxiv"},
            headers={"HX-Request": "True"},  # capital T
        )
        assert r.status_code == 201
        # Starlette normalizes header NAME case but NOT value case;
        # the handler checks == "true" so "True" should fall through
        # to JSON.
        assert "application/json" in r.headers.get("content-type", "").lower()

    def test_create_textbook_kind_returns_same_fragment_shape(
        self, m5_client: TestClient
    ) -> None:
        # m5-rect F4: ``_notebook_row_html`` accepts ``notebook_kind``
        # but DROPS it from the rendered fragment (the index.html
        # template doesn't show kind today). Verify the textbook-kind
        # code path through the HTML branch produces a fragment
        # visually indistinguishable from the arxiv-kind case AND
        # does NOT leak the upstream ``parse_status="pending"`` flag
        # (which the create handler sets at notebooks.py:300-302 for
        # textbook-kind notebooks). Regression guard against a future
        # template adding a kind column expecting the helper to
        # render it.
        r = m5_client.post(
            "/ui/api/notebooks",
            json={
                "slug": "tb-nb",
                "display_name": "Hartshorne",
                "notebook_kind": "textbook",
            },
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 201, r.text
        assert "text/html" in r.headers.get("content-type", "").lower()
        text = r.text
        # 4-column schema, same as arxiv (no kind column today).
        assert '<tr data-slug="tb-nb">' in text
        assert "<td><code>tb-nb</code></td>" in text
        assert "<td>Hartshorne</td>" in text
        # Kind is dropped from the row — accepted by helper signature
        # but unused (per the helper docstring's future-proofing note).
        assert "textbook" not in text
        # parse_status NOT leaked into the HTML branch either.
        assert "pending" not in text
        assert "parse_status" not in text


# ---------------------------------------------------------------------------
# UPL-12 v1 (create) — index.html template changes
# ---------------------------------------------------------------------------


class TestUPL12V1CreateTemplateChanges:
    """``index.html`` create-form swap + tbody rename + empty placeholder."""

    def test_tbody_renamed_to_notebooks_tbody(self) -> None:
        # Spike-2 C2: rename id="notebook-list" → id="notebooks-tbody"
        # for naming consistency with #papers-tbody.
        assert 'id="notebooks-tbody"' in INDEX_HTML
        assert 'id="notebook-list"' not in INDEX_HTML

    def test_tbody_has_aria_live_polite(self) -> None:
        # m1 UPL-3: aria-live="polite" on the swap-target tbody so
        # screen readers announce the create swap-in.
        m = _re.search(
            r'<tbody\b[^>]*id="notebooks-tbody"[^>]*>', INDEX_HTML
        )
        if m is None:
            raise AssertionError(
                'expected <tbody id="notebooks-tbody"> element in index.html'
            )
        assert 'aria-live="polite"' in m.group(0)

    def test_create_form_uses_in_place_swap_not_location_reload(self) -> None:
        # Negative regression: the legacy location.reload() flow is gone.
        # The create form gets hx-target + hx-swap + a multi-statement
        # success hook (remove empty placeholder + this.reset()).
        # Strip Jinja2 comments to avoid false-positives on doc prose.
        no_jinja = _re.sub(r"\{#.*?#\}", "", INDEX_HTML, flags=_re.DOTALL)
        # Find the create-notebook form (POSTs to /ui/api/notebooks, NOT
        # the per-paper sub-route).
        m = _re.search(
            r'<form\b[^>]*hx-post="/ui/api/notebooks"[^>]*>', no_jinja
        )
        assert m is not None
        form_attrs = m.group(0)
        assert 'hx-target="#notebooks-tbody"' in form_attrs
        assert 'hx-swap="beforeend"' in form_attrs
        # #431: the success hook moved from an inline hx-on::after-request
        # (dead under the console's CSP — htmx compiles it with new Function)
        # to a declarative token ui.js acts on. Same two behaviours, asserted
        # by name; tests/test_ui_delegated_listeners.py pins the token set.
        # Assert the BEHAVIOURS, not the literal token list — #450 appended
        # `recount:` and an exact-match assertion would have blocked it.
        tokens = _re.search(r'data-on-success="([^"]*)"', form_attrs)
        assert tokens is not None, form_attrs
        declared = tokens.group(1).split()
        assert "remove:#notebooks-empty" in declared, declared
        assert "reset" in declared, declared
        assert "hx-on::" not in form_attrs, (
            "hx-on:: is dead under this CSP (no 'unsafe-eval') — see #431"
        )
        # m1 UPL-3 / Spike-2 #8: m3-era hx-disabled-elt preserved.
        assert 'hx-disabled-elt="find button"' in form_attrs
        # No location.reload on the create form.
        assert "location.reload" not in form_attrs

    def test_empty_state_placeholder_inside_tbody(self) -> None:
        # The empty-state message MOVED inside the tbody as a
        # 4-column-spanning placeholder row (#notebooks-empty) so the
        # create form's success hook can .remove() it.
        assert 'id="notebooks-empty"' in INDEX_HTML
        assert 'colspan="4"' in INDEX_HTML


# ---------------------------------------------------------------------------
# UPL-12 v1 (delete) — Spike-2 pre-flight checklist
# ---------------------------------------------------------------------------


class TestUPL12V1DeletePreFlightChecklist:
    """Spike-2 pre-flight applied to ``DELETE /ui/api/notebooks/{slug}``."""

    def _create(self, c: TestClient, slug: str) -> None:
        r = c.post(
            "/ui/api/notebooks",
            json={"slug": slug, "display_name": "x", "notebook_kind": "arxiv"},
        )
        assert r.status_code == 201, r.text

    def test_delete_hx_request_returns_200_empty_body(
        self, m5_client: TestClient
    ) -> None:
        # htmx 2.0.10 ignores 204 (responseHandling
        # {code:"204",swap:false}); the HX-Request branch MUST return
        # 200 + empty body so hx-swap="outerHTML" removes the row.
        self._create(m5_client, "to-delete")
        r = m5_client.delete(
            "/ui/api/notebooks/to-delete",
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200, r.text
        assert r.text == "" or r.content == b""

    def test_delete_no_hx_request_preserves_204(
        self, m5_client: TestClient
    ) -> None:
        # The non-htmx path keeps the historical 204 — important so
        # existing JSON-direct tests (test_notebook_api.py:139 +
        # test_notebook_rename_delete.py:256) don't break.
        self._create(m5_client, "to-delete-json")
        r = m5_client.delete("/ui/api/notebooks/to-delete-json")
        assert r.status_code == 204
        assert r.content == b""

    def test_delete_slug_validation_precedes_fork(
        self, m5_client: TestClient
    ) -> None:
        # validate_slug MUST run before any branch reaches the renderer.
        # A bad slug → 422 BEFORE the 200/204 fork can fire.
        r = m5_client.delete(
            "/ui/api/notebooks/INVALID UPPER",
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 422, r.text

    def test_delete_404_on_missing_slug_for_both_branches(
        self, m5_client: TestClient
    ) -> None:
        # 404 check runs BEFORE the HX-Request fork — verified for
        # both branches.
        for headers in ({}, {"HX-Request": "true"}):
            r = m5_client.delete("/ui/api/notebooks/never-existed", headers=headers)
            assert r.status_code == 404, (r.text, headers)

    def test_delete_path_traversal_rejected_before_renderer(
        self, m5_client: TestClient
    ) -> None:
        # Spike-2 #10: path-traversal slug → 422 (URL-encoded by the
        # client) or 404 (route-not-matched) — never reaches the
        # row-removal fragment.
        r = m5_client.delete(
            "/ui/api/notebooks/..%2F..%2F..%2Fetc%2Fpasswd",
            headers={"HX-Request": "true"},
        )
        assert r.status_code in (404, 422), r.text


# ---------------------------------------------------------------------------
# UPL-12 v1 (delete) — index.html + notebook_detail.html template changes
# ---------------------------------------------------------------------------


class TestUPL12V1DeleteTemplateChanges:
    """Remove buttons get hx-target + hx-swap; delete-notebook button stays."""

    def test_index_remove_button_uses_closest_tr_swap(self) -> None:
        # Inside index.html's notebooks tbody, the Remove button gets
        # hx-target="closest tr" + hx-swap="outerHTML swap:200ms" so
        # htmx removes the row in place after the 200ms fade.
        # Find the button via its hx-delete attr.
        m = _re.search(
            r'<button[^>]*hx-delete="/ui/api/notebooks/\{\{ nb\.slug \}\}"[^>]*>',
            INDEX_HTML,
            flags=_re.DOTALL,
        )
        assert m is not None
        btn = m.group(0)
        assert 'hx-target="closest tr"' in btn
        assert 'hx-swap="outerHTML swap:200ms"' in btn
        # Legacy location.reload hook is gone from THIS button.
        assert "location.reload" not in btn

    def test_notebook_detail_delete_button_unchanged(self) -> None:
        # Spike-2 C6: the delete-notebook button in notebook_detail.html
        # is inside <div class="notebook-actions">, NOT a <tr> ancestor.
        # It MUST stay on its window.location.href navigation; applying
        # closest-tr would silently no-op.
        idx = NOTEBOOK_DETAIL_HTML.index('class="notebook-actions"')
        block = NOTEBOOK_DETAIL_HTML[idx : idx + 800]
        # #431: the navigation moved from an inline hx-on::after-request to
        # the declarative `navigate:` token. The Spike-2 C6 property this
        # guards is unchanged — this button navigates and must NOT use the
        # closest-tr removal that the in-<tr> buttons use.
        assert 'data-on-success="navigate:/ui/"' in block
        # Critical negative regression: must NOT have closest tr.
        assert "closest tr" not in block
        assert "remove-closest:tr" not in block

    def test_index_no_legacy_location_reload_on_remove_button(self) -> None:
        # Belt-and-braces: zero `location.reload` calls survive in
        # index.html (both the create form AND the remove button were
        # converted; the only remaining hooks are the new ones). Strip
        # Jinja2 comments first so the documentation prose
        # ("the legacy location.reload() flow") doesn't false-positive.
        no_jinja = _re.sub(r"\{#.*?#\}", "", INDEX_HTML, flags=_re.DOTALL)
        assert "location.reload" not in no_jinja


# ---------------------------------------------------------------------------
# UPL-8 v1 — dark-mode pill remap + th surface + programmatic contrast check
# ---------------------------------------------------------------------------


class TestUPL8V1DarkModePillContrast:
    """Programmatic WCAG verification for the m5 dark-mode pill palette."""

    PILLS = [
        ("--ok", "#0d2818", "#3fb950"),
        ("--warn", "#3d2a07", "#d29922"),
        ("--ops-warn", "#1c2230", "#8b949e"),
        ("--down", "#3d1216", "#f85149"),
    ]

    def test_all_pills_present_in_dark_block(self) -> None:
        # Find the dark @media block, then assert each pill is
        # redeclared inside it.
        dark_block_re = _re.compile(
            r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        m = dark_block_re.search(APP_CSS_NO_COMMENTS)
        assert m is not None
        dark = m.group(1)
        for name, bg, fg in self.PILLS:
            assert f".status-badge{name}" in dark, name
            assert f"background: {bg}" in dark, (name, bg)
            assert f"color: {fg}" in dark, (name, fg)

    def test_th_background_is_the_token_in_every_mode(self) -> None:
        """UPL-8 v1's intent, satisfied more strongly than by the mechanism
        it originally used — renamed from ``test_th_dark_background_redeclared``
        because the mechanism is what changed.

        THE INTENT: the light ``#f0f0f0`` table header must never show
        against the dark canvas. UPL-8 v1 got that with a dark-block
        redeclaration; ui-uplift-m6 pointed that redeclaration at
        ``var(--card-bg)`` so it could not drift (it had been a byte-copy of
        the old dark ``--card-bg``, ``#161b22``).

        ui-uplift-m8 closes it at the source instead. AC#2 re-roles
        ``--card-bg`` as the CONTROL GROUND, ``th`` is a control surface, so
        the BASE rule names the token and the dark redeclaration is deleted
        as dead code. Asserting the old mechanism now would pin a rule whose
        only job was to fix a literal that no longer exists.

        Both halves are checked, because half of this is a negative: the
        token is named once, unconditionally, and NO light hex literal
        remains as a ``th`` background anywhere in the sheet.
        """
        th_bg = _re.findall(r"\bth[^{}]*\{[^}]*?background:\s*([^;}]+)",
                            APP_CSS_NO_COMMENTS)
        assert th_bg, "no `th { background: ... }` rule found at all"
        for value in th_bg:
            assert value.strip() == "var(--card-bg)", (
                f"th renders background {value.strip()!r}. It must be the "
                f"--card-bg token in EVERY mode — a light hex literal here "
                f"is what UPL-8 v1's dark redeclaration existed to hide, and "
                f"ui-uplift-m8 removed that redeclaration by removing the "
                f"literal. Two modes must not disagree about this surface."
            )
        dark_block_re = _re.compile(
            r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        m = dark_block_re.search(APP_CSS_NO_COMMENTS)
        assert m is not None
        assert not _re.search(r"\bth\s*\{", m.group(1)), (
            "the dark @media block redeclares `th` again. Since the base rule "
            "is token-tracked this can only re-introduce drift between modes."
        )

    @pytest.mark.parametrize(("name", "bg", "fg"), PILLS)
    def test_pill_contrast_passes_wcag_aa(
        self, name: str, bg: str, fg: str
    ) -> None:
        # SC 1.4.3: 4.5:1 for normal text on the pill background.
        ratio = _contrast_ratio(fg, bg)
        assert ratio >= 4.5, (
            f"{name}: contrast {ratio:.2f} fails SC 1.4.3 (need ≥ 4.5:1) "
            f"for {fg} on {bg}"
        )

    def test_pill_text_color_also_visible_on_canvas(self) -> None:
        # SC 1.4.11: 3:1 for the border/text vs the surrounding canvas
        # (so the pill silhouette is distinguishable even outside
        # its background fill).
        #
        # ui-uplift-m6: the canvas is now PARSED from the stylesheet. It
        # used to be the Python literal `canvas = "#0d1117"`, a duplicate
        # of dark --bg — when that token was re-derived this test would not
        # have failed, it would have silently kept validating against a
        # ground the product no longer paints.
        from tests._ui_color import load_tokens

        _light, dark = load_tokens()
        canvas = dark["--bg"]
        for name, _bg, fg in self.PILLS:
            ratio = _contrast_ratio(fg, canvas)
            assert ratio >= 3.0, (
                f"{name}: border-color {fg} on canvas {canvas} = "
                f"{ratio:.2f}, fails SC 1.4.11 (need ≥ 3:1)"
            )

    def test_uniform_single_color_pill_pattern(self) -> None:
        # Synthesis C7: m5 simplifies all 4 pills to single-color
        # (text == border-color) in dark mode. Verify by reading the
        # declarations.
        dark_block_re = _re.compile(
            r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        m = dark_block_re.search(APP_CSS_NO_COMMENTS)
        assert m is not None
        dark = m.group(1)
        for name, _bg, fg in self.PILLS:
            # The declaration should have `color: <fg>; border-color: <fg>;`
            # — both reference the same value.
            rule_re = _re.compile(
                rf"\.status-badge{_re.escape(name)}\s*\{{[^}}]*"
                rf"color:\s*{_re.escape(fg)}[^}}]*"
                rf"border-color:\s*{_re.escape(fg)}",
                flags=_re.S,
            )
            assert rule_re.search(dark), (
                f"{name}: dark-mode rule should set both color AND "
                f"border-color to {fg} (single-color uniformity)"
            )


# ---------------------------------------------------------------------------
# UPL-19 v1 — body { max-width: clamp(640px, 92vw, 1400px) }
# ---------------------------------------------------------------------------


class TestUPL19V1BodyClamp:
    """``body`` rule swaps 980px ceiling for ``clamp(640px, 92vw, 1400px)``."""

    def test_body_max_width_uses_clamp(self) -> None:
        # Find the body rule and confirm clamp() is present.
        m = _re.search(
            r"body\s*\{[^}]*max-width:\s*clamp\(\s*640px\s*,\s*92vw\s*,\s*1400px\s*\)",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        )
        assert m is not None, "body max-width: clamp(640px, 92vw, 1400px) not found"

    def test_legacy_980px_ceiling_removed(self) -> None:
        # Negative regression: the old `max-width: 980px` is gone from
        # the body rule. (We scope to the body block to avoid matching
        # any 980px that might legitimately appear elsewhere.)
        m = _re.search(
            r"body\s*\{[^}]*\}",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        )
        assert m is not None
        body_block = m.group(0)
        assert "max-width: 980px" not in body_block


# ---------------------------------------------------------------------------
# UPL-12 v1 — row-fade keyframe gated by prefers-reduced-motion: no-preference
# ---------------------------------------------------------------------------


class TestUPL12V1RowFadeKeyframe:
    """``tr.htmx-swapping`` row-fade lives inside the existing reduced-motion block."""

    def test_row_fade_keyframe_present(self) -> None:
        assert "@keyframes row-fade-out" in APP_CSS_NO_COMMENTS
        # The keyframe definition itself.
        assert "from { opacity: 1; }" in APP_CSS_NO_COMMENTS
        assert "to   { opacity: 0; }" in APP_CSS_NO_COMMENTS

    def test_row_fade_gated_by_prefers_reduced_motion_no_preference(
        self,
    ) -> None:
        # The keyframe + selector MUST live inside the existing
        # @media (prefers-reduced-motion: no-preference) block; reduced-
        # motion users get the universal clamp instead.
        # Find the no-preference block via regex and confirm the
        # selector + keyframe both appear inside it.
        no_pref_re = _re.compile(
            r"@media\s*\(\s*prefers-reduced-motion:\s*no-preference\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        # There may be more than one no-preference block; check ALL.
        blocks = no_pref_re.findall(APP_CSS_NO_COMMENTS)
        assert blocks, "no @media (prefers-reduced-motion: no-preference) block found"
        # Find the block containing the row-fade rule.
        relevant = [b for b in blocks if "tr.htmx-swapping" in b]
        assert relevant, (
            "tr.htmx-swapping rule must live inside a "
            "@media (prefers-reduced-motion: no-preference) block — "
            "reduced-motion users get the universal clamp instead"
        )
        block = relevant[0]
        # The keyframe should also live inside this block (or a sibling
        # no-preference block). Per m4 consolidation pattern, the
        # synthesis says it consolidates with badge-flash + view-
        # transition. Verify.
        assert "@keyframes row-fade-out" in block

    def test_row_fade_animation_fill_mode_forwards(self) -> None:
        # The animation MUST set animation-fill-mode: forwards so the
        # row stays at opacity 0 through the settle phase (otherwise
        # it would flash back to opaque before being removed by htmx).
        m = _re.search(
            r"tr\.htmx-swapping\s*\{[^}]+\}",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        )
        assert m is not None
        rule = m.group(0)
        assert "forwards" in rule
        # And the duration must match the swap:200ms modifier in
        # index.html. ui-uplift-m6 replaced the literal with
        # var(--dur-fast), so resolve the token rather than pinning the
        # spelling — the numeric coupling is what matters.
        from tests._ui_color import load_raw_tokens

        assert "var(--dur-fast)" in rule
        base_tokens, _dark = load_raw_tokens()
        assert base_tokens["--dur-fast"] == "200ms", (
            f"--dur-fast is {base_tokens['--dur-fast']} but index.html's "
            f"hx-swap modifier is swap:200ms; they must stay in sync."
        )


# ---------------------------------------------------------------------------
# m4-F3 — add-paper form `this.reset()` on success
# ---------------------------------------------------------------------------


class TestM4F3FormReset:
    """``notebook_detail.html`` add-paper form gains the m4-F3 reset hook."""

    def test_add_paper_form_has_this_reset_hook(self) -> None:
        # Find the add-paper form (POSTs to /ui/api/notebooks/{slug}/
        # papers — NOT /papers/upload).
        m = _re.search(
            r'<form\b[^>]*hx-post="/ui/api/notebooks/\{\{ notebook\.slug \}\}/papers"[^>]*>',
            NOTEBOOK_DETAIL_HTML,
            flags=_re.DOTALL,
        )
        assert m is not None
        form_attrs = m.group(0)
        # The reset hook is present. #431 moved it from an inline
        # hx-on::after-request to the declarative token ui.js acts on.
        assert 'data-on-success="reset"' in form_attrs
        # m4 negative regression: location.reload still absent.
        assert "location.reload" not in form_attrs


# ---------------------------------------------------------------------------
# Cross-milestone safety (m1 / m2 / m3 / m4 surfaces intact + cap = 370)
# ---------------------------------------------------------------------------


class TestCrossMilestoneSafety:
    """m5 doesn't disturb m1 / m2 / m3 / m4 sites."""

    def test_m1_prefers_reduced_motion_reduce_block_still_present(self) -> None:
        assert "@media (prefers-reduced-motion: reduce)" in APP_CSS_NO_COMMENTS

    def test_m1_focus_visible_still_present(self) -> None:
        assert ":focus-visible" in APP_CSS_NO_COMMENTS

    def test_m2_color_mix_button_hover_still_present(self) -> None:
        idx = APP_CSS_NO_COMMENTS.index("button:hover")
        rule_block = APP_CSS_NO_COMMENTS[idx : idx + 300]
        assert "color-mix(in oklab" in rule_block

    def test_m2_table_wrap_overflow_still_present(self) -> None:
        # UPL-19 v1 widens body but m2's .table-wrap MUST still handle
        # sub-640px viewports (the floor of clamp()).
        assert ".table-wrap { overflow-x: auto; }" in APP_CSS_NO_COMMENTS

    def test_m3_dark_mode_block_still_present(self) -> None:
        assert "@media (prefers-color-scheme: dark)" in APP_CSS_NO_COMMENTS

    def test_m4_view_transition_pseudo_elements_still_present(self) -> None:
        # UPL-13 (m4) still active — m5 ADDED to the no-preference
        # block, didn't replace UPL-13's contents.
        assert "::view-transition-old(root)" in APP_CSS_NO_COMMENTS
        assert "::view-transition-new(root)" in APP_CSS_NO_COMMENTS

    def test_m4_badge_flash_still_present(self) -> None:
        # UPL-22 still active.
        assert ".status-badge.htmx-settling" in APP_CSS_NO_COMMENTS
        assert "@keyframes badge-flash" in APP_CSS_NO_COMMENTS

    def test_m4_paper_row_html_still_present(self) -> None:
        # Sanity check: importing _paper_row_html still works.
        from server.routes.notebooks import _paper_row_html

        out = _paper_row_html(
            slug="x", paper_id="1.1", added_at="2026-05-31T18:00:00+00:00"
        )
        assert "<td>added</td>" in out

    def test_app_css_under_m5_cap(self) -> None:
        # Cap = 600 (ui-uplift-m6 raised 400 → 480 for the OKLCH token
        # family + --dur-* tokens + their per-token derivation rationale).
        # This test mirrors the cap-tests in m3 and m4 test files — all
        # three MUST move in lockstep on a future cap raise.
        # ui-uplift-m7: cap UNCHANGED. The type scale fit because m7 moved
        # both :root blocks into server/frontend/static/tokens.css — the
        # documented split, taken instead of a fourth raise. All three caps
        # still measure app.css, so the lockstep rule is untouched.
        line_count = APP_CSS.count("\n") + (
            1 if not APP_CSS.endswith("\n") else 0
        )
        # ui-uplift-m7 RECTIFY: 480 -> 520, in lockstep across all three
        # files. Two reasons, both recorded rather than assumed:
        #  1. The m7 comment claimed the tokens split "dropped app.css from
        #     471 to ~400". It did not — the split removed the token blocks
        #     but the type scale added rules and rationale back, landing at
        #     478 of 480 (critique M1). Two lines of headroom is not a
        #     budget: the m7 rectify's four fixes overflowed it immediately.
        #  2. Post-split the cap bounds a PURE RULE SHEET; tokens.css carries
        #     its own separate bound. 520 restores roughly the working margin
        #     480 gave the pre-split file.
        # The cap is a discipline, not a dare — raise it deliberately and say
        # why, which m6 (400 -> 480) also did.
        # ui-uplift-m10: 520 -> 600, in lockstep. UPL-9's eight class rules
        # (.discover-* + .topic-*, the last of the BAN-R2 debt) plus two
        # recorded refusals do not fit 22 lines, and the tokens-split hatch
        # is spent. Merits argued on the m3 cap test; app.css was 575 AS OF
        # m10 — a historical record of that decision, not a live count.
        # ui-uplift-m12: 600 -> 680, in lockstep. The Manage disclosure
        # (UPL-1) is a third top-level region and needs the nested rule ladder
        # `main >`'s direct-child combinator no longer reaches. Merits argued
        # on the m3 cap test. No absolute line count here (m12 M3/L3) —
        # this read "file lands at 635" while it was 627.
        # issues #431/#433 (2026-08-22): 680 -> 690, in lockstep. The
        # server-unreachable banner is a genuinely new component, and it
        # was already minimised to three lines by reusing .error's surface
        # rather than defining a second themed box (m8's rule ladder
        # forbids the border + radius a standalone banner would want).
        assert line_count <= 690, (
            f"app.css is {line_count} lines — over the 690-line cap"
        )