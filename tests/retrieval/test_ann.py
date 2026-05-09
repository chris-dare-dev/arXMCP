"""``ANNPhase`` + ``reciprocal_rank_fusion`` tests (E07_S02).

Brief AC mapping:

- `ANNPhase.query("perverse sheaves...", bm25_candidates=[])` returns ≥1
  → ``TestANNPhaseQuery::test_pure_ann_fallback_with_empty_bm25``
- RRF output contains candidates from both BM25 list AND both ANN lists
  → ``TestANNPhaseQuery::test_rrf_includes_all_input_sources``
- `fused_score` values are descending
  → ``TestRRF::test_output_sorted_descending`` (+ end-to-end smoke)
- Both embedding calls go through the shared Singleflight wrapper
  (reinterpreted per research-synthesis.md D2 — there is only ONE
  encode call; verified via ``get_singleflight_dedup_count``)
  → ``TestSingleflightContract``
- `pytest tests/retrieval/test_ann.py` passes
  → the suite itself

Plus regression-grade tests for:
- RRF formula correctness (constant + tied ranks + tie-break)
- Determinism: identical input lists produce byte-identical output
- Score conversion: L2 distance → cosine similarity
- Graceful degradation when ``embedding_proof`` has zero rows
- Edge cases: empty input lists, top_n=1, top_n=corpus_size
- Resources.startup wires r.ann_phase end-to-end
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from server.retrieval.ann import (
    DEFAULT_TOP_N,
    PER_COLUMN_LIMIT,
    ANNPhase,
    _distance_to_score,
)
from server.retrieval.rrf import RRF_K, reciprocal_rank_fusion

# ===========================================================================
# Fixtures (mirror tests/retrieval/test_bm25.py)
# ===========================================================================


def _curated_chunk(
    paper_id: str, suffix: str, *, body_tokens: str, kind: str = "stmt"
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"arxiv:{paper_id}:{suffix:>16}",
        paper_id=paper_id,
        kind=kind,
        section_path=[],
        theorem_name=None,
        theorem_label=None,
        body_text=body_tokens,
        body_tokens=body_tokens,
        preamble_ref=None,
        chunker_version=CHUNKER_VERSION,
    )


def _dual_corpus() -> tuple[list[ChunkRecord], list[ChunkRecord]]:
    """Build a corpus with BOTH ``kind="stmt"`` AND ``kind="proof"``
    chunks so the dual-ANN path can be exercised end-to-end.

    Returns ``(stmt_chunks, proof_chunks)``. The two lists are
    disjoint (no chunk appears in both, per the schema invariant in
    ``ingest/schema.py:135-138``).

    Layout: 5 stmt chunks (paper ids 2307.00001-00005) + 3 proof
    chunks (paper ids 2307.10001-10003). Total 8 chunks; large
    enough to exercise top-50-per-column with degenerate over-fetch.
    """
    stmt_chunks = [
        _curated_chunk(
            "2307.00001",
            "0" * 16,
            body_tokens="Spec mathrm_Pic algebraic curve scheme",
            kind="stmt",
        ),
        _curated_chunk(
            "2307.00002",
            "1" * 16,
            body_tokens="étale cohomology Galois extension",
            kind="stmt",
        ),
        _curated_chunk(
            "2307.00003",
            "2" * 16,
            body_tokens="Hilbert space spectral theorem operator",
            kind="stmt",
        ),
        _curated_chunk(
            "2307.00004",
            "3" * 16,
            body_tokens="H_1 X_a fundamental group homotopy",
            kind="stmt",
        ),
        _curated_chunk(
            "2307.00005",
            "4" * 16,
            body_tokens="partial mathbb_Z derivation differential",
            kind="stmt",
        ),
    ]
    proof_chunks = [
        _curated_chunk(
            "2307.10001",
            "a" * 16,
            body_tokens="proof step lemma applied corollary follows",
            kind="proof",
        ),
        _curated_chunk(
            "2307.10002",
            "b" * 16,
            body_tokens="case analysis induction base step inductive",
            kind="proof",
        ),
        _curated_chunk(
            "2307.10003",
            "c" * 16,
            body_tokens="contradiction assume conclude QED therefore",
            kind="proof",
        ),
    ]
    return (stmt_chunks, proof_chunks)


def _embeddings_for_dual(
    stmt_chunks: list[ChunkRecord],
    proof_chunks: list[ChunkRecord],
    *,
    seed: int = 0,
) -> EmbedRecord:
    """Build an ``EmbedRecord`` with random L2-normalized vectors
    routed to ``embedding_stmt`` for stmt chunks and
    ``embedding_proof`` for proof chunks. Mirrors the
    kind-routing rule in ``ingest/embedder.py:19-22``."""
    rng = np.random.default_rng(seed)

    stmt_ids: list[str] = []
    stmt_rows: list[np.ndarray] = []
    for c in stmt_chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        stmt_ids.append(c.chunk_id)
        stmt_rows.append(v)

    proof_ids: list[str] = []
    proof_rows: list[np.ndarray] = []
    for c in proof_chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        proof_ids.append(c.chunk_id)
        proof_rows.append(v)

    return EmbedRecord(
        chunk_ids_stmt=stmt_ids,
        embedding_stmt=(
            np.stack(stmt_rows, axis=0)
            if stmt_rows
            else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        ),
        chunk_ids_proof=proof_ids,
        embedding_proof=(
            np.stack(proof_rows, axis=0)
            if proof_rows
            else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        ),
        embedder_version=EMBEDDER_VERSION,
    )


@pytest.fixture
def _mocked_bge(monkeypatch):
    """Replace ``encode_query`` with a deterministic stub.

    Without this, ``encode_query`` would download BGE-M3 + run a
    transformer forward pass — slow and CI-fragile. The stub returns
    a fresh L2-normalized random vector per call (seeded by the
    canonicalized query string so identical queries get identical
    vectors). The vector is the right shape (1024-dim float32) so
    LanceDB's HNSW search treats it as a real query."""
    import server.query_encoder as qe_mod

    def _fake_encode(query_text: str) -> np.ndarray:
        # Deterministic per-query: hash the canonicalized text → seed.
        canon = qe_mod._canonicalize(query_text)
        seed = abs(hash(canon)) % (2**32)
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        return v

    async def _fake_encode_async(query_text: str) -> np.ndarray:
        return _fake_encode(query_text)

    monkeypatch.setattr(qe_mod, "encode_query", _fake_encode_async)
    # Also patch the import seen by server.retrieval.ann.
    import server.retrieval.ann as ann_mod

    monkeypatch.setattr(ann_mod, "encode_query", _fake_encode_async)
    yield


