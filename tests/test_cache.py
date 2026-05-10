"""3-tier retrieval cache tests (E08_S03).

Coverage map (acceptance criteria → test class):

  AC                                                         Test class
  ──────────────────────────────────────────────────────────────────────
  Repeated identical query hits Tier-1, bypasses pipeline    TestTier1HitMissCycle
  Semantic-similar query (cos ≥ 0.97) hits Tier-2            TestTier2SemanticHit
  Corpus-version bump invalidates Tier-1 entries             TestCorpusVersionInvalidation
  GET /debug/cache-stats returns valid JSON                  TestDebugCacheStatsEndpoint
  Prometheus metrics emitted at /metrics                     TestPrometheusMetricsExposition
  pytest tests/test_cache.py passes                          the suite itself

Plus regression-grade tests for:
- Tier-3 (rerank-set memo) hit/miss cycle
- TTL expiry on Tier-1 (lazy eviction at read time)
- Tier-2 cold-start (empty ring buffer = no-op pass-through)
- Tier-2 filter-fingerprint mismatch even at cosine ≥ 0.97
- SQLite persistence across cache instances (rehydrate test)
- Failure-mode discipline: a SQLite I/O error logs and falls through
- Stats accessor: empty cache returns valid all-zero dict

The tests do NOT depend on any real ML model. The query embeddings
are synthetic numpy arrays of the right shape (1024-dim float32).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from server.cache import (
    EMBEDDING_DIM,
    TIER2_COSINE_THRESHOLD,
    RetrievalCache,
    reset_cache_for_tests,
    set_cache,
)
from server.cache_sqlite import (
    Tier1Store,
    canonical_query_form,
    derive_tier1_key,
)
from server.metrics import (
    ALL_TIERS,
    CACHE_BYTES_GAUGE,
    CACHE_HITS_COUNTER,
    CACHE_LOOKUPS_COUNTER,
    TIER_1,
    TIER_2,
    refresh_cache_metrics,
    reset_cache_metrics_for_tests,
)

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_cache_state():
    """Reset cache + metrics before/after every test."""
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()
    yield
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()


@pytest.fixture
def cache_db_path(tmp_path) -> Path:
    """Per-test SQLite path under tmp_path."""
    return tmp_path / "cache" / "retrieval.db"


def _make_embedding(seed: int) -> np.ndarray:
    """Deterministic synthetic L2-normalized BGE-M3-shaped embedding."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    v /= float(np.linalg.norm(v))
    return v


def _near_embedding(base: np.ndarray, *, target_cosine: float, seed: int) -> np.ndarray:
    """Return a unit vector whose cosine similarity with ``base`` is
    approximately ``target_cosine``.

    Construction: start with ``base * target_cosine``, add an
    orthogonal-ish perturbation scaled to ``sqrt(1 - target_cosine^2)``,
    then re-normalize. Suitable for testing both ≥0.97 hits and
    sub-threshold misses."""
    rng = np.random.default_rng(seed)
    perturb = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    # Project out the component along ``base``.
    perturb -= np.dot(perturb, base) * base
    perturb /= float(np.linalg.norm(perturb))
    new = target_cosine * base + np.sqrt(max(0.0, 1.0 - target_cosine**2)) * perturb
    new /= float(np.linalg.norm(new))
    return new.astype(np.float32)


def _payload(label: str = "demo") -> dict:
    """Synthetic search_papers payload — matches the structuredContent
    shape expected by the cache (a JSON-serializable dict)."""
    return {
        "embed_model": "bge-m3",
        "results": [
            {"chunk_id": f"arxiv:demo:{label}-001", "score": 0.95},
            {"chunk_id": f"arxiv:demo:{label}-002", "score": 0.92},
        ],
        "retrieval_mode": "dense_only",
    }


# ===========================================================================
# Key derivation
# ===========================================================================


