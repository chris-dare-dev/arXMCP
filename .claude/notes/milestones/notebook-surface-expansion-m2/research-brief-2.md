# Research Brief — notebook-surface-expansion-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T16:10:00Z

## In-codebase context

### slug validation — first-line path-traversal defense

From `tools/_notebook_common.py:47`:
```python
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")
```
And from `tools/_notebook_common.py:58–76`:
> "Raises NotebookError. This is the FIRST check every script's main() performs,
> before any path construction."

The `validate_slug` helper is already called on every path-param slug in the
existing DELETE handler (`server/routes/notebooks.py:351`). The PATCH handler
MUST call it first, before any body parsing, to match the existing pattern.
Slug constraints: lowercase ASCII letter start, then 2–30 chars of `[a-z0-9-]`,
total length 3–31. `../foo`, `foo/bar`, uppercase, shell metacharacters all rejected.

### display_name — existing field, no migration needed

From `server/notebooks_store.py:75`: `SCHEMA_VERSION: int = 4`. The `display_name`
column exists at v4 with default `''` (confirmed at line 17 schema DDL).
No migration is required for this milestone.

The existing `NotebookCreate` Pydantic model (`server/routes/notebooks.py:205`):
```python
display_name: str = Field(default="", max_length=256)
```
The new PATCH body model MUST enforce the same `max_length=256`. The store
has no `update_display_name` method yet — it must be added, following the
same pattern as `update_parse_status` (lines 607–645): single `async with
self._lock` + `asyncio.to_thread(_update)` + parameterized SQL UPDATE.

### Jinja2 autoescape — the XSS defense is in place

From `server/routes/ui.py:85–91`:
```python
_env: jinja2.Environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(
        enabled_extensions=("html", "htm", "xml"),
        default_for_string=True,
    ),
)
```
Templates render `{{ nb.display_name }}` and `{{ nb.display_name or "—" }}`
(confirmed in `frontend/templates/index.html:45` and `notebook_detail.html:11`)
with NO `| safe` filter. Autoescape is load-bearing; the implementation MUST
NOT introduce `| safe` on any display_name rendering.

The memory entry `jinja2-autoescape-explicit-construction` confirms: "Zero
`| safe` filters exist in any template. This is load-bearing — never introduce
`| safe` for `display_name` or other operator-controlled fields (stored-XSS
vector)."

### SecFetchSite — PATCH on /ui/* is already covered

From `server/middleware.py:556–561`:
```python
_UI_ALLOWED_VALUES: frozenset[bytes] = frozenset({
    b"none", b"same-origin",
})
```
And from `server/main.py:581`:
```python
app.add_middleware(SecFetchSiteMiddleware, exempt_prefixes=("/ui",))
```
Path `/ui/api/notebooks/{slug}` starts with `/ui`, so `is_exempt_path=True`.
A browser PATCH from the same origin sends `Sec-Fetch-Site: same-origin` →
passes. A PATCH from another local app (cross-site) sends `Sec-Fetch-Site:
cross-site` → 403. CLI tools (curl) send no header → passes. This behavior
is correct for loopback-only.

**CSRF analysis:** No CSRF token mechanism exists in this project. The defense
is layered:
1. `SecFetchSiteMiddleware` blocks `cross-site` / `same-site` from any other
   origin to `/ui/*`.
2. `OriginValidationMiddleware` blocks non-loopback Origins.
3. `HostValidationMiddleware` blocks non-loopback Hosts.
This triple-layer is the designed CSRF defense for the loopback-only threat
model. No additional CSRF token needed.

### DELETE route — already wired in UI

`frontend/templates/index.html:50–55` already has:
```html
<button type="button"
        hx-delete="/ui/api/notebooks/{{ nb.slug }}"
        hx-confirm="Remove notebook '{{ nb.slug }}' from the UI? ..."
```
The `hx-confirm` dialog IS the confirmation gate. The milestone brief says
"wire the existing DELETE into the UI behind a confirm" — this is ALREADY
DONE in m7/m8. No new DELETE wiring is needed for the confirm; it already
exists. The implementation should verify the confirm text is adequate and
add the missing `hx-on::htmx:after-request` to remove the row (the existing
code only does `location.reload()`).

**KEY FINDING:** The DELETE in `index.html` already has `hx-confirm` — the
"wire DELETE behind a confirm" AC appears to be about optionally making it do
an htmx swap instead of `location.reload()`, OR it refers to adding a Delete
button on the notebook_detail page as well. The route already exists; the UI
already calls it with confirm. Verify with researcher-1 at merge.

### htmx PATCH support