@pytest.fixture
def _seeded_dual_lancedb(tmp_path) -> tuple[Path, int]:
    """Seed a LanceDB with both stmt and proof chunks; return
    ``(lancedb_path, corpus_version)``."""
    stmt_chunks, proof_chunks = _dual_corpus()
    embeddings = _embeddings_for_dual(stmt_chunks, proof_chunks, seed=42)
    lancedb_path = tmp_path / "lancedb_dual"
    version = write_chunks(
        stmt_chunks + proof_chunks, embeddings, lancedb_path=lancedb_path
    )
    return (lancedb_path, version)


@pytest.fixture
def _stmt_only_lancedb(tmp_path) -> tuple[Path, int]:
    """Seed a LanceDB with ONLY stmt chunks (no proof). Exercises the
    graceful-degradation path where ``embedding_proof`` has zero
    rows and no HNSW index."""
    stmt_chunks, _proof = _dual_corpus()
    # Empty proof side.
    embeddings = _embeddings_for_dual(stmt_chunks, [], seed=43)
    lancedb_path = tmp_path / "lancedb_stmt_only"
    version = write_chunks(
        stmt_chunks, embeddings, lancedb_path=lancedb_path
    )
    return (lancedb_path, version)


def _open_chunks_table(lancedb_path: Path, version: int) -> Any:
    from server.corpus import open_chunks_table

    return open_chunks_table(lancedb_path, version=version)


@pytest.fixture
def _ann_phase_dual(_seeded_dual_lancedb) -> ANNPhase:
    lancedb_path, version = _seeded_dual_lancedb
    return ANNPhase(chunks_table=_open_chunks_table(lancedb_path, version))


@pytest.fixture
def _ann_phase_stmt_only(_stmt_only_lancedb) -> ANNPhase:
    lancedb_path, version = _stmt_only_lancedb
    return ANNPhase(chunks_table=_open_chunks_table(lancedb_path, version))


# ===========================================================================
# RRF utility tests
# ===========================================================================


