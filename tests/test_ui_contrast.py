"""ui-uplift-m6 — the WCAG gate over EVERY rendered pair in app.css.

**Be precise about what is and is not automated here.** Two halves, with a
deliberate boundary:

- **Hand-maintained (small, reviewable, changes rarely):** ``PAIRS`` below —
  the list of *which* foreground/background combinations actually render.
  Deriving that automatically would need a headless browser walking the real
  DOM + CSSOM for every element's computed ``color``/``background-color``,
  which this repo's no-Node/no-heavy-deps posture rules out. So this list can
  still go stale if a future milestone adds a selector and not a row here.
- **Generated (large, error-prone, exactly what broke before):** every ratio.
  No contrast number is typed by a human anywhere in this milestone.

That boundary matters because a *partial inventory* is how three AA failures
shipped: ``.card .note`` and ``.status-badge--ok`` (both fixed in UPL-27) and
``.skip-link:focus-visible`` white-on-accent at 2.53:1, which no contrast
table in this repo had ever listed. The old table covered 12 token-on-ground
cells; this one covers 67 rendered pairs.

Floors: **4.5:1** for text (SC 1.4.3) and **3:1** for non-text UI boundaries
and graphical objects (SC 1.4.11).

**No row claims WCAG's large-text exception, and that is deliberate.** Until
ui-uplift-m7, ``header h1 a`` was registered at 3:1 because ``header h1``
carried no ``font-size`` and rode the UA ``h1 { font-size: 2em }`` = a fixed
32px. m7 put it on ``clamp(1.5rem, 4vw + 0.5rem, 2.25rem)``, so its rendered
size is now viewport-dependent — 24px at a 390px viewport, 36px above 700px.
A viewport-agnostic registry cannot honestly carry a floor that only holds at
some viewports, so the row moved to the 4.5:1 TEXT floor, which holds at
every width. It still passes with an order of magnitude of headroom (16.0:1
light / 13.9:1 dark), so nothing was traded for the honesty.

The same m7 scale also makes the old "only a bare ``header h1``" claim wrong
in the *other* direction: sections are now 20px and every ``<h2>`` inherits
UA bold, so ``.card h2`` would qualify for the >=18.7px-bold branch. It is
held to 4.5:1 anyway, on the same reasoning.

Running this module directly regenerates ``.claude/docs/ui-contrast-table.md``:

    python -m tests.test_ui_contrast --update
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from tests._ui_color import (
    APP_CSS_PATH,
    REPO_ROOT,
    TOKENS_CSS_PATH,
    alpha_over,
    contrast_ratio,
    load_raw_tokens,
    load_tokens,
    mix_oklab,
)

TABLE_DOC: Path = REPO_ROOT / ".claude" / "docs" / "ui-contrast-table.md"
BEGIN_MARK = "<!-- BEGIN GENERATED CONTRAST TABLE -->"
END_MARK = "<!-- END GENERATED CONTRAST TABLE -->"

LIGHT, DARK = load_tokens()

TEXT = 4.5
NONTEXT = 3.0
#: ``LARGE = 3.0`` was REMOVED by ui-uplift-m7, not merely left unused.
#: Its only consumer was the ``header h1 a`` row (see the module docstring),
#: and it was numerically identical to ``NONTEXT`` — so an alias for a
#: DIFFERENT success criterion at the SAME number bought nothing and cost the
#: one thing this module exists to protect: ``render_table`` printed the SC
#: column by comparing against it, which meant a row's criterion was inferred
#: from its float. Two criteria that happen to share a threshold are exactly
#: the conflation the SC column was added to prevent. If a future milestone
#: earns a real large-text exemption, re-introduce it WITH a companion guard
#: pinning the rendered size at the narrowest viewport — an exemption whose
#: precondition nothing checks is unbacked.
#: A pair that genuinely renders but that WCAG does not require to meet a
#: floor. It is registered anyway, with its measured ratio, so the artifact
#: shows the number and the reason — critique H3's point was that "an
#: unstated exemption and an oversight look identical from the artifact".
#: Every EXEMPT site string must carry its justification inline.
EXEMPT = 0.0


def _resolve(spec: object, mode: str) -> str:
    """Resolve a pair-registry colour spec to the hex a browser paints."""
    table = LIGHT if mode == "light" else DARK
    if isinstance(spec, tuple):
        tag, base, amount, other = spec
        if tag == "mix":
            return mix_oklab(_resolve(base, mode), amount, _resolve(other, mode))
        if tag == "fade":
            return alpha_over(_resolve(base, mode), amount, _resolve(other, mode))
        raise RuntimeError(f"unknown colour spec tag: {tag!r}")
    if isinstance(spec, str) and spec.startswith("--"):
        return table[spec]
    if isinstance(spec, str):
        return spec
    raise RuntimeError(f"unresolvable colour spec: {spec!r}")


def mix(base: object, pct: float, other: object) -> tuple:
    """``color-mix(in oklab, <base> <pct>%, <other>)`` — two opaque colours."""
    return ("mix", base, pct, other)


def fade(base: object, alpha: float, ground: object) -> tuple:
    """``opacity: <alpha>`` — composite ``base`` over ``ground`` in sRGB.

    Distinct from :func:`mix` on purpose; see ``tests._ui_color.alpha_over``.
    Registering these is critique H3: ``opacity`` moves BOTH an element's
    text and its fill, so it changes the ground a pair is actually read
    against, and the m6 registry had no composited row at all.
    """
    return ("fade", base, alpha, ground)


WHITE = "#ffffff"
#: ``button:hover`` / ``.button:hover`` ground.
HOVER = mix("--accent", 88, WHITE)
#: ``tbody tr:hover`` ground.
ROW_HOVER = mix("--card-bg", 95, "--fg")

# ---------------------------------------------------------------------------
# THE HAND-MAINTAINED HALF: which pairs render.
# (mode, site, foreground, background, floor)
# Sourced from a full read of app.css plus every Jinja2 template and every
# HTML-fragment builder in server/routes/{ui,notebooks}.py.
# ---------------------------------------------------------------------------
PAIRS: list[tuple[str, str, object, object, float]] = []


def _p(mode: str, site: str, fg: object, bg: object, floor: float) -> None:
    PAIRS.append((mode, site, fg, bg, floor))


for _m in ("light", "dark"):
    # -- token-on-surface text ------------------------------------------------
    _p(_m, "body text", "--fg", "--bg", TEXT)
    _p(_m, "card body text", "--fg", "--card-bg", TEXT)
    # ui-uplift-m7: was LARGE (3.0). The title is now a clamp, so its size is
    # viewport-dependent and no single floor claim holds everywhere; TEXT is
    # the conservative one that does. Still passes at 16.0:1 / 13.9:1.
    _p(_m, "header h1 a", "--fg", "--bg", TEXT)
    _p(_m, "td text", "--fg", "--card-bg", TEXT)
    _p(_m, "tbody tr:hover text", "--fg", ROW_HOVER, TEXT)
    # -- --accent's five roles ------------------------------------------------
    _p(_m, ".breadcrumb a link [accent role 3]", "--accent", "--bg", TEXT)
    _p(_m, "focus ring on --bg [accent role 2]", "--accent", "--bg", NONTEXT)
    _p(_m, "focus ring on --card-bg [accent role 2]", "--accent", "--card-bg", NONTEXT)
    # -- danger -------------------------------------------------------------
    _p(_m, "pre.error text", "--danger", "--error-bg", TEXT)
    _p(_m, "button.danger focus ring on --bg", "--danger", "--bg", NONTEXT)
    _p(_m, "button.danger focus ring on --card-bg", "--danger", "--card-bg", NONTEXT)
    # -- borders (SC 1.4.11) --------------------------------------------------
    _p(_m, "--border on --bg [AC#4 in light]", "--border", "--bg", NONTEXT)
    _p(_m, "--border on --card-bg", "--border", "--card-bg", NONTEXT)

# -- on-accent text: white in light, var(--bg) in dark (mode-conditional) ----
_p("light", "button/.button text [accent role 1]", WHITE, "--accent", TEXT)
_p("light", "button:hover text", WHITE, HOVER, TEXT)
_p("light", "button.danger text", WHITE, "--danger", TEXT)
_p("light", ".skip-link:focus-visible text [accent role 4]", WHITE, "--accent", TEXT)
_p("dark", "button/.button text [accent role 1]", "--bg", "--accent", TEXT)
_p("dark", "button:hover text", "--bg", HOVER, TEXT)
_p("dark", "button.danger text", "--bg", "--danger", TEXT)
_p("dark", ".skip-link:focus-visible text [accent role 4]", "--bg", "--accent", TEXT)

# -- light-mode hardcoded greys (v1 scope; grounds moved, so re-verified) ----
_p("light", "header .subtitle #555", "#555555", "--bg", TEXT)
_p("light", "footer #666", "#666666", "--bg", TEXT)
_p("light", "footer a #666", "#666666", "--bg", TEXT)
_p("light", ".card .hint #555", "#555555", "--card-bg", TEXT)
_p("light", ".card .note #6f6f6f", "#6f6f6f", "--card-bg", TEXT)
_p("light", ".card .empty #666", "#666666", "--card-bg", TEXT)
_p("light", ".card .display-name #444", "#444444", "--card-bg", TEXT)
_p("light", "dl.meta dt #555", "#555555", "--card-bg", TEXT)
_p("light", "input/textarea typed text on #fff", "--fg", WHITE, TEXT)
_p("light", "th text on #f0f0f0", "--fg", "#f0f0f0", TEXT)

# -- dark-mode hardcoded greys (v1 scope; grounds moved, so re-verified) -----
_p("dark", "header .subtitle / footer / footer a #b3b9c0", "#b3b9c0", "--bg", TEXT)
_p("dark", ".card .hint / dl.meta dt #b3b9c0", "#b3b9c0", "--card-bg", TEXT)
_p("dark", ".card .note / .card .empty #9ba1a8", "#9ba1a8", "--card-bg", TEXT)
_p("dark", ".card .display-name #c9d1d9", "#c9d1d9", "--card-bg", TEXT)
_p("dark", "input/textarea typed text", "--fg", "--card-bg", TEXT)
_p("dark", "th text on th background", "--fg", "--card-bg", TEXT)

# -- status pills. Light --down uses the tokens, so it moves with them; the
#    other 3 light and all 4 dark pills are v1 literals. The
#    <small class="status-badge__remediation"> emitted by
#    server/routes/ui.py has no rule of its own and inherits the active
#    modifier's colour on its background — same ratio, second render site.
_LIGHT_PILLS = [
    ("ok", "#e6f4ea", "#15682d", "#15682d"),
    ("warn", "#fdf3e2", "#8a5a00", "#8a5a00"),
    ("ops-warn", "#eef2f7", "#475569", "#475569"),
]
_DARK_PILLS = [
    ("ok", "#0d2818", "#3fb950", "#3fb950"),
    ("warn", "#3d2a07", "#d29922", "#d29922"),
    ("ops-warn", "#1c2230", "#8b949e", "#8b949e"),
    ("down", "#3d1216", "#f85149", "#f85149"),
]
for _name, _bg, _fg, _bd in _LIGHT_PILLS:
    _p("light", f".status-badge--{_name} text", _fg, _bg, TEXT)
    _p("light", f".status-badge--{_name} border on --bg", _bd, "--bg", NONTEXT)
_p("light", ".status-badge--down text (tokens)", "--danger", "--error-bg", TEXT)
_p("light", ".status-badge--down border on --bg (token)", "--danger", "--bg", NONTEXT)
for _name, _bg, _fg, _bd in _DARK_PILLS:
    _p("dark", f".status-badge--{_name} text", _fg, _bg, TEXT)
    _p("dark", f".status-badge--{_name} border on --bg", _bd, "--bg", NONTEXT)
# .status-badge with no modifier uses the base border token.
for _m in ("light", "dark"):
    _p(_m, ".status-badge base border on --bg", "--border", "--bg", NONTEXT)

# ---------------------------------------------------------------------------
# COMPOSITED STATE CLASSES (critique H1 / H3 / M1 / M8).
#
# The m6 registry held zero composited rows, so two whole rendered state
# classes sat outside the "EVERY rendered pair" claim. Both change the ground
# text is read against, which is exactly the case a token-on-token sweep
# cannot see.
# ---------------------------------------------------------------------------

#: `form.htmx-request button[type=submit]` etc. `opacity` composites BOTH the
#: label and the fill over whatever is behind the button, collapsing their
#: mutual contrast. Registered for both grounds a button actually sits on.
IN_FLIGHT = 0.7

for _m in ("light", "dark"):
    _on_accent = WHITE if _m == "light" else "--bg"
    for _ground in ("--bg", "--card-bg"):
        for _label, _fill in (("accent", "--accent"), ("danger", "--danger")):
            # The label: exempt, and the exemption is `pointer-events: none`.
            _p(
                _m,
                f"in-flight {_label} button label on {_ground} "
                f"[EXEMPT: inactive component, SC 1.4.3 — pointer-events:none]",
                fade(_on_accent, IN_FLIGHT, _ground),
                fade(_fill, IN_FLIGHT, _ground),
                EXEMPT,
            )
            # The focus ring is NOT exempt — a keyboard user can still focus
            # the button mid-request, and SC 1.4.11 states a contrast
            # threshold with no width trade (width is SC 2.4.13, a different
            # criterion). This is the pair that forced opacity 0.6 -> 0.7.
            _p(
                _m,
                f"in-flight {_label} focus ring on {_ground}",
                fade(_fill, IN_FLIGHT, _ground),
                _ground,
                NONTEXT,
            )

#: AC#3 role 5. The flash animates `border-color` to --accent (it animated
#: `background` before the m6 critique, which replaced the pill's fill and put
#: 6 of 8 pill texts under 4.5:1). Because only the border moves, no text pair
#: changes — this is the whole pair the state introduces.
for _m in ("light", "dark"):
    for _ground in ("--bg", "--card-bg"):
        _p(
            _m,
            f".status-badge.htmx-settling flash border on {_ground} "
            f"[accent role 5]",
            "--accent",
            _ground,
            NONTEXT,
        )

# -- light --border's real binding grounds (critique M2). The token records
#    "solved: 3.30:1 on --bg", but it is also drawn against th's #f0f0f0 and
#    the tbody row-hover ground, both DARKER than --bg and therefore the
#    actually-binding ones. Neither was registered, so ~2.5% of the headroom
#    was unguarded and a future re-derivation aimed at the documented --bg
#    target could drop the real thinnest pair under 3:1 with the gate green.
_p("light", "--border on th #f0f0f0", "--border", "#f0f0f0", NONTEXT)
for _m in ("light", "dark"):
    _p(_m, "--border on tbody tr:hover", "--border", ROW_HOVER, NONTEXT)


def _rows() -> list[tuple[str, str, str, str, float, float, bool]]:
    out = []
    for mode, site, fg, bg, floor in PAIRS:
        fg_hex, bg_hex = _resolve(fg, mode), _resolve(bg, mode)
        ratio = contrast_ratio(fg_hex, bg_hex)
        out.append((mode, site, fg_hex, bg_hex, ratio, floor, ratio >= floor))
    return out


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("mode", "site", "fg", "bg", "floor"),
    PAIRS,
    ids=[f"{m}-{s}" for m, s, _f, _b, _fl in PAIRS],
)
def test_rendered_pair_meets_wcag_floor(
    mode: str, site: str, fg: object, bg: object, floor: float
) -> None:
    """AC#5, the hard gate: no rendered pair may sit under its floor."""
    fg_hex, bg_hex = _resolve(fg, mode), _resolve(bg, mode)
    ratio = contrast_ratio(fg_hex, bg_hex)
    if floor == EXEMPT:
        # Registered for the artifact, not gated. The site string carries the
        # justification; this asserts only that it HAS one, so an exemption
        # can never be added silently.
        assert "[EXEMPT:" in site, (
            f"{mode} / {site}: EXEMPT floor without a recorded justification. "
            f"Put the reason in the site string as '[EXEMPT: <why>]'."
        )
        return
    assert ratio >= floor, (
        f"{mode} / {site}: {fg_hex} on {bg_hex} = {ratio:.3f}:1, under the "
        f"{floor}:1 floor. ui-uplift-m6 AC#5 makes this a ship blocker — "
        f"re-derive the token against a contrast target, do not nudge the hex."
    )


