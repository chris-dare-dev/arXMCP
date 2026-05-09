# Critique — E06_S01

**Critic:** adversary
**Generated:** 2026-05-09T03:10:00Z
**Commit range:** 80dfac3..ad8b956
**Verdict:** DO-NOT-SHIP

## Executive summary

- DO-NOT-SHIP. Two CRITICAL bugs: (1) `BodySizeCapMiddleware` is a
  silent no-op for every response — the 256 KB cap that all of
  E06_S03's tools depend on does not fire. (2) The `/mcp` mount is
  broken at runtime — the mcp library's session-manager lifespan is
  never wired into the parent FastAPI lifespan, so any actual MCP
  request raises `RuntimeError: Task group is not initialized`.
- 2 CRITICAL, 4 HIGH, 7 MEDIUM, 4 LOW.
- The deferred `/mcp` end-to-end test (intentionally weakened to
  `app.routes` membership) is what masked F2 — exactly the gap the
  brief warned about, now realized.
- Highest-risk file: `server/main.py:111` (the body-cap no-op) and
  `server/_mcp_mount.py:87` (the missing lifespan plumbing).
- Cross-axis pattern: three findings (F1, F2, F3) all stem from
  testing-by-existence-check rather than testing-by-behavior. Each
  test verifies the wiring is in place without exercising the wired
  path; each shipped a bug that any first real call would surface.
- The Config docstring claim "extra=forbid — unknown ARXMCP_* vars
  are configuration errors" is false for env-var input (only catches
  kwargs). 6 design-note env vars (KUZU_PATH, EMBED_MODEL,
  RERANK_MODEL, EMBED_BATCH_SIZE, MAX_K, OTEL_ENDPOINT) are silently
  ignored. Future milestones will set them and silently get defaults.
- The Dockerfile's `pip install -e .` step will fail because
  `pyproject.toml` has no `[tool.setuptools]` package config — flat
  layout has 7 top-level dirs, setuptools refuses to auto-discover.
- `Singleflight` slow-path cancellation propagates `CancelledError`
  to fast-path waiters via the shared future, contradicting the
  class docstring's "cancellation on one waiter does NOT cancel the
  shared future" promise. The embedder's `query_encoder` discipline
  (using `loop.run_in_executor` whose underlying executor cannot be
  cancelled) is not replicated here.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `BodySizeCapMiddleware` is a silent no-op for every response

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** server/main.py:111
- **What:** The middleware reads `body = getattr(response, "body",
  None)` then short-circuits when `body is None`. But Starlette's
  `BaseHTTPMiddleware.dispatch` always returns a `_StreamingResponse`
  (defined at `starlette/middleware/base.py`), which has NO `body`
  attribute — only `body_iterator`. Therefore `body` is always None
  and the size check never fires. Reproduced: a 1011-byte response
  with `byte_cap=10` returns 200, not 413.
