# Critique (merged) — verification-feedback-m2

**Critics run:** adversary (1 of 1 — `milestone-infra-safety` did not fire:
no infra / docker / Makefile paths in the diff; `milestone-oss-scout` not
requested).
**Generated:** 2026-05-22T00:00:00Z
**Commit range:** `d9af59db4c3019194b77df42c7b328ae93ea8f0e..c9df7f1`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- **SHIP-WITH-FIXES.** The Lean REPL harness is well-built and the four
  declared deviations are sound; one HIGH (resource leak on a failed Lean
  spawn) and four MEDIUM findings are closed before ship.
- **HIGH (F1):** the `enable_lean=true` startup path placed the step-6e Lean
  spawn before the `Resources` constructor — a `LeanUnavailableError` leaked
  every already-warm resource (BGE-M3 ~1.5 GB, LanceDB, cache, SQLite) on
  every crash-restart iteration.
- Cache byte-stability, math fidelity, MCP-spec compliance, local-first,
  tier-sequencing, and no-fork axes are all clean — m2 adds no MCP tool, so
  `tools/list` bytes and `EXPECTED_TOOL_SCHEMA_SHA256` are correctly untouched.
- The fail-loud contract (`LeanUnavailableError` ⊂ `ResourceStartupError`,
  mirroring `RerankerUnavailableError`) and the `asyncio.create_subprocess_exec`
  non-blocking spawn are correct — AC2's no-cold-start-race intent is met.

## Severity calibration table

| Severity | Meaning | Count |
|---|---|---|
| CRITICAL | data loss / security regression / broken invariant | 0 |
| HIGH | wrong behavior on a common path / load-bearing constraint | 1 |
| MEDIUM | subtle correctness / missing test / latent foot-gun | 4 |
| LOW | style / naming / micro-perf | 2 |

## Cross-critic agreement

_None — single critic (adversary). No cross-critic corroboration applicable._

<!-- end:cross-critic-agreement -->

## Findings

The full per-finding detail (F1–F7, with `file:line` citations, proposed
fixes, and regression guards) lives in the canonical adversary critique at
`critique-adversary.md` in this directory. Summary:

- **F1 — HIGH** — Lean spawn failure leaks BGE-M3 / LanceDB / cache handles
  (`server/resources.py`). **Fixed.**
- **F2 — MEDIUM** — `query`/`_round_trip`/`close` had zero always-run test
  coverage (`tests/test_lean_repl.py`). **Fixed.**
- **F3 — MEDIUM** — `_round_trip` could hang to the 30 s timeout on a
  response with no trailing blank-line terminator (`server/lean_repl.py`).
  **Fixed.**
- **F4 — MEDIUM** — runaway-elaboration memory exhaustion unguarded
  (`RLIMIT_AS` deferred). **Addressed by tracking** — now an explicit m3
  acceptance criterion.
- **F5 — MEDIUM** — `close()` post-`kill()` reap was an unbounded `wait()`
  (`server/lean_repl.py`). **Fixed.**
- **F6 — LOW** — test env vars read at import time. **Deferred.**
- **F7 — LOW** — redundant `lean_repl` local initializer. **Deferred.**

## Recommended rectification order

1. F1 — wrap step-6e spawn so a Lean failure tears down warm resources.
2. F2 — add always-run `query`/`_round_trip`/`close` tests via a fake process.
3. F5 — bound the post-`kill()` reap with `asyncio.wait_for`.
4. F3 — make `_round_trip` resilient to a missing blank-line terminator.
5. F4 — carry `RLIMIT_AS` as an m3 acceptance criterion.
6. F6, F7 — LOW; defer.

## Rectification status

Rect commit closes F1–F5; F6–F7 deferred (LOW). **Zero findings invalidated**
on the Phase-4 re-verify gate (0% invalidation rate — every cited `file:line`
still matched the diff, well under the 40% heuristic).

- **F1 (HIGH) — fixed.** `server/resources.py`: step-6e Lean spawn moved
  after the `Resources` constructor; a spawn failure calls
  `instance.shutdown()` before re-raising. Guard:
  `tests/test_server_startup.py::TestStartupRefusals::test_enable_lean_spawn_failure_tears_down_resources`.
- **F2 (MEDIUM) — fixed.** New always-run fake-subprocess harness:
  `tests/test_lean_repl.py::TestFakeProcRoundTrips` (9 tests).
- **F3 (MEDIUM) — fixed.** `server/lean_repl.py::_round_trip` returns on the
  first successful `json.loads`, making the blank-line terminator optional.
  Guard: `TestFakeProcRoundTrips::test_query_returns_without_trailing_blank_line`.
- **F4 (MEDIUM) — addressed by tracking.** `RLIMIT_AS` is now an explicit
  acceptance criterion on the m3 brief in
  `plans/verification-feedback-roadmap.md`.
- **F5 (MEDIUM) — fixed.** `server/lean_repl.py::close` bounds the
  post-`kill()` reap with `asyncio.wait_for(_CLOSE_GRACE_S)`. Guard:
  `TestFakeProcRoundTrips::test_close_escalates_to_kill_and_stays_bounded`.
- **F6 (LOW) — deferred.** Test-author foot-gun, consistent with the existing
  `requires_model` env-var pattern.
- **F7 (LOW) — deferred.** Critic recommended "no change."
