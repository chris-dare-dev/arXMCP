"""Spike POC: compare dense-only vs hybrid vs hybrid+rerank precision@10
across 3 pointed sub-questions against the 22-paper math.AG corpus.

Throwaway code. Imports from the live arXMCP repo modules; not packaged.
Writes results to measurements.json next to this file.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

# Force the staging dataset (the 22-paper math.AG corpus).
os.environ["ARXMCP_LANCEDB_PATH"] = "var/arxmcp/index/lancedb-staging"

QUERIES = [
    {
        "id": "Q1",
        "text": "Bridgeland stability conditions on Enriques surfaces and elliptic surfaces",
        "known_relevant": {"2604.26204", "2604.26208"},
    },
    {
        "id": "Q2",
        "text": "Rigidity of compact Kähler manifolds and contact Kähler manifolds",
        "known_relevant": {"2604.26329", "2604.26425", "2604.27484"},
    },
    {
        "id": "Q3",
        "text": "Strata of differentials, primitive nonhyperelliptic components, totally ramified covers",
        "known_relevant": {"2604.26177", "2604.26193"},
    },
]
TOP_K = 10


def precision_at_k(retrieved_paper_ids: list[str], known: set[str]) -> float:
    """Recall over the known-relevant set, capped at 1.0."""
    if not known:
        return 0.0
    unique_pids = set(retrieved_paper_ids)
    hits = unique_pids & known
    return min(1.0, len(hits) / len(known))


async def run_dense_only(query_text: str, encode_query, tbl) -> tuple[list[str], float]:
    """Reproduce the live handler's dense-only ANN path."""
    t0 = time.monotonic()
    query_vec = await encode_query(query_text)
    arrow = (
        tbl.search(query_vec, vector_column_name="embedding_stmt")
        .limit(TOP_K * 5)
        .to_arrow()
    )
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    paper_ids = arrow.column("paper_id").to_pylist()[:TOP_K]
    return paper_ids, elapsed_ms


async def run_hybrid(
    query_text: str, encode_query, resources, *, with_rerank: bool
) -> tuple[list[str], float, dict[str, float]]:
    """Reproduce _run_hybrid_against_corpus orchestration on one query."""
    timings: dict[str, float] = {}
    t_total = time.monotonic()

    query_vec = await encode_query(query_text)

    # Phase 1: BM25
    t = time.monotonic()
    bm25_candidates, _fw = resources.bm25_phase.query(query_text, top_n=200)
    timings["bm25_ms"] = (time.monotonic() - t) * 1000.0

    # Phase 2: dual-ANN + RRF
    t = time.monotonic()
    fused = await resources.ann_phase.query(query_text, bm25_candidates, top_n=50)
    timings["ann_ms"] = (time.monotonic() - t) * 1000.0

    # Phase 3: optional rerank (passthrough when disabled)
    t = time.monotonic()
    ranked = await resources.rerank_phase.rerank(
        query_text, query_vec, fused, top_k=TOP_K
    )
    timings["rerank_ms"] = (time.monotonic() - t) * 1000.0
    timings["total_ms"] = (time.monotonic() - t_total) * 1000.0

    # Map chunk_ids back to paper_ids via prefix parsing.
    # chunk_id format: arxiv:<paper_id>:<16-hex>
    paper_ids = []
    for cid, _score in ranked:
        try:
            paper_ids.append(cid.split(":")[1])
        except IndexError:
            continue
    return paper_ids, timings["total_ms"], timings


