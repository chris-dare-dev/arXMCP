# Spike: handler-wiring rerank lift (intra-notebook adjacent-noise precision)

**Date:** 2026-05-20
**Audience:** downstream `/proof-verify` pivot planning + arXMCP roadmap.
**Question:** Does lifting the hybrid `BM25 → ANN+RRF → BGE-reranker-v2-m3`
pipeline (already shipped as code, never wired into `search_papers`) into
the live MCP handler improve **intra-notebook** precision on
topologically-adjacent queries, vs the current dense-only ANN path?

## Verdict format

```
Verdict: YES   — rerank lifts paper-level precision@10 by ≥ 0.30 absolute on hard
                 pointed sub-questions (Spike-A pass criterion).
Verdict: NO    — lift < 0.10, non-monotonic, or worse than dense-only.
Verdict: UNCERTAIN — lift in [0.10, 0.30), or fixture too small to discriminate.
```

A YES verdict justifies the handler-wiring milestone. NO collapses the
pivot premise and forces a redesign (sparse fusion, larger corpus
ingest, or a different retrieval architecture). UNCERTAIN requires a
larger fixture.

## Fixture

The 22-paper math.AG corpus already in `var/arxmcp/index/lancedb-staging/`
(`corpus_version=101`, ingested 2026-05-20). All 22 papers are April-2026
math.AG / math.AC submissions; topical density is exactly the
adjacent-noise regime downstream is fighting.

Three pointed sub-questions, each with a hand-identified **known-relevant
paper set** drawn from the corpus enumeration (paper-level, not
chunk-level — adequate for precision@K signal at this corpus scale):

### Q1 — "Bridgeland stability conditions on Enriques surfaces and elliptic surfaces"
- **Known-relevant papers (2):** `2604.26204`, `2604.26208`
  - 2604.26204: walls and chambers for (f,G,H)-semistability on elliptic K3 / Enriques surfaces
  - 2604.26208: semistable sheaves on elliptic ruled surfaces
- **Adjacent (must NOT be top-ranked):** `2604.27890` (CY degenerations), `2604.28085` (lc pairs, semiample), `2604.27634` (Białynicki-Birula cells on G_m-varieties)

### Q2 — "Rigidity of compact Kähler manifolds"
- **Known-relevant papers (3):** `2604.26329`, `2604.26425`, `2604.27484`
  - 2604.26329: globally rigid Kähler manifolds
  - 2604.26425: compact Kähler contact manifolds
  - 2604.27484: klt pair stability (deformation context)
- **Adjacent:** `2604.27890`, `2604.28085`, `2604.26204`

### Q3 — "Strata of differentials and translation surfaces, primitive components"
- **Known-relevant papers (2):** `2604.26177`, `2604.26193`
  - 2604.26177: primitive nonhyperelliptic component of Ω^k M_g(κ)
  - 2604.26193: genus-g cover of P^1 totally ramified at two points
- **Adjacent:** `2604.26659` (group actions on C^n), `2604.27246` (camera arrangements)

## Pipelines compared

| ID | Configuration | Where it runs today |
|---|---|---|
| `dense_only` | live `search_papers` handler: single ANN call over `embedding_stmt`, top-10 | Currently the only path users hit |
| `hybrid` | BM25 top-200 → ANN+RRF top-50 → identity (no rerank), final top-10 | Lives in `tests/eval/test_retrieval_quality.py::_run_hybrid_against_corpus` with `rerank_enabled=False` |
| `hybrid+rerank` | Same as `hybrid` + Phase-3 BGE-reranker-v2-m3 cross-encoder, top-10 by `sigmoid(logit)` | Same helper, `rerank_enabled=True` |

All three pipelines hit the SAME corpus (`var/arxmcp/index/lancedb-staging`,
`corpus_version=101`). The dense-only call goes through the live HTTP
handler; the two hybrid configurations are driven directly via the
eval helper to avoid having to wire the handler first (that wiring is
what the spike is informing).

## Metric

**Paper-level precision@10.** For each query, count the unique `paper_id`s
appearing in the top-10 chunks. Score = `|{p in top-10} ∩ known_relevant| / |known_relevant|`,
capped at 1.0. Aggregate across the 3 queries via mean.

Why paper-level not chunk-level:
- The fixture is small (22 papers); chunk-level labels would require
  hand-reading ~200 chunks. Paper-level identification is verifiable from
  the corpus enumeration.
- Matches downstream's actual SLO: they need the right PAPERS surfaced
  so their per-claim verifier can read relevant chunks; chunk ordering
  inside a relevant paper is a secondary signal.

## Out of scope

- Curating a 20-query fixture for `tests/eval/fixtures/queries.json`
  (that's the E07_S04 deliverable; this spike is informing whether
  to invest in it).
- Wiring the handler (the spike is what informs whether to do that).
- Sparse-fusion lift on top of rerank (deferred to a follow-up spike if
  rerank's lift is positive but marginal).
- Latency measurement (deferred to a separate small spike if Verdict=YES).
