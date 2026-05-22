# Research Synthesis — proof-verify-handler-wiring-m8

**Orchestrator merge of:** `research-brief-1.md`, `research-brief-2.md`
**Generated:** 2026-05-22T16:15:00Z
**Mode:** standard (2× Sonnet in parallel)

## TL;DR for the implementer

Build the htmx UI on top of m7's REST surface. Vendor htmx 2.0.10
(0BSD-licensed, ~87 KB raw — the brief's "14 KB" figure is stale,
matched the 1.9.x line; 2.0.x is the current stable and is what m8
ships). Render templates via FastAPI's `Jinja2Templates`
(autoescape explicit). Serve static assets at `/ui/static`
(under the m7 `/ui/*` carve-out — inherits SecFetchSite
protection). Add `python-multipart` + `jinja2` as EXPLICIT
project dependencies (both are transitive today via `mcp`, but
the project's "no implicit deps" discipline requires explicit
declaration). Extend `_arxiv_url_to_paper_id` (m7) to ALSO
accept `ar5iv.labs.arxiv.org/html/<id>`. Extend
`RequestBodySizeLimitMiddleware` with a `prefix_caps` dict so the
upload endpoint gets a 10 MB cap while the rest of the surface
stays at 1 MB. Sanitize the upload filename via `paper_id`
(NEVER `file.filename`); write atomically via `os.replace()`;
magic-byte sniff for HTML (first 16 bytes start with `<!` or
`<h`).

Estimated implementation surface: ~700 LOC across ~10 files
(templates, static, router, middleware extension, upload handler,
URL-normalizer extension, tests). Above the inline threshold by
file count; but the work is naturally serial and every pattern is
established (`Jinja2Templates`, `StaticFiles`, the m7
`exempt_prefixes` precedent for the prefix-caps shape). **Inline
path** chosen.

## Resolved disagreements

### Disagreement 1 — htmx version (1.9.x LTS vs 2.0.x current)

**R-1:** htmx 1.9.12 (~14 KB minified, matches the brief's stated
size; "do NOT use 2.x — dropped hx-swap-oob defaults, changed
hx-trigger semantics").

**R-2:** htmx 2.0.10 (~87 KB raw / ~51 KB gzipped, 0BSD-licensed,
current stable).

**Synthesis: R-2 wins.** Pick the current stable. R-1's concern
about 2.x semantic changes is real but applies only to advanced
features (`hx-swap-oob`, complex `hx-trigger` rules) that m8 does
NOT use. The htmx attributes m8 needs (`hx-post`, `hx-target`,
`hx-swap`, `hx-encoding="multipart/form-data"`,
`hx-on::htmx:responseError`) are stable across both lines. The
brief's "14 KB" estimate is stale — note that as a deviation in
the implementation summary. Pin **htmx 2.0.10**, download from
`https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js`
to `frontend/static/htmx.min.js`, vendor with a header comment
naming the version + source URL + 0BSD license.

### Disagreement 2 — htmx swap target shape (HTML fragments vs JSON + reload)

**R-1:** "the detail view expands inline via htmx (`hx-get` on the
'open' link fetching `/ui/api/notebooks/{slug}/papers` as an HTML
fragment)" — but this conflicts with itself, because the m7 route
returns JSON, not HTML.

**R-2:** Two options enumerated: (a) add m8-specific HTML-fragment
endpoints; (b) keep JSON + JavaScript callbacks. R-2 picks (a)
and recommends a new HTML-fragment upload endpoint that returns
`<tr>...</tr>` for `hx-swap="beforeend"`.

**Synthesis: hybrid wins.** The simplest m8 shape is:
- Mutation forms (create-notebook, paper-paste-URL) use htmx to
  POST to the m7 JSON routes, then trigger a **full-page reload**
  on success via `hx-on::htmx:afterRequest="if(event.detail.successful) location.reload()"`.
  No HTML-fragment wrappers needed for these — m7 routes stay
  JSON-only.
- The upload endpoint is NEW in m8 — design it to return an
  HTML fragment (`<tr>` row) from the start, swapped into the
  papers table via `hx-target="#papers-tbody" hx-swap="beforeend"`.
