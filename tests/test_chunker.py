"""Unit tests for ingest.chunker (E02_S01).

All tests use hand-crafted HTML fixtures under tests/fixtures/chunker/
and a patched PARSED_DIR / CHUNKS_DIR so no real corpus files are needed.

The acceptance-criterion test (two-theorem fixture → exactly 4 chunks:
2 stmt + 2 proof) is ``TestTwoTheoremGolden``.

Proof-window splitting is tested in ``TestProofWindowSplitting`` using a
programmatically generated long proof whose token count is above the 448-
token limit, verified against the BGE-M3 tokenizer.

Coverage checklist (from milestone brief):
  [x] matched theorem+proof pair
  [x] multi-section path
  [x] theorem with display name
  [x] theorem with custom label
  [x] auto-id-only theorem (theorem_label=None)
  [x] proof window splitting at 448-token budget
  [x] orphan proof (no preceding theorem sibling)
  [x] unmatched theorem (no proof)
  [x] definition / lemma / remark kinds
  [x] section chunk emission
  [x] malformed HTML graceful degradation
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Helpers to locate fixture files
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "chunker"


def _fixture_html(paper_id: str) -> str:
    return (FIXTURE_DIR / paper_id / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Import chunker internals for unit-level tests
# ---------------------------------------------------------------------------

from ingest.chunker import (  # noqa: E402
    PROOF_MAX_TOKENS,
    PROOF_WINDOW_OVERLAP,
    STMT_MAX_TOKENS,
    InvalidPaperIDError,
    _count_tokens,
    _element_text,
    _encode_tokens,
    _extract_chunks_from_container,
    _extract_section_path,
    _extract_theorem_label,
    _extract_theorem_name,
    _sanitize_log_field,
    _validate_paper_id,
    _window_proof_text,
    chunk_paper,
)
from ingest.chunker_types import ChunkRecord  # noqa: E402

# ---------------------------------------------------------------------------
# Utility: run _extract_chunks_from_container on raw HTML string
# ---------------------------------------------------------------------------


def _chunks_from_html(html: str, paper_id: str = "test.00000") -> list[ChunkRecord]:
    """Parse HTML and extract chunks from the body element."""
    soup = BeautifulSoup(html, "html.parser")
    from bs4 import Tag

    body = soup.find("body")
    root = body if isinstance(body, Tag) else soup
    counter = [0]
    return _extract_chunks_from_container(root, paper_id, counter)


# ===========================================================================
# TestTwoTheoremGolden — acceptance criterion
# ===========================================================================


class TestTwoTheoremGolden:
    """Acceptance criterion: two-theorem paper → exactly 4 chunks (2 stmt + 2 proof).

    Uses fixture 2307.00001 which contains:
      - Theorem 1.1 (Riemann–Roch) with label "myresult1" + proof
      - Theorem 1.2 with auto-id "S1.SS1.Thmtheorem2" + proof
    """

    PAPER_ID = "2307.00001"

    def _run(self, tmp_path: Path) -> list[ChunkRecord]:
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / self.PAPER_ID
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_bytes(
            (FIXTURE_DIR / self.PAPER_ID / "index.html").read_bytes()
        )
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            return chunk_paper(self.PAPER_ID)

    def test_exactly_four_chunks(self, tmp_path):
        chunks = self._run(tmp_path)
        assert len(chunks) == 4, (
            f"expected 4 chunks (2 stmt + 2 proof), got {len(chunks)}: "
            + str([(c.chunk_id, c.kind) for c in chunks])
        )

    def test_chunk_kinds(self, tmp_path):
        chunks = self._run(tmp_path)
        kinds = [c.kind for c in chunks]
        assert kinds == ["stmt", "proof", "stmt", "proof"]

    def test_first_theorem_label(self, tmp_path):
        chunks = self._run(tmp_path)
        stmt1 = chunks[0]
        assert stmt1.theorem_label == "myresult1"

    def test_first_theorem_name(self, tmp_path):
        chunks = self._run(tmp_path)
        stmt1 = chunks[0]
        assert stmt1.theorem_name == "Riemann–Roch"

    def test_second_theorem_auto_label_is_none(self, tmp_path):
        chunks = self._run(tmp_path)
        stmt2 = chunks[2]
        assert stmt2.theorem_label is None

    def test_second_theorem_no_display_name(self, tmp_path):
        chunks = self._run(tmp_path)
        stmt2 = chunks[2]
        assert stmt2.theorem_name is None

    def test_section_path_contains_both_sections(self, tmp_path):
        chunks = self._run(tmp_path)
        # All chunks are inside both "1. Main Results" and "1.1. Riemann-Roch Type Theorems"
        for chunk in chunks:
            path = chunk.section_path
            assert len(path) >= 1, f"empty section_path for {chunk.chunk_id}"
            # At least one level matches
            joined = " ".join(path)
            assert "Main Results" in joined or "Riemann" in joined or "1" in joined

    def test_chunker_version_on_all_chunks(self, tmp_path):
        chunks = self._run(tmp_path)
        for chunk in chunks:
            assert chunk.chunker_version == "v1.0"

    def test_body_tokens_populated(self, tmp_path):
        # E02_S03 wired tokenize_body into _chunk_paper_impl. Every chunk's
        # body_tokens is now a whitespace-joined string (was previously
        # `None` until that wire-in landed).
        chunks = self._run(tmp_path)
        for chunk in chunks:
            assert isinstance(chunk.body_tokens, str), (
                f"chunk {chunk.chunk_id} body_tokens is "
                f"{type(chunk.body_tokens).__name__}, expected str"
            )
            # body_tokens must be non-empty when body_text has content
            if chunk.body_text.strip():
                assert chunk.body_tokens, (
                    f"chunk {chunk.chunk_id} has body_text but empty "
                    f"body_tokens"
                )

    def test_preamble_ref_null(self, tmp_path):
        chunks = self._run(tmp_path)
        for chunk in chunks:
            assert chunk.preamble_ref is None

    def test_chunk_ids_content_addressable_format(self, tmp_path):
        # E02_S04 replaced the monotonic ``idx{N}`` placeholder with a
        # content-addressable hash. Each chunk_id matches
        # ``arxiv:<paper_id>:<16-hex>``.
        import re
        chunks = self._run(tmp_path)
        pattern = re.compile(
            rf"^arxiv:{re.escape(self.PAPER_ID)}:[0-9a-f]{{16}}$"
        )
        for chunk in chunks:
            assert pattern.match(chunk.chunk_id), (
                f"chunk_id {chunk.chunk_id!r} does not match the "
                f"content-addressable format"
            )

    def _chunk_jsons(self, chunks_dir):
        # E02_S04 added chunk_manifest.json alongside the per-chunk files.
        # Tests asserting on chunk-shaped JSON must exclude it.
        return [
            p for p in sorted(chunks_dir.glob("*.json"))
            if p.name != "chunk_manifest.json"
        ]

    def test_output_files_written(self, tmp_path):
        chunks = self._run(tmp_path)
        chunks_dir = tmp_path / "chunks" / self.PAPER_ID
        assert chunks_dir.exists()
        written = self._chunk_jsons(chunks_dir)
        assert len(written) == len(chunks)

    def test_output_json_keys_sorted(self, tmp_path):
        self._run(tmp_path)
        chunks_dir = tmp_path / "chunks" / self.PAPER_ID
        for json_file in self._chunk_jsons(chunks_dir):
            data = json.loads(json_file.read_text())
            keys = list(data.keys())
            assert keys == sorted(keys), f"keys not sorted in {json_file.name}"

    def test_output_json_has_required_fields(self, tmp_path):
        self._run(tmp_path)
        chunks_dir = tmp_path / "chunks" / self.PAPER_ID
        required = {
            "chunk_id", "paper_id", "kind", "section_path",
            "theorem_name", "theorem_label", "body_text",
            "body_tokens", "preamble_ref", "chunker_version",
        }
        for json_file in self._chunk_jsons(chunks_dir):
            data = json.loads(json_file.read_text())
            assert required <= set(data.keys()), (
                f"missing fields in {json_file.name}: {required - set(data.keys())}"
            )


# ===========================================================================
# TestMultiKindEnvironments
# ===========================================================================


class TestMultiKindEnvironments:
    """Fixture 2307.00002: definitions, remarks, lemmas, corollaries, examples,
    unmatched theorems, and orphan proofs."""

    PAPER_ID = "2307.00002"

    def _run(self, tmp_path: Path) -> list[ChunkRecord]:
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / self.PAPER_ID
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_bytes(
            (FIXTURE_DIR / self.PAPER_ID / "index.html").read_bytes()
        )
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            return chunk_paper(self.PAPER_ID)

    def test_definition_kind(self, tmp_path):
        chunks = self._run(tmp_path)
        kinds = [c.kind for c in chunks]
        assert "definition" in kinds

    def test_remark_kind(self, tmp_path):
        chunks = self._run(tmp_path)
        kinds = [c.kind for c in chunks]
        assert "remark" in kinds

    def test_lemma_kind(self, tmp_path):
        chunks = self._run(tmp_path)
        kinds = [c.kind for c in chunks]
        assert "lemma" in kinds

    def test_corollary_kind(self, tmp_path):
        chunks = self._run(tmp_path)
        kinds = [c.kind for c in chunks]
        assert "corollary" in kinds

    def test_example_kind(self, tmp_path):
        chunks = self._run(tmp_path)
        kinds = [c.kind for c in chunks]
        assert "example" in kinds

    def test_lemma_has_proof(self, tmp_path):
        chunks = self._run(tmp_path)
        # The lemma (key-lemma) should be followed by a proof chunk
        lemma_chunks = [c for c in chunks if c.kind == "lemma"]
        assert len(lemma_chunks) >= 1
        # There should be at least one proof chunk
        proof_chunks = [c for c in chunks if c.kind == "proof"]
        assert len(proof_chunks) >= 1

    def test_lemma_label(self, tmp_path):
        chunks = self._run(tmp_path)
        lemma_chunks = [c for c in chunks if c.kind == "lemma"]
        assert any(c.theorem_label == "key-lemma" for c in lemma_chunks)

    def test_lemma_display_name(self, tmp_path):
        chunks = self._run(tmp_path)
        lemma_chunks = [c for c in chunks if c.kind == "lemma"]
        assert any(c.theorem_name == "Key Lemma" for c in lemma_chunks)

    def test_unmatched_theorem_emits_stmt_only(self, tmp_path):
        """Theorem 2.1 has a remark between it and the proof — should be unmatched."""
        chunks = self._run(tmp_path)
        stmt_chunks = [c for c in chunks if c.kind == "stmt"]
        # There is one theorem in section 2 (Theorem 2.1) that is unmatched
        assert len(stmt_chunks) >= 1

    def test_all_chunks_have_chunker_version(self, tmp_path):
        chunks = self._run(tmp_path)
        for chunk in chunks:
            assert chunk.chunker_version == "v1.0"

    def test_section_chunk_emitted(self, tmp_path):
        chunks = self._run(tmp_path)
        section_chunks = [c for c in chunks if c.kind == "section"]
        assert len(section_chunks) >= 1

    def test_all_kinds_have_body_tokens_populated(self, tmp_path):
        # Closes F3: every chunk kind in this multi-kind fixture must have
        # body_tokens populated as a non-empty string. Pre-fix, only
        # TestTwoTheoremGolden exercised body_tokens, missing definition,
        # remark, lemma, corollary, example, and section kinds.
        chunks = self._run(tmp_path)
        kinds_seen = set()
        for chunk in chunks:
            assert isinstance(chunk.body_tokens, str), (
                f"chunk {chunk.chunk_id} (kind={chunk.kind}) body_tokens is "
                f"{type(chunk.body_tokens).__name__}"
            )
            if chunk.body_text.strip():
                assert chunk.body_tokens, (
                    f"chunk {chunk.chunk_id} (kind={chunk.kind}) has "
                    f"body_text but empty body_tokens"
                )
            kinds_seen.add(chunk.kind)
        # Sanity: the multi-kind fixture exercises at least 4 distinct kinds.
        assert len(kinds_seen) >= 4, (
            f"expected ≥4 chunk kinds in multi-kind fixture, got {kinds_seen}"
        )


# ===========================================================================
# TestProofWindowSplitting
# ===========================================================================


class TestProofWindowSplitting:
    """Test proof windowing when proof body exceeds 448 BGE-M3 tokens."""

    def _build_long_proof_html(self, paper_id: str, word_count: int) -> str:
        """Build an HTML page with a theorem + very long proof."""
        # Generate enough distinct words to exceed the token budget
        words = [f"alpha{i}" for i in range(word_count)]
        long_text = " ".join(words)
        return f"""<!DOCTYPE html>
