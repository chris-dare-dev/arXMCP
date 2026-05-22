# Research Brief — proof-verify-handler-wiring-m10

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-22T17:00:00Z

## In-codebase context

### HTML source location — VERDICT: two separate paths, search-order required

The brief says preview renders `var/arxmcp/corpus/parsed/<paper_id>/index.html`. This
is PARTIALLY correct — that path is written by the ingest pipeline, but NOT by the
m8 upload endpoint. Two distinct write sites exist:

**Path A — ingest pipeline** (`ingest/ar5iv_fetch.py:53,284`):
```
DEFAULT_PARSED_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"
...
parsed_path = parsed_paper_dir / "index.html"
# → var/arxmcp/corpus/parsed/<paper_id>/index.html
```
`try_cache` writes: `parsed_paper_dir.mkdir(parents=True, exist_ok=True)` then
`parsed_path.write_text(body, encoding="utf-8")`. The `paper_id` is used as a
subdirectory name directly — meaning old-style IDs like `hep-th/0001234` produce
nested subdirs (`corpus/parsed/hep-th/0001234/index.html`).

**Path B — m8 upload endpoint** (`server/routes/notebooks.py:605,619-620`):
```python
ar5iv_dir = nb_dir / "ar5iv"
flat_paper_id = paper_id.replace("/", "_")
target_path = ar5iv_dir / f"{flat_paper_id}.html"
# → var/arxmcp/notebooks/<slug>/ar5iv/<flat_paper_id>.html
```
where `nb_dir = notebook_dir(slug)` = `var/arxmcp/notebooks/<slug>/`. This is
**notebook-scoped and flat** (no subdirectory per paper).

**CRITICAL CONFLICT WITH BRIEF:** The brief's `var/arxmcp/corpus/parsed/<paper_id>/index.html`
path only exists if the paper was fetched via `tools/notebook_fetch.py` (which calls
`ingest.ar5iv_fetch.try_cache`) OR via the bulk ingest pipeline. A paper added via the
m8 upload UI (`POST /ui/api/notebooks/{slug}/papers/upload`) writes to Path B only.

**Recommended search order:**
1. First: `var/arxmcp/notebooks/<slug>/ar5iv/<flat_paper_id>.html` (notebook-scoped, created by m8 upload)
2. Second: `var/arxmcp/corpus/parsed/<paper_id>/index.html` (corpus-global, created by ingest pipeline)
3. If neither: return "no preview available" (inline tooltip, not a 404)

The handler must construct `flat_paper_id = paper_id.replace("/", "_")` for Path A lookup.

### Route placement — MUST go under `server/routes/ui.py`, NOT under `notebooks.py`

`server/main.py` mounts two routers:
```python
app.include_router(notebooks_router, prefix="/ui/api")   # line 552
app.include_router(ui_router, prefix="/ui")              # line 559
```

The target route is `/ui/notebooks/{slug}/papers/{paper_id}/preview` — no `/api`
segment. This is an HTML page route, not a JSON/REST route. It belongs in
`server/routes/ui.py` alongside `ui_notebook_detail`, NOT in `server/routes/notebooks.py`.
No change to `server/main.py` mounting is required.

### CSP override — use response header override (Option A)

`SecurityHeadersMiddleware` (`server/middleware.py:685-741`) operates as:
```python
if is_ui_path and b"content-security-policy" not in existing:
    headers.append((b"content-security-policy", CONTENT_SECURITY_POLICY_UI))
```

The idempotency check (`b"content-security-policy" not in existing`) means if the
handler itself sets `Content-Security-Policy` on the response BEFORE the middleware
intercepts, the middleware will NOT overwrite it. This is the correct override path.

The m8 UI CSP is:
```
default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';
img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'
```

The m10 preview route needs the TIGHTER per-AC CSP:
```
default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'
```

**NOTE on CSP3 directives:** `frame-ancestors`, `form-action`, `base-uri` are NOT
fetch directives and do NOT fall back to `default-src`. The m10 CSP must explicitly
add `frame-ancestors 'self'` (the preview wrapper page is framing the content — it
must be allowed to frame itself) and should add `form-action 'none'; base-uri 'self'`.
The m8 CSP has `frame-ancestors 'none'` which would block the preview's own iframe if
the preview wrapper were served with that CSP.

The handler sets the header on the `Response` object directly:
```python
response = HTMLResponse(content=html, status_code=200)
response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY_PREVIEW
```

**Recommendation:** Define `CONTENT_SECURITY_POLICY_PREVIEW` as a module-level
constant in `server/middleware.py` alongside `CONTENT_SECURITY_POLICY_UI`, for the
same "byte-stable constant" discipline. The preview handler imports it.

### iframe shape — Option A (two routes)

