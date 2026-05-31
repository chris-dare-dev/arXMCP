# Research Brief — onboarding-uplift-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-30T00:00:00Z

---

## In-codebase context

### Durability pragmas — must reproduce in new store

`server/notebooks_store.py` lines 134–135 (verbatim):
```python
conn.execute("PRAGMA synchronous=FULL")
conn.execute("PRAGMA fullfsync=ON")
```
Comment (lines 120–133): "synchronous=FULL: in WAL mode, NORMAL can roll back the last committed transaction on power loss; FULL adds a WAL sync after every commit -> ACID-durable across power loss. fullfsync=ON: macOS only. Forces a true fcntl(F_FULLFSYNC) … This is CONNECTION-scoped (it does NOT persist to a fresh connection), so it must be set here, on every open."

The new `OperatorSettingsStore` MUST reproduce `journal_mode=WAL`, `synchronous=FULL`, `fullfsync=ON` on every connection. They are connection-scoped — omitting them in the CLI connection silently degrades durability.

### Migration discipline (verbatim from notebooks_store.py docstring)

> "When adding a new version: append a new `if current_version < N:` block in `_open_sync` using `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` and bump SCHEMA_VERSION; do NOT drop existing tables."

Use `CREATE TABLE IF NOT EXISTS operator_settings (...)` for idempotent first-create.

### `isolation_level=None` pattern

Both `cache_sqlite.py` and `notebooks_store.py` use `isolation_level=None` with explicit `BEGIN`/`COMMIT`. The new store MUST match — do NOT use Python's default implicit transaction mode.

### `make add` REST endpoint — URL vs paper-id semantic mismatch

`POST /ui/api/notebooks/{slug}/papers` (line 500 of `server/routes/notebooks.py`) takes body `{"arxiv_url": "https://arxiv.org/abs/2401.00001"}`. The brief's `make add NOTEBOOK=demo PAPER=2401.00001` provides a bare paper-id. The Makefile recipe must construct the URL for REST; use the bare paper-id for the `papers.txt` fallback.

The handler returns: **404** if notebook doesn't exist; **409** on duplicate; **422** on malformed URL.

### Existing `make status` target conflict

The Makefile already has a `status` target (line 108) with the pattern:
```make
@if out=$$(curl -sf --max-time 5 "...$(ARXMCP_BIND_PORT)/status" 2>/dev/null); then \
    printf '%s' "$$out" | $(PYTHON) tools/status_line.py; \
else \
    echo "DOWN: arxmcp-server at ... is down or warming up"; \
fi
```

**FLAG: The brief calls for a new `make status` with offline fallback. A duplicate `status` target is silently ignored by Make (last definition wins). The implementer must EXTEND the existing `status` target's `else` branch rather than create a duplicate.**

### Makefile ARGS= spaces-in-paths warning (verbatim comment, Makefile lines 130–132)

> "NOTE on ARGS: paths inside ARGS must not contain spaces — Make's shell expansion splits at whitespace before argparse sees the tokens."

Same applies to `EMAIL=` values: `EMAIL=First Last <me@example.com>` breaks without quoting. The slug regex (`^[a-z][a-z0-9-]{2,30}$`) prevents spaces in `NOTEBOOK=`, so that is safe.

### `notebook_init.py` idempotency pattern

`run()` checks `if nb_dir.exists(): print("skipping") return 0`. The new `make init` must reproduce idempotency at the SQLite level: use `INSERT OR REPLACE` (or `INSERT OR IGNORE`) for the `contact_email` key — re-running `make init` must not fail.

### `var/arxmcp/cache/notebooks.db` file permissions

Current: `0644` (world-readable on macOS default umask). `OperatorSettingsStore.open()` should call `os.chmod(db_path, 0o600)` after creating the file on first open (not every open).

---

## Prior decisions and lessons

- `onboarding-uplift-m1` is complete (state.json: `"phase": "complete"`).
- `notebook-ops-hardening-m1` confirmed: WAL + `synchronous=FULL` + `fullfsync=ON` are the durability standard for `notebooks.db`. All new connections to this file must reproduce them.
- No banned patterns at risk: no `assert`, no `BaseHTTPMiddleware`, no `anthropic` SDK imports, no `KMP_DUPLICATE_LIB_OK` changes.
- AC8 (EXPECTED_TOOL_SCHEMA_SHA256 + EXPECTED_BP1_SHA256 UNCHANGED) is safe: no MCP tool is added or modified.

---

## External sources

### Python `sqlite3.connect()` default timeout (docs.python.org/3.12)

Verbatim: "**timeout** (_float_) – How many seconds the connection should wait before raising an `OperationalError` when a table is locked. If another connection opens a transaction to modify a table, that table will be locked until the transaction is committed. **Default five seconds.**"

The 5-second retry window is sufficient for a CLI `make init` on a single-operator workstation.

