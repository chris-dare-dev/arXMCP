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

import os

# E08_S03: faiss-cpu (Tier-2 cache) and PyTorch (BGE-M3 embedder)
# both link against an OpenMP runtime. On macOS, importing both in
# the same process can produce "OMP: Error #15: Initializing
# libomp.dylib, but found libiomp5.dylib already initialized" which
# manifests as a SIGSEGV in pytest. The documented Intel-MKL
# workaround is to set ``KMP_DUPLICATE_LIB_OK=TRUE`` BEFORE either
# library is imported. Set it at conftest module load (which fires
# before any test-file imports) so the env var is in place even
# when test files are collected before the test session starts.
#
# This is a TEST-ONLY workaround. Production deployments use a
# Linux container where the same OpenMP loader handles both libs
# without conflict.
#
# F10 fix from the E08_S03 critique: ``os.environ.setdefault`` would
# leak the env var into every subprocess pytest spawns AND would
# survive past the pytest session. We now use ``setdefault`` so a
# pre-existing operator setting wins, AND a session-finish hook
# clears it if WE were the one that set it. The brief "test-only"
# label is now backed by a finalizer.
_KMP_KEY = "KMP_DUPLICATE_LIB_OK"
_KMP_WAS_PRESET_BY_USER = _KMP_KEY in os.environ
os.environ.setdefault(_KMP_KEY, "TRUE")

import pytest  # noqa: E402


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """F10 fix from the E08_S03 critique: clear KMP_DUPLICATE_LIB_OK
    at session end if WE set it (a pre-existing operator setting is
    preserved). Closes the "leaks into subprocesses" concern by
    bounding the env var's lifetime to the pytest session."""
    if not _KMP_WAS_PRESET_BY_USER:
        os.environ.pop(_KMP_KEY, None)

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
    parser.addoption(
        "--update-tool-schema-hash",
        action="store_true",
        default=False,
        help=(
            "Regenerate EXPECTED_TOOL_SCHEMA_SHA256 in "
            "tests/test_server_tool_schema.py to match the live "
            "tools/list bytes. Use after an INTENTIONAL tool schema "
            "change (description / argument schema / TOOL_SCHEMA_VERSION "
            "bump). CI never sets this flag — a hash drift in CI is a "
            "BP1 prompt-cache invalidation signal (see "
            ".claude/notes/07-multi-agent-caching.md lines 40-49)."
        ),
    )
    parser.addoption(
        "--hybrid",
        action="store_true",
        default=False,
        help=(
            "Run the eval harness against the FULL hybrid pipeline "
            "(BM25 → ANN+RRF) instead of the dense-only ANN path. "
            "Default off; the existing Tier-0 eval invocation "
            "(`make eval`) stays dense-only. The Tier-1 → Tier-2 "
            "exit gate (E07_S04) flips this on. Test-side flag only; "
            "production retrieval is gated by ARXMCP_ENABLE_RERANK on "
            "the server config."
        ),
    )
    parser.addoption(
        "--rerank",
        action="store_true",
        default=False,
        help=(
            "Add Phase-3 BGE-reranker-v2-m3 cross-encoder pass on top "
            "of the hybrid pipeline (requires --hybrid; --rerank without "
            "--hybrid raises pytest.UsageError). The BGE-reranker model "
            "is ~2.3 GB; this flag also requires "
            "ARXMCP_RUN_REAL_BGE_RERANKER=1 (matches the env-gate "
            "convention from tests/retrieval/test_rerank.py); when the "
            "env var is unset, the test SKIPs."
        ),
    )


@pytest.fixture
def ndcg_min(request: pytest.FixtureRequest) -> float:
    """Return the configured ``--ndcg-min`` threshold."""
    return float(request.config.getoption("--ndcg-min"))


@pytest.fixture
def hybrid(request: pytest.FixtureRequest) -> bool:
    """Return whether the eval harness should run the FULL hybrid
    pipeline (BM25 → ANN+RRF) instead of dense-only ANN. Per
    research-synthesis.md D2 (E07_S04). Default False so the
    existing Tier-0 invocation is unchanged."""
    return bool(request.config.getoption("--hybrid"))


@pytest.fixture
def rerank(request: pytest.FixtureRequest) -> bool:
    """Return whether to add Phase-3 BGE-reranker on top of hybrid.

    D3 (E07_S04 synthesis): ``--rerank`` without ``--hybrid`` is a
    user error — reranking only-RRF candidates is the design;
    asking to rerank dense-only candidates is incoherent. Raise
    ``pytest.UsageError`` at fixture-setup time so the operator
    sees the problem before any test runs.
    """
    rerank_set = bool(request.config.getoption("--rerank"))
    hybrid_set = bool(request.config.getoption("--hybrid"))
    if rerank_set and not hybrid_set:
        raise pytest.UsageError(
            "--rerank requires --hybrid. Reranking only operates on "
            "Phase-2 RRF candidates; pass both flags to enable the "
            "full 3-phase pipeline."
        )
    return rerank_set


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


@pytest.fixture(autouse=True)
def _patched_bm25_index_root(tmp_path, monkeypatch):
    """Redirect ``ingest.bm25_indexer.BM25_INDEX_ROOT`` into ``tmp_path``.

    Without this, the BM25 artifact directory is global at
    ``var/arxmcp/index/bm25/v<N>/`` and stale artifacts from a
    previous test run poison subsequent tests — the cross-check
    introduced by E07_S01 F4 (``BM25Phase`` cross-checks
    ``chunk_ids.json`` against the live LanceDB table) trips on a
    stale artifact whose ids point to a different test's corpus.

    Autouse so every test gets a fresh per-tmp_path artifact root,
    matching the discipline of ``_patched_store_stats_path`` and
    ``_patched_bm25_stats_path``.
    """
    try:
        import ingest.bm25_indexer as bm25_mod
    except ImportError:
        yield
        return
    monkeypatch.setattr(
        bm25_mod,
        "BM25_INDEX_ROOT",
        tmp_path / "bm25_index_root",
    )
    yield


@pytest.fixture(autouse=True)
def _patched_cache_db_path(tmp_path, monkeypatch):
    """Redirect ``Config.cache_db_path`` default into ``tmp_path``.

    F4 fix from the E08_S03 critique: ``Config.cache_db_path`` defaults
    to ``var/arxmcp/cache/retrieval.db`` (a checkout-relative path).
    Without this fixture every integration test that constructs
    ``Resources`` would write Tier-1 SQLite entries under the
    developer's working directory AND those entries survive across
    test runs — a CI / local re-run would see Tier-1 hits from a
    previous run, producing test non-determinism.

    Mirrors the discipline of ``_patched_store_stats_path``,
    ``_patched_bm25_stats_path``, and ``_patched_bm25_index_root`` —
    the conftest's standing pattern for module-level on-disk paths.

    The patch redirects the pydantic-settings default by setting the
    corresponding environment variable BEFORE any ``Config()`` is
    constructed in the test. ``ARXMCP_CACHE_DB_PATH`` is the env-var
    form (per ``Config.model_config.env_prefix = 'ARXMCP_'``).
    """
    monkeypatch.setenv(
        "ARXMCP_CACHE_DB_PATH",
        str(tmp_path / "cache" / "retrieval.db"),
    )
    yield
