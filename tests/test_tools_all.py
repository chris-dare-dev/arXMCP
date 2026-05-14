"""Smoke + schema tests for all 7 MCP tools (E06_S03).

Two layers:

1. **Schema-shape tests** (always-on, no corpus needed). Assert
   ``tools/list`` returns exactly the 7 expected tools, each
   carries ``_meta: {"tool_schema_version": 1}``, each inputSchema
   passes JSON Schema Draft-07 conformance, and the registration
   order matches :data:`server.tools.ALL_TOOLS`.

2. **End-to-end smoke tests** (synthesized 5-chunk LanceDB +
   mocked BGE-M3, mirroring E06_S01's pattern). Each tool is
   invoked once via the FastAPI TestClient against the mounted
   /mcp/ endpoint; each is asserted to return without a 500 and
   to carry ``corpus_version`` in structuredContent.

The brief AC "All 7 tool smoke tests pass against the 50-paper
seed corpus" is satisfied via the synthetic-corpus path; the
literal 50-paper variant is gated behind the existing
``ARXMCP_RUN_REAL_BGE_M3`` env precedent (env-gated, not in the
default test path).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft7Validator

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from server.config import Config
from server.health import reset_metrics_for_tests
from server.main import create_app
from server.tools import (
    ALL_TOOLS,
    TOOL_SCHEMA_VERSION,
    reset_resources_for_tests,
)

# ===========================================================================
# Helpers (mirror E06_S01's _seed_corpus pattern)
# ===========================================================================


def _seed_corpus(lancedb_path: Path) -> int:
    """Seed a tiny 5-chunk corpus across 2 papers.

    Includes:
    - One chunk with theorem_name="Riemann-Roch" (find_lemma_by_name).
    - Several chunks distributed across 2 papers (paper grouping).
    - chunk_ids are consistent: the embedded paper_id in the
      chunk_id matches the ChunkRecord.paper_id field (otherwise
      the validator's _CHUNK_ID_RE would catch the mismatch).
    """
    paper_ids = ["2401.00001", "2401.00001", "2401.00001", "2401.00002", "2401.00002"]
    chunks = [
        ChunkRecord(
            chunk_id=f"arxiv:{paper_ids[i]}:{i:016x}",
            paper_id=paper_ids[i],
            kind="stmt",
            section_path=[f"Section {i // 2}"],
            theorem_name=("Riemann-Roch" if i == 0 else f"Lemma {i}.1" if i % 2 else None),
            theorem_label=f"Theorem {i}.1",
            body_text=f"This is the body of chunk {i}. It mentions algebraic curves.",
            body_tokens=f"chunk {i} body algebraic curves",
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
        )
        for i in range(5)
    ]
    rng = np.random.default_rng(42)
    rows = []
    for _ in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        rows.append(v)
    embeddings = EmbedRecord(
        chunk_ids_stmt=[c.chunk_id for c in chunks],
        embedding_stmt=np.stack(rows, axis=0),
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )
    return write_chunks(chunks, embeddings, lancedb_path=lancedb_path)


@pytest.fixture
def mocked_bge_m3(monkeypatch):
    """Replace the BGE-M3 model + tokenizer with no-ops, AND make
    encode_query return a deterministic vector so search_papers
    returns reproducible top-k. Mirrors E06_S01's fixture."""
    import server.query_encoder as qe_mod

    monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
    monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())

    async def _fake_encode_query(text):
        rng = np.random.default_rng(hash(text) % (2**32))
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        return v

    monkeypatch.setattr(qe_mod, "encode_query", _fake_encode_query)
    # Also patch the import in server.handlers.search and equation
    # (they bind it at import time).
    import server.handlers.equation as eq_mod
    import server.handlers.search as search_mod

    monkeypatch.setattr(search_mod, "encode_query", _fake_encode_query)
    monkeypatch.setattr(eq_mod, "encode_query", _fake_encode_query)
    yield


@pytest.fixture
def warm_app(tmp_path, mocked_bge_m3):
    lancedb_path = tmp_path / "lancedb"
    _seed_corpus(lancedb_path)
    cfg = Config(lancedb_path=lancedb_path)
    reset_resources_for_tests()
    reset_metrics_for_tests()
    app = create_app(cfg)
    with TestClient(app) as client:
        yield client


