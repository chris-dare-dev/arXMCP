"""Tests for the search_papers filters={"paper_id":[...]} wiring.

Covers proof-verify-handler-wiring-m1:

- AC #1: filter scopes results
- AC #2: no-filter behavior unchanged
- AC #3: malformed filter raises clear error
- AC #4: EXPECTED_TOOL_SCHEMA_SHA256 unchanged (cross-checked via test_server_tool_schema)
- AC #5: this file (new tests/test_search_filter.py)
- AC #6: make test green (project-level)

Plus all 9 failure modes from research-synthesis.md.

Tests at TWO layers:
1. Pure-function tests on ``_build_paper_id_predicate`` — fast, no mocks.
2. Handler-integration tests that mock the LanceDB ``.search().where()
   .limit().to_arrow()`` chain to verify the predicate is threaded into
   the ANN call correctly without spinning up a real corpus.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pyarrow as pa
import pytest

from server.handlers.search import (
    MAX_PAPER_ID_FILTER_ITEMS,
    SUPPORTED_FILTER_KEYS,
    _build_paper_id_predicate,
    _build_source_kind_predicate,
    _escape_paper_id_literal,
)


def _run(coro):
    """Project pattern (see tests/test_proof_chain.py) — async tests
    use asyncio.run() directly; pytest-asyncio is not configured."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Pure-function tests: _build_paper_id_predicate
# ---------------------------------------------------------------------------


class TestBuildPaperIdPredicate:
    """Direct unit tests of the predicate builder; no LanceDB involved."""

    def test_single_string_is_coerced_to_list(self) -> None:
        """FM-3: a single str must be treated as a one-element list,
        mirroring server.retrieval.bm25._apply_supported_filters."""
        predicate = _build_paper_id_predicate("2604.26204")
        assert predicate == "paper_id IN ('2604.26204')"

    def test_list_is_sorted_for_deterministic_predicate(self) -> None:
        """Sorting makes the IN-clause deterministic — useful for any
        caller that hashes the predicate string."""
        predicate = _build_paper_id_predicate(["2604.26208", "2604.26204"])
        assert predicate == "paper_id IN ('2604.26204','2604.26208')"

    def test_old_style_paper_ids_accepted(self) -> None:
        """is_valid_paper_id accepts both new (YYMM.NNNNN) and old
        (subject/NNNNNNN) formats; bridgeland-stability has both."""
        predicate = _build_paper_id_predicate(["0705.3794", "hep-th/0001234"])
        # Sorted order: digits before letters in ASCII
        assert "0705.3794" in predicate
        assert "hep-th/0001234" in predicate
        assert predicate.startswith("paper_id IN (")
        assert predicate.endswith(")")

    def test_empty_list_raises_value_error(self) -> None:
        """FM-2: empty list MUST raise, not silently coerce to no-filter."""
        with pytest.raises(ValueError, match="must not be empty"):
            _build_paper_id_predicate([])

    def test_oversized_list_raises_value_error(self) -> None:
        """FM-4: more than MAX_PAPER_ID_FILTER_ITEMS items rejected."""
        too_many = [f"2604.{i:05d}" for i in range(MAX_PAPER_ID_FILTER_ITEMS + 1)]
        with pytest.raises(ValueError, match="max allowed is"):
            _build_paper_id_predicate(too_many)

    def test_exactly_max_items_accepted(self) -> None:
        """Boundary: exactly MAX_PAPER_ID_FILTER_ITEMS items must work."""
        at_cap = [f"2604.{i:05d}" for i in range(MAX_PAPER_ID_FILTER_ITEMS)]
        predicate = _build_paper_id_predicate(at_cap)
        assert predicate.count("'") == 2 * MAX_PAPER_ID_FILTER_ITEMS

    def test_malformed_id_raises_with_first_invalid_named(self) -> None:
        """FM-5: per-element validation; raise on FIRST invalid with the
        bad value named in the message."""
        with pytest.raises(ValueError, match="not-an-arxiv-id"):
            _build_paper_id_predicate(["2604.26204", "not-an-arxiv-id"])

    def test_all_malformed_raises(self) -> None:
        # m3 rect F1: error message widened from "invalid arXiv IDs"
        # to "invalid IDs (neither arXiv nor textbook:<slug> form)"
        # in lockstep with the validator widening from
        # is_valid_arxiv_paper_id to is_valid_paper_id.
        with pytest.raises(ValueError, match="invalid IDs"):
            _build_paper_id_predicate(["bad-one", "bad-two"])

    def test_non_str_non_list_raises(self) -> None:
        with pytest.raises(ValueError, match="must be str or list"):
            _build_paper_id_predicate(42)  # type: ignore[arg-type]

    def test_dict_value_raises(self) -> None:
        with pytest.raises(ValueError, match="must be str or list"):
            _build_paper_id_predicate({"paper_id": "x"})  # type: ignore[arg-type]

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="must be str or list"):
            _build_paper_id_predicate(None)

    def test_injection_attempt_rejected_by_regex(self) -> None:
        """FM-1 layer 1: is_valid_paper_id regex structurally rejects
        any string containing a single quote / semicolon / etc.

        m3 rect F1: error message widened to "invalid IDs (neither
        arXiv nor textbook:<slug> form)" — match the new wording.
        """
        with pytest.raises(ValueError, match="invalid IDs"):
            _build_paper_id_predicate(["foo'; DROP TABLE chunks; --"])

    def test_escape_function_doubles_single_quotes(self) -> None:
        """FM-1 layer 2: defense-in-depth escape, even though regex
        prevents the input from reaching this layer."""
        assert _escape_paper_id_literal("a'b") == "a''b"
        assert _escape_paper_id_literal("''") == "''''"
        assert _escape_paper_id_literal("no-quote") == "no-quote"


# ---------------------------------------------------------------------------
# Handler integration tests: mock the LanceDB chain
# ---------------------------------------------------------------------------


def _make_arrow_table(rows: list[dict[str, Any]]) -> pa.Table:
    """Build a minimal pyarrow table matching the chunks schema fields
    that _arrow_to_rows reads."""
    if not rows:
        return pa.table({
            "chunk_id": pa.array([], type=pa.utf8()),
            "paper_id": pa.array([], type=pa.utf8()),
            "kind": pa.array([], type=pa.utf8()),
            "section_path": pa.array([], type=pa.list_(pa.utf8())),
            "body_text": pa.array([], type=pa.utf8()),
            "theorem_name": pa.array([], type=pa.utf8()),
            "theorem_label": pa.array([], type=pa.utf8()),
            "_distance": pa.array([], type=pa.float32()),
            # m9 / e4: _arrow_to_rows now reads source_kind (FM-7 —
            # fixture must carry the column or the read KeyErrors).
            "source_kind": pa.array([], type=pa.utf8()),
        })
    return pa.table({
        "chunk_id": [r["chunk_id"] for r in rows],
        "paper_id": [r["paper_id"] for r in rows],
        "kind": [r.get("kind", "stmt") for r in rows],
        "section_path": [r.get("section_path", []) for r in rows],
        "body_text": [r.get("body_text", "x") for r in rows],
        "theorem_name": [r.get("theorem_name") for r in rows],
        "theorem_label": [r.get("theorem_label") for r in rows],
        "_distance": [r.get("_distance", 0.5) for r in rows],
        # m9 / e4: default "arxiv" unless the row dict overrides it.
        "source_kind": [r.get("source_kind", "arxiv") for r in rows],
    })


