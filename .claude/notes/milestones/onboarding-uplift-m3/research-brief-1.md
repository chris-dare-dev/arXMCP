# Research Brief — onboarding-uplift-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T04:45:00Z

## In-codebase context

### 1. Existing `/ui/api/*` REST surface seam map

**Router wiring** (`server/main.py:738-740`):
```python
from server.routes.notebooks import router as notebooks_router
app.include_router(notebooks_router, prefix="/ui/api")
```
And UI pages (`server/main.py:745-747`):
```python
from server.routes.ui import router as ui_router
app.include_router(ui_router, prefix="/ui")
```

**Router instantiation** (`server/routes/notebooks.py:76`):
```python
router = APIRouter(tags=["ui"])
```

**Dependency injection pattern** (`server/routes/notebooks.py:167-182`):
```python
def get_notebooks_store(request: Request) -> NotebooksStore:
    store = getattr(request.app.state, "notebooks_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="notebook store not initialized",
        )
    return store
```

**Pydantic body models** (`server/routes/notebooks.py:229-233`):
```python
class PaperAdd(BaseModel):
    """Body for ``POST /ui/api/notebooks/{slug}/papers``."""
    arxiv_url: str = Field(min_length=1, max_length=512)
```

**Response-shape convention** (from existing handlers):
- `POST /notebooks` → 201 + `dict[str, str]`
- `DELETE /notebooks/{slug}` → 204 + None
- `POST /notebooks/{slug}/papers` → 201 + `{"slug": ..., "paper_id": ...}`

**Audit-log pattern** (mirror for new endpoints — `server/routes/notebooks.py:1027-1031`):
```python
logger.info(
    "uploaded %s: slug=%s paper_id=%s bytes=%d claimed_filename=%r",
    "pdf" if is_textbook else "ar5iv html",
    slug, paper_id, len(content), file.filename,
)
```

The new `POST /ui/api/admin/repair-registry` and `POST /ui/api/notebooks/<slug>/reconcile-marker` must use the same `logger` (module-level `logger = logging.getLogger(__name__)` at `server/routes/notebooks.py:74`).

**Note on `/admin/` prefix**: No existing admin-auth gate exists for `/ui/api/admin/*`. All `/ui/api/*` routes are operator-trusted per the loopback-only deployment model. The three new endpoints should be added to `server/routes/notebooks.py` (or a new `server/routes/admin.py` — see Recommendation).

### 2. `NotebooksStore.create_notebook` signature

(`server/notebooks_store.py:330-376`)
```python
async def create_notebook(
    self,
    slug: str,
    display_name: str,
    lancedb_path: str,
    created_at: str,
    notebook_kind: str = "arxiv",
    parse_status: str | None = None,
) -> None:
    """Insert a notebook row. Raises sqlite3.IntegrityError on duplicate slug."""
```

`IntegrityError`-on-duplicate is the canonical 409-path (m2 F1 lesson). The m3 `repair-registry` endpoint MUST call `create_notebook` — never a direct SQLite INSERT — and catch `sqlite3.IntegrityError` to handle already-registered slugs (these go into `already_registered`, not an error).

`get_notebook(slug)` returns `dict[str, str] | None` with keys: `slug`, `display_name`, `lancedb_path`, `created_at`, `notebook_kind`, `parse_status`, `parse_error`, `parsed_html_path`.

`list_notebooks()` returns `list[dict[str, str]]` ordered by `created_at DESC, slug ASC`.

### 3. `corpus-version.json` — live shape (verbatim from `var/arxmcp/notebooks/bridgeland-stability/lancedb/corpus-version.json`):
```json
{"chunk_count": 10298, "chunker_version": "v1.1", "created_at": "2026-05-28T02:38:05Z", "embedder_version": "bge-m3@5617a9f6", "paper_count": 53, "version": 645}
```

Keys: `chunk_count` (int), `chunker_version` (str), `created_at` (ISO-8601 UTC), `embedder_version` (str), `paper_count` (int), `version` (int, the LanceDB dataset version integer).

