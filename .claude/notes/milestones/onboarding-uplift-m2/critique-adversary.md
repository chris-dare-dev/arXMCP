# Critique — onboarding-uplift-m2

**Critic:** adversary
**Generated:** 2026-05-31T00:05:00Z
**Commit range:** 4f1f6648a914768fce72ae877962a78895d0c9fc..43b90858e2c23e6b4177016474273083ed2514d4
**Verdict:** DO-NOT-SHIP

## Executive summary

- Verdict DO-NOT-SHIP. **Live-reproduced CRITICAL data-loss bug** on the
  AC1→AC3 happy path: `make init NOTEBOOK=demo` writes a `notebooks` row
  via `_register_notebook_in_sqlite`, the operator runs `make up` for
  the first time, `NotebooksStore.open` reads `user_version=0`, runs the
  v0→v1 migration which is `DROP TABLE IF EXISTS notebooks` (not
  `IF NOT EXISTS`), and the registry row is silently destroyed — the
  very 404 AC3 was supposed to prevent now happens by construction.
- 1 CRITICAL, 1 HIGH, 4 MEDIUM, 2 LOW (8 findings total).
- Highest-risk site: `server/notebooks_store.py:154-156` (the
  unconditional `DROP TABLE` in v0→v1) consumed by
  `tools/notebook_init.py:178-189` (`CREATE TABLE IF NOT EXISTS notebooks`
  with `user_version` left at 0).
- Cardinal `PRAGMA user_version` non-touch invariant (synthesis §3 D1):
  VERIFIED clean — neither `server/operator_settings.py` nor
  `tools/notebook_init.py` calls `PRAGMA user_version = N`. Mutation-
  inject of `PRAGMA user_version = 99` into `_open_sync` was confirmed
  to break `test_user_version_NOT_touched_by_operator_settings` — the
  guard is real.
- BP1/BP2 hashes UNCHANGED. Live-ran
  `tests/test_server_tool_schema.py` + `tests/test_prompts.py` → 42
  passed. `ruff check .` clean. The MCP cache-stability axis is clean.
- `tools/notebook_list_offline.py` runs `NotebooksStore.open` against
  the disk file, which executes write-side migrations against what an
  operator (correctly) regards as a "list-only" command — surprising
  side effect that should be documented or gated to read-only.
- `tools/notebook_init.py::run` uses a SHARED real
  `var/arxmcp/cache/notebooks.db` via `notebook_lancedb_path(slug)` and
  the test harness writes/cleans rows against it (test pollution risk
  on shared workstation state).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `make init` row destroyed by first `make up` on fresh repo

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** `tools/notebook_init.py:178-189` (consumer) +
  `server/notebooks_store.py:154-156` (destroyer)
- **What:** `_register_notebook_in_sqlite` runs `CREATE TABLE IF NOT
  EXISTS notebooks (…8 cols…)` then `INSERT OR IGNORE INTO notebooks …`
  on a fresh `notebooks.db`. It deliberately does NOT touch
  `PRAGMA user_version`, so the file's `user_version` stays at 0.
  When the operator later runs `make up`, `NotebooksStore.open` reads
  `user_version=0`, enters the `if current_version < 1:` block at
  `notebooks_store.py:154`, and executes `DROP TABLE IF EXISTS
  notebooks` immediately followed by `CREATE TABLE notebooks (…4
  cols…)`. The row inserted by `make init` is DROPPED. Then the v1→v2,
  v2→v3, v3→v4 ADDITIVE migrations run on the now-empty table.
