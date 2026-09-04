"""`lean_verify` advertises its frozen result schema, and is no longer corpus-gated.

derived-alg-geo-lean **#185**. Two halves, and the second is not optional once
the first lands.

`server/schemas/lean_verify_result.json` existed and was **test-only**:
`TestLeanVerifyResultSchema` validated the handler's envelopes against it while
the wire advertised FastMCP's auto-derived
`{"type": "object", "additionalProperties": true,
  "title": "handle_lean_verifyDictOutput"}`.

So clients got no machine-readable output contract for the one tool whose
output is most consequential to misread, and the file that *was* the contract
was invisible to them.

The second half follows from the SDK, not from taste.
`FuncMetadata.convert_result` validates the `structuredContent` of every
`CallToolResult` against `output_model` whenever `output_schema` is set. The
bootstrap short-circuit returns a `CallToolResult` carrying
`{corpus_version, error_code, tool}` — one of thirteen required fields, plus
two the schema forbids. Advertising the schema turns that from "returned and
wrong" into "raises", so `lean_verify` had to stop being gated on corpus state
it does not read.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
from mcp.server.fastmcp import FastMCP

from server.tools import (
    _CORPUS_INDEPENDENT_TOOLS,
    ALL_TOOLS,
    BOOTSTRAP_CORPUS_VERSION_SENTINEL,
    LEAN_VERIFY,
    TOOL_SCHEMA_VERSION,
    _build_bootstrap_envelope,
    envelope,
    lean_verify_result_schema,
    register_all,
    reset_resources_for_tests,
    set_resources,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "server" / "schemas" / "lean_verify_result.json"
)


def _live_tools() -> dict[str, object]:
    mcp = FastMCP("arxmcp", json_response=True)
    register_all(mcp)
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


# --- the advertised contract ---------------------------------------------------

def test_the_advertised_schema_is_the_frozen_file_verbatim() -> None:
    """Not a Pydantic mirror of it. The file is what the handler is tested
    against, so a mirror would be a SECOND contract free to drift from the
    first — and the drift would be invisible from either side."""
    advertised = _live_tools()[LEAN_VERIFY.name].outputSchema
    assert advertised == json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert advertised == lean_verify_result_schema()


def test_the_advertised_schema_is_not_the_permissive_placeholder() -> None:
    """The exact shape #185 reported, pinned so a regression is legible.

    FastMCP derives `{"type": "object", "additionalProperties": true}` from a
    `dict` return annotation. It validates every payload and constrains none,
    which reads to a client as "documented" and means "unspecified".
    """
    advertised = _live_tools()[LEAN_VERIFY.name].outputSchema
    assert advertised.get("additionalProperties") is False
    assert len(advertised["required"]) == 13
    assert advertised.get("title") != "handle_lean_verifyDictOutput"


def test_the_advertised_schema_names_its_contract_version() -> None:
    """`version` is not a JSON Schema keyword and is shipped anyway: it tells a
    client WHICH `TOOL_SCHEMA_VERSION` this shape belongs to, on the wire,
    without a second request."""
    assert _live_tools()[LEAN_VERIFY.name].outputSchema["version"] == (
        TOOL_SCHEMA_VERSION
    )


def test_only_lean_verify_advertises_a_frozen_schema() -> None:
    """#185 is scoped to `lean_verify`. `search_papers_result.json` is frozen
    too and is NOT advertised — recorded here so the omission is a known scope
    boundary rather than something that looks done."""
    tools = _live_tools()
    assert tools[LEAN_VERIFY.name].outputSchema["additionalProperties"] is False
    others = [
        name for name, t in tools.items()
        if name != LEAN_VERIFY.name
        and (t.outputSchema or {}).get("additionalProperties") is not True
    ]
    assert others == [], f"unexpectedly strict outputSchema on {others}"


# --- the contract is enforced, not just published ------------------------------

def test_a_conforming_payload_validates_and_a_bootstrap_one_does_not() -> None:
    """The server must keep the promise it publishes.

    FastMCP's auto-derived `output_model` accepts any dict, so leaving it in
    place would advertise a strict contract while enforcing nothing. The model
    now validates against the FILE, which is what keeps the advertised, the
    enforced and the tested schema one thing.
    """
    from server.tools import _LeanVerifyResult

    validator = jsonschema.Draft7Validator(lean_verify_result_schema())
    stub = _build_bootstrap_envelope("lean_verify")
    errors = sorted(
        validator.iter_errors(stub.structuredContent), key=lambda e: str(e.path)
    )
    assert errors, "the bootstrap payload must NOT satisfy the frozen schema"

    #: The raw `jsonschema.ValidationError` propagates -- Pydantic v2 does not
    #: wrap a non-`ValueError` raised inside a validator. That is the better
    #: outcome: the message names the offending property and the schema path,
    #: where a wrapped one would say only "Value error". `Tool.run` catches it
    #: and re-raises as `ToolError`, so it reaches the client as a tool
    #: failure rather than a malformed success.
    with pytest.raises(jsonschema.ValidationError, match="(?i)additional propert"):
        _LeanVerifyResult.model_validate(stub.structuredContent)


def test_the_bootstrap_payload_satisfies_one_of_thirteen_required_fields() -> None:
    """#185 says "zero"; it is one — `corpus_version` — plus two properties the
    schema forbids. Recorded precisely because the number is the argument: a
    payload this far from its own contract is why the tool cannot both
    advertise the schema and keep the gate.
    """
    required = set(lean_verify_result_schema()["required"])
    payload = set(_build_bootstrap_envelope("lean_verify").structuredContent)
    assert payload & required == {"corpus_version"}
    assert payload - required == {"error_code", "tool"}


# --- the gate that had to go ---------------------------------------------------

def _bootstrap_resources() -> MagicMock:
    r = MagicMock()
    r.bootstrap_mode_active = True
    r.corpus_info = None
    r.config.bind_host = "127.0.0.1"
    r.config.bind_port = 7733
    return r


@pytest.fixture
def bootstrap_mode():
    set_resources(_bootstrap_resources())
    try:
        yield
    finally:
        reset_resources_for_tests()


def test_lean_verify_is_the_only_corpus_independent_tool() -> None:
    """`handle_lean_verify` touches `resources.lean_repl` and
    `resources.config` and nothing else — no chunk, no notebook, no index. The
    other seven read the corpus and must stay gated: answering from an
    un-ingested corpus is the failure bootstrap mode exists to prevent."""
    assert frozenset({LEAN_VERIFY.name}) == _CORPUS_INDEPENDENT_TOOLS
    gated = {t.name for t in ALL_TOOLS} - _CORPUS_INDEPENDENT_TOOLS
    assert len(gated) == 7


def test_envelope_uses_the_sentinel_when_there_is_no_corpus(
    bootstrap_mode,
) -> None:
    """The crash that was the gate's only real justification.

    `envelope()` reached `corpus_info.version` and raised `AttributeError`
    when `corpus_info` is None. The sentinel rather than `0`: zero is a real
    corpus version, and a caller comparing it would conclude the corpus is
    merely empty.
    """
    out = envelope({"status": "elaborated_no_errors"})
    assert out["corpus_version"] == BOOTSTRAP_CORPUS_VERSION_SENTINEL


def test_an_explicit_override_still_wins_over_the_sentinel(
    bootstrap_mode,
) -> None:
    """The per-notebook path (`filters.notebook`) passes its own version and
    must be unaffected by the fallback added beneath it."""
    assert envelope({}, override_corpus_version=7)["corpus_version"] == 7


def test_the_corpus_reading_tools_are_still_stubbed_in_bootstrap_mode(
    bootstrap_mode,
) -> None:
    """The half of the gate that is correct. Removing it for `lean_verify` must
    not remove it for anything that actually reads a corpus."""
    for name in ("get_chunk", "search_papers", "cite_neighbors"):
        stub = _build_bootstrap_envelope(name)
        assert stub.isError is True
        assert stub.structuredContent["error_code"] == "no_notebook_selected"
        assert stub.structuredContent["tool"] == name


# --- end to end ----------------------------------------------------------------

def test_the_handlers_real_output_validates_against_what_is_advertised() -> None:
    """`TestLeanVerifyResultSchema` already validates the handler against the
    FILE. This asserts the file and the WIRE are the same document, so that
    guarantee is one a client can rely on rather than one held only in this
    repo's tests."""
    advertised = _live_tools()[LEAN_VERIFY.name].outputSchema
    on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert advertised == on_disk
    jsonschema.Draft7Validator.check_schema(advertised)
