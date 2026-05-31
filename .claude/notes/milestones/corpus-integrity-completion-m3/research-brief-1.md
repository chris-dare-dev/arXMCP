# Research Brief — corpus-integrity-completion-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T00:00:00Z

## In-codebase context

### Load-bearing scaffolding — `tests/_graph_helpers.py`

`build_synthetic_lancedb` is the canonical LanceDB-only fixture builder:

```python
def build_synthetic_lancedb(
    lancedb_path: Path,
    rows: list[dict[str, Any]],
) -> Path:
```

It accepts a flat list of row dicts (each must include `chunk_id` and `paper_id`; other
required non-nullable columns — `section_path`, `body_text`, `body_tokens`,
`chunker_version`, `embedder_version` — get placeholder values). It calls
`lancedb.connect(str(lancedb_path))` and `db.create_table("chunks", data=table,
mode="create")`. **Critical gap for m3:** this helper does NOT call
`ingest.store.write_chunks`, so it does NOT write a `corpus-version.json` marker, does
NOT create HNSW indices, and does NOT invoke the BM25 indexer. A fixture built via this
helper alone will fail `Resources.startup()` — the startup code reads the marker at
`corpus_info = read_corpus_version(config.lancedb_path)` and raises
`CorpusNotIngestedError("corpus-version.json not found")` if absent.

**Conclusion:** `build_synthetic_lancedb` from `_graph_helpers.py` is NOT the right
primary tool here. The milestone brief says "use the synthetic-fixture pattern from
`tests/_graph_helpers.py`" but the implementing agent must use `write_chunks` directly
(as in `test_server_startup.py::_seed_corpus`), not `build_synthetic_lancedb`.

### Load-bearing scaffolding — `tests/test_server_startup.py`

The canonical bootstrap pattern is:

```python
def _seed_corpus(lancedb_path: Path) -> int:
    chunks = [ChunkRecord(chunk_id=..., paper_id=..., kind="stmt", ...) for i in (1, 2)]
    embeddings = EmbedRecord(
        chunk_ids_stmt=[c.chunk_id for c in chunks],
        embedding_stmt=np.stack(rows, axis=0),
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )
    return write_chunks(chunks, embeddings, lancedb_path=lancedb_path)
```

The lifespan is booted via `fastapi.testclient.TestClient` as a sync context manager:

```python
with TestClient(app) as client:
    yield client
```

The `with` block triggers the FastAPI lifespan (startup + shutdown). `httpx.AsyncClient`
is NOT used. The `warm_app` fixture pattern:

```python
@pytest.fixture
def warm_app(seeded_lancedb, mocked_bge_m3):
    cfg = Config(lancedb_path=seeded_lancedb)
    app = create_app(cfg)
    reset_metrics_for_tests()
    with TestClient(app) as client:
        yield client
```

BGE-M3 must be mocked in BOTH `server.query_encoder` AND `server.resources` modules
(the `test_corpus_count_reconciliation.py::_patch_model` helper does both):

```python
import server.query_encoder as qe_mod
import server.resources as res_mod
for mod in (qe_mod, res_mod):
    monkeypatch.setattr(mod, "_get_model", lambda: fake_model)
    monkeypatch.setattr(mod, "_get_tokenizer", lambda: fake_tokenizer)
```

The existing `mocked_bge_m3` fixture in `test_server_startup.py` patches ONLY
`server.query_encoder`. For m3, use the dual-patch pattern from
`test_corpus_count_reconciliation.py::_patch_model`.

### Load-bearing scaffolding — `tests/test_corpus_count_reconciliation.py`

The reconciliation tests use a real `write_chunks` call against a `tmp_path`-rooted
LanceDB. The mutation test pattern is:

```python
def _overwrite_marker_chunk_count(lancedb_path: Path, new_count: int) -> None:
    marker = lancedb_path / "corpus-version.json"
    data = json.loads(marker.read_text(encoding="utf-8"))
    data["chunk_count"] = new_count
    marker.write_text(json.dumps(data), encoding="utf-8")
```

This simulates post-write divergence by directly patching the JSON file. The m3 mutation
test goal differs: the AC says "monkey-patch `write_corpus_version_marker` to write a
deliberately-wrong `chunk_count`" — i.e. the test is meant to exercise a pre-m1 bug
shape where the marker is wrong as written (not corrupted afterward).

**The gap m3 closes:** All existing tests in `test_corpus_count_reconciliation.py` use
mocked resources or a JSON-rewrite mutation. None exercise the end-to-end
write→boot→readyz seam with multiple papers via a real `write_chunks` call.

### `ingest/store.py::write_chunks` and `write_corpus_version_marker`

Signature:
```python
def write_chunks(
    chunks: list[ChunkRecord],
    embeddings: EmbedRecord,
    lancedb_path: str | Path | None = None,
) -> int:
```

Returns the post-index LanceDB dataset version integer. Internally calls:

