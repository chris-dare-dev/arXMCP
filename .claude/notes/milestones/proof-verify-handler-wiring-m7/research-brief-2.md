# Research Brief — proof-verify-handler-wiring-m7

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T02:15:00Z

---

## In-codebase context

### SecFetchSiteMiddleware: current behavior confirms the bug

`server/middleware.py::SecFetchSiteMiddleware` (line 413–503) implements:

> "Any other value (``cross-site`` / ``same-site`` / ``same-origin`` / empty /
> garbage) → 403 with a JSON error body."

The allowed value constant at line 457 is:

```python
_ALLOWED_VALUE = b"none"
```

This is **not a bug in the MCP path** — for `/mcp`, rejecting `same-origin` is
correct (the MCP server has no same-origin partner; any browser fetch to `/mcp` is
an attack surface per Threat 5). The problem is that once `/ui/*` exists, the
htmx JS running at `http://127.0.0.1:7733/ui/` making a `fetch()` POST to
`http://127.0.0.1:7733/ui/api/notebooks` WILL receive `Sec-Fetch-Site: same-origin`
from the browser — and the current middleware will 403 it. The carve-out is genuine
and necessary.

Confirmed by `tests/security/test_origin_binding.py::TestSecFetchSiteRejection`:
`test_same_origin_rejected` (line 157) explicitly tests that `same-origin` returns 403.
This test must be preserved; the new test for `/ui/*` must show `same-origin` **passes**
there but fails on `/mcp`.

The `SessionCapMiddleware` (lines 916–929) already implements a path-prefix carve-out
pattern worth reusing:

```python
path: str = scope.get("path", "")
if method != "POST" or not (
    path == _MCP_PATH_PREFIX or path.startswith(_MCP_PATH_PREFIX + "/")
):
    await self.app(scope, receive, send)
    return
```

Use the same `path.startswith("/ui/") or path == "/ui"` prefix guard inside
`SecFetchSiteMiddleware`. This is Option A (in-middleware path check).

**FM-3 concern:** Use `path.startswith("/ui/") or path == "/ui"` — NOT a bare
`"/ui" in path` substring check. A request to `/mcp-ui/...` would NOT match the
prefix form; it would match a substring form. Use the prefix form, matching the
`SessionCapMiddleware` precedent.

### BodySizeCapMiddleware: `/ui/*` needs exemption

`server/main.py::_BYTE_CAP_EXEMPT_PREFIXES` (line 105) is:

```python
_BYTE_CAP_EXEMPT_PREFIXES = ("/healthz", "/readyz", "/metrics", "/mcp")
```

The `/ui/api/notebooks` responses will be small JSON, well under 256 KB. No exemption
needed. Leave this constant unchanged.

### SQLite pattern: inherit `cache_sqlite.py`'s approach

`server/cache_sqlite.py` uses:

```python
conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
```

All I/O via `asyncio.to_thread` + a per-store `asyncio.Lock`. This pattern is
established, tested, and documented as safe for the project's concurrency model.
The notebooks store MUST inherit this identical pattern — do not introduce `aiosqlite`
or bare sync calls.

**FM-6 (separate DB file vs same file):** The brief says "sibling to `cache_db_path`".
This means a **separate file** (`var/arxmcp/cache/notebooks.db`), not the same
`retrieval.db`. This is the correct call: adding tables to `retrieval.db` would
change its `user_version`/schema, potentially triggering the DROP-AND-RECREATE
migration in `Tier1Store.open()` and wiping the Tier-1 cache on startup. Use a
separate file.

**Add `Config.notebooks_db_path`** defaulting to `Path("var/arxmcp/cache/notebooks.db")`.
This matches the `cache_db_path` / `theorem_names_db_path` pattern in `config.py`.
Adding a new Config field does NOT affect EXPECTED_TOOL_SCHEMA_SHA256 (tool schema
is independent of Config fields).

### Proposed schema

```sql
CREATE TABLE notebooks (
    slug           TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL DEFAULT '',
    lancedb_path   TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL  -- ISO-8601 UTC, e.g. '2026-05-22T02:00:00Z'
);

CREATE TABLE notebook_papers (
    slug           TEXT NOT NULL,
    paper_id       TEXT NOT NULL,
    added_at       TEXT NOT NULL,  -- ISO-8601 UTC
    PRIMARY KEY (slug, paper_id),
    FOREIGN KEY (slug) REFERENCES notebooks(slug) ON DELETE CASCADE
);
CREATE INDEX idx_notebook_papers_slug ON notebook_papers(slug);
```

Enable `PRAGMA foreign_keys = ON` per connection so `ON DELETE CASCADE` works
(SQLite FK enforcement is off by default).

