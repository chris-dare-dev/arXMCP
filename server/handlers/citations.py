"""``cite_neighbors`` handler — wired to the live citation-graph
library (verification-feedback-m1).

Replaces the v1 empty stub. This handler is the MCP-tool boundary
over :func:`server.graph_queries.cite_neighbors` — the Kùzu
citation-graph read path shipped in E09_S03.

**F2 path-validation contract (E09_S03 critique F2, HIGH).** The Kùzu
and LanceDB paths passed to the library are derived from
:class:`server.config.Config` via :func:`server.tools.get_resources` —
NEVER from agent-supplied JSON arguments. The agent controls only
``chunk_id``, ``direction``, ``depth``, and ``limit``. This closes the
contract the library docstring defers to "the E06_S04 / E09_S04
tool-input boundary".

**No caching.** ``cite_neighbors`` results are NOT cached: the handler
calls the live Kùzu graph on every invocation, so a citation-graph
re-ingest can never serve a stale neighbor list. A ``graph_version``-
keyed cache is an optimization deferred to a future milestone — see
``.claude/notes/milestones/verification-feedback-m1/research-synthesis.md``
§ 2 for the scope decision (the Phase-3 challenger's sanctioned
"exclude from caching" option).

**Graceful degradation.** When the citation graph has not been
ingested (a seed-stage corpus), the handler returns an empty
neighborhood with ``graph_status="absent"`` rather than letting a Kùzu
binder error surface as a 5xx.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any, Literal

from pydantic import Field

from ingest.identifiers import is_valid_chunk_id
from server.graph_queries import cite_neighbors
from server.tools import cap_result_list, envelope, get_resources


def _cap(payload: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    """E13_S04b — apply the 256 KB result byte cap to the
    ``neighbors[]`` aggregate.

    Now that the handler is wired (verification-feedback-m1), a
    citation-rich result — up to ``limit`` neighbors — can genuinely
    push past the cap, so this is no longer a no-op.

    Uses :func:`server.tools.cap_result_list` with
    ``list_key="neighbors"`` so the lowest-priority trailing
    neighbors are trimmed until the payload fits; ``body_truncated=True``
    is set so consumers detect the truncation.

    Passes the INPUT ``chunk_id`` because it IS the parent context the
    resource-link belongs to: the cap-overflow surface for a
    cite_neighbors response is the neighborhood of the queried chunk,
    so a downstream agent receiving a truncated response knows which
    parent chunk's neighborhood was elided.
    """
    structured, _blocks = cap_result_list(
        payload, list_key="neighbors", chunk_id=chunk_id
    )
    return structured


async def handle_cite_neighbors(
    chunk_id: Annotated[str, Field(min_length=1, description="Source chunk_id")],
    direction: Annotated[
        Literal["cites", "cited_by", "depends_on"],
        Field(description="Graph traversal direction"),
    ] = "cites",
    depth: Annotated[int, Field(ge=1, le=3, description="Hop count")] = 1,
    limit: Annotated[int, Field(ge=1, le=100, description="Max neighbors returned")] = 30,
) -> dict[str, Any]:
    # E13_S01 D3 — Threat-1 (path traversal) coverage. ``chunk_id``
    # flows into the citation-graph query layer; validate the format
    # BEFORE any downstream use so an adversarial input never reaches
    # the graph layer. This check runs FIRST — before get_resources()
    # — so the validator fires regardless of resource state (the
    # forward-compat contract pinned by
    # tests/security/test_path_traversal.py).
    if not is_valid_chunk_id(chunk_id):
        raise ValueError(
            f"chunk_id does not match the expected format "
            f"arxiv:<paper_id>:<16-hex>; got {chunk_id!r}"
        )

    # F2 path-validation contract: the Kùzu and LanceDB paths come
    # from Config via the Resources singleton — never from the agent's
    # JSON arguments. The agent controls only chunk_id/direction/
    # depth/limit (all validated above / by Pydantic).
    config = get_resources().config
    kuzu_path = config.kuzu_path

    if not kuzu_path.exists():
        # Citation graph not ingested (seed-stage corpus). Return an
        # empty neighborhood rather than letting kuzu.Database create
        # an empty DB and the query fail on a missing ``papers`` table.
        neighbors: list[dict[str, Any]] = []
        graph_status = "absent"
    else:
        results = await cite_neighbors(
            chunk_id,
            depth=depth,
            direction=direction,
            max_results=limit,
            kuzudb_path=str(kuzu_path),
            lancedb_path=str(config.lancedb_path),
        )
        # CitationNeighbor is a frozen dataclass — serialize each to a
        # plain dict for the JSON envelope. The library's
        # (hop_distance ASC, paper_id ASC) ordering is preserved:
        # envelope()'s _sort_dict sorts dict keys, not list order.
        neighbors = [dataclasses.asdict(n) for n in results]
        graph_status = "present"

    return envelope(_cap(
        {
            "chunk_id": chunk_id,
            "depth": depth,
            "direction": direction,
            "graph_status": graph_status,
            "limit": limit,
            "neighbors": neighbors,
        },
        chunk_id,
    ))
