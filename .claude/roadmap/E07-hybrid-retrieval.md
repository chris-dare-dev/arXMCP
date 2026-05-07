# E07 — Hybrid Retrieval

Epic dependencies: E04 (LanceDB chunks table with `body_tokens` BM25 index and dual embedding columns shipped), E05 (retrieval eval harness with nDCG@5 metric shipped)

Goal: Implement the 3-phase hybrid retrieval pipeline (BM25 → dual-ANN + RRF → BGE-reranker) that backs `search_papers`. The pipeline must be modular (each phase independently testable), gated on environment flags, and validated against the E05 eval harness at nDCG@5 ≥ 0.80 before exiting Tier 1.

Effort: M + M + M + M = L total

References: `.claude/notes/05-storage-and-indexing.md` lines 293–304, `.claude/notes/07-multi-agent-caching.md` lines 111–158

---

### E07_S01 — Phase 1: BM25 over body_tokens

**Status:** NEW
**Tier:** 1
**Effort:** M
**Dependencies:** E04_S04

**Description.** Implement the broad, cheap first phase of hybrid retrieval: BM25 full-text search over the `body_tokens` column in the LanceDB `chunks` table. This column is populated by Sonnet A's E02_S03 (pre-tokenization) and indexed by E04_S04 with `rank_bm25` plus a standard English analyzer (the new design explicitly rejects the fictional Tantivy "LaTeX analyzer" — closes critique H4). The pre-tokenizer preserves LaTeX command tokens like `\Spec`, `\mathrm{Pic}`, `\mathcal{F}` as identifier-like tokens (`Spec`, `mathrm_Pic`, `mathcal_F`) before BM25 indexing. Phase 1 returns the top-200 candidates as `(chunk_id, bm25_score)` tuples, sorted descending by score.

The BM25 query is constructed from the raw query string without lowercasing or punctuation stripping — `\'etale` and `étale` produce different lexical matches and must not be conflated at this stage. This mirrors the two-key normalization rule in the retrieval cache: the lookup key may normalize aggressively, but the actual query passed to BM25 must be byte-faithful (`.claude/notes/07-multi-agent-caching.md` lines 141–145).

Phase 1 also applies any scalar pre-filters from the `filters` argument before the BM25 scan: `categories`, `year_min`, `year_max`, `authors`, `include_withdrawn`. LanceDB supports combined scalar + FTS predicates; use them to avoid a post-hoc filter that discards candidates after BM25 has already ranked them. The top-200 candidate list is the input to Phase 2 and must be materialized as a Python list (not a lazy iterator) before being handed off.

The `BM25Phase` class is instantiated once at server startup (from `server/resources.py`) and is thread-safe for concurrent reads. It accepts the pinned LanceDB dataset version resolved at startup (via `dataset.checkout(version=N)` per E04_S02) and must not re-read `corpus-version.json` on every query.

**Deliverables.**
- `server/retrieval/bm25.py` — `BM25Phase` class: `query(text, filters, top_n=200) -> list[tuple[str, float]]`
- `tests/retrieval/test_bm25.py` — unit test: at least 5 known-good queries against the seed corpus, assert top result is the expected chunk; assert filters narrow results correctly

**Acceptance criteria.**
- [ ] `BM25Phase.query("étale cohomology")` returns a non-empty list within 500ms against the seed corpus
- [ ] `BM25Phase.query("\\Spec", filters={"categories": ["math.AG"]})` returns only math.AG chunks
- [ ] Returned list length is ≤ 200
- [ ] `chunk_id` values in the returned list are valid (present in the LanceDB table)
- [ ] `pytest tests/retrieval/test_bm25.py` passes

**Out of scope.** Dense ANN (Phase 2). Reranking (Phase 3). Query normalization beyond byte-faithful passthrough.

**Risk notes.**
- LaTeX-aware tokenization is Sonnet A's E04_S04 deliverable; if that index is absent, Phase 1 falls back to the prose `body_canonical` BM25 index and logs a warning.

**Labels.** `area:retrieval`, `kind:feature`, `tier:1`

---

### E07_S02 — Phase 2: dual-ANN with Reciprocal Rank Fusion

**Status:** NEW
**Tier:** 1
**Effort:** M
**Dependencies:** E04_S03, E07_S01

