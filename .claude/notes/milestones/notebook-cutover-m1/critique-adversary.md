# Critique — notebook-cutover-m1

**Critic:** adversary
**Generated:** 2026-05-28T00:00:00Z
**Commit range:** c16aac7ad4b962e5af96446bb2a4fbb71bc1cb62..9625512cf2897484c8474e9aead0ed644edb173c
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the atomic-swap core, downgrade guard, rollback round-trip,
  and Threat-1 reuse are correct and faithful to the `ops/cutover.py` precedent;
  two real deviations (FM-3 prune contradiction + global BM25 namespace) need
  closing before this is trusted on the live `var/arxmcp/notebooks/` tree.
- Finding counts: 0 CRITICAL, 2 HIGH, 4 MEDIUM, 2 LOW.
- Highest-risk: `tools/notebook_cutover.py:189` builds the per-notebook BM25 into
  the GLOBAL `var/arxmcp/index/bm25/v<N>/` namespace keyed only on corpus_version —
  collision vector confirmed live (shared-corpus BM25 `v49` already on disk; shimura
  active is also `v49`).
- The impl-summary's AC7 rationale "notebook retrieval is dense-only (m1/m2)" is
  HALF wrong: fork-C (`ARXMCP_NOTEBOOK`) servers DO consume the notebook BM25 at
  `Resources.startup` (`server/resources.py:410`). Only fork-A is dense-only.
  Building pre-swap is therefore MORE justified than the summary claims — but the
  global-namespace bug it walks into is a live-serving correctness risk.
- The FM-3 "prune non-fatal, exit 0" guarantee from the locked synthesis is
  violated: `_prune_backups` raises `OSError` post-swap and `main()` does not catch
  it (`tools/notebook_cutover.py:209` + `:324`) — a successful promotion exits with
  an uncaught traceback. The docstring even claims "the CLI swallows it" — it does not.
- Test surface is strong (17 tests, AC1–AC7 covered) but AC7's "build pre-swap" is
  proven only against a monkeypatched recorder; no test exercises the real
  global-namespace collision or the prune-failure path.
- AC9 operator-deferral is honest: the tool + tests are real; only the live
  button-press is deferred (and was correctly auto-mode-blocked).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — BM25 built into GLOBAL version namespace; collision is live

- **Severity:** HIGH
- **Source:** adversary
- **File:** tools/notebook_cutover.py:189
- **What:** `perform_cutover` calls `build_bm25_index(staging, staging_version)`,
  which writes to `BM25_INDEX_ROOT / f"v{corpus_version}"` =
  `var/arxmcp/index/bm25/v<N>/` (`ingest/bm25_indexer.py:104,114`). That root is
  GLOBAL — shared between the corpus and every notebook — and keyed only on the
  per-dataset MVCC integer, which is NOT globally unique. `build_bm25_index`
  idempotent-skips when both artifact files already exist (`ingest/bm25_indexer.py:313`).
- **Why it matters:** Confirmed live: `var/arxmcp/index/bm25/v49/` already exists
  (built from the SHARED corpus, May 21) and `shimura-varieties/lancedb` is also
  version 49. A fork-C server (`ARXMCP_NOTEBOOK=shimura-varieties`) calls
  `BM25Phase.startup(corpus_version=49)` (`server/resources.py:410-413`), which loads
  the shared corpus's `v49` `chunk_ids.json`. The `live_chunk_ids` cross-check
  (`server/retrieval/bm25.py:500`) then raises `BM25IndexUnavailableError` →
  server refuses `/readyz` → the shimura notebook is UNBOOTABLE. For the
  cutover targets (bridgeland v645, shimura v143) there is no collision YET, but
  the tool does nothing to prevent the next one (a future re-embed can land any
  notebook at a version already owned by the corpus or another notebook). This is
  the same global-on-disk-namespace class as the retrieval-cache `cache_db_path`
  collision in notebook-retrieval-m1.
