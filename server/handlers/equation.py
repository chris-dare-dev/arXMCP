"""``find_equation`` handler — TED + dense cosine fusion (E10_S03).

Two-mode dispatch on the ``latex_or_mathml`` input:

* **MathML input** (``<math>`` root present) → delegate to
  :class:`server.retrieval.equations.EquationIndex` for the
  Zhang-Shasha tree-edit-distance + dense-cosine fusion path. The
  envelope reports ``retrieval_mode="ted_fused"``.
* **LaTeX input** → converted to Presentation MathML at query time
  (latex2mathml) and routed onto the SAME TED lane, reporting
  ``retrieval_mode="ted_fused"``/``"ted_fused_eq"`` with a
  ``query_conversion`` provenance field (retrieval-unlocks-m4). Gated
  by ``Config.eq_latex_route`` — **default OFF** (see the field's
  docstring for why); when off, LaTeX keeps the legacy dense-only
  fallback over ``embedding_stmt``
  (``retrieval_mode="dense_only_stmt_fallback"``), which is also the
  honest outcome when conversion fails.

If the ``equations`` table is missing or every row has
``mathml_tree_json=NULL`` (the indexer has not run for this corpus),
MathML inputs degrade to dense-only with
``retrieval_mode="dense_only_fallback"`` (AC4 of the brief).

The TED scan is bounded (retrieval-unlocks-m4 security fix): see the
``MAX_QUERY_TREE_NODES`` / ``MAX_TED_PAIR_PRODUCT`` / ``TED_WORK_BUDGET``
guards in :mod:`server.retrieval.equations`. Without them a large query
tree (which a short LaTeX string can amplify into) blocks the event loop
for minutes.
"""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any

from latex2mathml.converter import convert as latex2mathml_convert
from pydantic import Field

from server.query_encoder import encode_query
from server.retrieval.equations import EquationIndex, looks_like_mathml
from server.tools import cap_result_list, envelope, get_resources

logger = logging.getLogger(__name__)

