# E08_S03 — Implementation summary

## What shipped

Five new files + targeted edits to six existing files, implementing the
3-tier MCP-side retrieval cache. Tier-1 SQLite-backed exact-query memo,
Tier-2 in-process FAISS semantic-query memo at cosine ≥ 0.97, Tier-3
in-process LRU rerank-set memo (the deferred follow-up to E07_S03).

| Path | Status | Purpose |
|---|---|---|
| `server/cache.py` | NEW (~620 LOC) | `RetrievalCache` class — all three tiers, async API, fault-isolation try/except per design constitution. Module-level singleton + `get_cache()` / `set_cache()` / `reset_cache_for_tests()`. |
| `server/cache_sqlite.py` | NEW (~310 LOC) | `Tier1Store` — async SQLite via stdlib + `asyncio.to_thread`. WAL mode, schema-version migration, lazy TTL eviction, 10K-row LRU cap. |
| `server/metrics.py` | NEW (~165 LOC) | Prometheus `Counter` / `Gauge` for `arxmcp_cache_lookups_total{tier}`, `_hits_total{tier}`, `_evictions_total{tier}`, `_bytes{tier}`. Tier label constants + `refresh_cache_metrics()` scrape-time hook. |
| `server/routes/__init__.py` + `server/routes/debug.py` | NEW (~80 LOC) | `GET /debug/cache-stats` JSON endpoint. New `server/routes/` sub-package per the brief's deliverable list. |
| `tests/test_cache.py` | NEW (~485 LOC) | 28 tests across 8 classes covering all 6 ACs + key-derivation regression for the level-omission bug + failure-mode discipline + persistence-across-restart. |
| `server/config.py` | MODIFIED | Add `cache_db_path: Path` field (default `var/arxmcp/cache/retrieval.db`). |
| `server/resources.py` | MODIFIED | Add `cache: RetrievalCache \| None` field; init in `startup()` after corpus_version is pinned; close in `shutdown()`; clear module-level singleton on shutdown. |
| `server/main.py` | MODIFIED | Register `debug_router` from `server/routes/debug.py` under `/debug` prefix (NOT exempt from body-size cap). |
| `server/health.py` | MODIFIED | Extend `refresh_metrics_from_singleton_state` to call `refresh_cache_metrics(resources.cache)` so the bytes gauges refresh on every Prometheus scrape. |
| `server/handlers/search.py` | MODIFIED | Cache-lookup integration: Tier-1 lookup BEFORE encode + Tier-2 lookup AFTER encode + cache-store on miss path. Threads `level` through all key derivation. |
| `pyproject.toml` | MODIFIED | Add `faiss-cpu>=1.7` runtime dep. |
| `tests/conftest.py` | MODIFIED | `os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")` at module load — workaround for the macOS faiss-cpu × PyTorch OpenMP-loader collision (SIGSEGV in pytest when both libs init in the same process). |

Total: 28 new cache tests pass; full project suite **1066 passed, 4 skipped, 0 failed** (was 1038); `ruff check .` clean.

## How acceptance criteria are met

| AC | Where it's enforced |
|---|---|
| Repeated identical query hits Tier-1 and bypasses Phase 1/2/3 | `tests/test_cache.py::TestTier1HitMissCycle::test_tier1_miss_then_hit` — drives the cache through miss → store → hit, asserts second call returns the cached payload AND `hit_tier == TIER_1`. Integration: `server/handlers/search.py` calls `cache.lookup_search(...)` BEFORE `encode_query` and returns early on hit. |
| Semantically similar query (cos ≥ 0.97) hits Tier-2 and bypasses Phase 1/2/3 | `tests/test_cache.py::TestTier2SemanticHit::test_tier2_hit_at_cosine_098` — synthesizes two L2-normalized embeddings at exact cosine 0.98 (verified via `np.dot`), asserts the second-query lookup returns the first-query payload via Tier 2. Companion `test_tier2_miss_at_cosine_095` proves the threshold is real. |
| Server restart with corpus_version=N+1: all corpus_version=N entries unreachable | `tests/test_cache.py::TestCorpusVersionInvalidation::test_corpus_version_bump_unreachables_old_entries` — opens cache at v6, writes entry, closes, reopens at v7 against the SAME SQLite file, asserts the v6 entry is unreachable from v7 (different hash key). Hash construction makes this invariant by-design. |
| `GET /debug/cache-stats` returns valid JSON | `tests/test_cache.py::TestDebugCacheStatsEndpoint` — two tests: empty cache returns all-zero shape; populated cache reflects per-tier counters. The endpoint at `server/routes/debug.py` returns 200 with the per-tier `{lookups_total, hits_total, evictions_total, bytes_used}` shape. |
| `pytest tests/test_cache.py` passes | 28 tests pass in 0.28 s. |
| Prometheus metrics emitted at `/metrics` | `tests/test_cache.py::TestPrometheusMetricsExposition` — three tests verify the four metric families exist with all three tier labels, that `refresh_cache_metrics` updates the bytes gauge from cache state, and that a `None` cache is a no-op. The metrics live in the default single-process registry (same as `server/health.py`) and are automatically included in the existing `/metrics` ASGI app. |

