# Research Synthesis — notebook-ops-hardening-m1

**Milestone:** Notebook data + metadata enter the restic backup scope
**Mode:** standard (2× Sonnet, parallel)
**Sources:** research-brief-1.md (in-codebase grounding), research-brief-2.md
(restic docs + failure modes + restore-drill design)

---

## TL;DR — what to build

Extend the existing E14 restic backup (`ops/cron/arxmcp-backup.sh`) to cover
non-regenerable notebook data + metadata, with a mandatory pre-backup WAL
checkpoint, and extend the restore drill to prove a notebook round-trips.

Five coherent changes:
1. **WAL checkpoint before backup (CRITICAL).** Run `PRAGMA
   wal_checkpoint(TRUNCATE)` on `notebooks.db` immediately before `restic
   backup` so the main DB file is self-consistent without `-wal`/`-shm`
   sidecars.
2. **Manifest refactor + scope.** Switch the inline `BACKUP_PATHS` array to a
   `--files-from-verbatim -` manifest that adds `var/arxmcp/notebooks/` (whole
   subtree) + `var/arxmcp/cache/notebooks.db`; exclude the per-notebook
   regenerable query cache `*/cache/retrieval.db`.
3. **Retention hardening.** Existing `7/4/12` is already correct; add
   `--group-by host` to `forget` to avoid path-fragmentation as the manifest
   evolves.
4. **Drill `check --read-data-subset=5%`** added to `ops/restore_drill.sh`.
5. **Restore-drill verification + tests** — extend `restore_drill_check.py`
   with a notebook smoke check; add a unit test (always runs) + a
   `requires_restic` integration test (opt-in) that does a real
   backup→wipe→restore→sha256 byte-equality round-trip.

Plus doc updates: `.claude/notes/08-security-observability-ops.md` backup
section + `docs/ops/backup-restore.md` scope/schema.

No MCP tool / BP1 / tool-schema impact. No surprising external writes (only the
standard feat/chore commits + the per-event-authorized push).

---

## The existing machinery (verbatim, brief-1)

`ops/cron/arxmcp-backup.sh` lines 70–89 — current include-list is a positional
array, NOT `--files-from-verbatim`:
```bash
BACKUP_PATHS=(
    "${REPO_ROOT}/var/arxmcp/index/lancedb"
    "${REPO_ROOT}/var/arxmcp/index/kuzu"
    "${REPO_ROOT}/var/arxmcp/corpus/chunks"
)
restic backup --exclude "*.lock" --exclude "*.tmp" \
    --exclude "lancedb-staging-tmp" --json "${BACKUP_PATHS[@]}" | tail -n 1
```
Lines 133–136 — retention (already AC-correct): `restic forget --prune
--keep-daily 7 --keep-weekly 4 --keep-monthly 12`. The whole body runs inside
`exec flock -n "${LOCK_PATH}" bash -euo pipefail -c '...'` (line 53).

`ops/restore_drill_check.py` verifies LanceDB (`corpus-version.json` via rglob,
`open_chunks_table` non-empty) + Kùzu (best-effort). It does NOT check
`notebooks.db` or PDFs. `ops/restore_drill.sh` lines 43–67 call it with
`--restore-path`. No `restic check --read-data-subset` exists anywhere yet.

Existing tests to extend: `tests/test_backup_wrapper.py` (greps wrapper text for
retention flags etc.), `tests/test_restore_drill.py` (`TestBackupRestoreRunbook`
checks runbook text; `TestRunCheck` checks the smoke logic).

Notebook layout: `tools/_notebook_common.py:33`
`NOTEBOOKS_BASE = REPO_ROOT/var/arxmcp/notebooks`; per-slug subdirs: `lancedb/`,
`lancedb-prev-*/`, `lancedb-staging/`, `pdf-deferred/` + `pdfs/` (uploaded PDFs),
`ar5iv/` (re-fetchable), `cache/retrieval.db` (regenerable Tier-1 query cache),
`papers.txt` + `queries.json` (user-authored), `ops/` (logs).
`server/config.py:150` `notebooks_db_path = var/arxmcp/cache/notebooks.db`.

---

## RESOLVED: the cache/ exclusion conflict (both briefs flagged)

`.claude/notes/08-security-observability-ops.md` backup section says verbatim:
> "**Caches:** `/var/arxmcp/cache/`. NOT backed up; re-buildable on demand."

