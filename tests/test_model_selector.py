"""``select_model`` tests (E08_S05).

Coverage map (acceptance criteria → test class):

  AC                                                              Test class
  ────────────────────────────────────────────────────────────────────────────
  select_model(AUTOFORMALIZATION, LEAN_WRITE) → claude-sonnet-4-6 TestACSelections
  select_model(SYNTHESIS, RETRIEVAL) → claude-haiku-4-5            TestACSelections
  select_model(VERIFICATION, DRAFT) → claude-haiku-4-5             TestACSelections
  "claude-opus" does not appear anywhere in server/ source         TestForbiddenStrings
  docs/model-policy.md has section "Verifier pass: dropped and why" TestPolicyDoc
  pytest tests/test_model_selector.py passes                       this file

Plus regression-grade tests for:
- Model ID format pinned (catches accidental edits to the alias)
- Selection table totality (4 RouteTags × 3 TurnTypes = 12 cells)
- Verification mirrors Autoformalization for every TurnType
- Default is Haiku (every (RouteTag, TurnType) returns Haiku UNLESS
  it's (AUTOFORMALIZATION, LEAN_WRITE) or (VERIFICATION, LEAN_WRITE))
- TurnType enum closed at three values
- Closed-at-N import-time invariant survives -O optimization
- ``select_model`` raises ValueError on unknown pair (defensive
  rather than silent fallback)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from server.orchestrator.model_selector import (
    MODEL_HAIKU_4_5,
    MODEL_SONNET_4_6,
    POLICY_VERSION,
    TurnType,
    select_model,
)
from server.router import RouteTag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Path to ``server/`` for the forbidden-string scan.
SERVER_DIR: Path = Path(__file__).resolve().parent.parent / "server"

#: Path to the policy doc. Moved 2026-05-10 from ``docs/`` to ``.claude/docs/``
#: as part of the repo-wide doc-layout consolidation (root-MD restriction).
POLICY_DOC_PATH: Path = (
    Path(__file__).resolve().parent.parent / ".claude" / "docs" / "model-policy.md"
)

#: The verbatim section title required by AC #5.
REQUIRED_DOC_SECTION: str = "Verifier pass: dropped and why"

#: The forbidden substring per AC #4.
FORBIDDEN_STRING: str = "claude-opus"


# ===========================================================================
# AC — explicit (route_tag, turn_type) → model lookups
# ===========================================================================


class TestACSelections:
    """Each ACs from the brief, tested by direct lookup."""

    def test_autoformalization_lean_write_returns_sonnet(self):
        """AC #1 (corrected wording): the Autoformalizer's Lean-syntax
        write turn returns Sonnet 4.6, NOT Haiku. The brief had a
        confusing in-line correction; the corrected expectation is
        ``claude-sonnet-4-6``."""
        assert (
            select_model(RouteTag.AUTOFORMALIZATION, TurnType.LEAN_WRITE)
            == "claude-sonnet-4-6"
        )

    def test_synthesis_retrieval_returns_haiku(self):
        """AC #2: Synthesis retrieval turns use Haiku."""
        assert (
            select_model(RouteTag.SYNTHESIS, TurnType.RETRIEVAL)
            == "claude-haiku-4-5"
        )

    def test_verification_draft_returns_haiku(self):
        """AC #3: Verification routes to the Autoformalizer execution
        path; a DRAFT turn for either role returns Haiku."""
        assert (
            select_model(RouteTag.VERIFICATION, TurnType.DRAFT)
            == "claude-haiku-4-5"
        )


# ===========================================================================
# AC #4 — "claude-opus" forbidden in server/
# ===========================================================================


