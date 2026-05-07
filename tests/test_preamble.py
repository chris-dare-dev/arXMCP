"""Unit tests for the per-paper preamble extractor (E02_S02).

Coverage map:
  Acceptance criterion -> test class
  ──────────────────────────────────────────────────────────────────────
  preamble.json produced for the seed corpus  -> manual; tested via
                                                  TestExtractFixturePaper
                                                  on a fixture .tex
  preamble_text deterministic                 -> TestDeterminism
  preamble_ref matches SHA-256(text)[:16]     -> TestPreambleHashContract
  re-run on unchanged source is no-op         -> TestIdempotency
  fixture: 3 \\newcommand + 1 \\DeclareMathOperator -> TestExtractFixturePaper
                                                  + TestNewcommandExtraction
  module docstring rejects contextual retrieval -> TestModuleContract
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

import ingest.preamble as preamble_mod
from ingest.chunker import InvalidPaperIDError
from ingest.preamble import (
    PER_PAPER_FAILURE_EXCEPTIONS,
    _extract_macros,
    _normalise,
    _scan_balanced_body,
    _strip_tex_comments,
    extract_preamble,
    load_preamble,
)
from ingest.preamble_types import PreambleDoc

FIXTURE_TEX = Path(__file__).parent / "fixtures" / "preamble" / "sample.tex"


# ===========================================================================
# Helpers
# ===========================================================================


def _stage_paper(tmp_path: Path, paper_id: str, tex_source: str) -> Path:
    """Copy ``tex_source`` into ``tmp_path/raw/<paper_id>/<paper_id>.tex``.

    Returns the temp paper-id directory so callers can introspect.
    """
    raw_dir = tmp_path / "raw"
    paper_dir = raw_dir / paper_id
    paper_dir.mkdir(parents=True)
    (paper_dir / f"{paper_id}.tex").write_text(tex_source, encoding="utf-8")
    return paper_dir


def _patched_extract(tmp_path: Path, paper_id: str):
    """Run extract_preamble with RAW_DIR/PREAMBLE_DIR pointed at tmp_path."""
    raw_dir = tmp_path / "raw"
    preamble_dir = tmp_path / "preamble"
    log_path = tmp_path / "ops" / "preamble.log"
    with (
        patch("ingest.preamble.RAW_DIR", raw_dir),
        patch("ingest.preamble.PREAMBLE_DIR", preamble_dir),
        patch("ingest.preamble.PREAMBLE_LOG_PATH", log_path),
    ):
        return extract_preamble(paper_id)


# ===========================================================================
# TestModuleContract
# ===========================================================================


class TestModuleContract:
    def test_docstring_rejects_contextual_retrieval(self):
        doc = preamble_mod.__doc__ or ""
        assert "Anthropic contextual retrieval is rejected" in doc, (
            "module docstring must explicitly reject Anthropic contextual "
            "retrieval per the milestone acceptance criterion"
        )

    def test_per_paper_failure_exceptions_targeted(self):
        # Resilience-pattern exceptions only; programmer bugs propagate.
        assert OSError in PER_PAPER_FAILURE_EXCEPTIONS
        assert ValueError in PER_PAPER_FAILURE_EXCEPTIONS
        assert FileNotFoundError in PER_PAPER_FAILURE_EXCEPTIONS
        # AttributeError, KeyError, TypeError must NOT be caught.
        assert AttributeError not in PER_PAPER_FAILURE_EXCEPTIONS
        assert KeyError not in PER_PAPER_FAILURE_EXCEPTIONS
        assert TypeError not in PER_PAPER_FAILURE_EXCEPTIONS


# ===========================================================================
# TestCommentStripping
# ===========================================================================


class TestCommentStripping:
    def test_strips_simple_comment(self):
        assert _strip_tex_comments("foo % a comment\nbar") == "foo \nbar"

    def test_preserves_escaped_percent(self):
        assert _strip_tex_comments(r"50\% off\n") == r"50\% off\n"

    def test_double_backslash_percent_is_comment(self):
        # Two backslashes (even count) -> the % IS a comment.
        result = _strip_tex_comments("end\\\\% comment\nnext")
        # The double backslash stays; everything after % is stripped.
        assert "comment" not in result
        assert "next" in result

    def test_empty_string(self):
        assert _strip_tex_comments("") == ""


# ===========================================================================
# TestBraceBalancedScan
# ===========================================================================


class TestBraceBalancedScan:
    def test_simple_balanced(self):
        # Body: "abc"; opening { is at index 0, body starts at index 1.
        text = "{abc}"
        end = _scan_balanced_body(text, 1)
        assert end == 5  # past the closing }

    def test_nested_balanced(self):
        text = "{a{b}c}"
        end = _scan_balanced_body(text, 1)
        assert end == 7

    def test_escaped_braces_ignored(self):
        # \{ and \} should not affect depth.
        text = r"{a\{b\}c}"
        end = _scan_balanced_body(text, 1)
        assert end == len(text)

    def test_unbalanced_returns_none(self):
        text = "{unbalanced"
        assert _scan_balanced_body(text, 1) is None


# ===========================================================================
# TestNormalise
# ===========================================================================


class TestNormalise:
    def test_collapses_whitespace(self):
        assert _normalise("a   b\nc\t\td") == "a b c d"

    def test_strips_leading_trailing(self):
        assert _normalise("  foo  ") == "foo"


# ===========================================================================
# TestNewcommandExtraction
# ===========================================================================


class TestNewcommandExtraction:
    def test_simple_newcommand(self):
        macros = _extract_macros(r"\newcommand{\R}{\mathbb{R}}")
        assert macros == [r"\newcommand{\R}{\mathbb{R}}"]

    def test_renewcommand_extracted(self):
        macros = _extract_macros(r"\renewcommand{\foo}{bar}")
        assert any("renewcommand" in m for m in macros)

    def test_providecommand_extracted(self):
        macros = _extract_macros(r"\providecommand{\Hom}{\operatorname{Hom}}")
        assert any("providecommand" in m for m in macros)

    def test_newcommand_with_args(self):
        macros = _extract_macros(r"\newcommand{\Spec}[1]{\operatorname{Spec}(#1)}")
        assert len(macros) == 1
        assert "[1]" in macros[0]

    def test_newcommand_with_default(self):
        macros = _extract_macros(r"\newcommand{\foo}[2][zero]{x}")
        assert any("[zero]" in m for m in macros)

    def test_multiline_newcommand(self):
        src = "\\newcommand{\\big}{\n  Multi\n  Line\n  Body\n}"
        macros = _extract_macros(src)
        assert len(macros) == 1
        # Whitespace collapsed to single spaces
        assert "Multi Line Body" in macros[0]
        assert "\n" not in macros[0]


# ===========================================================================
# TestDefAndLetExtraction
# ===========================================================================


class TestDefAndLetExtraction:
    def test_def_extracted(self):
        macros = _extract_macros(r"\def\sheaf#1{\mathcal{#1}}")
        assert any(m.startswith(r"\def") for m in macros)

    def test_edef_extracted(self):
        macros = _extract_macros(r"\edef\v{1.2}")
        assert any(r"\edef" in m for m in macros)

    def test_gdef_extracted(self):
        macros = _extract_macros(r"\gdef\foo{bar}")
        assert any(r"\gdef" in m for m in macros)

    def test_xdef_extracted(self):
        macros = _extract_macros(r"\xdef\baz{qux}")
        assert any(r"\xdef" in m for m in macros)

    def test_let_with_equals(self):
        macros = _extract_macros(r"\let\old=\new")
        assert any(r"\let" in m for m in macros)

    def test_let_without_equals(self):
        macros = _extract_macros(r"\let\old\new")
        assert any(r"\let" in m for m in macros)


# ===========================================================================
# TestDeclareMathOperator
# ===========================================================================


class TestDeclareMathOperator:
    def test_basic(self):
        macros = _extract_macros(r"\DeclareMathOperator{\Pic}{Pic}")
        assert any("DeclareMathOperator" in m for m in macros)

    def test_starred(self):
        macros = _extract_macros(r"\DeclareMathOperator*{\colim}{colim}")
        assert any("colim" in m for m in macros)


# ===========================================================================
# TestExtractFixturePaper
# ===========================================================================


class TestExtractFixturePaper:
    """Acceptance test: the milestone-spec fixture must extract correctly."""

    def test_macros_count_meets_milestone_floor(self, tmp_path):
        # The milestone spec calls for "3 \\newcommand and 1 \\DeclareMathOperator
        # produces a macros list of length 4". Our richer fixture goes further
        # — 5 \\newcommand + 1 \\renewcommand + 1 \\providecommand + 2 DMO +
        # 4 \\def-family + 2 \\let = 15 macros — but the floor is satisfied.
        tex = FIXTURE_TEX.read_text()
        macros = _extract_macros(tex)
        # Count by directive family
        n_newcommand = sum(1 for m in macros if m.startswith(r"\newcommand"))
        n_decl_math = sum(1 for m in macros if r"\DeclareMathOperator" in m)
        assert n_newcommand >= 3, f"need >=3 newcommand, got {n_newcommand}"
        assert n_decl_math >= 1, f"need >=1 DeclareMathOperator, got {n_decl_math}"

    def test_extracted_macros_are_sorted(self, tmp_path):
        tex = FIXTURE_TEX.read_text()
        macros = _extract_macros(tex)
        assert macros == sorted(macros)

    def test_extracted_macros_are_unique(self, tmp_path):
        tex = FIXTURE_TEX.read_text()
        macros = _extract_macros(tex)
        assert len(macros) == len(set(macros))

    def test_commented_out_macro_not_extracted(self, tmp_path):
        tex = FIXTURE_TEX.read_text()
        macros = _extract_macros(tex)
        # The fixture has "% \\newcommand{\\fake}{x}" inside a comment.
        for m in macros:
            assert r"\fake" not in m, f"comment leaked into extraction: {m}"

    def test_escaped_percent_macro_extracted(self):
        # \halfoff body contains "50\\%" — the literal percent must NOT be
        # treated as a comment-starter by the extractor.
        tex = FIXTURE_TEX.read_text()
        macros = _extract_macros(tex)
        assert any(r"\halfoff" in m for m in macros), (
            "escaped percent in body must not break extraction"
        )

    def test_full_pipeline_produces_preamble_doc(self, tmp_path):
        paper_id = "2307.00001"
        tex = FIXTURE_TEX.read_text()
        _stage_paper(tmp_path, paper_id, tex)
        doc = _patched_extract(tmp_path, paper_id)
        assert isinstance(doc, PreambleDoc)
        assert doc.paper_id == paper_id
        assert len(doc.macros) >= 4
        assert doc.preamble_text == "\n".join(doc.macros)

    def test_writes_preamble_json(self, tmp_path):
        paper_id = "2307.00001"
        tex = FIXTURE_TEX.read_text()
        _stage_paper(tmp_path, paper_id, tex)
        _patched_extract(tmp_path, paper_id)
        out = tmp_path / "preamble" / paper_id / "preamble.json"
        assert out.exists()
        data = json.loads(out.read_text())
        # Sorted keys per BP1
        assert list(data.keys()) == sorted(data.keys())


# ===========================================================================
# TestPreambleHashContract
# ===========================================================================


class TestPreambleHashContract:
    """Acceptance: preamble_hash == SHA-256(preamble_text)[:16]."""

    def test_hash_matches_sha256_prefix(self, tmp_path):
        paper_id = "2307.00001"
        _stage_paper(tmp_path, paper_id, FIXTURE_TEX.read_text())
        doc = _patched_extract(tmp_path, paper_id)
        expected = hashlib.sha256(doc.preamble_text.encode("utf-8")).hexdigest()[:16]
        assert doc.preamble_hash == expected

    def test_source_hash_matches_full_sha256(self, tmp_path):
        paper_id = "2307.00001"
        tex = FIXTURE_TEX.read_text()
        _stage_paper(tmp_path, paper_id, tex)
        doc = _patched_extract(tmp_path, paper_id)
        expected = hashlib.sha256(tex.encode("utf-8")).hexdigest()
        assert doc.source_hash == expected
        assert len(doc.source_hash) == 64  # full SHA-256 hex


# ===========================================================================
# TestDeterminism
# ===========================================================================


class TestDeterminism:
    """preamble_text must be byte-identical across runs on the same source."""

    def test_two_runs_same_source_identical(self, tmp_path):
        paper_id = "2307.00001"
        _stage_paper(tmp_path, paper_id, FIXTURE_TEX.read_text())
        doc1 = _patched_extract(tmp_path, paper_id)
        # Touch the preamble.json (simulate concurrent reader); doesn't affect output
        doc2 = _patched_extract(tmp_path, paper_id)
        assert doc1.preamble_text == doc2.preamble_text
        assert doc1.preamble_hash == doc2.preamble_hash
        assert doc1.macros == doc2.macros

    def test_macro_input_order_does_not_affect_output(self, tmp_path):
        # Same macros declared in different order -> same preamble_text.
        a = r"""
        \newcommand{\R}{\mathbb{R}}
        \newcommand{\Z}{\mathbb{Z}}
        \DeclareMathOperator{\Pic}{Pic}
        """
        b = r"""
        \DeclareMathOperator{\Pic}{Pic}
        \newcommand{\Z}{\mathbb{Z}}
        \newcommand{\R}{\mathbb{R}}
        """
        ma = _extract_macros(a)
        mb = _extract_macros(b)
        assert ma == mb


# ===========================================================================
# TestIdempotency
# ===========================================================================


class TestIdempotency:
    """Re-run on unchanged source must NOT rewrite preamble.json."""

    def test_unchanged_source_no_rewrite(self, tmp_path):
        paper_id = "2307.00001"
        _stage_paper(tmp_path, paper_id, FIXTURE_TEX.read_text())
        _patched_extract(tmp_path, paper_id)
        out = tmp_path / "preamble" / paper_id / "preamble.json"
        first_mtime = out.stat().st_mtime_ns
        # Sleep a tick so mtime would change if we did write.
        import time as _t
        _t.sleep(0.01)
        _patched_extract(tmp_path, paper_id)
        second_mtime = out.stat().st_mtime_ns
        assert first_mtime == second_mtime, (
            "no-op re-run must NOT rewrite preamble.json"
        )

    def test_changed_source_triggers_rewrite(self, tmp_path):
        paper_id = "2307.00001"
        _stage_paper(tmp_path, paper_id, FIXTURE_TEX.read_text())
        doc1 = _patched_extract(tmp_path, paper_id)

        # Mutate the .tex source — add a new macro
        tex_path = tmp_path / "raw" / paper_id / f"{paper_id}.tex"
        tex_path.write_text(
            tex_path.read_text() + "\n\\newcommand{\\NewlyAdded}{x}\n",
            encoding="utf-8",
        )
        doc2 = _patched_extract(tmp_path, paper_id)
        assert doc2.source_hash != doc1.source_hash
        assert len(doc2.macros) > len(doc1.macros)
        assert any(r"\NewlyAdded" in m for m in doc2.macros)


# ===========================================================================
# TestPaperIDValidation
# ===========================================================================


class TestPaperIDValidation:
    def test_invalid_id_rejected(self, tmp_path):
        with (
            patch("ingest.preamble.RAW_DIR", tmp_path / "raw"),
            patch("ingest.preamble.PREAMBLE_DIR", tmp_path / "preamble"),
            pytest.raises(InvalidPaperIDError),
        ):
            extract_preamble("../etc/passwd")

    def test_invalid_id_creates_no_files(self, tmp_path):
        out_dir = tmp_path / "preamble"
        with (
            patch("ingest.preamble.RAW_DIR", tmp_path / "raw"),
            patch("ingest.preamble.PREAMBLE_DIR", out_dir),
            pytest.raises(InvalidPaperIDError),
        ):
            extract_preamble("foo\nbar")
        # Even the parent shouldn't be created
        assert not out_dir.exists()


# ===========================================================================
# TestMissingSource
# ===========================================================================


class TestMissingSource:
    def test_missing_raw_dir_raises_filenotfound(self, tmp_path):
        log_path = tmp_path / "ops" / "preamble.log"
        with (
            patch("ingest.preamble.RAW_DIR", tmp_path / "raw"),
            patch("ingest.preamble.PREAMBLE_DIR", tmp_path / "preamble"),
            patch("ingest.preamble.PREAMBLE_LOG_PATH", log_path),
            pytest.raises(FileNotFoundError),
        ):
            extract_preamble("9999.99999")
        # Log should be written for the failure
        assert log_path.exists()


# ===========================================================================
# TestLoadPreamble
# ===========================================================================


class TestLoadPreamble:
    def test_returns_none_when_missing(self, tmp_path):
        with (
            patch("ingest.preamble.PREAMBLE_DIR", tmp_path / "preamble"),
        ):
            assert load_preamble("9999.99999") is None

    def test_round_trips_through_disk(self, tmp_path):
        paper_id = "2307.00001"
        _stage_paper(tmp_path, paper_id, FIXTURE_TEX.read_text())
        doc1 = _patched_extract(tmp_path, paper_id)
        with patch("ingest.preamble.PREAMBLE_DIR", tmp_path / "preamble"):
            doc2 = load_preamble(paper_id)
        assert doc2 is not None
        assert doc2.preamble_text == doc1.preamble_text
        assert doc2.preamble_hash == doc1.preamble_hash
        assert doc2.macros == doc1.macros


# ===========================================================================
# TestChunkerIntegration
# ===========================================================================


class TestChunkerIntegration:
    """Verify that ingest/chunker.py populates ChunkRecord.preamble_ref
    from extract_preamble's output."""

    PAPER_ID = "2307.00001"

    def test_chunker_populates_preamble_ref(self, tmp_path):
        # Stage the chunker fixture
        from ingest.chunker import chunk_paper as chunk_paper_fn

        chunker_fixture = (
            Path(__file__).parent / "fixtures" / "chunker" / self.PAPER_ID / "index.html"
        )
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        raw_dir = tmp_path / "raw"
        preamble_dir = tmp_path / "preamble"

        paper_parsed = parsed_dir / self.PAPER_ID
        paper_parsed.mkdir(parents=True)
        shutil.copy(chunker_fixture, paper_parsed / "index.html")

        # Stage a .tex source so preamble extraction has something to chew on
        paper_raw = raw_dir / self.PAPER_ID
        paper_raw.mkdir(parents=True)
        (paper_raw / f"{self.PAPER_ID}.tex").write_text(
            r"\newcommand{\R}{\mathbb{R}}", encoding="utf-8"
        )

        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            patch("ingest.preamble.RAW_DIR", raw_dir),
            patch("ingest.preamble.PREAMBLE_DIR", preamble_dir),
        ):
            chunks = chunk_paper_fn(self.PAPER_ID)

        assert len(chunks) > 0
        # Every chunk should now carry the preamble_ref hash
        expected_text = r"\newcommand{\R}{\mathbb{R}}"
        expected_hash = hashlib.sha256(expected_text.encode("utf-8")).hexdigest()[:16]
        for chunk in chunks:
            assert chunk.preamble_ref == expected_hash, (
                f"chunk {chunk.chunk_id} preamble_ref={chunk.preamble_ref} "
                f"!= expected {expected_hash}"
            )

    def test_chunker_tolerates_missing_preamble(self, tmp_path):
        # When raw/<paper_id>/ doesn't exist, the chunker logs WARN and
        # falls back to preamble_ref=None. Chunks must still be emitted.
        from ingest.chunker import chunk_paper as chunk_paper_fn

        chunker_fixture = (
            Path(__file__).parent / "fixtures" / "chunker" / self.PAPER_ID / "index.html"
        )
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        raw_dir = tmp_path / "raw"  # intentionally empty
        preamble_dir = tmp_path / "preamble"

        paper_parsed = parsed_dir / self.PAPER_ID
        paper_parsed.mkdir(parents=True)
        shutil.copy(chunker_fixture, paper_parsed / "index.html")
        raw_dir.mkdir()  # exists but no per-paper subdir

        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            patch("ingest.preamble.RAW_DIR", raw_dir),
            patch("ingest.preamble.PREAMBLE_DIR", preamble_dir),
        ):
            chunks = chunk_paper_fn(self.PAPER_ID)

        assert len(chunks) > 0
        # Every chunk must have preamble_ref=None (graceful fallback)
        for chunk in chunks:
            assert chunk.preamble_ref is None