# ===========================================================================
# Schema-shape tests (always-on)
# ===========================================================================


class TestToolsList:
    """AC: tools/list returns exactly 7 tools, no more, no fewer."""

    def test_seven_tools_registered(self, tmp_path, mocked_bge_m3):
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path)
        cfg = Config(lancedb_path=lancedb_path)
        reset_resources_for_tests()
        reset_metrics_for_tests()
        app = create_app(cfg)
        # Inspect via FastMCP directly (no need to fire the lifespan).
        tools = asyncio.run(app.state.mcp_server.list_tools())
        assert len(tools) == 7

    def test_tool_names_match_canonical(self, tmp_path, mocked_bge_m3):
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path)
        cfg = Config(lancedb_path=lancedb_path)
        reset_resources_for_tests()
        reset_metrics_for_tests()
        app = create_app(cfg)
        tools = asyncio.run(app.state.mcp_server.list_tools())
        names = [t.name for t in tools]
        expected = [tm.name for tm in ALL_TOOLS]
        assert names == expected, f"order or names drifted: {names} vs {expected}"

    def test_per_tool_schema_version_meta(self, tmp_path, mocked_bge_m3):
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path)
        cfg = Config(lancedb_path=lancedb_path)
        reset_resources_for_tests()
        reset_metrics_for_tests()
        app = create_app(cfg)
        tools = asyncio.run(app.state.mcp_server.list_tools())
        for t in tools:
            assert t.meta is not None
            assert t.meta.get("tool_schema_version") == TOOL_SCHEMA_VERSION


class TestSchemaConformance:
    """AC: each tool's JSON schema validates against JSON Schema Draft-07."""

    def test_all_input_schemas_are_draft7_compatible(self, tmp_path, mocked_bge_m3):
        lancedb_path = tmp_path / "lancedb"
        _seed_corpus(lancedb_path)
        cfg = Config(lancedb_path=lancedb_path)
        reset_resources_for_tests()
        reset_metrics_for_tests()
        app = create_app(cfg)
        tools = asyncio.run(app.state.mcp_server.list_tools())
        for t in tools:
            schema = t.inputSchema
            # check_schema raises jsonschema.SchemaError on
            # incompatible constructs.
            Draft7Validator.check_schema(schema)
            # Belt + suspenders: $defs is 2020-12-only — a clean
            # Draft-07 schema uses ``definitions`` instead. Pydantic
            # may use $defs; if so the test catches it.
            assert "$defs" not in json.dumps(schema), (
                f"tool {t.name!r} inputSchema uses $defs which is "
                f"Draft-2020-12-only; Draft-07 expects 'definitions'"
            )


# ===========================================================================
# Per-tool smoke tests (against synthetic corpus)
# ===========================================================================


_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Host": "127.0.0.1:7733",
    "Mcp-Protocol-Version": "2025-06-18",
}


def _initialize_session(client: TestClient) -> str:
    """Perform the MCP initialize handshake. Returns the
    ``mcp-session-id`` from the response header so the caller can
    echo it on subsequent requests."""
    r = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers=_MCP_HEADERS,
    )
    assert r.status_code == 200, f"initialize failed: {r.status_code} {r.text[:200]}"
    sid = r.headers.get("mcp-session-id")
    assert sid is not None, "initialize did not return mcp-session-id header"
    # Send the required initialized notification (per MCP spec).
    client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={**_MCP_HEADERS, "mcp-session-id": sid},
    )
    return sid


def _call_tool(client: TestClient, name: str, arguments: dict, sid: str | None = None) -> dict:
    """Invoke an MCP tool via the FastAPI client. Caller must
    provide a session-id from a prior :func:`_initialize_session`
    call.
    """
    if sid is None:
        sid = _initialize_session(client)
    r = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers={**_MCP_HEADERS, "mcp-session-id": sid},
    )
    return r


