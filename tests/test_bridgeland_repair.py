"""Source coverage and embedding-budget gates for the corpus repair."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from arxmcp.ingest import chunker, embedder, tex_formal_chunker, textbook_pdf_chunker
from arxmcp.ingest.chunk import embedding_input


def test_windows_cover_exact_source_characters(monkeypatch):
    class WordTokenizer:
        def __call__(self, text, **kwargs):
            matches = list(re.finditer(r"\S+", text))
            return {
                "input_ids": list(range(len(matches))),
                "offset_mapping": [(m.start(), m.end()) for m in matches],
            }

    monkeypatch.setattr(chunker, "_get_tokenizer", lambda: WordTokenizer())
    source = "  alpha  beta\n\ngamma delta   epsilon zeta  "
    windows = chunker._window_text_spans(source, 3, 1)
    assert all(text == source[start:end] for text, start, end in windows)
    assert windows[0][1] == 0 and windows[-1][2] == len(source)
    assert all(windows[i][2] >= windows[i + 1][1] for i in range(len(windows) - 1))
    assert all(len(re.findall(r"\S+", text)) <= 3 for text, _, _ in windows)


def test_body_policy_and_special_token_budget(monkeypatch):
    # body-first-v1: the embedding input is the NFC body; no preamble reaches it.
    assert embedding_input("body") == "body"

    class Tokenizer:
        def __call__(self, texts, **kwargs):
            if kwargs.get("return_length"):
                return {"length": [embedder.MAX_TOKENS + 1]}
            raise AssertionError("overflow must fail before model encoding")

    monkeypatch.setattr(embedder, "_get_tokenizer", lambda: Tokenizer())
    monkeypatch.setattr(embedder, "_get_model", lambda: pytest.fail("model loaded"))
    with pytest.raises(ValueError, match="including special tokens"):
        embedder._encode_batch(["too long"], ["arxiv:test:chunk"])


def test_authentic_tex_environment_proof_linkage(tmp_path, monkeypatch):
    tex = tmp_path / "main.tex"
    tex.write_text(
        r"\newtheorem{prop}{Proposition}\begin{document}"
        r"\section{Results}Background text."
        r"\begin{prop}\label{p:one}Statement $x=1$.\end{prop}"
        r"\begin{proof}Because $x=1$.\end{proof}"
        r"\end{document}", encoding="utf-8",
    )
    monkeypatch.setattr(
        tex_formal_chunker.ApplicationPaths, "resolve",
        lambda: SimpleNamespace(corpus=tmp_path),
    )
    monkeypatch.setattr(tex_formal_chunker, "find_main_tex", lambda *_: tex)
    chunks = tex_formal_chunker.chunk_tex_formals("1309.5035")
    formal = [chunk for chunk in chunks if chunk.kind != "section"]
    assert [chunk.kind for chunk in formal] == ["proposition", "proof"]
    assert {chunk.theorem_label for chunk in formal} == {"p:one"}
    assert {chunk.printed_number for chunk in formal} == {"1"}
    assert any(chunk.kind == "section" and "Background text" in chunk.body_text for chunk in chunks)
    assert all(tex.read_text()[c.source_start:c.source_end] == c.body_text for c in chunks)


def test_pdf_number_first_labels_keep_page_spans(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "textbook_ko95.pdf").write_bytes(b"fixture")
    monkeypatch.setattr(textbook_pdf_chunker, "_resolve_notebook_dir", lambda _: tmp_path)
    monkeypatch.setattr(
        textbook_pdf_chunker.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="Intro text.\f2.2. Lemma. Let X exist.\nProof. Clear.\f"
        ),
    )
    chunks = textbook_pdf_chunker.chunk_textbook_pdf("bridgeland-stability", "textbook:ko95")
    lemma = next(c for c in chunks if c.kind == "lemma")
    proof = next(c for c in chunks if c.kind == "proof")
    assert lemma.printed_number == "2.2"
    assert lemma.page_start == lemma.page_end == 2
    assert proof.theorem_label == lemma.theorem_label


def test_heading_result_and_proof_share_source_label():
    soup = BeautifulSoup(
        '<section id="S1"><h2>1.4. Proposition</h2><div>Let X be smooth.</div></section>'
        '<section id="S2"><h2>2. Proof of Proposition 1.4</h2>'
        '<div>We prove the assertion.</div></section>',
        "html.parser",
    )
    chunks = chunker._extract_labeled_result_chunks(soup, "math/0210114", [0])
    statement = next(c for c in chunks if c.kind == "proposition")
    proof = next(c for c in chunks if c.kind == "proof")
    assert statement.theorem_label == proof.theorem_label == "S1"
    assert statement.printed_number == proof.printed_number == "1.4"
