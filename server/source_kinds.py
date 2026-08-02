"""Per-tool source-kind admission — chris-dare-dev/arXMCP#209.

``search_papers`` emits ``textbook:<slug>`` paper_ids. ``get_paper``,
``get_definitions`` and ``find_lemma_by_name`` gated on the arXiv-only
validator and answered one with::

    ValueError: paper_id 'textbook:foo-bar' does not match the arXiv id format

The server rejecting an identifier it emitted itself, on the canonical
documented workflow, and calling it malformed. Two distinct questions had
been collapsed into one boolean:

* **Is this a well-formed paper_id?** No → ``invalid-input``. Still a raise.
* **Is this a source kind I can serve?** No → ``unsupported-by-provider``,
  an *epistemic* outcome under CLAUDE.md §4.9 rule 2, which is explicit that
  abstention is a first-class tested success state and must stay distinct
  from operational status. A tool that cannot serve a kind has not been
  handed bad input; it has been asked a question outside its domain.

Each handler declares the kinds it serves and calls
:func:`admit_paper_id`. The declaration is per-handler on purpose: source
type #2 half-landed once already because the knowledge was spread across
six places with no owner, and a single global "textbook is supported now"
switch would repeat that by asserting readiness on behalf of tools whose
backing store may not have it.

Today all three declare both kinds — their indices are built from the
chunks table with no source-kind filter, so the rows are there and the
validator gate was the only thing rejecting them. The abstention path is
therefore not dead code kept for symmetry: it is the contract the *next*
source kind meets, and it is what stops that one from re-landing as a
``ValueError`` at the tool boundary.
"""

from __future__ import annotations

from ingest.identifiers import (
    SOURCE_KIND_ARXIV,
    SOURCE_KIND_TEXTBOOK,
    paper_id_source_kind,
)

#: The epistemic outcome for "well-formed, but not a kind this tool serves".
#: Named exactly as CLAUDE.md §4.9 rule 2 and
#: :mod:`server.proof_linkage` spell it, so one grep finds every site.
UNSUPPORTED_BY_PROVIDER: str = "unsupported-by-provider"

#: Every source kind the corpus can hold today. A handler that serves all
#: of them uses this; one that serves a subset spells the subset out.
ALL_SOURCE_KINDS: frozenset[str] = frozenset(
    {SOURCE_KIND_ARXIV, SOURCE_KIND_TEXTBOOK}
)


class UnsupportedSourceKind(Exception):
    """Raised by :func:`admit_paper_id` for a well-formed id of a kind the
    calling tool does not serve.

    Deliberately NOT a ``ValueError``. Handlers already raise ``ValueError``
    for malformed input and callers key on that; reusing it would rebuild
    the exact conflation #209 is about, one layer down.
    """

    def __init__(self, paper_id: str, source_kind: str, supported: frozenset[str]):
        self.paper_id = paper_id
        self.source_kind = source_kind
        self.supported = supported
        super().__init__(
            f"paper_id {paper_id!r} has source_kind {source_kind!r}, which "
            f"this tool does not serve (serves: {sorted(supported)})"
        )


def admit_paper_id(
    paper_id: str,
    supported: frozenset[str] = ALL_SOURCE_KINDS,
    *,
    field: str = "paper_id",
) -> str:
    """Return ``paper_id``'s source kind, or refuse it — with the refusals
    kept apart.

    Raises :class:`ValueError` when ``paper_id`` is not a well-formed
    identifier in ANY known form (``invalid-input``), and
    :class:`UnsupportedSourceKind` when it is well-formed but names a kind
    outside ``supported``.

    The union check is the important half: a ``textbook:`` id must stop
    being reported as malformed even by a tool that goes on to abstain on
    it, because "I cannot read that" and "that is not an identifier" send
    a calling agent down completely different paths.
    """
    kind = paper_id_source_kind(paper_id)
    if kind is None:
        raise ValueError(
            f"{field} {paper_id!r} is not a well-formed paper_id "
            f"(expected arXiv new-style YYMM.NNNNN[vN], arXiv old-style "
            f"subject/NNNNNNN[vN], or textbook:<slug>)"
        )
    if kind not in supported:
        raise UnsupportedSourceKind(paper_id, kind, supported)
    return kind


def unsupported_outcome(exc: UnsupportedSourceKind) -> dict[str, str]:
    """The abstention fields to merge into a tool's normal empty envelope.

    Kept as a fragment rather than a whole response so each tool keeps its
    own shape — an agent parsing ``definitions``/``matches``/``title`` still
    finds those keys, empty, alongside a positive statement of why.
    """
    return {
        "outcome": UNSUPPORTED_BY_PROVIDER,
        "unsupported_source_kind": exc.source_kind,
    }


__all__ = [
    "ALL_SOURCE_KINDS",
    "UNSUPPORTED_BY_PROVIDER",
    "UnsupportedSourceKind",
    "admit_paper_id",
    "unsupported_outcome",
]
