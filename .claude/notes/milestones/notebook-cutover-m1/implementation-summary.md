# Implementation Summary — notebook-cutover-m1

**Path:** inline (orchestrator main session)
**Base SHA:** `c16aac7ad4b962e5af96446bb2a4fbb71bc1cb62`
**Generated:** 2026-05-28

---

## ⚠ Premise update since research (READ — it INVERTS the synthesis's priority)

The Phase-1 synthesis (`research-synthesis.md` §"Premise correction") concluded the
cutover had **"no live-serving impact today"** because, at research time, the MCP
server did not read per-notebook `lancedb`. **That premise is now obsolete:**
notebook-retrieval-m1 (fork C, `ARXMCP_NOTEBOOK`) and m2 (fork A,
`filters.notebook`) shipped between the research phase and now — the server reads
the active `<slug>/lancedb` directly. So the cutover's "future-proofing" value
(synthesis §"corrected value proposition" #2) has come true: **promoting staging
now makes the improved data live.** The implementation plan was unaffected (the
swap mechanics are independent of the read path); only FM-2 (open server handle →
restart needed) is upgraded from cleanliness to correctness — the CLI prints a
RESTART hint after every cutover.

## One-line

`tools/notebook_cutover.py` + `make notebook-cutover`: atomic per-notebook
`lancedb-staging → lancedb` swap (2-rename + EXDEV guard + rollback-on-step-2),
BM25 built for the staging version pre-swap, N=2 timestamped backups, slug
Threat-1 validated, `--all-notebooks` default with per-notebook failure isolation.

## Acceptance criteria status

- **[AC1] swap+backup ✅** `perform_cutover` swaps staging→active, leaves a
  `lancedb-prev-<ts>` backup, removes staging. Verified:
  `test_notebook_cutover.py::test_cutover_swaps_and_backs_up`.
- **[AC2] rollback lossless ✅** `perform_rollback` restores the most-recent
  backup to `lancedb` and demotes the promoted content to `lancedb-staging`.
  Verified: `::test_rollback_is_lossless_roundtrip`.
- **[AC3] downgrade-refuse ✅** staging `corpus_version` ≤ active → `CutoverError`,
  no mutation; `--force` overrides. (The live data supports this: staging v645 >
  active v369, v143 > v49.) Verified: `::test_downgrade_refused`,
  `::test_equal_version_refused`, `::test_force_overrides_downgrade`.
- **[AC4] missing/incomplete staging ✅** no staging dir OR staging without
  `corpus-version.json` → refuse, no mutation. Verified:
  `::test_missing_staging_refused`, `::test_staging_without_marker_refused`.
- **[AC5] all-notebooks isolation ✅** `--all-notebooks` (default) cuts over every
  promotable notebook; one failure does not abort the others; exit non-zero.
  Verified: `::test_all_notebooks_isolates_failures`,
  `::test_all_notebooks_empty_is_clean`.
- **[AC6] N=2 prune ✅** at most 2 `lancedb-prev-*` retained (oldest pruned).
  Verified: `::test_backup_retention_prunes_to_two`.
- **[AC7] BM25 pre-swap ✅** `build_bm25_index(staging_path, staging_version)` runs
  BEFORE any rename (R2's clean-refusal ordering); a build failure leaves the
  directories untouched. Verified: `::test_bm25_built_for_staging_version`,
  `::test_bm25_failure_refuses_with_no_mutation`. NOTE: notebook retrieval is
  dense-only (m1/m2 + the spikes), so this index is built-but-unused at query
  time; its value is the clean pre-mutation refusal + sparing a slow first-boot
  auto-build if a fork-C server ever opens this version.
- **[AC8] docs ✅** `make notebook-cutover` help text + the module docstring
  document the measure-then-promote workflow, rollback, the restart hint, and the
  `PYTHON` 3.9 trap (`uv run python -m tools.notebook_cutover`).
- **[AC9] live promotion — OPERATOR-DEFERRED.** The two live staging datasets
  (bridgeland v645, shimura v143) are promotable by the tool; the actual live run
  on `var/arxmcp/notebooks/` is a separate operator step (it was auto-mode-blocked
  earlier this session — correctly). The pipeline tests use synthetic fixtures.
- **[X-1] `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED ✅** No MCP surface touched.
- **[X-2] `EXPECTED_BP1_SHA256` UNCHANGED ✅** No prompt/tool edit.
- **[X-3] ruff clean; make test green ✅** Full suite: only the 3 known
  pre-existing failures (latexmlc ×2 + Kùzu cite_neighbors ×1).
- **[X-4] no `CHUNKER_VERSION` bump ✅**

## New code

- **`tools/notebook_cutover.py`** — `discover_promotable`, `perform_cutover`,
  `perform_rollback`, `_prune_backups`, `_assert_same_filesystem` (EXDEV guard),
  `main()` (`--notebook` / `--all-notebooks` default / `--rollback` / `--force`).
  Reuses `validate_slug` + `notebook_dir` (Threat-1) and `build_bm25_index`.
- **`Makefile`** — `notebook-cutover` target (+ `.PHONY`), with the MIN_PY_MINOR
  guard and the operator help block.

## New tests

- `tests/test_notebook_cutover.py` — 17 tests (AC1–AC7 + first-ingest +
  swap-step-2 restore + Threat-1 traversal + rollback-no-backup + discover).
  Synthetic fixtures (corpus-version.json marker dirs); `build_bm25_index`
  monkeypatched to a recorder.

## External writes required

None — `os.rename`/`shutil.rmtree` within `var/arxmcp/notebooks/` + a BM25 write
to `var/arxmcp/index/bm25/v<N>/`. The AC9 live promotion is operator-invoked.

## Deviations from the brief / synthesis

1. **Premise inversion** (above): the cutover now HAS live-serving impact —
   strengthens the case, doesn't change the code.
2. **BM25 built-but-unused** for dense-only notebook retrieval — kept per the
   locked synthesis (AC7) for the clean-refusal property; documented so the next
   reader doesn't assume notebook BM25 is on the query path.

## Commit range

`c16aac7..<HEAD>` (filled after the feat commit lands).
