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
    INGEST_LAST_RUN_CHUNKS,
    INGEST_LAST_RUN_PAPERS,
    INGEST_LAST_RUN_TIMESTAMP_SECONDS,
    LATEXML_DRIFT_DETECTED_GAUGE,
    LEAN_REPL_AGE_SECONDS_GAUGE,
    LEAN_REPL_ENV_SNAPSHOTS_GAUGE,
    refresh_lean_repl_metrics,
    reset_drift_metrics_for_tests,
    reset_eval_metrics_for_tests,
    reset_lean_repl_metrics_for_tests,
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
    reset_lean_repl_metrics_for_tests()
    reset_metrics_for_tests()
    yield
    reset_request_metrics_for_tests()
    reset_embed_metrics_for_tests()
    reset_drift_metrics_for_tests()
    reset_eval_metrics_for_tests()
    reset_sentinel_metrics_for_tests()
    reset_lean_repl_metrics_for_tests()
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
        # Colon-free timestamps: ":" is illegal in Windows filenames. The
        # production reader (server.health._refresh_eval_ndcg5) globs
        # corpus_v<N>-*.json and selects by mtime, so the exact timestamp
        # text is irrelevant — only the corpus_v<N> prefix + mtime matter.
        old = reports_dir / "corpus_v3-2026-05-01T00-00-00.json"
        new = reports_dir / "corpus_v3-2026-05-14T00-00-00.json"
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


