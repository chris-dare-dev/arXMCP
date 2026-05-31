# Research Synthesis — corpus-integrity-completion-m3

**Synthesizer:** main orchestrator session (NOT a sub-agent)
**Generated:** 2026-05-31
**Briefs merged:** `research-brief-1.md` (in-codebase fixtures + monkeypatch), `research-brief-2.md` (external + 11 failure modes + body-shape)
**Verdict:** Auto-advance to Phase 2 / inline implementation. Briefs converged on the SAME implementation contract via independent paths. Two brief-vs-reality mismatches surfaced that the implementer MUST honor.

---

## 1. Implementation contract

Create `tests/test_server_startup_integration.py` with two test functions:

1. `test_chunk_count_marker_equals_table_after_multi_paper_write` — positive-path end-to-end test.
2. `test_pre_m1_bug_shape_is_caught_by_integration` — mutation test that proves the integration test would FAIL if a future bug re-introduced the pre-m1 `len(chunks)` shape.

### Critical primitives (all from existing scaffolding — do NOT reinvent)

| Primitive | Source file | Purpose |
|---|---|---|
| `_seed_corpus(lancedb_path, n=30)` | `tests/test_corpus_count_reconciliation.py:47-81` | Real `write_chunks` × N call — atomically writes table rows + marker + HNSW index per call |
| `_patch_model(monkeypatch)` | `tests/test_corpus_count_reconciliation.py:93-105` | DUAL-MODULE BGE-M3 stub (patches `server.query_encoder` AND `server.resources`) |
| `Config(lancedb_path=tmp_path / "lancedb")` | `tests/test_server_startup.py:138-149` | Canonical config-override pattern |
| `create_app(cfg)` | `server/main.py::create_app` | Builds FastAPI app with lifespan |
| `reset_metrics_for_tests()` | (from `server.observability.metrics`) | Counter monotonicity hygiene |
| `with TestClient(app) as client:` | `tests/test_server_startup.py:148` | Canonical lifespan-trigger pattern (sync, FastAPI canonical) |
| `r = client.get("/readyz")` then assert body | various | Test surface |

### Positive-path test shape

```python
def test_chunk_count_marker_equals_table_after_multi_paper_write(tmp_path, monkeypatch):
    _patch_model(monkeypatch)  # DUAL-MODULE patch — FM-1 critical
    lancedb_path = tmp_path / "lancedb"
    _seed_corpus(lancedb_path, n=30)  # 30 chunks; ~30 papers; triggers real write_chunks
    cfg = Config(lancedb_path=lancedb_path)
    app = create_app(cfg)
    reset_metrics_for_tests()
    with TestClient(app) as client:
        r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["chunk_count"] is not None  # FM-5: null is vacuous-equal to itself
    assert body["chunk_count"] == body["marker_chunk_count"]
```

### Mutation test shape

```python
def test_pre_m1_bug_shape_is_caught_by_integration(tmp_path, monkeypatch):
    _patch_model(monkeypatch)
    import ingest.store as store_mod  # FM-4: monkeypatch the module-local binding
    real_marker = store_mod.write_corpus_version_marker
    def bad_marker(target_path, *, version, chunker_version, embedder_version,
                   paper_count, chunk_count):
        # Simulate pre-m1 bug shape: write the WRONG chunk_count (last-batch only).
        # Inject 1 instead of the real count to guarantee > 5% tolerance breach.
        return real_marker(target_path, version=version,
                           chunker_version=chunker_version,
                           embedder_version=embedder_version,
                           paper_count=paper_count,
                           chunk_count=1)  # FM-9: positive, not -1 sentinel
    monkeypatch.setattr(store_mod, "write_corpus_version_marker", bad_marker)
    lancedb_path = tmp_path / "lancedb"
    _seed_corpus(lancedb_path, n=30)  # 30 rows committed, marker says chunk_count=1
    cfg = Config(lancedb_path=lancedb_path)
    app = create_app(cfg)
    reset_metrics_for_tests()
    with TestClient(app) as client:
        r = client.get("/readyz")
    # Resources.startup detects divergence (29-row gap >> 5% tolerance);
    # sets DegradedState(reason='chunk_count_diverged'); /readyz returns 503.
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["reason"] == "chunk_count_diverged"
```

---

## 2. Brief-vs-reality mismatches (BOTH must be honored)

Both researchers independently surfaced two errors in the milestone brief that the implementation MUST work around. Synthesizer treats these as RESOLVED — no open question remains.

