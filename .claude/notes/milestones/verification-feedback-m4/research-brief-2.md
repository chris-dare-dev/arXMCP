# Research Brief — verification-feedback-m4

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-30T00:00:00Z

---

## In-codebase context

### Design constitution touchpoints

**`06-mcp-server-design.md` — no protocol-level streaming of tool results:**
> "No protocol-level streaming of tool results. `notifications/progress` is a
> heartbeat, not a partial-result channel. A `tools/call` returns exactly one `result`."

This is load-bearing: progress notifications are fire-and-forget heartbeats emitted
WHILE the single `tools/call` response is pending. They do NOT deliver partial results.

**`06-mcp-server-design.md` — ContextVar vs FastMCP Context:**
`server/middleware.py:1427–1434` states verbatim:
> "**Why a ContextVar over a FastMCP `Context` parameter:** Today no handler signature
> takes a `Context` arg and threading one through would touch all 7 handlers + risk a
> TOOL_SCHEMA_VERSION bump if FastMCP exposes it on the wire. A ContextVar is
> single-chokepoint, asyncio-safe…"

**CONFLICT FLAG — the milestone brief vs this note:**
The milestone AC says "Handler signatures and the `server/tools.py` registration
wiring are updated to pass `ctx: Context`; the 7 existing handlers are unchanged in
behavior." The TracingContextMiddleware docstring is an explicit prior decision arguing
AGAINST threading `Context` through all handlers. Resolution: the AC does NOT require
adding `ctx` to all 7 existing handlers. Only `handle_lean_verify` needs it. The
phrase "7 existing handlers are unchanged in behavior" means behavior is unchanged —
their signatures remain unchanged. Only the lean_verify handler gets `ctx`.

**`07-multi-agent-caching.md` — BP1 byte-stability:**
> "Cache key is the hash of the exact prefix bytes including system prompt, tool
> definitions, and prior turns up to the breakpoint. Any whitespace or ordering
> change invalidates."

The `ctx: Context` parameter must NOT appear in the tool's `inputSchema`. FastMCP
reflects handler parameters into `inputSchema` only for non-`Context` typed args.
The `Context` type is explicitly excluded by FastMCP — confirmed in the installed
source (mcp==1.27.1): `Context` injection is handled via type-annotation introspection,
not as an input field. EXPECTED_TOOL_SCHEMA_SHA256 is therefore UNCHANGED.

**`server/handlers/lean_verify.py` — current handler shape:**
`handle_lean_verify` has no `ctx` parameter. It is `async def handle_lean_verify(snippet, imports, mode)`.
The Lean REPL call is at line 337: `resp = await lean_repl.query({"cmd": cmd})`.
This is the 5–30s blocking await. Progress notifications must be emitted DURING this
await — which requires a concurrent heartbeat task, not sequential emissions.

**Existing test harness (`tests/test_handlers_lean_verify.py`):**
The `_FakeLeanRepl` class captures `.commands` and supports `raise_with` injection.
The `_attach_fake_resources` helper + `set_resources` / `reset_resources_for_tests`
pattern is the established fixture approach. No `Context` is currently in any test.

---

## Prior decisions and lessons

Recent git log shows `verification-feedback-m3` is complete (commit `bfeabdf`).
m3 adversary found 8 findings, all fixed. m3 introduced `handle_lean_verify` with
timeout kill+respawn pattern (FM-2 in m3 synthesis), severity clamping, position
normalization.

Key prior decision from m3 synthesis: the handler uses a `try/except LeanReplTimeoutError`
that closes and respawns the REPL. Any heartbeat task spawned before `lean_repl.query()`
MUST be cancelled in the SAME `try/finally` block — not only in the success path.

**`agent-conventions.md §4` banned patterns to watch:**
- `assert` for invariants — use `if … raise RuntimeError(…)`
- `BaseHTTPMiddleware` — banned
- Adding `ctx` to `inputSchema` would be an indirect BP1 cache regression

---

## External sources

### MCP spec 2025-06-18 — `notifications/progress`
Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/progress

Verbatim MUST/SHOULD clauses:

> "Progress tokens **MUST** be a string or integer value"
> "Progress tokens can be chosen by the sender using any means, but **MUST** be unique
> across all active requests."

