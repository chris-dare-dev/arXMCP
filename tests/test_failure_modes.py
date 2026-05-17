"""E14_S05 — failure-mode handler tests.

Coverage map (synthesis D10 → test class):

- D2  LanceDB corruption N-1 fallback        TestLanceDBCorruptionFallback
- D2  /readyz degraded body                  TestDegradedReadyz
- D4  ingest-paused sentinel CLI + library   TestIngestSentinel
- D4  disk-full scrape hook + hysteresis     TestDiskFullSentinelLogic
- D6  hosted-embedder fallback wrapper       TestHostedEmbedderFallback

The Voyage stub raises in v1 by design (full HTTP client is out
of scope); these tests pin the FALLBACK CONTRACT — that a
hosted-provider failure routes to BGE-M3 with ``used_fallback=True``
and increments the Prometheus counter.
"""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# D4 — tools/ingest_sentinel.py
# ---------------------------------------------------------------------------


class TestIngestSentinel:
    def test_write_then_is_paused_reads_back(self, tmp_path):
        from tools.ingest_sentinel import is_paused, write_pause  # noqa: PLC0415

        p = tmp_path / "ingest-paused"
        write_pause(
            reason="disk_low",
            free_bytes=5_000_000,
            threshold_bytes=10 * 1024**3,
            path=p,
        )
        record = is_paused(path=p)
        assert record is not None
        assert record["reason"] == "disk_low"
        assert record["free_bytes"] == 5_000_000
        assert record["threshold_bytes"] == 10 * 1024**3
        # written_at is an ISO-Zulu string.
        assert isinstance(record["written_at"], str)
        assert record["written_at"].endswith("Z")

    def test_is_paused_returns_none_when_absent(self, tmp_path):
        from tools.ingest_sentinel import is_paused  # noqa: PLC0415

        assert is_paused(path=tmp_path / "absent") is None

    def test_clear_pause_removes_sentinel(self, tmp_path):
        from tools.ingest_sentinel import (  # noqa: PLC0415
            clear_pause,
            is_paused,
            write_pause,
        )

        p = tmp_path / "ingest-paused"
        write_pause(reason="manual", path=p)
        assert is_paused(path=p) is not None
        removed = clear_pause(path=p)
        assert removed is True
        assert is_paused(path=p) is None
        # Idempotent: second clear returns False (already absent).
        assert clear_pause(path=p) is False

    def test_overwrite_with_different_reason(self, tmp_path):
        """Second write with a different reason overwrites — the
        sentinel is one-at-a-time by design (latest writer wins)."""
        from tools.ingest_sentinel import is_paused, write_pause  # noqa: PLC0415

        p = tmp_path / "ingest-paused"
        write_pause(reason="disk_low", path=p)
        write_pause(reason="maintenance", path=p)
        record = is_paused(path=p)
        assert record["reason"] == "maintenance"

    def test_malformed_sentinel_returns_synthetic_record(self, tmp_path):
        """A malformed JSON body returns the synthetic
        ``{"reason": "malformed_sentinel"}`` so callers don't have
        to handle ``json.JSONDecodeError`` — operators see a
        clear "honor the pause" signal."""
        from tools.ingest_sentinel import is_paused  # noqa: PLC0415

        p = tmp_path / "ingest-paused"
        p.write_text("{not valid json", encoding="utf-8")
        record = is_paused(path=p)
        assert record == {"reason": "malformed_sentinel"}


