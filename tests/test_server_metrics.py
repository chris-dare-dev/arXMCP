"""E14_S01 — request-level / embedder / reranker / sentinel
Prometheus surface tests.

Coverage map (synthesis decisions → test):

  D3  dispatcher wrapper             TestDispatcherWrapper
  D4  embed counter                  TestEmbedderMetrics
  D5  sentinel-file scrape hook      TestSentinelScrapeHook
  D6  EVAL_NDCG5 label cardinality   TestEvalNdcg5LabelCap
  D10 /metrics endpoint shape        TestMetricsEndpoint

The default test path uses lightweight fakes — we exercise the wrap
+ scrape paths directly rather than spinning the full BGE-M3 model.
The integration check (``TestMetricsEndpoint``) reuses the
``warm_app`` pattern from :mod:`tests.test_server_startup` so the
prometheus output is rendered through the same ASGI mount the
operator scrapes.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from server.config import Config
from server.health import (
    refresh_sentinel_metrics,
    reset_metrics_for_tests,
)
from server.main import create_app
from server.metrics import (
    BACKUP_LAST_SUCCESS_GAUGE,
    BACKUP_STATUS_GAUGE,
    DELTA_TIMEOUT_ACTIVE_GAUGE,
    EVAL_NDCG5_GAUGE,
    EVAL_QUARANTINE_ACTIVE_GAUGE,
    LATEXML_DRIFT_DETECTED_GAUGE,
    reset_drift_metrics_for_tests,
    reset_eval_metrics_for_tests,
    reset_sentinel_metrics_for_tests,
)
from server.observability.metrics import (
    EMBED_CALLS_COUNTER,
    EMBED_LATENCY,
    REQUEST_COUNTER,
    REQUEST_INFLIGHT,
    REQUEST_LATENCY,
    RESULT_BYTES,
    reset_embed_metrics_for_tests,
    reset_request_metrics_for_tests,
)
from server.tools import _wrap_with_metrics

# ===========================================================================
# Fixtures (mirror tests/test_server_startup.py)
# ===========================================================================


def _seed_corpus(lancedb_path: Path) -> int:
    chunks = [
        ChunkRecord(
            chunk_id=f"arxiv:2307.0000{i}:{'0' * 16}",
            paper_id=f"2307.0000{i}",
            kind="stmt",
            section_path=[],
            theorem_name=None,
            theorem_label=None,
            body_text=f"chunk body {i}",
            body_tokens=f"chunk body {i}",
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
        )
        for i in (1, 2)
    ]
    rng = np.random.default_rng(42)
    rows = []
    for _ in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        rows.append(v)
    embeddings = EmbedRecord(
        chunk_ids_stmt=[c.chunk_id for c in chunks],
        embedding_stmt=np.stack(rows, axis=0),
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )
    return write_chunks(chunks, embeddings, lancedb_path=lancedb_path)


@pytest.fixture
def mocked_bge_m3(monkeypatch):
    import server.query_encoder as qe_mod

    fake_model = object()
    fake_tokenizer = object()
    monkeypatch.setattr(qe_mod, "_get_model", lambda: fake_model)
    monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: fake_tokenizer)
    yield


@pytest.fixture
def seeded_lancedb(tmp_path: Path) -> Path:
    lancedb_path = tmp_path / "lancedb"
    _seed_corpus(lancedb_path)
    return lancedb_path


@pytest.fixture
def reset_all_metrics():
    """Reset every metric family this milestone touches.

    The same reset is needed before AND after each test because
    prometheus_client uses module-level registries that persist
    across tests in the same process — leakage from one test would
    confuse the next.
    """
    reset_request_metrics_for_tests()
    reset_embed_metrics_for_tests()
    reset_drift_metrics_for_tests()
    reset_eval_metrics_for_tests()
    reset_sentinel_metrics_for_tests()
    reset_metrics_for_tests()
    yield
    reset_request_metrics_for_tests()
    reset_embed_metrics_for_tests()
    reset_drift_metrics_for_tests()
    reset_eval_metrics_for_tests()
    reset_sentinel_metrics_for_tests()
    reset_metrics_for_tests()


def _counter_value(counter, **labels) -> float:
    """Read a Counter cell's current value via the documented-private
    ``._value`` accessor (the same accessor the reset helpers use)."""
    return counter.labels(**labels)._value.get()


def _histogram_sample_count(histogram, **labels) -> int:
    """Sum a Histogram cell's bucket-count entries; mirrors what
    ``histogram._sum`` exposes but reads through the public
    ``.collect()`` API so we don't depend on the private layout."""
    metric = next(iter(histogram.collect()))
    target_labels = sorted(labels.items())
    for sample in metric.samples:
        if sample.name.endswith("_count"):
            sample_labels = sorted(
                (k, v) for k, v in sample.labels.items() if k != "le"
            )
            if sample_labels == target_labels:
                return int(sample.value)
    return 0


