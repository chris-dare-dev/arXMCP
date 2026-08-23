"""``GET /metrics`` is an observability read, not the ingest control plane — issue #208.

Before this, the Prometheus scrape wrapper called
``refresh_metrics_from_singleton_state``, which read every cron sentinel off
disk and ran the failure-mode-7 disk-full mitigation — including **writing and
deleting** ``var/arxmcp/ops/ingest-paused``. Three defects in one call site:

1. Blocking disk I/O on the event loop, inside a request handler.
2. A read-only ``GET`` mutating ingest state.
3. The mitigation was inert exactly where it was documented as live: the
   shipped compose stack has no Prometheus, so on a stock install nothing ever
   scraped and the disk-full pause never ran.

And it failed in the condition it exists to report — on a read-only ``var/``
the sentinel write raised, taking down both ``/metrics`` and startup.

The tests here pin the split: the scrape path is pure, the mitigation lives on
:mod:`server.metrics_refresh`'s background task, and neither startup nor a
scrape dies on a filesystem that refuses writes.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

from server import health, metrics_refresh

REPO_ROOT = Path(__file__).resolve().parent.parent


def _fake_resources(tmp_path: Path) -> SimpleNamespace:
    """Minimal duck-typed Resources for the filesystem-metric path."""
    ops = tmp_path / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        config=SimpleNamespace(ops_dir=ops, data_dir=tmp_path),
        corpus_info=None,
        startup_chunk_count=0,
        startup_unindexed_rows=-1,
        process_start_time_seconds=0.0,
        degraded=None,
        cache=None,
        lean_repl=None,
        is_resource_warm=lambda _name: False,
    )


class TestScrapePathIsPure:
    """AC2 — ``GET /metrics`` performs no filesystem writes and no blocking I/O."""

    def test_scrape_refresh_does_not_call_the_filesystem_half(
        self, tmp_path: Path, monkeypatch
    ):
        """THE #208 regression guard.

        ``refresh_metrics_from_singleton_state`` is what the ``/metrics``
        wrapper calls. If it ever reaches the sentinel readers or the
        disk-free mitigation again, this fails.
        """
        called: list[str] = []
        monkeypatch.setattr(
            health,
            "refresh_sentinel_metrics",
            lambda *a, **k: called.append("sentinel"),
        )
        monkeypatch.setattr(
            health,
            "refresh_disk_free_metric",
            lambda *a, **k: called.append("disk"),
        )

        health.refresh_metrics_from_singleton_state(_fake_resources(tmp_path))

        assert called == [], (
            f"the /metrics scrape path reached the filesystem half {called}; "
            "those belong to the background refresher (issue #208)"
        )

    def test_metrics_wrapper_calls_only_the_pure_refresh(self):
        """Pin the call site itself, not just the function's body.

        A future edit could reintroduce the coupling by calling
        ``refresh_filesystem_metrics`` from the wrapper rather than by moving
        the code back, and the body-level test above would still pass.
        """
        source = (REPO_ROOT / "server" / "main.py").read_text(encoding="utf-8")
        # Extract the WHOLE function rather than a fixed window: #470 added a
        # method gate to this wrapper and a 600-char slice stopped before the
        # refresh call, failing on a correct change. Cut at the mount that
        # follows the definition.
        start = source.index("async def metrics_wrapper")
        wrapper = source[start : source.index('app.mount("/metrics"', start)]
        assert "refresh_metrics_from_singleton_state" in wrapper
        assert "refresh_filesystem_metrics" not in wrapper, (
            "the /metrics wrapper must not run the filesystem half — it does "
            "blocking I/O and writes the ingest-paused sentinel (issue #208)"
        )

    def test_filesystem_half_is_sync_so_it_must_be_threaded(self):
        """It is meant for ``asyncio.to_thread``. A coroutine here would
        invite awaiting it directly on the loop, which is the bug."""
        assert not inspect.iscoroutinefunction(
            health.refresh_filesystem_metrics
        )


class TestReadOnlyFilesystemSurvival:
    """AC3 — ``/metrics`` and startup both survive a read-only ``var/`` tree."""

    @staticmethod
    def _readonly_resources(tmp_path: Path, monkeypatch) -> SimpleNamespace:
        """Resources whose disk looks full AND whose sentinel writes fail."""
        resources = _fake_resources(tmp_path)

        import shutil

        monkeypatch.setattr(
            shutil,
            "disk_usage",
            lambda _p: SimpleNamespace(
                total=100, used=100, free=1  # far below the 10 GB pause floor
            ),
        )
        from tools import ingest_sentinel

        def _readonly(*_a, **_k):
            raise OSError(30, "Read-only file system")

        monkeypatch.setattr(ingest_sentinel, "write_pause", _readonly)
        return resources

    def test_disk_mitigation_survives_a_readonly_tree(
        self, tmp_path: Path, monkeypatch, caplog
    ):
        """The write raising must NOT propagate. It used to reach the scrape
        handler and the startup path — the server dying in exactly the
        condition its disk gauge exists to report."""
        resources = self._readonly_resources(tmp_path, monkeypatch)

        with caplog.at_level("WARNING"):
            health.refresh_filesystem_metrics(resources)  # must not raise

        assert any(
            "could not write ingest-paused sentinel" in rec.message
            for rec in caplog.records
        ), "a swallowed write must leave a WARNING breadcrumb"

    def test_disk_gauge_is_still_set_when_the_write_fails(
        self, tmp_path: Path, monkeypatch
    ):
        """The ALERT must survive even though the automatic pause did not —
        losing the mitigation is tolerable, losing the signal is not."""
        from server.observability.metrics import DISK_FREE_BYTES

        resources = self._readonly_resources(tmp_path, monkeypatch)
        health.refresh_filesystem_metrics(resources)

        assert (
            DISK_FREE_BYTES.labels(path=str(tmp_path))._value.get() == 1
        ), "arxmcp_disk_free_bytes must be current so ArXMCPDiskFull fires"

    def test_scrape_refresh_never_touches_the_readonly_tree(
        self, tmp_path: Path, monkeypatch
    ):
        """A scrape on a read-only box is now trivially safe: the pure half
        does not go near the filesystem at all."""
        resources = self._readonly_resources(tmp_path, monkeypatch)
        health.refresh_metrics_from_singleton_state(resources)  # must not raise


class TestBackgroundRefresher:
    """AC1 — the mitigation runs on its own schedule, independent of scrapes."""

    def test_tick_runs_the_filesystem_half_off_loop(
        self, tmp_path: Path, monkeypatch
    ):
        """The work must be dispatched through a thread, or the background
        task just relocates the event-loop blocking rather than removing it."""
        seen: dict[str, object] = {}
        real_to_thread = asyncio.to_thread

        async def _spy(fn, *args, **kwargs):
            seen["threaded"] = fn
            return await real_to_thread(fn, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", _spy)
        monkeypatch.setattr(
            health, "refresh_filesystem_metrics", lambda _r: seen.setdefault("ran", True)
        )

        ok = asyncio.run(metrics_refresh._run_one_tick(_fake_resources(tmp_path)))

        assert ok is True
        assert seen.get("ran") is True
        assert seen.get("threaded") is not None, (
            "the blocking refresh must go through asyncio.to_thread"
        )

    def test_a_failing_tick_does_not_kill_the_refresher(
        self, tmp_path: Path, monkeypatch, caplog
    ):
        """A read-only tree, a vanished ops dir, a malformed sentinel — none
        may end the task for the life of the process."""

        def _boom(_r):
            raise OSError(30, "Read-only file system")

        monkeypatch.setattr(health, "refresh_filesystem_metrics", _boom)

        with caplog.at_level("WARNING"):
            ok = asyncio.run(
                metrics_refresh._run_one_tick(_fake_resources(tmp_path))
            )

        assert ok is False
        assert any("refresh tick failed" in r.message for r in caplog.records)

    def test_loop_ticks_repeatedly_without_any_scrape(
        self, tmp_path: Path, monkeypatch
    ):
        """The whole point of AC1: ticks happen on a timer, with nobody
        scraping. Previously zero scrapes meant zero mitigation."""
        ticks: list[int] = []
        monkeypatch.setattr(
            health,
            "refresh_filesystem_metrics",
            lambda _r: ticks.append(1),
        )

        async def _drive():
            task = metrics_refresh.start_metrics_refresh_task(
                _fake_resources(tmp_path), interval_seconds=0.01
            )
            await asyncio.sleep(0.08)
            await metrics_refresh.stop_metrics_refresh_task(task)

        asyncio.run(_drive())

        assert len(ticks) >= 3, (
            f"expected repeated background ticks with no scrape; got {len(ticks)}"
        )

    def test_stop_is_idempotent_and_none_safe(self):
        asyncio.run(metrics_refresh.stop_metrics_refresh_task(None))

    def test_lifespan_starts_and_stops_the_task(self):
        """Pin the wiring — an unstarted task means the mitigation is inert
        again, which is defect #2 in the issue."""
        source = (REPO_ROOT / "server" / "main.py").read_text(encoding="utf-8")
        assert "start_metrics_refresh_task" in source
        assert "stop_metrics_refresh_task" in source
        assert source.index("start_metrics_refresh_task") < source.index(
            "stop_metrics_refresh_task"
        )


# NOTE deliberately no frontend-asset-path tests here. The console assets
# moved to ``server/frontend/`` in a commit that left 11 consumers pointing at
# the old top-level ``frontend/`` — ``server/main.py``, ``server/routes/ui.py``
# and nine test modules — so ``create_app()`` raises and several UI test files
# fail at collection. That repair belongs to the session that did the move
# (which already has all 11 fixed, uncommitted); duplicating it here would
# conflict. This module confines itself to issue #208.
