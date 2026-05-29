# Research Brief — notebook-ops-hardening-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T13:00:00Z

## In-codebase context

### Current backup machinery (verbatim load-bearing quotes)

**`ops/cron/arxmcp-backup.sh` lines 70–89** — the include-list is an inline
POSIX array of three explicit paths passed positionally to `restic backup`:

```bash
BACKUP_PATHS=(
    "${REPO_ROOT}/var/arxmcp/index/lancedb"
    "${REPO_ROOT}/var/arxmcp/index/kuzu"
    "${REPO_ROOT}/var/arxmcp/corpus/chunks"
)

restic backup \
    --exclude "*.lock" \
    --exclude "*.tmp" \
    --exclude "lancedb-staging-tmp" \
    --json \
    "${BACKUP_PATHS[@]}" \
    | tail -n 1
```

`var/arxmcp/notebooks/` and `var/arxmcp/cache/notebooks.db` are **NOT** in the
include-list. The existing `--exclude` patterns target only LanceDB transient
files; there is no comment distinguishing regenerable vs non-regenerable data.

**Lines 133–136** — retention invocation:
```bash
restic forget --prune \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 12
```
Retention flags are already correct per the milestone AC. They live in the
backup wrapper, not in a separate config file.

**`test_backup_wrapper.py` line 113** asserts these exact retention flags:
```python
def test_wrapper_retention_policy(self):
    assert "--keep-daily 7" in text
    assert "--keep-weekly 4" in text
    assert "--keep-monthly 12" in text
```

**`ops/cron/arxmcp-backup.sh` line 53** — the `restic backup` call is inside
`exec flock -n "${LOCK_PATH}" bash -euo pipefail -c '...'`. The include-paths
are expanded into the single-quote heredoc using bash variable expansion. A
`--files-from-verbatim -` (stdin heredoc) refactor is valid but not strictly
required; the existing array form works. The AC says "a `--files-from-verbatim -`
manifest" — **this refactor is required by the AC**.

**No `restic check --read-data-subset` invocation exists** anywhere in
`ops/cron/arxmcp-backup.sh` or `ops/restore_drill.sh`. This is a new addition.

**`ops/restore_drill_check.py`** — the restore drill currently checks:
1. LanceDB `corpus-version.json` marker found via `rglob` (path-prefix-agnostic).
2. `open_chunks_table` returns a non-empty table.
3. Kùzu graph opens (optional).

It does NOT check for `notebooks.db` presence or PDF byte-for-byte recovery.
The `write_pass_sentinel` schema does not include notebook fields. This module
must be extended.

**`ops/restore_drill.sh` lines 43–67** — invokes
`python -m ops.restore_drill_check --restore-path ... --snapshot-id ... --flag-path ...`.
The shell wrapper only needs the `--restore-path` to contain the notebook
paths; the check module is where the new assertion logic goes.

**`docs/ops/backup-restore.md` "Scope" section (lines 17–26)** lists backed-up
items: LanceDB indices, Kùzu graph, corpus/chunks. The "Scope" bullet list and
the `paths_backed_up` array in the `backup-status.json` state-file schema
(lines 271–281) BOTH need updating to list the notebook paths. The test
`TestBackupRestoreRunbook.test_documents_retention_policy` checks the runbook
text — any new coverage test must also pass here.

### Notebook storage layout (from source + on-disk inspection)

**`tools/_notebook_common.py` line 33:**
```python
NOTEBOOKS_BASE: Path = REPO_ROOT / "var" / "arxmcp" / "notebooks"
```

**Per-notebook subdirs confirmed on disk (shimura-varieties example):**
- `lancedb/` — active per-notebook LanceDB (chunks.lance + corpus-version.json)
- `lancedb-prev-<timestamp>/` — prior LanceDB snapshots after cutover
- `lancedb-staging/` — in-flight re-embed staging (if cutover not yet run)
- `pdf-deferred/` — uploaded PDFs pending ingest (non-regenerable; confirmed two PDFs present)
- `ar5iv/` — fetched arXiv HTML (re-fetchable from ar5iv.org)
- `ops/` — daemon logs, smoke logs (regenerable)
- `papers.txt`, `queries.json` — user-authored config (non-regenerable)

**`server/config.py` line 150:**
```python
notebooks_db_path: Path = Path("var/arxmcp/cache/notebooks.db")
```

**`server/config.py` line 439 (per-notebook retrieval cache):**
```
var/arxmcp/notebooks/<slug>/cache/retrieval.db
```
This per-notebook Tier-1 retrieval cache is regenerable (query cache, not
user data). It must be **excluded** from the backup with a comment.