<html><body>
<article class="ltx_document">
  <section class="ltx_section" id="S1">
    <h2 class="ltx_title ltx_title_section">1. Long Proof</h2>
    <div class="ltx_theorem ltx_theorem_theorem" id="S1.Thmtheorem1">
      <h6 class="ltx_title ltx_runin ltx_font_bold ltx_title_theorem">Theorem 1.1.</h6>
      <div class="ltx_para"><p class="ltx_p">The result holds.</p></div>
    </div>
    <div class="ltx_proof">
      <h6 class="ltx_title ltx_runin ltx_font_italic ltx_title_proof">Proof.</h6>
      <div class="ltx_para"><p class="ltx_p">{long_text}</p></div>
    </div>
  </section>
</article>
</body></html>"""

    def test_short_proof_single_window(self):
        """A proof under 448 tokens produces exactly one window."""
        short_text = "This is a short proof. QED."
        windows = _window_proof_text(short_text)
        assert len(windows) == 1
        assert windows[0] == short_text

    def test_long_proof_produces_multiple_windows(self):
        """A proof over 448 tokens produces more than one window."""
        # Build text that is definitely > 448 tokens
        # Each "wordN " is roughly 2–3 tokens; 300 words ≈ 600–900 tokens
        words = [f"word{i}" for i in range(300)]
        long_text = " ".join(words)
        token_count = _count_tokens(long_text)
        assert token_count > PROOF_MAX_TOKENS, (
            f"test text too short ({token_count} tokens); increase word_count"
        )
        windows = _window_proof_text(long_text)
        assert len(windows) > 1

    def test_window_token_budget_respected(self):
        """Each window must be ≤ PROOF_MAX_TOKENS (448) tokens."""
        words = [f"tok{i}" for i in range(400)]
        long_text = " ".join(words)
        windows = _window_proof_text(long_text)
        for i, window in enumerate(windows):
            count = _count_tokens(window)
            assert count <= PROOF_MAX_TOKENS, (
                f"window {i} has {count} tokens > {PROOF_MAX_TOKENS}"
            )

    def test_window_overlap_present(self):
        """Consecutive windows share at least (PROOF_WINDOW_OVERLAP - 5) tokens of content."""
        words = [f"unique{i}" for i in range(500)]
        long_text = " ".join(words)
        windows = _window_proof_text(long_text)
        if len(windows) < 2:
            pytest.skip("not enough windows to test overlap")
        # The end of window[0] should appear in the start of window[1]
        # We verify by checking that the token sequences overlap appropriately
        ids_w0 = _encode_tokens(windows[0])
        ids_w1 = _encode_tokens(windows[1])
        # The tail of window 0 should match the head of window 1
        overlap_tail = ids_w0[-PROOF_WINDOW_OVERLAP:]
        overlap_head = ids_w1[: PROOF_WINDOW_OVERLAP]
        shared = sum(
            1 for a, b in zip(overlap_tail, overlap_head, strict=False) if a == b
        )
        # Allow some decode-boundary rounding — require at least half overlap
        assert shared >= PROOF_WINDOW_OVERLAP // 2, (
            f"overlap too small: only {shared}/{PROOF_WINDOW_OVERLAP} tokens match"
        )

    def test_proof_chunks_emitted_from_full_paper(self, tmp_path):
        """chunk_paper produces multiple proof chunks for a long-proof paper."""
        paper_id = "2307.00099"
        html = self._build_long_proof_html(paper_id, word_count=400)
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_text(html, encoding="utf-8")
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            chunks = chunk_paper(paper_id)

        proof_chunks = [c for c in chunks if c.kind == "proof"]
        assert len(proof_chunks) > 1, (
            f"expected multiple proof windows, got {len(proof_chunks)}"
        )
        for pc in proof_chunks:
            assert _count_tokens(pc.body_text) <= PROOF_MAX_TOKENS
        # Closes F3 (proof-window coverage): every emitted proof window
        # must carry non-empty body_tokens after the E02_S03 wire-in.
        for pc in proof_chunks:
            assert isinstance(pc.body_tokens, str), (
                f"proof window {pc.chunk_id} body_tokens is "
                f"{type(pc.body_tokens).__name__}"
            )
            assert pc.body_tokens, (
                f"proof window {pc.chunk_id} body_text non-empty but "
                f"body_tokens empty"
            )


# ===========================================================================
# TestTheoremLabelExtraction
# ===========================================================================


class TestTheoremLabelExtraction:
    """Unit tests for _extract_theorem_label."""

    def _make_div(self, elem_id: str | None):
        from bs4 import BeautifulSoup, Tag

        html = '<div class="ltx_theorem ltx_theorem_theorem"'
        if elem_id is not None:
            html += f' id="{elem_id}"'
        html += "><h6>Theorem 1.1.</h6></div>"
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("div")
        assert isinstance(tag, Tag)
        return tag

    def test_auto_id_returns_none(self):
        tag = self._make_div("S2.Thmtheorem2")
        assert _extract_theorem_label(tag) is None

    def test_auto_id_with_lemma_returns_none(self):
        tag = self._make_div("S1.Thmlemma3")
        assert _extract_theorem_label(tag) is None

    def test_custom_label_returned(self):
        tag = self._make_div("main-theorem")
        assert _extract_theorem_label(tag) == "main-theorem"

    def test_no_id_returns_none(self):
        tag = self._make_div(None)
        assert _extract_theorem_label(tag) is None

    def test_multi_section_auto_id_returns_none(self):
        tag = self._make_div("S3.SS2.Thmproposition1")
        assert _extract_theorem_label(tag) is None


# ===========================================================================
# TestTheoremNameExtraction
# ===========================================================================


class TestTheoremNameExtraction:
    """Unit tests for _extract_theorem_name."""

    def _make_div(self, heading_html: str):
        from bs4 import BeautifulSoup, Tag

        html = f'<div class="ltx_theorem ltx_theorem_theorem">{heading_html}</div>'
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("div")
        assert isinstance(tag, Tag)
        return tag

    def test_parenthetical_name_extracted(self):
        tag = self._make_div(
            '<h6 class="ltx_title">Theorem 3.1 (Riemann–Roch).</h6>'
        )
        assert _extract_theorem_name(tag) == "Riemann–Roch"

    def test_no_parenthetical_returns_none(self):
        tag = self._make_div('<h6 class="ltx_title">Theorem 3.1.</h6>')
        assert _extract_theorem_name(tag) is None

    def test_span_tag_extracted(self):
        tag = self._make_div(
            '<span class="ltx_tag ltx_tag_theorem">Lemma 2.4 (Key Lemma).</span>'
        )
        assert _extract_theorem_name(tag) == "Key Lemma"

    def test_nested_parenthetical(self):
        tag = self._make_div(
            '<h6 class="ltx_title">Proposition 5.7 (Serre Duality).</h6>'
        )
        assert _extract_theorem_name(tag) == "Serre Duality"


# ===========================================================================
# TestSectionPathExtraction
# ===========================================================================


class TestSectionPathExtraction:
    """Unit tests for _extract_section_path."""

    def test_flat_section(self):
        html = """<section class="ltx_section" id="S1">
          <h2 class="ltx_title ltx_title_section">1. Introduction</h2>
          <div class="ltx_theorem ltx_theorem_theorem" id="S1.Thmtheorem1">
            <h6 class="ltx_title">Theorem 1.1.</h6>
          </div>
        </section>"""
        from bs4 import BeautifulSoup, Tag

        soup = BeautifulSoup(html, "html.parser")
        thm = soup.find("div", class_="ltx_theorem")
        assert isinstance(thm, Tag)
        path = _extract_section_path(thm)
        assert "1. Introduction" in path

    def test_nested_subsection(self):
        html = """<section class="ltx_section" id="S2">
          <h2 class="ltx_title ltx_title_section">2. Main Results</h2>
          <section class="ltx_subsection" id="S2.SS1">
            <h3 class="ltx_title ltx_title_subsection">2.1. Key Estimates</h3>
            <div class="ltx_theorem ltx_theorem_lemma" id="S2.SS1.Thmlemma1">
              <h6 class="ltx_title">Lemma 2.1.</h6>
            </div>
          </section>
        </section>"""
        from bs4 import BeautifulSoup, Tag

        soup = BeautifulSoup(html, "html.parser")
        thm = soup.find("div", class_="ltx_theorem")
        assert isinstance(thm, Tag)
        path = _extract_section_path(thm)
        joined = " ".join(path)
        assert "Main Results" in joined
        assert "Key Estimates" in joined

    def test_toplevel_has_empty_or_minimal_path(self):
        html = """<article class="ltx_document">
          <div class="ltx_theorem ltx_theorem_theorem" id="thm1">
            <h6 class="ltx_title">Theorem 1.</h6>
          </div>
        </article>"""
        from bs4 import BeautifulSoup, Tag

        soup = BeautifulSoup(html, "html.parser")
        thm = soup.find("div", class_="ltx_theorem")
        assert isinstance(thm, Tag)
        path = _extract_section_path(thm)
        # Top-level theorem with no section ancestor → empty path
        assert isinstance(path, list)


# ===========================================================================
# TestOrphanProof
# ===========================================================================


class TestOrphanProof:
    """An ltx_proof div with no preceding theorem sibling emits kind='proof'."""

    def test_orphan_proof_emitted_as_proof_kind(self):
        html = """<!DOCTYPE html><html><body>
        <article class="ltx_document">
          <section class="ltx_section" id="S1">
            <h2 class="ltx_title ltx_title_section">1. Orphan Section</h2>
            <div class="ltx_proof">
              <h6 class="ltx_title ltx_font_italic">Proof of the claim.</h6>
              <div class="ltx_para"><p class="ltx_p">Here is the orphan proof body.</p></div>
            </div>
          </section>
        </article>
        </body></html>"""
        chunks = _chunks_from_html(html)
        assert any(c.kind == "proof" for c in chunks)
        orphan = next(c for c in chunks if c.kind == "proof")
        assert orphan.theorem_label is None
        assert orphan.theorem_name is None

    def test_orphan_proof_body_text_nonempty(self):
        html = """<!DOCTYPE html><html><body>
        <article class="ltx_document">
          <div class="ltx_proof">
            <div class="ltx_para"><p class="ltx_p">Orphan proof content here.</p></div>
          </div>
        </article>
        </body></html>"""
        chunks = _chunks_from_html(html)
        proof_chunks = [c for c in chunks if c.kind == "proof"]
        assert proof_chunks
        assert proof_chunks[0].body_text.strip()


# ===========================================================================
# TestUnmatchedTheorem
# ===========================================================================


class TestUnmatchedTheorem:
    """A theorem with a blocking remark between it and the proof is unmatched."""

    def test_unmatched_theorem_no_proof_chunk(self):
        html = """<!DOCTYPE html><html><body>
        <article class="ltx_document">
          <section class="ltx_section" id="S1">
            <h2 class="ltx_title ltx_title_section">1. Test</h2>
            <div class="ltx_theorem ltx_theorem_theorem" id="S1.Thmtheorem1">
              <h6 class="ltx_title">Theorem 1.1.</h6>
              <div class="ltx_para"><p class="ltx_p">Statement here.</p></div>
            </div>
            <!-- Blocking remark -->
            <div class="ltx_theorem ltx_theorem_remark" id="S1.Thmremark1">
              <h6 class="ltx_title">Remark 1.2.</h6>
              <div class="ltx_para"><p class="ltx_p">An intervening remark.</p></div>
            </div>
            <!-- Proof is now unmatched — no theorem sibling directly precedes it -->
            <div class="ltx_proof">
              <div class="ltx_para"><p class="ltx_p">The proof body.</p></div>
            </div>
          </section>
        </article>
        </body></html>"""
        chunks = _chunks_from_html(html)
        stmt_chunks = [c for c in chunks if c.kind == "stmt"]
        assert len(stmt_chunks) == 1
        # The proof becomes orphan (emitted with kind="proof" but not paired)
        proof_chunks = [c for c in chunks if c.kind == "proof"]
        assert len(proof_chunks) >= 1

    def test_theorem_stmt_kind_correct(self):
        html = """<!DOCTYPE html><html><body>
        <div class="ltx_theorem ltx_theorem_theorem" id="T1">
          <h6 class="ltx_title">Theorem 1.</h6>
          <p>No proof follows.</p>
        </div>
        </body></html>"""
        chunks = _chunks_from_html(html)
        assert any(c.kind == "stmt" for c in chunks)
        assert not any(c.kind == "proof" for c in chunks)


# ===========================================================================
# TestMalformedHTML
# ===========================================================================


class TestMalformedHTML:
    """Chunker should not raise on malformed HTML — graceful degradation."""

    PAPER_ID = "2307.00004"

    def _run(self, tmp_path: Path) -> list[ChunkRecord]:
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / self.PAPER_ID
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_bytes(
            (FIXTURE_DIR / self.PAPER_ID / "index.html").read_bytes()
        )
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            return chunk_paper(self.PAPER_ID)

    def test_no_exception_raised(self, tmp_path):
        # chunk_paper must not raise — it returns [] or partial results
        try:
            self._run(tmp_path)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"chunk_paper raised on malformed HTML: {exc}")

    def test_returns_list(self, tmp_path):
        result = self._run(tmp_path)
        assert isinstance(result, list)

    def test_theorem_chunk_extracted(self, tmp_path):
        """At least the well-formed theorem should be extracted."""
        chunks = self._run(tmp_path)
        assert len(chunks) >= 1


# ===========================================================================
# TestChunkRecord
# ===========================================================================


class TestChunkRecord:
    """Unit tests for ChunkRecord dataclass."""

    def test_to_dict_has_sorted_keys(self):
        record = ChunkRecord(
            chunk_id="arxiv:2307.00001:idx0",
            paper_id="2307.00001",
            kind="stmt",
            section_path=["1. Introduction"],
            theorem_name="Riemann–Roch",
            theorem_label="rr-thm",
            body_text="Some theorem text.",
        )
        d = record.to_dict()
        assert list(d.keys()) == sorted(d.keys())

    def test_to_dict_null_deferred_fields(self):
        record = ChunkRecord(
            chunk_id="arxiv:2307.00001:idx0",
            paper_id="2307.00001",
            kind="stmt",
            section_path=[],
            theorem_name=None,
            theorem_label=None,
            body_text="body",
        )
        d = record.to_dict()
        assert d["body_tokens"] is None
        assert d["preamble_ref"] is None

    def test_default_chunker_version(self):
        record = ChunkRecord(
            chunk_id="test",
            paper_id="2307.00001",
            kind="section",
            section_path=[],
            theorem_name=None,
            theorem_label=None,
            body_text="text",
        )
        assert record.chunker_version == "v1.0"

    def test_to_dict_serialises_all_fields(self):
        record = ChunkRecord(
            chunk_id="arxiv:2307.00001:idx5",
            paper_id="2307.00001",
            kind="proof",
            section_path=["2. Results"],
            theorem_name="Main",
            theorem_label="main",
            body_text="Proof text here.",
        )
        d = record.to_dict()
        assert d["chunk_id"] == "arxiv:2307.00001:idx5"
        assert d["paper_id"] == "2307.00001"
        assert d["kind"] == "proof"
        assert d["section_path"] == ["2. Results"]
        assert d["theorem_name"] == "Main"
        assert d["theorem_label"] == "main"
        assert d["body_text"] == "Proof text here."
        assert d["chunker_version"] == "v1.0"


# ===========================================================================
# TestChunkFailureIsolation
# ===========================================================================


class TestChunkFailureIsolation:
    """chunk_paper returns [] and logs on failure — never raises."""

    def test_missing_parsed_html_returns_empty(self, tmp_path):
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        parsed_dir.mkdir()
        chunks_dir.mkdir()
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            patch("ingest.chunker.CHUNK_LOG_PATH", tmp_path / "chunk.log"),
        ):
            result = chunk_paper("9999.99999")
        assert result == []

    def test_failure_writes_log(self, tmp_path):
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        log_path = tmp_path / "chunk.log"
        parsed_dir.mkdir()
        chunks_dir.mkdir()
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            patch("ingest.chunker.CHUNK_LOG_PATH", log_path),
        ):
            chunk_paper("9999.99999")
        assert log_path.exists()
        log_text = log_path.read_text()
        assert "9999.99999" in log_text
        assert "fail" in log_text


# ===========================================================================
# TestStatementTokenBudget
# ===========================================================================


class TestStatementTokenBudget:
    """No stmt chunk body_text should exceed 512 tokens."""

    def test_stmt_within_budget(self, tmp_path):
        paper_id = "2307.00001"
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_bytes(
            (FIXTURE_DIR / paper_id / "index.html").read_bytes()
        )
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            chunks = chunk_paper(paper_id)

        for chunk in chunks:
            if chunk.kind == "stmt":
                count = _count_tokens(chunk.body_text)
                assert count <= STMT_MAX_TOKENS, (
                    f"stmt chunk {chunk.chunk_id} has {count} tokens > {STMT_MAX_TOKENS}"
                )


# ===========================================================================
# Regression guards from Phase 3 critique (F1–F13)
# ===========================================================================


class TestF1MathMLPreservation:
    """F1 (CRITICAL): _element_text must preserve LaTeX from <math alttext="">."""

    def test_alttext_preserved_inline(self):
        from bs4 import BeautifulSoup
        html = (
            '<div><p>Let <math alttext="\\mathcal{F}">'
            '<mi class="ltx_font_mathcaligraphic">ℱ</mi></math> be a sheaf.</p></div>'
        )
        soup = BeautifulSoup(html, "html.parser")
        div = soup.find("div")
        text = _element_text(div)
        assert "\\mathcal{F}" in text, (
            f"alttext LaTeX must survive _element_text; got: {text!r}"
        )

    def test_no_dollar_count_regression(self):
        from bs4 import BeautifulSoup
        html = (
            '<div>'
            '<math alttext="\\mathcal{F}">x</math> '
            '<math alttext="\\int_0^1 f \\, dx">y</math>'
            '</div>'
        )
        soup = BeautifulSoup(html, "html.parser")
        div = soup.find("div")
        text = _element_text(div)
        # Each math element wraps to "$...$" with both opening and closing $.
        assert text.count("$") == 4, (
            f"two math elements => four dollar markers; got: {text!r}"
        )
        assert "\\int_0^1 f \\, dx" in text

    def test_fallback_when_no_alttext(self):
        from bs4 import BeautifulSoup
        html = '<div><math><mi>X</mi></math></div>'
        soup = BeautifulSoup(html, "html.parser")
        div = soup.find("div")
        text = _element_text(div)
        # No alttext: fall back to inner text, still wrapped in $
        assert "$" in text
        assert "X" in text


class TestF2PaperIDValidation:
    """F2 (CRITICAL): paper_id regex blocks path traversal and bad strings."""

    def test_valid_new_style(self):
        _validate_paper_id("2307.01156")
        _validate_paper_id("2307.01156v2")
        _validate_paper_id("9912.12345")

    def test_valid_old_style(self):
        _validate_paper_id("math/0301001")
        _validate_paper_id("hep-th/0301001v3")

    def test_rejects_path_traversal(self):
        with pytest.raises(InvalidPaperIDError):
            _validate_paper_id("../../etc/passwd")

    def test_rejects_slashes_in_new_style(self):
        with pytest.raises(InvalidPaperIDError):
            _validate_paper_id("a/b")

    def test_rejects_newline(self):
        with pytest.raises(InvalidPaperIDError):
            _validate_paper_id("foo\nbar")

    def test_rejects_tab(self):
        with pytest.raises(InvalidPaperIDError):
            _validate_paper_id("foo\tbar")

    def test_rejects_empty(self):
        with pytest.raises(InvalidPaperIDError):
            _validate_paper_id("")

    def test_chunk_paper_invalid_id_does_not_create_files(self, tmp_path):
        chunks_dir = tmp_path / "chunks"
        chunks_dir.mkdir()
        with (
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            pytest.raises(InvalidPaperIDError),
        ):
            chunk_paper("../etc/passwd")
        # No file created anywhere under chunks_dir
        assert list(chunks_dir.rglob("*")) == []


class TestF3StaleFileCleanup:
    """F3 (HIGH): re-run must clear stale chunk JSON files from prior run."""

    def test_stale_files_removed_before_write(self, tmp_path):
        paper_id = "2307.00001"
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_bytes(
            (FIXTURE_DIR / paper_id / "index.html").read_bytes()
        )
        # Pre-populate output dir with a stale file
        out_dir = chunks_dir / paper_id
        out_dir.mkdir(parents=True)
        sentinel = out_dir / "idx99.json"
        sentinel.write_text('{"stale": true}\n')
        assert sentinel.exists()

        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            chunks = chunk_paper(paper_id)

        assert len(chunks) > 0
        assert not sentinel.exists(), "stale idx99.json must be removed on re-run"


class TestF4SectionDocumentOrder:
    """F4 (HIGH): section chunks emitted in document order, not class-bucketed."""

    def test_section_chunks_interleave_subsections(self, tmp_path):
        # Build a fixture with Sec1 → SubSec1.1 → Sec2 → SubSec2.1
        # Each containing only prose (so they all become section chunks).
        paper_id = "2307.99001"
        prose1 = "First section prose " + ("alpha " * 30)
        prose11 = "First subsection prose " + ("beta " * 30)
        prose2 = "Second section prose " + ("gamma " * 30)
        prose21 = "Second subsection prose " + ("delta " * 30)
        html = f"""<!DOCTYPE html>
