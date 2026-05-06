# E08 — Multi-Agent Caching (Tier 2)

**Epic dependencies:** E07.

**Goal:** make the server cache-friendly across multiple concurrent Claude sub-agents. Three-tier retrieval cache (exact, semantic, rerank-set), singleflight on embedder/reranker/summarizer, summary cache (Haiku output), embedding cache. Document the orchestrator-side rule for normalizing tool-use IDs (the cache-killer the strawman missed). Exit criterion (`09-feature-priorities.md`): spawn 4 Claude Code sub-agents querying the same corpus and verify cache hit rates ≥40% on Tier 1 and ≥60% on Tier 3.

**Effort:** 1–2 weeks.

**References:** `07-multi-agent-caching.md` (entire file is authoritative); `06-mcp-server-design.md` § Determinism contract.

---

### E08_S01 — Tier-1 exact-query cache (in-process LRU + SQLite)

**Description.** Per `07-multi-agent-caching.md` § Tier 1 — key is `sha256(canonical_form(query) + filters_json + k + corpus_version)`, value is the full `structuredContent` payload, TTL 1 hour, store is in-process LRU (~10K entries) plus SQLite for cross-restart persistence. `canonical_form(query)` is `query.strip()` only — do NOT lowercase or strip punctuation.

**Acceptance criteria.**
- [ ] `server/cache/tier1.py::Tier1Cache` LRU + SQLite-backed.
- [ ] Cache key construction follows the note's formula exactly; filters_json is serialized with sorted keys.
- [ ] `canonical_form(query)` is `query.strip()` only (asserted in unit tests).
- [ ] LRU max 10K entries; SQLite persists across restarts.
- [ ] TTL 1 hour; expired entries are skipped on lookup and lazily evicted.
- [ ] Test: same query twice ⇒ 1 lookup, 1 hit on the second.
- [ ] Test: differing case (`étale` vs `Étale`) ⇒ cache miss (canonical form is case-preserving).
- [ ] Counter `arxmcp_cache_lookups_total{layer="tier1"}` and `arxmcp_cache_hits_total{layer="tier1"}` exposed.

**Dependencies.** none within E08.

**Complexity.** M.

**Labels.** `area:cache`, `kind:feature`.

---

### E08_S02 — Tier-2 semantic-query cache (FAISS over recent query embeddings)

**Description.** Per `07-multi-agent-caching.md` § Tier 2 — small in-process FAISS index over the last ~4096 query embeddings; on lookup, find nearest centroid with cosine > 0.97 AND filter match exact; serve cached payload. TTL 15 minutes. Threshold tuning matters: 0.97 is the defensible default. Two-key normalization rule: lookup key may aggressively normalize, but the actual query passed to BM25/embedder is unchanged.

**Acceptance criteria.**
- [ ] `server/cache/tier2.py::Tier2Cache` wraps a FAISS `IndexFlatIP` over recent query embeddings.
- [ ] Index capped at 4096 entries; oldest evicted on insert.
- [ ] Lookup: embed query, find nearest, check cosine > 0.97, check filter set equality, return cached payload if hit.
- [ ] Threshold is configurable via `ARXMCP_TIER2_COSINE_THRESHOLD` (default 0.97).
- [ ] Test: "definition of étale morphism" hits cache when "what is an étale morphism" was the prior query.
- [ ] Test: "definition of perverse sheaf" misses when "what is an étale morphism" was the prior query.
- [ ] 1% sampling: log Tier-2 hits to `var/arxmcp/ops/tier2-samples.jsonl` for human review.
- [ ] Counter `arxmcp_cache_hits_total{layer="tier2"}` exposed.

**Dependencies.** E08_S01.

**Complexity.** L.

**Labels.** `area:cache`, `kind:feature`, `risk:high`.

---

### E08_S03 — Tier-3 rerank-set cache

**Description.** Per `07-multi-agent-caching.md` § Tier 3 — key is `sha256(query_embedding_hash + sorted_candidate_id_tuple_hash + reranker_version)`. Value is the reranked top-k order. TTL 1 hour. Hit rates of 40–60% under multi-agent fan-out are the target.

**Acceptance criteria.**
- [ ] `server/cache/tier3.py::Tier3Cache` in-process LRU.
- [ ] Cache lookup happens after Phase 1+2 produce the candidate list and before invoking the reranker.
- [ ] Key includes the sorted candidate ID tuple's SHA-256 to detect "same candidates" across slightly different queries.
- [ ] `reranker_version` is part of the key; bumping reranker invalidates by construction.
- [ ] Test: two queries that produce overlapping top-200 candidate sets share a Tier-3 entry only if the candidate set is exactly equal.
- [ ] Counter `arxmcp_cache_hits_total{layer="tier3"}` exposed.

**Dependencies.** E06_S04.

**Complexity.** M.

**Labels.** `area:cache`, `kind:feature`.

