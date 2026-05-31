# Research Brief — onboarding-uplift-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T03:45:00Z

---

## In-codebase context

### 1. `server/notebooks_store.py` — the load-bearing template

**Class shape** (`server/notebooks_store.py:78–95`):
```python
class NotebooksStore:
    def __init__(self, db_path: Path, connection: sqlite3.Connection) -> None:
        self._db_path = db_path
        self._conn = connection
        self._lock = asyncio.Lock()
```
Not constructed directly — open via async classmethod `open(db_path)`.

**`_open_sync` pattern** (`server/notebooks_store.py:110–115`):
```python
conn = sqlite3.connect(
    str(db_path),
    isolation_level=None,
    check_same_thread=False,
)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=FULL")
conn.execute("PRAGMA fullfsync=ON")
conn.execute("PRAGMA foreign_keys = ON")
```
Note: `synchronous=FULL` + `fullfsync=ON` because notebooks.db holds
**non-regenerable user state** (`server/notebooks_store.py:117–136`).

**Schema-version discipline** (`server/notebooks_store.py:141–179`):
- Uses `PRAGMA user_version` (integer) as the schema version counter.
- v0→v1: DROP-AND-RECREATE (acceptable on empty DB).
- v1→v2 through v3→v4: ADDITIVE-only (`ALTER TABLE ADD COLUMN` + `CREATE TABLE IF NOT EXISTS`). 
- Key invariant (verbatim comment, line 62–66): "When adding a new version: append a new `if current_version < N:` block in `_open_sync` using `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` and bump SCHEMA_VERSION; do NOT drop existing tables."
- `SCHEMA_VERSION: int = 4` (line 75).

**Current `notebooks` table columns (v4 state)**:
`slug TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '', lancedb_path TEXT NOT NULL, created_at TEXT NOT NULL, notebook_kind TEXT NOT NULL DEFAULT 'arxiv', parse_status TEXT NOT NULL DEFAULT 'skipped', parse_error TEXT NOT NULL DEFAULT '', parsed_html_path TEXT NOT NULL DEFAULT ''`

**Thread-safety**: connection is cached (one per `NotebooksStore` instance). All public methods are `async` and offload SQL via `asyncio.to_thread`, serialized through `asyncio.Lock`. The store is designed for cross-process use (WAL mode allows concurrent readers from CLI while server writes).

**`OperatorSettingsStore` mirror requirements:**
- New file: `server/operator_settings.py`
- Same `open(db_path)` classmethod pattern
- Same `asyncio.to_thread` + `asyncio.Lock` pattern
- Same `PRAGMA journal_mode=WAL` + `synchronous=FULL` + `fullfsync=ON`
- Bump `SCHEMA_VERSION` in `notebooks_store.py` from 4 to 5 with ADDITIVE migration creating `operator_settings` table, OR use a separate SCHEMA_VERSION in `operator_settings.py` and track `user_version` there. **IMPORTANT**: `user_version` is per-DATABASE-FILE, not per-table. Since both live in the same `notebooks.db`, a single file, the `OperatorSettingsStore.open()` must reconcile with `NotebooksStore`'s v4 schema. Recommended: `OperatorSettingsStore` checks `user_version >= 5` and adds the `operator_settings` table in a v4→v5 migration block INSIDE `NotebooksStore._open_sync` — keeping a single migration sequence in the file that owns the DB.

**CRITICAL DESIGN QUESTION**: The brief says `OperatorSettingsStore` "lives in the same notebooks.db file" (single SQLite file, two tables). But `user_version` is per-file, and both stores share it. The cleanest solution: add the v4→v5 migration block to `NotebooksStore._open_sync` (adds `operator_settings` table), and let `OperatorSettingsStore` be a **synchronous** (not async) store that opens its own connection — since CLI tools call it from synchronous contexts and the table is a simple key-value store. This avoids the asyncio event-loop hazard from CLI callers.

### 2. `tools/_notebook_common.py` — current shape

