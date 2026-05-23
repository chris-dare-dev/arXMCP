"""m5 spike — hybrid+rerank lift at proper-notebook scale.

Compares dense_only / hybrid / hybrid+rerank against both notebooks
(bridgeland-stability 39 papers + shimura-varieties 12 papers) with
curated queries.json (10 per notebook, paper-level relevance labels
grounded in actually reading each paper).

Writes per-query rows + per-(pipeline, difficulty) aggregates to
measurements.json next to this file.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

NOTEBOOKS = [
    {
        "slug": "bridgeland-stability",
        "lancedb": "var/arxmcp/notebooks/bridgeland-stability/lancedb",
        "queries": "var/arxmcp/notebooks/bridgeland-stability/queries.json",
    },
    {
        "slug": "shimura-varieties",
        "lancedb": "var/arxmcp/notebooks/shimura-varieties/lancedb",
        "queries": "var/arxmcp/notebooks/shimura-varieties/queries.json",
    },
]
TOP_K = 10
ANN_TOP_FETCH = TOP_K * 5  # over-fetch then dedup by paper_id
HYBRID_FUSE_TOP_N = 50


def paper_from_chunk_id(cid: str) -> str | None:
    try:
        return cid.split(":")[1]
    except IndexError:
        return None


def paper_ids_from_arrow_top_k(arrow, top_k: int) -> list[str]:
    """Top-K UNIQUE paper_ids from an arrow result (de-duplicates chunks
    from the same paper, preserving order of first appearance)."""
    seen: list[str] = []
    for pid in arrow["paper_id"].to_pylist():
        if pid not in seen:
            seen.append(pid)
        if len(seen) >= top_k:
            break
    return seen


def paper_ids_from_chunk_id_list(ranked: list[tuple[str, float]], top_k: int) -> list[str]:
    seen: list[str] = []
    for cid, _score in ranked:
        pid = paper_from_chunk_id(cid)
        if pid is None or pid in seen:
            continue
        seen.append(pid)
        if len(seen) >= top_k:
            break
    return seen


def metrics(top_papers: list[str], expected: set[str], adjacent_count_basis: list[str]) -> dict:
    """Compute paper-level metrics. `top_papers` is the top-K unique
    paper_ids; `adjacent_count_basis` is the raw chunk_id list (to count
    chunks from adjacent papers, not deduplicated)."""
    intersect = set(top_papers) & expected
    precision = len(intersect) / TOP_K  # 0..1 per the spike spec
    recall = len(intersect) / len(expected) if expected else 0.0
    top1_in_expected = bool(top_papers) and top_papers[0] in expected
    rank_of_first_relevant: int | None = None
    for i, pid in enumerate(top_papers, start=1):
        if pid in expected:
            rank_of_first_relevant = i
            break
    chunks_from_adjacent = sum(
        1 for pid in adjacent_count_basis[:TOP_K] if pid not in expected
    )
    return {
        "paper_precision_at_10": precision,
        "paper_recall_at_10": recall,
        "top1_in_expected": top1_in_expected,
        "rank_of_first_relevant": rank_of_first_relevant,
        "chunks_from_adjacent_top10": chunks_from_adjacent,
    }


async def run_dense_only(query_text: str, encode_query, tbl) -> tuple[list[str], list[str], float]:
    t0 = time.monotonic()
    qv = await encode_query(query_text)
    arrow = tbl.search(qv, vector_column_name="embedding_stmt").limit(ANN_TOP_FETCH).to_arrow()
    elapsed = (time.monotonic() - t0) * 1000.0
    top_unique = paper_ids_from_arrow_top_k(arrow, TOP_K)
    raw_chunks = arrow["paper_id"].to_pylist()
    return top_unique, raw_chunks, elapsed


async def run_hybrid(
    query_text: str, encode_query, resources, *, with_rerank: bool
) -> tuple[list[str], list[str], dict]:
    timings: dict = {}
    t_total = time.monotonic()
    qv = await encode_query(query_text)
    t = time.monotonic()
    bm25_cands, _fw = resources.bm25_phase.query(query_text, top_n=200)
    timings["bm25_ms"] = (time.monotonic() - t) * 1000.0
    t = time.monotonic()
    fused = await resources.ann_phase.query(query_text, bm25_cands, top_n=HYBRID_FUSE_TOP_N)
    timings["ann_ms"] = (time.monotonic() - t) * 1000.0
    t = time.monotonic()
    ranked = await resources.rerank_phase.rerank(query_text, qv, fused, top_k=TOP_K * 5)
    timings["rerank_ms"] = (time.monotonic() - t) * 1000.0
    timings["total_ms"] = (time.monotonic() - t_total) * 1000.0
    top_unique = paper_ids_from_chunk_id_list(ranked, TOP_K)
    raw_chunks = [pid for pid in (paper_from_chunk_id(cid) for cid, _ in ranked) if pid]
    return top_unique, raw_chunks, timings


async def measure_pipeline_for_notebook(notebook: dict, pipeline: str) -> list[dict]:
    """Returns a list of per-query row dicts for the given (notebook, pipeline)."""
    from server.config import Config
    from server.query_encoder import encode_query
    from server.resources import Resources

    os.environ["ARXMCP_LANCEDB_PATH"] = notebook["lancedb"]
    queries = json.loads(Path(notebook["queries"]).read_text())["queries"]
    rerank_enabled = pipeline == "hybrid_rerank"
    cfg = Config(enable_rerank=rerank_enabled)
    res = await Resources.startup(cfg)
    rows: list[dict] = []
    try:
        for q in queries:
            expected = set(q["expected_relevant_papers"])
            if pipeline == "dense_only":
                top_unique, raw_chunks, elapsed_ms = await run_dense_only(
                    q["text"], encode_query, res.chunks_table
                )
                timings = {"total_ms": elapsed_ms, "bm25_ms": 0.0, "ann_ms": elapsed_ms, "rerank_ms": 0.0}
            else:
                with_rerank = pipeline == "hybrid_rerank"
                top_unique, raw_chunks, timings = await run_hybrid(
                    q["text"], encode_query, res, with_rerank=with_rerank
                )
            m = metrics(top_unique, expected, raw_chunks)
            rows.append({
                "notebook": notebook["slug"],
                "pipeline": pipeline,
                "query_id": q["id"],
                "difficulty": q["difficulty"],
                "expected_relevant_papers": sorted(expected),
                "top_unique_papers": top_unique,
                **m,
                "timings_ms": timings,
            })
            print(
                f"  [{pipeline:14s}] {q['id']:14s} [{q['difficulty']:11s}] "
                f"P@10={m['paper_precision_at_10']:.2f} R@10={m['paper_recall_at_10']:.2f} "
                f"top1={'Y' if m['top1_in_expected'] else 'N'} "
                f"adj={m['chunks_from_adjacent_top10']}/10 "
                f"t={timings['total_ms']:.0f}ms"
            )
    finally:
        await res.shutdown()
    return rows


def aggregate(rows: list[dict]) -> dict:
    """Compute per-(pipeline, difficulty) means and overall means."""
    by_pipeline: dict = {}
    for r in rows:
        p = r["pipeline"]
        if p not in by_pipeline:
            by_pipeline[p] = {
                "overall": {"queries": 0, "p10_sum": 0.0, "r10_sum": 0.0, "top1_sum": 0, "adj_sum": 0, "total_ms_sum": 0.0},
                "easy": {"queries": 0, "p10_sum": 0.0, "r10_sum": 0.0, "top1_sum": 0, "adj_sum": 0},
                "hard": {"queries": 0, "p10_sum": 0.0, "r10_sum": 0.0, "top1_sum": 0, "adj_sum": 0},
                "adversarial": {"queries": 0, "p10_sum": 0.0, "r10_sum": 0.0, "top1_sum": 0, "adj_sum": 0},
            }
        for k in ("overall", r["difficulty"]):
            b = by_pipeline[p][k]
            b["queries"] += 1
            b["p10_sum"] += r["paper_precision_at_10"]
            b["r10_sum"] += r["paper_recall_at_10"]
            b["top1_sum"] += 1 if r["top1_in_expected"] else 0
            b["adj_sum"] += r["chunks_from_adjacent_top10"]
            if k == "overall":
                b["total_ms_sum"] += r["timings_ms"]["total_ms"]
    summary: dict = {}
    for p, buckets in by_pipeline.items():
        summary[p] = {}
        for diff, b in buckets.items():
            n = b["queries"] or 1
            summary[p][diff] = {
                "n": b["queries"],
                "mean_p10": b["p10_sum"] / n,
                "mean_r10": b["r10_sum"] / n,
                "top1_rate": b["top1_sum"] / n,
                "mean_adj_chunks": b["adj_sum"] / n,
            }
            if diff == "overall":
                summary[p][diff]["mean_total_ms"] = b["total_ms_sum"] / n
    return summary


async def main() -> dict:
    all_rows: list[dict] = []
    for notebook in NOTEBOOKS:
        print(f"\n=== notebook: {notebook['slug']} ===")
        for pipeline in ("dense_only", "hybrid", "hybrid_rerank"):
            print(f"  --- pipeline: {pipeline} ---")
            rows = await measure_pipeline_for_notebook(notebook, pipeline)
            all_rows.extend(rows)
    summary = aggregate(all_rows)
    # Lifts (hybrid_rerank vs dense_only, overall + per difficulty).
    lifts: dict = {}
    for diff in ("overall", "easy", "hard", "adversarial"):
        dense = summary["dense_only"][diff]
        hybr = summary["hybrid"][diff]
        rer = summary["hybrid_rerank"][diff]
        lifts[diff] = {
            "hybrid_p10_lift": hybr["mean_p10"] - dense["mean_p10"],
            "rerank_p10_lift_over_hybrid": rer["mean_p10"] - hybr["mean_p10"],
            "full_p10_lift_over_dense": rer["mean_p10"] - dense["mean_p10"],
            "hybrid_top1_lift": hybr["top1_rate"] - dense["top1_rate"],
            "rerank_top1_lift_over_hybrid": rer["top1_rate"] - hybr["top1_rate"],
            "full_top1_lift_over_dense": rer["top1_rate"] - dense["top1_rate"],
            "hybrid_adj_delta": hybr["mean_adj_chunks"] - dense["mean_adj_chunks"],
            "rerank_adj_delta": rer["mean_adj_chunks"] - hybr["mean_adj_chunks"],
        }
    return {
        "rows": all_rows,
        "summary": summary,
        "lifts": lifts,
        "config": {
            "top_k": TOP_K,
            "ann_over_fetch": ANN_TOP_FETCH,
            "hybrid_fuse_top_n": HYBRID_FUSE_TOP_N,
            "notebooks": [n["slug"] for n in NOTEBOOKS],
        },
    }


if __name__ == "__main__":
    out = asyncio.run(main())
    out_path = Path(__file__).parent / "measurements.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {out_path}")
    print("\n=== SUMMARY (overall) ===")
    for p in ("dense_only", "hybrid", "hybrid_rerank"):
        s = out["summary"][p]["overall"]
        print(
            f"  {p:15s} P@10={s['mean_p10']:.3f} R@10={s['mean_r10']:.3f} "
            f"top1={s['top1_rate']:.3f} adj={s['mean_adj_chunks']:.1f} "
            f"t={s['mean_total_ms']:.0f}ms"
        )
    print("\n=== LIFTS ===")
    for diff in ("overall", "easy", "hard", "adversarial"):
        L = out["lifts"][diff]
        print(
            f"  [{diff:11s}] full_lift_over_dense_P10={L['full_p10_lift_over_dense']:+.3f}  "
            f"top1_lift={L['full_top1_lift_over_dense']:+.3f}  "
            f"rerank_only_P10={L['rerank_p10_lift_over_hybrid']:+.3f}"
        )
