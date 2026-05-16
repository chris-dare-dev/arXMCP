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

**Snippet contract (E06_S04).** ``snippet`` is the first
:data:`SNIPPET_MAX_CHARS` (=150) characters of the chunk's
canonical body text (column ``body_text`` in the LanceDB chunks
table; conceptually ``body_canonical`` per design note 04). NO
LLM rewriting, NO ellipsis beyond the character cap. The
``summary`` field documented in earlier notes drafts is
permanently dropped (would duplicate snippet, requires Haiku call
that breaks BP1 byte-stability when prompt versions change).

**`resource_link` content blocks (E06_S04).** Per the MCP 2025-06-18
spec's ``CallToolResult.content`` array semantics, this handler
returns BOTH a ``structuredContent`` (machine-readable, the dict
envelope) AND a ``content`` array carrying:

1. ``content[0]``: ``TextContent`` with the JSON-pretty-print of
   structuredContent. Keeps the FastMCP default surface for
   clients that read only ``content[0].text``.
2. ``content[1..N]``: one ``ResourceLink`` block per result row,
   in the same ``(score_desc, chunk_id_asc)`` order, with
   ``uri = "arxmcp://chunks/<chunk_id>"``. The MCP spec permits
   resource_link blocks in tool results; spec-compliant clients
   may follow the link to fetch the chunk.

**Note on body-size cap.** ``search_papers`` does NOT call
``server.tools.enforce_byte_cap`` (only ``get_chunk`` does at
v1). The result is bounded by ``k`` (max 50) × per-row size
(snippet ≤150 chars + small fields). When a future milestone
wires cap enforcement here, the wire-overhead factor will need
recalibration to account for the per-row ResourceLink overhead
(F5 from the E06_S04 critique).

The resource_link blocks are advisory — the agent runtime (E08)
does NOT rely on the client following them. Agents that ignore
them call :func:`server.handlers.chunk.handle_get_chunk` to
materialize a full body. Citations API integration is explicitly
NOT a dependency (Citations API validates document blocks in the
messages array, not MCP tool results — see
``docs/snippet-contract.md``).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from mcp.types import CallToolResult, ResourceLink, TextContent
from pydantic import AnyUrl, Field

from server.cache import get_cache
from server.query_encoder import encode_query
from server.tools import CHUNK_RESOURCE_URI_SCHEME, envelope, get_resources

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
    filters: Annotated[
        dict[str, Any] | None,
        Field(description="Reserved for E07_S04; ignored at v1 with filter_warnings"),
    ] = None,
    cursor: Annotated[
        str | None,
        Field(description="Reserved for E07_S04 pagination; ignored at v1"),
    ] = None,
) -> dict[str, Any]:
    """Search the corpus and return ranked chunk results.

    Closes F6 from the E06_S03 critique: ``filters`` and ``cursor``
    are accepted in the schema (matching the brief's promised
    signature) but ignored at v1. The ``filter_warnings`` field
    documents the partial support until E07_S04 wires real
    filtering + pagination.
    """
    r = get_resources()

    # E08_S03: 3-tier cache lookup BEFORE the encode + ANN path.
    # Tier 1 is checked first (no embedding required); Tier 2 needs
    # the query embedding, so we defer it until after the encode.
    # ``level`` is threaded through the cache key so different
    # aggregation levels get distinct cache entries (correctness).
    # E14_S02 — pull the OTel cache-layer setter so each tier hit
    # surfaces on the parent span's ``arxmcp.cache_layer_served``
    # attribute. NoOpTracer fast-path when tracing is disabled.
    from server.observability.tracing import (  # noqa: PLC0415
        set_cache_layer,
        span_ann,
    )

    cache = get_cache()
    if cache is not None:
        cached_payload, _hit_tier = await cache.lookup_search(
            query=query, filters=filters, k=k, level=level,
        )
        if cached_payload is not None:
            # Tier-1 hit — bypass Phase 1/2/3.
            set_cache_layer("tier1")
            structured = cached_payload
            rows = structured.get("results", [])
            content = _build_content_blocks(structured, rows)
            return CallToolResult(content=content, structuredContent=structured)

    # Encode query (singleflight + semaphore — two-tier concurrency).
    async with r.embed_semaphore:
        query_vec = await encode_query(query)

    # Tier-2 lookup with the freshly-computed embedding.
    if cache is not None:
        cached_payload, _hit_tier = await cache.lookup_search(
            query=query, filters=filters, k=k,
            query_embedding=query_vec, level=level,
        )
        if cached_payload is not None:
            set_cache_layer("tier2")
            structured = cached_payload
            rows = structured.get("results", [])
            content = _build_content_blocks(structured, rows)
            return CallToolResult(content=content, structuredContent=structured)

    # Dense ANN over embedding_stmt only. embedding_proof is for
    # proof bodies; mixing without RRF would produce inconsistent
    # rankings (E07 is the right venue for dual-column fusion).
    with span_ann(k=k):
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

    # F6: surface ignored filter/cursor warnings explicitly so the
    # agent runtime can detect partial support.
    filter_warnings: list[str] = []
    if filters:
        filter_warnings.append(
            "filters arg is accepted but not yet processed (deferred to E07_S04)"
        )
    if cursor is not None:
        filter_warnings.append(
            "cursor arg is accepted but pagination is deferred to E07_S04"
        )

    structured = envelope(
        {
            "embed_model": "bge-m3",
            # F5: explicit warning about proof-chunk exclusion at v1.
            "excluded_kinds": ["proof"],
            "filter_warnings": filter_warnings,
            "next_cursor": None,    # v1: no pagination
            "results": rows,
            "retrieval_mode": "dense_only",
        }
    )

    # E08_S03: cache-store on the miss path. We pass the query
    # embedding so Tier 2 indexes it for future semantic-equivalent
    # queries. ``level`` MUST match the lookup key (correctness).
    if cache is not None:
        await cache.store_search(
            query=query,
            filters=filters,
            k=k,
            payload=structured,
            query_embedding=query_vec,
            level=level,
        )

    # E06_S04: assemble the wire ``content`` array — pretty-printed
    # JSON of structuredContent (the FastMCP default surface) +
    # one ResourceLink per result row.
    content = _build_content_blocks(structured, rows)
    return CallToolResult(content=content, structuredContent=structured)


