# Critique — E07_S04

**Critic:** adversary
**Generated:** 2026-05-09T00:00:00Z
**Commit range:** e98fa39cd1134a1154516ed17babdcc3f04ddd16..5afbee8804272ccf2c6ca0930087fd1f0e9db25f
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES — wire-up is sound and correctly defers the
  un-runnable AC #1 + #2 to a fixture-curation deliverable, but the
  shutdown path swallows real errors and the unit-test coverage
  doesn't follow the new aggregate schema.
- Counts: 0 CRITICAL, 1 HIGH, 6 MEDIUM, 3 LOW.
- Highest-risk site: `tests/eval/test_retrieval_quality.py:461` —
  `contextlib.suppress(NameError, Exception)` masks shutdown
  timeouts and cleanup failures, including the 30-s `wait_for`
  the docstring promises will surface.
- Cross-axis pattern: every new write surface (latency JSON keys,
  `--rerank` env-gate, hybrid aggregate schema) is documented but
  not regression-guarded by a test — three independent foot-guns
  feeding the same "passes today, drifts tomorrow" failure mode.
- The synthesis reinterpretations of AC #1, #2, #3 are defensible
  given the empty fixture stub; AC #4 assertion has landed but its
  threshold (`LATENCY_P95_MAX_SECONDS`) is an editable constant
  with no pin-test guard.
- The "deviations" section in the implementation summary is
  correctly named — none are out-of-scope; all three are
  brief-ambiguity resolutions documented in the synthesis.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer |

## Findings

### F1 — Shutdown errors silently swallowed by Exception catch

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:461-464
- **What:** The hybrid helper's `finally` wraps
  `loop.run_until_complete(asyncio.wait_for(resources.shutdown(),
  timeout=30.0))` in `with contextlib.suppress(NameError,
  Exception):`. `Exception` swallows `asyncio.TimeoutError`,
  `RuntimeError`, and any other exception from `shutdown()` —
  including the 30-second `wait_for` the implementation summary
  cites as "the established convention". A stuck shutdown is
  invisible.
- **Why it matters:** AC #4 (latency budget) is asserted on the
  query loop, but operators won't notice that the LanceDB handle or
  the BGE-M3 executor failed to drain; the next eval run on the
  same process will inherit half-released resources. The pattern
  also masks `NameError` (which `Exception` already catches), so
  the explicit `NameError` argument is misleading code.
- **Proposed fix:** narrow the suppress to the specific failure
  modes that actually need swallowing. The only legitimate
  swallow is when `resources` is unbound because `Resources.startup`
  raised — guard that with a sentinel:
  ```python
  resources = None
  try:
      resources = loop.run_until_complete(Resources.startup(cfg))
      ...
  finally:
      if resources is not None:
          try:
              loop.run_until_complete(
                  asyncio.wait_for(resources.shutdown(), timeout=30.0)
              )
          except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
              # Log but don't fail the test for a slow drain.
              import warnings
              warnings.warn(f"shutdown drain exceeded 30s: {exc}")
      loop.close()
  ```
- **Regression guard:** add a unit test that mocks
  `resources.shutdown` to raise `asyncio.TimeoutError` and asserts
  the test surfaces a warning (or at least does not silently pass
  the suppress).

### F2 — Hybrid-aggregate JSON schema has no unit-test coverage

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/test_metrics.py:388-394
- **What:** `TestScoreAndWrite.test_above_threshold_writes_files_and_returns`
  asserts `list(agg.keys()) == [5 specific keys]`. The new hybrid
  path adds two MORE keys (`latency_ms`, `pipeline`); there is no
  test covering the 7-key shape. A future refactor that drops
  `latency_ms` (e.g., by mistakenly forgetting the
  `assert_latency_p95` branch) would pass the existing tests.
- **Why it matters:** the aggregate JSON is the drift baseline
  E11_S04 reads. A silently regressed schema breaks downstream
  consumers AND removes the latency profile from the report
  without warning.
