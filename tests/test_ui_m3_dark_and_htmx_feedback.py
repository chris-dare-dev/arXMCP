"""ui-attractive-polish-m3 — dark mode (UPL-8 v0) + htmx-request feedback (UPL-11).

Regression tests for the two e3 polish items bundled into m3:

- **UPL-8 v0** — ``@media (prefers-color-scheme: dark) { :root { … } }``
  redeclares the 8 base tokens with GitHub-Primer-anchored dark values.
  Status-pill modifier colors + `th` table-header are explicitly descoped
  to a v1 follow-on (per the challenger v0/v1 split).
- **UPL-11** — CSS rules for htmx's auto-applied ``.htmx-request`` class
  (button dim + spinner) + ``hx-disabled-elt`` HTML attributes on the 8
  htmx-bound interactive elements for keyboard a11y parity.

Tests follow the m1/m2 patterns: read ``APP_CSS_NO_COMMENTS`` for
structural assertions (so documentation comments containing asserted
substrings aren't false-positives) and regex-pin to specific CSS blocks
where order matters.

Load-bearing correctness fixes from the research synthesis (§2):

- **C1** ``--border #6e7681`` (NOT canonical Primer ``#30363d`` which
  fails SC 1.4.11 at 1.55:1).
- **C2** ``button, .button { color: #0d1117 }`` inside the dark block
  (white-on-#58a6ff is only 3.1:1; fails SC 1.4.3).
- **C3** ``button.danger.htmx-request:focus-visible { outline-width:
  3px }`` (m1's 2px danger ring at 0.6 opacity falls to 2.57:1; fails
  SC 1.4.11).
- **C4** ``hx-disabled-elt="find button"`` on the 5 ``<form>`` elements
  (NOT ``"this"`` — the HTML ``disabled`` attribute is non-standard on
  ``<form>``); ``hx-disabled-elt="this"`` on the 3 standalone ``<button>``
  elements.
- **C5** combined htmx-request selector chain (``form.htmx-request
  button[type="submit"], button.htmx-request, .button.htmx-request``)
  handles both form-triggered and button-triggered cases.
"""

from __future__ import annotations

import re as _re
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "frontend" / "static"
FRONTEND_TEMPLATES: Path = REPO_ROOT / "frontend" / "templates"

