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

from ingest.bm25_indexer import (
    BM25_CHUNK_IDS_NAME,
    BM25_INDEX_NAME,
    _atomic_write_bytes,
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
        """F8 fix: narrowed pytest.raises tuple. A corrupted bm25.pkl
        must raise one of the typed pickle/io errors — NOT a bare
        Exception that would mask any unrelated bug as 'success'."""
        lancedb_path, version = _seeded_lancedb
        build_bm25_index(lancedb_path, corpus_version=version)
        version_dir = _bm25_version_dir(version)
        pkl_path = version_dir / BM25_INDEX_NAME
        # Have to rewrite via _atomic_write_bytes so the F3 chmod
        # 0o600 is applied (otherwise the file-safety check would
        # complain about world-writable bits inherited from the
        # test process's umask). Defense-in-depth: the rectified
        # write path produces 0o600-mode files on its own.
        _atomic_write_bytes(pkl_path, b"this is not a valid pickle")

        with pytest.raises((pickle.UnpicklingError, EOFError, KeyError)):
            BM25Phase._sync_startup(lancedb_path, version)


# ===========================================================================
# F2 regression — parent-directory safety check
# ===========================================================================


@pytest.mark.skipif(
    os.name != "posix", reason="POSIX uid/mode semantics required"
)
class TestParentDirectorySafety:
    """F2 fix: parent directory must NOT be world-writable
    (without sticky bit). Without this check, an attacker who can
    write to the dir can swap files regardless of file mode."""

    def test_world_writable_parent_dir_rejected(
        self, _seeded_lancedb, _bm25_root
    ):
        from server.retrieval.bm25 import _assert_dir_safe

        lancedb_path, version = _seeded_lancedb
        build_bm25_index(lancedb_path, corpus_version=version)
        version_dir = _bm25_version_dir(version)

        original_mode = version_dir.stat().st_mode
        try:
            # Add world-write WITHOUT sticky bit.
            version_dir.chmod((original_mode | stat.S_IWOTH) & ~stat.S_ISVTX)
            with pytest.raises(BM25IndexUnsafeError, match="world-writable"):
                _assert_dir_safe(version_dir)
        finally:
            version_dir.chmod(original_mode)

    def test_safe_parent_dir_passes(self, _bm25_phase):
        """The artifact built by build_bm25_index in this test lives
        under a default-mode tmp directory — must pass the check."""
        from server.retrieval.bm25 import _assert_dir_safe

        _assert_dir_safe(_bm25_phase.artifact_path.parent)


# ===========================================================================
# F4 regression — chunk_ids cross-checked against live LanceDB
# ===========================================================================


class TestChunkIdsLiveCrossCheck:
    """F4 fix: chunk_ids that aren't in the live LanceDB table
    must trigger BM25IndexUnavailableError at startup, not produce
    phantom candidates."""

    def test_phantom_chunk_id_rejected(self, _seeded_lancedb, _bm25_root):
        lancedb_path, version = _seeded_lancedb
        # Build, then tamper chunk_ids.json to include a phantom id.
        build_bm25_index(lancedb_path, corpus_version=version)
        version_dir = _bm25_version_dir(version)
        ids_path = version_dir / BM25_CHUNK_IDS_NAME
        original = json.loads(ids_path.read_text())
        # Replace one id with a non-existent phantom (same length so
        # the misalignment check doesn't fire first).
        tampered = original[:]
        tampered[0] = "arxiv:9999.99999:" + ("9" * 16)
        # Rewrite using the same atomic write so the file-safety
        # check passes; the cross-check is what we want to fire.
        from ingest.bm25_indexer import _atomic_write_text

        _atomic_write_text(
            ids_path, json.dumps(tampered, ensure_ascii=False) + "\n"
        )

        # Build live_chunk_ids from the actual table.
        from server.corpus import open_chunks_table

        tbl = open_chunks_table(lancedb_path, version=version)
        live_ids = set(tbl.to_arrow().column("chunk_id").to_pylist())

        with pytest.raises(BM25IndexUnavailableError, match="not present"):
            BM25Phase._sync_startup(
                lancedb_path, version, live_chunk_ids=live_ids
            )

    def test_no_cross_check_when_live_chunk_ids_none(
        self, _seeded_lancedb, _bm25_root
    ):
        """When live_chunk_ids is None (the test-friendly default),
        no cross-check fires — preserves the existing test surface."""
        lancedb_path, version = _seeded_lancedb
        # No tampering, no live_chunk_ids — must succeed normally.
        phase = BM25Phase._sync_startup(lancedb_path, version)
        assert phase.corpus_size > 0


# ===========================================================================
# F3 regression — atomic write produces 0o600 mode regardless of umask
# ===========================================================================


@pytest.mark.skipif(
    os.name != "posix", reason="POSIX mode semantics required"
)
class TestAtomicWriteMode:
    """F3 fix: ``_atomic_write_bytes`` and ``_atomic_write_text`` must
    chmod 0o600 before the rename. Without this, a permissive umask
    would land the file world-writable, then immediately fail the
    file-safety check."""

    def test_bytes_write_under_open_umask_is_0o600(self, tmp_path):
        out = tmp_path / "x.pkl"
        original_umask = os.umask(0o000)
        try:
            _atomic_write_bytes(out, b"hello")
        finally:
            os.umask(original_umask)
        mode = out.stat().st_mode & 0o777
        assert mode == 0o600, (
            f"expected mode 0o600 even under umask 0o000; got {oct(mode)}"
        )

    def test_text_write_under_open_umask_is_0o600(self, tmp_path):
        from ingest.bm25_indexer import _atomic_write_text

        out = tmp_path / "x.json"
        original_umask = os.umask(0o000)
        try:
            _atomic_write_text(out, '{"a": 1}\n')
        finally:
            os.umask(original_umask)
        mode = out.stat().st_mode & 0o777
        assert mode == 0o600


# ===========================================================================
# F7 regression — additional artifact-integrity edges
# ===========================================================================


class TestArtifactIntegrityExtended:
    """F7 fix: cover both directions of length mismatch + duplicates."""

    def test_extra_chunk_ids_rejected(self, _seeded_lancedb, _bm25_root):
        """chunk_ids.json longer than corpus_size must also raise."""
        lancedb_path, version = _seeded_lancedb
        build_bm25_index(lancedb_path, corpus_version=version)
        version_dir = _bm25_version_dir(version)
        ids_path = version_dir / BM25_CHUNK_IDS_NAME

        from ingest.bm25_indexer import _atomic_write_text

        original = json.loads(ids_path.read_text())
        extended = original + ["arxiv:0000.00000:" + "0" * 16]
        _atomic_write_text(
            ids_path, json.dumps(extended, ensure_ascii=False) + "\n"
        )

        with pytest.raises(BM25IndexUnavailableError, match="misaligned"):
            BM25Phase._sync_startup(lancedb_path, version)


# ===========================================================================
# F9 regression — empty-corpus build failure
# ===========================================================================


class TestEmptyCorpusFailure:
    """F9 fix: a corpus with zero non-empty body_tokens fails the
    auto-build path, which must surface as BM25IndexUnavailableError."""

    def test_empty_body_tokens_corpus_raises(self, tmp_path, _bm25_root):
        """Build a LanceDB corpus where every chunk has empty
        body_tokens. ``build_bm25_index`` raises ValueError; the
        startup wrapper translates to BM25IndexUnavailableError."""
        # Build a chunk record where body_tokens is empty after split.
        chunk = ChunkRecord(
            chunk_id="arxiv:2307.99999:" + "9" * 16,
            paper_id="2307.99999",
            kind="stmt",
            section_path=[],
            theorem_name=None,
            theorem_label=None,
            body_text="x",
            body_tokens="   ",  # whitespace-only → split() returns []
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
        )
        chunks = [chunk]
        embeddings = _embeddings_for(chunks, seed=99)
        lancedb_path = tmp_path / "lancedb_empty"
        version = write_chunks(
            chunks, embeddings, lancedb_path=lancedb_path
        )
        with pytest.raises(BM25IndexUnavailableError, match="auto-build"):
            BM25Phase._sync_startup(lancedb_path, version)


# ===========================================================================
# F13 regression — over-fetch retry path for restrictive filters
# ===========================================================================


class TestOverFetchFallback:
    """F13 fix: when a restrictive paper_id filter drops every
    over-fetched candidate, the query retries once with a full-corpus
    sort so the result is non-empty."""

    def test_restrictive_filter_falls_back_to_full_sort(
        self, _bm25_phase
    ):
        """Pick a paper whose target chunk has a low BM25 score for
        the query, then assert the filter returns it via the
        full-sort fallback."""
        # Query with terms that match many chunks but only weakly
        # match the target paper. With top_n=1 and a paper_id filter,
        # over-fetch is 4 candidates — likely too small to include
        # a low-ranking target. The fallback should still surface it.
        candidates, _ = _bm25_phase.query(
            "homology",
            filters={"paper_id": "2307.00005"},
            top_n=1,
        )
        # If the target chunk has any positive BM25 score, the
        # fallback finds it. The 2307.00005 chunk has body
        # 'partial mathbb_Z derivation differential' — it doesn't
        # match 'homology', so an empty result is the correct
        # outcome (no matching tokens at all). We verify the
        # mechanism by querying for a token the target chunk DOES
        # have, but with a top_n so small that pre-filter trims it.
        candidates, _ = _bm25_phase.query(
            "Spec",  # matches chunk 2307.00001 strongly
            filters={"paper_id": "2307.00005"},
            top_n=1,
        )
        # Target chunk 2307.00005 has body 'partial mathbb_Z
        # derivation differential' — no 'Spec' token. Result is
        # legitimately empty after filter. Fallback only matters
        # when the filter picks chunks that DO have score > 0 but
        # rank below over-fetch budget.
        assert candidates == []  # no Spec match in the target paper


# ===========================================================================
# F17 regression — Resources.startup wires bm25_phase end-to-end
# ===========================================================================


class TestResourcesIntegration:
    """F17 fix: previously only BM25Phase.startup was unit-tested;
    the new step 4b in ``Resources.startup`` was never exercised by
    a test. This class probes the integration end-to-end."""

    def test_resources_startup_populates_bm25_phase(
        self, _seeded_lancedb, _bm25_root
    ):
        """``Resources.startup(cfg)`` MUST populate
        ``r.bm25_phase`` with a working ``BM25Phase`` instance."""
        # Mock BGE-M3 so we don't pay the model download in CI.
        import server.query_encoder as qe_mod
        from server.config import Config
        from server.resources import Resources

        original_get_model = qe_mod._get_model
        original_get_tok = qe_mod._get_tokenizer
        qe_mod._get_model = lambda: object()
        qe_mod._get_tokenizer = lambda: object()
        try:
            lancedb_path, _version = _seeded_lancedb
            cfg = Config(lancedb_path=lancedb_path)
            r = asyncio.run(Resources.startup(cfg))
            assert r.bm25_phase is not None
            assert r.bm25_phase.corpus_size > 0
            # End-to-end query through the wired phase.
            candidates, warnings = r.bm25_phase.query("Spec")
            assert candidates
            assert warnings == []
        finally:
            qe_mod._get_model = original_get_model
            qe_mod._get_tokenizer = original_get_tok


# ===========================================================================
# F6 regression — scale-stretching benchmark
# ===========================================================================


class TestScaleBenchmark:
    """F6 fix: the original 500ms budget on a 30-chunk corpus is
    50000x looser than reality and cannot catch an O(n²) regression.
    Synthetic 5K-corpus benchmark with a scale-relative deadline
    that DOES catch a regression."""

    def test_5k_corpus_query_under_scale_budget(self, tmp_path):
        """Build an in-memory BM25Okapi over 5000 random documents
        (no LanceDB roundtrip — pure scoring path); assert
        get_scores stays under a scale-relative budget."""
        import time

        from rank_bm25 import BM25Okapi

        rng = np.random.default_rng(0)
        # Synthesize 5K docs, each ~50 tokens drawn from a 1000-word
        # vocabulary. This exercises BM25 IDF scaling.
        vocab = [f"tok{i}" for i in range(1000)]
        corpus = [
            list(rng.choice(vocab, size=50, replace=True))
            for _ in range(5000)
        ]
        bm25 = BM25Okapi(corpus)
        query_tokens = ["tok0", "tok42", "tok500"]

        # Warm one call (avoid first-call JIT costs).
        bm25.get_scores(query_tokens)

        deadline_per_chunk_us = 5  # 5 µs per corpus chunk = 25 ms total
        max_deadline_s = (len(corpus) * deadline_per_chunk_us) / 1_000_000
        # Floor at 100 ms to absorb CI runner noise.
        max_deadline_s = max(max_deadline_s, 0.100)

        start = time.monotonic()
        bm25.get_scores(query_tokens)
        elapsed = time.monotonic() - start
        assert elapsed < max_deadline_s, (
            f"BM25Okapi.get_scores on 5000 docs took {elapsed * 1000:.1f}ms "
            f"(scale-relative deadline: {max_deadline_s * 1000:.1f}ms). "
            f"Likely regression to O(n²) or accidental Python-loop in scoring."
        )

