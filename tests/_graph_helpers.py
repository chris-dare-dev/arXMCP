"""Shared test helpers for the citation-graph milestones (E09_*).

Lifted from the per-test ``_build_lancedb`` / per-fixture ``kuzu_db``
patterns originally inline in ``tests/test_graph_queries.py`` and
``tests/test_intra_paper_refs.py``. E09_S04 introduces a 50-paper
synthetic graph for the proof-chain workflow perf-gate test; rather
than duplicate the fixture-building code for the third time,
consolidate here.

Existing tests in ``test_graph_queries.py`` and
``test_intra_paper_refs.py`` continue to use their inline helpers —
no refactor in this milestone (keeps the diff focused; the existing
tests are working as-is).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import kuzu

from ingest import graph_ingest, kuzudb_schema


def build_synthetic_kuzu_graph(
    db_path: Path,
    n_papers: int,
    edges_per_paper: int = 3,
    source: str = "openAlex",
    paper_id_prefix: str = "2605.",
    paper_id_start: int = 90000,
) -> list[str]:
    """Materialize a synthetic Kùzu graph in ``db_path``.

    Each paper ``P_i`` (for ``i in range(n_papers)``) carries
    ``edges_per_paper`` outgoing ``cites`` edges to its preceding
    papers ``P_{i-1}``, ``P_{i-2}``, ..., ``P_{i-edges_per_paper}``
    (mod ``n_papers``). For ``n_papers = 50`` and
    ``edges_per_paper = 3`` this produces 150 deterministic edges
    and a roughly uniform out-degree.

    The first ``edges_per_paper`` papers cite earlier indices that
    wrap (mod n_papers); this means P_0 has outgoing edges to
    P_{n-1}, P_{n-2}, P_{n-3} — so depth=2 from P_0 reaches
    ~9 distinct papers and exercises the dedup path.

    Args:
        db_path: where to materialize the DB. Caller's responsibility
            to make sure ``db_path.parent`` exists.
        n_papers: number of synthetic papers to create.
        edges_per_paper: outgoing-edges-per-paper (each is a cites
            edge to a preceding paper).
        source: ``cites.source`` value to write on every edge.
            Default ``"openAlex"`` mirrors the production cite-edge
            casing.
        paper_id_prefix: leading digits of the synthetic arXiv-style
            paper_id. Default ``"2605."`` matches the seed corpus
            range (post-2026 math.AG).
        paper_id_start: the integer the suffix counter starts at.

    Returns:
        The list of paper_ids in iteration order ``[P_0, P_1, ...,
        P_{n-1}]``.
    """
    if n_papers <= 0:
        raise ValueError(f"n_papers must be positive, got {n_papers}")
    if edges_per_paper < 0:
        raise ValueError(
            f"edges_per_paper must be non-negative, got {edges_per_paper}"
        )
    paper_ids = [
        f"{paper_id_prefix}{paper_id_start + i:05d}" for i in range(n_papers)
    ]

    kuzudb_schema.apply_schema(db_path)
    db = kuzu.Database(str(db_path))
    conn = None
    try:
        conn = kuzu.Connection(db)
        for paper_id in paper_ids:
            conn.execute(
                "MERGE (p:papers {paper_id: $id}) "
                "ON CREATE SET p.title = $title",
                {"id": paper_id, "title": f"Title-{paper_id}"},
            )
        # Each paper cites its `edges_per_paper` preceding indices
        # (mod n_papers). Deterministic so the test pins reproducibly.
        for i in range(n_papers):
            for k in range(1, edges_per_paper + 1):
                src = paper_ids[i]
                dst = paper_ids[(i - k) % n_papers]
                graph_ingest._merge_cite(
                    conn,
                    src_paper_id=src,
                    dst_paper_id=dst,
                    source=source,
                    confidence=1.0,
                )
    finally:
        # Explicit close releases kuzu's file lock deterministically (conn
        # before db, nested so db.close() runs even if conn.close() raises).
        try:
            if conn is not None:
                conn.close()
        finally:
            db.close()
    return paper_ids


def build_synthetic_lancedb(
    lancedb_path: Path,
    rows: list[dict[str, Any]],
) -> Path:
    """Materialize a minimal LanceDB ``chunks`` table for tests.

    Mirrors the inline `_build_lancedb` helper from
    ``tests/test_graph_queries.py::TestE09S03RectificationGuards`` —
    same Arrow-payload shape, same required-field placeholders.
    Lifted so the E09_S04 perf test can build 50-paper chunks
    fixtures without copying 30 lines of setup.

    Args:
        lancedb_path: directory the LanceDB will live under. Will be
            created by ``lancedb.connect``.
        rows: list of partial-row dicts. Each must include ``chunk_id``
            and ``paper_id``; missing required-non-nullable columns
            (``section_path`` / ``body_text`` / ``body_tokens`` /
            ``chunker_version`` / ``embedder_version``) get
            placeholder values. Missing nullable columns get None.

    Returns: ``lancedb_path``.
    """
    import lancedb
    import pyarrow as pa

    from ingest.schema import CHUNKS_SCHEMA_V1

    db = lancedb.connect(str(lancedb_path))
    placeholder_required = {
        "section_path": [],
        "body_text": "",
        "body_tokens": "",
        "chunker_version": "test",
        "embedder_version": "test",
    }
    payload: dict[str, list[Any]] = {field.name: [] for field in CHUNKS_SCHEMA_V1}
    for row in rows:
        full_row = {**placeholder_required, **row}
        for field in CHUNKS_SCHEMA_V1:
            payload[field.name].append(full_row.get(field.name))
    table = pa.Table.from_pydict(payload, schema=CHUNKS_SCHEMA_V1)
    db.create_table("chunks", data=table, mode="create")
    return lancedb_path
