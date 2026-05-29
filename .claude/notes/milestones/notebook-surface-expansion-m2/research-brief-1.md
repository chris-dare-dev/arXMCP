# Research Brief — notebook-surface-expansion-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T17:15:00Z

---

## In-codebase context

### 1. NotebooksStore mutation pattern

The store is in `server/notebooks_store.py`. Every public method follows this pattern:

```python
async def delete_notebook(self, slug: str) -> bool:
    async with self._lock:
        def _delete() -> bool:
            cur = self._conn.execute(
                "DELETE FROM notebooks WHERE slug = ?", (slug,)
            )
            return cur.rowcount > 0
        return await asyncio.to_thread(_delete)
```

The pattern: `async with self._lock` → define a sync inner function → `await asyncio.to_thread(inner)`. No `isolation_level=None` complications at the method level — the connection was opened with `isolation_level=None` and WAL, so each `execute` auto-commits.

**Return contracts by method:**
- `create_notebook(...)` → `None` (raises `sqlite3.IntegrityError` on dup slug)
- `delete_notebook(slug)` → `bool` (`True` if row deleted, `False` if not found)
- `update_parse_status(slug, ...)` → `bool` (`True` if row updated, `False` if slug unknown)
- `update_ingest_run(run_id, ...)` → `None` (always — run_id always valid at call point)

**`update_parse_status` body (verbatim — this is the exact precedent):**
```python
async def update_parse_status(
    self,
    slug: str,
    status: str,
    *,
    parse_error: str | None = None,
    parsed_html_path: str | None = None,
) -> bool:
    async with self._lock:
        def _update() -> bool:
            sets: list[str] = ["parse_status = ?"]
            params: list[object] = [status]
            if parse_error is not None:
                sets.append("parse_error = ?")
                params.append(parse_error)
            if parsed_html_path is not None:
                sets.append("parsed_html_path = ?")
                params.append(parsed_html_path)
            params.append(slug)
            cur = self._conn.execute(
                f"UPDATE notebooks SET {', '.join(sets)} WHERE slug = ?",
                tuple(params),
            )
            return cur.rowcount > 0
        return await asyncio.to_thread(_update)
```

**`updated_at` column:** There is NO `updated_at` column in the `notebooks` table. Schema DDL at v4 has: `slug`, `display_name`, `lancedb_path`, `created_at`, `notebook_kind`, `parse_status`, `parse_error`, `parsed_html_path`. Do NOT add one — the brief says no migration.

**`update_display_name` exact shape to write:**
```python
async def update_display_name(self, slug: str, display_name: str) -> bool:
    async with self._lock:
        def _update() -> bool:
            cur = self._conn.execute(
                "UPDATE notebooks SET display_name = ? WHERE slug = ?",
                (display_name, slug),
            )
            return cur.rowcount > 0
        return await asyncio.to_thread(_update)
```
Return `bool` (mirrors `delete_notebook`/`update_parse_status`). `False` → 404 at the handler. No dynamic `sets` list needed — single column update. `display_name` is already validated upstream via Pydantic `max_length=256`.

---

### 2. Route + Pydantic-input pattern

**`NotebookCreate` (verbatim):**
```python
class NotebookCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=256)
    notebook_kind: str = Field(default="arxiv", pattern="^(arxiv|textbook)$")
```
`display_name` max is 256 — the PATCH body model must use the same bound.

**`validate_slug` (tools/_notebook_common.py, verbatim):**
```python
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")

def validate_slug(slug: str) -> None:
    # raises NotebookError if slug doesn't match SLUG_RE
```
A malformed slug → `NotebookError` → caught → `HTTPException(422)`. This is the existing path-traversal defense for the `DELETE /notebooks/{slug}` handler (line 351–356 in notebooks.py).

**Existing `DELETE /notebooks/{slug}` handler (verbatim excerpt, lines 334–366):**
```python
@router.delete(
    "/notebooks/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_notebook(
    slug: str,
    store: NotebooksStore = Depends(get_notebooks_store),
) -> None:
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    deleted = await store.delete_notebook(slug)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    return None
```

**New `NotebookRename` Pydantic body model:**
```python
class NotebookRename(BaseModel):
    display_name: str = Field(max_length=256)
```
No `min_length` on `display_name` — the column allows empty string (default `""`). Pydantic `max_length=256` enforces the over-long-name reject automatically → 422 response from FastAPI's validation layer before the handler body runs.

**New PATCH handler shape:**
```python
@router.patch(
    "/notebooks/{slug}",
    status_code=status.HTTP_200_OK,
    response_class=HTMLResponse,
)
async def rename_notebook(
    slug: str,
    body: NotebookRename,
    store: NotebooksStore = Depends(get_notebooks_store),
) -> Response:
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    updated = await store.update_display_name(slug, body.display_name)
    if not updated:
        raise HTTPException(status_code=404, detail=f"notebook {slug!r} not found")
    # Return HTML fragment for htmx swap (see §3 below)
    ...
```

