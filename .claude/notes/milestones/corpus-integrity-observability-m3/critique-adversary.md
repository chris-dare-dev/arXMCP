# Critique — corpus-integrity-observability-m3

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** 9ac322a9b3095426921ca33594897a37266fd65d..b2b21d7707740033fdd0ac042a0169f0a28dc4ac
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the m2 critique's two HIGH gaps (FM-7 + FM-2-nonfatal at
  boot) are genuinely closed, but the D2 sentinel — the milestone's stated
  cardinal correctness point — is broken against a real LanceDB table.
- Finding counts: 0 CRITICAL, 1 HIGH, 1 MEDIUM, 1 LOW.
- Highest-risk: `server/resources.py:577` — `compute_unindexed_rows` counts the
  scalar `paper_id` BTree index as an "ANN index" (no `index_type` filter),
  contradicting synthesis §2 and admitting the exact D2 false-clean it exists to
  prevent. EMPIRICALLY CONFIRMED against a real seeded table (returns
  `(0, ['embedding_stmt_idx=0', 'paper_id_idx=0'])`).
- Test-surface pattern (the load-bearing axis): every test stubs `list_indices`
  with fake vector-only namespaces that have NO `index_type` and NO scalar
  index, so the real production index inventory is never exercised — the F1
  defect is invisible to all 42 tests.
- The `elif startup_unindexed_rows < 0` boot WARN branch (no-index via empty
  `list_indices()` / all-`None` `index_stats`) is reachable but unpinned — only
  the pure helper and the *API-raises* branch are tested at boot.
- FM-7 guard is correctly pinned: empirically a real 2-chunk corpus returns `0`
  (not `-1`), so `test_corpus_corruption_not_clobbered`'s `== -1` assertion DOES
  fail if the `degraded is not None` guard is removed. Mutation-valid.
- Axis 1 (cache byte-stability) verified clean: no `server/tools.py` /
  `server/prompts.py` / hash-pin file touched; the gauge never enters a
  prompt-cache key or tool payload. Axes 2/4/5/6/7 clean (N/A or untouched).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — D2 sentinel counts the scalar paper_id index as an ANN index

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/resources.py:577 (`for cfg in table.list_indices():` — the
  unfiltered loop body, lines 577-585)
- **What:** `compute_unindexed_rows` iterates EVERY index from
  `table.list_indices()` and counts each toward `index_count`, with no filter on
  index type. The synthesis §2 claimed `list_indices()` "returns ANN/vector
  indexes only" — this is FALSE for lancedb 0.30.2. EMPIRICALLY VERIFIED against
  a real seeded corpus: `list_indices()` returns BOTH `embedding_stmt_idx`
  (`index_type='IvfHnswSq'`) AND `paper_id_idx` (`index_type='BTree'`, built
  unconditionally by `ingest/store.py:628 _create_indices` →
  `create_scalar_index("paper_id")`). `compute_unindexed_rows` returns
  `(0, ['embedding_stmt_idx=0', 'paper_id_idx=0'])` — the scalar index is summed
  and named in the breakdown.
- **Why it matters:** This corrupts the cardinal D2 sentinel. D2's whole purpose
  (synthesis §3, §1) is "no resolvable *ANN* index ⇒ -1, because a never-indexed
  corpus brute-forces EVERYTHING and reporting 0 there is a dangerous
  false-clean." But the scalar `paper_id_idx` is built in normal operation EVEN
  WHEN both embedding columns are all-NULL and the vector indexes are skipped
  (`ingest/store.py:607-613` skips empty vector columns but
  `create_scalar_index` at :628 still runs). On such a vector-index-less corpus,
  `index_count` becomes ≥1 → the helper returns `0` ("checked & clean") instead
  of `-1` ("could not determine") — the precise false-clean D2 was designed to
  prevent. Separately, on a partial-write where only the scalar index lags, its
  `num_unindexed_rows` is misattributed to "unindexed HNSW rows" in the WARN
  (resources.py:585). The gauge can lie about ANN coverage in exactly the
  scenario it was built to detect.
- **Proposed fix:** Filter to vector indexes inside the loop. Both `cfg` and the
  stats object expose a type field (`cfg.index_type == 'IvfHnswSq'`;
  `stats.index_type == 'IVF_HNSW_SQ'`). Add, after `stats = ...; if stats is
  None: continue`: `idx_type = (getattr(stats, "index_type", "") or
  "").upper(); if "HNSW" not in idx_type and "IVF" not in idx_type: continue`
  (skip non-vector indexes BEFORE incrementing `index_count`). Update the
  synthesis §2 line ("returns ANN/vector indexes only") to record the
  live-verified truth. Keep `getattr`-defended so a stub without `index_type`
  (the existing unit fakes) still works — but see F2/regression-guard: the fakes
  must be upgraded to carry a vector `index_type` so the filter is actually
  exercised.
