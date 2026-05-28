# Research Brief — notebook-cutover-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T03:45:00Z

## In-codebase context

### E11_S05 precedent — `ops/cutover.py`

The shared-corpus cutover (`ops/cutover.py::perform_directory_swap`) is the canonical
precedent. Its two-rename sequence:

```python
os.rename(active_path, rollback_path)   # step 1
try:
    os.rename(staging_path, active_path)  # step 2
except OSError as exc:
    os.rename(rollback_path, active_path)  # best-effort restore on failure
    raise CutoverError(...)
```

This is **NOT a single atomic operation**. Each `os.rename` is individually atomic on
POSIX within a single filesystem (POSIX guarantees rename(2) is atomic), but the two
together leave a window between step 1 and step 2 where `lancedb` does not exist under
its canonical name. If the process dies in that window, neither path resolves correctly.

E11_S05 also includes a pre-flight cross-filesystem check: `os.stat(...).st_dev` on all
three paths; `EXDEV` would otherwise silently fail. Notebook cutover must replicate this.

The E11_S05 rollback path (`perform_rollback`) uses a timestamped `lancedb-failed-cutover-<ts>` dir for the failed-promoted copy, then restores rollback_path → active_path.

### Notebook server-read path confirmation

`server/routes/notebooks.py:273`:
```python
lancedb_path = str(nb_dir / "lancedb")
```

This is hardcoded at notebook creation time, stored as a STRING in SQLite
(`server/notebooks_store.py` `lancedb_path TEXT NOT NULL`). The server reads
`<slug>/lancedb` directly — an `os.rename` to/from that directory name DOES change
what's served. No alias indirection.

### BM25 index — GLOBAL, NOT per-notebook (critical finding)

`ingest/bm25_indexer.py:104`:
```python
BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / BM25_DIR_NAME
```

`_bm25_version_dir(N)` returns `BM25_INDEX_ROOT / f"v{N}"`. The BM25 artifact is stored
at a **global** path keyed ONLY by `corpus_version` integer. Notebook-level isolation
does NOT exist in the current BM25 layout.

`server/retrieval/bm25.py::BM25Phase._sync_startup`:
```python
version_dir = _bm25_version_dir(corpus_version)
...
if not (pkl_path.is_file() and ids_path.is_file()):
    build_bm25_index(lancedb_path, corpus_version=corpus_version)
```

`BM25Phase.startup` auto-builds if missing, but ONLY if called. The server calls this
exactly once at process startup for the shared corpus. **There is no server-side
auto-rebuild path for per-notebook BM25 after a cutover.** Notebook queries go through
the shared corpus BM25 phase at the server level — per-notebook BM25 is ONLY used when
a `BM25Phase` is constructed pointing at the notebook's lancedb path.

Live confirmed: `var/arxmcp/index/bm25/` contains `v5, v49, v81, v101, v157, v369` —
no `v645` or `v143` — the staging versions have NO BM25 index yet. The cutover tool
MUST call `build_bm25_index(notebook_lancedb_path, corpus_version=new_version)` BEFORE
or immediately AFTER the rename so queries don't fail.

### Disk footprint (live measurement)

| Dataset | Active `lancedb` | Staging `lancedb-staging` |
|---|---|---|
| bridgeland-stability | 505 MB | 923 MB |
| shimura-varieties | 57 MB | 143 MB |

N=2 `lancedb-prev-*` retention per notebook: bridgeland would cost 2 × 505 MB = ~1 GB;
across both notebooks ~1.1 GB per backup tier. N=2 is reasonable at this scale.

### Design note constraints

**`05-storage-and-indexing.md`** states: "Keep N=7 prior LanceDB dataset versions for
rollback; a compaction job GCs older versions after readers have migrated (see E11)."
This applies to LANCEDB INTERNAL MVCC VERSIONS (dataset-level, managed by LanceDB),
NOT to the directory-level `lancedb-prev-*` backup scheme. No contradiction with N=2
directory-level backups.

