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

Floors: **4.5:1** for text (SC 1.4.3), **3:1** for non-text UI boundaries and
graphical objects (SC 1.4.11) and for large text (>=24px, or >=18.7px bold —
in this stylesheet only a bare ``header h1``).

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
LARGE = 3.0


def _resolve(spec: object, mode: str) -> str:
    """Resolve a pair-registry colour spec to the hex a browser paints."""
    table = LIGHT if mode == "light" else DARK
    if isinstance(spec, tuple):
        _tag, base, pct, other = spec
        return mix_oklab(_resolve(base, mode), pct, _resolve(other, mode))
    if isinstance(spec, str) and spec.startswith("--"):
        return table[spec]
    if isinstance(spec, str):
        return spec
    raise RuntimeError(f"unresolvable colour spec: {spec!r}")


def mix(base: object, pct: float, other: object) -> tuple:
    return ("mix", base, pct, other)


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
    _p(_m, "header h1 a (large text)", "--fg", "--bg", LARGE)
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


def test_accent_satisfies_all_five_roles() -> None:
    """AC#3: ONE --accent token, five simultaneous roles, in BOTH modes."""
    for mode, table in (("light", LIGHT), ("dark", DARK)):
        on_accent = WHITE if mode == "light" else table["--bg"]
        checks = [
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
        ]
        for label, ratio, floor in checks:
            assert ratio >= floor, f"{mode}: --accent {label} = {ratio:.3f}:1 < {floor}"


def test_focus_ring_verified_against_card_bg_not_only_bg() -> None:
    """In dark mode --card-bg is LIGHTER than --bg, so it is the binding
    ground for a light accent ring. Assert explicitly rather than assuming
    the --bg pair covers it."""
    assert DARK["--card-bg"] != DARK["--bg"]
    assert contrast_ratio(DARK["--accent"], DARK["--card-bg"]) >= 3.0
    assert contrast_ratio(DARK["--border"], DARK["--card-bg"]) >= 3.0


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


def test_all_colour_tokens_are_oklch_on_one_of_two_hues() -> None:
    """AC#1, half two: ONE hue decision per semantic family, and the SAME
    construction in both modes — not achromatic greys in light against a
    cool-tinted Primer clone in dark."""
    hue_re = re.compile(r"oklch\(\s*[\d.]+%\s+[\d.]+\s+([\d.]+)(?:deg)?\s*\)", re.I)
    seen: dict[str, set[str]] = {}
    for label, raw in (("light", BASE_RAW), ("dark", DARK_RAW)):
        for name, value in raw.items():
            if name in ("--mono",) or name.startswith("--dur-"):
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
    """AC#6: load-bearing for UA control internals; not a token."""
    base = re.search(r"^:root\s*\{(.*?)^\}", CSS_NO_COMMENTS, re.S | re.M)
    assert base is not None
    assert re.search(r"color-scheme:\s*light\s+dark", base.group(1))


def test_light_dark_function_not_used() -> None:
    """AC#7: Baseline Newly Available, not Widely. Inside a custom property
    an unsupporting engine fails at SUBSTITUTION, and background-color does
    not inherit — so its initial value (transparent) would render."""
    assert not re.search(r"\blight-dark\s*\(", CSS_NO_COMMENTS), (
        "light-dark() must not be used in ui-uplift-m6 v0"
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
    custom properties, so this hex cannot be tokenised — only kept in sync."""
    svg = (APP_CSS_PATH.parent / "favicon.svg").read_text(encoding="utf-8")
    assert LIGHT["--accent"] in svg.lower(), (
        f"favicon.svg must use the light --accent value {LIGHT['--accent']}"
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
        sc = "1.4.3" if floor == TEXT else "1.4.11 / large text"
        lines.append(
            f"| {i} | {mode} | {site} | `{fg}` | `{bg}` | **{ratio:.3f}:1** | "
            f"{floor}:1 | {sc} | {'PASS' if ok else 'FAIL'} |"
        )
    return "\n".join(lines)


_REGION_RE = re.compile(
    rf"{re.escape(BEGIN_MARK)}(.*?){re.escape(END_MARK)}", re.S
)


def _extract_generated(doc: str) -> str:
    m = _REGION_RE.search(doc)
    if m is None:
        raise RuntimeError(f"{TABLE_DOC} is missing the generated-table markers")
    return m.group(1).strip()


def test_published_contrast_table_is_current() -> None:
    """AC#2: the shipped artifact is generated, not hand-typed. If this
    fails, run `python -m tests.test_ui_contrast --update`."""
    doc = TABLE_DOC.read_text(encoding="utf-8")
    assert _extract_generated(doc) == render_table().strip(), (
        f"{TABLE_DOC.relative_to(REPO_ROOT).as_posix()} is stale — regenerate "
        f"with: python -m tests.test_ui_contrast --update"
    )


def test_table_covers_more_than_the_legacy_token_grid() -> None:
    """The overlay's 12-cell (6 tokens x 2 grounds) table is what let three
    AA failures ship. Guard against silently shrinking back toward it."""
    assert len(PAIRS) >= 60, f"only {len(PAIRS)} pairs registered"
    assert {m for m, *_ in PAIRS} == {"light", "dark"}


def _update() -> None:
    doc = TABLE_DOC.read_text(encoding="utf-8")
    new, count = _REGION_RE.subn(
        lambda _m: f"{BEGIN_MARK}\n\n{render_table()}\n\n{END_MARK}", doc
    )
    # Fail loudly rather than writing the file back unchanged — a silent
    # no-match here would leave a stale table looking freshly generated.
    if count != 1:
        raise RuntimeError(
            f"expected exactly 1 generated-table region in {TABLE_DOC}, found {count}"
        )
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