class TestDiskFullSentinelLogic:
    """E14_S05 D4 — the scrape-time refresh hook in
    ``server.health.refresh_disk_free_metric`` is what wires
    ``shutil.disk_usage`` into the gauge + sentinel."""

    def test_writes_sentinel_when_free_below_threshold(
        self, tmp_path, monkeypatch
    ):
        from server.health import (  # noqa: PLC0415
            DISK_PAUSE_THRESHOLD_BYTES,
            refresh_disk_free_metric,
        )
        from tools.ingest_sentinel import is_paused  # noqa: PLC0415

        # 5 GB free — well under the 10 GB threshold.
        fake_usage = SimpleNamespace(
            total=100 * 1024**3,
            used=95 * 1024**3,
            free=5 * 1024**3,
        )
        monkeypatch.setattr(
            "shutil.disk_usage", lambda _: fake_usage
        )
        data_dir = tmp_path / "data"
        (data_dir / "ops").mkdir(parents=True)
        refresh_disk_free_metric(data_dir)

        record = is_paused(path=data_dir / "ops" / "ingest-paused")
        assert record is not None
        assert record["reason"] == "disk_low"
        assert record["free_bytes"] == 5 * 1024**3
        assert record["threshold_bytes"] == DISK_PAUSE_THRESHOLD_BYTES

    def test_clears_sentinel_when_free_above_hysteresis_band(
        self, tmp_path, monkeypatch
    ):
        from server.health import refresh_disk_free_metric  # noqa: PLC0415
        from tools.ingest_sentinel import is_paused, write_pause  # noqa: PLC0415

        data_dir = tmp_path / "data"
        (data_dir / "ops").mkdir(parents=True)
        sentinel = data_dir / "ops" / "ingest-paused"
        # Pre-seed a disk_low sentinel.
        write_pause(reason="disk_low", free_bytes=5_000_000, path=sentinel)
        # Now 20 GB free — well above the 15 GB clear threshold.
        fake_usage = SimpleNamespace(
            total=100 * 1024**3,
            used=80 * 1024**3,
            free=20 * 1024**3,
        )
        monkeypatch.setattr("shutil.disk_usage", lambda _: fake_usage)

        refresh_disk_free_metric(data_dir)
        assert is_paused(path=sentinel) is None

    def test_does_not_clear_operator_written_sentinel(
        self, tmp_path, monkeypatch
    ):
        """The auto-clear logic only clears sentinels with
        ``reason=disk_low``. An operator's manual maintenance
        sentinel survives auto-recovery."""
        from server.health import refresh_disk_free_metric  # noqa: PLC0415
        from tools.ingest_sentinel import is_paused, write_pause  # noqa: PLC0415

        data_dir = tmp_path / "data"
        (data_dir / "ops").mkdir(parents=True)
        sentinel = data_dir / "ops" / "ingest-paused"
        write_pause(reason="maintenance", path=sentinel)

        fake_usage = SimpleNamespace(
            total=100 * 1024**3,
            used=70 * 1024**3,
            free=30 * 1024**3,
        )
        monkeypatch.setattr("shutil.disk_usage", lambda _: fake_usage)
        refresh_disk_free_metric(data_dir)

        record = is_paused(path=sentinel)
        assert record is not None
        assert record["reason"] == "maintenance"

    def test_no_sentinel_within_hysteresis_band(
        self, tmp_path, monkeypatch
    ):
        """When free is between 10 GB and 15 GB (the hysteresis
        band), the refresh neither writes nor clears. Avoids the
        boundary-flap pattern."""
        from server.health import refresh_disk_free_metric  # noqa: PLC0415
        from tools.ingest_sentinel import is_paused  # noqa: PLC0415

        data_dir = tmp_path / "data"
        (data_dir / "ops").mkdir(parents=True)
        sentinel = data_dir / "ops" / "ingest-paused"
        # 12 GB free — between thresholds.
        fake_usage = SimpleNamespace(
            total=100 * 1024**3,
            used=88 * 1024**3,
            free=12 * 1024**3,
        )
        monkeypatch.setattr("shutil.disk_usage", lambda _: fake_usage)
        refresh_disk_free_metric(data_dir)
        # Neither write (free > 10 GB) nor clear (sentinel didn't
        # exist) — sentinel remains absent.
        assert is_paused(path=sentinel) is None


# ---------------------------------------------------------------------------
# D2 — LanceDB corruption fallback
# ---------------------------------------------------------------------------


class TestLanceDBCorruptionFallback:
    """The fallback decision tree lives in
    ``server.corpus.open_chunks_table_with_fallback``. The tests
    inject failures by monkey-patching ``open_chunks_table`` to
    raise on the live tip and succeed on N-1. A truly
    representative test would need a real LanceDB on disk with
    a synthetic corrupt manifest — that's heavy for a unit test
    but documented as a manual smoke step in
    docs/ops/failure-modes.md."""

    def test_happy_path_returns_none_for_degraded(self, monkeypatch):
        from server import corpus as corpus_mod  # noqa: PLC0415

        fake_table = SimpleNamespace(version=5)
        calls: list[int] = []

        def fake_open(lancedb_path=None, version=None):
            calls.append(version)
            return fake_table

        monkeypatch.setattr(corpus_mod, "open_chunks_table", fake_open)
        tbl, degraded = corpus_mod.open_chunks_table_with_fallback(
            lancedb_path=pathlib.Path("/tmp/x"), version=5
        )
        assert tbl is fake_table
        assert degraded is None
        assert calls == [5]

    def test_falls_back_to_n_minus_1_on_lance_error(self, monkeypatch):
        from server import corpus as corpus_mod  # noqa: PLC0415

        fallback_table = SimpleNamespace(version=4)
        calls: list[int] = []

        def fake_open(lancedb_path=None, version=None):
            calls.append(version)
            if version == 5:
                raise OSError("manifest truncated")
            return fallback_table

        monkeypatch.setattr(corpus_mod, "open_chunks_table", fake_open)
        tbl, degraded = corpus_mod.open_chunks_table_with_fallback(
            lancedb_path=pathlib.Path("/tmp/x"), version=5
        )
        assert tbl is fallback_table
        assert degraded is not None
        assert degraded.reason == "corpus_corruption"
        assert degraded.fallback_version == 4
        assert degraded.original_version == 5
        assert calls == [5, 4]

    def test_raises_at_floor_when_version_is_1(self, monkeypatch):
        from server import corpus as corpus_mod  # noqa: PLC0415

        def fake_open(lancedb_path=None, version=None):
            raise OSError("manifest truncated")

        monkeypatch.setattr(corpus_mod, "open_chunks_table", fake_open)
        with pytest.raises(RuntimeError, match="unrecoverable"):
            corpus_mod.open_chunks_table_with_fallback(
                lancedb_path=pathlib.Path("/tmp/x"), version=1
            )

    def test_raises_when_both_versions_corrupt(self, monkeypatch):
        from server import corpus as corpus_mod  # noqa: PLC0415

        def fake_open(lancedb_path=None, version=None):
            raise OSError(f"manifest v={version} truncated")

        monkeypatch.setattr(corpus_mod, "open_chunks_table", fake_open)
        with pytest.raises(RuntimeError, match="unrecoverable"):
            corpus_mod.open_chunks_table_with_fallback(
                lancedb_path=pathlib.Path("/tmp/x"), version=7
            )


