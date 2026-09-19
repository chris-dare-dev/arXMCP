"""filter_echo on search_papers responses (stage2/arx-a1).

Finding 06 §3 item 2 (spike-5 caveat): every scoped response must
AFFIRM the notebook filter it honored. The bridge envelope's substrate
block carries ``filter_echo`` as a load-bearing field; before this
change the server never echoed the routing decision, so a consumer
could not distinguish "server honored my notebook filter" from "server
silently ignored it" (spike-5 observed filter_echo-null on all 38
scoped queries).

Contract under test:

- ``filter_echo`` is ALWAYS present on search_papers structured
  content: ``{"notebook": <slug>}`` when a per-call notebook routed the
  query, ``{"notebook": null}`` when the shared corpus served it.
  (Unlike ``filters_applied``, absence is NOT the no-filter signal —
  an affirmative null is the whole point.)
- Cached payloads stay caller-agnostic: the stamp runs post-cache on
  all three serve paths (Tier-1 hit, Tier-2 hit, miss), mirroring the
  ``filters_applied`` m2-rect-F2 discipline.
- The addition ships as the deliberate v17 TOOL_SCHEMA_VERSION event
  (schema file + EXPECTED_TOOL_SCHEMA_SHA256 re-pin, the v9
  ``filters_applied`` precedent); the BP1 prompt-cache hashes
  ({name, description} only) are untouched — enforced by
  tests/test_prompts.py + tests/test_server_tool_schema.py suite-wide.

Harness: the tests/test_search_filter.py fake-resources pattern
(fake LanceDB search-builder chain; no model loads).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pyarrow as pa
import pytest


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Unit tests — the injector itself
# ---------------------------------------------------------------------------


class TestInjectFilterEcho:
    def test_always_present_with_null_when_unscoped(self) -> None:
        from server.handlers.search import _inject_filter_echo

        out = _inject_filter_echo({"results": []}, None)
        assert out["filter_echo"] == {"notebook": None}

    def test_affirms_slug_when_scoped(self) -> None:
        from server.handlers.search import _inject_filter_echo

        out = _inject_filter_echo({"results": []}, "bridgeland-stability")
        assert out["filter_echo"] == {"notebook": "bridgeland-stability"}

    def test_never_mutates_input(self) -> None:
        from server.handlers.search import _inject_filter_echo

        payload: dict[str, Any] = {"results": []}
        out = _inject_filter_echo(payload, "alpha-nb")
        assert "filter_echo" not in payload
        assert out is not payload


# ---------------------------------------------------------------------------
# Handler integration (fake resources — the test_search_filter pattern)
# ---------------------------------------------------------------------------


def _empty_arrow_table() -> pa.Table:
    return pa.table({
        "chunk_id": pa.array([], type=pa.utf8()),
        "paper_id": pa.array([], type=pa.utf8()),
        "kind": pa.array([], type=pa.utf8()),
        "section_path": pa.array([], type=pa.list_(pa.utf8())),
        "body_text": pa.array([], type=pa.utf8()),
        "theorem_name": pa.array([], type=pa.utf8()),
        "theorem_label": pa.array([], type=pa.utf8()),
        "_distance": pa.array([], type=pa.float32()),
        "source_kind": pa.array([], type=pa.utf8()),
    })


class _FakeSearchBuilder:
    def where(self, predicate: str, **kwargs: Any) -> _FakeSearchBuilder:
        return self

    def limit(self, n: int) -> _FakeSearchBuilder:
        return self

    def to_arrow(self) -> pa.Table:
        return _empty_arrow_table()


class _FakeTable:
    def search(self, query_vec, vector_column_name=None) -> _FakeSearchBuilder:
        return _FakeSearchBuilder()


@pytest.fixture
def fake_resources(monkeypatch: pytest.MonkeyPatch):
    """Fake Resources via set_resources() — supports BOTH the shared
    path and per-call notebook routing (``notebook_table``)."""
    from server.tools import reset_resources_for_tests, set_resources

    class _FakeSemaphore:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _FakeConfig:
        query_embed_provider = "local"
        result_byte_cap = 256 * 1024

    class _FakeCorpusInfo:
        version = 101

    class _FakeNotebookCorpusInfo:
        version = 1690

    class _FakeResources:
        def __init__(self) -> None:
            self.embed_semaphore = _FakeSemaphore()
            self.config = _FakeConfig()
            self.degraded = None
            self.chunks_table = _FakeTable()
            self.corpus_info = _FakeCorpusInfo()
            self.notebook_table_calls: list[str] = []

        async def notebook_table(self, slug: str):
            self.notebook_table_calls.append(slug)
            return _FakeTable(), _FakeNotebookCorpusInfo()

    fake = _FakeResources()
    set_resources(fake)  # type: ignore[arg-type]
    monkeypatch.setattr("server.handlers.search.get_cache", lambda: None)

    async def _fake_encode(query: str):
        import numpy as np

        return np.zeros(1024, dtype=np.float32)

    monkeypatch.setattr("server.handlers.search.encode_query", _fake_encode)
    yield fake
    reset_resources_for_tests()


class TestFilterEchoHandlerIntegration:
    def test_unscoped_miss_path_echoes_null(self, fake_resources) -> None:
        from server.handlers.search import handle_search_papers

        result = _run(handle_search_papers(query="x", k=3))
        sc = result.structuredContent
        assert sc["filter_echo"] == {"notebook": None}
        # Unscoped → the shared corpus version, unchanged behavior.
        assert sc["corpus_version"] == 101

    def test_scoped_miss_path_affirms_notebook(self, fake_resources) -> None:
        from server.handlers.search import handle_search_papers

        result = _run(handle_search_papers(
            query="x", filters={"notebook": "alpha-nb"}, k=3,
        ))
        sc = result.structuredContent
        assert sc["filter_echo"] == {"notebook": "alpha-nb"}
        # The scoped call really routed (AC6 companion assertion).
        assert fake_resources.notebook_table_calls == ["alpha-nb"]
        assert sc["corpus_version"] == 1690

    def test_scoped_echo_coexists_with_filters_applied(
        self, fake_resources,
    ) -> None:
        """``filter_echo`` (routing affirmation) and ``filters_applied``
        (row-filter echo) are two non-overlapping views; a call using
        both gets both."""
        from server.handlers.search import handle_search_papers

        result = _run(handle_search_papers(
            query="x",
            filters={"notebook": "alpha-nb", "paper_id": "0705.3794"},
            k=3,
        ))
        sc = result.structuredContent
        assert sc["filter_echo"] == {"notebook": "alpha-nb"}
        assert sc["filters_applied"] == {"paper_id": ["0705.3794"]}


class TestSpike5Regression:
    """AC-A.3's named regression: reproduce the spike-5 condition —
    38 notebook-scoped queries, ZERO null echoes (the cutover spike
    observed filter_echo-null on all 38 scoped queries; finding 06
    §2.1.3 / §3 item 2). Mixed cache states: with the fake cache
    installed, repeated queries exercise miss + Tier-1-hit serve
    paths; every response must still affirm the notebook."""

    def test_38_scoped_queries_zero_null_echoes(
        self, fake_resources, monkeypatch,
    ) -> None:
        from server.handlers.search import handle_search_papers

        stored: dict[str, dict[str, Any]] = {}

        class _FakeCache:
            async def lookup_search(self, **kwargs):
                key = kwargs["query"]
                if key in stored:
                    return dict(stored[key]), "tier1"
                return None, None

            async def store_search(self, **kwargs):
                stored[kwargs["query"]] = kwargs["payload"]

        monkeypatch.setattr(
            "server.handlers.search.get_cache", lambda: _FakeCache()
        )

        echoes: list[Any] = []
        for i in range(38):
            # 19 distinct queries, each issued twice → first pass is
            # the miss path, second pass the Tier-1 hit path.
            result = _run(handle_search_papers(
                query=f"q-{i % 19}",
                filters={"notebook": "bridgeland-stability"},
                k=3,
            ))
            echoes.append(
                result.structuredContent.get("filter_echo", {}).get("notebook")
            )

        assert len(echoes) == 38
        null_echoes = [i for i, e in enumerate(echoes) if e is None]
        assert null_echoes == [], (
            f"spike-5 regression: {len(null_echoes)}/38 scoped queries "
            f"returned a null filter_echo (positions {null_echoes})"
        )
        assert set(echoes) == {"bridgeland-stability"}


class TestFilterEchoCachePaths:
    """Tier-1 hit path: the cached payload must stay caller-agnostic
    (no filter_echo stored); the hit re-stamps it."""

    def test_tier1_hit_restamps_filter_echo(
        self, fake_resources, monkeypatch,
    ) -> None:
        from server.handlers.search import handle_search_papers

        stored: dict[str, Any] = {}

        class _FakeCache:
            async def lookup_search(self, **kwargs):
                if stored:
                    return dict(stored["payload"]), "tier1"
                return None, None

            async def store_search(self, **kwargs):
                stored["payload"] = kwargs["payload"]

        monkeypatch.setattr(
            "server.handlers.search.get_cache", lambda: _FakeCache()
        )

        # Miss → populates the fake cache.
        first = _run(handle_search_papers(
            query="x", filters={"notebook": "alpha-nb"}, k=3,
        ))
        assert first.structuredContent["filter_echo"] == {"notebook": "alpha-nb"}
        # The STORED payload is caller-agnostic (strip-then-re-add
        # invariant — mirrors test_cached_payload_omits_filters_applied).
        assert "filter_echo" not in stored["payload"]

        # Tier-1 hit → re-stamped on the way out.
        second = _run(handle_search_papers(
            query="x", filters={"notebook": "alpha-nb"}, k=3,
        ))
        assert second.structuredContent["filter_echo"] == {
            "notebook": "alpha-nb"
        }
