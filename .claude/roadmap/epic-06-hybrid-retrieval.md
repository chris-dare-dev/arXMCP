# E06 — Hybrid Retrieval & Reranking (Tier 1e)

**Epic dependencies:** E05.

**Goal:** implement the three-phase ranking from `05-storage-and-indexing.md` § Hybrid search at query time. Phase 1: BM25 over both `body_raw_latex` (LaTeX analyzer) and `body_canonical` (English analyzer), top-200. Phase 2: ANN over `embedding_prose` and `embedding_latex`, k=200 each, fused via Reciprocal Rank Fusion to top-50. Phase 3: rerank with `bge-reranker-v2-m3` to the user's requested k.

**Effort:** ~1 week.

**References:** `05-storage-and-indexing.md` § Hybrid search at query time; `06-mcp-server-design.md` § Concurrency model (semaphores).

---

### E06_S01 — Phase-1 BM25 fan-out across both analyzers

**Description.** Issue two BM25 queries against the `chunks` table — one against `body_raw_latex` (LaTeX analyzer) and one against `body_canonical` (English analyzer). Return top-200 from each as separate candidate lists, with their BM25 scores.

**Acceptance criteria.**
- [ ] `server/retrieval/phase1.py::bm25_search(query, filters, k=200) -> list[Candidate]`.
- [ ] Returns one merged list with BM25 scores per analyzer (so RRF in E06_S03 can use them separately).
- [ ] Filter clauses (`paper_id`, `version`, `level`, `kind`, year range, categories) applied at the LanceDB query level, not post-filter.
- [ ] Test: query for "étale cohomology" returns at least one chunk per analyzer on the seed corpus.
- [ ] Test: query for `\Spec` against the LaTeX analyzer returns relevant results.

**Dependencies.** none within E06.

**Complexity.** M.

**Labels.** `area:retrieval`, `kind:feature`.

---

### E06_S02 — Phase-2 dense ANN over both embedding columns

**Description.** Embed the user query (E06_S05 handles caching) and issue two HNSW searches — one against `embedding_prose`, one against `embedding_latex` — k=200 each. Return both lists with their cosine similarities.

**Acceptance criteria.**
- [ ] `server/retrieval/phase2.py::ann_search(query_vec_prose, query_vec_latex, filters, k=200) -> list[Candidate]`.
- [ ] Two searches run concurrently (asyncio.gather).
- [ ] Filters honoured at the LanceDB query level.
- [ ] Test: searching with a math.AG query returns chunks predominantly from math.AG papers when filtered by category.
- [ ] Test: prose-vec search and latex-vec search return overlapping but non-identical top-50 sets (sanity that dual embeddings actually differentiate).

**Dependencies.** E05_S03, E05_S06.

**Complexity.** M.

**Labels.** `area:retrieval`, `kind:feature`.

---

### E06_S03 — Reciprocal Rank Fusion across four candidate lists

**Description.** Per `05-storage-and-indexing.md` § Hybrid search at query time — fuse the four candidate lists (BM25-LaTeX, BM25-canonical, ANN-prose, ANN-LaTeX) via Reciprocal Rank Fusion. Output is a single top-50 ranked list. RRF formula: `score(d) = sum_i 1 / (k + rank_i(d))` with `k=60` (standard).

**Acceptance criteria.**
- [ ] `server/retrieval/fusion.py::rrf(lists, k=60) -> list[Candidate]` returns a fused top-N.
- [ ] Each fused candidate carries (a) the four per-list ranks (or `None` if absent) and (b) the RRF aggregate score.
- [ ] Tie-breaking is by `chunk_id_asc` to satisfy the determinism contract from `02-architecture-overview.md`.
- [ ] Test: a known-relevant chunk that ranks #1 in BM25-LaTeX and #5 in ANN-prose ranks above one that's #20 in all four.
- [ ] Test: identical input lists across two runs produce byte-identical RRF output.

**Dependencies.** E06_S01, E06_S02.

**Complexity.** M.

**Labels.** `area:retrieval`, `area:cache`, `kind:feature`.

---

### E06_S04 — Phase-3 reranker integration (`bge-reranker-v2-m3`)

**Description.** Load `BAAI/bge-reranker-v2-m3` per `05-storage-and-indexing.md` § Hybrid search Phase 3. Take the top-50 from RRF, rerank by cross-encoder score, return top-k where k is the user's requested k (default 10, max 50).

**Acceptance criteria.**
- [ ] `server/retrieval/rerank.py::rerank(query, candidates, k) -> list[Candidate]`.
- [ ] Reranker model commit SHA pinned per `08-security-observability-ops.md` Threat 6.
- [ ] Reranker calls are bounded by a semaphore (`max_concurrent_reranks=4` per `06-mcp-server-design.md` § Concurrency model).
- [ ] Reranker input is `(query, body_canonical[:1024 tokens])` — bounded to avoid OOM on long proofs.
- [ ] Test: reranker actually changes ordering vs. RRF on at least 30% of queries on the seed corpus (smoke test).
- [ ] `arxmcp_rerank_calls_total{model, outcome}` counter exposed.

**Dependencies.** E06_S03.

