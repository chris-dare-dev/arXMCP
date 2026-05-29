# Critique — notebook-ops-hardening-m1

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** 9cd28af839e6c0e771cb7f2fab36595a29f7cae9..5ff32641c01f03b46c18d7bfd8db61e3f3255e45
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the milestone is correct on the common path, but the
  WARN-not-fail decision on a BUSY WAL checkpoint can ship a corrupt-on-open
  `notebooks.db` snapshot — verified live, not theoretical (F1, HIGH).
- Finding counts: 0 CRITICAL, 1 HIGH, 2 MEDIUM, 1 LOW.
- Highest-risk file:line — `ops/cron/arxmcp-backup.sh:106-109` (the
  `ok|absent|no-wal` case → everything else WARNs and proceeds with `-wal`
  excluded from the manifest).
- Verified clean: pipefail exit-code capture (`printf | restic | tail` with
  `set -o pipefail` returns restic's code, not tail's — live-tested with stubs
  exiting 3 and 1).
- Verified clean: both `bash -n` checks pass; all milestone tests pass (one
  `requires_restic` skipped by design). Cache/tool-surface (Axis 1/4)
  untouched. No-fork (Axis 7), local-first (Axis 5), tier-sequencing (Axis 6)
  all clean.
- The pre-existing E11_S05 lone-apostrophe parse bug is genuinely fixed and
  guarded by two new regression tests (`bash -n` + balanced-quote count).
- The `*/cache/retrieval.db` exclude is correct and sufficient: the GLOBAL
  `var/arxmcp/cache/retrieval.db` is never in the manifest (only the single
  file `cache/notebooks.db` is), so only the per-notebook query caches need
  the glob.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Busy WAL checkpoint → corrupt notebooks.db snapshot, only WARNs

- **Severity:** HIGH
- **Source:** adversary
- **File:** ops/cron/arxmcp-backup.sh:106-109
- **What:** When `ops/checkpoint_notebooks_db.py` returns `busy` (or `error`),
  the wrapper's `case` matches only `ok|absent|no-wal`; the `*)` arm logs
  `WARN: ... backup may capture a slightly-stale notebooks.db` and proceeds.
  The manifest deliberately excludes the `-wal`/`-shm` sidecars
  (`checkpoint_notebooks_db.py:13-17`), relying on the checkpoint having folded
  every committed frame into the main file. On a busy checkpoint that
  assumption is FALSE.
- **Why it matters:** I reproduced this live. A `wal_checkpoint(TRUNCATE)`
  blocked by a concurrent read txn returned `(busy=1, log=4, checkpointed=3)`:
  the WAL was NOT truncated and the latest committed frame stayed only in the
  excluded `-wal`. Copying the main file alone (what restic backs up) then
  raised `database disk image is malformed` on BOTH a plain open AND
  `PRAGMA integrity_check`. So the WARN message understates the risk: the
  snapshot is not "slightly stale" — `notebooks.db` for that night can be
  unreadable. The restore drill's `integrity_check` would catch it, but only
  quarterly, by which time 7/4/12 retention may have aged out the last GOOD
  snapshot. This is the exact silent-data-loss class the milestone exists to
  prevent, re-introduced on the (rare, but real) busy path. Backup runs in the
  03:30 idle window so it is uncommon → HIGH, not CRITICAL.
- **Proposed fix:** Do not silently proceed on a non-self-consistent
  checkpoint. In `checkpoint_notebooks_db.py::checkpoint`, retry the TRUNCATE a
  few times with a short sleep (e.g. 3 attempts, 2s apart) before returning
  `busy`. In the wrapper `case`, treat a residual `busy`/`error` as a
  notebooks.db backup failure: set `BACKUP_STATUS="partial"` (so
  `backup-status.json` records it and the prior good snapshot is retained by
  `forget`) and keep the WARN — OR fall back to also adding
  `${NOTEBOOKS_DB}-wal` and `${NOTEBOOKS_DB}-shm` to `BACKUP_PATHS` for that
  run so the captured set can be restored consistently. Either way, the
  operator must be able to see from the sentinel that notebooks.db was not
  cleanly captured. Reword the WARN to "may be inconsistent/unreadable", not
  "slightly-stale".