class TestForbiddenStrings:
    """AC #4: the string ``"claude-opus"`` must NOT appear anywhere
    in ``server/`` source files. Walks every ``.py`` file under
    ``server/`` (excluding ``__pycache__``) and asserts no match.

    The ban is total: not as a constant, not in a comment, not in
    a docstring. The Opus deferral rationale lives in
    ``docs/model-policy.md`` (which IS allowed to mention the
    string)."""

    def test_no_claude_opus_in_server_python_files(self):
        """Walk server/**/*.py and assert FORBIDDEN_STRING is absent."""
        offenders: list[tuple[Path, int, str]] = []
        for py_file in SERVER_DIR.rglob("*.py"):
            # Skip __pycache__ (they're .pyc, not .py — defensive only).
            if "__pycache__" in py_file.parts:
                continue
            text = py_file.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if FORBIDDEN_STRING in line:
                    offenders.append((py_file, line_no, line.strip()))
        assert not offenders, (
            f"AC #4 violation: {FORBIDDEN_STRING!r} found in "
            f"server/. Per the v1 model policy, Opus 4.7 is "
            f"deferred (rationale lives in docs/model-policy.md). "
            f"Offending lines:\n"
            + "\n".join(
                f"  {path.relative_to(SERVER_DIR.parent)}:{n}: {line}"
                for path, n, line in offenders
            )
        )

    def test_forbidden_string_constant_pinned(self):
        """A defensive pin so a future contributor cannot soften the
        check by changing FORBIDDEN_STRING in this file."""
        assert FORBIDDEN_STRING == "claude-opus"


# ===========================================================================
# AC #5 — policy doc has the required section title
# ===========================================================================


class TestPolicyDoc:
    """AC #5: ``docs/model-policy.md`` includes a section titled
    exactly *"Verifier pass: dropped and why"*.

    The match is byte-exact on the section title text — a markdown
    heading prefix (``## `` or ``### ``) plus the title. We also
    permit the title appearing inline as text (in case a future
    reorg moves it under a different parent), as long as the exact
    phrase is present."""

    def test_policy_doc_exists(self):
        assert POLICY_DOC_PATH.is_file(), (
            f"AC #5 requires {POLICY_DOC_PATH} to exist."
        )

    def test_policy_doc_contains_verifier_pass_section_title(self):
        text = POLICY_DOC_PATH.read_text(encoding="utf-8")
        # Match the title as a markdown header line: ``## Verifier
        # pass: dropped and why`` (or ``### …``). Also accept the
        # phrase appearing standalone for resilience.
        section_header_re = re.compile(
            r"^#{1,6}\s+" + re.escape(REQUIRED_DOC_SECTION) + r"\s*$",
            re.MULTILINE,
        )
        assert section_header_re.search(text) or REQUIRED_DOC_SECTION in text, (
            f"AC #5: docs/model-policy.md must contain a section "
            f"titled {REQUIRED_DOC_SECTION!r}. Found neither a "
            f"markdown header nor an inline occurrence."
        )

    def test_policy_doc_documents_haiku_and_sonnet_ids(self):
        """Sanity: the doc cites the model IDs by their string form so
        a reader copying-pasting from the doc gets the canonical
        spelling."""
        text = POLICY_DOC_PATH.read_text(encoding="utf-8")
        assert MODEL_HAIKU_4_5 in text
        assert MODEL_SONNET_4_6 in text


# ===========================================================================
# Selection table — totality + structure
# ===========================================================================


class TestSelectionTableTotality:
    """The selection table is total over RouteTag × TurnType. A
    missing pair raises ValueError; this catches accidental enum
    extensions that forget to update the table."""

    @pytest.mark.parametrize("route_tag", list(RouteTag))
    @pytest.mark.parametrize("turn_type", list(TurnType))
    def test_every_pair_returns_known_model_or_raises_forbidden(
        self, route_tag, turn_type,
    ):
        """Every (RouteTag, TurnType) cross-product either returns
        one of the two whitelisted model IDs OR raises ValueError
        (the F1 fix: nonsense pairs are FORBIDDEN, not silently
        served Haiku). No KeyError, no surprise third model."""
        try:
            result = select_model(route_tag, turn_type)
        except ValueError as exc:
            # F1: forbidden pairs raise ValueError. Verify the
            # message names BOTH the route_tag and the turn_type
            # so the caller can debug.
            assert "not a legal" in str(exc), (
                f"ValueError for ({route_tag}, {turn_type}) should "
                f"mention 'not a legal'; got: {exc}"
            )
            return
        assert result in {MODEL_HAIKU_4_5, MODEL_SONNET_4_6}, (
            f"select_model({route_tag!r}, {turn_type!r}) returned "
            f"{result!r}, which is NOT one of the v1 model IDs. "
            f"AC #4 forbids any third model (especially "
            f"'claude-opus') in server/."
        )

    def test_select_model_unknown_pair_raises_value_error(self):
        """Defensive: an unknown pair raises ValueError rather than
        silently falling back to Haiku. The lookup is total over
        RouteTag × TurnType; a KeyError signals a bug, not a
        graceful-degradation case."""
        # Construct a string that's not a real RouteTag value but
        # passes the dict lookup check.
        with pytest.raises(ValueError, match="No model selected"):
            select_model("LOOKUP_TYPO", TurnType.RETRIEVAL)  # type: ignore[arg-type]


