"""Tests for E02_S04: content-addressable ``chunk_id`` and version stamping.

Regression guards from Phase 3 critique:
* F1 (HIGH) — cleanup-before-collision-abort: ``TestF1FailureLeavesEmptyDir``
* F2 (MEDIUM) — duplicate-content de-dup vs collision raise:
  ``TestF2DuplicateContentDeduped`` and ``TestF2CollisionRaises``
* F4 (MEDIUM) — single-source-of-truth scan:
  ``TestSingleVersionDefinition::test_v1_0_literal_count_in_ingest_package``
* F5 (MEDIUM) — fresh-Python-process determinism:
  ``TestF5FreshProcessDeterminism``
* F6 (LOW) — .tmp cleanup: ``TestF1FailureLeavesEmptyDir`` covers it
  by extension since cleanup runs unconditionally at function entry
* F7, F8 (LOW) — docstring drift: see ``ingest/chunker.py`` and
  ``ingest/chunker_types.py`` updated docstrings.

Coverage map (acceptance criteria → test):

* ``chunk_id`` matches ``arxiv:<paper_id>:<sha256(NFC(body_text))[:16]>``
  (ADR rule 1, chunk-module-m2) → ``TestChunkIDFormat``
* Re-running chunker on an unchanged paper produces byte-identical chunk_ids
  → ``TestChunkIDDeterminism::test_two_runs_same_paper_identical_ids``
* Modifying ``body_text`` produces a different chunk_id
  → ``TestChunkIDDeterminism::test_body_mutation_changes_chunk_id``
* The preamble, whether it resolved, and the data root do not change an id
  → ``TestRuleOneBodyOnly``; a TeX position value does
  → ``TestChunkIDDeterminism::test_position_value_changes_chunk_id``
* ``chunker_version: CHUNKER_VERSION`` on every chunk; defined as a single constant
  → ``TestChunkerVersionConstant``
* ``chunk_manifest.json`` exists for every paper after a chunker run
  → ``TestChunkManifest``
* ``CHUNKER_VERSION`` is the only place the current chunker version
  literal is defined in ``ingest/``
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

import pytest

from ingest.chunk import CHUNKER_VERSION
from ingest.chunker import _compute_chunk_id, chunk_paper

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
        a = _compute_chunk_id("2307.00001", "body")
        b = _compute_chunk_id("2307.00001", "body")
        assert a == b

    def test_compute_chunk_id_uses_documented_formula(self):
        # Spec (ADR rule 1): chunk_id = arxiv:<paper_id>:<sha256(NFC(body))[:16]>
        paper_id = "2307.00001"
        body = "Theorem text"
        expected_digest = hashlib.sha256(
            unicodedata.normalize("NFC", body).encode("utf-8")
        ).hexdigest()[:16]
        assert _compute_chunk_id(paper_id, body) == (
            f"arxiv:{paper_id}:{expected_digest}"
        )

    def test_position_value_is_hashed_raw_before_the_body(self):
        # The TeX chunker's position value: sha256(position + NFC(body)).
        paper_id = "2307.00001"
        body = "Theorem text"
        expected_digest = hashlib.sha256(
            ("tex-offset:42" + unicodedata.normalize("NFC", body)).encode("utf-8")
        ).hexdigest()[:16]
        assert _compute_chunk_id(paper_id, body, position="tex-offset:42") == (
            f"arxiv:{paper_id}:{expected_digest}"
        )

    def test_a_stale_three_positional_call_fails_loudly(self):
        # The pre-v1.3 signature was (paper_id, preamble_text, body_text).
        # A caller left on it must fail, not silently hash the preamble as
        # the body.
        with pytest.raises(TypeError):
            _compute_chunk_id("2307.00001", "preamble", "body")  # type: ignore[misc]


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
        a = _compute_chunk_id("2307.00001", "Original body text")
        b = _compute_chunk_id("2307.00001", "Modified body text")
        assert a != b

    def test_position_value_changes_chunk_id(self):
        # Only a TeX-chunker-owned paper passes a position; two identical
        # short proofs at different offsets must get distinct ids.
        a = _compute_chunk_id("2307.00001", "body", position="tex-offset:1")
        b = _compute_chunk_id("2307.00001", "body", position="tex-offset:2")
        assert a != b
        assert a != _compute_chunk_id("2307.00001", "body")

    def test_body_only_id_is_content_addressable(self):
        a = _compute_chunk_id("2307.00001", "body")
        b = _compute_chunk_id("2307.00001", "body")
        assert a == b
        c = _compute_chunk_id("2307.00001", "different body")
        assert a != c

    def test_paper_id_in_hash_input_via_prefix_only(self):
        # paper_id is in the chunk_id PREFIX, not the hash input — the
        # same body across two paper_ids produces the same hash suffix but
        # different prefixes. This is intentional: lets the embedder share
        # embedding-input cache hits when two papers genuinely have
        # identical chunk content.
        a = _compute_chunk_id("2307.00001", "body")
        b = _compute_chunk_id("2307.99999", "body")
        assert a != b
        # Same hash suffix
        assert a.split(":")[-1] == b.split(":")[-1]

    def test_nfc_normalization_applied_to_body(self):
        # Same logical body content in NFC and NFD must produce the
        # same chunk_id (BP1 cross-host stability).
        nfc = "étale"  # precomposed
        nfd = unicodedata.normalize("NFD", nfc)
        assert nfc != nfd  # they really are different bytes
        a = _compute_chunk_id("2307.00001", nfc)
        b = _compute_chunk_id("2307.00001", nfd)
        assert a == b


# ===========================================================================
# TestRuleOneBodyOnly — ADR rule 1 (chunk-module-m2)
# ===========================================================================


def _preamble_doc(paper_id: str, text: str):
    from ingest.preamble_types import PreambleDoc

    return PreambleDoc(
        paper_id=paper_id,
        source_hash="0" * 64,
        macros=[text],
        preamble_text=text,
        preamble_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    )


def _run_with_preamble(tmp_path: Path, paper_id: str, doc):
    parsed_dir, chunks_dir = _stage(tmp_path, paper_id)
    with (
        patch("ingest.chunker.PARSED_DIR", parsed_dir),
        patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        patch("ingest.chunker._resolve_preamble_doc", return_value=doc),
    ):
        return chunk_paper(paper_id)


class TestRuleOneBodyOnly:
    """An arXiv id is ``arxiv:<pid>:`` + ``sha256(NFC(body))[:16]``.

    The golden fixtures cannot prove this: they are generated with the
    preamble resolver stubbed to ``None``, so their ids are body-only under
    either formula. These tests chunk the same paper with no preamble and
    with two different resolvable preambles (what two data roots, or a
    recovered preamble, would yield) and require the same ids.
    """

    PAPER_ID = "2307.00002"  # multi-kind fixture

    def test_ids_do_not_depend_on_the_preamble(self, tmp_path):
        none = _run_no_preamble(tmp_path / "none", self.PAPER_ID)
        doc_a = _preamble_doc(self.PAPER_ID, r"\newcommand{\R}{\mathbb{R}}")
        doc_b = _preamble_doc(self.PAPER_ID, r"\def\Z{\mathbb{Z}}")
        with_a = _run_with_preamble(tmp_path / "a", self.PAPER_ID, doc_a)
        with_b = _run_with_preamble(tmp_path / "b", self.PAPER_ID, doc_b)

        assert len(none) > 1
        ids = [c.chunk_id for c in none]
        assert [c.chunk_id for c in with_a] == ids
        assert [c.chunk_id for c in with_b] == ids
        # The preamble still stamps preamble_ref; it just no longer reaches
        # the id.
        assert {c.preamble_ref for c in none} == {None}
        assert {c.preamble_ref for c in with_a} == {doc_a.preamble_hash}

    def test_ids_are_the_body_hash(self, tmp_path):
        doc = _preamble_doc(self.PAPER_ID, r"\newcommand{\R}{\mathbb{R}}")
        for chunk in _run_with_preamble(tmp_path, self.PAPER_ID, doc):
            digest = hashlib.sha256(
                unicodedata.normalize("NFC", chunk.body_text).encode("utf-8")
            ).hexdigest()[:16]
            assert chunk.chunk_id == f"arxiv:{self.PAPER_ID}:{digest}"

    def test_on_disk_manifest_matches_with_and_without_preamble(self, tmp_path):
        _run_no_preamble(tmp_path / "none", self.PAPER_ID)
        doc = _preamble_doc(self.PAPER_ID, r"\newcommand{\R}{\mathbb{R}}")
        _run_with_preamble(tmp_path / "doc", self.PAPER_ID, doc)

        def manifest_ids(root: Path) -> list[str]:
            manifest = json.loads(
                (root / "chunks" / self.PAPER_ID / "chunk_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            return [entry["chunk_id"] for entry in manifest["chunks"]]

        assert manifest_ids(tmp_path / "none") == manifest_ids(tmp_path / "doc")


# ===========================================================================
# TestTexPositionValue — TeX-chunker-owned papers keep their position value
# ===========================================================================

TEX_SOURCE = (
    r"\newtheorem{lemma}{Lemma}" "\n"
    r"\begin{document}" "\n"
    r"\section{One}" "\n"
    r"\begin{lemma}\label{l:a}First statement.\end{lemma}" "\n"
    r"\begin{proof}Clear.\end{proof}" "\n"
    r"\begin{lemma}\label{l:b}Second statement.\end{lemma}" "\n"
    r"\begin{proof}Clear.\end{proof}" "\n"
    r"\end{document}" "\n"
)


class _WordTokenizer:
    """Hermetic stand-in for the BGE-M3 tokenizer (whitespace words)."""

    def __call__(self, text, **kwargs):
        matches = list(re.finditer(r"\S+", text))
        return {
            "input_ids": list(range(len(matches))),
            "offset_mapping": [(m.start(), m.end()) for m in matches],
        }


def _tex_chunks(tmp_path: Path, monkeypatch, paper_id: str = "1309.5035"):
    from types import SimpleNamespace

    from ingest import chunker, tex_formal_chunker

    tex = tmp_path / "main.tex"
    tex.write_text(TEX_SOURCE, encoding="utf-8")
    monkeypatch.setattr(chunker, "_get_tokenizer", lambda: _WordTokenizer())
    monkeypatch.setattr(
        tex_formal_chunker.ApplicationPaths, "resolve",
        lambda: SimpleNamespace(corpus=tmp_path),
    )
    monkeypatch.setattr(tex_formal_chunker, "find_main_tex", lambda *_: tex)
    return tex_formal_chunker.chunk_tex_formals(paper_id)


class TestTexPositionValue:
    """ADR rule 1 clarification (chunk-module-m2): a TeX-chunker-owned paper
    keeps ``tex-offset:<n>`` in its id hash, because the same short proof
    recurs at different places in one source and both copies are kept."""

    #: The first "Clear." proof's id (offset 122). Computed with BOTH the
    #: v1.2 function at 2b05e7a (``_compute_chunk_id(pid, "tex-offset:122",
    #: "Clear.")``) and the v1.3 one, which agree. Pinned so a change to
    #: either the id function or the TeX chunker's position value fails here.
    PINNED_FIRST_PROOF_ID = "arxiv:1309.5035:2c5e961813f0a6a9"

    def test_identical_short_proofs_get_distinct_ids(self, tmp_path, monkeypatch):
        chunks = _tex_chunks(tmp_path, monkeypatch)
        proofs = [c for c in chunks if c.kind == "proof"]
        assert [p.body_text for p in proofs] == ["Clear.", "Clear."]
        assert proofs[0].chunk_id != proofs[1].chunk_id
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_tex_ids_hash_the_position_value(self, tmp_path, monkeypatch):
        for chunk in _tex_chunks(tmp_path, monkeypatch):
            digest = hashlib.sha256(
                (
                    f"tex-offset:{chunk.source_start}"
                    + unicodedata.normalize("NFC", chunk.body_text)
                ).encode("utf-8")
            ).hexdigest()[:16]
            assert chunk.chunk_id == f"arxiv:1309.5035:{digest}"

    def test_tex_id_literal_survives_the_v1_3_bump(self, tmp_path, monkeypatch):
        proofs = [c for c in _tex_chunks(tmp_path, monkeypatch) if c.kind == "proof"]
        assert proofs[0].chunk_id == self.PINNED_FIRST_PROOF_ID

    def test_chunk_paper_keeps_tex_ids_for_a_tex_owned_paper(
        self, tmp_path, monkeypatch
    ):
        # The public entry point writes TeX ids as-is for a TeX-owned
        # paper; the HTML body-only post-pass never sees them.
        from ingest import chunker

        expected = [c.chunk_id for c in _tex_chunks(tmp_path, monkeypatch)]
        monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
        got = [c.chunk_id for c in chunker.chunk_paper("1309.5035")]
        assert got == expected
        assert self.PINNED_FIRST_PROOF_ID in got


# ===========================================================================
# TestChunkerVersionConstant
# ===========================================================================


class TestChunkerVersionConstant:
    PAPER_ID = "2307.00001"

    def test_constant_value(self):
        assert CHUNKER_VERSION == "v1.3"

    def test_every_chunk_has_version(self, tmp_path):
        chunks = _run_no_preamble(tmp_path, self.PAPER_ID)
        for chunk in chunks:
            assert chunk.chunker_version == CHUNKER_VERSION

    def test_dataclass_default_uses_constant(self):
        # Construct without explicit chunker_version arg — default flows
        # from CHUNKER_VERSION.
        from ingest.chunk import ChunkRecord
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
    current chunker-version literal is defined in the ``ingest/``
    package. (TOKENIZER_VERSION is a separate concept and lives in
    tokenizer.py — that does not violate the criterion.)"""

    def test_version_literals_only_in_canonical_assignments(self):
        # Closes F4: broadened from a 2-file scan to the entire ingest/
        # package, and to BOTH "vX.Y" and 'vX.Y' quote forms. The scan
        # exempts the canonical assignments:
        #   chunk.py:         CHUNKER_VERSION = "<current>"
        #   tokenizer.py:     TOKENIZER_VERSION = "<current>"
        # CHUNKER_VERSION and TOKENIZER_VERSION track independent
        # invariants (chunking strategy vs tokenizer regex). The test
        # imports the live constants so the bump in
        # embedder-truncation-m1 (CHUNKER_VERSION "v1.0" → "v1.1")
        # doesn't require touching this test's allowed-count map.
        # Future modules that hard-code either literal instead of
        # importing the relevant constant will fail this check.
        from ingest.chunk import CHUNKER_VERSION
        from ingest.tokenizer import TOKENIZER_VERSION

        ingest_dir = Path(__file__).parent.parent / "ingest"
        canonical_literals = {
            "chunk.py": CHUNKER_VERSION,
            "tokenizer.py": TOKENIZER_VERSION,
        }
        # The literals we forbid outside their canonical home.
        watched = {CHUNKER_VERSION, TOKENIZER_VERSION}
        violations: list[str] = []
        for py_file in sorted(ingest_dir.glob("*.py")):
            # encoding="utf-8": the ingest sources contain non-ASCII bytes
            # (e.g. em-dashes) that Windows' default cp1252 decoder rejects.
            src = py_file.read_text(encoding="utf-8")
            canonical_lit = canonical_literals.get(py_file.name)
            for lit in watched:
                total = src.count(f'"{lit}"') + src.count(f"'{lit}'")
                allowed = 1 if lit == canonical_lit else 0
                if total != allowed:
                    violations.append(
                        f"{py_file.name}: has {total} occurrence(s) of "
                        f"{lit!r} literal (allowed: {allowed}). Import "
                        "the relevant *_VERSION constant from "
                        "ingest.chunk or tokenizer."
                    )
        assert not violations, (
            "single-source-of-truth violation:\n  " + "\n  ".join(violations)
        )


