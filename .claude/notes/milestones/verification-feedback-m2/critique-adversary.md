# Critique — verification-feedback-m2

**Critic:** adversary
**Generated:** 2026-05-22T00:00:00Z
**Commit range:** d9af59db4c3019194b77df42c7b328ae93ea8f0e..c9df7f1
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the harness is well-built and the four declared deviations are sound, but the `enable_lean=true` startup path leaks already-loaded resources when the Lean spawn fails, because step 6e raises before the `Resources` instance is constructed.
- Finding counts: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 2 LOW.
- Highest-risk file:line — `server/resources.py:644-657` (Lean spawn placed after every other resource is warm; `LeanUnavailableError` leaks BGE-M3 + LanceDB + cache + SQLite handles).
- Cache byte-stability (Axis 1) is clean: no `server/tools.py` / `server/prompts.py` change, no MCP tool added, schema hash untouched — correct, since m2 is the harness only and `lean_verify` is m3.
- Security (Axis 3): the sandbox doc is thorough and the gating mirrors `enable_rerank` correctly, but the deferred `RLIMIT_AS` cap (D4) leaves a runaway-elaboration memory exhaustion unguarded except by a 30 s wall-clock timeout — acceptable for a harness, flagged MEDIUM as a latent foot-gun.
- Test surface (Axis 8): Tier-1 always-run tests are solid; the `query`/`_round_trip`/`close`-escalation logic is only covered by `@requires_lean_repl` tests that skip on this and every CI workstation — the timeout, EOF, and non-JSON paths have zero always-run coverage.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Lean spawn failure leaks BGE-M3 / LanceDB / cache handles

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/resources.py:644-657
- **What:** Step 6e runs `lean_repl = await LeanRepl.spawn_from_config(config)` after every other resource (BGE-M3 model, LanceDB chunks table, retrieval cache singleton, theorem-names SQLite store) is already loaded and warm, but BEFORE the `instance = cls(...)` constructor at line 658. If `enable_lean=true` and the toolchain is unresolvable, `LeanUnavailableError` propagates out of `Resources.startup`; the `Resources` object is never constructed, so `Resources.shutdown` is never called and the BGE-M3 weights (~1.5 GB), the LanceDB connection, the open `RetrievalCache` SQLite file, and the theorem-names SQLite store are all leaked.
- **Why it matters:** Under `docker restart: on-failure` or a systemd restart loop, an operator who set `enable_lean=true` with a broken `ARXMCP_LAKE_PATH` gets a tight crash loop that leaks ~1.5 GB of BGE-M3 weights and an open SQLite WAL handle on every iteration. The implementer's own summary (referencing "m7 rect F2") shows this exact leak class was previously fixed for `NotebooksStore` by moving the open inside a try/finally — m2 reintroduces the pattern for the Lean spawn. The fail-loud contract is correct; the resource hygiene around it is not.
- **Proposed fix:** In `server/resources.py`, wrap the step-6e spawn so a failure tears down what is already warm before re-raising. Minimal form: `try: lean_repl = await LeanRepl.spawn_from_config(config) except Exception: await query_encoder.shutdown_executor(wait=False); <best-effort close cache + theorem_names_db>; raise`. Cleaner: construct the `Resources` instance with `lean_repl=None` first, then spawn and assign, so the existing `lifespan` finally-block / `Resources.shutdown` owns teardown. Note this is a worsening of a pre-existing latent pattern (steps 1–6d have the same leak-on-later-failure shape), but 6e is the only step that can fail on pure operator misconfiguration with all prior resources already warm.
- **Regression guard:** Add an always-run test: monkeypatch `LeanRepl.spawn_from_config` to raise `LeanUnavailableError`, call `Resources.startup` with `enable_lean=True` and a stub corpus, assert it raises AND assert `server.query_encoder` executor / cache singleton were torn down (e.g. `get_cache() is None`).

