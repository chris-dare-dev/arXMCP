"""ui-htmx-json-fix-m1 — htmx JSON request-body serialization contract.

These are **template-introspection** regression guards, NOT a real browser
test. The repo has no JS runtime / Node, so this asserts the *structural*
contract that makes browser-level htmx JSON serialization work. A true
end-to-end check would require driving a browser (the bug these guards exist
for was found exactly that way, by driving the live `/ui/` console in a
browser — the JSON-direct route tests never caught it because they POST JSON
straight to FastAPI and bypass htmx's client-side serialization entirely).

What the guards encode:

- **Bug 1 (BLOCKER):** the create-notebook / add-paper / discover / ingest /
  rename / topic forms send JSON via the `json-enc` htmx extension's
  `encodeParameters` hook — NOT via the removed inline `evt.detail.body`
  shim (htmx 2.0.10 has no such hook, so that shim sent an empty body and
  FastAPI 422'd). The multipart upload form and bodyless DELETE controls
  must NOT carry `hx-ext="json-enc"`.
- **Bug 2 (cosmetic):** `htmx.config.globalViewTransitions` is set inside a
  `DOMContentLoaded` handler (so htmx is defined when it runs), not in a
  no-op inline `<script defer>` block.

If any guard fails, a future edit has either reintroduced the empty-body bug
or regressed the multipart/DELETE exclusions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND: Path = REPO_ROOT / "server" / "frontend"
TEMPLATES: Path = FRONTEND / "templates"
STATIC: Path = FRONTEND / "static"

BASE_HTML: str = (TEMPLATES / "base.html").read_text(encoding="utf-8")
INDEX_HTML: str = (TEMPLATES / "index.html").read_text(encoding="utf-8")
#: #431: the console's behaviour moved out of base.html into this file.
UI_JS: str = (STATIC / "ui.js").read_text(encoding="utf-8")
DETAIL_HTML: str = (TEMPLATES / "notebook_detail.html").read_text(encoding="utf-8")


def _strip_comments(html: str) -> str:
    """Remove HTML ``<!-- -->`` and Jinja ``{# #}`` comments.

    The base template carries explanatory comments that quote the very code
    strings these guards assert the ABSENCE / POSITION of (e.g. a comment
    explaining why the old ``htmx:configRequest`` / ``evt.detail.body`` shim
    was removed). Structural assertions must run against code only, not prose.
    """
    no_html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r"\{#.*?#\}", "", no_html, flags=re.S)


#: base.html with comments removed — the canonical surface for "is this code
#: pattern present / absent / correctly placed" assertions.
BASE_CODE: str = _strip_comments(BASE_HTML)

#: Every <form ...> opening tag in a template (spans newlines; `[^>]` already
#: excludes '>', and none of these forms put a literal '>' inside an attribute
#: value, so the first '>' terminates the tag correctly).
_FORM_OPEN_RE = re.compile(r"<form\b[^>]*?>")


def _form_tag_containing(html: str, needle: str) -> str:
    """Return the single <form> opening tag whose attributes contain ``needle``."""
    matches = [t for t in _FORM_OPEN_RE.findall(html) if needle in t]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one <form> opening tag containing {needle!r}, "
            f"found {len(matches)}"
        )
    return matches[0]


# ---------------------------------------------------------------------------
# Bug 1 — the broken inline shim is gone from base.html
# ---------------------------------------------------------------------------


class TestBrokenShimRemoved:
    def test_no_evt_detail_body_assignment(self) -> None:
        # htmx 2.0.10 has no evt.detail.body hook; the assignment was a no-op
        # that left parameters cleared → empty body. Run against comment-
        # stripped code so the historical mention in the explanatory comment
        # does not false-positive.
        assert not re.search(r"evt\.detail\.body\s*=", BASE_CODE), (
            "the broken `evt.detail.body =` shim must be removed from base.html"
        )

    def test_no_parameters_cleared(self) -> None:
        # The old shim also did `evt.detail.parameters = {}`, which would
        # sabotage the extension's encodeParameters if left behind.
        assert not re.search(r"evt\.detail\.parameters\s*=\s*\{\s*\}", BASE_CODE)

    def test_no_inline_configrequest_listener_in_base(self) -> None:
        # The htmx:configRequest handling now lives in the json-enc extension
        # file, not inlined in base.html (comment prose may still mention it).
        assert "htmx:configRequest" not in BASE_CODE


# ---------------------------------------------------------------------------
# Bug 1 — the json-enc extension exists and is correct
# ---------------------------------------------------------------------------


class TestJsonEncExtension:
    def test_extension_file_exists(self) -> None:
        assert (STATIC / "json-enc.js").is_file(), (
            "frontend/static/json-enc.js missing"
        )

    def test_extension_defines_json_enc(self) -> None:
        js = (STATIC / "json-enc.js").read_text(encoding="utf-8")
        assert "defineExtension" in js
        assert "json-enc" in js

    def test_extension_uses_encode_parameters_hook(self) -> None:
        # encodeParameters is the real htmx-2.x body-override point (returns
        # the request body string). This is the whole fix.
        js = (STATIC / "json-enc.js").read_text(encoding="utf-8")
        assert "encodeParameters" in js

    def test_extension_iterates_formdata_not_stringify_directly(self) -> None:
        # htmx 2.x passes a FormData as `parameters`. JSON.stringify(parameters)
        # on a FormData yields "{}" (the htmx-1.x json-enc bug). The fix MUST
        # iterate with .forEach and stringify the accumulated object.
        js = (STATIC / "json-enc.js").read_text(encoding="utf-8")
        assert "parameters.forEach" in js, (
            "json-enc.js must iterate the FormData with .forEach(value, key)"
        )
        assert "JSON.stringify(parameters)" not in js, (
            "JSON.stringify(parameters) on a FormData yields '{}' — the "
            "htmx-1.x bug this fix exists to avoid"
        )

    def test_extension_sets_json_content_type(self) -> None:
        js = (STATIC / "json-enc.js").read_text(encoding="utf-8")
        assert "application/json" in js


# ---------------------------------------------------------------------------
# Bug 1 — base.html loads the extension, in the right order
# ---------------------------------------------------------------------------


class TestBaseHtmlLoadsExtension:
    def test_loads_json_enc_from_static(self) -> None:
        assert '<script src="/ui/static/json-enc.js"' in BASE_HTML

    def test_json_enc_loads_after_htmx(self) -> None:
        # defineExtension needs htmx defined; both are deferred and execute in
        # document order, so htmx.min.js must appear first.
        assert BASE_HTML.index("/ui/static/htmx.min.js") < BASE_HTML.index(
            "/ui/static/json-enc.js"
        )

    def test_no_cdn_reference(self) -> None:
        for cdn in ("unpkg.com", "jsdelivr", "cdnjs.cloudflare"):
            assert cdn not in BASE_HTML, f"CDN reference leaked: {cdn}"


# ---------------------------------------------------------------------------
# Bug 1 — per-form hx-ext placement (JSON forms in, multipart/DELETE out)
# ---------------------------------------------------------------------------


class TestPerFormHxExt:
    def test_create_notebook_form_opts_in(self) -> None:
        tag = _form_tag_containing(INDEX_HTML, 'hx-post="/ui/api/notebooks"')
        assert 'hx-ext="json-enc"' in tag

    def test_rename_form_opts_in(self) -> None:
        tag = _form_tag_containing(
            DETAIL_HTML, 'hx-patch="/ui/api/notebooks/{{ notebook.slug }}"'
        )
        assert 'hx-ext="json-enc"' in tag

    def test_topic_form_opts_in(self) -> None:
        tag = _form_tag_containing(
            DETAIL_HTML,
            'hx-patch="/ui/api/notebooks/{{ notebook.slug }}/topic"',
        )
        assert 'hx-ext="json-enc"' in tag

    def test_add_paper_form_opts_in(self) -> None:
        tag = _form_tag_containing(
            DETAIL_HTML,
            'hx-post="/ui/api/notebooks/{{ notebook.slug }}/papers"',
        )
        assert 'hx-ext="json-enc"' in tag

    def test_discover_form_opts_in(self) -> None:
        tag = _form_tag_containing(
            DETAIL_HTML,
            'hx-post="/ui/api/notebooks/{{ notebook.slug }}/discover"',
        )
        assert 'hx-ext="json-enc"' in tag

    def test_ingest_form_opts_in(self) -> None:
        tag = _form_tag_containing(
            DETAIL_HTML,
            'hx-post="/ui/api/notebooks/{{ notebook.slug }}/ingest"',
        )
        assert 'hx-ext="json-enc"' in tag

    def test_multipart_upload_form_excluded(self) -> None:
        # The upload card uploads ar5iv HTML as multipart/form-data and MUST
        # NOT be converted to JSON (FM-a).
        tag = _form_tag_containing(
            DETAIL_HTML,
            'hx-post="/ui/api/notebooks/{{ notebook.slug }}/papers/upload"',
        )
        assert 'hx-encoding="multipart/form-data"' in tag
        assert "json-enc" not in tag, (
            "the multipart upload form must NOT carry hx-ext=\"json-enc\" — "
            "that would convert the file upload to a JSON body and break it"
        )

    def test_no_hx_ext_on_body_or_html_wrapper(self) -> None:
        # hx-ext inherits to descendants; placing it on <body>/<html> would
        # silently capture the multipart upload form. It must be per-form only.
        assert not re.search(r"<body\b[^>]*hx-ext", BASE_HTML)
        assert not re.search(r"<html\b[^>]*hx-ext", BASE_HTML)

    def test_delete_controls_have_no_hx_ext(self) -> None:
        # DELETE buttons are standalone <button hx-delete> controls (no
        # enclosing hx-ext form) and must not be given json-enc.
        for html in (INDEX_HTML, DETAIL_HTML):
            for m in re.finditer(r"<button\b[^>]*hx-delete[^>]*>", html):
                assert "json-enc" not in m.group(0)


# ---------------------------------------------------------------------------
# Bug 2 — globalViewTransitions runs after htmx loads
# ---------------------------------------------------------------------------


class TestViewTransitionsOrdering:
    def test_assignment_present(self) -> None:
        # MOVED 2026-08-22 (#431): this code left base.html's inline
        # <script> for server/frontend/static/ui.js. The property this
        # guard protects is unchanged and still asserted — only its
        # home moved, because the console now ships NO inline script
        # (htmx's hx-on:: needs 'unsafe-eval', which the CSP withholds).
        assert "htmx.config.globalViewTransitions =" in UI_JS

    def test_reduced_motion_preference_is_re_read_on_change(self) -> None:
        # 2026q3-ui-uplift UPL-22: the preference must be re-read on `change`,
        # not sampled once at DOMContentLoaded. See the twin guard in
        # tests/test_ui_m4_in_place_add_paper.py.
        # MOVED 2026-08-22 (#431): this code left base.html's inline
        # <script> for server/frontend/static/ui.js. The property this
        # guard protects is unchanged and still asserted — only its
        # home moved, because the console now ships NO inline script
        # (htmx's hx-on:: needs 'unsafe-eval', which the CSP withholds).
        assert "addEventListener('change'" in UI_JS.replace('"', "'")

    def test_assignment_in_domcontentloaded_not_inline_defer(self) -> None:
        # MOVED 2026-08-22 (#431): this code left base.html's inline
        # <script> for server/frontend/static/ui.js. The property this
        # guard protects is unchanged and still asserted — only its
        # home moved, because the console now ships NO inline script
        # (htmx's hx-on:: needs 'unsafe-eval', which the CSP withholds).
        # Bug 2 was an INLINE <script defer>, where `defer` does nothing.
        # ui.js is EXTERNAL, where it works. So the guard is now: the flag is
        # NOT in base.html, and it IS inside a DOMContentLoaded handler.
        assert "htmx.config.globalViewTransitions =" not in BASE_CODE, (
            "an inline copy in base.html re-introduces the Bug-2 ordering "
            "hazard; the flag belongs in ui.js"
        )
        assert "DOMContentLoaded" in UI_JS, (
            "globalViewTransitions must be set inside a DOMContentLoaded "
            "handler so htmx is defined when it runs (Bug 2)"
        )


# ---------------------------------------------------------------------------
# Bug 1 (F1 rectification) — hx-ext on the SERVED HTML, not just the template
# ---------------------------------------------------------------------------
#
# The TestPerFormHxExt guards above read the raw template files. That is cheap
# source-drift coverage, but it is a proxy: the browser consumes RENDERED HTML,
# and a future Jinja change (a {% block %} override, an {% if %} guard,
# template-inheritance churn) could drop/relocate hx-ext in the served output
# while leaving it in the template source. This is the exact failure class the
# milestone exists to close — the old JSON-direct route tests never caught the
# 422 precisely because they bypassed the rendered client surface. So we ALSO
# render the detail page through the real ui/notebooks routers + TestClient and
# assert hx-ext on what is actually served (F1 from the adversary critique).


@pytest.fixture
def _ui_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Minimal app: notebooks + ui routers + a real NotebooksStore.

    Mirrors the fixture in tests/test_ui_html_pages.py so the served-HTML
    assertions exercise the same render path the browser hits.
    """
    import asyncio

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.notebooks_store import NotebooksStore
    from server.routes import notebooks as notebooks_module
    from server.routes.notebooks import router as notebooks_router
    from server.routes.ui import router as ui_router
    from tools import _notebook_common

    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(
        notebooks_module, "_now_iso", lambda: "2026-06-01T00:00:00+00:00"
    )
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        with TestClient(app) as c:
            r = c.post("/ui/api/notebooks", json={"slug": "demo-nb"})
            if r.status_code not in (200, 201):
                raise AssertionError(f"setup create failed: {r.status_code} {r.text}")
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


class TestServedHtmlHxExt:
    """hx-ext="json-enc" must be present in the RENDERED detail page, not just
    the template source (F1 — closes the rendered-surface coverage gap)."""

    #: The five JSON-bodied detail forms, keyed by the rendered hx attribute
    #: (slug interpolated). All must carry hx-ext="json-enc" in served HTML.
    _JSON_FORM_MARKERS = (
        'hx-patch="/ui/api/notebooks/demo-nb"',  # rename
        'hx-patch="/ui/api/notebooks/demo-nb/topic"',  # topic
        'hx-post="/ui/api/notebooks/demo-nb/papers"',  # add-paper
        'hx-post="/ui/api/notebooks/demo-nb/discover"',  # discover
        'hx-post="/ui/api/notebooks/demo-nb/ingest"',  # ingest
    )

    def test_detail_json_forms_carry_hx_ext_in_served_html(
        self, _ui_client: TestClient
    ) -> None:
        body = _ui_client.get("/ui/notebooks/demo-nb").text
        for marker in self._JSON_FORM_MARKERS:
            tag = _form_tag_containing(body, marker)
            assert 'hx-ext="json-enc"' in tag, (
                f"served detail form {marker!r} is missing hx-ext=\"json-enc\" "
                f"— the browser would send an empty body and 422"
            )

    def test_served_multipart_upload_form_excluded(
        self, _ui_client: TestClient
    ) -> None:
        body = _ui_client.get("/ui/notebooks/demo-nb").text
        tag = _form_tag_containing(
            body, 'hx-post="/ui/api/notebooks/demo-nb/papers/upload"'
        )
        assert 'hx-encoding="multipart/form-data"' in tag
        assert "json-enc" not in tag, (
            "served multipart upload form must NOT carry hx-ext — that would "
            "convert the file upload to a JSON body and break it"
        )

    def test_served_create_form_carries_hx_ext(
        self, _ui_client: TestClient
    ) -> None:
        body = _ui_client.get("/ui/").text
        tag = _form_tag_containing(body, 'hx-post="/ui/api/notebooks"')
        assert 'hx-ext="json-enc"' in tag

    def test_served_pages_load_json_enc_after_htmx(
        self, _ui_client: TestClient
    ) -> None:
        for path in ("/ui/", "/ui/notebooks/demo-nb"):
            body = _ui_client.get(path).text
            assert "/ui/static/json-enc.js" in body
            assert body.index("/ui/static/htmx.min.js") < body.index(
                "/ui/static/json-enc.js"
            ), f"{path}: json-enc.js must load after htmx.min.js"
