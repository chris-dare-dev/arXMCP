"""Tier-2 scope-key tests — GitHub issue #204.

``server/cache.py::_filter_fingerprint`` fed sentinel values for
``query``, ``k`` and ``corpus_version`` into ``canonical_key_components``
and justified them with: *"the query and k are already disambiguated by
the embedding."* The first half is true; the second is false. **The
embedding is a function of the query TEXT only.** So
``search_papers(Q, k=5)`` and ``search_papers(Q, k=50)`` produced the
same embedding hash and the same fingerprint, collided in one ring-buffer
slot, and the second call was served the five-row payload verbatim — the
handler returned ``structured["results"]`` with no re-slice and no
refetch. Silent under-retrieval on the entry-point tool.

Separately, the slot was keyed on ``sha256(embedding)`` alone, so a
cosine-0.97 NEIGHBOUR's rows came back shaped byte-identically to an
exact hit, with nothing on the wire to tell them apart.

Coverage map (issue acceptance criteria → test):

  AC                                                    Test class
  ────────────────────────────────────────────────────────────────
  k participates / payload re-sliced                    TestOrdinalKRule
  k=5 then k=50 returns 50 rows                         TestHandlerKRegression
  Embedder identity participates in the key             TestEmbedderIdentityAxis
  (the comment fix is prose — read _tier2_scope_fingerprint)

Plus the neighbour-indistinguishability half of the report:

  Approximate vs exact hit is on the wire               TestCacheMatchAxis
  corpus_version is no longer a Tier-2 sentinel         TestCorpusVersionAxis
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

from server.cache import (
    EMBEDDING_DIM,
    RetrievalCache,
    reset_cache_for_tests,
    set_cache,
)
from server.cache_sqlite import derive_tier1_key
from server.metrics import TIER_2, reset_cache_metrics_for_tests
from server.query_encoder import embedder_identity


def _run(coro):
    """Project pattern — async tests use asyncio.run(); pytest-asyncio
    is not configured."""
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_cache_state():
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()
    yield
    reset_cache_for_tests()
    reset_cache_metrics_for_tests()


def _unit(seed: int) -> np.ndarray:
    """Deterministic L2-normalized BGE-M3-shaped vector."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    v /= float(np.linalg.norm(v))
    return v


def _near(base: np.ndarray, *, cosine: float, seed: int) -> np.ndarray:
    """Unit vector at approximately ``cosine`` from ``base``."""
    rng = np.random.default_rng(seed)
    perturb = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    perturb -= np.dot(perturb, base) * base
    perturb /= float(np.linalg.norm(perturb))
    new = cosine * base + np.sqrt(max(0.0, 1.0 - cosine**2)) * perturb
    new /= float(np.linalg.norm(new))
    return new.astype(np.float32)


def _payload(n_rows: int, label: str = "p") -> dict[str, Any]:
    """Synthetic search_papers payload carrying ``n_rows`` result rows."""
    return {
        "embed_model": "bge-m3",
        "results": [
            {"chunk_id": f"arxiv:demo:{label}-{i:03d}", "score": 1.0 - i / 100}
            for i in range(n_rows)
        ],
        "retrieval_mode": "dense_only",
    }


# ===========================================================================
# AC — k participates: an entry answers only requests it is wide enough for
# ===========================================================================


