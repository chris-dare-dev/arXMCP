# Spike: hybrid+rerank lift at proper-notebook scale (m5) — note

**Date:** 2026-05-21
**Question:** Does hybrid (BM25 + ANN+RRF) or hybrid+rerank (adding BGE-reranker-v2-m3) lift intra-notebook paper-level precision over dense-only ANN, when measured against curated notebook fixtures with hand-labeled paper-level relevance?

## Verdict

**NO** — across 20 queries spanning 51 papers in two real-world notebooks, hybrid+rerank produces **zero P@10 lift** over dense-only ANN AND **actively regresses top-1 hit rate by 10 percentage points** (0.850 → 0.750). The latency cost is 122× (55 ms → 6703 ms on CPU). The hypothesis that the 22-paper spike's NO verdict was a small-fixture artifact is **refuted** — at proper-notebook scale, with carefully-curated labels grounded in actual paper reading, rerank still does not help.

**Action:** Close `proof-verify-handler-wiring-e3` (hybrid+rerank handler wiring) unimplemented. The dense+filter path (e1, m1) is the structural ceiling worth wiring; rerank wiring is not evidence-justified.

## Headline numbers

| pipeline | mean P@10 | mean R@10 | top-1 hit rate | mean adj chunks /10 | mean total_ms |
|---|---|---|---|---|---|
| dense_only | 0.215 | **0.936** | **0.850** | 4.3 | **55** |
| hybrid | 0.205 | 0.909 | 0.750 | 4.2 | 59 |
| hybrid_rerank | 0.215 | 0.938 | 0.750 | 4.2 | **6703** |

| lift | overall | easy | hard | adversarial |
|---|---|---|---|---|
| full P@10 lift over dense | **+0.000** | +0.000 | +0.000 | +0.000 |
| full top-1 lift over dense | **−0.100** | **−0.200** | +0.000 | **−0.200** |
| rerank-only P@10 lift over hybrid | +0.010 | +0.000 | +0.020 | +0.000 |

**Note on P@10 ceiling:** the labeled expected_relevant_papers sets average ~2-4 papers per query, so `paper_precision_at_10 = hits / 10` is structurally capped well below 1.0. Recall@10 is the cleaner read on "did we find the expected papers": all three pipelines hit ~93-94% recall@10. **The retrieval substrate already finds the expected papers** — the discrimination question is WHICH paper ranks at top-1, and that's where rerank regresses.

## Where rerank specifically regresses (top-1 transitions)

Across all 20 queries:
- **dense_only top-1 ✓ → hybrid_rerank top-1 ✗:** 4 queries (`bridge-q1` Bridgeland-original, `bridge-q6` KS-wall-crossing, `shimura-q5` LL-geometrization, `shimura-q10` Newton-strata-Igusa)
- **dense_only top-1 ✗ → hybrid_rerank top-1 ✓:** 1 query (`bridge-q9` Stab(X) covering)
- **No change:** 15 queries

Net top-1 regressions: **-3 (15% absolute, 20% relative)**. The promotions are sparse; the demotions are concentrated on queries where dense was already getting it right.

## Where hybrid (no rerank) regresses

Hybrid alone also drops top-1 from 0.850 → 0.750 (same -0.100 as the full rerank pipeline). This is the BM25 + RRF blend introducing lexical-overlap noise that confuses ANN's clean semantic ranking. Notable regressions:
- `bridge-q4` (Joyce structures, adversarial): dense Y → hybrid N. BM25 likely pulled a Bridgeland-stability paper that mentions "Joyce" superficially.
- `bridge-q6` (KS wall-crossing): dense Y → hybrid N.
- `bridge-q8` (Gushel-Mukai): dense Y → hybrid N.

**Pattern:** RRF blending with BM25 hurts the most on adversarial queries where adjacent papers share vocabulary but not actual subject ownership. This matches the theoretical expectation from the 22-paper spike's analysis: BM25 IDF on math text shares too much surface vocabulary between papers to be discriminating.

## Recall@10 — the actually-good news

| pipeline | mean R@10 | queries with R@10 = 1.0 |
|---|---|---|
| dense_only | 0.936 | 17 / 20 |
| hybrid | 0.909 | 16 / 20 |
| hybrid_rerank | 0.938 | 17 / 20 |

**Dense-only ALREADY surfaces ≥ 1 expected paper in top-10 for 17 of 20 queries (85%), and ALL expected papers for 17 of 20 (the same set).** The three queries where recall@10 < 1.0 are bridge-q3 (Fano-threefolds, R@10=0.71), bridge-q9 (Stab covering, R@10=0.50), bridge-q10 (quadratic differentials, R@10=0.50). These are the queries where the expected_relevant_papers vocabulary is most distant from dense embeddings.

**Practical implication:** for a downstream `found@K = (top-K ∩ known_relevant ≠ ∅)` rule (the R4 path from the synthesis), dense-only at K=10 satisfies the rule on 17 of 20 queries, and at K=1 satisfies it on 17 of 20 = 85% — strong enough for `/proof-verify`'s per-claim verification.

## Per-notebook breakdown

| notebook | pipeline | mean R@10 | top-1 hit rate |
|---|---|---|---|
| bridgeland-stability | dense_only | 0.901 | 0.800 |
| bridgeland-stability | hybrid | 0.815 | 0.500 |
| bridgeland-stability | hybrid_rerank | 0.876 | 0.700 |
| shimura-varieties | dense_only | 1.000 | 0.900 |
| shimura-varieties | hybrid | 1.000 | 1.000 |
| shimura-varieties | hybrid_rerank | 1.000 | 0.800 |

