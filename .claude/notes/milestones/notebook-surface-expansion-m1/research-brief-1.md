# Research Brief — notebook-surface-expansion-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T00:00:00Z

---

## In-codebase context

### Design constitution applicability

- **`07-multi-agent-caching.md`**: This milestone is `/ui` HTML-only. It does NOT
  touch `server/tools.py::ALL_TOOLS`, the `tools/list` wire bytes, or any BP1/BP2
  breakpoints. `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` are
  byte-unchanged by this milestone. No tool-schema re-pinning required.
- **`06-mcp-server-design.md`**: The roadmap (`plans/notebook-surface-expansion-roadmap.md`,
  Phase 2, assumption `[MUST]`) states: "MCP resources + the instructions field can
  expose notebooks to agents WITHOUT changing ALL_TOOLS, the tools/list bytes, or the
  EXPECTED_TOOL_SCHEMA_SHA256 / EXPECTED_BP1_SHA256 hashes." m1 is UI-only; this
  assumption is not stressed.
- **`08-security-observability-ops.md`**: The roadmap designates `security-reviewer`
  for m1. Jinja2 autoescaping is the primary XSS defense; the implementer must confirm
  `parse_status` values are rendered safely.

### `ui_notebook_detail` handler — full text

`server/routes/ui.py`, lines 195–245:

```python
@router.get(
    "/notebooks/{slug}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def ui_notebook_detail(
    slug: str,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),  # noqa: B008  (FastAPI DI pattern)
) -> HTMLResponse:
    """Per-notebook detail page — paper list + paste form + upload
    card (the "open" link from the landing page).

    404 if the slug doesn't exist; 422 on a malformed slug.
    """
    try:
        validate_slug(slug)
    except NotebookError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    notebook = await store.get_notebook(slug)
    if notebook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notebook {slug!r} not found",
        )
    papers = await store.list_papers(slug)
    # m10 AC #2 — annotate each paper row with on-disk preview existence
    annotated_papers: list[dict[str, object]] = []
    for row in papers:
        paper_id = row.get("paper_id", "")
        has_preview = (
            isinstance(paper_id, str)
            and is_valid_arxiv_paper_id(paper_id)
            and _preview_html_path(slug, paper_id) is not None
        )
        annotated_papers.append({**row, "has_preview": has_preview})
    return templates.TemplateResponse(
        request=request,
        name="notebook_detail.html",
        context={"notebook": notebook, "papers": annotated_papers},
    )
```

**Context keys today:** `{"notebook": dict, "papers": list[dict]}`.
The template receives `notebook` (slug, display_name, lancedb_path, created_at,
notebook_kind, parse_status, parse_error, parsed_html_path) and `papers` (annotated
rows, each: paper_id, added_at, has_preview).

**KEY FINDING — `parse_status` is on `notebooks`, NOT `notebook_papers`.**
`store.list_papers(slug)` at lines 398–413 SELECTs only `paper_id, added_at FROM
notebook_papers` — there is NO `parse_status` column on `notebook_papers`. The
notebook_papers schema (lines 22–28 of docstring) has only `slug, paper_id, added_at`.

The brief's description says "reusing the existing `parse_status` on the
`notebook_papers` rows (`list_papers`)" — **THIS IS INACCURATE**. `parse_status`
lives on the `notebooks` table (added by the v3→v4 migration), and is already
returned by `store.get_notebook(slug)` (lines 302–328). It is a per-NOTEBOOK status
(skipped / pending / running / complete / failed), NOT a per-paper status.

**This is a load-bearing conflict between the milestone brief and the codebase.**

### `list_papers` return shape — exact

```python
# server/notebooks_store.py, lines 406–412
rows = self._conn.execute(
    "SELECT paper_id, added_at FROM notebook_papers "
    "WHERE slug = ? ORDER BY added_at DESC, paper_id ASC",
    (slug,),
).fetchall()
return [{"paper_id": r[0], "added_at": r[1]} for r in rows]
```

Return type: `list[dict[str, str]]` — keys `paper_id` and `added_at` only.
No `parse_status` key at all.

### `get_latest_ingest_run` return shape — exact

`server/notebooks_store.py`, lines 507–529:

```python
async def get_latest_ingest_run(
    self,
    slug: str,
) -> dict[str, str | int | None] | None:
    """Return the most recent ingest-run row for ``slug``, or
    ``None`` if no run has ever been triggered."""
    ...
    return {
        "id": row[0], "slug": row[1], "status": row[2],
        "started_at": row[3], "finished_at": row[4],
        "exit_code": row[5], "stderr_tail": row[6],
    }
```

Returns `None` when no ingest has ever been triggered. When present, keys are:
`id` (int), `slug` (str), `status` (str: "running"/"success"/"failed"),
`started_at` (ISO-8601), `finished_at` (ISO-8601 or None), `exit_code` (int or None),
`stderr_tail` (str or None).

**Freshness display rule:** use `finished_at` when status is `success/failed`
(most meaningful timestamp), fall back to `started_at` when `running`, and
display "never indexed" when `get_latest_ingest_run` returns `None`.

