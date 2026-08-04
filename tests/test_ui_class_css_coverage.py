"""BAN-R2 — every server-emitted CSS class has a matching app.css rule.

Derived test for ``ui-uplift-m9`` (``plans/ui-uplift/roadmap.yaml``, epic
``ui-uplift-e2`` / tag ``BAN-R2``). Three acceptance criteria:

1. Any class literal emitted by a fragment builder in ``server/routes/``
   must have a matching selector in ``app.css``, or this test fails.
2. The dynamic status-badge modifier family is handled by an explicit
   allow-list, not a false failure.
3. A new fragment added later with no CSS rule fails the suite — the
   policy binds forward, not just retroactively.

Design (research-synthesis.md; both Phase-1 briefs agreed):

- **AST-scoped extraction, not a raw regex over file bytes.** A regex over
  ``notebooks.py`` would treat the docstring prose in ``_paper_row_html``
  (~line 1981, describing a rendered ``<span class="hint">``) as a 3rd
  "hint" emission. This module excludes real docstrings (the same
  first-statement discriminator :func:`ast.get_docstring` uses),
  reconstructs each remaining literal's text — adjacent string/f-string
  literals fold into ONE ``ast.JoinedStr``/``ast.Constant`` node at parse
  time, verified empirically — then regexes for ``class="..."`` within it.
- **Word-bounded CSS token search, not a selector parser.** ``app.css``
  has no bare ``.foo { }`` rules, so this matches ``.classname`` anywhere
  in the comment-stripped text, guarded on the right only (``.error``
  must not match inside ``.error-detail``; no left-side guard needed —
  CSS classes can't start with a digit).
- **Two structurally separate lists.** ``_DYNAMIC_MODIFIER_ALLOWLIST``
  (AC2) is permanent: ``class="status-badge status-badge--{css}"``
  (``ui.py:289``) is structurally unresolvable to a literal, so its 4 real
  values are pinned explicitly — never a wildcard on the prefix, which
  would let a future unstyled 5th value pass silently. A hypothetical 5th
  ``_classify_status_badge`` value with no matching allow-list edit is
  thus invisible to ANY static check — an inherent limit, not a bug.
  ``_KNOWN_UNSTYLED`` is a DATED DEBT DEFERRAL, not an exemption: 9
  classes ship today with zero CSS and ``app.css`` is at its 400-line
  soft cap, so styling them is out of scope here. Unlike a
  hand-maintained list it cannot rot silently:
  :class:`TestKnownUnstyledDebtIsSelfCleaning` fails the day an entry
  gains a rule.

Templates are out of scope (AC1 and the epic's own ``links.code`` both
name only ``server/routes/``): Jinja2-only classes like
``notebook_detail.html``'s ``rename-form`` are a deliberate scope line.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from server.routes.ui import _classify_status_badge

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
ROUTES_DIR: Path = REPO_ROOT / "server" / "routes"
STATIC_DIR: Path = REPO_ROOT / "server" / "frontend" / "static"

#: Negative lookbehind excludes a longer attribute name ending in "class"
#: (e.g. a hypothetical ``data-class="..."``) from matching.
_CLASS_ATTR_RE: re.Pattern[str] = re.compile(r'(?<![\w-])class="([^"]*)"')
_CSS_COMMENT_RE: re.Pattern[str] = re.compile(r"/\*.*?\*/", re.S)

#: Cannot appear in real Python/HTML/CSS source; substituted for every
#: ``{expr}`` interpolation when reconstructing an f-string's literal
#: text, so a dynamic segment is structurally distinguishable from static
#: text.
_DYNAMIC_MARKER: str = "\x00"

#: AC2 — the ONE dynamic class-token family in server/routes/:
#: ``class="status-badge status-badge--{css}"`` (``ui.py:289``). ``css``
#: is ``_classify_status_badge``'s 2nd return value; a static scan cannot
#: resolve the interpolation, so this is an explicit CLOSED allow-list —
#: never a bare prefix/wildcard (see module docstring for why).
_DYNAMIC_MODIFIER_ALLOWLIST: dict[str, frozenset[str]] = {
    "status-badge--": frozenset({"ok", "warn", "down", "ops-warn"}),
}

#: Dated debt deferral (2026-08-04) — NOT a policy exemption. These 9
#: classes are emitted today with zero CSS; landing that CSS is out of
#: ui-uplift-m9's scope (app.css is at its 400-line soft cap) and would
#: poach ui-uplift-m10's own discover-* scope. Self-checked below: this
#: list can only shrink (TestKnownUnstyledDebtIsSelfCleaning).
_KNOWN_UNSTYLED: dict[str, str] = {
    "status-badge__remediation": "ui.py:336 — unowned; no milestone scoped to style it",
    "topic-block": "notebooks.py:621 — unowned; no milestone scoped to style topic-*",
    "topic-category": "notebooks.py:622 — unowned; see topic-block",
    "topic-description": "notebooks.py:623 — unowned; see topic-block",
    "discover-candidate": "notebooks.py:731 — owned by ui-uplift-m10 (UPL-9)",
    "discover-title": "notebooks.py:732 — owned by ui-uplift-m10; see discover-candidate",
    "discover-meta": "notebooks.py:733 — owned by ui-uplift-m10; see discover-candidate",
    "discover-abstract": "notebooks.py:735 — owned by ui-uplift-m10; see discover-candidate",
    "discover-list": "notebooks.py:748 — owned by ui-uplift-m10; see discover-candidate",
}


@dataclass(frozen=True)
class EmittedClass:
    """One ``class="..."`` token from a real (non-docstring) literal.

    ``lineno`` is the AST node's start line — for a token inside a
    multi-line concatenated fragment (adjacent literals fold into one
    node), this is the fragment's start, not necessarily the token's own
    physical line. Close enough to locate the function; not a claim of
    per-token precision.
    """

    file: str
    lineno: int
    token: str
    is_dynamic: bool
    dynamic_prefix: str | None


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """``id()``s of every ``Constant`` node that IS a docstring.

    Mirrors :func:`ast.get_docstring`'s own discriminator (first
    statement of a def/class/module body, as a bare ``Expr(Constant)``).
    An f-string can never BE a docstring, so only ``Constant`` matters.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _joined_str_text(node: ast.JoinedStr) -> str:
    """Reconstruct an f-string's literal text; ``_DYNAMIC_MARKER`` stands
    in for every ``{expr}`` interpolation."""
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
        else:  # ast.FormattedValue — the {expr} itself; opaque to statics.
            parts.append(_DYNAMIC_MARKER)
    return "".join(parts)


