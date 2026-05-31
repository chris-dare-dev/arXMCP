# Critique — onboarding-uplift-m2 (merged)

**Critics:** milestone-adversary (8 findings: 1C/1H/4M/2L) +
milestone-infra-safety (1 finding: 1L). 9 findings total.
**Generated:** 2026-05-31.
**Commit range:** `4f1f6648a914768fce72ae877962a78895d0c9fc..43b90858e2c23e6b4177016474273083ed2514d4`
**Verdict:** RECTIFY-REQUIRED — DO-NOT-SHIP without F1 fix.

## Executive summary

- **F1 CRITICAL — live-reproduced data-loss bug on the AC1→AC3 happy path.**
  `_register_notebook_in_sqlite` writes a `notebooks` row via
  `CREATE TABLE IF NOT EXISTS` and INSERT OR IGNORE, deliberately NOT touching
  `PRAGMA user_version`. Per synthesis §3 D1 this was the explicit design.
  BUT: when the operator later runs `make up` for the first time,
  `NotebooksStore.open` reads `user_version=0`, enters the v0→v1 block at
  `server/notebooks_store.py:154-156` which executes
  `DROP TABLE IF EXISTS notebooks` UNCONDITIONALLY (not IF NOT EXISTS), and
  the row inserted by `make init` is DESTROYED. The very 404 that AC3 was
  built to prevent now happens by construction on the cold-clone path. The
  test `test_registers_notebook_in_sqlite` PASSED because it ran against a
  pre-existing `notebooks.db` already at `user_version=4` — the test masked
  the regression.
- **F2 HIGH** — `tools/notebook_list_offline.py` calls
  `NotebooksStore.open` which triggers the same destructive migration on
  the operator's only copy of the file when invoked against a fresh DB.
  Compounds F1.
- **Cardinal `PRAGMA user_version` non-touch invariant (D1) verified clean**
  in both `server/operator_settings.py` and `tools/notebook_init.py`.
  Mutation-injection of `PRAGMA user_version = 99` confirmed
  `test_user_version_NOT_touched_by_operator_settings` fails — the guard
  is real. The bug is that we DELEGATED schema ownership to NotebooksStore
  without claiming a compatible version.
- **BP1/BP2 byte-stability** verified clean (42 hash tests pass).
- 4 MEDIUMs (F3-F6) — test isolation, SQLite-shadow-log, partial-write
  atomicity, chmod-TOCTOU. All cheap fixes.
- 3 LOWs (F7-F8 + IS1) — duplicate DEFAULT_DB_PATH constant, .PHONY
  readability, unquoted `$(NOTEBOOK)` Make var.

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

### F1 — `make init` row destroyed by first `make up` on fresh repo (CRITICAL)

- **Source:** adversary
- **File:** `tools/notebook_init.py:178-189` + `server/notebooks_store.py:154-156`
- **What:** `_register_notebook_in_sqlite` writes a row via direct SQLite
  without setting `user_version`. The file stays at `user_version=0`.
  `NotebooksStore.open`'s v0→v1 block at line 154 then runs
  `DROP TABLE IF EXISTS notebooks` unconditionally, destroying the row.
  Live-reproduced.
- **Recommendation:** Adversary Option 2 (preferred): replace the inline
  SQLite write in `_register_notebook_in_sqlite` with a call into
  `NotebooksStore.open` + `store.create_notebook(...)`. Pays ~30ms event-loop
  spin in the CLI but eliminates the entire dual-schema-creator hazard.
  Regression test: open the DB at a fresh tmp_path, call the new register
  helper, then open via `NotebooksStore.open`, assert the row survives.

### F2 — `tools/notebook_list_offline.py` mutates the file on a "list" call (HIGH)

- **Source:** adversary
- **File:** `tools/notebook_list_offline.py:37`
- **What:** Offline lister calls `NotebooksStore.open` which runs the full
  v0→v4 migration sequence (including the v0→v1 DROP TABLE). An operator
  running `make notebook-list` to inspect state receives the side effect
  of having their schema force-upgraded.
