"""``find_equation`` handler — graceful dense-only fallback (E06_S03).

Per the brief's risk note, ``find_equation`` is "backed by E10_S03
when available; graceful fallback to dense-only before that epic
lands." The ``embedding_eq`` column on the chunks table is always
NULL today (``ingest/schema.py`` line 92-99 — populated by
E10_S03 when it ships).

v1 fallback: embed the LaTeX query as if it were a search query
and search the ``embedding_stmt`` column. The agent gets
chunks-with-similar-stmt-text, NOT chunks-with-similar-equations.
The ``retrieval_mode`` field documents the limitation.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from server.query_encoder import encode_query
from server.tools import envelope, get_resources

MAX_K = 50


async def handle_find_equation(
    latex_or_mathml: Annotated[
        str,
        Field(min_length=1, max_length=4000, description="LaTeX or MathML equation"),
    ],
    k: Annotated[int, Field(ge=1, le=MAX_K, description="Top-k cutoff")] = 10,
) -> dict[str, Any]:
    r = get_resources()
    async with r.embed_semaphore:
        query_vec = await encode_query(latex_or_mathml)

    arrow = (
        r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")
        .limit(k)
        .to_arrow()
    )

    rows = []
    cids = arrow.column("chunk_id").to_pylist()
    paper_ids = arrow.column("paper_id").to_pylist()
    distances = arrow.column("_distance").to_pylist()
    for cid, pid, dist in zip(cids, paper_ids, distances, strict=True):
        if cid is None:
            continue
        rows.append({"chunk_id": cid, "paper_id": pid, "score": _distance_to_score(dist)})

    rows.sort(key=lambda r: (-r["score"], r["chunk_id"]))

    return envelope(
        {
            "results": rows[:k],
            "retrieval_mode": "dense_only_stmt_fallback",
        }
    )


def _distance_to_score(dist: float | None) -> float:
    if dist is None:
        return 0.0
    return max(0.0, 1.0 - float(dist) / 2.0)