class TestOrdinalKRule:
    """``k`` is enforced ordinally on Tier-2: an entry built for ``k``
    rows can answer any request for at most ``k`` (the caller slices) and
    NO request for more (the extra rows were never retrieved)."""

    def test_narrow_entry_does_not_serve_wider_request(self, tmp_path):
        """THE BUG. Store a k=5 payload, then ask for k=50 with the same
        embedding, filters and level. Pre-#204 this hit and returned five
        rows. It must now MISS so the pipeline re-runs."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=42)
            try:
                emb = _unit(seed=1)
                await cache.store_search(
                    query="Q", filters=None, k=5,
                    payload=_payload(5), query_embedding=emb,
                )
                payload, hit_tier, match = await cache.lookup_search(
                    query="different text", filters=None, k=50,
                    query_embedding=emb,
                )
                assert payload is None, (
                    "a k=5 entry must not answer a k=50 request — the 45 "
                    "missing rows were never retrieved, so serving it is "
                    "silent under-retrieval, not a cache hit"
                )
                assert hit_tier == ""
                assert match is None
            finally:
                await cache.close()

        _run(go())

    def test_wide_entry_serves_narrower_request(self, tmp_path):
        """The reuse the ordinal rule buys: a k=50 entry answers a k=5
        request, reporting its own width so the caller can slice."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=42)
            try:
                emb = _unit(seed=1)
                await cache.store_search(
                    query="Q", filters=None, k=50,
                    payload=_payload(50), query_embedding=emb,
                )
                payload, hit_tier, match = await cache.lookup_search(
                    query="different text", filters=None, k=5,
                    query_embedding=emb,
                )
                assert hit_tier == TIER_2
                assert match is not None
                assert match.cached_k == 50
                # The CACHED payload keeps all 50 — slicing is the
                # caller's job and must not mutate the entry.
                assert len(payload["results"]) == 50
            finally:
                await cache.close()

        _run(go())

    def test_equal_k_still_hits(self, tmp_path):
        """Regression guard on the boundary: entry.k == requested k is a
        hit, not an off-by-one miss."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=42)
            try:
                emb = _unit(seed=1)
                await cache.store_search(
                    query="Q", filters=None, k=10,
                    payload=_payload(10), query_embedding=emb,
                )
                _payload_out, hit_tier, match = await cache.lookup_search(
                    query="other", filters=None, k=10, query_embedding=emb,
                )
                assert hit_tier == TIER_2
                assert match is not None and match.cached_k == 10
            finally:
                await cache.close()

        _run(go())

    def test_too_narrow_top_1_does_not_mask_wide_enough_top_2(self, tmp_path):
        """The k test must ``continue`` the top-K scan, not abort it —
        the same property F9 established for the scope-fingerprint test.
        Nearest neighbour is too narrow; the second-nearest is wide
        enough and must be found."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=42)
            try:
                q = _unit(seed=1)
                near = _near(q, cosine=0.995, seed=2)   # closest, k=5
                far = _near(q, cosine=0.975, seed=3)    # farther,  k=50
                await cache.store_search(
                    query="A", filters=None, k=5,
                    payload=_payload(5, "narrow"), query_embedding=near,
                )
                await cache.store_search(
                    query="B", filters=None, k=50,
                    payload=_payload(50, "wide"), query_embedding=far,
                )
                payload, hit_tier, match = await cache.lookup_search(
                    query="C", filters=None, k=50, query_embedding=q,
                )
                assert hit_tier == TIER_2
                assert payload == _payload(50, "wide")
                assert match is not None and match.cached_k == 50
            finally:
                await cache.close()

        _run(go())


# ===========================================================================
# AC — the embedder that produced a ranking participates in the key
# ===========================================================================


