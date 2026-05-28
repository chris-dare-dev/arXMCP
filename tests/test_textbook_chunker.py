"""Tests for the hierarchical textbook chunker (textbook-ingest-m7).

Mirrors `tests/test_chunker.py`'s patched-NOTEBOOKS_BASE approach: copy
a synthetic LaTeXML-shaped HTML5 fixture into a tmp notebook layout,
patch `ingest.textbook_chunker.NOTEBOOKS_BASE`, run `chunk_textbook`.

The tokenizer (BGE-M3 vocab, ~5 MB cached) is loaded by the reused
`_count_tokens` primitive — same as the arXiv chunker tests, which run
without a `requires_model` marker.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from ingest.identifiers import is_valid_chunk_id
from ingest.textbook_chunker import (
    TEXTBOOK_CHUNKER_VERSION,
    _collect_chapter_titles,
    _compute_textbook_chunk_id,
    _flat_paper_id,
    _resolve_notebook_dir,
    _textbook_chunks_dir,
    _textbook_html_path,
    chunk_textbook,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "textbook_chunker"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_fixture(
    base: Path, slug: str, paper_id: str, fixture_id: str = "two-chapter-book",
) -> None:
    """Copy a fixture's index.html into the tmp notebook parsed layout."""
    flat = _flat_paper_id(paper_id)
    dest = base / slug / "parsed" / flat
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_ROOT / fixture_id / "index.html", dest / "index.html")


def _write_html(base: Path, slug: str, paper_id: str, html: str) -> None:
    """Write raw HTML into the tmp notebook parsed layout."""
    flat = _flat_paper_id(paper_id)
    dest = base / slug / "parsed" / flat
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Pure-unit: path builders + chunk-id
# ---------------------------------------------------------------------------


class TestPathBuilders:
    @pytest.mark.parametrize(
        "paper_id,expected_flat",
        [
            ("textbook:my-book", "textbook_my-book"),
            ("textbook:two-chapter-book", "textbook_two-chapter-book"),
            ("hep-th/0001234", "hep-th_0001234"),
        ],
    )
    def test_flat_paper_id(self, paper_id: str, expected_flat: str) -> None:
        assert _flat_paper_id(paper_id) == expected_flat

    def test_html_path_under_notebook(self, tmp_path: Path) -> None:
        nb_dir = tmp_path / "notebooks" / "sv-book"
        p = _textbook_html_path(nb_dir, "textbook:sv-book")
        assert p.parts[-3:] == ("parsed", "textbook_sv-book", "index.html")
        # nb_dir / parsed / <flat> / index.html → 3 parents up is nb_dir.
        assert p.parent.parent.parent == nb_dir

    def test_chunks_dir_under_notebook(self, tmp_path: Path) -> None:
        nb_dir = tmp_path / "notebooks" / "sv-book"
        d = _textbook_chunks_dir(nb_dir, "textbook:sv-book")
        assert d.parts[-2:] == ("chunks", "textbook_sv-book")
        # nb_dir / chunks / <flat> → 2 parents up is nb_dir.
        assert d.parent.parent == nb_dir


class TestComputeTextbookChunkId:
    def test_prefix_is_textbook(self) -> None:
        cid = _compute_textbook_chunk_id("my-book", "", "some body")
        assert cid.startswith("textbook:my-book:")

    def test_round_trips_through_validator(self) -> None:
        cid = _compute_textbook_chunk_id("my-book", "", "theorem body")
        assert is_valid_chunk_id(cid), f"{cid} failed is_valid_chunk_id"

    def test_deterministic(self) -> None:
        a = _compute_textbook_chunk_id("b", "pre", "body")
        c = _compute_textbook_chunk_id("b", "pre", "body")
        assert a == c

    def test_body_change_changes_id(self) -> None:
        a = _compute_textbook_chunk_id("b", "", "body one")
        c = _compute_textbook_chunk_id("b", "", "body two")
        assert a != c

    def test_nfc_normalization_matches_arxiv_discipline(self) -> None:
        # NFC vs NFD of the same logical string must hash identically
        # (the arXiv _compute_chunk_id applies NFC to body before hashing).
        import unicodedata
        nfc = unicodedata.normalize("NFC", "café")  # é as single codepoint
        nfd = unicodedata.normalize("NFD", "café")  # e + combining accent
        assert nfc != nfd  # different byte sequences
        assert _compute_textbook_chunk_id("b", "", nfc) == \
            _compute_textbook_chunk_id("b", "", nfd)


# ---------------------------------------------------------------------------
# Chapter-title collection
# ---------------------------------------------------------------------------


