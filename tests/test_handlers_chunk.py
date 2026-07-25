"""get_chunk full-body serving tests (license-serving-removal-m1).

get_chunk returns the FULL sanitized chunk body for EVERY license token —
the former textbook-ingest-m11 / e5 300-char non-OA license-truncation gate
is removed (the served corpus is never redistributed, so licensing gates no
serving decision). No response carries a ``truncated_for_license`` flag.

The only remaining length safeguard is the size-based 256 KB byte-cap +
resource_link path (E13_S04), which is unrelated to license and applies to
every chunk. The <retrieved_chunk> delimiter wrap (E13_S02) is well-formed
around the full body.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pyarrow as pa
import pytest

from server.handlers.chunk import handle_get_chunk

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


def _chunk_arrow_v2(
    *,
    chunk_id: str = _OA_ID,
    license_token: str | None = "arxiv-license",
    source_revision_id: str | None = "2401.00001",
    source_span: str | None = '{"id":"","rev":"9e729a","txt":"95e9c2"}',
    truncated: bool | None = False,
    printed_number: str | None = "3.1",
    license_ref: str | None = "not-allowlisted-open",
) -> pa.Table:
    """A HYDRATED (v2 / 26-col schema) chunks-table Arrow result — a minimal
    stand-in carrying the base columns PLUS the 5 source-truth-m2 columns.
    (``_chunk_arrow`` itself is the UNMIGRATED (pre-v2 schema) case — the 5
    source-truth columns ABSENT, as on the live ``-pdfs`` notebooks. The
    26/21 numbers name the real schema versions, not these fixtures' counts.)"""
    base = _chunk_arrow(
        chunk_id=chunk_id, body_text="body", license_token=license_token,
        paper_id="arxiv:2401.00001",
    )
    cols = {name: base.column(name) for name in base.column_names}
    cols["source_revision_id"] = pa.array([source_revision_id], type=pa.utf8())
    cols["source_span"] = pa.array([source_span], type=pa.utf8())
    cols["truncated"] = pa.array([truncated], type=pa.bool_())
    cols["printed_number"] = pa.array([printed_number], type=pa.utf8())
    cols["license_ref"] = pa.array([license_ref], type=pa.utf8())
    return pa.table(cols)


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
    (the delimiter tags must never be sliced)."""
    assert wrapped.startswith(_OPEN), f"open tag missing/sliced: {wrapped[:40]!r}"
    assert wrapped.endswith(_CLOSE), f"close tag missing/sliced: {wrapped[-40:]!r}"
    return wrapped[len(_OPEN):-len(_CLOSE)]


class TestGetChunkNoLicenseTruncation:
    """license-serving-removal-m1: get_chunk returns the FULL body for EVERY
    license token — the 300-char non-OA truncation gate (formerly
    textbook-ingest-m11 / e5) is removed. No response carries a
    ``truncated_for_license`` flag. The only remaining length safeguard is
    the size-based 256 KB byte-cap, which is unrelated to license."""

    @pytest.mark.parametrize(
        "license_token",
        [
            "arxiv-license", "GFDL", "CC-BY",      # formerly open-access
            "author-distributed", "copyrighted",    # formerly non-OA -> truncated
            "weird-unknown-license",                # unknown token
            "",                                     # empty
            None,                                   # null (legacy / missing column)
        ],
    )
    def test_full_body_returned_for_any_license(self, res, license_token) -> None:
        """Regression (owner directive: never truncate on license): a
        500-char body is returned IN FULL for any license token — including
        the formerly-truncated non-OA / unknown / null cases — with no
        ``truncated_for_license`` flag."""
        body = "x" * 500
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token=license_token)
        assert _inner(r["chunk"]["body_text"]) == body
        assert "truncated_for_license" not in r

    def test_license_token_still_surfaced_as_metadata(self, res) -> None:
        """The license token is still surfaced as informational provenance
        — it just no longer gates serving."""
        r = _get(res, chunk_id=_NONOA_ID, body_text="hi", license_token="author-distributed")
        assert r["chunk"]["license"] == "author-distributed"

    def test_delimiter_wrap_intact_around_full_body(self, res) -> None:
        """The <retrieved_chunk> wrap is well-formed around the full body
        (no license slice can touch the delimiter tags anymore)."""
        body = "m" * 1000
        r = _get(res, chunk_id=_NONOA_ID, body_text=body, license_token="author-distributed")
        wrapped = r["chunk"]["body_text"]
        assert wrapped.startswith(_OPEN)
        assert wrapped.endswith(_CLOSE)
        assert _inner(wrapped) == body

    def test_huge_body_byte_capped_regardless_of_license(self, res) -> None:
        """A >256 KB body hits the size-based byte-cap (body_truncated +
        resource_link) for ANY license. The old non-OA carve-out that
        truncated to 300 chars FIRST (so the cap never fired and no link was
        emitted) is gone: a formerly-OA and a formerly-non-OA huge body now
        behave identically."""
        body = "h" * (300 * 1024)  # 300 KB, over the 256 KB byte-cap
        for license_token, cid in (
            ("arxiv-license", _OA_ID),
            ("author-distributed", _NONOA_ID),
        ):
            r = _get(res, chunk_id=cid, body_text=body, license_token=license_token)
            assert "truncated_for_license" not in r
            assert r.get("body_truncated") is True, f"{license_token}: byte-cap must fire"
            assert "resource_link_uri" in r, f"{license_token}: resource_link expected"


class TestGetChunkSourceTruthFields:
    """source-truth-m5: get_chunk surfaces the 5 m2 chunks-schema-v2 fields,
    explicit-null when the column is NULL (abstained) or absent (an
    unmigrated notebook) — never omitted, never a 500."""

    _FIVE = (
        "source_revision_id", "source_span", "truncated",
        "printed_number", "license_ref",
    )

    def test_hydrated_notebook_surfaces_all_five(self, res) -> None:
        res["holder"]["arrow"] = _chunk_arrow_v2()
        r = _run(handle_get_chunk(chunk_id=_OA_ID))
        chunk = r["chunk"]
        for f in self._FIVE:
            assert f in chunk, f"{f} must be present"
        assert chunk["source_revision_id"] == "2401.00001"
        assert chunk["source_span"] == '{"id":"","rev":"9e729a","txt":"95e9c2"}'
        assert chunk["truncated"] is False
        assert chunk["printed_number"] == "3.1"
        assert chunk["license_ref"] == "not-allowlisted-open"

    def test_unmigrated_notebook_surfaces_explicit_null(self, res) -> None:
        """The pre-m2 (21-col) fixture: the 5 columns are ABSENT from the
        Arrow row (the live ``-pdfs`` notebooks). ``row.get()`` must degrade
        to explicit null, never a KeyError/500 (the m5 landmine)."""
        res["holder"]["arrow"] = _chunk_arrow(
            chunk_id=_OA_ID, body_text="body", license_token="arxiv-license",
        )
        r = _run(handle_get_chunk(chunk_id=_OA_ID))
        assert r["found"] is True
        chunk = r["chunk"]
        for f in self._FIVE:
            assert f in chunk, f"{f} must be present even when the column is absent"
            assert chunk[f] is None, f"{f} must be explicit null on an unmigrated notebook"

    def test_hydrated_but_null_source_span_is_explicit_null(self, res) -> None:
        """An abstained span (backfill couldn't re-anchor) on a hydrated
        notebook: column present, value NULL -> explicit null, key present."""
        res["holder"]["arrow"] = _chunk_arrow_v2(source_span=None, printed_number=None)
        chunk = _run(handle_get_chunk(chunk_id=_OA_ID))["chunk"]
        assert "source_span" in chunk and chunk["source_span"] is None
        assert "printed_number" in chunk and chunk["printed_number"] is None
        assert chunk["source_revision_id"] == "2401.00001"  # still populated

    def test_license_ref_is_advisory_not_wired_to_serving(self, res) -> None:
        """``license_ref`` (and the ``license`` token) are advisory /
        informational ONLY: no license value gates serving. An OA-token
        chunk whose ``license_ref`` is ``not-allowlisted-open`` returns its
        FULL body — as does every other license (license-serving-removal-m1;
        the owner-gated source-truth-m4 cutover was retired)."""
        big = "z" * 500
        arrow = _chunk_arrow_v2(
            license_token="arxiv-license", license_ref="not-allowlisted-open",
        )
        cols = {name: arrow.column(name) for name in arrow.column_names}
        cols["body_text"] = pa.array([big], type=pa.utf8())
        res["holder"]["arrow"] = pa.table(cols)
        r = _run(handle_get_chunk(chunk_id=_OA_ID))
        assert _inner(r["chunk"]["body_text"]) == big  # full body, not truncated
        assert "truncated_for_license" not in r
        assert r["chunk"]["license_ref"] == "not-allowlisted-open"


# ===========================================================================
# agent-platform-t-batch-chunk-fetch (#83) — batched get_chunk
# ===========================================================================

_VALID_ID = "arxiv:2401.00001:0123456789abcdef"
_VALID_ID2 = "arxiv:2401.00002:0123456789abcdef"
_VALID_ID3 = "arxiv:2401.00003:0123456789abcdef"


def _chunk_arrow_multi(ids: list[str]) -> pa.Table:
    """A multi-row chunks-table Arrow result (the batch IN query)."""
    n = len(ids)
    return pa.table({
        "chunk_id": list(ids),
        "paper_id": [f"2401.{i:05d}" for i in range(n)],
        "kind": ["definition"] * n,
        "section_path": pa.array([["Chapter 1"]] * n, type=pa.list_(pa.utf8())),
        "body_text": pa.array([f"body {i}" for i in range(n)], type=pa.utf8()),
        "theorem_name": pa.array([None] * n, type=pa.utf8()),
        "theorem_label": pa.array([None] * n, type=pa.utf8()),
        "chunker_version": ["tv0.1"] * n,
        "embedder_version": ["bge-m3"] * n,
        "preamble_ref": pa.array([None] * n, type=pa.utf8()),
        "license": pa.array(["arxiv-license"] * n, type=pa.utf8()),
    })


class TestBatchFetch:
    def test_scalar_still_returns_flat_object(self, res):
        """The v1 contract is preserved: a scalar chunk_id returns the
        flat {chunk, found} envelope, NOT a chunks[] array."""
        res["holder"]["arrow"] = _chunk_arrow_multi([_VALID_ID])
        out = _run(handle_get_chunk(chunk_id=_VALID_ID))
        body = out.get("structuredContent", out)
        assert "chunks" not in body
        assert body["found"] is True
        assert body["chunk"]["chunk_id"] == _VALID_ID

    def test_list_returns_chunks_array_in_request_order(self, res):
        res["holder"]["arrow"] = _chunk_arrow_multi([_VALID_ID2, _VALID_ID])
        out = _run(handle_get_chunk(chunk_id=[_VALID_ID, _VALID_ID2]))
        body = out.get("structuredContent", out)
        assert "chunk" not in body  # not the flat shape
        assert len(body["chunks"]) == 2
        # request order preserved regardless of DB return order
        assert body["chunks"][0]["chunk"]["chunk_id"] == _VALID_ID
        assert body["chunks"][1]["chunk"]["chunk_id"] == _VALID_ID2

    def test_missing_id_is_found_false_element(self, res):
        # only _VALID_ID present; _VALID_ID2 absent
        res["holder"]["arrow"] = _chunk_arrow_multi([_VALID_ID])
        out = _run(handle_get_chunk(chunk_id=[_VALID_ID, _VALID_ID2]))
        body = out.get("structuredContent", out)
        assert body["chunks"][0]["found"] is True
        assert body["chunks"][1]["found"] is False
        assert body["chunks"][1]["chunk"] is None

    def test_batch_is_one_query(self, res, monkeypatch):
        """N ids => ONE LanceDB search, not N."""
        calls = {"n": 0}
        from server.tools import get_resources

        table = get_resources().chunks_table
        orig = table.search

        def _counting_search(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        monkeypatch.setattr(table, "search", _counting_search)
        res["holder"]["arrow"] = _chunk_arrow_multi([_VALID_ID, _VALID_ID2, _VALID_ID3])
        _run(handle_get_chunk(chunk_id=[_VALID_ID, _VALID_ID2, _VALID_ID3]))
        assert calls["n"] == 1

    def test_over_max_batch_rejected(self, res):
        ids = [f"arxiv:2401.{i:05d}:0123456789abcdef" for i in range(21)]
        res["holder"]["arrow"] = _chunk_arrow_multi(ids[:20])
        with pytest.raises(ValueError, match="max 20"):
            _run(handle_get_chunk(chunk_id=ids))

    def test_empty_batch_rejected(self, res):
        res["holder"]["arrow"] = _chunk_arrow_multi([])
        with pytest.raises(ValueError, match="must not be empty"):
            _run(handle_get_chunk(chunk_id=[]))

    def test_malformed_id_in_batch_rejected(self, res):
        res["holder"]["arrow"] = _chunk_arrow_multi([_VALID_ID])
        with pytest.raises(ValueError, match="does not match"):
            _run(handle_get_chunk(chunk_id=[_VALID_ID, "not-a-chunk-id"]))