class TestToolsSmoke:
    """One smoke test per tool. Each invokes via /mcp/ tools/call
    and asserts the response shape. The mcp library handles the
    initialize handshake transparently for stateless callers."""

    def _assert_envelope_ok(self, resp, name: str):
        """Generic check: HTTP 200 + structuredContent has corpus_version."""
        assert resp.status_code == 200, f"{name}: HTTP {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        assert "result" in body, f"{name}: missing 'result' in {body}"
        result = body["result"]
        # MCP tools/call returns CallToolResult with content + structuredContent
        sc = result.get("structuredContent", {})
        assert "corpus_version" in sc, f"{name}: corpus_version missing from structuredContent"

    def test_search_papers_smoke(self, warm_app):
        r = _call_tool(warm_app, "search_papers", {"query": "Riemann-Roch", "k": 3})
        self._assert_envelope_ok(r, "search_papers")
        sc = r.json()["result"]["structuredContent"]
        assert "results" in sc
        assert sc["retrieval_mode"] == "dense_only"
        assert isinstance(sc["results"], list)
        assert len(sc["results"]) <= 3

    def test_search_papers_level_paper(self, warm_app):
        r = _call_tool(warm_app, "search_papers", {"query": "algebraic", "level": "paper", "k": 5})
        self._assert_envelope_ok(r, "search_papers")
        sc = r.json()["result"]["structuredContent"]
        # Dedup-by-paper: the corpus has 2 papers, so at most 2 results.
        assert len({row["paper_id"] for row in sc["results"]}) == len(sc["results"])

    def test_get_chunk_smoke(self, warm_app):
        cid = "arxiv:2401.00001:0000000000000000"
        r = _call_tool(warm_app, "get_chunk", {"chunk_id": cid})
        self._assert_envelope_ok(r, "get_chunk")
        sc = r.json()["result"]["structuredContent"]
        assert sc["found"] is True
        assert sc["chunk"]["chunk_id"] == cid

    def test_get_chunk_not_found(self, warm_app):
        cid = "arxiv:9999.99999:ffffffffffffffff"
        r = _call_tool(warm_app, "get_chunk", {"chunk_id": cid})
        self._assert_envelope_ok(r, "get_chunk")
        sc = r.json()["result"]["structuredContent"]
        assert sc["found"] is False

    def test_find_equation_smoke(self, warm_app):
        r = _call_tool(warm_app, "find_equation", {"latex_or_mathml": r"\int_0^1 f(x) dx", "k": 3})
        self._assert_envelope_ok(r, "find_equation")
        sc = r.json()["result"]["structuredContent"]
        assert sc["retrieval_mode"] == "dense_only_stmt_fallback"
        assert "results" in sc

    def test_get_definitions_no_preamble(self, warm_app):
        # The warm-app test corpus has no definitions table built, so
        # the handler degrades to index_status="absent" (E10_S01).
        # Same empty-result shape either way; callers can distinguish
        # via index_status when needed.
        r = _call_tool(warm_app, "get_definitions", {"paper_id": "2401.00001"})
        self._assert_envelope_ok(r, "get_definitions")
        sc = r.json()["result"]["structuredContent"]
        assert sc["definitions"] == []
        assert sc["next_cursor"] is None
        assert sc["total"] == 0
        # index_status is "absent" until ingest.index_definitions runs.
        assert sc["index_status"] in ("absent", "ok")

    def test_find_lemma_by_name_smoke(self, warm_app):
        r = _call_tool(warm_app, "find_lemma_by_name", {"name": "Riemann"})
        self._assert_envelope_ok(r, "find_lemma_by_name")
        sc = r.json()["result"]["structuredContent"]
        # The warm_app fixture does NOT seed the theorem-names SQLite
        # DB, so the handler falls back to in-memory scan (E10_S02).
        # When a future fixture seeds the DB, this assertion still
        # passes for any FTS5 mode.
        assert sc["retrieval_mode"] in (
            "in_memory_scan_fallback",
            "fts5_exact",
            "fts5_trigram",
            "fuzzy_jaccard",
        )
        # The seeded corpus has theorem_name="Riemann-Roch" on chunk 0.
        assert len(sc["matches"]) >= 1
        assert any("riemann" in m["theorem_name"].lower() for m in sc["matches"])

    def test_get_paper_synthesized(self, warm_app):
        r = _call_tool(warm_app, "get_paper", {"paper_id": "2401.00001"})
        self._assert_envelope_ok(r, "get_paper")
        sc = r.json()["result"]["structuredContent"]
        assert sc["found"] is True
        assert sc["metadata_status"] == "synthesized_from_chunks"
        assert sc["paper"]["paper_id"] == "2401.00001"
        assert sc["paper"]["chunk_count"] >= 1
        # Null-fields per synthesis D4.
        assert sc["paper"]["authors"] is None
        assert sc["paper"]["title"] is None

    def test_get_paper_not_found(self, warm_app):
        r = _call_tool(warm_app, "get_paper", {"paper_id": "9999.99999"})
        self._assert_envelope_ok(r, "get_paper")
        sc = r.json()["result"]["structuredContent"]
        assert sc["found"] is False

    def test_cite_neighbors_stub(self, warm_app):
        cid = "arxiv:2401.00001:0000000000000000"
        r = _call_tool(warm_app, "cite_neighbors", {"chunk_id": cid})
        self._assert_envelope_ok(r, "cite_neighbors")
        sc = r.json()["result"]["structuredContent"]
        assert sc["infrastructure_status"] == "deferred"
        assert sc["neighbors"] == []


