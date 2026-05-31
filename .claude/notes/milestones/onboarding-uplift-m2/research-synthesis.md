# Research Synthesis — onboarding-uplift-m2

**Merged from:** research-brief-1.md (seam map + verbatim file:line evidence)
+ research-brief-2.md (failure-mode + sqlite/Make external sources).
**Generated:** 2026-05-31.
**Verdict:** INLINE — ~8 files, ~350 LOC main + tests + Makefile. No new
architecture once D-divergences resolved. Purely local. Both briefs
**concur on the central design landmine** (PRAGMA user_version is
file-scoped → cannot be shared between NotebooksStore and the new store).

---

## 1. The locked design

**New `server/operator_settings.py`** — a SQLite-backed key-value store
inside the same `notebooks.db` file as `NotebooksStore`. **Self-contained
migration discipline** via an in-table `__schema_version__` sentinel row
(NOT `PRAGMA user_version`, which `NotebooksStore` owns — see §3 D1).
Exposes BOTH:
- `class OperatorSettingsStore` with async `get` / `set` / `delete` for
  server-context callers (mirrors `NotebooksStore` shape).
- Module-level synchronous helpers (`get_setting(key, db_path) -> str |
  None`, `set_setting(key, value, db_path) -> None`) for CLI callers —
  open their own short-lived connection, no asyncio event-loop hazard.
- A purpose-specific `get_contact_email(db_path) -> str | None` thin
  wrapper, importable directly by `ingest/inspire_ingest.py` +
  `ingest/graph_ingest.py` (avoiding the `ingest/ → tools/` cross-package
  import R1 flagged — see §3 D3).

**`tools/_notebook_common.py` extension:** new `resolve_contact_email(arg:
str | None) -> str` helper. Priority chain: explicit `arg` → SQLite via
`server.operator_settings.get_contact_email(NOTEBOOKS_DB_PATH)` → env var
`ARXMCP_CONTACT_EMAIL` → raise `NotebookError` with a help message naming
`make init NOTEBOOK=... EMAIL=...` as the canonical fix.

**`tools/notebook_init.py` extension:** add optional `--email <addr>` CLI
arg + add a new `--register` flag (default ON) that performs an
`INSERT OR IGNORE INTO notebooks(slug, lancedb_path, created_at, ...)`
into `notebooks.db` via a direct synchronous SQLite write — making the
notebook server-up-discoverable immediately without requiring the server
to be running. **(§3 D2 resolution.)**

**Wire `resolve_contact_email` through 5 CLI fetch sites:**
- `tools/notebook_fetch.py:91` — replace bare `os.environ.get` check.
- `tools/recover_preambles.py:236` — same.
- `tools/arxiv_fetch.py:101` — `build_user_agent` already accepts an
  injected value; just update callers.
- `ingest/inspire_ingest.py:784` — import `get_contact_email` directly
  (not via tools/), use it as the priority-2 source after the explicit
  arg (which inspire_ingest itself accepts).
- `ingest/graph_ingest.py:775` — same.

**Makefile additions** (the new operator API, scoped per §3 D4 + D5):
- `make init NOTEBOOK=<slug> [EMAIL=<addr>]` — runs
  `tools/notebook_init.py <slug> [--email <addr>]` which scaffolds
  on-disk AND registers in SQLite AND persists EMAIL.
- `make add NOTEBOOK=<slug> PAPER=<id>` — if `/healthz` 200,
  `POST /ui/api/notebooks/<slug>/papers` with
  `{"arxiv_url": "https://arxiv.org/abs/<PAPER>"}`. If server DOWN
  (curl exit 7), append to `var/arxmcp/notebooks/<slug>/papers.txt`
  with idempotency (`grep -qxF || echo`). REST 404 NOT auto-fallback
  (clean error: "run make init first" — §3 D5 / FM-5).
- `make notebook-list` — if `/healthz` 200, curl `/ui/api/notebooks`
  and pipe to `jq` or a tiny formatter; else direct SQLite read via
  `python -c "from server.notebooks_store import ..."`.
- `make status` — **ALREADY EXISTS** (`Makefile:108`); m2 only verifies
  AC5 is met (no implementation change required for the target itself).
  R2 §"Existing `make status` target conflict" flagged this.
