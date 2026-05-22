# proof-verify-handler-wiring-m9 — implementation summary

## One-line summary

UI ingest trigger + status polling: `POST /ui/api/notebooks/{slug}/ingest`
spawns `python -m tools.notebook_ingest <slug>` as a subprocess
inside an `asyncio.create_task` managed by a NEW
`IngestTaskTracker`; `GET /ui/api/notebooks/{slug}/ingest/latest`
returns an HTML fragment for htmx polling and **HTTP 286** on
terminal-state runs (canonical htmx polling-stop signal).

## Commit range

`47e3502..<HEAD-after-feat-commit>`.

## Acceptance criteria status

From the milestone brief at
`plans/proof-verify-handler-wiring-roadmap.md:337-352`:

- [x] **AC #1** — Clicking "Ingest now" starts a background task;
  the run row stays `running` until the pipeline exits. Verified
  by `TestIngestTrigger::{test_trigger_returns_202_with_html_fragment,
  test_trigger_inserts_row_before_returning}` +
  `TestHttp286OnTerminal::test_286_on_success` (end-to-end:
  trigger → poll-while-running → poll-after-success).
- [x] **AC #2** — Failure surfaces the last 1 KB of stderr in the
  UI without exposing absolute paths beyond `var/arxmcp/`.
  Verified by `TestPathRedaction::{test_redact_paths (5 parametrized),
  test_prepare_stderr_tail_pipeline}` + end-to-end
  `TestHttp286OnTerminal::test_286_on_failure` asserts
  `var/arxmcp/oops` appears in the fragment but `/Users/` does NOT.
- [x] **AC #3** — Only one in-flight ingest per notebook is allowed
  (concurrent POST returns HTTP 409). Verified by
  `TestPerNotebookCollision::test_second_concurrent_post_returns_409`.
- [x] **AC #4** — No "preview paper" route, link, or iframe in m9.
  Verified by `tests/test_m9_scope_invariants.py::test_no_preview_or_iframe_in_frontend`
  — runs `grep -rEi "iframe|preview" frontend/` and fails if any
  match. Returns clean today.
- [x] **AC #5** — `make test` green; new tests cover the happy
  path and the 409 collision. **2461 passed**, 9 skipped, 1
  xfailed. Ruff clean.

## New / changed files

- **NEW:** `server/ingest_tracker.py` (~260 LOC) —
  `IngestTaskTracker` class + `prepare_stderr_tail` + `redact_paths`
  helpers.
- **EDIT:** `server/notebooks_store.py` — `SCHEMA_VERSION 1 → 2`
  with ADDITIVE migration (staged per-version ladder); 5 new
  methods (`insert_ingest_run`, `update_ingest_run`,
  `get_latest_ingest_run`, `has_running_ingest`,
  `mark_orphaned_runs_failed`).
- **EDIT:** `server/routes/notebooks.py` — module-scope `import html`
  (was inline); 2 new handlers (`trigger_ingest`, `latest_ingest`);
  `_get_ingest_tracker` dependency; `_ingest_status_fragment`
  helper.
- **EDIT:** `server/main.py` — lifespan opens
  `IngestTaskTracker`, runs orphan-recovery (FM-5), closes the
  tracker in the finally block (`shutdown(timeout_seconds=5.0)`).
- **EDIT:** `frontend/templates/notebook_detail.html` — added
  ingest trigger form + status placeholder with
  `hx-trigger="load"` so the page renders the latest status on
  first paint.
- **NEW:** `tests/test_ingest_endpoint.py` (~530 LOC, 22 tests).
- **NEW:** `tests/test_m9_scope_invariants.py` (~45 LOC, 1 test).
- **EDIT:** `CHANGES.md` — `## Unreleased` entry for 2026-05-22 m9.

## Tests

`make test`: **2461 passed, 9 skipped, 1 xfailed.** Net delta
from m8-complete (2438): **+23 tests** (22 ingest-endpoint +
1 scope-invariant). Ruff clean.
`EXPECTED_TOOL_SCHEMA_SHA256` unchanged (verified — no new MCP
tools).