### FastAPI router: Option A (plain `APIRouter`)

**Recommendation: Use `app.include_router(ui_router, prefix="/ui")` (Option A).**
Do NOT use `app.mount("/ui", sub_app)` (Option B).

Reasoning:
- Option B (`app.mount`) causes Starlette to bypass global middleware for the
  sub-app. This means `SecurityHeadersMiddleware`, `HostValidationMiddleware`,
  `OriginValidationMiddleware` would all be skipped on `/ui/*` requests. That is
  a security regression (Threat 5 mitigation bypassed by architecture, not by
  explicit exemption).
- Option A keeps the full middleware stack intact. The only required middleware
  change is adding a path-aware carve-out in `SecFetchSiteMiddleware`. All other
  middlewares remain correct as-is for `/ui/*` (Origin validation still fires,
  Host validation still fires, body-size cap still fires).

Handler signatures:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

ui_router = APIRouter(tags=["ui"])

class NotebookCreate(BaseModel):
    slug: str
    display_name: str = ""

class PaperAdd(BaseModel):
    arxiv_url: str

@ui_router.get("/api/notebooks")
async def list_notebooks() -> list[dict]: ...

@ui_router.post("/api/notebooks", status_code=201)
async def create_notebook(body: NotebookCreate) -> dict: ...

@ui_router.delete("/api/notebooks/{slug}", status_code=204)
async def delete_notebook(slug: str) -> None: ...

@ui_router.get("/api/notebooks/{slug}/papers")
async def list_papers(slug: str) -> list[dict]: ...

@ui_router.post("/api/notebooks/{slug}/papers", status_code=201)
async def add_paper(slug: str, body: PaperAdd) -> dict: ...

@ui_router.delete("/api/notebooks/{slug}/papers/{paper_id}", status_code=204)
async def remove_paper(slug: str, paper_id: str) -> None: ...
```

Use `async def` handlers + `asyncio.to_thread` for SQLite calls (matching
`cache_sqlite.py` pattern). This is NOT the sync handler threadpool pattern —
that would be `def` (sync), which FastAPI auto-runs in a threadpool but loses
async context. The `asyncio.to_thread` pattern from `cache_sqlite.py` is the
established approach.

---

## Prior decisions and lessons

From MEMORY.md (doc-placement-correction-pattern, 2026-05-17):
> Correct destination for audit docs is `.claude/docs/security-threat-N-audit.md`.
> The brief does not mandate a new doc here — m7 is not a security audit milestone.
> No new `.md` doc needed outside `.claude/`.

From MEMORY.md (no-delimiter-wrapping-exists-at-v1):
> This milestone does not touch tool result wrapping — irrelevant but noted for
> completeness.

From m6 research-synthesis (2026-05-21):
> Slug regex canonical form: `SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{2,30}$")` in
> `tools/_notebook_common.py`. The REST handler MUST import this same regex — do NOT
> re-define it. FM-2 (path traversal via slug) is defended by `validate_slug()` from
> `tools._notebook_common` + the containment check in `notebook_dir()`.

Git log shows `0555ea2 chore(notes): mark E13_S04b external writes as completed` is
the most recent commit — the E13 audit cycle is fully closed. No adjacent milestone
landmines relevant to m7.

---

## External sources

### Sec-Fetch-Site spec (W3C Fetch Metadata, 2022)

From `https://w3c.github.io/webappsec-fetch-metadata/`:

> "The `Sec-Fetch-Site` HTTP request header exposes the relationship between a
> request initiator's origin and its target's origin."
>
> Valid values: **`cross-site`**, **`same-origin`**, **`same-site`**, and **`none`**.
>
> Value assignment algorithm: starts at `same-origin`, then downgrades based on
> redirect chain. **`none`** is set only for "a navigation request that was explicitly
> caused by a user's interaction with the user agent" (address bar, bookmark).
>
> The `Sec-` prefix makes these "forbidden response-header names" — JavaScript
> running in a page cannot SET them in fetch() requests; browsers append them
> automatically.

**Key implication for m7:** An htmx POST from `http://127.0.0.1:7733/ui/` to
`http://127.0.0.1:7733/ui/api/notebooks` is a same-origin subresource fetch — the
browser WILL set `Sec-Fetch-Site: same-origin`. The current middleware 403s this.
The carve-out is necessary and correct.

A `fetch()` from the same page to `/mcp` would also produce `same-origin` — the
carve-out must be path-scoped to `/ui/*` only, leaving `/mcp` to continue rejecting
`same-origin`.

### CORS for `/ui/api/*`