**Description.** Implement Phase 2 dense ANN search over both embedding columns in the `chunks` table: `embedding_stmt` (prose-only, math stripped to `[MATH]` tokens) and `embedding_proof` (raw LaTeX with expanded macros). Each column is searched independently with HNSW ANN, returning the top-50 candidates per column. The two ranked lists — plus the top-200 BM25 list from Phase 1 — are fused using Reciprocal Rank Fusion (RRF) with k=60.

RRF score for a candidate `c` across ranked lists `L_1 … L_n`:

```
rrf_score(c) = sum over i of 1 / (k + rank_i(c))
```

where `rank_i(c)` is the 1-based position of `c` in list `L_i`, or infinity if absent. After fusion, the top-50 candidates by `rrf_score` are returned as `(chunk_id, fused_score)` tuples. These 50 candidates are the input to Phase 3.

Query-time embedding follows the same dual-representation strategy as index-time: the query text is embedded twice — once with the prose encoder (math tokens stripped) and once with the LaTeX encoder (macros preserved). Both embeddings are computed via the shared `Singleflight`-wrapped embedder in `server/resources.py`. The two query vectors are used to search their respective HNSW indexes.

The `ANNPhase` class is initialized once at server startup. It accepts the 200-candidate BM25 list and the query text, runs both ANN searches, fuses with RRF, and returns the top-50. The class must handle the edge case where the BM25 list is empty (e.g., highly symbolic queries with no body-token matches) by falling back to the ANN results only.

**Deliverables.**
- `server/retrieval/ann.py` — `ANNPhase` class: `query(query_text, bm25_candidates, top_n=50) -> list[tuple[str, float]]`
- `server/retrieval/rrf.py` — `reciprocal_rank_fusion(lists, k=60) -> list[tuple[str, float]]` utility
- `tests/retrieval/test_ann.py` — unit tests: dual embedding produces two non-identical result lists; RRF output is a strict superset of neither input list alone; score ordering is descending

**Acceptance criteria.**
- [ ] `ANNPhase.query("perverse sheaves on flag varieties", bm25_candidates=[])` returns ≥ 1 result (pure ANN fallback path works)
- [ ] RRF output contains candidates from both the BM25 list and both ANN lists
- [ ] `fused_score` values are descending in the returned list
- [ ] Both embedding calls go through the shared Singleflight wrapper (verifiable via the singleflight hit counter in `/debug/cache-stats`)
- [ ] `pytest tests/retrieval/test_ann.py` passes

**Out of scope.** Reranking (Phase 3). ColBERT late-interaction (v1.5 feature per `.claude/notes/05-storage-and-indexing.md` lines 275–283).

**Risk notes.**
- The dual-embedding strategy relies on E04_S03 having populated both `embedding_stmt` and `embedding_proof` columns. If only one column is present, the ANNPhase must degrade gracefully to single-ANN + BM25 RRF.

**Labels.** `area:retrieval`, `kind:feature`, `tier:1`

---

### E07_S03 — Phase 3: BGE-reranker with env-flag gate

**Status:** NEW
**Tier:** 1
**Effort:** M
**Dependencies:** E07_S02