class TestEmbedderIdentityAxis:
    """A ranking produced by the local fallback while a hosted provider
    was down must not be reachable from a request the hosted provider
    answered — ``_restamp_degraded`` would strip its degraded marker and
    re-serve it as undegraded."""

    def test_identity_token_shapes(self):
        local = embedder_identity("local")
        hosted = embedder_identity("voyage")
        fell_back = embedder_identity("voyage", used_fallback=True)
        assert local.startswith("local:bge-m3@")
        assert hosted == "hosted:voyage"
        # A fallback ran BGE-M3, so it IS the local embedder — same
        # rankings, therefore the same identity. What must not happen is
        # sharing with the HOSTED identity.
        assert fell_back == local
        assert fell_back != hosted

    def test_tier1_key_separates_embedders(self):
        a = derive_tier1_key(
            "q", None, 10, 7, level="theorem", embedder_id="hosted:voyage")
        b = derive_tier1_key(
            "q", None, 10, 7, level="theorem", embedder_id="local:bge-m3@abc")
        omitted = derive_tier1_key("q", None, 10, 7, level="theorem")
        assert a != b
        # An omitted embedder is a distinct value, never a wildcard.
        assert omitted not in {a, b}

    def test_tier2_hosted_entry_unreachable_from_fallback(self, tmp_path):
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=42)
            try:
                emb = _unit(seed=1)
                await cache.store_search(
                    query="Q", filters=None, k=10,
                    payload=_payload(10, "hosted"), query_embedding=emb,
                    embedder_id=embedder_identity("voyage"),
                )
                payload, hit_tier, _match = await cache.lookup_search(
                    query="Q2", filters=None, k=10, query_embedding=emb,
                    embedder_id=embedder_identity("voyage", used_fallback=True),
                )
                assert payload is None, (
                    "a hosted-provider ranking must not answer a request "
                    "the local fallback served, or the two rankings become "
                    "indistinguishable on the wire"
                )
                assert hit_tier == ""
            finally:
                await cache.close()

        _run(go())

    def test_tier2_fallback_entry_unreachable_from_healthy_hosted(self, tmp_path):
        """The direction the issue names: the degraded ranking must not
        be re-served to a healthy request."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=42)
            try:
                emb = _unit(seed=1)
                await cache.store_search(
                    query="Q", filters=None, k=10,
                    payload=_payload(10, "degraded"), query_embedding=emb,
                    embedder_id=embedder_identity("voyage", used_fallback=True),
                )
                payload, _hit, _match = await cache.lookup_search(
                    query="Q2", filters=None, k=10, query_embedding=emb,
                    embedder_id=embedder_identity("voyage"),
                )
                assert payload is None
            finally:
                await cache.close()

        _run(go())

    def test_same_embedder_still_hits(self, tmp_path):
        """The axis must not break normal reuse."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=42)
            try:
                emb = _unit(seed=1)
                eid = embedder_identity("local")
                await cache.store_search(
                    query="Q", filters=None, k=10, payload=_payload(10),
                    query_embedding=emb, embedder_id=eid,
                )
                payload, hit_tier, _m = await cache.lookup_search(
                    query="Q2", filters=None, k=10, query_embedding=emb,
                    embedder_id=eid,
                )
                assert hit_tier == TIER_2
                assert payload == _payload(10)
            finally:
                await cache.close()

        _run(go())


# ===========================================================================
# corpus_version was the third sentinel in the same comment
# ===========================================================================


class TestCorpusVersionAxis:
    """``corpus_version`` was fed as ``0`` alongside ``k``. Two notebooks
    pinned to different corpus versions, or an in-process corpus bump,
    must not share a Tier-2 slot."""

    def test_distinct_corpus_versions_do_not_share_a_slot(self, tmp_path):
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=101)
            try:
                emb = _unit(seed=1)
                await cache.store_search(
                    query="Q", filters=None, k=10, payload=_payload(10),
                    query_embedding=emb, corpus_version=369,
                )
                payload, _hit, _m = await cache.lookup_search(
                    query="Q2", filters=None, k=10, query_embedding=emb,
                    corpus_version=49,
                )
                assert payload is None
            finally:
                await cache.close()

        _run(go())

    def test_none_resolves_to_the_shared_version_on_both_sides(self, tmp_path):
        """``corpus_version=None`` must resolve identically at store and
        lookup, or Tier-2 would never hit on the common path."""
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=101)
            try:
                emb = _unit(seed=1)
                await cache.store_search(
                    query="Q", filters=None, k=10, payload=_payload(10),
                    query_embedding=emb, corpus_version=None,
                )
                hit_none, tier_a, _m1 = await cache.lookup_search(
                    query="Q2", filters=None, k=10, query_embedding=emb,
                    corpus_version=None,
                )
                hit_explicit, tier_b, _m2 = await cache.lookup_search(
                    query="Q3", filters=None, k=10, query_embedding=emb,
                    corpus_version=101,
                )
                assert tier_a == TIER_2 and hit_none is not None
                assert tier_b == TIER_2 and hit_explicit is not None
            finally:
                await cache.close()

        _run(go())