The server runs at `http://127.0.0.1:7733`. The htmx requests originate from the
same host and port — this is a **same-origin** request, not a cross-origin request.
CORS headers (Access-Control-Allow-Origin etc.) are NOT required for same-origin
fetches; browsers do not send a CORS preflight for same-origin requests.

**No new CORS configuration needed for `/ui/api/*`.** The existing
`ARXMCP_ALLOWED_ORIGINS` config (managed by `OriginValidationMiddleware`) is a
server-side Origin allow-list, not a CORS policy. Since htmx requests from the UI
carry `Origin: http://127.0.0.1:7733` which is already in `LOOPBACK_ORIGIN_HOSTS`,
they will pass `OriginValidationMiddleware` with zero configuration changes.

---

## Recommendation

**Implement with Option A (APIRouter, path-aware carve-out in SecFetchSiteMiddleware).**

Concrete steps:
1. Add `Config.notebooks_db_path = Path("var/arxmcp/cache/notebooks.db")`.
2. Create `server/notebooks_store.py` — a `NotebooksStore` class mirroring
   `Tier1Store`: `asyncio.Lock` + `asyncio.to_thread`, WAL mode, FK enforcement.
3. Wire `NotebooksStore` into `server/resources.py` (open on startup, close on
   shutdown).
4. Create `server/routes/ui.py` — `APIRouter` with the 6 routes above.
5. `app.include_router(ui_router, prefix="/ui")` in `server/main.py` AFTER the
   middleware stack is registered (order of `include_router` vs `add_middleware`
   does not affect which middleware fires — FastAPI applies all middleware globally).
6. Patch `SecFetchSiteMiddleware.__call__` to add a prefix check:
   `if path.startswith("/ui/") or path == "/ui": pass through same-origin`.
7. Slug validation in REST handlers: call `tools._notebook_common.validate_slug()`
   directly — import the shared helper, don't redefine.
8. arxiv_url normalization: extract paper_id from URL using the path component;
   validate with `ingest.identifiers.is_valid_paper_id`. Accepted forms listed in
   FM-4 below.

---

## Open questions

**OQ-1: ar5iv URL form in AC #2.** The AC states:
`POST /ui/api/notebooks/bridgeland/papers {"arxiv_url":"https://arxiv.org/abs/2604.26204"}`
But the m8 roadmap brief mentions `ar5iv.labs.arxiv.org/html/<id>` as an accepted
paste form. Does m7's URL normalizer also handle `ar5iv.labs.arxiv.org/html/<id>`?
The AC is unambiguous (`arxiv.org/abs/<id>` only). **Implementer should treat
`ar5iv.labs.arxiv.org` as out of scope for m7** unless the roadmap explicitly
contradicts this.

**OQ-2: `display_name` + `lancedb_path` in POST body.** AC #1 shows
`POST /ui/api/notebooks {"slug":"bridgeland"}` — only `slug`. The schema has
`display_name` and `lancedb_path` columns. Should the POST body accept these too,
or are they always derived (e.g., `lancedb_path` auto-set to
`var/arxmcp/notebooks/{slug}/lancedb`)? Recommend: accept optional `display_name`
in the body; auto-derive `lancedb_path` from slug + `NOTEBOOKS_BASE` (same layout
as `tools/_notebook_common.py::notebook_dir`).

---

## Failure-mode analysis

**FM-1 (SQLite concurrency — SQLITE_BUSY):** The `Tier1Store` pattern uses WAL +
`asyncio.Lock` for serialized writes. Inheriting this pattern for `NotebooksStore`
closes FM-1: WAL mode allows concurrent readers + one writer; the `asyncio.Lock`
ensures only one async task writes at a time. No additional mitigation needed beyond
inheriting the established pattern.

**FM-2 (slug path-traversal — `{"slug":"../etc/passwd"}`):** `SLUG_RE =
re.compile(r"^[a-z][a-z0-9-]{2,30}$")` rejects `..`, slashes, uppercase, shell
metacharacters. Import `tools._notebook_common.validate_slug()` directly in the REST
handler. Raises `NotebookError`; translate to `HTTPException(422)`. **Belt-and-braces:**
after slug validation, call `tools._notebook_common.notebook_dir(slug)` before
`mkdir` — this runs the containment check that catches symlinks (F3 from m6).

**FM-3 (prefix-vs-substring bug in SecFetchSiteMiddleware carve-out):** The carve-out
check must be `path.startswith("/ui/") or path == "/ui"`. A bare `"/ui" in path`
would incorrectly exempt `/evil-ui/malicious`. Cite `SessionCapMiddleware` as
precedent for the correct prefix form.

**FM-4 (arxiv_url surface area — which forms are accepted?):**
- `https://arxiv.org/abs/2604.26204` — extract `2604.26204`; ACCEPT
- `https://arxiv.org/abs/2604.26204v3` — extract `2604.26204v3`; ACCEPT
  (identifiers.py PAPER_ID_RE handles `vN` suffix)