APP_CSS: str = (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8")
APP_CSS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", APP_CSS, flags=_re.S)
INDEX_HTML: str = (FRONTEND_TEMPLATES / "index.html").read_text(encoding="utf-8")
NOTEBOOK_DETAIL_HTML: str = (
    FRONTEND_TEMPLATES / "notebook_detail.html"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Dark-mode block (UPL-8 v0) — token redeclaration + C1 + C2 corrections
# ---------------------------------------------------------------------------


class TestUPL8DarkModeBlock:
    """``@media (prefers-color-scheme: dark) { :root { … } }`` re-declares
    all 8 base tokens with WCAG-AA-compliant values."""

    #: Regex matching the dark-mode :root block. Capture group is the block body.
    _DARK_ROOT_RE = _re.compile(
        r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{[^}]*:root\s*\{([^}]*)\}",
        flags=_re.S,
    )

    def _dark_root_block(self) -> str:
        m = self._DARK_ROOT_RE.search(APP_CSS_NO_COMMENTS)
        assert m is not None, (
            "UPL-8 v0: no @media (prefers-color-scheme: dark) { :root { … } } "
            "block found in app.css"
        )
        return m.group(1)

    def test_dark_root_block_exists(self) -> None:
        # The presence assertion is the implicit-fail path for the helper.
        self._dark_root_block()

    def test_dark_block_redeclares_all_seven_color_tokens(self) -> None:
        # UPL-8 v0: all 8 base tokens re-declared with dark values. --mono is
        # the only token that legitimately stays light (it's a font-family,
        # not a color), so 7 color tokens MUST appear in the dark block.
        block = self._dark_root_block()
        for token in ("--fg", "--bg", "--card-bg", "--border", "--accent",
                       "--danger", "--error-bg"):
            assert token in block, (
                f"UPL-8 v0: dark-mode :root block missing redeclaration of "
                f"{token}"
            )

    def test_dark_border_uses_corrected_hex_not_primer_canonical(self) -> None:
        # synthesis §2 C1: Primer's canonical #30363d gives only 1.55:1 against
        # --bg #0d1117 — fails SC 1.4.11 (3:1 non-text). #6e7681 gives 4.12:1
        # and passes with margin. If a future refactor reverts to #30363d,
        # this regression fires.
        block = self._dark_root_block()
        assert "#6e7681" in block, (
            "UPL-8 v0 C1 regression: dark --border must be #6e7681 (4.12:1 on "
            "--bg, passes SC 1.4.11). Primer canonical #30363d fails 1.55:1."
        )
        # And the failed canonical value MUST NOT be present in the dark
        # block — protects against the WCAG-failing alternative slipping
        # back in.
        assert "#30363d" not in block, (
            "UPL-8 v0 C1 regression: dark --border #30363d fails SC 1.4.11 "
            "(1.55:1). Use #6e7681 instead."
        )

    def test_color_scheme_declared_on_root(self) -> None:
        # m3-rect F3 (MEDIUM): the initial :root must declare `color-scheme:
        # light dark` so browsers auto-darken UA-styled controls (form
        # internals, scrollbars, default focus rings, native dropdowns)
        # when prefers-color-scheme: dark fires. Without it, the white
        # input background defect (F1) renders deterministically across
        # Chromium-family browsers.
        # Scope the assertion to the INITIAL :root block (before any
        # @media query), so a future dark-block edit can't accidentally
        # satisfy this by adding color-scheme inside the @media.
        initial_root_re = _re.compile(
            r"^:root\s*\{([^}]*)\}", flags=_re.S | _re.M
        )
        m = initial_root_re.search(APP_CSS_NO_COMMENTS)
        assert m is not None, (
            "m3-rect F3: initial :root { ... } block not found at the top "
            "of app.css"
        )
        initial_root = m.group(1)
        assert _re.search(r"color-scheme:\s*light\s+dark", initial_root), (
            "m3-rect F3 regression: `color-scheme: light dark` missing from "
            "initial :root. Without it, browsers don't auto-darken UA-styled "
            "controls (form internals, scrollbars) when prefers-color-scheme: "
            "dark fires — compounds the F1 invisible-input bug."
        )

    def test_dark_block_redeclares_text_input_for_visibility(self) -> None:
        # m3-rect F1 (HIGH): the text-input rule at app.css:62-72 hardcodes
        # background: #fff with no color: — in dark mode the input inherits
        # color: var(--fg) = #e8e8e8 on white = 1.22:1, typed text
        # invisible. The dark @media block MUST override both background
        # and color to restore visibility.
        full_dark_block_re = _re.compile(
            r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        m = full_dark_block_re.search(APP_CSS_NO_COMMENTS)
        assert m is not None, "dark @media block not found"
        dark_full = m.group(1)
        # Search for the input rule inside the dark block. Must redeclare
        # BOTH background (so #fff is overridden) AND color (so typed text
        # is visible).
        input_rule = _re.search(
            r'input\[type="text"\][^{]*\{[^}]*background:\s*var\(--card-bg\)[^}]*color:\s*var\(--fg\)',
            dark_full,
            flags=_re.S,
        )
        # Also accept the rules in the other order (color before background).
        if input_rule is None:
            input_rule = _re.search(
                r'input\[type="text"\][^{]*\{[^}]*color:\s*var\(--fg\)[^}]*background:\s*var\(--card-bg\)',
                dark_full,
                flags=_re.S,
            )
        assert input_rule is not None, (
            "m3-rect F1 regression: inside @media (prefers-color-scheme: "
            "dark), the text-input rule must override BOTH `background: "
            "var(--card-bg)` AND `color: var(--fg)`. Otherwise dark-mode "
            "typed text is invisible (white bg, light --fg, 1.22:1)."
        )

    def test_dark_block_remaps_tertiary_text_greys(self) -> None:
        # m3-rect F2 (MEDIUM): the dark @media block must redeclare
        # `color:` for the hardcoded-grey tertiary-text selectors (subtitle,
        # hint, note, empty, display-name, dt, footer, footer a). Otherwise
        # they render at 1.5:1–4.5:1 in dark mode — fail or borderline SC
        # 1.4.3. We assert by presence of representative selector tokens
        # inside the dark @media block.
        full_dark_block_re = _re.compile(
            r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        m = full_dark_block_re.search(APP_CSS_NO_COMMENTS)
        assert m is not None
        dark_full = m.group(1)
        for sel_token in (
            "header .subtitle",
            ".card .hint",
            ".card .note",
            ".card .empty",
            ".card .display-name",
            "dl.meta dt",
            "footer",
        ):
            assert sel_token in dark_full, (
                f"m3-rect F2: dark @media block missing remap for "
                f"{sel_token!r}. Hardcoded greys (#444-#888) become "
                f"low-contrast on dark backgrounds — fail SC 1.4.3."
            )

    def test_dark_block_corrects_button_text_color(self) -> None:
        # synthesis §2 C2: white text on dark --accent #58a6ff gives ~3.1:1
        # for 14px text — fails SC 1.4.3 (4.5:1 text). Dark text (#0d1117)
        # gives ~7.2:1. The fix is a single `button, .button { color: ... }`
        # inside the dark @media block.
        # Find the dark @media block and look for the button color rule
        # inside it.
        full_dark_block_re = _re.compile(
            r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        m = full_dark_block_re.search(APP_CSS_NO_COMMENTS)
        assert m is not None, "dark @media block not found"
        dark_full = m.group(1)
        # The button rule must reside inside the dark @media block.
        assert _re.search(
            r"button\s*,\s*\.button\s*\{[^}]*color:\s*#0d1117[^}]*\}",
            dark_full,
            flags=_re.S,
        ), (
            "UPL-8 v0 C2 regression: inside @media (prefers-color-scheme: "
            "dark), `button, .button { color: #0d1117 }` is missing. White "
            "text on dark --accent #58a6ff = ~3.1:1, fails SC 1.4.3 at 14px."
        )


# ---------------------------------------------------------------------------
# htmx-request loading state (UPL-11) — dim + spinner + C3 focus-ring fix
# ---------------------------------------------------------------------------


class TestUPL11HtmxRequestStyling:
    """``.htmx-request`` triggers visible dim/spinner; spinner gated by
    ``prefers-reduced-motion: no-preference``; danger focus-ring widened
    to compensate for opacity reduction."""

    def test_htmx_request_dim_rules_present(self) -> None:
        # The combined selector chain (synthesis §2 C5) covers both
        # form-triggered (form.htmx-request -> descendant submit button)
        # AND button-triggered (button.htmx-request directly).
        for sel in (
            "form.htmx-request button[type=\"submit\"]",
            "button.htmx-request",
            ".button.htmx-request",
        ):
            assert sel in APP_CSS_NO_COMMENTS, (
                f"UPL-11 C5: missing selector {sel!r} from the htmx-request "
                f"styling block (chain must cover both form-triggered and "
                f"button-triggered cases)."
            )

    def test_htmx_request_dim_properties_are_unconditional(self) -> None:
        # opacity / pointer-events / cursor are SIGNAL, not motion — must
        # NOT be inside a prefers-reduced-motion no-preference block (per
        # challenger m1 UPL-11 finding). Reduced-motion users should still
        # see the dim/cursor change, just not the spin animation.
        # Find the htmx-request rule with opacity:0.6 and verify it's NOT
        # nested inside a prefers-reduced-motion media query.
        # Heuristic: search for the first opacity:0.6 occurrence and check
        # the surrounding 600 chars don't show a prefers-reduced-motion
        # opening before it.
        idx = APP_CSS_NO_COMMENTS.index("opacity: 0.6")
        # Walk backward to find the nearest unmatched `{` — if it's a
        # @media block, check whether it's prefers-reduced-motion.
        backward = APP_CSS_NO_COMMENTS[max(0, idx - 800) : idx]
        # The nearest media-open before opacity should NOT be reduced-motion.
        prm_no_pref = backward.rfind("@media (prefers-reduced-motion: no-preference)")
        prm_reduce = backward.rfind("@media (prefers-reduced-motion: reduce)")
        # Counts of `{` and `}` between any media-open and the opacity rule
        # determine nesting; for simplicity, just assert that the closest
        # @media-open before opacity isn't a prefers-reduced-motion one.
        # (Stronger heuristic: assert that the unconditional rule precedes
        # the no-preference block in the file.)
        if prm_no_pref != -1:
            # If a no-preference block opens earlier in the file, ensure it
            # also CLOSES before opacity is declared. Brace-count from the
            # block opening to the opacity index.
            block_start = max(prm_no_pref, prm_reduce)
            between = APP_CSS_NO_COMMENTS[block_start:idx]
            assert between.count("{") == between.count("}"), (
                "UPL-11 challenger lesson: opacity/pointer-events/cursor "
                "appear to be inside a prefers-reduced-motion block. They "
                "are SIGNAL not motion — must be UNCONDITIONAL."
            )

    def test_spinner_animation_gated_by_no_preference(self) -> None:
        # The spin keyframe + animation MUST live inside @media
        # (prefers-reduced-motion: no-preference). This is the m1 motion-
        # vocabulary MOT-NO-5 lesson — any animation that omits this gate
        # is a Phase-3 BLOCKER.
        no_pref_block_re = _re.compile(
            r"@media\s*\(\s*prefers-reduced-motion:\s*no-preference\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        m = no_pref_block_re.search(APP_CSS_NO_COMMENTS)
        assert m is not None, (
            "UPL-11 motion gate: @media (prefers-reduced-motion: no-preference) "
            "block is missing — the spin animation MUST be gated by it "
            "(motion-vocabulary MOT-NO-5)."
        )
        no_pref_body = m.group(1)
        assert "@keyframes spin" in no_pref_body, (
            "UPL-11 motion gate: @keyframes spin must be INSIDE the "
            "prefers-reduced-motion: no-preference block."
        )
        assert "animation: spin" in no_pref_body, (
            "UPL-11 motion gate: the .htmx-request::after spinner must apply "
            "`animation: spin` INSIDE the prefers-reduced-motion: no-preference "
            "block."
        )

    def test_spinner_after_pseudo_present_on_combined_selector(self) -> None:
        # The ::after spinner must also use the combined selector chain
        # (C5) so it fires for both form-triggered and button-triggered
        # requests.
        for sel in (
            "form.htmx-request button[type=\"submit\"]::after",
            "button.htmx-request::after",
            ".button.htmx-request::after",
        ):
            assert sel in APP_CSS_NO_COMMENTS, (
                f"UPL-11 C5 spinner: missing ::after selector {sel!r}."
            )

    def test_danger_focus_ring_widened_under_htmx_request(self) -> None:
        # synthesis §2 C3: m1's `button.danger:focus-visible { outline: 2px
        # solid var(--danger) }` at 0.6 opacity (mid-htmx-request) drops to
        # ~2.57:1 contrast — fails SC 1.4.11. Widening to 3px at the same
        # opacity restores perceptible focus. 1-LOC compensation.
        assert _re.search(
            r"button\.danger\.htmx-request:focus-visible\s*\{[^}]*outline-width:\s*3px",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        ), (
            "UPL-11 C3 regression: button.danger.htmx-request:focus-visible "
            "{ outline-width: 3px } missing. m1's 2px danger ring at 0.6 "
            "opacity falls to 2.57:1 — fails SC 1.4.11."
        )


# ---------------------------------------------------------------------------
# hx-disabled-elt attribute additions (UPL-11 part 2) — C4 form vs button
# ---------------------------------------------------------------------------


class TestUPL11HxDisabledEltAttributes:
    """All 8 htmx-bound elements carry hx-disabled-elt with the correct
    target — forms get ``find button``, standalone buttons get ``this``."""

    def test_forms_use_find_button_not_this(self) -> None:
        # synthesis §2 C4: <form> elements MUST use hx-disabled-elt="find
        # button" (the disabled HTML attribute is non-standard on <form>;
        # browsers don't propagate it to children). Targeting the submit
        # button is the correct pattern.
        #
        # Build a regex that finds every <form ... hx-... ...> block and
        # asserts each contains `hx-disabled-elt="find button"`.
        form_re = _re.compile(
            r"<form\s+[^>]*?hx-[a-z]+=[^>]*?>",
            flags=_re.S,
        )
        index_forms = form_re.findall(INDEX_HTML)
        detail_forms = form_re.findall(NOTEBOOK_DETAIL_HTML)
        all_forms = index_forms + detail_forms
        # notebook-paper-discovery-m1 added the topic-edit <form> on the
        # detail page (PATCH /ui/api/notebooks/{slug}/topic), bringing the
        # detail count from 4 to 5 (1 index + 5 detail = 6).
        assert len(all_forms) == 6, (
            f"Expected 6 htmx-bound <form> elements total (1 index + 5 "
            f"detail); found {len(all_forms)}"
        )
        for form in all_forms:
            assert 'hx-disabled-elt="find button"' in form, (
                f"UPL-11 C4: <form> element missing "
                f'hx-disabled-elt="find button":\n  {form[:200]}'
            )

    def test_standalone_delete_buttons_use_this(self) -> None:
        # The 3 standalone <button type="button" hx-delete=...> elements
        # (Remove notebook per-row, Delete notebook on detail, Remove
        # paper per-row) use hx-disabled-elt="this" — button IS the htmx
        # requester, so `this` is correct.
        button_re = _re.compile(
            r"<button\s+type=\"button\"\s+[^>]*?hx-delete=[^>]*?>",
            flags=_re.S,
        )
        index_buttons = button_re.findall(INDEX_HTML)
        detail_buttons = button_re.findall(NOTEBOOK_DETAIL_HTML)
        all_buttons = index_buttons + detail_buttons
        assert len(all_buttons) == 3, (
            f"Expected 3 standalone <button hx-delete> elements total "
            f"(1 index + 2 detail); found {len(all_buttons)}"
        )
        for btn in all_buttons:
            assert 'hx-disabled-elt="this"' in btn, (
                f"UPL-11 C4: standalone <button> element missing "
                f'hx-disabled-elt="this":\n  {btn[:200]}'
            )

    def test_no_form_uses_disabled_elt_this(self) -> None:
        # Negative-regression — protect against a future PR adding
        # hx-disabled-elt="this" on a <form> (which would be semantically
        # broken per synthesis C4). If any <form> uses "this", the test
        # fires.
        form_re = _re.compile(
            r"<form\s+[^>]*?hx-disabled-elt=\"this\"[^>]*?>",
            flags=_re.S,
        )
        offenders = form_re.findall(INDEX_HTML) + form_re.findall(NOTEBOOK_DETAIL_HTML)
        assert offenders == [], (
            f"UPL-11 C4 regression: <form> element(s) using "
            f'hx-disabled-elt="this" — semantically broken (disabled HTML '
            f"attribute is non-standard on <form>; use \"find button\" "
            f"instead).\nOffenders: {offenders[:2]}"
        )

    def test_no_button_uses_disabled_elt_find_button(self) -> None:
        # Negative-regression mirror: standalone <button> elements should
        # not use "find button" (would target a non-existent descendant
        # button); they should use "this".
        button_re = _re.compile(
            r'<button\s+type="button"\s+[^>]*?hx-disabled-elt="find button"[^>]*?>',
            flags=_re.S,
        )
        offenders = button_re.findall(INDEX_HTML) + button_re.findall(NOTEBOOK_DETAIL_HTML)
        assert offenders == [], (
            f"UPL-11 C4 regression: standalone <button> using "
            f'hx-disabled-elt="find button" — should be "this" '
            f"(button IS the requester).\nOffenders: {offenders[:2]}"
        )


# ---------------------------------------------------------------------------
# Cross-milestone safety — m1 + m2 assertions remain compatible
# ---------------------------------------------------------------------------


class TestCrossMilestoneSafety:
    """m3 doesn't disturb m1 (a11y baselines) or m2 (visible polish) sites."""

    def test_m1_prefers_reduced_motion_reduce_block_still_present(self) -> None:
        # m1's reduce block is the foundation m3's no-preference block
        # complements. If a future m3-style edit accidentally deletes m1's
        # block, this fires.
        assert "@media (prefers-reduced-motion: reduce)" in APP_CSS_NO_COMMENTS, (
            "m3 cross-safety: m1's @media (prefers-reduced-motion: reduce) "
            "block is missing — m3 must not delete or move it."
        )

    def test_m2_color_mix_button_hover_still_present(self) -> None:
        # m2's button hover uses color-mix(in oklab, var(--accent) 88%,
        # white). m3 doesn't touch this; assert it stays.
        assert "color-mix(in oklab" in APP_CSS_NO_COMMENTS

    def test_m1_focus_visible_rule_still_present(self) -> None:
        # m1's :focus-visible rules using var(--accent) automatically
        # benefit from the dark --accent rebinding. Assert m1's rule
        # block stays present.
        assert ":focus-visible" in APP_CSS_NO_COMMENTS
        assert ":focus:not(:focus-visible) {" in APP_CSS_NO_COMMENTS

    def test_app_css_under_soft_cap(self) -> None:
        # Soft cap on `app.css` line count. Trajectory: m1 left it at
        # 190, m2 at 216, m3 (feat) at 287. m3-rect raised it further:
        # the F1 dark-mode input visibility fix + F2 tertiary-text grey
        # remap + F3 color-scheme declaration added ~19 lines of
        # NECESSARY CSS (WCAG SC 1.4.3 compliance — see m3-rect for the
        # adversary finding chain). m4 raises the cap further to 335:
        # UPL-22 added .status-badge.htmx-settling badge-flash keyframes
        # (cross-milestone affordance for the m4-status-badge) and
        # UPL-13 added a ::view-transition-old/new duration override
        # (200ms snappy crossfade for htmx 2.0.10's native View
        # Transitions integration). Both live inside a single
        # consolidated prefers-reduced-motion:no-preference block to
        # minimize line cost. A future milestone either ships under
        # 335 or argues for another cap raise. The CLAUDE.md soft cap
        # itself is loose — this test's value is the discriminating gate.
        line_count = APP_CSS.count("\n") + (1 if not APP_CSS.endswith("\n") else 0)
        assert line_count <= 335, (
            f"app.css is {line_count} lines — over the 335-line cap "
            f"(revised in m4 from 330 → 335 to accommodate UPL-22 badge "
            f"flash + UPL-13 View Transitions duration override). Consider "
            f"stripping documentation comments, splitting the file (e.g. "
            f"tokens.css + app.css), or arguing for another revision."
        )
