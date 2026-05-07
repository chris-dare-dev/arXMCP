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
CHUNKER_VERSION = "v1.0"


@dataclass
class ChunkRecord:
    """One logical chunk emitted by the structural chunker.

    Attributes
    ----------
    chunk_id:
        Monotonic placeholder ``arxiv:<paper_id>:idx<N>`` until E02_S04
        replaces it with a content-addressable SHA-256 prefix.
    paper_id:
        Canonical arXiv ID without version suffix, e.g. ``2307.01156``.
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
    body_tokens:
        Reserved for E02_S03 (BM25 token list).  Written as ``None`` by
        this milestone.
    preamble_ref:
        Reserved for E02_S02 (reference to the per-paper preamble chunk).
        Written as ``None`` by this milestone.
    chunker_version:
        Monotonic version string.  Bump when chunking strategy changes so
        that downstream re-embedding and index rotation can be triggered.
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

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict with keys in sorted order."""
        return {
            "body_text": self.body_text,
            "body_tokens": self.body_tokens,
            "chunk_id": self.chunk_id,
            "chunker_version": self.chunker_version,
            "kind": self.kind,
            "paper_id": self.paper_id,
            "preamble_ref": self.preamble_ref,
            "section_path": self.section_path,
            "theorem_label": self.theorem_label,
            "theorem_name": self.theorem_name,
            "truncated": self.truncated,
        }