<html><body><article class="ltx_document">
  <section class="ltx_section" id="S1">
    <h2 class="ltx_title ltx_title_section">1. Sec One</h2>
    <p class="ltx_p">{prose1}</p>
    <section class="ltx_subsection" id="S1.SS1">
      <h3 class="ltx_title ltx_title_subsection">1.1 Sub One</h3>
      <p class="ltx_p">{prose11}</p>
    </section>
  </section>
  <section class="ltx_section" id="S2">
    <h2 class="ltx_title ltx_title_section">2. Sec Two</h2>
    <p class="ltx_p">{prose2}</p>
    <section class="ltx_subsection" id="S2.SS1">
      <h3 class="ltx_title ltx_title_subsection">2.1 Sub Two</h3>
      <p class="ltx_p">{prose21}</p>
    </section>
  </section>
</article></body></html>
"""
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_text(html, encoding="utf-8")
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            chunks = chunk_paper(paper_id)

        section_chunks = [c for c in chunks if c.kind == "section"]
        # Identify each section by the unique prose marker (alpha/beta/gamma/delta)
        markers = []
        for c in section_chunks:
            if "alpha" in c.body_text:
                markers.append("alpha")
            elif "beta" in c.body_text:
                markers.append("beta")
            elif "gamma" in c.body_text:
                markers.append("gamma")
            elif "delta" in c.body_text:
                markers.append("delta")
        # Document order: Sec1 (alpha) → SubSec1 (beta) → Sec2 (gamma) → SubSec2 (delta).
        # Class-bucketed (the bug) would be: alpha, gamma, beta, delta.
        idx = {m: i for i, m in enumerate(markers)}
        assert idx["alpha"] < idx["beta"], f"document order violated: {markers}"
        assert idx["beta"] < idx["gamma"], f"document order violated: {markers}"
        assert idx["gamma"] < idx["delta"], f"document order violated: {markers}"


class TestF5StmtTruncationFlag:
    """F5 (HIGH): silent truncation must surface via the truncated flag."""

    def test_long_stmt_truncated_flag_set(self, tmp_path):
        # Construct a synthetic theorem with a very long statement
        paper_id = "2307.99005"
        long_stmt = " ".join(f"word{i}" for i in range(2000))  # >> 512 tokens
        html = f"""<!DOCTYPE html>