### `parse_status` enum domain — exact

`server/notebooks_store.py`, lines 600–605:

```python
#: Terminal-state values for the ``parse_status`` column.
PARSE_STATUS_SKIPPED: str = "skipped"
PARSE_STATUS_PENDING: str = "pending"
PARSE_STATUS_RUNNING: str = "running"
PARSE_STATUS_COMPLETE: str = "complete"
PARSE_STATUS_FAILED: str = "failed"
```

Note: the milestone brief says "pending/parsing/parsed/failed/skipped" — the actual
values are "pending/running/complete/failed/skipped" (no "parsing", no "parsed").

### Jinja2 autoescape — confirmed

`server/routes/ui.py`, lines 85–92:

```python
_env: jinja2.Environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(
        enabled_extensions=("html", "htm", "xml"),
        default_for_string=True,
    ),
)
templates: Jinja2Templates = Jinja2Templates(env=_env)
```

Autoescape is **explicit** for `.html`. Status strings from the DB (skipped/pending/
running/complete/failed) contain no special HTML characters — safe to render verbatim,
but autoescape covers any future edge cases. This is secure.

### `notebook_detail.html` — papers table markup — full

`frontend/templates/notebook_detail.html`, lines 104–150:

```html
<section class="card">
  <h2>Papers in this notebook ({{ papers|length }})</h2>
  {% if not papers %}
    <p class="empty">No papers yet. Add one above.</p>
  {% endif %}
  <table class="papers">
    <thead>
      <tr><th>Paper ID</th><th>Added</th><th>Preview</th><th></th></tr>
    </thead>
    <tbody id="papers-tbody">
      {% for p in papers %}
      <tr data-slug="{{ notebook.slug }}" data-paper-id="{{ p.paper_id }}">
        <td><code>{{ p.paper_id }}</code></td>
        <td><time>{{ p.added_at }}</time></td>
        <td>
          {% if p.has_preview %}
            <a href="/ui/notebooks/{{ notebook.slug }}/papers/{{ p.paper_id }}/preview"
               target="_blank"
               rel="noopener">Preview</a>
          {% else %}
            <span class="hint"
                  title="upload an ar5iv HTML to enable preview">Preview</span>
          {% endif %}
        </td>
        <td>
          <button type="button"
                  hx-delete="/ui/api/notebooks/{{ notebook.slug }}/papers/{{ p.paper_id }}"
                  hx-confirm="Remove paper '{{ p.paper_id }}' from notebook '{{ notebook.slug }}'?"
                  hx-on::htmx:after-request="if(event.detail.successful) this.closest('tr').remove()"
                  class="danger">
            Remove
          </button>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
```

Currently 4 columns: Paper ID / Added / Preview / (Remove button). The status column
is added as a new `<th>Status</th>` and per-row `<td>{{ p.parse_status }}</td>`.
The freshness line goes in the section header or a new `<section class="card">` or
as a `<p>` below the `<h2>` inside the existing Ingest section (best placement —
immediately after the ingest form, providing per-notebook context).

### `GET /ui/api/notebooks/{slug}/parse-status` handler

`server/routes/notebooks.py`, lines 1215–1255. Returns JSON
`{slug, notebook_kind, parse_status, parse_error, parsed_html_path}` — this is a
per-NOTEBOOK status endpoint, NOT per-paper. The status already flows through
`store.get_notebook()`, which is already called in `ui_notebook_detail`. This JSON
route is used by external pollers/scripts; the detail page has no need to make a
second call to it.

### Render vs htmx poll decision

**Recommendation: server-side render in `ui_notebook_detail` (one page load).**

The AC says "When the operator opens `/ui/notebooks/{slug}`" — this implies the
status is visible on page open, no polling required. All needed data is already
fetched in the handler: `store.get_notebook(slug)` returns `parse_status` on the
`notebook` dict; `store.get_latest_ingest_run(slug)` is a single additional DB call.
An htmx poll is optional polish (useful for live-ingest progress) but NOT required
by the AC and adds complexity. Server-side render is simpler, faster, and sufficient.

### Existing UI-render test pattern

`tests/test_ui_html_pages.py`, lines 43–80 — the canonical fixture:

```python
@pytest.fixture
def client(
    tmp_path: Path, notebooks_base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    import asyncio
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        app.mount("/ui/static", StaticFiles(directory=str(FRONTEND_STATIC)), name="ui-static")
        monkeypatch.setattr(notebooks_module, "_now_iso", lambda: "2026-05-22T16:00:00+00:00")
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()
```

The test for the new status column will:
1. Reuse this fixture as-is (or a minimal variant).
2. Create a notebook via `client.post("/ui/api/notebooks", json={"slug": "test-nb"})`.
3. Add a paper via `client.post("/ui/api/notebooks/test-nb/papers", json={...})`.
4. Seed an ingest run directly via `store.insert_ingest_run(...)` +
   `store.update_ingest_run(...)` (to get a `finished_at` timestamp) using the
   `loop.run_until_complete` pattern already in the fixture.
