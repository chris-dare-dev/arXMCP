"""ui-attractive-polish-m2 — visible polish layer (UPL-9, -10, -19 v0, -23, -25).

Regression tests for the 5 visible-polish items from the
2026-05-ui-polish uplift, all bundled into one milestone:

- **UPL-9** Replace ``filter: brightness(1.08)`` button-hover with
  ``color-mix(in oklab, var(--accent) 88%, white)``. The replacement
  IS the assertion — if a future change reverts to ``filter:
  brightness()``, the test fails.
- **UPL-10** ``font-variant-numeric: tabular-nums`` on every numeric
  surface that changes on htmx swap (``time``, ``.status-badge``,
  ``dl.meta dd``, ``td code``).
- **UPL-19 v0** ``<div class="table-wrap">`` wrapping both tables +
  ``.table-wrap { overflow-x: auto }`` in CSS. The wider
  ``body { max-width: clamp(…) }`` expansion is descoped to v1 — the
  regression test ASSERTS the current ``980px`` ceiling stays.
- **UPL-23** Five footer ``·`` interpuncts wrapped in
  ``<span aria-hidden="true">·</span>``. The assertion checks both
  that wrappers exist AND that no bare interpunct survives the wrap.
- **UPL-25** ``frontend/static/favicon.svg`` exists (valid XML, uses
  hardcoded hex not CSS variable) + ``<link rel="icon">`` references
  it in ``base.html`` ``<head>``.

These tests deliberately do NOT touch m1's a11y assertions in
``tests/test_ui_a11y_baselines.py`` — m2 is conceptually a separate
surface (visible polish vs a11y baseline).
"""

from __future__ import annotations

import re as _re
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "frontend" / "static"
FRONTEND_TEMPLATES: Path = REPO_ROOT / "frontend" / "templates"

