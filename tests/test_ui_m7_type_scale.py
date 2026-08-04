"""ui-uplift-m7 (UPL-3) — the two-voice type scale, and the tokens.css split.

Four acceptance criteria, plus the structural guards the split needs to stay
a token layer rather than a second stylesheet:

1. The h2->body step is no longer 1.100x and size, not weight alone, carries
   the heading hierarchy.
2. Every identifier surface takes ``--mono`` and sits inside the ONE existing
   ``tabular-nums`` rule — including the HTML-fragment builders, which had
   drifted from the templates rendering the same tables.
3. The page title scales via the authored ``clamp()`` instead of riding the
   UA ``h1 { font-size: 2em }``.
4. The type tokens EXTEND the existing ``:root``; there is no second token
   set anywhere in the product.

Note the deliberate division of labour with the three app.css line-cap tests
(m3/m4/m5): they bound the RULE sheet and still read ``app.css``. This module
owns ``tokens.css`` — its size bound and, more importantly, the assertion
that it declares no rules. A line cap on a token file is weak; "contains only
:root blocks" is the property that actually keeps the split honest.
"""

from __future__ import annotations

import re as _re
from pathlib import Path

from tests._ui_color import APP_CSS_PATH, REPO_ROOT, TOKENS_CSS_PATH, load_raw_tokens

APP_CSS: str = APP_CSS_PATH.read_text(encoding="utf-8")
APP_CSS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", APP_CSS, flags=_re.S)
TOKENS_CSS: str = TOKENS_CSS_PATH.read_text(encoding="utf-8")
TOKENS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", TOKENS_CSS, flags=_re.S)

TEMPLATES: Path = REPO_ROOT / "server" / "frontend" / "templates"
BASE_HTML: str = (TEMPLATES / "base.html").read_text(encoding="utf-8")

BASE_TOKENS, DARK_TOKENS = load_raw_tokens()

#: ``rem`` -> px at the UA default root size. Nothing in the product sets a
#: font-size on html/:root/body, so this is the real rendered size, not a
#: convenient assumption — ``test_nothing_sets_a_root_font_size`` pins it.
ROOT_PX = 16.0


def _rem_px(value: str) -> float:
    m = _re.fullmatch(r"([\d.]+)rem", value.strip())
    if m is None:
        raise RuntimeError(f"{value!r} is not a plain rem value")
    return float(m.group(1)) * ROOT_PX


