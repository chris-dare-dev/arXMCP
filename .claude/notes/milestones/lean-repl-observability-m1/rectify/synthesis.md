# Rectify synthesis — lean-repl-observability-m1

## Dispositions
| id | disposition | detail |
|----|-------------|--------|
| M1 | fixed       | 51bfcc9 — tests/test_server_metrics.py::TestLeanReplMetrics::test_singleton_refresh_reflects_live_repl |
| L1 | deferred    | LOW; AC2 respawn tested at harness level, both critics agree handler respawn path is correct + deferrable for telemetry-only scope |

## Rect commit
- 51bfcc9 `rect(lean-repl-observability-m1): close M1`  (Reviewed-by trailers: milestone-adversary-critic, milestone-arxmcp-critic)

## Test deltas
- tests/test_server_metrics.py — new test drives the live + disabled Lean REPL gauges THROUGH the real `refresh_metrics_from_singleton_state` wiring (server/health.py:604), not the isolated `refresh_lean_repl_metrics` hook. Guards against a dropped scrape line or `Resources.lean_repl` rename silently zeroing both gauges with the suite green.

## Guard-works proof
- Commented out `server/health.py:604` wiring -> new test FAILED (`assert 0.0 == 7.0`).
- Restored the line -> test PASSES. Production code (health.py) is unchanged from HEAD; only the test file is committed.

## external_writes_required
- []  — none. (No push performed; main session gates any external write.)

## Check gate results
- pytest tests/test_server_metrics.py tests/test_lean_repl.py: PASS (53 passed, 5 skipped, exit 0)
- ruff check .: PASS (All checks passed!)
- git status: test file committed; untracked .claude/notes state + agent-memory intentionally NOT staged
