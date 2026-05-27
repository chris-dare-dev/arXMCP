"""Integration tests for the LanceDB ``chunks`` table writer (E04_S01).

Coverage map:
  Acceptance criterion -> test class
  ──────────────────────────────────────────────────────────────────────
  Table created on first write_chunks call             -> TestTableCreation
  Schema matches v1 column list exactly                -> TestSchemaContract
  HNSW indices on embedding_stmt + embedding_proof     -> TestIndices
  embedding_eq present + nullable + null on rows       -> TestSchemaContract
  Idempotent upsert (no duplicates on second write)    -> TestIdempotency
  Integration: 10 chunks → count_rows() == 10          -> TestRowCount
  Schema imported from a single schema.py module       -> TestSingleSourceOfTruth

Plus regression tests for D7 (NPZ alignment), D8 (body_tokens=None),
EmbedRecord constructor invariants, the load_embed_record helper, and
write-stats logging.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import (
    CHUNKS_SCHEMA_V1,
    CHUNKS_TABLE_NAME,
    EmbedRecord,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _make_chunk(
    paper_id: str,
    kind: str,
    body_text: str,
    *,
    suffix: str | None = None,
    section_path: list[str] | None = None,
) -> ChunkRecord:
    import hashlib

    if suffix is None:
        suffix = hashlib.sha256(
            f"{paper_id}::{kind}::{body_text}".encode()
        ).hexdigest()[:16]
    return ChunkRecord(
        chunk_id=f"arxiv:{paper_id}:{suffix}",
        paper_id=paper_id,
        kind=kind,
        section_path=section_path or [],
        theorem_name=None,
        theorem_label=None,
        body_text=body_text,
        body_tokens=" ".join(body_text.split()).lower() or "tok",
        preamble_ref=None,
        chunker_version=CHUNKER_VERSION,
    )


def _make_synthetic_embeddings(
    chunks: list[ChunkRecord],
    *,
    seed: int = 0,
) -> EmbedRecord:
    """Build an EmbedRecord with random L2-normalized vectors for ``chunks``.

    Routes by ``kind == "proof"`` like the production embedder. Each
    vector is a fresh seeded ``randn`` so successive calls produce
    distinct vectors (otherwise singleflight regressions would hide).
    """
    rng = np.random.default_rng(seed)
    chunk_ids_stmt: list[str] = []
    chunk_ids_proof: list[str] = []
    rows_stmt: list[np.ndarray] = []
    rows_proof: list[np.ndarray] = []
    for chunk in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        if chunk.kind == "proof":
            chunk_ids_proof.append(chunk.chunk_id)
            rows_proof.append(v)
        else:
            chunk_ids_stmt.append(chunk.chunk_id)
            rows_stmt.append(v)
    embedding_stmt = (
        np.stack(rows_stmt, axis=0)
        if rows_stmt
        else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    )
    embedding_proof = (
        np.stack(rows_proof, axis=0)
        if rows_proof
        else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    )
    return EmbedRecord(
        chunk_ids_stmt=chunk_ids_stmt,
        embedding_stmt=embedding_stmt,
        chunk_ids_proof=chunk_ids_proof,
        embedding_proof=embedding_proof,
        embedder_version=EMBEDDER_VERSION,
    )


def _make_corpus(n: int = 10) -> list[ChunkRecord]:
    """Build N synthetic chunks with mixed kinds + paper IDs."""
    chunks: list[ChunkRecord] = []
    kinds = ["stmt", "proof", "section", "definition", "lemma"]
    for i in range(n):
        paper_id = f"2307.0010{i % 3}"  # 3 distinct papers
        kind = kinds[i % len(kinds)]
        chunks.append(
            _make_chunk(
                paper_id,
                kind,
                f"Body text for chunk {i} in {kind} kind.",
                suffix=f"{i:016x}",
                section_path=["1. Intro"] if i % 2 else [],
            )
        )
    return chunks


# ===========================================================================
# Test isolation: each test uses its own tmp_path → fresh LanceDB.
# The store-stats redirect now lives in tests/conftest.py (F8 fix).
# ===========================================================================


# ===========================================================================
# TestSchemaContract — every column the brief enumerates is present
# ===========================================================================


class TestSchemaContract:
    def test_column_count_matches_brief(self):
        # E04_S01 brief: 14 arXiv columns.
        # textbook-ingest-m2 appended 7 textbook columns
        # (source_kind, license, chapter, page_start, page_end,
        # textbook_slug, parser_used). Total: 21.
        assert len(CHUNKS_SCHEMA_V1) == 21

    def test_column_names_in_brief_order(self):
        expected = [
            # E04_S01 arXiv columns (14)
            "chunk_id",
            "paper_id",
            "kind",
            "section_path",
            "theorem_name",
            "theorem_label",
            "body_text",
            "body_tokens",
            "embedding_stmt",
            "embedding_proof",
            "embedding_eq",
            "chunker_version",
            "embedder_version",
            "preamble_ref",
            # textbook-ingest-m2 columns (7) — appended at the end to
            # keep the arXiv-column block byte-stable for downstream
            # consumers that index by position.
            "source_kind",
            "license",
            "chapter",
            "page_start",
            "page_end",
            "textbook_slug",
            "parser_used",
        ]
        assert CHUNKS_SCHEMA_V1.names == expected

    def test_embedding_columns_are_fixed_size_list_1024(self):
        for col in ("embedding_stmt", "embedding_proof", "embedding_eq"):
            field = CHUNKS_SCHEMA_V1.field(col)
            assert pa.types.is_fixed_size_list(field.type)
            assert field.type.list_size == EMBEDDING_DIM
            assert field.type.value_type == pa.float32()
            assert field.nullable, f"{col} must be nullable"

    def test_required_columns_are_non_nullable(self):
        for col in (
            "chunk_id",
            "paper_id",
            "kind",
            "section_path",
            "body_text",
            "body_tokens",
            "chunker_version",
            "embedder_version",
        ):
            field = CHUNKS_SCHEMA_V1.field(col)
            assert not field.nullable, f"{col} should be non-nullable"

    def test_optional_columns_are_nullable(self):
        for col in ("theorem_name", "theorem_label", "preamble_ref"):
            field = CHUNKS_SCHEMA_V1.field(col)
            assert field.nullable, f"{col} should be nullable"

    def test_section_path_is_list_of_string(self):
        field = CHUNKS_SCHEMA_V1.field("section_path")
        assert pa.types.is_list(field.type)
        assert field.type.value_type == pa.utf8()


# ===========================================================================
# TestSingleSourceOfTruth — schema imported, not redefined inline
# ===========================================================================


class TestSingleSourceOfTruth:
    def test_table_name_constant_unique(self):
        # CHUNKS_TABLE_NAME defined exactly once in ingest/.
        repo_root = Path(__file__).parent.parent
        hits: list[Path] = []
        for py in (repo_root / "ingest").rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            if "CHUNKS_TABLE_NAME = " in text:
                hits.append(py)
        assert len(hits) == 1, (
            f"CHUNKS_TABLE_NAME assignment must appear exactly once; found in: {hits}"
        )
        assert hits[0].name == "schema.py"

    def test_store_imports_schema_does_not_redefine(self):
        # ingest/store.py must import CHUNKS_SCHEMA_V1 — not re-declare a
        # PyArrow schema literal. Detect a redefinition by scanning for
        # ``pa.schema(`` invocations inside store.py.
        repo_root = Path(__file__).parent.parent
        store_text = (repo_root / "ingest" / "store.py").read_text(encoding="utf-8")
        assert "pa.schema(" not in store_text, (
            "ingest/store.py must not declare pa.schema(...) inline; "
            "import CHUNKS_SCHEMA_V1 from ingest.schema instead"
        )

    def test_no_stray_1024_literal_in_new_files(self):
        # EMBEDDING_DIM is the canonical source of the 1024 value
        # (defined in ingest.embedder). The new schema/store files must
        # NOT introduce a stray 1024 literal that could drift.
        repo_root = Path(__file__).parent.parent
        for fname in ("schema.py", "store.py"):
            text = (repo_root / "ingest" / fname).read_text(encoding="utf-8")
            # Allow EMBEDDING_DIM references; just ban the bare literal.
            # Strip out comments so we don't false-positive on things
            # like "# 1024-dim". A real assignment would use the form
            # ``= 1024``, which is what we're guarding against.
            for line in text.splitlines():
                stripped = line.split("#", 1)[0]  # strip inline comments
                assert "= 1024" not in stripped, (
                    f"ingest/{fname} contains a stray '= 1024' literal; "
                    "import EMBEDDING_DIM from ingest.embedder instead"
                )


# ===========================================================================
# TestEmbedRecordConstructor — invariants from schema.py
# ===========================================================================


class TestEmbedRecordConstructor:
    def test_default_is_empty_record(self):
        rec = EmbedRecord(embedder_version="test@0")
        assert rec.chunk_ids_stmt == []
        assert rec.embedding_stmt.shape == (0, EMBEDDING_DIM)
        assert rec.chunk_ids_proof == []
        assert rec.embedding_proof.shape == (0, EMBEDDING_DIM)

    def test_mismatched_stmt_length_raises(self):
        with pytest.raises(ValueError, match="chunk_ids_stmt length"):
            EmbedRecord(
                chunk_ids_stmt=["a", "b"],
                embedding_stmt=np.zeros((3, EMBEDDING_DIM), dtype=np.float32),
                embedder_version="test@0",
            )

    def test_mismatched_proof_length_raises(self):
        with pytest.raises(ValueError, match="chunk_ids_proof length"):
            EmbedRecord(
                chunk_ids_proof=["a"],
                embedding_proof=np.zeros((2, EMBEDDING_DIM), dtype=np.float32),
                embedder_version="test@0",
            )

    def test_wrong_dim_raises(self):
        with pytest.raises(ValueError, match="embedding_stmt dim"):
            EmbedRecord(
                chunk_ids_stmt=["a"],
                embedding_stmt=np.zeros((1, 512), dtype=np.float32),
                embedder_version="test@0",
            )

    def test_wrong_dtype_raises(self):
        with pytest.raises(ValueError, match="dtype must be float32"):
            EmbedRecord(
                chunk_ids_stmt=["a"],
                embedding_stmt=np.zeros((1, EMBEDDING_DIM), dtype=np.float64),
                embedder_version="test@0",
            )

    def test_chunk_id_in_both_lists_raises(self):
        # Routing rule violation: a chunk_id can be in stmt OR proof,
        # never both (the embedder routes by kind exclusively).
        with pytest.raises(ValueError, match="BOTH stmt and proof"):
            EmbedRecord(
                chunk_ids_stmt=["dup"],
                embedding_stmt=np.zeros((1, EMBEDDING_DIM), dtype=np.float32),
                chunk_ids_proof=["dup"],
                embedding_proof=np.zeros((1, EMBEDDING_DIM), dtype=np.float32),
                embedder_version="test@0",
            )


# ===========================================================================
# TestTableCreation — first write creates the table
# ===========================================================================


class TestTableCreation:
    def test_first_write_creates_table(self, tmp_path):
        from ingest.store import write_chunks

        chunks = _make_corpus(5)
        embeddings = _make_synthetic_embeddings(chunks, seed=1)
        version = write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        assert isinstance(version, int)
        # The dataset directory exists.
        assert (tmp_path / "lancedb").is_dir()
        # Open it back via lancedb to confirm the table is real.
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        # list_tables() returns a ListTablesResponse in lancedb 0.30
        # whose ``.tables`` attribute is the plain list. Accept both.
        tables_obj = db.list_tables()
        tables = list(getattr(tables_obj, "tables", tables_obj))
        assert CHUNKS_TABLE_NAME in tables


# ===========================================================================
# TestRowCount + Idempotency + indices — the brief's central acceptance
# ===========================================================================


class TestRowCount:
    def test_ten_chunks_count_rows_eq_ten(self, tmp_path):
        from ingest.store import write_chunks

        chunks = _make_corpus(10)
        embeddings = _make_synthetic_embeddings(chunks, seed=0)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        # Re-open and count.
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        assert tbl.count_rows() == 10


class TestIdempotency:
    def test_second_write_no_duplicates(self, tmp_path):
        from ingest.store import write_chunks

        chunks = _make_corpus(10)
        embeddings = _make_synthetic_embeddings(chunks, seed=2)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        # Same chunks again — must upsert in place.
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        assert tbl.count_rows() == 10

    def test_second_write_updates_existing_row(self, tmp_path):
        # Write a chunk, then overwrite with a different body_text but
        # same chunk_id (synthetic test — real chunk_ids are content-
        # addressable, but we bypass that for this regression).
        from ingest.store import write_chunks

        chunk_a = _make_chunk("2307.00099", "stmt", "first body", suffix="0" * 16)
        chunk_b = _make_chunk("2307.00099", "stmt", "second body", suffix="0" * 16)
        # Same chunk_id (we forced suffix), different body_text.
        assert chunk_a.chunk_id == chunk_b.chunk_id
        embeddings_a = _make_synthetic_embeddings([chunk_a], seed=10)
        embeddings_b = _make_synthetic_embeddings([chunk_b], seed=20)
        write_chunks([chunk_a], embeddings_a, lancedb_path=tmp_path / "lancedb")
        write_chunks([chunk_b], embeddings_b, lancedb_path=tmp_path / "lancedb")
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        assert tbl.count_rows() == 1
        # Use to_arrow() instead of to_pandas() so the test does not
        # require pandas as a dev dep.
        arrow_tbl = tbl.to_arrow()
        body_texts = arrow_tbl.column("body_text").to_pylist()
        # The body_text is now "second body" (the upsert).
        assert body_texts == ["second body"]


class TestIndices:
    def test_hnsw_indices_created_after_write(self, tmp_path):
        from ingest.store import write_chunks

        chunks = _make_corpus(10)
        embeddings = _make_synthetic_embeddings(chunks, seed=3)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        # ``list_indices`` returns descriptors; columns of indexed cols.
        indices = tbl.list_indices()
        index_columns = {idx.columns[0] for idx in indices}
        assert "embedding_stmt" in index_columns
        assert "embedding_proof" in index_columns
        assert "paper_id" in index_columns


# ===========================================================================
# TestEmbeddingRouting — embedding_eq always NULL; dual-column routing
# ===========================================================================


class TestEmbeddingRouting:
    def test_embedding_eq_null_on_all_rows(self, tmp_path):
        from ingest.store import write_chunks

        chunks = _make_corpus(10)
        embeddings = _make_synthetic_embeddings(chunks, seed=4)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        arrow_tbl = tbl.to_arrow()
        # Every row's embedding_eq is None (NULL in Arrow → None in
        # the pylist projection).
        for val in arrow_tbl.column("embedding_eq").to_pylist():
            assert val is None

    def test_proof_chunks_have_only_embedding_proof(self, tmp_path):
        from ingest.store import write_chunks

        chunks = _make_corpus(10)
        embeddings = _make_synthetic_embeddings(chunks, seed=5)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        arrow_tbl = tbl.to_arrow()
        kinds = arrow_tbl.column("kind").to_pylist()
        stmt_vecs = arrow_tbl.column("embedding_stmt").to_pylist()
        proof_vecs = arrow_tbl.column("embedding_proof").to_pylist()
        for kind, stmt_v, proof_v in zip(kinds, stmt_vecs, proof_vecs, strict=True):
            if kind == "proof":
                assert proof_v is not None
                assert stmt_v is None
            else:
                assert stmt_v is not None
                assert proof_v is None


# ===========================================================================
# TestValidationGuards — D7 + D8 from research-synthesis
# ===========================================================================


class TestValidationGuards:
    def test_chunk_missing_from_embed_record_raises(self, tmp_path):
        # D7: a chunk in the chunks list but not in either ID list of
        # the EmbedRecord must raise — never silently insert a
        # null-embedding row.
        from ingest.store import write_chunks

        chunks = _make_corpus(3)
        # Build embeddings for only the FIRST two chunks.
        partial_embeddings = _make_synthetic_embeddings(chunks[:2], seed=6)
        with pytest.raises(ValueError, match="missing from EmbedRecord"):
            write_chunks(chunks, partial_embeddings, lancedb_path=tmp_path / "lancedb")

    def test_body_tokens_none_raises(self, tmp_path):
        # D8: body_tokens=None is a real bug post-E02_S03.
        from ingest.store import write_chunks

        chunk = _make_chunk("2307.00088", "stmt", "body", suffix="a" * 16)
        chunk.body_tokens = None  # forced regression
        embeddings = _make_synthetic_embeddings([chunk], seed=7)
        with pytest.raises(ValueError, match="body_tokens=None"):
            write_chunks([chunk], embeddings, lancedb_path=tmp_path / "lancedb")


# ===========================================================================
# TestStoreStats — write-stats JSONL log
# ===========================================================================


class TestStoreStats:
    def test_jsonl_line_per_call(self, tmp_path, monkeypatch):
        # The autouse fixture has already redirected STORE_STATS_PATH.
        import ingest.store as store_mod
        from ingest.store import write_chunks

        chunks = _make_corpus(3)
        embeddings = _make_synthetic_embeddings(chunks, seed=8)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        stats_path = store_mod.STORE_STATS_PATH
        assert stats_path.exists()
        line = stats_path.read_text(encoding="utf-8").strip()
        row = json.loads(line)
        assert row["chunk_count"] == 3
        assert isinstance(row["lancedb_version"], int)
        assert isinstance(row["elapsed_s"], (int, float))


# ===========================================================================
# TestLoadEmbedRecord — NPZ loader helper
# ===========================================================================


class TestLoadEmbedRecord:
    def test_returns_none_for_missing_npz(self, tmp_path, monkeypatch):
        from ingest.store import load_embed_record

        # Patch EMBEDDINGS_DIR to an empty tmp_path so no NPZs exist.
        monkeypatch.setattr("ingest.store.EMBEDDINGS_DIR", tmp_path / "embeddings")
        assert load_embed_record("2307.00200") is None

    def test_round_trip_via_real_embedder_writers(self, tmp_path, monkeypatch):
        # Use the embedder's actual sidecar + NPZ writers to produce an
        # artifact, then read it back via load_embed_record.
        from ingest.embedder import (
            _write_embeddings_manifest,
            _write_embeddings_npz,
        )
        from ingest.store import load_embed_record

        paper_id = "2307.00201"
        paper_dir = tmp_path / "embeddings" / paper_id
        paper_dir.mkdir(parents=True)
        chunk_ids_stmt = ["arxiv:2307.00201:" + "0" * 16]
        chunk_ids_proof = ["arxiv:2307.00201:" + "1" * 16]
        emb_stmt = np.ones((1, EMBEDDING_DIM), dtype=np.float32) / np.sqrt(
            EMBEDDING_DIM
        )
        emb_proof = (
            np.ones((1, EMBEDDING_DIM), dtype=np.float32) * 2 / np.sqrt(
                EMBEDDING_DIM * 4
            )
        )
        _write_embeddings_npz(
            paper_dir / "embeddings.npz",
            chunk_ids_stmt=chunk_ids_stmt,
            embedding_stmt=emb_stmt,
            chunk_ids_proof=chunk_ids_proof,
            embedding_proof=emb_proof,
        )
        _write_embeddings_manifest(
            paper_dir / "embeddings_manifest.json",
            paper_id=paper_id,
            embedded_chunks=[
                {"chunk_id": chunk_ids_stmt[0], "kind": "stmt"},
                {"chunk_id": chunk_ids_proof[0], "kind": "proof"},
            ],
        )
        monkeypatch.setattr("ingest.store.EMBEDDINGS_DIR", tmp_path / "embeddings")
        rec = load_embed_record(paper_id)
        assert rec is not None
        assert rec.chunk_ids_stmt == chunk_ids_stmt
        assert rec.chunk_ids_proof == chunk_ids_proof
        assert rec.embedding_stmt.shape == (1, EMBEDDING_DIM)
        assert rec.embedding_proof.shape == (1, EMBEDDING_DIM)
        assert rec.embedder_version == EMBEDDER_VERSION

    def test_missing_sidecar_raises(self, tmp_path, monkeypatch):
        # NPZ present, sidecar absent — must raise (the embedder_version
        # is unknowable without the sidecar).
        from ingest.embedder import _write_embeddings_npz
        from ingest.store import load_embed_record

        paper_id = "2307.00202"
        paper_dir = tmp_path / "embeddings" / paper_id
        paper_dir.mkdir(parents=True)
        _write_embeddings_npz(
            paper_dir / "embeddings.npz",
            chunk_ids_stmt=["arxiv:2307.00202:" + "0" * 16],
            embedding_stmt=np.zeros((1, EMBEDDING_DIM), dtype=np.float32),
            chunk_ids_proof=[],
            embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        )
        monkeypatch.setattr("ingest.store.EMBEDDINGS_DIR", tmp_path / "embeddings")
        with pytest.raises(ValueError, match="no sidecar manifest"):
            load_embed_record(paper_id)


# ===========================================================================
# Phase 4 rectification regression tests (F1, F2, F4, F6, F10)
# ===========================================================================


class TestPaperIdValidation:
    def test_load_embed_record_rejects_path_traversal(self):
        """Closes F1 from the E04_S01 critique: ``load_embed_record``
        must call ``_validate_paper_id`` BEFORE any path concat. A
        traversal-shaped paper_id like ``"../../../etc/passwd"`` must
        raise rather than silently traverse out of EMBEDDINGS_DIR."""
        from ingest.chunker import InvalidPaperIDError
        from ingest.store import load_embed_record

        with pytest.raises(InvalidPaperIDError):
            load_embed_record("../../../etc/passwd")
        with pytest.raises(InvalidPaperIDError):
            load_embed_record("not-a-paper-id")
        with pytest.raises(InvalidPaperIDError):
            load_embed_record("")


class TestWithinListDuplicateRejected:
    def test_duplicate_chunk_id_in_stmt_list_raises(self):
        # Closes F2 from the E04_S01 critique: a chunk_id that appears
        # twice in chunk_ids_stmt (or chunk_ids_proof) silently
        # collapses in the dict-comprehension lookup downstream and
        # discards one vector. Validate at the EmbedRecord boundary.
        # Build two unit vectors so the L2-norm check (F4) doesn't
        # fire first.
        rng = np.random.default_rng(98)
        rows = rng.standard_normal((2, EMBEDDING_DIM)).astype(np.float32)
        rows /= np.linalg.norm(rows, axis=1, keepdims=True)
        with pytest.raises(ValueError, match="duplicate chunk_id.*chunk_ids_stmt"):
            EmbedRecord(
                chunk_ids_stmt=["dup", "dup"],
                embedding_stmt=rows,
                embedder_version=EMBEDDER_VERSION,
            )

    def test_duplicate_chunk_id_in_proof_list_raises(self):
        # Build two unit vectors via a normalized identity-like
        # construction so the L2-norm check (F4) doesn't fire first.
        rng = np.random.default_rng(99)
        rows = rng.standard_normal((2, EMBEDDING_DIM)).astype(np.float32)
        rows /= np.linalg.norm(rows, axis=1, keepdims=True)
        with pytest.raises(ValueError, match="duplicate chunk_id.*chunk_ids_proof"):
            EmbedRecord(
                chunk_ids_proof=["dup", "dup"],
                embedding_proof=rows,
                embedder_version=EMBEDDER_VERSION,
            )


class TestL2NormEnforcement:
    def test_unnormalized_stmt_vectors_raise(self):
        # Closes F4 from the E04_S01 critique: BGE-M3 outputs are
        # L2-normalized; the store's HNSW index uses ``distance_type='l2'``
        # so un-normalized vectors silently corrupt ANN ranking.
        # Validate at the EmbedRecord boundary.
        bad = np.full((1, EMBEDDING_DIM), 2.0, dtype=np.float32)  # norm = 2*sqrt(N) >> 1
        with pytest.raises(ValueError, match="un-normalized vectors"):
            EmbedRecord(
                chunk_ids_stmt=["arxiv:2307.00301:" + "0" * 16],
                embedding_stmt=bad,
                embedder_version=EMBEDDER_VERSION,
            )

    def test_unnormalized_proof_vectors_raise(self):
        bad = np.full((1, EMBEDDING_DIM), 0.5, dtype=np.float32)
        with pytest.raises(ValueError, match="un-normalized vectors"):
            EmbedRecord(
                chunk_ids_proof=["arxiv:2307.00302:" + "0" * 16],
                embedding_proof=bad,
                embedder_version=EMBEDDER_VERSION,
            )

    def test_zero_vectors_rejected(self):
        # Zero vectors have norm 0 — must NOT pass the L2-norm check.
        # (BGE-M3 never emits zero vectors; this catches a pathological
        # caller.)
        with pytest.raises(ValueError, match="un-normalized vectors"):
            EmbedRecord(
                chunk_ids_stmt=["arxiv:2307.00303:" + "0" * 16],
                embedding_stmt=np.zeros((1, EMBEDDING_DIM), dtype=np.float32),
                embedder_version=EMBEDDER_VERSION,
            )

    def test_normalized_vectors_pass(self):
        # Sanity: normalized vectors construct cleanly.
        rng = np.random.default_rng(7)
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        EmbedRecord(
            chunk_ids_stmt=["arxiv:2307.00304:" + "0" * 16],
            embedding_stmt=v.reshape(1, -1),
            embedder_version=EMBEDDER_VERSION,
        )


class TestMixedInsertAndUpdate:
    def test_first_n_then_n_plus_m(self, tmp_path):
        """Closes F6 from the E04_S01 critique: idempotency tests
        previously covered only same-input-twice and single-row
        update. The realistic ingest case is "second batch is a
        superset of the first" — verify the upsert produces N+M
        rows total."""
        from ingest.store import write_chunks

        # First batch: 5 chunks.
        first_batch = _make_corpus(5)
        first_emb = _make_synthetic_embeddings(first_batch, seed=11)
        write_chunks(first_batch, first_emb, lancedb_path=tmp_path / "lancedb")
        # Second batch: same 5 + 3 new chunks (different suffixes).
        new_chunks = []
        for i in range(3):
            paper_id = f"2307.0020{i}"
            new_chunks.append(
                _make_chunk(
                    paper_id, "stmt", f"new chunk {i}",
                    suffix=f"new{i:013x}",
                )
            )
        second_batch = first_batch + new_chunks
        second_emb = _make_synthetic_embeddings(second_batch, seed=12)
        write_chunks(second_batch, second_emb, lancedb_path=tmp_path / "lancedb")
        # Total rows = 5 + 3 = 8.
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        assert tbl.count_rows() == 8


class TestKindValidation:
    def test_invalid_kind_raises(self, tmp_path):
        """Closes F10 from the E04_S01 critique: a chunker bug or
        driver typo like ``"theroem"`` (instead of ``"theorem"``) must
        surface at write time, not silently land in the dataset."""
        from ingest.store import write_chunks

        chunk = _make_chunk("2307.00400", "stmt", "body", suffix="0" * 16)
        chunk.kind = "theroem"  # typo — not in _ALLOWED_KINDS
        embeddings = _make_synthetic_embeddings([chunk], seed=14)
        # The synthetic-embeddings helper routes by kind == "proof"
        # (everything else goes to stmt), so the typo'd kind ends up in
        # the stmt list. It should raise on write.
        with pytest.raises(ValueError, match="not in the allowed set"):
            write_chunks([chunk], embeddings, lancedb_path=tmp_path / "lancedb")

    def test_all_chunker_kinds_pass(self, tmp_path):
        """Sanity: every kind the chunker actually emits is in
        ``_ALLOWED_KINDS``. Build one chunk per kind and confirm the
        write succeeds. This catches a future chunker change that adds
        a new kind without updating the allowed set in store.py."""
        from ingest.chunker import _THEOREM_ENV_KINDS
        from ingest.store import write_chunks

        kinds = sorted(set(_THEOREM_ENV_KINDS.values()) | {"stmt", "proof", "section"})
        chunks = [
            _make_chunk(f"2307.0050{i}", k, f"body {i}", suffix=f"{i:016x}")
            for i, k in enumerate(kinds)
        ]
        embeddings = _make_synthetic_embeddings(chunks, seed=15)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        assert tbl.count_rows() == len(kinds)


class TestStructuredIndicesCreated:
    def test_indices_created_is_dict_in_stats(self, tmp_path):
        """Closes F14 from the E04_S01 critique: ``indices_created``
        in the ops log is now a ``dict[str, bool]`` so consumers can
        filter individual outcomes without parsing strings."""
        import ingest.store as store_mod
        from ingest.store import write_chunks

        chunks = _make_corpus(3)
        embeddings = _make_synthetic_embeddings(chunks, seed=16)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        line = store_mod.STORE_STATS_PATH.read_text(encoding="utf-8").strip()
        row = json.loads(line)
        assert isinstance(row["indices_created"], dict)
        # Both HNSW indices must have succeeded (F3: hard-error semantics).
        assert row["indices_created"].get("hnsw_stmt") is True
        assert row["indices_created"].get("hnsw_proof") is True
        # Scalar index either succeeded or was logged as False.
        assert row["indices_created"].get("scalar_paper_id") in (True, False)


# ===========================================================================
# textbook-ingest-m2 — round-trip + migration tests
# ===========================================================================


def _make_textbook_chunk(
    slug: str,
    *,
    suffix: str = "abcdef0123456789",
    chapter: str = "Chapter 1: Schemes",
    page_start: int = 1,
    page_end: int = 10,
    license_token: str = "GFDL",
) -> ChunkRecord:
    """Build a textbook-shaped ChunkRecord for round-trip tests.

    Uses the ``textbook:<slug>`` paper_id form (m1 regex) and populates
    the m2 textbook-specific fields so the round-trip assertions can
    confirm every column survives.
    """
    return ChunkRecord(
        chunk_id=f"textbook:{slug}:{suffix}",
        paper_id=f"textbook:{slug}",
        kind="definition",
        section_path=["Chapter 1", "1.1 Affine schemes"],
        theorem_name=None,
        theorem_label=None,
        body_text="A scheme is a locally ringed space which admits a cover by affine schemes.",
        body_tokens="a scheme is a locally ringed space",
        preamble_ref=None,
        chunker_version=CHUNKER_VERSION,
        source_kind="textbook",
        license=license_token,
        chapter=chapter,
        page_start=page_start,
        page_end=page_end,
        textbook_slug=slug,
        parser_used="mineru+latexml",
    )


class TestTextbookChunkRoundtrip:
    """AC #1 — textbook chunk with ``source_kind="textbook"`` round-trips
    all 7 new columns with correct types."""

    def test_textbook_chunk_all_columns_survive_roundtrip(self, tmp_path):
        from ingest.store import write_chunks

        chunk = _make_textbook_chunk("shimura-varieties")
        embeddings = _make_synthetic_embeddings([chunk], seed=42)
        write_chunks([chunk], embeddings, lancedb_path=tmp_path / "lancedb")

        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        rows = tbl.to_arrow().to_pylist()
        assert len(rows) == 1
        row = rows[0]
        # The 7 m2 columns all populated with the input values.
        assert row["source_kind"] == "textbook"
        assert row["license"] == "GFDL"
        assert row["chapter"] == "Chapter 1: Schemes"
        assert row["page_start"] == 1
        assert row["page_end"] == 10
        assert row["textbook_slug"] == "shimura-varieties"
        assert row["parser_used"] == "mineru+latexml"
        # And the pre-existing columns still work as expected.
        assert row["chunk_id"] == chunk.chunk_id
        assert row["paper_id"] == "textbook:shimura-varieties"
        assert row["kind"] == "definition"

    def test_textbook_chunk_id_passes_chunker_paper_id_regex(self):
        """Sanity: m1's identifier regex accepts the paper_id the
        textbook chunk carries, so the chunker's _validate_paper_id
        won't reject textbook IDs in a future driver path."""
        from ingest.chunker import _PAPER_ID_RE

        assert _PAPER_ID_RE.match("textbook:shimura-varieties") is not None