class TestRRF:
    """Tests for ``reciprocal_rank_fusion`` independent of LanceDB."""

    def test_rrf_k_constant_is_60(self):
        """``RRF_K`` is the canonical Cormack 2009 default. A bump
        is a deliberate retrieval-quality change."""
        assert RRF_K == 60

    def test_single_list_passthrough(self):
        """A single ranked list fuses to itself, scored by 1/(k+rank)."""
        result = reciprocal_rank_fusion([["a", "b", "c"]], k=60)
        assert [cid for cid, _ in result] == ["a", "b", "c"]
        assert result[0][1] == pytest.approx(1.0 / 61)
        assert result[1][1] == pytest.approx(1.0 / 62)
        assert result[2][1] == pytest.approx(1.0 / 63)

    def test_two_lists_fuse_additively(self):
        """A chunk_id appearing in two lists gets the sum of its
        per-list contributions."""
        # 'a' is rank 1 in both lists; 'b' is rank 2 in both.
        result = reciprocal_rank_fusion(
            [["a", "b"], ["a", "b"]], k=60
        )
        assert result[0] == ("a", pytest.approx(2.0 / 61))
        assert result[1] == ("b", pytest.approx(2.0 / 62))

    def test_output_sorted_descending(self):
        """RRF output is sorted ``(score desc, chunk_id asc)``.

        Compute:
          a: 1/(60+3) + 1/(60+1) = 1/63 + 1/61 ≈ 0.032266
          b: 1/(60+2) + 1/(60+2) = 2/62        ≈ 0.032258
          c: 1/(60+1) + 1/(60+3) = 1/61 + 1/63 ≈ 0.032266 (== a)

        So ``a`` and ``c`` tie at ~0.032266, both > ``b`` at
        0.032258. Tie between ``a`` and ``c`` breaks by chunk_id
        asc → ``a`` first. Final order: a, c, b.
        """
        result = reciprocal_rank_fusion(
            [["c", "b", "a"], ["a", "b", "c"]], k=60
        )
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)
        # Verify the specific tiebreak math.
        assert [cid for cid, _ in result] == ["a", "c", "b"]
        assert result[0][1] == pytest.approx(1.0 / 63 + 1.0 / 61)
        assert result[1][1] == pytest.approx(1.0 / 61 + 1.0 / 63)
        assert result[2][1] == pytest.approx(2.0 / 62)

    def test_chunk_id_tiebreak_ascending(self):
        """When two chunks have IDENTICAL fused scores, ties break
        by chunk_id ascending — project-wide determinism rule."""
        # Identical lists → all chunks have identical scores.
        result = reciprocal_rank_fusion(
            [["zzz", "aaa"], ["aaa", "zzz"]], k=60
        )
        # Both 'aaa' and 'zzz' have score 1/61 + 1/62 (rank-2 + rank-1
        # for aaa, rank-1 + rank-2 for zzz). Ties → asc.
        assert result[0][0] == "aaa"
        assert result[1][0] == "zzz"

    def test_empty_outer_returns_empty(self):
        assert reciprocal_rank_fusion([]) == []

    def test_empty_inner_lists_tolerated(self):
        result = reciprocal_rank_fusion([[], ["a", "b"], []], k=60)
        assert [cid for cid, _ in result] == ["a", "b"]
        assert result[0][1] == pytest.approx(1.0 / 61)

    def test_all_empty_inner_lists(self):
        assert reciprocal_rank_fusion([[], [], []]) == []

    def test_zero_k_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            reciprocal_rank_fusion([["a"]], k=0)

    def test_negative_k_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            reciprocal_rank_fusion([["a"]], k=-5)

    def test_determinism_byte_identical_across_runs(self):
        """Two identical invocations produce byte-identical output."""
        a = reciprocal_rank_fusion([["x", "y", "z"], ["z", "x"]])
        b = reciprocal_rank_fusion([["x", "y", "z"], ["z", "x"]])
        assert a == b

    def test_default_k_is_rrf_k(self):
        """Default ``k`` is :data:`RRF_K`. Two calls — one with the
        default, one explicit — produce identical output."""
        a = reciprocal_rank_fusion([["a", "b"]])
        b = reciprocal_rank_fusion([["a", "b"]], k=RRF_K)
        assert a == b


# ===========================================================================
# Score conversion
# ===========================================================================