## External writes required

**None.** Pure-local milestone. The subprocess invocation
(`python -m tools.notebook_ingest <slug>`) is operator-initiated
via the UI and runs against the local repo's own `tools/` module;
no third-party API calls fire from the daemon itself. The
existing ar5iv politeness contract (`tools/arxiv_fetch.py`) is
respected by the ingest subprocess just as it is by the CLI
invocation.

## Deviations from the brief

- **Subprocess (NOT in-process via `asyncio.to_thread`).** The
  brief says "spawns ... as a background `asyncio.create_task`"
  without specifying subprocess vs in-process. Synthesis D1
  chose subprocess for:
  (1) Stderr capture is the AC #2 explicit requirement;
      `asyncio.subprocess.PIPE` is native vs the in-process
      alternative requiring global `sys.stderr` redirection
      from a worker thread.
  (2) Process isolation — an ingest crash (BGE-M3 OOM, LaTeXML
      segfault, LanceDB write fault) cannot crash the daemon.
  (3) Cold-start cost (~30s BGE-M3 reload) is rounding error
      on a 30-minute ingest.
- **HTTP 286 for polling-stop (NOT client-side JS).** Synthesis
  D2 chose the htmx-documented canonical mechanism over R-1's
  `hx-on::htmx:after-swap` JS that inspects `data-status` and
  removes `hx-trigger`. The server-side approach is zero-JS,
  idempotent across page refreshes, and bookmarks the
  terminal-state response.
- **Additive SCHEMA_VERSION 1 → 2 migration (NOT destructive).**
  The existing `NotebooksStore` migration pattern (and Tier1Store's)
  is DROP-AND-RECREATE on bump — appropriate for caches (a miss
  is not a correctness failure) but DATA-LOSS for notebook
  metadata. Synthesis flagged this; the m9 implementation
  ships a staged-per-version ladder so v0→v1 keeps the original
  destructive create (runs only on fresh DBs) and v1→v2 is
  additive (`CREATE TABLE IF NOT EXISTS`). Existing notebook +
  paper rows survive the bump. Pinned by
  `TestSchemaMigration::test_v1_to_v2_preserves_notebooks_rows`.
- **Global semaphore cap of 1 (not in the brief AC).** Added
  `asyncio.Semaphore(1)` in `IngestTaskTracker._global_cap`
  alongside the per-notebook check. The per-notebook 409 closes
  the AC; the global cap closes FM-1 (resource exhaustion from
  many ingests across many notebooks). Defense-in-depth.
- **Startup orphan-recovery (FM-5).** Not in the brief, but
  identified by both researchers as a real foot-gun: if the
  daemon dies mid-ingest, the `done_callback` never fires and
  the row stays `status='running'` forever. The lifespan now
  marks every `running` row older than 1 hour as `failed` with
  `"server restarted mid-ingest"` BEFORE accepting any new
  triggers. The 1-hour cutoff is defensive — any actually-
  in-flight ingest would have completed within that window.
- **Default ingest-running fragment polls every 2s; terminal
  fragments OMIT `hx-trigger`.** Defense-in-depth on top of
  HTTP 286: even if a future client doesn't honor 286, the
  fragment doesn't include the polling trigger so the loop
  stops anyway. Pinned by
  `TestHttp286OnTerminal::test_286_on_success` (asserts
  `"hx-trigger" not in r.text` on terminal response).

## What this unblocks

Track-D frontend is **complete** with m7+m8+m9. The operator can
now:
1. Create a notebook (m7 + m8 UI).
2. Add papers via URL paste OR drag-drop upload (m7 + m8).
3. Trigger ingest from the UI and watch status (m9).
4. Run downstream `/proof-verify` per-notebook queries via the
   m1 + m2 `paper_id` filter (Track A) against the freshly-
   ingested corpus.

The only remaining roadmap milestone is **m10 (v2, Later lane)**
— in-UI paper preview via sandboxed iframe. That's deferred
indefinitely per the user's 2026-05-21 decision; m9 AC #4
explicitly defends against any premature m10 leak (the
grep-based scope test).