- **Why it matters:** This is the EXACT failure mode the milestone was
  built to prevent (AC3: "make add works after make init without
  asking the server to register the notebook"). Live-reproduced
  end-to-end with `/tmp/test-cold.db`:
  ```
  After make init: rows=[('coldslug',)], user_version=0
  After NotebooksStore.open: rows=[]
  ```
  After this, `make add NOTEBOOK=coldslug PAPER=…` server-up POSTs to
  `/ui/api/notebooks/coldslug/papers` → 404 (no such notebook),
  surfaces "ERROR: REST call failed", and the operator hits the precise
  on-disk-vs-registry split D2 was supposed to fix. The repo's own
  `var/arxmcp/cache/notebooks.db` is already at `user_version=4` (from
  pre-m2 server runs), which is why
  `tests/test_make_targets.py::TestMakeInit::test_registers_notebook_in_sqlite`
  PASSES — the test is masking the regression by exercising a
  post-migration DB, not the fresh-clone path the synthesis explicitly
  targeted.
- **Proposed fix:** Two cleanest paths, pick one:
  1. In `_register_notebook_in_sqlite`, after the
     `CREATE TABLE IF NOT EXISTS notebooks (…)` succeeds, also set
     `PRAGMA user_version = 4` (the current `NotebooksStore.SCHEMA_VERSION`)
     — explicitly transferring schema-tracker ownership. The brittle
     coupling here is that `SCHEMA_VERSION` lives in
     `server/notebooks_store.py`; import it directly:
     `from server.notebooks_store import SCHEMA_VERSION as _NB_SCHEMA_VERSION`.
     Add a regression test that opens `NotebooksStore` after
     `_register_notebook_in_sqlite` on a fresh tmp_path DB and asserts
     the row survives.
  2. Simpler: rip out the in-line `CREATE TABLE` from
     `_register_notebook_in_sqlite` and instead reuse
     `NotebooksStore.open` + `store.create_notebook(...)`. This pays
     ~30ms of asyncio-event-loop spin in the CLI but eliminates the
     two-schema-creator hazard entirely. Likely the right answer for
     m2's risk surface.
- **Regression guard:** New test
  `tests/test_make_targets.py::TestMakeInit::test_row_survives_first_server_open`
  — fresh tmp_path DB, call `_register_notebook_in_sqlite('demo',
  db_path=…)`, then call `await NotebooksStore.open(db); rows =
  await store.list_notebooks()`, assert `len(rows) == 1`. This test
  WOULD HAVE FAILED on the current implementation.

### F2 — `tools/notebook_list_offline.py` mutates the file on a "list" call

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/notebook_list_offline.py:37`
- **What:** The Makefile recipe label is "list" (`make notebook-list`)
  and the implementation summary describes it as a server-down lister.
  But the implementation calls `await NotebooksStore.open(db_path)`,
  which at `server/notebooks_store.py:110-250` runs the FULL v0→v4
  migration sequence — including the destructive v0→v1 `DROP TABLE`
  plus three subsequent `ALTER TABLE ADD COLUMN` calls and PRAGMA
  bumps — on the operator's only copy of `notebooks.db`. An operator
  who runs `make notebook-list` to *inspect state* receives the side
  effect of having their schema force-upgraded to v4 and the
  `user_version` bumped, with no warning.
- **Why it matters:** Compounds F1. If `make init` ran cold (user_version=0,
  row present, 8-col schema), running `make notebook-list` server-down
  immediately afterward will trigger the same data-loss path as `make
  up`. Worse, the operator's mental model is "I just listed; the
  database is read-only by definition" — exactly the surprise the
  synthesis FM-7 hand-waved away ("Server-down uses `NotebooksStore`
  open which runs migrations on the local file. No additional
  mitigation needed").
- **Proposed fix:** Bypass `NotebooksStore.open` in the offline path.
  Open a raw `sqlite3.Connection`, run a single
  `SELECT slug, display_name FROM notebooks ORDER BY created_at DESC,
  slug ASC` wrapped in a `try/except sqlite3.OperationalError` (table
  missing → "no notebooks; run make init"). Reads are
  schema-version-agnostic for the two columns we display. ~15 LOC
  delta.
- **Regression guard:** New test
  `tests/test_make_targets.py::TestNotebookListOffline::test_user_version_unchanged_after_list`
  — pre-create a `notebooks.db` with `user_version=2` and a notebooks
  table containing one row, run `main([str(db)])`, assert
  `PRAGMA user_version == 2` afterward and the row is intact.

### F3 — `test_registers_notebook_in_sqlite` runs against shared real notebooks.db

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_make_targets.py:42-94, 96-127`
- **What:** The `fresh_slug` fixture cleans up by `shutil.rmtree(nb)`
  on `var/arxmcp/notebooks/m2-mk-test-zz` and DELETEs rows from the
  REAL `var/arxmcp/cache/notebooks.db`. The cleanup runs both
  pre-test (line 91) and post-test (line 94), but if pytest is
  SIGINT'd between setup and teardown, the operator's workstation
  has an orphan `m2-mk-test-zz` directory AND an orphan registry
  row. The `tools.notebook_init.run` call at line 100 uses the
  production-anchored `NOTEBOOKS_BASE` (from
  `tools/_notebook_common.py:33`) and writes to
  `var/arxmcp/cache/notebooks.db` via the
  `DEFAULT_DB_PATH = Path("var/arxmcp/cache/notebooks.db")` constant —
  no monkeypatch redirects either path. This is exactly the cross-test
  pollution shape the project has burnt itself on before (cf.
  `tests/conftest.py` autouse path-redirect fixture).
- **Why it matters:** The fixture comment at line 42 acknowledges
  "production-shape testing", but production-shape with shared
  destructive cleanup against the operator's real notebooks.db
  violates test hygiene. If the operator happens to have a real
  notebook slug `m2-mk-test-zz` (unlikely but not impossible), the
  teardown DELETEs their actual row. Less hypothetically: this test
  pattern blocks parallel test runs (`pytest -n auto`) since two
  workers will race on the same slug + DB.
- **Proposed fix:** Either (a) parametrize `notebook_init.run` to
  accept a `notebooks_base` override (a tiny `base: Path | None = None`
  parameter that threads through to `notebook_dir(slug, base=…)`)
  plus the existing `db_path` arg, and have the fixture pass
  `tmp_path` for both; or (b) accept the production-shape contract
  but rename the slug to something cryptographically unlikely (e.g.
  `m2-mk-test-{uuid4().hex[:8]}`) AND assert the slug isn't already
  in the DB before running, skipping the test otherwise.
- **Regression guard:** Same fix doubles as the guard — once
  redirected to tmp_path, the test no longer touches shared state.

### F4 — `resolve_contact_email` has no env-var-wins override hatch

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/_notebook_common.py:182-209`
- **What:** Priority chain documented in the docstring (lines 158-176)
  and implemented at line 190: SQLite ALWAYS wins over env. The
  rationale in the docstring is "sticky pref over shell ephemera",
  but the synthesis FM-3 explicitly anticipated the inverse pain
  point: "operators sometimes clear a pref (e.g. for environments
  where the env-var path should take over)" — and m2's answer is
  `set_setting("contact_email", "")` (empty string). Live-verified:
  `get_setting` returns `""` (empty), `resolve_contact_email` does
  `if persisted:` at line 191, which is False for empty string, so
  the env var DOES win in that case. So the escape hatch is "set the
  SQLite value to empty", which is undocumented at the helper-API
  level and orthogonal to the operator's intuition (operators expect
  shell env vars to override config files, the standard *NIX
  contract).
- **Why it matters:** An operator running a one-shot test with
  `ARXMCP_CONTACT_EMAIL=throwaway@example.com python -m
  tools.notebook_fetch demo` reasonably expects throwaway to win.
  Instead the persisted SQLite value wins silently. Discoverability:
  zero — no log message, no warning. The synthesis claims "Log an
  INFO message when env-var present but SQLite already has a value"
  (FM-3) but the implementation does NOT log this — `resolve_contact_email`
  goes straight to `return persisted` at line 192 with no detection
  of the env-var-also-set case.
- **Proposed fix:** Add a one-line `logger.info("SQLite contact_email
  shadowed env-var ARXMCP_CONTACT_EMAIL=%s", env_val)` when both are
  set (after the persisted check, before the return), as synthesis
  FM-3 prescribed. Cheap, contained, makes the silent-shadowing
  diagnosable.
- **Regression guard:** New test
  `tests/test_make_targets.py::TestResolveContactEmail::test_sqlite_shadows_env_var_logs_info`
  — set SQLite value + env var to distinct values, capture logs via
  `caplog.at_level(logging.INFO)`, call
  `resolve_contact_email(None, db_path=…)`, assert the INFO line is
  present.

### F5 — `_persist_email` and `_register_notebook_in_sqlite` are not atomic together

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/notebook_init.py:261-265`
- **What:** `run` (line 218) calls `_register_notebook_in_sqlite(slug,
  db_path=db_path)` at line 262 in a fresh sqlite3 connection scope
  that opens, writes, closes — then SEPARATELY at line 265
  `_persist_email(email, db_path=db_path)` opens a DIFFERENT fresh
  connection (via `set_setting` at `server/operator_settings.py:290`)
  to write `contact_email`. If `make init` is SIGINT'd between the
  two writes (Ctrl-C during the print() at line 199 or 215), the
  notebook is registered but the email is NOT persisted. The next
  `make add` server-up would work (slug exists) but `make ingest` or
  `tools/notebook_fetch.py` would raise NotebookError("no contact
  email available…") — partial state.
- **Why it matters:** AC1 promises three idempotent side effects.
  Atomic-on-failure is an implicit part of that promise; the
  synthesis does not address mid-call interruption. Low-severity in
  practice (operators retry on Ctrl-C), but flagged because the
  implementation summary line 22 explicitly claims "Idempotent at
  all three levels" without addressing partial-failure recovery.
- **Proposed fix:** Acceptable to defer with a docstring note that
  Ctrl-C between the two writes leaves partial state and re-running
  is idempotent. Alternatively, persist both via a single
  `OperatorSettingsStore` async session that holds the connection
  across both writes (notebooks-table INSERT + contact_email
  upsert). The simpler doc-only fix is the right call for m2's risk
  budget.
- **Regression guard:** Add a paragraph to the `run` docstring at
  `tools/notebook_init.py:218-232` noting that the two writes are not
  atomic and that re-running `make init NOTEBOOK=… EMAIL=…` is
  idempotent and recovers from partial state.

### F6 — `_open_sync`'s file_existed→chmod TOCTOU is silently single-process

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/operator_settings.py:197-228`
- **What:** Line 208 reads `file_existed = db_path.exists()`. Line 209
  opens the connection (creates the file if missing). Lines 216-227
  chmod 0o600 IFF `not file_existed`. Two concurrent processes both
  observing `file_existed=False` AND both racing `sqlite3.connect`:
  the second one's chmod silently overwrites the first's
  intentional perm (a contrived case — the file holds the same email
  in both branches). MORE realistically: a process other than
  `OperatorSettingsStore` could pre-create the file with perm 0644
  BETWEEN line 208 and line 216 (e.g. an unrelated `NotebooksStore.open`
  on a separate worker pre-creates `notebooks.db`). Result: `file_existed`
  returns False on the OperatorSettings side because Python's
  `path.exists()` is racy at the FS layer; OperatorSettings then
  chmods 0o600 a file `NotebooksStore` was actively using at 0o644.
  Not a security regression (0o600 is tighter than 0o644) but it
  contradicts the "never retroactively chmod" promise from D6.
- **Why it matters:** In single-workstation context (CLAUDE.md §4.1)
  the race window is microscopic and the consequence is benign
  tightening. The synthesis explicitly cites D6 / FM-4 as designed
  around the "operators may have set perms intentionally; silent
  tightening would be a surprise". The TOCTOU defeats that guarantee
  in the cross-process case.
- **Proposed fix:** Replace `db_path.exists()` + post-connect chmod
  with `os.open(db_path, O_RDWR | O_CREAT | O_EXCL, 0o600)` for the
  first-create path (atomic create-with-mode), then close that fd and
  pass the path to `sqlite3.connect`. If `OSError(EEXIST)` is raised,
  the file pre-existed and we skip the chmod entirely. Costs ~6 LOC
  and removes the TOCTOU.
- **Regression guard:** New test
  `tests/test_operator_settings.py::TestChmodOnFirstCreate::test_atomic_create_no_chmod_after_eexist`
  — pre-create the file with `os.open(..., O_CREAT | O_EXCL, 0o644)`
  in the test, then call `set_setting`, assert perms stayed 0o644.

### F7 — `notebook_list_offline.py:31` shadows the canonical DEFAULT_DB_PATH

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/notebook_list_offline.py:31` vs
  `server/operator_settings.py:91`
- **What:** Both modules define `DEFAULT_DB_PATH:
  Path("var/arxmcp/cache/notebooks.db")` as module-level constants.
  Two sources of truth for the canonical notebooks.db path; a future
  rename of the canonical location will break either module silently.
- **Why it matters:** Style-and-foot-gun finding. Drift risk is real
  but minor.
- **Proposed fix:** Import from `server.operator_settings` (or from
  `server.config` if that's the canonical seam): `from
  server.operator_settings import DEFAULT_DB_PATH`. Same
  late-import-cost concern doesn't apply here (the file already
  imports from `server.notebooks_store` at module load).

### F8 — `Makefile:1` .PHONY line is unreadable after m2 additions

- **Severity:** LOW
- **Source:** adversary
- **File:** `Makefile:1`
- **What:** Single 219-character line listing 19 targets, no line
  continuation. Diff hygiene + reviewer-ergonomics issue.
- **Why it matters:** Cosmetic. Flagged because m2 added three
  targets to a line already past the 80-char comfort threshold and
  the project convention elsewhere in the Makefile uses comments and
  spacing.
- **Proposed fix:** Split into multi-line `.PHONY` declarations grouped
  by section (one for first-time, one for everything-else), each on
  its own `.PHONY: ...` line.

## What was done well

- **Cardinal `PRAGMA user_version` non-touch (synthesis §3 D1 / FM-2)
  is RIGOROUSLY implemented.** No `PRAGMA user_version` write
  anywhere in `server/operator_settings.py` or
  `tools/notebook_init.py` (grep clean except docstring mentions).
  The in-table `__schema_version__` sentinel is correctly seeded by
  `INSERT OR REPLACE` at line 190-194, gated by a current-version
  check at line 185.
- **The cardinal regression test
  `test_user_version_NOT_touched_by_operator_settings` was verified
  to catch a real mutation.** Injecting `PRAGMA user_version = 99`
  into `_open_sync` caused the test predicate `assert user_version
  == 0` to fail. The guard is structurally sound.
- **BP1/BP2 hash discipline is held.** Live-ran
  `tests/test_server_tool_schema.py` + `tests/test_prompts.py` → 42
  passed; neither hash changed. `server/tools.py` and
  `server/prompts.py` UNCHANGED in the diff (verified).
- **ruff check . is clean.** Live-run, all checks passed.
- **Connection pragmas are mirrored verbatim** from `NotebooksStore`
  (`server/operator_settings.py:117-142`): WAL + synchronous=FULL +
  fullfsync=ON + busy_timeout=5000 + isolation_level=None. The
  comment block at 117-138 quotes the NotebooksStore reasoning
  verbatim and acknowledges the connection-scoped nature
  ("CONNECTION-scoped (does NOT persist), so it MUST be set on
  every open").
- **Reserved-key validation (`__schema_version__` refused at public
  API)** at `_check_key` (lines 231-244) closes the FM-2 corollary
  that the sentinel must not be writable from outside the module.
  Tests at `test_operator_settings.py:113-124` cover all three of
  `set/get/delete` against the reserved key.
- **The synthesis §3 D3 cross-package import direction is correctly
  honored:** `ingest/inspire_ingest.py` + `ingest/graph_ingest.py`
  import `from server.operator_settings import get_contact_email`
  (NOT from `tools._notebook_common`), avoiding the ingest/ →
  tools/ cross-direction that would have opened cycle risk.
- **`make add` Make recipe shell control-flow is correct** despite
  the `\`-line-continuation gauntlet: live-tested at /tmp/mkfail2/,
  the `[ -d … ] || { exit 1; }` does abort the recipe (joined as one
  shell invocation), AND the `grep -qxF` idempotency works on
  re-runs (verified: second run prints "no-op").
- **`make help` AC6 layout is precisely correct:** verified via
  `tests/test_make_targets.py::TestMakeHelp` which parametrizes 14
  pre-m2 targets and asserts each still appears in the output. The
  FIRST-TIME-before-EVERYTHING-ELSE positional invariant is also
  asserted (`test_first_time_appears_before_everything_else`).
- **`--register` / `--no-register` escape hatch** at
  `tools/notebook_init.py:115-127` is a clean default-ON design.
  Tests verify both branches.

## Recommended rectification order

1. **F1 (CRITICAL)** — first; this is the milestone-breaking bug.
   The fix likely involves `_register_notebook_in_sqlite` setting
   `PRAGMA user_version = NotebooksStore.SCHEMA_VERSION` after the
   `CREATE TABLE IF NOT EXISTS`. Add the regression test that
   reproduces the cold path. Re-run the full suite afterward.
2. **F2 (HIGH)** — `tools/notebook_list_offline.py` should not
   silently force-migrate. Cheapest fix is direct sqlite3 read,
   bypassing `NotebooksStore.open`. ~15 LOC delta.
3. **F4 (MEDIUM)** — emit the INFO log when SQLite shadows env-var.
   Cheap, contained, documented in the synthesis.
4. **F3 (MEDIUM)** — redirect the m2 test fixture to `tmp_path` for
   both `notebooks_base` AND `db_path`. ~25 LOC delta (touches
   `run`'s signature to thread the path through, and
   `_register_notebook_in_sqlite` already accepts `db_path`).
5. **F5 (MEDIUM, doc-only fix)** — docstring note on partial-state
   atomicity. ~5 LOC.
6. **F6 (MEDIUM)** — `O_CREAT | O_EXCL` first-create. ~6 LOC. Cheap
   but only paying off in cross-process race scenarios; safe to
   defer if m2 is time-pressured.
7. **F7, F8 (LOW)** — defer or close in a tidy-up commit.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