# ---------------------------------------------------------------------------
# AC#4 — one token set, extending the existing :root
# ---------------------------------------------------------------------------
class TestAC4OneTokenSet:
    def test_type_tokens_live_in_the_same_root_as_the_colour_tokens(self) -> None:
        # The point of AC#4: not "tokens exist somewhere" but "there is ONE
        # token block". Assert the type family shares its :root with the m6
        # colour family and the duration family.
        for name in (
            "--text-meta", "--text-small", "--text-body",
            "--text-section", "--text-title", "--tracking-meta",
        ):
            assert name in BASE_TOKENS, f"{name} is not declared in the base :root"
        for neighbour in ("--fg", "--accent", "--mono", "--dur-fast"):
            assert neighbour in BASE_TOKENS, (
                f"{neighbour} left the base :root — the type tokens were "
                f"supposed to JOIN the existing block, not replace it"
            )

    def test_there_is_exactly_one_base_root_block_in_the_product(self) -> None:
        # A second token set is the failure AC#4 names. Count `:root` across
        # BOTH stylesheets rather than trusting that app.css stayed clean.
        static = TOKENS_CSS_PATH.parent
        roots: dict[str, int] = {}
        for p in sorted(static.glob("*.css")):
            text = _re.sub(r"/\*.*?\*/", "", p.read_text(encoding="utf-8"), flags=_re.S)
            roots[p.name] = len(_re.findall(r":root\s*\{", text))
        assert roots.get("app.css", 0) == 0, (
            f"app.css declares {roots.get('app.css')} :root block(s); since "
            f"ui-uplift-m7 every custom property belongs in tokens.css"
        )
        # tokens.css carries exactly two: the base block and the dark override.
        assert roots.get("tokens.css") == 2, (
            f"tokens.css should hold exactly 2 :root blocks (base + dark), "
            f"found {roots.get('tokens.css')}"
        )
        assert sum(roots.values()) == 2, f"token blocks are scattered: {roots}"

    def test_type_tokens_are_declared_once_and_not_in_the_dark_block(self) -> None:
        # Mirrors test_duration_tokens_declared_once_in_base_root: type is
        # not colour-scheme dependent, so redeclaring it in dark mode would
        # be a second, silently-diverging definition.
        for name in BASE_TOKENS:
            if name.startswith(("--text-", "--tracking-")):
                assert name not in DARK_TOKENS, (
                    f"{name} is redeclared in the dark :root; type is not "
                    f"colour-scheme dependent"
                )

    def test_sizes_are_rem_and_tracking_is_em(self) -> None:
        # px would pin the scale against the reader's own default font size
        # (WCAG SC 1.4.4) — the exact defect this milestone fixes on the
        # title. Tracking is correctly `em`, not `rem`: it must scale with
        # its OWN element, which is the entire point at 11px.
        for name in ("--text-meta", "--text-small", "--text-body", "--text-section"):
            value = BASE_TOKENS[name]
            assert value.endswith("rem"), f"{name} = {value!r} must be rem, not px"
        assert BASE_TOKENS["--tracking-meta"].endswith("em"), "tracking must be em"
        assert not BASE_TOKENS["--tracking-meta"].endswith("rem"), (
            "--tracking-meta must be em (scales with its own element), not rem"
        )
        assert "px" not in BASE_TOKENS["--text-title"], (
            "the title clamp's terms must all be rem/vw so text-only zoom "
            "scales them (SC 1.4.4)"
        )

    def test_no_font_size_literal_survives_in_the_rule_sheet(self) -> None:
        # The scale is only a scale if everything is on it. Before m7 there
        # were 14 untokenised font-size declarations.
        #
        # ui-uplift-m7 rectify: the CSS-wide keywords are exempt. `inherit` is
        # the OPPOSITE of a hard-coded size — it defers to whatever the
        # cascade already decided, which is exactly how the rectify fixed the
        # nested-<code>-in-a-heading bug (critique H1/H3/H5). A predicate that
        # forbids it would force that fix to hard-code a size, i.e. force the
        # very thing this test exists to prevent.
        css_wide = {"inherit", "initial", "unset", "revert", "revert-layer"}
        literals = [
            v.strip()
            for v in _re.findall(r"font-size:\s*([^;]+);", APP_CSS_NO_COMMENTS)
            if not v.strip().startswith("var(") and v.strip() not in css_wide
        ]
        assert not literals, (
            f"app.css still hard-codes {len(literals)} font-size value(s) "
            f"{literals} — every size belongs to a --text-* token"
        )

    def test_nothing_sets_a_root_font_size(self) -> None:
        # The premise the whole rem scale rests on: `--text-body: 1rem` is
        # byte-identical to today's rendering only while the root is the UA
        # default. A future `html { font-size: 62.5% }` would rescale the
        # entire console silently, so pin its absence.
        root_size_re = _re.compile(
            r"(?:^|[},])\s*(?:html|:root)\s*\{[^}]*font-size", _re.S | _re.M
        )
        for label, text in (
            ("app.css", APP_CSS_NO_COMMENTS),
            ("tokens.css", TOKENS_NO_COMMENTS),
        ):
            assert not root_size_re.search(text), (
                f"{label} sets a font-size on html/:root; every rem in the "
                f"product resolves against it"
            )


