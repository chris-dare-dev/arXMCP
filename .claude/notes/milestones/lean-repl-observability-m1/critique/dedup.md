# Critique (deduped) — lean-repl-observability-m1

**Critics merged:** milestone-adversary-critic, milestone-arxmcp-critic
**Commit range:** 21a859d..e0dd72c
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. Zero CRITICAL, zero HIGH. Both critics independently flagged the
SAME MEDIUM (health.py scrape-hook wiring untested with a live REPL —
**cross-critic agreement**, fix first). One LOW (adversary only): AC2 respawn
verified at harness level only, explicitly deferrable for a telemetry-only
milestone. Increment placement, disabled-path explicit zeroing, error-path
no-increment coverage, psutil-free dependency hygiene, no BP1 / tool-schema
contact, commit signing + co-author trailer, and F7 doc-drift all verified
correct by both critics.

## Findings

**M1 — health.py scrape-hook wiring has no live-REPL test** (MEDIUM)

**Cross-critic agreement:** flagged independently by milestone-adversary-critic
AND milestone-arxmcp-critic, both at `server/health.py:604` — fix first.
**Where:** `server/health.py:604`
**Anchor:** `    refresh_lean_repl_metrics(getattr(resources, "lean_repl"`
**What:** `TestLeanReplMetrics` calls `refresh_lean_repl_metrics(...)` directly and
never through `refresh_metrics_from_singleton_state`, so the
`getattr(resources, "lean_repl", None)` wiring is exercised only on the None
branch (via pre-existing fakes lacking the attribute) — never with a live REPL
where the gauge must reflect a nonzero count.
**Why it matters:** because the wiring uses `getattr(..., None)`, a rename/typo of
`Resources.lean_repl`, or a dropped line in a future refactor of
`refresh_metrics_from_singleton_state`, would silently drive both gauges to 0
forever — indistinguishable from the common default-off path — with the full
suite staying green. That silent-zero is the exact failure the milestone exists
to prevent.
**Proposed fix:** add a test mirroring `TestF2SingleflightCounter`
(`tests/test_server_metrics.py:463`): build a fully-shaped
`SimpleNamespace(..., lean_repl=SimpleNamespace(env_snapshot_count=7,
age_seconds=42.5), cache=None, config=None,
corpus_info=SimpleNamespace(version=1, chunk_count=2), startup_chunk_count=2,
process_start_time_seconds=0.0, is_resource_warm=lambda n: True)`, call
`refresh_metrics_from_singleton_state(fake)`, and assert
`LEAN_REPL_ENV_SNAPSHOTS_GAUGE._value.get() == 7.0` and the age gauge `== 42.5`;
a second call with `lean_repl=None` asserts both drop to `0.0` through the real
wiring.
**Regression-guard:** `tests/test_server_metrics.py::TestLeanReplMetrics::test_singleton_refresh_reflects_live_repl` (new) — fails if `server/health.py:604` is removed or `lean_repl` is renamed.
**Source critic:** milestone-adversary-critic + milestone-arxmcp-critic
**Source axis:** Test discipline / Test surface (AC1)

**L1 — AC2 respawn reset tested at harness level only** (LOW)

**Where:** `tests/test_lean_repl.py:527`
**Anchor:** `    def test_new_instance_resets_count_a`
**What:** AC2 (a per-query-timeout kill+respawn drops the gauge toward 0) is
validated by constructing a second `LeanRepl` and asserting it reads 0, not by
exercising the `lean_verify` handler's respawn assignment
(`resources.lean_repl = await LeanRepl.spawn_from_config(...)`,
`server/handlers/lean_verify.py:955`).
**Why it matters:** the gauge-drop guarantee depends on the handler replacing the
singleton with a fresh instance; a future change that reset the existing instance
in place would break AC2 while the harness test stays green. The arxmcp critic
independently confirmed the handler respawn path IS currently correct (`:955`
fresh instance, `:963` None on failure), so this is guard-hardening, not a live
defect.
**Proposed fix:** optional given telemetry-only scope — a light integration test,
or a comment cross-referencing `lean_verify.py:955`/`963` as the respawn/disable
sites that make the per-instance reset observable. Acceptable to defer.
**Regression-guard:** optional (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage (AC2)

Severity counts: C0 H0 M1 L1

## Recommended rectification order

M1 (cross-critic — fix), L1 (defer — LOW, telemetry-only scope)
