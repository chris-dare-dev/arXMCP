"""Dual-column-fusion spike — does querying the unused ``embedding_proof``
column recover the "deep-treatment discrimination" case?

Context (from notebook-retrieval-m1 spike-accuracy-by-difficulty-class.md §4):
the live ``search_papers`` path is DENSE-ONLY over ``embedding_stmt`` and
explicitly excludes proof chunks from results. Every notebook carries a
fully-populated ``embedding_proof`` column (bridgeland 2671 proof chunks,
shimura 1664 — verified) that the live path never queries. The operator's
"depth lives where dense-only misses" intuition points at THIS column: the
paper that PROVES a named theorem owns its depth in the proof body.

This harness compares three bm25-free / rerank-free pipelines against the
same curated queries.json (paper-level relevance labels, difficulty-tagged)
the prior m5 spike used:

  dense_only        single ANN over embedding_stmt (the live path, baseline)
  dense_dual_paper  ANN over stmt + ANN over proof (prefilter kind='proof'),
                    dedup EACH to unique paper_ids, RRF-fuse the two PAPER
                    lists. Rewards a paper strong in BOTH columns — the
                    depth-boost hypothesis in its strongest form.
  dense_dual_chunk  same two ANN searches, RRF-fused at CHUNK level (mirrors
                    the production ANNPhase fusion granularity), then dedup
                    to papers. The "ship-as-is via ANNPhase" comparison.

Both dual arms prefilter the proof search to kind='proof' so the 4133/1961
zero-vector non-proof rows (a unit query vs a zero vector has fixed
squared-L2 distance 1, which outranks any proof chunk with cosine < 0.5)
cannot pollute the proof arm — a clean measurement of the proof signal.

READ-ONLY: changes no server code. Writes measurements_dual.json next to
this file. Run:

    HF_HUB_OFFLINE=1 KMP_DUPLICATE_LIB_OK=TRUE \
      /Users/chris.dare/Library/Python/3.9/bin/uv run python \
      .claude/notes/spikes/dual-column-fusion/poc_dual.py
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import lancedb

from server.retrieval.rrf import reciprocal_rank_fusion

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
ANN_TOP_FETCH = TOP_K * 5  # 50 — matches PER_COLUMN_LIMIT / the m5 spike
PIPELINES = ("dense_only", "dense_dual_paper", "dense_dual_chunk")


def paper_from_chunk_id(cid: str) -> str | None:
    try:
        return cid.split(":")[1]
    except IndexError:
        return None


def unique_in_order(items: list[str], top_k: int | None = None) -> list[str]:
    seen: list[str] = []
    for x in items:
        if x is None or x in seen:
            continue
        seen.append(x)
        if top_k is not None and len(seen) >= top_k:
            break
    return seen


def paper_ids_from_chunk_id_list(
    ranked: list[tuple[str, float]], top_k: int
) -> list[str]:
    seen: list[str] = []
    for cid, _score in ranked:
        pid = paper_from_chunk_id(cid)
        if pid is None or pid in seen:
            continue
        seen.append(pid)
        if len(seen) >= top_k:
            break
    return seen


def metrics(top_papers: list[str], expected: set[str], adj_basis: list[str]) -> dict:
    intersect = set(top_papers) & expected
    precision = len(intersect) / TOP_K
    recall = len(intersect) / len(expected) if expected else 0.0
    top1 = bool(top_papers) and top_papers[0] in expected
    rank_first: int | None = None
    for i, pid in enumerate(top_papers, start=1):
        if pid in expected:
            rank_first = i
            break
    chunks_from_adjacent = sum(1 for pid in adj_basis[:TOP_K] if pid not in expected)
    return {
        "paper_precision_at_10": precision,
        "paper_recall_at_10": recall,
        "top1_in_expected": top1,
        "rank_of_first_relevant": rank_first,
        "adjacent_in_top10": chunks_from_adjacent,
    }


def _search(tbl, qv, column: str, *, proof_only: bool):
    q = tbl.search(qv, vector_column_name=column)
    if proof_only:
        q = q.where("kind = 'proof'", prefilter=True)
    return q.limit(ANN_TOP_FETCH).to_arrow()


async def run_pipeline(pipeline: str, query_text: str, encode_query, tbl):
    t0 = time.monotonic()
    qv = await encode_query(query_text)
    if pipeline == "dense_only":
        arrow = _search(tbl, qv, "embedding_stmt", proof_only=False)
        top_unique = unique_in_order(arrow["paper_id"].to_pylist(), TOP_K)
        raw = arrow["paper_id"].to_pylist()
    elif pipeline == "dense_dual_paper":
        stmt = _search(tbl, qv, "embedding_stmt", proof_only=False)
        proof = _search(tbl, qv, "embedding_proof", proof_only=True)
        papers_stmt = unique_in_order(stmt["paper_id"].to_pylist())
        papers_proof = unique_in_order(proof["paper_id"].to_pylist())
        fused = reciprocal_rank_fusion([papers_stmt, papers_proof])
        top_unique = [pid for pid, _ in fused][:TOP_K]
        raw = [pid for pid, _ in fused]
    elif pipeline == "dense_dual_chunk":
        stmt = _search(tbl, qv, "embedding_stmt", proof_only=False)
        proof = _search(tbl, qv, "embedding_proof", proof_only=True)
        fused = reciprocal_rank_fusion(
            [stmt["chunk_id"].to_pylist(), proof["chunk_id"].to_pylist()]
        )
        top_unique = paper_ids_from_chunk_id_list(fused, TOP_K)
        raw = [p for p in (paper_from_chunk_id(c) for c, _ in fused) if p]
    else:  # pragma: no cover
        raise ValueError(pipeline)
    elapsed = (time.monotonic() - t0) * 1000.0
    return top_unique, raw, elapsed


async def measure(notebook: dict) -> list[dict]:
    from server.query_encoder import encode_query

    queries = json.loads(Path(notebook["queries"]).read_text())["queries"]
    tbl = lancedb.connect(notebook["lancedb"]).open_table("chunks")
    rows: list[dict] = []
    for pipeline in PIPELINES:
        print(f"  --- {pipeline} ---")
        for q in queries:
            expected = set(q["expected_relevant_papers"])
            top_unique, raw, elapsed = await run_pipeline(
                pipeline, q["text"], encode_query, tbl
            )
            m = metrics(top_unique, expected, raw)
            rows.append({
                "notebook": notebook["slug"],
                "pipeline": pipeline,
                "query_id": q["id"],
                "difficulty": q["difficulty"],
                "expected_relevant_papers": sorted(expected),
                "top_unique_papers": top_unique,
                **m,
                "elapsed_ms": elapsed,
            })
            print(
                f"  [{pipeline:16s}] {q['id']:14s} [{q['difficulty']:11s}] "
                f"P@10={m['paper_precision_at_10']:.2f} "
                f"R@10={m['paper_recall_at_10']:.2f} "
                f"top1={'Y' if m['top1_in_expected'] else 'N'} "
                f"rank1={m['rank_of_first_relevant']} t={elapsed:.0f}ms"
            )
    return rows


def aggregate(rows: list[dict]) -> dict:
    by: dict = {}
    for r in rows:
        p = r["pipeline"]
        by.setdefault(p, {d: {"n": 0, "p10": 0.0, "r10": 0.0, "top1": 0, "ms": 0.0}
                          for d in ("overall", "easy", "hard", "adversarial")})
        for key in ("overall", r["difficulty"]):
            b = by[p][key]
            b["n"] += 1
            b["p10"] += r["paper_precision_at_10"]
            b["r10"] += r["paper_recall_at_10"]
            b["top1"] += 1 if r["top1_in_expected"] else 0
            b["ms"] += r["elapsed_ms"]
    summary: dict = {}
    for p, buckets in by.items():
        summary[p] = {}
        for d, b in buckets.items():
            n = b["n"] or 1
            summary[p][d] = {
                "n": b["n"],
                "mean_p10": b["p10"] / n,
                "mean_r10": b["r10"] / n,
                "top1_rate": b["top1"] / n,
                "mean_ms": b["ms"] / n,
            }
    return summary


def transitions(rows: list[dict]) -> list[dict]:
    """Per-query top-1 flips: dense_only vs each dual pipeline."""
    by_q: dict = {}
    for r in rows:
        by_q.setdefault(r["query_id"], {})[r["pipeline"]] = r
    out: list[dict] = []
    for qid, byp in sorted(by_q.items()):
        base = byp["dense_only"]
        rec = {
            "query_id": qid,
            "difficulty": base["difficulty"],
            "dense_top1": base["top1_in_expected"],
            "dense_rank1": base["rank_of_first_relevant"],
            "dense_r10": base["paper_recall_at_10"],
        }
        for p in ("dense_dual_paper", "dense_dual_chunk"):
            rec[f"{p}_top1"] = byp[p]["top1_in_expected"]
            rec[f"{p}_rank1"] = byp[p]["rank_of_first_relevant"]
            rec[f"{p}_r10"] = byp[p]["paper_recall_at_10"]
        out.append(rec)
    return out


async def main() -> dict:
    all_rows: list[dict] = []
    for nb in NOTEBOOKS:
        print(f"\n=== notebook: {nb['slug']} ===")
        all_rows.extend(await measure(nb))
    summary = aggregate(all_rows)
    lifts: dict = {}
    for d in ("overall", "easy", "hard", "adversarial"):
        base = summary["dense_only"][d]
        lifts[d] = {}
        for p in ("dense_dual_paper", "dense_dual_chunk"):
            lifts[d][p] = {
                "top1_lift": summary[p][d]["top1_rate"] - base["top1_rate"],
                "r10_lift": summary[p][d]["mean_r10"] - base["mean_r10"],
                "p10_lift": summary[p][d]["mean_p10"] - base["mean_p10"],
            }
    return {
        "rows": all_rows,
        "summary": summary,
        "lifts": lifts,
        "transitions": transitions(all_rows),
        "config": {
            "top_k": TOP_K,
            "ann_top_fetch": ANN_TOP_FETCH,
            "pipelines": list(PIPELINES),
            "notebooks": [n["slug"] for n in NOTEBOOKS],
            "proof_arm_prefilter": "kind = 'proof'",
        },
    }


if __name__ == "__main__":
    out = asyncio.run(main())
    out_path = Path(__file__).parent / "measurements_dual.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {out_path}")
    print("\n=== SUMMARY (overall) ===")
    for p in PIPELINES:
        s = out["summary"][p]["overall"]
        print(f"  {p:16s} P@10={s['mean_p10']:.3f} R@10={s['mean_r10']:.3f} "
              f"top1={s['top1_rate']:.3f} t={s['mean_ms']:.0f}ms")
    print("\n=== LIFTS over dense_only (per difficulty) ===")
    for d in ("overall", "easy", "hard", "adversarial"):
        for p in ("dense_dual_paper", "dense_dual_chunk"):
            L = out["lifts"][d][p]
            print(f"  [{d:11s}] {p:16s} top1={L['top1_lift']:+.3f} "
                  f"R@10={L['r10_lift']:+.3f} P@10={L['p10_lift']:+.3f}")