### F2 — query/round-trip/close logic has zero always-run test coverage

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_lean_repl.py:104-182
- **What:** Every test that exercises `LeanRepl.query`, `_round_trip`, the timeout path, the EOF-before-response path, the non-JSON-response path, and the `close()` terminate→wait→kill escalation is inside `class TestRealLeanRepl`, decorated `@_lean_skip` + `@pytest.mark.requires_lean_repl`. `_lean_skip` skips unless both `ARXMCP_LAKE_PATH` and `ARXMCP_LEAN_REPL_DIR` are set — i.e. it skips on every CI/dev workstation without a Lean install. The Tier-1 always-run tests only cover Config defaults and the four `spawn`-time fail-loud branches.
- **Why it matters:** ~130 of the 291 lines in `server/lean_repl.py` (the entire `query` / `_round_trip` / `close` surface, including the sandbox-critical timeout guard and the kill-escalation) have no test that runs in the default `make test` invocation. The brief's Axis-8 expectation is "every new code path covered by at least one test." A regression in the timeout wrapper or the blank-line framing protocol would ship green. These paths are subprocess-IO but are trivially testable with a fake/stub process — no real Lean needed.
- **Proposed fix:** Add always-run tests in `tests/test_lean_repl.py` that drive `query` / `_round_trip` / `close` against a substitute process. Either (a) spawn a tiny Python helper subprocess that echoes a canned JSON-block + blank-line response, exercises the timeout (sleep-forever), EOF (exit immediately), and non-JSON (print garbage) cases; or (b) inject a fake object with `stdin`/`stdout`/`returncode`/`terminate`/`kill`/`wait` into `LeanRepl.__init__` directly. This validates the framing protocol and the timeout/escalation logic without a Lean toolchain.
- **Regression guard:** The added tests ARE the regression guard — at minimum: `query` timeout raises `LeanReplError` matching "timeout"; `_round_trip` on premature EOF raises `LeanReplError` matching "closed stdout"; `close()` escalates to `kill()` when `wait()` exceeds `_CLOSE_GRACE_S`.

### F3 — `_round_trip` can deadlock on a multi-line JSON response with no blank-line terminator

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/lean_repl.py:198-219
- **What:** `_round_trip` reads stdout line-by-line and treats a blank line *after* content as end-of-block. The docstring asserts the REPL protocol is "a JSON object terminated by a blank line on stdout." If the real REPL ever emits a JSON response that is NOT followed by a trailing blank line (e.g. a single-line `{...}\n` with no `\n\n`, or an unterminated final response), the `while True` loop blocks on `await stdout.readline()` indefinitely until the outer `asyncio.wait_for` timeout in `query` fires 30 s later. The blank-line framing assumption rests entirely on spike-2 observation, not a documented REPL guarantee.
- **Why it matters:** A protocol-framing mismatch turns every query into a 30 s hang rather than a fast clear error. The 30 s timeout does bound it (so this is not a true deadlock — hence MEDIUM not HIGH), but a harness whose happy path can silently degrade to 30 s/query on a REPL-version change is a latent foot-gun. The spike validated one REPL build; the operator points `ARXMCP_LEAN_REPL_DIR` at their own build, which may differ.
- **Proposed fix:** Either (a) document explicitly in `server/lean_repl.py` and `.claude/docs/lean-sandbox-design.md` that the harness depends on the `repl` build emitting the blank-line terminator, and pin/record the validated `leanprover-community/repl` commit in spike-2; or (b) make `_round_trip` resilient — attempt `json.loads` on the accumulated buffer after each non-blank line and return on the first successful parse, so a missing terminator does not hang. Option (b) is more robust and small.
- **Regression guard:** Add an always-run test (per F2's harness): a fake process that emits `{...}\n` with NO trailing blank line — assert `query` returns within the timeout, not after it.

### F4 — runaway-elaboration memory exhaustion is unguarded (RLIMIT_AS deferred)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** .claude/docs/lean-sandbox-design.md:31
- **What:** Declared deviation D4: the hard address-space cap (`RLIMIT_AS` via `preexec_fn` on POSIX) is documented in the sandbox design but not implemented. The only implemented resource guard is the 30 s `asyncio.wait_for` per-query timeout. The sandbox doc's own threat surface (line 14-20) explicitly names "allocate unbounded memory" as an attack the REPL must be bounded against.
- **Why it matters:** Lean's elaborator is Turing-complete metaprogramming; a snippet can allocate gigabytes within the 30 s window before the timeout fires. On a constrained single workstation (the project's hard local-first constraint), that can OOM-kill the whole `arxmcp-server` process, not just the REPL child. The wall-clock timeout does not bound memory. The D4 rationale (mirrors E13_S03 deferring the LaTeXML Docker cap) is reasonable for a *harness* that is gated OFF by default and exercises no agent-supplied input in m2 — hence MEDIUM, not HIGH — but it must be a tracked, non-silent deferral.
- **Proposed fix:** Acceptable to defer to m3 as documented, but: (1) ensure the m3 brief (`lean_verify` tool) carries `RLIMIT_AS` as an explicit acceptance criterion, since m3 is where agent-supplied Lean source first reaches `query`; (2) the POSIX `preexec_fn` + `resource.setrlimit(RLIMIT_AS, ...)` form is ~10 LOC and could land in m2's `LeanRepl.spawn` now (Windows path stays deferred). If Phase 4 has budget, implement the POSIX half here; otherwise confirm the m3 brief blocks on it.
- **Regression guard:** (m3) A `@requires_lean_repl` test submitting a high-allocation snippet asserts the REPL is killed/bounded rather than the parent OOMing; (m2, if POSIX cap landed) assert `spawn` sets the rlimit via the preexec hook.