- Per-notebook detail view: implement as a server-rendered
  `GET /ui/notebooks/{slug}` (Jinja2 template) — opening the
  "open" link is a full navigation, not htmx-inline. Cheaper to
  implement, easier to debug, no DOM state to manage.

This avoids any per-endpoint JSON-to-HTML wrapping while keeping
the upload endpoint htmx-native.

### Disagreement 3 — `prefix_caps` shape (single middleware extension vs second wrapper)

**R-1:** Add `prefix_caps: dict[str, int]` param to the existing
`RequestBodySizeLimitMiddleware` (single instance, single edit).

**R-2:** "Either approach is valid" — extends OR wraps with a
second ASGI middleware.

**Synthesis: R-1 wins.** Single middleware instance with a
`prefix_caps` dict mirrors the m7 `SecFetchSiteMiddleware`
`exempt_prefixes` precedent exactly. Backward-compatible (default
`{}`). Less surface area for the adversary critic to attack.
Concrete shape:
```python
def __init__(
    self,
    app,
    max_bytes: int = REQUEST_BODY_MAX_BYTES,
    prefix_caps: dict[str, int] | None = None,
) -> None:
    self.app = app
    self.max_bytes = max_bytes
    self._prefix_caps: dict[str, int] = prefix_caps or {}
```
Wire with `prefix_caps={"/ui/api/notebooks": 10 * 1024 * 1024}`.
The match is `path == p or path.startswith(p + "/")` (mirrors the
m7 carve-out pattern — FM-3 closure parity).

### Disagreement 4 — `frontend/` vs `server/routes/ui.py` for the HTML page

**R-1:** New UI router at `server/routes/ui.py`; templates under
`frontend/templates/`; upload handler joins the existing
`server/routes/notebooks.py` router.

**R-2:** Doesn't explicitly disagree, but recommends an HTML
wrapper at `/ui/notebooks/{slug}/papers` separate from the m7
JSON routes.

**Synthesis: R-1's split is correct.** The split is:
- `server/routes/ui.py` — `GET /ui/` and `GET /ui/notebooks/{slug}`
  HTML pages (the Jinja2-rendered templates).
- `server/routes/notebooks.py` — m7 JSON routes + the NEW upload
  endpoint (joins the existing router since they share the
  `/ui/api/notebooks` prefix and the `NotebooksStore` dependency).
- `frontend/templates/` — Jinja2 templates.
- `frontend/static/` — vendored htmx.min.js + minimal CSS.

### Disagreement 5 — Static mount path (`/ui/static` vs `/static`)

**R-1:** Mount at `/ui/static` to keep the entire `/ui/*` subtree
consistent (so the SecFetchSite carve-out covers it).

**R-2:** No explicit recommendation; implies `/static` via the CSP
example.

**Synthesis: R-1 wins.** `/ui/static` keeps the prefix
discipline consistent — every UI-related path is under `/ui/*`,
and the SecFetchSite carve-out automatically covers it. A standalone
`/static` path would need its own carve-out and would muddy the
threat-model boundary.

## Load-bearing facts the implementer needs

### Dep additions (pyproject.toml)

Both researchers confirmed both are transitive today via `mcp`
but NOT declared as explicit project deps:
```
"jinja2>=3.1.6",           # explicit (transitive via mcp)
"python-multipart>=0.0.18", # explicit (transitive via mcp); 0.0.18+ closes CVE-2024-53981
```
Match the project's "no implicit deps" discipline (pyproject's
`pyyaml` comment is the precedent).

### Existing m7 middleware/route surface

From `server/main.py`:
```python
app.add_middleware(SecFetchSiteMiddleware, exempt_prefixes=("/ui",))
# ...
app.include_router(notebooks_router, prefix="/ui/api")
```

The m7 carve-out already covers `/ui/static/*` and `/ui/notebooks/*`
(any path under `/ui/`). No new middleware wiring needed beyond the
`prefix_caps` extension to `RequestBodySizeLimitMiddleware`.

### Existing `_arxiv_url_to_paper_id` (m7)

```python
_ACCEPTED_HOSTS: frozenset[str] = frozenset({"arxiv.org"})

# in _arxiv_url_to_paper_id:
prefix = "/abs/"
if not path.startswith(prefix):
    return None
candidate = path[len(prefix):]
```