- **Recommendation:** Bypass `NotebooksStore.open`. Open a raw
  `sqlite3.Connection` and run `SELECT slug, display_name FROM notebooks
  ORDER BY created_at DESC, slug ASC` wrapped in `try/except
  sqlite3.OperationalError` (table-missing → friendly "no notebooks; run
  make init" message). Regression: pre-create a fresh DB at
  `user_version=2`, run main, assert version unchanged + row intact.

### F3 — `test_registers_notebook_in_sqlite` runs against shared real notebooks.db (MEDIUM)

- **Source:** adversary
- **File:** `tests/test_make_targets.py:42-94`
- **What:** Fixture cleans the real `var/arxmcp/cache/notebooks.db`; not
  monkeypatched. Blocks parallel test runs + risks collision with an
  operator's real slug.
- **Recommendation:** Thread `notebooks_base` + `db_path` overrides through
  `notebook_init.run` and have the fixture pass `tmp_path` for both.

### F4 — `resolve_contact_email` has no env-var-wins override hatch (MEDIUM)

- **Source:** adversary
- **File:** `tools/_notebook_common.py:182-209`
- **What:** SQLite wins over env var per synthesis §3 D1; synthesis FM-3
  prescribed "Log an INFO message when env-var present but SQLite already
  has a value" but implementation does NOT log this. Silent shadowing.
- **Recommendation:** Emit `logger.info("SQLite contact_email shadowed env-var")`
  in the SQLite-wins branch when both are set.

### F5 — `_persist_email` and `_register_notebook_in_sqlite` not atomic (MEDIUM, doc-only fix)

- **Source:** adversary
- **File:** `tools/notebook_init.py:261-265`
- **What:** Two separate sqlite3 sessions; SIGINT between them leaves
  partial state. Re-running `make init` recovers (both ops are idempotent)
  but the implementation summary line 22 promises "Idempotent at all three
  levels" without addressing partial-failure.
- **Recommendation:** Docstring note on the `run` function — re-running on
  partial state is the recovery mechanism. ~5 LOC, doc-only.

### F6 — `_open_sync`'s file_existed→chmod TOCTOU is silently single-process (MEDIUM)

- **Source:** adversary
- **File:** `server/operator_settings.py:197-228`
- **What:** `path.exists()` then `sqlite3.connect` then chmod is a TOCTOU
  vs another process pre-creating the file. Single-workstation context
  makes it benign-but-present.
- **Recommendation:** Use `os.open(db_path, O_RDWR | O_CREAT | O_EXCL,
  0o600)` for atomic create-with-mode; catch `OSError(EEXIST)` for the
  pre-existed branch. ~6 LOC.

### F7 — `notebook_list_offline.py` shadows the canonical DEFAULT_DB_PATH (LOW)

- **Source:** adversary
- **File:** `tools/notebook_list_offline.py:31` vs `server/operator_settings.py:91`
- **What:** Two sources of truth for the canonical notebooks.db path.
- **Recommendation:** Import from `server.operator_settings`. Single-line fix.

### F8 — `Makefile:1` .PHONY line is unreadable (LOW)

- **Source:** adversary
- **File:** `Makefile:1`
- **What:** 219-character one-line `.PHONY` declaration listing 19 targets.
- **Recommendation:** Split into multiple `.PHONY: ...` lines grouped by
  section. **DEFER** per LOW-fix rules.

### IS1 — Unquoted `$(NOTEBOOK)` in `init` and `add` shell recipes (LOW)

- **Source:** infra-safety
- **File:** `Makefile:427-429, 452-456`
- **What:** Unquoted Make variable interpolation in shell context;
  whitespace in NOTEBOOK would word-split. Latent (slug regex rejects
  whitespace at the Python layer).
- **Recommendation:** Quote `"$(NOTEBOOK)"` and `"$$papers_txt"` at every
  shell-word-position interpolation.

## What was done well (concatenated, dedup)

- **Cardinal `PRAGMA user_version` non-touch is RIGOROUSLY honored** in
  `server/operator_settings.py` and `tools/notebook_init.py` (grep clean).
- **The cardinal regression test
  `test_user_version_NOT_touched_by_operator_settings` was verified to
  catch a real mutation** (mutation-inject confirmed it fails on regression).
- **BP1/BP2 hash discipline is held** — live-run, 42 hash tests pass.
- **ruff check . is clean.**
- **Connection pragmas mirrored verbatim** from `NotebooksStore`:
  WAL + synchronous=FULL + fullfsync=ON + busy_timeout=5000 +
  isolation_level=None, with the comment block quoting NotebooksStore's
  reasoning verbatim.
- **Reserved-key validation** (`__schema_version__` refused at public API).
- **Synthesis §3 D3 cross-package import direction honored** —
  `ingest/*.py` import directly from `server.operator_settings`, avoiding
  the `ingest/ → tools/` cycle risk.
- **`make add` Make recipe shell control-flow is correct** despite the
  `\`-line-continuation gauntlet — live-tested.
- **`make help` AC6 layout precisely correct** — 14 pre-m2 targets
  parametrized + FIRST-TIME-before-EVERYTHING-ELSE positional invariant
  asserted.
- **`--register` / `--no-register` escape hatch** — clean default-ON.
- **Idempotency correctly handled** in all three new Make targets
  (INSERT OR IGNORE / OR REPLACE / grep -qxF).
- **Exit codes propagate correctly** throughout the new recipes.
- **`add` recipe correctly distinguishes server-up REST failure (clean
  error) from server-down (file fallback)** per synthesis D5.
- **No `sudo` anywhere.** No destructive defaults.

## Recommended rectification order

1. **F1 (CRITICAL)** — Option 2: route the `_register_notebook_in_sqlite`
   write through `NotebooksStore.open` + `store.create_notebook`. Add the
   cold-DB regression test that reproduces the bug pre-fix.
2. **F2 (HIGH)** — direct sqlite3 read in `notebook_list_offline.py`.
3. **F4 (MEDIUM)** — INFO log on SQLite-shadows-env-var.
4. **F3 (MEDIUM)** — test fixture redirect to tmp_path.
5. **F5 (MEDIUM, doc-only)** — atomicity docstring note.
6. **F6 (MEDIUM)** — O_CREAT | O_EXCL atomic create.
7. **IS1 (LOW)** — quote `$(NOTEBOOK)` + `$$papers_txt`.
8. **F7 (LOW)** — import DEFAULT_DB_PATH from canonical seam.
9. **F8 (LOW)** — DEFER (.PHONY readability).

## Rectification status (filled by Phase 4)

- **F1 (CRITICAL)** — RESOLVED. `_register_notebook_in_sqlite`
  rewritten to delegate to `NotebooksStore.open` + `create_notebook`
  via `asyncio.run`. The DB's `user_version` is now correctly bumped
  to `SCHEMA_VERSION=4` by NotebooksStore's migration sequence; a
  subsequent `make up` finds a current-version DB and skips the
  destructive v0→v1 block entirely. ~30ms event-loop spin in the CLI
  was the synthesis-acknowledged cost. **Cardinal regression guard:**
  `tests/test_make_targets.py::TestMakeInit::test_row_survives_first_server_open`
  — registers a slug then opens via `NotebooksStore.open` and asserts
  the row survives. This test would have failed pre-fix.
- **F2 (HIGH)** — RESOLVED. `tools/notebook_list_offline.py`
  rewritten to use a raw read-only `sqlite3.Connection`
  (`mode=ro` URI) with a single `SELECT slug, display_name FROM
  notebooks` query. Missing-table case caught via
  `sqlite3.OperationalError` and treated as "no notebooks yet". The
  file is now NEVER written to. **Regression guard:**
  `tests/test_make_targets.py::TestNotebookListOffline::test_user_version_unchanged_after_list`
  — pre-creates a v2-shape DB, runs the lister, asserts user_version
  unchanged + column count unchanged. Would have failed pre-fix.
- **F3 (MEDIUM)** — RESOLVED. `tools/notebook_init.run` gained a
  `notebooks_base: Path | None = None` parameter that threads through
  to `notebook_dir(base=...)` AND to `_register_notebook_in_sqlite`'s
  `notebook_lancedb_path(slug, base=...)` call. The
  `TestMakeInit.env` fixture now scopes BOTH `notebooks_base` and
  `db_path` to `tmp_path` — no shared-workstation pollution, parallel
  test runs are safe. The old `fresh_slug` fixture was removed.
- **F4 (MEDIUM)** — RESOLVED.
  `tools/_notebook_common.py::resolve_contact_email` now emits an
  INFO log when the SQLite-persisted value shadows a different env-var
  value: `"resolve_contact_email: SQLite operator_settings.contact_email
  (X) shadows env var ARXMCP_CONTACT_EMAIL (Y); set EMAIL= on make
  init to update the persisted value."`. The shadowing remains
  intentional (synthesis §3 D1 — sticky pref). **Regression guards
  (2):** `test_sqlite_shadows_env_var_emits_info_log` +
  `test_no_shadow_log_when_only_sqlite_set` (the negative case —
  no log fires when only SQLite is set).
- **F5 (MEDIUM, doc-only)** — RESOLVED. `tools/notebook_init.run`
  docstring extended with an explicit "Partial-state recovery"
  paragraph naming SIGINT between the three side-effects + the
  re-run-recovers contract. No test added (doc-only finding).
- **F6 (MEDIUM)** — RESOLVED.
  `server/operator_settings.py::_open_sync` rewritten to use
  `os.open(db_path, O_RDWR | O_CREAT | O_EXCL, 0o600)` for the
  atomic create-with-mode path. `FileExistsError` is caught to
  preserve the "never retroactively chmod" promise from D6. The
  belt-and-braces `os.chmod(db_path, 0o600)` runs only when WE
  created the file (file_created_by_us tracker). Existing
  `test_pre_existing_file_perms_NOT_retroactively_changed` still
  passes — file pre-existed → EEXIST → no chmod → mode stays 0o644.
- **F7 (LOW)** — RESOLVED.
  `tools/notebook_list_offline.py` now imports
  `DEFAULT_DB_PATH` from `server.operator_settings` (the canonical
  seam). Single source of truth restored.
- **F8 (LOW)** — DEFERRED. `.PHONY` line readability is cosmetic;
  rectification rules defer LOW findings unless cheap-and-related to
  a higher-severity fix. Tracked as a candidate for an
  `onboarding-uplift-m3` tidy-up commit.
- **IS1 (LOW)** — RESOLVED. `Makefile` `init` and `add` recipes now
  quote `"$(NOTEBOOK)"` + `"$$papers_txt"` at every shell-word-position
  interpolation. The slug regex at the Python layer already rejects
  whitespace; this is belt-and-braces in case a future contributor
  reads the Make recipe in isolation.

**0% invalidation rate** — all 9 findings re-verified cleanly;
1 CRITICAL + 1 HIGH + 4 MEDIUM + 2 LOW (IS1 + F7) fixed; 1 LOW (F8)
deferred with reason. 4 new regression tests
(`test_row_survives_first_server_open`,
`test_user_version_unchanged_after_list`,
`test_sqlite_shadows_env_var_emits_info_log`,
`test_no_shadow_log_when_only_sqlite_set`). All 7 pre-existing
TestMakeInit tests rewritten to use the new `env` fixture (tmp_path-
scoped). Full suite: `3 failed, 3588 passed, 30 skipped, 1 xfailed`
(3 pre-existing m2-unrelated failures). ruff clean.
