# Research Brief — corpus-integrity-completion-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T20:05:00Z

## In-codebase context

### Design notes

`08-security-observability-ops.md` is the primary relevant note. It defines the
observability stack and documents failure modes in a table. The most relevant quote
on observability design:

> "Disk full — Prometheus alert on free space — Block ingestion, allow reads to
> continue, page operator"

This is the model for the two new rules: same Prometheus-alert-on-gauge pattern, same
operator-visible failure mode signal.

`08-security-observability-ops.md` also documents the scrape model:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://127.0.0.1:7733/readyz"]
  interval: 30s
```

The group-level `interval: 30s` in `infra/prometheus/alerts.yml` matches this. The 10m
`for:` on `ArXMCPCorpusCountRowsFailed` = 20 scrapes; the 1h `for:` on
`ArXMCPCorpusUnindexedRows` = 120 scrapes. Both are reasonable suppression windows for
a startup-set gauge (startup-set means the gauge value is constant between restarts).

### Existing `infra/prometheus/alerts.yml` — shape and style constraints

The file has one group named `arxmcp` with a 30s interval. Every rule carries:
- `alert:`, `expr:`, `for:`, `labels:`, `annotations:` — the test `test_alert_rule_shape`
  enforces this structure at every test run.
- `labels:` block with exactly `severity` + `component`. No `team:` label. Canonical
  severity values are `"critical"`, `"warning"`, `"info"`, `"page"` (validated by the test).
- `annotations:` block with `summary:`, `description:` (multiline `|`), and `runbook_url:`.

**Verbatim annotation key from ArXMCPDiskFull:**
```yaml
runbook_url: "https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/failure-modes.md#disk-full"
```

The key is `runbook_url` (not `runbook`). All 4 existing rules that carry it use
`runbook_url`. The URL base is `https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/`.

**Existing component values:** `storage`, `server`, `backup`, `eval`, `latexml`. The new
rules' closest match is `storage` (corpus data integrity) or a new `corpus` value.
The roadmap does not mandate a specific value; the implementation should pick `corpus` to
distinguish from the `ArXMCPDiskFull` storage-space rule.

**Critical rule precedent — `ArXMCPDiskFull`:**
```yaml
- alert: ArXMCPDiskFull
  expr: arxmcp_disk_free_bytes < 10737418240
  for: 5m
  labels:
    severity: critical
    component: storage
  annotations:
    summary: "arXMCP free disk space < 10 GB"
    description: |
      ...
    runbook_url: "https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/failure-modes.md#disk-full"
```

The new `ArXMCPCorpusCountRowsFailed` rule must mirror this shape exactly.

### Gauge definitions in `server/health.py`

**CORPUS_CHUNK_COUNT_ACTUAL** (verbatim docstring):
```python
#: corpus-integrity-observability-m2 — the live ``chunks_table.count_rows()``
#: captured ONCE at startup (cached on Resources.startup_chunk_count). NOT
#: recomputed per scrape. ``-1`` means count_rows() failed at startup
#: (Resources.startup FM-2). Equals the marker gauge on the happy path.
CORPUS_CHUNK_COUNT_ACTUAL = Gauge(
    "arxmcp_corpus_chunk_count_actual",
    "Live chunks-table row count read once at startup. -1 = count "
    "unavailable. Equals arxmcp_corpus_chunk_count_marker on the happy "
    "path; a gap indicates corpus/marker divergence.",
)
```

**CORPUS_UNINDEXED_ROWS** (verbatim docstring):
```python
#: corpus-integrity-observability-m3 (scout CAND-10) — total HNSW unindexed
#: rows across all ANN indexes, read ONCE at startup. -1 = could not determine
#: (index API raised, or no ANN index exists); 0 = checked & clean; >0 =
#: abnormal (rows committed without an index rebuild → ANN brute-forces them, a
#: silent perf degradation). Non-zero is ALWAYS abnormal in normal operation
#: (_create_indices runs synchronously in write_chunks). Alert on > 0.
CORPUS_UNINDEXED_ROWS = Gauge(
    "arxmcp_corpus_unindexed_rows",
    "Total HNSW unindexed rows across all ANN indexes, read once at startup. "
    "-1 = unavailable (index API raised, or no ANN index). 0 = fully indexed "
    "(normal). >0 = abnormal: ANN brute-forces those rows; re-run ingest to "
    "rebuild.",
)
```

The -1 sentinel for `arxmcp_corpus_chunk_count_actual` is the canonical "count failed"
signal, confirmed by the gauge docstring AND by the roadmap's `[MUST]` assumption:
> "`arxmcp_corpus_chunk_count_actual = -1` is the canonical 'count_rows failure' sentinel
> per the m2/m3 implementation (verified at `server/health.py:111-120`)."

**Important:** the `-1` sentinel applies to BOTH gauges. The AC specifies
`arxmcp_corpus_unindexed_rows > 0` (not `!= -1`) for the unindexed-rows rule. This is
intentional — the -1 sentinel means "data unavailable," not "rows are unindexed." The
alert correctly fires only on confirmed > 0 (a real abnormal state).

### Existing test validation pattern in `tests/test_alerts_yaml.py`

The file already has a `promtool check rules` test:
```python
@pytest.mark.skipif(
    shutil.which("promtool") is None,
    reason="promtool not on PATH (install via `brew install prometheus` on macOS)",
)
def test_promtool_check_rules():
    result = subprocess.run(
        ["promtool", "check", "rules", str(ALERTS_PATH)],
        ...
    )
    assert result.returncode == 0, ...