But the AC requires `var/arxmcp/cache/notebooks.db` (non-regenerable user
metadata) to be backed up. **Resolution (both briefs agree, do NOT silently
average):** back up the *specific file* `var/arxmcp/cache/notebooks.db` while the
rest of `cache/` (esp. `retrieval.db`) stays excluded. `--files-from-verbatim`
accepts a single-file path, so this is exact. The design note MUST be updated to
call out `notebooks.db` as the **explicit EXCEPTION** to the cache-exclusion
policy, distinguishing it from `retrieval.db` (still excluded). This is an AC
edit target, not a silent fix.

## RESOLVED: WAL sidecar correctness (CRITICAL — brief-2 FM-2)

`notebooks.db` runs in WAL mode (`journal_mode=WAL`, +`synchronous=FULL`,
`fullfsync=ON` from m2). On disk that means three files: `notebooks.db`,
`-wal`, `-shm`. A file-level restic snapshot of `notebooks.db` alone — or of all
three captured non-atomically — can restore a DB that is BEHIND the last
committed transaction (silent staleness, no error). **Mandatory mitigation:** run
`PRAGMA wal_checkpoint(TRUNCATE)` on `notebooks.db` immediately before `restic
backup`. After a TRUNCATE checkpoint the WAL is folded into the main file and
zeroed, so `notebooks.db` is self-consistent and the manifest needs only
`notebooks.db` (not the sidecars). Implement as a small `python3 -c` (or a tiny
helper) invoked from the backup wrapper BEFORE the restic call. Safe with the
server running: WAL permits many readers + one checkpointer, and the backup
wrapper is an external process opening its own connection. (brief-2 open Q1
confirms this is viable.)

## RESOLVED: manifest form (the one real divergence)

- **brief-1:** bash heredoc `restic backup --files-from-verbatim - <<'EOF' …
  EOF` inline in the wrapper. Open question: does stdin/heredoc work inside the
  `exec flock … bash -c '…'` subshell?
- **brief-2:** a Python manifest-generator function piped via
  `… | restic backup --files-from-verbatim -` (more unit-testable, avoids bash
  heredoc fragility).

**Orchestrator decision → bash heredoc (brief-1), with a fallback.** Rationale:
(a) keeps the manifest IN the wrapper, matching the existing
`test_backup_wrapper.py` text-grep test pattern; (b) avoids introducing a new
Python module + import surface for what is fundamentally a shell wrapper;
(c) testability is met by the text-grep unit test PLUS the `requires_restic`
integration test that exercises the real manifest end-to-end. A bash heredoc
uses its own fd, so it works even when the outer stdin is `/dev/null` (cron) —
but **VERIFY with a quick local smoke test during implementation** (brief-1 open
Q1). If the heredoc misbehaves inside `flock`, fall back to a `mktemp` manifest
file + `--files-from-verbatim "$MANIFEST"` (NOT a Python module).

## RESOLVED: include the per-notebook lancedb/ subtree

The AC says "regenerable caches stay excluded." Both briefs converge: that
clause means the per-notebook `cache/retrieval.db` (query cache), NOT the
embedding store. **Include the whole `var/arxmcp/notebooks/` subtree** (brief-1):
restic dedup makes it cheap; `lancedb-prev-*/` are the m2 rollback targets; and
re-embedding a textbook notebook is expensive (MinerU + LaTeXML + BGE-M3), not
"cheap to regenerate." Exclude only `*/cache/retrieval.db`. Record this
interpretation in a script comment so a future reader doesn't "tidy up" the
lancedb dirs out of scope.

---

## Other settled decisions

- **`--files-from-verbatim` semantics (brief-2):** reads each line literally (no
  glob, no whitespace strip, does not skip `#` lines; empty lines ignored).
  Include-only — exclusions stay as separate `--exclude` flags. `-` = stdin.
- **`forget --group-by host` (brief-2):** default group-by is `host,paths`;
  changing the include-list creates a NEW paths-group, so old/new snapshots get
  separate 7/4/12 windows (safe but surprising). `--group-by host` keeps one
  unified window as the manifest evolves. Adopt + document.
- **`check --read-data-subset=5%` (brief-2):** valid syntax (restic ≥0.16),
  verifies pack-file integrity (not structural index). Add to
  `ops/restore_drill.sh` as a step before restore (brief-1 Option B). An
  unsubsetted `restic check` can stay the daily structural health check.
- **restic is NOT installed here** (both briefs) — the integration test must be
  marked opt-in; the wrapper already exits with an install message if absent.

## Restore-drill verification + test plan

- Extend `ops/restore_drill_check.py`: add `smoke_check_notebooks(restore_path)`
  using **rglob-based** discovery (restic restores preserve absolute source
  paths under `--target`; hardcoding fails — F1 closure from E11_S05). Assert
  `notebooks.db` is found + opens + `PRAGMA integrity_check` ok; discover ≥1 PDF
  under a `pdf-deferred/` or `pdfs/` dir. Add `notebooks_db_found: bool` +
  `notebook_pdf_count: int` to `write_pass_sentinel`. Use `if … raise`, NOT
  `assert` (CLAUDE.md §4.7).