The `reconcile-marker` endpoint preserves `version`, `chunker_version`, `embedder_version`, `created_at` and recomputes ONLY `chunk_count` + `paper_count`. The marker filename constant: `CORPUS_VERSION_MARKER_NAME = "corpus-version.json"` (`ingest/store.py:121`).

The `CorpusVersionInfo.to_dict()` serializes with alphabetical keys (`server/corpus.py:353-362`):
```python
def to_dict(self) -> dict:
    """Serialize with alphabetical keys for byte-stability."""
    return {
        "chunk_count": self.chunk_count,
        "chunker_version": self.chunker_version,
        "created_at": self.created_at,
        "embedder_version": self.embedder_version,
        "paper_count": self.paper_count,
        "version": self.version,
    }
```
The `reconcile-marker` rewrite MUST use `json.dumps(..., sort_keys=True, separators=(",", ":"))` or mirror `to_dict()` key order for byte-stability.

### 4. LanceDB checkout-at-version contract

(`server/corpus.py:231-321`)
```python
def open_chunks_table(
    lancedb_path: str | Path | None = None,
    version: int | None = None,
) -> lancedb.table.Table:
    ...
    db = lancedb.connect(str(resolved_path))
    tbl = db.open_table(CHUNKS_TABLE_NAME)

    if version is not None:
        try:
            tbl.checkout(version)
        except (ValueError, LookupError, KeyError) as exc:
            ...
    return tbl
```

The API is: `lancedb.connect(path)` → `db.open_table(name)` → `tbl.checkout(version)` (in-place). After checkout the table is read-only. The `reconcile-marker` handler should call `open_chunks_table(lancedb_path, version=info.version)` which returns a version-pinned read-only handle; then `tbl.count_rows()` for chunk count.

**For distinct paper_ids**: LanceDB does not have a SQL `COUNT(DISTINCT)` API directly. Use `tbl.to_arrow()["paper_id"].unique().to_pylist()` or `len(set(tbl.to_lance().to_table(columns=["paper_id"])["paper_id"].to_pylist()))`. For large tables this materializes all paper_ids — acceptable for the reconcile path (not a hot loop). Alternatively, use a pandas/polars aggregation via `tbl.to_pandas()["paper_id"].nunique()`.

**Concurrent ingest safety**: `tbl.checkout(version)` pins a SPECIFIC historical version. A concurrent writer committing new rows creates a NEW version integer — the pinned read handle never sees new writes. This is the LanceDB MVCC contract confirmed by `tests/test_mvcc.py::TestHandleIndependence`. No torn reads are possible.

### 5. Per-notebook directory layout

(`tools/_notebook_common.py:33-147`)
```python
NOTEBOOKS_BASE: Path = REPO_ROOT / "var" / "arxmcp" / "notebooks"

def notebook_dir(slug: str, *, base: Path | None = None) -> Path:
    """Return the per-notebook dir under NOTEBOOKS_BASE."""
    validate_slug(slug)
    nb_base = (base or NOTEBOOKS_BASE).resolve()
    unresolved_target = nb_base / slug
    if unresolved_target.is_symlink():
        raise NotebookError(...)
    target = unresolved_target.resolve()
    target.relative_to(nb_base)  # containment check
    return target

def notebook_lancedb_path(slug: str, *, base: Path | None = None) -> Path:
    """Return notebook_dir(slug) / 'lancedb'."""
    return notebook_dir(slug, base=base) / "lancedb"
```

For `repair-registry`: walk `NOTEBOOKS_BASE.iterdir()`, skip non-dirs, call `validate_slug(d.name)` (catch `NotebookError` → skip), check `(d / "lancedb" / "corpus-version.json").is_file()` as the marker presence test.

### 6. Health surfaces

**`compute_health_status` structure** (`server/health.py:295-470`):
- Returns `{"status": "pass"|"warn"|"fail", "http_code": int, "checks": dict, "summary": str}`
- Checks dict keys: `embedder:status`, `lancedb:status`, `corpus:version`, `notebooks:count`, `disk:utilization`, `backup:time`, `process:uptime`
- `_RETRIEVAL_CHECK_KEYS` in `server/routes/ui.py:170-175`: `{"embedder:status", "lancedb:status", "corpus:version", "notebooks:count"}` — these flip the badge to DEGRADED

