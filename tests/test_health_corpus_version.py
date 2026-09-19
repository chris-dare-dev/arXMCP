"""corpus_version restoration on /readyz + /status (stage2/arx-a1).

Finding 06 §3 item 2 / acceptance-criteria.md AC-A.3: the two
load-bearing substrate-block fields the cutover spikes proved missing.
Spike-3's failure mode was ``corpus_version`` silently dropping off the
readiness surface; the bridge envelope treats it (and the per-notebook
map) as load-bearing.

Coverage:

- TestReadyzCorpusVersion — ready body carries the shared pinned
  version; bootstrap body carries an explicit null; degraded body
  carries the fallback (the version actually being served).
- TestStatusNotebookVersions — /status carries the per-notebook
  ``notebooks:corpus_versions`` check on the warm AND bootstrap paths;
  marker-less notebooks render null; failures degrade, never 500.

Harness: fake Resources + real health router — the
tests/test_status_endpoint.py pattern (no lifespan, no model loads).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.health import _notebook_corpus_versions, compute_health_status
from server.health import router as health_router

# ---------------------------------------------------------------------------
# Fakes (mirroring tests/test_status_endpoint.py)
# ---------------------------------------------------------------------------


class _FakeResources:
    def __init__(
        self, *, warm=True, degraded=None, version=7, bootstrap=False,
        data_dir: Path, ops_dir: Path,
    ) -> None:
        self.warm = warm
        self.degraded = degraded
        self.bootstrap_mode_active = bootstrap
        self.corpus_info = SimpleNamespace(version=version, chunk_count=100)
        self.startup_chunk_count = 100
        self.process_start_time_seconds = time.time() - 3600
        self.config = SimpleNamespace(data_dir=data_dir, ops_dir=ops_dir)

    def is_resource_warm(self, name: str) -> bool:
        if name in ("embedder", "lancedb"):
            return self.warm
        if name == "reranker":
            return False
        raise KeyError(name)


class _FakeStore:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def list_notebooks(self) -> list[dict]:
        return self._rows


def _write_marker(lancedb_dir: Path, version: int) -> None:
    lancedb_dir.mkdir(parents=True, exist_ok=True)
    (lancedb_dir / "corpus-version.json").write_text(
        json.dumps({
            "chunk_count": 10,
            "chunker_version": "v1.1",
            "created_at": "2026-07-04T00:00:00Z",
            "embedder_version": "bge-m3@test",
            "paper_count": 2,
            "version": version,
        }),
        encoding="utf-8",
    )


def _app(resources, store=None) -> TestClient:
    app = FastAPI()
    app.include_router(health_router)
    app.state.resources = resources
    if store is not None:
        app.state.notebooks_store = store
    return TestClient(app)


# ---------------------------------------------------------------------------
# /readyz
# ---------------------------------------------------------------------------


class TestReadyzCorpusVersion:
    def test_ready_body_carries_corpus_version(self, tmp_path: Path) -> None:
        res = _FakeResources(
            version=42, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        r = _app(res).get("/readyz")
        assert r.status_code == 200
        assert r.json()["corpus_version"] == 42

    def test_bootstrap_body_carries_explicit_null(self, tmp_path: Path) -> None:
        res = _FakeResources(
            warm=False, bootstrap=True,
            data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        r = _app(res).get("/readyz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "bootstrap"
        assert "corpus_version" in body
        assert body["corpus_version"] is None

    def test_degraded_body_carries_fallback_version(self, tmp_path: Path) -> None:
        res = _FakeResources(
            version=42,
            degraded=SimpleNamespace(
                reason="corpus_corruption",
                fallback_version=41,
                original_version=42,
            ),
            data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        r = _app(res).get("/readyz")
        assert r.status_code == 503
        body = r.json()
        # The version actually being SERVED — consumers pinning
        # against corpus_version must see reality, not the failed tip.
        assert body["corpus_version"] == 41
        assert body["fallback_version"] == 41


# ---------------------------------------------------------------------------
# /status per-notebook corpus versions
# ---------------------------------------------------------------------------


class TestStatusNotebookVersions:
    def test_warm_status_includes_per_notebook_versions(
        self, tmp_path: Path,
    ) -> None:
        nb1 = tmp_path / "notebooks" / "alpha-nb" / "lancedb"
        _write_marker(nb1, 1690)
        store = _FakeStore([
            {"slug": "alpha-nb", "lancedb_path": str(nb1)},
            {"slug": "beta-nb", "lancedb_path": str(tmp_path / "nope")},
        ])
        res = _FakeResources(
            version=7, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        r = _app(res, store).get("/status")
        assert r.status_code == 200
        checks = r.json()["checks"]
        assert "notebooks:corpus_versions" in checks
        observed = checks["notebooks:corpus_versions"][0]["observedValue"]
        assert observed == {"alpha-nb": 1690, "beta-nb": None}
        # The shared corpus:version check is unchanged (additive-only).
        assert checks["corpus:version"][0]["observedValue"] == 7

    def test_bootstrap_status_includes_the_check(self, tmp_path: Path) -> None:
        nb1 = tmp_path / "notebooks" / "gamma-nb" / "lancedb"
        _write_marker(nb1, 5)
        store = _FakeStore([{"slug": "gamma-nb", "lancedb_path": str(nb1)}])
        res = _FakeResources(
            warm=False, bootstrap=True,
            data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        r = _app(res, store).get("/status")
        assert r.status_code == 200
        checks = r.json()["checks"]
        assert checks["notebooks:corpus_versions"][0]["observedValue"] == {
            "gamma-nb": 5
        }

    def test_malformed_marker_degrades_to_null(self, tmp_path: Path) -> None:
        nb = tmp_path / "notebooks" / "bad-nb" / "lancedb"
        nb.mkdir(parents=True)
        (nb / "corpus-version.json").write_text("{broken", encoding="utf-8")
        result = asyncio.run(
            _notebook_corpus_versions(
                _FakeStore([{"slug": "bad-nb", "lancedb_path": str(nb)}])
            )
        )
        assert result == {"bad-nb": None}

    def test_store_absent_returns_empty_map(self) -> None:
        assert asyncio.run(_notebook_corpus_versions(None)) == {}

    def test_throwing_store_degrades_to_empty_map(self) -> None:
        class _Boom:
            async def list_notebooks(self):
                raise RuntimeError("db locked")

        assert asyncio.run(_notebook_corpus_versions(_Boom())) == {}

    def test_compute_health_status_never_raises_on_marker_probe(
        self, tmp_path: Path,
    ) -> None:
        """Belt-and-braces: the full status computation with a
        throwing store stays a warn, never an exception."""
        class _Boom:
            async def list_notebooks(self):
                raise RuntimeError("db locked")

        res = _FakeResources(
            version=7, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        report = asyncio.run(compute_health_status(res, _Boom()))
        assert report["status"] in ("pass", "warn")
