# Research Brief — notebook-paper-discovery-m4

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T20:10:00Z

---

## In-codebase context

### m3 consumer interface: async vs sync

`tools/discover_for_notebook.py` exports two callables:

- `discover_for_notebook_async(store, slug, *, max_results, contact_email, sleep) -> list[DiscoveryCandidate]` — **async**, takes an already-open `NotebooksStore`.
- `discover_for_notebook(slug, *, db_path, max_results, contact_email, sleep) -> list[DiscoveryCandidate]` — **sync wrapper**, calls `asyncio.run(_run())`.

The new FastAPI route handler MUST call `discover_for_notebook_async(store, slug, ...)` directly — calling the sync wrapper `discover_for_notebook()` inside an async route would invoke `asyncio.run()` inside a running event loop and raise `RuntimeError: This event loop is already running`.

The `NotebooksStore` dependency is already available via `Depends(get_notebooks_store)` — the same pattern used by every existing route in `server/routes/notebooks.py`. No second store instance needs to be opened.

### fetch_candidates is synchronous (urllib) — blocking the event loop

`tools/_arxiv_api._fetch_url` uses `urllib.request.urlopen(req, timeout=60.0)` — a synchronous blocking call. When `discover_for_notebook_async` calls `fetch_candidates(...)`, that synchronous network I/O runs on the asyncio event loop thread, blocking uvicorn from serving any other request for up to 60 seconds.

For the loopback single-user operator console this is **acceptable but must be noted**. The design rationale from `notebook-discovery-model.md §2`: "The discovery driver issues official-API queries… Relevance judgment belongs to the calling agent." There is no concurrent-request concern for a single operator. Wrapping with `asyncio.to_thread(fetch_candidates, ...)` is the correct mitigation if desired, but the milestone brief does not mandate it and the existing m3 design makes no such requirement. The MAX_RESPONSE_BYTES=50MB cap guards against a hostile-large response inflating the process.

**Recommendation: implement without `asyncio.to_thread` for v1, document the blocking behavior in the route docstring. The single-user loopback context makes this acceptable.**

### SecFetchSite + OriginValidation — the new route inherits protection

`server/main.py:732`: `app.add_middleware(SecFetchSiteMiddleware, exempt_prefixes=("/ui",))`. The new POST `/ui/api/notebooks/{slug}/discover` lives under `/ui/api/` which starts with `/ui`, so it falls under the exempt prefix and gets the relaxed allow-set `{none, same-origin}`. Cross-site requests are still rejected. The `OriginValidationMiddleware` also applies. No changes to middleware are needed for the new route.

Per `server/middleware.py:604-606` the exempt-prefix match is prefix-based (not substring): `path == p or path.startswith(p + "/")`. The path `/ui/api/notebooks/{slug}/discover` satisfies `path.startswith("/ui/")` — confirmed safe.

### html.escape is mandatory for candidate fragments (f-string path)

`server/routes/notebooks.py` uses Python f-strings (not Jinja2 partials) for all htmx fragment responses. Verbatim from the `_paper_row_html` docstring (line 1773): "All interpolated values are HTML-escaped via `html.escape` — paper_id is regex-validated upstream and cannot contain HTML-significant characters today, but escaping is defensive". The `_display_name_fragment` docstring (line 477): "the escape here IS the XSS guard for the fragment path. Never wrap this in `| safe`".

The new candidate-row fragment MUST follow the same pattern: `html.escape(title)` and `html.escape(abstract_head)` for every interpolated value. The `title` and `abstract_head` fields come from the arXiv Atom API (external, untrusted) — they are NOT validated upstream like `paper_id` is. This is the **primary XSS risk** for the new route.

Jinja2 autoescape only protects `*.html` templates rendered through the `jinja2.Environment` in `server/routes/ui.py:86-92`. The htmx fragment in the new `/discover` endpoint is a Python f-string returned via `HTMLResponse` — autoescape does NOT apply. `html.escape()` is the only protection.

### DiscoveryCandidate fields

From `tools/discover_for_notebook.py:40-53`:
```python
@dataclass(frozen=True)
class DiscoveryCandidate:
    paper_id: str
    title: str
    abstract_head: str
    submitted_date: str
```

### "Add" wiring: notebook_papers + ingest trigger

The AC requires: "Add -> ingested into LanceDB + recorded in notebook_papers." Two-step approach:
1. Call `store.add_paper(slug=slug, paper_id=paper_id, added_at=_now_iso())` — records the junction row.
2. Then trigger the ingest pipeline (`IngestTaskTracker.start_ingest`) so the paper gets fetched and embedded into the notebook's LanceDB.

**However**: the `IngestTaskTracker` spawns `python -m tools.notebook_ingest <slug>` as a subprocess, which runs `run_bulk_ingest` against `papers.txt`. Papers added via `store.add_paper()` are in the junction table — but `notebook_ingest` reads from `papers.txt` on disk, not from `notebook_papers`. The route must also append the paper_id to `papers.txt` before triggering ingest, OR the `Add` response defers LanceDB ingest to the operator's "Run Ingest" button (which already exists in the UI).

