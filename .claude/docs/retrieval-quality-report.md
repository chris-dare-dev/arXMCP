# Retrieval-quality report — E07_S04

End-to-end nDCG@5 + latency findings for the 3-phase hybrid retrieval
pipeline (BM25 → ANN+RRF → optional cross-encoder rerank). This
document is the canonical record consulted by E11_S05's 200K-paper
scale-cutover go/no-go decision.

**Status:** MEASURED at notebook scale (51 papers, 20 hand-labeled queries)
as of 2026-05-21. Original E07_S04 20-query global fixture remains empty;
this report uses the m5 spike's per-notebook fixtures instead, which
better match downstream's actual use case (intra-notebook precision
inside a curated topical notebook, not global precision across mixed
subjects). See `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md`
for the full per-query breakdown.

## Headline finding (2026-05-21)

| pipeline | mean R@10 | top-1 hit rate | mean latency (CPU) |
|---|---|---|---|
| dense-only | 0.936 | **0.850** | **55 ms** |
| hybrid (BM25 + ANN+RRF) | 0.909 | 0.750 | 59 ms |
| hybrid + rerank | 0.938 | 0.750 | 6703 ms |

**Hybrid+rerank produces zero precision lift over dense-only and actively
regresses top-1 by 10 percentage points at 122× latency cost.**

Conclusion: `ARXMCP_ENABLE_RERANK` stays `False` as the production default.
The `proof-verify-handler-wiring-e3` epic (wire the hybrid pipeline into
`server/handlers/search.py`) is closed unimplemented.



## TL;DR (preliminary)

| Question | Answer | Evidence |
|---|---|---|
| Is `nDCG@5 ≥ 0.80` met by the hybrid pipeline (no rerank)? | **PENDING** — `tests/eval/fixtures/queries.json` is an empty stub | E05_S02 shipped the curation runbook (`docs/eval-curation.md`); the 20-query corpus has not yet been hand-labeled |
| Does Phase-3 cross-encoder reranking move the needle? | **PENDING** — same blocker | Will be answered by running `pytest tests/eval/test_retrieval_quality.py --hybrid --rerank --ndcg-min=0.80` after curation |
| Is the latency p95 ≤ 2 s at k=10? | **HARNESS LANDED** — assertion fires when the gate runs against a populated fixture | `LATENCY_P95_MAX_SECONDS = 2.0` in `tests/eval/test_retrieval_quality.py` |
| What is `ARXMCP_ENABLE_RERANK`'s production value? | **`False`** (unchanged) until the eval proves the reranker is required | Per E07_S03 `server/retrieval/rerank.py:13-16` opt-in protocol |

The Tier-1 → Tier-2 exit-gate machinery is in place. The gate is
flipped by running the hybrid eval against a populated corpus +
curated query fixture and recording the results in this document.

## Pipeline under test

The eval harness (`tests/eval/test_retrieval_quality.py`) accepts
three flags:

| flag | effect |
|---|---|
| `--ndcg-min=<float>` | Asserted threshold on `ndcg5_mean`. Default 0.70 (Tier-0). E07_S04 raises to 0.80 (Tier-1 → Tier-2). |
| `--hybrid` | Switches from dense-only ANN to BM25 → ANN+RRF. Without this, the harness runs the E05_S02 dense-only baseline. |
| `--rerank` | Adds Phase-3 BGE-reranker-v2-m3. Requires `--hybrid`; raises `pytest.UsageError` otherwise. ALSO requires `ARXMCP_RUN_REAL_BGE_RERANKER=1` env (the model is ~2.3 GB). |

The Tier-1 invocation is:

    ARXMCP_RUN_REAL_BGE_RERANKER=1 \
        pytest tests/eval/test_retrieval_quality.py \
        --hybrid --rerank --ndcg-min=0.80

## Per-phase nDCG@5 lift (PENDING)

The report below will be populated when the gate runs against a
populated fixture. Each row is a pipeline configuration; the score
is the mean nDCG@5 over the 20-query hand-labeled set.

| pipeline | nDCG@5 (mean) | Δ vs prev row | runs |
|---|---|---|---|
| dense-only (Tier-0 baseline) | _PENDING_ | — | `pytest --ndcg-min=0.70` |
| hybrid (BM25 + ANN+RRF) | _PENDING_ | _PENDING_ | `pytest --hybrid` |
| hybrid + rerank | _PENDING_ | _PENDING_ | `pytest --hybrid --rerank` |

**Expected pattern** (informed by Cormack 2009 and BGE-reranker
benchmarks): the hybrid step typically lifts nDCG@5 by 0.05–0.15 over
dense-only on small corpora; the reranker adds another 0.05–0.10.
Whether the lift is sufficient to cross 0.80 depends on the seed
corpus; this report records the actual measured deltas.

**Out-of-scope sanity check.** The reranker score is `sigmoid(logit)`
in `[0, 1]`, while the dense-only and RRF scores have different
ranges (cosine and `1/(k+rank)` respectively). nDCG consumes only
RANKS, not scores, so cross-pipeline comparisons of the metric are
valid (per E07_S03 critique F5 closure). DO NOT compare raw
`score` values across pipelines.

## Latency profile (PENDING)