---

### E08_S04 — Singleflight wrapper for embedder, reranker, summarizer

**Description.** Per `07-multi-agent-caching.md` § Singleflight on the embedder — when N concurrent agents ask the same question in the first 200 ms, you want one in-flight call, not N. Implement the asyncio Singleflight pattern from the note and wrap the embedder, reranker (per `(query, candidate_set)` key), and the summary generator (per `(query, candidate_set)` key).

**Acceptance criteria.**
- [ ] `server/cache/singleflight.py::Singleflight` matches the pattern in `07-multi-agent-caching.md`.
- [ ] `try/finally` ensures the inflight key is always popped (defends against deadlock from raised exceptions).
- [ ] Wraps embedder query path (E06_S05), reranker (E06_S04), and summary generation (E08_S07).
- [ ] Test: 10 concurrent calls to embed the same query result in exactly 1 underlying embedder invocation.
- [ ] Test: a raising `fn` does not leak the inflight entry.
- [ ] Counter `arxmcp_embed_singleflight_dedup_total` exposed.

**Dependencies.** E06_S04, E06_S05.

**Complexity.** M.

**Labels.** `area:cache`, `kind:feature`.

---

### E08_S05 — Query embedding cache (in-process LRU)

**Description.** Per `07-multi-agent-caching.md` § Query embedding cache — keyed by `sha256(model_name + model_version + canonical_form(query))`, value is the vector, TTL 1 hour, in-process LRU (~10K entries). Distinct from the chunk embedding cache built in E05_S08 (which is build-time, persistent).

**Acceptance criteria.**
- [ ] `server/cache/query_embed.py::QueryEmbedCache` LRU.
- [ ] Cache hit returns the stored vector and increments `arxmcp_cache_hits_total{layer="query_embed"}`.
- [ ] Stored alongside the model name/version/SHA so a model swap invalidates by construction.
- [ ] Test: re-embedding the same query ⇒ 1 hit.
- [ ] Test: switching `embed_model` env var between requests ⇒ 0 hits.

**Dependencies.** E06_S05.

**Complexity.** S.

**Labels.** `area:cache`, `kind:feature`.

---

### E08_S06 — Cache-key inclusion of `corpus_version`

**Description.** Per `07-multi-agent-caching.md` § Failure modes — "stale entry served after corpus version bump" is prevented by including `corpus_version` in every cache key. Validate this is the case across all four caches (Tier 1, Tier 2, Tier 3, query embed) and add a regression test that bumping the version invalidates every cache by construction.