# ===========================================================================
# Regression guards from Phase 3 critique (F1–F10)
# ===========================================================================


class TestF1SymlinkConfinement:
    """F1 (HIGH): refuse to read .tex outside the paper's raw dir."""

    def test_symlink_to_outside_raises(self, tmp_path):
        paper_id = "2307.00001"
        # Stage a paper directory containing a symlink that escapes
        outside_target = tmp_path / "secret.txt"
        outside_target.write_text(r"\newcommand{\stolen}{x}", encoding="utf-8")
        raw_dir = tmp_path / "raw"
        paper_dir = raw_dir / paper_id
        paper_dir.mkdir(parents=True)
        bad_symlink = paper_dir / f"{paper_id}.tex"
        bad_symlink.symlink_to(outside_target)
        with (
            patch("ingest.preamble.RAW_DIR", raw_dir),
            patch("ingest.preamble.PREAMBLE_DIR", tmp_path / "preamble"),
            patch("ingest.preamble.PREAMBLE_LOG_PATH", tmp_path / "preamble.log"),
            pytest.raises(ValueError, match="Threat 1"),
        ):
            extract_preamble(paper_id)

    def test_real_file_still_works(self, tmp_path):
        paper_id = "2307.00001"
        _stage_paper(tmp_path, paper_id, FIXTURE_TEX.read_text())
        doc = _patched_extract(tmp_path, paper_id)
        assert doc.paper_id == paper_id


