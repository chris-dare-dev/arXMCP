"""The mint prefill, and the four things it is forbidden to do.

derived-alg-geo-lean **#169**. Most of what matters about this tool is what it
REFUSES: it does not mint identity (ADR-0002), it does not write to the topic
repo (ADR-0001), it does not break a tie between candidate chunks, and it does
not fill in a field a human owes. A prefill that did any of those would be more
convenient and would defeat the point of a hand-minted registry.

The `printed_number` lookup is also asserted here as a lookup in its own right.
It is the reason this file lives in arXMCP rather than in `mfc` — the audit
found no path anywhere that fetches "the chunk numbered 8.2".

No LanceDB and no network: the chunk list is injected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools._statement_common import Chunk
from tools.statement_mint import (
    HUMAN_OWNED,
    build_entry,
    find_by_printed_number,
    find_by_text,
)

mfc_digest = pytest.importorskip("mfc.digest")

PAPER = "math/0212237"
BODY_82 = (
    "Lemma 8.2. Suppose $\\|\\sigma_1-\\sigma_2\\|<1/8$. Then the induced map "
    "on slicings is well-defined."
)
BODY_APPENDIX_82 = (
    "Lemma A.8.2 restated. The appendix reprints the bound of Lemma 8.2 in the "
    "numbering of this section."
)


def _chunk(suffix: str, body: str, printed: str | None) -> Chunk:
    return Chunk(
        chunk_id=f"arxiv:{PAPER}:{suffix}",
        paper_id=PAPER,
        body_text=body,
        printed_number=printed,
        chunker_version="v1.1",
    )


def _corpus() -> list[Chunk]:
    return [
        _chunk("1111111111111111", BODY_82, "8.2"),
        _chunk("2222222222222222", BODY_APPENDIX_82, "8.2"),
        _chunk("3333333333333333", "Proposition 8.1. A local homeomorphism.", "8.1"),
        _chunk("4444444444444444", "An unnumbered remark.", None),
        Chunk(chunk_id="arxiv:2101.04404:5555555555555555",
              paper_id="2101.04404", body_text=BODY_82, printed_number="8.2"),
    ]


# --- the lookup that did not exist ---------------------------------------------

def test_printed_number_fetches_the_chunk_numbered_that() -> None:
    """*Fetch the chunk numbered 8.1.* No tool in this repo accepted a
    printed_number as an input before this one."""
    hits = find_by_printed_number(_corpus(), PAPER, "8.1")
    assert [c.chunk_id for c in hits] == [f"arxiv:{PAPER}:3333333333333333"]


def test_printed_number_is_scoped_to_the_paper() -> None:
    """Numbers are per-paper. A lookup that ignored `paper_id` would return
    another paper's Lemma 8.2, and it looks exactly as plausible."""
    hits = find_by_printed_number(_corpus(), PAPER, "8.2")
    assert all(c.paper_id == PAPER for c in hits)
    assert len(hits) == 2


def test_printed_number_returns_every_match_rather_than_the_first() -> None:
    """It is not unique by construction — a body and an appendix can both
    print 8.2, and a re-chunk can leave two chunks carrying it. Returning one
    would be a coin flip wearing a lookup's clothes; the caller refuses on
    more than one."""
    assert len(find_by_printed_number(_corpus(), PAPER, "8.2")) == 2


def test_printed_number_matching_ignores_surrounding_whitespace() -> None:
    chunks = [_chunk("6666666666666666", "text", " 8.2 ")]
    assert find_by_printed_number(chunks, PAPER, "8.2")


@pytest.mark.parametrize("locator", ["", "   "])
def test_an_empty_locator_matches_nothing_rather_than_everything(
    locator: str,
) -> None:
    """`(c.printed_number or "") == ""` matches every chunk the chunker could
    not number — which on the textbook and MinerU paths is ALL of them.

    An empty locator selecting the whole notebook is the worst possible answer
    to it, and it looks like a working lookup right up until someone mints
    from the first result.
    """
    assert find_by_printed_number(_corpus(), PAPER, locator) == []


# --- the search, which lists ----------------------------------------------------

def test_search_is_whitespace_and_nfc_insensitive() -> None:
    """Same normalization as the digest, so a line-wrap difference between
    what an operator pastes and what the chunker stored is not a miss."""
    hits = find_by_text(
        _corpus(), PAPER, "induced   map\non   slicings", mfc_digest.norm_text
    )
    assert [c.chunk_id for c in hits] == [f"arxiv:{PAPER}:1111111111111111"]