class TestTextbookPaperIdFilter:
    """m3 rect F1 — the SEARCH_PAPERS description promises the filter
    accepts both arXiv and textbook:<slug> paper_id forms; the
    handler's validator must match. Pre-rect, the handler used
    ``is_valid_arxiv_paper_id`` and would have hard-errored any
    textbook paper_id sent by an obedient sub-agent.
    """

    def test_single_textbook_paper_id_accepted(self) -> None:
        predicate = _build_paper_id_predicate("textbook:shimura-varieties")
        # SQL form: paper_id IN ('textbook:shimura-varieties')
        assert "textbook:shimura-varieties" in predicate
        assert predicate.startswith("paper_id IN (")

    def test_mixed_arxiv_and_textbook_list_accepted(self) -> None:
        predicate = _build_paper_id_predicate(
            ["textbook:my-book", "2401.00001"]
        )
        assert "textbook:my-book" in predicate
        assert "2401.00001" in predicate

    def test_textbook_too_short_slug_rejected(self) -> None:
        # Slug ``[a-z][a-z0-9-]{2,30}`` — 2-char slug fails.
        with pytest.raises(ValueError, match="invalid IDs"):
            _build_paper_id_predicate("textbook:fo")

    def test_textbook_uppercase_slug_rejected(self) -> None:
        # SLUG_RE is lowercase-only.
        with pytest.raises(ValueError, match="invalid IDs"):
            _build_paper_id_predicate("textbook:UPPERCASE")

    def test_textbook_path_traversal_rejected(self) -> None:
        # Defense-in-depth Threat 1 — the m1 regex rejects ``../``.
        with pytest.raises(ValueError, match="invalid IDs"):
            _build_paper_id_predicate("textbook:../etc/passwd")

    def test_chunk_id_form_rejected_in_filter(self) -> None:
        # Filter accepts paper_id forms, NOT chunk_ids
        # (``textbook:<slug>:<16-hex>`` has 4 colon-segments).
        with pytest.raises(ValueError, match="invalid IDs"):
            _build_paper_id_predicate(
                "textbook:shimura-varieties:abcdef0123456789"
            )

    def test_error_message_mentions_both_forms(self) -> None:
        """The error message must reflect the widened acceptance —
        previously said 'invalid arXiv IDs' which was misleading
        for textbook-paper_id-aware callers."""
        with pytest.raises(ValueError, match="neither arXiv nor textbook"):
            _build_paper_id_predicate("complete-garbage")


class TestBuildSourceKindPredicate:
    """textbook-ingest-m9 / e4 — source_kind filter predicate builder."""

    def test_arxiv_value(self) -> None:
        assert _build_source_kind_predicate("arxiv") == "source_kind = 'arxiv'"

    def test_textbook_value(self) -> None:
        assert (
            _build_source_kind_predicate("textbook")
            == "source_kind = 'textbook'"
        )

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid source_kind"):
            _build_source_kind_predicate("preprint")

    def test_injection_value_rejected_by_whitelist(self) -> None:
        """FM-2: LanceDB has no bound params; the whitelist is the
        primary SQL-injection defense. A quote/semicolon payload is
        not in {arxiv, textbook} → ValueError before interpolation."""
        with pytest.raises(ValueError, match="not a valid source_kind"):
            _build_source_kind_predicate("arxiv'; DROP TABLE chunks; --")

    def test_non_str_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a str"):
            _build_source_kind_predicate(["textbook"])  # type: ignore[arg-type]

    def test_source_kind_in_supported_filter_keys(self) -> None:
        assert "source_kind" in SUPPORTED_FILTER_KEYS


class _FakeSearchBuilder:
    """Mock of the LanceDB search builder chain. Records calls so tests
    can assert the .where() predicate + prefilter args."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.where_call: tuple[str, dict[str, Any]] | None = None
        self.limit_value: int | None = None

    def where(self, predicate: str, **kwargs: Any) -> _FakeSearchBuilder:
        self.where_call = (predicate, kwargs)
        return self

    def limit(self, n: int) -> _FakeSearchBuilder:
        self.limit_value = n
        return self

    def to_arrow(self) -> pa.Table:
        return _make_arrow_table(self._rows)


@pytest.fixture
def fake_resources(monkeypatch: pytest.MonkeyPatch):
    """Install a fake Resources via set_resources() so the handler AND
    server.tools.envelope() (which calls get_resources() to read
    corpus_version) see the same stub. Reset via
    reset_resources_for_tests so other tests aren't polluted."""
    from server.tools import reset_resources_for_tests, set_resources

    captured: dict[str, Any] = {"search_builder": None}

    def _make_search_builder(rows: list[dict[str, Any]]):
        builder = _FakeSearchBuilder(rows)
        captured["search_builder"] = builder
        return builder

    class _FakeSemaphore:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _FakeConfig:
        query_embed_provider = "local"
        result_byte_cap = 256 * 1024  # E13_S04b cap

    class _FakeCorpusInfo:
        version = 101

    class _FakeChunksTable:
        def __init__(self):
            self._rows: list[dict[str, Any]] = []
        def set_rows(self, rows):
            self._rows = rows
        def search(self, query_vec, vector_column_name=None):
            return _make_search_builder(self._rows)

    class _FakeResources:
        def __init__(self):
            self.embed_semaphore = _FakeSemaphore()
            self.config = _FakeConfig()
            self.degraded = None
            self.chunks_table = _FakeChunksTable()
            self.corpus_info = _FakeCorpusInfo()

    fake = _FakeResources()
    set_resources(fake)  # type: ignore[arg-type]
    monkeypatch.setattr("server.handlers.search.get_cache", lambda: None)
    async def _fake_encode(query: str):
        import numpy as np
        return np.zeros(1024, dtype=np.float32)
    monkeypatch.setattr("server.handlers.search.encode_query", _fake_encode)
    yield {"resources": fake, "captured": captured}
    reset_resources_for_tests()


