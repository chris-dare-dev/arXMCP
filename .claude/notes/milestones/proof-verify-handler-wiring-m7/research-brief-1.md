# Research Brief — proof-verify-handler-wiring-m7

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-22T02:10:00Z

---

## In-codebase context

### 1. Pure-ASGI middleware stack

`server/main.py:371–437` (verbatim from `create_app`):

```
# add_middleware adds in LIFO request order — the LAST call wraps the request FIRST.
# request flow: SecurityHeaders -> SecFetchSite -> OriginValidation
#               -> HostValidation -> RequestBodySizeLimit
#               -> SessionCap -> BodySizeCap -> handler
app.add_middleware(TracingContextMiddleware)          # innermost
app.add_middleware(BodySizeCapMiddleware, byte_cap=cfg.result_byte_cap)
app.add_middleware(SessionCapMiddleware)
app.add_middleware(RequestBodySizeLimitMiddleware)
app.add_middleware(HostValidationMiddleware, allowed_port=None)
app.add_middleware(OriginValidationMiddleware, allowed_origins=cfg.allowed_origins)
app.add_middleware(SecFetchSiteMiddleware)
app.add_middleware(SecurityHeadersMiddleware)         # outermost
```

**`SecFetchSiteMiddleware` full decision logic** (`server/middleware.py:462–502`):

```python
async def __call__(self, scope, receive, send):
    if scope["type"] != "http":
        await self.app(scope, receive, send)
        return
    headers = scope.get("headers", [])
    sec_fetch_site = _get_header(headers, b"sec-fetch-site")
    if sec_fetch_site is None or sec_fetch_site == self._ALLOWED_VALUE:  # b"none"
        await self.app(scope, receive, send)
        return
    # Any other value (including "same-origin") → 403
    await _send_json_error(send, status=403, body={...})
```

Currently `SecFetchSiteMiddleware.__init__` takes only `app` — no path-prefix parameter. The class has **no carve-out mechanism at all**.

**Precedent for path-prefix carving**: `server/main.py::_BYTE_CAP_EXEMPT_PREFIXES` shows the canonical carve-out pattern:

```python
_BYTE_CAP_EXEMPT_PREFIXES = ("/healthz", "/readyz", "/metrics", "/mcp")

def _is_exempt_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _BYTE_CAP_EXEMPT_PREFIXES)
```

`BodySizeCapMiddleware.__call__` checks `_is_exempt_path(scope.get("path", ""))` at the top. This is the EXACT pattern to replicate in `SecFetchSiteMiddleware` for `/ui/*`.

**`BaseHTTPMiddleware` is project-banned** (CLAUDE.md §4.7): "Pure-ASGI middleware required. `BaseHTTPMiddleware` is project-banned (E06_S01 F1 — it silently no-ops response interception for SSE paths)." All existing middlewares follow the pure-ASGI `__init__(self, app) / async __call__(scope, receive, send)` pattern — this milestone's routes must do the same.

**FastAPI `APIRouter` is pure-ASGI-compatible**: the existing `health_router` and `debug_router` are both `fastapi.APIRouter` instances registered via `app.include_router(...)`. The middleware stack sees `scope["path"]` directly regardless of which router matched — path inspection in middleware does not require special FastMCP awareness.

### 2. SQLite-table conventions

`server/cache_sqlite.py` (Tier-1 cache) is the canonical SQLite pattern. Key decisions to mirror:

- **Connection**: `sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)` with an `asyncio.Lock` for serialization.
- **WAL mode**: `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL` at open.
- **Schema init**: inline `CREATE TABLE IF NOT EXISTS` at open time, no Alembic or sqlite-utils.
- **Schema versioning**: `PRAGMA user_version` integer; if `current_version < SCHEMA_VERSION` drop + recreate.
- **Async pattern**: `asyncio.to_thread(_sync_fn)` for all SQL I/O; stdlib `sqlite3` only — no `aiosqlite` dependency.
- **Parent dir**: `db_path.parent.mkdir(parents=True, exist_ok=True)` at open.