```

This test is NOT guarded by any custom marker like `requires_promtool`. It uses a
standard `pytest.mark.skipif` with `shutil.which("promtool") is None`. This means the
AC's "if a `requires_promtool` test marker pattern is added" clause is already solved —
the existing pattern in `test_alerts_yaml.py` IS the pattern. No new test marker is
needed; the existing `test_promtool_check_rules` will automatically validate the new
rules when `promtool` is on PATH.

The test also has `test_required_alerts_present` that pins `ArXMCPDiskFull`,
`ArXMCPDegradedMode`, `ArXMCPBackupStale`. The implementer SHOULD add
`ArXMCPCorpusCountRowsFailed` and `ArXMCPCorpusUnindexedRows` to that required set to
enforce forward regression protection.

### Scout final report — CAND-1 verbatim (load-bearing)

From `.claude/notes/capability-scouts/corpus-integrity-observability/artifacts/final-report.md` §3 Rank 1:

> "Challenger v0 scope adjustment: Ship rule (b) (`actual == -1 for 10m` — count_rows()
> failure sentinel; NOT covered by `ArXMCPDegradedMode`) and rule (c) (`unindexed_rows
> > 0 for 1h` — NOT covered). Fold a `corpus-drift-runbook.md` into this scope; absorb
> CAND-24's killed runbook idea here."

> "Challenger objections (MINOR): Rule (a) is redundant with the existing
> `ArXMCPDegradedMode` for the above-tolerance case — `DegradedState('chunk_count_diverged')`
> already fires that alert. Drop rule (a) or emit it as `severity: warning` only for
> sub-tolerance drift."

The AC confirms this decision:
> "No new rule is added for above-tolerance drift — the existing `ArXMCPDegradedMode`
> covers it; that decision is documented in the implementation summary per challenger §3 CAND-1."

### `docs/ops/` directory state

The `docs/ops/` directory exists and contains 16 files. `corpus-drift-runbook.md` is NOT
yet present — the sibling m2 milestone will create it. The m1 rules reference it
optimistically (the roadmap explicitly acknowledges this: "m1 references m2's file path
optimistically and the link will resolve once both ship").

## Prior decisions and lessons

**Recent git log:** The last 20 commits show:
- `ff00f49 chore(notes,scripts): land corpus-integrity-observability scout` — the prior
  epic's scout report just landed
- No corpus-integrity-completion milestones have shipped yet

**Adjacent milestone states:**
- `corpus-integrity-observability-m2` — COMPLETE. Shipped `CORPUS_CHUNK_COUNT_ACTUAL`
  gauge with `-1` sentinel contract. Confirmed at `server/health.py:115-120`.
- `corpus-integrity-observability-m3` — COMPLETE. Shipped `CORPUS_UNINDEXED_ROWS` gauge
  with `-1` sentinel for unavailable. Confirmed at `server/health.py:128-134`.

**Test infrastructure already present:** `tests/test_alerts_yaml.py` was shipped in
E14_S05 and already validates YAML syntax, group presence, rule shape, severity
canonicality, and runs `promtool check rules` when available. The implementation must
ensure the existing `test_alert_rule_shape` test continues to pass (both new rules must
carry `alert`, `expr`, `for`, `labels`, `annotations` with a canonical `severity`).

**No banned patterns at risk:** This milestone is pure YAML. No Python code changes. No
`assert`, no `BaseHTTPMiddleware`, no `anthropic` SDK. The macOS segfault guard
(`KMP_DUPLICATE_LIB_OK`) is unaffected. No MCP tool surface change; no
`EXPECTED_TOOL_SCHEMA_SHA256` re-pin required.

**Doc placement:** `docs/ops/corpus-drift-runbook.md` is the referenced path. Per the
roadmap, this is a pre-existing `docs/ops/` exception to CLAUDE.md §1. This milestone
does NOT create the runbook (m2 does); it only references the URL.

## External sources

### Prometheus alert rule schema

Per Prometheus documentation (https://prometheus.io/docs/alerting/configuration/),
the canonical annotation key for linking to operator documentation is `runbook_url`. This
matches arXMCP's existing usage in all 5 existing rules. Some organizations use `runbook`
(a shorter key), but arXMCP consistently uses `runbook_url` across all existing rules.
The implementer should use `runbook_url` — deviation from the project's established
convention would introduce inconsistency with no benefit.

The Prometheus alerting rule schema requires:
- `alert:` — name string
- `expr:` — PromQL expression
- `for:` — duration string (e.g. `10m`, `1h`)
- `labels:` — key/value pairs applied to alerts
- `annotations:` — human-readable strings (templated)

`for:` is tested against the group `interval: 30s`. Both `10m` and `1h` are multiples of
30s and well above the minimum (1 scrape interval). This is sensible suppression for a
startup-set gauge that never changes between restarts.

### `promtool check rules` semantics

`promtool check rules <file>` exits 0 on valid YAML + valid PromQL expressions. It
validates: YAML parsing, rule group structure, expression syntax, label/annotation
format, `for:` duration format. The existing test wraps this with `check=False` and
asserts `returncode == 0`. After the new rules are added, the same test validates them
automatically when `promtool` is on PATH. No additional test infrastructure is needed.

## Recommendation

**Append exactly two rules to `infra/prometheus/alerts.yml` following the precise shape of
`ArXMCPDiskFull` and `ArXMCPLatexmlDrift`.**

Rule 1: `ArXMCPCorpusCountRowsFailed`
- `expr: arxmcp_corpus_chunk_count_actual == -1`
- `for: 10m`
- `labels: {severity: critical, component: corpus}`
- `annotations.runbook_url: "https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/corpus-drift-runbook.md"`

Rule 2: `ArXMCPCorpusUnindexedRows`
- `expr: arxmcp_corpus_unindexed_rows > 0`
- `for: 1h`
- `labels: {severity: warning, component: corpus}`
- `annotations.runbook_url:` same URL as above

Use `component: corpus` (not `storage`) to distinguish from the `ArXMCPDiskFull`
storage-space rule. All existing rules use exactly `severity` + `component` — do not
add a `team:` label; there is no precedent and it would break test expectations.

Additionally, add both new alert names to the `required` set in
`test_required_alerts_present` in `tests/test_alerts_yaml.py`. This is the correct
forward-protection pattern — the test already enforces required alert presence; extending
it for the two new rules costs 2 lines and prevents accidental deletion.

Do NOT create `docs/ops/corpus-drift-runbook.md` in this milestone — that is m2's
deliverable. The `runbook_url` referencing a not-yet-existent file is explicitly
acknowledged in the roadmap as intentional optimistic ordering.

Do NOT add `ArXMCPCorpusChunkCountDrift` or any rule on `abs(...) / clamp_min(...)` —
the AC explicitly documents that `ArXMCPDegradedMode` already covers the above-tolerance
drift case and per the CAND-1 challenger finding, a duplicate rule is not warranted.

## Open questions

**(a) `runbook_url` vs `runbook` annotation key** — resolved. Every existing arXMCP
rule uses `runbook_url`. Use `runbook_url`. No open question.

**(b) Does a `requires_promtool` marker need to be added?** — resolved. The existing
`test_promtool_check_rules` in `tests/test_alerts_yaml.py` already uses
`pytest.mark.skipif(shutil.which("promtool") is None, ...)`. No new marker pattern is
required. The AC's "if a `requires_promtool` test marker pattern is added" clause is
speculative and unnecessary given the existing infrastructure.

**(c) Should extra `labels:` (team, component-tier) be added?** — resolved. The existing
5 rules carry exactly `severity` + `component`. The test `test_alert_rule_shape` validates
`severity` is present and canonical. No `team:` label exists in any rule; adding one
would be pattern-inconsistent. Use only `severity` + `component`.

**Genuine open question for the implementer:** The `component: corpus` value is new (existing
values are `storage`, `server`, `backup`, `eval`, `latexml`). No test validates the
component value's domain. This is safe to introduce, but note that Grafana dashboards or
Alertmanager routing rules (if the operator has them) that filter by `component` may need
updating. For a single-workstation deployment this is an FYI, not a blocker.

No other open questions — implementation can proceed on the above recommendation.

## External writes the implementation will require

- `git push origin main` after Phase 4 rectification (per-event authorization required
  per CLAUDE.md §4.4; not pre-authorized here).

All other changes are local: two YAML rule blocks appended to
`infra/prometheus/alerts.yml`, two new names added to the `required` set in
`tests/test_alerts_yaml.py`. No infra mutation, no PR, no ticket, no third-party API
call.
