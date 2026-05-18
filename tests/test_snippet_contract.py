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
# Moved 2026-05-10 from ``docs/`` to ``.claude/docs/`` per the repo-wide
# doc-layout consolidation.
DOC_PATH = REPO_ROOT / ".claude" / "docs" / "snippet-contract.md"


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
        ``"This is the body of chunk N. ..."``. After E13_S02, the
        snippet is wrapped in ``<retrieved_chunk>`` delimiters as a
        prompt-injection defense (Threat 2). The wrapped content
        must still be a verbatim prefix of body_text (no rewriting);
        only the surrounding delimiter changes.
        """
        body = _search(warm_app, k=5)
        rows = body["result"]["structuredContent"]["results"]
        assert len(rows) >= 1
        for row in rows:
            # E13_S02 — snippet is now wrapped in <retrieved_chunk>.
            # The content inside the delimiter is the verbatim
            # 150-char prefix of body_text (no LLM rewriting).
            assert row["snippet"].startswith(
                "<retrieved_chunk>This is the body of chunk"
            )
            assert row["snippet"].endswith("</retrieved_chunk>")

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
        """F3 close: the brief AC requires the LITERAL string 'No
        dependency on Anthropic Citations API'. The earlier
        paraphrase-tolerant check would have passed even if the
        literal sentence was edited away. The doc currently uses
        the literal phrase as the section heading; this test
        enforces it stays that way."""
        text = DOC_PATH.read_text(encoding="utf-8")
        # Whitespace-collapsed substring match so the sentence can
        # wrap across source lines, but no paraphrase tolerance.
        normalized = " ".join(text.split())
        required = "No dependency on Anthropic Citations API"
        assert required in normalized, (
            f"docs/snippet-contract.md must contain the literal AC "
            f"sentence {required!r} (whitespace-tolerant). "
            f"Paraphrases do not satisfy E06_S04 AC #5."
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


# ===========================================================================
# Rectification regression tests (F1, F2, F4, F7, F8)
# ===========================================================================


class TestRegexSourceOfTruth:
    """F1 close: the schema's chunk_id pattern must equal
    ``ingest.identifiers.CHUNK_ID_PATTERN`` byte-for-byte. E06_S03
    F11 collapsed the regex to a single source of truth; this test
    ensures the JSON Schema file does not silently re-introduce the
    drift surface.
    """

    def test_schema_chunk_id_pattern_matches_canonical(self):
        from ingest.identifiers import CHUNK_ID_PATTERN

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        pat = schema["properties"]["results"]["items"]["properties"]["chunk_id"]["pattern"]
        assert pat == f"^{CHUNK_ID_PATTERN}$", (
            f"schema chunk_id pattern drifted from "
            f"ingest.identifiers.CHUNK_ID_PATTERN; see E06_S03 F11. "
            f"schema={pat!r}, expected=^{CHUNK_ID_PATTERN}$"
        )


class TestNoLLMInSnippetPath:
    """F2 close: prove no LLM is called for the snippet by asserting
    no anthropic / openai client module is loaded as a side effect
    of importing the search handler. AC #2's "snippet derived from
    body_canonical text, not from any LLM call" is the goal; this
    is the strongest cheap proof we can offer (a future regression
    that calls Haiku would import anthropic at handler load)."""

    def test_no_llm_client_in_search_module(self):
        import importlib
        import sys

        for mod in ("anthropic", "openai", "cohere"):
            sys.modules.pop(mod, None)
        importlib.import_module("server.handlers.search")
        for mod in ("anthropic", "openai", "cohere"):
            assert mod not in sys.modules, (
                f"server.handlers.search imported {mod!r} — AC #2 "
                f"forbids LLM calls in the snippet path"
            )


class TestEdgeCaseShapes:
    """F4 close: zero-result + cap-edge cases were untested; the
    schema's bounds (snippet ≤150, additionalProperties: false,
    score in [0,1]) only fired against the 5-chunk happy path.
    """

    def test_snippet_function_at_cap(self):
        """``_snippet`` returns exactly the first 150 chars of the
        sanitized body_text wrapped in ``<retrieved_chunk>``
        delimiters (E13_S02 Threat 2 defense). The 150-char
        contract applies to the *content* inside the delimiter; the
        delimiter overhead is independent.
        """
        from server.handlers.search import SNIPPET_MAX_CHARS, _snippet

        # length == cap → content unchanged, wrapped in delimiters
        body_at = "a" * SNIPPET_MAX_CHARS
        snippet_at = _snippet(body_at)
        assert snippet_at == f"<retrieved_chunk>{body_at}</retrieved_chunk>"
        # The 150-char content contract is preserved inside the wrap.
        inner = snippet_at.removeprefix("<retrieved_chunk>").removesuffix(
            "</retrieved_chunk>"
        )
        assert len(inner) == SNIPPET_MAX_CHARS

        # length == cap + 1 → content truncated to exactly 150
        body_over = "a" * (SNIPPET_MAX_CHARS + 1)
        snippet_over = _snippet(body_over)
        inner_over = snippet_over.removeprefix("<retrieved_chunk>").removesuffix(
            "</retrieved_chunk>"
        )
        assert len(inner_over) == SNIPPET_MAX_CHARS
        assert inner_over == body_over[:SNIPPET_MAX_CHARS]

    def test_snippet_function_handles_none_and_empty(self):
        from server.handlers.search import _snippet

        assert _snippet(None) == ""
        assert _snippet("") == ""

    def test_distance_to_score_clamped_to_unit_interval(self):
        """``_distance_to_score`` should not emit values outside
        [0, 1]. The function clamps the lower bound but the upper
        bound depends on the L2 distance being non-negative
        (BGE-M3 unit vectors guarantee this; defensive check only).
        """
        from server.handlers.search import _distance_to_score

        # Identical vectors: dist=0 → score=1.0
        assert _distance_to_score(0.0) == 1.0
        # Orthogonal: dist=sqrt(2) ≈ 1.414 → score ≈ 0.293
        assert 0.0 <= _distance_to_score(1.414) <= 1.0
        # Antipodal: dist=2 → score=0.0
        assert _distance_to_score(2.0) == 0.0
        # Defensive: clamp below 0
        assert _distance_to_score(3.0) == 0.0
        # None → 0.0 (defensive)
        assert _distance_to_score(None) == 0.0

    def test_format_label_handles_all_none(self):
        """Empty string when both theorem_name and theorem_label
        are None — schema declares label as required."""
        from server.handlers.search import _format_label

        assert _format_label(None, None) == ""
        assert _format_label("Riemann-Roch", None) == "Riemann-Roch"
        assert _format_label(None, "3.4") == "3.4"
        assert _format_label("Lemma", "3.4") == "Lemma 3.4"


class TestSnippetCapConsistency:
    """F8 close: cross-file consistency between the SNIPPET_MAX_CHARS
    constant, the schema's maxLength, and the doc's mention of
    ``150``. A regression in ONE file is caught here."""

    def test_cap_constant_matches_schema_max_length(self):
        from server.handlers.search import SNIPPET_MAX_CHARS

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        snippet_schema = schema["properties"]["results"]["items"]["properties"]["snippet"]
        cap_in_schema = snippet_schema["maxLength"]
        assert cap_in_schema == SNIPPET_MAX_CHARS, (
            f"snippet cap drifted: handler={SNIPPET_MAX_CHARS}, "
            f"schema maxLength={cap_in_schema}"
        )

    def test_doc_mentions_the_exact_cap(self):
        """``test_doc_states_150_char_cap`` checks ``"150" in text``;
        this tightens to ``"150 character"`` so a future "150 ms" /
        "150 papers" drift is caught."""
        text = DOC_PATH.read_text(encoding="utf-8").lower()
        accepted = ("150 character", "150-character", "150-char", "150 char")
        assert any(s in text for s in accepted), (
            "docs/snippet-contract.md must mention the 150-character "
            "cap explicitly (a bare '150' could refer to anything)"
        )


class TestSchemaVersionPin:
    """F7 close: schema's ``version`` field must equal
    ``server.tools.TOOL_SCHEMA_VERSION``. A bump in one without
    the other is a contract drift."""

    def test_schema_version_matches_tool_schema_version(self):
        from server.tools import TOOL_SCHEMA_VERSION

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert "version" in schema, (
            "schema must carry a top-level ``version`` field equal "
            "to server.tools.TOOL_SCHEMA_VERSION"
        )
        assert schema["version"] == TOOL_SCHEMA_VERSION, (
            f"schema version {schema['version']} != "
            f"server.tools.TOOL_SCHEMA_VERSION {TOOL_SCHEMA_VERSION}"
        )

    def test_schema_has_id_for_canonical_url(self):
        """E06_S06 hash-pinning anchors on the schema's identity;
        ``$id`` provides a canonical URL even when the file is
        copied or renamed."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert "$id" in schema
        assert schema["$id"].startswith("https://arxmcp/schemas/")
