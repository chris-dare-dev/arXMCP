# Research Brief — ui-badge-disambiguate

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-30T23:55:00Z

## In-codebase context

### Design notes that apply

- `06-mcp-server-design.md` §"Browser UI surface": `/ui/status-badge` is explicitly
  documented as a loopback-only htmx endpoint that is NOT part of the MCP tool surface.
  "Lives under `/ui/` (NOT `/status`) on purpose: htmx renders HTML not JSON, and a
  browser XHR to the non-`/ui` `/status` would be 403'd by `SecFetchSiteMiddleware`
  (which exempts only `/ui`). **Always returns 200** — the badge must render the state
  (even 'DOWN') in the browser; it is a UI fragment, not a probe."

- `06-mcp-server-design.md` §"Security posture": "Jinja2 autoescape — the environment
  is constructed EXPLICITLY with `autoescape=select_autoescape(...)`. Zero `| safe`
  filters in any template (load-bearing — it is the stored-XSS guard for
  operator-authored fields like `display_name`)."

- `07-multi-agent-caching.md`: No MCP tool surface is touched; BP1/BP2 hashes are
  unaffected. `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning is NOT needed.

### Current `ui_status_badge` body (verbatim, `server/routes/ui.py` lines 162–193)

```python
async def ui_status_badge(request: Request) -> HTMLResponse:
    import html as _html  # noqa: PLC0415
    from server.health import compute_health_status  # noqa: PLC0415

    resources = getattr(request.app.state, "resources", None)
    store = getattr(request.app.state, "notebooks_store", None)
    report = await compute_health_status(resources, store)
    status = str(report["status"])  # pass | warn | fail
    summary = str(report["summary"])
    css = {"pass": "ok", "warn": "warn", "fail": "down"}.get(status, "down")
    safe = _html.escape(summary)
    fragment = (
        f'<span id="status-badge" class="status-badge status-badge--{css}" '
        f'hx-get="/ui/status-badge" hx-trigger="every 10s" '
        f'hx-swap="outerHTML" title="{safe}">{safe}</span>'
    )
    return HTMLResponse(content=fragment)