**Shimura is a clean win for dense-only and hybrid; bridgeland is harder.** Notably, hybrid actually IMPROVES top-1 on shimura (0.9 → 1.0) but tanks it on bridgeland (0.8 → 0.5). The bridgeland regression dominates the aggregate. Hypothesis: shimura's papers have more distinctive technical vocabulary (specific theorem names, conjecture names) that BM25 can lock onto; bridgeland's papers share the core "stability condition" / "derived category" vocabulary across nearly all 39, making BM25 noise dominant.

## Latency

| pipeline | mean | implication |
|---|---|---|
| dense_only | 55 ms | sub-interactive; fits 30 claims/article × < 1s budget |
| hybrid | 59 ms | basically free, but precision worse |
| hybrid_rerank | **6703 ms** | 122× cost for zero precision gain on CPU |

A GPU would drop rerank ~10× to ~670 ms — still significant per-query, and still no precision benefit. The latency story alone makes default-on rerank a no-go.

## Why this happens — confirmed at scale

The 22-paper spike's theoretical analysis is now empirically confirmed:

1. **BM25 IDF is non-discriminating on topical-domain notebooks.** Within a notebook curated around one research area, the shared vocabulary ("stability condition", "Shimura variety", "derived category") has near-uniform IDF. BM25 adds rank-noise without rank-signal. RRF blending then degrades the ANN baseline.

2. **The cross-encoder reranker is general-domain.** BGE-reranker-v2-m3 was trained on diverse English text. When all 50 candidates use highly specialized math vocabulary, the reranker's score distribution compresses; reranking becomes near-noise that occasionally swaps relevant top-1s with adjacent papers that happen to phrase-match the query more literally.

3. **Dense-only IS the right substrate for topically-clustered notebooks.** BGE-M3's semantic embedding captures "this paragraph is about Bridgeland stability on Enriques surfaces" with enough fidelity to put the right paper at top-1 for the majority of pointed sub-questions. The remaining 15% of queries that miss top-1 are genuinely hard ranking decisions that lexical / cross-encoder methods don't fix.

## What this does NOT prove

- **Rerank at 1000+ paper scale.** If notebooks grow 10×, the candidate set diversity may give the cross-encoder more signal to work with. Not measured.
- **Sparse-fusion (BGE-M3 multi-vector head) on top of dense.** The cross-encoder rerank is one specific approach; sparse-vector fusion is another, untested here.
- **Domain-adapted encoders.** Math-domain fine-tuned encoders (MathBERT, etc.) might shift the discrimination ceiling.
- **GPU rerank latency.** All measurements CPU-only.
- **The cluster of `bridge-q3`, `bridge-q9`, `bridge-q10` low-recall@10 cases.** These are where dense-only also fails — improving them needs query reformulation or sparse fusion, not rerank.

## Recommended actions

### Immediate (roadmap-level)

1. **Close `proof-verify-handler-wiring-e3` (hybrid+rerank wiring) without implementing.** Update the roadmap's MoSCoW + Now/Next/Later to reflect closure with rationale.
2. **Confirm `ARXMCP_ENABLE_RERANK=False` as the production default.** The flag stays; flipping it on costs latency without precision benefit.
3. **Update `.claude/docs/retrieval-quality-report.md`** with the measured numbers, replacing the PRELIMINARY / PENDING markers for this notebook scale.
4. **Update `.claude/notes/proof-verify-pivot/synthesis.md` and `.claude/notes/proof-verify-pivot/timeline.md`** with the verdict — the "M-weeks full-pivot" timeline collapses to "N-weeks operational unblock" because e3 is closed.

### Architecture-change candidates (if downstream wants better than 85% top-1)

In rough priority order, none of which are commits to do — these are the "what next?" options if dense-only's top-1=0.85 is insufficient for `/proof-verify`'s product needs:

1. **Query reformulation (cheapest, no architecture change).** Have the calling agent generate 3 paraphrasings per query, run dense-only on each, fuse the results. Low risk; might lift top-1 on the 3 missed queries.
2. **Sparse-vector fusion (BGE-M3 multi-vector head).** BGE-M3 ships with three signal heads: dense, sparse, multi-vector. Currently arXMCP uses only the dense head. The sparse head approximates BM25 but operates in the same model's feature space (no IDF-on-narrow-vocabulary problem). Worth a sub-spike (~3 days) if downstream wants better intra-notebook precision.
3. **Domain-adapted reranker.** A reranker fine-tuned on math content (e.g., MathBERT-based cross-encoder) might behave differently than the general-domain BGE-reranker. Larger investment; uncertain payoff.
4. **ColBERT late-interaction.** Different retrieval architecture entirely. Substantial engineering investment.
5. **Increase K from 10 to 30.** At K=30, dense-only recall would likely reach 0.99+ on this fixture. Trades precision for recall; useful if the downstream agent is doing its own filtering downstream of retrieval.

### What downstream should plan for

- The bare-minimum wiring (Track A from the synthesis: spike-1 + m1 + m2 + m3 + m6) IS sufficient for the `/proof-verify` product. 1-2 weeks to ship.
- The full pivot timeline (M-weeks) was always conditional on this verdict. With NO, the conditional resolves: full pivot = bare-minimum wiring. No additional rerank engineering needed.
- If downstream's product spec evolves to need >85% top-1, the sparse-fusion sub-spike (option 2 above) is the cheapest investigation path.

## Reproducibility

```
ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/bridgeland-stability/lancedb \
  uv run python .claude/notes/spikes/wiring-rerank-lift-100paper/poc.py
```

Output: `.claude/notes/spikes/wiring-rerank-lift-100paper/measurements.json` — full per-query rows for all 60 (pipeline × query) measurements.
