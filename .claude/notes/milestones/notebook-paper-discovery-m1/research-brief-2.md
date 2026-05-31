# Research Brief — notebook-paper-discovery-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T15:20:00Z

---

## In-codebase context

### Migration mechanism — how it works today

`server/notebooks_store.py` is the sole migration authority. SCHEMA_VERSION is a
module-level integer constant (`SCHEMA_VERSION: int = 4`, line 75). The migration
guard is `if current_version < N:` blocks inside `_open_sync`, applied in version
order. Each block ends with `conn.execute("PRAGMA user_version = N")`. Per the
module docstring (lines 57–75):

> "When adding a new version: append a new `if current_version < N:` block in
> `_open_sync` using `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` and bump
> SCHEMA_VERSION; do NOT drop existing tables."

`OperatorSettingsStore` (in `server/operator_settings.py`) **co-resides in the same
`notebooks.db` file** but uses an **in-table `__schema_version__` sentinel** rather
than `PRAGMA user_version`. Per its module docstring (lines 13–28): "NotebooksStore
owns `PRAGMA user_version`"; `OperatorSettingsStore` "has no `PRAGMA user_version`
line at all." This avoids a v4→v5 bump in `NotebooksStore` clobbering the settings
table's independent versioning. **No conflict with OperatorSettingsStore from this
migration.**

### SQLite NOT NULL + DEFAULT requirement — verbatim rule

SQLite's `ALTER TABLE ADD COLUMN` supports a column with `NOT NULL` only if a
`DEFAULT` value is also specified (so existing rows can be backfilled without a table
rewrite). The prior v2→v3 (`notebook_kind`) and v3→v4 (`parse_status`, `parse_error`,
`parsed_html_path`) migrations prove this pattern works:

```python
# server/notebooks_store.py lines 217-222 (v2→v3 pattern, verbatim):
conn.execute(
    "ALTER TABLE notebooks ADD COLUMN notebook_kind "
    "TEXT NOT NULL DEFAULT 'arxiv'"
)
conn.execute("PRAGMA user_version = 3")
```

Both new columns `discovery_category TEXT NOT NULL DEFAULT ''` and
`description TEXT NOT NULL DEFAULT ''` satisfy this rule — empty string is a valid
non-NULL default, backfills existing rows in O(1) (no row rewrite), and matches the
acceptance criteria.

### Autoescape — confirmed ON

`server/routes/ui.py` constructs:

```python
_env: jinja2.Environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(
        enabled_extensions=("html", "htm", "xml"),
        default_for_string=True,
    ),
```

(lines 86–91, verbatim). All template variables including `description` and
`discovery_category` are autoescaped. Zero `| safe` filters exist in any template.
Per `server/routes/ui.py` comment: "the brief's 'explicit > implicit' discipline
(m8 synthesis) calls for naming autoescape in this file so a future template-loader
change can't silently regress it." Free-text `description` rendered in a template is
XSS-safe by construction, provided no `| safe` filter is introduced.

### Validation pattern — `if … raise`, not `assert`

`CLAUDE.md §4.7`: **"`assert` is BANNED for invariants — Python `-O` strips them.
Use `if … raise RuntimeError(…)` instead."** The `discovery_category` validation
against `{math.AG, math.NT, math-ph, hep-th}` (empty allowed) must follow the same
pattern as e.g. `server/routes/notebooks.py` which raises `HTTPException` from
`NotebookError` rather than asserting.

Correct implementation:
```python
_VALID_CATEGORIES = frozenset({"math.AG", "math.NT", "math-ph", "hep-th", ""})
if body.discovery_category not in _VALID_CATEGORIES:
    raise HTTPException(status_code=422, detail="...")
```

The route layer (Pydantic model) OR the store's writer method are both valid
enforcement points; the route layer (Pydantic pattern validator) is preferred per
the precedent of `NotebookCreate.notebook_kind`'s regex pattern (line 214).

### Backup scope — `notebooks.db` is already in scope

