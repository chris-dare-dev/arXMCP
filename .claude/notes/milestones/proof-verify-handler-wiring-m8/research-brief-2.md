# Research Brief — proof-verify-handler-wiring-m8

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T15:00:00Z

---

## In-codebase context

### Middleware stack — what already exists

`server/main.py` lines 392–465 wire the full middleware stack (LIFO order):
```
SecurityHeaders -> SecFetchSiteMiddleware -> OriginValidation
  -> HostValidation -> RequestBodySizeLimitMiddleware
  -> SessionCap -> BodySizeCap -> handler
```

`RequestBodySizeLimitMiddleware` (defined in `server/middleware.py:699`) caps at `REQUEST_BODY_MAX_BYTES = 1 * 1024 * 1024` (line 129). Its constructor signature is:
```python
def __init__(self, app, max_bytes: int = REQUEST_BODY_MAX_BYTES) -> None:
```
The 10 MB upload carve-out CANNOT be a simple parameter change to the single existing middleware instance — it wraps the whole app. The correct pattern is to add a **second** `RequestBodySizeLimitMiddleware` instance with `max_bytes=10*1024*1024` mounted at a path-scoped ASGI wrapper, or more cleanly: subclass/configure the existing middleware with a `per_prefix_caps: dict[str, int]` extension that returns the per-path limit before falling back to the default 1 MB.

**CRITICAL:** The m7 `SecFetchSiteMiddleware` carve-out is ALREADY in place (`server/main.py:463`):
```python
app.add_middleware(SecFetchSiteMiddleware, exempt_prefixes=("/ui",))
```
The permitted values on `/ui/*` are `{none, same-origin}` (middleware.py:468–470). The upload endpoint `/ui/api/notebooks/*/papers/upload` automatically inherits this — no additional wiring needed.

### URL normalizer gap (CRITICAL)

`server/routes/notebooks.py:81` defines:
```python
_ACCEPTED_HOSTS: frozenset[str] = frozenset({"arxiv.org"})
```
Line 100 explicitly documents: `"ar5iv.labs.arxiv.org/html/... (out of m7 scope)"`. The m7 synthesis Disagreement-3 deferred ar5iv URL support to m8. **m8 MUST extend `_ACCEPTED_HOSTS` or add a separate normalizer for ar5iv URLs.** The existing `_arxiv_url_to_paper_id` function rejects ar5iv URLs with `None`; the upstream POST handler returns 422. This is a gap the implementer must close.

### Threat-2 delimiter wrapping

`server/tools.py:329–391` implements `wrap_retrieved_text()` with `_WRAP_TAG_CHUNK = "retrieved_chunk"`. Stored ar5iv HTML files ingested later will pass through the chunker and subsequently through `wrap_retrieved_text` when served as MCP tool output. The HTML file stored at upload time is raw binary — the Threat-2 delimiter protection fires at retrieval time (MCP tool call), NOT at upload time. Upload storage of raw HTML is correct behavior.

### No Jinja2 or StaticFiles currently in `server/`

Grep across `server/` finds zero references to `Jinja2Templates` or `StaticFiles`. Both are transitive deps today: `jinja2==3.1.6` is pulled via `mcp>=1.27.1` → dep chain; `python-multipart==0.0.27` is pulled directly by `mcp`. Neither is declared in `pyproject.toml` explicitly. **m8 must add both as explicit project dependencies** per the project's "no implicit deps" discipline (pyproject.toml comment on pyyaml: "Already a transitive dep via transformers / lancedb; declared explicitly to match the project's 'no implicit deps' discipline").

---

## Prior decisions and lessons

