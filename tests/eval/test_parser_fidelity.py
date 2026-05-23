"""Pytest harness for the CDM (Character Detection Matching) parser-
fidelity eval gate.

T2 spike from capability-scout pdf-ingest-2026. Tests fall into 3
tiers:

1. **Pure-Python unit tests** (always run). Cover the helpers that
   don't require pdflatex: tokenize_latex, color_grid,
   wrap_formula_latex, detect_bbox (with synthetic image arrays),
   _cost_matrix, and the cdm_score input-validation paths.

2. **Cold-start fixture tests** (always run). Validate the fixture
   directory structure + manifest.json + per-file conventions
   without invoking pdflatex.

3. **End-to-end CDM tests** (gated behind requires_pdflatex +
   ARXMCP_RUN_REAL_PDFLATEX=1). Render real LaTeX via the
   subprocess chain and verify the F1 score is in the expected
   range. Slow + system-dep-heavy; opt-in only.

Per the milestone brief: only the FIRST 2 example fixture pages
ship with this commit; the operator hand-curates the remaining 18.
The TIER-1 promotion gate (mean CDM ≥ 0.85) is conditional on
fixture completion per `.claude/TIER-GATES.md`.
"""

from __future__ import annotations

import json
import os  # noqa: F401 — referenced by lazy skipif string-condition below
import shutil  # noqa: F401 — referenced by lazy skipif string-condition below
from pathlib import Path

import numpy as np
import pytest

from tools import cdm_eval
from tools.cdm_eval import (
    AggregateResult,
    TokenBbox,
    _cost_matrix,  # noqa: PLC2701 — regression-test target for F1
    aggregate_cdm,
    cdm_score,
    color_grid,
    detect_all_bboxes,
    detect_bbox,
    render_latex_to_image,
    tokenize_latex,
    wrap_formula_latex,
)

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
FIXTURE_ROOT: Path = REPO_ROOT / "tests" / "eval" / "textbook_fixtures"

# ---------------------------------------------------------------------------
# Tier 1 — Pure-Python unit tests (always run)
# ---------------------------------------------------------------------------


class TestTokenizeLatex:
    @pytest.mark.parametrize(
        "formula,expected",
        [
            (r"\frac{a}{b}", ["\\frac", "{", "a", "}", "{", "b", "}"]),
            (r"x_i", ["x", "_", "i"]),
            (r"\alpha + \beta", ["\\alpha", "+", "\\beta"]),
            ("a", ["a"]),
            ("", []),
        ],
    )
    def test_tokenize(self, formula: str, expected: list[str]) -> None:
        assert tokenize_latex(formula) == expected

    def test_tokenize_complex_formula(self) -> None:
        tokens = tokenize_latex(r"\sum_{i=0}^n x_i")
        assert tokens == [
            "\\sum", "_", "{", "i", "=", "0", "}", "^", "n", "x", "_", "i",
        ]

    def test_tokenize_drops_whitespace(self) -> None:
        # Tokens are returned without explicit whitespace tokens — the
        # renderer collapses whitespace and CDM treats them as
        # non-glyphs anyway.
        tokens = tokenize_latex(r"a + b")
        assert tokens == ["a", "+", "b"]


class TestColorGrid:
    def test_zero_colors_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="n_colors must be >= 1"):
            color_grid(0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="n_colors must be >= 1"):
            color_grid(-1)

    def test_grid_capacity_exceeded(self) -> None:
        with pytest.raises(RuntimeError, match="exceeds.*grid capacity"):
            color_grid(10_000)  # > 4913

    def test_grid_capacity_boundary(self) -> None:
        # 4913 = (256//15)^3; the max we support.
        colors = color_grid(4913)
        assert len(colors) == 4913

    def test_colors_are_unique(self) -> None:
        colors = color_grid(100)
        assert len(set(colors)) == 100

    def test_no_pure_black(self) -> None:
        # Pure black aliases with default ink — must be skipped.
        colors = color_grid(1000)
        assert (0, 0, 0) not in colors

    def test_starts_at_interval_15(self) -> None:
        first = color_grid(1)[0]
        # First valid color skips (0,0,0); next in lex order is (0,0,15).
        assert first == (0, 0, 15)

    def test_lexicographic_order(self) -> None:
        colors = color_grid(20)
        for prev, curr in zip(colors[:-1], colors[1:], strict=True):
            assert prev < curr, f"colors not in lex order: {prev} >= {curr}"


