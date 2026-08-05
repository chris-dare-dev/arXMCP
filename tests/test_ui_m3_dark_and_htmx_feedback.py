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

- **C1** dark ``--border`` must clear SC 1.4.11 (3:1) and must not be a
  Primer grey-scale literal. *(ui-uplift-m6 re-derived every token in
  OKLCH, so the two C1/C2 tests below assert the PROPERTY rather than the
  specific hexes they used to pin — ``#6e7681`` and ``#0d1117`` — which
  turned any legitimate re-derivation into a false regression.)*
- **C2** the dark block must override the on-accent text colour so the
  resulting pair clears SC 1.4.3 (4.5:1); m6 widened that rule to cover
  ``.skip-link:focus-visible``, which had never picked it up.
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

from tests._ui_color import alpha_over, contrast_ratio, load_tokens

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "server" / "frontend" / "static"
FRONTEND_TEMPLATES: Path = REPO_ROOT / "server" / "frontend" / "templates"

APP_CSS: str = (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8")
APP_CSS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", APP_CSS, flags=_re.S)
#: ui-uplift-m7 moved the two `:root` token blocks into tokens.css. The
#: assertions in this file split cleanly: those about TOKEN VALUES read
#: TOKENS_CSS_NO_COMMENTS, those about RULES (the dark-mode input override,
#: the grey remaps, the on-accent colour) keep reading app.css, because that
#: is where those rules still live.
TOKENS_CSS: str = (FRONTEND_STATIC / "tokens.css").read_text(encoding="utf-8")
TOKENS_CSS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", TOKENS_CSS, flags=_re.S)
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
        # ui-uplift-m7: the dark :root TOKEN block moved to tokens.css. The
        # intent of this helper is unchanged — find the block that declares
        # the dark token values — so it follows the tokens rather than
        # staying pointed at the file they left.
        m = self._DARK_ROOT_RE.search(TOKENS_CSS_NO_COMMENTS)
        assert m is not None, (
            "UPL-8 v0: no @media (prefers-color-scheme: dark) { :root { … } } "
            "block found in tokens.css"
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

    def test_dark_border_is_not_a_primer_literal_and_clears_sc_1411(self) -> None:
        # ORIGINAL INTENT (UPL-8 v0 C1), preserved: Primer's canonical
        # #30363d gives only 1.55:1 against the dark canvas and fails SC
        # 1.4.11, so the dark --border must NOT be that value.
        #
        # ui-uplift-m6 generalised the assertion. It used to pin the single
        # replacement hex #6e7681, which made a legitimate re-derivation
        # look like a regression. What actually matters is the property:
        # not a Primer literal, AND clears 3:1 against BOTH of its grounds.
        # In dark mode --card-bg is LIGHTER than --bg, so --card-bg is the
        # binding ground — checking only --bg would pass a value that fails
        # where it is actually thinnest.
        from tests._ui_color import contrast_ratio, load_tokens

        block = self._dark_root_block()
        for primer in ("#30363d", "#6e7681"):
            assert primer not in block, (
                f"dark --border must not be the GitHub Primer grey-scale "
                f"literal {primer} (ui-uplift-m6 AC#1 — derive it instead)"
            )
        _light, dark = load_tokens()
        for ground in ("--bg", "--card-bg"):
            ratio = contrast_ratio(dark["--border"], dark[ground])
            assert ratio >= 3.0, (
                f"UPL-8 v0 C1 regression: dark --border on {ground} = "
                f"{ratio:.3f}:1, fails SC 1.4.11 (need >= 3:1)."
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
        # ui-uplift-m7: the base :root moved to tokens.css with the rest of
        # the token layer; `color-scheme` travels with the block it
        # configures, so this reads tokens.css. The "before any @media"
        # scoping the comment above describes still holds — the base :root
        # is the first block in that file.
        initial_root_re = _re.compile(
            r"^:root\s*\{([^}]*)\}", flags=_re.S | _re.M
        )
        m = initial_root_re.search(TOKENS_CSS_NO_COMMENTS)
        assert m is not None, (
            "m3-rect F3: initial :root { ... } block not found at the top "
            "of tokens.css"
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
        # ui-uplift-m8: the four `.card X` compounds lost their ancestor when
        # the primitive was deleted. ORIGINAL INTENT preserved — what this
        # guard is for is that every hardcoded tertiary grey has a dark-mode
        # remap, and the DESCENDANT half is what identifies each of them. So
        # the prefix is dropped rather than the tokens. `.note` is removed
        # outright: `class="note"` is emitted nowhere, so m8 deleted the
        # selector, and asserting a remap for a selector that does not exist
        # would be the same dead-guard problem pointing the other way.
        for sel_token in (
            "header .subtitle",
            ".hint",
            ".empty",
            ".display-name",
            "dl.meta dt",
            "footer",
        ):
            assert sel_token in dark_full, (
                f"m3-rect F2: dark @media block missing remap for "
                f"{sel_token!r}. Hardcoded greys (#444-#888) become "
                f"low-contrast on dark backgrounds — fail SC 1.4.3."
            )

    def test_dark_block_corrects_on_accent_text_color(self) -> None:
        # ORIGINAL INTENT (UPL-8 v0 C2), preserved: white text on the light
        # dark-mode --accent fails SC 1.4.3, so the dark block MUST override
        # the on-accent text colour to something dark.
        #
        # ui-uplift-m6 generalised this too. It used to regex-pin the literal
        # `color: #0d1117`, which was a byte-copy of the old dark --bg and so
        # broke on any re-derivation. The real invariant is: an override
        # exists in the dark block, and the resulting pair clears 4.5:1.
        # m6 also widened the selector to include .skip-link:focus-visible,
        # which is not a button and therefore never picked the override up —
        # it shipped white-on-accent at 2.526:1.
        from tests._ui_color import contrast_ratio, load_tokens

        full_dark_block_re = _re.compile(
            r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{(.*?)\n\}",
            flags=_re.S,
        )
        m = full_dark_block_re.search(APP_CSS_NO_COMMENTS)
        assert m is not None, "dark @media block not found"
        dark_full = m.group(1)
        rule = _re.search(
            r"(^|[},])\s*button\s*,\s*\.button[^{]*\{([^}]*)\}",
            dark_full,
            flags=_re.S | _re.M,
        )
        assert rule is not None, (
            "UPL-8 v0 C2 regression: inside @media (prefers-color-scheme: "
            "dark), the `button, .button { color: ... }` on-accent text "
            "override is missing entirely."
        )
        color = _re.search(r"color:\s*([^;]+);", rule.group(2))
        assert color is not None, "the dark button rule declares no color"

        _light, dark = load_tokens()
        on_accent = color.group(1).strip()
        resolved = dark["--bg"] if on_accent == "var(--bg)" else on_accent
        ratio = contrast_ratio(resolved, dark["--accent"])
        assert ratio >= 4.5, (
            f"UPL-8 v0 C2 regression: dark on-accent text {on_accent} on "
            f"--accent = {ratio:.3f}:1, fails SC 1.4.3 at 14px."
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
        # ui-uplift-m6 rectify: the dim value moved 0.6 -> 0.7 (the 0.6 ring
        # composited to 2.70-2.98:1, under SC 1.4.11). This test is about
        # WHERE the declaration sits, not what the number is, so find it by
        # pattern — hardcoding the value made an unrelated test fail on a
        # contrast fix and told us nothing about the nesting it guards.
        _dim = _re.search(r"opacity:\s*0\.\d+\s*;\s*\n\s*pointer-events:\s*none",
                          APP_CSS_NO_COMMENTS)
        assert _dim is not None, (
            "the htmx-request dim rule (opacity + pointer-events: none) is gone"
        )
        idx = _dim.start()
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

    def test_in_flight_focus_ring_clears_the_non_text_floor(self) -> None:
        """Successor to ``test_danger_focus_ring_widened_under_htmx_request``.

        m3 identified the right problem — the danger ring composites below
        SC 1.4.11 while the button is dimmed — but compensated with
        ``outline-width: 3px``. ui-uplift-m6's critique (H3) showed that is
        not a valid trade: **SC 1.4.11 states a contrast threshold and has
        no width term.** Thickness is SC 2.4.13 (Focus Appearance), a
        different criterion with its own separate requirements, so widening
        the ring left the 1.4.11 failure exactly where it was while looking
        like it had been addressed.

        The fix was to raise the dim opacity until the ring genuinely
        clears 3:1. This asserts the property m3 actually wanted, rather
        than the mechanism it reached for; every composited pair is
        enumerated in ``tests/test_ui_contrast.py``.
        """
        m = _re.search(r"opacity:\s*(0\.\d+)\s*;\s*\n\s*pointer-events:\s*none",
                       APP_CSS_NO_COMMENTS)
        assert m is not None, "the htmx-request dim rule is gone"
        alpha = float(m.group(1))

        light, dark = load_tokens()
        for mode, table in (("light", light), ("dark", dark)):
            for ground in ("--bg", "--card-bg"):
                for name in ("--danger", "--accent"):
                    ratio = contrast_ratio(
                        alpha_over(table[name], alpha, table[ground]),
                        table[ground],
                    )
                    assert ratio >= 3.0, (
                        f"{mode} {name} focus ring at opacity {alpha} on "
                        f"{ground} = {ratio:.3f}:1, under SC 1.4.11's 3:1. "
                        f"Raise the opacity — widening the outline does not "
                        f"satisfy a contrast criterion."
                    )

    def test_no_outline_width_compensation_remains(self) -> None:
        """The invalid trade must not come back. If a future milestone
        re-dims the in-flight button, the answer is the opacity, not the
        outline width."""
        assert not _re.search(
            r"\.htmx-request:focus-visible\s*\{[^}]*outline-width:",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        ), (
            "outline-width compensation reintroduced on an .htmx-request "
            "focus ring. SC 1.4.11 is a contrast threshold with no width "
            "term; see ui-uplift-m6 critique H3."
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
        # notebook-paper-discovery-m1 added the topic-edit <form> (detail 4->5);
        # notebook-paper-discovery-m4 added the Discover <form> on the detail
        # page (POST /ui/api/notebooks/{slug}/discover), bringing it to
        # 1 index + 6 detail = 7.
        assert len(all_forms) == 7, (
            f"Expected 7 htmx-bound <form> elements total (1 index + 6 "
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
        # Soft cap on `app.css` line count. Trajectory:
        #   m1=190 → m2=216 → m3-feat=287 → m3-rect=330 (F1/F2/F3 WCAG
        #   corrections) → m4=335 (UPL-22 + UPL-13 consolidated into
        #   ONE @media block) → m5=370 (UPL-19 v1 body clamp + UPL-8 v1
        #   four dark-mode pill remaps + th dark surface + UPL-12 v1
        #   row-fade keyframe — consolidated into EXISTING
        #   prefers-reduced-motion:no-preference block).
        # Documentation comments dominate the cost — kept because the
        # rationale chain (Primer-Dark anchoring, swap-delay gating,
        # clamp() trade-off) is load-bearing for future agents. A
        # future milestone either ships under 370 or argues for
        # another cap raise (or splits into tokens.css + app.css per
        # the documented escape-hatch in KR5).
        # CRITICAL: this cap MUST move in lockstep with the m4/m5 cap
        # test in tests/test_ui_m4_in_place_add_paper.py — the two
        # caps MUST agree (m4-rect F1 lesson; restated in m5 synthesis
        # C8).
        # 2026q3-ui-uplift: m5=370 → 400 for UPL-27 (two WCAG AA contrast
        # fixes), UPL-8 v0 (the first select/textarea base rules) and
        # UPL-15a (tbody tr:hover).
        # ui-uplift-m6: 400 → 480. The OKLCH re-derivation replaces every
        # colour token in both modes and adds 3 duration tokens; the cost
        # is the rationale block that records WHICH TARGET RATIO each token
        # was solved for and against WHICH ground. That provenance is the
        # deliverable — a bare oklch() triple with no target is exactly the
        # un-rederivable hand-typed value m6 exists to eliminate.
        # ui-uplift-m7: kept the cap at 480 and took the escape hatch this
        # comment has named since m3. The two :root blocks moved to
        # server/frontend/static/tokens.css. NOTE: m7's own claim that this
        # "dropped app.css from 471 to ~400" was wrong — it landed at 478
        # (critique M1); the type scale added back most of what the split
        # removed. The cap now bounds the RULE
        # sheet alone, which is what it was always trying to bound; the
        # token sheet has its own, separate bound plus a structural guard
        # that it contains no rules (tests/test_ui_m7_type_scale.py).
        # Splitting is therefore no longer available as a future escape
        # hatch for THIS cap — it has been spent. A future milestone that
        # needs more room argues for a raise on the merits.
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
        # ui-uplift-m10: 520 -> 600, again in lockstep across all three files.
        # The merits, since the split hatch above is spent and cannot be
        # re-taken:
        #  1. m10 lands EIGHT class rules at once — the whole .discover-*
        #     panel plus the .topic-* trio — which is the last of the BAN-R2
        #     debt (_KNOWN_UNSTYLED is empty as of this commit), not an
        #     incremental tweak. 22 lines of headroom did not fit eight rules
        #     under any authoring style.
        #  2. Two REFUSALS are recorded in the stylesheet rather than left
        #     silent: no per-candidate relevance line (the arXiv Atom driver
        #     supplies no basis) and no fade-in keyframe (globalViewTransitions
        #     already crossfades the swap). This repo writes refusals down —
        #     tokens.css:101-106, app.css's select/textarea note — and that
        #     prose is the deliverable, not padding to be trimmed.
        # m8 rectify (M5/M11): the file lands at 593 of 600. The 25-line margin
        # this block used to claim was consumed by the rectify pass itself;
        # the cap was HELD rather than raised a fourth time, and the room
        # came from trimming rationale. Deliberately more
        # than the 2 lines m7 left itself and had to rectify.
        # ui-uplift-m12: 600 -> 680, in lockstep across all three files. m8
        # held the cap because m8 was DELETING a primitive; m12 ADDS a
        # structural element — <details class="manage-disclosure">, a third
        # top-level region — which is the case the cap exists to make
        # deliberate rather than to forbid. Two lines of headroom cannot hold
        # a disclosure rule set (the existing .discover-abstract disclosure
        # costs six lines) and the tokens-split escape hatch is spent twice
        # over: tokens.css is at 289 of 290 and a test forbids putting rules
        # there. Folding selectors to fit would have bought the number by
        # spending readability, and m12 has three decisions to record at the
        # site — the direct-child ladder break, the class-scoping requirement
        # that protects m10's marker, and the corrected AC#5 refusal reason.
        # The file lands at 635 of 680.
        assert line_count <= 680, (
            f"app.css is {line_count} lines — over the 680-line cap "
            f"(m6: 400->480 for the OKLCH family; m10: 520->600 for the Discover "
            f"bibliography rules; m12: 600->680 for the Manage disclosure and the "
            f"nested rule ladder — see the raise history above). Consider stripping "
            f"documentation comments, splitting the file (e.g. tokens.css + "
            f"app.css per the escape-hatch noted in KR5), or arguing for "
            f"another revision. NOTE: the cap tests in "
            f"tests/test_ui_m4_in_place_add_paper.py and "
            f"tests/test_ui_m5_create_remove_in_place.py must also move in "
            f"lockstep — all three caps MUST agree."
        )