- **Proposed fix:** Build the notebook BM25 under a per-notebook root, not the
  global one. Cheapest: add a `bm25_root: Path | None` parameter to
  `build_bm25_index` / `_bm25_version_dir` defaulting to `BM25_INDEX_ROOT`, and have
  the cutover pass `notebook_dir(slug)/"bm25"`. The fork-C startup
  (`server/resources.py:410`) must derive the same per-notebook root when
  `config.notebook` is set, or the built index won't be found. If a same-commit
  server change is out of scope, downgrade the build to a documented WARN that the
  fork-C BM25 namespace is unsafe and explicitly do NOT build (the synthesis's
  "live BM25 dirs are v5/49/81/101/157/369 — v645/v143 do NOT exist yet" reasoning
  only held while no collision existed; v49 is now occupied).
- **Regression guard:** Test: pre-create `var/arxmcp/index/bm25/v<N>/` for the
  shared corpus, run `perform_cutover` on a notebook whose staging version equals
  `<N>`, assert the notebook's BM25 is written to a per-notebook path distinct from
  the global one (currently it idempotent-skips and writes nothing for the notebook).

### F2 — FM-3 violated: post-swap prune OSError crashes the run

- **Severity:** HIGH
- **Source:** adversary
- **File:** tools/notebook_cutover.py:209
- **What:** `perform_cutover` calls `_prune_backups(nb)` AFTER both swap renames have
  succeeded, with no try/except. `_prune_backups` runs `shutil.rmtree(victim)`
  (`tools/notebook_cutover.py:127`), which raises `OSError` on disk-full,
  permission, or a busy directory. `main()`'s loop catches only
  `(CutoverError, NotebookError)` (`tools/notebook_cutover.py:324`), so an `OSError`
  from prune propagates uncaught out of `main()` and aborts the entire
  `--all-notebooks` run with a traceback.