def test_light_border_clears_three_to_one_on_bg() -> None:
    """AC#4: the light rule token unblocks ui-uplift-m8. Was 1.342:1."""
    ratio = contrast_ratio(LIGHT["--border"], LIGHT["--bg"])
    assert ratio >= 3.0, (
        f"light --border on --bg = {ratio:.3f}:1; ui-uplift-m8's rule ladder "
        f"needs >= 3:1 (SC 1.4.11). It was 1.342:1 before ui-uplift-m6."
    )


def _accent_role_checks(mode: str) -> list[tuple[str, float, float]]:
    """AC#3's five --accent roles, as (label, measured ratio, floor).

    Shared by ``test_accent_satisfies_all_five_roles`` and the generated
    roles table in the published artifact — critique H2 found that table
    hand-typed, sitting outside the generated markers, with 9 of 12 numbers
    wrong. Deriving both from this one function is what makes the artifact's
    "Ratios are computed, never typed" claim true.
    """
    table = LIGHT if mode == "light" else DARK
    on_accent = WHITE if mode == "light" else table["--bg"]
    return [
        ("role 1 button ground vs its own text",
         contrast_ratio(on_accent, table["--accent"]), 4.5),
        ("role 1b :hover ground vs its own text",
         contrast_ratio(on_accent, _resolve(HOVER, mode)), 4.5),
        ("role 2 focus ring vs --bg",
         contrast_ratio(table["--accent"], table["--bg"]), 3.0),
        ("role 2 focus ring vs --card-bg",
         contrast_ratio(table["--accent"], table["--card-bg"]), 3.0),
        ("role 3 link vs --bg",
         contrast_ratio(table["--accent"], table["--bg"]), 4.5),
        ("role 4 skip-link ground vs its own text",
         contrast_ratio(on_accent, table["--accent"]), 4.5),
        # Critique H1: role 5 was named in AC#3 and checked by nothing. The
        # flash now moves border-color, so the measured pair is --accent
        # against the ground the pill sits on.
        ("role 5 badge-flash border vs --bg",
         contrast_ratio(table["--accent"], table["--bg"]), 3.0),
        ("role 5 badge-flash border vs --card-bg",
         contrast_ratio(table["--accent"], table["--card-bg"]), 3.0),
    ]