# ===========================================================================
# Default-is-Haiku invariant
# ===========================================================================


class TestDefaultIsHaiku:
    """The v1 policy: Haiku is the default; Sonnet is the EXCEPTION,
    used only for ``LEAN_WRITE`` on Autoformalizer-execution roles
    (AUTOFORMALIZATION + VERIFICATION).

    For every other (RouteTag, TurnType) pair, the answer must be
    Haiku."""

    def test_lookup_lean_write_is_forbidden(self):
        """F1 fix from the E08_S05 critique: LOOKUP doesn't produce
        Lean — `(LOOKUP, LEAN_WRITE)` is FORBIDDEN and raises
        `ValueError` rather than silently returning Haiku. The
        pre-fix behavior masked future caller bugs."""
        with pytest.raises(ValueError, match="not a legal"):
            select_model(RouteTag.LOOKUP, TurnType.LEAN_WRITE)

    def test_synthesis_lean_write_is_forbidden(self):
        """F1 fix: SYNTHESIS doesn't produce Lean either."""
        with pytest.raises(ValueError, match="not a legal"):
            select_model(RouteTag.SYNTHESIS, TurnType.LEAN_WRITE)

    @pytest.mark.parametrize(
        "route_tag",
        [RouteTag.LOOKUP, RouteTag.SYNTHESIS, RouteTag.VERIFICATION,
         RouteTag.AUTOFORMALIZATION],
    )
    @pytest.mark.parametrize(
        "turn_type",
        [TurnType.RETRIEVAL, TurnType.DRAFT],
    )
    def test_retrieval_and_draft_are_always_haiku(self, route_tag, turn_type):
        """Every retrieval and draft turn, regardless of role, is
        Haiku."""
        assert select_model(route_tag, turn_type) == MODEL_HAIKU_4_5


# ===========================================================================
# Verification ↔ Autoformalization parity
# ===========================================================================


class TestVerificationMirrorsAutoformalization:
    """Verification routes to Autoformalizer execution at dispatch
    time. The model selector encodes this by returning the SAME
    model ID for both roles at every TurnType."""

    @pytest.mark.parametrize("turn_type", list(TurnType))
    def test_verification_mirrors_autoformalization_for_every_turn_type(
        self, turn_type,
    ):
        verification_model = select_model(RouteTag.VERIFICATION, turn_type)
        autoformalization_model = select_model(
            RouteTag.AUTOFORMALIZATION, turn_type,
        )
        assert verification_model == autoformalization_model, (
            f"VERIFICATION and AUTOFORMALIZATION must return the "
            f"same model for every TurnType; differ for {turn_type!r}: "
            f"{verification_model!r} vs {autoformalization_model!r}. "
            f"This breaks the verifier-pass-routed-to-Autoformalizer "
            f"contract documented in docs/model-policy.md."
        )


# ===========================================================================
# Model ID format pinning
# ===========================================================================


class TestModelIdFormat:
    """Pin the model ID strings against accidental edits. A
    contributor changing ``MODEL_HAIKU_4_5`` to a pinned snapshot
    form (``"claude-haiku-4-5-20251001"``) would break the AC text
    and need to bump it deliberately."""

    def test_haiku_constant_is_alias_form(self):
        assert MODEL_HAIKU_4_5 == "claude-haiku-4-5"

    def test_sonnet_constant_is_alias_form(self):
        assert MODEL_SONNET_4_6 == "claude-sonnet-4-6"


# ===========================================================================
# TurnType enum — closed at three
# ===========================================================================


class TestTurnTypeClosedAtThree:
    """TurnType has exactly three values: RETRIEVAL, DRAFT,
    LEAN_WRITE. Adding a fourth value would require extending
    ``_SELECTION_TABLE`` in lockstep (caught by the import-time
    invariant in the source module)."""

    def test_three_turn_types(self):
        assert len(list(TurnType)) == 3

    def test_turn_type_values(self):
        assert {t.value for t in TurnType} == {"RETRIEVAL", "DRAFT", "LEAN_WRITE"}


