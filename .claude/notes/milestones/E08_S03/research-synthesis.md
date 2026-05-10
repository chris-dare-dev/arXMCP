# E08_S03 — Research synthesis

## Both researchers agree on these load-bearing facts

1. **`prometheus-client>=0.20` is ALREADY a dep** (E06_S01). Single-process registry. `server/health.py` is the established pattern. Add cache metrics in a new `server/metrics.py` module that imports the same default registry.

2. **`corpus_version` already exists**: `resources.corpus_info.version: int`, pinned at startup from `corpus-version.json`. No new plumbing needed.

3. **`RERANKER_VERSION` already exists** in `server/retrieval/rerank.py` and `_build_singleflight_key(query_vec, candidates) -> str` already computes `sha256(vec_bytes + sorted_chunk_ids + version_bytes)`. **The Tier-3 key REUSES this function verbatim** — do NOT reimplement. E07_S03 explicitly deferred the LRU memo to E08_S03.

4. **`faiss-cpu` is NOT installed**. Must add to `[project.dependencies]`. Pin: `faiss-cpu>=1.7`.

5. **`/debug` route prefix does NOT exist** in `server/main.py`. This milestone introduces `server/routes/` as a NEW sub-package and registers `debug_router` via `app.include_router(debug_router, prefix="/debug")`.

6. **AC #1 ("repeated identical query hits Tier-1 and bypasses Phase 1/2/3") REQUIRES modifying `server/handlers/search.py`** — the brief's deliverables list does NOT mention this file but the AC cannot be satisfied without it. Both researchers flagged this. Implementer MUST add the cache lookup BEFORE the encode + ANN path and the cache write AFTER assembling the payload.

7. **`structuredContent` is the cache payload** — `dict[str, Any]`, JSON-serializable. Stored in SQLite as `json.dumps(payload, sort_keys=True).encode("utf-8")` BLOB; held in-process as the deserialized dict. NO pickle (security threat-model precedent).

8. **Failure mode is mandatory: try/except → fall-through to recompute.** `.claude/notes/07-multi-agent-caching.md`: *"Cache layer crash / OOM → Fall through to recompute; log; alert. Caching is performance, not correctness."* Every tier lookup MUST be wrapped.

9. **1% Tier-2 hit sampling**: `random.random() < 0.01` at log time, stdlib `logging`. No reservoir sampling.

10. **Filters & k types**: `filters: dict[str, Any] | None` (treat None as `{}`); `k: int` constrained `[1, 50]` via pydantic Field.

11. **FAISS `IndexFlatIP(1024)` for cosine on L2-normalized BGE-M3 vectors**. Ring buffer = Python deque of 1,000 entries; on overflow, evict oldest and rebuild the FAISS index from the remaining deque (O(n) but n≤1000 dim=1024 is fast).

12. **Test patterns**: `asyncio.run()` in sync test bodies, `monkeypatch` for module paths, `tmp_path` for SQLite file. Module needs `reset_cache_for_tests()` mirroring the existing `reset_resources_for_tests()` / `reset_metrics_for_tests()` patterns.

## Decisions for the implementer

