"""Corpus-freshness seam (issue #207).

``server/corpus.py`` declared cache invalidation on a corpus-version
change a MUST and asserted the implementation honored it. It did not:
``purge_other_corpus_versions`` had zero callers repo-wide,
``Resources.notebook_table`` memoized ``(table, corpus_info)`` with no
re-check, and nothing re-read the marker after startup. The reachable
consequence — the operator clicks **Ingest** in the shipped ``/ui/``
console and the running server keeps serving the memoized pre-ingest
table while echoing the OLD ``corpus_version`` as truth.

Acceptance criteria → test:

- freshness seam detects a bump and drops the memoized table
  → ``TestNotebookTableFreshness`` (per-call notebook registry)
  → ``TestMidSessionIngest`` (process corpus, both trigger paths)
- ``purge_other_corpus_versions`` is actually called
  → ``TestPurgeIsWired``
- a test that ingests mid-session and asserts the next query reflects
  the new corpus AND echoes the new ``corpus_version``
  → ``TestMidSessionIngest.test_mid_session_ingest_over_the_mcp_wire``
  (the headline: a real LanceDB corpus, a real lifespan, real
  ``tools/call`` requests, a real ``write_chunks`` between them)

The gate's throttle/single-flight behavior is unit-tested with an
injected clock (``TestFreshnessGate``) so no test sleeps.

**Why the headline test writes a real corpus rather than mocking.** The
bug was a *seam* bug: every individual component behaved as documented,
and the failure lived in the fact that no component re-asked the
question. A mock-heavy test would have re-encoded the same assumption
that broke, so the load-bearing assertions here run against a real
``write_chunks`` → real marker → real ``lancedb.checkout`` chain.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ingest.embedder import EMBEDDING_DIM
from server.config import Config
from server.corpus_freshness import (
    DEFAULT_FRESHNESS_INTERVAL_SECONDS,
    FreshnessGate,
    read_marker_off_loop,
)
from server.health import reset_metrics_for_tests
from server.main import create_app
from server.tools import reset_resources_for_tests
from tests._corpus_helpers import patch_bge_m3_model, seed_corpus


def _run(coro):
    return asyncio.run(coro)


class _FakeClock:
    """Monotonic clock the test advances by hand.

    The gate takes ``clock`` precisely so throttle behavior is testable
    without ``time.sleep`` — a sleeping test would be both slow and
    flaky on a loaded CI box.
    """

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ===========================================================================
# FreshnessGate — throttle + single-flight, no I/O
# ===========================================================================


class TestFreshnessGate:
    def test_first_call_is_due(self) -> None:
        gate = FreshnessGate(2.0, clock=_FakeClock())
        assert gate.is_due() is True

    def test_throttles_within_the_interval(self) -> None:
        clock = _FakeClock()
        gate = FreshnessGate(2.0, clock=clock)

        async def go():
            calls = []

            async def probe():
                calls.append(1)
                return "probed"

            first = await gate.run_if_due(probe)
            clock.advance(0.5)
            second = await gate.run_if_due(probe)
            clock.advance(2.0)
            third = await gate.run_if_due(probe)
            return calls, first, second, third

        calls, first, second, third = _run(go())
        assert first == "probed"
        assert second is None, "a call inside the window must be skipped"
        assert third == "probed", "a call past the interval must probe again"
        assert len(calls) == 2
        assert gate.probe_count == 2

    def test_zero_interval_probes_every_call(self) -> None:
        clock = _FakeClock()
        gate = FreshnessGate(0.0, clock=clock)

        async def go():
            probe_calls = []

            async def probe():
                probe_calls.append(1)
                return True

            for _ in range(3):
                await gate.run_if_due(probe)
            return probe_calls

        assert len(_run(go())) == 3

    def test_negative_interval_disables_the_pull_path(self) -> None:
        """An operator opting out must get a true no-op, not a slow one."""
        gate = FreshnessGate(-1.0, clock=_FakeClock())
        assert gate.enabled is False

        async def go():
            calls = []

            async def probe():
                calls.append(1)
                return True

            skipped = await gate.run_if_due(probe)
            return skipped, calls

        skipped, calls = _run(go())
        assert skipped is None
        assert calls == []

    def test_force_overrides_both_throttle_and_disabled(self) -> None:
        """The PUSH path (ingest completion) knows a bump just happened;
        it must not wait out an interval, and must still work when the
        operator disabled the request-path probe."""
        clock = _FakeClock()
        gate = FreshnessGate(-1.0, clock=clock)

        async def go():
            calls = []

            async def probe():
                calls.append(1)
                return "rebound"

            forced = await gate.run_if_due(probe, force=True)
            # Immediately again, still forced, zero elapsed time.
            forced_again = await gate.run_if_due(probe, force=True)
            return forced, forced_again, calls

        forced, forced_again, calls = _run(go())
        assert forced == "rebound"
        assert forced_again == "rebound"
        assert len(calls) == 2

    def test_concurrent_callers_single_flight(self) -> None:
        """N requests observing the same bump must trigger ONE rebind.

        Without the gate's lock, every in-flight request would open its
        own chunks table, BM25 artifact and cache — an fd storm on the
        one event the seam exists to handle.
        """
        clock = _FakeClock()
        gate = FreshnessGate(5.0, clock=clock)

        async def go():
            calls = []

            async def probe():
                calls.append(1)
                # Yield so the other waiters get a chance to run and
                # would double-probe if the lock were absent.
                await asyncio.sleep(0)
                return True

            results = await asyncio.gather(
                *[gate.run_if_due(probe) for _ in range(8)]
            )
            return calls, results

        calls, results = _run(go())
        assert len(calls) == 1, f"expected 1 probe, got {len(calls)}"
        assert results.count(True) == 1
        assert results.count(None) == 7

    def test_failing_probe_still_marks_the_gate(self) -> None:
        """A probe that raises every time must not become a hot loop of
        failing probes on the request path."""
        clock = _FakeClock()
        gate = FreshnessGate(2.0, clock=clock)

        async def go():
            calls = []

            async def probe():
                calls.append(1)
                raise RuntimeError("marker read blew up")

            with pytest.raises(RuntimeError):
                await gate.run_if_due(probe)
            # Inside the window now — must be skipped, not retried.
            skipped = await gate.run_if_due(probe)
            return calls, skipped

        calls, skipped = _run(go())
        assert len(calls) == 1
        assert skipped is None

    def test_reset_makes_the_gate_due_again(self) -> None:
        clock = _FakeClock()
        gate = FreshnessGate(60.0, clock=clock)

        async def go():
            async def probe():
                return True

            await gate.run_if_due(probe)
            before = gate.is_due()
            gate.reset()
            return before, gate.is_due()

        before, after = _run(go())
        assert before is False
        assert after is True

    def test_default_interval_is_positive(self) -> None:
        """A zero/negative default would silently change the shipped
        behavior of every deployment that never sets the env var."""
        assert DEFAULT_FRESHNESS_INTERVAL_SECONDS > 0


# ===========================================================================
# read_marker_off_loop — every ambiguous read degrades to "keep serving"
# ===========================================================================


class TestReadMarkerOffLoop:
    def test_reads_a_valid_marker(self, tmp_path) -> None:
        from server.corpus import read_corpus_version

        seed_corpus(tmp_path / "lancedb", n=2)
        info = _run(
            read_marker_off_loop(
                tmp_path / "lancedb", reader=read_corpus_version
            )
        )
        assert info is not None
        assert info.version >= 1

    def test_absent_marker_returns_none(self, tmp_path) -> None:
        from server.corpus import read_corpus_version

        info = _run(
            read_marker_off_loop(tmp_path / "nope", reader=read_corpus_version)
        )
        assert info is None

    def test_corrupt_marker_returns_none_and_does_not_raise(
        self, tmp_path
    ) -> None:
        """A half-written marker is the NORMAL state during an ingest's
        atomic-rename window. Raising here would turn a routine race
        into operator-visible tool failures."""
        from server.corpus import read_corpus_version

        lancedb_path = tmp_path / "lancedb"
        lancedb_path.mkdir(parents=True)
        (lancedb_path / "corpus-version.json").write_text(
            "{not json", encoding="utf-8"
        )
        info = _run(
            read_marker_off_loop(lancedb_path, reader=read_corpus_version)
        )
        assert info is None


# ===========================================================================
# purge_other_corpus_versions — the MUST that had zero callers
# ===========================================================================


class TestPurgeIsWired:
    def test_open_with_purge_drops_other_versions(self, tmp_path) -> None:
        from server.cache import RetrievalCache
        from server.cache_sqlite import Tier1Store

        db = tmp_path / "retrieval.db"

        async def go():
            store = await Tier1Store.open(db)
            await store.put(
                key="old-key", value=b'{"x":1}', corpus_version=1,
            )
            await store.put(
                key="new-key", value=b'{"x":2}', corpus_version=2,
            )
            await store.close()

            cache = await RetrievalCache.open(
                cache_db_path=db, corpus_version=2, purge_other_versions=True
            )
            try:
                remaining = await cache._tier1_store.row_count()
                survivor = await cache._tier1_store.get("new-key")
                evicted = await cache._tier1_store.get("old-key")
            finally:
                await cache.close()
            return remaining, survivor, evicted

        remaining, survivor, evicted = _run(go())
        assert remaining == 1
        assert survivor is not None
        assert evicted is None

    def test_open_without_purge_keeps_other_versions(self, tmp_path) -> None:
        """Cold start has no previous in-process version to invalidate,
        so the default must leave the file alone — a restart should not
        silently throw away a warm cross-version cache."""
        from server.cache import RetrievalCache
        from server.cache_sqlite import Tier1Store

        db = tmp_path / "retrieval.db"

        async def go():
            store = await Tier1Store.open(db)
            await store.put(key="old-key", value=b"{}", corpus_version=1)
            await store.close()
            cache = await RetrievalCache.open(cache_db_path=db, corpus_version=2)
            try:
                return await cache._tier1_store.row_count()
            finally:
                await cache.close()

        assert _run(go()) == 1

    def test_purge_has_a_production_caller(self) -> None:
        """Regression pin for the #207 finding itself.

        The method existed, was documented as the mechanism serving a
        declared MUST, and had ZERO callers outside its own definition.
        A docstring is not an implementation; this asserts the call site
        exists in shipped code, so deleting it fails loudly here rather
        than quietly re-opening the issue.
        """
        import inspect

        import server.cache as cache_mod
        import server.resources as resources_mod

        cache_src = inspect.getsource(cache_mod)
        assert "purge_other_corpus_versions(" in cache_src, (
            "server/cache.py must CALL purge_other_corpus_versions — the "
            "cache-invalidation MUST in server/corpus.py depends on it"
        )
        resources_src = inspect.getsource(resources_mod)
        assert "purge_other_versions=True" in resources_src, (
            "the corpus-rebind path must request the purge; without it the "
            "call site in server/cache.py is itself unreachable"
        )

    def test_invalidate_corpus_version_clears_tier2_and_tier3(
        self, tmp_path
    ) -> None:
        """The semantic tiers are droppable on demand.

        Tier-3 is the one that still NEEDS this — its key is
        ``sha256(embedding + candidate_ids + reranker_version)`` with no
        corpus version, so a re-ingest that edits a chunk's body while
        keeping its ``chunk_id`` leaves a reachable, stale rerank memo.
        Tier-2 became version-scoped in #204 and is now reclamation
        rather than correctness — see
        ``RetrievalCache.invalidate_corpus_version``. Both are asserted
        here so a future key change on either side does not silently
        remove the guarantee.
        """
        from server.cache import RetrievalCache

        async def go():
            cache = await RetrievalCache.open(
                cache_db_path=tmp_path / "retrieval.db", corpus_version=1
            )
            try:
                vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
                vec[0] = 1.0
                await cache.store_search(
                    query="q", filters=None, k=5,
                    payload={"results": ["stale"]}, query_embedding=vec,
                )
                await cache.store_rerank(
                    query_embedding=vec,
                    candidates=[("arxiv:2307.00001:aaaa", 0.9)],
                    payload=[("arxiv:2307.00001:aaaa", 0.99)],
                )
                t2_before, _tier, _m = await cache.lookup_search(
                    query="different phrasing entirely",
                    filters=None, k=5, query_embedding=vec,
                )
                t3_before = await cache.lookup_rerank(
                    query_embedding=vec,
                    candidates=[("arxiv:2307.00001:aaaa", 0.9)],
                )
                dropped = await cache.invalidate_corpus_version()
                t2_after, _tier2, _m2 = await cache.lookup_search(
                    query="different phrasing entirely",
                    filters=None, k=5, query_embedding=vec,
                )
                t3_after = await cache.lookup_rerank(
                    query_embedding=vec,
                    candidates=[("arxiv:2307.00001:aaaa", 0.9)],
                )
                return t2_before, t3_before, dropped, t2_after, t3_after
            finally:
                await cache.close()

        t2_before, t3_before, dropped, t2_after, t3_after = _run(go())
        assert t2_before is not None, (
            "precondition: an identical embedding must hit Tier-2 before "
            "the invalidation (otherwise this test proves nothing)"
        )
        assert t3_before is not None, (
            "precondition: the rerank memo must hit before the invalidation"
        )
        assert dropped >= 2
        assert t2_after is None, "Tier-2 entry survived invalidate_corpus_version"
        assert t3_after is None, "Tier-3 entry survived invalidate_corpus_version"


# ===========================================================================
# Per-call notebook registry — the memoization #207 names directly
# ===========================================================================


class TestNotebookTableFreshness:
    """``Resources.notebook_table`` memoized ``(table, corpus_info)`` for
    process lifetime with no mtime or version recheck. These drive the
    registry directly with the marker reader and table opener faked, so
    the assertions are about the SEAM (does it re-ask?) rather than
    about LanceDB.
    """

    @staticmethod
    def _make_resources(interval: float = 0.0):
        import asyncio as _asyncio

        from server.resources import Resources, Singleflight

        return Resources(
            config=Config(corpus_freshness_interval_seconds=interval),
            corpus_info=SimpleNamespace(version=1),
            chunks_table=None,
            embed_semaphore=_asyncio.Semaphore(1),
            rerank_semaphore=_asyncio.Semaphore(1),
            rerank_singleflight=Singleflight(),
        )

    @pytest.fixture
    def faked_notebook_io(self, monkeypatch, tmp_path):
        """Fake the path helper, marker reader and table opener; keep the
        REAL ``validate_slug``. ``version_box`` is the on-disk version the
        test mutates to simulate an ingest."""
        import server.resources as res_mod
        import tools._notebook_common as nc

        monkeypatch.setattr(
            nc, "notebook_lancedb_path",
            lambda slug, **kw: tmp_path / slug / "lancedb",
        )
        state = SimpleNamespace(version=7, opens=[], marker_reads=0)

        def fake_read_cv(path):
            state.marker_reads += 1
            if state.version is None:
                return None
            return SimpleNamespace(version=state.version)

        def fake_open(*, lancedb_path, version):
            state.opens.append(version)
            return (SimpleNamespace(pinned=version), None)

        monkeypatch.setattr(res_mod, "read_corpus_version", fake_read_cv)
        monkeypatch.setattr(
            res_mod, "open_chunks_table_with_fallback", fake_open
        )
        return state

    def test_unchanged_version_reuses_the_memoized_handle(
        self, faked_notebook_io
    ) -> None:
        """The memoization contract still holds — the freshness probe
        must not turn every query into a table re-open."""
        res = self._make_resources(interval=0.0)

        async def go():
            t1, i1 = await res.notebook_table("alpha-nb")
            t2, i2 = await res.notebook_table("alpha-nb")
            return t1, t2, i1, i2

        t1, t2, i1, i2 = _run(go())
        assert t1 is t2
        assert i1.version == i2.version == 7
        assert faked_notebook_io.opens == [7], (
            f"expected exactly one open, got {faked_notebook_io.opens}"
        )

    def test_version_bump_drops_and_reopens(self, faked_notebook_io) -> None:
        """THE per-notebook acceptance criterion: a mid-session bump is
        detected, the memoized table is dropped, and the caller gets the
        new corpus AND the new version."""
        res = self._make_resources(interval=0.0)

        async def go():
            _t1, i1 = await res.notebook_table("alpha-nb")
            faked_notebook_io.version = 8  # the ingest lands
            t2, i2 = await res.notebook_table("alpha-nb")
            return i1, t2, i2

        i1, t2, i2 = _run(go())
        assert i1.version == 7
        assert i2.version == 8, (
            "notebook_table served the stale memoized corpus_info after a "
            "version bump — this is exactly issue #207"
        )
        assert t2.pinned == 8
        assert faked_notebook_io.opens == [7, 8]

    def test_absent_marker_keeps_serving(self, faked_notebook_io) -> None:
        """A marker that vanishes mid-session (delete/re-create window,
        atomic-rename race) must NOT drop a live table. Ambiguity means
        keep serving."""
        res = self._make_resources(interval=0.0)

        async def go():
            t1, _i1 = await res.notebook_table("alpha-nb")
            faked_notebook_io.version = None  # marker unreadable
            t2, i2 = await res.notebook_table("alpha-nb")
            return t1, t2, i2

        t1, t2, i2 = _run(go())
        assert t1 is t2
        assert i2.version == 7
        assert faked_notebook_io.opens == [7]

    def test_throttle_suppresses_the_probe_within_the_window(
        self, faked_notebook_io
    ) -> None:
        """With the production default interval, a hot notebook must not
        pay a marker read per query."""
        res = self._make_resources(interval=60.0)

        async def go():
            await res.notebook_table("alpha-nb")
            reads_after_open = faked_notebook_io.marker_reads
            for _ in range(5):
                await res.notebook_table("alpha-nb")
            return reads_after_open, faked_notebook_io.marker_reads

        after_open, after_queries = _run(go())
        assert after_queries == after_open, (
            "the freshness probe ran inside the throttle window; a 10 req/s "
            "workload would pay a stat+read per call"
        )

    def test_invalidate_notebook_table_drops_the_entry(
        self, faked_notebook_io
    ) -> None:
        """The PUSH path's per-notebook step: an explicit drop, no probe
        required."""
        res = self._make_resources(interval=60.0)

        async def go():
            await res.notebook_table("alpha-nb")
            dropped = await res.invalidate_notebook_table("alpha-nb")
            faked_notebook_io.version = 9
            _t, info = await res.notebook_table("alpha-nb")
            missing = await res.invalidate_notebook_table("never-opened")
            return dropped, info, missing

        dropped, info, missing = _run(go())
        assert dropped is True
        assert info.version == 9
        assert missing is False

    def test_lru_eviction_prunes_the_gate_registry(
        self, faked_notebook_io
    ) -> None:
        """m2 FM-6 bounded the table registry; #207 added a parallel gate
        dict that must be bounded in lockstep or it reintroduces the same
        unbounded-growth shape one dict over."""
        from server.resources import MAX_NOTEBOOK_TABLE_SLOTS

        res = self._make_resources(interval=0.0)

        async def go():
            for i in range(MAX_NOTEBOOK_TABLE_SLOTS + 5):
                await res.notebook_table(f"nb-{i:03d}")

        _run(go())
        assert len(res._notebook_tables) == MAX_NOTEBOOK_TABLE_SLOTS
        assert len(res._notebook_gates) <= MAX_NOTEBOOK_TABLE_SLOTS


# ===========================================================================
# Mid-session ingest — the headline acceptance criterion
# ===========================================================================


_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Host": "127.0.0.1:7733",
    "Mcp-Protocol-Version": "2025-06-18",
}


def _initialize_session(client: TestClient) -> str:
    r = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers=_MCP_HEADERS,
    )
    if r.status_code != 200:
        raise AssertionError(f"initialize failed: {r.status_code} {r.text[:200]}")
    sid = r.headers["mcp-session-id"]
    client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={**_MCP_HEADERS, "mcp-session-id": sid},
    )
    return sid


def _search(client: TestClient, sid: str, query: str, k: int = 20) -> dict:
    r = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_papers",
                "arguments": {"query": query, "k": k},
            },
        },
        headers={**_MCP_HEADERS, "mcp-session-id": sid},
    )
    if r.status_code != 200:
        raise AssertionError(f"tools/call failed: {r.status_code} {r.text[:300]}")
    body = r.json()
    if "result" not in body:
        raise AssertionError(f"tools/call returned no result: {body}")
    return body["result"]["structuredContent"]


@pytest.fixture
def deterministic_embedder(monkeypatch):
    """Mock BGE-M3 in BOTH modules and make ``encode_query`` deterministic.

    Dual-module patching is load-bearing: ``server/resources.py`` binds
    ``_get_model`` / ``_get_tokenizer`` by name at import time, so
    patching only ``query_encoder`` leaves ``Resources.startup`` loading
    real 1.5 GB weights (the notebook-retrieval-m2 lesson, encoded in
    ``tests/_corpus_helpers.patch_bge_m3_model``).
    """
    patch_bge_m3_model(monkeypatch)

    async def _fake_encode_query(text):
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        return v

    import server.handlers.search as search_mod
    import server.query_encoder as qe_mod

    monkeypatch.setattr(qe_mod, "encode_query", _fake_encode_query)
    monkeypatch.setattr(search_mod, "encode_query", _fake_encode_query)
    yield


class TestMidSessionIngest:
    def test_mid_session_ingest_over_the_mcp_wire(
        self, tmp_path, deterministic_embedder
    ) -> None:
        """THE acceptance criterion: ingest mid-session, and the NEXT
        query reflects the new corpus AND echoes the new corpus_version.

        End-to-end with nothing about the seam mocked — a real
        ``write_chunks`` bumps the LanceDB version and rewrites the
        marker between two real ``tools/call`` requests against a live
        lifespan.

        Pre-#207 this failed on BOTH assertions at once, which is what
        made the bug so quiet: the second query returned the pre-ingest
        rows *and* labelled them with the pre-ingest ``corpus_version``,
        so the response was internally consistent and externally wrong.

        This exercises the PULL path (a bare ``write_chunks``, as an
        out-of-band ``make ingest`` or a terminal
        ``tools/notebook_ingest.py`` run would produce — no in-process
        callback fires). ``corpus_freshness_interval_seconds=0`` removes
        the throttle so the test is deterministic rather than timing
        dependent.
        """
        lancedb_path = tmp_path / "lancedb"
        v1 = seed_corpus(lancedb_path, n=2)

        cfg = Config(
            lancedb_path=lancedb_path,
            cache_db_path=tmp_path / "cache" / "retrieval.db",
            corpus_freshness_interval_seconds=0.0,
        )
        reset_resources_for_tests()
        reset_metrics_for_tests()
        app = create_app(cfg)

        with TestClient(app) as client:
            sid = _initialize_session(client)

            before = _search(client, sid, "Riemann-Roch for stability")
            assert before["corpus_version"] == v1
            papers_before = {r["paper_id"] for r in before["results"]}
            assert papers_before == {"2307.00001", "2307.00002"}

            # --- the mid-session ingest ---------------------------------
            v2 = seed_corpus(lancedb_path, n=4)
            assert v2 != v1, "precondition: the ingest must bump the version"
            marker = json.loads(
                (lancedb_path / "corpus-version.json").read_text(
                    encoding="utf-8"
                )
            )
            assert marker["version"] == v2

            # --- the next query -----------------------------------------
            after = _search(client, sid, "Riemann-Roch for stability")

        assert after["corpus_version"] == v2, (
            f"the envelope still echoes corpus_version={after['corpus_version']} "
            f"after an ingest bumped the marker to {v2}. The served process "
            f"is reporting a stale version as truth — issue #207."
        )
        papers_after = {r["paper_id"] for r in after["results"]}
        assert {"2307.00003", "2307.00004"} <= papers_after, (
            f"the query did not reflect the new corpus: got {sorted(papers_after)}, "
            f"expected the two newly-ingested papers to be reachable. The "
            f"memoized pre-ingest table is still being served."
        )

    def test_ingest_completion_callback_rebinds_the_corpus(
        self, tmp_path, deterministic_embedder
    ) -> None:
        """The PUSH path — the ``/ui/`` Ingest button's actual mechanism.

        ``corpus_freshness_interval_seconds`` is set to an hour, so the
        request-path probe CANNOT be what notices the bump. Only the
        forced refresh inside ``on_ingest_complete`` can, which pins the
        push path independently of the pull path.
        """
        from server.resources import Resources

        lancedb_path = tmp_path / "lancedb"
        v1 = seed_corpus(lancedb_path, n=2)
        cfg = Config(
            lancedb_path=lancedb_path,
            cache_db_path=tmp_path / "cache" / "retrieval.db",
            corpus_freshness_interval_seconds=3600.0,
        )

        async def go():
            resources = await Resources.startup(cfg)
            try:
                served_before = resources.corpus_info.version
                count_before = resources.startup_chunk_count

                v2 = seed_corpus(lancedb_path, n=4)

                # A pull-path check must NOT be what fixes this.
                pulled = await resources.refresh_corpus_if_stale(cfg)
                served_mid = resources.corpus_info.version

                # The tracker's on_success_callback.
                await resources.on_ingest_complete(cfg, "some-notebook")
                return (
                    served_before,
                    count_before,
                    v2,
                    pulled,
                    served_mid,
                    resources.corpus_info.version,
                    resources.startup_chunk_count,
                )
            finally:
                await resources.shutdown()

        (
            served_before,
            count_before,
            v2,
            pulled,
            served_mid,
            served_after,
            count_after,
        ) = _run(go())

        assert served_before == v1
        assert count_before == 2
        assert pulled is False, "the throttle should have suppressed the pull"
        assert served_mid == v1, "the throttled pull path rebound anyway"
        assert served_after == v2, (
            "on_ingest_complete did not rebind the process corpus; the "
            "/ui/ Ingest button would leave the server serving the "
            "pre-ingest table (issue #207)"
        )
        assert count_after == 4, (
            "startup_chunk_count still reports the pre-ingest count, so "
            "/metrics and /readyz would describe the old corpus while the "
            "envelope reports the new corpus_version"
        )

    def test_rebind_failure_keeps_serving_the_previous_corpus(
        self, tmp_path, deterministic_embedder, monkeypatch
    ) -> None:
        """A rebind is a convergence step, not a request. If it fails,
        the process must keep serving what it has rather than ending up
        half-swapped or unwarm."""
        from server.resources import Resources

        lancedb_path = tmp_path / "lancedb"
        v1 = seed_corpus(lancedb_path, n=2)
        cfg = Config(
            lancedb_path=lancedb_path,
            cache_db_path=tmp_path / "cache" / "retrieval.db",
            corpus_freshness_interval_seconds=0.0,
        )

        async def go():
            resources = await Resources.startup(cfg)
            try:
                original_table = resources.chunks_table
                seed_corpus(lancedb_path, n=4)

                import server.resources as res_mod

                def boom(*a, **kw):
                    raise RuntimeError("simulated LanceDB open failure")

                monkeypatch.setattr(
                    res_mod, "open_chunks_table_with_fallback", boom
                )
                rebound = await resources.refresh_corpus_if_stale(cfg)
                return (
                    rebound,
                    resources.corpus_info.version,
                    resources.chunks_table is original_table,
                    resources.warm,
                )
            finally:
                await resources.shutdown()

        rebound, version, same_table, warm = _run(go())
        assert rebound is False
        assert version == v1, "a failed rebind published a partial swap"
        assert same_table is True
        assert warm is True, "a failed rebind must not take the server down"


# ===========================================================================
# Wiring — the ingest tracker actually calls the seam
# ===========================================================================


class TestIngestCallbackWiring:
    def test_lifespan_wires_the_tracker_to_on_ingest_complete(
        self, tmp_path, deterministic_embedder, monkeypatch
    ) -> None:
        """``server/main.py``'s ``_on_ingest_success`` closure must reach
        ``Resources.on_ingest_complete``.

        Before #207 it called ``late_bind``, which returns ``False``
        immediately once ``bootstrap_mode_active`` is ``False`` — so
        every ingest AFTER the first one invalidated nothing at all.
        This pins the wire rather than the behavior behind it, so a
        future refactor that drops the callback fails here.
        """
        from server.resources import Resources

        lancedb_path = tmp_path / "lancedb"
        seed_corpus(lancedb_path, n=2)
        cfg = Config(
            lancedb_path=lancedb_path,
            cache_db_path=tmp_path / "cache" / "retrieval.db",
        )
        calls: list[tuple[Path, str]] = []

        async def _record(self, config, slug):  # noqa: ANN001
            calls.append((config.lancedb_path, slug))

        monkeypatch.setattr(Resources, "on_ingest_complete", _record)

        reset_resources_for_tests()
        reset_metrics_for_tests()
        app = create_app(cfg)
        with TestClient(app) as client:
            _initialize_session(client)
            callback = app.state.ingest_tracker._on_success_callback
            assert callback is not None, (
                "the lifespan did not install an ingest on_success_callback"
            )
            _run(callback("freshly-ingested-notebook"))

        assert calls == [(lancedb_path, "freshly-ingested-notebook")]



# ===========================================================================
# The seam INVOKES the invalidation — issue #381
# ===========================================================================


def _bare_resources(tmp_path, cache):
    """A ``Resources`` with only what the invalidation seam touches.

    ``Resources.startup`` needs a real corpus; the seam does not. The
    docstring on the class permits direct construction in tests, and the
    six required fields are filled with inert values so the test exercises
    the seam rather than the startup path.
    """
    import asyncio as _asyncio

    from server.resources import Resources, Singleflight

    return Resources(
        config=Config(
            lancedb_path=tmp_path / "lancedb",
            cache_db_path=tmp_path / "cache" / "retrieval.db",
        ),
        corpus_info=None,
        chunks_table=None,
        embed_semaphore=_asyncio.Semaphore(1),
        rerank_semaphore=_asyncio.Semaphore(1),
        rerank_singleflight=Singleflight(),
        cache=cache,
    )


class TestInvalidationSeamIsWired:
    """``TestPurgeIsWired`` and
    ``test_invalidate_corpus_version_clears_tier2_and_tier3`` between them
    prove the purge is requested and the method works. Neither proves the
    freshness seam actually CALLS it.

    That gap is issue #381. Both call sites used to reach the method as
    ``getattr(cache, <name>, None)`` and skip a ``None``, so a rename, a
    typo or a deletion turned corpus invalidation into a no-op with no
    exception and no log line — while the direct-call test above stayed
    green, because it names the method itself. The 2026-08-02 rename
    survived on care, not on a mechanism.

    These exercise the seam and assert invocation, covering the wiring
    rather than the method.
    """

    def test_dropping_a_binding_invalidates_the_cache(self, tmp_path) -> None:
        calls: list[str] = []

        class _SpyCache:
            async def invalidate_corpus_version(self) -> int:
                calls.append("invalidate")
                return 0

        async def go():
            resources = _bare_resources(tmp_path, _SpyCache())
            # Seed a memoized binding: the seam only invalidates when it
            # actually drops something.
            resources._notebook_tables["nb"] = (object(), object())
            return await resources.invalidate_notebook_table("nb")

        dropped = _run(go())
        assert dropped is True
        assert calls == ["invalidate"], (
            "dropping a memoized notebook binding did not invalidate the "
            "semantic cache tiers, so a stale Tier-3 rerank memo survives "
            "the re-ingest (issues #207 / #338)"
        )

    def test_no_drop_means_no_invalidation(self, tmp_path) -> None:
        """The converse, so the test above cannot pass by invalidating
        unconditionally: nothing memoized means nothing to invalidate."""
        calls: list[str] = []

        class _SpyCache:
            async def invalidate_corpus_version(self) -> int:
                calls.append("invalidate")
                return 0

        async def go():
            resources = _bare_resources(tmp_path, _SpyCache())
            return await resources.invalidate_notebook_table("never-memoized")

        dropped = _run(go())
        assert dropped is False
        assert calls == []

    def test_a_missing_method_is_loud_not_skipped(self, tmp_path, caplog) -> None:
        """The #381 regression guard proper.

        A cache object without the method stands in for a future rename
        that misses these call sites. The seam must NOT silently skip it.
        It stays non-fatal — caching is performance, not correctness
        (``.claude/notes/07-multi-agent-caching.md``) — but it must leave
        a logged traceback rather than nothing at all.
        """
        import logging

        class _CacheMissingTheMethod:
            """What a renamed-away method looks like from the seam."""

        async def go():
            resources = _bare_resources(tmp_path, _CacheMissingTheMethod())
            resources._notebook_tables["nb"] = (object(), object())
            return await resources.invalidate_notebook_table("nb")

        with caplog.at_level(logging.ERROR):
            dropped = _run(go())

        # Non-fatal: the drop itself still succeeded.
        assert dropped is True
        # But LOUD: pre-#381 this produced no record whatsoever.
        assert any(
            r.levelno >= logging.ERROR and r.exc_info for r in caplog.records
        ), (
            "a cache missing invalidate_corpus_version produced no error "
            "record; the seam swallowed a programming error, which is "
            "exactly the #381 defect"
        )

    def test_no_cache_is_not_an_error(self, tmp_path, caplog) -> None:
        """``cache is None`` is a REAL runtime state (pre-startup, or a
        cache that failed to open), not a bug. It must stay silent — the
        #381 fix must not convert it into noise."""
        import logging

        async def go():
            resources = _bare_resources(tmp_path, None)
            resources._notebook_tables["nb"] = (object(), object())
            return await resources.invalidate_notebook_table("nb")

        with caplog.at_level(logging.ERROR):
            dropped = _run(go())

        assert dropped is True
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    def test_neither_call_site_uses_a_defaulting_getattr(self) -> None:
        """Structural guard. The defect was a code SHAPE, so pin the
        shape: no ``getattr`` on the cache with a default anywhere in
        resources.py. Comments are stripped first — the fix's own comment
        quotes the banned form to explain it, and matching that would be
        the guard failing on its own documentation."""
        import inspect
        import re

        import server.resources as resources_mod

        code = "\n".join(
            line for line in inspect.getsource(resources_mod).splitlines()
            if not line.lstrip().startswith("#")
        )
        offenders = re.findall(r"getattr\(\s*cache\s*,[^)]*\)", code)
        assert not offenders, (
            f"resources.py reaches the cache through a defaulting getattr "
            f"{offenders!r}. Issue #381: that form turns a renamed or "
            f"missing method into a silently skipped branch. Call it "
            f"directly and let the surrounding try/except log the failure."
        )