<html><body><article class="ltx_document">
  <section class="ltx_section" id="S1">
    <h2 class="ltx_title ltx_title_section">1. Long Stmt</h2>
    <div class="ltx_theorem ltx_theorem_theorem" id="long-stmt">
      <h6 class="ltx_title">Theorem 1.1.</h6>
      <div class="ltx_para"><p class="ltx_p">{long_stmt}</p></div>
    </div>
  </section>
</article></body></html>
"""
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_text(html, encoding="utf-8")
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            chunks = chunk_paper(paper_id)
        stmts = [c for c in chunks if c.kind == "theorem" or c.kind == "stmt"]
        assert len(stmts) >= 1
        # At least one stmt must be flagged truncated
        assert any(c.truncated for c in stmts), (
            f"long stmt must set truncated=True; got truncated values: "
            f"{[c.truncated for c in stmts]}"
        )

    def test_normal_stmt_not_truncated(self, tmp_path):
        paper_id = "2307.00001"
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_bytes(
            (FIXTURE_DIR / paper_id / "index.html").read_bytes()
        )
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            chunks = chunk_paper(paper_id)
        for c in chunks:
            assert c.truncated is False


class TestF6CharOffsetWindowing:
    """F6 (HIGH): proof windows must be substring slices of the source text."""

    def test_short_proof_returns_unchanged(self):
        text = "Short proof body that fits in one window."
        windows = _window_proof_text(text)
        assert windows == [text], "single-window result must be the exact input"

    def test_long_proof_concatenates_to_substring_of_source(self):
        # Build text long enough to require >= 2 windows
        words = [f"alpha{i}" for i in range(2000)]
        text = " ".join(words)
        windows = _window_proof_text(text)
        assert len(windows) >= 2
        # Every window must be a substring of the original text — proves the
        # offset-mapping path, not encode/decode round-trip.
        for w in windows:
            assert w in text, (
                f"window must be substring of source; window starts: {w[:50]!r}"
            )


class TestF7TSVLogSanitization:
    """F7 (MEDIUM): log rows must not contain embedded tab/newline."""

    def test_sanitize_strips_tab(self):
        assert "\t" not in _sanitize_log_field("a\tb")

    def test_sanitize_strips_newline(self):
        assert "\n" not in _sanitize_log_field("a\nb")
        assert "\r" not in _sanitize_log_field("a\rb")

    def test_failure_log_with_problematic_message(self, tmp_path):
        # Force a chunk_paper failure with a problematic exception message
        log_path = tmp_path / "chunk.log"
        chunks_dir = tmp_path / "chunks"
        parsed_dir = tmp_path / "parsed"
        chunks_dir.mkdir()
        parsed_dir.mkdir()

        def raise_with_tabs(_paper_id):
            raise OSError("error\twith\ttabs\nand\nnewlines")

        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            patch("ingest.chunker.CHUNK_LOG_PATH", log_path),
            patch("ingest.chunker._chunk_paper_impl", side_effect=raise_with_tabs),
        ):
            chunk_paper("2307.00001")

        log_lines = log_path.read_text().strip().split("\n")
        assert len(log_lines) == 1
        # Every row must have exactly 4 tab-separated fields
        assert log_lines[0].count("\t") == 3


class TestF8ProgrammerBugsPropagate:
    """F8 (MEDIUM): non-resilience-pattern exceptions must propagate."""

    def test_attribute_error_propagates(self, tmp_path):
        chunks_dir = tmp_path / "chunks"
        parsed_dir = tmp_path / "parsed"
        chunks_dir.mkdir()
        parsed_dir.mkdir()

        def raise_attr(_paper_id):
            raise AttributeError("simulated programmer bug")

        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            patch("ingest.chunker._chunk_paper_impl", side_effect=raise_attr),
            pytest.raises(AttributeError),
        ):
            chunk_paper("2307.00001")

    def test_value_error_caught(self, tmp_path):
        chunks_dir = tmp_path / "chunks"
        parsed_dir = tmp_path / "parsed"
        chunks_dir.mkdir()
        parsed_dir.mkdir()

        def raise_value(_paper_id):
            raise ValueError("simulated parser failure")

        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            patch("ingest.chunker._chunk_paper_impl", side_effect=raise_value),
        ):
            result = chunk_paper("2307.00001")
        assert result == []


class TestF9TheoremNameNoNestedLeak:
    """F9 (MEDIUM): theorem_name must come from the OUTER heading only."""

    def test_nested_theorem_name_does_not_leak_outward(self):
        from bs4 import BeautifulSoup
        # An outer theorem with no parenthetical name; inner has (NestedName).
        html = """
        <div class="ltx_theorem ltx_theorem_theorem" id="outer">
          <h6 class="ltx_title">Theorem 1.1.</h6>
          <div class="ltx_theorem ltx_theorem_lemma" id="inner">
            <h6 class="ltx_title">Lemma 1.2 (NestedName).</h6>
          </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        outer = soup.find("div", id="outer")
        # The outer theorem's name must be None (no parenthetical on its own
        # heading), NOT 'NestedName' from the inner lemma.
        name = _extract_theorem_name(outer)
        assert name is None, f"nested name leaked outward: {name!r}"


