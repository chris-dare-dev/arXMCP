# Critique — onboarding-uplift-m3 (merged)

**Critics:** milestone-adversary (4 findings: 0C/0H/1M/3L) +
milestone-infra-safety (1 finding: 0C/0H/1M/0L). **5 findings total**
(0 CRITICAL / 0 HIGH / 2 MEDIUM / 3 LOW).
**Generated:** 2026-05-31.
**Commit range:** `b66fa1e58fe2ee66f48ec4a73831624a9062bccf..72d5e183463dab323082bc08ad1438bda262ba18`
**Verdict:** SHIP-WITH-FIXES — all 5 are cheap and rectifiable.

## Executive summary

- **No CRITICAL, no HIGH.** The MVCC pinned-checkout invariant + the
  atomic-rewrite pattern + the byte-identical idempotency contract all
  hold. BP1/BP2 hashes UNCHANGED. Test isolation properly redirects
  both module bindings of `NOTEBOOKS_BASE`.
- **F1 MEDIUM (adversary)** — `reconcile_marker`'s 422 detail strings
  leak absolute install paths (`/Users/<username>/.../var/arxmcp/...`).
  Inconsistent with the sibling `notebook_health` 422 path which already
  omits paths. Drifts from the project's `redact_paths` precedent
  (`server/ingest_tracker.py:81` / m9 parse-tracker FM-4 closure).
- **IS1 MEDIUM (infra-safety)** — `.PHONY` group label "REPAIR /
  RECONCILE" disagrees with `make help`'s "FIRST TIME?" categorization
  for the same two targets. Operators reading either source build a
  different mental model of the target taxonomy. Fix: add a distinct
  "REPAIR / RECONCILE" section to `make help` so the two views agree
  (infra-safety's preferred option b).
- **F2 LOW** — `_DEFAULT_DB_PATH` declared at
  `tools/notebook_repair_registry.py:46` but never read. Dead weight;
  delete.
- **F3 LOW** — nested `aria-live="polite"` on the inner `<small>`
  inside an `aria-atomic="true"` parent (`server/routes/ui.py:317`)
  causes inconsistent screen-reader announcement. Drop the inner
  aria-live.
- **F4 LOW** — implementation summary claims "26 tests" in
  `tests/test_m3_endpoints.py` (actual count: 25). Bookkeeping drift.
  Fold into F3's regression test (one new test brings the count to 26
  for free).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix in Phase 4 |
| HIGH | wrong behavior on common path | always fix in Phase 4 |
| MEDIUM | subtle correctness, latent foot-gun | fix only if cheap (≤30 LOC) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — reconcile-marker 422 details leak absolute install path

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/routes/notebooks.py:936-937, 942-943`
- **What:** 422 responses include `{nb_lance}` (an absolute resolved
  path like `/Users/<username>/.../var/arxmcp/notebooks/<slug>/lancedb`).
  The sibling `notebook_health` endpoint at the same file's lines
  1026 / 1038 ALREADY OMITS paths from its analogous "no
  corpus-version.json" / "malformed" details — `reconcile_marker` is
  inconsistent.
- **Recommendation:** drop `{nb_lance}` from both 422 details and
  reference the slug: `f"no corpus-version.json for {slug!r}; run
  `make ingest` first"`. Matches `notebook_health`'s redacted form.
  Add regression test `test_422_detail_omits_absolute_path`.

### IS1 — `.PHONY` group labels mismatch `make help` categorization

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `Makefile:21-23` vs `Makefile:53-59`
- **What:** `.PHONY` comment assigns `repair-registry` + `reconcile`
  to "REPAIR / RECONCILE"; `make help` lists them under "FIRST TIME?
  (onboarding-uplift-m2)". The `Makefile:1-3` comment promises "each
  `.PHONY:` stanza below pairs with the section it describes" — this
  promise is violated.
