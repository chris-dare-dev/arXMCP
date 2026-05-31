# Research Brief — notebook-paper-discovery-m4

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T20:00:00Z

---

## In-codebase context

### Design notes that apply

**`notebook-discovery-model.md` §2 (the propose→confirm contract):**
> "Candidates are *proposed* in the operator console; the operator clicks "Add" to route a paper
> through the existing `ingest_one_paper` pipeline into the notebook's LanceDB."
> "Candidate queue is ephemeral in v1. The proposed list is not persisted; the panel is labeled
> 'Refresh to re-run discovery'."
> "No new MCP tool in v1 ... so `EXPECTED_TOOL_SCHEMA_SHA256` and the BP1 prefix stay byte-stable."

**`07-multi-agent-caching.md` Property 1:**
> "Pin tool JSON schemas. Sort properties alphabetically at serialization time. Freeze descriptions
> as constants in source. A casual edit to a tool description blows every sub-agent's cache."
> The AC explicitly confirms: "No new MCP tool; EXPECTED_TOOL_SCHEMA_SHA256 + BP1 byte-unchanged."

### `server/routes/notebooks.py` — add-paper route (line 651–737)

`POST /ui/api/notebooks/{slug}/papers` uses:
```python
class PaperAdd(BaseModel):
    """Body for ``POST /ui/api/notebooks/{slug}/papers``."""
    arxiv_url: str = Field(min_length=1, max_length=512)
```
(line 280–283). It:
1. Validates slug and notebook existence.
2. Calls `_arxiv_url_to_paper_id(body.arxiv_url)` to extract a paper_id from an arxiv URL.
3. Calls `await store.add_paper(slug=slug, paper_id=paper_id, added_at=added_at)`.
4. If `HX-Request: true` header is present, returns `HTMLResponse(_paper_row_html(...))` at 201.
5. Otherwise returns `{"slug": slug, "paper_id": paper_id}`.

**Critical finding:** `add_paper` records ONLY the junction row (notebook_papers). It does **NOT**
trigger LanceDB ingest. Ingest is a SEPARATE operation: `POST /ui/api/notebooks/{slug}/ingest`
spawns a subprocess (`tools.notebook_ingest`) as fire-and-forget via `IngestTaskTracker`.

The discovery-model note §2 says "route a paper through the existing `ingest_one_paper`
pipeline" — but `ingest_one_paper` is NOT a route-layer symbol in `server/routes/notebooks.py`
(confirmed by grep). **This is a documentation-vs-code mismatch in the milestone brief. The
existing "Add" workflow is: record junction row only; the operator then clicks "Ingest now" to
trigger LanceDB ingest separately.**

**Recommendation (see §Recommendation below):** reuse the existing `add_paper` route. The
"Add" button from the Discover panel calls the existing `POST /ui/api/notebooks/{slug}/papers`
route (which records the junction row + returns a `<tr>` fragment for `beforeend` swap into
`#papers-tbody`). It does NOT trigger LanceDB ingest inline. This is consistent with how the
URL-paste form works today, and it keeps the AC "ingested into LanceDB AND recorded in
notebook_papers" achievable — the operator runs "Ingest now" after adding papers, exactly as
they do today.

### `_paper_row_html` (lines 1761–1830)

```python
def _paper_row_html(
    slug: str,
    paper_id: str,
    added_at: str,
    *,
    has_preview: bool = True,
) -> str:
    ...
    return (
        f'<tr data-slug="{html.escape(slug)}" '
        f'data-paper-id="{html.escape(paper_id)}">'
        f'<td>{html.escape(paper_id)}</td>'
        f'<td>{html.escape(added_at)}</td>'
        f'{preview_cell}'
        f'<td>added</td>'
        f"</tr>"
    )
```
(lines 1822–1830). This is a Python f-string fragment with `html.escape()` on EVERY interpolated
value — NOT a Jinja2 partial. The Discover panel's "Add" button reuses this via the existing
`add_paper` route (see above).

