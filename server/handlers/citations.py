"""``cite_neighbors`` handler — empty stub at v1.

The Kùzu citation graph (E09 — Sonnet B's epic) is not built; the
intra-paper theorem dependency parser (for ``direction=
"depends_on"``) is also not built. There is no source of citation
edges anywhere in the project today.

v1 returns ``{neighbors: [], infrastructure_status: "deferred",
note: "..."}`` for every direction. The schema is locked here so
E09 can populate the result without an API change.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from server.tools import envelope


async def handle_cite_neighbors(
    chunk_id: Annotated[str, Field(min_length=1, description="Source chunk_id")],
    direction: Annotated[
        Literal["citers", "cited", "co_cited", "co_citing", "depends_on"],
        Field(description="Graph traversal direction"),
    ] = "cited",
    depth: Annotated[int, Field(ge=1, le=3, description="Hop count")] = 1,
    limit: Annotated[int, Field(ge=1, le=100, description="Max neighbors returned")] = 30,
) -> dict[str, Any]:
    return envelope(
        {
            "chunk_id": chunk_id,
            "depth": depth,
            "direction": direction,
            "infrastructure_status": "deferred",
            "limit": limit,
            "neighbors": [],
            "note": (
                "citation graph (E09) and intra-paper theorem "
                "dependency parser not yet built; this tool returns "
                "an empty stub at v1. The schema is stable across "
                "the future swap."
            ),
        }
    )
