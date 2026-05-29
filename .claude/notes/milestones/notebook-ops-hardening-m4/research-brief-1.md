# Research Brief — notebook-ops-hardening-m4

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T15:00:00Z

---

## In-codebase context

### `/status` placement and route registration

The health routes live in `server/health.py` and are registered in `server/main.py` via:

```python
# server/main.py:584
app.include_router(health_router)
```

The `health_router` is `APIRouter(tags=["health"])` (line 166 in `health.py`). The new
`GET /status` handler belongs in `server/health.py` alongside `healthz` and `readyz`, and
should be added to the existing `router` object. No new file needed.

**`/status` is a plain HTTP route, NOT an MCP tool.** Tool-schema SHA256 is unaffected. BP1
prompt-cache is unaffected. No `EXPECTED_TOOL_SCHEMA_SHA256` re-pin required.

### Byte-cap exempt list — `/status` must be added

`server/main.py:106-117`:
```python
_BYTE_CAP_EXEMPT_PREFIXES = (
    "/healthz", "/readyz", "/metrics", "/mcp",
    "/ui/static",
)
```

`/status` is not exempt. Its response body will be ~500 bytes, so it will NOT exceed the
256 KB `BodySizeCapMiddleware` cap — no exemption needed in practice. However, for parity
with the other health routes and correctness (no buffering delay), add `/status` to
`_BYTE_CAP_EXEMPT_PREFIXES` alongside `/healthz` and `/readyz`.

### Readiness logic the `/status` handler must reuse

`server/health.py:182-260` (the `readyz` handler):

```python
@router.get("/readyz")
async def readyz(request: Request) -> Response:
    resources: Resources | None = getattr(request.app.state, "resources", None)
    if resources is None or not resources.warm:
        ...return JSONResponse(status_code=503, ...)
    if resources.degraded is not None:
        return JSONResponse(status_code=503, content={"status": "degraded", ...})
    # 200 ready path:
    startup_count = resources.startup_chunk_count
    return JSONResponse(status_code=200, content={"status": "ready", ...})
```

`resources.warm` is `True` only after `Resources.startup` completes. `resources.degraded`
is a `DegradedState` dataclass or `None`. **`/readyz` 503-on-degraded behavior MUST NOT
change** (AC4 of the brief). The `/status` handler reads the same state but maps
`degraded → warn` with HTTP 200.

`Resources.is_resource_warm(name)` (line 979):
```python
def is_resource_warm(self, name: str) -> bool:
    if name == "embedder" or name == "lancedb":
        return self.warm
    if name == "reranker":
        return self.warm and self.reranker_model is not None
    raise KeyError(...)
```

### Data sources for `/status` checks

**`corpus_version`** — `resources.corpus_info.version` (int). Already exposed in `readyz`
200 body via `resources.corpus_info.version` (readable at line 283 of `health.py`:
`CORPUS_VERSION_GAUGE.set(resources.corpus_info.version)`).

**notebook count** — Call `await store.list_notebooks()` and take `len(...)`. The store is
always present when `resources` is warm (lifespan opens it before `Resources.startup`
yields, line 336 in `main.py`). Access pattern from handlers:

```python
# server/routes/notebooks.py:173
store = getattr(request.app.state, "notebooks_store", None)
if store is None:
    raise HTTPException(status_code=503, ...)
```

The `/status` handler should use the same `getattr(request.app.state, "notebooks_store", None)`
pattern. If `store` is None (pre-lifespan), include `"notebook_count": null` in the
output rather than 503 — this matches the IETF `health+json` spirit of reporting degraded
rather than failing.

**uptime** — `resources.process_start_time_seconds` (float, UNIX epoch, line 311 in
`resources.py`): `process_start_time_seconds: float = field(default_factory=time.time)`.
This is also exposed as `PROCESS_START_TIME_GAUGE` (line 136 in `health.py`). Uptime =
`time.time() - resources.process_start_time_seconds`.

