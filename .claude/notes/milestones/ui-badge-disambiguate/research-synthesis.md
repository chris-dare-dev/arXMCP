# Research Synthesis — ui-badge-disambiguate

**Generated:** 2026-05-30 (orchestrator merge of brief-1 + brief-2)
**Research mode:** standard (2× Sonnet in parallel)
**Inputs:** [research-brief-1.md](research-brief-1.md), [research-brief-2.md](research-brief-2.md)

---

## Convergent findings (both briefs agree, load-bearing)

### 1. Test-file path in the brief is WRONG

The milestone brief names `tests/test_routes_ui.py` as the location of badge tests.
**Both briefs independently confirm the file does not contain any badge tests.**
The existing badge tests live in `tests/test_status_endpoint.py::TestStatusBadge`:

- `test_badge_returns_html_fragment_200` — warm+healthy → asserts `status-badge--ok`
- `test_badge_down_class_when_not_warm` — not warm → asserts `status-badge--down`

There is **no existing test for the warn/degraded badge class**. The new test cases
(retrieval-degraded → DEGRADED, ops-only-warn → WARN) MUST go in
`tests/test_status_endpoint.py::TestStatusBadge`, not in `test_routes_ui.py`.

### 2. `report["summary"]` is unreliable for the new label

`compute_health_status` in `server/health.py` pre-renders `summary` as
`"DEGRADED | corpus vN | M notebooks"` for **all** `warn` cases — there is no
distinction between retrieval-degraded and ops-only-warn at that layer (verbatim
from `server/health.py:457-469`):

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

**The badge MUST re-derive the label by inspecting `report["checks"]` directly.**
Both briefs converge on this. Reusing `report["summary"]` verbatim would defeat the
entire purpose of the milestone (the badge would still say "DEGRADED" for ops-warn).

### 3. `report["checks"]` shape is `dict[str, list[dict]]` (IETF health+json)

Each check key maps to a list (one-element list in current code) of dicts with
`status: "pass" | "warn" | "fail"`. The retrieval/ops bucket assignment is:

**Retrieval-side (from milestone brief AC1):**
- `embedder:status` — always `"pass"` warm; `"fail"` only on pre-startup path
- `lancedb:status` — `"warn"` when `resources.degraded is not None` (THE current
  retrieval-degraded signal)
- `corpus:version` — always `"pass"` today (forward-compat inclusion)
- `notebooks:count` — `"warn"` when store absent or probe throws

**Ops-side (from milestone brief AC2):**
- `backup:time` — `"warn"` when no `backup-status.json` / stale / unreadable
- `disk:utilization` — `"warn"` when free < `DISK_PAUSE_THRESHOLD_BYTES` (10 GB)
- `process:uptime` — **always `"pass"`** (never contributes to warn today)

### 4. No MCP surface touched — no BP1/tool-schema hash bump

`server/routes/ui.py` is not part of `ALL_TOOLS` in `server/tools.py`.
`EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` is unchanged.
This is purely an HTML fragment + CSS + Python edit, all loopback-only.
Cross-checked against `.claude/notes/07-multi-agent-caching.md`.

### 5. No external writes required

Both briefs independently confirm: zero `git push`, no PR, no ticket, no infra
mutation, no third-party API call. Purely local; commits land on `main` directly
per the project's single-user-workstation convention.

### 6. `tools/status_line.py` is out of scope

`make status` CLI maps `warn → "DEGRADED"` for terminal context. The brief asks for
badge-only disambiguation. Both briefs recommend leaving the CLI as-is. No scope
creep into `tools/status_line.py`.

---

## Divergence resolved by the orchestrator

### Visual treatment: reuse `--warn` vs add `--ops-warn` CSS class

- **Brief 1** recommends reusing the existing `--warn` (amber) for BOTH DEGRADED
  and WARN — text label carries the semantic distinction. Simpler, less CSS.
- **Brief 2** recommends adding a NEW CSS class for visual distinction; suggests
  `--degraded` (red-orange) for retrieval-degraded.

**Orchestrator resolution: add `--ops-warn` CSS variant with a softer / cooler tone;
keep existing `--warn` for DEGRADED.** Reasoning:

1. The milestone brief explicitly says **"possibly add `--ops-warn` variant for
   clarity"** — naming the variant. The user's framing is "DEGRADED is the urgent
   amber; ops-warn is informational." That maps directly to: `--warn` stays amber
   (DEGRADED = act); `--ops-warn` gets a softer / blue-grey informational tone.

