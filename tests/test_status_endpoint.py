"""Tests for the /status operability surface (notebook-ops-hardening-m4).

Covers:
- compute_health_status: pass / warn (degraded, disk, backup, store-absent) /
  fail (not warm), deterministically (injected clock + fake Resources).
- GET /status: application/health+json, 200 for pass/warn, 503 for fail.
- AC4: a degraded server returns /status warn 200 AND /readyz 503 (the
  existing /readyz 503-on-degraded behavior is unchanged).
- GET /ui/status-badge: HTML fragment, always 200, correct modifier class.
- tools/status_line.py: the `make status` human-line parser.
- Makefile: the `status` target exists.

Uses a minimal FastAPI app + fake Resources (no model load / no lifespan), the
same lightweight pattern as tests/test_notebook_api.py.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.health import compute_health_status
from server.health import router as health_router
from tools.status_line import format_status_line

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResources:
    def __init__(
        self, *, warm=True, degraded=None, version=7,
        data_dir: Path, ops_dir: Path, start: float | None = None,
    ) -> None:
        self.warm = warm
        self.degraded = degraded
        self.corpus_info = SimpleNamespace(version=version, chunk_count=100)
        self.process_start_time_seconds = (
            start if start is not None else time.time() - 3600
        )
        self.config = SimpleNamespace(data_dir=data_dir, ops_dir=ops_dir)

    def is_resource_warm(self, name: str) -> bool:
        if name in ("embedder", "lancedb"):
            return self.warm
        if name == "reranker":
            return False
        raise KeyError(name)


_FakeDegraded = SimpleNamespace  # carries .reason/.fallback_version/.original_version


class _FakeStore:
    def __init__(self, n: int) -> None:
        self._n = n

    async def list_notebooks(self) -> list[dict[str, str]]:
        return [{"slug": f"n{i}"} for i in range(self._n)]


def _write_recent_backup(ops_dir: Path) -> None:
    ops_dir.mkdir(parents=True, exist_ok=True)
    (ops_dir / "backup-status.json").write_text(
        json.dumps({
            "finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "success",
        }),
        encoding="utf-8",
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# compute_health_status — unit
# ---------------------------------------------------------------------------


class TestComputeHealthStatus:
    def test_pass_when_warm_healthy(self, tmp_path):
        _write_recent_backup(tmp_path / "ops")
        res = _FakeResources(
            warm=True, version=7, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        report = _run(compute_health_status(res, _FakeStore(3)))
        assert report["status"] == "pass"
        assert report["http_code"] == 200
        checks = report["checks"]
        assert checks["corpus:version"][0]["observedValue"] == 7
        assert checks["notebooks:count"][0]["observedValue"] == 3
        assert checks["embedder:status"][0]["status"] == "pass"
        assert checks["lancedb:status"][0]["status"] == "pass"
        assert "READY" in report["summary"]

    def test_fail_when_not_warm(self, tmp_path):
        res = _FakeResources(
            warm=False, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        report = _run(compute_health_status(res, _FakeStore(3)))
        assert report["status"] == "fail"
        assert report["http_code"] == 503
        assert report["checks"]["embedder:status"][0]["status"] == "fail"

    def test_fail_when_resources_none(self):
        report = _run(compute_health_status(None, None))
        assert report["status"] == "fail"
        assert report["http_code"] == 503

    def test_warn_when_degraded(self, tmp_path):
        _write_recent_backup(tmp_path / "ops")
        res = _FakeResources(
            warm=True,
            degraded=_FakeDegraded(
                reason="corpus_corruption", fallback_version=6,
                original_version=7,
            ),
            data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        report = _run(compute_health_status(res, _FakeStore(2)))
        assert report["status"] == "warn"
        assert report["http_code"] == 200
        assert report["checks"]["lancedb:status"][0]["status"] == "warn"
        assert "degraded" in report["summary"]

    def test_warn_when_backup_absent(self, tmp_path):
        # ops dir exists but no backup-status.json → backup check warns.
        (tmp_path / "ops").mkdir()
        res = _FakeResources(
            warm=True, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        report = _run(compute_health_status(res, _FakeStore(1)))
        assert report["status"] == "warn"
        assert report["checks"]["backup:time"][0]["status"] == "warn"

    def test_warn_when_backup_stale(self, tmp_path):
        ops = tmp_path / "ops"
        ops.mkdir()
        old = (datetime.now(UTC) - timedelta(hours=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        (ops / "backup-status.json").write_text(
            json.dumps({"finished_at": old}), encoding="utf-8"
        )
        res = _FakeResources(warm=True, data_dir=tmp_path, ops_dir=ops)
        report = _run(compute_health_status(res, _FakeStore(1)))
        assert report["status"] == "warn"
        assert report["checks"]["backup:time"][0]["status"] == "warn"

    def test_warn_when_store_absent_does_not_500(self, tmp_path):
        _write_recent_backup(tmp_path / "ops")
        res = _FakeResources(
            warm=True, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        report = _run(compute_health_status(res, None))
        assert report["status"] == "warn"
        assert report["checks"]["notebooks:count"][0]["observedValue"] is None

    def test_throwing_store_warns_and_logs(self, tmp_path, caplog):
        """m4 rect F1: a store-layer exception must degrade to warn (never
        500) AND leave a log breadcrumb (the broad except was unexercised)."""
        import logging

        _write_recent_backup(tmp_path / "ops")

        class _BoomStore:
            async def list_notebooks(self):
                raise RuntimeError("boom")

        res = _FakeResources(
            warm=True, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        with caplog.at_level(logging.WARNING, logger="server.health"):
            report = _run(compute_health_status(res, _BoomStore()))
        assert report["status"] == "warn"
        assert report["checks"]["notebooks:count"][0]["observedValue"] is None
        assert any(
            "notebook-store probe failed" in r.getMessage()
            for r in caplog.records
        ), "expected a WARNING breadcrumb when the store probe raises"

    def test_now_injection_pins_backup_staleness_boundary(self, tmp_path):
        """m4 rect F2: exercise the documented ``now`` clock at the
        _BACKUP_STALE_SECONDS boundary (deterministic, no wall-clock flake)."""
        from server.health import _BACKUP_STALE_SECONDS

        ops = tmp_path / "ops"
        ops.mkdir()
        res = _FakeResources(warm=True, data_dir=tmp_path, ops_dir=ops)
        fixed_now = 1_900_000_000.0

        def _write(age_seconds: float) -> None:
            ts = datetime.fromtimestamp(
                fixed_now - age_seconds, UTC
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            (ops / "backup-status.json").write_text(
                json.dumps({"finished_at": ts}), encoding="utf-8"
            )

        # Just inside the window → backup check passes.
        _write(_BACKUP_STALE_SECONDS - 1)
        r1 = _run(compute_health_status(res, _FakeStore(1), now=fixed_now))
        assert r1["checks"]["backup:time"][0]["status"] == "pass"

        # Just over the window → backup check warns.
        _write(_BACKUP_STALE_SECONDS + 60)
        r2 = _run(compute_health_status(res, _FakeStore(1), now=fixed_now))
        assert r2["checks"]["backup:time"][0]["status"] == "warn"
        assert r2["status"] == "warn"


# ---------------------------------------------------------------------------
# Endpoint wiring (/status, /readyz unchanged, /ui/status-badge)
# ---------------------------------------------------------------------------


def _app_with(resources, store) -> FastAPI:
    app = FastAPI()
    app.state.resources = resources
    app.state.notebooks_store = store
    app.include_router(health_router)
    from server.routes.ui import router as ui_router
    app.include_router(ui_router, prefix="/ui")
    return app


class TestStatusEndpoint:
    def test_status_pass_is_health_json_200(self, tmp_path):
        _write_recent_backup(tmp_path / "ops")
        res = _FakeResources(
            warm=True, version=7, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        with TestClient(_app_with(res, _FakeStore(2))) as c:
            r = c.get("/status")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/health+json")
        body = r.json()
        assert body["status"] == "pass"
        assert body["checks"]["corpus:version"][0]["observedValue"] == 7
        assert body["checks"]["notebooks:count"][0]["observedValue"] == 2

    def test_status_degraded_warn_200_AND_readyz_still_503(self, tmp_path):
        """AC4: /status reports degraded as warn 200; /readyz keeps 503."""
        _write_recent_backup(tmp_path / "ops")
        res = _FakeResources(
            warm=True,
            degraded=_FakeDegraded(
                reason="corpus_corruption", fallback_version=6,
                original_version=7,
            ),
            data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        with TestClient(_app_with(res, _FakeStore(2))) as c:
            status_r = c.get("/status")
            readyz_r = c.get("/readyz")
        assert status_r.status_code == 200
        assert status_r.json()["status"] == "warn"
        # /readyz is UNCHANGED — still 503 on the degraded path.
        assert readyz_r.status_code == 503
        assert readyz_r.json()["status"] == "degraded"

    def test_status_fail_503_when_not_warm(self, tmp_path):
        res = _FakeResources(
            warm=False, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        with TestClient(_app_with(res, _FakeStore(0))) as c:
            r = c.get("/status")
        assert r.status_code == 503
        assert r.json()["status"] == "fail"


class TestStatusBadge:
    def test_badge_returns_html_fragment_200(self, tmp_path):
        _write_recent_backup(tmp_path / "ops")
        res = _FakeResources(
            warm=True, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        with TestClient(_app_with(res, _FakeStore(2))) as c:
            r = c.get("/ui/status-badge")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert 'id="status-badge"' in r.text
        assert "status-badge--ok" in r.text  # warm+healthy → ok class
        # Re-emits its own poll so the swapped element keeps polling.
        assert 'hx-get="/ui/status-badge"' in r.text
        assert 'hx-trigger="every 10s"' in r.text

    def test_badge_down_class_when_not_warm(self, tmp_path):
        res = _FakeResources(
            warm=False, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        with TestClient(_app_with(res, _FakeStore(0))) as c:
            r = c.get("/ui/status-badge")
        assert r.status_code == 200  # badge always 200 (it is a UI fragment)
        assert "status-badge--down" in r.text


# ---------------------------------------------------------------------------
# make status parser + Makefile target
# ---------------------------------------------------------------------------


class TestStatusLineParser:
    def test_pass_line(self):
        body = {
            "status": "pass",
            "checks": {
                "corpus:version": [{"observedValue": 7}],
                "notebooks:count": [{"observedValue": 3}],
            },
        }
        assert format_status_line(body) == "READY | corpus v7 | 3 notebooks"

    def test_warn_line(self):
        body = {"status": "warn", "checks": {
            "corpus:version": [{"observedValue": 7}],
            "notebooks:count": [{"observedValue": 3}],
        }}
        assert format_status_line(body).startswith("DEGRADED")

    def test_fail_line_with_missing_checks(self):
        assert format_status_line({"status": "fail"}) == (
            "DOWN | corpus v? | ? notebooks"
        )

    def test_null_observed_renders_question_mark(self):
        body = {"status": "warn", "checks": {
            "notebooks:count": [{"observedValue": None}],
        }}
        assert "? notebooks" in format_status_line(body)


class TestMakefileTarget:
    def test_status_target_exists(self):
        mk = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "\nstatus:" in mk
        assert "status" in mk.split("\n", 1)[0]  # in .PHONY
        assert "tools/status_line.py" in mk


class TestStatusSecFetchSiteDeviation:
    """m4 rect F4: pin Deviation #1's two premises to the REAL paths via a
    full create_app middleware stack (the bare-FastAPI tests above bypass
    SecFetchSiteMiddleware). A future router-prefix change to either path
    would otherwise silently regress the badge's design."""

    def _client(self, tmp_path, monkeypatch) -> TestClient:
        # Mirror tests/security/test_sec_fetch_site_carveout.py::_build_test_client
        # — SecFetchSite fires before handler dispatch, so the (failed) lifespan
        # is irrelevant; no model load.
        monkeypatch.setenv("ARXMCP_LANCEDB_PATH", str(tmp_path / "lancedb-empty"))
        monkeypatch.delenv("ARXMCP_ALLOWED_ORIGINS", raising=False)
        monkeypatch.delenv("ARXMCP_UNSAFE_NETWORK_BIND", raising=False)
        monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
        from server.config import Config
        from server.main import create_app

        return TestClient(create_app(Config()))

    def test_status_403s_browser_same_origin(self, tmp_path, monkeypatch):
        """WHY the badge can't hx-get /status: a browser same-origin XHR to the
        non-/ui /status is 403'd by SecFetchSiteMiddleware."""
        client = self._client(tmp_path, monkeypatch)
        r = client.get("/status", headers={"Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 403
        assert r.json()["error"] == "sec_fetch_site_forbidden"

    def test_ui_status_badge_not_403_browser_same_origin(
        self, tmp_path, monkeypatch
    ):
        """The badge endpoint under /ui is exempt → NOT 403 (the deviation
        works); the handler renders a badge even with no warm resources."""
        client = self._client(tmp_path, monkeypatch)
        r = client.get(
            "/ui/status-badge", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert r.status_code != 403
        assert "status-badge" in r.text
