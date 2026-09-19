"""cite_neighbors channel for the exploration pipeline (WS-E v0).

Probes the citation graph around operator-supplied anchor papers via
the wired ``server.graph_queries.cite_neighbors`` library (E09_S03;
finding 211 R-A: the library AND the MCP handler are live — this
module calls the library directly, per the proof-chain-workflow
pattern).

Degradation semantics mirror ``server/handlers/citations.py``
verbatim:

- ``"absent"``      — the Kùzu DB path does not exist (the live state
                      of the active Windows workstation, finding 211
                      R-A item 1). Empty neighbor set; the pipeline
                      proceeds on the Atom + open-problem channels.
- ``"unavailable"`` — path exists but is not a queryable graph
                      (RuntimeError from the Kùzu layer).
- ``"present"``     — neighbors returned.
- ``"skipped"``     — no anchors were supplied (channel not run).

Recency discipline (AC-E.2): graph neighbors carry no submission date
(``get_paper`` metadata is NULL — finding 01 §2.a.1), so a
neighbor is admitted as a *proposed paper* only when its new-style
arXiv id's YYMM month lies ENTIRELY inside the scan window
(:func:`tools.exploration.windowing.paper_id_month`). Neighbors that
also arrived through the Atom channel instead become corroborating
provenance on the Atom hit.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from ingest.identifiers import is_valid_paper_id

_SYNTH_CHUNK_SUFFIX = "0" * 16

GRAPH_PRESENT = "present"
GRAPH_ABSENT = "absent"
GRAPH_UNAVAILABLE = "unavailable"
GRAPH_SKIPPED = "skipped"


@dataclass(frozen=True)
class GraphNeighbor:
    """One citation-graph neighbor of an anchor paper."""

    paper_id: str
    anchor: str
    direction: str
    hop_distance: int


@dataclass
class GraphChannelResult:
    """Outcome of the cite_neighbors probe (status + neighbors)."""

    graph_status: str
    anchors: list[str] = field(default_factory=list)
    neighbors: list[GraphNeighbor] = field(default_factory=list)

    def provenance_for(self, paper_id: str) -> list[str]:
        """AC-E.4 provenance lines for ``paper_id`` (empty when unseen)."""
        return [
            (
                f"cite_neighbors {n.direction} hop-{n.hop_distance} "
                f"from anchor {n.anchor}"
            )
            for n in self.neighbors
            if n.paper_id == paper_id
        ]


def _synthetic_chunk_id(paper_id: str) -> str:
    """A structurally valid chunk_id for an anchor paper.

    ``cite_neighbors`` takes a chunk_id and derives the paper_id via
    ``ingest.identifiers.paper_id_from_chunk_id``; the 16-hex suffix
    is never dereferenced for the SOURCE paper, so a zero suffix is a
    valid probe handle.
    """
    return f"arxiv:{paper_id}:{_SYNTH_CHUNK_SUFFIX}"


def probe_graph(
    anchors: list[str],
    kuzudb_path: Path,
    *,
    depth: int = 1,
    directions: tuple[str, ...] = ("cites", "cited_by"),
    max_results_per_call: int = 50,
) -> GraphChannelResult:
    """Probe the citation graph around ``anchors``.

    Validates every anchor id up front (``if … raise``; Threat-1
    discipline — anchor ids reach the graph query layer). Returns a
    :class:`GraphChannelResult`; never raises for graph-availability
    failures (they degrade to ``absent`` / ``unavailable`` exactly like
    the MCP handler).
    """
    if not anchors:
        return GraphChannelResult(graph_status=GRAPH_SKIPPED)

    for anchor in anchors:
        if not is_valid_paper_id(anchor):
            raise ValueError(f"invalid anchor paper_id: {anchor!r}")

    if not kuzudb_path.exists():
        return GraphChannelResult(graph_status=GRAPH_ABSENT, anchors=list(anchors))

    # Import here so the (heavy) kuzu dependency loads only when a graph
    # probe actually runs — the absent/skipped paths stay light.
    from server.graph_queries import cite_neighbors

    async def _run() -> list[GraphNeighbor]:
        found: list[GraphNeighbor] = []
        for anchor in anchors:
            for direction in directions:
                results = await cite_neighbors(
                    _synthetic_chunk_id(anchor),
                    depth=depth,
                    direction=direction,  # type: ignore[arg-type]
                    max_results=max_results_per_call,
                    kuzudb_path=str(kuzudb_path),
                    lancedb_path=None,
                )
                found.extend(
                    GraphNeighbor(
                        paper_id=r.paper_id,
                        anchor=anchor,
                        direction=direction,
                        hop_distance=r.hop_distance,
                    )
                    for r in results
                )
        return found

    try:
        neighbors = asyncio.run(_run())
    except RuntimeError:
        # Path exists but is not a queryable graph (stray dir, corrupt /
        # half-ingested DB) — the handler's "unavailable" class.
        return GraphChannelResult(graph_status=GRAPH_UNAVAILABLE, anchors=list(anchors))

    return GraphChannelResult(
        graph_status=GRAPH_PRESENT,
        anchors=list(anchors),
        neighbors=neighbors,
    )


__all__ = [
    "GRAPH_ABSENT",
    "GRAPH_PRESENT",
    "GRAPH_SKIPPED",
    "GRAPH_UNAVAILABLE",
    "GraphChannelResult",
    "GraphNeighbor",
    "probe_graph",
]
