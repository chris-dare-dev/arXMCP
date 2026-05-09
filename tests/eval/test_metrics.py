"""Unit tests for ``tests/eval/metrics.py`` (E05_S02).

The retrieval-quality test (``test_retrieval_quality.py``) skips on a
cold-start dev box, so the metric functions need their own self-
contained verification. These tests run on every ``make test`` and
gate the math.

Coverage map:

  AC / Decision                        Test class
  ──────────────────────────────────────────────────────────────────
  AC: standalone ndcg_at_k             TestNdcgAtK
  AC: standalone recall_at_k           TestRecallAtK
  AC2: --ndcg-min=0.50 fails           TestThresholdCheck
  D5: plain (J-K) form, NOT Burges     TestNdcgAtK::test_plain_form_*
  D6: iDCG=0 → return 0.0              TestNdcgAtK::test_zero_idcg_*
  D7: empty relevant set → 0.0         TestRecallAtK::test_empty_*
  D14: HIGHLY_RELEVANT_GRADE=3 lock    TestConstants
"""

from __future__ import annotations

import math

import pytest

from tests.eval.metrics import (
    HIGHLY_RELEVANT_GRADE,
    ThresholdNotMetError,
    _mean,
    assert_threshold,
    ndcg_at_k,
    recall_at_k,
)

# ===========================================================================
# Constants — locks against silent grade-scale changes
# ===========================================================================


class TestConstants:
    def test_highly_relevant_grade_is_three(self):
        """The brief's 0–3 scale puts grade-3 as the 'primary answer'.
        A future move to 0–4 (TREC Web) would update this single
        constant, not literals in two functions."""
        assert HIGHLY_RELEVANT_GRADE == 3


# ===========================================================================
# nDCG@k — Järvelin-Kekäläinen (plain rel) form
# ===========================================================================