**`NotebookError`** (`tools/_notebook_common.py:50–55`):
```python
class NotebookError(RuntimeError):
    """Raised by any notebook helper when a precondition fails.
    Prefer this over `assert` per CLAUDE.md §4.7..."""
```

**`validate_slug`** (`tools/_notebook_common.py:58–76`):
```python
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")

def validate_slug(slug: str) -> None:
    if not isinstance(slug, str):
        raise NotebookError(...)
    if not SLUG_RE.fullmatch(slug):
        raise NotebookError(...)
```
Constraint: **3–31 chars total** (1 letter start + 2–30 alphanumeric/hyphen).

**`notebook_dir`** (`tools/_notebook_common.py:79–123`): validates slug, rejects symlinks at `nb_base/slug`, checks containment. Returns `Path`. Accepts `base: Path | None` for tests.

**Other helpers**: `notebook_lancedb_path`, `read_paper_ids_from_papers_txt`, `fetch_raw_tex_if_missing`.

**`resolve_contact_email(arg)` insertion point**: after line 123 (after `notebook_dir` and `notebook_lancedb_path`, before `read_paper_ids_from_papers_txt`). No existing email-resolution pattern exists in `_notebook_common.py` — this is purely new. The helper's signature per the brief: `resolve_contact_email(arg: str | None) -> str`. Must raise `NotebookError` (not `RuntimeError`) to stay consistent with the module's error convention.

**IMPORTANT**: `resolve_contact_email` will import `OperatorSettingsStore` to read from SQLite. This creates a dependency from `tools/_notebook_common.py` → `server/operator_settings.py`. That is fine IF `operator_settings.py` has NO server-side asyncio imports at module level. It MUST be a synchronous-capable module (the `_open_sync` pattern means the CLI can call `OperatorSettingsStore.get_sync(key)` without an event loop). Design `OperatorSettingsStore` with a synchronous fallback for CLI callers — or expose a standalone module-level `get_setting(key)` function that opens a fresh synchronous connection without requiring an event loop.

### 3. `ARXMCP_CONTACT_EMAIL` read sites (exhaustive)

All sites read the env var via `os.environ.get("ARXMCP_CONTACT_EMAIL")`:

| File | Line | Pattern | Refactor needed? |
|---|---|---|---|
| `tools/arxiv_fetch.py` | 101 | `email = contact_email or os.environ.get("ARXMCP_CONTACT_EMAIL")` | YES — `build_user_agent(contact_email)` accepts injected value; wire `resolve_contact_email` at callers |
| `tools/notebook_fetch.py` | 91 | `if not os.environ.get("ARXMCP_CONTACT_EMAIL"):` → raises `NotebookError` | YES — replace env check with `resolve_contact_email(None)` at `run()` entry |
| `tools/recover_preambles.py` | 236 | `if not os.environ.get("ARXMCP_CONTACT_EMAIL"):` → raises `NotebookError` | YES — same pattern as notebook_fetch |
| `ingest/inspire_ingest.py` | 784 | `contact_email = os.environ.get("ARXMCP_CONTACT_EMAIL")` → stderr + exit 2 | PARTIAL — `inspire_ingest.py` is in `ingest/` not `tools/`; importing from `tools._notebook_common` is a cross-package import. See below. |
| `ingest/graph_ingest.py` | 775 | `contact_email = os.environ.get("ARXMCP_CONTACT_EMAIL")` → stderr + exit 2 | PARTIAL — same cross-package concern |

**Cross-package import concern for `ingest/` files**: `ingest/inspire_ingest.py` and `ingest/graph_ingest.py` currently don't import from `tools/`. Adding `from tools._notebook_common import resolve_contact_email` is a new dependency. Given that `tools/` is a dev-utilities package (not a production server package), this is acceptable for this codebase — but the implementer should verify no circular imports result. Alternative: expose `resolve_contact_email` via a thin `server/operator_settings.py` helper function that has no `tools/` dependency.