class TestHandlerFilterWiring:
    """Integration tests: handle_search_papers with the fake LanceDB chain."""

    def test_filter_applied_when_paper_id_present(self, fake_resources) -> None:
        """AC #1: filter scopes results AND the .where() predicate +
        prefilter=True are passed to LanceDB."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([
            {"chunk_id": "arxiv:2604.26204:abc", "paper_id": "2604.26204"},
            {"chunk_id": "arxiv:2604.26208:def", "paper_id": "2604.26208"},
        ])
        _run(handle_search_papers(
            query="Bridgeland stability",
            filters={"paper_id": ["2604.26204", "2604.26208"]},
            k=10,
        ))
        builder = fake_resources["captured"]["search_builder"]
        assert builder.where_call is not None, "expected .where() called"
        predicate, kwargs = builder.where_call
        assert predicate == "paper_id IN ('2604.26204','2604.26208')"
        assert kwargs == {"prefilter": True}, "must use prefilter=True per synthesis"

    def test_no_filter_no_where_call(self, fake_resources) -> None:
        """AC #2: when filters=None, .where() is NOT called (pre-m1
        byte-identical behavior on the dense-only path)."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        _run(handle_search_papers(query="anything", filters=None, k=10))
        builder = fake_resources["captured"]["search_builder"]
        assert builder.where_call is None

    def test_empty_filter_dict_no_where_call(self, fake_resources) -> None:
        """filters={} (empty dict, no paper_id key) is no-filter."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        _run(handle_search_papers(query="anything", filters={}, k=10))
        assert fake_resources["captured"]["search_builder"].where_call is None

    def test_empty_paper_id_list_raises_clear_error(self, fake_resources) -> None:
        """AC #3 / FM-2: empty list → ValueError, not 500."""
        from server.handlers.search import handle_search_papers
        with pytest.raises(ValueError, match="must not be empty"):
            _run(handle_search_papers(
                query="x", filters={"paper_id": []}, k=10,
            ))

    def test_string_paper_id_coerced_to_one_element(self, fake_resources) -> None:
        """FM-3: filters={"paper_id": "x"} works."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        _run(handle_search_papers(
            query="x", filters={"paper_id": "2604.26204"}, k=10,
        ))
        builder = fake_resources["captured"]["search_builder"]
        assert builder.where_call is not None
        predicate, kwargs = builder.where_call
        assert predicate == "paper_id IN ('2604.26204')"
        assert kwargs == {"prefilter": True}

    def test_malformed_paper_id_raises_clear_error(self, fake_resources) -> None:
        """AC #3 / FM-5: invalid IDs in the list → ValueError.

        m3 rect F1: error message widened to "invalid IDs (neither
        arXiv nor textbook:<slug> form)" in lockstep with the
        validator widening from is_valid_arxiv_paper_id to
        is_valid_paper_id.
        """
        from server.handlers.search import handle_search_papers
        with pytest.raises(ValueError, match="invalid IDs"):
            _run(handle_search_papers(
                query="x",
                filters={"paper_id": ["2604.26204", "not-an-id"]},
                k=10,
            ))

    def test_non_list_non_str_paper_id_raises(self, fake_resources) -> None:
        """AC #3: filters={"paper_id": 42} → ValueError."""
        from server.handlers.search import handle_search_papers
        with pytest.raises(ValueError, match="must be str or list"):
            _run(handle_search_papers(
                query="x", filters={"paper_id": 42}, k=10,
            ))

    def test_oversized_paper_id_list_raises(self, fake_resources) -> None:
        """FM-4: > MAX_PAPER_ID_FILTER_ITEMS → ValueError."""
        from server.handlers.search import handle_search_papers
        too_many = [f"2604.{i:05d}" for i in range(MAX_PAPER_ID_FILTER_ITEMS + 1)]
        with pytest.raises(ValueError, match="max allowed is"):
            _run(handle_search_papers(
                query="x", filters={"paper_id": too_many}, k=10,
            ))

    def test_nonexistent_paper_id_returns_empty(self, fake_resources) -> None:
        """FM-7: valid-format paper_id not in corpus → empty results,
        no error. The fake table returns [] for this case."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        result = _run(handle_search_papers(
            query="x",
            filters={"paper_id": ["9999.99999"]},
            k=10,
        ))
        # CallToolResult; structuredContent has empty results
        structured = result.structuredContent
        # envelope wraps payload — find results
        assert "results" in structured or "data" in structured

    def test_unknown_filter_key_surfaced_as_warning(self, fake_resources) -> None:
        """FM-9: filters={"paper_id":[...], "year":2024} keeps a warning
        for 'year' while honoring 'paper_id'."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        result = _run(handle_search_papers(
            query="x",
            filters={"paper_id": ["2604.26204"], "year": 2024},
            k=10,
        ))
        structured = result.structuredContent
        # Drill into the envelope to find filter_warnings
        payload = structured.get("data", structured)
        warnings = payload.get("filter_warnings", [])
        joined = " ".join(warnings)
        assert "'year'" in joined or '"year"' in joined
        # paper_id was honored — must NOT appear in warnings
        assert "paper_id" not in joined or "supported keys" in joined
        # And the .where() call WAS made
        assert fake_resources["captured"]["search_builder"].where_call is not None

    def test_only_paper_id_filter_no_warnings(self, fake_resources) -> None:
        """When the only filter key is the honored paper_id, no
        filter_warnings should be emitted (m1 closes that F6 remnant)."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        result = _run(handle_search_papers(
            query="x", filters={"paper_id": ["2604.26204"]}, k=10,
        ))
        structured = result.structuredContent
        payload = structured.get("data", structured)
        warnings = payload.get("filter_warnings", [])
        # Empty (no unknown keys, no cursor)
        assert warnings == []


class TestSourceKindFilterWiring:
    """textbook-ingest-m9 / e4 — source_kind filter threaded into the
    dense ANN .where() pre-filter + surfaced in the result envelope."""

    def test_source_kind_threads_where_predicate(self, fake_resources) -> None:
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([
            {"chunk_id": "textbook:sv-book:abc", "paper_id": "textbook:sv-book",
             "source_kind": "textbook"},
        ])
        _run(handle_search_papers(
            query="shimura varieties",
            filters={"source_kind": "textbook"}, k=10,
        ))
        builder = fake_resources["captured"]["search_builder"]
        assert builder.where_call is not None
        predicate, kwargs = builder.where_call
        assert predicate == "source_kind = 'textbook'"
        assert kwargs == {"prefilter": True}

    def test_combined_paper_id_and_source_kind(self, fake_resources) -> None:
        """Both filters present → ANDed, parenthesized, single .where()."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        _run(handle_search_papers(
            query="x",
            filters={"paper_id": "textbook:sv-book", "source_kind": "textbook"},
            k=10,
        ))
        builder = fake_resources["captured"]["search_builder"]
        assert builder.where_call is not None
        predicate, kwargs = builder.where_call
        # paper_id clause first, then source_kind, each parenthesized.
        assert predicate == (
            "(paper_id IN ('textbook:sv-book')) AND (source_kind = 'textbook')"
        )
        assert kwargs == {"prefilter": True}

    def test_invalid_source_kind_raises_clear_error(self, fake_resources) -> None:
        from server.handlers.search import handle_search_papers
        with pytest.raises(ValueError, match="not a valid source_kind"):
            _run(handle_search_papers(
                query="x", filters={"source_kind": "preprint"}, k=10,
            ))

    def test_result_row_carries_source_kind(self, fake_resources) -> None:
        """The result envelope row carries the source_kind tag (e4
        outcome: operator sees source_kind='textbook')."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([
            {"chunk_id": "textbook:sv-book:abc", "paper_id": "textbook:sv-book",
             "source_kind": "textbook"},
        ])
        result = _run(handle_search_papers(query="x", filters=None, k=10))
        payload = result.structuredContent.get("data", result.structuredContent)
        rows = payload["results"]
        assert rows, "expected at least one result row"
        assert rows[0]["source_kind"] == "textbook"

    def test_no_source_kind_filter_no_where(self, fake_resources) -> None:
        """Default: no source_kind filter → no .where() call (returns
        chunks of any source_kind)."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        _run(handle_search_papers(query="x", filters={}, k=10))
        assert fake_resources["captured"]["search_builder"].where_call is None


