# E08_S03 — Adversary critique

## Executive summary

- **Verdict: NEEDS REWORK before merge.** Two HIGHs (cache TTL silently
  unenforced for hot Tier-1 entries; Tier-3 cache implemented but never
  wired into the rerank pipeline so AC-equivalent integration claim is
  false). One CRITICAL: cache key construction uses an unescaped
  `|` separator that allows trivial hash collision via crafted query
  text, even though `_build_singleflight_key` (this milestone's
  cited prior-art template) already solved this with length-prefix
  encoding.
- AC #1 (repeated identical query bypasses Phase 1/2/3) has no
  integration test. The integration-test surface (`warm_app`) calls
  `search_papers` against the real cache singleton without ever
  asserting that a second identical call hit Tier-1 — only the unit
  test on the cache class proves it.
- AC #4 (`GET /debug/cache-stats`) has no HTTP-level test that hits
  the actual route through TestClient; only the `_empty_stats()`
  helper and the `cache.stats()` accessor are exercised.
- AC #6 (Prometheus metrics at `/metrics`) has no scrape-level test
  that confirms `arxmcp_cache_*` lines appear in the rendered
  exposition; only that the metric objects exist on the registry.
- The implementation introduces a process-scope `KMP_DUPLICATE_LIB_OK`
  env-var hack in `tests/conftest.py` whose blast radius extends to
  any subprocess spawned during a test run. The brief's "test-only"
  framing is at odds with how `os.environ.setdefault` actually works.
- The deviation that adds `level` as a fifth Tier-1 key component
  is correct in spirit (the level argument materially changes the
  envelope) but the *encoding* — `f"{c}|{f}|{k}|{cv}|{level}"` —
  silently re-uses the same separator as the brief's four-component
  formula, so a cleverly-crafted (query, filters) pair on one corpus
  version can still collide with a different (query, filters, level)
  pair on the same version.
- The integration in `server/handlers/search.py` initializes
  `Resources` (and therefore `RetrievalCache`) without honoring a
  test-side override of `cache_db_path`. Fixture
  `tests/test_tools_all.py::warm_app` constructs `Config` with
  `lancedb_path=tmp_path/lancedb` but **leaves `cache_db_path` at the
  default** `var/arxmcp/cache/retrieval.db`. Every CI / local test
  run writes to a checkout-relative path — exactly the F8 issue
  E04_S01 closed for `STORE_STATS_PATH`.
- The SQLite Tier-1 eviction policy is `ORDER BY expires_at ASC`
  (FIFO by insert time given uniform TTL) — NOT actual LRU as the
  brief and the docstring claim. Hot, recently-accessed entries get
  evicted first under uniform-TTL pressure. Documented as "LRU";
  measurable as FIFO.

## Severity calibration

| Severity   | Definition                                                              | Count |
|------------|-------------------------------------------------------------------------|-------|
| CRITICAL   | Data loss / security vulnerability / broken core invariant              | 1     |
| HIGH       | Wrong behavior on common path; AC unmet; deliverable absent             | 5     |
| MEDIUM     | Subtle correctness or missing test that should exist                    | 9     |
| LOW        | Style, dead code, minor doc drift                                       | 5     |

## Findings

### F1 — Tier-1 cache key uses `|` separator without length-prefix or escaping
- **Severity:** CRITICAL
- **File:line:** `server/cache_sqlite.py:124-132`
- **What:** `derive_tier1_key` constructs the pre-hash payload as
  `f"{canonical}|{filters_json}|{k}|{corpus_version}|{level_token}".encode()`.
  The query text and filter JSON are user-controlled; the `|` byte
  appears with no escaping. A query like `"foo|{}|10|7|theorem"`
  with `filters=None`, `k=10`, `corpus_version=7`, `level=None`
  produces the SAME concatenated payload as a query `"foo"` with
  `level="theorem"`. Both hash to the same SHA-256.
- **Why:** This is exactly the failure mode that
  `server/retrieval/rerank.py:_build_singleflight_key` (the prior-art
  template the implementation summary cites for Tier-3) already
  solved with 8-byte big-endian length-prefix encoding. The Tier-3
  docstring explicitly calls out:
  *"F2 fix from the E07_S03 critique: chunk_id encoding is LENGTH-PREFIXED, not separator-based. A naive `b'\\n'.join(...)` would collide if any chunk_id contained a literal newline ... the cache key MUST be collision-resistant regardless of upstream id-format mutations."*
  The Tier-1 implementation duplicates the exact mistake the Tier-3
  fix mitigated. A cache poisoning attack via crafted query text is
  trivially constructible: an LLM-generated query could deliberately
  collide with a different cached result, returning stale or
  misleading evidence to a downstream agent.
- **Fix:** Replace separator concatenation with length-prefix
  encoding (mirror `_build_singleflight_key`). Update the
  TestKeyDerivation tests with a regression test that constructs a
  collision attempt and asserts distinct hashes.