- `https://arxiv.org/abs/hep-th/0001234` — old-style; ACCEPT (PAPER_ID_RE covers)
- `https://www.arxiv.org/abs/2604.26204` — `www.` subdomain; REJECT (normalizer
  should only accept `arxiv.org` or `ar5iv.labs.arxiv.org` as hosts; `www.arxiv.org`
  is not in scope per AC)
- `https://arxiv.org/pdf/2604.26204.pdf` — `/pdf/` path prefix + `.pdf` suffix;
  strip suffix and prefix to extract paper_id; ACCEPT with normalization, OR REJECT
  (simpler). **Recommend REJECT for m7 and document accepted forms.**

URL normalization recipe: `urlparse(arxiv_url).path` → strip leading `/abs/` →
validate remainder with `is_valid_paper_id`. Reject if host is not `arxiv.org`.

**FM-5 (duplicate slug INSERT race):** Two concurrent POSTs to
`POST /ui/api/notebooks {"slug":"X"}`. Both pass the existence check before either
commits. The PRIMARY KEY constraint on `notebooks.slug` catches the second INSERT;
the handler must catch `sqlite3.IntegrityError` and return HTTP 409. The
`asyncio.Lock` inside `NotebooksStore` serializes all writes, so in practice only
one INSERT runs at a time — but the `IntegrityError` catch is still required for
correctness (and for the non-concurrent idempotent case per AC #1).

**FM-6 (schema isolation — separate DB file):** **RESOLVED: use a separate file**
`var/arxmcp/cache/notebooks.db`. Adding tables to `cache_db_path` (`retrieval.db`)
would potentially trigger `Tier1Store`'s DROP-AND-RECREATE migration (it checks
`PRAGMA user_version`). Separate file = zero risk of cache wipe.

**FM-7 (referential integrity — orphaned notebook_papers rows):** `ON DELETE CASCADE`
on `notebook_papers.slug` FOREIGN KEY ensures `DELETE FROM notebooks WHERE slug=X`
automatically deletes all junction rows. Requires `PRAGMA foreign_keys = ON` per
connection (SQLite default is OFF). Add this pragma to `NotebooksStore._open_sync`.

**FM-8 (ar5iv URL form in paper add endpoint):** As noted in OQ-1, m7's AC only
names `arxiv.org/abs/<id>`. Do not add `ar5iv.labs.arxiv.org` URL parsing to m7.
If m8 needs it, m8 should extend the normalizer.

**FM-9 (POST creates directory — but directory already exists from prior DELETE):**
AC #3 states: after `DELETE /ui/api/notebooks/bridgeland`, subsequent
`POST {"slug":"bridgeland"}` must succeed. The on-disk `var/arxmcp/notebooks/bridgeland/`
directory still exists (deletion is metadata-only). The `mkdir(exist_ok=True)` call
in the POST handler must use `exist_ok=True` — not a bare `mkdir()` which would
raise `FileExistsError`. This is the minimal path to AC #3 passing.

---

## In-codebase cross-check against design notes

From `06-mcp-server-design.md` (load-bearing):
> "Tool definitions themselves are byte-stable across server restarts: pin schema,
> sort properties alphabetically, freeze descriptions in source."

m7 adds NO new MCP tools (confirmed by AC #5). `EXPECTED_TOOL_SCHEMA_SHA256` is
unchanged. `TOOL_SCHEMA_VERSION` is unchanged.

From `08-security-observability-ops.md` Threat 5:
> "`Sec-Fetch-Site: none` enforced where possible."

The carve-out for `/ui/*` is a **deliberate, documented exception** to Threat 5's
`none`-only enforcement. The exception is safe because:
1. The `/ui/*` route is still same-origin only (same 127.0.0.1:7733 host/port).
2. `OriginValidationMiddleware` still fires on `/ui/*` (Option A preserves it).
3. `HostValidationMiddleware` still fires on `/ui/*`.
The carve-out exempts `same-origin` on `/ui/*` — it does NOT allow `cross-site`.

**No conflicts found** between the milestone brief and the design constitution,
subject to: (a) separate notebooks DB file, (b) Option A router (not Option B mount),
(c) slug validation via shared `_notebook_common.validate_slug`.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no GitHub issue filing, no infra
mutation. The implementation writes to:
- `var/arxmcp/cache/notebooks.db` (SQLite, gitignored, runtime artifact)
- `var/arxmcp/notebooks/{slug}/` (directory, gitignored, runtime artifact)

Neither constitutes an external write in the sense of §8 of agent-conventions.md.