**`tools/arxiv_fetch.py:94–107` verbatim** (the shared library called by all fetch paths):
```python
def build_user_agent(contact_email: str | None = None) -> str:
    email = contact_email or os.environ.get("ARXMCP_CONTACT_EMAIL")
    if not email:
        raise RuntimeError(
            "ARXMCP_CONTACT_EMAIL is required (arXiv TOS §3 — politeness contract). "
            "Export it in your shell before running any tool that hits arxiv.org."
        )
    return ARXIV_USER_AGENT_TEMPLATE.format(email=email)
```
`build_user_agent` already accepts an injected `contact_email` arg — the refactor for `tools/arxiv_fetch.py` is: callers pass the resolved value (from `resolve_contact_email`) rather than `None`. The env-var fallback in `build_user_agent` itself can remain as a belt-and-braces final fallback.

### 4. `tools/notebook_init.py` — current shape

**CLI args** (`tools/notebook_init.py:69–78`): single positional arg `slug`. No `--email` arg today.

**Side effects** (`tools/notebook_init.py:81–104`):
- `validate_slug(slug)` 
- `notebook_dir(slug)` — constructs path, validates slug + symlink safety
- `if nb_dir.exists(): return 0` — **idempotency gate is on-disk dir existence only**
- Creates `nb_dir`, writes `papers.txt` + `queries.json` templates
- Exit 0 on both "created" and "already exists"

**No SQLite side effect today**: `notebook_init.py` does NOT touch `notebooks.db` at all — it only creates the on-disk scaffold. The `notebooks` table row is created by `POST /ui/api/notebooks` (the REST endpoint). These are currently separate operations.

**`make init` must call BOTH**: per AC1, `make init NOTEBOOK=demo EMAIL=me@example.com` creates the scaffold AND persists the email. The brief says "calls `python tools/notebook_init.py <slug>`". But for SQLite registration of the notebook itself: `notebook_init.py` does NOT register in `notebooks.db`. The brief text only says it writes EMAIL to `operator_settings` — not that it registers the notebook.

**OPEN QUESTION (see below)**: Should `make init` also register the notebook in `notebooks.db::notebooks`? The brief is silent on this. The existing on-disk vs SQLite gap is explicitly deferred to m3 (`make repair-registry`). For AC2 to work (`make add NOTEBOOK=demo PAPER=id` POSTs to `/ui/api/notebooks/<slug>/papers`), the notebook must be registered in `notebooks.db` FIRST — otherwise `add_paper` returns 404. This means either (a) `make init` must also call the equivalent of `POST /ui/api/notebooks` (via SQLite direct write or curl), or (b) `make add` has a different offline path that writes to `papers.txt` only (bypassing the SQLite FK requirement). The brief states the server-down path for `make add` is: "fallback to writing the paper-id to `var/arxmcp/notebooks/<slug>/papers.txt`". That means the offline path avoids SQLite entirely. Only the server-up path (REST POST) requires the notebook row to exist.

### 5. REST surface (read-side)

**`GET /ui/api/notebooks`** (`server/routes/notebooks.py:240–245`):
- Handler: `list_notebooks`
- Response: `list[dict[str, str]]` — list of notebook rows with `slug, display_name, lancedb_path, created_at, notebook_kind, parse_status, parse_error, parsed_html_path`

**`GET /ui/api/notebooks/{slug}/papers`** (`server/routes/notebooks.py:470–493`):
- Handler: `list_papers`
- Response: `list[dict[str, str]]` — `[{"paper_id": ..., "added_at": ...}]`
- 404 if notebook not found; 422 on bad slug

**`POST /ui/api/notebooks/{slug}/papers`** (`server/routes/notebooks.py:496–548`):
- Handler: `add_paper`
- Body: `{"arxiv_url": "<url>"}` — accepts `https://arxiv.org/abs/<id>` and `https://ar5iv.labs.arxiv.org/html/<id>` forms
- Response: `{"slug": ..., "paper_id": ...}` (201)
- 409 on duplicate; 404 if notebook not found; 422 on bad URL or slug

**`GET /healthz`** (`server/health.py:184–185`):
- Handler: `healthz`
- Response: `{"status": "ok"}` (200) — liveness only, always responds