- **Recommendation:** Option (b) per infra-safety — add a distinct
  "REPAIR / RECONCILE" section to `make help` so taxonomies align.
  Repair/reconcile are NOT first-time actions; they're corrective
  maintenance. ~6 LOC change to the `help` target.

### F2 — `_DEFAULT_DB_PATH` defined but never used in CLI

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/notebook_repair_registry.py:43-46`
- **What:** Module-level constant declared but `main()` imports
  `DEFAULT_DB_PATH` lazily from `server.operator_settings`. Dead
  weight + drift risk if a future maintainer adds references to it.
- **Recommendation:** delete the constant + its docstring comment.

### F3 — Nested `aria-live` on inner `<small>` inside `aria-atomic` parent

- **Severity:** LOW
- **Source:** adversary
- **File:** `server/routes/ui.py:317`
- **What:** Inner `<small aria-live="polite">` nested inside outer
  `<span aria-live="polite" aria-atomic="true">`. Screen readers
  handle nested live regions inconsistently — some announce both, some
  double-announce. Regresses the ui-attractive-polish-m1 UPL-3
  screen-reader contract (referenced verbatim in the same file's
  comment block at lines 261-267).
- **Recommendation:** drop `aria-live="polite"` from the inner
  `<small>`. The parent's `aria-live` + `aria-atomic` already cover
  the contents. Add regression test asserting the badge fragment
  contains exactly ONE `aria-live` attribute.

### F4 — Implementation summary claims 26 endpoint tests; actual is 25

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/notes/milestones/onboarding-uplift-m3/implementation-summary.md:68-70` + `tests/test_m3_endpoints.py`
- **What:** Summary claims `26 tests`; `grep -c "def test_"` returns 25.
- **Recommendation:** add F3's regression test (brings count to 26)
  OR update the summary to "25 tests". F3's path is the win-win.

## What was done well (concatenated, dedup)

- **MVCC pinned-checkout invariant correctly applied** at both REST
  handler (`server/routes/notebooks.py:947`) and CLI
  (`tools/notebook_reconcile_marker.py:124-125`) — `version=old_info.version`,
  never `None`.
- **Atomic-rewrite pattern is byte-identical to canonical** — tmp
  filename + os.replace + try/finally cleanup + sort_keys=True +
  ensure_ascii=False + trailing `\n`, verbatim mirror of
  `ingest/store.py::write_corpus_version_marker`. The minified-
  separator deviation flagged in the implementation summary was caught
  during smoke and corrected before landing.
- **`CorpusVersionInfo.with_counts()` validates input domain** with
  typed ValueError on non-int / negative counts.
- **D4 byte-identical idempotency is asserted by test, not by hope.**
  Both endpoint and CLI suites read the file bytes after two
  reconcile runs and assert equality.
- **BP1/BP2 cache hashes UNCHANGED.** Verified.
  `TestNoMCPSurfaceTouch` adds belt-and-braces.
- **Test isolation properly redirects both module bindings of
  `NOTEBOOKS_BASE`.** Sufficient because `notebook_lancedb_path(slug)`
  reads `_notebook_common.NOTEBOOKS_BASE` (no `base=` kwarg).
- **Per-dir failure isolation in `repair_registry`** — `_read_marker_safely`
  returns `(None, "malformed")` rather than raising; single bad
  marker doesn't abort the walk (FM-7).
- **TOCTOU race handled via `sqlite3.IntegrityError` catch.** The
  walk's `existing_slugs` snapshot may go stale; the catch routes
  racing slugs to `already_registered`.
- **`make reconcile` shell flow propagates curl exit codes** via
  `|| { echo ERROR; exit 1; }` after curl; server-down branch is the
  last command in its `else` branch.
- **`make reconcile NOTEBOOK=` server-up correctly falls back to CLI
  `--shared`** when no `NOTEBOOK=` is passed (no REST endpoint exists
  for shared-corpus reconcile). Honest fallback.
