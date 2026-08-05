"""ui-uplift-m8 (UPL-2) — retire ``.card``; adopt the graded rule ladder.

**AC#1 was unfalsifiable before this module existed.** "No ``.card``
primitive remains" was asserted by nothing: a repo-wide grep at research time
found the string only inside two test *comments*. The epic's headline claim
was defended by prose. Everything here is derived from the on-disk tree.

Two failure modes shaped how these are written:

- **Scanning comments instead of code.** ui-uplift-m10's rectify pass caught
  its own no-relevance guard flagging the rationale that explained the
  refusal. Every CSS assertion below reads the comment-stripped text, and the
  template assertions read markup only — which matters here more than usual,
  because the stylesheet's m8 comments necessarily *talk about* ``.card``.
- **Guards that pass vacuously.** A check that enumerates a set and asserts
  something about each member passes trivially when the set is empty, so the
  counts are pinned alongside the properties.
"""

from __future__ import annotations

import re as _re
from html.parser import HTMLParser as _HTMLParser

import pytest

from tests._ui_color import (
    APP_CSS_PATH,
    REPO_ROOT,
    TOKENS_CSS_PATH,
    contrast_ratio,
    load_raw_tokens,
    load_tokens,
)

APP_CSS: str = APP_CSS_PATH.read_text(encoding="utf-8")
APP_CSS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", APP_CSS, flags=_re.S)
TOKENS_CSS: str = TOKENS_CSS_PATH.read_text(encoding="utf-8")
TOKENS_NO_COMMENTS: str = _re.sub(r"/\*.*?\*/", "", TOKENS_CSS, flags=_re.S)
COMBINED_NO_COMMENTS: str = APP_CSS_NO_COMMENTS + "\n" + TOKENS_NO_COMMENTS

_TEMPLATES = REPO_ROOT / "server" / "frontend" / "templates"
TEMPLATE_PATHS = sorted(_TEMPLATES.glob("*.html"))
_ROUTES = REPO_ROOT / "server" / "routes"
ROUTE_PATHS = sorted(_ROUTES.glob("*.py"))

BASE_RAW, DARK_RAW = load_raw_tokens()
LIGHT, DARK = load_tokens()

#: The three weights the 2026q3 discovery authored BY NAME
#: (``discover/art-direction-scout-brief.md:176-177``,
#: ``artifacts/synthesis.md:234``). The roadmap item carries neither the names
#: nor the grading — the same drop-shape as m7's ``clamp()`` values and m10's
#: finding-H3 rules — so they are pinned here as authored requirements.
RULE_TOKENS = ("--rule-section", "--rule-row", "--rule-meta")

#: Elements that never open a scope, so they must not be pushed onto the
#: ancestry stack in :func:`_element_ancestries`.
_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "source", "track", "wbr",
})


