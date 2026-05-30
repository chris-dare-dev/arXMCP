# Research Brief — ui-badge-disambiguate

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-30T23:50:00Z

---

## In-codebase context

### Empirical /status report shape (`server/health.py::compute_health_status`)

The `checks` dict is built in `compute_health_status` (line ~295). Every value is a
**list** containing exactly one dict (IETF `application/health+json` per-component array
convention). The full set of checks and their possible status values, as found verbatim
in the source:

**Retrieval-side checks (failure means retrieval is impaired):**

- `embedder:status` — always `"pass"` on the warm path (line 346–347). No `"warn"` path
  exists yet; `"fail"` only fires on the pre-startup `fail` path (line 323).
- `lancedb:status` — `"pass"` normally; **`"warn"`** when `resources.degraded is not None`
  (line 352–354, verbatim: `lancedb_check["status"] = "warn"` + `output = f"fallback_version=..."`).
- `corpus:version` — always `"pass"` (line 359–363). Has `observedValue` (version int),
  `observedUnit = "version"`. No `"warn"` or `"fail"` path exists today.
- `notebooks:count` — `"pass"` normally; **`"warn"`** when store is absent (line 383–384) OR
  when `store.list_notebooks()` raises (line 382).

**Ops-side checks (failure means operational concern, retrieval still works):**

- `disk:utilization` — `"pass"` normally; **`"warn"`** when `usage.free < DISK_PAUSE_THRESHOLD_BYTES`
  (10 GB) (line 397) or when `shutil.disk_usage()` raises OSError (line 409).
- `backup:time` — `"pass"` normally; **`"warn"`** when no backup-status.json, when
  `finished_at` is absent/empty, when age > `_BACKUP_STALE_SECONDS` (25h), or when the
  file is unreadable (lines 430–448).
- `process:uptime` — **always `"pass"`** (line 452–455). The uptime check never flips to
  `"warn"` or `"fail"` in the current implementation; it only carries an `observedValue`.

**Brief-vs-codebase conflict check:**
- The brief says the milestone fixes "lines 162-195". In the current HEAD, `ui_status_badge`
  occupies **lines 159-193** in `server/routes/ui.py`. The function boundaries are correct;
  only the line numbers shifted. No functional conflict.
- The milestone brief says the test file is `tests/test_routes_ui.py`. **The badge tests
  actually live in `tests/test_status_endpoint.py::TestStatusBadge`**, not `test_routes_ui.py`.
  `test_routes_ui.py` contains no badge tests. This is a **significant brief inaccuracy** —
  the implementer must update `tests/test_status_endpoint.py`, not `test_routes_ui.py`.

**Current badge logic in `ui_status_badge` (verbatim, lines 184-186):**

```python
status = str(report["status"])  # pass | warn | fail
summary = str(report["summary"])
css = {"pass": "ok", "warn": "warn", "fail": "down"}.get(status, "down")
```

This maps the top-level `status` field directly to CSS. `summary` is the pre-built string
from `compute_health_status` (`"DEGRADED | corpus vN | M notebooks"` for all `warn` cases).
Both the CSS class and the label text need to be computed from `checks` rather than the
top-level `status`.

**Summary field origin (verbatim, lines 458-470 in health.py):**

```python
any_warn = degraded or disk_warn or backup_warn or nb_status == "warn"
status = "warn" if any_warn else "pass"
label = {"pass": "READY", "warn": "DEGRADED"}[status]
nb_text = "?" if nb_count is None else nb_count
summary = (
    f"{label} | corpus v{resources.corpus_info.version} | "
    f"{nb_text} notebooks" + (" | degraded" if degraded else "")
)
```

The `summary` field in the report is **also** wrong — it uses a single `"DEGRADED"` label
for all `warn` cases. **If the implementation wants to show "WARN" in the badge text, it
must NOT rely on `report["summary"]`** — it must re-derive the label in `ui_status_badge`
by inspecting `report["checks"]` directly.

