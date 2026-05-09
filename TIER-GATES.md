# Tier exit gates

This file is the single authoritative source for arXMCP's tier
promotion conditions. Every transition is a **machine-checkable**
statement: a single command whose exit code answers "are we ready to
promote?" Subjective criteria — "looks coherent", "demo transcript
seems good", "vibes-check" — do not appear here, by design.

This document supersedes the qualitative Tier-0 exit criterion
sketched in [`.claude/notes/09-feature-priorities.md`](.claude/notes/09-feature-priorities.md)
(line 36) and the planned `E01_S10` "vibes-check Claude Code
session transcript" milestone (which is not built — see the
"History" section at the bottom).

---

## The gates

| Transition | Gate condition (command) | Owning milestone |
|---|---|---|
| **Tier-0 → Tier-1** | `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70` passes on **ANN-only** retrieval (no BM25 hybrid, no reranker) | E05_S02 |
| **Tier-1 → Tier-2** | `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.80` passes with **BM25 hybrid + reranker** active (E07) | E07_S04 |
| **Tier-2 → Tier-3** | E08 caching telemetry healthy: cache hit rate ≥ 30 % on a 24-hour production traffic sample | E08 |
| **Tier-5 cutover** | 200 K paper backfill complete + drift watchdog stable (nDCG@5 within 5 % of baseline) | E11_S05 |

The Tier-3 → Tier-4 and Tier-4 → Tier-5 transitions do not have
quantitative gates here; they're scope cutovers (multi-category
ingest, full backfill) governed by their epics' acceptance
criteria.

**Reranker activation in E07 is conditional on nDCG@5 ≥ 0.80 after
BM25 hybrid is active.** If the hybrid pipeline alone reaches the
0.80 bar, the reranker can be deferred to Tier-2 polish work; if
hybrid + reranker together still misses 0.80, the retrieval
pipeline is debugged before Tier-2 begins. This conditional matters
because the reranker is the heaviest component of the query path
(GPU recommended); shipping it without measurable gain would be
overhead with no payoff.

---

## Tier-0 → Tier-1 gate (the active one)

### Command

```sh
pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70
```

Or via Make:

```sh
make eval
```

`make eval` is exactly the same invocation; it exists so contributors
don't have to memorize the pytest path.

### Expected output — pass

```
============================= test session starts ==============================
collected 1 item

tests/eval/test_retrieval_quality.py .                                   [100%]

============================== 1 passed in N.NNs ===============================
```

### Expected output — fail (below threshold)

```
============================= test session starts ==============================
collected 1 item

tests/eval/test_retrieval_quality.py F                                   [100%]

=================================== FAILURES ===================================
__________________________ test_retrieval_quality ______________________________
tests.eval.metrics.ThresholdNotMetError: nDCG@5 mean 0.62NN is below the
threshold 0.7000. Either retrieval quality regressed or the threshold needs
re-tuning. See var/arxmcp/ops/eval/results-*.jsonl for per-query detail.
============================== 1 failed in N.NNs ===============================
```

Per-query breakdown lives in
`var/arxmcp/ops/eval/results-<corpus_version>.jsonl` (one JSON line
per query). The aggregate is in
`var/arxmcp/ops/eval/aggregate-<corpus_version>.json`. The drift
watchdog (E11_S04) compares aggregates across corpus versions on a
schedule.

### Expected output — SKIP (NOT a pass)

```
============================= test session starts ==============================
collected 1 item

tests/eval/test_retrieval_quality.py s                                   [100%]

============================== 1 skipped in N.NNs ==============================
```

A SKIP outcome is **not** a pass for promotion. The retrieval-quality
test SKIPs when any of the following prerequisites is missing:

- The corpus marker (`var/arxmcp/index/lancedb/corpus-version.json`)
  does not exist — the seed corpus has not been ingested.
- The fixture (`tests/eval/fixtures/queries.json`) has zero entries
  — the 20-query curation pass has not happened.
- Server-side dependencies (`lancedb`, `transformers`) are not
  installed in the active environment.

A reviewer evaluating Tier-0 → Tier-1 readiness MUST verify the
test reports `1 passed`, not `1 skipped`. The skip exists so
`make test` stays green on a fresh checkout; it is not a promotion
signal.

### Prerequisites (operator checklist before declaring Tier-0 done)

