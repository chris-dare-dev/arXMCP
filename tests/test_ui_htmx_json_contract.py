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

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND: Path = REPO_ROOT / "frontend"
TEMPLATES: Path = FRONTEND / "templates"
STATIC: Path = FRONTEND / "static"

BASE_HTML: str = (TEMPLATES / "base.html").read_text(encoding="utf-8")
INDEX_HTML: str = (TEMPLATES / "index.html").read_text(encoding="utf-8")
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
        assert "htmx.config.globalViewTransitions = true" in BASE_CODE

    def test_assignment_in_domcontentloaded_not_inline_defer(self) -> None:
        # Run against comment-stripped code so the explanatory comment (which
        # quotes the assignment to describe the OLD bug) does not shift the
        # located index into a comment region.
        idx = BASE_CODE.index("htmx.config.globalViewTransitions = true")
        script_open = BASE_CODE.rfind("<script", 0, idx)
        assert script_open != -1
        opener = BASE_CODE[script_open : BASE_CODE.index(">", script_open) + 1]
        assert "defer" not in opener, (
            "globalViewTransitions must not be in an inline <script defer> "
            "block — defer is a no-op on inline scripts (Bug 2)"
        )
        body = BASE_CODE[script_open : BASE_CODE.index("</script>", idx)]
        assert "DOMContentLoaded" in body
        assert "prefers-reduced-motion" in body
