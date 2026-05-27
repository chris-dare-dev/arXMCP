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
No timestamps, no random content. Chunk IDs are content-addressable
``arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>``
(landed in E02_S04). The hash input uses the NFC-normalised
``body_text`` so the chunk_id is stable across hosts even when the
HTML parser emits NFD bytes; the stored ``chunk.body_text`` is left
unchanged. Any future consumer that recomputes a hash over
``chunk.body_text`` for its own cache key MUST apply the same
``unicodedata.normalize("NFC", ...)`` step or risk cache divergence
across hosts (F3 closure documents this asymmetry).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, NavigableString, Tag

# CHUNKER_VERSION lives in chunker_types to avoid a circular import — the
# dataclass default in ChunkRecord references it directly.
from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.tokenizer import tokenize_body

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

BGE_M3_MAX_TOKENS = 2048
PROOF_HEADER_RESERVE = 64          # tokens reserved for statement header in proof windows
# 2048 - 192 headroom (proof windows re-embed inline stmt + preamble overhead)
PROOF_MAX_TOKENS = 1856
PROOF_WINDOW_OVERLAP = 64          # tokens of overlap between consecutive proof windows
# 2048 - 128 preamble headroom (embedder concatenates preamble + body at encode time)
STMT_MAX_TOKENS = 1920

# ---------------------------------------------------------------------------
# LaTeXML CSS class patterns
# ---------------------------------------------------------------------------

# Matches ltx_theorem_<envname> on a div — captures the environment name.
_THEOREM_CLASS_RE = re.compile(r"\bltx_theorem_(\w+)\b")
# Auto-generated LaTeXML id pattern: S<N>.Thm<word><N>
_AUTO_ID_RE = re.compile(r"^S\d+(?:\.SS\d+)*(?:\.SSS\d+)*\.Thm\w+\d+$")
# Parenthetical display name inside theorem heading: Theorem 3.1 (Name)
_PAREN_NAME_RE = re.compile(r"\(([^)]+)\)")

# Closes F2: paper_id must match new-style YYMM.NNNNN[N][vN] or old-style
# subject/NNNNNNN[vN] or textbook:<slug> (textbook-ingest-m1); everything
# else is rejected before any path concat. Threat 1 in
# 08-security-observability-ops.md. Byte-equality with
# ingest/identifiers.py::_PAPER_ID_FULL_PATTERN is enforced by
# tests/test_identifiers.py::test_chunker_pattern_equals_canonical.
_PAPER_ID_RE = re.compile(
    # F3 closure from m1 critique: ``\Z`` not ``$`` — see
    # ingest/identifiers.py for the canonical pattern definition + rationale.
    # textbook-ingest-m1: third alternative ``textbook:<slug>`` added in
    # lockstep with the canonical pattern. The chunker never PRODUCES
    # textbook paper_ids in m1 (no schema for textbook chunks yet), but
    # the lockstep is required by the byte-equality test.
    r"^\d{4}\.\d{4,5}(v\d+)?\Z"
    r"|^[a-z][a-z\-]*/\d{7}(v\d+)?\Z"
    r"|^textbook:[a-z][a-z0-9-]{2,30}\Z"
)


class InvalidPaperIDError(ValueError):
    """Raised when a paper_id fails the validation regex."""


def _validate_paper_id(paper_id: str) -> None:
    """Reject paper_ids that could enable path traversal or log injection."""
    if not isinstance(paper_id, str) or not _PAPER_ID_RE.match(paper_id):
        raise InvalidPaperIDError(
            f"paper_id {paper_id!r} does not match new-style YYMM.NNNNN[vN] "
            "or old-style subject/NNNNNNN[vN]"
        )


def _sanitize_log_field(s: str) -> str:
    """Strip TSV-breaking characters (tab, newline, carriage return)."""
    return s.replace("\t", " ").replace("\n", " ").replace("\r", " ")


# Closes F8: targeted exception envelope for per-paper failures, mirroring
# tools/arxiv_fetch.py's PER_PAPER_FAILURE_EXCEPTIONS pattern (commits
# c486b26, 01c6579). Programmer bugs (AttributeError, KeyError, TypeError,
# RecursionError) propagate so dev-time regressions surface.
PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)


