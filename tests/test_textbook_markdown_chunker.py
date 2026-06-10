"""Tests for the markdown-native textbook chunker (textbook-markdown-chunker-m1).

Pure-Python: drives ``_chunk_markdown_impl(slug, paper_id, markdown)`` with
fixture strings — no MinerU, no LaTeXML, no file IO.
"""

from __future__ import annotations

from ingest.store import _ALLOWED_PARSER_USED
from ingest.textbook_markdown_chunker import (
    _MAX_TOKENS,
    TEXTBOOK_MD_CHUNKER_VERSION,
    TEXTBOOK_MD_PARSER_USED,
    _chunk_markdown_impl,
    _inline_math_open,
)

SLUG = "bridgeland-stability-pdfs"
PID = "textbook:a-book"


def _chunk(md: str):
    return _chunk_markdown_impl(SLUG, PID, md)


class TestStampingAndIdentity:
    def test_store_allows_mineru_markdown_parser(self) -> None:
        # Without this the LanceDB write raises ValueError on every chunk.
        assert TEXTBOOK_MD_PARSER_USED in _ALLOWED_PARSER_USED
        assert TEXTBOOK_MD_PARSER_USED == "mineru+markdown"

    def test_fields_stamped(self) -> None:
        chunks = _chunk("# Chapter\n\nSome prose about sheaves.")
        assert len(chunks) == 1
        c = chunks[0]
        assert c.source_kind == "textbook"
        assert c.textbook_slug == SLUG
        assert c.parser_used == TEXTBOOK_MD_PARSER_USED
        assert c.chunker_version == TEXTBOOK_MD_CHUNKER_VERSION
        assert c.paper_id == PID
        assert c.page_start is None and c.page_end is None
        assert c.body_tokens is not None and c.body_tokens != ""

    def test_chunk_id_textbook_prefixed_and_stable(self) -> None:
        md = "# H\n\nbody one.\n\nbody two here."
        a = _chunk(md)
        b = _chunk(md)
        assert all(c.chunk_id.startswith(f"textbook:{SLUG}:") for c in a)
        # Deterministic across runs.
        assert [c.chunk_id for c in a] == [c.chunk_id for c in b]

    def test_identical_body_same_section_deduped(self) -> None:
        # Two byte-identical bodies in the SAME section -> second dropped.
        md = (
            "## S\n\nProof. Same text here.\n\n"
            "Lemma 1. A different claim.\n\nProof. Same text here."
        )
        chunks = _chunk(md)
        bodies = [c.body_text for c in chunks]
        assert bodies.count("Proof. Same text here.") == 1

    def test_identical_body_distinct_sections_both_kept(self) -> None:
        # F4: identical bodies in DIFFERENT sections must BOTH survive (section
        # breadcrumb is folded into the chunk_id hash) — no cross-section loss.
        md = "# A\n\nProof. Omitted.\n\n# B\n\nProof. Omitted."
        chunks = _chunk(md)
        bodies = [c.body_text for c in chunks]
        assert bodies.count("Proof. Omitted.") == 2
        # and they carry their correct (distinct) section attribution.
        paths = sorted(c.section_path for c in chunks)
        assert paths == [["A"], ["B"]]


class TestHeadingHierarchy:
    def test_section_path_and_chapter(self) -> None:
        md = (
            "# 1 Triangulated categories\n\nIntro prose.\n\n"
            "## 1.2 Exact functors\n\nSubsection prose about functors.\n\n"
            "### 1.2.1 Detail\n\nDeep prose."
        )
        chunks = _chunk(md)
        by_body = {c.body_text.split(".")[0]: c for c in chunks}
        assert by_body["Intro prose"].section_path == ["1 Triangulated categories"]
        deep = by_body["Deep prose"]
        assert deep.section_path == [
            "1 Triangulated categories", "1.2 Exact functors", "1.2.1 Detail",
        ]
        # chapter = nearest depth<=2 outermost heading.
        assert deep.chapter == "1 Triangulated categories"

    def test_sibling_heading_pops_stack(self) -> None:
        md = "# A\n\na body.\n\n## A.1\n\nsub body.\n\n# B\n\nb body."
        chunks = _chunk(md)
        bbody = next(c for c in chunks if c.body_text.startswith("b body"))
        assert bbody.section_path == ["B"]  # A.1 and A popped

    def test_no_heading_still_chunks(self) -> None:
        # The p101-140 case: content with no leading heading must NOT be lost.
        md = "Just prose with no heading at all.\n\nA second paragraph here."
        chunks = _chunk(md)
        assert len(chunks) >= 1
        assert chunks[0].section_path == []
        assert chunks[0].chapter is None


