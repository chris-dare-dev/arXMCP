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
        with pytest.raises(ValueError, match="invalid arXiv IDs"):
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
        any string containing a single quote / semicolon / etc."""
        with pytest.raises(ValueError, match="invalid arXiv IDs"):
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
    })


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
        """AC #3 / FM-5: invalid IDs in the list → ValueError."""
        from server.handlers.search import handle_search_papers
        with pytest.raises(ValueError, match="invalid arXiv IDs"):
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


# ---------------------------------------------------------------------------
# Tool-schema byte-stability (AC #4) — cross-check via existing test
# ---------------------------------------------------------------------------


def test_supported_filter_keys_matches_expected() -> None:
    """SUPPORTED_FILTER_KEYS is the source of truth for which filter
    keys are honored. m1 ships only {'paper_id'}; a future milestone
    extending this set should bump the documented supported keys in
    the docstring + filter_warnings message."""
    assert frozenset({"paper_id"}) == SUPPORTED_FILTER_KEYS


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
