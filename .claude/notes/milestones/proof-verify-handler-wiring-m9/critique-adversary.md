# Critique — proof-verify-handler-wiring-m9

**Critic:** adversary
**Generated:** 2026-05-22T16:18:34Z
**Commit range:** 47e3502e58e3f384a7f6a7194b50c5e004511bde..4db472a86000a75b18a6d06e1c8d2ae0d88db766
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Implementation closes all five ACs cleanly; the security-critical surface
  (slug regex, list-args subprocess spawn, html.escape on stderr, additive
  schema migration) is right. Three real foot-guns remain on the
  task-lifecycle and orphan-recovery seam.
- 0 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk file:line — `server/ingest_tracker.py:205-217` (CancelledError
  is BaseException, not caught by `except Exception:` → cancelled tasks leave
  the DB row pinned to `running` and the subprocess orphaned).
- Cache byte-stability axis clean — `ALL_TOOLS` untouched, no MCP surface
  drift, `EXPECTED_TOOL_SCHEMA_SHA256` unchanged.
- MCP spec compliance axis clean — endpoints are under `/ui/api/*`, not
  `/mcp`. Custom HTTP 286 is htmx-specific and accepted by Starlette.
- No-fork / banned-pattern axes clean — no `BaseHTTPMiddleware` usage in
  new code, no `assert` for invariants in production paths (only in test
  helpers), no submodule additions, no model-name references in `server/`.
- The 1-hour orphan-recovery cutoff combined with the un-killed subprocess
  on shutdown creates a multi-minute deadlock window after clean restart;
  this is the single most operator-visible foot-gun (F2 below).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — CancelledError leaks past `except Exception` and pins DB row to `running`

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/ingest_tracker.py:205-245
- **What:** `_run_ingest_subprocess` wraps `await proc.communicate()` in
  `try / except Exception`. When `shutdown()` calls `task.cancel()` (line
  262), the `await` raises `asyncio.CancelledError`, which inherits from
  `BaseException` — not `Exception` — in Python 3.8+. The except block
  does NOT fire, the `update_ingest_run` call never runs, and the DB row
  stays `status='running'` with `finished_at=NULL`.
- **Why it matters:** Two consequences. (1) Until the FM-5 orphan-recovery
  next runs (server restart + row age > 1 hour), `has_running_ingest(slug)`
  returns True → operator gets a permanent 409 on retry. (2) The subprocess
  itself is never sent SIGTERM (no `proc.kill()` / `proc.terminate()` in
  the cancel path), so it continues running with no DB row tracking it.
  The combination breaks the AC #3 "only one in-flight ingest per notebook"
  contract for a window of up to 1 hour after any daemon shutdown that
  happened to coincide with an in-flight ingest.
- **Proposed fix:** Split the handler into a `try / except` that catches
  `Exception` AND a separate `try / finally` (or a `BaseException` re-raise
  branch) that writes a terminal-state DB row on cancellation. Sketch:
  ```python
  async with self._global_cap:
      proc = None
      try:
          proc = await asyncio.create_subprocess_exec(...)
          _stdout, stderr_bytes = await proc.communicate()
          exit_code = proc.returncode
      except asyncio.CancelledError:
          if proc is not None:
              with contextlib.suppress(ProcessLookupError):
                  proc.terminate()
                  try:
                      await asyncio.wait_for(proc.wait(), timeout=2.0)
                  except TimeoutError:
                      proc.kill()
          await store.update_ingest_run(
              run_id=run_id, status=store.INGEST_STATUS_FAILED,
              finished_at=now_iso_provider(), exit_code=-2,
              stderr_tail=html.escape("cancelled at daemon shutdown"),
          )
          raise
      except Exception as e:  # noqa: BLE001
          ...existing branch...
  ```
- **Regression guard:** Add a test (`TestIngestTrackerUnit::
  test_cancel_writes_failed_row_and_kills_subprocess`) that spawns a
  hung subprocess via the same fake-spawn pattern, calls
  `tracker.shutdown(timeout_seconds=1.0)`, then asserts the latest run
  row's `status == "failed"` AND the fake proc's `.terminate()` was
  called.