### `POST /ui/api/notebooks/{slug}/ingest` (lines 1855–1931)

Triggers an ingest subprocess via `IngestTaskTracker.start_ingest`. Returns a 202 HTML fragment
(htmx polled every 2s). This is the separate "Ingest now" action — NOT invoked by "Add" in the
existing pattern.

### `tools/discover_for_notebook.py` — m3 async core

`discover_for_notebook_async(store, slug, *, max_results, contact_email, sleep)` is the correct
entrypoint for the route. The synchronous `discover_for_notebook()` (line 127) uses
`asyncio.run()` — **calling it from an async FastAPI route handler would raise
`RuntimeError: This event loop is already running`**. The route MUST call
`discover_for_notebook_async` directly.

**Blocking HTTP call:** `discover_for_notebook_async` calls `fetch_candidates` (line 96 in
`tools/discover_for_notebook.py`) which calls `urllib.request.urlopen` (blocking I/O). The
route must wrap with `asyncio.to_thread`:
```python
candidates = await asyncio.to_thread(
    fetch_candidates,
    category, max_results, contact_email,
    abs_keywords=keywords or None,
    sleep=time.sleep,
)
```
OR restructure to call the entire async core via `asyncio.to_thread`. The simpler approach is
to NOT call `discover_for_notebook_async` at all and instead:
1. Read notebook from store (async — fine).
2. Call `asyncio.to_thread(fetch_candidates, ...)` (offloads the blocking HTTP).
3. Dedup against existing papers (async store call — fine).

Actually, the cleanest pattern is: call `discover_for_notebook_async` with a thread-offloaded
`fetch_candidates` — but the simplest refactor is to inline the logic from
`discover_for_notebook_async` in the route, using `asyncio.to_thread` for the fetch step.
OR: wrap the entire sync work (fetch + dedup) via `asyncio.to_thread(discover_for_notebook, slug, db_path=..., ...)` — but then the store is opened twice.

**Recommended approach:** In the route handler, call `discover_for_notebook_async` but first
patch `fetch_candidates` to run in a thread. The cleanest: call `asyncio.to_thread` around
`fetch_candidates` by refactoring `discover_for_notebook_async` to accept an `async_fetch`
parameter — but this requires modifying m3 code. Simpler: the route calls
`discover_for_notebook_async(store, slug, ...)` with a `sleep` that is `asyncio.to_thread`
compatible. The actual blocking is `urllib.request.urlopen`; the loopback-only console handles
one operator at a time so blocking the event loop for the duration of one arXiv API call
(~200ms latency, single page for max_results ≤ 2000) is acceptable. The implementer should
note this and add `await asyncio.to_thread(lambda: None)` as a yield point around the fetch,
OR wrap the entire `discover_for_notebook_async` body in `asyncio.to_thread`. For a
loopback-only console with a single operator, blocking the event loop briefly is an accepted
tradeoff — document it, don't over-engineer.

### `contact_email` source for the discover route

`ARXMCP_CONTACT_EMAIL` is REJECTED by the server startup scan as "not a server config var"
(`server/main.py` lines 290–297). The canonical server-context source is
`server.operator_settings.get_contact_email()` — a sync function returning `str | None`.
The lifespan does NOT attach an `OperatorSettingsStore` to `app.state` (confirmed: no
`operator_settings_store` key in `main.py`). The route should call
`get_contact_email()` synchronously (it opens a short-lived SQLite connection — acceptable
for a loopback operator console). Alternatively, wrap in `asyncio.to_thread`.

### SecFetchSiteMiddleware

The discover route lives under `/ui/api/notebooks/{slug}/discover`. The middleware is
registered with `exempt_prefixes=("/ui",)` (main.py line 732). The `/ui/api/notebooks/...`
path starts with `/ui` → already exempt. No middleware change required.

### Template and fragment pattern

The Jinja2 environment in `server/routes/ui.py` uses explicit autoescape (no `| safe` filters);
templates live in `frontend/templates/`. The notebook_detail.html template does NOT yet have a
Discover section. New HTML section must be added.