**`GET /status`** (`server/health.py:473–501`):
- Handler: `status_endpoint`
- Response: `application/health+json` — `{"status": "pass|warn|fail", "description": "arXMCP MCP server", "checks": {...}}` (200 for pass/warn, 503 for fail)
- `make status` curls this endpoint and pipes through `tools/status_line.py`

**`make add` REST path**: `POST /ui/api/notebooks/{slug}/papers` with body `{"arxiv_url": "https://arxiv.org/abs/<paper_id>"}` — NOT a raw paper_id. The Make target must construct the arxiv URL from the PAPER arg.

### 6. Makefile current state

**Help block** (`Makefile:10–41`): current post-m1 state has no "FIRST TIME?" section. The `ARXMCP_CONTACT_EMAIL` mention at lines 37–40 is a note under "Before running the arXiv CLI fetch tools", not a structured section. The help target is plain `@echo` — no variable substitution.

**Existing `KEY=VALUE` pattern**: The `ARGS=` pattern is used extensively (`make ingest ARGS="--limit=5"`). The `NOTEBOOK=` and `PAPER=` pattern (positional Make variables) does NOT yet exist — this is new convention for m2. The precedent is `ARGS=`, not named keys. But the brief explicitly specifies `make init NOTEBOOK=<slug> EMAIL=<email>` — implementer should define `NOTEBOOK ?=` and `EMAIL ?=` at the top of the Makefile alongside the existing `PYTHON ?=` and `ARXMCP_BIND_PORT ?=`.

**`make status` current** (`Makefile:108–120`): already implemented in m1; curls `/status` and pipes through `tools/status_line.py`. The brief's `make status` (AC5) should reuse this — it already works. No new target needed for `make status` itself (it exists); the brief's AC5 "works whether up or down" means verifying the existing offline-fallback `echo "DOWN: ..."` in the else branch covers it.

**`make bootstrap` (lines 42–68)**: creates `var/arxmcp/` tree; does NOT create `var/arxmcp/cache/` — but `notebooks.db` already lands there from prior notebook-ops work (the lifespan creates it). `OperatorSettingsStore` opens the same path. No bootstrap change needed.

**`.PHONY` line 1**: currently `help bootstrap test eval up status ingest delta re-embed re-embed-all ingest-recover-preambles watchdog cutover notebook-cutover daily-report parser-failures-report sbom refresh-arxiv-ca`. New targets `init add notebook-list` must be added here.

### 7. On-disk vs SQLite-registry gap

`POST /ui/api/notebooks` (the REST handler `create_notebook` at `server/routes/notebooks.py:252–348`) does BOTH:
1. Calls `store.create_notebook(...)` — SQLite INSERT
2. Calls `nb_dir.mkdir(parents=True, exist_ok=True)` — on-disk dir

The REST handler does both atomically (mkdir after INSERT, with rollback on mkdir failure). `tools/notebook_init.py` does ONLY the on-disk scaffold — no SQLite write.

**For `make init` idempotency (AC1)**: the brief says `make init` is idempotent. If `make init` calls `notebook_init.py` (on-disk) AND also writes to SQLite directly:
- First run: creates both on-disk + SQLite row
- Second run: `notebook_init.py` short-circuits on `nb_dir.exists()`. SQLite INSERT would hit IntegrityError on duplicate slug → must use `INSERT OR IGNORE` or check-first.

**Recommended sequence for `make init`**:
1. Call `python tools/notebook_init.py <slug>` (on-disk scaffold; idempotent)
2. Write EMAIL to `operator_settings` if provided (always idempotent via `INSERT OR REPLACE`)
3. Optionally register notebook in SQLite using direct SQLite write (not curl POST — no server dependency). Use `INSERT OR IGNORE INTO notebooks(slug, lancedb_path, created_at) VALUES (...)` to be idempotent.

This avoids requiring the server to be running during `make init`.

### 8. Existing test patterns

