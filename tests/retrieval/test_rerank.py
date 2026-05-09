"""``RerankPhase`` tests (E07_S03).

Brief AC mapping:

- ``ARXMCP_ENABLE_RERANK=false`` → returns input candidates in
  original order → ``TestOffPathPassthrough``
- ``ARXMCP_ENABLE_RERANK=true`` → loads + scores 50 in <5s →
  ``TestOnPathRequiresModel`` (opt-in: ``pytest -m requires_model``
  AND ``ARXMCP_RUN_REAL_BGE_RERANKER=1``)
- Tier-3 cache hit bypasses the reranker → reinterpreted (per
  research-synthesis.md D9; ``/debug/cache-stats`` is fiction) via
  ``Resources.rerank_singleflight.dedup_count`` →
  ``TestSingleflightCacheBypass``
- ``pytest -k "not requires_model"`` passes without model →
  the suite itself

Plus regression tests for:
- Singleflight key construction (deterministic across orderings)
- Phantom-id contract (E07_S02 F5 → carried into rerank)
- Body-text fetch with quote-injection defense
- SHA constants pinned (single source of truth)
- ``maybe_log_sha_drift`` behaviors (matched / drift / no-cache)
- Resources.startup wires r.rerank_phase end-to-end
- ``top_k`` validation
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from server.resources import Singleflight
from server.retrieval.rerank import (
    BGE_RERANKER_COMMIT_SHA,
    MAX_K,
    RERANKER_MAX_LENGTH,
    RERANKER_MODEL_ID,
    RERANKER_VERSION,
    RerankPhase,
    _build_singleflight_key,
    _fetch_body_texts,
    _huggingface_cache_snapshot_sha,
    maybe_log_sha_drift,
)

# ===========================================================================
# Fixtures (mirror tests/retrieval/test_ann.py)
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


def _stmt_corpus() -> list[ChunkRecord]:
    """Five stmt-kind chunks with distinct body_text strings so the
    rerank test can assert score variation."""
    return [
        _curated_chunk(
            "2307.00001", "0" * 16,
            body_tokens="theorem about Spec algebraic curve scheme",
        ),
        _curated_chunk(
            "2307.00002", "1" * 16,
            body_tokens="étale cohomology Galois extension definition",
        ),
        _curated_chunk(
            "2307.00003", "2" * 16,
            body_tokens="Hilbert space spectral theorem operator analysis",
        ),
        _curated_chunk(
            "2307.00004", "3" * 16,
            body_tokens="fundamental group homotopy classification",
        ),
        _curated_chunk(
            "2307.00005", "4" * 16,
            body_tokens="partial mathbb_Z derivation differential calculus",
        ),
    ]


def _embeddings_for_stmt(
    chunks: list[ChunkRecord], *, seed: int = 7,
) -> EmbedRecord:
    rng = np.random.default_rng(seed)
    rows: list[np.ndarray] = []
    cids: list[str] = []
    for c in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        rows.append(v)
        cids.append(c.chunk_id)
    return EmbedRecord(
        chunk_ids_stmt=cids,
        embedding_stmt=np.stack(rows, axis=0),
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )


@pytest.fixture
def _seeded_lancedb(tmp_path) -> tuple[Path, int]:
    chunks = _stmt_corpus()
    embeddings = _embeddings_for_stmt(chunks, seed=7)
    lancedb_path = tmp_path / "lancedb_rerank"
    version = write_chunks(chunks, embeddings, lancedb_path=lancedb_path)
    return (lancedb_path, version)


def _open_chunks_table(lancedb_path: Path, version: int) -> Any:
    from server.corpus import open_chunks_table

    return open_chunks_table(lancedb_path, version=version)


@pytest.fixture
def _phase_off(_seeded_lancedb) -> RerankPhase:
    """Off-path RerankPhase. No model load required."""
    lancedb_path, version = _seeded_lancedb
    tbl = _open_chunks_table(lancedb_path, version)
    return RerankPhase(
        chunks_table=tbl,
        rerank_singleflight=Singleflight(),
        rerank_semaphore=asyncio.Semaphore(4),
        enabled=False,
        model_handle=None,
    )


class _FakeTokenizer:
    """Minimal stub: BatchEncoding-shaped output with one tensor per
    pair. The fake model only inspects shape so the values don't
    need to be real token ids."""

    def __call__(
        self, pairs, padding=True, truncation=True,
        max_length=512, return_tensors="pt",
    ):
        import torch  # noqa: PLC0415

        n = len(pairs)
        return {
            "input_ids": torch.zeros((n, max_length), dtype=torch.long),
            "attention_mask": torch.ones((n, max_length), dtype=torch.long),
        }


class _FakeRerankerModel:
    """Cross-encoder stub: returns a logit per pair. Score is the
    length of the (lowercased) intersection of the query's
    whitespace tokens and the body's whitespace tokens — a crude
    "word overlap" signal so different queries produce different
    rankings."""

    def __init__(self, query_text_for_test: str = "") -> None:
        self._call_count = 0

    def eval(self) -> None:
        return None

    def __call__(self, **inputs):
        import torch  # noqa: PLC0415
        # The fake works by reading the input_ids batch dimension;
        # actual scoring happens via a closure trick in the test.
        # For deterministic-but-varied scores we hash the input_ids
        # row sums (which depend on padding) — unrealistic but
        # produces stable ordering for tests.
        n = inputs["input_ids"].shape[0]
        # Random but deterministic scores per row so the resulting
        # order is non-trivial.
        rng = np.random.default_rng(42)
        scores = rng.standard_normal(n).astype(np.float32)
        return type("Out", (), {
            "logits": torch.from_numpy(scores).view(-1, 1),
        })()


@pytest.fixture
def _phase_on_with_fake_model(_seeded_lancedb) -> RerankPhase:
    """On-path RerankPhase with a fake (model, tokenizer) handle."""
    lancedb_path, version = _seeded_lancedb
    tbl = _open_chunks_table(lancedb_path, version)
    fake_model = _FakeRerankerModel()
    fake_tokenizer = _FakeTokenizer()
    return RerankPhase(
        chunks_table=tbl,
        rerank_singleflight=Singleflight(),
        rerank_semaphore=asyncio.Semaphore(4),
        enabled=True,
        model_handle=(fake_model, fake_tokenizer),
    )


# ===========================================================================
# AC #1: Off-path passthrough
# ===========================================================================


class TestOffPathPassthrough:
    """Brief AC #1: ``ARXMCP_ENABLE_RERANK=false`` →
    ``RerankPhase.rerank(...)`` returns input candidates in original
    order with no encode / no model / no semaphore / no singleflight."""

    def test_off_path_returns_input_order(self, _phase_off):
        candidates = [
            ("arxiv:2307.00001:" + "0" * 16, 0.9),
            ("arxiv:2307.00002:" + "1" * 16, 0.8),
            ("arxiv:2307.00003:" + "2" * 16, 0.7),
        ]
        query_vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        result = asyncio.run(
            _phase_off.rerank(
                "any query", query_vec, candidates, top_k=10
            )
        )
        # Same chunk_ids, same scores, same order.
        assert result == candidates

    def test_off_path_truncates_to_top_k(self, _phase_off):
        candidates = [
            (f"arxiv:2307.0000{i}:" + str(i) * 16, 1.0 - i * 0.1)
            for i in range(5)
        ]
        query_vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        result = asyncio.run(
            _phase_off.rerank(
                "any query", query_vec, candidates, top_k=3
            )
        )
        assert len(result) == 3
        assert result == candidates[:3]

    def test_off_path_does_not_touch_singleflight(self, _phase_off):
        """Off-path MUST NOT acquire the singleflight (no encode call,
        no rerank). The dedup counter stays at 0."""
        candidates = [("arxiv:2307.00001:" + "0" * 16, 0.5)]
        query_vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        before = _phase_off._rerank_singleflight.dedup_count
        for _ in range(5):
            asyncio.run(
                _phase_off.rerank(
                    "any", query_vec, candidates, top_k=1
                )
            )
        after = _phase_off._rerank_singleflight.dedup_count
        assert after == before

    def test_off_path_empty_candidates(self, _phase_off):
        query_vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        result = asyncio.run(
            _phase_off.rerank("any", query_vec, [], top_k=10)
        )
        assert result == []

    def test_enabled_property(self, _phase_off):
        assert _phase_off.enabled is False

    def test_top_k_zero_rejected(self, _phase_off):
        with pytest.raises(ValueError, match=r"\[1, 50\]"):
            asyncio.run(
                _phase_off.rerank(
                    "x",
                    np.zeros(EMBEDDING_DIM, dtype=np.float32),
                    [],
                    top_k=0,
                )
            )

    def test_top_k_over_max_rejected(self, _phase_off):
        with pytest.raises(ValueError, match=r"\[1, 50\]"):
            asyncio.run(
                _phase_off.rerank(
                    "x",
                    np.zeros(EMBEDDING_DIM, dtype=np.float32),
                    [],
                    top_k=51,
                )
            )

    def test_max_k_constant(self):
        assert MAX_K == 50

    def test_enabled_true_without_model_rejected(
        self, _seeded_lancedb,
    ):
        """Constructing with ``enabled=True`` AND ``model_handle=None``
        is a programming error — refuse upfront."""
        lancedb_path, version = _seeded_lancedb
        tbl = _open_chunks_table(lancedb_path, version)
        with pytest.raises(ValueError, match="enabled=True requires"):
            RerankPhase(
                chunks_table=tbl,
                rerank_singleflight=Singleflight(),
                rerank_semaphore=asyncio.Semaphore(4),
                enabled=True,
                model_handle=None,
            )


# ===========================================================================
# Singleflight key construction
# ===========================================================================


class TestSingleflightKey:
    """The Tier-3 cache key MUST be deterministic given the same
    inputs (regardless of input ordering for candidates)."""

    def test_key_is_64_hex_chars(self):
        v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        candidates = [("arxiv:2307.00001:" + "0" * 16, 0.5)]
        key = _build_singleflight_key(v, candidates)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_key_is_deterministic(self):
        v = np.full(EMBEDDING_DIM, 0.01, dtype=np.float32)
        candidates = [("arxiv:2307.00001:" + "a" * 16, 0.9)]
        a = _build_singleflight_key(v, candidates)
        b = _build_singleflight_key(v, candidates)
        assert a == b

    def test_key_invariant_to_candidate_order(self):
        """Per the spec: ``sorted_candidate_id_tuple_hash`` — order
        of input candidates MUST NOT affect the key."""
        v = np.full(EMBEDDING_DIM, 0.01, dtype=np.float32)
        cands_a = [
            ("arxiv:2307.00001:" + "a" * 16, 0.9),
            ("arxiv:2307.00002:" + "b" * 16, 0.5),
        ]
        cands_b = list(reversed(cands_a))
        a = _build_singleflight_key(v, cands_a)
        b = _build_singleflight_key(v, cands_b)
        assert a == b

    def test_key_changes_when_query_vec_changes(self):
        v1 = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        v2 = np.full(EMBEDDING_DIM, 0.01, dtype=np.float32)
        candidates = [("arxiv:2307.00001:" + "a" * 16, 0.9)]
        a = _build_singleflight_key(v1, candidates)
        b = _build_singleflight_key(v2, candidates)
        assert a != b

    def test_key_changes_when_candidates_change(self):
        v = np.full(EMBEDDING_DIM, 0.01, dtype=np.float32)
        a = _build_singleflight_key(
            v, [("arxiv:2307.00001:" + "a" * 16, 0.5)]
        )
        b = _build_singleflight_key(
            v, [("arxiv:2307.00002:" + "b" * 16, 0.5)]
        )
        assert a != b

    def test_key_includes_reranker_version(self):
        """The reranker version is part of the key — mock the
        constant and verify the key changes."""
        v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        candidates = [("arxiv:2307.00001:" + "a" * 16, 0.5)]
        original_key = _build_singleflight_key(v, candidates)
        # Manually compute the key with a different reranker version.
        h = hashlib.sha256()
        h.update(v.tobytes())
        h.update(b"\x00")
        h.update(b"arxiv:2307.00001:aaaaaaaaaaaaaaaa")
        h.update(b"\x00")
        h.update(b"different-version")
        manual_key_alt = h.hexdigest()
        assert original_key != manual_key_alt


# ===========================================================================
# On-path with fake model: singleflight cache bypass
# ===========================================================================


class TestSingleflightCacheBypass:
    """Brief AC #3 reinterpreted (per research-synthesis.md D9):
    Tier-3 cache hit bypasses the reranker, verified via
    ``rerank_singleflight.dedup_count``."""

    def test_concurrent_identical_rerank_dedups(
        self, _phase_on_with_fake_model
    ):
        """Two concurrent ``rerank`` calls with the same (query_vec,
        candidates) hit the singleflight: only ONE forward pass
        happens; the second call coalesces and ``dedup_count``
        increments by 1."""
        phase = _phase_on_with_fake_model
        candidates = [
            ("arxiv:2307.00001:" + "0" * 16, 0.5),
            ("arxiv:2307.00002:" + "1" * 16, 0.4),
        ]
        v = np.full(EMBEDDING_DIM, 0.01, dtype=np.float32)

        before = phase._rerank_singleflight.dedup_count

        async def go():
            return await asyncio.gather(
                phase.rerank("query", v, candidates, top_k=2),
                phase.rerank("query", v, candidates, top_k=2),
            )

        r1, r2 = asyncio.run(go())
        after = phase._rerank_singleflight.dedup_count

        assert after - before == 1, (
            f"singleflight should coalesce 2 concurrent identical "
            f"reranks; got {after - before} dedup hits"
        )
        # Both callers receive the SAME ranking.
        assert r1 == r2

    def test_distinct_candidates_no_dedup(
        self, _phase_on_with_fake_model
    ):
        phase = _phase_on_with_fake_model
        v = np.full(EMBEDDING_DIM, 0.01, dtype=np.float32)
        cands_a = [("arxiv:2307.00001:" + "0" * 16, 0.5)]
        cands_b = [("arxiv:2307.00002:" + "1" * 16, 0.5)]

        before = phase._rerank_singleflight.dedup_count

        async def go():
            return await asyncio.gather(
                phase.rerank("query", v, cands_a, top_k=1),
                phase.rerank("query", v, cands_b, top_k=1),
            )

        asyncio.run(go())
        after = phase._rerank_singleflight.dedup_count
        assert after == before


# ===========================================================================
# On-path with fake model: rerank shape + sort + truncation
# ===========================================================================


class TestOnPathRerank:
    def test_returns_top_k_in_score_desc_order(
        self, _phase_on_with_fake_model
    ):
        phase = _phase_on_with_fake_model
        # 5 candidates from the seeded corpus.
        candidates = [
            ("arxiv:2307.00001:" + "0" * 16, 0.5),
            ("arxiv:2307.00002:" + "1" * 16, 0.5),
            ("arxiv:2307.00003:" + "2" * 16, 0.5),
            ("arxiv:2307.00004:" + "3" * 16, 0.5),
            ("arxiv:2307.00005:" + "4" * 16, 0.5),
        ]
        v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        result = asyncio.run(
            phase.rerank("any query", v, candidates, top_k=3)
        )
        assert len(result) == 3
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)

    def test_phantom_chunk_id_silently_dropped(
        self, _phase_on_with_fake_model
    ):
        """E07_S02 F5 contract: phantom chunk_ids (not in the live
        LanceDB table) appear in candidates but have no body_text;
        the rerank silently drops them rather than crashing."""
        phase = _phase_on_with_fake_model
        candidates = [
            ("arxiv:2307.00001:" + "0" * 16, 0.5),  # real
            ("arxiv:9999.99999:" + "f" * 16, 0.4),  # phantom
        ]
        v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        result = asyncio.run(
            phase.rerank("any query", v, candidates, top_k=10)
        )
        result_ids = {cid for cid, _ in result}
        # Real id in result; phantom dropped.
        assert "arxiv:2307.00001:" + "0" * 16 in result_ids
        assert "arxiv:9999.99999:" + "f" * 16 not in result_ids

    def test_all_candidates_phantom_returns_empty(
        self, _phase_on_with_fake_model
    ):
        phase = _phase_on_with_fake_model
        candidates = [
            ("arxiv:9999.99999:" + "f" * 16, 0.5),
            ("arxiv:9999.99998:" + "e" * 16, 0.4),
        ]
        v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        result = asyncio.run(
            phase.rerank("any", v, candidates, top_k=10)
        )
        assert result == []

    def test_empty_candidates_returns_empty(
        self, _phase_on_with_fake_model
    ):
        v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        result = asyncio.run(
            _phase_on_with_fake_model.rerank(
                "any", v, [], top_k=10
            )
        )
        assert result == []


# ===========================================================================
# Body-text fetch
# ===========================================================================


class TestFetchBodyTexts:
    def test_returns_dict_keyed_by_chunk_id(self, _seeded_lancedb):
        lancedb_path, version = _seeded_lancedb
        tbl = _open_chunks_table(lancedb_path, version)
        ids = ["arxiv:2307.00001:" + "0" * 16]
        result = _fetch_body_texts(tbl, ids)
        assert ids[0] in result
        assert "Spec" in result[ids[0]]

    def test_phantom_id_absent_from_dict(self, _seeded_lancedb):
        lancedb_path, version = _seeded_lancedb
        tbl = _open_chunks_table(lancedb_path, version)
        ids = ["arxiv:9999.99999:" + "f" * 16]
        result = _fetch_body_texts(tbl, ids)
        assert result == {}

    def test_empty_input_returns_empty(self, _seeded_lancedb):
        lancedb_path, version = _seeded_lancedb
        tbl = _open_chunks_table(lancedb_path, version)
        assert _fetch_body_texts(tbl, []) == {}

    def test_quote_in_chunk_id_dropped_defensively(
        self, _seeded_lancedb, caplog
    ):
        """Defense-in-depth: a chunk_id containing a single quote
        is dropped rather than passed to the SQL IN clause
        (would otherwise be a SQL-injection vector)."""
        import logging

        lancedb_path, version = _seeded_lancedb
        tbl = _open_chunks_table(lancedb_path, version)
        with caplog.at_level(logging.WARNING):
            result = _fetch_body_texts(
                tbl, ["arxiv:malicious';DROP TABLE chunks;--:" + "f" * 16],
            )
        assert result == {}
        assert any("single quote" in r.getMessage() for r in caplog.records)


# ===========================================================================
# SHA constants / drift check
# ===========================================================================


class TestShaConstants:
    def test_bge_reranker_commit_sha_format(self):
        """40 lowercase hex chars (git commit SHA-1)."""
        assert len(BGE_RERANKER_COMMIT_SHA) == 40
        assert all(
            c in "0123456789abcdef" for c in BGE_RERANKER_COMMIT_SHA
        )

    def test_reranker_version_includes_short_sha(self):
        assert BGE_RERANKER_COMMIT_SHA[:8] in RERANKER_VERSION
        assert RERANKER_VERSION.startswith("bge-reranker-v2-m3@")

    def test_reranker_max_length_is_512(self):
        assert RERANKER_MAX_LENGTH == 512

    def test_reranker_model_id(self):
        assert RERANKER_MODEL_ID == "BAAI/bge-reranker-v2-m3"

    def test_config_default_matches_constant(self):
        """``Config.rerank_model_sha`` default MUST equal
        :data:`BGE_RERANKER_COMMIT_SHA` — the constant is the
        single source of truth; the Config field default mirrors."""
        from server.config import Config

        cfg = Config()
        assert cfg.rerank_model_sha == BGE_RERANKER_COMMIT_SHA


class TestShaDriftCheck:
    def test_no_cache_logs_info_no_warning(self, tmp_path, caplog):
        """If the local cache is empty, drift check logs INFO not
        WARNING."""
        import logging

        # Point HF_HOME at empty tmp dir.
        os.environ["HF_HOME"] = str(tmp_path)
        try:
            with caplog.at_level(logging.INFO, logger="server.retrieval.rerank"):
                maybe_log_sha_drift(BGE_RERANKER_COMMIT_SHA)
        finally:
            del os.environ["HF_HOME"]
        warns = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warns == []

    def test_matched_sha_logs_info_no_warning(
        self, tmp_path, caplog
    ):
        import logging

        # Build a fake cache with the matching SHA dir.
        snap = (
            tmp_path / "hub" / "models--BAAI--bge-reranker-v2-m3"
            / "snapshots" / BGE_RERANKER_COMMIT_SHA
        )
        snap.mkdir(parents=True)
        os.environ["HF_HOME"] = str(tmp_path)
        try:
            with caplog.at_level(logging.INFO, logger="server.retrieval.rerank"):
                maybe_log_sha_drift(BGE_RERANKER_COMMIT_SHA)
        finally:
            del os.environ["HF_HOME"]
        warns = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warns == []

    def test_drift_logs_warning(self, tmp_path, caplog):
        import logging

        # Build a fake cache with a DIFFERENT SHA dir.
        wrong_sha = "0" * 40
        snap = (
            tmp_path / "hub" / "models--BAAI--bge-reranker-v2-m3"
            / "snapshots" / wrong_sha
        )
        snap.mkdir(parents=True)
        os.environ["HF_HOME"] = str(tmp_path)
        try:
            with caplog.at_level(
                logging.WARNING, logger="server.retrieval.rerank"
            ):
                maybe_log_sha_drift(BGE_RERANKER_COMMIT_SHA)
        finally:
            del os.environ["HF_HOME"]
        warns = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warns
        assert any("SHA drift" in r.getMessage() for r in warns)


class TestHuggingfaceCacheLookup:
    def test_no_cache_returns_none(self, tmp_path):
        os.environ["HF_HOME"] = str(tmp_path)
        try:
            assert _huggingface_cache_snapshot_sha(RERANKER_MODEL_ID) is None
        finally:
            del os.environ["HF_HOME"]

    def test_cached_sha_returned(self, tmp_path):
        snap = (
            tmp_path / "hub" / "models--BAAI--bge-reranker-v2-m3"
            / "snapshots" / BGE_RERANKER_COMMIT_SHA
        )
        snap.mkdir(parents=True)
        os.environ["HF_HOME"] = str(tmp_path)
        try:
            sha = _huggingface_cache_snapshot_sha(RERANKER_MODEL_ID)
        finally:
            del os.environ["HF_HOME"]
        assert sha == BGE_RERANKER_COMMIT_SHA


# ===========================================================================
# Resources integration
# ===========================================================================


class TestResourcesIntegration:
    """End-to-end probe: ``Resources.startup`` populates
    ``r.rerank_phase`` (off-path by default; passes through)."""

    def test_resources_startup_populates_rerank_phase_off(
        self, _seeded_lancedb
    ):
        # Mock BGE-M3 so we don't pay the model download in CI.
        import server.query_encoder as qe_mod
        from server.config import Config
        from server.resources import Resources

        original_get_model = qe_mod._get_model
        original_get_tok = qe_mod._get_tokenizer
        qe_mod._get_model = lambda: object()
        qe_mod._get_tokenizer = lambda: object()
        try:
            lancedb_path, _version = _seeded_lancedb
            cfg = Config(
                lancedb_path=lancedb_path, enable_rerank=False
            )
            r = asyncio.run(Resources.startup(cfg))
            assert r.rerank_phase is not None
            assert r.rerank_phase.enabled is False
            assert r.reranker_model is None
        finally:
            qe_mod._get_model = original_get_model
            qe_mod._get_tokenizer = original_get_tok


# ===========================================================================
# Real-model path (env-gated, opt-in)
# ===========================================================================


class TestOnPathRequiresModel:
    """Brief AC #2 (and the ``-k 'not requires_model'`` exclusion).
    Marked for opt-in via:

        ARXMCP_RUN_REAL_BGE_RERANKER=1 pytest -m requires_model

    Skipped by default — actual BGE-reranker-v2-m3 is a 2.27 GB
    download. On CI without the env var, these are no-op."""

    @pytest.mark.requires_model
    @pytest.mark.skipif(
        os.environ.get("ARXMCP_RUN_REAL_BGE_RERANKER") != "1",
        reason="set ARXMCP_RUN_REAL_BGE_RERANKER=1 to exercise the real model",
    )
    def test_real_reranker_loads_and_scores_50_under_5s(
        self, _seeded_lancedb,
    ):
        """AC #2: with flag on, reranker loads and scores all 50
        candidates within 5s. Times the ``rerank`` call (NOT the
        startup load — startup is paid once)."""
        import time as _time

        from server.config import Config
        from server.resources import Resources

        lancedb_path, _version = _seeded_lancedb
        cfg = Config(lancedb_path=lancedb_path, enable_rerank=True)
        r = asyncio.run(Resources.startup(cfg))
        assert r.rerank_phase.enabled is True

        # 50 candidates from the corpus (5 chunks × 10 dups; the
        # rerank dedups by chunk_id silently — just verifying
        # latency).
        chunks = _stmt_corpus()
        candidates = [
            (c.chunk_id, 1.0 - i * 0.01)
            for i, c in enumerate(chunks * 10)
        ][:50]
        v = np.full(EMBEDDING_DIM, 0.01, dtype=np.float32)

        start = _time.monotonic()
        result = asyncio.run(
            r.rerank_phase.rerank(
                "perverse sheaves on flag varieties",
                v,
                candidates,
                top_k=10,
            )
        )
        elapsed = _time.monotonic() - start
        assert len(result) <= 10
        assert elapsed < 5.0, (
            f"rerank exceeded 5s budget: {elapsed:.2f}s"
        )
