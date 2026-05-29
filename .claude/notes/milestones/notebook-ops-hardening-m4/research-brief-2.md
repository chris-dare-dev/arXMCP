# Research Brief — notebook-ops-hardening-m4

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T14:45:00Z

## In-codebase context

### Health + readiness surface (load-bearing)

`server/health.py` currently provides three routes: `/healthz` (liveness, always 200),
`/readyz` (readiness, 200 when warm, 503 on degraded or not-warm), and `/metrics`
(Prometheus). The `/readyz` 200 body currently has:
```json
{"status": "ready", "chunk_count": <int|null>, "marker_chunk_count": <int>, "warm": {...}}
```
The `/readyz` 503-degraded body has `{"status": "degraded", "reason": ..., "fallback_version": ..., ...}`.
**AC4 requires this behavior is entirely unchanged.** `/status` is a NEW route, additive only.

### Middleware stack (pure-ASGI constraint — CLAUDE.md §4.7)

From `server/middleware.py`: `BaseHTTPMiddleware` is project-banned (E06_S01 F1 — silently
no-ops SSE response interception). All middleware must be pure-ASGI. `/status` is a plain
HTTP GET route registered on the FastAPI `router`; it does NOT go through
`SessionCapMiddleware` (line 1115: `if method != "POST" or not path.startswith("/mcp")`
— `/status` is GET, not POST, and is not on `/mcp`). **No session-cap concern for the
badge's 10s polling.**

### CSP for `/ui/*` (load-bearing)

From `server/middleware.py:170-177`, `CONTENT_SECURITY_POLICY_UI`:
```
default-src 'self';
script-src 'self' 'unsafe-inline';
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
connect-src 'self';
frame-ancestors 'none'
```
`connect-src 'self'` is ALREADY present. An `hx-get="/status"` XHR from `/ui/` to
`/status` is a same-origin request — **no CSP delta needed**. The current CSP already
permits it.

### MCP tool surface — NOT touched

