"""Theorem-aware structural chunker for LaTeXML HTML5 parse trees (E02_S01).

Public API
----------
chunk_paper(paper_id: str, *, parsed_dir: Path | None = None) -> list[ChunkRecord]
    Walk ``<parsed_dir>/<paper_id>/index.html`` (``parsed_dir`` defaults to
    ``var/arxmcp/corpus/parsed``), extract all
    theorem, proof, definition, section, and similar environments, and return
    a list of :class:`~arxmcp.corpus.chunk.ChunkRecord` objects.  Output
    JSON files are written to ``var/arxmcp/corpus/chunks/<paper_id>/``.

Token budgets
-------------
Statements, sections, and fallback prose use source-substring windows of at
most 1,920 BGE-M3 tokens. Proofs use 1,856-token windows. Adjacent windows
overlap by 64 tokens and cover the complete extracted source text. The
embedder counts special tokens separately against its 2,048-token limit.

Tokenization uses ``AutoTokenizer.from_pretrained("BAAI/bge-m3")`` with
``add_special_tokens=False`` to count raw subword tokens without the
CLS/SEP inflation of ``tokenizer(text)["input_ids"]``.

Error handling
--------------
Per-paper exceptions are caught broadly inside ``chunk_paper``.  On failure
the function logs a TSV row to
``var/arxmcp/ops/parser-failures/chunk.log`` and returns ``[]``.  This
mirrors the ``PER_PAPER_FAILURE_EXCEPTIONS`` pattern from
``src/arxmcp/tools/fetch_seed.py`` (commits c486b26, 01c6579) and ensures a single
corrupt paper does not abort the ingestion loop.

Determinism (BP1)
-----------------
*Output bytes are reproducible.*  Dict keys are sorted before JSON
serialisation (see :meth:`~arxmcp.corpus.chunk.ChunkRecord.to_dict`).
No timestamps, no random content. Chunk IDs are content-addressable
``arxiv:<paper_id>:<sha256(NFC(body_text))[:16]>`` (the body only; the
paper preamble is not hashed). The hash input
uses the NFC-normalised
``body_text`` so the chunk_id is stable across hosts even when the
HTML parser emits NFD bytes; the stored ``chunk.body_text`` is left
unchanged. Any future consumer that recomputes a hash over
``chunk.body_text`` for its own cache key MUST apply the same
``unicodedata.normalize("NFC", ...)`` step or risk cache divergence
across hosts (F3 closure documents this asymmetry).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, NavigableString, Tag

# The record, its version and the chunk-id hash live in arxmcp.corpus.chunk. The id
# function is imported under its bare name so ``_chunk_paper_impl`` resolves
# it in this module's namespace (tests patch ``arxmcp.ingest.chunker.compute_chunk_id``
# and ``TestChunkerVersionFreeze`` pins its source through this re-export).
from arxmcp.corpus import (
    CHUNKER_VERSION,
    ChunkRecord,
    compute_chunk_id,
    sanitize_log_field,
    validate_paper_id,
)
from arxmcp.ingest.hidden_text import count_by_kind, scan_hidden_text
from arxmcp.ingest.tokenizer import tokenize_body
from arxmcp.settings import ApplicationPaths

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_APPLICATION_PATHS = ApplicationPaths.resolve()
PARSED_DIR = _APPLICATION_PATHS.corpus / "parsed"
CHUNKS_DIR = _APPLICATION_PATHS.corpus / "chunks"
CHUNK_LOG_PATH = _APPLICATION_PATHS.ops / "parser-failures" / "chunk.log"

# ---------------------------------------------------------------------------
# Token budget constants
# ---------------------------------------------------------------------------

BGE_M3_MAX_TOKENS = 2048
PROOF_HEADER_RESERVE = 64          # tokens reserved for statement header in proof windows
# Leave room for tokenizer special tokens and boundary retokenization.
PROOF_MAX_TOKENS = 1856
PROOF_WINDOW_OVERLAP = 64          # tokens of overlap between consecutive proof windows
# Body-first input uses no full preamble.
STMT_MAX_TOKENS = 1920

# ---------------------------------------------------------------------------
# LaTeXML CSS class patterns
# ---------------------------------------------------------------------------

# Matches ltx_theorem_<envname> on a div — captures the environment name.
_THEOREM_CLASS_RE = re.compile(r"\bltx_theorem_(\w+)\b")
# Auto-generated LaTeXML id pattern: ``[S<N>[.SS<N>[.SSS<N>]].]Thm<word><N>``.
# The section-number prefix is OPTIONAL. LaTeXML also emits *section-less*
# auto-ids like ``Thmdefix1`` / ``Thmthm2x1`` / ``Thmx1`` when a theorem
# environment is numbered independently of the section counter (a global
# amsthm counter, or an env appearing where the section counter has not
# incremented). Verified against real corpus output —
# ``var/arxmcp/corpus/parsed/0708.2247/index.html`` (``Thmdefix1``,
# ``Thmthm2x1``) and ``1409.6128`` (``Thmx1``); ~728 such divs across 57 of
# 172 parsed papers. Before the prefix was made optional these section-less
# auto-ids failed to match and ``_extract_theorem_label`` mis-read them as
# genuine ``\label{}`` keys.
_AUTO_ID_RE = re.compile(r"^(?:S\d+(?:\.SS\d+)*(?:\.SSS\d+)*\.)?Thm\w+\d+$")
# Parenthetical display name inside theorem heading: Theorem 3.1 (Name)
_PAREN_NAME_RE = re.compile(r"\(([^)]+)\)")
# source-truth-m2: the rendered "printed number" trailing a theorem tag.
# spike-2's hand-validated pattern ``[A-Za-z]?\.?\d+(\.\d+)*`` (an optional
# single appendix letter, an optional dot, then a dotted numeric run),
# anchored at the END of the ltx_tag_theorem heading text. The trailing
# ``[\s.]*`` swallows the period/space LaTeXML renders after the tag
# ("Theorem 3.1.") without letting a citation bracket ("[Ku]", "([HRS96])")
# — which ends in ]/) not a digit — match. The leading ``(?:^|[\s(\[])``
# requires a start-of-string or a whitespace/bracket boundary BEFORE the
# optional appendix letter, so a word-letter fused to a digit with no
# separator ("Corollary3") cannot have its trailing "y3" captured as the
# number (m2 rect L1). Real LaTeXML always renders a space between the tag
# word and its number ("Theorem 3.1"), so the boundary is present in every
# genuine case; a fused form is malformed input we correctly decline.
# Extracted from the RENDERED text, never the LaTeXML id/class (spike-2 §3e:
# id "A2.ThmThm1" can disagree with the rendered prefix "B.1"; the rendered
# text is the only reliable source).
_PRINTED_NUMBER_RE = re.compile(r"(?:^|[\s(\[])([A-Za-z]?\.?\d+(?:\.\d+)*)[\s.]*$")

# Closes F8: targeted exception envelope for per-paper failures, mirroring
# src/arxmcp/ingest/arxiv_fetch.py's PER_PAPER_FAILURE_EXCEPTIONS pattern (commits
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

# Structural container classes that make a render chunkable by the two
# structural passes: the section family (``_SECTION_DIV_CLASSES``, pass 2) plus
# the theorem/proof environments (pass 1). The AC4 observability signals
# (``arxmcp.ingest.ar5iv_fetch`` no-sections WARN, ``arxmcp.ingest.bulk_ingest.
# _diagnose_empty_render``) import this so their "is this render structurally
# chunkable?" substring heuristic tracks the chunker's ACTUAL gates from a
# single source and cannot silently drift apart (ingest-robustness-m1 M2/L1).
STRUCTURE_SIGNAL_CLASSES: tuple[str, ...] = tuple(_SECTION_DIV_CLASSES) + (
    "ltx_theorem",
    "ltx_proof",
)

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
    # which arxmcp.corpus.chunk.ALLOWED_KINDS rejects.
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
    weight load to ``arxmcp.corpus.embedding`` (E03_S01). The chunker itself does
    not import ``torch``.

    Closes F7 from the E03_S01 adversary critique: the tokenizer is
    pinned to :data:`arxmcp.corpus.BGE_M3_COMMIT_SHA` to satisfy
    Threat 6. Without ``revision=...``
    the tokenizer would float on whatever HuggingFace serves for the
    ``main`` tag — silent rotation of the tokenizer-only files (with
    model weights unchanged) would drift ``body_tokens`` across runs
    while ``chunker_version`` stays the same, which is a dormant
    cache-poisoning bomb for BP1 byte-stability.
    """
    global _tokenizer
    if _tokenizer is None:
        # Lazy import inside the function body, mirroring the corpus
        # model loaders, so importing the chunker never imports
        # transformers.
        from transformers import AutoTokenizer  # noqa: PLC0415

        from arxmcp.corpus import (  # noqa: PLC0415
            BGE_M3_COMMIT_SHA,
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

    Math fidelity matters more than coverage here.
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
    is present, and otherwise generates an auto-id.  The auto-id normally
    carries a section-number prefix (``S<N>.Thm<envname><N>``) but LaTeXML also
    emits *section-less* auto-ids (``Thm<envname><N>`` — e.g. ``Thmdefix1``,
    ``Thmx1``) for theorem environments numbered independently of the section
    counter.  Both forms match ``_AUTO_ID_RE``; return ``None`` for either so a
    section-less auto-id is never mistaken for a genuine ``\\label{}`` key.
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


def _extract_printed_number(tag: Tag) -> str | None:
    """Extract the rendered "printed number" from a theorem heading (m2).

    Companion to :func:`_extract_theorem_name`: reuses the SAME
    ``heading_candidates`` gathering (direct-child ``<h1-6 class="ltx_title">``
    and ``<span class="ltx_tag_theorem">`` elements, in that order) and reads
    each with the math-fidelity-preserving :func:`_element_text`, but applies
    the trailing-number pattern :data:`_PRINTED_NUMBER_RE` instead of the
    parenthetical-name pattern.

    Returns the rendered number ("3.1", "A.2", "1.5.1", "B.1") or ``None``
    when the heading carries no trailing number — the F1 case: a genuinely
    unnumbered statement ("Theorem"), a named/attributed statement whose tag
    ends in a citation bracket ("Definition ([HRS96]).") or reference
    ("Theorem [Ku]"), or an environment with no theorem-tag heading at all.
    ``None`` is a CORRECT extraction here, not a failure — the number does
    not exist to extract, mirroring how ``_extract_theorem_name`` returns
    ``None`` for an unnamed theorem.

    The ``ltx_tag_theorem`` span holds the clean "Theorem 3.1" tag with the
    parenthetical name and trailing punctuation OUTSIDE it, so it yields the
    number directly. Modern LaTeXML NESTS that span inside the ``ltx_title``
    heading; the direct-child ``ltx_title`` heading text ("Theorem 3.1
    (Riemann-Roch).") ends in the name/period and would decline to match, so
    the tag span (whether a direct child of the environment OR nested in a
    direct-child heading) is tried FIRST, with the full heading text as a
    fallback for LaTeXML output that renders the number inline with no tag
    span. Nested-span search is confined to the direct-child headings so a
    theorem nested inside this environment cannot leak its tag (the F9
    direct-children discipline ``_extract_theorem_name`` documents).

    Extraction reads only the rendered heading text — never the element ``id``
    or CSS class — so an author's independent numbering that disagrees with
    the auto-generated id is reported as rendered (spike-2 §3e).
    """
    # Direct-child ltx_title headings (h1–h6), same scan as
    # _extract_theorem_name.
    title_headings: list[Tag] = []
    for child in tag.children:
        if not isinstance(child, Tag):
            continue
        if child.name and re.match(r"^h[1-6]$", child.name):
            classes = _get_classes(child)
            if any(isinstance(c, str) and "ltx_title" in c.split() for c in classes):
                title_headings.append(child)

    # The clean tag span: a direct-child ltx_tag_theorem span (run-in style)
    # AND any ltx_tag_theorem span nested inside a direct-child heading. These
    # carry the number without the trailing parenthetical name, so try them
    # before the full heading text.
    tag_spans: list[Tag] = []
    for child in tag.children:
        if isinstance(child, Tag) and child.name == "span" and _has_class(
            child, "ltx_tag_theorem"
        ):
            tag_spans.append(child)
    for heading in title_headings:
        tag_spans.extend(
            s
            for s in heading.find_all("span", class_="ltx_tag_theorem")
            if isinstance(s, Tag)
        )

    for candidate in tag_spans + title_headings:
        text = _element_text(candidate)
        m = _PRINTED_NUMBER_RE.search(text)
        if m:
            number = m.group(1).strip()
            if number:
                return number

    return None


def _env_kind(env_name: str) -> str:
    """Map a LaTeXML environment subclass name to a ``kind`` string.

    Unknown environment names default to ``"stmt"`` — the same kind
    plain ``theorem`` maps to. Returning the raw env_name produced a
    bulk-ingest crash when papers used custom theorem environments
    not in ``_THEOREM_ENV_KINDS`` (e.g. an author's ``\\newtheorem
    {weirdthm}``) because the resulting chunk's ``kind`` is rejected
    by ``arxmcp.corpus.chunk.ALLOWED_KINDS``.
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
    return [window for window, _, _ in _window_text_spans(
        proof_text, PROOF_MAX_TOKENS, PROOF_WINDOW_OVERLAP
    )]


def _window_text_spans(
    text: str, max_tokens: int, overlap: int = 64
) -> list[tuple[str, int, int]]:
    """Cover every source character with bounded, overlapping substrings.

    Offsets refer to the exact input text, including leading/trailing spaces.
    No encode/decode round trip can alter math or punctuation.
    """
    if max_tokens <= 0 or overlap < 0 or overlap >= max_tokens:
        raise ValueError("invalid token window budget or overlap")
    tokenizer = _get_tokenizer()
    enc = tokenizer(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
    )
    token_ids = enc["input_ids"]
    offsets = enc["offset_mapping"]
    if len(token_ids) <= max_tokens:
        return [(text, 0, len(text))]

    windows: list[tuple[str, int, int]] = []
    start = 0
    while start < len(token_ids):
        end = min(start + max_tokens, len(token_ids))
        if end < len(token_ids):
            lower_token = start + max(int(max_tokens * 0.7), overlap + 1)
            lower_char = offsets[min(lower_token, end - 1)][0]
            upper_char = offsets[end - 1][1]
            for pattern in (r"\n\s*\n", r"[.!?]\s+"):
                candidates = list(re.finditer(pattern, text[lower_char:upper_char]))
                for match in reversed(candidates):
                    boundary = lower_char + match.end()
                    delimiters = re.findall(r"(?<!\\)\$\$|(?<!\\)\$", text[:boundary])
                    open_math: str | None = None
                    for delimiter in delimiters:
                        if open_math is None:
                            open_math = delimiter
                        elif open_math == delimiter:
                            open_math = None
                    if open_math is not None:
                        continue
                    candidate_end = end
                    while (
                        candidate_end > start + overlap + 1
                        and offsets[candidate_end - 1][1] > boundary
                    ):
                        candidate_end -= 1
                    if candidate_end > start + overlap + 1:
                        end = candidate_end
                        break
                if end != min(start + max_tokens, len(token_ids)):
                    break
        char_start = offsets[start][0]
        char_start = min(char_start, windows[-1][2]) if windows else 0
        char_end = len(text) if end == len(token_ids) else offsets[end - 1][1]
        windows.append((text[char_start:char_end], char_start, char_end))
        if end >= len(token_ids):
            break
        start = end - overlap

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
            # DEBUG (not WARNING): an orphan proof — a <div class="ltx_proof">
            # not immediately preceded by a theorem environment — is a
            # *structural* feature of many real papers (math.AG corpus
            # alone produces 10-30 per long paper). The chunker correctly
            # tags these as kind='proof'; no operator action is required.
            # Promoting to WARNING level made the log unreadable during
            # corpus-wide re-embeds. Operators who want the per-paper
            # detail can set the chunker logger to DEBUG.
            logger.debug(
                "[%s] orphan proof at index %d in <%s>; emitting as kind='proof'",
                paper_id,
                i,
                container.name,
            )
            section_path = _extract_section_path(child)
            proof_text = _element_text(child)
            proof_windows = _window_text_spans(
                proof_text, PROOF_MAX_TOKENS, PROOF_WINDOW_OVERLAP
            )
            for part_index, (window, source_start, source_end) in enumerate(proof_windows, 1):
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
                        part_index=part_index,
                        part_count=len(proof_windows),
                        source_start=source_start,
                        source_end=source_end,
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
        # source-truth-m2: rendered theorem number ("3.1"/"A.2"/...) from the
        # same heading tag. None when unnumbered (F1). The paired proof chunk
        # inherits it below, matching theorem_name/theorem_label inheritance.
        printed_number = _extract_printed_number(child)
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
        # Windows retain every source character; to do that,
        # use character-offset slicing, not encode/decode round-trip.
        stmt_windows = _window_text_spans(stmt_text, STMT_MAX_TOKENS)
        for part_index, (window, source_start, source_end) in enumerate(stmt_windows, 1):
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
                    body_text=window,
                    printed_number=printed_number,
                    part_index=part_index,
                    part_count=len(stmt_windows),
                    source_start=source_start,
                    source_end=source_end,
                )
            )

        # ----------------------------------------------------------------
        # Emit proof chunk(s) if paired
        # ----------------------------------------------------------------
        if proof_child is not None:
            proof_text = _element_text(proof_child)
            proof_windows = _window_text_spans(
                proof_text, PROOF_MAX_TOKENS, PROOF_WINDOW_OVERLAP
            )
            for part_index, (window, source_start, source_end) in enumerate(proof_windows, 1):
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
                        printed_number=printed_number,
                        part_index=part_index,
                        part_count=len(proof_windows),
                        source_start=source_start,
                        source_end=source_end,
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
        # offset-mapping while preserving every source character.
        prose_windows = _window_text_spans(prose, STMT_MAX_TOKENS)
        for part_index, (window, source_start, source_end) in enumerate(prose_windows, 1):
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
                    body_text=window,
                    part_index=part_index,
                    part_count=len(prose_windows),
                    source_start=source_start,
                    source_end=source_end,
                )
            )

    return chunks


_LABELED_PARA_RE = re.compile(
    r"^(Theorem|Lemma|Proposition|Corollary|Definition|Remark|Example)\s+"
    r"(\d+(?:\.\d+)*[A-Za-z]?)\.(?:\s|$)", re.IGNORECASE
)
_LABELED_HEADING_RE = re.compile(
    r"^(\d+(?:\.\d+)*)\.\s+"
    r"(?:Main\s+)?(Theorem|Lemma|Proposition|Corollary|Definition)\b",
    re.IGNORECASE,
)
_PROOF_HEADING_RE = re.compile(
    r"^\d+(?:\.\d+)*\.\s+Proof of (?:Theorem|Lemma|Proposition|Propositions)\s+"
    r"(\d+(?:\.\d+)*)\b", re.IGNORECASE,
)


def _extract_labeled_result_chunks(
    soup: BeautifulSoup, paper_id: str, counter: list[int]
) -> list[ChunkRecord]:
    """Recover local results rendered as labels in prose or headings.

    A label must begin the paragraph or heading. References such as
    ``Theorem 3 of [12]`` and ordinary mid-sentence citations are excluded.
    Structural LaTeXML theorem containers are handled by the main pass.
    """
    chunks: list[ChunkRecord] = []
    for tag in soup.find_all(["p", "h2", "h3", "h4", "h5", "h6"]):
        if any(
            any(_THEOREM_CLASS_RE.match(c) or c == "ltx_proof" for c in _get_classes(parent))
            for parent in tag.parents if isinstance(parent, Tag)
        ):
            continue
        label_text = tag.get_text(" ", strip=True)
        para_match = _LABELED_PARA_RE.match(label_text) if tag.name == "p" else None
        if para_match and re.match(
            r"(?:implies|states|shows|gives|yields|proves|of|in|from)\b",
            label_text[para_match.end():].lstrip(), re.IGNORECASE,
        ):
            para_match = None
        heading_match = _LABELED_HEADING_RE.match(label_text) if tag.name != "p" else None
        if para_match:
            kind, printed_number = para_match.group(1).lower(), para_match.group(2)
            parent = tag.parent if isinstance(tag.parent, Tag) else tag
            body = _element_text(parent)
            source_id = parent.get("id") or tag.get("id")
        elif heading_match:
            printed_number, kind = heading_match.group(1), heading_match.group(2).lower()
            parent = tag.parent if isinstance(tag.parent, Tag) else tag
            body = " ".join(
                _element_text(child) for child in parent.children
                if isinstance(child, Tag) and child is not tag
                and child.name not in {"section", "article"}
            ).strip()
            source_id = parent.get("id")
        else:
            continue
        if not body:
            continue
        windows = _window_text_spans(body, STMT_MAX_TOKENS)
        for part_index, (window, start, end) in enumerate(windows, 1):
            idx = counter[0]
            counter[0] += 1
            chunks.append(ChunkRecord(
                chunk_id=f"arxiv:{paper_id}:idx{idx}",
                paper_id=paper_id,
                kind="stmt" if kind == "theorem" else kind,
                section_path=_extract_section_path(tag),
                theorem_name=None,
                theorem_label=source_id,
                body_text=window,
                printed_number=printed_number,
                part_index=part_index,
                part_count=len(windows),
                source_start=start,
                source_end=end,
            ))
    labels_by_number = {
        chunk.printed_number: chunk.theorem_label
        for chunk in chunks if chunk.printed_number and chunk.theorem_label
    }
    for tag in soup.find_all(["h2", "h3", "h4", "h5", "h6"]):
        match = _PROOF_HEADING_RE.match(tag.get_text(" ", strip=True))
        if match is None or not isinstance(tag.parent, Tag):
            continue
        parent = tag.parent
        body = " ".join(
            _element_text(child) for child in parent.children
            if isinstance(child, Tag) and child is not tag
            and child.name not in {"section", "article"}
        ).strip()
        if not body:
            continue
        windows = _window_text_spans(body, PROOF_MAX_TOKENS, PROOF_WINDOW_OVERLAP)
        for part_index, (window, start, end) in enumerate(windows, 1):
            idx = counter[0]
            counter[0] += 1
            chunks.append(ChunkRecord(
                chunk_id=f"arxiv:{paper_id}:idx{idx}",
                paper_id=paper_id, kind="proof",
                section_path=_extract_section_path(tag),
                theorem_name=None,
                theorem_label=labels_by_number.get(match.group(1)),
                body_text=window, printed_number=match.group(1),
                part_index=part_index, part_count=len(windows),
                source_start=start, source_end=end,
            ))
    return chunks


def _link_labeled_proofs(
    soup: BeautifulSoup, proof_chunks: list[ChunkRecord]
) -> None:
    """Pair adjacent HTML proof blocks with paragraph-labeled results."""
    by_body: dict[str, list[ChunkRecord]] = {}
    for chunk in proof_chunks:
        if chunk.kind == "proof" and chunk.theorem_label is None:
            by_body.setdefault(chunk.body_text, []).append(chunk)
    for tag in soup.find_all("p"):
        match = _LABELED_PARA_RE.match(tag.get_text(" ", strip=True))
        if match is None or not isinstance(tag.parent, Tag):
            continue
        parent = tag.parent
        following = parent.find_next_sibling()
        if not isinstance(following, Tag) or not _has_class(following, "ltx_proof"):
            continue
        source_id = parent.get("id") or tag.get("id")
        for window in _window_proof_text(_element_text(following)):
            for chunk in by_body.get(window, []):
                chunk.theorem_label = source_id
                chunk.printed_number = match.group(2)


def _extract_body_fallback_chunks(
    root: Tag,
    paper_id: str,
    counter: list[int],
) -> list[ChunkRecord]:
    """Fallback prose extraction for section-less, theorem-less renders.

    LaTeXML occasionally fails its sectioning/title pass on old submission
    formats (notably pre-2010 hep-th papers): it emits a COMPLETE body —
    real prose in ``ltx_para``/``ltx_p`` blocks directly under
    ``ltx_document`` with inline ``<math>`` — but ZERO
    ``ltx_section``/``ltx_theorem`` containers. Both structural passes
    (:func:`_extract_chunks_from_container` and
    :func:`_extract_section_chunks`) then return nothing and the paper is
    dropped as ``chunker_returned_empty`` despite carrying full content
    (observed on hep-th/0002037: 93 ``ltx_para`` blocks, 321 ``<math>``,
    title "Untitled Document").

    This fallback runs ONLY when both structural passes yielded zero chunks
    (guarded at the call site by ``if not all_chunks:``), so it can never
    perturb a sectioned paper's output. It harvests the top-level prose
    blocks under the document container in document order, token-packs them
    into ``STMT_MAX_TOKENS``-bounded chunks, and emits ``kind="section"``
    records with an empty ``section_path``. Placeholder ids are assigned
    here; :func:`_chunk_paper_impl`'s post-pass replaces them with the
    content-addressable :func:`compute_chunk_id` hash and applies the same
    dedup rule, so fallback chunks inherit determinism and collision-safety
    unchanged.

    Returns ``[]`` when there is no non-trivial harvestable prose (a
    math-only or genuinely empty render) — preserving the empty outcome
    that :mod:`arxmcp.ingest.bulk_ingest` categorizes for the residual unchunkable
    case (the ``render_unchunkable_no_sections`` signal).
    """
    MIN_BLOCK_CHARS = 80  # skip trivial blocks (mirrors _extract_section_chunks)

    # Locate the document container. ``root`` is <body> (or the soup);
    # ar5iv wraps the article body in <article class="ltx_document">, with
    # the prose sometimes one level down in <div class="ltx_page_content">.
    doc = (
        root.find(class_="ltx_document")
        or root.find(class_="ltx_page_content")
        or root
    )

    # Prefer LaTeXML's prose-block class ``ltx_para`` (a <div>), taking only
    # TOP-LEVEL blocks (not those nested inside another ltx_para) so text is
    # never double-counted. Fall back to raw ``ltx_p`` paragraphs, then bare
    # <p>. Each tier is a document-order list of prose blocks.
    #
    # KNOWN LIMITATION (ingest-robustness-m1 M3, deferred): a section-less
    # render's *standalone* top-level display-math containers
    # (``ltx_equation``/``ltx_equationgroup`` not wrapped in an ``ltx_para``)
    # are not harvested here. On the old-format renders this fallback targets
    # (e.g. hep-th/0002037) the math is inline within ``ltx_para`` prose and IS
    # preserved by ``_element_text`` (which emits ``<math alttext>`` as
    # ``$...$``); free-standing display equations are a rarer shape left to a
    # follow-up rather than dropped silently.
    blocks = [
        b
        for b in doc.find_all("div", class_="ltx_para")
        if b.find_parent("div", class_="ltx_para") is None
    ]
    if not blocks:
        blocks = doc.find_all("p", class_="ltx_p")
    if not blocks:
        blocks = doc.find_all("p")

    # Math-fidelity-preserving text per non-trivial block, document order.
    texts: list[str] = []
    for block in blocks:
        text = _element_text(block)
        if len(text) >= MIN_BLOCK_CHARS:
            texts.append(text)
    if not texts:
        return []

    chunks: list[ChunkRecord] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def _flush() -> None:
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        prose = " ".join(buffer).strip()
        prose_windows = _window_text_spans(prose, STMT_MAX_TOKENS)
        for part_index, (window, source_start, source_end) in enumerate(prose_windows, 1):
            idx = counter[0]
            counter[0] += 1
            chunks.append(
                ChunkRecord(
                    chunk_id=f"arxiv:{paper_id}:idx{idx}",
                    paper_id=paper_id,
                    kind="section",
                    section_path=[],
                    theorem_name=None,
                    theorem_label=None,
                    body_text=window,
                    part_index=part_index,
                    part_count=len(prose_windows),
                    source_start=source_start,
                    source_end=source_end,
                )
            )
        buffer = []
        buffer_tokens = 0

    # Token-pack blocks into STMT_MAX_TOKENS-bounded chunks. A single
    # oversized block is emitted through the same no-loss window path.
    for text in texts:
        n = _count_tokens(text)
        if buffer and buffer_tokens + n > STMT_MAX_TOKENS:
            _flush()
        buffer.append(text)
        buffer_tokens += n
    _flush()

    return chunks


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def chunk_paper(
    paper_id: str, *, parsed_dir: Path | None = None
) -> list[ChunkRecord]:
    """Chunk one paper and write output JSON files.

    Parameters
    ----------
    paper_id:
        Canonical arXiv ID, e.g. ``"2307.01156"``.
    parsed_dir:
        Root of the parsed-HTML tree; the paper is read from
        ``<parsed_dir>/<paper_id>/index.html``. Defaults to
        :data:`PARSED_DIR`. Pass the same directory the HTML was fetched
        into (for example ``arxmcp.ingest.ar5iv_fetch.try_cache(parsed_dir=...)``).

    Returns
    -------
    list[ChunkRecord]
        All chunks emitted for the paper.  Returns ``[]`` and logs a failure
        row to ``chunk.log`` if any unrecoverable error occurs.

    Side effects
    ------------
    Writes ``var/arxmcp/corpus/chunks/<paper_id>/<hash16>.json`` for each
    chunk plus ``chunk_manifest.json``.  Creates the directory if it does not
    exist.  The previous chunk set is replaced only once the new one is
    complete; a failed run leaves it as it was.
    """
    # Closes F2: validate paper_id before any path concat or logging.
    # Validation runs OUTSIDE the per-paper exception envelope so an invalid
    # paper_id surfaces to the caller rather than being silently logged with
    # itself as the offending field.
    validate_paper_id(paper_id)

    start = time.monotonic()
    try:
        return _chunk_paper_impl(paper_id, parsed_dir)
    except PER_PAPER_FAILURE_EXCEPTIONS as exc:
        # Closes F8: catch only the resilience-pattern exception set, NOT a
        # bare `except Exception`. Programmer bugs (AttributeError, KeyError,
        # TypeError) propagate to surface during dev.
        elapsed = time.monotonic() - start
        _log_chunk_failure(paper_id, elapsed, str(exc))
        logger.error("[%s] chunk_paper failed: %s", paper_id, exc, exc_info=True)
        return []


def _chunk_paper_impl(paper_id: str, parsed_dir: Path | None) -> list[ChunkRecord]:
    if paper_id in {"1309.5035", "1802.01134"}:
        # These authentic sources have incomplete LaTeXML renders. Keep the
        # verified TeX extraction behind the public chunker entry point so
        # ordinary ingestion and re-embedding produce the same sidecars.
        from arxmcp.ingest.tex_formal_chunker import chunk_tex_formals

        chunks = chunk_tex_formals(paper_id)
        _write_chunk_set(CHUNKS_DIR / paper_id, paper_id, chunks)
        return chunks

    parsed_root = PARSED_DIR if parsed_dir is None else parsed_dir
    parsed_html = parsed_root / paper_id / "index.html"
    if not parsed_html.exists():
        raise FileNotFoundError(
            f"parsed HTML not found at {parsed_html}; "
            "run src/arxmcp/tools/fetch_seed.py first"
        )

    html_bytes = parsed_html.read_bytes()
    soup = BeautifulSoup(html_bytes, "html.parser")

    body = soup.find("body")
    root: Tag = body if isinstance(body, Tag) else soup  # type: ignore[assignment]

    # Warn only: hidden text is reported for review and still chunked, so
    # chunk bodies and ids do not depend on the scan. The counts are logged,
    # never the text, which is untrusted.
    hidden = scan_hidden_text(root)
    if hidden:
        logger.warning(
            "[%s] hidden-text scan: %d element(s) carry invisible text %s",
            paper_id,
            len(hidden),
            count_by_kind(hidden),
        )

    counter = [0]

    # Pass 1: theorem/proof pairs and unmatched theorem-like environments
    theorem_chunks = _extract_chunks_from_container(root, paper_id, counter)
    if paper_id in {"1607.08199", "1711.08504"}:
        # LaTeXML renders the formal statements for these sources but drops
        # every proof environment. The authentic TeX formal sequence matches
        # the HTML sequence exactly, so attach its labels in source order and
        # supplement the missing proof bodies with TeX source spans.
        from arxmcp.ingest.tex_formal_chunker import chunk_tex_formals

        tex_chunks = chunk_tex_formals(paper_id)
        tex_formals = [
            c for c in tex_chunks
            if c.kind not in {"proof", "section"} and c.part_index == 1
        ]
        html_formals = [c for c in theorem_chunks if c.kind != "proof" and c.part_index == 1]
        if len(tex_formals) != len(html_formals):
            raise ValueError(
                f"{paper_id}: TeX/HTML formal sequence differs: "
                f"{len(tex_formals)} versus {len(html_formals)}"
            )
        formal_index = -1
        for chunk in theorem_chunks:
            if chunk.kind == "proof":
                continue
            if chunk.part_index == 1:
                formal_index += 1
            chunk.theorem_label = tex_formals[formal_index].theorem_label
        theorem_chunks.extend(c for c in tex_chunks if c.kind == "proof")

    # Pass 2: section-level prose chunks
    section_chunks = _extract_section_chunks(soup, paper_id, counter)

    labeled_chunks = _extract_labeled_result_chunks(soup, paper_id, counter)
    _link_labeled_proofs(soup, theorem_chunks)
    # Prefer a formal kind when the section prose has byte-identical body
    # text; content-addressable dedup keeps the first copy.
    all_chunks = theorem_chunks + labeled_chunks + section_chunks

    # ingest-robustness-m1 (AC1): section-less fallback. LaTeXML sometimes
    # renders a complete body (ltx_para/ltx_p prose + inline <math>) with
    # ZERO ltx_section/ltx_theorem containers on old submission formats, so
    # both passes above yield nothing and the paper is dropped despite
    # carrying full content. Recover the prose ONLY when both passes were
    # empty — this guard guarantees byte-identical output for every
    # sectioned paper (they always yield >=1 chunk from pass 1 or 2).
    if not all_chunks:
        all_chunks = _extract_body_fallback_chunks(root, paper_id, counter)

    # Resolve the per-paper preamble to stamp ``preamble_ref`` (its
    # hash). The preamble reaches neither the chunk id nor the embedding
    # input (``body-first-v1``). When extraction fails, ``preamble_doc``
    # is None and the chunker still emits every chunk; the ids are the
    # same either way.
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
    # ``arxiv:<paper_id>:<sha256(NFC(body_text))[:16]>`` (the body only,
    # no position value). TeX proofs merged in above for the
    # hybrid papers lose their ``tex-offset`` ids here and take the same
    # body-only id; only a TeX-chunker-owned paper (the early return at the
    # top of this function) keeps its position value. See
    # ``compute_chunk_id`` for the NFC discipline. The hash must be
    # assigned in a SEPARATE pass that runs AFTER ``preamble_ref`` and
    # ``body_tokens`` are populated so the tokenizer wire-in cannot
    # accidentally feed normalized bytes into the chunk_id input (it
    # doesn't today, but pinning the call order makes that invariant
    # audit-friendly).
    #
    # Closes F2 (MEDIUM): the duplicate-chunk_id case mixes two disjoint
    # outcomes. Genuinely duplicate body_text values — common
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
        chunk.chunk_id = compute_chunk_id(paper_id, chunk.body_text)
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
                f"paper {paper_id} maps to two distinct body_text values "
                "(~1 in 90k probability at 200K-paper scale)."
            )
        seen[chunk.chunk_id] = chunk.body_text
        deduped_chunks.append(chunk)
    all_chunks = deduped_chunks

    # Nothing on disk changes until the whole new set exists, so any
    # failure above leaves the previous chunk set intact.
    _write_chunk_set(CHUNKS_DIR / paper_id, paper_id, all_chunks)

    return all_chunks


# ---------------------------------------------------------------------------
# Failure logging
# ---------------------------------------------------------------------------


def _resolve_preamble_doc(paper_id: str):
    """Look up the per-paper PreambleDoc from E02_S02's preamble extractor.

    Performs the lookup lazily — the import happens inside the function so
    that ``arxmcp.ingest.chunker`` does not pay the preamble module's cost at
    import time. The lazy import is NOT wrapped in ``except ImportError``:
    a real packaging failure should surface as a crash, not silently
    produce chunks with ``preamble_ref=None`` for the entire corpus
    (closes F3 from the E02_S02 critique). Tests that need to bypass
    preamble lookup should patch ``_resolve_preamble_doc`` itself.

    Returns the full ``PreambleDoc``; the chunker reads its
    ``preamble_hash`` for the chunk's ``preamble_ref`` field. The
    preamble does not reach the chunk id.
    """
    from arxmcp.ingest.preamble import (
        PER_PAPER_FAILURE_EXCEPTIONS as PREAMBLE_FAILURES,
    )
    from arxmcp.ingest.preamble import extract_preamble

    try:
        return extract_preamble(paper_id)
    except PREAMBLE_FAILURES as exc:
        logger.warning(
            "[%s] preamble extraction failed; preamble_ref will be null "
            "(chunk ids do not depend on the preamble): %s",
            paper_id,
            exc,
        )
        return None


_CHUNK_MANIFEST_NAME = "chunk_manifest.json"


def _write_chunk_set(
    out_dir: Path, paper_id: str, chunks: list[ChunkRecord]
) -> None:
    """Replace the paper's on-disk chunk set with ``chunks``.

    Readers reach chunk files only through ``chunk_manifest.json``, so the
    manifest replacement is the commit point:

    1. every new chunk JSON is written to a temporary file and then moved
       onto its final name;
    2. the manifest is replaced atomically;
    3. chunk JSONs the new manifest does not list, and leftover temporary
       files, are removed.

    A failure before step 2 leaves the previous manifest and every file it
    lists in place. Each chunk file is named by the 16-char hash suffix of
    its ``chunk_id``, which keeps colons out of file names.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_suffix = f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    keep = {_CHUNK_MANIFEST_NAME}
    staged: list[tuple[Path, Path]] = []
    try:
        for chunk in chunks:
            name = f"{chunk.chunk_id.rsplit(':', 1)[-1]}.json"
            tmp = out_dir / f"{name}{tmp_suffix}"
            tmp.write_text(
                json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            staged.append((tmp, out_dir / name))
            keep.add(name)
        for tmp, final in staged:
            os.replace(tmp, final)
    finally:
        for tmp, _final in staged:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)

    _write_chunk_manifest(out_dir / _CHUNK_MANIFEST_NAME, paper_id, chunks)

    for path in out_dir.iterdir():
        if path.name not in keep and path.suffix in {".json", ".tmp"}:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()


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
        f"{sanitize_log_field(paper_id)}\tfail\t{elapsed_s:.1f}\t"
        f"{sanitize_log_field(message)}\n"
    )
    try:
        with CHUNK_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(row)
    except OSError:
        # If we can't write the log, we still silently return [] above —
        # don't let a logging failure raise from a catch-all.
        logger.error("could not write to chunk.log: %s", CHUNK_LOG_PATH)