# ---------------------------------------------------------------------------
# AC#1 — the heading step
# ---------------------------------------------------------------------------
class TestAC1HeadingStep:
    def test_section_to_body_step_is_no_longer_1_10x(self) -> None:
        section = _rem_px(BASE_TOKENS["--text-section"])
        body = _rem_px(BASE_TOKENS["--text-body"])
        ratio = section / body
        # The measured baseline was EXACTLY 1.100x (17.6px vs 16px) — a
        # 1.6px difference, below what a reader resolves at reading
        # distance, which is why the heading signal was entirely the
        # inherited UA bold. Assert a real typographic step.
        assert ratio >= 1.2, (
            f"section/body = {ratio:.3f}x; ui-uplift-m7 AC#1 requires the "
            f"step to carry hierarchy by SIZE, not by weight alone "
            f"(the pre-m7 value was exactly 1.100x)"
        )

    def test_card_h2_is_edited_not_shadowed(self) -> None:
        # Every <h2> in the product sits inside <section class="card">, so
        # `.card h2` (0,1,1) shadows any bare `h2` rule (0,0,1). A milestone
        # that "fixed" this by adding a bare h2 rule would change nothing
        # rendered and every test that reads tokens would still pass.
        m = _re.search(r"\.card h2\s*\{([^}]*)\}", APP_CSS_NO_COMMENTS)
        assert m is not None, ".card h2 rule is missing"
        assert "var(--text-section)" in m.group(1), (
            "the section size must be set ON `.card h2` — a bare `h2` rule "
            "is shadowed by it and would have no effect"
        )

    def test_the_scale_is_not_regularised_into_a_modular_ramp(self) -> None:
        # The four sizes are hand-picked round pixels approximating ~1.2
        # without being a modular scale; a true 1.2 ramp from 11 gives
        # 13.2 and 15.84, which render blurry on a system stack. Pin the
        # round values so a future "tidy-up" cannot generate them.
        got = {
            name: _rem_px(BASE_TOKENS[name])
            for name in ("--text-meta", "--text-small", "--text-body", "--text-section")
        }
        assert got == {
            "--text-meta": 11.0,
            "--text-small": 13.0,
            "--text-body": 16.0,
            "--text-section": 20.0,
        }, f"the hand-picked round-pixel scale drifted: {got}"


# ---------------------------------------------------------------------------
# AC#3 — the fluid title
# ---------------------------------------------------------------------------
class TestAC3TitleClamp:
    #: The value authored by the 2026q3 discovery, identical in
    #: art-direction-scout-brief.md:493, synthesis.md:270 and
    #: final-report.md:193. A FOURTH, different clamp
    #: (`clamp(1.5rem, 4vw + 1rem, 2rem)`) sits in
    #: current-state-critic-brief.md:324 and is explicitly a hypothetical
    #: "credible v1 fill-in" — one grep returns both. This is the real one.
    AUTHORED = "clamp(1.5rem, 4vw + 0.5rem, 2.25rem)"

    def test_title_token_is_the_authored_clamp(self) -> None:
        got = BASE_TOKENS["--text-title"]
        norm = got.replace(" ", "")
        assert norm == self.AUTHORED.replace(" ", ""), (
            f"--text-title is {got!r}; the authored art direction is "
            f"{self.AUTHORED!r}. AC#3 constrains the clamp only negatively, "
            f"so an invented value passes the criterion while discarding "
            f"the design decision — do not re-derive it here."
        )

    def test_header_h1_uses_the_token_instead_of_the_ua_2em(self) -> None:
        m = _re.search(r"header h1\s*\{([^}]*)\}", APP_CSS_NO_COMMENTS)
        assert m is not None, "header h1 rule is missing"
        assert "var(--text-title)" in m.group(1), (
            "header h1 must carry an authored font-size; without one it "
            "rides the UA `h1 { font-size: 2em }` = a fixed 32px"
        )

    def test_clamp_satisfies_the_resize_text_criterion(self) -> None:
        # Two distinct hazards, both real, commonly conflated:
        #  (1) page zoom — a vw-ONLY preferred term cancels the zoom, so the
        #      preferred value needs a non-viewport term;
        #  (2) text-only zoom / a raised default font size — vw AND px both
        #      ignore it, so min and max must be rem.
        # Plus the published numeric rule: max <= 2.5x min.
        m = _re.fullmatch(
            r"clamp\(\s*([\d.]+)rem\s*,\s*[\d.]+vw\s*\+\s*([\d.]+)rem\s*,\s*([\d.]+)rem\s*\)",
            BASE_TOKENS["--text-title"].strip(),
        )
        assert m is not None, (
            "the title clamp must be clamp(<rem>, <vw> + <rem>, <rem>): rem "
            "bounds for text-only zoom, a rem term beside the vw for page zoom"
        )
        low, _pref_rem, high = (float(g) for g in m.groups())
        assert high / low <= 2.5, (
            f"clamp max/min = {high / low:.2f}x, over the 2.5x SC 1.4.4 ceiling"
        )

    def test_the_canon_deviation_is_declared_not_silent(self) -> None:
        # The design canon states a title range of 28-40px; this clamp's
        # minimum is 24px, 4px below that floor at a 390px viewport. Shipped
        # deliberately — but an undeclared deviation and an oversight are
        # indistinguishable to a later reader, which is the whole reason the
        # token block carries derivation comments at all.
        low = float(_re.match(r"clamp\(\s*([\d.]+)rem", BASE_TOKENS["--text-title"]).group(1))
        if low * ROOT_PX < 28.0:
            block = _re.search(r"--text-title:.*", TOKENS_CSS)
            assert block is not None
            assert "DECLARED DEVIATION" in TOKENS_CSS, (
                f"the title clamp's minimum is {low * ROOT_PX:.0f}px, below "
                f"the canon's 28px floor. Either raise it to 1.75rem or keep "
                f"the 'DECLARED DEVIATION' note in tokens.css explaining why."
            )


