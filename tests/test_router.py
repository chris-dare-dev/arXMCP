"""Query-router tests (E08_S01).

Coverage map (acceptance criteria → test class):

  AC                                                       Test class
  ────────────────────────────────────────────────────────────────────
  classify("What is the definition...") → LOOKUP           TestBriefAcceptanceCriteria
  classify("Prove...") → SYNTHESIS                         TestBriefAcceptanceCriteria
  classify("Formalize...Lean 4") → AUTOFORMALIZATION       TestBriefAcceptanceCriteria
  classify(...) returns within 1 ms                        TestLatencyBudget
  pytest tests/test_router.py passes                       the suite itself
  YAML edits do NOT require touching router.py             TestPatternFileSourceOfTruth

Plus regression-grade coverage for:
- 5+ canonical examples per RouteTag
- 3+ ambiguous cases with documented expected behavior (per brief)
- Defensive input handling (None, non-str, empty, whitespace-only)
- Unicode handling (étale, Poincaré)
- Priority order (first-match wins per YAML order)
- Import-time validation (malformed YAML, unknown tag, bad regex)
"""

from __future__ import annotations

import timeit
from pathlib import Path

import pytest

from server.router import (
    DEFAULT_TAG,
    MAX_QUERY_PREFIX_CHARS,
    PATTERNS_PATH,
    RouteTag,
    _canonicalize,
    _load_and_compile,
    classify,
)

# ===========================================================================
# Brief-literal AC coverage
# ===========================================================================


class TestBriefAcceptanceCriteria:
    """Brief AC #1, #2, #3 verbatim — these MUST pass."""

    def test_ac1_what_is_definition_is_lookup(self):
        result = classify("What is the definition of an étale morphism?")
        assert result is RouteTag.LOOKUP

    def test_ac2_prove_is_synthesis(self):
        result = classify(
            "Prove that the Hodge conjecture holds for "
            "abelian varieties of CM type"
        )
        assert result is RouteTag.SYNTHESIS

    def test_ac3_formalize_lean_is_autoformalization(self):
        result = classify("Formalize Yoneda lemma in Lean 4")
        assert result is RouteTag.AUTOFORMALIZATION


# ===========================================================================
# 5+ canonical examples per RouteTag (brief deliverable line)
# ===========================================================================


class TestCanonicalLookup:
    """≥5 canonical Lookup queries."""

    @pytest.mark.parametrize("query", [
        "What is the definition of an étale morphism?",
        "Define the cotangent complex.",
        "Theorem 3.4 in Hartshorne",
        "Lemma 2.1 from Atiyah-Macdonald",
        "What is the notation for the Picard group?",
        "Statement of the Yoneda lemma",
    ])
    def test_lookup_examples(self, query):
        assert classify(query) is RouteTag.LOOKUP


class TestCanonicalSynthesis:
    """≥5 canonical Synthesis queries.

    None of these contain Lookup-precedence tokens like "what is" or
    "definition" — they're explicit derivation requests."""

    @pytest.mark.parametrize("query", [
        "Prove that every finite-dimensional Hilbert space is isomorphic to C^n",
        "Show that the Galois group of a separable extension is a profinite group",
        "Derive the equation for the Riemann zeta function on Re(s) > 1",
        "Sketch a proof of the snake lemma",
        "Give a proof using Zorn's lemma",
    ])
    def test_synthesis_examples(self, query):
        assert classify(query) is RouteTag.SYNTHESIS


class TestCanonicalVerification:
    """≥5 canonical Verification queries."""

    @pytest.mark.parametrize("query", [
        "Verify this proof of the snake lemma",
        "Check the inductive step in the following argument",
        "Is this argument valid?",
        "Validate the application of Zorn's lemma here",
        "Is the conclusion correct given the premises?",
    ])
    def test_verification_examples(self, query):
        assert classify(query) is RouteTag.VERIFICATION


class TestCanonicalAutoformalization:
    """≥5 canonical Autoformalization queries."""

    @pytest.mark.parametrize("query", [
        "Formalize Yoneda lemma in Lean 4",
        "Translate this proof to Lean 4",
        "Write a Mathlib version of this theorem",
        "Formalize the snake lemma",
        "Translate Cauchy-Schwarz into Lean",
    ])
    def test_autoformalization_examples(self, query):
        assert classify(query) is RouteTag.AUTOFORMALIZATION


# ===========================================================================
# Ambiguous cases (≥3 per brief deliverable; documented expected behavior)
# ===========================================================================


