"""The single test that proves the identifier scheme works.

derived-alg-geo-lean **#170**. The claim under test is the one the whole
contract rests on: a citation key minted by hand in a topic repo keeps
addressing the same statement after the corpus is re-ingested and every
``chunk_id`` rotates. If that is false, ``registry/<slug>.json`` is a set of
dangling pointers with a schema.

So this file does not check that the resolver runs. It rotates the corpus and
checks that identity survived the rotation — and, just as importantly, that a
statement genuinely REMOVED from the corpus comes back ``unresolvable`` rather
than pointed at the nearest surviving chunk. A resolver that reported
``current`` for everything would pass a "does it resolve" test and be worse
than useless.

Per #151 the rotation is not a whitespace mutation. ``nfc-ws-collapse/1``
absorbs whitespace by construction, so a test built on it proves the
normalization works and says nothing about the ladder. The rotation here
**merges** two chunks into one and **splits** a third, which is what a real
chunker bump does and what the ``quote_containment`` rung was added for.

Deliberately cheap: no LanceDB, no Lean, no models, no network. The fixture is
four dicts. That is what lets it be this repo's first CI job.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools._statement_common import (
    Chunk,
    corpus_paper_id,
    read_document_versions,
)
from tools.statement_resolve import RESOLVER_VERSION, resolve

mfc_digest = pytest.importorskip(
    "mfc.digest",
    reason=(
        "the contract package is not installed; `pip install -e '.[contract]'`. "
        "It is not vendored on purpose — see tools/_statement_common.py"
    ),
)

PAPER = "math/0212237"
REGISTRY_ID = "a520a8d4f877"

#: The statement text of Definition 1.1, standing alone as one chunk.
DEF_11 = (
    "Definition 1.1. A stability condition $(Z,\\mathcal{P})$ on a "
    "triangulated category $\\mathcal{D}$ consists of a group homomorphism "
    "$Z\\colon K(\\mathcal{D})\\to\\mathbb{C}$ called the central charge, and "
    "full additive subcategories $\\mathcal{P}(\\phi)$."
)

#: Lemma 8.2, standing alone. Merged with the chunk after it in the rotation.
LEM_82 = (
    "Lemma 8.2. Let $\\sigma=(Z,\\mathcal{P})$ be a stability condition and "
    "suppose $\\|\\sigma_1-\\sigma_2\\|<1/8$. Then the map on slicings is "
    "well-defined."
)

#: The chunk that FOLLOWS Lemma 8.2 and gets merged into it.
LEM_82_NEXT = (
    "The proof proceeds by induction on the length of the Harder-Narasimhan "
    "filtration, using axiom (d) of Definition 1.1."
)

#: Proposition 8.1's STATEMENT. The mint took the statement; the chunk it came
#: from carried statement + proof, so this entry resolves by containment even
#: before any rotation. The rotation then splits that chunk in two.
PROP_81_STMT = (
    "Proposition 8.1. The map $\\mathcal{Z}\\colon\\operatorname{Stab}"
    "(\\mathcal{D})\\to\\operatorname{Hom}(K(\\mathcal{D}),\\mathbb{C})$ is a "
    "local homeomorphism."
)
PROP_81_PROOF = (
    "Proof. Fix a stability condition and apply Lemma 8.2 to the pair of "
    "slicings obtained from the deformation. $\\square$"
)

#: An obligation whose text is in no chunk, before or after the rotation. The
#: control: whatever the ladder does to the other three, this one must come
#: back unresolvable.
REMOVED = (
    "Lemma 9.9. Every stability condition on a K3 surface is induced by a "
    "Bridgeland pair, which no version of this paper ever claimed."
)


def _entry(
    *,
    quote: str,
    kind: str = "lemma",
    printed_number: str | None = None,
    version: str | None = "v3",
    scheme: str = "arxiv",
    ident: str = PAPER,
    mint_chunk_id: str | None = None,
) -> dict:
    return {
        "kind": kind,
        "title": "fixture entry",
        "informal": "fixture",
        "source": {
            "scheme": scheme,
            "id": ident,
            "version": version,
            "printed_number": printed_number,
            "locator": None,
        },
        "quote_mode": "verbatim",
        "quote": quote,
        "quote_norm": "nfc-ws-collapse/1",
        "quote_sha256": mfc_digest.quote_sha256(quote),
        "mint_resolution": (
            None if mint_chunk_id is None else {
                "notebook": "bridgeland-stability",
                "chunk_id": mint_chunk_id,
                "matched_by": "quote_sha256",
                "corpus_manifest_content_hash": "1" * 64,
                "observed_at": "2026-08-05T09:00:00Z",
            }
        ),
        "depends_on": [],
        "frontier": [],
        "minted_at": "2026-08-05",
        "minted_by": "fixture",
        "supersedes": None,
        "superseded_by": None,
        "mint_unresolved_reason": None if mint_chunk_id else "no resolver yet",
    }


def _key(label: str) -> str:
    return f"stmt:{REGISTRY_ID}:bridgeland2007.{label}"


K_DEF = _key("def-1.1")
K_LEM = _key("lem-8.2")
K_PROP = _key("prop-8.1")
K_GONE = _key("obl-removed")


def _registry() -> dict:
    return {
        "schema_version": "registry/1.0",
        "registry_id": REGISTRY_ID,
        "notebook_hint": "bridgeland-stability",
        "entries": {
            K_DEF: _entry(quote=DEF_11, kind="definition", printed_number="1.1",
                          mint_chunk_id=f"arxiv:{PAPER}:aaaaaaaaaaaaaaaa"),
            K_LEM: _entry(quote=LEM_82, printed_number="8.2",
                          mint_chunk_id=f"arxiv:{PAPER}:bbbbbbbbbbbbbbbb"),
            K_PROP: _entry(quote=PROP_81_STMT, kind="proposition",
                           printed_number="8.1"),
            K_GONE: _entry(quote=REMOVED, kind="obligation", printed_number=None),
        },
    }


def _chunk(suffix: str, body: str, printed: str | None = None) -> Chunk:
    return Chunk(
        chunk_id=f"arxiv:{PAPER}:{suffix}",
        paper_id=PAPER,
        body_text=body,
        printed_number=printed,
        kind="theorem",
        chunker_version="v1.1",
    )


def _corpus_as_minted() -> list[Chunk]:
    """Four chunks, with the ids the registry's mint_resolutions name."""
    return [
        _chunk("aaaaaaaaaaaaaaaa", DEF_11, "1.1"),
        _chunk("bbbbbbbbbbbbbbbb", LEM_82, "8.2"),
        _chunk("cccccccccccccccc", LEM_82_NEXT, None),
        _chunk("dddddddddddddddd", f"{PROP_81_STMT}\n\n{PROP_81_PROOF}", "8.1"),
    ]