# ---------------------------------------------------------------------------
# AC#2 — the mono voice reaches every identifier surface
# ---------------------------------------------------------------------------
class TestAC2IdentifierSurfaces:
    def test_mono_is_applied_by_element_not_by_table_position(self) -> None:
        # Before m7, --mono reached four selectors and `table code` was one
        # of them — so an identifier was mono if and only if it happened to
        # sit in a table. The slug in the detail-page heading, the LanceDB
        # path, the discovery category and the discover-candidate paper id
        # all fell back to the UA generic monospace.
        m = _re.search(r"(?:^|[},])\s*code\s*,\s*time\s*\{([^}]*)\}", APP_CSS_NO_COMMENTS, _re.M)
        assert m is not None, (
            "expected a `code, time { … }` rule giving every identifier "
            "element the mono voice"
        )
        assert "var(--mono)" in m.group(1)
        # The explicit size is load-bearing, not tidiness: browsers apply a
        # smaller default font-size to monospace elements, so a <code> with
        # no font-size renders ~13px beside 16px neighbours regardless of
        # what the scale says.
        assert "var(--text-" in m.group(1), (
            "the mono rule must name a scale step; without it the browser's "
            "monospace-default-size quirk sets the size instead"
        )

    def test_time_elements_take_the_mono_voice(self) -> None:
        # <time> was in the tabular-nums rule but was never --mono at all —
        # the one identifier class rendering wholly in the prose voice.
        m = _re.search(r"(?:^|[},])\s*code\s*,\s*time\s*\{", APP_CSS_NO_COMMENTS, _re.M)
        assert m is not None

    def test_tabular_scope_is_one_rule_covering_code_and_time(self) -> None:
        decls = _re.findall(
            r"([^{}]*)\{[^}]*font-variant-numeric:\s*tabular-nums", APP_CSS_NO_COMMENTS
        )
        assert len(decls) == 1, (
            f"expected exactly ONE tabular-nums rule (AC#2: identifier "
            f"surfaces INHERIT the existing scope, they do not fork it); "
            f"found {len(decls)}"
        )
        selectors = decls[0]
        for sel in ("time", "code", ".status-badge", "dl.meta dd"):
            assert sel in selectors, f"{sel!r} missing from the tabular-nums scope"

    def test_paper_row_fragment_agrees_with_the_template_it_appends_to(self) -> None:
        # The live divergence m7 closes. `_paper_row_html` emitted bare
        # <td>{paper_id}</td> / <td>{added_at}</td> while
        # notebook_detail.html rendered the SAME table with <td><code>…
        # and <td><time>…, so an htmx-appended row rendered sans +
        # proportional beside identical mono + tabular rows until reload.
        # Assert the two AGREE, rather than pinning either shape alone —
        # that is the invariant, and it is what actually broke.
        from server.routes.notebooks import _paper_row_html

        out = _paper_row_html(
            slug="demo", paper_id="2401.01234", added_at="2026-08-04T12:00:00+00:00"
        )
        detail = (TEMPLATES / "notebook_detail.html").read_text(encoding="utf-8")
        papers_table = detail[detail.index("<th>Paper ID</th>"):]
        for wrapper in ("<code>", "<time>"):
            assert wrapper in papers_table, (
                f"the papers-table template no longer emits {wrapper}; update "
                f"the fragment builder in the same commit or they diverge again"
            )
            assert wrapper in out, (
                f"_paper_row_html emits no {wrapper}, but the template "
                f"rendering the same table does — an appended row would "
                f"render in a different voice than its neighbours"
            )

    def test_ingest_status_fragment_wraps_its_identifiers(self) -> None:
        # Inventory sites 28-31: the state token, the two timestamps, the run
        # id and the exit code were all bare text in this fragment — sans
        # voice, proportional figures, on values the operator reads to
        # correlate a run against a log.
        from server.routes.notebooks import _ingest_status_fragment

        failed = _ingest_status_fragment(
            slug="demo", run_id=42, status="failed", started_at=None,
            finished_at=None, exit_code=1, stderr_tail=None,
        )
        assert "<code>failed</code>" in failed, "the state token must be mono"
        assert "<code>42</code>" in failed, "the run id is an identifier"
        assert "<code>1</code>" in failed, "the exit code is an identifier"

        running = _ingest_status_fragment(
            slug="demo", run_id=7, status="running",
            started_at="2026-08-04T12:00:00+00:00", finished_at=None,
            exit_code=None, stderr_tail=None,
        )
        assert "<time>2026-08-04T12:00:00+00:00</time>" in running, (
            "the started-at timestamp must be a <time>, like every other "
            "timestamp the console renders"
        )

    def test_micro_caps_role_never_lands_on_an_identifier(self) -> None:
        # The recorded cost of text-transform: uppercase is that the
        # TRANSFORMED string reaches the accessibility tree, so VoiceOver in
        # Chrome can re-read a short word as an initialism. That cost is
        # acceptable only while the rule is confined to authored,
        # non-semantic label text. This is the guard on that constraint:
        # uppercase must never reach an element that renders operator data.
        forbidden = ("code", "time", "td", ".status-badge", "dd", "input", "pre")
        uppercase_rule_re = _re.compile(
            r"([^{}]*)\{[^}]*text-transform:\s*uppercase[^}]*\}"
        )
        for m in uppercase_rule_re.finditer(APP_CSS_NO_COMMENTS):
            selectors = [s.strip() for s in m.group(1).split(",")]
            for sel in selectors:
                assert sel == "th", (
                    f"text-transform: uppercase is applied to {sel!r}. It is "
                    f"confined to `th` (authored column labels) precisely "
                    f"because it rewrites the accessibility-tree string; "
                    f"never put it on an identifier surface {forbidden}."
                )

    def test_tracking_ships_together_with_the_micro_caps_size(self) -> None:
        # All-caps removes the ascender/descender word-shape cues a reader
        # uses at 11px, and positive tracking is the standard mitigation.
        # Shipping the uppercase without the tracking is worse than either
        # alone, so they are pinned to the same rule.
        m = _re.search(r"(?:^|[},])\s*th\s*\{([^}]*)\}", APP_CSS_NO_COMMENTS, _re.M)
        assert m is not None, "the th rule is missing"
        body = m.group(1)
        if "text-transform: uppercase" in body:
            assert "letter-spacing: var(--tracking-meta)" in body, (
                "uppercase without the compensating tracking"
            )
            assert "var(--text-meta)" in body, "the micro-caps role is the 11px step"