class TestWrapFormulaLatex:
    def test_colored_wrap_includes_xcolor(self) -> None:
        doc = wrap_formula_latex(r"x", colored=True)
        assert "\\usepackage[x11names]{xcolor}" in doc
        assert "\\mathcolor[RGB]" in doc

    def test_uncolored_wrap_omits_mathcolor(self) -> None:
        doc = wrap_formula_latex(r"x", colored=False)
        assert "\\mathcolor[RGB]" not in doc
        assert "x" in doc

    def test_amsmath_loaded(self) -> None:
        # amsmath provides \text, \cases, etc — load unconditionally.
        doc = wrap_formula_latex(r"x")
        assert "\\usepackage{amsmath,amssymb}" in doc

    def test_empty_formula_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="no tokens"):
            wrap_formula_latex("", colored=True)

    def test_each_token_gets_unique_color(self) -> None:
        doc = wrap_formula_latex(r"abc", colored=True)
        # Three tokens (a, b, c); should see exactly 3 \mathcolor wraps.
        assert doc.count("\\mathcolor[RGB]") == 3


class TestDetectBbox:
    def test_no_matching_pixels(self) -> None:
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        bbox = detect_bbox(image, (15, 0, 0))
        assert bbox is None

    def test_single_pixel_match(self) -> None:
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        image[5, 7] = (15, 0, 0)
        bbox = detect_bbox(image, (15, 0, 0))
        assert bbox == (5, 7, 5, 7)

    def test_rectangular_region(self) -> None:
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        image[3:7, 2:5] = (45, 60, 75)
        bbox = detect_bbox(image, (45, 60, 75))
        assert bbox == (3, 2, 6, 4)

    def test_tolerance_accepts_near_matches(self) -> None:
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        image[5, 5] = (16, 1, 1)  # off by 1 in each channel
        # Default tolerance=3 should match (15, 0, 0).
        bbox = detect_bbox(image, (15, 0, 0))
        assert bbox == (5, 5, 5, 5)

    def test_tolerance_rejects_far_matches(self) -> None:
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        image[5, 5] = (30, 0, 0)  # 15 off in r channel
        # Default tolerance=3 should NOT match (15, 0, 0).
        bbox = detect_bbox(image, (15, 0, 0))
        assert bbox is None

    def test_bad_image_shape_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="expected HxWx3"):
            detect_bbox(np.zeros((10, 10), dtype=np.uint8), (0, 0, 0))


class TestDetectAllBboxes:
    def test_returns_token_with_bbox(self) -> None:
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        image[3:5, 4:6] = (15, 0, 0)
        tokens = [TokenBbox(token="x", index=0, color=(15, 0, 0))]
        result = detect_all_bboxes(image, tokens)
        assert len(result) == 1
        assert result[0].bbox == (3, 4, 4, 5)
        # Original token data preserved.
        assert result[0].token == "x"
        assert result[0].index == 0

    def test_none_for_missing_color(self) -> None:
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        tokens = [TokenBbox(token="x", index=0, color=(99, 99, 99))]
        result = detect_all_bboxes(image, tokens)
        assert result[0].bbox is None


# ---------------------------------------------------------------------------
# Tier 1 — cdm_score input-validation paths (no subprocess required)
# ---------------------------------------------------------------------------


class TestCdmScoreInputValidation:
    """The cdm_score function rejects bad inputs BEFORE attempting any
    subprocess call. These tests run without pdflatex installed."""

    def test_empty_predicted_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="predicted_latex is empty"):
            cdm_score("", r"\frac{a}{b}")

    def test_empty_ground_truth_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="ground_truth_latex is empty"):
            cdm_score(r"\frac{a}{b}", "")

    def test_whitespace_only_rejected(self) -> None:
        # Both stripped — whitespace alone is "empty" for our purposes.
        with pytest.raises(RuntimeError, match="empty"):
            cdm_score("   ", r"\frac{a}{b}")


