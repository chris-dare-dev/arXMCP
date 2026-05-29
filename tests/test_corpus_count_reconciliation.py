"""corpus-integrity-observability-m2 — startup reconciliation invariant +
corpus-size gauges.

The motivating bug (m1): a persisted ``corpus-version.json`` ``chunk_count``
silently diverged ~100x from the live table and NOTHING flagged it. m2 adds the
defense-in-depth: at ``Resources.startup`` the server computes ``count_rows()``
ONCE, caches it, reconciles it against the marker, and on divergence beyond a
configurable tolerance logs a WARN + flips ``/readyz`` to ``degraded`` +
exposes a ``/metrics`` gauge pair. WARN-and-serve — retrieval is unaffected.

Tests:
- ``TestComputeChunkCountDivergence`` — the pure decision core (all edge cases:
  FM-2 count-unavailable, FM-3 zero-marker, FM-4 1-row floor, FM-6 direction).
- ``TestStartupReconciliation`` — real ``Resources.startup`` (mocked model)
  degrades on a divergent marker and stays clean on a matching one (AC-1/AC-2).
- ``TestReadyzChunkCountDivergedBody`` — ``/readyz`` serializes the new reason.
- ``TestChunkCountGauges`` — gauges are set from the cached count and are NEVER
  recomputed per scrape (AC-3).
- ``TestDegradedModeEnumeration`` — the reason is in the zero-out enumeration.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from server.config import Config
from server.corpus import DegradedState
from server.resources import Resources, compute_chunk_count_divergence

# ===========================================================================
# Helpers
# ===========================================================================


def _seed_corpus(lancedb_path: Path, *, n: int = 2) -> int:
    """Ingest a tiny n-chunk / n-paper corpus; return its corpus_version.

    Mirrors tests/test_server_startup.py::_seed_corpus. The marker's
    chunk_count == n after this (m1 made the marker table-derived).
    """
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
        for i in range(1, n + 1)
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


def _overwrite_marker_chunk_count(lancedb_path: Path, new_count: int) -> None:
    """Rewrite the marker's chunk_count to simulate a post-write divergence
    (the exact silent-drift the m1 bug produced)."""
    marker = lancedb_path / "corpus-version.json"
    data = json.loads(marker.read_text(encoding="utf-8"))
    data["chunk_count"] = new_count
    marker.write_text(json.dumps(data), encoding="utf-8")


def _patch_model(monkeypatch) -> None:
    """Mock the BGE-M3 load in BOTH the query_encoder module and the
    resources module (resources.py binds ``_get_model`` by name via
    ``from server.query_encoder import _get_model``, so patching only
    query_encoder is insufficient — notebook-retrieval-m2 lesson)."""
    import server.query_encoder as qe_mod
    import server.resources as res_mod

    fake_model = object()
    fake_tokenizer = object()
    for mod in (qe_mod, res_mod):
        monkeypatch.setattr(mod, "_get_model", lambda: fake_model)
        monkeypatch.setattr(mod, "_get_tokenizer", lambda: fake_tokenizer)


def _fake_scrape_resources(**overrides):
    """A SimpleNamespace that survives refresh_metrics_from_singleton_state.

    config=None short-circuits the ops_dir / data_dir sentinel branches;
    chunks_table.count_rows is a Mock so a test can assert the SCRAPE path
    never calls it.
    """
    base = dict(
        corpus_info=SimpleNamespace(version=1, chunk_count=2),
        startup_chunk_count=2,
        process_start_time_seconds=0.0,
        is_resource_warm=lambda n: True,
        cache=None,
        config=None,
        degraded=None,
        chunks_table=SimpleNamespace(count_rows=Mock(return_value=999)),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ===========================================================================
# TestComputeChunkCountDivergence — the pure decision core
# ===========================================================================


class TestComputeChunkCountDivergence:
    def test_matching_counts_no_divergence(self):
        assert compute_chunk_count_divergence(100, 100, 0.05) is None

    def test_within_tolerance_no_divergence(self):
        # |104-100| = 4 ≤ max(1, 5) = 5 → within tolerance.
        assert compute_chunk_count_divergence(100, 104, 0.05) is None

    def test_rows_lost_beyond_tolerance(self):
        # |90-100| = 10 > 5 → diverged, actual < marker.
        assert compute_chunk_count_divergence(100, 90, 0.05) == "rows_lost"

    def test_rows_added_beyond_tolerance(self):
        assert compute_chunk_count_divergence(100, 110, 0.05) == "rows_added"

    def test_tolerance_boundary_is_strict_greater_than(self):
        # exactly at the tolerance (delta == 5 == 5% of 100) is NOT diverged.
        assert compute_chunk_count_divergence(100, 105, 0.05) is None
        assert compute_chunk_count_divergence(100, 106, 0.05) == "rows_added"

    def test_fm2_count_unavailable_sentinel(self):
        # actual_count < 0 is the count_rows()-failed sentinel.
        assert compute_chunk_count_divergence(100, -1, 0.05) is None

    def test_fm3_zero_marker_zero_actual_not_diverged(self):
        # 0/0 must not div-by-zero and is not a divergence (both empty).
        assert compute_chunk_count_divergence(0, 0, 0.05) is None

    def test_fm3_zero_marker_nonzero_actual_diverges(self):
        assert compute_chunk_count_divergence(0, 5, 0.05) == "rows_added"

    def test_fm4_one_row_floor_on_micro_corpus(self):
        # tolerance*marker = 0.5 < 1 → the 1-row floor applies; a single-row
        # delta is within the floor, a two-row delta is not.
        assert compute_chunk_count_divergence(10, 11, 0.05) is None
        assert compute_chunk_count_divergence(10, 12, 0.05) == "rows_added"

    def test_zero_tolerance_still_keeps_one_row_floor(self):
        # tolerance 0.0 → max(1, 0) = 1; a single-row delta is still tolerated.
        assert compute_chunk_count_divergence(100, 101, 0.0) is None
        assert compute_chunk_count_divergence(100, 102, 0.0) == "rows_added"


# ===========================================================================
# TestStartupReconciliation — real Resources.startup (mocked model)
# ===========================================================================


class TestStartupReconciliation:
    def test_divergent_marker_degrades_and_warns(
        self, tmp_path, monkeypatch, caplog
    ):
        """AC-1: a marker diverging beyond tolerance ⇒ WARN + degraded
        with reason=chunk_count_diverged, and the cached count is the
        REAL table count (2), not the bogus marker (1000)."""
        _patch_model(monkeypatch)
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path, n=2)
        _overwrite_marker_chunk_count(lancedb_path, 1000)
        cfg = Config(lancedb_path=lancedb_path)

        with caplog.at_level(logging.WARNING, logger="server.resources"):
            resources = asyncio.run(Resources.startup(cfg))
        try:
            assert resources.degraded is not None
            assert resources.degraded.reason == "chunk_count_diverged"
            assert resources.startup_chunk_count == 2
            warns = [
                r.getMessage()
                for r in caplog.records
                if r.levelno == logging.WARNING
            ]
            assert any("chunk_count DIVERGED" in m for m in warns)
            assert any("marker=1000 actual=2" in m for m in warns)
        finally:
            asyncio.run(resources.shutdown())

    def test_matching_marker_not_degraded(self, tmp_path, monkeypatch):
        """AC-2: matching counts ⇒ not degraded, count cached correctly."""
        _patch_model(monkeypatch)
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path, n=2)  # marker chunk_count == 2 == actual
        cfg = Config(lancedb_path=lancedb_path)

        resources = asyncio.run(Resources.startup(cfg))
        try:
            assert resources.degraded is None
            assert resources.startup_chunk_count == 2
        finally:
            asyncio.run(resources.shutdown())

    def test_corpus_corruption_not_clobbered(
        self, tmp_path, monkeypatch, caplog
    ):
        """F1 / FM-7 (the design's TOP RISK): when a prior corpus_corruption
        N-1 fallback already set ``degraded``, the reconciliation must SKIP —
        a count divergence must NOT downgrade the more-severe corruption
        alert. Fails if the ``degraded is not None`` guard is removed."""
        import server.resources as res_mod  # noqa: PLC0415

        _patch_model(monkeypatch)
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path, n=2)
        _overwrite_marker_chunk_count(lancedb_path, 1000)  # WOULD diverge

        real_open = res_mod.open_chunks_table_with_fallback

        def fake_open(*args, **kwargs):
            tbl, _ = real_open(*args, **kwargs)
            return tbl, DegradedState(
                reason="corpus_corruption",
                fallback_version=0,
                original_version=1,
            )

        monkeypatch.setattr(
            res_mod, "open_chunks_table_with_fallback", fake_open
        )
        cfg = Config(lancedb_path=lancedb_path)

        with caplog.at_level(logging.INFO, logger="server.resources"):
            resources = asyncio.run(Resources.startup(cfg))
        try:
            # The pre-existing corruption reason WINS — not clobbered.
            assert resources.degraded is not None
            assert resources.degraded.reason == "corpus_corruption"
            msgs = [r.getMessage() for r in caplog.records]
            assert any(
                "skipping chunk_count reconciliation" in m for m in msgs
            )
            # corpus-integrity-observability-m3 FM-7: the unindexed-rows check
            # ALSO skips when degraded is already set (more severe) — cached
            # -1, with an INFO note, never clobbering corpus_corruption.
            assert resources.startup_unindexed_rows == -1
            assert any(
                "skipping unindexed-rows check" in m for m in msgs
            )
        finally:
            asyncio.run(resources.shutdown())

    def test_count_rows_raises_is_nonfatal(self, tmp_path, monkeypatch, caplog):
        """F2 / FM-2: a count_rows() failure at startup must NOT abort the
        server (WARN-and-serve). The server starts warm with
        startup_chunk_count = -1, degraded is None, and the FM-2 WARN fires.
        Fails if the try/except around count_rows() is removed."""
        import server.resources as res_mod  # noqa: PLC0415

        _patch_model(monkeypatch)
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path, n=2)

        real_open = res_mod.open_chunks_table_with_fallback

        def fake_open(*args, **kwargs):
            tbl, degraded = real_open(*args, **kwargs)

            class _CountRowsRaises:
                """Delegates everything to the real table EXCEPT count_rows,
                which raises — simulating a transient Lance metadata read
                failure at startup."""

                def __getattr__(self, name):
                    if name == "count_rows":
                        def _raise(*_a, **_k):
                            raise RuntimeError("simulated lance read failure")

                        return _raise
                    return getattr(tbl, name)

            return _CountRowsRaises(), degraded

        monkeypatch.setattr(
            res_mod, "open_chunks_table_with_fallback", fake_open
        )
        cfg = Config(lancedb_path=lancedb_path)

        with caplog.at_level(logging.WARNING, logger="server.resources"):
            resources = asyncio.run(Resources.startup(cfg))
        try:
            assert resources.warm is True  # served, not aborted
            assert resources.startup_chunk_count == -1  # FM-2 sentinel
            assert resources.degraded is None  # divergence skipped, not degraded
            msgs = [r.getMessage() for r in caplog.records]
            assert any("count_rows() failed" in m for m in msgs)
        finally:
            asyncio.run(resources.shutdown())


# ===========================================================================
# TestReadyzChunkCountDivergedBody — /readyz reason wiring (AC-1)
# ===========================================================================


class TestReadyzChunkCountDivergedBody:
    def test_readyz_reports_chunk_count_diverged(self):
        """The existing degraded /readyz path serializes the new reason
        without any handler change."""
        from server.health import readyz  # noqa: PLC0415

        resources = SimpleNamespace(
            warm=True,
            degraded=DegradedState(
                reason="chunk_count_diverged",
                fallback_version=7,
                original_version=7,
            ),
            is_resource_warm=lambda name: True,
        )
        scope = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(resources=resources))
        )
        response = asyncio.run(readyz(scope))
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["status"] == "degraded"
        assert body["reason"] == "chunk_count_diverged"
        assert body["fallback_version"] == 7
        assert body["original_version"] == 7


# ===========================================================================
# TestChunkCountGauges — gauge wiring + AC-3 (never recomputed per scrape)
# ===========================================================================


class TestChunkCountGauges:
    def test_gauges_set_from_cache_not_recomputed_per_scrape(self):
        """AC-3: the two gauges read the cached startup count + marker
        count; a /metrics scrape NEVER calls count_rows()."""
        from server import health as health_mod  # noqa: PLC0415

        resources = _fake_scrape_resources(
            corpus_info=SimpleNamespace(version=1, chunk_count=2),
            startup_chunk_count=2,
        )
        # Three scrapes.
        for _ in range(3):
            health_mod.refresh_metrics_from_singleton_state(resources)

        resources.chunks_table.count_rows.assert_not_called()
        assert health_mod.CORPUS_CHUNK_COUNT_MARKER._value.get() == 2.0
        assert health_mod.CORPUS_CHUNK_COUNT_ACTUAL._value.get() == 2.0

    def test_gauges_expose_the_divergence_delta(self):
        """When the marker lies, the two gauges differ — the operator can
        compute abs(actual - marker) and alert on it."""
        from server import health as health_mod  # noqa: PLC0415

        resources = _fake_scrape_resources(
            corpus_info=SimpleNamespace(version=1, chunk_count=1000),
            startup_chunk_count=2,
        )
        health_mod.refresh_metrics_from_singleton_state(resources)
        assert health_mod.CORPUS_CHUNK_COUNT_MARKER._value.get() == 1000.0
        assert health_mod.CORPUS_CHUNK_COUNT_ACTUAL._value.get() == 2.0

    def test_count_unavailable_sentinel_surfaces_as_minus_one(self):
        """FM-2: count_rows() failed at startup ⇒ startup_chunk_count = -1
        ⇒ the actual gauge reports -1.0 so operators see the count-miss."""
        from server import health as health_mod  # noqa: PLC0415

        resources = _fake_scrape_resources(
            corpus_info=SimpleNamespace(version=1, chunk_count=50),
            startup_chunk_count=-1,
        )
        health_mod.refresh_metrics_from_singleton_state(resources)
        assert health_mod.CORPUS_CHUNK_COUNT_ACTUAL._value.get() == -1.0


# ===========================================================================
# TestDegradedModeEnumeration — chunk_count_diverged in the zero-out loop
# ===========================================================================


class TestDegradedModeEnumeration:
    def test_chunk_count_diverged_zeroed_on_happy_path(self):
        from server import health as health_mod  # noqa: PLC0415
        from server.observability.metrics import (  # noqa: PLC0415
            DEGRADED_MODE_ACTIVE,
        )

        # First light it up, then prove the happy-path zero-out clears it.
        diverged = SimpleNamespace(
            degraded=DegradedState(
                reason="chunk_count_diverged",
                fallback_version=1,
                original_version=1,
            )
        )
        health_mod.refresh_degraded_mode_metric(diverged)
        assert (
            DEGRADED_MODE_ACTIVE.labels(reason="chunk_count_diverged")._value.get()
            == 1.0
        )

        healthy = SimpleNamespace(degraded=None)
        health_mod.refresh_degraded_mode_metric(healthy)
        assert (
            DEGRADED_MODE_ACTIVE.labels(reason="chunk_count_diverged")._value.get()
            == 0.0
        )


# ===========================================================================
# TestConfigToleranceValidator — F3: the tolerance config is bounded [0, 1]
# ===========================================================================


class TestConfigToleranceValidator:
    @pytest.mark.parametrize("bad", [-0.1, 1.5, 2.0])
    def test_out_of_range_rejected(self, bad):
        from pydantic import ValidationError  # noqa: PLC0415

        with pytest.raises(ValidationError, match="CORPUS_CHUNK_COUNT_TOLERANCE"):
            Config(corpus_chunk_count_tolerance=bad)

    @pytest.mark.parametrize("ok", [0.0, 0.05, 0.5, 1.0])
    def test_in_range_accepted(self, ok):
        cfg = Config(corpus_chunk_count_tolerance=ok)
        assert cfg.corpus_chunk_count_tolerance == ok

    def test_default_is_five_percent(self):
        assert Config().corpus_chunk_count_tolerance == 0.05


# ===========================================================================
# corpus-integrity-observability-m3 — HNSW unindexed-rows guard (CAND-10)
# ===========================================================================


def _index_table(real_tbl, *, list_indices, index_stats):
    """Wrap a real LanceDB table, overriding ONLY list_indices/index_stats
    (delegating everything else — count_rows, to_arrow, etc.) so a startup
    test can dictate the unindexed-rows the m3 guard sees."""

    class _Proxy:
        def __getattr__(self, name):
            if name == "list_indices":
                return list_indices
            if name == "index_stats":
                return index_stats
            return getattr(real_tbl, name)

    return _Proxy()


class TestComputeUnindexedRows:
    """The pure D2 decision core: -1 = could-not-determine (no resolvable ANN
    index), 0 = checked & clean, >0 = abnormal. Unit-tested without booting."""

    @staticmethod
    def _table(pairs):
        """pairs: (name, num_unindexed | None) or (name, num, index_type).

        index_type defaults to a vector type ('IVF_HNSW_SQ') so existing cases
        pass the F1 vector-index filter; pass a 3rd element ('BTREE') to model
        the scalar paper_id index that list_indices() also returns.
        """
        norm = [(p[0], p[1], p[2] if len(p) > 2 else "IVF_HNSW_SQ") for p in pairs]

        def list_indices():
            return [SimpleNamespace(name=n, index_type=t) for n, _, t in norm]

        def index_stats(name):
            for n, v, t in norm:
                if n == name:
                    return None if v is None else SimpleNamespace(
                        num_unindexed_rows=v, index_type=t
                    )
            return None

        return SimpleNamespace(list_indices=list_indices, index_stats=index_stats)

    def test_all_clean_returns_zero(self):
        from server.resources import compute_unindexed_rows

        value, breakdown = compute_unindexed_rows(
            self._table([("embedding_stmt_idx", 0), ("embedding_proof_idx", 0)])
        )
        assert value == 0
        assert breakdown == ["embedding_stmt_idx=0", "embedding_proof_idx=0"]

    def test_unindexed_rows_summed(self):
        from server.resources import compute_unindexed_rows

        value, _ = compute_unindexed_rows(
            self._table([("embedding_stmt_idx", 7), ("embedding_proof_idx", 3)])
        )
        assert value == 10

    def test_no_index_returns_minus_one_not_zero(self):
        """D2: a never-indexed corpus brute-forces EVERY row — reporting 0
        would be a dangerous false-clean. Empty list_indices() → -1."""
        from server.resources import compute_unindexed_rows

        value, breakdown = compute_unindexed_rows(self._table([]))
        assert value == -1
        assert breakdown == []

    def test_all_stats_none_returns_minus_one(self):
        from server.resources import compute_unindexed_rows

        value, _ = compute_unindexed_rows(
            self._table([("a", None), ("b", None)])
        )
        assert value == -1  # no resolvable index

    def test_none_stat_is_skipped_not_counted(self):
        from server.resources import compute_unindexed_rows

        value, breakdown = compute_unindexed_rows(
            self._table([("a", None), ("b", 3)])
        )
        assert value == 3  # only the resolvable index counts
        assert breakdown == ["b=3"]

    def test_scalar_index_is_not_counted(self):
        """F1: list_indices() also returns the scalar paper_id BTree. It must NOT
        be counted as an ANN index — only the vector index contributes."""
        from server.resources import compute_unindexed_rows

        value, breakdown = compute_unindexed_rows(
            self._table(
                [
                    ("embedding_stmt_idx", 0, "IVF_HNSW_SQ"),
                    ("paper_id_idx", 0, "BTREE"),
                ]
            )
        )
        assert value == 0
        assert breakdown == ["embedding_stmt_idx=0"]  # scalar excluded

    def test_scalar_only_corpus_returns_minus_one(self):
        """F1 (the cardinal regression): a corpus with ONLY a scalar index (no
        vector index — e.g. vector indexes skipped on empty embedding columns)
        must report -1 (no resolvable ANN index), NOT a false-clean 0. Counting
        the scalar paper_id BTree would defeat the D2 sentinel. Fails on the
        pre-fix unfiltered code (which returned 0)."""
        from server.resources import compute_unindexed_rows

        value, breakdown = compute_unindexed_rows(
            self._table([("paper_id_idx", 0, "BTREE")])
        )
        assert value == -1
        assert breakdown == []


class TestUnindexedRowsStartup:
    """Real Resources.startup (mocked model) wired through the m3 guard via a
    table proxy that dictates list_indices/index_stats."""

    def test_unindexed_rows_warns_and_caches(self, tmp_path, monkeypatch, caplog):
        """AC-1: unindexed rows → WARN + the count cached on Resources."""
        import server.resources as res_mod  # noqa: PLC0415

        _patch_model(monkeypatch)
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path, n=2)
        real_open = res_mod.open_chunks_table_with_fallback

        def fake_open(*args, **kwargs):
            tbl, degraded = real_open(*args, **kwargs)
            li = lambda: [  # noqa: E731
                SimpleNamespace(name="embedding_stmt_idx", index_type="IvfHnswSq"),
                SimpleNamespace(name="embedding_proof_idx", index_type="IvfHnswSq"),
                # the scalar paper_id BTree list_indices() also returns — must be
                # filtered out (F1); if counted it would skew the total.
                SimpleNamespace(name="paper_id_idx", index_type="BTree"),
            ]
            ist = lambda name: SimpleNamespace(  # noqa: E731
                num_unindexed_rows=7 if name == "embedding_stmt_idx" else 0,
                index_type="BTree" if name == "paper_id_idx" else "IVF_HNSW_SQ",
            )
            return _index_table(tbl, list_indices=li, index_stats=ist), degraded

        monkeypatch.setattr(res_mod, "open_chunks_table_with_fallback", fake_open)
        cfg = Config(lancedb_path=lancedb_path)
        with caplog.at_level(logging.WARNING, logger="server.resources"):
            resources = asyncio.run(Resources.startup(cfg))
        try:
            assert resources.startup_unindexed_rows == 7
            assert resources.degraded is None  # NOT a /readyz-degrade (D1)
            assert any(
                "unindexed HNSW rows" in r.getMessage() for r in caplog.records
            )
        finally:
            asyncio.run(resources.shutdown())

    def test_fully_indexed_no_warn(self, tmp_path, monkeypatch, caplog):
        """AC-2: ≥1 index all-clean → 0, no unindexed WARN."""
        import server.resources as res_mod  # noqa: PLC0415

        _patch_model(monkeypatch)
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path, n=2)
        real_open = res_mod.open_chunks_table_with_fallback

        def fake_open(*args, **kwargs):
            tbl, degraded = real_open(*args, **kwargs)
            li = lambda: [  # noqa: E731
                SimpleNamespace(name="embedding_stmt_idx", index_type="IvfHnswSq")
            ]
            ist = lambda name: SimpleNamespace(  # noqa: E731
                num_unindexed_rows=0, index_type="IVF_HNSW_SQ"
            )
            return _index_table(tbl, list_indices=li, index_stats=ist), degraded

        monkeypatch.setattr(res_mod, "open_chunks_table_with_fallback", fake_open)
        cfg = Config(lancedb_path=lancedb_path)
        with caplog.at_level(logging.WARNING, logger="server.resources"):
            resources = asyncio.run(Resources.startup(cfg))
        try:
            assert resources.startup_unindexed_rows == 0
            assert not any(
                "unindexed HNSW rows" in r.getMessage() for r in caplog.records
            )
        finally:
            asyncio.run(resources.shutdown())

    def test_index_api_raises_is_nonfatal(self, tmp_path, monkeypatch, caplog):
        """FM-1/FM-2: list_indices() raising must NOT abort startup — cached
        -1, WARN, server warm, /readyz reachable."""
        import server.resources as res_mod  # noqa: PLC0415

        _patch_model(monkeypatch)
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path, n=2)
        real_open = res_mod.open_chunks_table_with_fallback

        def fake_open(*args, **kwargs):
            tbl, degraded = real_open(*args, **kwargs)

            def li():
                raise RuntimeError("simulated index API failure")

            return (
                _index_table(tbl, list_indices=li, index_stats=lambda n: None),
                degraded,
            )

        monkeypatch.setattr(res_mod, "open_chunks_table_with_fallback", fake_open)
        cfg = Config(lancedb_path=lancedb_path)
        with caplog.at_level(logging.WARNING, logger="server.resources"):
            resources = asyncio.run(Resources.startup(cfg))
        try:
            assert resources.warm is True  # served, not aborted
            assert resources.startup_unindexed_rows == -1
            assert resources.degraded is None
            assert any(
                "index_stats()/list_indices() unavailable" in r.getMessage()
                for r in caplog.records
            )
        finally:
            asyncio.run(resources.shutdown())

    def test_no_resolvable_index_warns_at_boot(
        self, tmp_path, monkeypatch, caplog
    ):
        """F2: the no-resolvable-ANN-index boot path (list_indices() returns []
        cleanly — NOT an exception, e.g. only a scalar index, or vector indexes
        skipped) reaches the DISTINCT `elif < 0` WARN ("no resolvable ANN index
        found / coverage UNKNOWN"), separate from the API-raises branch. Pins -1
        + that WARN end-to-end; fails if the elif branch is removed."""
        import server.resources as res_mod  # noqa: PLC0415

        _patch_model(monkeypatch)
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path, n=2)
        real_open = res_mod.open_chunks_table_with_fallback

        def fake_open(*args, **kwargs):
            tbl, degraded = real_open(*args, **kwargs)
            return (
                _index_table(
                    tbl, list_indices=lambda: [], index_stats=lambda n: None
                ),
                degraded,
            )

        monkeypatch.setattr(res_mod, "open_chunks_table_with_fallback", fake_open)
        cfg = Config(lancedb_path=lancedb_path)
        with caplog.at_level(logging.WARNING, logger="server.resources"):
            resources = asyncio.run(Resources.startup(cfg))
        try:
            assert resources.warm is True
            assert resources.startup_unindexed_rows == -1
            assert resources.degraded is None
            msgs = [r.getMessage() for r in caplog.records]
            assert any("no resolvable ANN index found" in m for m in msgs)
            # the DISTINCT no-index WARN, not the API-raises one
            assert not any(
                "index_stats()/list_indices() unavailable" in m for m in msgs
            )
        finally:
            asyncio.run(resources.shutdown())


class TestUnindexedRowsGauge:
    """The gauge reads the startup-cached value and NEVER re-queries the index
    API per scrape (the 'computed once at startup' contract)."""

    def test_gauge_set_from_cache_not_recomputed_per_scrape(self):
        from server import health as health_mod  # noqa: PLC0415

        resources = _fake_scrape_resources(startup_unindexed_rows=7)
        # chunks_table carries list_indices/index_stats Mocks so we can assert
        # the scrape path never touches the index API.
        resources.chunks_table.list_indices = Mock(return_value=[])
        resources.chunks_table.index_stats = Mock(return_value=None)
        for _ in range(3):
            health_mod.refresh_metrics_from_singleton_state(resources)
        resources.chunks_table.list_indices.assert_not_called()
        resources.chunks_table.index_stats.assert_not_called()
        assert health_mod.CORPUS_UNINDEXED_ROWS._value.get() == 7.0

    def test_minus_one_sentinel_surfaces_on_gauge(self):
        from server import health as health_mod  # noqa: PLC0415

        resources = _fake_scrape_resources(startup_unindexed_rows=-1)
        health_mod.refresh_metrics_from_singleton_state(resources)
        assert health_mod.CORPUS_UNINDEXED_ROWS._value.get() == -1.0
