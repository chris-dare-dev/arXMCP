# Research Brief — onboarding-uplift-m4

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T15:10:00Z

---

## In-codebase context

### Existing ingest infrastructure (NOT tabula rasa)

The brief's proposed `app.state.ingest_jobs` dict and `IngestJob` dataclass **do not exist yet**. However, the existing codebase already has a mature parallel infrastructure from onboarding-uplift-m9:

- `server/ingest_tracker.py` — `IngestTaskTracker` with `_tasks: dict[str, asyncio.Task]`, `_global_cap: asyncio.Semaphore(1)`, `is_running(slug)`, `start_ingest(...)`, `shutdown()`. It launches SUBPROCESS-based ingests (`asyncio.create_subprocess_exec tools/notebook_ingest.py <slug>`), not in-process async tasks.
- `app.state.ingest_tracker` — already wired in lifespan (`server/main.py:522`).
- `app.state.parse_tracker` — `ParseTaskTracker` for PDF parse (lifespan `server/main.py:528`).
- `POST /ui/api/notebooks/<slug>/ingest` — already exists at `server/routes/notebooks.py:1634`, returns 202 HTML fragment.
- `GET /ui/api/notebooks/<slug>/ingest/latest` — already exists at `server/routes/notebooks.py:1713`.

**CONFLICT FLAG: the brief's scope item 4 ("TWO new endpoints: POST /ui/api/notebooks/<slug>/ingest, GET /ui/api/notebooks/<slug>/ingest-status") collides with already-shipped endpoints from m9.** The ingest-trigger and ingest-status surface is already largely built. The m4 additions are: (1) bootstrap mode in `Resources.startup`, (2) late-binding flip, (3) BGE-M3 progress shim wired into the ingest orchestrator, (4) the `bootstrap_mode` config field.

### `Resources.startup` current behavior (load-bearing)

From `server/resources.py:440-447`:
```python
corpus_info = read_corpus_version(config.lancedb_path)
if corpus_info is None:
    marker = Path(config.lancedb_path) / "corpus-version.json"
    raise CorpusNotIngestedError(
        f"corpus-version.json not found at {marker}; "
        f"run the ingest pipeline first. The server "
        f"refuses to start on a cold-start corpus state."
    )
```
This is the exact branch the bootstrap mode branch must intercept. The m4 implementation inserts: `if corpus_info is None and config.bootstrap_mode: ... (skip raise, register stub) else: raise`.

### Existing `app.state` keys (no collision)

Current lifespan sets: `app.state.config`, `app.state.resources`, `app.state.mcp_server`, `app.state.notebooks_store`, `app.state.ingest_tracker`, `app.state.parse_tracker`. The brief's proposed `app.state.ingest_jobs` is a NEW key not present today — no collision, but the brief's framing is conceptually superseded by the already-shipped `IngestTaskTracker` pattern. The implementer should extend `IngestTaskTracker` to expose phase/bytes progress rather than introducing a second parallel job registry.

### Design note 08 logging discipline (verbatim, load-bearing)

From `08-security-observability-ops.md`: "Sensitive fields (full query text, chunk bodies) are logged at DEBUG only, never at INFO or above." This applies directly to FM-11 (IngestJob.last_error must not contain stack traces at INFO). The existing `ingest_tracker.py` already implements path redaction (`_ABS_PATH_PREFIX_RE`) and HTML escaping — these patterns apply to any new progress/error fields.

### AC10 tool-schema stability (load-bearing)

"EXPECTED_TOOL_SCHEMA_SHA256 + EXPECTED_BP1_SHA256 UNCHANGED — bootstrap mode is a server-internal state, not a tool input." The new endpoints are under `/ui/api/`, NOT `/mcp/`. No MCP tool schema change. Per `07-multi-agent-caching.md` Property 1: "A casual edit to a tool description blows every sub-agent's cache." This constraint is satisfied by routing new surface to the UI tier.

---

## Prior decisions and lessons

**From agent memory:**

- `startup_chunk_count` measures the SHARED global corpus, NOT per-notebook LanceDB. In bootstrap mode, `startup_chunk_count` will be `-1` (sentinel) since no corpus exists. Health endpoints must handle this.
- `write_corpus_version_marker` sets `created_at=datetime.now(UTC)` on each call — idempotency hazard on re-run. The existing m3 fix: write marker LAST, atomically. The bootstrap mode must NOT write the marker during the stub phase.
- `SecFetchSiteMiddleware` only allows `same-origin` on `exempt_prefixes` (currently `/ui`). New endpoints under `/ui/api/` inherit this exemption correctly.
- The `KMP_DUPLICATE_LIB_OK=TRUE` guard in `tests/conftest.py` is load-bearing — BGE-M3 progress shim must not touch this fixture.