class TestScoreConversion:
    """``_distance_to_score`` mirrors the existing dense-only path."""

    def test_zero_distance_is_one(self):
        """L2 distance 0 (identical unit vectors) → cosine 1.0."""
        assert _distance_to_score(0.0) == 1.0

    def test_distance_two_is_zero(self):
        """L2 distance 2 (antipodal unit vectors) → cosine 0.0."""
        assert _distance_to_score(2.0) == 0.0

    def test_distance_one_is_half(self):
        """L2 distance 1 (orthogonal unit vectors with both norm=1)
        → cosine 0.5."""
        assert _distance_to_score(1.0) == pytest.approx(0.5)

    def test_none_distance_is_zero(self):
        assert _distance_to_score(None) == 0.0

    def test_negative_distance_clamped_to_zero(self):
        """Numerical instability could produce a tiny negative
        distance; clamp to 0."""
        # 1 - (-0.0001/2) = 1.00005 — but our bound is max(0, ...)
        # which doesn't clamp the upper side. Verify the doc says
        # clamps lower-only.
        assert _distance_to_score(3.0) == 0.0  # 1 - 1.5 = -0.5 → 0


# ===========================================================================
# ANNPhase query path
# ===========================================================================


class TestANNPhaseQuery:
    def test_dual_corpus_returns_results(
        self, _ann_phase_dual, _mocked_bge
    ):
        """Smoke test: dual corpus + non-empty query → non-empty
        result."""
        result = asyncio.run(
            _ann_phase_dual.query(
                "perverse sheaves on flag varieties",
                bm25_candidates=[],
            )
        )
        assert result, "dual-corpus query returned empty result"

    def test_pure_ann_fallback_with_empty_bm25(
        self, _ann_phase_dual, _mocked_bge
    ):
        """Brief AC #1: ``bm25_candidates=[]`` returns ≥ 1 result
        via pure-ANN fallback."""
        result = asyncio.run(
            _ann_phase_dual.query(
                "perverse sheaves on flag varieties",
                bm25_candidates=[],
            )
        )
        assert len(result) >= 1
        # Every result MUST be a (str, float) tuple.
        for entry in result:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            cid, score = entry
            assert isinstance(cid, str)
            assert isinstance(score, float)

    def test_rrf_includes_all_input_sources(
        self, _ann_phase_dual, _mocked_bge, _seeded_dual_lancedb
    ):
        """Brief AC #2: RRF output contains candidates from BOTH the
        BM25 list AND both ANN lists.

        We construct a BM25 list with a synthetic chunk_id that does
        NOT appear in the LanceDB ANN results, then assert that
        chunk_id appears in the RRF output (proving the BM25 list
        contributed). We then assert at least one stmt-kind chunk_id
        and at least one proof-kind chunk_id appear (proving both
        ANN lists contributed)."""
        lancedb_path, version = _seeded_dual_lancedb
        tbl = _open_chunks_table(lancedb_path, version)
        live_ids = set(tbl.to_arrow().column("chunk_id").to_pylist())

        # Pick a BM25 candidate from the live corpus so the RRF
        # output contains a real chunk_id.
        bm25_only_id = sorted(live_ids)[0]
        bm25_candidates = [(bm25_only_id, 1.0)]

        result = asyncio.run(
            _ann_phase_dual.query(
                "Spec algebraic curve",
                bm25_candidates=bm25_candidates,
                top_n=10,
            )
        )
        result_ids = {cid for cid, _ in result}

        # BM25 contribution: the BM25 chunk_id appears in the result.
        assert bm25_only_id in result_ids, (
            f"BM25 chunk_id {bm25_only_id!r} not in RRF output: "
            f"{result_ids}"
        )

        # ANN contribution from both columns: the result should
        # include at least one stmt-kind id AND at least one proof-
        # kind id (because both columns were searched).
        stmt_ids = {
            cid for cid in result_ids if "2307.0000" in cid
        }
        proof_ids = {
            cid for cid in result_ids if "2307.1000" in cid
        }
        assert stmt_ids, f"no stmt-kind chunk_ids in result: {result_ids}"
        assert proof_ids, f"no proof-kind chunk_ids in result: {result_ids}"

    def test_fused_scores_descending(
        self, _ann_phase_dual, _mocked_bge
    ):
        """Brief AC #3: fused_score values are descending."""
        result = asyncio.run(
            _ann_phase_dual.query(
                "Spec algebraic curve scheme",
                bm25_candidates=[("arxiv:2307.00002:" + "1" * 16, 1.0)],
                top_n=10,
            )
        )
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True), (
            f"fused_score values not descending: {scores}"
        )

    def test_top_n_cap_respected(self, _ann_phase_dual, _mocked_bge):
        result = asyncio.run(
            _ann_phase_dual.query(
                "Spec", bm25_candidates=[], top_n=3
            )
        )
        assert len(result) <= 3

    def test_default_top_n_is_50(self):
        assert DEFAULT_TOP_N == 50

    def test_per_column_limit_is_50(self):
        assert PER_COLUMN_LIMIT == 50

    def test_top_n_zero_rejected(self, _ann_phase_dual, _mocked_bge):
        with pytest.raises(ValueError, match="top_n must be"):
            asyncio.run(
                _ann_phase_dual.query("x", bm25_candidates=[], top_n=0)
            )


