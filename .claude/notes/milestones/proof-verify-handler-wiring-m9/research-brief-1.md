# Research Brief — proof-verify-handler-wiring-m9

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-22T16:10:00Z

## In-codebase context

### m6 ingest entry point (`tools/notebook_ingest.py`)

**CLI invocation (verbatim from docstring):**
```
uv run python tools/notebook_ingest.py <slug>
```

**Entry function:** `run(slug: str) -> int` — a pure synchronous function. Comment
verbatim: `"""Pure function — returns exit code. Tests call this directly."""`

**Import-and-call directly?** YES for tests, but for the server it is dangerous: `run_bulk_ingest` (called by `run()`) is entirely synchronous — it contains a blocking `for n, paper_id in enumerate(work, start=1)` loop with no `await` points anywhere in `ingest/bulk_ingest.py`. Calling `run()` directly from `asyncio.create_task(...)` would block the event loop for the entire ingest duration. **The implementer MUST use `asyncio.to_thread(tools.notebook_ingest.run, slug)` inside the spawned task, not a bare `create_task` over the synchronous function.**

**Exit code contract:**
- `0` — ingest succeeded AND BM25 index was built (or both skipped idempotently)
- `1` — slug validation failed, ingest had any paper failure, or BM25 build raised
(Non-zero means partial or total failure; the summary `print` goes to stdout, failure detail to stderr.)

**Log path (verbatim):**
```python
log_path = ops_dir / "ingestion.log"   # ops_dir = nb_dir / "ops"
```
where `nb_dir = var/arxmcp/notebooks/<slug>/`. Full path:
`var/arxmcp/notebooks/<slug>/ops/ingestion.log`

Parser failures path: `var/arxmcp/notebooks/<slug>/ops/parser-failures.jsonl`

**Blocking vs async:** `run_bulk_ingest` is a SYNCHRONOUS blocking loop (confirmed: no `async def`, no `await`, no `asyncio` import in `bulk_ingest.py`). The `tools/notebook_ingest.py::run()` function calls it directly. The background task MUST wrap via `asyncio.to_thread`.

**stderr capture:** `run()` writes failure lines to `sys.stderr` via `print(..., file=sys.stderr)`. To capture stderr, m9 MUST spawn the ingest in a subprocess (`subprocess.Popen` or `asyncio.create_subprocess_exec`) rather than calling `run()` via `asyncio.to_thread`. The subprocess approach gives full stderr capture; `asyncio.to_thread` does not capture it. **Recommend subprocess spawning.**

### `NotebooksStore` schema bump

**Current `SCHEMA_VERSION: int = 1`** (verbatim from `server/notebooks_store.py:61`).

**Current migration pattern (verbatim):**
```python
if current_version < SCHEMA_VERSION:
    conn.execute("DROP TABLE IF EXISTS notebook_papers")
    conn.execute("DROP TABLE IF EXISTS notebooks")
    conn.execute("CREATE TABLE notebooks ...")
    conn.execute("CREATE TABLE notebook_papers ...")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
```

**CRITICAL gap:** the DROP-AND-RECREATE path wipes `notebooks` and `notebook_papers` rows. The `cache_sqlite.py` Tier1Store uses the SAME destructive pattern. For m9, this would destroy live notebook metadata every time the server restarts against a version-1 DB.

**Recommendation: ADDITIVE migration, not destructive.** Bump `SCHEMA_VERSION` to `2` and add a branch in the `_open_sync` migration block:

```python
if current_version < 1:
    # (existing full create for version 0 -> 1)
    ...
    conn.execute(f"PRAGMA user_version = 1")
if current_version < 2:
    # Additive: add notebook_ingest_runs WITHOUT dropping existing tables.
    conn.execute("CREATE TABLE IF NOT EXISTS notebook_ingest_runs (...)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_slug ON notebook_ingest_runs(slug, id DESC)")
    conn.execute("PRAGMA user_version = 2")
```

**Recommended schema for `notebook_ingest_runs`:**
```sql
CREATE TABLE notebook_ingest_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT NOT NULL,
    status       TEXT NOT NULL,    -- 'running' | 'success' | 'failed'
    started_at   TEXT NOT NULL,    -- ISO-8601 UTC
    finished_at  TEXT,             -- NULL while running
    exit_code    INTEGER,          -- NULL while running
    stderr_tail  TEXT,             -- last 1 KB of stderr on failure
    FOREIGN KEY (slug) REFERENCES notebooks(slug) ON DELETE CASCADE
);
CREATE INDEX idx_runs_slug ON notebook_ingest_runs(slug, id DESC);
```

The FK cascade means deleting a notebook also cleans its run history — correct behavior.

The deviation from the existing DROP-AND-RECREATE pattern is intentional and MUST be documented in inline comments: `# m9 DEVIATION: additive migration; do NOT drop existing tables here`.

### Background task lifecycle

