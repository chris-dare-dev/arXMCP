# Research Brief — onboarding-uplift-m4

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T18:00:00Z

---

## In-codebase context

### 1. `server/config.py::Config` — field declaration pattern

The existing bool field pattern (verbatim from `server/config.py:205-206`):

```python
enable_lean: bool = False
```

No `Field(...)` wrapper needed. `SettingsConfigDict(env_prefix="ARXMCP_")` means any field
named `bootstrap_mode` automatically reads `ARXMCP_BOOTSTRAP_MODE`. Pydantic-settings
applies bool coercion from strings ("1", "true", "yes" → True) automatically for `bool`
fields with no explicit `Field`. The existing `enable_rerank: bool = False` and
`enable_lean: bool = False` confirm this pattern.

The `extra="forbid"` line (`server/config.py:83`) means `ARXMCP_BOOTSTRAP_MODE` MUST be
declared on `Config` — otherwise `_scan_unknown_arxmcp_env_vars` in `server/main.py`
raises at startup (`server/main.py:396`).

**Recommendation for new field** (verbatim compatible pattern):

```python
#: onboarding-uplift-m4 — opt-in bootstrap mode. When True + no
#: corpus-version.json, Resources.startup skips CorpusNotIngestedError
#: and registers a stub reader. Default False = cold-start without a
#: corpus is still FATAL (D1: no silent flip; no production footgun).
bootstrap_mode: bool = False
```

**Important conflict to flag:**
The `Config.derive_notebook_lancedb_path` validator at `server/config.py:510-515`
already does `if not (derived / "corpus-version.json").is_file(): raise ValueError(...)`.
When `bootstrap_mode=True` AND `ARXMCP_NOTEBOOK=<slug>` is also set, this validator fires
BEFORE `Resources.startup` and will still fatal. The bootstrap mode guard in
`Resources.startup` cannot reach it. **The implementer must add a bootstrap_mode check to
`derive_notebook_lancedb_path` or document that `ARXMCP_NOTEBOOK` + bootstrap_mode is
unsupported.**

### 2. `server/resources.py::Resources.startup` — the CorpusNotIngestedError raise site

The exact raise site (verbatim, `server/resources.py:439-447`):

```python
# 1. Corpus marker — REFUSE TO START on absent (synthesis D5).
corpus_info = read_corpus_version(config.lancedb_path)
if corpus_info is None:
    marker = Path(config.lancedb_path) / "corpus-version.json"
    raise CorpusNotIngestedError(
        f"corpus-version.json not found at {marker}; "
        f"run the ingest pipeline first. The server "
        f"refuses to start on a cold-start corpus state."
    )
```

The bootstrap mode branch REPLACES this raise with:
- Set `corpus_info = None` (skip the read).
- Set `chunks_table = None` (no table to open — skip steps 2, 2b, 2c).
- Skip BM25Phase.startup (it needs `live_chunk_ids` from `chunks_table.to_arrow()`).
- Skip `RetrievalCache.open` (its key includes `corpus_info.version` — cannot be called with None corpus_info).
- Proceed to create the `Resources` instance with sentinel values and `warm=False`.

**Critical downstream consumers of `resources.chunks_table`** (all require a null check in stub mode):
- `server/handlers/chunk.py:53` — `r.chunks_table.search()...`
- `server/handlers/search.py:528` — `search_table = r.chunks_table`
- `server/handlers/equation.py` — direct `chunks_table` query
- `server/handlers/lemma.py` — direct `chunks_table` query
- `server/handlers/paper.py` — direct `chunks_table` query
- `server/handlers/definitions.py` — via `r.definitions_table` (separately null-able)

**Also** — `envelope()` in `server/tools.py:420` calls `get_resources().corpus_info.version`.
If `corpus_info is None` in bootstrap mode, this will `AttributeError`. The stub-mode
check must happen BEFORE `envelope()` is called in any handler.

**`Resources` dataclass field** — no existing `bootstrap_mode_active: bool` field. The
implementer adds one:

```python
bootstrap_mode_active: bool = False
```

The late-binding flip sets this to `False` after successful ingest. Handlers check this first.

### 3. MCP tool handler surface