### Mismatch A — `tests/_graph_helpers.py` is NOT the right primary tool

R1 §"Conclusion" (verbatim):
> "`build_synthetic_lancedb` from `_graph_helpers.py` is NOT the right primary tool here. The milestone brief says 'use the synthetic-fixture pattern from `tests/_graph_helpers.py`' but the implementing agent must use `write_chunks` directly (as in `test_server_startup.py::_seed_corpus`), not `build_synthetic_lancedb`."

R2 §"Existing `_seed_corpus` helpers" (verbatim):
> "Two distinct but compatible `_seed_corpus` helpers exist: 1. `tests/test_server_startup.py:56-86`... 2. `tests/test_corpus_count_reconciliation.py:47-81` — seeds `n` chunks (`n` parameter, `n` papers). The m3 milestone requires 3 papers × ~30 chunks. The `test_corpus_count_reconciliation.py` helper is parameterized."

**Resolution:** Use `_seed_corpus(lancedb_path, n=30)` from `tests/test_corpus_count_reconciliation.py`. Either copy the helper into the new test file or import it (`from tests.test_corpus_count_reconciliation import _seed_corpus, _patch_model`). R1 recommended copy (avoids cross-file coupling); R2 left both options open. **Synthesizer pick: import**, because (a) the helpers carry the load-bearing FM-1 dual-module patch lesson via their pinned location in `test_corpus_count_reconciliation.py`, (b) copying creates duplicate maintenance surface for a future helper update, (c) the pattern is already established in arXMCP (one test file imports helpers from another for fixture reuse).

### Mismatch B — `httpx.AsyncClient` is NOT the canonical pattern

R1 §"FastAPI test-client docs" (verbatim):
> "The sync `TestClient` with a `with` block is the canonical lifespan-triggering pattern... `httpx.AsyncClient` is NOT used. The milestone brief says 'httpx.AsyncClient + the existing tests/test_server_startup.py TestClient bootstrap pattern' — this is a slight contradiction in the brief; the existing tests exclusively use sync `TestClient`."

R2 §"`asyncio_mode` NOT configured" (verbatim):
> "`pyproject.toml [tool.pytest.ini_options]` has NO `asyncio_mode` setting. The project does NOT use `pytest-asyncio` (no dependency in pyproject.toml). All async code in existing tests is run via `asyncio.run(...)` (sync test functions). The integration test should be a **SYNC test function** using `TestClient` as a context manager — do NOT introduce `@pytest.mark.asyncio` or `pytest-asyncio`."

**Resolution:** SYNC `TestClient` from `fastapi.testclient`. No `httpx.AsyncClient`, no `pytest-asyncio`, no `@pytest.mark.asyncio`. The brief's `httpx.AsyncClient` mention is aspirational and contradicts the project's actual dependency tree.

---

## 3. Quoted load-bearing constraints

### From `tests/test_corpus_count_reconciliation.py:93-105` (R2 verbatim — the FM-1 critical pattern)

> "`_patch_model(monkeypatch)` patches BOTH `server.query_encoder` AND `server.resources` because resources.py binds `_get_model` by name via `from server.query_encoder import _get_model`, so patching only query_encoder is insufficient — notebook-retrieval-m2 lesson"

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

### From `server/health.py:282-295` (R2 verbatim) — `/readyz` body shape

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

### From `ingest/store.py:946` (R1 + R2 cross-verified) — monkeypatch target site

