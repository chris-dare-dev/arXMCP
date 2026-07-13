"""Unit tests for E09_S03 — `cite_neighbors` graph traversal.

The tests build a 5-paper synthetic Kùzu graph in ``tmp_path`` and
exercise every direction (cites, cited_by, depends_on) at depth=1
and depth=2. The brief AC requires:

  - depth=1 returns direct neighbors;
  - depth=2 returns hop-1 + hop-2 with correct ``hop_distance``;
  - cited_by returns incoming edges;
  - depends_on returns intra-paper ref-chain results;
  - results capped at max_results=50;
  - each result includes the full dataclass shape;
  - papers in graph but not in chunks return ``chunk_id=None``.

The Kùzu DB is built directly via ``apply_schema`` + ``_merge_cite``;
the LanceDB chunk lookup is exercised via a real (but tiny) LanceDB
table in some tests, and via passing ``lancedb_path=None`` in others
to verify the all-None fallback path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import kuzu
import pytest

from ingest import graph_ingest, kuzudb_schema
from server.graph_queries import (
    DEFAULT_MAX_RESULTS,
    _build_query,
    _row_passes_direction_filter,
    cite_neighbors,
)
from server.graph_types import CitationNeighbor

# ---------------------------------------------------------------------------
# Synthetic 5-paper corpus
# ---------------------------------------------------------------------------
#
# Edge layout (all edges via ``_merge_cite``):
#
#   A → B        (openAlex)
#   A → C        (inspire)
#   B → D        (openAlex)
#   C → D        (inspire)
#   E → A        (openAlex)   — incoming for cited_by tests
#   A → A        (intra-paper) — self-loop for depends_on tests

P_A = "2401.50001"
P_B = "2401.50002"
P_C = "2401.50003"
P_D = "2401.50004"
P_E = "2401.50005"
ALL_PAPERS = [P_A, P_B, P_C, P_D, P_E]

# Source paper's chunk_id (for cite_neighbors input).
CHUNK_A = f"arxiv:{P_A}:0123456789abcdef"


@pytest.fixture
def kuzu_db(tmp_path: Path) -> Path:
    """Materialize the 5-paper synthetic graph in ``tmp_path``."""
    db_path = tmp_path / "kuzu_test"
    kuzudb_schema.apply_schema(db_path)
    db = kuzu.Database(str(db_path))
    conn = None
    try:
        conn = kuzu.Connection(db)
        for pid in ALL_PAPERS:
            conn.execute(
                "MERGE (p:papers {paper_id: $id}) "
                "ON CREATE SET p.title = $title",
                {"id": pid, "title": f"Title-{pid}"},
            )
        edges = [
            (P_A, P_B, "openAlex"),
            (P_A, P_C, "inspire"),
            (P_B, P_D, "openAlex"),
            (P_C, P_D, "inspire"),
            (P_E, P_A, "openAlex"),
            (P_A, P_A, "intra-paper"),
        ]
        for src, dst, source in edges:
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
    return db_path


def _run(coro):
    """Synchronously execute an ``async def`` test body."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Cypher query construction
# ---------------------------------------------------------------------------


class TestQueryBuilder:
    def test_cites_outgoing_arrow(self):
        q = _build_query("cites", 2)
        assert "(s:papers {paper_id: $paper_id})-[r:cites*1..2]->(n:papers)" in q
        assert "RETURN n.paper_id" in q

    def test_cited_by_reverses_arrow(self):
        q = _build_query("cited_by", 2)
        assert "(n:papers)-[r:cites*1..2]->(s:papers {paper_id: $paper_id})" in q

    def test_depends_on_uses_outgoing_arrow(self):
        # depends_on uses the same outgoing arrow as cites; the
        # difference is the direction filter, not the Cypher pattern.
        q = _build_query("depends_on", 2)
        assert "(s:papers {paper_id: $paper_id})-[r:cites*1..2]->(n:papers)" in q

    def test_depth_1_clamps_upper_bound(self):
        q = _build_query("cites", 1)
        assert "[r:cites*1..1]" in q

    def test_invalid_depth_raises(self):
        with pytest.raises(ValueError):
            _build_query("cites", 0)
        with pytest.raises(ValueError):
            _build_query("cites", 3)


# ---------------------------------------------------------------------------
# Direction filter
# ---------------------------------------------------------------------------


