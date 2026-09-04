"""The formal-release resources, and the zero-cost claim proved mechanically.

derived-alg-geo-lean **#175**. Two resources — ``arxmcp://formal/{notebook}``
and ``arxmcp://formal/{notebook}/{key}`` — and the reason they are RESOURCES
rather than tools is a claim, not a preference: ``resources/read`` is a
different JSON-RPC method from ``tools/call``, so ``tools/list`` bytes are
untouched and neither ``EXPECTED_TOOL_SCHEMA_SHA256`` nor the BP1 prompt-cache
prefix moves. The issue asks for that to be asserted here rather than in a PR
description, which is what :class:`TestByteStability` does.

The other half is ADR-0004's asymmetry, which is the whole permission model
across the seam: arXMCP MAY downgrade a trust axis from its own fresher
information and has NO code path that raises one. So the record is re-served
verbatim and every judgement this server adds arrives as a generated caveat
BESIDE it. Those tests are the ones that fail if someone later "helpfully"
annotates a record in place.

Private-loop store fixture, mirroring ``tests/test_mcp_resources.py``. No
model load, no LanceDB, no network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from server.mcp_resources import (
    FORMAL_INDEX_TEMPLATE_URI,
    FORMAL_RECORD_TEMPLATE_URI,
    register_resources,
    reset_notebooks_store_for_tests,
    set_notebooks_store,
)
from server.notebooks_store import NotebooksStore
from server.tools import register_all
from tests.test_server_tool_schema import (
    EXPECTED_TOOL_SCHEMA_SHA256,
    compute_tool_schema_hash,
)
from tools import _notebook_common

SLUG = "bridgeland-stability"
REGISTRY_ID = "a520a8d4f877"
KEY = f"stmt:{REGISTRY_ID}:bridgeland2007.lem-8.2"
OTHER_KEY = f"stmt:{REGISTRY_ID}:bridgeland2007.def-1.1"


def _registry() -> dict:
    def entry(printed: str, version: str = "v3") -> dict:
        return {
            "kind": "lemma", "title": "A bound", "informal": "A bound.",
            "source": {"scheme": "arxiv", "id": "math/0212237",
                       "version": version, "printed_number": printed,
                       "locator": None},
            "quote_mode": "verbatim", "quote": f"Lemma {printed}. A bound.",
            "quote_norm": "nfc-ws-collapse/1", "quote_sha256": "e" * 64,
            "mint_resolution": None,
            "mint_unresolved_reason": "no resolver run",
            "depends_on": [], "frontier": [],
            "minted_at": "2026-08-05", "minted_by": "Chris Dare",
            "supersedes": None, "superseded_by": None,
        }

    return {
        "schema_version": "registry/1.0",
        "registry_id": REGISTRY_ID,
        "notebook_hint": SLUG,
        "entries": {KEY: entry("8.2"), OTHER_KEY: entry("1.1")},
    }


def _pin_row(**overrides) -> dict:
    row = {
        "slug": SLUG,
        "repo": "https://github.com/chris-dare-dev/derived-alg-geo-lean",
        "tag": "v0.1.0",
        "tag_object_sha": "df9e6e6d46028000bfd2241d2061cadcbb21e79d",
        "commit_sha": "7f649532ad83ac6a93b90918cba9fdbd779cec67",
        "registry_id": REGISTRY_ID,
        "registry_sha256": "f" * 64,
        "env_digest": "45d9e8ca8c1b" + "c" * 52,
        "digest_provenance": "self_attested_only",
        "asset_dir": "/abs/host/path/assets",
        "bundle_json": json.dumps({"schema_version": "bundle/1.0"}),
        "registry_json": json.dumps(_registry()),
        "resolution_json": None,
        "review_json": None,
        "withdrawals_json": None,
        "withdrawals_tag": "v0.1.0",
        "pinned_at": "2026-09-03T12:00:00Z",
    }
    row.update(overrides)
    return row


@pytest.fixture
def env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[asyncio.AbstractEventLoop, NotebooksStore]]:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    loop = asyncio.new_event_loop()
    store = loop.run_until_complete(NotebooksStore.open(tmp_path / "notebooks.db"))
    loop.run_until_complete(store.create_notebook(
        slug=SLUG, display_name="Bridgeland stability",
        lancedb_path=str(base / SLUG / "lancedb"),
        created_at="2026-05-21T00:00:00Z",
    ))
    set_notebooks_store(store)
    try:
        yield loop, store
    finally:
        loop.run_until_complete(store.close())
        loop.close()
        reset_notebooks_store_for_tests()


def _mcp() -> FastMCP:
    mcp = FastMCP("arxmcp", json_response=True)
    register_all(mcp)
    register_resources(mcp)
    return mcp


def _read(loop, mcp: FastMCP, uri: str) -> dict:
    contents = loop.run_until_complete(mcp.read_resource(uri))
    text = "".join(c.content for c in contents)
    assert text.startswith("<retrieved_formal>")
    assert text.endswith("</retrieved_formal>")
    inner = text[len("<retrieved_formal>"): -len("</retrieved_formal>")]
    return json.loads(inner)


def _pin(loop, store: NotebooksStore, **overrides) -> None:
    loop.run_until_complete(store.upsert_formal_release(_pin_row(**overrides)))


# --- the zero-cost claim, asserted rather than described ------------------------

class TestByteStability:
    """`EXPECTED_TOOL_SCHEMA_SHA256` and the BP1 prefix must not move.

    #175: "must assert EXPECTED_TOOL_SCHEMA_SHA256 is unchanged — proving the
    zero-cost claim mechanically rather than asserting it in a PR
    description." If one of these fails, a resource LEAKED into the tool
    registry. Fix the leak; do not re-pin the constant.
    """

    def test_the_tool_schema_hash_is_unchanged(self) -> None:
        tools = asyncio.run(_mcp().list_tools())
        assert compute_tool_schema_hash(tools) == EXPECTED_TOOL_SCHEMA_SHA256

    def test_the_formal_resources_add_no_tools(self) -> None:
        """Two servers, one with the resources: identical tool lists.

        Stronger than comparing against the pinned constant alone, which would
        also pass if BOTH the constant and the surface had drifted together.
        """
        base = FastMCP("arxmcp", json_response=True)
        register_all(base)
        base_tools = asyncio.run(base.list_tools())
        with_resources = asyncio.run(_mcp().list_tools())
        assert [t.name for t in base_tools] == [t.name for t in with_resources]
        assert compute_tool_schema_hash(base_tools) == \
            compute_tool_schema_hash(with_resources) == EXPECTED_TOOL_SCHEMA_SHA256

    def test_they_are_registered_as_templates_on_notebook(self) -> None:
        """Templating on `{notebook}` is what makes a SECOND topic repo cost
        zero arXMCP code — no new URI, no new registration, no schema bump."""
        templates = asyncio.run(_mcp().list_resource_templates())
        uris = {str(t.uriTemplate) for t in templates}
        assert FORMAL_INDEX_TEMPLATE_URI in uris
        assert FORMAL_RECORD_TEMPLATE_URI in uris


# --- a notebook that pins nothing ----------------------------------------------

def test_an_unpinned_notebook_answers_rather_than_erroring(env) -> None:
    """"This corpus has no formalization" is an answer, and it is the state
    almost every notebook is in. Raising here would make the ordinary case
    look like a fault."""
    loop, _ = env
    payload = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}")
    assert payload["pinned"] is False
    assert "no formal release is pinned" in payload["reason"]


def test_a_record_read_on_an_unpinned_notebook_is_an_error(env) -> None:
    """Different from the index: there is no record to describe, so there is
    nothing to answer WITH."""
    loop, _ = env
    with pytest.raises(Exception, match="pins no formal release"):
        _read(loop, _mcp(), f"arxmcp://formal/{SLUG}/{KEY}")


# --- the index -----------------------------------------------------------------

def test_the_index_reports_what_was_pinned_and_how_it_was_verified(env) -> None:
    loop, store = env
    _pin(loop, store)
    payload = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}")
    assert payload["pinned"] is True
    assert payload["pin"]["tag"] == "v0.1.0"
    assert payload["pin"]["tag_object_sha"].startswith("df9e6e6d")
    assert payload["pin"]["digest_provenance"] == "self_attested_only"
    assert sorted(payload["keys"]) == sorted([KEY, OTHER_KEY])


def test_coverage_is_a_dated_census_and_names_its_missing_denominator(env) -> None:
    """§4.9 rule 3. Ten records against a 15,280-chunk notebook have covered
    ~0.07% of it, and a bare `entries: 10` reads as a covered corpus.

    `corpus_chunks` is null rather than absent, and says so in a sibling field:
    the number a reader looks for is present and visibly unanswered instead of
    quietly missing. #179 owns measuring it.
    """
    loop, store = env
    _pin(loop, store)
    census = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}")["census"]
    assert census["entries"] == 2
    assert census["papers_covered"] == 1
    assert census["corpus_chunks"] is None
    assert "coverage fraction" in census["corpus_chunks_note"]
    assert census["generated_at"].endswith("Z")


def test_the_index_caveats_name_every_absent_axis(env) -> None:
    """Absent is not passing. A pin with no resolution and no review says so
    on every read, rather than leaving a reader to notice two missing keys."""
    loop, store = env
    _pin(loop, store)
    caveats = " ".join(_read(loop, _mcp(), f"arxmcp://formal/{SLUG}")["caveats"])
    assert "self_attested_only" in caveats
    assert "No corpus resolution" in caveats
    assert "No human faithfulness review" in caveats


# --- one record, verbatim -------------------------------------------------------

def test_the_record_is_the_producers_entry_byte_for_byte(env) -> None:
    """ADR-0004: arXMCP may DOWNGRADE an axis from its own fresher
    information, and has no code path that raises one. Re-serving verbatim is
    what makes that asymmetry checkable — an edited record cannot be compared
    to what the producer published."""
    loop, store = env
    _pin(loop, store)
    payload = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}/{KEY}")
    assert payload["entry"] == _registry()["entries"][KEY]


def test_this_servers_judgements_arrive_beside_the_record_not_inside_it(env) -> None:
    """The caveats are the only channel. If a future change annotates the
    entry in place, this fails — which is the point."""
    loop, store = env
    _pin(loop, store)
    payload = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}/{KEY}")
    assert set(payload["entry"]) == set(_registry()["entries"][KEY])
    assert payload["caveats"] and isinstance(payload["caveats"], list)


def test_an_unknown_key_is_an_error_not_an_empty_record(env) -> None:
    loop, store = env
    _pin(loop, store)
    with pytest.raises(Exception, match="no entry"):
        _read(loop, _mcp(), f"arxmcp://formal/{SLUG}/stmt:{REGISTRY_ID}:nope")


# --- withdrawals come first -----------------------------------------------------

def _withdrawals(key: str = KEY, registry_id: str = REGISTRY_ID) -> str:
    return json.dumps({
        "schema_version": "withdrawals/1.0",
        "registry_id": registry_id,
        "withdrawals": [{
            "key": key,
            "withdrawn_at": "2026-09-01",
            "reason": "the reviewer found the statement diverges from the paper",
        }],
    })


def test_a_withdrawn_record_says_so_first(env) -> None:
    """The worst failure this contract can have is a record a human has
    determined is NOT faithful still being served as evidence. A reader who
    stops after one caveat must read that one."""
    loop, store = env
    _pin(loop, store, withdrawals_json=_withdrawals(), withdrawals_tag="v0.2.0")
    payload = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}/{KEY}")
    assert payload["withdrawn"] is True
    assert payload["caveats"][0].startswith("WITHDRAWN")
    assert "diverges from the paper" in payload["caveats"][0]


def test_a_withdrawal_names_the_tag_it_came_from(env) -> None:
    """It is read from the NEWEST tag even when pinned to an older one — the
    single channel allowed to travel forward in time. A reader comparing the
    pinned tag to the withdrawal's tag must be able to see that happen."""
    loop, store = env
    _pin(loop, store, withdrawals_json=_withdrawals(), withdrawals_tag="v0.2.0")
    caveat = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}/{KEY}")["caveats"][0]
    assert "v0.2.0" in caveat and "v0.1.0" in caveat