**`05-storage-and-indexing.md`** also states: "Manual symlink swaps (`current -> v0007`)
are **explicitly prohibited** under the new design." The `os.rename` approach does NOT
use symlinks — compliant.

**`08-security-observability-ops.md` Threat 1**: "Tool arguments come from LLM output.
An LLM that has been prompt-injected … could pass `paper_id="../../../etc/passwd"`."
The slug-to-dir path flows through `--notebook=<slug>` CLI arg into `validate_slug` +
`notebook_dir` from `tools/_notebook_common.py`. These must be reused — do NOT
re-implement. `validate_slug` enforces `^[a-z][a-z0-9-]{2,30}$` (slug regex).
`notebook_dir` adds belt-and-braces `resolve()` + containment check + symlink rejection.

## Prior decisions and lessons

From git log: the most recent relevant commits are:
- `be1a3ff feat(ingest): fetch raw .tex on ar5iv path; back-fill preambles (notebook-preamble-recovery-m1)`
- `461d2a7 chore(notes): append milestone-researcher memory for E13_S03b run`

The E11_S05 `ops/cutover.py` was designed for the SHARED corpus (one fixed path),
with 4 heavyweight gates (seed eval, watchdog, ingest-complete, restore-drill) that
are explicitly inappropriate for per-notebook datasets (brief design decision §4).
The notebook cutover is a lighter-weight sibling. The cross-filesystem check
(`st_dev` comparison) and the rollback-path-exists pre-check from E11_S05 ARE worth
replicating — they prevented adversary F8 in the E11_S05 critique.

From MEMORY.md (pre-loaded): E13_S05 / E13_S03 / E13_S09 milestones confirm that the
notebook slug → dir path traversal surface is high-priority. Reuse `_notebook_common.py`.