**disk** — Call `shutil.disk_usage(str(resources.config.data_dir))`. The config attribute
is `config.data_dir: Path = Path("var/arxmcp")` (line 294 of `config.py`). The existing
`refresh_disk_free_metric` in `health.py` (line 601) already does this:
`usage = shutil.disk_usage(str(data_dir))`. The warn threshold is
`DISK_PAUSE_THRESHOLD_BYTES: int = 10 * 1024**3` (10 GB, line 587). For the `/status`
check: `status: "warn"` if `free_bytes < 10 GB`, else `"pass"`.

**last-backup** — Read `var/arxmcp/ops/backup-status.json` via `resources.config.ops_dir /
"backup-status.json"` (pattern at health.py line 391). Schema confirmed from
`ops/cron/arxmcp-backup.sh`:
```json
{"backup_status": "ok|failed|...", "finished_at": "<ISO-8601>", "forget_status": "...", ...}
```
Note: the field name in the script is `backup_status` (not `status`). The `health.py`
sentinel reader checks `payload.get("status")` — **this is a CONFLICT**: the script writes
`backup_status` but `refresh_sentinel_metrics` reads `status`. The actual behavior is that
`BACKUP_STATUS_GAUGE` never fires from this file because the key doesn't match.

**FLAG: The backup-status.json field name mismatch.** `ops/cron/arxmcp-backup.sh` writes
`backup_status` but `server/health.py:407` reads `payload.get("status")`. These are
different keys. `BACKUP_LAST_SUCCESS_GAUGE` (reading `finished_at`) works correctly; the
`BACKUP_STATUS_GAUGE` (reading `status`) silently never fires. The `/status` endpoint
should read `payload.get("backup_status") or payload.get("status")` for resilience, and
document this in a comment. The implementer should file this as a separate bug rather than
silently fixing it (to preserve audit trail).

For the "last-backup staleness → warn" threshold: 25 hours is a reasonable threshold (the
daily cron runs at ~3am; >25h means it missed a day). If `finished_at` is absent or older
than 25h, report `status: "warn"`.

### CSP — `/status` XHR from htmx badge

`server/middleware.py:170-177`:
```python
CONTENT_SECURITY_POLICY_UI: bytes = (
    b"default-src 'self'; "
    b"script-src 'self' 'unsafe-inline'; "
    b"style-src 'self' 'unsafe-inline'; "
    b"img-src 'self' data:; "
    b"connect-src 'self'; "
    b"frame-ancestors 'none'"
)
```

`connect-src 'self'` is already present. An htmx `hx-get="/status"` from a page served at
`/ui/` makes a same-origin XHR to `/status` — this is allowed by `connect-src 'self'`.
**No CSP change required.** The existing CSP already covers the badge's XHR.

The CSP is applied to all `/ui/*` paths by `SecurityHeadersMiddleware` (line 762-786 in
`middleware.py`):
```python
path_b = scope.get("path", "").encode("latin-1", errors="replace")
is_ui_path = any(
    path_b == p or path_b.startswith(p + b"/")
    for p in _CSP_UI_PREFIXES  # b"/ui"
)
```

`/status` is NOT under `/ui/*` — it gets no CSP header (which is correct; it's a JSON
endpoint). htmx runs in the browser on pages served from `/ui/`, so the CSP that governs
the badge's behavior is the one on the `/ui/` response — which already has `connect-src 'self'`.

### `base.html` — where to insert the badge

`frontend/templates/base.html:55-61`:
```html
<footer>
  <small>
    Loopback only · same-origin only ·
    Destructive notebook wipe lives in <code>tools/notebook_purge.py</code> ·
    <a href="/healthz">/healthz</a> · <a href="/readyz">/readyz</a>
  </small>
</footer>
```

htmx 2.0.10 is already loaded (line 9: `<script src="/ui/static/htmx.min.js" defer>`).
The badge should go in `<footer>`, appended to the `<small>` block. The `hx-target` should
be a `<span id="status-badge">` that htmx swaps with the response text. The badge must use
`hx-swap="innerHTML"` and `hx-trigger="load, every 10s"`.

