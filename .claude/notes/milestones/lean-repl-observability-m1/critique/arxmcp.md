# Critique — lean-repl-observability-m1 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 21a859d..e0dd72c
**Diff stats:** 7 files, 318 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The change is a clean, correctly-scoped read-only telemetry addition: two unlabeled gauges on the disjoint `/metrics` mount, no MCP-surface / BP1 / tool-schema contact, no new runtime dependency (psutil correctly deferred), and the env-tree *bounding* was correctly NOT built here. The env-snapshot increment is race-free under the existing `_io_lock` and provably unreachable on every failure path, and the disabled-`None` path explicitly zeroes both gauges to avoid stale module-level series. The one gap: the load-bearing wiring line in `server/health.py` (the scrape hook that pulls a *live* REPL's telemetry through `refresh_metrics_from_singleton_state`) has no covering test — deleting it leaves the entire suite green.

## Executive summary

- [MEDIUM] The `health.py` scrape-hook wiring (`refresh_lean_repl_metrics(getattr(resources, "lean_repl", None))`) is untested; `TestLeanReplMetrics` calls the refresh fn directly, never through `refresh_metrics_from_singleton_state`, so the milestone's raison d'être (live gauge at `/metrics`) is not regression-guarded.
- [CLEAN] Axis 1 cache byte-stability / BP1: `server/tools.py`, `server/prompts.py`, `TOOL_SCHEMA_VERSION` untouched; gauges live on the disjoint `/metrics` ASGI mount — `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256` structurally cannot change.
- [CLEAN] Axis 3 security: read-only int counter + `time.monotonic` age; no untrusted input, no new subprocess, no psutil/ctypes/RSS surface (RSS deferred as briefed).
- [CLEAN] Axis 4 MCP compliance: no tool contract change; telemetry is off the MCP surface.
- [CLEAN] Axis 5 local-first: psutil absent from `pyproject.toml`/`uv.lock` (both untouched in range); stdlib `time` + already-pinned `prometheus_client` only.
- [CLEAN] Axis 6 boundary §4.8: server-internal operational telemetry (like the cache byte gauges); no corpus write; env-tree bounding correctly left to R3 m7.
- [CLEAN] Axis 8 (mostly): increment/timeout/EOF/non-JSON/exited/respawn-reset all covered; reset helper wired into `reset_all_metrics` both before and after `yield`; fixture regenerated at 0.0 (default REPL-off).

## Findings

**M1 — Live scrape-hook wiring in health.py has no covering test** (MEDIUM)

**Where:** `server/health.py:604`
**Anchor:** `    refresh_lean_repl_metrics(getattr(resources, "lean_repl"`
**What:** The one line that surfaces a *live* REPL's telemetry at `/metrics` — the call from `refresh_metrics_from_singleton_state` — is exercised by no test; `TestLeanReplMetrics` (tests/test_server_metrics.py:620) calls `refresh_lean_repl_metrics` directly, and the existing `refresh_metrics_from_singleton_state` tests (tests/test_server_metrics.py:496, tests/test_corpus_count_reconciliation.py:327) use `SimpleNamespace` fakes with no `lean_repl` field and assert nothing about the lean gauges.
**Why it matters:** Deleting or dropping this line during a future refactor of `refresh_metrics_from_singleton_state` leaves the whole suite green while the gauges silently read 0 forever — indistinguishable from the (common, default-off) disabled path, so the regression is invisible; the milestone's entire deliverable is that a *live* REPL's snapshot growth reaches `/metrics`.
**Why it matters (invariant):** Wiring-untested-while-impl-tested — the load-bearing selector/route is what ships, not the unit under it.
**Proposed fix:** Add one test that calls `health.refresh_metrics_from_singleton_state` with a `SimpleNamespace(..., lean_repl=SimpleNamespace(env_snapshot_count=7, age_seconds=42.5))` and asserts `LEAN_REPL_ENV_SNAPSHOTS_GAUGE._value.get() == 7.0` and the age gauge `== 42.5`; a second call with `lean_repl=None` asserting both drop to `0.0` covers the disabled branch through the real wiring.
**Regression-guard:** `tests/test_server_metrics.py::TestLeanReplMetrics::test_singleton_refresh_reflects_live_repl` (new) — fails if `server/health.py:604` is removed.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Test surface

## What was done well

- Env-snapshot increment placed at `server/lean_repl.py:370`, inside `_io_lock` and after the timeout re-raise, so it is race-free with no new primitive and provably unreachable on the already-exited, timeout, EOF, and non-JSON paths — each of those is pinned by a dedicated negative test (tests/test_lean_repl.py:266-305).
- The `None`-REPL branch (`server/metrics.py:406`) *explicitly* zeroes both gauges rather than no-op'ing, correctly defusing the module-level stale-series hazard, and `test_disabled_after_live_returns_to_zero` proves live→disabled returns to 0.
- No BP1 / tool-schema contact: the change is confined to `/metrics`, so byte-stability of `tools/list` and the BP1 cache breakpoint is structurally preserved — the highest-risk arXMCP axis is untouched.
- psutil / RSS correctly deferred; no new runtime dependency, keeping the local-first + no-new-dep constraint intact (`pyproject.toml`/`uv.lock` unchanged in range).
- Respawn-reset is genuine end-to-end, not just a comment: the timeout path assigns a fresh instance (`server/handlers/lean_verify.py:955`) or `None` on respawn failure (`:963`), so age/count actually drop at the next scrape; the harness test `test_new_instance_resets_count_and_age` mirrors it.
- `reset_lean_repl_metrics_for_tests` is wired into `reset_all_metrics` on both the pre-`yield` and post-`yield` legs (tests/test_server_metrics.py:143,151), preventing cross-test gauge leakage from an unlabeled module-level Gauge.
- The regenerated `tests/fixtures/metrics_sample.txt` shows both gauges at `0.0` (the correct default REPL-off state) and stays consistent with the deterministic `regen_metrics_fixture` round-trip check (tests/test_daily_metrics_report.py:356).
- Honest labeling: both docstrings and the gauge `help` text call the count a *proxy* for the snapshot tree (one round-trip ≈ one immutable snapshot) rather than overclaiming an exact tree size — good trust-language hygiene per §4.9.

Severity counts: C0 H0 M1 L0

## Recommended rectification order

M1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
