"""ChunkRecord dataclass for the theorem-aware structural chunker (E02_S01).

Field history:
- ``preamble_ref``: E02_S02 (per-paper preamble extraction)
- ``body_tokens``:  E02_S03 (BM25 tokenization)
- ``chunk_id``:     E02_S04 (content-addressable SHA-256 hash)
- ``CHUNKER_VERSION`` constant: E02_S04 (single source of truth for the
  version string; bumping it signals the LanceDB MVCC writer (E04_S02) and
  the re-embedder (E03_S02) that existing rows are stale).

CHUNKER_VERSION lives here (not in ``ingest.chunker``) so the dataclass
default can reference it without creating a circular import:
``ingest.chunker`` already imports ``ChunkRecord`` from this module; the
inverse import would close a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Single source of truth for the chunker version string. Bump this
# constant in lockstep with any change to chunking strategy
# (theorem/proof detection, windowing, section extraction). The value
# flows into every ChunkRecord's ``chunker_version`` field via the
# dataclass default below, into the per-paper ``chunk_manifest.json``
# (written by ``ingest.chunker``), and is what E04_S02's MVCC writer
# uses to detect stale rows.
#
# **Schema-migration constraint (E11_S03).** The CANONICAL-BYTES
# function ``ingest.chunker._compute_chunk_id`` —
# ``sha256(preamble_text + NFC(body_text))[:16]`` — must remain
# byte-stable across CHUNKER_VERSION bumps. The partial re-embed
# driver (``ingest/re_embed.py``) depends on the invariant that
# byte-identical canonical chunk content keeps the same chunk_id
# across versions; this is what makes the "copy unchanged
# embeddings" path safe.
#
# If you ever change ``_compute_chunk_id`` itself (e.g. swap NFC
# for NFKC, change the prefix-stripping rule, alter the hash
# truncation length), every chunk_id rotates even for byte-
# identical content. That is a SCHEMA migration, NOT a chunker_version
# bump: every paper must be re-embedded from scratch and the
# `tests/test_re_embed.py::TestChunkerVersionFreeze` regression
# guard must be updated in the same PR.
CHUNKER_VERSION = "v1.1"


@dataclass
class ChunkRecord:
    """One logical chunk emitted by the structural chunker.

    Attributes
    ----------
    chunk_id:
        Content-addressable identifier
        ``arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>``
        for arXiv chunks (landed in E02_S04), or
        ``textbook:<slug>:<sha256(...)[:16]>`` for textbook chunks
        (textbook-ingest-m1 + m2). The 16-hex-char prefix is stable
        across re-runs of the same paper and changes deterministically
        when either the preamble or the body content changes.
    paper_id:
        Canonical arXiv ID without version suffix (``2307.01156``)
        or textbook paper_id (``textbook:shimura-varieties``).
    kind:
        Chunk type.  Matched theorem+proof pairs yield ``"stmt"`` and
        ``"proof"`` chunks.  Unmatched environments use the LaTeXML subclass
        name (``"lemma"``, ``"corollary"``, ``"definition"``, ``"remark"``,
        ``"example"``, etc.).  Stand-alone prose sections emit ``"section"``.
    section_path:
        Ordered list of section titles from outermost to innermost, e.g.
        ``["3. Main results", "3.2 The flat case"]``.  Empty list when the
        chunk is in the document preamble or top-level prose.
    theorem_name:
        Display name extracted from the theorem heading, e.g.
        ``"Riemann–Roch"`` from ``Theorem 3.1 (Riemann–Roch)``.  ``None``
        for non-theorem environments and when no parenthetical name is
        present.
    theorem_label:
        User-supplied ``\\label{}`` key embedded in the LaTeXML ``id``
        attribute, or ``None`` when LaTeXML auto-generated the id.
    body_text:
        Plain-text extraction of the environment body (no HTML tags).
        Statement chunks contain the theorem statement text; proof chunks
        contain a window of the proof body (≤448 BGE-M3 tokens so that a
        64-token statement header can be prepended at embedding time).
        NOTE: stored bytes are NOT NFC-normalised — the chunk_id hash
        (E02_S04) applies NFC for cross-host stability, but the stored
        body_text preserves the parser's exact output. Downstream
        consumers that hash body_text for their own cache keys must
        apply ``unicodedata.normalize("NFC", ...)`` to match the
        chunk_id discipline (F3 closure).
    body_tokens:
        Whitespace-joined math-aware token stream produced by E02_S03's
        ``ingest.tokenizer.tokenize_body``. The string the BM25 index
        (E04_S04) splits at query time. ``None`` only when the chunker
        emitted before E02_S03 wired this field in (legacy artifacts).
    preamble_ref:
        First 16 hex chars of ``SHA-256(preamble_text)`` for the paper's
        per-paper preamble (E02_S02). The embedder uses this to look up
        the preamble text and prepend it during embedding-input
        construction. ``None`` when preamble extraction failed for the
        paper (F3 fallback in E02_S02).
    chunker_version:
        Stable version string for the chunking strategy. Defaults to
        :data:`CHUNKER_VERSION` (defined above). Bump the constant when
        chunking changes; downstream re-embedding (E03_S02) and LanceDB
        MVCC rotation (E04_S02) consume this field to detect stale rows.
    truncated:
        ``True`` when the chunker had to truncate ``body_text`` to fit
        the BGE-M3 token budget. NOT persisted to LanceDB — runtime
        signal only, surfaced to consumers via a different path.

    Textbook-specific fields (textbook-ingest-m2). All optional; the
    arXiv chunking path leaves them at their defaults, and the schema
    enforces ``source_kind="arxiv"`` + ``license="arxiv-license"`` as
    the arXiv-corpus defaults.

    source_kind:
        ``"arxiv"`` (default) or ``"textbook"``. Discriminates the
        chunk's origin corpus. Mirrored on the LanceDB ``source_kind``
        column for downstream filtering (cross-corpus search filter
        lands in m4 / textbook-ingest-e4).
    license:
        Free-text license token. Default ``"arxiv-license"`` for
        arXiv chunks; textbook chunks carry the textbook's license
        (e.g. ``"GFDL"`` for Stacks Project, ``"author-distributed"``
        for lecture notes, etc.). Documentary at m2; enforcement of
        ``truncated_for_license`` flag lands with e5.
    chapter:
        Textbook chapter name (``"Chapter 3: Schemes"``) or ``None``
        for arXiv. Surfaced in the result envelope for textbook
        chunks in m4.
    page_start, page_end:
        Inclusive page range for textbook chunks. ``None`` for arXiv.
        Surfaced to the operator for original-PDF verification.
    textbook_slug:
        Notebook slug (``"shimura-varieties"``) for textbook chunks;
        redundant with ``paper_id = "textbook:<slug>"`` but enables
        a scalar-index filter without string-splitting at query time.
        ``None`` for arXiv.
    parser_used:
        Per-chunk parser provenance. Enum domain:
        ``{"ar5iv", "latexml", "mineru+latexml"}`` plus ``None`` for
        unknown / failure. Promoted from the in-memory ``PaperOutcome``
        dataclass to a persisted chunks-table column in m2 so chunk-
        grained re-parse decisions are possible.
    """

    chunk_id: str
    paper_id: str
    kind: str
    section_path: list[str]
    theorem_name: str | None
    theorem_label: str | None
    body_text: str
    # E02_S03 populates this with a whitespace-joined string produced by
    # `ingest.tokenizer.tokenize_body`. The annotation is `str | None`
    # (NOT `list[str] | None`) to match the LanceDB schema's `string`
    # column type — E04_S04's BM25 indexer does `body_tokens.split()`.
    body_tokens: str | None = field(default=None)
    preamble_ref: str | None = field(default=None)
    chunker_version: str = field(default=CHUNKER_VERSION)
    # Closes F5 (HIGH): surface silent truncation to downstream consumers
    # rather than letting them mistake a sliced statement for a complete one.
    # ``True`` when the chunker had to truncate ``body_text`` to fit the
    # 512-token (stmt) or 448-token (proof window) BGE-M3 budget.
    truncated: bool = field(default=False)
    # ---- textbook-ingest-m2 fields ----
    # Discriminator (default "arxiv"). The LanceDB column is nullable
    # to accommodate the in-place migration of existing rows, but new
    # writes always populate this field explicitly.
    source_kind: str = field(default="arxiv")
    # License token. arXiv default; textbook chunks override.
    license: str = field(default="arxiv-license")
    # Textbook-only metadata; all None for arXiv chunks.
    chapter: str | None = field(default=None)
    page_start: int | None = field(default=None)
    page_end: int | None = field(default=None)
    textbook_slug: str | None = field(default=None)
    # Per-chunk parser provenance. None until the chunker / driver
    # populates it; m2 ships the column, m3+ wires the population path.
    parser_used: str | None = field(default=None)

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict with keys in sorted order."""
        return {
            "body_text": self.body_text,
            "body_tokens": self.body_tokens,
            "chapter": self.chapter,
            "chunk_id": self.chunk_id,
            "chunker_version": self.chunker_version,
            "kind": self.kind,
            "license": self.license,
            "page_end": self.page_end,
            "page_start": self.page_start,
            "paper_id": self.paper_id,
            "parser_used": self.parser_used,
            "preamble_ref": self.preamble_ref,
            "section_path": self.section_path,
            "source_kind": self.source_kind,
            "textbook_slug": self.textbook_slug,
            "theorem_label": self.theorem_label,
            "theorem_name": self.theorem_name,
            "truncated": self.truncated,
        }
