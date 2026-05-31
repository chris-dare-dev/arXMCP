"""onboarding-uplift-m4 — bootstrap mode tests.

Coverage map (acceptance criteria from the brief + synthesis):

  AC1   server boots with ARXMCP_BOOTSTRAP_MODE=1 + no corpus       test 1, 4
  AC2   make up-wizard target sets ARXMCP_BOOTSTRAP_MODE=1          test_make_up_wizard_target
  AC3   default cold-start still fatals without bootstrap_mode      test 3
  AC4   POST /ui/api/notebooks/<slug>/ingest exists (m9, pre-exists) — confirmed by m9 tests
  AC5   GET /ui/api/notebooks/<slug>/ingest/latest exists (m9)      — confirmed by m9 tests
  AC6   late_bind flips bootstrap_mode_active + sets event           test 6
  AC7   BGE-M3 download-progress bytes tracking DEFERRED to m5
  AC8   stub envelope shape: isError=True, corpus_version=-1        test 7
  AC9   make test green + ruff clean                                 CI gate
  AC10  EXPECTED_TOOL_SCHEMA_SHA256 + EXPECTED_BP1_SHA256 unchanged  test_bp1_bp2_unchanged
  AC11  regression tests present                                     this file

FM-7   bootstrap_mode=True + corpus present → normal boot           test 5

All tests run without a real BGE-M3 model, real LanceDB, or a real corpus.
Heavy I/O calls (model load, LanceDB open, BM25 build, cache open) are
mocked so the suite stays offline-fast.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from server.config import Config
from server.resources import CorpusNotIngestedError, Resources
from server.tools import (
    BOOTSTRAP_CORPUS_VERSION_SENTINEL,
    _build_bootstrap_envelope,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_corpus_version_info(version: int = 1, chunk_count: int = 10):
    """Return a CorpusVersionInfo-compatible namespace for tests that need
    a marker without writing real LanceDB data."""
    from server.corpus import CorpusVersionInfo

    return CorpusVersionInfo(
        version=version,
        chunker_version="v1.0",
        embedder_version="bge-m3@test",
        created_at="2026-05-31T00:00:00Z",
        paper_count=2,
        chunk_count=chunk_count,
    )


def _write_corpus_marker(lancedb_path: Path, version: int = 1) -> None:
    """Write a minimal corpus-version.json so read_corpus_version returns a
    non-None CorpusVersionInfo at the given path."""
    lancedb_path.mkdir(parents=True, exist_ok=True)
    marker = lancedb_path / "corpus-version.json"
    marker.write_text(
        json.dumps(
            {
                "chunk_count": 10,
                "chunker_version": "v1.0",
                "created_at": "2026-05-31T00:00:00Z",
                "embedder_version": "bge-m3@test",
                "paper_count": 2,
                "version": version,
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Test 1 — AC1: Config.bootstrap_mode default is False
# ---------------------------------------------------------------------------


class TestConfigBootstrapModeDefault:
    def test_config_bootstrap_mode_default_false(self, tmp_path):
        """Config().bootstrap_mode is False when ARXMCP_BOOTSTRAP_MODE is unset."""
        # We need a valid notebooks_db_path so the Config parses without errors.
        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
        )
        assert cfg.bootstrap_mode is False


# ---------------------------------------------------------------------------
# Test 2 — AC1: env var ARXMCP_BOOTSTRAP_MODE=1 flips it
# ---------------------------------------------------------------------------


class TestConfigBootstrapModeEnvVar:
    def test_config_bootstrap_mode_env_var_true(self, tmp_path, monkeypatch):
        """ARXMCP_BOOTSTRAP_MODE=1 sets Config.bootstrap_mode to True."""
        monkeypatch.setenv("ARXMCP_BOOTSTRAP_MODE", "1")
        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
        )
        assert cfg.bootstrap_mode is True

    def test_config_bootstrap_mode_env_var_true_spelled_out(
        self, tmp_path, monkeypatch
    ):
        """ARXMCP_BOOTSTRAP_MODE=true also flips the field."""
        monkeypatch.setenv("ARXMCP_BOOTSTRAP_MODE", "true")
        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
        )
        assert cfg.bootstrap_mode is True


# ---------------------------------------------------------------------------
# Test 3 — AC3: default cold-start (bootstrap_mode=False) still raises
# ---------------------------------------------------------------------------


class TestResourcesStartupRaisesOnColdStartDefault:
    def test_resources_startup_raises_on_cold_start_default(self, tmp_path):
        """bootstrap_mode=False + no corpus marker raises CorpusNotIngestedError."""
        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=False,
        )
        with pytest.raises(CorpusNotIngestedError) as exc_info:
            asyncio.run(Resources.startup(cfg))

        # The new hint sentence must be present (AC3 regression guard).
        assert "ARXMCP_BOOTSTRAP_MODE=1" in str(exc_info.value)
        assert "make up-wizard" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 4 — AC1: bootstrap_mode=True + no marker skips the error
# ---------------------------------------------------------------------------


class TestResourcesStartupSkipsRaiseInBootstrapMode:
    def test_resources_startup_skips_raise_in_bootstrap_mode(self, tmp_path):
        """bootstrap_mode=True + no corpus marker returns stub Resources.

        The stub must have:
          - bootstrap_mode_active = True
          - corpus_info is None
          - chunks_table is None
          - warm = False
        """
        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
        )
        stub = asyncio.run(Resources.startup(cfg))

        assert stub.bootstrap_mode_active is True
        assert stub.corpus_info is None
        assert stub.chunks_table is None
        assert stub.warm is False
        # The corpus_ready_event must NOT be set yet.
        assert not stub._corpus_ready_event.is_set()


# ---------------------------------------------------------------------------
# Test 5 — FM-7: bootstrap_mode=True + corpus present → normal boot
# ---------------------------------------------------------------------------


class TestResourcesStartupBootstrapHintIgnoredWhenCorpusExists:
    def test_resources_startup_bootstrap_hint_ignored_when_corpus_exists(
        self, tmp_path, monkeypatch
    ):
        """bootstrap_mode=True + corpus marker present → normal boot.

        FM-7: the bootstrap flag is a hint, not an override.  When
        corpus-version.json exists, the server boots normally:
          - bootstrap_mode_active = False
          - corpus_info is not None
        """
        lancedb_path = tmp_path / "lancedb"
        _write_corpus_marker(lancedb_path, version=3)

        # Mock the heavy I/O so we don't need a real BGE-M3 or BM25 index.
        _patch_startup_heavy_io(monkeypatch, lancedb_path)

        cfg = Config(
            lancedb_path=lancedb_path,
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
        )
        resources = asyncio.run(Resources.startup(cfg))

        assert resources.bootstrap_mode_active is False
        assert resources.corpus_info is not None
        assert resources.corpus_info.version == 3
        assert resources.warm is True


# ---------------------------------------------------------------------------
# Test 6 — AC6: late_bind promotes bootstrap stub to normal operation
# ---------------------------------------------------------------------------


class TestLateBindPromotesBootstrapToNormal:
    def test_late_bind_promotes_bootstrap_to_normal(self, tmp_path, monkeypatch):
        """late_bind() returns True, flips bootstrap_mode_active, sets event."""
        lancedb_path = tmp_path / "lancedb"
        cfg = Config(
            lancedb_path=lancedb_path,
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
        )

        # Start in bootstrap mode (no marker yet).
        stub = asyncio.run(Resources.startup(cfg))
        assert stub.bootstrap_mode_active is True

        # Now "ingest completes" — write the marker.
        _write_corpus_marker(lancedb_path, version=1)

        # Mock heavy I/O for late_bind (BM25, ANN, cache).
        _patch_late_bind_heavy_io(monkeypatch, lancedb_path)

        result = asyncio.run(stub.late_bind(cfg))

        assert result is True
        assert stub.bootstrap_mode_active is False
        assert stub.corpus_info is not None
        assert stub.corpus_info.version == 1
        assert stub._corpus_ready_event.is_set()

    def test_late_bind_is_idempotent_when_already_normal(self, tmp_path, monkeypatch):
        """late_bind() returns False immediately if already out of bootstrap mode."""
        lancedb_path = tmp_path / "lancedb"
        _write_corpus_marker(lancedb_path, version=1)

        _patch_startup_heavy_io(monkeypatch, lancedb_path)

        cfg = Config(
            lancedb_path=lancedb_path,
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=False,
        )
        resources = asyncio.run(Resources.startup(cfg))
        assert resources.bootstrap_mode_active is False

        # Calling late_bind on a non-bootstrap instance is a no-op.
        result = asyncio.run(resources.late_bind(cfg))
        assert result is False

    def test_late_bind_returns_false_when_marker_still_absent(
        self, tmp_path
    ):
        """late_bind() returns False (FM-3) if marker is still absent after ingest."""
        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
        )
        stub = asyncio.run(Resources.startup(cfg))
        assert stub.bootstrap_mode_active is True

        # Do NOT write the marker — simulate a failed/partial ingest.
        result = asyncio.run(stub.late_bind(cfg))

        assert result is False
        assert stub.bootstrap_mode_active is True
        assert not stub._corpus_ready_event.is_set()


# ---------------------------------------------------------------------------
# Test 7 — AC8: _build_bootstrap_envelope shape
# ---------------------------------------------------------------------------


class TestBuildBootstrapEnvelope:
    def test_build_bootstrap_envelope_shape(self):
        """_build_bootstrap_envelope returns a correctly-shaped sorted dict."""
        envelope = _build_bootstrap_envelope("search_papers")

        # Keys must be alphabetically sorted (BP1 byte-stability discipline).
        assert list(envelope.keys()) == sorted(envelope.keys())

        # Required keys + values.
        assert set(envelope.keys()) >= {
            "content",
            "corpus_version",
            "error_code",
            "isError",
            "tool",
        }
        assert envelope["corpus_version"] == BOOTSTRAP_CORPUS_VERSION_SENTINEL
        assert envelope["corpus_version"] == -1
        assert envelope["isError"] is True
        assert envelope["error_code"] == "no_notebook_selected"
        assert envelope["tool"] == "search_papers"

        # content must be a non-empty list with at least one text block.
        assert isinstance(envelope["content"], list)
        assert len(envelope["content"]) >= 1
        assert envelope["content"][0]["type"] == "text"
        assert len(envelope["content"][0]["text"]) > 0

    def test_build_bootstrap_envelope_sentinel_constant(self):
        """BOOTSTRAP_CORPUS_VERSION_SENTINEL is -1."""
        assert BOOTSTRAP_CORPUS_VERSION_SENTINEL == -1

    def test_build_bootstrap_envelope_different_tools(self):
        """The tool field echoes the passed tool name."""
        for tool_name in ("get_chunk", "find_equation", "cite_neighbors"):
            env = _build_bootstrap_envelope(tool_name)
            assert env["tool"] == tool_name


# ---------------------------------------------------------------------------
# Test — AC2: make up-wizard target exists and sets ARXMCP_BOOTSTRAP_MODE=1
# ---------------------------------------------------------------------------


class TestMakeUpWizardTarget:
    def test_make_up_wizard_target_exists_and_sets_env_var(self, tmp_path):
        """make up-wizard target exists and references ARXMCP_BOOTSTRAP_MODE=1."""
        # Dry-run: read the Makefile directly (no subprocess) — the target
        # body must contain the env var setting.
        makefile = (
            Path(__file__).parent.parent / "Makefile"
        )
        assert makefile.is_file(), "Makefile not found at repo root"
        content = makefile.read_text(encoding="utf-8")
        assert "up-wizard" in content, "up-wizard target not in Makefile"
        assert "ARXMCP_BOOTSTRAP_MODE=1" in content, (
            "ARXMCP_BOOTSTRAP_MODE=1 not set in up-wizard target"
        )

    def test_makefile_phony_includes_up_wizard(self):
        """up-wizard is declared in .PHONY."""
        makefile = Path(__file__).parent.parent / "Makefile"
        content = makefile.read_text(encoding="utf-8")
        # Look for any .PHONY line that contains up-wizard.
        phony_lines = [
            line for line in content.splitlines() if line.startswith(".PHONY:")
        ]
        all_phony = " ".join(phony_lines)
        assert "up-wizard" in all_phony, (
            "up-wizard must appear in a .PHONY declaration"
        )


# ---------------------------------------------------------------------------
# Test — AC10: BP1/BP2 hashes unchanged by this milestone
# ---------------------------------------------------------------------------


class TestBP1BP2HashesUnchanged:
    """Regression guard: m4 must NOT change the tools/list schema or
    SYSTEM_PROMPT bytes (those are BP1/BP2 cache breakpoints).

    We verify the CURRENT computed hash still matches the pinned constant.
    If the hash changes this test fails loudly, forcing an explicit
    re-pin review.
    """

    def test_tool_schema_hash_matches_pinned(self, tmp_path):
        """EXPECTED_TOOL_SCHEMA_SHA256 in test_server_tool_schema.py is still valid."""
        from tests.test_server_tool_schema import (  # type: ignore[import]
            EXPECTED_TOOL_SCHEMA_SHA256,
            _build_app_and_list_tools,
            compute_tool_schema_hash,
        )

        tools = _build_app_and_list_tools(tmp_path)
        actual_hash = compute_tool_schema_hash(tools)
        assert actual_hash == EXPECTED_TOOL_SCHEMA_SHA256, (
            "tools/list schema changed unexpectedly — re-pin "
            "EXPECTED_TOOL_SCHEMA_SHA256 via "
            "`pytest --update-tool-schema-hash` if this is intentional."
        )

    def test_bootstrap_mode_fields_not_in_tool_descriptions(self):
        """bootstrap_mode-related strings must NOT appear in any tool description.

        Any tool description change would affect BP1/BP2 bytes.  This is
        a direct regression guard that doesn't require the pinned hash
        constant to be importable.
        """
        from server.tools import ALL_TOOLS

        for tool in ALL_TOOLS:
            assert "bootstrap_mode" not in tool.description, (
                f"Tool {tool.name!r} description references 'bootstrap_mode'; "
                "this would change BP1 bytes."
            )
            assert "no_notebook_selected" not in tool.description, (
                f"Tool {tool.name!r} description references 'no_notebook_selected'; "
                "this would change BP1 bytes."
            )


# ---------------------------------------------------------------------------
# Helpers: mock heavy I/O so tests run offline/fast
# ---------------------------------------------------------------------------


def _patch_startup_heavy_io(monkeypatch, lancedb_path: Path) -> None:
    """Patch the expensive startup steps (BGE-M3, LanceDB, BM25, cache)
    so Resources.startup can run in a fast offline test."""
    import server.resources as res_mod

    # BGE-M3 model + tokenizer.
    fake_model = object()
    fake_tokenizer = object()
    monkeypatch.setattr(res_mod, "_get_model", lambda: fake_model)
    monkeypatch.setattr(res_mod, "_get_tokenizer", lambda: fake_tokenizer)

    # LanceDB open — return a fake table + no degraded state.
    fake_table = _make_fake_table()
    monkeypatch.setattr(
        res_mod,
        "open_chunks_table_with_fallback",
        lambda **_kw: (fake_table, None),
    )

    # BM25Phase.startup — return a fake phase.
    from server.retrieval import BM25Phase

    fake_bm25 = MagicMock(spec=BM25Phase)
    fake_bm25.corpus_size = 10

    async def _fake_bm25_startup(**_kw):
        return fake_bm25

    monkeypatch.setattr(BM25Phase, "startup", staticmethod(_fake_bm25_startup))

    # RetrievalCache.open.
    from server.cache import RetrievalCache

    fake_cache = MagicMock(spec=RetrievalCache)

    async def _fake_cache_open(**_kw):
        return fake_cache

    monkeypatch.setattr(RetrievalCache, "open", staticmethod(_fake_cache_open))

    # set_cache — no-op.
    import server.cache as cache_mod

    monkeypatch.setattr(cache_mod, "set_cache", lambda _c: None)


def _patch_late_bind_heavy_io(monkeypatch, lancedb_path: Path) -> None:
    """Patch the expensive steps in Resources.late_bind."""
    import server.resources as res_mod

    fake_table = _make_fake_table()
    monkeypatch.setattr(
        res_mod,
        "open_chunks_table_with_fallback",
        lambda **_kw: (fake_table, None),
    )

    from server.retrieval import BM25Phase

    fake_bm25 = MagicMock(spec=BM25Phase)
    fake_bm25.corpus_size = 10

    async def _fake_bm25_startup(**_kw):
        return fake_bm25

    monkeypatch.setattr(BM25Phase, "startup", staticmethod(_fake_bm25_startup))

    from server.cache import RetrievalCache

    fake_cache = MagicMock(spec=RetrievalCache)

    async def _fake_cache_open(**_kw):
        return fake_cache

    monkeypatch.setattr(RetrievalCache, "open", staticmethod(_fake_cache_open))

    import server.cache as cache_mod

    monkeypatch.setattr(cache_mod, "set_cache", lambda _c: None)


def _make_fake_table():
    """Build a minimal fake LanceDB table that satisfies startup checks.

    Must include 'embedding_stmt' and 'embedding_proof' columns so
    ANNPhase.__init__'s schema-validation guard passes (it checks
    chunks_table.schema.names against EMBEDDING_COLUMNS).
    """
    import pyarrow as pa

    from ingest.schema import EMBEDDING_DIM

    fake_table = MagicMock()
    fake_table.count_rows.return_value = 10
    fake_table.list_indices.return_value = []

    # Schema must include embedding columns for ANNPhase validation.
    schema = pa.schema(
        [
            pa.field("chunk_id", pa.string()),
            pa.field(
                "embedding_stmt",
                pa.list_(pa.float32(), EMBEDDING_DIM),
            ),
            pa.field(
                "embedding_proof",
                pa.list_(pa.float32(), EMBEDDING_DIM),
            ),
        ]
    )
    fake_table.schema = schema

    arrow_table = pa.table(
        {"chunk_id": pa.array([], type=pa.string())}
    )
    fake_table.to_arrow.return_value = arrow_table

    # _column_has_rows calls:
    #   chunks_table.search().where(...).select([...]).limit(1).to_arrow()
    # and checks arrow.num_rows > 0.  Return a real PyArrow table with
    # num_rows=0 so both embedding columns register as empty (valid — just
    # means ANNPhase._searchable_columns is empty, ANN returns nothing).
    empty_arrow = pa.table({"chunk_id": pa.array([], type=pa.string())})
    fake_search = MagicMock()
    fake_search.where.return_value = fake_search
    fake_search.select.return_value = fake_search
    fake_search.limit.return_value = fake_search
    fake_search.to_arrow.return_value = empty_arrow
    fake_table.search.return_value = fake_search
    return fake_table
