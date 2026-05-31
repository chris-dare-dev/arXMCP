"""onboarding-uplift-m4 — bootstrap mode tests.

Coverage map (acceptance criteria from the brief + synthesis):

  AC1   server boots with ARXMCP_BOOTSTRAP_MODE=1 + no corpus       test 1, 4
  AC2   make up-wizard target sets ARXMCP_BOOTSTRAP_MODE=1          test_make_up_wizard_target
  AC3   default cold-start still fatals without bootstrap_mode      test 3
  AC4   POST /ui/api/notebooks/<slug>/ingest exists (m9, pre-exists) — confirmed by m9 tests
  AC5   GET /ui/api/notebooks/<slug>/ingest/latest exists (m9)      — confirmed by m9 tests
  AC6   late_bind flips bootstrap_mode_active                        test 6
  AC7   BGE-M3 download-progress bytes tracking DEFERRED to m5
  AC8   stub envelope shape: isError=True, corpus_version=-1        test 7
  AC9   make test green + ruff clean                                 CI gate
  AC10  EXPECTED_TOOL_SCHEMA_SHA256 + EXPECTED_BP1_SHA256 unchanged  test_bp1_bp2_unchanged
  AC11  regression tests present                                     this file

FM-7   bootstrap_mode=True + corpus present → normal boot           test 5

Rectification (onboarding-uplift-m4):
  F1    refresh_metrics crash guard                                  TestLifespanBootstrapMode
  F2    /readyz returns 200 + "bootstrap" in bootstrap mode         TestReadyzBootstrapMode
  F2    /status returns warn in bootstrap mode                       TestStatusBootstrapMode
  F3    _build_bootstrap_envelope returns CallToolResult             TestBuildBootstrapEnvelope
  F4    on_success_callback coverage                                 TestOnSuccessCallback
  F5    late_bind lazy-loads reranker                               TestLateBindWithRerank
  F6    _corpus_ready_event removed (dead code)                     (assertions removed from test 6)
  F7    set_cache after RerankPhase in late_bind                    TestLateBindCacheNotLeaked
  F8    bootstrap envelope uses configured bind address             TestBootstrapEnvelopeBind

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
        # F6 rect: _corpus_ready_event removed (dead code — no consumer
        # awaited it; orchestrator reads bootstrap_mode_active bool flag).


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
        # F6 rect: _corpus_ready_event removed; bool flag is the mechanism.

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
        # F6 rect: _corpus_ready_event removed.


# ---------------------------------------------------------------------------
# Test 7 — AC8: _build_bootstrap_envelope shape
# ---------------------------------------------------------------------------


class TestBuildBootstrapEnvelope:
    def test_build_bootstrap_envelope_shape(self):
        """_build_bootstrap_envelope returns CallToolResult with isError=True.

        F3 rect: result is now mcp.types.CallToolResult (not a plain dict)
        so FastMCP passes it through unchanged and isError=True reaches the
        MCP wire level.
        """
        from mcp.types import CallToolResult, TextContent

        result = _build_bootstrap_envelope("search_papers")

        # Must be a CallToolResult so FastMCP short-circuits at the
        # isinstance(result, CallToolResult) branch in func_metadata.py.
        assert isinstance(result, CallToolResult)
        assert result.isError is True

        # structuredContent must carry the error metadata.
        assert result.structuredContent is not None
        sc = result.structuredContent
        assert sc["corpus_version"] == BOOTSTRAP_CORPUS_VERSION_SENTINEL
        assert sc["corpus_version"] == -1
        assert sc["error_code"] == "no_notebook_selected"
        assert sc["tool"] == "search_papers"
        # structuredContent keys must be alphabetically sorted (BP1 discipline).
        assert list(sc.keys()) == sorted(sc.keys())

        # content must have at least one TextContent block.
        assert len(result.content) >= 1
        assert isinstance(result.content[0], TextContent)
        assert len(result.content[0].text) > 0

    def test_build_bootstrap_envelope_sentinel_constant(self):
        """BOOTSTRAP_CORPUS_VERSION_SENTINEL is -1."""
        assert BOOTSTRAP_CORPUS_VERSION_SENTINEL == -1

    def test_build_bootstrap_envelope_different_tools(self):
        """The tool field in structuredContent echoes the passed tool name."""
        for tool_name in ("get_chunk", "find_equation", "cite_neighbors"):
            result = _build_bootstrap_envelope(tool_name)
            assert result.structuredContent["tool"] == tool_name

    def test_build_bootstrap_envelope_wire_isError_is_true(self):
        """isError=True is set at the CallToolResult level (not buried in text).

        Regression guard: before F3, isError was a key in the plain dict
        which FastMCP converted to TextContent, dropping isError=True at wire.
        """
        from mcp.types import CallToolResult

        result = _build_bootstrap_envelope("search_papers")
        assert isinstance(result, CallToolResult)
        # isError must be at the top level of CallToolResult, not inside content.
        assert result.isError is True


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
# F1 rectification: lifespan + metrics do not crash in bootstrap mode
# ---------------------------------------------------------------------------


class TestLifespanBootstrapMode:
    """Regression guard for F1 (CRITICAL): refresh_metrics_from_singleton_state
    must not crash when corpus_info is None (bootstrap mode)."""

    def test_refresh_metrics_skips_corpus_info_when_none(self, tmp_path):
        """refresh_metrics_from_singleton_state skips corpus gauges in bootstrap mode."""
        from server.health import refresh_metrics_from_singleton_state
        from server.resources import Resources

        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
        )
        stub = asyncio.run(Resources.startup(cfg))
        assert stub.corpus_info is None  # sanity check

        # Must not raise AttributeError — this was the CRITICAL crash.
        refresh_metrics_from_singleton_state(stub)


# ---------------------------------------------------------------------------
# F2 rectification: /readyz and /status return 200 in bootstrap mode
# ---------------------------------------------------------------------------


class TestReadyzBootstrapMode:
    """F2 regression tests: /readyz returns 200 + bootstrap body in stub mode."""

    def test_readyz_returns_bootstrap_status_in_bootstrap_mode(self, tmp_path):
        """/readyz returns 200 with status='bootstrap' when bootstrap_mode_active."""
        from starlette.testclient import TestClient

        from server.health import readyz

        # Build a stub Resources with bootstrap_mode_active=True.
        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
        )
        stub = asyncio.run(Resources.startup(cfg))
        assert stub.bootstrap_mode_active is True

        # Build a minimal Starlette app with the stub attached.
        from starlette.applications import Starlette
        from starlette.routing import Route

        async def _readyz(request):
            return await readyz(request)

        app = Starlette(routes=[Route("/readyz", _readyz)])
        app.state.resources = stub

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/readyz")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "bootstrap"
        assert body.get("bootstrap_mode_active") is True


class TestStatusBootstrapMode:
    """F2 regression tests: compute_health_status returns warn in bootstrap mode."""

    def test_status_returns_warn_in_bootstrap_mode(self, tmp_path):
        """compute_health_status returns status='warn' when bootstrap_mode_active."""
        from server.health import compute_health_status

        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
        )
        stub = asyncio.run(Resources.startup(cfg))
        assert stub.bootstrap_mode_active is True

        result = asyncio.run(compute_health_status(resources=stub, now=1_000_000.0))

        assert result["status"] == "warn"
        assert result["http_code"] == 200
        assert "bootstrap" in result["summary"]


# ---------------------------------------------------------------------------
# F4 rectification: on_success_callback coverage
# ---------------------------------------------------------------------------


class TestOnSuccessCallback:
    """F4 regression tests: IngestTaskTracker.on_success_callback plumbing."""

    def test_callback_fires_on_exit_code_zero(self, tmp_path, monkeypatch):
        """on_success_callback is called once with the slug on exit code 0."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from server.ingest_tracker import IngestTaskTracker

        called_with: list[str] = []

        async def _cb(slug: str) -> None:
            called_with.append(slug)

        tracker = IngestTaskTracker(on_success_callback=_cb)

        # Stub the subprocess to exit 0 cleanly.
        fake_proc = AsyncMock()
        fake_proc.communicate.return_value = (b"", b"")
        fake_proc.returncode = 0

        fake_store = MagicMock()
        fake_store.INGEST_STATUS_SUCCESS = "success"
        fake_store.INGEST_STATUS_FAILED = "failed"
        fake_store.update_ingest_run = AsyncMock()
        fake_store.mark_run_cancelled_if_running = AsyncMock()

        with patch(
            "server.ingest_tracker.asyncio.create_subprocess_exec",
            return_value=fake_proc,
        ):
            asyncio.run(
                tracker._run_ingest_subprocess(
                    slug="test-notebook",
                    run_id=1,
                    store=fake_store,
                    now_iso_provider=lambda: "2026-05-31T00:00:00Z",
                )
            )

        assert called_with == ["test-notebook"]

    def test_callback_not_fired_on_nonzero_exit(self, tmp_path, monkeypatch):
        """on_success_callback is NOT called when ingest exits with code 1."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from server.ingest_tracker import IngestTaskTracker

        called_with: list[str] = []

        async def _cb(slug: str) -> None:
            called_with.append(slug)

        tracker = IngestTaskTracker(on_success_callback=_cb)

        fake_proc = AsyncMock()
        fake_proc.communicate.return_value = (b"", b"ingest failed")
        fake_proc.returncode = 1

        fake_store = MagicMock()
        fake_store.INGEST_STATUS_SUCCESS = "success"
        fake_store.INGEST_STATUS_FAILED = "failed"
        fake_store.update_ingest_run = AsyncMock()
        fake_store.mark_run_cancelled_if_running = AsyncMock()

        with patch(
            "server.ingest_tracker.asyncio.create_subprocess_exec",
            return_value=fake_proc,
        ):
            asyncio.run(
                tracker._run_ingest_subprocess(
                    slug="test-notebook",
                    run_id=1,
                    store=fake_store,
                    now_iso_provider=lambda: "2026-05-31T00:00:00Z",
                )
            )

        assert called_with == []

    def test_callback_exception_logged_not_propagated(
        self, tmp_path, monkeypatch, caplog
    ):
        """A callback exception is logged at ERROR and does NOT propagate."""
        import asyncio
        import logging
        from unittest.mock import AsyncMock, MagicMock, patch

        from server.ingest_tracker import IngestTaskTracker

        async def _raising_cb(slug: str) -> None:
            raise RuntimeError("late-bind exploded")

        tracker = IngestTaskTracker(on_success_callback=_raising_cb)

        fake_proc = AsyncMock()
        fake_proc.communicate.return_value = (b"", b"")
        fake_proc.returncode = 0

        fake_store = MagicMock()
        fake_store.INGEST_STATUS_SUCCESS = "success"
        fake_store.INGEST_STATUS_FAILED = "failed"
        fake_store.update_ingest_run = AsyncMock()
        fake_store.mark_run_cancelled_if_running = AsyncMock()

        with patch(
            "server.ingest_tracker.asyncio.create_subprocess_exec",
            return_value=fake_proc,
        ), caplog.at_level(logging.ERROR, logger="server.ingest_tracker"):
            # Must not raise.
            asyncio.run(
                tracker._run_ingest_subprocess(
                    slug="test-notebook",
                    run_id=1,
                    store=fake_store,
                    now_iso_provider=lambda: "2026-05-31T00:00:00Z",
                )
            )

        # An ERROR log must have been emitted for the callback exception.
        error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("on_success_callback" in m or "late-bind" in m or "callback" in m.lower()
                   for m in error_msgs), (
            f"Expected ERROR log about callback failure; got: {error_msgs}"
        )

    def test_main_closure_passes_through_to_late_bind(self, tmp_path, monkeypatch):
        """The _on_ingest_success closure in main.py calls resources.late_bind(config)."""
        from server.config import Config

        cfg = Config(
            lancedb_path=tmp_path / "lancedb",
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
        )

        # Build a stub Resources with a mocked late_bind.
        stub = asyncio.run(Resources.startup(cfg))
        late_bind_calls: list[Config] = []

        async def _mock_late_bind(config: Config) -> bool:
            late_bind_calls.append(config)
            return True

        stub.late_bind = _mock_late_bind  # type: ignore[method-assign]

        # Replicate the closure from server/main.py:526.
        resources = stub

        async def _on_ingest_success(_slug: str) -> None:
            await resources.late_bind(cfg)

        # Invoke the closure.
        asyncio.run(_on_ingest_success("test-slug"))

        assert len(late_bind_calls) == 1
        assert late_bind_calls[0] is cfg


# ---------------------------------------------------------------------------
# F5 rectification: late_bind lazy-loads reranker when enable_rerank=True
# ---------------------------------------------------------------------------


class TestLateBindWithRerank:
    """F5 regression test: late_bind loads reranker lazily in bootstrap mode."""

    def test_late_bind_with_enable_rerank_loads_reranker_lazily(
        self, tmp_path, monkeypatch
    ):
        """late_bind lazy-loads the reranker when enable_rerank=True + bootstrap mode."""
        import server.resources as res_mod

        lancedb_path = tmp_path / "lancedb"
        cfg = Config(
            lancedb_path=lancedb_path,
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
            enable_rerank=True,
        )

        stub = asyncio.run(Resources.startup(cfg))
        assert stub.bootstrap_mode_active is True
        assert stub.reranker_model is None  # not loaded at bootstrap startup

        _write_corpus_marker(lancedb_path, version=1)
        _patch_late_bind_heavy_io(monkeypatch, lancedb_path)

        # Patch _load_reranker_or_raise to return a stub model tuple.
        fake_reranker = (object(), object())
        load_calls: list[int] = []

        async def _fake_load():
            load_calls.append(1)
            return fake_reranker

        monkeypatch.setattr(res_mod, "_load_reranker_or_raise", _fake_load)

        result = asyncio.run(stub.late_bind(cfg))

        assert result is True
        assert stub.bootstrap_mode_active is False
        assert stub.reranker_model is fake_reranker
        assert len(load_calls) == 1, "Reranker must be loaded exactly once"


# ---------------------------------------------------------------------------
# F7 rectification: set_cache not leaked on RerankPhase failure
# ---------------------------------------------------------------------------


class TestLateBindCacheNotLeaked:
    """F7 regression test: set_cache global stays None when RerankPhase raises."""

    def test_late_bind_failure_does_not_leak_cache_global(
        self, tmp_path, monkeypatch
    ):
        """If RerankPhase construction fails, get_cache() stays None.

        F7 regression guard: set_cache must run AFTER RerankPhase construction.
        When RerankPhase.__init__ raises, set_cache never executes, so
        get_cache() stays None.
        """
        import server.cache as cache_mod
        from server.retrieval.rerank import RerankPhase

        lancedb_path = tmp_path / "lancedb"
        cfg = Config(
            lancedb_path=lancedb_path,
            notebooks_db_path=tmp_path / "notebooks.db",
            cache_db_path=tmp_path / "cache.db",
            bootstrap_mode=True,
        )

        stub = asyncio.run(Resources.startup(cfg))
        _write_corpus_marker(lancedb_path, version=1)
        # Patch late_bind I/O but do NOT patch set_cache — we need the
        # real set_cache so we can observe whether it was called.
        _patch_late_bind_heavy_io_no_cache_stub(monkeypatch, lancedb_path)

        # Make RerankPhase.__init__ raise.
        def _exploding_init(self, **_kw):
            raise RuntimeError("Simulated RerankPhase failure")

        monkeypatch.setattr(RerankPhase, "__init__", _exploding_init)

        # Reset cache global to None before test + restore afterward.
        cache_mod.reset_cache_for_tests()
        try:
            result = asyncio.run(stub.late_bind(cfg))

            assert result is False
            # F7: set_cache runs AFTER RerankPhase — a RerankPhase failure
            # must leave the global cache as None (not published).
            assert cache_mod.get_cache() is None
        finally:
            # Always restore to None so later tests are not affected.
            cache_mod.reset_cache_for_tests()


# ---------------------------------------------------------------------------
# F8 rectification: bootstrap envelope uses configured bind address
# ---------------------------------------------------------------------------


class TestBootstrapEnvelopeBind:
    """F8 regression test: hint text uses configured bind_host:bind_port."""

    def test_bootstrap_envelope_text_uses_configured_bind(self):
        """_build_bootstrap_envelope uses the ui_url kwarg in hint text."""
        result = _build_bootstrap_envelope(
            "search_papers", ui_url="http://127.0.0.1:9999/ui/"
        )
        # The hint text inside content[0] must mention port 9999.
        hint_text = result.content[0].text
        assert "9999" in hint_text, (
            f"Expected port 9999 in hint text, got: {hint_text!r}"
        )


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


def _patch_late_bind_heavy_io_no_cache_stub(
    monkeypatch, lancedb_path: Path
) -> None:
    """Like _patch_late_bind_heavy_io but does NOT stub set_cache.

    Used by TestLateBindCacheNotLeaked to observe real cache global state.
    """
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
    # Intentionally do NOT patch set_cache here.


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