- `make help` — add a "FIRST TIME?" section at the top listing
  `bootstrap → init → add → ingest → up`. Existing block reorder is
  cosmetic (no removed/renamed targets per AC6).

**New tests:**
- `tests/test_operator_settings.py` — round-trip set/get/delete via BOTH
  async (`OperatorSettingsStore`) and sync (`get_setting`) APIs;
  schema-version sentinel survives reopen; concurrent reader/writer
  (cross-process); chmod 0600 file perm assertion; multi-call
  `set(k, v1); set(k, v2)` updates `updated_at`.
- `tests/test_make_targets.py` — execute each new Make target with
  `tmp_path` notebooks.db + mocked server (or real loopback), assert
  the right SQLite side effects + REST call + fallback behaviour.

---

## 2. Load-bearing facts (both briefs concur, live-verified)

- **`NotebooksStore` is the load-bearing template** (`server/notebooks_store.py`):
  - `_open_sync` pattern at lines 110-115: `sqlite3.connect(str(db_path),
    isolation_level=None, check_same_thread=False)` + four pragmas
    (`journal_mode=WAL`, `synchronous=FULL`, `fullfsync=ON`,
    `foreign_keys=ON`). **All four must be reproduced** in the new
    store. Comment at notebooks_store.py:120-133 explains: "synchronous=FULL:
    in WAL mode, NORMAL can roll back the last committed transaction on
    power loss; FULL adds a WAL sync after every commit → ACID-durable
    across power loss. fullfsync=ON: macOS only. … This is
    CONNECTION-scoped (it does NOT persist to a fresh connection), so it
    must be set here, on every open."
  - **`SCHEMA_VERSION = 4`** at line 75. **DO NOT bump.** `OperatorSettingsStore`
    uses its own in-table sentinel (§3 D1).
  - Migration discipline (verbatim, notebooks_store.py docstring): *"When
    adding a new version: append a new `if current_version < N:` block in
    `_open_sync` using `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` and
    bump SCHEMA_VERSION; do NOT drop existing tables."* — applies to
    `NotebooksStore`'s own migration sequence; `OperatorSettingsStore`
    creates its table independently.

- **`isolation_level=None`** pattern (both `cache_sqlite.py` and
  `notebooks_store.py`) → use explicit `BEGIN/COMMIT` rather than
  Python's implicit transactions. Adopt in new store.

- **`tools/_notebook_common.py` extension point:** new
  `resolve_contact_email` lands after `notebook_lancedb_path` and
  before `read_paper_ids_from_papers_txt` (R1 §2). Must raise
  `NotebookError` (not bare `RuntimeError`) per the module's error
  convention.

- **`tools/notebook_init.py` current shape** (R1 §4): single positional
  `slug` arg today. Side effects: validate slug, create dir, write
  templates. Idempotency gate: `if nb_dir.exists(): return 0`. **NO
  SQLite write today.** m2's `--email` + `--register` flags are
  additive.

- **REST endpoints `make add` + `make notebook-list` consume**:
  - `POST /ui/api/notebooks/{slug}/papers` (server/routes/notebooks.py:496):
    body `{"arxiv_url": ...}` (URL form, NOT bare paper_id — §3 D5),
    returns 201, 404, 409, 422. Use `curl -sf --fail-with-body --max-time 5`.
  - `GET /ui/api/notebooks` (server/routes/notebooks.py:240): response
    `list[dict[str, str]]` with 8 keys per row.