# ---------------------------------------------------------------------------
# The tokens.css split — the guards that keep it a token layer
# ---------------------------------------------------------------------------
class TestTokensCssSplit:
    def test_tokens_css_declares_only_root_blocks(self) -> None:
        """The structural guarantee behind the split.

        A line cap on a token file is weak — this is the property that
        actually matters. Strip the two ``:root`` blocks and their ``@media``
        wrapper; whatever is left must contain no ``{``, i.e. no rule.
        Without this, the next milestone that needs room simply moves rules
        here and the app.css cap becomes decorative.
        """
        text = TOKENS_NO_COMMENTS
        text = _re.sub(r":root\s*\{[^}]*\}", "", text)
        text = _re.sub(r"@media[^{]*\{\s*\}", "", text)
        assert "{" not in text, (
            "tokens.css contains something other than :root blocks:\n"
            f"{text.strip()[:400]}\n"
            "Rules belong in app.css — tokens.css is a token layer, not a "
            "second stylesheet."
        )

    def test_tokens_css_has_its_own_size_bound(self) -> None:
        # app.css's 480-line cap is asserted in lockstep by m3/m4/m5 and
        # measures the RULE sheet. The token sheet needs its own bound or
        # the split is an unbounded escape valve.
        count = TOKENS_CSS.count("\n") + (1 if not TOKENS_CSS.endswith("\n") else 0)
        assert count <= 200, (
            f"tokens.css is {count} lines — over its 200-line bound. The "
            f"per-token derivation comments are the deliverable, so this is "
            f"generous; if a milestone needs more, raise it deliberately "
            f"here (this cap is NOT one of the three app.css caps and does "
            f"not move with them)."
        )

    def test_base_html_links_tokens_before_app(self) -> None:
        # Custom properties must be declared before the rules that var()
        # them. Getting this order wrong renders every var() as its initial
        # value, and nothing else in the suite would notice.
        tokens_at = BASE_HTML.find('href="/ui/static/tokens.css"')
        app_at = BASE_HTML.find('href="/ui/static/app.css"')
        assert tokens_at != -1, "base.html does not link tokens.css"
        assert app_at != -1, "base.html does not link app.css"
        assert tokens_at < app_at, (
            "tokens.css must be linked BEFORE app.css — a custom property "
            "has to be declared before the rules that reference it"
        )

    def test_every_stylesheet_base_html_links_actually_exists(self) -> None:
        # The failure mode a token split introduces that nothing else here
        # would catch: base.html links a second stylesheet, and a typo'd
        # href or an unshipped file yields a 404 whose only symptom is that
        # every var() silently falls back to its initial value. Derive the
        # hrefs from the template rather than naming them.
        static = TOKENS_CSS_PATH.parent
        hrefs = _re.findall(r'<link rel="stylesheet" href="/ui/static/([^"]+)"', BASE_HTML)
        assert set(hrefs) == {"tokens.css", "app.css"}, (
            f"base.html links {hrefs}; expected exactly tokens.css + app.css"
        )
        for href in hrefs:
            assert (static / href).is_file(), (
                f"base.html links /ui/static/{href}, which does not exist in "
                f"{static.relative_to(REPO_ROOT).as_posix()}"
            )


