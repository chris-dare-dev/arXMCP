"""get_chunk license-truncation handler tests (textbook-ingest-m11 / e5).

The non-OA license-truncation policy: ``get_chunk`` surfaces at most
``LICENSE_TRUNCATION_CHARS`` (300) chars of a NON-open-access chunk's body
and flags the response ``truncated_for_license=True``; open-access chunks
return their full body with no flag.

The ORDERING invariant (license-truncate BEFORE the byte-cap + before the
<retrieved_chunk> wrap) is the load-bearing correctness property
(textbook-ingest-m11 FM-1/FM-2): a non-OA chunk can never surface >300
chars via ANY path — not the delimiter wrap, not the resource_link.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pyarrow as pa
import pytest

from server.handlers.chunk import handle_get_chunk
from server.license_policy import LICENSE_TRUNCATION_CHARS

# E13_S02 delimiter tags (stable contract).
_OPEN = "<retrieved_chunk>"
_CLOSE = "</retrieved_chunk>"

_OA_ID = "arxiv:2401.00001:abcdef0123456789"
_NONOA_ID = "textbook:sv-book:abcdef0123456789"


def _run(coro):
    return asyncio.run(coro)


def _chunk_arrow(
    *, chunk_id: str, body_text: str, license_token: str | None,
    paper_id: str = "textbook:sv-book",
) -> pa.Table:
    """Build a 1-row chunks-table Arrow result for get_chunk's
    ``.search().where().limit(1).to_arrow()`` chain."""
    return pa.table({
        "chunk_id": [chunk_id],
        "paper_id": [paper_id],
        "kind": ["definition"],
        "section_path": pa.array([["Chapter 1"]], type=pa.list_(pa.utf8())),
        "body_text": pa.array([body_text], type=pa.utf8()),
        "theorem_name": pa.array([None], type=pa.utf8()),
        "theorem_label": pa.array([None], type=pa.utf8()),
        "chunker_version": ["tv0.1"],
        "embedder_version": ["bge-m3"],
        "preamble_ref": pa.array([None], type=pa.utf8()),
        "license": pa.array([license_token], type=pa.utf8()),
    })


@pytest.fixture
def res(monkeypatch: pytest.MonkeyPatch):
    """Install a fake Resources whose chunks_table returns a settable
    1-row Arrow table for get_chunk. Reset afterward so other tests are
    not polluted."""
    from server.tools import reset_resources_for_tests, set_resources

    holder: dict[str, Any] = {"arrow": None}

    class _Builder:
        def where(self, *a: Any, **k: Any) -> _Builder:
            return self

        def limit(self, *a: Any, **k: Any) -> _Builder:
            return self

        def to_arrow(self):
            return holder["arrow"]

    class _FakeChunksTable:
        def search(self, *a: Any, **k: Any) -> _Builder:
            return _Builder()

    class _FakeConfig:
        result_byte_cap = 256 * 1024

    class _FakeCorpusInfo:
        version = 101

    class _FakeResources:
        def __init__(self) -> None:
            self.config = _FakeConfig()
            self.chunks_table = _FakeChunksTable()
            self.corpus_info = _FakeCorpusInfo()
            self.degraded = None

    set_resources(_FakeResources())  # type: ignore[arg-type]
    yield {"holder": holder}
    reset_resources_for_tests()


def _get(res, *, chunk_id: str, body_text: str, license_token: str | None):
    res["holder"]["arrow"] = _chunk_arrow(
        chunk_id=chunk_id, body_text=body_text, license_token=license_token,
    )
    return _run(handle_get_chunk(chunk_id=chunk_id))


def _inner(wrapped: str) -> str:
    """Strip the <retrieved_chunk> wrapper, asserting it is INTACT
    (FM-1: license truncation must not slice the delimiter tags)."""
    assert wrapped.startswith(_OPEN), f"open tag missing/sliced: {wrapped[:40]!r}"
    assert wrapped.endswith(_CLOSE), f"close tag missing/sliced: {wrapped[-40:]!r}"
    return wrapped[len(_OPEN):-len(_CLOSE)]


class TestGetChunkLicenseTruncation:
    def test_open_access_returns_full_body_no_flag(self, res) -> None:
        body = "x" * 500
        r = _get(res, chunk_id=_OA_ID, body_text=body, license_token="arxiv-license")
        assert _inner(r["chunk"]["body_text"]) == body
        assert "truncated_for_license" not in r

    def test_gfdl_is_open_access_full_body(self, res) -> None:
        body = "g" * 500
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token="GFDL")
        assert _inner(r["chunk"]["body_text"]) == body
        assert "truncated_for_license" not in r

    def test_non_oa_body_truncated_to_300_with_flag(self, res) -> None:
        body = "y" * 500
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token="author-distributed")
        assert len(_inner(r["chunk"]["body_text"])) == LICENSE_TRUNCATION_CHARS
        assert r["truncated_for_license"] is True

    def test_unknown_license_fail_closed(self, res) -> None:
        body = "z" * 500
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token="weird-unknown-license")
        assert len(_inner(r["chunk"]["body_text"])) == LICENSE_TRUNCATION_CHARS
        assert r["truncated_for_license"] is True

    def test_empty_license_fail_closed(self, res) -> None:
        body = "z" * 500
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token="")
        assert len(_inner(r["chunk"]["body_text"])) == LICENSE_TRUNCATION_CHARS
        assert r["truncated_for_license"] is True

    def test_null_license_fail_closed(self, res) -> None:
        body = "z" * 500
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token=None)
        assert len(_inner(r["chunk"]["body_text"])) == LICENSE_TRUNCATION_CHARS
        assert r["truncated_for_license"] is True

    def test_non_oa_short_body_not_truncated_no_flag(self, res) -> None:
        """A non-OA chunk whose body is already < 300 chars is returned
        whole — truncation only fires when it would actually shorten."""
        body = "a short non-OA body well under three hundred chars"
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token="author-distributed")
        assert _inner(r["chunk"]["body_text"]) == body
        assert "truncated_for_license" not in r

    def test_license_token_surfaced_in_chunk(self, res) -> None:
        """m11 D4: the license token is surfaced so an agent sees WHY a
        body was (or was not) truncated."""
        r = _get(res, chunk_id=_NONOA_ID, body_text="hi", license_token="author-distributed")
        assert r["chunk"]["license"] == "author-distributed"

    def test_delimiter_wrap_intact_after_truncation(self, res) -> None:
        """FM-1: license truncation operates on the INNER body before the
        wrap, so the </retrieved_chunk> close tag is never sliced."""
        body = "m" * 1000
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token="author-distributed")
        wrapped = r["chunk"]["body_text"]
        assert wrapped.startswith(_OPEN)
        assert wrapped.endswith(_CLOSE)  # tag intact, not sliced
        assert len(_inner(wrapped)) == LICENSE_TRUNCATION_CHARS

    def test_non_oa_huge_body_never_emits_resource_link(self, res) -> None:
        """FM-2 (headline risk): a >256 KB non-OA body is license-truncated
        to 300 chars FIRST, so the byte-cap never fires and no
        resource_link to the full unrestricted body is emitted."""
        body = "h" * (300 * 1024)  # 300 KB, over the 256 KB byte-cap
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token="author-distributed")
        assert "resource_link_uri" not in r, "non-OA chunk must NOT emit a full-body resource_link"
        assert not r.get("body_truncated"), "byte-cap must not fire on a 300-char body"
        assert len(_inner(r["chunk"]["body_text"])) == LICENSE_TRUNCATION_CHARS
        assert r["truncated_for_license"] is True

    def test_oa_huge_body_still_byte_capped(self, res) -> None:
        """An OPEN-access chunk is NOT license-truncated, so a >256 KB
        body still hits the byte-cap path (body_truncated + resource_link)
        — the existing E13_S04 behavior is unchanged for OA chunks."""
        body = "h" * (300 * 1024)
        r = _get(res, chunk_id=_OA_ID, body_text=body, license_token="arxiv-license")
        assert "truncated_for_license" not in r
        assert r.get("body_truncated") is True
        assert "resource_link_uri" in r