class TestArxivChunkByteStableAfterSchemaBump:
    """AC #2 — existing arXiv chunks read with documented defaults;
    existing field values byte-identical to pre-m2 behavior."""

    def test_arxiv_chunk_defaults_populated_via_chunkrecord(self, tmp_path):
        from ingest.store import write_chunks

        chunk = _make_chunk("2307.00099", "stmt", "body", suffix="0" * 16)
        embeddings = _make_synthetic_embeddings([chunk], seed=11)
        write_chunks([chunk], embeddings, lancedb_path=tmp_path / "lancedb")

        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        row = tbl.to_arrow().to_pylist()[0]
        # ChunkRecord defaults: source_kind="arxiv", license="arxiv-license".
        assert row["source_kind"] == "arxiv"
        assert row["license"] == "arxiv-license"
        # Textbook-only fields are None for arXiv chunks.
        assert row["chapter"] is None
        assert row["page_start"] is None
        assert row["page_end"] is None
        assert row["textbook_slug"] is None
        assert row["parser_used"] is None
        # Pre-m2 fields unchanged.
        assert row["paper_id"] == "2307.00099"
        assert row["chunk_id"] == chunk.chunk_id
        assert row["body_text"] == "body"


class TestMixedCorpusInSameTable:
    """AC #1+#2 combined — arXiv and textbook chunks coexist cleanly
    in the same LanceDB table without column drift."""

    def test_both_kinds_coexist(self, tmp_path):
        from ingest.store import write_chunks

        arxiv_chunk = _make_chunk("2307.00099", "stmt", "arxiv body", suffix="a" * 16)
        textbook_chunk = _make_textbook_chunk("hartshorne")
        chunks = [arxiv_chunk, textbook_chunk]
        embeddings = _make_synthetic_embeddings(chunks, seed=22)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")

        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        assert tbl.count_rows() == 2
        rows = {r["chunk_id"]: r for r in tbl.to_arrow().to_pylist()}
        # arXiv chunk: defaults + arxiv paper_id.
        a = rows[arxiv_chunk.chunk_id]
        assert a["source_kind"] == "arxiv"
        assert a["license"] == "arxiv-license"
        assert a["textbook_slug"] is None
        # textbook chunk: populated + textbook paper_id.
        t = rows[textbook_chunk.chunk_id]
        assert t["source_kind"] == "textbook"
        assert t["license"] == "GFDL"
        assert t["textbook_slug"] == "hartshorne"