def _corpus_rotated() -> list[Chunk]:
    """The same paper after a chunker bump. Every id is different.

    Three distinct mutations, none of them cosmetic:

    * ``A`` keeps its body and loses its id — the plain rotation.
    * ``B`` and ``C`` are MERGED. Lemma 8.2's quote is no longer any chunk's
      whole body, so byte-equality is gone and only containment can find it.
    * ``D`` is SPLIT at the statement/proof boundary. Proposition 8.1's quote
      resolved by containment before the rotation and by byte-equality after
      it, which is the direction a split moves the evidence.
    """
    return [
        _chunk("1111111111111111", DEF_11, "1.1"),
        _chunk("2222222222222222", f"{LEM_82}\n\n{LEM_82_NEXT}", "8.2"),
        _chunk("3333333333333333", PROP_81_STMT, "8.1"),
        _chunk("4444444444444444", PROP_81_PROOF, None),
    ]


def _resolve(chunks, *, versions=None, registry=None) -> dict:
    return resolve(
        registry or _registry(),
        chunks,
        notebook="bridgeland-stability",
        registry_sha256="e" * 64,
        corpus_version=5048,
        corpus_manifest_content_hash="1" * 64,
        chunker_version="v1.1",
        document_versions={PAPER: "v3"} if versions is None else versions,
        generated_at="2026-09-03T12:00:00Z",
        norm_text=mfc_digest.norm_text,
    )


def _by_key(document: dict) -> dict[str, dict]:
    return {r["key"]: r for r in document["results"]}


# --- the rotation, which is the whole point ----------------------------------

