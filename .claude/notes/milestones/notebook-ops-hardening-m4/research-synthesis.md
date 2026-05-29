# Research Synthesis — notebook-ops-hardening-m4

**Milestone:** "Is it running + ready?" answerable in one action
**Mode:** standard (2× Sonnet, parallel)
**Sources:** research-brief-1.md (in-codebase), research-brief-2.md
(health+json spec + htmx/CSP + failure modes)

---

## TL;DR — what to build

1. **`GET /status`** in `server/health.py` (on the existing `health_router`) —
   an `application/health+json` body: top-level `status: pass|warn|fail` +
   `checks` keyed `<component>:<measurement>` (embedder, lancedb, corpus:version,
   notebooks:count, disk:utilization, backup:time, process:uptime). HTTP 200 for
   `pass`/`warn`, **503 for `fail`**.
2. **`GET /ui/status-badge`** in `server/routes/ui.py` — an HTML fragment
   `<span>` the htmx badge swaps in (htmx can't render JSON; and `/status` would
   403 via SecFetchSite for a browser XHR — see RESOLVED #1).
3. **`make status`** — `curl -sf --max-time 5 .../status | python3 -c '<parse>' ||
   echo DOWN` → prints `READY | corpus v7 | 3 notebooks`.
4. **Badge in `frontend/templates/base.html`** —
   `<span id="status-badge" hx-get="/ui/status-badge" hx-trigger="load, every 10s"
   hx-swap="outerHTML">…</span>` in the footer (htmx 2.0.10 already self-hosted).
5. **`/readyz` UNCHANGED** (still 503-on-degraded; only `/status` adopts `warn` 2xx).

A shared `compute_status(resources, store, ...)` helper backs BOTH `/status`
(JSON) and `/ui/status-badge` (HTML) — DRY. No MCP/BP1/tool-schema impact.
infra-safety critic WILL fire (Makefile change).

---

## In-codebase facts (verbatim, both briefs)

- **Routes:** `health_router` in `server/health.py` (`/healthz`, `/readyz`,
  `/metrics`), registered `app.include_router(health_router)` (main.py:584). Add
  `/status` here.
- **Readiness state:** `request.app.state.resources` (`Resources`); `resources.warm`
  (bool), `resources.degraded` (`DegradedState | None`),
  `resources.corpus_info.version` (corpus_version),
  `resources.process_start_time_seconds` (uptime base), `resources.config.data_dir`
  (`var/arxmcp`). `/readyz` returns 503 when `not warm` OR `degraded is not None`.
- **Notebook count:** `len(await store.list_notebooks())` where `store =
  getattr(request.app.state, "notebooks_store", None)`; no `count()` method, N is
  small. If store is None → report `null`/`warn`, do NOT 503.
- **Disk:** `shutil.disk_usage(str(data_dir))`; warn threshold
  `DISK_PAUSE_THRESHOLD_BYTES = 10 GB` (health.py:587). Existing
  `refresh_disk_free_metric` is the precedent.
- **Last-backup:** `ops_dir / "backup-status.json"` — has `finished_at` (ISO-8601)
  + `status`/`backup_status`. Staleness >25h → `warn`. (See RESOLVED #4 on the key.)
- **CSP (middleware.py:170-177):** `default-src 'self'; … connect-src 'self'; …` —
  **already permits the same-origin badge XHR; NO CSP change needed.** htmx is
  self-hosted (`/ui/static/htmx.min.js`), covered by `script-src 'self'`.
- **base.html footer (55-61):** has the `/healthz`·`/readyz` links — the badge
  goes here. htmx loaded at line 9.
- **Makefile:** `make up` style (lines 93-97); add `make status` (curl + python
  parse). Port = `ARXMCP_BIND_PORT` (default 7733).
- **Constraints:** `BaseHTTPMiddleware` BANNED (pure-ASGI only); `assert` banned
  for invariants (use `if … raise`); `/status` is a plain HTTP route → no
  `EXPECTED_TOOL_SCHEMA_SHA256` / BP1 impact.

---

## RESOLVED design questions

### #1 — Badge endpoint: `/ui/status-badge` HTML fragment (both briefs agree)

The brief's AC3 literally says `hx-get="/status"`. **That literal wording is
technically broken**, for TWO independent reasons both researchers found:
1. **htmx renders HTML, not JSON.** `hx-get` on a `health+json` endpoint dumps raw
   `{"status":"pass",…}` text into the DOM — not a badge.
2. **`SecFetchSiteMiddleware` 403s it.** A browser htmx XHR from a `/ui/` page to
   `/status` carries `Sec-Fetch-Site: same-origin`; the middleware exempts only
   `/ui` + `/ui/*` for same-origin, so `/status` (non-`/ui`) is rejected 403.

**Resolution:** the badge points at **`/ui/status-badge`** (HTML fragment, under
`/ui/` so SecFetchSite + CSP already allow it). `/status` stays the
machine-readable health+json endpoint for `make status` + monitors. Both backed
by one `compute_status` helper. **DEVIATION from AC3's literal `hx-get="/status"`
wording, recorded** — it faithfully realizes AC3's intent (a live polled
ready/degraded/down badge) while being the only form that actually works.

### #2 — health+json shape: spec-faithful, NO ad-hoc top-level fields (brief-2)

Per draft-inadarei-api-health-check (https://inadarei.github.io/rfc-healthcheck/):
top-level `status` MUST be `pass|warn|fail`; `checks` is keyed
`<component>:<measurement>`, each an array of `{componentType, observedValue,
observedUnit, status, time, output}`. **`corpus_version`/`notebook_count`/`uptime`
go INSIDE `checks` (`corpus:version`, `notebooks:count`, `process:uptime`), NOT as
ad-hoc top-level keys** (a content-type claiming `application/health+json` must not
invent top-level fields). **This overrides brief-1's `summary_line` top-level
suggestion** — `make status` computes the human line by parsing `checks` instead.
Content-Type: `application/health+json`.

### #3 — Status mapping + HTTP codes (both converge)

| server state | `/status` `status` | `/status` HTTP | `/readyz` (unchanged) |
|---|---|---|---|
| warm + healthy | `pass` | 200 | 200 |
| warm + degraded | `warn` | **200** | 503 |
| not warm / pre-startup | `fail` | 503 | 503 |

So `/status` differs from `/readyz` ONLY in the degraded case (warn 200 vs 503) —
exactly the brief. `make status` uses `curl -sf --max-time 5 … || echo DOWN` so a
503/unreachable becomes a clean "DOWN" line, not a stack trace.

### #4 — backup-status.json key (brief-1 flagged a possible bug)

brief-1 flagged that `arxmcp-backup.sh` writes `backup_status` while
`health.py::refresh_sentinel_metrics` reads `status`. **VERIFY at implementation:**
the m1 final sentinel writes BOTH `status` (FINAL_STATUS) and `backup_status`
(BACKUP_STATUS) — so `status` likely IS present and the gauge is fine. For
`/status`, read defensively: `finished_at` for staleness (>25h → warn) +
`payload.get("status") or payload.get("backup_status")`. If a real gauge bug is
confirmed, note it (do not silently widen scope; a follow-up, not part of m4).

### #5 — SecFetchSite for `make status` (curl) — VERIFY

The badge uses `/ui/status-badge` (browser path, exempt). `make status` uses
`curl` which sends NO `Sec-Fetch-Site` header. **VERIFY** the middleware allows
header-less (non-browser) requests on `/status` (typical: missing header =
trusted/non-browser → allowed). If header-less requests are rejected, add
`/status` to `SecFetchSiteMiddleware` exempt_prefixes. (Expected: no exempt change
needed; confirm with a test or a live curl.)

---

## Other settled decisions

- **`_BYTE_CAP_EXEMPT_PREFIXES`:** add `/status` for parity with `/healthz`/`/readyz`
  (body ~500B, under the 256KB cap anyway, but parity + no buffering). Cheap.
- **`/ui/status-badge` always returns 200** with the badge reflecting the state
  (even "DOWN") — it is a UI fragment, not a probe; the browser must always get a
  renderable badge, never a 503.
- **No session-cap concern:** `SessionCapMiddleware` only gates POST `/mcp`
  (middleware.py:1115); the 10s GET poll is unaffected.
- **Info-leak (08-security):** `/status` is loopback-only; expose corpus_version,
  counts, uptime, disk %, backup time — NOT internal paths or stack traces. The
  `output` field on a degraded check carries a SHORT reason (e.g.
  "fallback_version=N-1"), not a traceback.

## Failure modes (brief-2, condensed)

- /status depends on a down component → degrade to warn/fail, NEVER 500 (wrap the
  notebook-store/backup-file reads in try/except → that check goes `warn`).
- 10s poll log-noise → /status should be low-log (no per-request INFO spam).
- info-leak → expose only safe fields (above).
- `make status` fragile parse on a `warn`/`fail` body → parse defensively
  (`.get`, `next(...,'?')`), `|| echo DOWN`.
- CSP over-widening → NO CSP change needed; do not add `unsafe-*`.
- `warn` 2xx misread as healthy by a naive monitor → documented; the `status`
  field is the source of truth, not the HTTP code.

## Test plan

`tests/test_status_endpoint.py` (or extend `tests/test_health.py` — match the
existing health-test fixture for faking `app.state.resources`):
- **AC1:** warm + healthy → `/status` 200, `application/health+json`,
  `status=="pass"`, `checks` has `corpus:version` (observedValue == corpus_version),
  `notebooks:count`, embedder/lancedb pass.
- **AC4:** warm + degraded → `/status` 200 `warn` AND `/readyz` still 503
  (assert both — pins that /readyz is unchanged).
- not-warm → `/status` 503 `fail`.
- **`/ui/status-badge`** returns `text/html` with a `<span>` badge reflecting
  pass/warn/fail; always 200.
- **`make status`:** assert the Makefile target exists + a unit test of the parse
  one-liner against a sample pass/warn body (or a doc/grep test of the target).
- store-absent / backup-file-absent → `/status` does not 500 (degrades).

## Acceptance criteria → artifacts

| AC | Artifact |
|---|---|
| AC1 health+json with status=pass, corpus_version, notebook count, checks | `/status` handler + test |
| AC2 `make status` human summary parsed from /status | Makefile target + parse test |
| AC3 base.html htmx badge; CSP permits | badge → `/ui/status-badge` (deviation #1); CSP already permits |
| AC4 /readyz 503-on-degraded unchanged | no /readyz edit; test asserts both /status warn 200 + /readyz 503 |

## Deviations from the brief (recorded)

1. **Badge `hx-get` target** = `/ui/status-badge` (HTML fragment), NOT the literal
   `hx-get="/status"` — htmx can't render JSON + SecFetchSite 403 (RESOLVED #1).
   Faithful to AC3's intent.
2. **No `summary_line` top-level field** on `/status` (spec-faithful health+json;
   RESOLVED #2). `make status` computes the line from `checks`.

## Open questions (carried to implementation, all with recommendations)

- **#4** verify backup-status.json `status` key presence; read defensively.
- **#5** verify SecFetchSite allows header-less curl on `/status`; add to exempt
  only if needed.
- **cold-start = fail/503** (resolved #3); `make status` handles via `|| echo DOWN`.
- No blockers.

## External writes the implementation will require

**None.** Purely local: `server/health.py`, `server/routes/ui.py`,
`server/main.py`, `frontend/templates/base.html` (+ maybe a small CSS class),
`Makefile`, tests. No git push (Phase 4, per-event), no infra mutation, no API.

## Orchestrator synthesis note

The briefs CONVERGED on the load-bearing finding (badge must be a `/ui/`-prefixed
HTML fragment, not `hx-get="/status"`) — independently derived from two angles
(htmx-can't-render-JSON + SecFetchSite-403). The one genuine divergence —
brief-1's `summary_line` top-level field vs brief-2's spec-faithful checks-only
shape — is resolved in favor of brief-2 (an `application/health+json` body must
not invent top-level keys). brief-1's `backup_status` key flag is carried as a
verify-and-read-defensively item, not a scope-widening fix.