**How slug → 422 works:** path-param is a plain `str` (no regex in the route), `validate_slug()` raises `NotebookError`, caught → `HTTPException(422)`. This is identical to all other handlers.

**How over-long-name → 422 works:** Pydantic `Field(max_length=256)` on the body model. FastAPI returns 422 with a `RequestValidationError` before the handler body executes — no manual length check needed.

---

### 3. htmx UI wiring

**Existing htmx patterns in templates:**

`notebook_detail.html` has these htmx usages:
- Paper URL-paste form: `hx-post + hx-on::htmx:after-request="if(event.detail.successful) location.reload()"` — full-page reload on success
- Upload form: `hx-post + hx-target="#papers-tbody" + hx-swap="beforeend"` — fragment insert
- Ingest form: `hx-post + hx-target="#ingest-status" + hx-swap="outerHTML"` — fragment replace
- Ingest poll: `hx-get + hx-trigger="load"` then `hx-trigger="every 2s"` on returned fragment
- Paper remove button: `hx-delete + hx-confirm + hx-on::htmx:after-request="if(event.detail.successful) this.closest('tr').remove()"`

`index.html` has:
- Notebook delete button (verbatim): `hx-delete="/ui/api/notebooks/{{ nb.slug }}" hx-confirm="..." hx-on::htmx:after-request="if(event.detail.successful) location.reload()"`

**Key finding — DELETE already wired in index.html.** The `index.html` already has a working `hx-delete` button with `hx-confirm` for each notebook row (line 49–55 of `frontend/templates/index.html`). The milestone brief says to wire the DELETE "into the UI behind a confirm" — this is ALREADY DONE. The implementer should verify this is working end-to-end (the handler exists, the button exists), and the m2 work is the RENAME only from a UI-wiring standpoint, PLUS the brief's acceptance criteria specifically call out a confirm for delete — confirm the index.html button is already there.

**PATCH support in htmx:** htmx supports `hx-patch` natively (htmx core feature since v1.x). The vendored `frontend/static/htmx.min.js` must be checked to confirm version supports PATCH. This is standard htmx — no concern.

**PATCH handler response:** The handler must return an HTML fragment (not a full-page reload) for the htmx row-swap. The `ui_status_badge` handler in `server/routes/ui.py` (lines 159–193) is the exact fragment-return precedent:
```python
@router.get("/status-badge", response_class=HTMLResponse, include_in_schema=False)
async def ui_status_badge(request: Request) -> HTMLResponse:
    ...
    return HTMLResponse(content=fragment)
```
The PATCH handler should return `HTMLResponse(content=<rendered display_name HTML>)`.

**Where the rename form goes:** In the notebook detail page header section (`<section class="card">` containing the `<h2>{{ notebook.slug }}</h2>`), inline after the display_name paragraph. The form targets a `<span id="display-name-display">` or similar — use `hx-patch` → `hx-target="#display-name-cell"` → `hx-swap="outerHTML"`.

**SecFetchSiteMiddleware carve-out:** `server/main.py` line 581 wires: `app.add_middleware(SecFetchSiteMiddleware, exempt_prefixes=("/ui",))`. The new `PATCH /ui/api/notebooks/{slug}` is under `/ui/api/` which starts with `/ui` — it IS covered by the existing carve-out. No change to `exempt_prefixes` needed. Browser-issued PATCH from `/ui/` pages will carry `Sec-Fetch-Site: same-origin` — permitted by the carve-out.

---

### 4. Test-harness pattern

**`detail_client` fixture (verbatim, from `tests/test_notebook_detail_status.py` lines 40–75):**
```python
@pytest.fixture
def detail_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path]]:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(
        notebooks_module, "_now_iso", lambda: "2026-05-28T16:00:00+00:00"
    )
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        app.mount(
            "/ui/static",
            StaticFiles(directory=str(FRONTEND_STATIC)),
            name="ui-static",
        )
        with TestClient(app) as c:
            yield c, db_path
        loop.run_until_complete(store.close())
    finally:
        loop.close()
```

**M2 test structure recommendation:** Create `tests/test_notebook_rename_delete.py`. Reuse the `detail_client` fixture as-is (import from the m1 test file OR duplicate it — duplication is safer to avoid cross-file fixture coupling). Use the same `_create_notebook` helper pattern.