`server/config.py:103` shows the existing SQLite path convention:
```python
cache_db_path: Path = Path("var/arxmcp/cache/retrieval.db")
theorem_names_db_path: Path = Path("var/arxmcp/index/sqlite/theorem_names.db")
```

The notebooks DB should be `var/arxmcp/notebooks/notebooks.db` (sibling to the per-notebook dirs in `var/arxmcp/notebooks/`).

**New `Config` field required**: `notebooks_db_path: Path = Path("var/arxmcp/notebooks/notebooks.db")`. Adding a field means the env-var scanner in `_scan_unknown_arxmcp_env_vars` picks it up automatically via `Config.model_fields`, but **the scanner also means any new `ARXMCP_*` var in the environment will be rejected at startup** — no action needed for the scanner.

**CRITICAL: `Config` uses `extra="forbid"`** (`model_config = SettingsConfigDict(..., extra="forbid")`). A new `notebooks_db_path` field must be declared in `Config` before the server can start.

### 3. FastAPI route registration

The existing precedent (`server/main.py:440–448`):
```python
app.include_router(health_router)
from server.routes.debug import router as debug_router
app.include_router(debug_router, prefix="/debug")
```

The UI routes belong at:
```python
from server.routes.notebooks import router as notebooks_router
app.include_router(notebooks_router, prefix="/ui/api")
```

This makes the full URL `/ui/api/notebooks` match the brief. Create `server/routes/notebooks.py` with a `fastapi.APIRouter()` instance.

**`/mcp` is a `FastMCP` sub-app** mounted via `app.mount("/mcp", ...)`. FastMCP's `TransportSecurityMiddleware` applies to `/mcp` only. The `/ui/*` routes are plain FastAPI routes — they do NOT enter the FastMCP session-management layer and do NOT enforce `Mcp-Session-Id`. This is correct by design: the notebook REST surface is browser-facing, not MCP-protocol.

**`SessionCapMiddleware`** only fires on `POST /mcp` paths (it checks `path == "/mcp" or path.startswith("/mcp/")`). The `/ui/*` routes are transparent to it.

### 4. arXiv URL → paper_id normalization

`ingest/identifiers.py::PAPER_ID_RE` (verbatim):
```python
_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?\Z"      # new style: 2401.00001 or 2401.00001v3
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?\Z" # old style: hep-th/0001234
)
PAPER_ID_RE = re.compile(_PAPER_ID_FULL_PATTERN)
```

The `\Z` anchor (not `$`) is load-bearing per **m1-rect-F3**: `is_valid_paper_id("2604.26204\n")` returned `True` before the fix. The URL normalizer must NOT strip-then-pass a raw URL to `PAPER_ID_RE` — only the extracted paper_id segment should be validated.

**Recommended helper signature** (to implement in `server/routes/notebooks.py`):
```python
def _arxiv_url_to_paper_id(url: str) -> str | None:
    """Extract and validate the paper_id from an arXiv or ar5iv URL.
    Returns None for non-matching or malformed inputs.
    Handles:
      https://arxiv.org/abs/<paper_id>[v<N>]
      https://ar5iv.labs.arxiv.org/html/<paper_id>
    """
```

Implementation: `urlparse(url)`, check netloc in `{"arxiv.org", "ar5iv.labs.arxiv.org"}`, extract the path segment after `/abs/` or `/html/`, strip leading `/`, then call `is_valid_paper_id(segment)`. Do NOT attempt to import `requests` or call external network; this is pure URL parsing. Returns `None` on any mismatch — the handler returns HTTP 422 with a JSON body.

**No existing URL-parsing helper** in the codebase. All handlers receive pre-validated `paper_id` strings directly. This is new surface.

### 5. `SecFetchSiteMiddleware` exemption mechanism

**Recommended approach**: add an `exempt_prefixes` constructor parameter:

```python
class SecFetchSiteMiddleware:
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        exempt_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self._exempt_prefixes = exempt_prefixes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send); return
        path = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in self._exempt_prefixes):
            await self.app(scope, receive, send); return
        # existing Sec-Fetch-Site check ...
```