class TestNdcgAtK:
    def test_perfect_ranking_returns_one(self):
        """Top-3 retrieved are exactly the top-3 graded chunks in
        descending grade order → nDCG = 1.0."""
        retrieved = ["a", "b", "c"]
        ground = {"a": 3, "b": 2, "c": 1}
        assert ndcg_at_k(retrieved, ground, k=3) == 1.0

    def test_reversed_ranking_below_one(self):
        """Inverted order — same chunks, worst-first — must score
        strictly less than 1.0."""
        retrieved = ["c", "b", "a"]
        ground = {"a": 3, "b": 2, "c": 1}
        result = ndcg_at_k(retrieved, ground, k=3)
        assert 0.0 < result < 1.0

    def test_plain_form_matches_hand_calculation(self):
        """D5: plain (J-K) form — DCG = Σ rel_i / log2(i+1).

        Hand calc with retrieved=[a, b, c, d], grades a=3, b=1, c=2,
        d=0, k=4:
          DCG  = 3/log2(2) + 1/log2(3) + 2/log2(4) + 0/log2(5)
               = 3/1 + 1/1.585 + 2/2 + 0
               = 3 + 0.6309 + 1 + 0 = 4.6309
          ideal grades sorted desc → [3, 2, 1, 0]
          IDCG = 3/log2(2) + 2/log2(3) + 1/log2(4) + 0/log2(5)
               = 3 + 1.2619 + 0.5 + 0 = 4.7619
          nDCG = 4.6309 / 4.7619 ≈ 0.9725
        """
        retrieved = ["a", "b", "c", "d"]
        ground = {"a": 3, "b": 1, "c": 2, "d": 0}
        expected = (
            (3 + 1 / math.log2(3) + 2 / math.log2(4))
            / (3 + 2 / math.log2(3) + 1 / math.log2(4))
        )
        result = ndcg_at_k(retrieved, ground, k=4)
        assert math.isclose(result, expected, rel_tol=1e-9)

    def test_plain_form_diverges_from_burges_form(self):
        """D5 lock: rule out a future regression where someone
        switches the implementation to ``2^rel - 1`` (Burges /
        sklearn default).

        With grades a=3, b=0, c=0 (perfect ranking → both forms 1.0),
        we choose a non-trivial layout to expose the difference:
        retrieved=[a, b], ground={a:3, b:1}, k=2.

          Plain:  DCG = 3/1 + 1/log2(3) ≈ 3.6309
                  IDCG = 3/1 + 1/log2(3) ≈ 3.6309 → nDCG = 1.0

        OK — that's still 1.0 in plain form because retrieval IS
        ideal. Pick a different layout: retrieved=[b, a], grades
        a=3, b=1, k=2.

          Plain:  DCG = 1/1 + 3/log2(3) ≈ 1 + 1.8927 = 2.8927
                  IDCG = 3/1 + 1/log2(3) ≈ 3.6309
                  nDCG = 2.8927 / 3.6309 ≈ 0.7967
          Burges: DCG = 1/1 + 7/log2(3) = 1 + 4.4163 = 5.4163
                  IDCG = 7/1 + 1/log2(3) = 7.6309
                  nDCG = 5.4163 / 7.6309 ≈ 0.7099

        The plain form scores ~0.7967, the Burges form ~0.7099. We
        assert the plain value.
        """
        retrieved = ["b", "a"]
        ground = {"a": 3, "b": 1}
        result = ndcg_at_k(retrieved, ground, k=2)
        plain_expected = (1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3))
        burges_expected = (1 + 7 / math.log2(3)) / (7 + 1 / math.log2(3))
        assert math.isclose(result, plain_expected, rel_tol=1e-9)
        assert not math.isclose(result, burges_expected, rel_tol=1e-3)

    def test_zero_idcg_returns_zero(self):
        """D6: a query with no positive-relevance chunks → IDCG=0 →
        nDCG=0.0 (NOT NaN)."""
        retrieved = ["a", "b"]
        ground = {"a": 0, "b": 0}
        assert ndcg_at_k(retrieved, ground, k=2) == 0.0

    def test_zero_idcg_empty_ground_returns_zero(self):
        """An empty ground-truth dict → IDCG=0 → nDCG=0."""
        assert ndcg_at_k(["a"], {}, k=1) == 0.0

    def test_truncates_retrieved_to_k(self):
        """Top-k cutoff: if more chunks are retrieved than k, only
        the first k contribute to DCG."""
        retrieved = ["a", "b", "c", "d", "e"]
        ground = {"a": 3, "b": 2, "c": 1, "d": 0, "e": 0}
        # nDCG@3 should NOT depend on what's at ranks 4–5.
        retrieved_short = ["a", "b", "c"]
        assert ndcg_at_k(retrieved, ground, k=3) == ndcg_at_k(
            retrieved_short, ground, k=3
        )

    def test_unranked_retrieved_grade_zero(self):
        """Chunks retrieved that have no ground-truth entry are
        implicit grade 0 (no contribution to DCG)."""
        retrieved = ["unknown_chunk"]
        ground = {"a": 3}
        # DCG = 0; IDCG = 3 (from 'a'); nDCG = 0.
        assert ndcg_at_k(retrieved, ground, k=1) == 0.0

    def test_invalid_k_raises(self):
        with pytest.raises(ValueError, match="k must be a positive int"):
            ndcg_at_k(["a"], {"a": 3}, k=0)
        with pytest.raises(ValueError, match="k must be a positive int"):
            ndcg_at_k(["a"], {"a": 3}, k=-1)

    def test_invalid_grade_raises(self):
        with pytest.raises(ValueError, match="must be int in 0..3"):
            ndcg_at_k(["a"], {"a": 4}, k=1)
        with pytest.raises(ValueError, match="must be int in 0..3"):
            ndcg_at_k(["a"], {"a": -1}, k=1)
        with pytest.raises(ValueError, match="must be int in 0..3"):
            ndcg_at_k(["a"], {"a": 1.5}, k=1)

    def test_bool_grade_rejected(self):
        """``True`` is an instance of ``int`` in Python — must be
        explicitly rejected."""
        with pytest.raises(ValueError, match="must be int in 0..3"):
            ndcg_at_k(["a"], {"a": True}, k=1)

    def test_non_dict_ground_raises(self):
        with pytest.raises(ValueError, match="must be a dict"):
            ndcg_at_k(["a"], [("a", 3)], k=1)


# ===========================================================================
# Recall@k
# ===========================================================================


