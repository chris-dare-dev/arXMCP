# Critique — corpus-integrity-observability-m2

**Critic:** adversary
**Generated:** 2026-05-28T21:51:48Z
**Commit range:** 6e18e96e5cb08349c1687c86ac36346849b49365..513aeb61472befe8ace53bc5bd7bc14c1fb22be5
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the core logic and edge-case math are solid, but the
  explicitly-required FM-7 regression test was never written, leaving the
  TOP-RISK guard unpinned.
- Finding counts: 0 CRITICAL, 2 HIGH, 3 MEDIUM, 1 LOW.
- Highest-risk gap: `server/resources.py:447` — the `degraded is not None`
  clobber guard (FM-7, brief-2's TOP RISK) has zero startup-level test; a future
  reorder would silently regress.
- Test-surface pattern: three of the design's named failure modes (FM-7, FM-2-at-
  startup) and the new config validator are reasoned-but-not-tested — the pure
  helper is exhaustively covered, the integration boundaries are not.
- Cache byte-stability (Axis 1) verified clean: no `ALL_TOOLS` / prompt / hash
  file touched; gauges and `reason` never enter a cache key or tool payload.
- The `getattr` defense (`health.py:281`) is asymmetric and admits to masking a
  pre-existing test-fake break — a code-smell worth tightening, not a prod bug.
- Math fidelity (Axis 2), MCP spec (Axis 4), local-first (Axis 5), no-fork
  (Axis 7) all verified clean — N/A or untouched on this diff.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — FM-7 clobber guard (TOP RISK) has no startup regression test

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/resources.py:447
- **What:** The `if degraded is not None:` guard that prevents a
  `chunk_count_diverged` state from clobbering a pre-existing
  `corpus_corruption` fallback is the design's stated TOP RISK (synthesis §4
  FM-7, brief-2). `open_chunks_table_with_fallback` genuinely returns
  `DegradedState(reason="corpus_corruption", ...)` on the N-1 fallback
  (`server/corpus.py:224-227`), so this is a reachable common path — yet no test
  in `tests/test_corpus_count_reconciliation.py` boots `Resources.startup` with a
  pre-set `corpus_corruption` degraded state.
- **Why it matters:** The synthesis §5 (line 130) AND §6 (line 153) BOTH list
  "FM-7 (corpus_corruption not clobbered)" as required regression coverage. The
  guard is currently a comment + an ordering convention; a future refactor that
  moves the reconciliation block above the `degraded is not None` check (or
  re-runs it unconditionally) would silently downgrade a corruption alert to a
  count-divergence alert with NO failing test. The more-severe signal is lost.
- **Proposed fix:** Add `TestStartupReconciliation::test_corpus_corruption_not_
  clobbered`: monkeypatch `server.resources.open_chunks_table_with_fallback` to
  return `(table, DegradedState(reason="corpus_corruption", fallback_version=N-1,
  original_version=N))`, seed a marker that WOULD diverge, boot startup, and
  assert `resources.degraded.reason == "corpus_corruption"` (not
  `chunk_count_diverged`) plus the INFO "skipping chunk_count reconciliation"
  log fired.
- **Regression guard:** The test above — it must fail if the `degraded is not
  None` guard at `resources.py:447` is removed.

### F2 — count_rows()-raises-at-startup (FM-2) non-fatal path untested at boot

- **Severity:** HIGH
- **File:** server/resources.py:435-445
- **What:** The try/except wrapping `count_rows()` at startup (FM-2: failure is
  non-fatal, sentinel `-1`, skip reconciliation, server still starts) is only
  validated indirectly — `test_fm2_count_unavailable_sentinel` (line 153) tests
  the pure helper with `actual=-1`, and `test_count_unavailable_sentinel_
  surfaces_as_minus_one` (line 293) tests the gauge with a hand-set `-1`. No test
  drives `Resources.startup` with `chunks_table.count_rows` actually raising.
- **Why it matters:** The load-bearing claim is "a `count_rows()` exception at
  startup does not abort the server." That behavior lives entirely in the
  `try/except Exception` at `resources.py:435`. If a future edit narrows the
  except, mis-sets the sentinel, or lets the exception escape, the server would
  refuse `/readyz` on a transient Lance metadata read error — the opposite of the
  WARN-and-serve contract — and no test would catch it. This is a common path on
  a constrained workstation (transient I/O).