class TestAmbiguousCases:
    """Per the brief deliverable: ≥3 ambiguous cases with documented
    expected behavior. The expected behavior is determined by the
    YAML priority order:

        AUTOFORMALIZATION > VERIFICATION > LOOKUP > SYNTHESIS

    See ``server/router_patterns.yaml`` header for the full
    priority rationale + ``research-synthesis.md`` D4."""

    def test_what_is_proof_of_X_routes_to_lookup(self):
        """``"What is the proof of the Yoneda lemma?"`` has BOTH
        a "what is" Lookup signal AND a "proof" Synthesis signal.
        Lookup precedes Synthesis → LOOKUP wins.

        Rationale: most users asking "what is the proof of X" want
        the cached proof retrieved, not assembled from scratch."""
        result = classify("What is the proof of the Yoneda lemma?")
        assert result is RouteTag.LOOKUP

    def test_verify_correct_definition_routes_to_verification(self):
        """``"Verify that this is the correct definition of étale"``
        has VERIFICATION ("verify", "correct") AND LOOKUP
        ("definition") signals. Verification precedes Lookup →
        VERIFICATION wins.

        Rationale: the user has a candidate to validate; that's
        the definitional verification framing."""
        result = classify(
            "Verify that this is the correct definition of étale"
        )
        assert result is RouteTag.VERIFICATION

    def test_formalize_proof_of_X_routes_to_autoformalization(self):
        """``"Formalize the proof of the Hodge conjecture"`` has
        AUTOFORMALIZATION ("formalize") AND SYNTHESIS ("proof")
        signals. Autoformalization is the highest priority →
        AUTOFORMALIZATION wins.

        Rationale: Lean target is the hard mode-switch."""
        result = classify("Formalize the proof of the Hodge conjecture")
        assert result is RouteTag.AUTOFORMALIZATION

    def test_verify_lean_proof_routes_to_autoformalization(self):
        """Bonus ambiguity: ``"Verify that this Lean proof of
        Cauchy-Schwarz typechecks"`` has VERIFICATION ("verify")
        AND AUTOFORMALIZATION ("Lean") signals. Autoformalization
        wins by priority — the Lean target is the hard signal."""
        result = classify(
            "Verify that this Lean proof of Cauchy-Schwarz typechecks"
        )
        assert result is RouteTag.AUTOFORMALIZATION


# ===========================================================================
# Defensive input handling
# ===========================================================================


class TestDefensiveInput:
    """Per the brief: misrouting is a quality issue, not a
    correctness issue. ``classify`` MUST NOT raise on weird
    inputs — it returns ``DEFAULT_TAG`` instead."""

    def test_default_tag_is_lookup(self):
        """The cheapest route is the safe default — Haiku-tier
        retrieval per E08-agent-runtime.md:192."""
        assert DEFAULT_TAG is RouteTag.LOOKUP

    def test_none_returns_default(self):
        assert classify(None) is DEFAULT_TAG

    def test_non_string_returns_default(self):
        assert classify(42) is DEFAULT_TAG
        assert classify(["query"]) is DEFAULT_TAG

    def test_empty_returns_default(self):
        assert classify("") is DEFAULT_TAG

    def test_whitespace_only_returns_default(self):
        assert classify("   \t\n  ") is DEFAULT_TAG

    def test_no_pattern_match_returns_default(self):
        """A query containing none of the priority tokens routes
        to DEFAULT_TAG (Lookup)."""
        assert classify("hello world test") is DEFAULT_TAG


# ===========================================================================
# Unicode handling
# ===========================================================================


class TestUnicode:
    """Python 3's ``re`` module uses Unicode word boundaries on
    ``str`` patterns by default. AC #1's ``étale`` exercises this;
    these tests pin the behavior so a future ``re.ASCII`` flag
    addition fails loudly."""

    def test_etale_in_query_routes_to_lookup(self):
        """``\\b`` boundaries work on ``é`` correctly."""
        assert classify("What is the étale fundamental group?") is RouteTag.LOOKUP

    def test_poincare_accent_doesnt_break_match(self):
        assert classify("Define the Poincaré conjecture") is RouteTag.LOOKUP

    def test_canonicalize_nfc_normalizes(self):
        """NFC normalizes precomposed vs decomposed forms. The
        canonical form is precomposed (``é`` = U+00E9)."""
        decomposed = "étale"  # e + combining acute accent
        precomposed = "étale"
        assert _canonicalize(f"What is {decomposed}?") == _canonicalize(
            f"What is {precomposed}?"
        )


