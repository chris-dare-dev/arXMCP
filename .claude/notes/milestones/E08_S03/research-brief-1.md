# E08_S03 Research Brief 1 — MCP-side 3-Tier Retrieval Cache

## 1. In-Codebase Context

### Design notes that apply

**`07-multi-agent-caching.md`** is the primary constitution for this milestone. Load-bearing quotes:

- Tier 1 key formula: `"key = sha256(canonical_form(query) + filters_json + k + corpus_version)"` — `canonical_form` is `query.strip()` only; `"do NOT lowercase, do NOT strip punctuation. \\'etale and étale produce different lexical matches."`
- Tier 2: `"key = nearest centroid in query-embedding space, cosine > 0.97, AND filters match exactly"` … `"store = small in-process FAISS index over recent query embeddings"`. Also: `"**Two-key normalization rule (critical):** the cache *lookup key* may use aggressive normalization; the *actual query passed to BM25 / embedder* must be unchanged."`
- Lines 150–158 (Tier 2 review contract): `"Log every Tier-2 hit; sample 1% for human review; tune."` and `"If the FAISS index is empty (cold start), Tier 2 is a no-op pass-through."`
- Tier 3 key: `"key = sha256(query_embedding_hash + sorted_candidate_id_tuple_hash + reranker_version)"` TTL 1 hour. Expected hit rate 40–60%.
- Cache observability (lines 301–315): four metrics per layer: `cache_lookups_total{layer}`, `cache_hits_total{layer}`, `cache_evictions_total{layer}`, `cache_bytes{layer}`.
- Failure mode quote: `"Cache layer crash / OOM → Fall through to recompute; log; alert. Caching is performance, not correctness."`

**`06-mcp-server-design.md`** — `structuredContent` is the canonical, byte-stable, cache-friendly payload. Results must be sorted `(score_desc, chunk_id_asc)` and JSON keys serialized alphabetically.

**`08-security-observability-ops.md`** — observability is required; one `GET /debug/cache-stats` endpoint is mentioned in the design notes.

### Key source files examined

**`server/resources.py`**: The `Resources` dataclass is the lifecycle container attached to `app.state.resources`. The cache singleton should be added here as a new field (e.g., `retrieval_cache: RetrievalCache | None = None`) initialized in `Resources.startup()`. The pattern for injecting process-lifetime singletons is established: `bm25_phase`, `ann_phase`, `rerank_phase` are all added in `startup()` and stored as `Any | None` duck-typed fields. The `Singleflight` class already exists in this module and must NOT be duplicated.

**`server/config.py`**: Uses `pydantic-settings` with `env_prefix="ARXMCP_"` and `extra="forbid"`. No `cache_path` field exists yet. The brief needs one new field: `cache_db_path: Path = Path("var/arxmcp/cache/retrieval.db")` (sibling to `lancedb_path`). Adding it requires the `_scan_unknown_arxmcp_env_vars` check in `main.py` to pass.

**`server/corpus.py`**: `CorpusVersionInfo.version: int` is the canonical corpus version integer, read via `read_corpus_version(config.lancedb_path)` → loaded once into `resources.corpus_info.version`. Quote from `corpus.py` docstring: `"Downstream caches (E08_S03) must include corpus_version in their keys. Specifically: server-side caches use the version integer from CorpusVersionInfo as their cache namespace key — NOT chunker_version, NOT embedder_version, NOT created_at."` The `corpus-version.json` file lives at `<lancedb_path>/corpus-version.json`.

**`server/health.py`**: `prometheus_client` is **already a project dependency** (`prometheus-client>=0.20` in `pyproject.toml`). `Counter` and `Gauge` are already imported. The pattern for adding new metrics is: define module-level constants with `Counter(...)` / `Gauge(...)`, then call `.inc()` / `.set()` from the cache layer. The `refresh_metrics_from_singleton_state` hook runs at scrape time.

**`server/main.py`**: Routes are added via `app.include_router(router)`. The `debug` router must be added after the health router. The `_BYTE_CAP_EXEMPT_PREFIXES` tuple must include `/debug` (or the cache-stats JSON will hit the 256 KB cap, which is fine for small stats but the exemption is cleaner). Prometheus metrics ASGI is already mounted at `/metrics`.