**`server/tools.py:360-421`** — registration + `envelope` helper:

```python
def get_resources() -> Resources:
    ...
def envelope(
    payload: dict[str, Any],
    *,
    override_corpus_version: int | None = None,
) -> dict[str, Any]:
```

The `envelope()` function reads `get_resources().corpus_info.version` (line 420). In
bootstrap mode, `corpus_info` is `None` → this crashes. The stub-check helper must either:
(a) use a sentinel `corpus_version = -1` in bootstrap mode, OR
(b) call `envelope()` only after confirming the stub-check passes.

**Handlers that depend on `chunks_table`** (require the bootstrap check at the top):
- `server/handlers/search.py` — `handle_search_papers`
- `server/handlers/chunk.py` — `handle_get_chunk`
- `server/handlers/equation.py` — `handle_find_equation`
- `server/handlers/lemma.py` — `handle_find_lemma_by_name`
- `server/handlers/paper.py` — `handle_get_paper`
- `server/handlers/definitions.py` — `handle_get_definitions`

`server/handlers/citations.py` — `handle_cite_neighbors` uses `r.config.kuzu_path`, not
`r.chunks_table`, but citation graph may also be absent in bootstrap mode.

**Error envelope shape** (from `server/tools.py:399-422` + `server/handlers/chunk.py:58-67`):

```python
return envelope({"chunk": None, "found": False, ...})
```

The stub-mode envelope must match this structure but use a sentinel `corpus_version`. The
`no_notebook_selected` envelope from the brief should be:

```python
{"error": "no_notebook_selected", "message": "<actionable hint>", "corpus_version": -1}
```

Note: `corpus_version: -1` avoids calling `envelope()` with a null `corpus_info`.

### 4. `/ui/api/notebooks/*` REST pattern for new endpoints

**`server/routes/notebooks.py`** dependency injection for `NotebooksStore` (line 170-185):

```python
def get_notebooks_store(request: Request) -> NotebooksStore:
    store = getattr(request.app.state, "notebooks_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="notebook store not initialized")
    return store
```

**The analogous pattern for `ingest_jobs`** — `app.state.ingest_tracker` already exists
at `server/main.py:522`:

```python
app.state.ingest_tracker = IngestTaskTracker()
```

The new `POST /ingest` and `GET /ingest-status` endpoints should access
`app.state.ingest_tracker` directly (same DI pattern as `get_notebooks_store` but reading
`request.app.state.ingest_tracker`). **No new `app.state.ingest_jobs` dict is needed** —
`IngestTaskTracker` (at `server/ingest_tracker.py`) already provides the live-task
registry. The ingest-status endpoint reads from `NotebooksStore` which stores
`{status, started_at, finished_at, last_error}` per run via `IngestTaskTracker`.

**Existing POST pattern** (`add_paper`, `server/routes/notebooks.py:499-551`):
Returns 201 + JSON dict `{"slug": slug, "paper_id": paper_id}`.
The new `POST /ingest` mirrors this: returns 202 + `{"slug": slug, "job_id": "<uuid>", "status": "started"}`.

### 5. Existing ingest pipeline

**`tools/notebook_fetch.py:77`** — `def run(slug: str, *, sleep_seconds: float = ...) -> int:`
**`tools/notebook_ingest.py:73`** — `def run(slug: str) -> int:`

The existing `IngestTaskTracker._run_ingest_subprocess` at `server/ingest_tracker.py:200`
already wraps BOTH via `asyncio.create_subprocess_exec` calling
`tools/notebook_ingest.py <slug>` as a subprocess. The m9 architecture is **subprocess-
over-in-process**. The new `POST /ingest` endpoint should REUSE `IngestTaskTracker.spawn`
rather than creating a new in-process coroutine approach.

**Phase boundaries from the subprocess stdout/stderr** — the notebook_ingest subprocess
currently prints `bulk_ingest: total=N ok=N fail=N ...` to stdout. Parsing this for
fine-grained phase progress requires either: (a) modifying the subprocess to emit
structured progress events, OR (b) inferring progress from DB rows. The brief's
`downloading_model` / `fetching` / `chunking` / `embedding` / `indexing` / `done` phases
suggest (a) or a synthetic progress estimate.