MAX_K = 50


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    """E13_S04b — apply the 256 KB result byte cap to the
    ``results[]`` aggregate.

    No-op today (k≤50 with small per-row metadata; TED equation
    index returns chunk_id/paper_id/score only) but defensive
    against future surrounding-context expansion or full-MathML
    payload growth.

    Uses :func:`server.tools.cap_result_list` with
    ``list_key="results"`` (post-F1 rectification): when the cap
    fires, the LOWEST-relevance trailing rows are trimmed until
    the payload fits — agents still get the highest-scoring rows.
    ``chunk_id=None`` because the cap-overflow surface for a
    multi-result aggregate is the response envelope, not a single
    chunk.

    """
    structured, _blocks = cap_result_list(payload, list_key="results")
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

    # retrieval-unlocks-m4 — LaTeX now reaches the TED lane. Convert to
    # Presentation MathML at query time, then feed the SAME
    # ``EquationIndex.query`` path MathML input has always used. The
    # conversion is the only new step; the retrieval method is unchanged,
    # which is why ``retrieval_mode`` keeps its existing vocabulary and
    # the cross-engine caveat rides a separate ``query_conversion`` field
    # (trust-language-policy §6 rule 1: namespaced and axis-specific —
    # retrieval METHOD and query PROVENANCE are two axes, not one token).
    ted_input: str | None = latex_or_mathml if is_mathml else None
    conversion: dict[str, Any] | None = None
    if (
        not is_mathml
        and equations_table is not None
        and getattr(r.config, "eq_latex_route", False)
    ):
        ted_input, conversion = _convert_latex_to_mathml(latex_or_mathml)

    if ted_input is not None and equations_table is not None:
        # TED + cosine fusion path.
        alpha = getattr(r.config, "eq_ted_weight", 0.5)
        index = EquationIndex(
            equations_table=equations_table,
            chunks_table=r.chunks_table,
            alpha=alpha,
        )
        try:
            hits = index.query(ted_input, query_vec, k)
        except (ValueError, RecursionError) as exc:
            # The parsed input could not be turned into a usable tree —
            # degrade to dense-only rather than 5xx. Two sources:
            #   * caller-supplied MathML that failed to parse
            #     -> malformed_mathml_fallback.
            #   * a converted-LaTeX query whose MathML did not parse.
            #     latex2mathml can emit XML-INVALID output (e.g. it leaks
            #     a raw ``&`` alignment tab from \begin{aligned} as
            #     ``<mi>&</mi>``), so this is NOT "valid but degenerate".
            #     The conversion output was therefore NOT used for
            #     retrieval, so query_conversion.applied flips to False —
            #     reporting applied=True here would claim TED ran when it
            #     did not. (RecursionError is caught for symmetry with the
            #     candidate-tree path; unreachable under the 4000-char cap
            #     today, defensive if the cap ever rises.)
            logger.warning("EquationIndex.query failed on MathML: %s", exc)
            if conversion is not None:
                conversion = {
                    "applied": False,
                    "converter": conversion["converter"],
                    "reason": "converter-output-unparseable",
                }
            return await _dense_only(
                r, query_vec, k,
                mode=(
                    "dense_only_stmt_fallback" if conversion
                    else "malformed_mathml_fallback"
                ),
                conversion=conversion,
            )
        if not hits:
            # Index is wired but the candidate set was empty (or
            # every candidate had mathml_tree_json=NULL). Surface
            # the AC4 path so callers can distinguish from
            # "ted_fused with results".
            return await _dense_only(
                r, query_vec, k, mode="dense_only_fallback",
                conversion=conversion,
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
        payload: dict[str, Any] = {
            "alpha": alpha,
            "results": rows[:k],
            "retrieval_mode": getattr(
                index, "last_retrieval_mode", "ted_fused"
            ),
        }
        if conversion is not None:
            payload["query_conversion"] = conversion
        return envelope(_cap(payload))

    if is_mathml and equations_table is None:
        # MathML input but the equations table was not opened at
        # startup. Honor AC4: graceful fallback with a distinct mode
        # tag so callers know the TED path is the missing piece.
        return await _dense_only(
            r, query_vec, k, mode="dense_only_fallback"
        )

    # LaTeX that never reached the TED lane: the equations table is
    # absent, the route is disabled, or conversion failed. Dense-only
    # over embedding_stmt — the mode names that method, and
    # ``query_conversion`` (when present) says which of those it was.
    return await _dense_only(
        r, query_vec, k, mode="dense_only_stmt_fallback",
        conversion=conversion,
    )


def _latex_converter_id() -> str:
    """``latex2mathml==<installed version>`` for the provenance field.

    DERIVED from the installed distribution, never hardcoded: the string
    exists to trace a result to the exact converter build, and a
    hand-maintained literal would silently lie the moment the pin is
    bumped and this line is forgotten (the critique's provenance-drift
    finding). ``importlib.metadata`` reads the same metadata the pin
    installs, so the two cannot diverge.
    """
    try:
        return f"latex2mathml=={version('latex2mathml')}"
    except PackageNotFoundError:  # pragma: no cover — dep is a hard req
        return "latex2mathml==unknown"


def _convert_latex_to_mathml(
    latex: str,
) -> tuple[str | None, dict[str, Any]]:
    """Convert a LaTeX query to Presentation MathML (m4).

    Returns ``(mathml_or_None, query_conversion_payload)``. A ``None``
    first element means the caller must NOT use the TED lane — the
    honest outcome is dense-only, reported as such.

    **Cross-engine caveat, recorded in the payload.** The corpus trees
    were produced by LaTeXML; this converts with latex2mathml, a
    different engine that does NOT expand ``\\newcommand`` macros the way
    LaTeXML did at ingest. The two therefore agree on structure only
    approximately. That gap was measured before this route was made
    available — see ``tests/eval/test_equations_parity.py``: on real
    corpus equations the converted query still retrieves its own equation
    rank-1 (the property that matters for serving), even though exact
    tree agreement is only ~18%.

    Never raises: latex2mathml is a third-party parser running on
    caller-controlled input, so every failure becomes an honest
    dense-only fallback. Input is bounded to 4000 chars by the handler's
    ``Field(max_length=...)``, which bounds CONVERSION and PARSE cost —
    but NOT the downstream TED cost, which a short input can amplify into
    a huge tree. That is bounded separately by the ``MAX_QUERY_TREE_NODES``
    / ``MAX_TED_PAIR_PRODUCT`` / ``TED_WORK_BUDGET`` guards in
    :mod:`server.retrieval.equations`, not here.
    """
    try:
        mathml = latex2mathml_convert(latex)
    except Exception as exc:  # noqa: BLE001 — 3rd-party parser, any error
        logger.info("latex2mathml could not convert query: %s", exc)
        return None, {
            "applied": False,
            "converter": _latex_converter_id(),
            "reason": "unconvertible-latex",
        }
    if not mathml or not looks_like_mathml(mathml):
        # Converter returned something without a <math> root — treat as
        # a failure rather than feeding a non-MathML string to the
        # XML parser.
        return None, {
            "applied": False,
            "converter": _latex_converter_id(),
            "reason": "converter-output-not-mathml",
        }
    return mathml, {"applied": True, "converter": _latex_converter_id()}


# ---------------------------------------------------------------------------
# Dense-only fallback (retained from the v1 handler)
# ---------------------------------------------------------------------------


async def _dense_only(
    r: Any,
    query_vec: Any,
    k: int,
    mode: str,
    conversion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the legacy dense-only ANN over ``embedding_stmt``.

    Used in three cases (the ``mode`` tag tells callers which):

    * ``mode="dense_only_stmt_fallback"`` — LaTeX that did not reach
      the TED lane: the equations table is absent, the route is
      disabled, or conversion failed. When m4's conversion was
      attempted, ``conversion`` distinguishes those.
    * ``mode="dense_only_fallback"`` — MathML input but the
      equations table is absent or empty (AC4 of the brief).
    * ``mode="malformed_mathml_fallback"`` — caller-supplied MathML
      that failed to parse; degrade rather than 5xx. NOT used for a
      failed LaTeX conversion — that is not the caller's MathML.

    ``conversion`` is echoed as ``query_conversion`` when present, so a
    dense-only answer still says whether a conversion was tried and why
    it did not carry (m4).
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
    payload: dict[str, Any] = {
        "results": rows[:k],
        "retrieval_mode": mode,
    }
    if conversion is not None:
        payload["query_conversion"] = conversion
    return envelope(_cap(payload))


def _distance_to_score(dist: float | None) -> float:
    if dist is None:
        return 0.0
    return max(0.0, 1.0 - float(dist) / 2.0)