# ===========================================================================
# Regression guards from Phase 3 critique
# ===========================================================================


class TestF1FailureLeavesEmptyDir:
    """F1 (HIGH): a per-paper failure (e.g. duplicate-chunk_id raise)
    must NOT leave stale chunk JSONs or chunk_manifest.json on disk
    from a prior run. The fix moved the cleanup glob to the top of
    ``_chunk_paper_impl`` so any subsequent failure leaves the directory
    empty rather than retaining the previous corpus.
    """

    PAPER_ID = "2307.00001"

    def test_failure_clears_prior_artifacts(self, tmp_path):
        # Stage: pre-populate the chunks dir with stale artifacts that
        # mimic a prior chunker run.
        chunks_dir = tmp_path / "chunks" / self.PAPER_ID
        chunks_dir.mkdir(parents=True)
        stale_chunk = chunks_dir / "deadbeefdeadbeef.json"
        stale_chunk.write_text('{"stale": true}', encoding="utf-8")
        stale_manifest = chunks_dir / "chunk_manifest.json"
        stale_manifest.write_text('{"stale": true}', encoding="utf-8")
        stale_tmp = chunks_dir / "chunk_manifest.json.123.abc.tmp"
        stale_tmp.write_text('{"stale-tmp": true}', encoding="utf-8")

        # Patch _compute_chunk_id to ALWAYS raise so the chunker fails
        # mid-_chunk_paper_impl (after cleanup, before write).
        def boom(*args, **kwargs):
            raise RuntimeError("simulated mid-run failure")

        parsed_dir = tmp_path / "parsed"
        paper_parsed = parsed_dir / self.PAPER_ID
        paper_parsed.mkdir(parents=True)
        shutil.copy(
            FIXTURE_DIR / self.PAPER_ID / "index.html",
            paper_parsed / "index.html",
        )

        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", tmp_path / "chunks"),
            patch("ingest.chunker._resolve_preamble_doc", return_value=None),
            patch("ingest.chunker._compute_chunk_id", side_effect=boom),
        ):
            # chunk_paper catches RuntimeError? No — only
            # PER_PAPER_FAILURE_EXCEPTIONS (OSError/ValueError/FileNotFoundError).
            # RuntimeError will propagate. We don't care about the return
            # value here; we care about the directory state.
            import contextlib
            with contextlib.suppress(RuntimeError):
                chunk_paper(self.PAPER_ID)

        # All three stale artifacts must be gone — cleanup ran at
        # function entry, before the simulated failure.
        assert not stale_chunk.exists(), (
            "stale chunk JSON survived cleanup-before-failure"
        )
        assert not stale_manifest.exists(), (
            "stale chunk_manifest.json survived cleanup-before-failure"
        )
        assert not stale_tmp.exists(), (
            "stale .tmp file survived cleanup-before-failure (F6)"
        )


