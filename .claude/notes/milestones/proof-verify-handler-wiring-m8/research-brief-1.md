# Research Brief — proof-verify-handler-wiring-m8

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-22T00:00:00Z

---

## In-codebase context

### m7 inheritance — what is reusable verbatim

The m7 REST router is mounted in `server/main.py` as:

```python
from server.routes.notebooks import router as notebooks_router
app.include_router(notebooks_router, prefix="/ui/api")
```

m8 adds a new upload endpoint to the same router. The dependency-injection
pattern (`get_notebooks_store` → `request.app.state.notebooks_store`) is
reusable verbatim; new handlers in the same `router = APIRouter(tags=["ui"])`
object inherit it automatically.

The m7 `_arxiv_url_to_paper_id` normalizer is defined at module scope in
`server/routes/notebooks.py` and currently rejects ar5iv:

```python
#: arXiv URL host whitelist for m7. Only ``arxiv.org`` (the canonical
#: paper host) is in scope. ``ar5iv.labs.arxiv.org`` is explicitly
#: out of scope per the m7 synthesis Disagreement-3 resolution;
#: m8's paste UI may extend this if needed.
_ACCEPTED_HOSTS: frozenset[str] = frozenset({"arxiv.org"})
```

And in `_arxiv_url_to_paper_id`, the path-prefix check is hard-wired to
`/abs/`:

```python
prefix = "/abs/"
if not path.startswith(prefix):
    return None
candidate = path[len(prefix):]
```

**m8 must extend both.** The cleanest change is a per-host prefix dispatch
table. Concretely:

```python
_ACCEPTED_HOSTS: frozenset[str] = frozenset({"arxiv.org", "ar5iv.labs.arxiv.org"})

_HOST_PATH_PREFIX: dict[str, str] = {
    "arxiv.org": "/abs/",
    "ar5iv.labs.arxiv.org": "/html/",
}
```

Then in `_arxiv_url_to_paper_id`, replace the hardcoded `prefix = "/abs/"` line
with:

```python
prefix = _HOST_PATH_PREFIX.get(parsed.hostname, "")
if not prefix or not path.startswith(prefix):
    return None
```

This is a one-function change to the existing helper — no new abstraction needed.

### Existing app.mount convention

`server/main.py` has two `app.mount(...)` calls today:

```python
app.mount("/metrics", metrics_wrapper)
# ... (FastMCP via mount_mcp, which calls app.mount inside)
```