class TestSourceKindEnumGuard:
    """``_ALLOWED_SOURCE_KINDS`` guard catches typos before they land
    in the dataset — mirrors the existing ``kind`` enum guard
    (F10 from the E04_S01 critique)."""

    def test_invalid_source_kind_raises(self, tmp_path):
        from ingest.store import write_chunks

        chunk = _make_chunk("2307.00200", "stmt", "body", suffix="b" * 16)
        chunk.source_kind = "arxv"  # typo
        embeddings = _make_synthetic_embeddings([chunk], seed=33)
        with pytest.raises(ValueError, match="source_kind"):
            write_chunks([chunk], embeddings, lancedb_path=tmp_path / "lancedb")

    def test_textbook_source_kind_accepted(self, tmp_path):
        from ingest.store import write_chunks

        chunk = _make_textbook_chunk("stacks-project")
        embeddings = _make_synthetic_embeddings([chunk], seed=34)
        # Should NOT raise.
        write_chunks([chunk], embeddings, lancedb_path=tmp_path / "lancedb")


class TestSchemaMigrationGuard:
    """FM-1 from m2 synthesis — pre-m2 (14-column) chunks tables
    auto-migrate on next ``write_chunks`` so existing rows pick up
    ``source_kind="arxiv"`` / ``license="arxiv-license"`` via the SQL
    backfill (FM-6 mitigation)."""

    def _make_legacy_14col_table(self, tmp_path):
        """Create a chunks table with the pre-m2 14-column schema."""
        import lancedb

        legacy_schema = pa.schema(
            [
                pa.field("chunk_id", pa.utf8(), nullable=False),
                pa.field("paper_id", pa.utf8(), nullable=False),
                pa.field("kind", pa.utf8(), nullable=False),
                pa.field("section_path", pa.list_(pa.utf8()), nullable=False),
                pa.field("theorem_name", pa.utf8(), nullable=True),
                pa.field("theorem_label", pa.utf8(), nullable=True),
                pa.field("body_text", pa.utf8(), nullable=False),
                pa.field("body_tokens", pa.utf8(), nullable=False),
                pa.field(
                    "embedding_stmt",
                    pa.list_(pa.float32(), EMBEDDING_DIM),
                    nullable=True,
                ),
                pa.field(
                    "embedding_proof",
                    pa.list_(pa.float32(), EMBEDDING_DIM),
                    nullable=True,
                ),
                pa.field(
                    "embedding_eq",
                    pa.list_(pa.float32(), EMBEDDING_DIM),
                    nullable=True,
                ),
                pa.field("chunker_version", pa.utf8(), nullable=False),
                pa.field("embedder_version", pa.utf8(), nullable=False),
                pa.field("preamble_ref", pa.utf8(), nullable=True),
            ]
        )
        db = lancedb.connect(str(tmp_path / "lancedb"))
        legacy_row = {
            "chunk_id": "arxiv:2307.00777:" + "c" * 16,
            "paper_id": "2307.00777",
            "kind": "stmt",
            "section_path": ["1. Intro"],
            "theorem_name": None,
            "theorem_label": None,
            "body_text": "legacy body",
            "body_tokens": "legacy body",
            "embedding_stmt": [0.0] * EMBEDDING_DIM,
            "embedding_proof": None,
            "embedding_eq": None,
            "chunker_version": "v1.0",
            "embedder_version": "bge-m3@legacy00",
            "preamble_ref": None,
        }
        tbl = db.create_table(
            CHUNKS_TABLE_NAME,
            data=pa.Table.from_pylist([legacy_row], schema=legacy_schema),
        )
        return db, tbl

    def test_migration_adds_seven_columns_with_arxiv_defaults(self, tmp_path):
        from ingest.store import write_chunks

        # Build the 14-col legacy table directly.
        db, tbl = self._make_legacy_14col_table(tmp_path)
        assert len(tbl.schema.names) == 14
        assert "source_kind" not in tbl.schema.names

        # Trigger the migration via a follow-up write_chunks call
        # (which calls _migrate_chunks_schema_if_needed internally).
        new_chunk = _make_chunk(
            "2307.00888", "stmt", "new body", suffix="d" * 16
        )
        new_embed = _make_synthetic_embeddings([new_chunk], seed=44)
        write_chunks([new_chunk], new_embed, lancedb_path=tmp_path / "lancedb")

        # Re-open and assert all 21 columns present.
        tbl2 = db.open_table(CHUNKS_TABLE_NAME)
        assert len(tbl2.schema.names) == 21
        for col in CHUNKS_SCHEMA_V1.names:
            assert col in tbl2.schema.names, f"column {col} missing post-migration"

        # The legacy row's m2 columns now have arXiv backfilled defaults.
        rows = {r["chunk_id"]: r for r in tbl2.to_arrow().to_pylist()}
        legacy = rows["arxiv:2307.00777:" + "c" * 16]
        assert legacy["source_kind"] == "arxiv"
        assert legacy["license"] == "arxiv-license"
        # Textbook-only fields stay NULL on legacy rows.
        assert legacy["chapter"] is None
        assert legacy["page_start"] is None
        assert legacy["page_end"] is None
        assert legacy["textbook_slug"] is None
        assert legacy["parser_used"] is None

        # m2 rect F6: column TYPES post-migration must match the
        # canonical schema. Defense-in-depth — a future LanceDB
        # version that changes SQL ``int`` width semantics would
        # silently produce a type-mismatched column otherwise.
        for col_name in (
            "source_kind",
            "license",
            "chapter",
            "page_start",
            "page_end",
            "textbook_slug",
            "parser_used",
        ):
            assert tbl2.schema.field(col_name).type == CHUNKS_SCHEMA_V1.field(
                col_name
            ).type, f"m2 rect F6 — migration type mismatch for {col_name}"

    def test_post_migration_nullability_matches_canonical(self, tmp_path):
        """m2 rect F2 regression guard.

        LanceDB ``add_columns`` with a non-NULL SQL default infers
        ``nullable=False`` from the expression. Without the
        ``alter_columns`` pass in ``_migrate_chunks_schema_if_needed``,
        ``source_kind`` and ``license`` on a migrated table become
        stricter than on a freshly-created v21 table — a
        path-dependent skew. This test asserts every m2 column post-
        migration has the same nullable bit as ``CHUNKS_SCHEMA_V1``.
        """
        from ingest.store import write_chunks

        db, _tbl = self._make_legacy_14col_table(tmp_path)
        new_chunk = _make_chunk(
            "2307.00999", "stmt", "post-migration", suffix="e" * 16
        )
        new_embed = _make_synthetic_embeddings([new_chunk], seed=66)
        write_chunks([new_chunk], new_embed, lancedb_path=tmp_path / "lancedb")

        tbl2 = db.open_table(CHUNKS_TABLE_NAME)
        for col_name in (
            "source_kind",
            "license",
            "chapter",
            "page_start",
            "page_end",
            "textbook_slug",
            "parser_used",
        ):
            post = tbl2.schema.field(col_name).nullable
            canonical = CHUNKS_SCHEMA_V1.field(col_name).nullable
            assert post == canonical, (
                f"m2 rect F2 — nullability skew on {col_name}: "
                f"migrated={post} vs canonical={canonical}"
            )

    def test_merge_insert_update_on_migrated_table(self, tmp_path):
        """m2 rect F3 regression guard.

        The legacy 14-col table is migrated, then a write of a
        ChunkRecord with the SAME chunk_id as the legacy row but a
        different ``source_kind`` value MUST update the row (merge_insert
        semantics) — not duplicate it. Verifies that merge_insert
        works across the migration boundary on m2 columns.
        """
        from ingest.store import write_chunks

        db, _tbl = self._make_legacy_14col_table(tmp_path)

        # The legacy row has chunk_id "arxiv:2307.00777:cccccccccccccccc"
        # from _make_legacy_14col_table. Write a ChunkRecord with the
        # same chunk_id but populated m2 fields to test the upsert
        # path on the migrated table. Use kind="stmt" (matches the
        # legacy row's kind) so the embedding routing is consistent.
        update_chunk = ChunkRecord(
            chunk_id="arxiv:2307.00777:" + "c" * 16,
            paper_id="2307.00777",
            kind="stmt",
            section_path=["updated"],
            theorem_name=None,
            theorem_label=None,
            body_text="updated body",
            body_tokens="updated body",
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
            # Explicit m2 fields — the upsert path should preserve them.
            source_kind="arxiv",
            license="arxiv-license",
            parser_used="ar5iv",
        )
        embeddings = _make_synthetic_embeddings([update_chunk], seed=77)
        write_chunks([update_chunk], embeddings, lancedb_path=tmp_path / "lancedb")

        tbl2 = db.open_table(CHUNKS_TABLE_NAME)
        # Still exactly 1 row — merge_insert updated, didn't duplicate.
        assert tbl2.count_rows() == 1
        rows = tbl2.to_arrow().to_pylist()
        row = rows[0]
        assert row["body_text"] == "updated body"
        assert row["section_path"] == ["updated"]
        assert row["source_kind"] == "arxiv"
        assert row["license"] == "arxiv-license"
        assert row["parser_used"] == "ar5iv"

    def test_textbook_chunk_into_migrated_table(self, tmp_path):
        """m2 rect F3 regression guard — a brand-new textbook chunk
        can be written into a previously-migrated arXiv table.
        """
        from ingest.store import write_chunks

        db, _tbl = self._make_legacy_14col_table(tmp_path)
        # Trigger the migration with a no-op arXiv write first.
        primer = _make_chunk("2307.00111", "stmt", "primer", suffix="f" * 16)
        embeds_a = _make_synthetic_embeddings([primer], seed=80)
        write_chunks([primer], embeds_a, lancedb_path=tmp_path / "lancedb")

        # Now write a textbook chunk against the migrated table.
        textbook = _make_textbook_chunk("stacks-project")
        embeds_b = _make_synthetic_embeddings([textbook], seed=81)
        write_chunks([textbook], embeds_b, lancedb_path=tmp_path / "lancedb")

        tbl = db.open_table(CHUNKS_TABLE_NAME)
        rows = {r["chunk_id"]: r for r in tbl.to_arrow().to_pylist()}
        tb_row = rows[textbook.chunk_id]
        assert tb_row["source_kind"] == "textbook"
        assert tb_row["license"] == "GFDL"
        assert tb_row["chapter"] == "Chapter 1: Schemes"
        assert tb_row["page_start"] == 1
        assert tb_row["page_end"] == 10
        assert tb_row["textbook_slug"] == "stacks-project"
        assert tb_row["parser_used"] == "mineru+latexml"

    def test_migration_is_idempotent(self, tmp_path):
        """A second write_chunks call after migration is a no-op for
        the schema (no double-add_columns)."""
        from ingest.store import _migrate_chunks_schema_if_needed, write_chunks

        chunks = _make_corpus(3)
        embeddings = _make_synthetic_embeddings(chunks, seed=55)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")

        # Reopen and call the migration helper directly — should return
        # an empty list since the table is already at v21.
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        added = _migrate_chunks_schema_if_needed(tbl)
        assert added == []
        # Schema still has exactly 21 columns.
        assert len(tbl.schema.names) == 21

    def test_migration_unhandled_column_raises(self, tmp_path):
        """A future schema column not in _TEXTBOOK_MIGRATION_DEFAULTS
        triggers a loud RuntimeError rather than silent skip.

        Note (m2 rect F5): this test uses ``patch`` to simulate the
        future-m3 negative branch. The mock surface
        (``ingest.store.CHUNKS_SCHEMA_V1``) is intentionally the
        module-level alias; a hypothetical store.py refactor that
        re-imports CHUNKS_SCHEMA_V1 into a different namespace would
        need to update this patch path in lockstep with the
        sibling positive-branch test below.
        """
        from unittest.mock import patch

        from ingest.store import _migrate_chunks_schema_if_needed

        # Simulate a future schema that includes an unknown column.
        future_schema = pa.schema(
            [*CHUNKS_SCHEMA_V1, pa.field("future_m3_col", pa.utf8(), nullable=True)]
        )
        _db, tbl = self._make_legacy_14col_table(tmp_path)
        with (
            patch("ingest.store.CHUNKS_SCHEMA_V1", future_schema),
            pytest.raises(RuntimeError, match="future_m3_col"),
        ):
            _migrate_chunks_schema_if_needed(tbl)

    def test_migration_extensible_with_new_default(self, tmp_path):
        """m2 rect F5 positive-branch sibling.

        When a future milestone (e.g. m3) lands a new chunks-table
        column AND extends ``_TEXTBOOK_MIGRATION_DEFAULTS`` with a
        matching SQL expression, the migration helper should add the
        column cleanly. Asymmetric coverage with the negative-branch
        test above ensures the trip-wire reminder is balanced.
        """
        from unittest.mock import patch

        from ingest.store import (
            _TEXTBOOK_MIGRATION_DEFAULTS,
            _migrate_chunks_schema_if_needed,
        )

        future_schema = pa.schema(
            [
                *CHUNKS_SCHEMA_V1,
                pa.field("future_m3_col", pa.utf8(), nullable=True),
            ]
        )
        future_defaults = {
            **_TEXTBOOK_MIGRATION_DEFAULTS,
            "future_m3_col": "cast(NULL as string)",
        }
        _db, tbl = self._make_legacy_14col_table(tmp_path)
        with (
            patch("ingest.store.CHUNKS_SCHEMA_V1", future_schema),
            patch("ingest.store._TEXTBOOK_MIGRATION_DEFAULTS", future_defaults),
        ):
            added = _migrate_chunks_schema_if_needed(tbl)

        assert "future_m3_col" in added
        # The 7 m2 columns + the simulated m3 column all landed.
        assert len(added) == 8
        assert "future_m3_col" in tbl.schema.names


