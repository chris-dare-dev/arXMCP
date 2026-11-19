"""Interface tests for ``ingest.chunk`` (chunk-module-m1).

Everything here goes through the module's interface: the record and its
row mapping, chunk ids, the route, the embedding input and the reuse
identity (ADR ``.claude/docs/adr-chunk-identity-and-reuse.md`` rules 2
and 3). ``TestLanceDBRoundTrip`` takes records through a real temporary
LanceDB table and back.
"""

from __future__ import annotations

import ast
import hashlib
import sys
import unicodedata
from dataclasses import fields
from pathlib import Path

import lancedb
import numpy as np
import pytest

from ingest.chunk import (
    ALLOWED_KINDS,
    CHUNKER_VERSION,
    CHUNKS_SCHEMA_V1,
    EMBED_INPUT_POLICY_VERSION,
    EMBEDDING_DIM,
    LEGACY_EMBED_INPUT_POLICY_VERSION,
    ChunkRecord,
    _compute_chunk_id,
    _compute_textbook_chunk_id,
    embedding_input,
    from_row,
    reusable_vectors,
    reuse_identity,
    route,
    stored_reuse_identity,
    stored_vector,
    to_arrow_table,
    to_row,
)

EMBEDDER = "bge-m3@aaaaaaaa"
CHUNK_PY = Path(__file__).resolve().parent.parent / "ingest" / "chunk.py"


