# Research Synthesis — notebook-paper-discovery-m4

**Orchestrator merge of research-brief-1 (route/add-wiring) + research-brief-2 (security/failure-modes)**
**Milestone:** Operator-console "Discover" panel (propose→confirm). Implement INLINE.
**Verdict:** Purely-local. No external writes. No MCP tool, no BP1 change. Both briefs converge.

---

## 1. Scope

Add a loopback `POST /ui/api/notebooks/{slug}/discover` route + a notebook-detail-page htmx panel
that lists discovered candidates (title + abstract) with per-row "Add" buttons. "Add" reuses the
existing add-paper route. The candidate queue is **ephemeral** (no new table; "Refresh to re-run").
This is the LAST Now-lane milestone — it turns the m3 driver into the operator surface.

---

## 2. The route (both briefs agree)

```python
@router.post("/notebooks/{slug}/discover", response_class=HTMLResponse,
             status_code=status.HTTP_200_OK, response_model=None)
async def discover_papers(slug, store=Depends(get_notebooks_store)) -> HTMLResponse:
```
- **No request body** — the Discover button sends no form fields; the base.html JSON-shim produces
  `{}` which a body-less handler ignores (brief-1 §base.html shim).
- Flow: `validate_slug(slug)` → 422 on `NotebookError`; then
  `await discover_for_notebook_async(store, slug, contact_email=get_contact_email(), sleep=time.sleep)`.
- **MUST call the m3 ASYNC core** `discover_for_notebook_async(store, slug, …)` — NOT the sync
  `discover_for_notebook()` (its `asyncio.run` inside a running loop raises
  `RuntimeError: This event loop is already running`; both briefs flag this).
- **Error handling (FM-B/FM-C):** catch `ValueError` (notebook missing / no `discovery_category` →
  a friendly "set a topic first" error fragment) and `(RuntimeError, OSError)` (arXiv unreachable /
  error-entry → "Discovery failed: arXiv unreachable" fragment). **Never let an exception reach the
  default 500 handler.** Return the error as an htmx fragment (HTTP 200) so the panel renders it.
- **contact_email** from `server.operator_settings.get_contact_email()` (sync SQLite read; may be
  `None` — fine, `fetch_candidates` accepts `None`). `ARXMCP_CONTACT_EMAIL` env is rejected by the
  server (CLAUDE.md §9), so the settings store is the source.
- **Blocking I/O (FM-E):** `fetch_candidates` is synchronous `urllib` (up to 60s timeout) and blocks
  the single uvicorn worker for the request. **Accepted for v1** (loopback single-operator console;
  both briefs concur). Document it in the route docstring; `MAX_RESPONSE_BYTES` (m2) caps the
  response. Do NOT add `asyncio.to_thread` in v1 (the core interleaves async store calls + the sync
  fetch; wrapping cleanly is a restructure not worth it for a single user).
- **Middleware:** `/ui/api/notebooks/{slug}/discover` is under the `/ui` exempt prefix of
  `SecFetchSiteMiddleware` and inherits `OriginValidationMiddleware` — no middleware change (FM-F).

---

## 3. The fragment renderer (f-string + html.escape — THE security requirement)

New `_discover_results_fragment(slug, candidates: list[DiscoveryCandidate]) -> str` in
`server/routes/notebooks.py`, mirroring `_paper_row_html` / `_topic_fragment`: a Python f-string
returned via `HTMLResponse` (NOT a Jinja2 partial — autoescape does NOT apply to f-strings).

**XSS is the primary risk (brief-2 FM-A):** `title` and `abstract_head` come from the arXiv API
(external, untrusted, NOT regex-validated like `paper_id`). EVERY interpolated value MUST be
`html.escape(...)`; **never `| safe`**. A malicious arXiv title `<script>` must render inert.

Fragment shape:
- Outer `<div id="discover-results" aria-live="polite" aria-atomic="true">` (the htmx
  `hx-swap="outerHTML"` target — must re-emit `aria-live` on every branch, ui-attractive-polish-m1
  lesson).
- Empty state: "No new candidates found." + the ephemeral notice.
- Per candidate: a row showing `html.escape(title)` + `html.escape(abstract_head)` + a mini-form:
  ```
  <form hx-post="/ui/api/notebooks/{slug}/papers" hx-target="#papers-tbody"
        hx-swap="beforeend" hx-disabled-elt="find button">
    <input type="hidden" name="arxiv_url" value="https://arxiv.org/abs/{html.escape(paper_id)}">
    <button type="submit">Add</button>
  </form>
  ```
- A visible "Results are not saved — Refresh to re-run discovery" notice (ephemeral-queue AC).

---

## 4. "Add" wiring — REUSE the existing add-paper route (both briefs, option (c))

The AC says "Add → ingested into LanceDB AND recorded in notebook_papers." Verified reality
(brief-1 lines 39-47, brief-2 OQ-1): the existing `POST /ui/api/notebooks/{slug}/papers` route
records ONLY the `notebook_papers` junction row; **LanceDB embedding is a SEPARATE step** — the
operator clicks "Ingest now" (`POST .../ingest` → `IngestTaskTracker` subprocess reading
`papers.txt`). There is **no `ingest_one_paper` route-layer symbol** (the discovery-model note's
wording was aspirational). URL-paste adding works the same way today: add → junction; ingest → embed.

**Resolution (both briefs → option (c)):** the Discover panel's "Add" button POSTs to the EXISTING
`/papers` route with `arxiv_url=https://arxiv.org/abs/{paper_id}`. This reuses the validated,
tested, htmx-aware handler (returns the `<tr>` fragment via `_paper_row_html`, 201, `beforeend` into
`#papers-tbody`) with **zero new add-paper code**. LanceDB embedding remains the operator's existing
"Ingest now" action — consistent with URL-paste.