`/status` is a plain HTTP route, not an MCP tool. `ALL_TOOLS` in `server/tools.py` is
untouched. **`EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning for this milestone.**
This is a zero-BP1-impact route.

### htmx vendored, self-hosted

`frontend/templates/base.html` line 9: `<script src="/ui/static/htmx.min.js" defer>`.
htmx is vendored at `frontend/static/htmx.min.js` — NOT loaded from a CDN. `script-src
'self'` in the CSP covers it. No CDN CSP change needed.

### SecFetchSiteMiddleware (UI path exemption)

`server/middleware.py:559-582`: `/ui/*` paths are in `exempt_prefixes`, which relaxes
`Sec-Fetch-Site` from `{none}` to `{none, same-origin}`. The badge's `hx-get="/status"`
will carry `Sec-Fetch-Site: same-origin`. Since `/status` is NOT under `/ui/`, this
middleware will evaluate `/status` as a non-exempt path — it only allows `none` there.

**FLAG: CONFLICT between brief and middleware.** The brief says `hx-get="/status"` (on the
path `/status`). The existing `SecFetchSiteMiddleware` exempts only paths matching
`/ui` or `/ui/*`. A browser-originated htmx XHR to `/status` carries
`Sec-Fetch-Site: same-origin`, which the middleware rejects with 403 on a non-exempt path.
The implementer must either: (a) register `/status` as an exempt prefix in
`SecFetchSiteMiddleware`, OR (b) make the badge hit `/ui/status` (a UI-prefixed route
that returns either JSON or an HTML fragment). Option (b) avoids the Sec-Fetch-Site issue
naturally and is consistent with the existing pattern of UI-API routes living under `/ui/`.
**Recommendation: use `/ui/status` for the badge endpoint** (see Recommendation section).

### NotebooksStore — notebook count

`server/notebooks_store.py:273`: `async def list_notebooks(self) -> list[dict[str, str]]`.
No `count_notebooks()` method exists. For `/status`, use `len(await store.list_notebooks())`
— O(N) but N is small (single-user workstation, ≤ tens of notebooks). Alternatively, a
COUNT query can be added to the store, but the brief does not require it.

### `resources.degraded` — warm/degraded state

`server/resources.py`: `Resources.degraded` is `None` (pass) or a `DegradedState` object
(reason + fallback_version). `Resources.warm` is the bool gate. These map cleanly to
health+json `status: pass | warn | fail`.

### Backup status sentinel

`server/health.py:63`: `_BACKUP_STATUS_NAME = "backup-status.json"` at `ops_dir`. The
file has `{"status": "ok"|"failed"|"running", "finished_at": <iso8601>}`. The
`finished_at` timestamp is the "last-backup" check value for `/status`.

### Disk free

`server/health.py:601-664`: `refresh_disk_free_metric(data_dir)` already reads
`shutil.disk_usage`. The same logic can drive the disk check entry in `/status`.

### Process uptime

`server/health.py:135`: `PROCESS_START_TIME_GAUGE` stores the UNIX epoch at startup.
`resources.process_start_time_seconds` is the attribute. Uptime = `time.time() - resources.process_start_time_seconds`.

## Prior decisions and lessons

- From git log: notebook-ops-hardening-m3 (complete, commit `55e4e88`) shipped
  `infra/docker-compose.yml`. m4 is the next in sequence.
- corpus-integrity-observability-e2 (complete, commit `4706ecf`) wired JSON-structured
  logging and the `/readyz` chunk-count body. `/status` must not regress those.
- `SecFetchSiteMiddleware` path-prefix exemption pattern (m7 rect F1) is the authoritative
  reference: prefix must be `path == p OR path.startswith(p + "/")`, NOT substring.
  This trap recurs — always verify with the existing pattern.
- From CLAUDE.md §4.7: `assert` banned for invariants; use `if ... raise RuntimeError`.
- From CLAUDE.md §8 gotcha 1: `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` must
  not be removed.

## External sources

### IETF draft-inadarei-api-health-check (application/health+json)

Source: https://inadarei.github.io/rfc-healthcheck/ (the de-facto spec)

Top-level fields: `status` (REQUIRED, `"pass"|"fail"|"warn"`), `version`, `releaseId`,
`notes`, `output`, `serviceId`, `description`, `checks`, `links`.

Per the spec: "For 'pass' status, HTTP response code in the 2xx-3xx range MUST be used.
For 'fail' status, HTTP response code in the 4xx-5xx range MUST be used." For 'warn':
2xx-3xx range with additional information. **This means: `/status` returns 200 for both
`pass` and `warn` (degraded-but-serving). 503 is reserved for `fail` (completely down).
This matches the brief exactly.**

`checks` keys follow `{componentName}:{measurementName}` pattern. Pre-defined measurement
names include: `utilization`, `responseTime`, `connections`, `uptime`. Each key maps to
an array of check objects with: `componentId`, `componentType` (`"component"`,
`"datastore"`, `"system"`), `observedValue`, `observedUnit`, `status`, `affectedEndpoints`,
`time`, `output`, `links`.

**Fields arXMCP should populate vs omit:**
- Populate: `status`, `checks`, `description` (optional but useful)
- Omit: `version`, `releaseId`, `notes`, `output`, `serviceId`, `links` (not needed for
  loopback-only single-operator use)
- `corpus_version`, `notebook_count`, `uptime_seconds` belong inside `checks` entries,
  NOT as ad-hoc top-level fields (spec does not define them at top level; anything outside
  spec-defined keys is a spec violation for a content-type claiming `application/health+json`)

### htmx response model

Source: https://htmx.org/docs/

`hx-trigger="load, every 10s"` fires on element load and every 10 seconds thereafter.
**htmx expects HTML responses, not JSON.** The docs state: "when you are using htmx, on
the server side you typically respond with HTML, not JSON." If an endpoint returns JSON,
htmx renders the raw JSON bytes as text in the DOM. **The brief's `hx-get="/status"` (which
returns `application/health+json`) will NOT produce a badge — it will render raw JSON
as text.** This is a design gap in the brief that must be resolved.

## Recommendation

**Implement a separate HTML-fragment endpoint `/ui/status-badge` for the htmx badge.**
Do not point the badge at the JSON `/status` endpoint directly.

Rationale:
1. htmx does NOT render JSON as HTML — `hx-get="/status"` on a health+json endpoint
   renders raw `{"status":"pass",...}` text in the DOM, not a badge.
2. `/status` is NOT under `/ui/*`, so `SecFetchSiteMiddleware` will 403-reject the
   same-origin XHR from a browser page at `http://127.0.0.1:7733/ui/`.
3. Both issues resolve cleanly with a `/ui/status-badge` route that reads the same
   underlying state (resources.degraded, Resources.warm, etc.) and returns a small
   HTML fragment: `<span class="badge badge--pass">READY · corpus v7 · 3 notebooks</span>`.

**Concrete recommended approach:**

- `GET /status` — full `application/health+json` response (JSON, `status: pass|warn|fail`,
  200 for pass/warn, 503 for fail). Used by `make status` and external monitoring.
- `GET /ui/status-badge` — HTML fragment endpoint returning a `<span>` with badge classes.
  Reads the same `Resources` state. Lives under `/ui/*` so `SecFetchSiteMiddleware` allows
  same-origin XHR and CSP `connect-src 'self'` covers it.
- `base.html` badge: `<span id="status-badge" hx-get="/ui/status-badge" hx-trigger="load, every 10s" hx-target="#status-badge" hx-swap="outerHTML">Loading...</span>`

**No CSP changes needed** — `connect-src 'self'` already covers same-origin XHR under `/ui/`.

**Recommended exact JSON body for `/status`:**

Pass case (200):
```json
{
  "status": "pass",
  "description": "arXMCP MCP server",
  "checks": {
    "embedder:status": [{"componentType": "component", "status": "pass", "time": "<iso8601>"}],
    "lancedb:status": [{"componentType": "datastore", "status": "pass", "time": "<iso8601>"}],
    "corpus:version": [{"componentType": "datastore", "observedValue": 7, "observedUnit": "version", "status": "pass", "time": "<iso8601>"}],
    "notebooks:count": [{"componentType": "datastore", "observedValue": 3, "observedUnit": "notebooks", "status": "pass", "time": "<iso8601>"}],
    "disk:utilization": [{"componentType": "system", "observedValue": 42.1, "observedUnit": "percent", "status": "pass", "time": "<iso8601>"}],
    "backup:time": [{"componentType": "system", "observedValue": "<iso8601-of-last-backup>", "status": "pass", "time": "<iso8601>"}],
    "process:uptime": [{"componentType": "system", "observedValue": 3600, "observedUnit": "s", "status": "pass", "time": "<iso8601>"}]
  }
}
```

Warn case (200, degraded):
```json
{
  "status": "warn",
  "output": "LanceDB fallback to corpus version N-1 (corpus_corruption)",
  "checks": {
    "lancedb:status": [{"componentType": "datastore", "status": "warn", "output": "fallback_version=N-1", "time": "<iso8601>"}],
    ...
  }
}
```

Fail case (503, embedder not warm):
```json
{
  "status": "fail",
  "output": "embedder not warm",
  "checks": {
    "embedder:status": [{"componentType": "component", "status": "fail", "time": "<iso8601>"}],
    ...
  }
}
```

**`make status` implementation:** Use `python -c` to parse JSON from `curl`:
```makefile
status:
	@curl -sf http://127.0.0.1:7733/status | python3 -c \
	  "import sys,json; d=json.load(sys.stdin); \
	   cv=next((c['observedValue'] for c in d.get('checks',{}).get('corpus:version',[{}])), '?'); \
	   nb=next((c['observedValue'] for c in d.get('checks',{}).get('notebooks:count',[{}])), '?'); \
	   print(f\"{d['status'].upper()} | corpus v{cv} | {nb} notebooks\")"
```
This is robust to `warn` bodies and the `fail` state where some checks may be absent.

## Open questions

**OQ-1 (must resolve before coding): `/status` fail semantics on partial warm.**
When the server is alive but embedder is still loading (not yet warm), should `/status`
return `fail` (503) or `warn` (200)? The brief says "server warm → pass"; the logical
counterpart is "not warm → fail". But the `make status` target must not get a 503 and
fail the `curl -sf`. Recommend: use `fail` + 503 when not warm (consistent with `/readyz`
503-before-warm); `make status` should use `curl -sf --max-time 5 || echo "DOWN"` to
handle non-2xx gracefully.

**OQ-2 (implementation choice): notebook count — `list_notebooks()` vs new `count()` method.**
`list_notebooks()` returns all notebook dicts; `len(result)` is O(N). For a
single-operator workstation with ≤ tens of notebooks this is fine. No new store method
needed unless N is expected to grow large.

## External writes the implementation will require

None — this milestone is purely local.