class TestCollectChapterTitles:
    def test_finds_chapter_titles(self) -> None:
        from bs4 import BeautifulSoup
        html = (
            '<section class="ltx_chapter">'
            '<h2 class="ltx_title ltx_title_chapter">Chapter 1. Foo</h2>'
            '</section>'
            '<section class="ltx_chapter">'
            '<h2 class="ltx_title ltx_title_chapter">Chapter 2. Bar</h2>'
            '</section>'
        )
        soup = BeautifulSoup(html, "html.parser")
        titles = _collect_chapter_titles(soup)
        assert titles == {"Chapter 1. Foo", "Chapter 2. Bar"}

    def test_empty_when_no_chapters(self) -> None:
        from bs4 import BeautifulSoup
        html = (
            '<section class="ltx_section">'
            '<h3 class="ltx_title ltx_title_section">1. Only a section</h3>'
            '</section>'
        )
        soup = BeautifulSoup(html, "html.parser")
        assert _collect_chapter_titles(soup) == set()

    def test_chapter_heading_without_ltx_title_does_not_pull_section(
        self,
    ) -> None:
        """m7 F1 regression: a chapter heading lacking the generic
        ``ltx_title`` class must NOT cause the recursive fallback to
        return the nested SECTION title as the chapter title."""
        from bs4 import BeautifulSoup
        html = (
            '<section class="ltx_chapter">'
            # Chapter heading carries ltx_title_chapter but NOT the
            # generic ltx_title — the pre-fix recursive fallback would
            # descend into the nested section.
            '<h2 class="ltx_chapter_heading ltx_title_chapter">Chapter 1. Real Chapter</h2>'
            '<section class="ltx_section">'
            '<h3 class="ltx_title ltx_title_section">1.1 Nested Section</h3>'
            '</section>'
            '</section>'
        )
        soup = BeautifulSoup(html, "html.parser")
        titles = _collect_chapter_titles(soup)
        # The CHAPTER title is captured; the SECTION title is NOT.
        assert "Chapter 1. Real Chapter" in titles
        assert "1.1 Nested Section" not in titles

    def test_identical_chapter_titles_collapse_v0_limitation(self) -> None:
        """m7 F2: two chapters with identical title text collapse to one
        set entry. Pins the documented v0 limitation; flip when m8
        disambiguates by ordinal/id."""
        from bs4 import BeautifulSoup
        html = (
            '<section class="ltx_chapter">'
            '<h2 class="ltx_title ltx_title_chapter">Introduction</h2>'
            '</section>'
            '<section class="ltx_chapter">'
            '<h2 class="ltx_title ltx_title_chapter">Introduction</h2>'
            '</section>'
        )
        soup = BeautifulSoup(html, "html.parser")
        assert _collect_chapter_titles(soup) == {"Introduction"}


# ---------------------------------------------------------------------------
# Golden-fixture end-to-end
# ---------------------------------------------------------------------------


