# Research Synthesis — proof-verify-handler-wiring-m9

**Orchestrator merge of:** `research-brief-1.md`, `research-brief-2.md`
**Generated:** 2026-05-22T17:00:00Z
**Mode:** standard (2× Sonnet in parallel)

## TL;DR for the implementer

Spawn the ingest as a **subprocess** via `asyncio.create_subprocess_exec(
sys.executable, "-m", "tools.notebook_ingest", slug, stderr=PIPE)` inside
a fire-and-forget `asyncio.create_task` managed by a NEW
`IngestTaskTracker` attached to `app.state.ingest_tracker`. Add the
`notebook_ingest_runs` table to `NotebooksStore` via an **additive**
SCHEMA_VERSION 1→2 migration (NOT the existing destructive pattern;
that would wipe live notebook data). Two new endpoints:
`POST /ui/api/notebooks/{slug}/ingest` (creates the DB row BEFORE
spawning the task; returns 202 with the run_id; 409 on collision)
and `GET /ui/api/notebooks/{slug}/ingest/latest` (returns an HTML
fragment for htmx polling; returns **HTTP 286** for terminal-state
runs to stop client polling — the htmx-documented canonical
mechanism). Redact absolute paths from stderr via regex; HTML-escape
the captured stderr tail before storage. Add startup-recovery in
the lifespan to mark orphaned `running` rows as `failed`.

Estimated implementation surface: ~700 LOC across 7 files
(notebooks_store extension, NEW ingest_tracker, notebooks.py 2 new
handlers + redaction helper, ui.py / template polling shell,
main.py wiring, 2 new test files). Above the inline threshold but
every pattern is established (NotebooksStore, app.state lifecycle,
asyncio.create_task with tracker dict, htmx polling). **Inline
path.**

## Resolved disagreements

### Disagreement 1 — Subprocess vs in-process ingest

**R-1:** `asyncio.create_subprocess_exec(sys.executable, "-m",
"tools.notebook_ingest", slug, stderr=PIPE)` — subprocess
isolation, native stderr capture via `proc.communicate()`.

**R-2:** `asyncio.create_task(asyncio.to_thread(tools.notebook_ingest.run, slug))`
— in-process, re-uses the daemon's BGE-M3 cache (avoids ~30s
cold-start), simpler.

**Synthesis: R-1 wins (subprocess).** Three reasons:

1. **Stderr capture is the AC explicit requirement.** AC #2 says
   "surface the last 1 KB of stderr". The subprocess approach
   captures stderr via `asyncio.subprocess.PIPE` natively; the
   in-process approach would require `contextlib.redirect_stderr`
   on the GLOBAL `sys.stderr` (because `tools/notebook_ingest.py`
   uses `print(..., file=sys.stderr)`), which is dangerous to
   manipulate from a background thread that runs concurrently
   with other server code paths.
2. **Process isolation is the right default for long-running
   work.** An ingest crash (BGE-M3 OOM, LaTeXML segfault, LanceDB
   write fault) MUST not crash the daemon. The MCP server has
   uptime obligations to in-flight `/mcp` callers; an isolated
   subprocess preserves that contract.
3. **The cold-start cost (~30s BGE-M3 reload) is amortized over
   minutes-to-hours of ingest.** A 30s overhead is rounding error
   on a 30-minute ingest. The daemon's own BGE-M3 stays warm for
   concurrent MCP `search_papers` calls — no resource contention.

R-2's concern about subprocess overhead is real but outweighed by
the AC + isolation arguments. The implementation summary should
document the trade-off explicitly.

### Disagreement 2 — Polling stop mechanism

**R-1:** Client-side `hx-on::htmx:after-swap` JS that inspects
`data-status` and removes `hx-trigger` if terminal.

**R-2:** Server returns **HTTP 286** when the run is in a terminal
state (`success` or `failed`). htmx's documented canonical
mechanism: "If you want to stop polling from a server response you
can respond with the HTTP response code `286` and the element will
cancel the polling."