def test_every_entry_resolves_before_the_rotation() -> None:
    """The baseline. Without it a green rotation test proves nothing.

    Note `prop-8.1` is already on the containment rung here: the mint took
    Proposition 8.1's statement and the chunk it sat in carried the proof too.
    That is the ordinary case, not a degraded one.
    """
    rows = _by_key(_resolve(_corpus_as_minted()))
    assert rows[K_DEF]["resolution"] == "current"
    assert rows[K_DEF]["matched_by"] == "quote_sha256"
    assert rows[K_LEM]["resolution"] == "current"
    assert rows[K_LEM]["matched_by"] == "quote_sha256"
    assert rows[K_PROP]["resolution"] == "current"
    assert rows[K_PROP]["matched_by"] == "quote_containment"
    assert rows[K_GONE]["resolution"] == "unresolvable"


def test_identity_survives_a_rotation_of_every_chunk_id() -> None:
    """No chunk_id in the rotated corpus appears in the registry, and every
    minted statement still resolves ``current``.

    This is the claim `stmt:<12hex>:<label>` exists to make. The key carries no
    corpus-derived bytes, so a re-ingest that rotates every id cannot touch it;
    what has to be shown is that the RESOLVER can still find the statement the
    key names once the cache hint it was minted with is dead.
    """
    rotated = _corpus_rotated()
    minted_ids = {
        e["mint_resolution"]["chunk_id"]
        for e in _registry()["entries"].values()
        if e["mint_resolution"]
    }
    assert minted_ids and not (minted_ids & {c.chunk_id for c in rotated}), (
        "the fixture must rotate every id it minted against, or the test is "
        "asserting nothing"
    )

    rows = _by_key(_resolve(rotated))
    assert rows[K_DEF]["resolution"] == "current"
    assert rows[K_LEM]["resolution"] == "current"
    assert rows[K_PROP]["resolution"] == "current"


def test_the_merge_is_survived_by_containment_and_nothing_weaker() -> None:
    """Lemma 8.2's chunk was merged with the one after it.

    Byte-equality is genuinely gone — the quote is no chunk's whole body any
    more — so this is the rung #151 added, doing the job it was added for. It
    reads `current` because containment is an identity claim: the statement is
    in the chunk or it is not.
    """
    row = _by_key(_resolve(_corpus_rotated()))[K_LEM]
    assert row["resolution"] == "current"
    assert row["matched_by"] == "quote_containment"
    assert row["chunk_id"] == f"arxiv:{PAPER}:2222222222222222"
    #: The schema forbids a similarity score here, and so does the design:
    #: a number beside a containment match invites the reading that it was a
    #: near-miss.
    assert row["similarity"] is None


def test_the_split_moves_the_evidence_up_the_ladder_not_down() -> None:
    """Proposition 8.1's chunk was split at the statement/proof boundary.

    Before the split the quote was a proper substring of a statement+proof
    chunk (containment). After it, the statement IS a chunk, so the match is
    byte-equal. A split that isolates the statement can only make the evidence
    stronger, and this pins that it does.
    """
    before = _by_key(_resolve(_corpus_as_minted()))[K_PROP]
    after = _by_key(_resolve(_corpus_rotated()))[K_PROP]
    assert before["matched_by"] == "quote_containment"
    assert after["matched_by"] == "quote_sha256"
    assert after["resolution"] == "current"


def test_a_removed_statement_is_unresolvable_and_never_a_wrong_match() -> None:
    """The control, and the failure this whole design is built to avoid.

    A resolver that reached for the nearest surviving chunk would silently
    re-point a citation at a different theorem, and every other assertion in
    this file would still pass. So: no chunk_id, no digest, no printed_number,
    and `matched_by: none`.
    """
    for chunks in (_corpus_as_minted(), _corpus_rotated()):
        row = _by_key(_resolve(chunks))[K_GONE]
        assert row["resolution"] == "unresolvable"
        assert row["matched_by"] == "none"
        assert row["chunk_id"] is None
        assert row["matched_body_sha256"] is None
        assert row["similarity"] is None
        assert row["reason"]