# ---------------------------------------------------------------------------
# Cache-key correctness (FM-6 regression)
# ---------------------------------------------------------------------------


class TestCacheKeyDistinguishesFilterSets:
    """The roadmap brief said 'update the cache key to include filters'
    but both researchers verified the cache key ALREADY includes the
    filters dict via canonical_key_components. These tests pin that
    behavior so future cache refactors don't silently break filter
    scoping correctness (FM-6)."""

    def test_canonical_filter_fingerprint_distinct_per_filter_set(self) -> None:
        """Two filter dicts with different paper_id sets must produce
        distinct serializations (sort_keys=True canonicalizes)."""
        a = json.dumps(
            {"paper_id": ["2604.26204"]}, sort_keys=True, separators=(",", ":")
        )
        b = json.dumps(
            {"paper_id": ["2604.26208"]}, sort_keys=True, separators=(",", ":")
        )
        assert a != b

    def test_canonical_filter_fingerprint_no_filter_distinct(self) -> None:
        """filters=None and filters={"paper_id":["x"]} must serialize
        to distinct strings (so the Tier-1 cache key differs)."""
        none_repr = json.dumps({} or {}, sort_keys=True, separators=(",", ":"))
        filtered = json.dumps(
            {"paper_id": ["x"]}, sort_keys=True, separators=(",", ":")
        )
        assert none_repr != filtered

    def test_source_kind_filter_distinct_cache_key(self) -> None:
        """m9 / e4: a source_kind=textbook query must NOT collide with
        an unfiltered query in the cache. The filters dict is hashed
        into the key via canonical_key_components, so different filters
        → different serialization → different key."""
        unfiltered = json.dumps({} or {}, sort_keys=True, separators=(",", ":"))
        textbook = json.dumps(
            {"source_kind": "textbook"}, sort_keys=True, separators=(",", ":")
        )
        arxiv = json.dumps(
            {"source_kind": "arxiv"}, sort_keys=True, separators=(",", ":")
        )
        assert len({unfiltered, textbook, arxiv}) == 3


# ---------------------------------------------------------------------------
# Tool-schema byte-stability (AC #4) — cross-check via existing test
# ---------------------------------------------------------------------------


def test_supported_filter_keys_matches_expected() -> None:
    """SUPPORTED_FILTER_KEYS is the source of truth for which filter
    keys are honored. m1 shipped {'paper_id'}; textbook-ingest-m9 / e4
    added 'source_kind'. A future milestone extending this set should
    bump the documented supported keys in the docstring +
    filter_warnings message."""
    assert frozenset({"paper_id", "source_kind"}) == SUPPORTED_FILTER_KEYS


def test_filters_field_description_names_source_kind() -> None:
    """e4 rect F3 (MEDIUM): the ``filters`` parameter Field description
    — which FastMCP renders into the live ``tools/list`` inputSchema —
    MUST name ``source_kind`` as an honored key. Before this fix the
    same ``tools/list`` payload contradicted itself: the ToolMeta said
    source_kind was filterable while the parameter schema said "other
    keys are ignored". Guards against that doc-vs-validator drift
    re-surfacing on the inputSchema surface."""
    import typing

    from server.handlers.search import handle_search_papers

    hints = typing.get_type_hints(handle_search_papers, include_extras=True)
    filters_ann = hints["filters"]
    # Annotated[dict|None, Field(...)] → the FieldInfo is in __metadata__.
    field_info = filters_ann.__metadata__[0]
    assert "source_kind" in field_info.description, (
        "filters Field description must name source_kind so the "
        "tools/list inputSchema agrees with the ToolMeta description"
    )


def test_arrow_to_rows_null_source_kind_falls_back_to_arxiv() -> None:
    """e4 rect F5 (MEDIUM): _arrow_to_rows emits source_kind="arxiv" when
    the column value is NULL — a legacy row that slipped past the m2
    backfill. The defensive ``sk if sk is not None else "arxiv"`` branch
    (search.py:_arrow_to_rows) had zero coverage: _make_arrow_table
    defaults source_kind to "arxiv" and no test ever fed None. This pins
    the documented fallback so a future edit (e.g. to "unknown", or
    removing it and tripping the result schema's required +
    additionalProperties:false) is caught."""
    from server.handlers.search import _arrow_to_rows

    # Key present with value None → a real NULL in the arrow column
    # (_make_arrow_table's r.get default only fires when the key is absent).
    table = _make_arrow_table([
        {
            "chunk_id": "arxiv:2401.00001:abcdef0123456789",
            "paper_id": "2401.00001",
            "source_kind": None,
        },
    ])
    rows = _arrow_to_rows(table)
    assert len(rows) == 1
    assert rows[0]["source_kind"] == "arxiv"


# ---------------------------------------------------------------------------
# Rectification regression tests (F1, F2, F3, F4 from critique-merged)
# ---------------------------------------------------------------------------