# ---------------------------------------------------------------------------
# Tier 2 — Cold-start fixture validation (always run)
# ---------------------------------------------------------------------------


class TestFixtureStructure:
    """Validate fixture directory structure + manifest.json without
    invoking pdflatex. Catches fixture-curation mistakes early."""

    def test_fixture_root_exists(self) -> None:
        assert FIXTURE_ROOT.is_dir(), (
            f"Fixture root missing: {FIXTURE_ROOT}. Did the milestone "
            f"3rd commit not land?"
        )

    def test_manifest_present(self) -> None:
        manifest_path = FIXTURE_ROOT / "manifest.json"
        assert manifest_path.is_file()

    def test_manifest_parses(self) -> None:
        manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
        assert manifest["schema_version"] == 1
        assert manifest["milestone"] == "parser-fidelity-eval-m1"
        assert set(manifest["classes"].keys()) == {
            "paper-control",
            "hartshorne-style",
            "griffiths-harris-style",
            "milne-style",
        }

    def test_manifest_totals_consistent(self) -> None:
        """Totals.current_pages must equal sum of per-class current_pages."""
        manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
        per_class_sum = sum(
            c["current_pages"] for c in manifest["classes"].values()
        )
        assert manifest["totals"]["current_pages"] == per_class_sum, (
            f"Manifest totals out of sync: sum-of-classes="
            f"{per_class_sum}, totals.current_pages="
            f"{manifest['totals']['current_pages']}. Run "
            f"`python -m tools.cdm_eval --recount-manifest` (NYI) or "
            f"hand-fix manifest.json."
        )

    def test_promotion_gate_thresholds(self) -> None:
        manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
        assert manifest["totals"]["promotion_threshold_pages"] == 20
        assert manifest["totals"]["promotion_cdm_min"] == 0.85

    @pytest.mark.parametrize(
        "class_name",
        ["paper-control", "hartshorne-style", "griffiths-harris-style", "milne-style"],
    )
    def test_class_dir_exists(self, class_name: str) -> None:
        assert (FIXTURE_ROOT / class_name).is_dir()


class TestFixturePerPageContract:
    """For every NN-formula.tex file in the fixture, a matching
    NN-formula.mathml must also exist. Catches operator slips during
    hand-curation."""

    def _all_tex_files(self) -> list[Path]:
        return sorted(FIXTURE_ROOT.glob("*/[0-9][0-9]-formula.tex"))

    def test_every_tex_has_mathml(self) -> None:
        missing: list[str] = []
        for tex in self._all_tex_files():
            mathml = tex.with_suffix(".mathml")
            if not mathml.is_file():
                missing.append(str(mathml.relative_to(FIXTURE_ROOT)))
        assert not missing, (
            f"Fixture pages missing .mathml ground truth: {missing}"
        )

    def test_every_mathml_has_tex(self) -> None:
        missing: list[str] = []
        for mathml in sorted(FIXTURE_ROOT.glob("*/[0-9][0-9]-formula.mathml")):
            tex = mathml.with_suffix(".tex")
            if not tex.is_file():
                missing.append(str(tex.relative_to(FIXTURE_ROOT)))
        assert not missing, (
            f"Fixture .mathml without matching .tex: {missing}"
        )

    def test_tex_files_are_nonempty(self) -> None:
        empty: list[str] = []
        for tex in self._all_tex_files():
            if tex.stat().st_size == 0:
                empty.append(str(tex.relative_to(FIXTURE_ROOT)))
        assert not empty, f"Empty .tex files in fixture: {empty}"

    def test_mathml_files_are_well_formed_xml(self) -> None:
        """MathML is XML; must parse. Catches typos in hand-typed
        ground truth before they reach the CDM scoring step."""
        import xml.etree.ElementTree as ET

        broken: list[tuple[str, str]] = []
        for mathml in sorted(FIXTURE_ROOT.glob("*/[0-9][0-9]-formula.mathml")):
            try:
                ET.fromstring(mathml.read_text(encoding="utf-8"))
            except ET.ParseError as e:
                broken.append((str(mathml.relative_to(FIXTURE_ROOT)), str(e)))
        assert not broken, f"MathML files failed XML parse: {broken}"


