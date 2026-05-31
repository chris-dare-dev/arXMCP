# Research Brief — corpus-integrity-completion-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T20:05:00Z

---

## In-codebase context

### Existing alerts.yml structure (load-bearing)

`infra/prometheus/alerts.yml` (110 lines) has ONE group named `arxmcp` containing
**five existing rules** under `groups[0].rules[]`:

1. `ArXMCPDiskFull` — `expr: arxmcp_disk_free_bytes < 10737418240`, `for: 5m`,
   `severity: critical`, `component: storage`
2. `ArXMCPDegradedMode` — `expr: arxmcp_degraded_mode_active == 1`, `for: 1m`,
   `severity: warning`, `component: server`
3. `ArXMCPBackupStale` — `expr: (time() - arxmcp_backup_last_success_timestamp_seconds) > 172800`,
   `for: 10m`, `severity: warning`, `component: backup`
4. `ArXMCPEvalQuarantine` — `expr: arxmcp_eval_quarantine_active == 1`, `for: 1m`,
   `severity: warning`, `component: eval`
5. `ArXMCPLatexmlDrift` — `expr: arxmcp_latexml_drift_fixtures > 0`, `for: 1m`,
   `severity: warning`, `component: latexml`

**Critical structural constraint:** the file has a single top-level `groups:` key containing
one array. The new rules MUST be appended INSIDE this existing `groups[0].rules:` array — do NOT
add a second `groups:` key or a second group object. Duplicating the `groups:` key is a YAML
structural error caught by `promtool check rules`.

**Canonical annotation key is `runbook_url`** (not `runbook`). Every existing rule uses
`runbook_url:` verbatim. The AC's `runbook_url` is confirmed correct.

**Label conventions:** every existing rule carries BOTH `severity` and `component` labels.
The proposed rules must also carry a `component` label; the milestone brief only specifies
`severity`. The roadmap text (`e2` epic description) does not mention `component` either, but
the test at `tests/test_alerts_yaml.py:78` requires `{"alert", "expr", "for", "labels",
"annotations"}` — and `labels` must contain `severity`. It does NOT require `component`.
**Recommendation: add `component: corpus` to match the existing per-rule pattern.**

**Severity enum is validated by test:** `tests/test_alerts_yaml.py:92-97` asserts
`labels["severity"] in ("critical", "warning", "info", "page")`. Both `critical` (new rule 1)
and `warning` (new rule 2) are in the allowed set — no change needed.

**Existing test coverage for new names:** `tests/test_alerts_yaml.py:50-70`
(`test_required_alerts_present`) asserts only `{ArXMCPDiskFull, ArXMCPDegradedMode,
ArXMCPBackupStale}` exist. The two new names are NOT in that set. The implementer must decide
whether to add them to the required set — adding them is the right call for regression protection,
but is outside the strict AC. Recommend: extend the set.

### Gauge name verification (confirmed in `server/health.py`)

- `arxmcp_corpus_chunk_count_actual` — line 116: registered as `CORPUS_CHUNK_COUNT_ACTUAL`
- `arxmcp_corpus_unindexed_rows` — line 129: registered as `CORPUS_UNINDEXED_ROWS`

Both are gauges set ONCE at startup (never per-scrape). The `-1` sentinel for
`arxmcp_corpus_chunk_count_actual` is explicitly documented at `server/health.py:113-114`:
"``-1`` means count_rows() failed at startup (Resources.startup FM-2)."

### Runbook file status

`docs/ops/corpus-drift-runbook.md` **DOES NOT EXIST** yet. The 16 files in `docs/ops/`
include `failure-modes.md`, `backup-restore.md`, `drift-watchdog.md`, `latexml-drift-runbook.md`,
and others — but NOT `corpus-drift-runbook.md`. The AC's `runbook_url` points to a file that
ships in m2 (same epic). The roadmap explicitly acknowledges this: "m1 references m2's file
path optimistically and the link will resolve once both ship."

**NO conflict** between milestone brief and existing codebase alert names — neither
`ArXMCPCorpusCountRowsFailed` nor `ArXMCPCorpusUnindexedRows` appear anywhere in the repo
outside the roadmap specification.

### Design note constraints (08-security-observability-ops.md)

Note-08 documents the failure mode table at §"Failure modes and graceful degradation". Neither
`count_rows failure` nor `unindexed rows` appears in that table — these are new corpus-integrity
failure modes from the observability-m2/m3 milestones. The note does not restrict alert naming,
severity tiers, or runbook URL format. No design constraint in note-08 contradicts the AC.

