# Rectify summary — lean-repl-observability-m1

**Rect commit:** `51bfcc9` (`rect(lean-repl-observability-m1): close M1`, signed,
Reviewed-by both critics + co-author). Delegated to `milestone-rectifier`
(Phase-4 trigger #3: the implementer ran inline this session → fresh delegate
re-verifies).

## Dispositions

| Finding | Sev | Disposition | Note |
|---|---|---|---|
| M1 — health.py scrape-hook wiring untested with a live REPL (cross-critic) | MEDIUM | **fixed** | Added `TestLeanReplMetrics::test_singleton_refresh_reflects_live_repl` driving `refresh_metrics_from_singleton_state` with a live `lean_repl` fake (asserts gauges reflect 7 / 42.5) AND with `lean_repl=None` (asserts both drop to 0.0) — through the real `server/health.py:604` wiring. **Guard proven:** commenting out the wiring line made the test FAIL (`0.0 != 7.0`); restoring it passes. |
| L1 — AC2 respawn reset tested at harness level only | LOW | **deferred** | Telemetry-only scope; both critics confirmed the handler respawn path (`lean_verify.py:955` fresh instance / `:963` None-on-failure) is already correct, so this is guard-hardening, not a live defect. Adversary critic explicitly marked it "acceptable to defer". |

- **Invalidated:** none (invalidation rate 0% — well under the 40% re-critique threshold).
- **Regression tests added:** `tests/test_server_metrics.py::TestLeanReplMetrics::test_singleton_refresh_reflects_live_repl`.

## Gate (rectifier)

`uv run --extra dev python -m pytest tests/test_server_metrics.py tests/test_lean_repl.py`
→ 53 passed / 5 skipped (the `requires_lean_repl` real-REPL tests). `ruff check .`
clean. (The full default suite was confirmed green by the main session at
implement-complete; the rect change is test-only.)

## Commit triple

1. `e0dd72c` — `feat(server): REPL env-tree telemetry gauges`
2. `51bfcc9` — `rect(lean-repl-observability-m1): close M1`
3. chore(notes) — finalize milestone artifacts (this session, pre-boundary).

## Remaining

External-write boundary: land the commits on `main` (fast-forward/merge the
`claude/laughing-goldstine-b8ea4f` worktree branch → `main`, then push).
USER-GATED — not performed by the pipeline.