### SQLite WAL concurrency (sqlite.org/wal.html §2.2)

Verbatim: "Writers merely append new content to the end of the WAL file. Because writers do nothing that would interfere with the actions of readers, writers and readers can run at the same time. However, since there is only one WAL file, **there can only be one writer at a time.**"

In WAL mode: the server (reader most of the time) and a CLI (writer) co-exist safely. Write-write contention hits the busy timeout (5s default) before raising `OperationalError`.

### SQLite WAL `synchronous=NORMAL` vs `FULL` (sqlite.org/wal.html §2.3)

Verbatim: "Writers sync the WAL on every transaction commit if PRAGMA synchronous is set to FULL but omit this sync if PRAGMA synchronous is set to NORMAL."

`operator_settings` is user-authored, NON-regenerable (email loss = arXiv fetch tools break). Use `synchronous=FULL`, same as `notebooks_store.py`.

### GNU Make `KEY=VALUE` override semantics

`make init NOTEBOOK=foo EMAIL=bar` — standard GNU Make command-line variable override. Variables set this way override `?=` in the Makefile. They propagate to sub-make via `MAKEFLAGS`. Use `NOTEBOOK ?=` with a guard:
```make
@[ -n "$(NOTEBOOK)" ] || { echo "ERROR: NOTEBOOK= required"; exit 1; }
```
Space trap: `EMAIL=First Last <me@example.com>` without quoting splits at the space. Document in the target's `@echo` help line.

---

## Failure mode enumeration

**FM-1: SQLite write lock contention**
Trigger: Server mid-write on `notebooks.db` (notebook create/update) + CLI `make init` write to `operator_settings` simultaneously.
Symptom: `sqlite3.OperationalError: database is locked` after 5s.
Mitigation: Set `PRAGMA busy_timeout = 5000` in `OperatorSettingsStore._open_sync()` to make the intent explicit. On failure, print: "notebooks.db is busy — retry in a moment." In WAL mode this is rare (server writes only on notebook CRUD ops, not reads).

**FM-2: Schema-version drift (CRITICAL)**
Trigger: `OperatorSettingsStore` and `NotebooksStore` open the same `notebooks.db`. Both use `PRAGMA user_version` (file-scoped). If `OperatorSettingsStore` sets `PRAGMA user_version = 1`, it clobbers `NotebooksStore`'s `user_version = 4`, triggering a v0→v4 migration re-run that may clobber the `notebooks` table.
Symptom: All existing notebook metadata is lost.
Mitigation: **Use an in-table sentinel row** for schema versioning in `OperatorSettingsStore`:
```python
version_row = conn.execute(
    "SELECT value FROM operator_settings WHERE key='__schema_version__'"
).fetchone()
current_version = int(version_row[0]) if version_row else 0
```
Never call `PRAGMA user_version = N` in `OperatorSettingsStore`.

**DISAGREEMENT WITH R1:** R1's MEMORY.md entry (2026-05-31) recommends adding a v4→v5 block inside `NotebooksStore._open_sync`. R2 recommends an in-table sentinel so `OperatorSettingsStore` is fully self-contained. Rationale: the CLI opens `OperatorSettingsStore` without the server present; requiring `NotebooksStore` migrations to run first would be a layering violation. The orchestrator should choose: (A) R1's shared-migration approach; or (B) R2's decoupled in-table sentinel. **R2 recommends B.**

**FM-3: Stale email — SQLite wins over env var**
Trigger: Old email in `operator_settings`, new `ARXMCP_CONTACT_EMAIL` in shell. SQLite-first precedence means old email is used.
Symptom: arXiv requests sent with wrong User-Agent.
Mitigation: Log a DEBUG message when SQLite and env var differ. Operator escape: `make init EMAIL=new@example.com` updates the row. Preserve the brief's SQLite-first precedence — it is intentional (stickier than env var, survives shell restarts).

