"""Graph-query result types (E09_S03).

Carries the ``CitationNeighbor`` dataclass returned by
``server.graph_queries.cite_neighbors``. Lifted out of
``graph_queries.py`` so a future MCP-tool wrapper (E06_S04) can import
the type without pulling the full Kùzu read path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CitationNeighbor:
    """One neighbor of a chunk in the citation graph.

    The brief signature pinned ``chunk_id: str`` plus an AC saying
    "Papers in the graph but not in the chunked corpus return
    ``chunk_id=None``" — those are inconsistent. This dataclass
    follows the AC: ``chunk_id`` is ``str | None`` and downstream
    callers must check before passing the value to ``get_chunk``.
    See ``research-synthesis.md`` § 4 for the rationale.

    Fields:
        chunk_id: representative ``chunk_id`` for this paper — the
            first ``kind="stmt"`` chunk by best-effort priority, or
            ``None`` when no theorem-kind chunk exists for the paper.
        paper_id: arXiv ID of the neighbor paper.
        edge_kind: ``"cites"`` (outgoing query), ``"cited_by"``
            (incoming query), or ``"ref"`` (intra-paper ``\\ref{}``
            chain via ``source="intra-paper"`` edge).
        hop_distance: 1 = direct neighbor, 2 = neighbor's neighbor.
        source: raw value from the ``cites.source`` rel-table column;
            one of ``"openAlex"`` (camelCase, OpenAlex ingest),
            ``"inspire"`` (lowercase, INSPIRE-HEP ingest), or
            ``"intra-paper"`` (this milestone's intra-paper ``\\ref{}``
            ingest pass). The case asymmetry is documented drift —
            see F9 from the E09_S02 critique.
        confidence: ``cites.confidence`` from the rel table. 1.0 for
            curated sources (OpenAlex, INSPIRE, intra-paper).
    """

    chunk_id: str | None
    paper_id: str
    edge_kind: str
    hop_distance: int
    source: str
    confidence: float