Wire in `create_app`:
```python
app.add_middleware(SecFetchSiteMiddleware, exempt_prefixes=("/ui",))
```

This mirrors the `BodySizeCapMiddleware`'s `_BYTE_CAP_EXEMPT_PREFIXES` pattern exactly and is pure-ASGI-compatible. The `/ui` prefix carve-out allows `Sec-Fetch-Site: same-origin` on any `/ui/*` path, which is correct: htmx POSTs from the browser to the same-origin daemon will carry `same-origin`.

### 6. Test surface plumbing

The canonical middleware test pattern is `fastapi.testclient.TestClient(app)` (NOT `httpx.AsyncClient`). See `tests/security/test_origin_binding.py` which uses:
```python
from fastapi.testclient import TestClient
from server.main import create_app
# builds TestClient with tmp_path monkeypatch for lancedb_path
```

The `_build_test_client` helper in `test_origin_binding.py` is the exact fixture shape to mirror. AC #4 requires:
- `Sec-Fetch-Site: same-origin` → 403 on `/mcp` (existing behavior)
- `Sec-Fetch-Site: same-origin` → NOT 403 on `/ui/api/notebooks`

These are synchronous HTTP-layer tests — no MCP session, no model loading needed. The lancedb_path can be an empty `tmp_path` (same as origin-binding tests).

