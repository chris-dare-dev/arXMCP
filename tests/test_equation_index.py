"""Tests for the equation TED + dense-cosine fusion index (E10_S03).

Covers:

* MathML parser — namespace stripping, attribute dropping, mixed
  text/element content, parse failures surface as ``ValueError``.
* JSON tree round-trip — ``tree_to_json`` → ``tree_from_json``
  reconstructs the same tree (TED of the round-tripped tree against
  itself is 0).
* Normalized TED — structurally identical integrals score lower
  than either against a structurally distinct summation; the
  brief's AC2 assertion.
* Fusion arithmetic — α=0 collapses to pure cosine; α=1 collapses
  to pure inverted-TED; α=0.5 produces an equal weighting.
* Handler — MathML input routes to ``ted_fused``; LaTeX input
  routes to ``dense_only_stmt_fallback``; missing equations table
  produces ``dense_only_fallback``; malformed MathML degrades
  gracefully.

The handler-level tests use a minimal Resources stub seeded with an
in-memory LanceDB chunks table + equations table; the full BGE-M3
stack is mocked so the test does not pay the model-load cost.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

import server.handlers.equation as eq_handler_mod
import server.tools as server_tools
from ingest.schema import (
    CHUNKS_SCHEMA_V1,
    EQUATIONS_SCHEMA_V1,
    EQUATIONS_TABLE_NAME,
)
from server.retrieval.equations import (
    EquationHit,
    EquationIndex,
    fuse_scores,
    looks_like_mathml,
    normalized_ted,
    parse_mathml_to_tree,
    tree_from_json,
    tree_size,
    tree_to_json,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "equations"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _run(coro):
    """Run an async coroutine inside a fresh event loop.

    Same pattern as ``tests/test_definitions_index.py::_run`` —
    ``asyncio.get_event_loop()`` is unsafe across the full test
    suite because prior tests may have closed it. A fresh loop per
    call is the canonical sync-into-async bridge for tests that
    don't use ``pytest-asyncio``.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@dataclass
class _MinimalConfig:
    lancedb_path: Path
    result_byte_cap: int = 256_000
    eq_ted_weight: float = 0.5


@dataclass
class _MinimalCorpus:
    version: int = 1


@dataclass
class _MinimalResources:
    config: _MinimalConfig
    corpus_info: _MinimalCorpus
    chunks_table: Any
    embed_semaphore: Any
    equations_table: Any | None = None


