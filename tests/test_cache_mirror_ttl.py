"""Tier-1 mirror fidelity — GitHub issue #338's two amplifiers.

#338's headline defect (no corpus-freshness seam) was closed by #207.
These are the two amplifiers underneath it, both in the Tier-1 mirror:

**Amplifier 1 — TTL doubling.** ``_tier1_get`` fell through to SQLite on
a mirror miss and re-cached the payload under a fresh
``now + TIER1_TTL_SECONDS`` window instead of the row's stored
``expires_at``. The code called that "a small approximation … worst
case: served slightly past TTL". The worst case is 2x: a row written at
T and first read at T+3599 stayed live in the mirror until T+7199. Worse,
every later mirror-miss read renewed it again, so a steadily-read key
could outlive its TTL without bound.

**Amplifier 2 — rehydrate ignored corpus_version.**
``_rehydrate_tier1_from_sqlite`` loaded every unexpired row regardless of
version. Rows from another corpus version are unreachable by hash
construction (the key is salted with it), so they consumed slots in the
10K-bounded mirror and the cap evicted live entries in their favour.

The second fix depends on the first two issues in this family: #337 made
the ``corpus_version`` column honest (before it, filtering on the column
would have dropped REACHABLE notebook rows), and #204 added the embedder
key component, which retroactively orphaned every row written by an older
binary — exactly the population this filter now keeps out of the mirror.
"""

from __future__ import annotations

import asyncio

import pytest

from server.cache import (
    TIER1_TTL_SECONDS,
    RetrievalCache,
    reset_cache_for_tests,
)
from server.cache_sqlite import Tier1Store, derive_tier1_key
from server.metrics import reset_cache_metrics_for_tests

SHARED = 101


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_cache_state():
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()
    yield
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()


# ===========================================================================
# Amplifier 1 — the mirror inherits the row's expiry, never mints new life
# ===========================================================================


class TestMirrorInheritsRowExpiry:

    def test_sqlite_fallthrough_does_not_extend_the_ttl(self, tmp_path):
        """THE BUG. Write a row, drop it from the mirror so the next read
        goes to SQLite, and assert the re-cached mirror entry carries the
        ROW's expiry rather than a fresh full window."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "a.db", corpus_version=SHARED)
            try:
                await cache.store_search(
                    query="q", filters=None, k=10, payload={"results": []},
                    level="theorem",
                )
                key = next(iter(cache._tier1_mirror))
                _payload, original_expiry = cache._tier1_mirror[key]

                # Evict from the mirror ONLY; the SQLite row stays live.
                cache._tier1_mirror.clear()

                got = await cache._tier1_get(key)
                assert got is not None, "row should still be served from SQLite"
                _payload2, recached_expiry = cache._tier1_mirror[key]

                assert recached_expiry == pytest.approx(original_expiry, abs=1e-6), (
                    "the mirror minted a new TTL window instead of "
                    "inheriting the row's remaining life"
                )
            finally:
                await cache.close()

        _run(go())

    def test_the_mirror_and_the_row_agree_at_write_time(
        self, tmp_path, monkeypatch,
    ):
        """The invariant the loop test below depends on, pinned directly.

        ``_tier1_put`` writes SQLite and the mirror. If it reads the
        clock twice, the two expiries differ by however long the write
        took — the mirror is not-quite-mirroring the row it was created
        alongside.

        **Driven by an injected clock, deliberately.** The real
        ``time.time()`` cannot express this test on Windows: its ~15.6 ms
        granularity makes two consecutive readings usually identical, so
        a wall-clock version passes against the broken code and fails
        only when the two readings straddle a tick. That is precisely how
        the bug hid, and a test with the same blind spot would be
        decoration. A clock that advances 1 ms per call makes a second
        reading observable, so the assertion below is decided by the
        code's structure rather than by scheduling luck.

        Both ``server.cache`` and ``server.cache_sqlite`` do ``import
        time`` and call ``time.time()``, so patching the module
        attribute covers the pair.
        """
        import time as _time

        ticks = iter(range(10_000))
        base = 1_800_000_000.0
        monkeypatch.setattr(
            _time, "time", lambda: base + next(ticks) / 1000.0,
        )

        async def go():
            cache = await RetrievalCache.open(tmp_path / "x.db", corpus_version=SHARED)
            try:
                await cache.store_search(
                    query="q", filters=None, k=10, payload={"results": []},
                    level="theorem",
                )
                key = next(iter(cache._tier1_mirror))
                _payload, mirror_expiry = cache._tier1_mirror[key]

                row = await cache._tier1_store.get_with_expiry(key)
                assert row is not None
                _blob, row_expiry = row

                assert mirror_expiry == row_expiry, (
                    f"mirror expiry {mirror_expiry!r} != row expiry "
                    f"{row_expiry!r}; _tier1_put read the clock twice, so "
                    f"the mirror does not mirror the row it was written "
                    f"beside"
                )
            finally:
                await cache.close()

        _run(go())

    def test_repeated_mirror_misses_cannot_renew_indefinitely(self, tmp_path):
        """The compounding half. Ten fall-through reads must not push the
        expiry out ten times — pre-#338 each one restarted the clock."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "b.db", corpus_version=SHARED)
            try:
                await cache.store_search(
                    query="q", filters=None, k=10, payload={"results": []},
                    level="theorem",
                )
                key = next(iter(cache._tier1_mirror))
                _p, original_expiry = cache._tier1_mirror[key]

                for _ in range(10):
                    cache._tier1_mirror.clear()
                    await cache._tier1_get(key)

                _p2, final_expiry = cache._tier1_mirror[key]
                assert final_expiry == pytest.approx(original_expiry, abs=1e-6)
            finally:
                await cache.close()

        _run(go())

    def test_a_nearly_expired_row_is_not_resurrected(self, tmp_path):
        """The scenario in the issue: a row read late in its life must
        keep its short remaining window, not gain a full fresh one."""
        async def go():
            store = await Tier1Store.open(tmp_path / "c.db")
            cache = RetrievalCache(tier1_store=store, corpus_version=SHARED)
            try:
                # Write directly with a 1-second remaining TTL.
                key = derive_tier1_key("q", None, 10, SHARED, level="theorem")
                await store.put(
                    key, b'{"results": []}',
                    ttl_seconds=1.0, corpus_version=SHARED,
                )
                got = await cache._tier1_get(key)
                assert got is not None

                _p, expiry = cache._tier1_mirror[key]
                import time
                remaining = expiry - time.time()
                assert remaining < 5.0, (
                    f"mirror gave a nearly-expired row {remaining:.0f}s of "
                    f"life; the row had ~1s and the full TTL is "
                    f"{TIER1_TTL_SECONDS:.0f}s"
                )
            finally:
                await cache.close()

        _run(go())

    def test_get_still_returns_a_bare_blob(self, tmp_path):
        """``get`` keeps its documented contract — #338 added
        ``get_with_expiry`` alongside it rather than changing it, because
        three callers read the bare blob."""
        async def go():
            store = await Tier1Store.open(tmp_path / "d.db")
            try:
                await store.put(
                    "k", b"payload", ttl_seconds=60.0, corpus_version=SHARED)
                assert await store.get("k") == b"payload"
                row = await store.get_with_expiry("k")
                assert row is not None
                blob, expires_at = row
                assert blob == b"payload"
                assert expires_at > 0
                # Both agree on absence.
                assert await store.get("missing") is None
                assert await store.get_with_expiry("missing") is None
            finally:
                await store.close()

        _run(go())