- **Why it matters:** The locked synthesis FM-3 says: "disk-full during prune →
  WARNING not ERROR; prune failure non-fatal, exit 0 if core swap succeeded." The
  shipped behavior is the opposite: a notebook that promoted SUCCESSFULLY is
  reported as a crash, the non-zero exit misleads the operator into thinking the
  swap failed (it didn't), and subsequent notebooks in `--all-notebooks` never run.
  The function docstring itself claims "the CLI swallows it post-swap"
  (`tools/notebook_cutover.py:122`) — a direct doc-vs-code contradiction; the CLI
  does not swallow it.
- **Proposed fix:** Wrap the prune call: `try: pruned = _prune_backups(nb) except
  OSError as exc: logger.warning("prune failed post-swap (non-fatal): %s", exc);
  pruned = []`. The swap already succeeded; prune is best-effort. Update the
  docstring to match (or make the docstring true by adding the guard).
- **Regression guard:** Test: monkeypatch `shutil.rmtree` to raise `OSError` after a
  successful 3rd cutover, assert `perform_cutover` returns normally (swap committed,
  active = new version) and `main()` exit code is 0 for that notebook.

### F3 — Cross-notebook MVCC version comparison can force spurious --force

- **Severity:** MEDIUM
- **File:** tools/notebook_cutover.py:175
- **What:** The downgrade guard compares `staging_version <= active_version` where
  both are per-dataset LanceDB MVCC counters. These are independent per dataset;
  the integer is NOT a global monotonic clock. The guard is only meaningful because
  staging is a re-embed OF the same notebook's active, so its version is normally
  strictly greater.
- **Why it matters:** A legitimate re-embed path that rebuilds a notebook's dataset
  from scratch (fresh LanceDB → version resets to a low integer) could produce a
  staging version ≤ the active's accumulated version, forcing the operator to pass
  `--force` on a perfectly valid promotion — eroding the guard's signal value. This
  is latent (the current re-embed-into-existing path monotonically increments), so
  it is not on today's common path, but the comparison is documented as a hard
  semantic guard and the assumption is unstated in the code.
- **Proposed fix:** Add a one-line comment at `:175` stating the guard ASSUMES
  staging is a re-embed of the SAME dataset (monotonic version), and that a
  from-scratch rebuild legitimately needs `--force`. Optionally compare
  `created_at` / chunk_count as a tiebreaker. The `active_info is None → -1`
  fallback (`:174`) is safe (any healthy staging ≥ 1 promotes over a corrupt
  marker, which is the intended recovery).
- **Regression guard:** Test asserting the `-1` fallback path promotes a v1 staging
  over a corrupt-marker active without `--force`; comment-only otherwise.

### F4 — AC7 "build pre-swap" proven only against a monkeypatched recorder

- **Severity:** MEDIUM
- **File:** tests/test_notebook_cutover.py:69
- **What:** Every test monkeypatches `build_bm25_index` to a recorder
  (`recorded_bm25` fixture, `:69-83`). `test_bm25_built_for_staging_version`
  (`:108`) asserts the recorder was called with `version=645` and that the staging
  dir existed at call time — but the REAL `build_bm25_index` (which reads the
  LanceDB table, fits BM25Okapi, and writes into the global namespace) is never
  exercised by any cutover test.
- **Why it matters:** The recorder cannot catch the F1 global-namespace collision,
  the idempotent-skip-writes-nothing behavior, or a real build raising on a
  zero-row staging dataset. "AC7 verified" is true only for call ordering, not for
  the index actually being usable post-swap. This is the
  "asserts on monkeypatched fakes that can't catch real regressions" pattern.
- **Proposed fix:** Add one integration-flavored test (no model needed — BM25 reads
  `body_tokens`, not embeddings) that builds a tiny real LanceDB staging dir and
  asserts the BM25 artifact lands at the EXPECTED (per-notebook, post-F1) path with
  matching chunk_ids. Keep it out of `requires_model`.
- **Regression guard:** The integration test itself is the guard.

### F5 — Rollback restores most-recent backup; older backups silently stranded

- **Severity:** MEDIUM
- **File:** tools/notebook_cutover.py:235
- **What:** `perform_rollback` restores `backups[-1]` (most recent) and demotes the
  current active to `lancedb-staging`. After one cutover this is correct and
  lossless (proven by `test_rollback_is_lossless_roundtrip`). But with N=2 backups
  present (two prior cutovers), rollback restores only the newest backup; the older
  `lancedb-prev-*` is left on disk untouched, and a SECOND rollback is impossible —
  it would refuse because `lancedb-staging` now exists (`:241`).
- **Why it matters:** Operators may expect rollback to be repeatable ("undo the last
  N cutovers"). It is single-level only. That is a defensible v1 choice, but it is
  undocumented in the rollback docstring (`:220-224`) and there is no test for the
  two-backup rollback scenario, so the limitation is invisible until an operator
  hits it mid-incident.
- **Proposed fix:** Document "single-level rollback only; restores the most recent
  backup; older `lancedb-prev-*` remain as cold snapshots and must be promoted
  manually" in the docstring + the Makefile help. No code change required.
- **Regression guard:** Test: two successive cutovers, then `perform_rollback`,
  assert active = the immediately-prior version and the older backup still exists
  on disk (documents the single-level semantics).

### F6 — _utc_ts_filename collision possible under back-to-back forced cutovers

- **Severity:** MEDIUM
- **File:** tools/notebook_cutover.py:75
- **What:** Backup dir names use `%Y%m%dT%H%M%S_%fZ` (microsecond). The docstring
  (`:73-74`) claims "two cutovers in the same second cannot collide." Microsecond
  resolution makes a same-microsecond collision astronomically unlikely for a human
  operator, but if two cutovers of the SAME notebook produced the identical
  microsecond timestamp, `os.rename(active, backup)` (`:198`) would rename the new
  active INTO the existing backup dir (POSIX rename onto an existing empty dir
  succeeds; onto a non-empty dir raises) — there is no `if backup.exists(): refuse`
  pre-check as `ops/cutover.py:523` has for its single rollback path.
- **Why it matters:** Practically unreachable on a single workstation, but the
  precedent (`ops/cutover.py`) explicitly refuses if the rollback target exists, and
  this tool dropped that guard. Defense-in-depth gap, not a live bug.
- **Proposed fix:** Add `if backup.exists(): raise CutoverError(...)` before
  `os.rename(active, backup)` at `:198`, mirroring `ops/cutover.py:523`.
- **Regression guard:** Test: monkeypatch `_utc_ts_filename` to a constant, run two
  cutovers, assert the second refuses rather than renaming onto the existing backup.

### F7 — Makefile version guard uses banned `assert`

- **Severity:** LOW
- **File:** Makefile (notebook-cutover target, the `$(PYTHON) -c "...assert sys.version_info..."` line)
- **What:** The new `notebook-cutover` target's Python version guard uses `assert
  sys.version_info >= (3, $(MIN_PY_MINOR))`. `assert` is banned project-wide
  (CLAUDE.md §4.7 — stripped under `-O`).
- **Why it matters:** Low: this is an inline Make recipe, not `server/`/`ingest/`
  source, it mirrors the existing `cutover` target verbatim (consistent precedent,
  not a newly-invented pattern), and `make` does not pass `-O`. Flagged for
  completeness; the precedent target has the same line.
- **Proposed fix:** Replace with `import sys; sys.exit(...)` guard, or leave as-is
  for consistency with `cutover` and fix both in a separate sweep. Defer.
- **Regression guard:** None warranted at LOW.

### F8 — discover_promotable will pick up stale/empty notebook scaffolds

- **Severity:** LOW
- **File:** tools/notebook_cutover.py:114
- **What:** `discover_promotable` includes any child dir containing a
  `lancedb-staging` SUBDIR, regardless of whether that staging has a valid
  `corpus-version.json`. The live tree has empty scaffolds (`csrf-victim`,
  `demo-nb`) — those lack staging so are skipped today, but a half-initialized
  notebook with an empty `lancedb-staging` dir would be discovered, then refused at
  `perform_cutover` (`:161`, no marker) and counted as a FAILURE → non-zero exit on
  `--all-notebooks`.
- **Why it matters:** Low: it fails safe (no mutation) and the error message is
  clear, but a single half-baked notebook turns an otherwise-clean `--all-notebooks`
  run non-zero, which may spook an operator. Cosmetic robustness.
- **Proposed fix:** In `discover_promotable`, additionally require
  `(child / STAGING_NAME / "corpus-version.json").is_file()` before listing, so
  incomplete staging dirs are silently skipped rather than surfaced as failures.
- **Regression guard:** Test: a notebook with an empty `lancedb-staging` (no marker)
  is NOT returned by `discover_promotable`.

## What was done well

- Atomic two-rename swap with rollback-on-step-2 (`tools/notebook_cutover.py:198-207`)
  faithfully replicates the `ops/cutover.py:558-569` precedent, including the
  best-effort restore on step-2 failure — the swap window invariant (active never
  permanently missing) is preserved and tested (`test_swap_step2_failure_restores_active`).
- The EXDEV `_assert_same_filesystem` guard (`:87-101`) correctly stats the parent
  for the not-yet-existing backup target and mirrors the precedent's st_dev check.
- Threat-1 is handled correctly: `validate_slug` is the FIRST call in BOTH
  `perform_cutover` (`:151`) and `perform_rollback` (`:225`), before any path
  construction, and `notebook_dir` adds symlink rejection + containment. Traversal
  test covers both entry points.
- BM25 is correctly ordered BEFORE the renames (`:189`) so a build failure refuses
  cleanly with zero mutation — the clean-refusal property the synthesis locked in,
  and it is tested (`test_bm25_failure_refuses_with_no_mutation`).
- The impl-summary HONESTLY discloses the obsolete-premise inversion up front and
  correctly concludes the swap mechanics were unaffected — the fork-C live-serving
  reality is acknowledged and the RESTART hint (`:328-333`) is the right mitigation.
- Downgrade guard with `--force` override, equal-version boundary, and the
  corrupt-marker `-1` recovery fallback are all correct and individually tested.
- `--all-notebooks` per-notebook failure isolation is real (try/except per slug in
  the loop) and tested end-to-end through `main()` with a mixed good/bad fixture.
- AC9 operator-deferral is honest — the tool and 17 tests are genuinely delivered;
  only the live button-press on real data is deferred, and it was correctly
  auto-mode-blocked rather than silently run.

## Recommended rectification order

1. F2 (FM-3 prune crash) — smallest fix, removes a guaranteed-wrong exit code on a
   successful promotion; also fixes the doc-vs-code contradiction.
2. F1 (global BM25 namespace) — highest blast radius; the live v49 collision makes
   the shimura fork-C notebook unbootable today. Coordinate the per-notebook BM25
   root with `server/resources.py:410` so the built index is also FOUND.
3. F4 (real BM25 build test) — naturally lands alongside F1; proves the index is
   usable, not just that a recorder fired.
4. F3, F5, F6, F8 — cheap comment/doc + defensive guards; fold in if ≤30 LOC each.
5. F7 — defer to a separate Makefile sweep (precedent target shares the pattern).

## Rectification status
<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