class TestF2CacheCorruption:
    """F2 (HIGH): _read_existing_preamble must reject malformed cache."""

    def test_macros_as_string_returns_none(self, tmp_path):
        from ingest.preamble import _read_existing_preamble
        bad = tmp_path / "preamble.json"
        bad.write_text(
            json.dumps({
                "paper_id": "2307.00001",
                "source_hash": "x" * 64,
                "macros": "oops not a list",
                "preamble_text": "oops",
                "preamble_hash": "0" * 16,
            }),
            encoding="utf-8",
        )
        # Without the F2 fix: from_dict's list("oops not a list") would
        # silently produce one-letter "macros". The fix raises TypeError
        # which _read_existing_preamble catches → returns None.
        assert _read_existing_preamble(bad) is None

    def test_macros_with_non_string_entries_returns_none(self, tmp_path):
        from ingest.preamble import _read_existing_preamble
        bad = tmp_path / "preamble.json"
        bad.write_text(
            json.dumps({
                "paper_id": "2307.00001",
                "source_hash": "x" * 64,
                "macros": ["ok", 123, None],
                "preamble_text": "ok\n123\nNone",
                "preamble_hash": "0" * 16,
            }),
            encoding="utf-8",
        )
        assert _read_existing_preamble(bad) is None

    def test_corrupt_cache_triggers_reextraction(self, tmp_path):
        # Stage paper, extract once (cache valid), then corrupt cache,
        # extract again — extractor should detect corruption and re-extract.
        paper_id = "2307.00001"
        _stage_paper(tmp_path, paper_id, FIXTURE_TEX.read_text())
        doc1 = _patched_extract(tmp_path, paper_id)
        # Corrupt the cache
        cache = tmp_path / "preamble" / paper_id / "preamble.json"
        cache.write_text(
            json.dumps({
                "paper_id": paper_id,
                "source_hash": doc1.source_hash,
                "macros": "corrupt",
                "preamble_text": "corrupt",
                "preamble_hash": "deadbeef00000000",
            }),
            encoding="utf-8",
        )
        doc2 = _patched_extract(tmp_path, paper_id)
        # Re-extracted cleanly — the corrupt cache did not poison output
        assert doc2.preamble_hash == doc1.preamble_hash
        assert doc2.macros == doc1.macros


