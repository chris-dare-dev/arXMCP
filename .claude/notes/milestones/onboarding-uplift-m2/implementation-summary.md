# Implementation Summary — onboarding-uplift-m2

**Summary:** New `server/operator_settings.py` SQLite key-value store co-resident
in `notebooks.db` with an in-table `__schema_version__` sentinel (decoupled from
`NotebooksStore`'s `PRAGMA user_version`); new `tools/_notebook_common.py::
resolve_contact_email` priority chain (explicit arg → SQLite → env var → raise);
`tools/notebook_init.py` extended with `--email` + `--register` flags (registers
the notebook row in `notebooks.db` so `make add` doesn't 404); 5 fetch-tool
wire-throughs (notebook_fetch.py, recover_preambles.py, arxiv_fetch.py,
inspire_ingest.py, graph_ingest.py); 3 new Make targets (`init`, `add`,
`notebook-list`) + `make help` FIRST-TIME reorg; new `tools/notebook_list_offline.py`
helper backing the server-down path of `make notebook-list`.

**Commit range:** `40f3552febaa921140a650397a5cf4488dab250d..<HEAD after feat>`

## Acceptance criteria status

- [x] **AC1** `make init NOTEBOOK=demo EMAIL=me@example.com` creates scaffold,
      writes `notebooks.db::notebooks` row via `INSERT OR IGNORE`, persists email
      to `operator_settings`. Idempotent at all three levels. Regression:
      `tests/test_make_targets.py::TestMakeInit` (6 tests).
- [x] **AC2** `python tools/notebook_fetch.py demo` works without
      `ARXMCP_CONTACT_EMAIL` set in the env (SQLite value is read via
      `resolve_contact_email`). Regression:
      `tests/test_make_targets.py::TestResolveContactEmail::test_sqlite_wins_over_env_var`
      and 3 sibling tests.
- [x] **AC3** `make add NOTEBOOK=demo PAPER=2401.00001` server-up (POST to
      `/ui/api/notebooks/<slug>/papers`) and server-down (append to papers.txt).
      Per m2 synthesis §3 D5, REST 404 / 5xx is a clean error — NOT auto-fallback
      (would create orphan rows). Verified via Make dry-run + the Make recipe
      itself; an integration test against a real server is out of m2 scope.
- [x] **AC4** `make notebook-list` works server-up (curl + python -c) and
      server-down (via `tools/notebook_list_offline.py`). Regression:
      `tests/test_make_targets.py::TestNotebookListOffline` (3 tests).
- [x] **AC5** `make status` works server-up and server-down. **UNCHANGED in m2** —
      the existing `Makefile:108` target already implements both paths via
      `curl /status | python tools/status_line.py` with an `else: echo DOWN`
      branch. Verified to satisfy the AC without modification.
- [x] **AC6** `make help` has FIRST-TIME? section listing
      `bootstrap → init → add → notebook-list → ingest → up`. EVERYTHING ELSE
      section below preserves every pre-m2 target (no removed/renamed targets).
      Regression: `tests/test_make_targets.py::TestMakeHelp` (4 tests with 14
      parametrized cases — verifies the new section, the order, and every
      pre-m2 target name still appears).
- [x] **AC7** `make test` green (3 pre-existing m2-unrelated failures), `ruff
      check .` clean.
- [x] **AC8** `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED —
      verified by `tests/test_server_tool_schema.py` + `tests/test_prompts.py`
      (42 tests pass). Plus a new structural guard
      (`tests/test_make_targets.py::TestNoMCPSurfaceTouch`) that asserts the new
      m2 modules don't `import` from `server.tools` or reference `ALL_TOOLS`.
- [x] **AC9** 56 new regression tests across two new files:
      `tests/test_operator_settings.py` (20 tests) +
      `tests/test_make_targets.py` (36 tests).

## File deltas

**New files (3):**

- **`server/operator_settings.py`** (~330 LOC) — `OperatorSettingsStore` async
  class + module-level sync helpers (`get_setting`, `set_setting`,
  `delete_setting`, `get_contact_email`). In-table `__schema_version__` sentinel
  (synthesis §3 D1). WAL + `synchronous=FULL` + `fullfsync=ON` +
  `busy_timeout=5000` (mirrors `NotebooksStore`'s pragmas). `chmod 0o600` on
  first file create (synthesis §3 D6 / FM-4). Reserved-key validation
  (`__schema_version__` can't be written through the public API).
- **`tools/notebook_list_offline.py`** (~70 LOC) — server-down lister called by
  `make notebook-list`'s `else` branch. Uses `NotebooksStore` (which auto-runs
  migrations on open). Friendly "does not exist; run `make init`" message when
  the DB hasn't been created yet.
- **`tests/test_operator_settings.py`** (~300 LOC) — 20 tests covering
  round-trip, key validation, async+sync API parity, sentinel discipline,
  user_version non-touch (CRITICAL: cardinal invariant from synthesis §3 D1
  / FM-2 — the test that proves `OperatorSettingsStore` doesn't clobber
  `NotebooksStore`'s migration tracker), coexistence with `NotebooksStore` on
  the same file, chmod 0o600 on first create + NOT retroactively, default
  DB path constant.
- **`tests/test_make_targets.py`** (~360 LOC) — 36 tests covering AC1, AC2, AC4,
  AC6 + the `tools/notebook_init.py` CLI argparse surface + the AC8
  no-MCP-surface-touch structural guard.

**Modified files (8):**

- **`tools/_notebook_common.py`** — added `resolve_contact_email(arg,
  *, db_path=None)` after `notebook_lancedb_path`. Lazy-imports `server.
  operator_settings` to keep the module-import cost light + avoid hard
  dependency at import time.
- **`tools/notebook_init.py`** — added `--email <addr>` + `--register` /
  `--no-register` flags. New `_register_notebook_in_sqlite(slug, db_path)`
  helper performs `INSERT OR IGNORE INTO notebooks(...)` via a fresh sync
  sqlite3 connection (matches `NotebooksStore`'s 4 pragmas + 5s busy_timeout
  — explicitly does NOT touch `PRAGMA user_version`, which `NotebooksStore`
  owns). New `_persist_email` helper calls `set_setting` from m2. The original
  scaffold path is unchanged; the new behaviours are additive.
- **`tools/notebook_fetch.py`** — replaced `if not os.environ.get(...)` check
  at line 91 with `resolve_contact_email(None)`. Dropped now-unused `import os`.
- **`tools/recover_preambles.py`** — same pattern at line 236.
- **`tools/arxiv_fetch.py`** — extended `build_user_agent` to consult SQLite
  before the env-var fallback (the SHARED library that fronts every fetch
  CLI). Priority chain: explicit arg → SQLite → env → raise.
- **`ingest/inspire_ingest.py`** — direct `from server.operator_settings import
  get_contact_email` (synthesis §3 D3 — avoids `ingest/ → tools/` cross-package
  import). `contact_email = get_contact_email() or os.environ.get(...)`.
  Updated the error message to point at `make init NOTEBOOK=...`.
- **`ingest/graph_ingest.py`** — identical pattern at line 775.
- **`Makefile`** — added `init`, `add`, `notebook-list` targets to `.PHONY` and
  recipes. `NOTEBOOK ?=`, `EMAIL ?=`, `PAPER ?=` declared. `make help` block
  reorganised with FIRST-TIME and EVERYTHING-ELSE sections (no targets
  removed; `make ingest` deduplicated from the second section since it now
  appears in FIRST-TIME).

**No other files touched.** `server/tools.py`, `server/prompts.py`,
`server/notebooks_store.py` (its `SCHEMA_VERSION` stays at 4; m2 doesn't touch
it) — all UNCHANGED.

## New / changed test paths

- `tests/test_operator_settings.py` — 20 new tests.
- `tests/test_make_targets.py` — 36 new tests.
- No existing test file modified.

## Deviations from the synthesis

None. All design decisions adopted:

- **D1** (in-table sentinel, not shared `PRAGMA user_version`) — implemented
  in `server/operator_settings.py::_apply_migrations`. Cardinal regression
  guard: `tests/test_operator_settings.py::TestSchemaSentinel::test_user_version_NOT_touched_by_operator_settings`.
- **D2** (yes, `make init` registers in `notebooks.db`) — implemented via the
  new `--register` flag (default ON). Direct synchronous SQLite write; no
  server dependency.
- **D3** (`ingest/` imports from `server.operator_settings`, NOT
  `tools._notebook_common`) — `inspire_ingest.py` and `graph_ingest.py` use
  the direct `server.operator_settings.get_contact_email` import. Avoids
  the `ingest/ → tools/` cross-package direction.
- **D4** (`make status` already does up/down — no Make change needed) — verified
  via reading the existing recipe; no code change in this milestone.
- **D5** (`make add` constructs `https://arxiv.org/abs/<PAPER>` for REST; 404
  is a clean error, only curl exit 7 triggers the papers.txt fallback) —
  implemented in the Makefile recipe.
- **D6** (chmod 0o600 on FIRST create only; never retroactively) — implemented
  in `_open_sync`. Tests:
  `tests/test_operator_settings.py::TestChmodOnFirstCreate` (2 tests).

## External writes required

**None.** Purely local. The synthesis predicted zero external writes; this holds.
No `git push`, no PR, no ticket, no infra mutation, no external API call.