# Closes F13: recursion depth bound so adversarial nested HTML cannot trip
# the Python recursion limit and silently drop the paper.
_MAX_CONTAINER_DEPTH = 50

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
    # Short-form aliases observed in real arXiv papers (math.AG corpus
    # April 2026 — IntroThm/IntroCor/Df/Lm/Rmk style class names from
    # LaTeXML). Without these the fallback would emit raw env_name
    # which the schema's _ALLOWED_KINDS rejects.
    "lm": "lemma",
    "df": "definition",
    "rmk": "remark",
    "introthm": "stmt",
    "introcor": "corollary",
    "introprop": "proposition",
    "introlem": "lemma",
    "maintheorem": "stmt",
    "mainthm": "stmt",
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
    model weights, in this module — keeping the chunker import cheap (~5 MB
    cached download) and confining the heavyweight ``torch`` + safetensors
    weight load to ``ingest.embedder`` (E03_S01). The chunker itself does
    not import ``torch``.

    Closes F7 from the E03_S01 adversary critique: the tokenizer is
    pinned to :data:`ingest.embedder.BGE_M3_COMMIT_SHA` to satisfy
    Threat 6 (08-security-observability-ops.md). Without ``revision=...``
    the tokenizer would float on whatever HuggingFace serves for the
    ``main`` tag — silent rotation of the tokenizer-only files (with
    model weights unchanged) would drift ``body_tokens`` across runs
    while ``chunker_version`` stays the same, which is a dormant
    cache-poisoning bomb for BP1 byte-stability.
    """
    global _tokenizer
    if _tokenizer is None:
        # Lazy import inside the function body, mirroring the embedder's
        # pattern. This also avoids a top-of-file circular import:
        # ingest.embedder imports from ingest.chunker (paper_id
        # validators), so a top-level import the other way would close
        # the cycle.
        from transformers import AutoTokenizer  # noqa: PLC0415

        from ingest.embedder import BGE_M3_COMMIT_SHA  # noqa: PLC0415
        from server.model_loader import (  # noqa: PLC0415
            resolve_trust_remote_code,
            validate_model_revision,
        )

        # E13_S06 Threat 6: re-validate at every load so a runtime
        # monkeypatch of BGE_M3_COMMIT_SHA cannot bypass the guard.
        validate_model_revision(BGE_M3_COMMIT_SHA, model_name="BAAI/bge-m3")
        _tokenizer = AutoTokenizer.from_pretrained(
            "BAAI/bge-m3",
            revision=BGE_M3_COMMIT_SHA,
            trust_remote_code=resolve_trust_remote_code(),
        )
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
    """Extract all text from a BS4 tag, preserving math content.

    Closes F1 (CRITICAL math fidelity violation): a naive ``get_text()`` call
    discards LaTeXML's ``<math alttext="...">`` payload and keeps only the
    rendered Unicode glyphs from ``<mi>`` etc., destroying the very content
    the project exists to preserve. We walk the subtree, replace each
    ``<math>`` element with the verbatim ``alttext`` LaTeX wrapped in
    ``$...$`` delimiters, and only fall back to inner-text when ``alttext``
    is absent.

    Cite: 01-mission-and-context.md § "Why current arXiv-context tools fail
    for research math" (mission DP1: math fidelity over coverage).
    """
    parts: list[str] = []

    def _walk(node):
        if isinstance(node, Tag):
            if node.name == "math":
                alttext = node.get("alttext")
                if alttext:
                    parts.append(f"${alttext}$")
                    return
                # Fallback: inner text without recursing again
                fallback = node.get_text(separator=" ")
                if fallback.strip():
                    parts.append(f"${fallback.strip()}$")
                return
            for child in node.children:
                _walk(child)
        elif isinstance(node, NavigableString):
            parts.append(str(node))

    _walk(tag)
    return " ".join("".join(parts).split())


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
        # Find the title heading of this section. Closes F10: explicit
        # ``isinstance(c, str)`` guard — bs4's class predicate is invoked
        # with ``c`` as a single class string in current versions, but the
        # documented behavior allows ``c`` to be the full list. The string
        # guard is safe across both calling conventions.
        def _has_ltx_title(c) -> bool:
            return isinstance(c, str) and "ltx_title" in c.split()

        title_tag = ancestor.find(True, class_=_has_ltx_title, recursive=False)
        if title_tag is None:
            # Try one level deeper (some LaTeXML versions nest the heading)
            title_tag = ancestor.find(True, class_=_has_ltx_title)
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

    # Try h1–h6 with ltx_title class. Closes F9: only direct children of
    # the theorem div, not nested theorems' headings. recursive=False on
    # the immediate scan; bs4 doesn't accept recursive on a regex tag, so
    # we filter the children manually.
    for child in tag.children:
        if not isinstance(child, Tag):
            continue
        if child.name and re.match(r"^h[1-6]$", child.name):
            classes = _get_classes(child)
            if any(isinstance(c, str) and "ltx_title" in c.split() for c in classes):
                heading_candidates.append(child)

    # Try span with ltx_tag_theorem (also direct children only)
    for child in tag.children:
        if not isinstance(child, Tag):
            continue
        if child.name == "span" and _has_class(child, "ltx_tag_theorem"):
            heading_candidates.append(child)

    for candidate in heading_candidates:
        text = _element_text(candidate)
        m = _PAREN_NAME_RE.search(text)
        if m:
            name = m.group(1).strip()
            if name:
                return name

    return None


def _env_kind(env_name: str) -> str:
    """Map a LaTeXML environment subclass name to a ``kind`` string.

    Unknown environment names default to ``"stmt"`` — the same kind
    plain ``theorem`` maps to. Returning the raw env_name produced a
    bulk-ingest crash when papers used custom theorem environments
    not in ``_THEOREM_ENV_KINDS`` (e.g. an author's ``\\newtheorem
    {weirdthm}``) because the resulting chunk's ``kind`` is rejected
    by ``ingest.store._ALLOWED_KINDS``.
    """
    return _THEOREM_ENV_KINDS.get(env_name.lower(), "stmt")


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

    Closes F6: windows are character-substring slices of ``proof_text``,
    NOT encode/decode round-trips. Decoding WordPiece subwords mutates
    whitespace and breaks the determinism contract that E02_S04's
    content-addressable hashes depend on. We get token-indexed character
    offsets via the BGE-M3 fast tokenizer's ``return_offsets_mapping=True``
    and slice the original string by those offsets.

    Returns a list of substring windows. If the proof fits in a single
    window, returns ``[proof_text]`` unchanged.
    """
    tokenizer = _get_tokenizer()
    enc = tokenizer(
        proof_text,
        add_special_tokens=False,
        return_offsets_mapping=True,
    )
    token_ids = enc["input_ids"]
    offsets = enc["offset_mapping"]
    if len(token_ids) <= PROOF_MAX_TOKENS:
        return [proof_text]

    windows: list[str] = []
    start = 0
    while start < len(token_ids):
        end = min(start + PROOF_MAX_TOKENS, len(token_ids))
        # Substring from the first token's start to the last token's end.
        char_start = offsets[start][0]
        char_end = offsets[end - 1][1]
        windows.append(proof_text[char_start:char_end])
        if end >= len(token_ids):
            break
        start = end - PROOF_WINDOW_OVERLAP

    return windows


