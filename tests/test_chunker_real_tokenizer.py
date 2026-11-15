"""Chunker tests that depend on token counts, re-run on the real BGE-M3
tokenizer.

Every other test gives the chunker a stand-in tokenizer
(``tests/_stand_in_tokenizer.py``). These classes re-run the ones whose
assertions are about token budgets, windows, truncation and the golden
fixtures, so the real tokenizer's behaviour stays pinned. They need the
tokenizer in the Hugging Face cache: ``pytest -m requires_model``.
"""

from __future__ import annotations

import pytest

from tests import test_chunker as stand_in_suite

pytestmark = pytest.mark.requires_model


class TestRealFixtureSuite(stand_in_suite.TestFixtureSuite):
    pass


class TestRealProofWindowSplitting(stand_in_suite.TestProofWindowSplitting):
    pass


class TestRealStatementTokenBudget(stand_in_suite.TestStatementTokenBudget):
    pass


class TestRealBudgetBump(stand_in_suite.TestB2BudgetBumpTakesEffect):
    pass


class TestRealStmtTruncationFlag(stand_in_suite.TestF5StmtTruncationFlag):
    pass


class TestRealCharOffsetWindowing(stand_in_suite.TestF6CharOffsetWindowing):
    pass


def test_runs_on_the_real_tokenizer():
    """Guards the guard: if the stand-in leaked in here, the classes above
    would re-test the stand-in and pin nothing."""
    from ingest.chunker import _get_tokenizer

    assert type(_get_tokenizer()).__name__ != "StandInTokenizer"
