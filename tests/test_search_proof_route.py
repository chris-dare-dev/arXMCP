"""retrieval-unlocks-m2 — opt-in proof-column route on search_papers.

``filters={'include_kinds': ['proof']}`` searches ``embedding_proof``
instead of ``embedding_stmt``, making proof bodies reachable for the
first time, and ``retrieval_mode``/``excluded_kinds`` describe the route
that actually ran rather than a hardcoded statement-route answer.

Covers m2's two ACs plus the sub-tasks:

* AC1 / t-include-kinds-filter + t-honest-retrieval-mode-proof
* AC2 — the default route is byte-for-byte unchanged
* t-per-notebook-ann-phase — per-notebook isolation of proof results.
  NOTE: search_papers does not route through ANNPhase at all (it calls
  ``search_table.search(...)`` directly on the already-notebook-resolved
  table), so the AC is verified on the mechanism that actually exists.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ingest.store import ALLOWED_KINDS
from server.handlers.search import (
    _EXCLUDED_KINDS_PROOF_ROUTE,
    _PROOF_COLUMN,
    _ROUTING_FILTER_KEYS,
    _STMT_COLUMN,
    SUPPORTED_FILTER_KEYS,
    _canonicalize_filters,
    handle_search_papers,
)


def _run(coro):
    return asyncio.run(coro)


class _FakeSearchBuilder:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.where_called: str | None = None

    def where(self, pred: str, **k: Any) -> _FakeSearchBuilder:
        self.where_called = pred
        return self

    def limit(self, n: int) -> _FakeSearchBuilder:
        return self

    def to_arrow(self):
        import pyarrow as pa

        cols = {
            "chunk_id": [r.get("chunk_id", "") for r in self._rows],
            "paper_id": [r.get("paper_id", "") for r in self._rows],
            "kind": [r.get("kind", "stmt") for r in self._rows],
            "body_text": [r.get("body_text", "b") for r in self._rows],
            "theorem_name": [None for _ in self._rows],
            "theorem_label": [None for _ in self._rows],
            "section_path": pa.array(
                [[] for _ in self._rows], type=pa.list_(pa.utf8())
            ),
            "_distance": [0.1 for _ in self._rows],
        }
        return pa.table(cols)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch):
    """Resources whose chunks_table records the vector column it was
    asked for — the single fact this milestone turns on."""
    from server.tools import reset_resources_for_tests, set_resources

    cap: dict[str, Any] = {"columns": [], "tables": []}

    class _Sem:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _Cfg:
        query_embed_provider = "local"
        result_byte_cap = 256 * 1024

    class _Info:
        version = 101

    class _Table:
        def __init__(self, name: str = "shared") -> None:
            self.name = name
            self._rows: list[dict[str, Any]] = []

        def set_rows(self, rows): self._rows = rows

        def search(self, query_vec, vector_column_name=None):
            cap["columns"].append(vector_column_name)
            cap["tables"].append(self.name)
            return _FakeSearchBuilder(self._rows)

    class _Res:
        def __init__(self) -> None:
            self.embed_semaphore = _Sem()
            self.config = _Cfg()
            self.degraded = None
            self.chunks_table = _Table("shared")
            self.corpus_info = _Info()

    res = _Res()
    set_resources(res)  # type: ignore[arg-type]
    monkeypatch.setattr("server.handlers.search.get_cache", lambda: None)

    async def _enc(query: str):
        import numpy as np
        return np.zeros(1024, dtype=np.float32)

    monkeypatch.setattr("server.handlers.search.encode_query", _enc)
    yield {"res": res, "cap": cap, "Table": _Table}
    reset_resources_for_tests()


def _payload(result):
    s = result.structuredContent
    return s.get("data", s)


# ===========================================================================
# AC1 — the proof route is selected and reported honestly
# ===========================================================================


class TestProofRoute:
    def test_include_kinds_proof_selects_the_proof_column(self, fake) -> None:
        _run(handle_search_papers(
            query="q", filters={"include_kinds": ["proof"]}, k=5,
        ))
        assert fake["cap"]["columns"] == [_PROOF_COLUMN]

    def test_retrieval_mode_names_the_proof_route(self, fake) -> None:
        out = _run(handle_search_papers(
            query="q", filters={"include_kinds": ["proof"]}, k=5,
        ))
        assert _payload(out)["retrieval_mode"] == "dense_only_proof_column"

    def test_excluded_kinds_omits_proof(self, fake) -> None:
        """The AC's exact wording. Reporting ['proof'] here -- the old
        hardcoded value -- would state the precise opposite of what the
        route did."""
        out = _run(handle_search_papers(
            query="q", filters={"include_kinds": ["proof"]}, k=5,
        ))
        excluded = _payload(out)["excluded_kinds"]
        assert "proof" not in excluded
        assert "stmt" in excluded and "lemma" in excluded

    def test_excluded_kinds_is_derived_from_the_write_time_enum(self) -> None:
        """Guard: a kind added to ingest.store cannot silently go
        unreported in the proof route's exclusion set."""
        assert set(_EXCLUDED_KINDS_PROOF_ROUTE) == ALLOWED_KINDS - {"proof"}

    def test_include_kinds_is_a_routing_key_not_a_filter(self) -> None:
        """It must not land in filters_applied (an applied-retrieval-
        filter view) nor in filter_warnings (an ignored-key view). It is
        recognized and consumed."""
        assert "include_kinds" in _ROUTING_FILTER_KEYS
        assert "include_kinds" not in SUPPORTED_FILTER_KEYS

    def test_no_spurious_filter_warning(self, fake) -> None:
        out = _run(handle_search_papers(
            query="q", filters={"include_kinds": ["proof"]}, k=5,
        ))
        warnings = _payload(out)["filter_warnings"]
        assert not any("include_kinds" in w for w in warnings), warnings

    def test_include_kinds_not_echoed_in_filters_applied(self, fake) -> None:
        out = _run(handle_search_papers(
            query="q", filters={"include_kinds": ["proof"]}, k=5,
        ))
        assert "include_kinds" not in _payload(out).get("filters_applied", {})

    def test_proof_and_stmt_get_distinct_cache_keys(self) -> None:
        """The cache is keyed on canonical_filters. include_kinds MUST
        survive canonicalization, or a statement query could be served a
        cached proof payload for the same text -- a silent correctness
        bug. This pins the load-bearing property directly."""
        proof_key = _canonicalize_filters({"include_kinds": ["proof"]})
        stmt_key = _canonicalize_filters(None)
        assert proof_key != stmt_key
        assert proof_key["include_kinds"] == ["proof"]


