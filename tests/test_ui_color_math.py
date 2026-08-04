"""Ground-truth anchors for `tests/_ui_color.py` (ui-uplift-m6 critique M3).

`_ui_color.py` is the arithmetic authority for the whole contrast gate AND
for the published artifact, and it had no test asserting a single
independently-known value. That is a specific, quiet failure mode rather
than a theoretical one: **a transposed matrix row or a swapped OKLab
coefficient would shift every ratio coherently.** The gate would still pass
(every pair moves together), the artifact would regenerate to match itself,
and `.claude/docs/ui-contrast-table.md`'s central claim — "the arithmetic is
generated, not typed" — would be quietly, invisibly wrong.

The artifact asserts in prose that "the implementation reproduces all nine
independently-published numbers it was checked against". This is that claim,
executed. Each anchor below is a value published somewhere outside this
module — the W3C definition, a research brief, the roadmap — against the
inputs it was published for, so none of them can be back-fitted from the
current implementation.
"""

from __future__ import annotations

import pytest

from tests._ui_color import (
    alpha_over,
    contrast_ratio,
    in_srgb_gamut,
    mix_oklab,
    relative_luminance,
    resolve_color,
)


class TestWcagAnchors:
    """WCAG 2.1 relative luminance / contrast, against published values."""

    def test_black_on_white_is_exactly_twenty_one(self) -> None:
        """The definitional extreme: (1.0 + 0.05) / (0.0 + 0.05) = 21."""
        assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=5e-4)

    def test_contrast_is_symmetric(self) -> None:
        """The ratio is defined lighter-over-darker, so argument order
        cannot matter. A sign error in the max/min would be invisible on
        every pair where the foreground happens to be the darker one."""
        for fg, bg in (("#1f609b", "#f6f9fb"), ("#f6f9fb", "#1f609b")):
            assert contrast_ratio(fg, bg) == pytest.approx(
                contrast_ratio(bg, fg), abs=1e-9
            )

    def test_identical_colours_are_one_to_one(self) -> None:
        assert contrast_ratio("#abcdef", "#abcdef") == pytest.approx(1.0, abs=1e-9)

    def test_relative_luminance_endpoints(self) -> None:
        assert relative_luminance("#000000") == pytest.approx(0.0, abs=1e-12)
        assert relative_luminance("#ffffff") == pytest.approx(1.0, abs=1e-12)

    def test_luminance_coefficients_are_not_transposed(self) -> None:
        """0.2126 R + 0.7152 G + 0.0722 B. Pure green must be by far the
        brightest primary and pure blue by far the dimmest — a swapped pair
        of coefficients survives every symmetric test above."""
        r = relative_luminance("#ff0000")
        g = relative_luminance("#00ff00")
        b = relative_luminance("#0000ff")
        assert g > r > b
        assert r == pytest.approx(0.2126, abs=1e-9)
        assert g == pytest.approx(0.7152, abs=1e-9)
        assert b == pytest.approx(0.0722, abs=1e-9)


class TestHistoricalPublishedRatios:
    """The numbers this milestone was measured against, at their own hexes.

    All three describe the PRE-m6 stylesheet, so they are frozen: the code
    they were measured on is in git history, not in the working tree, and
    they can never legitimately drift.
    """

    def test_light_border_was_1_342(self) -> None:
        """`plans/ui-uplift/roadmap.yaml` states this three times, and
        ui-uplift-m8's AC#4 is written against it. Old `--border: #d8d8d8`
        on old `--bg: #f8f8f8`."""
        assert contrast_ratio("#d8d8d8", "#f8f8f8") == pytest.approx(1.342, abs=5e-4)

    def test_skip_link_failure_was_2_526(self) -> None:
        """The live AA failure m6 closed: white on the old Primer accent
        `#58a6ff` (research/synthesis.md:101)."""
        assert contrast_ratio("#ffffff", "#58a6ff") == pytest.approx(2.526, abs=5e-4)

    def test_card_note_was_4_478_on_white(self) -> None:
        """The UPL-27 comment's own figure: `#777` on `#fff`."""
        assert contrast_ratio("#777777", "#ffffff") == pytest.approx(4.478, abs=5e-4)


class TestOklchConversion:
    """OKLCH -> sRGB, against a reference conversion nobody here authored."""

    def test_canonical_red_round_trip(self) -> None:
        """`oklch(62.796% 0.25768 29.234)` is sRGB red — the worked example
        in Bottosson's original OKLab post and in the CSS Color 4 spec."""
        assert resolve_color("oklch(62.796% 0.25768 29.234)") == "#ff0000"

    def test_achromatic_endpoints(self) -> None:
        assert resolve_color("oklch(100% 0 0)") == "#ffffff"
        assert resolve_color("oklch(0% 0 0)") == "#000000"

    def test_zero_chroma_is_a_pure_grey(self) -> None:
        """Any hue at C=0 must land on R == G == B. A hue term leaking into
        the achromatic path is exactly the kind of error that shifts every
        neutral token coherently."""
        for hue in ("0", "28", "250", "359"):
            hexval = resolve_color(f"oklch(50% 0 {hue})")
            assert hexval[1:3] == hexval[3:5] == hexval[5:7], (
                f"oklch(50% 0 {hue}) = {hexval} is not achromatic"
            )


class TestGamutGuard:
    """`in_srgb_gamut` is what stops a token being published at a colour the
    browser would gamut-map to something else before painting."""

    def test_in_gamut_token_accepted(self) -> None:
        assert in_srgb_gamut(47.863 / 100, 0.115, 250) is True

    def test_out_of_gamut_rejected(self) -> None:
        """OKLCH covers P3 and beyond; C=0.4 at L=70% on hue 250 is far
        outside sRGB."""
        assert in_srgb_gamut(0.70, 0.4, 250) is False

    def test_resolve_refuses_an_out_of_gamut_value(self) -> None:
        with pytest.raises(RuntimeError):
            resolve_color("oklch(70% 0.4 250)")

    def test_resolve_refuses_an_unsupported_value_shape(self) -> None:
        with pytest.raises(RuntimeError):
            resolve_color("color(display-p3 1 0 0)")


class TestMixAndComposite:
    """`mix_oklab` and `alpha_over` are different operations. Conflating
    them was how the m6 registry mis-modelled the badge flash."""

    def test_mix_endpoints_are_the_inputs(self) -> None:
        assert mix_oklab("#ff0000", 100, "#0000ff") == "#ff0000"
        assert mix_oklab("#ff0000", 0, "#0000ff") == "#0000ff"

    def test_mix_of_identical_colours_is_that_colour(self) -> None:
        assert mix_oklab("#1f609b", 37, "#1f609b") == "#1f609b"

    def test_alpha_over_endpoints(self) -> None:
        assert alpha_over("#ff0000", 1.0, "#0000ff") == "#ff0000"
        assert alpha_over("#ff0000", 0.0, "#0000ff") == "#0000ff"

    def test_alpha_over_is_a_per_channel_srgb_blend(self) -> None:
        """50% of #000 over #fff is the arithmetic midpoint 127/128 in
        GAMMA-ENCODED sRGB — NOT the perceptual midpoint mix_oklab would
        give, and not the linear-light midpoint (~#bcbcbc). Browsers
        composite in the destination space; this pins that."""
        assert alpha_over("#000000", 0.5, "#ffffff") == "#808080"

    def test_alpha_over_differs_from_mix_oklab(self) -> None:
        """If these ever agree, one of them is implemented wrong."""
        assert alpha_over("#000000", 0.5, "#ffffff") != mix_oklab(
            "#000000", 50, "#ffffff"
        )