**Banned patterns to watch:**
- `assert` for invariants — use `if … raise NotebookError(…)` (already the pattern in `_notebook_common.py`)
- `BaseHTTPMiddleware` — not relevant here (CLI tool)
- No MCP surface change → `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED (X-1 explicit)

## External sources

### POSIX `rename(2)` atomicity — precisely scoped

On Linux/macOS, a single `rename(2)` syscall is atomic: it either completes the directory
entry swap or fails; directory entries are never partially updated. However:

1. `os.rename` on a non-empty directory target raises `OSError: EISDIR` / `ENOTEMPTY`
   on Linux. macOS allows renaming over a non-empty directory. For safety, the cutover
   must ensure the destination name is FREE before each rename — which the pre-flight
   check (`if rollback_path.exists(): raise`) already does.
2. `rename` across filesystem boundaries raises `EXDEV` — must check `st_dev` equality
   (already done in E11_S05; replicate for notebook cutover).
3. **The two-rename sequence has a window**: after rename 1 (`lancedb → lancedb-prev-<ts>`)
   and before rename 2 (`lancedb-staging → lancedb`), the canonical `lancedb` path does
   not exist. A server query in this window would fail with `FileNotFoundError` when
   LanceDB tries to open the DB. The window is microseconds under normal conditions but
   can extend indefinitely if the process dies between the two calls (crash, SIGKILL).

### LanceDB on-disk layout — safe to `mv`

LanceDB stores its dataset as a directory of versioned parquet files + Lance manifest
files. The internal manifest references are relative paths within the DB root directory.
Moving the entire directory with `os.rename` (same filesystem) preserves all internal
relative paths. The `corpus-version.json` sits at the LanceDB root (e.g.,
`lancedb/corpus-version.json`) and moves with it.

**Moving `lancedb/` wholesale via `os.rename` is safe** — no internal paths break.

Confirmed by `ingest/store.py` (the writer): it connects with `lancedb.connect(str(path))`
using the directory path. As long as the renamed directory is consistent (all files
present), reconnecting after rename works.

### LanceDB version: `lancedb>=0.6` (from `pyproject.toml:60`). No breaking changes
to the directory layout for move-safety in this version range. No external URL needed.

## Recommendation

**Use `tools/notebook_cutover.py` as a standalone CLI** (not as a `--cutover` flag on
`re_embed_all`). Mirror the E11_S05 structure: `perform_directory_swap` +
`perform_rollback` + per-notebook version gates. Do NOT replicate the 4 heavyweight
E11_S05 criteria (seed eval / watchdog / re-embed state / restore drill).

**BM25 consistency (AC7) — build before the rename sequence:**
Call `build_bm25_index(staging_lancedb_path, corpus_version=staging_version)` as an
explicit pre-cutover step, BEFORE the two renames. This is the safest sequence:
1. Build BM25 for staging version (idempotent-skip if already exists).
2. `os.rename(active_path, rollback_path)` — active moves to backup.
3. `os.rename(staging_path, active_path)` — staging becomes active.

If step 1 fails, no directory mutation has occurred — clean refusal. If the process dies
between steps 2 and 3, the BM25 artifact for the new version already exists (harmless)
and the operator can recover by running step 3 manually.

**Rollback**: restore the most recent `lancedb-prev-*` dir. AC2 requires moving current
`lancedb` back to `lancedb-staging`. After rollback, the BM25 artifact at the old
version still exists (idempotent, no cleanup needed).

**Backup retention**: N=2 `lancedb-prev-*` dirs per notebook. Scan for `lancedb-prev-*`
glob after cutover, sort by name (timestamps are sortable ISO strings), delete all
except the two most recent. This prevents OS errors on directory-is-not-empty by using
`shutil.rmtree` (not `os.rmdir`).

## Open questions

No open questions — implementation can proceed on the above recommendation. The BM25
question is resolved: build before rename. The server-read path is confirmed as
`<slug>/lancedb`. The path-traversal surface is covered by existing `_notebook_common.py`
helpers.

## Six failure modes (plus one additional)

**FM-1: Crash between the two renames**
- Trigger: `SIGKILL` or power loss after `lancedb → lancedb-prev-<ts>` but before
  `lancedb-staging → lancedb`.
- Symptom: `lancedb/` does not exist under the notebook dir. Server startup fails:
  `read_corpus_version` returns None → `Resources.startup` raises → `/readyz` never 200.
  BM25Phase auto-build would also fail (`FileNotFoundError` on `lancedb_path`).
- Mitigation: The existing E11_S05 recovery protocol covers this case. Operator runs:
  `os.rename(lancedb-prev-<ts>, lancedb)` to restore or
  `os.rename(lancedb-staging, lancedb)` to promote. The cutover tool MUST print both
  options to stdout BEFORE the swap sequence begins ("if interrupted, run X to restore").
  The step-2 `OSError` handler in `perform_directory_swap` (from E11_S05) handles the
  common non-crash failure; the crash case needs operator runbook documentation.

**FM-2: Server holds open LanceDB handle during the swap**
- Trigger: `make notebook-cutover` while server is running.
- Symptom: The server's open file descriptor follows the **inode** of the old LanceDB
  directory, not the path name. On Linux/macOS, once a directory is opened (lancedb
  connects via path at startup), the internal fd remains valid even after the path
  name changes via `os.rename`. The server's in-memory `chunks_table` keeps working
  for the OLD dataset version until the server restarts. New queries resolve the new
  path only after a server restart.
- Risk: The server won't error — it will silently continue serving the old embeddings
  from its pinned MVCC version. The cutover "works" from the tool's perspective but the
  server won't pick it up until restarted.
- Mitigation: The brief's design (gate 3) warns if `/healthz` returns 200. The cutover
  tool should print a bold "RESTART SERVER to activate new corpus" message post-swap.
  The Makefile target help text should document this.

**FM-3: Disk full during backup prune (N=2 retention)**
- Trigger: `shutil.rmtree(old_backup)` fails due to OSError (e.g., disk full prevented
  creating the new backup's own files, but the rmtree then also fails on a different
  reason).
- Symptom: Old `lancedb-prev-*` dirs accumulate; disk fills further. Worst case: the
  new `lancedb-prev-<ts>` directory couldn't even be written (rename would have already
  failed at step 1 in this case — `os.rename` requires enough inode slots). Most likely
  prune failure leaves N=3+ backup dirs but the active and staging are correct.
- Mitigation: Log the rmtree failure at WARNING (not ERROR) — it does not affect
  correctness of the current cutover. The cutover exit code should still be 0 if the
  core swap succeeded. Document that prune failures are non-fatal.

**FM-4: BM25 staleness after cutover — the AC7 surface**
- Trigger: Cutover without building BM25 for the new version first. The server is
  restarted after cutover; `BM25Phase.startup` auto-builds — but it calls
  `build_bm25_index(lancedb_path=config.lancedb_path, ...)` where `lancedb_path` is
  the SHARED corpus path, not the notebook path. Per-notebook BM25 is ONLY built when
  someone explicitly calls `build_bm25_index(notebook_lancedb_path, version)`.
  If the cutover tool doesn't do this, the notebook's new corpus_version has no
  BM25 artifact at `var/arxmcp/index/bm25/v<new_version>/`. The server's shared BM25
  phase at v369 (or whatever the shared corpus is at) is irrelevant to per-notebook
  retrieval quality.
- Resolution: Build `build_bm25_index(staging_lancedb_path, corpus_version=staging_version)`
  explicitly in the cutover tool, before the rename. This is AC7's answer — the cutover
  BUILDS, not defers.

**FM-5: Slug path traversal via `--notebook`**
- Trigger: `make notebook-cutover ARGS="--notebook=../../etc"`.
- Symptom: Without validation, constructs `var/arxmcp/notebooks/../../etc/lancedb` →
  renames arbitrary filesystem paths.
- Mitigation: Call `validate_slug(slug)` + `notebook_dir(slug)` from
  `tools/_notebook_common.py` as the FIRST action in `main()`, before any filesystem
  op. `validate_slug` enforces `^[a-z][a-z0-9-]{2,30}$`; `notebook_dir` adds
  resolve-and-containment. This is already the established pattern for all notebook
  tools. Do NOT re-implement.

**FM-6: Rollback when no `lancedb-prev-*` exists**
- Trigger: Operator runs `--rollback --notebook=bridgeland-stability` but has never
  cut over (no `lancedb-prev-*` dir).
- Symptom: Without a guard, `perform_rollback` raises `CutoverError("rollback path
  does not exist")` — which is the correct behavior. The tool must surface this clearly:
  "No backup found. Have you run a cutover for this notebook?"
- Mitigation: Explicit check for `lancedb-prev-*` glob before attempting rollback;
  fail with a clear message and exit non-zero.

**FM-7: Concurrent cutover + re-embed**
- Trigger: `make notebook-cutover` while `make re-embed-all` is still writing to
  `lancedb-staging/`.
- Symptom: The cutover renames `lancedb-staging → lancedb` while the re-embed writer
  has an open LanceDB connection to `lancedb-staging`. The rename succeeds (the inode
  follows the writer's fd), but the writer continues appending new MVCC versions to
  the now-renamed directory (which is now `lancedb`). Result: the supposedly-stable
  promoted dataset gets new writes appended by the still-running re-embed, advancing
  `corpus-version.json` unexpectedly.
- Mitigation: The brief's pre-cutover gate checks `chunks.lance` existence, but does
  NOT check for a lock file. A simple advisory lock file (`lancedb-staging/.cutover-lock`)
  created by the cutover tool and checked by `re_embed_all` would help, but that is
  complex. Simpler: document in the Makefile help text that the operator must not run
  both simultaneously. The tool should print a warning if it detects a running Python
  process accessing the staging path (out of scope for M milestones; accept as known
  limitation and document).

## External writes the implementation will require

None — this milestone is purely local. All operations are `os.rename` and `shutil.rmtree`
within `var/arxmcp/notebooks/` and a write to `var/arxmcp/index/bm25/v<N>/`. No git
push, no PR, no infra mutation, no network egress.