**`Resources.startup_chunk_count` and `startup_unindexed_rows`** (`server/resources.py:386-396`):
```python
startup_chunk_count: int = -1   # STALE BY DESIGN — captured once at startup
startup_unindexed_rows: int = -1  # STALE BY DESIGN — captured once at startup
```

**CRITICAL DESIGN QUESTION**: `startup_chunk_count` is the SHARED GLOBAL corpus count (read from `config.lancedb_path` which is `var/arxmcp/index/lancedb/`), NOT per-notebook. For the `GET /ui/api/notebooks/<slug>/health` per-notebook endpoint, these startup values are IRRELEVANT — they measure the shared corpus, not the per-notebook LanceDB. See Open Questions section.

### 7. `/ui/status-badge` current implementation

(`server/routes/ui.py:219-273`)
```python
@router.get(
    "/status-badge", response_class=HTMLResponse, include_in_schema=False
)
async def ui_status_badge(request: Request) -> HTMLResponse:
    ...
    fragment = (
        f'<span id="status-badge" class="status-badge status-badge--{css}" '
        f'aria-live="polite" aria-atomic="true" '
        f'hx-get="/ui/status-badge" hx-trigger="every 10s" '
        f'hx-swap="outerHTML" title="{safe}">{safe}</span>'
    )
    return HTMLResponse(content=fragment)
```

The `title="{safe}"` attribute is the natural hook for the tooltip. For m3, when `label` is `"DEGRADED"` or `"WARN"`, the implementer should extend the fragment to include a `<details>` tooltip. The `_classify_status_badge` function (`server/routes/ui.py:178-216`) already identifies WHICH checks are failing — the tooltip should read the report's `checks` dict to name them.

**Route still exists post-m1/m2**: confirmed. Last touched in `ui-badge-disambiguate` milestone (commit `2df990c`).

### 8. Audit-log pattern

Existing pattern from `server/routes/notebooks.py:74`:
```python
logger = logging.getLogger(__name__)
```

All new endpoint handlers in `server/routes/notebooks.py` should use this same module-level logger with INFO-level log lines. Example from ingest trigger (`server/routes/notebooks.py` — same file): the format is `logger.info("action: slug=%s key=%s ...", slug, key)`.

### 9. Makefile patterns for m3

**`make add` dual-mode pattern** (`Makefile:437-469`):
```makefile
add:
    @if curl -sf --max-time 2 "http://127.0.0.1:$(ARXMCP_BIND_PORT)/healthz" >/dev/null 2>&1; then \
        echo "server up — POST /ui/api/notebooks/$(NOTEBOOK)/papers"; \
        curl -sf --fail-with-body --max-time 30 \
            -X POST -H "Content-Type: application/json" \
            -d '{"arxiv_url":"https://arxiv.org/abs/$(PAPER)"}' \
            "http://127.0.0.1:$(ARXMCP_BIND_PORT)/ui/api/notebooks/$(NOTEBOOK)/papers" \
            || { echo "ERROR: REST call failed — see above" >&2; exit 1; }; \
        echo; \
    else \
        # server-down: direct Python fallback ...
    fi
```

For `make reconcile`:
- Server-up: `curl -sf -X POST "http://127.0.0.1:$(ARXMCP_BIND_PORT)/ui/api/notebooks/$(NOTEBOOK)/reconcile-marker"`
- Server-down: `$(PYTHON) -m tools.notebook_reconcile_marker $(NOTEBOOK)` (a new CLI script)
- Global shared corpus: if `NOTEBOOK=` is unset, reconcile `var/arxmcp/index/lancedb/corpus-version.json`

For `make repair-registry`:
- Server-up: `curl -sf -X POST "http://127.0.0.1:$(ARXMCP_BIND_PORT)/ui/api/admin/repair-registry"`
- Server-down: `$(PYTHON) -m tools.notebook_repair_registry`

