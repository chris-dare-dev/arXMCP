"""Theorem-aware structural chunker for LaTeXML HTML5 parse trees (E02_S01).

Public API
----------
chunk_paper(paper_id: str) -> list[ChunkRecord]
    Walk ``var/arxmcp/corpus/parsed/<paper_id>/index.html``, extract all
    theorem, proof, definition, section, and similar environments, and return
    a list of :class:`~ingest.chunker_types.ChunkRecord` objects.  Output
    JSON files are written to ``var/arxmcp/corpus/chunks/<paper_id>/``.

Token budgets
-------------
*Statement chunks* (``kind="stmt"``): body_text ≤ 512 BGE-M3 tokens.
Preamble-inclusive verification is end-to-end with E02_S02; this milestone
enforces the body-only cap.

*Proof window chunks* (``kind="proof"``): body_text ≤ 448 BGE-M3 tokens
(512 − 64 header reserve).  When a proof body exceeds this budget it is
split into overlapping windows of 448 tokens with 64-token overlap between
consecutive windows; each window is emitted as a separate chunk.

Tokenization uses ``AutoTokenizer.from_pretrained("BAAI/bge-m3")`` with
``add_special_tokens=False`` to count raw subword tokens without the
CLS/SEP inflation of ``tokenizer(text)["input_ids"]``.

Error handling
--------------
Per-paper exceptions are caught broadly inside ``chunk_paper``.  On failure
the function logs a TSV row to
``var/arxmcp/ops/parser-failures/chunk.log`` and returns ``[]``.  This
mirrors the ``PER_PAPER_FAILURE_EXCEPTIONS`` pattern from
``tools/fetch_seed.py`` (commits c486b26, 01c6579) and ensures a single
corrupt paper does not abort the ingestion loop.

Determinism (BP1)
-----------------
*Output bytes are reproducible.*  Dict keys are sorted before JSON
serialisation (see :class:`~ingest.chunker_types.ChunkRecord.to_dict`).
No timestamps, no random content.  Chunk IDs use the monotonic placeholder
``arxiv:<paper_id>:idx<N>`` until E02_S04 lands the content-addressable
SHA-256 hash.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, Tag

from ingest.chunker_types import ChunkRecord

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PARSED_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"
CHUNKS_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "chunks"
CHUNK_LOG_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "parser-failures" / "chunk.log"

# ---------------------------------------------------------------------------
# Token budget constants
# ---------------------------------------------------------------------------

BGE_M3_MAX_TOKENS = 512
PROOF_HEADER_RESERVE = 64          # tokens reserved for statement header in proof windows
PROOF_MAX_TOKENS = BGE_M3_MAX_TOKENS - PROOF_HEADER_RESERVE  # 448
PROOF_WINDOW_OVERLAP = 64          # tokens of overlap between consecutive proof windows
STMT_MAX_TOKENS = BGE_M3_MAX_TOKENS  # preamble headroom is E02_S02's responsibility

# ---------------------------------------------------------------------------
# LaTeXML CSS class patterns
# ---------------------------------------------------------------------------

# Matches ltx_theorem_<envname> on a div — captures the environment name.
_THEOREM_CLASS_RE = re.compile(r"\bltx_theorem_(\w+)\b")
# Auto-generated LaTeXML id pattern: S<N>.Thm<word><N>
_AUTO_ID_RE = re.compile(r"^S\d+(?:\.SS\d+)*(?:\.SSS\d+)*\.Thm\w+\d+$")
# Parenthetical display name inside theorem heading: Theorem 3.1 (Name)
_PAREN_NAME_RE = re.compile(r"\(([^)]+)\)")

# Section div classes, ordered from outermost to innermost
_SECTION_DIV_CLASSES = [
    "ltx_chapter",
    "ltx_section",
    "ltx_subsection",
    "ltx_subsubsection",
    "ltx_paragraph",
    "ltx_subparagraph",
]

# Section element tag names used by LaTeXML (HTML5 sectioning elements)
_SECTION_TAG_NAMES = {"section", "article", "div"}

# Environments that get specific ``kind`` values matching their LaTeXML subclass
_THEOREM_ENV_KINDS = {
    "theorem": "stmt",
    "thm": "stmt",
    # Lemma-like
    "lemma": "lemma",
    "lem": "lemma",
    # Proposition-like
    "proposition": "proposition",
    "prop": "proposition",
    # Corollary-like
    "corollary": "corollary",
    "cor": "corollary",
    # Others
    "definition": "definition",
    "defn": "definition",
    "def": "definition",
    "remark": "remark",
    "rem": "remark",
    "note": "remark",
    "example": "example",
    "exa": "example",
    "ex": "example",
    "claim": "claim",
    "fact": "fact",
    "conjecture": "conjecture",
    "conj": "conjecture",
    "hypothesis": "hypothesis",
    "observation": "observation",
    "problem": "problem",
    "question": "question",
    "exercise": "exercise",
    "assumption": "assumption",
    "convention": "convention",
    "notation": "notation",
}

# Environments that are treated as "theorem-with-optional-proof" (may get a
# stmt + proof pair if followed by ltx_proof sibling).
_THEOREM_LIKE_ENVNAMES = {
    "theorem", "thm",
    "lemma", "lem",
    "proposition", "prop",
    "corollary", "cor",
    "claim",
    "conjecture", "conj",
    "fact",
    "hypothesis",
    "observation",
}

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tokenizer (loaded lazily)
# ---------------------------------------------------------------------------

_tokenizer = None


def _get_tokenizer():
    """Return the BGE-M3 tokenizer, loading it on first call.

    We intentionally load only the tokenizer (vocab + config), NOT the full
    model weights.  This keeps the import cheap (~5 MB cached download) and
    avoids pulling PyTorch into the ingestion process.
    """
    global _tokenizer
    if _tokenizer is None:
        from transformers import AutoTokenizer  # noqa: PLC0415

        _tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")
    return _tokenizer


def _count_tokens(text: str) -> int:
    """Count BGE-M3 subword tokens without CLS/SEP inflation."""
    tokenizer = _get_tokenizer()
    return len(tokenizer.encode(text, add_special_tokens=False))


def _encode_tokens(text: str) -> list[int]:
    """Encode text to BGE-M3 token IDs without CLS/SEP."""
    tokenizer = _get_tokenizer()
    return tokenizer.encode(text, add_special_tokens=False)


def _decode_tokens(token_ids: list[int]) -> str:
    """Decode a list of token IDs back to a string."""
    tokenizer = _get_tokenizer()
    return tokenizer.decode(token_ids, skip_special_tokens=True)


# ---------------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------------


def _has_class(tag: Tag, cls: str) -> bool:
    """Return True if ``tag`` has ``cls`` among its CSS classes."""
    classes = tag.get("class") or []
    return cls in classes


def _get_classes(tag: Tag) -> list[str]:
    return tag.get("class") or []


def _element_text(tag: Tag) -> str:
    """Extract all text from a BS4 tag, collapsing whitespace."""
    return " ".join(tag.get_text(separator=" ").split())


def _is_structural_sibling(tag: Tag) -> bool:
    """Return True if ``tag`` is a non-whitespace, non-proof sibling that
    would block theorem→proof pairing.

    We allow non-structural siblings (e.g. plain <p> prose) between a theorem
    and its proof — some LaTeXML outputs include a brief remark paragraph
    between the statement and the proof.  We block pairing only when another
    *theorem-like* or *section* div intervenes.
    """
    classes = _get_classes(tag)
    for cls in classes:
        if _THEOREM_CLASS_RE.match(cls):
            return True
    # A nested section element also breaks the pairing
    return tag.name in {"section"}


def _extract_section_path(tag: Tag) -> list[str]:
    """Walk ancestors to build the section breadcrumb for a given element.

    LaTeXML wraps sections in ``<section class="ltx_section">`` etc.  We
    collect the section title from the first child heading of each ancestor
    section, from outermost to innermost.
    """
    path: list[str] = []
    for ancestor in reversed(list(tag.parents)):
        if not isinstance(ancestor, Tag):
            continue
        classes = _get_classes(ancestor)
        is_section_el = ancestor.name == "section" or any(
            c in _SECTION_DIV_CLASSES for c in classes
        )
        if not is_section_el:
            continue
        # Find the title heading of this section
        title_tag = ancestor.find(
            True,
            class_=lambda c: c and "ltx_title" in c.split(),
            recursive=False,
        )
        if title_tag is None:
            # Try one level deeper (some LaTeXML versions nest the heading)
            title_tag = ancestor.find(
                True, class_=lambda c: c and "ltx_title" in c.split()
            )
        if title_tag:
            title_text = " ".join(title_tag.get_text(separator=" ").split())
            if title_text and title_text not in path:
                path.append(title_text)
    return path


def _extract_theorem_label(tag: Tag) -> str | None:
    """Extract a user-supplied ``\\label{}`` key from the LaTeXML ``id``.

    LaTeXML incorporates the user's label key into the element ``id`` when one
    is present, and generates an auto-id of the form ``S<N>.Thm<envname><N>``
    when no ``\\label{}`` is given.  Return ``None`` for auto-generated ids.
    """
    elem_id = tag.get("id")
    if not elem_id:
        return None
    if _AUTO_ID_RE.match(str(elem_id)):
        return None
    return str(elem_id)


def _extract_theorem_name(tag: Tag) -> str | None:
    """Extract a parenthetical display name from the theorem heading.

    Looks for both ``<h6 class="ltx_title">`` and
    ``<span class="ltx_tag ltx_tag_theorem">`` markup (different LaTeXML
    versions use different elements).  Returns the content of the innermost
    parenthetical, e.g. ``"Riemann–Roch"`` from
    ``Theorem 3.1 (Riemann–Roch)``.
    """
    heading_candidates = []

    # Try h1–h6 with ltx_title class
    for heading in tag.find_all(re.compile(r"^h[1-6]$"), class_="ltx_title"):
        heading_candidates.append(heading)

    # Try span with ltx_tag_theorem
    for span in tag.find_all("span", class_="ltx_tag_theorem"):
        heading_candidates.append(span)

    for candidate in heading_candidates:
        text = _element_text(candidate)
        m = _PAREN_NAME_RE.search(text)
        if m:
            name = m.group(1).strip()
            if name:
                return name

    return None


def _env_kind(env_name: str) -> str:
    """Map a LaTeXML environment subclass name to a ``kind`` string."""
    return _THEOREM_ENV_KINDS.get(env_name.lower(), env_name.lower())


def _is_theorem_like(env_name: str) -> bool:
    """Return True if this environment may pair with a following proof."""
    return env_name.lower() in _THEOREM_LIKE_ENVNAMES


# ---------------------------------------------------------------------------
# Proof windowing
# ---------------------------------------------------------------------------


def _window_proof_text(proof_text: str) -> list[str]:
    """Split a long proof body into overlapping token windows.

    Each window contains at most ``PROOF_MAX_TOKENS`` (448) tokens.
    Consecutive windows overlap by ``PROOF_WINDOW_OVERLAP`` (64) tokens.

    Returns a list of decoded window strings.  If the proof fits in a single
    window the list contains exactly one element (the original text, possibly
    slightly altered by encode→decode round-tripping on whitespace).
    """
    token_ids = _encode_tokens(proof_text)
    if len(token_ids) <= PROOF_MAX_TOKENS:
        return [proof_text]

    windows: list[str] = []
    start = 0
    while start < len(token_ids):
        end = min(start + PROOF_MAX_TOKENS, len(token_ids))
        window_ids = token_ids[start:end]
        windows.append(_decode_tokens(window_ids))
        if end >= len(token_ids):
            break
        start = end - PROOF_WINDOW_OVERLAP

    return windows


# ---------------------------------------------------------------------------
# Core extraction: enumerate theorem/proof pairs in one parent container
# ---------------------------------------------------------------------------


def _extract_chunks_from_container(
    container: Tag,
    paper_id: str,
    counter: list[int],  # mutable int-in-list so we can mutate across calls
) -> list[ChunkRecord]:
    """Extract chunks from the direct children of ``container``.

    This is the sibling-pairing logic described in the research synthesis:
    each ``ltx_theorem_*`` div is paired with the next sibling ``ltx_proof``
    div unless a blocking structural sibling intervenes.
    """
    chunks: list[ChunkRecord] = []

    children = [c for c in container.children if isinstance(c, Tag)]

    i = 0
    while i < len(children):
        child = children[i]

        # ----------------------------------------------------------------
        # Detect ltx_proof (orphan — no preceding theorem in this scope)
        # ----------------------------------------------------------------
        if _has_class(child, "ltx_proof"):
            logger.warning(
                "[%s] orphan proof at index %d in <%s>; emitting as kind='proof'",
                paper_id,
                i,
                container.name,
            )
            section_path = _extract_section_path(child)
            proof_text = _element_text(child)
            for window in _window_proof_text(proof_text):
                idx = counter[0]
                counter[0] += 1
                chunks.append(
                    ChunkRecord(
                        chunk_id=f"arxiv:{paper_id}:idx{idx}",
                        paper_id=paper_id,
                        kind="proof",
                        section_path=section_path,
                        theorem_name=None,
                        theorem_label=None,
                        body_text=window,
                    )
                )
            i += 1
            continue

        # ----------------------------------------------------------------
        # Detect ltx_theorem_* divs
        # ----------------------------------------------------------------
        thm_match = None
        for cls in _get_classes(child):
            m = _THEOREM_CLASS_RE.match(cls)
            if m:
                thm_match = m
                break

        if thm_match is None:
            # Recurse into nested sections / containers
            if child.name in {"section", "div", "article"}:
                chunks.extend(_extract_chunks_from_container(child, paper_id, counter))
            elif child.name not in {
                "p", "table", "figure", "ul", "ol", "dl",
                "h1", "h2", "h3", "h4", "h5", "h6",
                "math", "span", "a",
            }:
                # Unknown structural element — recurse defensively
                chunks.extend(_extract_chunks_from_container(child, paper_id, counter))
            i += 1
            continue

        env_name = thm_match.group(1)
        section_path = _extract_section_path(child)
        theorem_label = _extract_theorem_label(child)
        theorem_name = _extract_theorem_name(child)
        stmt_text = _element_text(child)

        # ----------------------------------------------------------------
        # Attempt to pair with the next ltx_proof sibling
        # ----------------------------------------------------------------
        proof_child: Tag | None = None
        if _is_theorem_like(env_name):
            j = i + 1
            while j < len(children):
                sib = children[j]
                if _has_class(sib, "ltx_proof"):
                    proof_child = sib
                    break
                # A pure whitespace text node is not a sibling for this purpose
                # (we already filtered to Tag children above)
                # A blocking structural sibling ends the search
                if _is_structural_sibling(sib):
                    break
                j += 1

        # ----------------------------------------------------------------
        # Emit statement chunk
        # ----------------------------------------------------------------
        kind = _env_kind(env_name)
        # Enforce stmt budget
        stmt_tokens = _count_tokens(stmt_text)
        if stmt_tokens > STMT_MAX_TOKENS:
            logger.warning(
                "[%s] statement chunk exceeds %d tokens (%d); truncating",
                paper_id,
                STMT_MAX_TOKENS,
                stmt_tokens,
            )
            stmt_ids = _encode_tokens(stmt_text)[:STMT_MAX_TOKENS]
            stmt_text = _decode_tokens(stmt_ids)

        stmt_idx = counter[0]
        counter[0] += 1
        chunks.append(
            ChunkRecord(
                chunk_id=f"arxiv:{paper_id}:idx{stmt_idx}",
                paper_id=paper_id,
                kind=kind,
                section_path=section_path,
                theorem_name=theorem_name,
                theorem_label=theorem_label,
                body_text=stmt_text,
            )
        )

        # ----------------------------------------------------------------
        # Emit proof chunk(s) if paired
        # ----------------------------------------------------------------
        if proof_child is not None:
            proof_text = _element_text(proof_child)
            for window in _window_proof_text(proof_text):
                proof_idx = counter[0]
                counter[0] += 1
                chunks.append(
                    ChunkRecord(
                        chunk_id=f"arxiv:{paper_id}:idx{proof_idx}",
                        paper_id=paper_id,
                        kind="proof",
                        section_path=section_path,
                        theorem_name=theorem_name,
                        theorem_label=theorem_label,
                        body_text=window,
                    )
                )
            # Advance past the proof element we consumed
            i = children.index(proof_child) + 1
        else:
            i += 1

    return chunks


# ---------------------------------------------------------------------------
# Section-level prose chunks
# ---------------------------------------------------------------------------


def _extract_section_chunks(
    soup: BeautifulSoup,
    paper_id: str,
    counter: list[int],
) -> list[ChunkRecord]:
    """Emit ``kind="section"`` chunks for top-level section prose.

    Walks each ``<section class="ltx_section">`` (and ltx_subsection etc.),
    extracts the leading prose paragraphs (before any theorem environment)
    and emits them as section chunks when they have substantial content.

    This is intentionally lightweight — the theorem/proof extraction already
    handles the mathematically dense content; this captures narrative prose.
    """
    MIN_SECTION_TEXT_CHARS = 80  # skip trivial section bodies
    chunks: list[ChunkRecord] = []

    all_section_classes = _SECTION_DIV_CLASSES  # already has ltx_ prefix

    for sec_class in all_section_classes:
        for section in soup.find_all(True, class_=sec_class):
            section_path = _extract_section_path(section)

            # Collect prose paragraphs that are NOT inside a theorem/proof env
            para_texts: list[str] = []
            for child in section.children:
                if not isinstance(child, Tag):
                    continue
                child_classes = _get_classes(child)
                # Stop at theorem-like environments — they're handled above
                if any(_THEOREM_CLASS_RE.match(c) for c in child_classes):
                    break
                if _has_class(child, "ltx_proof"):
                    break
                # Collect <p> tags and similar prose containers
                if child.name in {"p", "div"} and not any(
                    c in all_section_classes for c in child_classes
                ):
                    text = _element_text(child)
                    if text:
                        para_texts.append(text)

            prose = " ".join(para_texts).strip()
            if len(prose) < MIN_SECTION_TEXT_CHARS:
                continue

            # Token-cap the section prose
            prose_tokens = _count_tokens(prose)
            if prose_tokens > STMT_MAX_TOKENS:
                ids = _encode_tokens(prose)[:STMT_MAX_TOKENS]
                prose = _decode_tokens(ids)

            idx = counter[0]
            counter[0] += 1
            chunks.append(
                ChunkRecord(
                    chunk_id=f"arxiv:{paper_id}:idx{idx}",
                    paper_id=paper_id,
                    kind="section",
                    section_path=section_path,
                    theorem_name=None,
                    theorem_label=None,
                    body_text=prose,
                )
            )

    return chunks


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def chunk_paper(paper_id: str) -> list[ChunkRecord]:
    """Chunk one paper and write output JSON files.

    Parameters
    ----------
    paper_id:
        Canonical arXiv ID, e.g. ``"2307.01156"``.

    Returns
    -------
    list[ChunkRecord]
        All chunks emitted for the paper.  Returns ``[]`` and logs a failure
        row to ``chunk.log`` if any unrecoverable error occurs.

    Side effects
    ------------
    Writes ``var/arxmcp/corpus/chunks/<paper_id>/<chunk_idx>.json`` for each
    chunk.  Creates the directory if it does not exist.
    """
    start = time.monotonic()
    try:
        return _chunk_paper_impl(paper_id)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - start
        _log_chunk_failure(paper_id, elapsed, str(exc))
        logger.error("[%s] chunk_paper failed: %s", paper_id, exc, exc_info=True)
        return []


def _chunk_paper_impl(paper_id: str) -> list[ChunkRecord]:
    parsed_html = PARSED_DIR / paper_id / "index.html"
    if not parsed_html.exists():
        raise FileNotFoundError(
            f"parsed HTML not found at {parsed_html}; "
            "run tools/fetch_seed.py first"
        )

    html_bytes = parsed_html.read_bytes()
    soup = BeautifulSoup(html_bytes, "html.parser")

    body = soup.find("body")
    root: Tag = body if isinstance(body, Tag) else soup  # type: ignore[assignment]

    counter = [0]

    # Pass 1: theorem/proof pairs and unmatched theorem-like environments
    theorem_chunks = _extract_chunks_from_container(root, paper_id, counter)

    # Pass 2: section-level prose chunks
    section_chunks = _extract_section_chunks(soup, paper_id, counter)

    all_chunks = theorem_chunks + section_chunks

    # Write output JSON
    out_dir = CHUNKS_DIR / paper_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for chunk in all_chunks:
        # Extract the monotonic index from the placeholder chunk_id
        idx_str = chunk.chunk_id.split(":idx")[-1]
        out_path = out_dir / f"{idx_str}.json"
        out_path.write_text(
            json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return all_chunks


# ---------------------------------------------------------------------------
# Failure logging
# ---------------------------------------------------------------------------


def _log_chunk_failure(paper_id: str, elapsed_s: float, message: str) -> None:
    """Append a TSV row to the chunk failure log.

    Format mirrors ``fetch_seed.py``'s ``seed.log``:
    ``<paper_id>\\t<status>\\t<elapsed_s>\\t<message>``
    """
    CHUNK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = f"{paper_id}\tfail\t{elapsed_s:.1f}\t{message}\n"
    try:
        with CHUNK_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(row)
    except OSError:
        # If we can't write the log, we still silently return [] above —
        # don't let a logging failure raise from a catch-all.
        logger.error("could not write to chunk.log: %s", CHUNK_LOG_PATH)