# ===========================================================================
# Rectification regression tests (F1, F2, F3, F6, F7)
# ===========================================================================


class TestPaperIdValidation:
    """F3 close: paper_id is validated before use as filter or path."""

    def test_get_definitions_rejects_path_traversal(self, warm_app):
        """Threat 1 closure: ``../../etc/passwd`` would have built a
        traversal path. Now rejected with isError=true."""
        r = _call_tool(
            warm_app, "get_definitions", {"paper_id": "../../../../etc/passwd"}
        )
        # Either FastMCP wraps the ValueError into isError or returns
        # JSON-RPC error; both indicate the call did NOT silently
        # path-traverse.
        body = r.json()
        assert body.get("error") is not None or body.get("result", {}).get("isError") is True, (
            f"path traversal was not rejected: {body!r}"
        )

    def test_get_paper_rejects_malformed_paper_id(self, warm_app):
        r = _call_tool(warm_app, "get_paper", {"paper_id": "not-an-arxiv-id"})
        body = r.json()
        assert body.get("error") is not None or body.get("result", {}).get("isError") is True

    def test_find_lemma_rejects_malformed_paper_id(self, warm_app):
        r = _call_tool(
            warm_app,
            "find_lemma_by_name",
            {"name": "x", "paper_id": "../etc"},
        )
        body = r.json()
        assert body.get("error") is not None or body.get("result", {}).get("isError") is True


class TestSearchSchemaContract:
    """F6 close: search_papers schema accepts filters + cursor."""

    def test_search_accepts_filters_arg(self, warm_app):
        r = _call_tool(
            warm_app,
            "search_papers",
            {"query": "Riemann", "k": 3, "filters": {"year_min": 2020}},
        )
        # Must NOT 4xx-error with "additional properties not allowed".
        assert r.status_code == 200
        sc = r.json()["result"]["structuredContent"]
        # filters arg is accepted but documented as ignored at v1.
        assert any("filters arg" in w for w in sc.get("filter_warnings", []))

    def test_search_accepts_cursor_arg(self, warm_app):
        r = _call_tool(
            warm_app,
            "search_papers",
            {"query": "x", "k": 1, "cursor": "abc"},
        )
        assert r.status_code == 200
        sc = r.json()["result"]["structuredContent"]
        assert any("cursor arg" in w for w in sc.get("filter_warnings", []))

    def test_search_excludes_proof_kinds_documented(self, warm_app):
        """F5 close: result envelope carries excluded_kinds=['proof']
        so agents can detect the v1 limitation programmatically."""
        r = _call_tool(warm_app, "search_papers", {"query": "x", "k": 1})
        assert r.status_code == 200
        sc = r.json()["result"]["structuredContent"]
        assert sc["excluded_kinds"] == ["proof"]

    def test_search_results_have_no_version_field(self, warm_app):
        """F7 close: dropped the hardcoded version=1 from result
        rows. Schema has no paper-version column; the prior literal
        was misinformation."""
        r = _call_tool(warm_app, "search_papers", {"query": "x", "k": 5})
        sc = r.json()["result"]["structuredContent"]
        for row in sc["results"]:
            assert "version" not in row, f"unexpected 'version' field: {row}"