**Complexity.** M.

**Labels.** `area:retrieval`, `area:embedder`, `kind:feature`.

---

### E06_S05 — Query embedder with bounded concurrency

**Description.** Wrap the embedder used for query-time encoding in an asyncio semaphore (`max_concurrent_embeddings=8` per `06-mcp-server-design.md`). The same embedder used at ingestion time (bge-m3) — but loaded as a long-lived singleton, not re-loaded per request.

**Acceptance criteria.**
- [ ] `server/embed/query.py::embed_query(text) -> (prose_vec, latex_vec)`.
- [ ] Embedder model loaded once at server startup.
- [ ] Semaphore bounds concurrent embeddings to 8.
- [ ] Test: 100 concurrent calls eventually all return; never more than 8 in flight at once.
- [ ] Single embed-pair call is <200 ms on CPU for short queries.

**Dependencies.** E05_S06.

**Complexity.** M.

**Labels.** `area:embedder`, `area:server`, `kind:feature`.

---

### E06_S06 — Result canonicalization and determinism contract

**Description.** Per `06-mcp-server-design.md` § Determinism contract — sort results by `(score_desc, chunk_id_asc)`, no timestamps in payloads, JSON keys serialized alphabetically, include `corpus_version` and `embed_model` in every response.

**Acceptance criteria.**
- [ ] `server/retrieval/canonicalize.py::to_response(candidates, query, corpus_version, embed_model) -> dict`.
- [ ] Output is `structuredContent` per the schema in `06-mcp-server-design.md` § search_papers.
- [ ] JSON is serialized with `sort_keys=True`, no timestamps, no random tie-breakers.
- [ ] `corpus_version` and `embed_model` always present.
- [ ] Test: running the same query twice on the same corpus version produces SHA-256-identical response bytes.
- [ ] Test: changing `embed_model` between runs produces different bytes.

**Dependencies.** E06_S04.

**Complexity.** M.

**Labels.** `area:retrieval`, `area:cache`, `risk:high`.

---

### E06_S07 — Result-byte hard cap and `resource_link` spillover

**Description.** Per `06-mcp-server-design.md` § Spec compliance points — tool result size has a 256 KB hard cap on inline content. Long bodies are returned as `resource_link` URIs of the form `arxmcp://chunks/<chunk_id>` instead of inline. Inline payload always carries summary + 200-char snippet.

**Acceptance criteria.**
- [ ] `server/retrieval/canonicalize.py` enforces the 256 KB cap.
- [ ] Each result includes a `resource_link` to the full chunk; inline payload is the summary + snippet.
- [ ] Test: a synthetic response that would exceed 256 KB inline is rewritten to `resource_link` form and stays under the cap.
- [ ] Hard cap is configurable via `ARXMCP_RESULT_BYTE_CAP` per `06-mcp-server-design.md` § Configuration.

**Dependencies.** E06_S06.

**Complexity.** S.

**Labels.** `area:server`, `area:retrieval`, `area:security`.

---

### E06_S08 — Filter validation and JSON-Schema gate

**Description.** Filters (`categories`, `year_min`, `year_max`, `authors`, `include_withdrawn`) come from LLM output — validate strictly per `06-mcp-server-design.md` and `08-security-observability-ops.md` Threat 4. Reject malformed values at the JSON-Schema layer before they reach the handler.

**Acceptance criteria.**
- [ ] JSON-Schema for `search_papers` rejects `k > 50`, `year_min > year_max`, non-string author entries.
- [ ] Categories must match `^(math|hep-th|math-ph|cs|cond-mat|...).<sub>$` — full whitelist enumerated in code.
- [ ] Test: bad inputs return JSON-RPC error code -32602 (invalid params).
- [ ] Test: well-formed inputs pass through cleanly.
- [ ] Validation errors do NOT leak internal stack traces to the client.

**Dependencies.** E06_S06.

**Complexity.** S.

**Labels.** `area:server`, `area:security`.

---

### E06_S09 — Retrieval-quality evaluation harness for the seed corpus

**Description.** Per the Tier 1 exit criterion in `09-feature-priorities.md` — "retrieval over 1,000 papers reliably surfaces the right theorem for queries phrased in 3 different ways." Build a small evaluation harness with hand-crafted query/ground-truth pairs over the 50-paper seed: 10 queries × 3 phrasings each. Track top-1 / top-5 / top-10 hit rates as a baseline.

**Acceptance criteria.**
- [ ] `tests/retrieval/eval_seed.yaml` lists 30 query/ground-truth pairs (10 queries × 3 phrasings).
- [ ] `tools/eval_retrieval.py` runs them all, reports top-1/top-5/top-10 hit rates, P@5 and recall, plus per-phrasing breakdown.
- [ ] Baseline numbers committed to `docs/retrieval/seed-baseline.md`.
- [ ] Hit rate at top-10 ≥80% on this small set is the soft target (used to gate progress, not a hard requirement).
- [ ] Same harness re-used in E12 for full-corpus validation.

**Dependencies.** E06_S07.

**Complexity.** M.

**Labels.** `area:retrieval`, `kind:research`.

---