### F5 — `close()` after a `kill()` escalation can hang on the unbounded final `wait()`

- **Severity:** MEDIUM
- **Source:** server/lean_repl.py:283
- **File:** server/lean_repl.py:283
- **What:** In `close()`, after the `terminate()` grace period expires and the code escalates to `self._proc.kill()`, the final reap is a bare `await self._proc.wait()` with no `asyncio.wait_for` bound. Every other wait in this module is timeout-bounded. If `kill()` does not actually reap the process (a defunct child whose parent-side transport is wedged, or a Windows handle edge case), `close()` hangs forever.
- **Why it matters:** `close()` is called from `Resources.shutdown`, which the lifespan wraps in `asyncio.wait_for(..., timeout=30.0)` — so the outer 30 s budget does bound it, and the `Resources.shutdown` caller swallows the exception. So this is contained (MEDIUM, not HIGH), but it burns the entire 30 s shutdown drain on a single wedged child and the comment "escalates to kill()" implies a guaranteed reap that the code does not actually guarantee.
- **Proposed fix:** Bound the post-kill reap: `await asyncio.wait_for(self._proc.wait(), timeout=_CLOSE_GRACE_S)` wrapped in a `try/except TimeoutError` that logs and returns. `SIGKILL` is uninterceptable so a short bound is safe.
- **Regression guard:** Always-run test (per F2 harness): fake process whose `wait()` never resolves even after `kill()` — assert `close()` returns within ~`_CLOSE_GRACE_S`, not unbounded.

### F6 — `_LAKE_PATH` / `_REPL_DIR` env vars read once at module import time

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_lean_repl.py:30-36
- **What:** `_LAKE_PATH`, `_REPL_DIR`, and `_LEAN_AVAILABLE` are evaluated at module import time via `os.environ.get`. A test or fixture that sets these env vars after import (e.g. via `monkeypatch.setenv`) will not flip the `_lean_skip` decision, since the `skipif` condition was already frozen.
- **Why it matters:** Purely a test-author foot-gun, not a product bug. It matches the existing `requires_model` / `ARXMCP_RUN_REAL_BGE_RERANKER` pattern (D3 explicitly cites it), so it is consistent — flagged LOW for completeness only.
- **Proposed fix:** None required; optionally a one-line comment noting the env vars must be set before pytest collection. Defer.
- **Regression guard:** n/a (LOW).

### F7 — dead `lean_repl` local initializer in step 6e

- **Severity:** LOW
- **Source:** adversary
- **File:** server/resources.py:643
- **What:** `lean_repl: Any | None = None` is declared, then immediately overwritten inside `if config.enable_lean:` with the spawn result. The pre-initializer only matters for the `enable_lean=False` branch, which is correct — but combined with the `lean_repl: Any | None = None` dataclass field default at line 264, the local is mildly redundant. Minor.
- **Why it matters:** Style only; the code is correct. Calling it out so the open-scan dead-code check is explicit.
- **Proposed fix:** Leave as-is (the local is needed to pass `lean_repl=lean_repl` into the constructor on both branches). Defer — no change recommended.
- **Regression guard:** n/a (LOW).

## What was done well