htmx 2.0.10 is vendored at `frontend/static/htmx.min.js` (confirmed by
`base.html:8`). `hx-patch` has been supported since htmx 1.0.0 — all htmx
HTTP method attributes (`hx-get`, `hx-post`, `hx-put`, `hx-patch`,
`hx-delete`) are part of the core spec.

The JSON-shim in `base.html:18–44` explicitly handles PATCH at line 21:
```javascript
if (verb !== 'post' && verb !== 'put' && verb !== 'patch') return;
```
PATCH requests will automatically get `Content-Type: application/json` and
JSON-serialized body — the same path POST uses. No shim change needed.

### MCP tool surface — NOT touched

`/ui/api/*` is the browser REST surface, entirely separate from the frozen
7-tool `/mcp` surface. This milestone does NOT add or modify any entry in
`server/tools.py::ALL_TOOLS`. **No `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning
required.** No BP1/BP2 cache impact.

### delete_notebook — DB-row-only, var/ tree preserved

From `server/routes/notebooks.py:17–22`:
> "DELETE /ui/api/notebooks/{slug} is metadata-only — the on-disk LanceDB /
> BM25 / ar5iv assets under var/arxmcp/notebooks/{slug}/ are NOT touched.
> Destructive on-disk wipe is the explicit job of tools/notebook_purge.py (m6)."

`NotebooksStore.delete_notebook` (lines 378–392) executes only:
```python
"DELETE FROM notebooks WHERE slug = ?", (slug,)
```
No filesystem mutation. ON DELETE CASCADE in the schema removes the
`notebook_papers` rows for that slug.

## Prior decisions and lessons

Recent git log confirms `notebook-surface-expansion-m1` (commit `096be65`)
completed just prior. The `_lock = asyncio.Lock()` on the `NotebooksStore`
instance is the serialization mechanism for all SQLite operations.

From `tests/test_notebook_api.py:63–86`, the test fixture pattern uses
`asyncio.new_event_loop()` + `loop.run_until_complete(NotebooksStore.open(db_path))`
because the store is opened on a new loop that closes before the TestClient
(which uses its own portal loop). New tests for the PATCH route MUST follow
this exact pattern — do NOT use `asyncio.get_event_loop()` on Python 3.12
(raises RuntimeError).

Memory entry `SecFetchSiteMiddleware-blocks-cross-path-htmx-XHR`: "Any new
endpoint that htmx polls from /ui/ pages must be added to `exempt_prefixes`
in `create_app`, OR placed under /ui/ itself." The PATCH endpoint will be at
`/ui/api/notebooks/{slug}` — already under `/ui` prefix, already covered.

## External sources

**htmx `hx-patch`:** htmx 2.0.10 supports `hx-patch` natively. The attribute
is documented since htmx 1.0.0 and is present in the vendored file. The
response shape for a PATCH that succeeds should return the updated table row
HTML fragment (200 + HTML) to enable htmx `outerHTML` swap of the `<tr>`.

**MCP spec (2025-06-18):** The `/ui/api/*` REST surface is NOT part of the
MCP protocol. The MCP spec governs only the `tools/list` and `tools/call`
exchanges over the `/mcp` transport. No MCP spec consultation required for
this milestone.

**Anthropic prompt-caching docs:** No cache impact — this milestone does not
change `server/tools.py::ALL_TOOLS` or `server/prompts.py`.

## Recommendation

Implement the PATCH as a thin, security-hardened handler following the exact
pattern of the existing DELETE handler: (1) call `validate_slug(slug)` first,
raising 422 on failure; (2) parse a `NotebookRename` Pydantic model with only
`display_name: str = Field(max_length=256)` — no other fields accepted, closing
mass-assignment; (3) strip control chars / newlines from `display_name` before
store write (a `re.sub(r'[\x00-\x1f\x7f]', '', value)` guard); (4) call a new
`NotebooksStore.update_display_name(slug, display_name)` → 404 if not found;
(5) render and return the updated `<tr>` HTML fragment for htmx `outerHTML`
swap. The store method follows the `update_parse_status` pattern verbatim:
`async with self._lock` + `asyncio.to_thread` + parameterized UPDATE.

For the DELETE confirm: the confirm dialog is already in `index.html`. The
implementation need only verify it exists and matches the brief's intent. If
the brief requires adding a Delete button on `notebook_detail.html` as well,
add it there with the same `hx-confirm` pattern and `location.reload()`.

## Open questions

1. **htmx swap target for PATCH rename:** Should the PATCH return the updated
   `<tr>` row HTML fragment (htmx `outerHTML` swap) or return 204 and let
   `location.reload()` refresh the page? The brief says "row re-renders (htmx
   swap)" which implies an `outerHTML` swap of the `<tr>`. The implementer
   should choose htmx `outerHTML` swap for the rename, consistent with the
   brief — this is the more elegant htmx idiom and avoids a full-page reload.
   Recommended: return the rendered `<tr>` fragment via a Jinja2 template
   fragment (add a `notebook_row.html` partial).

2. **Empty string display_name on rename:** `display_name=""` is the default
   and is a valid stored value. The PATCH handler MUST allow empty string (it
   means "clear the display name"). Pydantic's `min_length` must NOT be set
   on the rename model's `display_name` field.

3. **Delete confirm on notebook_detail page:** The milestone brief says "wire
   the existing DELETE into the UI behind a confirm" — `index.html` already
   has it. Does the brief also want a Delete button on `notebook_detail.html`?
   If yes, add it there. If no, the AC is already met by existing code. The
   implementer should check and document the decision.

## External writes the implementation will require

None — this milestone is purely local. No git push, ticket, PR, or infra
mutation. All changes are SQLite + FastAPI route + Jinja2 template modifications
within the repo.

---

## Failure-mode analysis (≥5 modes)

**FM-1: PATCH on a nonexistent slug.** Trigger: `PATCH /ui/api/notebooks/no-such-slug`.
Symptom without guard: `update_display_name` returns `False` (rowcount=0); if
handler doesn't check, it returns 200 with stale data. Mitigation: check the
bool return; raise HTTP 404 if `False`, same as the DELETE handler (line 359–363).

**FM-2: display_name with HTML/script injection.** Trigger: `{"display_name":
"<script>alert(1)</script>"}`. Symptom: stored in DB, rendered by Jinja2.
Mitigation: Jinja2 `autoescape` is the defense — `{{ nb.display_name }}` is
HTML-escaped at render time. Do NOT add `| safe`. Autoescape is explicit and
load-bearing (confirmed in `server/routes/ui.py:87–90`). Additionally, strip
control chars / newlines in the handler to prevent log injection.

**FM-3: display_name with Unicode control chars / newlines.** Trigger:
`{"display_name": "name\x00\nSECOND LINE"}`. Symptom: newlines in display_name
render as text in HTML (autoescape handles `\n` → not dangerous in HTML, but
ugly in single-line field; `\x00` silently truncates in some C paths).
Mitigation: strip `[\x00-\x1f\x7f]` in handler before writing.

**FM-4: Concurrent rename + delete of the same notebook.** Trigger: PATCH
and DELETE race at the same time. Symptom: `update_display_name` returns True
(UPDATE before DELETE) but DELETE succeeds and removes the row; or DELETE runs
first, then UPDATE returns False (rowcount=0) → 404. Both outcomes are correct:
the `asyncio.Lock` in `NotebooksStore` serializes all operations, so the two
calls queue up and one wins cleanly. No deadlock risk (SQLite WAL allows
concurrent reads; the single-writer Lock is the Python-level serializer).

**FM-5: Cross-event-loop asyncio.Lock trap in tests.** Trigger: `NotebooksStore`
opened on `loop = asyncio.new_event_loop()` then the TestClient (Starlette)
runs on its own portal loop. The `asyncio.Lock` is bound to the loop it was
created on. If the TestClient's portal loop is different from the one that
opened the store, `await self._lock.acquire()` will block forever or raise.
Mitigation: the existing test fixture (lines 71–86 in `test_notebook_api.py`)
creates the store on `asyncio.new_event_loop()` and the TestClient runs
synchronously in the same thread — `TestClient` uses `anyio`'s portal, which
runs async code on the store's loop via the portal bridge. New tests for PATCH
MUST use the same `asyncio.new_event_loop()` + `TestClient` fixture pattern.

**FM-6: Mass-assignment via PATCH body.** Trigger: `{"display_name": "ok",
"slug": "new-slug", "notebook_kind": "textbook", "parse_status": "pending"}`.
Symptom: without body model restriction, the handler might forward unexpected
fields to the store. Mitigation: use a dedicated `NotebookRename(BaseModel)`
with ONLY `display_name: str = Field(max_length=256)`. Pydantic strips any
extra fields by default (`model_config = ConfigDict(extra="ignore")` or just
rely on Pydantic v2 default). The store method accepts only `slug` + `display_name`.

**FM-7: Over-long display_name bypass.** Trigger: PATCH with 500-char
`display_name`. Symptom: stored in DB, rendered in table cell (cosmetic issue,
also potential DoS if memory-backed). Mitigation: Pydantic `Field(max_length=256)`
enforced by FastAPI; returns 422 before handler body executes.