class TestF3ChunkerImportFailureSurfaces:
    """F3 (HIGH): chunker's preamble lookup does NOT silently swallow
    a real import failure for the preamble module."""

    def test_resolve_preamble_doc_has_no_except_importerror(self):
        # Static source check: the body of _resolve_preamble_doc must not
        # contain `except ImportError`. Pre-fix, the chunker silently
        # returned None on any ImportError (including real packaging
        # failures), masking corpus-wide preamble_ref=None bugs.
        from pathlib import Path
        chunker_src = (
            Path(__file__).parent.parent / "ingest" / "chunker.py"
        ).read_text()
        # Find the function body
        marker = "def _resolve_preamble_doc"
        idx = chunker_src.index(marker)
        # Look at the next ~50 lines (whole function body)
        body = chunker_src[idx : idx + 2000]
        # Search for the actual code construct (with colon and indentation),
        # not the bare string — the function's docstring legitimately
        # references the phrase "except ImportError" in prose.
        import re as _re
        pattern = _re.compile(r"^\s*except\s+ImportError\s*[:(]", _re.MULTILINE)
        assert pattern.search(body) is None, (
            "_resolve_preamble_doc must not swallow ImportError; a real "
            "packaging failure should surface, not silently null-stamp "
            "every chunk's preamble_ref. Closes F3."
        )