def test_accent_satisfies_all_five_roles() -> None:
    """AC#3: ONE --accent token, five simultaneous roles, in BOTH modes."""
    for mode in ("light", "dark"):
        checks = _accent_role_checks(mode)
        roles = {label.split()[1] for label, _r, _f in checks}
        assert roles == {"1", "1b", "2", "3", "4", "5"}, (
            f"AC#3 enumerates five --accent roles; this test covers {sorted(roles)}. "
            f"Role 5 (badge-flash) went unchecked through the whole of m6."
        )
        for label, ratio, floor in checks:
            assert ratio >= floor, f"{mode}: --accent {label} = {ratio:.3f}:1 < {floor}"


def test_focus_ring_verified_against_card_bg_not_only_bg() -> None:
    """In dark mode --card-bg is LIGHTER than --bg, so it is the binding
    ground for a light accent ring. Assert explicitly rather than assuming
    the --bg pair covers it."""
    assert DARK["--card-bg"] != DARK["--bg"]
    assert contrast_ratio(DARK["--accent"], DARK["--card-bg"]) >= 3.0
    assert contrast_ratio(DARK["--border"], DARK["--card-bg"]) >= 3.0


def test_surface_separation_is_pinned_in_both_modes() -> None:
    """Critique L4: the card/canvas surface pair was guarded by a bare
    ``!=`` in dark and by nothing at all in light, while m6 halved the light
    separation (1.062:1 -> ~1.028:1) without recording it.

    Not a defect — net card visibility improved, because the 1 px --border
    around the card went from 1.342:1 to over 3:1 — but two identical hexes
    would have passed every test in the milestone. A floor at the shipped
    value stops the surface distinction being collapsed silently.
    """
    for mode, table in (("light", LIGHT), ("dark", DARK)):
        ratio = contrast_ratio(table["--card-bg"], table["--bg"])
        assert ratio >= 1.02, (
            f"{mode} --card-bg vs --bg = {ratio:.4f}:1. The card surface must "
            f"stay distinguishable from the canvas; ui-uplift-m8 AC#2 depends "
            f"on --card-bg having a successor role."
        )