**Deviation to record in the implementation summary:** "Add" records the paper in `notebook_papers`
(reusing the existing route); LanceDB embedding is the existing separate "Ingest now" step, NOT an
auto-trigger on Add. This matches the established console pattern (URL-paste never auto-ingests) and
the propose→confirm model. Auto-ingest-on-Add would be a heavier divergence from the codebase and is
out of scope for v1; if the operator wants embedding they click "Ingest now" exactly as today.

---

## 5. Template (`frontend/templates/notebook_detail.html`)

Add a `<section class="card">` (e.g. after the Topic & discovery card) with:
- An `<h2>Discover papers</h2>` + a hint line ("Find new arXiv papers for this notebook's topic.").
- A Discover `<form>`/button: `hx-post="/ui/api/notebooks/{slug}/discover"`,
  `hx-target="#discover-results"`, `hx-swap="outerHTML"`, `hx-disabled-elt="find button"`, with an
  error `<pre id="discover-error" aria-live="polite">`.
- A static `<div id="discover-results" aria-live="polite">` placeholder labeled
  "Results are not saved — click Discover to (re-)run." (the ephemeral-queue label; the swap replaces
  this div with the fragment from §3). **No `| safe`** anywhere; no Node/SPA.

This adds a 7th htmx-bound form on the detail page → update
`tests/test_ui_m3_dark_and_htmx_feedback.py::test_forms_use_find_button_not_this` form-count (it is
currently 6 = 1 index + 5 detail; the Discover form makes it 7) and ensure the Discover/Add forms use
`hx-disabled-elt="find button"`.

---

## 6. Failure modes → required mitigations (brief-2, all in-scope)

| FM | Trigger | Mitigation |
|---|---|---|
| A | hostile arXiv `title`/`abstract` | `html.escape` every interpolated field; no `\| safe`. **Primary risk.** |
| B | arXiv down / error-entry | catch `(RuntimeError, OSError)` → error fragment, never 500. |
| C | notebook has no `discovery_category` | catch `ValueError` → "set a topic first" fragment (not 500). |
| D | malformed slug | `validate_slug(slug)` first → 422 (m6 path-traversal defense). |
| E | event-loop block during fetch | accepted for v1 loopback; documented; `MAX_RESPONSE_BYTES` caps response. |
| F | CSRF / cross-origin | inherited `SecFetchSite` + `OriginValidation` on `/ui/*`; no change. |
| G | ephemeral-queue confusion | visible "not saved — refresh to re-run" label (AC). |

---

## 7. Tests (TestClient + NotebooksStore + monkeypatched `_arxiv_api._fetch_url`)

New `tests/test_discover_route.py` using the `test_notebook_api.py` `client`-fixture pattern (minimal
FastAPI app + notebooks router + a real tmp `NotebooksStore`), monkeypatching `_arxiv_api._fetch_url`:
- **Discover happy path:** seed a topic'd notebook + a feed with ≥N entries → `POST /discover` returns
  200 + a fragment containing candidate titles + abstracts, `id="discover-results"`, `aria-live`.
- **XSS (FM-A):** a feed entry with `title=<script>alert(1)</script>` → the fragment contains
  `&lt;script&gt;`, NOT raw `<script>`.
- **Dedup:** a paper already in `notebook_papers` is absent from the fragment.
- **Unconfigured (FM-C):** empty `discovery_category` → 200 error fragment with a "topic" hint, no 500.
- **arXiv failure (FM-B):** `_fetch_url` stub raises `URLError`/`RuntimeError` → error fragment, no 500.
- **Bad slug (FM-D):** `POST /ui/api/notebooks/..%2f../discover`-style → 422 (validate_slug).
- **Add wiring:** the fragment's mini-form `hx-post`s to `.../papers` with
  `value="https://arxiv.org/abs/<paper_id>"` and `hx-target="#papers-tbody"`.
- Confirm `tests/test_ui_m3_dark_and_htmx_feedback.py` form-count test updated (6 → 7) and the existing
  suite stays green; `EXPECTED_TOOL_SCHEMA_SHA256` unchanged (no ALL_TOOLS edit).

---

## 8. Doc update

Add a short line to `.claude/notes/notebook-discovery-model.md` (§2/§4) noting m4 SHIPPED the panel as
the propose→confirm surface, "Add" reuses the add-paper route (embedding via the existing Ingest step),
and the candidate queue is ephemeral. Markdown only under `.claude/` (CLAUDE.md §1).

---

## 9. Orchestrator synthesis note (divergences)

Effectively none — both briefs independently reached the same design: async-core call, reuse-add-paper
(option c), html.escape-everything, no `to_thread` for v1, error fragments not 500. Brief-2 marked
itself "partial" but its content is complete and corroborates brief-1. The only judgement call is the
AC's "ingested into LanceDB" → resolved to the established two-step (Add=junction, Ingest=embed) and
recorded as a documented deviation (§4).

## 10. Open questions

None blocking. OQ-1 ("Add = metadata-only vs auto-ingest") resolved to reuse the existing add-paper
route (§4); the rest are resolved in §2–§5.

## 11. External writes required

**None.** New route + fragment in `server/routes/notebooks.py`, a template section in
`notebook_detail.html`, a note line in `notebook-discovery-model.md`, a form-count test update, and a
new `tests/test_discover_route.py`. The arXiv call is the m2/m3-owned egress. Both briefs confirm.
`state.external_writes_required = []`.
