"""The derived-index modules run as the commands the server tells
operators to run (``python -m ingest.index_*``)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import lancedb
import pyarrow as pa

from arxmcp.corpus.schema import CHUNKS_SCHEMA_V1, EQUATIONS_SCHEMA_V1
from arxmcp.ingest import index_definitions
from arxmcp.ingest.index_equations import open_or_create_equations_table
from arxmcp.ingest.mathml_tree import MATHML_TREE_NORMALIZER_VERSION
from arxmcp.ingest.preamble import PreambleDoc

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(module: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120, check=False,
    )


def _chunk(paper_id: str, n: int, theorem_name: str | None) -> dict:
    row = {field.name: None for field in CHUNKS_SCHEMA_V1}
    row.update(
        chunk_id=f"{paper_id}#c{n}",
        paper_id=paper_id,
        kind="theorem",
        section_path=["1"],
        theorem_name=theorem_name,
        body_text="body",
        body_tokens="body",
        chunker_version="v",
        embedder_version="v",
    )
    return row


def _chunks_db(tmp_path: Path) -> Path:
    path = tmp_path / "index" / "lancedb"
    rows = [
        _chunk("2401.00001", 0, "Riemann-Roch theorem"),
        _chunk("2401.00001", 1, None),
        _chunk("2401.00002", 0, "Serre duality"),
    ]
    lancedb.connect(str(path)).create_table(
        "chunks", data=pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)
    )
    return path


def test_theorem_names_command_builds_the_index_the_server_reads(tmp_path):
    lancedb_path = _chunks_db(tmp_path)

    result = _run("arxmcp.ingest.index_theorem_names", "--lancedb-path", str(lancedb_path))

    assert result.returncode == 0, result.stderr
    assert "across 2 paper(s)" in result.stdout
    db = lancedb_path / "derived" / "theorem_names.db"
    conn = sqlite3.connect(str(db))
    try:
        names = {r[0] for r in conn.execute("SELECT display_name FROM theorem_names")}
    finally:
        conn.close()
    assert names == {"Riemann-Roch theorem", "Serre duality"}


def _equations_db(tmp_path: Path) -> Path:
    """Equations with no tree, a tree the running normalizer wrote, and
    one an older normalizer wrote."""
    path = tmp_path / "lancedb"
    path.mkdir()
    table = open_or_create_equations_table(path)
    rows = []
    for eq_id, tree, version in (
        ("eq-new", None, None),
        ("eq-current", "current tree", MATHML_TREE_NORMALIZER_VERSION),
        ("eq-stale", "stale tree", MATHML_TREE_NORMALIZER_VERSION - 1),
    ):
        row = {field.name: None for field in EQUATIONS_SCHEMA_V1}
        row.update(
            equation_id=eq_id, paper_id="2401.00001",
            presentation_latex="x", mathml="<math><mi>x</mi></math>",
            mathml_tree_json=tree, normalizer_version=version,
        )
        rows.append(row)
    table.add(pa.Table.from_pylist(rows, schema=EQUATIONS_SCHEMA_V1))
    return path


def _trees(path: Path) -> dict[str, tuple[str, int]]:
    table = lancedb.connect(str(path)).open_table("equations").to_arrow()
    return dict(zip(
        table.column("equation_id").to_pylist(),
        zip(
            table.column("mathml_tree_json").to_pylist(),
            table.column("normalizer_version").to_pylist(),
            strict=True,
        ),
        strict=True,
    ))


def test_equations_command_rebuilds_trees_another_normalizer_wrote(tmp_path):
    path = _equations_db(tmp_path)

    result = _run("arxmcp.ingest.index_equations", "--lancedb-path", str(path))

    assert result.returncode == 0, result.stderr
    trees = _trees(path)
    assert trees["eq-current"] == ("current tree", MATHML_TREE_NORMALIZER_VERSION)
    assert json.loads(trees["eq-new"][0])
    assert trees["eq-stale"] == trees["eq-new"]
    assert trees["eq-new"][1] == MATHML_TREE_NORMALIZER_VERSION


def test_equations_rebuild_replaces_every_tree(tmp_path):
    path = _equations_db(tmp_path)

    result = _run("arxmcp.ingest.index_equations", "--lancedb-path", str(path), "--rebuild")

    assert result.returncode == 0, result.stderr
    trees = _trees(path)
    assert trees["eq-current"] == trees["eq-new"] == trees["eq-stale"]
    assert json.loads(trees["eq-current"][0])


def test_trees_from_before_the_version_column_are_rebuilt(tmp_path):
    """A table written before trees recorded their normalizer gains the
    column, and its trees count as another normalizer's."""
    path = tmp_path / "lancedb"
    old_schema = pa.schema(
        [f for f in EQUATIONS_SCHEMA_V1 if f.name != "normalizer_version"]
    )
    row = {f.name: None for f in old_schema}
    row.update(
        equation_id="eq-old", paper_id="2401.00001", presentation_latex="x",
        mathml="<math><mi>x</mi></math>", mathml_tree_json="old tree",
    )
    lancedb.connect(str(path)).create_table(
        "equations", data=pa.Table.from_pylist([row], schema=old_schema)
    )

    result = _run("arxmcp.ingest.index_equations", "--lancedb-path", str(path))

    assert result.returncode == 0, result.stderr
    tree, version = _trees(path)["eq-old"]
    assert json.loads(tree) and version == MATHML_TREE_NORMALIZER_VERSION


def test_equations_command_refuses_a_missing_dataset(tmp_path):
    result = _run(
        "arxmcp.ingest.index_equations", "--lancedb-path", str(tmp_path / "absent")
    )

    assert result.returncode == 2
    assert "no LanceDB dataset" in result.stderr


def test_definitions_command_is_runnable():
    result = _run("arxmcp.ingest.index_definitions", "--help")

    assert result.returncode == 0
    assert "usage: python -m arxmcp.ingest.index_definitions" in result.stdout


def test_definitions_command_indexes_every_paper_in_the_chunks_table(
    tmp_path, capsys
):
    lancedb_path = _chunks_db(tmp_path)
    preamble_dir = tmp_path / "preamble"
    for paper_id in ("2401.00001", "2401.00002"):
        doc = PreambleDoc(
            paper_id=paper_id, source_hash="0" * 64,
            macros=[r"\newcommand{\RR}{\mathbb{R}}"],
            preamble_text="", preamble_hash="0" * 16,
        )
        (preamble_dir / paper_id).mkdir(parents=True)
        (preamble_dir / paper_id / "preamble.json").write_text(
            json.dumps(doc.to_dict()), encoding="utf-8"
        )

    with patch("arxmcp.ingest.preamble.PREAMBLE_DIR", preamble_dir):
        assert index_definitions._cli(["--lancedb-path", str(lancedb_path)]) == 0

    assert "indexed 2 definition(s) across 2 paper(s)" in capsys.readouterr().out
    table = lancedb.connect(str(lancedb_path)).open_table("definitions").to_arrow()
    assert sorted(table.column("paper_id").to_pylist()) == ["2401.00001", "2401.00002"]