# ===========================================================================
# Latency budget (brief AC #4: <1 ms)
# ===========================================================================


class TestLatencyBudget:
    """Brief AC #4: ``classify(...)`` returns within 1 ms for any
    200-character prefix (measured via ``timeit``)."""

    def test_classify_under_1ms_mean(self):
        """Mean over N=1000 iterations on a worst-case query —
        one that matches NO pattern, so every regex in the list is
        exercised. Single-call measurement is JIT/cache-noise
        dominated at sub-ms scale; the mean is the right signal."""
        # 200-char query with no priority tokens → triggers every
        # regex.search() in the list → DEFAULT_TAG return.
        worst_case = "x " * 100  # 200 chars of "x " repeated; no signals
        worst_case = worst_case[:200]
        assert len(worst_case) == 200

        # Warm up (first call may pay one-time JIT cost).
        classify(worst_case)

        n = 1000
        elapsed_total_s = timeit.timeit(
            lambda: classify(worst_case), number=n,
        )
        mean_per_call_ms = (elapsed_total_s / n) * 1000.0

        assert mean_per_call_ms < 1.0, (
            f"classify exceeded 1ms budget: mean = "
            f"{mean_per_call_ms:.3f} ms (over {n} iterations). "
            f"Either too many patterns OR a regex with catastrophic "
            f"backtracking."
        )

    def test_classify_under_1ms_on_first_match(self):
        """A query that matches the FIRST priority pattern (Lean)
        should be even faster — no need to walk the full list."""
        n = 1000
        elapsed_total_s = timeit.timeit(
            lambda: classify("Translate this to Lean 4"), number=n,
        )
        mean_per_call_ms = (elapsed_total_s / n) * 1000.0
        assert mean_per_call_ms < 1.0


# ===========================================================================
# Pattern file is the source of truth
# ===========================================================================


class TestPatternFileSourceOfTruth:
    """Brief AC #6: editing ``router_patterns.yaml`` does NOT
    require modifying ``router.py``. The router code is
    pattern-list-agnostic; only the YAML file owns the patterns."""

    def test_no_hardcoded_patterns_in_router_module(self):
        """Sanity: the router module has zero literal regex strings
        for the four priority intents. (Module-level constants for
        canonicalization are fine; what we want to catch is a
        future change that hardcodes ``r"\\bprove\\b"`` in
        ``router.py`` instead of the YAML.)"""
        router_src = Path(
            "server/router.py"
        ).resolve()
        text = router_src.read_text(encoding="utf-8")
        # The brief's example patterns must NOT appear as Python
        # string literals in the source (they live in the YAML).
        for needle in (r"\bprove\b", r"\bdefin", r"\blean\b"):
            assert needle not in text, (
                f"Pattern {needle!r} appears literally in router.py "
                f"— it should live in router_patterns.yaml so adding "
                f"a new pattern doesn't require touching this file."
            )

    def test_patterns_path_resolves(self):
        assert PATTERNS_PATH.is_file()

    def test_max_query_prefix_chars_is_200(self):
        """Pin the brief's "first 200 characters" constant."""
        assert MAX_QUERY_PREFIX_CHARS == 200


# ===========================================================================
# Import-time validation
# ===========================================================================