`ops/cron/arxmcp-backup.sh` lines 89–95 already include
`"${REPO_ROOT}/var/arxmcp/cache/notebooks.db"` in `BACKUP_PATHS`. Per
`08-security-observability-ops.md` (lines 242–265):

> "**Notebook metadata:** `/var/arxmcp/cache/notebooks.db` …
> **EXCEPTION to the cache-exclusion policy below** — it is user-authored state
> (notebook membership, slugs, uploaded-paper provenance), not a regenerable cache."

The new v4→v5 migration adds columns to the `notebooks` table inside this same file.
**No change to the backup script is required** — the file path is unchanged; the new
columns are automatically included. The acceptance criterion "new columns included in
the restic backup scope" is satisfied by the existing include-list without modification.

### doc-placement — where the discovery-model note goes

`CLAUDE.md §1` and `agent-conventions.md §6`: "All other agent-internal Markdown …
new milestone artifacts go to `.claude/notes/milestones/<ID>/`. Per-feature internal
references go to `.claude/docs/`." The milestone brief says "`.claude/notes/<name>.md`
discovery-model note committed." That exact path (`.claude/notes/`) is within the
allowed zone — agent-internal design notes live there (it is the design constitution
directory). The note must NOT go in `server/`, `ingest/`, or repo root.

### arXiv categories — exact codes from CLAUDE.md §2

> "Target arXiv categories: `math.AG`, `math.NT`, `math-ph`, `hep-th`."

These four are the validation domain. An empty string is accepted (per the acceptance
criteria: "empty allowed"). No other values.

### Tool-schema impact

This milestone does NOT add or modify any MCP tool in `server/tools.py::ALL_TOOLS`.
`EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` is **unchanged**.
No re-pin needed.

### `PRAGMA user_version` is per-file

As confirmed by the `OperatorSettingsStore` design: `PRAGMA user_version` is
per-database-FILE, not per-table. The v4→v5 bump is the only migration writing to
`user_version`; no other store references `user_version = 5`.

---

## Prior decisions and lessons

### Recent git log

```
e69de9c chore(plans): land ui-attractive-polish m3 roadmap section
8122ace chore(notes): finalize onboarding-uplift-m2 state -> complete
e3ec3f3 rect(server,tools,tests): close F1+F2+F3+F4+F5+F6+F7+IS1 from m2 critique
fdd28d4 chore(notes): finalize ui-attractive-polish-m2 state -> complete
43b9085 feat(server,tools,ingest): make init/add/notebook-list + SQLite settings
```

The most recent substantive milestones are `ui-attractive-polish-m3` (UI polish) and
`onboarding-uplift-m2` (SQLite settings store). The SQLite migration pattern from m2
is directly applicable: the `onboarding-uplift-m2` memory entry notes the
`user_version` is per-file and owned by `NotebooksStore._open_sync`.

### onboarding-uplift-m2 lesson (from agent memory)

Memory entry: "`PRAGMA user_version` is per-database-FILE, not per-table. When two
stores (`NotebooksStore`, `OperatorSettingsStore`) open the same `notebooks.db`, their
migrations must share a single version sequence in `NotebooksStore._open_sync`."
**This is resolved**: `OperatorSettingsStore` uses an in-table sentinel (confirmed by
reading `server/operator_settings.py`). The v4→v5 block for this milestone belongs
only in `NotebooksStore._open_sync`. No cross-store coordination needed.

### Jinja2 autoescape confirmed on (no regression risk)

Memory entry `ui-attractive-polish-m1`: "Jinja2 autoescape explicit construction in
`server/routes/ui.py`. Zero `| safe` filters in any template." Confirmed current.
A `description` field rendered in a template is safe without additional escaping —
but the implementer MUST NOT introduce `| safe` on these new fields.

### outerHTML swap loses aria-live (if applicable)

Memory entry: "htmx `hx-swap='outerHTML'` REPLACES the element — the new element
from the server must carry `aria-live` in its markup." If the edit form's
`description`/`discovery_category` fields are inside a div that gets an outerHTML
swap, the server-rendered fragment must also carry `aria-live`. For a simple PATCH
that re-renders a field value, follow the same pattern as `_display_name_fragment`
in `server/routes/notebooks.py`.