def _class_tokens_from_text(text: str) -> list[str]:
    """Every whitespace-separated token inside every ``class="..."`` in
    ``text``."""
    tokens: list[str] = []
    for match in _CLASS_ATTR_RE.finditer(text):
        tokens.extend(match.group(1).split())
    return tokens


class _EmissionVisitor(ast.NodeVisitor):
    """Collects :class:`EmittedClass` records, name-agnostic across every
    string/f-string literal in the module (AC3 — no hand-maintained list
    of "known fragment-builder function names" to keep in sync).

    ``visit_JoinedStr`` deliberately skips ``generic_visit``: its own
    ``Constant``/``FormattedValue`` children would otherwise be re-visited
    as spurious extra top-level candidates (confirmed empirically),
    double-counting fragments of an already-reconstructed literal.
    """

    def __init__(self, relpath: str, docstring_ids: set[int]) -> None:
        self.relpath = relpath
        self._docstring_ids = docstring_ids
        self.emissions: list[EmittedClass] = []

    def _record(self, lineno: int, text: str) -> None:
        for token in _class_tokens_from_text(text):
            if _DYNAMIC_MARKER in token:
                prefix = token.split(_DYNAMIC_MARKER, 1)[0]
                self.emissions.append(
                    EmittedClass(self.relpath, lineno, token, True, prefix)
                )
            else:
                self.emissions.append(
                    EmittedClass(self.relpath, lineno, token, False, None)
                )

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self._record(node.lineno, _joined_str_text(node))

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self._docstring_ids:
            self._record(node.lineno, node.value)