- **Regression guard:** Two tests. (1) Extend `TestComputeUnindexedRows` with a
  fake table whose `list_indices()` returns a vector index (`num_unindexed_rows=0`,
  `index_type='IVF_HNSW_SQ'`) AND a scalar index (`index_type='BTREE'`); assert
  the scalar index is NOT counted (breakdown == `['embedding_stmt_idx=0']`,
  value `0`). (2) A pure-helper case where ONLY a scalar index exists → assert
  value `-1` (no resolvable ANN index), which fails today (returns `0`). Both
  fail on the current unfiltered code.

### F2 — no-index-at-boot (empty list_indices / all-None) path is unpinned

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/resources.py:592-598 (the `elif startup_unindexed_rows < 0:`
  WARN branch)
- **What:** Three startup tests exist: unindexed>0 (line 549), fully-indexed
  (line 582), and `list_indices()` *raising* (line 609, hits the `except`
  branch + its "index_stats()/list_indices() unavailable" WARN). The fourth boot
  path — `list_indices()` returns `[]` cleanly (no exception), OR every
  `index_stats()` returns `None` (FM-3) — flows through the `else` block to the
  DISTINCT `elif startup_unindexed_rows < 0` branch and its DISTINCT WARN ("no
  resolvable ANN index found … coverage UNKNOWN", resources.py:593-597). No test
  reaches this branch at boot: grep for "no resolvable ANN index" / "coverage
  UNKNOWN" across `tests/` returns nothing. The empty-list and all-`None` cases
  are covered ONLY by the pure helper (`test_no_index_returns_minus_one_not_zero`
  line 518, `test_all_stats_none_returns_minus_one` line 527).
- **Why it matters:** The two `-1` sources (API-raises vs no-resolvable-index)
  produce DIFFERENT WARN messages and reach the cache field via DIFFERENT code
  paths (the `except` block vs the `else`→`elif` block). AC-3 (synthesis §5.3)
  bundles "raising OR no ANN index present" but the test only proves the raising
  half end-to-end. A future edit that drops or mis-conditions the
  `elif < 0` branch (e.g. makes it `elif startup_unindexed_rows == -1` after some
  other negative value is introduced, or removes the WARN entirely) would leave a
  never-indexed corpus SILENT at boot — no operator signal that ANN coverage is
  unknown — with no failing test. This is the same "verified-by-reading-not-
  pinned" class the m2 adversary flagged for FM-7.
- **Proposed fix:** Add `TestUnindexedRowsStartup::test_no_resolvable_index_warns`:
  patch `open_chunks_table_with_fallback` to return a proxy whose `list_indices`
  returns `[]` (no raise), boot startup, assert
  `resources.startup_unindexed_rows == -1`, `resources.warm is True`,
  `resources.degraded is None`, and that the "no resolvable ANN index found"
  WARN fired (NOT the "unavailable" WARN). Optionally a second case with
  `index_stats=lambda n: None` over a non-empty `list_indices()` to pin FM-3 at
  boot.
- **Regression guard:** The test above — fails if the `elif startup_unindexed_rows
  < 0` branch (resources.py:592) is removed or its WARN string changes.

### F3 — dead assignment `_idx_breakdown = []` in the except branch

- **Severity:** LOW
- **Source:** adversary
- **File:** server/resources.py:575
- **What:** `_idx_breakdown = []` inside the `except` block is never read.
  `_idx_breakdown` is only consumed at resources.py:590 inside the `else:` block
  of the `try/except/else`, which is mutually exclusive with the `except`. When
  the `try` succeeds `_idx_breakdown` is bound at line 568; when it fails the
  `else` never runs, so line 575's assignment is dead. Ruff does not flag it
  because the `_`-prefix exempts it from the unused-variable lint.
- **Why it matters:** Pure noise — no behavioral consequence. Worth removing so a
  future reader doesn't assume the `except` branch feeds the breakdown into a
  WARN (it doesn't).
- **Proposed fix:** Delete line 575. (Defer per LOW policy.)
- **Regression guard:** None required (no behavior change).

## What was done well

- The two HIGH gaps from the m2 adversary critique are genuinely closed: FM-7 is
  folded into `test_corpus_corruption_not_clobbered` (asserts both
  `startup_unindexed_rows == -1` AND the "skipping unindexed-rows check" INFO),
  and the FM-2/FM-1 nonfatal-at-boot path has a real boot test
  (`test_index_api_raises_is_nonfatal`).
- FM-7 mutation-validity holds empirically: a real seeded 2-chunk corpus returns
  `0` (not `-1`) from `compute_unindexed_rows`, so the `== -1` assertion truly
  fails if the `degraded is not None` guard is removed — not a vacuous guard.
- D1 (WARN-not-degrade) is implemented correctly and tested: `degraded is None`
  on the unindexed>0 path (line 575 of the test), and
  `refresh_degraded_mode_metric`'s zero-out tuple is untouched — no misleading
  unset label was added.
- The AC-4 never-per-scrape gauge guard is a REAL guard, not trivially true:
  `refresh_metrics_from_singleton_state` reads only the cached int, and the test
  mocks `chunks_table.list_indices`/`index_stats` with `assert_not_called`, which
  WOULD fire if someone regressed the setter to recompute per scrape.
- Cache byte-stability respected: no `server/tools.py` / `server/prompts.py` /
  `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256` touched; the gauge never
  enters a prompt-cache key.
- The metrics fixture was correctly regenerated without a `populate_registry`
  seed: the gauge renders at `0.0` via `server.health`'s side-effect import
  (matching the m2 corpus-gauge precedent), and `TestRegenFixture` reproduces the
  on-disk bytes (verified green).
- `getattr`-defended gauge setter (`getattr(resources, "startup_unindexed_rows",
  -1)`) tolerates a partial/duck-typed `Resources`, and the gauge was added to
  `__all__`.
- The pure-helper extraction (`compute_unindexed_rows`) mirrors m2's
  `compute_chunk_count_divergence` and makes the sentinel rule unit-testable
  without booting — a sound deviation from the nested-closure sketch.
- `int(stats.num_unindexed_rows)` coercion defends against a `float`/`np.int`
  stat; the `None` stat is guarded BEFORE the `int()`, so no `TypeError` risk.
- No new dependency, no `assert` for invariants, no `BaseHTTPMiddleware`, no
  fork, no external write — all banned-pattern / constraint axes clean.
- Security: the WARN messages carry only index names + integer counts (no paths,
  no secrets, no agent input); `compute_unindexed_rows` runs on the
  config-derived `chunks_table` only — Axis 3 clean.

## Recommended rectification order

1. **F1** (HIGH) — filter `compute_unindexed_rows` to vector index types and fix
   the synthesis §2 claim. Highest blast radius: it corrupts the D2 sentinel on
   the real production path. Land the two regression tests in the same change so
   the scalar-index contamination is permanently pinned (and upgrade the existing
   stubs to carry an `index_type`).
2. **F2** (MEDIUM) — add the no-resolvable-index boot test for the
   `elif < 0` WARN branch. Cheap (~20 LOC, mirrors the existing proxy fixtures).
   Best landed alongside F1 since both touch the same test fixtures.
3. **F3** (LOW) — delete the dead `_idx_breakdown = []`. Defer per LOW policy.

## Rectification status

- **F1 (HIGH) — FIXED.** `compute_unindexed_rows` now filters to VECTOR index
  types: after fetching `stats`, it reads `index_type` (from `cfg` with a `stats`
  fallback) and `continue`s on any index whose type lacks `HNSW`/`IVF` — so the
  scalar `paper_id` BTree no longer counts toward `index_count` or the breakdown.
  This restores the D2 sentinel: a vector-index-less corpus (only the scalar
  index) now correctly returns `-1`, not a false-clean `0`. Re-verified against
  `_create_indices` (docstring: "plus a scalar index on paper_id"). Regression
  guards: `TestComputeUnindexedRows::test_scalar_only_corpus_returns_minus_one`
  (scalar-only → -1; FAILS on the pre-fix unfiltered code which returned 0) +
  `test_scalar_index_is_not_counted` (vector+scalar → breakdown excludes the
  scalar). The existing unit/startup stubs were upgraded to carry `index_type`
  (incl. a scalar `paper_id_idx` in the non-zero startup proxy) so the filter is
  actually exercised. Synthesis §2's "vector-only" claim corrected.
- **F2 (MEDIUM) — FIXED.** Added
  `TestUnindexedRowsStartup::test_no_resolvable_index_warns_at_boot`: boots with a
  proxy whose `list_indices()` returns `[]` (no exception), asserts
  `startup_unindexed_rows == -1`, warm, not degraded, and the DISTINCT "no
  resolvable ANN index found" WARN fired (NOT the API-raises "unavailable" WARN).
  Pins the `elif startup_unindexed_rows < 0` boot branch end-to-end.
- **F3 (LOW) — FIXED.** Deleted the dead `_idx_breakdown = []` assignment in the
  `except` branch (never read — the breakdown is only consumed in the mutually
  exclusive `else`).

**Invalidation summary:** 3 findings (0 CRITICAL, 1 HIGH, 1 MEDIUM, 1 LOW). All 3
FIXED. 0 invalidated (F1 re-verified real against `_create_indices` + the live
`list_indices()` inventory the critic empirically reproduced). Adversary
invalidation rate: 0%. Sub-agent-implemented; the fresh-eyes critique caught the
real production index inventory (scalar paper_id) that every stubbed test missed —
the cardinal D2 correctness fix.
