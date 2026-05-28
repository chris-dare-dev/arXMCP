"""Hierarchical textbook chunker (textbook-ingest-m7, e3 spine).

A thin driver over :mod:`ingest.chunker`'s structural primitives that
chunks the HTML5+MathML a textbook PDF produces (MinerU → LaTeXML via
m5/m6) at **book / chapter / section** granularity. Theorem / lemma /
proof environments inside a section pair exactly as they do for arXiv
papers — this module REUSES the existing pairing primitives rather than
reimplementing them.

Public API
----------
``chunk_textbook(slug, paper_id) -> list[ChunkRecord]``
    Read ``var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/index.html``,
    emit chunks tagged ``source_kind="textbook"`` with the chapter
    breadcrumb populated, and write per-chunk JSONs to
    ``var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/``. Returns the
    record list. Mirrors :func:`ingest.chunker.chunk_paper`'s resilience
    envelope (logs a failure row + returns ``[]`` on a per-paper error;
    programmer bugs propagate).

Design decisions (research-synthesis §"LOAD-BEARING constraints")
-----------------------------------------------------------------
1. Does NOT call :func:`ingest.chunker._compute_chunk_id` — that hardcodes
   the ``arxiv:`` prefix. Uses :func:`_compute_textbook_chunk_id` which
   emits ``textbook:<slug>:<sha>`` with the SAME hash discipline.
2. Does NOT call ``_resolve_preamble_doc`` — it resolves the arXiv
   preamble store (wrong tree; the ``:`` is an invalid path byte).
   ``preamble_text`` is PERMANENTLY ``""`` for PDF-sourced textbooks
   (textbook-ingest-m8 OQ-1 decision): MinerU emits math already
   expanded at the PDF-render level, so there are no author macros to
   inherit. NOT a placeholder — see
   ``.claude/docs/textbook-preamble-decision.md``.
3. Replicates the ``_chunk_paper_impl`` dedup loop — same body + empty
   preamble → same chunk_id; without dedup the second JSON would
   silently overwrite the first on disk (m7 FM-4).
4. ``page_start`` / ``page_end`` stay ``None`` — MinerU's
   ``content_list.json`` page metadata is not propagated through the
   LaTeXML render. Correlating it back is a future item (not in the e3
   outcome); see textbook-preamble-decision.md §related-deferrals.
5. ``TEXTBOOK_CHUNKER_VERSION`` is SEPARATE from
   ``chunker_types.CHUNKER_VERSION`` so a textbook-only change never
   forces arXiv corpus re-embedding.
6. Writes chunk JSONs only — NOT LanceDB. Embedding/LanceDB-write is a
   downstream step (matches ``chunk_paper``'s contract); this keeps the
   spike-3 per-notebook LanceDB isolation boundary untouched by m7.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import unicodedata
import uuid
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from ingest.chunker import (
    PER_PAPER_FAILURE_EXCEPTIONS,
    _extract_chunks_from_container,
    _extract_section_chunks,
    _get_classes,
    _sanitize_log_field,
    _validate_paper_id,
)
from ingest.chunker_types import ChunkRecord
from ingest.tokenizer import tokenize_body
from tools._notebook_common import NotebookError, notebook_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS_BASE = REPO_ROOT / "var" / "arxmcp" / "notebooks"

#: Deliberately SEPARATE from ``chunker_types.CHUNKER_VERSION`` (the arXiv
#: chunker version): a textbook-chunker change must NOT trigger arXiv
#: corpus re-embedding. The ``tv`` prefix marks textbook chunks distinctly;
#: ``0.1`` is the v0 cut (book/chapter/section only — no definition/
#: exercise levels yet). Single-source-of-truth guard
#: (tests/test_chunker_ids.py) forbids quoting the arXiv version literal
#: here, hence the descriptive reference.
TEXTBOOK_CHUNKER_VERSION = "tv0.1"

#: Parser provenance stamped on every textbook chunk (m5 MinerU + m6
#: LaTeXML). Enum member of the m2 ``parser_used`` domain.
TEXTBOOK_PARSER_USED = "mineru+latexml"


# ---------------------------------------------------------------------------
# Path builders
# ---------------------------------------------------------------------------


def _flat_paper_id(paper_id: str) -> str:
    """Flatten a paper_id to a path-safe form (mirrors the m6 renderer).

    ``textbook:my-book`` → ``textbook_my-book``.
    """
    return paper_id.replace("/", "_").replace(":", "_")


def _resolve_notebook_dir(slug: str) -> Path:
    """Return the symlink-checked, containment-checked notebook dir.

    Routes through ``tools._notebook_common.notebook_dir`` (m6 F3) so
    the textbook chunker shares the same belt-and-braces posture as the
    rest of the notebook surface (notebook_init / fetch / ingest /
    purge): ``validate_slug`` (primary regex defense) + symlink refusal
    + ``.resolve()`` containment. Passing ``base=NOTEBOOKS_BASE`` keeps
    the test-patch of this module's constant effective.
    """
    return notebook_dir(slug, base=NOTEBOOKS_BASE)


def _textbook_html_path(nb_dir: Path, paper_id: str) -> Path:
    """Resolve m6's HTML5 output path under a resolved notebook dir."""
    return nb_dir / "parsed" / _flat_paper_id(paper_id) / "index.html"