**The BGE-M3 cold-start** happens inside the subprocess at its first embed call, not in
the server process. The `bytes_done`/`bytes_total` shim must be in the SUBPROCESS, not the
server process — making the D5 huggingface_hub tqdm shim a cross-process progress concern.

### 6. BGE-M3 download — where it happens

`ingest/embedder.py:302-340` — `_get_model()` uses `AutoModel.from_pretrained(...)`. This
calls `huggingface_hub` internally to download safetensors. BGE-M3 uses `transformers`
(not `sentence_transformers`) as confirmed by `from transformers import AutoModel` at line
314. The download mechanism is `huggingface_hub`'s file download, which uses `tqdm`.

The `huggingface_hub.utils.tqdm` monkeypatch approach would work IF the model download
happens in the server process. But the `IngestTaskTracker` architecture runs ingest as a
**subprocess** (`asyncio.create_subprocess_exec`). The subprocess has its own memory space;
a monkeypatch in the server process cannot intercept the subprocess's tqdm callbacks.

**This is a significant architectural challenge for D5.** Options:
1. The subprocess writes `bytes_done`/`bytes_total` to a shared file/pipe that the server
   polls.
2. Detect "model already downloaded" by checking
   `~/.cache/huggingface/hub/models--BAAI--bge-m3/` existence before spawn.
3. Simplify D5: report `phase="downloading_model"` with `bytes_total=-1` (unknown) when
   the model cache is absent, and skip the shim entirely.

The brief specifies "intercept huggingface_hub's tqdm callbacks" but this conflicts with
the subprocess isolation architecture already in `IngestTaskTracker`.

### 7. Late-binding mechanism

**No existing `reload_after_cutover` method** exists in `server/resources.py`. The
existing pattern is startup-once-permanent — the server never auto-switches corpus.

For late-binding after ingest completes, the implementer needs:

1. A module-level `asyncio.Lock` or the existing `resources._notebook_tables_lock` analog.
2. After ingest done_callback fires, call a new `Resources.late_bind(config)` coroutine:
   - Re-read `corpus-version.json` from `config.lancedb_path`.
   - Open `chunks_table` at the new version.
   - Rebuild `BM25Phase` with the live `chunk_ids`.
   - Open `RetrievalCache`.
   - Set `resources.bootstrap_mode_active = False`.
   - Set `resources.warm = True`.

**The `Singleflight` class in `server/resources.py:134`** provides the cancellation-safe
in-flight deduplication. A new `asyncio.Lock` on the `Resources` instance (or on the
`late_bind` coroutine path) serializes the flip so in-flight handlers either see the old
state (all-stub) or the new state (fully warm), never a half-flipped state.

**The `set_resources()` / `get_resources()` module-level singleton** in `server/tools.py:360-375`
is the existing access pattern. Late-binding does NOT need to replace the `Resources`
instance — it mutates the fields of the EXISTING instance (the same object that
`get_resources()` returns). Thread safety: asyncio event loop is single-threaded; no mutex
needed if the late_bind is an `async` method and all handlers are coroutines (which they
are — FastMCP handlers are async).

### 8. `make up-wizard` target

**Existing `make up` recipe** (verbatim from `Makefile:153-157`):

```makefile
up:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make up PYTHON=python3.$(MIN_PY_MINOR)'"
	$(PYTHON) -m server.main
```

The new target:

```makefile
up-wizard:
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
		f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}. \
Try: make up PYTHON=python3.$(MIN_PY_MINOR)'"
	ARXMCP_BOOTSTRAP_MODE=1 $(PYTHON) -m server.main
```

The `VAR=val $(MAKE) target` idiom exports the env var for the child make process.
`ARXMCP_BOOTSTRAP_MODE=1 $(PYTHON) -m server.main` sets it inline for the single
command — the cleaner form. The Python version check must be repeated (or extracted into a
macro) since `make up-wizard` does not call `make up`. The `PYTHON` variable is already
defined at `Makefile:26`.

### 9. Existing tests for `Resources.startup`