**Synthesis: R-2 wins (HTTP 286).** htmx-documented, zero
client-side JS, idempotent (a refreshed page that polls again
after a terminal run still gets the 286 and stops immediately).
R-1's JS approach works but requires more template surface area
and is brittle if a future `hx-swap` value changes. The terminal-
state fragment is still useful for content; only the status code
gates polling.

### Disagreement 3 — Polling stop with `hx-swap="outerHTML"` vs `innerHTML`

R-1 raised this open question. Synthesis D2 makes it moot — with
HTTP 286 stopping the polling, the swap value doesn't affect the
stop behavior. Pick `hx-swap="outerHTML"` so the entire status
div is replaced (including any state-specific CSS classes); the
implementer can ship either consistently.

## Strong agreement (cited verbatim from both briefs)

These were independently reached by both researchers — no merge
needed.

### FM-6 (CRITICAL execution-shell pitfall)

Both briefs flagged this as the highest-risk implementation
mistake: **`asyncio.create_task(sync_function())` does NOT
actually run async** — it raises TypeError (sync_function returns
a value, not a coroutine), OR if wrapped as `create_task(async
wrapper that calls sync directly)`, the wrapper pins the event
loop for the entire ingest duration, blocking ALL other requests
to the daemon. The correct shell:

```python
task = asyncio.create_task(
    _run_ingest_subprocess(slug, store, run_id)
)
```
where `_run_ingest_subprocess` is an async function that awaits
`asyncio.create_subprocess_exec(...)`.

### Additive SCHEMA_VERSION migration (NOT destructive)

Both briefs flagged the existing DROP-AND-RECREATE pattern in
`NotebooksStore._open_sync` as DATA-LOSS on schema bump. The m9
implementer MUST add an additive branch:

```python
current_version = conn.execute("PRAGMA user_version").fetchone()[0]
if current_version < 1:
    # (existing v0→v1 destructive create — runs only on fresh DBs)
    ...
    conn.execute("PRAGMA user_version = 1")
if current_version < 2:
    # m9 additive migration: do NOT drop existing tables.
    conn.execute("CREATE TABLE IF NOT EXISTS notebook_ingest_runs (...)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_slug ON notebook_ingest_runs(slug, id DESC)")
    conn.execute("PRAGMA user_version = 2")
```

Explicit `# m9 DEVIATION` comment naming the rationale. The
existing Tier1Store's destructive pattern stays as-is (cache loss
is a miss, not a correctness failure); the NotebooksStore
deviates because notebook metadata MUST survive schema bumps.

### Schema for `notebook_ingest_runs`

```sql
CREATE TABLE notebook_ingest_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT NOT NULL,
    status       TEXT NOT NULL,    -- 'running' | 'success' | 'failed'
    started_at   TEXT NOT NULL,    -- ISO-8601 UTC
    finished_at  TEXT,             -- NULL while running
    exit_code    INTEGER,          -- NULL while running
    stderr_tail  TEXT,             -- last 1 KB of redacted stderr on failure
    FOREIGN KEY (slug) REFERENCES notebooks(slug) ON DELETE CASCADE
);
CREATE INDEX idx_runs_slug ON notebook_ingest_runs(slug, id DESC);
```

The FK cascade means deleting a notebook also cleans its run
history — correct behavior matching the m7 cascade discipline.

### Row-before-task ordering (FM-7 closure)

Sequence inside `POST /ui/api/notebooks/{slug}/ingest`:

1. `validate_slug(slug)`.
2. 409-check: in-memory dict + DB-fallback for cross-restart safety.
3. `await store.insert_ingest_run(slug, status="running", started_at=_now_iso())` — returns `run_id`.
4. `asyncio.create_task(_run_ingest_subprocess(slug, store, run_id))` — fire-and-forget; the task ref is stored in the tracker's `_tasks` dict to prevent GC.
5. Return HTTP 202 Accepted with `{"run_id": run_id}` JSON (or HTML fragment for htmx swap; both researchers diverged here — pick HTML fragment to match the m8 upload pattern).