2. Brief 2's instinct (visual signal aids glance-parsing) is correct, but the
   direction was wrong — the user's brief names the NEW variant for the OPS case,
   not for the degraded case. Adding `--ops-warn` (not `--degraded`) keeps the
   existing `--warn` semantics intact for any callers that aren't the badge.

3. Adds exactly **one** CSS rule (~3 lines). Brief 1's concern about CSS proliferation
   is addressed by keeping the addition minimal and adding a test that asserts the
   class is rendered.

### `corpus:version` in the retrieval allowlist

Both briefs agree it never fires today (`"pass"` always in warm path), but include
it per AC1 for forward-compat. No conflict — include in the frozenset.

### `notebooks:count` warn = retrieval-degraded?

Brief 2 raised a judgment question: `notebooks:count` warning is a DB probe failure,
arguably "ops-side." Brief 1 accepts the brief's classification (retrieval-side).

**Orchestrator resolution: retrieval-side**, per AC1. The user already made this
classification call; we honor it. Rationale: if the notebooks store probe is broken,
the operator cannot confirm any notebook is loaded, which IS a retrieval-readiness
concern from the operator's perspective.

---

## Recommended implementation shape

**Single inline edit to `server/routes/ui.py::ui_status_badge` + 1 CSS line + 2 new
test cases. NO changes to `server/health.py`, `server/tools.py`, or
`tools/status_line.py`.**

### `server/routes/ui.py` — module-level constant + classify helper

```python
# Retrieval-side check keys: any non-pass here → "DEGRADED" badge.
# Keep in lockstep with compute_health_status() check key set in server/health.py.
# If you add a check there, classify it here too.
_RETRIEVAL_CHECK_KEYS = frozenset({
    "embedder:status",
    "lancedb:status",
    "corpus:version",
    "notebooks:count",
})


def _classify_badge(report: dict) -> tuple[str, str]:
    """Return (label, css_modifier) for the operator-console badge.

    fail  → ("DOWN", "down")          — server not warm
    warn (retrieval) → ("DEGRADED", "warn")     — operator should act
    warn (ops only)  → ("WARN", "ops-warn")     — informational
    pass  → ("READY", "ok")
    """
    status = str(report.get("status") or "fail")
    if status == "fail":
        return ("DOWN", "down")
    if status == "pass":
        return ("READY", "ok")
    # status == "warn": split by check classification
    checks = report.get("checks") or {}
    if not isinstance(checks, dict):
        # Defensive: schema drift fallback — preserve today's behavior
        return ("DEGRADED", "warn")
    for key in _RETRIEVAL_CHECK_KEYS:
        entries = checks.get(key) or []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("status") not in (None, "pass"):
                return ("DEGRADED", "warn")
    return ("WARN", "ops-warn")
```

### `ui_status_badge` body change

Replace lines 184–186 (current verbatim):
```python
status = str(report["status"])  # pass | warn | fail
summary = str(report["summary"])
css = {"pass": "ok", "warn": "warn", "fail": "down"}.get(status, "down")
```

with:
```python
label, css = _classify_badge(report)
raw_summary = str(report.get("summary") or "")
# Replace compute_health_status()'s leading label token with our disambiguated label.
# raw_summary format: "{LABEL} | corpus v{N} | {M} notebooks[ | degraded]"
if "|" in raw_summary:
    summary = label + raw_summary[raw_summary.find("|"):]
else:
    summary = label
```

### `frontend/static/app.css` — one new variant

Add after the existing `.status-badge--warn` rule (~line 124):
```css
.status-badge--ops-warn { background: #eef2f7; color: #475569; border-color: #94a3b8; }
```

(Soft blue-grey informational tone, distinct from the amber `--warn`.)

### `tests/test_status_endpoint.py::TestStatusBadge` — 2+ new cases

Add to the existing `TestStatusBadge` class:

1. **retrieval-warn → DEGRADED + `status-badge--warn`** — fixture where
   `lancedb:status = "warn"` (the live degraded path), asserts the fragment contains
   both `"DEGRADED"` text and `class="status-badge status-badge--warn"`.

2. **ops-only-warn → WARN + `status-badge--ops-warn`** — fixture where
   `backup:time = "warn"` and all retrieval-side checks are `"pass"`, asserts the
   fragment contains `"WARN"` text (NOT `"DEGRADED"`) and
   `class="status-badge status-badge--ops-warn"`.

3. Optional defensive: **mixed retrieval-warn + ops-warn → DEGRADED** (retrieval wins).

The two existing cases (`--ok`, `--down`) must continue to pass unchanged.

---

## Failure-mode analysis (synthesized)

