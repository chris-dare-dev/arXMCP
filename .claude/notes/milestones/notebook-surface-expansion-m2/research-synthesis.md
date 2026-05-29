# Research Synthesis — notebook-surface-expansion-m2

**Milestone:** Operator renames + deletes a notebook in-page (htmx).
**Mode:** standard (2× Sonnet). Both briefs `ok`, 0 external writes each.
**Implementation path:** INLINE (4 files + 1 new test file; < 200 LOC; no novel arch).

---

## Load-bearing decisions (orchestrator-resolved)

### D1 — Fragment rendering: Python f-string + `html.escape()` (NOT a Jinja2 partial)

The two briefs diverged here (brief-1: Python-string fragment like the existing
handlers; brief-2: a new `notebook_row.html` Jinja2 partial). **Resolved on
evidence in favor of brief-1.** The codebase already has TWO precedents that
build HTML fragments as Python f-strings escaping every value:
- `server/routes/ui.py::ui_status_badge` (lines 177-193) — `import html`,
  `safe = html.escape(summary)`, f-string fragment that re-emits its own
  `hx-get`/`hx-trigger`.
- `server/routes/notebooks.py::_paper_row_html` (lines ~1008-1030) — escapes
  `slug`, `paper_id`, `added_at` on every interpolation; `_ingest_status_fragment`
  (~1279) does the same.

A new Jinja2 partial would be the ONLY fragment in the repo rendered that way —
gratuitous inconsistency. The autoescape env stays the XSS guard for full-page
templates; hand-built fragments use `html.escape()` per-value. Adding a partial
+ `| safe` is explicitly banned.

### D2 — Rename lives on the DETAIL page; swaps ONLY the display-name `<p>`

AC1 says "the row re-renders with the new name (htmx swap)". The dependency note
("soft-after m1, same template") + the e4 epic ("in-page RENAME + DELETE") point
at `notebook_detail.html` (m1's file). Design:
- Header card: replace the conditional `{% if notebook.display_name %}<p
  class="display-name">…</p>{% endif %}` with an ALWAYS-rendered
  `<p class="display-name" id="display-name-block">{{ notebook.display_name or "—" }}</p>`
  so the swap target always exists.
- A rename `<form hx-patch="/ui/api/notebooks/{slug}"
  hx-target="#display-name-block" hx-swap="outerHTML">` sitting OUTSIDE the swap
  target (so the form survives the swap). The `base.html` JSON-shim already
  serializes PATCH bodies to JSON (`verb === 'patch'` handled at base.html:21,
  confirmed by brief-2) → the handler reads a JSON `NotebookRename` body.
- The PATCH handler returns the re-rendered `<p class="display-name"
  id="display-name-block">…</p>` fragment (escaped). `outerHTML` swap updates it
  in place — no full-page reload. This is the literal "row re-renders (htmx
  swap)" the AC asks for.

### D3 — Delete: index.html ALREADY wired; add a detail-page Delete too

Both briefs found `index.html:49-55` already has `hx-delete` + `hx-confirm` +
`location.reload()`. So AC2 ("the list re-renders without it") is ALREADY
satisfied on the index page — m2 adds a **test** locking the round-trip, not new
index UI. For completeness of "in-page DELETE", add a Delete button to the
detail header behind the same `hx-confirm`, redirecting to `/ui/` on success
(reloading the detail page of a just-deleted notebook would 404). Reuses the
existing wired `DELETE /ui/api/notebooks/{slug}` route — zero route change.

### D4 — Security hardening (security-reviewer lens)

- **Slug / path-traversal:** `validate_slug(slug)` FIRST in the handler →
  `NotebookError` → 422. Identical to the DELETE handler (notebooks.py:351). The
  regex `^[a-z][a-z0-9-]{2,30}$` rejects `../foo`, `foo/bar`, uppercase, shell
  metachars.
- **Over-long name:** Pydantic `display_name: str = Field(max_length=256)` →
  FastAPI 422 before the handler body. Same bound as `NotebookCreate`.
