# E05 — Eval Harness (NEW)

**Epic dependencies:** E02 (stable, content-addressable `chunk_id`s via E02_S04 and fixture suite via E02_S05), E03 (embeddings written to LanceDB), E04 (LanceDB table queryable via ANN, corpus_version pinned).

**Goal:** Define and enforce the quantitative exit gate for Tier-0. The eval harness is not a nice-to-have quality metric — it is the *definition* of done for the Tier-0 vertical slice. Without a passing harness run (nDCG@5 ≥ 0.70 ANN-only), no Tier-1 work begins. With a passing run at ≥ 0.80 after hybrid + reranker land (E07, Sonnet B), Tier-1 is declared complete and Tier-2 begins. The harness also provides the drift-detection baseline for production monitoring (E11_S04).

**Effort:** ~1 week calendar (M+M+S across three milestones).

**References:** `09-feature-priorities.md` § Tier 0 exit criterion (nDCG@5 threshold), `05-storage-and-indexing.md` § Retrieval quality metrics (nDCG@5, Recall@10 definitions), `08-security-observability-ops.md` § Observability (drift detection).

---

### E05_S01 — `tests/eval/fixtures/queries.json` — 20 hand-labeled query triples

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E02_S04, E02_S05

**Description.** The eval fixture file contains 20 `(query, chunk_id, relevance)` triples curated by a human against the 50-paper seed corpus. Each triple asserts that for a given natural-language query string, a specific chunk (identified by its content-addressable `chunk_id` from E02_S04) is relevant to that query, with a graded relevance score.

**Fixture schema (`tests/eval/fixtures/queries.json`):**
```json
{
  "schema_version": "1.0",
  "chunker_version": "v1.0",
  "created_at": "2026-05-06",
  "queries": [
    {
      "query_id": "q01",
      "query_text": "Riemann-Roch theorem for algebraic curves",
      "relevant_chunks": [
        {"chunk_id": "arxiv:2301.00001:abc123def456789a", "relevance": 3},
        {"chunk_id": "arxiv:2301.00002:ff1122334455667a", "relevance": 1}
      ]
    }
  ]
}
```

Relevance is graded 0–3: 3 = highly relevant (the chunk is the primary answer), 2 = relevant (the chunk directly addresses the query), 1 = partially relevant (useful context), 0 = not relevant (not in the fixture; absent chunks are assumed grade 0). At least one grade-3 chunk must exist per query.

The milestone ships when `queries.json` is committed and validated. Validation is automated: a helper script `tools/validate_eval_fixtures.py` checks that every `chunk_id` in the fixture exists in the chunker output (by reading `chunk_manifest.json` files from E02_S04), that `chunker_version` matches the current chunker, and that query IDs are unique. This script is run as part of `make test`.

**Important:** the user owns curation. The milestone is blocked on a human reviewing chunker output for 50 papers and writing 20 query-relevance pairs. The milestone ships when the JSON is committed and validated — the implementer cannot automate the curation itself (that would make the eval circular). The fixture curation process is documented in `docs/eval-curation.md`.

The 20 queries should span the math.AG domain: theorems (Riemann-Roch, Grothendieck-Riemann-Roch, Serre duality), constructions (Picard group, derived category of coherent sheaves, Hilbert scheme), and proof techniques (spectral sequences, resolution of singularities). Diverse query phrasing (formal, informal, fragment-style) improves harness coverage.

**Deliverables.**
- `tests/eval/fixtures/queries.json` — 20 hand-labeled query triples
- `tools/validate_eval_fixtures.py` — validation script
- `docs/eval-curation.md` — curation process documentation
- `make test` integration: runs `python tools/validate_eval_fixtures.py` as part of the test suite

**Acceptance criteria.**
- [ ] `queries.json` contains exactly 20 query entries.
- [ ] Each query has at least one grade-3 `chunk_id`.
- [ ] Every `chunk_id` in the fixture exists in the chunker output (verified by `validate_eval_fixtures.py`).
- [ ] `chunker_version` in the fixture header matches `"v1.0"`.
- [ ] `validate_eval_fixtures.py` exits 0 on a clean checkout with a valid corpus.
- [ ] `validate_eval_fixtures.py` exits non-zero if a `chunk_id` in the fixture does not exist in any `chunk_manifest.json`.
- [ ] At least 5 queries reference `kind="stmt"` chunks and at least 5 reference `kind="proof"` chunks.