class TestF4F5AtomicWriteCleanup:
    """F4 (MEDIUM): per-process tmp suffix prevents same-paper races.
    F5 (MEDIUM): tmp file does not leak when os.replace fails."""

    def test_tmp_suffix_is_unique_per_call(self, tmp_path, monkeypatch):
        from ingest.preamble import _write_preamble_json
        from ingest.preamble_types import PreambleDoc
        seen: list[Path] = []

        real_replace = os.replace

        def capture_replace(src, dst):
            seen.append(Path(src))
            real_replace(src, dst)

        monkeypatch.setattr("ingest.preamble.os.replace", capture_replace)
        doc = PreambleDoc(
            paper_id="2307.00001",
            source_hash="a" * 64,
            macros=[r"\newcommand{\R}{}"],
            preamble_text=r"\newcommand{\R}{}",
            preamble_hash="0" * 16,
        )
        out = tmp_path / "preamble.json"
        _write_preamble_json(out, doc)
        _write_preamble_json(out, doc)
        assert len(seen) == 2
        # Two distinct tmp filenames despite same out_path
        assert seen[0] != seen[1]

    def test_tmp_cleaned_up_when_replace_fails(self, tmp_path, monkeypatch):
        from ingest.preamble import _write_preamble_json
        from ingest.preamble_types import PreambleDoc

        def boom(src, dst):
            raise OSError("simulated rename failure")

        monkeypatch.setattr("ingest.preamble.os.replace", boom)
        doc = PreambleDoc(
            paper_id="2307.00001",
            source_hash="a" * 64,
            macros=[r"\newcommand{\R}{}"],
            preamble_text=r"\newcommand{\R}{}",
            preamble_hash="0" * 16,
        )
        out = tmp_path / "preamble.json"
        with pytest.raises(OSError):
            _write_preamble_json(out, doc)
        # No leftover .tmp files in the output directory
        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == []


