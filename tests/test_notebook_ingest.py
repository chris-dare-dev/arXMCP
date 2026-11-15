"""``tools/notebook_ingest.py`` builds the indexes a notebook is served from."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import lancedb
import pyarrow as pa

from ingest.preamble import PreambleDoc
from ingest.schema import CHUNKS_SCHEMA_V1
from ingest.store import write_corpus_version_marker
from tools import _notebook_common, notebook_ingest

PAPERS = ("2401.00001", "2401.00002")


def _chunk(paper_id: str) -> dict:
    row = {field.name: None for field in CHUNKS_SCHEMA_V1}
    row.update(
        chunk_id=f"{paper_id}#c0", paper_id=paper_id, kind="theorem",
        section_path=["1"], body_text="Let X be a scheme.",
        body_tokens="let x be a scheme", chunker_version="v",
        theorem_name=f"Lemma of {paper_id}",
        embedder_version="v",
    )
    return row


def _fake_bulk_ingest(paper_ids, *, lancedb_staging_path, **_kwargs):
    """Stand in for the fetch/parse/chunk/embed loop: leave behind what a
    successful run leaves, a chunks table and its version marker."""
    rows = [_chunk(pid) for pid in paper_ids]
    lancedb.connect(str(lancedb_staging_path)).create_table(
        "chunks", data=pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)
    )
    write_corpus_version_marker(
        lancedb_staging_path, version=1, chunker_version="v",
        embedder_version="v", paper_count=len(rows), chunk_count=len(rows),
    )
    return SimpleNamespace(
        papers_total=len(rows), papers_succeeded=len(rows),
        papers_failed=0, ar5iv_hit_rate=1.0,
    )


def test_ingest_builds_the_definitions_table(tmp_path, monkeypatch):
    base = tmp_path / "notebooks"
    nb_dir = base / "demo-nb"
    nb_dir.mkdir(parents=True)
    (nb_dir / "papers.txt").write_text("\n".join(PAPERS) + "\n", encoding="utf-8")
    preamble_dir = tmp_path / "preamble"
    for paper_id in PAPERS:
        doc = PreambleDoc(
            paper_id=paper_id, source_hash="0" * 64,
            macros=[r"\newcommand{\RR}{\mathbb{R}}"],
            preamble_text="", preamble_hash="0" * 16,
        )
        (preamble_dir / paper_id).mkdir(parents=True)
        (preamble_dir / paper_id / "preamble.json").write_text(
            json.dumps(doc.to_dict()), encoding="utf-8"
        )
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr("ingest.preamble.PREAMBLE_DIR", preamble_dir)
    monkeypatch.setattr(notebook_ingest, "run_bulk_ingest", _fake_bulk_ingest)

    assert notebook_ingest.run("demo-nb") == 0

    definitions = (
        lancedb.connect(str(nb_dir / "lancedb")).open_table("definitions").to_arrow()
    )
    assert sorted(definitions.column("paper_id").to_pylist()) == sorted(PAPERS)
    assert set(definitions.column("symbol").to_pylist()) == {r"\RR"}


def test_ingest_builds_the_theorem_name_index(tmp_path, monkeypatch):
    base = tmp_path / "notebooks"
    nb_dir = base / "demo-nb"
    nb_dir.mkdir(parents=True)
    (nb_dir / "papers.txt").write_text("\n".join(PAPERS) + "\n", encoding="utf-8")
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr("ingest.preamble.PREAMBLE_DIR", tmp_path / "preamble")
    monkeypatch.setattr(notebook_ingest, "run_bulk_ingest", _fake_bulk_ingest)

    assert notebook_ingest.run("demo-nb") == 0

    conn = sqlite3.connect(str(nb_dir / "lancedb" / "derived" / "theorem_names.db"))
    try:
        names = {r[0] for r in conn.execute("SELECT display_name FROM theorem_names")}
    finally:
        conn.close()
    assert names == {f"Lemma of {pid}" for pid in PAPERS}