**Non-regenerable items:**
- `var/arxmcp/notebooks/<slug>/pdf-deferred/*.pdf` and `pdfs/*.pdf` — user-uploaded PDFs; these are the ONLY copy unless the user re-uploads
- `var/arxmcp/notebooks/<slug>/papers.txt` — user-authored paper ID list
- `var/arxmcp/notebooks/<slug>/queries.json` — user-authored eval queries
- `var/arxmcp/cache/notebooks.db` — notebook metadata (slug, display_name, lancedb_path, created_at, paper membership) per `server/notebooks_store.py`

**Regenerable items (must be excluded with comment):**
- `var/arxmcp/notebooks/<slug>/lancedb/` — per-notebook LanceDB embeddings; CAN be rebuilt from uploaded PDFs via `notebook_textbook_ingest` or from fetched ar5iv HTML via `notebook_ingest`
- `var/arxmcp/notebooks/<slug>/lancedb-prev-*/` — prior LanceDB snapshots; regenerable (though expensive)
- `var/arxmcp/notebooks/<slug>/cache/retrieval.db` — Tier-1 query cache; fully regenerable
- `var/arxmcp/notebooks/<slug>/ops/` — daemon logs; not user data
- `var/arxmcp/cache/retrieval.db` — global retrieval cache; already excluded (was never in the include-list)

**HOWEVER — recommendation complexity:** The brief says "regenerable caches stay excluded." Per-notebook LanceDB IS regenerable IF the source PDFs are present. But `lancedb-prev-*/` versions are the m1/m2 durability rollback targets. For a minimal m1 scope, the cleanest approach is: **include ALL of `var/arxmcp/notebooks/`** (entire tree, deduplication via restic makes this cheap) and rely on restic's `--exclude "*.lock" --exclude "*.tmp"` to skip transient files. This avoids the complexity of sub-path exclusions and ensures rollback targets survive. The AC says "regenerable caches stay excluded" — the per-notebook `cache/retrieval.db` must be explicitly excluded.

**`08-security-observability-ops.md` lines 233–250 (verbatim backup section):**
```
## Backup and restore

What to back up:

- **Corpus raw + parsed:** `/var/arxmcp/corpus/`. Idempotent and re-fetchable
  in principle, but re-fetching takes weeks under arxiv.org rate limits.
- **LanceDB indices:** `/var/arxmcp/index/lancedb/`. Re-buildable from corpus
  + chunker + embedder, but takes ~1–2 days of GPU time.
- **Kùzu graph:** `/var/arxmcp/index/kuzu/`. Re-buildable from OpenAlex +
  INSPIRE, takes hours.
- **Caches:** `/var/arxmcp/cache/`. NOT backed up; re-buildable on demand.

Strategy: nightly snapshot via `restic`...
```

**The AC requires updating this section** to add: notebooks (`var/arxmcp/notebooks/`) and notebook metadata (`var/arxmcp/cache/notebooks.db`).

**CONFLICT FLAG: The AC says `var/arxmcp/cache/notebooks.db` must be included,
but the design note says `/var/arxmcp/cache/` is "NOT backed up." This is a
direct conflict. Resolution: the design note is the GENERAL policy
(regenerable caches); `notebooks.db` is user-authored state that happens to
live in `cache/`. The note must be updated to call out this exception. Do NOT
silently resolve this — the update to `08-security-observability-ops.md` must
explicitly note that `notebooks.db` is the exception to the cache-exclusion
policy, distinguishing it from `retrieval.db` which remains excluded.**

### `--files-from-verbatim -` refactor

The AC explicitly requires this form. Current code uses `"${BACKUP_PATHS[@]}"`.
The refactor requires the include-list to be piped via stdin heredoc:

```bash
restic backup \
    --files-from-verbatim - \
    --exclude "*.lock" \
    --exclude "*.tmp" \
    --exclude "*/cache/retrieval.db" \
    --exclude "lancedb-staging-tmp" \
    --json \
    <<'INCLUDE_EOF'
${REPO_ROOT}/var/arxmcp/index/lancedb
${REPO_ROOT}/var/arxmcp/index/kuzu
${REPO_ROOT}/var/arxmcp/corpus/chunks
${REPO_ROOT}/var/arxmcp/notebooks
${REPO_ROOT}/var/arxmcp/cache/notebooks.db
INCLUDE_EOF
```

Note: `--files-from-verbatim -` takes lines from stdin verbatim (no glob
expansion). The existing `exec flock ... bash -c '...'` wrapper must be
checked for stdin fd availability — `exec flock` replaces the shell process
and the inner `bash -c '...'` may not inherit stdin from the outer process.
**This is an open question (see below).**

