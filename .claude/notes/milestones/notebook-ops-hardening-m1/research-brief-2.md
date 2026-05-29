# Research Brief — notebook-ops-hardening-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T13:00:00Z

---

## In-codebase context

### What the existing backup covers (and what it doesn't)

`ops/cron/arxmcp-backup.sh` (E11_S05) hard-codes three paths in `BACKUP_PATHS`:

```bash
BACKUP_PATHS=(
    "${REPO_ROOT}/var/arxmcp/index/lancedb"
    "${REPO_ROOT}/var/arxmcp/index/kuzu"
    "${REPO_ROOT}/var/arxmcp/corpus/chunks"
)
```

`var/arxmcp/notebooks/` and `var/arxmcp/cache/notebooks.db` are **absent**.
This is the gap the milestone closes.

The backup invokes `restic backup ... "${BACKUP_PATHS[@]}"` — no
`--files-from-verbatim` today. The milestone AC mandates switching to a
`--files-from-verbatim -` stdin manifest. This is a **structural change to
the backup invocation**, not an additive path append.

### notebooks.db WAL mode (CRITICAL — see FM-2 below)

`server/notebooks_store.py` opens `notebooks.db` with:

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=FULL")
conn.execute("PRAGMA fullfsync=ON")
```

`notebook-ops-hardening-m2` already set `synchronous=FULL` and `fullfsync=ON`
for durability. BUT: **WAL mode means three files exist on disk at any point:
`notebooks.db`, `notebooks.db-wal`, `notebooks.db-shm`.** A file-level backup
that captures only `notebooks.db` without the `-wal`/`-shm` sidecars — or
without a checkpoint — may restore a stale or inconsistent DB.

The `08-security-observability-ops.md` backup section states:
> "Caches: `/var/arxmcp/cache/`. NOT backed up; re-buildable on demand."

**THIS IS A DESIGN CONFLICT.** The milestone brief reclassifies `notebooks.db`
from "cache" (regenerable) to "non-regenerable user data" and moves it into
backup scope. The ops note must be updated to reflect this distinction
explicitly, or the next operator reading it will exclude `notebooks.db`
thinking it is a regenerable cache.

### Local-first contract confirmed

`08-security-observability-ops.md` backup section:
> "Strategy: nightly snapshot via `restic` (https://restic.net) to a local NAS
> or to Backblaze B2 (S3-compatible, $6/TB/month, deduped). The user constraint
> 'no S3' was about not paying AWS for arXiv; B2 for backup is a different
> question and a small cost (~$3/month for 500GB)."

No AWS-S3-only requirement. Local NAS path or B2 both fine. Local-first
contract holds.

### restore_drill_check.py checks LanceDB + Kùzu structurally

The existing `ops/restore_drill_check.py` (E11_S05) verifies:
- LanceDB opens and has >0 rows (via `open_chunks_table` + `count_rows`)
- Kùzu graph opens (best-effort)

It does NOT check `notebooks.db` existence, row count, or byte-equality of
PDFs. The milestone requires extending this check.

---

## External sources

### restic version

**restic is NOT installed on this workstation** (`restic version` → not on
PATH). The backup script checks for it and exits with a helpful install message.
`docs/ops/backup-restore.md` specifies `restic >= 0.16`.

### `--files-from-verbatim` vs `--files-from` (restic docs, stable branch)

Source: https://restic.readthedocs.io/en/stable/040_backup.html

**`--files-from`**: expands glob patterns, strips leading/trailing whitespace,
ignores `#`-prefixed comment lines and empty lines. NOT suitable when paths
contain spaces or when literal treatment is required.

**`--files-from-verbatim`**: reads each line as a literal path. No glob
expansion, no whitespace stripping, does not skip `#`-prefixed lines; empty
lines are still ignored. Correct for the manifest pattern in the AC.

**Neither flag supports exclusions** — they are include-only. Exclusions
require separate `--exclude` / `--exclude-file` flags alongside the manifest.

