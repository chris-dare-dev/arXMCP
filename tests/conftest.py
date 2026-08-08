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
# Opt-in marker deselection (issue #206)
# ---------------------------------------------------------------------------

#: The markers whose ``pyproject.toml`` registration promises "Skipped by
#: default; opt-in via ``pytest -m <marker>``". Nothing implemented that
#: promise: ``addopts`` is bare ``-q``, so the markers were pure metadata
#: and every marked test ran on every ``make test``.
#:
#: Most marked tests happen to carry a second, self-imposed guard (an env
#: var, a ``shutil.which`` probe), which hid the gap. ``requires_latexmlc``
#: on ``tests/test_drift_check.py::TestIntegrationRealLatexmlc`` does not,
#: deliberately — its docstring records that an added ``skipif`` was REMOVED
#: (F10) because it produced silent skips even on explicit opt-in. That
#: reasoning is right, and it is exactly why the deselection belongs here,
#: at collection, rather than in a per-class ``skipif``: opting in must
#: still fail loudly. Without it a fresh clone with no LaTeXML installed
#: hard-fails ``make test`` on its first run, and a box that HAS LaTeXML
#: fails on the 15s render timeout instead.
#:
#: ``eval`` is deliberately NOT in this set: its registration documents
#: opt-OUT semantics (``pytest -m "not eval"``) and ``make eval`` depends on
#: it running by default.
_OPT_IN_MARKERS: frozenset[str] = frozenset(
    {
        "requires_model",
        "requires_latexmlc",
        "requires_full_corpus",
        "requires_lean_repl",
        "requires_pdflatex",
        "requires_mineru",
        "requires_restic",
        "requires_wheel_build",
        "requires_desktop_stack",
    }
)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip :data:`_OPT_IN_MARKERS`-marked tests unless ``-m`` names them.

    The check is a substring test against the raw ``-m`` expression rather
    than a parsed one. That is sufficient for the two shapes the project
    documents — ``-m requires_restic`` (opt in) and ``-m "not eval"`` (opt
    out of something else) — and errs toward RUNNING a test when an exotic
    expression mentions the marker, which is the safe direction: a test that
    runs when it should have been skipped is visible, one that silently
    skips when it should have run is not.

    Per-test guards are left in place. Where a test also probes for its
    binary or env var, both fire and the skip reason may come from either;
    the outcome (skipped) is the same.
    """
    markexpr = str(config.getoption("markexpr", default="") or "")
    for item in items:
        for marker in _OPT_IN_MARKERS:
            if marker in item.keywords and marker not in markexpr:
                item.add_marker(
                    pytest.mark.skip(
                        reason=(
                            f"{marker}: opt-in only — run with "
                            f"`pytest -m {marker}` (see pyproject.toml "
                            f"[tool.pytest.ini_options].markers for the "
                            f"binary / env-var prerequisites)"
                        )
                    )
                )
                break


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
def _reset_session_state_for_tests():
    """Drop the per-MCP-session retrieval-cap registry before+after
    each test (E08_S04).

    The registry is a module-level singleton in ``server/session.py``.
    Without this fixture, a session's counter from a previous test
    leaks into the next one, producing non-deterministic behavior
    when two tests use the same Mcp-Session-Id (or none — both
    headerless test bodies are skip-cap paths but explicit reset is
    safer).

    Mirrors the discipline of ``_isolate_cache_state`` in
    ``tests/test_cache.py`` — both registries are process-lifetime
    singletons that demand explicit per-test isolation.
    """
    try:
        from server.session import reset_session_state_for_tests
    except ImportError:
        # ``server.session`` may not be importable from every test
        # environment (the module could fail to import if a future
        # refactor breaks an unrelated dep). The fixture must NEVER
        # break test collection; if the import fails we yield with
        # no-op cleanup and let the underlying test surface the bug.
        yield
        return
    reset_session_state_for_tests()
    yield
    reset_session_state_for_tests()


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


@pytest.fixture(autouse=True)
def _patched_operator_settings_db(tmp_path, monkeypatch):
    """Redirect ``server.operator_settings``'s default DB path into ``tmp_path``.

    Direct sibling of ``_patched_cache_db_path`` — same ``var/arxmcp/cache/``
    dir, same checkout-relative-path bug class. ``DEFAULT_DB_PATH`` is the
    real ``var/arxmcp/cache/notebooks.db``, where the operator's persisted
    ``contact_email`` lives. Without this fixture, any test that calls
    ``build_user_agent()`` / ``get_contact_email()`` without an explicit
    email reads that real value off disk. Because onboarding-uplift-m2
    inserted the SQLite source ABOVE the ``ARXMCP_CONTACT_EMAIL`` env var in
    ``build_user_agent``'s priority chain, the persisted email SHADOWS the
    env var those politeness-contract tests set via ``monkeypatch.setenv`` —
    so on any machine where ``make init`` has ever run, they fail (and,
    worse, quietly read operator PII). This fixture was simply missed when
    m2 landed; the env-var-only tests predate the SQLite source.

    ``DEFAULT_DB_PATH`` is consumed as a *default argument value*, which
    Python binds at function-definition time — rebinding the module global
    alone does NOT reach ``get_setting`` / ``get_contact_email`` et al. So
    we also re-point each reader/writer's ``__defaults__`` (mutating the
    shared function object, so every importer — including module-level
    ``from ... import get_contact_email`` in ``ingest/*`` — sees the
    redirect). An explicit ``db_path=`` arg still wins; monkeypatch restores
    everything after the test.
    """
    try:
        import server.operator_settings as ops
    except ImportError:
        # server.operator_settings may not be importable from every test
        # environment; the redirect is a no-op when it can't be imported.
        yield
        return
    fake = tmp_path / "cache" / "notebooks.db"
    monkeypatch.setattr(ops, "DEFAULT_DB_PATH", fake)
    # Each of these takes db_path as its sole default arg
    # (__defaults__ == (DEFAULT_DB_PATH,)); re-point it at the tmp file.
    # ingest-robustness-m1 AC3 added get_mineru_bin (read by
    # ingest/textbook_parser._resolve_mineru_binary) — it must be isolated too,
    # or a machine with a persisted mineru_bin leaks it into the resolver tests.
    for _name in (
        "get_setting",
        "set_setting",
        "delete_setting",
        "get_contact_email",
        "get_mineru_bin",
    ):
        monkeypatch.setattr(getattr(ops, _name), "__defaults__", (fake,))
    yield
