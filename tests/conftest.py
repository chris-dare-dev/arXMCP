"""Shared pytest fixtures for the arXMCP test suite.

Closes F8 from the E04_S01 adversary critique: the
``_patched_store_paths`` fixture lived inside ``tests/test_store.py``
and only fired for tests in that file. Any future test in another
file that exercises ``ingest.store.write_chunks`` would write to
the developer's checkout-local ``var/arxmcp/ops/store-stats.jsonl``
on every run. Hoisting the fixture into the package-level
``conftest.py`` makes it autouse for every test in ``tests/``.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Custom pytest options (E05_S02)
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--ndcg-min`` flag for the retrieval-quality test.

    The eval harness (``tests/eval/test_retrieval_quality.py``) uses
    this threshold to gate the Tier-0 → Tier-1 transition. Default is
    ``0.70`` (the Tier-0 ANN-only target). E07_S04 raises this to
    ``0.80`` for the hybrid + reranker pipeline (Tier-1 → Tier-2).

    Surfaced as a fixture (``ndcg_min`` below) so tests read the
    threshold via dependency injection rather than reaching into
    ``request.config.getoption`` ad-hoc.
    """
    parser.addoption(
        "--ndcg-min",
        action="store",
        default=0.70,
        type=float,
        help=(
            "minimum acceptable nDCG@5 mean for the retrieval-quality "
            "test. Default 0.70 (Tier-0 ANN-only); E07 raises to 0.80 "
            "for hybrid + reranker."
        ),
    )


@pytest.fixture
def ndcg_min(request: pytest.FixtureRequest) -> float:
    """Return the configured ``--ndcg-min`` threshold."""
    return float(request.config.getoption("--ndcg-min"))


@pytest.fixture(autouse=True)
def _patched_store_stats_path(tmp_path, monkeypatch):
    """Redirect ``ingest.store.STORE_STATS_PATH`` into ``tmp_path``.

    The store appends one JSON line to that path per ``write_chunks``
    call. Without this fixture, every integration test would pollute
    the developer's checkout-local ``var/arxmcp/ops/store-stats.jsonl``
    on every run. Patching at the module level via ``monkeypatch``
    auto-restores after each test, so cross-test contamination is
    impossible.
    """
    try:
        import ingest.store as store_mod
    except ImportError:
        # ingest.store may not be importable from every test (e.g. tests
        # that intentionally avoid pulling lancedb / pyarrow); skipping
        # the patch is safe because no STORE_STATS_PATH writer can fire.
        yield
        return
    monkeypatch.setattr(
        store_mod,
        "STORE_STATS_PATH",
        tmp_path / "ops" / "store-stats.jsonl",
    )
    yield


@pytest.fixture(autouse=True)
def _patched_bm25_stats_path(tmp_path, monkeypatch):
    """Redirect ``ingest.bm25_indexer.BM25_STATS_PATH`` into ``tmp_path``.

    Mirrors ``_patched_store_stats_path`` for the BM25 ops log so
    integration tests cannot pollute the developer's checkout-local
    ``var/arxmcp/ops/bm25-stats.jsonl`` on every run.
    """
    try:
        import ingest.bm25_indexer as bm25_mod
    except ImportError:
        # rank-bm25 may not be installed in every test environment;
        # the patch is a no-op when the module can't be imported.
        yield
        return
    monkeypatch.setattr(
        bm25_mod,
        "BM25_STATS_PATH",
        tmp_path / "ops" / "bm25-stats.jsonl",
    )
    yield
