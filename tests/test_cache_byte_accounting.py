"""Per-tier byte accounting and the Tier-1 mirror's byte ceiling.

The ``arxmcp_cache_bytes`` gauges are read on the event loop at every
``/metrics`` scrape, so they must be running sums kept on insert and
evict rather than a pass over the entries. They count UTF-8 bytes of
each payload's serialization, which is what the payload occupies once
it is stored, not its character count. And Tier-1's in-process mirror
is bounded by bytes as well as by entries: wide payloads cannot grow it
without limit, and an evicted entry is still served from SQLite.
"""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

import arxmcp.server.cache as cache_mod
from arxmcp.server.cache import EMBEDDING_DIM, RetrievalCache, reset_cache_for_tests
from arxmcp.server.cache_sqlite import Tier1Store
from arxmcp.server.metrics import (
    CACHE_BYTES_GAUGE,
    TIER_1,
    TIER_2,
    TIER_3,
    refresh_cache_metrics,
    reset_cache_metrics_for_tests,
)

CORPUS = 42


@pytest.fixture(autouse=True)
def _isolate_cache_state():
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()
    yield
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()


def _run(coro):
    return asyncio.run(coro)


def _serialized_len(payload) -> int:
    return len(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def _payload(label: str, body: str = "") -> dict:
    return {
        "results": [{"chunk_id": f"arxiv:demo:{label}", "snippet": body}],
        "retrieval_mode": "dense_only",
    }


def _embedding(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / float(np.linalg.norm(v))


def _gauge(tier: str) -> float:
    return CACHE_BYTES_GAUGE.labels(tier=tier)._value.get()


# ===========================================================================
# The gauges are honest running sums
# ===========================================================================


class TestTier1ByteCount:

    def test_counts_utf8_bytes_not_characters(self, tmp_path):
        greek = "Σ_{α∈Γ} ζ(α) ≤ ∏ ℓ-adic Ⅲ " * 40
        payload = _payload("greek", greek)

        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=CORPUS)
            try:
                await cache.store_search(query="q", filters=None, k=10, payload=payload)
                return cache.tier1_bytes_used()
            finally:
                await cache.close()

        used = _run(go())
        chars = len(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        assert used == _serialized_len(payload)
        assert used > chars

    def test_tracks_replacement_and_ttl_eviction(self, tmp_path, monkeypatch):
        small, large = _payload("a", "x" * 10), _payload("a", "x" * 5000)
        other = _payload("b", "y" * 300)

        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=CORPUS)
            try:
                await cache.store_search(query="q", filters=None, k=10, payload=small)
                await cache.store_search(query="r", filters=None, k=10, payload=other)
                assert cache.tier1_bytes_used() == (
                    _serialized_len(small) + _serialized_len(other)
                )

                # Re-storing the same key replaces its bytes, not adds.
                await cache.store_search(query="q", filters=None, k=10, payload=large)
                assert cache.tier1_bytes_used() == (
                    _serialized_len(large) + _serialized_len(other)
                )

                # Past the TTL, a read evicts the entry and its bytes go.
                real_time = cache_mod.time.time
                monkeypatch.setattr(
                    cache_mod.time, "time",
                    lambda: real_time() + cache_mod.TIER1_TTL_SECONDS + 60,
                )
                got, hit, _ = await cache.lookup_search(query="q", filters=None, k=10)
                assert (got, hit) == (None, "")
                got, hit, _ = await cache.lookup_search(query="r", filters=None, k=10)
                assert (got, hit) == (None, "")
                assert cache.tier1_bytes_used() == 0
            finally:
                await cache.close()

        _run(go())

    def test_rehydrated_mirror_is_counted(self, tmp_path):
        db = tmp_path / "c.db"
        payloads = [_payload(f"p{i}", "z" * (100 * i)) for i in range(4)]

        async def go():
            cache = await RetrievalCache.open(db, corpus_version=CORPUS)
            try:
                for i, p in enumerate(payloads):
                    await cache.store_search(query=f"q{i}", filters=None, k=10, payload=p)
            finally:
                await cache.close()
            reopened = await RetrievalCache.open(db, corpus_version=CORPUS)
            try:
                return reopened.tier1_bytes_used()
            finally:
                await reopened.close()

        assert _run(go()) == sum(_serialized_len(p) for p in payloads)


class TestTier2AndTier3ByteCounts:

    def test_tier2_counts_embedding_and_payload_and_clears(self, tmp_path):
        p1, p2 = _payload("a", "α" * 50), _payload("b", "β" * 70)

        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=CORPUS)
            try:
                e1, e2 = _embedding(1), _embedding(2)
                await cache.store_search(
                    query="q1", filters=None, k=10, payload=p1, query_embedding=e1,
                )
                await cache.store_search(
                    query="q2", filters=None, k=10, payload=p2, query_embedding=e2,
                )
                assert cache.tier2_bytes_used() == (
                    e1.nbytes + _serialized_len(p1) + e2.nbytes + _serialized_len(p2)
                )
                # Same embedding replaces the slot.
                await cache.store_search(
                    query="q1", filters=None, k=10, payload=p2, query_embedding=e1,
                )
                assert cache.tier2_bytes_used() == 2 * (e1.nbytes + _serialized_len(p2))

                await cache.invalidate_corpus_version()
                assert cache.tier2_bytes_used() == 0
            finally:
                await cache.close()

        _run(go())

    def test_tier3_counts_payload_and_evicts_at_capacity(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_mod, "TIER3_LRU_CAPACITY", 2)
        ranked = [("arxiv:demo:1", 0.9), ("arxiv:demo:2", 0.8)]
        one = _serialized_len(ranked)

        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=CORPUS)
            try:
                for seed in range(3):
                    await cache.store_rerank(_embedding(seed), ranked, ranked)
                assert cache.tier3_bytes_used() == 2 * one
                await cache.invalidate_corpus_version()
                assert cache.tier3_bytes_used() == 0
            finally:
                await cache.close()

        _run(go())