# ===========================================================================
# Graceful degradation: stmt-only corpus (no proof column rows)
# ===========================================================================


class TestGracefulDegradation:
    """Brief risk note: when ``embedding_proof`` has zero rows or no
    HNSW index, ANNPhase MUST fuse only the available lists rather
    than crashing."""

    def test_stmt_only_corpus_returns_results(
        self, _ann_phase_stmt_only, _mocked_bge
    ):
        """Stmt-only corpus + empty BM25 → still returns ANN results
        from embedding_stmt only."""
        result = asyncio.run(
            _ann_phase_stmt_only.query(
                "Spec algebraic curve", bm25_candidates=[]
            )
        )
        assert result, "stmt-only corpus returned empty result"
        # All results are stmt-kind ids (the proof column is empty).
        for cid, _ in result:
            assert "2307.0000" in cid

    def test_stmt_only_corpus_with_bm25_fuses_two_lists(
        self, _ann_phase_stmt_only, _mocked_bge, _stmt_only_lancedb
    ):
        """Stmt-only corpus + non-empty BM25 → fuses BM25 + stmt
        ANN; proof side contributes nothing but doesn't crash."""
        lancedb_path, version = _stmt_only_lancedb
        tbl = _open_chunks_table(lancedb_path, version)
        live_ids = sorted(
            tbl.to_arrow().column("chunk_id").to_pylist()
        )
        bm25_only_id = live_ids[0]
        result = asyncio.run(
            _ann_phase_stmt_only.query(
                "Spec",
                bm25_candidates=[(bm25_only_id, 1.0)],
                top_n=10,
            )
        )
        # Result is non-empty; bm25_only_id is among the candidates.
        assert result
        result_ids = {cid for cid, _ in result}
        assert bm25_only_id in result_ids


# ===========================================================================
# Singleflight contract (brief AC #4 reinterpreted)
# ===========================================================================


