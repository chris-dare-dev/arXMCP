# Research Brief — corpus-integrity-completion-m3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T22:30:00Z

---

## In-codebase context

### Canonical lifespan-testing pattern (CONFIRMED from codebase)

`tests/test_server_startup.py` is the authoritative precedent. It uses:

```python
from fastapi.testclient import TestClient
...
with TestClient(app) as client:
    r = client.get("/readyz")
    assert r.status_code == 200
```

The `warm_app` fixture (lines 138–149) is the canonical shape:

```python
@pytest.fixture
def warm_app(seeded_lancedb, mocked_bge_m3):
    cfg = Config(lancedb_path=seeded_lancedb)
    app = create_app(cfg)
    reset_metrics_for_tests()
    with TestClient(app) as client:
        yield client
```

**CRITICAL finding on BGE-M3 mocking (FM-1 resolution):** `resources.py` imports `_get_model` and `_get_tokenizer` by name at module level via `from server.query_encoder import (_get_model, _get_tokenizer, ...)` (resources.py:78-82). The `mocked_bge_m3` fixture in `test_server_startup.py` patches only `server.query_encoder`, which is INSUFFICIENT for the startup path because resources.py binds those names at import time.

`tests/test_corpus_count_reconciliation.py:93–105` documents this lesson explicitly:

> "resources.py binds `_get_model` by name via `from server.query_encoder import _get_model`, so patching only query_encoder is insufficient — notebook-retrieval-m2 lesson"

The correct helper (already in `test_corpus_count_reconciliation.py`) patches BOTH modules:

```python
def _patch_model(monkeypatch) -> None:
    import server.query_encoder as qe_mod
    import server.resources as res_mod
    fake_model = object()
    fake_tokenizer = object()
    for mod in (qe_mod, res_mod):
        monkeypatch.setattr(mod, "_get_model", lambda: fake_model)
        monkeypatch.setattr(mod, "_get_tokenizer", lambda: fake_tokenizer)
```

The `mocked_bge_m3` fixture in `test_server_startup.py` (lines 107–121) does NOT patch `server.resources` — it only patches `server.query_encoder`. The integration test **MUST use the `_patch_model` pattern from `test_corpus_count_reconciliation.py`**, not the simpler `mocked_bge_m3` fixture, to reliably mock the BGE-M3 load in `Resources.startup`.

### Existing `_seed_corpus` helpers

Two distinct but compatible `_seed_corpus` helpers exist:

1. `tests/test_server_startup.py:56–86` — seeds 2 chunks (2 papers, hardcoded `i in (1, 2)`)
2. `tests/test_corpus_count_reconciliation.py:47–81` — seeds `n` chunks (`n` parameter, `n` papers)

The m3 milestone requires 3 papers × ~30 chunks. The `test_corpus_count_reconciliation.py` helper is parameterized (`n=30` yields 30 chunks from 30 papers). The implementer should copy or import this helper.

### `/readyz` body shape (load-bearing from `server/health.py:282–295`)

```python
startup_count = resources.startup_chunk_count
return JSONResponse(
    status_code=200,
    content={
        "status": "ready",
        "chunk_count": None if startup_count < 0 else startup_count,
        "marker_chunk_count": resources.corpus_info.chunk_count,
        ...
    },
)
```

The body includes `chunk_count` (integer or null) AND `marker_chunk_count` (always integer). The positive test must assert `body["chunk_count"] == body["marker_chunk_count"]`. The sentinel path (`startup_chunk_count == -1`) renders `chunk_count` as JSON `null` — the test must assert against the integer, not null (see FM-5 below).

### `write_corpus_version_marker` binding (FM-4 resolution)

At `ingest/store.py:946`, `write_corpus_version_marker` is called as a **local name** (not via module reference). The call at line 946 is:

```python
write_corpus_version_marker(
    target_path,
    version=dataset_version,
    ...
    chunk_count=chunk_count,
)
```