```python
chunk_count = tbl.count_rows()
paper_count = len(set(tbl.to_arrow().select(["paper_id"])["paper_id"].to_pylist()))
write_corpus_version_marker(
    target_path,
    version=dataset_version,
    chunker_version=CHUNKER_VERSION,
    embedder_version=embeddings.embedder_version,
    paper_count=paper_count,
    chunk_count=chunk_count,
)
```

The **m1 fix** (corpus-integrity-observability-m1) changed `chunk_count` from
`len(chunks)` (last-batch-only) to `tbl.count_rows()` (cumulative table count). This is
the seam m3 must exercise end-to-end.

`write_corpus_version_marker` is defined at module scope in `ingest/store.py` and called
via **local name reference** (not imported into another module) inside `write_chunks`.
Monkeypatching `ingest.store.write_corpus_version_marker` will work because `write_chunks`
and `write_corpus_version_marker` are in the same module and the call at line 946 uses the
module-level name directly.

### `server/health.py::readyz` response shape

The confirmed `/readyz` response shapes:

- **200 ready:** `{"status": "ready", "chunk_count": int|null, "marker_chunk_count": int,
  "warm": {"embedder": bool, "lancedb": bool, "reranker": bool}}`
- **503 not_ready:** `{"status": "not_ready", "warm": {...}}`
- **503 degraded:** `{"status": "degraded", "reason": str, "fallback_version": int,
  "original_version": int, "warm": {...}}`
- **200 bootstrap:** `{"status": "bootstrap", "bootstrap_mode_active": true, "warm": {...}}`

The `chunk_count` key is `None` when `startup_chunk_count < 0` (the -1 sentinel for
`count_rows()` failure at startup). `marker_chunk_count` is `resources.corpus_info.chunk_count`.

**When divergence triggers 503:** `resources.degraded` is set to
`DegradedState(reason="chunk_count_diverged", ...)` which causes a 503 with
`{"status": "degraded", "reason": "chunk_count_diverged", ...}`. The divergence path is
reached ONLY if the divergence exceeds `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE` (default
5%). For the mutation test to catch a wrong marker, the injected wrong `chunk_count` must
diverge by MORE than 5% from the actual table count.

### Design constitution references

- `05-storage-and-indexing.md`: "The corpus-version marker file `corpus-version.json` is
  co-located with the LanceDB dataset directory... `chunk_count` records the TOTAL ROWS
  in the committed chunks table."
- `07-multi-agent-caching.md`: No tool-schema change in this milestone — no BP1
  re-pinning required.

### `conftest.py` autouse fixtures

Five autouse fixtures fire for every test:
1. `_patched_store_stats_path` — redirects `ingest.store.STORE_STATS_PATH` to `tmp_path`
2. `_patched_bm25_stats_path` — redirects BM25 ops log
3. `_patched_bm25_index_root` — redirects `ingest.bm25_indexer.BM25_INDEX_ROOT` to `tmp_path`
4. `_reset_session_state_for_tests` — clears MCP session registry
5. `_patched_cache_db_path` — redirects `Config.cache_db_path` to `tmp_path`

These are all active for the new integration test. The BM25 index root autouse means
`Resources.startup()` will build a BM25 index under `tmp_path/bm25_index_root` —
appropriate for an integration test.

## Prior decisions and lessons

**Recent git log signal:**
- `c58c19e` (m1) and `951d3f3` (m1 rect): shipped alert rules + runbook stub
- `653986a` (m2) and `8180a0c` (m2 rect): shipped corpus-drift-runbook
- Both m1 and m2 critiques cite KR-1 as the "headline" unmet result: the end-to-end
  integration test (m3) remains the primary open gap at epic close

**m1 critique (relevant to m3):** Critique F1+F2 flagged that test coverage pins
names/shapes but not the write→read seam. m3 is the explicit answer to that gap.

**m2 critique (relevant to m3):** No findings that directly constrain m3 implementation.

**corpus-integrity-observability-m3 memory (MEMORY.md):** `lancedb 0.30.2`:
`tbl.list_indices()` returns `Iterable[IndexConfig]`; `tbl.index_stats(name)` returns
`Optional[IndexStatistics]` with `.num_unindexed_rows`. The `_create_indices` call in
`write_chunks` builds HNSW indices synchronously during `write_chunks`. After a real
`write_chunks` call on ≥1 chunk with non-null embeddings, `list_indices()` returns at
least one IVF_HNSW_SQ index. The `compute_unindexed_rows` function at startup reads
these; a freshly-written corpus should have 0 unindexed rows so the
`startup_unindexed_rows` gauge is 0, not -1.

**Banned patterns to watch:**
- No `assert` for invariants — use `if ... raise RuntimeError(...)`
- No `BaseHTTPMiddleware`
- `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` must not be removed
- No tool schema changes in this milestone — no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin needed

## External sources

**FastAPI test-client docs (version in use: fastapi>=0.115):** The sync `TestClient` with
a `with` block is the canonical lifespan-triggering pattern. `httpx.AsyncClient` with
`lifespan=` was added in ASGI-lifespan-aware versions but is NOT the established pattern
in this codebase. The milestone brief says "httpx.AsyncClient + the existing
tests/test_server_startup.py TestClient bootstrap pattern" — this is a slight
contradiction in the brief; the existing tests exclusively use sync `TestClient`. The
implementer should use sync `TestClient` (the established pattern).

