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

**Graceful degradation.** ``graph_status`` reports the citation graph's
state: ``"absent"`` when the Kùzu DB path does not exist (seed-stage
corpus, graph not ingested), ``"unavailable"`` when the path exists but
is not a queryable Kùzu graph (a stray directory, an empty / corrupt /
half-ingested DB — Kùzu raises ``RuntimeError`` for these), and
``"present"`` when the graph was queried successfully. In the first two
cases the handler returns an empty ``neighbors`` list rather than
surfacing a 5xx; the ``"unavailable"`` case is logged at WARNING so the
operator failure is observable, not silently masked.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Annotated, Any, Literal

from pydantic import Field

from ingest.identifiers import is_valid_chunk_id
from server.graph_queries import cite_neighbors
from server.metadata_enrich import enrich_rows_with_titles
from server.tools import cap_result_list, envelope, get_resources

logger = logging.getLogger(__name__)


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
    depth: Annotated[int, Field(ge=1, le=2, description="Hop count (1 or 2)")] = 2,
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

    neighbors: list[dict[str, Any]] = []
    if not kuzu_path.exists():
        # Citation graph not ingested (seed-stage corpus). Return an
        # empty neighborhood rather than letting the query layer fail.
        graph_status = "absent"
    else:
        try:
            results = await cite_neighbors(
                chunk_id,
                depth=depth,
                direction=direction,
                max_results=limit,
                kuzudb_path=str(kuzu_path),
                lancedb_path=str(config.lancedb_path),
            )
        except RuntimeError as exc:
            # The Kùzu path exists but is not a queryable graph — a
            # stray directory, or an empty / half-ingested / corrupt
            # DB. Kùzu surfaces all of these as RuntimeError. (Bad
            # chunk_id / direction / depth are pre-validated above and
            # by Pydantic, so cite_neighbors cannot raise RuntimeError
            # for an input error here — a RuntimeError is unambiguously
            # a graph-availability failure.) Degrade to "unavailable"
            # instead of a 5xx; log at WARNING so the operator failure
            # is observable rather than silently masked.
            logger.warning(
                "cite_neighbors: Kùzu graph at %s is not queryable: %s",
                kuzu_path,
                exc,
            )
            graph_status = "unavailable"
        else:
            # CitationNeighbor is a frozen dataclass — serialize each to
            # a plain dict for the JSON envelope. The library's
            # (hop_distance ASC, paper_id ASC) ordering is preserved:
            # envelope()'s _sort_dict sorts dict keys, not list order.
            neighbors = [dataclasses.asdict(n) for n in results]
            # #84: join paper title/year onto each neighbor row from the
            # shared PaperMetadataStore (cite_neighbors has no notebook
            # routing, so the shared store is the correct source).
            # Null-safe: absent store / un-backfilled paper → title:null.
            await enrich_rows_with_titles(
                getattr(get_resources(), "paper_metadata_store", None), neighbors
            )
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
