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

from ingest.identifiers import is_valid_chunk_id
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
    # E13_S01 D3 — Threat-1 (path traversal) coverage. The handler
    # is a v1 stub but ``chunk_id`` flows into the response
    # envelope and (once E09 wiring lands) will be the key into
    # the Kùzu citation graph. Validate the format BEFORE any
    # downstream use so an adversarial input never reaches the
    # graph layer. Mirrors the ``get_chunk`` precedent.
    # See ``.claude/docs/security-threat-1-audit.md`` for the
    # full audit table and the deferred migration plan
    # (Pydantic ``pattern=`` Field migration + ``max_length``
    # caps + ``McpError(INVALID_PARAMS)`` wire-level wrap —
    # all Tier-6+ work tied to the same byte-stability re-pin).
    if not is_valid_chunk_id(chunk_id):
        raise ValueError(
            f"chunk_id does not match the expected format "
            f"arxiv:<paper_id>:<16-hex>; got {chunk_id!r}"
        )

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