# ===========================================================================
# D3 — dispatcher wrapper
# ===========================================================================


class TestDispatcherWrapper:
    def test_ok_path_increments_counter_and_records_latency(
        self, reset_all_metrics
    ):
        result_payload = SimpleNamespace(structuredContent={"k": "v"})

        async def handler() -> SimpleNamespace:
            return result_payload

        wrapped = _wrap_with_metrics("test_tool", handler)
        out = asyncio.run(wrapped())
        assert out is result_payload

        assert _counter_value(REQUEST_COUNTER, tool="test_tool", status="ok") == 1.0
        assert _counter_value(REQUEST_COUNTER, tool="test_tool", status="error") == 0.0
        assert _histogram_sample_count(REQUEST_LATENCY, tool="test_tool") == 1
        assert _histogram_sample_count(RESULT_BYTES, tool="test_tool") == 1
        # In-flight returns to zero in the finally block.
        assert REQUEST_INFLIGHT.labels(tool="test_tool")._value.get() == 0.0

    def test_error_path_records_error_status_and_does_not_record_bytes(
        self, reset_all_metrics
    ):
        async def handler() -> None:
            raise RuntimeError("boom")

        wrapped = _wrap_with_metrics("err_tool", handler)
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(wrapped())

        assert _counter_value(REQUEST_COUNTER, tool="err_tool", status="error") == 1.0
        assert _counter_value(REQUEST_COUNTER, tool="err_tool", status="ok") == 0.0
        # Latency is recorded for both ok and error.
        assert _histogram_sample_count(REQUEST_LATENCY, tool="err_tool") == 1
        # RESULT_BYTES is ok-path only.
        assert _histogram_sample_count(RESULT_BYTES, tool="err_tool") == 0
        # In-flight returns to zero even on raise.
        assert REQUEST_INFLIGHT.labels(tool="err_tool")._value.get() == 0.0

    def test_signature_is_preserved_via_functools_wraps(self):
        async def handler(x: int, y: str = "z") -> dict[str, Any]:
            return {"x": x, "y": y}

        wrapped = _wrap_with_metrics("sig_tool", handler)
        # functools.wraps copies __wrapped__ so inspect.signature can
        # see through to the original function — FastMCP introspects
        # the handler signature for the input-schema, so wrapping
        # must be transparent at that boundary.
        import inspect

        sig = inspect.signature(wrapped)
        assert list(sig.parameters) == ["x", "y"]


# ===========================================================================
# D4 — embedder metrics (mocked model path)
# ===========================================================================


class TestEmbedderMetrics:
    def test_embed_counter_increments_on_encode_query_sync(
        self, monkeypatch, reset_all_metrics
    ):
        """The forward-pass path increments EMBED_CALLS_COUNTER and
        records EMBED_LATENCY exactly once per call."""
        import server.query_encoder as qe_mod

        # Fake tokenizer returns a dict-shaped object that supports
        # ``**encoded`` unpacking but the model below ignores its
        # contents — we just need the with-torch.no_grad path to run.
        class _FakeOutput:
            def __init__(self, dim: int):
                import torch  # noqa: PLC0415

                self.last_hidden_state = torch.zeros((1, 4, dim))

        class _FakeModel:
            def __call__(self, **kwargs):  # noqa: ANN003
                return _FakeOutput(EMBEDDING_DIM)

        def _fake_tokenizer(texts, **kwargs):  # noqa: ANN001, ANN003
            import torch  # noqa: PLC0415

            return {
                "input_ids": torch.zeros((1, 4), dtype=torch.long),
                "attention_mask": torch.ones((1, 4), dtype=torch.long),
            }

        monkeypatch.setattr(qe_mod, "_get_model", lambda: _FakeModel())
        monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: _fake_tokenizer)

        vec = qe_mod._encode_query_sync("a test query")
        assert vec.shape == (EMBEDDING_DIM,)

        assert _counter_value(EMBED_CALLS_COUNTER, model="bge-m3", outcome="ok") == 1.0
        assert (
            _counter_value(EMBED_CALLS_COUNTER, model="bge-m3", outcome="error") == 0.0
        )
        assert _histogram_sample_count(EMBED_LATENCY, model="bge-m3") == 1