1. The 20-query fixture is curated per
   [`docs/eval-curation.md`](docs/eval-curation.md). Validator passes:
   `python tools/validate_eval_fixtures.py` exits 0 with `OK:
   fixture validated in complete mode (queries=20, manifests=...)`.
2. The 50-paper seed corpus is ingested. Concretely:
   - `python tools/fetch_seed.py` has fetched every ID in
     `tools/seed-papers.txt`.
   - The chunker has run against every fetched paper (per-paper
     `chunk_manifest.json` exists under `var/arxmcp/corpus/chunks/`).
   - The embedder has produced `embedding_stmt` / `embedding_proof`
     vectors for every chunk.
   - `ingest.store.write_chunks(...)` has written the rows to LanceDB
     and produced `corpus-version.json`.
3. `make eval` reports `1 passed`. The aggregate file
   `var/arxmcp/ops/eval/aggregate-<v>.json` carries
   `"ndcg5_mean": >= 0.70`.

If any of these is incomplete, the gate is open. Do not promote.

---

## Tier-1 → Tier-2 gate

### Command

```sh
pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.80
```

### When this becomes the active gate

After E07 (hybrid retrieval epic) lands. The retrieval pipeline at
that point fuses ANN + BM25 results via Reciprocal Rank Fusion, then
re-ranks the top-k via the BGE-reranker. The eval test does not
change shape; only the threshold rises. The same fixture
(`tests/eval/fixtures/queries.json`) is used.

If the gate fails, the recommended debug path is:
1. Compare per-query JSONL across the Tier-0 baseline and the
   Tier-1 run (both stored in `var/arxmcp/ops/eval/`). Identify
   queries that regressed.
2. Verify BM25 + reranker are actually in the query path (E07's
   feature-flag should be ON).
3. Re-tune RRF weights or reranker threshold per E07's design.

---

## Tier-2 → Tier-3 gate

### Condition

Cache hit rate ≥ 30 % on a 24-hour production traffic sample.

### Where the metric comes from

The MCP server's caching telemetry (E08, Sonnet B) emits per-tool
hit/miss counts to `var/arxmcp/ops/cache-stats.jsonl`. A 24-hour
window is the smallest sample that's large enough to escape the
cold-start regime (the prompt cache fills in the first few hours)
and small enough to be representative of recent traffic. Lower bound
30 % comes from the multi-agent caching design note
(`07-multi-agent-caching.md`) — anything below that means the
cache-key discipline (BP1 byte-stability) has drifted.

The exact aggregation command lands in E08; this file is updated
when it does.

---

## Tier-5 cutover

### Conditions (both must hold)

1. **Backfill complete:** the full 200 K paper corpus is ingested
   to a single LanceDB table.
2. **Drift watchdog stable:** the latest scheduled
   nDCG@5 measurement (per E11_S04's drift watchdog) is within 5 %
   of the previous baseline. "Within 5 %" means
   `|aggregate.ndcg5_mean - prior.ndcg5_mean| / prior.ndcg5_mean
   <= 0.05`.

### Why the cutover is a gate, not a milestone close

Tier-5 is the production regime; the cutover is an irreversible
operational change (single-tenant → multi-host eligibility, larger
LanceDB datasets, longer index rebuilds). Asserting both conditions
at the boundary keeps a half-finished backfill from accidentally
becoming the production state.

---

## History

E01_S10 was originally specified as a manual "vibes-check" Claude
Code session transcript demonstrating end-to-end retrieval. That
qualitative criterion was retired in favor of the quantitative
nDCG@5 gate when E05 was scoped. The roadmap entry at
`.claude/roadmap/E01-shipped.md` (search for "E01_S10") records the
supersession formally; this document is the active replacement.

The 0.70 / 0.80 threshold values come from the project's design
constitution ([`.claude/notes/09-feature-priorities.md`](.claude/notes/09-feature-priorities.md)
§ "Tier 0 exit criterion" and the E05 epic header in
[`.claude/roadmap/E05-eval-harness.md`](.claude/roadmap/E05-eval-harness.md)).

---

## Owner approval

Per the E05_S03 risk note, this document **must be reviewed and
approved by the project owner before Tier-1 work begins**. Owner
sign-off is recorded in the commit-trailer of the `feat(eval)`
commit that lands this file.