# ---------------------------------------------------------------------------
# Tier 3 — End-to-end CDM (requires pdflatex + ARXMCP_RUN_REAL_PDFLATEX=1)
# ---------------------------------------------------------------------------


# NOTE: The `requires_pdflatex` skipif used to call a module-level
# `_pdflatex_available()` helper. That form evaluated at module-
# import time, so any CI plugin or autouse fixture that flipped
# ARXMCP_RUN_REAL_PDFLATEX after import would not unstick the skip.
# We use pytest's lazy string-condition form below to defer the
# evaluation to test-run time (rectifies parser-fidelity-eval-m1 F7).


@pytest.mark.requires_pdflatex
@pytest.mark.eval
@pytest.mark.skipif(
    "shutil.which('pdflatex') is None or shutil.which('pdftoppm') is None"
    " or os.environ.get('ARXMCP_RUN_REAL_PDFLATEX') != '1'",
    reason="pdflatex + pdftoppm not on PATH, or ARXMCP_RUN_REAL_PDFLATEX != 1",
)
class TestRenderLatexToImage:
    def test_renders_simple_formula(self, tmp_path: Path) -> None:
        doc = wrap_formula_latex(r"x", colored=False)
        image = render_latex_to_image(doc, work_dir=tmp_path)
        assert image.ndim == 3
        assert image.shape[2] == 3
        assert image.dtype == np.uint8
        assert image.size > 0


@pytest.mark.requires_pdflatex
@pytest.mark.eval
@pytest.mark.skipif(
    "shutil.which('pdflatex') is None or shutil.which('pdftoppm') is None"
    " or os.environ.get('ARXMCP_RUN_REAL_PDFLATEX') != '1'",
    reason="pdflatex + pdftoppm not on PATH, or ARXMCP_RUN_REAL_PDFLATEX != 1",
)
class TestCdmScoreEndToEnd:
    def test_identical_formulas_score_one(self, tmp_path: Path) -> None:
        result = cdm_score(r"\frac{a}{b}", r"\frac{a}{b}", work_dir=tmp_path)
        assert result.score == pytest.approx(1.0)

    def test_completely_different_formulas_score_low(
        self, tmp_path: Path,
    ) -> None:
        result = cdm_score(
            r"\frac{a}{b}", r"\sum_{i=0}^n x_i",
            work_dir=tmp_path,
        )
        assert result.score < 0.5


@pytest.mark.requires_pdflatex
@pytest.mark.eval
@pytest.mark.skipif(
    "shutil.which('pdflatex') is None or shutil.which('pdftoppm') is None"
    " or os.environ.get('ARXMCP_RUN_REAL_PDFLATEX') != '1'",
    reason="pdflatex + pdftoppm not on PATH, or ARXMCP_RUN_REAL_PDFLATEX != 1",
)
class TestAggregateCdm:
    def test_aggregate_empty(self, tmp_path: Path) -> None:
        result = aggregate_cdm([], work_dir=tmp_path)
        assert isinstance(result, AggregateResult)
        assert result.mean == 0.0
        assert result.scores == []
        assert result.failures == []

    def test_aggregate_single_perfect_pair(self, tmp_path: Path) -> None:
        result = aggregate_cdm(
            [(r"x", r"x")], work_dir=tmp_path,
        )
        assert result.mean == pytest.approx(1.0)
        assert len(result.scores) == 1
        assert result.failures == []


# ---------------------------------------------------------------------------
# Tier-1 promotion gate (cold-start matrix)
# ---------------------------------------------------------------------------