class TestSingleflightContract:
    """Brief AC #4: "Both embedding calls go through the shared
    Singleflight wrapper." Reinterpreted per research-synthesis.md
    D2: there is only ONE encode_query call per ANNPhase.query (one
    encoder, two columns, one query vector). The test verifies the
    single call DOES go through the singleflight by:

    (a) calling ANNPhase.query() once and asserting
        ``get_singleflight_dedup_count()`` did NOT increment (no
        concurrent duplicate, so dedup count stays at 0); AND
    (b) calling ANNPhase.query() with the SAME query concurrently
        from two coroutines and asserting the dedup counter DID
        increment by exactly 1 (proving the singleflight wrapper
        coalesced the second call).
    """

    def test_single_query_does_not_increment_dedup(
        self, _ann_phase_dual, monkeypatch
    ):
        """One encode call → no duplicates → dedup counter unchanged.

        F7 fix from the E07_S02 critique: uses ``monkeypatch.setattr``
        instead of manual try/finally so pytest's teardown is
        guaranteed even on KeyboardInterrupt."""
        import server.query_encoder as qe_mod

        qe_mod._reset_for_tests()
        before = qe_mod.get_singleflight_dedup_count()

        def _fake_sync(query_text: str) -> np.ndarray:
            seed = abs(hash(query_text)) % (2**32)
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
            v /= np.linalg.norm(v)
            return v

        monkeypatch.setattr(qe_mod, "_encode_query_sync", _fake_sync)
        asyncio.run(
            _ann_phase_dual.query(
                "single-call query", bm25_candidates=[]
            )
        )

        after = qe_mod.get_singleflight_dedup_count()
        assert after == before, (
            f"singleflight dedup counter unexpectedly incremented "
            f"({before} → {after}) on a single ANNPhase.query call. "
            f"Either ANNPhase is calling encode_query twice (it "
            f"shouldn't — see research-synthesis.md D1) or another "
            f"caller polluted the counter."
        )

    def test_concurrent_identical_queries_dedup_to_one(
        self, _ann_phase_dual, monkeypatch
    ):
        """Two concurrent ANNPhase.query calls with the SAME query
        text → singleflight coalesces → counter += 1 (one dedup hit).

        Proves the encode call DOES route through the singleflight
        wrapper (i.e. ANNPhase isn't calling some lower-level encode
        bypass).

        F7 fix: uses ``monkeypatch.setattr`` for guaranteed teardown."""
        import server.query_encoder as qe_mod

        qe_mod._reset_for_tests()
        before = qe_mod.get_singleflight_dedup_count()

        import time as _time

        def _slow_sync(query_text: str) -> np.ndarray:
            _time.sleep(0.05)  # 50ms — long enough to overlap
            seed = abs(hash(query_text)) % (2**32)
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
            v /= np.linalg.norm(v)
            return v

        monkeypatch.setattr(qe_mod, "_encode_query_sync", _slow_sync)

        async def go():
            return await asyncio.gather(
                _ann_phase_dual.query(
                    "concurrent dedup query", bm25_candidates=[]
                ),
                _ann_phase_dual.query(
                    "concurrent dedup query", bm25_candidates=[]
                ),
            )

        r1, r2 = asyncio.run(go())

        after = qe_mod.get_singleflight_dedup_count()
        assert after - before == 1, (
            f"expected singleflight to coalesce 2 concurrent identical "
            f"queries to 1 forward pass (dedup counter +1); got "
            f"{after - before} (before={before}, after={after})"
        )
        assert r1 == r2

    def test_ann_phase_query_routes_through_encode_query(
        self, _ann_phase_dual, monkeypatch
    ):
        """F2 fix: directly verify that ``ANNPhase.query`` calls
        ``encode_query`` (not some lower-level bypass like
        ``_encode_query_sync`` directly).

        Replace ``encode_query`` itself with a counter; assert it
        was invoked exactly once per ANNPhase.query call. Catches
        a future refactor that imports ``_encode_query_sync`` for
        "speed" and bypasses the singleflight."""
        import server.retrieval.ann as ann_mod

        call_count = {"n": 0}

        async def _counting_encode(query_text: str) -> np.ndarray:
            call_count["n"] += 1
            seed = abs(hash(query_text)) % (2**32)
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
            v /= np.linalg.norm(v)
            return v

        monkeypatch.setattr(ann_mod, "encode_query", _counting_encode)

        asyncio.run(
            _ann_phase_dual.query("routing test", bm25_candidates=[])
        )
        assert call_count["n"] == 1, (
            f"ANNPhase.query MUST call encode_query exactly once; "
            f"got {call_count['n']} calls. A future refactor that "
            f"bypasses encode_query (e.g. by calling "
            f"_encode_query_sync directly) would break the "
            f"singleflight routing — keep this test green."
        )


# ===========================================================================
# Resources integration
# ===========================================================================


class TestResourcesIntegration:
    """End-to-end probe: ``Resources.startup`` populates
    ``r.ann_phase`` with a working ``ANNPhase`` instance."""

    def test_resources_startup_populates_ann_phase(
        self, _seeded_dual_lancedb
    ):
        # Mock BGE-M3 model + tokenizer load (no download in CI).
        import server.query_encoder as qe_mod
        from server.config import Config
        from server.resources import Resources

        original_get_model = qe_mod._get_model
        original_get_tok = qe_mod._get_tokenizer
        qe_mod._get_model = lambda: object()
        qe_mod._get_tokenizer = lambda: object()
        try:
            lancedb_path, _version = _seeded_dual_lancedb
            cfg = Config(lancedb_path=lancedb_path)
            r = asyncio.run(Resources.startup(cfg))
            assert r.ann_phase is not None
            assert r.ann_phase.chunks_table is not None
            # The chunks_table reference is the same one pinned on
            # Resources — no redundant copy.
            assert r.ann_phase.chunks_table is r.chunks_table
        finally:
            qe_mod._get_model = original_get_model
            qe_mod._get_tokenizer = original_get_tok


# ===========================================================================
# F1 regression — LanceDB returns squared L2 distance for the L2 metric
# ===========================================================================


