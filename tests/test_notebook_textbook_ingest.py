"""Tests for the notebook_textbook_ingest driver (textbook-ingest-m12).

The driver embeds m7 textbook chunks and writes them into a notebook's
LanceDB so they are retrievable via search_papers. These tests run
MODEL-FREE: a synthetic encoder is injected so no BGE-M3 download occurs
(m12 FM-5). The payoff guard (TestIngestTextbookPaper::test_textbook_chunk_
is_dense_retrievable_with_source_kind_filter) writes via the real driver
path to a real tmp LanceDB and asserts the textbook chunk returns under the
e4 dense + source_kind pre-filter — the same retrieval mechanism
search_papers uses for a notebook (notebook-retrieval-m2 routing is proven
separately in tests/test_search_notebook_routing.py).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from ingest.chunker_types import ChunkRecord
from ingest.embedder import EMBEDDING_DIM
from ingest.schema import CHUNKS_TABLE_NAME
from ingest.textbook_chunker import TEXTBOOK_CHUNKER_VERSION
from tools import notebook_textbook_ingest as driver

_SLUG = "sv-book"


def _synthetic_encoder(seed: int = 0):
    """Return an _encode_batch-shaped callable producing deterministic,
    L2-normalized vectors — so EmbedRecord.__post_init__ (atol 1e-3) passes
    and no model is loaded."""
    rng = np.random.default_rng(seed)

    def _encode(texts: list[str], chunk_ids: list[str] | None = None) -> tuple[Any, int]:
        v = rng.standard_normal((len(texts), EMBEDDING_DIM)).astype(np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        return v, 0

    return _encode


def _textbook_chunk(
    *, suffix: str, kind: str = "definition",
    body_text: str = "A scheme is a locally ringed space.",
    license_token: str = "author-distributed",
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"textbook:{_SLUG}:{suffix}",
        paper_id=f"textbook:{_SLUG}",
        kind=kind,
        section_path=["Chapter 1", "1.1 Affine schemes"],
        theorem_name=None,
        theorem_label=None,
        body_text=body_text,
        body_tokens=" ".join(body_text.lower().split()) or "tok",
        preamble_ref=None,
        chunker_version=TEXTBOOK_CHUNKER_VERSION,
        source_kind="textbook",
        license=license_token,
        chapter="Chapter 1: Schemes",
        page_start=1,
        page_end=10,
        textbook_slug=_SLUG,
        parser_used="mineru+latexml",
    )


# ---------------------------------------------------------------------------
# _build_embed_record — the embed seam (model-free via synthetic encoder)
# ---------------------------------------------------------------------------


class TestBuildEmbedRecord:
    def test_stmt_and_proof_route_to_distinct_columns(self) -> None:
        """m12 FM-1 guard (unit level): a proof chunk lands in the proof
        column, all other kinds in the stmt column. The routing rule is the
        single imported source — this pins that the driver applies it."""
        stmt = _textbook_chunk(suffix="a" * 16, kind="definition")
        proof = _textbook_chunk(suffix="b" * 16, kind="proof")
        rec = driver._build_embed_record(
            [stmt, proof], encoder=_synthetic_encoder(seed=1),
        )
        assert rec.chunk_ids_stmt == [stmt.chunk_id]
        assert rec.chunk_ids_proof == [proof.chunk_id]
        assert rec.embedding_stmt.shape == (1, EMBEDDING_DIM)
        assert rec.embedding_proof.shape == (1, EMBEDDING_DIM)

    def test_embedder_version_stamped(self) -> None:
        from ingest.embedder import EMBEDDER_VERSION

        rec = driver._build_embed_record(
            [_textbook_chunk(suffix="c" * 16)], encoder=_synthetic_encoder(),
        )
        assert rec.embedder_version == EMBEDDER_VERSION

    def test_empty_chunks_returns_empty_record(self) -> None:
        rec = driver._build_embed_record([], encoder=_synthetic_encoder())
        assert rec.chunk_ids_stmt == []
        assert rec.chunk_ids_proof == []
        assert rec.embedding_stmt.shape == (0, EMBEDDING_DIM)

    def test_all_vectors_l2_normalized(self) -> None:
        """EmbedRecord.__post_init__ would raise if not — this pins that the
        synthetic + real paths both produce unit vectors the store accepts."""
        rec = driver._build_embed_record(
            [_textbook_chunk(suffix=f"{i:016x}") for i in range(5)],
            encoder=_synthetic_encoder(seed=2),
        )
        norms = np.linalg.norm(rec.embedding_stmt, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-3)


# ---------------------------------------------------------------------------
# ingest_textbook_paper — chunk -> embed -> write the notebook LanceDB
# ---------------------------------------------------------------------------


class TestIngestTextbookPaper:
    @pytest.fixture
    def wired(self, tmp_path, monkeypatch):
        """Point notebook_lancedb_path at a tmp dir and stub chunk_textbook to
        return synthetic textbook chunks. write_chunks stays REAL (writes a
        real tmp LanceDB). Returns the tmp notebook lancedb path + a spy
        capturing the lancedb_path write_chunks received (FM-3)."""
        nb_lancedb = tmp_path / "notebooks" / _SLUG / "lancedb"
        monkeypatch.setattr(
            driver, "notebook_lancedb_path", lambda slug: nb_lancedb,
        )

        chunks = [
            _textbook_chunk(suffix="d" * 16, kind="definition",
                            body_text="An affine scheme is Spec of a ring."),
            _textbook_chunk(suffix="e" * 16, kind="proof",
                            body_text="Proof: by the universal property."),
        ]
        monkeypatch.setattr(driver, "chunk_textbook", lambda slug, pid: list(chunks))

        captured: dict[str, Any] = {}
        real_write = driver.write_chunks

        def _spy_write(chs, embeddings, *, lancedb_path=None):
            captured["lancedb_path"] = lancedb_path
            return real_write(chs, embeddings, lancedb_path=lancedb_path)

        monkeypatch.setattr(driver, "write_chunks", _spy_write)
        return {"nb_lancedb": nb_lancedb, "captured": captured, "chunks": chunks}

    def _open(self, lancedb_path):
        import lancedb

        db = lancedb.connect(str(lancedb_path))
        return db.open_table(CHUNKS_TABLE_NAME)

    def test_writes_textbook_chunks_to_notebook_lancedb(self, wired) -> None:
        result = driver.ingest_textbook_paper(
            _SLUG, f"textbook:{_SLUG}", encoder=_synthetic_encoder(seed=3),
        )
        assert result["chunks"] == 2
        assert result["lancedb_version"] is not None
        tbl = self._open(wired["nb_lancedb"])
        rows = tbl.to_arrow().to_pylist()
        kinds = {r["source_kind"] for r in rows}
        assert kinds == {"textbook"}
        assert all(r["chunk_id"].startswith("textbook:") for r in rows)

    def test_write_targets_notebook_path_not_global_corpus(self, wired) -> None:
        """m12 FM-3: write_chunks MUST receive the per-notebook lancedb path,
        never the global DEFAULT_LANCEDB_PATH (corpus pollution)."""
        from ingest.store import DEFAULT_LANCEDB_PATH

        driver.ingest_textbook_paper(
            _SLUG, f"textbook:{_SLUG}", encoder=_synthetic_encoder(seed=3),
        )
        assert wired["captured"]["lancedb_path"] == wired["nb_lancedb"]
        assert wired["captured"]["lancedb_path"] != DEFAULT_LANCEDB_PATH

    def test_textbook_chunk_is_dense_retrievable_with_source_kind_filter(
        self, wired,
    ) -> None:
        """THE e4-demo guard: a textbook chunk written via the driver path is
        returned by the dense + source_kind='textbook' pre-filter — the
        retrieval mechanism search_papers uses against a notebook. The
        definition (stmt-routed) chunk lives in embedding_stmt, which is the
        dense column search_papers queries."""
        driver.ingest_textbook_paper(
            _SLUG, f"textbook:{_SLUG}", encoder=_synthetic_encoder(seed=3),
        )
        tbl = self._open(wired["nb_lancedb"])
        qv = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        rows = (
            tbl.search(qv, vector_column_name="embedding_stmt")
            .where("source_kind = 'textbook'", prefilter=True)
            .limit(10)
            .to_arrow()
        )
        sks = rows.column("source_kind").to_pylist()
        cids = rows.column("chunk_id").to_pylist()
        assert sks, "expected at least one textbook chunk from the dense path"
        assert set(sks) == {"textbook"}
        assert f"textbook:{_SLUG}:" + "d" * 16 in cids  # the definition chunk

    def test_idempotent_rerun_no_duplicates(self, wired) -> None:
        """write_chunks merge_insert(chunk_id) → re-running is a no-op upsert."""
        pid = f"textbook:{_SLUG}"
        driver.ingest_textbook_paper(_SLUG, pid, encoder=_synthetic_encoder(seed=3))
        n1 = self._open(wired["nb_lancedb"]).count_rows()
        driver.ingest_textbook_paper(_SLUG, pid, encoder=_synthetic_encoder(seed=4))
        n2 = self._open(wired["nb_lancedb"]).count_rows()
        assert n1 == n2 == 2

    def test_dry_run_skips_write(self, tmp_path, monkeypatch) -> None:
        nb_lancedb = tmp_path / "nb" / "lancedb"
        monkeypatch.setattr(driver, "notebook_lancedb_path", lambda slug: nb_lancedb)
        monkeypatch.setattr(
            driver, "chunk_textbook",
            lambda slug, pid: [_textbook_chunk(suffix="f" * 16)],
        )
        result = driver.ingest_textbook_paper(_SLUG, f"textbook:{_SLUG}", dry_run=True)
        assert result["chunks"] == 1
        assert result["lancedb_version"] is None
        assert not nb_lancedb.exists()  # nothing written


# ---------------------------------------------------------------------------
# run() exit codes
# ---------------------------------------------------------------------------


class TestRunExitCodes:
    def test_no_paper_ids_exit_2(self) -> None:
        assert driver.run(_SLUG, []) == 2

    def test_missing_chunks_exit_1(self, monkeypatch) -> None:
        """chunk_textbook returns [] (missing parsed HTML) -> exit 1."""
        monkeypatch.setattr(driver, "chunk_textbook", lambda slug, pid: [])
        assert driver.run(_SLUG, [f"textbook:{_SLUG}"]) == 1

    def test_all_papers_chunked_exit_0(self, tmp_path, monkeypatch) -> None:
        nb_lancedb = tmp_path / "nb" / "lancedb"
        monkeypatch.setattr(driver, "notebook_lancedb_path", lambda slug: nb_lancedb)
        monkeypatch.setattr(
            driver, "chunk_textbook",
            lambda slug, pid: [_textbook_chunk(suffix="0" * 16)],
        )
        # Capture the real builder BEFORE patching so the override injects a
        # synthetic encoder (no model load) without recursing. run() does not
        # take an encoder arg, so this is how we keep run() model-free.
        real_build = driver._build_embed_record
        monkeypatch.setattr(
            driver, "_build_embed_record",
            lambda chunks, **kw: real_build(chunks, encoder=_synthetic_encoder(seed=9)),
        )
        assert driver.run(_SLUG, [f"textbook:{_SLUG}"]) == 0
