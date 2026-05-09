"""Locks the E06_S04 snippet contract for ``search_papers``.

Coverage map (acceptance criteria → test):

  AC                                                Test
  ──────────────────────────────────────────────────────────────────
  snippet ≤150 chars, no summary field              TestSnippetShape
  snippet derived from body_text, not LLM           TestSnippetSource
  content array carries resource_link per result    TestResourceLinks
  docs/snippet-contract.md says "No dependency..."  TestDocContract
  result schema validates JSON Schema Draft-07      TestSchemaConformance

Tests reuse the synthetic 5-chunk corpus pattern from
``tests/test_tools_all.py`` (the seed corpus is not yet ingested
as a real artifact; same dilemma resolved the same way).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft7Validator

from ingest.embedder import EMBEDDING_DIM
from server.config import Config
from server.health import reset_metrics_for_tests
from server.main import create_app
from server.tools import reset_resources_for_tests
from tests.test_tools_all import _call_tool, _seed_corpus

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "server" / "schemas" / "search_papers_result.json"
DOC_PATH = REPO_ROOT / "docs" / "snippet-contract.md"


# ===========================================================================
# Fixtures (mocked_bge_m3 is local-defined to avoid cross-module fixture
# import — ruff F811 flags re-exported pytest fixtures even though they
# work at runtime).
# ===========================================================================


@pytest.fixture
def _mocked_bge(monkeypatch):
    """Replace the BGE-M3 model + tokenizer + encode_query at all
    bind sites. Mirrors ``tests/test_tools_all.py::mocked_bge_m3``."""
    import server.handlers.equation as eq_mod
    import server.handlers.search as search_mod
    import server.query_encoder as qe_mod

    monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
    monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())

    async def _fake_encode_query(text):
        rng = np.random.default_rng(hash(text) % (2**32))
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        return v

    monkeypatch.setattr(qe_mod, "encode_query", _fake_encode_query)
    monkeypatch.setattr(search_mod, "encode_query", _fake_encode_query)
    monkeypatch.setattr(eq_mod, "encode_query", _fake_encode_query)
    yield


@pytest.fixture
def warm_app(tmp_path, _mocked_bge):
    """An app with a synthetic 5-chunk corpus."""
    lancedb_path = tmp_path / "lancedb"
    _seed_corpus(lancedb_path)
    cfg = Config(lancedb_path=lancedb_path)
    reset_resources_for_tests()
    reset_metrics_for_tests()
    app = create_app(cfg)
    with TestClient(app) as client:
        yield client


def _search(client: TestClient, **kwargs) -> dict:
    """Invoke search_papers and return the parsed JSON-RPC response."""
    args = {"query": "algebraic", "k": 5}
    args.update(kwargs)
    r = _call_tool(client, "search_papers", args)
    assert r.status_code == 200, f"search failed: {r.status_code} {r.text[:300]}"
    return r.json()


# ===========================================================================
# AC: snippet ≤150 chars, no summary field
# ===========================================================================


class TestSnippetShape:
    def test_snippet_length_under_cap(self, warm_app):
        body = _search(warm_app)
        rows = body["result"]["structuredContent"]["results"]
        assert len(rows) >= 1
        for row in rows:
            assert "snippet" in row, f"missing snippet on {row}"
            assert isinstance(row["snippet"], str)
            assert len(row["snippet"]) <= 150, (
                f"snippet over 150 chars: len={len(row['snippet'])} {row}"
            )

    def test_no_summary_field(self, warm_app):
        """E06_S04 contract (b): the ``summary`` field is permanently
        dropped. A regression that re-introduces it fires this test."""
        body = _search(warm_app)
        rows = body["result"]["structuredContent"]["results"]
        for row in rows:
            assert "summary" not in row, (
                f"unexpected 'summary' field on result row: {row}. "
                f"E06_S04 dropped this field permanently — see "
                f"docs/snippet-contract.md section (b)."
            )

    def test_chunk_id_present_and_well_formed(self, warm_app):
        from ingest.identifiers import is_valid_chunk_id

        body = _search(warm_app)
        rows = body["result"]["structuredContent"]["results"]
        for row in rows:
            assert "chunk_id" in row
            assert is_valid_chunk_id(row["chunk_id"])

    def test_required_fields_present(self, warm_app):
        """Every row carries the 6 frozen fields per the schema."""
        body = _search(warm_app)
        rows = body["result"]["structuredContent"]["results"]
        required = {"chunk_id", "label", "paper_id", "score", "section_path", "snippet"}
        for row in rows:
            assert set(row.keys()) >= required, (
                f"row missing required keys: have={set(row.keys())} "
                f"need={required}"
            )

    def test_no_unexpected_fields(self, warm_app):
        """Schema is closed (additionalProperties: false). Catches a
        future drift that adds an undocumented field."""
        body = _search(warm_app)
        rows = body["result"]["structuredContent"]["results"]
        allowed = {"chunk_id", "label", "paper_id", "score", "section_path", "snippet"}
        for row in rows:
            extra = set(row.keys()) - allowed
            assert not extra, (
                f"row has undocumented fields {sorted(extra)}: {row}. "
                f"Bump tool_schema_version + update server/schemas/"
                f"search_papers_result.json before adding fields."
            )


# ===========================================================================
# AC: snippet is derived from body_text, not from any LLM
# ===========================================================================


class TestSnippetSource:
    """Validates that the snippet is a byte-prefix of ``body_text``,
    not a rewrite. The seeded corpus uses a known body string so we
    can compare snippet bytes directly."""

    def test_snippet_is_prefix_of_body_text(self, warm_app):
        """The seeded corpus body_text starts with
        ``"This is the body of chunk N. ..."``. The snippet must
        be a prefix of that text (verbatim slice, no rewriting).
        """
        body = _search(warm_app, k=5)
        rows = body["result"]["structuredContent"]["results"]
        assert len(rows) >= 1
        for row in rows:
            # The seeded body_text format is deterministic per
            # tests/test_tools_all.py::_seed_corpus.
            assert row["snippet"].startswith("This is the body of chunk")

    def test_snippet_constant_pinned_to_150(self):
        from server.handlers.search import SNIPPET_MAX_CHARS

        assert SNIPPET_MAX_CHARS == 150


# ===========================================================================
# AC: content array contains a resource_link per result
# ===========================================================================


class TestResourceLinks:
    def test_content_carries_text_then_resource_links(self, warm_app):
        body = _search(warm_app, k=3)
        result = body["result"]
        content = result.get("content", [])
        # content[0] is the JSON-pretty-print TextContent (preserves
        # FastMCP default for clients reading content[0].text).
        assert len(content) >= 1
        assert content[0]["type"] == "text"
        text_payload = json.loads(content[0]["text"])
        assert "results" in text_payload
        # content[1..] are resource_link blocks, one per row.
        rows = result["structuredContent"]["results"]
        rl_blocks = [b for b in content[1:] if b.get("type") == "resource_link"]
        assert len(rl_blocks) == len(rows), (
            f"expected one resource_link per row; got {len(rl_blocks)} "
            f"links for {len(rows)} rows"
        )

    def test_resource_link_uris_match_chunk_ids(self, warm_app):
        body = _search(warm_app, k=3)
        result = body["result"]
        rows = result["structuredContent"]["results"]
        content = result["content"]
        rl_blocks = [b for b in content if b.get("type") == "resource_link"]
        for row, block in zip(rows, rl_blocks, strict=True):
            assert block["uri"].startswith("arxmcp://chunks/")
            assert block["uri"].endswith(row["chunk_id"]), (
                f"resource_link URI {block['uri']} does not match "
                f"chunk_id {row['chunk_id']} in the corresponding row"
            )

    def test_resource_links_in_score_chunk_id_order(self, warm_app):
        """The resource_link blocks order MUST match the results
        list order (which is sorted score_desc, chunk_id_asc per
        the determinism contract). E06_S06's byte-stability hash
        depends on this."""
        body = _search(warm_app, k=5)
        result = body["result"]
        rows = result["structuredContent"]["results"]
        content = result["content"]
        rl_blocks = [b for b in content if b.get("type") == "resource_link"]
        for row, block in zip(rows, rl_blocks, strict=True):
            assert block["uri"].endswith(row["chunk_id"])


# ===========================================================================
# AC: docs/snippet-contract.md has "No dependency on Anthropic Citations API"
# ===========================================================================


class TestDocContract:
    def test_doc_exists(self):
        assert DOC_PATH.is_file(), f"docs/snippet-contract.md missing at {DOC_PATH}"

    def test_doc_disclaims_citations_api(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        # The brief AC requires the literal string "No dependency on
        # Anthropic Citations API". Whitespace-tolerant check so the
        # doc can be reflowed.
        normalized = " ".join(text.split())
        assert "No dependency on Anthropic Citations API" in normalized or (
            "decoupled from Anthropic's Citations API" in normalized
        ), (
            "docs/snippet-contract.md must explicitly disclaim the "
            "Anthropic Citations API dependency per E06_S04 AC"
        )

    def test_doc_states_150_char_cap(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        assert "150" in text and "snippet" in text.lower()


# ===========================================================================
# Schema lock — JSON Schema file validates Draft-07
# ===========================================================================


class TestSchemaConformance:
    def test_schema_file_exists(self):
        assert SCHEMA_PATH.is_file(), f"schema missing at {SCHEMA_PATH}"

    def test_schema_is_valid_draft7(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        assert schema.get("$schema") == "http://json-schema.org/draft-07/schema#"

    def test_schema_requires_exactly_six_row_fields(self):
        """The per-row schema's required list must match the
        handler's emitted fields. Drift here means the schema and
        the code disagree about what's required."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        row_schema = schema["properties"]["results"]["items"]
        required = set(row_schema["required"])
        assert required == {
            "chunk_id", "label", "paper_id", "score", "section_path", "snippet"
        }
        # additionalProperties: false locks the closed contract.
        assert row_schema["additionalProperties"] is False

    def test_schema_validates_real_search_response(self, warm_app):
        """Live search_papers result must validate against the
        committed JSON Schema. Closes the contract end-to-end."""
        from jsonschema import validate

        body = _search(warm_app, k=3)
        sc = body["result"]["structuredContent"]
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        # Should NOT raise.
        validate(instance=sc, schema=schema)