**Out of scope.** Running the retrieval evaluation (E05_S02). Automated query generation (an LLM-generated fixture would make the eval circular; all curation is manual). Queries for math.NT, hep-th, math-ph categories (Tier 1+ multi-category ingest).

**Risk notes.**
- The `chunk_id` stability guarantee from E02_S04 and E02_S05 is what makes this fixture viable. If `chunk_id`s are not reproducible, the fixture becomes stale on every chunker run and curation effort is wasted. `validate_eval_fixtures.py` catching stale IDs is the safety net.
- The fixture should be updated in lockstep with any `chunker_version` bump. `docs/eval-curation.md` must document this update procedure so it is not skipped.

**Labels.** `area:eval`, `kind:data`, `tier:0`.

---

### E05_S02 — `tests/eval/test_retrieval_quality.py` — nDCG@5 + Recall@10 measurement

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E05_S01, E03_S01, E04_S01, E04_S02

**Description.** The retrieval quality test reads `queries.json`, issues each query as an ANN search against the LanceDB `chunks` table (pinned to the current corpus version via `open_chunks_table`), retrieves the top-10 results from `embedding_stmt` and `embedding_proof` (merged and deduped by score), and scores the ranked list against the ground-truth relevance grades using nDCG@5 and Recall@10.

**Metric definitions:**
- **nDCG@5**: Normalized Discounted Cumulative Gain at rank 5, using graded relevance (0–3). `DCG@5 = Σ (rel_i / log2(i+1))` for i=1..5, normalized by ideal DCG@5.
- **Recall@10**: fraction of grade-3 ("highly relevant") chunks for each query that appear in the top-10 ANN results, averaged over all queries.

The test writes per-query results to `var/arxmcp/ops/eval/results-<corpus_version>.jsonl` (one JSON line per query: `{query_id, query_text, retrieved_chunk_ids, ndcg5, recall10}`). It also writes an aggregate metric file `var/arxmcp/ops/eval/aggregate-<corpus_version>.json` with `{corpus_version, ndcg5_mean, recall10_mean, query_count, timestamp}`. These files are the drift-detection baseline referenced by E11_S04.

The test fails if `ndcg5_mean` drops below the threshold passed via `pytest --ndcg-min=0.70` (default 0.70 for Tier-0 ANN-only). This pytest argument is implemented as a custom option in `conftest.py`. The threshold can be raised to 0.80 when testing the full hybrid + reranker pipeline (E07, Sonnet B) — this is the Tier-1 exit criterion.

ANN search uses both `embedding_stmt` and `embedding_proof` columns: two ANN queries are issued (one per column), top-k results are merged and sorted by score, deduped by `chunk_id`, and the top 10 are taken. The query embedding uses `encode_query` from `server/query_encoder.py` (E03_S03) — the same model and same SHA as index time.

**Deliverables.**
- `tests/eval/test_retrieval_quality.py` — pytest test using `--ndcg-min` flag
- `tests/conftest.py` — `--ndcg-min` option registration
- `var/arxmcp/ops/eval/results-<corpus_version>.jsonl` — per-query results (written, not committed)
- `var/arxmcp/ops/eval/aggregate-<corpus_version>.json` — aggregate metrics (written, not committed)
- Metric computation utilities in `tests/eval/metrics.py` (nDCG, Recall)

**Acceptance criteria.**
- [ ] `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70` passes on the 50-paper seed corpus after E03 and E04 are complete.
- [ ] `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.50` fails if nDCG@5 is below 0.50 (threshold enforcement verified in test).
- [ ] Per-query JSONL and aggregate JSON are written to `var/arxmcp/ops/eval/` on each run.
- [ ] ANN search uses the pinned corpus version from `read_corpus_version()` (E04_S03).
- [ ] Both `embedding_stmt` and `embedding_proof` columns are searched; results are merged.
- [ ] `tests/eval/metrics.py` contains standalone `ndcg_at_k` and `recall_at_k` functions with their own unit tests.
- [ ] Test runtime under 120 seconds for 20 queries against 50-paper corpus.

