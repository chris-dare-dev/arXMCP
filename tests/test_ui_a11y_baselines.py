"""ui-attractive-polish-m1 — foundational a11y baselines (UPL-1..4).

Regression tests for the 4 baselines from the 2026-05-ui-polish discovery
pipeline:

- **UPL-1** ``@media (prefers-reduced-motion: reduce)`` universal gate in
  ``frontend/static/app.css``.
- **UPL-2** ``:focus-visible`` outline-ring rules using ``var(--accent)``
  (and ``var(--danger)`` on ``button.danger``) + ``:focus:not(:focus-visible)``
  reset.
- **UPL-3** ``aria-live="polite"`` parity on htmx success swap targets:
  ``#display-name-block``, ``#ingest-status``, ``#papers-tbody``, and
  ``#status-badge`` (with ``aria-atomic="true"``). The load-bearing test is
  that the SERVER-RENDERED fragments (the outputs of ``_display_name_fragment``,
  ``_ingest_status_fragment``, and the ``/ui/status-badge`` endpoint) ALSO
  carry the attribute, not just the initial template render — htmx
  ``hx-swap="outerHTML"`` replaces the element entirely, so without the
  attribute on the swap result the live region goes silent after the first
  poll (research-synthesis.md §2).
- **UPL-4** Skip-to-main-content link + ``<main id="main" tabindex="-1">`` in
  ``base.html`` + matching ``.skip-link`` rule in ``app.css``.

These are mostly static-file inspection tests (read from disk, assert
substrings). The server-fragment cases go through the FastAPI ``TestClient``
to exercise the actual rendering path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import (
    _display_name_fragment,
    _ingest_status_fragment,
)
from server.routes.ui import router as ui_router
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "server" / "frontend" / "static"
FRONTEND_TEMPLATES: Path = REPO_ROOT / "server" / "frontend" / "templates"

APP_CSS: str = (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8")
BASE_HTML: str = (FRONTEND_TEMPLATES / "base.html").read_text(encoding="utf-8")
NOTEBOOK_DETAIL_HTML: str = (
    FRONTEND_TEMPLATES / "notebook_detail.html"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# UPL-1 — prefers-reduced-motion universal gate (static CSS inspection)
# ---------------------------------------------------------------------------


class TestUPL1ReducedMotion:
    """``app.css`` carries a universal ``prefers-reduced-motion: reduce`` block."""

    def test_app_css_has_prefers_reduced_motion_media_query(self) -> None:
        assert "@media (prefers-reduced-motion: reduce)" in APP_CSS

    def test_universal_selector_clamps_all_six_timing_properties(self) -> None:
        """Per challenger MINOR finding: include animation-delay + transition-delay
        for completeness, not just the durations."""
        # The selector + every property must appear in the file. Order is not
        # asserted (CSS is order-independent at this granularity).
        idx = APP_CSS.index("@media (prefers-reduced-motion: reduce)")
        block = APP_CSS[idx:]
        assert "*, *::before, *::after" in block
        for prop in (
            "animation-duration",
            "animation-iteration-count",
            "transition-duration",
            "animation-delay",
            "transition-delay",
            "scroll-behavior",
        ):
            assert prop in block, f"missing {prop!r} in reduced-motion block"


# ---------------------------------------------------------------------------
# UPL-2 — :focus-visible baseline outline ring (static CSS inspection)
# ---------------------------------------------------------------------------


class TestUPL2FocusVisible:
    """``app.css`` defines :focus-visible rings for every interactive element."""

    def test_focus_visible_rule_covers_all_interactive_selectors(self) -> None:
        # The rule must cover button, .button, a, input, select, textarea,
        # [tabindex] — researcher-2's enumeration of "every interactive
        # element."
        # Match flexibility: the implementation may split the selector list
        # across multiple lines; assert each selector appears as a token.
        for sel in (
            "button:focus-visible",
            ".button:focus-visible",
            "input:focus-visible",
            "a:focus-visible",
            "select:focus-visible",
            "textarea:focus-visible",
            # ui-uplift-m12 M11. `summary` was missing while two shipped
            # disclosures existed — m12's Manage gate (the ONLY keyboard route
            # to all five mutation forms) and m10's abstract reveal — so both
            # fell back to the UA ring instead of the authored one. This list
            # is enumerated by hand, which is exactly why the omission was
            # invisible to the guard that exists for this class of gap.
            "summary:focus-visible",
            "[tabindex]:focus-visible",
        ):
            assert sel in APP_CSS, f"missing :focus-visible selector {sel!r}"

    def test_every_shipped_disclosure_is_covered_by_the_ring(self) -> None:
        """The list above is hand-maintained, so pair it with a derived check.

        ui-uplift-m12 M11: `<summary>` is focusable by default and receives
        focus with no `tabindex`, so it is invisible to a `[tabindex]` sweep.
        If any template ships a `<details>`, `summary:focus-visible` must be
        authored — otherwise the one control gating a whole region has an
        unauthored focus state.
        """
        templates = sorted(
            (FRONTEND_STATIC.parent / "templates").glob("*.html")
        )
        ships_details = any(
            "<details" in p.read_text(encoding="utf-8") for p in templates
        )
        if not ships_details:
            pytest.skip("no template ships a <details>")
        assert "summary:focus-visible" in APP_CSS, (
            "a template ships a <details> but `summary:focus-visible` is not "
            "authored; its focus ring falls back to the UA default."
        )

    def test_focus_visible_outline_uses_accent_token(self) -> None:
        # The baseline ring uses var(--accent), not a hardcoded hex.
        assert "outline: 2px solid var(--accent)" in APP_CSS

    def test_danger_button_focus_visible_uses_danger_token(self) -> None:
        # Per challenger UPL-2 fix — destructive controls deserve the LOUDEST
        # ring, not the quietest. var(--danger) on outline-color.
        assert "button.danger:focus-visible" in APP_CSS
        # The implementation may put outline-color on the .danger rule.
        # Verify either pattern.
        rule_start = APP_CSS.index("button.danger:focus-visible")
        rule_block = APP_CSS[rule_start : rule_start + 200]
        assert "var(--danger)" in rule_block

    def test_focus_not_focus_visible_reset_present(self) -> None:
        # Mouse clicks set :focus but not :focus-visible; suppress the ring
        # for mouse-only focus so the user doesn't see a ring on every click.
        # Look for the CSS RULE (with opening brace), not a comment mention.
        rule_marker = ":focus:not(:focus-visible) {"
        assert rule_marker in APP_CSS, (
            "missing :focus:not(:focus-visible) CSS rule (the mouse-focus reset)"
        )
        idx = APP_CSS.index(rule_marker)
        assert "outline: none" in APP_CSS[idx : idx + 100]


# ---------------------------------------------------------------------------
# UPL-4 — Skip-to-main-content link (static template + CSS inspection)
# ---------------------------------------------------------------------------


class TestUPL4SkipLink:
    """``base.html`` carries the skip-link + ``<main id="main" tabindex="-1">``;
    ``app.css`` carries the matching ``.skip-link`` visually-hidden-then-revealed
    rule."""

    def test_skip_link_is_first_body_child(self) -> None:
        # The skip-link must come BEFORE the header so a keyboard user reaches
        # it on the first Tab press. WCAG SC 2.4.1.
        body_open = BASE_HTML.index("<body>")
        first_header = BASE_HTML.index("<header>")
        skip_link_idx = BASE_HTML.index('<a class="skip-link"')
        assert body_open < skip_link_idx < first_header, (
            "skip-link must appear between <body> and the first <header>"
        )

    def test_skip_link_targets_main_anchor(self) -> None:
        assert '<a class="skip-link" href="#main">' in BASE_HTML

    def test_main_element_has_id_and_tabindex(self) -> None:
        # tabindex="-1" makes <main> programmatically focusable so the
        # skip link's href="#main" actually moves keyboard focus, not just
        # scrolls. Per MDN tabindex + WebAIM G1.
        assert '<main id="main" tabindex="-1">' in BASE_HTML

    def test_skip_link_css_rule_present(self) -> None:
        assert ".skip-link {" in APP_CSS
        assert ".skip-link:focus-visible {" in APP_CSS

    def test_skip_link_default_state_is_visually_hidden(self) -> None:
        # WebAIM G1: the default state must be off-screen, NOT display:none
        # (which would remove it from the keyboard nav order).
        rule_start = APP_CSS.index(".skip-link {")
        rule_block = APP_CSS[rule_start : rule_start + 250]
        # Off-screen via absolute position + negative left.
        assert "position: absolute" in rule_block
        assert "left: -9999px" in rule_block
        # NOT removed from DOM/AT.
        assert "display: none" not in rule_block
        assert "visibility: hidden" not in rule_block

    def test_skip_link_revealed_state_is_position_fixed_with_zindex(self) -> None:
        # Per research-synthesis D2: use position: fixed (not absolute) so the
        # revealed link stays in the viewport regardless of scroll. z-index
        # ensures visibility above the header.
        rule_start = APP_CSS.index(".skip-link:focus-visible {")
        rule_block = APP_CSS[rule_start : rule_start + 400]
        assert "position: fixed" in rule_block
        assert "z-index:" in rule_block
        assert "var(--accent)" in rule_block  # background uses the brand color


# ---------------------------------------------------------------------------
# UPL-3 — aria-live on htmx success swap targets (templates + server fragments)
# ---------------------------------------------------------------------------
#
# The most-critical UPL: the outerHTML swap REPLACES the live-region element
# entirely, so the SERVER-RENDERED FRAGMENT must also carry aria-live. The
# tests below split into:
#
#   - "static template" assertions (the initial render before any htmx swap)
#   - "server fragment" assertions (the body returned by the swap endpoints)
#
# A future refactor that updates only the template (drift) would silently
# break the live region; the server-fragment tests are the load-bearing
# protection.


class TestUPL3StaticTemplateAriaLive:
    """The static templates emit ``aria-live`` on the 4 swap targets."""

    def test_status_badge_template_has_aria_live_and_aria_atomic(self) -> None:
        # base.html — the static placeholder before the first poll.
        idx = BASE_HTML.index('id="status-badge"')
        attrs = BASE_HTML[idx : idx + 500]
        assert 'aria-live="polite"' in attrs
        assert 'aria-atomic="true"' in attrs

    def test_display_name_block_template_has_aria_live(self) -> None:
        # notebook_detail.html — the static initial render.
        idx = NOTEBOOK_DETAIL_HTML.index('id="display-name-block"')
        attrs = NOTEBOOK_DETAIL_HTML[idx : idx + 300]
        assert 'aria-live="polite"' in attrs

    def test_ingest_status_template_has_aria_live_and_aria_atomic(self) -> None:
        # notebook_detail.html — the static "Loading…" placeholder. Both
        # attributes are required for parity with the swap fragments (m1-rect
        # F1 added aria-atomic).
        idx = NOTEBOOK_DETAIL_HTML.index('id="ingest-status"')
        attrs = NOTEBOOK_DETAIL_HTML[idx : idx + 500]
        assert 'aria-live="polite"' in attrs
        assert 'aria-atomic="true"' in attrs

    def test_papers_tbody_template_has_aria_live(self) -> None:
        # notebook_detail.html — beforeend swap target; the tbody itself is
        # never replaced so the static attribute is enough.
        idx = NOTEBOOK_DETAIL_HTML.index('id="papers-tbody"')
        attrs = NOTEBOOK_DETAIL_HTML[idx : idx + 300]
        assert 'aria-live="polite"' in attrs


class TestUPL3DisplayNameFragmentAriaLive:
    """``_display_name_fragment`` emits ``aria-live`` on its returned <p>.

    Without this, the live region goes silent after the first rename swap.
    """

    def test_display_name_fragment_includes_aria_live(self) -> None:
        # Unit-test the fragment in isolation — no fixture, no event loop.
        out = _display_name_fragment("Bridgeland Stability")
        assert 'aria-live="polite"' in out
        # Sanity: the element id and class are preserved across the
        # attribute addition (no breakage of the swap-target contract).
        assert 'id="display-name-block"' in out
        assert 'class="display-name"' in out

    def test_display_name_fragment_aria_live_on_empty_name(self) -> None:
        # The empty path renders the em-dash placeholder; aria-live must
        # still be present (rename to-empty IS a state change worth
        # announcing).
        out = _display_name_fragment("")
        assert 'aria-live="polite"' in out
        assert ">—<" in out


class TestUPL3IngestStatusFragmentAriaLive:
    """Every ``_ingest_status_fragment`` branch emits ``aria-live`` AND
    ``aria-atomic`` on its <div>.

    Four code paths: none / running / success / failed. All four must carry
    BOTH attributes — ``aria-live`` so the live-region fires after the
    outerHTML swap, and ``aria-atomic="true"`` (m1-rect F1) so the AT re-reads
    the whole composite string ("Status: success · Finished … · Run #42")
    rather than guessing diffs on a whole-element replacement.
    """

    def test_ingest_status_fragment_none_includes_aria_live(self) -> None:
        out = _ingest_status_fragment(
            slug="bridgeland-stability",
            run_id=None,
            status="none",
            started_at=None,
            finished_at=None,
            exit_code=None,
            stderr_tail=None,
        )
        assert 'data-status="none"' in out
        assert 'aria-live="polite"' in out
        assert 'aria-atomic="true"' in out

    def test_ingest_status_fragment_running_includes_aria_live(self) -> None:
        out = _ingest_status_fragment(
            slug="bridgeland-stability",
            run_id=42,
            status="running",
            started_at="2026-05-30T10:00:00Z",
            finished_at=None,
            exit_code=None,
            stderr_tail=None,
        )
        assert 'data-status="running"' in out
        assert 'aria-live="polite"' in out
        assert 'aria-atomic="true"' in out

    def test_ingest_status_fragment_success_includes_aria_live(self) -> None:
        out = _ingest_status_fragment(
            slug="bridgeland-stability",
            run_id=42,
            status="success",
            started_at="2026-05-30T10:00:00Z",
            finished_at="2026-05-30T10:05:00Z",
            exit_code=0,
            stderr_tail=None,
        )
        assert 'data-status="success"' in out
        assert 'aria-live="polite"' in out
        assert 'aria-atomic="true"' in out

    def test_ingest_status_fragment_failed_includes_aria_live(self) -> None:
        out = _ingest_status_fragment(
            slug="bridgeland-stability",
            run_id=42,
            status="failed",
            started_at="2026-05-30T10:00:00Z",
            finished_at="2026-05-30T10:05:00Z",
            exit_code=1,
            stderr_tail="boom",
        )
        assert 'data-status="failed"' in out
        assert 'aria-live="polite"' in out
        assert 'aria-atomic="true"' in out


# ---------------------------------------------------------------------------
# UPL-3 server endpoint — /ui/status-badge fragment carries aria-live
# ---------------------------------------------------------------------------


@pytest.fixture
def status_badge_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Minimal app for hitting GET /ui/status-badge.

    The /ui/status-badge endpoint depends on ``app.state.resources`` (compute_
    health machinery + corpus version + config.data_dir/ops_dir). We mirror
    the ``_FakeResources`` shape from tests/test_status_endpoint.py — warm +
    healthy → status-badge--ok.
    """
    import json as _json
    import time as _time
    from datetime import UTC, datetime
    from types import SimpleNamespace

    class _FakeResources:
        def __init__(self, data_dir: Path, ops_dir: Path) -> None:
            self.warm = True
            self.degraded = None
            self.corpus_info = SimpleNamespace(version=7, chunk_count=100)
            self.process_start_time_seconds = _time.time() - 3600
            self.config = SimpleNamespace(data_dir=data_dir, ops_dir=ops_dir)

        def is_resource_warm(self, name: str) -> bool:
            if name in ("embedder", "lancedb"):
                return True
            if name == "reranker":
                return False
            raise KeyError(name)

    base = tmp_path / "notebooks"
    base.mkdir()
    ops_dir = tmp_path / "ops"
    ops_dir.mkdir(parents=True, exist_ok=True)
    # The "backup-status.json freshness" check warns when missing/stale; a
    # recent success entry keeps the badge in "ok" territory.
    (ops_dir / "backup-status.json").write_text(
        _json.dumps({
            "finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "success",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.state.resources = _FakeResources(data_dir=tmp_path, ops_dir=ops_dir)
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


class TestUPL3StatusBadgeEndpoint:
    """GET /ui/status-badge returns a fragment carrying aria-live + aria-atomic.

    The 10s poll's outerHTML swap REPLACES the <span>; without these attributes
    on the returned fragment, the live region goes silent after the first
    poll.
    """

    def test_status_badge_endpoint_fragment_has_aria_live(
        self, status_badge_client: TestClient
    ) -> None:
        r = status_badge_client.get("/ui/status-badge")
        assert r.status_code == 200
        # The fragment IS the response body (no surrounding chrome).
        text = r.text
        assert 'id="status-badge"' in text
        assert 'aria-live="polite"' in text
        assert 'aria-atomic="true"' in text
