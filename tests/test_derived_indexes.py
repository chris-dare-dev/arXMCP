"""``ingest.derived_indexes`` builds a dataset's indexes inside it."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import lancedb
import pyarrow as pa

from ingest.derived_indexes import build_derived_indexes
from ingest.preamble import PreambleDoc
from ingest.schema import CHUNKS_SCHEMA_V1
from ingest.store import write_corpus_version_marker

PAPERS = ("2401.00001", "2401.00002")


def _chunk(paper_id: str) -> dict:
    row = {field.name: None for field in CHUNKS_SCHEMA_V1}
    row.update(
        chunk_id=f"{paper_id}#c0", paper_id=paper_id, kind="theorem",
        section_path=["1"], body_text="Let X be a scheme.",
        body_tokens="let x be a scheme", chunker_version="v",
        theorem_name=f"Lemma of {paper_id}", embedder_version="v",
    )
    return row


def _dataset(tmp_path, monkeypatch, name="lancedb-staging", papers=PAPERS):
    """A dataset (chunks + marker) and the preambles of its papers."""
    staging = tmp_path / name
    rows = [_chunk(pid) for pid in papers]
    table = lancedb.connect(str(staging)).create_table(
        "chunks", data=pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)
    )
    write_corpus_version_marker(
        staging, version=table.version, chunker_version="v", embedder_version="v",
        paper_count=len(rows), chunk_count=len(rows),
    )
    preamble_dir = tmp_path / "preamble"
    for paper_id in papers:
        doc = PreambleDoc(
            paper_id=paper_id, source_hash="0" * 64,
            macros=[r"\newcommand{\RR}{\mathbb{R}}"],
            preamble_text="", preamble_hash="0" * 16,
        )
        (preamble_dir / paper_id).mkdir(parents=True, exist_ok=True)
        (preamble_dir / paper_id / "preamble.json").write_text(
            json.dumps(doc.to_dict()), encoding="utf-8"
        )
    monkeypatch.setattr("ingest.preamble.PREAMBLE_DIR", preamble_dir)
    return staging


def test_a_staged_dataset_carries_its_own_indexes(tmp_path, monkeypatch):
    staging = _dataset(tmp_path, monkeypatch)

    summary = build_derived_indexes(staging)

    # Nothing lands beside the dataset but the build-stats log.
    assert {p.name for p in tmp_path.iterdir()} == {"lancedb-staging", "preamble", "ops"}
    bm25 = staging / "derived" / "bm25" / f"v{summary.corpus_version}"
    assert sorted(json.loads((bm25 / "chunk_ids.json").read_text())) == [
        f"{pid}#c0" for pid in PAPERS
    ]
    definitions = (
        lancedb.connect(str(staging)).open_table("definitions").to_arrow()
    )
    assert sorted(definitions.column("paper_id").to_pylist()) == sorted(PAPERS)
    assert set(definitions.column("symbol").to_pylist()) == {r"\RR"}
    conn = sqlite3.connect(str(staging / "derived" / "theorem_names.db"))
    try:
        names = {r[0] for r in conn.execute("SELECT display_name FROM theorem_names")}
    finally:
        conn.close()
    assert names == {f"Lemma of {pid}" for pid in PAPERS}


def test_rebuilding_is_safe(tmp_path, monkeypatch):
    staging = _dataset(tmp_path, monkeypatch)
    first = build_derived_indexes(staging)
    assert build_derived_indexes(staging) == first


def _snapshot(dataset: Path) -> dict[str, bytes]:
    derived = dataset / "derived"
    return {
        str(f.relative_to(derived)): f.read_bytes()
        for f in sorted(derived.rglob("*")) if f.is_file()
    }


def test_cutover_then_rollback_restores_the_live_indexes(tmp_path, monkeypatch):
    from ops.cutover import perform_directory_swap, perform_rollback
    from server.config import Config

    live = _dataset(tmp_path, monkeypatch, "lancedb", PAPERS[:1])
    build_derived_indexes(live)
    staging = _dataset(tmp_path, monkeypatch, "lancedb-staging", PAPERS)
    build_derived_indexes(staging)
    before = _snapshot(live)
    staged = _snapshot(staging)
    served = Config(lancedb_path=live)

    perform_directory_swap(
        active_path=live, staging_path=staging,
        rollback_path=tmp_path / "lancedb-prev",
    )
    assert _snapshot(live) == staged
    perform_rollback(active_path=live, rollback_path=tmp_path / "lancedb-prev")

    assert _snapshot(live) == before
    assert served.theorem_names_db_path.read_bytes() == before["theorem_names.db"]
    assert served.bm25_index_root.is_relative_to(live)