**From git log:**

Recent commits show `onboarding-uplift-m3` closed with `write_corpus_version_marker` idempotency fixes and `repair-registry` / `reconcile-marker`. The m4 work inherits these patterns but the implementer must be aware that the ingest surface from m9 (subprocess-based) conflicts with the brief's description of in-process `asyncio.create_task`.

**Key conflict from m9:** `IngestTaskTracker.start_ingest` runs `notebook_ingest.py` as a SUBPROCESS with a global semaphore of 1. The brief describes a new in-process `server/ingest_orchestrator.py`. These are architecturally different. The subprocess approach (m9) gives crash isolation; the in-process approach gives direct access to progress state without IPC. **The implementer must decide which pattern to extend.** Recommendation below picks one.

---

## External sources

### FastAPI BackgroundTasks

From https://fastapi.tiangolo.com/tutorial/background-tasks/ (fetched 2026-05-31):

> "You can define background tasks to be run _after_ returning a response."

BackgroundTasks runs AFTER the response is sent — fire-and-forget, not queryable mid-flight. For long-running jobs, the FastAPI docs explicitly recommend external queues (Celery, RQ). However, the existing codebase uses the better pattern: `asyncio.create_task(...)` stored in `IngestTaskTracker._tasks` dict. This keeps a strong reference (preventing GC) and makes the task queryable.

**On SIGTERM:** FastAPI/uvicorn sends `CancelledError` to `asyncio.Task`s during shutdown. The existing lifespan (`server/main.py:540-542`) calls `await ingest_tracker.shutdown()` which cancels in-flight tasks. The marker is NOT written on cancellation — this is the correct pattern.

### `huggingface_hub` download progress

The manage-cache docs do not expose a `tqdm` interception API directly. The correct approach for progress shim is to monkeypatch `huggingface_hub.utils.tqdm` (the internal tqdm wrapper). The `sentence-transformers` library (which loads BGE-M3) uses `huggingface_hub.snapshot_download` / `hf_hub_download` internally, which wraps progress in `huggingface_hub.utils.tqdm`. The relevant class is `huggingface_hub.utils._tqdm.tqdm` — wrapping its `__init__` and `update(n)` methods allows intercepting `n` (bytes transferred) and `total` (total bytes).

Verified pin from `pyproject.toml`: `transformers>=4.40`, `safetensors>=0.4`. No explicit `huggingface-hub` pin found — it is pulled transitively. The `sentence-transformers` package is NOT listed in `pyproject.toml` — BGE-M3 is loaded directly via `transformers.AutoModel.from_pretrained`, which uses `huggingface_hub` for download.

For `HF_HUB_OFFLINE=1`: `huggingface_hub` skips all HTTP calls and raises `OfflineModeIsEnabled` before the tqdm wrapper is ever invoked. The shim must guard with `try/except` around the monkeypatch or test for offline mode and skip progress tracking silently.

### MCP 2025-06-18 spec on tool error handling

From https://modelcontextprotocol.io/specification/2025-06-18/server/tools (fetched 2026-05-31):

> "Tools use two error reporting mechanisms:
> 1. **Protocol Errors**: Standard JSON-RPC errors for issues like: Unknown tools, Invalid arguments, Server errors
> 2. **Tool Execution Errors**: Reported in tool results with `isError: true`: API failures, Invalid input data, **Business logic errors**"

