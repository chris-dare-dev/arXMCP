"""Structural scan of parsed ar5iv/LaTeXML HTML for invisible text.

Text a reader of the rendered paper never sees still reaches ``body_text``,
because the chunker extracts text from the markup, not from the rendering.
That makes hidden text a channel for instructions aimed at the agent that
later reads the chunk. This module finds it in the soup the chunker already
built, without re-parsing the document.

The scan reports and never edits: it does not drop or rewrite text, so chunk
bodies and chunk ids are the same whether or not it runs.

Each finding is recorded at the outermost element that hides its text, and
that element's descendants are not scanned again, so one hidden paragraph is
one finding. Text inside ``<math>`` is skipped: phantoms and zero-width
spacing are ordinary typesetting there.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from bs4 import Tag

# The kinds a finding can carry.
DISPLAY_NONE = "display-none"
VISIBILITY_HIDDEN = "visibility-hidden"
HIDDEN_ATTRIBUTE = "hidden-attribute"
HIDDEN_CLASS = "hidden-class"
TINY_FONT = "tiny-font"
TRANSPARENT = "transparent"
OFF_PAGE = "off-page"
CLIPPED = "clipped"
NEAR_WHITE_TEXT = "near-white-text"
TEXT_MATCHES_BACKGROUND = "text-matches-background"

# LaTeXML's stylesheet hides these classes.
_HIDDEN_CLASSES = frozenset({"ltx_hidden", "ltx_phantom"})

# Below these sizes text is not legible. Keyed by CSS unit.
_MIN_FONT_SIZE = {"px": 2.0, "pt": 1.5, "em": 0.2, "rem": 0.2, "%": 20.0, "": 0.0}

# An offset this far negative puts the box off any page.
_OFF_PAGE = {"px": -1000.0, "pt": -750.0, "em": -60.0, "rem": -60.0, "%": -100.0}

_NAMED_COLORS = {
    "white": (255, 255, 255),
    "snow": (255, 250, 250),
    "ivory": (255, 255, 240),
    "ghostwhite": (248, 248, 255),
    "whitesmoke": (245, 245, 245),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
}

# Channels within this distance read as the same colour.
_SAME_COLOR_DISTANCE = 16
# Every channel at or above this reads as white on a white page.
_NEAR_WHITE = 240

_LENGTH = re.compile(r"^(-?\d*\.?\d+)\s*(px|pt|em|rem|%)?$")
_RGB = re.compile(r"^rgba?\(([^)]*)\)$")

_SNIPPET_CHARS = 80

# LaTeXML writes colours either as plain CSS or as its own custom properties.
_COLOR_PROPS = ("color", "--ltx-fg-color")
_BACKGROUND_PROPS = ("background-color", "background", "--ltx-bg-color")

Rgb = tuple[int, int, int]


@dataclass(frozen=True)
class HiddenTextFinding:
    """One element whose text is in the markup but not visible.

    ``text`` is the start of the hidden text, for a person reviewing the
    finding; it is untrusted paper content.
    """

    kind: str
    text: str


def scan_hidden_text(root: Tag) -> list[HiddenTextFinding]:
    """Return every element under ``root`` that carries invisible text.

    The walk keeps its own stack, so a deeply nested page cannot exhaust
    the interpreter's recursion limit.
    """
    findings: list[HiddenTextFinding] = []
    # Each entry is an element with the text and background colours it
    # inherits; children are pushed in reverse to keep document order.
    stack: list[tuple[Tag, Rgb | None, Rgb | None]] = [
        (child, None, None) for child in reversed(_child_tags(root))
    ]
    while stack:
        tag, color, background = stack.pop()
        if tag.name == "math":
            continue
        style = _parse_style(tag.get("style"))
        own_color = _first_color(style, _COLOR_PROPS)
        own_background = _first_color(style, _BACKGROUND_PROPS)
        color = own_color or color
        background = own_background or background

        kind = _hiding_kind(tag, style)
        if kind is None and (own_color or own_background):
            kind = _color_kind(color, background)
        if kind is not None:
            text = tag.get_text(" ", strip=True)
            if text:
                findings.append(HiddenTextFinding(kind, text[:_SNIPPET_CHARS]))
                continue
        stack.extend((child, color, background) for child in reversed(_child_tags(tag)))
    return findings


def count_by_kind(findings: list[HiddenTextFinding]) -> dict[str, int]:
    """Finding counts keyed by kind, in a stable order for logging."""
    return dict(sorted(Counter(f.kind for f in findings).items()))


def _child_tags(tag: Tag) -> list[Tag]:
    return [child for child in tag.children if isinstance(child, Tag)]


def _hiding_kind(tag: Tag, style: dict[str, str]) -> str | None:
    if style.get("display") == "none":
        return DISPLAY_NONE
    if style.get("visibility") in {"hidden", "collapse"}:
        return VISIBILITY_HIDDEN
    if tag.has_attr("hidden"):
        return HIDDEN_ATTRIBUTE
    classes = tag.get("class") or []
    if _HIDDEN_CLASSES.intersection(classes):
        return HIDDEN_CLASS
    if _is_tiny(style.get("font-size", "")):
        return TINY_FONT
    if _is_transparent(style):
        return TRANSPARENT
    if _is_off_page(style):
        return OFF_PAGE
    if _is_clipped(style):
        return CLIPPED
    return None


def _color_kind(color: Rgb | None, background: Rgb | None) -> str | None:
    if color is None:
        return None
    if background is None:
        # No background set anywhere above: the page is white.
        if min(color) >= _NEAR_WHITE:
            return NEAR_WHITE_TEXT
        return None
    if max(abs(a - b) for a, b in zip(color, background, strict=True)) <= _SAME_COLOR_DISTANCE:
        return TEXT_MATCHES_BACKGROUND
    return None


def _first_color(style: dict[str, str], props: tuple[str, ...]) -> Rgb | None:
    for prop in props:
        parsed = _parse_color(style.get(prop, ""))
        if parsed is not None:
            return parsed
    return None


def _parse_style(raw: object) -> dict[str, str]:
    if not isinstance(raw, str):
        return {}
    style: dict[str, str] = {}
    for declaration in raw.split(";"):
        name, sep, value = declaration.partition(":")
        if not sep:
            continue
        value = value.replace("!important", "").strip().lower()
        style[name.strip().lower()] = value
    return style


def _length(value: str) -> tuple[float, str] | None:
    match = _LENGTH.match(value.strip())
    if match is None:
        return None
    return float(match.group(1)), match.group(2) or ""


def _is_tiny(value: str) -> bool:
    length = _length(value)
    if length is None:
        return False
    size, unit = length
    return size <= 0 or size < _MIN_FONT_SIZE.get(unit, 0.0)


def _is_transparent(style: dict[str, str]) -> bool:
    opacity = _length(style.get("opacity", ""))
    if opacity is not None and opacity[0] <= 0.05:
        return True
    return style.get("color") == "transparent" or _alpha(style.get("color", "")) == 0


def _is_off_page(style: dict[str, str]) -> bool:
    for prop in ("left", "top", "right", "text-indent", "margin-left", "margin-top"):
        length = _length(style.get(prop, ""))
        if length is None:
            continue
        offset, unit = length
        if unit in _OFF_PAGE and offset <= _OFF_PAGE[unit]:
            return True
    return False


def _is_clipped(style: dict[str, str]) -> bool:
    clip = style.get("clip", "").replace(" ", "")
    if clip in {"rect(0,0,0,0)", "rect(0px,0px,0px,0px)"}:
        return True
    if style.get("clip-path", "").replace(" ", "") in {"inset(50%)", "inset(100%)"}:
        return True
    if style.get("overflow") == "hidden":
        for prop in ("width", "height", "max-width", "max-height"):
            length = _length(style.get(prop, ""))
            if length is not None and length[0] <= 0:
                return True
    return False


def _alpha(value: str) -> float | None:
    match = _RGB.match(value)
    if match is None:
        return None
    parts = [p.strip() for p in match.group(1).split(",")]
    if len(parts) != 4:
        return None
    try:
        return float(parts[3])
    except ValueError:
        return None


def _parse_color(value: str) -> Rgb | None:
    value = value.strip()
    if not value:
        return None
    if value in _NAMED_COLORS:
        return _NAMED_COLORS[value]
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) != 6:
            return None
        try:
            return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
        except ValueError:
            return None
    match = _RGB.match(value)
    if match is None:
        return None
    parts = [p.strip() for p in match.group(1).split(",")]
    if len(parts) not in {3, 4}:
        return None
    try:
        r, g, b = (int(float(p)) for p in parts[:3])
    except ValueError:
        return None
    return (r, g, b)