**Recommendation: use `--files-from-verbatim -`** (stdin, `-` means stdin).
This matches the AC exactly and avoids glob surprises with paths containing
brackets (LanceDB version directories may use `_v` suffixes, not brackets, but
verbatim is strictly correct).

### `forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12`

Source: https://restic.readthedocs.io/en/stable/060_forget.html

`restic forget` without `--prune` removes snapshot references but leaves data
blocks on disk. **`--prune` must be passed** (or `restic prune` run separately)
to reclaim space. The existing `arxmcp-backup.sh` already calls
`restic forget --prune ...` — this is correct.

**Default `--group-by` is `host,paths`.** When the include-list changes (e.g.,
adding `var/arxmcp/notebooks/`), snapshots taken before the change have
different `paths` than snapshots taken after. **This means the old snapshots
and new snapshots fall into DIFFERENT groups under `forget`.** The retention
policy is applied per-group: each group gets its own 7/4/12 window.
Consequence: immediately after adding the new paths, only 1 new-format snapshot
exists; forget will NOT prune old-format snapshots using the new policy — they
age out on their own schedule. This is safe but the operator should be aware.

To avoid group fragmentation, pass `--group-by host` or `--group-by ''` if the
intent is a single unified retention window. **For this milestone: recommend
`--group-by host`** to avoid the paths-fragmentation gotcha as the manifest
evolves.

### `check --read-data-subset=5%`

Source: https://restic.readthedocs.io/en/stable/045_working_with_repos.html

Accepted formats:
- `n%` — integer or float percentage of pack files randomly selected (e.g., `5%`, `2.5%`)
- `n/t` — select pack group `n` of `t` (round-robin, deterministic; combine with cron to cover 100% monthly)
- `nS` — file size limit (e.g., `50M`, `10G`)

`5%` is **valid syntax** and verifies **pack-file integrity** (confirms on-disk
pack files are unmodified since write). It does NOT verify structural index
consistency — for that, run `restic check` (no subset flag) separately.

The AC calls for `check --read-data-subset=5%` as part of the drill rotation.
This is correct and sufficient for a weekly/monthly spot-check. Add an
unsubsetted `restic check` (structural only, no data read) as the daily health
check.

---

## Failure modes

**FM-1: LanceDB mid-write when backup runs (torn LanceDB snapshot)**
- Trigger: restic file-copies LanceDB dataset dir while a write transaction
  (new paper ingest) is appending a version fragment.
- Symptom: restored LanceDB version manifest references a fragment file that
  is half-written; LanceDB raises `FileNotFoundError` or corrupt-read on open.
- Mitigation: LanceDB uses MVCC — the version counter in `corpus-version.json`
  points to a committed version. A new version's fragments are written THEN the
  version marker is atomically updated. File-level backup of a committed version
  is safe AS LONG AS the backup captures the marker and the fragment atomically.
  Restic's file-level snapshot does not guarantee this ordering. Mitigate by
  scheduling backup 90+ minutes after the ingest write window closes (already
  the case: ingest ends ~04:05, backup fires 04:10). Accept the residual risk;
  document in ops runbook.

**FM-2: notebooks.db backed up without WAL checkpoint (CRITICAL)**
- Trigger: restic file-copies `notebooks.db` while `-wal` sidecar has
  uncommitted or uncheckpointed frames. The `-wal` and `-shm` files are EITHER
  not in the manifest (missing from backup) OR are in the manifest but captured
  at an inconsistent point relative to `notebooks.db`.
- Symptom: after restore, SQLite opens `notebooks.db` to a consistent state
  that is BEHIND the last committed transaction; or if `-wal` is absent after
  restore, SQLite silently rolls back to the last checkpoint in `notebooks.db`.
  The user sees notebook metadata that is older than expected with no error.