**Acceptance criteria.**
- [ ] Tier 1, Tier 2, Tier 3 keys all include `corpus_version`.
- [ ] Query-embedding cache key does NOT include corpus_version (it's just embedding) — but this is documented as intentional.
- [ ] Test: store an entry at version 7, switch the pinned version to 8, look up the same query, expect a miss.
- [ ] Documented in `docs/cache/key-design.md`.

**Dependencies.** E08_S01, E08_S02, E08_S03.

**Complexity.** S.

**Labels.** `area:cache`, `kind:infra`.

---

### E08_S07 — Haiku-backed summary generator with summary cache

**Description.** Per `07-multi-agent-caching.md` § Summary cache — `search_papers` returns a `summary` field generated by Claude Haiku over the top-k candidates. Cache key: `sha256(query_canonical + sorted(candidate_chunk_ids) + summarizer_prompt_version + summarizer_model_version)`. TTL 1 hour. SQLite-backed so cache survives restarts.

**Acceptance criteria.**
- [ ] `server/summary/generator.py::summarize(query, candidates) -> str` calls Haiku with a fixed prompt template at temperature 0.
- [ ] Cache key includes `summarizer_prompt_version` constant; bumping it invalidates old summaries.
- [ ] Cache TTL 1 hour; SQLite-backed.
- [ ] Test: 4 concurrent calls with the same `(query, candidates)` invoke Haiku once (singleflight from E08_S04).
- [ ] Test: cache survives a server restart.
- [ ] Test: changing the `summarizer_prompt_version` constant invalidates by construction.
- [ ] Counter `arxmcp_cache_hits_total{layer="summary"}` exposed.
- [ ] Spend metric `arxmcp_api_spend_usd_total{provider="anthropic", agent_role="summarizer"}` per `08-security-observability-ops.md`.

**Dependencies.** E08_S04.

**Complexity.** L.

**Labels.** `area:cache`, `area:embedder`, `kind:feature`.

---

### E08_S08 — `/debug/cache-stats` endpoint

**Description.** Per `07-multi-agent-caching.md` § Cache observability — debugging endpoint returning a JSON snapshot of all cache layers' sizes, hit/miss counts, and eviction counts. Useful when 4 agents are concurrently retrieving and you need to understand where budget is being spent.

**Acceptance criteria.**
- [ ] `GET /debug/cache-stats` returns JSON with one entry per layer (`tier1`, `tier2`, `tier3`, `query_embed`, `summary`, `chunk_embed`).
- [ ] Each entry includes `lookups_total`, `hits_total`, `evictions_total`, `bytes`, `entry_count`.
- [ ] Endpoint is gated to localhost (same Origin/Host validation as the rest of the server).
- [ ] Test: hit ratios computed by the test match what the LRU reports.
- [ ] Documented in `docs/server/debug-endpoints.md`.

**Dependencies.** E08_S01, E08_S02, E08_S03, E08_S05, E08_S07.

**Complexity.** S.

**Labels.** `area:cache`, `area:observability`.

---

### E08_S09 — Tool-result default shape: summary + citations + resource_links

**Description.** Per `07-multi-agent-caching.md` § Tool-result shape — `search_papers` returns `{summary, citations, resource_links}` (PaperQA2-inspired). Default keeps inline payload small; agents materialize chunk bodies via `resource_link`s only when needed. The summary comes from E08_S07's cache.

**Acceptance criteria.**
- [ ] `search_papers` response includes top-level `summary` (string), `citations` (list of `{chunk_id, score, snippet (≤200 char), label}`), and `resource_links` (list of `{uri, name}`).
- [ ] Default per-result inline tokens <= 300 (vs ~2000 for full body inline).
- [ ] Test: 10-result response total bytes <= 30 KB inline.
- [ ] Test: each `resource_link` URI resolves to the corresponding chunk via `resources/read`.

**Dependencies.** E08_S07, E07_S03.

**Complexity.** S.

**Labels.** `area:server`, `area:cache`, `kind:feature`.

---

### E08_S10 — Tool-use ID normalization documentation for orchestrator authors

**Description.** Per `07-multi-agent-caching.md` § The cache-killer the strawman missed — the orchestrator (the layer that composes sub-agent prompts) must normalize `tool_use` and `tool_result` IDs before composing the next agent turn. This is NOT a server-side change, but the server's docs must explain the rule because consumers will need it. Ship the canonical Python recipe from the note as a documented, copy-pasteable utility.

**Acceptance criteria.**
- [ ] `docs/orchestrator/tool-use-id-canonicalization.md` explains the rule, the failure mode, and includes the exact Python recipe from `07-multi-agent-caching.md`.
- [ ] Reference implementation as `arxmcp/orchestrator_helpers/canonicalize_turn.py` (importable but not used server-side).
- [ ] Unit tests demonstrate the recipe correctly remaps IDs and is idempotent.
- [ ] README links the doc from the top-level "Multi-agent caching" section.
- [ ] Documented as the "single most underrated optimization in agentic pipelines."

**Dependencies.** none within E08.

**Complexity.** S.

**Labels.** `area:cache`, `kind:research`.

---

### E08_S11 — Cache-failure fallback (caching is performance, not correctness)

**Description.** Per `07-multi-agent-caching.md` § Failure modes for the cache layer — every cache layer must fall through to recompute on failure; no data integrity rests on cache state. Add explicit `try/except` boundaries in each layer's `get`/`set` paths so cache crashes/OOM gracefully degrade.

**Acceptance criteria.**
- [ ] Every cache `get` returns `None` on internal exception, logs WARN, increments a `cache_errors_total{layer}` counter.
- [ ] Every cache `set` swallows internal exceptions silently, increments the error counter.
- [ ] Test: a fault-injected cache (raising on `get`) does not propagate the exception to the tool handler; query returns correct (recomputed) result.
- [ ] Documented in `docs/cache/failure-modes.md`.

**Dependencies.** E08_S01, E08_S02, E08_S03, E08_S05, E08_S07.

**Complexity.** S.

**Labels.** `area:cache`, `area:observability`.

---

### E08_S12 — 4-agent fan-out hit-rate validation

**Description.** Per the Tier 2 exit criterion in `09-feature-priorities.md` — spawn 4 Claude Code sub-agents querying the same corpus and verify Tier 1 hit rate ≥40% and Tier 3 hit rate ≥60% across the run. Hand-craft a 20-query workload that exercises overlap.

**Acceptance criteria.**
- [ ] `tools/eval_cache_fanout.py` spawns 4 client sessions, each issuing a 20-query workload (with deliberate overlap on ~50% of queries).
- [ ] After the run, `/debug/cache-stats` reports hit rates ≥40% on Tier 1 and ≥60% on Tier 3.
- [ ] Workload definition committed in `tests/cache/fanout-workload.yaml`.
- [ ] Numbers logged to `var/arxmcp/ops/fanout-eval.json` for tracking over time.
- [ ] If hit rates fall below threshold, the workload OR the cache thresholds are adjusted (and the rationale documented).

**Dependencies.** E08_S01, E08_S03, E08_S08.

**Complexity.** M.

**Labels.** `area:cache`, `kind:research`.

---
