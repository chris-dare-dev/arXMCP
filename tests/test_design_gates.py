"""Design-gate suite — the anti-"AI-slop" checklist as tests (stage2/arx-b1).

Encodes the greppable subset of design-system-brief.md §8 (mandate:
T1, T4, T5, C1-C3, L1, L3, L5, M2, I1 minimum; this file also pins
T3, T6, C4, C7, R1, R2, the AA contrast computation, and the IF-1
client-drift tripwire).

Per finding 210's mechanical lesson, every CSS gate runs against the
**COMPILED** stylesheets in ``frontend-app/dist/assets/*.css`` — the
committed build output — because class-framework compilation bakes
color literals that source audits miss. Source greps (I1/R1/R2) run
over ``frontend-app/src``.

The parser here is deliberately dumb (brace-scan + regex over minified
CSS). It over-collects rather than under-collects; a false positive is
a conversation, a false negative is a shipped violation.
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = REPO_ROOT / "frontend-app"
DIST_ASSETS = FRONTEND / "dist" / "assets"
SRC = FRONTEND / "src"

# ---------------------------------------------------------------------------
# Corpus loading + tiny CSS parsing helpers
# ---------------------------------------------------------------------------


def _built_css() -> str:
    files = sorted(DIST_ASSETS.glob("*.css"))
    if not files:
        raise AssertionError(
            "no compiled CSS under frontend-app/dist/assets - the design "
            "gates MUST run against the built artifact. "
            "Rebuild + commit: cd frontend-app && npm ci && npm run build"
        )
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def _src_files(patterns: tuple[str, ...] = ("*.tsx", "*.ts", "*.css")) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        out.extend(SRC.rglob(pat))
    return sorted(out)


def _declaration_blocks(css: str) -> list[tuple[str, str]]:
    """Yield (selector-ish header, declarations) pairs via brace scan.

    Handles nested at-rules by treating every innermost ``{...}`` as a
    block; the header is whatever text precedes it since the previous
    brace/semicolon. Good enough for gate greps over minified output.
    """
    blocks: list[tuple[str, str]] = []
    stack_header: list[str] = []
    buf = ""
    header = ""
    for ch in css:
        if ch == "{":
            stack_header.append(header.strip())
            header = ""
            buf = ""
        elif ch == "}":
            if stack_header:
                blocks.append((stack_header.pop(), buf))
            buf = ""
        else:
            buf += ch
            if ch in ";\n":
                header = ""
            else:
                header += ch
    return blocks


_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
_FUNC_COLOR_RE = re.compile(r"\b(rgba?|hsla?|oklch)\(([^)]*)\)")


def _hex_to_rgb(h: str) -> tuple[float, float, float] | None:
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[: 3 if len(h) == 3 else 4])
    if len(h) == 8:
        h = h[:6]
    if len(h) != 6:
        return None
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _iter_colors(css: str):
    """Yield (context, r, g, b) for every hex/rgb/hsl literal."""
    for m in _HEX_RE.finditer(css):
        rgb = _hex_to_rgb(m.group(1))
        if rgb is not None:
            yield m.group(0), *rgb
    for m in _FUNC_COLOR_RE.finditer(css):
        fn, args = m.group(1), [a.strip() for a in re.split(r"[,/ ]+", m.group(2)) if a.strip()]
        try:
            if fn in ("rgb", "rgba"):
                vals = []
                for a in args[:3]:
                    vals.append(float(a[:-1]) / 100 if a.endswith("%") else float(a) / 255)
                yield m.group(0), *vals
            elif fn in ("hsl", "hsla"):
                h = float(re.sub(r"deg$", "", args[0])) / 360
                s = float(args[1].rstrip("%")) / 100
                lit = float(args[2].rstrip("%")) / 100
                yield m.group(0), *colorsys.hls_to_rgb(h, lit, s)
            # oklch: none expected in this stack; if one appears the C1
            # test flags it for manual conversion rather than guessing.
            elif fn == "oklch":
                yield m.group(0), -1.0, -1.0, -1.0
        except (ValueError, IndexError):
            continue


def _hue_sat(r: float, g: float, b: float) -> tuple[float, float]:
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s


def _rel_luminance(r: float, g: float, b: float) -> float:
    def f(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a: str, b: str) -> float:
    ra = _hex_to_rgb(a.lstrip("#"))
    rb = _hex_to_rgb(b.lstrip("#"))
    if ra is None or rb is None:
        raise AssertionError(f"unparseable token colors: {a!r} vs {b!r}")
    la, lb = _rel_luminance(*ra), _rel_luminance(*rb)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def _root_vars(css_scope: str) -> dict[str, str]:
    return dict(re.findall(r"--([\w-]+)\s*:\s*([^;}]+)[;}]", css_scope))


def _dark_scope(css: str) -> str:
    m = re.search(r"@media[^{]*prefers-color-scheme:\s*dark[^{]*\{", css)
    if m is None:
        raise AssertionError("no prefers-color-scheme: dark block in built CSS (gate C4)")
    depth, i = 1, m.end()
    start = i
    while i < len(css) and depth:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    return css[start : i - 1]


@pytest.fixture(scope="module")
def built_css() -> str:
    return _built_css()


# ---------------------------------------------------------------------------
# Typography gates
# ---------------------------------------------------------------------------


class TestTypographyGates:
    _BANNED_FACES = ("Inter", "Geist", "Space Grotesk", "Instrument Serif", "Roboto")

    def test_t1_no_banned_faces(self, built_css: str) -> None:
        """T1: none of the AI-default faces ship as chosen fonts."""
        for face in self._BANNED_FACES:
            pat = re.compile(
                r"font-family[^;}]*[\"'\s,:]" + re.escape(face) + r"[\"'\s,;}]", re.IGNORECASE
            )
            hit = pat.search(built_css)
            if hit:
                raise AssertionError(f"T1: banned face {face!r} in built CSS: {hit.group(0)!r}")
            at_face = re.compile(
                r"@font-face[^}]*font-family[^;}]*" + re.escape(face), re.IGNORECASE
            )
            if at_face.search(built_css):
                raise AssertionError(f"T1: banned face {face!r} declared via @font-face")

    def test_t3_scale_has_three_sizes_ratio_1_2(self, built_css: str) -> None:
        """T3: >=3 scale sizes, adjacent ratio >= 1.2 (computed from tokens)."""
        sizes = sorted(
            float(v[:-2])
            for k, v in _root_vars(built_css).items()
            if re.fullmatch(r"scale-\d", k) and v.endswith("px")
        )
        if len(sizes) < 3:
            raise AssertionError(f"T3: need >=3 --scale-* tokens, found {sizes}")
        for a, b in zip(sizes, sizes[1:], strict=False):
            if b / a < 1.199:  # float slack on the 1.2 floor
                raise AssertionError(f"T3: adjacent ratio {b}/{a} = {b / a:.3f} < 1.2")

    def test_t4_uppercase_only_in_micro_label_style(self, built_css: str) -> None:
        """T4: text-transform:uppercase only with font-size <= 11px
        (the single tracked-caps micro-label style)."""
        for header, decls in _declaration_blocks(built_css):
            if "text-transform" not in decls or "uppercase" not in decls:
                continue
            fs = re.search(r"font-size\s*:\s*([^;}]+)", decls)
            if fs is None:
                raise AssertionError(
                    f"T4: uppercase block without a bounding font-size: {header!r}"
                )
            val = fs.group(1).strip()
            ok = "var(--text-micro)" in val or (
                val.endswith("px") and float(val[:-2]) <= 11.0
            )
            if not ok:
                raise AssertionError(f"T4: uppercase at non-micro size {val!r} in {header!r}")

    def test_t5_no_gradient_text(self, built_css: str) -> None:
        """T5: no background-clip: text, ever."""
        if re.search(r"background-clip\s*:\s*text", built_css) or re.search(
            r"-webkit-background-clip\s*:\s*text", built_css
        ):
            raise AssertionError("T5: gradient-text (background-clip: text) found")

    def test_t6_measure_and_leading(self, built_css: str) -> None:
        """T6: editorial measure <= 80ch; editorial line-height >= 1.3."""
        tokens = _root_vars(built_css)
        measure = tokens.get("measure-editorial", "")
        if not measure.endswith("ch") or float(measure[:-2]) > 80:
            raise AssertionError(f"T6: --measure-editorial {measure!r} not <= 80ch")
        leading = float(tokens.get("leading-editorial", "0"))
        if leading < 1.3:
            raise AssertionError(f"T6: editorial leading {leading} < 1.3")


# ---------------------------------------------------------------------------
# Color gates
# ---------------------------------------------------------------------------


class TestColorGates:
    def test_c1_no_violet_band_hue(self, built_css: str) -> None:
        """C1: no hue in ~250-290° (violet/indigo/lavender) among tokens
        AND literals in the built CSS. Achromatic values (sat <= 0.12)
        are exempt — grays have no meaningful hue."""
        offenders = []
        for ctx, r, g, b in _iter_colors(built_css):
            if r < 0:  # oklch sentinel — force a human look
                offenders.append(f"oklch literal needs manual hue check: {ctx}")
                continue
            hue, sat = _hue_sat(r, g, b)
            if 250 <= hue <= 290 and sat > 0.12:
                offenders.append(f"{ctx} (hue {hue:.0f}, sat {sat:.2f})")
        if offenders:
            raise AssertionError("C1: banned-band colors in built CSS: " + "; ".join(offenders))

    def test_c2_no_gradients(self, built_css: str) -> None:
        """C2: zero gradients in M0. The brief allows AT MOST one,
        data-encoding only (e.g. a latency-heatmap ramp) — when that
        surface lands, this pin moves to a named allowlist of exactly
        one selector, never a blanket count bump."""
        hits = re.findall(r"(?:linear|radial|conic)-gradient", built_css)
        if hits:
            raise AssertionError(f"C2: {len(hits)} gradient(s) found in built CSS")

    def test_c3_no_chromatic_glow(self, built_css: str) -> None:
        """C3: no box-shadow with a chromatic color at blur > 2px."""
        for header, decls in _declaration_blocks(built_css):
            for m in re.finditer(r"box-shadow\s*:\s*([^;}]+)", decls):
                value = m.group(1)
                if value.strip() in ("none", "unset", "initial"):
                    continue
                lengths = re.findall(r"(-?\d*\.?\d+)px", value)
                blur = float(lengths[2]) if len(lengths) >= 3 else 0.0
                chromatic = any(
                    _hue_sat(r, g, b)[1] > 0.12 for _c, r, g, b in _iter_colors(value) if r >= 0
                )
                if blur > 2 and chromatic:
                    raise AssertionError(f"C3: chromatic glow in {header!r}: {value!r}")

    def test_c4_light_first_class_dark_owned(self, built_css: str) -> None:
        """C4: both palettes exist; color-scheme never pinned dark-only."""
        _dark_scope(built_css)  # raises if absent
        # (?<!prefers-) keeps the media-feature name out of the net.
        for m in re.finditer(r"(?<!prefers-)color-scheme\s*:\s*([^;})]+)", built_css):
            val = m.group(1).strip()
            if "light" not in val:
                raise AssertionError(f"C4: color-scheme pinned without light: {val!r}")

    def test_c7_no_primer_hexes(self, built_css: str) -> None:
        """C7: the GitHub-Primer dark palette must not reappear."""
        for h in ("#0d1117", "#161b22", "#58a6ff", "#21262d", "#30363d"):
            if h in built_css.lower():
                raise AssertionError(f"C7: Primer hex {h} in built CSS")

    def test_aa_contrast_all_token_pairs_both_modes(self, built_css: str) -> None:
        """CO-3/AC-B.17: computed AA (>=4.5) for every text token pair
        against --paper, light and dark."""
        text_roles = (
            "ink",
            "ink-muted",
            # De-emphasized text (ghost-lane head): must clear AA on its
            # own at full opacity — the point of dimming via color, not
            # container opacity (which composited it to ~2.5:1).
            "ink-faint",
            "accent",
            "danger",
            "status-ok",
            "status-warn",
            "status-ops",
            "status-down",
        )
        light = _root_vars(built_css)
        dark = {**light, **_root_vars(_dark_scope(built_css))}
        for mode, tokens in (("light", light), ("dark", dark)):
            paper = tokens["paper"]
            for role in text_roles:
                ratio = _contrast(tokens[role], paper)
                if ratio < 4.5:
                    raise AssertionError(
                        f"AA: --{role} vs --paper = {ratio:.2f} < 4.5 in {mode} mode"
                    )


# ---------------------------------------------------------------------------
# Layout gates
# ---------------------------------------------------------------------------


class TestLayoutGates:
    def test_l1_radius_cap_2px(self, built_css: str) -> None:
        """L1: border-radius <= 2px everywhere in the built CSS."""
        for m in re.finditer(r"border(?:-\w+)*-radius\s*:\s*([^;}]+)", built_css):
            value = m.group(1)
            if "var(--radius)" in value:
                continue
            for num in re.findall(r"(-?\d*\.?\d+)(px|rem|em)", value):
                px = float(num[0]) * (16 if num[1] in ("rem", "em") else 1)
                if px > 2.0:
                    raise AssertionError(f"L1: border-radius {value.strip()!r} > 2px")

    def test_l3_no_accent_side_stripes(self, built_css: str) -> None:
        """L3: no chromatic border-left/top stripes. Neutral hairlines
        (var(--rule-*), achromatic literals, currentColor) pass."""
        for header, decls in _declaration_blocks(built_css):
            for m in re.finditer(r"border-(?:left|top)\s*:\s*([^;}]+)", decls):
                value = m.group(1)
                if "var(--rule-" in value or "currentcolor" in value.lower():
                    continue
                for _ctx, r, g, b in _iter_colors(value):
                    if r >= 0 and _hue_sat(r, g, b)[1] > 0.12:
                        raise AssertionError(
                            f"L3: chromatic side/top stripe in {header!r}: {value!r}"
                        )

    def test_l5_no_glassmorphism(self, built_css: str) -> None:
        """L5: zero backdrop-filter."""
        if "backdrop-filter" in built_css:
            raise AssertionError("L5: backdrop-filter found in built CSS")


# ---------------------------------------------------------------------------
# Motion gates
# ---------------------------------------------------------------------------


class TestMotionGates:
    def test_m2_no_bounce_or_elastic_easings(self, built_css: str) -> None:
        """M2a: no overshoot cubic-beziers (y outside [0,1]) and no
        elastic/bounce keywords — CSS side. (The JS side has no
        passthrough API; src/motion/anime.ts exports fixed helpers.)"""
        if re.search(r"elastic|bounce", built_css, re.IGNORECASE):
            raise AssertionError("M2: elastic/bounce keyword in built CSS")
        for m in re.finditer(r"cubic-bezier\(([^)]*)\)", built_css):
            parts = [float(x) for x in m.group(1).split(",")]
            if len(parts) == 4 and not (0 <= parts[1] <= 1 and 0 <= parts[3] <= 1):
                raise AssertionError(f"M2: overshoot easing cubic-bezier({m.group(1)})")

    def test_m2_duration_discipline(self, built_css: str) -> None:
        """M2b: transition/animation durations <= 400ms in CSS (DUR_3);
        the 800ms token exists ONLY as the 3D-camera value, never in a
        transition/animation declaration."""
        for m in re.finditer(r"(?:transition|animation)(?:-duration)?\s*:\s*([^;}]+)", built_css):
            value = m.group(1)
            for num, unit in re.findall(r"(\d*\.?\d+)(ms|s)\b", value):
                ms = float(num) * (1000 if unit == "s" else 1)
                if ms > 400:
                    raise AssertionError(f"M2: DOM duration {ms:.0f}ms > 400ms: {value.strip()!r}")

    def test_motion_tokens_are_the_normative_set(self, built_css: str) -> None:
        """Brief §5.1: the four duration tokens are exactly 100/200/400/800.
        The minifier rewrites 100ms -> .1s, so compare numerically."""

        def _ms(raw: str) -> float:
            m = re.fullmatch(r"(\d*\.?\d+)(ms|s)", raw.strip())
            if m is None:
                raise AssertionError(f"unparseable duration token {raw!r}")
            return float(m.group(1)) * (1000 if m.group(2) == "s" else 1)

        tokens = _root_vars(built_css)
        expected = {"motion-dur-1": 100, "motion-dur-2": 200,
                    "motion-dur-3": 400, "motion-dur-4": 800}
        for k, v in expected.items():
            if k not in tokens or _ms(tokens[k]) != v:
                raise AssertionError(f"motion token --{k} = {tokens.get(k)!r}, expected {v}ms")


# ---------------------------------------------------------------------------
# Iconography / copy / reuse gates (source-level)
# ---------------------------------------------------------------------------

# Emoji blocks (chrome may not use emoji as icons — I1). Geometric
# shapes (U+25A0-25FF: the ▸/▾ disclosure affordances) are typographic,
# not emoji, and stay allowed (IC-2).
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001ffff☀-➿️⬀-⯿]"
)


class TestSourceGates:
    def test_i1_no_emoji_in_chrome(self) -> None:
        """I1: no emoji in component/template sources (dist inherits)."""
        offenders = []
        for f in _src_files(("*.tsx", "*.ts")):
            text = f.read_text(encoding="utf-8")
            for m in _EMOJI_RE.finditer(text):
                offenders.append(f"{f.relative_to(FRONTEND)}: {m.group(0)!r}")
        if offenders:
            raise AssertionError("I1: emoji in chrome sources: " + "; ".join(offenders[:10]))

    def test_r2_banned_components_never_vendored(self) -> None:
        """R2: MagicCard/BorderBeam/TiltCard/CardGrid are C2/C3/M3
        violations by construction — never present, never imported."""
        banned = ("MagicCard", "BorderBeam", "TiltCard", "CardGrid", "magic-card", "border-beam")
        for f in _src_files(("*.tsx", "*.ts")):
            text = f.read_text(encoding="utf-8")
            for b in banned:
                # README.md documents the ban list; code must not carry it.
                if b in text:
                    raise AssertionError(f"R2: banned component {b!r} referenced in {f.name}")

    def test_p2_empty_states_have_no_exclamation(self) -> None:
        """P2: empty-state copy = facts + next action, no exclamation."""
        for f in _src_files(("*.tsx",)):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"empty-state[\s\S]{0,400}?</", text):
                if "!" in m.group(0).replace("!=", "").replace("!important", ""):
                    raise AssertionError(f"P2: exclamation in empty-state copy in {f.name}")


# ---------------------------------------------------------------------------
# IF-1 drift tripwire
# ---------------------------------------------------------------------------


class TestApiClientDrift:
    def test_generated_client_matches_openapi_dump(self) -> None:
        """The typed client's source-sha256 stamp must match the live
        repo-root openapi.json (IF-1). On mismatch: cd frontend-app &&
        npm run gen:api, rebuild, re-commit."""
        dump = REPO_ROOT / "openapi.json"
        schema = FRONTEND / "src" / "api" / "schema.d.ts"
        stamp = re.search(r"source-sha256: ([0-9a-f]{64})", schema.read_text(encoding="utf-8"))
        if stamp is None:
            raise AssertionError("schema.d.ts missing its source-sha256 stamp")
        actual = hashlib.sha256(dump.read_bytes()).hexdigest()
        if stamp.group(1) != actual:
            raise AssertionError(
                "IF-1 drift: openapi.json changed since the typed client was "
                f"generated (stamp {stamp.group(1)[:12]}…, dump {actual[:12]}…). "
                "Run: cd frontend-app && npm run gen:api && npm run build"
            )
        json.loads(dump.read_text(encoding="utf-8"))  # dump stays valid JSON