class _PassthroughSemaphore:
    """Stand-in for asyncio.Semaphore that supports the async
    context manager protocol without bounding concurrency.

    Pytest's typical lifecycle does not need real concurrency caps
    for these tests; we just need an awaitable context.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _install_resources(
    chunks_table: Any,
    equations_table: Any | None,
    tmp_path: Path,
    eq_ted_weight: float = 0.5,
) -> None:
    """Patch the live Resources singleton with a hand-built stub."""
    res = _MinimalResources(
        config=_MinimalConfig(
            lancedb_path=tmp_path,
            eq_ted_weight=eq_ted_weight,
        ),
        corpus_info=_MinimalCorpus(),
        chunks_table=chunks_table,
        embed_semaphore=_PassthroughSemaphore(),
        equations_table=equations_table,
    )
    server_tools._RESOURCES = res


def _mock_encode_query(monkeypatch, vector: np.ndarray | None = None) -> None:
    """Replace the real BGE-M3 encode_query with a constant vector
    returner so handler tests don't need the model.
    """
    if vector is None:
        # A unit vector along the first dim; arbitrary, but
        # deterministic. Matches CHUNKS_SCHEMA_V1's embedding_stmt
        # dimensionality (1024).
        from ingest.embedder import EMBEDDING_DIM

        vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        vector[0] = 1.0

    async def _fake(_query_text: str) -> np.ndarray:
        return vector

    monkeypatch.setattr(eq_handler_mod, "encode_query", _fake)


def _build_chunks_table(tmp_path: Path, chunks: list[dict[str, Any]]) -> Any:
    """Build a real LanceDB chunks table seeded with the given rows.

    Each ``chunks`` entry must carry the columns the test cares
    about: ``chunk_id``, ``paper_id``, ``kind``, ``section_path``,
    ``body_text``, ``body_tokens``, ``chunker_version``,
    ``embedder_version``. The embedding columns are filled with
    deterministic unit vectors so the ANN pass produces a stable
    ranking.
    """
    import lancedb

    from ingest.embedder import EMBEDDING_DIM

    rows: list[dict[str, Any]] = []
    for ch in chunks:
        row = {
            "chunk_id": ch["chunk_id"],
            "paper_id": ch["paper_id"],
            "kind": ch.get("kind", "section"),
            "section_path": ch.get("section_path", []),
            "theorem_name": ch.get("theorem_name"),
            "theorem_label": ch.get("theorem_label"),
            "body_text": ch.get("body_text", ""),
            "body_tokens": ch.get("body_tokens", ""),
            "embedding_stmt": ch.get(
                "embedding_stmt",
                _unit_vec(EMBEDDING_DIM, axis=ch.get("axis", 0)),
            ),
            "embedding_proof": ch.get("embedding_proof"),
            "embedding_eq": ch.get("embedding_eq"),
            "chunker_version": ch.get("chunker_version", "test"),
            "embedder_version": ch.get("embedder_version", "test"),
            "preamble_ref": ch.get("preamble_ref"),
        }
        rows.append(row)

    arrow_table = pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)
    db = lancedb.connect(str(tmp_path))
    return db.create_table("chunks", data=arrow_table)


def _build_equations_table(
    tmp_path: Path, equations: list[dict[str, Any]]
) -> Any:
    """Build a real LanceDB equations table seeded with the given rows."""
    import lancedb

    rows: list[dict[str, Any]] = []
    for eq in equations:
        rows.append(
            {
                "equation_id": eq["equation_id"],
                "paper_id": eq["paper_id"],
                "label": eq.get("label"),
                "presentation_latex": eq.get("presentation_latex", ""),
                "mathml": eq["mathml"],
                "ascii_form": eq.get("ascii_form"),
                "context_sentence": eq.get("context_sentence"),
                "parent_chunk_id": eq.get("parent_chunk_id"),
                "mathml_tree_json": eq.get("mathml_tree_json"),
                "embedding_eq": eq.get("embedding_eq"),
            }
        )
    arrow_table = pa.Table.from_pylist(rows, schema=EQUATIONS_SCHEMA_V1)
    db = lancedb.connect(str(tmp_path))
    if EQUATIONS_TABLE_NAME in db.table_names():  # noqa: SIM118 — deprecated but stable for tests
        db.drop_table(EQUATIONS_TABLE_NAME)
    return db.create_table(EQUATIONS_TABLE_NAME, data=arrow_table)


def _unit_vec(dim: int, axis: int = 0) -> list[float]:
    """Return a deterministic unit vector along ``axis``.

    Used to seed the dense embedding columns so the ANN pass produces
    a known ranking (rows with the same axis cluster together).
    """
    v = [0.0] * dim
    v[axis % dim] = 1.0
    return v


# ===========================================================================
# Parser tests
# ===========================================================================


class TestParseMathML:
    def test_simple_integral_parses(self):
        mathml = _read_fixture("int_01_fxdx.mathml")
        tree = parse_mathml_to_tree(mathml)
        assert tree.label == "math"
        assert tree_size(tree) > 5

    def test_strips_namespace_prefix(self):
        prefixed = (
            "<m:math xmlns:m='http://www.w3.org/1998/Math/MathML'>"
            "<m:mi>x</m:mi></m:math>"
        )
        plain = "<math><mi>x</mi></math>"
        t1 = parse_mathml_to_tree(prefixed)
        t2 = parse_mathml_to_tree(plain)
        # Same trees → TED is 0.
        assert normalized_ted(t1, t2) == 0.0

    def test_drops_attributes(self):
        with_attrs = (
            "<math display='block'><mi mathvariant='italic'>x</mi></math>"
        )
        without_attrs = "<math><mi>x</mi></math>"
        t1 = parse_mathml_to_tree(with_attrs)
        t2 = parse_mathml_to_tree(without_attrs)
        assert normalized_ted(t1, t2) == 0.0

    def test_uppercase_tags_normalize_to_lowercase(self):
        """F2 regression (E10_S03 critique) — ``looks_like_mathml``
        matches case-insensitively, so an uppercase MathML
        serialization must produce the same tree as the lowercase
        form (otherwise the TED score is non-zero for
        structurally-identical equations differing only in case).
        """
        upper = "<MATH><MI>x</MI></MATH>"
        lower = "<math><mi>x</mi></math>"
        assert normalized_ted(
            parse_mathml_to_tree(upper),
            parse_mathml_to_tree(lower),
        ) == 0.0

    def test_mixed_content_operators_distinguished(self):
        """F1 regression (E10_S03 critique) — tail-text inside mixed-
        content MathML must NOT be dropped. ``<mrow><mi>x</mi> + <mi>y</mi></mrow>``
        and ``<mrow><mi>x</mi> - <mi>y</mi></mrow>`` differ by a
        single operator that lives as tail-text on the first child;
        the previous implementation silently conflated them.
        """
        plus = parse_mathml_to_tree(
            "<math><mrow><mi>x</mi> + <mi>y</mi></mrow></math>"
        )
        minus = parse_mathml_to_tree(
            "<math><mrow><mi>x</mi> - <mi>y</mi></mrow></math>"
        )
        adj = parse_mathml_to_tree(
            "<math><mrow><mi>x</mi><mi>y</mi></mrow></math>"
        )
        # All three are structurally distinguishable now.
        assert normalized_ted(plus, minus) > 0.0
        assert normalized_ted(plus, adj) > 0.0
        assert normalized_ted(minus, adj) > 0.0

    def test_text_content_distinguishes_mi_elements(self):
        x = parse_mathml_to_tree("<math><mi>x</mi></math>")
        y = parse_mathml_to_tree("<math><mi>y</mi></math>")
        # Different text → different leaf nodes → non-zero TED.
        assert normalized_ted(x, y) > 0.0

    def test_malformed_raises_value_error(self):
        with pytest.raises(ValueError, match="malformed MathML"):
            parse_mathml_to_tree("<math><mi>x</mi>")  # missing close tag

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_mathml_to_tree("")


class TestLooksLikeMathML:
    def test_simple_mathml(self):
        assert looks_like_mathml("<math><mi>x</mi></math>")

    def test_whitespace_prefix(self):
        assert looks_like_mathml("\n  <math><mi>x</mi></math>")

    def test_namespace_prefix(self):
        assert looks_like_mathml(
            "<m:math xmlns:m='ns'><m:mi>x</m:mi></m:math>"
        )

    def test_latex_is_not_mathml(self):
        assert not looks_like_mathml(r"\int_0^1 f(x) dx")

    def test_empty_is_not_mathml(self):
        assert not looks_like_mathml("")


# ===========================================================================
# Tree JSON round-trip
# ===========================================================================


class TestTreeJSONRoundTrip:
    def test_simple_round_trip(self):
        original = parse_mathml_to_tree(_read_fixture("int_01_fxdx.mathml"))
        payload = tree_to_json(original)
        rebuilt = tree_from_json(payload)
        # Round-trip is structurally identical (TED is 0).
        assert normalized_ted(original, rebuilt) == 0.0

    def test_payload_is_deterministic(self):
        # Same tree → same JSON bytes (sorted keys + no whitespace).
        t1 = parse_mathml_to_tree("<math><mi>a</mi></math>")
        t2 = parse_mathml_to_tree("<math><mi>a</mi></math>")
        assert tree_to_json(t1) == tree_to_json(t2)

    def test_rejects_missing_label(self):
        with pytest.raises(ValueError, match="'label'"):
            tree_from_json(json.dumps({"children": []}))

    def test_rejects_non_string_label(self):
        with pytest.raises(ValueError, match="'label' must be a string"):
            tree_from_json(json.dumps({"label": 42, "children": []}))


# ===========================================================================
# Normalized TED + fusion
# ===========================================================================


class TestNormalizedTED:
    def test_identical_trees_score_zero(self):
        t = parse_mathml_to_tree(_read_fixture("int_01_fxdx.mathml"))
        assert normalized_ted(t, t) == 0.0

    def test_two_integrals_closer_than_integral_vs_sum(self):
        """AC2: TED between ``\\int_0^1 f(x) dx`` and
        ``\\int_a^b g(t) dt`` is lower than between either and
        ``\\sum_{n=0}^\\infty a_n``.
        """
        int_fx = parse_mathml_to_tree(_read_fixture("int_01_fxdx.mathml"))
        int_gt = parse_mathml_to_tree(_read_fixture("int_ab_gtdt.mathml"))
        sum_an = parse_mathml_to_tree(_read_fixture("sum_0_inf_an.mathml"))

        d_int_int = normalized_ted(int_fx, int_gt)
        d_int_sum = normalized_ted(int_fx, sum_an)
        d_int_sum_other = normalized_ted(int_gt, sum_an)

        assert d_int_int < d_int_sum
        assert d_int_int < d_int_sum_other

    def test_range_is_unit_interval(self):
        a = parse_mathml_to_tree("<math><mi>x</mi></math>")
        b = parse_mathml_to_tree(
            "<math><mfrac><mi>a</mi><mi>b</mi></mfrac></math>"
        )
        d = normalized_ted(a, b)
        assert 0.0 <= d <= 1.0


class TestFuseScores:
    def test_alpha_one_collapses_to_ted_only(self):
        # alpha=1 → final = 1 - normalized_ted (cosine ignored).
        assert fuse_scores(ted_norm=0.0, cosine_score=0.0, alpha=1.0) == 1.0
        assert fuse_scores(ted_norm=0.4, cosine_score=0.9, alpha=1.0) == pytest.approx(0.6)

    def test_alpha_zero_collapses_to_cosine_only(self):
        # alpha=0 → final = cosine (TED ignored).
        assert fuse_scores(ted_norm=0.0, cosine_score=0.42, alpha=0.0) == 0.42
        assert fuse_scores(ted_norm=0.9, cosine_score=0.7, alpha=0.0) == 0.7

    def test_alpha_half_averages(self):
        # alpha=0.5 → equal weights.
        v = fuse_scores(ted_norm=0.2, cosine_score=0.6, alpha=0.5)
        # final = 0.5 * (1 - 0.2) + 0.5 * 0.6 = 0.4 + 0.3 = 0.7
        assert v == pytest.approx(0.7)

    def test_alpha_out_of_range_raises(self):
        with pytest.raises(ValueError, match=r"alpha must be in"):
            fuse_scores(0.0, 0.0, alpha=1.1)
        with pytest.raises(ValueError, match=r"alpha must be in"):
            fuse_scores(0.0, 0.0, alpha=-0.5)


# ===========================================================================
# Handler dispatch
# ===========================================================================


class TestHandlerDispatch:
    def test_latex_input_dense_only_stmt_fallback(self, tmp_path, monkeypatch):
        chunks = _build_chunks_table(
            tmp_path,
            chunks=[
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "kind": "section",
                    "section_path": [],
                    "body_text": "An integral over [0, 1]",
                    "body_tokens": "integral",
                    "axis": 0,
                }
            ],
        )
        _install_resources(chunks, equations_table=None, tmp_path=tmp_path)
        _mock_encode_query(monkeypatch)
        try:
            result = _run(
                eq_handler_mod.handle_find_equation(
                    latex_or_mathml=r"\int_0^1 f(x) dx", k=3
                )
            )
        finally:
            server_tools._RESOURCES = None
        assert result["retrieval_mode"] == "dense_only_stmt_fallback"

    def test_mathml_input_without_table_falls_back(self, tmp_path, monkeypatch):
        chunks = _build_chunks_table(
            tmp_path,
            chunks=[
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "kind": "section",
                    "section_path": [],
                    "body_text": "An integral",
                    "body_tokens": "integral",
                }
            ],
        )
        _install_resources(chunks, equations_table=None, tmp_path=tmp_path)
        _mock_encode_query(monkeypatch)
        mathml = _read_fixture("int_01_fxdx.mathml")
        try:
            result = _run(
                eq_handler_mod.handle_find_equation(
                    latex_or_mathml=mathml, k=3
                )
            )
        finally:
            server_tools._RESOURCES = None
        # AC4: MathML input but no equations table → dense_only_fallback.
        assert result["retrieval_mode"] == "dense_only_fallback"

    def test_mathml_input_with_populated_table_routes_to_ted_fused(
        self, tmp_path, monkeypatch
    ):
        # Seed the chunks table with two chunks (axis 0 and axis 1)
        # so the ANN pass returns deterministic candidates.
        chunks = _build_chunks_table(
            tmp_path,
            chunks=[
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "kind": "section",
                    "section_path": [],
                    "body_text": "Defining the integral",
                    "body_tokens": "integral",
                    "axis": 0,
                },
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000002",
                    "paper_id": "2401.00001",
                    "kind": "section",
                    "section_path": [],
                    "body_text": "Defining the summation",
                    "body_tokens": "sum",
                    "axis": 1,
                },
            ],
        )
        # Pre-compute the tree JSON for two equations and seed the
        # equations table.
        int_tree = tree_to_json(
            parse_mathml_to_tree(_read_fixture("int_ab_gtdt.mathml"))
        )
        sum_tree = tree_to_json(
            parse_mathml_to_tree(_read_fixture("sum_0_inf_an.mathml"))
        )
        equations = _build_equations_table(
            tmp_path,
            equations=[
                {
                    "equation_id": "arxiv:2401.00001:eq1",
                    "paper_id": "2401.00001",
                    "label": "(1.1)",
                    "presentation_latex": r"\int_a^b g(t) dt",
                    "mathml": _read_fixture("int_ab_gtdt.mathml"),
                    "parent_chunk_id": "arxiv:2401.00001:0000000000000001",
                    "mathml_tree_json": int_tree,
                },
                {
                    "equation_id": "arxiv:2401.00001:eq2",
                    "paper_id": "2401.00001",
                    "label": "(1.2)",
                    "presentation_latex": r"\sum_{n=0}^\infty a_n",
                    "mathml": _read_fixture("sum_0_inf_an.mathml"),
                    "parent_chunk_id": "arxiv:2401.00001:0000000000000002",
                    "mathml_tree_json": sum_tree,
                },
            ],
        )
        _install_resources(chunks, equations_table=equations, tmp_path=tmp_path)
        _mock_encode_query(monkeypatch)
        # Query with the integral fixture → structural match should
        # rank the integral equation above the summation.
        query_mathml = _read_fixture("int_01_fxdx.mathml")
        try:
            result = _run(
                eq_handler_mod.handle_find_equation(
                    latex_or_mathml=query_mathml, k=5
                )
            )
        finally:
            server_tools._RESOURCES = None
        assert result["retrieval_mode"] == "ted_fused"
        # AC1: structurally similar integral appears in top-3.
        top_eq_ids = [r["equation_id"] for r in result["results"][:3]]
        assert "arxiv:2401.00001:eq1" in top_eq_ids
        # AC: integral ranks above summation.
        eq1_pos = next(
            i for i, r in enumerate(result["results"]) if r["equation_id"] == "arxiv:2401.00001:eq1"
        )
        eq2_pos = next(
            i for i, r in enumerate(result["results"]) if r["equation_id"] == "arxiv:2401.00001:eq2"
        )
        assert eq1_pos < eq2_pos

    def test_latex_input_returns_integral_chunk_in_top3(
        self, tmp_path, monkeypatch
    ):
        """F3 regression (E10_S03 critique) — AC1 of the brief is
        literally about a LaTeX input ``\\int_0^1 f(x) dx``. The
        handler routes LaTeX to ``dense_only_stmt_fallback``; this
        test pins the actual AC1 behavior end-to-end (even though
        the path does not exercise TED).

        Seeds the chunks table so the integral chunk sits along
        axis 0 (matching the mocked encode_query unit vector) and
        the summation chunk sits along axis 1. The ANN pass should
        rank the integral above the summation.
        """
        chunks = _build_chunks_table(
            tmp_path,
            chunks=[
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "kind": "section",
                    "section_path": [],
                    "body_text": "An integral over [0, 1]",
                    "body_tokens": "integral",
                    "axis": 0,
                },
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000002",
                    "paper_id": "2401.00001",
                    "kind": "section",
                    "section_path": [],
                    "body_text": "A summation",
                    "body_tokens": "sum",
                    "axis": 1,
                },
            ],
        )
        _install_resources(chunks, equations_table=None, tmp_path=tmp_path)
        _mock_encode_query(monkeypatch)
        try:
            result = _run(
                eq_handler_mod.handle_find_equation(
                    latex_or_mathml=r"\int_0^1 f(x) dx", k=3
                )
            )
        finally:
            server_tools._RESOURCES = None
        assert result["retrieval_mode"] == "dense_only_stmt_fallback"
        top_chunk_ids = [r["chunk_id"] for r in result["results"][:3]]
        # Integral chunk (axis 0) must appear in the top-3 because
        # the mocked encode_query vector is also axis 0.
        assert "arxiv:2401.00001:0000000000000001" in top_chunk_ids

    def test_all_null_trees_falls_through_to_dense_only_fallback(
        self, tmp_path, monkeypatch
    ):
        """F4 regression (E10_S03 critique) — when the equations
        table is populated but every candidate's mathml_tree_json is
        NULL, the TED-fusion path produces degenerate results
        (ted_norm=1.0 on every row) and the retrieval_mode tag of
        ``ted_fused`` would mislead callers. The handler must fall
        back to ``dense_only_fallback`` in this case.
        """
        chunks = _build_chunks_table(
            tmp_path,
            chunks=[
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "kind": "section",
                    "section_path": [],
                    "body_text": "An integral",
                    "body_tokens": "integral",
                    "axis": 0,
                }
            ],
        )
        # Equation row with mathml but NO mathml_tree_json (NULL).
        equations = _build_equations_table(
            tmp_path,
            equations=[
                {
                    "equation_id": "arxiv:2401.00001:eq1",
                    "paper_id": "2401.00001",
                    "presentation_latex": r"\int_0^1 f(x) dx",
                    "mathml": _read_fixture("int_01_fxdx.mathml"),
                    "parent_chunk_id": "arxiv:2401.00001:0000000000000001",
                    # mathml_tree_json deliberately omitted → NULL.
                }
            ],
        )
        _install_resources(chunks, equations_table=equations, tmp_path=tmp_path)
        _mock_encode_query(monkeypatch)
        query_mathml = _read_fixture("int_01_fxdx.mathml")
        try:
            result = _run(
                eq_handler_mod.handle_find_equation(
                    latex_or_mathml=query_mathml, k=3
                )
            )
        finally:
            server_tools._RESOURCES = None
        # AC4 — every row's tree was NULL, so the TED path cannot
        # contribute; fall back to dense_only_fallback.
        assert result["retrieval_mode"] == "dense_only_fallback"

    def test_ted_fused_eq_mode_when_embedding_eq_populated(
        self, tmp_path, monkeypatch
    ):
        """E10_S03b path — when embedding_eq is non-NULL on at
        least one row, EquationIndex queries it directly and the
        envelope reports ``retrieval_mode="ted_fused_eq"``. The
        chunks-proxy path is bypassed.
        """
        from ingest.embedder import EMBEDDING_DIM

        # Seed a chunks table with a single irrelevant chunk so the
        # ANN setup is plausible; the dense pass should NEVER touch
        # the chunks table on the embedding_eq path.
        chunks = _build_chunks_table(
            tmp_path,
            chunks=[
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "kind": "section",
                    "section_path": [],
                    "body_text": "irrelevant",
                    "body_tokens": "irrelevant",
                }
            ],
        )

        # Two equation rows with synthetic L2-normalized embedding_eq
        # vectors along distinct unit axes — the query vector (axis 0)
        # ranks eq1 (axis 0) above eq2 (axis 1).
        v_axis_0 = _unit_vec(EMBEDDING_DIM, axis=0)
        v_axis_1 = _unit_vec(EMBEDDING_DIM, axis=1)
        int_tree = tree_to_json(
            parse_mathml_to_tree(_read_fixture("int_ab_gtdt.mathml"))
        )
        sum_tree = tree_to_json(
            parse_mathml_to_tree(_read_fixture("sum_0_inf_an.mathml"))
        )
        equations = _build_equations_table(
            tmp_path,
            equations=[
                {
                    "equation_id": "arxiv:2401.00001:eq1",
                    "paper_id": "2401.00001",
                    "label": "E1",
                    "presentation_latex": r"\int_a^b g(t) dt",
                    "mathml": _read_fixture("int_ab_gtdt.mathml"),
                    "mathml_tree_json": int_tree,
                    "embedding_eq": v_axis_0,
                },
                {
                    "equation_id": "arxiv:2401.00001:eq2",
                    "paper_id": "2401.00001",
                    "label": "E2",
                    "presentation_latex": r"\sum_{n=0}^\infty a_n",
                    "mathml": _read_fixture("sum_0_inf_an.mathml"),
                    "mathml_tree_json": sum_tree,
                    "embedding_eq": v_axis_1,
                },
            ],
        )
        _install_resources(chunks, equations_table=equations, tmp_path=tmp_path)
        _mock_encode_query(monkeypatch)  # query_vec is axis 0
        query_mathml = _read_fixture("int_01_fxdx.mathml")
        try:
            result = _run(
                eq_handler_mod.handle_find_equation(
                    latex_or_mathml=query_mathml, k=5
                )
            )
        finally:
            server_tools._RESOURCES = None
        # The new dense path fired.
        assert result["retrieval_mode"] == "ted_fused_eq"
        # eq1 (axis 0 — matches query_vec) ranks above eq2 (axis 1).
        eq_ids = [r["equation_id"] for r in result["results"]]
        assert eq_ids.index("arxiv:2401.00001:eq1") < eq_ids.index(
            "arxiv:2401.00001:eq2"
        )

    def test_malformed_mathml_degrades_gracefully(
        self, tmp_path, monkeypatch
    ):
        chunks = _build_chunks_table(
            tmp_path,
            chunks=[
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "kind": "section",
                    "section_path": [],
                    "body_text": "An integral",
                    "body_tokens": "integral",
                }
            ],
        )
        equations = _build_equations_table(
            tmp_path,
            equations=[
                {
                    "equation_id": "arxiv:2401.00001:eq1",
                    "paper_id": "2401.00001",
                    "presentation_latex": "",
                    "mathml": "<math><mi>x</mi></math>",
                    "mathml_tree_json": tree_to_json(
                        parse_mathml_to_tree("<math><mi>x</mi></math>")
                    ),
                    "parent_chunk_id": "arxiv:2401.00001:0000000000000001",
                }
            ],
        )
        _install_resources(chunks, equations_table=equations, tmp_path=tmp_path)
        _mock_encode_query(monkeypatch)
        try:
            result = _run(
                eq_handler_mod.handle_find_equation(
                    latex_or_mathml="<math><mi>x</mi>",  # missing close tag
                    k=3,
                )
            )
        finally:
            server_tools._RESOURCES = None
        # Looks like MathML (has <math) but parse fails → degrade.
        assert result["retrieval_mode"] == "malformed_mathml_fallback"


# ===========================================================================
# EquationIndex unit tests
# ===========================================================================


class TestEquationIndex:
    def test_alpha_out_of_range_raises(self):
        with pytest.raises(ValueError, match="alpha must be in"):
            EquationIndex(equations_table=None, chunks_table=None, alpha=1.5)

    def test_available_false_when_table_none(self):
        idx = EquationIndex(equations_table=None, chunks_table=None)
        assert not idx.available

    def test_query_returns_empty_when_unavailable(self):
        idx = EquationIndex(equations_table=None, chunks_table=None)
        result = idx.query("<math/>", query_vec=[0.0], k=5)
        assert result == []


# ===========================================================================
# Hit dataclass
# ===========================================================================


class TestEquationHit:
    def test_field_shape(self):
        h = EquationHit(
            equation_id="x",
            paper_id="p",
            chunk_id="c",
            cosine_score=0.5,
            ted_norm=0.1,
            final_score=0.7,
        )
        assert h.equation_id == "x"
        assert h.cosine_score == 0.5
        assert h.ted_norm == 0.1
        assert h.final_score == 0.7