def _build_content_blocks(
    structured: dict[str, Any], rows: list[dict[str, Any]]
) -> list[Any]:
    """Build the ``content`` array per the E06_S04 contract.

    Block 0 is a TextContent carrying ``json.dumps(structured,
    indent=2, sort_keys=True)`` — same shape FastMCP's default
    dict-handler emits, so clients that only read
    ``content[0].text`` see the full payload.

    Blocks 1..N are ResourceLink blocks in the same order as
    ``rows`` (which is already sorted ``(score_desc,
    chunk_id_asc)``). Each link's URI is
    ``arxmcp://chunks/<chunk_id>`` per the design note's resource
    URI scheme.

    Note: ``search_papers`` does NOT call ``enforce_byte_cap``
    (only ``get_chunk`` does at v1). When a future milestone
    wires cap enforcement here, the per-row ResourceLink overhead
    must be added to the wire-overhead factor calibration in
    ``server/tools.py``.
    """
    blocks: list[Any] = [
        TextContent(
            type="text",
            text=json.dumps(structured, indent=2, sort_keys=True, ensure_ascii=False),
        )
    ]
    for row in rows:
        cid = row["chunk_id"]
        blocks.append(
            ResourceLink(
                type="resource_link",
                uri=AnyUrl(f"{CHUNK_RESOURCE_URI_SCHEME}{cid}"),
                name=cid,
            )
        )
    return blocks


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
        # F7 fix from the E06_S03 critique: dropped the
        # hardcoded ``version: 1`` field. The chunks schema has no
        # paper-version column; the prior code emitted a literal
        # ``1`` regardless of the paper's actual arXiv version
        # (``v1``, ``v2``, ...) which is misinformation. The
        # paper_id may carry the version suffix; agents that need
        # it parse it from there.
        rows.append(
            {
                "chunk_id": cid,
                "label": _format_label(tn, tl),
                "paper_id": pid,
                "score": _distance_to_score(dist),
                "section_path": list(sp) if sp is not None else [],
                "snippet": _snippet(bt),
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
    """LanceDB squared-L2 distance → cosine similarity in [0, 1].

    LanceDB returns *squared* L2 distance on ``_distance`` for the
    L2 metric (verified empirically — see the rectification note in
    :func:`server.retrieval.ann._distance_to_score`). For unit
    vectors ``||a-b||² = 2 - 2·cos(a, b)``, so ``cos = 1 - dist/2``
    is the correct conversion. Do NOT "fix" to ``1 - sqrt(dist)/2``
    — that would silently break ranking quality."""
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