class TestF6NFCNormalization:
    """F6 (MEDIUM): preamble_text uses NFC Unicode normalization."""

    def test_nfc_and_nfd_produce_identical_hash(self, tmp_path):
        # Same macro using two Unicode forms for "é"
        nfc = "\\newcommand{\\étale}{etale}"     # precomposed (U+00E9)
        nfd = "\\newcommand{\\étale}{etale}"   # decomposed (e + U+0301)
        # Pre-fix: hashes would differ. Post-fix: both normalise to NFC.
        for paper_id, src in [("2307.00100", nfc), ("2307.00101", nfd)]:
            _stage_paper(tmp_path, paper_id, src)
        d1 = _patched_extract(tmp_path, "2307.00100")
        d2 = _patched_extract(tmp_path, "2307.00101")
        assert d1.preamble_hash == d2.preamble_hash, (
            f"NFC vs NFD must produce identical hashes; "
            f"got {d1.preamble_hash} vs {d2.preamble_hash}"
        )


class TestF7StrictUTF8Decode:
    """F7 (MEDIUM): non-UTF-8 source raises ValueError, not silent U+FFFD."""

    def test_invalid_utf8_raises_and_logs(self, tmp_path):
        paper_id = "2307.00001"
        raw_dir = tmp_path / "raw"
        paper_dir = raw_dir / paper_id
        paper_dir.mkdir(parents=True)
        # Latin-1 byte 0xe9 is not valid UTF-8 in this sequence
        (paper_dir / f"{paper_id}.tex").write_bytes(b"\\newcommand{\\R}{\xe9}")
        log_path = tmp_path / "preamble.log"
        with (
            patch("ingest.preamble.RAW_DIR", raw_dir),
            patch("ingest.preamble.PREAMBLE_DIR", tmp_path / "preamble"),
            patch("ingest.preamble.PREAMBLE_LOG_PATH", log_path),
            pytest.raises(ValueError),
        ):
            extract_preamble(paper_id)
        # Failure must be logged for weekly ops review
        assert log_path.exists()


