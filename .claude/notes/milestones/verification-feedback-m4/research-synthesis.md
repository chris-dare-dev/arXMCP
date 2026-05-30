# Research Synthesis — verification-feedback-m4

**Merged from:** research-brief-1.md (seam map + FastMCP introspection + BP1
proof path) + research-brief-2.md (MCP-spec MUST clauses + 9 failure modes +
PII / cancellation / disconnect).
**Generated:** 2026-05-30.
**Verdict:** INLINE, ~1 handler-file edit + 1 import + ~25 LOC + new test file.
Purely local. 0 open questions. 0 external writes. Both briefs concur on EVERY
load-bearing fact; two design divergences resolved in §3.

## 1. The locked design

Add **only** the `lean_verify` handler signature change + a heartbeat task. The
seven other handlers are untouched (their AC "unchanged in behavior" is
satisfied trivially). BP1/BP2 hashes (`EXPECTED_TOOL_SCHEMA_SHA256`,
`EXPECTED_BP1_SHA256`) STAY FROZEN; `TOOL_SCHEMA_VERSION` STAYS AT 16. No
`server/tools.py` `ToolMeta` change; no `server/prompts.py` change.

**File deltas (~5 edits, ~25 LOC):**

- **`server/handlers/lean_verify.py`** — (a) `from mcp.server.fastmcp import Context`
  added at top; (b) new optional last parameter on `handle_lean_verify`:
  `ctx: Context | None = None` (§3 D2); (c) heartbeat-task block wrapping the
  `resp = await lean_repl.query({"cmd": cmd})` call (§3 D1); (d) no other behavior
  change — every existing `try/except LeanReplTimeoutError`/`LeanReplError` path
  preserved verbatim.
- **`tests/test_handlers_lean_verify.py`** (or new `tests/test_lean_verify_progress.py`) —
  new tests for: (1) `ctx is None` path → no emissions, query still works
  (back-compat for existing direct-call sites); (2) `ctx` with mocked
  `report_progress` + a `_FakeLeanRepl` whose `query` sleeps >3 s → at least one
  emission captured; (3) FM-3: heartbeat task is cancelled after the result
  (no emissions after `query` returns); (4) FM-7: heartbeat task is cancelled on
  exception (LeanReplTimeoutError raised mid-await).
- **`server/tools.py`** — UNCHANGED. (FastMCP's `find_context_parameter` walks
  the wrapped handler's type hints via `inspect.signature` → `__wrapped__`, which
  `_wrap_with_observability` preserves via `@functools.wraps`. The `ctx` param is
  auto-injected by FastMCP and auto-excluded from `inputSchema` via `skip_names`.)

## 2. Load-bearing facts (both briefs)

- **MCP spec 2025-06-18 — the AC-2 "vacuously satisfied" rule (R2 FM-1, LOAD-BEARING).**
  The spec MUST: "Progress notifications MUST only reference tokens that were
  provided in an active request" and "Receivers of progress requests MAY choose
  not to send any progress notifications" — if the client omits
  `_meta.progressToken` on the `tools/call` request, the server MUST NOT emit.
  `Context.report_progress` (FastMCP installed source, mcp==1.27.1,
  `.venv/.../mcp/server/fastmcp/server.py:1162`) implements this: `if
  progress_token is None: return`. **Test consequence:** the test MUST mock
  `request_context.meta.progressToken` to a non-None value (e.g., `"test-tok"`)
  to actually exercise the emission path. A test that does not mock the token
  only verifies no-op behavior.
- **MCP spec monotonicity MUST (R2):** "The progress value MUST increase with
  each notification, even if the total is unknown." Concrete: single heartbeat
  task with a single counter incremented inside it — no shared mutable state,
  no concurrent emitters.
- **MCP spec post-completion MUST (R2):** "Progress notifications MUST stop
  after completion." Concrete: heartbeat task cancelled in `finally`,
  awaited with `return_exceptions=True` (or CancelledError-suppressed).
- **FastMCP `Context.report_progress` (R1+R2, live-verified mcp==1.27.1):**
  `async def report_progress(self, progress: float, total: float | None = None,
  message: str | None = None) -> None`. Silent no-op when no progressToken;
  no exception raised in that path. Transport: SSE channel on the active
  Streamable HTTP session via `send_progress_notification`.
- **The BP1 byte-stability mechanism (R1 cardinal correctness point).**
  FastMCP `Tool.from_function` (`.venv/.../mcp/server/fastmcp/tools/base.py:57-91`):
  `context_kwarg = find_context_parameter(fn)` → `skip_names=[context_kwarg]` →
  excluded from `arg_model.model_json_schema(by_alias=True)`. The `ctx: Context`
  parameter is therefore NEVER in the tool's `inputSchema`. The
  `_wrap_with_observability` wrapper in `server/tools.py:688-799` uses
  `@functools.wraps(handler)` which sets `__wrapped__`; Python 3.12
  `inspect.signature(func, eval_str=True)` follows `__wrapped__` by default →
  the wrapper is transparent to Context injection. **No `Annotated` marker, no
  special decorator needed — the literal annotation `Context` is sufficient.**