# ---------------------------------------------------------------------------
# Baseline refusals carried forward
# ---------------------------------------------------------------------------
class TestBaselineRefusals:
    def test_text_wrap_is_not_used(self) -> None:
        """``final-report.md:492`` attaches ``text-wrap: balance`` to UPL-3
        by name, which makes it the obvious reach for a fluid title.

        It is Baseline **Newly** available (2024-05-13); Widely lands
        2026-11-13, after this milestone. Refused on exactly the basis
        ui-uplift-m6 refused ``light-dark()``. ``text-wrap: pretty`` is a
        harder no — Baseline limited, Firefox has not shipped it at all.
        """
        for label, text in (("app.css", APP_CSS_NO_COMMENTS), ("tokens.css", TOKENS_NO_COMMENTS)):
            assert "text-wrap" not in text, (
                f"{label} uses text-wrap. balance is Baseline Newly (Widely "
                f"2026-11-13, after this milestone) and pretty is Baseline "
                f"limited — both barred under the repo's Widely-only bar."
            )

    def test_letter_spacing_only_appears_via_the_token(self) -> None:
        # This milestone introduces the product's first letter-spacing. Keep
        # it tokenised so the tracking cannot drift per-selector.
        for value in _re.findall(r"letter-spacing:\s*([^;]+);", APP_CSS_NO_COMMENTS):
            assert value.strip() == "var(--tracking-meta)", (
                f"letter-spacing: {value.strip()!r} is hand-typed; use the "
                f"--tracking-meta token"
            )


