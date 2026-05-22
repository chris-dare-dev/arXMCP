# Research Synthesis — proof-verify-handler-wiring-m7

**Orchestrator merge of:** `research-brief-1.md`, `research-brief-2.md`
**Generated:** 2026-05-22T03:00:00Z
**Mode:** standard (2× Sonnet in parallel)

## TL;DR for the implementer

Add a sibling REST surface (`/ui/api/notebooks` + `/ui/api/notebooks/{slug}/papers`)
backed by a NEW separate SQLite database file at
`var/arxmcp/cache/notebooks.db` (NOT in the existing `retrieval.db` — that
would risk Tier1Store's DROP-AND-RECREATE migration on schema bump).
Inherit the `cache_sqlite.py::Tier1Store` pattern verbatim:
`asyncio.to_thread` + `asyncio.Lock` + WAL mode + `PRAGMA user_version`
migration. Use `Option A` (plain `APIRouter` mounted via
`app.include_router(router, prefix="/ui")`) — NOT a separate FastAPI
sub-app via `app.mount(...)`, because Starlette `mount()` silently
bypasses parent-app middleware (Origin / Host / SecurityHeaders all
would be skipped — a security regression).

`SecFetchSiteMiddleware` gets a new `exempt_prefixes: tuple[str, ...] = ()`
constructor parameter and the same path-prefix pattern that
`BodySizeCapMiddleware` already uses
(`_BYTE_CAP_EXEMPT_PREFIXES = ("/healthz", "/readyz", "/metrics", "/mcp")`).
Use the prefix-match form (`path.startswith("/ui/") or path == "/ui"`),
NOT a substring check — `"/ui" in path` would incorrectly exempt
`/evil-ui/...`.

Estimated implementation surface: ~650 LOC across 7 files. Borderline
inline/delegated; **inline path** chosen because every pattern is
established (SQLite store, middleware exemption, router registration)
and the work is naturally serial.

## Resolved disagreements

### Disagreement 1 — DB file location

**R-1:** `var/arxmcp/notebooks/notebooks.db` (sibling to per-notebook dirs).
**R-2:** `var/arxmcp/cache/notebooks.db` (sibling to `cache_db_path`).

**Synthesis: R-2 wins.** The brief says verbatim: *"a `notebooks` SQLite
table (sibling to `cache_db_path`)"*. R-2's location matches the brief
verbatim and groups SQLite databases together under `var/arxmcp/cache/`.
R-1's location entangles the notebook DB with the per-notebook
data directories (which the m6 + m4 work treats as "operator/script
territory"), risking accidental wipe by `tools/notebook_purge.py`.

Final: `Config.notebooks_db_path: Path = Path("var/arxmcp/cache/notebooks.db")`.

### Disagreement 2 — DELETE `/papers` route shape

**R-1:** Does not enumerate single-paper DELETE separately.
**R-2:** Adds `DELETE /api/notebooks/{slug}/papers/{paper_id}` for
single-paper removal.

**Synthesis: R-2 wins.** The brief says "wire `/ui/api/notebooks/{slug}/papers`
(GET/POST/DELETE)" — the DELETE verb on a junction collection is most
naturally interpreted as single-row removal with the paper_id in the
path. The alternative ("delete all papers in notebook X") would be
operator-destructive without an explicit `purge=true` flag, which is
out of scope. The 6-route shape from R-2 is what to ship:

```
GET    /ui/api/notebooks
POST   /ui/api/notebooks
DELETE /ui/api/notebooks/{slug}                          (notebook metadata + cascading papers via FK)
GET    /ui/api/notebooks/{slug}/papers
POST   /ui/api/notebooks/{slug}/papers
DELETE /ui/api/notebooks/{slug}/papers/{paper_id}        (single-paper removal)
```

### Disagreement 3 — ar5iv URL form in AC #2

**R-1:** Handle both `arxiv.org/abs/<id>` AND `ar5iv.labs.arxiv.org/html/<id>`.
**R-2:** Only `arxiv.org/abs/<id>` for m7; defer ar5iv to m8 if needed.

**Synthesis: R-2 wins.** AC #2 names only `arxiv.org/abs/` explicitly:
*"normalizes the URL, validates against the existing `paper_id` regex"*
with example `https://arxiv.org/abs/2604.26204`. Be conservative: m7
accepts only `arxiv.org` host. If m8 surfaces an `ar5iv.labs.arxiv.org`
paste path, it can extend the normalizer one-line. Smaller m7 surface =
smaller adversary critique attack surface.

Accepted host: `arxiv.org` only. Accepted path prefixes: `/abs/`. All
other forms (`www.arxiv.org`, `arxiv.org/pdf/`, `ar5iv.labs.arxiv.org/html/`)
return HTTP 422 with a structured error naming what's accepted.

### Disagreement 4 — Module file location

**R-1:** `server/routes/notebooks.py` (matches `server/routes/debug.py` pattern).
**R-2:** `server/routes/ui.py` for the router; separate `server/notebooks_store.py`
for the store.

**Synthesis: hybrid wins** — R-1's filename for the router, R-2's
separation of store-vs-router into two files:
- `server/notebooks_store.py` — the `NotebooksStore` class (mirrors
  `server/cache_sqlite.py::Tier1Store`).
- `server/routes/notebooks.py` — the `fastapi.APIRouter` + 6 handlers.
- Wire in `server/main.py`:
  `app.include_router(notebooks_router, prefix="/ui/api")`.

Rationale: store is reusable (m9 will need to read it from the ingest
trigger handler too); router is the HTTP surface. Separating keeps
the unit-test surface tight (`NotebooksStore` is testable without
spinning up a FastAPI TestClient).

### Disagreement 5 — NotebooksStore lifecycle

**R-1:** Open independently in `lifespan()`, attach to `app.state.notebook_store`.
**R-2:** Wire into `server/resources.py`.

**Synthesis: R-1 wins.** Notebook concerns are HTTP-surface, not
ML-resource lifecycle. Entangling them with `Resources` (which owns
BGE-M3, LanceDB connection, embed semaphore) blurs ownership and
makes the `Resources` class harder to test in isolation. Open in
`lifespan()` block:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = ...
    app.state.notebook_store = await NotebooksStore.open(cfg.notebooks_db_path)
    try:
        # existing Resources.startup() etc.
        yield
    finally:
        await app.state.notebook_store.close()
        # existing Resources.shutdown()
```

Handler access pattern: FastAPI dependency injection
(`store: NotebooksStore = Depends(_get_notebook_store)`).

## Load-bearing facts the implementer needs

### Quoted middleware stack from `server/main.py:371-437`

```python
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

The ONLY change m7 makes to this stack:
```python
-app.add_middleware(SecFetchSiteMiddleware)
+app.add_middleware(SecFetchSiteMiddleware, exempt_prefixes=("/ui",))
```

### Quoted `SecFetchSiteMiddleware` current logic (`server/middleware.py:462-502`)

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

The carve-out adds a path-prefix bypass at the top:
```python
async def __call__(self, scope, receive, send):
    if scope["type"] != "http":
        await self.app(scope, receive, send); return
    path = scope.get("path", "")
    if any(path == p or path.startswith(p + "/") for p in self._exempt_prefixes):
        await self.app(scope, receive, send); return
    # existing Sec-Fetch-Site check ...
```

### Quoted `Tier1Store` SQLite pattern from `server/cache_sqlite.py`

```python
conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
```

All I/O via `asyncio.to_thread` + a per-store `asyncio.Lock`. Schema
versioning via `PRAGMA user_version`; if drift detected → DROP-AND-RECREATE.

For `NotebooksStore`, ADD per-connection `PRAGMA foreign_keys = ON` so
the `ON DELETE CASCADE` on `notebook_papers.slug` fires when a notebook
is deleted. SQLite default is OFF and must be re-set per connection
(it's a per-connection setting, not a database-file setting).

### Quoted `PAPER_ID_RE` from `ingest/identifiers.py:67`

```python
_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?\Z"      # new style: 2401.00001 or 2401.00001v3
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?\Z" # old style: hep-th/0001234
)
PAPER_ID_RE = re.compile(_PAPER_ID_FULL_PATTERN)
```

The `\Z` anchor (NOT `$`) is the m1-rect-F3 hardening — load-bearing.
The URL normalizer MUST extract the paper_id segment then pass it to
`is_valid_paper_id()`. Do NOT call `PAPER_ID_RE.match(url)` directly.

### Quoted `SLUG_RE` from `tools/_notebook_common.py:36`

```python
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")
```

The REST handler imports and calls `tools._notebook_common.validate_slug()` —
does NOT redefine the regex. `validate_slug()` raises `NotebookError` on
malformed input; handler translates to `HTTPException(status_code=422)`.

### Schema (from R-2, refined)

```sql
CREATE TABLE notebooks (
    slug           TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL DEFAULT '',
    lancedb_path   TEXT NOT NULL,
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

Schema versioning constant: `SCHEMA_VERSION = 1` in `notebooks_store.py`.

## Failure modes the implementer must inoculate against

Consolidated from R-2's catalog:

1. **FM-1 — SQLITE_BUSY under concurrent writes.** Mitigation: inherit
   the `Tier1Store` pattern (WAL + `asyncio.Lock`). Closed by
   construction.
2. **FM-2 — slug path-traversal (`{"slug": "../etc/passwd"}`).**
   Mitigation: import `validate_slug` from `tools/_notebook_common.py`
   (which is the m6 F1-CRITICAL closure). Belt-and-braces: also call
   `notebook_dir(slug)` which runs the m6 F3 symlink-rejection check
   before `mkdir`.
3. **FM-3 — prefix-vs-substring bug in the SecFetchSite carve-out.**
   Mitigation: use `path == p or path.startswith(p + "/")` form, not
   `p in path`. The existing `_BYTE_CAP_EXEMPT_PREFIXES` helper in
   `server/main.py:105` is the canonical form to mirror.
4. **FM-4 — arxiv_url surface area.** Accept only host `arxiv.org` +
   path prefix `/abs/`. Reject `www.arxiv.org`, `/pdf/`, version-
   suffix-bearing pdf paths, ar5iv hosts. Return 422 with a
   structured error naming accepted forms.
5. **FM-5 — duplicate slug INSERT race.** Mitigation: PRIMARY KEY on
   `notebooks.slug` + catch `sqlite3.IntegrityError` → HTTP 409.
   `asyncio.Lock` makes the in-process case impossible; the catch is
   for cross-process safety + idempotency per AC #1.
6. **FM-6 — schema isolation.** RESOLVED: use a separate DB file
   (`var/arxmcp/cache/notebooks.db`). Adding tables to `retrieval.db`
   would trigger `Tier1Store`'s `user_version` migration.
7. **FM-7 — orphaned notebook_papers rows.** Mitigation:
   `ON DELETE CASCADE` on the FK + `PRAGMA foreign_keys = ON` per
   connection.
8. **FM-9 — POST after DELETE: stale on-disk directory.** AC #3
   requires re-creating the same slug after DELETE; the on-disk
   `var/arxmcp/notebooks/<slug>/` may still exist (deletion is
   metadata-only). Mitigation: `mkdir(parents=True, exist_ok=True)`
   in the POST handler — never bare `mkdir()`.

R-2's FM-8 (ar5iv URL form in m7) folded into FM-4 via Disagreement 3
resolution.

## Acceptance-criteria mapping

- [ ] **AC #1** — `POST /ui/api/notebooks {"slug":"bridgeland"}` creates
  row + on-disk dir; idempotent → HTTP 409 on duplicate. Implementer
  verifies via `sqlite3.IntegrityError` catch returning 409 + a TestClient
  test that POSTs twice and asserts (201, 409).
- [ ] **AC #2** — `POST /ui/api/notebooks/{slug}/papers
  {"arxiv_url": "https://arxiv.org/abs/2604.26204"}` normalizes URL via
  `_arxiv_url_to_paper_id(url) -> str | None`, validates via
  `is_valid_paper_id`, writes junction row. TestClient test covers
  arxiv.org/abs/ accept + each FM-4 reject case.
- [ ] **AC #3** — `DELETE /ui/api/notebooks/{slug}` drops SQLite rows
  (cascading via FK) but leaves `var/arxmcp/notebooks/{slug}/` untouched.
  Subsequent POST with same slug succeeds. Verified by inspecting
  the directory still exists after DELETE.
- [ ] **AC #4** — `SecFetchSiteMiddleware` carve-out for `/ui/*`.
  Test at `tests/security/test_sec_fetch_site_carveout.py` mirroring
  `test_origin_binding.py` shape: 403 on `/mcp` POST with
  `Sec-Fetch-Site: same-origin`; 2xx on `/ui/api/notebooks` with the
  same header.
- [ ] **AC #5** — `EXPECTED_TOOL_SCHEMA_SHA256` unchanged. No
  modifications to `server/tools.py::ALL_TOOLS`. Verified by the
  existing `tests/test_server_tool_schema.py` test passing without
  re-pinning.
- [ ] **AC #6** — `make test` green. Verified by full suite run.

## Open questions (deduped union)

1. **POST body `display_name` + `lancedb_path` shape.** R-1 + R-2 both
   surfaced. **Synthesis resolution:** accept optional `display_name`
   in POST body (default `""`); ALWAYS auto-derive `lancedb_path` from
   `str(NOTEBOOKS_BASE / slug / "lancedb")`. The caller doesn't need
   to know the layout; the auto-derivation matches what
   `tools/notebook_init.py` does.

2. **GET `/ui/api/notebooks` response shape.** R-1 surfaced.
   **Synthesis resolution:** `[{"slug", "display_name", "lancedb_path",
   "created_at"}, ...]` ordered by `created_at DESC`. ISO-8601 UTC
   timestamps. Empty list (NOT 404) when no notebooks exist.

3. **Where do timestamps come from?** Implicit. **Synthesis resolution:**
   use `datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")`
   in the handler before INSERT. Test fixture monkeypatches a
   `_now_iso()` helper for deterministic time values in tests.

4. **HTTP 422 vs 400 for malformed slug / URL.** **Synthesis resolution:**
   422 for validation failures (matches Pydantic/FastAPI conventions);
   409 for duplicate slug (Conflict); 404 for missing notebook on
   GET/DELETE/papers-add; 201 for successful create; 204 for successful
   delete; 200 for successful read.

5. **Should the `OriginValidationMiddleware` allow-list need any
   update for `/ui/*`?** R-2 surfaced. **Synthesis resolution:** NO.
   The default `LOOPBACK_ORIGIN_HOSTS` already covers
   `http://127.0.0.1:7733`, which is the same-origin where htmx will
   come from. Zero config change needed.

None are blockers.

## External writes required

**None.** Phase 4 has no blocking external-write gates. The
implementation creates:
- `var/arxmcp/cache/notebooks.db` (SQLite, gitignored, runtime artifact)
- `var/arxmcp/notebooks/<slug>/` directories on POST (gitignored)

Both are local filesystem mutations only.

## Orchestrator synthesis note

The two researchers converged tightly on every architectural axis (Option
A vs B, separate DB file, asyncio.to_thread pattern, shared
`validate_slug`, schema with FK + CASCADE). The 5 minor disagreements
all resolved with clear reasoning. R-1's strength was in-codebase
plumbing detail (quoted middleware order, exact line refs for the
exemption pattern, the BodySizeCapMiddleware precedent). R-2's strength
was the failure-mode catalog and the explicit FastAPI mount-vs-include
trade-off rationale (mount bypasses parent middleware — a real
security regression risk worth catching at synthesis time).

The implementation surface is borderline at the inline/delegated
threshold (~650 LOC, 7 files vs the 500 LOC / 5 file rule). **Inline
path is the right call** because:
- Every pattern is established (`Tier1Store`, `_BYTE_CAP_EXEMPT_PREFIXES`,
  `app.include_router`)
- Work is naturally serial (store → routes → middleware tweak → tests)
- Delegation overhead (worktree, sub-agent prompt, merge step) outweighs
  the parallelism benefit at this size

Commit type: `feat(server)` (server source changes are dominant). The
m4 pattern of mostly-tests + small surface doesn't apply — m7 is a
real new surface.