- **Regression guard:** Add a unit test in `tests/test_backup_wrapper.py` (or a
  new `tests/test_checkpoint_notebooks_db.py`) that forces a busy checkpoint:
  open `notebooks.db` in WAL mode on connection A, hold an open read txn on
  connection B, commit a frame on A, then assert `checkpoint(db)` returns
  `busy` AND that a main-file-only copy fails `PRAGMA integrity_check` — pinning
  the invariant that `busy` must NOT be treated as a clean capture. Add a
  text-grep test asserting the wrapper marks the backup partial (or includes
  the sidecars) on a non-ok checkpoint status.

### F2 — Checkpoint stderr swallowed by `2>/dev/null`; failure modes collapse to "error"

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ops/cron/arxmcp-backup.sh:105
- **What:** The checkpoint is invoked as
  `python3 .../checkpoint_notebooks_db.py "${NOTEBOOKS_DB}" 2>/dev/null || echo error`.
  Any real diagnostic the helper or Python interpreter emits (DB locked,
  permission denied, `python3` missing, an unexpected `sqlite3` exception) is
  discarded; all distinct failures collapse into the single token `error`,
  which the `case` arm treats identically to `busy`. The operator gets a WARN
  with no actionable cause.
- **Why it matters:** This is an observability foot-gun on the exact path that
  F1 makes dangerous. When the checkpoint silently fails, the operator cannot
  tell a transient busy-lock from a hard misconfiguration (e.g. the helper path
  is wrong, or `notebooks.db` is owned by another user). It also masks the case
  where `checkpoint()` itself raised an uncaught exception — the helper's
  docstring promises "exit 0 on a reachable DB" but an unhandled `sqlite3`
  error inside `checkpoint()` (e.g. a locked DB raising rather than returning a
  busy row) would propagate and become an opaque `error`. Not on the common
  path → MEDIUM.
- **Proposed fix:** Drop the `2>/dev/null` so the helper's stderr reaches the
  cron/journal log, or redirect it to the same log the wrapper writes. In
  `checkpoint_notebooks_db.py::checkpoint`, wrap the `conn.execute(...PRAGMA
  wal_checkpoint...)` in a `try/except sqlite3.Error` that returns a distinct
  status (e.g. `locked`/`error`) instead of letting it propagate, so the
  documented "exit 0 on a reachable DB" contract actually holds and the wrapper
  can distinguish causes.
- **Regression guard:** Add a unit test that points `checkpoint()` at a path
  whose parent is unwritable / a locked DB and asserts it returns a defined
  status string rather than raising; and a wrapper text-grep test asserting the
  checkpoint invocation does not redirect stderr to `/dev/null` (or routes it
  to the log).

### F3 — `smoke_check_notebooks` PDF count matches ANY path containing a "notebooks" segment

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ops/restore_drill_check.py:196-200
- **What:** `pdf_count` is `sum(1 for p in restore_path.rglob("*.pdf") if
  p.is_file() and "notebooks" in p.parts)`. The guard `"notebooks" in p.parts`
  matches ANY path component literally equal to `notebooks`, not specifically
  the `var/arxmcp/notebooks/` subtree. A restored corpus PDF (or any future
  backup path) that happens to live under a directory named `notebooks`
  anywhere in the tree is counted as an "uploaded notebook PDF", and
  conversely the count is not anchored to the canonical
  `.../var/arxmcp/notebooks/<slug>/` layout the drill claims to verify.
- **Why it matters:** The drill's `notebook_pdf_count` is the
  signal the operator reads to confirm uploaded PDFs round-tripped. A loose
  substring-on-parts match makes the count an unreliable proxy: it can
  over-count (false confidence) and is not tied to the actual notebook source
  prefix. It does not cause a false PASS by itself (the drill passes on
  `notebooks_db_found` + LanceDB rows, and absence of notebook PDFs is not a
  failure), so it is a correctness-of-signal issue, not a broken gate →
  MEDIUM.
