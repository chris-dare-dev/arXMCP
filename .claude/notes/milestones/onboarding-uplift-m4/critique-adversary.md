# Critique — onboarding-uplift-m4 (adversary)

**Critic:** adversary
**Generated:** 2026-05-31T00:00:00Z
**Commit range:** 574f1c2..071d4b1
**Verdict:** DO-NOT-SHIP

## Executive summary

- AC1 ("ARXMCP_BOOTSTRAP_MODE=1 make up boots cleanly") is FALSE — the
  lifespan crashes with AttributeError immediately after Resources.startup
  returns, because `refresh_metrics_from_singleton_state` unconditionally
  dereferences `resources.corpus_info.version` and `.chunk_count`. This
  is verified by direct repro (see F1). The test suite never exercises
  the lifespan, so the headline acceptance criterion was rubber-stamped.
- 1 CRITICAL, 4 HIGH, 4 MEDIUM, 2 LOW. The CRITICAL alone is shippable-
  bug-in-production-now; F2 (synthesis D1 non-implementation, /readyz +
  /status return 503) compounds it by ensuring even a fixed F1 still
  leaves the shim unable to distinguish bootstrap from genuine not-ready.
- Highest-risk file:line — `server/main.py:444` (the un-defended
  `refresh_metrics_from_singleton_state(resources)` call in lifespan).
- MCP 2025-06-18 spec compliance is broken on the bootstrap envelope:
  `_build_bootstrap_envelope` returns a plain dict, so FastMCP's
  lowlevel handler stuffs the whole envelope into a single TextContent
  block and hard-codes the wire-level `isError=False`. The intent of
  the synthesis's "isError: true for business-logic errors" is dead on
  arrival at the wire (F3, verified by direct repro).
- The `on_success_callback` plumbing in IngestTaskTracker has ZERO test
  coverage — no test verifies it fires on exit_code==0, that it does NOT
  fire on exit_code!=0, or that the exception-swallow behavior holds.
  This is a load-bearing piece of the milestone's promise.
