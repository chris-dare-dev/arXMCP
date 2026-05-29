# Implementation Summary — notebook-ops-hardening-m1

**One-liner:** Notebook data (`var/arxmcp/notebooks/`) + metadata
(`var/arxmcp/cache/notebooks.db`) now enter the restic backup scope via a
`--files-from-verbatim -` manifest, with a mandatory pre-backup WAL checkpoint,
and the restore drill verifies a notebook round-trips.

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline (orchestrator) — 8 files, surgical, no clean
parallel boundary; the WAL-checkpoint ↔ manifest ↔ restore-drill ↔ test
invariant chain favors single-author coherence. Recorded deviation from the
strict `< 5 files` heuristic.

---

## What landed

### Backup scope + correctness (`ops/cron/arxmcp-backup.sh`)
- Switched the include-list from a positional `BACKUP_PATHS` array to a
  `--files-from-verbatim -` manifest (`printf '%s\n' "${BACKUP_PATHS[@]}" |
  restic backup --files-from-verbatim -`). This satisfies the AC's exact flag
  and sidesteps the flock-subshell stdin/heredoc open question entirely
  (restic's stdin is the printf pipe).
- Added `var/arxmcp/notebooks/` (whole subtree) + `var/arxmcp/cache/notebooks.db`
  to the manifest; added `--exclude "*/cache/retrieval.db"` (regenerable
  per-notebook query cache).
- **WAL checkpoint (CRITICAL):** new helper `ops/checkpoint_notebooks_db.py`
  runs `PRAGMA wal_checkpoint(TRUNCATE)` on `notebooks.db` BEFORE the snapshot
  (WARN-not-fail on busy). Without it a file-level copy of the WAL-mode DB can
  restore a state behind the last committed transaction.
- `forget` gained `--group-by host` (avoids retention-window fragmentation into
  separate paths-groups when the manifest evolves).
- Both `backup-status.json` `paths_backed_up` arrays list the new paths.

### Restore drill (`ops/restore_drill.sh`, `ops/restore_drill_check.py`)
- `restore_drill.sh` runs `restic check --read-data-subset=5%` (pack-file
  integrity) before the restore.
- `restore_drill_check.py` gained `smoke_check_notebooks()` (rglob discovery of
  `notebooks.db` → `PRAGMA integrity_check`, hardened to map any `sqlite3.Error`
  to `RuntimeError`; counts uploaded PDFs under the restored `notebooks/`
  subtree). Sentinel gained `notebooks_db_found` + `notebook_pdf_count`.
  `notebooks.db` absence is acceptable (pre-m1 snapshots); found-but-corrupt is
  a drill failure.

### Docs
- `.claude/notes/08-security-observability-ops.md` backup section: lists the
  notebook paths, calls out `notebooks.db` as the **EXCEPTION** to the
  cache-exclusion policy (retrieval.db stays excluded), documents the WAL
  checkpoint, `--group-by host`, the `read-data-subset` drill, and the FM-1/FM-5
  residual risks.
- `docs/ops/backup-restore.md`: Scope section + both state-file schemas.

### Pre-existing bug fixed (discovered)
- `ops/cron/arxmcp-backup.sh` had a **lone literal apostrophe** (`restic's`)
  inside the single-quoted `exec flock … bash -c '…'` body, which prematurely
  closed the quote — the committed E11_S05 script **failed `bash -n` and could
  never run**. It shipped because every existing test only greps the script text
  and restic is not installed here. Reworded to drop the apostrophe; added
  `bash -n` regression guards for both ops scripts.

### Tests
- `pyproject.toml`: `requires_restic` marker.
- `tests/test_backup_wrapper.py`: `TestBackupWrapperSyntax` (bash -n + balanced
  quotes), `TestNotebookBackupScope` (manifest paths, retrieval.db exclude, WAL
  checkpoint ordering, group-by host, sentinel paths, helper exists).
- `tests/test_restore_drill.py`: `TestSmokeCheckNotebooks` (found/absent/corrupt/
  rglob-prefix), `TestRunCheck::test_sentinel_carries_notebook_fields`,
  `read-data-subset` + bash -n script asserts, runbook + 08-security-note
  coverage asserts, and `TestResticNotebookRoundTrip` (`@requires_restic`,
  opt-in: real backup→wipe→restore→sha256 byte-equality of PDF + notebooks.db
  row recovery — the faithful AC G/W/T realization).

---

## Acceptance criteria status

- [x] **`--files-from-verbatim -` manifest covers `notebooks/` +
  `cache/notebooks.db`; regenerable caches excluded with a comment.**
  Implemented; `*/cache/retrieval.db` excluded with comment; asserted by
  `TestNotebookBackupScope`.
- [x] **Retention `7/4/12`; drill runs `check --read-data-subset=5%`.** Retention
  already correct (+`--group-by host`); `read-data-subset` added to
  `restore_drill.sh`; asserted by tests.
- [x] **G/W/T: notebook (PDF + notebooks.db row) recovers byte-for-byte via
  backup→wipe→restore.** `TestResticNotebookRoundTrip` (opt-in `requires_restic`
  — restic not installed by default) + the always-run `smoke_check_notebooks`
  unit tests.
- [x] **`08-security-...ops.md` backup section + ops note list the notebook
  paths.** Both updated; asserted by `TestSecurityNoteBackupSection` +
  `TestBackupRestoreRunbook::test_documents_notebook_backup_scope`.

---

## Deviations from the brief (recorded)

1. **Manifest form.** Synthesis chose a bash heredoc; the actual `bash -c`-body
   quoting made a printf-pipe (`printf | restic --files-from-verbatim -`)
   cleaner and it sidesteps the flock-stdin open question. Same AC flag, no new
   Python module for the manifest. (The WAL checkpoint IS a small Python helper.)
2. **Pre-existing apostrophe bug fixed** (out of the literal AC but in-scope: the
   script I am extending could not parse/run).
3. **WAL checkpoint** + **`--group-by host`** added beyond the literal AC text
   (correctness + retention-fragmentation foot-gun) per synthesis.
4. **lancedb/ included** (not excluded) — "regenerable caches" = `retrieval.db`,
   not the embedding store. Recorded in a script comment.

## Test surface

New/changed: `tests/test_backup_wrapper.py`, `tests/test_restore_drill.py`,
`ops/restore_drill_check.py`, `ops/checkpoint_notebooks_db.py` (new),
`ops/cron/arxmcp-backup.sh`, `ops/restore_drill.sh`, `pyproject.toml`,
`docs/ops/backup-restore.md`, `.claude/notes/08-security-observability-ops.md`.

## External writes required

**None surprising.** Standard feat/chore commits (local) + `git push origin main`
(per-event authorized, gated at finalize). No infra mutation, no ticket, no cloud
credential. The `requires_restic` integration test runs a throwaway local repo
under tmp_path only when opted in.