**`server/query_encoder.py`**: `encode_query(query_text: str) -> np.ndarray` is async. Returns L2-normalized float32 shape `(1024,)`. Already has singleflight. This is Tier 2's embedding source. The canonical form is `unicodedata.normalize("NFC", query_text.strip())`.

**`server/retrieval/rerank.py`**: `RERANKER_VERSION: str = f"bge-reranker-v2-m3@{BGE_RERANKER_COMMIT_SHA[:8]}"` is the `reranker_version_sha` for the Tier-3 key. `_build_singleflight_key(query_vec, candidates) -> str` already computes `sha256(vec_bytes + sorted_chunk_ids + version_bytes)` using length-prefix encoding — **this is the Tier-3 key**. Tier-3 LRU was explicitly deferred from E07_S03 (`"the LRU is deferred to a follow-up"`).

**`server/handlers/search.py`**: `handle_search_papers` returns `CallToolResult(content=content, structuredContent=structured)`. The `structuredContent` dict is the payload to cache. It is JSON-serializable (already serialized to string for `content[0]`). Payload type: `dict[str, Any]` — store as `json.dumps(payload, sort_keys=True).encode("utf-8")` in SQLite and keep the deserialized `dict` in the in-process LRU.

**Test patterns** (`tests/conftest.py`): Module-level state is reset via autouse fixtures using `monkeypatch.setattr`. The `_reset_for_tests()` pattern exists in `server/query_encoder.py`. The cache module must expose a `reset_cache_for_tests()` function that clears all three tiers (LRUs + FAISS index + SQLite in-memory state). Tests use `asyncio.run()` inside sync test bodies, NOT `pytest-asyncio`.

### FAISS status
**FAISS is NOT a current dependency.** `pyproject.toml` has no `faiss-cpu` or `faiss-gpu` entry. This milestone must add `faiss-cpu>=1.7` to `pyproject.toml`. This is a runtime dependency, not dev-only.

### Prometheus multiprocess mode
Single-process deployment (Uvicorn with one worker per `06-mcp-server-design.md`). The `PROMETHEUS_MULTIPROC_DIR` multiprocess mode is **not needed**. Use the default `prometheus_client` single-process registry.

---

## 2. Prior Decisions and Lessons

### What prior milestones established

- **E06_S01**: `prometheus-client>=0.20` added to runtime deps. The metric-naming pattern is `arxmcp_{metric_name}` with `{label}` for label cardinality.
- **E07_S03**: Tier-3 singleflight key (`_build_singleflight_key`) ships in `server/retrieval/rerank.py`. The E07_S03 impl summary explicitly says: `"Tier-3 LRU memo (1-hour TTL) — deferred to a follow-up."` **This milestone IS that follow-up.** The Tier-3 LRU key must reuse `_build_singleflight_key(query_vec, candidates)` — do NOT reimplement.
- **E08_S02**: No cache-related changes. No new runtime deps.

### FLAG: Milestone brief vs. existing code conflict

The brief specifies Tier-3 cache key as `sha256(query_embedding_hash + sha256(sorted_candidate_ids_json) + reranker_version_sha)`. The existing `_build_singleflight_key` in `rerank.py` computes `sha256(vec_bytes + sorted_chunk_ids + version_bytes)` using length-prefix encoding (not a sha of sorted_ids_json). **These differ structurally but are cryptographically equivalent.** Recommendation: reuse `_build_singleflight_key` verbatim for the Tier-3 LRU key — the output is a hex SHA256 string, which is the right input for the `sha256(...)` key composition the brief describes. Do NOT invent a second key function.

### `corpus_version` existence

`corpus_version` exists and is well-defined. It is `resources.corpus_info.version` (an `int` ≥ 1, loaded at startup from `corpus-version.json`). The caching module receives it as a constructor argument pinned at startup. No new definition needed.

### No existing `server/cache.py` or `server/cache_sqlite.py`

Neither file exists. Both are new.

### `server/routes/debug.py` path

The brief specifies `server/routes/debug.py`. The existing handler structure uses `server/handlers/` (not `server/routes/`). Check whether a `server/routes/` dir should be created or whether to use `server/handlers/debug.py` instead. Recommend creating `server/routes/` as a new sub-package (consistent with the brief) with its own `__init__.py`.