- **Mitigation (REQUIRED):** Before backup, run
  `PRAGMA wal_checkpoint(TRUNCATE)` against `notebooks.db` to fold all
  committed WAL frames into the main database file and zero the WAL.
  After `TRUNCATE` checkpoint, `notebooks.db` is self-consistent without any
  sidecar. The backup manifest then needs only `notebooks.db`, NOT `-wal`/`-shm`.
  Alternatively: include `notebooks.db`, `notebooks.db-wal`, `notebooks.db-shm`
  in the manifest AND back them up atomically (not possible with file-level
  restic — prefer the checkpoint approach).
  Implement as: a Python one-liner in the backup wrapper that runs the checkpoint
  before `restic backup` fires.

**FM-3: Include-manifest drift — new notebook subdir scheme not covered**
- Trigger: a future milestone changes the notebook slug scheme or adds a new
  subdirectory under `var/arxmcp/` for notebook data; the manifest is not
  updated.
- Symptom: silent data loss — restic backs up the manifest, not the new path.
  No error. The only detection is a failed restore drill.
- Mitigation: the manifest should use `var/arxmcp/notebooks/` (the entire
  subtree, not individual slug dirs). Restic backs up the entire subtree
  recursively when given a directory path. Document this in the manifest comment.

**FM-4: Restore drill asserts existence only, not byte-equality**
- Trigger: restore completes but PDF file is silently truncated or corrupted;
  smoke check only verifies `os.path.exists`.
- Symptom: drill "passes" but restored PDF is unreadable.
- Mitigation: the pytest regression test must assert `sha256(original_pdf) ==
  sha256(restored_pdf)` explicitly. Do not rely on restic's own integrity check
  at restore time (restic does verify pack-level checksums on restore, but a
  test that asserts byte-equality is a positive safety signal for the test
  suite).

**FM-5: `forget` prunes the only snapshot containing a since-deleted notebook**
- Trigger: user deletes a notebook from the UI (which removes only the
  `notebooks.db` row, NOT the `var/arxmcp/notebooks/<slug>/` directory per the
  deletion contract). Later, the user asks to restore the deleted notebook.
  The 7-daily / 4-weekly / 12-monthly retention window may have already pruned
  the only snapshot that contained it.
- Mitigation: document in runbook that notebook deletion is metadata-only and
  on-disk assets survive until `tools/notebook_purge.py`. If on-disk purge has
  not run, the most-recent restic snapshot covers it. If purge has run AND
  retention window has passed, the data is gone. This is acceptable; document
  it.

**FM-6: RESTIC_REPOSITORY / RESTIC_PASSWORD_FILE unset in cron**
- Trigger: systemd environment does not inherit the shell env; `ops/restic-env.sh`
  is not sourced; backup wrapper exits with `ERROR: ${ENV_FILE} missing` or
  restic fails to authenticate.
- Symptom: backup fails silently if the wrapper's lock-check isn't watched;
  `backup-status.json` is stale from the previous night.
- Mitigation: the existing wrapper sources `ops/restic-env.sh` and checks for
  the file's existence (exits 1 if missing). The systemd `.service` unit must
  set `EnvironmentFile=` or equivalent. This is already documented in the
  E11_S05 service unit. Verify the new paths don't add new env dependencies.

---

## Restore-drill regression test design

The AC requires a pytest test asserting byte-for-byte round-trip. The project
has precedent for opt-in system-binary markers: `requires_latexmlc`,
`requires_pdflatex`, `requires_mineru` (all in `pyproject.toml`).

**Recommended split:**

1. **Unit test (no restic required, always runs):** Test the manifest generator
   function in isolation. Assert that given a config with `notebooks_dir` and
   `notebooks_db_path`, the generated manifest lines include the expected paths
   and exclude the expected cache paths (with inline comment). Uses a mock
   filesystem or `tmp_path`.