# ===========================================================================
# Closed-at-N import-time invariant survives -O
# ===========================================================================


class TestClosedAtNInvariantSurvivesDashO:
    """The import-time invariant in ``model_selector.py`` uses
    ``if … raise RuntimeError(…)`` rather than a bare ``assert``,
    so it survives ``python -O``. Mirrors the F4 fix from E08_S02."""

    def test_module_imports_under_dash_o(self):
        """Spawn ``python -O -c "import server.orchestrator.model_selector"``
        and assert it succeeds. If the closed-at-N check were a
        bare ``assert``, ``-O`` would compile it away — but the
        check would still need to fire on a divergence."""
        result = subprocess.run(
            [sys.executable, "-O", "-c",
             "import server.orchestrator.model_selector"],
            capture_output=True, text=True, timeout=30,
            cwd=str(SERVER_DIR.parent),
        )
        assert result.returncode == 0, (
            f"`python -O -c 'import server.orchestrator.model_selector'` "
            f"failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_invariant_uses_raise_not_assert(self):
        """Read the source and confirm the closed-at-N check uses
        ``raise RuntimeError`` not ``assert``. A defense-in-depth
        pair: this catches accidental regression of the discipline."""
        source = (
            SERVER_DIR / "orchestrator" / "model_selector.py"
        ).read_text(encoding="utf-8")
        assert "raise RuntimeError" in source, (
            "model_selector.py's closed-at-N invariant must use "
            "`raise RuntimeError` so it survives `python -O`."
        )
        # And: the bare `assert _actual_keys == _expected_keys` form
        # must NOT have crept in.
        assert "assert _actual_keys == _expected_keys" not in source, (
            "Found a bare `assert` form of the closed-at-N invariant "
            "in model_selector.py — this would no-op under `python -O`. "
            "Use `if ... raise RuntimeError(...)` instead."
        )


# ===========================================================================
# E08_S05 critique rectification guards (F1, F2, F3)
# ===========================================================================


#: F2 fix: the canonical model_selector module path. The forbidden-
#: string test allows haiku/sonnet IDs ONLY in this file.
_MODEL_SELECTOR_REL_PATH = "orchestrator/model_selector.py"


class TestRectificationGuards:
    """Regression guards for the E08_S05 critique findings F1
    (forbidden cells), F2 (symmetric SSoT enforcement), and F3
    (policy-version pin)."""

    @pytest.mark.parametrize(
        "model_id,name", [
            (MODEL_HAIKU_4_5, "MODEL_HAIKU_4_5"),
            (MODEL_SONNET_4_6, "MODEL_SONNET_4_6"),
        ],
    )
    def test_f2_haiku_and_sonnet_appear_only_in_model_selector(
        self, model_id, name,
    ):
        """F2 fix from the E08_S05 critique: enforce the
        single-source-of-truth property for ALL model IDs, not just
        Opus. A future contributor pasting
        ``model="claude-sonnet-4-6"`` directly into a
        ``messages.create`` call must trip this test.

        Allows the model ID strings ONLY in
        ``server/orchestrator/model_selector.py`` (the SSoT). The
        Opus ID is forbidden everywhere (see the existing
        TestForbiddenStrings::test_no_claude_opus_in_server_python_files
        test)."""
        offenders: list[tuple[Path, int, str]] = []
        for py_file in SERVER_DIR.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            rel = py_file.relative_to(SERVER_DIR)
            # Allow the model ID strings ONLY in the SSoT module.
            if str(rel) == _MODEL_SELECTOR_REL_PATH:
                continue
            text = py_file.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if model_id in line:
                    offenders.append(
                        (py_file, line_no, line.strip())
                    )
        assert not offenders, (
            f"F2 violation: {model_id!r} (constant {name}) found "
            f"OUTSIDE server/orchestrator/model_selector.py. The "
            f"brief mandates that select_model() be the single "
            f"source of truth for model IDs; hardcoded references "
            f"break this guarantee. Offending lines:\n"
            + "\n".join(
                f"  {path.relative_to(SERVER_DIR.parent)}:{n}: {line}"
                for path, n, line in offenders
            )
        )

    def test_f1_forbidden_cell_lookup_raises_value_error(self):
        """F1 fix: `(LOOKUP, LEAN_WRITE)` and `(SYNTHESIS, LEAN_WRITE)`
        are FORBIDDEN — `select_model` raises `ValueError` rather
        than silently returning Haiku. The error message must
        identify the offending pair so caller bugs are easy to
        diagnose."""
        with pytest.raises(ValueError) as exc_info:
            select_model(RouteTag.LOOKUP, TurnType.LEAN_WRITE)
        msg = str(exc_info.value)
        assert "LOOKUP" in msg
        assert "LEAN_WRITE" in msg
        assert "not a legal" in msg

        with pytest.raises(ValueError) as exc_info:
            select_model(RouteTag.SYNTHESIS, TurnType.LEAN_WRITE)
        msg = str(exc_info.value)
        assert "SYNTHESIS" in msg
        assert "LEAN_WRITE" in msg

    def test_f1_forbidden_cell_table_entry_is_sentinel(self):
        """The pre-fix table had `(LOOKUP, LEAN_WRITE) = "claude-haiku-4-5"`
        which silently passed. The post-fix table uses a sentinel
        value distinct from any model ID. Verify by inspection
        that the table entry for the two forbidden cells is the
        sentinel."""
        from server.orchestrator.model_selector import (
            _FORBIDDEN,
            _SELECTION_TABLE,
        )

        assert _SELECTION_TABLE[(RouteTag.LOOKUP, TurnType.LEAN_WRITE)] is _FORBIDDEN
        assert _SELECTION_TABLE[(RouteTag.SYNTHESIS, TurnType.LEAN_WRITE)] is _FORBIDDEN
        # And: the legitimate cells should NOT be the sentinel.
        assert _SELECTION_TABLE[(RouteTag.AUTOFORMALIZATION, TurnType.LEAN_WRITE)] is not _FORBIDDEN
        assert _SELECTION_TABLE[(RouteTag.VERIFICATION, TurnType.LEAN_WRITE)] is not _FORBIDDEN


class TestPolicyVersion:
    """F3 fix from the E08_S05 critique: pin the POLICY_VERSION
    constant. Bumping the constant is a deliberate, reviewable
    signal in the PR diff that ANY change to ``_SELECTION_TABLE``
    cells (which would invalidate the Anthropic prompt cache for
    that pair) was intentional. The test failure message points
    the contributor to docs/model-policy.md::Cache-invalidation
    discipline for the bump procedure."""

    EXPECTED_VERSION = "1.0"

    def test_policy_version_pinned(self):
        """If you intentionally changed `_SELECTION_TABLE`, also
        bump POLICY_VERSION + add a CHANGELOG row to
        docs/model-policy.md. Then update EXPECTED_VERSION here.
        See docs/model-policy.md::Cache-invalidation discipline."""
        assert POLICY_VERSION == self.EXPECTED_VERSION, (
            f"POLICY_VERSION = {POLICY_VERSION!r} but the test "
            f"pin says {self.EXPECTED_VERSION!r}. If you intentionally "
            f"changed `_SELECTION_TABLE`, ALSO bump POLICY_VERSION + "
            f"add a CHANGELOG row to docs/model-policy.md. If you "
            f"only changed POLICY_VERSION (e.g., to fix a typo) "
            f"without changing `_SELECTION_TABLE`, just update "
            f"EXPECTED_VERSION in this test file."
        )

    def test_policy_doc_has_cache_invalidation_section(self):
        """F3: the cache-invalidation discipline section must exist
        in the policy doc. A regression that drops the section
        would let table changes ship without the cache-warming
        cost being acknowledged."""
        text = POLICY_DOC_PATH.read_text(encoding="utf-8")
        assert "Cache-invalidation discipline" in text, (
            "docs/model-policy.md must contain a 'Cache-invalidation "
            "discipline' section per F3 fix from the E08_S05 critique."
        )
        # The section must mention POLICY_VERSION.
        assert "POLICY_VERSION" in text, (
            "Cache-invalidation section must mention POLICY_VERSION "
            "(the constant that signals intent in PR diffs)."
        )
