"""Standalone metric functions for the E05 eval harness.

Two pure, dependency-free functions:

- :func:`ndcg_at_k` — Normalized Discounted Cumulative Gain at rank
  ``k``, **plain (Järvelin–Kekäläinen 2002) form**: ``DCG@k = Σ rel_i
  / log2(i+1)`` for ``i`` in ``1..k``. NOT the Burges (2005) form
  used by :func:`sklearn.metrics.ndcg_score` (``2^rel - 1``); the
  brief AC unambiguously specifies the plain form.

- :func:`recall_at_k` — Fraction of grade-3 chunks for a query that
  appear in the top-``k`` retrieved list. Brief: *"fraction of
  grade-3 ('highly relevant') chunks for each query that appear in
  the top-10 ANN results."*

**Edge cases.** Both functions return ``0.0`` (not ``NaN``, not
``1.0``) when the denominator is zero. ``nDCG`` returns 0.0 when the
ideal-DCG is 0.0 (a query with no positive-relevance chunks);
``recall`` returns 0.0 when the relevant set is empty. The fixture
contract (E05_S01 AC-2) forbids the empty-relevant case at curation
time, but these standalone functions cannot assume the AC and must
handle the case explicitly.

**Threshold check.** :func:`assert_threshold` is a tiny convenience
that the retrieval-quality test calls with ``ndcg5_mean`` and
``--ndcg-min``; it raises ``ThresholdNotMetError`` rather than
``AssertionError`` so the failure surface is searchable.

**No filesystem touch, no network, no model load.** Every function
operates on Python lists / numbers; unit tests in
:mod:`tests.eval.test_metrics` exercise them with hand-built inputs.

TODO(E11_S04): the drift watchdog is the first non-test consumer of
this module. If a non-test path needs ``ndcg_at_k`` or ``recall_at_k``,
relocate this module to a top-level ``eval/`` package and update the
import path in this file's docstring + the watchdog. The current
``tests/eval/`` placement matches the brief verbatim.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The "highly relevant" grade per the brief and per E05_S01's AC-2.
#: Recall denominator is ``|chunks where relevance == HIGHLY_RELEVANT|``;
#: any future bump (e.g. switching to a 0–4 scale) would update this
#: single constant rather than a literal scattered through the file.
HIGHLY_RELEVANT_GRADE = 3


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ThresholdNotMetError(AssertionError):
    """Raised by :func:`assert_threshold` when ``ndcg5_mean`` is below
    the configured ``--ndcg-min`` threshold.

    Subclasses :class:`AssertionError` so that pytest's standard
    failure-reporting machinery surfaces it (pytest treats
    ``AssertionError`` specially), but the named subclass makes the
    failure greppable in CI logs and easy to wrap with custom matchers
    in unit tests.
    """


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def ndcg_at_k(
    retrieved_chunk_ids: Sequence[str],
    relevance_by_chunk_id: dict[str, int],
    k: int,
) -> float:
    """Return nDCG@``k`` for one query (Järvelin–Kekäläinen plain form).

    Parameters
    ----------
    retrieved_chunk_ids
        The ranked top-``k`` (or longer; only the first ``k`` are
        used) of chunk_ids returned by retrieval.
    relevance_by_chunk_id
        Ground-truth relevance grades (0..3) keyed by chunk_id. Any
        chunk_id absent from this mapping is implicitly grade 0.
    k
        Rank cutoff (e.g. 5 for nDCG@5). Must be ``>= 1``.

    Returns
    -------
    float
        ``DCG@k / IDCG@k`` in ``[0.0, 1.0]``. Returns ``0.0`` when
        ``IDCG@k == 0`` (the query has no positive-relevance chunks).

    Raises
    ------
    ValueError
        ``k < 1``, or any value in ``relevance_by_chunk_id`` is not a
        plain ``int`` in ``0..3``. ``bool`` is rejected explicitly
        (``isinstance(True, int)`` is ``True`` in Python).

    Notes
    -----
    The discount is ``log2(i + 1)`` with ``i`` 1-indexed so that
    ``i = 1`` → ``log2(2) = 1`` (no discount on the top result),
    ``i = 2`` → ``log2(3) ≈ 1.585``, etc. The ideal DCG is computed
    from the ``k`` largest relevance grades in
    ``relevance_by_chunk_id`` (sorted descending, padded with zeros
    if fewer than ``k`` chunks are graded).

    **Duplicates in `retrieved_chunk_ids[:k]` are rejected** (closes
    F1 from the E05_S02 critique). Without rejection, a caller
    accidentally passing the same chunk_id at two ranks would
    double-count its gain into DCG while iDCG (which uses the
    relevance multiset, not the retrieved positions) would not see
    the duplication — producing nDCG > 1.0 and silently inflating
    the score. The production call site in
    ``test_retrieval_quality.py`` dedupes upstream via the
    ``per_chunk_min_distance`` dict, but the standalone metric must
    not trust callers.
    """
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError(f"k must be a positive int (>= 1); got {k!r}")
    _validate_grades(relevance_by_chunk_id)

    top_k = list(retrieved_chunk_ids[:k])
    if len(set(top_k)) != len(top_k):
        # Duplicate chunk_id at two ranks would inflate DCG without
        # affecting IDCG. Refuse rather than silently double-count.
        raise ValueError(
            f"retrieved_chunk_ids[:k={k}] contains duplicate chunk_ids; "
            f"dedup upstream (e.g. via dict[chunk_id, score]) before "
            f"calling ndcg_at_k. Got: {top_k!r}"
        )

    # DCG over the actual ranked retrieval, capped at k.
    dcg = 0.0
    for rank_idx, chunk_id in enumerate(top_k, start=1):
        rel = relevance_by_chunk_id.get(chunk_id, 0)
        dcg += rel / math.log2(rank_idx + 1)

    # IDCG over the ideal-ordered relevance grades (top-k by grade).
    ideal_grades = sorted(relevance_by_chunk_id.values(), reverse=True)[:k]
    idcg = 0.0
    for rank_idx, rel in enumerate(ideal_grades, start=1):
        idcg += rel / math.log2(rank_idx + 1)

    if idcg == 0.0:
        # No positive-relevance chunks → undefined nDCG. Convention:
        # return 0.0 (matches sklearn / TREC behavior; never NaN).
        return 0.0
    return dcg / idcg


def recall_at_k(
    retrieved_chunk_ids: Sequence[str],
    relevance_by_chunk_id: dict[str, int],
    k: int,
) -> float:
    """Return Recall@``k`` for one query.

    Parameters
    ----------
    retrieved_chunk_ids
        The ranked top-``k`` (or longer; only the first ``k`` are
        used) of chunk_ids returned by retrieval.
    relevance_by_chunk_id
        Ground-truth relevance grades (0..3) keyed by chunk_id.
    k
        Rank cutoff (e.g. 10 for Recall@10).

    Returns
    -------
    float
        ``|grade-3 chunks ∩ top-k retrieved| / |grade-3 chunks|``.
        Returns ``0.0`` when the relevant set is empty (the
        conservative choice — see the module docstring's
        "Edge cases" section).

    Notes
    -----
    Only grade-3 chunks count toward both numerator and denominator.
    Grade-1 and grade-2 chunks are ignored for Recall (they DO
    contribute to nDCG via :func:`ndcg_at_k`). This asymmetry is
    intentional per the brief: Recall measures coverage of the
    *primary* answers, nDCG measures the full graded ranking.
    """
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError(f"k must be a positive int (>= 1); got {k!r}")
    _validate_grades(relevance_by_chunk_id)

    relevant = {
        cid
        for cid, grade in relevance_by_chunk_id.items()
        if grade == HIGHLY_RELEVANT_GRADE
    }
    if not relevant:
        # Vacuous: no grade-3 chunks in the ground truth. Return 0.0
        # (NOT 1.0 — see module docstring) so a fixture mistake does
        # not silently inflate Recall via vacuous-true cells.
        return 0.0
    top_k = set(retrieved_chunk_ids[:k])
    hits = relevant & top_k
    return len(hits) / len(relevant)


# ---------------------------------------------------------------------------
# Threshold helper
# ---------------------------------------------------------------------------


def assert_threshold(ndcg5_mean: float, ndcg_min: float) -> None:
    """Raise :class:`ThresholdNotMetError` if ``ndcg5_mean < ndcg_min``.

    Used by the retrieval-quality test as the AC1/AC2 enforcement
    helper. Factored out as a standalone function so it has its own
    unit test (``test_metrics.py::TestThresholdCheck``) — the brief
    AC2 explicitly requires that the threshold-failure path is
    verified in test, but no real corpus exists at Tier-0 to produce
    a low-nDCG run on demand. This helper is the unit-testable
    boundary.
    """
    if not isinstance(ndcg_min, (int, float)) or isinstance(ndcg_min, bool):
        raise ValueError(
            f"ndcg_min must be a real number; got "
            f"{type(ndcg_min).__name__} ({ndcg_min!r})"
        )
    if not isinstance(ndcg5_mean, (int, float)) or isinstance(ndcg5_mean, bool):
        raise ValueError(
            f"ndcg5_mean must be a real number; got "
            f"{type(ndcg5_mean).__name__} ({ndcg5_mean!r})"
        )
    # F6 close: reject NaN / inf explicitly. Any comparison with NaN
    # returns False (so ``ndcg5_mean < ndcg_min`` would silently
    # PASS the threshold check on a NaN-corrupted score). +inf would
    # also pass vacuously. Both are real-corpus regressions
    # masquerading as success.
    if not math.isfinite(ndcg5_mean):
        raise ValueError(
            f"ndcg5_mean must be finite; got {ndcg5_mean!r} "
            f"(NaN or inf would silently pass the < threshold check)"
        )
    if not math.isfinite(ndcg_min):
        raise ValueError(
            f"ndcg_min must be finite; got {ndcg_min!r}"
        )
    if ndcg5_mean < ndcg_min:
        raise ThresholdNotMetError(
            f"nDCG@5 mean {ndcg5_mean:.4f} is below the threshold "
            f"{ndcg_min:.4f}. Either retrieval quality regressed or "
            f"the threshold needs re-tuning. See "
            f"var/arxmcp/ops/eval/results-*.jsonl for per-query detail."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_grades(relevance_by_chunk_id: dict[str, int]) -> None:
    """Enforce the 0..3 integer grade contract.

    A standalone helper so both ``ndcg_at_k`` and ``recall_at_k``
    catch the same set of input errors with the same wording. Rejects
    ``bool`` explicitly (Python: ``isinstance(True, int) is True``).
    """
    if not isinstance(relevance_by_chunk_id, dict):
        raise ValueError(
            f"relevance_by_chunk_id must be a dict; got "
            f"{type(relevance_by_chunk_id).__name__}"
        )
    for cid, grade in relevance_by_chunk_id.items():
        if not isinstance(cid, str):
            raise ValueError(
                f"relevance_by_chunk_id keys must be str; got "
                f"{type(cid).__name__} for {cid!r}"
            )
        if (
            not isinstance(grade, int)
            or isinstance(grade, bool)
            or not 0 <= grade <= 3
        ):
            raise ValueError(
                f"relevance_by_chunk_id[{cid!r}] must be int in 0..3; "
                f"got {type(grade).__name__} ({grade!r})"
            )


def _mean(values: Iterable[float]) -> float:
    """Return the arithmetic mean of ``values``, or 0.0 if empty.

    Standalone for the same reason as ``_validate_grades``: a future
    weighted-mean variant (e.g. weighting by relevance-set size)
    swaps in here without touching call sites. Empty input returns
    0.0 rather than raising — the test's caller has already skipped
    the empty case via D1's behavior matrix.
    """
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


__all__ = [
    "HIGHLY_RELEVANT_GRADE",
    "ThresholdNotMetError",
    "_mean",
    "assert_threshold",
    "ndcg_at_k",
    "recall_at_k",
]