def _extract_emissions_from_source(source: str, relpath: str) -> list[EmittedClass]:
    """Parse ``source`` text (not a path) and return every emission found.

    Text, not a path, so :class:`TestPolicyBindsForwardAC3` can run this
    SAME machinery against a synthetic snippet — proving AC3 without
    adding real dead code to ``server/routes/``.
    """
    tree = ast.parse(source)
    docstring_ids = _docstring_constant_ids(tree)
    visitor = _EmissionVisitor(relpath, docstring_ids)
    visitor.visit(tree)
    return visitor.emissions


def _route_files() -> list[Path]:
    """Every ``.py`` file directly under ``server/routes/`` — a GLOB, not
    a hand-listed pair, so a fifth route module is picked up with no
    test-file edit required (AC3)."""
    return sorted(ROUTES_DIR.glob("*.py"))


def _all_emissions() -> list[EmittedClass]:
    emissions: list[EmittedClass] = []
    for path in _route_files():
        relpath = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        emissions.extend(_extract_emissions_from_source(source, relpath))
    return emissions


def _css_files() -> list[Path]:
    """Every ``.css`` file under ``server/frontend/static/`` — globbed,
    not hardcoded to ``app.css``, so the ``tokens.css`` split the app.css
    line-cap tests already name as an escape hatch doesn't silently drop
    out of coverage the day it happens."""
    return sorted(STATIC_DIR.glob("*.css"))


def _combined_css_text_no_comments() -> str:
    chunks = [
        _CSS_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))
        for path in _css_files()
    ]
    return "\n".join(chunks)


def _css_defines_class(classname: str, css_text_no_comments: str) -> bool:
    """Word-bounded ``.classname`` match anywhere in
    ``css_text_no_comments``.

    ``app.css`` has no bare ``.foo { }`` rules — every selector is
    compound (``.card .hint``), element+class (``pre.error``),
    comma-grouped (``button, .button``), pseudo-suffixed, or ``@media``
    -nested — so this matches ``.classname`` as a token ANYWHERE in the
    text, guarded only on the right (``.error`` must not match inside
    ``.error-detail``; CSS classes can't start with a digit, so there is
    no left-side ambiguity with e.g. ``0.4rem``).

    Accepted, inert-today limitation: scanning full declaration text (not
    just selector position) means a future ``url(icon.svg)`` or a
    dot-bearing ``content: ".foo"`` value could inflate the "defined"
    set — false-negative-only, so it can only mask a gap, never invent a
    failure.
    """
    pattern = re.compile(r"\." + re.escape(classname) + r"(?![\w-])")
    return pattern.search(css_text_no_comments) is not None