- **Proposed fix:** Add `test_count_rows_raises_is_nonfatal`: after `_seed_corpus`,
  monkeypatch the opened table's `count_rows` to raise (e.g. patch
  `open_chunks_table_with_fallback` to return a table whose `count_rows` raises),
  boot startup, assert it returns a warm `Resources` with
  `startup_chunk_count == -1`, `degraded is None`, and the FM-2 WARN logged.
- **Regression guard:** The test above — fails if the try/except at
  `resources.py:435` is removed or the `-1` sentinel assignment is dropped.

### F3 — config tolerance validator has zero test coverage

- **Severity:** MEDIUM
- **File:** server/config.py:653-665
- **What:** `validate_corpus_chunk_count_tolerance` rejects values outside
  `[0.0, 1.0]`, but no test constructs `Config(corpus_chunk_count_tolerance=...)`
  or sets `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE` out of range to assert it raises.
  A grep of `tests/` for `corpus_chunk_count_tolerance` /
  `CORPUS_CHUNK_COUNT_TOLERANCE` returns nothing.
- **Why it matters:** The synthesis §6.1 explicitly specified this validator
  "mirroring `validate_eq_ted_weight`." The sibling `eq_ted_weight` validator is
  the template, and validators of this class are exactly where a copy-paste typo
  (wrong bound, wrong field name in the decorator) ships silently. AC-3's "test
  surface" is the load-bearing axis for this milestone; an untested input guard
  is a foot-gun, though not on a hot path (mis-config is operator error, caught
  at boot).
- **Proposed fix:** Add a small parametrized test:
  `Config(corpus_chunk_count_tolerance=1.5)` and `=-0.1` each raise
  `ValidationError`; `=0.0`, `=0.05`, `=1.0` each construct successfully.
- **Regression guard:** The parametrized test above.

### F4 — getattr defense is asymmetric and masks a pre-existing fake break

- **Severity:** MEDIUM
- **File:** server/health.py:281
- **What:** `CORPUS_CHUNK_COUNT_MARKER.set(getattr(resources.corpus_info,
  "chunk_count", -1))` defends the `.chunk_count` attribute but accesses
  `resources.corpus_info` undefended — and the unchanged line directly above
  (`health.py:273`) already does `resources.corpus_info.version` with no guard.
  So the getattr only protects against a `corpus_info` that has `version` but
  lacks `chunk_count`. The implementation-summary (lines 84-85) admits this
  "fixed a latent break in an existing `test_server_metrics.py` fake that omits
  `chunk_count`" — confirmed at `tests/test_server_metrics.py:464-470`, where the
  fake is `corpus_info=SimpleNamespace(version=1)` with no `chunk_count` and no
  `startup_chunk_count`.
- **Why it matters:** A `getattr(..., -1)` fallback inside a scrape handler will
  silently emit `chunk_count_marker = -1` if a real `Resources` ever loses its
  `chunk_count` field, hiding a genuine wiring bug behind a sentinel that looks
  like the legitimate FM-2 count-unavailable signal — operators cannot
  distinguish "count_rows failed" from "marker field missing." The cleaner fix
  was to give the test fake the field. In production `refresh_metrics_from_
  singleton_state` is only ever called post-startup with a fully-constructed
  `Resources`, so this is a test-accommodation smell, not a prod bug — hence
  MEDIUM.
- **Proposed fix:** Update the `test_server_metrics.py:464-470` fake to include
  `chunk_count=...` on its `corpus_info` and a top-level `startup_chunk_count`,
  then drop the `getattr` wrappers in favor of direct attribute access
  (consistent with the undefended `version` read one line up). If the team wants
  defense-in-depth, defend `corpus_info` itself too — but symmetry beats a
  half-guard.
- **Regression guard:** Keep `test_count_unavailable_sentinel_surfaces_as_minus_
  one`; after the fake is fixed, the direct-access version must still pass.

### F5 — AC-3 "computed at most once at startup" is false when rerank is enabled

- **Severity:** MEDIUM
- **File:** server/resources.py:579
- **What:** With `config.enable_rerank=True`, `count_rows()` is called a SECOND
  time at startup in the reranker warm-up block (`resources.py:579`,
  `total_rows = chunks_table.count_rows()`), in addition to the new step-2b call
  (`resources.py:436`). The new code comment (`health.py:275`) and the field
  docstring (`resources.py:320` "captured ONCE at startup") assert a single
  startup call.
