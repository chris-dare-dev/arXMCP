# Research Brief — proof-verify-handler-wiring-m9

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T16:00:00Z

## In-codebase context

### Dependencies confirmed shipped

- **m6** (`phase: complete`, commit `c6229fa`): `tools/notebook_ingest.py` is the ingest entry point. The `run()` function is the callable; it calls `run_bulk_ingest(...)` which is **synchronous** (`def`, not `async def` — confirmed at `ingest/bulk_ingest.py:338`). This is the critical architectural constraint for m9.
- **m7** (`phase: complete`, commit `18dcee8`): `server/notebooks_store.py` exists; uses `asyncio.to_thread` for all DB I/O. The `NotebooksStore` is opened in `lifespan` and stored at `app.state.notebooks_store`. The `/ui/*` prefix is already exempted from `SecFetchSiteMiddleware` via `exempt_prefixes=("/ui",)` at `server/main.py:488`.
- **m8** (`phase: complete`, commit `dece742`): htmx 2.0.10 vendored. The deferred finding F3 ("concurrent-upload tmp-write race") is tracked "alongside m9 background-worker concurrency design."

### Slug validation — path traversal defense already in place

`tools._notebook_common.validate_slug` is imported and called in `server/routes/notebooks.py` at every handler that accepts a slug path parameter (lines 240, 327, 361, 393, 451, 547). The regex is `^[a-z][a-z0-9-]{2,30}$` (confirmed at `tools/_notebook_common.py:36`). The new ingest trigger handler MUST import and call `validate_slug(slug)` in the same pattern — this is already the established precedent.

### `notebook_ingest_runs` table — does NOT exist yet