Note-08's observability section lists existing Prometheus metric families but does NOT enumerate
the new `corpus_chunk_count_*` or `corpus_unindexed_rows` gauges (those landed in m2/m3 after
note-08 was authored). This is pre-existing drift — not a conflict.

---

## Prior decisions and lessons

From git log and milestone state:
- `corpus-integrity-observability-m3` (complete) shipped `arxmcp_corpus_unindexed_rows`
  gauge with explicit docstring: "Non-zero is ALWAYS abnormal in normal operation... Alert on > 0."
- `corpus-integrity-observability-m2` (complete) shipped `arxmcp_corpus_chunk_count_actual`
  with the `-1` sentinel contract.
- The adversary scout for corpus-integrity-observability-e3 documented at MEMORY entry
  `2026-05-29 — corpus-integrity-observability-m3 — warn-only-not-degraded-for-perf-issues`:
  "WARN+gauge is the right pattern when results remain CORRECT (just slower)." This confirms
  `arxmcp_corpus_unindexed_rows > 0` = `severity: warning` (not critical) is architecturally
  correct — brute-force ANN fallback is a perf issue, not a correctness regression.
- `tests/test_alerts_yaml.py` has a `promtool` test that **skips when `promtool` is not on
  PATH** (line 122: `@pytest.mark.skipif(shutil.which("promtool") is None, ...)`). The AC
  says "promtool check rules exits 0" — this is conditionally tested, matching the
  existing project pattern.

---

## External sources

**Prometheus alerting rules spec** (https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/):
- `expr`: the PromQL expression defining the alert condition
- `for`: "causes Prometheus to wait for a certain duration between first encountering a new
  expression output vector element and counting an alert as firing" (optional; alerts become
  active immediately on first evaluation if omitted)
- `labels`: "allows specifying a set of additional labels to be attached to the alert"
- `annotations`: "specifies a set of informational labels that can be used to store longer
  additional information such as alert descriptions or runbook links"