def test_an_empty_search_matches_nothing_rather_than_everything() -> None:
    """The empty string is contained in every body. Returning the whole paper
    is the least useful possible answer to an empty query, and looks like a
    working search."""
    assert find_by_text(_corpus(), PAPER, "   ", mfc_digest.norm_text) == []


def test_search_is_scoped_to_the_paper() -> None:
    hits = find_by_text(_corpus(), PAPER, "well-defined", mfc_digest.norm_text)
    assert all(c.paper_id == PAPER for c in hits)


# --- the fragment ---------------------------------------------------------------

def _entry(**kw):
    defaults = dict(
        scheme="arxiv", work_id=PAPER, source_version="v3",
        notebook="bridgeland-stability", corpus_version=5048,
        corpus_manifest_content_hash="1" * 64,
        quote_sha256=mfc_digest.quote_sha256,
        minted_at="2026-09-03", observed_at="2026-09-03T12:00:00Z",
    )
    defaults.update(kw)
    return build_entry(_corpus()[0], **defaults)


def test_the_quote_is_the_chunk_body_byte_for_byte() -> None:
    """Not normalized, not cleaned. `quote` is the MACHINE-owned field and
    `mint_resolution.matched_by: quote_sha256` requires byte-equality with the
    chunk; anything tidied here demotes the entry to printed_number forever.
    A human's corrections belong in `quote_as_read`."""
    assert _entry()["quote"] == BODY_82


def test_the_digest_is_the_function_the_resolver_will_compare_against() -> None:
    """Two implementations of one comparison is the failure mode the whole
    contract exists to prevent, so this asserts the identity rather than a
    recomputed constant."""
    assert _entry()["quote_sha256"] == mfc_digest.quote_sha256(BODY_82)
    assert _entry()["quote_norm"] == mfc_digest.TEXT_NORM_ID


@pytest.mark.parametrize("field", ["kind", "title", "informal", "minted_by"])
def test_every_human_owned_field_is_null(field: str) -> None:
    """`null`, never `"TODO: …"`.

    A placeholder STRING validates against `registry/1.0` — `title` asks only
    for a non-empty string — so a fragment pasted and forgotten would pass
    `mfc registry validate` and carry the word TODO into a published record.
    `null` fails at the first gate the topic repo runs, which is the entire
    reason this output is deliberately invalid.
    """
    assert _entry()[field] is None


def test_the_checklist_names_every_field_left_null() -> None:
    """A null with no explanation is a bug report from the tool to the user."""
    entry = _entry()
    named = {item.split(" ")[0] for item in HUMAN_OWNED}
    assert named == {k for k, v in entry.items() if v is None} - {
        "supersedes", "superseded_by", "mint_unresolved_reason",
    }


def test_mint_resolution_records_the_rung_it_actually_is() -> None:
    """`quote` IS this chunk's body, so `quote_sha256` matches by
    construction. Recorded rather than left null so the resolver's rung 1 has
    a hint to try first — and the resolver still recomputes before accepting
    it, which is what makes a stale hint harmless."""
    resolution = _entry()["mint_resolution"]
    assert resolution["matched_by"] == "quote_sha256"
    assert resolution["chunk_id"] == f"arxiv:{PAPER}:1111111111111111"
    assert resolution["notebook"] == "bridgeland-stability"
    assert resolution["corpus_version"] == 5048
    assert _entry()["mint_unresolved_reason"] is None


def test_no_manifest_hash_means_no_mint_resolution_and_a_stated_reason() -> None:
    """An adopter with no arXMCP running still mints — the schema makes
    `mint_resolution` nullable *with a reason* for exactly that case.

    What it must never do is stamp a resolution carrying a manifest hash
    nobody computed: the topic repo's F-02 freshness rule compares that field
    to decide whether the corpus has moved, and a fabricated value reads as
    "it has not".
    """
    entry = _entry(corpus_manifest_content_hash="")
    assert entry["mint_resolution"] is None
    assert "no mint-time resolution" in entry["mint_unresolved_reason"]


def test_the_printed_number_rides_as_a_typed_field_not_in_a_key() -> None:
    """ADR-0002: the paper coordinate is typed fields, never key segments.
    Three of the four candidate designs packed it into the key and survived
    `math/0212237` only by luck."""
    source = _entry()["source"]
    assert source == {
        "scheme": "arxiv", "id": PAPER, "version": "v3",
        "printed_number": "8.2", "locator": None,
    }