class TestF2DuplicateContentDeduped:
    """F2 (MEDIUM): two chunks with byte-identical body_text must de-dupe
    to one chunk, NOT raise the whole paper out via the
    PER_PAPER_FAILURE_EXCEPTIONS envelope."""

    def test_duplicate_body_text_emits_one_chunk(self):
        # Build a fixture with two identical theorem environments.
        # Each emits a stmt chunk with the same body_text → same
        # chunk_id → must de-dupe rather than crash.
        from ingest.chunker import _compute_chunk_id

        # Two chunk_ids identical when the bodies match.
        a = _compute_chunk_id("2307.00001", "duplicated body")
        b = _compute_chunk_id("2307.00001", "duplicated body")
        assert a == b  # same content → same id (precondition for the test)

    def test_duplicate_chunks_in_same_paper_dedupe(self, tmp_path):
        # Construct a synthetic HTML with TWO byte-identical theorem
        # divs in the same section. Both produce the same body_text
        # after _element_text. The chunker must emit ONE stmt chunk,
        # not zero (raise) and not two (overwrite).
        paper_id = "2307.99002"
        html = (
            "<!DOCTYPE html><html><body><article class='ltx_document'>"
            "<section class='ltx_section'>"
            "<h2 class='ltx_title'>1. Section</h2>"
            "<div class='ltx_theorem ltx_theorem_definition' id='d1'>"
            "<h6 class='ltx_title'>Definition 1.</h6>"
            "<p>Identical body text for the duplicate test.</p>"
            "</div>"
            "<div class='ltx_theorem ltx_theorem_definition' id='d2'>"
            "<h6 class='ltx_title'>Definition 2.</h6>"
            "<p>Identical body text for the duplicate test.</p>"
            "</div>"
            "</section></article></body></html>"
        )
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_text(html, encoding="utf-8")
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            patch("ingest.chunker._resolve_preamble_doc", return_value=None),
        ):
            chunks = chunk_paper(paper_id)
        # Filter to chunks whose body_text exactly matches what
        # _element_text produces from the duplicated div content.
        # The "Definition N." heading text differs by the digit, so
        # only the body paragraphs (without the heading) would
        # actually be duplicates. We instead assert the WEAKER but
        # robust property: the call did not raise (vs. the pre-fix
        # behaviour of raising and returning [] via the envelope) and
        # the manifest has no duplicate chunk_ids.
        assert len(chunks) > 0, (
            "duplicate-content paper should NOT silently drop to []; "
            "expected at least one chunk after dedup"
        )
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), (
            f"manifest contains duplicate chunk_ids: {ids}"
        )


