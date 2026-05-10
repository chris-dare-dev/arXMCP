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
    TurnType,
    select_model,
)
from server.router import RouteTag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Path to ``server/`` for the forbidden-string scan.
SERVER_DIR: Path = Path(__file__).resolve().parent.parent / "server"

#: Path to the policy doc.
POLICY_DOC_PATH: Path = (
    Path(__file__).resolve().parent.parent / "docs" / "model-policy.md"
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
    def test_every_pair_returns_a_known_model_id(self, route_tag, turn_type):
        """Every (RouteTag, TurnType) cross-product returns one of
        the two whitelisted model IDs. No KeyError, no surprise
        third model."""
        result = select_model(route_tag, turn_type)
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

    def test_lookup_lean_write_is_haiku(self):
        """LOOKUP doesn't produce Lean — its LEAN_WRITE turn (if it
        ever happens, defensive-only) gets Haiku."""
        assert select_model(RouteTag.LOOKUP, TurnType.LEAN_WRITE) == MODEL_HAIKU_4_5

    def test_synthesis_lean_write_is_haiku(self):
        """SYNTHESIS doesn't produce Lean either."""
        assert select_model(RouteTag.SYNTHESIS, TurnType.LEAN_WRITE) == MODEL_HAIKU_4_5

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