def _textbook_chunks_dir(nb_dir: Path, paper_id: str) -> Path:
    """Per-notebook chunk-JSON output dir (mirrors arXiv corpus/chunks/)."""
    return nb_dir / "chunks" / _flat_paper_id(paper_id)


def _textbook_chunk_log_path(nb_dir: Path) -> Path:
    """Per-notebook chunk-failure log (analogous to corpus chunk.log)."""
    return nb_dir / "ops" / "chunk-failures.log"


# ---------------------------------------------------------------------------
# Chunk-id (textbook prefix — NOT the arxiv: hardcode in chunker.py)
# ---------------------------------------------------------------------------


def _compute_textbook_chunk_id(
    slug: str, preamble_text: str, body_text: str
) -> str:
    """Return ``textbook:<slug>:<sha256(preamble_text + NFC(body_text))[:16]>``.

    Identical hash discipline to
    :func:`ingest.chunker._compute_chunk_id` (NFC-normalize body, UTF-8
    encode, 16-hex prefix) but emits the ``textbook:`` prefix so the
    id round-trips through ``ingest.identifiers.CHUNK_ID_PATTERN``. The
    arXiv helper hardcodes ``arxiv:`` and cannot be reused directly.
    """
    body_normalized = unicodedata.normalize("NFC", body_text)
    digest = hashlib.sha256(
        (preamble_text + body_normalized).encode("utf-8")
    ).hexdigest()[:16]
    return f"textbook:{slug}:{digest}"


# ---------------------------------------------------------------------------
# Chapter-label extraction
# ---------------------------------------------------------------------------


def _section_title_text(section_tag: Tag) -> str | None:
    """Extract a section's title text, mirroring ``_extract_section_path``.

    Uses the same ``ltx_title``-class heuristic + whitespace collapse so
    the returned string byte-matches the corresponding ``section_path``
    breadcrumb entry (the chapter-label match in
    :func:`_collect_chapter_titles` relies on this equality).
    """
    def _has_ltx_title(c: object) -> bool:
        return isinstance(c, str) and "ltx_title" in c.split()

    title_tag = section_tag.find(True, class_=_has_ltx_title, recursive=False)
    if title_tag is None:
        title_tag = section_tag.find(True, class_=_has_ltx_title)
    if title_tag is None:
        return None
    text = " ".join(title_tag.get_text(separator=" ").split())
    return text or None


