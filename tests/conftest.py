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
