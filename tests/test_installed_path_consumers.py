"""Regression coverage for Config-owned installed-runtime writable paths."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP

from server.config import Config
from server.mcp_resources import (
    CORPUS_MANIFEST_URI,
    register_resources,
    reset_notebooks_store_for_tests,
    set_notebooks_store,
)
from server.notebooks_store import NotebooksStore
from server.routes.notebooks import router as notebooks_router
from server.routes.ui import router as ui_router
from server.tools import reset_resources_for_tests, set_resources
from tools import _notebook_common


def test_http_consumers_ignore_import_time_writable_roots(
    tmp_path: Path, monkeypatch
) -> None:
    """A Config data root wins even when legacy module globals are poisoned."""
    runtime_root = tmp_path / "runtime"
    poison = tmp_path / "poison"
    config = Config(data_dir=runtime_root)
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", poison / "notebooks")
    monkeypatch.setattr(
        _notebook_common, "CORPUS_PARSED_DIR", poison / "corpus" / "parsed"
    )

    loop = asyncio.new_event_loop()
    store = loop.run_until_complete(
        NotebooksStore.open(config.notebooks_db_path)
    )
    app = FastAPI()
    app.state.config = config
    app.state.notebooks_store = store
    app.include_router(notebooks_router, prefix="/ui/api")
    app.include_router(ui_router, prefix="/ui")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/ui/api/notebooks", json={"slug": "demo-nb"}
            )
            assert response.status_code == 201, response.text
            preview = (
                config.application_paths.notebooks
                / "demo-nb"
                / "ar5iv"
                / "2604.26204.html"
            )
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_text("<html>configured root</html>", encoding="utf-8")
            shown = client.get(
                "/ui/notebooks/demo-nb/papers/2604.26204/preview"
            )
            assert shown.status_code == 200
            assert "configured root" in shown.text
    finally:
        loop.run_until_complete(store.close())
        loop.close()

    assert (runtime_root / "notebooks" / "demo-nb").is_dir()
    assert not poison.exists()


def test_per_notebook_retrieval_uses_configured_base(
    tmp_path: Path, monkeypatch
) -> None:
    from server import resources as resources_module
    from server.resources import Resources, Singleflight

    config = Config(data_dir=tmp_path / "runtime")
    seen_bases: list[Path | None] = []

    def fake_notebook_path(slug: str, *, base: Path | None = None) -> Path:
        seen_bases.append(base)
        return (base or tmp_path / "wrong") / slug / "lancedb"

    monkeypatch.setattr(
        _notebook_common, "notebook_lancedb_path", fake_notebook_path
    )
    monkeypatch.setattr(
        resources_module,
        "read_corpus_version",
        lambda path: SimpleNamespace(version=7),
    )
    monkeypatch.setattr(
        resources_module,
        "open_chunks_table_with_fallback",
        lambda **kwargs: (SimpleNamespace(path=kwargs["lancedb_path"]), None),
    )
    resources = Resources(
        config=config,
        corpus_info=SimpleNamespace(version=1),
        chunks_table=None,
        embed_semaphore=asyncio.Semaphore(1),
        rerank_semaphore=asyncio.Semaphore(1),
        rerank_singleflight=Singleflight(),
    )

    asyncio.run(resources.notebook_table("demo-nb"))

    assert seen_bases == [config.application_paths.notebooks]


def test_mcp_resources_use_live_config_paths(
    tmp_path: Path, monkeypatch
) -> None:
    from server import corpus_manifest

    config = Config(data_dir=tmp_path / "runtime")
    poison = tmp_path / "poison-notebooks"
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", poison)
    seen: dict[str, Path | None] = {}

    async def fake_manifest(store, *, base=None, settings_db_path=None):
        seen["base"] = base
        seen["settings_db_path"] = settings_db_path
        return {"snapshot": {"notebooks": {}}}

    monkeypatch.setattr(corpus_manifest, "build_manifest", fake_manifest)

    async def exercise() -> None:
        store = await NotebooksStore.open(config.notebooks_db_path)
        await store.create_notebook(
            slug="demo-nb",
            display_name="Demo",
            lancedb_path="redacted",
            created_at="2026-08-06T00:00:00Z",
        )
        (config.application_paths.notebooks / "demo-nb" / "lancedb").mkdir(
            parents=True
        )
        set_resources(SimpleNamespace(config=config))
        set_notebooks_store(store)
        mcp = FastMCP("arxmcp", json_response=True)
        register_resources(mcp)
        try:
            detail = await mcp.read_resource("arxmcp://notebooks/demo-nb")
            assert '"is_ingested": true' in detail[0].content
            await mcp.read_resource(CORPUS_MANIFEST_URI)
        finally:
            await store.close()
            reset_notebooks_store_for_tests()
            reset_resources_for_tests()

    asyncio.run(exercise())

    assert seen == {
        "base": config.application_paths.notebooks,
        "settings_db_path": config.application_paths.notebooks_db,
    }
    assert not poison.exists()
