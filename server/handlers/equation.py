"""``find_equation`` handler — TED + dense cosine fusion (E10_S03).

Two-mode dispatch on the ``latex_or_mathml`` input:

* **MathML input** (``<math>`` root present) → delegate to
  :class:`server.retrieval.equations.EquationIndex` for the
  Zhang-Shasha tree-edit-distance + dense-cosine fusion path. The
  envelope reports ``retrieval_mode="ted_fused"``.
* **LaTeX input** → keep the legacy dense-only fallback over the
  chunks table's ``embedding_stmt`` column. The envelope reports
  ``retrieval_mode="dense_only_stmt_fallback"``. Until a query-time
  LaTeXML subprocess pool lands (deferred — see
  ``research-synthesis.md`` §3 D4), there is no way to parse LaTeX
  into MathML inside the request path.

If the ``equations`` table is missing or every row has
``mathml_tree_json=NULL`` (the indexer has not run for this corpus),
MathML inputs degrade to dense-only with
``retrieval_mode="dense_only_fallback"`` (AC4 of the brief).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field

from server.query_encoder import encode_query
from server.retrieval.equations import EquationIndex, looks_like_mathml
from server.tools import enforce_byte_cap, envelope, get_resources

logger = logging.getLogger(__name__)

MAX_K = 50


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    """E13_S04b — apply the 256 KB result byte cap. No-op today
    (k≤50 with small per-row metadata; TED equation index returns
    chunk_id/paper_id/score only) but defensive against future
    surrounding-context expansion or full-MathML payload growth.
    Passes ``chunk_id=None`` because the cap-overflow surface for
    a multi-result aggregate is the response envelope, not a single
    chunk.
    """
    structured, _blocks = enforce_byte_cap(payload)
    return structured


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

    is_mathml = looks_like_mathml(latex_or_mathml)
    equations_table = getattr(r, "equations_table", None)

    if is_mathml and equations_table is not None:
        # TED + cosine fusion path.
        alpha = getattr(r.config, "eq_ted_weight", 0.5)
        index = EquationIndex(
            equations_table=equations_table,
            chunks_table=r.chunks_table,
            alpha=alpha,
        )
        try:
            hits = index.query(latex_or_mathml, query_vec, k)
        except ValueError as exc:
            # Malformed MathML — fall through to dense-only rather
            # than 5xx the request. The caller gets a coherent
            # result set, just without TED.
            logger.warning("EquationIndex.query failed on MathML: %s", exc)
            return await _dense_only(
                r, query_vec, k, mode="malformed_mathml_fallback"
            )
        if not hits:
            # Index is wired but the candidate set was empty (or
            # every candidate had mathml_tree_json=NULL). Surface
            # the AC4 path so callers can distinguish from
            # "ted_fused with results".
            return await _dense_only(
                r, query_vec, k, mode="dense_only_fallback"
            )
        rows = [
            {
                "chunk_id": h.chunk_id,
                "cosine_score": round(h.cosine_score, 6),
                "equation_id": h.equation_id,
                "paper_id": h.paper_id,
                "score": round(h.final_score, 6),
                "ted_norm": round(h.ted_norm, 6),
            }
            for h in hits
        ]
        # `last_retrieval_mode` reflects which dense path fired:
        # ``"ted_fused_eq"`` when EquationIndex queried the
        # equations table's ``embedding_eq`` column directly
        # (E10_S03b), ``"ted_fused"`` when the chunks-proxy
        # legacy path fired (corpora pre-E10_S03b). The default
        # in the EquationIndex constructor is ``"ted_fused"`` so
        # this defaults safely if a future code path forgets to
        # set the attribute.
        return envelope(_cap(
            {
                "alpha": alpha,
                "results": rows[:k],
                "retrieval_mode": getattr(
                    index, "last_retrieval_mode", "ted_fused"
                ),
            })
        )

    if is_mathml and equations_table is None:
        # MathML input but the equations table was not opened at
        # startup. Honor AC4: graceful fallback with a distinct mode
        # tag so callers know the TED path is the missing piece.
        return await _dense_only(
            r, query_vec, k, mode="dense_only_fallback"
        )

    # LaTeX input — legacy dense-only path on embedding_stmt.
    return await _dense_only(
        r, query_vec, k, mode="dense_only_stmt_fallback"
    )


# ---------------------------------------------------------------------------
# Dense-only fallback (retained from the v1 handler)
# ---------------------------------------------------------------------------


async def _dense_only(
    r: Any, query_vec: Any, k: int, mode: str
) -> dict[str, Any]:
    """Run the legacy dense-only ANN over ``embedding_stmt``.

    Used in three cases (the ``mode`` tag tells callers which):

    * ``mode="dense_only_stmt_fallback"`` — LaTeX input; no LaTeXML
      pool to parse into MathML; the current production path.
    * ``mode="dense_only_fallback"`` — MathML input but the
      equations table is absent or empty (AC4 of the brief).
    * ``mode="malformed_mathml_fallback"`` — MathML input but the
      parse failed; degrade rather than 5xx.
    """
    arrow = (
        r.chunks_table.search(
            query_vec, vector_column_name="embedding_stmt"
        )
        .limit(k)
        .to_arrow()
    )
    rows: list[dict[str, Any]] = []
    cids = arrow.column("chunk_id").to_pylist()
    paper_ids = arrow.column("paper_id").to_pylist()
    distances = arrow.column("_distance").to_pylist()
    for cid, pid, dist in zip(cids, paper_ids, distances, strict=True):
        if cid is None:
            continue
        rows.append(
            {
                "chunk_id": cid,
                "paper_id": pid,
                "score": _distance_to_score(dist),
            }
        )
    rows.sort(key=lambda row: (-row["score"], row["chunk_id"]))
    return envelope(_cap(
        {
            "results": rows[:k],
            "retrieval_mode": mode,
        }
    ))


def _distance_to_score(dist: float | None) -> float:
    if dist is None:
        return 0.0
    return max(0.0, 1.0 - float(dist) / 2.0)