**Out of scope.** BM25 hybrid retrieval (E07, Sonnet B). Reranker (E07, Sonnet B). Drift detection alerting and CI scheduling (E11_S04 — this milestone writes the baseline; E11_S04 compares against it on a schedule). Queries beyond math.AG (Tier 1+).

**Risk notes.**
- **Closes MEDIUM: drift detection (initial implementation).** This milestone produces the baseline metric files that E11_S04's drift watchdog compares against. The initial implementation is a one-shot test; E11_S04 productionizes it as a scheduled job. The file naming convention (`aggregate-<corpus_version>.json`) is forward-compatible with E11's multi-version comparison logic.
- nDCG@5 ≥ 0.70 for ANN-only (no BM25, no reranker) on a 50-paper math-domain corpus is an ambitious threshold. If the corpus is too small to generate challenging queries, the threshold may be trivially met; if chunking quality is poor, it may not be met at all. The fixture curation (E05_S01) should include at least 5 queries where the relevant chunk is NOT the highest cosine-similarity result, to ensure the threshold is meaningful.

**Labels.** `area:eval`, `kind:test`, `tier:0`.

---

### E05_S03 — Tier-0 exit gate documentation

**Status:** NEW
**Tier:** 0
**Effort:** S
**Dependencies:** E05_S01, E05_S02

**Description.** This milestone makes the Tier-0 exit gate explicit, unambiguous, and visible at the top level of the roadmap. It defines the promotion conditions for each tier transition as machine-checkable statements, not prose aspirations. The gate replaces the qualitative "vibes-check" demo from E01_S10.

**Tier exit gates (authoritative — defined here, referenced in `README.md`):**

| Transition | Gate condition | Milestone |
|---|---|---|
| Tier-0 → Tier-1 | `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70` passes on ANN-only (no BM25, no reranker) | E05_S02 |
| Tier-1 → Tier-2 | `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.80` passes with BM25 hybrid + reranker active (E07) | E07_S04 (Sonnet B) |
| Tier-2 → Tier-3 | E08 caching telemetry healthy: cache hit rate ≥ 30% on a 24-hour production traffic sample | E08 (Sonnet B) |
| Tier-5 cutover | 200K paper backfill complete + drift watchdog stable (nDCG@5 within 5% of baseline) | E11_S05 (Sonnet B) |

The Tier-0 → Tier-1 condition is ANN-only because BM25 hybrid retrieval (E07) and the reranker (E07) are Tier-1 deliverables, not Tier-0 deliverables. Reranker activation is conditional on the Tier-1 metric gate: if nDCG@5 does not reach 0.80 after adding BM25 + reranker, activation is blocked and the retrieval pipeline is debugged before Tier-2 begins.

This milestone ships a `TIER-GATES.md` file in the root of the repository (not in `.claude/`) that is the single authoritative source for tier promotion conditions. It is linked from the roadmap `README.md`. The file includes the command to run and the expected output for each gate, so any contributor can verify tier readiness without reading the full roadmap.

**Deliverables.**
- `TIER-GATES.md` — root-level file with tier promotion conditions and commands
- Update to `Makefile`: `make eval` target that runs `pytest tests/eval/test_retrieval_quality.py`
- Update to `README.md`: link to `TIER-GATES.md`

**Acceptance criteria.**
- [ ] `TIER-GATES.md` exists at repo root and defines all four tier transitions with exact pytest commands.
- [ ] `make eval` runs `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70`.
- [ ] `TIER-GATES.md` states: "Reranker activation in E07 is conditional on nDCG@5 ≥ 0.80 after BM25 hybrid is active."
- [ ] Root `README.md` links to `TIER-GATES.md`.
- [ ] No subjective acceptance criteria (no "demo transcript" or "looks coherent" language).

**Out of scope.** Tier-1 and higher gates are specified here but implemented in Sonnet B's epics. This milestone only documents and wires the Tier-0 gate.

**Risk notes.**
- This milestone is the formal retirement of E01_S10 (vibes-check demo). The transition from qualitative to quantitative exit criteria is a process change as much as a code change. `TIER-GATES.md` must be reviewed and approved by the project owner before Tier-1 work begins.

**Labels.** `area:eval`, `kind:docs`, `tier:0`.