def test_no_result_is_ever_matched_by_fuzzy() -> None:
    """There is no nearest-neighbour rung, and there is not meant to be.

    The schema permits `fuzzy` and forbids it from reading `current`. This
    resolver does not implement it at all: the only thing a similarity score
    could add to this artifact is a number that invites the reading the schema
    spent a conditional forbidding.
    """
    for chunks in (_corpus_as_minted(), _corpus_rotated(), []):
        document = _resolve(chunks)
        assert all(r["matched_by"] != "fuzzy" for r in document["results"])
        assert all(r["similarity"] is None for r in document["results"])


# --- the version guard (#171's condition, living here per #170) ---------------

def test_an_empty_arxiv_version_yields_not_applicable_never_current() -> None:
    """`documents.arxiv_version == ''` is every row in both live notebooks.

    `notebook_fetch` pulls ar5iv for the bare id — arXiv LATEST — so a
    byte-equal match written up as `current` for an entry declaring `v3`
    asserts a v3 pin confirmed by bytes of unknown version. The guard is
    unconditional on #171's backfill: a row that still reads `''` afterwards
    is exactly a row whose version could not be established.
    """
    rows = _by_key(_resolve(_corpus_rotated(), versions={PAPER: ""}))
    for key in (K_DEF, K_LEM, K_PROP):
        assert rows[key]["resolution"] == "not_applicable", key
        assert rows[key]["resolved_source_version"] is None
        assert "unknown version" in rows[key]["reason"]
    #: Withheld, not erased: the evidence that a match WAS found stays on the
    #: record, so the operator can see the guard is what withheld it.
    assert rows[K_DEF]["chunk_id"]
    assert rows[K_DEF]["matched_body_sha256"]
    #: And a statement that is genuinely gone is still unresolvable — the
    #: guard downgrades a pass, it does not upgrade a failure.
    assert rows[K_GONE]["resolution"] == "unresolvable"


def test_a_work_missing_from_documents_db_is_treated_as_unversioned() -> None:
    """An absent row and an empty column are the same fact for this purpose.

    Both mean the corpus cannot name the version it holds. They differ in
    remedy, not in what may be claimed, so neither may read `current`.
    """
    rows = _by_key(_resolve(_corpus_rotated(), versions={}))
    assert rows[K_DEF]["resolution"] == "not_applicable"


def test_a_corpus_holding_a_different_version_cannot_confirm_the_pin() -> None:
    """The guard fires in both directions.

    Once #171 lands and the corpus can say `v4`, an entry pinning `v3` is not
    thereby confirmed — a match against a different revision is not evidence
    for the pinned one, even when the statement is unchanged between them.
    """
    rows = _by_key(_resolve(_corpus_rotated(), versions={PAPER: "v4"}))
    assert rows[K_DEF]["resolution"] == "not_applicable"
    assert "v4" in rows[K_DEF]["reason"] and "v3" in rows[K_DEF]["reason"]


def test_a_matching_version_is_what_finally_permits_current() -> None:
    """The guard is a guard, not a blanket refusal.

    Asserted so a future change that hard-wires `not_applicable` — which would
    pass every other test in this section — fails here.
    """
    rows = _by_key(_resolve(_corpus_rotated(), versions={PAPER: "v3"}))
    assert rows[K_DEF]["resolution"] == "current"
    assert rows[K_DEF]["resolved_source_version"] == "v3"


def test_an_unversioned_source_is_not_caught_by_the_guard() -> None:
    """A `textbook:` source has no version axis; there is nothing to confirm.

    The registry schema makes a version on a textbook source a category error,
    so a guard that fired here would make the whole scheme unresolvable for
    the two live textbook notebooks.
    """
    registry = _registry()
    registry["entries"] = {
        K_DEF: _entry(quote=DEF_11, kind="definition", scheme="textbook",
                      ident="huybrechts-fm", version=None),
    }
    chunks = [Chunk(chunk_id="textbook:huybrechts-fm:0f0f0f0f0f0f0f0f",
                    paper_id="textbook:huybrechts-fm", body_text=DEF_11)]
    rows = _by_key(_resolve(chunks, versions={}, registry=registry))
    assert rows[K_DEF]["resolution"] == "current"


# --- the rungs that are not `current` ----------------------------------------