**LanceDB (0.30.2 per pyproject.toml):** `lancedb.connect(str(path))` creates the DB;
`db.create_table("chunks", schema=CHUNKS_SCHEMA_V1)` creates the table; `write_chunks`
handles all of this internally. No direct LanceDB API calls needed in the test — `write_chunks`
is the one entry point.

**pytest `tmp_path`:** Works in sync tests. The existing pattern (`def test_...(tmp_path)`)
is correct. Async tests would require `pytest-asyncio` which is not present in this
project's dependencies (no `asyncio_mode` setting in `pyproject.toml`). The existing
tests use `asyncio.run(...)` for async calls inside sync test functions. This is the
correct pattern here too.

## Recommendation

Use the `_seed_corpus` pattern from `test_server_startup.py` — NOT `build_synthetic_lancedb`
from `_graph_helpers.py` — to write the multi-paper corpus. Specifically:

1. **Positive-path test:** Write 3 papers × ~10 chunks each (30 total) using a loop
   calling `write_chunks` once per paper (matching the production bulk-ingest
   per-paper call cadence). Use `CHUNKER_VERSION`, `EMBEDDER_VERSION`, and
   `EMBEDDING_DIM` from their canonical import locations. Use the dual-patch pattern
   from `test_corpus_count_reconciliation.py::_patch_model` (not the single-patch
   `mocked_bge_m3` fixture). Boot via sync `TestClient` with `with` block. Assert
   `body["status"] == "ready"` and `body["chunk_count"] == body["marker_chunk_count"]`.
   Call `reset_metrics_for_tests()` before booting.

2. **Mutation test:** Monkeypatch `ingest.store.write_corpus_version_marker` at the
   module level to record the call arguments and write an intentionally wrong `chunk_count`
   (e.g. `chunk_count=1` when actual table count is 30). Then boot the server and assert
   `/readyz` returns 503 with `body["status"] == "degraded"` and
   `body["reason"] == "chunk_count_diverged"`. The injected wrong count must differ from
   the actual table count by more than the 5% default tolerance — e.g., inject
   `chunk_count=1` for a 30-row table (97% divergence).

**Monkeypatch target:** `ingest.store.write_corpus_version_marker` (the correct module path
since `write_chunks` calls it by local name within `ingest/store.py`).

**Do NOT use async tests.** No `pytest-asyncio` dependency exists. Use `asyncio.run()`
for any async calls if needed (as in the existing `TestStartupReconciliation` tests).

## Open questions

**(a) FastAPI lifespan testing pattern:** Use sync `TestClient(app)` with a `with` block
— confirmed as the exclusive pattern in this codebase. The brief's mention of
`httpx.AsyncClient` is aspirational wording that contradicts the existing code; ignore it.
Recommendation: sync `TestClient`.

**(b) Does `_graph_helpers.py` provide a turn-key 3-paper LanceDB builder?** No.
`build_synthetic_lancedb` does NOT write a marker, does NOT build HNSW indices, and does
NOT boot `Resources.startup()` correctly. The implementer must use `write_chunks` directly
(same as `test_server_startup.py::_seed_corpus`), iterating across 3 papers.

**(c) Monkeypatch import site:** `write_corpus_version_marker` is called by `write_chunks`
at module scope in `ingest/store.py`. The monkeypatch target is
`ingest.store.write_corpus_version_marker`. This will intercept the call correctly because
Python name lookup for `write_corpus_version_marker` inside `write_chunks` resolves to
the module global at call time. No secondary import site exists (`server/corpus.py`
imports `CORPUS_VERSION_MARKER_NAME` and `DEFAULT_LANCEDB_PATH` from `ingest.store`, but
NOT the function itself).

**(d) Does `Resources.startup()` need special env-var gymnastics?** No. The test sets
`Config(lancedb_path=tmp_path / "lancedb")` — the same pattern used in
`TestStartupReconciliation`. `Resources.startup(cfg)` opens the LanceDB at
`config.lancedb_path`. The autouse `_patched_cache_db_path` fixture handles cache path
isolation automatically. No additional env-var patching is needed.

**(e) Does the synthetic LanceDB table need an HNSW index for `Resources.startup()` to
succeed?** When using `write_chunks` directly, HNSW indices ARE built by `_create_indices`
as part of the write. After a successful `write_chunks` call, the table has HNSW indices.
`compute_unindexed_rows` at startup will find 0 unindexed rows (clean state). If
`build_synthetic_lancedb` were used instead (it does NOT call `_create_indices`),
`startup_unindexed_rows` would be -1 (no index found) — a WARN, not a startup failure.
But since we use `write_chunks`, this is a non-issue.

**No open questions — implementation can proceed on the above recommendation.**

## External writes the implementation will require

None — this milestone is purely local. The only write after Phase 4 will be
`git push origin main` authorized per-event by the user in Phase 4.