m8 extends to:
```python
_ACCEPTED_HOSTS: frozenset[str] = frozenset({
    "arxiv.org", "ar5iv.labs.arxiv.org",
})

_HOST_PATH_PREFIX: dict[str, str] = {
    "arxiv.org": "/abs/",
    "ar5iv.labs.arxiv.org": "/html/",
}

# in _arxiv_url_to_paper_id:
prefix = _HOST_PATH_PREFIX.get(parsed.hostname, "")
if not prefix or not path.startswith(prefix):
    return None
candidate = path[len(prefix):]
```

### Upload-endpoint contract (synthesis decision)

Route: `POST /ui/api/notebooks/{slug}/papers/upload`

Form fields:
- `file` (UploadFile, required) — the ar5iv HTML file
- `paper_id` (str, required) — the arXiv paper id (validated via
  `is_valid_paper_id`); the on-disk filename is derived from this,
  NEVER from `file.filename` (FM-4)

Server behavior:
1. Validate `slug` via `validate_slug`.
2. Validate `paper_id` via `is_valid_paper_id`.
3. Check the notebook exists (`store.get_notebook(slug)` → 404 if absent).
4. Read the file (≤ 10 MB per the prefix_caps cap).
5. Magic-byte sniff: first 16 bytes must start with `<!` or `<h`
   (case-insensitive) — else 422 with "uploaded file does not
   appear to be HTML" (FM-2).
6. Atomic write: `Path(ar5iv_dir / f"{paper_id}.html.tmp").write_bytes(content)` →
   `os.replace(...)` to `.html` (FM-5).
7. `await store.add_paper(slug, paper_id, _now_iso())` — 409 on
   duplicate junction row.
8. Return HTML fragment `<tr>...</tr>` for htmx
   `hx-swap="beforeend"`.

### Jinja2 autoescape — explicit

```python
templates = Jinja2Templates(
    directory="frontend/templates",
    autoescape=True,  # explicit; Starlette default is select_autoescape(["html","xml"])
)
```

R-2 verified that Starlette's `Jinja2Templates(directory=...)`
defaults to `select_autoescape()` which enables autoescape for
`.html`/`.htm`/`.xml`. Passing `autoescape=True` explicitly is
defensive but the default already protects.

### `_BYTE_CAP_EXEMPT_PREFIXES` extension

R-1 surfaced that `BodySizeCapMiddleware` caps RESPONSE bodies at
256 KB. A Jinja2-rendered `GET /ui/` page listing many notebooks
COULD approach this; add `/ui/` to `_BYTE_CAP_EXEMPT_PREFIXES`
preemptively so the response cap doesn't truncate the HTML page.

Current value:
```python
_BYTE_CAP_EXEMPT_PREFIXES = ("/healthz", "/readyz", "/metrics", "/mcp")
```
Extend to:
```python
_BYTE_CAP_EXEMPT_PREFIXES = ("/healthz", "/readyz", "/metrics", "/mcp", "/ui")
```

(The `/ui/api/*` JSON routes are well under 256 KB but folding
the whole `/ui` subtree into the exempt set is the cleanest
choice — same prefix-match convention.)

## Failure modes the implementer must inoculate against

Consolidated from R-2's catalog with R-1's input:

1. **FM-1** — Oversized upload UX. 10 MB cap fires; the existing
   413 response is JSON. Add an `hx-on::htmx:responseError`
   handler in the upload-card template to display the error in a
   visible `<div id="upload-error">`.
2. **FM-2** — Non-HTML file upload. Magic-byte sniff (first 16
   bytes) + `.html` extension gate. Extension alone is forgeable.
3. **FM-3** — Malicious embedded `<script>` in stored HTML. m8
   stores raw bytes; the chunker + delimiter contract handle
   Threat 2 at retrieval time. m10's iframe sandbox handles the
   preview path. m8 is correct as-is.
4. **FM-4** — Filename path-traversal in multipart upload. Derive
   on-disk filename from `paper_id` form field exclusively
   (validated via `is_valid_paper_id`). Never use `file.filename`
   for anything other than logging.
5. **FM-5** — Concurrent upload of same paper_id. Atomic write via
   `os.replace()` so readers never see a partial file. Junction
   PRIMARY KEY catches the race at DB layer (409).