- **Proposed fix:** Anchor the match to the `var/arxmcp/notebooks` segment
  sequence, e.g. require the relative parts to contain the ordered subsequence
  `("var", "arxmcp", "notebooks")` or check that `"notebooks"` is preceded by
  `"arxmcp"` in `p.parts`. Mirrors the `_locate_kuzu_root` discipline
  (`restore_drill_check.py:73-76`) which already filters on
  `entry.parent.name == "index"` to avoid matching arbitrary `kuzu` dirs.
- **Regression guard:** Add a test seeding a `*.pdf` under a decoy
  `.../something/notebooks/x.pdf` that is NOT under `var/arxmcp/notebooks/` and
  assert it is NOT counted; plus the existing positive case under the canonical
  prefix.

### F4 — WARN comment claims "slightly-stale"; understates the corruption risk

- **Severity:** LOW
- **Source:** adversary
- **File:** ops/cron/arxmcp-backup.sh:97-103
- **What:** The block comment and WARN text describe a busy/partial checkpoint
  as producing a "slightly-behind"/"slightly-stale notebooks.db" that is
  "degraded, not corrupt". Per the F1 live reproduction, a main-file-only copy
  after a busy TRUNCATE checkpoint can be unreadable (malformed), i.e. corrupt
  on open — not merely stale.
- **Why it matters:** Documentation accuracy on a data-durability path. An
  operator reading this comment will under-prioritize a busy-checkpoint WARN,
  believing the worst case is a slightly-old DB rather than an unrestorable
  one. Pure wording → LOW (the behavioral fix is F1).
- **Proposed fix:** Reword the comment and WARN to: "a busy/partial checkpoint
  leaves committed frames only in the (un-backed-up) -wal, so the captured
  notebooks.db may be stale OR corrupt-on-restore." Same wording in the
  `08-security-observability-ops.md` backup section if it repeats the claim.
- **Regression guard:** None required (doc-only); covered incidentally by the
  F1 guard.

## What was done well

- The pipefail exit-code capture for the new `printf | restic | tail` pipeline
  is correct (`arxmcp-backup.sh:122-132`): I stub-tested it and `$?` returns
  restic's exit (3/1), not tail's — the partial-success (exit 3) handling
  survives the refactor intact.
- The pre-existing E11_S05 lone-apostrophe parse bug is genuinely fixed; both
  ops scripts now pass `bash -n`, and the fix is guarded by two complementary
  regression tests (`bash -n` parse + even-apostrophe-count).
- The WAL-checkpoint-before-backup design is the right correctness call and is
  faithfully ordered (the `test_wal_checkpoint_runs_before_backup` test anchors
  on the real `printf | restic` invocation, not the header comment — a sharp
  test).
- The `--files-from-verbatim -` manifest is implemented as a printf pipe, which
  cleanly sidesteps the flock-subshell stdin open question the research flagged
  — a better resolution than the planned heredoc.
- The cache-exclusion EXCEPTION is handled exactly right: only the single file
  `cache/notebooks.db` is included, the global `cache/retrieval.db` is never in
  scope, and `*/cache/retrieval.db` correctly drops the per-notebook query
  caches. The design note's EXCEPTION call-out distinguishes it from
  `retrieval.db`.
- rglob-based discovery (`_locate_notebooks_db`) correctly reuses the E11_S05 F1
  closure pattern so the smoke check survives restic's absolute-source-path
  preservation under `--target`.
- The absent-vs-corrupt distinction in `smoke_check_notebooks` is correct:
  absent returns `(False, n)` without failing (pre-m1 snapshots), corrupt
  raises `RuntimeError` mapped from any `sqlite3.Error`, and `run_check`
  catches it as exit 1 rather than crashing — verified by the corrupt-db test.
- No `assert` for invariants, no `BaseHTTPMiddleware`, no `anthropic` import, no
  tool-schema/prompts/cache touch, no forked code, no `0.0.0.0`, no `latest`
  tags — the banned-pattern checklist is clean.