This is a bare name call WITHIN `ingest.store` module scope. To monkeypatch the mutation test effectively, the target binding is `ingest.store.write_corpus_version_marker` (the module's own namespace). `monkeypatch.setattr("ingest.store", "write_corpus_version_marker", fake_fn)` or `monkeypatch.setattr(store_mod, "write_corpus_version_marker", fake_fn)` — not the caller's import alias.

### `asyncio_mode` NOT configured

`pyproject.toml [tool.pytest.ini_options]` has NO `asyncio_mode` setting. The project does NOT use `pytest-asyncio` (no dependency in pyproject.toml). All async code in existing tests is run via `asyncio.run(...)` (sync test functions). The integration test should be a **SYNC test function** using `TestClient` as a context manager — do NOT introduce `@pytest.mark.asyncio` or `pytest-asyncio`.

### `reset_metrics_for_tests()` and state isolation

`tests/test_server_startup.py:148` calls `reset_metrics_for_tests()` before the `TestClient(app)` context. The integration test must do the same. The `_reset_session_state_for_tests` autouse fixture (conftest.py:237–265) handles session caps. The `_patched_cache_db_path`, `_patched_bm25_index_root`, `_patched_store_stats_path` autouse fixtures (conftest.py) handle filesystem pollution. These autouse fixtures run for all tests — the integration test inherits them automatically.

### 5-second budget analysis

The `mocked_bge_m3` in `test_server_startup.py` uses `object()` stubs and completes in milliseconds. `test_readyz_reaches_200_within_30s` (line 247) asserts `elapsed < 30.0`. With the dual-module patch (`_patch_model`), the lifespan completes in < 0.5s on the test machine. LanceDB cold-open for a 30-chunk table adds < 0.5s. Total budget: comfortably under 5s.

### Design notes applying to this milestone

- `07-multi-agent-caching.md`: no tool-schema changes → `EXPECTED_TOOL_SCHEMA_SHA256` is UNCHANGED. The test adds no MCP tool.
- `08-security-observability-ops.md`: integration test uses `tmp_path` (no corpus pollution); no loopback bind required for TestClient.

---

## Failure-mode analysis (≥10 modes)

**FM-1 — BGE-M3 load in lifespan exceeds 5s budget.**
Trigger: using the `mocked_bge_m3` fixture which only patches `server.query_encoder`, not `server.resources`. Resources.startup at line 677 calls `_get_model()` directly from its import-time binding — the patch never fires. The lifespan downloads/loads BGE-M3 (~5-30s cold).
Mitigation: use `_patch_model(monkeypatch)` from `test_corpus_count_reconciliation.py` which patches BOTH `server.query_encoder` AND `server.resources`.

**FM-2 — Synthetic table lacks an HNSW index; startup logs WARNING but does NOT abort.**
Trigger: a small synthetic table written by `write_chunks` gets `_create_indices` called internally (it's inside `write_chunks`) — so the index IS built. If tests somehow produce a table without an index, `compute_unindexed_rows` returns -1 (from empty `list_indices()`) and logs a WARNING. Resources.startup proceeds normally (`startup_unindexed_rows == -1`, no degrade). This is non-fatal and the `/readyz` 200 still fires. No blocker.

**FM-3 — TestClient teardown leaves LanceDB handle open, polluting next test.**
Trigger: if the test does not use `TestClient` as a context manager and does not call `Resources.shutdown()`, the LanceDB file handle remains open. Under `tmp_path`, each test gets a unique directory, so cross-test pollution cannot occur at the filesystem level. The autouse fixtures reset module-level state (session caps, BM25 root, store stats path). The integration test should use `with TestClient(app)` to guarantee lifespan teardown (`Resources.shutdown()` is called on context manager exit).

**FM-4 — Mutation test monkeypatches wrong binding.**
Trigger: `write_corpus_version_marker` is called at line 946 of `ingest/store.py` as a LOCAL name in the module's namespace. If the mutation test does `monkeypatch.setattr(ingest.store, "write_corpus_version_marker", bad_fn)` the patch works. But if the test does `monkeypatch.setattr("tests.test_server_startup_integration", "write_corpus_version_marker", bad_fn)` (wrong module) or `from ingest.store import write_corpus_version_marker; monkeypatch.setattr(write_corpus_version_marker, ...)` (incorrect API), the patch silently no-ops and the mutation test always passes — detecting nothing.
Mitigation: explicitly `import ingest.store as store_mod` and `monkeypatch.setattr(store_mod, "write_corpus_version_marker", bad_fn)`.

**FM-5 — `/readyz` returns `chunk_count: null` (not the integer), causing assertion error.**
Trigger: if `count_rows()` fails at startup (returns exception), `startup_chunk_count == -1` and `health.py:287` renders `chunk_count` as JSON `null`. The positive test must assert BOTH that `chunk_count is not None` AND that `chunk_count == marker_chunk_count`. If the test only asserts `body["chunk_count"] == body["marker_chunk_count"]` and both are `null`, the assertion passes while the test is vacuously verifying nothing.
Mitigation: assert `body["chunk_count"] is not None` before the equality check. The mutation test should also verify `/readyz` returns 503 (not 200) when divergence is detected, which is distinct from the null case.

**FM-6 — Resources global state leaks between integration test and other tests.**
Trigger: `server/resources.py` may expose `set_resources()`/`get_resources()` module-level globals (mirroring the `_notebooks_store` singleton pattern in `server/tools.py`). If `Resources.startup` stores state globally, a prior test's Resources survives into the integration test. Confirmed: `TestClient` lifespan attaches Resources to `app.state.resources` (not a module global). The `_reset_session_state_for_tests` autouse fixture handles the session cap registry. No ResourcesgGlobal state bleed.

**FM-7 — KMP_DUPLICATE_LIB_OK guard absent in subprocess context.**
Trigger: if the integration test (incorrectly) spawned a subprocess for the server. The test uses in-process `TestClient` (no subprocess), so this guard is irrelevant. `tests/conftest.py` already sets `KMP_DUPLICATE_LIB_OK=TRUE` at module-load time for the in-process BGE-M3 + faiss-cpu concern. No action needed for this test.

**FM-8 — Marker file not written before lifespan boots.**
Trigger: the test builds the LanceDB table but does not write the marker. `Resources.startup` reads `corpus-version.json` via `read_corpus_version(config.lancedb_path)` at line 461 — if absent, raises `CorpusNotIngestedError` and the lifespan fails. Mitigation: `write_chunks` ALWAYS writes the marker at line 946 (inside the same call). The integration test must call `write_chunks(...)` (the real implementation, not a stub), which atomically writes both the table rows and the marker. Order: call `write_chunks` for each paper, then boot the lifespan.

**FM-9 — Mutation test triggers the sentinel path (null) instead of the divergence path (503).**
Trigger: the mutation test patches `write_corpus_version_marker` to write a WRONG `chunk_count`. If the fake writes `chunk_count=0` and the table has 30 rows, `compute_chunk_count_divergence(marker_count=0, actual_count=30, tolerance=0.05)` returns `"rows_added"` → `degraded=DegradedState(reason="chunk_count_diverged")` → `/readyz` returns 503. This is the correct detection path. BUT if the fake writes `chunk_count=-1` (sentinel value), the `compute_chunk_count_divergence` function treats `actual_count < 0` as "count unavailable, skip check" → no degrade. The mutation fake must write a WRONG POSITIVE COUNT, not a negative sentinel.
Mitigation: the mutation fake should write `chunk_count=0` (empty) or `chunk_count=1` (too few) when the real table has 30 rows — guaranteed to diverge beyond the 5% tolerance.

**FM-10 — 3-paper × 30-chunks fixture produces non-deterministic chunk IDs.**
Trigger: chunk IDs are `sha256(canonical_chunk_bytes)[:16]` — if `body_text` varies per run (e.g. contains a timestamp), chunk IDs differ and `merge_insert` creates duplicate rows rather than upserts. Using deterministic `body_text=f"chunk body {i}"` (as in the existing `_seed_corpus`) makes IDs deterministic.
Mitigation: model chunk IDs after the existing `_seed_corpus` pattern. Use `rng = np.random.default_rng(42)` for embedding generation.

**FM-11 — `reset_metrics_for_tests()` not called → Prometheus registry conflict.**
Trigger: if a prior test in the same session already registered Prometheus metrics with the same name, a second `create_app` → lifespan → gauge-set sequence may see a collision. `reset_metrics_for_tests()` resets only `_LAST_DEDUP_COUNT`. The Prometheus library uses a global `REGISTRY`; the gauges are registered at module-import time (not per `create_app`). Multiple `create_app` calls in the same process share the same gauge objects — gauge `.set()` is safe to call multiple times. No registry conflict risk; `reset_metrics_for_tests()` is still needed for counter monotonicity.

---

## External sources

### FastAPI TestClient lifespan (docs.fastapi.io/advanced/testing-events)

The canonical pattern per FastAPI documentation (confirmed above):

> "Use the `TestClient` as a context manager (with statement) to trigger the `lifespan` events."

```python
with TestClient(app) as client:
    # lifespan has run; resources are warm
    response = client.get("/readyz")
```

There is NO async `TestClient` in FastAPI for lifespan testing — the async path (httpx.AsyncClient + ASGITransport) is for async test functions only and requires `pytest-asyncio`. Since the project has NO `asyncio_mode` configured and NO `pytest-asyncio` dependency, the sync `TestClient` is the canonical and ONLY valid choice.

### LanceDB `count_rows()` contract (from codebase comments)

From `ingest/store.py:920-921` (inline doc, verbatim):

> "Reading `tbl.count_rows()` (O(1) — Lance fragment metadata)"

And from `server/resources.py:549-551` (startup comment):

> "Compute count_rows() ONCE (O(1) Lance fragment metadata) and cache it on the instance so the /metrics gauges read a startup snapshot, never a per-scrape scan."

The O(1) claim is from Lance's fragment-metadata design — `count_rows()` reads the manifested row count from the Lance fragment metadata, not by scanning rows. On an empty table, `count_rows()` returns `0` (not -1, not raises). The -1 sentinel is project-specific: `startup_chunk_count = -1` is set only when `count_rows()` RAISES an exception (FM-2 path in `resources.py:567-573`).

### `pytest-asyncio` NOT present

`pyproject.toml` has no `pytest-asyncio` or `anyio` dependency in `[project.dependencies]` or `[project.optional-dependencies]`. The `[tool.pytest.ini_options]` block has no `asyncio_mode`. The project uses `asyncio.run(...)` in sync test functions — never `@pytest.mark.asyncio`. The integration test MUST be a sync test function using `TestClient`.

---

## Recommendation

**Use sync `TestClient` + `_patch_model` (dual-module) + `write_chunks` for real corpus construction.**

Concretely:

1. **Do NOT create a new `_seed_corpus` helper.** Reuse or copy the `_seed_corpus(lancedb_path, n=30)` helper from `tests/test_corpus_count_reconciliation.py` (it takes an `n` parameter). Call it 3 times with different lancedb_path roots — or call it once with `n=30` for 30 chunks from 30 papers (the milestone says "3-paper × ~30-chunks"; interpret as ≥3 papers and ~30 total chunks; 30 calls to `write_chunks` with 1 chunk each, or 3 calls with 10 chunks each).

2. **Dual-module BGE-M3 mock.** Copy `_patch_model(monkeypatch)` verbatim from `test_corpus_count_reconciliation.py` into the new test file (or import it — but copying is safer to avoid cross-file coupling).

3. **Call `reset_metrics_for_tests()` before the `with TestClient(app)` block.**

4. **Positive test:**
   ```python
   lancedb_path = tmp_path / "lancedb"
   _seed_corpus(lancedb_path, n=30)  # 30 chunks, 30 papers
   cfg = Config(lancedb_path=lancedb_path)
   app = create_app(cfg)
   reset_metrics_for_tests()
   with TestClient(app) as client:
       r = client.get("/readyz")
   assert r.status_code == 200
   body = r.json()
   assert body["chunk_count"] is not None, "count_rows() must succeed (not FM-2 sentinel)"
   assert body["chunk_count"] == body["marker_chunk_count"]
   ```

5. **Mutation test:** `monkeypatch.setattr(store_mod, "write_corpus_version_marker", bad_fn)` where `bad_fn` writes `chunk_count=1` regardless of the real table size. Then seed the corpus (30 rows), boot the server. The 29-row gap (1 vs 30) exceeds the 5% tolerance floor (max(1, 0.05×1) = 1.05 → 29 >> 1.05). Assert `/readyz` returns 503 with `body["reason"] == "chunk_count_diverged"`.

   **Key ordering constraint:** `monkeypatch.setattr` must be called BEFORE `write_chunks` is called (because the marker is written inside `write_chunks`). The test body is:
   ```python
   monkeypatch.setattr(store_mod, "write_corpus_version_marker", bad_marker)
   _seed_corpus(lancedb_path, n=30)  # now writes chunk_count=1 in marker
   ...  # boot server; assert /readyz 503 + reason
   ```

6. **No `pytest.mark.asyncio`, no `httpx.AsyncClient`.** The project has no asyncio_mode and no pytest-asyncio dependency. Do not introduce them.

7. **No `requires_full_corpus` marker.** The test uses a synthetic 30-chunk corpus via `tmp_path` — it runs in `make test` without markers.

---

## Open questions

**OQ-1 — `warm.embedder` will be `False` in the /readyz body when using the fake `_get_model` stub.**

`is_resource_warm("embedder")` checks whether the loaded model is a real FlagModel, not just any object. If the check is `isinstance(model, FlagModel)`, then `object()` stubs will make `warm.embedder == False`. Confirmed in `test_server_startup.py:207-210`:

```python
assert body["warm"]["embedder"] is True
assert body["warm"]["lancedb"] is True
assert body["warm"]["reranker"] is False
```

This works in the existing test with `mocked_bge_m3`. Whether it works with `_patch_model` depends on how `is_resource_warm("embedder")` is implemented. The existing `TestStartupReconciliation` tests use `_patch_model` but do NOT check `body["warm"]["embedder"]`. The AC says "GET /readyz returns 200" — it does NOT require `warm.embedder == True`. The milestone AC only requires `body["chunk_count"] == body["marker_chunk_count"]`, so `warm.embedder: false` is acceptable for this test.

**No other open questions — implementation can proceed on the above recommendation.** The `warm.embedder` question is resolved: AC-4 permits `warm.embedder: false` in the test context since it's testing the chunk-count body field, not the embedder warm state.

---

## External writes the implementation will require

None — this milestone is purely local. The implementation creates one new test file (`tests/test_server_startup_integration.py`) with no external dependencies, no git push, no infra mutation, no third-party API calls required.