The server uses `asyncio.get_running_loop().create_task(...)` in `server/resources.py` (singleflight). The same pattern applies here, but m9 tasks are fire-and-forget (not awaited by the caller).

**The implementer MUST NOT use FastAPI `BackgroundTasks`** for the ingest trigger. FastAPI `BackgroundTasks` are request-scoped — they fire after the response returns, which is correct, but the lifecycle is NOT tracked in `app.state` and cannot be cancelled at shutdown. For a long-running ingest (minutes), a fire-and-forget `asyncio.create_task` stored in `app.state` is correct.

**Recommended `IngestTaskTracker` class** (to live in `server/ingest_tracker.py`):

- `start_ingest(slug: str, store: NotebooksStore) -> int` — inserts a `running` row, spawns `asyncio.create_task(_run_ingest_subprocess(slug, store, run_id))`, stores the `Future` in `_tasks: dict[str, asyncio.Task]` keyed by slug. Returns `run_id`.
- `is_running(slug: str) -> bool` — checks `_tasks` dict for a non-done task.
- `cleanup_finished_tasks()` — removes done tasks from `_tasks` (call from a periodic background coroutine or lazily in `is_running`).
- `shutdown()` — cancels all in-flight tasks and awaits them with a short timeout (e.g. 5s).

The tracker MUST be attached to `app.state.ingest_tracker` in the lifespan, closed in the `finally` block alongside `notebooks_store.close()`.

**Subprocess invocation inside the tracked task:**
```python
proc = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "tools.notebook_ingest", slug,
    stderr=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
)
_, stderr_bytes = await proc.communicate()
exit_code = proc.returncode
```

This gives full stderr capture and a clean exit code, matching the AC exactly.

### Concurrency control (409 check)

**Recommendation: in-memory dict as primary source of truth; DB as fallback.**

The 409 check fires in two steps:
1. `ingest_tracker.is_running(slug)` — O(1) dict lookup on live `asyncio.Task` objects. If `True`, return HTTP 409 immediately.
2. If the server restarted mid-ingest, the in-memory dict is empty but the DB row may show `status='running'`. Add a DB fallback: `SELECT 1 FROM notebook_ingest_runs WHERE slug=? AND status='running' LIMIT 1`. If found, return HTTP 409.

The DB fallback handles crash-restart scenarios correctly. The in-memory dict is authoritative for the running process. DB rows left `status='running'` after a restart should be marked `status='failed'` with `stderr_tail='server restarted'` at startup (optional cleanup in `IngestTaskTracker.startup(store)`).

### stderr capture without exposing absolute paths

AC #2: "surface the last 1 KB of stderr in the UI without exposing absolute paths beyond `var/arxmcp/`."

The subprocess stderr will contain paths like `/Users/chris.dare/Personal/SourceCode/arXMCP/var/arxmcp/notebooks/<slug>/ops/parser-failures.jsonl`.

**Recommend a `_redact_paths(text: str, repo_root: str) -> str` helper** in `server/ingest_tracker.py`:
```python
import re as _re
_ABS_PREFIX_RE = _re.compile(r"[/\\][\w/\\.-]+(var/arxmcp/)")
def _redact_paths(text: str) -> str:
    # Replace any absolute path prefix up to var/arxmcp/ with just var/arxmcp/
    return _ABS_PREFIX_RE.sub(r"var/arxmcp/", text)
```

The `repo_root` prefix is not stable across deployments so use the regex approach rather than a literal string replacement. Strip to the last 1024 bytes of stderr BEFORE redacting (avoid regex over multi-MB output).

### htmx polling endpoint shape

`GET /ui/api/notebooks/{slug}/ingest/latest` returns an **HTML fragment** (same pattern as the m8 upload endpoint which returns `HTMLResponse`). The endpoint is exempt from `BodySizeCapMiddleware` via the `/ui/static` exemption? No — `/ui/api/` is NOT exempt. The fragment must stay under 256 KB (trivially true for a status row). The `SecFetchSiteMiddleware` exempts `/ui` prefix (verbatim from `main.py:488`): `exempt_prefixes=("/ui",)` — so the polling endpoint is already exempt from the Sec-Fetch-Site check.

**Fragment shape (running):**
```html
<div id="ingest-status" data-status="running">
  Status: running · Started 2026-05-22T16:00:00+00:00 · Run ID 42
</div>
```

**Fragment shape (failed):**
```html
<div id="ingest-status" data-status="failed">
  Status: failed · Exit 1 · Last stderr:
  <pre>...redacted stderr tail...</pre>
</div>
```

**Fragment shape (no runs):**
```html
<div id="ingest-status" data-status="none">No ingest runs yet.</div>
```

### Polling stop condition

**Recommend using `data-status` attribute inspection via `hx-on::htmx:after-swap`** in the notebook_detail.html template. After each swap, inspect the swapped element's `data-status`; if it is `success` or `failed`, remove the `hx-trigger` attribute to stop polling:

