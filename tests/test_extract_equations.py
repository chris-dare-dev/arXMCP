"""Tests for the equation atom extractor (E10_S03b).

Covers:

* Pure parser — `extract_equation_atoms_from_html` against hand-crafted
  LaTeXML HTML fixtures under `tests/fixtures/extract_equations/`.
* Detection rules — single-equation tables, align-group tables, skip
  inline math.
* Persistence — `extract_equations_for_paper` writes to a real
  LanceDB equations table; per-paper sweep is idempotent.
* `equation_id` content-addressing — same inputs produce the same id.
* `parent_chunk_id = None` at v1 (synthesis D7).
* AC1 coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.extract_equations import (
    extract_equation_atoms_from_html,
    extract_equations_for_paper,
)
from ingest.index_equations import open_or_create_equations_table

FIXTURES = Path(__file__).parent / "fixtures" / "extract_equations"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _empty_lancedb_path(tmp_path: Path) -> Path:
    """``open_or_create_equations_table`` requires the LanceDB
    directory to exist already (it raises FileNotFoundError
    otherwise). Mirror the fixture pattern used by the E10_S01/S03
    tests.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tmp_path


# ===========================================================================
# Pure parser
# ===========================================================================


class TestExtractEquationAtomsFromHtml:
    def test_single_equation_environment(self):
        html = _read("single_equation.html")
        atoms = extract_equation_atoms_from_html(html, "2401.00001")
        assert len(atoms) == 1
        atom = atoms[0]
        assert atom["paper_id"] == "2401.00001"
        # ``label`` is the LaTeXML id suffix, NOT the human-facing (1).
        assert atom["label"] == "E1"
        assert atom["presentation_latex"] == r"e^{i\pi}+1=0"
        # ``mathml`` carries the <math> wrapper for downstream parsing.
        assert atom["mathml"].lstrip().startswith("<math")
        # Defaults established by synthesis decisions.
        assert atom["parent_chunk_id"] is None
        assert atom["ascii_form"] == ""
        assert atom["mathml_tree_json"] is None
        assert atom["embedding_eq"] is None
        # Context is the enclosing paragraph.
        assert "Euler" in atom["context_sentence"]
        # equation_id is content-addressable and 22+16 chars
        # ("arxiv:" + paper_id + ":" + 16 hex).
        assert atom["equation_id"].startswith("arxiv:2401.00001:")

    def test_align_group_two_labeled_rows(self):
        """Each labeled <tbody> in a ltx_equationgroup is ONE atom."""
        html = _read("align_group.html")
        atoms = extract_equation_atoms_from_html(html, "2401.00002")
        assert len(atoms) == 2
        labels = sorted(a["label"] for a in atoms)
        assert labels == ["E2", "E3"]
        # Both rows of the first equation stitch into one
        # presentation_latex (space-joined).
        e2 = next(a for a in atoms if a["label"] == "E2")
        assert e2["presentation_latex"] == "x+y =3"
        # mathml column carries the full <tbody> so the tree
        # captures the LHS/RHS column relationship.
        assert e2["mathml"].lstrip().startswith("<tbody")
        assert "<math" in e2["mathml"]

    def test_skips_inline_math(self):
        """Inline math outside any ltx_eqn_table is NOT an atom (v1
        scope: display math only)."""
        html = _read("inline_only.html")
        atoms = extract_equation_atoms_from_html(html, "2401.00003")
        assert atoms == []

    def test_empty_html_zero_atoms(self):
        html = _read("empty_math.html")
        atoms = extract_equation_atoms_from_html(html, "2401.00004")
        assert atoms == []


# ===========================================================================
# Content addressing
# ===========================================================================