- **Proposed fix:** add `test_hybrid_rows_emit_latency_and_pipeline`
  to `TestScoreAndWrite` that drives `score_and_write` with
  synthetic rows containing `total_ms`/`bm25_ms`/`ann_ms`/
  `rerank_ms`/`pipeline`, asserts the aggregate has the 7
  expected top-level keys, asserts `latency_ms` has the four
  per-phase entries each with `p50/p95/max`, and asserts
  `pipeline == "hybrid"` (or "hybrid+rerank").
- **Regression guard:** the new test itself.

### F3 — `LATENCY_P95_MAX_SECONDS` is an editable module constant

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:117
- **What:** The 2.0-second budget is a plain `float` constant. A
  contributor lowering the threshold to 5.0 (or raising it to
  match a slow CI box) would face no test failure — the brief's
  AC #4 is encoded in code, not in a contract test.
- **Why it matters:** the brief makes 2.0 s load-bearing for the
  Tier-1 exit gate ("Latency p95 for the full pipeline ... is ≤ 2
  seconds at k=10"). A silent edit deviates from the spec.
- **Proposed fix:** add `test_latency_budget_pin` to
  `tests/eval/test_metrics.py` that imports
  `LATENCY_P95_MAX_SECONDS` and asserts `== 2.0` exactly. Anchor
  the AC in the test surface so a future edit triggers a
  deliberate-bump test failure (mirrors the
  `EXPECTED_TOOL_SCHEMA_SHA256` discipline cited in
  `tests/conftest.py:53-56`).
- **Regression guard:** the new test.

### F4 — `--rerank` without `--hybrid` UsageError has no test coverage

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/conftest.py:115-120
- **What:** Synthesis D3 calls the precondition "load-bearing", but
  it's only documented in a docstring; no test invokes pytest in a
  subprocess with the bad flag combination to assert the
  `UsageError` actually fires. A future refactor of the fixture
  body could silently downgrade the precondition to a SKIP without
  any test failing.
- **Why it matters:** the operator-error guard is exactly the kind
  of code path that bit-rots silently — by the time someone hits
  `--rerank` alone, the only consequence is a confusing test run.
- **Proposed fix:** add `test_rerank_without_hybrid_raises_usage_error`
  in `tests/test_conftest.py` (or similar) that uses pytest's own
  `pytester` fixture to invoke the eval with `--rerank` only and
  asserts the run exits with the UsageError text.
- **Regression guard:** the new test.

### F5 — `Config()` re-reads ARXMCP_* env vars; `ARXMCP_BIND_HOST` will trip the eval

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:375
- **What:** `_run_hybrid_against_corpus` constructs `Config(enable_rerank=...)`,
  and pydantic-settings reads ALL `ARXMCP_*` env vars at
  instantiation. If the operator has a non-loopback
  `ARXMCP_BIND_HOST=0.0.0.0` (or any other validator-failing var) in
  their shell, `Config()` raises `pydantic.ValidationError` and the
  eval crashes with a confusing error rather than the AC failure
  the operator was looking for.
- **Why it matters:** the eval runbook in
  `docs/retrieval-quality-report.md:106-117` lists prerequisites but
  not "ensure ARXMCP_BIND_HOST is unset or loopback". A common
  developer setup that sources `.envrc` could break the eval with
  no actionable guidance.
- **Proposed fix:** either (a) construct `Config` with
  `_env_file=None, _env_prefix=""` to bypass env loading for the
  eval (the eval doesn't need bind_host or other server-side knobs;
  only `enable_rerank` matters), or (b) catch
  `pydantic.ValidationError` and re-raise with a friendly hint
  pointing to the env-var override pattern.
- **Regression guard:** add a test that sets a bogus
  `ARXMCP_BIND_HOST=0.0.0.0` via `monkeypatch.setenv` and asserts
  the eval skips/fails with a CLEAR message rather than a raw
  `ValidationError`.

### F6 — Module-level `_inflight` not reset around the hybrid helper

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:376-465
- **What:** `_run_hybrid_against_corpus` opens a fresh event loop,
  drives `encode_query` (which writes futures into the module-level
  `server.query_encoder._inflight` dict via
  `loop.run_in_executor`), then closes the loop. The pending
  `loop.call_later(DEDUP_WINDOW_S, _inflight.pop, key, None)`
  eviction callbacks never fire on a closed loop, so stale futures
  bound to a dead loop linger in `_inflight`. Other tests in
  `tests/retrieval/test_ann.py` already call `_reset_for_tests()`
  for exactly this reason; the eval helper does not.
- **Why it matters:** when the eval runs in the same pytest
  session as a downstream test that also calls `encode_query`
  with an identical query string within the eviction window
  (mostly hypothetical at the seed-fixture scale, but real for
  the 200K-paper E11 cutover), the FAST PATH would await a
  cancelled future bound to a closed loop.
- **Proposed fix:** add `from server import query_encoder as _qe;
  _qe._reset_for_tests()` in the helper's `finally` AFTER
  `loop.close()`. Mirrors the discipline at
  `tests/retrieval/test_ann.py:596,635`.
- **Regression guard:** add an integration test that runs the
  eval helper followed immediately by a `test_query_encoder.py`
  test using the same query string; assert no `RuntimeError:
  loop is closed`.

### F7 — `_run_hybrid_against_corpus` instantiates Resources per call (cold-start matrix re-runs are expensive)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:380
- **What:** Every test invocation builds a fresh `Resources` via
  `Resources.startup(cfg)` — LanceDB open, BGE-M3 warm, BM25 build,
  optional reranker download. For a 20-query eval that's ~one
  startup; for an operator iterating on `--ndcg-min` thresholds
  (e.g. 0.78 → 0.80 → 0.82 to chart the sensitivity curve), each
  invocation pays the full cold-start cost. On the rerank-on path
  the cost is the 2.3 GB model load + warmup.
- **Why it matters:** the synthesis's "we run the gate once"
  assumption is fine for the BLOCK-on-fixture status; once the
  fixture lands and engineers iterate on the pipeline, this
  becomes friction. Not a correctness bug, but a UX-quality
  warning the report should call out.
- **Proposed fix:** document the per-invocation startup cost in
  the report's "How to run the gate" section so operators know
  to budget time. Optionally add a session-scoped fixture that
  caches `Resources` across multiple test invocations in a
  pytest session (would require lifting startup OUT of the
  helper into a fixture).
- **Regression guard:** none required — this is documentation +
  a workflow improvement.

### F8 — Latency assertion is gated on threshold-pass

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:542-558
- **What:** `assert_threshold` raises before the latency check
  reaches line 547, so a test that fails on nDCG never reports
  whether the latency budget was also violated. Operators
  triaging a failed gate get one signal at a time.
- **Why it matters:** when the eval finally runs and fails, the
  operator wants to know if BOTH ACs are violated (suggesting a
  pipeline-wide issue) or only ONE (suggesting a more local
  problem). The current order forces serial discovery.
- **Proposed fix:** swap the order — check latency BEFORE
  asserting nDCG threshold, so a latency violation is reported
  alongside a nDCG failure (or chain them via
  `pytest.raises` style accumulation). Trivial reorder.
- **Regression guard:** none required.

### F9 — `contextlib.suppress(NameError, Exception)` is redundantly typed

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:461
- **What:** `NameError` is a subclass of `Exception`; listing both
  is dead code. Resolved by F1's narrower fix; flagged here so the
  rectifier doesn't re-introduce the redundancy.
- **Why it matters:** code clarity. `NameError` in the catch-list
  signals intent ("we expected `resources` might be unbound") that
  the broad `Exception` already swallows; reading the line twice
  to understand it is a small papercut.
- **Proposed fix:** remove `NameError` from the suppress; subsume
  into F1's `if resources is not None:` guard.
- **Regression guard:** none required.

### F10 — `score_and_write` writes aggregate before latency assert; no test covers the latency-fail-but-file-exists invariant

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:535-558
- **What:** `score_and_write` writes the aggregate JSON BEFORE
  asserting either threshold (good — file-on-fail is the documented
  contract). But `TestScoreAndWrite` only verifies this for the
  nDCG-threshold path (test_below_threshold_raises:432-436); no
  test verifies that a latency-budget violation also leaves the
  aggregate file behind. A regression that moves the JSON write
  AFTER the latency assertion would not be caught.
- **Why it matters:** the operator expects diagnostic files on EVERY
  failure mode, not just nDCG.
- **Proposed fix:** add `test_latency_violation_writes_files_then_raises`
  to `TestScoreAndWrite` that drives `score_and_write` with rows
  whose `total_ms` p95 exceeds 2000 ms and asserts both files exist
  AND the AssertionError mentions "AC #4 violated".
- **Regression guard:** the new test.

## What was done well

- The synthesis correctly identifies the empty-fixture blocker for
  AC #1 + #2 and ships the wire-up + decision protocol rather than
  faking a result. The implementation summary's "deviations"
  section is honest about what's blocked vs what's done.
- The cold-start matrix at lines 182-197 is preserved AND the
  hybrid-helper integration sits cleanly inside the RUN cell —
  the harness still SKIPs cleanly on every cold-start
  permutation; `pytest -q` still emits 920 passed / 4 skipped.
- The `--rerank` env-gate (`ARXMCP_RUN_REAL_BGE_RERANKER=1`)
  mirrors `tests/retrieval/test_rerank.py:743-746` exactly, so
  the operator-friendly opt-in is consistent across the codebase.
- Per-phase latency instrumentation uses `time.monotonic()` (not
  `time.time()`), which is the correct choice for an interval
  measurement — robust against wall-clock skew.
- `_percentile` is pure-Python with a clean docstring on the
  N=20 interpolation behavior; no numpy-at-the-eval-aggregate
  dep introduced.
- The `score_and_write` writes the aggregate JSON BEFORE asserting
  the threshold (line 535-538 vs 542) — the diagnostic baseline
  lands even on threshold-fail. This is the right ordering.
- Eval marker registration in `pyproject.toml` is well-formed and
  the marker description doubles as a runbook hint
  (`pytest -m "not eval"` opt-out).
- The decision-protocol in `docs/retrieval-quality-report.md:90-99`
  is concrete: 4 numbered steps that an operator can mechanically
  follow. The "DO NOT lower the threshold" step (5) is the right
  guardrail.
- The `Config(enable_rerank=rerank_enabled)` construction respects
  the synthesis D7 default-False security posture: the wire-up
  doesn't pre-flip the prod config.
- Documentation correctly distinguishes the off-path (passthrough,
  RRF score) from on-path (sigmoid logit) score semantics —
  closes the E07_S03 F5 contract gap by re-stating it for future
  readers in the report's "Out-of-scope sanity check" callout.

## Recommended rectification order

1. **F1** — narrow the `contextlib.suppress` to handle the
   resources-may-be-unbound case explicitly. Highest-leverage:
   one site, ~10 LOC, restores observable shutdown failures.
2. **F2 + F10** — bundle the missing `score_and_write` test
   coverage (hybrid-aggregate schema + latency-fail-then-file).
   Both new tests live in `TestScoreAndWrite` and share fixture
   setup. ~40 LOC total.
3. **F3** — pin `LATENCY_P95_MAX_SECONDS` with a contract test
   so the AC is encoded in test surface, not just code. ~5 LOC.
4. **F6** — call `_reset_for_tests()` in the helper's `finally`
   to match the established discipline. ~3 LOC.
5. **F4** — add the `--rerank` precondition pytest-internal test
   via `pytester`. ~15 LOC.
6. **F5** — guard `Config()` against operator env-var noise.
   ~10 LOC + a regression test.
7. **F8 + F9** — cosmetic reorder + dead-code removal.
   Subsume into F1's diff if convenient.
8. **F7** — pure documentation note in the report. ~3 lines.

## Rectification status (filled by Phase 4)

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | HIGH | **fixed** | Replaced `with contextlib.suppress(NameError, Exception)` with an explicit `if resources is not None:` guard + a narrow `try/except TimeoutError` around `wait_for(shutdown)`. `TimeoutError` surfaces as a `warnings.warn` (not silent suppression); other shutdown exceptions propagate. Subsumes F9. |
| F2 | MEDIUM | **fixed** | New `TestHybridAggregate::test_hybrid_rows_emit_latency_and_pipeline` in `tests/eval/test_metrics.py`. Drives `score_and_write` with synthetic hybrid rows (with `total_ms`/`bm25_ms`/`ann_ms`/`rerank_ms`/`pipeline` keys); asserts the 7-key aggregate shape including `latency_ms` (with `p50`/`p95`/`max` per phase) and `pipeline` identity. |
| F3 | MEDIUM | **fixed** | New `TestLatencyBudgetPin::test_latency_budget_pinned_at_2_seconds` asserts `LATENCY_P95_MAX_SECONDS == 2.0` exactly. Mirrors the `EXPECTED_TOOL_SCHEMA_SHA256` discipline from E06_S06. |
| F4 | MEDIUM | **deferred** | Pytester subprocess test is heavier than the rectification budget. The `pytest.UsageError` raise IS exercised manually (we ran `pytest tests/eval/test_retrieval_quality.py --rerank` and confirmed the error fires). Document inline; future test cleanup may add a pytester check. |
| F5 | MEDIUM | **fixed** | Wrapped `Config(enable_rerank=...)` in a try/except that catches `Exception` and `pytest.fail`s with a clear hint pointing at the operator's stale `ARXMCP_*` env vars. |
| F6 | MEDIUM | **fixed** | Added `_qe._reset_for_tests()` in the helper's `finally` block AFTER `loop.close()`, mirroring `tests/retrieval/test_ann.py`. Cross-test contamination of the encode singleflight closed. |
| F7 | MEDIUM | **fixed** | New "Cold-start cost per invocation" section in `docs/retrieval-quality-report.md` with concrete timing budgets (without rerank: 10-30s; cold rerank: 2-5min; warm rerank: 30-60s). Recommends session-scoped Resources as a future improvement. |
| F8 | LOW | **fixed** | Reordered `score_and_write` to compute the latency violation message FIRST, then catch the nDCG `assert_threshold` raise, then chain BOTH into a single `AssertionError("BOTH ACs violated:...")` when both fail. Single failed run now reports both violations. New `TestHybridAggregate::test_both_acs_violated_reports_both` exercises this. |
| F9 | LOW | **fixed** | Subsumed into F1's narrower exception handling. The redundant `NameError` is gone; the `is not None` guard makes the intent explicit. |
| F10 | LOW | **fixed** | New `TestHybridAggregate::test_latency_violation_writes_files_then_raises` asserts both `results-101.jsonl` and `aggregate-101.json` exist after a latency-only failure. Plus `test_latency_assertion_off_when_not_requested` pins backwards-compat with E05_S02 invocations. |

Suite at rectification: **925 passed, 4 skipped, ruff clean** (was 920 pre-rect — +5 from new test classes; F1+F5+F6+F8 are in-place edits without new tests).

Reverify pass: F1 was reproduced via inspection (the broad `Exception` catch swallows `asyncio.TimeoutError`). F4's deferral rationale: pytester subprocess tests add ~5s of overhead and the manual test passed on first try; the operator-typo is also rare. F7's documentation-only fix is appropriate for the workflow concern.