---

## External sources

**07-multi-agent-caching.md** is relevant for confirming no tool-schema change is
required: "Pin tool JSON schemas … A casual edit to a tool description blows every
sub-agent's cache." Since this milestone adds no MCP tool, BP1 cache stability is
unaffected.

**SQLite ALTER TABLE documentation** — the constraint that `NOT NULL` columns require
a DEFAULT is from the SQLite specification. The existing codebase migrations
(v2→v3, v3→v4) demonstrate this pattern works correctly on the live schema. No
external vendor doc lookup is required; the codebase is the authoritative source.

**08-security-observability-ops.md backup section** (lines 242–265) — verbatim
confirms `cache/notebooks.db` is already in the backup include-list. No external
source needed.

No MCP spec or Anthropic prompt-caching docs are relevant — this milestone does not
touch the server tool surface or caching.

---

## Failure-mode analysis (five enumerated)

### FM-1 — Category validation rejecting empty string (incorrect validation logic)

**Trigger:** Implementer validates `discovery_category` as
`if discovery_category not in {"math.AG", "math.NT", "math-ph", "hep-th"}` (omitting
`""` from the allowed set). Any operator who leaves the field blank on create/edit
gets a 422.

**Symptom:** Create notebook form fails with an unprocessable-entity error whenever
the operator doesn't fill in the category — breaking existing no-category workflows.

**Mitigation:** The validation set must be `frozenset({"math.AG", "math.NT",
"math-ph", "hep-th", ""})`. The acceptance criteria explicitly states "empty
allowed." Use a Pydantic `pattern` field (e.g.
`pattern="^(math\\.AG|math\\.NT|math-ph|hep-th|)$"`) or an explicit set membership
check.

### FM-2 — Stored XSS via free-text `description` rendered with `| safe`

**Trigger:** Implementer adds `{{ notebook.description | safe }}` to a template
(e.g. to allow basic HTML formatting), bypassing Jinja2's autoescape.

**Symptom:** A crafted `description` value like `<script>alert(1)</script>` executes
JavaScript in the operator's browser. Since the console is loopback-only, the
practical severity is low, but it violates the project's explicit stored-XSS
defense documented in memory for `ui-attractive-polish-m1`.

**Mitigation:** Never use `| safe` on operator-controlled fields. Autoescape is
already ON for all `.html` templates. The `display_name` field is the direct
precedent — it is rendered without `| safe` throughout all templates.

### FM-3 — Partial migration leaving DB in a half-upgraded state

**Trigger:** The server crashes (power loss, OOM kill, SIGKILL) between the two
`ALTER TABLE ADD COLUMN` statements and before `PRAGMA user_version = 5` is written.
On restart, `current_version` is still 4, so the migration block runs again. The
second `ALTER TABLE ADD COLUMN discovery_category` fails with `sqlite3.OperationalError:
duplicate column name`.

**Symptom:** Server fails to start on the next boot. The `_open_sync` function raises
an uncaught `sqlite3.OperationalError`, preventing the lifespan from completing.

**Mitigation:** Two options: (a) Wrap the v4→v5 block in a transaction
(`conn.execute("BEGIN")`...`conn.execute("COMMIT")`) so the two `ALTER TABLE` and
the `PRAGMA user_version = 5` are atomic — if any fails, the whole block rolls back
and retries cleanly. (b) Use a try/except to check if the column already exists
before attempting `ALTER TABLE`. Option (a) is simpler and consistent with SQLite WAL
behavior. Note: `isolation_level=None` (autocommit) is set on the connection; the
implementer must call `conn.execute("BEGIN")` explicitly.

**RECOMMENDED MITIGATION:** Wrap the v4→v5 block in `BEGIN`/`COMMIT` explicitly, as
the existing migration blocks appear to rely on implicit auto-commit. Alternatively,
catch `sqlite3.OperationalError` on duplicate column and treat it as a no-op (already
migrated path), then unconditionally write `user_version = 5`.

### FM-4 — `description` / `discovery_category` absent from `list_notebooks` and `get_notebook` selects