`/status` will return JSON (`application/json`). htmx by default inserts the raw response
body into the target. For a simple badge, the `/status` endpoint can return either:
- A plain JSON body (badge JavaScript reads it via `htmx:afterSettle`)
- OR `text/plain` human line for htmx direct insert

**Recommendation**: Return `application/health+json` for the `/status` endpoint. The badge
should use `hx-get="/status"` with a custom `htmx:afterSettle` handler (inline script,
already permitted by `script-src 'self' 'unsafe-inline'`) that parses the JSON and updates
the badge span text. Alternatively, add a separate `/status/badge` route returning
`text/html` fragment for direct htmx swap — this is simpler and avoids inline JS. Use the
`/status/badge` approach: it's one extra route but eliminates the JS dependency.

### Makefile — `make status` style

Existing targets use this pattern (lines 93-97 for `make up`):
```makefile
up:
	@$(PYTHON) -c "import sys; assert sys.version_info >= ..."
	$(PYTHON) -m server.main
```

The `make status` target should use `curl` (no Python needed, simpler):
```makefile
status:
	@curl -sf http://127.0.0.1:$(ARXMCP_BIND_PORT)/status \
	  | $(PYTHON) -c "import sys,json; d=json.load(sys.stdin); print(d['summary_line'])" \
	  || echo "DOWN: server not reachable at 127.0.0.1:$(ARXMCP_BIND_PORT)"
```

Or, since `DEFAULT_BIND_PORT = 7733` is in `config.py`, hardcode it in the Makefile:
`127.0.0.1:7733`. The `ARXMCP_BIND_PORT` env var is the override. Use `curl -sf` (silent +
fail on non-2xx). Add a `summary_line` field to the `/status` JSON body to make `make status`
easy to parse without complex jq-style logic.

### SecFetchSiteMiddleware and `/status` path

`SecFetchSiteMiddleware` exempts `/ui` paths to allow `Sec-Fetch-Site: same-origin`. The
badge at `/ui/*` does `hx-get="/status"` — this is a cross-path XHR (from `/ui/` to
`/status`). The browser will set `Sec-Fetch-Site: same-origin` (same origin, different path).
`/status` is NOT in the exempt_prefixes for SecFetchSiteMiddleware — **it will be rejected
with 403 for `Sec-Fetch-Site: same-origin`**.

**This is a FLAG / potential conflict.** The htmx badge at `/ui/` doing `hx-get="/status"`
sends `Sec-Fetch-Site: same-origin` (because both the page and the API are on `127.0.0.1:7733`).
The `SecFetchSiteMiddleware` only allows `same-origin` on exempt paths (currently `/ui`).
`/status` is NOT under `/ui`. **The badge will 403 unless `/status` is added to
`exempt_prefixes` OR the badge is served via `/ui/status`.**

**Resolution options:**
1. Route the badge XHR to `/ui/status` instead of `/status` (alias route under `/ui/api/`)
2. Add `/status` to `SecFetchSiteMiddleware` exempt_prefixes in `create_app` (widens the `same-origin` allowance to the status endpoint specifically)
3. Move `/status` under `/ui/` (e.g. `/ui/status`) — cleanest from a middleware perspective

**Recommendation**: Register `/status` as a standalone route (not under `/ui/`) AND add it to
`SecFetchSiteMiddleware`'s `exempt_prefixes` in `create_app`. This preserves the standalone
operability semantics (curl `/status` without UI machinery) while allowing same-origin htmx
fetches. The exemption is narrow (only `/status`, not `/status/*`).

---

## Prior decisions and lessons

- `notebook-ops-hardening-m3` shipped the docker-compose (commit `55e4e88`). m4 is the
  next hardening step and has no implementation commits yet (state: `research-running`).
- `corpus-integrity-observability-e2` (commit `b248b60`) wired `startup_chunk_count` and
  `resources.corpus_info.chunk_count` into the `/readyz` 200 body. The `/status` endpoint
  reuses these same values.
