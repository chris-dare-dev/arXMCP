"""ui-attractive-polish-m4 — in-place add-paper swap + View Transitions + flash.

Regression tests for the three e4 polish items in m4 v0:

- **UPL-12 v0** — `POST /ui/api/notebooks/{slug}/papers` returns an HTML
  `<tr>` fragment when ``HX-Request: true``; existing JSON branch preserved
  for curl/non-htmx clients. ``_paper_row_html`` extended with
  ``has_preview: bool = True`` so the URL-paste branch renders a
  disabled-look placeholder instead of a broken Preview link.
- **UPL-13** — `htmx.config.globalViewTransitions = true` in `base.html`
  inline script + a `::view-transition-old/new(root)` duration override in
  `app.css`. Per Spike-1 — htmx 2.0.10 has native View Transitions
  integration; no `htmx:beforeSwap` wrapper code.
- **UPL-22** — `.status-badge { min-width: 14ch }` for footer stability
  + a `.htmx-settling` flash keyframe on the badge after swap-in
  (gated by `prefers-reduced-motion: no-preference`).

The Spike-2 13-item pre-flight checklist is the load-bearing security
contract for UPL-12. The test classes below mechanically verify each
checklist item.
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
    _paper_row_html,
)
from server.routes.notebooks import (
    router as notebooks_router,
)
from server.routes.ui import router as ui_router
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "server" / "frontend" / "static"
FRONTEND_TEMPLATES: Path = REPO_ROOT / "server" / "frontend" / "templates"

APP_CSS: str = (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8")
APP_CSS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", APP_CSS, flags=_re.S)
BASE_HTML: str = (FRONTEND_TEMPLATES / "base.html").read_text(encoding="utf-8")
NOTEBOOK_DETAIL_HTML: str = (
    FRONTEND_TEMPLATES / "notebook_detail.html"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test fixture (mirrors tests/test_notebook_rename_delete.py pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
def m4_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Minimal app (notebooks + ui routers + static) + a real NotebooksStore."""
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(
        notebooks_module, "_now_iso", lambda: "2026-05-31T16:00:00+00:00"
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
            r = c.post(
                "/ui/api/notebooks",
                json={
                    "slug": "test-nb",
                    "display_name": "Test Notebook",
                    "notebook_kind": "arxiv",
                },
            )
            assert r.status_code in (200, 201), r.text
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# UPL-12 v0 — _paper_row_html helper extension (has_preview param)
# ---------------------------------------------------------------------------


class TestUPL12PaperRowHtmlHasPreview:
    """``_paper_row_html`` accepts ``has_preview: bool = True`` and renders
    different Preview cells based on it."""

    def test_default_preserves_upload_behavior(self) -> None:
        # Default has_preview=True must render the live Preview <a> link
        # (the m8 upload-handler behavior — upload writes ar5iv HTML so
        # the preview route IS valid).
        out = _paper_row_html(
            slug="test-nb", paper_id="2604.00001", added_at="2026-05-31T16:00:00+00:00"
        )
        assert '<a href="/ui/notebooks/test-nb/papers/2604.00001/preview"' in out
        assert 'target="_blank"' in out
        assert 'rel="noopener"' in out
        # NOT the disabled placeholder.
        assert "upload an ar5iv HTML to enable preview" not in out

    def test_has_preview_false_renders_disabled_placeholder(self) -> None:
        # m4 UPL-12 v0: URL-paste writes NO ar5iv HTML, so the preview
        # link would 404. Render the m10-rect-F6 disabled-look <span>
        # instead.
        out = _paper_row_html(
            slug="test-nb",
            paper_id="2604.00001",
            added_at="2026-05-31T16:00:00+00:00",
            has_preview=False,
        )
        assert '<span class="hint"' in out
        assert "upload an ar5iv HTML to enable preview" in out
        # NOT the live preview link.
        assert "/ui/notebooks/test-nb/papers/2604.00001/preview" not in out

    def test_actions_cell_says_added(self) -> None:
        # m4 changed "uploaded" → "added" (neutral wording for both
        # upload + URL-paste paths). Regression guard.
        out_upload = _paper_row_html(
            slug="test-nb", paper_id="2604.00001", added_at="2026-05-31T16:00:00+00:00"
        )
        out_paste = _paper_row_html(
            slug="test-nb",
            paper_id="2604.00001",
            added_at="2026-05-31T16:00:00+00:00",
            has_preview=False,
        )
        # Both paths show "added"; neither shows the old "uploaded".
        assert "<td>added</td>" in out_upload
        assert "<td>added</td>" in out_paste
        assert "uploaded" not in out_upload
        assert "uploaded" not in out_paste

    def test_all_interpolated_values_html_escaped(self) -> None:
        # Spike-2 pre-flight item #1: server-fragment correctness.
        # Every interpolated value MUST go through html.escape().
        out = _paper_row_html(
            slug='nb"x',  # HTML-significant in attribute context
            paper_id="<id>",  # HTML-significant in text + attribute context
            added_at='ts"&<',  # all three HTML-significant chars
            has_preview=True,
        )
        # Each special char escaped at least once.
        assert "&quot;" in out  # the " in slug + added_at
        assert "&lt;" in out  # the < in paper_id + added_at
        assert "&gt;" in out  # the > in paper_id
        assert "&amp;" in out  # the & in added_at
        # And the raw chars MUST NOT survive outside escaped context.
        # (The escaped output may legitimately contain " around attribute
        # values, so we don't check for absence of " — just confirm the
        # injection chars from the input are escaped.)
        assert 'nb"x' not in out
        assert "<id>" not in out


# ---------------------------------------------------------------------------
# UPL-12 v0 — Spike-2 pre-flight checklist: content-negotiation + XSS
# ---------------------------------------------------------------------------


class TestUPL12PreFlightChecklist:
    """The Spike-2 13-item pre-flight checklist — server-fragment correctness,
    middleware integrity (axes 1+3 covered here; 2+4 by inspection +
    elsewhere)."""

    def test_content_negotiation_html_branch_on_hx_request(
        self, m4_client: TestClient
    ) -> None:
        # Spike-2 pre-flight: HX-Request: true returns an HTML <tr>
        # fragment (text/html content-type); the JSON branch is NOT taken.
        r = m4_client.post(
            "/ui/api/notebooks/test-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.00001"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 201, r.text
        # Content-Type should indicate HTML.
        assert "text/html" in r.headers.get("content-type", "").lower()
        # The body is a <tr> fragment, not a JSON object.
        text = r.text
        assert text.startswith("<tr")
        assert "</tr>" in text
        assert 'data-slug="test-nb"' in text
        assert 'data-paper-id="2604.00001"' in text
        # URL-paste path → has_preview=False → placeholder rendered.
        assert "upload an ar5iv HTML to enable preview" in text

    def test_content_negotiation_json_branch_without_hx_request(
        self, m4_client: TestClient
    ) -> None:
        # Spike-2 pre-flight: non-htmx clients (curl, scripts) get the
        # existing JSON body unchanged. No HX-Request header sent.
        # Need a different paper_id to avoid 409 from the previous test
        # (which used the same client and inserted the same paper).
        r = m4_client.post(
            "/ui/api/notebooks/test-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.00002"},
        )
        assert r.status_code == 201, r.text
        # Content-Type should indicate JSON.
        assert "application/json" in r.headers.get("content-type", "").lower()
        body = r.json()
        assert body == {"slug": "test-nb", "paper_id": "2604.00002"}

    def test_hx_request_false_takes_json_branch(
        self, m4_client: TestClient
    ) -> None:
        # Spike-2 pre-flight: only the literal string "true" triggers
        # the HTML branch. Any other value (including "false", "1",
        # "True" capitalized) takes the JSON branch.
        r = m4_client.post(
            "/ui/api/notebooks/test-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.00003"},
            headers={"HX-Request": "false"},
        )
        assert r.status_code == 201, r.text
        assert "application/json" in r.headers.get("content-type", "").lower()

    def test_slug_validation_gate_before_renderer(
        self, m4_client: TestClient
    ) -> None:
        # Spike-2 pre-flight item #3: input validation runs BEFORE the
        # response fork. Path-traversal slug must 422 regardless of
        # HX-Request header; the renderer must never see it.
        # The FastAPI path-pattern uses {slug} so URL-encoded slashes
        # are intercepted; the validate_slug() path-traversal check
        # fires for slugs containing dots or upper-case.
        # Use a starts-with-uppercase slug that's a regex violation.
        r = m4_client.post(
            "/ui/api/notebooks/INVALID-slug/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.00001"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 422, r.text
        # 422 is JSON detail regardless of HX-Request — validation
        # rejection precedes the renderer.

    def test_xss_payload_through_hx_request_branch_is_escaped(
        self, m4_client: TestClient
    ) -> None:
        # Spike-2 pre-flight item #4: XSS injection through the new
        # HX-Request branch must be html-escaped in the rendered
        # fragment. The only operator-controlled value in the
        # add-paper payload is the arxiv_url, which gets parsed by
        # _arxiv_url_to_paper_id and the extracted paper_id flows
        # through html.escape() in _paper_row_html. We can't inject
        # XSS via arxiv_url (it's regex-validated to arxiv.org URLs
        # only), but we can verify by direct unit-test that
        # _paper_row_html escapes a hostile payload (already covered
        # in TestUPL12PaperRowHtmlHasPreview::
        # test_all_interpolated_values_html_escaped); here we verify
        # the response chain end-to-end. With a real arxiv-format URL
        # the response will contain the validated paper_id, so the
        # assertion is that the response is HTML and that the
        # paper_id appears escaped (paper_id format is digits + dot,
        # so &lt;/&gt; won't appear in this happy path — the real
        # safeguard is the unit test on _paper_row_html).
        r = m4_client.post(
            "/ui/api/notebooks/test-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/2604.00004"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 201, r.text
        text = r.text
        # No unescaped raw payload markers in the response.
        assert "<script" not in text.lower()
        assert "javascript:" not in text.lower()

    def test_malformed_arxiv_url_returns_422_no_fragment(
        self, m4_client: TestClient
    ) -> None:
        # Spike-2 pre-flight item #3 (cont.): _arxiv_url_to_paper_id
        # rejection precedes the renderer too.
        r = m4_client.post(
            "/ui/api/notebooks/test-nb/papers",
            json={"arxiv_url": "https://example.com/not-arxiv"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 422, r.text

    def test_old_style_paper_id_through_html_branch(
        self, m4_client: TestClient
    ) -> None:
        # m4-rect F2 (MEDIUM): _arxiv_url_to_paper_id (via
        # is_valid_arxiv_paper_id at ingest/identifiers.py) accepts BOTH
        # new-style (2604.00001) AND old-style (hep-th/0001234) paper IDs.
        # Pre-rect, every HTML-branch test in this file exercised only
        # new-style IDs, so the renderer's behaviour for the slash-bearing
        # old-style form was undocumented. The slash is HTML-safe (only
        # `< > & "` are escape-relevant) so this is NOT an XSS path, but
        # the assertion surface that "Spike-2 13-item pre-flight checklist
        # is mechanically exercised" (impl-summary AC row 10) needs the
        # full input range to mean what it claims.
        r = m4_client.post(
            "/ui/api/notebooks/test-nb/papers",
            json={"arxiv_url": "https://arxiv.org/abs/hep-th/0001234"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 201, r.text
        assert "text/html" in r.headers.get("content-type", "").lower()
        text = r.text
        assert 'data-paper-id="hep-th/0001234"' in text
        # ui-uplift-m7: was `"<td>hep-th/0001234</td>"`. The cell now wraps
        # the id in <code> (AC#2 — it is an identifier, and the template
        # rendering this same table always did). The ASSERTION'S INTENT is
        # the slash-bearing old-style id surviving the renderer intact and
        # unescaped, not the element that carries it, so it is re-expressed
        # that way rather than re-pinned to the new shape: the id appears in
        # the id cell, and the slash is untouched.
        assert "<td><code>hep-th/0001234</code></td>" in text
        assert "hep-th&#x2F;0001234" not in text, (
            "the slash is HTML-safe and must not be escaped"
        )
        # has_preview=False branch (URL-paste writes no ar5iv HTML on
        # disk) — disabled-look Preview affordance present.
        assert "upload an ar5iv HTML to enable preview" in text


# ---------------------------------------------------------------------------
# UPL-12 v0 — template changes on the add-paper form
# ---------------------------------------------------------------------------


class TestUPL12TemplateChanges:
    """``notebook_detail.html`` add-paper form swapped from
    ``location.reload()`` to ``hx-target`` + ``hx-swap``."""

    def test_add_paper_form_has_hx_target_papers_tbody(self) -> None:
        # Find the add-paper form (the one POSTing to /ui/api/notebooks/
        # {slug}/papers — NOT /papers/upload). It must carry the new
        # hx-target/hx-swap attributes.
        # Match the form element + the next ~500 chars.
        m = _re.search(
            r'<form\b[^>]*hx-post="/ui/api/notebooks/\{\{ notebook\.slug \}\}/papers"[^>]*>',
            NOTEBOOK_DETAIL_HTML,
        )
        assert m is not None, "add-paper form not found"
        form_block = m.group(0)
        assert 'hx-target="#papers-tbody"' in form_block, (
            "UPL-12 v0: add-paper form missing hx-target=\"#papers-tbody\""
        )
        # ui-uplift-m12 (UPL-1) AC#4: the exact string `hx-swap="beforeend"`
        # no longer appears — the reorder moved #papers-tbody ABOVE this form,
        # so the append needs htmx's `show:` modifier or it lands off-screen
        # upward. The KIND of swap is what UPL-12 v0 decided and is what this
        # guard is for, so it is asserted on the value's first token; a
        # modifier is an m12 addition, not a repeal. Anchored so `beforeend`
        # is the swap and not a substring of some other attribute.
        m_swap = _re.search(r'hx-swap="(beforeend)(?:\s+[^"]*)?"', form_block)
        assert m_swap is not None, (
            f"UPL-12 v0: add-paper form's swap is not beforeend: {form_block!r}"
        )
        assert "show:#papers-tbody" in form_block, (
            "ui-uplift-m12 AC#4: after the reorder the beforeend target sits "
            "above this form, so the swap must scroll the append point into "
            "view or it succeeds invisibly."
        )

    def test_add_paper_form_no_longer_uses_location_reload(self) -> None:
        # Negative-regression: the legacy `hx-on::htmx:after-request=
        # "if(event.detail.successful) location.reload()"` line on the
        # add-paper form must be GONE (UPL-12 v0 replaced it). The
        # create-notebook form in index.html still uses location.reload
        # (m5 v1 follow-on), but the add-paper form in
        # notebook_detail.html must not.
        # Locate the add-paper form block.
        m = _re.search(
            r'<form\b[^>]*hx-post="/ui/api/notebooks/\{\{ notebook\.slug \}\}/papers"[^>]*>',
            NOTEBOOK_DETAIL_HTML,
        )
        assert m is not None
        form_block = m.group(0)
        # The form block (single multi-line element) must NOT contain
        # location.reload anywhere.
        assert "location.reload" not in form_block, (
            "UPL-12 v0 regression: add-paper form still contains "
            "location.reload — m4 should have replaced it with htmx swap"
        )

    def test_add_paper_form_preserves_m3_hx_disabled_elt(self) -> None:
        # m3 added hx-disabled-elt="find button" — m4 must preserve it.
        # Cross-milestone safety check.
        m = _re.search(
            r'<form\b[^>]*hx-post="/ui/api/notebooks/\{\{ notebook\.slug \}\}/papers"[^>]*>',
            NOTEBOOK_DETAIL_HTML,
        )
        assert m is not None
        form_block = m.group(0)
        assert 'hx-disabled-elt="find button"' in form_block

    def test_papers_tbody_still_has_m1_aria_live(self) -> None:
        # m1's aria-live="polite" on #papers-tbody must be preserved
        # (it's what makes the new beforeend swap announce via screen
        # readers). Negative-regression: m4 must not have stripped it.
        # Strip Jinja2 `{# ... #}` comments first — the design comments
        # at the top of the template (line ~212) quote the literal
        # `<tbody id="papers-tbody">` string, which would false-positive
        # the regex anchor against documentation rather than the live
        # element.
        no_jinja = _re.sub(
            r"\{#.*?#\}", "", NOTEBOOK_DETAIL_HTML, flags=_re.DOTALL
        )
        m = _re.search(r'<tbody\b[^>]*id="papers-tbody"[^>]*>', no_jinja)
        if m is None:
            raise AssertionError(
                "expected <tbody id=\"papers-tbody\"> element in detail template"
            )
        attrs = m.group(0)
        assert 'aria-live="polite"' in attrs


# ---------------------------------------------------------------------------
# UPL-13 — htmx.config.globalViewTransitions = true in base.html
# ---------------------------------------------------------------------------


class TestUPL13GlobalViewTransitions:
    """``base.html`` enables htmx native View Transitions.

    ui-htmx-json-fix-m1 corrected the STRUCTURE of this opt-in. Previously
    the flag lived in an inline ``<script defer>`` block — but ``defer`` is
    ignored on inline scripts, so the line ran at parse time before the
    deferred ``htmx.min.js`` loaded; ``htmx`` was undefined and the
    assignment threw and never took effect. The flag now lives inside a
    ``DOMContentLoaded`` handler (which fires after deferred scripts run, so
    ``htmx`` is defined) and is gated on ``prefers-reduced-motion``.
    """

    def test_global_view_transitions_flag_present(self) -> None:
        # The opt-in assignment is still present. Strip HTML comments first:
        # base.html's explanatory comment QUOTES the old assignment to describe
        # the original bug, so an un-stripped `in BASE_HTML` check would pass
        # on the prose even if the real code were deleted.
        base_code = _re.sub(r"<!--.*?-->", "", BASE_HTML, flags=_re.S)
        assert "htmx.config.globalViewTransitions =" in base_code

    def test_global_view_transitions_runs_after_load_not_in_inline_defer(
        self,
    ) -> None:
        # ui-htmx-json-fix-m1 (Bug 2 regression guard): the assignment MUST
        # be inside a DOMContentLoaded handler, NOT a bare inline
        # <script defer> body (that was the bug — `defer` is a no-op on
        # inline scripts, so the line ran before htmx existed). Strip HTML
        # comments first — base.html's explanatory comment quotes the
        # assignment to describe the old bug and would otherwise shift `idx`
        # into a comment region (whose nearest preceding <script ...> is the
        # external deferred json-enc tag).
        base_code = _re.sub(r"<!--.*?-->", "", BASE_HTML, flags=_re.S)
        idx = base_code.index("htmx.config.globalViewTransitions =")
        # Walk back to the enclosing <script ...> opener.
        script_open = base_code.rfind("<script", 0, idx)
        assert script_open != -1, "expected an enclosing <script> block"
        opener = base_code[script_open : base_code.index(">", script_open) + 1]
        # The enclosing script must NOT be an inline `defer` block, and must
        # NOT be an external src= script (the flag is real inline JS).
        assert "defer" not in opener, (
            "ui-htmx-json-fix-m1 regression: globalViewTransitions is back "
            "inside an inline <script defer> — `defer` is ignored on inline "
            "scripts so htmx is undefined at parse time. Use DOMContentLoaded."
        )
        # The assignment must sit inside a DOMContentLoaded listener so it
        # runs after the deferred htmx.min.js has executed.
        script_body = base_code[script_open : base_code.index("</script>", idx)]
        assert "DOMContentLoaded" in script_body, (
            "ui-htmx-json-fix-m1: globalViewTransitions must be set inside a "
            "DOMContentLoaded handler so htmx is defined when it runs."
        )
        # And it must be guarded against the reduced-motion preference.
        assert "prefers-reduced-motion" in script_body, (
            "ui-htmx-json-fix-m1: the View Transitions opt-in must honor "
            "prefers-reduced-motion."
        )

    def test_reduced_motion_preference_is_re_read_on_change(self) -> None:
        # 2026q3-ui-uplift UPL-22 regression guard. The three CSS gates
        # (app.css @media blocks) re-evaluate continuously because @media
        # does; this single JS read did not, so an operator who flipped
        # their OS reduced-motion setting mid-session kept View Transitions
        # until a full page reload. The MediaQueryList must carry a
        # `change` listener, not just be sampled once at DOMContentLoaded.
        base_code = _re.sub(r"<!--.*?-->", "", BASE_HTML, flags=_re.S)
        idx = base_code.index("htmx.config.globalViewTransitions =")
        script_open = base_code.rfind("<script", 0, idx)
        script_body = base_code[script_open : base_code.index("</script>", idx)]
        assert "addEventListener('change'" in script_body.replace('"', "'"), (
            "UPL-22 regression: the prefers-reduced-motion MediaQueryList is "
            "sampled once and never re-read. Register a 'change' listener so "
            "a mid-session OS preference flip takes effect without a reload."
        )

    def test_no_obsolete_htmx_beforeswap_wrapper_added(self) -> None:
        # Spike-1 explicitly rejected the htmx-1.x wrapper pattern
        # (intercept htmx:beforeSwap → document.startViewTransition →
        # re-enter via htmx.swap). If a future PR re-introduces it,
        # this fires. Strip Jinja2 comments, HTML comments, and
        # JS line comments first so the existing "NO htmx:beforeSwap-
        # wrapper code" prose comment in base.html (documentation,
        # not code) doesn't false-positive.
        no_jinja = _re.sub(r"\{#.*?#\}", "", BASE_HTML, flags=_re.DOTALL)
        no_html_c = _re.sub(r"<!--.*?-->", "", no_jinja, flags=_re.DOTALL)
        no_js_line = _re.sub(r"//[^\n]*", "", no_html_c)
        no_js_block = _re.sub(r"/\*.*?\*/", "", no_js_line, flags=_re.DOTALL)
        assert "htmx:beforeSwap" not in no_js_block, (
            "UPL-13 regression: htmx:beforeSwap wrapper code in base.html "
            "is the obsolete htmx-1.x pattern (Spike-1). htmx 2.0.10 "
            "handles View Transitions natively via the config flag — no "
            "wrapper code needed."
        )


# ---------------------------------------------------------------------------
# UPL-13 — CSS duration override for ::view-transition-old/new(root)
# ---------------------------------------------------------------------------


class TestUPL13ViewTransitionsCss:
    """``app.css`` carries the ``::view-transition-old/new(root)`` duration
    override gated by ``prefers-reduced-motion: no-preference``."""

    def test_view_transition_pseudo_elements_present(self) -> None:
        assert "::view-transition-old(root)" in APP_CSS_NO_COMMENTS
        assert "::view-transition-new(root)" in APP_CSS_NO_COMMENTS

    def test_duration_override_is_200ms(self) -> None:
        # Find the View Transitions rule block and assert the
        # animation-duration RESOLVES to 200ms.
        #
        # ui-uplift-m6 replaced the literal with var(--dur-fast). The
        # intent of this test is the effective duration, not its spelling,
        # so it now resolves the token — a future edit that re-times
        # --dur-fast still fails here, which is the point.
        from tests._ui_color import load_raw_tokens

        m = _re.search(
            r"::view-transition-(?:old|new)\(root\)[^{]*\{[^}]*"
            r"animation-duration:\s*var\(--dur-fast\)",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        )
        assert m is not None, (
            "UPL-13: ::view-transition-*(root) { animation-duration: "
            "var(--dur-fast) } rule missing"
        )
        base_tokens, _dark = load_raw_tokens()
        assert base_tokens["--dur-fast"] == "200ms", (
            f"UPL-13: --dur-fast is {base_tokens['--dur-fast']}, not 200ms — "
            f"the view transition would re-time."
        )

    def test_duration_override_gated_by_no_preference(self) -> None:
        # The override MUST be inside a @media (prefers-reduced-motion:
        # no-preference) block per the m1 motion-vocabulary discipline.
        no_pref_re = _re.compile(
            r"@media\s*\(\s*prefers-reduced-motion:\s*no-preference\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        # Find all no-preference blocks; the View Transitions one must
        # be one of them.
        blocks = no_pref_re.findall(APP_CSS_NO_COMMENTS)
        assert any(
            "::view-transition-old(root)" in b or "::view-transition-new(root)" in b
            for b in blocks
        ), (
            "UPL-13: ::view-transition-*(root) override must live inside "
            "a @media (prefers-reduced-motion: no-preference) block — "
            "reduced-motion users get the universal clamp from m1's "
            "@media (prefers-reduced-motion: reduce) block instead."
        )


# ---------------------------------------------------------------------------
# UPL-22 — .status-badge min-width + .htmx-settling flash
# ---------------------------------------------------------------------------


class TestUPL22BadgeStability:
    """``.status-badge`` has ``min-width: 14ch`` for footer stability +
    a ``.htmx-settling`` flash keyframe gated by reduced-motion."""

    def test_status_badge_min_width_14ch(self) -> None:
        # Find the .status-badge { ... } rule and assert min-width.
        m = _re.search(
            r"\.status-badge\s*\{[^}]*min-width:\s*14ch",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        )
        assert m is not None, (
            "UPL-22: .status-badge { min-width: 14ch } missing — without "
            "it the footer reflows on DEGRADED/WARN/OK/DOWN state changes."
        )

    def test_htmx_settling_flash_keyframe_present(self) -> None:
        assert "@keyframes badge-flash" in APP_CSS_NO_COMMENTS
        assert ".status-badge.htmx-settling" in APP_CSS_NO_COMMENTS

    def test_flash_gated_by_no_preference(self) -> None:
        no_pref_re = _re.compile(
            r"@media\s*\(\s*prefers-reduced-motion:\s*no-preference\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        blocks = no_pref_re.findall(APP_CSS_NO_COMMENTS)
        assert any(
            ".status-badge.htmx-settling" in b for b in blocks
        ), (
            "UPL-22: .status-badge.htmx-settling animation must live inside "
            "a @media (prefers-reduced-motion: no-preference) block."
        )

    def test_flash_derives_from_accent_not_a_hardcoded_hex(self) -> None:
        """UPL-22's real requirement: the flash colour must DERIVE from
        ``var(--accent)`` so a re-derived accent carries into it for free,
        rather than being a hex literal that silently goes stale.

        This asserted the ``color-mix(in oklab, var(--accent) …)`` spelling
        specifically. ui-uplift-m6's critique (H1/M8) found that flashing
        the ``background`` property REPLACED each pill's opaque fill for
        the full 400 ms, dropping 6 of 8 pill texts under SC 1.4.3, so the
        flash now moves ``border-color`` to ``var(--accent)`` directly and
        no text pair moves at all. Still derived, more directly than
        before — so the requirement holds and only the spelling changed.
        """
        m = _re.search(
            r"@keyframes\s+badge-flash\s*\{(.*?)\n\s*\}",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        )
        assert m is not None, "the badge-flash keyframe is gone"
        body = m.group(1)
        assert "var(--accent)" in body, (
            "UPL-22: badge-flash must derive its colour from var(--accent)."
        )
        assert not _re.search(r"#[0-9a-fA-F]{3,8}\b", body), (
            f"UPL-22: badge-flash hardcodes a hex literal: {body.strip()!r}. "
            f"It must track --accent."
        )


# ---------------------------------------------------------------------------
# Cross-milestone safety — m1 + m2 + m3 assertions remain compatible
# ---------------------------------------------------------------------------


class TestCrossMilestoneSafety:
    """m4 doesn't disturb m1 / m2 / m3 sites."""

    def test_m1_prefers_reduced_motion_reduce_block_still_present(self) -> None:
        assert "@media (prefers-reduced-motion: reduce)" in APP_CSS_NO_COMMENTS

    def test_m1_focus_visible_rule_still_present(self) -> None:
        assert ":focus-visible" in APP_CSS_NO_COMMENTS
        assert ":focus:not(:focus-visible) {" in APP_CSS_NO_COMMENTS

    def test_m2_color_mix_button_hover_still_present(self) -> None:
        # m2's button hover uses color-mix(in oklab, var(--accent) 88%, white).
        # m4 adds a SECOND color-mix call (the badge-flash); the m2 one
        # must still be there.
        idx = APP_CSS_NO_COMMENTS.index("button:hover")
        rule_block = APP_CSS_NO_COMMENTS[idx : idx + 300]
        assert "color-mix(in oklab" in rule_block

    def test_m3_dark_mode_block_still_present(self) -> None:
        assert "@media (prefers-color-scheme: dark)" in APP_CSS_NO_COMMENTS

    def test_m3_htmx_request_styling_still_present(self) -> None:
        # m3 added `form.htmx-request button[type="submit"]` selector
        # for in-flight spinner. m4 must not break it.
        assert (
            'form.htmx-request button[type="submit"]' in APP_CSS_NO_COMMENTS
        )

    def test_app_css_under_revised_soft_cap(self) -> None:
        # m5: single source of truth — this cap mirrors the m3 test
        # file's cap exactly. Trajectory:
        #   m1=190 → m2=216 → m3-feat=287 → m3-rect=330 (WCAG) →
        #   m4=335 (UPL-22 + UPL-13) → m5=370 (UPL-19 v1 body clamp +
        #   UPL-8 v1 four dark-mode pill remaps + th dark surface +
        #   UPL-12 v1 row-fade keyframe — all consolidated into the
        #   existing dark @media block and the existing
        #   prefers-reduced-motion:no-preference block to minimise
        #   line cost).
        # If a future milestone raises the cap again, BOTH this test
        # AND tests/test_ui_m3_dark_and_htmx_feedback.py::
        # TestCrossMilestoneSafety::test_app_css_under_soft_cap must
        # move in lockstep — the two caps MUST agree.
        # 2026q3-ui-uplift: m5=370 → 400 for UPL-27 (two WCAG AA contrast
        # fixes), UPL-8 v0 (the first select/textarea base rules) and
        # UPL-15a (tbody tr:hover).
        # ui-uplift-m6: 400 → 480 for the OKLCH token family (every colour
        # token re-derived in both modes) + 3 --dur-* tokens + the
        # per-token derivation rationale (which target ratio, which ground).
        # ui-uplift-m7: kept the cap at 480. m7 needed room for the type
        # scale and took the tokens.css split this message already named as
        # the alternative, rather than a fourth raise — see the fuller note
        # on the m3 cap test. The lockstep requirement is unaffected: all
        # three caps still MUST agree, and they still all read app.css.
        line_count = APP_CSS.count("\n") + (1 if not APP_CSS.endswith("\n") else 0)
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
        # ui-uplift-m10: 520 -> 600, in lockstep. UPL-9 lands eight class
        # rules in one pass (the .discover-* panel + the .topic-* trio, i.e.
        # the last of the BAN-R2 debt) plus two recorded refusals — no
        # relevance line, no fade-in keyframe. 22 lines of headroom did not
        # fit that, and the tokens-split hatch named above is spent. The
        # merits are argued at length on the m3 cap test; the file lands at
        # 593 of 600 (m8 rectify M5/M11 — the cap was held, not raised).
        # ui-uplift-m12: 600 -> 680, in lockstep. UPL-1 adds a third top-level
        # region (<details class="manage-disclosure">) plus the nested rule
        # ladder the direct-child `main >` combinator no longer reaches. The
        # merits are argued at length on the m3 cap test. NO absolute line
        # count is recorded here (m12 M3/L3): this said "the file lands at
        # 635 of 680" while it was 627, and `line_count` above is live.
        assert line_count <= 680, (
            f"app.css is {line_count} lines — over the 680-line cap (revised "
            f"by m6 400->480, then m7 480->520, then m10 520->600, then m12 "
            f"600->680 — see the "
            f"raise history above). "
            f"Consider stripping documentation comments, splitting the file "
            f"(e.g. tokens.css + app.css), or arguing for another revision. "
            f"NOTE: the cap tests in tests/test_ui_m3_dark_and_htmx_feedback.py "
            f"and tests/test_ui_m5_create_remove_in_place.py must also move in "
            f"lockstep — all three caps MUST agree."
        )
