"""``BM25Phase`` query-side tests (E07_S01).

Brief AC mapping:

- `BM25Phase.query("étale cohomology")` non-empty <500ms
  → ``TestKnownGoodQueries``
- `BM25Phase.query("\\Spec", filters={"categories":[...]})`
  → ``TestFilters`` (reinterpreted per research-synthesis.md D2)
- Returned list length ≤ 200 → ``TestTopNCap``
- `chunk_id` values present in LanceDB table → ``TestKnownGoodQueries``
- `pytest tests/retrieval/test_bm25.py` passes → the suite itself

Plus regression-grade tests for:
- File-safety check (closes E04_S04 TODO(E07))
- Auto-build at startup (closes E04_S04 H1)
- Tokenization parity (raw query → tokenize_body → BM25)
- Concurrent reader safety
- Misaligned artifact pair rejected at load
"""

from __future__ import annotations

import asyncio
import json
import os
import pickle
import stat
from pathlib import Path

import numpy as np
import pytest
from rank_bm25 import BM25Okapi

from ingest.bm25_indexer import (
    BM25_CHUNK_IDS_NAME,
    BM25_INDEX_NAME,
    _bm25_version_dir,
    build_bm25_index,
)
from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from server.retrieval.bm25 import (
    DEFAULT_TOP_N,
    DEFERRED_FILTER_KEYS,
    SUPPORTED_FILTER_KEYS,
    BM25IndexUnavailableError,
    BM25IndexUnsafeError,
    BM25Phase,
    _assert_pickle_file_safe,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _curated_chunk(paper_id: str, suffix: str, *, body_tokens: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"arxiv:{paper_id}:{suffix:>16}",
        paper_id=paper_id,
        kind="stmt",
        section_path=[],
        theorem_name=None,
        theorem_label=None,
        body_text=body_tokens,
        body_tokens=body_tokens,
        preamble_ref=None,
        chunker_version=CHUNKER_VERSION,
    )


def _curated_corpus() -> list[ChunkRecord]:
    """Five hand-crafted target chunks + 25 decoys.

    Targets chosen to exercise:
    - LaTeX command tokens (``Spec``, ``mathrm_Pic``)
    - Unicode words (``étale``)
    - Pure prose (``Hilbert space spectral theorem``)
    - Subscript identifiers (``H_1``, ``X_a``)
    - Bare commands (``partial``, ``mathbb_Z``)
    """
    chunks: list[ChunkRecord] = [
        _curated_chunk(
            "2307.00001",
            "0" * 16,
            body_tokens="Spec mathrm_Pic algebraic curve scheme",
        ),
        _curated_chunk(
            "2307.00002",
            "1" * 16,
            body_tokens="étale cohomology Galois extension",
        ),
        _curated_chunk(
            "2307.00003",
            "2" * 16,
            body_tokens="Hilbert space spectral theorem operator",
        ),
        _curated_chunk(
            "2307.00004",
            "3" * 16,
            body_tokens="H_1 X_a fundamental group homotopy",
        ),
        _curated_chunk(
            "2307.00005",
            "4" * 16,
            body_tokens="partial mathbb_Z derivation differential",
        ),
    ]
    decoy_bodies = [
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
        "linear operator banach unitary",
        "manifold de_rham simplicial homology",
        "moduli stack groupoid descent",
        "fundamental galois extension etale",
        "sheaf coherent quasi_coherent presheaf",
        "ring ideal prime spectrum noetherian",
        "module exact sequence short exact",
        "tensor product symmetric antisymmetric",
        "lie algebra bracket structure constant",
        "chromatic polynomial graph coloring",
        "elliptic curve weierstrass equation",
        "modular form cusp form eisenstein",
        "spectral sequence filtration grading",
    ]
    for i, body in enumerate(decoy_bodies, start=10):
        chunks.append(
            _curated_chunk(
                f"2307.{i:05d}",
                f"{i:016x}",
                body_tokens=body,
            )
        )
    return chunks


def _embeddings_for(chunks: list[ChunkRecord], *, seed: int = 0) -> EmbedRecord:
    """Minimal EmbedRecord with normalized vectors so write_chunks succeeds."""
    rng = np.random.default_rng(seed)
    rows: list[np.ndarray] = []
    chunk_ids: list[str] = []
    for c in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        rows.append(v)
        chunk_ids.append(c.chunk_id)
    return EmbedRecord(
        chunk_ids_stmt=chunk_ids,
        embedding_stmt=np.stack(rows, axis=0),
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )


@pytest.fixture
def _bm25_root(tmp_path, monkeypatch) -> Path:
    """Redirect ``BM25_INDEX_ROOT`` into tmp_path so the test does
    not pollute the developer's checkout-local ``var/arxmcp/``."""
    import ingest.bm25_indexer as bm25_mod

    root = tmp_path / "bm25_root"
    monkeypatch.setattr(bm25_mod, "BM25_INDEX_ROOT", root)
    return root


@pytest.fixture
def _seeded_lancedb(tmp_path) -> tuple[Path, int]:
    """Write the curated corpus to a fresh LanceDB and return
    ``(lancedb_path, corpus_version)``."""
    chunks = _curated_corpus()
    embeddings = _embeddings_for(chunks, seed=42)
    lancedb_path = tmp_path / "lancedb"
    version = write_chunks(chunks, embeddings, lancedb_path=lancedb_path)
    return (lancedb_path, version)


@pytest.fixture
def _bm25_phase(_seeded_lancedb, _bm25_root) -> BM25Phase:
    """Build the BM25 artifact + return a loaded ``BM25Phase``.

    Synchronous helper — calls ``BM25Phase._sync_startup`` directly so
    tests don't need to spin up an event loop."""
    lancedb_path, version = _seeded_lancedb
    return BM25Phase._sync_startup(lancedb_path, version)


# ===========================================================================
# AC: BM25Phase.query("étale cohomology") non-empty <500ms
# ===========================================================================


class TestKnownGoodQueries:
    """At least 5 known-good queries, each asserting the top result
    is the expected chunk."""

    def test_etale_cohomology(self, _bm25_phase):
        candidates, warnings = _bm25_phase.query("étale cohomology")
        assert candidates, "expected non-empty candidates for 'étale cohomology'"
        top_chunk_id, _score = candidates[0]
        assert top_chunk_id == "arxiv:2307.00002:1111111111111111", (
            f"top result for 'étale cohomology' should be the étale chunk; "
            f"got {top_chunk_id}"
        )
        assert warnings == []

    def test_etale_cohomology_under_500ms(self, _bm25_phase):
        """Brief AC literal: returns a non-empty list within 500ms.

        We measure 5 calls + take the max so single-iteration jitter
        doesn't make the test flaky."""
        import time

        deadline_s = 0.500
        for _ in range(5):
            start = time.monotonic()
            candidates, _ = _bm25_phase.query("étale cohomology")
            elapsed = time.monotonic() - start
            assert candidates
            assert elapsed < deadline_s, (
                f"BM25 query exceeded {deadline_s * 1000:.0f}ms budget: "
                f"elapsed={elapsed * 1000:.1f}ms"
            )

    def test_spec_pic(self, _bm25_phase):
        candidates, _ = _bm25_phase.query("\\Spec \\mathrm{Pic}")
        assert candidates
        top_chunk_id, _ = candidates[0]
        assert top_chunk_id == "arxiv:2307.00001:0000000000000000"

    def test_hilbert_spectral(self, _bm25_phase):
        candidates, _ = _bm25_phase.query("Hilbert spectral")
        assert candidates
        top_chunk_id, _ = candidates[0]
        assert top_chunk_id == "arxiv:2307.00003:2222222222222222"

    def test_subscript_identifier(self, _bm25_phase):
        """A query with subscript notation should match the subscript
        chunk, not a decoy that happens to share words."""
        candidates, _ = _bm25_phase.query("H_1 fundamental group")
        assert candidates
        top_chunk_id, _ = candidates[0]
        assert top_chunk_id == "arxiv:2307.00004:3333333333333333"

    def test_partial_mathbb(self, _bm25_phase):
        candidates, _ = _bm25_phase.query("\\partial \\mathbb{Z}")
        assert candidates
        top_chunk_id, _ = candidates[0]
        assert top_chunk_id == "arxiv:2307.00005:4444444444444444"

    def test_chunk_ids_are_valid_format(self, _bm25_phase):
        """Every returned chunk_id must match the canonical format."""
        candidates, _ = _bm25_phase.query("Spec")
        for chunk_id, _score in candidates:
            assert chunk_id.startswith("arxiv:"), (
                f"chunk_id {chunk_id!r} missing arxiv: prefix"
            )
            assert chunk_id.count(":") == 2, (
                f"chunk_id {chunk_id!r} should have 2 colons"
            )

    def test_chunk_ids_present_in_lancedb(
        self, _bm25_phase, _seeded_lancedb
    ):
        """Every returned chunk_id must exist in the LanceDB chunks
        table — closes the brief AC literally."""
        from server.corpus import open_chunks_table

        lancedb_path, version = _seeded_lancedb
        tbl = open_chunks_table(lancedb_path, version=version)
        live_ids = set(tbl.to_arrow().column("chunk_id").to_pylist())

        candidates, _ = _bm25_phase.query("Spec")
        for chunk_id, _score in candidates:
            assert chunk_id in live_ids, (
                f"BM25 returned chunk_id={chunk_id!r} not in the LanceDB table"
            )


# ===========================================================================
# AC: filters return non-empty filter_warnings; paper_id filter narrows
# ===========================================================================


class TestFilters:
    """Reinterpreted brief AC #2 per research-synthesis.md D2:
    unsupported filter keys (categories/year/authors/...) surface as
    ``filter_warnings``; the supported ``paper_id`` filter actually
    narrows results."""

    def test_categories_filter_surfaces_warning(self, _bm25_phase):
        """The literal brief AC: passing ``filters={"categories":
        ["math.AG"]}`` produces a non-empty warning (the chunks table
        has no ``categories`` column)."""
        _candidates, warnings = _bm25_phase.query(
            "\\Spec", filters={"categories": ["math.AG"]}
        )
        assert any("categories" in w for w in warnings), (
            f"expected 'categories' warning; got {warnings}"
        )

    def test_all_deferred_keys_surface_warnings(self, _bm25_phase):
        """All five deferred filter keys must each emit a distinct
        warning naming themselves."""
        _candidates, warnings = _bm25_phase.query(
            "Spec",
            filters={
                "categories": ["math.AG"],
                "year_min": 2020,
                "year_max": 2025,
                "authors": ["Grothendieck"],
                "include_withdrawn": False,
            },
        )
        # Every deferred key should appear in at least one warning.
        for key in DEFERRED_FILTER_KEYS:
            assert any(key in w for w in warnings), (
                f"expected warning for deferred filter {key!r}; got {warnings}"
            )

    def test_paper_id_filter_narrows(self, _bm25_phase):
        """``paper_id`` IS a real chunks column — the filter actually
        restricts the result set to the named paper."""
        target = "2307.00001"
        candidates, warnings = _bm25_phase.query(
            "Spec mathrm_Pic", filters={"paper_id": target}
        )
        # Warning should be empty since paper_id is supported.
        assert warnings == []
        assert candidates, "expected at least one candidate for the target paper"
        for chunk_id, _ in candidates:
            assert f"arxiv:{target}:" in chunk_id, (
                f"paper_id filter did not narrow: got chunk_id={chunk_id!r}, "
                f"expected paper_id={target!r}"
            )

    def test_paper_id_filter_accepts_list(self, _bm25_phase):
        """``paper_id`` may be a string OR a list of strings."""
        candidates, warnings = _bm25_phase.query(
            "Spec",
            filters={"paper_id": ["2307.00001", "2307.00002"]},
        )
        assert warnings == []
        for chunk_id, _ in candidates:
            assert any(
                f"arxiv:{p}:" in chunk_id
                for p in ("2307.00001", "2307.00002")
            ), f"chunk_id {chunk_id!r} not in allowed paper_id list"

    def test_unknown_filter_key_surfaces_warning(self, _bm25_phase):
        """A filter key NOT in supported NOR deferred sets surfaces a
        warning naming the legal key sets."""
        _candidates, warnings = _bm25_phase.query(
            "Spec", filters={"totally_made_up_key": "x"}
        )
        assert warnings
        assert any("totally_made_up_key" in w for w in warnings)
        assert any("unknown" in w for w in warnings)

    def test_no_filters_no_warnings(self, _bm25_phase):
        _candidates, warnings = _bm25_phase.query("Spec")
        assert warnings == []

    def test_empty_filters_dict_no_warnings(self, _bm25_phase):
        _candidates, warnings = _bm25_phase.query("Spec", filters={})
        assert warnings == []

    def test_supported_filter_keys_constant(self):
        assert "paper_id" in SUPPORTED_FILTER_KEYS

    def test_deferred_filter_keys_match_brief(self):
        assert frozenset(
            {
                "categories",
                "year_min",
                "year_max",
                "authors",
                "include_withdrawn",
            }
        ) == DEFERRED_FILTER_KEYS


# ===========================================================================
# AC: returned list length <= 200
# ===========================================================================


class TestTopNCap:
    """Brief AC: returned list length is ≤ 200."""

    def test_default_top_n_is_200(self):
        assert DEFAULT_TOP_N == 200

    def test_returned_length_at_most_top_n(self, _bm25_phase):
        candidates, _ = _bm25_phase.query("Spec", top_n=3)
        assert len(candidates) <= 3

    def test_returned_length_at_most_default_200(self, _bm25_phase):
        # Curated corpus is only 30 chunks; we still verify the cap.
        candidates, _ = _bm25_phase.query("Spec")
        assert len(candidates) <= DEFAULT_TOP_N

    def test_top_n_zero_rejected(self, _bm25_phase):
        with pytest.raises(ValueError, match="top_n must be"):
            _bm25_phase.query("Spec", top_n=0)


# ===========================================================================
# Regression: file-safety check (closes E04_S04 TODO(E07))
# ===========================================================================


@pytest.mark.skipif(
    os.name != "posix", reason="POSIX uid/mode semantics required"
)
class TestFileSafetyCheck:
    """The pickle loader MUST refuse:
    - pickles owned by a different uid (RCE attack vector)
    - world-writable pickles (attacker-controllable regardless of owner)
    """

    def test_safe_file_passes(self, _bm25_phase):
        """The artifact built by build_bm25_index in this test is
        owned by the test runner with default umask — must pass the
        check without raising."""
        _assert_pickle_file_safe(_bm25_phase.artifact_path)

    def test_world_writable_rejected(self, _bm25_phase):
        path = _bm25_phase.artifact_path
        original_mode = path.stat().st_mode
        try:
            # Add world-write bit.
            path.chmod(original_mode | stat.S_IWOTH)
            with pytest.raises(BM25IndexUnsafeError, match="world-writable"):
                _assert_pickle_file_safe(path)
        finally:
            path.chmod(original_mode)

    def test_missing_file_raises_unavailable(self, tmp_path):
        """A missing file raises ``BM25IndexUnavailableError`` (NOT
        ``BM25IndexUnsafeError``) so the caller can distinguish
        "missing" from "unsafe"."""
        with pytest.raises(BM25IndexUnavailableError, match="missing"):
            _assert_pickle_file_safe(tmp_path / "nonexistent.pkl")

    def test_unsafe_error_is_subclass_of_unavailable(self):
        """``BM25IndexUnsafeError`` MUST be a subclass of
        ``BM25IndexUnavailableError`` so a single ``except`` clause
        in ``Resources.startup`` catches both."""
        assert issubclass(BM25IndexUnsafeError, BM25IndexUnavailableError)


# ===========================================================================
# Regression: auto-build at startup (closes E04_S04 H1)
# ===========================================================================


class TestAutoBuild:
    """``BM25Phase.startup`` auto-builds the artifact if missing."""

    def test_auto_build_when_artifact_missing(
        self, _seeded_lancedb, _bm25_root
    ):
        """Fresh LanceDB + no pre-existing BM25 artifact: startup
        builds it and returns a working BM25Phase."""
        lancedb_path, version = _seeded_lancedb
        version_dir = _bm25_version_dir(version)
        # Sanity: artifact does NOT exist yet.
        assert not (version_dir / BM25_INDEX_NAME).is_file()

        phase = BM25Phase._sync_startup(lancedb_path, version)
        assert phase.corpus_size > 0
        # Post-startup: artifact exists.
        assert (version_dir / BM25_INDEX_NAME).is_file()
        assert (version_dir / BM25_CHUNK_IDS_NAME).is_file()

    def test_warm_start_uses_existing_artifact(
        self, _seeded_lancedb, _bm25_root
    ):
        """Pre-build the artifact, then call startup. The build is
        idempotent-skip; startup loads the existing pickle."""
        lancedb_path, version = _seeded_lancedb
        # Pre-build.
        build_bm25_index(lancedb_path, corpus_version=version)
        version_dir = _bm25_version_dir(version)
        pkl_mtime_before = (version_dir / BM25_INDEX_NAME).stat().st_mtime

        phase = BM25Phase._sync_startup(lancedb_path, version)
        assert phase.corpus_size > 0
        # Artifact was NOT rewritten.
        pkl_mtime_after = (version_dir / BM25_INDEX_NAME).stat().st_mtime
        assert pkl_mtime_before == pkl_mtime_after

    def test_build_failure_raises_unavailable(self, tmp_path, _bm25_root):
        """If LanceDB is missing entirely, build raises ValueError /
        FileNotFoundError, which startup wraps as
        ``BM25IndexUnavailableError``."""
        # Missing LanceDB path.
        with pytest.raises(BM25IndexUnavailableError):
            BM25Phase._sync_startup(tmp_path / "no_lancedb", 1)


# ===========================================================================
# Regression: tokenization parity (raw query → tokenize_body → BM25)
# ===========================================================================


class TestTokenizationParity:
    """The query MUST go through ``tokenize_body`` so it matches
    index-time tokenization. Without parity, raw ``\\Spec`` would
    miss the indexed ``Spec`` token."""

    def test_raw_latex_command_matches_indexed_token(self, _bm25_phase):
        """``\\Spec`` (raw LaTeX) must match the indexed ``Spec`` token."""
        candidates, _ = _bm25_phase.query("\\Spec")
        assert candidates
        chunk_ids = [c for c, _ in candidates]
        assert "arxiv:2307.00001:0000000000000000" in chunk_ids

    def test_raw_latex_brace_arg_matches_indexed_underscore_token(
        self, _bm25_phase
    ):
        """``\\mathrm{Pic}`` (raw LaTeX) must match indexed
        ``mathrm_Pic`` token (E02_S03 tokenizer rule)."""
        candidates, _ = _bm25_phase.query("\\mathrm{Pic}")
        assert candidates
        chunk_ids = [c for c, _ in candidates]
        assert "arxiv:2307.00001:0000000000000000" in chunk_ids

    def test_punctuation_only_query_returns_empty(self, _bm25_phase):
        """A query that tokenizes to nothing (pure punctuation) must
        return empty candidates without raising."""
        candidates, _ = _bm25_phase.query("$$$ ;;; ,,,")
        assert candidates == []


# ===========================================================================
# Regression: misaligned artifact pair rejected
# ===========================================================================


class TestArtifactIntegrity:
    """The pickle and chunk_ids.json MUST be from the same build.
    A misaligned pair would silently return wrong chunk_ids."""

    def test_misaligned_corpus_size_rejected(
        self, _seeded_lancedb, _bm25_root
    ):
        """Build a normal index, then truncate chunk_ids.json so it
        has fewer entries than the pickle. Startup must raise."""
        lancedb_path, version = _seeded_lancedb
        build_bm25_index(lancedb_path, corpus_version=version)
        version_dir = _bm25_version_dir(version)
        ids_path = version_dir / BM25_CHUNK_IDS_NAME

        # Truncate chunk_ids to half its size.
        original = json.loads(ids_path.read_text())
        truncated = original[: len(original) // 2]
        ids_path.write_text(json.dumps(truncated))

        with pytest.raises(BM25IndexUnavailableError, match="misaligned"):
            BM25Phase._sync_startup(lancedb_path, version)


# ===========================================================================
# Regression: BM25Phase return shape contract
# ===========================================================================


class TestReturnShape:
    """The brief specified ``list[tuple[str, float]]``; we extended to
    ``tuple[list[tuple[str,float]], list[str]]`` per
    research-synthesis.md D2."""

    def test_query_returns_tuple_of_two(self, _bm25_phase):
        result = _bm25_phase.query("Spec")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_list_of_tuples(self, _bm25_phase):
        candidates, _ = _bm25_phase.query("Spec")
        assert isinstance(candidates, list)
        for entry in candidates:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            chunk_id, score = entry
            assert isinstance(chunk_id, str)
            assert isinstance(score, float)

    def test_second_element_is_list_of_strings(self, _bm25_phase):
        _, warnings = _bm25_phase.query(
            "Spec", filters={"categories": ["math.AG"]}
        )
        assert isinstance(warnings, list)
        for w in warnings:
            assert isinstance(w, str)

    def test_candidates_sorted_descending_by_score(self, _bm25_phase):
        candidates, _ = _bm25_phase.query("Spec algebraic curve scheme")
        scores = [s for _, s in candidates]
        assert scores == sorted(scores, reverse=True), (
            f"candidates not sorted descending: {scores}"
        )


# ===========================================================================
# Regression: concurrent reader safety
# ===========================================================================


class TestConcurrentReaders:
    """``rank_bm25.BM25Okapi.get_scores`` is read-only after
    construction. Multiple threads must produce identical results."""

    def test_concurrent_queries_consistent(self, _bm25_phase):
        import concurrent.futures

        expected_candidates, _ = _bm25_phase.query("Spec mathrm_Pic")

        def query():
            return _bm25_phase.query("Spec mathrm_Pic")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: query(), range(32)))

        for candidates, warnings in results:
            assert candidates == expected_candidates
            assert warnings == []