def test_no_pair_registry_duplicates_a_token_as_a_literal() -> None:
    """Guards the failure mode that made the old m5 canvas check useless: a
    token value duplicated as a Python string silently validates the wrong
    ground once the token moves."""
    token_hexes = {v.lower() for v in (*LIGHT.values(), *DARK.values())}
    for mode, site, fg, bg, _floor in PAIRS:
        for spec in (fg, bg):
            if isinstance(spec, str) and spec.startswith("#"):
                assert spec.lower() not in token_hexes, (
                    f"{mode} / {site}: literal {spec} equals a current token "
                    f"value — reference the token instead so it cannot drift."
                )


# ---------------------------------------------------------------------------
# AC#1 / AC#6 / AC#7 — structural properties of the token block
# ---------------------------------------------------------------------------
CSS_TEXT = APP_CSS_PATH.read_text(encoding="utf-8")
CSS_NO_COMMENTS = re.sub(r"/\*.*?\*/", "", CSS_TEXT, flags=re.S)
#: ui-uplift-m7 split the token blocks out of app.css. Assertions about
#: TOKENS read this; assertions about RULES keep reading CSS_NO_COMMENTS.
TOKENS_TEXT = TOKENS_CSS_PATH.read_text(encoding="utf-8")
TOKENS_NO_COMMENTS = re.sub(r"/\*.*?\*/", "", TOKENS_TEXT, flags=re.S)
BASE_RAW, DARK_RAW = load_raw_tokens()