**Description.** Implement Phase 3 neural reranking using `BAAI/bge-reranker-v2-m3`, loaded from a pinned commit SHA recorded in `server/config.py`. The reranker scores each of the Phase-2 top-50 candidates against the original query using a cross-encoder pass, producing a final ranking. The top-k candidates (where k is the caller's requested `k`, default 10, max 50) are returned as `(chunk_id, rerank_score)` tuples.

Phase 3 is gated by the `ARXMCP_ENABLE_RERANK` environment variable, which defaults to `false` in all Tier-0 and Tier-1 deployments. When the flag is false, `search_papers` returns the Phase-2 RRF-ordered top-k directly, skipping the reranker entirely. The activation path is: E07_S04 demonstrates that nDCG@5 ≥ 0.80 requires the reranker, at which point the flag is enabled in production. If nDCG@5 ≥ 0.80 is already reached without reranking, the flag stays off and Phase 3 remains dormant.

Concurrent reranker calls are gated by `max_concurrent_reranks=4` (the semaphore initialized in `server/resources.py` E06_S01). The reranker call is wrapped in the `Singleflight` pattern keyed on `(query_embedding_hash, sorted_candidate_id_tuple_hash, reranker_version)` — this is Tier 3 of the retrieval cache (`.claude/notes/07-multi-agent-caching.md` lines 150–158). A cache hit on Tier 3 bypasses the reranker entirely and returns the cached ranking in microseconds.

The pinned commit SHA for the reranker model is stored as `ARXMCP_RERANK_MODEL_SHA` in config and validated at startup (when reranking is enabled) by comparing the local model directory's git ref against the pinned value. A mismatch is a startup warning, not a fatal error — the server continues but logs the drift.

**Deliverables.**
- `server/retrieval/rerank.py` — `RerankPhase` class: `rerank(query_text, candidates, top_k) -> list[tuple[str, float]]`; no-op passthrough when `ARXMCP_ENABLE_RERANK=false`
- `server/config.py` — updated with `ARXMCP_ENABLE_RERANK: bool = False` and `ARXMCP_RERANK_MODEL_SHA: str`
- `tests/retrieval/test_rerank.py` — unit test: with flag off, returns Phase-2 order unchanged; with flag on (requires model), returns a different order on a query where BM25/ANN ranking is known to be suboptimal

**Acceptance criteria.**
- [ ] With `ARXMCP_ENABLE_RERANK=false`, `RerankPhase.rerank(...)` returns input candidates in original order
- [ ] With `ARXMCP_ENABLE_RERANK=true`, reranker loads and scores all 50 candidates within 5 seconds
- [ ] Tier-3 cache hit bypasses the reranker (verifiable via cache-stats endpoint)
- [ ] `pytest tests/retrieval/test_rerank.py -k "not requires_model"` passes without the model downloaded

**Out of scope.** Cohere Rerank API (self-hosted only in v1). Fine-tuning the reranker. Online learning from agent feedback.

**Risk notes.**
- Reranker activation is explicitly tied to the E07_S04 nDCG@5 gate — enabling it preemptively without a quality signal is wasteful and adds latency.

**Labels.** `area:retrieval`, `kind:feature`, `tier:1`

---

### E07_S04 — End-to-end eval: promote nDCG@5 to ≥0.80

**Status:** NEW
**Tier:** 1
**Effort:** M
**Dependencies:** E07_S03, E05_S03

**Description.** Run the full 3-phase hybrid pipeline against E05's retrieval quality harness and promote the system to Tier-1 exit status when nDCG@5 ≥ 0.80 on the hand-labeled query set. This milestone is the gate that enables the 200K-paper scale cutover in E11.

The E05 harness has a fixed set of 20 hand-labeled queries with known-relevant chunk IDs. Each query is run through the full pipeline (Phase 1 BM25 → Phase 2 ANN+RRF → optionally Phase 3 rerank), and nDCG@5 is computed over the top-5 returned chunks. The threshold is 0.80. If Phase-3 reranking is required to cross 0.80, then `ARXMCP_ENABLE_RERANK` is set to `true` in the production config and documented in a brief findings note.

The pytest invocation is:

```
pytest tests/eval/test_retrieval_quality.py --hybrid --rerank --ndcg-min=0.80
```

This test is marked `@pytest.mark.eval` and excluded from the default test run — it requires the full seed corpus and (optionally) the reranker model. It is run manually before declaring E07 complete and again as part of E11's scale-cutover readiness check.

The findings from this milestone must be captured in `docs/retrieval-quality-report.md`: which phase contributes how much nDCG lift, whether the reranker is necessary, and the latency profile (p50/p95 per phase at k=10).

**Deliverables.**
- `tests/eval/test_retrieval_quality.py` — updated to accept `--hybrid` and `--rerank` flags and the `--ndcg-min` threshold argument
- `docs/retrieval-quality-report.md` — nDCG@5 per phase, latency p50/p95, reranker necessity finding
- `server/config.py` — `ARXMCP_ENABLE_RERANK` set to its production value based on findings

**Acceptance criteria.**
- [ ] `pytest tests/eval/test_retrieval_quality.py --hybrid --rerank --ndcg-min=0.80` passes
- [ ] nDCG@5 is ≥ 0.80 on the 20-query hand-labeled set
- [ ] `docs/retrieval-quality-report.md` states clearly whether the reranker is required
- [ ] Latency p95 for the full pipeline (with rerank if enabled) is ≤ 2 seconds at k=10 on the seed corpus

**Out of scope.** Expanding the eval query set beyond 20 queries (E11_S04 adds drift detection over the full corpus). A/B testing between retrieval configurations.

**Risk notes.**
- This milestone is the single explicit Tier-1 exit gate. E11_S05 references this nDCG@5 threshold as the activation criterion for the 200K scale cutover (closes H9 indirectly via E11_S05).

**Labels.** `area:retrieval`, `kind:eval`, `tier:1`
