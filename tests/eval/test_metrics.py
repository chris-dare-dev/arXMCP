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

import json
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

    def test_duplicate_retrieved_raises(self):
        """F1: duplicate chunk_ids in retrieved must be rejected.
        Without rejection, the standalone metric returns nDCG > 1.0
        (DCG double-counts the duplicated rel; IDCG does not)."""
        with pytest.raises(
            ValueError, match="contains duplicate chunk_ids"
        ):
            ndcg_at_k(["a", "a", "b"], {"a": 3, "b": 1}, k=3)

    def test_duplicate_retrieved_outside_k_does_not_raise(self):
        """The dup-check is scoped to the top-k slice. A duplicate at
        rank > k does not contribute to DCG and should not trip the
        guard (slice-then-set semantics are the contract)."""
        # Duplicate is at rank 4; k=3 trims it off → no error.
        ndcg_at_k(["a", "b", "c", "a"], {"a": 3, "b": 2, "c": 1}, k=3)


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

    def test_nan_score_rejected(self):
        """F6: NaN comparisons return False, so a NaN ndcg5_mean would
        silently PASS the < threshold check and a real corpus
        regression would ship as a green test."""
        with pytest.raises(ValueError, match="ndcg5_mean must be finite"):
            assert_threshold(float("nan"), 0.70)

    def test_inf_score_rejected(self):
        """+inf would pass the < threshold check vacuously."""
        with pytest.raises(ValueError, match="ndcg5_mean must be finite"):
            assert_threshold(float("inf"), 0.70)

    def test_nan_threshold_rejected(self):
        with pytest.raises(ValueError, match="ndcg_min must be finite"):
            assert_threshold(0.85, float("nan"))


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


# ===========================================================================
# F4 — score_and_write integration tests (RUN-cell helper)
# ===========================================================================


