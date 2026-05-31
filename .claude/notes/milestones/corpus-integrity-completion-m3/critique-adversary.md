# Critique — corpus-integrity-completion-m3

**Critic:** adversary
**Generated:** 2026-05-31T22:40:31Z
**Commit range:** `1a398f7..6b3f422`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. The shipped tests pass (3 passed in 1.42s, well under the 5s/test AC) and the divergence-detection path is end-to-end exercised correctly via monkeypatch — but the implementation summary makes two factually-wrong claims about WHAT the test catches, and the headline "multi-paper write" framing is structurally false against the actual `_seed_corpus` shape (single call, not n calls).
- 0 CRITICAL, 2 HIGH, 3 MEDIUM, 1 LOW.
- Highest-risk file:line — `tests/test_server_startup_integration.py:75` + summary §"Regression-class coverage": the test imports `_seed_corpus` which calls `write_chunks` ONCE with n chunks (verified at `tests/test_corpus_count_reconciliation.py:81`), so the **multi-paper cumulative-marker bug shape is NOT reproduced** by this fixture.
- A reintroduced `chunk_count = len(chunks)` regression on the write path would NOT fail either test in this file (positive test trivially passes since `len(chunks) == count_rows()` for a single-call fixture; mutation test doesn't exercise the production code path). The summary's "Direct re-regression" coverage claim is FALSE.
- The cross-test import (`from tests.test_corpus_count_reconciliation import _patch_model, _seed_corpus`) is sound at the import-mechanic level (verified under `pytest tests/`, `pytest tests/test_server_startup_integration.py`, `-k integration`) — but the import couples this test's correctness to an unmarked helper API in a sibling test file with no contract pin.
- `bad_marker_writer` signature (`tests/test_server_startup_integration.py:185-193`) hard-codes the exact 5-keyword set of `write_corpus_version_marker`. Any future kwarg addition (e.g. `corpus_hash`, `created_at_override`) breaks the wrapper with `TypeError` rather than silent skew, but the resulting test failure points at the wrapper, not the new kwarg — operator confusion at the fix site.
- Parallel marker-write path in `server/routes/notebooks.py:935-985` mirrors `write_corpus_version_marker` VERBATIM and bypasses the monkeypatch target — the implementation summary's claim that the mutation test "generalizes to any future code path that bypasses the table-count reconciliation" is FALSE for this known-shipped sibling path.
- "What was done well" section populated with 7 bullets (the synthesis mismatch resolutions, FM-5/FM-9 guards, and tolerance-floor sanity test are genuinely sharp engineering).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Positive test would NOT fail on a reintroduced `len(chunks)` write-path regression

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tests/test_server_startup_integration.py:88-145` (positive test) + `tests/test_corpus_count_reconciliation.py:81` (single-call `write_chunks`)
- **What:** The implementation summary §"Regression-class coverage" claims the positive test catches any commit that rewrites `chunk_count = tbl.count_rows()` back to `chunk_count = len(chunks)`. This is FALSE. The fixture's `_seed_corpus(lancedb_path, n=30)` calls `write_chunks` exactly ONCE with a 30-chunk list (verified at `tests/test_corpus_count_reconciliation.py:67-81` — single `write_chunks(chunks, embeddings, ...)` call). In a single-call ingest, `len(chunks) == 30 == tbl.count_rows()`. A buggy `chunk_count = len(chunks)` would write the SAME value as the table count, the marker would equal the count, and the positive test would pass cleanly. The actual pre-m1 bug shape lived in **multi-call cumulative** ingest where `len(chunks)` reflected only the LAST batch (e.g. last paper had 1 chunk while the cumulative table had 30) — the m3 fixture does not exercise that shape.
- **Why it matters:** The headline KR-1 of the parent epic, restated in the file docstring at lines 4-9 and the test docstring at lines 91-103, is "any future commit that re-introduces a `len(...)`-flavored `chunk_count` write fails the mutation test in CI." With the chosen fixture, the regression DOES NOT fail either test. The mutation test catches divergence-detection regressions (a different bug class — useful, but not what the file claims). The positive test catches "is the divergence body shape correct on the happy path" (also useful, but not what the file claims). The headline regression-class protection the AC is the ENTIRE point of the milestone is not actually delivered.
- **Proposed fix:** Either (a) replace `_seed_corpus(lancedb_path, n=30)` with a loop that calls `write_chunks` N times with disjoint chunk batches (1 chunk per call, 30 calls), so the cumulative table grows past the last per-call `len(chunks)`; or (b) add a NEW test `test_pre_m1_len_chunks_regression_caught` that builds the multi-call cumulative fixture and asserts the positive-path divergence detection fires when `chunk_count = len(chunks)` is artificially reintroduced via monkeypatch on the live formula site. Option (b) is the smaller diff but the more honest regression guard.
- **Regression guard:** Add an assertion or comment in `_seed_corpus`-using tests that says "this fixture is single-call; the multi-call cumulative shape is NOT exercised — see [new test name] for that shape." Without this, future readers will assume the existing test covers the bug class.

### F2 — Implementation summary "Marker-side corruption" claim is overstated: parallel marker writer in `server/routes/notebooks.py` not intercepted

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/routes/notebooks.py:935-985` (the `_rewrite_corpus_version_marker` helper) + summary line 43
- **What:** Implementation summary line 43 claims the mutation test's `bad_marker_writer` intercept "generalizes to 'any future code path that bypasses the table-count reconciliation' — including, e.g., a hypothetical optimization that caches a stale count." But there is a known-shipped sibling path TODAY at `server/routes/notebooks.py:935-985` (`_rewrite_corpus_version_marker`) that performs its own `json.dumps + os.replace` of the marker file — it does NOT call `ingest.store.write_corpus_version_marker`. The docstring at lines 937-939 says "mirrors `ingest/store.py::write_corpus_version_marker` verbatim". A `monkeypatch.setattr(store_mod, "write_corpus_version_marker", ...)` does NOT intercept this path. The same is true for `tools/notebook_reconcile_marker.py:75+` which the comment says also mirrors the serializer.
- **Why it matters:** The implementation summary represents the test as protecting against an entire bug CLASS. It does not. It protects against bugs that flow through ONE module-level binding. The two parallel write paths are precisely the kind of "marker-side corruption" the summary claims to cover. An operator reading the summary and concluding "the integration test guards the write contract end-to-end" will be surprised when a regression in notebook ingest's marker rewrite ships without alarm.
- **Proposed fix:** Either (a) reword the implementation summary to specify the coverage scope (`ingest.store.write_corpus_version_marker` only — does NOT cover `server/routes/notebooks._rewrite_corpus_version_marker` or `tools/notebook_reconcile_marker`); or (b) add a second mutation test that monkey-patches the notebook-route marker writer and confirms `/readyz` divergence detection fires for that path. Option (a) is honest; option (b) is rigorous.
- **Regression guard:** A comment in `_rewrite_corpus_version_marker`'s docstring pointing to the m3 integration test and noting "this path is NOT covered by m3's mutation test — if changing chunk_count computation here, add a sibling test."

### F3 — Cross-test import couples to an unmarked helper API with no contract pin

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_server_startup_integration.py:75` (the import) + `tests/test_corpus_count_reconciliation.py:47` (the helper)
- **What:** The test imports `_patch_model, _seed_corpus` from `tests.test_corpus_count_reconciliation`. The leading-underscore name convention in Python's PEP 8 marks these as module-private. There is no contract anywhere (no docstring pin, no `__all__`, no separate `tests/conftest.py` extraction) saying these helpers are stable. A future refactor to `test_corpus_count_reconciliation.py` (rename, signature change, inline-and-delete) silently breaks the integration test — and the failure mode is an `ImportError` at collection time of `test_server_startup_integration.py`, which a maintainer may "fix" by re-copying the helper inline (losing the FM-1 dual-module-patch lesson) rather than restoring the shared abstraction.
- **Why it matters:** The synthesis (per implementation summary §"Mismatch A") explicitly picked import-over-copy on maintenance grounds ("one source of truth for the load-bearing `_patch_model` dual-module pattern"). That choice is defensible, but it requires either (a) promoting the helpers out of a leading-underscore name in a test module, or (b) explicitly marking the helpers as part of a shared-test-helper contract via `tests/conftest.py` extraction. Today neither is done. The shipped state is one PEP-8-naming-convention violation away from silent helper deletion.
- **Proposed fix:** Move `_seed_corpus` and `_patch_model` into `tests/_corpus_helpers.py` (mirroring the existing `tests/_graph_helpers.py` pattern), drop the leading underscores, and update both test files to import from there. ~30 LOC: one new file + two import-line changes. Belt-and-suspenders: add a docstring on each helper noting "Used by test_corpus_count_reconciliation.py AND test_server_startup_integration.py; signature changes require updating both callers."
- **Regression guard:** A grep on `_seed_corpus` and `_patch_model` would surface both call sites today; promoting to a shared module makes the dependency explicit at import-statement level.

### F4 — Implementation summary states `_seed_corpus` runs `write_chunks` 30 times (it runs once)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/notes/milestones/corpus-integrity-completion-m3/implementation-summary.md:13` + `tests/test_server_startup_integration.py:78-84` (docstring)
- **What:** Implementation summary line 13 says: "The test calls `_seed_corpus(lancedb_path, n=30)` (which runs `write_chunks` 30 times — once per paper, matching the production bulk-ingest per-paper cadence)". Test docstring at lines 78-84 says: "yields N chunks across N papers (one chunk per paper). 30 satisfies the '~30 chunks' intent." Both are factually wrong. Reading `_seed_corpus` at `tests/test_corpus_count_reconciliation.py:47-81`: it builds a list of n `ChunkRecord` objects, builds a SINGLE `EmbedRecord` with n vectors, and calls `write_chunks(chunks, embeddings, ...)` exactly ONCE. There is no per-paper loop calling `write_chunks` n times.
- **Why it matters:** Documentation drift in the implementation summary is mostly cosmetic, but here the wrong claim is load-bearing for the reader's belief that the test catches the m1 multi-paper bug shape. A reader who trusts the summary will conclude the test covers the bug class; reading the actual fixture shows it does not (see F1). The wrong claim cross-cuts every section that hand-waves about "multi-paper cumulative" behavior. This is the same shape as the "stale-docstring-anti-pattern" memory: the summary "completing" a milestone makes a structural claim that the code does not actually deliver.
- **Proposed fix:** Rewrite lines 13 and 82-84 to accurately describe the fixture: "single `write_chunks` call with n chunks, n papers; the m1 multi-call cumulative-bug shape is NOT exercised by this fixture — the mutation test exercises the divergence-detection contract independent of how chunk_count was computed."
- **Regression guard:** The accurate description forces the reader to confront F1 directly.

### F5 — `bad_marker_writer` keyword-only signature breaks loudly on future kwarg additions

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_server_startup_integration.py:185-201` (the wrapper) + `ingest/store.py:663-670` (the production signature)
- **What:** The mutation test's `bad_marker_writer` declares a keyword-only signature `(target_path, *, version, chunker_version, embedder_version, paper_count, chunk_count)`. The production `write_corpus_version_marker` (`ingest/store.py:663-670`) is `(lancedb_path, version, chunker_version, embedder_version, paper_count, chunk_count)` — positional-or-keyword. A future enhancement that adds a new keyword (e.g. `corpus_hash`, `parent_corpus_version`, anything from the m1 critique's referenced "future enhancements") will be passed by `write_chunks` to `bad_marker_writer` via keyword. The wrapper's hard-coded keyword set raises `TypeError: bad_marker_writer() got an unexpected keyword argument 'corpus_hash'`. The test fails — useful — but the failure points at the test wrapper, not at the production change. An operator debugging the failure may "fix" by adding the new kwarg to the wrapper signature, never realizing the test surface should be using `**kwargs` passthrough.
- **Why it matters:** The shipped wrapper is fragile in a way that creates misleading failure messages. The fix is one-line. The cost of not fixing is operator-confusion-during-rectification at some future milestone that legitimately extends the marker schema.
- **Proposed fix:** Replace the explicit kwarg list with `**kwargs` passthrough and a single override:
  ```python
  def bad_marker_writer(target_path, **kwargs):
      kwargs["chunk_count"] = 1  # PRE-M1 BUG SHAPE — last-batch-only
      return real_marker(target_path, **kwargs)
  ```
  3 LOC delta. Same behavior for the current signature; forward-compatible with kwarg additions.
- **Regression guard:** Comment line "Future-proof against marker-schema extensions per m3 adversary F5."

### F6 — `pytestmark = []` is dead code; comment above it is the only signal

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_server_startup_integration.py:284`
- **What:** `pytestmark = []` is a no-op for pytest. The line above it (`# ... no opt-in markers required`) is the only thing communicating intent. The implementation summary at line 17 calls this "an explicit 'no opt-in markers' marker for future reviewers" — but a no-op assignment is not a marker. A grep for `pytestmark` finds this line, but a maintainer would read it as "this file actively sets pytestmark to empty for some pytest reason," not as a documentation comment.
- **Why it matters:** Dead code that masquerades as semantic load. Either drop the line and keep the comment (it stands alone as a file-level comment), or use a real pytest marker the file genuinely needs.
- **Proposed fix:** Delete line 284 (`pytestmark = []`). Keep the explanatory comment block above it. Net: 1 LOC removed.
- **Regression guard:** None needed — pure cleanup.

## What was done well

- The synthesis-mismatch resolutions (Mismatch A: `_seed_corpus` over `build_synthetic_lancedb`; Mismatch B: sync `TestClient` over `httpx.AsyncClient`) are correctly grounded in the project's actual dependency tree and the actual helper semantics; both choices were verified by reading the production code, not paraphrased from the brief.
- The dual-module `_patch_model` reuse (over a single-module mock) carries forward the load-bearing notebook-retrieval-m2 lesson (`server/resources.py` binds `_get_model` by name at module load time); the test docstring at lines 36-43 names this explicitly.
- FM-5 guard at lines 122-130: asserting `body["chunk_count"] is not None` BEFORE the equality check stops `null == null` from passing vacuously if `Resources.startup` set the -1 sentinel. This is exactly the discriminator pattern flagged in adversary memory `[[vacuous-test-kept-as-documentation]]`.
- FM-9 guard: injecting `chunk_count=1` rather than `-1` in the mutation test avoids routing through the count-unavailable skip-branch of `compute_chunk_count_divergence` (verified at `server/resources.py:240-241`). The mutation reaches the actual divergence-detection code, not the "skip-check" branch.
- The monkeypatch target choice (`store_mod, "write_corpus_version_marker"` — the module-local binding, NOT a caller's import alias) is correct given that `ingest/store.py:946` calls the function by bare name from within its own module.
- The tolerance-floor sanity test (`test_synthetic_corpus_size_exceeds_divergence_tolerance_floor`) is a genuine novel contribution beyond the AC — it interlocks `_SYNTHETIC_CORPUS_SIZE` against the divergence-tolerance math and would catch a future shrunk fixture (e.g. n=2) that silently disarms the mutation test. Cheap insurance for a real failure mode.
- Wall-clock budget: 3 tests in 1.42s total, comfortably under the 5s/test AC-4 ceiling. Dual-module BGE-M3 stub keeps the lifespan boot under 0.5s instead of 5-30s real cold-load.

## Recommended rectification order

1. **F1** — extend the test surface to actually catch the `len(chunks)` regression class (multi-call cumulative fixture or a new sibling test). This is the load-bearing claim of the milestone; F4's doc-correction should follow F1's code fix or be rendered moot by it.
2. **F2** — either tighten the implementation-summary coverage claim or add a sibling mutation test for `server/routes/notebooks._rewrite_corpus_version_marker`. The "honest doc" path is the smallest diff.
3. **F4** — correct the wrong "`write_chunks` 30 times" claim in the implementation summary and the test docstring. If F1's fix lands by switching the fixture to multi-call, this becomes a re-write of the docstring to match the new fixture; if F1's fix lands via a new test, F4 stands as a separate doc correction.
4. **F3** — promote the helpers to `tests/_corpus_helpers.py` (or accept the cross-test import as deliberate, with a contract pin in the donor file's docstring).
5. **F5** — swap to `**kwargs` passthrough in `bad_marker_writer`.
6. **F6** — drop the dead `pytestmark = []` line.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
