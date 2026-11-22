"""``ARXMCP_BM25_PHASE`` decides whether the server loads the BM25 phase.

No served tool reads BM25, so the default (``auto``) leaves it off: neither
corpus bind loads the artifact or scans the chunk_id column for its
cross-check, and ``/readyz`` and ``/status`` say ``disabled`` rather than
reporting it cold. With the phase on, both binds run the cross-check against
the live table, and the hybrid eval harness turns it on for its own run.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arxmcp.settings import Config


def _rows(start: int, count: int) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": f"c{i}",
            "paper_id": f"p{i}",
            "kind": "section",
            "section_path": ["1"],
            "theorem_name": None,
            "theorem_label": None,
            "body_text": "body",
            "body_tokens": "body",
            "embedding_stmt": [0.1] * 1024,
            "embedding_proof": None,
            "embedding_eq": None,
            "chunker_version": "test",
            "embedder_version": "test",
            "preamble_ref": None,
        }
        for i in range(start, start + count)
    ]


def _write_marker(lance: Path, *, version: int, chunk_count: int) -> None:
    from arxmcp.ingest.embedder import EMBEDDER_VERSION

    (lance / "corpus-version.json").write_text(
        json.dumps(
            {
                "version": version,
                "chunker_version": "test",
                "embedder_version": EMBEDDER_VERSION,
                "created_at": "2026-08-23T00:00:00Z",
                "paper_count": chunk_count,
                "chunk_count": chunk_count,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A three-chunk v1 corpus, BGE-M3 stubbed, BM25 loads recorded."""
    import lancedb
    import pyarrow as pa

    import arxmcp.server.cache as cache_mod
    import arxmcp.server.query_encoder as qe_mod
    import arxmcp.server.resources as res_mod
    from arxmcp.ingest.schema import CHUNKS_SCHEMA_V1
    from arxmcp.server.retrieval import BM25Phase

    lance = tmp_path / "lancedb"
    table = lancedb.connect(str(lance)).create_table(
        "chunks", data=pa.Table.from_pylist(_rows(0, 3), schema=CHUNKS_SCHEMA_V1)
    )
    _write_marker(lance, version=1, chunk_count=3)

    monkeypatch.setattr(res_mod, "open_chunks_table_with_fallback", lambda **_kw: (table, None))
    monkeypatch.setattr(cache_mod, "set_cache", lambda _c: None)
    monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
    monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())

    bm25_calls: list[dict[str, Any]] = []
    real_startup = BM25Phase.startup

    async def _recording_startup(**kwargs: Any) -> Any:
        bm25_calls.append(kwargs)
        return await real_startup(**kwargs)

    monkeypatch.setattr(BM25Phase, "startup", _recording_startup)

    scanned_columns: list[str] = []
    real_project = res_mod.project_column

    def _recording_project(tbl: Any, column: str, **kwargs: Any) -> Any:
        scanned_columns.append(column)
        return real_project(tbl, column, **kwargs)

    monkeypatch.setattr(res_mod, "project_column", _recording_project)

    def _config(**overrides: Any) -> Config:
        return Config(
            lancedb_path=lance,
            notebooks_db_path=tmp_path / "nb.db",
            cache_db_path=tmp_path / "cache.db",
            bm25_index_root=tmp_path / "bm25",
            enable_rerank=False,
            **overrides,
        )

    return {
        "config": _config,
        "table": table,
        "lance": lance,
        "bm25_calls": bm25_calls,
        "scanned_columns": scanned_columns,
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_is_auto_and_resolves_off(self, monkeypatch) -> None:
        monkeypatch.delenv("ARXMCP_BM25_PHASE", raising=False)
        cfg = Config()
        assert cfg.bm25_phase == "auto"
        assert cfg.bm25_phase_enabled is False

    @pytest.mark.parametrize(
        ("raw", "mode", "enabled"),
        [("on", "on", True), ("OFF", "off", False), (" Auto ", "auto", False)],
    )
    def test_env_var_is_read_and_normalized(
        self, monkeypatch, raw: str, mode: str, enabled: bool
    ) -> None:
        monkeypatch.setenv("ARXMCP_BM25_PHASE", raw)
        cfg = Config()
        assert cfg.bm25_phase == mode
        assert cfg.bm25_phase_enabled is enabled

    def test_unknown_mode_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="ARXMCP_BM25_PHASE"):
            Config(bm25_phase="hybrid")


# ---------------------------------------------------------------------------
# Corpus binds
# ---------------------------------------------------------------------------


def test_default_startup_and_rebind_skip_the_phase(corpus) -> None:
    import pyarrow as pa

    from arxmcp.ingest.schema import CHUNKS_SCHEMA_V1
    from arxmcp.server.resources import Resources

    async def _scenario() -> tuple[Any, str, bool, int]:
        resources = await Resources.startup(corpus["config"]())
        try:
            at_boot = (resources.bm25_phase, resources.bm25_phase_state)
            corpus["table"].add(pa.Table.from_pylist(_rows(3, 3), schema=CHUNKS_SCHEMA_V1))
            _write_marker(corpus["lance"], version=2, chunk_count=6)
            landed = await resources.refresh_corpus_if_stale(force=True)
            if resources.corpus_info is None:
                raise RuntimeError("rebind left the instance unbound")
            if resources.bm25_phase is not None:
                raise RuntimeError("the rebind loaded a disabled phase")
            return (*at_boot, landed, resources.corpus_info.version)
        finally:
            await resources.shutdown()

    phase, state, landed, version = asyncio.run(_scenario())
    assert phase is None
    assert state == "disabled"
    assert landed is True and version == 2
    assert corpus["bm25_calls"] == []
    assert "chunk_id" not in corpus["scanned_columns"]