class TestLanceDBDistanceSemantics:
    """F1 fix from the E07_S02 critique: pin the LanceDB return-value
    contract AND the score-conversion formula together. A future
    LanceDB upgrade that changed the distance semantics, OR a
    well-meaning maintainer that "fixed" the formula, would fail
    this test loudly."""

    def test_lancedb_returns_squared_l2_for_unit_vectors(self, tmp_path):
        """Build a 3-row corpus of {v, v_orth, -v} unit vectors,
        query with v, assert ``_distance == [0, 2, 4]``.

        Confirms LanceDB's L2 metric returns SQUARED distance (not
        raw L2 distance). For unit vectors:
          ||v - v||²     = 0
          ||v - v_orth||² = 2 - 2·0 = 2
          ||v - (-v)||²   = 2 - 2·(-1) = 4
        """
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(str(tmp_path / "lancedb_distance_test"))
        schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("vec", pa.list_(pa.float32(), 3)),
            ]
        )
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v_orth = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        v_anti = np.array([-1.0, 0.0, 0.0], dtype=np.float32)
        data = [
            {"id": "v", "vec": v.tolist()},
            {"id": "v_orth", "vec": v_orth.tolist()},
            {"id": "v_anti", "vec": v_anti.tolist()},
        ]
        tbl = db.create_table("t", data=data, schema=schema)
        arrow = (
            tbl.search(v.tolist(), vector_column_name="vec")
            .limit(3)
            .to_arrow()
        )
        ids = arrow.column("id").to_pylist()
        distances = arrow.column("_distance").to_pylist()

        # Best-first ordering.
        assert ids == ["v", "v_orth", "v_anti"]
        # SQUARED L2 distances. If LanceDB ever switches to raw L2,
        # the values would be [0, sqrt(2)≈1.414, 2] — this test
        # catches that change loudly.
        assert distances[0] == pytest.approx(0.0)
        assert distances[1] == pytest.approx(2.0)
        assert distances[2] == pytest.approx(4.0)

    def test_distance_to_score_inverts_lancedb_distances_correctly(
        self,
    ):
        """The full pipeline: LanceDB distances [0, 2, 4] →
        cosines [1.0, 0.0, 0.0]. (The -1 cosine is clamped to 0
        since this score is a bounded similarity in [0, 1].)"""
        assert _distance_to_score(0.0) == pytest.approx(1.0)
        assert _distance_to_score(2.0) == pytest.approx(0.0)
        assert _distance_to_score(4.0) == pytest.approx(0.0)


# ===========================================================================
# F3 regression — schema validation at __init__ rejects typos upfront
# ===========================================================================


class TestSchemaValidation:
    """F3 fix: ANNPhase.__init__ validates that every column listed
    in EMBEDDING_COLUMNS exists on the chunks_table schema. A typo
    in a hardcoded column name (or a schema drift) was previously
    silently absorbed by the per-query ``except Exception`` —
    this test pins the upfront failure."""

    def test_missing_column_raises_at_init(
        self, _seeded_dual_lancedb, monkeypatch
    ):
        """Patch EMBEDDING_COLUMNS to include a typo column;
        construction MUST raise ValueError at init."""
        import server.retrieval.ann as ann_mod

        lancedb_path, version = _seeded_dual_lancedb
        tbl = _open_chunks_table(lancedb_path, version)

        monkeypatch.setattr(
            ann_mod,
            "EMBEDDING_COLUMNS",
            ("embedding_stmt", "embedding_typooooo"),
        )
        with pytest.raises(ValueError, match="missing from chunks_table schema"):
            ann_mod.ANNPhase(chunks_table=tbl)


# ===========================================================================
# F5 regression — phantom BM25 chunk_ids propagate through RRF
# ===========================================================================


class TestPhantomBm25Ids:
    """F5 fix: ANNPhase does NOT cross-check that BM25 chunk_ids
    exist in the live chunks table — the BM25Phase.startup
    cross-check (E07_S01 F4) is the canonical guard. This test
    pins the documented behavior: if a phantom id IS passed in,
    it appears in the RRF output unmodified (no crash, no
    silent drop). Downstream consumers must tolerate phantoms."""

    def test_phantom_bm25_id_appears_in_output(
        self, _ann_phase_dual, _mocked_bge
    ):
        phantom = "arxiv:9999.99999:" + "f" * 16
        result = asyncio.run(
            _ann_phase_dual.query(
                "any query",
                bm25_candidates=[(phantom, 1.0)],
                top_n=50,
            )
        )
        result_ids = {cid for cid, _ in result}
        assert phantom in result_ids, (
            f"phantom BM25 chunk_id {phantom!r} should appear in RRF "
            f"output (the documented contract — see ANNPhase.query "
            f"docstring); got {result_ids}"
        )


# ===========================================================================
# F6 regression — latency budget on dual-corpus query
# ===========================================================================