class TestEquationIdContentAddress:
    def test_same_inputs_same_id(self):
        html = _read("single_equation.html")
        a1 = extract_equation_atoms_from_html(html, "2401.00001")
        a2 = extract_equation_atoms_from_html(html, "2401.00001")
        assert a1[0]["equation_id"] == a2[0]["equation_id"]

    def test_different_paper_id_different_id(self):
        html = _read("single_equation.html")
        a1 = extract_equation_atoms_from_html(html, "2401.00001")
        a2 = extract_equation_atoms_from_html(html, "2401.00002")
        assert a1[0]["equation_id"] != a2[0]["equation_id"]

    def test_id_has_arxiv_prefix(self):
        html = _read("single_equation.html")
        atoms = extract_equation_atoms_from_html(html, "2401.00001")
        # Format: arxiv:<paper_id>:<16 hex>
        prefix = "arxiv:2401.00001:"
        assert atoms[0]["equation_id"].startswith(prefix)
        hex_suffix = atoms[0]["equation_id"][len(prefix):]
        assert len(hex_suffix) == 16
        assert all(c in "0123456789abcdef" for c in hex_suffix)


# ===========================================================================
# Persistence — `extract_equations_for_paper`
# ===========================================================================


class TestExtractEquationsForPaper:
    def test_writes_rows_to_lancedb_table(self, tmp_path):
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        html_path = FIXTURES / "single_equation.html"
        n = extract_equations_for_paper(
            "2401.00001", lancedb_path, html_path=html_path
        )
        assert n == 1
        table = open_or_create_equations_table(lancedb_path)
        rows = table.to_arrow().to_pylist()
        assert len(rows) == 1
        assert rows[0]["paper_id"] == "2401.00001"
        assert rows[0]["presentation_latex"] == r"e^{i\pi}+1=0"
        assert rows[0]["embedding_eq"] is None

    def test_idempotent_per_paper(self, tmp_path):
        """Re-running on the same paper leaves the row count stable."""
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        html_path = FIXTURES / "single_equation.html"
        n1 = extract_equations_for_paper(
            "2401.00001", lancedb_path, html_path=html_path
        )
        n2 = extract_equations_for_paper(
            "2401.00001", lancedb_path, html_path=html_path
        )
        assert n1 == n2 == 1
        table = open_or_create_equations_table(lancedb_path)
        rows = [
            r for r in table.to_arrow().to_pylist()
            if r["paper_id"] == "2401.00001"
        ]
        assert len(rows) == 1

    def test_two_papers_coexist(self, tmp_path):
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        html_path = FIXTURES / "single_equation.html"
        extract_equations_for_paper(
            "2401.00001", lancedb_path, html_path=html_path
        )
        extract_equations_for_paper(
            "2401.00002", lancedb_path, html_path=html_path
        )
        table = open_or_create_equations_table(lancedb_path)
        paper_ids = {r["paper_id"] for r in table.to_arrow().to_pylist()}
        assert paper_ids == {"2401.00001", "2401.00002"}

    def test_align_group_persists_two_rows(self, tmp_path):
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        html_path = FIXTURES / "align_group.html"
        n = extract_equations_for_paper(
            "2401.00003", lancedb_path, html_path=html_path
        )
        assert n == 2

    def test_missing_html_returns_zero(self, tmp_path):
        """A paper whose LaTeXML HTML never landed (conversion
        failed, file absent, etc.) produces zero rows without
        raising. The seed corpus is in this state for ~48/50
        papers today — extractor must handle it gracefully.
        """
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        n = extract_equations_for_paper(
            "2401.99999",
            lancedb_path,
            html_path=tmp_path / "does_not_exist.html",
        )
        assert n == 0

    def test_inline_only_html_writes_zero(self, tmp_path):
        """An HTML with only inline math (no display equations) writes
        zero atoms — v1 scope is display math only."""
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        html_path = FIXTURES / "inline_only.html"
        n = extract_equations_for_paper(
            "2401.00004", lancedb_path, html_path=html_path
        )
        assert n == 0

    def test_rejects_malformed_paper_id(self, tmp_path):
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        with pytest.raises(ValueError, match="paper_id"):
            extract_equations_for_paper(
                "../../../etc",
                lancedb_path,
                html_path=FIXTURES / "single_equation.html",
            )