async def main() -> dict:
    from server.config import Config
    from server.query_encoder import encode_query
    from server.resources import Resources
    import lancedb

    results: dict = {
        "fixture": "var/arxmcp/index/lancedb-staging (22 math.AG papers, corpus_version=101)",
        "queries": [q["id"] for q in QUERIES],
        "top_k": TOP_K,
        "runs": {},
    }

    # --- DENSE_ONLY (live handler path) ---
    print("\n=== DENSE_ONLY ===")
    cfg_dense = Config(enable_rerank=False)
    res_dense = await Resources.startup(cfg_dense)
    try:
        dense_rows = []
        for q in QUERIES:
            paper_ids, elapsed = await run_dense_only(
                q["text"], encode_query, res_dense.chunks_table
            )
            p = precision_at_k(paper_ids, q["known_relevant"])
            dense_rows.append(
                {
                    "query_id": q["id"],
                    "precision_at_10": p,
                    "top_paper_ids": paper_ids,
                    "elapsed_ms": elapsed,
                }
            )
            print(f"  {q['id']}: P@10={p:.3f}  papers={paper_ids[:5]}  {elapsed:.1f}ms")
        results["runs"]["dense_only"] = dense_rows
    finally:
        await res_dense.shutdown()

    # --- HYBRID (no rerank) ---
    print("\n=== HYBRID (no rerank) ===")
    cfg_hybrid = Config(enable_rerank=False)
    res_hybrid = await Resources.startup(cfg_hybrid)
    try:
        hybrid_rows = []
        for q in QUERIES:
            paper_ids, total_ms, timings = await run_hybrid(
                q["text"], encode_query, res_hybrid, with_rerank=False
            )
            p = precision_at_k(paper_ids, q["known_relevant"])
            hybrid_rows.append(
                {
                    "query_id": q["id"],
                    "precision_at_10": p,
                    "top_paper_ids": paper_ids,
                    "timings_ms": timings,
                }
            )
            print(
                f"  {q['id']}: P@10={p:.3f}  papers={paper_ids[:5]}  "
                f"bm25={timings['bm25_ms']:.1f} ann={timings['ann_ms']:.1f} "
                f"rerank={timings['rerank_ms']:.1f} total={total_ms:.1f}ms"
            )
        results["runs"]["hybrid"] = hybrid_rows
    finally:
        await res_hybrid.shutdown()

    # --- HYBRID + RERANK ---
    print("\n=== HYBRID + RERANK ===")
    cfg_rerank = Config(enable_rerank=True)
    res_rerank = await Resources.startup(cfg_rerank)
    try:
        rerank_rows = []
        for q in QUERIES:
            paper_ids, total_ms, timings = await run_hybrid(
                q["text"], encode_query, res_rerank, with_rerank=True
            )
            p = precision_at_k(paper_ids, q["known_relevant"])
            rerank_rows.append(
                {
                    "query_id": q["id"],
                    "precision_at_10": p,
                    "top_paper_ids": paper_ids,
                    "timings_ms": timings,
                }
            )
            print(
                f"  {q['id']}: P@10={p:.3f}  papers={paper_ids[:5]}  "
                f"bm25={timings['bm25_ms']:.1f} ann={timings['ann_ms']:.1f} "
                f"rerank={timings['rerank_ms']:.1f} total={total_ms:.1f}ms"
            )
        results["runs"]["hybrid_rerank"] = rerank_rows
    finally:
        await res_rerank.shutdown()

    # Summary
    def mean(rows):
        return sum(r["precision_at_10"] for r in rows) / len(rows)

    summary = {
        "dense_only_p10_mean": mean(results["runs"]["dense_only"]),
        "hybrid_p10_mean": mean(results["runs"]["hybrid"]),
        "hybrid_rerank_p10_mean": mean(results["runs"]["hybrid_rerank"]),
    }
    summary["hybrid_lift_over_dense"] = (
        summary["hybrid_p10_mean"] - summary["dense_only_p10_mean"]
    )
    summary["rerank_lift_over_hybrid"] = (
        summary["hybrid_rerank_p10_mean"] - summary["hybrid_p10_mean"]
    )
    summary["full_lift_over_dense"] = (
        summary["hybrid_rerank_p10_mean"] - summary["dense_only_p10_mean"]
    )
    results["summary"] = summary
    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v:.3f}")
    return results


if __name__ == "__main__":
    out = asyncio.run(main())
    out_path = Path(__file__).parent / "measurements.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {out_path}")
