"""REST citation-graph read endpoint (stage2/arx-a45 — AC-A.20).

``GET /api/v1/notebooks/{slug}/graph/neighbors`` must mirror the MCP
``cite_neighbors`` handler's envelope vocabulary and its
``present`` / ``absent`` / ``unavailable`` degradation semantics
(``server/handlers/citations.py``, verification-feedback-m1). The MCP
handler itself is NOT touched by this slice (E-1: already wired) —
its behavior here is exercised only as the parity oracle.

Harness: the ``tests/test_api_v1.py`` minimal-app pattern + the
``tests/_graph_helpers.py`` synthetic Kùzu builder (E09_S04). No
network, no models; Kùzu on tmp_path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.config import Config
from server.notebooks_store import NotebooksStore
from server.routes.api_v1 import API_V1_FORMAT_VERSION
from server.routes.api_v1 import router as api_v1_router
from tests._graph_helpers import build_synthetic_kuzu_graph
from tools import _notebook_common

_N_PAPERS = 12
_EDGES_PER_PAPER = 3


@pytest.fixture(scope="module")
def synthetic_graph(tmp_path_factory) -> dict:
    """Module-scoped synthetic Kùzu graph (builds once; read-only)."""
    root = tmp_path_factory.mktemp("graph")
    kuzu_dir = root / "kuzu"
    paper_ids = build_synthetic_kuzu_graph(
        kuzu_dir, n_papers=_N_PAPERS, edges_per_paper=_EDGES_PER_PAPER,
    )
    return {"kuzu_dir": kuzu_dir, "paper_ids": paper_ids}


def _make_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kuzu_path: Path,
) -> Iterator[dict]:
    base = tmp_path / "notebooks"
    base.mkdir(exist_ok=True)
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    loop = asyncio.new_event_loop()
    store = loop.run_until_complete(
        NotebooksStore.open(tmp_path / "notebooks.db")
    )
    app = FastAPI()
    app.state.notebooks_store = store
    app.state.config = Config(
        kuzu_path=kuzu_path,
        lancedb_path=tmp_path / "lancedb-absent",  # chunk_id lookup → None
    )
    app.include_router(api_v1_router, prefix="/api/v1")
    with TestClient(app) as client:
        client.post("/api/v1/notebooks", json={"slug": "graph-nb"})
        yield {"client": client, "loop": loop, "store": store}
    loop.run_until_complete(store.close())
    loop.close()


@pytest.fixture
def present_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, synthetic_graph: dict,
) -> Iterator[dict]:
    yield from _make_app(tmp_path, monkeypatch, synthetic_graph["kuzu_dir"])


@pytest.fixture
def absent_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict]:
    yield from _make_app(tmp_path, monkeypatch, tmp_path / "kuzu-missing")


@pytest.fixture
def unavailable_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict]:
    # The path EXISTS but is not a queryable Kùzu graph (stray dir with
    # junk) — the handler's documented "unavailable" trigger.
    stray = tmp_path / "kuzu-stray"
    stray.mkdir()
    (stray / "junk.bin").write_bytes(b"\x00not-a-kuzu-db\x00")
    yield from _make_app(tmp_path, monkeypatch, stray)


def _get(harness: dict, paper_id: str, **params):
    return harness["client"].get(
        "/api/v1/notebooks/graph-nb/graph/neighbors",
        params={"paper_id": paper_id, **params},
    )


# ---------------------------------------------------------------------------
# Degradation semantics — the AC-A.20 envelope triple
# ---------------------------------------------------------------------------


class TestDegradation:
    def test_absent_graph_returns_200_empty(self, absent_harness):
        r = _get(absent_harness, "2605.90000")
        assert r.status_code == 200
        body = r.json()
        assert body["graph_status"] == "absent"
        assert body["neighbors"] == []
        assert body["format_version"] == API_V1_FORMAT_VERSION

    def test_unavailable_graph_returns_200_empty(self, unavailable_harness):
        r = _get(unavailable_harness, "2605.90000")
        assert r.status_code == 200
        body = r.json()
        assert body["graph_status"] == "unavailable"
        assert body["neighbors"] == []

    def test_present_graph_returns_neighbors(
        self, present_harness, synthetic_graph,
    ):
        source = synthetic_graph["paper_ids"][5]
        r = _get(present_harness, source, depth=1)
        assert r.status_code == 200
        body = r.json()
        assert body["graph_status"] == "present"
        # P_5 cites P_4, P_3, P_2 at depth 1.
        got = [n["paper_id"] for n in body["neighbors"]]
        assert got == sorted(synthetic_graph["paper_ids"][2:5])
        # CitationNeighbor field vocabulary, verbatim.
        for n in body["neighbors"]:
            assert set(n) == {
                "chunk_id", "paper_id", "edge_kind",
                "hop_distance", "source", "confidence",
            }
            assert n["hop_distance"] == 1
            assert n["edge_kind"] == "cites"


# ---------------------------------------------------------------------------
# Envelope parity with the MCP handler (the AC-A.20 "mirrors" clause)
# ---------------------------------------------------------------------------


class TestMcpEnvelopeParity:
    def _call_mcp_handler(
        self, kuzu_path: Path, lancedb_path: Path, paper_id: str,
        direction: str, depth: int, limit: int,
    ) -> dict:
        from server.handlers.citations import handle_cite_neighbors
        from server.tools import set_resources

        class _FakeCorpusInfo:
            version = 1

        class _FakeResources:
            config = Config(
                kuzu_path=kuzu_path, lancedb_path=lancedb_path,
            )
            corpus_info = _FakeCorpusInfo()

        set_resources(_FakeResources())
        chunk_id = f"arxiv:{paper_id}:0000000000000000"
        return asyncio.run(handle_cite_neighbors(
            chunk_id=chunk_id, direction=direction,
            depth=depth, limit=limit,
        ))

    @pytest.mark.parametrize("direction", ["cites", "cited_by", "depends_on"])
    def test_neighbors_and_status_match_mcp(
        self, present_harness, synthetic_graph, tmp_path, direction,
    ):
        source = synthetic_graph["paper_ids"][0]
        rest = _get(
            present_harness, source, direction=direction, depth=2, limit=10,
        ).json()
        mcp = self._call_mcp_handler(
            synthetic_graph["kuzu_dir"], tmp_path / "lancedb-absent",
            source, direction, 2, 10,
        )
        assert rest["graph_status"] == mcp["graph_status"] == "present"
        assert rest["neighbors"] == mcp["neighbors"]
        # Shared scalar vocabulary (paper_id here ↔ chunk_id there is
        # the documented surface difference).
        assert rest["direction"] == mcp["direction"]
        assert rest["depth"] == mcp["depth"]
        assert rest["limit"] == mcp["limit"]

    def test_absent_status_matches_mcp(self, absent_harness, tmp_path):
        rest = _get(absent_harness, "2605.90000").json()
        mcp = self._call_mcp_handler(
            tmp_path / "kuzu-missing", tmp_path / "lancedb-absent",
            "2605.90000", "cites", 2, 30,
        )
        assert rest["graph_status"] == mcp["graph_status"] == "absent"
        assert rest["neighbors"] == mcp["neighbors"] == []


# ---------------------------------------------------------------------------
# Validation + scoping
# ---------------------------------------------------------------------------


class TestValidation:
    def test_unknown_notebook_404(self, present_harness):
        r = present_harness["client"].get(
            "/api/v1/notebooks/ghost/graph/neighbors",
            params={"paper_id": "2605.90000"},
        )
        assert r.status_code == 404

    def test_malformed_slug_422(self, present_harness):
        r = present_harness["client"].get(
            "/api/v1/notebooks/UPPER/graph/neighbors",
            params={"paper_id": "2605.90000"},
        )
        assert r.status_code == 422

    @pytest.mark.parametrize(
        "bad_id",
        ["not-an-id", "2605.90000'; DROP TABLE papers;--", "../../etc"],
    )
    def test_malformed_paper_id_422(self, present_harness, bad_id):
        r = _get(present_harness, bad_id)
        assert r.status_code == 422

    def test_missing_paper_id_422(self, present_harness):
        r = present_harness["client"].get(
            "/api/v1/notebooks/graph-nb/graph/neighbors"
        )
        assert r.status_code == 422

    @pytest.mark.parametrize(
        "params",
        [
            {"direction": "sideways"},
            {"depth": 0},
            {"depth": 3},
            {"limit": 0},
            {"limit": 101},
        ],
    )
    def test_out_of_bounds_params_422(self, present_harness, params):
        r = _get(present_harness, "2605.90000", **params)
        assert r.status_code == 422

    def test_limit_caps_neighbor_count(
        self, present_harness, synthetic_graph,
    ):
        source = synthetic_graph["paper_ids"][0]
        body = _get(present_harness, source, depth=2, limit=2).json()
        assert body["graph_status"] == "present"
        assert len(body["neighbors"]) == 2

    def test_out_of_graph_paper_is_present_and_empty(self, present_harness):
        # A valid paper id with no node in the graph: the query
        # succeeds (present) with zero neighbors — same as the MCP
        # library semantics.
        body = _get(present_harness, "2401.99999").json()
        assert body["graph_status"] == "present"
        assert body["neighbors"] == []