Client binding (the `_meta.progressToken` field):
> "When a party wants to *receive* progress updates for a request, it includes a
> `progressToken` in the request metadata."

The shape of the notification:
> "The receiver **MAY** then send progress notifications containing:
> * The original progress token
> * The current progress value so far
> * An optional 'total' value
> * An optional 'message' value"

Monotonicity MUST:
> "The `progress` value **MUST** increase with each notification, even if the total
> is unknown."

Optional fields:
> "The `progress` and the `total` values **MAY** be floating point."
> "The `message` field **SHOULD** provide relevant human readable progress information."

Behavior when no progressToken:
> "Progress notifications **MUST** only reference tokens that:
> * Were provided in an active request
> * Are associated with an in-progress operation"
> "Receivers of progress requests **MAY**:
> * Choose not to send any progress notifications"

**Client opt-out is the bedrock of AC-2:** if the client did NOT include
`_meta.progressToken` in the `tools/call` request, the server MUST NOT emit any
`notifications/progress`. The AC-2 wording ("Given a lean_verify call that runs
longer than 2s… at least one notifications/progress message is emitted before the
result") is vacuously satisfied when the client sent no progressToken. Tests MUST
mock a progressToken to actually exercise the emission path.

Rate limiting:
> "Both parties **SHOULD** implement rate limiting to prevent flooding"

Post-completion:
> "Progress notifications **MUST** stop after completion"

No `notifications/cancelled` interaction text on the progress page — cancellation
interrupts the entire request, not just the progress stream. FastMCP handles session
cancellation at the transport level; the handler should use `asyncio.CancelledError`
propagation normally (heartbeat task cancelled in `finally`).

### FastMCP `Context.report_progress` — mcp==1.27.1 (installed)

Exact source (inspected live):
```python
async def report_progress(
    self,
    progress: float,
    total: float | None = None,
    message: str | None = None,
) -> None:
    progress_token = (
        self.request_context.meta.progressToken
        if self.request_context.meta
        else None
    )
    if progress_token is None:  # pragma: no cover
        return
    await self.request_context.session.send_progress_notification(
        progress_token=progress_token,
        progress=progress,
        total=total,
        message=message,
    )
```

Key facts:
1. **Silently no-ops when no progressToken is present** — the `if progress_token is None: return` guard is correct per spec. No exception raised.
2. **Transport path:** `send_progress_notification` sends over the active Streamable HTTP session's SSE channel. It does NOT block — it is an async send. Client disconnect errors are handled at the transport layer (mcp SDK), not surfaced to the caller in normal operation.
3. **`ctx: Context` is injected by FastMCP when present as a type annotation.** It does NOT appear in `inputSchema`. The installed `Context` docstring confirms: "The context parameter name can be anything as long as it's annotated with `Context`. The context is optional — tools that don't need it can omit the parameter."
4. **No known FastMCP 1.27.1 bugs** around `report_progress` found in available source inspection. The `# pragma: no cover` on the no-op branch is the library's own test annotation, not a code smell.

---

## Failure-mode enumeration

**FM-1 — No `_meta.progressToken` from client.**
Trigger: client sends `tools/call` without `_meta: {progressToken: ...}`.
Observable: `ctx.report_progress()` silently returns — zero notifications emitted.
Spec compliance: CORRECT (server MAY choose not to send). AC-2 is vacuously satisfied.
Mitigation: tests must mock `request_context.meta.progressToken` to a non-None value
to exercise the actual emission path. Without this, the test only confirms no-op behavior.

**FM-2 — Client disconnects mid-emission (SSE stream closes).**
Trigger: client closes the HTTP connection while `lean_repl.query()` is running.
Observable: `send_progress_notification()` may raise (transport closed error) or
silently discard depending on mcp SDK version. FastMCP's session transport
handles this at its layer.
Mitigation: wrap `ctx.report_progress()` calls inside the heartbeat task with
`try/except Exception: pass` (or a narrow transport-closed exception) so a
mid-stream disconnect does NOT propagate to `handle_lean_verify` or kill the
REPL query. The REPL query continues to completion regardless.

**FM-3 — Heartbeat coroutine outlives the Lean call (task leak).**
Trigger: heartbeat `asyncio.Task` not cancelled after `lean_repl.query()` returns.
Observable: additional `notifications/progress` emitted AFTER the `tools/call`
response has been sent — spec violation ("Progress notifications MUST stop after
completion").
Mitigation: use `try/finally` around `lean_repl.query()`. In the `finally` block:
`heartbeat_task.cancel(); await asyncio.gather(heartbeat_task, return_exceptions=True)`.
The `return_exceptions=True` avoids a second exception from `CancelledError`.

**FM-4 — Non-monotonic progress (spec violation).**
Trigger: heartbeat emits progress values out of order (e.g., two concurrent tasks
both increment a shared counter, race condition).
Observable: downstream client may log a spec violation; progress bar could regress.
Mitigation: use a single `asyncio.Task` for heartbeat. Increment a local counter
strictly within that task (no shared mutable state). Wall-clock monotonic approach:
`elapsed = time.monotonic() - start; await ctx.report_progress(elapsed, total=30.0)`.

**FM-5 — `report_progress` blocks the event loop or stalls Lean wait.**
Trigger: `send_progress_notification` is slow (e.g., SSE write buffer backpressure).
Observable: Lean elaboration pauses because the heartbeat task holds the GIL or
blocks `await`.
Mitigation: `lean_repl.query()` runs in a separate `asyncio.Task` (use
`asyncio.create_task(lean_repl.query(...))` + `asyncio.create_task(heartbeat(...))`
then `asyncio.wait({lean_task, heartbeat_task}, return_when=FIRST_COMPLETED)`).
The heartbeat is SEPARATE from the REPL query — they interleave naturally under
the event loop without stalling each other.

**FM-6 — Backpressure: emit-every-100ms floods the SSE stream.**
Trigger: heartbeat interval too tight (< 1s).
Observable: client receives many hundreds of notifications for a 30s elaboration.
Spec: "Both parties SHOULD implement rate limiting to prevent flooding."
Mitigation: use a 2–3 second heartbeat interval. Five to fifteen notifications over
a 30s call is appropriate. Recommend: `asyncio.sleep(3.0)` between heartbeats.

**FM-7 — `lean_verify` raises BEFORE first heartbeat tick (REPL crash or timeout).**
Trigger: `lean_repl.query()` raises `LeanReplTimeoutError` or `LeanReplError`
immediately (e.g., REPL process exited before the first heartbeat fires at t=3s).
Observable: heartbeat task left running unless cancelled in `finally`.
Mitigation: the `try/finally` structure in FM-3 handles this case identically.
The `finally` fires regardless of whether `lean_repl.query()` raised or returned.
Existing m3 timeout-kill-respawn logic must be PRESERVED inside this new `finally`.

**FM-8 — BP1 cache regression from careless `ctx` plumbing.**
Trigger: implementer accidentally adds `ctx` to the function signature without
FastMCP `Context` type annotation, causing it to appear in `inputSchema`.
Observable: `EXPECTED_TOOL_SCHEMA_SHA256` flips. Every Claude agent prompt cache
invalidates on next `tools/list`. Cost spike + 80–95% latency increase on
multi-agent fan-out (per `07-multi-agent-caching.md`: "Anthropic prompt cache:
80–95% of input tokens on the second-and-subsequent agent calls in a pipeline").
Mitigation: annotate EXACTLY as `ctx: Context` (from `mcp.server.fastmcp`). The
test `test_lean_verify_in_all_tools` already verifies the schema hash; it will
catch this regression at CI time. The milestone AC explicitly states
"EXPECTED_TOOL_SCHEMA_SHA256 is unchanged by this milestone."

**FM-9 — Progress messages leak Lean source or proof content.**
Trigger: message field includes the `snippet` variable or REPL response text.
Observable: proof body leaks through an informational channel (PII / size risk).
`08-security-observability-ops.md` Threat 2 mandates content wrapping for retrieved
chunks; a similar concern applies here — even though progress messages aren't
retrieval results, leaking user-supplied Lean code in a notification is undesirable.
Mitigation: keep message strings to durations and elapsed seconds only:
`f"Lean elaboration running — {elapsed:.0f}s elapsed"`. Never include `snippet`,
`cmd`, or any REPL response text in the message field.

---

## In-codebase cross-check (lightweight)

**(a) `docs/snippet-contract.md`:** The snippet contract (≤150 chars from
`body_canonical`) applies only to retrieval-result tools. `lean_verify` explicitly
documents "No 150-char snippet contract" (handler docstring line 11–14). Progress
messages are not result rows — they never pass through `envelope()` or `cap_result_list`.
No conflict.

**(b) `server/middleware.py` BodySizeCap / SessionCap:** Progress notifications
are MCP-level JSON-RPC notifications sent by the SDK's `send_progress_notification`.
They do NOT flow through the FastAPI request/response cycle that `BodySizeCapMiddleware`
and `SessionCapMiddleware` intercept. `SessionCapMiddleware` counts `tools/call`
invocations (one increment per call), not notifications emitted during a call.
Progress emissions are INDEPENDENT of session caps.

**(c) `Mcp-Session-Id` retrieval cache:** `report_progress` uses
`self.request_context.session.send_progress_notification`, which sends on the
session's SSE channel. This is independent of the Tier-1/2/3 retrieval caches
(keyed on `Mcp-Session-Id`). No interaction.

**(d) `server/observability/logging_setup.py`:** `corpus-integrity-observability-e2`
wired `JsonFormatter` as the default. The implementer SHOULD emit a structured INFO
log at each heartbeat tick (e.g., `logger.info("lean_verify: progress heartbeat",
extra={"elapsed_s": elapsed})`) in ADDITION to the MCP notification — this provides
ops visibility when monitoring logs. The log MUST NOT include `snippet` (DEBUG-only
per `08-security-observability-ops.md` §Logging rule: "Sensitive fields [full query
text] are logged at DEBUG only, never at INFO or above").

---

## Recommendation

**Implement the heartbeat as two concurrent `asyncio.Task` objects: one for
`lean_repl.query()` and one for the heartbeat loop, joined with
`asyncio.wait(return_when=FIRST_COMPLETED)` + `finally` cancellation.**

Concrete pattern for `handle_lean_verify`:
```python
async def handle_lean_verify(snippet: ..., imports: ..., mode: ..., ctx: Context) -> dict:
    ...
    start = time.monotonic()
    progress_counter = 0.0

    async def _heartbeat():
        nonlocal progress_counter
        while True:
            await asyncio.sleep(3.0)
            progress_counter += 3.0
            try:
                await ctx.report_progress(progress_counter, total=30.0,
                    message=f"Lean elaboration running — {progress_counter:.0f}s elapsed")
            except Exception:
                pass  # FM-2: client disconnect; continue REPL wait

    lean_task = asyncio.create_task(lean_repl.query({"cmd": cmd}))
    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        done, _ = await asyncio.wait(
            {lean_task, heartbeat_task},
            return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)

    if lean_task.cancelled():
        ...  # propagate CancelledError
    if lean_task.exception():
        raise lean_task.exception()
    resp = lean_task.result()
    ...
```

This satisfies FM-3, FM-4, FM-5, FM-7. The existing `try/except LeanReplTimeoutError`
and `try/except LeanReplError` from m3 must be restructured to wrap `lean_task.result()`
rather than `lean_repl.query()` directly.

Reasoning: separating REPL query and heartbeat into independent tasks means neither
can stall the other; `finally` guarantees FM-3/FM-7 cancellation on all exit paths.
The 3s interval satisfies FM-6. Single counter inside `_heartbeat` satisfies FM-4.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one subtlety to note (not an open question, but a decision): the `asyncio.wait`
pattern requires restructuring the existing `try/except LeanReplTimeoutError` block
in `handle_lean_verify`. The exception is now raised by `lean_task.result()` (or
caught from `lean_task.exception()`), not directly from `await lean_repl.query()`.
The implementing agent must verify `LeanReplTimeoutError` still propagates correctly
through the task boundary — `asyncio.create_task` wraps exceptions in the Task;
`lean_task.result()` re-raises them.

---

## External writes the implementation will require

None — this milestone is purely local.