def test_a_paper_that_was_never_ingested_is_paper_absent_not_unresolvable() -> None:
    """Different facts, and the remedies differ.

    `unresolvable` says we looked through this paper's chunks and the
    statement is not among them. `paper_absent` says there were no chunks to
    look through. Collapsing them would report an un-ingested notebook as a
    corpus that had lost the statement.
    """
    rows = _by_key(_resolve([]))
    assert {r["resolution"] for r in rows.values()} == {"paper_absent"}
    assert all(r["matched_by"] == "none" for r in rows.values())


def test_printed_number_is_a_hint_and_can_only_read_drifted() -> None:
    """Authors renumber between versions, so the number is never an identity.

    The chunk here still carries `8.2` and no longer carries the quote. The
    schema forces this rung to `drifted`; the resolver must not be the thing
    that keeps it honest, but it must not fight it either.
    """
    chunks = [_chunk("9999999999999999", "Entirely different text.", "8.2")]
    rows = _by_key(_resolve(chunks))
    assert rows[K_LEM]["resolution"] == "drifted"
    assert rows[K_LEM]["matched_by"] == "printed_number"
    assert rows[K_LEM]["printed_number"] == "8.2"


def test_a_source_scheme_with_no_corpus_coordinate_is_not_run() -> None:
    """A `doi:` entry is legal in the registry and is not a thing this corpus
    indexes. `not_run` says we did not look; `unresolvable` would say we looked
    and it is gone, which is a claim nobody made."""
    registry = _registry()
    registry["entries"] = {
        K_DEF: _entry(quote=DEF_11, scheme="doi", ident="10.1007/x", version=None),
    }
    rows = _by_key(_resolve(_corpus_as_minted(), registry=registry))
    assert rows[K_DEF]["resolution"] == "not_run"
    assert rows[K_DEF]["matched_by"] == "none"
    assert "doi" in rows[K_DEF]["reason"]


def test_an_entry_with_neither_quote_nor_digest_is_not_run() -> None:
    """Obligations are minted with no quote — they name work, not text."""
    registry = _registry()
    entry = _entry(quote=REMOVED, kind="obligation")
    entry["quote"], entry["quote_sha256"] = None, None
    registry["entries"] = {K_GONE: entry}
    rows = _by_key(_resolve(_corpus_as_minted(), registry=registry))
    assert rows[K_GONE]["resolution"] == "not_run"


# --- the mint hint is a hint --------------------------------------------------

def test_a_stale_mint_chunk_id_is_never_accepted_without_recomputing() -> None:
    """The id still exists and now addresses a DIFFERENT statement.

    `merge_insert` has no delete arm, so a rotated-away id can be re-used by
    whatever the new chunker put there. Rung 1 must therefore recompute the
    body digest and reject on mismatch — accepting the hint on its own would
    turn a stale cache entry into a confident wrong answer, which is strictly
    worse than a cache miss.
    """
    poisoned = [
        _chunk("aaaaaaaaaaaaaaaa", "Some other paper's Lemma 4.4.", "4.4"),
        _chunk("7777777777777777", DEF_11, "1.1"),
    ]
    row = _by_key(_resolve(poisoned))[K_DEF]
    assert row["resolution"] == "current"
    assert row["chunk_id"] == f"arxiv:{PAPER}:7777777777777777"
    assert "rotated" in (row["reason"] or "")


def test_a_mint_hint_from_another_notebook_is_ignored() -> None:
    """`chunk_id` is only unique within a notebook's table.

    Honouring a hint minted against a different notebook would read a
    same-shaped id out of the wrong corpus.
    """
    registry = _registry()
    registry["entries"][K_DEF]["mint_resolution"]["notebook"] = "shimura-varieties"
    rows = _by_key(_resolve(_corpus_as_minted(), registry=registry))
    assert rows[K_DEF]["resolution"] == "current"
    assert rows[K_DEF]["reason"], "a scan that bypassed the hint must say so"


# --- the artifact ------------------------------------------------------------