**Trigger:** The migration correctly adds the columns, but the `SELECT` statements in
`list_notebooks()` and `get_notebook()` (lines 283–299 and 311–327) are not updated
to include the new columns.

**Symptom:** The API returns dicts without `discovery_category` or `description`.
The operator-console forms silently lose their saved values on page reload (the
fields appear empty even though the DB has data). Tests that check persistence pass
at the DB level but fail at the HTTP layer.

**Mitigation:** Update the SELECT queries in both `list_notebooks` and `get_notebook`
to include `discovery_category, description` and add them to the returned dicts. This
is the same pattern applied for `notebook_kind` (v2→v3) and `parse_status` (v3→v4).

### FM-5 — `create_notebook` signature gap: new fields accepted by Pydantic but not passed to `store.create_notebook`

**Trigger:** The route adds `discovery_category` and `description` to `NotebookCreate`
(Pydantic model) but the call to `store.create_notebook(...)` doesn't forward the
new fields. SQLite applies the column-level `DEFAULT ''`, so DB rows always have
empty strings for these fields regardless of what the operator submitted.

**Symptom:** The create form accepts the fields, returns HTTP 201, but the notebook's
`discovery_category` and `description` are always empty. No error is raised. This is
a silent data loss.

**Mitigation:** Update `store.create_notebook(...)` signature to accept
`discovery_category: str = ""` and `description: str = ""`, pass them through in the
`INSERT` statement. Ensure the route handler forwards them from `body.discovery_category`
and `body.description`. Add a test that round-trips a non-empty category through the
create endpoint.

---

## Recommendation

**Implement the v4→v5 migration as two `ALTER TABLE ADD COLUMN ... NOT NULL DEFAULT ''`
statements inside a `BEGIN`/`COMMIT` transaction in `NotebooksStore._open_sync`,
bump `SCHEMA_VERSION` to 5 and the `PRAGMA user_version = 5`; validate
`discovery_category` via a Pydantic `pattern` field in `NotebookCreate` and a new
`NotebookUpdate` (or extend `NotebookRename`) model, not via `assert`.**

Rationale: The transaction guard prevents FM-3 (partial-migration crash loop). The
Pydantic pattern validation is the established project pattern for categorical fields
(`notebook_kind` precedent at line 214 of `server/routes/notebooks.py`). The empty
string must be included in the allowed set. The backup script requires no change
(already targets `notebooks.db` by file path). The discovery-model note belongs at
`.claude/notes/notebook-discovery-model.md` (or a similar name under `.claude/notes/`).

For the edit form: add a new PATCH endpoint or extend the existing
`PATCH /ui/api/notebooks/{slug}` to accept `discovery_category` and `description` —
the existing `NotebookRename` model is limited to `display_name` only (mass-assignment
defense per line 222–229). A separate `NotebookUpdate` model with the three optional
fields is the safest pattern.

**No MCP tool changes, no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin, no backup script
changes are needed.**

---

## Open questions

1. **Edit endpoint shape**: Should the implementer extend `PATCH /ui/api/notebooks/{slug}`
   to also accept `discovery_category` and `description` (alongside `display_name`),
   or create a new `PATCH /ui/api/notebooks/{slug}/metadata` endpoint? The existing
   `NotebookRename` model explicitly excludes other fields as a mass-assignment defense
   (line 222). Recommendation: create a new `NotebookMetadataUpdate` Pydantic model
   covering all three editable fields (`display_name`, `discovery_category`, `description`)
   and wire a single PATCH endpoint that handles any subset — simpler than two endpoints.

2. **Discovery-model note filename**: The milestone brief says "`.claude/notes/<name>.md`"
   but does not specify the `<name>`. Suggested: `.claude/notes/notebook-discovery-model.md`.
   This does not conflict with any existing numbered note (01–10) and is descriptive enough
   for future agents to locate it.

---

## External writes the implementation will require

None — this milestone is purely local.

All changes are to source files, SQLite schema (local file), frontend templates, and
a design note under `.claude/notes/`. No git push, no GitHub PR, no infra mutation,
no third-party API call is required or expected.