Per-phase p50 / p95 latency at `k=10` against the seed corpus, in
milliseconds. The eval harness records `bm25_ms`, `ann_ms`,
`rerank_ms`, and `total_ms` per query into
`var/arxmcp/ops/eval/results-<v>.jsonl`; aggregates land in
`var/arxmcp/ops/eval/aggregate-<v>.json`.

| phase | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|
| Phase 1 — BM25 | _PENDING_ | _PENDING_ | _PENDING_ |
| Phase 2 — ANN+RRF | _PENDING_ | _PENDING_ | _PENDING_ |
| Phase 3 — Rerank | _PENDING_ | _PENDING_ | _PENDING_ |
| Total | _PENDING_ | _PENDING_ | _PENDING_ |

**AC #4 budget:** `total_ms` p95 must be ≤ 2,000 ms (2 s) at k=10
on the seed corpus. The eval test asserts this when `--hybrid` is
passed.

## Reranker-necessity decision

The brief: `ARXMCP_ENABLE_RERANK` is set to its production value
based on these findings.

Decision protocol (D7 from research-synthesis.md):

1. Run `pytest ... --hybrid --ndcg-min=0.80` (rerank OFF).
2. **If pass** → leave `enable_rerank=False` in `server/config.py`.
3. **If fail**, run `pytest ... --hybrid --rerank --ndcg-min=0.80`.
4. **If pass with rerank** → flip `enable_rerank` default to `True`
   in a follow-up commit; update this report.
5. **If both fail** → DO NOT lower the threshold; debug the
   pipeline (per `TIER-GATES.md`'s "the retrieval pipeline is
   debugged before Tier-2 begins").

**Current production setting:** `enable_rerank: bool = False`
(unchanged from E07_S03).

## How to run the gate

Prerequisites:

1. Ingest a seed corpus into LanceDB (`var/arxmcp/index/lancedb/`)
   and ensure `corpus-version.json` is present (E04_S03 marker).
2. Build the BM25 artifact: `python -m ingest.bm25_indexer …`
   (E04_S04). The phase auto-builds on first query, so this can be
   skipped if the operator doesn't mind the startup latency.
3. Curate the 20-query fixture per `docs/eval-curation.md` and
   write to `tests/eval/fixtures/queries.json`.
4. (For `--rerank` only) Set `ARXMCP_RUN_REAL_BGE_RERANKER=1` and
   ensure the BGE-reranker-v2-m3 weights are downloadable from
   HuggingFace (or pre-cached at `~/.cache/huggingface/`).

Then:

    # Hybrid only (no rerank).
    pytest tests/eval/test_retrieval_quality.py \
        --hybrid --ndcg-min=0.80

    # Full 3-phase pipeline (with rerank).
    ARXMCP_RUN_REAL_BGE_RERANKER=1 \
        pytest tests/eval/test_retrieval_quality.py \
        --hybrid --rerank --ndcg-min=0.80

The aggregate JSON at `var/arxmcp/ops/eval/aggregate-<v>.json`
carries the latency percentiles and pipeline identity. After each
run, copy the per-phase nDCG@5 + latency tables above into this
file and either confirm `ARXMCP_ENABLE_RERANK=False` or flip it.

### Cold-start cost per invocation

Every `pytest` invocation builds a fresh `Resources` instance:
LanceDB open + BGE-M3 warm + BM25 build + (with `--rerank`) ~2.3 GB
reranker download/load. For an operator iterating on `--ndcg-min`
thresholds (e.g. 0.78 → 0.80 → 0.82 to chart the sensitivity
curve), each invocation pays this full cold-start cost.

Practical timing on commodity hardware:
- Without `--rerank`: ~10–30 seconds per invocation (BGE-M3 warm
  dominates).
- With `--rerank` (cold model cache): ~2–5 minutes (model download
  + warmup).
- With `--rerank` (warm cache): ~30–60 seconds (model load).

Budget operator time accordingly. A future improvement (see
"Open follow-ups" below) would session-scope `Resources` so
multi-threshold runs share one startup.

## Open follow-ups

- **Curate the 20-query fixture** (separate deliverable, blocks the
  gate run).
- **Lift the orchestrator into `server/handlers/search.py`** (E08
  agent runtime, when the live server actually serves hybrid
  retrieval to MCP clients). The eval helper at
  `tests/eval/test_retrieval_quality.py:_run_hybrid_against_corpus`
  is the reference orchestration path.
- **`TIER-GATES.md` Tier-1 → Tier-2 row** — update to mention the
  `--hybrid` and `--rerank` flag surface (low-priority doc fix).

## Related files

- `tests/eval/test_retrieval_quality.py` — the harness.
- `tests/eval/metrics.py` — `ndcg_at_k`, `recall_at_k`,
  `assert_threshold`, `ThresholdNotMetError`.
- `tests/eval/fixtures/queries.json` — the 20-query fixture
  (currently empty stub).
- `server/retrieval/{bm25,ann,rerank,rrf}.py` — the three phases +
  RRF utility.
- `server/config.py` — `enable_rerank: bool = False`.
- `.claude/notes/05-storage-and-indexing.md:312-331` — the canonical
  3-phase contract.
- `TIER-GATES.md` — the Tier-1 → Tier-2 promotion gate.
