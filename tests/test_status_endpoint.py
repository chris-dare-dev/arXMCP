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

from server.backup_status import BACKUP_STATE_FAILED, BACKUP_STATE_OK
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
            # arXMCP#202: "success" was never a token any consumer knew.
            # The shared vocabulary lives in server/backup_status.py.
            "status": BACKUP_STATE_OK,
        }),
        encoding="utf-8",
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _set_healthy_disk(monkeypatch) -> None:
    """Make tests for the healthy status independent of host capacity."""
    monkeypatch.setattr(
        "shutil.disk_usage",
        lambda _: SimpleNamespace(
            total=100 * 1024**3,
            used=20 * 1024**3,
            free=80 * 1024**3,
        ),
    )


# ---------------------------------------------------------------------------
# compute_health_status — unit
# ---------------------------------------------------------------------------


class TestComputeHealthStatus:
    def test_pass_when_warm_healthy(self, tmp_path, monkeypatch):
        _set_healthy_disk(monkeypatch)
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

    def test_warn_when_recent_backup_run_failed(self, tmp_path):
        """chris-dare-dev/arXMCP#203 — the wrapper stamps ``finished_at``
        on every run that reaches the end, success or not. A fresh
        timestamp from a FAILED run must not read as a healthy backup;
        pre-fix this check trusted the timestamp alone and reported pass.
        """
        ops = tmp_path / "ops"
        ops.mkdir()
        (ops / "backup-status.json").write_text(
            json.dumps({
                "finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": BACKUP_STATE_FAILED,
            }),
            encoding="utf-8",
        )
        res = _FakeResources(warm=True, data_dir=tmp_path, ops_dir=ops)
        report = _run(compute_health_status(res, _FakeStore(1)))
        assert report["status"] == "warn"
        check = report["checks"]["backup:time"][0]
        assert check["status"] == "warn"
        assert "did not succeed" in check["output"]

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
                # The status must be a real success, or the arXMCP#203 gate
                # below warns for that reason instead of the age boundary
                # this test is pinning.
                json.dumps({"finished_at": ts, "status": BACKUP_STATE_OK}),
                encoding="utf-8",
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
    def test_status_pass_is_health_json_200(self, tmp_path, monkeypatch):
        _set_healthy_disk(monkeypatch)
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
    def test_badge_returns_html_fragment_200(self, tmp_path, monkeypatch):
        _set_healthy_disk(monkeypatch)
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

    # ui-badge-disambiguate AC1: any retrieval-side check non-pass → DEGRADED
    # + status-badge--warn (operator should ACT — corpus / lancedb /
    # embedder / notebooks layer is impaired).
    def test_badge_retrieval_warn_renders_degraded_label(self, tmp_path):
        """Retrieval-side warn (lancedb degraded) → 'DEGRADED' label +
        status-badge--warn class. The current live signal for corpus
        drift / MVCC fallback flows through ``lancedb:status = warn``."""
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
            r = c.get("/ui/status-badge")
        assert r.status_code == 200
        assert "status-badge--warn" in r.text
        # The CSS class for "ops-only-warn" must NOT appear here — this is
        # the disambiguation: retrieval-warn uses --warn, ops-warn uses
        # --ops-warn. (The substring guard catches a future operator
        # collapse back to a single shared class.)
        assert "status-badge--ops-warn" not in r.text
        assert "DEGRADED" in r.text
        assert "WARN |" not in r.text  # the ops-only label must not appear
        # F1 + F3 regression guard (rect): pin the full label-and-trailer
        # phrase, including the space before the first pipe. A previous
        # implementation used ``label + raw_summary[pipe:]`` which dropped
        # the space and rendered "DEGRADED| corpus v7 ...".
        assert "DEGRADED | corpus v7 | 2 notebooks" in r.text

    # ui-badge-disambiguate AC2: when ONLY ops-side checks are non-pass,
    # the badge label is "WARN" and the class is status-badge--ops-warn —
    # NOT "DEGRADED" (which would actively mislead an operator post-fix
    # when restic just hasn't run yet).
    def test_badge_ops_only_warn_renders_distinct_label(self, tmp_path):
        """No backup-status.json → backup:time warns; all retrieval-side
        checks are 'pass'. Pre-fix this rendered as 'DEGRADED' (the bug);
        post-fix it must render 'WARN' + status-badge--ops-warn."""
        # ops dir exists but contains no backup-status.json → backup warn.
        (tmp_path / "ops").mkdir()
        res = _FakeResources(
            warm=True, data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        with TestClient(_app_with(res, _FakeStore(2))) as c:
            r = c.get("/ui/status-badge")
        assert r.status_code == 200
        assert "status-badge--ops-warn" in r.text
        # Must NOT render the retrieval-degraded class — that is the very
        # collision this milestone removed.
        assert "status-badge--warn\"" not in r.text  # exact class boundary
        assert "DEGRADED" not in r.text
        assert "WARN" in r.text  # the disambiguated label
        # F1 + F3 regression guard (rect): full label-and-trailer phrase
        # including the space before the first pipe.
        assert "WARN | corpus v7 | 2 notebooks" in r.text

    # ui-badge-disambiguate FM-1 regression guard: when BOTH a retrieval-side
    # check AND an ops-side check are non-pass, retrieval wins (DEGRADED).
    # Otherwise an operator would see "WARN" and dismiss a real degradation.
    def test_badge_mixed_retrieval_and_ops_warn_prefers_degraded(self, tmp_path):
        """Both lancedb degraded AND backup absent → retrieval wins, badge
        is 'DEGRADED' + status-badge--warn (NOT the softer ops-warn)."""
        # No backup-status.json → backup:time warns; degraded → lancedb warns.
        (tmp_path / "ops").mkdir()
        res = _FakeResources(
            warm=True,
            degraded=_FakeDegraded(
                reason="corpus_corruption", fallback_version=6,
                original_version=7,
            ),
            data_dir=tmp_path, ops_dir=tmp_path / "ops",
        )
        with TestClient(_app_with(res, _FakeStore(2))) as c:
            r = c.get("/ui/status-badge")
        assert r.status_code == 200
        assert "DEGRADED" in r.text
        assert "status-badge--ops-warn" not in r.text


class TestClassifyStatusBadge:
    """Unit coverage for the ``_classify_status_badge`` helper (ui-badge-
    disambiguate). The endpoint-level tests above exercise the live wiring;
    these tests pin the helper's contract under edge inputs that are
    expensive to stage via a full TestClient (schema drift, malformed
    entries, ALL retrieval-key membership)."""

    def _classify(self, report):
        from server.routes.ui import _classify_status_badge

        return _classify_status_badge(report)

    def test_fail_short_circuits_to_down(self):
        assert self._classify({"status": "fail", "checks": {}}) == ("DOWN", "down")

    def test_pass_returns_ready_ok(self):
        assert self._classify({"status": "pass", "checks": {}}) == ("READY", "ok")

    def test_warn_with_empty_checks_falls_through_to_ops_warn(self):
        # Empty checks dict + status==warn means we can find no retrieval
        # signal → "WARN" (the ops-only path). This is the safer default
        # than always-DEGRADED, because the live ops checks (backup/disk)
        # are the only ones that can flip top-level warn today.
        assert self._classify({"status": "warn", "checks": {}}) == ("WARN", "ops-warn")

    def test_warn_with_non_dict_checks_defaults_to_degraded(self):
        # FM-2 (schema drift): if checks is a list or None, preserve
        # today's "DEGRADED" so a real retrieval degradation cannot hide
        # behind a future shape change.
        assert self._classify({"status": "warn", "checks": []}) == ("DEGRADED", "warn")
        assert self._classify({"status": "warn", "checks": None}) == ("DEGRADED", "warn")
        assert self._classify({"status": "warn"}) == ("DEGRADED", "warn")

    def test_warn_with_each_retrieval_key_renders_degraded(self):
        from server.routes.ui import _RETRIEVAL_CHECK_KEYS

        for key in _RETRIEVAL_CHECK_KEYS:
            report = {
                "status": "warn",
                "checks": {key: [{"status": "warn"}]},
            }
            assert self._classify(report) == ("DEGRADED", "warn"), key

    def test_warn_with_retrieval_check_fail_also_renders_degraded(self):
        # ``status != "pass"`` covers both ``warn`` and ``fail`` per AC1.
        report = {
            "status": "warn",
            "checks": {"lancedb:status": [{"status": "fail"}]},
        }
        assert self._classify(report) == ("DEGRADED", "warn")

    def test_warn_with_ops_only_keys_renders_ops_warn(self):
        report = {
            "status": "warn",
            "checks": {
                "backup:time": [{"status": "warn"}],
                "disk:utilization": [{"status": "pass"}],
                # Retrieval-side keys present but all "pass".
                "embedder:status": [{"status": "pass"}],
                "lancedb:status": [{"status": "pass"}],
                "corpus:version": [{"status": "pass"}],
                "notebooks:count": [{"status": "pass"}],
            },
        }
        assert self._classify(report) == ("WARN", "ops-warn")

    # F2 regression guard (rect): symmetric to
    # ``test_warn_with_each_retrieval_key_renders_degraded`` — each ops-side
    # key, exercised IN ISOLATION, must produce ("WARN", "ops-warn").
    # Catches a future regression that accidentally moves one ops key into
    # ``_RETRIEVAL_CHECK_KEYS`` (e.g. a typo like "disk:utilisation"
    # leaking the retrieval-side path).
    def test_warn_with_each_ops_key_renders_ops_warn(self):
        for key in ("backup:time", "disk:utilization", "process:uptime"):
            report = {"status": "warn", "checks": {key: [{"status": "warn"}]}}
            assert self._classify(report) == ("WARN", "ops-warn"), key

    def test_warn_with_malformed_entry_is_ignored(self):
        # Non-dict entries (e.g. a future tuple shape) should not crash;
        # the loop treats them as missing.
        report = {
            "status": "warn",
            "checks": {
                "lancedb:status": ["bogus_string", None, 42],
                # Real ops-side warn must still produce "WARN".
                "backup:time": [{"status": "warn"}],
            },
        }
        assert self._classify(report) == ("WARN", "ops-warn")


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
        """m3 / m2 critique F8: the Makefile's single ``.PHONY`` line
        was split into per-section stanzas. ``status`` now lives in the
        OPS / MAINTENANCE stanza rather than the first line. This test
        walks EVERY ``.PHONY:`` stanza for the target name."""
        import re as _re

        mk = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "\nstatus:" in mk
        # Collect targets from ALL .PHONY: lines (multi-line declarations
        # are a valid Make pattern).
        phony_targets: list[str] = []
        for m in _re.finditer(r"^\.PHONY:\s+(.+)$", mk, _re.MULTILINE):
            phony_targets.extend(m.group(1).split())
        assert "status" in phony_targets, (
            f".PHONY stanzas must list 'status'; got {phony_targets}"
        )
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