class TestScrapeDoesNotSerialize:

    def test_metrics_refresh_reads_sums_without_serializing(self, tmp_path, monkeypatch):
        payload = _payload("a", "x" * 1000)
        ranked = [("arxiv:demo:1", 0.5)]
        payload_len, ranked_len = _serialized_len(payload), _serialized_len(ranked)

        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=CORPUS)
            try:
                await cache.store_search(
                    query="q", filters=None, k=10, payload=payload,
                    query_embedding=_embedding(7),
                )
                await cache.store_rerank(_embedding(8), ranked, ranked)

                def _refuse(*_a, **_kw):
                    raise AssertionError("a metrics scrape serialized a payload")

                with monkeypatch.context() as m:
                    m.setattr(cache_mod.json, "dumps", _refuse)
                    refresh_cache_metrics(cache)
                    stats = cache.stats()
                return stats
            finally:
                await cache.close()

        stats = _run(go())
        assert _gauge(TIER_1) == payload_len
        assert _gauge(TIER_2) == _embedding(7).nbytes + payload_len
        assert _gauge(TIER_3) == ranked_len
        assert stats["tier1"]["bytes_used"] == payload_len


# ===========================================================================
# The Tier-1 mirror's byte ceiling
# ===========================================================================


class TestTier1ByteCeiling:

    def test_mirror_evicts_lru_to_stay_under_the_ceiling(self, tmp_path):
        payloads = [_payload(f"p{i}", "x" * 400) for i in range(6)]
        each = _serialized_len(payloads[0])
        ceiling = 3 * each

        async def go():
            cache = await RetrievalCache.open(
                tmp_path / "c.db", corpus_version=CORPUS, tier1_max_bytes=ceiling,
            )
            try:
                for i, p in enumerate(payloads):
                    await cache.store_search(query=f"q{i}", filters=None, k=10, payload=p)
                    assert cache.tier1_bytes_used() <= ceiling
                assert cache.tier1_bytes_used() == ceiling
                assert len(cache._tier1_mirror) == 3

                # An entry evicted from memory is still a Tier-1 hit:
                # its SQLite row was never touched.
                got, hit, _ = await cache.lookup_search(query="q0", filters=None, k=10)
                assert hit == "1"
                assert got == payloads[0]
                assert cache.tier1_bytes_used() <= ceiling
            finally:
                await cache.close()

        _run(go())

    def test_recently_read_entries_survive_eviction(self, tmp_path):
        payloads = [_payload(f"p{i}", "x" * 400) for i in range(4)]
        ceiling = 3 * _serialized_len(payloads[0])

        async def go():
            cache = await RetrievalCache.open(
                tmp_path / "c.db", corpus_version=CORPUS, tier1_max_bytes=ceiling,
            )
            try:
                for i in range(3):
                    await cache.store_search(
                        query=f"q{i}", filters=None, k=10, payload=payloads[i],
                    )
                await cache.lookup_search(query="q0", filters=None, k=10)
                await cache.store_search(query="q3", filters=None, k=10, payload=payloads[3])
                mirrored = {cache._tier1_mirror[k][0]["results"][0]["chunk_id"]
                            for k in cache._tier1_mirror}
                return mirrored
            finally:
                await cache.close()

        assert _run(go()) == {"arxiv:demo:p0", "arxiv:demo:p2", "arxiv:demo:p3"}

    def test_an_entry_larger_than_the_ceiling_is_served_from_sqlite(self, tmp_path):
        small = _payload("small", "x" * 10)
        huge = _payload("huge", "x" * 10_000)
        ceiling = 2_000

        async def go():
            cache = await RetrievalCache.open(
                tmp_path / "c.db", corpus_version=CORPUS, tier1_max_bytes=ceiling,
            )
            try:
                await cache.store_search(query="s", filters=None, k=10, payload=small)
                await cache.store_search(query="h", filters=None, k=10, payload=huge)
                # The huge entry did not push the small one out.
                assert cache.tier1_bytes_used() == _serialized_len(small)
                got, hit, _ = await cache.lookup_search(query="h", filters=None, k=10)
                assert (got, hit) == (huge, "1")
                assert cache.tier1_bytes_used() == _serialized_len(small)

                # Replacing a mirrored key with an oversized payload must
                # not leave the old payload in the mirror.
                await cache.store_search(query="s", filters=None, k=10, payload=huge)
                got, hit, _ = await cache.lookup_search(query="s", filters=None, k=10)
                assert (got, hit) == (huge, "1")
                assert cache.tier1_bytes_used() == 0
            finally:
                await cache.close()

        _run(go())

    def test_rehydrate_keeps_the_freshest_rows_that_fit(self, tmp_path):
        db = tmp_path / "c.db"
        blob = json.dumps({"v": "x" * 100}).encode("utf-8")

        async def go():
            store = await Tier1Store.open(db)
            for i in range(5):
                await store.put(
                    f"row-{i}", blob, ttl_seconds=3600.0 + i, corpus_version=CORPUS,
                )
            await store.close()
            cache = await RetrievalCache.open(
                db, corpus_version=CORPUS, tier1_max_bytes=2 * len(blob),
            )
            try:
                return list(cache._tier1_mirror), cache.tier1_bytes_used()
            finally:
                await cache.close()

        keys, used = _run(go())
        # Freshest last, so it is the last the LRU would evict.
        assert keys == ["row-3", "row-4"]
        assert used == 2 * len(blob)

    def test_a_non_positive_ceiling_is_refused(self, tmp_path):
        async def go():
            store = await Tier1Store.open(tmp_path / "c.db")
            try:
                with pytest.raises(ValueError):
                    RetrievalCache(tier1_store=store, corpus_version=CORPUS, tier1_max_bytes=0)
            finally:
                await store.close()

        _run(go())