# ===========================================================================
# The neighbour-indistinguishability half of the report
# ===========================================================================


class TestCacheMatchAxis:
    """A cosine-0.97 neighbour's rows and an exact hit's rows must be
    distinguishable. ``exact_embedding`` is decided by comparing
    ring-buffer slot keys — byte equality, no float epsilon."""

    def test_neighbour_is_flagged_approximate(self, tmp_path):
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=42)
            try:
                base = _unit(seed=42)
                near = _near(base, cosine=0.98, seed=99)
                await cache.store_search(
                    query="original", filters=None, k=10,
                    payload=_payload(10), query_embedding=base,
                )
                _p, hit_tier, match = await cache.lookup_search(
                    query="paraphrase", filters=None, k=10,
                    query_embedding=near,
                )
                assert hit_tier == TIER_2
                assert match is not None
                assert match.exact_embedding is False
                assert abs(match.cosine - 0.98) < 1e-2
            finally:
                await cache.close()

        _run(go())

    def test_same_embedding_is_flagged_exact(self, tmp_path):
        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=42)
            try:
                emb = _unit(seed=42)
                await cache.store_search(
                    query="original", filters=None, k=10,
                    payload=_payload(10), query_embedding=emb,
                )
                # Different query TEXT (so Tier-1 misses) but the same
                # embedding — the ring-buffer dedup slot.
                _p, hit_tier, match = await cache.lookup_search(
                    query="a different string", filters=None, k=10,
                    query_embedding=emb,
                )
                assert hit_tier == TIER_2
                assert match is not None
                assert match.exact_embedding is True
                assert abs(match.cosine - 1.0) < 1e-4
            finally:
                await cache.close()

        _run(go())


# ===========================================================================
# Handler-level regression — the shape the issue reported
# ===========================================================================


_CORPUS_ROWS = [
    {
        "chunk_id": f"arxiv:2604.{i:05d}:{i:016x}",
        "paper_id": f"2604.{i:05d}",
        "body_text": f"body of chunk {i}",
        "_distance": 0.01 * i,
    }
    for i in range(60)
]


def _arrow(rows: list[dict[str, Any]]) -> pa.Table:
    return pa.table({
        "chunk_id": [r["chunk_id"] for r in rows],
        "paper_id": [r["paper_id"] for r in rows],
        "section_path": [[] for _ in rows],
        "theorem_name": [None for _ in rows],
        "theorem_label": [None for _ in rows],
        "body_text": [r["body_text"] for r in rows],
        "_distance": [r["_distance"] for r in rows],
        "source_kind": ["arxiv" for _ in rows],
    })


class _FakeSearchBuilder:
    def __init__(self, rows):
        self._rows = rows

    def where(self, predicate, **kw):
        return self

    def limit(self, n):
        return self

    def to_arrow(self):
        return _arrow(self._rows)


class _FakeTable:
    @property
    def schema(self):
        return SimpleNamespace(names=[
            "chunk_id", "paper_id", "section_path", "theorem_name",
            "theorem_label", "body_text", "_distance", "source_kind",
        ])

    def search(self, qv, vector_column_name=None):
        return _FakeSearchBuilder(_CORPUS_ROWS)


#: Query text → embedding. The production encoder is a function of the
#: query text alone; this stub preserves exactly that property, which is
#: the whole premise of the bug.
_QUERY_VECTORS = {
    "stability conditions": _unit(seed=7),
}
_QUERY_VECTORS["stability conditions, restated"] = _near(
    _QUERY_VECTORS["stability conditions"], cosine=0.985, seed=8,
)