#: Values the previous stylesheet lifted from GitHub Primer, by its own
#: comments (canvas.default / canvas.subtle / accent.fg / danger.fg + the
#: two grey-scale steps and the dark-analogue error surface).
PRIMER_LITERALS = [
    "#0d1117", "#161b22", "#58a6ff", "#f85149", "#30363d", "#6e7681", "#2a1a18",
]


def test_no_token_is_a_primer_literal() -> None:
    """AC#1, half one."""
    for name, value in [*BASE_RAW.items(), *DARK_RAW.items()]:
        for primer in PRIMER_LITERALS:
            assert primer not in value.lower(), (
                f"{name}: {value} is the GitHub Primer literal {primer}. "
                f"ui-uplift-m6 AC#1 requires a derived value."
            )
    for mode, table in (("light", LIGHT), ("dark", DARK)):
        for name, rendered in table.items():
            assert rendered.lower() not in PRIMER_LITERALS, (
                f"{mode} {name} resolves to the Primer literal {rendered}"
            )


#: The CLOSED set of token families that are deliberately not colours.
#:
#: ui-uplift-m7 added the ``--text-*`` / ``--tracking-*`` families to
#: ``:root``, which the oklch guard below would otherwise reject. Widening it
#: is required — but the widening is an explicit allow-list, never a
#: "skip anything that does not parse as a colour". That looser predicate
#: would silently retire the guarantee ui-uplift-m6 shipped (EVERY colour
#: token is ``oklch()`` on one of two hues): a future ``--fg: #444`` would
#: stop being a colour by the predicate's own reckoning and skip itself.
#: A new non-colour family means adding it HERE, deliberately.
NON_COLOUR_TOKEN_NAMES = frozenset({"--mono"})
NON_COLOUR_TOKEN_PREFIXES = ("--dur-", "--text-", "--tracking-")


def _is_non_colour_token(name: str) -> bool:
    return name in NON_COLOUR_TOKEN_NAMES or name.startswith(NON_COLOUR_TOKEN_PREFIXES)


def test_the_non_colour_allow_list_has_no_dead_entries() -> None:
    """The allow-list only stays honest while every entry is real.

    A stale prefix is a hole nobody sees: it skips a name that no longer
    exists today and quietly pre-authorises whatever claims that name
    tomorrow. Assert each entry currently matches at least one token.
    """
    for name in NON_COLOUR_TOKEN_NAMES:
        assert name in BASE_RAW, f"{name} is allow-listed but declared nowhere"
    for prefix in NON_COLOUR_TOKEN_PREFIXES:
        assert any(n.startswith(prefix) for n in BASE_RAW), (
            f"no token starts with the allow-listed prefix {prefix!r} — "
            f"drop the entry rather than leaving a pre-authorised namespace"
        )


def test_all_colour_tokens_are_oklch_on_one_of_two_hues() -> None:
    """AC#1, half two: ONE hue decision per semantic family, and the SAME
    construction in both modes — not achromatic greys in light against a
    cool-tinted Primer clone in dark."""
    hue_re = re.compile(r"oklch\(\s*[\d.]+%\s+[\d.]+\s+([\d.]+)(?:deg)?\s*\)", re.I)
    seen: dict[str, set[str]] = {}
    for label, raw in (("light", BASE_RAW), ("dark", DARK_RAW)):
        for name, value in raw.items():
            if _is_non_colour_token(name):
                continue
            m = hue_re.fullmatch(value.strip())
            assert m is not None, f"{label} {name} = {value!r} is not an oklch() value"
            seen.setdefault(label, set()).add(m.group(1))
    hues = seen["light"] | seen["dark"]
    assert hues == {"250", "28"}, (
        f"expected exactly two authored hues (brand 250, danger 28); got {sorted(hues)}"
    )
    # The same two hues must appear in BOTH modes — that is what "one hue
    # decision, both modes" means operationally.
    assert seen["light"] == seen["dark"] == hues