- **Why it matters:** AC-3 as worded in synthesis §5.3 is specifically about the
  PER-SCRAPE path ("a test asserts `count_rows()` is called AT MOST ONCE across
  startup + a `/metrics` scrape" with the table count_rows mocked), and
  `test_gauges_set_from_cache_not_recomputed_per_scrape` correctly pins the
  scrape path to zero calls. So the AC is technically satisfied. But the inline
  comments and docstring over-claim "ONCE at startup" — startup-total is two
  calls when rerank is on. This is a documentation/precision drift, not a
  correctness bug (the warmup call is independent, pre-existing E14_S05 code, and
  both calls are O(1) Lance metadata reads). Worth correcting so a future reader
  does not "optimize" by reusing `startup_chunk_count` in the warmup block and
  couple two unrelated concerns.
- **Proposed fix:** Soften the `resources.py:320` docstring and `health.py:275`
  comment to "captured once for the reconciliation/gauge path" rather than
  "ONCE at startup," or add a one-line note that the reranker warm-up
  (`resources.py:579`) independently calls `count_rows()` when rerank is enabled.
- **Regression guard:** None required (doc-precision); the existing per-scrape
  test already pins the load-bearing AC.

### F6 — DegradedState fallback_version=version is semantically misleading on /readyz

- **Severity:** LOW
- **File:** server/resources.py:475-478
- **What:** For a count divergence, `DegradedState` is built with
  `fallback_version=corpus_info.version` and `original_version=corpus_info.
  version` (both equal). `/readyz` then serializes
  `fallback_version == original_version == <pinned version>`
  (`tests/test_corpus_count_reconciliation.py:253-254` asserts both == 7). For
  the `corpus_corruption` reason these two fields carry "we fell back N→N-1"
  semantics; here no fallback occurred.
- **Why it matters:** An operator reading `/readyz` for a `chunk_count_diverged`
  body sees two version fields that look like a fallback record but are not.
  This is the D2 resolution as designed (synthesis §3 D2 chose this over a `0`
  sentinel, and the inline comment at `resources.py:471-474` documents it), so
  it is intentional — flagged LOW only because the serialized JSON reuses
  fallback-shaped fields for a non-fallback condition, which a dashboard could
  misread. The actual divergence magnitude lives in the two gauges, not
  `/readyz`, which is the right call.
- **Proposed fix:** None required (defer). Optionally document on the SECURITY/
  ops side that `chunk_count_diverged` populates `fallback_version ==
  original_version == pinned_version` by convention and the real signal is the
  gauge pair. Record under `deferred_findings`.
- **Regression guard:** N/A (LOW / deferred).

## What was done well

- The pure-helper extraction (`compute_chunk_count_divergence`,
  `resources.py:219-251`) is exactly right: the FM-2/3/4/6 edge cases are
  exhaustively unit-tested (10 cases) without booting the server, and the
  tolerance-boundary tests (`==` is strict-greater, `test_corpus_count_
  reconciliation.py:148-151`) pin the off-by-one precisely.
- The D3 divergence formula is correctly implemented: the `marker <= 0` guard
  (`resources.py:445`) genuinely prevents div-by-zero, and the `max(1, tolerance
  * marker)` floor is verified by `test_fm4_one_row_floor_on_micro_corpus` and
  `test_zero_tolerance_still_keeps_one_row_floor`.
- Cache byte-stability is preserved: zero MCP-tool / prompt / hash-file changes
  (`EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` untouched); the new
  gauges and `reason` string never enter a cache key or tool-result payload.
- Correct reuse of the existing `/readyz` degraded path — no handler routing
  change, exactly as both briefs converged on; `TestReadyzChunkCountDivergedBody`
  proves the new reason serializes cleanly.
- The `refresh_degraded_mode_metric` zero-out tuple was correctly extended with
  `chunk_count_diverged` (`health.py:670-675`) and a test
  (`TestDegradedModeEnumeration`) proves the gauge is zeroed on recovery — the
  one wiring step both briefs flagged was not missed.
- `count_rows()` is correctly off-loaded to `run_in_executor` (`resources.py:436`),
  matching the synchronous-I/O discipline of the step-2 LanceDB open — the event
  loop is not blocked.
- The metrics fixture was regenerated and the timestamp churn is benign: the
  `_created` lines are stripped by `test_daily_metrics_report.py::_normalize`
  (line 267), so the new gauge families are the only load-bearing fixture delta.
- The `_patch_model` helper correctly patches `_get_model`/`_get_tokenizer` in
  BOTH `query_encoder` and `resources` modules (the notebook-retrieval-m2 lesson),
  so the startup integration tests exercise real `Resources.startup`, not a stub.
- Local-first + no-fork + tier-sequencing all clean: no new dependency, no
  vendored code, m1 dependency (`8e58c42`) is shipped, no unbuilt-tier
  consumption.

## Recommended rectification order

1. **F1** (FM-7 startup test) — highest leverage; pins the design's TOP RISK and
   is the only finding tied to an explicitly-required-but-missing AC. ~15 LOC.
2. **F2** (FM-2 startup test) — same test file, same fixture pattern as F1;
   pin the non-fatal contract. ~15 LOC.
3. **F3** (config validator test) — independent, trivial parametrized test.
   ~10 LOC.
4. **F4** (getattr asymmetry) — fix the `test_server_metrics.py` fake, then
   tighten the gauge reads; small surface, but order after F1-F3 since it
   touches a second test file.
5. **F5** (AC-3 doc-precision) — comment/docstring softening only; no test.
6. **F6** (LOW / deferred) — no action required; record under deferred_findings.

## Rectification status

- **F1 (HIGH) — FIXED.** Added
  `TestStartupReconciliation::test_corpus_corruption_not_clobbered`: monkeypatches
  `open_chunks_table_with_fallback` to return a pre-set
  `DegradedState(reason="corpus_corruption")`, seeds a marker that WOULD diverge,
  boots `Resources.startup`, asserts `degraded.reason == "corpus_corruption"` (NOT
  clobbered) + the "skipping chunk_count reconciliation" INFO log. Fails if the
  `degraded is not None` guard at `resources.py` is removed.
- **F2 (HIGH) — FIXED.** Added
  `TestStartupReconciliation::test_count_rows_raises_is_nonfatal`: wraps the opened
  table so `count_rows()` raises at startup, asserts `Resources.startup` returns a
  warm instance with `startup_chunk_count == -1`, `degraded is None`, and the FM-2
  WARN. Fails if the try/except around `count_rows()` is removed.
- **F3 (MEDIUM) — FIXED.** Added `TestConfigToleranceValidator` (parametrized):
  out-of-range (`-0.1`, `1.5`, `2.0`) raise `ValidationError`; in-range
  (`0.0`, `0.05`, `0.5`, `1.0`) construct; default is `0.05`.
- **F4 (MEDIUM) — FIXED.** Dropped the asymmetric `getattr` sentinel in
  `refresh_metrics_from_singleton_state`; both gauge reads are now direct attribute
  access (consistent with the `corpus_info.version` read above), so a genuine
  missing-field wiring bug surfaces as an `AttributeError` rather than being masked
  as the FM-2 `-1` count-unavailable signal. Fixed the `test_server_metrics.py`
  fake (`TestF2SingleflightCounter`) to carry `chunk_count` + `startup_chunk_count`.
- **F5 (MEDIUM) — FIXED.** Softened the `startup_chunk_count` field docstring and
  the `health.py` gauge-setter comment from "captured ONCE at startup" to "captured
  once for the reconciliation/gauge path", with an explicit note that the reranker
  warm-up independently calls `count_rows()` when `enable_rerank` is on (so a future
  reader does not couple the two). The load-bearing per-scrape AC is unchanged and
  still pinned by `test_gauges_set_from_cache_not_recomputed_per_scrape`.
- **F6 (LOW) — DEFERRED.** The `fallback_version == original_version == pinned
  version` shape on the `chunk_count_diverged` `/readyz` body is the intentional D2
  design (the real divergence magnitude lives in the gauge pair, not `/readyz`).
  Recorded under deferred_findings; optional ops-doc note left for a future pass.

**Invalidation summary:** 6 findings (0 CRITICAL, 2 HIGH, 3 MEDIUM, 1 LOW). 5 FIXED
(F1–F5), 1 DEFERRED (F6, intentional design). 0 invalidated on re-verify (both HIGH
findings' cited regions still matched). Adversary invalidation rate: 0%.