class TestImportTimeValidation:
    """``_load_and_compile`` must fail loudly on bad YAML. These
    tests probe the validation surface by writing synthetic YAML
    files into ``tmp_path``."""

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="missing"):
            _load_and_compile(tmp_path / "nonexistent.yaml")

    def test_malformed_yaml_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("not: a: list:\n  - bad\n  bad", encoding="utf-8")
        with pytest.raises(RuntimeError, match="malformed YAML"):
            _load_and_compile(bad)

    def test_top_level_not_list_raises(self, tmp_path):
        not_list = tmp_path / "dict.yaml"
        not_list.write_text("foo: bar\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="must be a YAML list"):
            _load_and_compile(not_list)

    def test_missing_required_keys_raises(self, tmp_path):
        bad = tmp_path / "missing_keys.yaml"
        bad.write_text(
            "- tag: LOOKUP\n  regex: 'foo'\n",  # missing 'rationale'
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="missing required keys"):
            _load_and_compile(bad)

    def test_unknown_tag_raises(self, tmp_path):
        bad = tmp_path / "bad_tag.yaml"
        bad.write_text(
            "- tag: SOMETHING_ELSE\n  regex: 'foo'\n  rationale: 'x'\n",
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="not a valid RouteTag"):
            _load_and_compile(bad)

    def test_bad_regex_raises(self, tmp_path):
        bad = tmp_path / "bad_regex.yaml"
        bad.write_text(
            "- tag: LOOKUP\n  regex: '[unclosed'\n  rationale: 'x'\n",
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="failed to compile"):
            _load_and_compile(bad)

    def test_empty_pattern_list_raises(self, tmp_path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("[]\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="zero entries"):
            _load_and_compile(empty)

    def test_non_dict_entry_raises(self, tmp_path):
        bad = tmp_path / "non_dict.yaml"
        bad.write_text(
            "- 'just a string'\n", encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="must be a mapping"):
            _load_and_compile(bad)


# ===========================================================================
# Priority order pins
# ===========================================================================


class TestPriorityOrder:
    """The synthesis decision D4: AUTOFORMALIZATION > VERIFICATION
    > LOOKUP > SYNTHESIS. Pin this with explicit cases so a future
    YAML reorder is caught."""

    def test_autoformalization_beats_verification(self):
        """``"Verify the Lean proof"`` — Lean (top) beats verify."""
        assert classify("Verify the Lean proof") is RouteTag.AUTOFORMALIZATION

    def test_autoformalization_beats_lookup(self):
        """``"What is the Lean syntax for X"`` — Lean beats what-is."""
        assert classify("What is the Lean syntax for monoid?") is (
            RouteTag.AUTOFORMALIZATION
        )

    def test_autoformalization_beats_synthesis(self):
        """``"Prove this in Lean"`` — Lean beats prove."""
        assert classify("Prove this in Lean") is RouteTag.AUTOFORMALIZATION

    def test_verification_beats_lookup(self):
        """``"Check the definition"`` — check beats define."""
        assert classify("Check the definition of monoid") is (
            RouteTag.VERIFICATION
        )

    def test_verification_beats_synthesis(self):
        """``"Verify this proof"`` — verify beats prove."""
        assert classify("Verify this proof") is RouteTag.VERIFICATION

    def test_lookup_beats_synthesis(self):
        """``"What is the proof of X"`` — what-is beats proof."""
        assert classify("What is the proof of Cauchy-Schwarz?") is (
            RouteTag.LOOKUP
        )


# ===========================================================================
# The 200-char prefix slice
# ===========================================================================


class TestPrefixSlice:
    """Patterns operate on the first 200 chars only. A signal
    appearing AFTER char 200 must NOT trigger."""

    def test_signal_past_200_chars_ignored(self):
        """200 chars of pure padding + "prove" at position 201 →
        the prove signal is sliced off, no Synthesis match,
        DEFAULT_TAG returned."""
        prefix_padding = "x " * 100  # 200 chars of "x " repeated
        prefix_padding = prefix_padding[:200]
        assert len(prefix_padding) == 200
        query = prefix_padding + " prove this"
        # The "prove" signal is past char 200 → not seen.
        assert classify(query) is DEFAULT_TAG

    def test_signal_at_char_199_still_matches(self):
        """A signal STARTING within the first 200 chars is matched.

        Note: regex match needs the FULL keyword in the slice; if the
        keyword spans the 200-char boundary, only part is visible.
        We test the canonical case where the keyword fits entirely."""
        # "verify" at char 0 — well inside the 200-char window.
        assert classify("verify " + "x" * 190) is RouteTag.VERIFICATION


# ===========================================================================
# Canonicalization unit tests
# ===========================================================================


class TestCanonicalization:
    def test_canonicalize_strips_leading_trailing_whitespace(self):
        assert _canonicalize("  hello  ") == "hello"

    def test_canonicalize_collapses_internal_whitespace(self):
        assert _canonicalize("hello\t\n  world") == "hello world"

    def test_canonicalize_truncates_to_200_chars(self):
        long = "a" * 300
        result = _canonicalize(long)
        assert len(result) <= 200

    def test_canonicalize_does_not_lowercase(self):
        """We rely on re.IGNORECASE for matching; the canonical form
        preserves case so the original repr is debuggable."""
        assert _canonicalize("HELLO World") == "HELLO World"

    def test_canonicalize_non_string_returns_empty(self):
        assert _canonicalize(None) == ""
        assert _canonicalize(42) == ""
        assert _canonicalize(["foo"]) == ""