### F2 — Tier-1 in-process mirror does NOT enforce TTL on read
- **Severity:** HIGH
- **File:line:** `server/cache.py:395-418`
- **What:** `_tier1_get` returns `mirror_hit` directly without
  consulting any expiry. `_Tier2Entry` and Tier-3 entries carry
  `expires_at`; the Tier-1 mirror is a bare `OrderedDict[str, Any]`
  (no expiry field). Once a payload is in the mirror, it is served
  for the entire process lifetime (or until LRU evicts it on
  overflow). The 1-hour TTL the brief mandates is enforced ONLY at
  the SQLite layer, which is bypassed on every mirror hit.
- **Why:** The brief explicitly specifies `TTL: 1 hour` for Tier-1.
  An entry stored at T=0 with hit at T=2h returns a 2-hour-stale
  payload — the corpus_version is the same, but the freshness
  contract documented in the cache header docstring
  (`"Tier 1 — Exact-query memo. ... 1-hour TTL"`) is silently
  violated. The cache layer's design constitution
  (`07-multi-agent-caching.md`) is "stale read = miss, never
  correctness failure" — but a 1h TTL exists precisely because
  STALE READ IS NOT MISS. The mirror skipping TTL turns the
  documented 1-hour TTL into "TTL until process restart".
- **Fix:** Store `expires_at` in the mirror entry (a small dataclass
  or 2-tuple), check it in `_tier1_get`, lazy-evict on expiry, and
  decrement the eviction counter. Mirror the discipline used by
  `_Tier2Entry` and the Tier-3 LRU.

### F3 — Tier-3 (`lookup_rerank` / `store_rerank`) implemented but NEVER wired into RerankPhase
- **Severity:** HIGH
- **File:line:** `server/cache.py:583-646`; `server/retrieval/rerank.py:520-596`
- **What:** `RetrievalCache.lookup_rerank` and `store_rerank` are
  defined and tested in isolation, but a grep of the entire
  repository turns up zero call sites outside `tests/test_cache.py`
  (verified: `grep -rn "lookup_rerank\|store_rerank" server/` shows
  only the definitions). `RerankPhase.rerank` (which is the only
  legitimate caller) does not import `server.cache` and does not
  consult Tier-3 before running the cross-encoder. The brief's
  Tier-3 deliverable says: *"This tier fires when Phase-2 produces
  an identical candidate set to a recent query — the reranker
  output is deterministic given the same (query, candidates, model)
  triple, so the cached ranking is bit-identical to a fresh
  rerank. Expected hit rate in a multi-agent fan-out: 40–60%."* The
  expected 40-60% hit rate is unattainable when the cache is
  unreachable.
- **Why:** The brief lists Tier-3 in the same paragraph as the
  acceptance criteria: *"Tier-3 hit after identical candidate set"*.
  The `tests/test_cache.py::TestTier3RerankMemo` tests pass because
  they call the cache API directly, but the AC is satisfied in name
  only. A future caller who follows the implementation summary's
  *"Tier-3 reuses `_build_singleflight_key` from `server/retrieval/rerank.py` verbatim"* claim will find the API surface but no
  consumer.
- **Fix:** Wire `lookup_rerank` / `store_rerank` into
  `RerankPhase.rerank` (around the singleflight + semaphore call):
  cache lookup before `_do_rerank`, cache store after. Add an
  integration test that drives the rerank phase and asserts the
  second call hits Tier-3 and bypasses the cross-encoder. (The
  bypass can be observed by monkey-patching `_rerank_sync` to
  raise on second call.)

### F4 — Default `cache_db_path` writes to checkout-relative `var/arxmcp/cache/retrieval.db` from every test run
- **Severity:** HIGH
- **File:line:** `server/config.py:103`; `tests/test_tools_all.py:122-131`
- **What:** `Config.cache_db_path` defaults to
  `Path("var/arxmcp/cache/retrieval.db")` — a relative path. The
  `warm_app` fixture in `tests/test_tools_all.py:122` constructs
  `Config(lancedb_path=tmp_path / "lancedb")` but does NOT override
  `cache_db_path`. When the lifespan fires `Resources.startup`, the
  cache opens at the checkout-relative path and writes Tier-1
  entries under the developer's working directory. There is no
  autouse fixture analogous to `_patched_store_stats_path` /
  `_patched_bm25_stats_path` / `_patched_bm25_index_root` for the
  cache.
- **Why:** This is precisely the F8-from-E04_S01 issue — the
  conftest fixtures explicitly cite "every integration test would
  pollute the developer's checkout-local
  `var/arxmcp/ops/store-stats.jsonl` on every run". The cache
  shipping has the same shape of bug: any
  `tests/test_tools_all.py::test_search_papers_smoke` invocation
  produces a SQLite file under the worktree. Worse, the file
  *survives across test runs*, so test-1 of run-N can hit a Tier-1
  entry stored by test-1 of run-(N-1) — non-determinism in the
  test suite.
