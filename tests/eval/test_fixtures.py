"""Tests for ``tools/validate_eval_fixtures.py`` (E05_S01).

Coverage map (synthesis §D12):

  Test                                                 Locks behavior
  ──────────────────────────────────────────────────────────────────
  test_seed_fixture_passes                             empty stub →ok
  test_default_fixture_validates                       repo's queries.json
  test_paper_id_regex_matches_chunker                  single-source-of-truth
  test_chunker_version_locked                          imported, not literal
  test_malformed_json_raises                           bad JSON
  test_missing_top_level_key_raises                    schema header
  test_wrong_chunker_version_raises                    AC-4
  test_partial_fixture_raises                          1-19 → error
  test_no_grade_3_raises                               AC-2
  test_too_few_stmt_kind_raises                        AC-7
  test_stale_chunk_id_raises                           AC-3
  test_full_valid_fixture_passes                       happy path
  test_malformed_chunk_id_raises                       D10
  test_duplicate_query_id_raises                       D11
  test_duplicate_chunk_id_within_query_raises          D11
  test_completed_fixture_no_corpus_raises              behavior matrix

Real ``var/arxmcp/corpus/chunks/`` is NOT used. All chunked-corpus
state is synthesized into ``tmp_path`` per test. The validator's
``chunks_dir`` parameter is the override hook.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest.chunker import _PAPER_ID_RE as CHUNKER_PAPER_ID_RE
from ingest.chunker_types import CHUNKER_VERSION
from tools.validate_eval_fixtures import (
    _PAPER_ID_RE,
    DEFAULT_FIXTURE_PATH,
    MIN_QUERIES_BY_KIND,
    TARGET_QUERY_COUNT,
    FixtureValidationError,
    validate,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _write_fixture(path: Path, *, queries: list, **header_overrides) -> Path:
    """Write a queries.json fixture with sensible defaults."""
    payload = {
        "schema_version": "1.0",
        "chunker_version": CHUNKER_VERSION,
        "created_at": "2026-05-08",
        "queries": queries,
    }
    payload.update(header_overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_manifest(
    chunks_dir: Path, paper_id: str, chunks: list[dict]
) -> Path:
    """Write a chunk_manifest.json mirroring ingest.chunker schema."""
    out = chunks_dir / paper_id / "chunk_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "chunker_version": CHUNKER_VERSION,
        "chunks": chunks,
        "paper_id": paper_id,
    }
    out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def _make_chunk_id(paper_id: str, suffix: str) -> str:
    """Build an ``arxiv:<paper_id>:<16-hex>`` chunk_id."""
    suffix = (suffix * 16)[:16]  # right-pad / truncate to exactly 16 hex
    return f"arxiv:{paper_id}:{suffix}"


def _make_full_corpus(chunks_dir: Path) -> dict[str, str]:
    """Synthesize a 25-paper chunked corpus.

    Returns a mapping ``chunk_id → kind`` so the test can pick chunks
    by kind when constructing the fixture. 12 stmt + 12 proof + 1
    misc; comfortably exceeds the AC-7 quota.
    """
    kind_index: dict[str, str] = {}
    for i in range(1, 26):
        paper_id = f"2307.{i:05d}"
        chunks = []
        for j, kind in enumerate(["stmt", "proof"]):
            cid = _make_chunk_id(paper_id, f"{j:x}")
            chunks.append({"chunk_id": cid, "kind": kind})
            kind_index[cid] = kind
        # one misc chunk so the manifest has variety
        cid_misc = _make_chunk_id(paper_id, "f")
        chunks.append({"chunk_id": cid_misc, "kind": "definition"})
        kind_index[cid_misc] = "definition"
        _write_manifest(chunks_dir, paper_id, chunks)
    return kind_index


def _make_full_fixture(kind_index: dict[str, str]) -> list[dict]:
    """Build 20 queries: 10 reference stmt-kind, 10 reference proof-kind.

    Each query has at least one grade-3 chunk_id. The chunk_ids are
    drawn from ``kind_index`` so they all resolve.
    """
    stmt_chunks = [cid for cid, k in kind_index.items() if k == "stmt"]
    proof_chunks = [cid for cid, k in kind_index.items() if k == "proof"]
    queries = []
    for i in range(10):
        queries.append(
            {
                "query_id": f"q{i + 1:02d}",
                "query_text": f"stmt query {i + 1}",
                "relevant_chunks": [
                    {"chunk_id": stmt_chunks[i], "relevance": 3},
                ],
            }
        )
    for i in range(10):
        queries.append(
            {
                "query_id": f"q{i + 11:02d}",
                "query_text": f"proof query {i + 11}",
                "relevant_chunks": [
                    {"chunk_id": proof_chunks[i], "relevance": 3},
                ],
            }
        )
    return queries


# ===========================================================================
# Single-source-of-truth and constant-import locks
# ===========================================================================


class TestSingleSourceOfTruth:
    def test_paper_id_regex_matches_chunker(self):
        """The validator duplicates ``_PAPER_ID_RE`` from
        ``ingest.chunker`` to avoid pulling LaTeXML deps. The pattern
        strings MUST be identical."""
        assert _PAPER_ID_RE.pattern == CHUNKER_PAPER_ID_RE.pattern

    def test_chunker_version_locked(self):
        """Default fixture's chunker_version equals the running
        constant. AC-4 by construction at ship time."""
        data = json.loads(DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))
        assert data["chunker_version"] == CHUNKER_VERSION

    def test_no_v1_literal_in_validator_source(self):
        """The string ``"v1.0"`` must not appear in the validator
        source — ``CHUNKER_VERSION`` is the only acceptable reference.
        Mirrors the E04_S04 single-source-of-truth literal scan."""
        repo_root = Path(__file__).parent.parent.parent
        validator_src = (repo_root / "tools" / "validate_eval_fixtures.py").read_text(
            encoding="utf-8"
        )
        assert '"v1.0"' not in validator_src, (
            "tools/validate_eval_fixtures.py must not literalize "
            '"v1.0" — import CHUNKER_VERSION instead'
        )


# ===========================================================================
# Seed mode (queries: [])
# ===========================================================================


class TestSeedMode:
    def test_default_fixture_validates(self, tmp_path):
        """The committed seed fixture passes in seed mode against
        an empty corpus dir. This is the cold-start dev box state."""
        result = validate(DEFAULT_FIXTURE_PATH, tmp_path)
        assert result.mode == "seed"
        assert result.query_count == 0
        assert result.chunk_manifests_found == 0
        assert any("pending" in w for w in result.warnings)

    def test_seed_with_corpus_emits_corpus_warning(self, tmp_path):
        """Seed fixture + populated corpus → warning text mentions
        the corpus chunk count so triage knows curation is the gate."""
        chunks_dir = tmp_path / "chunks"
        _make_full_corpus(chunks_dir)
        fixture = _write_fixture(tmp_path / "queries.json", queries=[])
        result = validate(fixture, chunks_dir)
        assert result.mode == "seed"
        assert result.chunk_manifests_found == 25
        assert any("25 chunked papers" in w for w in result.warnings)


# ===========================================================================
# Header / structural errors
# ===========================================================================


class TestHeaderErrors:
    def test_missing_fixture_file_raises(self, tmp_path):
        with pytest.raises(FixtureValidationError, match="does not exist"):
            validate(tmp_path / "nope.json", tmp_path)

    def test_malformed_json_raises(self, tmp_path):
        bad = tmp_path / "queries.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(FixtureValidationError, match="not valid JSON"):
            validate(bad, tmp_path)

    def test_top_level_not_object_raises(self, tmp_path):
        bad = tmp_path / "queries.json"
        bad.write_text("[]", encoding="utf-8")
        with pytest.raises(FixtureValidationError, match="must be a JSON object"):
            validate(bad, tmp_path)

    def test_missing_top_level_key_raises(self, tmp_path):
        bad = tmp_path / "queries.json"
        bad.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "chunker_version": CHUNKER_VERSION,
                    "queries": [],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(
            FixtureValidationError, match="missing required top-level keys"
        ):
            validate(bad, tmp_path)

    def test_wrong_schema_version_raises(self, tmp_path):
        fixture = _write_fixture(
            tmp_path / "queries.json", queries=[], schema_version="2.0"
        )
        with pytest.raises(
            FixtureValidationError, match="schema_version must be '1.0'"
        ):
            validate(fixture, tmp_path)

    def test_wrong_chunker_version_raises(self, tmp_path):
        fixture = _write_fixture(
            tmp_path / "queries.json", queries=[], chunker_version="v999.0"
        )
        with pytest.raises(
            FixtureValidationError,
            match="chunker_version must equal",
        ):
            validate(fixture, tmp_path)


# ===========================================================================
# Partial-fixture branch (1-19 queries)
# ===========================================================================


class TestPartialFixture:
    def test_partial_fixture_raises(self, tmp_path):
        """Even one valid query is not enough — the fixture is
        all-or-nothing."""
        partial_query = [
            {
                "query_id": "q01",
                "query_text": "Riemann-Roch theorem",
                "relevant_chunks": [
                    {
                        "chunk_id": _make_chunk_id("2307.00001", "0"),
                        "relevance": 3,
                    }
                ],
            }
        ]
        fixture = _write_fixture(tmp_path / "queries.json", queries=partial_query)
        with pytest.raises(
            FixtureValidationError, match="expected 0 .seed. or 20 .complete."
        ):
            validate(fixture, tmp_path)

    def test_19_queries_raises(self, tmp_path):
        """Off-by-one defense: 19 is partial, 20 is complete."""
        chunks_dir = tmp_path / "chunks"
        kind_index = _make_full_corpus(chunks_dir)
        full = _make_full_fixture(kind_index)
        fixture = _write_fixture(tmp_path / "queries.json", queries=full[:19])
        with pytest.raises(FixtureValidationError, match="got 19"):
            validate(fixture, chunks_dir)


# ===========================================================================
# Per-query structural errors (caught even in seed-adjacent populated states)
# ===========================================================================


class TestQueryStructure:
    def test_missing_query_id_raises(self, tmp_path):
        bad_query = [
            {
                "query_text": "Riemann-Roch",
                "relevant_chunks": [
                    {
                        "chunk_id": _make_chunk_id("2307.00001", "0"),
                        "relevance": 3,
                    }
                ],
            }
        ]
        fixture = _write_fixture(tmp_path / "queries.json", queries=bad_query)
        with pytest.raises(FixtureValidationError, match="missing required keys"):
            validate(fixture, tmp_path)

    def test_empty_query_text_raises(self, tmp_path):
        bad_query = [
            {
                "query_id": "q01",
                "query_text": "",
                "relevant_chunks": [
                    {
                        "chunk_id": _make_chunk_id("2307.00001", "0"),
                        "relevance": 3,
                    }
                ],
            }
        ]
        fixture = _write_fixture(tmp_path / "queries.json", queries=bad_query)
        with pytest.raises(
            FixtureValidationError,
            match="query_text must be a non-empty string",
        ):
            validate(fixture, tmp_path)

    def test_empty_relevant_chunks_raises(self, tmp_path):
        bad_query = [
            {
                "query_id": "q01",
                "query_text": "Riemann-Roch",
                "relevant_chunks": [],
            }
        ]
        fixture = _write_fixture(tmp_path / "queries.json", queries=bad_query)
        with pytest.raises(
            FixtureValidationError, match="relevant_chunks must be a non-empty list"
        ):
            validate(fixture, tmp_path)

    def test_malformed_chunk_id_raises(self, tmp_path):
        """D10: a typo in a curated fixture should report as malformed,
        not 'stale'."""
        bad_query = [
            {
                "query_id": "q01",
                "query_text": "Riemann-Roch",
                "relevant_chunks": [
                    {"chunk_id": "arxiv:bogus:abc", "relevance": 3}
                ],
            }
        ]
        fixture = _write_fixture(tmp_path / "queries.json", queries=bad_query)
        with pytest.raises(FixtureValidationError, match="malformed chunk_id"):
            validate(fixture, tmp_path)

    def test_relevance_out_of_range_raises(self, tmp_path):
        bad_query = [
            {
                "query_id": "q01",
                "query_text": "Riemann-Roch",
                "relevant_chunks": [
                    {
                        "chunk_id": _make_chunk_id("2307.00001", "0"),
                        "relevance": 4,
                    }
                ],
            }
        ]
        fixture = _write_fixture(tmp_path / "queries.json", queries=bad_query)
        with pytest.raises(
            FixtureValidationError, match=r"relevance must be an integer in"
        ):
            validate(fixture, tmp_path)

    def test_relevance_bool_rejected(self, tmp_path):
        """``True`` is an instance of ``int`` in Python — the validator
        explicitly excludes ``bool``."""
        bad_query = [
            {
                "query_id": "q01",
                "query_text": "Riemann-Roch",
                "relevant_chunks": [
                    {
                        "chunk_id": _make_chunk_id("2307.00001", "0"),
                        "relevance": True,
                    }
                ],
            }
        ]
        fixture = _write_fixture(tmp_path / "queries.json", queries=bad_query)
        with pytest.raises(
            FixtureValidationError, match=r"relevance must be an integer"
        ):
            validate(fixture, tmp_path)

    def test_duplicate_chunk_id_within_query_raises(self, tmp_path):
        cid = _make_chunk_id("2307.00001", "0")
        bad_query = [
            {
                "query_id": "q01",
                "query_text": "Riemann-Roch",
                "relevant_chunks": [
                    {"chunk_id": cid, "relevance": 3},
                    {"chunk_id": cid, "relevance": 1},
                ],
            }
        ]
        fixture = _write_fixture(tmp_path / "queries.json", queries=bad_query)
        with pytest.raises(FixtureValidationError, match="duplicate chunk_id"):
            validate(fixture, tmp_path)


# ===========================================================================
# Full-fixture (count == 20) branch — corpus-mode invariants
# ===========================================================================


class TestCompleteFixtureBranch:
    def test_full_valid_fixture_passes(self, tmp_path):
        """Happy path: 20 queries × valid chunk_ids × ≥ 1 grade-3 each
        × kind quotas met → ok."""
        chunks_dir = tmp_path / "chunks"
        kind_index = _make_full_corpus(chunks_dir)
        full = _make_full_fixture(kind_index)
        fixture = _write_fixture(tmp_path / "queries.json", queries=full)

        result = validate(fixture, chunks_dir)
        assert result.mode == "complete"
        assert result.query_count == TARGET_QUERY_COUNT
        assert result.chunk_manifests_found == 25
        assert result.warnings == []

    def test_completed_fixture_no_corpus_raises(self, tmp_path):
        """Complete (20-query) fixture with empty chunks_dir → AC-3
        cannot pass; explicit error."""
        chunks_dir = tmp_path / "chunks"
        chunks_dir.mkdir()
        kind_index = _make_full_corpus(tmp_path / "synthesis_only")
        full = _make_full_fixture(kind_index)
        fixture = _write_fixture(tmp_path / "queries.json", queries=full)
        with pytest.raises(
            FixtureValidationError, match="no chunk_manifest.json files exist"
        ):
            validate(fixture, chunks_dir)

    def test_no_grade_3_raises(self, tmp_path):
        """AC-2: every query must have ≥ 1 grade-3 chunk."""
        chunks_dir = tmp_path / "chunks"
        kind_index = _make_full_corpus(chunks_dir)
        full = _make_full_fixture(kind_index)
        # Downgrade the first query's only relevant chunk to grade-2.
        full[0]["relevant_chunks"][0]["relevance"] = 2
        fixture = _write_fixture(tmp_path / "queries.json", queries=full)
        with pytest.raises(
            FixtureValidationError, match=r"AC-2 requires . 1 grade-3"
        ):
            validate(fixture, chunks_dir)

    def test_stale_chunk_id_raises(self, tmp_path):
        """AC-3: every chunk_id must resolve to a manifest entry.
        A well-formed but-stale chunk_id (e.g. from a re-chunk) fires
        the safety net."""
        chunks_dir = tmp_path / "chunks"
        kind_index = _make_full_corpus(chunks_dir)
        full = _make_full_fixture(kind_index)
        # Replace the first chunk_id with a well-formed but stale ID
        # that does NOT exist in any manifest.
        full[0]["relevant_chunks"][0]["chunk_id"] = _make_chunk_id(
            "2307.99999", "deadbeef"
        )
        fixture = _write_fixture(tmp_path / "queries.json", queries=full)
        with pytest.raises(
            FixtureValidationError,
            match="does not exist in any chunk_manifest.json",
        ):
            validate(fixture, chunks_dir)

    def test_too_few_stmt_kind_raises(self, tmp_path):
        """AC-7: at least 5 queries must reference stmt-kind chunks."""
        chunks_dir = tmp_path / "chunks"
        kind_index = _make_full_corpus(chunks_dir)
        # Build 20 queries that ALL reference proof-kind chunks. Result:
        # 0 stmt queries, well under the AC-7 threshold.
        proof_chunks = [cid for cid, k in kind_index.items() if k == "proof"]
        queries = [
            {
                "query_id": f"q{i + 1:02d}",
                "query_text": f"all proof query {i + 1}",
                "relevant_chunks": [
                    {"chunk_id": proof_chunks[i % len(proof_chunks)], "relevance": 3},
                ],
            }
            for i in range(TARGET_QUERY_COUNT)
        ]
        fixture = _write_fixture(tmp_path / "queries.json", queries=queries)
        with pytest.raises(
            FixtureValidationError,
            match=rf"queries reference kind='stmt'.* at least {MIN_QUERIES_BY_KIND['stmt']}",
        ):
            validate(fixture, chunks_dir)

    def test_duplicate_query_id_raises(self, tmp_path):
        chunks_dir = tmp_path / "chunks"
        kind_index = _make_full_corpus(chunks_dir)
        full = _make_full_fixture(kind_index)
        # Force two queries to share a query_id.
        full[1]["query_id"] = full[0]["query_id"]
        fixture = _write_fixture(tmp_path / "queries.json", queries=full)
        with pytest.raises(FixtureValidationError, match="duplicate query_id"):
            validate(fixture, chunks_dir)


# ===========================================================================
# Manifest-corruption branch
# ===========================================================================


class TestManifestErrors:
    def test_corrupt_manifest_raises(self, tmp_path):
        chunks_dir = tmp_path / "chunks"
        kind_index = _make_full_corpus(chunks_dir)
        # Corrupt one manifest after the fact.
        corrupt_path = chunks_dir / "2307.00001" / "chunk_manifest.json"
        corrupt_path.write_text("{not json", encoding="utf-8")
        full = _make_full_fixture(kind_index)
        fixture = _write_fixture(tmp_path / "queries.json", queries=full)
        with pytest.raises(
            FixtureValidationError, match="could not read chunk manifest"
        ):
            validate(fixture, chunks_dir)