# ===========================================================================
# Async startup smoke test
# ===========================================================================


class TestAsyncStartup:
    """``BM25Phase.startup`` is the production async entry point."""

    def test_async_startup_returns_phase(
        self, _seeded_lancedb, _bm25_root
    ):
        lancedb_path, version = _seeded_lancedb
        phase = asyncio.run(BM25Phase.startup(lancedb_path, version))
        assert isinstance(phase, BM25Phase)
        assert phase.corpus_version == version
        assert phase.corpus_size > 0


# ===========================================================================
# Regression: corrupt pickle raises during load (defense-in-depth)
# ===========================================================================


class TestCorruptPickleHandling:
    def test_corrupt_pickle_raises(self, _seeded_lancedb, _bm25_root):
        """A corrupted bm25.pkl must NOT silently produce a working
        BM25Phase; it must raise."""
        lancedb_path, version = _seeded_lancedb
        # Pre-build, then corrupt the pickle.
        build_bm25_index(lancedb_path, corpus_version=version)
        version_dir = _bm25_version_dir(version)
        pkl_path = version_dir / BM25_INDEX_NAME
        pkl_path.write_bytes(b"this is not a valid pickle")

        with pytest.raises((pickle.UnpicklingError, EOFError, Exception)):
            BM25Phase._sync_startup(lancedb_path, version)


# Suppress unused-import warnings for symbols kept for test infrastructure.
_ = (BM25Okapi,)