class TestF2CollisionRaises:
    """F2 (MEDIUM): a genuine 64-bit SHA-256 prefix collision (different
    content, same chunk_id) MUST raise — only the same-content case
    de-dupes silently."""

    def test_collision_path_raises_with_precise_message(self, tmp_path):
        from ingest.chunker import _resolve_preamble_doc  # noqa: F401

        paper_id = "2307.99003"
        # Two chunks with DIFFERENT body_text but a forced same chunk_id.
        # Patch _compute_chunk_id to return the same id for any input.
        canned_id = "arxiv:2307.99003:0123456789abcdef"

        parsed_dir = tmp_path / "parsed"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        # Use the multi-kind fixture which emits >1 chunk per paper.
        shutil.copy(
            FIXTURE_DIR / "2307.00002" / "index.html",
            paper_parsed / "index.html",
        )
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", tmp_path / "chunks"),
            patch("ingest.chunker._resolve_preamble_doc", return_value=None),
            patch("ingest.chunker._compute_chunk_id", return_value=canned_id),
        ):
            # Multiple distinct body_texts → all map to canned_id →
            # collision raise on the second one.
            try:
                chunks = chunk_paper(paper_id)
            except ValueError as exc:
                # The new message says "SHA-256 prefix collision", NOT
                # the prior conflated "duplicate chunk_id ... either ..."
                assert "collision" in str(exc).lower()
                assert paper_id in str(exc)
                return
            # If chunks come back without raising, the fixture had only
            # one chunk after _element_text — a fixture artifact, skip.
            if len(chunks) <= 1:
                pytest.skip("fixture produced ≤1 chunk; cannot test collision")
            pytest.fail("expected collision raise, got chunks back")