class TestGoldenFixture:
    """Chunk the two-chapter fixture; diff against the committed expected.json.

    See `.claude/docs/textbook-chunker-fixtures.md` for the regeneration
    runbook.
    """

    SLUG = "two-chapter-book"
    PAPER_ID = "textbook:two-chapter-book"

    def _run(self, tmp_path: Path) -> list[dict]:
        base = tmp_path / "notebooks"
        _install_fixture(base, self.SLUG, self.PAPER_ID)
        with patch("ingest.textbook_chunker.NOTEBOOKS_BASE", base):
            records = chunk_textbook(self.SLUG, self.PAPER_ID)
        return [r.to_dict() for r in records]

    def test_matches_golden(self, tmp_path: Path) -> None:
        actual = self._run(tmp_path)
        expected = json.loads(
            (FIXTURE_ROOT / self.SLUG / "expected.json").read_text(
                encoding="utf-8"
            )
        )
        assert actual == expected, (
            "textbook chunker output drifted from the golden fixture. If "
            "the change is intentional, regenerate per "
            ".claude/docs/textbook-chunker-fixtures.md and re-commit "
            "expected.json."
        )

    def test_six_chunks(self, tmp_path: Path) -> None:
        assert len(self._run(tmp_path)) == 6

    def test_chunk_kinds(self, tmp_path: Path) -> None:
        kinds = sorted(d["kind"] for d in self._run(tmp_path))
        # 1 theorem (stmt) + 1 lemma + 2 proof + 2 section.
        assert kinds == ["lemma", "proof", "proof", "section", "section", "stmt"]

    def test_all_chunks_tagged_textbook(self, tmp_path: Path) -> None:
        for d in self._run(tmp_path):
            assert d["source_kind"] == "textbook"
            assert d["textbook_slug"] == self.SLUG
            assert d["parser_used"] == "mineru+latexml"
            assert d["chunker_version"] == TEXTBOOK_CHUNKER_VERSION

    def test_chapter_labels_populated(self, tmp_path: Path) -> None:
        chapters = {d["chapter"] for d in self._run(tmp_path)}
        assert chapters == {
            "Chapter 1. Affine Schemes",
            "Chapter 2. Sheaves of Modules",
        }

    def test_page_columns_null_in_v0(self, tmp_path: Path) -> None:
        for d in self._run(tmp_path):
            assert d["page_start"] is None
            assert d["page_end"] is None

    def test_all_chunk_ids_valid(self, tmp_path: Path) -> None:
        for d in self._run(tmp_path):
            assert is_valid_chunk_id(d["chunk_id"]), d["chunk_id"]

    def test_cross_chapter_pairing_terminates(self, tmp_path: Path) -> None:
        """The Chapter-1 theorem pairs with the Chapter-1 proof, NOT the
        Chapter-2 proof — _is_structural_sibling breaks at the chapter
        boundary (m7 FM-2)."""
        records = self._run(tmp_path)
        stmt = next(d for d in records if d["kind"] == "stmt")
        # The stmt is in Chapter 1; its paired proof must also be Ch1.
        ch1_proofs = [
            d for d in records
            if d["kind"] == "proof"
            and d["chapter"] == "Chapter 1. Affine Schemes"
        ]
        assert stmt["chapter"] == "Chapter 1. Affine Schemes"
        assert len(ch1_proofs) == 1

    def test_output_json_written(self, tmp_path: Path) -> None:
        base = tmp_path / "notebooks"
        _install_fixture(base, self.SLUG, self.PAPER_ID)
        with patch("ingest.textbook_chunker.NOTEBOOKS_BASE", base):
            chunk_textbook(self.SLUG, self.PAPER_ID)
            # _textbook_chunks_dir now takes the resolved notebook dir.
            nb_dir = _resolve_notebook_dir(self.SLUG)
            out_dir = _textbook_chunks_dir(nb_dir, self.PAPER_ID)
        json_files = sorted(out_dir.glob("*.json"))
        # 6 chunk JSONs + 1 manifest.
        assert len(json_files) == 7
        assert (out_dir / "chunk_manifest.json").is_file()


# ---------------------------------------------------------------------------
# No-chapter input (FM-1)
# ---------------------------------------------------------------------------


class TestNoChapterStructure:
    """A flat/article-class textbook (only ltx_section, no ltx_chapter)
    must NOT crash; chapter=None is valid (m7 FM-1)."""

    FLAT_HTML = (
        "<!DOCTYPE html><html><body><article class='ltx_document'>"
        '<section class="ltx_section" id="S1">'
        '<h2 class="ltx_title ltx_title_section">1. Preliminaries</h2>'
        '<div class="ltx_para"><p class="ltx_p">'
        "This monograph is compiled with the article class and has no chapter "
        "structure whatsoever, only sections, which the chunker must handle "
        "gracefully without raising.</p></div>"
        '<div class="ltx_theorem ltx_theorem_theorem" id="S1.Thm1">'
        '<h6 class="ltx_title ltx_runin ltx_title_theorem">Theorem 1.1.</h6>'
        '<div class="ltx_para"><p class="ltx_p">A flat statement.</p></div>'
        "</div></section></article></body></html>"
    )

    def test_no_chapter_chapter_is_none(self, tmp_path: Path) -> None:
        base = tmp_path / "notebooks"
        _write_html(base, "flat-nb", "textbook:flat-nb", self.FLAT_HTML)
        with patch("ingest.textbook_chunker.NOTEBOOKS_BASE", base):
            records = chunk_textbook("flat-nb", "textbook:flat-nb")
        assert records, "chunker should still emit chunks without chapters"
        for r in records:
            assert r.chapter is None
            assert r.source_kind == "textbook"


# ---------------------------------------------------------------------------
# Dedup (FM-4)
# ---------------------------------------------------------------------------