Example from spec:
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "content": [{"type": "text", "text": "Failed to fetch weather data: API rate limit exceeded"}],
    "isError": true
  }
}
```

**Verdict on AC8:** The spec EXPLICITLY supports returning a structured error envelope with `isError: true` rather than raising a JSON-RPC protocol error. "Bootstrap mode active — no corpus" is a business logic condition, not a protocol error. The AC8 `{"error": "no_notebook_selected", "message": "..."}` envelope returned via `envelope(...)` with `isError=True` is fully spec-compliant. No MUST clause requires a JSON-RPC error for this case.

### `asyncio.create_task` lifecycle

Per Python docs (quoted by `ingest_tracker.py` inline): "Save a reference to the result of [create_task], to avoid a task disappearing mid-execution." The existing `IngestTaskTracker._tasks` dict holds strong references. If the task reference is only in a local variable inside a request handler, the GC CAN collect it mid-flight when the handler function returns. **The implementer MUST store the task reference in `app.state.ingest_tracker._tasks`, not in a local variable.**

---

## Failure-mode enumeration

**FM-1: SIGTERM during mid-flight in-process ingest**

- **Trigger:** `SIGTERM` arrives while the ingest orchestrator is inside `embed()` or `notebook_ingest.run()`.
- **Symptom:** asyncio cancels the ingest task; partial LanceDB rows may exist; `corpus-version.json` not yet written.
- **Mitigation:** The existing `ingest_tracker.shutdown()` calls `task.cancel()` and awaits. The ingest coroutine MUST catch `asyncio.CancelledError` in `try/finally`, call `store.mark_ingest_failed(slug, "cancelled")`, and re-raise. LanceDB MVCC means partial rows from a cancelled write are unreachable (version not committed). Do NOT write the corpus-version marker on cancel path.

**FM-2: Late-binding race — MCP query at exact moment of ingest completion**

- **Trigger:** Ingest coroutine calls `resources.late_bind(corpus_info, chunks_table)` while a concurrent MCP handler reads `resources.bootstrap_mode_active`.
- **Symptom:** Handler reads `bootstrap_mode_active=True`, enters stub path, but corpus is now live — query returns error even though corpus is ready.
- **Mitigation:** Use `asyncio.Event` for the one-way flip. `resources._corpus_ready_event: asyncio.Event`. Ingest calls `event.set()` atomically. Handlers that check `not event.is_set()` see consistent state. No lock needed — `asyncio.Event.set()` is a one-time, non-contended operation. Do NOT use a `bool` flag with a separate `asyncio.Lock` — that requires acquiring the lock on every handler invocation (hot path).

**FM-3: Half-failed first ingest — partial chunks written, no marker**

- **Trigger:** Ingest crashes at embedder phase; some LanceDB rows written; `corpus-version.json` not written.
- **Symptom:** Stub reader stays active. Second ingest attempt starts clean. But the stale partial LanceDB rows may consume disk space and could confuse row counts.
- **Mitigation:** Do NOT write the corpus-version marker until ALL phases complete. The existing `_write_marker_atomically` (in `server/routes/notebooks.py:684`) enforces this pattern. The stub check uses the marker's absence as the gate — no marker = still in bootstrap. LanceDB MVCC: the partial rows are unreachable via `open_chunks_table(version=N)` until a new version is committed.

**FM-4: BGE-M3 download interrupted mid-flight**

- **Trigger:** Network drops during HuggingFace model download.
- **Symptom:** `hf_hub_download` raises an exception; `bytes_done` shim stops updating.
- **Mitigation:** HuggingFace hub uses partial-file blobs — resume is automatic on retry (the blob cache in `~/.cache/huggingface/hub/` stores incomplete blobs and resumes). The progress shim will see `n` reset to 0 on resume start; the `IngestJob.bytes_done` field should be cumulative across retries OR reset per-retry with a clear phase label. Recommend: reset to 0 on retry start, update `bytes_done` incrementally as `update(n)` fires. This handles restart-from-partial cleanly since `total` stays constant.

**FM-5: Two concurrent POST /ingest against the SAME slug**

- **Trigger:** Double-click on "Ingest" button, or two operators.
- **Symptom:** Without a guard, two subprocess tasks spawn for the same slug.
- **Mitigation:** Already handled by `IngestTaskTracker.is_running(slug)` (in-memory check) + `store.has_running_ingest(slug)` (DB fallback). Returns 409. The global semaphore cap=1 also prevents two ingests running concurrently even for different slugs — though this is overly restrictive (see FM-6).

**FM-6: Two concurrent POST /ingest against DIFFERENT slugs**

- **Trigger:** Two operators ingest two different notebooks simultaneously.
- **Symptom:** The existing `_global_cap = asyncio.Semaphore(1)` in `IngestTaskTracker` means the SECOND ingest blocks until the FIRST completes. For bootstrap mode, this is acceptable (single operator, single notebook scenario).
- **Mitigation:** No change needed for m4 scope. The global cap is a documented design choice from m9 FM-1 (resource exhaustion guard). For bootstrap mode with one operator, it works correctly.

**FM-7: bootstrap_mode=True but corpus-version.json ALREADY EXISTS**

- **Trigger:** Operator sets `ARXMCP_BOOTSTRAP_MODE=1` but corpus was previously ingested.
- **Symptom:** Without a guard, the server enters bootstrap mode unnecessarily, serving stub responses despite a valid corpus.
- **Mitigation:** In `Resources.startup`, the check is: `if corpus_info is None and config.bootstrap_mode`. If `corpus_info` is NOT None (marker exists), skip the bootstrap branch entirely and boot normally. Log `INFO "bootstrap_mode requested but corpus already ingested; booting normally"`. The bootstrap flag is silently ignored.

**FM-8: Server restart with ARXMCP_BOOTSTRAP_MODE=1 after successful ingest**

- **Trigger:** Operator left `make up-wizard` alias; server restarts.
- **Symptom:** Per FM-7 mitigation, the marker now exists so the server boots in normal mode. The `bootstrap_mode=1` flag is benign.
- **Mitigation:** None needed. FM-7 resolution handles this automatically.

**FM-9: Handler bypasses stub-check — missing bootstrap guard**

- **Trigger:** A future handler is added without the stub-check helper, or an existing handler has the check on the WRONG branch.
- **Symptom:** In bootstrap mode, the handler reaches `resources.chunks_table` which is `None` (stub) and raises `AttributeError`/`NoneType` — returns 5xx instead of the structured stub envelope.
- **Mitigation:** Implement stub-check at the ORCHESTRATOR level, not per-handler. The `set_resources()` / `get_resources()` call chain in `server/tools.py` is the centralized entry point. Adding a `_check_bootstrap(resources)` guard inside the top-level `handle_call()` dispatch (before routing to per-handler functions) ensures all handlers are covered automatically. Do NOT rely on per-handler calls — the "missed handler" failure mode is documented as the cardinal safety check.

**FM-10: Aggressive polling of ingest-status while ingest is writing progress**

- **Trigger:** htmx polls `GET /ui/api/notebooks/<slug>/ingest/latest` every 2s; ingest orchestrator writes `bytes_done` to `IngestJob` concurrently.
- **Symptom:** Torn read — handler sees partial progress update.
- **Mitigation:** Since both the poll handler and the ingest orchestrator run in the SAME asyncio event loop (single-threaded), there is NO concurrent access hazard for pure Python attribute reads/writes. `asyncio` tasks yield at `await` points only — plain attribute assignment `job.bytes_done = n` is atomic within a single event loop. No lock needed. This is different from a threading model.

**FM-11: IngestJob.last_error contains stack trace with absolute paths (PII / D6)**

- **Trigger:** Ingest orchestrator catches an exception and stores `str(exc)` in `last_error`.
- **Symptom:** Stack trace with `/Users/chris.dare/Personal/SourceCode/arXMCP/...` paths leaks into the ingest-status response and potentially into logs at INFO.
- **Mitigation:** Apply the SAME `prepare_stderr_tail()` pipeline from `ingest_tracker.py:91-107` to any new `last_error` field — truncate to 1KB, redact via `_ABS_PATH_PREFIX_RE`, HTML-escape. Store only the high-level category string. Log the full error at DEBUG, never at INFO/WARN.

**FM-12: HF_HUB_OFFLINE=1 crashes the BGE-M3 progress shim**

- **Trigger:** Test suite runs with `HF_HUB_OFFLINE=1` (offline test discipline); the monkeypatch on `huggingface_hub.utils.tqdm` installs successfully but the download is never called.
- **Symptom:** If the shim patches the tqdm class but HuggingFace raises `OfflineModeIsEnabled` before calling tqdm, the shim simply never fires — no crash. But if the monkeypatch itself raises (e.g., the tqdm class is not importable in offline mode), the shim would crash.
- **Mitigation:** Guard the monkeypatch installation with `try/except ImportError`. Check `huggingface_hub.constants.HF_HUB_OFFLINE` before installing the shim. If `HF_HUB_OFFLINE` is truthy, skip shim installation entirely and log `DEBUG "BGE-M3 progress shim disabled (HF_HUB_OFFLINE=1)"`. The `IngestJob.bytes_done` / `bytes_total` stay at 0/0 in offline mode, which is correct since the model is already cached.

---

## Recommendation

**Extend `IngestTaskTracker` rather than creating a parallel `IngestJob` dict.** The existing subprocess-based tracker has the right GC-safety, 409-collision, and shutdown patterns. For m4, the gap is: (1) there is no in-process phase/bytes-progress tracking because the existing tracker runs a subprocess. **Solve this by adding an `IngestProgressStore` dataclass (keyed by slug) alongside `IngestTaskTracker`** — the ingest orchestrator writes phase + bytes to this store; the `GET /ingest/latest` endpoint reads from both the DB (terminal state) and the progress store (running state). This avoids rewriting the existing m9 ingest surface and preserves the subprocess isolation.

For the late-binding flip: use `asyncio.Event` (one-way, non-contended, no lock overhead on the hot MCP query path).

For the stub-check: implement at the orchestrator dispatch level in `server/tools.py`, not per-handler.

For `/readyz`: return **200** in bootstrap mode (with `"status": "bootstrap"` in the JSON body). The shim polls `/readyz` for liveness; returning 503 would cause the shim to give up before the operator has a chance to ingest. The structured body makes bootstrap vs. normal distinguishable without causing a 503 liveness failure.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one ambiguity (subprocess vs in-process for the new orchestrator) is resolved: extend the existing `IngestTaskTracker` pattern with a companion `IngestProgressStore` for in-flight phase/bytes visibility, keeping subprocess isolation for the heavy ingest work.

---

## External writes the implementation will require

None — this milestone is purely local.