class TestF8HashCollisionAcrossPapers:
    """F8 (MEDIUM): identical preamble across papers yields identical ref."""

    def test_identical_preamble_across_papers_yields_same_ref(self, tmp_path):
        tex = r"\newcommand{\R}{\mathbb{R}}"
        _stage_paper(tmp_path, "2307.00001", tex)
        _stage_paper(tmp_path, "2307.00002", tex)
        d1 = _patched_extract(tmp_path, "2307.00001")
        d2 = _patched_extract(tmp_path, "2307.00002")
        assert d1.preamble_hash == d2.preamble_hash
        # Source hashes should also match (same .tex content) — but
        # the paper_ids on the docs must differ.
        assert d1.source_hash == d2.source_hash
        assert d1.paper_id != d2.paper_id


class TestF9BraceScannerEscapedBackslash:
    """F9 (MEDIUM): `\\\\{` (escaped backslash + open brace) regression."""

    def test_escaped_backslash_followed_by_open_brace(self):
        # The text is literally: { a \\ { b } c }
        # \\ is an escaped backslash (skip 2 chars), then { increments depth,
        # } decrements, } at end closes. The full body must be returned.
        from ingest.preamble import _scan_balanced_body
        text = r"{a\\{b}c}"
        end = _scan_balanced_body(text, 1)
        assert end == len(text)