def test_enabled_binds_cross_check_against_the_live_table(corpus) -> None:
    import pyarrow as pa

    from arxmcp.ingest.schema import CHUNKS_SCHEMA_V1
    from arxmcp.server.resources import Resources

    async def _scenario() -> tuple[str, str]:
        resources = await Resources.startup(corpus["config"](bm25_phase="on"))
        try:
            at_boot = resources.bm25_phase_state
            corpus["table"].add(pa.Table.from_pylist(_rows(3, 2), schema=CHUNKS_SCHEMA_V1))
            _write_marker(corpus["lance"], version=2, chunk_count=5)
            if not await resources.refresh_corpus_if_stale(force=True):
                raise RuntimeError("the v2 rebind did not land")
            return at_boot, resources.bm25_phase_state
        finally:
            await resources.shutdown()

    at_boot, after_rebind = asyncio.run(_scenario())
    assert (at_boot, after_rebind) == ("warm", "warm")
    assert [call["live_chunk_ids"] for call in corpus["bm25_calls"]] == [
        {"c0", "c1", "c2"},
        {"c0", "c1", "c2", "c3", "c4"},
    ]


def test_enabled_phase_with_a_stale_artifact_reads_unavailable(corpus) -> None:
    """A v1 artifact naming a chunk the table no longer has fails the
    cross-check: the phase stays unloaded and says so."""
    from arxmcp.ingest.bm25_indexer import build_bm25_index
    from arxmcp.server.resources import Resources

    cfg = corpus["config"](bm25_phase="on")
    build_bm25_index(cfg.lancedb_path, corpus_version=1, index_root=cfg.bm25_index_root)
    corpus["table"].delete("chunk_id = 'c2'")
    _write_marker(corpus["lance"], version=1, chunk_count=2)

    async def _scenario() -> tuple[Any, str]:
        resources = await Resources.startup(cfg)
        try:
            return resources.bm25_phase, resources.bm25_phase_state
        finally:
            await resources.shutdown()

    phase, state = asyncio.run(_scenario())
    assert phase is None
    assert state == "unavailable"
    assert corpus["bm25_calls"][0]["live_chunk_ids"] == {"c0", "c1"}


# ---------------------------------------------------------------------------
# /readyz and /status
# ---------------------------------------------------------------------------


def _readyz_body(resources: Any) -> dict[str, Any]:
    from arxmcp.server.health import router

    app = FastAPI()
    app.include_router(router)
    app.state.resources = resources
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [({}, "disabled"), ({"bm25_phase": "on"}, "warm")],
)
def test_readyz_reports_the_phase_state(corpus, overrides, expected) -> None:
    from arxmcp.server.resources import Resources

    resources = asyncio.run(Resources.startup(corpus["config"](**overrides)))
    try:
        body = _readyz_body(resources)
    finally:
        asyncio.run(resources.shutdown())
    assert body["bm25_phase"] == expected
    assert set(body["warm"]) == {"embedder", "lancedb", "reranker"}


class _StatusResources:
    def __init__(self, tmp_path: Path, bm25_state: str) -> None:
        self.warm = True
        self.degraded = None
        self.corpus_info = SimpleNamespace(version=3, chunk_count=10)
        self.process_start_time_seconds = time.time() - 60
        self.config = SimpleNamespace(data_dir=tmp_path, ops_dir=tmp_path)
        self.bm25_phase_state = bm25_state

    def is_resource_warm(self, name: str) -> bool:
        return name != "reranker"


@pytest.mark.parametrize(
    ("state", "check_status", "warns"),
    [("disabled", "pass", False), ("warm", "pass", False), ("unavailable", "warn", True)],
)
def test_status_reports_the_phase_and_warns_only_when_it_failed(
    tmp_path, state: str, check_status: str, warns: bool
) -> None:
    from arxmcp.server.health import compute_health_status

    report = asyncio.run(compute_health_status(_StatusResources(tmp_path, state), None))
    (check,) = report["checks"]["bm25:phase"]
    assert check["observedValue"] == state
    assert check["status"] == check_status
    assert ("bm25 unavailable" in report["summary"]) is warns


# ---------------------------------------------------------------------------
# Hybrid eval harness
# ---------------------------------------------------------------------------


def test_hybrid_eval_turns_the_phase_on_and_refuses_without_it(
    monkeypatch,
) -> None:
    """``ARXMCP_BM25_PHASE=off`` in the shell does not stop a hybrid run
    from requesting the phase, and a phase that did not load stops the run
    rather than scoring a pipeline with no BM25 stage."""
    from arxmcp.ops.retrieval_eval import run_hybrid_against_corpus
    from arxmcp.server.resources import Resources

    monkeypatch.setenv("ARXMCP_BM25_PHASE", "off")
    seen: list[Config] = []
    shut_down: list[bool] = []

    async def _fake_shutdown() -> None:
        shut_down.append(True)

    async def _fake_startup(cfg: Config) -> Any:
        seen.append(cfg)
        return SimpleNamespace(
            bm25_phase=None,
            bm25_phase_state="unavailable",
            shutdown=_fake_shutdown,
        )

    monkeypatch.setattr(Resources, "startup", staticmethod(_fake_startup))

    async def _never_encode(_text: str) -> Any:
        raise AssertionError("no query may run without the BM25 phase")

    with pytest.raises(RuntimeError, match="needs the BM25 phase"):
        run_hybrid_against_corpus(
            [{"query_id": "q1", "query_text": "x", "relevant_chunks": []}],
            None,
            _never_encode,
            corpus_version=1,
            rerank_enabled=False,
        )
    assert [cfg.bm25_phase_enabled for cfg in seen] == [True]
    assert shut_down == [True]