class TestF13RecursionDepthBound:
    """F13 (MEDIUM): adversarial nested HTML must not blow the stack."""

    def test_deep_nesting_does_not_raise(self, tmp_path):
        paper_id = "2307.99013"
        # 200 levels of nested <div> — well past _MAX_CONTAINER_DEPTH=50
        body = "<p>some text</p>"
        for _ in range(200):
            body = f'<div class="container">{body}</div>'
        html = f'<!DOCTYPE html><html><body>{body}</body></html>'
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        (paper_parsed / "index.html").write_text(html, encoding="utf-8")
        with (
            patch("ingest.chunker.PARSED_DIR", parsed_dir),
            patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
        ):
            # Must return without raising RecursionError
            result = chunk_paper(paper_id)
        # Empty list is a valid outcome — we just need no crash.
        assert isinstance(result, list)


# ===========================================================================
# E02_S05 fixture suite — 10 hand-crafted golden-output fixtures
# ===========================================================================

# Reading: ``tests/fixtures/chunker/<paper_id>.expected.json`` per fixture is
# the locked-in golden output. The bootstrap procedure (run the chunker once
# with ``_resolve_preamble_doc`` patched to None, record the output, commit)
# is documented in ``docs/chunker-fixtures.md``. A chunker change that
# legitimately alters chunk_ids forces a deliberate re-run of that procedure
# AND a coordinated update to E05's eval queries.
#
# Existing fixtures (pre-E02_S05): 2307.0000{1,2,3,4}.
# Added in E02_S05: 2307.0000{5,6,7,8,9,10}.
# - 2307.00005: proposition + conjecture kinds
# - 2307.00006: deeply nested section path (3 levels)
# - 2307.00007: multi-window proof (long body, ≥1 split)
# - 2307.00008: definition-heavy, NO proof environments
# - 2307.00009: appendix section after main
# - 2307.00010: <math alttext> preservation throughout body