# ===========================================================================
# Amplifier 2 — rehydrate loads only the active corpus version
# ===========================================================================


class TestRehydrateFiltersByCorpusVersion:

    def test_other_version_rows_stay_out_of_the_mirror(self, tmp_path):
        """Rows salted with another version are unreachable by hash
        construction; rehydrating them burns bounded mirror slots."""
        async def go():
            db = tmp_path / "e.db"
            store = await Tier1Store.open(db)
            live = derive_tier1_key("q", None, 10, SHARED, level="theorem")
            dead = derive_tier1_key("q", None, 10, SHARED - 1, level="theorem")
            await store.put(
                live, b'{"v": "live"}', ttl_seconds=3600.0,
                corpus_version=SHARED)
            await store.put(
                dead, b'{"v": "dead"}', ttl_seconds=3600.0,
                corpus_version=SHARED - 1)
            await store.close()

            cache = await RetrievalCache.open(db, corpus_version=SHARED)
            try:
                assert live in cache._tier1_mirror
                assert dead not in cache._tier1_mirror, (
                    "a row from another corpus version was rehydrated; it "
                    "can never be hit, and it displaces one that can"
                )
            finally:
                await cache.close()

        _run(go())

    def test_the_unreachable_rows_are_left_on_disk(self, tmp_path):
        """Filtering the REHYDRATE is not deletion. Reclamation is
        ``purge_other_corpus_versions``'s job, so a row that is merely
        not-mine must survive an open that does not purge."""
        async def go():
            db = tmp_path / "f.db"
            store = await Tier1Store.open(db)
            dead = derive_tier1_key("q", None, 10, SHARED - 1, level="theorem")
            await store.put(
                dead, b'{"v": "dead"}', ttl_seconds=3600.0,
                corpus_version=SHARED - 1)
            await store.close()

            cache = await RetrievalCache.open(db, corpus_version=SHARED)
            try:
                assert await cache._tier1_store.row_count() == 1
            finally:
                await cache.close()

        _run(go())

    def test_load_all_unexpired_still_loads_everything_when_unfiltered(
        self, tmp_path,
    ):
        """The filter is opt-in: ops inspection and tests that want the
        whole table still get it."""
        async def go():
            store = await Tier1Store.open(tmp_path / "g.db")
            try:
                await store.put(
                    "a", b"1", ttl_seconds=3600.0, corpus_version=SHARED)
                await store.put(
                    "b", b"2", ttl_seconds=3600.0, corpus_version=SHARED - 1)
                assert len(await store.load_all_unexpired()) == 2
                assert len(
                    await store.load_all_unexpired(corpus_version=SHARED)
                ) == 1
            finally:
                await store.close()

        _run(go())

    def test_a_full_table_of_dead_rows_yields_an_empty_mirror(self, tmp_path):
        """The #204 deploy scenario: adding the embedder key component
        orphaned every row an older binary wrote. The first restart after
        that must not rehydrate a mirror full of entries that can never
        be hit."""
        async def go():
            db = tmp_path / "h.db"
            store = await Tier1Store.open(db)
            for i in range(50):
                await store.put(
                    f"orphan-{i}", b'{"v": 1}', ttl_seconds=3600.0,
                    corpus_version=SHARED - 1,
                )
            await store.close()

            cache = await RetrievalCache.open(db, corpus_version=SHARED)
            try:
                assert len(cache._tier1_mirror) == 0
                # Still on disk, awaiting purge.
                assert await cache._tier1_store.row_count() == 50
            finally:
                await cache.close()

        _run(go())