class _AncestryScanner(_HTMLParser):
    """Record the open-element chain above every occurrence of a tag.

    Added 2026-08-05. ``TestExemptionIsConditionalPerSite`` used to prove
    "these cells are grouped by their table" with ``"tbody" in selector`` — a
    substring test against a CSS string, which says nothing about what
    renders. This walks the real element nesting instead.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.chains: dict[str, list[list[str]]] = {}

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _VOID_ELEMENTS:
            return
        self.chains.setdefault(tag, []).append(list(self.stack))
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: object) -> None:
        self.chains.setdefault(tag, []).append(list(self.stack))

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass


def _strip_jinja(markup: str) -> str:
    """Remove Jinja comments, statements and expressions.

    What is left is the HTML skeleton every render shares, which is the level
    the structural claims are about. Interpolated VALUES cannot change
    nesting; only ``{% if %}`` around whole elements could, and the templates
    here wrap attributes and text, not element boundaries.
    """
    for pattern in (r"\{#.*?#\}", r"\{%.*?%\}", r"\{\{.*?\}\}"):
        markup = _re.sub(pattern, "", markup, flags=_re.S)
    return markup


def _split_selector_list(selector: str) -> list[str]:
    """Split a selector list on top-level commas only.

    ``main > :where(section, div) + div`` is ONE selector; a naive
    ``split(",")`` makes it two and the second is nonsense.
    """
    parts, depth, current = [], 0, []
    for ch in selector:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _selector_subjects(selector: str) -> set[str]:
    """The element name each alternative in ``selector`` finally targets.

    Returns an empty-string entry for a compound with no element name (a bare
    class or id), which is exactly the case a structural claim must not be
    allowed to make: ``.discover-candidate`` cannot be "grouped by its
    table", because nothing about that selector says it is in one.
    """
    subjects: set[str] = set()
    for alt in _split_selector_list(selector):
        # Drop functional pseudo-class arguments before splitting on
        # descendant/child/sibling combinators, so `:has(tbody:empty)` does
        # not contribute its inner tokens as compounds.
        flat = _re.sub(r"\([^()]*\)", "", alt)
        compounds = [c for c in _re.split(r"[\s>+~]+", flat) if c]
        last = compounds[-1] if compounds else ""
        m = _re.match(r"^([a-zA-Z][\w-]*)", last)
        subjects.add(m.group(1).lower() if m else "")
    return subjects


def _element_ancestries(tag: str) -> list[list[str]]:
    """Every ancestor chain under which ``tag`` is emitted by a template."""
    chains: list[list[str]] = []
    for path in TEMPLATE_PATHS:
        scanner = _AncestryScanner()
        scanner.feed(_strip_jinja(path.read_text(encoding="utf-8")))
        chains.extend(scanner.chains.get(tag, []))
    return chains


# ---------------------------------------------------------------------------
# AC#1 — the primitive is gone, and that is now checkable
# ---------------------------------------------------------------------------
class TestCardPrimitiveIsGone:
    def test_no_template_carries_the_card_class(self) -> None:
        """The check AC#1 never had.

        Reads markup, not prose: the m8 templates explain the deletion in
        Jinja comments that necessarily contain the string ``class="card"``,
        so a naive substring scan over the file would fail on the very
        comment documenting the fix.
        """
        assert TEMPLATE_PATHS, "no templates found — the glob is wrong"
        offenders = []
        for path in TEMPLATE_PATHS:
            markup = _re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"),
                             flags=_re.S)
            for m in _re.finditer(r'class="([^"]*)"', markup):
                if "card" in m.group(1).split():
                    offenders.append(f"{path.name}: {m.group(0)}")
        assert not offenders, (
            "ui-uplift-m8 AC#1: the `.card` primitive must not remain in any "
            f"template. Found {len(offenders)}:\n  " + "\n  ".join(offenders)
        )

    def test_no_fragment_builder_emits_the_card_class(self) -> None:
        """The Jinja templates were never the only emitter of markup — the
        htmx fragment builders in ``server/routes/`` emit class attributes
        too, and a class re-introduced there would be invisible to the
        template check above."""
        assert ROUTE_PATHS, "no route modules found — the glob is wrong"
        offenders = [
            f"{p.name}:{i}"
            for p in ROUTE_PATHS
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            for m in _re.finditer(r'class=\\?"([^"\\]*)', line)
            if "card" in m.group(1).split()
        ]
        assert not offenders, (
            f"ui-uplift-m8 AC#1: a fragment builder emits class=\"card\": "
            f"{offenders}"
        )

    def test_no_stylesheet_declares_a_card_rule(self) -> None:
        """Deleting the markup without deleting the rule leaves the primitive
        alive and re-appliable. Comment-stripped, because both stylesheets
        discuss the deletion at length."""
        selectors = _re.findall(r"\.card\b[^{;]*\{", COMBINED_NO_COMMENTS)
        assert not selectors, (
            f"ui-uplift-m8 AC#1: {selectors} still declare rules for the "
            f"deleted primitive."
        )

    def test_structure_carries_no_border_radius(self) -> None:
        """AC#1's geometry half. ``.card``'s 6px was the file's only radius on
        structure; what survives must be the control layer plus the two
        exceptions the art direction and physics grant, ENUMERATED so a new
        one cannot be added silently."""
        radii = _re.findall(r"([^{}]+)\{[^}]*border-radius:\s*([^;}]+)",
                            APP_CSS_NO_COMMENTS)
        found = {sel.strip(): value.strip() for sel, value in radii}
        assert "6px" not in found.values(), (
            "the 6px structural radius is back; AC#1 deletes it with .card"
        )
        allowed_exceptions = {".status-badge", "@keyframes spin"}
        for selector, value in found.items():
            # m8 rectify (M17): check EVERY selector in a comma group, not
            # just the last — a radius on a non-final selector was invisible
            # here. And `[tabindex]` is dropped from the control pattern:
            # `main[tabindex="-1"]` is the main landmark, so matching it would
            # let structure carry a radius under the name of a control.
            parts = [s.strip() for s in selector.split(",") if s.strip()]
            is_control = all(
                _re.search(r"(input|textarea|button|\.button|\.skip-link"
                           r"|:focus-visible)", part)
                for part in parts
            )
            leaf = " , ".join(parts)
            is_circle = value == "50%"
            named = any(exc in selector for exc in allowed_exceptions)
            assert is_control or is_circle or named, (
                f"`{leaf}` carries border-radius: {value} but is neither a "
                f"control nor one of the two documented exceptions "
                f"({sorted(allowed_exceptions)}). ui-uplift-m8's claim is "
                f"'radius marks the control layer, with named exceptions' — "
                f"an unnamed third exception makes that claim false."
            )


# ---------------------------------------------------------------------------
# The ladder itself
# ---------------------------------------------------------------------------
class TestRuleLadder:
    @pytest.mark.parametrize("name", RULE_TOKENS)
    def test_the_authored_token_is_declared(self, name: str) -> None:
        assert name in BASE_RAW, (
            f"{name} is one of the three weights the discovery authored by "
            f"name; the roadmap summary dropped all three, so losing it again "
            f"is the documented failure mode, not a new one."
        )

    @pytest.mark.parametrize("name", RULE_TOKENS)
    def test_the_token_is_actually_used(self, name: str) -> None:
        """A minted-but-unused token is a claim the sheet does not honour."""
        assert f"var({name})" in APP_CSS_NO_COMMENTS, (
            f"{name} is declared but no rule references it."
        )

    @pytest.mark.parametrize("name", RULE_TOKENS)
    def test_the_token_is_not_forked_across_colour_schemes(self, name: str) -> None:
        """One declaration, both modes. The values name ``var(--border)`` and
        ``var(--bg)``, which substitute at USE time against whichever
        ``:root`` won — so a dark redeclaration would fork the ladder into
        two definitions free to drift, which is what the m6/m7 token
        discipline exists to prevent."""
        assert name not in DARK_RAW, (
            f"{name} is redeclared in the dark :root. It resolves per mode "
            f"already; two declarations can only drift apart."
        )

    def test_the_ladder_is_horizontal_only(self) -> None:
        """The discovery's constraint, verbatim: "three weights, horizontal
        only. No vertical edges anywhere." A vertical rule would re-introduce
        the box one edge at a time.

        ``*-color`` sub-properties are excluded, and the exclusion is the
        interesting part rather than a convenience: the spinner is a circle
        drawn from a 4-sided border with ``border-right-color: transparent``
        cutting the arc. That declaration REMOVES an edge; reading it as a
        vertical rule would fail this guard on the one rule in the file that
        proves the constraint is being honoured.
        """
        vertical = [
            decl for decl in _re.findall(
                r"border-(?:left|right|inline-start|inline-end)[\w-]*\s*:[^;}]*",
                APP_CSS_NO_COMMENTS,
            )
            if not _re.match(r"border-\w+-color\b", decl)
        ]
        # m8 rectify (M9): the four-sided `border:` SHORTHAND draws vertical
        # edges too, and the pattern above never saw it — so a square,
        # differently-named box passed this guard and all three of its
        # siblings. `border: none` and `border: 0` remove edges; a shorthand
        # with a width and a style is the box coming back under another name.
        # Scoped to STRUCTURE. Controls keep a four-sided box by design — it
        # is the other half of "radius 0 on structure, 4px on controls" — so
        # inputs, textareas, buttons and the spinner's `2px solid
        # currentColor` arc are not vertical edges in the ladder's sense.
        _CONTROL = _re.compile(
            r"(input|textarea|button|\.button|\.skip-link|:focus-visible"
            r"|@keyframes|\.status-badge)"
        )
        shorthand = [
            f"{sel.strip()[:40]} {{ {decl.strip()} }}"
            for sel, decl in _re.findall(
                r"([^{}]+)\{[^{}]*?((?<![\w-])border\s*:[^;}]*)",
                APP_CSS_NO_COMMENTS, flags=_re.S,
            )
            if not _re.search(r":\s*(none|0)\s*$", decl)
            and not _CONTROL.search(sel)
        ]
        assert not vertical and not shorthand, (
            f"vertical edges found: {vertical + shorthand}. The ladder is "
            f"horizontal only; the box was deleted on purpose, and the "
            f"four-sided `border:` shorthand re-draws it."
        )

    def test_the_block_ladder_uses_the_section_weight(self) -> None:
        """The nine former cards are separated by the FULL weight, because a
        reader must perceive that boundary to understand the page — which is
        exactly the condition under which SC 1.4.11's decorative exemption
        does NOT apply."""
        m = _re.search(r"main\s*>[^{}]*\+[^{}]*\{([^}]*)\}", APP_CSS_NO_COMMENTS)
        assert m is not None, "the block-ladder rule is missing from app.css"
        assert "var(--rule-section)" in m.group(1), (
            "the boundary between top-level blocks must take the FULL weight: "
            "it is the sole cue for the grouping, so a tinted rung there "
            "would be structural and its exemption would be false."
        )

    def test_the_thead_separation_uses_the_section_weight(self) -> None:
        """AC#3. The header boundary is structural — a reader who cannot see
        where the header ends reads a label as data."""
        m = _re.search(r"thead\s+th\s*\{([^}]*)\}", APP_CSS_NO_COMMENTS)
        assert m is not None, "no `thead th` rule — AC#3's rule is missing"
        assert "var(--rule-section)" in m.group(1)

    def test_the_th_fill_survives_alongside_the_rule(self) -> None:
        """AC#2 and AC#3 pull opposite ways on ``th``: one keeps ``--card-bg``
        as the control ground for table headers, the other migrates the
        separation to a rule weight. The resolution is BOTH — reading AC#3
        alone and deleting the fill breaks
        ``test_ui_m5_create_remove_in_place``'s guard, and reading AC#2 alone
        leaves the boundary at 1.03:1."""
        # Anchored at line start: a bare `(?<![\w.-])th` also matches the
        # `th` in `thead th`, which is the RULE half of this pair and would
        # make the assertion read the wrong block.
        m = _re.search(r"^th\s*\{([^}]*)\}", APP_CSS_NO_COMMENTS, flags=_re.M)
        assert m is not None, "the base `th` rule is gone"
        assert "background: var(--card-bg)" in m.group(1), (
            f"the base th rule no longer carries the control-ground fill: "
            f"{m.group(1).strip()!r}"
        )


# ---------------------------------------------------------------------------
# The exemption is conditional, so measure it
# ---------------------------------------------------------------------------
class TestGradingIsMeasuredNotAsserted:
    def test_the_section_rung_clears_sc_1411_on_every_ground(self) -> None:
        """The one rung that carries structure must clear 3:1 wherever it is
        drawn — on the canvas (blocks, header, footer) AND on the ``th`` fill
        it separates the header from."""
        for mode, table in (("light", LIGHT), ("dark", DARK)):
            for ground in ("--bg", "--card-bg"):
                ratio = contrast_ratio(table["--border"], table[ground])
                assert ratio >= 3.0, (
                    f"{mode} --rule-section on {ground} = {ratio:.4f}:1, under "
                    f"SC 1.4.11. This rung carries every structural boundary "
                    f"in the product; it has no exemption to fall back on."
                )

    def test_no_tinted_rung_is_claimed_to_clear_the_bar(self) -> None:
        """The honest half, and the reason the tinted rungs are registered
        EXEMPT rather than gated.

        ``--border`` was solved by m6 to exactly 3.30:1 — it IS the floor — so
        every tint of it toward the ground lands under 3:1. This asserts that
        the *shipped* tints really are under the bar, which is what makes
        "declared decorative" the honest description of them rather than a
        label on a value that happens to pass. A tint that crept back over 3:1
        would mean the ladder had silently collapsed onto one weight.
        """
        from tests.test_ui_contrast import RULE_META, RULE_ROW, _resolve

        for mode, table in (("light", LIGHT), ("dark", DARK)):
            for label, spec in (("--rule-row", RULE_ROW), ("--rule-meta", RULE_META)):
                ratio = contrast_ratio(_resolve(spec, mode), table["--bg"])
                assert ratio < 3.0, (
                    f"{mode} {label} on --bg = {ratio:.4f}:1, at or over SC "
                    f"1.4.11's bar. If a tinted rung now clears 3:1 it is no "
                    f"longer decorative and should be gated, not exempted — "
                    f"or the ladder has collapsed onto a single weight."
                )

    def test_every_tinted_rung_is_registered_exempt_with_a_reason(self) -> None:
        """``test_rendered_pair_meets_wcag_floor`` already refuses an EXEMPT
        row without a justification. This is the other direction: it refuses
        a tinted rung that was never registered AT ALL, which is how a
        sub-3:1 boundary ships without anyone deciding it should."""
        from tests.test_ui_contrast import EXEMPT, PAIRS

        for label in ("--rule-row", "--rule-meta"):
            rows = [p for p in PAIRS if label in p[1]]
            assert rows, f"{label} renders but is registered nowhere"
            for mode, site, _fg, _bg, floor in rows:
                assert floor == EXEMPT and "[EXEMPT:" in site, (
                    f"{mode} / {site}: a tinted rung must be registered with "
                    f"the EXEMPT sentinel AND an inline justification."
                )
            assert {p[0] for p in rows} == {"light", "dark"}, (
                f"{label} is registered in only one mode"
            )


# ---------------------------------------------------------------------------
# AC#2 — --card-bg's successor role
# ---------------------------------------------------------------------------
class TestCardBgSuccessorRole:
    #: Every rule-level ``var(--card-bg)`` consumer, with the role that keeps
    #: it. The AC's own count ("three dark-mode rules") is wrong twice over:
    #: there are three CSS rules of which only ONE is dark-only, plus three
    #: dark TOKEN derivations that name it as their solved ground.
    EXPECTED_CONSUMERS = {
        "th": "control ground — table header fill, both modes",
        "input": "control ground — dark input/textarea fill",
        "tbody tr:hover": "control ground — the interaction-target tint",
    }

    def test_card_bg_is_no_longer_a_panel_ground(self) -> None:
        rules = _re.findall(r"([^{}]+)\{[^}]*var\(--card-bg\)", APP_CSS_NO_COMMENTS)
        assert rules, "--card-bg has no consumers left at all — AC#2 asks for "
        for selector in rules:
            leaf = selector.strip().splitlines()[-1].strip()
            assert any(key in leaf for key in self.EXPECTED_CONSUMERS), (
                f"`{leaf}` grounds on --card-bg but is not one of its "
                f"successor-role consumers {sorted(self.EXPECTED_CONSUMERS)}. "
                f"ui-uplift-m8 AC#2 re-roles this token from PANEL ground to "
                f"CONTROL ground; a new panel use re-opens the primitive under "
                f"another name."
            )

    def test_the_two_modes_agree_about_the_header_surface(self) -> None:
        """UPL-8 v0 shipped a light ``th`` literal and a dark redeclaration to
        hide it. m8 collapsed that to one token-tracked rule, so the light and
        dark stylesheets must not disagree about this surface again."""
        assert "#f0f0f0" not in APP_CSS_NO_COMMENTS, (
            "the hardcoded light th fill is back; it is what forced the dark "
            "redeclaration UPL-8 v1 added and ui-uplift-m8 removed."
        )


# ---------------------------------------------------------------------------
# D2 — the per-site <section> vs <div> decision
# ---------------------------------------------------------------------------
class TestSectioningElementDecision:
    """m8 decided the ELEMENT per site rather than keeping ``<section>`` by
    reflex. An unnamed ``<section>`` exposes no region landmark — it is
    semantically a ``<div>`` — so this moves no accessibility tree today; what
    it records is intent. The property worth guarding is the one that DOES
    carry navigation: every block still opens with its ``<h2>``.
    """

    #: (template, expected <section> count, expected COLUMN-0 block count)
    #:
    #: ui-uplift-m12 M4/M8: this said "top-level block count" and no longer
    #: measured one. After m12 the detail page has THREE top-level blocks —
    #: two <section>s and the <details> — while five of the seven blocks the
    #: ^<(section|div)> extractor finds are children of <details>, kept at
    #: column 0 on purpose (indenting them would drop five of the seven
    #: per-site records out of this guard's view). So the extractor measures
    #: blocks at COLUMN 0, and the tuple is honestly unchanged at (2, 7)
    #: because no element decision changed.
    #:
    #: The coupling to source indentation is therefore real and load-bearing,
    #: and DECIDED's comment said so while this one did not. It is pinned
    #: from the other side by
    #: test_ui_m12_corpus_before_machinery.py::TestManageDisclosureNesting
    #: ::test_the_mutation_divs_stay_at_column_zero — so an agent or
    #: formatter that indents them fails THERE, with the right cause named,
    #: rather than failing here with a message about a structure that does
    #: not exist.
    EXPECTED = {"index.html": (1, 2), "notebook_detail.html": (2, 7)}

    #: m8 rectify (M8): the ORDERED element of each column-0 block, per
    #: template. The count-only version of this guard passed after swapping
    #: both index.html sites — the overlay critic proved it by mutation — so
    #: it asserted nothing about the per-site decisions its own failure
    #: message claimed to protect. A decision recorded as a total is not a
    #: recorded decision.
    #: Transcribed from implement/synthesis.md's D2 table, in its site order:
    #:   1 create-notebook div · 2 existing-notebooks section
    #:   3 record section · 4 topic div · 5 discover div · 6 add-paper div
    #:   7 upload div · 8 ingest div · 9 papers section
    #: Read from the RECORD, not from the templates — deriving it from the
    #: markup would make this guard circular, asserting only that the file
    #: equals itself.
    #:
    #: ui-uplift-m12 (UPL-1) — a RE-DECISION of notebook_detail.html's order,
    #: not a re-sort to match whatever the template now emits. m12 changed the
    #: ORDER of the seven blocks and changed NOTHING about which element each
    #: site takes: every one of m8's per-site judgements stands. The new site
    #: order, transcribed from m12's implement/synthesis.md with the reason
    #: each block sits where it does:
    #:   1 record    SECTION — identity leads. It is what the URL names, and
    #:                         it KEEPS form.rename-form: m12 reads AC#1 as
    #:                         "no MUTATION form above the table" and renaming
    #:                         edits the record's label, not the corpus. That
    #:                         narrowing is recorded in the template too.
    #:   2 papers    SECTION — the corpus, promoted from LAST to second. It is
    #:                         the reason the page gets opened; leaving it
    #:                         under six input forms is BAN-5 / BAN-R1 and was
    #:                         the run's only CRITICAL visual finding.
    #:   3 topic     DIV     — the five mutation blocks, unchanged in element
    #:   4 discover  DIV       and in relative order (the authored sequence
    #:   5 add-paper DIV       Topic -> Discover -> Add-by-URL -> Upload ->
    #:   6 upload    DIV       Ingest), now nested inside
    #:   7 ingest    DIV       <details class="manage-disclosure">.
    #: The five DIVs deliberately stay at column 0: indenting them would drop
    #: five of the seven per-site records out of this guard's ^<(section|div)>
    #: view, and a decision recorded as a total is not a recorded decision
    #: (m8 rectify M8, above). That they are INSIDE the disclosure is pinned
    #: separately by tests/test_ui_m12_corpus_before_machinery.py, which is
    #: also the guard indentation would only ever have asserted by accident.
    DECIDED: dict[str, list[str]] = {
        "index.html": ["div", "section"],
        "notebook_detail.html": [
            "section", "section", "div", "div", "div", "div", "div",
        ],
    }

    @staticmethod
    def _blocks(name: str) -> list[str]:
        markup = _re.sub(
            r"\{#.*?#\}", "", (_TEMPLATES / name).read_text(encoding="utf-8"),
            flags=_re.S,
        )
        return [m.group(1) for m in
                _re.finditer(r"^<(section|div)>", markup, flags=_re.M)]

    @pytest.mark.parametrize(("name", "counts"), sorted(EXPECTED.items()))
    def test_block_element_split_is_as_decided(
        self, name: str, counts: tuple[int, int]
    ) -> None:
        want_sections, want_blocks = counts
        blocks = self._blocks(name)
        sections = blocks.count("section")
        assert (sections, len(blocks)) == (want_sections, want_blocks), (
            f"{name}: {sections} <section> of {len(blocks)} column-0 blocks; "
            f"expected {want_sections} of {want_blocks}."
        )

    @pytest.mark.parametrize("name", sorted(EXPECTED))
    def test_each_block_keeps_the_element_it_was_decided_to_have(
        self, name: str
    ) -> None:
        """m8 rectify (M8): the per-SITE assertion, in document order.

        This is what the milestone actually decided — nine individual calls
        about whether a block is a landmark a reader would jump to, or only a
        visual grouping. Swapping any two of them is a different decision and
        must fail here, which the count-only guard let through.
        """
        assert self._blocks(name) == self.DECIDED[name], (
            f"{name}: column-0 blocks are {self._blocks(name)}, decided "
            f"{self.DECIDED[name]}. The split is a recorded per-site "
            f"judgement (implement/synthesis.md); swapping two blocks is a "
            f"re-decision, not a refactor."
        )

    @pytest.mark.parametrize("name", sorted(EXPECTED))
    def test_every_block_still_opens_with_its_heading(self, name: str) -> None:
        """The document outline is carried by heading rank, not by sectioning
        elements — the HTML5 outline algorithm was never implemented in any
        browser. So this, not the element choice, is what a screen-reader user
        navigates by, and it must survive the swap intact."""
        markup = _re.sub(
            r"\{#.*?#\}", "", (_TEMPLATES / name).read_text(encoding="utf-8"),
            flags=_re.S,
        )
        blocks = _re.findall(r"^<(?:section|div)>\s*\n\s*(<[^>\s]+)",
                             markup, flags=_re.M)
        want = self.EXPECTED[name][1]
        assert len(blocks) == want, (
            f"{name}: {len(blocks)} of {want} column-0 blocks open with an "
            f"element on the next line"
        )
        for opener in blocks:
            assert opener == "<h2", (
                f"{name}: a column-0 block opens with {opener!r}, not <h2>. "
                f"With the visual box gone the heading is ALL that delimits "
                f"the group for an AT user."
            )

    def test_no_block_was_promoted_to_a_landmark(self) -> None:
        """Deliberately NOT done. Naming these sections would mint seven or
        nine ``region`` landmarks on one page, and over-populating a page with
        landmarks reduces their ability to help users find the important
        parts. Heading hierarchy is the recommended answer and is what ships.
        """
        for path in TEMPLATE_PATHS:
            markup = _re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"),
                             flags=_re.S)
            for m in _re.finditer(r"<section\b[^>]*>", markup):
                assert "aria-label" not in m.group(0), (
                    f"{path.name}: {m.group(0)} names a section, promoting it "
                    f"to a region landmark. ui-uplift-m8 refused this on "
                    f"purpose — see implement/synthesis.md."
                )


class TestExemptionIsConditionalPerSite:
    """m8 rectify (M1). The owner granted the tinted rungs SC 1.4.11's
    decorative carve-out on ONE condition: they are exempt only where
    something ELSE carries the grouping. All three critics audited that by
    inspection and it held — but nothing in the repo pinned it, so the next
    milestone could add a fourth tinted-rung site with no second cue and no
    test would notice.

    The carve-out covers a boundary "that does not require the user to see or
    understand it to understand the content". This asserts the structural
    invariant that makes that true here: a tinted rung never appears on a
    selector that is the ONLY separator between two groups — operationally,
    every tinted-rung rule must also carry spacing, or sit inside a table or
    definition list whose own semantics group the rows.

    **REWRITTEN 2026-08-05 after an external review found it proved nothing
    it claimed.** The previous version stored a free-text sentence per site
    and had four independent holes, each of which the review demonstrated:

    1. ``if m is None: continue`` — a selector NOT in the stylesheet was
       silently skipped, so an invented site with an invented cue passed.
    2. The cue string was interpolated into failure messages and asserted
       against nothing. It was documentation wearing a test's clothes.
    3. ``semantic = any(x in selector for x in ("dl.meta", "tbody"))`` —
       a substring test on the SELECTOR TEXT was treated as proof that the
       rendered element sits inside a grouping structure.
    4. ``"padding" in body or "margin" in body`` — satisfied by
       ``padding: 0``. The review confirmed ``.discover-candidate`` still
       passed after its spacing was reduced to zero.

    Each cue is now a CHECKABLE KIND rather than a sentence, and each kind
    has a test that can actually fail: spacing is parsed and required to be
    positive, and the structural kinds are proved against the shipped markup
    by walking an element ancestry, not by matching a substring of the CSS.
    """

    #: Cue kinds. A tinted rung is decorative — and so SC 1.4.11 exempt —
    #: only where one of these independently carries the grouping.
    SPACING = "spacing"      #: the rule itself declares POSITIVE spacing
    TABLE = "table"          #: the marked cells sit inside a <table>
    DEF_LIST = "dl"          #: the marked terms sit inside a <dl>
    DEGENERATE = "degenerate"  #: there is no second group to separate from

    CUE_KINDS = frozenset({SPACING, TABLE, DEF_LIST, DEGENERATE})

    #: selector -> (cue kind, why this site qualifies). The NOTE is prose for
    #: a reader; the KIND is what the tests below enforce. Adding a site
    #: without a kind fails; adding one whose kind does not hold fails.
    TINTED_SITES: dict[str, tuple[str, str]] = {
        "dl.meta dt, dl.meta dd": (
            DEF_LIST, "<dl> pairs are grouped by dt/dd semantics"),
        "tbody td": (
            TABLE, "<table> rows are grouped by the table itself"),
        ".discover-candidate": (
            SPACING, "each candidate carries its own padding rhythm"),
        "main > :where(section, div) + div": (
            SPACING, "1.25rem margin + padding"),
        # Added by m8's own rectify (M16) and caught by this guard on its
        # first run — which is the guard doing its job. The cue here is
        # degenerate and therefore the strongest: with an empty tbody there
        # is no second group to separate from, so nothing depends on the
        # rule to perceive a grouping that does not exist.
        "table:has(tbody:empty) thead th": (
            DEGENERATE, "no rows below it to separate from"),
        # ui-uplift-m12 (UPL-1). The nested continuation of the row rung: the
        # five mutation blocks left main's child list when they moved inside
        # <details class="manage-disclosure">, so `main >` stopped reaching
        # them. Same blocks, same rung, one level down.
        ".manage-disclosure > div + div": (
            SPACING, "1.25rem margin + padding, each block opening with its <h2>"),
    }

    @staticmethod
    def _tinted_selectors_in_css() -> list[str]:
        """Every selector whose rule body paints a tinted rung."""
        return [
            " ".join(sel.split())
            for sel in _re.findall(
                r"([^{}]+)\{[^{}]*var\(--rule-(?:row|meta)\)",
                APP_CSS_NO_COMMENTS,
            )
        ]

    @staticmethod
    def _rule_body(selector: str) -> str | None:
        """The declaration block for an EXACT selector, or None."""
        m = _re.search(
            rf"(?:^|\}})\s*{_re.escape(selector)}\s*\{{([^}}]*)\}}",
            APP_CSS_NO_COMMENTS, flags=_re.M,
        )
        return m.group(1) if m else None

    def test_cue_kinds_are_from_the_closed_set(self) -> None:
        """Hole 2's replacement has to be a closed vocabulary, or it decays
        back into free text that nothing enforces."""
        assert self.TINTED_SITES, "vacuous: no tinted sites enumerated"
        for selector, (kind, note) in self.TINTED_SITES.items():
            assert kind in self.CUE_KINDS, (
                f"`{selector}` claims cue kind {kind!r}, which no test can "
                f"check. Use one of {sorted(self.CUE_KINDS)}."
            )
            assert note.strip(), f"`{selector}` has an empty note"

    def test_every_enumerated_selector_exists_verbatim_in_app_css(self) -> None:
        """Hole 1. The old guard skipped a selector it could not find, so a
        site that does not exist — with any cue at all — passed."""
        for selector in self.TINTED_SITES:
            assert self._rule_body(selector) is not None, (
                f"TINTED_SITES enumerates `{selector}`, which is not a "
                f"selector in app.css. An entry that matches nothing used to "
                f"be skipped silently; it is now a failure, because a guard "
                f"that cannot find its subject proves nothing about it."
            )

    def test_every_enumerated_selector_actually_paints_a_tinted_rung(
        self,
    ) -> None:
        """The dict is the exemption REGISTRY. An entry whose rule draws no
        tinted rung is claiming an exemption for something that needs none —
        which is how a stale entry would keep covering a site that changed."""
        tinted = set(self._tinted_selectors_in_css())
        for selector in self.TINTED_SITES:
            assert selector in tinted, (
                f"`{selector}` is registered as an SC 1.4.11 exemption but "
                f"its rule no longer references var(--rule-row) or "
                f"var(--rule-meta). Remove the entry."
            )

    def test_every_tinted_rung_site_is_enumerated(self) -> None:
        """Coverage, the other direction — now by EXACT selector.

        The old form was ``any(k in sel for k in TINTED_SITES)``, so a new
        selector merely CONTAINING an enumerated one inherited its exemption
        without ever being reviewed.
        """
        registered = set(self.TINTED_SITES)
        for sel in self._tinted_selectors_in_css():
            assert sel in registered, (
                f"`{sel}` uses a tinted rung but is not enumerated in "
                f"TINTED_SITES with the cue kind that earns its SC 1.4.11 "
                f"exemption. A tinted rung measures 2.533:1 (row) or 1.960:1 "
                f"(meta); it is decorative ONLY where something else carries "
                f"the grouping. Add the site and its kind, or use "
                f"--rule-section."
            )

    def test_spacing_cues_declare_POSITIVE_spacing(self) -> None:
        """Hole 4. ``padding: 0`` satisfied the old substring check, which
        means a site could claim a spacing cue while providing no spacing.
        The review reduced ``.discover-candidate`` to ``padding: 0`` and the
        guard still passed.
        """
        spacing_sites = [
            s for s, (kind, _n) in self.TINTED_SITES.items()
            if kind == self.SPACING
        ]
        assert spacing_sites, "vacuous: no site claims the spacing cue"
        for selector in spacing_sites:
            body = self._rule_body(selector)
            assert body is not None
            lengths = _re.findall(
                r"(?:padding|margin)(?:-[a-z-]+)?\s*:\s*([^;]+)", body
            )
            assert lengths, (
                f"`{selector}` claims a spacing cue and declares no "
                f"padding or margin at all"
            )
            values = [
                float(n)
                for decl in lengths
                for n in _re.findall(r"(-?\d*\.?\d+)(?=r?em|px|%|ch|vh|vw)", decl)
            ]
            assert values, (
                f"`{selector}` declares padding/margin with no length value "
                f"({lengths!r}) — `auto` and keywords do not separate groups"
            )
            assert any(v > 0 for v in values), (
                f"`{selector}` claims a spacing cue but every declared length "
                f"is {values!r}. Zero spacing means the tinted rule IS the "
                f"only separator, and the decorative exemption does not hold."
            )

    def test_structural_cues_hold_in_the_SHIPPED_MARKUP(self) -> None:
        """Hole 3. ``"tbody" in selector`` was treated as proof that the
        marked element sits inside a table. It is proof of nothing — it is a
        substring of a CSS string. This walks the element ancestry of the
        shipped templates instead, so the claim is checked against the
        structure that actually renders.
        """
        #: kind -> (elements that only exist inside the structure, the
        #: grouping ancestor they must have).
        required = {
            self.TABLE: ({"td", "th", "tr", "tbody", "thead"}, "table"),
            self.DEF_LIST: ({"dt", "dd"}, "dl"),
        }
        structural = [
            (s, kind) for s, (kind, _n) in self.TINTED_SITES.items()
            if kind in required
        ]
        assert structural, "vacuous: no site claims a structural cue"
        for selector, kind in structural:
            allowed, ancestor = required[kind]
            subjects = _selector_subjects(selector)

            # (a) The selector must actually TARGET the structure it invokes.
            # Without this the check passes vacuously: any selector at all
            # could claim TABLE and be validated against unrelated <td>s
            # elsewhere in the templates.
            assert subjects <= allowed and "" not in subjects, (
                f"`{selector}` claims its grouping comes from <{ancestor}>, "
                f"but it targets {sorted(subjects)!r} — not one of "
                f"{sorted(allowed)!r}. A selector that does not target the "
                f"structure cannot inherit that structure's grouping."
            )

            # (b) And that structure must really wrap it where it renders.
            for subject in sorted(subjects):
                chains = _element_ancestries(subject)
                assert chains, (
                    f"`{selector}` claims grouping from <{ancestor}>, but no "
                    f"<{subject}> is emitted by any shipped template — the "
                    f"claim is untestable and the exemption unearned."
                )
                for chain in chains:
                    assert ancestor in chain, (
                        f"`{selector}` claims <{ancestor}> semantics carry "
                        f"the grouping, but a <{subject}> renders at "
                        f"{chain!r} with no <{ancestor}> ancestor. There, "
                        f"the tinted rule is the only separator."
                    )

    def test_the_degenerate_cue_really_targets_an_empty_group(self) -> None:
        """The degenerate cue says "there is no second group to separate
        from". That is only true if the selector itself is conditioned on
        emptiness — otherwise it is the strongest-sounding claim in the
        registry with nothing behind it."""
        for selector, (kind, _n) in self.TINTED_SITES.items():
            if kind != self.DEGENERATE:
                continue
            assert ":empty" in selector, (
                f"`{selector}` claims the degenerate cue but is not "
                f"conditioned on an empty group; it applies with rows "
                f"present, where the rung IS a separator."
            )