| ID | Decision | Rationale |
|---|---|---|
| D1 | **Stdlib `sqlite3` + `asyncio.to_thread()`** for Tier-1 persistence — NO new `aiosqlite` dep. | Brief 1 didn't recommend; Brief 2 did. The project already follows the "offload sync I/O to executor" pattern (`server/query_encoder.py`). Fewer deps wins. `aiosqlite` is a thin wrapper around the same pattern. |
| D2 | **`server/routes/` as a NEW sub-package** with `__init__.py` + `debug.py`. Even though the existing convention is `server/handlers/`, the brief explicitly says `server/routes/debug.py`. Honor the brief. | Brief is explicit. Adding a sub-package is cheap; deviating from a brief deliverable invites critic findings. |
| D3 | **`Config.cache_db_path: Path = Path("var/arxmcp/cache/retrieval.db")`** added to `server/config.py`. Sibling-of-sibling to `lancedb_path`. Parent directory created at `Resources.startup()`. | Brief 1's recommendation. Shorter than `cache_sqlite_path`. Symmetric with `lancedb_path` field naming. |
| D4 | **`Resources.cache: RetrievalCache \| None = None`**, initialized in `Resources.startup()`, closed in `shutdown()`. Duck-typed like existing `bm25_phase`, `ann_phase`, `rerank_phase` fields. | Both researchers agree. Mirrors established singleton lifecycle. |
| D5 | **`server/metrics.py` is the new module** carrying ONLY cache metrics (Counter for `lookups_total`, `hits_total`, `evictions_total`; Gauge for `bytes`). Use `labelnames=["tier"]` with values `"1"`, `"2"`, `"3"`. The metrics REGISTRY is the default single-process one (same as `server/health.py`). | Brief 2's clear synthesis. Naming follows the existing `arxmcp_*_total` convention. |
| D6 | **`refresh_metrics_from_singleton_state` extended** to call `refresh_cache_metrics(resources.cache)` so scrape-time gauges are up-to-date. Same pattern as the existing `refresh_metrics_from_singleton_state` in `server/health.py`. | Brief 2. Single hook keeps Prometheus discipline consistent. |
| D7 | **DO NOT add `/debug` to `_BYTE_CAP_EXEMPT_PREFIXES`**. Cache-stats JSON is small (<1 KB); the 256 KB cap will never trigger. Exempting opens an unnecessary middleware surface. | Brief 2's cleaner stance. Fewer exceptions = fewer surprises. |
| D8 | **Tier-3 key reuses `_build_singleflight_key`** from `server/retrieval/rerank.py` verbatim. The brief's spec (`sha256(query_embedding_hash + sha256(sorted_candidate_ids_json) + reranker_version_sha)`) is structurally a different formula but produces a cryptographic hash equivalent in security; the existing length-prefix encoding is correct. The Tier-3 LRU stores `lookup_key -> reranked_candidates`. | Brief 1 + Brief 2 converge. Avoids double-hashing AND the brief's "follow-up to E07_S03" framing. |
| D9 | **FAISS thread safety**: protect the ring buffer + index with an `asyncio.Lock`. FAISS `IndexFlatIP.add()` / `.search()` are NOT thread-safe but in single-process asyncio they're called from the event-loop thread. Use `loop.run_in_executor(None, ...)` for `index.search()` only if profiling shows it blocks; for a 1024-dim 1000-entry flat index, search is sub-millisecond. | Brief 1 + Brief 2. Default to in-event-loop FAISS calls; promote to executor only on measured block. |
| D10 | **Tier-1 write-through to SQLite** is async via `asyncio.to_thread(sqlite_conn.execute, ...)`. SQLite opened with `PRAGMA journal_mode=WAL` + `PRAGMA synchronous=NORMAL`. WAL allows concurrent readers (test fixtures can read the same file the cache writer is writing). | Both researchers. WAL is the established cache-friendly mode. |
| D11 | **In-process LRU implementation**: `collections.OrderedDict` with `move_to_end()` on hit + `popitem(last=False)` on overflow. NO `functools.lru_cache` (decorator-based, doesn't compose with TTL or async). NO third-party LRU lib. | Stdlib-only; matches project no-new-deps discipline. |
| D12 | **Tier-2 cold-start no-op**: per the brief and `.claude/notes/07-multi-agent-caching.md`, an empty FAISS index returns "no hit" without exception. Implement as `if len(self._ring_buffer) == 0: return None` BEFORE calling `index.search`. | Brief explicit. Avoids an unnecessary FAISS call on every miss until the ring buffer fills. |
| D13 | **Test isolation**: `reset_cache_for_tests()` clears LRUs (Tier-1 in-memory mirror, Tier-3), resets the FAISS index (`index.reset()`), drops the SQLite file (`tmp_path` based — fixture handles cleanup), and resets all `arxmcp_cache_*` Prometheus counters. Mirror the `reset_metrics_for_tests()` pattern from `server/health.py`. | Both researchers. `prometheus_client` global counters require explicit reset. |

## D-Schema: Tier-1 SQLite schema

```sql
CREATE TABLE IF NOT EXISTS tier1_cache (
    key        TEXT PRIMARY KEY,         -- sha256 hex
    value      BLOB NOT NULL,            -- json.dumps(payload, sort_keys=True).encode()
    expires_at REAL NOT NULL,            -- unix epoch seconds
    corpus_version INTEGER NOT NULL      -- redundant with key but enables WHERE clause
);
CREATE INDEX IF NOT EXISTS idx_expires ON tier1_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_corpus_version ON tier1_cache(corpus_version);
```

Schema-version bump strategy: a `PRAGMA user_version` field. On startup, if `user_version` < `EXPECTED_SCHEMA_VERSION`, drop the table and recreate. This is acceptable for a cache (loss = miss).

## D-Metrics: full Prometheus surface

```
arxmcp_cache_lookups_total{tier="1|2|3"}     Counter
arxmcp_cache_hits_total{tier="1|2|3"}        Counter
arxmcp_cache_evictions_total{tier="1|2|3"}   Counter
arxmcp_cache_bytes{tier="1|2|3"}             Gauge   (current size)
```

## D-Stats: `/debug/cache-stats` JSON shape

```json
{
  "tier1": {"lookups_total": 0, "hits_total": 0, "evictions_total": 0, "bytes_used": 0},
  "tier2": {"lookups_total": 0, "hits_total": 0, "evictions_total": 0, "bytes_used": 0},
  "tier3": {"lookups_total": 0, "hits_total": 0, "evictions_total": 0, "bytes_used": 0}
}
```

`bytes_used` is an estimate (sum of payload byte lengths for Tier-1 / Tier-3; FAISS index size for Tier-2).

## Open questions

1. **search.py integration depth**: AC #1 demands cache integration into `handle_search_papers`. The minimum is `cache.lookup()` before encode and `cache.store()` after assembly. Tier-3 (rerank LRU) integration should land in `handle_search_papers` between the candidate-set step and the rerank step. The implementer should NOT modify the rerank function itself — Tier-3 is an outer wrapper.

2. **Cache-bytes accounting**: per-payload `len(json.dumps(payload).encode())` is an approximation; a precise byte count would need to deserialize on store. Approximation is fine for a Gauge (`bytes_used` is operational telemetry, not a hard limit).

3. **Eviction policy on Tier-1 overflow**: SQLite has 10K row cap. On `store()`, if `SELECT COUNT(*) FROM tier1_cache > 10000`, delete the oldest by `expires_at ASC LIMIT N`. Simple and adequate.

4. **Tier-3 LRU size**: not specified by brief. Recommend 1,024 entries (matches the typical Tier-2 ring-buffer hit rate and the fact that an entry is just a list of chunk IDs — small).

## External writes the implementation will require

NEW RUNTIME DEP — must be flagged at the user-checkpoint boundary:

| Type | Target | Why |
|---|---|---|
| `pyproject.toml` edit | add `faiss-cpu>=1.7` to `[project.dependencies]` | Tier-2 FAISS flat index; not installed today |
| `pyproject.toml` edit | document new `ARXMCP_CACHE_DB_PATH` env-var | New `Config.cache_db_path` field; `extra="forbid"` requires the var be a known field |

NEW FILES (no external write — pure-internal):
- `server/cache.py`
- `server/cache_sqlite.py`
- `server/metrics.py`
- `server/routes/__init__.py` + `server/routes/debug.py`
- `tests/test_cache.py`

MODIFIED FILES (no external write — pure-internal):
- `server/resources.py` (add cache field + init/close)
- `server/handlers/search.py` (cache lookup/store integration)
- `server/main.py` (register debug router)
- `server/health.py` (extend `refresh_metrics_from_singleton_state`)
- `server/config.py` (add `cache_db_path`)
- `pyproject.toml` (add `faiss-cpu`)

NO git push, NO PR creation, NO ticket mutation, NO third-party API call. ONE new runtime dep (`faiss-cpu`).