---

## 3. External Sources

### SQLite WAL mode (for `cache_sqlite.py`)

Use `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL`. WAL allows concurrent readers while one writer holds the write lock — critical when the async cache writer and the test fixture reader hit the same file. With `synchronous=NORMAL` SQLite flushes at checkpoints, not on every commit, which is appropriate for a cache (correctness failure = cache miss, not data loss). Schema: `CREATE TABLE tier1_cache (key TEXT PRIMARY KEY, value BLOB, expires_at REAL)`.

### FAISS: `IndexFlatIP` for cosine on normalized vectors

BGE-M3 returns L2-normalized vectors (float32, dim=1024). Cosine similarity on L2-normalized vectors equals inner product. Use `faiss.IndexFlatIP(1024)` — inner product index. Do NOT use `IndexFlatL2` (measures Euclidean distance, not cosine). A query is a hit when `faiss.knn(query_vec, k=1)` returns distance ≥ 0.97. The ring buffer of 1,000 entries fits entirely in memory (1024 × 4 bytes × 1000 = ~4 MB).

### prometheus_client multiprocess mode

Not applicable. Uvicorn runs one worker. Use the default single-process registry. No `PROMETHEUS_MULTIPROC_DIR` env var needed.

---

## Open Questions

1. **Payload type stored in Tier 1 / Tier 2 cache**: The implementer should store the `structuredContent` dict serialized as `json.dumps(payload, sort_keys=True).encode("utf-8")` in SQLite (BLOB). In-process LRU holds the deserialized dict. The round-trip is `json.loads(blob)`. Do not use pickle (Threat 6 precedent in this codebase).

2. **SQLite file location**: `Config.lancedb_path` is `Path("var/arxmcp/index/lancedb")`. The cache DB should live at `Config.lancedb_path.parent.parent / "cache" / "retrieval.db"` → `var/arxmcp/cache/retrieval.db`. This requires adding a `cache_db_path: Path` field to `Config`. The parent dir must be created at startup (`cache_db_path.parent.mkdir(parents=True, exist_ok=True)`).

3. **How `handle_search_papers` gets the cache**: `handle_search_papers` calls `get_resources()` for the `Resources` singleton. The `Resources` dataclass must carry `retrieval_cache: RetrievalCache | None = None`. The handler inserts a cache lookup BEFORE the encode + ANN path and a cache write AFTER assembling the payload.

4. **Tier-2 FAISS thread safety**: `faiss.IndexFlatIP.add()` and `faiss.IndexFlatIP.search()` are not thread-safe. Since the MCP server is single-process asyncio, FAISS operations should be called from the event-loop thread (no thread-pool needed for FAISS flat index — it's fast enough). Protect the ring buffer with an `asyncio.Lock`, not a `threading.Lock`.

5. **`search_papers` / `get_chunk` async-friendliness**: Both handlers are already `async def`. The cache lookup path is fully async-compatible — all three tier lookups run sequentially as specified.

6. **Test isolation for cache**: The `reset_cache_for_tests()` function must clear the in-process LRU dicts, the FAISS index (call `index.reset()`), and reset all Prometheus counters. Because `prometheus_client` counters are global singletons, tests must use `REGISTRY.unregister(counter_obj)` + re-register, or use the `reset_metrics_for_tests()` pattern from `server/health.py`. Recommend a module-level `_CACHE_SINGLETON: RetrievalCache | None = None` that `reset_cache_for_tests()` replaces with a fresh instance.

7. **`/debug` path exempt from byte cap**: Add `"/debug"` to `_BYTE_CAP_EXEMPT_PREFIXES` in `server/main.py` — or verify the cache-stats JSON is always < 256 KB (it will be, but exempting is cleaner).

---

## External Writes the Implementation Will Require

| Type | Target | Why |
|---|---|---|
| `pyproject.toml` edit | `faiss-cpu>=1.7` added to `[project.dependencies]` | Tier-2 FAISS index is a new runtime dep; not present today |
| `pyproject.toml` edit | `ARXMCP_CACHE_DB_PATH` env var documented | New `Config.cache_db_path` field needs the env-var documented in a comment |
| none (prometheus already present) | — | `prometheus-client>=0.20` already in deps from E06_S01 |