- **XSS:** `html.escape()` on the display_name in the returned fragment (D1).
  Initial template render is autoescaped. Never `| safe`.
- **Mass-assignment:** a dedicated `NotebookRename` model with ONLY
  `display_name`. slug/notebook_kind/parse_status are NOT acceptable PATCH
  fields. The store method takes only `(slug, display_name)`.
- **Control chars / log injection (brief-2 FM-3):** strip `[\x00-\x1f\x7f]` from
  `display_name` in the handler before the store write (single-line field; no
  legitimate control chars). Length only shrinks post-strip, so still ≤256.
- **CSRF:** the loopback triple-defense (SecFetchSite `/ui` carve-out +
  Origin + Host validation) is the designed posture; no token. A browser
  cross-site PATCH → `Sec-Fetch-Site: cross-site` → 403; same-origin passes;
  curl (no header) passes — acceptable loopback-only.

### D5 — Empty display_name is VALID

`display_name` default is `''`. The rename model has NO `min_length` — an empty
string clears the name (renders as `—`). The PATCH fragment renders
`html.escape(name) or "—"`.

---

## Implementation checklist

1. **`server/notebooks_store.py`** — add `update_display_name(self, slug, display_name) -> bool`
   right after `delete_notebook` (line 392), mirroring its body verbatim
   (`async with self._lock` → `_update()` single-column `UPDATE notebooks SET
   display_name = ? WHERE slug = ?` → `cur.rowcount > 0` → `asyncio.to_thread`).
   No `updated_at` column exists; do NOT add one. No schema bump.
2. **`server/routes/notebooks.py`** —
   - Add `NotebookRename(BaseModel)` with `display_name: str = Field(max_length=256)`
     near `NotebookCreate` (line ~210).
   - Add a module-level `_display_name_fragment(display_name: str) -> str` helper
     (f-string, `html.escape`, `or "—"`) next to `_paper_row_html`.
   - Add `@router.patch("/notebooks/{slug}", response_class=HTMLResponse)`
     `rename_notebook(slug, body: NotebookRename, store=Depends(...))`:
     validate_slug→422; strip control chars; `update_display_name`→404 if False;
     return `HTMLResponse(_display_name_fragment(cleaned))`.
3. **`frontend/templates/notebook_detail.html`** — always-render the
   `<p id="display-name-block">`; add the rename form (hx-patch, JSON-shim error
   handler like the paste form) + a detail-page Delete button (hx-confirm →
   redirect `/ui/`).
4. **`tests/test_notebook_rename_delete.py`** (new) — reuse the `detail_client`
   fixture pattern (new-event-loop store + TestClient portal + REST seed):
   rename happy-path (200, escaped new name in fragment, persists via GET detail);
   422 malformed slug; 422 over-long (257-char) name; 404 nonexistent slug;
   control-char strip; mass-assignment (extra `slug`/`notebook_kind` fields in
   body ignored — slug/kind unchanged); XSS (`<script>` → `&lt;script&gt;` in
   fragment, no raw tag); delete round-trip (DELETE → `list_notebooks` omits it);
   delete bad slug → 422; template GET asserts `hx-patch` rename form present.

---

## What this milestone does NOT touch (byte-stability / scope)

`server/tools.py`, `EXPECTED_TOOL_SCHEMA_SHA256`, `EXPECTED_BP1_SHA256`,
`server/prompts.py`, the `/mcp` transport, any MCP tool. `/ui/api/*` is the
browser REST surface — entirely disjoint from the frozen 7-tool surface. No
schema migration (display_name exists at SCHEMA_VERSION 4). No `exempt_prefixes`
change (PATCH is under `/ui`).

## Open questions

None blocking. (Brief-2's 3 "open questions" — swap target, empty-name allow,
detail-page delete — are all resolved above in D2/D5/D3.)

## External writes required

**None.** Purely local: SQLite method + FastAPI route + Jinja2 template + tests.
Push at milestone end is per-event authorized (not part of implementation).