- The `enable_lean` gate is a faithful mirror of the established `enable_rerank` precedent: default OFF, fail-loud on operator opt-in with a broken toolchain, `LeanUnavailableError` correctly subclasses `ResourceStartupError` so the lifespan's broad-except FATAL path catches it.
- `asyncio.create_subprocess_exec` is used correctly — non-blocking spawn, no event-loop-blocking startup path, no synchronous subprocess call; the pure-ASGI / no-cold-start-race constraint from AC2 is genuinely met.
- The four deviations (D1–D4) are all declared, each with a sound rationale; D1 (lifecycle in `Resources` not literally `main.py`) and D2 (three Config fields not one) are correct reads of the codebase's actual structure.
- The banned-pattern checklist is clean: no `assert` for invariants (the code explicitly notes the ban at line 205-206 and raises `LeanReplError` instead), no `BaseHTTPMiddleware`, no `import anthropic`, no `claude-opus` string, no fork, no `0.0.0.0` bind, no `latest` tag, no `git`/`gh` mutation, `KMP_DUPLICATE_LIB_OK` untouched.
- `stderr=DEVNULL` is a genuine and correctly-reasoned sandbox decision — it removes the pipe-buffer deadlock where a large diagnostic write blocks the child while the parent reads only stdout.
- The `_io_lock` serialization of `query` round-trips correctly prevents two concurrent queries from interleaving JSON on the single stdin/stdout stream — a real race the implementer anticipated.
- `close()` is idempotent, exception-safe, and reaps the child (`terminate` → bounded `wait` → `kill` fallback); the comment correctly notes an unreaped child is a zombie/leaked-handle.
- The sandbox sub-design doc (`.claude/docs/lean-sandbox-design.md`) is genuinely one page, correctly placed under `.claude/docs/`, models E13_S03, and is honest about what is implemented vs deferred (the guard table's "m2 status" column).
- Cache byte-stability is correctly preserved: no MCP tool added, `server/tools.py` and `server/prompts.py` untouched, `EXPECTED_TOOL_SCHEMA_SHA256` correctly NOT re-pinned (there is nothing to re-pin) — the implementer understood that m2 is harness-only.
- The `requires_lean_repl` marker is registered in `pyproject.toml` with a thorough description, and the Tier-1 fail-loud tests (`TestFailLoudContract`) cover all four `spawn`-time error branches with `pytest.raises` + `match=`.

## Recommended rectification order

1. F1 — wrap step-6e spawn so a Lean failure tears down already-warm resources before re-raising. Highest blast radius (crash-loop resource leak); ~10-15 LOC.
2. F2 — add always-run tests for `query` / `_round_trip` / `close` via a fake/stub process. Unblocks coverage for F3 and F5's regression guards too.
3. F5 — bound the post-`kill()` reap with `asyncio.wait_for`. ~3 LOC; small and self-contained.
4. F3 — make `_round_trip` resilient to a missing blank-line terminator (or pin the validated repl commit in spike-2 + document the dependency). ~5-10 LOC.
5. F4 — confirm the m3 brief carries `RLIMIT_AS` as an acceptance criterion; optionally land the POSIX `preexec_fn` half in m2.
6. F6, F7 — LOW; defer.

## Rectification status (filled by Phase 4)

Rect commit closes F1–F5; F6–F7 deferred (LOW). Zero findings invalidated
on the Phase-4 re-verify gate — every cited `file:line` still matched the
diff (0% invalidation rate, well under the 40% heuristic).

- F1 (HIGH) — **fixed** in `server/resources.py`: the step-6e Lean spawn now
  runs AFTER the `Resources` constructor; a spawn failure calls
  `instance.shutdown()` (tearing down BGE-M3, LanceDB, cache, theorem-names
  SQLite) before re-raising. Regression guard:
  `tests/test_server_startup.py::TestStartupRefusals::test_enable_lean_spawn_failure_tears_down_resources`
  — monkeypatches `LeanRepl.spawn_from_config` to raise, asserts
  `Resources.startup` re-raises AND `get_cache() is None` (teardown ran).
- F2 (MEDIUM) — **fixed**: a fake-subprocess test harness gives the
  `query` / `_round_trip` / `close` surface always-run coverage with no
  Lean toolchain. Regression guard: the new
  `tests/test_lean_repl.py::TestFakeProcRoundTrips` class (9 tests covering
  parse, missing-terminator, timeout, EOF, non-JSON, exited-process, reap,
  kill-escalation).
- F3 (MEDIUM) — **fixed** in `server/lean_repl.py::_round_trip`: the reader
  attempts `json.loads` after each non-blank line and returns on the first
  successful parse, so a REPL build that omits the trailing blank-line
  terminator no longer hangs to the 30 s timeout. Regression guard:
  `TestFakeProcRoundTrips::test_query_returns_without_trailing_blank_line`.
- F4 (MEDIUM) — **addressed by tracking**: the `RLIMIT_AS` memory cap stays
  deferred for the m2 harness (gated OFF by default; no agent-supplied input
  reaches `query` in m2), but is now an explicit acceptance criterion on the
  m3 brief in `plans/verification-feedback-roadmap.md` — m3 is where
  agent-authored Lean source first reaches `LeanRepl.query`. The critic's
  preferred outcome (the deferral must be tracked and non-silent) is met.
- F5 (MEDIUM) — **fixed** in `server/lean_repl.py::close`: the post-`kill()`
  reap is now `asyncio.wait_for`-bounded by `_CLOSE_GRACE_S`, so `close()`
  cannot hang the lifespan shutdown drain on a wedged transport. Regression
  guard: `TestFakeProcRoundTrips::test_close_escalates_to_kill_and_stays_bounded`.
- F6 (LOW) — **deferred**: `_LAKE_PATH`/`_REPL_DIR` read at import time.
  A test-author foot-gun only; consistent with the existing
  `requires_model` / `ARXMCP_RUN_REAL_BGE_RERANKER` pattern. Per the
  rectify policy LOW findings are deferred.
- F7 (LOW) — **deferred**: the `lean_repl` local initializer in step 6e is
  mildly redundant. The critic itself recommended "no change"; deferred.