# ---------------------------------------------------------------------------
# ui-uplift-m7 RECTIFY — guards for the Phase-3 critique findings.
# ---------------------------------------------------------------------------
NOTEBOOK_DETAIL: str = (
    REPO_ROOT / "server" / "frontend" / "templates" / "notebook_detail.html"
).read_text(encoding="utf-8")


class TestRectifyNestedCodeSizing:
    """H1/H3/H5 — all three critics, independently.

    ``code, time { font-size: var(--text-small) }`` sets an ABSOLUTE size on
    the element, so it also fires on a ``<code>`` nested inside a heading and
    beats the size the heading inherits down. ``notebook_detail.html`` renders
    its subject as ``<h2><code>{{ slug }}</code></h2>``, so the detail page's
    own heading rendered at 13px inside a 20px ``<h2>`` — below body text, and
    smaller than before this milestone, in the milestone whose whole thesis is
    that size carries the hierarchy.

    Not a specificity contest: the rules target different elements.
    """

    def test_heading_nested_code_inherits_the_heading_size(self) -> None:
        assert _re.search(
            r"h1 code,\s*h2 code,\s*h3 code\s*\{[^}]*font-size:\s*inherit",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        ), (
            "A <code> nested in a heading must inherit the heading's size. "
            "Without this, `code { font-size: --text-small }` shrinks it to "
            "13px — see ui-uplift-m7 critique H1/H3/H5."
        )

    def test_the_detail_page_heading_is_still_the_shape_that_broke(self) -> None:
        """If the template stops nesting <code> in <h2>, the rule above is
        dead weight and this test says so instead of passing silently."""
        assert _re.search(r"<h2><code>\{\{\s*notebook\.slug\s*\}\}</code></h2>",
                          NOTEBOOK_DETAIL), (
            "notebook_detail.html no longer renders <h2><code>slug</code></h2>. "
            "Re-check whether the h1/h2/h3 code rule is still needed."
        )

    def test_nested_code_keeps_the_mono_voice(self) -> None:
        """Only the SIZE defers to the heading. An identifier in a heading is
        still machine-addressable and must stay mono (AC#2)."""
        m = _re.search(r"h1 code,\s*h2 code,\s*h3 code\s*\{([^}]*)\}",
                       APP_CSS_NO_COMMENTS, flags=_re.S)
        assert m is not None
        assert "font-family" not in m.group(1), (
            "the nested-code rule must not override font-family — the mono "
            "voice is the point of wrapping an identifier in <code>"
        )


class TestRectifyStateTokenVoice:
    """H2/H6/M5 — brief-1 inventory site 10.

    ``latest_run.status`` is a state token: a machine-addressable value from a
    fixed vocabulary, which is exactly what AC#2 puts in the mono voice. It was
    left in sans while the ingest-status FRAGMENT builder rendered the same
    datum as ``<code>`` — two rendering paths for one value disagreeing about
    its voice, the same defect class ``_paper_row_html`` carried.
    """

    def test_latest_run_status_is_mono(self) -> None:
        assert _re.search(r"\(ingest <code>\{\{\s*latest_run\.status\s*\}\}</code>\)",
                          NOTEBOOK_DETAIL), (
            "latest_run.status must render inside <code> — it is a state "
            "token, and the ingest fragment builder already renders the same "
            "datum that way."
        )


class TestRectifyNestedSmallSizing:
    """M3/M12 — the badge's remediation text compounded to ~9.2px.

    ``.status-badge`` is 11px and ``server/routes/ui.py`` nests a ``<small>``
    inside it; UA ``<small>`` is 0.83em. The string that tells an operator what
    to DO about a degraded state ended up the smallest text in the product.
    """

    def test_remediation_is_pinned_to_the_badge_size(self) -> None:
        assert _re.search(
            r"\.status-badge__remediation\s*\{[^}]*font-size:\s*var\(--text-meta\)",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        ), (
            "the nested <small> remediation must be pinned to --text-meta, or "
            "UA 0.83em compounds it below the badge it explains"
        )