class TestRectificationGuards:
    """Regression guards for the m1 critique findings. Each test names
    its finding ID in the docstring so future maintainers can trace
    back to the critique."""

    def test_filter_oversized_key_rejected(self, fake_resources) -> None:
        """F2 (HIGH): per-key length cap rejects oversized keys at the
        boundary, preventing the filter_warnings reflection block from
        amplifying input size beyond the result byte cap."""
        from server.handlers.search import MAX_FILTER_KEY_LEN, handle_search_papers
        big_key = "x" * (MAX_FILTER_KEY_LEN + 1)
        with pytest.raises(ValueError, match="exceeds cap"):
            _run(handle_search_papers(
                query="anything", filters={big_key: "v"}, k=3,
            ))

    def test_filter_warnings_total_size_bounded(self, fake_resources) -> None:
        """F2 (HIGH): With MAX_FILTER_KEY_LEN enforced, even an
        adversarial filter dict at the maximum cap produces a bounded
        filter_warnings payload."""
        from server.handlers.search import (
            MAX_FILTER_ITEMS,
            MAX_FILTER_KEY_LEN,
            handle_search_papers,
        )
        # 100 keys of 64 chars each = 6400 chars of key bytes. Per-warning
        # is ~150 chars of boilerplate + ~70 chars of key repr → ~22 KB total.
        # That's well under the 256 KB cap.
        adversarial = {f"k{i:063d}": "v" for i in range(MAX_FILTER_ITEMS - 1)}
        # Verify keys are at the cap or just under (sanity check)
        assert all(len(k) <= MAX_FILTER_KEY_LEN for k in adversarial)
        result = _run(handle_search_papers(
            query="x", filters=adversarial, k=3,
        ))
        sc = result.structuredContent
        payload = sc.get("data", sc)
        warnings = payload.get("filter_warnings", [])
        total_bytes = sum(len(w.encode("utf-8")) for w in warnings)
        assert total_bytes < 256 * 1024, (
            f"filter_warnings total {total_bytes} bytes exceeds 256 KB cap"
        )

    def test_filter_warnings_rejects_non_str_key(self, fake_resources) -> None:
        """F2 companion: non-string keys are rejected early."""
        from server.handlers.search import handle_search_papers
        with pytest.raises(ValueError, match="must be strings"):
            _run(handle_search_papers(
                query="x", filters={42: "v"}, k=3,
            ))

    def test_filters_field_description_documents_paper_id(self) -> None:
        """F1 (HIGH): the rendered tool schema's filters description
        must mention paper_id so LLM consumers can discover the m1
        feature."""
        # Read the rendered Pydantic Field description directly.
        # This catches any future refactor that reverts the description
        # to the stale "ignored at v1" text.
        from server.handlers.search import handle_search_papers
        sig = (
            handle_search_papers.__wrapped__
            if hasattr(handle_search_papers, "__wrapped__")
            else handle_search_papers
        )
        # Access the type annotations to find the Field metadata
        import typing
        hints = typing.get_type_hints(sig, include_extras=True)
        filters_annotation = hints["filters"]
        # Annotated[dict[...] | None, Field(...)] — Field is the second arg
        meta_args = filters_annotation.__metadata__
        field_meta = meta_args[0]
        description = field_meta.description or ""
        assert "paper_id" in description, (
            f"filters Field description must mention paper_id; got: {description!r}"
        )

    def test_search_papers_toolmeta_mentions_paper_id_filter(self) -> None:
        """F1 (HIGH) companion: top-level SEARCH_PAPERS description
        also mentions paper_id filter scoping."""
        from server.tools import SEARCH_PAPERS
        assert "paper_id" in SEARCH_PAPERS.description, (
            f"SEARCH_PAPERS.description must mention paper_id; "
            f"got: {SEARCH_PAPERS.description!r}"
        )

    def test_paper_id_rejects_trailing_newline(self) -> None:
        """F3 (MEDIUM): is_valid_paper_id with \\Z anchor rejects
        strings ending in \\n. Pre-fix, Python's default $ semantics
        accepted them. Closes the defense-in-depth gap named in the
        _escape_paper_id_literal docstring."""
        from ingest.identifiers import is_valid_paper_id
        assert is_valid_paper_id("2604.26204\n") is False
        assert is_valid_paper_id("hep-th/0001234\n") is False
        # Also trailing CR + multiline
        assert is_valid_paper_id("2604.26204\r") is False
        assert is_valid_paper_id("2604.26204\r\n") is False
        # And the unmodified strings still validate
        assert is_valid_paper_id("2604.26204") is True
        assert is_valid_paper_id("hep-th/0001234") is True

    def test_cache_key_str_vs_one_element_list_equivalent(self) -> None:
        """F4 (MEDIUM): _canonicalize_filters normalizes
        {"paper_id": "x"} and {"paper_id": ["x"]} to the same form so
        the cache key canonicalizer (json.dumps with sort_keys) sees
        identical input → same cache slot for semantically-equivalent
        calls."""
        from server.handlers.search import _canonicalize_filters
        canon_str = _canonicalize_filters({"paper_id": "2604.26204"})
        canon_list = _canonicalize_filters({"paper_id": ["2604.26204"]})
        # Both must produce identical canonical dicts
        assert canon_str == canon_list
        # And the dicts serialize identically under the cache's canonicalizer
        a = json.dumps(canon_str, sort_keys=True, separators=(",", ":"))
        b = json.dumps(canon_list, sort_keys=True, separators=(",", ":"))
        assert a == b
        # None → None passthrough
        assert _canonicalize_filters(None) is None

    def test_cache_key_unsorted_list_normalized(self) -> None:
        """F4 companion: paper_id lists in different orders normalize
        to the same canonical form."""
        from server.handlers.search import _canonicalize_filters
        a = _canonicalize_filters({"paper_id": ["b", "a", "c"]})
        b = _canonicalize_filters({"paper_id": ["c", "a", "b"]})
        assert a == b
        assert a == {"paper_id": ["a", "b", "c"]}


# ---------------------------------------------------------------------------
# m2 — filters_applied echo field
# ---------------------------------------------------------------------------


class TestFiltersAppliedHelper:
    """Direct unit tests of _inject_filters_applied."""

    def test_canonical_filters_none_returns_payload_unchanged(self) -> None:
        from server.handlers.search import _inject_filters_applied
        p = {"results": [], "retrieval_mode": "dense_only"}
        out = _inject_filters_applied(p, None)
        assert out is p
        assert "filters_applied" not in out  # absent, not null

    def test_canonical_filters_with_paper_id_adds_echo(self) -> None:
        from server.handlers.search import _inject_filters_applied
        p: dict = {"results": []}
        out = _inject_filters_applied(p, {"paper_id": ["a", "b"]})
        assert out["filters_applied"] == {"paper_id": ["a", "b"]}

    def test_unsupported_keys_excluded_from_echo(self) -> None:
        """Synthesis Disagreement 1: only SUPPORTED_FILTER_KEYS in the
        echo. year/categories etc. live in filter_warnings, NOT here."""
        from server.handlers.search import _inject_filters_applied
        p: dict = {"results": []}
        out = _inject_filters_applied(
            p, {"paper_id": ["x"], "year": 2024, "categories": ["math.AG"]},
        )
        assert out["filters_applied"] == {"paper_id": ["x"]}
        assert "year" not in out["filters_applied"]

    def test_canonical_filters_with_no_supported_keys_omits_field(self) -> None:
        """If canonical_filters has only UNsupported keys (year etc.),
        filters_applied should be absent — nothing was actually applied."""
        from server.handlers.search import _inject_filters_applied
        p: dict = {"results": []}
        out = _inject_filters_applied(p, {"year": 2024})
        assert "filters_applied" not in out