- The E14_S01 sentinel reader pattern in `health.py::refresh_sentinel_metrics` is the
  precedent for reading `backup-status.json` at a non-scrape path (the pattern can be
  reused directly for the `/status` handler's backup check).
- **CLAUDE.md §4.7**: `BaseHTTPMiddleware` is BANNED. The `/status` route is a plain
  FastAPI handler on the existing `health_router` — no new middleware needed.
- **Doc placement (CLAUDE.md §1)**: no new Markdown files go in `server/`. This brief and
  any milestone notes go in `.claude/`.
- **`assert` is banned** (CLAUDE.md §4.7). The existing `BodySizeCapMiddleware` at line 233
  (`assert start_event is not None`) is pre-existing debt — do not add more.

---

## External sources

The milestone references IETF `application/health+json`. The relevant spec is
[draft-inadarei-api-health-check](https://inadarei.github.io/rfc-healthcheck/) (RFC
candidate). Key fields: `status: "pass"|"warn"|"fail"`, `version`, `serviceId`,
`description`, `checks` (object keyed by component name). The `/status` endpoint should
use `Content-Type: application/health+json` per the draft.

MCP spec 2025-06-18: `/status` is NOT an MCP endpoint. It does not affect the tool surface,
`tools/list`, or BP1 hash.

Anthropic prompt caching docs: not relevant (no tool schema change).

---

## Recommendation

**Build `/status` in `server/health.py` on the existing `health_router`, returning
`application/health+json`.** Use `status: "pass"|"warn"|"fail"` mapping: warm+not-degraded
→ `pass`; warm+degraded → `warn`; not-warm or pre-startup → `fail`. Include `corpus_version`,
`notebook_count`, `uptime_seconds`, and per-component `checks` (embedder, lancedb, disk,
last_backup). Add a `summary_line` field (e.g. `"READY | embedder warm | corpus v7 | 3 notebooks"`)
for `make status`.

For the badge: add a thin `/ui/status-badge` route in `server/routes/ui.py` that calls the
internal status logic and returns a small HTML fragment (`<span class="badge-...">READY</span>`).
This eliminates the inline-JS requirement and htmx directly swaps it. The badge in
`base.html` does `hx-get="/ui/status-badge" hx-trigger="load, every 10s" hx-swap="outerHTML"`.

For the `SecFetchSiteMiddleware` problem: add `/status` to `exempt_prefixes` in
`create_app` AND add `/ui/status-badge` implicitly via the existing `/ui` exemption.

**`make status`** should `curl -sf http://127.0.0.1:7733/status` and extract `.summary_line`
via a one-liner Python parse (already available via `$(PYTHON)`).

**Critical implementation order**:
1. Add `/status` handler to `health.py`
2. Add `/status` to `_BYTE_CAP_EXEMPT_PREFIXES` and `SecFetchSiteMiddleware` exempt_prefixes
3. Add `/ui/status-badge` to `server/routes/ui.py`
4. Update `base.html` footer badge
5. Add `make status` to Makefile (Makefile changes trigger infra-safety critic)

---

## Open questions

1. **backup-status.json key mismatch**: The script writes `backup_status`; `health.py`
   reads `status`. The `/status` handler should silently handle both keys for now and
   document the mismatch as a separate bug. Should the implementer fix the script too or
   just note the discrepancy?  
   **Recommendation**: read both keys (`payload.get("status") or payload.get("backup_status")`)
   in the `/status` handler only. Do not touch the script — that is a separate concern.
   File an inline `# TODO: backup-status.json uses backup_status key not status` comment.

2. **`/ui/status-badge` vs `/status`**: The brief says `hx-get="/status"` in the badge.
   If the implementer follows the brief literally, they must add `/status` to the
   `SecFetchSiteMiddleware` exempt_prefixes. The `/ui/status-badge` alternative is cleaner
   but deviates from the brief's literal AC. Either approach is valid — the implementer
   should pick one and be consistent.

---

## External writes the implementation will require

None — this milestone is purely local (code + Makefile changes, no git push, no infra
mutation beyond the Makefile). The Makefile change will trigger the infra-safety critic
as noted in the brief.
