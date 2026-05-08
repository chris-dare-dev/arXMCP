"""MVCC tests for the LanceDB ``chunks`` dataset (E04_S02).

Coverage map:
  Acceptance criterion -> test
  ──────────────────────────────────────────────────────────────────────
  write_chunks returns int dataset version           -> TestVersionIsInt
  open_chunks_table(path, v_a).count == 10           -> TestVersionPinning
  open_chunks_table(path, v_b).count == 15           -> TestVersionPinning
  No symlinks under var/arxmcp/index/lancedb/        -> TestNoSymlinks
  store.py docstring states the AC5 sentence         -> TestDocstringContract
  open_chunks_table(path, version=None) → live tip   -> TestVersionPinning
  invalid version raises ValueError                  -> TestVersionPinning
  writes against checked-out table raise ValueError  -> TestWriteRejection
  CHUNKS_TABLE_NAME imported, not redefined          -> TestSingleSourceOfTruth

Real LanceDB on tmp_path; no model load. Synthetic random vectors
produced by the same helper used in test_store.py (re-imported here
to avoid duplication).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from server.corpus import open_chunks_table

# Reuse the synthetic-corpus helpers from test_store.py rather than
# duplicating the bodies. Direct module import is the cleanest bridge —
# the helpers are pure (no side effects on import) and test_store.py
# defines them at module scope.
from tests.test_store import (
    _make_corpus,
    _make_synthetic_embeddings,
)

# ===========================================================================
# TestVersionIsInt — AC1 from the brief
# ===========================================================================


class TestVersionIsInt:
    def test_write_chunks_returns_int(self, tmp_path):
        from ingest.store import write_chunks

        chunks = _make_corpus(5)
        embeddings = _make_synthetic_embeddings(chunks, seed=1)
        result = write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        # The brief AC: "write_chunks returns the new LanceDB dataset
        # version integer on each call."
        assert isinstance(result, int)
        assert result > 0


# ===========================================================================
# TestVersionPinning — the brief's central MVCC AC
# ===========================================================================


class TestVersionPinning:
    def test_checkout_pre_and_post_second_write(self, tmp_path):
        """Brief AC: write 10 chunks (v_a), write 5 more (v_b),
        ``checkout(v_a)`` returns 10 rows and ``checkout(v_b)`` returns
        15 rows.

        Use the helper-returned values rather than hard-coding 1/2 —
        the actual integers depend on how many ``_create_indices``
        calls occurred between writes (see ``ingest/store.py``'s
        post-index version invariant).
        """
        from ingest.store import write_chunks

        # First batch: 10 chunks, capture version v_a.
        first_batch = _make_corpus(10)
        first_emb = _make_synthetic_embeddings(first_batch, seed=10)
        v_a = write_chunks(
            first_batch, first_emb, lancedb_path=tmp_path / "lancedb"
        )
        # Second batch: 10 originals + 5 new chunks, capture version v_b.
        new_chunks = []
        for i in range(5):
            paper_id = f"2307.0030{i}"
            new_chunks.append(
                __import__("tests.test_store", fromlist=["_make_chunk"])._make_chunk(
                    paper_id, "stmt", f"new chunk {i}",
                    suffix=f"new{i:013x}",
                )
            )
        second_batch = first_batch + new_chunks
        second_emb = _make_synthetic_embeddings(second_batch, seed=11)
        v_b = write_chunks(
            second_batch, second_emb, lancedb_path=tmp_path / "lancedb"
        )

        assert v_a < v_b, f"second write must produce a newer version (v_a={v_a}, v_b={v_b})"

        # checkout(v_a) returns the dataset as it was after the first write.
        tbl_a = open_chunks_table(tmp_path / "lancedb", version=v_a)
        assert tbl_a.count_rows() == 10, (
            f"checkout(v_a={v_a}) should return 10 rows; got {tbl_a.count_rows()}"
        )
        # checkout(v_b) returns the dataset after the second write (10 + 5 = 15).
        tbl_b = open_chunks_table(tmp_path / "lancedb", version=v_b)
        assert tbl_b.count_rows() == 15, (
            f"checkout(v_b={v_b}) should return 15 rows; got {tbl_b.count_rows()}"
        )

    def test_checkout_none_returns_live_tip(self, tmp_path):
        """``open_chunks_table(path, version=None)`` returns the live
        tip — useful for callers that don't care about pinning."""
        from ingest.store import write_chunks

        chunks = _make_corpus(7)
        embeddings = _make_synthetic_embeddings(chunks, seed=12)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        tbl = open_chunks_table(tmp_path / "lancedb", version=None)
        assert tbl.count_rows() == 7

    def test_invalid_version_raises_value_error(self, tmp_path):
        from ingest.store import write_chunks

        chunks = _make_corpus(3)
        embeddings = _make_synthetic_embeddings(chunks, seed=13)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        with pytest.raises(ValueError, match="not accessible"):
            open_chunks_table(tmp_path / "lancedb", version=999_999)

    def test_missing_path_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="does not exist"):
            open_chunks_table(tmp_path / "does_not_exist", version=None)


# ===========================================================================
# TestWriteRejection — checkout is read-only (LanceDB's own guard)
# ===========================================================================