```html
<div id="ingest-status"
     hx-get="/ui/api/notebooks/{{ notebook.slug }}/ingest/latest"
     hx-trigger="every 2s"
     hx-target="#ingest-status"
     hx-swap="outerHTML"
     hx-on::htmx:after-swap="
       const s = document.getElementById('ingest-status');
       if (s && (s.dataset.status === 'success' || s.dataset.status === 'failed')) {
         htmx.off(s, 'htmx:trigger');
         s.removeAttribute('hx-trigger');
         htmx.process(s);
       }
     ">
  No ingest runs yet.
</div>
```

Note: `hx-swap="outerHTML"` replaces the entire `<div>` including the `hx-trigger` attribute, so the returned fragment from the server for terminal states should NOT include `hx-trigger="every 2s"` — the server controls polling stop by omitting the attribute from terminal-state fragments.

### AC #4 scope assertion test

**Recommend `tests/test_m9_scope_invariants.py::test_no_preview_or_iframe_in_frontend`:**
```python
import subprocess, sys
def test_no_preview_or_iframe_in_frontend():
    result = subprocess.run(
        ["grep", "-ri", "iframe|preview", "frontend/"],
        capture_output=True, text=True,
    )
    assert result.stdout == "", f"Found preview/iframe references:\n{result.stdout}"
```

This test is a static grep — it runs without the server and fails fast if a future template accidentally adds the out-of-scope feature.

## Prior decisions and lessons

- **m7 established the `NotebooksStore.open()` + lifespan pattern** (verbatim from `main.py:334`): `app.state.notebooks_store = await NotebooksStore.open(config.notebooks_db_path)`. The ingest tracker follows the same `app.state` attach + lifespan-finally close pattern.
- **m8 established htmx HTML fragment returns** via `HTMLResponse` in `upload_paper`. The polling endpoint should return `HTMLResponse` with `content=...` (not JSON).
- **`SecFetchSiteMiddleware` already exempts `/ui` prefix** (main.py line 488) — the new ingest endpoints at `/ui/api/notebooks/{slug}/ingest` and `/ui/api/notebooks/{slug}/ingest/latest` are automatically included in this exemption.
- **No `iframe` or `preview` in frontend/ currently** — confirmed by grep returning empty output.
- **`SCHEMA_VERSION` is `1` today** (notebooks_store.py:61). The additive bump to `2` is the minimum-disruption path.
- **`BodySizeCapMiddleware` uses DROP-AND-RECREATE** — do NOT replicate this for the m9 table addition; it would wipe notebook data.

## External sources

No MCP protocol changes — m9 adds REST/htmx endpoints only (not MCP tool additions). No tool schema re-pinning required. No prompt-caching changes.

The MCP spec and Anthropic prompt-caching docs are not load-bearing for this milestone. Not fetched — stated explicitly per brief format requirements.

## Recommendation

**Spawn the ingest as `asyncio.create_subprocess_exec(sys.executable, "-m", "tools.notebook_ingest", slug, stderr=PIPE)` inside a fire-and-forget `asyncio.create_task`, managed by an `IngestTaskTracker` attached to `app.state`.**

Do NOT call `tools.notebook_ingest.run()` via `asyncio.to_thread` — it does not capture stderr. Do NOT use FastAPI `BackgroundTasks` — they are not cancellable at shutdown and not trackable in `app.state`.

Use additive migration (not DROP-AND-RECREATE) for SCHEMA_VERSION 1→2 with `notebook_ingest_runs`. Use in-memory dict as the primary 409 check with DB fallback for post-restart correctness. Redact absolute paths in `_redact_paths()` before storing `stderr_tail`. Return HTML fragments from both the POST and GET/polling endpoints (matching the m8 upload pattern).

## Open questions

1. **`tools.notebook_ingest` as a module (`-m tools.notebook_ingest`):** the `tools/` directory has an `__init__.py` so it is a package. The implementer should verify `python -m tools.notebook_ingest` is the correct invocation form (vs `python tools/notebook_ingest.py`). If the module-form doesn't work, use `[sys.executable, str(Path(__file__).parents[2] / "tools" / "notebook_ingest.py"), slug]` with the explicit file path.

2. **`IngestTaskTracker.startup` — stale `running` rows:** should the tracker mark stale `running` rows `failed` at server startup? Recommend yes (with `stderr_tail='server restarted'`), but the implementer must decide the SQL update and whether this fires synchronously before `yield` or asynchronously.

3. **Polling stop via `hx-swap="outerHTML"` vs `hx-swap="innerHTML"`:** the brief says `hx-target="#ingest-status" hx-swap="innerHTML"`, but for the stop-condition pattern to work (removing `hx-trigger` from the polling element), `hx-swap="outerHTML"` is cleaner (replaces the whole div including its attributes). The implementer should pick one and be consistent between the template and the test.

## External writes the implementation will require

None — this milestone is purely local. The new REST endpoints, SQLite table, `IngestTaskTracker`, template additions, and tests all land in the local repo. No `git push`, no `gh` mutations, no infra changes.