**`tests/test_server_startup.py`** — `_seed_corpus(lancedb_path)` (line 56) seeds a 2-chunk
corpus. **`tests/test_corpus_count_reconciliation.py`** — `TestStartupReconciliation` at
line 14 runs real `Resources.startup` with mocked model.

**The fixture pattern** (from `tests/test_server_startup.py:56-86`):
```python
def _seed_corpus(lancedb_path: Path) -> int:
    """Ingest a tiny 2-chunk corpus and return its corpus_version."""
    ...
    return write_chunks(chunks, embeddings, lancedb_path=lancedb_path)
```

The new `test_bootstrap_mode.py` calls `Resources.startup(config_with_empty_lancedb_path)`
with `Config(bootstrap_mode=True)` and verifies no exception is raised. For the non-
bootstrap case, it verifies `CorpusNotIngestedError` is raised.

### 10. BP1/BP2 cross-check

**Confirmed safe.** `bootstrap_mode` is a `Config` field — it affects `Resources.startup`
behavior, not the `tools/list` JSON schema. `EXPECTED_TOOL_SCHEMA_SHA256` is the SHA256
of the serialized `ALL_TOOLS` list (tool names + descriptions + inputSchema from type
annotations). None of those change. `EXPECTED_BP1_SHA256` hashes `{name, description}` per
tool from `server/tools.py`. Neither is touched.

The `no_notebook_selected` error envelope is returned in `tools/call` RESPONSE body, not
in `tools/list`. **EXPECTED_TOOL_SCHEMA_SHA256 is UNCHANGED. EXPECTED_BP1_SHA256 is
UNCHANGED.** AC10 is safe.

### 11. Recent git log

Last 5 commits:
- `867edb7` — `chore(notes): finalize onboarding-uplift-m3 state -> complete`
- `b242eb4` — `rect(server,tools,tests): close F1+F2+F3+F4+IS1 from m3 critique`
- `72d5e18` — `feat(server,tools,tests): repair-registry + reconcile-marker + health`

**m3 just completed.** No parallel-session work on `server/resources.py`, `server/config.py`,
or `server/main.py` in the last 20 commits that would conflict with m4 scope. The m3 work
added `repair_registry`, `reconcile_marker`, and `notebook_health` endpoints to
`server/routes/notebooks.py` — the file this milestone also touches for the new ingest
endpoints.

---

## Prior decisions and lessons

**m3 lesson (from MEMORY.md):** `Resources.startup_chunk_count` measures the SHARED
corpus, not per-notebook LanceDB. In bootstrap mode, `startup_chunk_count` should be `-1`
(unavailable sentinel) since there is no corpus yet.

**m9 architecture is subprocess-based:** `server/ingest_tracker.py` already exists with
`IngestTaskTracker` using `asyncio.create_subprocess_exec`. The new POST /ingest endpoint
MUST use this existing tracker rather than inventing a new in-process approach.

**m9 `IngestTaskTracker.spawn` already provides:** 409 on duplicate slug (via
`is_running(slug)` check), DB row insertion before task spawn (FM-7 closure), and
`done_callback` for status updates.

**m2 critique F1 lesson (from MEMORY.md):** Every write to `notebooks.db::notebooks` MUST
go through `NotebooksStore.create_notebook`. Direct SQLite INSERTs are BANNED.

**m7 rect F2:** `IngestTaskTracker` is created in `server/main.py:522` as
`app.state.ingest_tracker`. The new GET `/ingest-status` endpoint accesses it via
`request.app.state.ingest_tracker`.

**`_scan_unknown_arxmcp_env_vars`** at `server/main.py:359` — **load-bearing**: `bootstrap_mode`
MUST be declared on `Config` before `ARXMCP_BOOTSTRAP_MODE=1` works, otherwise the startup
scan raises `ValueError: unknown ARXMCP_* environment variables`.

---

## External sources

No MCP spec or prompt-caching docs are relevant to this milestone. Bootstrap mode is a
server-internal startup behavior change with no effect on the MCP wire protocol or
tool-schema bytes. The `tools/list` response and all BP1/BP2 caching behavior are
unchanged.

No external sources consulted — all load-bearing constraints are in the codebase.

---