- Duration format: Prometheus duration syntax (e.g. `10m`, `1h`)
- No explicit MUST on `for`, `labels`, or `annotations` — only `alert` and `expr` are
  structurally required by Prometheus (the project's test at line 78 enforces all 5 keys)

**Prometheus practices for alerting** (https://prometheus.io/docs/practices/alerting/):
- No explicit recommendation extracted for `for:` durations or severity labels.
- Community convention: Camel Case for alert names (already followed by all 5 existing rules).

**`runbook_url` vs `runbook` annotation key:** The external awesome-prometheus-alerts catalog
does not standardize annotation keys. The in-codebase evidence is definitive: all 5 existing
rules use `runbook_url` — this is the project canon.

**Prometheus version:** `infra/docker-compose.yml` does NOT include a Prometheus service (only
the MCP server). `infra/observability/` contains a Phoenix OTel sidecar (`phoenix-compose.yml`).
No Prometheus docker-compose exists in the repo — Prometheus is operator-deployed separately
per note-08: "the operator runs Prometheus + Grafana separately, landing in E14_S09." The alerts
file header (lines 7-9) confirms: "Reference from prometheus.yml: rule_files:
[ '/etc/prometheus/arxmcp-alerts.yml' ]". The YAML syntax is independent of the Prometheus
version; `promtool check rules` validates against whatever local version is installed.

---

## Failure mode analysis (5 scenarios)

**FM-1: Runbook URL is a 404 at time of alert fire.**
Trigger: Operator's Alertmanager fires `ArXMCPCorpusCountRowsFailed`; they click the
`runbook_url` before m2 ships. GitHub returns 404. Mitigation: (a) the roadmap explicitly
accepts this sequencing: "link resolves once both ship"; (b) the URL path is the same for
both rules — the operator can recognize the pattern; (c) m1 and m2 can land in the same
commit triple (or m2 first). This is an accepted, documented risk per the roadmap.

**FM-2: `arxmcp_corpus_chunk_count_actual == -1` fires as false positive on every cold boot.**
Trigger: Fresh install before first ingest run. The server starts, `count_rows()` returns 0
(empty table), NOT -1. The `-1` sentinel is set ONLY when `count_rows()` raises an exception
(`server/health.py:574: CORPUS_CHUNK_COUNT_ACTUAL.set(resources.startup_chunk_count)` where
`startup_chunk_count` defaults to -1 on exception). An empty table returns 0, not -1. This means
the false-positive risk is LOW: `actual == -1` specifically means the API failed, not "no data."
Mitigation: the `for: 10m` duration filters transient startup failures. **This is NOT a
significant false-positive risk** — empty table = 0, not -1.

**FM-3: `arxmcp_corpus_unindexed_rows > 0` fires during active ingest.**
Trigger: Ingest adds rows and calls `_create_indices` synchronously BEFORE `write_chunks`
returns (per m3's design — "ingest/store.py::_create_indices runs SYNCHRONOUSLY inside
write_chunks"). There is NO window where rows exist without a rebuilt index during normal
ingest. However, if a partial write crash occurs mid-ingest, unindexed rows could persist
until next startup. The `for: 1h` suppresses transient situations. Mitigation: the `for: 1h`
duration is exactly right here — no normal single ingest run lasts > 1 hour uninterrupted.

**FM-4: YAML structure error: duplicate `groups:` key.**
Trigger: Implementer adds rules by appending a second `groups:` block rather than appending
inside the existing one. PyYAML silently uses the LAST `groups:` key (Python dict behavior on
duplicate keys). `test_arxmcp_group_present` would then FAIL because the first group is
silently overwritten. `promtool check rules` would also flag this. Mitigation: read the full
file first; append to the existing `rules:` array under `groups[0]`.

**FM-5: `tests/test_alerts_yaml.py::test_alert_rule_shape` fails on missing `component` label.**
Trigger: New rules added without `component:` label. Current test at line 89 only checks for
`severity`, not `component`. So this test would PASS even if `component` is missing. However,
the operational inconsistency is observable: every existing rule has `component`, the new ones
don't. The adversary critic will likely flag this as a MEDIUM finding. Mitigation: add
`component: corpus` to both new rules.

**FM-6: `test_required_alerts_present` not updated — regression gap.**
Trigger: A future change removes `ArXMCPCorpusCountRowsFailed` or renames it. No test fails
because only `{ArXMCPDiskFull, ArXMCPDegradedMode, ArXMCPBackupStale}` are in the required
set. Mitigation: extend `test_required_alerts_present` to include the two new alert names —
this is within the implementer's judgment and matches the established pattern.

**FM-7: `arxmcp_corpus_unindexed_rows` gauge reports `-1` (index API unavailable).**
Trigger: The `arxmcp_corpus_unindexed_rows > 0` rule does NOT fire when the gauge is `-1`
(since `-1 > 0` is false). This is correct behavior — `-1` means "unknown," not "broken."
However, the expression `arxmcp_corpus_unindexed_rows > 0` silently misses the "API
unavailable" case. Mitigation: this is an accepted design tradeoff per m3's docstring: "-1 =
unavailable (index API raised, or no ANN index)." A separate alert for the `-1` case would
be premature; the existing `ArXMCPDegradedMode` covers broader startup failures.

---

## Recommendation

**Append both rules inside the existing `groups[0].rules:` array in `infra/prometheus/alerts.yml`.**
Shape each rule identically to existing rules — including `component: corpus` (not in AC but
matches every existing rule pattern). Use `summary` + `description` + `runbook_url` annotations
exactly as in the 5 existing rules. Additionally extend `test_required_alerts_present` to add
the two new alert names, preventing future silent removal.

The `for: 10m` for `ArXMCPCorpusCountRowsFailed` is correct — filters one-shot startup hiccups.
The `for: 1h` for `ArXMCPCorpusUnindexedRows` is correct — normal ingest completes its index
rebuild within the startup sequence; 1h filters any transient startup + rebuild window.

Rationale: (a) both gauge names are confirmed live in `server/health.py`; (b) both alert names
are confirmed absent from the existing file; (c) `runbook_url` is the canonical key; (d) the
`severity: critical` / `severity: warning` split is architecturally grounded in the WARN-not-
degraded decision from m3 (`count_rows` failure = correctness break; unindexed rows = perf only).

---

## Open questions

1. **Should `test_required_alerts_present` be extended?** The AC doesn't require it, but it's
   the right regression guard. Recommend: yes, add both names. Low-risk addition.

2. **`docs/ops/corpus-drift-runbook.md` is absent.** The `runbook_url` will 404 until m2 ships.
   The roadmap explicitly accepts this sequencing. If the implementer wants, they can ship m2
   first (the roadmap states both orders are fine). No blocking issue.

These questions have answers — implementation can proceed on the above recommendation without
waiting for resolution.

---

## External writes the implementation will require

None — this milestone is purely local. The only file changed is `infra/prometheus/alerts.yml`
(and optionally `tests/test_alerts_yaml.py` for the required-alerts extension). No git push,
no GitHub issue, no infra mutation.