# ===========================================================================
# D5 — sentinel-file scrape hook
# ===========================================================================


class TestSentinelScrapeHook:
    def test_drift_flag_touchfile_sets_gauge_to_one(
        self, tmp_path: Path, reset_all_metrics
    ):
        (tmp_path / "drift-detected.flag").write_text("")
        refresh_sentinel_metrics(tmp_path)
        assert LATEXML_DRIFT_DETECTED_GAUGE._value.get() == 1.0

    def test_drift_flag_json_body_sets_gauge_to_fixture_count(
        self, tmp_path: Path, reset_all_metrics
    ):
        (tmp_path / "drift-detected.flag").write_text(
            json.dumps({"fixture_count": 7})
        )
        refresh_sentinel_metrics(tmp_path)
        assert LATEXML_DRIFT_DETECTED_GAUGE._value.get() == 7.0

    def test_drift_flag_absent_sets_gauge_to_zero(
        self, tmp_path: Path, reset_all_metrics
    ):
        # No file at tmp_path/drift-detected.flag.
        LATEXML_DRIFT_DETECTED_GAUGE.set(9.0)  # prior stale value
        refresh_sentinel_metrics(tmp_path)
        assert LATEXML_DRIFT_DETECTED_GAUGE._value.get() == 0.0

    def test_eval_quarantine_and_delta_timeout_touchfiles(
        self, tmp_path: Path, reset_all_metrics
    ):
        (tmp_path / "eval-quarantine.flag").write_text("")
        (tmp_path / "delta-timeout.flag").write_text("")
        refresh_sentinel_metrics(tmp_path)
        assert EVAL_QUARANTINE_ACTIVE_GAUGE._value.get() == 1.0
        assert DELTA_TIMEOUT_ACTIVE_GAUGE._value.get() == 1.0

        # Removing the touch files zeroes the gauges on next refresh.
        (tmp_path / "eval-quarantine.flag").unlink()
        (tmp_path / "delta-timeout.flag").unlink()
        refresh_sentinel_metrics(tmp_path)
        assert EVAL_QUARANTINE_ACTIVE_GAUGE._value.get() == 0.0
        assert DELTA_TIMEOUT_ACTIVE_GAUGE._value.get() == 0.0

    def test_backup_status_ok(self, tmp_path: Path, reset_all_metrics):
        (tmp_path / "backup-status.json").write_text(
            json.dumps(
                {
                    "status": "ok",
                    "finished_at": "2026-05-14T03:00:00+00:00",
                }
            )
        )
        refresh_sentinel_metrics(tmp_path)

        # Expected epoch for 2026-05-14T03:00:00+00:00
        from datetime import UTC, datetime  # noqa: PLC0415

        expected = datetime(
            2026, 5, 14, 3, 0, 0, tzinfo=UTC
        ).timestamp()
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == expected
        assert BACKUP_STATUS_GAUGE.labels(state="ok")._value.get() == 1.0
        assert BACKUP_STATUS_GAUGE.labels(state="failed")._value.get() == 0.0
        assert BACKUP_STATUS_GAUGE.labels(state="running")._value.get() == 0.0

    def test_backup_status_failed_is_exclusive(
        self, tmp_path: Path, reset_all_metrics
    ):
        # First write ok.
        (tmp_path / "backup-status.json").write_text(
            json.dumps(
                {"status": "ok", "finished_at": "2026-05-14T03:00:00+00:00"}
            )
        )
        refresh_sentinel_metrics(tmp_path)
        assert BACKUP_STATUS_GAUGE.labels(state="ok")._value.get() == 1.0

        # Then overwrite as failed; the ``ok`` cell must zero.
        (tmp_path / "backup-status.json").write_text(
            json.dumps(
                {"status": "failed", "finished_at": "2026-05-14T04:00:00+00:00"}
            )
        )
        refresh_sentinel_metrics(tmp_path)
        assert BACKUP_STATUS_GAUGE.labels(state="failed")._value.get() == 1.0
        assert BACKUP_STATUS_GAUGE.labels(state="ok")._value.get() == 0.0

    def test_eval_ndcg5_picks_latest_report_per_version(
        self, tmp_path: Path, reset_all_metrics
    ):
        reports_dir = tmp_path / "eval-reports"
        reports_dir.mkdir()
        old = reports_dir / "corpus_v3-2026-05-01T00:00:00.json"
        new = reports_dir / "corpus_v3-2026-05-14T00:00:00.json"
        old.write_text(json.dumps({"ndcg5_mean": 0.10}))
        new.write_text(json.dumps({"ndcg5_mean": 0.42}))
        # Force ``new``'s mtime to be later than ``old``'s.
        old_mtime = time.time() - 3600
        new_mtime = time.time()
        import os  # noqa: PLC0415

        os.utime(old, (old_mtime, old_mtime))
        os.utime(new, (new_mtime, new_mtime))

        refresh_sentinel_metrics(tmp_path)
        assert (
            EVAL_NDCG5_GAUGE.labels(corpus_version="3")._value.get()
            == pytest.approx(0.42)
        )