**Required test cases per AC:**
1. `test_rename_happy_path` — PATCH with valid `display_name`, assert 200, assert returned HTML contains new name.
2. `test_rename_malformed_slug_422` — PATCH to `/ui/api/notebooks/../etc/passwd`, assert 422.
3. `test_rename_over_long_name_422` — PATCH with `display_name` of 257 chars, assert 422.
4. `test_rename_nonexistent_404` — PATCH to valid but absent slug, assert 404.
5. `test_delete_round_trip` — DELETE a notebook that exists, assert 204, GET list → slug absent.
6. `test_delete_rejects_bad_slug_422` — DELETE malformed slug, assert 422 (already covered in `test_notebook_api.py::TestNotebookCrud::test_delete_rejects_bad_slug` but add one for completeness).

**Template test:** Use `detail_client` to GET `/ui/notebooks/{slug}` and assert that the rename form appears in the HTML (e.g. `assert 'hx-patch' in r.text` or `assert 'display-name' in r.text`). Mirrors the m1 test approach of checking badge presence via substring.

---

## Prior decisions and lessons

**Recent git log (last 15 commits):**
- `096be65 chore(notes): finalize notebook-surface-expansion-m1 state -> complete` — m1 is the direct predecessor; same template file
- `41a7309 rect(server): close notebook-surface-expansion-m1 critique (1M 1L; 1L deferred)` — m1 had a deferred finding; check what it was
- `934ecba feat(server): notebook detail parse-status + freshness (notebook-surface-expansion-m1)` — last template change commit

**Memory — jinja2-autoescape-explicit-construction (from MEMORY.md):** `server/routes/ui.py` constructs Jinja2 with explicit `autoescape=jinja2.select_autoescape(enabled_extensions=("html","htm","xml"), default_for_string=True)`. Zero `| safe` filters exist in any template. **NEVER introduce `| safe` for `display_name` or other operator-controlled fields** (stored-XSS vector). The `display_name` is operator-authored text — it MUST go through autoescaping. The PATCH handler that returns an HTML fragment must use `html.escape()` directly (the `_paper_row_html` precedent) or render via `templates.TemplateResponse`.

**Memory — SecFetchSiteMiddleware-blocks-cross-path-htmx-XHR:** htmx XHRs from `/ui/*` pages to paths NOT under `/ui/` carry `Sec-Fetch-Site: same-origin` and would be blocked. The PATCH route at `/ui/api/notebooks/{slug}` IS under `/ui/` — no issue.

**Schema at v4:** `display_name TEXT NOT NULL DEFAULT ''` exists since v1 (initial schema). SCHEMA_VERSION is 4. **No migration needed** — confirmed by reading `_open_sync`. The column is there.

**No MCP surface touched:** This milestone touches `server/routes/notebooks.py` (add PATCH), `server/notebooks_store.py` (add `update_display_name`), `server/routes/ui.py` if any template rendering change needed, and `frontend/templates/notebook_detail.html`. It does NOT touch `server/tools.py`, does NOT add/modify any MCP tool. Therefore `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning and `EXPECTED_BP1_SHA256` is unaffected.

---

## External sources

No external vendor docs are required. This milestone touches no MCP tool surface (no spec changes needed) and no caching layer (no prompt-cache doc needed). The htmx `hx-patch` support is a core feature since htmx 1.0 — no external lookup required. The vendored `frontend/static/htmx.min.js` should be visually confirmed to be htmx ≥1.0 by checking the first comment line, but this is not a blocker.

---

## Recommendation

Implement `update_display_name` as a simple single-column UPDATE returning `bool` (mirrors `delete_notebook`), add a `NotebookRename` Pydantic model with `display_name: str = Field(max_length=256)`, and wire `PATCH /ui/api/notebooks/{slug}` returning an `HTMLResponse` fragment (following the `_ingest_status_fragment` / `_paper_row_html` Python-string pattern — NOT a Jinja2 template render — for self-contained testability). The fragment must `html.escape()` the `display_name` value before interpolation. The rename form in `notebook_detail.html` should go in the header card, using `hx-patch` targeting the display-name element with `hx-swap="outerHTML"`.

For DELETE: the `index.html` already has a working `hx-delete` + `hx-confirm` button. The PATCH handler is the only new route. Tests go in `tests/test_notebook_rename_delete.py` using the `detail_client` fixture pattern from `tests/test_notebook_detail_status.py`.

Do NOT write a Jinja2 partial template for the fragment — inline Python string with `html.escape()` is the established pattern in this codebase and keeps the handler self-contained.

---

## Open questions

No open questions — implementation can proceed on the above recommendation. The one thing to verify mechanically (not a blocker): confirm the vendored htmx version in `frontend/static/htmx.min.js` supports `hx-patch` (all htmx ≥1.0 does). If it is htmx 1.x, `hx-patch` is supported. If the file is absent or malformed, alert and halt.

---

## External writes the implementation will require

None — this milestone is purely local.