Three options were considered:
- **Option A:** `/ui/notebooks/{slug}/papers/{paper_id}/preview` serves a wrapper
  HTML page containing `<iframe sandbox="allow-same-origin" src="/ui/notebooks/{slug}/papers/{paper_id}/preview/raw">`.
  A second route `/ui/notebooks/{slug}/papers/{paper_id}/preview/raw` serves the
  raw HTML directly.
- **Option B:** The notebook_detail page has a hidden `<iframe>` whose src the
  "Preview" link populates via JavaScript.
- **Option C:** The preview route serves the HTML directly; the browse table opens
  it in a new tab (no iframe in our markup).

**Recommendation: Option A.** Reasoning:
1. Option B requires JavaScript to manipulate the iframe src — the current UI design
   is htmx-driven and avoids script logic; adding imperative JS is an anti-pattern
   in this codebase.
2. Option C provides no iframe sandbox boundary — the raw HTML runs in the tab's
   full same-origin context. The `sandbox="allow-same-origin"` attribute is the
   load-bearing CSP bypass prevention mechanism; without it, inline scripts would run.
3. Option A gives two independently testable routes: the wrapper page (tests the
   `<iframe sandbox>` attribute and the tight wrapper CSP), and the raw route (tests
   that the raw HTML is served with `default-src 'none'` so scripts are blocked).
4. The raw HTML served at `/raw` must receive the tightest CSP (`default-src 'none';
   script-src 'none'; ...`) because the raw route is what the browser actually
   renders inside the iframe.

### m9 scope-invariant test — MUST be deleted before any frontend change

`tests/test_m9_scope_invariants.py::test_no_preview_or_iframe_in_frontend` greps
`frontend/` for `iframe|preview` and fails if found. The test body:
```python
result = subprocess.run(
    ["grep", "-rEi", "iframe|preview", str(FRONTEND_DIR)],
    capture_output=True, text=True, check=False,
)
if result.returncode == 0:
    raise AssertionError("AC #4 violation: m9 must not introduce preview/iframe...")
```

**This test MUST be deleted in the FIRST step of implementation** — before any
template or route change. Any attempt to run `make test` with m10's templates
present will fail on this guard. The test was a legitimate m9 scope guard; m10
supersedes it. Delete `tests/test_m9_scope_invariants.py` entirely.

### Browse-table "Preview" link insertion point

The per-paper `<tr>` in `frontend/templates/notebook_detail.html:114-131`:
```html
{% for p in papers %}
<tr data-slug="{{ notebook.slug }}" data-paper-id="{{ p.paper_id }}">
  <td><code>{{ p.paper_id }}</code></td>
  <td><time>{{ p.added_at }}</time></td>
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
```

The "Preview" link goes in the existing action `<td>`, alongside the Remove button.
The preview link should be a plain `<a href="...">` that opens the preview in a
new tab (`target="_blank"`). The "no preview available" tooltip case: check in the
template context whether a preview exists (pass `has_preview: bool` per paper from
the handler), conditionally rendering either the link or a `<span title="no preview
available" class="hint">Preview</span>`.

**NOTE:** The `ui_notebook_detail` handler in `server/routes/ui.py` currently calls
`store.list_papers(slug)` which returns `list[dict[str, str]]` with keys `paper_id`
and `added_at`. m10 must augment this with a `has_preview: bool` key per row, computed
by the route handler checking the filesystem for Path A or Path B.

### `is_valid_paper_id` + path-traversal defense

The existing `remove_paper` route uses `{paper_id:path}` (line 433) for old-style IDs
containing slashes. The m10 preview route must do the same. Pattern:

```python
@router.get("/notebooks/{slug}/papers/{paper_id:path}/preview")
async def ui_preview(slug: str, paper_id: str, request: Request) -> Response:
    validate_slug(slug)           # raises NotebookError → 422
    if not is_valid_paper_id(paper_id):  # \Z anchor hardening
        raise HTTPException(422, detail=...)
    # THEN filesystem lookup
```

The `\Z` anchor in `is_valid_paper_id` (m1-rect-F3 hardening) prevents trailing-newline
injection, path-traversal via `../../` (which fails the regex), and any non-arXiv-ID
character. The validator fires BEFORE the `flat_paper_id = paper_id.replace("/", "_")`
substitution and any `Path(...)` construction.

## Prior decisions and lessons

**Pattern of adversary findings on this Track-D chain:**
- m7: F1 (HIGH) — CSRF broken because `SecFetchSiteMiddleware` was not carved out for `/ui`
- m8: F1 (CRITICAL) — form-encoding bug (htmx default is `application/x-www-form-urlencoded`,
  multipart requires explicit `hx-encoding="multipart/form-data"`)
- m9: F1 (HIGH) — `CancelledError` leaks past `except Exception` (BaseException subclass)

**Pattern for m10:** The adversary will look for:
1. CSP bypass — iframe `sandbox` attribute incorrectly set (e.g. `sandbox="allow-scripts
   allow-same-origin"` would re-enable scripts), or CSP `frame-ancestors` not set correctly.
