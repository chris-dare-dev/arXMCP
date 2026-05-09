# Critique — E05_S02

**Critic:** adversary
**Generated:** 2026-05-08T00:00:00Z
**Commit range:** 1bca8a9..0843095
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: the metric math is sound and the cold-start
  matrix is honest, but two latent foot-guns plus several
  source-of-truth / docstring drift items will calcify if not fixed
  now.
- Counts: 0 CRITICAL, 2 HIGH, 5 MEDIUM, 4 LOW.
- Highest-risk file: `tests/eval/test_retrieval_quality.py:185` —
  per-query `asyncio.run(encode_query(...))` interacts unsafely with
  the `query_encoder._inflight` singleflight cache (stale `Future`
  bound to a dead loop survives across queries).
- Cross-axis pattern: AC2 ("`--ndcg-min=0.50` fails when nDCG@5 below
  0.50") is verified ONLY at the helper boundary; the integration of
  `assert_threshold` into `test_retrieval_quality` is unverified, and
  there is no smoke test that the `--ndcg-min` flag is actually wired
  through pytest_addoption.
- `ndcg_at_k` is not robust to duplicate `chunk_id`s in
  `retrieved_chunk_ids` and can return values > 1.0 — a latent
  foot-gun in the standalone metric API even though the production
  call-site dedupes upstream.
- The `EMBEDDING_COLUMNS = ("embedding_stmt", "embedding_proof")`
  literal at `tests/eval/test_retrieval_quality.py:101` is a
  source-of-truth violation per D14 (the brief's "imports… not
  literalized" intent).
- Misleading inline doc at `test_retrieval_quality.py:239` claims
  "JSONL: append-mode (mirrors store-stats / bm25-stats discipline)"
  but the code opens with `"w"` (truncate). The synthesis D8 endorses
  truncate-write — the comment is wrong, not the code.
- `_atomic_write_text` is now duplicated in **5** modules; the brief
  for E04_S04 already noted the housekeeping deferral.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `ndcg_at_k` returns > 1.0 on duplicate retrieved ids

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/eval/metrics.py:118-138
- **What:** The DCG loop iterates `retrieved_chunk_ids[:k]` without
  deduping. A caller passing `retrieved=['a','a','b']` with
  `ground={'a':3,'b':1}` and `k=3` produces
  `DCG = 3/log2(2) + 3/log2(3) + 1/log2(4) ≈ 5.39` against
  `IDCG = 3/log2(2) + 1/log2(3) + 0 ≈ 3.63`, yielding `nDCG ≈ 1.485`.
  The function's docstring promises a value "in [0.0, 1.0]" (line 99).
- **Why it matters:** Standalone metric contract violated. Today
  `test_retrieval_quality.py:189-208` dedupes via
  `per_chunk_min_distance` so the production call cannot trip this,
  but E11_S04 (drift watchdog) is the next non-test consumer and the
  module docstring already names it as such (line 33). A drift
  watchdog that re-runs against legacy results files where a future
  change introduces duplicates would silently produce inflated nDCG
  and miss a real regression.
- **Proposed fix:** Either (a) dedupe `retrieved_chunk_ids` while
  preserving rank order before the DCG loop, or (b) raise
  `ValueError` on duplicates with a clear message. Option (b) is
  safer (signals the caller's bug instead of silently rewriting
  intent). Pick (b): add `if len(set(retrieved_chunk_ids[:k])) !=
  len(retrieved_chunk_ids[:k]): raise ValueError(...)` near the top
  of `ndcg_at_k`, mirroring `_validate_grades` discipline.
- **Regression guard:** Add `test_metrics.py::TestNdcgAtK::
  test_duplicate_retrieved_raises` asserting the new ValueError, and
  document the contract in the module docstring's "Edge cases"
  section.

### F2 — Stale singleflight `Future` survives `asyncio.run` cleanup

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:185
- **What:** `asyncio.run(encode_query(query_text))` opens a fresh
  event loop per query. `encode_query` (server/query_encoder.py:345)
  registers the resulting `loop.run_in_executor` Future into the
  module-level `_inflight` dict and schedules eviction via
  `loop.call_later(DEDUP_WINDOW_S, ...)` (line 357). When
  `asyncio.run` closes the loop ~0.0s after the await returns, the
  100ms-delayed eviction never fires. The Future stays in `_inflight`
  bound to a dead loop. If a subsequent query in the same eval run
  has identical canonical text (`unicodedata.normalize("NFC",
  query.strip())`), the FAST PATH (line 326) finds the stale Future
  and `await asyncio.shield(inflight_fut)` raises
  `RuntimeError: ... is bound to a different event loop`.
- **Why it matters:** The validator (E05_S01) enforces unique
  `query_id`, NOT unique `query_text`. A curator legitimately can
  add two queries with the same text exploring different facets
  (e.g. variant `relevant_chunks` lists). Today the fixture is empty
  so the bug is unreachable, but as soon as the corpus + 20 queries
  land, a single duplicate text breaks the entire eval pass and the
  drift baseline cannot be written.
- **Proposed fix:** Either (a) use a single event loop for the entire
  test via `loop = asyncio.new_event_loop(); try: ... loop.run_until_
  complete(encode_query(q))` for every query, then close once at the
  end, or (b) add `query_encoder._reset_for_tests()` (already exists,
  line 374) call at the top of the test to clear the dict, plus
  defensive de-dup of `query_text` per pass. Option (a) is closer to
  the intended async semantics and avoids reaching into the
  singleflight internals from the test.
- **Regression guard:** Add a unit test in `tests/test_query_encoder
  .py` that calls `asyncio.run(encode_query("x"))` twice in a row
  with the SAME text and asserts no `RuntimeError`. (Option a in the
  fix means this test still passes by avoiding the multi-loop case
  entirely.)

### F3 — `EMBEDDING_COLUMNS` literalizes column names — SoT violation

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:101
- **What:** `EMBEDDING_COLUMNS = ("embedding_stmt", "embedding_proof")`
  duplicates string literals that are also defined in
  `ingest/schema.py` (lines 83, 88), `ingest/store.py` (lines 412-413,
  339, 342). D14 of the synthesis says: *"never literalize ``1024``
  or ``\"chunks\"`` in the test or metrics code"* — the same
  reasoning applies to column names. The implementation summary's
  D14 row claims "no `1024` / `\"chunks\"` literals appear" but is
  silent on `embedding_stmt` / `embedding_proof`.
- **Why it matters:** A future schema rename (e.g. `embedding_stmt` →
  `embedding_statement`) bumps three production files plus this test
  in sync. Forgetting any one breaks ingestion or eval. The single-
  source-of-truth scan test from D14 only catches `1024` / `chunks`
  today.
- **Proposed fix:** Export the column-name tuple from `ingest/schema
  .py` (e.g. `EMBEDDING_COLUMN_NAMES = ("embedding_stmt",
  "embedding_proof")`) and import it in both
  `tests/eval/test_retrieval_quality.py` and `ingest/store.py`. Two-
  line change.
- **Regression guard:** Extend the existing single-source-of-truth
  scan test to catch `"embedding_stmt"` / `"embedding_proof"`
  literals outside `ingest/schema.py`.

### F4 — AC2 integration into the actual test is unverified

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:262
- **What:** `assert_threshold(ndcg5_mean=ndcg5_mean, ndcg_min=ndcg_min)`
  is the only call site that ties the helper into the AC2 path. The
  unit tests in `test_metrics.py::TestThresholdCheck` exercise the
  helper itself but no test confirms the eval test calls the helper
  with the right arguments in the right order. A future refactor
  that drops or moves this call would not be detected by any
  regression test.
- **Why it matters:** AC2 explicitly says "threshold enforcement
  verified in test." Today the verification lives in a sibling unit
  test, not in the test that the AC names. The data-blocked AC1
  branch makes this gap defensible — but it should be explicit.
- **Proposed fix:** Either (a) factor the
  threshold-and-write-results scoring step into a small helper
  function in `test_retrieval_quality.py` (e.g.
  `_score_and_write(per_query_rows, ndcg_min, output_dir)`) and
  unit-test it directly with synthetic per-query rows that produce
  `ndcg5_mean = 0.3`, asserting `ThresholdNotMetError`; or (b) add
  an integration-style test that monkeypatches `open_chunks_table`
  and `encode_query` to return canned data, drives the full
  `test_retrieval_quality` body, and asserts the threshold-fail
  path. Option (a) is lower-blast-radius.
- **Regression guard:** the new helper test would itself be the
  guard.

### F5 — Misleading "append-mode" comment vs `"w"` open

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:239-241
- **What:** Line 239 comment: `"# JSONL: append-mode (mirrors
  store-stats / bm25-stats discipline)"`. Line 241 code:
  `with results_path.open("w", encoding="utf-8") as fh:`. The code
  truncates (correct per synthesis D8 — "JSONL is one row per query
  (write-once, no overwrite); simple `with open('w')` is fine") but
  the comment claims append, citing the wrong precedent.
- **Why it matters:** A future contributor reading the comment may
  "fix" the code to match by switching to `"a"`, which would cause
  re-runs to accumulate stale rows from prior corpus versions
  (filename includes `corpus_version` so the same file is
  overwritten on re-run with same version). That breaks E11_S04's
  drift baseline contract — one row per query, not history of all
  past runs.
- **Proposed fix:** Update the comment to read: `"# JSONL: write-once
  per corpus_version (truncate-write); filename embeds the version
  so re-runs overwrite cleanly. NOT append-mode — the store-stats /
  bm25-stats append discipline is for monotonic ops logs, not for
  per-corpus-version baselines."`
- **Regression guard:** none required — comment-only fix.

### F6 — `assert_threshold` accepts NaN / inf without rejection

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/metrics.py:209-225
- **What:** `isinstance(ndcg5_mean, (int, float))` accepts `float('nan')`
  and `float('inf')`. With `ndcg5_mean = float('nan')` the comparison
  `ndcg5_mean < ndcg_min` returns `False` (any comparison with NaN
  is False), so the threshold check silently PASSES. With
  `ndcg5_mean = float('inf')` it also passes (no upper bound). Either
  state would be a real corpus regression masquerading as success.
- **Why it matters:** `_mean(ndcg_scores)` in
  `test_retrieval_quality.py:231` could return NaN if any
  `ndcg_at_k` call produced NaN (today blocked by the iDCG=0 → 0.0
  guard, but a future metric-math change could reintroduce NaN). A
  vacuous-pass on NaN defeats the entire AC2 contract.
- **Proposed fix:** Add `if not math.isfinite(ndcg5_mean): raise
  ValueError(...)` near the top of `assert_threshold`. Same for
  `ndcg_min` (defensive — operator could pass `--ndcg-min=inf`).
- **Regression guard:** Add `test_metrics.py::TestThresholdCheck::
  test_nan_score_rejected` and `test_inf_score_rejected`.

### F7 — `query_id` / `relevant_chunks` access via `[]` will KeyError instead of skip on partial fixture

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:178-183
- **What:** `query["query_id"]`, `query["query_text"]`,
  `query["relevant_chunks"]`, `entry["chunk_id"]`,
  `entry["relevance"]` all use bracket access. If a developer adds
  one query manually to the fixture without running the validator,
  any missing key raises `KeyError` mid-loop AFTER some queries have
  already been processed. The partial state (some rows scored, some
  not) is never written; the test fails with a naked `KeyError`
  traceback that doesn't name the validator as the fix.
- **Why it matters:** D11 says "the validator already ran in `make
  test`" — but `make test` doesn't enforce that the fixture validator
  is invariant under fixture edits between runs. The user-handoff
  steps in the implementation summary instruct the user to "curate
  the 20-query fixture per docs/eval-curation.md" — that path
  doesn't include a "must re-run validator" gate.
- **Proposed fix:** Wrap the per-query access in a try/except
  KeyError that raises `pytest.fail` with a message naming
  `python -m tools.validate_eval_fixtures` as the fix. Two lines.
  Alternative: call `validate()` once at the top of the RUN cell —
  but D11 explicitly forbids that.
- **Regression guard:** Add a smoke test that mutates a temp
  `queries.json`, drops a required key, and asserts the eval test
  fails with the validator-pointer message (NOT a raw KeyError).

### F8 — `--ndcg-min` flag wiring is end-to-end unverified

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/conftest.py:21-49
- **What:** No test confirms that `pytest --ndcg-min=0.55` actually
  produces `ndcg_min == 0.55` inside `test_retrieval_quality`. The
  conftest fixture has a default of `0.70`, so a typo in
  `pytest_addoption` (e.g. `dest="ndcg_minimum"`) would silently
  swallow the CLI value and the fixture would always return the
  default. The user never sees the misconfiguration.
- **Why it matters:** AC1/AC2 both mention `pytest --ndcg-min=...`.
  If the wiring breaks, both ACs silently degrade to "default-only."
- **Proposed fix:** Add a sub-test using `pytester` that invokes
  pytest with `--ndcg-min=0.55` and asserts a fixture-consuming test
  observes `0.55`. Five lines using `pytest.fixture(name="testdir")`.
- **Regression guard:** the new pytester test.

### F9 — `_atomic_write_text` is now the 5th copy

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:270-288
- **What:** Identical (modulo docstring) atomic-write helpers exist in
  `ingest/preamble.py:262`, `ingest/embedder.py:516`,
  `ingest/store.py:518` (atomic_write_json), `ingest/bm25_indexer
  .py:203`, and now `tests/eval/test_retrieval_quality.py:270`.
  Five copies of ~20 LOC each. The E04_S04 implementation summary
  explicitly noted this and deferred extraction.
- **Why it matters:** Each copy can drift independently (e.g. one
  could grow an `fsync` call, others miss it; one could acquire
  retry semantics). At 5 copies, the next bug fix has to find them
  all.
- **Proposed fix:** Extract to a `common/atomic_io.py` (or under
  `ingest/_atomic_io.py` since `ingest` is the closest shared
  ancestor today). Import from all 5 sites. Per-site change is
  3 lines.
- **Regression guard:** Add a single-source-of-truth test that
  scans for `os.replace(tmp, out_path)` patterns outside the new
  module.

### F10 — Module docstring claims "filename embeds version" without fsync

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:30-38
- **What:** Docstring says aggregate JSON is the "drift-detection
  baseline" written via "atomic write via PID + UUID-suffix tmp +
  `os.replace`." `os.replace` is atomic on POSIX for the rename
  step but does NOT call `fsync` on the directory entry. A power
  failure between `os.replace` and the next directory sync can
  resurrect an empty file from the prior write or lose the new one
  entirely. For a drift baseline this is a small but real risk.
- **Why it matters:** Same severity reasoning as the existing
  `_atomic_write_text` precedents — the project has deliberately
  chosen not to fsync. Calling it out explicitly in the docstring
  prevents a future "why isn't this fsync'd?" follow-up.
- **Proposed fix:** Add a one-line note: "No `fsync(dir)` —
  consistent with the project-wide atomic-write discipline; a power
  failure during a re-run may roll back to the prior baseline. The
  drift watchdog (E11_S04) re-runs on schedule, so the next pass
  rebuilds the baseline."
- **Regression guard:** none required — docstring-only fix.

### F11 — `ndcg5` / `recall10` field names hard-code `k=5` / `k=10` in the JSONL row schema

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/eval/test_retrieval_quality.py:222-228
- **What:** Per-query row keys `ndcg5` and `recall10` embed the
  `NDCG_K` and `FINAL_TOP_K` constant values into the schema. If
  E07 or a future tier raises k (e.g. nDCG@10), the JSONL schema
  has to migrate. The brief explicitly fixes nDCG@5 / Recall@10 for
  Tier-0; the field names are correct today.
- **Why it matters:** E11_S04's drift watchdog will key on these
  field names. A future schema migration becomes a coordinated
  multi-milestone change. Not blocking now.
- **Proposed fix:** Document the field-name contract in the module
  docstring's "Output files" section: "JSONL row keys `ndcg5` and
  `recall10` embed the Tier-0 cutoffs. Renaming requires a
  coordinated update of E11_S04's drift watchdog."
- **Regression guard:** none required — docstring-only.

## What was done well

- Plain (J-K) nDCG implemented correctly with explicit `dcg / idcg`
  guard returning 0.0 on iDCG=0; matches the brief's formula
  verbatim and the synthesis D5 / D6 decisions.
- The Burges-divergence test (`test_plain_form_diverges_from_burges_
  form`, test_metrics.py:92-124) shows hand-derived numbers; the
  asserted `0.7967` (plain) vs `0.7099` (Burges) values check out
  on re-derivation. This is a load-bearing regression guard.
- `HIGHLY_RELEVANT_GRADE = 3` as a named constant — a future bump to
  the TREC 0–4 scale becomes a one-line change.
- `bool` rejected explicitly in `_validate_grades` — closes the
  classic `isinstance(True, int) is True` foot-gun.
- Aggregate JSON written via the canonical
  PID-UUID-tmp-`os.replace` pattern with `sort_keys=True`; output
  bytes are deterministic across hosts (BP1 discipline preserved).
- Per-query JSONL row keys are sorted alphabetically via
  `sort_keys=True` on every `json.dumps`, AND the
  `retrieved_chunk_ids` list within each row is intentionally
  unsorted (rank-ordered) — the discipline is correct on both axes.
- Cold-start matrix (D1) is the single largest correctness call here
  — handling all four cells with explicit `pytest.skip` messages
  that name the missing prerequisite is the right pattern and keeps
  `make test` green on a fresh checkout.
- Deferred imports inside the test body for `server.corpus` and
  `server.query_encoder` (lines 122-124) wrapped in try/except
  ImportError correctly handle a fully-cold dev box without
  obscuring real bugs (a typo in module name would still fall
  through to `pytest.skip` with the import-error in the message).
- The `ThresholdNotMetError` subclass of `AssertionError` is the
  right pattern for pytest-friendly + greppable failure surfaces.
- `_main_only` / `_reset_for_tests` / private helpers all carry
  underscore prefixes; the `__all__` declarations in both
  `metrics.py` and `test_retrieval_quality.py` avoid stale-export
  drift.

## Recommended rectification order

1. **F2** — fix the singleflight stale-Future bug first; it sits on
   the same control flow as F4 / F5 / F7 and a fix here may simplify
   their fixes (e.g. switching to a single event loop changes how
   the integration test in F4 must be structured).
2. **F1** — `ndcg_at_k` duplicate-input contract; pure metric-side
   change, cannot interact with downstream fixes.
3. **F6** — NaN/inf rejection in `assert_threshold`; tiny diff,
   tightens the AC2 contract.
4. **F4** — AC2 integration test (after F1+F6 land so the test
   reflects the tightened contract).
5. **F3** — column-name SoT export; touches `ingest/schema.py` and
   the test, schedule before F7 so the import boundary is settled.
6. **F7** — fixture-access KeyError → pytest.fail with validator
   pointer.
7. **F5** — comment fix (one line; can land anywhere).
8. **F8** — `--ndcg-min` flag wiring smoke test (independent).
9. **F9** — `_atomic_write_text` extraction (housekeeping; can also
   defer if Phase 4 is tight on budget).
10. **F10, F11** — docstring-only; lowest leverage; may defer.

## Rectification status

**Phase 4 commit:** see `state.json` `rectification_commit` field.

| Finding | Severity | Status | Where fixed |
|---|---|---|---|
| F1 — `ndcg_at_k` returns > 1.0 on duplicate retrieved ids | HIGH | **fixed** | `tests/eval/metrics.py:104-115`: dedup check at the top of `ndcg_at_k`; raises `ValueError` if `len(set(top_k)) != len(top_k)`. Locked by `TestNdcgAtK::test_duplicate_retrieved_raises` and `test_duplicate_retrieved_outside_k_does_not_raise` (the dup-check is correctly scoped to the top-k slice, so a dup at rank > k doesn't trip the guard). |
| F2 — Stale singleflight `Future` survives `asyncio.run` cleanup | HIGH | **fixed** | `tests/eval/test_retrieval_quality.py::_run_queries_against_corpus`: replaced per-query `asyncio.run()` with a single `asyncio.new_event_loop()` + `loop.run_until_complete()` per query inside one `try/finally`. The 100ms eviction delayed by `loop.call_later` now fires normally because the loop stays alive for the duration of the test. No more dead-loop Futures in `_inflight`. |
| F3 — `EMBEDDING_COLUMNS` literal SoT violation | MEDIUM | **fixed** | `ingest/schema.py`: added `EMBEDDING_COLUMN_NAMES = ("embedding_stmt", "embedding_proof")` constant. `tests/eval/test_retrieval_quality.py` now imports it. Locked by `TestColumnNamesSourceOfTruth::test_test_module_uses_imported_constant` (asserts `EMBEDDING_COLUMNS is EMBEDDING_COLUMN_NAMES` AND that both names are in the schema's actual field list). |
| F4 — AC2 integration into actual test is unverified | MEDIUM | **fixed** | Factored the threshold-and-write step out of the test body into `score_and_write(per_query_rows, corpus_version, ndcg_min, output_dir)`. New `TestScoreAndWrite` class drives this helper with synthetic per-query rows and locks: (a) above-threshold writes both files with the correct schema; (b) below-threshold raises `ThresholdNotMetError` AND still writes the diagnostic files; (c) at-threshold passes (with FP-precision note in the docstring). |
| F5 — Misleading "append-mode" comment vs `"w"` open | MEDIUM | **fixed** | `tests/eval/test_retrieval_quality.py::score_and_write`: the comment now reads "JSONL: write-once per corpus_version (truncate-write); the filename embeds the version so re-runs with the same version overwrite cleanly. NOT append-mode — the store-stats / bm25-stats append discipline is for monotonic ops logs, not per-corpus-version baselines." |
| F6 — `assert_threshold` accepts NaN / inf without rejection | MEDIUM | **fixed** | `tests/eval/metrics.py::assert_threshold`: added `math.isfinite()` checks for both `ndcg5_mean` and `ndcg_min`. Locked by `test_nan_score_rejected`, `test_inf_score_rejected`, `test_nan_threshold_rejected`. |
| F7 — KeyError on partial fixture | MEDIUM | **fixed** | `tests/eval/test_retrieval_quality.py::_run_queries_against_corpus`: per-query field access is wrapped in `try/except (KeyError, TypeError)` that calls `pytest.fail` with a message naming `python tools/validate_eval_fixtures.py` as the diagnostic. |
| F8 — `--ndcg-min` flag wiring is end-to-end unverified | LOW | **deferred** | The wiring is a 3-line `pytest_addoption` + a 2-line fixture; `pytester` smoke tests add complexity not justified at Tier-0. The existing fixture (`ndcg_min`) IS exercised by `test_retrieval_quality` whenever the RUN cell fires. Reconsider in E05_S03 (TIER-GATES.md) when the flag is invoked from CI. |
| F9 — `_atomic_write_text` is now the 5th copy | LOW | **deferred (LOW-threshold)** | E04_S04 implementation summary already deferred this as housekeeping. No new bugs introduced; the 5th copy is identical to the others. Extraction to `ingest/_atomic_io.py` is a separate, no-behavior-change commit. |
| F10 — fsync docstring note | LOW | **deferred** | Docstring polish; the project-wide atomic-write discipline (no `fsync(dir)`) is consistent across all 5 sites. |
| F11 — `ndcg5` / `recall10` field-name docstring | LOW | **deferred** | Tier-0 cutoffs are fixed at 5 and 10; future-tier renames would be a coordinated change anyway. Documenting in E11_S04's drift watchdog spec is the right place. |

**New regression tests added in this rectification batch:**
- `TestNdcgAtK::test_duplicate_retrieved_raises` (F1).
- `TestNdcgAtK::test_duplicate_retrieved_outside_k_does_not_raise` (F1, scoping check).
- `TestThresholdCheck::test_nan_score_rejected` (F6).
- `TestThresholdCheck::test_inf_score_rejected` (F6).
- `TestThresholdCheck::test_nan_threshold_rejected` (F6).
- `TestScoreAndWrite::test_above_threshold_writes_files_and_returns` (F4).
- `TestScoreAndWrite::test_below_threshold_raises` (F4 + AC2 integration lock).
- `TestScoreAndWrite::test_at_threshold_passes` (F4 + edge case).
- `TestColumnNamesSourceOfTruth::test_test_module_uses_imported_constant` (F3).

(F2 has no direct unit-test guard; the regression surface is the
removal of per-query `asyncio.run` from the test body. A future
contributor reverting the single-loop pattern would re-introduce
the bug, but the docstring on `_run_queries_against_corpus` names
the issue explicitly.)

**Suite at rectification time:** 579 passed, 3 skipped, ruff clean.