- **Current handlers + call site (R1, verbatim from source):**
  `handle_lean_verify(snippet, imports, mode) -> dict[str, Any]`
  (`server/handlers/lean_verify.py:268-304`). The 5–30 s await is a SINGLE call:
  `resp = await lean_repl.query({"cmd": cmd})` at line 337. `lean_repl.query`
  internally uses `asyncio.wait_for(self._round_trip(command), timeout=30.0)`
  inside `_io_lock` (`server/lean_repl.py:282-300`).
- **BP1/BP2 hashes (R1, verbatim):** `EXPECTED_TOOL_SCHEMA_SHA256` =
  `"c7df4c5c10c86693ac8553b7d079b55fba21749881c233f0f298955379d13375"`
  (`tests/test_server_tool_schema.py:95`); `EXPECTED_BP1_SHA256` =
  `"483344e3fcdea1d64de893cc669c9f142fd6f1198d4c8d383cd9c232558959bc"`
  (`tests/test_prompts.py:649`). The implementer verifies with
  `uv run python -m pytest tests/test_server_tool_schema.py tests/test_prompts.py --tb=short`
  and asserts both unchanged. **`TOOL_SCHEMA_VERSION=16` MUST NOT be bumped.**

## 3. Divergences resolved (orchestrator synthesis note)

**D1 — heartbeat-task topology. RESOLVED → R1's single-heartbeat-task pattern
(Lean call stays on main coroutine).** R2 proposes `asyncio.create_task` for
BOTH the Lean query AND the heartbeat, joined by `asyncio.wait(..., FIRST_COMPLETED)`,
with the Lean exception re-raised via `lean_task.exception()`. R1 proposes only
the heartbeat as a task; the Lean call remains a plain `await
lean_repl.query(...)` inside `try/finally`. **Pick R1.** Reasoning: (i) the
event loop interleaves a `await lean_repl.query(...)` and a separately-scheduled
`heartbeat_task` exactly as well as it interleaves two tasks — R2's stated
"neither can stall the other" advantage does not exist (only the heartbeat
needs to be a separate task for non-blocking concurrency); (ii) R2's pattern
forces a SUBSTANTIAL restructure of the existing m3 `try/except
LeanReplTimeoutError` / `try/except LeanReplError` blocks — the exception must
now propagate through `lean_task.result()` instead of directly from `await
lean_repl.query(...)`, which is a regression-risk surface in the most
security-sensitive handler in the codebase; (iii) R1's pattern preserves m3's
timeout-kill-respawn logic verbatim. Concrete shape:

```python
async def _heartbeat(ctx: Context, total_s: float = 30.0):
    elapsed = 0.0
    interval = 3.0
    try:
        while True:
            await asyncio.sleep(interval)
            elapsed += interval
            pct = min(elapsed / total_s, 0.95)
            try:
                await ctx.report_progress(
                    pct,
                    total=1.0,
                    message=f"Lean elaboration running — {elapsed:.0f}s elapsed",
                )
            except Exception:
                # FM-2: client disconnect — never propagate to handler
                pass
    except asyncio.CancelledError:
        raise

# inside handle_lean_verify, replacing the bare `resp = await lean_repl.query(...)`:
heartbeat_task: asyncio.Task[None] | None = None
if ctx is not None:
    heartbeat_task = asyncio.create_task(_heartbeat(ctx))
try:
    resp = await lean_repl.query({"cmd": cmd})
finally:
    if heartbeat_task is not None:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
```

The `try/except LeanReplTimeoutError` and `try/except LeanReplError` blocks
that wrap this `try/finally` from m3 are UNCHANGED — the `finally` runs before
the outer exception handlers see the exception, so the heartbeat is cancelled
regardless of how `query` exits (FM-3 + FM-7 covered by one structure).

**D2 — `ctx` parameter default. RESOLVED → R1's `ctx: Context | None = None`
(optional, defaults to None).** R2's signature is `ctx: Context` (no default).
**Pick R1.** Reasoning: the existing `tests/test_handlers_lean_verify.py` test
suite calls the handler directly via `asyncio.run(handle_lean_verify(snippet=...))`
WITHOUT a `ctx` argument. A non-optional `ctx` parameter would break every
existing test as a TypeError ("missing 1 required positional argument: 'ctx'").
R1's pattern keeps backward compatibility AND lets FastMCP inject `ctx` at
runtime (when annotated `Context`, FastMCP injects regardless of whether a
default is present). The heartbeat path is gated `if ctx is not None`, so the
None path skips emission cleanly.