Grep across the entire codebase returns zero hits for `notebook_ingest_runs`, `ingest_runs`, or `IngestRun`. This table must be created from scratch in m9. It belongs in the same SQLite file as `NotebooksStore` (per m7's single-DB-file design) OR as a new table in `notebooks_store.py`.

### Event loop / task patterns in codebase

`asyncio.to_thread` is the dominant pattern for offloading sync work: `server/notebooks_store.py`, `server/cache_sqlite.py`, `server/theorem_names_store.py`, `server/graph_queries.py` all use it. `asyncio.create_task` appears at `server/resources.py:182` (singleflight pattern). No `app.state.ingest_tasks` or task tracker exists.

### Rate limiting — hourly cap applies to MCP tools only

The `SessionCapMiddleware` (with `check_hourly_rate_limit`) applies exclusively to `/mcp` tool calls. The new `/ui/api/notebooks/{slug}/ingest` endpoint is NOT under `/mcp` and is NOT subject to the 1000/hour MCP session cap. The 2s polling loop at 30 req/min hits only the UI routes, which have no rate limiting today. This is informational, not a bug.

### lifespan shutdown context

`server/main.py:351`: `await asyncio.wait_for(resources.shutdown(), timeout=30.0)`. Any in-flight background ingest task at shutdown is NOT awaited — cancellation is not called explicitly. An `asyncio.Task` that is not awaited or cancelled in `finally` will be abandoned mid-execution. This is a known gap that m9 must address.

## Prior decisions and lessons

- **m7 deferred F3**: "concurrent-upload tmp-write race; tracked alongside m9 background-worker concurrency design." The implementer must close this finding or explicitly re-defer it with justification.
- **m8 deferred F8**: "Python string concat vs Jinja2 partial; html.escape() protection correct." The stderr tail display (m9 AC#2) must use `html.escape()` for the same reason.
- **Slug path traversal** is the established Threat 1 concern for all notebook routes; `validate_slug` is the defense.
- `asyncio.to_thread` is the project's canonical pattern for wrapping synchronous work in async handlers — NOT bare `asyncio.create_task(sync_fn())` which would block the event loop.

## External sources

### Python asyncio docs (Python 3.11+)

From `https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task`:

> **Important**: Save a reference to the result of this function, to avoid a task disappearing mid-execution. The event loop only keeps weak references to tasks. A task that isn't referenced elsewhere may get garbage collected at any time, even before it's done.

Recommended fire-and-forget pattern (Python docs verbatim):

```python
background_tasks = set()
task = asyncio.create_task(some_coro())
background_tasks.add(task)
task.add_done_callback(background_tasks.discard)
```

On `task.cancel()`:

> The method arranges for a CancelledError exception to be thrown into the wrapped coroutine on the next cycle of the event loop. ... unlike Future.cancel(), Task.cancel() does not guarantee that the Task will be cancelled.

**Implication for ingest**: `run_bulk_ingest` is synchronous and runs inside `asyncio.to_thread`. When the thread is executing, `task.cancel()` delivers `CancelledError` to the async wrapper, but the thread itself continues until the current paper completes. The embedder HuggingFace cache may be left in a partial state. Cancellation is best-effort only.

### htmx 2.x polling stop mechanism

From `https://htmx.org/docs/#polling`:

`hx-trigger="every 2s"` polls indefinitely. The canonical stop mechanism: **"If you want to stop polling from a server response you can respond with the HTTP response code `286` and the element will cancel the polling."**

Returning HTTP `286` from `/ui/api/notebooks/{slug}/ingest/latest` when the run is in a terminal state (`success` or `failed`) stops client polling without requiring any JS. This is cleaner than removing `hx-trigger` client-side or using `HX-Retarget`. **Recommendation: use HTTP 286 for terminal states.**

### FastAPI BackgroundTasks vs asyncio.create_task

From `https://fastapi.tiangolo.com/tutorial/background-tasks/`:

`BackgroundTasks` runs after the response returns but within the same request lifecycle span. FastAPI docs explicitly state: "If you need to perform heavy background computation and you don't necessarily need it to be run by the same process, you might benefit from using other bigger tools like Celery."

`BackgroundTasks` is designed for light post-response tasks (emails, small logs). For ingest (30s–hours, CPU-bound BGE-M3 embedding), `BackgroundTasks` is insufficient — the task must outlive the request span. `asyncio.create_task` with a tracker stored on `app.state` is the correct shape for long-running work that must survive across requests.

## Failure-mode analysis

**FM-1 (Threat 4 — resource exhaustion across notebooks):** The 409 collision check is per-notebook (`status='running'` for slug X). A client can fire 100 ingests across 100 different notebooks. Mitigation: a global concurrent ingest cap (e.g. 1 active ingest at a time across the daemon, not just 1 per notebook). Implement as a module-level `asyncio.Semaphore(1)` or a count field on `app.state`.

**FM-2 (Threat 1 — path traversal via slug):** The slug arrives via path parameter. `validate_slug` from `tools._notebook_common` is already called in all existing `notebooks.py` handlers. The new ingest handler MUST call it too — the established pattern is at `server/routes/notebooks.py:327`. If skipped, a slug like `../../../etc` could reach `notebook_dir()`.

**FM-3 (Threat 2 — stderr as prompt injection vector):** If `run_bulk_ingest` or LaTeXML emits `<retrieved_chunk>` literal text in a parser failure, the stderr tail captured in the UI could contain delimiter-class content. AC#2 says show "the last 1 KB of stderr in the UI." This text MUST be (a) `html.escape()`-ed before storage and (b) the delimiter contract applies — do not embed raw paper content in the UI response. Precedent: m8 F8 used `html.escape()` for paper row HTML.

**FM-4 (path leakage in stderr):** `run_bulk_ingest` logs paths like `/Users/chris.dare/Personal/SourceCode/arXMCP/var/arxmcp/notebooks/slug/ops/ingestion.log`. AC#2 says "without exposing absolute paths beyond `var/arxmcp/`." The stored stderr tail must be scrubbed with a regex: `re.sub(r'/[^\s]*/var/arxmcp/', 'var/arxmcp/', stderr_tail)` before writing to the DB row. The repo root prefix varies per operator install; the safe scrub replaces everything up to and including `var/arxmcp/`.

**FM-5 (daemon restart mid-ingest — orphaned `running` row):** The `done_callback` that marks the row `success` or `failed` fires asynchronously. If the daemon shuts down between task completion and callback execution, the row stays `status='running'` forever. **Required**: add a startup recovery step in `lifespan` (after `NotebooksStore.open`) that scans for rows with `status='running'` older than 1 hour and marks them `failed` with `"daemon restarted mid-ingest"` as the failure message.

**FM-6 (BGE-M3 pins the event loop — CRITICAL design issue):** `run_bulk_ingest` is synchronous and CPU-bound. The brief says "spawns... as a background `asyncio.create_task`." Running `asyncio.create_task(sync_fn())` is a TypeError (sync_fn is not a coroutine). The correct shell is:

```python
task = asyncio.create_task(
    asyncio.to_thread(tools.notebook_ingest.run, slug)
)
```

`asyncio.to_thread` submits to the default thread pool executor; the event loop remains unblocked during ingest. Do NOT use `asyncio.create_task(coroutine_that_calls_sync_fn())` where the coroutine body calls `run_bulk_ingest` directly without `to_thread` — that pins the loop for the entire ingest duration.

**FM-7 (404 between trigger and row commit):** If the handler creates the DB row AFTER spawning the task and returning the response, the first 2s poll fires before the row exists and returns 404. The row MUST be inserted BEFORE `create_task` returns the 202 response. Sequence: (1) validate, (2) 409-check, (3) `INSERT INTO notebook_ingest_runs`, (4) `create_task(asyncio.to_thread(run, slug))`, (5) return 202.

**FM-8 (subprocess isolation alternative):** An alternative to `asyncio.to_thread` is `asyncio.create_subprocess_exec(sys.executable, "tools/notebook_ingest.py", slug)`. This gives true process isolation: an ingest crash cannot corrupt the daemon's BGE-M3 model state or LanceDB connection pool. The trade-off is a ~30s cold-start penalty to reload BGE-M3 weights from disk (the daemon's already-loaded model is not shared across process boundary). Given this is a single-user local tool, the **recommendation is `asyncio.to_thread` (in-process)** for speed — the daemon serves only one operator, so a crash-on-ingest causing a daemon restart is acceptable and rare.

## Recommendation

**Use `asyncio.create_task(asyncio.to_thread(tools.notebook_ingest.run, slug))` as the ingest execution shell.** Store the task reference in a module-level `dict[str, asyncio.Task]` on `app.state` (key = slug) to prevent GC. Add a `done_callback` that (a) updates the DB row to `success`/`failed`, (b) pops the task from the tracker. Use **HTTP 286** as the polling-stop signal for terminal run states — it is the htmx-documented canonical mechanism and requires zero client-side JS. Create the DB row BEFORE spawning the task. Add startup recovery in `lifespan` to mark orphaned `running` rows as `failed`. Add a global concurrent ingest semaphore (1 across all slugs) to prevent FM-1 resource exhaustion.

**Proposed `IngestTaskTracker` sketch (not code — shape only):**

```
class IngestTaskTracker:
    _tasks: dict[str, asyncio.Task]   # slug -> Task
    _lock: asyncio.Lock               # serialize .start() / .done() calls
    _semaphore: asyncio.Semaphore(1)  # global cap: 1 concurrent ingest

    async def start(slug, db_row_id) -> asyncio.Task | None:
        # Returns None if semaphore is already held (caller → HTTP 409)
        ...
    def on_done(slug, db_row_id, store):
        # done_callback: runs in any thread
        # schedules asyncio.ensure_future(store.update_run(db_row_id, ...))
        ...
```

**Proposed polling endpoint fragment shape:**

```html
<!-- terminal state: server returns HTTP 286, htmx stops polling -->
<div id="ingest-status">
  <span class="status-failed">Failed</span>
  <pre>{{ last_1kb_stderr_html_escaped }}</pre>
</div>

<!-- running state: server returns HTTP 200 with hx-trigger retained -->
<div id="ingest-status"
     hx-get="/ui/api/notebooks/{{ slug }}/ingest/latest"
     hx-trigger="every 2s"
     hx-swap="outerHTML">
  <span class="status-running">Running...</span>
</div>
```

## Open questions

1. **Where does `notebook_ingest_runs` live?** Option A: new table added to `NotebooksStore` (same SQLite file, same `asyncio.Lock` discipline). Option B: separate SQLite file alongside notebooks.db. Recommendation: Option A — `notebooks_store.py` already handles the `asyncio.to_thread` wrapper; add the three new methods (`insert_run`, `update_run`, `get_latest_run`) there.

2. **Global semaphore vs per-notebook 409?** The brief mandates per-notebook 409 (one in-flight per notebook). The FM-1 global cap (one total) is a recommendation not in the brief. The implementer must decide whether to add it or document the gap.

3. **Lifespan `finally` — should in-flight ingest be awaited or cancelled?** The current lifespan has a 30s drain for resources but nothing for ingest tasks. Awaiting could block shutdown indefinitely (ingest takes 30s–hours). Recommendation: call `task.cancel()` on all running tasks in `finally` (best-effort; the thread continues its current paper), then `asyncio.gather(*tasks, return_exceptions=True)` with a 5s timeout.

## External writes the implementation will require

None — this milestone is purely local. All changes are:
- New SQLite table (notebook_ingest_runs) in the existing notebooks.db file
- New FastAPI route handlers under `/ui/api/notebooks/{slug}/ingest`
- New Jinja2 template fragment for the polling status widget
- New tests under `tests/`

No git push, no GitHub issue creation, no infra mutation, no third-party API call.