- **`BaseHTTPMiddleware` is project-banned** (CLAUDE.md §4.7, agent-conventions.md §4). The per-prefix body-cap carve-out MUST be pure-ASGI. The existing `RequestBodySizeLimitMiddleware` is already pure-ASGI — extend it, don't bypass it.
- **No MCP tools added in m8** (REST + HTML surface only). `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning; the milestone brief confirms this explicitly ("TOOL_SCHEMA_SHA256 unchanged; no new MCP tools").
- **`docs_url=None`** is set in `server/main.py:384` — no FastAPI OpenAPI UI. The htmx UI is served from `frontend/` subdirectory (template + static), not from FastAPI's built-in docs.
- **`KMP_DUPLICATE_LIB_OK=TRUE`** in `tests/conftest.py` is load-bearing; m8 adds no ML model loads, so no risk of removal.
- **Doc placement:** any new Markdown for this milestone goes under `.claude/docs/` or `.claude/notes/milestones/proof-verify-handler-wiring-m8/`. Specifically, a UI/security audit note belongs at `.claude/docs/security-ui-upload-audit.md`, NOT at `docs/`.

---

## External sources

### htmx version and licensing

**Stable version: 2.0.10** (confirmed from CDN reference `https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js`).

**File size:** `htmx.min.js` is ~51 KB as gzip-compressed (measured: `51238` bytes), and ~87 KB unminified. The brief states "14 KB" — this is the htmx 1.x era size. **htmx 2.x `htmx.min.js` is ~51 KB gzipped, ~87 KB raw.** The implementer should vendor the raw `.min.js` (87 KB on disk); it will be served gzip-compressed by uvicorn's built-in StaticFiles. The "14 KB" figure in the brief is stale — the vendored file will be ~87 KB on disk.

**License: Zero-Clause BSD (0BSD).** Confirmed from the htmx v2.0.10 GitHub tag. 0BSD is more permissive than BSD-2-Clause — no attribution clause, no license-preservation requirement. Compatible with arXMCP's MIT license and the project's no-AGPL rule.

**htmx attributes for m8:**
- `hx-post="/ui/api/notebooks"` — create notebook
- `hx-target="#notebook-list"` — DOM target for swap
- `hx-swap="outerHTML"` — replace the list on create/delete
- `hx-encoding="multipart/form-data"` — REQUIRED for the file-upload drag-drop card (without this, the file input sends as `application/x-www-form-urlencoded`, which loses binary content)
- `hx-trigger="drop"` — for drag-drop (or use a standard `<input type="file">` with `hx-on:change`)

**CSP for m8:** htmx loaded from `<script src="/static/htmx.min.js"></script>` (no inline script) requires only `script-src 'self'`. htmx uses HTML attributes (`hx-*`) for behavior, not inline `<script>` blocks. Minimal CSP for m8: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'`. The `unsafe-inline` for styles is for the minimal inline CSS only; m10 tightens this further with nonces. **No `unsafe-inline` for scripts is needed for htmx 2.x when loaded from a vendored file.**

### jinja2 and python-multipart

- `jinja2==3.1.6` — installed (transitive via mcp dep chain). CVE-2024-22195 (`xmlattr` XSS) fixed in 3.1.3; our version is safe.
- `python-multipart==0.0.27` — installed (direct dep of mcp). CVE-2024-53981 (DoS via crafted multipart) fixed in 0.0.18; our version is safe.
- **Both must be added to `pyproject.toml` explicitly** with minimum bounds `jinja2>=3.1.3` and `python-multipart>=0.0.18`.

### Starlette StaticFiles path-traversal protection

`starlette/staticfiles.py:163` (verified in `.venv`):
```python
if os.path.commonpath([full_path, directory]) != str(directory):
    # Don't allow misbehaving clients to break out of the static files directory.
    continue
```
`os.path.realpath` resolves `..` components before the `commonpath` check. Path traversal via `GET /static/../../etc/passwd` is blocked by Starlette itself. The implementer does NOT need to add a separate traversal guard for `StaticFiles`. This protection is built in.

### Jinja2 autoescape

Starlette's `Jinja2Templates(directory=...)` constructor (`.venv/starlette/templating.py:95`) calls:
```python
self.env = jinja2.Environment(loader=loader, autoescape=jinja2.select_autoescape())
```
`jinja2.select_autoescape()` defaults to enabling autoescape for `.html`, `.htm`, `.xml` extensions. Since all templates will use `.html` extensions, **autoescape is ON by default** when using `Jinja2Templates(directory=...)`. However, the implementer MUST add an explicit `autoescape=True` (or `autoescape=select_autoescape(["html", "xml"])`) call in the constructor call to make the protection visible and not rely on the default — per the milestone brief's "explicit > implicit" discipline.

---

## Failure-mode analysis

