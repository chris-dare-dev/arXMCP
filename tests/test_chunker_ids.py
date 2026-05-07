"""Tests for E02_S04: content-addressable ``chunk_id`` and version stamping.

Coverage map (acceptance criteria → test):

* ``chunk_id`` matches ``arxiv:<paper_id>:<sha256(preamble_normalized + body_text)[:16]>``
  → ``TestChunkIDFormat``
* Re-running chunker on an unchanged paper produces byte-identical chunk_ids
  → ``TestChunkIDDeterminism::test_two_runs_same_paper_identical_ids``
* Modifying ``body_text`` produces a different chunk_id
  → ``TestChunkIDDeterminism::test_body_mutation_changes_chunk_id``
* Modifying preamble produces a different chunk_id
  → ``TestChunkIDDeterminism::test_preamble_mutation_changes_chunk_id``
* ``chunker_version: "v1.0"`` on every chunk; defined as a single constant
  → ``TestChunkerVersionConstant``
* ``chunk_manifest.json`` exists for every paper after a chunker run
  → ``TestChunkManifest``
* ``CHUNKER_VERSION`` is the only place ``"v1.0"`` is defined in ``ingest/``
  → ``TestSingleVersionDefinition``
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
from pathlib import Path
from unittest.mock import patch

from ingest.chunker import _compute_chunk_id, chunk_paper
from ingest.chunker_types import CHUNKER_VERSION

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "chunker"


# ===========================================================================
# Helpers
# ===========================================================================


def _stage(tmp_path: Path, paper_id: str, fixture_name: str = None):
    """Stage a chunker fixture (parsed HTML) under tmp_path/parsed/<paper_id>/.

    Returns ``(parsed_dir, chunks_dir)`` for use as RAW_DIR/CHUNKS_DIR mocks.
    """
    src = FIXTURE_DIR / (fixture_name or paper_id) / "index.html"
    parsed_dir = tmp_path / "parsed"
    chunks_dir = tmp_path / "chunks"
    paper_parsed = parsed_dir / paper_id
    paper_parsed.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, paper_parsed / "index.html")
    return parsed_dir, chunks_dir


def _run_no_preamble(tmp_path: Path, paper_id: str, fixture_name: str = None):
    """Run chunk_paper with the preamble extractor stubbed out so the
    chunk_id hash uses an empty-string preamble fallback (F3 path)."""
    parsed_dir, chunks_dir = _stage(tmp_path, paper_id, fixture_name)
    with (
        patch("ingest.chunker.PARSED_DIR", parsed_dir),
        patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        patch("ingest.chunker._resolve_preamble_doc", return_value=None),
    ):
        return chunk_paper(paper_id)


# ===========================================================================
# TestChunkIDFormat
# ===========================================================================


class TestChunkIDFormat:
    """chunk_id matches ``arxiv:<paper_id>:<16-hex-chars>``."""

    PAPER_ID = "2307.00001"
    PATTERN = re.compile(r"^arxiv:[\w./-]+:[0-9a-f]{16}$")

    def test_format_matches(self, tmp_path):
        chunks = _run_no_preamble(tmp_path, self.PAPER_ID)
        for chunk in chunks:
            assert self.PATTERN.match(chunk.chunk_id), (
                f"chunk_id {chunk.chunk_id!r} does not match expected pattern"
            )

    def test_paper_id_segment_correct(self, tmp_path):
        chunks = _run_no_preamble(tmp_path, self.PAPER_ID)
        for chunk in chunks:
            parts = chunk.chunk_id.split(":")
            assert parts[0] == "arxiv"
            assert parts[1] == self.PAPER_ID
            assert len(parts[2]) == 16

    def test_compute_chunk_id_helper_is_pure(self):
        # The helper is the canonical implementation — always returns the
        # same digest for the same inputs.
        a = _compute_chunk_id("2307.00001", "preamble", "body")
        b = _compute_chunk_id("2307.00001", "preamble", "body")
        assert a == b

    def test_compute_chunk_id_uses_documented_formula(self):
        # Spec: chunk_id = arxiv:<paper_id>:<sha256(preamble + NFC(body))[:16]>
        paper_id = "2307.00001"
        preamble = r"\newcommand{\R}{\mathbb{R}}"
        body = "Theorem text"
        expected_digest = hashlib.sha256(
            (preamble + unicodedata.normalize("NFC", body)).encode("utf-8")
        ).hexdigest()[:16]
        assert _compute_chunk_id(paper_id, preamble, body) == (
            f"arxiv:{paper_id}:{expected_digest}"
        )


# ===========================================================================
# TestChunkIDDeterminism
# ===========================================================================


class TestChunkIDDeterminism:
    """Re-runs produce byte-identical chunk_ids; mutations change them."""

    PAPER_ID = "2307.00001"

    def test_two_runs_same_paper_identical_ids(self, tmp_path):
        # Run twice in fresh temp dirs (simulating fresh Python state).
        chunks_a = _run_no_preamble(tmp_path / "a", self.PAPER_ID)
        chunks_b = _run_no_preamble(tmp_path / "b", self.PAPER_ID)
        assert len(chunks_a) == len(chunks_b)
        ids_a = [c.chunk_id for c in chunks_a]
        ids_b = [c.chunk_id for c in chunks_b]
        assert ids_a == ids_b, (
            f"two-run chunk_id divergence:\n  a={ids_a}\n  b={ids_b}"
        )

    def test_body_mutation_changes_chunk_id(self):
        # Use the helper directly — same paper_id, same preamble, but
        # one byte of body text differs → different chunk_id.
        a = _compute_chunk_id("2307.00001", "preamble", "Original body text")
        b = _compute_chunk_id("2307.00001", "preamble", "Modified body text")
        assert a != b

    def test_preamble_mutation_changes_chunk_id(self):
        a = _compute_chunk_id("2307.00001", "preamble v1", "body")
        b = _compute_chunk_id("2307.00001", "preamble v2", "body")
        assert a != b

    def test_empty_preamble_fallback_works(self):
        # F3 path: when preamble extraction fails, preamble_text="".
        # Result is content-addressable on body alone.
        a = _compute_chunk_id("2307.00001", "", "body")
        b = _compute_chunk_id("2307.00001", "", "body")
        assert a == b
        # And different body → different id even with empty preamble.
        c = _compute_chunk_id("2307.00001", "", "different body")
        assert a != c

    def test_paper_id_in_hash_input_via_prefix_only(self):
        # paper_id is in the chunk_id PREFIX, not the hash input — same
        # body+preamble across two paper_ids produces the same hash
        # suffix but different prefixes. This is intentional: lets the
        # embedder share embedding-input cache hits when two papers
        # genuinely have identical chunk content.
        a = _compute_chunk_id("2307.00001", "preamble", "body")
        b = _compute_chunk_id("2307.99999", "preamble", "body")
        assert a != b
        # Same hash suffix
        assert a.split(":")[-1] == b.split(":")[-1]

    def test_nfc_normalization_applied_to_body(self):
        # Same logical body content in NFC and NFD must produce the
        # same chunk_id (BP1 cross-host stability).
        nfc = "étale"  # precomposed
        nfd = unicodedata.normalize("NFD", nfc)
        assert nfc != nfd  # they really are different bytes
        a = _compute_chunk_id("2307.00001", "", nfc)
        b = _compute_chunk_id("2307.00001", "", nfd)
        assert a == b


# ===========================================================================
# TestChunkerVersionConstant
# ===========================================================================


class TestChunkerVersionConstant:
    PAPER_ID = "2307.00001"

    def test_constant_value(self):
        assert CHUNKER_VERSION == "v1.0"

    def test_every_chunk_has_version(self, tmp_path):
        chunks = _run_no_preamble(tmp_path, self.PAPER_ID)
        for chunk in chunks:
            assert chunk.chunker_version == CHUNKER_VERSION

    def test_dataclass_default_uses_constant(self):
        # Construct without explicit chunker_version arg — default flows
        # from CHUNKER_VERSION.
        from ingest.chunker_types import ChunkRecord
        rec = ChunkRecord(
            chunk_id="test",
            paper_id="2307.00001",
            kind="stmt",
            section_path=[],
            theorem_name=None,
            theorem_label=None,
            body_text="body",
        )
        assert rec.chunker_version == CHUNKER_VERSION


# ===========================================================================
# TestChunkManifest
# ===========================================================================


class TestChunkManifest:
    PAPER_ID = "2307.00001"

    def test_manifest_written(self, tmp_path):
        chunks = _run_no_preamble(tmp_path, self.PAPER_ID)
        manifest_path = tmp_path / "chunks" / self.PAPER_ID / "chunk_manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["paper_id"] == self.PAPER_ID
        assert data["chunker_version"] == CHUNKER_VERSION
        assert isinstance(data["chunks"], list)
        assert len(data["chunks"]) == len(chunks)

    def test_manifest_keys_sorted(self, tmp_path):
        _run_no_preamble(tmp_path, self.PAPER_ID)
        manifest_path = tmp_path / "chunks" / self.PAPER_ID / "chunk_manifest.json"
        data = json.loads(manifest_path.read_text())
        keys = list(data.keys())
        assert keys == sorted(keys), f"manifest keys not sorted: {keys}"

    def test_manifest_lists_every_chunk_id(self, tmp_path):
        chunks = _run_no_preamble(tmp_path, self.PAPER_ID)
        manifest_path = tmp_path / "chunks" / self.PAPER_ID / "chunk_manifest.json"
        data = json.loads(manifest_path.read_text())
        manifest_ids = {entry["chunk_id"] for entry in data["chunks"]}
        chunk_ids = {c.chunk_id for c in chunks}
        assert manifest_ids == chunk_ids

    def test_manifest_includes_kind(self, tmp_path):
        _run_no_preamble(tmp_path, self.PAPER_ID)
        manifest_path = tmp_path / "chunks" / self.PAPER_ID / "chunk_manifest.json"
        data = json.loads(manifest_path.read_text())
        for entry in data["chunks"]:
            assert "kind" in entry
            assert entry["kind"] in {
                "stmt", "proof", "section", "definition", "lemma",
                "corollary", "remark", "example", "claim", "fact",
                "conjecture", "hypothesis", "observation", "problem",
                "question", "exercise", "assumption", "convention",
                "notation", "proposition",
            }

    def test_manifest_atomic_write_no_tmp_left(self, tmp_path):
        # The atomic-write pattern uses a PID/UUID-suffixed tmp path
        # that must be cleaned up on the success path. No .tmp files
        # may remain in the chunks dir after a clean run.
        _run_no_preamble(tmp_path, self.PAPER_ID)
        chunks_dir = tmp_path / "chunks" / self.PAPER_ID
        leftover = list(chunks_dir.glob("*.tmp"))
        assert leftover == [], f"tmp files leaked: {leftover}"

    def test_manifest_replaces_on_rerun(self, tmp_path):
        # Run, mutate the manifest, run again — the second run replaces
        # the manifest so the schema is whatever the current chunker
        # emits (NOT the corrupted prior content).
        _run_no_preamble(tmp_path, self.PAPER_ID)
        manifest_path = tmp_path / "chunks" / self.PAPER_ID / "chunk_manifest.json"
        manifest_path.write_text('{"corrupted": true}', encoding="utf-8")
        chunks = _run_no_preamble(tmp_path, self.PAPER_ID)
        data = json.loads(manifest_path.read_text())
        assert "corrupted" not in data
        assert data["paper_id"] == self.PAPER_ID
        assert len(data["chunks"]) == len(chunks)


# ===========================================================================
# TestOutputFilenames
# ===========================================================================


class TestOutputFilenames:
    """Per-chunk JSON files are named ``<hash_suffix>.json``, not
    ``idx<N>.json``. Filenames align with content-addressable identity."""

    PAPER_ID = "2307.00001"

    def test_chunk_files_named_by_hash(self, tmp_path):
        chunks = _run_no_preamble(tmp_path, self.PAPER_ID)
        chunks_dir = tmp_path / "chunks" / self.PAPER_ID
        chunk_files = [
            p for p in chunks_dir.glob("*.json")
            if p.name != "chunk_manifest.json"
        ]
        # Each chunk file's stem matches the 16-hex hash suffix of some
        # emitted chunk_id.
        emitted_suffixes = {c.chunk_id.rsplit(":", 1)[-1] for c in chunks}
        file_stems = {p.stem for p in chunk_files}
        assert file_stems == emitted_suffixes, (
            f"filename/chunk_id mismatch:\n"
            f"  files:    {file_stems}\n"
            f"  emitted:  {emitted_suffixes}"
        )

    def test_no_idx_named_files(self, tmp_path):
        _run_no_preamble(tmp_path, self.PAPER_ID)
        chunks_dir = tmp_path / "chunks" / self.PAPER_ID
        # No filename should start with "idx" — that was the placeholder
        # naming convention that E02_S04 retired.
        for p in chunks_dir.glob("*.json"):
            assert not p.stem.startswith("idx"), (
                f"legacy idx-named file leaked: {p.name}"
            )


# ===========================================================================
# TestSingleVersionDefinition
# ===========================================================================


class TestSingleVersionDefinition:
    """Acceptance criterion: ``CHUNKER_VERSION`` is the only place the
    string ``"v1.0"`` is defined in the ``ingest/`` package as a chunker
    version. (TOKENIZER_VERSION = "v1.0" is a separate concept and lives
    in tokenizer.py — that does not violate the criterion.)"""

    def test_v1_0_literal_count_in_chunker_modules(self):
        # Static check: scan ingest/chunker.py and ingest/chunker_types.py
        # for the literal '"v1.0"'. It should appear exactly once
        # (the CHUNKER_VERSION = "v1.0" assignment in chunker_types.py).
        chunker_src = (
            Path(__file__).parent.parent / "ingest" / "chunker.py"
        ).read_text()
        types_src = (
            Path(__file__).parent.parent / "ingest" / "chunker_types.py"
        ).read_text()
        # Look for the chunker version literal — ignore anything in
        # docstrings that documents the value.
        chunker_count = chunker_src.count('"v1.0"')
        types_count = types_src.count('"v1.0"')
        # chunker.py must NOT contain the literal — it imports CHUNKER_VERSION.
        assert chunker_count == 0, (
            f'ingest/chunker.py has {chunker_count} occurrences of \'"v1.0"\'; '
            "the constant must live in chunker_types.py only"
        )
        # chunker_types.py contains exactly one occurrence (the constant
        # definition); the dataclass default uses the constant by name.
        assert types_count == 1, (
            f'ingest/chunker_types.py has {types_count} occurrences of '
            f'\'"v1.0"\' — expected exactly 1 (the CHUNKER_VERSION constant)'
        )