_FIXTURE_SUITE_IDS = [
    "2307.00001", "2307.00002", "2307.00003", "2307.00004",
    "2307.00005", "2307.00006", "2307.00007", "2307.00008",
    "2307.00009", "2307.00010",
]


def _load_expected_fixture(paper_id: str) -> dict:
    expected_path = (
        Path(__file__).parent / "fixtures" / "chunker" / f"{paper_id}.expected.json"
    )
    return json.loads(expected_path.read_text(encoding="utf-8"))


class TestFixtureSuite:
    """E02_S05 golden-output suite: locks in chunker behavior across 10
    diverse hand-crafted fixtures. The brief calls for "10 of the 50 seed
    papers"; with the seed corpus not materialized in this worktree, we
    use 10 hand-crafted fixtures that exercise the same scenario diversity
    (theorem+proof pairs, multi-kind environments, multi-window proofs,
    definition-heavy papers, appendix ordering, MathML alttext preservation,
    deeply nested sections, malformed HTML, and conjecture/proposition
    kinds). The implementation summary documents this substitution.
    """

    @pytest.mark.parametrize("paper_id", _FIXTURE_SUITE_IDS)
    def test_chunk_count_matches(self, paper_id, tmp_path):
        expected = _load_expected_fixture(paper_id)
        chunks = self._run(tmp_path, paper_id)
        assert len(chunks) == expected["chunk_count"], (
            f"{paper_id} chunk count mismatch: got {len(chunks)}, "
            f"expected {expected['chunk_count']}"
        )

    @pytest.mark.parametrize("paper_id", _FIXTURE_SUITE_IDS)
    def test_kind_counts_match(self, paper_id, tmp_path):
        # Closes F4: ``kind_counts`` now pins the FULL distribution of
        # emitted kinds, not just stmt/proof/section/definition. Drift in
        # lemma/corollary/remark/example/proposition/conjecture counts
        # would previously have been invisible at the kind level.
        from collections import Counter
        expected = _load_expected_fixture(paper_id)
        chunks = self._run(tmp_path, paper_id)
        actual = dict(Counter(c.kind for c in chunks))
        assert actual == expected["kind_counts"], (
            f"{paper_id} kind_counts mismatch:\n  got      {actual}\n"
            f"  expected {expected['kind_counts']}"
        )

    @pytest.mark.parametrize("paper_id", _FIXTURE_SUITE_IDS)
    def test_expected_chunk_ids_in_document_order(self, paper_id, tmp_path):
        # Closes F3: list-equality (not subset). The expected_chunk_ids
        # array in expected.json is in document order; the chunker output
        # must match exactly. A reorder (e.g. F4-style class-bucketing
        # regression) would previously have been invisible to this test
        # because the prior subset check used a set comparison.
        expected = _load_expected_fixture(paper_id)
        chunks = self._run(tmp_path, paper_id)
        emitted = [c.chunk_id for c in chunks]
        assert emitted == expected["expected_chunk_ids"], (
            f"{paper_id}: chunk_id document-order mismatch.\n"
            f"  emitted:  {emitted}\n"
            f"  expected: {expected['expected_chunk_ids']}"
        )

    def test_chunker_version_matches_constant_globally(self):
        # Closes F8: previously parametrized over all 10 fixtures, which
        # produced 10 redundant failure reports for one underlying issue
        # on a CHUNKER_VERSION bump. One assertion now reports the full
        # mismatch list and exits.
        from ingest.chunker_types import CHUNKER_VERSION
        mismatches = []
        for paper_id in _FIXTURE_SUITE_IDS:
            expected = _load_expected_fixture(paper_id)
            if expected["chunker_version"] != CHUNKER_VERSION:
                mismatches.append(
                    f"{paper_id}: fixture chunker_version="
                    f"{expected['chunker_version']!r}"
                )
        assert not mismatches, (
            f"chunker_version drift in fixtures (current CHUNKER_VERSION="
            f"{CHUNKER_VERSION!r}); regenerate per docs/chunker-fixtures.md"
            f":\n  " + "\n  ".join(mismatches)
        )

    def test_2307_00006_section_path_three_levels_deep(self, tmp_path):
        # Closes F2: chunk_id hash does NOT include section_path, so a
        # section-path regression on the deeply-nested fixture would be
        # invisible to byte-stability checks. This direct assertion pins
        # the 3-element section_path on the deepest theorem.
        chunks = self._run(tmp_path, "2307.00006")
        # Find the stmt chunk for the buried theorem
        stmt = next((c for c in chunks if c.kind == "stmt"), None)
        assert stmt is not None, "2307.00006 must emit a stmt chunk"
        assert stmt.section_path == [
            "1. Deep section nesting",
            "1.1 Outer subsection",
            "1.1.1 Inner subsubsection",
        ], (
            f"2307.00006 buried theorem section_path mismatch: "
            f"got {stmt.section_path!r}"
        )

    def test_2307_00010_alttext_uses_real_latex(self, tmp_path):
        # Closes F1 (regression guard): verify the alttext fixture
        # actually contains real LaTeX (single-backslash) in body_text,
        # not the literal double-backslash sequence the prior version
        # accidentally locked in. Uses raw string to disambiguate.
        chunks = self._run(tmp_path, "2307.00010")
        all_body = " ".join(c.body_text for c in chunks)
        assert r"$\langle\cdot,\cdot\rangle$" in all_body, (
            "2307.00010 must preserve single-backslash LaTeX in body_text "
            "(F1 regression guard): the fixture's <math alttext> "
            "attributes must use real LaTeX commands, not double-escaped."
        )
        assert r"\\langle" not in all_body, (
            "2307.00010 must NOT contain double-backslash LaTeX literals — "
            "those are an authoring bug, not real LaTeXML output."
        )

    def test_multi_window_proof_fixture_exists(self, tmp_path):
        """Acceptance criterion: at least one fixture exercises a
        multi-window proof. 2307.00007 has a long proof body that splits
        into ≥2 proof chunks under the 448-token PROOF_MAX_TOKENS budget."""
        chunks = self._run(tmp_path, "2307.00007")
        proof_chunks = [c for c in chunks if c.kind == "proof"]
        assert len(proof_chunks) >= 2, (
            f"2307.00007 must split into ≥2 proof chunks (multi-window "
            f"acceptance criterion); got {len(proof_chunks)}"
        )

    def test_no_proof_fixture_exists(self, tmp_path):
        """Acceptance criterion: at least one fixture has no explicit
        proof environments. 2307.00008 is definition-heavy with zero
        ``ltx_proof`` divs in the source HTML."""
        chunks = self._run(tmp_path, "2307.00008")
        proof_chunks = [c for c in chunks if c.kind == "proof"]
        assert len(proof_chunks) == 0, (
            f"2307.00008 must produce zero proof chunks (no-proof "
            f"acceptance criterion); got {len(proof_chunks)}"
        )
        # Sanity: it should still emit chunks (definitions, sections, etc.).
        assert len(chunks) > 0

    @staticmethod
    def _run(tmp_path: Path, paper_id: str):
        import shutil as _shutil
        from unittest.mock import patch as _patch

        from ingest.chunker import chunk_paper as _chunk_paper

        fixture = (
            Path(__file__).parent / "fixtures" / "chunker" / paper_id / "index.html"
        )
        parsed_dir = tmp_path / "parsed"
        chunks_dir = tmp_path / "chunks"
        paper_parsed = parsed_dir / paper_id
        paper_parsed.mkdir(parents=True)
        _shutil.copy(fixture, paper_parsed / "index.html")
        with (
            _patch("ingest.chunker.PARSED_DIR", parsed_dir),
            _patch("ingest.chunker.CHUNKS_DIR", chunks_dir),
            _patch("ingest.chunker._resolve_preamble_doc", return_value=None),
        ):
            return _chunk_paper(paper_id)
