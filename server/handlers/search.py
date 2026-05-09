"""``search_papers`` handler — dense-only ANN over BGE-M3 embeddings.

v1 ships dense-only retrieval over the ``embedding_stmt`` column
of the chunks table. The hybrid BM25 + RRF + reranker pipeline
lands in E07 (Sonnet B); the wire-level tool contract does not
change when E07 ships — only the internal retrieval mode.

Aggregation per ``level``:
- ``level="theorem"`` (default): one row per chunk.
- ``level="section"``: dedup by ``(paper_id, section_path[0])``,
  keep the highest-score chunk per section.
- ``level="paper"``: dedup by ``paper_id``, keep the highest-score
  chunk per paper.

Sort: ``(score_desc, chunk_id_asc)`` per the determinism contract.
``snippet`` is ≤150 chars taken from the start of ``body_text``
(synthesis D2 of E06_S04 will lock the truncation rule but the
shape is stable here).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from pydantic import Field

from server.query_encoder import encode_query
from server.tools import envelope, get_resources

#: Hard upper bound on per-tool ``k``. Mirrors the design note's
#: per-tool argument validation rule (k in [1, 50]).
MAX_K = 50

#: Snippet truncation length. E06_S04 will formalize this in a
#: dedicated schema file; the value is pinned here for the v1
#: result shape.
SNIPPET_MAX_CHARS = 150


async def handle_search_papers(
    query: Annotated[
        str, Field(min_length=1, max_length=2000, description="Natural-language query")
    ],
    level: Annotated[
        Literal["paper", "section", "theorem"],
        Field(description="Aggregation level for results"),
    ] = "theorem",
    k: Annotated[int, Field(ge=1, le=MAX_K, description="Top-k cutoff")] = 10,
) -> dict[str, Any]:
    """Search the corpus and return ranked chunk results.

    ``filters`` and ``cursor`` are accepted in the schema but
    ignored at v1 (no filterable columns yet; pagination deferred
    to E07_S04). The ``filter_warnings`` field in the result
    documents this until full support lands.
    """
    r = get_resources()
    # Encode query (singleflight + semaphore — two-tier concurrency).
    async with r.embed_semaphore:
        query_vec = await encode_query(query)

    # Dense ANN over embedding_stmt only. embedding_proof is for
    # proof bodies; mixing without RRF would produce inconsistent
    # rankings (E07 is the right venue for dual-column fusion).
    arrow = (
        r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")
        .limit(k * 5 if level != "theorem" else k)  # over-fetch for dedup
        .to_arrow()
    )
    rows = _arrow_to_rows(arrow)

    # Aggregate per level.
    if level == "paper":
        rows = _dedup_keep_best(rows, key=lambda r: r["paper_id"])
    elif level == "section":
        rows = _dedup_keep_best(
            rows, key=lambda r: (r["paper_id"], _first_section(r["section_path"]))
        )

    # Sort: (score_desc, chunk_id_asc).
    rows.sort(key=lambda r: (-r["score"], r["chunk_id"]))
    rows = rows[:k]

    return envelope(
        {
            "embed_model": "bge-m3",
            "filter_warnings": [],  # v1: no filters processed
            "next_cursor": None,    # v1: no pagination
            "results": rows,
            "retrieval_mode": "dense_only",
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arrow_to_rows(arrow) -> list[dict[str, Any]]:  # noqa: ANN001
    """Convert a LanceDB Arrow result to per-row dicts with the v1
    result fields. ``score = 1 - _distance / 2`` for L2-normalized
    BGE-M3 vectors yields cosine similarity in [0, 1]."""
    cids = arrow.column("chunk_id").to_pylist()
    paper_ids = arrow.column("paper_id").to_pylist()
    section_paths = arrow.column("section_path").to_pylist()
    theorem_names = arrow.column("theorem_name").to_pylist()
    theorem_labels = arrow.column("theorem_label").to_pylist()
    body_texts = arrow.column("body_text").to_pylist()
    distances = arrow.column("_distance").to_pylist()
    rows = []
    for cid, pid, sp, tn, tl, bt, dist in zip(
        cids, paper_ids, section_paths, theorem_names, theorem_labels, body_texts,
        distances, strict=True,
    ):
        if cid is None:
            continue
        rows.append(
            {
                "chunk_id": cid,
                "label": _format_label(tn, tl),
                "paper_id": pid,
                "score": _distance_to_score(dist),
                "section_path": list(sp) if sp is not None else [],
                "snippet": _snippet(bt),
                "version": 1,  # paper version; no schema column yet
            }
        )
    return rows


def _format_label(theorem_name: str | None, theorem_label: str | None) -> str:
    """Build the ``label`` field per design note (e.g.
    ``"Theorem 3.4"``). Returns empty string when both are None."""
    parts = [s for s in (theorem_name, theorem_label) if s]
    return " ".join(parts)


def _snippet(body_text: str | None) -> str:
    """Take the first :data:`SNIPPET_MAX_CHARS` characters of
    ``body_text`` verbatim. No LLM rewriting (E06_S04 freezes this
    contract)."""
    if not body_text:
        return ""
    return body_text[:SNIPPET_MAX_CHARS]


def _distance_to_score(dist: float | None) -> float:
    """L2 distance on unit vectors → cosine similarity in [0, 1]."""
    if dist is None:
        return 0.0
    return max(0.0, 1.0 - float(dist) / 2.0)


def _first_section(section_path: list[str] | None) -> str:
    if not section_path:
        return ""
    return section_path[0]


def _dedup_keep_best(
    rows: list[dict[str, Any]], key
) -> list[dict[str, Any]]:
    """Group by ``key(row)``; keep the row with the highest score
    in each group. Stable order across runs because LanceDB
    returns deterministic search order."""
    best: dict[Any, dict[str, Any]] = {}
    for r in rows:
        k = key(r)
        if k not in best or r["score"] > best[k]["score"]:
            best[k] = r
    return list(best.values())


# Suppress F401 for asyncio — kept as the import path for handlers
# that need explicit asyncio behavior beyond the ``async def`` shape.
_ = asyncio