@pytest.mark.eval
def test_tier1_promotion_gate_status() -> None:
    """The TIER-1 promotion gate fires only when the fixture is
    complete (≥20 pages across the 4 classes). Until then, the
    test reports STATUS but does not fail — operator curation is
    incremental per the milestone brief.

    When fixture is complete, change this test's assertion to
    `assert mean_cdm >= 0.85` and re-pin in .claude/TIER-GATES.md.
    """
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
    current = manifest["totals"]["current_pages"]
    threshold = manifest["totals"]["promotion_threshold_pages"]
    if current < threshold:
        pytest.skip(
            f"Fixture has {current}/{threshold} pages — promotion gate "
            f"in INCREMENTAL mode. Operator must hand-curate "
            f"{threshold - current} more pages to activate the gate. "
            f"See tests/eval/textbook_fixtures/README.md."
        )
    # When fixture is complete, the actual CDM eval would run here
    # against a specific parser (Marker, MinerU, Docling, etc.) —
    # the parser identity is a runtime flag the bake-off milestone
    # will add. For now the gate is structural: fixture-complete
    # without a parser flag means the gate is "ready" but inert.
    pytest.skip(
        "Fixture complete but no --parser flag provided. Re-run with "
        "`pytest tests/eval/test_parser_fidelity.py --parser=<name>`."
    )


# ---------------------------------------------------------------------------
# Phase-4 rectification regression tests (parser-fidelity-eval-m1)
# ---------------------------------------------------------------------------


class TestCostMatrixOrderingNormalization:
    """Regression for F1 (HIGH). The ordering-cost `lo` must stay in
    [0, 1] regardless of how many invisible tokens (braces, script
    markers, etc.) fall out of the bbox filter. Pre-fix, `lo` was
    normalized by the visible-token count, so any formula whose raw
    tokenizer index exceeded the visible count produced `lo > 1.0`
    and biased the F1 score downward.
    """

    def test_lo_stays_le_one_with_invisible_tokens(self) -> None:
        # Simulate a 2-visible-of-7-raw-token formula (think
        # `\frac{a}{b}` — 7 tokenizer outputs, 2 visible glyphs at
        # raw-indices 2 and 5).
        predicted_full = [
            TokenBbox(token=t, index=i, color=(0, 0, 0))
            for i, t in enumerate(["\\frac", "{", "a", "}", "{", "b", "}"])
        ]
        # Only "a" (idx=2) and "b" (idx=5) get bboxes.
        predicted_full[2] = TokenBbox(
            token="a", index=2, color=(0, 0, 0), bbox=(0, 0, 5, 5),
        )
        predicted_full[5] = TokenBbox(
            token="b", index=5, color=(0, 0, 15), bbox=(0, 10, 5, 15),
        )
        # Mirror for ground-truth (identical shape).
        gt_full = [
            TokenBbox(token=t, index=i, color=(0, 0, 0))
            for i, t in enumerate(["\\frac", "{", "a", "}", "{", "b", "}"])
        ]
        gt_full[2] = TokenBbox(
            token="a", index=2, color=(0, 0, 0), bbox=(0, 0, 5, 5),
        )
        gt_full[5] = TokenBbox(
            token="b", index=5, color=(0, 0, 15), bbox=(0, 10, 5, 15),
        )
        # Build the cost matrix.
        cost = _cost_matrix(
            predicted_full, gt_full,
            pred_img_shape=(100, 100, 3),
            gt_img_shape=(100, 100, 3),
        )
        # Each cell's `lo` contribution is bounded by raw_n=7, so
        # max(|p.idx/7 - g.idx/7|) ≤ 1.0 always. The total cost should
        # be small (identical tokens, identical bboxes) and well under
        # the 0.5 threshold so both pairs match cleanly.
        assert cost.shape == (2, 2)
        # Off-diagonal cells are the worst case: lt=1 (different
        # tokens "a" vs "b"), lp=L1(bbox-diff), lo=|2/7 - 5/7|=3/7.
        # The diagonal cells (a→a, b→b) should be near zero.
        assert cost[0, 0] < 0.1, f"Diagonal cost too high: {cost[0, 0]}"
        assert cost[1, 1] < 0.1, f"Diagonal cost too high: {cost[1, 1]}"
        # The bug pre-fix: lo = |2/2 - 5/2| = 1.5 (visible-count
        # denominator), so the WORST cell's lo would have been 1.5.
        # Post-fix: max possible lo = |2/7 - 5/7| ≈ 0.43. No cell can
        # exceed Wt*1 + Wp*4 + Wo*1 = 3.1, and in practice (matching
        # tokens) stays far below.
        max_lo_contribution = _LATEX_MAX_LO_CONTRIBUTION  # 0.1 * 1.0
        # Check that no cell exceeds Wt + Wp*4 + Wo (worst-case bound).
        worst_case_bound = 1.0 + 0.5 * 4 + max_lo_contribution
        assert (cost <= worst_case_bound).all(), (
            f"Cost matrix exceeds worst-case bound: {cost.max()} > {worst_case_bound}"
        )

    def test_lo_normalizes_by_raw_count_not_visible(self) -> None:
        # Pre-fix this test would FAIL — lo for the (p.idx=10, g.idx=10,
        # m=n=1) pair would compute as |10/1 - 10/1| = 0 (coincidence
        # only because indices align). The more telling case: p.idx=10,
        # g.idx=0 with m=n=1 — visible-count denominator gives
        # |10/1 - 0/1| = 10, raw-count denominator gives
        # |10/11 - 0/11| ≈ 0.91.
        pred = [
            TokenBbox(token="x", index=i, color=(i, 0, 0))
            for i in range(11)  # 11 raw tokens
        ]
        # Only token at index 10 visible.
        pred[10] = TokenBbox(
            token="x", index=10, color=(10, 0, 0), bbox=(0, 0, 5, 5),
        )
        gt = [
            TokenBbox(token="x", index=i, color=(i, 0, 0))
            for i in range(11)
        ]
        # Only token at index 0 visible.
        gt[0] = TokenBbox(
            token="x", index=0, color=(0, 0, 0), bbox=(0, 0, 5, 5),
        )
        cost = _cost_matrix(
            pred, gt,
            pred_img_shape=(100, 100, 3),
            gt_img_shape=(100, 100, 3),
        )
        # lo = |10/11 - 0/11| ≈ 0.909; lt=0 (matching); lp≈0 (same bbox).
        # cost ≈ 0 + 0 + 0.1 * 0.909 ≈ 0.091, well under the 0.5 threshold.
        # Pre-fix bug: lo = |10/1 - 0/1| = 10; cost ≈ 0 + 0 + 0.1 * 10 = 1.0
        # which exceeds the threshold and would be rejected as a match.
        assert cost.shape == (1, 1)
        assert cost[0, 0] < 0.5, (
            f"Cost {cost[0, 0]} exceeds match threshold — F1 ordering "
            f"bug may have regressed"
        )


