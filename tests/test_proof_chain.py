"""Integration test for E09_S04 — 2-round cross-paper proof chain pattern.

Closes H7 (in combination with E09_S03's ``cite_neighbors``
implementation). Verifies the agent-side workflow documented in
``docs/proof-chain-workflow.md``:

  Round 1: cite_neighbors(chunk_id=<entry>, depth=2, direction="cites")
  Round 2: asyncio.gather(*[get_chunk(c) for c in neighbors if c.chunk_id])
  Total rounds: 2 (fits the 3-round budget from E08).

The test uses a synthetic 50-paper Kùzu graph (matching AC#3's
"50-paper corpus" language) plus a synthetic LanceDB chunks table —
the real ingested seed corpus isn't materialized in CI. See
``research-synthesis.md`` § 3 for the design rationale.

The ``chunk_id=None`` branch (AC#5 fallback) is exercised by leaving
exactly ONE paper out of the LanceDB fixture while still present in
Kùzu — the test asserts the neighbor for that paper has
``chunk_id=None`` and is correctly skipped from the round-2
``get_chunk`` calls.

Performance gate (AC#3): ``cite_neighbors(depth=2)`` MUST complete
in ≤ 500 ms on the 50-paper graph. Measured with ``time.monotonic``
(no ``pytest-benchmark`` dep — matches the project's existing
performance-test precedent at ``tests/test_server_startup.py:211``
and ``tests/retrieval/test_*.py``).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from server.graph_queries import cite_neighbors
from server.graph_types import CitationNeighbor
from server.handlers.chunk import handle_get_chunk
from server.tools import reset_resources_for_tests, set_resources
from tests._graph_helpers import build_synthetic_kuzu_graph, build_synthetic_lancedb

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

N_PAPERS = 50
# F1 fix from the E09_S04 critique: densified from 3 → 10 edges per
# paper so the synthetic graph approximates real OpenAlex+INSPIRE
# citation density (math.AG papers typically reference 10-60 others).
# 50 papers × 10 = 500 edges; depth=2 BFS from any node can reach up
# to ~100 papers before the max_results=50 cap fires. This stresses
# the BFS + dedup path more meaningfully than the original 150-edge
# fixture while still completing well under the 500ms perf gate.
EDGES_PER_PAPER = 10
EXPECTED_EDGE_COUNT = N_PAPERS * EDGES_PER_PAPER  # 500; pin via fixture assertion
PAPER_ID_PREFIX = "2605."
PAPER_ID_START = 90000

# The hex suffix is synthetic-but-realistic per the doc's callout.
# We just use the paper index padded to 16 hex chars.
def _chunk_id_for(paper_id: str, idx: int) -> str:
    return f"arxiv:{paper_id}:{idx:016x}"


@pytest.fixture
def graph_corpus(tmp_path: Path) -> dict:
    """Materialize the 50-paper synthetic graph + LanceDB chunks.

    Exactly ONE paper (the LAST one) is intentionally LEFT OUT of the
    LanceDB chunks fixture — this paper exists as a node in Kùzu but
    has no chunk in LanceDB, exercising the ``chunk_id=None``
    branch (AC#5).

    F3 fix from the E09_S04 critique: the fixture asserts that the
    entry paper (P_0) cites the missing paper (P_{N-1}) so the AC#7
    test's `missing in by_pid` assertion can't silently pass if a
    future helper refactor changes the edge-wiring semantics.
    """
    import kuzu

    kuzu_path = tmp_path / "kuzu"
    paper_ids = build_synthetic_kuzu_graph(
        db_path=kuzu_path,
        n_papers=N_PAPERS,
        edges_per_paper=EDGES_PER_PAPER,
        source="openAlex",
        paper_id_prefix=PAPER_ID_PREFIX,
        paper_id_start=PAPER_ID_START,
    )

    # F3 fixture-time assertion: edge wiring is what AC#7 depends on.
    db = kuzu.Database(str(kuzu_path))
    try:
        conn = kuzu.Connection(db)
        edge_count_result = conn.execute(
            "MATCH ()-[r:cites]->() RETURN COUNT(*)"
        )
        edge_count = edge_count_result.get_next()[0]
        assert edge_count == EXPECTED_EDGE_COUNT, (
            f"synthetic graph has {edge_count} edges; expected "
            f"{EXPECTED_EDGE_COUNT} ({N_PAPERS} × {EDGES_PER_PAPER}). "
            "F1 guard: a future change to build_synthetic_kuzu_graph "
            "that silently lowers edge density would weaken the perf "
            "gate."
        )
        entry_cites_result = conn.execute(
            "MATCH (s:papers {paper_id: $s})-[:cites]->(n:papers) "
            "RETURN n.paper_id",
            {"s": paper_ids[0]},
        )
        entry_direct_neighbors = set()
        while entry_cites_result.has_next():
            entry_direct_neighbors.add(entry_cites_result.get_next()[0])
    finally:
        del db

    chunks_missing_paper = paper_ids[-1]
    # F3 guard: AC#7 relies on entry → missing-paper being a direct
    # (or 2-hop) edge. With EDGES_PER_PAPER=10 and mod-wrap, P_0
    # cites P_{N-1} (it's i-1 mod N). Assert at fixture time so a
    # future helper refactor surfaces a structural-change failure
    # here rather than as a silent AC#7 pass.
    assert chunks_missing_paper in entry_direct_neighbors, (
        f"AC#7 test depends on entry paper {paper_ids[0]} citing the "
        f"missing-from-LanceDB paper {chunks_missing_paper}; current "
        f"direct neighbors: {sorted(entry_direct_neighbors)}"
    )

    # Build LanceDB chunks for every paper EXCEPT the last one — that
    # one will return chunk_id=None per AC#7.
    rows = []
    for i, paper_id in enumerate(paper_ids):
        if paper_id == chunks_missing_paper:
            continue
        rows.append(
            {
                "chunk_id": _chunk_id_for(paper_id, i),
                "paper_id": paper_id,
                "kind": "stmt",
                "theorem_label": None,
                # Real body_text so AC#2's "non-null" assertion is
                # meaningful — we use a synthetic but recognizable
                # string so the test can pin the lookup wiring.
                # F7 fix: the assertion in
                # test_round_2_returns_non_null_body_text_for_all_chunks
                # now substring-matches "Statement of theorem for"
                # which is contained here. A field-swap regression
                # (handler returns chunk_id in place of body_text)
                # would fail because chunk_ids don't contain that
                # substring.
                "body_text": f"Statement of theorem for {paper_id}. "
                f"Synthetic body for proof-chain test (paper index {i}).",
            }
        )
    lancedb_path = build_synthetic_lancedb(tmp_path / "lancedb", rows)

    return {
        "paper_ids": paper_ids,
        "kuzu_path": kuzu_path,
        "lancedb_path": lancedb_path,
        "chunks_missing_paper": chunks_missing_paper,
        "entry_paper_id": paper_ids[0],
        "entry_chunk_id": _chunk_id_for(paper_ids[0], 0),
    }


@pytest.fixture
def fake_resources(graph_corpus: dict):
    """Set up the global Resources singleton so ``handle_get_chunk``
    can find the chunks table.

    Mirrors the ``_FakeResources`` pattern from
    ``tests/test_tools_all.py:482-496``. ``reset_resources_for_tests``
    runs at teardown so subsequent tests aren't polluted.
    """
    import lancedb

    from server.config import Config

    cfg = Config(result_byte_cap=256 * 1024)

    class _FakeCorpusInfo:
        version = 1

    db = lancedb.connect(str(graph_corpus["lancedb_path"]))
    chunks_table = db.open_table("chunks")

    class _FakeResources:
        config = cfg
        corpus_info = _FakeCorpusInfo()

    fake = _FakeResources()
    fake.chunks_table = chunks_table
    set_resources(fake)
    try:
        yield fake
    finally:
        # F4 fix from the E09_S04 critique: drop the LanceDB handle
        # explicitly before clearing the singleton so file
        # descriptors / Arrow buffers are released deterministically
        # (avoids GC-ordering flakes on Windows CI in long suites).
        reset_resources_for_tests()
        del chunks_table
        del db


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Round 1 — cite_neighbors
# ---------------------------------------------------------------------------


class TestRound1CiteNeighbors:
    def test_round_1_returns_at_least_one_neighbor(
        self, graph_corpus: dict
    ):
        """AC#2 round 1: ≥1 neighbor for a known entry chunk."""
        result = _run(
            cite_neighbors(
                graph_corpus["entry_chunk_id"],
                depth=2,
                direction="cites",
                kuzudb_path=graph_corpus["kuzu_path"],
                lancedb_path=graph_corpus["lancedb_path"],
            )
        )
        assert len(result) >= 1, "round 1 must surface at least one neighbor"
        for neighbor in result:
            assert isinstance(neighbor, CitationNeighbor)

    def test_round_1_returns_chunk_ids_when_paper_in_lancedb(
        self, graph_corpus: dict
    ):
        """The neighbor for an in-corpus paper has a non-None chunk_id."""
        result = _run(
            cite_neighbors(
                graph_corpus["entry_chunk_id"],
                depth=2,
                direction="cites",
                kuzudb_path=graph_corpus["kuzu_path"],
                lancedb_path=graph_corpus["lancedb_path"],
            )
        )
        any_present = any(n.chunk_id is not None for n in result)
        assert any_present, (
            "at least one neighbor should resolve to a real chunk_id"
        )


# ---------------------------------------------------------------------------
# Round 2 — bulk parallel get_chunk
# ---------------------------------------------------------------------------


class TestRound2BulkGetChunk:
    def test_round_2_returns_non_null_body_text_for_all_chunks(
        self, graph_corpus: dict, fake_resources
    ):
        """AC#2 round 2: every returned chunk_id (skipping None)
        resolves via ``handle_get_chunk`` to a non-null body_text.

        Uses ``asyncio.gather`` to issue N concurrent handler calls
        — this is the canonical 2-round-pattern shape: "N parallel
        tool_use blocks in one assistant turn = one MCP round."
        """
        async def _runner() -> list:
            neighbors = await cite_neighbors(
                graph_corpus["entry_chunk_id"],
                depth=2,
                direction="cites",
                kuzudb_path=graph_corpus["kuzu_path"],
                lancedb_path=graph_corpus["lancedb_path"],
            )
            # Skip neighbors with chunk_id=None (the v1 fallback gap
            # documented in proof-chain-workflow.md).
            cids = [n.chunk_id for n in neighbors if n.chunk_id is not None]
            assert cids, "expected at least one resolvable chunk_id"
            # Round 2 — parallel.
            bodies = await asyncio.gather(
                *[handle_get_chunk(cid) for cid in cids]
            )
            return bodies

        bodies = _run(_runner())
        for body in bodies:
            assert body["found"] is True
            assert body["chunk"] is not None
            body_text = body["chunk"]["body_text"]
            assert body_text, (
                "AC#2: body_text must be non-null/non-empty for all "
                "round-2 chunks"
            )
            # F7 fix from the E09_S04 critique: substring-pin to the
            # synthetic body's signature phrase so a field-swap
            # regression (handler returning, say, chunk_id in place
            # of body_text) trips the assertion. Without this, ANY
            # non-empty string would pass — too weak for AC#2.
            assert "Statement of theorem for" in body_text, (
                f"body_text does not contain the synthetic signature "
                f"phrase; got: {body_text[:80]!r}. A field-swap "
                "regression would silently pass without this guard."
            )


# ---------------------------------------------------------------------------
# AC#5 — chunk_id=None branch
# ---------------------------------------------------------------------------


class TestChunkIdNoneBranch:
    def test_paper_missing_from_lancedb_returns_chunk_id_none(
        self, graph_corpus: dict
    ):
        """AC#5 / AC#7: the paper that's in Kùzu but NOT in LanceDB
        must surface a ``chunk_id=None`` neighbor.

        The entry paper at index 0 cites P_{N-1} (and P_{N-2},
        P_{N-3}) per the synthetic graph's edge pattern. P_{N-1}
        is the missing-from-LanceDB paper.
        """
        result = _run(
            cite_neighbors(
                graph_corpus["entry_chunk_id"],
                depth=2,
                direction="cites",
                kuzudb_path=graph_corpus["kuzu_path"],
                lancedb_path=graph_corpus["lancedb_path"],
            )
        )
        by_pid = {n.paper_id: n for n in result}
        missing = graph_corpus["chunks_missing_paper"]
        assert missing in by_pid, (
            f"the synthetic graph wires P_0 -> {missing}; expected it "
            "in the round-1 result"
        )
        assert by_pid[missing].chunk_id is None, (
            "missing-from-LanceDB paper must surface chunk_id=None "
            "(AC#7) — the v1 fallback gap means the agent skips it "
            "rather than spending a third round"
        )

    def test_chunk_id_none_neighbors_skipped_from_round_2(
        self, graph_corpus: dict, fake_resources
    ):
        """Per ``docs/proof-chain-workflow.md``, the agent SKIPS
        neighbors with ``chunk_id=None`` rather than spending a third
        round on ``search_papers(filters={"paper_id": ...})`` —
        because v1's filter is ignored.
        """
        async def _runner():
            neighbors = await cite_neighbors(
                graph_corpus["entry_chunk_id"],
                depth=2,
                direction="cites",
                kuzudb_path=graph_corpus["kuzu_path"],
                lancedb_path=graph_corpus["lancedb_path"],
            )
            none_count = sum(1 for n in neighbors if n.chunk_id is None)
            cids = [n.chunk_id for n in neighbors if n.chunk_id is not None]
            bodies = await asyncio.gather(
                *[handle_get_chunk(cid) for cid in cids]
            )
            return none_count, len(cids), len(bodies)

        none_count, present_count, body_count = _run(_runner())
        # At least one None (the missing-from-LanceDB paper).
        assert none_count >= 1
        # Round 2 calls handle_get_chunk for ONLY the present ones.
        assert body_count == present_count


# ---------------------------------------------------------------------------
# AC#3 — performance gate
# ---------------------------------------------------------------------------


class TestPerfGate:
    def test_perf_gate_500ms(self, graph_corpus: dict):
        """AC#3: cite_neighbors(depth=2) MUST complete in ≤ 500 ms on
        the 50-paper synthetic graph.

        Measurement: ``time.monotonic`` deltas around the await. This
        matches the project's existing performance-test precedent
        (``tests/test_server_startup.py:211``,
        ``tests/retrieval/test_bm25.py:228``,
        ``tests/eval/test_retrieval_quality.py:424``). No
        ``pytest-benchmark`` dep, no new test marker — runs always.

        If this test flakes on CI under load, the recommended fix
        (per research-synthesis.md § 4) is to raise the cap to
        1.0 s with a one-line TODO; do NOT mark the test as
        ``@pytest.mark.bench`` or skip it conditionally — the
        500ms guarantee is project-wide.
        """
        async def _runner():
            start = time.monotonic()
            result = await cite_neighbors(
                graph_corpus["entry_chunk_id"],
                depth=2,
                direction="cites",
                max_results=50,
                kuzudb_path=graph_corpus["kuzu_path"],
                lancedb_path=graph_corpus["lancedb_path"],
            )
            elapsed = time.monotonic() - start
            return elapsed, result

        elapsed, result = _run(_runner())
        assert len(result) >= 1
        assert elapsed < 0.5, (
            f"cite_neighbors(depth=2) took {elapsed * 1000:.1f}ms on "
            f"{N_PAPERS}-paper synthetic graph (AC#3 budget: 500ms). "
            "If this fires under load, raise to 1.0s with a TODO; "
            "do NOT skip-on-bench — the guarantee is project-wide."
        )


# ---------------------------------------------------------------------------
# AC#1 + AC#4 + AC#5 — documentation pins
# ---------------------------------------------------------------------------


class TestDocumentationPins:
    """The brief's documentation ACs are testable via simple
    substring checks on the doc file. Pins prevent silent doc drift
    — if a future edit removes the AC-pinned sentence, the test
    surfaces it."""

    # Moved 2026-05-10 from ``docs/`` to ``.claude/docs/`` per the
    # repo-wide doc-layout consolidation.
    DOC_PATH = (
        Path(__file__).resolve().parent.parent
        / ".claude" / "docs" / "proof-chain-workflow.md"
    )

    def test_doc_exists(self):
        assert self.DOC_PATH.exists(), (
            f".claude/docs/proof-chain-workflow.md (AC#1) missing at {self.DOC_PATH}"
        )

    def test_doc_states_total_round_count(self):
        """AC#4: the doc states 'Total round count = 2. This fits the
        3-round cap from E08. Round 1 (cite_neighbors) + Round 2
        (bulk parallel get_chunk) = 2 rounds.'

        F8 fix from the E09_S04 critique: normalize whitespace
        before substring-matching so a markdown reflow that wraps
        the phrase across lines doesn't fail this test.
        """
        text = self.DOC_PATH.read_text(encoding="utf-8")
        text_norm = " ".join(text.split())
        # Pin the load-bearing AC#4 phrases against the normalized
        # form so line-wrap reformatting can't trip them.
        assert "Total round count = 2" in text_norm
        assert "3-round cap from E08" in text_norm
        assert "Round 1" in text_norm and "Round 2" in text_norm
        assert "cite_neighbors" in text_norm and "get_chunk" in text_norm

    def test_doc_documents_chunk_id_none_fallback(self):
        """AC#5: the doc documents the chunk_id=None fallback.

        F2 fix from the E09_S04 critique: the AC#5 mandate is that
        the fallback 'counts as a third round and exhausts the
        budget.' The previous test had a 3-way disjunction that
        accepted 'deferred to E07_S04' as a substitute — but that
        phrase is about the v1 gap, not about the AC#5 invariant.
        Require the round-budget framing explicitly.
        """
        text = self.DOC_PATH.read_text(encoding="utf-8")
        text_norm = " ".join(text.split())
        assert (
            "chunk_id=None" in text_norm
            or "chunk_id` is `None`" in text_norm
            or "chunk_id is None" in text_norm
        )
        assert "search_papers" in text_norm
        # F2: pin the round-budget AC#5 framing — at least ONE of
        # "third round" or "exhausts" must be present; "deferred"
        # alone is insufficient.
        assert "third round" in text_norm or "exhausts" in text_norm, (
            "AC#5 mandates that the doc state the chunk_id=None "
            "fallback counts as a third round and exhausts the "
            "budget. F2 tightening: 'deferred to E07_S04' is about "
            "the v1 gap, not the round-budget invariant."
        )

    def test_doc_includes_worked_example(self):
        text = self.DOC_PATH.read_text(encoding="utf-8")
        # The worked example shows both rounds with concrete calls.
        assert "Round 1:" in text
        assert "Round 2" in text
        assert "asyncio.gather" in text


# ---------------------------------------------------------------------------
# verification-feedback-m1 — cite_neighbors HANDLER end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def handler_resources(graph_corpus: dict):
    """Resources singleton wired so ``handle_cite_neighbors`` finds the
    synthetic Kùzu graph + LanceDB chunks.

    The wired handler (verification-feedback-m1) derives BOTH the Kùzu
    and LanceDB paths from ``Config`` via ``get_resources()`` — the F2
    path-validation contract — so this fixture points a real ``Config``
    at the synthetic ``graph_corpus`` paths.
    """
    from server.config import Config

    cfg = Config(
        result_byte_cap=256 * 1024,
        kuzu_path=graph_corpus["kuzu_path"],
        lancedb_path=graph_corpus["lancedb_path"],
    )

    class _FakeCorpusInfo:
        version = 1

    class _FakeResources:
        config = cfg
        corpus_info = _FakeCorpusInfo()

    set_resources(_FakeResources())
    try:
        yield
    finally:
        reset_resources_for_tests()


class TestHandlerEndToEnd:
    """verification-feedback-m1 AC#1/AC#5 — exercise the wired
    ``handle_cite_neighbors`` HANDLER end-to-end, not just the library.

    Every test here fails against the old v1 stub (which returned
    ``infrastructure_status='deferred'`` + an empty ``neighbors`` list
    regardless of input).
    """

    def test_handler_returns_real_neighbors(
        self, graph_corpus: dict, handler_resources
    ):
        """AC#1 + AC#5: the handler routes through the live library and
        returns real neighbors — verified at the HANDLER boundary, not
        only the library."""
        from server.handlers.citations import handle_cite_neighbors

        result = _run(
            handle_cite_neighbors(
                chunk_id=graph_corpus["entry_chunk_id"],
                direction="cites",
                depth=2,
            )
        )
        assert "infrastructure_status" not in result, (
            "the v1 stub key must be gone once the handler is wired"
        )
        assert result["graph_status"] == "present"
        assert result["neighbors"], "wired handler must return real neighbors"
        # corpus_version is added by envelope().
        assert result["corpus_version"] == 1
        for n in result["neighbors"]:
            assert set(n) >= {
                "paper_id", "chunk_id", "edge_kind",
                "hop_distance", "source", "confidence",
            }, f"neighbor dict missing CitationNeighbor fields: {n}"

    def test_handler_honors_cited_by_direction(
        self, graph_corpus: dict, handler_resources
    ):
        """AC#2: the handler's ``direction`` enum is re-aligned to the
        library's — ``cited_by`` is a valid library direction (the old
        stub enum had ``citers``/``cited``, never the library's set)."""
        from server.handlers.citations import handle_cite_neighbors

        result = _run(
            handle_cite_neighbors(
                chunk_id=graph_corpus["entry_chunk_id"],
                direction="cited_by",
                depth=1,
            )
        )
        assert result["direction"] == "cited_by"
        assert "infrastructure_status" not in result

    def test_handler_perf_gate_500ms(
        self, graph_corpus: dict, handler_resources
    ):
        """AC#5: the 500 ms performance gate holds at the HANDLER level
        (library call + envelope + cap + dataclasses.asdict)."""
        from server.handlers.citations import handle_cite_neighbors

        async def _runner():
            start = time.monotonic()
            result = await handle_cite_neighbors(
                chunk_id=graph_corpus["entry_chunk_id"],
                direction="cites",
                depth=2,
                limit=50,
            )
            return time.monotonic() - start, result

        elapsed, result = _run(_runner())
        assert result["neighbors"]
        assert elapsed < 0.5, (
            f"handle_cite_neighbors(depth=2) took {elapsed * 1000:.1f}ms "
            f"at the handler boundary (AC budget: 500ms). If this fires "
            f"under load, raise to 1.0s with a TODO — do not skip."
        )

    def test_handler_rejects_malformed_chunk_id(self):
        """The Threat-1 chunk_id validator fires before any resource
        access — no Resources singleton is needed for this path."""
        from server.handlers.citations import handle_cite_neighbors

        with pytest.raises(ValueError, match="chunk_id"):
            _run(handle_cite_neighbors(chunk_id="not-a-valid-chunk-id"))

    def test_handler_graph_absent_returns_empty(
        self, graph_corpus: dict, tmp_path: Path
    ):
        """When ``Config.kuzu_path`` does not exist (graph not
        ingested), the handler returns ``graph_status='absent'`` + an
        empty ``neighbors`` list rather than erroring."""
        from server.config import Config
        from server.handlers.citations import handle_cite_neighbors

        cfg = Config(
            result_byte_cap=256 * 1024,
            kuzu_path=tmp_path / "no_such_kuzu_graph",
            lancedb_path=graph_corpus["lancedb_path"],
        )

        class _FakeCorpusInfo:
            version = 1

        class _FakeResources:
            config = cfg
            corpus_info = _FakeCorpusInfo()

        set_resources(_FakeResources())
        try:
            result = _run(
                handle_cite_neighbors(
                    chunk_id=graph_corpus["entry_chunk_id"],
                    direction="cites",
                )
            )
        finally:
            reset_resources_for_tests()
        assert result["graph_status"] == "absent"
        assert result["neighbors"] == []

    def test_handler_graph_unqueryable_returns_unavailable(
        self, graph_corpus: dict, tmp_path: Path
    ):
        """verification-feedback-m1 F2 — when Config.kuzu_path exists
        but is NOT a queryable Kùzu graph (here: a stray directory —
        Kùzu 0.11.3 rejects a directory path with RuntimeError), the
        handler degrades to graph_status='unavailable' with an empty
        neighbors list, instead of letting the RuntimeError surface as
        a 5xx. Covers the half-ingested / corrupt / stray-path
        operator-failure modes the bare Path.exists() guard cannot
        distinguish."""
        from server.config import Config
        from server.handlers.citations import handle_cite_neighbors

        bad_kuzu = tmp_path / "kuzu_is_a_directory"
        bad_kuzu.mkdir()  # exists() is True; Kùzu rejects a directory path.

        cfg = Config(
            result_byte_cap=256 * 1024,
            kuzu_path=bad_kuzu,
            lancedb_path=graph_corpus["lancedb_path"],
        )

        class _FakeCorpusInfo:
            version = 1

        class _FakeResources:
            config = cfg
            corpus_info = _FakeCorpusInfo()

        set_resources(_FakeResources())
        try:
            result = _run(
                handle_cite_neighbors(
                    chunk_id=graph_corpus["entry_chunk_id"],
                    direction="cites",
                )
            )
        finally:
            reset_resources_for_tests()
        assert result["graph_status"] == "unavailable"
        assert result["neighbors"] == []

    def test_handler_exposes_no_path_param(self):
        """verification-feedback-m1 F3 — F2 path-validation contract
        regression guard. handle_cite_neighbors MUST NOT expose any
        Kùzu/LanceDB path as a parameter: the E09_S03 F2 contract
        requires graph + index paths to be Config-derived, never
        agent-supplied. A future refactor that re-adds a path param
        'for testability' fails loudly here."""
        import inspect

        from server.handlers.citations import handle_cite_neighbors

        params = set(inspect.signature(handle_cite_neighbors).parameters)
        forbidden = {
            "kuzudb_path", "kuzu_path", "lancedb_path", "lancedb",
            "db_path", "graph_path", "path",
        }
        leaked = params & forbidden
        assert not leaked, (
            f"handle_cite_neighbors exposes path param(s) {sorted(leaked)} "
            f"-- the E09_S03 F2 contract requires graph/index paths to be "
            f"Config-derived, never agent-supplied. signature: {sorted(params)}"
        )
        assert params == {"chunk_id", "direction", "depth", "limit"}, (
            f"unexpected handle_cite_neighbors signature: {sorted(params)}"
        )