Without this ordering the first 2s poll would 404 (no row yet).

### Concurrency control (FM-1 + per-notebook 409)

Two-layer defense:
- **Per-notebook (mandatory, AC #3):** `IngestTaskTracker.is_running(slug)`
  is O(1) dict lookup on live `asyncio.Task` objects.
- **Global semaphore (recommended; not in AC):** `asyncio.Semaphore(1)`
  on `IngestTaskTracker._global_cap` so the entire daemon runs
  at-most-one ingest at a time. Prevents the "100 notebooks ×
  100 concurrent subprocesses" resource-exhaustion path
  (R-2 FM-1).

**Synthesis decision: ship both.** The per-notebook check is the
brief's AC. The global semaphore is one extra line of defense
and matches the m8 upload-cap discipline (defense-in-depth even
when the immediate threat is narrow).

### Startup recovery for orphaned `running` rows (FM-5)

If the daemon dies mid-ingest, the `done_callback` never fires
and the DB row stays `status='running'` forever. The lifespan
must mark stale rows `failed` at startup:

```python
async def recover_orphaned_runs(store: NotebooksStore) -> int:
    """Mark `running` rows older than 1 hour as `failed` —
    they cannot still be running because we just started."""
    return await store.mark_orphans_failed(
        cutoff=_now_iso_minus(hours=1),
        message="server restarted mid-ingest",
    )
```

Called from the lifespan AFTER `NotebooksStore.open` AND BEFORE
the new `IngestTaskTracker` is initialized. The 1-hour cutoff is
defensive — any actually-running ingest would have completed
within that window.

### Path redaction (FM-4)

```python
import re
_ABS_PATH_PREFIX_RE: re.Pattern[bytes] = re.compile(
    rb"[/\\][\w/\\.-]*?var/arxmcp/"
)
def _redact_paths(stderr_bytes: bytes) -> bytes:
    """Replace any absolute path prefix up to ``var/arxmcp/``
    with the relative form. Bytes-domain so it works whether the
    subprocess emits UTF-8 or punted-to-Latin-1 output."""
    return _ABS_PATH_PREFIX_RE.sub(b"var/arxmcp/", stderr_bytes)
```

Truncate to the last 1024 bytes BEFORE redacting (the regex
should not scan multi-MB stderr). The truncation + redaction +
HTML-escape pipeline:

```python
stderr_tail_raw = stderr_bytes[-1024:]
stderr_tail_redacted = _redact_paths(stderr_tail_raw)
stderr_tail_text = stderr_tail_redacted.decode("utf-8", errors="replace")
stderr_tail_html_safe = html.escape(stderr_tail_text)
```

The HTML escape closes FM-3 (Threat 2 — prompt-injection via
delimiter literals in paper content).

### Polling endpoint fragment shape

```html
<!-- HTTP 200, running (htmx keeps polling): -->
<div id="ingest-status"
     data-status="running"
     hx-get="/ui/api/notebooks/{{ slug }}/ingest/latest"
     hx-trigger="every 2s"
     hx-swap="outerHTML">
  Status: running · Started {{ started_at }} · Run #{{ run_id }}
</div>

<!-- HTTP 286, success (htmx stops polling): -->
<div id="ingest-status" data-status="success">
  Status: success · Finished {{ finished_at }} · Run #{{ run_id }}
</div>

<!-- HTTP 286, failed (htmx stops polling): -->
<div id="ingest-status" data-status="failed">
  Status: failed · Exit {{ exit_code }} · Run #{{ run_id }}
  <pre>{{ stderr_tail_html_safe }}</pre>
</div>

<!-- HTTP 200, no runs yet: -->
<div id="ingest-status" data-status="none">No ingest runs yet.</div>
```

The terminal-state fragments do NOT include `hx-trigger` (defense-
in-depth even though HTTP 286 already stops polling). The
"no runs yet" state polls because a fresh trigger might land.

### AC #4 scope assertion test

```python
def test_no_preview_or_iframe_in_frontend(tmp_path):
    """m9 AC #4: paper preview is out of scope (deferred to m10).
    A grep over frontend/ for 'iframe' or 'preview' must return
    empty — defends against an accidental m10 leak into m9."""
    import subprocess
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["grep", "-rEi", "iframe|preview",
         str(repo_root / "frontend")],
        capture_output=True, text=True,
    )
    assert result.stdout == "", (
        f"Found preview/iframe references in frontend/ "
        f"(AC #4 violation):\n{result.stdout}"
    )
```

In `tests/test_m9_scope_invariants.py`. Runs as a static check;
no server needed.

## Load-bearing facts the implementer needs

### `tools/notebook_ingest.py` invocation form

From R-1: `python -m tools.notebook_ingest <slug>` is the module
form (the `tools/` directory has `__init__.py`). The implementer
should verify by running:

```bash
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m tools.notebook_ingest --help 2>&1 | head -5
```

If the module form works, use `[sys.executable, "-m", "tools.notebook_ingest", slug]`.
If it doesn't, fall back to `[sys.executable, str(Path(__file__).parents[2] / "tools" / "notebook_ingest.py"), slug]`.

### `tools/notebook_ingest.py::run()` exit-code contract

- `0` — ingest succeeded AND BM25 index built (or both no-op-idempotent)
- `1` — slug validation failed, any paper failure, OR BM25 build raised
- Non-zero = partial or total failure

m9 stores the exit code on the run row; surfaces it in the failed-
state fragment.

### `validate_slug` is the path-traversal defense (FM-2)

```python
from tools._notebook_common import validate_slug, NotebookError
try:
    validate_slug(slug)
except NotebookError as e:
    raise HTTPException(status_code=422, detail=str(e)) from e
```

Pattern at `server/routes/notebooks.py:240,327,361,393,451,547`
(precedent in 6 existing handlers).

### m7 SecFetchSite carve-out already covers the new endpoints

`/ui/api/notebooks/{slug}/ingest` and
`/ui/api/notebooks/{slug}/ingest/latest` are under `/ui/*` which
is in `exempt_prefixes=("/ui",)` (post-m7 rect F1 it's relaxed to
`{none, same-origin}`). No new middleware change needed for m9.

## Failure modes the implementer must inoculate against

Consolidated from both researchers' catalogs:

1. **FM-1 — Resource exhaustion (R-2):** global semaphore caps to
   1 concurrent ingest across all slugs.
2. **FM-2 — Slug path-traversal (R-2):** `validate_slug` in the
   new handlers; matches the 6 existing handler pattern.
3. **FM-3 — Stderr as prompt-injection vector (R-2):**
   `html.escape()` on the captured stderr tail before storage.
4. **FM-4 — Absolute-path leakage in stderr (R-2):** `_redact_paths()`
   regex substitution before truncating + storing.
5. **FM-5 — Orphaned `running` rows after daemon restart (both):**
   startup recovery scans `WHERE status='running'`, marks them
   `failed` with `"server restarted mid-ingest"`.
6. **FM-6 — Event-loop blocking via bare `create_task(sync_fn)`
   (both, CRITICAL):** the task wrapper MUST be async — subprocess
   spawn via `asyncio.create_subprocess_exec` is the chosen
   approach.
7. **FM-7 — 404 between trigger and row commit (R-2):** insert
   the run row BEFORE spawning the task.
8. **FM-8 — Polling rate-limit collision (R-2):** the 2s polling
   loop hits `/ui/api/*` which has no rate limit; the MCP
   1000/hour cap applies to `/mcp` only. Informational.
9. **FM-9 — `done_callback` race with daemon shutdown (R-2):**
   the FM-5 startup-recovery is the backstop. The `done_callback`
   must also handle the case where the SQLite update fails (just
   log it; the FM-5 recovery will catch the stale row eventually).

## Acceptance-criteria mapping

- [ ] **AC #1** — Clicking "Ingest now" starts a background task;
  the run row stays `running` until the pipeline exits.
  Verified by: integration test that posts to the trigger
  endpoint, polls `/latest`, asserts `data-status="running"`
  initially → `data-status="success"` after the (mocked)
  subprocess completes.
- [ ] **AC #2** — Failure surfaces the last 1 KB of stderr in the
  UI without exposing absolute paths beyond `var/arxmcp/`.
  Verified by: a test that mocks the subprocess to return
  exit_code=1 + stderr containing `/Users/.../var/arxmcp/foo`;
  asserts the stored `stderr_tail` contains `var/arxmcp/foo` but
  NOT `/Users/`.
- [ ] **AC #3** — Only one in-flight ingest per notebook is
  allowed (concurrent POST returns HTTP 409). Verified by: two
  POSTs to the same slug back-to-back; first returns 202, second
  returns 409.
- [ ] **AC #4** — No "preview paper" route, link, or iframe in
  m9. Verified by: `tests/test_m9_scope_invariants.py::test_no_preview_or_iframe_in_frontend`
  which greps `frontend/` for the forbidden tokens.
- [ ] **AC #5** — `make test` green; new tests cover happy path
  and 409.

## Open questions (deduped union)

1. **`notebook_ingest_runs` table location** (R-2 OQ-1). Synthesis
   resolution: same SQLite file as `NotebooksStore`. Add 3 new
   methods (`insert_ingest_run`, `update_ingest_run`,
   `get_latest_ingest_run`) to the existing class.

2. **Global semaphore vs per-notebook only** (R-2 OQ-2). Synthesis
   resolution: ship both. Per-notebook is AC; global is FM-1
   defense-in-depth.

3. **Lifespan shutdown — await or cancel in-flight ingest?** (R-2 OQ-3).
   Synthesis resolution: `task.cancel()` on all in-flight tasks
   in the lifespan finally, then `asyncio.gather(*tasks,
   return_exceptions=True)` with a short timeout (5s). Document
   that the subprocess continues running until the OS reaps it —
   the daemon restart leaves a subprocess orphan briefly, but the
   FM-5 startup recovery marks the row `failed` on the next boot.

4. **`tools.notebook_ingest` invocation form** (R-1 OQ-1). The
   implementer verifies `python -m tools.notebook_ingest` works
   before writing the code; falls back to the explicit file-path
   form if not.

5. **htmx swap value: `outerHTML` vs `innerHTML`** (R-1 OQ-3).
   Synthesis D3 resolution: pick `outerHTML`. HTTP 286 stops
   polling regardless of swap mode; `outerHTML` lets the response
   change the wrapper div's classes for status-driven styling.

None are blockers.

## External writes required

**None.** Pure-local milestone. New SQLite table in the existing
notebooks.db file; new FastAPI route handlers; new Jinja2 template
partial; new tests. No git push, no GH issue, no infra mutation.

Phase 4 has no blocking external-write gates.

## Orchestrator synthesis note

Both researchers reached the same conclusion on FM-6 (CRITICAL —
the brief's "asyncio.create_task" framing is correct as the SHELL,
but the work inside MUST be a subprocess or `to_thread` call;
bare `create_task(sync_fn())` would pin the event loop). Both
caught the additive-vs-destructive schema migration trap. Both
identified the row-before-task ordering and the startup-recovery
need.

The substantive disagreement on subprocess vs in-process resolved
in favor of subprocess: the AC #2 stderr-capture requirement +
process isolation outweigh the cold-start cost. The HTTP 286
polling-stop signal from R-2 is cleaner than R-1's client-side
JS approach and got picked unconditionally.

Inline path is correct (~700 LOC, every pattern established).
Commit type: `feat(server)` — server source changes dominant.
