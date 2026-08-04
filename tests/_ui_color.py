"""Shared colour math for the operator-console stylesheet (ui-uplift-m6).

This is the repo's single WCAG-contrast implementation. Before m6 the only
one lived inline in ``tests/test_ui_m5_create_remove_in_place.py`` and every
other contrast number in the codebase was hand-typed — which is how three
AA failures shipped (``.card .note``, ``.status-badge--ok``, and the
``.skip-link:focus-visible`` white-on-accent pair m6 closed) and how a
comment in ``app.css`` came to state a ratio that was ~20% wrong.

Two jobs:

1. **Colour math** — sRGB relative luminance / WCAG contrast, plus the
   OKLab<->linear-sRGB matrices needed to evaluate ``oklch()`` token values
   and ``color-mix(in oklab, ...)`` results.
2. **Stylesheet parsing** — pull the ``:root`` token tables straight out of
   ``tokens.css`` so no test ever duplicates a token value as a Python
   string. (``test_ui_m5_create_remove_in_place.py`` used to hardcode
   ``canvas = "#0d1117"``; when that token moved the test kept silently
   validating against the wrong ground.)

   ui-uplift-m7 moved the two ``:root`` blocks out of ``app.css`` into
   ``server/frontend/static/tokens.css``, so ``TOKENS_CSS_PATH`` — not
   ``APP_CSS_PATH`` — is what the parsers read. ``APP_CSS_PATH`` is kept and
   still exported: callers that assert on *rules* (and
   ``test_ui_contrast.py``'s favicon sibling lookup) legitimately want the
   rule sheet. Getting these two the wrong way round is silent, not loud —
   a token parse against ``app.css`` now raises rather than returning an
   empty table, which is the whole reason the missing-block errors below
   name the file they searched.

Every ratio is computed from the **8-bit hex a browser actually paints**,
not from exact linear intermediates, so the published numbers are the
rendered ones.

Naming note: ``_ui_color.py`` (leading underscore, no ``test_`` prefix)
follows ``tests/_graph_helpers.py`` — pytest does not collect it.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
_STATIC: Path = REPO_ROOT / "server" / "frontend" / "static"
#: The RULE sheet. Holds no custom property since ui-uplift-m7.
APP_CSS_PATH: Path = _STATIC / "app.css"
#: The TOKEN sheet — the only file with ``:root`` blocks. ``load_tokens`` /
#: ``load_raw_tokens`` read this one.
TOKENS_CSS_PATH: Path = _STATIC / "tokens.css"


# --------------------------------------------------------------------------
# sRGB / WCAG 2.1
# --------------------------------------------------------------------------
def hex_to_rgb01(value: str) -> tuple[float, float, float]:
    h = value.lstrip("#").strip()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise RuntimeError(f"not a 3- or 6-digit hex colour: {value!r}")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def srgb_to_linear(c: float) -> float:
    # WCAG publishes 0.03928; that is a known carry-over error from the
    # original sRGB spec and the self-consistent value at the branch
    # boundary is 0.04045 (IEC 61966-2-1). The two differ only for 8-bit
    # channels below 11/255, so this changes no ratio in this stylesheet.
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def relative_luminance(hex_color: str) -> float:
    r, g, b = (srgb_to_linear(c) for c in hex_to_rgb01(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    lum_a, lum_b = relative_luminance(fg_hex), relative_luminance(bg_hex)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


# --------------------------------------------------------------------------
# OKLab <-> linear sRGB (matrices per bottosson.github.io/posts/oklab/,
# the same ones the CSS Color 4 sample code reproduces)
# --------------------------------------------------------------------------
def linear_srgb_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    lms_l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    lms_m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    lms_s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    # Out-of-gamut intermediates can be negative; a plain ** (1/3) on a
    # negative float returns a complex number in Python.
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (lms_l, lms_m, lms_s))
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_linear_srgb(lightness: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    lms_l, lms_m, lms_s = l_ ** 3, m_ ** 3, s_ ** 3
    return (
        4.0767416621 * lms_l - 3.3077115913 * lms_m + 0.2309699292 * lms_s,
        -1.2684380046 * lms_l + 2.6097574011 * lms_m - 0.3413193965 * lms_s,
        -0.0041960863 * lms_l - 0.7034186147 * lms_m + 1.7076147010 * lms_s,
    )


def oklch_to_linear(lightness: float, chroma: float, hue_deg: float) -> tuple[float, float, float]:
    a = chroma * math.cos(math.radians(hue_deg))
    b = chroma * math.sin(math.radians(hue_deg))
    return oklab_to_linear_srgb(lightness, a, b)


def linear_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(round(linear_to_srgb(c) * 255) for c in rgb))


def hex_to_linear(hex_color: str) -> tuple[float, float, float]:
    return tuple(srgb_to_linear(c) for c in hex_to_rgb01(hex_color))  # type: ignore[return-value]


def in_srgb_gamut(lightness: float, chroma: float, hue_deg: float, eps: float = 1e-4) -> bool:
    """OKLCH covers P3 and beyond. A browser gamut-maps an out-of-gamut
    colour through CSS Color 4's chroma-reduction algorithm before painting
    it, so a naive clamp would NOT match what renders — such a token must
    fail loudly rather than be silently measured."""
    return all(-eps <= c <= 1 + eps for c in oklch_to_linear(lightness, chroma, hue_deg))


def mix_oklab(color_a: str, pct_a: float, color_b: str) -> str:
    """``color-mix(in oklab, <color_a> <pct_a>%, <color_b>)`` -> rendered hex.

    Linear interpolation in OKLab coordinates, which is what the CSS
    function specifies.
    """
    lab_a = linear_srgb_to_oklab(*hex_to_linear(color_a))
    lab_b = linear_srgb_to_oklab(*hex_to_linear(color_b))
    frac = pct_a / 100.0
    mixed = tuple(frac * x + (1 - frac) * y for x, y in zip(lab_a, lab_b, strict=True))
    return linear_to_hex(oklab_to_linear_srgb(*mixed))


def alpha_over(fg_hex: str, alpha: float, bg_hex: str) -> str:
    """Composite ``fg_hex`` at ``alpha`` over ``bg_hex`` -> rendered hex.

    **Not** :func:`mix_oklab`. Compositing and colour-mixing are different
    operations and the difference is load-bearing here:

    - ``color-mix(in oklab, A 30%, B)`` interpolates in OKLab between two
      OPAQUE colours.
    - Alpha compositing — what ``opacity`` does, and what
      ``color-mix(in oklab, A 30%, transparent)`` reduces to once the
      premultiplied result is painted — is a per-channel linear blend in the
      **destination** space, which for a normal (non-``color()``-managed)
      page is gamma-encoded sRGB. Browsers composite in 8-bit sRGB, so this
      rounds to integer channels the same way.

    ui-uplift-m6's critique (H3) found the pair registry had no composited
    row at all, so ``opacity: 0.6`` in-flight buttons and the badge flash —
    both of which change the ground that text is actually read against —
    were outside the "EVERY rendered pair" sweep.
    """
    fg = [int(fg_hex.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    bg = [int(bg_hex.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(
        f"{round(alpha * f + (1 - alpha) * b):02x}"
        for f, b in zip(fg, bg, strict=True)
    )


# --------------------------------------------------------------------------
# Stylesheet parsing
# --------------------------------------------------------------------------
_OKLCH_RE = re.compile(
    r"oklch\(\s*([\d.]+)%\s+([\d.]+)\s+([\d.]+)(?:deg)?\s*\)", re.I
)
_DECL_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
_BASE_ROOT_RE = re.compile(r"^:root\s*\{(.*?)^\}", re.S | re.M)
_DARK_ROOT_RE = re.compile(
    r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{.*?:root\s*\{(.*?)\n\s*\}",
    re.S,
)


def resolve_color(value: str) -> str:
    """Resolve an authored CSS colour value to the hex a browser paints.

    Handles the two shapes this stylesheet's tokens use: a bare hex literal
    and ``oklch(L% C H)``. Anything else raises rather than guessing — a
    silently mis-resolved token would put a wrong number in the published
    contrast table, the exact failure mode m6 exists to end.
    """
    value = value.strip()
    if value.startswith("#"):
        return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in hex_to_rgb01(value)))
    m = _OKLCH_RE.fullmatch(value)
    if m is None:
        raise RuntimeError(
            f"unsupported colour value {value!r}: _ui_color resolves only hex "
            f"and oklch(L% C H). Teach resolve_color the new shape rather than "
            f"letting the contrast table silently skip it."
        )
    lightness, chroma, hue = float(m.group(1)) / 100.0, float(m.group(2)), float(m.group(3))
    if not in_srgb_gamut(lightness, chroma, hue):
        raise RuntimeError(
            f"{value} is outside the sRGB gamut; the browser would gamut-map it "
            f"and the computed contrast would not match what renders."
        )
    return linear_to_hex(oklch_to_linear(lightness, chroma, hue))


def _tokens_from(block: str) -> dict[str, str]:
    return {name: raw.strip() for name, raw in _DECL_RE.findall(block)}


def load_tokens(css: str | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(light, dark)`` token maps of ``--name -> rendered hex``.

    ``dark`` is the base table overlaid with the dark ``:root`` block, i.e.
    what actually applies under ``prefers-color-scheme: dark`` — tokens the
    dark block does not redeclare (``--mono``, ``--dur-*``) fall through.
    Non-colour tokens are dropped.

    ``css`` overrides the file read (used by tests that mutate a token to
    prove a guard discriminates). It must be TOKEN css, not rule css.
    """
    if css is None:
        css = TOKENS_CSS_PATH.read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    base_m = _BASE_ROOT_RE.search(stripped)
    if base_m is None:
        raise RuntimeError("no base `:root { ... }` block found in tokens.css")
    dark_m = _DARK_ROOT_RE.search(stripped)
    if dark_m is None:
        raise RuntimeError("no dark-mode `:root { ... }` block found in tokens.css")

    base_raw = _tokens_from(base_m.group(1))
    dark_raw = dict(base_raw)
    dark_raw.update(_tokens_from(dark_m.group(1)))

    def colors(raw: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for name, value in raw.items():
            if value.startswith("#") or _OKLCH_RE.fullmatch(value):
                out[name] = resolve_color(value)
        return out

    return colors(base_raw), colors(dark_raw)


def load_raw_tokens(css: str | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """``(base, dark)`` maps of ``--name -> authored value`` (unresolved).

    Includes non-colour tokens, so callers can assert on ``--dur-*`` and
    ``--mono``. ``dark`` here is only what the dark block itself declares.
    """
    if css is None:
        css = TOKENS_CSS_PATH.read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    base_m = _BASE_ROOT_RE.search(stripped)
    dark_m = _DARK_ROOT_RE.search(stripped)
    if base_m is None or dark_m is None:
        raise RuntimeError("tokens.css is missing a base or dark `:root` block")
    return _tokens_from(base_m.group(1)), _tokens_from(dark_m.group(1))
