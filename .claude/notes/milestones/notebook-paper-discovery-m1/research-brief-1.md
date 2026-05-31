# Research Brief — notebook-paper-discovery-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T15:10:00Z

## In-codebase context

### Design constitution notes that apply

- `01-mission-and-context.md` — "power tool, not autopilot"; no server-side LLM at runtime
- `06-mcp-server-design.md` — loopback-only operator console, Jinja2+htmx, no Node/SPA
- `07-multi-agent-caching.md` — tool schema byte-stability; **this milestone does NOT add an MCP tool**, so `EXPECTED_TOOL_SCHEMA_SHA256` is UNCHANGED
- `08-security-observability-ops.md` — backup scope; `notebooks.db` is non-regenerable user state
- `CLAUDE.md §4.7` (load-bearing): "`assert` is BANNED for invariants — use `if … raise RuntimeError(…)` instead"
- `CLAUDE.md §1` (load-bearing): "When you create a new Markdown file, default to `.claude/` unless the content is BOTH operator-facing AND linked from the root README."

### Current schema state (`server/notebooks_store.py`)

Current `SCHEMA_VERSION: int = 4` at line 75. Migration history verbatim:

- `v0→v1` (line 154): destructive CREATE — fires only on fresh/empty DB
- `v1→v2` (line 187): ADDITIVE `CREATE TABLE IF NOT EXISTS notebook_ingest_runs`
- `v2→v3` (line 217): ADDITIVE `ALTER TABLE notebooks ADD COLUMN notebook_kind TEXT NOT NULL DEFAULT 'arxiv'`
- `v3→v4` (line 238): ADDITIVE `ALTER TABLE notebooks ADD COLUMN parse_status TEXT NOT NULL DEFAULT 'skipped'` (plus `parse_error` and `parsed_html_path`)

The v3 and v4 migration blocks are the EXACT pattern to follow for v4→v5. The code comment at lines 63–75 states the invariant explicitly: "do NOT drop existing tables."

### Where the v4→v5 block goes

`server/notebooks_store.py:251` — immediately after the `conn.execute("PRAGMA user_version = 4")` line and before `return conn`. The new block must follow the same shape as v3→v4:

```python
if current_version < 5:
    conn.execute(
        "ALTER TABLE notebooks ADD COLUMN discovery_category "
        "TEXT NOT NULL DEFAULT ''"
    )
    conn.execute(
        "ALTER TABLE notebooks ADD COLUMN description "
        "TEXT NOT NULL DEFAULT ''"
    )
    conn.execute("PRAGMA user_version = 5")
```

`SCHEMA_VERSION` at line 75 must be bumped from `4` to `5`.

### SQLite ALTER TABLE NOT NULL semantics (confirmed)

SQLite 3.25+ allows `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT <literal>`. The DEFAULT expression backfills existing rows in O(1) via a stored default — no row rewrite. This is exactly what v2→v3 and v3→v4 use. An empty string `''` is a valid SQLite literal. No migration risk.

### Where the validation helper goes

The `discovery_category` validator belongs in `server/routes/notebooks.py`, parallel to `_CONTROL_CHARS_RE` and the existing inline slug validation. The milestone brief requires `if … raise`, NOT `assert`. Recommended location: a module-level constant + helper, e.g.:

```python
_VALID_DISCOVERY_CATEGORIES: frozenset[str] = frozenset({
    "math.AG", "math.NT", "math-ph", "hep-th",
})

def _validate_discovery_category(value: str) -> None:
    if value and value not in _VALID_DISCOVERY_CATEGORIES:
        raise ValueError(
            f"discovery_category {value!r} is not one of "
            f"{sorted(_VALID_DISCOVERY_CATEGORIES)} (or empty string)"
        )
```

Called from both the `NotebookCreate` create handler and the new edit PATCH handler. The route handler translates `ValueError` to HTTP 422.

### Where to extend `NotebookCreate` and add the PATCH body model

`server/routes/notebooks.py`, `NotebookCreate` Pydantic model at lines 193–215. Add two new optional fields:

```python
discovery_category: str = Field(default="", max_length=32)
description: str = Field(default="", max_length=512)
```

A new `NotebookTopicUpdate` model (parallel to `NotebookRename` at lines 218–229) for the PATCH endpoint:

```python
class NotebookTopicUpdate(BaseModel):
    discovery_category: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=512)
```

The PATCH endpoint mirrors `rename_notebook` (lines 424–465) in structure: `validate_slug` first, then `_validate_discovery_category`, then a new `store.update_topic` call, then an HTML fragment response.

### Where to add `create_notebook` and `update_topic` changes

`server/notebooks_store.py`, `create_notebook` method at line 330: extend the INSERT to include `discovery_category` and `description`. The `update_topic` method mirrors `update_display_name` (lines 394–416) — a two-column `UPDATE notebooks SET discovery_category = ?, description = ? WHERE slug = ?`.

### Operator console form changes

**Create form** (`frontend/templates/index.html`, currently 72 lines): add two new `<label>` blocks to the create form between "Display name" and the submit button. `discovery_category` should be a `<select>` with values `["", "math.AG", "math.NT", "math-ph", "hep-th"]` (empty = "Not specified"). `description` is a `<textarea>` with `maxlength="512"`. The form currently POSTs JSON via the htmx `hx-post="/ui/api/notebooks"` handler; the JSON body model `NotebookCreate` is matched by the `base.html` JSON shim.

**Edit form** (`frontend/templates/notebook_detail.html`): add a new `<form>` card for editing topic metadata (like the rename form at lines 31–46), using `hx-patch="/ui/api/notebooks/{slug}/topic"` (a new route), `hx-target="#topic-block"`, `hx-swap="outerHTML"`. A corresponding static `<div id="topic-block">` shows the current `discovery_category` and `description`.