**This is a key design question** — see Open Questions below.

### No new MCP tool

From `notebook-discovery-model.md §2` (verbatim): "No new MCP tool in v1. The discovery surface is the operator console, not the MCP tool surface — so `EXPECTED_TOOL_SCHEMA_SHA256` and the BP1 prefix stay byte-stable." Confirmed: the milestone brief's AC explicitly states `EXPECTED_TOOL_SCHEMA_SHA256` and BP1 are byte-unchanged.

### Ephemeral-queue contract

From `notebook-discovery-model.md §4` (verbatim): "no candidate-queue persistence table (queue is ephemeral until a milestone needs otherwise)." The panel must be labeled "Refresh to re-run discovery" — no new table, no new store.

### Validate slug before any store access

All existing routes in `server/routes/notebooks.py` call `validate_slug(slug)` first and raise HTTP 422 on failure. The new `/discover` route must follow this exact pattern (path-traversal defense, m6 F1/F3).

### ValueError from discover_for_notebook_async maps to 422 (not 500)

From `tools/discover_for_notebook.py:82-89`: raises `ValueError` when notebook not found OR when `discovery_category` is not set. The route must catch `ValueError` and return a clean error response (422 or an htmx error fragment) — never let it propagate to a 500 stack trace.

---

## Prior decisions and lessons

From git log: m1-m3 shipped cleanly with the three-commit pattern. No failed pre-commit hooks. The m3 driver (`discover_for_notebook.py`) was shipped as a `tools/` module, not in `server/`. The route for m4 lives in `server/routes/notebooks.py`.