def _chapter_title_text(chapter_tag: Tag) -> str | None:
    """Extract a chapter element's OWN title (m7 F1).

    Prefers a non-recursive match on the chapter-specific
    ``ltx_title_chapter`` class — this prevents the recursive
    ``_section_title_text`` fallback from descending into the chapter's
    first nested ``ltx_section`` and returning the SECTION title when
    the chapter heading itself lacks the generic ``ltx_title`` class
    (some LaTeXML configs emit ``ltx_title_chapter`` only). Falls back
    to ``_section_title_text`` only when no chapter-specific title is
    found.
    """
    def _has_chapter_title(c: object) -> bool:
        return isinstance(c, str) and "ltx_title_chapter" in c.split()

    title_tag = chapter_tag.find(
        True, class_=_has_chapter_title, recursive=False
    )
    if title_tag is None:
        # Some LaTeXML configs nest the chapter heading one level deeper
        # (but still tagged ltx_title_chapter) — recursive match is safe
        # here because we match the CHAPTER-specific class, not the
        # generic ltx_title that a nested section would carry.
        title_tag = chapter_tag.find(True, class_=_has_chapter_title)
    if title_tag is not None:
        text = " ".join(title_tag.get_text(separator=" ").split())
        if text:
            return text
    # Last resort: the generic title extractor (matches the
    # section_path breadcrumb for the well-formed case).
    return _section_title_text(chapter_tag)


def _collect_chapter_titles(soup: BeautifulSoup) -> set[str]:
    """Return the set of chapter-level section titles in the document.

    Finds every element whose class list contains ``ltx_chapter`` and
    collects its OWN title text (via :func:`_chapter_title_text`, which
    prefers the ``ltx_title_chapter`` class to avoid pulling a nested
    section title — m7 F1). A chunk's ``chapter`` field is then the
    first ``section_path`` breadcrumb that is in this set (robust to a
    ``\\part`` above the chapter). Empty set ⇒ no chapter structure ⇒
    all chunks get ``chapter=None`` (m7 FM-1: flat/article-class).

    **v0 limitation (m7 F2):** two ``ltx_chapter`` elements with the
    SAME title text collapse to one set entry, so their chunks become
    indistinguishable on the ``chapter`` field. The chunk_id stays
    unique (content-addressable), so this is a label-fidelity limit,
    not data loss. Disambiguating identical chapter titles (by ordinal
    / element id) is deferred to m8. Realistic trigger: two chapters
    both titled "Introduction" in a multi-part lecture-notes volume.
    """
    titles: set[str] = set()
    for el in soup.find_all(True):
        if not isinstance(el, Tag):
            continue
        if "ltx_chapter" in _get_classes(el):
            t = _chapter_title_text(el)
            if t:
                titles.add(t)
    return titles


def _chapter_for_chunk(
    chunk: ChunkRecord, chapter_titles: set[str]
) -> str | None:
    """Pick the chunk's chapter label from its section_path breadcrumb.

    Returns the first breadcrumb entry that is a known chapter title, or
    ``None`` when the chunk is not under any chapter (or the document has
    no chapter structure).
    """
    for crumb in chunk.section_path:
        if crumb in chapter_titles:
            return crumb
    return None


# ---------------------------------------------------------------------------
# Public driver
# ---------------------------------------------------------------------------