class TestScoreAndWrite:
    """Lock the AC2 threshold-failure path AND the per-query-JSONL +
    aggregate-JSON write contract. Closes F4 of the E05_S02 critique:
    the original implementation tested ``assert_threshold`` in
    isolation but had no test that the live ``test_retrieval_quality``
    actually passes the right arguments to it.

    These tests drive ``score_and_write`` directly with synthetic
    per-query rows (no encoder, no LanceDB) so they run on every
    ``make test``.
    """

    def _synthetic_rows(
        self, *, ndcg_pattern: list[float], recall_pattern: list[float]
    ) -> list[dict]:
        """Build N rows where each row carries a controlled
        ``ndcg5`` / ``recall10`` value. The mean of ``ndcg_pattern``
        becomes the aggregate ``ndcg5_mean``."""
        return [
            {
                "ndcg5": ndcg,
                "query_id": f"q{i + 1:02d}",
                "query_text": f"synthetic query {i + 1}",
                "recall10": recall,
                "retrieved_chunk_ids": [
                    f"arxiv:2307.{i + 1:05d}:{'a' * 16}"
                ],
            }
            for i, (ndcg, recall) in enumerate(
                zip(ndcg_pattern, recall_pattern, strict=True)
            )
        ]

    def test_above_threshold_writes_files_and_returns(self, tmp_path):
        from tests.eval.test_retrieval_quality import score_and_write

        rows = self._synthetic_rows(
            ndcg_pattern=[0.9, 0.85, 0.95],
            recall_pattern=[1.0, 1.0, 0.5],
        )
        score_and_write(
            per_query_rows=rows,
            corpus_version=42,
            ndcg_min=0.70,
            output_dir=tmp_path,
        )
        results_path = tmp_path / "results-42.jsonl"
        aggregate_path = tmp_path / "aggregate-42.json"
        assert results_path.is_file()
        assert aggregate_path.is_file()

        # Aggregate schema: brief-locked 5 keys, alphabetical.
        agg = json.loads(aggregate_path.read_text(encoding="utf-8"))
        assert list(agg.keys()) == [
            "corpus_version",
            "ndcg5_mean",
            "query_count",
            "recall10_mean",
            "timestamp",
        ]
        assert agg["corpus_version"] == 42
        assert agg["query_count"] == 3
        assert agg["ndcg5_mean"] == pytest.approx(0.9)
        assert agg["recall10_mean"] == pytest.approx(2.5 / 3)

        # JSONL: one line per row, alphabetical keys per row.
        lines = results_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        first = json.loads(lines[0])
        assert list(first.keys()) == [
            "ndcg5",
            "query_id",
            "query_text",
            "recall10",
            "retrieved_chunk_ids",
        ]

    def test_below_threshold_raises(self, tmp_path):
        """AC2: synthetic ``ndcg5_mean = 0.3`` must fail the 0.50
        threshold via ``ThresholdNotMetError``. This locks the
        integration of ``assert_threshold`` into the actual harness
        (the original critique was that the helper was tested in
        isolation but the integration was unverified)."""
        from tests.eval.metrics import ThresholdNotMetError
        from tests.eval.test_retrieval_quality import score_and_write

        rows = self._synthetic_rows(
            ndcg_pattern=[0.3, 0.3, 0.3],
            recall_pattern=[0.0, 0.0, 0.0],
        )
        with pytest.raises(ThresholdNotMetError, match="below the threshold"):
            score_and_write(
                per_query_rows=rows,
                corpus_version=7,
                ndcg_min=0.50,
                output_dir=tmp_path,
            )
        # IMPORTANT: even on threshold-fail, the result files must be
        # written (the drift baseline is the diagnostic output —
        # operators need the per-query JSONL to triage the failure).
        assert (tmp_path / "results-7.jsonl").is_file()
        assert (tmp_path / "aggregate-7.json").is_file()

    def test_at_threshold_passes(self, tmp_path):
        """The threshold check is ``<``, so equality passes.

        Uses 0.5 (exactly representable in IEEE 754) so the mean of
        ``[0.5, 0.5, 0.5]`` is exactly 0.5 and the test isolates the
        equality-passes invariant from floating-point rounding.
        ``0.7`` is NOT exactly representable; ``mean([0.7, 0.7, 0.7])``
        is ``0.6999999999999999`` — which is the correct behavior of
        the ``<`` threshold check (a real corpus producing 0.69... is
        below 0.70 and SHOULD fail).
        """
        from tests.eval.test_retrieval_quality import score_and_write

        rows = self._synthetic_rows(
            ndcg_pattern=[0.5, 0.5, 0.5],
            recall_pattern=[1.0, 1.0, 1.0],
        )
        # Should NOT raise.
        score_and_write(
            per_query_rows=rows,
            corpus_version=99,
            ndcg_min=0.5,
            output_dir=tmp_path,
        )
        agg = json.loads(
            (tmp_path / "aggregate-99.json").read_text(encoding="utf-8")
        )
        assert agg["ndcg5_mean"] == 0.5


# ===========================================================================
# F3 lock — column-name single source of truth
# ===========================================================================


class TestColumnNamesSourceOfTruth:
    def test_test_module_uses_imported_constant(self):
        """Closes F3: ``EMBEDDING_COLUMN_NAMES`` is exported from
        ``ingest.schema``; the eval harness imports it rather than
        literalizing the column-name strings."""
        from ingest.schema import EMBEDDING_COLUMN_NAMES
        from tests.eval.test_retrieval_quality import EMBEDDING_COLUMNS

        assert EMBEDDING_COLUMNS is EMBEDDING_COLUMN_NAMES
        # Sanity: the actual schema column list contains both names.
        from ingest.schema import CHUNKS_SCHEMA_V1

        schema_field_names = {f.name for f in CHUNKS_SCHEMA_V1}
        for col in EMBEDDING_COLUMN_NAMES:
            assert col in schema_field_names
