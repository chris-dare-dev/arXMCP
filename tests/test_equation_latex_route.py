"""retrieval-unlocks-m4 — LaTeX queries reach the TED+dense fusion lane.

Before m4, a LaTeX ``find_equation`` query could never reach the equation
index: routing keyed on ``looks_like_mathml``, so LaTeX fell through to a
dense ANN over ``embedding_stmt`` — statement prose, not equations. m4
converts the query to Presentation MathML with latex2mathml and feeds the
SAME ``EquationIndex.query`` lane MathML has always used.

Covers both milestone ACs:

* AC1 — a LaTeX query reaches the TED-fused route and reports it.
* AC2 — LaTeX that latex2mathml cannot parse falls back to dense-only and
  says so, rather than silently returning TED-fused results.

The cross-engine fidelity question (latex2mathml vs the LaTeXML that
built the corpus) is measured separately in
``tests/eval/test_equations_parity.py``.
"""

from __future__ import annotations

import pytest

import server.handlers.equation as eq_handler_mod
import server.tools as server_tools
from server.handlers.equation import _convert_latex_to_mathml
from server.retrieval.equations import (
    looks_like_mathml,
    parse_mathml_to_tree,
    tree_to_json,
)

from .test_equation_index import (  # reuse the built harness
    _build_chunks_table,
    _build_equations_table,
    _install_resources,
    _mock_encode_query,
    _read_fixture,
    _run,
)

_CHUNKS = [
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
]


def _seed(tmp_path):
    """Chunks + a two-equation table (an integral and a summation)."""
    chunks = _build_chunks_table(tmp_path, chunks=_CHUNKS)
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
                "mathml_tree_json": tree_to_json(
                    parse_mathml_to_tree(_read_fixture("int_ab_gtdt.mathml"))
                ),
            },
            {
                "equation_id": "arxiv:2401.00001:eq2",
                "paper_id": "2401.00001",
                "label": "(1.2)",
                "presentation_latex": r"\sum_{n=0}^\infty a_n",
                "mathml": _read_fixture("sum_0_inf_an.mathml"),
                "parent_chunk_id": "arxiv:2401.00001:0000000000000002",
                "mathml_tree_json": tree_to_json(
                    parse_mathml_to_tree(_read_fixture("sum_0_inf_an.mathml"))
                ),
            },
        ],
    )
    return chunks, equations


_UNSET = object()


def _call(latex, tmp_path, monkeypatch, *, table=True, route=True):
    chunks, equations = _seed(tmp_path)
    _install_resources(
        chunks,
        equations_table=equations if table else None,
        tmp_path=tmp_path,
    )
    _mock_encode_query(monkeypatch)
    from server.tools import get_resources

    # route is None -> leave the flag UNSET so the handler's getattr
    # default (production default: OFF) governs, exercising the real
    # default rather than an explicitly-forced value.
    if route is not None:
        get_resources().config.eq_latex_route = route
    try:
        return _run(
            eq_handler_mod.handle_find_equation(latex_or_mathml=latex, k=5)
        )
    finally:
        server_tools._RESOURCES = None


# ===========================================================================
# AC1 — LaTeX reaches the TED lane
# ===========================================================================


class TestLatexReachesTed:
    def test_latex_query_routes_to_ted_fused(self, tmp_path, monkeypatch):
        """The headline: LaTeX no longer dead-ends in dense-only."""
        out = _call(r"\int_0^1 f(x) dx", tmp_path, monkeypatch)
        assert out["retrieval_mode"] == "ted_fused"
        assert out["query_conversion"]["applied"] is True
        assert "latex2mathml" in out["query_conversion"]["converter"]

    def test_latex_ranks_the_structurally_matching_equation_first(
        self, tmp_path, monkeypatch
    ):
        """A LaTeX integral must rank the stored integral above the
        stored summation — the whole point of routing onto TED."""
        out = _call(r"\int_0^1 f(x) dx", tmp_path, monkeypatch)
        ids = [r["equation_id"] for r in out["results"]]
        assert ids[0] == "arxiv:2401.00001:eq1", ids

    def test_results_carry_ted_scores(self, tmp_path, monkeypatch):
        out = _call(r"\int_0^1 f(x) dx", tmp_path, monkeypatch)
        assert "ted_norm" in out["results"][0]


# ===========================================================================
# AC2 — honest fallback, never a silent TED claim
# ===========================================================================