def test_color_scheme_light_dark_preserved() -> None:
    """AC#6: load-bearing for UA control internals; not a token.

    ui-uplift-m7: the base ``:root`` now lives in tokens.css, so this reads
    that file. The declaration itself must NOT move into app.css — it
    belongs with the block it configures.
    """
    base = re.search(r"^:root\s*\{(.*?)^\}", TOKENS_NO_COMMENTS, re.S | re.M)
    assert base is not None, "no base :root block in tokens.css"
    assert re.search(r"color-scheme:\s*light\s+dark", base.group(1))


def test_light_dark_function_not_used() -> None:
    """AC#7: Baseline Newly Available, not Widely. Inside a custom property
    an unsupporting engine fails at SUBSTITUTION, and background-color does
    not inherit — so its initial value (transparent) would render.

    ui-uplift-m7 checks BOTH stylesheets: the refusal is about the token
    layer above all, and after the split checking only app.css would leave
    the file that actually declares the tokens unguarded.
    """
    for label, text in (("app.css", CSS_NO_COMMENTS), ("tokens.css", TOKENS_NO_COMMENTS)):
        assert not re.search(r"\blight-dark\s*\(", text), (
            f"light-dark() must not be used ({label}); ui-uplift-m6 AC#7"
        )


# ---------------------------------------------------------------------------
# Duration tokens
# ---------------------------------------------------------------------------
def test_duration_tokens_declared_once_in_base_root() -> None:
    assert BASE_RAW["--dur-fast"] == "200ms"
    assert BASE_RAW["--dur-normal"] == "400ms"
    assert BASE_RAW["--dur-slow"] == "600ms"
    # Duration is not colour-scheme dependent.
    for name in ("--dur-fast", "--dur-normal", "--dur-slow"):
        assert name not in DARK_RAW, f"{name} must not be redeclared in the dark block"


def test_no_hardcoded_durations_remain_on_animation_rules() -> None:
    for literal in ("0.6s", "400ms ease-out", "animation-duration: 200ms"):
        assert literal not in CSS_NO_COMMENTS, (
            f"{literal!r} should now reference a --dur-* token"
        )
    for token in ("var(--dur-fast)", "var(--dur-normal)", "var(--dur-slow)"):
        assert token in CSS_NO_COMMENTS