**Recommended test file**: `tests/security/test_sec_fetch_site_carveout.py` (stays with the security test family; mirrors `test_origin_binding.py`'s placement).

---

## Prior decisions and lessons

- **m6 is complete** (`phase: complete`, commit `c6229fa`). The `tools/_notebook_common.py` module ships `SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{2,30}$")`, `validate_slug()`, and `notebook_dir()` with symlink rejection. The REST handlers must import and reuse these — NOT redefine.

- **Git log confirms m6 is the most recent notebook work** (`b4e5dd5` feat, `c6229fa` rect). The `var/arxmcp/notebooks/` directory layout is established.

- **No UI routes exist yet**. `server/routes/` contains only `debug.py`. There is no `notebooks.py`, no `/ui` prefix, no notebook SQLite DB.

- **`BodySizeCapMiddleware` uses `_BYTE_CAP_EXEMPT_PREFIXES`** but `/ui` is NOT in it. The notebook REST endpoints return small JSON payloads (<1 KB) — they will NOT exceed the 256 KB cap — but the implementer should verify no responses approach it. No exemption needed for `/ui` in `BodySizeCapMiddleware`.

- **`EXPECTED_TOOL_SCHEMA_SHA256` must remain unchanged** (AC #5). No changes to `server/tools.py::ALL_TOOLS` or any `ToolMeta`. The notebook REST surface is a sibling `APIRouter`, not an MCP tool.

- **Known landmine (CLAUDE.md §8 row 8)**: `uv run pytest` must use `/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest`. System pytest may pick up Python 3.9.

- **`KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py`** is load-bearing; this milestone touches no ML code so no risk of removal.

---

## External sources

- **MCP 2025-06-18 spec**: not directly relevant — notebook REST surface is a sibling FastAPI route, not an MCP tool. No new MCP surface means no spec compliance obligation for these endpoints.
- **Anthropic prompt-caching docs**: not relevant — no tool-schema change, no BP1/BP2 breakpoint impact.
- **No external vendor docs required** for this milestone (SQLite stdlib, FastAPI routing, arXiv URL parsing are all in-codebase or stdlib).

---

## Recommendation

**Implement as follows:**

1. **Add `notebooks_db_path: Path = Path("var/arxmcp/notebooks/notebooks.db")` to `server/config.py::Config`**. This is the single Config field the REST layer needs; it follows the `cache_db_path` convention exactly.

2. **Create `server/routes/notebooks.py`** with:
   - A `NotebookStore` class (mirrors `Tier1Store` shape: `asyncio.Lock`, `asyncio.to_thread`, WAL mode, `SCHEMA_VERSION`, `PRAGMA user_version` migration) with two tables:
     ```sql
     CREATE TABLE notebooks (
       slug TEXT PRIMARY KEY,
       display_name TEXT NOT NULL DEFAULT '',
       lancedb_path TEXT NOT NULL,
       created_at TEXT NOT NULL
     );
     CREATE TABLE notebook_papers (
       slug TEXT NOT NULL REFERENCES notebooks(slug),
       paper_id TEXT NOT NULL,
       added_at TEXT NOT NULL,
       PRIMARY KEY (slug, paper_id)
     );
     ```
   - A `_arxiv_url_to_paper_id(url: str) -> str | None` helper using `urllib.parse.urlparse` + `ingest.identifiers.is_valid_paper_id`.
   - A `fastapi.APIRouter` with five routes: GET/POST/DELETE `/notebooks`, GET/POST/DELETE `/notebooks/{slug}/papers`.
   - **Import `validate_slug` and `notebook_dir` from `tools._notebook_common`** — do not redefine the slug regex.

3. **Add `SecFetchSiteMiddleware(exempt_prefixes=("/ui",))`** in `server/main.py::create_app`. Modify `SecFetchSiteMiddleware.__init__` to accept `exempt_prefixes: tuple[str, ...] = ()`.

4. **Wire the router in `create_app`** after the debug router: `app.include_router(notebooks_router, prefix="/ui/api")`.

5. **Open the `NotebookStore` in the lifespan** (via `app.state.notebook_store`) alongside `Resources.startup`. Close it in the `finally` block.

6. **Test file**: `tests/security/test_sec_fetch_site_carveout.py` for AC #4. Notebook CRUD tests in `tests/test_notebook_api.py` (or `tests/routes/test_notebooks.py`).

**Rationale**: the `Tier1Store` / `asyncio.to_thread` pattern is proven in this codebase and avoids a new dependency (no `aiosqlite`). The `exempt_prefixes` constructor param is the cleanest carve-out — it's pure-ASGI-compatible, testable, and mirrors the `BodySizeCapMiddleware` precedent exactly.

---

## Open questions

1. **`NotebookStore` lifecycle in the lifespan**: should it be opened inside `Resources.startup()` (requires `Resources` to know about the notebook DB path) or independently in `lifespan()` before the `yield`? Recommendation: open independently in `lifespan()`, attach to `app.state.notebook_store`, and close in the `finally` block. This avoids entangling notebook concerns with the ML-resource lifecycle.

2. **`POST /ui/api/notebooks` body**: the brief says `{"slug": "bridgeland"}` but also lists `display_name` and `lancedb_path` as schema columns. Should `POST` accept `display_name` and `lancedb_path` from the caller, or derive them? Recommendation: `lancedb_path` is auto-derived as `str(notebooks_base / slug / "lancedb")`; `display_name` is optional with default `""`. This keeps the POST body minimal.

3. **`GET /ui/api/notebooks` return shape**: not specified in the brief. Recommendation: `[{"slug": ..., "display_name": ..., "lancedb_path": ..., "created_at": ...}, ...]` — list of all notebooks ordered by `created_at DESC`.

4. **`Sec-Fetch-Site: same-origin` on `/ui/api/notebooks` with htmx**: htmx sends `same-origin` when the request comes from the same origin. The carve-out makes `/ui/*` exempt from the Sec-Fetch-Site check entirely — meaning `cross-site` also passes. This is intentional: the notebook UI is not an MCP protocol surface and does not need the DNS-rebinding defense that protects `/mcp`. Document this trade-off explicitly in the middleware docstring update.

No open questions block implementation start. The above questions are design choices the implementer can resolve unilaterally with the recommendations above.

---

## External writes the implementation will require

- **None** — this milestone creates new files under `server/routes/`, modifies `server/middleware.py`, `server/main.py`, `server/config.py`, and adds tests. All writes are local.
- **New on-disk SQLite file**: `var/arxmcp/notebooks/notebooks.db` is created at server startup (first run). It lives under `var/` (gitignored) and is not a tracked file.
- **New on-disk directory**: `var/arxmcp/notebooks/<slug>/` created by `POST /ui/api/notebooks`. Also `var/` tree, gitignored.

Both are local filesystem mutations, not external writes requiring Phase 4 authorization.
