# Deviations from brief-1.md — desktop-distribution-m6

The brief's architecture (extensions-key injection, fixture-driven matrix,
real-supervisor code-under-test, shared redaction vectors, evidence
discipline) was followed. Five deliberate deviations, each with why:

1. **Bound-timeout override is a `Plan` field (`test_bound_timeout_ms`), not
   an env var.** The brief proposed `ARXMCP_DESKTOP_BOUND_TIMEOUT_MS`
   mirroring `BARRIER_ENV`; but the brief itself then insisted the
   grace/force knobs must ride the Plan "not a second override path". One
   test-configuration surface (the Plan) is strictly simpler and removes any
   env-scrub reasoning: the knobs structurally cannot reach the child.
2. **The grace/force shrink CANNOT ride the wire frame.** The brief said
   "shrink them via the Plan [into the wire launch frame]" — but
   `validate_shutdown_semantics` enforces `grace_ms >= MIN_GRACE_MS
   (35_000)` on every encoded frame, so a wire-level shrink is a contract
   change (banned). `test_shutdown_grace_ms`/`test_shutdown_force_after_ms`
   therefore override only the supervisor's LOCAL `ChildControl` budgets;
   the wire frame the child sees keeps the contract floor. The
   escalation-ladder code under test (`shutdown_child`) consumes exactly
   those budgets, so nothing tested is weakened.
3. **A sixth fixture arm `never-ready` was added** (the spike had the same
   case). With the fixture as counterparty every full cycle fails at the MCP
   smoke sub-second, so the brief's "kill the supervisor after child-bound"
   had no stable window. `never-ready` parks the supervisor in its 120 s
   readiness poll with a live bound listener — a deterministic window for
   the supervisor-SIGKILL test, while the fixture stays a cooperating child.
4. **`redact::scrub` was built and production-wired** (the brief left it
   conditional on a raw-capture diagnostic existing). The `bound-frame-
   invalid` diagnostic IS such a site: the one place raw child bytes get
   persisted, and a child echoing its launch frame is exactly how the
   capability could reach disk. The malformed-bound fault arm deliberately
   embeds the token in its invalid frame so the fault matrix proves
   scrub-before-persist end-to-end. Scrub runs before truncation so a
   boundary cut cannot leave a partial secret.
5. **The Python half of the redaction vectors is a test-level reference**
   (exact-match replace), because no production Python substring scrubber
   exists (`RedactionFilter` drops named structured-log fields — a different
   mechanism for a surface Rust does not have) and inventing a callerless
   module would be dead code. The dispatch's "consumed by both languages"
   holds: both language gates fail independently on vector drift.

## Production bug found and fixed by the matrix (in-scope)

`AppHandle::exit(code)` in tauri 2.11 does NOT propagate a nonzero code into
the process exit status — a failed lifecycle exited 0 (measured live:
crash-before-bound run, exit=0 with `lifecycle-failed` recorded). m5's AC3
never caught it because its success path asserts 0 == 0. `main.rs` now
captures `RunEvent::ExitRequested { code }` and exits with it after the
`RunEvent::Exit` child shutdown. Also added: the `orphan-shutdown` event in
`run_cycle`'s Err arm so fault cleanup is observable, not just inferable.
