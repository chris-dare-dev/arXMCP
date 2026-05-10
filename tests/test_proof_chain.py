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
EDGES_PER_PAPER = 3
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
    """
    kuzu_path = tmp_path / "kuzu"
    paper_ids = build_synthetic_kuzu_graph(
        db_path=kuzu_path,
        n_papers=N_PAPERS,
        edges_per_paper=EDGES_PER_PAPER,
        source="openAlex",
        paper_id_prefix=PAPER_ID_PREFIX,
        paper_id_start=PAPER_ID_START,
    )

    # Build LanceDB chunks for every paper EXCEPT the last one — that
    # one will return chunk_id=None per AC#7.
    chunks_missing_paper = paper_ids[-1]
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
        reset_resources_for_tests()


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
            assert body["chunk"]["body_text"], (
                "AC#2: body_text must be non-null/non-empty for all "
                "round-2 chunks"
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

    DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "proof-chain-workflow.md"

    def test_doc_exists(self):
        assert self.DOC_PATH.exists(), (
            f"docs/proof-chain-workflow.md (AC#1) missing at {self.DOC_PATH}"
        )

    def test_doc_states_total_round_count(self):
        """AC#4: the doc states 'Total round count = 2. This fits the
        3-round cap from E08. Round 1 (cite_neighbors) + Round 2
        (bulk parallel get_chunk) = 2 rounds.'"""
        text = self.DOC_PATH.read_text(encoding="utf-8")
        # Tolerant of formatting variations (backticks, line breaks)
        # — pin the load-bearing phrases.
        assert "Total round count = 2" in text
        assert "3-round cap from E08" in text
        assert "Round 1" in text and "Round 2" in text
        assert "cite_neighbors" in text and "get_chunk" in text

    def test_doc_documents_chunk_id_none_fallback(self):
        """AC#5: the doc documents the chunk_id=None fallback (with
        the v1-search-filter caveat)."""
        text = self.DOC_PATH.read_text(encoding="utf-8")
        assert (
            "chunk_id=None" in text
            or "chunk_id` is `None`" in text
            or "chunk_id is None" in text
        )
        assert "search_papers" in text
        assert "third round" in text or "exhausts" in text or "deferred to E07_S04" in text

    def test_doc_includes_worked_example(self):
        text = self.DOC_PATH.read_text(encoding="utf-8")
        # The worked example shows both rounds with concrete calls.
        assert "Round 1:" in text
        assert "Round 2" in text
        assert "asyncio.gather" in text