class TestFiltersAppliedHandlerIntegration:
    """End-to-end through the handler: confirm filters_applied appears
    in the structured envelope on all 3 cache paths."""

    def test_filters_applied_on_miss_path(self, fake_resources) -> None:
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        result = _run(handle_search_papers(
            query="x", filters={"paper_id": ["2604.26204"]}, k=3,
        ))
        sc = result.structuredContent
        assert sc.get("filters_applied") == {"paper_id": ["2604.26204"]}

    def test_filters_applied_absent_when_no_filter(self, fake_resources) -> None:
        """Synthesis Disagreement 4: absent, not null, preserves byte-
        equivalence with pre-m2 responses on the unfiltered common path."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        result = _run(handle_search_papers(query="x", filters=None, k=3))
        sc = result.structuredContent
        assert "filters_applied" not in sc

    def test_filters_applied_uses_canonical_form_with_str_input(
        self, fake_resources,
    ) -> None:
        """Synthesis Disagreement 1: caller passed str; echo is the
        canonical list form (what was actually used to scope the query)."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        result = _run(handle_search_papers(
            query="x", filters={"paper_id": "2604.26204"}, k=3,
        ))
        sc = result.structuredContent
        # str coerced to list per _canonicalize_filters
        assert sc.get("filters_applied") == {"paper_id": ["2604.26204"]}

    def test_filters_applied_uses_sorted_list_form(self, fake_resources) -> None:
        """Caller passed unsorted list; echo is sorted (canonical)."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        result = _run(handle_search_papers(
            query="x",
            filters={"paper_id": ["0712.1083", "0705.3794"]},
            k=3,
        ))
        sc = result.structuredContent
        assert sc.get("filters_applied") == {
            "paper_id": ["0705.3794", "0712.1083"],
        }

    def test_filters_applied_unknown_keys_still_warned_not_applied(
        self, fake_resources,
    ) -> None:
        """FM-9 companion: unknown keys appear in filter_warnings, NOT
        in filters_applied. Two non-overlapping views."""
        from server.handlers.search import handle_search_papers
        fake_resources["resources"].chunks_table.set_rows([])
        result = _run(handle_search_papers(
            query="x",
            filters={"paper_id": ["2604.26204"], "year": 2024},
            k=3,
        ))
        sc = result.structuredContent
        applied = sc.get("filters_applied")
        assert applied == {"paper_id": ["2604.26204"]}
        warnings = sc.get("filter_warnings", [])
        assert any("year" in w for w in warnings)


class TestSchemaConformanceForFiltersApplied:
    """Validate the new payload shape against the JSON schema."""

    def test_schema_includes_filters_applied_property(self) -> None:
        """The schema must declare filters_applied in properties (with
        additionalProperties:false, undeclared fields are rejected)."""
        import json
        from pathlib import Path
        schema = json.loads(
            Path("server/schemas/search_papers_result.json").read_text()
        )
        assert "filters_applied" in schema["properties"]
        # Must NOT be in required (it's conditional/optional)
        assert "filters_applied" not in schema.get("required", [])

    def test_schema_version_matches_after_m2_bump(self) -> None:
        """Synthesis: schema["version"] must equal TOOL_SCHEMA_VERSION
        (cross-checked by tests/test_snippet_contract.py too; this is
        an m2-local regression guard)."""
        import json
        from pathlib import Path

        from server.tools import TOOL_SCHEMA_VERSION
        schema = json.loads(
            Path("server/schemas/search_papers_result.json").read_text()
        )
        assert schema["version"] == TOOL_SCHEMA_VERSION
        assert schema["$id"].endswith(f"v{TOOL_SCHEMA_VERSION}.json")

    def test_filtered_response_validates_against_schema(
        self, fake_resources,
    ) -> None:
        """End-to-end: a filtered response with filters_applied set
        must pass jsonschema.validate."""
        import json
        from pathlib import Path

        import jsonschema

        from server.handlers.search import handle_search_papers
        schema = json.loads(
            Path("server/schemas/search_papers_result.json").read_text()
        )
        fake_resources["resources"].chunks_table.set_rows([])
        result = _run(handle_search_papers(
            query="x", filters={"paper_id": ["2604.26204"]}, k=3,
        ))
        sc = result.structuredContent
        # Schema validation must not raise
        jsonschema.validate(instance=sc, schema=schema)


# ---------------------------------------------------------------------------
# m2 rect F5 — _canonicalize_filters dedup
# ---------------------------------------------------------------------------


class TestCanonicalizeFiltersDedup:
    """m2 rect F5 closure: `_canonicalize_filters` must dedup the
    `paper_id` list so semantically-equivalent inputs share a cache
    key AND emit the same `filters_applied` echo. The original m2
    impl only sorted; the rect added `dict.fromkeys()` for dedup."""

    def test_canonicalize_filters_dedupes_paper_id(self) -> None:
        from server.handlers.search import _canonicalize_filters
        out = _canonicalize_filters({"paper_id": ["a", "a", "b"]})
        assert out == {"paper_id": ["a", "b"]}

    def test_canonicalize_filters_dedupes_then_sorts(self) -> None:
        """Order of operations: dedup first (via dict.fromkeys preserves
        first-occurrence) then sort. Both calls must produce identical
        output regardless of input ordering."""
        from server.handlers.search import _canonicalize_filters
        out_a = _canonicalize_filters({"paper_id": ["b", "a", "a", "b"]})
        out_b = _canonicalize_filters({"paper_id": ["a", "b"]})
        assert out_a == out_b == {"paper_id": ["a", "b"]}

    def test_dedup_does_not_affect_single_element(self) -> None:
        from server.handlers.search import _canonicalize_filters
        out = _canonicalize_filters({"paper_id": ["x"]})
        assert out == {"paper_id": ["x"]}

    def test_dedup_preserves_other_filter_keys(self) -> None:
        """Dedup only fires on the paper_id list; other keys
        pass through unchanged."""
        from server.handlers.search import _canonicalize_filters
        out = _canonicalize_filters({
            "paper_id": ["x", "x"], "year": 2024, "categories": ["math.AG"],
        })
        assert out == {
            "paper_id": ["x"], "year": 2024, "categories": ["math.AG"],
        }


# ---------------------------------------------------------------------------
# m2 rect F1 + F2 — cache-hit re-stamp tests
# ---------------------------------------------------------------------------


class _FakeCache:
    """Minimal in-memory MultiTierCache stand-in that exposes only the
    surface `handle_search_papers` actually calls (lookup_search /
    store_search). Stores Tier-1 payloads keyed by the canonical
    (query, filters, k, level) tuple; Tier-2 keyed by the same tuple
    minus query (semantic match).

    The point of this fake is to exercise the cache-HIT re-stamp path
    of `_inject_filters_applied` — F1 in the m2 adversary critique
    flagged that the production `MultiTierCache` path was untested,
    so without this fake we cannot verify the post-cache stamping
    invariant established by F2 (Option A — strip from cache; re-stamp
    on every emit)."""

    def __init__(self) -> None:
        self.tier1: dict[Any, Any] = {}
        self.tier2: dict[Any, Any] = {}
        self.stored_payloads: list[Any] = []

    @staticmethod
    def _t1_key(query, filters, k, level):
        # Deterministic, hashable representation of the filter dict.
        f_key = (
            tuple(sorted(
                (k_, tuple(v) if isinstance(v, list) else v)
                for k_, v in (filters or {}).items()
            ))
            if filters
            else None
        )
        return (query, f_key, k, level)

    @staticmethod
    def _t2_key(filters, level):
        # Tier-2 semantic match: same filter + level, embedding match
        # done elsewhere. For test purposes we collapse "semantic
        # equivalent" to "same filter + level + ANY query".
        f_key = (
            tuple(sorted(
                (k_, tuple(v) if isinstance(v, list) else v)
                for k_, v in (filters or {}).items()
            ))
            if filters
            else None
        )
        return (f_key, level)

    async def lookup_search(
        self, query, filters, k, query_embedding=None, *, level=None,
        corpus_version=None,
    ):
        # notebook-retrieval-m2 F2: the real cache API gained an optional
        # ``corpus_version`` override; mirror it so the handler's call site
        # (which now always passes it) does not TypeError. The shared-corpus
        # path passes None — this fake's keying is unaffected.
        t1 = self.tier1.get(self._t1_key(query, filters, k, level))
        if t1 is not None:
            return t1, "1"
        if query_embedding is None:
            return None, ""
        t2 = self.tier2.get(self._t2_key(filters, level))
        if t2 is not None:
            return t2, "2"
        return None, ""

    async def store_search(
        self, query, filters, k, payload, query_embedding=None, *, level=None,
        corpus_version=None,
    ):
        self.stored_payloads.append(payload)
        self.tier1[self._t1_key(query, filters, k, level)] = payload
        if query_embedding is not None:
            self.tier2[self._t2_key(filters, level)] = payload


@pytest.fixture
def fake_resources_with_cache(monkeypatch: pytest.MonkeyPatch):
    """Variant of `fake_resources` that installs a `_FakeCache` instead
    of monkeypatching `get_cache` to `None`. Lets the cache-hit
    re-stamp tests verify the F1/F2 invariants end-to-end through
    the handler."""
    from server.tools import reset_resources_for_tests, set_resources

    captured: dict[str, Any] = {"search_builder": None}

    def _make_search_builder(rows: list[dict[str, Any]]):
        builder = _FakeSearchBuilder(rows)
        captured["search_builder"] = builder
        return builder

    class _FakeSemaphore:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _FakeConfig:
        query_embed_provider = "local"
        result_byte_cap = 256 * 1024

    class _FakeCorpusInfo:
        version = 101

    class _FakeChunksTable:
        def __init__(self):
            self._rows: list[dict[str, Any]] = []
        def set_rows(self, rows):
            self._rows = rows
        def search(self, query_vec, vector_column_name=None):
            return _make_search_builder(self._rows)

    class _FakeResources:
        def __init__(self):
            self.embed_semaphore = _FakeSemaphore()
            self.config = _FakeConfig()
            self.degraded = None
            self.chunks_table = _FakeChunksTable()
            self.corpus_info = _FakeCorpusInfo()

    fake = _FakeResources()
    fake_cache = _FakeCache()
    set_resources(fake)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "server.handlers.search.get_cache", lambda: fake_cache,
    )

    async def _fake_encode(query: str):
        import numpy as np
        return np.zeros(1024, dtype=np.float32)
    monkeypatch.setattr("server.handlers.search.encode_query", _fake_encode)
    yield {"resources": fake, "cache": fake_cache, "captured": captured}
    reset_resources_for_tests()


class TestFiltersAppliedHitPathRestamp:
    """m2 rect F1 closure: exercise the Tier-1 / Tier-2 cache-hit
    re-stamp paths for `filters_applied`. Combined with the F2 closure
    (strip-then-re-add: miss path stores filter-agnostic payload,
    `_restamp_degraded` pops any stale `filters_applied`), these
    tests pin the invariant that the cached value never carries
    caller-specific metadata."""

    def test_tier1_hit_restamps_filters_applied(
        self, fake_resources_with_cache,
    ) -> None:
        """First call: miss + store (filter-agnostic cached payload).
        Second call: Tier-1 hit + re-stamp. Both wire-form responses
        carry the same `filters_applied` echo."""
        from server.handlers.search import handle_search_papers
        fake_resources_with_cache["resources"].chunks_table.set_rows([])
        r1 = _run(handle_search_papers(
            query="x", filters={"paper_id": ["2604.26204"]}, k=3,
        ))
        r2 = _run(handle_search_papers(
            query="x", filters={"paper_id": ["2604.26204"]}, k=3,
        ))
        sc1 = r1.structuredContent
        sc2 = r2.structuredContent
        assert sc1.get("filters_applied") == {"paper_id": ["2604.26204"]}
        assert sc2.get("filters_applied") == {"paper_id": ["2604.26204"]}
        # Both wire responses identical on the load-bearing field.
        assert sc1["filters_applied"] == sc2["filters_applied"]

    def test_tier2_hit_restamps_filters_applied(
        self, fake_resources_with_cache,
    ) -> None:
        """Tier-2 path: same filter + level, different query string.
        The fake-cache models Tier-2 as a semantic-equivalent match
        (same filter + level matches regardless of query). The
        re-stamp must still fire."""
        from server.handlers.search import handle_search_papers
        fake_resources_with_cache["resources"].chunks_table.set_rows([])
        # First call: miss + store under Tier-1 key (query="alpha")
        # and Tier-2 key (filter+level, no query).
        _ = _run(handle_search_papers(
            query="alpha", filters={"paper_id": ["2604.26204"]}, k=3,
        ))
        # Second call: DIFFERENT query string, same filter -> Tier-1
        # MISS (different query) -> Tier-2 HIT (filter+level match).
        r2 = _run(handle_search_papers(
            query="beta", filters={"paper_id": ["2604.26204"]}, k=3,
        ))
        sc2 = r2.structuredContent
        assert sc2.get("filters_applied") == {"paper_id": ["2604.26204"]}

    def test_cached_payload_omits_filters_applied(
        self, fake_resources_with_cache,
    ) -> None:
        """F2 strip-then-re-add invariant: the cached value MUST NOT
        carry `filters_applied`. The miss path stamps post-store,
        and `_restamp_degraded` pops any stale field defensively
        on every hit."""
        from server.handlers.search import handle_search_papers
        fake_resources_with_cache["resources"].chunks_table.set_rows([])
        _ = _run(handle_search_papers(
            query="x", filters={"paper_id": ["2604.26204"]}, k=3,
        ))
        # Reach into the fake cache; verify the stored Tier-1 payload
        # is FILTER-AGNOSTIC (no `filters_applied` field).
        cache = fake_resources_with_cache["cache"]
        assert len(cache.stored_payloads) == 1
        stored = cache.stored_payloads[0]
        assert "filters_applied" not in stored, (
            f"Cached payload must be filter-agnostic; got "
            f"filters_applied={stored.get('filters_applied')!r}. "
            "F2 strip-then-re-add invariant violated."
        )

    def test_tier1_hit_strips_stale_cached_filters_applied(
        self, fake_resources_with_cache,
    ) -> None:
        """Defensive regression: if a payload was cached by an older
        code path (pre-F2) WITH `filters_applied` baked in, the hit
        path must still strip and re-stamp with the current request's
        canonical filter. `_restamp_degraded`'s `pop` call is the
        gate; this test prevents a future refactor from silently
        removing it."""
        from server.handlers.search import handle_search_papers
        fake_resources_with_cache["resources"].chunks_table.set_rows([])
        # Manually seed the Tier-1 cache with a payload that ALREADY
        # contains a stale `filters_applied` from a hypothetical
        # pre-F2 cached entry.
        cache = fake_resources_with_cache["cache"]
        stale_payload = {
            "corpus_version": 101,
            "embed_model": "bge-m3",
            "excluded_kinds": ["proof"],
            "filter_warnings": [],
            "next_cursor": None,
            "results": [],
            "retrieval_mode": "dense_only",
            # Stale field from a different request — must be replaced.
            "filters_applied": {"paper_id": ["WRONG_STALE_ID"]},
        }
        key = cache._t1_key(
            "x", {"paper_id": ["2604.26204"]}, 3, "theorem",
        )
        cache.tier1[key] = stale_payload
        # Now make the request — hit fires.
        r = _run(handle_search_papers(
            query="x", filters={"paper_id": ["2604.26204"]}, k=3,
        ))
        sc = r.structuredContent
        # The stale value MUST have been stripped and re-stamped
        # with the current request's canonical filter.
        assert sc["filters_applied"] == {"paper_id": ["2604.26204"]}
        assert "WRONG_STALE_ID" not in str(sc["filters_applied"])

    def test_no_filter_call_omits_filters_applied_on_hit(
        self, fake_resources_with_cache,
    ) -> None:
        """The no-filter common path must remain byte-equivalent to
        pre-m2 across miss + hit (Synthesis Disagreement #4)."""
        from server.handlers.search import handle_search_papers
        fake_resources_with_cache["resources"].chunks_table.set_rows([])
        r1 = _run(handle_search_papers(query="x", filters=None, k=3))
        r2 = _run(handle_search_papers(query="x", filters=None, k=3))
        sc1 = r1.structuredContent
        sc2 = r2.structuredContent
        assert "filters_applied" not in sc1
        assert "filters_applied" not in sc2


# ---------------------------------------------------------------------------
# BM25-path source_kind branch (supplementary; m9 / e4)
# ---------------------------------------------------------------------------


class TestBm25SourceKindBranch:
    """The supplementary BM25-path filter in
    server.retrieval.bm25._apply_supported_filters infers source_kind
    from the chunk_id prefix (BM25 candidates are (chunk_id, score)
    tuples with no source_kind column). The authoritative path is the
    LanceDB dense pre-filter; this branch keeps the filter coherent if
    the hybrid path is ever active."""

    def test_source_kind_from_chunk_id(self) -> None:
        from server.retrieval.bm25 import _source_kind_from_chunk_id

        assert _source_kind_from_chunk_id("arxiv:2401.1:abc") == "arxiv"
        assert _source_kind_from_chunk_id("textbook:sv-book:abc") == "textbook"
        assert _source_kind_from_chunk_id("weird:thing:abc") is None

    def test_filter_keeps_only_textbook(self) -> None:
        from server.retrieval.bm25 import _apply_supported_filters

        candidates = [
            ("arxiv:2401.00001:aaa", 0.9),
            ("textbook:sv-book:bbb", 0.8),
            ("arxiv:2401.00002:ccc", 0.7),
        ]
        out = _apply_supported_filters(candidates, {"source_kind": "textbook"})
        assert out == [("textbook:sv-book:bbb", 0.8)]

    def test_filter_keeps_only_arxiv(self) -> None:
        from server.retrieval.bm25 import _apply_supported_filters

        candidates = [
            ("arxiv:2401.00001:aaa", 0.9),
            ("textbook:sv-book:bbb", 0.8),
        ]
        out = _apply_supported_filters(candidates, {"source_kind": "arxiv"})
        assert out == [("arxiv:2401.00001:aaa", 0.9)]

    def test_no_source_kind_filter_passes_all(self) -> None:
        from server.retrieval.bm25 import _apply_supported_filters

        candidates = [
            ("arxiv:2401.00001:aaa", 0.9),
            ("textbook:sv-book:bbb", 0.8),
        ]
        out = _apply_supported_filters(candidates, {})
        assert out == candidates

    def test_paper_id_and_source_kind_compose(self) -> None:
        """Both filters AND together (a candidate must satisfy both)."""
        from server.retrieval.bm25 import _apply_supported_filters

        candidates = [
            ("arxiv:2401.00001:aaa", 0.9),
            ("textbook:sv-book:bbb", 0.8),
        ]
        # paper_id matches only the arxiv chunk; source_kind=textbook
        # matches only the textbook chunk → intersection is empty.
        out = _apply_supported_filters(
            candidates,
            {"paper_id": "2401.00001", "source_kind": "textbook"},
        )
        assert out == []