class TestF1OversizedSentinel:
    """F1 rectification — every read_text on a sentinel must enforce
    :data:`server.health._MAX_SENTINEL_BYTES` so a 100 GB
    ``drift-detected.flag`` (attacker, or buggy cron) cannot OOM the
    server at /metrics scrape time."""

    def test_oversized_drift_flag_falls_through_to_touchfile(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        from server import health as health_mod  # noqa: PLC0415

        # Write a file larger than the cap. Cap is 64 KB; we write
        # 65 KB and confirm the body is NEVER read.
        big = tmp_path / "drift-detected.flag"
        big.write_bytes(b"x" * (health_mod._MAX_SENTINEL_BYTES + 1024))
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)
        assert LATEXML_DRIFT_DETECTED_GAUGE._value.get() == 1.0
        assert any(
            "is " in rec.message and "bytes (cap is " in rec.message
            for rec in caplog.records
        )

    def test_oversized_backup_status_is_ignored(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        from server import health as health_mod  # noqa: PLC0415

        # First seed a known-good backup status so we have a prior
        # observable value.
        (tmp_path / "backup-status.json").write_text(
            json.dumps(
                {"status": "ok", "finished_at": "2026-05-14T03:00:00+00:00"}
            )
        )
        refresh_sentinel_metrics(tmp_path)
        prior_ts = BACKUP_LAST_SUCCESS_GAUGE._value.get()
        assert prior_ts > 0

        # Replace with an oversized file — the scrape hook must
        # refuse to parse it AND leave the prior gauges intact
        # (operator-facing semantics: "the prior known-good value
        # is more useful than a 0 zero" — same as malformed-JSON
        # behavior).
        (tmp_path / "backup-status.json").write_bytes(
            b"{" + b"x" * (health_mod._MAX_SENTINEL_BYTES + 1)
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == prior_ts


class TestNonObjectJsonSentinel:
    """A sentinel whose body is VALID JSON of the wrong SHAPE must not
    500 the /metrics scrape.

    Every reader in :func:`server.health.refresh_sentinel_metrics` pulls
    fields with ``.get``, which only a mapping has. Two of them guarded
    with ``if payload is not None`` and one had no guard at all, so a
    top-level array / string / number / bool raised ``AttributeError`` —
    a type named in none of their ``except`` tuples. It escaped the
    reader, escaped ``refresh_sentinel_metrics``, and took the whole
    scrape with it: EVERY gauge went dark, not just the one whose file
    was bad. ``compute_health_status`` (the /status consumer) has always
    guarded with ``isinstance(payload, dict)``; these tests pin the
    /metrics readers to the same contract.

    Expected behavior for an unusable sentinel on this path is the one
    the malformed-JSON cases already established — **leave the prior
    gauge values and log a WARNING**. Zeroing is wrong here: on the
    backup path a 0.0 asserts "no backup has ever succeeded", which an
    unparseable file is not evidence for.
    """

    # Valid JSON, none of it an object.
    NON_OBJECT_BODIES = ["[1, 2, 3]", '"a string"', "123", "true", "null"]

    def _seed_good_backup(self, ops_dir: Path) -> float:
        (ops_dir / "backup-status.json").write_text(
            json.dumps(
                {"status": "ok", "finished_at": "2026-05-14T03:00:00+00:00"}
            ),
            encoding="utf-8",
        )
        refresh_sentinel_metrics(ops_dir)
        prior = BACKUP_LAST_SUCCESS_GAUGE._value.get()
        assert prior > 0
        return prior

    @pytest.mark.parametrize("body", NON_OBJECT_BODIES)
    def test_backup_status_non_object_does_not_raise(
        self, tmp_path: Path, body: str, reset_all_metrics
    ):
        """The reported case: ``[1, 2, 3]`` -> AttributeError -> scrape 500."""
        (tmp_path / "backup-status.json").write_text(body, encoding="utf-8")
        refresh_sentinel_metrics(tmp_path)  # must not raise

    def test_backup_status_non_object_leaves_prior_and_warns(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        prior = self._seed_good_backup(tmp_path)
        (tmp_path / "backup-status.json").write_text(
            "[1, 2, 3]", encoding="utf-8"
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)

        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == prior
        # Not zeroed either — the state cells keep the last known verdict.
        assert BACKUP_STATUS_GAUGE.labels(state="ok")._value.get() == 1.0
        assert any(
            "backup-status.json" in rec.message
            and "not a JSON object" in rec.message
            for rec in caplog.records
        )

    def test_oversized_backup_status_does_not_double_warn(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        """An oversized file also yields ``payload is None``, but
        ``_read_capped`` has already logged it. The shape guard must not
        add a second, misleading "not a JSON object" line for a file it
        never even read."""
        from server import health as health_mod

        self._seed_good_backup(tmp_path)
        (tmp_path / "backup-status.json").write_bytes(
            b"{" + b"x" * (health_mod._MAX_SENTINEL_BYTES + 1)
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)

        assert not any(
            "not a JSON object" in rec.message for rec in caplog.records
        )
        assert any("cap is " in rec.message for rec in caplog.records)

    @pytest.mark.parametrize("body", NON_OBJECT_BODIES)
    def test_ingest_summary_non_object_does_not_raise(
        self, tmp_path: Path, body: str, reset_all_metrics
    ):
        (tmp_path / "ingest-summary.json").write_text(body, encoding="utf-8")
        refresh_sentinel_metrics(tmp_path)  # must not raise

    def test_ingest_summary_non_object_leaves_prior_and_warns(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        INGEST_LAST_RUN_PAPERS.set(42.0)
        INGEST_LAST_RUN_CHUNKS.set(4242.0)
        (tmp_path / "ingest-summary.json").write_text(
            "[1, 2, 3]", encoding="utf-8"
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)

        assert INGEST_LAST_RUN_PAPERS._value.get() == 42.0
        assert INGEST_LAST_RUN_CHUNKS._value.get() == 4242.0
        assert any(
            "ingest-summary.json" in rec.message
            and "not a JSON object" in rec.message
            for rec in caplog.records
        )

    @pytest.mark.parametrize("bad_count", [None, [1, 2], {"n": 1}])
    def test_ingest_summary_wrong_typed_count_leaves_prior(
        self, tmp_path: Path, bad_count, caplog, reset_all_metrics
    ):
        """Right shape, wrong field type. ``float(None)`` raises TypeError,
        which was absent from this reader's ``except`` tuple — so a
        schema-v1 object with a null count crashed the scrape exactly like
        a top-level array did."""
        INGEST_LAST_RUN_PAPERS.set(42.0)
        (tmp_path / "ingest-summary.json").write_text(
            json.dumps({"schema_version": 1, "papers_processed": bad_count}),
            encoding="utf-8",
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)

        assert INGEST_LAST_RUN_PAPERS._value.get() == 42.0
        assert any(
            "ingest-summary.json" in rec.message for rec in caplog.records
        )

    def test_ingest_summary_bad_second_count_leaves_both_prior(
        self, tmp_path: Path, reset_all_metrics
    ):
        """"Leave the prior values" must cover ALL the gauges the reader
        owns. With the coercions done inline at their ``.set`` call sites,
        a wrong-typed SECOND count raised only after the first gauge had
        already been written — so a rejected file still moved the papers
        gauge, landing on a state that is neither the new reading nor the
        prior one."""
        INGEST_LAST_RUN_PAPERS.set(42.0)
        INGEST_LAST_RUN_CHUNKS.set(4242.0)
        (tmp_path / "ingest-summary.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "papers_processed": 52,          # fine on its own
                    "chunks_written_this_run": None,  # blows up after it
                }
            ),
            encoding="utf-8",
        )
        refresh_sentinel_metrics(tmp_path)

        assert INGEST_LAST_RUN_PAPERS._value.get() == 42.0
        assert INGEST_LAST_RUN_CHUNKS._value.get() == 4242.0

    @pytest.mark.parametrize("body", NON_OBJECT_BODIES)
    def test_eval_report_non_object_does_not_raise(
        self, tmp_path: Path, body: str, reset_all_metrics
    ):
        """Third reader with the same shape — ``_refresh_eval_ndcg5`` had
        no guard at all."""
        reports_dir = tmp_path / "eval-reports"
        reports_dir.mkdir()
        (reports_dir / "corpus_v3-2026-05-14T00-00-00.json").write_text(
            body, encoding="utf-8"
        )
        refresh_sentinel_metrics(tmp_path)  # must not raise

    def test_eval_report_non_object_skips_only_that_file(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        """One bad report must not cost the other versions their gauge."""
        reports_dir = tmp_path / "eval-reports"
        reports_dir.mkdir()
        (reports_dir / "corpus_v3-2026-05-14T00-00-00.json").write_text(
            "[1, 2, 3]", encoding="utf-8"
        )
        (reports_dir / "corpus_v4-2026-05-14T00-00-00.json").write_text(
            json.dumps({"ndcg5_mean": 0.42}), encoding="utf-8"
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)

        assert EVAL_NDCG5_GAUGE.labels(
            corpus_version="4"
        )._value.get() == pytest.approx(0.42)
        assert any(
            "eval-report" in rec.message and "not a JSON object" in rec.message
            for rec in caplog.records
        )

    @pytest.mark.parametrize("bad_count", [None, [1, 2], {"n": 1}])
    def test_drift_flag_wrong_typed_fixture_count_is_touchfile(
        self, tmp_path: Path, bad_count, caplog, reset_all_metrics
    ):
        """``_read_drift_flag``'s docstring promises "non-numeric
        ``fixture_count`` -> 1.0 with a WARNING", but ``float(None)``
        raises TypeError, which its ``except`` tuple did not name."""
        (tmp_path / "drift-detected.flag").write_text(
            json.dumps({"fixture_count": bad_count}), encoding="utf-8"
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)

        assert LATEXML_DRIFT_DETECTED_GAUGE._value.get() == 1.0
        assert any(
            "drift-detected.flag" in rec.message for rec in caplog.records
        )

    def test_one_bad_sentinel_does_not_darken_the_whole_scrape(
        self, tmp_path: Path, reset_all_metrics
    ):
        """The operator-visible consequence, pinned directly.

        ``backup-status.json`` is read BEFORE ingest-summary and the eval
        reports, so an escaping AttributeError meant a single malformed
        file zeroed out the observability surface for gauges that had
        nothing to do with it. Every later sentinel must still refresh.
        """
        (tmp_path / "backup-status.json").write_text(
            "[1, 2, 3]", encoding="utf-8"
        )
        (tmp_path / "drift-detected.flag").write_text(
            json.dumps({"fixture_count": 7}), encoding="utf-8"
        )
        (tmp_path / "eval-quarantine.flag").write_text("", encoding="utf-8")
        (tmp_path / "ingest-summary.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "papers_processed": 52,
                    "chunks_written_this_run": 4820,
                }
            ),
            encoding="utf-8",
        )
        reports_dir = tmp_path / "eval-reports"
        reports_dir.mkdir()
        (reports_dir / "corpus_v9-2026-05-14T00-00-00.json").write_text(
            json.dumps({"ndcg5_mean": 0.33}), encoding="utf-8"
        )

        refresh_sentinel_metrics(tmp_path)

        # Read before the bad file.
        assert LATEXML_DRIFT_DETECTED_GAUGE._value.get() == 7.0
        assert EVAL_QUARANTINE_ACTIVE_GAUGE._value.get() == 1.0
        # Read AFTER the bad file — these are what the crash used to eat.
        assert INGEST_LAST_RUN_PAPERS._value.get() == 52.0
        assert INGEST_LAST_RUN_CHUNKS._value.get() == 4820.0
        assert EVAL_NDCG5_GAUGE.labels(
            corpus_version="9"
        )._value.get() == pytest.approx(0.33)


class TestF2SingleflightCounter:
    """F2 rectification — the brief AC#3 named
    ``arxmcp_embed_singleflight_dedup_total`` increment on concurrent
    identical queries. The scrape hook in
    :func:`refresh_metrics_from_singleton_state` rehydrates the
    Prometheus counter from the source-of-truth integer
    :data:`server.query_encoder.SINGLEFLIGHT_DEDUP_COUNT` via a
    monotonic delta. A regression that flipped the delta sign would
    not have been caught without this test."""

    def test_counter_rehydrates_from_source_of_truth(
        self, monkeypatch, reset_all_metrics
    ):
        import server.query_encoder as qe_mod  # noqa: PLC0415
        from server import health as health_mod  # noqa: PLC0415

        # Reset the module-level delta tracker so the increment math
        # starts from a known 0.
        health_mod._LAST_DEDUP_COUNT = 0
        # Pretend the singleflight has dedup'd 3 queries by now.
        monkeypatch.setattr(
            qe_mod, "get_singleflight_dedup_count", lambda: 3
        )

        fake_resources = SimpleNamespace(
            # corpus-integrity-observability-m2: the gauge setters read
            # corpus_info.chunk_count + startup_chunk_count directly, so a
            # fully-shaped Resources fake must carry both fields.
            corpus_info=SimpleNamespace(version=1, chunk_count=2),
            startup_chunk_count=2,
            process_start_time_seconds=0.0,
            is_resource_warm=lambda n: True,
            cache=None,
            config=None,
        )
        # Reset the prometheus Counter to 0 first so we observe a
        # pure delta increment. The counter is module-level and
        # may have prior values from earlier tests.
        try:
            health_mod.EMBED_SINGLEFLIGHT_DEDUP_COUNTER.reset()
        except AttributeError:
            health_mod.EMBED_SINGLEFLIGHT_DEDUP_COUNTER._value.set(0)

        health_mod.refresh_metrics_from_singleton_state(fake_resources)
        assert health_mod.EMBED_SINGLEFLIGHT_DEDUP_COUNTER._value.get() == 3.0

        # A subsequent scrape with no further dedup must NOT
        # re-increment the counter (the delta tracker absorbs the
        # already-counted hits).
        health_mod.refresh_metrics_from_singleton_state(fake_resources)
        assert health_mod.EMBED_SINGLEFLIGHT_DEDUP_COUNTER._value.get() == 3.0

        # A new dedup hit DOES increment.
        monkeypatch.setattr(
            qe_mod, "get_singleflight_dedup_count", lambda: 5
        )
        health_mod.refresh_metrics_from_singleton_state(fake_resources)
        assert health_mod.EMBED_SINGLEFLIGHT_DEDUP_COUNTER._value.get() == 5.0


class TestF4BackupUnknownState:
    """F4 rectification — an unrecognised backup-status value lights
    up the ``unknown`` cell rather than silently zeroing every
    state. Prevents alert suppression for a regression-to-future-
    state-string failure mode in the backup wrapper."""

    def test_unknown_status_routes_to_unknown_cell(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        (tmp_path / "backup-status.json").write_text(
            json.dumps(
                {
                    "status": "degraded",
                    "finished_at": "2026-05-14T03:00:00+00:00",
                }
            )
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)
        assert BACKUP_STATUS_GAUGE.labels(state="unknown")._value.get() == 1.0
        assert BACKUP_STATUS_GAUGE.labels(state="ok")._value.get() == 0.0
        assert BACKUP_STATUS_GAUGE.labels(state="failed")._value.get() == 0.0
        assert any(
            "unknown state 'degraded'" in rec.message for rec in caplog.records
        )


class TestF7BackupStatusZSuffix:
    """F7 regression guard — the ``finished_at`` field may end in
    ``Z`` (RFC-3339 UTC shorthand). Python 3.11+ supports this
    natively; the prior code path had a dead ``.replace("Z", "+00:00")``
    shim. A regression to a stricter parser must not silently zero
    ``BACKUP_LAST_SUCCESS_GAUGE``."""

    def test_z_suffix_parses_to_same_epoch_as_plus_offset(
        self, tmp_path: Path, reset_all_metrics
    ):
        from datetime import UTC, datetime  # noqa: PLC0415

        (tmp_path / "backup-status.json").write_text(
            json.dumps(
                {"status": "ok", "finished_at": "2026-05-14T03:00:00Z"}
            )
        )
        refresh_sentinel_metrics(tmp_path)
        expected = datetime(2026, 5, 14, 3, 0, 0, tzinfo=UTC).timestamp()
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == expected


class TestF5UnserializableStructuredContent:
    """F5 rectification — a handler whose ``structuredContent`` is
    not JSON-serializable produces a WARNING log (previously DEBUG)
    so operators have a positive signal that the metric is
    undercounting. Silent metric cold-out was the E08_S03 F11
    lesson applied to the new metric-recording layer."""

    def test_warning_logged_when_structured_content_not_serializable(
        self, caplog, reset_all_metrics
    ):
        # A datetime is not JSON-serializable by default.
        from datetime import UTC, datetime  # noqa: PLC0415

        bad_payload = SimpleNamespace(
            structuredContent={"when": datetime(2026, 1, 1, tzinfo=UTC)}
        )

        async def handler():
            return bad_payload

        wrapped = _wrap_with_metrics("bad_tool", handler)
        with caplog.at_level("WARNING"):
            asyncio.run(wrapped())
        assert any(
            "RESULT_BYTES record failed for bad_tool" in rec.message
            for rec in caplog.records
        )
        # The handler still returned successfully — the request
        # counter records ok status even though byte-size recording
        # failed (metric-recording is best-effort).
        assert _counter_value(REQUEST_COUNTER, tool="bad_tool", status="ok") == 1.0


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
# lean-repl-observability-m1 — Lean REPL telemetry scrape hook
# ===========================================================================


class TestLeanReplMetrics:
    """``refresh_lean_repl_metrics`` scrape hook: the gauges reflect a live
    REPL's env-snapshot count + age, and read a clean 0 on the disabled
    (``None``) path — even after a prior nonzero value (the module-level
    gauge-persistence hazard AC3 guards against). A minimal duck-typed fake
    stands in for the real ``LeanRepl`` (the hook reads two attributes)."""

    def test_none_repl_sets_both_gauges_to_zero(self, reset_all_metrics):
        # Seed prior stale values first to prove the None branch EXPLICITLY
        # zeroes (a bare no-op would leave these — the refresh_cache_metrics
        # hazard the disabled-path AC calls out).
        LEAN_REPL_ENV_SNAPSHOTS_GAUGE.set(9.0)
        LEAN_REPL_AGE_SECONDS_GAUGE.set(123.0)
        refresh_lean_repl_metrics(None)
        assert LEAN_REPL_ENV_SNAPSHOTS_GAUGE._value.get() == 0.0
        assert LEAN_REPL_AGE_SECONDS_GAUGE._value.get() == 0.0

    def test_live_repl_reflects_snapshot_count_and_age(self, reset_all_metrics):
        fake = SimpleNamespace(env_snapshot_count=7, age_seconds=42.5)
        refresh_lean_repl_metrics(fake)
        assert LEAN_REPL_ENV_SNAPSHOTS_GAUGE._value.get() == 7.0
        assert LEAN_REPL_AGE_SECONDS_GAUGE._value.get() == 42.5

    def test_disabled_after_live_returns_to_zero(self, reset_all_metrics):
        # Live (nonzero) then disabled (e.g. a respawn failed and the handler
        # set resources.lean_repl = None) must zero on the next scrape.
        refresh_lean_repl_metrics(
            SimpleNamespace(env_snapshot_count=3, age_seconds=5.0)
        )
        assert LEAN_REPL_ENV_SNAPSHOTS_GAUGE._value.get() == 3.0
        refresh_lean_repl_metrics(None)
        assert LEAN_REPL_ENV_SNAPSHOTS_GAUGE._value.get() == 0.0
        assert LEAN_REPL_AGE_SECONDS_GAUGE._value.get() == 0.0

    def test_gauges_appear_in_exposition(self, reset_all_metrics):
        # Unlabeled gauges register at import, so both names render at 0 in
        # the default-registry exposition even before any scrape (AC1's
        # "/metrics exposes ..." holds for the disabled path too).
        from prometheus_client import generate_latest  # noqa: PLC0415

        text = generate_latest().decode("utf-8")
        assert "arxmcp_lean_repl_env_snapshots" in text
        assert "arxmcp_lean_repl_age_seconds" in text

    def test_singleton_refresh_reflects_live_repl(
        self, monkeypatch, reset_all_metrics
    ):
        """M1 rectification — drive the gauges THROUGH the real
        ``refresh_metrics_from_singleton_state`` wiring (``server/health.py``
        ``refresh_lean_repl_metrics(getattr(resources, "lean_repl", None))``),
        not by calling ``refresh_lean_repl_metrics`` directly. The class's
        other tests exercise the hook in isolation, so a dropped scrape line
        or a rename of ``Resources.lean_repl`` would silently drive both
        gauges to 0 forever with the suite still green — the exact
        silent-zero failure this milestone exists to prevent. Mirrors
        ``TestF2SingleflightCounter``: a fully-shaped Resources fake carries
        every field the setters read (corpus_info + startup_chunk_count +
        singleflight source-of-truth), plus the ``lean_repl`` field."""
        import server.query_encoder as qe_mod  # noqa: PLC0415
        from server import health as health_mod  # noqa: PLC0415

        # refresh_metrics_from_singleton_state also reads the singleflight
        # dedup source-of-truth; pin it so the unrelated hook is a no-op.
        health_mod._LAST_DEDUP_COUNT = 0
        monkeypatch.setattr(qe_mod, "get_singleflight_dedup_count", lambda: 0)

        fake = SimpleNamespace(
            corpus_info=SimpleNamespace(version=1, chunk_count=2),
            startup_chunk_count=2,
            process_start_time_seconds=0.0,
            is_resource_warm=lambda n: True,
            cache=None,
            config=None,
            lean_repl=SimpleNamespace(env_snapshot_count=7, age_seconds=42.5),
        )
        health_mod.refresh_metrics_from_singleton_state(fake)
        assert LEAN_REPL_ENV_SNAPSHOTS_GAUGE._value.get() == 7.0
        assert LEAN_REPL_AGE_SECONDS_GAUGE._value.get() == 42.5

        # Disabled path THROUGH the real wiring: getattr -> None must
        # explicitly zero both gauges (not leave the prior live values).
        fake.lean_repl = None
        health_mod.refresh_metrics_from_singleton_state(fake)
        assert LEAN_REPL_ENV_SNAPSHOTS_GAUGE._value.get() == 0.0
        assert LEAN_REPL_AGE_SECONDS_GAUGE._value.get() == 0.0


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

        **F3 rationale (E14_S01 adversary critique).** The brief
        names ``promtool check metrics`` as the validator. We use
        ``prometheus_client.parser.text_string_to_metric_families``
        instead because (a) ``promtool`` is a Go binary that is
        not guaranteed on developer or CI environments, and a
        skip-if-missing test creates false-green coverage that
        looks landed but isn't; (b) the parser exercises the SAME
        format-conformance contract — HELP/TYPE/sample line
        validity — that ``promtool`` does, by invoking the
        prometheus-client library's own parser. The two validators
        diverge only on aggressively-pedantic surface rules
        (e.g. trailing-newline strictness, comment-line placement)
        that the prometheus_client generator already conforms to
        because it IS the canonical generator. Operators who want
        ``promtool``-level paranoia can pipe ``curl /metrics``
        through ``promtool check metrics`` manually.
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


# ===========================================================================
# corpus-integrity-observability-e3 — ingest-summary.json reader tests
# ===========================================================================


class TestIngestSummaryReader:
    """FM-4, FM-5, FM-7 mitigations for the ingest-summary.json reader block
    in :func:`server.health.refresh_sentinel_metrics`."""

    def _seed_valid(self, ops_dir: Path) -> None:
        """Write a valid v1 ingest-summary.json to ops_dir."""
        import json as _json  # noqa: PLC0415

        payload = {
            "schema_version": 1,
            "driver": "bulk_ingest",
            "finished_at": "2026-05-29T04:00:00Z",
            "elapsed_seconds": 312.4,
            "papers_processed": 52,
            "papers_succeeded": 50,
            "papers_failed": 2,
            "chunks_written_this_run": 4820,
            "total_rows_after_commit": 10298,
        }
        (ops_dir / "ingest-summary.json").write_text(
            _json.dumps(payload) + "\n", encoding="utf-8"
        )

    def test_present_valid_sets_gauges(self, tmp_path: Path, reset_all_metrics):
        """FM-4 (present): all three gauges are set from the file."""
        from datetime import UTC, datetime  # noqa: PLC0415

        self._seed_valid(tmp_path)
        refresh_sentinel_metrics(tmp_path)
        assert INGEST_LAST_RUN_PAPERS._value.get() == 52.0
        assert INGEST_LAST_RUN_CHUNKS._value.get() == 4820.0
        expected_ts = datetime(2026, 5, 29, 4, 0, 0, tzinfo=UTC).timestamp()
        assert INGEST_LAST_RUN_TIMESTAMP_SECONDS._value.get() == pytest.approx(
            expected_ts
        )

    def test_absent_zeros_all_gauges(self, tmp_path: Path, reset_all_metrics):
        """FM-4 (absent): all three gauges must be set to 0.0 (no ingest yet)."""
        # Seed prior non-zero values so we can confirm they are zeroed.
        INGEST_LAST_RUN_PAPERS.set(99.0)
        INGEST_LAST_RUN_CHUNKS.set(9999.0)
        INGEST_LAST_RUN_TIMESTAMP_SECONDS.set(1.0)

        refresh_sentinel_metrics(tmp_path)
        assert INGEST_LAST_RUN_PAPERS._value.get() == 0.0
        assert INGEST_LAST_RUN_CHUNKS._value.get() == 0.0
        assert INGEST_LAST_RUN_TIMESTAMP_SECONDS._value.get() == 0.0

    def test_oversized_leaves_prior(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        """FM-5 oversized: _read_capped returns None → leave prior gauges."""
        from server import health as health_mod  # noqa: PLC0415

        # Seed a valid read first so we have a prior value.
        self._seed_valid(tmp_path)
        refresh_sentinel_metrics(tmp_path)
        prior_papers = INGEST_LAST_RUN_PAPERS._value.get()
        assert prior_papers == 52.0

        # Replace with an oversized file.
        (tmp_path / "ingest-summary.json").write_bytes(
            b"{" + b"x" * (health_mod._MAX_SENTINEL_BYTES + 1)
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)
        # Prior gauges must be preserved.
        assert INGEST_LAST_RUN_PAPERS._value.get() == prior_papers

    def test_malformed_json_warns_and_leaves_prior(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        """FM-5 malformed: WARN + leave prior, no crash."""
        self._seed_valid(tmp_path)
        refresh_sentinel_metrics(tmp_path)
        prior_papers = INGEST_LAST_RUN_PAPERS._value.get()

        (tmp_path / "ingest-summary.json").write_text(
            "{{not valid json}}", encoding="utf-8"
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)
        # Prior value preserved.
        assert INGEST_LAST_RUN_PAPERS._value.get() == prior_papers
        assert any(
            "ingest-summary.json" in rec.message for rec in caplog.records
        )

    def test_schema_version_mismatch_warns_and_leaves_prior(
        self, tmp_path: Path, caplog, reset_all_metrics
    ):
        """FM-7: unknown schema_version → WARN + leave prior, no crash, no zero."""
        import json as _json  # noqa: PLC0415

        # Seed a valid read first.
        self._seed_valid(tmp_path)
        refresh_sentinel_metrics(tmp_path)
        prior_papers = INGEST_LAST_RUN_PAPERS._value.get()
        assert prior_papers == 52.0

        # Write a future-version file.
        payload = {
            "schema_version": 99,  # unknown future version
            "papers_processed": 999,
        }
        (tmp_path / "ingest-summary.json").write_text(
            _json.dumps(payload) + "\n", encoding="utf-8"
        )
        with caplog.at_level("WARNING"):
            refresh_sentinel_metrics(tmp_path)
        # Prior gauges must NOT be overwritten.
        assert INGEST_LAST_RUN_PAPERS._value.get() == prior_papers
        assert any(
            "unknown schema_version" in rec.message for rec in caplog.records
        )

    def test_schema_version_mismatch_does_not_zero_gauges(
        self, tmp_path: Path, reset_all_metrics
    ):
        """FM-7 regression guard: schema_version mismatch must NOT silently zero.
        A zero reads as 'never ingested', which is worse than stale."""
        import json as _json  # noqa: PLC0415

        # Seed known prior values.
        INGEST_LAST_RUN_PAPERS.set(42.0)
        INGEST_LAST_RUN_CHUNKS.set(4242.0)
        INGEST_LAST_RUN_TIMESTAMP_SECONDS.set(1748476800.0)

        (tmp_path / "ingest-summary.json").write_text(
            _json.dumps({"schema_version": 2, "papers_processed": 999}) + "\n",
            encoding="utf-8",
        )
        refresh_sentinel_metrics(tmp_path)
        # All three gauges must retain their prior values, not drop to zero.
        assert INGEST_LAST_RUN_PAPERS._value.get() == 42.0
        assert INGEST_LAST_RUN_CHUNKS._value.get() == 4242.0
        assert INGEST_LAST_RUN_TIMESTAMP_SECONDS._value.get() == 1748476800.0
