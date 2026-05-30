# Implementation Summary — verification-feedback-m4

**Summary:** thread an optional FastMCP `Context` into `handle_lean_verify` and
emit `notifications/progress` heartbeats every 3 s while the Lean REPL is
elaborating, so the calling agent sees progress rather than an apparent hang
on the 5–30 s call. `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`
verified unchanged.

**Commit range:** `7f9cac993d1e178a23eb8c7cf5de08d63543e9dc..<HEAD after feat>`

## Acceptance criteria status

- [x] **AC-1** Handler signatures and `server/tools.py` registration wiring
      updated to pass `ctx: Context`; the 7 existing handlers are unchanged in
      behavior. → Only `handle_lean_verify` gained `ctx: Context | None = None`
      (synthesis §3 D2). The other 7 handlers were NOT touched (synthesis
      §3 D1 — the brief AC's "unchanged in behavior" is satisfied by leaving
      them as-is). `server/tools.py` itself is UNCHANGED — FastMCP's
      `find_context_parameter` introspects the registered handler at
      `register_one` time and auto-injects `ctx` without any registration-side
      change.
- [x] **AC-2** Given a `lean_verify` call that runs longer than 2 s, when it
      executes, then at least one `notifications/progress` message is emitted
      before the result. → `TestProgressHeartbeat::test_ac2_emits_progress_before_result_for_slow_call`
      uses a `_SlowFakeLeanRepl(delay_s=0.2)` and a monkeypatched
      `_HEARTBEAT_INTERVAL_S=0.05`; asserts `len(ctx.calls) >= 1`, monotonic
      progress, and `total == 30.0` for every emission.
- [x] **AC-3** No BP1/BP2 cache-discipline regression — `tools/list` bytes
      unchanged → live-verified: `tests/test_server_tool_schema.py` (42
      tests including `test_tool_schema_hash_matches`) +
      `tests/test_prompts.py` all pass with `EXPECTED_TOOL_SCHEMA_SHA256`
      and `EXPECTED_BP1_SHA256` UNCHANGED.
      `TOOL_SCHEMA_VERSION` stays at 16. Mechanism guarded by
      `TestProgressHeartbeat::test_fm8_ctx_excluded_from_input_schema`
      (asserts `find_context_parameter(handle_lean_verify) == "ctx"`).
- [x] **AC-4** `make test` green, `ruff check .` clean → 3468 passed,
      30 skipped, 1 xfailed; 3 pre-existing failures unrelated to m4
      (`test_drift_check::test_render_fixture_does_not_leave_log_artifact`,
      `test_tools_all::test_cite_neighbors_wired`, and one Windows-platform
      test) — verified to be the same 3 failures present BEFORE this
      milestone (3416 → 3468 = +52 from m4's 8 new tests + 44 from the
      parallel notebook-surface session). `ruff check .` clean.

## File deltas

**`server/handlers/lean_verify.py`** (+~95 LOC, +2 imports)
- Added `import asyncio`, `import contextlib`, `from mcp.server.fastmcp
  import Context`.
- New module-level constants `_HEARTBEAT_INTERVAL_S = 3.0` and
  `_HEARTBEAT_TOTAL_S = 30.0`.
- New helper `async def _emit_progress_heartbeats(ctx: Context)` — runs as
  an asyncio task while the REPL elaborates; emits via `ctx.report_progress`
  every 3 s; swallows transport exceptions per FM-2; emits an INFO log
  per heartbeat (FM-9 PII discipline — no snippet text).
- `handle_lean_verify` signature: new last parameter
  `ctx: Context | None = None` (synthesis §3 D2 — default `None` preserves
  the existing direct-call test sites).
- The `resp = await lean_repl.query({"cmd": cmd})` call is now wrapped in
  a `try/finally` that spawns the heartbeat task (only when `ctx is not
  None`) and cancels it on every exit path (success — AC-6 / FM-3; timeout
  — AC-5a / FM-7; non-timeout `LeanReplError` — AC-5b / FM-7). The m3
  `try/except LeanReplTimeoutError` / `try/except LeanReplError` blocks
  that wrap this `try/finally` are UNCHANGED.

**`tests/test_handlers_lean_verify.py`** (+~290 LOC)
- New `_RecordingCtx` test helper (lean stand-in for `Context`; captures
  every `report_progress` call; supports `raise_on_call` for FM-2).
- New `_SlowFakeLeanRepl` subclass (sleeps `delay_s` before responding or
  raising).
- New `TestProgressHeartbeat` class with 8 tests:
  - `test_ac4_no_emission_when_ctx_is_none` (AC-4 default-call back-compat)
  - `test_ac2_emits_progress_before_result_for_slow_call` (AC-2)
  - `test_ac7_message_contains_no_snippet_or_cmd_text` (AC-7 / FM-9 PII)
  - `test_ac6_no_emission_after_result_returns` (AC-6 / FM-3)
  - `test_ac5a_heartbeat_cancelled_on_lean_repl_timeout` (AC-5a / FM-7;
    also asserts the m3 timeout-kill-respawn path is preserved)
  - `test_ac5b_heartbeat_cancelled_on_lean_repl_error` (AC-5b / FM-7)
  - `test_fm2_disconnected_ctx_does_not_break_handler` (FM-2)
  - `test_fm8_ctx_excluded_from_input_schema` (FM-8 mechanism guard)
- Autouse fixture `_fast_heartbeat` monkeypatches `_HEARTBEAT_INTERVAL_S` to
  0.05 s so the suite runs in ~2 s rather than ~60 s.

**No other files touched.** `server/tools.py`, `server/prompts.py`,
`server/handlers/*.py` (other than `lean_verify.py`), every schema file,
every fixture file — UNCHANGED.

## New / changed test paths

- `tests/test_handlers_lean_verify.py` — 8 new tests under `TestProgressHeartbeat`.
- No other test files modified.

## Deviations from the synthesis

None. Adopted both synthesis design resolutions verbatim:
- **D1**: R1's single-heartbeat-task pattern (Lean call on main coroutine,
  heartbeat as a separate task) over R2's two-task `asyncio.wait`
  FIRST_COMPLETED pattern. Preserves m3 exception flow with zero
  restructure.
- **D2**: `ctx: Context | None = None` (default `None`) over a required
  parameter — necessary for the existing `_run(handle_lean_verify(...))`
  direct-call test sites to remain unchanged.

The ruff-recommended `contextlib.suppress(...)` form is used in both
heartbeat-cleanup paths (vs the literal `try/except/pass` shown in the
synthesis snippet) — pure cosmetic style fix to satisfy SIM105.

## External writes required

**None.** Purely local. The synthesis predicted zero external writes; this
holds. No `git push`, no PR, no ticket, no infra mutation.