### `restic check --read-data-subset`

AC requires the quarterly drill to run `restic check --read-data-subset=5%`.
The current quarterly drill script (`ops/cron/arxmcp-quarterly-drill.sh`) calls
`tools/quarterly_drill_reminder.sh` — it writes a REMINDER FILE, not a live
`restic check`. The milestone must decide where the check goes:
- Option A: add to the quarterly cron as a separate wrapper step after the reminder
- Option B: add to `ops/restore_drill.sh` (which IS the drill, not just the reminder)
- **Recommendation: Option B** — add `restic check --read-data-subset=5%` to
  `ops/restore_drill.sh` BEFORE the restore + smoke check steps. The drill is
  the right home; the quarterly reminder just schedules when to run the drill.

### Existing test coverage to extend

- `tests/test_backup_wrapper.py::TestBackupShellWrapper` — greps the wrapper
  text for retention flags, lock, etc. Must be updated to assert the new
  include-list form + the notebook path + the `*/cache/retrieval.db` exclude.
- `tests/test_restore_drill.py::TestBackupRestoreRunbook` — checks runbook text
  for retention policy + drill mentions. Must be updated to assert notebook
  coverage.
- `tests/test_restore_drill.py::TestRunCheck` — must be extended with a
  `test_notebook_round_trip` that seeds a synthetic `notebooks.db` + a PDF
  file, runs the smoke check against a restore path, and asserts byte-for-byte
  PDF recovery. No live `restic` needed — the check module operates on a path.

## Prior decisions and lessons

**Recent git log (last 20 commits):**
```
9cd28af chore(notes): finalize corpus-integrity-observability-m2 state -> complete
a8c7414 rect(server): close 5 of 6 from corpus-integrity-observability-m2 critique
7604e60 chore(notes): finalize notebook-ops-hardening-m2 state -> complete
f379355 rect(server): close notebook-ops-hardening-m2 critique (1M 1L; 1L deferred)
513aeb6 feat(server): startup corpus-count reconciliation + size gauges
6e18e96 feat(server): durable notebooks.db + LanceDB format pin (notebook-ops-hardening-m2)
```

notebook-ops-hardening-m2 is **already complete** (shipped 2026-05-28).
`notebooks.db` now opens with `synchronous=FULL` + `fullfsync=ON` per m2.
The present milestone (m1) is the restic-scope extension.

**`ops/restore_drill_check.py`** uses `rglob("corpus-version.json")` to locate
LanceDB under the restore path, which is path-prefix-agnostic (F1 closure from
E11_S05 adversary). The new notebook smoke check must use the same
rglob-based discovery rather than hardcoded paths, for the same reason
(restic restores preserve absolute source paths under `--target`).

**CLAUDE.md §1 doc-placement rule:** operator-facing backup docs live under
`docs/ops/`. The existing `docs/ops/backup-restore.md` is the correct file to
update. No new Markdown file should be created at the repo root or under
`server/`, `ops/`, etc.

**CLAUDE.md §4.7 banned patterns:** `assert` is banned; use `if ... raise
RuntimeError(...)`. The `restore_drill_check.py` already follows this pattern;
new smoke-check code for notebooks must do the same.

**macOS segfault guard (`tests/conftest.py`):** not touched by this milestone.

**Tool-schema re-pinning:** this milestone does NOT add or modify any MCP tool.
`EXPECTED_TOOL_SCHEMA_SHA256` must NOT be changed. The AC confirms this.

## External sources

The milestone brief says "formalize the retention policy + a `check --read-data-subset`
rotation." The existing retention flags in `arxmcp-backup.sh` (lines 133–136)
already match the AC (`--keep-daily 7 --keep-weekly 4 --keep-monthly 12`).
No spec drift here — the retention is already correct; the AC is asking for
it to be documented/confirmed, not changed.

`restic check --read-data-subset=5%` is a standard restic flag (restic ≥ 0.9.6).
It validates 5% of pack data bytes (not just the index). This is the
"verify pack data, not just the index" contract from CAND-18. No external
version constraint; the existing `brew install restic` (`≥ 0.16` per the
runbook) supports it.

No MCP spec or Anthropic prompt-caching docs are relevant to this milestone.

## Recommendation

**Implement the backup extension as follows:**