def _offenders(
    emissions: list[EmittedClass],
    css_text: str,
    known_unstyled: dict[str, str] | None = None,
    allowlist: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """AC1 + AC2 in one shared pass — reused by the real-repo test AND the
    synthetic AC3 proof, so "a new offender is caught" runs the real
    function, not a reimplementation that could drift from it.
    """
    known_unstyled = known_unstyled or {}
    allowlist = allowlist or {}
    offenders: list[str] = []
    for e in emissions:
        if e.is_dynamic:
            suffixes = allowlist.get(e.dynamic_prefix or "")
            if suffixes is None:
                offenders.append(
                    f"{e.file}:{e.lineno} — dynamic class prefix "
                    f"{e.dynamic_prefix!r} has no _DYNAMIC_MODIFIER_ALLOWLIST "
                    "entry. Add one, or make the class literal static."
                )
                continue
            for suffix in suffixes:
                concrete = f"{e.dynamic_prefix}{suffix}"
                if not _css_defines_class(concrete, css_text):
                    offenders.append(
                        f"{e.file}:{e.lineno} — allow-listed dynamic class "
                        f"{concrete!r} (prefix {e.dynamic_prefix!r} + suffix "
                        f"{suffix!r}) has no selector in app.css. Add a "
                        f"`.{concrete}` rule to server/frontend/static/app.css."
                    )
            continue
        if e.token in known_unstyled:
            continue
        if not _css_defines_class(e.token, css_text):
            offenders.append(
                f"{e.file}:{e.lineno} — class {e.token!r} has no selector "
                f"in app.css. Add a `.{e.token}` rule to "
                "server/frontend/static/app.css, or (if genuinely dynamic "
                "or a reasoned, dated deferral) add it to "
                "_DYNAMIC_MODIFIER_ALLOWLIST or _KNOWN_UNSTYLED with a "
                "reason."
            )
    return offenders


# ---------------------------------------------------------------------------
# AC1 + AC3 — extraction correctness ("guard the guard")
# ---------------------------------------------------------------------------


class TestExtractionFindsKnownSites:
    """Guard the guard — mirrors ``test_assert_ban.py``'s
    ``test_shipped_trees_are_actually_scanned``: a broken glob/extractor
    must not make every other assertion below vacuously true."""

    def test_route_glob_finds_the_known_route_modules(self) -> None:
        names = {p.name for p in _route_files()}
        expected = {"notebooks.py", "ui.py", "debug.py", "__init__.py"}
        assert expected <= names, (
            f"expected the known route modules among the glob results; "
            f"found {sorted(names)}"
        )

    def test_scan_finds_at_least_the_16_known_emission_sites(self) -> None:
        emissions = _all_emissions()
        assert len(emissions) >= 16, (
            f"expected >= 16 class-literal emissions across server/routes/"
            f"*.py (research counted 16 known sites); found "
            f"{len(emissions)} — the extractor or the route glob is "
            "probably broken"
        )

    def test_docstring_prose_is_not_treated_as_an_emission(self) -> None:
        """notebooks.py's ``_paper_row_html`` docstring contains a literal
        ``class="hint"`` substring as prose, not an emission — a live
        false positive both Phase-1 research briefs flagged. Assert on
        COUNT + span non-overlap, not a hardcoded line number, so an
        unrelated reformat can't fail this for the wrong reason.
        """
        path = ROUTES_DIR / "notebooks.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        docstring_ids = _docstring_constant_ids(tree)
        docstring_span: tuple[int, int] | None = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and id(node) in docstring_ids
                and isinstance(node.value, str)
                and 'class="hint"' in node.value
            ):
                docstring_span = (node.lineno, node.end_lineno or node.lineno)
                break
        assert docstring_span is not None, (
            'expected to find the known class="hint"-in-a-docstring case '
            "in notebooks.py; if that docstring changed, this regression "
            "guard needs updating"
        )
        hint_emissions = [
            e
            for e in _extract_emissions_from_source(
                source, "server/routes/notebooks.py"
            )
            if e.token == "hint"
        ]
        assert len(hint_emissions) == 2, (
            f"expected exactly the 2 real 'hint' emission sites; found "
            f"{len(hint_emissions)}: {hint_emissions} — the docstring at "
            f"notebooks.py:{docstring_span[0]} may be leaking into the scan"
        )
        for e in hint_emissions:
            assert not (docstring_span[0] <= e.lineno <= docstring_span[1]), (
                f"emission at {e.file}:{e.lineno} falls inside the "
                f"docstring span {docstring_span} — docstring exclusion "
                "is broken"
            )


# ---------------------------------------------------------------------------
# AC1 — every emitted class has a rule (or a reasoned, tracked exemption)
# ---------------------------------------------------------------------------


class TestEveryEmittedClassHasARuleOrExemption:
    """AC1 — the main derived check."""

    def test_every_emitted_class_has_a_rule_or_reasoned_exemption(self) -> None:
        css_text = _combined_css_text_no_comments()
        offenders = _offenders(
            _all_emissions(),
            css_text,
            known_unstyled=_KNOWN_UNSTYLED,
            allowlist=_DYNAMIC_MODIFIER_ALLOWLIST,
        )
        assert not offenders, (
            "BAN-R2: every class emitted from server/routes/ must have a "
            f"matching app.css selector. {len(offenders)} offender(s):\n  "
            + "\n  ".join(offenders)
        )


# ---------------------------------------------------------------------------
# AC2 — the dynamic status-badge modifier family
# ---------------------------------------------------------------------------