**FM-4: PII in SQLite**
Trigger: `notebooks.db` contains operator email. Current perms: `0644` (world-readable).
Symptom: Any local user can read the email.
Mitigation: `os.chmod(db_path, 0o600)` after file creation in `OperatorSettingsStore.open()`. This is a new tightening (the existing `notebooks_store.py` does not do this — a pre-existing gap; m2 is the right time to add it since we're creating a store that explicitly holds PII).

**FM-5: `make add` when server UP but notebook doesn't exist**
Trigger: Server running; `POST /ui/api/notebooks/demo/papers` → HTTP 404.
Symptom: With naive curl, cryptic error message.
Mitigation: Use `curl -sf --fail-with-body`. Parse HTTP status: 404 → print "ERROR: notebook not found — run `make init NOTEBOOK=demo` first" and exit 1. Do NOT fall back to `papers.txt` on 404 — that silently creates an orphan entry. Only fall back when the server is DOWN (curl exit 7 = connection refused).

**FM-6: `make add` server DOWN but notebook dir missing**
Trigger: Operator skipped `make init`. `var/arxmcp/notebooks/demo/` doesn't exist.
Symptom: `bash: .../demo/papers.txt: No such file or directory`.
Mitigation: Before fallback append:
```bash
@[ -d "var/arxmcp/notebooks/$(NOTEBOOK)" ] || { \
    echo "ERROR: notebook '$(NOTEBOOK)' not initialized — run 'make init NOTEBOOK=$(NOTEBOOK)' first" >&2; exit 1; }
```

**FM-7: `make notebook-list` with old-schema `notebooks.db`**
Trigger: `notebooks.db` created before `operator_settings` table was added.
Symptom: None — the REST path reads from the server's already-migrated DB. `OperatorSettingsStore` runs only when explicitly invoked (e.g. `make init EMAIL=...`).
Mitigation: No action needed. `make notebook-list` (server up) uses REST; (server down) reads directly via `NotebooksStore.open()` which runs any pending migrations on open.

**FM-8: `ARXMCP_CONTACT_EMAIL` env-var rejection — server scan vs CLI**
Trigger: `server/config.py` strict-typo check for `ARXMCP_*` vars. Does it reject `ARXMCP_CONTACT_EMAIL` for server use?
Investigation: `Config` dataclass in `server/config.py` does not include `contact_email`. The server never reads `ARXMCP_CONTACT_EMAIL`. The strict-typo scan only catches misspellings of KNOWN server vars.
Conclusion: No conflict. CLI tools read `ARXMCP_CONTACT_EMAIL` independently. `server/config.py` needs no change. Implementation proceeds as specified.

**FM-9: REST 5xx during `make add`**
Trigger: Server up, `POST /ui/api/notebooks/{slug}/papers` → 500.
Symptom: With `curl -sf`, exit non-zero but opaque error.
Mitigation: Use `curl -sf --fail-with-body`. Print response body on non-2xx. Do NOT fall back to `papers.txt` on 5xx — paper would be in file but not in DB.
Correct shell idiom:
```make
@if ! curl -sf --fail-with-body --max-time 5 -X POST \
    -H "Content-Type: application/json" \
    -d '{"arxiv_url":"https://arxiv.org/abs/$(PAPER)"}' \
    "http://127.0.0.1:$(ARXMCP_BIND_PORT)/ui/api/notebooks/$(NOTEBOOK)/papers"; then \
    echo "ERROR: server returned error — see above" >&2; exit 1; \
fi
```

### `curl` health-check idiom for server-up detection

Existing `make status` uses `curl -sf --max-time 5`. For `/healthz` (always-200, no warm-up dependency), use `--max-time 2` — it never blocks. For REST calls with real work, keep `--max-time 5`. Correct shell pattern in Make:
```make
@if curl -sf --max-time 2 "http://127.0.0.1:$(ARXMCP_BIND_PORT)/healthz" >/dev/null 2>&1; then \
    # server is up — use REST \
else \
    # server is down — use file fallback \
fi
```
`-s` = silent (no progress bar). `-f` = exit non-zero on HTTP 4xx/5xx. Combine with `>/dev/null 2>&1` to suppress output from the health check itself.

---

## Recommendation

Implement `OperatorSettingsStore` as a fully self-contained class in `server/operator_settings.py` that: (1) opens `notebooks.db` with `WAL + synchronous=FULL + fullfsync=ON + isolation_level=None`, (2) uses an in-table `__schema_version__` sentinel row (NOT `PRAGMA user_version`), (3) uses `os.chmod(db_path, 0o600)` on first file creation. For Makefile targets: extend the existing `status` target's `else` branch; use `curl -sf --max-time 2 /healthz` as the server-up gate (not `/status`); use `--fail-with-body` for REST calls. Differentiate 404 (clean error) from connection-refused (fallback) in `make add`.

---

## Open questions

1. **FM-2 schema-version strategy:** R1 proposes extending `NotebooksStore._open_sync` with a v4→v5 migration for `operator_settings`. R2 proposes a self-contained in-table sentinel. The orchestrator must pick one before implementation. R2's recommendation: in-table sentinel (decoupled, works without `NotebooksStore` running first).

2. **`make add` paper-id vs URL:** The REST endpoint requires `arxiv_url`; the CLI arg is a bare `PAPER=` id. Implementer must construct `https://arxiv.org/abs/$(PAPER)` for the REST body. Confirm this is the expected behavior (no version suffix stripping needed for `make add`).

3. **`make status` offline fallback:** Extending `else` branch requires a Python helper to read `notebooks.db` + check for `corpus-version.json`. Implementer should extend `tools/status_line.py` with an `--offline` mode flag rather than a new file, to avoid a new import surface.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no ticket, no infra mutation, no external API call.