class TestWriteRejection:
    def test_writes_against_checked_out_table_raise(self, tmp_path):
        """LanceDB's built-in write guard raises when a write is
        attempted against a checked-out table. We rely on this rather
        than wrapping in a defensive proxy."""
        from ingest.store import write_chunks

        chunks = _make_corpus(3)
        embeddings = _make_synthetic_embeddings(chunks, seed=14)
        v_a = write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        tbl = open_chunks_table(tmp_path / "lancedb", version=v_a)
        # Construct a row matching the schema and try to add it. LanceDB
        # raises ValueError for the version-pinned write.
        new_row = [
            {
                "chunk_id": "arxiv:2307.99999:" + "0" * 16,
                "paper_id": "2307.99999",
                "kind": "stmt",
                "section_path": [],
                "theorem_name": None,
                "theorem_label": None,
                "body_text": "rejected",
                "body_tokens": "rejected",
                "embedding_stmt": [0.0] * 1024,
                "embedding_proof": None,
                "embedding_eq": None,
                "chunker_version": "v1.0",
                "embedder_version": "test@0",
                "preamble_ref": None,
            }
        ]
        # Use a normalized vector since the schema accepts the value.
        v = np.random.default_rng(15).standard_normal(1024).astype(np.float32)
        v /= np.linalg.norm(v)
        new_row[0]["embedding_stmt"] = v.tolist()
        # LanceDB raises ``ValueError`` ("table cannot be modified when a
        # specific version is checked out") on writes against a
        # checked-out table. The exact subclass may shift across
        # lancedb releases, so we match the broad ``ValueError`` family
        # which is the documented contract.
        with pytest.raises(ValueError):
            tbl.add(new_row)


# ===========================================================================
# TestNoSymlinks — AC4
# ===========================================================================


class TestNoSymlinks:
    def test_no_symlinks_under_lancedb_root(self, tmp_path):
        """Brief AC4: no symlinks created under ``var/arxmcp/index/lancedb/``
        by any ingest or server code. The native LanceDB layout is
        ``<lancedb_path>/<table>.lance/`` — never a symlink."""
        from ingest.store import write_chunks

        chunks = _make_corpus(3)
        embeddings = _make_synthetic_embeddings(chunks, seed=16)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        # Walk every entry under tmp_path/lancedb and assert none are
        # symlinks. Using ``rglob('*')`` includes nested files.
        for entry in (tmp_path / "lancedb").rglob("*"):
            assert not entry.is_symlink(), (
                f"unexpected symlink under LanceDB root: {entry}"
            )


# ===========================================================================
# TestDocstringContract — AC5 docstring requirement
# ===========================================================================


class TestDocstringContract:
    def test_store_docstring_states_mvcc_handshake(self):
        """Brief AC5: the module docstring in ``ingest/store.py`` must
        state: 'No symlink swaps. LanceDB version int IS the
        corpus_version. Writers use the current dataset; readers call
        dataset.checkout(version=N).'

        Whitespace-collapsed substring match so the sentence can wrap
        across source lines without breaking the test.
        """
        import ingest.store as store_mod

        doc = store_mod.__doc__ or ""
        doc_collapsed = " ".join(doc.split())
        required = (
            "No symlink swaps. LanceDB version int IS the corpus_version. "
            "Writers use the current dataset; readers call "
            "dataset.checkout(version=N)."
        )
        assert required in doc_collapsed, (
            "ingest/store.py docstring must contain the AC5 MVCC handshake sentence"
        )


# ===========================================================================
# TestSingleSourceOfTruth — CHUNKS_TABLE_NAME imported, not redefined
# ===========================================================================


class TestSingleSourceOfTruth:
    def test_corpus_imports_table_name_does_not_redefine(self):
        """``server/corpus.py`` must reference the table by importing
        ``CHUNKS_TABLE_NAME`` from ``ingest.schema`` — never via the
        bare string literal ``"chunks"``. Mirrors the BGE_M3_COMMIT_SHA
        single-source-of-truth scan from ``test_query_encoder.py``.
        """
        repo_root = Path(__file__).parent.parent
        corpus_text = (repo_root / "server" / "corpus.py").read_text(encoding="utf-8")
        # The string literal "chunks" (with quotes) must not appear.
        # The import line ``from ingest.schema import CHUNKS_TABLE_NAME``
        # is the only allowed reference.
        assert '"chunks"' not in corpus_text, (
            'server/corpus.py must not contain the literal "chunks"; '
            "import CHUNKS_TABLE_NAME from ingest.schema instead"
        )
        assert "'chunks'" not in corpus_text, (
            "server/corpus.py must not contain the literal 'chunks'; "
            "import CHUNKS_TABLE_NAME from ingest.schema instead"
        )

    def test_corpus_table_name_resolves_to_schema_constant(self):
        """Object-identity check that ``CHUNKS_TABLE_NAME`` referenced
        in ``server.corpus`` is the SAME object as in ``ingest.schema``.
        """
        import ingest.schema
        import server.corpus

        # server.corpus imports the symbol; verify it's the same object.
        assert server.corpus.CHUNKS_TABLE_NAME is ingest.schema.CHUNKS_TABLE_NAME