def chunk_textbook(slug: str, paper_id: str) -> list[ChunkRecord]:
    """Chunk a textbook's m6 HTML5 output at book/chapter/section grain.

    Parameters
    ----------
    slug:
        Notebook slug (validated via ``validate_slug``).
    paper_id:
        Textbook paper_id, e.g. ``"textbook:shimura-varieties"``
        (validated via the shared ``_validate_paper_id``).

    Returns
    -------
    list[ChunkRecord]
        All textbook chunks emitted, or ``[]`` on an unrecoverable
        per-paper error (a failure row is logged). Programmer bugs
        (AttributeError, KeyError, TypeError) propagate.

    Side effects
    ------------
    Writes ``var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/<hash>.json``
    per chunk + a ``chunk_manifest.json``. Does NOT write LanceDB.
    """
    # Validate OUTSIDE the resilience envelope so a bad/unsafe slug or
    # paper_id surfaces to the caller (mirrors chunk_paper's
    # _validate_paper_id placement). notebook_dir runs validate_slug +
    # symlink refusal + containment (m7 F3); _validate_paper_id raises
    # InvalidPaperIDError (a ValueError).
    try:
        nb_dir = _resolve_notebook_dir(slug)
    except NotebookError as exc:
        raise ValueError(
            f"invalid or unsafe notebook slug {slug!r}: {exc}"
        ) from exc
    _validate_paper_id(paper_id)

    start = time.monotonic()
    try:
        return _chunk_textbook_impl(nb_dir, slug, paper_id)
    except PER_PAPER_FAILURE_EXCEPTIONS as exc:
        elapsed = time.monotonic() - start
        _log_chunk_failure(nb_dir, paper_id, elapsed, str(exc))
        logger.error(
            "[%s/%s] chunk_textbook failed: %s",
            slug, paper_id, exc, exc_info=True,
        )
        return []


