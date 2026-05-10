# E08_S03 — Research Brief 2

## 1. In-codebase context

### Design notes that apply

**`07-multi-agent-caching.md`** is the primary authority. Load-bearing quotes:

- "Tier 1: `key = sha256(canonical_form(query) + filters_json + k + corpus_version)` … `canonical_form(query)` is `query.strip()` only — do NOT lowercase, do NOT strip punctuation."
- "Tier 2: `key = nearest centroid in query-embedding space, cosine > 0.97, AND filters match exactly` … Log every Tier-2 hit; sample 1% for human review; tune."
- "Tier 3: `key = sha256(query_embedding_hash + sorted_candidate_id_tuple_hash + reranker_version)` … TTL: 1 hour … store: in-process LRU."
- "Two-key normalization rule (critical): the cache *lookup key* may use aggressive normalization; the *actual query passed to BM25 / embedder* must be unchanged."
- Failure table: "Cache layer crash / OOM → Fall through to recompute; log; alert. Caching is performance, not correctness."

**`06-mcp-server-design.md`** (lines 53–59): `structuredContent` is "the canonical, byte-stable, cache-friendly payload." Tool results are sorted `(score_desc, chunk_id_asc)` deterministically — this means `payload` stored in caches is a `dict[str, Any]` matching the `structuredContent` shape, not a `CallToolResult`.

### What E06_S01 established

`server/resources.py` already owns the singleton lifecycle. The `Resources` dataclass has `corpus_info: CorpusVersionInfo` with `corpus_info.version: int` — this is the `corpus_version` the Tier-1 key needs. `corpus_version` is pinned at startup from `corpus-version.json`. **The `corpus_version` integer is already available at startup; E08_S03 does not introduce it.** The `Resources.startup()` classmethod is the integration point — the cache singleton must be initialized there and stored on `Resources`.

### What E07_S03 established

`server/retrieval/rerank.py` provides `RERANKER_VERSION = f"bge-reranker-v2-m3@{SHA[:8]}"` (module constant). This is the `reranker_version_sha` component of the Tier-3 key. E07_S03 implementation summary notes: "Tier-3 LRU memo (1-hour TTL) is explicitly deferred to a follow-up" — **E08_S03 is that follow-up.** The existing `Resources.rerank_singleflight` is a singleflight (dedup), not a memo (no TTL, no persistence). E08_S03 adds the actual LRU on top.

### `server/health.py` — Prometheus registry

The project already uses `prometheus_client`. Installed in `.venv`: `prometheus_client 0.25.0`. Existing pattern:

```python
from prometheus_client import Counter, Gauge
CORPUS_VERSION_GAUGE = Gauge("arxmcp_corpus_version", "...")
EMBED_SINGLEFLIGHT_DEDUP_COUNTER = Counter("arxmcp_embed_singleflight_dedup_total", "...")
```

Single-process registry (no multiprocess mode). The docstring in `health.py` is explicit: "Default single-process registry; multiprocess mode is explicitly NOT used (the server is single-process by design)." New cache metrics in `server/metrics.py` should import and use the same default `REGISTRY`. Use `Counter` for `lookups_total`, `hits_total`, `evictions_total`; use `Gauge` for `bytes_used`. The metrics refresh pattern (`refresh_metrics_from_singleton_state`) called from the `/metrics` ASGI wrapper is the established hook for scrape-time refresh.

### `server/main.py` — route registration, `/debug` prefix

No `/debug` prefix exists. The router only has `app.include_router(health_router)` plus the mounted `/metrics` and `/mcp` ASGI sub-apps. **This milestone introduces `server/routes/debug.py` and a new `server/routes/` directory.** The `/debug/cache-stats` route should be registered via `app.include_router(debug_router, prefix="/debug")` inside `create_app()`. The new router is NOT exempt from `BodySizeCapMiddleware` — cache stats are small JSON and must remain under 256 KB.

### `server/resources.py` — singleton lifecycle and test patterns

`Resources` is a `@dataclass`. New field pattern: add `cache: RetrievalCache | None = None` (duck-typed like `bm25_phase`, `ann_phase`, `rerank_phase`). The `startup()` classmethod initializes it as the last step before `warm = True`. The `shutdown()` must call `cache.close()` or equivalent to flush the SQLite WAL and release the FAISS index.

Test patterns: `asyncio.run()` in sync test bodies (no `pytest-asyncio`). `monkeypatch` for module-level paths. `tmp_path` for SQLite file. The project pattern for module-level path singletons is to redirect via `monkeypatch.setattr(module, "PATH_CONSTANT", tmp_path / "...")` in `conftest.py` autouse fixtures.

### `server/handlers/search.py` — integration seam

