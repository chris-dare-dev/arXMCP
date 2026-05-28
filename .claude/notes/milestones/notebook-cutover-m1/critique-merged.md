# Critique — notebook-cutover-m1 (merged)

**Critics:** adversary + infra-safety (Makefile changed → infra fired; oss-scout not requested)
**Generated:** 2026-05-28
**Commit range:** `c16aac7..9625512`
**Merged verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. The atomic-swap core, downgrade guard, rollback round-trip,
  Threat-1 reuse, and `--all-notebooks` failure isolation are correct and faithful
  to the `ops/cutover.py` precedent. Two HIGH deviations must close.
- Counts: **0 CRITICAL, 2 HIGH, 5 MEDIUM, 2 LOW** (adversary 0/2/4/2 + infra 0/0/1/0).
- **F1 (HIGH):** the cutover builds BM25 into the GLOBAL `var/arxmcp/index/bm25/v<N>/`
  namespace keyed only on the per-dataset MVCC version — collision confirmed live
  (shared-corpus `v49` exists; shimura active is also v49 → a fork-C
  `ARXMCP_NOTEBOOK=shimura-varieties` server is UNBOOTABLE today). This is a
  pre-existing m1/m2 fork-C-startup namespace bug the cutover surfaced and
  participates in.
- **F2 (HIGH):** FM-3 violated — a post-swap `_prune_backups` `OSError` propagates
  uncaught, so a SUCCESSFUL promotion exits non-zero (and the docstring falsely
  claims the CLI swallows it).
- Cross-critic: no overlap (infra scoped to Makefile, adversary to the tool); no
  agreement section needed.

## Findings (preserved IDs)

### F1 — BM25 built into GLOBAL version namespace; collision is live (HIGH)
`tools/notebook_cutover.py` `perform_cutover` → `build_bm25_index(staging, version)`
writes to the global `bm25/v<N>/` root (per-dataset MVCC, not globally unique).
Fork-C startup (`server/resources.py:410`) CONSUMES this index and cross-checks
chunk_ids; a version collision (shimura v49 vs shared v49) makes the notebook
unbootable. **Disposition: remove the build from the cutover** (fork-A is
dense-only; fork-C startup auto-builds via E04_S04 H1). The proper fix —
per-notebook BM25 root coordinated with fork-C startup — is the BM25 analog of
m1's `cache_db_path` isolation and is filed as a FOLLOW-UP (cross-cutting server
change, out of this cutover tool's scope).

### F2 — FM-3 violated: post-swap prune OSError crashes the run (HIGH)
`_prune_backups` (post-swap, unguarded) `shutil.rmtree` `OSError` propagates;
`main()` catches only `(CutoverError, NotebookError)`. **Fix:** wrap the prune in
`try/except OSError → WARN, non-fatal`; correct the docstring.

### F3 — cross-notebook MVCC version comparison assumption unstated (MEDIUM)
The downgrade guard assumes staging is a re-embed OF the same active (monotonic
version). **Fix:** comment the assumption at the guard; the `active_info is None →
-1` recovery fallback is safe (add a guard test).

### F4 — AC7 "build pre-swap" proven only against a monkeypatched recorder (MEDIUM)
**OBVIATED by F1:** removing the build removes the thing F4 said was under-tested.
Replaced by an F1 guard test (the cutover writes NO global BM25).

### F5 — rollback is single-level; older backups stranded; undocumented (MEDIUM)
`perform_rollback` restores only the most-recent backup; a second rollback refuses
(staging exists). **Fix:** document single-level semantics in the docstring +
Makefile help; add a two-cutover-then-rollback test.

### F6 — `_utc_ts_filename` collision has no `backup.exists()` pre-check (MEDIUM)
The precedent (`ops/cutover.py:523`) refuses if the swap target exists; this tool
dropped that guard. **Fix:** `if backup.exists(): raise CutoverError(...)` before
the rename; test with a monkeypatched constant timestamp.