`write_corpus_version_marker(...)` is called as a BARE NAME inside `write_chunks` (module-local). The monkeypatch target is `ingest.store.write_corpus_version_marker` (the module's own namespace).

### Divergence threshold (R2 §FM-9 verbatim — load-bearing for the mutation test)

> "If the fake writes `chunk_count=0` and the table has 30 rows, `compute_chunk_count_divergence(marker_count=0, actual_count=30, tolerance=0.05)` returns `'rows_added'` → `degraded=DegradedState(reason='chunk_count_diverged')` → `/readyz` returns 503. This is the correct detection path. BUT if the fake writes `chunk_count=-1` (sentinel value), the function treats `actual_count < 0` as 'count unavailable, skip check' → no degrade. The mutation fake must write a WRONG POSITIVE COUNT, not a negative sentinel."

**Resolution:** Inject `chunk_count=1` (positive, well below the 5% tolerance floor for 30 rows). 29-row gap = 96.7% divergence, well above 5%.

---

## 4. Resolved decisions (no open questions)

Both briefs reached the same conclusion on every disputed point:

1. **TestClient pattern:** sync `fastapi.testclient.TestClient(app)` with `with` block. NOT async httpx. NOT pytest-asyncio.
2. **`_graph_helpers.py` usage:** NOT applicable for this milestone; use `_seed_corpus` from `tests/test_corpus_count_reconciliation.py`.
3. **BGE-M3 patch:** dual-module via `_patch_model(monkeypatch)`. The simple `mocked_bge_m3` fixture is INSUFFICIENT.
4. **Monkeypatch target for mutation:** `ingest.store.write_corpus_version_marker` (module's own namespace).
5. **Mutation injected count:** `chunk_count=1` (positive, well below tolerance floor for 30 rows).
6. **`warm.embedder` value in `/readyz` body:** acceptable as `False` for this test — the AC asserts only `chunk_count == marker_chunk_count`, not `warm.embedder == True`.
7. **5-second wall-clock budget:** achievable (R2 measured <0.5s lifespan + <0.5s LanceDB cold-open with the dual-module patch).
8. **No new markers:** runs in default `make test` set. No `requires_full_corpus`, no `requires_model`, no opt-in.
9. **Reuse via import:** `from tests.test_corpus_count_reconciliation import _seed_corpus, _patch_model` rather than copying (synthesizer pick — R1 said "copy", R2 said either; import wins on maintenance grounds).

---

## 5. Failure-mode coverage (consolidated from R2's 11 modes)

R2 enumerated 11 failure modes. The 5 that directly shape the implementation:

| FM | Trigger | Mitigation in test |
|---|---|---|
| FM-1 | Single-module BGE-M3 patch insufficient — lifespan tries to load real BGE-M3 | Use `_patch_model` (dual-module) |
| FM-4 | Monkeypatch wrong binding for `write_corpus_version_marker` | `monkeypatch.setattr(store_mod, "write_corpus_version_marker", bad_fn)` — module's own namespace |
| FM-5 | `chunk_count: null` vs integer in `/readyz` body — equality is vacuously true | Assert `body["chunk_count"] is not None` BEFORE the equality check |
| FM-8 | Marker file not written before lifespan boots → CorpusNotIngestedError | `write_chunks` writes both atomically; call BEFORE `with TestClient(app)` |
| FM-9 | Mutation injected count too low/wrong-sign — divergence not detected | Inject `chunk_count=1` (positive, below tolerance floor for 30 rows) |

FM-2, FM-3, FM-6, FM-7, FM-10, FM-11 are non-blocking per R2's analysis. FM-2 (no HNSW index) is non-issue because `write_chunks` runs `_create_indices` synchronously. FM-11 (Prometheus registry conflict) is mitigated by `reset_metrics_for_tests()`.

---

## 6. Open questions (none blocking)

Both researchers ended with 0 open questions. R2's "OQ-1" (whether `warm.embedder: false` in the body is acceptable) is resolved by direct AC reading — the AC only asserts `chunk_count == marker_chunk_count`, NOT `warm.embedder == True`.

---

## 7. External writes the implementation will require

Both briefs agree: **NONE during implementation.** Single new test file at `tests/test_server_startup_integration.py`. The eventual `git push origin main` after Phase 4 is a separate per-event authorization per CLAUDE.md §4.4 — not pre-authorized. The state field is `[]`.

---

## 8. Orchestrator synthesis note

This is the cleanest convergence of the corpus-integrity-completion epic — both briefs identified the SAME load-bearing primitives, the SAME FM-1 dual-module-patch risk, the SAME monkeypatch target binding, the SAME divergence-threshold math, and reached the SAME implementation shape. No tensions to resolve at synthesis time.

Two brief-vs-reality mismatches (Mismatch A: `_graph_helpers.py` vs `_seed_corpus`; Mismatch B: `httpx.AsyncClient` vs sync `TestClient`) are deliberate corrections to the milestone brief. The implementer treats both as RESOLVED in the synthesis, with the documented research-grounding visible in §2.

Implementation path: **inline** (orchestrator main session). Estimated effort: ~110 LOC test code in one new file. Well under the 500 LOC / 5 files threshold for delegation. Determinism-reviewer specialist suggested by the roadmap but the implementation is straightforward (synthetic fixture via existing helpers — no novel determinism risk beyond what `_seed_corpus` already encodes); the adversary critic will catch any determinism gap if it slips in.

The integration test closes KR-1 of the parent epic ("end-to-end multi-paper write→/readyz integration test that fails on the pre-m1 bug shape") and is the headline deliverable both prior milestones' critiques cited as unmet.