class TestDirectionFilter:
    def test_cites_excludes_path_with_intra_paper(self):
        rels = [{"source": "openAlex"}, {"source": "intra-paper"}]
        assert _row_passes_direction_filter(rels, "cites") is False

    def test_cites_keeps_path_of_pure_citations(self):
        rels = [{"source": "openAlex"}, {"source": "inspire"}]
        assert _row_passes_direction_filter(rels, "cites") is True

    def test_depends_on_keeps_intra_paper(self):
        rels = [{"source": "intra-paper"}]
        assert _row_passes_direction_filter(rels, "depends_on") is True

    def test_cited_by_excludes_intra_paper(self):
        rels = [{"source": "intra-paper"}]
        assert _row_passes_direction_filter(rels, "cited_by") is False


# ---------------------------------------------------------------------------
# cite_neighbors — happy paths (the AC battery)
# ---------------------------------------------------------------------------


class TestCiteNeighborsCites:
    def test_depth_1_returns_direct_outgoing(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        ids = sorted(n.paper_id for n in result)
        assert ids == sorted([P_B, P_C])
        for neighbor in result:
            assert neighbor.hop_distance == 1
            assert neighbor.edge_kind == "cites"
            assert neighbor.confidence == pytest.approx(1.0)

    def test_depth_2_returns_hop1_and_hop2(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=2,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        # Expected hop_distance per paper:
        #   B: 1 (A→B)
        #   C: 1 (A→C)
        #   D: 2 (A→B→D and A→C→D — same shortest hop)
        # E and A excluded (E points TO A; A is the source via self-loop).
        by_pid = {n.paper_id: n for n in result}
        assert P_B in by_pid and by_pid[P_B].hop_distance == 1
        assert P_C in by_pid and by_pid[P_C].hop_distance == 1
        assert P_D in by_pid and by_pid[P_D].hop_distance == 2
        assert P_E not in by_pid
        assert P_A not in by_pid  # self-loop excluded for "cites"

    def test_dedup_keeps_smallest_hop_distance(self, kuzu_db: Path):
        """D is reachable via TWO depth-2 paths (A→B→D and A→C→D); the
        result list must contain D exactly once."""
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=2,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        d_count = sum(1 for n in result if n.paper_id == P_D)
        assert d_count == 1

    def test_results_ordered_by_hop_then_paper_id(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=2,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        # B, C are hop=1 (lex order: B then C); D is hop=2.
        order = [(n.hop_distance, n.paper_id) for n in result]
        assert order == [(1, P_B), (1, P_C), (2, P_D)]


class TestCiteNeighborsCitedBy:
    def test_cited_by_returns_incoming_edges(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cited_by",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        # E → A is the only incoming edge to A (A → A self-loop is
        # filtered for cited_by).
        ids = [n.paper_id for n in result]
        assert ids == [P_E]
        assert result[0].edge_kind == "cited_by"
        assert result[0].hop_distance == 1


class TestCiteNeighborsDependsOn:
    def test_depends_on_includes_intra_paper_self_loop(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="depends_on",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        # The A→A self-loop is the intra-paper ref edge; for
        # depends_on it MUST be returned, with edge_kind="ref".
        # depth=1 outgoing also includes B and C (cite-edges) per the
        # synthesis "depends_on follows any cites edge for cross-paper
        # fallback" rule.
        by_pid = {n.paper_id: n for n in result}
        assert P_A in by_pid
        assert by_pid[P_A].edge_kind == "ref"
        assert by_pid[P_A].source == "intra-paper"
        # Cross-paper cites edges also returned (fallback).
        assert P_B in by_pid
        assert P_C in by_pid


# ---------------------------------------------------------------------------
# AC#5 cap + AC#7 chunk_id None
# ---------------------------------------------------------------------------


class TestMaxResultsAndChunkIdNone:
    def test_max_results_caps_returned_count(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=2,
                direction="cites",
                max_results=2,
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        assert len(result) == 2
        # Cap applied after dedup + ordering, so the first two
        # (by hop, paper_id) survive.
        assert [n.paper_id for n in result] == [P_B, P_C]

    def test_chunk_id_none_when_lancedb_path_none(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        for neighbor in result:
            assert neighbor.chunk_id is None

    def test_max_results_zero_returns_empty(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                max_results=0,
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        assert result == []

    def test_default_max_results_is_50(self):
        assert DEFAULT_MAX_RESULTS == 50


# ---------------------------------------------------------------------------
# Result dataclass shape (AC#6)
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_each_result_includes_all_fields(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        assert len(result) > 0
        for neighbor in result:
            assert isinstance(neighbor, CitationNeighbor)
            assert isinstance(neighbor.paper_id, str)
            assert neighbor.hop_distance in (1, 2)
            assert isinstance(neighbor.source, str)
            assert isinstance(neighbor.confidence, float)
            assert isinstance(neighbor.edge_kind, str)
            # chunk_id is allowed to be None per AC#7.

    def test_source_field_is_raw_value(self, kuzu_db: Path):
        """Source string is the raw rel-table value (no normalization).
        OpenAlex: 'openAlex' camelCase. INSPIRE: 'inspire' lowercase."""
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        sources = {n.source for n in result}
        assert sources == {"openAlex", "inspire"}


# ---------------------------------------------------------------------------
# chunk_id input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_invalid_chunk_id_raises(self, kuzu_db: Path):
        with pytest.raises(ValueError):
            _run(
                cite_neighbors(
                    "../../etc/passwd",
                    depth=1,
                    direction="cites",
                    kuzudb_path=kuzu_db,
                    lancedb_path=None,
                )
            )

    def test_chunk_id_without_paper_id_segment_raises(self, kuzu_db: Path):
        with pytest.raises(ValueError):
            _run(
                cite_neighbors(
                    "not-a-chunk-id",
                    depth=1,
                    direction="cites",
                    kuzudb_path=kuzu_db,
                    lancedb_path=None,
                )
            )

    def test_invalid_depth_raises(self, kuzu_db: Path):
        with pytest.raises(ValueError):
            _run(
                cite_neighbors(
                    CHUNK_A,
                    depth=5,
                    direction="cites",
                    kuzudb_path=kuzu_db,
                    lancedb_path=None,
                )
            )


# ---------------------------------------------------------------------------
# Identifier helper
# ---------------------------------------------------------------------------


class TestE09S03RectificationGuards:
    """Regression tests for findings closed by the E09_S03 rect commit.

    Each test corresponds to a finding (F1, F3, F4, F5, F8). Pin the
    rectified behavior so a future refactor can't silently re-open
    a closed finding.
    """

    def _build_lancedb(
        self,
        tmp_path: Path,
        rows: list[dict],
    ) -> Path:
        """Helper: materialize a tiny LanceDB chunks table.

        Used by F1 + F5 tests that need to exercise the
        real-LanceDB-but-paper-missing branches.
        """
        import lancedb
        import pyarrow as pa

        from ingest.schema import CHUNKS_SCHEMA_V1

        lancedb_path = tmp_path / "lancedb"
        db = lancedb.connect(str(lancedb_path))
        placeholder_required = {
            "section_path": [],
            "body_text": "",
            "body_tokens": "",
            "chunker_version": "test",
            "embedder_version": "test",
        }
        payload: dict = {field.name: [] for field in CHUNKS_SCHEMA_V1}
        for row in rows:
            full_row = {**placeholder_required, **row}
            for field in CHUNKS_SCHEMA_V1:
                payload[field.name].append(full_row.get(field.name))
        table = pa.Table.from_pydict(payload, schema=CHUNKS_SCHEMA_V1)
        db.create_table("chunks", data=table, mode="create")
        return lancedb_path

    def test_f1_chunk_id_none_for_paper_missing_from_real_lancedb(
        self, kuzu_db: Path, tmp_path: Path
    ):
        """F1: AC#7 must hold when the LanceDB EXISTS but the result
        paper is genuinely absent from it. The pre-rect test only
        exercised the ``lancedb_path=None`` shortcut."""
        # Build a LanceDB containing chunks for ONLY P_B; depth=1
        # cites returns P_B and P_C, so P_C must come back with
        # chunk_id=None while P_B has a real chunk_id.
        lancedb_path = self._build_lancedb(
            tmp_path,
            rows=[
                {
                    "chunk_id": f"arxiv:{P_B}:0000000000000001",
                    "paper_id": P_B,
                    "kind": "stmt",
                    "theorem_label": None,
                },
            ],
        )
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=lancedb_path,
            )
        )
        by_pid = {n.paper_id: n.chunk_id for n in result}
        assert by_pid[P_B] == f"arxiv:{P_B}:0000000000000001"
        assert by_pid[P_C] is None

    def test_f3_cited_by_depth_2_arrow_reversal(self, kuzu_db: Path):
        """F3: depth=2 cited_by exercises the arrow-reversal in
        ``_build_query`` end-to-end. The fixture has only one
        incoming edge to A (E→A), so depth=2 returns just E (no
        hop-2 incoming). Asserting that explicitly is non-vacuous —
        if dedup were broken or the arrow flipped wrong, the result
        list would change."""
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=2,
                direction="cited_by",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        assert [(n.paper_id, n.hop_distance) for n in result] == [(P_E, 1)]
        assert result[0].edge_kind == "cited_by"

    def test_f4_depends_on_depth_2_dedups_self_loop_paths(
        self, kuzu_db: Path
    ):
        """F4: depth=2 depends_on with the A→A self-loop. The dedup
        keeps the smallest hop_distance; A is hop=1 (direct
        self-loop), B and C are hop=1 (direct cites edges, NOT via
        A→A→B). Pinning the dedup behavior on the self-loop branch."""
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=2,
                direction="depends_on",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        by_pid = {n.paper_id: n for n in result}
        # A is in the result via the intra-paper self-loop (hop=1).
        assert P_A in by_pid
        assert by_pid[P_A].hop_distance == 1
        assert by_pid[P_A].edge_kind == "ref"
        # B and C are direct cites — hop_distance=1, not 2.
        assert by_pid[P_B].hop_distance == 1
        assert by_pid[P_C].hop_distance == 1
        # D is reachable at hop=2 via A→B→D and A→C→D — appears once.
        assert by_pid[P_D].hop_distance == 2
        d_count = sum(1 for n in result if n.paper_id == P_D)
        assert d_count == 1

    def test_f5_priority_list_falls_back_to_lemma(
        self, kuzu_db: Path, tmp_path: Path
    ):
        """F5: a paper with NO ``kind="stmt"`` chunk falls back to
        the next priority kind (``lemma``)."""
        lancedb_path = self._build_lancedb(
            tmp_path,
            rows=[
                {
                    "chunk_id": f"arxiv:{P_B}:0000000000000001",
                    "paper_id": P_B,
                    "kind": "lemma",  # NO stmt; lemma is the fallback
                    "theorem_label": None,
                },
            ],
        )
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=lancedb_path,
            )
        )
        by_pid = {n.paper_id: n.chunk_id for n in result}
        # The lemma chunk is the representative.
        assert by_pid[P_B] == f"arxiv:{P_B}:0000000000000001"

    def test_f5_priority_list_prefers_stmt_over_lemma(
        self, kuzu_db: Path, tmp_path: Path
    ):
        """F5: when both ``stmt`` AND ``lemma`` chunks exist for a
        paper, the lookup picks the ``stmt`` chunk."""
        lancedb_path = self._build_lancedb(
            tmp_path,
            rows=[
                {
                    "chunk_id": f"arxiv:{P_B}:0000000000000002",
                    "paper_id": P_B,
                    "kind": "lemma",
                    "theorem_label": None,
                },
                {
                    "chunk_id": f"arxiv:{P_B}:0000000000000001",
                    "paper_id": P_B,
                    "kind": "stmt",
                    "theorem_label": None,
                },
            ],
        )
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=lancedb_path,
            )
        )
        by_pid = {n.paper_id: n.chunk_id for n in result}
        # stmt chunk wins over lemma.
        assert by_pid[P_B] == f"arxiv:{P_B}:0000000000000001"

    def test_f8_invalid_direction_raises_early(self, kuzu_db: Path):
        """F8: a typo or prompt-injection in the direction argument
        must raise ``ValueError``, not silently degrade to
        cites-like behavior."""
        with pytest.raises(ValueError) as excinfo:
            _run(
                cite_neighbors(
                    CHUNK_A,
                    depth=1,
                    direction="other",  # type: ignore[arg-type]
                    kuzudb_path=kuzu_db,
                    lancedb_path=None,
                )
            )
        assert "direction" in str(excinfo.value)


class TestCiteNeighborsReopenReleasesLock:
    """Behavioral guard for the kuzu 0.11.3 close-discipline fix.

    Two ``cite_neighbors`` calls against the SAME ``kuzudb_path`` in ONE
    process must not raise kuzu's ``RuntimeError: ... Could not set lock on
    file`` — the first call must release the DB lock (explicit conn-then-db
    close) before the second reopens it.

    Honesty note (verified this session on CPython 3.11, Windows): because
    ``cite_neighbors`` binds ``db``/``conn`` as locals with no reference cycle,
    CPython refcounting frees them at function return, so this happy-path
    double-call does NOT by itself reproduce the pre-fix lock leak here — it
    passed on reverted ``del db`` code too. The deterministic failure needs a
    live ``kuzu.Connection`` to outlive the reopen (a retained traceback
    pinning the frame, or a non-refcounting runtime such as PyPy); the explicit
    close makes that impossible regardless. This test therefore guards the
    reopen contract and the close discipline; the fix's correctness rests on
    matching the proven deterministic-close idiom from
    ``adhoc-20260712-955c958`` and kuzu's documented close-before-db ordering.
    POSIX advisory locks tolerate same-process overlap, so the assertion is a
    no-op there. See milestone ``adhoc-20260712-698fead``.
    """

    def test_second_call_same_path_does_not_lock(self, kuzu_db: Path):
        first = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        # Back-to-back reopen with minimal intervening work — the tightest
        # window for a leaked lock to still be held on Windows pre-fix.
        try:
            second = _run(
                cite_neighbors(
                    CHUNK_A,
                    depth=1,
                    direction="cites",
                    kuzudb_path=kuzu_db,
                    lancedb_path=None,
                )
            )
        except RuntimeError as exc:
            pytest.fail(
                "cite_neighbors did not release the kuzu file lock across "
                f"two same-process calls: {exc}"
            )
        # Both reopens resolve the same 5-paper graph identically.
        assert {n.paper_id for n in first} == {P_B, P_C}
        assert {n.paper_id for n in second} == {P_B, P_C}

    def test_cite_neighbors_closes_conn_then_db(
        self, kuzu_db: Path, monkeypatch
    ):
        """Deterministic guard: cite_neighbors closes conn THEN db.

        Unlike the reopen test above (which is timing-dependent and passes
        even on pre-fix ``del db`` code under CPython refcounting), this spies
        on ``kuzu.Database.close`` / ``kuzu.Connection.close`` and asserts both
        were invoked, conn before db. Reverting to ``finally: del db`` (no
        close), dropping either close, or reversing the order makes this RED
        deterministically on every runtime, independent of GC semantics.
        """
        import server.graph_queries as gq

        real_database = gq.kuzu.Database
        real_connection = gq.kuzu.Connection
        closed: list[str] = []

        class _DBSpy:
            def __init__(self, path):
                self._real = real_database(path)

            def close(self):
                closed.append("db")
                self._real.close()

            def __getattr__(self, name):
                return getattr(self._real, name)

        class _ConnSpy:
            def __init__(self, db):
                self._real = real_connection(db._real)

            def close(self):
                closed.append("conn")
                self._real.close()

            def __getattr__(self, name):
                return getattr(self._real, name)

        monkeypatch.setattr(gq.kuzu, "Database", _DBSpy)
        monkeypatch.setattr(gq.kuzu, "Connection", _ConnSpy)

        _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )

        # Both handles closed (not leaked via del db), conn before db.
        assert closed == ["conn", "db"], closed


class TestPaperIdFromChunkId:
    def test_extracts_paper_id(self):
        from ingest.identifiers import paper_id_from_chunk_id

        assert (
            paper_id_from_chunk_id("arxiv:2401.00001:0123456789abcdef")
            == "2401.00001"
        )

    def test_old_style_paper_id(self):
        from ingest.identifiers import paper_id_from_chunk_id

        assert (
            paper_id_from_chunk_id("arxiv:hep-th/9711200:0123456789abcdef")
            == "hep-th/9711200"
        )

    def test_invalid_input_raises(self):
        from ingest.identifiers import paper_id_from_chunk_id

        for bad in ["", "no-prefix", "arxiv:bad:xyz", "arxiv:2401.0001:short"]:
            with pytest.raises(ValueError):
                paper_id_from_chunk_id(bad)

    def test_non_string_raises(self):
        from ingest.identifiers import paper_id_from_chunk_id

        with pytest.raises(ValueError):
            paper_id_from_chunk_id(None)  # type: ignore[arg-type]