class TestHonestFallback:
    @pytest.mark.parametrize("bad", [r"\bogus{{{", r"\frac{", "   "])
    def test_unconvertible_latex_falls_back_and_says_so(
        self, bad, tmp_path, monkeypatch
    ):
        out = _call(bad, tmp_path, monkeypatch)
        assert out["retrieval_mode"] == "dense_only_stmt_fallback"
        assert out["query_conversion"]["applied"] is False
        assert out["query_conversion"]["reason"]
        # The critical negative: never claim TED ran.
        assert "ted" not in out["retrieval_mode"]

    def test_degenerate_but_valid_latex_still_routes_to_ted(
        self, tmp_path, monkeypatch
    ):
        """latex2mathml is LENIENT: a bare backslash converts to a
        literal ``<mi>\\</mi>``, giving the same 3-node tree shape a
        legitimate single-symbol query (``x``, ``\\mathbb{C}``) produces.

        We deliberately do NOT guard on tree size. A minimum-size check
        would have to reject ``x`` to reject ``\\`` — they are
        structurally indistinguishable — and rejecting valid
        single-symbol queries is the worse error. Reporting
        ``ted_fused`` here is honest: TED really did run, and the hits
        really are the nearest stored trees. Garbage in, nearest
        neighbours out, truthfully labelled."""
        out = _call("\\", tmp_path, monkeypatch)
        assert out["retrieval_mode"] == "ted_fused"
        assert out["query_conversion"]["applied"] is True

    def test_config_default_is_off(self):
        """m4 ships default-OFF (adversarial-critique decision): the
        parity guard is CI-skipped and the route is latent, so it stays
        off until W1 flips it together with the tool description."""
        from server.config import Config

        assert Config().eq_latex_route is False

    def test_production_default_keeps_latex_dense_only(
        self, tmp_path, monkeypatch
    ):
        """With the flag UNSET (production default OFF), a LaTeX query
        must NOT reach TED — byte-identical to pre-m4, no conversion
        attempted."""
        out = _call(
            r"\int_0^1 f(x) dx", tmp_path, monkeypatch, route=None
        )
        assert out["retrieval_mode"] == "dense_only_stmt_fallback"
        assert "query_conversion" not in out

    def test_route_disabled_keeps_legacy_behaviour(
        self, tmp_path, monkeypatch
    ):
        """The explicit kill-switch must restore byte-identical pre-m4
        output — no query_conversion key at all, not an applied=False
        one."""
        out = _call(
            r"\int_0^1 f(x) dx", tmp_path, monkeypatch, route=False
        )
        assert out["retrieval_mode"] == "dense_only_stmt_fallback"
        assert "query_conversion" not in out

    def test_aligned_query_falls_back_honestly(self, tmp_path, monkeypatch):
        """latex2mathml leaks a raw & from an alignment tab, producing
        XML-invalid output that fails to parse. The result must be an
        honest dense fallback with applied=FALSE (not the applied=True
        the pre-rectification code reported) — TED did not run."""
        out = _call(
            r"\begin{aligned} a &= b \\ c &= d \end{aligned}",
            tmp_path, monkeypatch, route=True,
        )
        assert out["retrieval_mode"] == "dense_only_stmt_fallback"
        assert out["query_conversion"]["applied"] is False
        assert out["query_conversion"]["reason"] == "converter-output-unparseable"

    def test_no_equations_table_means_no_conversion_attempted(
        self, tmp_path, monkeypatch
    ):
        """Converting would be wasted work with nothing to match
        against, so the conversion must not even be attempted."""
        out = _call(
            r"\int_0^1 f(x) dx", tmp_path, monkeypatch, table=False
        )
        assert out["retrieval_mode"] == "dense_only_stmt_fallback"
        assert "query_conversion" not in out

    def test_mathml_input_is_untouched_by_m4(self, tmp_path, monkeypatch):
        """MathML callers must see exactly the pre-m4 response shape."""
        out = _call(
            _read_fixture("int_01_fxdx.mathml"), tmp_path, monkeypatch
        )
        assert out["retrieval_mode"] == "ted_fused"
        assert "query_conversion" not in out


# ===========================================================================
# The converter contract
# ===========================================================================


class TestConverter:
    def test_converter_never_raises_on_hostile_input(self):
        """latex2mathml is a third-party parser on caller-controlled
        input; every failure must become an honest fallback, never a
        500. (Input is separately bounded to 4000 chars by the handler
        Field, which bounds parse cost.)"""
        for junk in ["", "\\", "{" * 200, "\\begin{x}", "\x00", "\\\\" * 500]:
            mathml, conv = _convert_latex_to_mathml(junk)
            assert isinstance(conv, dict)
            assert conv["applied"] is (mathml is not None)

    def test_successful_conversion_is_parseable_mathml(self):
        """Whatever we hand the index must survive the same parse the
        index will run, or the route would just relocate the failure."""
        for latex in [r"\int_0^1 f(x)dx", r"\frac{a}{b}", "x+y", r"\mathbb{C}"]:
            mathml, conv = _convert_latex_to_mathml(latex)
            assert conv["applied"] is True, latex
            assert looks_like_mathml(mathml)
            parse_mathml_to_tree(mathml)  # must not raise

    def test_converter_version_is_recorded(self):
        """The pin is exact because output shape feeds a distance
        metric; the response records which build produced the tree."""
        _, conv = _convert_latex_to_mathml("x")
        assert "==" in conv["converter"]

    def test_converter_version_is_derived_not_hardcoded(self):
        """Provenance must track the INSTALLED build, so it can't drift
        from reality when the pin is bumped (the critique's finding). It
        must equal importlib.metadata, not a literal."""
        from importlib.metadata import version

        _, conv = _convert_latex_to_mathml("x")
        assert conv["converter"] == f"latex2mathml=={version('latex2mathml')}"