- The `requires_restic` opt-in marker follows the established
  `requires_latexmlc`/`requires_pdflatex`/`requires_mineru` convention exactly,
  with a faithful byte-for-byte round-trip integration test behind it.
- `--group-by host` on `forget` is a well-justified addition that prevents
  retention-window fragmentation as the manifest evolves — documented in both
  the script comment and the design note.

## Recommended rectification order

1. **F1 (HIGH)** — busy/error checkpoint must not be treated as a clean
   capture; this is the load-bearing data-durability fix. Fix the helper
   (retry + defined status) and the wrapper `case` (mark partial or include
   sidecars) together — they share the same code region.
2. **F2 (MEDIUM)** — stop swallowing checkpoint stderr and harden
   `checkpoint()` to return a status instead of raising; small and adjacent to
   F1, do in the same pass.
3. **F3 (MEDIUM)** — anchor the notebook PDF count to the
   `var/arxmcp/notebooks` segment; independent, cheap, mirrors existing kuzu
   discipline.
4. **F4 (LOW)** — reword the busy-checkpoint comment/WARN; trivially folds into
   the F1 edit. Defer if F1 is not taken.

## Rectification status

All four findings fixed (re-verify gate: F1's busy→corrupt claim was
live-reproduced before fixing — `wal_checkpoint(TRUNCATE)` returned `(1,4,3)`
with the WAL un-truncated, and a main-file-only copy raised `database disk
image is malformed`).

- **F1 (HIGH) — FIXED.** `ops/checkpoint_notebooks_db.py::checkpoint` now
  RETRIES the TRUNCATE (3 attempts, 2s apart; params for testability) and
  returns a degraded status (`busy`/`locked`) the caller must not treat as
  clean (new `CLEAN_STATUSES = {ok, absent, no-wal}`). `ops/cron/arxmcp-backup.sh`
  no longer silently proceeds: on a degraded status it (a) appends the
  `${NOTEBOOKS_DB}-wal`/`-shm` sidecars to `BACKUP_PATHS` for that run so the
  captured set can recover, and (b) forces `BACKUP_STATUS="partial"` so the
  sentinel flags it and `forget` keeps the prior good snapshot. Regression
  guards: `tests/test_checkpoint_notebooks_db.py` (reader-blocks-TRUNCATE →
  `busy`; main-only copy after busy is malformed-or-stale, never faithful) +
  `tests/test_backup_wrapper.py::test_degraded_checkpoint_marks_partial`.
- **F2 (MEDIUM) — FIXED.** The checkpoint invocation dropped `2>/dev/null`
  (diagnostics now reach the journal), and `checkpoint()` wraps the pragma in
  `try/except sqlite3.Error` → returns `locked` instead of propagating (the
  documented "exit 0 on a reachable DB" contract now holds). Guards:
  `test_directory_in_place_of_db_returns_locked` +
  `test_checkpoint_stderr_not_discarded`.
- **F3 (MEDIUM) — FIXED.** `smoke_check_notebooks` PDF count now anchors to the
  canonical `.../arxmcp/notebooks/` segment (`_under_notebooks_subtree`,
  mirroring the `_locate_kuzu_root` parent-name discipline) instead of matching
  any `notebooks` path component. Guard:
  `test_decoy_notebooks_dir_not_counted` (a decoy PDF under an unrelated
  `notebooks/` dir is NOT counted).
- **F4 (LOW) — FIXED.** Reworded the wrapper comment + WARN and the
  `08-security-observability-ops.md` backup section from "slightly-stale" to
  "stale OR corrupt-on-restore" with the degraded-path behavior. Folded into
  the F1 edit.

Net: 1 HIGH + 2 MEDIUM + 1 LOW all fixed; 0 deferred; 0 invalidated. New test
file `tests/test_checkpoint_notebooks_db.py`; the new `bash -n` guard caught a
fresh apostrophe regression I introduced mid-rectification (a `helper's` in a
comment) — fixed before commit.