From `MEMORY.md` (2026-05-31 onboarding-uplift-m3): `hx-swap="outerHTML"` loses `<details>` open state on every poll. The Discover panel does not need polling (it's a one-shot POST response), so this hazard does not apply here.

From `MEMORY.md` (2026-05-31 ui-attractive-polish-m3): `button.htmx-request` CSS selector will NOT dim a submit button on form submission — need `form.htmx-request button[type="submit"]` as additional selector.

From `MEMORY.md` (2026-05-31 notebook-ops-hardening-m4): `SecFetchSiteMiddleware` blocks cross-path htmx XHRs. New endpoints hit from `/ui/*` pages must be under `/ui/` or explicitly added to `exempt_prefixes`. The `/discover` path is under `/ui/api/` which is already under the `/ui` exempt prefix — no change needed.

---

## External sources

### MCP spec (2025-06-18)

Not needed for this milestone — no MCP tool surface change. The milestone brief explicitly confirms `EXPECTED_TOOL_SCHEMA_SHA256` is byte-unchanged.

### Anthropic prompt-caching docs

Not needed — no tool-schema change, no BP1/BP2 impact.

### arXiv API

The m2 `_arxiv_api.py` already handles the arXiv Atom API. No new API surface. The polite User-Agent pattern (`tools/arxiv_fetch.py`) is already wired.

---

## Failure-mode analysis (security-reviewer focus)

### FM-A: XSS via unescaped candidate title or abstract_head

**Trigger:** arXiv returns a paper with title `<script>alert(1)</script>` or abstract containing HTML-special chars. The route renders these into a Python f-string `HTMLResponse` without escaping.

**Symptom:** Script executes in the operator's browser. Although the attacker would need to get such a title into arXiv, the arXiv API is external and its response is untrusted per `08-security-observability-ops.md` Threat 7.

**Mitigation:** Apply `html.escape(c.title)`, `html.escape(c.abstract_head)`, `html.escape(c.paper_id)` in every candidate-row f-string fragment. This is mandatory, not optional. The `_paper_row_html` precedent does exactly this. **Do NOT use `| safe` anywhere in this fragment path.**

### FM-B: arXiv unreachable / slow / error-entry during POST /discover

**Trigger:** arXiv is down, returns a 4xx/5xx, or returns an error entry (HTTP-200 with `/api/errors#` in the entry id). `_arxiv_api.fetch_candidates` raises `RuntimeError` (line 177 in `_arxiv_api.py`). The urllib `urlopen` raises `urllib.error.URLError` on DNS failure or connection refused.

**Symptom:** Unhandled exception propagates to FastAPI's default 500 handler, exposing a stack trace to the operator browser.

**Mitigation:** Catch `RuntimeError` and `urllib.error.URLError` (or their common base `OSError`) in the route handler. Return an htmx error fragment (e.g., `<div class="error">Discovery failed: arXiv unreachable</div>`) with HTTP 200 or 503. **Never let network exceptions reach the default 500 handler.**

### FM-C: notebook has no discovery_category set

**Trigger:** Operator clicks Discover on a notebook before setting a topic. `discover_for_notebook_async` raises `ValueError: notebook 'X' has no discovery_category set`.

**Symptom:** Unhandled ValueError propagates as 500, or if caught, an unclear error.

**Mitigation:** Catch `ValueError` explicitly. Return a helpful htmx error fragment: "Set a discovery topic first via the topic panel." HTTP 422 or an inline error fragment. This is distinct from FM-B — it is a pre-condition failure, not an external API failure.

### FM-D: slug path traversal / invalid slug on the new route

**Trigger:** Malformed slug in `/ui/api/notebooks/{slug}/discover` (e.g., `../../../etc/passwd`). If `validate_slug()` is not called first, `store.get_notebook()` may run against an unexpected key, or the store's SQL could be called with a tainted value.

**Mitigation:** Call `validate_slug(slug)` first, exactly as all other routes do. Raise HTTP 422 on `NotebookError`. This is the m6 F1/F3 path-traversal defense — already implemented in `tools._notebook_common.validate_slug`.

### FM-E: Event loop blocked during arXiv fetch (acceptable for loopback)

**Trigger:** `fetch_candidates` calls `urllib.request.urlopen(timeout=60)`, blocking the uvicorn thread for up to 60 seconds while the arXiv API responds.

**Symptom:** Other requests (e.g., the status-badge polling) are blocked for the duration. For a single-operator loopback console this is tolerable.

**Mitigation (v1):** Document the blocking in the route docstring. MAX_RESPONSE_BYTES=50MB cap already protects against response inflation. If a future milestone needs concurrency, wrap with `asyncio.to_thread(fetch_candidates, ...)`.

### FM-F: CSRF / origin pinning

**Trigger:** A malicious page on another localhost port attempts to POST to `/ui/api/notebooks/{slug}/discover`.

**Mitigation:** `SecFetchSiteMiddleware` rejects `cross-site` / `same-site` requests on `/ui/*` paths (only `none` and `same-origin` are allowed). `OriginValidationMiddleware` rejects non-loopback Origins. Both middlewares apply to the new route automatically. No new middleware configuration is required.

### FM-G: Ephemeral-queue confusion — candidates lost on navigate-away

**Trigger:** Operator discovers 20 candidates, navigates away, navigates back — candidates are gone.

**Mitigation:** The panel must display a clearly labeled notice: "Results are not saved. Refresh to re-run discovery." (`notebook-discovery-model.md §4` mandate). This is UX, not a security issue, but the brief requires it.

---

## Recommendation

Implement the route as `async def discover` in `server/routes/notebooks.py` following the existing handler shape: (1) `validate_slug` → 422, (2) `await store.get_notebook` → 404 if missing, (3) `await discover_for_notebook_async(store, slug, ...)` → catch `ValueError` for unconfigured notebook (422 fragment) and `(RuntimeError, OSError)` for arXiv failures (error fragment), (4) render candidates as an escaped f-string list (NOT Jinja2 partial) with per-row Add buttons. The Add button should POST to the existing `POST /ui/api/notebooks/{slug}/papers` with the paper_id wrapped as a fake arxiv URL (`https://arxiv.org/abs/{paper_id}`) — this reuses the validated, tested, htmx-aware handler with zero new code, avoids duplicating the `store.add_paper` call, and lets the operator trigger ingest separately via the existing Ingest button (which already writes to papers.txt). This is the correct v1 approach — "Add" records metadata, "Ingest" embeds.

Use `html.escape()` on every interpolated field in candidate-row f-strings. No `| safe`. No new MCP tool. No new pip dependency. No `asyncio.to_thread` in v1.

---

## Open questions

**OQ-1 (must resolve before code): "Add -> ingested into LanceDB" — does this mean immediate embedding, or metadata-only + operator-triggered ingest?**

The milestone brief AC says "Then the paper is ingested into the notebook's LanceDB and recorded in notebook_papers." The word "ingested" implies LanceDB embedding. However, `store.add_paper()` only records the junction row — it does NOT embed. The embedding pipeline runs via `IngestTaskTracker.start_ingest()` which spawns `notebook_ingest.py`, which reads `papers.txt`. The existing "Add paper" route (`POST /ui/api/notebooks/{slug}/papers`) only records the junction row (no embedding). LanceDB embedding always requires the separate "Run Ingest" button.

Resolution options:
- (a) "Add" records junction row only + writes paper_id to `papers.txt` + triggers ingest subprocess automatically (same as clicking Ingest). This matches the AC literally but adds ingest-trigger complexity.
- (b) "Add" records junction row only (calls existing `add_paper` route, no embedding). The operator clicks Ingest to embed. This matches the existing UI pattern.
- (c) Redirect the Add button to POST to the existing `/papers` endpoint and document that LanceDB embedding requires the Ingest button.

**My recommendation: option (c) — reuse the existing `POST /ui/api/notebooks/{slug}/papers` endpoint.** This avoids introducing a second code path for `store.add_paper`, reuses all the existing validation and htmx response logic, and is consistent with how URL-paste adding works. The brief's "ingested into LanceDB" may be loose language for "recorded in notebook_papers + eventually ingested via existing Ingest button." If the product owner requires immediate automatic ingest, that is a design escalation from the milestone brief as written.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no GitHub issue/PR, no infra mutation, no third-party API call (beyond the arXiv query that happens at runtime during operator use, which is pre-authorized by the m2/m3 design).