- **Unit test (always runs)** in `tests/test_restore_drill.py`: seed a synthetic
  `notebooks.db` via `NotebooksStore.open()` + a synthetic PDF under a tmp
  restore path, call `smoke_check_notebooks(tmp_path)`, assert both found. No
  live restic.
- **Unit test (always runs)** in `tests/test_backup_wrapper.py`: grep the
  wrapper for the new manifest paths, the `*/cache/retrieval.db` exclude, the
  `wal_checkpoint(TRUNCATE)` step, `--files-from-verbatim`, and `--group-by host`.
- **Integration test (`@pytest.mark.requires_restic`, opt-in)** — the faithful
  realization of the AC's "backup→wipe→restore … byte-for-byte": real
  `restic init`→`backup`→wipe→`restore latest`→assert
  `sha256(orig_pdf)==sha256(restored_pdf)` AND the `notebooks.db` row recovers.
  Run `wal_checkpoint(TRUNCATE)` BEFORE sha256 capture. Register the marker in
  `pyproject.toml`: `requires_restic` (opt-in via `-m requires_restic` AND
  `ARXMCP_RUN_RESTIC_TESTS=1`; install `brew install restic`).

## Documented residual risks (runbook prose, NOT code)

- **FM-1 (brief-2):** LanceDB mid-write torn snapshot — mitigated by the 90-min
  gap between ingest close (~04:05) and backup (~04:10); document.
- **FM-5 (brief-2):** `forget` can prune the only snapshot of a since-deleted
  notebook (deletion is metadata-only until `notebook_purge`); document.

---

## Acceptance criteria → verifiable artifacts

| AC | Artifact |
|---|---|
| `--files-from-verbatim -` manifest covers `notebooks/` + `cache/notebooks.db`; regenerable caches excluded w/ comment | wrapper refactor + `*/cache/retrieval.db` exclude + comment; text-grep test |
| Retention `7/4/12`; drill runs `check --read-data-subset=5%` | retention already correct (+`--group-by host`); `check` added to restore_drill.sh; tests |
| G/W/T: notebook (PDF + notebooks.db row) recovers byte-for-byte via backup→wipe→restore | `requires_restic` integration test (sha256 + row) + smoke-check unit test |
| `08-security-...ops.md` backup section + ops note list notebook paths | design-note edit (notebooks.db EXCEPTION call-out) + `docs/ops/backup-restore.md` |

## Deviations from the brief (to record)

1. **WAL checkpoint added** beyond the literal AC text — required for the
   byte-for-byte guarantee to hold for a WAL-mode DB (brief-2 FM-2). Faithful to
   AC intent.
2. **`--group-by host`** added to `forget` — not in the AC, but prevents a
   retention-window fragmentation foot-gun when the manifest changes (brief-2).
3. **lancedb/ included** (not excluded) — "regenerable caches" interpreted as
   `retrieval.db`, not the embedding store (both briefs). Recorded in a comment.

## Open questions (carried to implementation)

1. **flock-subshell stdin/heredoc** — verify the `--files-from-verbatim -`
   heredoc works inside `exec flock … bash -c '…'` with outer stdin `/dev/null`.
   Smoke-test locally; fallback = `mktemp` manifest file. (brief-1 Q1)
2. None blocking. restic-not-installed → integration test is opt-in by design.

## External writes the implementation will require

**None surprising.** Standard milestone-pipeline writes only: feat commit
(local), chore commit (local), and `git push origin main` (per-event authorized
per CLAUDE.md §4.4 — gated in Phase 4). No infra mutation, no ticket, no
third-party API, no cloud credential. The restic repo is operator-configured
locally; this milestone's code creates/mutates no cloud resource.

## Orchestrator synthesis note

Briefs agreed on scope, the cache-exclusion conflict resolution, retention
correctness, restic-not-installed, and the local-first contract. The one real
divergence — manifest form (bash heredoc vs Python generator) — was resolved in
favor of brief-1's in-wrapper heredoc (matches the existing test pattern, no new
module) with a `mktemp`-file fallback if the flock-stdin smoke test fails.
brief-2's CRITICAL WAL-checkpoint finding (absent from brief-1) is adopted as the
single most important correctness constraint. brief-2's `--group-by host` and the
opt-in `requires_restic` integration test are adopted; brief-1's rglob-based
smoke check + include-whole-subtree recommendation are adopted.
