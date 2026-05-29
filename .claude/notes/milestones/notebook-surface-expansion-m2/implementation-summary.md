# Implementation Summary — notebook-surface-expansion-m2

**One-liner:** Operators can now rename a notebook in-page via an htmx
`PATCH /ui/api/notebooks/{slug}` (returns the re-rendered display-name fragment
for an `outerHTML` swap) and delete it in-page behind a confirm. (Epic e4 — UI
completion.)

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline — 4 files (store method + route + template + a
new test file).

---

## What landed

### `server/notebooks_store.py`
- New `update_display_name(self, slug, display_name) -> bool` (after
  `delete_notebook`). Single-column `UPDATE notebooks SET display_name = ?`,
  mirroring `delete_notebook`/`update_parse_status` (`async with self._lock` →
  `asyncio.to_thread(_update)` → `cur.rowcount > 0`). Returns `False` on unknown
  slug (handler → 404). NO schema migration (`display_name` exists at
  SCHEMA_VERSION 4); no escaping at the store layer (output-time escape).

### `server/routes/notebooks.py`
- New `NotebookRename(BaseModel)` — `display_name: str = Field(max_length=256)`
  ONLY (mass-assignment defense; no `min_length` → empty name clears).
- New `_display_name_fragment(display_name)` helper — Python f-string with
  `html.escape` per the existing `_paper_row_html` / `ui_status_badge` precedent
  (NOT a Jinja2 partial). Empty → `—`.
- New `_CONTROL_CHARS_RE` (`[\x00-\x1f\x7f]`) — strips control chars from the
  single-line display name (log-injection / single-line-render defense).
- New `@router.patch("/notebooks/{slug}")` `rename_notebook`: `validate_slug`
  first (→ 422 on malformed/traversal slug); strip control chars;
  `update_display_name` (→ 404 if unknown); return the escaped
  `#display-name-block` fragment (`HTMLResponse`).

### `frontend/templates/notebook_detail.html`
- The display name is now ALWAYS rendered as `<p class="display-name"
  id="display-name-block">{{ notebook.display_name or "—" }}</p>` (the stable
  htmx swap target), replacing the prior `{% if %}`-gated paragraph.
- A rename `<form hx-patch=... hx-target="#display-name-block"
  hx-swap="outerHTML">` (outside the swap target so it survives the swap; the
  base.html JSON-shim already serializes PATCH bodies to JSON).
- An in-page `Delete notebook` button wiring the existing
  `DELETE /ui/api/notebooks/{slug}` behind `hx-confirm`, navigating to `/ui/` on
  success (the just-deleted detail page would 404 on reload).

### `tests/test_notebook_rename_delete.py` (new, 13 tests)
Self-contained (mirrors `test_notebook_detail_status.py`: private-loop store +
REST seed through the TestClient portal; no model load). Covers rename
happy-path (200 + escaped fragment + persists), empty→`—`, malformed slug 422,
over-long (257) 422, exact-256 boundary accepted, nonexistent 404, control-char
strip, `<script>` XSS escape (fragment + detail page), mass-assignment ignored
(slug/kind unchanged, no `evil-nb` conjured); delete round-trip (list omits it,
sibling survives), delete malformed slug 422, delete nonexistent 404; detail
page renders the rename form + swap target + Delete button.

---

## Acceptance criteria status

- [x] **AC1 (G/W/T)** — rename form → `PATCH /ui/api/notebooks/{slug}` updates
  `display_name`; the `#display-name-block` row re-renders via htmx `outerHTML`
  swap; malformed slug → 422; over-long name → 422.
- [x] **AC2 (G/W/T)** — in-page Delete behind `hx-confirm`; the notebook is
  removed and the list re-renders without it (index.html delete was already
  wired in m7/m8; m2 adds a detail-page Delete + a round-trip test).
- [x] **AC3** — new PATCH route + `update_display_name` (NO migration); handler
  + template tests (rename happy-path, 422 malformed slug, over-long reject,
  delete round-trip) — all present, 13 tests.

## Deviations from the brief

None material. Two clarifications resolved in synthesis:
1. **Fragment via Python f-string + `html.escape`, not a Jinja2 partial** — the
   established codebase pattern (`_paper_row_html`, `ui_status_badge`). Avoids a
   one-off partial and a `| safe`.
2. **Detail-page Delete added** in addition to the pre-existing index.html
   delete. AC2's "list re-renders without it" was already met by index.html; the
   detail-page Delete completes the e4 "in-page DELETE" intent.

## Test surface

New: `tests/test_notebook_rename_delete.py` (13). Changed:
`server/notebooks_store.py`, `server/routes/notebooks.py`,
`frontend/templates/notebook_detail.html`. Adjacent suites
(`test_notebook_api.py`, `test_notebook_detail_status.py`,
`test_notebook_durability.py`) + byte-stability guards (`test_server_tool_schema.py`,
`test_prompts.py`, `test_ui_html_pages.py`) all green. `ruff check .` clean.

## Security (security-reviewer lens)

State-mutating surface on the un-audited UI. Defenses: `validate_slug` first
(path-traversal → 422); Pydantic `max_length=256` (over-long → 422);
`NotebookRename` carries only `display_name` (mass-assignment closed); control
chars stripped; `html.escape` in the fragment + Jinja2 autoescape on the detail
page (stored-XSS); loopback SecFetchSite `/ui` carve-out + Origin + Host
validation is the CSRF posture (no token, by design). No `| safe` introduced.

## Byte-stability / scope

No `server/tools.py`, `EXPECTED_TOOL_SCHEMA_SHA256`, `EXPECTED_BP1_SHA256`,
`server/prompts.py`, or `/mcp` change. `/ui/api/*` is disjoint from the frozen
7-tool surface. No `exempt_prefixes` change (PATCH is under `/ui`).

## External writes required

**None.** Purely local. Push at milestone end is per-event authorized.