- **`/healthz` is the right server-up gate.** Always 200; never blocks.
  `curl -sf --max-time 2` is the right pattern (R2 §"curl health-check
  idiom"). NOT `/status` (which depends on warmup state) and NOT
  `/readyz` (which 503s on degraded).

- **The existing `make status` already implements up/down logic**
  (Makefile:108, both briefs concur). m2 does NOT need to touch it.
  AC5 is verified by a test, not by editing the target.

- **`/ui/api/notebooks/{slug}/papers` requires the notebook row in
  `notebooks.db`** (R1 §7); 404s otherwise. This is **load-bearing**
  for the §3 D2 decision (yes, `make init` must register).

- **File perms on `notebooks.db`:** today 0644 (world-readable on
  default umask). R2 FM-4: the new store opens the file with `chmod
  0600` on first create. **This is a NEW tightening over today's
  state** — acknowledge in the implementation summary; do NOT
  retroactively chmod existing files (avoid surprise behaviour for
  in-flight deployments).

- **BP1/BP2 hashes** stay unchanged:
  `EXPECTED_TOOL_SCHEMA_SHA256 = c7df4c5c…d13375`
  (`tests/test_server_tool_schema.py:94-96`); `EXPECTED_BP1_SHA256 =
  483344e3…58959bc` (`tests/test_prompts.py:649-651`). Run both files
  post-implementation.

---

## 3. Divergences resolved (orchestrator synthesis note)

### D1 — Schema migration strategy: in-table sentinel vs shared `user_version`

R1 recommends extending `NotebooksStore._open_sync` with a v4→v5 migration
block that adds the `operator_settings` table; the file's `user_version`
becomes the single source of truth. R2 recommends an in-table
`__schema_version__` sentinel row inside `operator_settings`; the new
store NEVER touches `PRAGMA user_version`.

**RESOLVED → R2 wins. In-table sentinel.**

Reasoning:
1. **Layering.** R2 correctly observes that requiring `NotebooksStore.open()`
   to run before `OperatorSettingsStore.open()` is a coupling violation —
   CLI tools (`make init EMAIL=...`) open `OperatorSettingsStore` cold,
   often without ever instantiating `NotebooksStore`.
2. **Risk asymmetry.** If `OperatorSettingsStore` ever accidentally
   touched `PRAGMA user_version`, it would clobber `NotebooksStore`'s
   v0→v4 sequence and risk data loss on the notebooks table (a
   CRITICAL failure mode per R2 FM-2). The in-table sentinel makes this
   regression structurally impossible — the new code path has no
   `PRAGMA user_version` line at all.
3. **Idempotency.** `CREATE TABLE IF NOT EXISTS operator_settings(...)`
   is already idempotent. The sentinel row tracks intra-table migrations
   independently. `NotebooksStore`'s v4→v5 sequence (if ever needed) is
   unaffected.

**Implementation:** `OperatorSettingsStore._open_sync` runs
`CREATE TABLE IF NOT EXISTS operator_settings (key TEXT PRIMARY KEY,
value TEXT NOT NULL, updated_at TEXT NOT NULL)`, then `SELECT value FROM
operator_settings WHERE key = '__schema_version__'`. If absent →
`INSERT INTO operator_settings(key, value, updated_at) VALUES
('__schema_version__', '1', <iso-utc>)`. Future versions: `if current < 2:
ALTER TABLE … ; UPDATE operator_settings SET value='2' WHERE
key='__schema_version__'`.

### D2 — Does `make init` register the notebook in `notebooks.db::notebooks`?

R1 explicitly asks the question. R2 implies yes via FM-5 (the
clean-error 404 on server-up `make add`).

**RESOLVED → YES. `make init` writes BOTH the on-disk scaffold AND a
`notebooks.db::notebooks` row via direct SQLite `INSERT OR IGNORE`.**

Reasoning:
1. **AC3 viability.** "`make add NOTEBOOK=demo PAPER=...` works whether
   server up or down" — server-up path POSTs to
   `/ui/api/notebooks/demo/papers`, which 404s if no row exists in
   `notebooks.db`. Without `make init` registering, the user must
   either separately curl `POST /ui/api/notebooks` (which requires the
   server up) or wait for m3's `make repair-registry`. Both defeat the
   m2 ergonomic goal.
2. **No server dependency.** Direct SQLite `INSERT OR IGNORE` keeps
   `make init` fully offline-capable (D1 alignment).
3. **Idempotency.** `INSERT OR IGNORE` is naturally idempotent; second
   `make init NOTEBOOK=demo` is a no-op for the SQLite path.

**Implementation:** `tools/notebook_init.py` gains a new `--register`
flag (default ON; `--no-register` to skip). When ON, after the on-disk
scaffold completes, it opens `notebooks.db` via a fresh sync sqlite3
connection (same pragmas as `NotebooksStore`) and runs `INSERT OR
IGNORE INTO notebooks(slug, display_name, lancedb_path, created_at,
notebook_kind, parse_status, parse_error, parsed_html_path) VALUES
(?, '', ?, ?, 'arxiv', 'skipped', '', '')`. The `lancedb_path` is the
per-notebook path under `var/arxmcp/notebooks/<slug>/lancedb` (matches
the live registry pattern we saw mid-session in the manual
registration). Per D2 (corpus stays at shared level), this path is
recorded for the registry's information BUT the actual ingest goes to
the shared global corpus (no per-notebook lancedb gets written by `make
add`). Future m3 work may align this — out of scope.

### D3 — Cross-package import: `ingest/` files reading `resolve_contact_email`

R1 flags an ingest/ → tools/ cross-direction import; today `tools/`
imports `ingest/` but not the reverse. R2 doesn't dwell.

**RESOLVED → R1 wins. Expose a module-level
`server.operator_settings.get_contact_email(db_path)` function that
returns the SQLite value (or None). `ingest/` files import THIS
directly; `tools/_notebook_common.py::resolve_contact_email` thin-wraps
it.**

Reasoning:
1. **Existing import direction.** `ingest/` files already import from
   `server/` (e.g., `server.config`). Adding `from server.operator_settings
   import get_contact_email` keeps that direction.
2. **Avoids circular risk.** `tools/notebook_fetch.py` imports
   `ingest.ar5iv_fetch` today. If we then add `ingest/inspire_ingest.py`
   → `tools._notebook_common`, we open the door to import-time cycles.
3. **Single responsibility.** `server.operator_settings` is the
   canonical SQLite reader for operator-pref values. `tools/_notebook_common`'s
   `resolve_contact_email` is the CLI-facing priority chain (explicit
   arg → SQLite → env → raise). Each module owns its semantic.

### D4 — `make status` already does up/down; verify AC5 by test only

Both briefs concur. **RESOLVED → no Make change for `status`. AC5 is
verified by a small integration test that exercises both up and down
paths.**

### D5 — `make add` paper-id vs URL semantic + 404 handling

R2 flagged: the REST endpoint takes `arxiv_url`; CLI takes bare `PAPER=`.
Also: 404 vs connection-refused must be distinguished.

**RESOLVED → Make constructs `https://arxiv.org/abs/$(PAPER)` for the
REST body. 404 (server-up + notebook-missing) is a CLEAN error with the
remediation hint, NOT a silent file-write fallback. Only `curl` exit 7
(connection refused → server is down) triggers the papers.txt
fallback.**

Reasoning: silent fallback on 404 would create an orphan papers.txt
entry that the user (and the server) can't see — exactly the
on-disk-vs-registry split the milestone is trying to fix.

### D6 — File permissions (chmod 0600) on `notebooks.db`

R2 FM-4 recommends `os.chmod(db_path, 0o600)` on first create. R1
silent.

**RESOLVED → adopt R2's recommendation, with a constraint: only chmod
on FILE CREATE (i.e., when the file didn't exist before
`OperatorSettingsStore.open()`). Never retroactively chmod an existing
file (could surprise operators of in-flight deployments who
intentionally set perms).**

Implementation: `db_path.exists()` before `sqlite3.connect`; if False →
post-connect, `os.chmod(db_path, 0o600)`. Add a test that creates a
fresh db_path and asserts `(db_path.stat().st_mode & 0o777) == 0o600`.

---

## 4. Failure modes → required handling (from R2)

- **FM-1 (write-lock contention):** set
  `PRAGMA busy_timeout=5000` explicitly in the new store; rely on
  WAL's reader/writer concurrency. Document the failure mode in the
  store's docstring.
- **FM-2 (schema-version drift — CRITICAL):** SOLVED by §3 D1
  (in-table sentinel; never touch `PRAGMA user_version`). Test:
  `OperatorSettingsStore.open()` followed by
  `NotebooksStore.open()` on the same file → both report their own
  version cleanly; no crashes; existing `notebooks` table data
  intact.
- **FM-3 (stale email priority):** SQLite WINS over env var. Log an
  INFO message when env-var present but SQLite already has a value
  (so operators see "I expected env to override but SQLite has it").
  Document this in the resolve_contact_email docstring.
- **FM-4 (PII leak via 0644):** SOLVED by §3 D6 (chmod 0600 on
  create). Test included.
- **FM-5 (`make add` 404 vs connection-refused):** SOLVED by §3 D5
  (curl exit 7 → fallback; HTTP 404 → clean error).
- **FM-6 (`make add` offline + notebook dir missing):** Make recipe
  guards with `[ -d var/arxmcp/notebooks/$(NOTEBOOK) ]` before the
  papers.txt append; clean error pointing at `make init`.
- **FM-7 (`make notebook-list` old schema):** Server-up uses REST
  (server already migrated). Server-down uses `NotebooksStore` open
  (which runs migrations on the local file). No additional
  mitigation needed.
- **FM-8 (server env-var rejection):** No conflict.
  `ARXMCP_CONTACT_EMAIL` continues to be rejected by the server's
  strict-typo check (m1 carve-out). CLI tools read it independently
  (now via `resolve_contact_email`). No server-side change.
- **FM-9 (REST 5xx during `make add`):** `curl -sf
  --fail-with-body` surfaces the body on non-2xx. Clean error, no
  fallback (would create a stale papers.txt entry on transient
  server error).

---

## 5. Acceptance criteria — restated with implementation handles

- **AC1** — `make init NOTEBOOK=demo EMAIL=me@example.com` creates
  scaffold + persists email + registers in notebooks.db; idempotent.
  Test: `test_make_init_idempotent_sqlite_and_disk` exercises both
  the first-call and the second-call. SQLite check: `SELECT * FROM
  notebooks WHERE slug='demo'` returns the row. Operator settings:
  `SELECT value FROM operator_settings WHERE key='contact_email'`
  returns the email.
- **AC2** — after AC1, `python tools/notebook_fetch.py demo`
  succeeds without `ARXMCP_CONTACT_EMAIL` set. Test:
  `test_resolve_contact_email_sqlite_priority` mocks the env unset
  and asserts the SQLite value is read.
- **AC3** — `make add NOTEBOOK=demo PAPER=2401.00001` works
  server-up and server-down. Test:
  `test_make_add_rest_path_server_up` + `test_make_add_file_path_server_down`.
  Idempotency: re-adding present paper is a no-op (REST path uses
  409-as-noop pattern; file path uses `grep -qxF`).
- **AC4** — `make notebook-list` works server-up and server-down.
  Test: `test_make_notebook_list_dual_mode`.
- **AC5** — `make status` works up and down. Test:
  `test_make_status_dual_mode` (verifies existing target's
  behaviour without modifying it).
- **AC6** — `make help` has FIRST-TIME section; no removed/renamed
  targets. Test: `test_make_help_first_time_section_present` greps
  the help output for "FIRST TIME" + verifies every pre-m2 target
  name still appears.
- **AC7** — `make test` green; `ruff check .` clean.
- **AC8** — `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_BP1_SHA256` UNCHANGED. Verified by post-impl run of
  `tests/test_server_tool_schema.py` + `tests/test_prompts.py`.
- **AC9** — Regression tests in both `tests/test_operator_settings.py`
  + `tests/test_make_targets.py`.

---

## 6. Implementation order

1. `server/operator_settings.py` — class + module-level
   `get_setting/set_setting/get_contact_email` + chmod 0600 on
   create + in-table sentinel. ~120 LOC.
2. `tests/test_operator_settings.py` — round-trip + concurrency +
   chmod + schema-sentinel sanity. ~150 LOC.
3. `tools/notebook_init.py` — `--email` + `--register` flags +
   SQLite `INSERT OR IGNORE` direct write. ~30 LOC added.
4. `tools/_notebook_common.py` — `resolve_contact_email`. ~25 LOC.
5. **5 fetch-tool wire-throughs** — minimal edits to:
   - `tools/notebook_fetch.py:91`
   - `tools/recover_preambles.py:236`
   - `tools/arxiv_fetch.py:101` (callers, not the function itself)
   - `ingest/inspire_ingest.py:784` (direct `get_contact_email`)
   - `ingest/graph_ingest.py:775` (direct `get_contact_email`)
   ~40 LOC across 5 files.
6. `Makefile` — add `init`, `add`, `notebook-list` targets +
   `make help` FIRST-TIME section. Existing `status` UNCHANGED.
   `.PHONY` extended. ~50 LOC.
7. `tests/test_make_targets.py` — run each new target via
   `subprocess.run` against a tmp_path notebooks.db; verify side
   effects. ~200 LOC.
8. Verify BP1/BP2 hashes unchanged + `make test` green + ruff clean.

---

## 7. Open questions

**None blocking.** All three R1 + all three R2 open questions
resolved in §3 D1-D6.

## 8. External writes required

**None.** Purely local. Both briefs concur.
