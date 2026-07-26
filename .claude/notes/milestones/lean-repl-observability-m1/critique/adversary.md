# Critique — lean-repl-observability-m1 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 21a859d..e0dd72c
**Diff stats:** 7 files, ~318 LOC (≈214 of which is regenerated `metrics_sample.txt` fixture churn)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. This is a tight, well-scoped telemetry-only milestone: the increment is placed correctly (successful round-trips only, under `_io_lock`), the disabled-path explicit `.set(0)` is right, error paths are exhaustively tested, and no lifecycle/schema/dependency surface was touched. The single actionable gap is a MEDIUM: the health.py scrape-hook wiring (`resources.lean_repl` → gauge) is never exercised end-to-end with a live REPL, so an attribute rename would silently zero the gauge the milestone exists to surface — and the repo already has an established precedent (the F2 singleflight test) for closing exactly this wiring class. Zero CRITICAL, zero HIGH.

## Executive summary

- [MEDIUM] The `refresh_metrics_from_singleton_state` → `refresh_lean_repl_metrics(resources.lean_repl)` wiring in `server/health.py` has no test driving it with a live REPL; a rename of `Resources.lean_repl` would silently zero the gauge with the full suite still green.
- [LOW] AC2 (respawn resets the gauge) is verified only at harness level (a fresh `LeanRepl` reads 0); no test ties the `lean_verify` handler's respawn (`resources.lean_repl = await LeanRepl.spawn_from_config(...)`) to a dropped gauge, though the handler code path is correct.
- Increment placement is correct and adversarially verified: timeout, EOF, non-JSON, and already-exited paths all raise before `self._env_snapshot_count += 1`, each with a dedicated no-increment test.
- Dependency hygiene clean: `psutil` was NOT sneaked in; RSS gauge properly deferred per brief.
- Commit hygiene clean: signed (good GPG sig), 44-char conventional subject, mandated co-author trailer present.
- Doc drift resolved: `lean-sandbox-design.md` §F7 "no in-product signal" caveat replaced with the shipped-gauge pointer + ops restart-threshold note (AC7 met).
- No external write, no one-writer-rule violation, no MCP tool-schema/BP1 hash touch (AC4 held structurally).

## Findings

**M1 — health.py scrape-hook wiring has no live-REPL test** (MEDIUM)

**Where:** `server/health.py:604`
**Anchor:** `    refresh_lean_repl_metrics(getattr(res`
**What:** The new tests (`TestLeanReplMetrics`) call `refresh_lean_repl_metrics(...)` directly and never through `refresh_metrics_from_singleton_state`, so the actual `getattr(resources, "lean_repl", None)` wiring is exercised only on the None branch (incidentally, via pre-existing fakes that lack the attribute) — never with a live REPL where the gauge must reflect a nonzero count.
**Why it matters:** Because the wiring uses `getattr(..., None)`, a rename/typo of `Resources.lean_repl` (or passing the wrong object) would silently drive both gauges to 0 forever — the exact silent-zero failure the milestone exists to prevent — and the full suite would stay green.
**Proposed fix:** Add a test mirroring `TestF2SingleflightCounter` (`tests/test_server_metrics.py:463`): build a `SimpleNamespace(..., lean_repl=SimpleNamespace(env_snapshot_count=4, age_seconds=9.0), cache=None, config=None, corpus_info=..., startup_chunk_count=..., process_start_time_seconds=0.0, is_resource_warm=lambda n: True)`, call `health_mod.refresh_metrics_from_singleton_state(fake_resources)`, and assert `LEAN_REPL_ENV_SNAPSHOTS_GAUGE._value.get() == 4.0` and the age gauge `== 9.0`. This locks the attribute name into a regression guard.
**Regression-guard:** `tests/test_server_metrics.py::TestLeanReplMetrics::test_scrape_hook_reflects_live_repl` (new).
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline / Acceptance coverage (AC1)

**L1 — AC2 respawn reset tested at harness level only** (LOW)

**Where:** `tests/test_lean_repl.py:527`
**Anchor:** `    def test_new_instance_resets_count_a`
**What:** AC2 ("a per-query-timeout kill+respawn drops the snapshot gauge toward 0") is validated by constructing a second `LeanRepl` and asserting it reads 0, not by exercising the `lean_verify` handler's respawn assignment (`resources.lean_repl = await LeanRepl.spawn_from_config(...)` at `server/handlers/lean_verify.py:955`).
**Why it matters:** The gauge-drop guarantee depends on the handler actually replacing the singleton with a fresh instance on timeout; a future change that reused/reset the existing instance in place would break AC2 while the harness test stays green.
**Proposed fix:** Optional given telemetry-only scope — a light integration test (or a comment cross-referencing `lean_verify.py:955`/`963` as the respawn-and-disable sites that make the per-instance reset observable) would close the loop. Acceptable to defer.
**Regression-guard:** optional (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage (AC2)

## What was done well

- **Increment placement is exactly right.** `self._env_snapshot_count += 1` sits after the timeout `except` and after `await asyncio.wait_for(...)` succeeds, inside `_io_lock`, before `return resp` (`server/lean_repl.py:370`) — the already-exited raise, the timeout raise, and `_round_trip`'s EOF/non-JSON `LeanReplError` all bypass it. Race-free with no new primitive.
- **Error-path no-increment cases are exhaustively covered** — dedicated tests assert `env_snapshot_count == 0` after timeout, EOF, non-JSON, and post-exit (`tests/test_lean_repl.py:499-525`), each a real counterexample to over-counting.
- **Disabled-path explicitness is correct and tested.** `refresh_lean_repl_metrics(None)` calls `.set(0.0)` on both gauges rather than no-op'ing, and `test_none_repl_sets_both_gauges_to_zero` seeds stale nonzero values first to prove the module-level-gauge-persistence hazard is handled.
- **Per-instance state initialised in `__init__`, not `spawn`** (`server/lean_repl.py:91`), so the direct-construction fake-proc test path gets it and a kill+respawn resets for free — a clean design choice with a matching test.
- **Dependency hygiene honored the brief:** no `psutil`, RSS gauge deferred and documented as deferred; portable count+age gauges are the floor.
- **No schema/hash cascade:** `tools.py`, `server/schemas/*`, BP1 untouched; AC4 holds structurally (no tool-surface change).
- **Fixture regenerated the right way:** `tests/fixtures/metrics_sample.txt` was produced by `tools/regen_metrics_fixture.py` (verified — `TestRegenFixture::test_regen_matches_checked_in_fixture` passes on this box); the large-looking churn is non-deterministic lines (`_created`/`python_*`) that `_normalize` strips, not hand-editing.
- **Commit hygiene clean:** good GPG signature, 44-char conventional subject, mandated `Co-Authored-By` trailer, thorough body; single `feat` commit is correct for the pre-rectify phase.
- **Doc drift closed (AC7):** the §F7 caveat now points at the shipped gauges with a concrete ops restart threshold; the R3-m7 forward-owner note updated from "scoped" to "shipped."
- **Within the data-plane boundary:** read-only operational telemetry, same class as the cache byte gauges; no corpus write, no agent memory.

Severity counts: C0 H0 M1 L1

## Recommended rectification order

M1, L1
