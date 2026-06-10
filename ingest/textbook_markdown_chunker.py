"""Markdown-native textbook chunker (textbook-markdown-chunker-m1).

Chunks MinerU markdown DIRECTLY into :class:`~ingest.chunker_types.ChunkRecord`
objects, bypassing the ``markdown -> LaTeXML -> HTML -> section-div`` path of
:func:`ingest.textbook_chunker.chunk_textbook`.

Why a second chunker: the HTML path emits one chunk per ``ltx_section`` div, so a
dense textbook (e.g. Huybrechts, *Fourier-Mukai Transforms*) produces very few,
truncated chunks, DROPS prose not wrapped in a section div, and yields ZERO chunks
when math-dense pages overflow LaTeXML's 100-error abort. The MinerU markdown is
clean and complete (ATX ``#``/``##`` headings, paragraph breaks, ``$...$`` /
``$$...$$`` math), so chunking it directly:

- needs no LaTeXML render (nothing to abort),
- captures ALL content (every paragraph),
- preserves math verbatim as LaTeX source in ``body_text``,
- and produces fine, token-bounded chunks instead of one truncated chunk per section.

The chunk identity / store contract is IDENTICAL to the HTML path: ``chunk_id`` via
:func:`ingest.textbook_chunker._compute_textbook_chunk_id` (so the m9 ``textbook:``
prefix <-> ``source_kind`` invariant + dedup hold), ``source_kind="textbook"``,
``preamble_text=""`` (m8 OQ-1: PDF textbooks have no author macros). Only the
``chunker_version`` (``tmd0.1``) and ``parser_used`` (``mineru+markdown``) differ, so
this is a separate lineage that never forces arXiv or HTML-textbook re-embedding.

**Per-segment breadcrumb note:** a MinerU markdown that begins mid-chapter (e.g. a
page-range segment of a large book) has no leading ``#`` heading, so its first chunks
carry ``section_path=[]`` / ``chapter=None`` until the first heading appears. This
mirrors the HTML chunker's flat/article-class behavior and is accepted.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ingest.chunker import _validate_paper_id
from ingest.chunker_types import ChunkRecord
from ingest.textbook_chunker import (
    _compute_textbook_chunk_id,
    _flat_paper_id,
    _resolve_notebook_dir,
)
from ingest.textbook_renderer import _ATX_HEADING_RE
from ingest.tokenizer import tokenize_body
from tools._notebook_common import NotebookError

logger = logging.getLogger(__name__)

#: Separate lineage from the HTML chunker ("tv0.1" / "mineru+latexml") so a
#: markdown-chunker change never invalidates arXiv or HTML-textbook chunks.
TEXTBOOK_MD_CHUNKER_VERSION = "tmd0.1"
#: MUST be present in ``ingest.store._ALLOWED_PARSER_USED`` or write_chunks raises.
TEXTBOOK_MD_PARSER_USED = "mineru+markdown"

#: Soft target / hard ceiling (in whitespace tokens) for a chunk. The target is
#: where we flush a healthy chunk; the max is where we refuse to grow further.
#: Neither truncates — an oversized atom is split (never cut), and a single
#: unsplittable atom is emitted whole (BGE-M3 truncates the EMBEDDING input at
#: 2048 tokens, but the stored body_text stays complete).
_TARGET_TOKENS = 600
_MAX_TOKENS = 1500

_STMT_RE = re.compile(
    r"^(?:\*\*\s*)?(Theorem|Lemma|Proposition|Corollary|Definition|Remark|Example)\b",
    re.IGNORECASE,
)
_PROOF_RE = re.compile(r"^(?:\*\*\s*)?Proof\b", re.IGNORECASE)
#: Sentence boundary: end punctuation followed by whitespace. Used only as an
#: oversized-block splitter, with a math-parity guard so it never cuts inside math.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_BLANKLINE_RE = re.compile(r"\n[ \t]*\n")


def _markdown_path(nb_dir: Path, paper_id: str) -> Path:
    """Locate the cached MinerU markdown under a resolved notebook dir."""
    flat = _flat_paper_id(paper_id)
    base = nb_dir / "parsed" / flat
    mds = sorted(base.glob("**/auto/*.md"))
    if not mds:
        raise FileNotFoundError(
            f"no MinerU markdown under {base}/**/auto/*.md; run the PDF "
            f"parse (MinerU) for {paper_id!r} first."
        )
    return mds[0]


def _token_count(text: str) -> int:
    """Whitespace-token count via the shared tokenizer (handles ``$`` math)."""
    return len(tokenize_body(text).split())


def _inline_math_open(text: str) -> bool:
    """True if ``text`` has an unclosed ``$``/``$$`` (so the next block belongs
    to the same math span and must not be split off)."""
    dollar_pairs = text.count("$$")
    if dollar_pairs % 2 == 1:
        return True
    single = text.count("$") - 2 * dollar_pairs
    return single % 2 == 1


def _chapter_from_stack(stack: list[tuple[int, str]]) -> str | None:
    """The nearest chapter-grain title: the outermost depth<=2 heading."""
    for depth, title in stack:
        if depth <= 2:
            return title
    return stack[0][1] if stack else None


def _parse_sections(markdown: str) -> list[tuple[list[str], str | None, str]]:
    """Split markdown into ``(section_path, chapter, body_text)`` regions, one
    per heading-delimited block. Body before the first heading -> ``([], None)``.
    Heading title lines are NOT included in body (the breadcrumb carries them)."""
    stack: list[tuple[int, str]] = []
    body_lines: list[str] = []
    out: list[tuple[list[str], str | None, str]] = []

    def flush() -> None:
        body = "\n".join(body_lines).strip()
        body_lines.clear()
        if body:
            out.append(
                ([t for (_, t) in stack], _chapter_from_stack(stack), body)
            )

    for line in markdown.split("\n"):
        match = _ATX_HEADING_RE.match(line)
        if match is None:
            body_lines.append(line)
            continue
        flush()  # body so far belongs to the PREVIOUS heading context
        depth = len(match.group(1))
        title = match.group(2).strip()
        while stack and stack[-1][0] >= depth:
            stack.pop()
        stack.append((depth, title))
    flush()
    return out


def _paragraph_blocks(body: str) -> list[str]:
    """Blank-line-separated blocks, with ``$$...$$`` spans kept ATOMIC: a block
    with an unclosed ``$$``/``$`` is merged with following blocks until the math
    closes (FM-1: a display block spanning a blank line must not be split)."""
    raw = [b.strip() for b in _BLANKLINE_RE.split(body) if b.strip()]
    blocks: list[str] = []
    i = 0
    while i < len(raw):
        block = raw[i]
        while _inline_math_open(block) and i + 1 < len(raw):
            i += 1
            block = block + "\n\n" + raw[i]
        blocks.append(block)
        i += 1
    return blocks


def _split_oversized(block: str) -> list[str]:
    """Split a single >max-token block at sentence boundaries, keeping math
    spans intact (parity-merge). Never truncates; if nothing splits, returns the
    block whole."""
    sentences = _SENTENCE_SPLIT_RE.split(block)
    # Re-merge sentence fragments that broke an open math span.
    merged: list[str] = []
    i = 0
    while i < len(sentences):
        piece = sentences[i]
        while _inline_math_open(piece) and i + 1 < len(sentences):
            i += 1
            piece = piece + " " + sentences[i]
        merged.append(piece)
        i += 1
    pieces: list[str] = []
    buf: list[str] = []
    for sent in merged:
        # Check BEFORE adding so a finished piece never exceeds the max (a lone
        # sentence longer than the max is the only case that can, and it is
        # emitted whole rather than truncated).
        if buf and _token_count(" ".join([*buf, sent])) > _MAX_TOKENS:
            pieces.append(" ".join(buf))
            buf = []
        buf.append(sent)
    if buf:
        pieces.append(" ".join(buf))
    return pieces or [block]


def _group_blocks(blocks: list[str]) -> list[str]:
    """Group paragraph blocks into chunk bodies under the token budget, with a
    secondary split at ``Proof`` boundaries and an oversized-block fallback."""
    chunks: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            chunks.append("\n\n".join(buf))
            buf.clear()

    for block in blocks:
        # A new statement/proof unit starts a fresh chunk so stmt and proof
        # land in DISTINCT chunks (the kind split routes embedding_proof vs
        # embedding_stmt). Continuation paragraphs (classified "section") join
        # the current chunk, so a multi-paragraph proof stays intact.
        if buf and _classify_kind(block) in ("stmt", "proof"):
            flush()
        # An oversized standalone block is split (never truncated).
        if _token_count(block) > _MAX_TOKENS:
            flush()
            chunks.extend(_split_oversized(block))
            continue
        # Adding this block would breach the hard max: flush the buffer first.
        if buf and _token_count("\n\n".join([*buf, block])) > _MAX_TOKENS:
            flush()
        buf.append(block)
        if _token_count("\n\n".join(buf)) >= _TARGET_TOKENS:
            flush()
    flush()
    return chunks


def _classify_kind(body: str) -> str:
    """``stmt`` / ``proof`` / ``section`` from the first non-empty line."""
    first = next((ln for ln in body.split("\n") if ln.strip()), "").lstrip()
    if _PROOF_RE.match(first):
        return "proof"
    if _STMT_RE.match(first):
        return "stmt"
    return "section"


def _chunk_markdown_impl(
    slug: str, paper_id: str, markdown: str
) -> list[ChunkRecord]:
    """Pure core: markdown text -> deduped ChunkRecords (no file IO)."""
    raw: list[tuple[list[str], str | None, str]] = []
    for section_path, chapter, body in _parse_sections(markdown):
        for chunk_body in _group_blocks(_paragraph_blocks(body)):
            raw.append((section_path, chapter, chunk_body))

    seen: dict[str, str] = {}
    out: list[ChunkRecord] = []
    for section_path, chapter, body in raw:
        chunk_id = _compute_textbook_chunk_id(slug, "", body)
        if chunk_id in seen:
            if seen[chunk_id] == body:
                logger.debug(
                    "[%s/%s] dropping duplicate chunk_id %s (identical body)",
                    slug, paper_id, chunk_id,
                )
                continue
            raise ValueError(
                f"SHA-256 prefix collision: chunk_id {chunk_id} for textbook "
                f"{paper_id} maps to two distinct body_text values."
            )
        seen[chunk_id] = body
        out.append(
            ChunkRecord(
                chunk_id=chunk_id,
                paper_id=paper_id,
                kind=_classify_kind(body),
                section_path=section_path,
                theorem_name=None,
                theorem_label=None,
                body_text=body,
                body_tokens=tokenize_body(body),
                chunker_version=TEXTBOOK_MD_CHUNKER_VERSION,
                source_kind="textbook",
                chapter=chapter,
                textbook_slug=slug,
                parser_used=TEXTBOOK_MD_PARSER_USED,
            )
        )
    return out


def chunk_textbook_markdown(slug: str, paper_id: str) -> list[ChunkRecord]:
    """Chunk a textbook's cached MinerU markdown into ChunkRecords.

    Reads ``notebooks/<slug>/parsed/<flat_paper_id>/**/auto/<stem>.md`` (the
    MinerU output the renderer also consumes) and chunks it directly — no
    LaTeXML render. Returns ``[]`` only when the markdown has no body content;
    a bad/unsafe slug or paper_id raises (mirrors :func:`chunk_textbook`).
    """
    try:
        nb_dir = _resolve_notebook_dir(slug)
    except NotebookError as exc:
        raise ValueError(
            f"invalid or unsafe notebook slug {slug!r}: {exc}"
        ) from exc
    _validate_paper_id(paper_id)
    markdown = _markdown_path(nb_dir, paper_id).read_text(
        encoding="utf-8", errors="replace"
    )
    return _chunk_markdown_impl(slug, paper_id, markdown)