class TestEvalNdcg5LabelCap:
    def test_only_five_most_recent_versions_kept(
        self, tmp_path: Path, reset_all_metrics
    ):
        reports_dir = tmp_path / "eval-reports"
        reports_dir.mkdir()
        # Seven distinct versions; only the five highest must survive.
        for v in range(1, 8):
            (reports_dir / f"corpus_v{v}-stamp.json").write_text(
                json.dumps({"ndcg5_mean": 0.1 * v})
            )

        refresh_sentinel_metrics(tmp_path)

        # Expect labels for versions 3..7 (five most-recent by integer).
        present = {labelvalues[0] for labelvalues in EVAL_NDCG5_GAUGE._metrics}
        assert present == {"3", "4", "5", "6", "7"}


# ===========================================================================
# D10 — /metrics endpoint end-to-end
# ===========================================================================


class TestMetricsEndpoint:
    def test_metrics_endpoint_returns_valid_prometheus_text(
        self, seeded_lancedb, mocked_bge_m3, reset_all_metrics
    ):
        """AC1 + AC6 — the rendered output parses with
        ``prometheus_client.parser.text_string_to_metric_families``.

        Closes the E14_S01 brief's exposition AC by exercising the
        actual ASGI mount path the operator hits — not by reading
        the registry directly.
        """
        cfg = Config(lancedb_path=seeded_lancedb, ops_dir=Path("/tmp/nonexistent-ops"))
        app = create_app(cfg)
        with TestClient(app) as client:
            r = client.get("/metrics")
            assert r.status_code == 200
            text = r.text
            # Validate the exposition format parses end-to-end.
            families = list(text_string_to_metric_families(text))
            assert len(families) > 0
            family_names = {f.name for f in families}
            # The new request-level + embed + rerank + sentinel metric
            # names should appear once the registry has been populated
            # by any module import (counters are zero-valued until
            # invoked but DO render in exposition).
            assert "arxmcp_request" in family_names or any(
                n.startswith("arxmcp_request") for n in family_names
            )

    def test_metrics_endpoint_records_request_after_tool_call(
        self, seeded_lancedb, mocked_bge_m3, reset_all_metrics
    ):
        """AC2 — `arxmcp_request_total{tool,status}` records an
        increment for each tool invocation via the dispatcher wrapper.

        We invoke the wrapped handler synthetically (no real BGE-M3
        forward pass needed) and confirm the gauge surfaces at
        ``/metrics``.
        """
        cfg = Config(lancedb_path=seeded_lancedb, ops_dir=Path("/tmp/nonexistent-ops"))
        app = create_app(cfg)
        with TestClient(app) as client:
            # Hit /metrics once just to confirm endpoint is alive.
            assert client.get("/metrics").status_code == 200

            # Increment via the wrapper directly — equivalent to a
            # real tool call but without a LanceDB scan.
            async def handler():
                return SimpleNamespace(structuredContent={"ok": True})

            wrapped = _wrap_with_metrics("search_papers", handler)
            asyncio.run(wrapped())

            text = client.get("/metrics").text
            # The counter line for the ok path must appear.
            assert (
                'arxmcp_request_total{status="ok",tool="search_papers"} 1.0'
                in text
                or
                'arxmcp_request_total{tool="search_papers",status="ok"} 1.0'
                in text
            )