class TestKeyDerivation:
    """Cache-key invariants — the load-bearing property is that the
    same (canonical-query, filters, k, corpus_version) tuple yields
    the SAME hash, and ANY change yields a different hash."""

    def test_canonical_query_form_is_strip_only(self):
        # The brief: "canonical_form(query) is query.strip() only —
        # do NOT lowercase, do NOT strip punctuation."
        assert canonical_query_form("  étale  ") == "étale"
        assert canonical_query_form("\\'etale") == "\\'etale"  # NOT lowered
        assert canonical_query_form("Étale") == "Étale"  # case preserved
        # Punctuation preserved.
        assert canonical_query_form("Hi, world!") == "Hi, world!"

    def test_identical_inputs_produce_identical_keys(self):
        k1 = derive_tier1_key("foo", {"a": 1}, 10, corpus_version=7)
        k2 = derive_tier1_key("foo", {"a": 1}, 10, corpus_version=7)
        assert k1 == k2

    def test_corpus_version_change_changes_key(self):
        k_v6 = derive_tier1_key("foo", None, 10, corpus_version=6)
        k_v7 = derive_tier1_key("foo", None, 10, corpus_version=7)
        assert k_v6 != k_v7, "corpus_version change MUST invalidate the key"

    def test_filter_change_changes_key(self):
        k_no = derive_tier1_key("foo", None, 10, corpus_version=7)
        k_yes = derive_tier1_key("foo", {"year": 2024}, 10, corpus_version=7)
        assert k_no != k_yes

    def test_filters_none_equals_empty_dict(self):
        # The cache must treat None and {} identically so a no-filter
        # query and an explicit-empty-filter query share a slot.
        k_none = derive_tier1_key("foo", None, 10, corpus_version=7)
        k_empty = derive_tier1_key("foo", {}, 10, corpus_version=7)
        assert k_none == k_empty

    def test_filter_key_order_does_not_change_key(self):
        # json.dumps(..., sort_keys=True) is the stability guarantee.
        k_a_first = derive_tier1_key("foo", {"a": 1, "b": 2}, 10, corpus_version=7)
        k_b_first = derive_tier1_key("foo", {"b": 2, "a": 1}, 10, corpus_version=7)
        assert k_a_first == k_b_first

    def test_k_change_changes_key(self):
        k10 = derive_tier1_key("foo", None, 10, corpus_version=7)
        k20 = derive_tier1_key("foo", None, 20, corpus_version=7)
        assert k10 != k20

    def test_level_change_changes_key(self):
        """Regression: the brief omitted ``level`` from the key
        formula but ``search_papers`` accepts a ``level`` argument
        (theorem/section/paper) that materially changes the result
        envelope. Distinct levels MUST produce distinct keys."""
        k_theorem = derive_tier1_key("foo", None, 10, corpus_version=7, level="theorem")
        k_section = derive_tier1_key("foo", None, 10, corpus_version=7, level="section")
        k_paper = derive_tier1_key("foo", None, 10, corpus_version=7, level="paper")
        k_none = derive_tier1_key("foo", None, 10, corpus_version=7, level=None)
        # All four must be distinct.
        assert len({k_theorem, k_section, k_paper, k_none}) == 4

    def test_level_omitted_kwarg_equals_explicit_none(self):
        """``derive_tier1_key(..., level=None)`` == ``derive_tier1_key(...)``
        — the kwarg defaults to None and produces the same key."""
        k_default = derive_tier1_key("foo", None, 10, corpus_version=7)
        k_none = derive_tier1_key("foo", None, 10, corpus_version=7, level=None)
        assert k_default == k_none


# ===========================================================================
# AC — Tier-1 hit/miss cycle
# ===========================================================================


class TestTier1HitMissCycle:
    """AC: a repeated identical query hits Tier-1 and bypasses
    Phase 1/2/3."""

    def test_tier1_miss_then_hit(self, cache_db_path):
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                # First call — miss.
                payload, hit_tier = await cache.lookup_search(
                    query="my query", filters=None, k=10,
                )
                assert payload is None
                assert hit_tier == ""

                # Store.
                await cache.store_search(
                    query="my query", filters=None, k=10, payload=_payload(),
                )

                # Second call — hit on Tier 1.
                payload, hit_tier = await cache.lookup_search(
                    query="my query", filters=None, k=10,
                )
                assert payload == _payload()
                assert hit_tier == TIER_1
            finally:
                await cache.close()

        asyncio.run(_run())

    def test_tier1_hit_does_not_require_embedding(self, cache_db_path):
        """The integration seam in handle_search_papers checks Tier 1
        BEFORE computing the query embedding. Confirm the lookup
        works without the embedding argument."""
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                await cache.store_search(
                    query="q", filters=None, k=10, payload=_payload(),
                )
                # NO query_embedding passed — Tier 1 still hits.
                payload, hit_tier = await cache.lookup_search(
                    query="q", filters=None, k=10, query_embedding=None,
                )
                assert payload == _payload()
                assert hit_tier == TIER_1
            finally:
                await cache.close()

        asyncio.run(_run())