def test_the_document_validates_against_resolution_1_0() -> None:
    """Every cross-field rule in the schema, over real resolver output.

    The fixtures in `math-formal-contract-lean` prove the schema accepts a
    hand-written instance. This proves it accepts THIS producer's, which is a
    different claim and the one that breaks first.
    """
    jsonschema = pytest.importorskip("jsonschema")
    import mfc

    schema = json.loads(
        (Path(mfc.__file__).resolve().parent / "schema"
         / "resolution-1.0.schema.json").read_text(encoding="utf-8")
    )
    for chunks, versions in (
        (_corpus_as_minted(), {PAPER: "v3"}),
        (_corpus_rotated(), {PAPER: "v3"}),
        (_corpus_rotated(), {PAPER: ""}),
        (_corpus_rotated(), {PAPER: "v4"}),
        ([], {}),
    ):
        document = _resolve(chunks, versions=versions)
        errors = sorted(
            jsonschema.Draft202012Validator(schema).iter_errors(document),
            key=lambda e: list(e.path),
        )
        assert not errors, f"{errors[0].json_path}: {errors[0].message}"


def test_counts_agree_with_the_results_they_summarise() -> None:
    """A summary that can disagree with its own rows is worse than none."""
    document = _resolve(_corpus_rotated(), versions={PAPER: ""})
    for state, n in document["counts"].items():
        assert n == sum(1 for r in document["results"]
                        if r["resolution"] == state), state
    assert sum(document["counts"].values()) == len(document["results"])


def test_two_runs_over_one_corpus_are_byte_identical() -> None:
    """The operator commits this file. A resolution whose row order depended
    on Arrow fragment layout would show a diff on every re-run and teach them
    to stop reading diffs."""
    a = json.dumps(_resolve(_corpus_rotated()), indent=2)
    b = json.dumps(_resolve(list(reversed(_corpus_rotated()))), indent=2)
    assert a == b


def test_the_header_records_what_produced_this_answer() -> None:
    document = _resolve(_corpus_rotated())
    assert document["schema_version"] == "resolution/1.0"
    assert document["resolver_version"] == RESOLVER_VERSION
    assert document["notebook"] == "bridgeland-stability"
    assert document["registry_sha256"] == "e" * 64


def test_the_registry_is_not_mutated_by_resolving_it() -> None:
    """It is the topic repo's file; this tool has no business writing to it,
    in memory or on disk."""
    registry = _registry()
    before = copy.deepcopy(registry)
    _resolve(_corpus_rotated(), registry=registry)
    assert registry == before


# --- the helpers the CLI leans on --------------------------------------------

@pytest.mark.parametrize("source,expected", [
    ({"scheme": "arxiv", "id": PAPER, "version": "v3"}, PAPER),
    ({"scheme": "arxiv", "id": "2101.04404", "version": "v2"}, "2101.04404"),
    ({"scheme": "textbook", "id": "huybrechts-fm", "version": None},
     "textbook:huybrechts-fm"),
    ({"scheme": "doi", "id": "10.1007/x", "version": None}, None),
    ({"scheme": "url", "id": "https://x.invalid", "version": None}, None),
    ({"scheme": "arxiv", "id": "", "version": "v1"}, None),
])
def test_corpus_paper_id_never_appends_the_version(source, expected) -> None:
    """`paper_id` in the chunks table is the bare id; the version lives in
    `documents.arxiv_version`. Appending it would miss every row."""
    assert corpus_paper_id(source) == expected


def test_read_document_versions_prefers_a_concrete_version_over_empty(
    tmp_path: Path,
) -> None:
    """PRIMARY KEY is `(work_id, arxiv_version)`, so one work can carry both an
    unversioned row and a versioned one. If ANY row names a version, the corpus
    knows one, and the guard must see it."""
    import sqlite3

    db = tmp_path / "documents.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE documents (work_id TEXT, arxiv_version TEXT, "
        "PRIMARY KEY (work_id, arxiv_version))"
    )
    conn.executemany(
        "INSERT INTO documents VALUES (?, ?)",
        [(PAPER, ""), (PAPER, "v3"), ("2101.04404", "")],
    )
    conn.commit()
    conn.close()
    versions = read_document_versions(db)
    assert versions[PAPER] == "v3"
    assert versions["2101.04404"] == ""


def test_read_document_versions_does_not_create_a_missing_db(
    tmp_path: Path,
) -> None:
    """`DocumentsStore.open` would create the file. "This notebook was never
    backfilled" is a fact the resolver must be able to observe rather than
    erase — and a read command that leaves a new file behind is a surprise."""
    db = tmp_path / "documents.db"
    assert read_document_versions(db) == {}
    assert not db.exists()