def test_a_textbook_source_carries_no_version() -> None:
    """The registry schema makes a version on a textbook source a category
    error — there is no version axis to pin."""
    entry = build_entry(
        Chunk(chunk_id="textbook:huybrechts-fm:0f0f0f0f0f0f0f0f",
              paper_id="textbook:huybrechts-fm", body_text=BODY_82),
        scheme="textbook", work_id="huybrechts-fm", source_version=None,
        notebook="huybrechts", corpus_version=1,
        corpus_manifest_content_hash="1" * 64,
        quote_sha256=mfc_digest.quote_sha256,
    )
    assert entry["source"]["version"] is None
    assert entry["source"]["scheme"] == "textbook"


def test_an_unknown_arxiv_version_stays_null_rather_than_becoming_latest() -> None:
    """`documents.arxiv_version` is `''` for every row today. Filling `v1`, or
    today's latest, would be the fabrication #171 is about — and the schema
    REQUIRES a version on an arXiv source, so a null here is a hard stop
    rather than a soft omission."""
    assert _entry(source_version=None)["source"]["version"] is None


def _schema() -> dict:
    import mfc

    return json.loads(
        (Path(mfc.__file__).resolve().parent / "schema"
         / "registry-1.0.schema.json").read_text(encoding="utf-8")
    )


def _document(entry: dict) -> dict:
    """A whole `registry/1.0` file around one entry.

    The entry subschema is validated in context rather than on its own: its
    `source` / `mintResolution` / `citationKey` members are `$ref`s into the
    file's `$defs`, and pulling the subschema out leaves them pointing at
    nothing.
    """
    return {
        "schema_version": "registry/1.0",
        "registry_id": "a520a8d4f877",
        "notebook_hint": "bridgeland-stability",
        "entries": {"stmt:a520a8d4f877:bridgeland2007.lem-8.2": entry},
    }


def test_the_fragment_carries_exactly_the_registry_entry_keys() -> None:
    """`additionalProperties: false`. A key this tool invents is rejected by
    the topic repo, and the operator has no way to know which one."""
    schema = _schema()
    allowed = set(schema["$defs"]["entry"]["properties"])
    required = set(schema["$defs"]["entry"]["required"])
    produced = set(_entry())
    assert produced <= allowed, f"invented key(s): {sorted(produced - allowed)}"
    assert required <= produced, f"missing required: {sorted(required - produced)}"


def test_filling_the_human_fields_makes_the_fragment_valid() -> None:
    """The deliberate invalidity must be EXACTLY the human's four fields.

    Without this, a structural mistake anywhere else in the fragment would
    hide behind "it is supposed to fail validation" and only surface when
    someone had already filled the prose in by hand.
    """
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(_schema())

    entry = _entry()
    errors = list(validator.iter_errors(_document(entry)))
    assert errors, "the fragment must NOT validate before a human fills it in"
    #: And it must fail for the RIGHT reason. Without this the test passes on
    #: any malformed fragment, which is the failure it exists to catch.
    assert {tuple(e.path)[-1] for e in errors} == {
        "kind", "title", "informal", "minted_by"}

    entry.update(kind="lemma", title="A bound on the slicing map",
                 informal="Nearby stability conditions induce a well-defined "
                          "map on slicings.", minted_by="Chris Dare")
    errors = sorted(validator.iter_errors(_document(entry)),
                    key=lambda e: list(e.path))
    assert not errors, f"{errors[0].json_path}: {errors[0].message}"


def test_a_filled_fragment_passes_the_registry_rules_end_to_end() -> None:
    """Schema-valid is not rule-valid. `mfc registry validate` runs R-01..R-13
    over the whole file, and R-02 (`quote_sha256` recomputes from the inline
    quote) is the one this tool could plausibly get wrong."""
    pytest.importorskip("jsonschema")
    from mfc.rules_registry import check as registry_check

    entry = _entry()
    entry.update(kind="lemma", title="A bound on the slicing map",
                 informal="Nearby stability conditions induce a map.",
                 minted_by="Chris Dare")
    results = registry_check(_document(entry))
    failed = [r for r in results if r.status.name == "FAIL"]
    assert not failed, [(r.rule, r.findings) for r in failed]
    #: R-02 is the rule this tool could plausibly break, so assert it ran
    #: rather than trusting an empty failure list over a vacuous sweep.
    assert any(r.rule == "R-02" and r.status.name == "PASS" for r in results)