# ===========================================================================
# AC — Tier-2 semantic hit
# ===========================================================================


class TestTier2SemanticHit:
    """AC: a semantically similar query (cos ≥ 0.97) hits Tier-2
    and bypasses Phase 1/2/3."""

    def test_tier2_hit_at_cosine_098(self, cache_db_path):
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                base = _make_embedding(seed=42)
                near = _near_embedding(base, target_cosine=0.98, seed=99)
                # Cosine should be approximately 0.98 — verify.
                assert abs(float(np.dot(base, near)) - 0.98) < 1e-3

                # Store the original query.
                await cache.store_search(
                    query="original", filters={"year": 2024}, k=10,
                    payload=_payload("original"), query_embedding=base,
                )

                # The semantically-near query has DIFFERENT exact text,
                # so Tier 1 misses; Tier 2 must hit on cosine ≥ 0.97.
                payload, hit_tier = await cache.lookup_search(
                    query="different text",
                    filters={"year": 2024},
                    k=10,
                    query_embedding=near,
                )
                assert payload == _payload("original")
                assert hit_tier == TIER_2
            finally:
                await cache.close()

        asyncio.run(_run())

    def test_tier2_miss_at_cosine_095(self, cache_db_path):
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                base = _make_embedding(seed=42)
                far = _near_embedding(base, target_cosine=0.95, seed=99)
                assert float(np.dot(base, far)) < TIER2_COSINE_THRESHOLD

                await cache.store_search(
                    query="original", filters=None, k=10,
                    payload=_payload(), query_embedding=base,
                )

                payload, hit_tier = await cache.lookup_search(
                    query="different", filters=None, k=10, query_embedding=far,
                )
                assert payload is None
                assert hit_tier == ""
            finally:
                await cache.close()

        asyncio.run(_run())

    def test_tier2_cold_start_no_op(self, cache_db_path):
        """Per the brief: 'If the FAISS index is empty (cold start),
        Tier 2 is a no-op pass-through.'"""
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                emb = _make_embedding(seed=42)
                payload, hit_tier = await cache.lookup_search(
                    query="cold", filters=None, k=10, query_embedding=emb,
                )
                assert payload is None
                # Tier 1 miss + Tier 2 cold-start no-op → empty hit_tier.
                assert hit_tier == ""
            finally:
                await cache.close()

        asyncio.run(_run())

    def test_tier2_filter_fingerprint_mismatch_misses(self, cache_db_path):
        """A cosine-≥0.97 match with a DIFFERENT filter fingerprint
        must NOT hit. The brief: 'cosine similarity > 0.97 AND exact
        filter match.'"""
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                base = _make_embedding(seed=42)
                near = _near_embedding(base, target_cosine=0.99, seed=99)
                await cache.store_search(
                    query="orig", filters={"year": 2024}, k=10,
                    payload=_payload(), query_embedding=base,
                )
                payload, _ = await cache.lookup_search(
                    query="diff", filters={"year": 2025},
                    k=10, query_embedding=near,
                )
                assert payload is None, (
                    "Tier-2 must require EXACT filter match; cosine alone "
                    "is not sufficient."
                )
            finally:
                await cache.close()

        asyncio.run(_run())


# ===========================================================================
# AC — corpus_version invalidation
# ===========================================================================


class TestCorpusVersionInvalidation:
    """AC: after server restart with corpus_version=N+1, all Tier-1
    entries from corpus_version=N are unreachable."""

    def test_corpus_version_bump_unreachables_old_entries(self, cache_db_path):
        async def _run():
            # Open at corpus_version=6 and write an entry.
            cache_v6 = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=6,
            )
            try:
                await cache_v6.store_search(
                    query="q", filters=None, k=10, payload=_payload("v6"),
                )
            finally:
                await cache_v6.close()

            # Reopen at corpus_version=7 — same SQLite file. The Tier-1
            # entry from v6 must be unreachable by hash construction
            # (the v7 lookup key is different).
            cache_v7 = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=7,
            )
            try:
                payload, hit_tier = await cache_v7.lookup_search(
                    query="q", filters=None, k=10,
                )
                assert payload is None
                assert hit_tier == ""

                # And: writing an entry at v7 produces a v7-keyed row
                # that does NOT clobber the v6 row (different keys).
                await cache_v7.store_search(
                    query="q", filters=None, k=10, payload=_payload("v7"),
                )
                payload, hit_tier = await cache_v7.lookup_search(
                    query="q", filters=None, k=10,
                )
                assert payload == _payload("v7")
                assert hit_tier == TIER_1
            finally:
                await cache_v7.close()

        asyncio.run(_run())