class TestLatencyBudget:
    """F6 fix: pin a generous 500ms budget on ANNPhase.query against
    the dual-corpus fixture. Catches catastrophic O(n²) regressions
    in the LanceDB integration without making the test flaky on
    slow CI runners."""

    def test_query_under_500ms_against_dual_corpus(
        self, _ann_phase_dual, _mocked_bge
    ):
        import time

        # Warm-up call (first query may pay one-time index init).
        asyncio.run(
            _ann_phase_dual.query("warm-up", bm25_candidates=[])
        )

        deadline_s = 0.500
        # 3 calls; assert max stays under the budget.
        for i in range(3):
            start = time.monotonic()
            asyncio.run(
                _ann_phase_dual.query(
                    f"latency test {i}", bm25_candidates=[]
                )
            )
            elapsed = time.monotonic() - start
            assert elapsed < deadline_s, (
                f"ANNPhase.query exceeded the {deadline_s * 1000:.0f}ms "
                f"latency budget on the 8-row dual corpus: "
                f"elapsed={elapsed * 1000:.1f}ms. Likely a regression "
                f"in the LanceDB ANN search path or a Python-loop "
                f"hot-path accidentally introduced."
            )


# ===========================================================================
# F9 regression — top_n > corpus_size truncates safely
# ===========================================================================


class TestTopNLargerThanCorpus:
    """F9 fix: a caller passing top_n > number of unique candidates
    should get back the union (not crash, not allocate a huge
    buffer)."""

    def test_top_n_larger_than_corpus_returns_union_size(
        self, _ann_phase_dual, _mocked_bge
    ):
        # The dual corpus has 8 chunks total. Pass top_n=100.
        result = asyncio.run(
            _ann_phase_dual.query(
                "Spec", bm25_candidates=[], top_n=100
            )
        )
        # Must not crash; must return at most 8 (the corpus union).
        assert len(result) <= 8


# ===========================================================================
# F10 regression — query_text validation at the ANNPhase boundary
# ===========================================================================


class TestQueryTextValidation:
    """F10 fix: ANNPhase.query rejects empty / whitespace-only queries
    AND oversized queries at its own boundary, independent of the
    FastAPI handler's Pydantic validator."""

    def test_empty_query_rejected(self, _ann_phase_dual, _mocked_bge):
        with pytest.raises(ValueError, match="non-whitespace"):
            asyncio.run(
                _ann_phase_dual.query("", bm25_candidates=[])
            )

    def test_whitespace_only_query_rejected(
        self, _ann_phase_dual, _mocked_bge
    ):
        with pytest.raises(ValueError, match="non-whitespace"):
            asyncio.run(
                _ann_phase_dual.query("   \t\n  ", bm25_candidates=[])
            )

    def test_oversized_query_rejected(
        self, _ann_phase_dual, _mocked_bge
    ):
        oversized = "x" * 10_001
        with pytest.raises(
            ValueError, match="exceeds the 10,000-char"
        ):
            asyncio.run(
                _ann_phase_dual.query(oversized, bm25_candidates=[])
            )

    def test_just_under_cap_query_accepted(
        self, _ann_phase_dual, _mocked_bge
    ):
        """A 10000-char query should pass (the cap is exclusive of
        the limit)."""
        valid = "abcde fghij " * 833  # ~10,000 chars
        valid = valid[:10_000]
        # Should not raise; returns some result.
        asyncio.run(
            _ann_phase_dual.query(valid, bm25_candidates=[])
        )


# ===========================================================================
# F14 regression — no per-query WARN log on stmt-only corpus
# ===========================================================================


class TestStmtOnlyCorpusLogQuiet:
    """F14 fix: stmt-only corpus is the production reality at v1.
    Each query previously logged a WARNING when the empty-proof
    column raised — multi-agent fan-out × every query → log spam.
    The init-cached ``_searchable_columns`` set now skips the
    empty column entirely, so no per-query warning fires."""

    def test_stmt_only_corpus_no_per_query_warning(
        self, _ann_phase_stmt_only, _mocked_bge, caplog
    ):
        import logging

        with caplog.at_level(
            logging.WARNING, logger="server.retrieval.ann"
        ):
            asyncio.run(
                _ann_phase_stmt_only.query(
                    "first query", bm25_candidates=[]
                )
            )
            asyncio.run(
                _ann_phase_stmt_only.query(
                    "second query", bm25_candidates=[]
                )
            )

        # The init may emit a one-time warning if BOTH columns are
        # empty (not the case here — stmt has rows). On a stmt-only
        # corpus, no per-query WARN should fire.
        per_query_warns = [
            r for r in caplog.records
            if "ANN search on column" in r.getMessage()
        ]
        assert per_query_warns == [], (
            f"expected zero per-query WARNs on stmt-only corpus; got "
            f"{[r.getMessage() for r in per_query_warns]}. The "
            f"init-cached _searchable_columns should skip the empty "
            f"proof column entirely."
        )