class TestDedup:
    """Two sections with identical body + empty preamble → one chunk on
    disk (m7 FM-4 — without dedup the second JSON overwrites the first)."""

    DUP_HTML = (
        "<!DOCTYPE html><html><body><article class='ltx_document'>"
        '<section class="ltx_section" id="S1">'
        '<h2 class="ltx_title ltx_title_section">1. First</h2>'
        '<p class="ltx_p">Identical prose body that appears twice verbatim in '
        "this document to force a chunk-id collision under the empty-preamble "
        "v0 hashing discipline of the textbook chunker.</p></section>"
        '<section class="ltx_section" id="S2">'
        '<h2 class="ltx_title ltx_title_section">2. Second</h2>'
        '<p class="ltx_p">Identical prose body that appears twice verbatim in '
        "this document to force a chunk-id collision under the empty-preamble "
        "v0 hashing discipline of the textbook chunker.</p></section>"
        "</article></body></html>"
    )

    def test_identical_body_deduped(self, tmp_path: Path) -> None:
        base = tmp_path / "notebooks"
        _write_html(base, "dup-nb", "textbook:dup-nb", self.DUP_HTML)
        with patch("ingest.textbook_chunker.NOTEBOOKS_BASE", base):
            records = chunk_textbook("dup-nb", "textbook:dup-nb")
        # The two identical-body section chunks dedupe to one.
        section_chunks = [r for r in records if r.kind == "section"]
        ids = {r.chunk_id for r in section_chunks}
        assert len(ids) == len(section_chunks), "dup chunk_ids not deduped"


# ---------------------------------------------------------------------------
# Resilience + validation
# ---------------------------------------------------------------------------


class TestResilience:
    def test_missing_html_returns_empty_and_logs(
        self, tmp_path: Path,
    ) -> None:
        base = tmp_path / "notebooks"
        # Create the notebook dir but NOT the parsed HTML.
        (base / "no-html-nb").mkdir(parents=True)
        with patch("ingest.textbook_chunker.NOTEBOOKS_BASE", base):
            records = chunk_textbook("no-html-nb", "textbook:no-html-nb")
            log = base / "no-html-nb" / "ops" / "chunk-failures.log"
        assert records == []
        assert log.is_file()
        assert "fail" in log.read_text(encoding="utf-8")

    def test_invalid_slug_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="invalid notebook slug"):
            chunk_textbook("UPPER", "textbook:upper")

    def test_invalid_paper_id_raises(self, tmp_path: Path) -> None:
        # _validate_paper_id raises InvalidPaperIDError (a ValueError).
        with pytest.raises(ValueError):
            chunk_textbook("good-slug", "not a valid paper id")

    def test_symlink_notebook_dir_refused(self, tmp_path: Path) -> None:
        """m7 F3 regression: if var/arxmcp/notebooks/<slug> is a symlink,
        chunk_textbook refuses (routes through notebook_dir's symlink
        guard) rather than reading/writing through it."""
        base = tmp_path / "notebooks"
        base.mkdir()
        # Point the slug at an out-of-tree real directory via symlink.
        outside = tmp_path / "outside-target"
        outside.mkdir()
        (base / "evil-nb").symlink_to(outside, target_is_directory=True)
        with (
            patch("ingest.textbook_chunker.NOTEBOOKS_BASE", base),
            pytest.raises(ValueError, match="unsafe notebook slug"),
        ):
            chunk_textbook("evil-nb", "textbook:evil-nb")


class TestTheoremLabelAutoId:
    """m7 F5: a textbook theorem with a LaTeXML auto-id yields
    theorem_label=None (the fixture uses explicit Ch-prefixed ids that
    are treated as user labels; this guards the auto-id path)."""

    AUTO_ID_HTML = (
        "<!DOCTYPE html><html><body><article class='ltx_document'>"
        '<section class="ltx_chapter" id="Ch1">'
        '<h2 class="ltx_title ltx_title_chapter">Chapter 1. Foo</h2>'
        '<section class="ltx_section" id="S1">'
        '<h3 class="ltx_title ltx_title_section">1.1 Bar</h3>'
        # LaTeXML auto-id shape (matches _AUTO_ID_RE: S<N>.Thm<word><N>).
        '<div class="ltx_theorem ltx_theorem_theorem" id="S1.Thmtheorem1">'
        '<h6 class="ltx_title ltx_runin ltx_title_theorem">Theorem 1.1.</h6>'
        '<div class="ltx_para"><p class="ltx_p">An auto-id theorem whose '
        "label LaTeXML generated rather than the author.</p></div>"
        "</div></section></section></article></body></html>"
    )

    def test_auto_id_theorem_label_is_none(self, tmp_path: Path) -> None:
        base = tmp_path / "notebooks"
        flat = "textbook_autoid-nb"
        dest = base / "autoid-nb" / "parsed" / flat
        dest.mkdir(parents=True)
        (dest / "index.html").write_text(self.AUTO_ID_HTML, encoding="utf-8")
        with patch("ingest.textbook_chunker.NOTEBOOKS_BASE", base):
            records = chunk_textbook("autoid-nb", "textbook:autoid-nb")
        stmt = next(r for r in records if r.kind == "stmt")
        assert stmt.theorem_label is None, (
            "LaTeXML auto-id theorems must yield theorem_label=None "
            "(the id matched _AUTO_ID_RE, so it is not a user label)"
        )