### 10. m2 F8 deferred LOW — `.PHONY` line

Current `Makefile:1`:
```
.PHONY: help bootstrap test eval up status ingest delta re-embed re-embed-all ingest-recover-preambles watchdog cutover notebook-cutover daily-report parser-failures-report sbom refresh-arxiv-ca init add notebook-list
```

This is a 219-char single-line declaration. m3 must split into per-section `.PHONY:` groups and add `repair-registry` and `reconcile` to the appropriate group (FIRST-TIME or EVERYTHING-ELSE).

### 11. Test fixture pattern

(`tests/test_notebook_api.py:45-82`)
```python
@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    return base

@pytest.fixture
def client(tmp_path, notebooks_base, monkeypatch) -> Iterator[TestClient]:
    import asyncio
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        monkeypatch.setattr(notebooks_module, "_now_iso", lambda: "2026-05-22T03:00:00+00:00")
        with TestClient(app) as c:
            yield c
    finally:
        loop.run_until_complete(store.close())
        loop.close()
```

New test files (`tests/test_admin_endpoints.py`, `tests/test_reconcile_endpoint.py`, `tests/test_notebook_health.py`) should mirror this pattern. For reconcile/health tests, the test will need to create a minimal LanceDB fixture (write a `corpus-version.json` to `tmp_path/lancedb/`) and optionally a minimal lancedb dataset (or mock `open_chunks_table`).

### 12. BP1/BP2 cross-check

The new endpoints are all under `/ui/api/` or `/ui/`, NOT the MCP `/mcp/` surface. They do NOT add MCP tools, do NOT touch `server/tools.py::ALL_TOOLS`, and do NOT touch `server/prompts.py`.

Current pins:
- `EXPECTED_TOOL_SCHEMA_SHA256 = "c7df4c5c10c86693ac8553b7d079b55fba21749881c233f0f298955379d13375"` (`tests/test_server_tool_schema.py:95`)
- `EXPECTED_BP1_SHA256 = "483344e3fcdea1d64de893cc669c9f142fd6f1198d4c8d383cd9c232558959bc"` (`tests/test_prompts.py:649-650`)

**Both hashes must remain UNCHANGED after m3.** The implementer MUST run `make test` to verify.

### 13. Recent git log

Last 20 commits show:
- `58bfb41` — `ui-attractive-polish-m3` (dark mode) — touches `frontend/`, `server/routes/ui.py`
- `8122ace` — `onboarding-uplift-m2` finalized
- `e3ec3f3` — m2 rect (server, tools, tests)
- `43b9085` — m2 feat (server, tools, ingest)

No in-flight parallel work on `server/routes/notebooks.py` or `server/health.py`. The m2 rect landed cleanly. m3 starts from `58bfb41` (HEAD).

## Prior decisions and lessons

From MEMORY.md (injected):

- **`user-version-shared-across-stores` (2026-05-31)**: `PRAGMA user_version` is per-database-FILE. m3 does NOT add a new schema version to `NotebooksStore` (no new columns needed). If a future m3 addition requires a schema change, add a `v4→v5` block in `NotebooksStore._open_sync`. For m3 as scoped, `SCHEMA_VERSION` stays at `4`.

- **`ingest-to-tools-import-direction`**: `ingest/` files do not import from `tools/`. The `repair-registry` server-down fallback script should live in `tools/` (like `notebook_init.py`, `notebook_list_offline.py`) and import from `tools._notebook_common` — not from `server/`.

- **m2 critique F1 lesson (direct SQL banned)**: Both new endpoints MUST route writes through `NotebooksStore.create_notebook`. No direct `conn.execute("INSERT INTO notebooks ...")`.

- **Doc placement**: Any new Markdown files go under `.claude/`, not in `server/` or `tools/`.

## External sources

None required. This milestone is purely local REST surface + Make targets + badge tooltip. No MCP spec changes, no prompt-caching impact, no LanceDB version concerns beyond the existing `lancedb.connect` / `tbl.checkout` API already verified in production.