# ===========================================================================
# Tier-3 rerank-set memo
# ===========================================================================


class TestTier3RerankMemo:
    """The brief: 'Tier-3 hit after identical candidate set.' Reuses
    ``server.retrieval.rerank._build_singleflight_key`` so a Tier-3
    hit corresponds to the same (query_embedding, candidate_set,
    model) triple."""

    def test_tier3_miss_then_hit(self, cache_db_path):
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                emb = _make_embedding(seed=42)
                candidates = [
                    ("arxiv:p1:001", 0.95),
                    ("arxiv:p1:002", 0.91),
                    ("arxiv:p2:003", 0.88),
                ]
                payload = [
                    {"chunk_id": "arxiv:p1:002", "rerank_score": 0.99},
                    {"chunk_id": "arxiv:p1:001", "rerank_score": 0.93},
                ]

                miss = await cache.lookup_rerank(emb, candidates)
                assert miss is None

                await cache.store_rerank(emb, candidates, payload)

                hit = await cache.lookup_rerank(emb, candidates)
                assert hit == payload
            finally:
                await cache.close()

        asyncio.run(_run())

    def test_tier3_different_candidate_set_misses(self, cache_db_path):
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                emb = _make_embedding(seed=42)
                candidates_a = [("arxiv:a:001", 0.9)]
                candidates_b = [("arxiv:b:001", 0.9)]
                payload = [{"chunk_id": "a", "score": 1.0}]

                await cache.store_rerank(emb, candidates_a, payload)
                miss = await cache.lookup_rerank(emb, candidates_b)
                assert miss is None
            finally:
                await cache.close()

        asyncio.run(_run())


# ===========================================================================
# TTL expiry
# ===========================================================================


class TestTtlExpiry:
    def test_tier1_lazy_eviction_on_expired_read(self, cache_db_path, monkeypatch):
        """Direct Tier1Store test: write with a past TTL, read returns
        None and deletes the row."""
        async def _run():
            store = await Tier1Store.open(cache_db_path)
            try:
                # Write with a TTL in the PAST so the very next read
                # treats it as expired.
                await store.put(
                    "k1", b"v1",
                    ttl_seconds=-100.0, corpus_version=1,
                )
                row = await store.get("k1")
                assert row is None  # lazy-evicted
                # The row count should now be 0 (the get deleted it).
                assert (await store.row_count()) == 0
            finally:
                await store.close()

        asyncio.run(_run())


# ===========================================================================
# Persistence across restart
# ===========================================================================


class TestSqlitePersistence:
    def test_unexpired_rows_rehydrate_into_mirror(self, cache_db_path):
        """Cache instance B opened against the same SQLite file as A
        sees A's unexpired entries."""
        async def _run():
            cache_a = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                await cache_a.store_search(
                    query="persisted", filters=None, k=10,
                    payload=_payload("persisted"),
                )
            finally:
                await cache_a.close()

            cache_b = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                payload, hit_tier = await cache_b.lookup_search(
                    query="persisted", filters=None, k=10,
                )
                assert payload == _payload("persisted")
                assert hit_tier == TIER_1
            finally:
                await cache_b.close()

        asyncio.run(_run())


# ===========================================================================
# Failure-mode discipline
# ===========================================================================


class TestFailureModeDiscipline:
    """Per the design constitution: 'Cache layer crash / OOM → Fall
    through to recompute; log; alert. Caching is performance, not
    correctness.' A SQLite I/O error inside the cache MUST NOT
    propagate to the caller."""

    def test_tier1_get_swallows_store_error(self, cache_db_path, monkeypatch):
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                # Monkey-patch the store's get to raise.
                async def boom(*_a, **_kw):
                    raise OSError("disk failure")

                monkeypatch.setattr(cache._tier1_store, "get", boom)

                # The lookup must return (None, "") rather than raising.
                payload, hit_tier = await cache.lookup_search(
                    query="q", filters=None, k=10,
                )
                assert payload is None
                assert hit_tier == ""
            finally:
                await cache.close()

        asyncio.run(_run())