class TestF10TopLevelTexPreferred:
    """F10 (MEDIUM): vendored samples/template.tex must NOT shadow the
    paper's own .tex when both exist."""

    def test_top_level_tex_preferred_over_samples(self, tmp_path):
        from ingest.preamble import _select_root_tex
        paper_id = "2307.00001"
        raw_dir = tmp_path / "raw"
        paper_dir = raw_dir / paper_id
        paper_dir.mkdir(parents=True)
        # Top-level paper file
        main = paper_dir / "main.tex"
        main.write_text(
            r"\documentclass{article}" "\n" r"\newcommand{\paperonly}{x}",
            encoding="utf-8",
        )
        # Vendored sample
        samples = paper_dir / "samples"
        samples.mkdir()
        template = samples / "template.tex"
        template.write_text(
            r"\documentclass{article}" "\n" r"\newcommand{\templateonly}{y}",
            encoding="utf-8",
        )
        chosen = _select_root_tex(paper_dir, paper_id)
        assert chosen == main, (
            f"_select_root_tex must prefer top-level main.tex over "
            f"samples/template.tex; got {chosen}"
        )

    def test_falls_back_to_recursive_if_no_top_level(self, tmp_path):
        from ingest.preamble import _select_root_tex
        paper_id = "2307.00001"
        raw_dir = tmp_path / "raw"
        paper_dir = raw_dir / paper_id
        paper_dir.mkdir(parents=True)
        # Only nested .tex
        nested_dir = paper_dir / "src"
        nested_dir.mkdir()
        nested = nested_dir / "main.tex"
        nested.write_text(r"\documentclass{article}", encoding="utf-8")
        chosen = _select_root_tex(paper_dir, paper_id)
        assert chosen == nested