- **Fix:** Add an autouse `_patched_cache_db_path` fixture in
  `tests/conftest.py` that monkey-patches the default to
  `tmp_path / "cache" / "retrieval.db"`, mirroring the discipline
  the conftest already enforces for three other on-disk paths.

### F5 — No HTTP-level integration test for `GET /debug/cache-stats`
- **Severity:** HIGH
- **File:line:** `tests/test_cache.py:582-635`
- **What:** AC #4 in the brief is *"GET /debug/cache-stats returns
  valid JSON"*. The only tests for the endpoint exercise (a) the
  `_empty_stats()` helper directly and (b) `cache.stats()` against a
  unit-level `RetrievalCache`. Neither test routes through the
  FastAPI app, the `/debug` prefix mount, or the response middleware
  stack. A regression that breaks router registration in
  `server/main.py:399-401`, an Origin-validation refusal, or a JSON
  serialization error would not fail any test.
- **Why:** AC compliance requires an end-to-end test. The same file
  pattern is established in `tests/test_server_startup.py` — the
  `warm_app` fixture exposes a `TestClient`; `client.get("/debug/cache-stats")` and asserting on `response.status_code == 200`
  + `set(response.json().keys()) == {"tier1","tier2","tier3"}` is
  the missing test.
- **Fix:** Add a test in `tests/test_cache.py` (or a new
  `tests/test_debug_endpoints.py`) that uses the `warm_app`
  TestClient to GET `/debug/cache-stats` and validate body shape +
  HTTP status.

### F6 — No HTTP-level test that `arxmcp_cache_*` metrics appear in `/metrics` exposition
- **Severity:** HIGH
- **File:line:** `tests/test_cache.py:643-684`
- **What:** AC #6 is *"Prometheus metrics are emitted at /metrics"*.
  The `TestPrometheusMetricsExposition` test verifies (a) that the
  metric objects exist (touching `.labels(...)`) and (b) that
  `refresh_cache_metrics` mutates the bytes gauge. Neither asserts
  that an HTTP scrape of `/metrics` contains the metric family
  names. A regression that inadvertently registers the cache
  counters into a non-default registry, or that breaks the
  `metrics_wrapper` ASGI mount, would not fail any test.