| ID | Trigger | Symptom | Mitigation |
|----|---------|---------|------------|
| FM-1 | New check added to `compute_health_status` (e.g. `parser:failures`) without updating `_RETRIEVAL_CHECK_KEYS` | Silently falls into "ops" bucket — operator dismisses what should be DEGRADED | Inline comment cross-referencing `server/health.py`; consider future test that enumerates all check keys and asserts each is classified |
| FM-2 | `report["checks"]` schema drift (list-of-components instead of dict) | All buckets empty → silent "WARN" label when degraded | `_classify_badge` falls back to today's "DEGRADED" behavior if `checks` is not a dict |
| FM-3 | Retrieval check at `warn` (not `fail`) — should that count? | AC1 says "non-pass" — yes. The current `lancedb:status warn` for fallback IS the degraded signal | Use `entry.get("status") not in (None, "pass")`, NOT `entry.get("status") == "fail"` |
| FM-4 | `status == "fail"` (server pre-startup) | Should stay `--down`, not the new disambiguation | `_classify_badge` short-circuits on `status == "fail"` first |
| FM-5 | New CSS class misspelled in template vs CSS file | Badge renders unstyled, no test failure | Add assertion in new tests on exact `status-badge--ops-warn` class string; CSS file edit + Python f-string in same commit |
| FM-6 | `/ui/status-badge` auth/Sec-Fetch | Already resolved in notebook-ops-hardening-m4; `TestStatusSecFetchSiteDeviation` pins exemption | No change needed; existing test guards |
| FM-7 | `report["summary"]` format change (e.g. `compute_health_status` drops the leading `LABEL |`) | Badge text shows just `label` (e.g. "WARN") with no corpus version | Defensive: if `"|"` not in raw_summary, fall back to `label` alone — already in shape above |

---

## Acceptance criteria checklist (from brief)

1. ✅ When `lancedb:status`, `corpus:version`, `embedder:status`, or `notebooks:count`
   is non-pass → label includes `"DEGRADED"`. — Covered by `_RETRIEVAL_CHECK_KEYS`
   + `_classify_badge` retrieval-side branch + new test case 1.

2. ✅ When ONLY `backup:time`, `disk:utilization`, or `process:uptime` is non-pass →
   label is `"WARN"` (not `"DEGRADED"`). — Covered by `_classify_badge` ops-only
   fall-through branch + new test case 2.

3. ✅ Existing badge tests in `tests/test_status_endpoint.py` (NOT
   `tests/test_routes_ui.py` as the brief incorrectly stated) updated. — Add 2 new
   cases to `TestStatusBadge`; verify the 2 existing cases still pass.

4. ✅ `make test` green, ruff clean, BP1/tool-schema hashes unchanged. — Verified
   no MCP surface touched (Convergent finding §4); ruff requires care around
   the new helper signature and CSS edit.

5. ✅ No new dependencies, no SPA, no JS beyond htmx. — One CSS rule added;
   Python uses only stdlib + existing imports; htmx polling unchanged.

---

## Open questions (none blocking; documenting judgment calls)

1. **`corpus:version` is forward-compat-only today** (always `"pass"`). Included
   in retrieval allowlist per AC1 — agreed, do not remove.

2. **`tools/status_line.py` CLI consistency:** The `make status` CLI will still
   say `"DEGRADED"` for ops-warn. Per brief scope, leave it alone. If the user
   later wants CLI parity, it's an easy follow-up.

3. **Visual contrast of `--ops-warn`**: Chose soft blue-grey (`#eef2f7` /
   `#475569`). Alternative: a lighter amber. Implementer may swap if color
   doesn't render distinctively in the operator's browser theme.

---

## External writes the implementation will require

**None.** Purely local. No `git push`, no PR, no `gh issue create`, no infra
mutation, no third-party API call. All work commits to `main` per project
convention (single-user-workstation).

---

## Orchestrator synthesis note

- **Test-file correction** (briefs flagged in agreement): use
  `tests/test_status_endpoint.py::TestStatusBadge`, NOT `tests/test_routes_ui.py`.
- **CSS variant choice resolved in favor of brief 2's instinct + user's brief
  language**: add `--ops-warn` (not `--degraded`); keep `--warn` for DEGRADED.
  This honors the user's "possibly add `--ops-warn` variant for clarity"
  wording verbatim.
- **`notebooks:count` classification** resolved per user's AC1 (retrieval-side),
  overriding brief 2's mild objection.
- **`tools/status_line.py` scope** held at brief-explicit boundary (badge-only).
- **Implementation size estimate:** ≪ 200 LOC, 3 files (`server/routes/ui.py`,
  `frontend/static/app.css`, `tests/test_status_endpoint.py`). Inline path
  appropriate for Phase 2.