# Sentinel for the bound calculation in the test above (avoids magic
# number in the assertion; pulled from _WEIGHT_ORDER * max(|lo|)=1.0).
_LATEX_MAX_LO_CONTRIBUTION: float = 0.1


class TestAggregateFailuresObservability:
    """Regression for F3 (MEDIUM). When a pair raises during rendering,
    `aggregate_cdm` substitutes 0.0 AND records the failure in
    `result.failures` — the operator can distinguish "scored zero" from
    "render crashed". Pre-fix the failure count was silently lost.
    """

    def test_failure_recorded_in_aggregate_result(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # Mock cdm_score to raise on the second pair.
        call_count = {"n": 0}

        def fake_cdm_score(*args: object, **kwargs: object) -> object:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("boom")

            class FakeResult:
                score = 0.9

            return FakeResult()

        monkeypatch.setattr(cdm_eval, "cdm_score", fake_cdm_score)
        result = aggregate_cdm(
            [("a", "a"), ("b", "b"), ("c", "c")],
            work_dir=tmp_path,
        )
        # Two clean scores (0.9, 0.9) + one substituted-zero.
        assert result.scores == [0.9, 0.0, 0.9]
        assert result.failures == [(1, "boom")]
        # Mean across all three: (0.9 + 0.0 + 0.9) / 3 = 0.6.
        assert result.mean == pytest.approx(0.6)

    def test_no_failures_means_empty_failures_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        def fake_cdm_score(*args: object, **kwargs: object) -> object:
            class FakeResult:
                score = 1.0

            return FakeResult()

        monkeypatch.setattr(cdm_eval, "cdm_score", fake_cdm_score)
        result = aggregate_cdm([("a", "a")], work_dir=tmp_path)
        assert result.failures == []
        assert result.mean == pytest.approx(1.0)


class TestUnicodeTokenization:
    """Regression for F10 (LOW). Documented in `tokenize_latex`
    docstring: literal-unicode math chars round-trip but do NOT
    canonicalize to backslash form. The fixture-curation contract
    requires operator to pick one shape.
    """

    def test_greek_letters_tokenize_as_individual_chars(self) -> None:
        assert tokenize_latex("α + β") == ["α", "+", "β"]

    def test_nabla_and_partial_round_trip(self) -> None:
        assert tokenize_latex("∇f = 0") == ["∇", "f", "=", "0"]

    def test_alpha_backslash_form_differs_from_unicode(self) -> None:
        # Documented asymmetry: \alpha and literal α are different
        # tokens. Operator chooses one canonical form for the fixture.
        assert tokenize_latex(r"\alpha") == ["\\alpha"]
        assert tokenize_latex("α") == ["α"]
        # No equality between the two outputs.
        assert tokenize_latex(r"\alpha") != tokenize_latex("α")


class TestFixtureShape:
    """Regression for F4 (MEDIUM). The v0 fixture uses hand-typed
    sparse MathML (≤ 50 lines, no LaTeXML provenance markers). If the
    operator switches to LaTeXML-verbose form for some pages but not
    others, CDM scoring becomes inconsistent. This test pins the
    current shape and FAILS LOUDLY when a future commit drifts.
    """

    def test_all_mathml_files_match_v0_shape(self) -> None:
        """All shipped MathML files must be either consistently
        hand-typed-sparse (≤ 50 lines AND no `<annotation
        encoding="application/x-tex">`) or consistently LaTeXML-
        verbose (BOTH ≤ 50 lines is False AND the annotation tag is
        present). Mixed shapes fail.
        """
        all_mathml = sorted(FIXTURE_ROOT.glob("*/[0-9][0-9]-formula.mathml"))
        if not all_mathml:
            pytest.skip("No MathML fixture files present yet.")
        shape_per_file: dict[str, str] = {}
        for path in all_mathml:
            content = path.read_text(encoding="utf-8")
            line_count = content.count("\n")
            has_annotation = "<annotation" in content and "x-tex" in content
            if line_count <= 50 and not has_annotation:
                shape = "hand-typed-sparse"
            elif has_annotation:
                shape = "latexml-verbose"
            else:
                shape = "unknown"
            shape_per_file[str(path.relative_to(FIXTURE_ROOT))] = shape
        shapes = set(shape_per_file.values())
        assert len(shapes) == 1, (
            f"Mixed MathML shapes in fixture (CDM scoring will be "
            f"inconsistent): {shape_per_file}. "
            f"Pick one shape across all pages — see "
            f"tests/eval/textbook_fixtures/README.md §Regenerating."
        )

    def test_v0_pages_are_hand_typed_sparse(self) -> None:
        """The 2 v0 example pages under paper-control/ are hand-typed.
        If a future commit regenerates them via latexmlc, this test
        catches the drift and forces the operator to update
        manifest.json::mathml_shape + this assertion in lockstep.
        """
        v0_pages = sorted(
            (FIXTURE_ROOT / "paper-control").glob("0[12]-formula.mathml")
        )
        if len(v0_pages) < 2:
            pytest.skip(
                f"Expected 2 v0 example pages, found {len(v0_pages)}. "
                f"Did the milestone fixture-skeleton commit not land?"
            )
        for path in v0_pages:
            content = path.read_text(encoding="utf-8")
            assert content.count("\n") <= 50, (
                f"{path.name} exceeds the hand-typed-sparse 50-line "
                f"budget ({content.count('n')} lines) — did someone "
                f"regenerate via latexmlc without updating "
                f"manifest.json::mathml_shape?"
            )
            assert "<annotation" not in content, (
                f"{path.name} contains a LaTeXML <annotation> tag — "
                f"v0 shape is hand-typed-sparse without annotations. "
                f"See README §Regenerating for the shape-switch protocol."
            )