The cache intercept point is `handle_search_papers`. The current flow: `encode_query` → LanceDB ANN → optionally BM25/RRF/rerank → `envelope(...)` → `CallToolResult(content=..., structuredContent=structured)`. The cache's `lookup()` returns the `structuredContent` dict. On a hit, reconstruct `content` from the cached `structuredContent` (re-run `_build_content_blocks`) and return early. On a miss, run the full pipeline, then `store()` the `structuredContent`. **The brief says "E08_S03 does not say modify search_papers" but the AC ("a repeated identical query hits Tier-1 and bypasses Phase 1/2/3") requires integration into `search.py` or the tool dispatcher.**

### `pyproject.toml` — current deps

`faiss-cpu` is **NOT installed** (confirmed: `.venv/bin/pip list` shows no faiss entry). `prometheus_client 0.25.0` is installed. `aiosqlite` is **NOT installed**. Both `faiss-cpu` and `aiosqlite` must be added to `pyproject.toml` dependencies.

### `filters` type

In `server/handlers/search.py`, the signature is `filters: dict[str, Any] | None`. When `filters` is `None`, use `{}` for the JSON fingerprint. The Tier-1 cache key uses `json.dumps(filters or {}, sort_keys=True)`.

### `k` type

`k: int = 10` with `ge=1, le=50` (pydantic `Field` constraint). Always an integer in `[1, 50]`, never `None` or sentinel.

---

## 2. Prior decisions and lessons

### Fault isolation (try/except wrapping)

The design note is explicit: "Caching is performance, not correctness." Every tier lookup must be wrapped in `try/except Exception` that logs and falls through to a cache miss. A FAISS crash or SQLite I/O error must never propagate to the caller. This is a MUST for the implementation — not doing it violates the primary design invariant.

### 1% sampling for Tier-2 hits

Note 07 says "Log every Tier-2 hit; sample 1% for human review." The mechanism: `random.random() < 0.01` at log time. Use `logger.info("tier2_hit_sample ...")` when the condition fires. No reservoir sampling — simple Bernoulli at 1% is sufficient given the expected workload. Logs go to the standard structlog/logging stream (the project uses stdlib `logging`).

### Async stack

The project is async throughout (`async def handle_search_papers`, `asyncio.run()` in tests). The cache's `lookup()` and `store()` must be `async def`. SQLite I/O via `aiosqlite` is the correct pattern (not blocking `sqlite3` in the event loop). FAISS operations are CPU-bound synchronous; off-load to `loop.run_in_executor(None, ...)` to avoid blocking the event loop. This is the same discipline as the BGE-M3 encoder.

### Tier-3 deferred memo vs. singleflight

E07_S03 implementation summary: "Tier-3 LRU memo (1-hour TTL) — deferred to a follow-up. The brief asks for the singleflight wrapper only; the LRU is deferred to E08_S03." The Tier-3 key in E07_S03 uses `sha256(query_vec.tobytes() + sorted_chunk_ids + version_bytes)` as the singleflight key. E08_S03's Tier-3 uses `sha256(query_embedding_hash + sha256(sorted_candidate_ids_json) + reranker_version_sha)` per the milestone brief. These are semantically the same key; the implementer should use the same hash from the rerank singleflight key where possible to avoid double-hashing.

### `store` idempotency

The brief does not say `store` must be idempotent, but multiple concurrent writes to the same key are the normal case (singleflight is NOT on the cache write path). The LRU `__setitem__` must be thread-safe or protected by `asyncio.Lock`. SQLite in WAL mode + serialized writes handles this for Tier-1. The in-process LRU for Tier-3 must use an `asyncio.Lock`.

### Conflict with brief: `server/metrics.py` vs. `server/health.py`

The brief says to create `server/metrics.py` for cache-specific Prometheus metrics. The existing `server/health.py` already defines metrics using the same registry. **No conflict** — `metrics.py` is a new module for cache counters/gauges, imported by `health.py`'s refresh function. The naming convention is established: `arxmcp_cache_lookups_total{tier}`, `arxmcp_cache_hits_total{tier}`, `arxmcp_cache_evictions_total{tier}`, `arxmcp_cache_bytes{tier}`. Use `labelnames=["tier"]` with values `"1"`, `"2"`, `"3"`.

---

## 3. External sources

### FAISS-CPU

`faiss-cpu` on PyPI (latest: 1.10.0 as of May 2026). Ships `faiss` Python bindings compiled against CPU BLAS. For Tier-2's cosine similarity, use `faiss.IndexFlatIP` (inner product) on L2-normalized vectors (cosine ≈ dot product on unit vectors). API:

```python
import faiss, numpy as np
index = faiss.IndexFlatIP(dim)  # dim=1024 for BGE-M3
vecs = np.vstack(embeddings).astype(np.float32)
faiss.normalize_L2(vecs)
index.add(vecs)
D, I = index.search(query_vec.reshape(1, -1), k=1)  # D is cosine similarity
```