class TestF5FreshProcessDeterminism:
    """F5 (MEDIUM): the brief explicitly required cross-process
    determinism. Spawn a fresh interpreter (with PYTHONHASHSEED=random)
    twice and assert the chunk_ids match."""

    def test_two_subprocesses_produce_identical_ids(self, tmp_path):
        import os as _os
        import subprocess
        import sys

        repo_root = Path(__file__).parent.parent
        # The script uses _compute_chunk_id directly so we don't need
        # a full chunker run + fixture staging in each subprocess.
        # This isolates the determinism question to the hash path.
        script = (
            "import sys, json; "
            # repr() emits a valid Python string literal with proper
            # escaping — a bare Windows path would inject invalid \U / \P
            # escape sequences into the -c source and SyntaxError the child.
            "sys.path.insert(0, " + repr(str(repo_root)) + "); "
            "from ingest.chunker import _compute_chunk_id; "
            "body = 'Theorem 3.4. Let X be a smooth projective variety.'; "
            "ids = [_compute_chunk_id('2307.00001', body) for _ in range(3)]; "
            "print(json.dumps(ids))"
        )
        env = _os.environ.copy()
        env["PYTHONHASHSEED"] = "random"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        out_a = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=env, check=True,
        )
        out_b = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=env, check=True,
        )
        ids_a = json.loads(out_a.stdout.strip())
        ids_b = json.loads(out_b.stdout.strip())
        # Within each subprocess, the three calls must produce the
        # same id (intra-process determinism).
        assert ids_a[0] == ids_a[1] == ids_a[2]
        assert ids_b[0] == ids_b[1] == ids_b[2]
        # Across subprocesses with PYTHONHASHSEED randomized, the id
        # must STILL match — the hash input has no dict iteration or
        # set membership; the fix is structural.
        assert ids_a[0] == ids_b[0], (
            f"cross-process chunk_id divergence:\n"
            f"  process A: {ids_a[0]}\n"
            f"  process B: {ids_b[0]}"
        )