1. **Refactor `ops/cron/arxmcp-backup.sh`**: Convert the `BACKUP_PATHS` array
   to a `--files-from-verbatim -` stdin heredoc inside the `flock` subshell.
   Add `${REPO_ROOT}/var/arxmcp/notebooks` and
   `${REPO_ROOT}/var/arxmcp/cache/notebooks.db` to the include list. Add
   `--exclude "*/cache/retrieval.db"` to exclude per-notebook query caches.
   Add a comment block above the exclude distinguishing non-regenerable (PDFs,
   `notebooks.db`, `papers.txt`, `queries.json`, per-notebook `lancedb/`) from
   regenerable (retrieval caches). Update the `paths_backed_up` array in
   both `TMP_STATUS` JSON writes (lines 112–127 and 156–173) to include the
   two new paths. **Verify stdin fd behavior inside the `flock` subshell before
   landing** (see open questions).

2. **Extend `ops/restore_drill.sh`**: Add `restic check --read-data-subset=5%`
   as the first step (before the restore), with its exit code captured and
   non-zero treated as a drill failure.

3. **Extend `ops/restore_drill_check.py`**: Add `smoke_check_notebooks` function
   using `rglob`-based discovery of `notebooks.db` under `restore_path`. Assert
   the file exists and is a valid SQLite (try `sqlite3.connect` + `PRAGMA
   integrity_check`). Add optional discovery of at least one PDF under a
   `pdf-deferred/` or `pdfs/` dir. Update `write_pass_sentinel` to include
   `notebooks_db_found: bool` and `notebook_pdf_count: int` fields.

4. **Add a pytest test** `test_notebook_round_trip` in
   `tests/test_restore_drill.py` that seeds a synthetic `notebooks.db` (using
   `NotebooksStore.open()`) + a synthetic PDF, then calls
   `smoke_check_notebooks(tmp_path)` and asserts both are found.

5. **Update `08-security-observability-ops.md`** backup section to add:
   - `var/arxmcp/notebooks/` — per-notebook LanceDB + uploaded PDFs (non-regenerable)
   - `var/arxmcp/cache/notebooks.db` — notebook metadata (non-regenerable; EXCEPTION to the `cache/` exclusion policy — `retrieval.db` stays excluded)

6. **Update `docs/ops/backup-restore.md`** Scope section and
   `backup-status.json` schema example to list the notebook paths.

7. **Update tests** in `test_backup_wrapper.py` to assert the new include-list
   form and the `*/cache/retrieval.db` exclude.

The per-notebook `lancedb/` directory should be **included** (not excluded) in
the backup tree despite being regenerable, because: (a) restic deduplication
makes the marginal cost low; (b) `lancedb-prev-*/` rollback targets need
backup coverage; (c) re-embedding a textbook notebook requires re-running
MinerU + LaTeXML + BGE-M3 (expensive, not truly "cheap" to regenerate). The AC
says "regenerable caches stay excluded" — this applies to `retrieval.db`, not
to the LanceDB embedding store.

## Open questions

1. **stdin fd availability inside `flock` subshell**: The current
   `ops/cron/arxmcp-backup.sh` wraps the entire body in
   `exec flock -n "${LOCK_PATH}" bash -euo pipefail -c '...'`. The
   `--files-from-verbatim -` form reads from stdin. When called via cron or
   systemd, stdin is `/dev/null`. The heredoc `<<'INCLUDE_EOF'` redirects
   stdin for the `restic backup` subcommand itself — this should work even
   with the outer stdin closed, because bash heredocs use a pipe, not the
   inherited stdin fd. **The implementer should verify this with a quick
   `bash -c 'cat <<EOF\nfoo\nEOF' | restic backup --files-from-verbatim -`
   smoke test locally before landing.**

2. **Include `lancedb/` or not?** Recommendation above says include; the AC
   says "regenerable caches stay excluded." If the reviewer interprets
   "regenerable" broadly to include per-notebook LanceDB, then `lancedb/` and
   `lancedb-prev-*/` should be excluded. The implementer should decide
   explicitly and record the reasoning in a comment in the backup script.

No other open questions — implementation can proceed on the above recommendation
for all other items.

## External writes the implementation will require

None — this milestone is purely local. All changes are:
- `ops/cron/arxmcp-backup.sh` (shell script)
- `ops/restore_drill.sh` (shell script)
- `ops/restore_drill_check.py` (Python module)
- `tests/test_restore_drill.py` (tests)
- `tests/test_backup_wrapper.py` (tests)
- `.claude/notes/08-security-observability-ops.md` (design note)
- `docs/ops/backup-restore.md` (operator runbook)

No `git push`, no `gh` calls, no infra mutations. The restore-drill regression
test (`test_notebook_round_trip`) uses synthetic `tmp_path` fixtures — no
live `restic` binary required, no external network access. The `restic check`
addition to `ops/restore_drill.sh` requires a live restic binary, but this is
operator-invoked (not part of `make test`).
