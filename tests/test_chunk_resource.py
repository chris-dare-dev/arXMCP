"""``arxmcp://chunks/{chunk_id}``: the resource the tool handlers link to."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import lancedb
import pyarrow as pa
import pytest
from mcp.server.fastmcp import FastMCP

from arxmcp.ingest.schema import CHUNKS_SCHEMA_V1
from arxmcp.server.handlers.chunk import handle_get_chunk
from arxmcp.server.mcp_resources import CHUNK_TEMPLATE_URI, register_resources
from arxmcp.server.tools import reset_resources_for_tests, set_resources

CHUNK_ID = "arxiv:2401.00001:0123456789abcdef"
LONG_BODY = "Let X be a smooth projective variety. " * 500  # ~19 KB


@pytest.fixture
def mcp(tmp_path):
    row = {field.name: None for field in CHUNKS_SCHEMA_V1}
    row.update(
        chunk_id=CHUNK_ID, paper_id="2401.00001", kind="theorem",
        section_path=["1"], body_text=LONG_BODY, body_tokens="x",
        chunker_version="v", embedder_version="v", license="",
    )
    table = lancedb.connect(str(tmp_path / "lancedb")).create_table(
        "chunks", data=pa.Table.from_pylist([row], schema=CHUNKS_SCHEMA_V1)
    )
    set_resources(SimpleNamespace(
        chunks_table=table,
        corpus_info=SimpleNamespace(version=7),
        # Small enough that get_chunk must truncate this body.
        config=SimpleNamespace(result_byte_cap=8 * 1024),
    ))
    server = FastMCP("arxmcp", json_response=True)
    register_resources(server)
    yield server
    reset_resources_for_tests()


def _read(server: FastMCP, uri: str) -> dict:
    (content,) = asyncio.run(server.read_resource(uri))
    return json.loads(content.content)


def test_the_template_is_registered(mcp):
    templates = asyncio.run(mcp.list_resource_templates())
    assert CHUNK_TEMPLATE_URI in {t.uriTemplate for t in templates}


def test_get_chunks_over_cap_link_resolves_to_the_whole_body(mcp):
    """get_chunk truncates the body and points at this resource; reading
    the link must give back what was cut."""
    capped = asyncio.run(handle_get_chunk(CHUNK_ID))
    assert capped["body_truncated"] is True
    assert len(capped["chunk"]["body_text"]) < len(LONG_BODY)

    full = _read(mcp, capped["resource_link_uri"])

    assert full["found"] is True
    assert full.get("body_truncated") is not True
    assert LONG_BODY.strip() in full["chunk"]["body_text"]


def test_an_id_not_in_the_corpus_is_found_false(mcp):
    missing = _read(mcp, "arxmcp://chunks/arxiv:2401.00002:0123456789abcdef")

    assert missing["found"] is False


def test_a_malformed_id_is_an_error(mcp):
    with pytest.raises(Exception, match="does not match"):
        asyncio.run(mcp.read_resource("arxmcp://chunks/not-a-chunk-id"))