2. **Integration test (`@pytest.mark.requires_restic`, opt-in):** Full
   backup→wipe→restore cycle in a `tmp_path` restic repo (using
   `RESTIC_REPOSITORY=/tmp/...` and `RESTIC_PASSWORD=test`). Steps:
   a. Create a synthetic notebook: a small PDF in
      `tmp_path/var/arxmcp/notebooks/<slug>/pdfs/test.pdf` and a
      `notebooks.db` row.
   b. Run `PRAGMA wal_checkpoint(TRUNCATE)` on `notebooks.db`.
   c. `restic init`, `restic backup` with the manifest.
   d. Wipe the source tree.
   e. `restic restore latest --target tmp_path/restore/`.
   f. Assert `sha256(original_pdf) == sha256(restored_pdf)`.
   g. Open restored `notebooks.db` and assert the row is present with correct
      fields.

   Register the marker in `pyproject.toml` as:
   `"requires_restic: tests that invoke the real restic binary. Skipped by
   default; opt-in via pytest -m requires_restic AND ARXMCP_RUN_RESTIC_TESTS=1.
   Install: brew install restic / apt install restic."`

**WAL note for byte-equality assertion on `notebooks.db`:** After
`PRAGMA wal_checkpoint(TRUNCATE)`, the WAL is zeroed and `notebooks.db` is
self-consistent. Backup and restore of `notebooks.db` alone is then
byte-stable. The test must run the checkpoint BEFORE capturing the sha256 of
the original, or the sha256 will include unflushed WAL state that won't survive
the restore (if the manifest excludes `-wal`/`-shm`).

---

## Recommendation

**Implement the manifest as a Python function that prints lines to stdout,
piped via `--files-from-verbatim -`, and prepend a
`PRAGMA wal_checkpoint(TRUNCATE)` call before `restic backup`.**

Rationale: a Python manifest generator is testable (unit test covers inclusion/
exclusion logic), easily extended by future milestones, and avoids bash heredoc
fragility. The WAL checkpoint MUST come first to ensure `notebooks.db` is
self-consistent at backup time — this is the single most important correctness
constraint in this milestone. Use `--group-by host` in `forget` to avoid
snapshot-group fragmentation as the include-list evolves.

The AC's `--files-from-verbatim -` is the correct flag (verbatim, not glob).
The `5%` subset syntax is valid. The retention policy (`7/4/12`) is already
correct in the existing script; the new paths inherit it at no change.

No banned patterns are at risk in this milestone (no server code, no `assert`
for invariants, no `BaseHTTPMiddleware`, no `anthropic` SDK at runtime). The
`KMP_DUPLICATE_LIB_OK` line in `conftest.py` is not touched.

---

## Open questions

1. **WAL sidecar inclusion vs. checkpoint:** The brief does not specify whether
   the manifest should include `notebooks.db-wal` + `notebooks.db-shm`, or
   whether a pre-backup checkpoint is the chosen approach. The checkpoint
   approach is simpler and avoids sidecar inconsistency; recommend it. But the
   implementer must confirm that `notebooks_store.py`'s `asyncio.Lock` allows
   a synchronous checkpoint call from the backup wrapper (which runs outside
   the server process — so it can connect directly to `notebooks.db` and run
   `PRAGMA wal_checkpoint(TRUNCATE)` via `python3 -c "..."` in the shell
   wrapper). This is safe: WAL-mode allows multiple readers and a single
   checkpointer; an external process can checkpoint while the server is running.

2. **`--group-by host` vs `--group-by paths` for forget:** If the operator
   runs backups on multiple hosts pointing at the same repository, `--group-by
   host` is correct. If single-host (the typical case for this project), either
   works. Recommend `--group-by host` and document it.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `git commit` (feat) | `main` | Implementation commit: backup script + manifest generator + WAL checkpoint + restore drill extension |
| `git commit` (chore) | `main` | State finalization: `state.json` → complete |
| `git push` | `origin/main` | Land the milestone (per-event authorization required per CLAUDE.md §4.4) |

None of these require external infra mutation, ticket creation, or third-party
API calls. The restic repository is operator-configured locally; no cloud
credentials are created or mutated by this milestone's code.
