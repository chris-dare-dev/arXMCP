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
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from tools.cdm_eval import (
    TokenBbox,
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


def _pdflatex_available() -> bool:
    return (
        shutil.which("pdflatex") is not None
        and shutil.which("pdftoppm") is not None
        and os.environ.get("ARXMCP_RUN_REAL_PDFLATEX") == "1"
    )


@pytest.mark.requires_pdflatex
@pytest.mark.eval
@pytest.mark.skipif(
    not _pdflatex_available(),
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
    not _pdflatex_available(),
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
    not _pdflatex_available(),
    reason="pdflatex + pdftoppm not on PATH, or ARXMCP_RUN_REAL_PDFLATEX != 1",
)
class TestAggregateCdm:
    def test_aggregate_empty(self, tmp_path: Path) -> None:
        mean, scores = aggregate_cdm([], work_dir=tmp_path)
        assert mean == 0.0
        assert scores == []

    def test_aggregate_single_perfect_pair(self, tmp_path: Path) -> None:
        mean, scores = aggregate_cdm(
            [(r"x", r"x")], work_dir=tmp_path,
        )
        assert mean == pytest.approx(1.0)
        assert len(scores) == 1


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
