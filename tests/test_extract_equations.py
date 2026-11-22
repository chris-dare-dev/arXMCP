"""Tests for the equation atom extractor (E10_S03b).

Covers:

* Pure parser — `extract_equation_atoms_from_html` against hand-crafted
  LaTeXML HTML fixtures under `tests/fixtures/extract_equations/`.
* Detection rules — single-equation tables, align-group tables, skip
  inline math.
* Persistence — `extract_equations_for_paper` writes to a real
  LanceDB equations table; per-paper sweep is idempotent.
* `equation_id` content-addressing — same inputs produce the same id.
* `parent_chunk_id` — the chunk whose text holds the equation.
* An ingest run leaves `find_equation` a table it answers `ted_fused` from.
* AC1 coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arxmcp.ingest.extract_equations import (
    extract_equation_atoms_from_html,
    extract_equations_for_paper,
)
from arxmcp.ingest.index_equations import open_or_create_equations_table

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
        # No chunks given, so no parent.
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
        # mathml column carries a synthetic <math> root wrapping the
        # stitched cell contents — F2 (E10_S03b critique) close. The
        # inner <math> wrappers are stripped so the TED tree shape
        # matches single-equation atoms with the same content.
        assert e2["mathml"].lstrip().startswith("<math")
        # The stitched mrow content from both cells is present.
        assert "<mrow>" in e2["mathml"]

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

    def test_align_group_mathml_has_math_root(self, tmp_path):
        """F2 regression (E10_S03b critique) — align-group atoms
        must serialize ``mathml`` with a ``<math>`` root, not a
        ``<tbody>`` root. The previous implementation used
        ``str(tbody)`` which made the TED tree root incomparable
        with single-equation atoms; this test pins the new
        wrapped-in-math serialization.
        """
        html = _read("align_group.html")
        atoms = extract_equation_atoms_from_html(html, "2401.00002")
        assert atoms
        for atom in atoms:
            # The serialized mathml must START with <math
            # (synthetic root from F2 rect) rather than <tbody.
            assert atom["mathml"].lstrip().startswith("<math"), (
                f"align-group atom mathml has non-<math root: "
                f"{atom['mathml'][:80]}"
            )
            # And it must still carry the inner <math> cells.
            assert atom["mathml"].count("<math") >= 1

    def test_align_group_ted_comparable_to_single_equation(self, tmp_path):
        """F2 regression — a single-equation atom and an
        align-group atom carrying the same inner content should
        compute a low normalized TED. The previous implementation
        scored ~0.79 due to the root-label mismatch
        (``tbody`` vs ``math``); after the fix both atoms parse to
        trees rooted at ``math`` and the structural similarity is
        recoverable.
        """
        from arxmcp.ingest.mathml_tree import (
            normalized_ted,
            parse_mathml_to_tree,
        )

        single_html = """
<table class="ltx_equation ltx_eqn_table" id="S0.E1">
<tbody><tr><td><math alttext="x" display="block" id="S0.E1.m1">
<mrow><mi>x</mi></mrow>
</math></td></tr></tbody></table>"""
        group_html = """
