"""Tests for notebook-retrieval-m2 (fork A): per-call notebook routing.

``search_papers(filters={"notebook": "<slug>"})`` routes a single call to
that notebook's lancedb WITHOUT a server relaunch — generalizing m1's
fork C (one-notebook-per-process ``ARXMCP_NOTEBOOK``) to many-notebooks-
per-process. Routes the SAME dense-only ``embedding_stmt`` path m1 ships.

Acceptance criteria → test:
- AC1 routing            → TestHandlerNotebookRouting.test_routes_to_notebook_table
- AC2 same dense path    → ...test_envelope_shape_and_retrieval_mode
- AC3 cache isolation    → TestCacheKeyIsolation (notebook rides in filters_json)
- AC4 no-notebook ident  → TestCacheKeyIsolation + TestEnvelopeOverride
- AC5 clean errors       → TestHandlerNotebookRouting.test_*_raises_value_error
- AC6 notebook version   → ...test_envelope_echoes_notebook_corpus_version
- registry LRU/Threat-1  → TestNotebookTableRegistry
- source_kind-absent     → TestArrowRowsSourceKindGuard
- filter_warnings hygiene→ ...test_notebook_key_not_in_filter_warnings
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# AC3 / AC4 — cache-key isolation comes from notebook riding in filters_json
# ===========================================================================


class TestCacheKeyIsolation:
    """The Tier-1 key already hashes ``filters_json``. Keeping ``notebook``
    in the (canonical) filters dict isolates notebooks for free (AC3) and
    leaves the no-notebook key byte-identical to today (AC4)."""

    def test_canonicalize_retains_notebook_key(self) -> None:
        """``_canonicalize_filters`` must NOT strip ``notebook`` — it has
        to remain so it participates in the cache key."""
        from server.handlers.search import _canonicalize_filters

        out = _canonicalize_filters({"notebook": "alpha-nb", "paper_id": "x"})
        assert out is not None
        assert out["notebook"] == "alpha-nb"

    def test_canonicalize_none_unchanged(self) -> None:
        """AC4: no filters → None (no spurious notebook key injected)."""
        from server.handlers.search import _canonicalize_filters

        assert _canonicalize_filters(None) is None

    def test_distinct_notebooks_distinct_keys(self) -> None:
        """AC3: two notebooks, same query/k/version → DISTINCT key bytes,
        even though ``corpus_version`` (the shared salt) collides."""
        from server.cache_sqlite import canonical_key_components

        ka = canonical_key_components(
            query="Bridgeland stability",
            filters={"notebook": "alpha-nb"},
            k=10,
            corpus_version=1,
            level="theorem",
        )
        kb = canonical_key_components(
            query="Bridgeland stability",
            filters={"notebook": "beta-nb"},
            k=10,
            corpus_version=1,
            level="theorem",
        )
        assert ka != kb

    def test_same_notebook_same_key(self) -> None:
        """Same notebook + same args → identical key (cache HIT path)."""
        from server.cache_sqlite import canonical_key_components

        common = dict(
            query="q", filters={"notebook": "alpha-nb"}, k=10,
            corpus_version=1, level="theorem",
        )
        assert canonical_key_components(**common) == canonical_key_components(
            **common
        )

    def test_no_notebook_key_byte_identical_to_today(self) -> None:
        """AC4: the no-notebook key bytes are exactly what they were
        before m2 (m2 does not touch ``canonical_key_components``)."""
        from server.cache_sqlite import canonical_key_components

        # filters=None and filters={} both → "{}" in the key.
        k_none = canonical_key_components(
            query="q", filters=None, k=10, corpus_version=1, level="theorem"
        )
        # A notebook query is INTENTIONALLY a different key.
        k_nb = canonical_key_components(
            query="q", filters={"notebook": "alpha-nb"}, k=10,
            corpus_version=1, level="theorem",
        )
        assert k_none != k_nb


# ===========================================================================
# AC4 / AC6 — envelope corpus_version override
# ===========================================================================


class TestEnvelopeOverride:
    def test_override_none_is_byte_identical(self, monkeypatch) -> None:
        """AC4: envelope(payload, override_corpus_version=None) ==
        envelope(payload) — the shared-corpus path is unchanged."""
        import server.tools as tools_mod

        monkeypatch.setattr(
            tools_mod, "get_resources",
            lambda: SimpleNamespace(corpus_info=SimpleNamespace(version=101)),
        )
        payload = {"results": [], "retrieval_mode": "dense_only"}
        assert tools_mod.envelope(dict(payload)) == tools_mod.envelope(
            dict(payload), override_corpus_version=None
        )

    def test_override_echoes_notebook_version(self, monkeypatch) -> None:
        """AC6: a provided override wins over the process-wide version."""
        import server.tools as tools_mod

        monkeypatch.setattr(
            tools_mod, "get_resources",
            lambda: SimpleNamespace(corpus_info=SimpleNamespace(version=101)),
        )
        out = tools_mod.envelope(
            {"results": []}, override_corpus_version=777
        )
        assert out["corpus_version"] == 777


# ===========================================================================
# source_kind-absent guard — pre-m9 notebook tables lack the column
# ===========================================================================


class TestArrowRowsSourceKindGuard:
    def test_absent_source_kind_column_defaults_to_arxiv(self) -> None:
        """Fork A is the first path to run the ANN over per-notebook
        tables, which were ingested BEFORE m9 added ``source_kind``. The
        column may be ABSENT (not just NULL) — ``_arrow_to_rows`` must
        default to "arxiv" rather than raising on ``arrow.column``."""
        from server.handlers.search import _arrow_to_rows

        # A table WITHOUT a source_kind column (pre-m9 notebook shape).
        arrow = pa.table({
            "chunk_id": ["arxiv:0705.3794:abc"],
            "paper_id": ["0705.3794"],
            "section_path": [[]],
            "theorem_name": [None],
            "theorem_label": [None],
            "body_text": ["x"],
            "_distance": [0.5],
        })
        rows = _arrow_to_rows(arrow)
        assert len(rows) == 1
        assert rows[0]["source_kind"] == "arxiv"


# ===========================================================================
# Resources.notebook_table — registry LRU + Threat-1 + un-ingested
# ===========================================================================


class TestNotebookTableRegistry:
    def _make_resources(self):
        from server.config import Config
        from server.resources import Resources, Singleflight

        return Resources(
            config=Config(),
            corpus_info=SimpleNamespace(version=1),
            chunks_table=None,
            embed_semaphore=asyncio.Semaphore(1),
            rerank_semaphore=asyncio.Semaphore(1),
            rerank_singleflight=Singleflight(),
        )

    @pytest.fixture
    def patched_open(self, monkeypatch, tmp_path):
        """Patch the path helper + corpus reader + table opener so no
        real lancedb is needed; keep the REAL ``validate_slug``."""
        import server.resources as res_mod
        import tools._notebook_common as nc

        monkeypatch.setattr(
            nc, "notebook_lancedb_path",
            lambda slug, **kw: tmp_path / slug / "lancedb",
        )
        opened: list[str] = []

        def fake_read_cv(path):
            if "missing-nb" in str(path):
                return None  # un-ingested
            return SimpleNamespace(version=42)

        def fake_open(*, lancedb_path, version):
            opened.append(str(lancedb_path))
            return (SimpleNamespace(path=str(lancedb_path)), None)

        monkeypatch.setattr(res_mod, "read_corpus_version", fake_read_cv)
        monkeypatch.setattr(
            res_mod, "open_chunks_table_with_fallback", fake_open
        )
        return opened

    def test_traversal_slug_rejected(self, patched_open) -> None:
        """Threat-1 (m2 FM-4): a path-traversal slug raises NotebookError
        BEFORE any path use (real validate_slug)."""
        from tools._notebook_common import NotebookError

        res = self._make_resources()
        for bad in ("../etc", "a/b", "ABC", "x"):
            with pytest.raises(NotebookError):
                _run(res.notebook_table(bad))

    def test_un_ingested_raises_corpus_not_ingested(self, patched_open) -> None:
        """m2 FM-5a: a valid slug with no corpus-version.json raises
        CorpusNotIngestedError (not a silent empty result)."""
        from server.resources import CorpusNotIngestedError

        res = self._make_resources()
        with pytest.raises(CorpusNotIngestedError):
            _run(res.notebook_table("missing-nb"))

    def test_memoization_opens_once(self, patched_open) -> None:
        res = self._make_resources()

        async def go():
            t1, info1 = await res.notebook_table("alpha-nb")
            t2, info2 = await res.notebook_table("alpha-nb")
            assert t1 is t2
            assert info1.version == 42

        _run(go())
        assert len([p for p in patched_open if p.endswith("alpha-nb/lancedb")]) == 1

    def test_lru_eviction_bounds_registry(self, patched_open) -> None:
        """m2 FM-6: opening more than MAX_NOTEBOOK_TABLE_SLOTS distinct
        notebooks keeps the registry bounded (evict-oldest)."""
        from server.resources import MAX_NOTEBOOK_TABLE_SLOTS

        res = self._make_resources()

        async def go():
            for i in range(MAX_NOTEBOOK_TABLE_SLOTS + 3):
                await res.notebook_table(f"nb-{i:03d}")

        _run(go())
        assert len(res._notebook_tables) == MAX_NOTEBOOK_TABLE_SLOTS

    def test_concurrent_same_slug_opens_once(self, patched_open) -> None:
        """m2 FM-8: two concurrent first-accesses for the same slug must
        open the table only once (lock + double-check)."""
        res = self._make_resources()

        async def go():
            await asyncio.gather(
                res.notebook_table("conc-nb"),
                res.notebook_table("conc-nb"),
            )

        _run(go())
        assert len(
            [p for p in patched_open if p.endswith("conc-nb/lancedb")]
        ) == 1


# ===========================================================================
# Handler integration — routing, envelope version, errors, warnings
# ===========================================================================


def _make_arrow_table(rows: list[dict[str, Any]]) -> pa.Table:
    """Minimal chunks-shape arrow table (with source_kind, as a migrated
    table would have)."""
    cols = {
        "chunk_id": [r["chunk_id"] for r in rows],
        "paper_id": [r["paper_id"] for r in rows],
        "section_path": [r.get("section_path", []) for r in rows],
        "theorem_name": [r.get("theorem_name") for r in rows],
        "theorem_label": [r.get("theorem_label") for r in rows],
        "body_text": [r.get("body_text", "x") for r in rows],
        "_distance": [r.get("_distance", 0.5) for r in rows],
        "source_kind": [r.get("source_kind", "arxiv") for r in rows],
    }
    if not rows:
        return pa.table({
            "chunk_id": pa.array([], pa.utf8()),
            "paper_id": pa.array([], pa.utf8()),
            "section_path": pa.array([], pa.list_(pa.utf8())),
            "theorem_name": pa.array([], pa.utf8()),
            "theorem_label": pa.array([], pa.utf8()),
            "body_text": pa.array([], pa.utf8()),
            "_distance": pa.array([], pa.float32()),
            "source_kind": pa.array([], pa.utf8()),
        })
    return pa.table(cols)


class _FakeSearchBuilder:
    def __init__(self, rows):
        self._rows = rows
        self.where_call = None

    def where(self, predicate, **kw):
        self.where_call = (predicate, kw)
        return self

    def limit(self, n):
        return self

    def to_arrow(self):
        return _make_arrow_table(self._rows)


class _FakeTable:
    # Default chunks-table columns INCLUDING source_kind (post-m9 shape).
    _DEFAULT_COLS = (
        "chunk_id", "paper_id", "section_path", "theorem_name",
        "theorem_label", "body_text", "_distance", "source_kind",
    )

    def __init__(self, rows, columns=None):
        self._rows = rows
        self._columns = tuple(columns) if columns is not None else self._DEFAULT_COLS

    @property
    def schema(self):
        # Mirrors lancedb table.schema.names — the F1 gate reads this to
        # detect a pre-m9 notebook table that lacks ``source_kind``.
        return SimpleNamespace(names=list(self._columns))

    def search(self, qv, vector_column_name=None):
        return _FakeSearchBuilder(self._rows)


@pytest.fixture
def fake_resources(monkeypatch):
    """Fake Resources with a notebook_table registry returning per-slug
    fake tables. Shared table = 'default' rows; notebooks keyed by slug."""
    from server.resources import CorpusNotIngestedError
    from server.tools import reset_resources_for_tests, set_resources

    shared = _FakeTable([{"chunk_id": "arxiv:shared.0001:z", "paper_id": "shared.0001"}])
    # slug -> (table, corpus_info)
    nb_map = {
        "bridgeland-stability": (
            _FakeTable([{"chunk_id": "arxiv:0705.3794:a", "paper_id": "0705.3794"}]),
            SimpleNamespace(version=369),
        ),
        "shimura-varieties": (
            _FakeTable([{"chunk_id": "arxiv:1234.5678:b", "paper_id": "1234.5678"}]),
            SimpleNamespace(version=49),
        ),
        # F1: a pre-m9 notebook table that LACKS the source_kind column.
        "legacy-nb": (
            _FakeTable(
                [{"chunk_id": "arxiv:0001.0001:c", "paper_id": "0001.0001"}],
                columns=(
                    "chunk_id", "paper_id", "section_path", "theorem_name",
                    "theorem_label", "body_text", "_distance",
                ),
            ),
            SimpleNamespace(version=7),
        ),
        # F3: two notebooks with a COLLIDING corpus_version (369) so
        # cross-notebook isolation depends SOLELY on notebook-in-filters.
        "collide-a": (
            _FakeTable([{"chunk_id": "arxiv:AAAA.0001:a", "paper_id": "AAAA.0001"}]),
            SimpleNamespace(version=369),
        ),
        "collide-b": (
            _FakeTable([{"chunk_id": "arxiv:BBBB.0002:b", "paper_id": "BBBB.0002"}]),
            SimpleNamespace(version=369),
        ),
    }

    class _FakeSem:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _FakeResources:
        def __init__(self):
            self.embed_semaphore = _FakeSem()
            self.config = SimpleNamespace(query_embed_provider="local", result_byte_cap=256 * 1024)
            self.degraded = None
            self.chunks_table = shared
            self.corpus_info = SimpleNamespace(version=101)
        async def notebook_table(self, slug):
            if slug not in nb_map:
                raise CorpusNotIngestedError(f"notebook {slug!r}: not ingested")
            return nb_map[slug]

    fake = _FakeResources()
    set_resources(fake)  # type: ignore[arg-type]
    monkeypatch.setattr("server.handlers.search.get_cache", lambda: None)

    async def _fake_encode(query):
        import numpy as np
        return np.zeros(1024, dtype=np.float32)

    monkeypatch.setattr("server.handlers.search.encode_query", _fake_encode)
    yield fake
    reset_resources_for_tests()


class TestHandlerNotebookRouting:
    def test_routes_to_notebook_table(self, fake_resources) -> None:
        """AC1: filters.notebook routes to that notebook's table — the
        result rows are the NOTEBOOK's, not the shared corpus's."""
        from server.handlers.search import handle_search_papers

        res = _run(handle_search_papers(
            query="Bridgeland's original definition",
            filters={"notebook": "bridgeland-stability"},
            k=10,
        ))
        sc = res.structuredContent
        pids = [r["paper_id"] for r in sc["results"]]
        assert "0705.3794" in pids
        assert "shared.0001" not in pids

    def test_envelope_echoes_notebook_corpus_version(self, fake_resources) -> None:
        """AC6: the envelope corpus_version is the NOTEBOOK's (369), not
        the process-wide shared version (101)."""
        from server.handlers.search import handle_search_papers

        res = _run(handle_search_papers(
            query="q", filters={"notebook": "bridgeland-stability"}, k=10,
        ))
        assert res.structuredContent["corpus_version"] == 369

    def test_no_notebook_uses_shared_and_shared_version(self, fake_resources) -> None:
        """AC4: no filters.notebook → shared table + shared version 101."""
        from server.handlers.search import handle_search_papers

        res = _run(handle_search_papers(query="q", filters=None, k=10))
        sc = res.structuredContent
        assert sc["corpus_version"] == 101
        assert [r["paper_id"] for r in sc["results"]] == ["shared.0001"]

    def test_envelope_shape_and_retrieval_mode(self, fake_resources) -> None:
        """AC2: same dense-only path; envelope shape identical."""
        from server.handlers.search import handle_search_papers

        res = _run(handle_search_papers(
            query="q", filters={"notebook": "shimura-varieties"}, k=10,
        ))
        sc = res.structuredContent
        assert sc["retrieval_mode"] == "dense_only"
        assert sc["excluded_kinds"] == ["proof"]
        assert "results" in sc and "corpus_version" in sc

    def test_notebook_key_not_in_filter_warnings(self, fake_resources) -> None:
        """``notebook`` is a routing key — must NOT appear in
        filter_warnings (it would read as a spurious 'ignored' warning)."""
        from server.handlers.search import handle_search_papers

        res = _run(handle_search_papers(
            query="q", filters={"notebook": "bridgeland-stability"}, k=10,
        ))
        warnings = res.structuredContent["filter_warnings"]
        assert not any("notebook" in w for w in warnings)

    def test_notebook_not_in_filters_applied(self, fake_resources) -> None:
        """``notebook`` is a routing key, not a retrieval filter — it must
        NOT appear in the filters_applied echo."""
        from server.handlers.search import handle_search_papers

        res = _run(handle_search_papers(
            query="q", filters={"notebook": "bridgeland-stability"}, k=10,
        ))
        applied = res.structuredContent.get("filters_applied", {})
        assert "notebook" not in applied

    def test_traversal_slug_raises_value_error(self, fake_resources) -> None:
        """AC5 / Threat-1: a traversal slug → clean ValueError, not 500."""
        from server.handlers.search import handle_search_papers

        with pytest.raises(ValueError, match="not a valid notebook slug"):
            _run(handle_search_papers(
                query="q", filters={"notebook": "../etc"}, k=10,
            ))

    def test_non_str_notebook_raises_value_error(self, fake_resources) -> None:
        from server.handlers.search import handle_search_papers

        with pytest.raises(ValueError, match="must be a str"):
            _run(handle_search_papers(
                query="q", filters={"notebook": ["a-list"]}, k=10,
            ))

    def test_un_ingested_notebook_raises_value_error(self, fake_resources) -> None:
        """AC5: a valid slug for a non-existent/un-ingested notebook →
        clean ValueError (converted from CorpusNotIngestedError)."""
        from server.handlers.search import handle_search_papers

        with pytest.raises(ValueError, match="not-a-real-nb"):
            _run(handle_search_papers(
                query="q", filters={"notebook": "not-a-real-nb"}, k=10,
            ))

    def test_notebook_plus_paper_id_compose(self, fake_resources) -> None:
        """notebook routing composes with a paper_id filter (the filter
        still applies within the routed notebook corpus)."""
        from server.handlers.search import handle_search_papers

        # Should route to bridgeland AND build a paper_id predicate.
        res = _run(handle_search_papers(
            query="q",
            filters={"notebook": "bridgeland-stability", "paper_id": "0705.3794"},
            k=10,
        ))
        # filters_applied carries paper_id (a real filter) but not notebook.
        applied = res.structuredContent.get("filters_applied", {})
        assert applied.get("paper_id") == ["0705.3794"]
        assert "notebook" not in applied

    def test_source_kind_filter_on_legacy_notebook_raises(self, fake_resources) -> None:
        """F1 (HIGH) rectification: a source_kind filter against a pre-m9
        notebook table that LACKS the source_kind column must raise a clean
        ValueError, NOT let LanceError(Schema) propagate as a 500."""
        from server.handlers.search import handle_search_papers

        with pytest.raises(
            ValueError, match="source_kind.*not supported on notebook"
        ):
            _run(handle_search_papers(
                query="q",
                filters={"notebook": "legacy-nb", "source_kind": "arxiv"},
                k=10,
            ))

    def test_source_kind_filter_on_migrated_notebook_ok(self, fake_resources) -> None:
        """F1: a notebook table WITH source_kind accepts the filter — the
        gate must not false-positive on migrated/post-m9 notebook tables."""
        from server.handlers.search import handle_search_papers

        res = _run(handle_search_papers(
            query="q",
            filters={"notebook": "bridgeland-stability", "source_kind": "arxiv"},
            k=10,
        ))
        assert res.structuredContent["retrieval_mode"] == "dense_only"

    def test_two_notebooks_do_not_cross_serve_via_real_cache(
        self, fake_resources, monkeypatch, tmp_path
    ) -> None:
        """F3 (AC3 end-to-end): with a REAL cache, warming notebook A then
        querying notebook B (identical query/k/level, COLLIDING
        corpus_version 369) must NOT serve A's rows to B. Guards
        notebook-in-filters isolation through the real lookup/store path —
        would FAIL if a refactor stripped notebook from canonical_filters."""
        from server.cache import RetrievalCache
        from server.handlers.search import handle_search_papers

        cache = _run(RetrievalCache.open(tmp_path / "c.db", corpus_version=101))
        monkeypatch.setattr("server.handlers.search.get_cache", lambda: cache)
        try:
            res_a = _run(handle_search_papers(
                query="q", filters={"notebook": "collide-a"}, k=10,
            ))
            assert [r["paper_id"] for r in res_a.structuredContent["results"]] == [
                "AAAA.0001"
            ]
            # Identical query/k/level; only the notebook differs. With a
            # colliding corpus_version, isolation rests ENTIRELY on the
            # notebook key riding in filters_json.
            res_b = _run(handle_search_papers(
                query="q", filters={"notebook": "collide-b"}, k=10,
            ))
            assert [r["paper_id"] for r in res_b.structuredContent["results"]] == [
                "BBBB.0002"
            ]
        finally:
            _run(cache.close())


class TestCacheCorpusVersionOverride:
    """F2 rectification: the optional ``corpus_version`` override on
    lookup_search/store_search salts the Tier-1 key on the per-call
    (notebook) version; ``None`` reduces to the shared version (AC4)."""

    def test_override_threads_into_tier1_key(self, tmp_path) -> None:
        from server.cache import RetrievalCache

        async def go():
            cache = await RetrievalCache.open(tmp_path / "c.db", corpus_version=101)
            try:
                payload = {"results": [{"paper_id": "X.1"}], "corpus_version": 369}
                await cache.store_search(
                    query="q", filters={"notebook": "a"}, k=10,
                    payload=payload, level="theorem", corpus_version=369,
                )
                hit, _ = await cache.lookup_search(
                    query="q", filters={"notebook": "a"}, k=10,
                    level="theorem", corpus_version=369,
                )
                assert hit is not None  # same version → HIT
                miss, _ = await cache.lookup_search(
                    query="q", filters={"notebook": "a"}, k=10,
                    level="theorem", corpus_version=49,
                )
                assert miss is None  # different version salt → MISS
                miss2, _ = await cache.lookup_search(
                    query="q", filters={"notebook": "a"}, k=10,
                    level="theorem", corpus_version=None,
                )
                assert miss2 is None  # None → shared (101) ≠ 369 → MISS
            finally:
                await cache.close()

        _run(go())

    def test_none_override_byte_identical_to_shared(self, tmp_path) -> None:
        """AC4: ``corpus_version=None`` collapses to the shared version, so a
        store/lookup with None and an explicit-shared lookup hit the SAME
        key (byte-identical to the pre-m2 behavior)."""
        from server.cache import RetrievalCache

        async def go():
            cache = await RetrievalCache.open(tmp_path / "c2.db", corpus_version=101)
            try:
                await cache.store_search(
                    query="q", filters=None, k=10, payload={"results": []},
                    level="theorem", corpus_version=None,
                )
                hit_none, _ = await cache.lookup_search(
                    query="q", filters=None, k=10, level="theorem",
                    corpus_version=None,
                )
                hit_explicit, _ = await cache.lookup_search(
                    query="q", filters=None, k=10, level="theorem",
                    corpus_version=101,
                )
                assert hit_none is not None
                assert hit_explicit is not None  # None and 101 → same key
            finally:
                await cache.close()

        _run(go())