## Recommendation

**Use the existing `IngestTaskTracker` subprocess architecture for `POST /ingest`.**
Do NOT invent a new in-process async background task for ingest — `server/ingest_tracker.py`
already solves the 409/idempotency, done_callback, DB row, and SIGTERM cleanup problems.
The new endpoint is a thin wrapper that calls `tracker.spawn(slug, store)` and returns 202.

For `GET /ingest-status`, read from `NotebooksStore`'s existing ingest row schema (the
`status`, `started_at`, `finished_at`, `last_error` fields already written by
`IngestTaskTracker`).

For bootstrap mode in `Resources.startup`: add a branch after the `corpus_info is None`
check — when `config.bootstrap_mode is True`, skip the raise, set `corpus_info = None`,
`chunks_table = None`, `bm25_phase = None`, `cache = None`, `bootstrap_mode_active = True`,
`warm = False` (readyz stays 503 or returns a bootstrap-specific body), and construct the
`Resources` instance with these sentinels. Skip steps 2-6c entirely.

For **D5 BGE-M3 progress**: simplify to a best-effort approach — detect if
`~/.cache/huggingface/hub/models--BAAI--bge-m3/` exists before spawning the subprocess.
If absent, set `phase="downloading_model"` with `bytes_total=-1` for the first N minutes
of the ingest. The full `huggingface_hub.utils.tqdm` shim is not feasible across a
subprocess boundary without a shared IPC channel (pipe or file). The brief's D5 spec
should be implemented as a `bytes_total=-1` (unknown) sentinel rather than real byte
tracking.

---

## Open questions

**(a) `/readyz` in bootstrap mode: 200 or 503?**
The brief defers to synthesis. My recommendation: return **200 with a structured body
containing `"status": "bootstrap"`** distinct from the normal `"status": "ok"`. This lets
the UI load (`/ui/` IS reachable — AC1) while `warm = False` prevents misleading the shim
into thinking retrieval is ready. The shim (`shim/arxmcp_shim.py`) polls `/readyz` before
forwarding MCP tool calls — it should NOT proceed to tool calls in bootstrap mode, which
the structured `"status": "bootstrap"` body allows the shim to distinguish from a real
`200 ok`. This is a design decision only the implementer can finalize.

**(b) Late-binding flip serialization:**
The event loop is single-threaded and all handlers are coroutines, so field mutation
inside the Resources instance is safe WITHOUT an asyncio.Lock IF:
- The done_callback schedules `asyncio.create_task(resources.late_bind(...))` (runs on the
  event loop, not in a thread).
- The late_bind coroutine is itself not reentrant (use `resources.bootstrap_mode_active`
  as a double-check guard at the top).

No separate `asyncio.Lock` is needed — the event loop's cooperative multitasking is the
serialization. **This is confident; no open question here.**

**(c) HF_HUB_OFFLINE=1 and the D5 shim:**
If `HF_HUB_OFFLINE=1` is set in the subprocess environment, `huggingface_hub` will skip
downloads and the model load either succeeds (model cached) or fails (model absent). In
tests, `HF_HUB_OFFLINE=1` causes the model to be absent → the model-load raises. But since
m4 ingest tests will mock the subprocess (not run a real subprocess), the D5 shim tests
are separately bounded. The simpler `bytes_total=-1` approach is immune to this concern
entirely.

**(d) `ARXMCP_NOTEBOOK + bootstrap_mode` conflict:**
**FLAG:** `Config.derive_notebook_lancedb_path` at `server/config.py:510-515` checks for
`corpus-version.json` and raises `ValueError` when absent, REGARDLESS of `bootstrap_mode`.
Setting both `ARXMCP_NOTEBOOK=<slug>` and `ARXMCP_BOOTSTRAP_MODE=1` will fatal at config
parse time. The implementer must either: (1) add a `bootstrap_mode` check to the validator
(requires accessing `self.bootstrap_mode` inside `derive_notebook_lancedb_path`), or (2)
document that the combination is unsupported. Recommendation: document as unsupported for
m4; the per-notebook bootstrap path is m5+ scope.

---

## External writes the implementation will require

None — this milestone is purely local.