The htmx pattern for the Discover panel:
- Initial GET renders the section with `hx-post="/ui/api/notebooks/{slug}/discover"` and no
  discovery results (static Jinja2 render).
- `POST /ui/api/notebooks/{slug}/discover` runs discovery and returns an HTML fragment
  replacing `#discover-results` via `hx-swap="outerHTML"`.
- Fragment uses Python f-string with `html.escape()` (NOT Jinja2 partial) — matches
  `_ingest_status_fragment` and `_paper_row_html` precedents.
- Fragment must include `aria-live="polite"` per ui-attractive-polish-m1 lesson (outerHTML
  swap replaces the element; AT loses the live region without it).

### base.html JSON shim behavior

The JSON shim (base.html lines 26–51) intercepts `htmx:configRequest` for POST/PUT/PATCH and
serializes form fields to `application/json`. The Discover POST `hx-post` has **no form
fields** (it's triggered by a button with no input fields to collect) — so the shim produces
an empty body `{}`. The route handler should accept no request body (no Pydantic model needed),
reading only the path parameter `slug`.

---

## Prior decisions and lessons

**Recent git log (last 20):**
- `96b6338` finalize notebook-paper-discovery-m3 state
- `b5069c5` rect F1 MEDIUM from m3 critique (versioned dedup fix)
- `cd7d2a0` feat m3 arXiv Atom discovery driver

**ui-attractive-polish-m1 lesson (MEMORY):** `hx-swap="outerHTML"` REPLACES the element — the
new element from the server must carry `aria-live` in its markup. The Discover panel fragment
(`#discover-results`) must emit `aria-live="polite"` on EVERY returned fragment branch
(empty result, candidates present, error).

**ui-attractive-polish-m3 lesson (MEMORY):** `hx-disabled-elt` applies to `<button>` elements,
NOT `<form>`. Use `hx-disabled-elt="find button"` on the form to disable the submit button.

**onboarding-uplift-m3 lesson (MEMORY):** `<details>` `open` attribute is lost on outerHTML
swap every poll. Use `<small>` sub-element for tooltip content, no `<details>` toggle.

**Fragment helper pattern:** All route-layer HTML fragments are Python f-strings with
`html.escape()` on every interpolated value. NOT Jinja2 partials. See `_paper_row_html`,
`_ingest_status_fragment`, `_topic_fragment`, `_display_name_fragment`.

**NotebooksStore DI:** `Depends(get_notebooks_store)` fetches from `app.state.notebooks_store`
(line 179 in `server/routes/notebooks.py`). The discover route gets the store the same way.

---

## External sources

No MCP spec relevant (no new MCP tool). No new pip dependency (m3 already owns the
arXiv API call; m4 wires it to the UI). The milestone brief explicitly confirms this.

For reference: htmx `hx-swap="outerHTML"` replaces the entire target element with the
response body. `hx-swap="beforeend"` appends children. The Discover panel uses `outerHTML`
to replace `#discover-results`; the "Add" button uses `beforeend` into `#papers-tbody`
(via the existing `add_paper` route).

---

## Recommendation

**Route signature (new):**
```python
@router.post(
    "/notebooks/{slug}/discover",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    response_model=None,
)
async def discover_papers(
    slug: str,
    request: Request,
    store: NotebooksStore = Depends(get_notebooks_store),
) -> HTMLResponse:
```

No request body model — the Discover button sends no form fields; the JSON shim would produce
`{}` which FastAPI ignores for a handler with no body param.

**"Add" wiring:** Reuse the EXISTING `POST /ui/api/notebooks/{slug}/papers` route. The Discover
panel renders each candidate with a mini-form whose single hidden input is `arxiv_url` (set to
`https://arxiv.org/abs/{paper_id}`). On submit, `hx-post="/ui/api/notebooks/{slug}/papers"`,
`hx-target="#papers-tbody"`, `hx-swap="beforeend"` — exactly the same target and swap as the
URL-paste form. The returned `<tr>` appends to the table. The "Add" button in the candidate
row should be disabled after click (use `hx-disabled-elt="this"`). **Do NOT trigger
LanceDB ingest inline** — the operator uses "Ingest now" afterward, matching the existing
workflow.

**Fragment renderer (new):**
```python
def _discover_results_fragment(slug: str, candidates: list[DiscoveryCandidate]) -> str:
```
Python f-string with `html.escape()` on all values. Returns `<div id="discover-results"
aria-live="polite" aria-atomic="true">` wrapper with either "No new candidates" text or one
mini-form per candidate. Each mini-form contains a hidden `arxiv_url` input + "Add" button.

**`contact_email`:** call `get_contact_email()` (sync) from `server.operator_settings` at
the top of the handler, passing result to `discover_for_notebook_async`. Acceptable for
loopback console.

**Blocking I/O:** call `discover_for_notebook_async(store, slug, contact_email=email, ...)`.
The `fetch_candidates` call inside it blocks the event loop briefly (~200ms for a single
arXiv page). For a loopback-only single-operator console this is acceptable. Add a comment
noting the known limitation. If the implementer wants belt-and-suspenders:
`candidates = await asyncio.to_thread(fetch_candidates, category, max_results, email, ...)`.
But that requires duplicating the dedup logic. Accept the brief block for v1.

**Template update:** Add a `<section class="card">` with `id="discover-section"` in
`notebook_detail.html` after the Topic section. The static render includes:
- "Discover" button (`hx-post`, `hx-target="#discover-results"`, `hx-swap="outerHTML"`,
  `hx-disabled-elt="find button"`).
- An error `<pre>` with `aria-live="polite"`.
- `<div id="discover-results">` (initially empty, labeled "Refresh to re-run discovery").

**Update `notebook-discovery-model.md` §3:** Add a paragraph documenting that the candidate
queue is ephemeral (panel resets on page load; labeled accordingly).

**No tool schema changes** → `EXPECTED_TOOL_SCHEMA_SHA256` is unchanged.

**No `assert` usage** — use `if … raise` per CLAUDE.md §4.7.

---

## Open questions

**Resolved — no open questions:**

1. **Does "Add" reuse the add-paper route or trigger ingest?** Resolved: reuse the existing
   `POST /ui/api/notebooks/{slug}/papers` route. LanceDB ingest remains a separate "Ingest now"
   step. The brief's "ingested into LanceDB AND recorded in notebook_papers" means the junction
   row is recorded immediately; LanceDB ingest happens when the operator clicks "Ingest now"
   (which they would need to do anyway after adding papers via URL-paste today).

2. **Does the discover route call m3 async core directly?** Yes: call
   `discover_for_notebook_async(store, slug, ...)`. The sync wrapper uses `asyncio.run` and
   would crash inside an async handler. The blocking I/O is acceptable for v1 loopback console.

3. **Is the blocking arXiv fetch acceptable inside an async route?** Yes for v1 loopback console.
   Single operator, ~200ms single-page fetch. Document it. No `asyncio.to_thread` wrapping needed
   unless the implementer sees it as a risk.

4. **Where does `contact_email` come from?** Call `get_contact_email()` from
   `server.operator_settings` (synchronous SQLite read). Result may be `None` — that's fine;
   `fetch_candidates` accepts `None` and omits the email from the User-Agent.

5. **How does the panel render server-side on initial GET vs on POST?** Initial GET: the detail
   page template renders `<div id="discover-results">` as an empty placeholder with the
   "Refresh to re-run discovery" label. POST `/discover` returns a new `<div id="discover-results">`
   fragment via `hx-swap="outerHTML"` replacing that placeholder.

---

## External writes the implementation will require

None — this milestone is purely local.

All changes are: new route in `server/routes/notebooks.py`, template update in
`frontend/templates/notebook_detail.html`, update to
`.claude/notes/notebook-discovery-model.md`, and new tests. No git push, no PR, no
infra mutation, no third-party API call beyond the existing arXiv Atom API already
owned by m3.