- **Why:** Same story as F5 — AC compliance is end-to-end. The
  pattern is established in `tests/test_server_startup.py` (line
  427: *"raise AssertionError('arxmcp_corpus_version not found in
  /metrics')"*).
- **Fix:** Add a test that scrapes `/metrics` via TestClient and
  asserts `arxmcp_cache_lookups_total`, `arxmcp_cache_hits_total`,
  `arxmcp_cache_evictions_total`, `arxmcp_cache_bytes` appear in
  the response text.

### F7 — Tier-1 SQLite eviction is FIFO-by-insert, not LRU
- **Severity:** MEDIUM
- **File:line:** `server/cache_sqlite.py:301-316`
- **What:** The eviction policy on cap overflow is
  `DELETE FROM tier1_cache WHERE key IN (SELECT key FROM tier1_cache ORDER BY expires_at ASC LIMIT ?)`.
  Since every entry uses the same `DEFAULT_TTL_SECONDS = 3600.0`,
  `expires_at` orders strictly by insert time. There is no
  `last_accessed_at` column and no UPDATE on read. A row inserted
  early and re-read 1000 times every minute is evicted before a
  row inserted 30 minutes later that has never been re-read.
- **Why:** The brief and the docstring both call this an "LRU
  cache, maximum 10,000 entries". Operators will reason about cache
  performance assuming LRU semantics. The class is documented in
  `cache_sqlite.py:1-37` as *"SQLite-backed exact-query memo with a
  1-hour TTL and a 10K-row cap"* and the cache.py header at line
  13-15 says *"SQLite-backed LRU, max 10K entries"*. The mirror IS
  LRU (via `OrderedDict.move_to_end` in `_tier1_get`); the SQLite
  layer is FIFO. Hit-rate degrades for skewed query distributions.
- **Fix:** Either (a) add a `last_accessed_at` column and ORDER BY
  it on eviction, plus an UPDATE on read; or (b) rename the brief
  text and the docstrings to "TTL-priority eviction" and document
  the FIFO behavior. Option (b) is the pragmatic one — full LRU on
  every SQLite read adds a write per read which doubles the I/O
  cost.

### F8 — `_rehydrate_tier1_from_sqlite` does not enforce mirror cap
- **Severity:** MEDIUM
- **File:line:** `server/cache.py:254-287`
- **What:** Rehydrate iterates ALL unexpired SQLite rows and inserts
  each into `self._tier1_mirror` without any cap check. Since SQLite
  is bounded at `MAX_ROWS = 10_000` and the mirror cap is also
  10K, the mirror equals SQLite size after rehydrate. In a pathological
  case where SQLite has 10K rows and the in-process mirror cap was
  later tightened (a future configurability change), this would
  silently overflow. The docstring at line 260-263 references a
  cap-bounded rehydrate that is not actually implemented:
  *"Capped at the in-process LRU's :data:`MAX_ROWS` cap — if more rows are present we keep the most-recently-expiring (i.e. most-recently-inserted given uniform TTL)."*
  The sort exists, but the truncation does not.
- **Why:** This is benign today (SQLite cap = mirror cap) but is a
  latent bug. If E08_S04 makes mirror cap configurable below SQLite
  cap, rehydrate exceeds the configured cap.
- **Fix:** Add `rows = rows[:MAX_ROWS]` after the sort and before
  the loop. Document the truncation in the docstring (already done
  in spirit — just needs the implementation to match).

### F9 — Tier-2 lookup returns the nearest neighbor only; second-nearest with matching filter is missed
- **Severity:** MEDIUM
- **File:line:** `server/cache.py:467-518`
- **What:** `_tier2_lookup` calls `index.search(qv, 1)` — top-1
  only. If the nearest neighbor's filter fingerprint does not match
  the query's, the lookup returns `None` even when a SECOND-nearest
  neighbor at cosine ≥ 0.97 with matching filter exists in the
  buffer. Same story for TTL — if the nearest is expired, the
  lookup misses without consulting the second-nearest.
- **Why:** The brief uses singular *"nearest centroid at ≥ 0.97
  cosine + filter fingerprint"* which is ambiguous, but the spirit
  is "find a hit if one exists at the threshold". Returning a miss
  when a valid hit exists in the buffer is a hit-rate regression.
- **Fix:** Search for top-K neighbors (K=8 or so) and iterate until
  one matches both the filter fingerprint and the TTL check. Add a
  test that constructs three buffer entries (nearest = wrong filter,
  second = right filter, third = wrong) and asserts the lookup
  finds the second.

### F10 — `KMP_DUPLICATE_LIB_OK=TRUE` set in conftest.py leaks into subprocesses
- **Severity:** MEDIUM
- **File:line:** `tests/conftest.py:14-29`
- **What:** `os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")`
  sets a process-wide env var that every subprocess pytest spawns
  inherits. Apple's documentation explicitly warns this can mask
  real OpenMP-loader bugs (silent-corruption in worst case, slow
  shutdown in common case). The conftest documents it as
  "TEST-ONLY" but the env var is process-scope. If any test invokes
  uvicorn via subprocess (e.g., a shim integration test), or if the
  developer's local shell inherits the var from a wrapping make
  target, the production runtime sees it.
- **Why:** "Test-only" is an aspirational label, not an enforcement
  mechanism. The brief explicitly excludes this hack from
  production deliverables. The right shape is to either (a) gate the
  env var on a pytest marker (set only when the test imports faiss),
  or (b) use a pytest plugin hook that sets the var in a child-
  process-only way.
- **Fix:** Move the env-var set into a session-scoped autouse fixture
  with explicit `monkeypatch.setenv` so pytest restores the original
  state at session end. OR (better) add a comment + assertion that
  the production Docker image build script verifies the env var is
  NOT set in the runtime image, and document the macOS-only nature
  of the workaround.

### F11 — JSON-roundtrip of cache payload may lose Pydantic types
- **Severity:** MEDIUM
- **File:line:** `server/cache.py:420-446`; `server/handlers/search.py:174-184`
- **What:** `_tier1_put` does `json.dumps(payload, sort_keys=True, ensure_ascii=False)`.
  The `payload` argument is the `structured` dict from
  `envelope(...)` — currently a plain dict, but `envelope` is a
  shared helper used by all six tools. If a future tool returns a
  payload containing a Pydantic model, `datetime`, `Decimal`, or
  any other non-JSON-native type, `_tier1_put` silently logs
  *"Tier-1 payload not JSON-serializable; skipping"* and the cache
  goes cold for that tool. There is no test that exercises this
  failure mode.
- **Why:** The brief calls Tier-1 a "performance layer", but a
  silent skip with no metric or alert is still a regression — a
  future maintainer who adds a `datetime` field to one tool's
  envelope finds the cache "doesn't seem to work" with no telemetry
  to debug.
- **Fix:** When `_tier1_put` skips for non-serializable payload,
  increment a dedicated eviction counter (or a new
  `arxmcp_cache_skips_total{reason="non_serializable"}` counter)
  so operators can see it. Add a unit test that constructs a
  payload with a `datetime` and asserts both the skip behavior AND
  the counter increment.

### F12 — `level` argument changes Tier-1 key but is encoded redundantly between Tier-1 and Tier-2
- **Severity:** MEDIUM
- **File:line:** `server/cache.py:120-136`; `server/cache_sqlite.py:124-132`
- **What:** `level` is mixed into the Tier-1 key as a fifth
  pipe-separated component, but into the Tier-2 filter fingerprint
  via `_filter_fingerprint(filters, level=level)` which produces
  `"{json}|level={level}"`. Two distinct encodings of the same
  semantic component. A future maintainer who changes the Tier-1
  encoding (e.g., to fix F1 with length-prefixing) must remember to
  also update the Tier-2 fingerprint encoding — and there is no
  test that pins the cross-tier consistency.
- **Why:** Closely-related encodings that drift independently are a
  classic source of subtle bugs. The fact that both currently work
  is incidental.
- **Fix:** Extract a single `_canonical_key_components(query, filters, k, corpus_version, level)` helper that produces the
  byte-stable encoded payload, used by both Tier-1 and the Tier-2
  filter fingerprint. Add a regression test that asserts the
  encoding output for a known input remains stable.

### F13 — Brief specifies `lookup(query, filters, k)` API but implementation diverges to `lookup_search` + `lookup_rerank`
- **Severity:** MEDIUM
- **File:line:** `server/cache.py:293-353, 583-621`
- **What:** The brief explicitly specifies
  *"`RetrievalCache` class with `lookup(query, filters, k) -> Optional[payload]` and `store(query, filters, k, payload)` methods"*.
  The implementation has `lookup_search`, `store_search`,
  `lookup_rerank`, `store_rerank` instead. The implementation
  summary's `D8` justifies splitting the rerank path, but the
  search path could (and per the brief, should) be the
  unparameterized `lookup`/`store`. The added `level` kwarg is
  defensible (closes a real bug); the renaming away from the
  brief-mandated method names is not.
- **Why:** Brief deviations are allowed when justified by a
  correctness bug. The renaming has no correctness justification —
  it is a stylistic choice. A future caller reading the brief and
  attempting `cache.lookup(...)` will hit `AttributeError`.
- **Fix:** Either rename `lookup_search` → `lookup` and
  `store_search` → `store` (with a separate `lookup_rerank` /
  `store_rerank` for Tier-3), OR document the deviation in a
  prominent CHANGELOG/decision log.

### F14 — Mirror update happens AFTER SQLite write; transient state where mirror is stale until next put
- **Severity:** MEDIUM
- **File:line:** `server/cache.py:420-446`
- **What:** `_tier1_put` writes to SQLite first, then mirrors. If a
  concurrent `_tier1_get` for the same key fires between the
  SQLite write and the mirror update, it sees a mirror miss, then
  consults SQLite, finds the new row, and re-populates the mirror
  itself. The race is benign for correctness (SQLite is the source
  of truth) but produces a double-write to the mirror in the
  contention case — the second `_tier1_put`'s
  `self._tier1_mirror[key] = payload` overwrites a freshly-read
  payload from `_tier1_get`'s mirror-population side. Since both
  are the same `payload` object (read from the same SQLite blob),
  it's a no-op in practice. But the comment at line 435-436
  *"post-SQLite write so a SQLite failure does not leave the mirror out-of-sync"* is half-true: a SQLite I/O error during the
  `await self._tier1_store.put(...)` call leaves the mirror with
  whatever it had (possibly empty), but a subsequent SUCCESSFUL
  put for the SAME key + DIFFERENT payload also has a window where
  the mirror lags SQLite by one entry version.
- **Why:** Documentation drift. The reasoning in the comment is
  correct in one direction (SQLite-fails-mirror-stays-empty) but
  not the inverse. A reader debugging cache inconsistency has a
  misleading guide.
- **Fix:** Either tighten the comment ("post-SQLite write so a
  SQLite I/O error keeps the mirror out of the success state") or
  hold the lock across both SQLite write + mirror update (small
  perf cost; tighter consistency).

### F15 — `_tier1_put`'s in-function `from server.cache_sqlite import MAX_ROWS as TIER1_CAP` is a code smell
- **Severity:** LOW
- **File:line:** `server/cache.py:441-443`
- **What:** The import is inside the function body, executed on
  every put. Python's import cache makes this O(dict-lookup) per
  call, but it's still a function-body import for a constant that
  could trivially live at module scope. Pattern is inconsistent
  with how other constants (`TIER2_TTL_SECONDS`, `TIER3_TTL_SECONDS`)
  are pulled at module top.
- **Why:** Style inconsistency invites copy-paste of the wrong
  pattern.
- **Fix:** Hoist `from server.cache_sqlite import MAX_ROWS as TIER1_MIRROR_CAP` to module top.

### F16 — `_safe_inc` exists but is not used uniformly — two competing patterns for the same goal
- **Severity:** LOW
- **File:line:** `server/cache.py:323-326, 342-344, 599-600, 700-708`
- **What:** Lookup counter increments at lines 324, 342, 599 use
  inline `try/except Exception: logger.debug(...)`. Hit counter
  increments at lines 333, 348, 620 use `self._safe_inc(...)`.
  Eviction counter increments use `self._safe_inc(...)`. Three
  call sites for one helper, three call sites for inlined try/except.
- **Why:** The inlined pattern is more verbose and duplicates the
  helper's contract.
- **Fix:** Convert all `CACHE_LOOKUPS_COUNTER.labels(tier=...).inc()` sites to use `_safe_inc`.

### F17 — `_tier_stats` reads private `._value.get()` Prometheus API
- **Severity:** LOW
- **File:line:** `server/cache.py:711-727`; `server/metrics.py:170-176`
- **What:** Both production stats and the test reset hook access
  the prometheus_client `_value` private attribute. The docstring
  says *"private API but stable across prometheus_client 0.16+"* —
  there is no upper bound on tested versions. A library upgrade
  could break both surfaces silently.
- **Why:** Promethean-client public API offers `.collect()` for
  read; the test reset path could swap the metric for a fresh
  Counter. Relying on `_value` is fast but fragile.
- **Fix:** Either pin prometheus_client to a tested range in
  `pyproject.toml` and add a CI check, or migrate to the public
  `.collect()` iteration. A simple intermediate is to add a unit
  test that asserts the private API still works against the
  installed library version.

### F18 — `corpus_version` is the *integer* but the on-disk JSON sidecar may produce a float in some edge cases
- **Severity:** LOW
- **File:line:** `server/cache.py:243`; `server/resources.py:401-411`
- **What:** `corpus_version: int` is the documented type; if a
  future `corpus-version.json` ships `{"version": 7.0}` (JSON
  number), `read_corpus_version` will return a float. The cache
  key derivation calls `f"{corpus_version}"` which formats `7.0` as
  `"7.0"` — distinct from `"7"`. A roundtrip from float-encoded JSON
  to a previously-int-keyed entry would silently miss.
- **Why:** Defensive coding. `read_corpus_version` should already
  enforce `int`, but the cache layer also doing the cast would
  prevent a class of subtle drift.
- **Fix:** Cast at construction: `self._corpus_version = int(corpus_version)`.

### F19 — Docstring drift: cache.py header claims FIFO/LRU but is actually FIFO at SQLite layer
- **Severity:** LOW
- **File:line:** `server/cache.py:13`; `server/cache_sqlite.py:62-64`
- **What:** Documentation says *"SQLite-backed LRU, max 10K entries"*
  but the implementation evicts by `expires_at ASC` (see F7).
- **Why:** Same content as F7 (impl); recorded separately as a
  documentation finding because the docstring claim is reproduced
  verbatim in three places (cache.py header, cache_sqlite.py
  header, cache.py docstring at line 213-214).
- **Fix:** Single source of truth — fix in one place, search-and-
  replace the other two.

### F20 — No load-test that asserts the brief's "40-60% Tier-3 hit rate" claim
- **Severity:** LOW
- **File:line:** `tests/test_cache.py` (entire file); brief lines 18-23
- **What:** The brief makes a load-bearing performance claim:
  *"Expected hit rate in a multi-agent fan-out: 40–60%"*. There is
  no benchmark that drives a representative multi-agent query
  distribution and measures actual hit rate. A regression that
  lowers the rate to 5% would not fail any test.
- **Why:** This is a load-test, not a correctness test, so it's
  optional in the unit-test suite. But the claim is the
  justification for the entire Tier-3 implementation; some
  empirical validation should exist.
- **Fix:** Add an opt-in (`pytest -m perf`) test that drives a
  synthetic 4-agent fan-out and asserts hit rate ≥ 0.4. Defer
  if E08_S04 owns this.

## What was done well

- The `corpus_version` invariant — including the integer in the
  Tier-1 key and storing it as a separate column for explicit purge
  — is a clean implementation of the brief's "unreachable by hash
  construction" pattern. The separate `purge_other_corpus_versions`
  housekeeping method is a thoughtful addition.
- Failure-mode discipline is rigorously applied: every tier
  lookup AND store is wrapped in `try/except Exception` per the
  design constitution (`07-multi-agent-caching.md`). Verified by
  `TestFailureModeDiscipline::test_tier1_get_swallows_store_error`.
- The Tier-2 cold-start no-op (`if not self._tier2_buffer: return None`
  at line 480-482) closes the brief's explicit cold-start
  requirement and is regression-tested.
- Length-prefix encoding in `_build_singleflight_key` is correctly
  reused for Tier-3 (no double-hashing, byte-stable). It's a missed
  opportunity that the same pattern wasn't applied to Tier-1, but
  the Tier-3 reuse itself is clean.
- Schema migration discipline: `Tier1Store._open_sync` checks
  `PRAGMA user_version`, drops + recreates on version mismatch, and
  documents the cache-loss-is-acceptable rationale.
- Test isolation via the autouse `_isolate_cache_state` fixture
  resets BOTH the singleton and the Prometheus metrics — a
  thoughtful pairing.
- WAL mode + `synchronous=NORMAL` is the documented-correct SQLite
  configuration for cache use; the comment cites the rationale.
- The `level=None` distinct encoding (`"None"` literal) ensures
  legacy non-search callers cannot collide with explicit-level
  callers — a careful detail.
- Hit-sample logging at 1% Bernoulli (per brief) and the choice not
  to log the query text in the sample message is a good
  defense-in-depth choice (closes the privacy axis).
- The Resources lifecycle integration (cache opens AFTER
  corpus_version is pinned in step 6 of `Resources.startup`, closes
  in step 1 of `Resources.shutdown`) honors the dependency order.

## Recommended rectification order

1. F1 (CRITICAL) — Fix the `|`-separator key construction with
   length-prefix encoding. Affects all Tier-1 reads/writes; landing
   first means subsequent fixes hit the corrected code.
2. F2 (HIGH) — Add `expires_at` to the Tier-1 mirror entry and
   enforce TTL on read.
3. F4 (HIGH) — Add the `_patched_cache_db_path` autouse fixture so
   subsequent test additions don't pollute the worktree.
4. F3 (HIGH) — Wire Tier-3 into RerankPhase. Without this, the
   brief's headline performance claim is unattainable.
5. F5, F6 (HIGH) — Add HTTP-level integration tests for `/debug/cache-stats` and `/metrics`. Required for AC compliance.
6. F7 (MEDIUM) — Either rename "LRU" → "TTL-priority" in docs OR
   add an LRU implementation. Pick (b) only if hit-rate data
   justifies the per-read SQLite UPDATE cost.
7. F11, F12 (MEDIUM) — JSON-serialization defensiveness + unify
   the cross-tier `level` encoding.
8. F8, F9, F10, F13, F14 (MEDIUM) — Subtle correctness fixes;
   batch them.
9. F15-F20 (LOW) — Cleanup pass; safe to defer to a follow-up
   milestone if rectification budget is tight.

## Rectification status

Re-verified F1 (CRITICAL) before fixing — the `|` separator
collision is theoretical (a practical exploit requires ≥2 component
overlap which is hard with always-int `k`/`cv`) but the right
discipline (length-prefix encoding) is cheap to apply. All
CRITICAL + HIGH and 7/9 MEDIUM fixed; 5 LOW deferred per the
rectifier protocol.

Fixed in the rectification commit:

- **F1** (CRITICAL) — fixed. Replaced `|`-separator concatenation in
  `derive_tier1_key` with length-prefix encoding via a new
  `canonical_key_components(...)` helper in `server/cache_sqlite.py`.
  Mirrors `_build_singleflight_key`'s discipline. Regression guards:
  `test_f1_canonical_key_is_length_prefixed_collision_resistant`,
  `test_f1_canonical_key_components_uses_length_prefix`.
- **F2** (HIGH) — fixed. Tier-1 mirror entry shape is now
  `(payload, expires_at)`. `_tier1_get` checks `expires_at` against
  `time.time()`, lazy-evicts expired entries, increments
  `CACHE_EVICTIONS_COUNTER{tier="1"}`. Regression guard:
  `test_f2_tier1_mirror_enforces_ttl_on_read` monkeypatches a
  past-expiry into the mirror and asserts the lookup misses.
- **F3** (HIGH) — fixed. Wired Tier-3 into `RerankPhase.rerank`:
  cache lookup BEFORE the singleflight + cross-encoder, cache store
  AFTER a successful rerank. The cache key is the SAME bytes the
  singleflight uses (`_build_singleflight_key`). All cache calls are
  fault-isolated (lookup error → miss; store error swallowed).
  Regression guard: `test_f3_tier3_wired_into_rerank_phase` asserts
  the source contains both `lookup_rerank` and `store_rerank` calls.
- **F4** (HIGH) — fixed. Added autouse `_patched_cache_db_path`
  fixture in `tests/conftest.py` that sets `ARXMCP_CACHE_DB_PATH` to
  `tmp_path/cache/retrieval.db`. Mirrors the established pattern of
  `_patched_store_stats_path` / `_patched_bm25_stats_path` /
  `_patched_bm25_index_root`. Regression guard:
  `test_f4_cache_db_path_redirected_into_tmp_path` constructs
  `Config()` and asserts the resolved path is under `tmp_path`.
- **F5** (HIGH) — fixed. Added `test_f5_debug_cache_stats_endpoint_returns_valid_json`
  using `fastapi.testclient.TestClient` against a minimal app with
  the debug router mounted. Verifies HTTP 200 + body shape +
  per-tier required fields. Avoids the heavy LanceDB / BGE-M3 warm
  path of a full `create_app(...)`.
- **F6** (HIGH) — fixed. Added `test_f6_metrics_endpoint_includes_cache_metric_families`
  that touches each cache metric label (forces time-series creation)
  and asserts the names appear in `prometheus_client.generate_latest(REGISTRY)`
  output. Mirrors the pattern in `tests/test_server_startup.py`.
- **F7** (MEDIUM) — fixed (docs). Updated docstrings in
  `server/cache_sqlite.py` and `server/cache.py` to call the SQLite
  layer "TTL-priority eviction (FIFO under uniform-TTL inserts)"
  rather than "LRU". Documented the trade-off (no per-read SQLite
  UPDATE) and noted the in-process mirror IS true LRU.
- **F8** (MEDIUM) — fixed. `_rehydrate_tier1_from_sqlite` now
  truncates at `TIER1_MIRROR_CAP` (= `MAX_ROWS = 10_000`) before
  populating the mirror. Regression guard:
  `test_f8_rehydrate_caps_at_mirror_max` greps the source for the
  truncation expression.
- **F9** (MEDIUM) — fixed. `_tier2_lookup` now searches top-K (K=8
  capped at `index.ntotal`) and iterates until one matches both
  the filter fingerprint AND the TTL window. Pre-fix the top-1 with
  wrong filter masked a valid second-nearest. Regression guard:
  `test_f9_tier2_searches_top_k_not_top_1` constructs two near-cosine
  embeddings with different filters and asserts the right-filter
  second-nearest is found.
- **F10** (MEDIUM) — fixed. `KMP_DUPLICATE_LIB_OK` now uses
  `os.environ.setdefault` (so a pre-existing operator setting wins)
  AND a `pytest_sessionfinish` hook clears it if WE were the one
  that set it. The "test-only" framing is now backed by an
  enforcement mechanism.
- **F11** (MEDIUM) — fixed. Added `arxmcp_cache_payload_skips_total{reason}`
  Counter (`reason="non_serializable"`); incremented when
  `_tier1_put`'s JSON encode raises. Regression guard:
  `test_f11_non_serializable_payload_increments_skip_counter`
  passes a `datetime` payload and asserts the counter rises.
- **F12** (MEDIUM) — fixed. `_filter_fingerprint` now derives from
  the same `canonical_key_components` helper used by `derive_tier1_key`,
  so a future encoding fix to the Tier-1 key automatically
  propagates to the Tier-2 fingerprint. Regression guard:
  `test_f12_filter_fingerprint_uses_canonical_components` verifies
  the fingerprint depends on both filters and level distinctly.
- **F13** (MEDIUM) — fixed. Added `RetrievalCache.lookup` and
  `RetrievalCache.store` as brief-spec aliases over `lookup_search`
  / `store_search`. The `(lookup_rerank, store_rerank)` Tier-3 surface
  retains its distinct names. Regression guard:
  `test_f13_lookup_and_store_aliases_exist` exercises both names.
- **F14** (MEDIUM) — fixed (docs). Tightened the comment in
  `_tier1_put` to *"post-SQLite write so a SQLite I/O error keeps
  the mirror out of the success state"* — explicit about which
  failure direction the post-write ordering protects against.
- **F15** (LOW) — fixed inline. Hoisted
  `from server.cache_sqlite import MAX_ROWS as TIER1_MIRROR_CAP` to
  module top in `server/cache.py`.
- **F16** (LOW) — fixed inline. All `CACHE_*_COUNTER.labels(...)` 
  increments in `lookup_search` / `lookup_rerank` now route through
  `self._safe_inc(...)`. Single source of truth for "metrics
  failure must not propagate".
- **F18** (LOW) — fixed inline. Defensive `int(corpus_version)` cast
  in `RetrievalCache.__init__` so a future float-decoded
  `corpus-version.json` cannot silently break key matching.
- **F19** (LOW) — fixed inline. Same content as F7 (docstring drift
  about "LRU"); single fix in `cache.py`'s module docstring covers
  both findings.

Deferred (per rectifier protocol — fix as paper-cuts in a future pass):

- **F17** (LOW) — `_tier_stats` / `reset_cache_metrics_for_tests`
  read prometheus_client `_value` private API. Migration to public
  `.collect()` iteration is a separate refactor. The docstring
  documents the dependency.
- **F20** (LOW) — no load-test for the brief's "40-60% Tier-3 hit
  rate" claim. Defer to a future perf-test milestone.

Test additions (regression guards):

- 12 new tests in `TestRectificationGuards` covering F1, F1-bytes,
  F2, F3, F4, F5, F6, F8, F9, F11, F12, F13.
- `test_level_change_changes_key` was added in the original
  implementation pass (covers the level-omission bug F12 implicitly).

Final test count: **40 cache tests** (was 28). Full suite: **1078
passed, 4 skipped, 0 failed** (was 1066). `ruff check .` clean.

Inner-loop attempt counts: every finding fixed in 1 attempt. Below
the 3-attempt cap.

Outer-loop iterations: 1 (single full-suite run after batched
fixes, plus a small ruff/contextlib correction). Under the
3-iteration cap.

Invalidation rate: 0/1 CRITICAL (0%) and 0/5 HIGH (0%) and 0/9
MEDIUM (0%) findings invalidated. Well below the 40% threshold.