class TestDynamicStatusBadgeAllowlist:
    def test_scan_finds_exactly_one_dynamic_family(self) -> None:
        prefixes = {e.dynamic_prefix for e in _all_emissions() if e.is_dynamic}
        assert prefixes == {"status-badge--"}, (
            f"expected exactly one dynamic class-token family "
            f"('status-badge--'); found {sorted(prefixes)} — a NEW dynamic "
            "family needs its own _DYNAMIC_MODIFIER_ALLOWLIST entry"
        )

    def test_every_allowlisted_suffix_has_a_concrete_css_rule(self) -> None:
        css_text = _combined_css_text_no_comments()
        offenders = [
            f"{prefix}{suffix}"
            for prefix, suffixes in _DYNAMIC_MODIFIER_ALLOWLIST.items()
            for suffix in suffixes
            if not _css_defines_class(f"{prefix}{suffix}", css_text)
        ]
        assert not offenders, (
            f"allow-listed dynamic classes with no CSS rule: {offenders}"
        )

    def test_allowlist_matches_classify_status_badge_return_values(self) -> None:
        """Pin the allow-list to its real source of truth (narrows, but
        per the module docstring cannot fully close, the inherent gap: a
        future 5th return value is invisible to a static f-string scan).
        """
        css_values = {
            _classify_status_badge({"status": "fail"})[1],
            _classify_status_badge({"status": "pass"})[1],
            _classify_status_badge({"status": "warn", "checks": {}})[1],
            _classify_status_badge(
                {
                    "status": "warn",
                    "checks": {"lancedb:status": [{"status": "fail"}]},
                }
            )[1],
        }
        assert css_values == _DYNAMIC_MODIFIER_ALLOWLIST["status-badge--"]


# ---------------------------------------------------------------------------
# Debt-deferral list must shrink, never rot
# ---------------------------------------------------------------------------


class TestKnownUnstyledDebtIsSelfCleaning:
    """Separates ``_KNOWN_UNSTYLED`` from the hand-maintained list this
    milestone replaces: it cannot silently go stale in either direction.
    """

    def test_known_unstyled_entries_are_still_actually_unstyled(self) -> None:
        css_text = _combined_css_text_no_comments()
        now_styled = [c for c in _KNOWN_UNSTYLED if _css_defines_class(c, css_text)]
        assert not now_styled, (
            "the following _KNOWN_UNSTYLED entries now HAVE a CSS rule — "
            "delete them from _KNOWN_UNSTYLED (AC1 coverage re-activates "
            f"automatically once removed): {now_styled}"
        )


# ---------------------------------------------------------------------------
# AC3 — the policy binds forward, proven directly with synthetic source
# ---------------------------------------------------------------------------


class TestPolicyBindsForwardAC3:
    """Direct proof: run the REAL extraction + offender-detection
    machinery against a synthetic fragment never added to
    ``server/routes/`` — no need to ship real dead code to prove AC3.
    """

    def test_new_static_class_with_no_css_rule_is_caught(self) -> None:
        source = (
            "def _brand_new_fragment(x: str) -> str:\n"
            '    return f\'<div class="ui-uplift-m9-synthetic-probe">{x}</div>\'\n'
        )
        emissions = _extract_emissions_from_source(source, "synthetic.py")
        offenders = _offenders(emissions, _combined_css_text_no_comments())
        assert any("ui-uplift-m9-synthetic-probe" in o for o in offenders), (
            "a brand-new unstyled static class must be caught by the "
            f"derived check; offenders were: {offenders}"
        )

    def test_new_dynamic_family_with_no_allowlist_entry_is_caught(self) -> None:
        source = (
            "def _brand_new_dynamic_fragment(tag: str) -> str:\n"
            "    return f'<div class=\"totally-new-{tag}\">x</div>'\n"
        )
        emissions = _extract_emissions_from_source(source, "synthetic.py")
        offenders = _offenders(
            emissions,
            _combined_css_text_no_comments(),
            allowlist=_DYNAMIC_MODIFIER_ALLOWLIST,
        )
        assert any("totally-new-" in o for o in offenders), (
            "a brand-new dynamic class family with no allow-list entry "
            f"must be caught, not silently passed; offenders were: "
            f"{offenders}"
        )
        # Negative control (same test): the machinery doesn't just flag
        # everything synthetic — a new emission of an ALREADY-covered
        # class (the real `pre.error` rule) passes clean.
        clean_source = (
            "def _another_fragment() -> str:\n"
            "    return '<pre class=\"error\">boom</pre>'\n"
        )
        clean_emissions = _extract_emissions_from_source(clean_source, "s.py")
        assert _offenders(clean_emissions, _combined_css_text_no_comments()) == []