def _truncate_to_token_budget(text: str, max_tokens: int) -> tuple[str, bool]:
    """Truncate ``text`` to at most ``max_tokens`` BGE-M3 tokens.

    Closes F5/F6: returns a substring slice (not an encode/decode round-trip)
    plus a ``truncated`` flag so the chunk record can surface the loss to
    downstream consumers. ``truncated=False`` means the text was already
    within budget.
    """
    tokenizer = _get_tokenizer()
    enc = tokenizer(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
    )
    token_ids = enc["input_ids"]
    offsets = enc["offset_mapping"]
    if len(token_ids) <= max_tokens:
        return text, False
    char_end = offsets[max_tokens - 1][1]
    return text[:char_end], True


# ---------------------------------------------------------------------------
# Core extraction: enumerate theorem/proof pairs in one parent container
# ---------------------------------------------------------------------------


def _extract_chunks_from_container(
    container: Tag,
    paper_id: str,
    counter: list[int],  # mutable int-in-list so we can mutate across calls
    depth: int = 0,
) -> list[ChunkRecord]:
    """Extract chunks from the direct children of ``container``.

    This is the sibling-pairing logic described in the research synthesis:
    each ``ltx_theorem_*`` div is paired with the next sibling ``ltx_proof``
    div unless a blocking structural sibling intervenes.

    Closes F13: ``depth`` is bounded by ``_MAX_CONTAINER_DEPTH`` so that
    adversarial nested HTML (e.g. an arxiv submission with thousands of
    nested ``<div>``s) cannot trip Python's recursion limit and silently
    drop the paper via the per-paper exception envelope.
    """
    if depth > _MAX_CONTAINER_DEPTH:
        logger.warning(
            "[%s] container nesting exceeded %d levels; truncating descent",
            paper_id,
            _MAX_CONTAINER_DEPTH,
        )
        return []
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
                chunks.extend(
                    _extract_chunks_from_container(child, paper_id, counter, depth + 1)
                )
            elif child.name not in {
                "p", "table", "figure", "ul", "ol", "dl",
                "h1", "h2", "h3", "h4", "h5", "h6",
                "math", "span", "a",
            }:
                # Unknown structural element — recurse defensively
                chunks.extend(
                    _extract_chunks_from_container(child, paper_id, counter, depth + 1)
                )
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
        # Enforce stmt budget. Closes F5: surface truncation via the
        # ``truncated`` flag on the chunk record so downstream consumers can
        # distinguish a complete statement from a truncated one. Closes F6:
        # use character-offset slicing, not encode/decode round-trip.
        stmt_text, stmt_truncated = _truncate_to_token_budget(
            stmt_text, STMT_MAX_TOKENS
        )
        if stmt_truncated:
            logger.warning(
                "[%s] statement chunk exceeded %d tokens; truncated",
                paper_id,
                STMT_MAX_TOKENS,
            )

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
                truncated=stmt_truncated,
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

    # Closes F4: a single document-order traversal collects every section
    # element. Iterating per-class would emit all ltx_section chunks before
    # any ltx_subsection chunk, scrambling document order and breaking the
    # determinism contract that E02_S04's chunk_id hashing depends on.
    def _is_section_class(c) -> bool:
        if isinstance(c, str):
            return c in all_section_classes
        return False

    for section in soup.find_all(True, class_=_is_section_class):
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

        # Token-cap the section prose. Closes F5/F6: substring slicing via
        # offset-mapping, with a ``truncated`` flag surfaced on the chunk.
        prose, prose_truncated = _truncate_to_token_budget(prose, STMT_MAX_TOKENS)
        if prose_truncated:
            logger.warning(
                "[%s] section prose chunk exceeded %d tokens; truncated",
                paper_id,
                STMT_MAX_TOKENS,
            )

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
                truncated=prose_truncated,
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
    # Closes F2: validate paper_id before any path concat or logging.
    # Validation runs OUTSIDE the per-paper exception envelope so an invalid
    # paper_id surfaces to the caller rather than being silently logged with
    # itself as the offending field.
    _validate_paper_id(paper_id)

    start = time.monotonic()
    try:
        return _chunk_paper_impl(paper_id)
    except PER_PAPER_FAILURE_EXCEPTIONS as exc:
        # Closes F8: catch only the resilience-pattern exception set, NOT a
        # bare `except Exception`. Programmer bugs (AttributeError, KeyError,
        # TypeError) propagate to surface during dev.
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

    # Closes F1 (HIGH): cleanup MUST happen before any chunk assembly
    # so a downstream failure (e.g. duplicate-chunk_id raise) leaves the
    # directory empty rather than retaining stale per-chunk JSONs and a
    # stale chunk_manifest.json from a previous run. The previous
    # arrangement performed cleanup just before the JSON write loop, so
    # an early-exit path silently preserved the prior corpus state.
    # Also extends the *.json sweep to *.tmp (closes F6).
    out_dir = CHUNKS_DIR / paper_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.json"):
        stale.unlink()
    for stale in out_dir.glob("*.tmp"):
        stale.unlink()

    counter = [0]

    # Pass 1: theorem/proof pairs and unmatched theorem-like environments
    theorem_chunks = _extract_chunks_from_container(root, paper_id, counter)

    # Pass 2: section-level prose chunks
    section_chunks = _extract_section_chunks(soup, paper_id, counter)

    all_chunks = theorem_chunks + section_chunks

    # E02_S02 wire-in: resolve the per-paper preamble (full PreambleDoc, not
    # just the hash) so we can both stamp ``preamble_ref`` (the hash) and
    # feed ``preamble_text`` into the E02_S04 content-addressable
    # ``chunk_id``. When extraction fails, ``preamble_doc`` is None, the
    # chunker remains functional, and the chunk_id hash falls back to an
    # empty preamble contribution (F3 graceful degradation).
    preamble_doc = _resolve_preamble_doc(paper_id)
    if preamble_doc is not None:
        for chunk in all_chunks:
            chunk.preamble_ref = preamble_doc.preamble_hash

    # E02_S03 wire-in: pre-tokenize body_text into the BM25 token stream.
    # Pure local computation; no I/O. tokenize_body is deterministic
    # (NFC normalization + module-level compiled regex) so chunks remain
    # byte-stable across runs (BP1 contract).
    for chunk in all_chunks:
        chunk.body_tokens = tokenize_body(chunk.body_text)

    # E02_S04 wire-in: replace the monotonic ``arxiv:<paper_id>:idx<N>``
    # placeholder with the content-addressable
    # ``arxiv:<paper_id>:<sha256(preamble_text + body_text)[:16]>``.
    # See ``_compute_chunk_id`` for the empty-preamble fallback and the
    # NFC discipline. The hash must be assigned in a SEPARATE pass that
    # runs AFTER ``preamble_ref`` and ``body_tokens`` are populated so the
    # tokenizer wire-in cannot accidentally feed normalized bytes into the
    # chunk_id input (it doesn't today, but pinning the call order makes
    # that invariant audit-friendly).
    preamble_text = preamble_doc.preamble_text if preamble_doc is not None else ""
    # Closes F2 (MEDIUM): the duplicate-chunk_id case mixes two disjoint
    # outcomes. Genuinely duplicate (preamble, body_text) tuples — common
    # in papers that legitimately contain repeated text or
    # whitespace-collapsed copies — are silently de-duplicated to a
    # single chunk (BM25 and embedding behaviour are byte-identical for
    # identical content, so the de-dupe is safe). A genuine 64-bit
    # SHA-256 prefix collision across DIFFERENT content is caught by the
    # follow-up content check and raises with a precise message — not
    # the conflated "duplicate or collision" message of the prior code.
    seen: dict[str, str] = {}  # chunk_id -> body_text fingerprint
    deduped_chunks: list[ChunkRecord] = []
    for chunk in all_chunks:
        chunk.chunk_id = _compute_chunk_id(paper_id, preamble_text, chunk.body_text)
        if chunk.chunk_id in seen:
            if seen[chunk.chunk_id] == chunk.body_text:
                # Legitimate duplicate content — drop the second copy.
                logger.debug(
                    "[%s] dropping duplicate chunk_id %s (kind=%s) — "
                    "body_text matches prior chunk",
                    paper_id, chunk.chunk_id, chunk.kind,
                )
                continue
            # Same chunk_id, different content → real 64-bit collision.
            raise ValueError(
                f"SHA-256 prefix collision: chunk_id {chunk.chunk_id} for "
                f"paper {paper_id} maps to two distinct (preamble, body_text) "
                "tuples (~1 in 90k probability at 200K-paper scale)."
            )
        seen[chunk.chunk_id] = chunk.body_text
        deduped_chunks.append(chunk)
    all_chunks = deduped_chunks

    # Write output JSON. Cleanup happened at the top of this function
    # (closes F1); here we only write the new chunk set + manifest.
    for chunk in all_chunks:
        # Filename is the 16-char hash suffix of chunk_id (the part after
        # the last colon). Avoids colon-in-filename portability issues
        # and aligns the on-disk artifact with its content-addressable
        # identity.
        hash_suffix = chunk.chunk_id.rsplit(":", 1)[-1]
        out_path = out_dir / f"{hash_suffix}.json"
        out_path.write_text(
            json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # E02_S04: write the per-paper chunk manifest after all chunk JSONs
    # have landed. Used by the eval harness (E05_S01) to validate that
    # curated chunk_id references in the labeled query set still exist
    # after a re-chunk. Atomic write via tmp + os.replace mirrors the
    # pattern from preamble.py (closes F4/F5 from E02_S02 by
    # construction).
    _write_chunk_manifest(out_dir / "chunk_manifest.json", paper_id, all_chunks)

    return all_chunks


# ---------------------------------------------------------------------------
# Failure logging
# ---------------------------------------------------------------------------


def _resolve_preamble_doc(paper_id: str):
    """Look up the per-paper PreambleDoc from E02_S02's preamble extractor.

    Performs the lookup lazily — the import happens inside the function so
    that ``ingest.chunker`` does not pay the preamble module's cost at
    import time. The lazy import is NOT wrapped in ``except ImportError``:
    a real packaging failure should surface as a crash, not silently
    produce chunks with ``preamble_ref=None`` for the entire corpus
    (closes F3 from the E02_S02 critique). Tests that need to bypass
    preamble lookup should patch ``_resolve_preamble_doc`` itself.

    Returns the full ``PreambleDoc`` so callers can extract both
    ``preamble_hash`` (for the chunk's ``preamble_ref`` field) and
    ``preamble_text`` (for the E02_S04 content-addressable ``chunk_id``
    hash) from a single ``extract_preamble`` call.
    """
    from ingest.preamble import (
        PER_PAPER_FAILURE_EXCEPTIONS as PREAMBLE_FAILURES,
    )
    from ingest.preamble import extract_preamble

    try:
        return extract_preamble(paper_id)
    except PREAMBLE_FAILURES as exc:
        logger.warning(
            "[%s] preamble extraction failed; preamble_ref will be null "
            "and chunk_id hash will treat preamble as empty: %s",
            paper_id,
            exc,
        )
        return None


def _compute_chunk_id(paper_id: str, preamble_text: str, body_text: str) -> str:
    """Return ``arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>``.

    The hash input is ``preamble_text + NFC(body_text)`` UTF-8-encoded.
    ``preamble_text`` is already NFC (preamble.py applies F6's
    normalization at extraction time); ``body_text`` is NFC-normalised
    here for the hash but the stored ``chunk.body_text`` is left
    unchanged. This is the same discipline ``tokenize_body`` uses.

    The 16-hex-char prefix is 64 bits of entropy. At the project's 200K-
    paper end state (~20M chunks), the birthday-bound collision
    probability is ≈ 1.1×10⁻⁵ — negligible for a retrieval system, and
    we additionally fail loudly on any duplicate ``chunk_id`` per paper
    (see ``_chunk_paper_impl``).

    When the per-paper preamble is missing (extraction failed; F3
    fallback), ``preamble_text`` is ``""``. The hash then depends only
    on ``body_text``, which still keeps the chunk_id content-addressable
    and stable across re-runs of the same paper.
    """
    body_normalized = unicodedata.normalize("NFC", body_text)
    digest = hashlib.sha256(
        (preamble_text + body_normalized).encode("utf-8")
    ).hexdigest()[:16]
    return f"arxiv:{paper_id}:{digest}"


def _write_chunk_manifest(
    manifest_path: Path, paper_id: str, chunks: list[ChunkRecord]
) -> None:
    """Atomically write the per-paper chunk manifest.

    Schema (sorted JSON keys, no timestamps — BP1 byte-stable):

        {
            "chunker_version": <CHUNKER_VERSION>,
            "chunks": [
                {"chunk_id": "arxiv:...:<hash>", "kind": "stmt"},
                ...
            ],
            "paper_id": "2307.01156"
        }

    Used by E05_S01's eval harness to validate that curated ``chunk_id``
    references in the labeled query set still exist after a re-chunk.
    Mirrors the atomic-write pattern from ``preamble._write_preamble_json``
    (PID + UUID-suffixed tmp; ``os.replace``; ``try/finally`` cleanup).
    """
    manifest = {
        "chunker_version": CHUNKER_VERSION,
        "chunks": [
            {"chunk_id": c.chunk_id, "kind": c.kind} for c in chunks
        ],
        "paper_id": paper_id,
    }
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(
        f"{manifest_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, manifest_path)
    finally:
        import contextlib
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _log_chunk_failure(paper_id: str, elapsed_s: float, message: str) -> None:
    """Append a TSV row to the chunk failure log.

    Format mirrors ``fetch_seed.py``'s ``seed.log``:
    ``<paper_id>\\t<status>\\t<elapsed_s>\\t<message>``

    Closes F7: paper_id and message are sanitized to strip embedded tab and
    newline characters that would otherwise break downstream TSV parsing
    in the weekly parser-failures review.
    """
    CHUNK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = (
        f"{_sanitize_log_field(paper_id)}\tfail\t{elapsed_s:.1f}\t"
        f"{_sanitize_log_field(message)}\n"
    )
    try:
        with CHUNK_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(row)
    except OSError:
        # If we can't write the log, we still silently return [] above —
        # don't let a logging failure raise from a catch-all.
        logger.error("could not write to chunk.log: %s", CHUNK_LOG_PATH)