```

**Current behavior:** CSS class is purely driven by `report["status"]` (pass/warn/fail).
Both retrieval-degraded and ops-warn paths set `status="warn"` in
`compute_health_status`, so both get `status-badge--warn`. The `summary` string is
also uniformly `"DEGRADED | corpus vN | M notebooks"` for any warn.

### `compute_health_status` label logic (verbatim, `server/health.py` lines 457–469)

```python
any_warn = degraded or disk_warn or backup_warn or nb_status == "warn"
status = "warn" if any_warn else "pass"
label = {"pass": "READY", "warn": "DEGRADED"}[status]
nb_text = "?" if nb_count is None else nb_count
summary = (
    f"{label} | corpus v{resources.corpus_info.version} | "
    f"{nb_text} notebooks" + (" | degraded" if degraded else "")
)
return {
    "status": status,
    "http_code": 200,
    "checks": checks,
    "summary": summary,
}
```

The `summary` is pre-rendered in `compute_health_status` and consumed verbatim by
`ui_status_badge`. The check values themselves (`checks["backup:time"]`,
`checks["lancedb:status"]`, etc.) are available in `report["checks"]`.

### Check key taxonomy from `compute_health_status`

Retrieval checks (non-pass = ACT):
- `embedder:status`
- `lancedb:status`
- `corpus:version` (always pass in warm path; holds version only)
- `notebooks:count` (warn when store absent or throws)

Ops checks (non-pass = informational):
- `backup:time`
- `disk:utilization`
- `process:uptime` (always pass in current code)

**Note:** `corpus:version` is set to `status: "pass"` unconditionally in the warm path.
The retrieval-degraded signal comes from `lancedb:status` (which gets `"warn"` when
`resources.degraded is not None`), NOT from `corpus:version`. The milestone brief
includes `corpus:version` in the retrieval set — this is valid as a forward-compat
guard but today it never fires as a warn in the warm path.

### CSS classes (verbatim, `frontend/static/app.css` lines 123–125)

```css
.status-badge--ok   { background: #e6f4ea; color: #1a7f37; border-color: #1a7f37; }
.status-badge--warn { background: #fdf3e2; color: #8a5a00; border-color: #8a5a00; }
.status-badge--down { background: var(--error-bg); color: var(--danger); border-color: var(--danger); }
```

`--warn` (amber) exists. `--ops-warn` does NOT exist. The milestone brief says
"possibly add `--ops-warn` variant for clarity" — this is the key open question.

### Existing badge tests (`tests/test_status_endpoint.py`, class `TestStatusBadge`)

```python
class TestStatusBadge:
    def test_badge_returns_html_fragment_200(self, tmp_path):
        # warm+healthy → status-badge--ok
        assert "status-badge--ok" in r.text
        assert 'hx-get="/ui/status-badge"' in r.text
        assert 'hx-trigger="every 10s"' in r.text

    def test_badge_down_class_when_not_warm(self, tmp_path):
        # not warm → status-badge--down
        assert "status-badge--down" in r.text
```

**There is NO existing test for the warn/degraded badge class.** The `TestStatusLineParser`
tests `format_status_line` which asserts `startswith("DEGRADED")` for any warn, but
that is in `tools/status_line.py` — separate from the badge.

The actual badge test file listed in state.json is `tests/test_status_endpoint.py`
(not `tests/test_routes_ui.py` — the milestone brief named the wrong file). The
tests that need adding are a third case in `TestStatusBadge`: warm but ops-only-warn
should show `--warn` (or `--ops-warn`) with label "WARN", not "DEGRADED".

## Prior decisions and lessons

**Recent git log (last 20 commits):**
- `ca2c274` — finalize verification-feedback-m4 (lean_verify progress notifications)
- `bd65584` — finalize notebook-surface-expansion-m7 (notebook restore CLI)
- Previous milestones: notebook-surface-expansion-m3 through m7, corpus-integrity-observability series

**notebook-ops-hardening-m4 (the badge's origin):** The badge was introduced in
`notebook-ops-hardening-m4` (complete, commit `67864da`). Key prior decisions from
that milestone's state.json: external_writes_required = [] (purely local). The badge
endpoint lives at `/ui/status-badge`, polls every 10s, always returns 200.

**From MEMORY.md (notebook-ops-hardening-m4):**
"SecFetchSiteMiddleware blocks cross-path htmx XHR. htmx XHRs from `/ui/*` pages to
paths NOT under `/ui/` carry `Sec-Fetch-Site: same-origin` and get 403'd. The badge
endpoint MUST stay under `/ui/`." This constraint is satisfied; no change needed.

**`format_status_line` in `tools/status_line.py`:** This is the `make status` CLI tool.
It maps `warn` → `"DEGRADED"` unconditionally. The milestone brief asks only for the
badge disambiguation, not the CLI tool. However, for consistency, the implementer
should consider whether `format_status_line` also needs updating — the brief's AC2
says "badge label is 'WARN'" but the CLI's `_LABELS = {"warn": "DEGRADED"}` would
still say "DEGRADED". This is a potential scope question.

**No prior milestone has touched badge label disambiguation.** This is a new concern
born from the operational experience described in the brief (restic not-yet-run
causing misleading DEGRADED on an otherwise healthy system).

## External sources

This milestone is a localhost-only HTML/CSS/Python tweak. No external APIs involved.

**MCP spec check:** The `/ui/` route prefix is not part of the MCP protocol surface.
The MCP spec (`modelcontextprotocol.io/specification/2025-06-18`) governs `/mcp`
transport, `tools/list`, `resources/list` etc. The `/ui/status-badge` endpoint is a
plain FastAPI HTML route, not an MCP method. No spec change needed; `EXPECTED_TOOL_SCHEMA_SHA256` is unchanged.

**Internal /status shape documentation:** Defined in `server/health.py` docstring
(lines 304–315) and `06-mcp-server-design.md` §"Health and readiness". The check keys
are not separately documented but are canonical in `compute_health_status`.

## Recommendation

**Implement the disambiguation entirely inside `ui_status_badge` in
`server/routes/ui.py` using a small inline helper. Do NOT touch `compute_health_status`
or `tools/status_line.py`.**

Concrete shape:

```python
_RETRIEVAL_CHECKS = frozenset({
    "embedder:status", "lancedb:status", "corpus:version", "notebooks:count"
})

def _badge_classify(report: dict) -> tuple[str, str]:
    """Returns (label, css_modifier) for the badge span.

    - fail → ("DOWN", "down")
    - warn with any retrieval check non-pass → ("DEGRADED", "warn")
    - warn with only ops checks non-pass → ("WARN", "warn")
    - pass → ("READY", "ok")
    """
    status = str(report.get("status", "fail"))
    if status == "fail":
        return ("DOWN", "down")
    if status == "pass":
        return ("READY", "ok")
    # status == "warn": check whether any retrieval check is non-pass
    checks = report.get("checks") or {}
    for key in _RETRIEVAL_CHECKS:
        entries = checks.get(key) or []
        if any(e.get("status") not in ("pass", None) for e in entries if isinstance(e, dict)):
            return ("DEGRADED", "warn")
    return ("WARN", "warn")
```

Then in `ui_status_badge`, replace:
```python
css = {"pass": "ok", "warn": "warn", "fail": "down"}.get(status, "down")
safe = _html.escape(summary)
```

with:
```python
label, css = _badge_classify(report)
# Rebuild summary with correct label (compute_health_status always says DEGRADED)
nb_text = report.get("summary", "").split("|")[2].strip() if "|" in report.get("summary","") else "?"
safe = _html.escape(f"{label} | {report.get('summary','').split('|',1)[1].lstrip()}" if "|" in report.get("summary","") else label)
```

Actually cleaner: don't re-parse the summary string. Reconstruct the display text
from the checks dict directly, parallel to what `compute_health_status` does, or
just replace the leading label:

```python
label, css = _badge_classify(report)
raw_summary = str(report.get("summary", ""))
# Replace the leading READY/DEGRADED/DOWN token with our disambiguated label
display = label + raw_summary[raw_summary.find("|"):] if "|" in raw_summary else label
safe = _html.escape(display)
```

**On `--ops-warn` CSS variant:** Reuse the existing `--warn` class for both DEGRADED
and WARN badge states. Adding `--ops-warn` is unnecessary visual complexity for a
minimal operator console, and the amber `--warn` already visually distinguishes from
`--ok` (green) and `--down` (red). The label text ("WARN" vs "DEGRADED") carries the
semantic distinction. This avoids a new CSS class that the tests would also need to
cover.

**Do NOT touch `tools/status_line.py`**: The `make status` CLI operates on the raw
`/status` JSON body where `status: "warn"` is correct for both cases. The CLI's
`"DEGRADED"` label is accurate for a terminal operator running `make status` who needs
to investigate. The disambiguation is specifically for the browser badge where the
visual context is limited.

**Placement:** `_RETRIEVAL_CHECKS` and `_badge_classify` as module-level in
`server/routes/ui.py`, not extracted to a separate module. The logic is 10 lines and
the file is the only consumer.

## Open questions

1. **`corpus:version` in the retrieval check set**: `corpus:version` always has
   `status: "pass"` in the current warm path — it carries version metadata, not a
   health signal. Including it in `_RETRIEVAL_CHECKS` is forward-compat (safe) but
   never fires today. Implementer should include it per the brief's AC1 for robustness.

2. **`format_status_line` consistency**: The brief's AC2 says only the badge should say
   "WARN", not "DEGRADED". The `make status` CLI (`tools/status_line.py`) still maps
   `warn → "DEGRADED"`. This is acceptable per the brief's scope, but the implementer
   should confirm Chris does not want the CLI updated too. My recommendation: leave
   the CLI as-is (its "DEGRADED" is accurate for terminal context).

3. **Test file name**: The brief says "tests/test_routes_ui.py" but that file does not
   exist. The badge tests live in `tests/test_status_endpoint.py` (class `TestStatusBadge`).
   Implementer must add the ops-only-warn test case there, not create a new file.

4. **`notebooks:count` warn classification**: When the store is absent (`store=None`),
   `nb_status = "warn"` → `any_warn = True` → top-level `status = "warn"`. This is
   a retrieval-relevant warn (can't count notebooks = can't confirm readiness), so
   treating it as DEGRADED (not just WARN) is correct. The `_badge_classify` logic
   covers this via `_RETRIEVAL_CHECKS`.

## External writes the implementation will require

None — this milestone is purely local. Changes are confined to:
- `server/routes/ui.py` (badge logic)
- `frontend/static/app.css` (no change needed if reusing `--warn`)
- `tests/test_status_endpoint.py` (new test case in `TestStatusBadge`)

No git push, no PR, no ticket, no infra mutation, no third-party API call.