- `_corpus_ready_event` is added with a load-bearing-looking comment but
  has no consumer — no code awaits it; the orchestrator check reads the
  bool flag. The synthesis D2 rationale ("Event over Lock+flag so the
  hot path doesn't take a lock") describes a use case that does not
  exist in the implementation. The Event is dead-code-by-construction.
- Failure-mode coverage for `late_bind` partial-mutation is incomplete:
  `set_cache(retrieval_cache)` runs BEFORE the flag flip and BEFORE the
  RerankPhase construction that can raise. An operator running
  `ARXMCP_BOOTSTRAP_MODE=1 + ARXMCP_ENABLE_RERANK=true` triggers a
  silent late_bind failure that leaks a real cache into the global
  module while the bool flag stays True — observable through global
  state, even if the orchestrator wrapper masks it from handlers.
- AC7 is honestly deferred to m5 with synthesis backing (§3 D3); D4
  (ARXMCP_NOTEBOOK+BOOTSTRAP_MODE) is honestly documented as
  unsupported with synthesis backing (§3 D4). No critique on those.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — refresh_metrics_from_singleton_state crashes lifespan in bootstrap mode

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** server/main.py:444 (caller) + server/health.py:523,532 (NPE site)
- **What:** Immediately after `Resources.startup(config)` returns in
  bootstrap mode, the lifespan calls
  `refresh_metrics_from_singleton_state(resources)` synchronously. That
  function reads `resources.corpus_info.version` (line 523) and
  `resources.corpus_info.chunk_count` (line 532) WITHOUT a None-guard.
  In bootstrap mode `corpus_info is None`, so the lifespan raises
  `AttributeError: 'NoneType' object has no attribute 'version'` and
  the server never starts. Verified by direct repro:
  ```
  $ uv run python -c "import asyncio,tempfile; from pathlib import Path; \
      from server.config import Config; from server.resources import Resources; \
      from server.health import refresh_metrics_from_singleton_state; \
      asyncio.run((async def(): ...)())"
  AttributeError: 'NoneType' object has no attribute 'version'
  ```
  The function is ALSO called on every `/metrics` scrape
  (`server/main.py:781` inside `metrics_wrapper`), so even if the
  startup call were guarded, every Prometheus scrape during bootstrap
  mode would 500.
- **Why it matters:** AC1 ("ARXMCP_BOOTSTRAP_MODE=1 make up boots
  cleanly with no corpus-version.json") is the headline of the
  milestone and is literally false. The implementation-summary marks
  AC1 `[x]` verified by `test_resources_startup_skips_raise_in_bootstrap_mode`,
  but that test only exercises `Resources.startup` in isolation — it
  never runs the lifespan, never calls `refresh_metrics_from_singleton_state`,
  and therefore never reaches the actual crash site. The 40% bar for
  test-vs-claim alignment is failed on the single most load-bearing AC.
- **Proposed fix:** in `server/health.py::refresh_metrics_from_singleton_state`,
  guard each `corpus_info.*` read with a None check, mirroring the
  existing `getattr` defense at line 538 for `startup_unindexed_rows`.
  Specifically: skip CORPUS_VERSION_GAUGE / CORPUS_CHUNK_COUNT_MARKER /
  CORPUS_CHUNK_COUNT_ACTUAL updates when `resources.corpus_info is None`
  (set to a sentinel like -1 or leave the gauge un-set). Also update
  the lifespan call at `server/main.py:444` to skip when
  `resources.bootstrap_mode_active is True` for symmetry, but the core
  fix is in health.py.
- **Regression guard:** new test
  `test_lifespan_succeeds_in_bootstrap_mode_with_metrics_scrape` that
  uses `TestClient(create_app())` with `ARXMCP_BOOTSTRAP_MODE=1` (no
  marker on disk) and asserts (a) the app's lifespan completes without
  raising, (b) `GET /metrics` returns 200, (c) `GET /healthz` returns
  200. This is the smoke test AC1 implicitly promised and never had.

### F2 — /readyz and /status return 503 in bootstrap mode (synthesis D1 not implemented)

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/health.py:215 (readyz) + server/health.py:322 (compute_health_status)
- **What:** Synthesis §3 D1 ("`/readyz` returns 200 with `"status":
  "bootstrap"` in the JSON body") explicitly resolved that /readyz must
  NOT 503 in bootstrap mode, on the grounds that "a 503 would cause the
  shim (`shim/arxmcp_shim.py`) to give up before the operator can
  ingest, defeating the milestone goal." The implementation does not
  honor this. In bootstrap mode the stub Resources has `warm=False`
  (resources.py:475), and both `/readyz` (`if resources is None or not
  resources.warm:`) and `/status`' `compute_health_status` (line 322
  same check) return 503/fail. There is no code path that recognizes
  `bootstrap_mode_active=True` as a distinct ready state.
- **Why it matters:** the wizard flow described in the brief is "operator
  runs `make up-wizard`, opens the UI, creates a notebook, ingests, the
  server promotes itself." The shim (`shim/arxmcp_shim.py`) gates
  Streamable HTTP traffic on /readyz — a 503 means the shim treats the
  server as down and refuses to forward MCP calls. Even though the
  orchestrator-level stub-check (tools.py:811) would correctly return
  the no_notebook_selected envelope, the shim never lets the call reach
  it. The UX promise of the milestone collapses.
- **Proposed fix:** in `server/health.py::readyz` AND in
  `compute_health_status`, add a third branch BEFORE the `not warm`
  guard: if `resources is not None and resources.bootstrap_mode_active`,
  return 200 with `{"status": "bootstrap", "warm": {...}}` for /readyz
  and "warn" with `summary="bootstrap | awaiting first ingest"` for
  /status. The shim then treats bootstrap as "serving but degraded" and
  forwards MCP calls.
- **Regression guard:** new tests
  `test_readyz_returns_bootstrap_in_bootstrap_mode` and
  `test_status_returns_warn_in_bootstrap_mode` that build a stub
  Resources with `bootstrap_mode_active=True` and assert the
  status_code/body shape.

### F3 — Bootstrap envelope isError=true is dead at the MCP wire

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/tools.py:418-438 (`_build_bootstrap_envelope` returns plain dict)
- **What:** `_build_bootstrap_envelope` returns a plain Python dict
  with `"isError": True` as a payload field. The orchestrator wrapper
  (`_wrap_with_observability`) returns this dict directly to FastMCP.
  FastMCP's `Tool.run` with `convert_result=True` calls
  `func_metadata.convert_result(plain_dict)` → since the handler has
  no output_schema, this falls into the `output_schema is None` branch
  and returns `_convert_to_content(plain_dict)` =
  `[TextContent(type="text", text=json.dumps(plain_dict))]`. The
  lowlevel server's `call_tool` handler (mcp/server/lowlevel/server.py:
  548-578) then sees the list-of-content branch and constructs
  `CallToolResult(content=[...], structuredContent=None,
  **isError=False**)` — note the **hardcoded isError=False at line 576**.
  Direct repro:
  ```
  $ uv run python -c "import asyncio; from mcp.server.fastmcp import FastMCP; \
      from server.tools import _build_bootstrap_envelope; \
      m=FastMCP('test'); \
      m.add_tool(lambda: _build_bootstrap_envelope('search_papers'), \
                 name='search_papers', description='t'); \
      print(asyncio.run(m.call_tool('search_papers', {})))"
  [TextContent(type='text', text='{...\"isError\": true,...}', ...)]
  ```
  The wire response is a single TextContent containing the bootstrap
  envelope as JSON text. The MCP-spec-level `isError` field on the
  result is False.
- **Why it matters:** AC8 ("MCP tool handlers in stub mode return
  structured `no_notebook_selected` envelope with `isError: true` and
  `corpus_version: -1`") is satisfied at the helper-return-value layer
  but VIOLATED at the wire. Per the MCP 2025-06-18 spec §"Tool
  Execution Errors", `isError: true` is the canonical mechanism for
  business-logic errors AND the spec example shows it at the TOP level
  of the result alongside `content`. The synthesis explicitly invoked
  this spec language to justify the design. The implementation does not
  deliver it. The downstream agent's `result.isError` check will see
  False and process the envelope as a successful tool call, then have
  to parse the JSON text content to discover the real error_code. The
  bootstrap envelope is silently demoted to "yet another success
  result with weird text" by every spec-conforming MCP client.
- **Proposed fix:** change `_build_bootstrap_envelope` to construct
  and return an `mcp.types.CallToolResult` instance (the existing
  `search_papers` handler at `server/handlers/search.py:571` is the
  canonical example):
  ```python
  from mcp.types import CallToolResult, TextContent
  def _build_bootstrap_envelope(tool_name: str) -> CallToolResult:
      structured = _sort_dict({
          "corpus_version": BOOTSTRAP_CORPUS_VERSION_SENTINEL,
          "error_code": "no_notebook_selected",
          "tool": tool_name,
      })
      return CallToolResult(
          content=[TextContent(type="text",
                               text="No corpus ingested yet. ...")],
          structuredContent=structured,
          isError=True,
      )
  ```
  This puts `isError=True` at the spec-mandated top level. The
  orchestrator wrapper returns the CallToolResult; FastMCP's
  `convert_result` short-circuits at the `isinstance(result,
  CallToolResult)` branch (func_metadata.py:114-118) and passes it
  through unchanged.
- **Regression guard:** new test
  `test_bootstrap_envelope_wire_isError_is_true` that wires a
  FastMCP test instance, registers the wrapped handler, calls
  `tool_manager.call_tool(...)` with `convert_result=True`, and
  asserts that the returned object is a CallToolResult with
  `isError is True`.

### F4 — `on_success_callback` plumbing has zero test coverage

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/ingest_tracker.py:128-145,316-333 + server/main.py:526-531
- **What:** The new `on_success_callback` kwarg on
  `IngestTaskTracker.__init__` and the invocation at
  `_run_ingest_subprocess` (lines 319-328) are completely untested.
  Searching the test suite:
  ```
  $ grep -rn "on_success_callback" tests/
  (nothing — only the test_bootstrap_mode.py docstring uses the word
  "callback" generically)
  ```
  None of these claims is exercised:
  - the callback fires when `exit_code == 0`
  - the callback does NOT fire when `exit_code != 0`
  - an exception raised by the callback is logged at ERROR and NOT
    propagated (so it doesn't corrupt the ingest_status DB row or
    re-raise through the task)
  - the callback receives the correct `slug` argument
  - the closure in `server/main.py:526` actually awaits
    `resources.late_bind(config)` with the closure-captured `resources`
    and `config` (and that `resources` is the same object across calls)
- **Why it matters:** this is the load-bearing wire that makes "first
  ingest promotes the server in-process" actually work. AC6 says
  "Late-binding flips bootstrap_mode_active + sets `_corpus_ready_event`
  after first successful ingest"; the test verifies `late_bind`'s
  internals in isolation but NOT that the tracker actually invokes
  it. The implementation could silently never call the callback (e.g.
  a refactor that flips the exit_code check, or moves the call before
  the DB-update transaction so an early raise skips it) and the test
  suite would still pass.
- **Proposed fix:** add 4 tests in
  `tests/test_bootstrap_mode.py::TestOnSuccessCallback`:
  1. `test_callback_fires_on_exit_code_zero` — instantiate
     `IngestTaskTracker(on_success_callback=cb)`, drive
     `_run_ingest_subprocess` with a stubbed asyncio.subprocess that
     exits 0, assert cb was called exactly once with the slug.
  2. `test_callback_not_fired_on_nonzero_exit` — same setup with exit 1.
  3. `test_callback_exception_logged_not_propagated` — cb raises;
     assert ERROR log line and that the surrounding task completes
     normally.
  4. `test_main_closure_passes_through_to_late_bind` — patch
     `Resources.late_bind` with a recording mock, run the lifespan in
     bootstrap mode via TestClient, trigger a fake exit-0 callback
     via `app.state.ingest_tracker._on_success_callback("foo")`, and
     assert `late_bind(config)` was awaited with the same `config`
     that's on `app.state`.

### F5 — late_bind silently fails on enable_rerank=True + bootstrap path

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/resources.py:1094-1100 + server/retrieval/rerank.py:460-464
- **What:** In bootstrap mode, the startup stub never loads
  `_load_reranker_or_raise()` — `reranker_model` defaults to None
  (resources.py:333). When `late_bind` runs after first ingest, it
  constructs `RerankPhase(enabled=config.enable_rerank,
  model_handle=self.reranker_model)` (line 1094). `RerankPhase.__init__`
  raises `ValueError` when `enabled=True and model_handle is None`
  (rerank.py:460). The `except Exception` at resources.py:1125 catches
  it, logs "promotion failed", returns False. The operator's first
  successful ingest does not promote the server. Subsequent ingests
  hit the same code path and re-fail.
- **Why it matters:** operators who flip `ARXMCP_ENABLE_RERANK=true` AND
  `ARXMCP_BOOTSTRAP_MODE=1` together (a plausible-and-encouraged
  combination for "I want the good retrieval quality from day one")
  are stuck in bootstrap mode FOREVER with no diagnostic beyond a
  single ERROR-level log line buried in stderr. The "retry via another
  ingest run" advice in the docstring is wrong — every retry fails the
  same way until the operator restarts the server WITHOUT bootstrap_mode
  so the normal startup path can load the reranker model.
- **Proposed fix:** in `Resources.late_bind`, when `config.enable_rerank`
  is True AND `self.reranker_model is None`, lazily load the reranker
  in-process (mirror the eager-load at startup line 685):
  ```python
  if config.enable_rerank and self.reranker_model is None:
      from server.resources import _load_reranker_or_raise
      self.reranker_model = await _load_reranker_or_raise()
  ```
  Place this BEFORE the `RerankPhase(...)` construction. Match the
  startup branch's `_log_reranker_load(...)` and warmup behavior if
  practical; if not, at least surface a WARN log.
- **Regression guard:** new test
  `test_late_bind_with_enable_rerank_loads_reranker_lazily` that builds
  a bootstrap-mode stub, patches `_load_reranker_or_raise` to return a
  stub model, calls `late_bind`, asserts result is True and
  `self.reranker_model is not None` post-call.

### F6 — `_corpus_ready_event` is dead code (no awaiter)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/resources.py:428 (field) + 1114 (set call)
- **What:** `_corpus_ready_event: asyncio.Event` is added with a
  load-bearing-looking comment ("Preferred over Lock+flag (synthesis
  D2): the event loop is single-threaded, set() is an atomic one-way
  operation, and handlers can check `not event.is_set()` cheaply on
  the hot path without lock overhead"). `late_bind` calls
  `self._corpus_ready_event.set()` at line 1114. Grep confirms there
  are zero `_corpus_ready_event.wait()` or `_corpus_ready_event.is_set()`
  consumers in `server/` or `tests/` outside the bootstrap-mode test
  file (which only asserts the set state, never awaits). The
  orchestrator stub-check at tools.py:811 reads `bootstrap_mode_active`
  (the bool), not the event.
- **Why it matters:** the synthesis D2 reasoning was "Event over
  Lock+flag because handlers can check is_set() cheaply" — but no
  handler does this. The Event is structurally redundant. Either the
  intended consumer was forgotten (the orchestrator-level check should
  read the event, OR a `wait_for_ready` helper should exist for callers
  that want to block) OR the Event should be removed and the synthesis
  D2 rewritten to note that the bool flag is the entire mechanism.
  Dead code with a load-bearing-looking comment is a maintenance
  hazard — a future reader will assume something is awaiting the event
  and propagate the pattern.
- **Proposed fix:** EITHER
  (a) delete the field + the `set()` call + the synthesis D2 comment
      block, OR
  (b) add a `Resources.wait_for_corpus_ready(timeout: float | None = None)`
      coroutine that awaits the event, document it, and ship at least
      one in-tree consumer (e.g. a `/ui/api/bootstrap-status`
      endpoint the wizard JS polls instead of /readyz).
  (a) is the smaller change.
- **Regression guard:** if (a) — the deletion is the regression guard.
  If (b) — test `test_wait_for_corpus_ready_unblocks_after_late_bind`
  that awaits the helper with a small timeout, asserts it raises
  TimeoutError pre-late_bind, then runs late_bind in a background
  task, then awaits again and asserts it returns.

### F7 — late_bind partial-mutation leaks set_cache state on rerank-construction failure

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/resources.py:1089 (set_cache call) + 1094 (RerankPhase ctor)
- **What:** Inside `late_bind`'s try-block, the ordering is:
  1. open chunks_table
  2. build bm25_phase
  3. build ann_phase
  4. open RetrievalCache → `set_cache(retrieval_cache)` (mutates
     global module-level state at line 1089)
  5. construct RerankPhase (line 1094, can raise — see F5)
  6. in-place field assignments + `bootstrap_mode_active = False`
     + event.set() (lines 1105-1114)
  If step 5 raises (the F5 scenario), the `except Exception` at line
  1125 logs and returns False, but `set_cache(retrieval_cache)` from
  step 4 has already published a real cache into the
  `server.cache._cache_instance` module-level slot. The bootstrap
  flag stays True, so the orchestrator wrapper masks the cache from
  handlers; but anything else that reads `server.cache.get_cache()`
  (the debug endpoint at `server/routes/debug.py:58` does) will see a
  cache while the server claims to still be in bootstrap mode. The
  docstring promise that failure leaves "the stub remains active" is
  violated for the cache state.
- **Why it matters:** the inconsistency is small (debug endpoint sees a
  cache, handler path doesn't), but it makes the failure-mode reasoning
  in the docstring false-by-construction. A more defensive late_bind
  would either (a) defer `set_cache` until ALL construction succeeds,
  or (b) tear the cache back down inside the except.
- **Proposed fix:** move `set_cache(retrieval_cache)` to AFTER the
  RerankPhase construction (so it sits on line 1100 just before the
  in-place mutation block), OR inside the except, call
  `set_cache(None)` to revert the global. The first is cheaper and
  matches the "build everything, then publish atomically" principle.
- **Regression guard:** new test
  `test_late_bind_failure_does_not_leak_cache_global` that patches
  `RerankPhase.__init__` to raise, runs `late_bind`, asserts result is
  False AND `server.cache.get_cache() is None`.

### F8 — Bootstrap hint text hardcodes 127.0.0.1:7733 ignoring operator config

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/tools.py:425-427
- **What:** `_build_bootstrap_envelope` returns a text content block
  saying `"Open the operator console at http://127.0.0.1:7733/ui/ to
  create a notebook..."`. The host and port are hardcoded. The
  Config exposes `bind_host` and `bind_port` (default 127.0.0.1:7733
  but operator-configurable via `ARXMCP_BIND_HOST` /
  `ARXMCP_BIND_PORT`). An operator who flips to a non-default port
  gets misleading hint text directing them to a port the server isn't
  listening on. Same critique applies to the
  CorpusNotIngestedError hint at resources.py:471-472 ("run `make
  up-wizard`") — at least that one names a generic Makefile target
  rather than a specific URL, so it's safer.
- **Why it matters:** failure-mode UX. The bootstrap envelope is the
  PRIMARY surface the operator sees during the wizard flow. Wrong-URL
  text wastes the operator's time and erodes trust in the wizard.
- **Proposed fix:** thread `config.bind_host`/`config.bind_port` into
  `_build_bootstrap_envelope`. Cleanest: change the signature to
  `_build_bootstrap_envelope(tool_name, *, ui_url: str = "http://127.0.0.1:7733/ui/")`
  and have `_wrap_with_observability` pass
  `f"http://{r.config.bind_host}:{r.config.bind_port}/ui/"` when
  invoking. Falls back to the literal default if Resources is None.
- **Regression guard:** new test
  `test_bootstrap_envelope_text_uses_configured_bind`
  that constructs Resources with bind_port=9999 and asserts the
  envelope text contains "9999".

### F9 — Synthesis D5 ("downloading_model phase sentinel") silently dropped

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** none (the synthesis described an implementation that didn't ship)
- **What:** Synthesis §3 D3 (which is "D5 simplification" from the
  brief) committed to the **smaller** scope: "detect whether
  `~/.cache/huggingface/hub/models--BAAI--bge-m3/` exists BEFORE
  spawning the subprocess. If absent, set `phase = 'downloading_model'`
  in the existing notebook_ingest_runs row with `bytes_total = -1`
  (unknown sentinel). If present, skip the `downloading_model` phase
  entirely. ~10 LOC delta." This was the load-bearing trade-off that
  let m4 ship without full IPC byte-tracking. The implementation
  summary says "the `downloading_model` phase sentinel approach
  documented in the synthesis was also deferred since it requires
  modifying `tools/notebook_ingest.py` in ways that expand scope" —
  silently widening the deferral from "full bytes IPC" (synthesis-
  blessed) to "any progress signal at all" (NOT synthesis-blessed).
  AC7 in implementation-summary is honestly marked unmet, but the
  smaller phase-sentinel that the synthesis said WAS in scope is
  also missing, with no explicit synthesis sign-off.
- **Why it matters:** the synthesis was the contract between the
  research phase and the implementer. The implementer agreed to the
  10-LOC phase-sentinel work AND deferred only the IPC-bytes work.
  Quietly absorbing the phase-sentinel into the deferral is scope-
  slip that the synthesis did not authorize. The operator UX hit is
  small (the ingest-status endpoint shows the same `phase` string as
  before BGE-M3 loads instead of `downloading_model`), but the
  pattern — "deferral-quietly-widened-without-orchestrator-signoff" —
  is a named anti-pattern from prior milestones (see memory:
  textbook-ingest-m4 D3 synthesis-vs-impl drift).
- **Proposed fix:** EITHER ship the 10-LOC phase-sentinel as the
  synthesis specified (pre-spawn HF cache existence check in
  `tools/notebook_ingest.py` or in the tracker's start_ingest path,
  write `phase='downloading_model'` to the DB row when the cache
  dir is absent), OR explicitly amend the synthesis with a
  one-paragraph deferral rationale and surface it in the implementation
  summary so it's reviewable on its own merits.
- **Regression guard:** if the sentinel ships, test that
  `~/.cache/huggingface/hub/models--BAAI--bge-m3/` absence triggers
  `phase='downloading_model'` in the DB row, present skips it.
  If the deferral ships, no regression guard but the synthesis must
  be amended.

### F10 — Non-bootstrap startup omits explicit `bootstrap_mode_active=False`

- **Severity:** LOW
- **Source:** adversary
- **File:** server/resources.py:956-976
- **What:** The normal-boot path constructs `instance = cls(...)`
  without passing `bootstrap_mode_active=False`. It relies on the
  dataclass default (`bootstrap_mode_active: bool = False` at line
  420). This works today. But a future refactor that adds a positional
  argument between the existing positionals and `bootstrap_mode_active`
  could silently shift the default; reordering dataclass fields is
  exactly the change a future "this dataclass is getting too big, let
  me kw_only it" refactor would do. The bootstrap-stub construction
  at lines 466-477 DOES pass `bootstrap_mode_active=True` explicitly,
  which makes the asymmetry worse: a reader sees the explicit set in
  the stub path and might assume the normal path explicitly sets False
  too.
- **Why it matters:** small. Forward-compat hazard, not a current bug.
- **Proposed fix:** add `bootstrap_mode_active=False,` to the normal
  `cls(...)` construction at line 956. One-line edit. Mirror the stub
  branch for symmetry; serves as docstring-by-code.
- **Regression guard:** new test
  `test_normal_startup_sets_bootstrap_mode_active_false_explicitly`
  that builds Resources via startup and asserts
  `resources.bootstrap_mode_active is False`. (Cheap; the existing
  FM-7 test already exercises this path but doesn't check the field.)

### F11 — Late-bind first-query BGE-M3 load latency undocumented

- **Severity:** LOW
- **Source:** adversary
- **File:** server/resources.py:1014-1031 (late_bind docstring)
- **What:** In bootstrap mode, the startup stub skips the eager
  `_get_model()` / `_get_tokenizer()` calls at resources.py:677-678.
  `late_bind` itself does NOT load BGE-M3 — it only opens LanceDB,
  builds BM25/ANN/RerankPhase, opens the cache. The first MCP
  `search_papers` call after promotion triggers lazy BGE-M3 load via
  `server.query_encoder._get_model()`, which downloads ~1.5 GB on a
  fresh machine + loads ~5s on a warm cache. The docstring promise of
  "in-process promotion (no restart needed)" is technically correct
  but operationally misleading — the first post-promotion query
  blocks for 5min-on-fresh-cache (HF download) or ~5s-on-warm-cache
  (CPU load).
- **Why it matters:** operator UX. Not a bug. But the brief and the
  synthesis both stress "no restart needed" without flagging the
  hidden first-query cost. The wizard UX may need a "preparing
  retrieval" indicator the first query can hit before BGE-M3 warms.
- **Proposed fix:** add a paragraph to the `late_bind` docstring noting
  that BGE-M3 is NOT pre-loaded by late_bind; the first MCP query
  after promotion triggers lazy load (5min on cold cache). OR (better)
  add an `asyncio.create_task` at the end of late_bind that calls
  `loop.run_in_executor(None, _get_model)` to warm BGE-M3 in the
  background after promotion succeeds. Either is fine; the docstring
  fix is sufficient for LOW.
- **Regression guard:** none needed for LOW.

## What was done well

- The orchestrator-level stub-check pattern (one wrap site,
  short-circuits all 8 registered tools) is correct in principle —
  the implementer correctly identified that per-handler checks would
  miss future additions. The only registration site is
  `server/tools.py::register_all`, and every tool flows through
  `_wrap_with_observability`. Resource handlers in
  `server/mcp_resources.py` correctly are NOT stubbed because they
  read the notebooks store, not corpus_info.
- The synthesis §3 D4 deferral (ARXMCP_NOTEBOOK + BOOTSTRAP_MODE
  unsupported until m5+) is honestly documented in the implementation
  summary and the config docstring; the implementer didn't silently
  paper over the conflict.
- BP1/BP2 byte-stability is preserved AND directly guarded — the new
  `TestBP1BP2HashesUnchanged` class runs the pinned-hash test AND a
  content-substring guard against `bootstrap_mode` / `no_notebook_selected`
  appearing in any tool description. The latter is a tighter regression
  guard than the hash alone.
- The new test file `tests/test_bootstrap_mode.py` is well-organized
  with clear AC-to-test mapping in the docstring; the
  `_patch_startup_heavy_io` / `_patch_late_bind_heavy_io` helpers keep
  tests offline-fast (1.26s for 16 tests).
- `Config.bootstrap_mode: bool = False` correctly follows the
  `enable_lean` pattern with pydantic-settings auto-deriving the env
  var name from the field name + the existing `env_prefix="ARXMCP_"`.
  No `Field(...)` wrapper drift.
- The FM-7 hint-vs-override semantic (bootstrap_mode=True + existing
  corpus = silent INFO + normal boot) is correctly implemented at
  resources.py:497-504 with a clear log message, AND tested at
  `test_resources_startup_bootstrap_hint_ignored_when_corpus_exists`.
- The closure-based wiring in `server/main.py:526` captures
  `resources` after it's assigned at line 438 (and never rebound),
  so the closure is safe. Good async/closure discipline.
- The Makefile `up-wizard` target correctly uses the `ARXMCP_BOOTSTRAP_MODE=1`
  inline env-var prefix (not `export`) — the env var is scoped to
  this single invocation, not leaking into the shell. The Python-
  version preflight is preserved.
- `_build_bootstrap_envelope` correctly uses `_sort_dict` to maintain
  alphabetical key ordering, mirroring the BP1 byte-stability
  discipline used throughout the project (even though the bootstrap
  envelope isn't part of BP1, the consistency is the right reflex).
- The bootstrap envelope construction deliberately AVOIDS calling
  `envelope(...)` (which crashes on `corpus_info.version` when None) —
  the comment at tools.py:413-416 captures the reasoning. This is
  exactly the kind of defensive-by-construction pattern the cache-
  consistency discipline rewards.

## Recommended rectification order

1. **F1 (CRITICAL)** — the lifespan crash is the show-stopper. Without
   this fix, no operator can even reach the bootstrap envelope. Fix
   `refresh_metrics_from_singleton_state` to None-guard `corpus_info`
   reads. Add the lifespan smoke test. ~15 LOC + 1 test.
2. **F3 (HIGH)** — MCP-spec compliance bug. Affects every bootstrap-mode
   tool response. Change `_build_bootstrap_envelope` to return a
   `CallToolResult` instance. ~10 LOC + 1 test. Should be done IN THE
   SAME COMMIT as F1 because the smoke test from F1 will start
   exercising tool calls that need the F3 fix to actually carry
   isError correctly to the wire.
3. **F2 (HIGH)** — synthesis D1 non-implementation. /readyz returning
   503 in bootstrap mode breaks the shim+wizard flow. Add the
   `bootstrap_mode_active` branch in `readyz` and `compute_health_status`.
   ~20 LOC + 2 tests.
4. **F5 (HIGH)** — silent late_bind failure on `enable_rerank=True`.
   Lazy-load the reranker in `late_bind`. ~10 LOC + 1 test.
5. **F4 (HIGH)** — `on_success_callback` test coverage. Add the 4
   tests in `TestOnSuccessCallback`. ~120 LOC of test code; no
   production change.
6. **F7 (MEDIUM)** — `set_cache` ordering in late_bind. ~5 LOC + 1 test.
7. **F8 (MEDIUM)** — bootstrap-envelope hint URL hardcoded. ~10 LOC + 1
   test.
8. **F6 (MEDIUM)** — `_corpus_ready_event` dead code. Pick (a) deletion
   (5 LOC) or (b) `wait_for_corpus_ready` helper + one consumer (~30
   LOC + 1 test). (a) is cheaper unless the wizard JS is about to grow
   a poll endpoint anyway.
9. **F9 (MEDIUM)** — synthesis D5 phase-sentinel scope-slip. Either
   ship the 10 LOC or amend the synthesis. Reviewer's call.
10. **F10 (LOW)** — explicit `bootstrap_mode_active=False` in normal
    startup. 1 LOC + 1 test.
11. **F11 (LOW)** — late_bind first-query BGE-M3 latency docstring.
    Docstring-only.

## Rectification status (filled by Phase 4)

- F1 | CRITICAL | fixed | health.py: None-guard on corpus_info reads in refresh_metrics_from_singleton_state; main.py: skip call in bootstrap mode
- F2 | HIGH | fixed | health.py: bootstrap branch added to readyz (200 + bootstrap body) and compute_health_status (warn/200)
- F3 | HIGH | fixed | tools.py: _build_bootstrap_envelope now returns CallToolResult with isError=True at wire level
- F4 | HIGH | fixed | tests/test_bootstrap_mode.py: TestOnSuccessCallback with 4 tests covering fire/no-fire/exception/closure
- F5 | HIGH | fixed | resources.py: late_bind lazily loads reranker via _load_reranker_or_raise when enable_rerank=True + reranker_model is None
- F6 | MEDIUM | fixed | resources.py: _corpus_ready_event field and .set() call deleted; synthesis D2 updated with deferral rationale
- F7 | MEDIUM | fixed | resources.py: set_cache moved after RerankPhase construction in late_bind; TestLateBindCacheNotLeaked verifies
- F8 | MEDIUM | fixed | tools.py: _build_bootstrap_envelope accepts ui_url kwarg; _wrap_with_observability passes config.bind_host:bind_port
- F9 | MEDIUM | fixed | research-synthesis.md D3 amended with deferral paragraph for phase-sentinel scope-slip
- F10 | LOW | deferred | orchestrator will record under deferred_findings in state.json
- F11 | LOW | deferred | orchestrator will record under deferred_findings in state.json