**`tests/test_notebook_api.py` fixture pattern** (lines 45–86):
- `notebooks_base` fixture: `tmp_path / "notebooks"` + `monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)`
- `client` fixture: `asyncio.new_event_loop()` → `loop.run_until_complete(NotebooksStore.open(db_path))` → builds minimal `FastAPI()` app → `app.state.notebooks_store = store` → `TestClient(app)`
- Teardown: `loop.run_until_complete(store.close())` → `loop.close()`

**`tests/test_operator_settings.py` should mirror this**: `tmp_path / "notebooks.db"` as the db_path. For the synchronous API paths (CLI), use `asyncio.new_event_loop().run_until_complete(...)` or expose a synchronous open method.

**Existing notebook test files** (via `ls tests/ | grep -i notebook`):
`test_checkpoint_notebooks_db.py`, `test_notebook_api.py`, `test_notebook_cutover.py`, `test_notebook_detail_status.py`, `test_notebook_durability.py`, `test_notebook_export.py`, `test_notebook_rename_delete.py`, `test_notebook_restore.py`, `test_notebook_textbook_ingest.py`, `test_search_notebook_routing.py`, `test_textbook_notebook_isolation.py`

### 9. BP1/BP2 cross-check

m2 touches: `Makefile`, `tools/_notebook_common.py`, `tools/notebook_init.py`, `tools/notebook_fetch.py`, `tools/recover_preambles.py`, `ingest/inspire_ingest.py`, `ingest/graph_ingest.py`, `server/operator_settings.py` (NEW).

None of these touch `server/tools.py::ALL_TOOLS`, `server/prompts.py`, or the MCP tool definitions.

**`EXPECTED_TOOL_SCHEMA_SHA256`** (`tests/test_server_tool_schema.py:94–96`):
```
"c7df4c5c10c86693ac8553b7d079b55fba21749881c233f0f298955379d13375"
```
**MUST stay unchanged** — AC8.

**`EXPECTED_BP1_SHA256`** (`tests/test_prompts.py:649–651`):
```
"483344e3fcdea1d64de893cc669c9f142fd6f1198d4c8d383cd9c232558959bc"
```
**MUST stay unchanged** — AC8.

### 10. Recent git log

```
40f3552 chore(notes): finalize ui-attractive-polish-m1 state -> complete
dc30b93 rect(server,tests,notes): close F1, F2 from ui-attractive-polish-m1 critique
33c5a93 chore(notes): finalize onboarding-uplift-m1 state -> complete
5a82802 rect(server): close F1, F2, F3, F4, F5 from onboarding-uplift-m1 critique
c5adff3 feat(server,frontend): foundational a11y baselines (ui-attractive-polish-m1)
924d5ad chore(plans,notes): land ui-attractive-planing artifacts
e7c480a feat(server): clear env-var error + ARXMCP_CONTACT_EMAIL doc sweep
```

The m1 commit `e7c480a` landed the ARXMCP_CONTACT_EMAIL doc sweep. No parallel sessions are editing `server/notebooks_store.py`, `server/routes/notebooks.py`, `tools/_notebook_common.py`, or the Makefile in the current HEAD. The `onboarding-uplift-m1` rectification (`5a82802`) landed clean.

---

## Prior decisions and lessons

- **D1 (bootstrap OFF)**: Do NOT touch the boot-time corpus guard. Cold-start still fatals. `make init` must work even when the server is down.
- **D2 (corpus-level ingest)**: `make add` does NOT trigger per-notebook LanceDB ingest. Tagging is SQLite-only (+ papers.txt fallback when server is down). `make ingest` (shared corpus) remains separate.
- **D4 (operator settings → SQLite)**: `operator_settings` table in `var/arxmcp/cache/notebooks.db`. Schema: `(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)`.
- **MEMORY pattern** (from agent memory): `NotebooksStore` is `async`-only; CLI callers use `asyncio.new_event_loop().run_until_complete(...)`. For CLI tools that run synchronously, the `OperatorSettingsStore` MUST expose a synchronous path — either via a module-level `get_setting(key, db_path)` function or a `get_sync(key)` method that creates a fresh sync connection.
- **Banned**: `assert` for invariants, `BaseHTTPMiddleware`, `anthropic` SDK at runtime. None of these are risks for m2.
- **Doc placement**: `server/operator_settings.py` goes under `server/` (source code). Test file `tests/test_operator_settings.py` goes under `tests/`. `tests/test_make_targets.py` goes under `tests/`. No new Markdown files outside `.claude/`.

