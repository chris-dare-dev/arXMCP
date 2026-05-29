# Implementation Summary — notebook-ops-hardening-m4

**One-liner:** "Is it running + ready?" is now answerable in one action — a
`GET /status` IETF `application/health+json` endpoint, a `make status` human
one-liner, and a live htmx-polled badge in the UI footer — without touching
`/readyz`'s 503-on-degraded probe semantics.

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline — surgical, tightly-coupled surfaces sharing one
`compute_health_status` helper, no clean parallel boundary.

---

## What landed

### `server/health.py` — `compute_health_status` + `GET /status`
- New `compute_health_status(resources, store, *, now=None)` — the single
  snapshot backing BOTH `/status` and `/ui/status-badge`. Returns
  `{status, http_code, checks, summary}`. Maps: **not-warm → `fail`/503**
  (mirrors `/readyz`), **warm+degraded/disk-low/backup-stale → `warn`/200**,
  **warm+healthy → `pass`/200**. Every probe degrades to `warn` rather than
  raising — a status endpoint never 500s. `now` injectable for tests.
- `GET /status` returns `application/health+json` (200 for pass/warn, 503 for
  fail) with spec-faithful `checks` keyed `<component>:<measurement>`
  (embedder, lancedb, corpus:version, notebooks:count, disk:utilization,
  backup:time, process:uptime). No ad-hoc top-level fields.
- `/readyz` is UNCHANGED (AC4).

### `server/routes/ui.py` — `GET /ui/status-badge`
HTML-fragment endpoint the badge swaps in (htmx renders HTML not JSON; and a
browser XHR to the non-`/ui` `/status` would 403 via `SecFetchSiteMiddleware`).
Always 200 (a UI fragment, not a probe); re-emits its own `hx-get`/`hx-trigger`
so the swapped element keeps polling. Reads the same `compute_health_status`.

### `frontend/templates/base.html` + `frontend/static/app.css`
Footer badge `<span id="status-badge" hx-get="/ui/status-badge"
hx-trigger="load, every 10s" hx-swap="outerHTML">` + `.status-badge--ok/warn/down`
classes. **No CSP change** — `connect-src 'self'` already covers the same-origin
`/ui/` XHR (verified in the synthesis).

### `make status` + `tools/status_line.py`
`make status` curls `/status` and pipes to `tools/status_line.py`, printing
`READY | corpus v7 | 3 notebooks` (or `DEGRADED`/`DOWN`). A 503/non-2xx/unreachable
falls through to a single clean `DOWN:` line (`curl -sf … || echo`). The parser is
a small testable script (robust to `warn`/`fail`/missing-checks bodies), not a
fragile in-Makefile one-liner. `ARXMCP_BIND_PORT ?= 7733` added.

### `server/main.py`
`/status` added to `_BYTE_CAP_EXEMPT_PREFIXES` (parity with the other health
probes; tiny body). No SecFetchSite exempt needed (curl sends no Sec-Fetch-Site
= absent = allowed; the badge uses the `/ui`-exempt `/ui/status-badge`).

---

## Acceptance criteria status

- [x] **AC1** — `GET /status` → health+json with `status:"pass"`,
  `corpus:version`, `notebooks:count`, per-component checks. (`test_status_pass_*`)
- [x] **AC2** — `make status` prints a human summary parsed from `/status`.
  (`tools/status_line.py` + `TestStatusLineParser` + `TestMakefileTarget`)
- [x] **AC3** — `base.html` renders a polled badge; CSP permits it. **Deviation:**
  badge `hx-get="/ui/status-badge"` (HTML fragment) NOT the literal
  `hx-get="/status"` (JSON) — htmx can't render JSON + `/status` would 403 via
  SecFetchSite. Faithful to AC3's intent. (`TestStatusBadge`)
- [x] **AC4** — `/readyz` 503-on-degraded unchanged; only `/status` adopts
  `warn` 2xx. (`test_status_degraded_warn_200_AND_readyz_still_503` asserts both)

## Deviations from the brief (recorded)

1. **Badge endpoint** `/ui/status-badge` (HTML), not the literal `hx-get="/status"`
   — the literal form is doubly broken (htmx-renders-HTML-not-JSON + SecFetchSite
   403). Both researchers independently concluded this.
2. **Spec-faithful health+json** — no `summary_line` top-level field; `make status`
   computes the line from `checks`.
3. **Extra warn signals** beyond the brief's degraded case: disk-low and
   backup-stale/absent also flip `/status` to `warn` (operability — the whole
   point of the milestone). Documented in the checks.

## Notes / verifies

- `backup-status.json`: `/status` reads `finished_at` for recency (>25h or
  absent → warn), independent of the `status`/`backup_status` string enum (which
  lives in `/metrics`). Not a scope-widening fix of the gauge.
- Live `make status` smoke (no server) → clean `DOWN:` line.

## Test surface

New: `tests/test_status_endpoint.py` (17 tests), `tools/status_line.py`. Changed:
`server/health.py`, `server/routes/ui.py`, `server/main.py`,
`frontend/templates/base.html`, `frontend/static/app.css`, `Makefile`.

## External writes required

**None.** Purely local. `git push` is per-event authorized at finalize.