def test_dur_fast_stays_coupled_to_the_hx_swap_modifier() -> None:
    """row-fade-out must stay numerically in sync with index.html's
    hx-swap="outerHTML swap:200ms" modifier."""
    index = (REPO_ROOT / "server" / "frontend" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    m = re.search(r"swap:(\d+)ms", index)
    assert m is not None, "index.html no longer carries an hx-swap swap:<n>ms modifier"
    assert BASE_RAW["--dur-fast"] == f"{m.group(1)}ms", (
        f"--dur-fast is {BASE_RAW['--dur-fast']} but index.html swaps at "
        f"{m.group(1)}ms; the row-fade animation and the swap delay must match."
    )
    assert re.search(r"row-fade-out\s+var\(--dur-fast\)", CSS_NO_COMMENTS)


def test_skip_link_has_a_mode_conditional_on_accent_text_colour() -> None:
    """The live AA failure m6 closes: .skip-link:focus-visible set
    color:#fff unconditionally and, not being a button, never picked up the
    dark-mode override -> white on the dark accent at 2.53:1."""
    dark_block = re.search(
        r"@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{(.*?)\n\}",
        CSS_NO_COMMENTS,
        re.S,
    )
    assert dark_block is not None
    assert re.search(
        r"\.skip-link:focus-visible[^{]*\{[^}]*color:\s*var\(--bg\)",
        dark_block.group(1),
        re.S,
    ), "dark mode must override .skip-link:focus-visible's text colour"
    assert contrast_ratio(DARK["--bg"], DARK["--accent"]) >= 4.5


def test_favicon_tracks_light_accent() -> None:
    """SVG favicons render in browser-tab chrome and do NOT inherit page CSS
    custom properties, so this hex cannot be tokenised — only kept in sync.

    Critique M6/M7: this asserted ``LIGHT["--accent"] in svg`` — a substring
    test over the whole file — and ``favicon.svg`` embeds that same hex in
    the explanatory XML comment this milestone added. The one guard between
    a re-derived ``--accent`` and a stale brand colour in tab chrome was
    satisfied by a comment: delete the ``<rect>`` entirely and it still
    passed. Assert the rendered attribute instead.
    """
    svg = (APP_CSS_PATH.parent / "favicon.svg").read_text(encoding="utf-8")
    m = re.search(r"<rect[^>]*\bfill=\"(#[0-9a-fA-F]{6})\"", svg)
    assert m is not None, "favicon.svg has no <rect> with a fill attribute"
    assert m.group(1).lower() == LIGHT["--accent"].lower(), (
        f"favicon.svg <rect fill=\"{m.group(1)}\"> must track the light "
        f"--accent value {LIGHT['--accent']}"
    )


# ---------------------------------------------------------------------------
# The published artifact
# ---------------------------------------------------------------------------
def render_table() -> str:
    lines = [
        "| # | Mode | Site / selector | Foreground | Background | Ratio | Floor | SC | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, (mode, site, fg, bg, ratio, floor, ok) in enumerate(_rows(), start=1):
        if floor == EXEMPT:
            sc, floor_cell, verdict = "exempt", "—", "EXEMPT"
        else:
            # ui-uplift-m7: was `"1.4.3" if floor == TEXT else
            # "1.4.11 / large text"`. With LARGE gone, every non-TEXT floor
            # is SC 1.4.11 and nothing else, so the label says so plainly
            # instead of offering the reader a criterion no row uses.
            sc = "1.4.3" if floor == TEXT else "1.4.11"
            floor_cell = f"{floor}:1"
            verdict = "PASS" if ok else "FAIL"
        lines.append(
            f"| {i} | {mode} | {site} | `{fg}` | `{bg}` | **{ratio:.3f}:1** | "
            f"{floor_cell} | {sc} | {verdict} |"
        )
    return "\n".join(lines)


def render_roles_table() -> str:
    """AC#3's five roles, generated (critique H2).

    This table was hand-typed and outside the generated markers; nine of its
    twelve ratio cells disagreed with what the milestone's own code computes,
    several of them digit transpositions (6.583 vs 6.553, 7.199 vs 7.190) —
    the classic hand-typing tell, inside the artifact written to end exactly
    that failure mode.
    """
    light = {label: r for label, r, _f in _accent_role_checks("light")}
    dark = {label: r for label, r, _f in _accent_role_checks("dark")}
    _flash = "`@keyframes badge-flash`"
    sites = [
        ("1 · button ground", "`button, .button`",
         "role 1 button ground vs its own text"),
        ("1b · hover ground", "`button:hover`",
         "role 1b :hover ground vs its own text"),
        ("2 · focus ring vs `--bg`", "`:focus-visible`",
         "role 2 focus ring vs --bg"),
        ("2 · focus ring vs `--card-bg`", "`:focus-visible`",
         "role 2 focus ring vs --card-bg"),
        ("3 · link", "`.breadcrumb a`", "role 3 link vs --bg"),
        ("4 · skip-link ground", "`.skip-link:focus-visible`",
         "role 4 skip-link ground vs its own text"),
        ("5 · badge-flash border vs `--bg`", _flash,
         "role 5 badge-flash border vs --bg"),
        ("5 · badge-flash border vs `--card-bg`", _flash,
         "role 5 badge-flash border vs --card-bg"),
    ]
    lines = ["| Role | Site | Light | Dark |", "|---|---|---|---|"]
    for role, site, key in sites:
        lines.append(f"| {role} | {site} | {light[key]:.3f}:1 | {dark[key]:.3f}:1 |")
    return "\n".join(lines)


def render_headline() -> str:
    """The Headline block, generated (critique M4).

    It hand-typed "68 (34 light, 34 dark)" when the split was 36/32, on the
    first page of a document whose thesis is that hand-typed numbers are how
    three AA failures shipped.
    """
    rows = _rows()
    gated = [r for r in rows if r[5] != EXEMPT]
    exempt = [r for r in rows if r[5] == EXEMPT]
    light_n = sum(1 for r in rows if r[0] == "light")
    failures = [r for r in gated if not r[6]]
    tightest = min(gated, key=lambda r: r[4])
    text_rows = [r for r in gated if r[5] == TEXT]
    tightest_text = min(text_rows, key=lambda r: r[4])
    return "\n".join([
        "| | |",
        "|---|---|",
        f"| Pairs measured | **{len(rows)}** ({light_n} light, "
        f"{len(rows) - light_n} dark) |",
        f"| Of those, gated / exempt | **{len(gated)}** gated, "
        f"**{len(exempt)}** exempt (each with its reason in the Site column) |",
        f"| Failures | **{len(failures)}** |",
        f"| Tightest gated pair | {tightest[0]} `{tightest[1]}` — "
        f"**{tightest[4]:.3f}:1** against a {tightest[5]}:1 floor |",
        f"| Tightest gated text pair | {tightest_text[0]} `{tightest_text[1]}` — "
        f"**{tightest_text[4]:.3f}:1** against 4.5:1 |",
    ])


#: Every generated region in the artifact: marker name -> renderer.
#: Critique H2/M4: the roles table and the Headline block were BOTH hand-typed
#: and BOTH outside the single marker pair, so
#: ``test_published_contrast_table_is_current`` structurally could not see
#: them — it only ever compared the rows between the CONTRAST TABLE markers.
GENERATED_REGIONS: dict[str, object] = {
    "CONTRAST TABLE": render_table,
    "ROLES TABLE": render_roles_table,
    "HEADLINE": render_headline,
}


def _region_re(name: str) -> re.Pattern[str]:
    return re.compile(
        rf"<!-- BEGIN GENERATED {re.escape(name)} -->(.*?)"
        rf"<!-- END GENERATED {re.escape(name)} -->",
        re.S,
    )


def _extract_generated(doc: str, name: str = "CONTRAST TABLE") -> str:
    m = _region_re(name).search(doc)
    if m is None:
        raise RuntimeError(f"{TABLE_DOC} is missing the GENERATED {name} markers")
    return m.group(1).strip()


@pytest.mark.parametrize("name", sorted(GENERATED_REGIONS))
def test_published_region_is_current(name: str) -> None:
    """AC#2: the shipped artifact is generated, not hand-typed. If this
    fails, run `python -m tests.test_ui_contrast --update`."""
    doc = TABLE_DOC.read_text(encoding="utf-8")
    render = GENERATED_REGIONS[name]
    assert _extract_generated(doc, name) == render().strip(), (  # type: ignore[operator]
        f"{TABLE_DOC.relative_to(REPO_ROOT).as_posix()} region {name!r} is "
        f"stale — regenerate with: python -m tests.test_ui_contrast --update"
    )


#: A contrast ratio written as prose. Critique H2: the artifact claimed
#: "Ratios are computed, never typed" while carrying twelve typed ones, nine
#: of them wrong.
_TYPED_RATIO_RE = re.compile(r"\d+\.\d{2,3}:1")


def test_no_ratio_is_typed_outside_a_generated_region() -> None:
    """The artifact's own central claim, enforced instead of asserted.

    Historical ratios (the before-values this milestone closed) are the one
    legitimate typed number — they describe code that no longer exists, so
    they cannot drift. They live in the narrative sections and are allow-
    listed here explicitly.
    """
    doc = TABLE_DOC.read_text(encoding="utf-8")
    for name in GENERATED_REGIONS:
        doc = _region_re(name).sub("", doc)
    historical = {
        # Before-values this milestone closed, or measurements of code that
        # no longer exists. None can drift: the code they describe is gone.
        "1.342:1", "2.526:1", "4.974:1", "21.000:1", "2.414:1", "4.478:1",
        "1.062:1", "5.025:1",
        # Measurements of the REJECTED badge-flash alternatives, recorded so
        # the decision is auditable (30% fill tint, inset box-shadow).
        "3.095:1", "4.542:1", "3.044:1", "3.902:1",
    }
    targets = {
        # The "Solved for" column of the token family table. These are design
        # INPUTS — the target each token was binary-searched against — not
        # measurements of anything, so they cannot be generated from the
        # result. Written with 2 decimals precisely to read as targets.
        "3.30:1", "3.35:1", "5.30:1", "5.60:1", "6.20:1", "6.60:1",
    }
    typed = {m for m in _TYPED_RATIO_RE.findall(doc)} - historical - targets
    assert not typed, (
        f"{TABLE_DOC.name} types the ratio(s) {sorted(typed)} outside a "
        f"generated region. Either move the number into a generated region "
        f"or, if it is a historical before-value that can never drift, add "
        f"it to the allow-list in this test with a note."
    )


def test_table_covers_more_than_the_legacy_token_grid() -> None:
    """The overlay's 12-cell (6 tokens x 2 grounds) table is what let three
    AA failures ship. Guard against silently shrinking back toward it."""
    assert len(PAIRS) >= 60, f"only {len(PAIRS)} pairs registered"
    assert {m for m, *_ in PAIRS} == {"light", "dark"}


def test_every_faded_css_rule_has_a_registry_row() -> None:
    """Critique H3's structural guard: an `opacity` under 1.0 changes the
    ground text is read against, so every such rule needs composited rows.
    The m6 registry had none, and nothing would have noticed the next one."""
    faded = re.findall(r"opacity:\s*(0?\.\d+)\s*;", CSS_NO_COMMENTS)
    if not faded:
        return
    registered = {
        spec[2]
        for _m, _s, fg, bg, _fl in PAIRS
        for spec in (fg, bg)
        if isinstance(spec, tuple) and spec[0] == "fade"
    }
    for value in set(faded):
        assert float(value) in registered, (
            f"app.css has an `opacity: {value}` rule but no PAIRS row "
            f"composites at that alpha. A faded element's text and fill both "
            f"composite over the page, so its real contrast is unmeasured."
        )


def _update() -> None:
    doc = TABLE_DOC.read_text(encoding="utf-8")
    for name, render in GENERATED_REGIONS.items():
        body = render()  # type: ignore[operator]
        doc, count = _region_re(name).subn(
            lambda _m, _n=name, _b=body: (
                f"<!-- BEGIN GENERATED {_n} -->\n\n{_b}\n\n"
                f"<!-- END GENERATED {_n} -->"
            ),
            doc,
        )
        # Fail loudly rather than writing the file back unchanged — a silent
        # no-match here would leave a stale table looking freshly generated.
        if count != 1:
            raise RuntimeError(
                f"expected exactly 1 GENERATED {name} region in {TABLE_DOC}, "
                f"found {count}"
            )
    new = doc
    # newline="\n" explicitly: the default translates to os.linesep on
    # write, so regenerating on Windows vs POSIX would churn every line of
    # a checked-in artifact.
    TABLE_DOC.write_text(new, encoding="utf-8", newline="\n")
    print(f"wrote {len(PAIRS)} pairs to {TABLE_DOC}")


if __name__ == "__main__":
    if "--update" in sys.argv:
        _update()
    else:
        print(render_table())