6. **FM-6** — ar5iv URL paste rejected by m7 normalizer. Mandatory
   m8 fix — extend `_ACCEPTED_HOSTS` + `_HOST_PATH_PREFIX`.
7. **FM-7** — CSRF on the upload endpoint. Already protected by
   the m7 `SecFetchSiteMiddleware` carve-out (`{none, same-origin}`
   on `/ui/*`). No additional CSRF token needed.
8. **FM-8** — htmx vs JSON mismatch. Resolved per synthesis D2:
   mutations on m7 JSON routes use full-page reload; the new m8
   upload endpoint returns an HTML fragment.

## Acceptance-criteria mapping

- [ ] **AC #1** — `GET /ui/` returns HTML page listing notebooks
  with create-notebook form + per-notebook "open" link. New
  `server/routes/ui.py` with `GET /ui/` → Jinja2 template.
- [ ] **AC #2** — Drop `.html` file onto a notebook card POSTs to
  `/ui/api/notebooks/{slug}/papers/upload`; file stored at
  `var/arxmcp/notebooks/{slug}/ar5iv/{paper_id}.html`; junction
  row created. New upload handler in `server/routes/notebooks.py`.
- [ ] **AC #3** — URL paste accepts both `arxiv.org/abs/<id>` AND
  `ar5iv.labs.arxiv.org/html/<id>`. Extend
  `_arxiv_url_to_paper_id` per synthesis.
- [ ] **AC #4** — `RequestBodySizeLimitMiddleware`'s 1 MB cap is
  raised for `/ui/api/notebooks/*/papers/upload` only — extend
  via `prefix_caps={"/ui/api/notebooks": 10 * 1024 * 1024}`.
- [ ] **AC #5** — Vendored htmx + minimal CSS; no internet fetch
  at runtime. htmx 2.0.10 vendored to `frontend/static/htmx.min.js`
  with header comment naming version + source URL + license.

## Open questions (deduped union)

1. **Per-notebook detail view route shape** (R-1 OQ-3). Synthesis
   resolution: `GET /ui/notebooks/{slug}` returns a Jinja2-rendered
   detail page (full-navigation, NOT htmx-inline). Simpler than
   inline-expansion-via-htmx and matches the brief AC #1's
   "open link" language.

2. **paper_id source for the upload endpoint** (R-1 OQ-2).
   Synthesis resolution: REQUIRE a separate `paper_id` form field
   in the multipart POST (NEVER derive from `file.filename`).
   The UI form has both `<input type="file">` and
   `<input name="paper_id">` fields. Per FM-4, derive nothing from
   `file.filename`.

3. **Upload idempotency on duplicate** (R-1 OQ-1). Synthesis
   resolution: 409 on duplicate `(slug, paper_id)` junction row
   (mirrors m7's `add_paper` behavior); the on-disk file
   overwrites idempotently via `os.replace()`. Documented in
   the handler docstring.

None block implementation.

## External writes required

| Type | Target | Why |
|---|---|---|
| HTTP GET (one-time, during implementation) | `https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js` | Vendor htmx into `frontend/static/htmx.min.js`. One-time download; file committed to the repo. No runtime internet fetch (AC #5). |

The htmx download is the only external action. Phase 4 should
surface this for explicit user authorization.

## Orchestrator synthesis note

Strong agreement on every architectural axis except htmx version
(R-1 picked the older LTS for size; R-2 picked the current stable).
Synthesis went with R-2 (current stable) because the semantic
differences R-1 cited don't apply to the basic htmx attributes m8
uses, and the project's preference for current-stable on small
vendored deps is consistent with the kuzu==0.11.3 pin (last
stable before archive) and the BGE-M3 v2 pin (latest stable
encoder).

The implementation surface is **~700 LOC across ~10 files** —
templates (4-5 files), upload handler (~80 LOC in existing
router), middleware extension (~20 LOC), URL normalizer
extension (~10 LOC), tests (~250 LOC), vendored htmx + CSS, and
the new `server/routes/ui.py`. Above the inline threshold by
file count but every pattern is established. **Inline path**
chosen — delegation overhead is not worth it for serial work.

Commit type: `feat(server)` (server source changes dominate;
templates are a small addition).