## Design choices made (with rationale anchored to research synthesis)

- **Stdlib `sqlite3` + `asyncio.to_thread`** instead of `aiosqlite` (D1) — fewer deps. The project already follows the "offload sync I/O to executor" pattern (BGE-M3 encoder, LanceDB).
- **`server/routes/` as a NEW sub-package** (D2) — honors the brief deliverable string verbatim even though the existing convention is `server/handlers/`.
- **`Config.cache_db_path: Path`** at `var/arxmcp/cache/retrieval.db` (D3) — sibling-of-sibling to `lancedb_path`; parent dir created at `Resources.startup`.
- **`Resources.cache` duck-typed Any** (D4) — mirrors the existing `bm25_phase`, `ann_phase`, `rerank_phase` field shape.
- **Tier label constants `TIER_1 = "1"`, `TIER_2 = "2"`, `TIER_3 = "3"`** in `server/metrics.py` (D5) — string-typed so the Prometheus label space stays canonical; constants prevent typos.
- **`refresh_cache_metrics()` called from `refresh_metrics_from_singleton_state`** (D6) — single scrape-time hook.
- **DO NOT exempt `/debug` from body-size cap** (D7) — cache stats are sub-1KB; fewer middleware exceptions = fewer surprises.
- **Tier-3 reuses `_build_singleflight_key`** from `server/retrieval/rerank.py` verbatim (D8) — no double-hashing; Tier-3 is the LRU follow-up E07_S03 explicitly deferred.
- **FAISS in single-process asyncio with `asyncio.Lock`** (D9) — `IndexFlatIP.search()` on 1024-dim flat index of ≤1000 entries is sub-millisecond; no executor needed.
- **`OrderedDict` LRU** (D11) — stdlib, composes with TTL + async naturally.
- **Tier-2 cold-start no-op** (D12) — empty ring buffer returns `None` BEFORE calling `index.search`.
- **`KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py`** (NEW, post-implementation) — the `faiss-cpu` + PyTorch OpenMP collision on macOS produced a SIGSEGV in the full pytest run. The documented Intel-MKL workaround set at conftest module load time fixes it without touching production code.

## Deviations from the brief

- **`level` argument added to the Tier-1 cache key** (NOT in the brief). The brief specifies key as `sha256(canonical_form(query) + filters_json + k + corpus_version)` but `search_papers` accepts a `level` argument (`"theorem" | "section" | "paper"`) whose value materially changes the result envelope (dedup-by-paper, dedup-by-section, no dedup). Caching across distinct `level` values was a CORRECTNESS BUG — verified empirically by `tests/test_tools_all.py::TestToolsSmoke::test_search_papers_level_paper` failing on first integration. Fix: extend `derive_tier1_key(..., level: str | None = None)` and `lookup_search/store_search(..., level=)`. Regression test `test_level_change_changes_key` pins the new behavior.
- **`server/handlers/search.py` is modified** even though the brief's "Deliverables" section did not list it. AC #1 ("repeated identical query hits Tier-1 and bypasses Phase 1/2/3") cannot be satisfied without integration. Both research briefs flagged this in their Open Questions; the synthesis explicitly called it out (D-Open-1).

## Failure-mode discipline

Per `.claude/notes/07-multi-agent-caching.md`: *"Cache layer crash / OOM → Fall through to recompute; log; alert. Caching is performance, not correctness."*

Every tier lookup AND store is wrapped in `try/except Exception` that logs and falls through. A FAISS crash, SQLite I/O error, or Prometheus library glitch returns a cache miss — not a 500. Verified by `tests/test_cache.py::TestFailureModeDiscipline::test_tier1_get_swallows_store_error` which monkey-patches `store.get` to raise `OSError` and asserts `lookup_search` returns `(None, "")` rather than raising.

## External writes performed

- `pyproject.toml` modified — `faiss-cpu>=1.7` runtime dep added (the brief implicitly requires this; flagged in research synthesis as the only external-write at the user-checkpoint boundary).
- `pip install 'faiss-cpu>=1.7'` ran in `.venv/` (1.13.2 installed) so test suite has the runtime available.

NO git push. NO PR. NO third-party API call. NO data exfiltration.

## Files for the critic to focus on

- `server/cache.py:300-400` — Tier-1 lookup/store path (mirror dance + LRU + JSON serialization)
- `server/cache.py:430-510` — Tier-2 FAISS lookup + ring-buffer overflow + index rebuild
- `server/cache.py:520-580` — Tier-3 LRU + reuse of `_build_singleflight_key`
- `server/cache_sqlite.py:140-200` — `Tier1Store.open` schema-version migration discipline
- `server/handlers/search.py:107-170` — cache integration in `handle_search_papers`; verify `level` is correctly threaded through ALL three call sites (Tier-1 lookup, Tier-2 lookup, store)
- `tests/test_cache.py::TestKeyDerivation` — verify the level-omission bug regression test is sufficient
- `tests/conftest.py:13-30` — KMP workaround; would the same workaround need to fire in production?
