# Implementation synthesis — lean-repl-observability-m1

**Path:** inline (orchestrator-written). Production surface is 3 files / ~60 LOC
(well within the inline threshold); the remaining files are test + doc + a
regenerated fixture. **Base:** `21a859d`. **Feat commit:** `e0dd72c`.

## What shipped

Read-only `/metrics` telemetry for the long-lived Lean REPL child process,
surfacing the F7 unbounded env-snapshot growth so an operator can watch it and
restart before OOM. Two gauges:

- `arxmcp_lean_repl_env_snapshots` — successful `LeanRepl.query` round-trips
  served by the current instance (proxy for the REPL's append-only snapshot-tree
  size; the round-trip-counter proxy chosen per research D1).
- `arxmcp_lean_repl_age_seconds` — worker age (computed live).

## Files

| File | Change |
|---|---|
| `server/lean_repl.py` | `import time`; `__init__` gains `_spawn_monotonic` + `_env_snapshot_count`; `env_snapshot_count` / `age_seconds` read-only properties; `query()` increments the counter once per successful round-trip, inside the existing `_io_lock`, after `_round_trip` returns (never on the already-exited / timeout / EOF / non-JSON paths). |
| `server/metrics.py` | Two unlabeled gauges; `refresh_lean_repl_metrics(lean_repl \| None)` with an **explicit `.set(0.0)`** on the `None` branch (research D2 — module-level gauges persist, so a no-op leaks a stale value and fails AC3); `reset_lean_repl_metrics_for_tests()`; `TYPE_CHECKING` import of `LeanRepl`; `__all__`. |
| `server/health.py` | `refresh_lean_repl_metrics(getattr(resources, "lean_repl", None))` wired into `refresh_metrics_from_singleton_state` beside `refresh_cache_metrics`. |
| `tests/test_lean_repl.py` | `TestObservabilityTelemetry`: counter increments per success; NOT on timeout/EOF/non-JSON/after-exit; new-instance reset (AC2 at harness level); age non-negative + non-decreasing. |
| `tests/test_server_metrics.py` | `TestLeanReplMetrics`: `None` → both gauges 0 (after seeding stale values — AC3); live repl reflects count+age; live→disabled returns to 0; exposition presence. `reset_lean_repl_metrics_for_tests()` added to the `reset_all_metrics` fixture. |
| `tests/fixtures/metrics_sample.txt` | Regenerated (`tools/regen_metrics_fixture`) — the two gauges render at `0.0`, which is the accurate default (REPL disabled). |
| `.claude/docs/lean-sandbox-design.md` | F7 § "no in-product signal today" replaced with the shipped-gauge pointer + ops restart-threshold note; forward-owner cross-ref updated to shipped tense (AC7). |

## AC status

1. count non-decreasing / age increasing — ✅ (harness + scrape-hook tests).
2. respawn resets — ✅ (fresh instance; harness test).
3. disabled path reads 0 — ✅ (explicit `.set(0)` + test seeding a stale value first).
4. `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` unchanged — ✅ (full suite green; `/metrics` is a disjoint ASGI mount).
5. RSS gauge — **deferred** (research D3: `psutil` not a dep, no portable Windows reader). The honest AC5 branch on this host is "absent".
6. `make test` green — ✅ ruff clean; full default pytest suite exit 0 (one expected golden-fixture drift fixed by regenerating `metrics_sample.txt`).
7. doc § F7 updated — ✅.

## Gate results

- `ruff check .` → clean (exit 0).
- `pytest` (full default suite, worktree `.venv` + `--extra dev`) → exit 0. The
  affected files (`test_lean_repl.py` + `test_server_metrics.py`) → 56 passed /
  5 skipped (the `requires_lean_repl` real-REPL tests).

## Deviations / notes

- **File count > 5** (7 tracked): driven entirely by test (2) + doc (1) +
  regenerated fixture (1) surface. Production code is 3 files / ~60 LOC, coherent
  and single-purpose — the inline-scope guard's intent (runaway production
  complexity) is not triggered. Proceeded inline.
- **Fixture drift** (`test_daily_metrics_report.py::TestRegenFixture`) was the
  only initial failure — expected when a new metric family is added; fixed by
  regenerating per the tool's own documented workflow. Gauges render at `0.0`
  (default REPL-off), so no synthetic seeding was added to the regen tool.
- Ran in the `claude/laughing-goldstine-b8ea4f` worktree (fast-forwarded to
  `main` for the brief). Landing on `main` is the Phase-4 external write.
