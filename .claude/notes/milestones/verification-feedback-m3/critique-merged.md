# Critique (merged) — verification-feedback-m3

**Critics run:** adversary (1 of 1 — `milestone-infra-safety` did not fire:
no infra / docker / Makefile paths in the diff; `milestone-oss-scout` not
requested).
**Generated:** 2026-05-22T23:21:40Z
**Commit range:** `f52ce5cf4559f0a10dc68402baa5b621e438181a..52951ad`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- **SHIP-WITH-FIXES.** The `lean_verify` tool is wired correctly across
  handler, schema, registration, BP1 hash, and the RLIMIT_AS plumbing.
  Eight findings (2 HIGH, 4 MEDIUM, 2 LOW) close before ship — every fix
  is small and localized.
- **HIGH F1**: the RLIMIT_AS integration test asserted nothing about the
  cap (the m2 critique F4 carry-forward regression guard was meaningless).
- **HIGH F2**: the frozen result-row schema had no Draft7Validator
  conformance test — purely documentary today.
- Cache discipline is intact: `TOOL_SCHEMA_VERSION` 11→12,
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned, `EXPECTED_BP1_SHA256` re-pinned,
  `LEAN_VERIFY` appended (not inserted mid-tuple), description is a literal
  constant.
- Banned-pattern checklist clean across every axis (no `assert`-for-
  invariant, no `BaseHTTPMiddleware`, no `0.0.0.0`, no fork, no `latest`
  tag, no `import anthropic`, no `claude-opus` string).

## Severity calibration table

| Severity | Meaning | Count |
|---|---|---|
| CRITICAL | data loss / security regression / broken invariant | 0 |
| HIGH | wrong behavior on a common path / load-bearing constraint | 2 |
| MEDIUM | subtle correctness / missing test / latent foot-gun | 4 |
| LOW | style / naming / micro-perf | 2 |

## Cross-critic agreement

_None — single critic (adversary). No cross-critic corroboration applicable._

<!-- end:cross-critic-agreement -->

## Findings

The full per-finding detail (F1–F8, with `file:line` citations, proposed
fixes, and regression guards) lives in the canonical adversary critique at
`critique-adversary.md` in this directory. Summary:

- **F1 — HIGH** — RLIMIT_AS integration test asserts nothing about the cap
  (`tests/test_handlers_lean_verify.py:702`). **Fixed.**
- **F2 — HIGH** — `lean_verify_result.json` not enforced against real
  handler output (no Draft7Validator). **Fixed.**
- **F3 — MEDIUM** — Timeout detection relies on substring match on the
  exception message (`server/handlers/lean_verify.py:302`). **Fixed.**
- **F4 — MEDIUM** — Respawn-failure path swallows all exceptions
  (`server/handlers/lean_verify.py:320`). **Fixed.**
- **F5 — MEDIUM** — `_normalize_position` accepts negative integers,
  violating schema `minimum: 0`. **Fixed.**
- **F6 — MEDIUM** — Sentinel envelopes not covered by schema test.
  **Fixed (subsumed by F2).**
- **F7 — LOW** — Schema description claims a non-existent byte-hash test.
  **Fixed (doc reword).**
- **F8 — LOW** — `MAX_IMPORTS` not enforced defense-in-depth. **Fixed.**

## Recommended rectification order

1. F1 — meaningful RLIMIT_AS test + cap-integer closure assertion.
2. F2 — `TestLeanVerifyResultSchema` Draft7Validator suite + severity-clamp
   + str-coerce in `_normalize_response`.
3. F3 — `LeanReplTimeoutError` subclass + type-based discrimination.
4. F4 — narrow `except Exception:` to specific subclasses + propagate
   `CancelledError`.
5. F5 — `max(0, int(...))` clamp in `_normalize_position`.
6. F6 — subsumed by F2.
7. F8 — `len(imports_list) > MAX_IMPORTS → ValueError`.
8. F7 — schema description reword.

## Rectification status

Rect commit closes F1–F8 (every finding); zero deferred. **Zero findings
invalidated** on the Phase-4 re-verify gate (0% invalidation rate — every
cited `file:line` still matched the diff, well under the 40% heuristic).

- **F1 (HIGH) — fixed.** `test_real_rlimit_as_bounds_subprocess` rewritten
  to spawn at a 32 MiB cap (below Lean's baseline) and assert observable
  failure; companion unit-level assertion in `TestSpawnRlimitGuard` uses
  `inspect.getclosurevars` to confirm the cap integer reaches the
  setrlimit closure.
- **F2 (HIGH) — fixed.** New `TestLeanVerifyResultSchema` class (7
  Draft7Validator tests covering every envelope); `_normalize_response`
  clamps `severity` to the schema enum (unknown → "error") and coerces
  `text` / `goal` to `str(...)`.
- **F3 (MEDIUM) — fixed.** `LeanReplTimeoutError(LeanReplError)` subclass
  in `server/lean_repl.py`; handler catches it distinctly. Guard:
  `TestTimeoutDiscriminatorIsTypeNotSubstring`.
- **F4 (MEDIUM) — fixed.** Respawn-failure `except` narrowed to
  `(LeanUnavailableError, OSError)`; close-failure to `(OSError,
  LeanReplError)`. `CancelledError` propagates. Guard:
  `TestRespawnFailureNarrowExcept`.
- **F5 (MEDIUM) — fixed.** `_normalize_position` clamps with `max(0, ...)`.
  Guard: `TestPositionClampsNegatives`.
- **F6 (MEDIUM) — subsumed by F2.** Disabled / timeout / generic-error
  envelopes now Draft7Validator-validated.
- **F7 (LOW) — fixed.** Schema description reworded to match reality.
- **F8 (LOW) — fixed.** `len(imports_list) > MAX_IMPORTS` enforcement.
  Guard: `TestImportsListLengthDefenseInDepth`.
