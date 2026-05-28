"""Per-notebook LanceDB isolation regression test.

**Spike output:** textbook-ingest-spike-3 from
``plans/textbook-ingest-roadmap.md`` Phase 3. Validates the `[MUST]`
assumption that per-notebook LanceDB isolation is the correct blast
radius for textbook chunks.

**What this test pins.** The notebook-scoped storage layout
(``var/arxmcp/notebooks/<slug>/lancedb/`` per m6) is the only blast-
radius boundary between the shared arXiv corpus and textbook chunks.
``ingest.store.write_chunks`` and ``server.corpus.open_chunks_table``
both accept an explicit ``lancedb_path`` argument; this test exercises
both APIs against two distinct paths in the same test invocation and
verifies neither writer corrupts the other dataset, neither reader
sees the other dataset's rows.

**Why this matters.** textbook-ingest-m1 widened the chunk-id regex
to accept ``textbook:<slug>`` and m2 added textbook-aware schema
columns. Both changes ride on the assumption that textbook chunks
NEVER appear in the shared arXiv ``var/arxmcp/index/lancedb/`` corpus
— they live ONLY in per-notebook LanceDB datasets. A regression that
let a textbook chunk leak into the shared corpus (e.g. via a
default-``lancedb_path`` bug) would silently corrupt the arXiv search
surface for every notebook.

Synthesis FM-7 from textbook-ingest-m2 names this as the
``source_kind``-conditional handler reading non-existent column trap
on stale-corpus rows; this test is the structural-isolation guard
that prevents the scenario from arising in the first place.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from server.corpus import open_chunks_table


def _make_arxiv_chunk() -> ChunkRecord:
    """Synthetic arXiv ChunkRecord — defaults reflect a typical
    math.AG paper writing path."""
    return ChunkRecord(
        chunk_id="arxiv:2401.00099:" + "a" * 16,
        paper_id="2401.00099",
        kind="stmt",
        section_path=["1. Introduction"],
        theorem_name=None,
        theorem_label=None,
        body_text="Let X be a smooth projective variety over k.",
        body_tokens="let x be a smooth projective variety over k",
        preamble_ref=None,
        chunker_version=CHUNKER_VERSION,
        # source_kind defaults to "arxiv"; the writer's
        # _ALLOWED_SOURCE_KINDS guard at m2 enforces this is the only
        # value an arXiv-shaped chunk should carry.
    )


def _make_textbook_chunk() -> ChunkRecord:
    """Synthetic textbook ChunkRecord — populates every m2 column
    so the round-trip assertions below cover the full surface."""
    return ChunkRecord(
        chunk_id="textbook:shimura-varieties:" + "b" * 16,
        paper_id="textbook:shimura-varieties",
        kind="definition",
        section_path=["Chapter 1", "1.1 Affine schemes"],
        theorem_name=None,
        theorem_label=None,
        body_text=(
            "A Shimura variety is a quotient of a Hermitian symmetric "
            "domain by an arithmetic group."
        ),
        body_tokens="a shimura variety is a quotient of a hermitian",
        preamble_ref=None,
        chunker_version=CHUNKER_VERSION,
        source_kind="textbook",
        license="author-distributed",
        chapter="Chapter 1",
        page_start=1,
        page_end=10,
        textbook_slug="shimura-varieties",
        parser_used="mineru+latexml",
    )


def _make_synthetic_embeddings(
    chunks: list[ChunkRecord], *, seed: int = 0
) -> EmbedRecord:
    """L2-normalized random vectors for the given chunks."""
    rng = np.random.default_rng(seed)
    stmt_ids: list[str] = []
    proof_ids: list[str] = []
    stmt_rows: list[np.ndarray] = []
    proof_rows: list[np.ndarray] = []
    for chunk in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        if chunk.kind == "proof":
            proof_ids.append(chunk.chunk_id)
            proof_rows.append(v)
        else:
            stmt_ids.append(chunk.chunk_id)
            stmt_rows.append(v)
    return EmbedRecord(
        chunk_ids_stmt=stmt_ids,
        embedding_stmt=(
            np.stack(stmt_rows, axis=0)
            if stmt_rows
            else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        ),
        chunk_ids_proof=proof_ids,
        embedding_proof=(
            np.stack(proof_rows, axis=0)
            if proof_rows
            else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        ),
        embedder_version=EMBEDDER_VERSION,
    )


class TestNotebookScopedLanceDBIsolation:
    """The `[MUST]` assumption: textbook chunks written to a notebook-
    scoped LanceDB never appear in the shared arXiv corpus, and vice
    versa.

    Each test uses its own ``tmp_path``-rooted layout (no global
    fixtures, no shared state) so a failure in one test cannot taint
    the others.
    """

    def test_textbook_chunk_does_not_leak_into_arxiv_corpus(
        self, tmp_path: Path,
    ) -> None:
        """Write an arXiv chunk to the shared arXiv corpus, then a
        textbook chunk to a notebook-scoped LanceDB. Reopen the arXiv
        corpus and assert the textbook chunk is absent.
        """
        arxiv_path = tmp_path / "arxiv-corpus" / "lancedb"
        notebook_path = (
            tmp_path / "notebooks" / "shimura-varieties" / "lancedb"
        )

        # 1. Seed the arXiv corpus with one arXiv chunk.
        arxiv_chunk = _make_arxiv_chunk()
        arxiv_embeds = _make_synthetic_embeddings([arxiv_chunk], seed=1)
        write_chunks([arxiv_chunk], arxiv_embeds, lancedb_path=arxiv_path)

        # 2. Seed the notebook-scoped LanceDB with one textbook chunk.
        textbook_chunk = _make_textbook_chunk()
        textbook_embeds = _make_synthetic_embeddings(
            [textbook_chunk], seed=2
        )
        write_chunks(
            [textbook_chunk], textbook_embeds, lancedb_path=notebook_path
        )

        # 3. Reopen the arXiv corpus and verify it contains ONLY the
        # arXiv chunk — textbook chunks must NOT have leaked.
        tbl = open_chunks_table(arxiv_path)
        assert tbl.count_rows() == 1
        rows = tbl.to_arrow().to_pylist()
        assert rows[0]["chunk_id"] == arxiv_chunk.chunk_id
        assert rows[0]["paper_id"] == "2401.00099"
        assert rows[0]["source_kind"] == "arxiv"
        # The textbook chunk's chunk_id must NOT appear here.
        assert all(
            "textbook" not in r["chunk_id"] for r in rows
        ), f"textbook chunk leaked into arXiv corpus: {rows}"

    def test_arxiv_chunk_does_not_leak_into_notebook(
        self, tmp_path: Path,
    ) -> None:
        """Mirror of the above — the notebook-scoped LanceDB contains
        ONLY its own textbook chunks; no arXiv corpus rows bleed in.
        """
        arxiv_path = tmp_path / "arxiv-corpus" / "lancedb"
        notebook_path = (
            tmp_path / "notebooks" / "shimura-varieties" / "lancedb"
        )

        arxiv_chunk = _make_arxiv_chunk()
        textbook_chunk = _make_textbook_chunk()
        write_chunks(
            [arxiv_chunk],
            _make_synthetic_embeddings([arxiv_chunk], seed=3),
            lancedb_path=arxiv_path,
        )
        write_chunks(
            [textbook_chunk],
            _make_synthetic_embeddings([textbook_chunk], seed=4),
            lancedb_path=notebook_path,
        )

        # Open the notebook-scoped LanceDB; only the textbook chunk
        # should be present.
        tbl = open_chunks_table(notebook_path)
        assert tbl.count_rows() == 1
        rows = tbl.to_arrow().to_pylist()
        assert rows[0]["chunk_id"] == textbook_chunk.chunk_id
        assert rows[0]["source_kind"] == "textbook"
        assert rows[0]["textbook_slug"] == "shimura-varieties"
        # The arXiv chunk's chunk_id must NOT appear here.
        assert all(
            r["chunk_id"] != arxiv_chunk.chunk_id for r in rows
        ), f"arXiv chunk leaked into notebook LanceDB: {rows}"

    def test_two_notebooks_do_not_share_chunks(
        self, tmp_path: Path,
    ) -> None:
        """Per-notebook isolation between TWO notebook-scoped
        LanceDBs (not just notebook-vs-arxiv). The shimura-varieties
        notebook's textbook chunks must not appear in the bridgeland-
        stability notebook's LanceDB, even though both are
        ``source_kind="textbook"`` and use the textbook prefix
        regex.
        """
        nb1_path = (
            tmp_path / "notebooks" / "shimura-varieties" / "lancedb"
        )
        nb2_path = (
            tmp_path / "notebooks" / "bridgeland-stability" / "lancedb"
        )

        nb1_chunk = ChunkRecord(
            chunk_id="textbook:shimura-varieties:" + "c" * 16,
            paper_id="textbook:shimura-varieties",
            kind="definition",
            section_path=["Ch 1"],
            theorem_name=None,
            theorem_label=None,
            body_text="Shimura body.",
            body_tokens="shimura body",
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
            source_kind="textbook",
            license="GFDL",
            textbook_slug="shimura-varieties",
            parser_used="mineru+latexml",
        )
        nb2_chunk = ChunkRecord(
            chunk_id="textbook:bridgeland-stability:" + "d" * 16,
            paper_id="textbook:bridgeland-stability",
            kind="definition",
            section_path=["Ch 1"],
            theorem_name=None,
            theorem_label=None,
            body_text="Bridgeland body.",
            body_tokens="bridgeland body",
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
            source_kind="textbook",
            license="GFDL",
            textbook_slug="bridgeland-stability",
            parser_used="mineru+latexml",
        )

        write_chunks(
            [nb1_chunk],
            _make_synthetic_embeddings([nb1_chunk], seed=5),
            lancedb_path=nb1_path,
        )
        write_chunks(
            [nb2_chunk],
            _make_synthetic_embeddings([nb2_chunk], seed=6),
            lancedb_path=nb2_path,
        )

        tbl1 = open_chunks_table(nb1_path)
        assert tbl1.count_rows() == 1
        assert tbl1.to_arrow().to_pylist()[0]["textbook_slug"] == (
            "shimura-varieties"
        )

        tbl2 = open_chunks_table(nb2_path)
        assert tbl2.count_rows() == 1
        assert tbl2.to_arrow().to_pylist()[0]["textbook_slug"] == (
            "bridgeland-stability"
        )

    def test_paths_resolve_to_distinct_on_disk_directories(
        self, tmp_path: Path,
    ) -> None:
        """The blast-radius boundary is the on-disk path. Two distinct
        ``lancedb_path`` arguments must resolve to two distinct
        directories — no symlink trickery, no canonicalization
        collisions.
        """
        arxiv_path = tmp_path / "arxiv-corpus" / "lancedb"
        notebook_path = (
            tmp_path / "notebooks" / "shimura-varieties" / "lancedb"
        )

        arxiv_chunk = _make_arxiv_chunk()
        write_chunks(
            [arxiv_chunk],
            _make_synthetic_embeddings([arxiv_chunk], seed=7),
            lancedb_path=arxiv_path,
        )
        textbook_chunk = _make_textbook_chunk()
        write_chunks(
            [textbook_chunk],
            _make_synthetic_embeddings([textbook_chunk], seed=8),
            lancedb_path=notebook_path,
        )

        # Both directories exist and are siblings, not nested.
        assert arxiv_path.is_dir()
        assert notebook_path.is_dir()
        assert arxiv_path.resolve() != notebook_path.resolve()
        # Neither path is a parent of the other.
        try:
            arxiv_path.resolve().relative_to(notebook_path.resolve())
            pytest.fail(
                "arxiv_path is nested under notebook_path; "
                "isolation boundary violated"
            )
        except ValueError:
            pass  # expected — they are siblings
        try:
            notebook_path.resolve().relative_to(arxiv_path.resolve())
            pytest.fail(
                "notebook_path is nested under arxiv_path; "
                "isolation boundary violated"
            )
        except ValueError:
            pass  # expected

    def test_default_lancedb_path_distinct_from_notebook_paths(
        self,
    ) -> None:
        """The DEFAULT_LANCEDB_PATH (used by callers that don't
        pass an explicit ``lancedb_path``) resolves to the shared
        arXiv corpus root, NOT under a notebook subtree. This pins
        the contract that an accidental
        ``write_chunks(chunks, embeddings)`` call (no explicit path)
        defaults to the shared arXiv corpus — never to a notebook
        path — so a textbook chunker bug that omits the
        ``lancedb_path`` argument would write to the arXiv corpus
        and be caught by the source_kind enum guard there (rather
        than silently land in some other notebook).
        """
        from ingest.store import DEFAULT_LANCEDB_PATH

        default_str = str(DEFAULT_LANCEDB_PATH.resolve())
        # The default path must NOT be under a notebooks subtree.
        assert "/notebooks/" not in default_str, (
            f"DEFAULT_LANCEDB_PATH {default_str!r} is under a "
            f"/notebooks/ subtree — isolation boundary violated"
        )
        # And must be under the canonical var/arxmcp/index/ tree.
        assert "var/arxmcp/index" in default_str, (
            f"DEFAULT_LANCEDB_PATH {default_str!r} is not under "
            f"var/arxmcp/index — expected the shared arXiv corpus"
        )

    def test_writing_with_arxiv_source_kind_to_textbook_path_is_allowed(
        self, tmp_path: Path,
    ) -> None:
        """The notebook-scoped storage is a BLAST-RADIUS boundary, not
        a content-discriminator boundary. An arXiv chunk CAN be written
        to a notebook-scoped LanceDB if the operator wants (e.g. a
        notebook that contains both arXiv preprints and textbook
        excerpts on the same topic). What the test fixes is the
        DIRECTION of leakage: chunks from one path don't bleed into
        another path under normal write semantics.

        This test documents the design intent: per-notebook
        ``lancedb_path`` is the leak boundary; ``source_kind`` is the
        content discriminator. They are orthogonal.
        """
        notebook_path = (
            tmp_path / "notebooks" / "mixed-notebook" / "lancedb"
        )
        arxiv_chunk = _make_arxiv_chunk()
        textbook_chunk = _make_textbook_chunk()
        chunks = [arxiv_chunk, textbook_chunk]
        write_chunks(
            chunks,
            _make_synthetic_embeddings(chunks, seed=9),
            lancedb_path=notebook_path,
        )

        tbl = open_chunks_table(notebook_path)
        assert tbl.count_rows() == 2
        rows = {r["chunk_id"]: r for r in tbl.to_arrow().to_pylist()}
        assert (
            rows[arxiv_chunk.chunk_id]["source_kind"] == "arxiv"
        )
        assert (
            rows[textbook_chunk.chunk_id]["source_kind"] == "textbook"
        )
