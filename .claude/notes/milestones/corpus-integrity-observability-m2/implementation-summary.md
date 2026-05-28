# Implementation Summary — corpus-integrity-observability-m2

**One-line:** A startup reconciliation invariant compares the marker's
`chunk_count` against a once-cached `count_rows()`; divergence beyond a
configurable tolerance logs a WARN, flips `/readyz` to `degraded
(reason=chunk_count_diverged)`, and is exposed via two `/metrics` gauges.

**Commit range:** `a54f8f3..<HEAD>` (this feat commit)

**Implementation path:** INLINE — 3 source files (`server/config.py`,
`server/resources.py`, `server/health.py`, ~95 LOC) + 1 new test file. Purely
local. Depends on m1 (marker now table-derived; shipped `8e58c42`).

## What landed

- **`server/config.py`** — `corpus_chunk_count_tolerance: float = 0.05`
  (`ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE`) with a `[0.0, 1.0]` `@field_validator`
  mirroring `validate_eq_ted_weight`.
- **`server/resources.py`** —
  - New module-level pure helper `compute_chunk_count_divergence(marker, actual,
    tolerance) -> str | None` returning `"rows_added"` / `"rows_lost"` / `None`.
    Handles FM-2 (`actual < 0` sentinel), FM-3 (zero-marker, no div-by-zero),
    FM-4 (1-row absolute floor), FM-6 (symmetric direction). Extracted so the
    decision is exhaustively unit-testable without booting the server.
  - New `Resources.startup_chunk_count: int = -1` field (cached once at startup).
  - New step 2b in `startup()`: after the LanceDB open and before the BM25 scan,
    `count_rows()` via `run_in_executor` (sync I/O) wrapped in try/except (FM-2
    non-fatal). Reconciliation runs ONLY when `degraded is None` (FM-7: a
    pre-existing `corpus_corruption` fallback is more severe and is not
    clobbered). On divergence: WARN with `marker/actual/direction/tolerance` +
    `degraded = DegradedState(reason="chunk_count_diverged",
    fallback_version=version, original_version=version)` (D2 sentinel).
- **`server/health.py`** — two scalar gauges `CORPUS_CHUNK_COUNT_MARKER` +
  `CORPUS_CHUNK_COUNT_ACTUAL` beside `CORPUS_VERSION_GAUGE`; set in
  `refresh_metrics_from_singleton_state` from the cached fields (O(1), getattr-
  defended, NO `count_rows()` at scrape); `"chunk_count_diverged"` added to the
  zero-out enumeration in `refresh_degraded_mode_metric`; both gauges added to
  `__all__`. `/readyz` needs NO change — the existing degraded path serializes
  the new reason.

## Acceptance criteria

1. ✅ **Divergence > tolerance ⇒ WARN + degraded.**
   `TestStartupReconciliation::test_divergent_marker_degrades_and_warns` boots
   `Resources.startup` (mocked model) against a marker rewritten to 1000 vs a
   real 2-row table; asserts `degraded.reason == "chunk_count_diverged"`,
   `startup_chunk_count == 2`, and the WARN log fires with `marker=1000 actual=2`.
   `TestReadyzChunkCountDivergedBody` asserts `/readyz` returns 503 with
   `reason=chunk_count_diverged`.
2. ✅ **Matching counts ⇒ clean + gauges equal.**
   `test_matching_marker_not_degraded` (degraded is None on matching counts);
   `test_gauges_set_from_cache_not_recomputed_per_scrape` (both gauges == 2).
3. ✅ **Single cached count, never per scrape.** Gauges read
   `resources.startup_chunk_count` / `corpus_info.chunk_count` (cached ints).
   `test_gauges_set_from_cache_not_recomputed_per_scrape` drives 3 scrapes and
   asserts `chunks_table.count_rows` is NEVER called; the integration boot test
   asserts the real count was cached once. (The single startup call site +
   the scrape-never-calls test together pin "at most once".)
4. ✅ **X-gates.** `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`
   UNCHANGED (no MCP tool surface touched; `/readyz` + `/metrics` are
   operational endpoints). `tests/test_server_tool_schema.py` +
   `tests/test_prompts.py` green. `make test` green.

## New / changed test paths

- `tests/test_corpus_count_reconciliation.py` (new) — 17 tests:
  - `TestComputeChunkCountDivergence` (10) — the pure decision core, all edge
    cases (tolerance boundary, FM-2/3/4/6, zero-tolerance floor).
  - `TestStartupReconciliation` (2) — real boot, diverged + matching.
  - `TestReadyzChunkCountDivergedBody` (1) — `/readyz` reason wiring.
  - `TestChunkCountGauges` (3) — gauge wiring, never-per-scrape (AC-3),
    divergence-delta exposure, `-1` count-unavailable sentinel.
  - `TestDegradedModeEnumeration` (1) — `chunk_count_diverged` zeroed on recovery.

## Deviations from the brief's design

- **Extracted `compute_chunk_count_divergence` as a pure module-level helper**
  (the synthesis described inline logic). Reason: makes the FM-2/3/4/6 edge
  cases exhaustively unit-testable without booting the server — the
  determinism-reviewer concern the roadmap flagged. No behavioral change.
- **Defensive `getattr` on the two gauge reads** (not in the synthesis): a
  partial/duck-typed `Resources` (startup race window, or a minimal test fake)
  reports the `-1` sentinel rather than raising inside a `/metrics` scrape
  handler. This also fixed a latent break in an existing
  `test_server_metrics.py` fake that omits `chunk_count`.

## External writes required

**None** — purely local. No git push, PR, infra, or third-party API.