2. Path-traversal in the filesystem lookup — verifying `is_valid_paper_id` fires before
   any `Path` construction.
3. XSS via the paper title or paper_id interpolated into the wrapper HTML without escaping.
4. Missing `has_preview` check — preview link rendered even when HTML doesn't exist (link
   404s rather than showing tooltip).

**Idempotency pattern from m8 (line 619):** `flat_paper_id = paper_id.replace("/", "_")`
is the canonical form for old-style paper IDs on disk. The preview route must use the same
transformation for Path B lookup.

**Tool-schema SHA:** No new MCP tools in m10. `EXPECTED_TOOL_SCHEMA_SHA256` in
`tests/test_server_tool_schema.py` does NOT need re-pinning.

**KMP guard:** `tests/conftest.py::KMP_DUPLICATE_LIB_OK=TRUE` is unrelated to m10
(no faiss/PyTorch in the preview route). Do not touch it.

## External sources

Not directly relevant for the route/CSP implementation. The MCP spec surface is
unchanged (no new MCP tools). The Anthropic prompt-caching docs are irrelevant (no
tool schema changes, no cache breakpoints affected).

CSP3 spec reference: `frame-ancestors`, `form-action`, `base-uri` are directives of
the "Non-Fetch directives" category and are explicitly excluded from `default-src`
fallback behavior. This is a known footgun — see the prior memory entry from m10
initial research: "csp-frame-ancestors-form-action-base-uri-not-default-src-fallback".

## Recommendation

**Implement Option A (two routes) with notebook-first search order.**

1. Delete `tests/test_m9_scope_invariants.py` as step zero.
2. Add `CONTENT_SECURITY_POLICY_PREVIEW` constant to `server/middleware.py`.
3. Add two routes to `server/routes/ui.py`:
   - `GET /notebooks/{slug}/papers/{paper_id:path}/preview` — wrapper page with
     `<iframe sandbox="allow-same-origin" src=".../preview/raw">`, served with a
     permissive-enough CSP that allows `frame-src 'self'`.
   - `GET /notebooks/{slug}/papers/{paper_id:path}/preview/raw` — raw HTML served
     directly from disk with the tight CSP (`default-src 'none'; img-src 'self' data:;
     style-src 'self' 'unsafe-inline'; script-src 'none'; frame-ancestors 'self';
     form-action 'none'; base-uri 'self'`).
4. Augment `ui_notebook_detail` to pass `has_preview: bool` per paper (filesystem check).
5. Add "Preview" link to `notebook_detail.html` with `has_preview` guard.

Route handler sketch:
```python
@router.get(
    "/notebooks/{slug}/papers/{paper_id:path}/preview",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def ui_paper_preview(
    slug: str,
    paper_id: str,
    request: Request,
) -> Response:
    validate_slug(slug)
    if not is_valid_paper_id(paper_id):
        raise HTTPException(status_code=422, detail=f"invalid paper_id {paper_id!r}")
    # search-order: notebook-scoped first, corpus-global second
    flat = paper_id.replace("/", "_")
    nb_html = notebook_dir(slug) / "ar5iv" / f"{flat}.html"
    corpus_html = (
        Path(REPO_ROOT) / "var" / "arxmcp" / "corpus" / "parsed"
        / paper_id / "index.html"
    )
    if nb_html.is_file():
        html_path = nb_html
    elif corpus_html.is_file():
        html_path = corpus_html
    else:
        raise HTTPException(status_code=404, detail="no preview available")
    raw_url = request.url_for("ui_paper_preview_raw", slug=slug, paper_id=paper_id)
    response = templates.TemplateResponse(
        request=request,
        name="preview_wrapper.html",
        context={"raw_url": raw_url},
    )
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY_PREVIEW_WRAPPER
    return response
```

## Open questions

1. **Should `/preview/raw` return a 404 or redirect back to `/preview` when the HTML
   is gone between the wrapper-page request and the iframe load?** The window is tiny
   on loopback, but a 404 with a user-visible error message inside the iframe is
   acceptable. Recommendation: 404 with a plain-text body (no HTML, since the tight
   CSP on the raw route would block any styling anyway).

2. **Does the wrapper CSP need `frame-src 'self'`?** Yes — the wrapper page renders
   an `<iframe src="/ui/notebooks/.../preview/raw">` which is a same-origin fetch.
   Without `frame-src 'self'` (or `child-src 'self'`), a browser honoring CSP3 will
   block the iframe load. The wrapper CSP must allow it.

These are answerable by the implementer without additional research — they are
implementation-time decisions, not ambiguous architectural choices.

**No open questions that block implementation from proceeding.**

## External writes the implementation will require

None — this milestone is purely local. Route + template + tests; no git push, no
ticket creation, no infra mutation, no third-party API call.

The only files touched will be under `server/`, `frontend/`, and `tests/`, all within
`$REPO_ROOT`. The single pre-push authorization needed is per CLAUDE.md §4.4 (user
"yes, push" for the final commit).