def _chunk_textbook_impl(
    nb_dir: Path, slug: str, paper_id: str
) -> list[ChunkRecord]:
    parsed_html = _textbook_html_path(nb_dir, paper_id)
    if not parsed_html.exists():
        raise FileNotFoundError(
            f"parsed textbook HTML not found at {parsed_html}; "
            "run the m6 upload→parse pipeline first "
            "(POST a PDF to the textbook notebook + await parse_status=complete)."
        )

    html_bytes = parsed_html.read_bytes()
    soup = BeautifulSoup(html_bytes, "html.parser")

    body = soup.find("body")
    root: Tag = body if isinstance(body, Tag) else soup  # type: ignore[assignment]

    # Cleanup BEFORE assembly (mirrors chunk_paper F1): a downstream
    # raise leaves the dir empty rather than retaining stale JSONs.
    out_dir = _textbook_chunks_dir(nb_dir, paper_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.json"):
        stale.unlink()
    for stale in out_dir.glob("*.tmp"):
        stale.unlink()

    counter = [0]

    # Pass 1: theorem/proof pairs + unmatched theorem-like environments.
    # Reused verbatim — pairing is structural, not arXiv-specific. The
    # placeholder chunk_id ("arxiv:...:idxN") is overwritten in the SHA
    # pass below, so its prefix is irrelevant.
    theorem_chunks = _extract_chunks_from_container(root, paper_id, counter)

    # Pass 2: section-level prose chunks (handles ltx_chapter/ltx_section
    # via the shared _SECTION_DIV_CLASSES list).
    section_chunks = _extract_section_chunks(soup, paper_id, counter)

    all_chunks = theorem_chunks + section_chunks

    # Chapter-label index: map each chunk to its chapter breadcrumb.
    chapter_titles = _collect_chapter_titles(soup)
    if not chapter_titles:
        logger.debug(
            "[%s/%s] no ltx_chapter structure detected; "
            "chapter=None on all chunks (flat/article-class textbook)",
            slug, paper_id,
        )

    # Stamp textbook-specific fields + body_tokens on every chunk.
    for chunk in all_chunks:
        chunk.source_kind = "textbook"
        chunk.textbook_slug = slug
        chunk.parser_used = TEXTBOOK_PARSER_USED
        chunk.chunker_version = TEXTBOOK_CHUNKER_VERSION
        chunk.chapter = _chapter_for_chunk(chunk, chapter_titles)
        # page_start/page_end stay None: page metadata is lost in the m6
        # markdown→LaTeX→LaTeXML render. Correlating MinerU's
        # content_list.json page_idx back onto rendered chunks is a
        # future item (NOT m8 — not part of the e3 outcome); see
        # .claude/docs/textbook-preamble-decision.md §"related deferrals".
        chunk.page_start = None
        chunk.page_end = None
        chunk.body_tokens = tokenize_body(chunk.body_text)

    # SHA pass — replace the placeholder id with the content-addressable
    # textbook chunk-id. The dedup loop is LOAD-BEARING (m7 FM-4):
    # same body + empty preamble → same chunk_id → the second JSON would
    # overwrite the first on disk without it.
    #
    # PREAMBLE DECISION (textbook-ingest-m8, OQ-1): preamble_text is
    # PERMANENTLY "" for PDF-sourced textbooks, and preamble_ref stays
    # None. This is NOT a v0 placeholder — it is the correct steady
    # state. The arXiv preamble lever (04-parsing-and-chunking.md)
    # expands UNEXPANDED author macros (\newcommand/\def) from a .tex
    # source; the PDF→MinerU→LaTeXML path has none — MinerU emits math
    # already expanded at the PDF-render level (\mathbb{F}, never \F).
    # A future .tex-source textbook ingest path (separate epic) would
    # call ingest.preamble.extract_preamble; until such a path exists
    # there is nothing to inherit. Full rationale + evidence:
    # .claude/docs/textbook-preamble-decision.md.
    preamble_text = ""
    seen: dict[str, str] = {}  # chunk_id -> body_text fingerprint
    deduped_chunks: list[ChunkRecord] = []
    for chunk in all_chunks:
        chunk.chunk_id = _compute_textbook_chunk_id(
            slug, preamble_text, chunk.body_text
        )
        if chunk.chunk_id in seen:
            if seen[chunk.chunk_id] == chunk.body_text:
                logger.debug(
                    "[%s/%s] dropping duplicate chunk_id %s (kind=%s) — "
                    "body_text matches prior chunk",
                    slug, paper_id, chunk.chunk_id, chunk.kind,
                )
                continue
            raise ValueError(
                f"SHA-256 prefix collision: chunk_id {chunk.chunk_id} for "
                f"textbook {paper_id} maps to two distinct body_text values."
            )
        seen[chunk.chunk_id] = chunk.body_text
        deduped_chunks.append(chunk)
    all_chunks = deduped_chunks

    # Write per-chunk JSONs (filename = hash suffix; no colon-in-filename).
    for chunk in all_chunks:
        hash_suffix = chunk.chunk_id.rsplit(":", 1)[-1]
        out_path = out_dir / f"{hash_suffix}.json"
        out_path.write_text(
            json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    _write_textbook_manifest(out_dir / "chunk_manifest.json", paper_id, all_chunks)

    return all_chunks


# ---------------------------------------------------------------------------
# Manifest + failure logging
# ---------------------------------------------------------------------------


def _write_textbook_manifest(
    manifest_path: Path, paper_id: str, chunks: list[ChunkRecord]
) -> None:
    """Atomically write the per-textbook chunk manifest (BP1 byte-stable).

    Mirrors ``ingest.chunker._write_chunk_manifest`` but stamps the
    textbook chunker version. Atomic tmp + ``os.replace``.
    """
    manifest = {
        "chunker_version": TEXTBOOK_CHUNKER_VERSION,
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


def _log_chunk_failure(
    nb_dir: Path, paper_id: str, elapsed_s: float, message: str
) -> None:
    """Append a TSV failure row to the per-notebook chunk-failure log.

    Format: ``<paper_id>\\tfail\\t<elapsed_s>\\t<message>`` (mirrors the
    arXiv ``chunk.log``). Fields are sanitized to strip tab/newline.
    ``nb_dir`` is the already-resolved (symlink-checked) notebook dir.
    """
    log_path = _textbook_chunk_log_path(nb_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = (
        f"{_sanitize_log_field(paper_id)}\tfail\t{elapsed_s:.1f}\t"
        f"{_sanitize_log_field(message)}\n"
    )
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(row)
    except OSError:
        logger.warning(
            "[%s] could not write chunk-failure log at %s",
            paper_id, log_path,
        )


__all__ = [
    "TEXTBOOK_CHUNKER_VERSION",
    "TEXTBOOK_PARSER_USED",
    "chunk_textbook",
]