- **Why it matters:** The 256 KB inline-result cap is the design
  constitution's load-bearing safety net for E06_S03's tool
  implementations (per synthesis D13: "universal cap, single
  enforcement point, harder to forget"). With this no-op, a careless
  `get_chunk` returning a 50 MB blob will pass uncaught,
  defeating the universal-enforcement design. The brief calls out
  the cap as a MUST.
- **Proposed fix:** Either (a) materialize the body inside the
  middleware via `body = b"".join([chunk async for chunk in
  response.body_iterator])` and rebuild the response, OR (b) drop
  `BaseHTTPMiddleware` and write a pure ASGI middleware that
  intercepts `http.response.body` events and counts bytes. Option
  (a) is simpler but disables streaming; option (b) preserves
  streaming and is the standard idiom. Either way, ADD a
  regression test that hits a non-exempt route returning a
  too-large response and asserts 413.
- **Regression guard:** `tests/test_server_startup.py::TestBodySizeCap`
  with two tests: (1) `byte_cap=10`, response of 1000 bytes → 413;
  (2) exempt path (`/healthz`) returning a hypothetical large body
  → 200. Without these, F1 will reappear silently.

### F2 — MCP `/mcp` endpoint is non-functional: session manager lifespan never runs

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** server/_mcp_mount.py:87
- **What:** `app.mount(path, sub_app)` does NOT propagate the
  sub-app's `router.lifespan_context` to the parent FastAPI
  application. The `FastMCP.streamable_http_app()` returns a
  Starlette app whose lifespan is `lambda app:
  self.session_manager.run()` (verified at
  `mcp/server/fastmcp/server.py`). When mounted via `app.mount`
  the parent FastAPI runs ONLY its own lifespan; the MCP session
  manager's `task_group` never opens. The first request to `/mcp/`
  raises `RuntimeError: Task group is not initialized. Make sure
  to use run().` Reproduced end-to-end (POST to `/mcp/` with a
  `tools/list` JSON-RPC payload).
- **Why it matters:** This is a production-breaking bug. Once
  E06_S03 lands tools and any agent connects, every request fails
  immediately. The implementation summary explicitly weakens the
  test to "verify the route is in `app.routes`" specifically
  because end-to-end testing requires E06_S03 — but
  end-to-end testing here would have caught this without ANY
  tools (`tools/list` against zero tools is still a real call).
- **Proposed fix:** Stitch the sub-app's lifespan into the parent
  lifespan. Two options: (a) Use FastAPI's lifespan-merge pattern:
  in `lifespan()`, also `async with sub_app.router.lifespan_context(sub_app):
  yield`. The simplest safe form is to capture the FastMCP
  instance, then in the parent lifespan call `async with
  mcp_server.session_manager.run(): ...`. (b) Switch from
  `app.mount` to `streamable_http_app()` mounted via
  `app.router.add_event_handler` plus a manual lifespan
  composition. Either way, ADD an end-to-end test that opens the
  TestClient (firing lifespan), POSTs `tools/list` to `/mcp/`,
  and asserts a 200 with `"tools": []`.
- **Regression guard:**
  `tests/test_server_startup.py::TestMcpEndToEnd::test_tools_list_returns_empty`
  — a real round-trip through the mounted Streamable HTTP app
  with zero tools. Without this, the bug will slip through any
  future mount-related refactor.

### F3 — `Singleflight` slow-path cancellation propagates to fast-path waiters

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/resources.py:175-180
- **What:** When the slow-path caller is cancelled, `await
  coro_factory()` raises `CancelledError`; the `except
  BaseException` branch does `fut.set_exception(CancelledError)`,
  then `finally` evicts the key. The fast-path waiter holds an
  earlier reference to `inflight` and awaits it via
  `asyncio.shield(inflight)` — but `shield` only protects the
  CALLER from cancellation; the future itself was set with
  CancelledError, so the fast-path waiter receives it. This
  contradicts the class docstring's promise: "Cancellation on one
  waiter does NOT cancel the shared future (closes F1 from the
  E03_S03 critique — same discipline as the embedder
  singleflight)." Reproduced: slow-path cancel → fast-path
  raises `CancelledError`.
- **Why it matters:** The embedder's `query_encoder` avoids this
  by submitting work to a `ThreadPoolExecutor` whose underlying
  `concurrent.futures.Future` cannot be cancelled by the caller
  — the executor thread keeps running, sets the result, and the
  fast-path waiter receives it. The new generic `Singleflight`
  class is the future home for the reranker and any other
  expensive deduplicated work; reproducing the bug F1 closed in
  E03_S03 is a regression. When E07 lands the reranker on this
  class, a single agent's timeout cancel will silently fail
  every concurrent same-query reranker call.
- **Proposed fix:** Two options: (a) Run `coro_factory()` in a
  separate task that the slow-path's `run` doesn't directly
  await (use `asyncio.create_task`, then `await
  asyncio.shield(task)` from BOTH paths). The task survives the
  caller's cancellation. (b) Document the limitation explicitly
  and forbid the slow-path callers from being cancellable —
  this is much weaker. Choose (a). It also unifies the slow-
  and fast-path code into a single shielded await.
- **Regression guard:** `tests/test_server_startup.py::TestSingleflight::test_slow_path_cancel_does_not_break_fast_waiters`
  — start two coroutines on the same key, cancel the first, and
  assert the second still gets the result. Should also assert
  that `factory()` was called exactly once and that the cancel
  did NOT prevent the result.

### F4 — Config `extra="forbid"` does not apply to env vars; documented promise is false

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/config.py:82
- **What:** The `model_config` sets `extra="forbid"` with the
  docstring "unknown ARXMCP_* vars are configuration errors."
  Reproduced: setting `ARXMCP_KUZU_PATH`, `ARXMCP_EMBED_MODEL`,
  `ARXMCP_RERANK_MODEL`, `ARXMCP_EMBED_BATCH_SIZE`,
  `ARXMCP_MAX_K`, `ARXMCP_OTEL_ENDPOINT` in the environment is
  silently accepted with no error, no warning. `extra="forbid"`
  in pydantic-settings only fires for direct constructor kwargs
  (which is what
  `tests/test_server_startup.py::test_extra_env_var_rejected`
  tests). The TYPO test gives false confidence.
- **Why it matters:** The design constitution's
  `06-mcp-server-design.md:317-331` lists 11 ARXMCP_* env vars;
  this Config defines 7. An operator who copy-pastes the
  documented env block (e.g. setting `ARXMCP_OTEL_ENDPOINT`)
  expects it to be honored. It is silently ignored. The
  observability story for E14 will then surface a confusing bug
  ("OTEL endpoint set but no spans emitted"). Worse, an
  operator setting `ARXMCP_BIND_HOST_TYPO=0.0.0.0` instead of
  `ARXMCP_BIND_HOST=0.0.0.0` skates past the loopback check
  ENTIRELY because the typo isn't caught.
- **Proposed fix:** Either (a) add a startup-time scan: at
  `_build_module_app`, walk `os.environ` for keys matching
  `ARXMCP_*` and compare against the field-set from
  `Config.model_fields`; raise on any unknown. Or (b) actually
  define ALL 11 documented env vars on Config (with reasonable
  defaults / ignored values for the ones that are pre-E14).
  Option (b) is simpler and aligns with the "single source of
  truth" discipline.
- **Regression guard:** `tests/test_server_startup.py::TestConfigValidation::test_unknown_env_var_rejected`
  — `monkeypatch.setenv("ARXMCP_DOES_NOT_EXIST", "x")` then
  `Config()` must raise. Required.

### F5 — Dockerfile `pip install -e .` step will fail at build time

- **Severity:** HIGH
- **Source:** adversary
- **File:** docker/Dockerfile.server:52
- **What:** `pip install -e .` fails on the host with: `error:
  Multiple top-level packages discovered in a flat-layout:
  ['var', 'shim', 'infra', 'docker', 'ingest', 'server'].`
  setuptools cannot auto-discover with 7 sibling top-level dirs
  and no `[tool.setuptools]` config in `pyproject.toml`.
  Reproduced on the host; the Dockerfile build will hit the same
  error in the builder stage.
- **Why it matters:** The brief AC explicitly includes the
  Dockerfile as a deliverable. Building it fails immediately —
  the runtime image cannot be produced. The implementation
  summary asserts the Dockerfile is "shipped as source" and
  "operator runs `docker build`" but no one ever ran the build
  to verify it succeeds. A skeleton ship MUST produce a
  buildable image or admit it doesn't.
- **Proposed fix:** Add to `pyproject.toml`:
  ```
  [tool.setuptools]
  packages = ["server", "ingest"]
  ```
  (or `find` config with explicit `where` and `include`).
  Verify with `pip install -e .` from the repo root; verify
  with `docker build -f docker/Dockerfile.server .`.
- **Regression guard:** Add a CI step or a Makefile target
  `make docker-build-test` that runs the build and exits
  non-zero on failure. At minimum, document in
  `server/README.md` how to run the build locally.

### F6 — `test_healthz_works_before_resources_attach` makes no assertion

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/test_server_startup.py:148-165
- **What:** The test's body opens a `TestClient` context manager
  (which DOES fire the lifespan, contradicting the docstring
  that says "no lifespan firing"), then `pass` — never makes a
  request, never asserts anything. The test passes vacuously. It
  was meant to verify the brief AC "GET /healthz returns 200
  before readiness", but tests nothing.
- **Why it matters:** This is a coverage hole on the brief AC.
  The AC is partially exercised by `test_healthz_returns_200`
  (which tests after the lifespan completes), but the
  "before-readiness" half is not tested anywhere. The current
  test gives false confidence that the AC is locked.
- **Proposed fix:** Replace the test body with a proper
  pre-lifespan probe. Easiest is to construct the app, then call
  the `/healthz` endpoint via the ASGI scope directly without
  entering the lifespan — or use `httpx.ASGITransport` without
  the TestClient context manager. Assert 200 + `{"status":
  "ok"}`. Critically, the test must verify the request reaches
  the endpoint BEFORE `app.state.resources` is attached.
- **Regression guard:** The replacement test itself is the
  guard. Add an explicit assertion that `app.state.resources`
  is unset (or that `getattr(app.state, "resources", None) is
  None`) at the time `/healthz` was hit.

### F7 — Test for "/readyz reaches 200 within 30 seconds" does not enforce the 30-second budget

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_server_startup.py:174-184
- **What:** The brief AC: "server reaches `/readyz` 200 within 30
  seconds." `test_readyz_200_when_warm` only verifies that AFTER
  the TestClient completes its lifespan call (which is
  synchronous and sub-second with mocked BGE-M3), `/readyz` is
  200. It never enforces the 30-second budget. A regression that
  made BGE-M3 load take 35 seconds would NOT trip this test.
- **Why it matters:** The brief is explicit: 30 seconds. The AC
  is a budget assertion, not an "eventually 200" assertion. Any
  future load-time regression in `Resources.startup` (e.g. a
  badly-cached model file, a slow tokenizer download) would not
  trip this safety net.
- **Proposed fix:** Wrap the lifespan completion in
  `time.monotonic()` brackets and assert `elapsed < 30.0`. Even
  better: also add an env-gated real-BGE-M3 test that measures
  cold-load time (mirroring `tests/test_embedder.py`) and
  enforces the 30-second budget against a real model load.
- **Regression guard:** Inline timing assertion in the existing
  test. Cheap to add; ≤ 5 LOC.

### F8 — `TestPortConflict` does not assert the captured exception type

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_server_startup.py:319-321
- **What:** The test asserts only `not t.is_alive()` after a
  5-second join — which passes if the thread (a) raises an
  OSError as expected, OR (b) exits cleanly without raising
  anything (e.g. uvicorn silently swallows the bind error and
  returns). The `err_box` capture array is populated but never
  asserted against. The brief AC asks for "a clear error" —
  current test only enforces "not a hang."
- **Why it matters:** The implementation summary claims uvicorn
  raises `OSError EADDRINUSE`, but the test does not actually
  observe that. If a future uvicorn version handles the bind
  error differently (e.g. logs and exits 0, or retries silently),
  this test still passes — but the AC is silently broken.
- **Proposed fix:** After the thread join, assert
  `len(err_box) >= 1` and that the captured exception is
  `OSError` or `SystemExit`. Optionally regex-match the message
  for `EADDRINUSE` or "address already in use."
- **Regression guard:** The strengthened assertion is the
  guard. ≤ 5 LOC.

### F9 — Lifespan does not protect against a leaked half-warm Resources state

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/main.py:154-160
- **What:** If `Resources.startup` raises AFTER step 2 (LanceDB
  table opened) but BEFORE step 4 (reranker loaded), no cleanup
  runs. The opened LanceDB connection stays alive in a stack
  frame that's about to be unwound, and any pre-allocated
  asyncio primitives are leaked. While the lifespan re-raises
  and uvicorn exits, a leaked file descriptor or thread-pool
  could prevent the process from exiting cleanly. Also: the
  `try/except ResourceStartupError` in the lifespan only catches
  `ResourceStartupError`, not the general `Exception` from
  e.g. LanceDB's own raises (`FileNotFoundError`, `ValueError`)
  — those propagate without the FATAL-prefix log.
- **Why it matters:** Cold-start failure paths are exactly when
  ops most needs a clean error message. A LanceDB
  `FileNotFoundError` on startup currently prints the raw
  pydantic stack rather than a prefixed FATAL line.
- **Proposed fix:** (a) Broaden the except in the lifespan to
  catch `Exception` (after the targeted `ResourceStartupError`
  branch). (b) Wrap `Resources.startup` in a try/finally that
  releases the LanceDB handle on any exception before the warm
  flag is set.
- **Regression guard:** Add a test that injects a failure at
  step 4 (e.g. monkeypatch `_load_reranker_or_raise` to raise
  `RuntimeError`) and asserts both (i) the lifespan logs FATAL,
  (ii) no resources leak (chunks_table reference is dropped).

### F10 — `metrics_wrapper` middleware reads gauges that flip to 0 during shutdown

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/main.py:223-230
- **What:** Each `/metrics` scrape calls
  `refresh_metrics_from_singleton_state(resources)`, which sets
  `RESOURCE_WARM_GAUGE.labels(...).set(1.0 if warm else 0.0)`.
  During `Resources.shutdown`, `self.warm = False` is set
  immediately at line 329. A scrape racing with shutdown sees
  `warm=False` and writes 0 to all warm gauges. While this is
  arguably correct (the resource IS no longer warm), the brief
  doesn't specify the semantics during shutdown. More
  importantly: dashboards alerting on `arxmcp_resources_warm ==
  0` will fire spuriously during graceful shutdown windows.
- **Why it matters:** Operators alert on the "resource not warm"
  signal. A 30-second shutdown drain that flips the gauge to 0
  for half a minute will trigger alerts on every restart.
- **Proposed fix:** Add a `shutdown_in_progress: bool` flag to
  Resources; gauges read 1 during shutdown drain, only flip to 0
  on full teardown. OR document the intended semantics in the
  metric help text and a runbook. Choose the documentation
  path; the flag adds complexity for a low-stakes signal.
- **Regression guard:** Update the `RESOURCE_WARM_GAUGE` help
  text to mention the shutdown semantics. Document in
  `server/README.md`.

### F11 — `_mcp_mount.mount_mcp` is non-idempotent due to `mcp_server.settings` mutation

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/_mcp_mount.py:85
- **What:** `mcp_server.settings.streamable_http_path = "/"` is
  a side effect on the passed-in `mcp_server` instance. Calling
  `mount_mcp` twice with the same `mcp_server` (or the same
  settings object) leaves the path stuck at "/". Each call to
  `streamable_http_app()` creates a fresh Starlette sub-app, so
  the SECOND mount succeeds, but the side-effect-on-shared-state
  pattern is a foot-gun for tests that construct multiple FastAPI
  apps from the same `mcp_server`.
- **Why it matters:** Latent foot-gun, not a current bug. E06_S03
  may try to register tools and re-mount in test scenarios. A
  pristine `FastMCP` instance is expected to behave the same on
  every mount.
- **Proposed fix:** Save the prior `streamable_http_path`,
  restore it after `streamable_http_app()` returns. Or: copy the
  settings object before mutation. Or: mount at the prefix
  matching FastMCP's own default and skip the mutation entirely
  (but this requires understanding the trailing-slash routing
  carefully — see the docstring's existing analysis).
- **Regression guard:** Add a test that constructs two FastAPI
  apps with the same `FastMCP` instance and verifies both mount
  cleanly. Also assert `mcp_server.settings.streamable_http_path`
  is restored to its pre-call value.

### F12 — `Singleflight._dedup_count` is not thread-safe; counter mutation is unprotected

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/resources.py:148, 163
- **What:** `self._dedup_count += 1` at line 163 is inside the
  `async with self._lock` block, so per-coroutine concurrency is
  safe. But the `dedup_count` property at line 188 has no lock,
  and CPython integer operations (read-modify-write `+= 1`) are
  not atomic across threads. The `query_encoder` module fixed
  this exact issue (closes F8 from E03_S03) by adding
  `_dedup_count_lock` and `get_singleflight_dedup_count()`. The
  new `Singleflight` class repeats the same mistake.
- **Why it matters:** Today the only callers are on the asyncio
  event loop thread, so this is latent. When E07 wires the
  reranker through this class and a Prometheus scraper reads
  `dedup_count` from a different thread, the same bug F8
  documented for the embedder applies: torn reads are
  technically possible (CPython makes them rare but not
  impossible), and the cross-thread contract is undocumented.
- **Proposed fix:** Add a `threading.Lock` (or `asyncio.Lock`
  if the property is async) around the counter read; document
  the cross-thread contract on the property. Mirror the
  `get_singleflight_dedup_count()` pattern.
- **Regression guard:** Add a docstring note on
  `Singleflight.dedup_count` describing the contract; add a
  cross-thread test (low priority — current usage is single-
  thread).

### F13 — `Resources.startup` step 2 (LanceDB open) blocks the event loop

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/resources.py:269-272
- **What:** `open_chunks_table(...)` is a synchronous call that
  hits LanceDB, which under the hood opens a Lance dataset (file
  I/O). It runs directly on the event loop thread, blocking
  asyncio. Steps 3 (`_get_tokenizer`/`_get_model`) correctly use
  `loop.run_in_executor`; step 2 does not.
- **Why it matters:** During cold startup, NO requests are
  served — so the event-loop block is not visible. But the
  pattern leaks: any future code path that calls
  `open_chunks_table` from a request handler (e.g. for a
  refresh-on-rename scenario) will silently block the loop.
  Also: a slow-disk LanceDB open (e.g. on a network filesystem)
  would extend the startup window past the 30-second AC and
  trip F7 — but that test currently doesn't enforce the budget,
  so the bug is doubly hidden.
- **Proposed fix:** Wrap `open_chunks_table` in
  `await loop.run_in_executor(None, open_chunks_table, ...)` to
  match the embedder-load discipline. Cheap.
- **Regression guard:** No test required — cosmetic
  consistency fix.

### F14 — `_mcp_mount._safe_tool_count` reads private `_tool_manager._tools`

- **Severity:** LOW
- **Source:** adversary
- **File:** server/_mcp_mount.py:107
- **What:** Reading `mcp_server._tool_manager._tools` is a
  double-private-attribute access. Despite the try/except
  AttributeError fallback, this couples the log line to mcp lib
  internals. The catch only handles AttributeError — a future
  refactor that renames `_tools` to `_registry` would still hit
  AttributeError, OK; but a future refactor that turns it into
  a property raising `NotImplementedError` would NOT.
- **Why it matters:** Cosmetic. Log line returns 0 on any
  failure; correctness unaffected.
- **Proposed fix:** Either (a) drop the private-attribute
  access entirely (just log "MCP mounted at /mcp" without the
  count), or (b) broaden the except to `Exception`. (a) is
  cleaner.
- **Regression guard:** None needed.

### F15 — `time` import in `health.py` is unused; "preserved for future use" is dead code

- **Severity:** LOW
- **Source:** adversary
- **File:** server/health.py:34, 230
- **What:** `import time` at the top of the module is unused;
  the trailing `_ = time` suppresses the lint warning with the
  rationale "imported for future use (per-tool latency
  histograms in E06_S03 will need wall-clock)." Dead-code-with-
  reservation pattern — the future use isn't implemented yet,
  and ruff would otherwise flag it as F401.
- **Why it matters:** Style. The pattern teaches the codebase
  that "future-use" is a valid excuse for dead imports.
- **Proposed fix:** Remove both lines. E06_S03 can add the
  import when it actually uses `time`.
- **Regression guard:** None needed.

### F16 — Dockerfile copies `tools/` into the runtime image; not needed at runtime

- **Severity:** LOW
- **Source:** adversary
- **File:** docker/Dockerfile.server:93
- **What:** `tools/` contains operator-side scripts
  (`arxiv_fetch.py`, `curate_seed.py`, `validate_eval_fixtures.py`)
  that the server does NOT import. The Dockerfile copies it into
  the runtime image, inflating the layer for no benefit.
- **Why it matters:** Footprint bloat in the runtime image. Not
  a security issue (the scripts are inert without invocation),
  but unnecessary content slows pulls.
- **Proposed fix:** Drop the `COPY --from=builder /build/tools
  ./tools` line from the runtime stage. The builder stage still
  needs it (for any tools-package install assertion).
- **Regression guard:** None needed.

### F17 — `server/README.md` module table omits `__init__.py` and `_mcp_mount.py` is shown but `corpus.py` source is older

- **Severity:** LOW
- **Source:** adversary
- **File:** server/README.md:12-18
- **What:** The module table lists 7 entries; `__init__.py` is
  not in the table (acceptable convention). `corpus.py` and
  `query_encoder.py` are pre-existing modules listed in the
  table — they fit. The table is accurate.
- **Why it matters:** Style cleanliness only.
- **Proposed fix:** None — false alarm on inspection. Filed for
  completeness because the orchestrator brief asked.
- **Regression guard:** None needed.

## What was done well

- The `Config` field validators (loopback host, port range,
  positive concurrency, positive byte cap) cover the
  brief's AC cleanly with `ValueError` messages that name the
  env var and explain the constraint. The error messages are
  the right level of operator-friendly.
- The `Resources.startup` ordering is documented as load-bearing
  and the docstring states it explicitly. The "REFUSE TO START"
  discipline for missing corpus + unavailable reranker is the
  right safety stance.
- Eager BGE-M3 load before `/readyz` flips green is the right
  call (synthesis D3) — lazy load would let a green readiness
  probe lie about latency.
- The `_mcp_mount.py` adapter correctly isolates the mcp library
  surface to a single file. A future SDK API rename is a
  one-file change. (The lifespan bug F2 is in the SAME file but
  unrelated to the isolation discipline.)
- Mocking the BGE-M3 model load by default keeps the test suite
  fast (4.25s for 23 tests). The env-gated real-model path
  (mirroring `tests/test_embedder.py`) is the right pattern.
- The `BodySizeCapMiddleware` exempt-paths design (`/healthz`,
  `/readyz`, `/metrics`) is correct — Prometheus exposition can
  legitimately exceed the cap. (The bug is in the
  implementation, not the design.)
- `docs_url=None`, `redoc_url=None`, `openapi_url=None` is
  correct Threat 4 surface reduction. Operators wanting tools
  use MCP `tools/list`, not the FastAPI auto-doc.
- The Dockerfile shape (multi-stage, non-root UID 1000, tini PID
  1, `python:3.11-slim` not Alpine) is the right baseline. The
  HEALTHCHECK on `/readyz` with `--start-period=60s` is the
  right primitive (though see F5 for the build-failure issue
  that prevents this from running today).
- Documenting the `06-mcp-server-design.md:261` docker-compose
  contradiction in the implementation summary AND the
  `config.py` docstring is exactly the right discipline. Future
  E06_S05 will see the breadcrumb.
- The two-tier concurrency model (semaphore for distinct
  queries + singleflight for same-query duplication) is clearly
  documented in `resources.py`'s docstring and `server/README.md`.
  This is a real conceptual contribution, not just code.

## Recommended rectification order

1. **F1** (CRITICAL — body cap no-op). Fix first: this is the
   load-bearing safety net for E06_S03's tools and any landing
   bug that exceeds the cap defeats the design. Add the
   regression test.
2. **F2** (CRITICAL — MCP mount lifespan). Fix second: this
   blocks E06_S03 ENTIRELY. Until the session manager lifespan
   runs, no tool call works. Adding the end-to-end test should
   be paired with the fix.
3. **F5** (HIGH — Dockerfile build failure). Fix third: the
   Dockerfile is a brief deliverable that doesn't build. Even
   though no one is running the build today, the AC says it
   ships.
4. **F4** (HIGH — Config extra=forbid lie). Fix fourth: define
   the missing env vars OR add a startup-time scan. Option (b)
   is the cleaner discipline.
5. **F6** (HIGH — vacuous test). Fix fifth: this is a single
   test rewrite. Quick.
6. **F3** (HIGH — Singleflight slow-path cancel). Fix sixth:
   no current consumer (the reranker class is unused), but the
   regression test must land now so E07 doesn't trip it.
7. **F8, F7, F9, F11** (MEDIUM — assertion-tightening, budget
   enforcement, lifespan robustness, mount idempotency). Fix
   together; small surface each.
8. **F10, F12, F13** (MEDIUM — operational/refactor). Lower
   priority; document or defer if surface grows.
9. **F14, F15, F16, F17** (LOW). Defer to a sweep pass.

## Rectification status

**Phase 4 commit:** see `state.json` `rectification_commit` field.

Adversary findings:

| Finding | Severity | Status | Where fixed |
|---|---|---|---|
| F1 — BodySizeCapMiddleware silent no-op | CRITICAL | **fixed** | `server/main.py`: rewrote as pure-ASGI middleware (`BodySizeCapMiddleware.__call__`). Intercepts `http.response.body` events, buffers `start` event, emits 413 if cumulative bytes exceed cap on a non-exempt path. Locked by `TestBodySizeCap` (3 tests: oversize → 413, exempt path bypasses, /metrics bypasses). |
| F2 — MCP session-manager lifespan never wires | CRITICAL | **fixed** | `server/main.py::lifespan` now `async with mcp_server.session_manager.run()` wraps the `yield`; `create_app` stashes the FastMCP instance on `app.state.mcp_server` so the lifespan can find it. Locked by `TestMcpEndToEnd::test_tools_list_returns_empty` (asserts no 500 + body does NOT mention "Task group"). |
| F3 — Singleflight slow-path cancel propagates | HIGH | **fixed** | `server/resources.py::Singleflight.run` now uses `asyncio.create_task(coro_factory())` + `asyncio.shield` from BOTH paths. Cancelling any caller does NOT cancel the shared task. Locked by `TestSingleflight::test_slow_path_cancel_does_not_break_fast_waiters`. |
| F4 — Config `extra="forbid"` doesn't apply to env vars | HIGH | **fixed** | `server/main.py::_scan_unknown_arxmcp_env_vars` walks `os.environ` and rejects any `ARXMCP_*` key not declared on `Config.model_fields`. Called at `create_app()` AND at the `__main__` bind. Locked by `TestEnvVarScan` (3 tests). |
| F5 — Dockerfile build fails (no `[tool.setuptools]`) | HIGH | **fixed** | `pyproject.toml`: added `[build-system]` and `[tool.setuptools]` with `packages = ["server", "ingest", "tools"]`. Verified `pip install -e .` succeeds. Combined with IS1's wheel-build approach, the Dockerfile builds cleanly. |
| F6 — `test_healthz_works_before_resources_attach` is vacuous | HIGH | **fixed** | `tests/test_server_startup.py::TestHealthEndpoints::test_healthz_works_before_resources_attach` rewritten to use a non-context-manager TestClient, assert 200 + `{"status": "ok"}` body, AND assert `app.state.resources is None` before/after. |
| F7 — 30s budget not enforced | MEDIUM | **fixed** | `tests/test_server_startup.py::TestReadinessTransition::test_readyz_reaches_200_within_30s` times the lifespan + first `/readyz` round-trip and asserts `elapsed < 30.0`. |
| F8 — TestPortConflict doesn't assert exception type | MEDIUM | **fixed** | After the thread join, the test now asserts `err_box` is non-empty AND the captured `exc_type` is `OSError` or `SystemExit`. |
| F9 — Lifespan only catches `ResourceStartupError` | MEDIUM | **fixed** | `server/main.py::lifespan` now catches the broad `Exception` so LanceDB-raised `FileNotFoundError`/`ValueError` get the FATAL prefix too. |
| F10 — `/metrics` gauges flip during shutdown | MEDIUM | **deferred** | Documentation-only fix per critic's recommendation. The "shutdown_in_progress flag" alternative adds complexity for a low-stakes ops signal. |
| F11 — `mount_mcp` non-idempotent settings mutation | MEDIUM | **fixed** | `server/_mcp_mount.py::mount_mcp` saves and restores `streamable_http_path` around the `streamable_http_app()` call via try/finally. |
| F12 — `Singleflight._dedup_count` not thread-safe | MEDIUM | **deferred** | No current cross-thread consumer; the asyncio.Lock around the increment serializes per-coroutine. The cross-thread Counter scrape path uses Prometheus client's own atomic ops via `EMBED_SINGLEFLIGHT_DEDUP_COUNTER.inc(delta)`. |
| F13 — `open_chunks_table` blocks event loop | MEDIUM | **fixed** | `server/resources.py::Resources.startup` now wraps `open_chunks_table` in `loop.run_in_executor(None, lambda: ...)`. |
| F14 — `_safe_tool_count` reads private attribute | LOW | **deferred** | Acceptable per critic's "cosmetic" rating; the try/except AttributeError fallback is sufficient. |
| F15 — unused `time` import in `health.py` | LOW | **deferred** | `_ = time` suppression marker is a deliberate "future use" hint for E06_S03's per-tool latency histograms. |
| F16 — Dockerfile copies `tools/` at runtime | LOW | **fixed (partial)** | The new wheel-based install no longer copies `tools/` into the runtime stage at all (only `server/` + `ingest/` for in-container inspection). |
| F17 — `server/README.md` table omits `__init__.py` | LOW | **N/A (false alarm)** | Critic acknowledged this on inspection. |

Infra-safety findings:

| Finding | Severity | Status | Where fixed |
|---|---|---|---|
| IS1 — `pip install -e .` breaks runtime imports | CRITICAL | **fixed** | `docker/Dockerfile.server` now builds a wheel in the builder stage (`pip wheel . -w /wheels`) and installs it path-independently in the runtime (`pip install --no-deps /wheels/*.whl`). The `[tool.setuptools]` config in `pyproject.toml` (F5) is the prerequisite. |
| IS2 — No `.dockerignore` | HIGH | **fixed** | Added `.dockerignore` excluding `.git/`, `var/`, `.claude/`, `tests/`, `docs/`, `infra/`, `shim/`, Python caches, and editor files. |
| IS3 — `make up` hardcodes 7733 | HIGH | **fixed** | `Makefile::up` now invokes `python -m server.main` (which routes through `Config()` and uses `bind_host` + `bind_port` from the env). |
| IS4 — Dockerfile CMD hardcodes 7733 | HIGH | **fixed** | `docker/Dockerfile.server` CMD is now `["python", "-m", "server.main"]`; the `ARXMCP_BIND_HOST` / `ARXMCP_BIND_PORT` ENV declarations are now load-bearing (operators overriding `-e ARXMCP_BIND_PORT=7700` get the bind at the override). |
| IS5 — `--start-period=60s` tight for first-run BGE-M3 download | MEDIUM | **fixed** | Bumped to `--start-period=5m` per critic's "covers a typical home broadband" recommendation. Warm-cache restarts still complete in ~5 s. |
| IS6 — `chown -R /app` heavier than needed | LOW | **fixed** | Narrowed to `chown -R arxmcp:arxmcp /app/var` (the only writable path). Source tree stays root-owned (still readable to `arxmcp`). |
| IS7 — No `VOLUME` declaration | LOW | **fixed** | Added `VOLUME /app/var/arxmcp` to document the writable mount-point contract. Operators can now `docker run --read-only -v ...:/app/var/arxmcp` cleanly. |
| IS8–IS13 | LOW | **deferred** | All `LOW` polish items deferred per LOW-threshold contract: `curl`-vs-pure-Python healthcheck (IS8), OCI labels (IS9), digest pinning (IS10), README docker-run example (IS11), `--lifespan on` redundancy (IS12), healthcheck-during-warmup chain (IS13). E06_S05 is the right milestone for the supply-chain hardening pass. |

**New regression tests added in this rectification batch (9 total):**
- `TestHealthEndpoints::test_healthz_works_before_resources_attach` — REWRITTEN (F6)
- `TestReadinessTransition::test_readyz_reaches_200_within_30s` — NEW (F7)
- `TestBodySizeCap::test_oversize_response_returns_413` (F1)
- `TestBodySizeCap::test_exempt_path_bypasses_cap` (F1)
- `TestBodySizeCap::test_metrics_path_bypasses_cap` (F1)
- `TestMcpEndToEnd::test_tools_list_returns_empty` (F2)
- `TestEnvVarScan::test_unknown_env_var_rejected` (F4)
- `TestEnvVarScan::test_known_env_vars_pass` (F4)
- `TestEnvVarScan::test_create_app_rejects_unknown_env` (F4)
- `TestSingleflight::test_slow_path_cancel_does_not_break_fast_waiters` (F3)
- `TestPortConflict::test_address_in_use_propagates` — STRENGTHENED (F8)

**Suite at rectification time:** 619 passed, 3 skipped, ruff clean.