APP_CSS: str = (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8")
#: ``app.css`` with /* ... */ CSS comments stripped, so substring checks for
#: rule-text don't accidentally match inline-comment documentation that
#: REFERENCES a pattern (e.g. "replace `filter: brightness(...)` with ...").
APP_CSS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", APP_CSS, flags=_re.S)
BASE_HTML: str = (FRONTEND_TEMPLATES / "base.html").read_text(encoding="utf-8")
INDEX_HTML: str = (FRONTEND_TEMPLATES / "index.html").read_text(encoding="utf-8")
NOTEBOOK_DETAIL_HTML: str = (
    FRONTEND_TEMPLATES / "notebook_detail.html"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# UPL-9 — color-mix() button hover replacement
# ---------------------------------------------------------------------------


class TestUPL9ColorMix:
    """``button:hover`` uses ``color-mix(in oklab, ...)`` instead of
    ``filter: brightness(...)``."""

    def test_filter_brightness_removed(self) -> None:
        # The prior `filter: brightness(1.08)` rule must be gone. If a
        # future refactor reverts to it, the regression fires loudly.
        # Scan the comment-stripped CSS so the documentation comment
        # ("replace `filter: brightness(1.08)` with color-mix()...")
        # is not a false positive.
        assert "filter: brightness" not in APP_CSS_NO_COMMENTS, (
            "UPL-9 regression: filter: brightness(...) reverted; "
            "should use color-mix(in oklab, ...) instead"
        )

    def test_color_mix_oklab_present_on_button_hover(self) -> None:
        # The replacement IS the assertion. oklab is the recommended
        # color space (MDN: srgb produces overly-dark mixes).
        assert "color-mix(in oklab" in APP_CSS, (
            "UPL-9 regression: color-mix(in oklab, ...) missing"
        )
        # Locate the button hover rule and confirm the mix is on it,
        # not on some unrelated selector.
        idx = APP_CSS.index("button:hover")
        rule_block = APP_CSS[idx : idx + 300]
        assert "color-mix(in oklab" in rule_block

    def test_button_hover_uses_accent_token(self) -> None:
        # The mix must derive from --accent (the token system); a
        # hardcoded hex would violate the 8-variable token discipline.
        idx = APP_CSS.index("button:hover")
        rule_block = APP_CSS[idx : idx + 300]
        assert "var(--accent)" in rule_block


# ---------------------------------------------------------------------------
# UPL-10 — tabular-nums
# ---------------------------------------------------------------------------


class TestUPL10TabularNums:
    """``font-variant-numeric: tabular-nums`` on numeric surfaces."""

    def test_tabular_nums_rule_present(self) -> None:
        assert "font-variant-numeric: tabular-nums" in APP_CSS

    def test_tabular_nums_covers_required_selectors(self) -> None:
        # Locate the tnum rule and assert it covers every digit-bearing
        # surface that changes on htmx swap: timestamps, the operability
        # badge, the metadata dl values, and per-paper IDs in tables.
        idx = APP_CSS.index("font-variant-numeric: tabular-nums")
        # Look backward to capture the selector list (~200 chars
        # comfortably covers the multi-selector block).
        selector_block = APP_CSS[max(0, idx - 300) : idx]
        for sel in ("time", ".status-badge", "dl.meta dd", "td code"):
            assert sel in selector_block, (
                f"UPL-10 selector {sel!r} missing from the tabular-nums "
                f"rule's selector list"
            )


# ---------------------------------------------------------------------------
# UPL-19 v0 — .table-wrap mobile fix
# ---------------------------------------------------------------------------


class TestUPL19TableWrap:
    """``.table-wrap { overflow-x: auto }`` + both tables wrapped."""

    def test_table_wrap_rule_present(self) -> None:
        assert ".table-wrap" in APP_CSS
        idx = APP_CSS.index(".table-wrap")
        rule_block = APP_CSS[idx : idx + 200]
        assert "overflow-x: auto" in rule_block

    def test_index_table_wrapped(self) -> None:
        # The notebooks table must be inside a .table-wrap div.
        # Find the <table class="notebooks"> and walk backward to find
        # the preceding open-div.
        idx = INDEX_HTML.index('<table class="notebooks">')
        # The .table-wrap wrapper should be within ~300 chars before the
        # table (the Jinja2 if-else preamble fits comfortably).
        preamble = INDEX_HTML[max(0, idx - 300) : idx]
        assert '<div class="table-wrap">' in preamble, (
            "UPL-19 v0: <table class=\"notebooks\"> in index.html is not "
            "wrapped by <div class=\"table-wrap\">"
        )

    def test_notebook_detail_table_wrapped(self) -> None:
        idx = NOTEBOOK_DETAIL_HTML.index('<table class="papers">')
        preamble = NOTEBOOK_DETAIL_HTML[max(0, idx - 500) : idx]
        assert '<div class="table-wrap">' in preamble, (
            "UPL-19 v0: <table class=\"papers\"> in notebook_detail.html "
            "is not wrapped by <div class=\"table-wrap\">"
        )

    def test_body_max_width_980px_preserved(self) -> None:
        # The wider clamp(640px, 92vw, 1400px) expansion is descoped to
        # v1 per the challenger. m2 v0 preserves the 980px ceiling.
        # If a future commit accidentally lands the v1 expansion, this
        # test reminds the implementer it requires its own milestone.
        assert "max-width: 980px" in APP_CSS, (
            "UPL-19 v0: body max-width: 980px is the v0 ceiling; the "
            "wider clamp(...) is descoped to v1 per the challenger."
        )


# ---------------------------------------------------------------------------
# UPL-23 — footer interpunct aria-hidden
# ---------------------------------------------------------------------------


class TestUPL23FooterInterpunct:
    """Five footer ``·`` interpuncts wrapped in
    ``<span aria-hidden="true">·</span>``."""

    def test_aria_hidden_interpunct_count_is_five(self) -> None:
        # The footer has exactly 5 separator dots; each must be
        # individually wrapped. (The remaining 2 dots in base.html live
        # inside a Jinja2 {# ... #} comment — stripped at render time
        # and never reach the rendered HTML.)
        wrapped = BASE_HTML.count('<span aria-hidden="true">·</span>')
        assert wrapped == 5, (
            f"UPL-23 expected 5 wrapped interpuncts, found {wrapped}"
        )

    def test_no_bare_interpunct_in_rendered_footer(self) -> None:
        # Find the footer block and assert no bare `·` survives the
        # wrap. (Jinja2 comments are stripped at render time so we
        # excise them before scanning.)
        # Strip Jinja2 {# ... #} comments (which never reach the DOM).
        jinja_stripped = _re.sub(r"\{\#.*?\#\}", "", BASE_HTML, flags=_re.S)
        # Strip HTML comments too (rendered but invisible to ATs).
        html_stripped = _re.sub(r"<!--.*?-->", "", jinja_stripped, flags=_re.S)
        # Now extract the footer.
        footer_start = html_stripped.index("<footer>")
        footer_end = html_stripped.index("</footer>")
        footer = html_stripped[footer_start:footer_end]
        # Every `·` in the rendered footer must be inside a
        # <span aria-hidden="true">. We assert this by checking that
        # the count of bare `·` outside any <span...>·</span> wrapper
        # equals zero. The simplest proxy: count `·` in the footer,
        # count `<span aria-hidden="true">·</span>` in the footer,
        # assert equality.
        bare_dots = footer.count("·")
        wrapped_dots = footer.count('<span aria-hidden="true">·</span>')
        assert bare_dots == wrapped_dots, (
            f"UPL-23: footer has {bare_dots} interpuncts but only "
            f"{wrapped_dots} are wrapped in aria-hidden spans"
        )


# ---------------------------------------------------------------------------
# UPL-25 — favicon SVG + <link rel="icon">
# ---------------------------------------------------------------------------


class TestUPL25Favicon:
    """``frontend/static/favicon.svg`` exists, is valid XML, uses
    hardcoded hex; ``base.html`` ``<head>`` carries the matching
    ``<link rel="icon">``."""

    def test_favicon_svg_file_exists(self) -> None:
        favicon = FRONTEND_STATIC / "favicon.svg"
        assert favicon.exists(), (
            "UPL-25: frontend/static/favicon.svg is missing"
        )

    def test_favicon_svg_parses_as_xml(self) -> None:
        # SVG is XML; if it doesn't parse, the browser will refuse to
        # render it as a favicon.
        favicon = FRONTEND_STATIC / "favicon.svg"
        text = favicon.read_text(encoding="utf-8")
        # A bad SVG raises ET.ParseError — let it propagate to fail the
        # test loudly with the parse details.
        root = ET.fromstring(text)
        # The root element must be the SVG namespace.
        assert root.tag.endswith("svg"), (
            f"UPL-25: favicon root element is {root.tag!r}, expected svg"
        )

    def test_favicon_uses_hardcoded_hex_not_css_var(self) -> None:
        # Browsers render favicons in the tab context, OUTSIDE the page
        # CSS, so var(--accent) would not resolve. The fill must be a
        # hardcoded hex. Both researchers flagged this independently —
        # this regression test protects against a future refactor
        # accidentally introducing var(--...) in the SVG.
        favicon = FRONTEND_STATIC / "favicon.svg"
        text = favicon.read_text(encoding="utf-8")
        assert "var(--" not in text, (
            "UPL-25: favicon.svg references a CSS variable; favicons "
            "render outside page CSS, so use a hardcoded hex (e.g. "
            "#1e5b8a matching --accent)."
        )
        # And it should use a recognizable hex. We assert presence of
        # SOME hex literal (matching e.g. "#1e5b8a") without pinning the
        # exact value — design choice is the implementer's.
        assert _re.search(r"#[0-9a-fA-F]{3,6}", text), (
            "UPL-25: favicon.svg has no hex color literal"
        )

    def test_base_html_link_icon_present(self) -> None:
        # The <link rel="icon"> must reference the SVG with the correct
        # MIME type.
        assert '<link rel="icon"' in BASE_HTML
        # Find the link and assert it points at /ui/static/favicon.svg.
        idx = BASE_HTML.index('<link rel="icon"')
        link_block = BASE_HTML[idx : idx + 200]
        assert "/ui/static/favicon.svg" in link_block
        assert 'type="image/svg+xml"' in link_block

    def test_link_icon_is_in_head(self) -> None:
        # The <link> must appear inside <head>, not somewhere weird like
        # the body. Otherwise the browser ignores the favicon hint.
        head_start = BASE_HTML.index("<head>")
        head_end = BASE_HTML.index("</head>")
        head_block = BASE_HTML[head_start:head_end]
        assert '<link rel="icon"' in head_block, (
            "UPL-25: <link rel=\"icon\"> is not inside <head> — browser "
            "won't pick it up"
        )