### Restic backup scope — already covered

The `ops/cron/arxmcp-backup.sh` backup manifest (lines 89–95) already includes `var/arxmcp/cache/notebooks.db` as an explicit entry:

```bash
"'"${REPO_ROOT}"'/var/arxmcp/cache/notebooks.db"
```

Since the new columns live in the same `notebooks.db` file, the restic backup scope automatically covers them without any change to `arxmcp-backup.sh`. The acceptance criterion is satisfied by the existing backup script. **No modification to `ops/cron/arxmcp-backup.sh` is required.**

### Discovery-model note placement

Per `CLAUDE.md §1` and `agent-conventions.md §6`, the note goes under `.claude/notes/` — specifically `.claude/notes/notebook-discovery-model.md`. It is NOT operator-facing documentation (not referenced from README), so it does NOT go in `docs/`. The note covers: field schema (discovery_category + description), the propose→confirm model, and the channel-dedup boundary (CC-4 from the roadmap synthesis).

### arXiv category codes

From `CLAUDE.md §2` and the roadmap verbatim: target categories are `math.AG`, `math.NT`, `math-ph`, `hep-th`. These are the exact strings arXiv uses in its category taxonomy (`math-ph` has no period; `hep-th` has a hyphen; `math.AG` and `math.NT` have periods). The validator must match these exactly. No external lookup required — confirmed against the capability scout final-report.

## Prior decisions and lessons

**Recent git log (relevant milestones):**

- `867edb7 chore(notes): finalize onboarding-uplift-m3 state -> complete` — last completed milestone; that milestone added `repair-registry`, `reconcile-marker`, and per-notebook health endpoints. All are schema-version-safe (they only read/write existing columns).
- `43b9085 feat(server,tools,ingest): make init/add/notebook-list + SQLite settings` — the onboarding-uplift-m2 milestone introduced the `OperatorSettingsStore` pattern, which shares `notebooks.db` with `NotebooksStore`. **Critical lesson from MEMORY.md entry `onboarding-uplift-m2 — user-version-shared-across-stores`:** `PRAGMA user_version` is per-database-FILE. Both `NotebooksStore` and `OperatorSettingsStore` open the same `notebooks.db`. The v4→v5 migration block must go in `NotebooksStore._open_sync`, and `OperatorSettingsStore` must assert `user_version >= 5` but NOT run its own migration. See `server/operator_settings.py` for the current state.

**Test pattern for additive migrations:** `tests/test_notebook_api.py` shows the established pattern (lines 1063–1327). Each migration bump gets:
1. A test that seeds a pre-migration DB directly via raw `sqlite3.connect`, sets the old `user_version` via `PRAGMA`, then opens via `NotebooksStore.open` and asserts the new columns exist with correct defaults on existing rows.
2. An idempotency test that opens the DB twice and asserts columns are stable.
3. A "version set correctly" test asserting `PRAGMA user_version == SCHEMA_VERSION`.

The v4→v5 test should follow the same shape: seed a v4 DB with an existing notebook row, open via `NotebooksStore.open`, confirm `discovery_category == ''` and `description == ''` on the legacy row, confirm `user_version == 5`.

**`list_notebooks` and `get_notebook` must be updated** to include the new columns in their `SELECT` queries and in the returned dicts. The pattern at lines 283–299 and 311–327 shows all columns enumerated explicitly — a new column NOT added here would silently not appear in API responses.

**MEMORY.md entry `onboarding-uplift-m2 — ingest-to-tools-import-direction`** warns against `ingest/ → tools/` cross-imports. This milestone doesn't touch `ingest/`, so not relevant.

## External sources

**SQLite ALTER TABLE NOT NULL with DEFAULT:** SQLite documentation confirms that `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT <value>` is supported since SQLite 3.25 (the project requires Python 3.11+ which ships with SQLite 3.37+). The DEFAULT literal fills existing rows without rewriting them. The four prior v1–v4 migrations use this exact mechanism. No external verification needed.

**MCP spec:** Not relevant — this milestone does NOT add, remove, or modify any MCP tool. `EXPECTED_TOOL_SCHEMA_SHA256` is UNCHANGED.

**Anthropic prompt-caching docs:** Not relevant — no tool-schema change means no BP1 cache impact.

**arXiv category codes:** Confirmed against the capability-scout final-report (line 48: `"math.AG", "math.NT", "math-ph", "hep-th"`) and CLAUDE.md §2 verbatim. No external lookup needed.

## Recommendation

**Implement the v4→v5 migration in `server/notebooks_store.py` following the v3→v4 pattern verbatim, place the `discovery_category` validator as a module-level helper in `server/routes/notebooks.py`, extend `NotebookCreate` with two optional fields (`discovery_category` + `description`, both default `""`), add a new `PATCH /ui/api/notebooks/{slug}/topic` route mirroring `rename_notebook`, update the create form in `index.html` with a `<select>` for category and a `<textarea>` for description, and add a topic-edit card to `notebook_detail.html`.**

Rationale: this is a straightforward additive migration that mirrors v3→v4 exactly. The PATCH route is the right surface (not modifying the existing PATCH rename endpoint) because the topic fields are semantically separate from the display name. The create-form `<select>` enforces the category enum at the client side too (defense in depth). The backup scope requires no changes.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The schema question (one free-text `description` vs structured `(discovery_category, topic_keywords)`) was resolved in the roadmap at `plans/notebook-paper-discovery-roadmap.md` Phase 3: ship BOTH `discovery_category` (validated category) and `description` (free-text keywords/topic context). The milestone brief confirms this. The field names and types are fixed.

## External writes the implementation will require

None — this milestone is purely local.