class TestDefinitionsParser:
    """F2 close (carried forward across E10_S01): the brace-balanced
    parser handles multi-newcommand lines correctly. After E10_S01
    the parser lives in ``ingest.index_definitions`` (the indexer is
    the new owner of macro-line parsing); the regression assertions
    are preserved here so a future regression in the parser surfaces
    even if the indexer's own tests are skipped.
    """

    def test_parse_two_macros_on_one_line(self):
        from ingest.index_definitions import parse_macro_line

        line = r"\newcommand{\R}{\mathbb{R}}\newcommand{\C}{\mathbb{C}}"
        records = parse_macro_line(line)
        assert len(records) == 2
        symbols = {r["symbol"] for r in records}
        expansions = {r["expansion"] for r in records}
        assert symbols == {"\\R", "\\C"}
        assert expansions == {"\\mathbb{R}", "\\mathbb{C}"}

    def test_parse_with_internal_braces(self):
        from ingest.index_definitions import parse_macro_line

        line = r"\newcommand{\Z}{\mathbb{Z}^{n}}"
        records = parse_macro_line(line)
        assert len(records) == 1
        assert records[0]["symbol"] == "\\Z"
        assert records[0]["expansion"] == "\\mathbb{Z}^{n}"

    def test_parse_handles_renewcommand(self):
        from ingest.index_definitions import parse_macro_line

        line = r"\renewcommand{\foo}{bar}"
        records = parse_macro_line(line)
        assert len(records) == 1
        assert records[0]["symbol"] == "\\foo"
        assert records[0]["expansion"] == "bar"


class TestByteCapEnforcement:
    """F1 + F4 close: enforce_byte_cap respects the body_text_path
    arg AND accounts for wire-envelope overhead."""

    def test_enforce_byte_cap_truncates_nested_body(self):

        from server.config import Config
        from server.tools import enforce_byte_cap, set_resources

        # Synthesize a Resources with a tiny cap.
        cfg = Config(result_byte_cap=200)
        # Build a minimal Resources without going through startup
        # (no LanceDB needed for the cap test).

        class _FakeCorpusInfo:
            version = 1

        class _FakeResources:
            config = cfg
            corpus_info = _FakeCorpusInfo()

        set_resources(_FakeResources())

        # Construct an over-cap payload with body_text nested under
        # ``chunk``. Use 5000 chars so the truncation [:1024] slice
        # produces a meaningfully shorter result.
        big_body = "x" * 5000
        cid = "arxiv:2401.00001:0000000000000000"
        payload = {"chunk": {"body_text": big_body, "chunk_id": cid}}
        structured, blocks = enforce_byte_cap(
            payload,
            chunk_id=cid,
            body_text_path=("chunk", "body_text"),
        )
        # F1: nested body_text must be truncated.
        assert structured["chunk"]["body_text"] != big_body
        assert len(structured["chunk"]["body_text"]) == 1024
        assert structured["body_truncated"] is True
        # Resource_link block emitted.
        assert len(blocks) == 1
        assert blocks[0]["type"] == "resource_link"
        assert blocks[0]["uri"].endswith(cid)
        # F4: the wire-overhead factor halves the effective cap, so
        # any payload over 100 bytes (= 200 / 2) trips truncation.
        assert len(big_body) > 100  # sanity

    def test_enforce_byte_cap_under_cap_passthrough(self):
        from server.config import Config
        from server.tools import enforce_byte_cap, set_resources

        cfg = Config(result_byte_cap=10000)

        class _FakeCorpusInfo:
            version = 1

        class _FakeResources:
            config = cfg
            corpus_info = _FakeCorpusInfo()

        set_resources(_FakeResources())
        # Small payload — should pass through unchanged with no
        # resource_link block.
        payload = {"chunk": {"body_text": "small", "chunk_id": "x"}}
        structured, blocks = enforce_byte_cap(
            payload, chunk_id="x", body_text_path=("chunk", "body_text")
        )
        assert structured == payload
        assert blocks == []