def _vector(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _record(**overrides) -> ChunkRecord:
    values = dict(
        chunk_id="arxiv:2401.00001:" + "a" * 16,
        paper_id="2401.00001",
        kind="stmt",
        section_path=["1. Intro"],
        theorem_name=None,
        theorem_label="thm:main",
        body_text="Let X be a scheme.",
        body_tokens="let x be a scheme",
    )
    values.update(overrides)
    return ChunkRecord(**values)


def _row(record: ChunkRecord, seed: int = 0, **kwargs) -> dict:
    return to_row(
        record,
        _vector(seed).tolist(),
        embedder_version=kwargs.get("embedder_version", EMBEDDER),
        policy=kwargs.get("policy", EMBED_INPUT_POLICY_VERSION),
    )


# ---------------------------------------------------------------------------
# The module boundary
# ---------------------------------------------------------------------------


class TestImportBoundary:
    def test_imports_only_stdlib_and_pyarrow(self):
        # chunk.py is the leaf every other ingest module depends on; an
        # ingest (or numpy, lancedb, server) import here would reopen the
        # embedder -> chunker -> chunk cycle.
        tree = ast.parse(CHUNK_PY.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    roots.add("." * node.level)
                elif node.module:
                    roots.add(node.module.split(".")[0])
        allowed = set(sys.stdlib_module_names) | {"__future__", "pyarrow"}
        assert roots - allowed == set(), f"non-stdlib imports: {sorted(roots - allowed)}"

    def test_callers_see_the_same_objects(self):
        # The modules that used to own these facts re-export them; none
        # keeps its own copy.
        import ingest.chunker
        import ingest.embedder
        import ingest.schema
        import ingest.store

        assert ingest.chunker._compute_chunk_id is _compute_chunk_id
        assert ingest.chunker.ChunkRecord is ChunkRecord
        assert ingest.schema.CHUNKS_SCHEMA_V1 is CHUNKS_SCHEMA_V1
        assert ingest.embedder.EXPECTED_CHUNKER_VERSION is CHUNKER_VERSION
        assert ingest.embedder.EMBED_INPUT_POLICY_VERSION is EMBED_INPUT_POLICY_VERSION
        assert ingest.embedder.EMBEDDING_DIM == EMBEDDING_DIM
        assert ingest.store.ALLOWED_KINDS is ALLOWED_KINDS

    def test_chunker_types_is_gone(self):
        assert not (CHUNK_PY.parent / "chunker_types.py").exists()


# ---------------------------------------------------------------------------
# Chunk ids
# ---------------------------------------------------------------------------


class TestChunkIds:
    def test_arxiv_id_hashes_prefix_plus_nfc_body(self):
        body = "Let étale X be a scheme."  # NFD é
        expected = hashlib.sha256(
            ("PRE" + unicodedata.normalize("NFC", body)).encode("utf-8")
        ).hexdigest()[:16]
        assert _compute_chunk_id("2401.00001", "PRE", body) == (
            f"arxiv:2401.00001:{expected}"
        )

    def test_prefix_is_hashed_raw_and_without_a_separator(self):
        # NFC(prefix + body) differs from prefix + NFC(body) when the body
        # starts with a combining mark (UAX #15 §1.4); the id keeps the
        # latter, and a separator would rotate every id.
        body = "́ rest"
        raw = hashlib.sha256(
            ("e" + unicodedata.normalize("NFC", body)).encode("utf-8")
        ).hexdigest()[:16]
        assert _compute_chunk_id("2401.00001", "e", body).endswith(raw)
        assert _compute_chunk_id("2401.00001", "e", body) != _compute_chunk_id(
            "2401.00001", "", "e" + body
        )

    def test_textbook_id_uses_the_same_digest_with_its_prefix(self):
        arxiv = _compute_chunk_id("x", "\x00".join(["Ch 1", "1.2"]), "body")
        textbook = _compute_textbook_chunk_id("ko95", "\x00".join(["Ch 1", "1.2"]), "body")
        assert textbook == "textbook:ko95:" + arxiv.rsplit(":", 1)[-1]


# ---------------------------------------------------------------------------
# Route and embedding input
# ---------------------------------------------------------------------------


class TestRouteAndInput:
    @pytest.mark.parametrize(
        ("kind", "expected"),
        [("proof", "proof"), ("stmt", "stmt"), ("section", "stmt"),
         ("definition", "stmt"), ("lemma", "stmt"), (None, "stmt")],
    )
    def test_route(self, kind, expected):
        assert route(kind) == expected

    def test_embedding_input_is_the_nfc_body(self):
        body_nfd = "café"
        assert embedding_input(body_nfd) == "café"
        assert embedding_input("Theorem 1.") == "Theorem 1."

    def test_policy_versions(self):
        assert EMBED_INPUT_POLICY_VERSION == "body-first-v1"
        assert LEGACY_EMBED_INPUT_POLICY_VERSION != EMBED_INPUT_POLICY_VERSION


# ---------------------------------------------------------------------------
# Reuse identity (ADR rules 2 and 3)
# ---------------------------------------------------------------------------


class TestReuseIdentity:
    def test_is_a_full_sha256_hex_digest(self):
        identity = reuse_identity("stmt", "body", embedder_version=EMBEDDER)
        assert len(identity) == 64
        assert set(identity) <= set("0123456789abcdef")

    def test_matches_on_input_embedder_and_route(self):
        base = reuse_identity("stmt", "body", embedder_version=EMBEDDER)
        # Same route, other kind: same vector space, same identity.
        assert reuse_identity("section", "body", embedder_version=EMBEDDER) == base
        # NFC-equivalent bodies are the same embedding input.
        assert reuse_identity("stmt", "café", embedder_version=EMBEDDER) == (
            reuse_identity("stmt", "café", embedder_version=EMBEDDER)
        )
        assert reuse_identity("proof", "body", embedder_version=EMBEDDER) != base
        assert reuse_identity("stmt", "body.", embedder_version=EMBEDDER) != base
        assert reuse_identity("stmt", "body", embedder_version="bge-m3@bbbbbbbb") != base

    def test_needs_an_embedder_version(self):
        with pytest.raises(ValueError, match="embedder_version"):
            reuse_identity("stmt", "body", embedder_version="")

    def test_stored_row_identity_is_recomputed_from_the_row(self):
        record = _record()
        row = _row(record)
        assert stored_reuse_identity(row) == reuse_identity(
            record.kind, record.body_text, embedder_version=EMBEDDER
        )

    @pytest.mark.parametrize(
        "policy", [None, LEGACY_EMBED_INPUT_POLICY_VERSION, "some-future-v9"]
    )
    def test_a_row_whose_policy_cannot_be_recomputed_is_not_reusable(self, policy):
        row = _row(_record())
        row["embed_input_policy_version"] = policy
        assert stored_reuse_identity(row) is None

    def test_a_row_missing_an_identity_column_is_not_reusable(self):
        row = _row(_record())
        del row["body_text"]
        assert stored_reuse_identity(row) is None

    def test_stored_vector_reads_the_route_column_only(self):
        proof = _row(_record(kind="proof"), seed=3)
        assert stored_vector(proof) == _vector(3).tolist()
        # The 7b160a0 shape: a proof row whose vector sits in the
        # statement column has no vector on its own route.
        proof["embedding_stmt"], proof["embedding_proof"] = proof["embedding_proof"], None
        assert stored_vector(proof) is None

    def test_reusable_vectors_index_by_identity(self):
        a = _row(_record(chunk_id="arxiv:2401.00001:" + "b" * 16), seed=1)
        b = _row(_record(chunk_id="arxiv:2401.00001:" + "a" * 16), seed=2)
        legacy = _row(_record(body_text="other body"), seed=3)
        legacy["embed_input_policy_version"] = LEGACY_EMBED_INPUT_POLICY_VERSION
        index = reusable_vectors([a, b, legacy])
        identity = reuse_identity("stmt", "Let X be a scheme.", embedder_version=EMBEDDER)
        # Two rows share the identity: the lowest chunk id wins.
        assert index == {identity: _vector(2).tolist()}


# ---------------------------------------------------------------------------
# Record <-> row
# ---------------------------------------------------------------------------


class TestRowMapping:
    def test_every_record_field_is_a_column(self):
        record_fields = {f.name for f in fields(ChunkRecord)}
        assert record_fields <= set(CHUNKS_SCHEMA_V1.names)
        assert set(CHUNKS_SCHEMA_V1.names) - record_fields == {
            "embedding_stmt", "embedding_proof", "embedding_eq",
            "embedder_version", "embed_input_policy_version",
            "source_revision_id", "source_span", "license_ref",
        }

    def test_to_dict_keys_are_the_fields_sorted(self):
        # to_dict is the per-chunk JSON and the textbook golden fixture.
        record = _record(printed_number="3.1")
        assert list(record.to_dict()) == sorted(f.name for f in fields(ChunkRecord))
        assert record.to_dict()["chunker_version"] == CHUNKER_VERSION

    def test_to_row_places_the_vector_by_route(self):
        stmt = _row(_record(), seed=1)
        assert stmt["embedding_stmt"] == _vector(1).tolist()
        assert stmt["embedding_proof"] is None
        proof = _row(_record(kind="proof"), seed=2)
        assert proof["embedding_proof"] == _vector(2).tolist()
        assert proof["embedding_stmt"] is None
        for row in (stmt, proof):
            assert row["embedding_eq"] is None
            assert row["embedder_version"] == EMBEDDER
            assert row["embed_input_policy_version"] == EMBED_INPUT_POLICY_VERSION
            assert set(row) == set(CHUNKS_SCHEMA_V1.names)

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"truncated": True}, "truncated=true"),
            ({"body_tokens": None}, "body_tokens=None"),
            ({"kind": "theroem"}, "not in the allowed set"),
            ({"source_kind": "arxv"}, "source_kind"),
            ({"source_kind": "textbook"}, "prefix"),
            ({"parser_used": "latexm"}, "parser_used"),
        ],
    )
    def test_to_row_refuses_a_record_the_table_must_not_hold(self, overrides, message):
        with pytest.raises(ValueError, match=message):
            _row(_record(**overrides))

    def test_to_row_refuses_a_vector_of_the_wrong_width(self):
        with pytest.raises(ValueError, match="embedding_stmt vector has 3 values"):
            to_row(_record(), [0.0, 0.0, 1.0], embedder_version=EMBEDDER, policy="x")

    def test_to_arrow_table_names_a_missing_or_misspelled_column(self):
        row = _row(_record())
        row["embed_input_policy_versoin"] = row.pop("embed_input_policy_version")
        with pytest.raises(ValueError) as excinfo:
            to_arrow_table([row])
        assert "embed_input_policy_version" in str(excinfo.value)
        assert "embed_input_policy_versoin" in str(excinfo.value)

    def test_to_arrow_table_names_a_null_required_column(self):
        row = _row(_record())
        row["kind"] = None
        with pytest.raises(ValueError, match="column 'kind' is non-nullable"):
            to_arrow_table([row])

    def test_to_arrow_table_conforms_to_the_schema(self):
        table = to_arrow_table([_row(_record()), _row(_record(kind="proof"))])
        assert table.schema == CHUNKS_SCHEMA_V1
        assert to_arrow_table([]).schema == CHUNKS_SCHEMA_V1

    def test_from_row_inverts_to_row(self):
        record = _record(
            source_kind="textbook",
            chunk_id="textbook:ko95:" + "c" * 16,
            paper_id="textbook:ko95",
            license="author-distributed",
            chapter="Chapter 2",
            page_start=3,
            page_end=4,
            textbook_slug="ko95",
            parser_used="pdftotext",
            printed_number="2.2",
            part_index=2,
            part_count=3,
            source_start=10,
            source_end=28,
        )
        assert from_row(_row(record)) == record

    @pytest.mark.parametrize("column", ["truncated", "part_index", "body_text"])
    def test_from_row_refuses_null_in_a_required_field(self, column):
        row = _row(_record())
        row[column] = None
        with pytest.raises(ValueError, match=f"column '{column}' is NULL"):
            from_row(row)

    def test_from_row_keeps_optional_nulls(self):
        row = _row(_record(theorem_label=None, preamble_ref=None))
        assert from_row(row).theorem_label is None