- **The `.PHONY` split correctly eliminates the 219-char single-line
  anti-pattern from m2 F8** and provides a maintainable per-section
  structure.
- **`SCOPE_SLUG`/`SCOPE_LABEL` shell vars in `reconcile`** are
  double-quoted inside assignments; no word-splitting hazard.
- **No `sudo`, no destructive defaults, no mutations outside the
  narrow documented paths** (notebooks.db + corpus-version.json).

## Recommended rectification order

1. **IS1 (MEDIUM)** — add "REPAIR / RECONCILE" section to `make help`
   so its taxonomy matches the `.PHONY` group labels. ~6 LOC.
2. **F1 (MEDIUM)** — drop `{nb_lance}` from `reconcile_marker`'s 422
   details; reference `{slug!r}` instead (matches `notebook_health`).
   Add regression test. ~5 LOC + ~10 LOC test.
3. **F3 (LOW)** — drop the nested `aria-live` from the inner `<small>`.
   Add regression test asserting exactly ONE `aria-live` in the
   fragment (this becomes the 26th endpoint test → folds F4 closure
   in for free).
4. **F2 (LOW)** — delete the dead `_DEFAULT_DB_PATH` constant in
   `tools/notebook_repair_registry.py`.
5. **F4 (LOW)** — folded into F3's regression-test addition.

## Rectification status (filled by Phase 4)

- **F1 (MEDIUM)** — RESOLVED. `reconcile_marker`'s 422 details no longer
  leak `{nb_lance}` (the absolute lancedb path). Both no-marker and
  malformed branches now reference `{slug!r}` instead, matching the
  sibling `notebook_health` endpoint's redaction discipline + the
  project's `redact_paths` precedent. Regression guard:
  `tests/test_m3_endpoints.py::TestReconcileMarker::test_422_detail_omits_absolute_path`
  (negative-asserts on `/var/arxmcp` substring across BOTH 422 branches).
- **IS1 (MEDIUM)** — RESOLVED. `make help` now has a distinct "REPAIR /
  RECONCILE" section that groups `repair-registry` + `reconcile`
  separately from "FIRST TIME?". The label now matches the `.PHONY`
  group label verbatim (per the infra-safety promise at
  `Makefile:1-3`). Operators reading either source now build the same
  taxonomy: repair/reconcile are corrective maintenance, not
  first-time actions.
- **F2 (LOW)** — RESOLVED. Deleted the dead `_DEFAULT_DB_PATH`
  module-level constant + its docstring comment from
  `tools/notebook_repair_registry.py`. Single source of truth restored
  via the canonical `server.operator_settings.DEFAULT_DB_PATH` import
  inside `main()`.
- **F3 (LOW)** — RESOLVED. Dropped `aria-live="polite"` from the inner
  `<small>` in `_build_remediation_block`. The parent `<span>`'s
  `aria-live` + `aria-atomic="true"` cover the contents (UPL-3
  contract preserved). Regression guard:
  `tests/test_m3_endpoints.py::TestStatusBadgeRemediation::test_remediation_small_does_not_redeclare_aria_live`
  (asserts ZERO `aria-live` in the inner block — the parent declares
  it once).
- **F4 (LOW)** — RESOLVED via F3's regression test addition + an
  updated implementation-summary line. m3 endpoint test count went
  from 25 → 27 (F1 + F3 regression guards landed in m3-endpoints.py);
  CLI count stays at 11. Total m3 tests: 38 → 39 → 39 (no double
  counting; F4 was a bookkeeping correction).

**0% invalidation rate** — all 5 findings re-verified cleanly. 2
MEDIUM + 3 LOW fixed (no findings deferred). 2 new regression tests
(`test_422_detail_omits_absolute_path`,
`test_remediation_small_does_not_redeclare_aria_live`). Full suite:
`3 failed, 3648 passed, 30 skipped, 1 xfailed` (3 pre-existing
m3-unrelated failures). ruff clean.