class TestParserUsedEnumGuard:
    """m2 rect F4 — ``parser_used`` is a documented enum (per the
    brief's "extend the parser_used enum" wording). Without the
    guard, a chunker bug or driver typo (``"latexm"``, ``"ar5iv2"``)
    pollutes the chunks table and downstream chunk-grained re-parse
    decisions read the wrong provenance.
    """

    def test_invalid_parser_used_raises(self, tmp_path):
        from ingest.store import write_chunks

        chunk = _make_chunk("2307.00300", "stmt", "body", suffix="9" * 16)
        chunk.parser_used = "latexm"  # typo
        embeddings = _make_synthetic_embeddings([chunk], seed=91)
        with pytest.raises(ValueError, match="parser_used"):
            write_chunks([chunk], embeddings, lancedb_path=tmp_path / "lancedb")

    def test_none_parser_used_accepted(self, tmp_path):
        """None means failure / unknown per the docstring; must NOT raise."""
        from ingest.store import write_chunks

        chunk = _make_chunk("2307.00400", "stmt", "body", suffix="8" * 16)
        assert chunk.parser_used is None  # ChunkRecord default
        embeddings = _make_synthetic_embeddings([chunk], seed=92)
        write_chunks([chunk], embeddings, lancedb_path=tmp_path / "lancedb")

    def test_each_valid_parser_used_accepted(self, tmp_path):
        from ingest.store import _ALLOWED_PARSER_USED, write_chunks

        for i, parser in enumerate(sorted(_ALLOWED_PARSER_USED)):
            chunk = _make_chunk(
                f"2307.0050{i}", "stmt", f"body {i}", suffix=f"7{i:015x}"
            )
            chunk.parser_used = parser
            embeddings = _make_synthetic_embeddings([chunk], seed=93 + i)
            write_chunks(
                [chunk], embeddings, lancedb_path=tmp_path / f"lancedb-{i}"
            )