The LanceDB checkout-at-version API is verified by `tests/test_mvcc.py::TestHandleIndependence` in the existing test suite — no external docs needed.

## Recommendation

**Implement all 3 new endpoints in `server/routes/notebooks.py`** (not a new file). Rationale: the admin endpoint (`repair-registry`) needs `NotebooksStore` via the same `get_notebooks_store` dependency already wired in that module, and the per-notebook endpoints (`reconcile-marker`, `health`) belong to the same notebooks surface. Splitting into a new file adds an include_router call in `main.py` and a new test file but no architectural benefit.

For the badge tooltip extension in `ui_status_badge`: use an HTML `<details>/<summary>` nested inside the `<span>` — but confirm htmx `hx-swap="outerHTML"` on a `<span>` that contains a `<details>` is valid HTML (it is, per HTML5). The `_classify_status_badge` function already has the check structure; pass `report["checks"]` into a helper that renders the actionable lines.

For `make repair-registry` server-down path: implement `tools/notebook_repair_registry.py` that opens `NotebooksStore` directly (same pattern as `tools/notebook_list_offline.py`). For `make reconcile` server-down path: implement `tools/notebook_reconcile_marker.py` that reads the JSON, opens `open_chunks_table`, counts rows, rewrites JSON.

For the `reconcile-marker` distinct paper_id count: use `tbl.to_lance().to_table(columns=["paper_id"]).to_pandas()["paper_id"].nunique()` — or `len(set(tbl.to_lance().to_table(columns=["paper_id"])["paper_id"].to_pylist()))`. Avoid materializing all columns.

## Open questions

**(a) Per-notebook `health` endpoint vs. shared `startup_chunk_count`:**

**RESOLVED**: `Resources.startup_chunk_count` is the SHARED corpus count (from `var/arxmcp/index/lancedb/`), NOT per-notebook. The brief's "use cached `Resources.startup_chunk_count`" is **INCORRECT for a per-notebook health endpoint** — there is no cached per-notebook count in `Resources`. The `GET /ui/api/notebooks/<slug>/health` endpoint MUST read the per-notebook LanceDB on-demand (via `open_chunks_table(notebook_lancedb_path(slug), version=info.version)` then `tbl.count_rows()`). The brief's cardinal safety check ("MUST NOT cause an expensive scan on every request") applies to the SHARED `/status` endpoint context, not this per-notebook endpoint which is explicitly per-call. The implementer should: read the notebook's `corpus-version.json`, open the LanceDB at that version, call `count_rows()`, compare to marker's `chunk_count`. This is a fresh count per call — acceptable because `/ui/api/notebooks/<slug>/health` is an operator-triggered diagnostic, not a 10s hot poll.

**(b) Admin auth gate for `/ui/api/admin/*`:**

**RESOLVED**: No existing admin-auth gate exists. All `/ui/api/*` routes are operator-trusted under the loopback-only deployment model (`server/config.py::reject_non_loopback`). The `repair-registry` endpoint under `/ui/api/admin/` is safe without additional auth — the deployment boundary IS the auth. No new middleware needed.

**(c) `repair-registry` display_name and created_at for re-registered notebooks:**

**RESOLVED**: For a re-registered on-disk dir:
- `display_name`: use `""` (empty string) — same default as `NotebookCreate` model default. The operator can rename later via `PATCH /ui/api/notebooks/<slug>`.
- `lancedb_path`: auto-derive as `str(notebook_dir(slug) / "lancedb")` — same derivation as the `create_notebook` REST handler.
- `created_at`: use `_now_iso()` (the time of repair), NOT the marker's `created_at` (which is the ingest timestamp, not the notebook-registration timestamp). This is consistent with the `create_notebook` handler which always uses `_now_iso()`.
- `notebook_kind`: default `"arxiv"` — `repair-registry` cannot infer kind from the on-disk layout; operators can adjust if needed.

No open questions — implementation can proceed on the above recommendations.

## External writes the implementation will require

None — this milestone is purely local.
