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
# defines them at module scope. Closes F8 from the E04_S02 critique:
# ``_make_chunk`` lives in this import block too rather than via an
# awkward ``__import__`` indirection.
from tests.test_store import (
    _make_chunk,
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
                _make_chunk(
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

        # Closes F4 from the E04_S02 critique: open BOTH handles first,
        # THEN assert. The previous ordering (open A → assert A → open
        # B → assert B) would silently pass even if opening B
        # invalidated A's view (which would happen if lancedb cached
        # a shared Connection / Table object across calls).
        tbl_a = open_chunks_table(tmp_path / "lancedb", version=v_a)
        tbl_b = open_chunks_table(tmp_path / "lancedb", version=v_b)
        assert tbl_a.count_rows() == 10, (
            f"checkout(v_a={v_a}) should return 10 rows AFTER "
            f"opening v_b; got {tbl_a.count_rows()}"
        )
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
        # Closes F6 from the E04_S02 critique: match the requested
        # version integer (a stable contract) rather than the
        # implementation-specific "not accessible" wording.
        with pytest.raises(ValueError, match="999999"):
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
        ``<lancedb_path>/<table>.lance/`` — never a symlink.

        Closes F5 from the E04_S02 critique: collect entries first
        and assert ``len > 0`` so the test fails loudly if a future
        refactor of ``write_chunks`` produces no on-disk files.
        """
        from ingest.store import write_chunks

        chunks = _make_corpus(3)
        embeddings = _make_synthetic_embeddings(chunks, seed=16)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        entries = list((tmp_path / "lancedb").rglob("*"))
        assert len(entries) > 0, (
            "LanceDB root contains zero entries after write_chunks; "
            "the symlink check would pass vacuously"
        )
        # Walk every entry and assert none are symlinks.
        for entry in entries:
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

    def test_corpus_imports_default_path_from_store(self):
        """Closes F3 from the E04_S02 critique: server.corpus and
        ingest.store share the same ``DEFAULT_LANCEDB_PATH`` constant.
        Asymmetric defaults would force every reader to hard-code the
        path."""
        import ingest.store
        import server.corpus

        assert (
            server.corpus.DEFAULT_LANCEDB_PATH
            is ingest.store.DEFAULT_LANCEDB_PATH
        )

    def test_corpus_docstring_states_mvcc_handshake(self):
        """Closes F16 from the E04_S02 critique: extend the docstring
        contract scan to cover ``server.corpus`` too. The verbatim AC5
        sentence MUST appear in both the writer (ingest.store) and
        the reader (server.corpus) — drift in either direction would
        be silent without this test."""
        import server.corpus as corpus_mod

        doc = corpus_mod.__doc__ or ""
        doc_collapsed = " ".join(doc.split())
        required = (
            "No symlink swaps. LanceDB version int IS the corpus_version. "
            "Writers use the current dataset; readers call "
            "dataset.checkout(version=N)."
        )
        assert required in doc_collapsed, (
            "server/corpus.py docstring must contain the AC5 MVCC handshake "
            "sentence so doc-drift between reader and writer is regression-locked"
        )


# ===========================================================================
# TestHandleIndependence — F1: two pinned handles must not stamp on each other
# ===========================================================================


class TestHandleIndependence:
    def test_two_handles_with_different_versions_are_independent(self, tmp_path):
        """Closes F1 from the E04_S02 critique: opening one handle at
        v_a and another at v_b, then asserting both still report their
        own pinned counts. This locks the docstring claim that each
        ``open_chunks_table`` call returns a fresh handle.

        If LanceDB ever changes its connection-caching behavior such
        that the second ``checkout(v_b)`` mutates the first handle,
        this test catches it.
        """
        from ingest.store import write_chunks

        first_batch = _make_corpus(7)
        first_emb = _make_synthetic_embeddings(first_batch, seed=21)
        v_a = write_chunks(
            first_batch, first_emb, lancedb_path=tmp_path / "lancedb"
        )
        new_chunks = [
            _make_chunk(
                f"2307.0040{i}", "stmt", f"new {i}", suffix=f"hi{i:014x}"
            )
            for i in range(4)
        ]
        second_batch = first_batch + new_chunks
        second_emb = _make_synthetic_embeddings(second_batch, seed=22)
        v_b = write_chunks(
            second_batch, second_emb, lancedb_path=tmp_path / "lancedb"
        )

        # Open BOTH handles, then verify each maintains its own pin.
        tbl_a = open_chunks_table(tmp_path / "lancedb", version=v_a)
        tbl_b = open_chunks_table(tmp_path / "lancedb", version=v_b)
        # Object identity: distinct Connection objects should produce
        # distinct Table objects.
        assert tbl_a is not tbl_b
        # Each handle reports its own pinned version.
        assert tbl_a.version == v_a
        assert tbl_b.version == v_b
        # And its own row count.
        assert tbl_a.count_rows() == 7
        assert tbl_b.count_rows() == 11

        # And — the F1 stress: opening tbl_b did NOT mutate tbl_a's view.
        # Re-read tbl_a's count after tbl_b was created.
        assert tbl_a.count_rows() == 7
        assert tbl_a.version == v_a


# ===========================================================================
# TestNoneVsLatestEquivalence — F10: version=None and version=<live> agree
# ===========================================================================


class TestNoneVsLatestEquivalence:
    def test_checkout_at_live_tip_equals_checkout_none(self, tmp_path):
        """Closes F10 from the E04_S02 critique: ``version=None`` skips
        the ``checkout`` call, while ``version=<live>`` invokes it.
        These should produce semantically equivalent handles in
        lancedb 0.30.x; lock the equivalence so a future LanceDB
        change to ``checkout`` semantics surfaces here.
        """
        from ingest.store import write_chunks

        chunks = _make_corpus(4)
        embeddings = _make_synthetic_embeddings(chunks, seed=23)
        v = write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        tbl_none = open_chunks_table(tmp_path / "lancedb", version=None)
        tbl_explicit = open_chunks_table(tmp_path / "lancedb", version=v)
        assert tbl_none.count_rows() == tbl_explicit.count_rows() == 4
        assert tbl_none.version == tbl_explicit.version == v


# ===========================================================================
# TestNarrowExceptionCatch — F2: OSError / RuntimeError must propagate
# ===========================================================================


class TestNarrowExceptionCatch:
    def test_oserror_propagates_unchanged(self, tmp_path, monkeypatch):
        """Closes F2 from the E04_S02 critique: if ``checkout`` raises
        an OSError (disk full / permission denied / file vanished),
        ``open_chunks_table`` MUST propagate it unchanged rather than
        masking it as ``ValueError("version not accessible")``. Triage
        clarity matters under failure conditions.

        Patches the concrete ``LanceTable.checkout`` (the lancedb 0.30
        subclass returned by ``connect`` + ``open_table``) so the
        OSError surfaces from inside the function under test.
        """
        from ingest.store import write_chunks

        chunks = _make_corpus(2)
        embeddings = _make_synthetic_embeddings(chunks, seed=24)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")

        # The concrete Table subclass in local mode is LanceTable;
        # patch its ``checkout`` directly so the override is hit.
        from lancedb.table import LanceTable

        def _raising_checkout(self, version):
            raise OSError("simulated disk full")

        monkeypatch.setattr(LanceTable, "checkout", _raising_checkout)
        with pytest.raises(OSError, match="disk full"):
            open_chunks_table(tmp_path / "lancedb", version=2)

    def test_runtimeerror_propagates_unchanged(self, tmp_path, monkeypatch):
        """Companion to the OSError test: a LanceDB-internal
        RuntimeError (e.g. corruption, panic) must also propagate
        unchanged rather than being masked as a generic
        version-not-accessible ValueError."""
        from lancedb.table import LanceTable

        from ingest.store import write_chunks

        chunks = _make_corpus(2)
        embeddings = _make_synthetic_embeddings(chunks, seed=25)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")

        def _raising_checkout(self, version):
            raise RuntimeError("simulated lance panic")

        monkeypatch.setattr(LanceTable, "checkout", _raising_checkout)
        with pytest.raises(RuntimeError, match="lance panic"):
            open_chunks_table(tmp_path / "lancedb", version=2)