### F2 — 1-hour orphan-recovery cutoff blocks operator for up to 55 minutes after clean restart

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/main.py:342-349, server/notebooks_store.py:428-462
- **What:** The lifespan startup calls `mark_orphaned_runs_failed` with
  `cutoff = now - 1h`. Rows whose `started_at` is more recent than the
  cutoff are NOT touched. Combined with F1, a daemon that restarts 5
  minutes after a user-triggered ingest leaves the `running` row in place;
  `has_running_ingest(slug)` returns True for the next 55 minutes →
  every retry POST returns HTTP 409.
- **Why it matters:** Operators hit this on any clean restart-during-ingest
  scenario (config change, docker-compose reload, OS update). The
  experience is "the UI shows 'Status: running' but no progress, and
  every 'Ingest now' click returns 409". The 1-hour cutoff is designed
  to NOT clobber a possibly-still-running ingest, but the assumption
  ("any actually-in-flight ingest would have completed within that
  window") is false for big notebooks AND ignores the cancel path (F1).
- **Proposed fix:** Two options, pick one:
  1. **Best — cross-reference live PIDs.** Persist `subprocess.pid` on the
     run row at spawn time and use `os.kill(pid, 0)` at startup recovery
     to test liveness; mark rows whose PID is not alive (or whose PID is
     held by a different process) as `failed` regardless of age.
  2. **Cheap — make cutoff configurable AND lower the default to 5
     minutes.** The 5-minute floor matches the polling cadence and the
     usual "fast iterate while debugging" UX. Document the trade-off in
     `server/main.py`. If F1 is fixed, the cancel path writes the failed
     row directly and this is just defense-in-depth for hard kills.
- **Regression guard:** Add a test asserting that after F1's cancel-path
  writes the `failed` row, `has_running_ingest(slug)` returns False
  immediately on next request — i.e., end-to-end "shutdown → restart →
  retry succeeds with no 409".

### F3 — `mark_orphaned_runs_failed` writes the `message` arg to `stderr_tail` without HTML escape

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/notebooks_store.py:444-461
- **What:** The `_update` closure binds `(self.INGEST_STATUS_FAILED,
  cutoff_iso, message, ..., cutoff_iso)` and stores the raw `message`
  string in the `stderr_tail` column. The `_ingest_status_fragment`
  helper interpolates `stderr_tail` directly into `<pre>{stderr_tail}</pre>`
  with no escaping (line 915), trusting `prepare_stderr_tail` to have
  done the escape upstream.
- **Why it matters:** Today's only caller is `server/main.py:348` which
  passes a hardcoded ASCII string ("server restarted mid-ingest (m9 FM-5
  recovery)"), so the page renders safely. The contract drift is
  silent: a future caller that passes a message containing `<` or `&`
  (e.g. a stack-trace snippet, an error message that quotes
  `<retrieved_chunk>`, a path that includes `&amp;`) would inject raw
  HTML into the failure-state fragment. This is the same Threat 2 vector
  that `prepare_stderr_tail` was added to close.
- **Proposed fix:** In `mark_orphaned_runs_failed`, escape the message
  before storage:
  ```python
  safe_message = html.escape(message)
  cur = self._conn.execute(
      "UPDATE ... stderr_tail = ? ...",
      (..., safe_message, ...),
  )
  ```
  Add `import html` at module scope. OR document `mark_orphaned_runs_failed`'s
  contract as "caller MUST pre-escape `message`" and have the lifespan
  caller pass `html.escape(...)` — but that's a footgun split across
  files; doing it inside the store is the durable fix.
- **Regression guard:** A unit test that calls
  `mark_orphaned_runs_failed(cutoff_iso=..., message="<script>x</script>")`
  then reads back the row and asserts `stderr_tail == "&lt;script&gt;x&lt;/script&gt;"`.

### F4 — Path-redaction regex skips paths with spaces (e.g. `/Users/Joe Smith/...`)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/ingest_tracker.py:69-71
- **What:** The regex `rb"[/\\][\w/\\.\-]*?var[/\\]arxmcp[/\\]"` matches
  characters in the `\w` class (letters, digits, underscore) plus
  `/`, `\`, `.`, `-`. It does NOT match spaces. A macOS path like
  `/Users/Joe Smith/Personal/SourceCode/arXMCP/var/arxmcp/foo` will fail
  to match (the lazy `*?` stops at the first space, then `var` won't
  follow). The path leaks unredacted into the stored `stderr_tail`.
- **Why it matters:** AC #2 says "without exposing absolute paths beyond
  `var/arxmcp/`". The username is operator-controlled, but on macOS,
  spaces in user names are not uncommon (Apple's default "First Last"
  full-name account). Linux usernames cannot contain spaces (POSIX
  rules), so this is macOS-specific. The leak surfaces directly in the
  failure-state HTML fragment that the operator reads in the browser.
- **Proposed fix:** Allow spaces in the character class:
  ```python
  _ABS_PATH_PREFIX_RE: re.Pattern[bytes] = re.compile(
      rb"[/\\][\w /\\.\-]*?var[/\\]arxmcp[/\\]"
  )
  ```
  Test that `b"/Users/Joe Smith/repo/var/arxmcp/x"` redacts to
  `b"var/arxmcp/x"`. Optional bonus: also handle Windows UNC paths
  (`\\?\C:\Users\Joe\...`) by adding `?` to the character class; lower
  priority since the daemon only runs on POSIX today.
- **Regression guard:** Add a parametrized case to
  `TestPathRedaction::test_redact_paths` with input
  `b"/Users/Joe Smith/repo/var/arxmcp/x"` and expected
  `b"var/arxmcp/x"`.

### F5 — `INGEST_STATUS_*` constants are class attributes, used both via instance and class — drift risk

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/notebooks_store.py:332-334, server/ingest_tracker.py:224-244,
  server/routes/notebooks.py:844
- **What:** The status enum is three string class-attributes. Every
  consumer dereferences them via the `store` instance
  (`store.INGEST_STATUS_FAILED`). The class itself is `NotebooksStore`
  — a SQLite persistence class. Putting domain enums on a persistence
  class couples them to the storage implementation. A future split
  (e.g. a separate `IngestRunsStore`) will need to keep these constants
  alive on `NotebooksStore` indefinitely or update every call site.
- **Why it matters:** Latent footgun, not a bug today. The 7 call sites
  agree on the constant values, and the SQL `WHERE status = ?` checks
  use the same constants — so a typo in the strings would be caught.
  But putting domain enums on a persistence class is a common drift
  source.
- **Proposed fix:** Move the three constants to module scope in
  `server/ingest_tracker.py` (the domain owner), import them where
  needed. The `NotebooksStore` keeps a runtime alias for backwards
  compat:
  ```python
  # server/ingest_tracker.py
  INGEST_STATUS_RUNNING = "running"
  INGEST_STATUS_SUCCESS = "success"
  INGEST_STATUS_FAILED  = "failed"
  ```
  No behavior change; cleans up the import graph.
- **Regression guard:** No new test needed; existing tests cover the
  string values.

### F6 — `latest_ingest` does not call `_get_ingest_tracker` despite the dependency being defined for both endpoints

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/routes/notebooks.py:794-858
- **What:** The dependency function `_get_ingest_tracker` (defined at
  line 698) is only called from `trigger_ingest` (line 757). The
  `latest_ingest` handler reads exclusively from the SQLite store —
  ignoring the in-memory tracker entirely. This means a polling request
  that arrives between (a) the trigger handler writing the `running`
  row and (b) the tracker dict entry being populated by `start_ingest`
  shows correct state from the DB, but a polling request that arrives
  AFTER tracker has cleared the entry on done-callback but BEFORE the
  done-callback completed the DB update would still see `running` —
  which is the correct UX (status="running" until DB says otherwise).
- **Why it matters:** This is actually correct behavior, but the
  inconsistency between the two endpoints means an operator reading
  the code has to reason about why one handler uses both sources of
  truth and the other doesn't. The docstring on `latest_ingest`
  claims "the in-memory IngestTaskTracker is the primary source of
  truth for live processes" (server/notebooks_store.py:412) — but
  `latest_ingest` doesn't consult it.
- **Proposed fix:** Either (1) add a comment in `latest_ingest`
  explaining that the DB is authoritative for the polling endpoint
  by design (the row is always-current because `update_ingest_run`
  fires before the task returns), or (2) update the docstring on
  `has_running_ingest` to reflect that "primary source of truth" is
  scoped to the 409 check, not all consumers. Pick (1) — it's a
  one-line comment fix.
- **Regression guard:** None — pure documentation.

### F7 — `_get_ingest_tracker` has an incorrect `# noqa: ARG001` (request IS used)

- **Severity:** LOW
- **Source:** adversary
- **File:** server/routes/notebooks.py:698
- **What:** The function signature is `def _get_ingest_tracker(request: Request):  # noqa: ARG001`.
  ARG001 = unused function argument. But `request.app.state` is read on
  line 706. The noqa suppresses a warning that wouldn't fire.
- **Why it matters:** Cosmetic. If a future ruff version starts checking
  no-op suppressions, this would become a lint warning. Also misleads
  the reader into thinking the parameter is dead.
- **Proposed fix:** Remove the `# noqa: ARG001`. Optionally add a
  `-> IngestTaskTracker` return annotation (with a TYPE_CHECKING import
  to avoid the runtime import cost).
- **Regression guard:** None.

### F8 — Test loops poll up to 20 times via `client.get` to catch task completion (masks ordering)

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_ingest_endpoint.py:284, 310
- **What:** Both `TestHttp286OnTerminal` tests loop `for _ in range(20)`
  calling `client.get(...)` until a 286 is observed. The mocked
  subprocess returns immediately, so the background task completes
  before the FIRST poll — the loop is masking the race between the
  task's done-callback DB write and the polling request. If the
  callback hangs or never fires, the test passes silently on the 20th
  iteration with the wrong status code being asserted (because the
  `r` variable holds the last response, not necessarily the 286 one,
  if no 286 was ever seen — wait, actually the `break` skips the
  outer assertion when 286 IS seen, so if no 286 is seen, the assert
  fires on the LAST response — correct).
- **Why it matters:** The loop hides timing assumptions. If a future
  change makes the done-callback slower (or breaks it), the test would
  take 20× longer but still pass. Better to wait deterministically
  for the task to complete.
- **Proposed fix:** Either (1) add `asyncio.wait_for(tracker._tasks[slug],
  timeout=1.0)` between trigger and poll — but TestClient doesn't expose
  the tracker easily. OR (2) loop with an `assert r.status_code in
  (200, 286)` body each iteration so a regression that produces 500s
  fails fast. OR (3) reduce the loop bound to 3 and add a deterministic
  `time.sleep(0.05)` — if the test is flakey at that bound, the
  ordering is genuinely broken and the test SHOULD fail.
- **Regression guard:** Same tests, tightened.

### F9 — `_tasks` dict is not cleared at lifespan shutdown (held until process exit)

- **Severity:** LOW
- **Source:** adversary
- **File:** server/ingest_tracker.py:247-276
- **What:** `shutdown()` cancels tasks but does not clear `self._tasks`.
  After shutdown returns, cancelled tasks remain referenced in the
  dict until the IngestTaskTracker instance is garbage-collected (at
  process exit). The done-callbacks may still fire during the await,
  which DO clear entries via `_on_task_done` — but if a callback is
  itself cancelled by the timeout, the dict entry survives.
- **Why it matters:** Pure-leak; lifespan-end means the process is
  about to exit so the leak is bounded by uvicorn's reload cycle. In
  long-running production this is a no-op; in test loops with
  many app instances per process it could accumulate.
- **Proposed fix:** After the gather completes (success or timeout),
  `self._tasks.clear()`. One line.
- **Regression guard:** Existing `test_shutdown_cancels_running_tasks`
  can be tightened to assert `tracker._tasks == {}` after shutdown.

## What was done well

- Subprocess spawned with a fixed-length argv list (`sys.executable, "-m",
  "tools.notebook_ingest", slug`) and NOT `shell=True` — the right
  defense against argument-injection. Combined with the strict
  `^[a-z][a-z0-9-]{2,30}$` slug regex, there is no reachable code path
  that injects a `-c` or `-m` flag (server/ingest_tracker.py:207-214).
- The SCHEMA_VERSION 1→2 migration is genuinely additive — `CREATE TABLE
  IF NOT EXISTS` + a clearly-labeled `m9 DEVIATION` comment naming
  WHY the destructive Tier1Store pattern doesn't apply here
  (server/notebooks_store.py:154-180). The `test_v1_to_v2_preserves_notebooks_rows`
  test pins this with a hand-crafted v0 DB.
- `prepare_stderr_tail` orders the pipeline correctly — truncate FIRST
  (bounds the regex scan), then redact, then decode, then escape. Five
  parametrized cases cover the redaction (server/ingest_tracker.py:84-100
  + tests/test_ingest_endpoint.py:178-218).
- The row-before-task ordering closes FM-7 with an explicit comment AND
  an explicit test (`test_trigger_inserts_row_before_returning`)
  (server/routes/notebooks.py:773-782).
- The HTTP 286 polling-stop signal is implemented with defense-in-depth
  — terminal-state fragments ALSO omit the `hx-trigger` attribute, so
  a client that ignores 286 still stops polling (server/routes/notebooks.py:903-924,
  tested at tests/test_ingest_endpoint.py:293,321).
- Lifespan ordering is right: open store → run orphan-recovery → init
  tracker → yield. This guarantees no request can hit the trigger
  endpoint before orphans are cleared (server/main.py:334-362).
- The done-callback (`_on_task_done`) retrieves `task.exception()` to
  prevent the asyncio "Task exception was never retrieved" warning —
  correct discipline (server/ingest_tracker.py:179-184).
- AC #4 (no preview/iframe) is enforced by a static-grep test that
  runs without the server — a cheap, durable scope-invariant
  (tests/test_m9_scope_invariants.py).
- Both new endpoints validate slug via the shared `validate_slug` from
  `tools._notebook_common` — the established path-traversal defense
  (server/routes/notebooks.py:744, 817).
- The 22 tests + 1 scope test give honest coverage: trigger happy path,
  409 collision, path redaction (5 cases), HTML escape, latest endpoint
  (running/none/missing), 286 on success + failure, schema migration
  preservation, orphan recovery, tracker unit tests, shutdown cancellation.

## Recommended rectification order

1. **F1** (HIGH) — fix the CancelledError leak in
   `_run_ingest_subprocess`. This is the blast-radius foundation: the
   bug pins DB rows, leaks subprocesses, and underpins F2's UX impact.
   The fix is ~15 LOC + 1 test.
2. **F2** (HIGH) — either lower the orphan-recovery cutoff to 5 minutes
   OR add PID liveness check. Cheapest: make cutoff configurable
   (`ARXMCP_INGEST_ORPHAN_CUTOFF_SECONDS`) with a 300s default. Once F1
   lands, this becomes pure defense-in-depth.
3. **F3** (MEDIUM, ~5 LOC) — html-escape the `message` argument in
   `mark_orphaned_runs_failed`. Closes the only remaining unescaped
   path into the failure-state fragment.
4. **F4** (MEDIUM, ~3 LOC + 1 test case) — add space to the redaction
   regex character class. Same diff hunk as F3 if convenient.
5. **F5** (MEDIUM, ~20 LOC across 3 files) — only worth doing if Phase
   4 already has the test surface open. Defer if rectification budget
   is tight.
6. **F6** (MEDIUM, 1-line comment) — cheap; bundle with F3 or F4.
7. **F7** (LOW), **F8** (LOW), **F9** (LOW) — defer to a future polish
   pass; not load-bearing.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