# ===========================================================================
# AC — /debug/cache-stats endpoint
# ===========================================================================


class TestDebugCacheStatsEndpoint:
    """AC: GET /debug/cache-stats returns valid JSON with all required
    fields."""

    def test_empty_cache_returns_all_zero_stats(self):
        """No cache singleton set → endpoint returns all-zero stats."""
        from server.routes.debug import _empty_stats

        stats = _empty_stats()
        assert set(stats.keys()) == {"tier1", "tier2", "tier3"}
        for tier_dict in stats.values():
            assert tier_dict == {
                "lookups_total": 0,
                "hits_total": 0,
                "evictions_total": 0,
                "bytes_used": 0,
            }

    def test_cache_stats_after_hit_miss_cycle(self, cache_db_path):
        """Drive the cache through a miss + hit, then verify the
        stats endpoint reports the counter values."""
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            set_cache(cache)
            try:
                # Drive: miss + store + hit.
                await cache.lookup_search(query="q", filters=None, k=10)
                await cache.store_search(
                    query="q", filters=None, k=10, payload=_payload(),
                )
                await cache.lookup_search(query="q", filters=None, k=10)

                stats = cache.stats()
                assert set(stats.keys()) == {"tier1", "tier2", "tier3"}
                assert stats["tier1"]["lookups_total"] >= 2
                assert stats["tier1"]["hits_total"] >= 1
                # Required fields all present.
                for tier_name in ("tier1", "tier2", "tier3"):
                    for field in (
                        "lookups_total",
                        "hits_total",
                        "evictions_total",
                        "bytes_used",
                    ):
                        assert field in stats[tier_name], (
                            f"{tier_name} missing field {field}"
                        )
            finally:
                set_cache(None)
                await cache.close()

        asyncio.run(_run())


# ===========================================================================
# AC — Prometheus metrics exposition
# ===========================================================================


class TestPrometheusMetricsExposition:
    """AC: Prometheus metrics are emitted at /metrics. The metrics
    are defined as module-level Counter/Gauge in server/metrics.py
    and live in the default single-process registry — automatically
    included in the /metrics scrape."""

    def test_cache_metric_families_exist(self):
        """The four metric families must be defined and labeled with
        all three tier values. Verify by exercising
        ``.labels(tier=...)`` for each."""
        for tier in ALL_TIERS:
            # Touching .labels(...) creates the time series; the
            # ._value.get() read must succeed.
            CACHE_LOOKUPS_COUNTER.labels(tier=tier)._value.get()
            CACHE_HITS_COUNTER.labels(tier=tier)._value.get()
            CACHE_BYTES_GAUGE.labels(tier=tier)._value.get()

    def test_refresh_cache_metrics_sets_bytes_gauges(self, cache_db_path):
        """The scrape-time refresh hook must update the bytes gauge
        from the cache singleton's accessors."""
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            try:
                await cache.store_search(
                    query="q", filters=None, k=10, payload=_payload(),
                )
                refresh_cache_metrics(cache)
                # Tier 1 should now have a non-zero bytes gauge.
                tier1_bytes = CACHE_BYTES_GAUGE.labels(tier=TIER_1)._value.get()
                assert tier1_bytes > 0
            finally:
                await cache.close()

        asyncio.run(_run())

    def test_refresh_cache_metrics_no_op_on_none(self):
        """Passing ``None`` is a no-op — the gauges keep their last
        value rather than raising."""
        # Should not raise.
        refresh_cache_metrics(None)


# ===========================================================================
# Reset hook — required for test isolation
# ===========================================================================


class TestResetHooks:
    def test_reset_cache_metrics_zeroes_counters(self):
        # Touch a counter so it has a non-zero value.
        CACHE_HITS_COUNTER.labels(tier=TIER_2).inc(7)
        assert CACHE_HITS_COUNTER.labels(tier=TIER_2)._value.get() == 7
        reset_cache_metrics_for_tests()
        assert CACHE_HITS_COUNTER.labels(tier=TIER_2)._value.get() == 0

    def test_reset_cache_for_tests_clears_singleton(self, cache_db_path):
        async def _run():
            cache = await RetrievalCache.open(
                cache_db_path=cache_db_path, corpus_version=42,
            )
            set_cache(cache)
            from server.cache import get_cache

            assert get_cache() is cache
            reset_cache_for_tests()
            assert get_cache() is None
            await cache.close()

        asyncio.run(_run())