5. Assert `r.text` contains the status column header and the `parse_status` value,
   and the freshness signal ("last indexed" or "never indexed").

---

## Prior decisions and lessons

**Recent git log:** The freshest UI precedent is `notebook-ops-hardening-m4`
(`67864da`) — the `/ui/status-badge` htmx fragment. Its handler in
`server/routes/ui.py::ui_status_badge` (lines 147–178) shows the pattern for
server-side HTML generation with autoescaped values. The `_html.escape()` call
and the `<span id="...">` pattern are directly reusable for the freshness line.

**Concurrent work:** Recent log shows `corpus-integrity-observability-e3` (`2971010`)
and `corpus-integrity-observability-e2` (`4706ecf`) just landed. Those milestones
edit `server/health.py`, `server/metrics.py`, `ingest/`. m1 touches
`server/routes/ui.py`, `server/notebooks_store.py` (READ ONLY — one new async call),
and `frontend/templates/notebook_detail.html`. **No collision risk**.

**Banned patterns check:**
- No `assert` for invariants — handler uses `if … raise HTTPException`; continue
  this pattern.
- No `BaseHTTPMiddleware` — m1 adds no middleware.
- No `import anthropic` in server source — not applicable.
- No `claude-opus` string — not applicable.
- `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` — not touched by m1.
- No new MCP tools — confirms `EXPECTED_TOOL_SCHEMA_SHA256` unchanged.
- Doc placement: no new `.md` outside `.claude/`; test file goes in `tests/`.

**SecFetchSite middleware:** the freshness line and status column are rendered
server-side in the initial page load (not a new XHR endpoint), so no new
`exempt_prefixes` entry is needed. If an htmx poll were added later for live
status updates, the endpoint would need to live under `/ui/` — but the server-side
render recommendation avoids this entirely.

---

## External sources

This milestone is `/ui` HTML-only — no MCP tool surface changes, no caching
protocol changes. Reading `07-multi-agent-caching.md` confirms BP1/BP2 are not
at risk. No external docs are relevant.

---

## Recommendation

**Implement via server-side render in `ui_notebook_detail` — one additional DB call,
no new routes, no htmx polling.**

Exact implementation:

1. **Handler (`server/routes/ui.py::ui_notebook_detail`):**
   - After `papers = await store.list_papers(slug)`, add:
     `latest_run = await store.get_latest_ingest_run(slug)`
   - Pass `latest_run` in the template context:
     `context={"notebook": notebook, "papers": annotated_papers, "latest_run": latest_run}`
   - The `notebook["parse_status"]` is already in the context via the `notebook` dict
     (returned by `store.get_notebook(slug)`, which is already called). No extra store
     call needed for per-notebook parse_status.
   - **For per-paper status**: `parse_status` does NOT exist on `notebook_papers`.
     The only available per-notebook status is the `notebook["parse_status"]` field on
     the `notebooks` table. The "per-paper status" described in the brief is
     architecturally impossible without a schema change — but the AC says "no schema
     migration." The correct reading: render the notebook-level `parse_status` as
     a column value (same value for all rows) OR as a notebook-level status badge.
     Recommend a notebook-level status badge (one line, not a per-row column), plus
     the freshness line — this fulfills the AC spirit with no schema change.

2. **Template (`frontend/templates/notebook_detail.html`):**
   - Add a freshness `<p>` to the Ingest section:
     ```html
     {% if latest_run %}
       <p class="hint">Last indexed: <time>{{ latest_run.finished_at or latest_run.started_at }}</time> — status: <span class="status-{{ notebook.parse_status }}">{{ notebook.parse_status }}</span></p>
     {% else %}
       <p class="hint">Never indexed.</p>
     {% endif %}
     ```
   - Add a `<th>Status</th>` column and a per-row `<td>{{ notebook.parse_status }}</td>`
     (same value for all rows — this is the factually correct representation given the schema).

3. **Tests (`tests/test_ui_html_pages.py` or a new `tests/test_notebook_detail_status.py`):**
   - Mirror the `client` fixture exactly; seed ingest run via `loop.run_until_complete`;
     assert "last indexed" + "never indexed" + status values in `r.text`.

---

## Open questions

1. **Per-paper vs per-notebook status:** The brief says "each paper row shows its
   parse status" — but `parse_status` is on the `notebooks` table, not
   `notebook_papers`. The implementer must confirm: is the intent (a) render the same
   per-notebook status value in every paper row (architecturally honest, no schema
   change), or (b) actually add a `parse_status` column to `notebook_papers` (schema
   change, which the brief explicitly prohibits)? **Recommendation: (a). The AC says
   "no schema migration" — implement per-notebook status displayed in the paper table
   header or as a notebook-level badge, not per-row.**

2. **Freshness timestamp display:** Use `latest_run["finished_at"]` when status is
   `success` or `failed`; use `latest_run["started_at"]` when status is `running`.
   When `latest_run is None`, show "never indexed." This is a minor display decision
   the implementer can resolve inline.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no ticket, no infra
mutation. The m3 milestone (constitution refresh + UI-security-audit issue filed)
is the only external write in the Now lane — it is separate from m1.
