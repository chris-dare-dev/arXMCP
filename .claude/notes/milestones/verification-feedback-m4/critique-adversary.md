# Adversary Critique — verification-feedback-m4

**Verdict:** RECTIFY-REQUIRED — 5 findings (0 CRITICAL / 2 HIGH / 2 MEDIUM / 1 LOW).
**Commit range:** `7f9cac9..2a34210` (single feat commit).

## Executive summary

- Cap-at-0.95 plateau **violates MCP spec MUST** ("progress MUST increase with
  each notification") whenever elapsed ≥ `_HEARTBEAT_TOTAL_S` × 0.95 = 28.5 s.
  Today this is masked because `DEFAULT_QUERY_TIMEOUT_S=30.0` and the cadence
  is 3 s, so the LAST emission before timeout is `(elapsed=30.0, pct=0.95)`
  and the next would-be tick is preempted — but the bug is real-by-construction
  and decouples the moment anyone bumps the timeout.
- BP1/BP2 byte-stability **independently verified clean** —
  `inputSchema.properties = ['snippet','imports','mode']`, `ctx` excluded;
  both `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` tests pass;
  `find_context_parameter(handle_lean_verify) == 'ctx'` returns correctly
  through the `@functools.wraps`-preserved `__wrapped__` chain.
- m3 timeout-kill-respawn flow preserved **verbatim** — the
  `try/except LeanReplTimeoutError` / `except LeanReplError` blocks now wrap
  a nested `try/finally` (heartbeat cleanup), but the exception path is
  byte-identical to m3.
- Cancellation discipline correct in Python 3.12 — `CancelledError` is
  `BaseException`-subclass (verified live: `issubclass(asyncio.CancelledError,
  Exception) is False` on 3.12.13), so `contextlib.suppress(Exception)`
  correctly does NOT swallow it; cancellation propagates cleanly out of the
  heartbeat task.
- Full test suite: `3 failed, 3468 passed, 30 skipped, 1 xfailed` — the 3
  failures are pre-existing m4-unrelated.

---

## Findings

### F1 — Heartbeat plateau at 0.95 violates MCP spec "progress MUST increase"

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/handlers/lean_verify.py:151`
- **What:** The loop computes
  `pct = min(elapsed / _HEARTBEAT_TOTAL_S, 0.95)`. Once
  `elapsed >= 28.5 s` the cap clamps every subsequent emission to exactly
  `0.95`. The MCP 2025-06-18 spec
  (https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/progress)
  says: *"The `progress` value **MUST** increase with each notification, even
  if the total is unknown."* Plateaued values are not strictly increasing →
  MUST violation. Today this is masked because `DEFAULT_QUERY_TIMEOUT_S=30.0`
  and the cadence is 3 s, so the LAST emission before timeout is at
  `(elapsed=30.0, pct=0.95)` and the next would-be tick is preempted. But the
  bug is real-by-construction: if `DEFAULT_QUERY_TIMEOUT_S` is raised (likely
  in a future milestone — F2 also flags this divergence) OR if the heartbeat
  tick races with timeout dispatch, multiple `progress=0.95` notifications go
  on the wire. The synthesis claim "FM-4 monotonic progress satisfied by
  construction (single counter)" is false — the counter increases but the
  *emitted* `progress` field plateaus, and the spec talks about the emitted
  field, not the local counter.
- **Recommendation:** Replace the cap with a strictly-increasing asymptote.
  Concrete options:
  1. Asymptotic taper: `pct = 1.0 - math.exp(-elapsed / _HEARTBEAT_TOTAL_S)` —
     strictly < 1, strictly monotonic, no cap arithmetic. Preferred.
  2. Drop `total` field; emit `elapsed` directly as `progress` (spec allows
     total unknown; raw `elapsed` is monotonic by construction).

### F2 — `_HEARTBEAT_TOTAL_S` hardcoded, drifts silently from `DEFAULT_QUERY_TIMEOUT_S`

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/handlers/lean_verify.py:99-105` (constant) +
  `server/handlers/lean_verify.py:453` (timeout path already imports
  `DEFAULT_QUERY_TIMEOUT_S` directly from `server.lean_repl`).
- **What:** The module declares `_HEARTBEAT_TOTAL_S: float = 30.0` with the
  docstring claiming *"we surface the same number here so a client progress
  bar reflects the same wall-clock budget."* The actual single source of
  truth is `server.lean_repl.DEFAULT_QUERY_TIMEOUT_S = 30.0`
  (`server/lean_repl.py:62`). The timeout-envelope path **already** imports
  this directly (`from server.lean_repl import DEFAULT_QUERY_TIMEOUT_S` at
  `lean_verify.py:453`). So the same file has TWO sources of truth for the
  same number, and the heartbeat's `total` arg silently desynchronizes the
  moment anyone bumps `DEFAULT_QUERY_TIMEOUT_S`.
- **Recommendation:** Replace the constant with a direct import at module
  top: `from server.lean_repl import DEFAULT_QUERY_TIMEOUT_S` — and use it
  inside `_emit_progress_heartbeats`. Removes the divergence by
  construction. Note this is the SAME import pattern the timeout path
  already uses — no new dependency surface.

### F3 — INFO log fires every tick regardless of emission success or no-progressToken no-op

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/handlers/lean_verify.py:152-163`
- **What:** Structure is:
  ```python
  with contextlib.suppress(Exception):
      await ctx.report_progress(pct, total=_HEARTBEAT_TOTAL_S, message=message)
  logger.info("lean_verify: progress heartbeat", extra={"elapsed_s": elapsed})
  ```
  The `logger.info(...)` runs unconditionally — after the `suppress` block,
  NOT inside it. Two observability consequences: (1) **No-progressToken
  case (FM-1)** — FastMCP's `report_progress` silently no-ops when the
  client did not include `_meta.progressToken`. The heartbeat task is still
  spawned whenever `ctx is not None`; on a 30 s call without a progressToken
  that's ~10 INFO log lines per call documenting heartbeats that emitted
  nothing. (2) **Transport-error case (FM-2)** — when `report_progress`
  raises (client disconnect), `suppress(Exception)` swallows it silently —
  no `logger.warning` / `logger.exception` records that emission failed,
  while the INFO log still records "heartbeat fired" — actively misleading.
- **Recommendation:** Track emission success and only log on success; log
  WARN on transport failure. Optionally also skip the heartbeat task
  entirely when no progressToken (peek at
  `ctx.request_context.meta.progressToken` once at spawn time).

### F4 — Test fixture does not model the no-progressToken FM-1 path

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_handlers_lean_verify.py:1077-1106` (the
  `_RecordingCtx` shim) + class-level — no test covers the no-token case.
- **What:** `_RecordingCtx.report_progress` unconditionally appends to
  `self.calls`. The real FastMCP `Context.report_progress` returns immediately
  when `progress_token is None`. The synthesis names FM-1 as the
  AC-2-vacuously-satisfied case but no test exercises it: every m4 test
  passes a non-None recording shim, so the most common call path (no
  progressToken from the calling agent) is mechanism-tested via
  `find_context_parameter` (FM-8) but never runtime-tested.
- **Recommendation:** Add a `_NoTokenCtx` shim whose `report_progress`
  returns immediately without recording, and a test that asserts: (a)
  handler still returns `status=ok`; (b) emission counter is 0; (c) the
  heartbeat task is cancelled cleanly. Combine with F3's proposed
  skip-on-no-token to assert the task is never spawned.

### F5 — Monotonicity assertion is non-strict, would not catch F1

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_handlers_lean_verify.py:1207-1210`
- **What:**
  `assert progresses == sorted(progresses), ("progress MUST monotonically increase per MCP spec; ...")`.
  Sorted-equality is a non-strict monotonic check; `[0.95, 0.95, 0.95]`
  passes. The spec language is "MUST increase" (strict).
- **Recommendation:** Tighten to strict-increase:
  `assert all(a < b for a, b in zip(progresses, progresses[1:])), f"...got {progresses}"`.

---

## What was done well

- **FastMCP injection mechanism correctly used.** The literal
  `Context | None = None` annotation + the `@functools.wraps`-preserved
  `__wrapped__` chain through `_wrap_with_observability` causes
  `find_context_parameter` to return `"ctx"` (verified live), and
  `Tool.from_function` correctly excludes `ctx` from
  `inputSchema.properties`. Both BP1/BP2 hash tests pass unchanged.
- **m3 timeout-kill-respawn flow preserved verbatim.** The outer
  `try/except LeanReplTimeoutError` / `except LeanReplError` blocks are
  byte-identical to m3; the heartbeat cleanup lives inside a nested
  `try/finally` that runs BEFORE the exception handlers see the exception.
- **Cancellation discipline correct for Python 3.12.**
  `contextlib.suppress(Exception)` does NOT catch `CancelledError`, so
  cancellation propagates cleanly out of the heartbeat.
- **No `assert` for invariants** introduced (CLAUDE.md §4.7 banned-pattern
  clean).
- **No `BaseHTTPMiddleware` regression**, no `--no-verify`, no
  `--no-gpg-sign`. No forks. Pure-ASGI compatible. No `anthropic` SDK
  introduced.
- **PII discipline clean.** The progress `message` is duration-only —
  `f"Lean elaboration running — {elapsed:.0f}s elapsed"`. AC-7 test
  asserts the negative with seeded "SECRETSAUCE" markers.
- **Spec rate-limit SHOULD respected.** 3 s cadence on a 30 s budget →
  ~10 emissions, well under any flooding threshold.
- **Default-None back-compat.** Every pre-existing direct-call test site
  compiles and runs unchanged; the synthesis §3 D2 decision was sound.
- **No-fork / loopback-only / Docker-compatible** — no infra-tier
  dependencies added.
- **Test count delta correct.** +8 m4 tests; matches the 3416 → 3468
  baseline shift.

---

## Recommended rectification order

1. **F1 + F2 together** — both touch `_emit_progress_heartbeats` and the
   `_HEARTBEAT_TOTAL_S` constant. Switch to
   `from server.lean_repl import DEFAULT_QUERY_TIMEOUT_S`, drop
   `_HEARTBEAT_TOTAL_S`, and replace the `min(..., 0.95)` cap with the
   asymptotic-taper formula `1.0 - math.exp(-elapsed / DEFAULT_QUERY_TIMEOUT_S)`.
2. **F5** — flip the test assertion to strict-increase; paired with F1.
3. **F3 + F4 together** — add the no-progressToken skip + WARN-on-failure
   log + `_NoTokenCtx` test fixture covering both branches.

## Rectification status (filled by Phase 4)

- **F1 (HIGH) — heartbeat plateau at 0.95.** RESOLVED. Replaced the
  ``min(elapsed / _HEARTBEAT_TOTAL_S, 0.95)`` cap with a new
  ``_heartbeat_progress`` helper using the asymptotic taper
  ``1.0 - math.exp(-elapsed / DEFAULT_QUERY_TIMEOUT_S)`` — strictly
  monotonic on ``[0, ∞)``, strictly less than 1.
  Regression guard: ``test_f1_progress_never_plateaus`` in
  `tests/test_handlers_lean_verify.py` monkeypatches
  ``DEFAULT_QUERY_TIMEOUT_S = 0.1`` to force the would-be-cap region,
  spawns >=5 ticks, and asserts strict-increase + ``p < 1.0``.
- **F2 (HIGH) — hardcoded `_HEARTBEAT_TOTAL_S` divergence.** RESOLVED.
  Dropped the ``_HEARTBEAT_TOTAL_S`` constant; added
  ``from server.lean_repl import DEFAULT_QUERY_TIMEOUT_S`` at module
  top; ``_emit_progress_heartbeats`` now passes ``total=DEFAULT_QUERY_TIMEOUT_S``
  directly. Same file already used this import on the timeout path —
  one source of truth.
  Regression guard: ``test_f2_total_tracks_default_query_timeout_s``
  monkeypatches the constant to 99.0 and asserts every emission carries
  ``total == 99.0``.
- **F3 (MEDIUM) — INFO log fires unconditionally + silent swallow on
  emission failure.** RESOLVED. (a) New ``_has_progress_token(ctx)``
  helper gates the heartbeat-task spawn in ``handle_lean_verify`` —
  no token ⇒ no task ⇒ no INFO spam. (b)
  ``_emit_progress_heartbeats`` replaced ``contextlib.suppress(Exception)``
  with a try/except that logs ``logger.warning("lean_verify: progress
  emission failed (client disconnect?)", exc_info=True)``. (c) The
  ``logger.info("lean_verify: progress heartbeat", ...)`` is now gated
  on ``emitted`` so it fires ONLY on successful emission.
  Regression guard: ``test_f3_warn_log_on_emission_failure`` uses
  ``caplog`` to assert (i) WARN was emitted on the disconnect tick;
  (ii) the heartbeat-INFO record was NOT emitted on the failed-emission
  tick.
- **F4 (MEDIUM) — no-progressToken test gap.** RESOLVED. Added
  ``_FakeMeta``, ``_FakeRequestContext``, and a ``progress_token``
  ctor argument on ``_RecordingCtx`` (default ``"test-tok"``; pass
  ``None`` to model the FM-1 path). New test
  ``test_f4_no_emission_when_client_omits_progress_token`` constructs
  ``_RecordingCtx(progress_token=None)``, runs a 0.2 s fake-Lean call,
  and asserts ``ctx.calls == []`` — the task is never spawned, no
  emissions happen.
- **F5 (LOW) — non-strict monotonicity assertion.** RESOLVED.
  ``test_ac2_emits_progress_before_result_for_slow_call`` flipped from
  ``progresses == sorted(progresses)`` to
  ``all(a < b for a, b in zip(progresses, progresses[1:], strict=False))``
  — the spec MUST "MUST increase" is now actually enforced; the
  prior assertion silently passed ``[0.95, 0.95, 0.95]``.

**0% invalidation rate** — all 5 findings closed with code + regression
tests. Full suite: `3 failed, 3472 passed, 30 skipped, 1 xfailed` (3
pre-existing m4-unrelated failures: `test_drift_check`,
`test_cite_neighbors_wired`, and one Windows-only path).