class TestDegradedReadyz:
    """/readyz must return 503 with a degraded body when
    ``resources.degraded`` is set. The shape is documented in
    docs/ops/failure-modes.md."""

    def test_degraded_returns_503_with_reason(self):
        """Build a minimal Resources duck and call readyz
        directly. The full ASGI test path is heavier; this is the
        contract check."""
        from server.corpus import DegradedState  # noqa: PLC0415

        # Build a fake Resources with .warm=True + .degraded set.
        # readyz introspects the dataclass shape; a SimpleNamespace
        # suffices.
        resources = SimpleNamespace(
            warm=True,
            degraded=DegradedState(
                reason="corpus_corruption",
                fallback_version=4,
                original_version=5,
            ),
            is_resource_warm=lambda name: True,
        )

        # Fake the FastAPI Request + app.state.
        scope = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(resources=resources))
        )
        import asyncio  # noqa: PLC0415

        from server.health import readyz  # noqa: PLC0415

        response = asyncio.run(readyz(scope))
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["status"] == "degraded"
        assert body["reason"] == "corpus_corruption"
        assert body["fallback_version"] == 4
        assert body["original_version"] == 5


# ---------------------------------------------------------------------------
# D6 — hosted-embedder fallback
# ---------------------------------------------------------------------------


class TestHostedEmbedderFallback:
    """The Voyage stub always raises; the fallback wrapper must
    route the call to BGE-M3 and stamp ``used_fallback=True``."""

    @pytest.fixture(autouse=True)
    def reset_warned(self):
        from server.query_encoder import (  # noqa: PLC0415
            _reset_hosted_fallback_logged_for_tests,
        )

        _reset_hosted_fallback_logged_for_tests()
        yield
        _reset_hosted_fallback_logged_for_tests()

    def test_local_provider_no_fallback(self, monkeypatch):
        import asyncio  # noqa: PLC0415

        import numpy as np  # noqa: PLC0415

        from server import query_encoder as qe  # noqa: PLC0415

        async def fake_encode(text):
            return np.array([1.0, 2.0], dtype=np.float32)

        monkeypatch.setattr(qe, "encode_query", fake_encode)
        vec, used_fallback = asyncio.run(
            qe.encode_query_with_fallback("hello", "local")
        )
        assert used_fallback is False
        assert vec.shape == (2,)

    def test_voyage_provider_falls_back_to_local(self, monkeypatch):
        import asyncio  # noqa: PLC0415

        import numpy as np  # noqa: PLC0415

        from server import query_encoder as qe  # noqa: PLC0415
        from server.observability.metrics import (  # noqa: PLC0415
            HOSTED_EMBED_FALLBACK_COUNTER,
        )

        async def fake_local(text):
            return np.array([3.0, 4.0], dtype=np.float32)

        monkeypatch.setattr(qe, "encode_query", fake_local)
        # Snapshot the counter so we can assert the increment.
        before = HOSTED_EMBED_FALLBACK_COUNTER.labels(
            provider="voyage"
        )._value.get()

        vec, used_fallback = asyncio.run(
            qe.encode_query_with_fallback("hello", "voyage")
        )
        assert used_fallback is True
        assert vec.shape == (2,)
        after = HOSTED_EMBED_FALLBACK_COUNTER.labels(
            provider="voyage"
        )._value.get()
        assert after == before + 1

    def test_warn_log_fires_once_per_process(self, monkeypatch, caplog):
        import asyncio  # noqa: PLC0415
        import logging  # noqa: PLC0415

        import numpy as np  # noqa: PLC0415

        from server import query_encoder as qe  # noqa: PLC0415

        async def fake_local(text):
            return np.array([1.0], dtype=np.float32)

        monkeypatch.setattr(qe, "encode_query", fake_local)
        with caplog.at_level(logging.WARNING, logger="server.query_encoder"):
            asyncio.run(qe.encode_query_with_fallback("a", "voyage"))
            asyncio.run(qe.encode_query_with_fallback("b", "voyage"))
            asyncio.run(qe.encode_query_with_fallback("c", "voyage"))
        warns = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "voyage" in r.message
        ]
        # WARN-once contract: 3 fallbacks, 1 log entry.
        assert len(warns) == 1