Ring buffer of 1,000 embeddings: use `index.reset()` and rebuild from the ring buffer when it reaches capacity, OR use `faiss.IndexIDMap` to track IDs and remove stale entries. Simpler: rebuild from a Python deque of (embedding, metadata) on each add when size > 1000.

### prometheus_client (0.25.0 installed)

Starlette/ASGI integration: `prometheus_client.make_asgi_app()` — already used in `server/main.py`. No additional integration needed. Single-process mode (no `PROMETHEUS_MULTIPROC_DIR`). For new counters/gauges, instantiate at module import time (same as `health.py`). The refresh-at-scrape pattern: the `/metrics` wrapper in `main.py` calls `refresh_metrics_from_singleton_state(resources)` — extend this to also call `refresh_cache_metrics(resources.cache)`.

### SQLite WAL mode and asyncio

Use `aiosqlite` (async wrapper around `sqlite3`). WAL mode: `await db.execute("PRAGMA journal_mode=WAL")` at connection time. Thread safety: `aiosqlite` runs SQLite in a thread pool executor, so WAL mode + serialized writes is safe. Schema: one table `tier1_cache (key TEXT PRIMARY KEY, value BLOB, expires_at REAL)`. On startup, load all rows where `expires_at > time.time()` into the in-process LRU. On TTL expiry during lookup, delete and treat as miss. Background eviction (to bound disk size to ~10K entries) can run as an async task or on `store()`.

---

## Open questions

1. **`store()` idempotency spec**: multiple concurrent writes to the same key will occur (singleflight is on the embedder, not the cache). The `store()` implementation must handle this gracefully (last-write-wins is fine for an LRU). No action needed — just confirm the implementer uses `asyncio.Lock` on the in-process LRU.

2. **Tier-2 ring buffer eviction**: when the 1,000-entry ring buffer fills, the oldest entry is evicted. The FAISS index must be rebuilt (no `remove` in `IndexFlatIP`). Rebuild cost at 1,000 × 1024-dim float32 vectors is negligible (<1ms). Confirm: rebuild from scratch on each add once capacity is reached, or use a separate deque + periodic full rebuild. Recommendation: deque of (vec, metadata, timestamp), rebuild on every add (O(n) but n≤1000 and dim=1024 — fast).

3. **Integration into `search.py`**: the brief's deliverables do not list `server/handlers/search.py` as modified, but AC #1 ("a repeated identical query hits Tier-1 and bypasses Phase 1/2/3") requires it. The implementer MUST modify `handle_search_papers` to call `cache.lookup()` before the pipeline and `cache.store()` after. This is not optional.

4. **Tier-2 filter fingerprint**: the Tier-2 hit requires "exact filter match." The filter fingerprint is `sha256(json.dumps(filters or {}, sort_keys=True).encode())` — same as in the Tier-1 key. Implement once in a helper function shared by both tiers.

5. **`/metrics` endpoint already wired**: yes. `server/main.py` mounts `metrics_wrapper` at `/metrics`. Adding new metrics to `server/metrics.py` automatically includes them in the existing exposition — no new wiring needed. The refresh-at-scrape call needs to be extended to `refresh_cache_metrics`.

6. **SQLite file path**: the brief does not specify the path. Recommendation: `Config.cache_sqlite_path: Path = Path("var/arxmcp/cache/tier1.db")`. Needs a new `Config` field — but `Config` uses `extra="forbid"`, so omitting the `ARXMCP_CACHE_SQLITE_PATH` env-var declaration would cause startup failure if accidentally set. Add the field.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `pyproject.toml` dep add | `faiss-cpu>=1.7` | Tier-2 FAISS flat index; not installed |
| `pyproject.toml` dep add | `aiosqlite>=0.19` | Tier-1 async SQLite persistence; not installed |
| New directory create | `server/routes/` | Milestone deliverable `server/routes/debug.py` |
| New file | `server/cache.py` | `RetrievalCache` class |
| New file | `server/cache_sqlite.py` | SQLite persistence for Tier 1 |
| New file | `server/routes/debug.py` | `GET /debug/cache-stats` endpoint |
| New file | `server/metrics.py` | Cache Prometheus counters/gauges |
| New file | `tests/test_cache.py` | Unit tests |
| Modify | `server/resources.py` | Add `cache: RetrievalCache` field + init in `startup()` + close in `shutdown()` |
| Modify | `server/handlers/search.py` | Integrate `cache.lookup()` / `cache.store()` into pipeline |
| Modify | `server/main.py` | Register `debug_router` from `server/routes/debug.py` |
| Modify | `server/health.py` | Extend `refresh_metrics_from_singleton_state` to include cache metrics |
| Modify | `server/config.py` | Add `cache_sqlite_path: Path` field |
