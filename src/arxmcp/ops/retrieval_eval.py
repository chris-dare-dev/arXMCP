"""Run the hybrid retrieval pipeline over eval queries and score each one.

Both ``tests/eval/test_retrieval_quality.py`` and the drift watchdog
(``src/arxmcp/ops/watchdog_eval.py``) score a corpus with this function. It lives in
``ops`` rather than in the test tree because the watchdog ships with the
server and runs the post-cutover gate; the test tree is not installed.
"""

from __future__ import annotations

import asyncio
import time
import warnings
from collections.abc import Awaitable, Callable
from typing import Any

from arxmcp.ops.eval_metrics import ndcg_at_k, recall_at_k

#: Final cutoff after fusion and rerank; also the Recall@k cutoff.
FINAL_TOP_K = 10

#: Cutoff for nDCG.
NDCG_K = 5


def run_hybrid_against_corpus(
    queries: list[dict],
    tbl: Any,
    encode_query: Callable[[str], Awaitable[Any]],
    *,
    corpus_version: int,
    rerank_enabled: bool,
) -> list[dict]:
    """Score every query through BM25, dual-ANN + RRF, and optional rerank.

    Per-query stages:
      1. BM25: top-200 candidates.
      2. Dual-ANN fused with the BM25 list by RRF: top-50.
      3. Cross-encoder rerank when enabled (a passthrough otherwise):
         top ``FINAL_TOP_K``.

    Each row carries ``ndcg5``, ``recall10``, the retrieved ids and the
    per-phase latency in milliseconds (``bm25_ms``, ``ann_ms``,
    ``rerank_ms``, ``total_ms``).

    ``encode_query`` is called once per query for the rerank vector; the
    ANN phase encodes again internally, and the query encoder's
    singleflight collapses the two into one forward pass.

    ``tbl`` and ``corpus_version`` identify the corpus the caller pinned;
    the pipeline itself is built from ``Config`` by ``Resources.startup``,
    with the BM25 phase forced on for this run whatever
    ``ARXMCP_BM25_PHASE`` says: the server leaves it off because no served
    tool is hybrid, and this pipeline is.

    Raises ``ValueError`` when ``Config`` cannot be built from the
    environment or a query is malformed, and ``RuntimeError`` when the
    BM25 phase does not load, including when its artifact fails the
    cross-check against the live chunks table.
    """
    from arxmcp.server.resources import Resources  # noqa: PLC0415
    from arxmcp.settings import Config  # noqa: PLC0415

    # Config() reads every declared ARXMCP_* variable, so a stray value
    # in the operator's shell fails here. Name the likely cause.
    try:
        cfg = Config(enable_rerank=rerank_enabled, bm25_phase="on")
    except Exception as exc:
        raise ValueError(
            "eval harness Config() failed; an ARXMCP_* environment variable "
            "in this shell may be invalid for the loopback or value-range "
            f"validators: {exc}"
        ) from exc

    resources = None
    loop = asyncio.new_event_loop()
    try:
        resources = loop.run_until_complete(Resources.startup(cfg))
        if resources.bm25_phase is None:
            raise RuntimeError(
                "hybrid eval needs the BM25 phase, and it did not load "
                f"(state={resources.bm25_phase_state}); the log above names "
                "the cause, e.g. an artifact that failed the live-table "
                "cross-check."
            )

        per_query_rows: list[dict] = []
        for query_idx, query in enumerate(queries):
            try:
                query_id = query["query_id"]
                query_text = query["query_text"]
                ground_truth = {
                    entry["chunk_id"]: entry["relevance"]
                    for entry in query["relevant_chunks"]
                }
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"queries[{query_idx}] is malformed ({exc!r}); run "
                    "`python src/arxmcp/tools/validate_eval_fixtures.py` to diagnose."
                ) from exc

            t_total_start = time.monotonic()
            query_vec = loop.run_until_complete(encode_query(query_text))

            t_bm25_start = time.monotonic()
            bm25_candidates, _filter_warnings = resources.bm25_phase.query(
                query_text, top_n=200
            )
            bm25_ms = (time.monotonic() - t_bm25_start) * 1000.0

            t_ann_start = time.monotonic()
            fused = loop.run_until_complete(
                resources.ann_phase.query(query_text, bm25_candidates, top_n=50)
            )
            ann_ms = (time.monotonic() - t_ann_start) * 1000.0

            t_rerank_start = time.monotonic()
            ranked = loop.run_until_complete(
                resources.rerank_phase.rerank(
                    query_text, query_vec, fused, top_k=FINAL_TOP_K,
                )
            )
            rerank_ms = (time.monotonic() - t_rerank_start) * 1000.0
            total_ms = (time.monotonic() - t_total_start) * 1000.0

            retrieved_chunk_ids = [cid for cid, _score in ranked]
            per_query_rows.append(
                {
                    "ndcg5": ndcg_at_k(retrieved_chunk_ids, ground_truth, k=NDCG_K),
                    "query_id": query_id,
                    "query_text": query_text,
                    "recall10": recall_at_k(
                        retrieved_chunk_ids, ground_truth, k=FINAL_TOP_K
                    ),
                    "retrieved_chunk_ids": retrieved_chunk_ids,
                    "bm25_ms": bm25_ms,
                    "ann_ms": ann_ms,
                    "rerank_ms": rerank_ms,
                    "total_ms": total_ms,
                    "pipeline": "hybrid+rerank" if rerank_enabled else "hybrid",
                }
            )
        return per_query_rows
    finally:
        if resources is not None:
            try:
                loop.run_until_complete(
                    asyncio.wait_for(resources.shutdown(), timeout=30.0)
                )
            except TimeoutError:
                # The scores are already computed; a slow drain is worth
                # a warning, not a failed run.
                warnings.warn(
                    "Resources.shutdown exceeded the 30s drain budget "
                    "during eval cleanup; the eval results are valid "
                    "but the next process may inherit half-released "
                    "handles.",
                    stacklevel=2,
                )
        # The query encoder's singleflight registry holds futures bound to
        # this loop; clear it before the loop closes so a later caller in
        # the same process does not await a dead future.
        from arxmcp.server import query_encoder  # noqa: PLC0415

        query_encoder._reset_for_tests()
        loop.close()