# ===========================================================================
# AC2 — the default route is untouched
# ===========================================================================


class TestDefaultRouteUnchanged:
    @pytest.mark.parametrize("filters", [None, {}, {"paper_id": ["2401.00001"]}])
    def test_default_still_searches_the_stmt_column(self, fake, filters) -> None:
        _run(handle_search_papers(query="q", filters=filters, k=5))
        assert fake["cap"]["columns"] == [_STMT_COLUMN]

    @pytest.mark.parametrize("filters", [None, {}])
    def test_default_mode_and_exclusions_unchanged(self, fake, filters) -> None:
        out = _run(handle_search_papers(query="q", filters=filters, k=5))
        p = _payload(out)
        assert p["retrieval_mode"] == "dense_only"
        assert p["excluded_kinds"] == ["proof"]


# ===========================================================================
# Rejected inputs — loud, never a silent fall-through
# ===========================================================================


class TestRejectedIncludeKinds:
    @pytest.mark.parametrize("value", [
        "proof",              # str instead of list -- the likely typo
        [],                   # empty list
        ["lemma"],            # a kind the column split cannot serve
        ["proof", "lemma"],   # partially supported
        ["Proof"],            # case-sensitive
        [123],                # non-str member
        [123, "proof"],       # MIXED types -- sorting these naively
        ["proof", None],      # raises TypeError, not ValueError
        {"kind": "proof"},    # wrong container
    ])
    def test_unsupported_values_raise(self, fake, value) -> None:
        """A caller who asked for proofs and silently received statements
        could not tell from the response, so these fail loudly rather
        than degrading to the default route."""
        with pytest.raises(ValueError):
            _run(handle_search_papers(
                query="q", filters={"include_kinds": value}, k=5,
            ))

    def test_rejection_happens_before_retrieval(self, fake) -> None:
        with pytest.raises(ValueError):
            _run(handle_search_papers(
                query="q", filters={"include_kinds": ["lemma"]}, k=5,
            ))
        assert fake["cap"]["columns"] == [], "no search should have run"

    def test_str_rejection_suggests_the_list_form(self, fake) -> None:
        with pytest.raises(ValueError, match=r"\['proof'\]"):
            _run(handle_search_papers(
                query="q", filters={"include_kinds": "proof"}, k=5,
            ))


# ===========================================================================
# Per-notebook isolation (t-per-notebook-ann-phase)
# ===========================================================================


class TestPerNotebookIsolation:
    def test_two_notebooks_in_sequence_use_their_own_tables(
        self, fake, monkeypatch
    ) -> None:
        """AC: each notebook's proof-column results come from its own
        corpus. search_papers resolves search_table per notebook BEFORE
        the vector search, so swapping the column cannot introduce a
        shared cross-notebook binding -- this pins that."""
        tables = {
            "nb-alpha": fake["Table"]("nb-alpha"),
            "nb-beta": fake["Table"]("nb-beta"),
        }

        class _Info:
            version = 202

        async def _notebook_table(slug: str):
            return tables[slug], _Info()

        fake["res"].notebook_table = _notebook_table

        for slug in ("nb-alpha", "nb-beta"):
            _run(handle_search_papers(
                query="q",
                filters={"notebook": slug, "include_kinds": ["proof"]},
                k=5,
            ))

        assert fake["cap"]["tables"] == ["nb-alpha", "nb-beta"]
        assert fake["cap"]["columns"] == [_PROOF_COLUMN, _PROOF_COLUMN]
        # And never the shared table.
        assert "shared" not in fake["cap"]["tables"]