There is NO existing `app.mount("/static", ...)` for `StaticFiles`. m8 introduces
the first one. The canonical FastAPI pattern is:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/ui/static", StaticFiles(directory="frontend/static"), name="static")
```

Mount path recommendation: `/ui/static` (not `/static`). This keeps the entire
`/ui/` prefix subtree consistent (UI routes at `/ui/api/*`, static assets at
`/ui/static/*`, HTML page at `/ui/`). A standalone `/static` path would be
outside the UI subtree and would require separate carve-outs in
`SecFetchSiteMiddleware`.

`Jinja2Templates` is configured via:

```python
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="frontend/templates")
```

Both `StaticFiles` and `Jinja2Templates` are included with FastAPI — no extra
dep beyond what is already in `pyproject.toml` for FastAPI >= 0.115.

**CONFLICT FLAG: `python-multipart` is NOT in `pyproject.toml`.** FastAPI's
`UploadFile` (used for the ar5iv HTML drag-drop upload endpoint) requires
`python-multipart` to be installed. The current `pyproject.toml` has no
`python-multipart` entry. m8 MUST add:

```
"python-multipart>=0.0.9",  # UploadFile / multipart/form-data for ar5iv HTML upload
```

**CONFLICT FLAG: `jinja2` is NOT in `pyproject.toml`.** FastAPI's
`Jinja2Templates` requires the `jinja2` package. It is NOT currently declared
as a dep. m8 MUST add:

```
"jinja2>=3.1",  # server-side HTML templating for the /ui/ page
```

(`aiofiles` is NOT needed if templates are rendered synchronously via
`templates.TemplateResponse(...)` — FastAPI's templating is sync-rendered.)

### `RequestBodySizeLimitMiddleware` — constructor and carve-out mechanism

Current constructor signature (verbatim from `server/middleware.py`):

```python
def __init__(
    self,
    app: Callable[..., Awaitable[None]],
    max_bytes: int = REQUEST_BODY_MAX_BYTES,
) -> None:
    self.app = app
    self.max_bytes = max_bytes
```

It has NO `prefix_overrides` or `exempt_prefixes` yet. The `SecFetchSiteMiddleware`
`exempt_prefixes` is the existing precedent for path-based conditional behavior,
but `RequestBodySizeLimitMiddleware` does not yet have it.

**Recommended extension:** Add a `prefix_caps: dict[str, int]` constructor
argument (parallel to `SecFetchSiteMiddleware`'s `exempt_prefixes`). In
`__call__`, before the default cap, check whether `scope["path"]` starts with
any key in `prefix_caps` and substitute the override:

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

Then in `create_app`:

```python
app.add_middleware(
    RequestBodySizeLimitMiddleware,
    prefix_caps={"/ui/api/notebooks": 10 * 1024 * 1024},  # 10 MB for ar5iv upload
)
```

The path `/ui/api/notebooks/*/papers/upload` would match
`path.startswith("/ui/api/notebooks")` — this also covers the general notebooks
prefix without affecting the 1 MB default for all other paths.

**IMPORTANT security note:** The `prefix_caps` key should be
`"/ui/api/notebooks"` (not `"/ui/api/notebooks/*/papers/upload"` — glob
matching is NOT implemented). This means all POST bodies to any `/ui/api/notebooks/*`
route get the 10 MB cap, not just `/upload`. That is acceptable because all
other `/ui/api/notebooks/*` routes accept small JSON bodies which are
much smaller than 10 MB anyway; the cap is a ceiling, not a floor.

### `BodySizeCapMiddleware` vs `RequestBodySizeLimitMiddleware` — the distinction

`BodySizeCapMiddleware` is defined in `server/main.py` and caps **RESPONSE** bodies
(outgoing). Its docstring: "Pure-ASGI middleware enforcing the 256 KB inline-result
cap." It intercepts `http.response.body` events.

`RequestBodySizeLimitMiddleware` is defined in `server/middleware.py` and caps
**REQUEST** bodies (incoming). Its docstring: "Cap incoming request bodies at
`max_bytes`." It drains the `receive()` callable.

m8 only needs to touch `RequestBodySizeLimitMiddleware`. The 256 KB response cap
in `BodySizeCapMiddleware` does NOT apply to the `/ui/` HTML pages because they
are served as responses through the same middleware; HTML pages that exceed 256 KB
would be truncated with a 413. **POTENTIAL ISSUE:** the `GET /ui/` response (a
Jinja2-rendered HTML page listing all notebooks) must stay under 256 KB, or it needs
to be added to `_BYTE_CAP_EXEMPT_PREFIXES` in `server/main.py`. With a small
notebook count this won't be an issue at v1; but the brief should note this as a
latent concern (add `/ui/` to the exempt set preemptively).

### `frontend/` directory placement

CLAUDE.md §1: "Subdirs other than `.claude/` — Only `README.md` and `CLAUDE.md`
(if useful for that subdir). No other Markdown." And §5 directory layout shows only
`README.md` and `CLAUDE.md` as Markdown allowed at subdir level.

`frontend/templates/` and `frontend/static/` are **source code** (HTML templates,
a JS file, CSS) — not Markdown docs. The placement rule applies only to Markdown.
New source directories at repo root are allowed. `frontend/` as a top-level
directory is therefore correct per CLAUDE.md §1 and §5.

**`pyproject.toml` packages:** The current `[tool.setuptools] packages =
["server", "ingest", "tools", "shim"]` does NOT include `frontend`. `frontend/` is
NOT a Python package — it contains templates and static assets, not Python modules.
No change to `packages = [...]` is needed. FastAPI's `StaticFiles` and
`Jinja2Templates` are pointed at directory paths, not Python packages.

**`.gitignore` implications:** The existing `.gitignore` has `__pycache__/`
globally. Since `frontend/` has no Python files, there is no `__pycache__` risk.
The vendored `htmx.min.js` and CSS files MUST be committed (not gitignored) — they
are checked-in assets. No `.gitignore` additions needed for `frontend/`.

### `app.mount` calls in `server/main.py` — existing convention to follow

```python
app.mount("/metrics", metrics_wrapper)   # ASGI callable, line ~498
# and via mount_mcp():
# app.mount(path, sub_app)              # FastMCP ASGI sub-app
```

m8 adds, in the same `create_app` function, before the `include_router` calls:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/ui/static", StaticFiles(directory="frontend/static"), name="static")
```

Placement: mount static files BEFORE `include_router` calls (so the router takes
precedence for `/ui/api/*`). The `/ui/` HTML route itself is added via
`include_router` (a new `ui_router` or added to the existing notebooks router scope).

### Vendored htmx version recommendation

**Recommend htmx 1.9.12** — the latest stable 1.9.x release. Source URL for
the implementer to download:

```
https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js
```

The file MUST:
1. Be checked into the repo at `frontend/static/htmx.min.js`.
2. Carry a comment header at the top of the file (prepend manually after download):
   ```
   /* htmx 1.9.12 — https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js */
   ```
3. NOT be gitignored. The repo currently has no pattern that would catch it.

Do NOT use htmx 2.x — the 2.x line dropped `hx-swap-oob` defaults and changed
`hx-trigger` semantics; 1.9.x is the stable, widely-documented LTS line. At 14 KB
minified it meets the brief's stated size requirement.

---

## Prior decisions and lessons

From the m7 implementation summary:
- **m7 synthesis D3** explicitly deferred `ar5iv.labs.arxiv.org/html/` to m8:
  "m7's normalizer is minimal — m8 can extend it one-line."
- `_arxiv_url_to_paper_id` docstring already documents the ar5iv rejection as
  "out of m7 scope" — not a bug, a deferred feature.
- The `NotebooksStore` lives at `app.state.notebooks_store` — the upload handler
  must go through the same `get_notebooks_store` FastAPI dependency.
- The `var/arxmcp/notebooks/{slug}/` directory is created on notebook POST. The
  `ar5iv/` subdirectory does NOT yet exist — the upload handler must create it
  with `(var/arxmcp/notebooks/{slug}/ar5iv/).mkdir(parents=True, exist_ok=True)`.
- The `notebook_dir()` helper from `tools/_notebook_common.py` includes the
  m6 F3 symlink-rejection containment check — use it in the upload handler to
  derive the target directory safely.

From git log, m7 shipped as `ead7af9` (2 days ago); m8 starts from that base.

The `SecFetchSiteMiddleware` with `exempt_prefixes=("/ui",)` is already in place
and correctly handles `same-origin` for `/ui/*`. The upload endpoint at
`/ui/api/notebooks/{slug}/papers/upload` will already benefit from the existing
carve-out — no SecFetchSite change needed for m8.

**Known banned patterns to avoid:**
- `BaseHTTPMiddleware` is project-banned (E06_S01 F1). The `prefix_caps` extension
  to `RequestBodySizeLimitMiddleware` MUST remain pure-ASGI.
- No `assert` for invariants — use `if ... raise RuntimeError(...)`.
- No new `.md` files outside `.claude/` (except navigational README/CLAUDE.md).

---

## External sources

MCP spec is not directly relevant to this milestone — m8 adds HTML/static serving
and a file-upload route, neither of which is part of the MCP tool surface. No MCP
tool modifications → `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need to be re-pinned.

FastAPI documentation for `StaticFiles` + `Jinja2Templates` + `UploadFile` is
stable and well-known. The critical dep fact (python-multipart required for
UploadFile) is verified from pyproject.toml inspection — it is absent.

---

## Recommendation

**Implement m8 as three coordinated pieces:**

1. **New deps** (`pyproject.toml`): add `jinja2>=3.1` and `python-multipart>=0.0.9`.

2. **`RequestBodySizeLimitMiddleware` extension**: add `prefix_caps: dict[str, int] | None = None`
   to the constructor; check path prefix before applying the default cap. Wire in
   `create_app` with `prefix_caps={"/ui/api/notebooks": 10 * 1024 * 1024}`. Add
   `/ui/` to `_BYTE_CAP_EXEMPT_PREFIXES` in `server/main.py` so the response cap
   doesn't truncate large notebook lists.

3. **New UI router** (`server/routes/ui.py`): `GET /ui/` returning `TemplateResponse`;
   add `/ui/api/notebooks/{slug}/papers/upload` upload handler to `server/routes/notebooks.py`
   (same file, same router). Wire `StaticFiles` at `/ui/static`. Vendor htmx 1.9.12.

4. **Extend `_arxiv_url_to_paper_id`**: add `ar5iv.labs.arxiv.org` to `_ACCEPTED_HOSTS`
   and add the `_HOST_PATH_PREFIX` dispatch dict (one-function change).

This approach minimizes blast radius: no new routers are needed (the upload endpoint
joins the existing notebooks router), the middleware extension is backward compatible,
and the URL normalizer change is a self-contained two-line addition.

---

## Open questions

1. **Upload de-duplication**: if the same ar5iv HTML file (same paper_id) is
   uploaded twice to the same notebook, should it overwrite the on-disk file and
   return 200, or return 409 like the URL-paste route? The brief says "a junction
   row is created" but doesn't specify the idempotency contract for the file.
   **Recommendation:** overwrite on disk (idempotent file write), return 409 on
   duplicate junction row (mirrors existing `add_paper` behavior). Implementer
   should confirm this is correct before writing the handler.

2. **Paper ID extraction from the uploaded HTML filename**: the upload endpoint
   receives a `.html` file. The paper_id must come from somewhere — either from
   the `ar5iv.labs.arxiv.org` URL pattern in the filename (e.g. `2401.00001.html`),
   from a separate form field, or from the file content (parsing). The brief says
   "the file is stored under `var/arxmcp/notebooks/{slug}/ar5iv/` and a junction
   row is created" but doesn't specify where the paper_id comes from.
   **Recommendation:** derive paper_id from the filename (strip `.html` suffix,
   validate with `is_valid_paper_id`). This is the simplest approach and matches
   ar5iv's naming convention. Implementer must verify and document in the handler.

3. **`GET /ui/` template structure**: the brief says "listing notebooks with a
   create-notebook form and (for each notebook) an 'open' link." The 'open' link
   presumably navigates to a per-notebook detail page. But there is no `GET
   /ui/notebooks/{slug}` route in m7 or in the m8 brief. Does m8 implement a
   per-notebook detail page, or does the "open" link just expand inline via htmx?
   **Recommendation:** the detail view expands inline via htmx (`hx-get` on the
   "open" link fetching `/ui/api/notebooks/{slug}/papers` as an HTML fragment).
   This avoids needing a full second page route and keeps m8 scope tight.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| HTTP GET (one-time, during implementation) | `https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js` | Download and vendor the htmx JS file into `frontend/static/htmx.min.js`. This is a one-time download that the implementer runs manually; the result is committed to the repo. No runtime internet access. |

**No git push or GitHub API calls are required.** The vendored file download is
the only external write and occurs during Phase 2 (implementation), not Phase 4.
The orchestrator should surface this to the user as a single authorized one-time
download.
