# Spike: handler-wiring rerank lift — note

**Date:** 2026-05-20
**Question:** Does hybrid + BGE-reranker-v2-m3 lift intra-notebook precision over the live dense-only `search_papers` path, on adjacent-noise queries within a topologically-clustered math.AG corpus?

## Verdict

**NO** — on the 22-paper math.AG fixture, hybrid+rerank does not lift paper-level precision@10 over dense-only ANN (mean P@10 = 0.722 across all three configurations). On the load-bearing query (Q1 — Bridgeland stability on Enriques/elliptic surfaces, the cleanest adjacent-noise test in the fixture), hybrid+rerank is **qualitatively worse than dense-only**: rerank promoted an adjacent paper (`2604.28085`, "lc pair semiample") into top-3, displacing chunks from the known-relevant `2604.26204`. Latency cost: rerank is **80x slower** than dense-only on CPU (6.8 s vs 83 ms).

**CAVEAT (load-bearing):** the 22-paper fixture is below the scale at which BM25 / RRF / cross-encoder rerank typically demonstrates value. A NO verdict at 22 papers does NOT cleanly generalize to 100-paper notebooks. The defensible read is: **the rerank-lift hypothesis is currently unsupported by evidence at the scale we can measure, and a 100-paper-fixture follow-up is required before committing to wire the hybrid pipeline as the live-handler default.**

## Headline numbers

| pipeline | Q1 P@10 | Q2 P@10 | Q3 P@10 | mean | mean total_ms |
|---|---|---|---|---|---|
| dense_only | 0.500 | 0.667 | 1.000 | **0.722** | 83 |
| hybrid (BM25 + RRF, no rerank) | 0.500 | 0.667 | 1.000 | **0.722** | 57 |
| hybrid + rerank (cross-encoder) | 0.500 | 0.667 | 1.000 | **0.722** | **6794** |

| pipeline | hybrid_lift_over_dense | rerank_lift_over_hybrid | full_lift_over_dense |
|---|---|---|---|
| numerical | 0.000 | 0.000 | 0.000 |

## Adjacent-noise chunk leakage (the actual signal)

Paper-level P@10 saturates because the fixture is small. The richer signal is **what fraction of top-10 chunks come from adjacent (non-known-relevant) papers**:

| query | dense_only | hybrid | hybrid+rerank |
|---|---|---|---|
| Q1 (Bridgeland) | **2/10** adjacent | 4/10 adjacent | 4/10 adjacent |
| Q2 (Kähler rigidity) | 0/10 adjacent | 0/10 adjacent | 1/10 adjacent |
| Q3 (differential strata) | 0/10 adjacent | 0/10 adjacent | 0/10 adjacent |

Q1 is the cleanest test (the corpus has multiple Bridgeland-adjacent papers). Dense-only wins it: 8/10 chunks from the known-relevant `2604.26204` set vs hybrid's 6/10 and hybrid+rerank's 6/10. **Rerank moved the adjacent paper `2604.28085` (lc pair semiample — different research program) into position 3, the worst kind of confusion for a `found@K` rule.**

## Why this happens at small corpus scale (theory)

The hybrid pipeline is built around three signals:

1. **BM25** rewards lexical token overlap. On 22 papers from one subfield, IDF is low across most query tokens — "stability", "surface", "moduli" appear in many papers. BM25 introduces noise rather than discrimination.
2. **RRF** blends BM25 ranks with ANN ranks. When BM25 is noisy, RRF degrades ANN's clean ranking instead of complementing it. This is the dominant effect on Q1.
3. **BGE-reranker-v2-m3** is a general-domain cross-encoder. On highly specialized math text where most candidates use similar vocabulary, its score distribution compresses; the top of the RRF list gets reshuffled but not improved.

At 100-paper or 200-paper scale, BM25's IDF starts discriminating and the rerank typically wins. **We have no data at that scale**, and `tests/eval/fixtures/queries.json` is still an empty stub.

## Latency findings (CPU)

| pipeline | mean total_ms | observations |
|---|---|---|
| dense_only | 83 | acceptable for interactive use; first-query is 150ms (warm cache after) |
| hybrid | 57 | faster than dense_only because BM25 is sub-3ms and ANN dominates anyway |
| hybrid+rerank | **6794** | 80× the dense path. CPU-bound on 50-candidate forward pass. |

The 6.8s/query rerank latency is operationally crippling at downstream's expected query volume (~30 claims per article × 100ms-budget-per-claim). With a GPU, the rerank cost would drop ~10x to ~0.7s — still significant. Without GPU, hybrid+rerank is not a default-on candidate.

## Implications for the handler-wiring pivot

### Decouples R1 (notebook scoping) from R2 (two-stage retrieval)

The spike argues for a **two-phase wiring plan**:

- **Phase 1 (≤ 1 week, high confidence):** wire the existing `filters` argument through `search_papers` to LanceDB's scalar predicate. Dense-only ANN + `paper_id IN (...)` filter satisfies R1 (notebook scoping) and is shown by the spike to ALREADY find the right papers at top-1 across all 3 queries.
- **Phase 2 (blocked on evidence):** wire BM25/RRF/rerank into the handler ONLY after a 100-paper eval fixture demonstrates positive lift on adjacent-noise queries. Per E07_S04's curation runbook this is a real-but-bounded deliverable (`.claude/docs/eval-curation.md`).

### Reranker is provisioned-but-not-default

The current `ARXMCP_ENABLE_RERANK=False` default is correct given the evidence. Per-query opt-in (`rerank=True` arg on `search_papers`) would let downstream pay the 6.8s/query cost only on the small subset of claims where dense-only's `found@K` rule failed.

### Score-discrimination is the unmeasured question downstream actually needs

Downstream's R3 (intra-notebook precision SLO) and R4 (rank-based `found`) both depend on **score distribution sharpness**, not on rank correctness. The spike measured rank quality (paper-level P@10) but did NOT measure: are rerank's `sigmoid(logit)` scores well-separated between top-1 and top-10? If yes, a rank-based `found = (top-1 score > 0.5)` rule is structurally sharp regardless of paper-level P@K. **This is the highest-value follow-up spike** and requires a populated query fixture with chunk-level relevance labels.

## What this spike does NOT answer

- Lift at 100-paper notebook scale (the actual downstream target).
- Chunk-level (not paper-level) precision and ordering.
- Rerank score distribution / discriminative power for a `found` rule.
- GPU latency profile.
- Whether sparse-fusion (BGE-M3 sparse + dense + rerank) would change the picture.
- Behavior of the `filters` argument when threaded through hybrid (BM25Phase already supports it; the handler doesn't).

## Recommended follow-ups (ranked)

1. **Build the 100-paper math.AG fixture** with chunk-level labels per E07_S04's `.claude/docs/eval-curation.md` runbook. This is the long-deferred work that gates every retrieval-quality claim arXMCP can make.
2. **Re-run this spike at 100-paper scale** with chunk-level relevance and a score-distribution metric (max-score, top-1-minus-top-5 gap).
3. **Phase-1 wiring milestone**: thread `filters={"paper_id":[...]}` through `search_papers`. Decouple from rerank decisions.
4. **Score-discrimination spike**: are rerank scores sharper than dense scores for `found`-rule construction?
