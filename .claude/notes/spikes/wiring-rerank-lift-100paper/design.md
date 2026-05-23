# Spike: hybrid+rerank lift at proper-notebook scale (m5)

**Date:** 2026-05-21
**Question:** Does hybrid (BM25 + ANN+RRF) and/or hybrid+rerank (adding the BGE-reranker-v2-m3 cross-encoder) lift intra-notebook paper-level precision over the live dense-only ANN path, when measured against curated notebook fixtures with paper-level relevance labels grounded in actually reading the papers?

This re-runs the wiring-rerank-lift spike with three improvements over the 22-paper original:
1. **Larger, real-curated fixture** — 39 bridgeland-stability papers + 12 shimura-varieties papers, with 10 hand-labeled pointed sub-questions per notebook (20 queries total).
2. **Labels grounded in actually reading the papers** — I dumped the first-section intro chunk per paper and synthesized queries where I know which paper(s) own each topic, rather than guessing.
3. **Difficulty stratification** — each query is tagged `easy` / `hard` / `adversarial`; the report breaks down lift by class. A NO verdict on `hard` + a YES on `easy` is much more diagnostic than an undifferentiated headline.

## Verdict criteria

```
Verdict: YES
  hybrid+rerank lifts paper-level precision@10 over dense_only by ≥ 0.10 absolute,
  AND ≥ 0.30 absolute on `hard` + `adversarial` queries.
  Action: promote e3 from Could to Now; ~1-2 weeks to wire the hybrid pipeline
  into server/handlers/search.py.

Verdict: NO
  Lift < 0.05 absolute OR rerank actively regresses on ≥ 25% of queries.
  Action: close e3 unimplemented. Either dense-only is the structural ceiling
  for /proof-verify's notebook scale (write the architecture-change recommendation
  appendix), OR investigate non-rerank improvements first (sparse fusion, BGE-M3
  multi-vector, ColBERT, domain-adapted encoder).

Verdict: UNCERTAIN
  Lift between 0.05 and 0.10 absolute, or directionally positive but
  inconsistent across difficulty classes.
  Action: investigate score-distribution sharpness and per-query patterns
  before deciding; possibly run a sparse-fusion sub-spike.
```

## Metrics measured per (pipeline, notebook, query)

- **paper_precision_at_10** — unique paper_ids in top-10 chunks that are in `expected_relevant_papers`, divided by 10 (lower bound on precision; chunk-to-paper aggregation).
- **paper_recall_at_10** — `|{papers in top-10} ∩ expected_relevant| / |expected_relevant|`.
- **top1_in_expected** — bool: is the top-1 chunk's paper in `expected_relevant_papers`.
- **rank_of_first_relevant** — 1-based rank of the first chunk whose paper_id is in `expected_relevant`. None if no relevant paper in top-50.
- **chunks_from_adjacent** — count of top-10 chunks whose paper_id is NOT in `expected_relevant` (proxy for adjacent-noise leakage; lower is better).
- **timings_ms** — `bm25_ms`, `ann_ms`, `rerank_ms`, `total_ms`.

## Pipelines

| ID | Stages |
|---|---|
| `dense_only` | ANN over `embedding_stmt`, top-50, take top-10 unique papers |
| `hybrid` | BM25 top-200 → dual ANN+RRF top-50 → identity, take top-10 |
| `hybrid_rerank` | + BGE-reranker-v2-m3 cross-encoder over the 50 candidates, top-10 |

All three target the per-notebook `var/arxmcp/notebooks/<slug>/lancedb` path.

## Out of scope

- Sparse-vector fusion (BGE-M3 multi-vector head). Deferred unless the verdict is UNCERTAIN.
- GPU benchmarking. CPU only; latency observations carry the "CPU regime" caveat.
- Score-distribution analysis. Captured as raw scores in `measurements.json` but not analyzed in the headline verdict.
