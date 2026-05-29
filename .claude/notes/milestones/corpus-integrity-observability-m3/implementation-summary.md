# Implementation Summary — corpus-integrity-observability-m3

**One-line:** A startup HNSW unindexed-rows tripwire (scout CAND-10) — at
`Resources.startup` the server sums `num_unindexed_rows` across the ANN indexes
once, caches it, and exposes `arxmcp_corpus_unindexed_rows`; non-zero is always
abnormal (silent brute-force-ANN-fallback) → WARN. Mirrors m2 verbatim.

**Implementation path:** INLINE — 3 source files + the regenerated metrics fixture
+ tests. Purely local.

## What landed

- **`server/resources.py`** — new module-level pure helper
  `compute_unindexed_rows(table) -> (value, breakdown)`: discovers ANN index names
  via `table.list_indices()` (never hardcoded), sums `index_stats(name).num_unindexed_rows`
  (guarding `None`), and returns the **D2 sentinel**: `-1` when no resolvable ANN
  index exists (a never-indexed corpus brute-forces everything — `0` there would be
  a false-clean), `0` when ≥1 index all-clean, `>0` when abnormal. New
  `Resources.startup_unindexed_rows: int = -1` field. New "step 2c" block in
  `startup()` (after the m2 count_rows block): FM-7 skip when `degraded` already set;
  else `run_in_executor(compute_unindexed_rows)` in a try/except → `-1` + WARN on any
  API failure (FM-1/FM-2, never aborts startup); WARN naming the per-index breakdown
  on `>0`; WARN "coverage unknown" on `-1`. Passed to `cls(...)`.
- **`server/health.py`** — `CORPUS_UNINDEXED_ROWS` scalar gauge beside the m2 corpus
  gauges; set once in `refresh_metrics_from_singleton_state` from the cached field,
  getattr-defended; added to `__all__`. NO degraded-reason added (D1).
- **`tests/fixtures/metrics_sample.txt`** — regenerated (the gauge appears at `0.0`,
  matching the corpus-gauge precedent; no `populate_registry` seed needed).

**Design decisions carried (synthesis §3):**
- **D1 — WARN + gauge ONLY, NOT a `/readyz` degrade.** Brute-force ANN serves
  CORRECT results (perf-only); a 503 would eject a correct-serving server.
  `refresh_degraded_mode_metric` zero-out tuple UNCHANGED.
- **D2 — no-index ⇒ `-1`, not `0`** (distinguishes "fully indexed" from "could not
  determine"; avoids a false-clean on a never-indexed corpus).

## Acceptance criteria

1. ✅ Unindexed rows → WARN + non-zero gauge:
   `TestUnindexedRowsStartup::test_unindexed_rows_warns_and_caches` (7 unindexed →
   `startup_unindexed_rows == 7`, "unindexed HNSW rows" WARN, not degraded).
2. ✅ Fully-indexed → 0, no WARN: `test_fully_indexed_no_warn`.
3. ✅ API unavailable / no index → `-1` + WARN + `/readyz` still boots:
   `test_index_api_raises_is_nonfatal` (warm, `startup_unindexed_rows == -1`,
   "index_stats()/list_indices() unavailable" WARN) + the pure-helper no-index/all-None
   `-1` cases.
4. ✅ Gauge set once, never per scrape:
   `TestUnindexedRowsGauge::test_gauge_set_from_cache_not_recomputed_per_scrape`
   (3 scrapes; `list_indices`/`index_stats` Mocks `assert_not_called`; gauge == cached).
5. ✅ FM-7 startup regression (degraded ⇒ unindexed check skipped, not clobbered):
   `TestStartupReconciliation::test_corpus_corruption_not_clobbered` extended
   (`startup_unindexed_rows == -1` + "skipping unindexed-rows check").
6. ✅ `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED (no MCP tool /
   prompts.py); no `CHUNKER_VERSION` bump; `make test` green (incl. regenerated fixture).

## New / changed test paths

- `tests/test_corpus_count_reconciliation.py` — `TestComputeUnindexedRows` (5, pure
  D2 core), `TestUnindexedRowsStartup` (3, real boot via a list_indices/index_stats
  table proxy), `TestUnindexedRowsGauge` (2, gauge wiring + never-per-scrape), + the
  FM-7 assertion folded into `test_corpus_corruption_not_clobbered`.

## Deviations from the synthesis

- **Extracted `compute_unindexed_rows` as a module-level pure helper** (the synthesis
  sketched a nested closure). Reason: makes the D2 sentinel rule exhaustively
  unit-testable without booting the server (mirrors m2's `compute_chunk_count_divergence`).
- **No `tools/regen_metrics_fixture.py` seed edit** (both briefs assumed one): the
  existing corpus gauges (`CORPUS_CHUNK_COUNT_*`) are NOT seeded in `populate_registry`
  — they render at `0.0` via the side-effect import. The new gauge follows that
  precedent; only the fixture regeneration was needed.

## External writes required

**None** — purely local.