class TestKindClassification:
    def test_proof_stmt_section(self) -> None:
        # Prose-first: a new stmt/proof lead flushes the prior chunk, so the
        # three units land in distinct chunks. (Trailing prose after a proof
        # intentionally joins the proof chunk to keep multi-paragraph proofs
        # intact — so the section block is placed BEFORE the theorem.)
        md = (
            "# S\n\n"
            "Just some ordinary prose here.\n\n"
            "Theorem 1.1. Every object is nice.\n\n"
            "Proof. It follows immediately. $\\square$"
        )
        chunks = _chunk(md)
        kinds = [c.kind for c in chunks]
        assert "section" in kinds
        assert "stmt" in kinds
        assert "proof" in kinds

    def test_proof_starts_new_chunk(self) -> None:
        # A Proof block must split off from a preceding statement chunk so the
        # embedding-column routing (proof -> embedding_proof) is correct.
        md = "# S\n\nLemma 2. A short claim.\n\nProof. A short proof body."
        chunks = _chunk(md)
        stmt = [c for c in chunks if c.kind == "stmt"]
        proof = [c for c in chunks if c.kind == "proof"]
        assert stmt and proof
        assert "Lemma 2" in stmt[0].body_text
        assert proof[0].body_text.lstrip().startswith("Proof")

    def test_bold_theorem_classified(self) -> None:
        chunks = _chunk("# S\n\n**Theorem 3.** A bold-styled statement.")
        assert chunks[0].kind == "stmt"


class TestMathPreservationAndAtomicity:
    def test_inline_and_display_math_preserved(self) -> None:
        md = "# S\n\nWe have $x_i$ inline and a display:\n\n$$\\sum_{i} a_i x^i$$"
        chunks = _chunk(md)
        joined = "\n".join(c.body_text for c in chunks)
        assert "$x_i$" in joined
        assert "$$\\sum_{i} a_i x^i$$" in joined

    def test_display_math_spanning_blank_lines_atomic(self) -> None:
        # A $$...$$ with a blank line inside must NOT be split across chunks.
        md = "# S\n\n$$\n\n\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}\n\n$$"
        chunks = _chunk(md)
        # The whole display lands in exactly one chunk (balanced $$).
        owners = [c for c in chunks if "$$" in c.body_text]
        assert len(owners) == 1
        assert owners[0].body_text.count("$$") == 2

    def test_inline_math_open_helper(self) -> None:
        assert _inline_math_open("a $x")          # unclosed single $
        assert not _inline_math_open("a $x$ b")   # balanced
        assert _inline_math_open("text $$")        # unclosed display
        assert not _inline_math_open("$$x$$")      # balanced display