**FM-1 (Threat 4 — oversized upload UX):** Operator drops a 100 MB HTML file. The 10 MB per-prefix cap fires first (HTTP 413). The existing 413 response shape from `RequestBodySizeLimitMiddleware` is JSON: `{"error": "payload_too_large", "message": "...", "max_bytes": N}`. htmx on HTTP 413 does NOT auto-swap — the user sees no visible error unless the template uses `hx-on::htmx:responseError` or a `<div id="upload-error">` target. **Recommendation:** add `hx-on::htmx:responseError="document.getElementById('upload-error').innerText = event.detail.xhr.responseText"` to the upload card and include a visible `<div id="upload-error">` placeholder.

**FM-2 (Threat 4 — non-HTML file upload):** Operator drops a `.exe` or `.pdf`. Content-Type is forgeable. Recommend a **dual gate:** (a) require `Content-Type: text/html` in the multipart part AND (b) read the first 16 bytes after upload and reject if they don't start with `<!` or `<h` (magic-byte sniff). Extension check alone (`Path(file.filename).name.endswith(".html")`) is insufficient. A `.exe` renamed to `.html` passes the extension check.

**FM-3 (Threat 2 — malicious embedded script in stored HTML):** Operator drops a crafted HTML with `<script>alert(1)</script>`. The file is stored as-is in `var/arxmcp/notebooks/{slug}/ar5iv/`. When later ingested, the chunker processes it; when returned via MCP tool output, `wrap_retrieved_text()` escapes any `<retrieved_chunk>` boundary tokens. The primary Threat-2 defense is the delimiter contract at retrieval time — it does NOT sanitize `<script>` tags. **This is acceptable for m8** because the stored HTML is not served directly via the MCP surface in this milestone (that's m10). Flag for m10: the iframe preview MUST have `sandbox="allow-same-origin"` and CSP `script-src 'none'`.

**FM-4 (Threat 1 — path traversal via multipart filename):** A crafted multipart upload sends `filename="../../../etc/passwd"`. The handler MUST NOT use `file.filename` to derive the on-disk path. **Recommendation (opinionated):** derive the output filename exclusively from the `paper_id` field submitted in the same multipart form (a separate `<input name="paper_id">` or from the slug route parameter), validated via `ingest.identifiers.is_valid_paper_id`. The on-disk path is then deterministic: `var/arxmcp/notebooks/{slug}/ar5iv/{paper_id}.html`. Never use `file.filename` for anything other than logging.

**FM-5 (concurrent upload of same paper_id):** Two uploads of the same `paper_id` race. The junction-row PRIMARY KEY (slug, paper_id) catches the second at DB layer (SQLite UNIQUE constraint → 409). The on-disk file gets silently overwritten by whichever upload completes last. **Recommendation:** atomic write — write to `{paper_id}.html.tmp`, then `os.replace()` (POSIX-atomic rename). This prevents a reader from seeing a partial file. 409 on the junction row is the correct HTTP response for the duplicate; the file overwrite is idempotent and acceptable.

**FM-6 (CRITICAL — ar5iv URL paste rejected by m7 normalizer):** The m7 URL normalizer at `server/routes/notebooks.py:81` explicitly rejects `ar5iv.labs.arxiv.org` (line 100: `"ar5iv.labs.arxiv.org/html/... (out of m7 scope)"`). The AC #3 for m8 states: "URL paste accepts both `arxiv.org/abs/<id>` and `ar5iv.labs.arxiv.org/html/<id>` forms." This is a **confirmed gap** — m8 must add `ar5iv.labs.arxiv.org` to `_ACCEPTED_HOSTS` and add an `"/html/"` path-prefix handler in `_arxiv_url_to_paper_id`. **The implementer must modify `server/routes/notebooks.py` to extend the normalizer.**

**FM-7 (CSRF via SecFetchSite):** The `/ui/api/notebooks/*/papers/upload` endpoint is under `/ui/*`. `SecFetchSiteMiddleware` already admits `{none, same-origin}` for the `/ui` prefix (middleware.py:468–470). A same-origin htmx POST from the page at `http://127.0.0.1:7733/ui/` to `/ui/api/notebooks/{slug}/papers/upload` carries `Sec-Fetch-Site: same-origin` — this is permitted. Cross-origin POSTs from another local port carry `Sec-Fetch-Site: cross-site` — this is rejected. **The CSRF protection is already in place for m8 via the m7 middleware wiring. No additional CSRF token is required.**

**FM-8 (htmx + JSON API mismatch):** m7 routes return JSON. htmx by default swaps the raw response body into `hx-target`. Receiving `{"slug": "my-nb", "paper_id": "2301.00001"}` and inserting it into a table cell produces raw JSON in the DOM, not an HTML row. Two options: (a) return HTML fragments from new m8-specific handlers; (b) keep JSON and use `hx-on::htmx:afterRequest` with a JavaScript callback to hydrate. **Recommendation (opinionated):** For the URL-paste and upload endpoints, add **m8-specific HTML-fragment endpoints** at `/ui/api/notebooks/{slug}/papers/upload` (the new endpoint) and mount the m7 JSON routes unchanged. The upload endpoint returns an `<tr>...</tr>` fragment; htmx swaps it into the `<tbody>` via `hx-target="#papers-tbody" hx-swap="beforeend"`. The m7 JSON routes remain JSON-only for programmatic use. This avoids any JavaScript and keeps the htmx conventions clean. The URL-paste form at `/ui/api/notebooks/{slug}/papers` (m7 JSON) may need a thin m8 wrapper endpoint at `/ui/notebooks/{slug}/papers` (HTML fragment) to avoid touching m7 JSON contracts.

---

## Recommendation

**Implement m8 as follows:**

1. **htmx version: 2.0.10, license: 0BSD.** Download once and vendor to `frontend/static/htmx.min.js` (~87 KB on disk). Document the version and license in a one-line comment in the HTML template. No CDN fetch at runtime.

2. **Per-prefix upload cap:** extend `RequestBodySizeLimitMiddleware` to accept `per_prefix_caps: dict[str, int] = {}`. The carve-out for `/ui/api/notebooks/` uses `10 * 1024 * 1024`. This is pure-ASGI, avoids `BaseHTTPMiddleware`, and keeps the single middleware instance. Alternative: mount a second ASGI wrapper only around the upload route — also acceptable.

3. **Filename sanitization:** derive disk filename from `paper_id` (form field, validated via `is_valid_paper_id`), never from `file.filename`. Write atomically via `os.replace()`.

4. **Magic-byte sniff + Content-Type gate:** reject uploads that don't start with `<!` or `<h` (first 16 bytes), in addition to the `.html` extension check.

5. **ar5iv URL normalizer extension:** add `ar5iv.labs.arxiv.org` to `_ACCEPTED_HOSTS` with path prefix `/html/` in `server/routes/notebooks.py`. This is a required change for AC #3.

6. **htmx + JSON strategy:** upload endpoint returns HTML fragment (`<tr>`); URL-paste route has a thin m8 HTML-fragment wrapper. m7 JSON routes untouched.

7. **Jinja2 autoescape:** use `Jinja2Templates(directory="frontend/templates", autoescape=True)` explicitly. Do not rely on the `select_autoescape()` default.

8. **`pyproject.toml`:** add `"jinja2>=3.1.3"` and `"python-multipart>=0.0.18"` as explicit project dependencies.

---

## Open questions

1. **Exact per-prefix cap implementation shape:** should `RequestBodySizeLimitMiddleware` grow a `per_prefix_caps` parameter (modifies existing middleware, requires test update), or should a second thin ASGI wrapper be placed only around the upload route? Either approach is valid; the implementer must pick one before writing code.

2. **ar5iv URL normalizer scope:** should `_arxiv_url_to_paper_id` be extended in `server/routes/notebooks.py` (minimal change, keeps m7 file small), or should a new `_normalizer.py` helper be extracted (better testability)? Recommend in-place extension for m8 given the "M complexity" estimate.

3. **Frontend directory location:** the brief specifies `frontend/templates/` and `frontend/static/` at repo root. This is outside `server/`, `ingest/`, etc. Confirm it doesn't conflict with the `pyproject.toml` `packages = ["server", "ingest", "tools", "shim"]` declaration (it shouldn't — `frontend/` would be a non-package directory served as static files, not imported).

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| One-time file download | `https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js` → `frontend/static/htmx.min.js` | Vendor the htmx JS file so no internet fetch at runtime (AC #5). This is a one-time download at implementation time; the file is committed to the repo. |

All other work is local. No git push, no GitHub issue, no infra mutation required for m8 itself.