### F7 — Makefile version guard uses banned `assert` (LOW)
Mirrors every sibling target verbatim; `make` does not pass `-O`. **DEFER** to a
separate Makefile-wide sweep.

### F8 — `discover_promotable` lists staging dirs lacking a marker (MEDIUM→treated cheap)
A half-initialized `lancedb-staging` (no `corpus-version.json`) is discovered then
refused → turns an `--all-notebooks` run non-zero. **Fix:** require
`corpus-version.json` in `discover_promotable`; test. (Adversary rated LOW; fixing
is one line — folded in.)

### IS1 — `notebook-cutover` absent from `make help` (MEDIUM, infra)
The default-all-notebooks scope + restart requirement live only in `@#` recipe
comments. **Fix:** add a `help` entry with the all-notebooks-default + restart note.

## Recommended rectification order
1. F2 (HIGH) — smallest; removes a guaranteed-wrong exit on success.
2. F1 (HIGH) — remove the global-namespace build; file the per-notebook-BM25-root
   follow-up.
3. IS1 (MEDIUM) — `make help` entry.
4. F3, F5, F6, F8 (MEDIUM, cheap) — comment/doc/guards + tests.
5. F7 (LOW) — defer. F4 — obviated by F1.

## Rectification status

Generated 2026-05-28. Re-verify gate: F1 + F2 (both HIGH) re-read at cited
lines and confirmed live-valid before fixing; no findings invalidated.

- **F1 (HIGH) — FIXED.** Removed the `build_bm25_index` call + import from
  `tools/notebook_cutover.py` (the global-namespace write was unsafe; fork-C
  startup auto-builds, fork-A is dense-only). Module + `perform_cutover`
  docstrings document the AC7 resolution. The proper fix (per-notebook BM25
  root coordinated with fork-C startup) is filed as a follow-up. Guard:
  `test_cutover_builds_no_global_bm25` (cutover writes nothing to a
  monkeypatched BM25 root).
- **F2 (HIGH) — FIXED.** `perform_cutover` now wraps `_prune_backups` in
  `try/except OSError → WARN`, so a post-swap prune failure is non-fatal (the
  promotion stands, exit stays 0). `_prune_backups` docstring corrected (was
  "the CLI swallows it" — now accurate). Guard:
  `test_prune_failure_does_not_fail_promotion`.
- **F3 (MEDIUM) — FIXED.** Commented the MVCC monotonicity assumption at the
  downgrade guard; the corrupt-marker `-1` recovery path is now tested.
  Guard: `test_corrupt_active_marker_promotes_as_recovery`.
- **F4 (MEDIUM) — OBVIATED by F1** (no build → nothing to "really build"-test).
- **F5 (MEDIUM) — FIXED.** `perform_rollback` docstring + `make help` document
  single-level rollback. Guard: `test_rollback_is_single_level`.
- **F6 (MEDIUM) — FIXED.** Added an `if backup.exists(): raise` pre-check before
  the swap rename (mirrors `ops/cutover.py:523`). Guard:
  `test_backup_name_collision_refused`.
- **F7 (LOW) — DEFERRED.** Makefile `assert` mirrors every sibling target; `make`
  passes no `-O`. Tracked for a separate Makefile-wide sweep.
- **F8 (MEDIUM/cheap) — FIXED.** `discover_promotable` now requires a
  `corpus-version.json` marker, so a half-initialized staging dir is skipped
  rather than failing an `--all-notebooks` run. Guard:
  `test_discover_skips_staging_without_marker`.
- **IS1 (MEDIUM) — FIXED.** Added a `notebook-cutover` entry to `make help`
  naming the all-notebooks default, the scope flag, rollback, and the restart
  requirement.

**Follow-up filed:** per-notebook BM25 root (the F1 root-cause fork-C startup
collision) — a separate milestone (BM25 analog of m1's cache_db_path isolation).

**Net rect tests:** removed 2 BM25-build tests (obviated), added 6
(no-global-BM25, prune-non-fatal, corrupt-marker recovery, single-level
rollback, backup-collision, discover-skips-bare). Cutover test file: 21 tests.