## 4. Failure modes → required handling (R2's enumeration)

- **FM-1 No client progressToken:** `Context.report_progress` no-ops; AC-2 is
  vacuously satisfied. Tests MUST mock a progressToken to exercise emission.
- **FM-2 Client disconnects mid-emission:** wrap `report_progress` in
  `try/except Exception: pass` inside the heartbeat loop — never propagate
  transport errors to the handler / abort the REPL query.
- **FM-3 Heartbeat task leak (notifications after completion):** `finally`
  block cancels + awaits heartbeat with `CancelledError` suppressed. Spec MUST.
- **FM-4 Non-monotonic progress:** single heartbeat task, single local
  `elapsed` counter, no shared mutable state. Spec MUST.
- **FM-5 Heartbeat stalls Lean wait:** heartbeat is a separate task →
  asyncio interleaves naturally; no event-loop blocking.
- **FM-6 SSE flooding:** 3 s heartbeat interval (5–10 emissions per 30 s call)
  satisfies spec SHOULD on rate-limiting.
- **FM-7 Lean raises before first heartbeat tick:** same `try/finally`
  structure covers; the m3 timeout-kill-respawn is preserved verbatim.
- **FM-8 BP1 cache regression from ctx in `inputSchema`:** the import must be
  EXACTLY `from mcp.server.fastmcp import Context` and the annotation must be
  literally `Context` (or `Context | None`). The existing
  `test_lean_verify_in_all_tools` + `EXPECTED_TOOL_SCHEMA_SHA256` test is the
  catch-net. If the hash drifts, FastMCP isn't excluding the param → bug.
- **FM-9 Progress messages leak Lean source (PII):** message field STRICTLY
  duration-only — `f"Lean elaboration running — {elapsed:.0f}s elapsed"`.
  Never `snippet`, `cmd`, or REPL response text.

Add a structured INFO log alongside each heartbeat emission (R2's
cross-check (d)): `logger.info("lean_verify: progress heartbeat",
extra={"elapsed_s": elapsed})`. NEVER log `snippet` at INFO (DEBUG only, per
`08-security-observability-ops.md` §Logging).

## 5. Acceptance criteria

1. `handle_lean_verify` has `ctx: Context | None = None` added as last
   parameter; the 7 other handlers are unchanged.
2. Given a `lean_verify` call with a mocked `progressToken` whose REPL `query`
   sleeps > 3 s, when the call runs, then ≥ 1 `ctx.report_progress` invocation
   is captured before the result returns.
3. `EXPECTED_TOOL_SCHEMA_SHA256` (`tests/test_server_tool_schema.py:95`) and
   `EXPECTED_BP1_SHA256` (`tests/test_prompts.py:649`) are UNCHANGED.
   `TOOL_SCHEMA_VERSION` stays at 16.
4. Given `ctx is None` (existing direct-call test sites), when the handler
   runs, then no emissions, no task spawned, query returns normally.
5. Given a `query` that raises `LeanReplTimeoutError` or `LeanReplError`
   mid-await, when the handler runs, then the heartbeat task is cancelled
   (no leaked emissions after the exception) — explicit regression tests for
   both exception types.
6. Given a `query` that succeeds, when the handler returns the result, then
   the heartbeat task is cancelled before the result is returned (no
   post-completion emissions).
7. Progress `message` field contains ONLY duration/elapsed text — explicit
   test that `snippet`/`cmd` substrings do NOT appear in any captured emission.
8. `make test` green, `ruff check .` clean.

## 6. Implementation order

1. `server/handlers/lean_verify.py` — import `Context`, add `ctx` param,
   define `_heartbeat` helper, wrap `lean_repl.query` call in
   `try/finally` heartbeat-task structure. Touch ~20 LOC.
2. Tests: AC-2, AC-4, AC-5 (both exception types), AC-6, AC-7. Either extend
   `tests/test_handlers_lean_verify.py` or new
   `tests/test_lean_verify_progress.py`. Use `MagicMock(spec=Context)` /
   `AsyncMock` for `ctx.report_progress`; `_FakeLeanRepl` with
   `asyncio.sleep(3.2)` for the >3 s case.
3. Run `uv run python -m pytest tests/test_server_tool_schema.py
   tests/test_prompts.py --tb=short` to confirm AC-3 hashes unchanged.
4. Run `make test` for green pass.

## 7. Open questions

**None.** Both briefs reported "No open questions." Both design divergences
(D1 heartbeat topology, D2 ctx default) resolved above.

## 8. External writes required

**None.** Purely local. Both briefs concur.