<table class="ltx_equationgroup ltx_eqn_table" id="S0.EG1">
<tbody id="S0.E2"><tr><td><math alttext="x" display="inline" id="S0.E2.m1">
<mrow><mi>x</mi></mrow>
</math></td></tr></tbody></table>"""
        single = extract_equation_atoms_from_html(single_html, "p1")[0]
        group = extract_equation_atoms_from_html(group_html, "p2")[0]
        tree_single = parse_mathml_to_tree(single["mathml"])
        tree_group = parse_mathml_to_tree(group["mathml"])
        # Both roots are now ``math``; the inner structure is
        # identical (one mrow with one mi child), so TED is 0.
        assert normalized_ted(tree_single, tree_group) == 0.0

    def test_delete_failure_surfaces_not_swallowed(self, tmp_path):
        """F5 regression (E10_S03b critique) — a genuine LanceDB
        delete error (permission denied, schema mismatch, etc.)
        must NOT be swallowed under the cover of "first-write
        edge case." The empty-table edge case is now handled by
        the row-count precondition; a delete failure on a populated
        table is unambiguous.
        """
        from unittest.mock import patch as _patch

        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        html_path = FIXTURES / "single_equation.html"
        # First run seeds a row so the second run's precondition
        # check fires.
        extract_equations_for_paper(
            "2401.00001", lancedb_path, html_path=html_path
        )

        # Wrap the table so delete raises PermissionError on the
        # second run.
        real_table = open_or_create_equations_table(lancedb_path)

        class _BadDelete:
            def __init__(self, wrapped):
                self._wrapped = wrapped

            def __getattr__(self, name):
                if name == "delete":
                    def _raise(*_a, **_kw):
                        raise PermissionError("simulated denied")
                    return _raise
                return getattr(self._wrapped, name)

        with _patch(
            "arxmcp.ingest.extract_equations.open_or_create_equations_table",
            return_value=_BadDelete(real_table),
        ), pytest.raises(PermissionError, match="simulated"):
            extract_equations_for_paper(
                "2401.00001",
                lancedb_path,
                html_path=html_path,
            )

    def test_rejects_malformed_paper_id(self, tmp_path):
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        with pytest.raises(ValueError, match="paper_id"):
            extract_equations_for_paper(
                "../../../etc",
                lancedb_path,
                html_path=FIXTURES / "single_equation.html",
            )


# ===========================================================================
# Parent chunk
# ===========================================================================


class TestParentChunk:
    def _chunk(self, chunk_id, body, *, has_stmt=True):
        from arxmcp.ingest.extract_equations import _ChunkText

        return _ChunkText(chunk_id, body, has_stmt)

    def test_the_chunk_holding_the_equation_is_its_parent(self):
        chunks = [
            self._chunk("c1", "Nothing here."),
            self._chunk("c2", r"Euler: $e^{i\pi}+1=0$ links five constants."),
        ]
        [atom] = extract_equation_atoms_from_html(
            _read("single_equation.html"), "2401.00001", chunks
        )
        assert atom["parent_chunk_id"] == "c2"

    def test_a_statement_chunk_wins_over_a_proof_chunk(self):
        body = r"$e^{i\pi}+1=0$"
        chunks = [
            self._chunk("a-proof", body, has_stmt=False),
            self._chunk("b-stmt", body),
        ]
        [atom] = extract_equation_atoms_from_html(
            _read("single_equation.html"), "2401.00001", chunks
        )
        assert atom["parent_chunk_id"] == "b-stmt"

    def test_no_chunk_holding_it_leaves_no_parent(self):
        [atom] = extract_equation_atoms_from_html(
            _read("single_equation.html"), "2401.00001",
            [self._chunk("c1", "e^{i\\pi}+1=0 without delimiters")],
        )
        assert atom["parent_chunk_id"] is None

    def test_an_align_row_needs_every_cell(self):
        atoms = extract_equation_atoms_from_html(
            _read("align_group.html"), "2401.00001",
            [self._chunk("c1", "$x+y$ $=3$ and $2x$ alone")],
        )
        parents = {a["label"]: a["parent_chunk_id"] for a in atoms}
        assert parents == {"E2": "c1", "E3": None}


# ===========================================================================
# Through an ingest run
# ===========================================================================


def _ingest_fixture_paper(tmp_path, paper_id):
    """Run a bulk ingest of one paper from ``two_theorems.html``: the real
    chunker, store, equation extraction and tree build, with the
    embedder replaced by one unit vector per chunk."""
    from contextlib import ExitStack
    from unittest.mock import patch

    import numpy as np

    from arxmcp.ingest.ar5iv_fetch import Ar5ivResult
    from arxmcp.ingest.bulk_ingest import run_bulk_ingest
    from arxmcp.ingest.chunk import EMBEDDING_DIM, route
    from arxmcp.ingest.chunker import chunk_paper
    from arxmcp.ingest.embedder import EmbedStats
    from arxmcp.ingest.schema import EmbedRecord

    parsed_dir = tmp_path / "parsed"
    (parsed_dir / paper_id).mkdir(parents=True)
    html = parsed_dir / paper_id / "index.html"
    html.write_text(_read("two_theorems.html"), encoding="utf-8")
    chunked: list = []

    def _chunk(pid, **kwargs):
        chunked[:] = chunk_paper(pid, **kwargs)
        return chunked

    def _record(_pid):
        stmt = [c for c in chunked if route(c.kind) == "stmt"]
        proof = [c for c in chunked if route(c.kind) == "proof"]
        eye = np.eye(len(chunked), EMBEDDING_DIM, dtype=np.float32)
        return EmbedRecord(
            chunk_ids_stmt=[c.chunk_id for c in stmt],
            embedding_stmt=eye[: len(stmt)],
            chunk_ids_proof=[c.chunk_id for c in proof],
            embedding_proof=eye[len(stmt) :],
            embedder_version="bge-m3@00000000",
        )

    staging = tmp_path / "staging"
    with ExitStack() as stack:
        for target, kwargs in [
            ("try_cache", {"return_value": Ar5ivResult(
                paper_id=paper_id, hit=True, cache_path=html,
                parsed_path=html, reason="ok_local_cache",
            )}),
            ("chunk_paper", {"side_effect": _chunk}),
            ("embed_paper", {"return_value": EmbedStats(
                paper_id=paper_id, chunks_processed=len(chunked),
                chunks_skipped=0, truncated_count=0, elapsed_s=0.0,
            )}),
            ("load_embed_record", {"side_effect": _record}),
            ("build_derived_indexes", {}),
        ]:
            stack.enter_context(patch(f"arxmcp.ingest.bulk_ingest.{target}", **kwargs))
        stack.enter_context(patch("arxmcp.ingest.chunker.CHUNKS_DIR", tmp_path / "chunks"))
        stack.enter_context(
            patch("arxmcp.ingest.chunker._resolve_preamble_doc", return_value=None)
        )
        summary = run_bulk_ingest(
            [paper_id],
            lancedb_staging_path=staging,
            parsed_dir=parsed_dir,
            failures_path=tmp_path / "failures.jsonl",
            log_path=tmp_path / "ingestion.log",
            ops_dir=tmp_path / "ops",
        )
    assert summary.papers_succeeded == 1
    return staging


def test_an_ingested_paper_answers_find_equation_by_tree(tmp_path, monkeypatch):
    import lancedb
    import numpy as np

    import arxmcp.server.handlers.equation as eq_handler_mod
    import arxmcp.server.tools as server_tools
    from tests.test_equation_index import _install_resources, _run

    paper_id = "2401.00007"
    staging = _ingest_fixture_paper(tmp_path, paper_id)

    db = lancedb.connect(str(staging))
    chunks = db.open_table("chunks")
    equations = db.open_table("equations")
    rows = {r["label"]: r for r in equations.to_arrow().to_pylist()}
    assert set(rows) == {"E1", "E2"}
    assert all(r["mathml_tree_json"] for r in rows.values())
    bodies = {
        r["chunk_id"]: r["body_text"] for r in chunks.to_arrow().to_pylist()
    }
    assert "\\int" in bodies[rows["E1"]["parent_chunk_id"]]
    assert "\\sum" in bodies[rows["E2"]["parent_chunk_id"]]

    # The query lands next to the integral's chunk; the tree must still
    # rank the integral first among the candidates the chunks bring in.
    [integral_chunk] = (
        chunks.search()
        .where(f"chunk_id = '{rows['E1']['parent_chunk_id']}'")
        .to_arrow()
        .to_pylist()
    )
    query_vec = np.asarray(integral_chunk["embedding_stmt"], dtype=np.float32)

    async def _encode(_text):
        return query_vec

    monkeypatch.setattr(eq_handler_mod, "encode_query", _encode)
    _install_resources(chunks, equations_table=equations, tmp_path=staging)
    query = (Path(__file__).parent / "fixtures" / "equations" / "int_01_fxdx.mathml")
    try:
        result = _run(
            eq_handler_mod.handle_find_equation(
                latex_or_mathml=query.read_text(encoding="utf-8"), k=5
            )
        )
    finally:
        server_tools._RESOURCES = None
    assert result["retrieval_mode"] == "ted_fused"
    assert result["results"][0]["equation_id"] == rows["E1"]["equation_id"]