**CSS classes already present in `frontend/static/app.css`:**
- `.status-badge--ok` (green, #e6f4ea)
- `.status-badge--warn` (amber, #fdf3e2)
- `.status-badge--down` (red, using `--error-bg`/`--danger`)

No `.status-badge--degraded` exists. The brief implies adding it OR reusing `--warn` for
ops-only issues while using `--down` (or a new class) for retrieval-degraded. The brief
says "possibly add an --ops-warn variant for clarity."

**`process:uptime` status is always `"pass"`** — it can never contribute to a WARN or
DEGRADED badge, making it a safe member of either bucket (irrelevant in practice).

---

## Prior decisions and lessons

From the recent git log, the last 20 commits are clean milestone completions for
`verification-feedback-m4`, `notebook-surface-expansion-m6/m7`, and various E14 ops milestones.
No stale branch, no incomplete work.

**Adjacent state.json files:** this is a new standalone milestone with no prior research
artifacts beyond state.json showing `phase: research-running`.

**Patterns to preserve:**
- `tests/test_status_endpoint.py::TestStatusBadge` has TWO existing tests: `test_badge_returns_html_fragment_200`
  (asserts `status-badge--ok`) and `test_badge_down_class_when_not_warm` (asserts
  `status-badge--down`). These need a new WARN scenario test.
- `TestStatusLineParser::test_warn_line` in `test_status_endpoint.py` pins that
  `format_status_line` produces a line starting with `"DEGRADED"` for status=`"warn"`. The
  `tools/status_line.py` parser is a SEPARATE consumer of `/status` — the milestone brief
  does NOT require changing it (it shows the operator a raw label, not the badge). Keep
  `status_line.py` unchanged to avoid scope creep.

**Check-classification precedent:** no "check classification" convention is documented
anywhere in `.claude/notes/`. This is a first-class design decision in this milestone.
The correct approach is to hardcode the retrieval-side allowlist in `ui_status_badge`
(since that is the only consumer needing the distinction).

---

## External sources

**MCP spec (2025-06-18):** Not relevant — `ui_status_badge` is not an MCP tool, not part
of the `tools/list` surface, and `server/routes/ui.py` contains no tool registrations.

**Prompt-caching docs:** Not relevant to this change. Confirmed: `server/routes/ui.py` is
NOT part of the `ALL_TOOLS` table in `server/tools.py`. From `07-multi-agent-caching.md`
(verbatim): "Pin tool JSON schemas. Sort properties alphabetically at serialization time.
Freeze descriptions as constants in source." None of these apply here. `EXPECTED_TOOL_SCHEMA_SHA256`
in `tests/test_server_tool_schema.py` is NOT touched by this change.

---

## Recommendation

**Implementation approach: hardcode a `_RETRIEVAL_CHECKS` frozenset in `ui_status_badge`
and walk `report["checks"]` to split the label.**

Concrete change to `ui_status_badge` in `server/routes/ui.py`:

1. Define at module level (or inline in the function) a frozenset of retrieval-side check
   keys: `{"embedder:status", "lancedb:status", "corpus:version", "notebooks:count"}`.
2. Walk `report["checks"]` (which is a `dict[str, list[dict]]`). For each key, extract
   `checks[key][0]["status"]` defensively (guard against empty list or missing key).
3. If any retrieval-side check has a non-`"pass"` status → label `"DEGRADED"`, CSS `"warn"`
   (reuse amber) OR introduce a new `--degraded` CSS class in `app.css` (stronger visual).
4. Elif any check has a non-`"pass"` status → label `"WARN"`, CSS `"warn"` (amber).
5. Else → label `"READY"`, CSS `"ok"`.
6. Build `safe` from `f"{label} | corpus v{corpus_version} | {nb_count} notebooks"` by
   reading `corpus:version[0].observedValue` and `notebooks:count[0].observedValue` from
   the checks dict directly (DO NOT rely on `report["summary"]` — it will still say
   "DEGRADED" for ops-side warns).

**For CSS:** add `.status-badge--degraded` to `app.css` with a distinct color from
`--warn` (e.g. red-orange or a deeper amber). This gives operators an immediate visual
distinction between "backup is stale" (amber) and "corpus is on fallback" (red-orange).
This is preferable to reusing `--warn` for both, which would silently collapse the visual
distinction the text adds back.

**Rationale:** the frozenset approach is the most direct, least coupled, and requires no
new abstractions. The alternative (a `componentType == "datastore"` split) would falsely
classify `process:uptime` as an ops check on its componentType alone — but `process:uptime`
carries componentType `"system"` anyway, so it would work. However, componentType is not a
documented classification axis in the milestone brief's intent; a named allowlist is more
legible and robust to future check additions.

---

## Open questions

### 1. Should retrieval-degraded use `--warn` (amber) or a new `--degraded` CSS class?

The brief says "possibly add an --ops-warn variant for clarity." My recommendation is to
add `--degraded` (reuse the existing `--down` red-orange hue but maybe lighter) so the
badge color alone communicates urgency without requiring the operator to read the text.
If the adversary finds this too cosmetic, the implementer can reuse `--warn` for
retrieval-degraded and reserve `--down` for the "not warm" case — that is the conservative
fallback.

### 2. Does `corpus:version` belong in the retrieval-side bucket?

In the current code, `corpus:version` **always returns `"pass"`** — it has no warn/fail
path. Including it in the retrieval-side set is safe (a future degradation signal would
correctly light up DEGRADED), but today it never fires. **The brief explicitly lists it**
so include it. No open issue here; just documenting the "currently inert" state.

### 3. What about `notebooks:count` warn = retrieval-degraded?

The brief says yes: `notebooks:count` non-pass is retrieval-side. But the warn condition
for `notebooks:count` is "store probe failed or store absent" — which is a DB/SQLite
failure, not a retrieval failure. The corpus is still fully searchable. **This is a
classification judgment call in the brief**; implement as specified (retrieval-side) since
the brief is explicit.

---

## Failure-mode analysis

### FM-1: New check added later silently falls into ops-side (or neither bucket)

**Trigger:** developer adds `corpus:drift_detected` or similar in `server/health.py` without
updating the frozenset in `ui_status_badge`.

**Symptom:** badge shows "WARN" (ops-only) when it should show "DEGRADED" — silent
misclassification. An operator might dismiss the badge without acting.

**Mitigation:** a comment in `ui_status_badge` explicitly listing the frozenset with a
cross-reference to `compute_health_status`, plus a test that enumerates the current full
check key set and asserts all are classified (will fail when a new check appears and forces
the developer to make a conscious classification decision). This is the strongest guard.

### FM-2: `report["checks"]` shape changes (list vs dict)

**Trigger:** a future refactor wraps checks in a list-of-components or changes the IETF
health+json shape.

**Symptom:** `checks.get(key, [])` returns `[]` for all keys; both sets are empty;
badge silently shows "READY" when server is degraded.

**Mitigation:** add a defensive guard: if `checks` is not a `dict`, fall back to reading
`report["status"]` (old behavior) and emit a `logger.warning`. This keeps the badge
functional under schema drift.

### FM-3: `warn` on a retrieval check — does it count as DEGRADED?

**Trigger:** `lancedb:status` is `"warn"` (the current corpus-degraded path — line 353).

**Per acceptance criterion 1:** "When lancedb:status, corpus:version, embedder:status, or
notebooks:count is **non-pass**" → DEGRADED. `"warn"` is non-pass. This is correct and
matches the current degraded case.

**Mitigation:** the condition in `ui_status_badge` must be `status != "pass"`, NOT
`status == "fail"`. Do not be tempted to use `status in ("fail", "error")`.

### FM-4: `report["checks"]` is empty (server pre-startup, fail path)

**Trigger:** `compute_health_status` returns `status == "fail"` with a minimal `checks`
dict containing only `embedder:status`, `lancedb:status`, and `process:uptime` (see the
pre-startup branch, lines 322–341 in health.py).

**Symptom:** retrieval-side bucket check finds `embedder:status: fail` → correctly shows
DEGRADED. But the `process:uptime` check (ops-side) is `"pass"` on the pre-startup path too.

**Actually fine** — the pre-startup path correctly triggers DEGRADED because `embedder:status`
is `"fail"`. No silent regression here.

**However:** the top-level `status == "fail"` should short-circuit to `css = "down"` as
before. The new disambiguation logic should only apply when `status == "warn"`. The
`"fail"` case (server not warm) should remain `status-badge--down`.

### FM-5: CSS class `--degraded` misspelled or missing in app.css

**Trigger:** implementer adds CSS class but spells it differently than the Python f-string
(`status-badge--degraded` vs `status-badge--degarded`).

**Symptom:** badge renders with no background/color — visually unstyled, appears as plain
text. No Python error, no test failure unless a test asserts the rendered CSS class AND
verifies it's a known value.

**Mitigation:** add a test that asserts the rendered badge fragment contains
`status-badge--{expected_class}` where `expected_class` is one of the defined set.

### FM-6: `/ui/status-badge` auth check (loopback only?)

**Trigger:** `/ui/status-badge` is under the `/ui` prefix and uses `SecFetchSiteMiddleware`.

**Finding from `tests/test_status_endpoint.py::TestStatusSecFetchSiteDeviation`
(lines 357-395):** the test explicitly pins that `/ui/status-badge` is exempt from the
`Sec-Fetch-Site: same-origin` 403 because it lives under `/ui`. The test
`test_ui_status_badge_not_403_browser_same_origin` passes a `Sec-Fetch-Site: same-origin`
header and asserts it is NOT 403. **No auth issue exists** — this was already resolved in
`notebook-ops-hardening-m4`. The badge is loopback-only by the bind constraint
(`127.0.0.1`) but requires no additional auth. No change needed here.

---

## External writes the implementation will require

None — this milestone is purely local.

- No git push required.
- No PR creation.
- No ticket mutation.
- No infra change.

The three changed files are: `server/routes/ui.py`, `frontend/static/app.css` (optional
new CSS class), and `tests/test_status_endpoint.py` (badge test updates). All local edits.