class TestRectifyProseStaysSans:
    """M13 — AC#2's two-voice discipline runs BOTH ways.

    The mono rule was scoped by input TYPE, which caught ``display_name`` — a
    human-readable notebook title, i.e. prose.
    """

    def test_mono_inputs_are_scoped_by_name_not_type(self) -> None:
        assert not _re.search(
            r"input\[type=\"text\"\][^{]*\{[^}]*font-family:\s*var\(--mono\)",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        ), "scoping the mono voice by input TYPE catches display_name (prose)"

    def test_display_name_input_is_not_mono(self) -> None:
        mono_rules = _re.findall(
            r"(input\[[^{]*\})\s*\{[^}]*font-family:\s*var\(--mono\)",
            APP_CSS_NO_COMMENTS,
            flags=_re.S,
        )
        for sel in mono_rules:
            assert "display_name" not in sel, (
                f"display_name is prose and must stay in the sans voice: {sel}"
            )


class TestRectifyCrossFileTokenIntegrity:
    """M6 — nothing guarded that a ``var(--x)`` in the RULE sheet resolves to a
    token actually declared in the TOKEN sheet.

    Before ui-uplift-m7 the two lived in one file, so a typo was visible on
    inspection. Splitting them made the correspondence a cross-file invariant
    with no checker: a renamed or dropped token now fails silently at runtime
    (the property resolves to its initial value) and no test notices.
    """

    def test_every_var_reference_resolves_to_a_declared_token(self) -> None:
        declared = set(_re.findall(r"(--[\w-]+)\s*:", TOKENS_NO_COMMENTS))
        referenced = set(_re.findall(r"var\((--[\w-]+)", APP_CSS_NO_COMMENTS))
        missing = sorted(referenced - declared)
        assert not missing, (
            f"app.css references {missing} but tokens.css declares no such "
            f"token. Since the m7 split these are different files, so this "
            f"resolves to the property's initial value at runtime — silently."
        )

    def test_no_token_is_declared_in_the_rule_sheet(self) -> None:
        """AC#4's other half: one token home, not two."""
        stray = _re.findall(r"^\s*(--[\w-]+)\s*:", APP_CSS_NO_COMMENTS, flags=_re.M)
        assert not stray, (
            f"app.css declares custom properties {sorted(set(stray))}; tokens "
            f"live in tokens.css. Two token homes is what AC#4 forbids."
        )


class TestRectifyTabularNumsScope:
    """M10 — AC#2 has two halves and only one was guarded.

    "Uses ``--mono`` AND inherits the existing tabular-nums scope" means the
    two selector sets must agree. The tabular list was a four-name hand-list
    that predated m7, and m7 added mono surfaces without extending it, so
    identifier text rendered mono with PROPORTIONAL figures — the columns of
    digits that motivated tabular-nums in the first place.

    Derived, not hand-listed: a future milestone that adds a mono surface and
    forgets the tabular rule fails here instead of shipping misaligned digits.
    """

    @staticmethod
    def _selectors_with(decl: str) -> set[str]:
        out: set[str] = set()
        for sel, body in _re.findall(r"([^{}]+)\{([^}]*)\}", APP_CSS_NO_COMMENTS):
            if decl in body:
                out.update(s.strip() for s in sel.split(",") if s.strip())
        return out

    def test_every_mono_surface_inherits_tabular_nums(self) -> None:
        mono = self._selectors_with("font-family: var(--mono)")
        tabular = self._selectors_with("font-variant-numeric: tabular-nums")
        missing = sorted(mono - tabular)
        assert not missing, (
            f"{missing} render in the --mono voice but are outside the "
            f"tabular-nums scope. AC#2 requires both — an identifier shown "
            f"with proportional figures does not align in a column."
        )

    def test_the_tabular_rule_is_still_a_single_declaration(self) -> None:
        """Extended IN PLACE. A second tabular-nums rule would fork the scope,
        which is what "inherits the EXISTING scope" rules out."""
        n = len(_re.findall(r"font-variant-numeric:\s*tabular-nums",
                            APP_CSS_NO_COMMENTS))
        assert n == 1, f"expected exactly 1 tabular-nums declaration, found {n}"
