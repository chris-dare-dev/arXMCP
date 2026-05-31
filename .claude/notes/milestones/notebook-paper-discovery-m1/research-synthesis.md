# Research Synthesis — notebook-paper-discovery-m1

**Orchestrator merge of research-brief-1 + research-brief-2**
**Milestone:** Notebook topic metadata (schema v4→v5) + discovery-model note (ENABLER; first of m1–m4)
**Verdict:** Purely-local, additive migration. No open blockers. Implement INLINE.

---

## 1. Scope (fixed)

Three deliverables:
1. **Additive v4→v5 SQLite migration** in `server/notebooks_store.py` adding `discovery_category` + `description` columns.
2. **Operator-console create + edit** surfaces for both fields (loopback Jinja2+htmx).
3. **`.claude/notes/notebook-discovery-model.md`** — the design note fixing the field schema, propose→confirm model, and post-aggregation channel-dedup boundary for m2–m4.

**Explicitly OUT of scope (m2–m4):** the arXiv API library, any discovery driver, any new discovery channel, any new MCP tool. Confirmed by both briefs: `EXPECTED_TOOL_SCHEMA_SHA256` is **unchanged**; no BP1 cache impact.

---

## 2. Load-bearing constraints (quoted)

- **`CLAUDE.md §4.7`:** "`assert` is BANNED for invariants — Python `-O` strips them. Use `if … raise RuntimeError(…)` instead." → `discovery_category` validation uses explicit `if … raise`, not `assert`.
- **`CLAUDE.md §1`:** agent-internal Markdown lives under `.claude/`. The discovery-model note goes to `.claude/notes/notebook-discovery-model.md` — NOT `server/`, `ingest/`, `docs/`, or repo root. (It is a cross-milestone design note that outlives m1, so the design-constitution dir is correct, not `.claude/notes/milestones/<ID>/`.)
- **`server/notebooks_store.py:75`:** `SCHEMA_VERSION: int = 4` → bump to `5`. Module docstring (lines 57–75): "append a new `if current_version < N:` block … using `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` and bump SCHEMA_VERSION; **do NOT drop existing tables**."
- **`server/operator_settings.py`:** `OperatorSettingsStore` co-resides in `notebooks.db` but uses an **in-table `__schema_version__` sentinel**, NOT `PRAGMA user_version`. "NotebooksStore owns `PRAGMA user_version`." → **No cross-store coordination needed**; the v4→v5 block lives only in `NotebooksStore._open_sync`. (Both briefs agree; resolves the `onboarding-uplift-m2` per-file-user_version lesson.)
- **`server/routes/ui.py:86-91`:** Jinja2 `autoescape=select_autoescape(..., default_for_string=True)`; zero `| safe` filters anywhere. → free-text `description` is XSS-safe by construction **provided no `| safe` is introduced**.
- **`08-security-observability-ops.md:242-265`:** `var/arxmcp/cache/notebooks.db` is "user-authored state … EXCEPTION to the cache-exclusion policy" and is already an explicit entry in `ops/cron/arxmcp-backup.sh:89-95`. → **The new columns are auto-covered by the existing backup; no backup-script change required.** The AC "new columns included in restic backup scope" is satisfied by the existing include-list. (Document this in the discovery-model note so the AC's intent is traceable.)

---

## 3. Implementation plan (file-by-file)

### a) `server/notebooks_store.py`
- Bump `SCHEMA_VERSION` 4 → 5 (line 75).
- Add the v4→v5 block immediately after the `PRAGMA user_version = 4` line (~line 251), mirroring the v3→v4 block exactly:
  ```python
  if current_version < 5:
      conn.execute("ALTER TABLE notebooks ADD COLUMN discovery_category TEXT NOT NULL DEFAULT ''")
      conn.execute("ALTER TABLE notebooks ADD COLUMN description TEXT NOT NULL DEFAULT ''")
      conn.execute("PRAGMA user_version = 5")
  ```
  SQLite `ALTER TABLE ADD COLUMN … NOT NULL DEFAULT ''` backfills existing rows in O(1) — confirmed by both briefs and proven by v2→v3 / v3→v4.
- **Crash-safety (FM-3 — see §4):** the connection is `isolation_level=None` (autocommit), so the two ALTERs + the PRAGMA are three separate auto-committed statements; a crash between them re-runs the block and `ALTER TABLE` fails with `duplicate column name`. **Resolution (orchestrator decision):** make the v4→v5 block atomic. Preferred: wrap the three statements in an explicit `BEGIN`/`COMMIT`. **First, read the existing v2→v3 / v3→v4 blocks** — if they already run inside a transaction, follow that exact pattern for consistency; if they don't, add a `BEGIN`/`COMMIT` around the v4→v5 block only (do NOT retrofit older blocks — out of scope). Either way the block must be re-runnable without a `duplicate column` crash.
- **FM-4:** add `discovery_category, description` to the `SELECT` column lists in `list_notebooks()` (~283-299) and `get_notebook()` (~311-327) AND to the returned dicts. (Same pattern as `notebook_kind`/`parse_status`.) Omitting this silently drops the fields from API responses → forms appear empty on reload.
- **FM-5:** extend `create_notebook(...)` signature with `discovery_category: str = ""`, `description: str = ""` and include them in the INSERT. Add `update_topic(slug, discovery_category, description)` mirroring `update_display_name` (~394-416): `UPDATE notebooks SET discovery_category = ?, description = ? WHERE slug = ?`.

### b) `server/routes/notebooks.py`
- Module-level validation helper (honors the AC's literal "`if … raise`"):
  ```python
  _VALID_DISCOVERY_CATEGORIES = frozenset({"math.AG", "math.NT", "math-ph", "hep-th"})

  def _validate_discovery_category(value: str) -> None:
      if value and value not in _VALID_DISCOVERY_CATEGORIES:
          raise NotebookError(...)  # → HTTP 422 via existing NotebookError handler
  ```
  Empty string MUST be accepted (AC: "empty allowed" — FM-1). Pydantic `max_length` (category ≤32, description ≤512) is fine as defense-in-depth but the **explicit `if … raise` is the canonical enforcement** the AC names.
- Extend `NotebookCreate` (lines 193-215) with `discovery_category: str = Field(default="", max_length=32)` and `description: str = Field(default="", max_length=512)`; forward both into `store.create_notebook(...)` (FM-5).
- **Edit endpoint (divergence resolved → dedicated route):** add a new `NotebookTopicUpdate` model (`discovery_category`, `description` only) and a new `PATCH /ui/api/notebooks/{slug}/topic` route mirroring `rename_notebook` (~424-465): `validate_slug` → `_validate_discovery_category` → `store.update_topic(...)` → HTML fragment. **Do NOT widen the existing `NotebookRename`/rename endpoint** — keep its mass-assignment defense (brief-2 line 222) and the topic concern separate (brief-1's shape; lower blast radius than brief-2's combined `NotebookMetadataUpdate`).
- The returned topic fragment must carry `aria-live` if swapped via `hx-swap="outerHTML"` (brief-2 memory note), following the `_display_name_fragment` pattern.

### c) `frontend/templates/index.html` (create form)
- Add a `<select name="discovery_category">` with options `["" (Not specified), math.AG, math.NT, math-ph, hep-th]` and a `<textarea name="description" maxlength="512">` between "Display name" and submit. Client-side enum is defense-in-depth; server validation is authoritative. **No `| safe`.**

### d) `frontend/templates/notebook_detail.html` (edit form)
- Add a topic-metadata card mirroring the rename form (~31-46): `hx-patch="/ui/api/notebooks/{slug}/topic"`, `hx-target="#topic-block"`, `hx-swap="outerHTML"`, plus a static `<div id="topic-block">` showing current values. **No `| safe`.**

### e) `.claude/notes/notebook-discovery-model.md` (NEW)
- 1–2 pages: (1) field schema (`discovery_category` validated enum + free-text `description`); (2) propose→confirm model (operator confirms before ingest; no auto-ingest; no server-side LLM); (3) post-aggregation channel-dedup boundary — dedup happens AFTER merging all channel results, not inside each channel (CC-3/CC-4 from the roadmap). Note that backup scope is satisfied by the existing `notebooks.db` include-list.

### f) `tests/test_notebook_api.py` (extend)
- Follow the established additive-migration test pattern (~1063-1327): (1) seed a v4 DB with an existing notebook row via raw `sqlite3` + `PRAGMA user_version=4`, open via `NotebooksStore.open`, assert `discovery_category == ''` and `description == ''` on the legacy row and `user_version == 5`; (2) idempotency: open twice, columns stable, no crash (covers FM-3); (3) round-trip a non-empty category + description through the **create** endpoint and assert they persist + appear in `get_notebook`/`list_notebooks` (covers FM-4 + FM-5); (4) the topic PATCH endpoint updates both fields; (5) invalid `discovery_category` (e.g. `"math.QQ"`) → 422; empty string → accepted.

---

## 4. Failure modes → required mitigations (from brief-2, all in-scope)

| FM | Trigger | Mitigation (REQUIRED) |
|---|---|---|
| FM-1 | Validation set omits `""` | `frozenset` allows empty; only reject non-empty non-members. Test both. |
| FM-2 | `{{ description \| safe }}` added | Never use `\| safe`; autoescape already ON. Test renders an HTML-ish description safely. |
| FM-3 | Crash between the two ALTERs | Make the v4→v5 block atomic (BEGIN/COMMIT) OR tolerant of `duplicate column`; re-runnable. Idempotency test. |
| FM-4 | SELECTs not updated | Add both columns to `list_notebooks`/`get_notebook` SELECTs + dicts. HTTP-layer round-trip test. |
| FM-5 | Fields not forwarded to `create_notebook` | Forward from route → store → INSERT. Create-endpoint round-trip test. |

---

## 5. Orchestrator synthesis note (divergences resolved)

- **Validation style:** brief-1 (explicit `if … raise` helper) vs brief-2 (Pydantic `pattern`). **Resolved → explicit `if … raise` helper as canonical** (honors the AC's literal wording and §4.7), with Pydantic `max_length` as defense-in-depth. A Pydantic `pattern` alone would satisfy "not assert" but not the AC's explicit "`if … raise`" phrasing.
- **Edit endpoint:** brief-1 (new dedicated `/topic` route + `NotebookTopicUpdate`) vs brief-2 (single combined `NotebookMetadataUpdate` covering display_name too). **Resolved → brief-1's dedicated `/topic` route.** Keeps the rename endpoint's mass-assignment defense untouched and minimizes blast radius on shipped code; the combined endpoint is a larger change for no v1 benefit.
- **Migration atomicity:** brief-1 follows v3→v4 verbatim (no explicit txn); brief-2 flags FM-3 and recommends BEGIN/COMMIT. **Resolved → adopt brief-2's crash-safety**, but gated on first reading whether existing blocks already transact (consistency-first). This is a strict improvement with no downside.
- **Note filename:** both agree → `.claude/notes/notebook-discovery-model.md`.
- Both confirm: no MCP tool change, no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin, no backup-script change.

## 6. Open questions

None blocking. The two from brief-2 are resolved above (edit-endpoint shape → dedicated `/topic` route; note filename → `notebook-discovery-model.md`). The schema-shape question (one field vs two) was already fixed by the roadmap: ship BOTH `discovery_category` + `description`.

## 7. External writes required (deduped union)

**None.** Both briefs independently confirm the milestone is purely local — source edits, a local SQLite migration, frontend templates, a `.claude/notes/` design note, and tests. No git push, no PR, no infra mutation, no third-party API call.