@pytest.fixture
def handler_env(monkeypatch, tmp_path):
    """Fake Resources + a REAL RetrievalCache, so ``handle_search_papers``
    exercises the production cache code rather than a stand-in."""
    from server.tools import reset_resources_for_tests, set_resources

    class _FakeSem:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _FakeResources:
        def __init__(self):
            self.embed_semaphore = _FakeSem()
            self.config = SimpleNamespace(
                query_embed_provider="local", result_byte_cap=256 * 1024,
            )
            self.degraded = None
            self.chunks_table = _FakeTable()
            self.corpus_info = SimpleNamespace(version=101)

    set_resources(_FakeResources())  # type: ignore[arg-type]

    async def _fake_encode(query: str):
        return _QUERY_VECTORS[query]

    monkeypatch.setattr("server.handlers.search.encode_query", _fake_encode)

    cache = _run(RetrievalCache.open(tmp_path / "handler.db", corpus_version=101))
    set_cache(cache)
    yield cache
    _run(cache.close())
    reset_resources_for_tests()


def _search(**kwargs):
    from server.handlers.search import handle_search_papers

    return _run(handle_search_papers(**kwargs)).structuredContent


class TestHandlerKRegression:
    """The issue's acceptance test, at the layer where the bug bit."""

    def test_k5_then_k50_returns_50_rows(self, handler_env):
        """``search_papers(Q, k=5)`` followed by ``search_papers(Q, k=50)``
        must return 50 rows. Pre-#204 the second call missed Tier-1 (whose
        key does include k), hit Tier-2 (whose key did not), and was
        handed the five-row payload verbatim."""
        first = _search(query="stability conditions", k=5)
        assert len(first["results"]) == 5

        second = _search(query="stability conditions", k=50)
        assert len(second["results"]) == 50, (
            f"asked for 50 candidates, got {len(second['results'])} — the "
            f"Tier-2 slot served the k=5 payload"
        )
        # And the rows are the real top-50, not five rows padded.
        assert len({r["chunk_id"] for r in second["results"]}) == 50

    def test_k50_then_k5_reslices_to_5(self, handler_env):
        """The reuse direction: a wider entry answers a narrower request,
        sliced to the requested k — never handed back over-wide."""
        first = _search(query="stability conditions", k=50)
        assert len(first["results"]) == 50

        second = _search(query="stability conditions", k=5)
        assert len(second["results"]) == 5
        # Served from Tier-2 (Tier-1's key includes k, so it missed) and
        # flagged as this query's own embedding, not a neighbour's.
        assert second["cache_match"]["kind"] == "exact_query_embedding"

    def test_repeat_identical_call_is_a_tier1_hit_with_no_marker(self, handler_env):
        """Absence of ``cache_match`` means 'these rows are about YOUR
        query'. An exact Tier-1 memo qualifies; it must not be marked."""
        first = _search(query="stability conditions", k=10)
        assert "cache_match" not in first  # fresh pipeline run
        second = _search(query="stability conditions", k=10)
        assert second["results"] == first["results"]
        assert "cache_match" not in second

    def test_neighbour_hit_is_marked_approximate(self, handler_env):
        """A cosine-0.985 paraphrase is served the original's rows — a
        legitimate cache hit, but the agent must be able to see that the
        rows answer a different question."""
        _search(query="stability conditions", k=10)
        near = _search(query="stability conditions, restated", k=10)
        assert near["cache_match"]["kind"] == "approximate_neighbor"
        assert 0.97 <= near["cache_match"]["cosine"] <= 1.0

    def test_cache_match_validates_against_the_result_schema(self, handler_env):
        """The envelope schema is ``additionalProperties: false``, so an
        undeclared field would be a silent contract break."""
        import json
        from pathlib import Path

        import jsonschema

        schema = json.loads(
            Path("server/schemas/search_papers_result.json").read_text(
                encoding="utf-8",
            )
        )
        _search(query="stability conditions", k=10)
        near = _search(query="stability conditions, restated", k=10)
        assert "cache_match" in near
        jsonschema.validate(instance=near, schema=schema)