def test_a_withdrawal_of_another_key_does_not_touch_this_one(env) -> None:
    """A revocation channel that fires on the wrong keys is worse than none."""
    loop, store = env
    _pin(loop, store, withdrawals_json=_withdrawals(key=OTHER_KEY))
    payload = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}/{KEY}")
    assert payload["withdrawn"] is False
    assert not any(c.startswith("WITHDRAWN") for c in payload["caveats"])


def test_the_index_counts_withdrawn_entries(env) -> None:
    loop, store = env
    _pin(loop, store, withdrawals_json=_withdrawals())
    census = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}")["census"]
    assert census["entries"] == 2 and census["withdrawn"] == 1


def test_unparseable_withdrawals_do_not_take_the_resource_down(env) -> None:
    """A record served WITHOUT its withdrawal is the failure this channel
    exists to prevent, so the alternative would be to fail the read — but the
    withdrawals blob is written by the pinner, which validated it, and a
    corrupt one here means local damage rather than an untrustworthy producer.
    Degrade to no-withdrawals and log; the caveats still say no review and no
    resolution accompany the pin."""
    loop, store = env
    _pin(loop, store, withdrawals_json="{not json")
    payload = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}/{KEY}")
    assert payload["withdrawn"] is False


# --- security -------------------------------------------------------------------

def test_an_invalid_slug_is_rejected_before_any_store_access(env) -> None:
    """`validate_slug` FIRST — the same discipline the notebook resources
    carry. A traversal in the notebook segment must never reach a path join."""
    loop, _ = env
    # `NotebookError` is what `validate_slug` raises; FastMCP may wrap a
    # resource-callback failure, so the assertion is on the MESSAGE reaching
    # the caller rather than on the class. A bare `Exception` would also pass
    # if the read failed for an unrelated reason.
    with pytest.raises(Exception, match="(?i)slug"):
        _read(loop, _mcp(), "arxmcp://formal/..%2F..%2Fetc")


def test_the_payload_never_exposes_the_asset_dir(env) -> None:
    """`asset_dir` is a host path. It is in the pin so an OPERATOR can find
    the 16 MB artifacts; it is not in the served record, because a filesystem
    layout is not something an agent on the other side of the seam needs."""
    loop, store = env
    _pin(loop, store)
    index = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}")
    record = _read(loop, _mcp(), f"arxmcp://formal/{SLUG}/{KEY}")
    assert "/abs/host/path" not in json.dumps(index)
    assert "/abs/host/path" not in json.dumps(record)
