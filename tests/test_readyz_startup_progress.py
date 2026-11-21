"""``/readyz`` names the resources still loading, and each flag answers alone.

The lifespan publishes a :class:`server.resources.StartupProgress` on
``app.state`` before ``Resources.startup`` begins, and startup flips one
flag per resource as it loads. These tests hold BGE-M3's load open, ask
``/readyz`` in the middle, and check that the body separates the LanceDB
table (already open) from the embedder (still loading).
"""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest

from server.config import Config
from server.main import create_app
from server.resources import (
    WARM_RESOURCE_NAMES,
    Resources,
    Singleflight,
    StartupProgress,
)
from tests._corpus_helpers import seed_corpus

_WAIT_SECONDS = 30.0


async def _wait_for(predicate, what: str) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _WAIT_SECONDS
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


async def _readyz(app) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1"
    ) as client:
        return await client.get("/readyz")


def test_readyz_names_the_cold_embedder_mid_startup(tmp_path, monkeypatch):
    import server.query_encoder as qe_mod

    release_model = threading.Event()
    model_requested = threading.Event()

    def _blocking_model() -> object:
        model_requested.set()
        if not release_model.wait(_WAIT_SECONDS):
            raise RuntimeError("test never released the model load")
        return object()

    monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())
    monkeypatch.setattr(qe_mod, "_get_model", _blocking_model)

    lancedb_path = tmp_path / "lancedb"
    seed_corpus(lancedb_path, n=2)
    app = create_app(Config(lancedb_path=lancedb_path, enable_rerank=False))

    async def _scenario() -> tuple[httpx.Response, httpx.Response]:
        stop = asyncio.Event()

        async def _run_lifespan() -> None:
            async with app.router.lifespan_context(app):
                await stop.wait()

        lifespan_task = asyncio.create_task(_run_lifespan())
        try:
            await _wait_for(model_requested.is_set, "the BGE-M3 load")
            if getattr(app.state, "resources", None) is not None:
                raise AssertionError("Resources attached before startup ended")
            mid = await _readyz(app)

            release_model.set()
            await _wait_for(
                lambda: getattr(app.state, "resources", None) is not None,
                "Resources to attach",
            )
            after = await _readyz(app)
        finally:
            release_model.set()
            stop.set()
            await lifespan_task
        return mid, after

    mid, after = asyncio.run(_scenario())

    assert mid.status_code == 503
    assert mid.json() == {
        "status": "not_ready",
        "warm": {"embedder": False, "lancedb": True, "reranker": False},
        "bm25_phase": "disabled",
    }
    assert after.status_code == 200, after.json()
    assert after.json()["warm"] == {
        "embedder": True,
        "lancedb": True,
        "reranker": False,
    }


def _resources(progress: StartupProgress, *, warm: bool) -> Resources:
    return Resources(
        config=Config(),
        corpus_info=None,
        chunks_table=None,
        embed_semaphore=asyncio.Semaphore(1),
        rerank_semaphore=asyncio.Semaphore(1),
        rerank_singleflight=Singleflight(),
        warm=warm,
        progress=progress,
    )


def test_embedder_and_lancedb_answer_independently() -> None:
    resources = _resources(
        StartupProgress(lancedb=True, embedder=False), warm=True
    )
    assert resources.is_resource_warm("lancedb") is True
    assert resources.is_resource_warm("embedder") is False
    assert resources.is_resource_warm("reranker") is False


def test_every_resource_reads_cold_once_warm_drops() -> None:
    resources = _resources(
        StartupProgress(lancedb=True, embedder=True, reranker=True),
        warm=False,
    )
    resources.reranker_model = object()
    assert {n: resources.is_resource_warm(n) for n in WARM_RESOURCE_NAMES} == (
        dict.fromkeys(WARM_RESOURCE_NAMES, False)
    )


def test_unknown_resource_name_raises() -> None:
    resources = _resources(StartupProgress(), warm=True)
    with pytest.raises(KeyError):
        resources.is_resource_warm("embeder")
