# E11_S05 — Research Synthesis

Merged from [research-brief-1.md](research-brief-1.md) (cutover
mechanics + activation criteria + rollback semantics) and
[research-brief-2.md](research-brief-2.md) (backup/restore +
restic + systemd + restore drill). The briefs converge sharply
on the file-sentinel pattern (4 prior E11 milestones established
it) and on the staging-vs-active discipline. Two important
opinions:

1. Brief 1: **the activation IS a directory swap**, not a marker
   rewrite. Synthesized below.
2. Brief 1: **ship Python `ops/cutover.py` + a thin
   `ops/cutover.sh` wrapper**. The bash deliverable in the brief
   is satisfied by the wrapper; the heavy logic (JSON parsing,
   atomic renames, HTTP polling, subprocess to watchdog) lives
   in Python where it can be unit-tested.

---

## 1. Headline findings (consensus)

| # | finding | resolution |
|---|---|---|
| 1 | **Activation = atomic directory swap, NOT marker rewrite.** The staging and active LanceDB datasets live at different filesystem paths; their internal version integers are not interchangeable. Copying `corpus-version.json` from staging to active would point the server at a non-existent LanceDB version. | Two `os.rename`s on the same FS: `lancedb/` → `lancedb-prev/` (rollback snapshot), then `lancedb-staging/` → `lancedb/`. The staging `corpus-version.json` is already correct (it carries the staging dataset's internal version, which after the swap IS the active dataset). No marker rewrite needed. |
| 2 | **Cutover is Python + bash wrapper.** Brief specifies `.sh` deliverable; ship `ops/cutover.py` with `ops/cutover.sh` thin wrapper. The script does JSON parsing, atomic renames, HTTP polling, subprocess invocation — bash + `jq` is fragile compared to Python's testability. | `ops/cutover.sh`: `exec uv run python -m ops.cutover "$@"`. The brief's deliverable is satisfied by the bash wrapper. |
| 3 | **Server has NO warm-reload path.** `Resources.startup` runs once; the chunks-table handle is cached for process lifetime. Cutover REQUIRES a process restart. | The runbook documents the ~10-30s unavailability window. `cutover.py` polls `/readyz` with `curl --fail --retry 12 --retry-delay 5` (60s budget per AC4). |
| 4 | **Rollback = inverse atomic swap.** The brief's "revert corpus-version.json" is wrong in isolation — the version integer is dataset-specific. Full rollback: stop server, `os.rename("lancedb/", "lancedb-failed-cutover-<ts>/")`, `os.rename("lancedb-prev/", "lancedb/")`, restart. Two renames + restart < 30s. | The runbook documents this concretely. `cutover.py --rollback` could implement the inverse swap (recommended addition). |
| 5 | **4 activation criteria, ordered cheap-first** (file reads before subprocess invocations): C3 (re-embed state) → C4 (restore-drill flag) → C1 (seed eval aggregate) → C2 (watchdog quarantine + latest report). Any fail → refuse with clear error. | `cutover.py` runs all four checks in this order. Each check returns `(ok: bool, reason: str)`; first failure aborts. |
| 6 | **Restore drill writes its own sentinel.** No existing source-of-truth file for "drill passed". Recommend `var/arxmcp/ops/restore-drill-passed.flag` written by `ops/restore_drill.sh` after smoke check succeeds. | Drill script writes the flag atomically (tmp+rename); cutover.py reads it for C4. |
| 7 | **Restore-drill smoke check is LIGHT, not a full server run.** Open LanceDB, count rows, run a synthetic ANN query, open Kùzu. Faster than starting BGE-M3 + FastAPI; catches the data-integrity questions a restore drill actually needs. | `ops/restore_drill_check.py`: lazy imports of `server.corpus.open_chunks_table`, opens the staging table via the synthetic-LanceDB pattern from E09's `_graph_helpers.py`. |
| 8 | **`lancedb-prev/` existence check.** If a prior cutover failed and left `lancedb-prev/` in place, cutover.py must refuse with an actionable message rather than silently overwriting the rollback lifeline. | Pre-flight check before step 1 of the swap. |
| 9 | **restic backup paths are deployment-relative.** Use `${REPO_ROOT}/var/arxmcp/...` not hardcoded `/opt/arxmcp/...` so the wrapper works on developer machines AND production. | Same pattern as the cron wrappers (E11_S02 IS2 lesson, doubly reinforced by E11_S04 IS2). |
| 10 | **Backup is operator-runtime, not code-ship.** The implementation ships configuration, scripts, and tests. Actual `restic backup` against a live repository requires operator hardware + configured creds. | Same posture as E11_S01 bulk ingest, E11_S02 OAI delta — code-ship is the scaffolding. |
| 11 | **Cross-process /metrics for backup status is deferred to E14.** A `backup-status.json` sentinel is the v1 operational signal (same posture as E10_S04 drift + E11_S04 watchdog). | E14 will read the sentinel at scrape time. |
| 12 | **No tool-schema changes.** No new MCP tools. | `TOOL_SCHEMA_VERSION` stays at 6. |

---

## 2. Load-bearing quotes

### `ingest/bulk_ingest.py` module docstring

> "The active `corpus-version.json` (under `var/arxmcp/index/lancedb/`)
> is left untouched; E11_S05 advances it via an atomic directory
> swap."

(This is the load-bearing claim that justifies the directory-swap
approach; all 4 prior E11 milestones honor it.)

### `.claude/notes/06-mcp-server-design.md` lines 346-354

> "The MCP server does NOT auto-switch — it continues using its
> pinned version. Restart the server to pick up the new corpus."

### `.claude/notes/05-storage-and-indexing.md` (MVCC activation)

> "No manual symlink swaps. LanceDB version int IS the
> corpus_version. Writers use the current dataset; readers call
> `dataset.checkout(version=N)`."

(Note: "no symlink swaps" — but the resolution here is
**directory renames**, not symlinks. The constraint is honored.)

### `.claude/TIER-GATES.md` — Tier-5 cutover (verbatim)

> "**Backfill complete:** the full 200 K paper corpus is ingested
> to a single LanceDB table. **Drift watchdog stable:** the
> latest scheduled nDCG@5 measurement (per E11_S04's drift
> watchdog) is within 5% of the previous baseline."

(TIER-GATES.md specifies 5% for the gate; E11_S04's default
threshold ships at 10% for statistical robustness. cutover.py
checks BOTH: the quarantine flag (watchdog's own threshold) AND
the most recent report's `ndcg5_mean >= 0.80`.)

### Restic password loss is unrecoverable

> "Encryption: restic encrypts all repository data at rest using
> AES-256-CTR with HMAC-SHA256 authentication. Losing the
> password = permanent data loss — there is no recovery path."

---

## 3. Divergence + resolution

### `cutover.sh` vs `cutover.py`

Brief 1 recommends Python; brief 2 doesn't take a position.
**Resolution:** ship Python (`ops/cutover.py`) with a thin bash
wrapper (`ops/cutover.sh`). The brief's `.sh` deliverable is
satisfied by the wrapper; the heavy logic is testable.

### Restore-drill smoke depth

Brief 2 explicitly recommends the LIGHTER smoke check (LanceDB
+ Kùzu open + synthetic ANN query) over a full server run.
**Resolution:** ship the lighter check. Document both options in
the runbook.

---

## 4. Design decisions

### D1. Module: `ops/cutover.py` + `ops/cutover.sh`

`cutover.py` owns:
- `CutoverError` exception.
- `CriterionResult` dataclass (`(name, ok, reason)`).
- `check_criterion_3_re_embed_state(state_path)` — file read.
- `check_criterion_4_restore_drill_flag(flag_path)` — file
  presence + JSON-parse the flag.
- `check_criterion_1_seed_eval(active_marker_path, eval_dir)` —
  reads active corpus-version.json, finds
  `aggregate-<N>.json`, asserts `ndcg5_mean >= 0.80`.
- `check_criterion_2_watchdog(quarantine_path, report_dir,
  staging_version, threshold=0.80)` — reads the most-recent
  watchdog report at the staging version, asserts no quarantine
  flag + `ndcg5_mean >= 0.80`.
- `verify_lancedb_integrity(staging_path)` — opens the staging
  chunks table, asserts `count_rows > 0`. Replaces the brief's
  fictional `lancedb verify` CLI.
- `perform_directory_swap(active_path, staging_path,
  rollback_path)` — two `os.rename`s. Pre-flight: refuse if
  rollback_path already exists.
- `poll_readyz(url, total_timeout=60.0, interval=5.0)` — HTTP
  polling.
- `run_post_activation_watchdog(active_path)` — subprocess
  invocation of `ops.watchdog_eval` against the now-active path.
- `run_cutover()` — orchestrator.
- `run_rollback()` — inverse swap + restart.
- `_cli(argv)` — argparse with `--dry-run`, `--rollback`.

`ops/cutover.sh` is a 5-line wrapper:
```bash
#!/usr/bin/env bash
set -euo pipefail
# (SCRIPT_DIR/REPO_ROOT resolution + uv lookup, same pattern)
exec "${UV_BIN}" run python -m ops.cutover "$@"
```

### D2. Activation criteria check order

Cheap-first: **C3 → C4 → C1 → C2** (per Brief 1 §2). All 4 must
pass before the directory swap fires. Failure messages cite the
exact file path the operator should inspect.

### D3. Atomic directory swap

```python
def perform_directory_swap(
    active_path: Path,
    staging_path: Path,
    rollback_path: Path,
) -> None:
    if rollback_path.exists():
        raise CutoverError(
            f"refusing to overwrite existing rollback path "
            f"{rollback_path} — prior cutover may have failed"
        )
    os.rename(active_path, rollback_path)
    try:
        os.rename(staging_path, active_path)
    except OSError as exc:
        # Best-effort: restore the old active path.
        os.rename(rollback_path, active_path)
        raise CutoverError(
            f"directory swap failed at step 2: {exc}. "
            f"Restored old active path."
        ) from exc
```

### D4. Restore drill: `ops/restore_drill.sh` +
`ops/restore_drill_check.py`

- `restore_drill.sh`: bash wrapper. Sources restic env, picks
  most-recent snapshot, restores to
  `/tmp/arxmcp-restore-drill/`, calls `restore_drill_check`,
  writes the sentinel, cleans up.
- `restore_drill_check.py`: lazy-imports `server.corpus`. Opens
  the restored LanceDB, asserts row count > 0, runs a synthetic
  ANN query, opens Kùzu. Exit 0 / 1.

### D5. Backup wrapper + systemd

- `ops/cron/arxmcp-backup.sh`: mirrors `arxmcp-watchdog.sh`
  (E11_S04). `set -euo pipefail`, SCRIPT_DIR/REPO_ROOT
  resolution, `command -v uv/flock/restic`. Sources
  `ops/restic-env.sh`. Runs `restic backup` + `restic forget
  --prune`. Writes `backup-status.json` sentinel.
- `ops/systemd/arxmcp-backup.{service,timer}`: nightly at
  03:30, `TimeoutStartSec=14400` (4h defense-in-depth),
  hardening directives mirror `arxmcp-delta.service`.

### D6. restic env template

- `ops/restic-env.sh.template`: committed; documents
  RESTIC_REPOSITORY, RESTIC_PASSWORD_FILE, B2_ACCOUNT_ID,
  B2_ACCOUNT_KEY. Refuses sourcing when RESTIC_REPOSITORY is
  empty.
- `ops/restic-env.sh`: gitignored (the actual file with creds).
  Add to `.gitignore`.

### D7. Runbooks

- `docs/ops/cutover-runbook.md`: structure mirrors
  E11_S01/S02/S03/S04 runbooks. Sections: scope, prerequisites,
  activation criteria (the 4 bullets), procedure, post-
  activation health checks, rollback procedure (< 30s),
  failure modes, state file schema.
- `docs/ops/backup-restore.md`: same shape per Brief 2 §6.

### D8. README link

The README Operations table (closed in E11_S04) gains two new
rows: cutover-runbook.md (E11_S05) + backup-restore.md
(E11_S05).

### D9. Makefile target

Mirror `make ingest` / `make delta` / `make re-embed` /
`make watchdog`:

```makefile
cutover:
    @# E11_S05 — activation script. Checks 4 criteria + atomic
    @# directory swap. See docs/ops/cutover-runbook.md.
    ...
    $(PYTHON) -m ops.cutover $(ARGS)
```

(No `make backup` target — restic is operator-cron-driven, not
ad-hoc. Document the wrapper invocation in the runbook.)

### D10. Test surface

Per Brief 2 §7:

- `tests/test_cutover.py`:
  - `TestActivationCriteria` × 4 (one per criterion): synthetic
    fixtures + assertions.
  - `TestDirectorySwap`: tmp_path with synthetic
    `lancedb/`/`lancedb-staging/`; asserts atomic semantics +
    rollback-on-step-2-failure.
  - `TestRollback`: inverse swap.
  - `TestPreflightRollbackExists`: refuses if `lancedb-prev/`
    already exists.
  - `TestPollReadyz`: mocks `requests.get` with a sequence of
    503 → 503 → 200.

- `tests/test_backup_wrapper.py`:
  - `TestEnvTemplate`: assert template names env vars; not
    executable.
  - `TestSystemdUnit`: assert hardening directives,
    TimeoutStartSec, OnCalendar.
  - `TestShellWrapper`: assert `set -euo pipefail`, flock guard,
    no hardcoded paths.

- `tests/test_restore_drill.py`:
  - `TestSentinelWrite`: mock subprocess; assert sentinel JSON.
  - `TestRestoreDrillCheck`: synthetic LanceDB; assert exit 0
    on valid data, non-zero on empty table.

- Pytest marker: `requires_restic` (env-var-gated:
  `ARXMCP_RUN_RESTORE_DRILL=1`).

### D11. No tool-schema changes

`TOOL_SCHEMA_VERSION` stays at 6.

### D12. `.gitignore` mutation

Add `ops/restic-env.sh` to `.gitignore` (the credential file).

---

## 5. Forced cross-file changes

| File | Change | Why |
|---|---|---|
| `ops/cutover.py` (NEW) | Python orchestrator + activation criteria + swap + rollback | D1, D2, D3 |
| `ops/cutover.sh` (NEW) | thin bash wrapper invoking `python -m ops.cutover` | D1 (satisfies brief's `.sh` deliverable) |
| `ops/restic-env.sh.template` (NEW) | restic config template | D6 |
| `ops/cron/arxmcp-backup.sh` (NEW) | backup shell wrapper with flock + restic call | D5 |
| `ops/systemd/arxmcp-backup.service` (NEW) | nightly oneshot unit | D5 |
| `ops/systemd/arxmcp-backup.timer` (NEW) | OnCalendar=*-*-* 03:30:00 | D5 |
| `ops/restore_drill.sh` (NEW) | operator-invoked drill script | D4 |
| `ops/restore_drill_check.py` (NEW) | smoke-check module | D4 |
| `docs/ops/cutover-runbook.md` (NEW) | operator runbook | D7 |
| `docs/ops/backup-restore.md` (NEW) | operator runbook | D7 |
| `Makefile` (MODIFY) | `make cutover` target | D9 |
| `README.md` (MODIFY) | 2 new rows in Operations table | D8 |
| `.gitignore` (MODIFY) | `ops/restic-env.sh` line | D12 |
| `tests/test_cutover.py` (NEW) | Cutover unit tests | D10 |
| `tests/test_backup_wrapper.py` (NEW) | Backup-wrapper unit tests | D10 |
| `tests/test_restore_drill.py` (NEW) | Restore-drill unit tests | D10 |
| `pyproject.toml` (MODIFY) | Register `requires_restic` marker | D10 |

NOT touched: `server/tools.py`, `ingest/store.py`,
`ingest/oai_delta.py`, `ingest/re_embed.py`,
`ops/watchdog_eval.py`, hash-anchored tests.

---

## 6. Landmines (consolidated)

1. **Activation = directory swap, not marker rewrite.** Same FS,
   `os.rename`. POSIX-atomic.
2. **Pre-flight: refuse if `lancedb-prev/` exists.** Don't
   overwrite the operator's rollback lifeline.
3. **No warm-reload path on the server.** Cutover requires a
   process restart; budget ~10-30s for BGE-M3 warm-up.
4. **`/readyz` poll, not a fixed sleep.** AC4 demands ≤60s; a
   warm server flips faster.
5. **Post-activation watchdog targets `DEFAULT_LANCEDB_PATH`**
   (the now-active path). The watchdog's `--lancedb-staging-path`
   flag is paradoxically the override mechanism — the runbook
   makes this explicit.
6. **`restic` password loss is unrecoverable.** Store in a
   password manager AND a hard copy.
7. **`flock` not on macOS PATH.** E11_S04 IS1 lesson; the
   backup wrapper guards.
8. **`/Users/`-hardcoded paths are banned.** E11_S02 IS2
   lesson, internalized.
9. **`assert` banned for invariants.**
10. **HEREDOC commits, GPG signed, no `--no-verify`.**
11. **Cross-process /metrics for backup status is E14.**
    `backup-status.json` sentinel is the v1 signal.
12. **No `--resume` flag** (cutover is short-lived;
    E11_S01 F3 lesson).

---

## 7. AC coverage at code-ship

| Brief AC | Coverage at code-ship |
|---|---|
| AC1 (cutover.py checks 4 criteria) | Verifiable via `TestActivationCriteria` × 4. |
| AC2 (restore drill + MCP smoke passes) | Verifiable in synthetic-LanceDB mode (`TestRestoreDrillCheck`). End-to-end against real restic requires `ARXMCP_RUN_RESTORE_DRILL=1`. |
| AC3 (runbook states 4 criteria + rollback time) | Verifiable via grep tests on `docs/ops/cutover-runbook.md`. |
| AC4 (/readyz 200 within 60s) | Verifiable via `TestPollReadyz` with mocked HTTP. Operator-gated for real cutover. |
| AC5 (post-cutover watchdog nDCG@5 ≥ 0.80) | Synthetic test via mocked subprocess; operator-gated for real. |

---

## 8. External writes required at code-ship

**None.** All in-repo writes. Operator-runtime writes:

- `var/arxmcp/index/lancedb/` ← `os.rename` from staging (THE
  cutover write)
- `var/arxmcp/index/lancedb-prev/` ← `os.rename` from old
  active (rollback lifeline)
- `var/arxmcp/ops/restore-drill-passed.flag` (sentinel)
- `var/arxmcp/ops/backup-status.json` (sentinel)
- restic repository writes to NAS or B2

These are gated on operator action.

---

## 9. Suggested implementation order

1. `ops/cutover.py` + `ops/cutover.sh` wrapper + `tests/test_cutover.py`.
2. `ops/cron/arxmcp-backup.sh` + `ops/restic-env.sh.template` +
   `ops/systemd/arxmcp-backup.{service,timer}` +
   `tests/test_backup_wrapper.py`.
3. `ops/restore_drill.sh` + `ops/restore_drill_check.py` +
   `tests/test_restore_drill.py`.
4. `docs/ops/cutover-runbook.md` + `docs/ops/backup-restore.md`.
5. `Makefile` (`make cutover`).
6. `README.md` (Operations table rows).
7. `.gitignore` (`ops/restic-env.sh`).
8. `pyproject.toml` (`requires_restic` marker).
9. `make test` (full suite); ruff clean; feat commit.

---

## 10. Done-when checklist

- [ ] All 5 brief ACs covered (3 fully + 2 operator-gated with
  synthetic tests).
- [ ] Directory swap implemented with rollback safety.
- [ ] `lancedb-prev/` preflight check in place.
- [ ] `/readyz` polling honors 60s budget.
- [ ] Restore drill writes the `restore-drill-passed.flag`
  sentinel atomically.
- [ ] Backup wrapper carries `flock`, `command -v
  uv/flock/restic` guards, no hardcoded paths.
- [ ] systemd unit hardening directives match E11_S02 pattern.
- [ ] Runbooks document all 4 criteria + rollback time + state
  file schemas.
- [ ] README Operations table linked.
- [ ] `make cutover` target with Python version guard + ARGS
  word-split note.
- [ ] No `TOOL_SCHEMA_VERSION` bump.
- [ ] `make test` green; ruff clean.