---

## External sources

Not applicable. m2 touches only local SQLite, Make targets, and Python CLI tools. No MCP spec or Anthropic prompt-caching docs are relevant (no MCP surface change, no cache-pinning change).

---

## Recommendation

**Implement `OperatorSettingsStore` as a dual-mode class**: synchronous methods (`get_sync`, `set_sync`) for CLI callers + async methods (`get`, `set`) for server context. Both use the same `notebooks.db` file. Add the `operator_settings` table as a v4→v5 ADDITIVE migration in `NotebooksStore._open_sync` so the single file's `user_version` stays authoritative. Expose a module-level `get_setting(key, db_path) -> str | None` function in `server/operator_settings.py` so `tools/_notebook_common.py::resolve_contact_email` can import it without pulling in asyncio overhead.

For `make init`: call `python tools/notebook_init.py <slug>` (on-disk scaffold) then write EMAIL to `operator_settings` AND register the notebook in `notebooks.db` using a direct synchronous SQLite `INSERT OR IGNORE` — this makes `make add` (server-up REST path) work immediately after `make init` without a separate `POST /ui/api/notebooks` step.

For `make add`: server-up path: POST `{"arxiv_url": "https://arxiv.org/abs/<PAPER>"}` to `/ui/api/notebooks/<NOTEBOOK>/papers`. Server-down path: `echo "<PAPER>" >> var/arxmcp/notebooks/<NOTEBOOK>/papers.txt` (no SQLite write — avoids the FK requirement). Idempotency for the offline path: use `grep -qxF "<PAPER>" papers.txt || echo ...`.

---

## Open questions

1. **Does `make init` register the notebook in `notebooks.db::notebooks`?** The brief says `make init` calls `python tools/notebook_init.py <slug>` and writes EMAIL to `operator_settings`. It does NOT explicitly say it also registers the notebook row. But `make add` (server-up) POSTs to `/ui/api/notebooks/<slug>/papers`, which 404s if the notebook row doesn't exist. RECOMMENDATION: `make init` should ALSO write the notebook row via direct SQLite `INSERT OR IGNORE` (not curl, not via the server). This keeps `make init` fully offline-capable and makes `make add` (server-up) work correctly. If the brief author intended otherwise, the implementer should flag this before writing `test_make_targets.py`.

2. **`OperatorSettingsStore` schema migration vs `NotebooksStore` ownership**: Since both live in the same `notebooks.db` and share `PRAGMA user_version`, the v4→v5 migration (adding `operator_settings` table) should be in `NotebooksStore._open_sync`. This means every `NotebooksStore.open()` call creates the `operator_settings` table as a side effect — acceptable because the table is always wanted. Alternative: a separate `PRAGMA application_id` trick. RECOMMENDATION: put v4→v5 in `NotebooksStore._open_sync`; `OperatorSettingsStore` only opens the file (no migration of its own) and asserts `user_version >= 5` as a sanity guard.

3. **`ingest/` files importing from `tools/`**: `inspire_ingest.py` and `graph_ingest.py` currently have no `tools._notebook_common` import. Is this a circular-import risk? Check: `ingest/` imports from `server/`? No (ingest is a pipeline package). `tools/` imports from `ingest/` (yes — `notebook_fetch.py` imports `ingest.ar5iv_fetch`). So `ingest/ → tools/` would be a NEW cross-direction import. RECOMMENDATION: Instead of importing `resolve_contact_email` from `tools._notebook_common` in `ingest/` files, expose a standalone `server.operator_settings.get_contact_email(db_path)` function (no tools dependency) and import that in `ingest/` files.

No other open questions — the seam map above is sufficient to implement all 5 files.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR creation, no infra mutation, no third-party API calls.
