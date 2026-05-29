"""Tests for the BM25 indexer (E04_S04).

Coverage map:
  Acceptance criterion -> test class
  ──────────────────────────────────────────────────────────────────────
  BM25 index built from non-null body_tokens         -> TestBuildIndex
  bm25.pkl + chunk_ids.json written                  -> TestBuildIndex
  Query "Spec mathrm_Pic" returns matching chunk     -> TestQueryAccuracy
  Idempotent re-run                                  -> TestIdempotency
  Module docstring states H4 remediation sentence    -> TestModuleContract
  Build time logged to bm25-stats.jsonl              -> TestStatsLogging

Plus regression tests for partial-state rebuild, empty-corpus raise,
the Threat-1 docstring deferral, and atomic-write tmp leak prevention.

Real LanceDB on tmp_path; no model load. Curated synthetic chunks
with hand-crafted ``body_tokens`` strings — the test query
"Spec mathrm_Pic" tokenizes to ``["Spec", "mathrm_Pic"]``, which
the tokenizer's actual output for ``\\mathrm{Spec}`` (=
``"mathrm_Spec"``) would NOT match. Curated body_tokens make the
test deterministic and decoupled from chunker fixture stability.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pytest

from ingest.bm25_indexer import (
    BM25_CHUNK_IDS_NAME,
    BM25_INDEX_NAME,
    BM25Stats,
    build_bm25_index,
)
from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks

# ===========================================================================
# Helpers — curated chunks with hand-crafted body_tokens
# ===========================================================================


def _curated_chunk(
    paper_id: str,
    suffix: str,
    *,
    body_tokens: str,
    kind: str = "stmt",
) -> ChunkRecord:
    """Build a ChunkRecord with the EXACT body_tokens we want indexed.

    Bypasses ``ingest.tokenizer.tokenize_body`` so the test's BM25
    query matches reliably. The brief query "Spec mathrm_Pic"
    requires a chunk whose body_tokens contains those exact tokens
    after a whitespace split.
    """
    return ChunkRecord(
        chunk_id=f"arxiv:{paper_id}:{suffix}",
        paper_id=paper_id,
        kind=kind,
        section_path=[],
        theorem_name=None,
        theorem_label=None,
        body_text=body_tokens,  # plausible body_text; not the focus here
        body_tokens=body_tokens,
        preamble_ref=None,
        chunker_version=CHUNKER_VERSION,
    )


def _curated_corpus() -> list[ChunkRecord]:
    """Return 20 chunks with deterministic body_tokens.

    Index 0 is the target chunk (contains both ``Spec`` and
    ``mathrm_Pic``). The other 19 are decoys with disjoint
    vocabulary so the BM25 query cannot accidentally match them.
    """
    chunks: list[ChunkRecord] = [
        _curated_chunk(
            "2307.00001",
            "0" * 16,
            body_tokens="Spec mathrm_Pic algebraic curve scheme",
        ),
    ]
    decoy_bodies = [
        "theorem proof lemma corollary",
        "differential geometry manifold tangent",
        "category functor natural transformation",
        "topology homology homotopy fundamental",
        "group ring field module algebra",
        "complex analysis holomorphic residue",
        "probability measure random variable",
        "graph vertex edge incidence matrix",
        "logic predicate quantifier inference",
        "optimization convex gradient lagrangian",
        "polynomial root coefficient discriminant",
        "matrix eigenvalue determinant rank",
        "sequence series convergence cauchy",
        "integral measure lebesgue borel",
        "linear operator hilbert banach",
        "manifold cohomology de_rham simplicial",
        "moduli stack groupoid descent",
        "etale fundamental galois extension",
        "sheaf coherent quasi_coherent presheaf",
    ]
    for i, body in enumerate(decoy_bodies, start=1):
        chunks.append(
            _curated_chunk(
                f"2307.{i:05d}",
                f"{i:016x}",
                body_tokens=body,
            )
        )
    return chunks


def _embeddings_for(chunks: list[ChunkRecord], *, seed: int = 0) -> EmbedRecord:
    """Build a minimal EmbedRecord with normalized vectors so write_chunks succeeds."""
    rng = np.random.default_rng(seed)
    chunk_ids_stmt: list[str] = []
    rows_stmt: list[np.ndarray] = []
    for c in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        chunk_ids_stmt.append(c.chunk_id)
        rows_stmt.append(v)
    embedding_stmt = np.stack(rows_stmt, axis=0)
    return EmbedRecord(
        chunk_ids_stmt=chunk_ids_stmt,
        embedding_stmt=embedding_stmt,
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )


# ===========================================================================
# TestModuleContract — the H4 remediation docstring sentence
# ===========================================================================


class TestModuleContract:
    def test_docstring_h4_remediation_sentence(self):
        """Brief AC: 'Module docstring states: "Standard Python BM25
        over pre-tokenized body_tokens. No Tantivy, no custom analyzer.
        See H4 remediation."'

        Whitespace-collapsed substring match so the sentence can wrap
        across source lines.
        """
        import ingest.bm25_indexer as bm25_mod

        doc = bm25_mod.__doc__ or ""
        doc_collapsed = " ".join(doc.split())
        required = (
            "Standard Python BM25 over pre-tokenized body_tokens. "
            "No Tantivy, no custom analyzer. See H4 remediation."
        )
        assert required in doc_collapsed, (
            "ingest/bm25_indexer.py docstring must contain the H4 "
            "remediation sentence verbatim per E04_S04 AC"
        )

    def test_docstring_threat1_deferral(self):
        """Mirrors the discipline from E04_S03 M2: any function
        accepting a filesystem path must carry the Threat 1 deferral
        marker."""
        from ingest.bm25_indexer import build_bm25_index

        doc = build_bm25_index.__doc__ or ""
        doc_collapsed = " ".join(doc.split())
        assert "Threat 1" in doc_collapsed
        assert "TODO(E06)" in doc_collapsed


# ===========================================================================
# TestBuildIndex — the central AC: BM25 built + files written
# ===========================================================================


class TestBuildIndex:
    def test_writes_pkl_and_chunk_ids(self, tmp_path, monkeypatch):
        """AC: bm25.pkl + chunk_ids.json are written under
        ``var/arxmcp/index/bm25/v<N>/``."""
        # Redirect BM25_INDEX_ROOT into tmp_path so we don't pollute
        # the developer's var/ tree.
        import ingest.bm25_indexer as bm25_mod

        monkeypatch.setattr(
            bm25_mod, "BM25_INDEX_ROOT", tmp_path / "bm25"
        )

        chunks = _curated_corpus()
        embeddings = _embeddings_for(chunks, seed=1)
        version = write_chunks(
            chunks, embeddings, lancedb_path=tmp_path / "lancedb"
        )
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)

        version_dir = bm25_mod._bm25_version_dir(version)
        assert (version_dir / BM25_INDEX_NAME).is_file()
        assert (version_dir / BM25_CHUNK_IDS_NAME).is_file()

    def test_chunk_ids_json_is_aligned_with_bm25_corpus(
        self, tmp_path, monkeypatch
    ):
        """The chunk_ids.json list is row-aligned with the BM25
        corpus stored in bm25.pkl. Loading both back must produce
        equal-length sequences."""
        import ingest.bm25_indexer as bm25_mod

        monkeypatch.setattr(
            bm25_mod, "BM25_INDEX_ROOT", tmp_path / "bm25"
        )

        chunks = _curated_corpus()
        embeddings = _embeddings_for(chunks, seed=2)
        version = write_chunks(
            chunks, embeddings, lancedb_path=tmp_path / "lancedb"
        )
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)

        version_dir = bm25_mod._bm25_version_dir(version)
        with (version_dir / BM25_INDEX_NAME).open("rb") as fh:
            bm25 = pickle.load(fh)
        chunk_ids = json.loads(
            (version_dir / BM25_CHUNK_IDS_NAME).read_text(encoding="utf-8")
        )
        assert len(chunk_ids) == len(chunks)
        # rank_bm25's BM25Okapi exposes corpus_size attribute.
        assert bm25.corpus_size == len(chunks)


# ===========================================================================
# TestQueryAccuracy — the brief's central AC: "Spec mathrm_Pic"
# ===========================================================================


class TestQueryAccuracy:
    def test_query_spec_mathrm_pic_returns_target_chunk(
        self, tmp_path, monkeypatch
    ):
        """AC: BM25 query over "Spec mathrm_Pic" returns the chunk
        containing those tokens with the highest score."""
        import ingest.bm25_indexer as bm25_mod

        monkeypatch.setattr(
            bm25_mod, "BM25_INDEX_ROOT", tmp_path / "bm25"
        )

        chunks = _curated_corpus()
        embeddings = _embeddings_for(chunks, seed=3)
        target_chunk_id = chunks[0].chunk_id  # the Spec mathrm_Pic chunk
        version = write_chunks(
            chunks, embeddings, lancedb_path=tmp_path / "lancedb"
        )
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)

        version_dir = bm25_mod._bm25_version_dir(version)
        with (version_dir / BM25_INDEX_NAME).open("rb") as fh:
            bm25 = pickle.load(fh)
        chunk_ids = json.loads(
            (version_dir / BM25_CHUNK_IDS_NAME).read_text(encoding="utf-8")
        )

        # The query splits on whitespace into ["Spec", "mathrm_Pic"]
        # and BM25 returns one float score per corpus document.
        scores = bm25.get_scores(["Spec", "mathrm_Pic"])
        top_idx = int(scores.argmax())
        top_chunk_id = chunk_ids[top_idx]

        assert top_chunk_id == target_chunk_id, (
            f"expected target {target_chunk_id} as top result; got "
            f"{top_chunk_id} (top-3 scores: {sorted(scores.tolist(), reverse=True)[:3]})"
        )

    def test_query_disjoint_vocabulary_does_not_match_target(
        self, tmp_path, monkeypatch
    ):
        """M4 fix: a query whose tokens appear in a SPECIFIC decoy
        chunk must rank that decoy top-1. The previous version asserted
        only ``top != target`` which is satisfied by any ranking
        permutation of the 19 decoys — a bug where the index returns
        a constant non-zero index would still pass.

        Index 16 is the ``"manifold cohomology de_rham simplicial"``
        decoy (chunks[0] is the target, then decoy_bodies starts at
        i=1, so decoy_bodies[15] lands at chunks[16]). The query
        ``["manifold", "cohomology"]`` shares two tokens with
        chunks[16] and one token (``manifold``) with chunks[2]
        (``"differential geometry manifold tangent"``). chunks[16]
        wins because it has TF=2 for the query terms vs chunks[2]'s
        TF=1.
        """
        import ingest.bm25_indexer as bm25_mod

        monkeypatch.setattr(
            bm25_mod, "BM25_INDEX_ROOT", tmp_path / "bm25"
        )

        chunks = _curated_corpus()
        embeddings = _embeddings_for(chunks, seed=4)
        target_chunk_id = chunks[0].chunk_id
        cohomology_decoy_chunk_id = chunks[16].chunk_id
        version = write_chunks(
            chunks, embeddings, lancedb_path=tmp_path / "lancedb"
        )
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)

        version_dir = bm25_mod._bm25_version_dir(version)
        with (version_dir / BM25_INDEX_NAME).open("rb") as fh:
            bm25 = pickle.load(fh)
        chunk_ids = json.loads(
            (version_dir / BM25_CHUNK_IDS_NAME).read_text(encoding="utf-8")
        )

        # "manifold cohomology" appears ONLY in chunks[15]. The cohomology
        # decoy MUST rank top-1; the target MUST NOT.
        scores = bm25.get_scores(["manifold", "cohomology"])
        top_idx = int(scores.argmax())
        assert chunk_ids[top_idx] == cohomology_decoy_chunk_id, (
            f"expected cohomology decoy {cohomology_decoy_chunk_id} as "
            f"top result for ['manifold', 'cohomology']; got "
            f"{chunk_ids[top_idx]}"
        )
        assert chunk_ids[top_idx] != target_chunk_id


# ===========================================================================
# TestIdempotency — re-run is a no-op when both files exist
# ===========================================================================


class TestIdempotency:
    def test_rerun_is_skipped_when_files_exist(self, tmp_path, monkeypatch):
        import ingest.bm25_indexer as bm25_mod

        monkeypatch.setattr(
            bm25_mod, "BM25_INDEX_ROOT", tmp_path / "bm25"
        )

        chunks = _curated_corpus()
        embeddings = _embeddings_for(chunks, seed=5)
        version = write_chunks(
            chunks, embeddings, lancedb_path=tmp_path / "lancedb"
        )
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)

        version_dir = bm25_mod._bm25_version_dir(version)
        pkl_path = version_dir / BM25_INDEX_NAME
        ids_path = version_dir / BM25_CHUNK_IDS_NAME
        # Capture mtimes; a no-op re-run leaves them untouched.
        mtime_pkl = pkl_path.stat().st_mtime_ns
        mtime_ids = ids_path.stat().st_mtime_ns

        # Second call should be a no-op.
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)
        assert pkl_path.stat().st_mtime_ns == mtime_pkl
        assert ids_path.stat().st_mtime_ns == mtime_ids

    def test_partial_state_triggers_rebuild(self, tmp_path, monkeypatch):
        """If only one of the two files exists (partial write from a
        prior crash), the next run rebuilds rather than honoring the
        partial state.

        L2 fix: compare ``st_ino`` rather than ``st_mtime_ns`` to
        detect the atomic-replace. ``os.replace(tmp, dst)`` produces a
        new inode on the same filesystem regardless of whether the
        kernel updated mtime within the test's wall-clock window. The
        previous mtime-based assertion required a ``time.sleep(0.01)``
        before the rebuild, which was racy on filesystems with
        coarse-grained mtime (e.g. APFS often rounds to seconds for
        replace-induced writes).
        """
        import ingest.bm25_indexer as bm25_mod

        monkeypatch.setattr(
            bm25_mod, "BM25_INDEX_ROOT", tmp_path / "bm25"
        )

        chunks = _curated_corpus()
        embeddings = _embeddings_for(chunks, seed=6)
        version = write_chunks(
            chunks, embeddings, lancedb_path=tmp_path / "lancedb"
        )
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)

        version_dir = bm25_mod._bm25_version_dir(version)
        pkl_path = version_dir / BM25_INDEX_NAME
        ids_path = version_dir / BM25_CHUNK_IDS_NAME

        # Delete chunk_ids.json — simulate a partial-write crash.
        ids_path.unlink()
        # Capture pkl inode — should change after rebuild because
        # ``os.replace`` swaps the inode rather than truncating in
        # place.
        ino_pkl_before = pkl_path.stat().st_ino

        # Re-run rebuilds because not BOTH files are present.
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)
        assert ids_path.is_file()  # restored
        # The pkl was atomically replaced — different inode.
        assert pkl_path.stat().st_ino != ino_pkl_before


# ===========================================================================
# TestEmptyCorpus — zero non-null body_tokens raises
# ===========================================================================


class TestEmptyCorpus:
    def test_empty_corpus_raises_value_error(self, tmp_path, monkeypatch):
        """An empty BM25 corpus produces NaN IDFs (rank_bm25). Surface
        explicitly as a ValueError rather than writing a useless
        index."""
        import ingest.bm25_indexer as bm25_mod

        monkeypatch.setattr(
            bm25_mod, "BM25_INDEX_ROOT", tmp_path / "bm25"
        )

        # Build an empty LanceDB table by writing zero chunks.
        embeddings = EmbedRecord(
            chunk_ids_stmt=[],
            embedding_stmt=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
            chunk_ids_proof=[],
            embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
            embedder_version=EMBEDDER_VERSION,
        )
        # write_chunks with empty chunks is a logged no-op (returns the
        # empty-table version).
        version = write_chunks(
            [], embeddings, lancedb_path=tmp_path / "lancedb"
        )
        with pytest.raises(ValueError, match="cannot build BM25 index"):
            build_bm25_index(tmp_path / "lancedb", corpus_version=version)


# ===========================================================================
# TestStatsLogging — bm25-stats.jsonl per call
# ===========================================================================


class TestStatsLogging:
    def test_stats_line_appended_on_build(self, tmp_path, monkeypatch):
        import ingest.bm25_indexer as bm25_mod

        monkeypatch.setattr(
            bm25_mod, "BM25_INDEX_ROOT", tmp_path / "bm25"
        )

        chunks = _curated_corpus()
        embeddings = _embeddings_for(chunks, seed=7)
        version = write_chunks(
            chunks, embeddings, lancedb_path=tmp_path / "lancedb"
        )
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)

        # The autouse fixture redirected BM25_STATS_PATH into tmp_path.
        stats_path = bm25_mod.BM25_STATS_PATH
        assert stats_path.exists()
        line = stats_path.read_text(encoding="utf-8").strip()
        row = json.loads(line)
        assert row["chunk_count"] == len(chunks)
        assert row["corpus_version"] == version
        assert row["skipped"] is False
        assert isinstance(row["elapsed_s"], (int, float))
        # L4 + L5: empty_chunks_skipped + paper_count are present and
        # carry the documented values for a healthy build.
        assert row["empty_chunks_skipped"] == 0
        # _curated_corpus has 20 chunks across 20 distinct paper_ids.
        assert row["paper_count"] == len({c.paper_id for c in chunks})

    def test_stats_line_records_skipped_on_no_op_rerun(
        self, tmp_path, monkeypatch
    ):
        import ingest.bm25_indexer as bm25_mod

        monkeypatch.setattr(
            bm25_mod, "BM25_INDEX_ROOT", tmp_path / "bm25"
        )

        chunks = _curated_corpus()
        embeddings = _embeddings_for(chunks, seed=8)
        version = write_chunks(
            chunks, embeddings, lancedb_path=tmp_path / "lancedb"
        )
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)
        build_bm25_index(tmp_path / "lancedb", corpus_version=version)

        stats_path = bm25_mod.BM25_STATS_PATH
        lines = [
            json.loads(line)
            for line in stats_path.read_text(encoding="utf-8")
            .strip()
            .splitlines()
        ]
        # Two lines: first build, second skipped.
        assert len(lines) == 2
        assert lines[0]["skipped"] is False
        assert lines[1]["skipped"] is True
        assert lines[1]["chunk_count"] == 0


# ===========================================================================
# TestSingleSourceOfTruth — naming constants live in bm25_indexer.py
# ===========================================================================


class TestSingleSourceOfTruth:
    def test_constants_defined_exactly_once(self):
        """``BM25_DIR_NAME``, ``BM25_INDEX_NAME``, ``BM25_CHUNK_IDS_NAME``
        live only in ``ingest/bm25_indexer.py``."""
        repo_root = Path(__file__).parent.parent
        for name in ("BM25_DIR_NAME", "BM25_INDEX_NAME", "BM25_CHUNK_IDS_NAME"):
            hits = []
            for src_dir in ("ingest", "server"):
                for py in (repo_root / src_dir).rglob("*.py"):
                    text = py.read_text(encoding="utf-8")
                    if f"{name} = " in text:
                        hits.append(py)
            assert len(hits) == 1, (
                f"{name} must be defined exactly once; found in: {hits}"
            )
            assert hits[0].name == "bm25_indexer.py"

    def test_no_stray_v_string_literal(self):
        """The ``f"v{N}"`` per-version directory pattern lives only in
        ``_bm25_version_dir``. No other source file should construct
        the version subdir name inline."""
        # _bm25_version_dir is the sole owner of f"v{...}". A scan
        # for the literal ``f"v{`` across server/ + ingest/ should
        # only hit bm25_indexer.py.
        repo_root = Path(__file__).parent.parent
        hits = []
        for src_dir in ("ingest", "server"):
            for py in (repo_root / src_dir).rglob("*.py"):
                text = py.read_text(encoding="utf-8")
                if 'f"v{' in text:
                    hits.append(py)
        # Allow exactly one hit in bm25_indexer.py.
        assert len(hits) == 1, (
            f"f-string ``v{{N}}`` literal must be confined to "
            f"_bm25_version_dir; found in: {hits}"
        )
        assert hits[0].name == "bm25_indexer.py"


# ===========================================================================
# TestBM25StatsDataclass — to_dict alphabetical keys
# ===========================================================================


class TestBM25StatsDataclass:
    def test_to_dict_alphabetical_keys(self):
        stats = BM25Stats(
            chunk_count=20,
            corpus_version=5,
            elapsed_s=0.123,
            empty_chunks_skipped=2,
            paper_count=4,
            skipped=False,
        )
        d = stats.to_dict()
        assert list(d.keys()) == [
            "chunk_count",
            "corpus_version",
            "elapsed_s",
            "empty_chunks_skipped",
            "paper_count",
            "skipped",
        ]
        # All six fields present at their declared values.
        assert d["chunk_count"] == 20
        assert d["corpus_version"] == 5
        assert d["elapsed_s"] == 0.123
        assert d["empty_chunks_skipped"] == 2
        assert d["paper_count"] == 4
        assert d["skipped"] is False


# ===========================================================================
# TestBM25IndexRootIsolation — notebook-bm25-isolation-m1
# AC-3: two builds at the same version N with different index_root
#       resolve to non-overlapping artifact paths.
# ===========================================================================


class TestBM25IndexRootIsolation:
    """Regression: per-notebook BM25 index root isolation.

    These tests MUST FAIL on the pre-fix code (before
    ``notebook-bm25-isolation-m1``) where ``_bm25_version_dir`` always
    used the global ``BM25_INDEX_ROOT`` and ``build_bm25_index`` had no
    ``index_root`` parameter.

    Post-fix they pass because the ``index_root`` parameter makes each
    call use a different directory tree.
    """

    def test_version_dirs_differ_with_different_index_roots(self, tmp_path):
        """AC-3: ``_bm25_version_dir(N, index_root=A)`` !=
        ``_bm25_version_dir(N, index_root=B)`` when A != B.

        This is the structural guarantee that no collision can occur when
        two callers supply distinct roots for the same version integer.
        """
        import ingest.bm25_indexer as bm25_mod

        root_a = tmp_path / "notebook-a" / "index" / "bm25"
        root_b = tmp_path / "notebook-b" / "index" / "bm25"
        version = 1

        dir_a = bm25_mod._bm25_version_dir(version, index_root=root_a)
        dir_b = bm25_mod._bm25_version_dir(version, index_root=root_b)

        assert dir_a != dir_b, (
            f"Same version {version} with different index_root values "
            f"must produce different version dirs; got same: {dir_a}"
        )
        assert dir_a == root_a / f"v{version}"
        assert dir_b == root_b / f"v{version}"

    def test_build_bm25_index_per_root_no_overlap(self, tmp_path):
        """AC-3: two ``build_bm25_index`` calls at the same version N
        but with different ``index_root`` values produce artifacts in
        non-overlapping directories.

        Pre-fix this test would fail because both calls would write to
        the same global-root ``bm25/v<N>/`` directory (or whichever
        was monkeypatched), and the second call's idempotent-skip would
        silently leave the first caller's ``chunk_ids.json`` in place.

        Post-fix each call writes to its own root, so the files are
        fully separated.
        """
        import ingest.bm25_indexer as bm25_mod

        root_a = tmp_path / "nb-alpha" / "index" / "bm25"
        root_b = tmp_path / "nb-beta" / "index" / "bm25"

        # Build two tiny corpora with DIFFERENT chunk_ids so we can
        # verify each root got its own artifact.
        lancedb_a = tmp_path / "lancedb_a"
        lancedb_b = tmp_path / "lancedb_b"

        chunks_a = [_curated_chunk("2301.00001", "aaaa0001", body_tokens="alpha theorem lemma")]
        embeds_a = _embeddings_for(chunks_a, seed=1)
        version_a = write_chunks(chunks_a, embeds_a, lancedb_a)

        chunks_b = [_curated_chunk("2302.00002", "bbbb0002", body_tokens="beta corollary proof")]
        embeds_b = _embeddings_for(chunks_b, seed=2)
        version_b = write_chunks(chunks_b, embeds_b, lancedb_b)

        # Both notebooks land at version 1 (per-dataset MVCC starts at 1).
        if version_a != version_b != 1:
            pytest.skip("Unexpected version numbers; corpus setup changed")

        # Build index for notebook-A under root_a
        bm25_mod.build_bm25_index(lancedb_a, corpus_version=version_a, index_root=root_a)
        # Build index for notebook-B under root_b
        bm25_mod.build_bm25_index(lancedb_b, corpus_version=version_b, index_root=root_b)

        pkl_a = root_a / f"v{version_a}" / bm25_mod.BM25_INDEX_NAME
        ids_a = root_a / f"v{version_a}" / bm25_mod.BM25_CHUNK_IDS_NAME
        pkl_b = root_b / f"v{version_b}" / bm25_mod.BM25_INDEX_NAME
        ids_b = root_b / f"v{version_b}" / bm25_mod.BM25_CHUNK_IDS_NAME

        # Both directories exist and are independent.
        assert pkl_a.is_file(), f"Missing pkl at {pkl_a}"
        assert ids_a.is_file(), f"Missing chunk_ids at {ids_a}"
        assert pkl_b.is_file(), f"Missing pkl at {pkl_b}"
        assert ids_b.is_file(), f"Missing chunk_ids at {ids_b}"

        # The chunk_ids in each root match their respective corpora.
        import json as _json
        ids_list_a = _json.loads(ids_a.read_text())
        ids_list_b = _json.loads(ids_b.read_text())
        assert ids_list_a != ids_list_b, (
            "The two notebooks have different chunk_ids but got the same "
            f"chunk_ids.json — collision still present: {ids_list_a}"
        )
        assert any("2301" in cid for cid in ids_list_a), (
            f"root_a chunk_ids should contain notebook-A chunks; got {ids_list_a}"
        )
        assert any("2302" in cid for cid in ids_list_b), (
            f"root_b chunk_ids should contain notebook-B chunks; got {ids_list_b}"
        )

    def test_none_index_root_uses_monkeypatched_global(self, tmp_path, monkeypatch):
        """FM-6: when ``index_root=None`` (the default), ``_bm25_version_dir``
        reads ``BM25_INDEX_ROOT`` at call time, so the conftest autouse
        monkeypatch continues to intercept the path in tests.

        This asserts the lazy-resolution semantic that keeps ~40 existing
        tests green after the fix.
        """
        import ingest.bm25_indexer as bm25_mod

        patched_root = tmp_path / "patched_root"
        monkeypatch.setattr(bm25_mod, "BM25_INDEX_ROOT", patched_root)

        version = 3
        result = bm25_mod._bm25_version_dir(version, index_root=None)
        assert result == patched_root / f"v{version}", (
            f"index_root=None must resolve to the (patchable) "
            f"BM25_INDEX_ROOT at call time; got {result}"
        )
