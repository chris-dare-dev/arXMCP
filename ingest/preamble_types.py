"""PreambleDoc dataclass for the per-paper preamble extractor (E02_S02).

The preamble extractor reads a paper's root .tex and serializes its macro
definitions to ``var/arxmcp/corpus/preamble/<paper_id>/preamble.json``. The
embedder (E03_S01) reads this back via the ``preamble_hash`` field, which
matches the ``preamble_ref`` stored on every chunk emitted by ``chunker.py``.

The serialised JSON is sorted-keys, no timestamps — supporting BP1
byte-identical caching per ``08-security-observability-ops.md``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PreambleDoc:
    """One paper's preamble metadata.

    Attributes
    ----------
    paper_id:
        Canonical arXiv ID without version suffix, e.g. ``2307.01156``.
    source_hash:
        Full ``SHA-256`` hex digest of the root .tex source bytes. Used by
        the extractor to short-circuit on unchanged source (idempotency).
    macros:
        Sorted, deduplicated list of normalised macro-definition strings.
        Each entry is a single-line whitespace-collapsed form of the
        original multi-line macro definition (e.g.
        ``"\\newcommand{\\R}{\\mathbb{R}}"``).
    preamble_text:
        Deterministic text fed to the embedder as the prefix of every
        chunk's embedding-input view. Computed as
        ``"\\n".join(self.macros)``.
    preamble_hash:
        First 16 hex chars of ``SHA-256(preamble_text)``. This is what
        each emitted ``ChunkRecord.preamble_ref`` carries so the embedder
        can verify the lookup.
    """

    paper_id: str
    source_hash: str
    macros: list[str]
    preamble_text: str
    preamble_hash: str

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict with keys in sorted order."""
        return {
            "macros": list(self.macros),
            "paper_id": self.paper_id,
            "preamble_hash": self.preamble_hash,
            "preamble_text": self.preamble_text,
            "source_hash": self.source_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PreambleDoc:
        """Inverse of ``to_dict``: load a previously serialised PreambleDoc.

        Raises ``TypeError`` if ``macros`` is not a list of strings — without
        this guard, ``list(data["macros"])`` would silently iterate a
        corrupt-cache string character-by-character and produce one-letter
        "macros". Closes F2 from the E02_S02 critique.
        """
        macros_raw = data["macros"]
        if not isinstance(macros_raw, list):
            raise TypeError(
                f"PreambleDoc.macros must be a list, got {type(macros_raw).__name__}"
            )
        if not all(isinstance(m, str) for m in macros_raw):
            raise TypeError("PreambleDoc.macros must contain only str entries")
        return cls(
            paper_id=data["paper_id"],
            source_hash=data["source_hash"],
            macros=list(macros_raw),
            preamble_text=data["preamble_text"],
            preamble_hash=data["preamble_hash"],
        )