class TestTokenBudget:
    def test_long_section_split_into_multiple_chunks(self) -> None:
        # 60 sizeable paragraphs must NOT become one truncated chunk (the m12
        # defect); they split into several chunks, each under the hard max.
        para = "This is a sentence of moderate length about derived functors. " * 8
        md = "# S\n\n" + "\n\n".join(para.strip() for _ in range(60))
        chunks = _chunk(md)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c.body_tokens.split()) <= _MAX_TOKENS

    def test_oversized_single_block_split_not_truncated(self) -> None:
        # One huge block (no blank lines) > max tokens: split at sentences,
        # never truncated -> total text preserved across the pieces. Sentences
        # are VARIED so the content-addressable dedup does not drop any.
        block = " ".join(
            f"Sentence number {i} discusses derived functors and sheaves here."
            for i in range(600)
        )  # ~5400 words, well over the max
        md = "# S\n\n" + block
        chunks = _chunk(md)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c.body_tokens.split()) <= _MAX_TOKENS
            assert not c.truncated
        # No content dropped: concatenated chunk text covers the whole block.
        joined_words = " ".join(c.body_text for c in chunks).split()
        assert len(joined_words) >= len(block.split()) - 5


class TestEmptyInput:
    def test_empty_markdown_yields_no_chunks(self) -> None:
        assert _chunk("") == []
        assert _chunk("# Only a heading\n\n") == []


class TestParityHardening:
    def test_escaped_dollar_not_treated_as_open(self) -> None:
        # F3: a LaTeX-escaped \$ (literal dollar glyph) must not flip parity.
        assert not _inline_math_open(r"the price is \$5 today")
        assert not _inline_math_open(r"$x = \$5$ holds")  # one balanced span

    def test_merge_cap_bounds_blast_radius(self) -> None:
        # F3: one stray unbalanced $ must NOT swallow the whole document — the
        # merge run is capped, so tail blocks survive as separate blocks.
        from ingest.textbook_markdown_chunker import (
            _MAX_MERGE_BLOCKS,
            _paragraph_blocks,
        )
        body = "open $ here\n\n" + "\n\n".join(
            f"plain block number {i}" for i in range(_MAX_MERGE_BLOCKS + 20)
        )
        blocks = _paragraph_blocks(body)
        assert len(blocks) > 1  # not all merged into one


class TestErrorEnvelopeAndRouting:
    def test_missing_markdown_returns_empty_not_raises(
        self, monkeypatch, tmp_path
    ) -> None:
        # F1: a missing MinerU markdown must return [] (logged), NOT raise and
        # abort a batch — matching chunk_textbook's per-paper envelope.
        import ingest.textbook_markdown_chunker as mod

        monkeypatch.setattr(mod, "_resolve_notebook_dir", lambda slug: tmp_path)
        # tmp_path has no parsed/**/auto/*.md -> _markdown_path raises -> caught.
        assert mod.chunk_textbook_markdown(SLUG, "textbook:nope") == []

    def test_non_utf8_markdown_returns_empty_not_raises(
        self, monkeypatch, tmp_path
    ) -> None:
        # F5: non-UTF-8 markdown is a per-paper failure (strict decode), not a
        # silent U+FFFD substitution into math body_text.
        import ingest.textbook_markdown_chunker as mod

        bad = tmp_path / "bad.md"
        bad.write_bytes(b"# H\n\nmath \xa1 and \xca bytes\n")
        monkeypatch.setattr(mod, "_resolve_notebook_dir", lambda slug: tmp_path)
        monkeypatch.setattr(mod, "_markdown_path", lambda nb, pid: bad)
        assert mod.chunk_textbook_markdown(SLUG, PID) == []

    def test_chunker_flag_routes_to_correct_chunker(self, monkeypatch) -> None:
        # F2: the --chunker selection must actually route to the chosen chunker.
        import tools.notebook_textbook_ingest as nti

        called: list[str] = []
        monkeypatch.setattr(
            nti, "chunk_textbook",
            lambda s, p: (called.append("html"), [])[1],
        )
        monkeypatch.setattr(
            nti, "chunk_textbook_markdown",
            lambda s, p: (called.append("markdown"), [])[1],
        )
        nti.ingest_textbook_paper(
            SLUG, "textbook:x", chunker="markdown", dry_run=True
        )
        assert called == ["markdown"]
        called.clear()
        nti.ingest_textbook_paper(SLUG, "textbook:x", dry_run=True)  # default
        assert called == ["html"]