class TestRecallAtK:
    def test_all_relevant_in_top_k(self):
        """Every grade-3 chunk in the top-k → recall = 1.0."""
        retrieved = ["a", "b", "c"]
        ground = {"a": 3, "b": 3}
        assert recall_at_k(retrieved, ground, k=3) == 1.0

    def test_half_relevant_in_top_k(self):
        retrieved = ["a", "x", "y"]
        ground = {"a": 3, "b": 3}
        assert recall_at_k(retrieved, ground, k=3) == 0.5

    def test_grade2_does_not_count_toward_recall(self):
        """Recall denominator is grade-3 only — grade-2 chunks must
        be ignored."""
        retrieved = ["b"]
        ground = {"a": 3, "b": 2}
        # b is grade-2 (ignored). Relevant set = {a}; not retrieved.
        assert recall_at_k(retrieved, ground, k=1) == 0.0

    def test_grade1_does_not_count_toward_recall(self):
        retrieved = ["b"]
        ground = {"a": 3, "b": 1}
        assert recall_at_k(retrieved, ground, k=1) == 0.0

    def test_empty_relevant_set_returns_zero(self):
        """D7: vacuous case — no grade-3 chunks → return 0.0
        (NOT 1.0). Avoids vacuous-true cells silently inflating
        downstream means."""
        retrieved = ["a", "b"]
        ground = {"a": 1, "b": 2}
        assert recall_at_k(retrieved, ground, k=2) == 0.0

    def test_truncates_retrieved_to_k(self):
        """A chunk at rank k+1 does not contribute to recall@k."""
        retrieved = ["x", "y", "z", "a"]
        ground = {"a": 3}
        assert recall_at_k(retrieved, ground, k=3) == 0.0
        assert recall_at_k(retrieved, ground, k=4) == 1.0

    def test_invalid_k_raises(self):
        with pytest.raises(ValueError, match="k must be a positive int"):
            recall_at_k(["a"], {"a": 3}, k=0)

    def test_invalid_grade_raises(self):
        with pytest.raises(ValueError, match="must be int in 0..3"):
            recall_at_k(["a"], {"a": 5}, k=1)


# ===========================================================================
# assert_threshold (AC2 lock)
# ===========================================================================


class TestThresholdCheck:
    def test_above_threshold_passes(self):
        # Returns None on success; just verify no raise.
        assert_threshold(ndcg5_mean=0.85, ndcg_min=0.70)

    def test_at_threshold_passes(self):
        """The check is ``< ndcg_min``, so equality passes."""
        assert_threshold(ndcg5_mean=0.70, ndcg_min=0.70)

    def test_below_threshold_raises(self):
        """AC2: ``--ndcg-min=0.50`` fails when nDCG@5 mean is below 0.50."""
        with pytest.raises(
            ThresholdNotMetError, match="nDCG@5 mean .* is below the threshold"
        ):
            assert_threshold(ndcg5_mean=0.49, ndcg_min=0.50)

    def test_below_threshold_default_70(self):
        """AC1 calibration: 0.69 fails at the project default 0.70."""
        with pytest.raises(ThresholdNotMetError):
            assert_threshold(ndcg5_mean=0.69, ndcg_min=0.70)

    def test_threshold_error_subclasses_assertion_error(self):
        """Pytest treats ``AssertionError`` specially. Subclass it so
        the failure surface is greppable AND pytest-friendly."""
        assert issubclass(ThresholdNotMetError, AssertionError)

    def test_invalid_threshold_type_raises(self):
        with pytest.raises(ValueError, match="ndcg_min must be a real number"):
            assert_threshold(0.85, "0.70")  # type: ignore[arg-type]

    def test_invalid_score_type_raises(self):
        with pytest.raises(ValueError, match="ndcg5_mean must be a real number"):
            assert_threshold("0.85", 0.70)  # type: ignore[arg-type]

    def test_bool_threshold_rejected(self):
        with pytest.raises(ValueError, match="ndcg_min must be a real number"):
            assert_threshold(0.85, True)  # type: ignore[arg-type]


# ===========================================================================
# _mean helper
# ===========================================================================


class TestMean:
    def test_normal(self):
        assert _mean([1.0, 2.0, 3.0]) == 2.0

    def test_empty_returns_zero(self):
        """Empty input returns 0.0 (not ZeroDivisionError) — the
        caller's behavior matrix already skips the cold-start case."""
        assert _mean([]) == 0.0

    def test_iterator_input(self):
        assert _mean(iter([1.0, 2.0])) == 1.5
