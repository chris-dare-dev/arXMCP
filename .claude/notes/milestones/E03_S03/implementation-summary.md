# E03_S03 Implementation Summary

**Commit:** `9424d17` — `feat(server): singleflight wrapper for query encoding (E03_S03)`
**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 2 (both new)
**Net diff:** +830 / 0

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `server/query_encoder.py` | NEW | Public `encode_query`, lazy state via `_inflight` dict + `ThreadPoolExecutor`, GIL/eviction/error documentation in module docstring |
| `tests/test_query_encoder.py` | NEW | 22 unit tests + 1 env-gated integration test |

## Decisions exercised from research-synthesis.md

| Decision | Where it landed |
|---|---|
| D1 server/ exists; only query_encoder.py is new | confirmed by `ls server/` (README.md + __init__.py only); pyproject.toml unchanged |
| D2 reuse embedder's lazy loaders | `from ingest.embedder import _get_model, _get_tokenizer` — no second model instance |
| D3 encode chain matches `_encode_batch` exactly | `_encode_query_sync` lines 138–172 |
| D4 strip + NFC canonicalization | `_canonicalize` lines 113–130 |
| D5 `asyncio.get_running_loop()` | inside `encode_query`, not the deprecated `get_event_loop()` |
| D6 lock-free dict mutation | comment at lines 218–220; no `await` between `.get()` and `[key] = fut` |
| D7 single-worker executor | line 92, comment explains "serialization not parallelism" |
| D8 completion-based 100ms eviction | `loop.call_later(DEDUP_WINDOW_S, _inflight.pop, key, None)` line 235 |
| D9 unbounded in-flight dedup | by construction — key stays in dict until cleanup callback fires |
| D10 immediate eviction on error | `except` branch lines 226–230 |
| D11 cancellation does not cancel encode | documented in module docstring |
| D12 `.copy()` per caller | both fast and slow paths call `.copy()` before return |
| D13 SINGLEFLIGHT_DEDUP_COUNT observability | module-level int incremented in fast path |
| D14 SHA literal scan test | `TestSingleSourceOfTruth.test_sha_literal_appears_exactly_once_across_ingest_and_server` |
| D15 `asyncio.run()` in tests | every async test wraps `asyncio.run(_run())` — no pytest-asyncio added |
| D16 env-gated integration test | `@pytest.mark.skipif(os.environ.get("ARXMCP_RUN_REAL_BGE_M3") != "1", ...)` |

## Test results

- 400 passed, 2 skipped (1 pre-existing + 1 env-gated integration)
- ruff clean
- 22 new unit tests + 1 skipped integration test

## Acceptance-criteria mapping

| Brief criterion | Test |
|---|---|
| 10 concurrent encode_query → 1 forward pass | `TestSingleflight.test_ten_concurrent_same_query_one_forward_pass` |
| Each waiter gets identical numpy array | `TestSingleflight.test_concurrent_callers_get_independent_array_objects` (same value, distinct objects) |
| 100ms dedup window; 101ms past = new request | `TestEvictionWindow.test_call_after_eviction_window_is_fresh_request` (sleeps DEDUP_WINDOW_S + 50ms) |
| Module docstring includes GIL release sentence | `TestModuleContract.test_docstring_includes_gil_release_rationale` (whitespace-collapsed substring match) |
| BGE_M3_COMMIT_SHA imported, not redefined | `TestSingleSourceOfTruth` — both object-identity check AND filesystem scan |
| Integration test cosine ≥ 0.9999 | `TestRealModelIntegration.test_two_calls_same_query_cosine_ge_9999` (env-gated) |

## Out-of-scope (deferred per brief)

- BM25 query-time matching (E04_S04, E07 Sonnet B)
- Reranker (E07 Sonnet B)
- Server-side caching of full search_papers results by corpus_version (E08_S03)
- Prometheus client wiring for `arxmcp_embed_singleflight_dedup_total` (separate observability milestone — module-level `SINGLEFLIGHT_DEDUP_COUNT` int is the wireable hook)

## Notable design choices documented for the critic

1. **Slow-path future is the executor's future**, not a separately-created `loop.create_future()`. The earlier draft used a synthesized future that nobody awaited, producing "Future exception was never retrieved" warnings. Storing the executor's future directly means all callers (slow and fast paths) await the same object — every exception is retrieved.
2. **Defensive `.copy()` on every return** — including the slow-path return — prevents in-place mutation by one caller from leaking to others. Cost: 4 KB memcpy per call.
3. **Test isolation via autouse fixture** — `_reset_singleflight_state` clears `_inflight` and `SINGLEFLIGHT_DEDUP_COUNT` before AND after each test. Without this, prior `call_later` cleanups could fire mid-next-test and the dedup counter would accumulate masking off-by-one bugs.
4. **`pytest.skipif` on the integration test** — using `@pytest.mark.skipif(os.environ.get("ARXMCP_RUN_REAL_BGE_M3") != "1")` mirrors `test_embedder.py:TestVectorContract` exactly. CI never downloads the 2.3 GB model unless an operator opts in.