# ---------------------------------------------------------------------------
# record -> row -> temporary LanceDB -> row -> record
# ---------------------------------------------------------------------------


class TestLanceDBRoundTrip:
    def test_records_survive_a_lancedb_table(self, tmp_path):
        from ingest.schema import EmbedRecord
        from ingest.store import write_chunks

        records = [
            _record(),
            _record(
                chunk_id="arxiv:2401.00001:" + "b" * 16,
                kind="proof",
                body_text="Proof. Cléar.",  # non-NFC bytes are stored as-is
                theorem_name="Riemann–Roch",
                printed_number="1.1",
                part_index=1,
                part_count=2,
                source_start=0,
                source_end=14,
            ),
            _record(
                chunk_id="textbook:ko95:" + "c" * 16,
                paper_id="textbook:ko95",
                kind="definition",
                section_path=[],
                source_kind="textbook",
                license="author-distributed",
                page_start=7,
                page_end=7,
                textbook_slug="ko95",
                parser_used="pdftotext",
            ),
        ]
        vectors = {r.chunk_id: _vector(i) for i, r in enumerate(records)}
        stmt = [r for r in records if route(r.kind) == "stmt"]
        proof = [r for r in records if route(r.kind) == "proof"]
        embeddings = EmbedRecord(
            chunk_ids_stmt=[r.chunk_id for r in stmt],
            embedding_stmt=np.stack([vectors[r.chunk_id] for r in stmt]),
            chunk_ids_proof=[r.chunk_id for r in proof],
            embedding_proof=np.stack([vectors[r.chunk_id] for r in proof]),
            embedder_version=EMBEDDER,
        )
        write_chunks(records, embeddings, lancedb_path=tmp_path, build_indices=False)

        table = lancedb.connect(str(tmp_path)).open_table("chunks")
        assert table.schema == CHUNKS_SCHEMA_V1
        # merge_insert does not keep row order: key the rows by chunk_id.
        rows = {row["chunk_id"]: row for row in table.to_arrow().to_pylist()}
        assert set(rows) == set(vectors)
        for record in records:
            row = rows[record.chunk_id]
            assert from_row(row) == record
            assert (
                np.asarray(stored_vector(row), dtype=np.float32).tobytes()
                == vectors[record.chunk_id].tobytes()
            )
            other = "embedding_stmt" if route(record.kind) == "proof" else "embedding_proof"
            assert row[other] is None
            # Rule 3: the identity recomputed from the stored row equals the
            # identity of the record that was written.
            assert stored_reuse_identity(row) == reuse_identity(
                record.kind, record.body_text, embedder_version=EMBEDDER
            )

    def test_store_refuses_a_vector_in_the_other_routes_list(self, tmp_path):
        from ingest.schema import EmbedRecord
        from ingest.store import write_chunks

        proof = _record(kind="proof")
        embeddings = EmbedRecord(
            chunk_ids_stmt=[proof.chunk_id],
            embedding_stmt=np.stack([_vector(0)]),
            embedder_version=EMBEDDER,
        )
        with pytest.raises(ValueError, match="proof route"):
            write_chunks([proof], embeddings, lancedb_path=tmp_path, build_indices=False)
