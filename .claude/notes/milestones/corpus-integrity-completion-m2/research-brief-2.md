# Research Brief — corpus-integrity-completion-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T21:00:00Z

---

## In-codebase context

### Design constitution files that apply

- `08-security-observability-ops.md` — threat model + daily ops cadence. The two alerts
  cover corpus-integrity failure modes. Verbatim from §Failure modes:
  > "LanceDB corrupt on restart | Open fails | Fall back to previous dataset version via
  > `dataset.checkout(version=N-1)` … alert."
  The runbook sits at the intersection of failure modes 2 (LanceDB corruption) and the
  corpus-integrity observability sub-system added by the corpus-integrity-observability epic.

- CLAUDE.md §7 **stale entry**: "make ingest is a stub that exits 1" — **THIS IS WRONG**.
  `ingest/bulk_ingest.py` EXISTS and is the real E11_S01 bulk ingest orchestrator. The
  Makefile `ingest:` target runs `$(PYTHON) -m ingest.bulk_ingest $(ARGS)`. The CLAUDE.md
  §7 note predates E11 shipping. **The runbook's Remediation section for
  `ArXMCPCorpusUnindexedRows` MAY reference `make ingest` as a real working command.**

### Alerts from `infra/prometheus/alerts.yml`

The two alerts this runbook covers (verbatim from alerts.yml):

```yaml
- alert: ArXMCPCorpusCountRowsFailed
  expr: arxmcp_corpus_chunk_count_actual == -1
  for: 10m
  labels:
    severity: critical
    component: corpus
  annotations:
    runbook_url: "https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/corpus-drift-runbook.md"
```

```yaml
- alert: ArXMCPCorpusUnindexedRows
  expr: arxmcp_corpus_unindexed_rows > 0
  for: 1h
  labels:
    severity: warning
    component: corpus
  annotations:
    description: |
      ANN queries brute-force those rows; results stay
      correct but get slower. Re-run ingest to rebuild
      the index per the runbook.
```

Alert comment in alerts.yml (verbatim load-bearing):
> "The `-1` 'unknown' sentinel does NOT trip this rule (`-1 > 0` is false) — that case is
> covered by `ArXMCPDegradedMode`."

### `ArXMCPDegradedMode` relationship (load-bearing)

The runbook MUST NOT duplicate the LanceDB N-1 fallback path (corpus_corruption reason).
That case is covered by `ArXMCPDegradedMode` + `docs/ops/failure-modes.md#lancedb-corruption`.
The two m2 alerts cover a DISTINCT narrow scope:
1. `count_rows()` RAISED at startup (not LanceDB open failure) — gauge = -1
2. HNSW index has unindexed rows after write — gauge > 0

Verbatim from alerts.yml comment:
> "The above-tolerance drift case (gauge >= 0 but differs from the marker) is already
> covered by `ArXMCPDegradedMode` via `DegradedState('chunk_count_diverged')`; no
> duplicate rule is added here."

### `/readyz` body (verbatim from `server/health.py:282-292`)

```python
return JSONResponse(
    status_code=200,
    content={
        "status": "ready",
        "chunk_count": None if startup_count < 0 else startup_count,
        "marker_chunk_count": resources.corpus_info.chunk_count,
        ...
    },
)
```

The `chunk_count` key IS `application/health+json`-style (the IETF draft's `checks`
component pattern with `observedValue`). When `arxmcp_corpus_chunk_count_actual == -1`,
`GET /readyz` returns `"chunk_count": null` (not -1) — the sentinel is only observable
in Prometheus, not the health endpoint.

**CONFLICT flagged:** The m1 placeholder says "The marker-vs-actual reconciliation
surfaced by `GET /readyz` is unreliable as long as the gauge reports -1." This is
ACCURATE — when `chunk_count: null`, the comparison `chunk_count == marker_chunk_count`
is undefined. The runbook must state this clearly.

### `make reconcile` — what it actually does

The Makefile `reconcile:` target (lines 560-589):
- If server up + NOTEBOOK= set: POST to `/ui/api/notebooks/{slug}/reconcile-marker`
- If server up + no NOTEBOOK=: falls back to CLI (`python -m tools.notebook_reconcile_marker --shared`)
- If server down: runs CLI directly

The CLI (`tools/notebook_reconcile_marker.py`) verbatim exit-code contract:
```
Exit codes:
    0 — recount completed (drift may be zero on idempotent re-run)
    1 — operational failure (missing marker, malformed marker, LanceDB open failure)
```

CLI output on SUCCESS (verbatim from `_reconcile_one`):
```
reconcile-marker [shared]: version=42 before=150000 chunks / 3200 papers
  after=150000 chunks / 3200 papers drift_resolved=0
```

CLI output on FAILURE (writes to stderr): `ERROR: corpus-version.json at ... is malformed: ...`

**IMPORTANT: `make reconcile` only fixes corpus-version.json marker drift and
unindexed-rows issues indirectly via ingest. It does NOT fix `count_rows()` failures.**
For `ArXMCPCorpusCountRowsFailed`, the correct remediation is: stop server → inspect
LanceDB dataset → restore from backup if needed → restart.

### Doc placement constraint

`docs/ops/corpus-drift-runbook.md` is an existing operator-facing file referenced by
`README.md` and the alert's `runbook_url`. It EXISTS at that path (the m1 placeholder).
This milestone REPLACES its content. This is `docs/` (operator-facing), not `.claude/`.
The doc-placement rule (CLAUDE.md §1) is satisfied — `docs/ops/` is for user-facing
content. **No new `.md` files are created outside allowed locations.**

### README "Common tasks" section

**DOES NOT EXIST.** The README has a "## Operations" section (line 65) with a runbook
table, but NO "## Common tasks" section. The AC says to add a line to `README.md`
"Common tasks" — this means the implementer must determine whether to:
(a) add a new `## Common tasks` H2, or
(b) add to the `## Operations` section.

**Recommendation below picks (b)** — adding a new section contradicts CLAUDE.md §1
("what the project does, how to use it, its layout, hard constraints") and the
restriction that README is not the place for work-tracking. A one-liner in the
Operations table or below it is appropriate.

---

## Prior decisions and lessons

From git log, m1 landed 3 commits ago (`c58c19e`, `951d3f3`, `5a8c7f0`). Key lessons
from m1's critique (which created the placeholder runbook):

1. The placeholder file was added by `rect(tests,docs): close F1, F2, F3, IS1 from m1
   critique` — the IS1 finding specifically required the runbook placeholder to prevent
   GitHub 404 for the `runbook_url` annotation. m2's deliverable closes this gap.

2. From MEMORY.md entry `corpus-integrity-observability-e3 — sentinel-gauge-placement-rule`:
   "Startup-set gauges live in `server/health.py`." The `arxmcp_corpus_chunk_count_actual`
   and `arxmcp_corpus_unindexed_rows` gauges are both in `server/health.py` — cite
   `server/health.py` in the runbook's Detection section, not `server/metrics.py`.

3. From MEMORY.md entry `corpus-integrity-observability-m3 — warn-only-not-degraded-for-perf-issues`:
   "WARN+gauge is the right pattern when results remain CORRECT (just slower). Degraded/503
   is for CORRECTNESS regressions." The runbook must reinforce: ArXMCPCorpusUnindexedRows
   is WARNING (correctness preserved, perf impact only). Do NOT suggest calling the server
   degraded for unindexed rows.

4. From MEMORY.md entry `corpus-integrity-observability-m3 — lancedb-list-indices-api-verified`:
   "`tbl.list_indices()` … `IndexStatistics.num_unindexed_rows: int` is the field."
   `arxmcp_corpus_unindexed_rows` is set from `startup_unindexed_rows` cached at startup.
   Re-running `_create_indices` (via ingest) is the only automated fix — no direct
   `tbl.create_index()` CLI exists in this codebase.

---

## External sources

### Prometheus `runbook_url` — how operators receive it

The Prometheus alerting docs do not specify what Alertmanager does with `runbook_url` at
notification time. This is by design: `runbook_url` is a conventional annotation name
(adopted from Google SRE practices) but Alertmanager treats it as an opaque string.

**The actual delivery mechanism depends on the notification receiver template.**
The canonical behavior across common receivers:

- **Slack receiver:** The default Alertmanager Slack template renders `{{ .Annotations.runbook_url }}`
  as a URL in the message body. The operator clicks it manually. It is NOT auto-opened.
- **PagerDuty receiver:** Annotations are included in the incident details panel. The
  operator sees the URL as a clickable link in the PagerDuty UI.
- **Email receiver:** Annotations are included in the email body as plaintext or HTML link.

**Implication for runbook structure:** The `runbook_url` is a clickable link opened by
an operator who has just been paged or sees a Slack alert. This is a **2am-pager
runbook**. The operator has not already diagnosed the problem. Structure MUST lead with:
Quick triage FIRST (1-3 shell commands), not background explanation.

This is a firm recommendation: Quick triage before Likely causes. Background and
escalation paths come after. The m1 placeholder already follows this pattern (triage
before causes). The full m2 content must preserve it.

### IETF `application/health+json` (draft-inadarei-api-health-check)

The IETF draft defines `chunk_count` and `marker_chunk_count` as NON-canonical fields.
The spec defines the `checks` object with `observedValue`, `observedUnit`,
`componentType`, and `affectedEndpoints`. Project-custom keys like `chunk_count` and
`marker_chunk_count` are valid under "additional user-defined keys MAY be included."

The spec does NOT define `status: "ready"` — only `pass`, `fail`, `warn`. The project
uses its own status vocabulary for `/readyz`. The runbook should reference the actual
response body shape (verbatim from `server/health.py`) rather than citing the IETF draft
as an authority on these keys.

---

## Failure-mode analysis (7 scenarios)

The runbook MUST cover these scenarios:

### S1 — count_rows() raised at cold-corrupted LanceDB (CRITICAL alert)
**Trigger:** `chunks_table.count_rows()` raises `lance.LanceError` or `OSError` at startup.
**Gauge state:** `arxmcp_corpus_chunk_count_actual = -1`; `arxmcp_corpus_chunk_count_marker = N`
**Observable in `/readyz`:** `"chunk_count": null, "marker_chunk_count": N` — null signals
the anomaly without returning -1.
**Alert fires:** `ArXMCPCorpusCountRowsFailed` after 10m.
**Remediation:**
1. `curl http://127.0.0.1:7733/readyz` — confirm `chunk_count: null`
2. `ls -la var/arxmcp/index/lancedb/_versions/` — check the version directory exists
3. If corrupt: `make down` → restore per `docs/ops/backup-restore.md` → `make up`
4. If transient: `make down` + `make up` (restart clears the cached -1)
**Note:** `make reconcile` does NOT fix this — reconcile operates on the marker file,
not on LanceDB dataset open failures.

### S2 — Ingest crashed mid-write leaving unindexed rows (WARNING alert)
**Trigger:** `write_chunks` in `ingest/store.py` completed row writes but `_create_indices`
raised before completing.
**Gauge state:** `arxmcp_corpus_unindexed_rows > 0`
**Observable in `/readyz`:** `"status": "ready"` (no change — correctness preserved);
ANN queries brute-force unindexed rows silently.
**Alert fires:** `ArXMCPCorpusUnindexedRows` after 1h sustained.
**Remediation:** Re-run ingest from the same paper-id set with `make ingest
ARGS="--paper-ids-file=<last-batch-ids>"`. `ingest/store.py::_create_indices` runs
synchronously inside `write_chunks` and rebuilds the HNSW index.
**CAUTION:** `make reconcile` does NOT rebuild the index — it only recounts rows and
rewrites the marker. The unindexed-rows gauge is set at startup; a server restart after
successful ingest will confirm the fix.

### S3 — Operator manually edited or deleted corpus-version.json
**Trigger:** Operator edited `var/arxmcp/index/lancedb/corpus-version.json` (e.g.,
wrong chunk_count value, deleted to "force re-ingest").
**Gauge state:** `arxmcp_corpus_chunk_count_marker` diverges from `arxmcp_corpus_chunk_count_actual`
**Observable in `/readyz`:** `chunk_count != marker_chunk_count` — triggers
`DegradedState('chunk_count_diverged')` → `/readyz` 503 + `ArXMCPDegradedMode` fires.
**Note:** This case is covered by `ArXMCPDegradedMode`, NOT by the two m2 alerts. The
corpus-drift runbook should MENTION this case and cross-reference
`docs/ops/failure-modes.md#lancedb-corruption` but clarify the alert path.
**Remediation:** `make reconcile` — recounts live LanceDB rows and atomically rewrites
the marker with the correct value. Restart server to reload.

### S4 — marker MISSING (no previous ingest run, cold-clone deployment)
**Trigger:** `var/arxmcp/index/lancedb/corpus-version.json` does not exist.
**Gauge state:** Server startup logs WARN; `arxmcp_corpus_version` gauge = -1 (or 0);
`arxmcp_corpus_chunk_count_marker` = 0 (or not set).
**Observable in `/readyz`:** 503 (server not warm — `corpus_info is None`).
**Note:** `arxmcp_corpus_chunk_count_actual == -1` alert does NOT fire here if
`count_rows()` succeeds and returns 0 for an empty table. This is documented in
alerts.yml: "an empty table returns 0, not -1, so cold-clone deployments before the
first ingest do NOT trip this rule."
**Remediation:** Run `make ingest` to create the first corpus version.

### S5 — Concurrent `make ingest` + `make reconcile` race
**Trigger:** Operator runs `make reconcile` while `make ingest` is writing new chunks.
**Gauge state:** Reconcile opens the LanceDB at the version pinned in the EXISTING
marker (MVCC snapshot — concurrent-ingest-safe). It reads rows from version N, then
writes the marker for version N with correct counts. Ingest meanwhile writes version N+1.
**Result:** The marker reflects version N until the next ingest write updates it. This
is correct behavior — `reconcile` is MVCC-pinned and idempotent.
**Observable:** Reconcile stdout: `drift_resolved=0` (no drift at the snapshot version).
After ingest completes and writes a new marker, the counts will diverge again (correctly)
until the next reconcile or server restart.
**Remediation:** No operator action needed — the race is safe. Run `make reconcile`
again after ingest completes if the alert re-fires.

### S6 — `make reconcile` returns exit code 1 (operational failure)
**Trigger:** The marker file is malformed JSON, the version field is missing, or
the LanceDB recount itself raises an exception.
**Observable:** CLI prints to STDERR: `ERROR: corpus-version.json at ... is malformed: ...`
or `ERROR: LanceDB recount at ... failed: ...`. Exit code 1.
**Remediation:**
- If malformed marker: inspect `cat var/arxmcp/index/lancedb/corpus-version.json` to
  confirm corruption. Restore the marker from the latest restic snapshot or re-run
  `make ingest` to recreate it.
- If LanceDB recount failed: same recovery path as S1 (LanceDB corruption).
**The runbook must document expected output for both success (exit 0 + stdout) and
failure (exit 1 + stderr) paths.** Operators need to know what to look for.

### S7 — gauge -1 not clearing after restart (persistent count_rows failure)
**Trigger:** LanceDB dataset at `ARXMCP_LANCEDB_PATH` is pointing to a path that no
longer exists or whose permissions changed (e.g., after a filesystem remount or Docker
volume misconfiguration).
**Gauge state:** Persistent `arxmcp_corpus_chunk_count_actual = -1` across restarts.
**Observable:** Server logs `Resources.startup FM-2` error path each restart.
**Remediation:**
1. `echo $ARXMCP_LANCEDB_PATH` — confirm the env var is set correctly
2. `ls -la $ARXMCP_LANCEDB_PATH` — confirm the path exists and is readable
3. Check Docker volume mounts if running in container
4. Correct the path/permissions and restart

---

## Recommendation

**Brief stance: brevity-first, triage-at-top.** The `runbook_url` is a pager link. The
operator opening it at 2am has already seen the alert in Slack/PagerDuty. Lead with
Quick triage (2-3 commands). Keep Likely causes and Remediation concise. Escalation is
one paragraph.

**Pick: separate H2 sections for each alert.** The two alerts have DIFFERENT triage
paths (CRITICAL vs WARNING, different root causes, different remediation commands). A
single flat runbook mixes two distinct failure classes. Use:

```
## Alert: ArXMCPCorpusCountRowsFailed (severity: critical)
### Symptom / Quick triage / Likely causes / Remediation

## Alert: ArXMCPCorpusUnindexedRows (severity: warning)
### Symptom / Quick triage / Likely causes / Remediation

## Escalation
```

This differs from the AC's required `## Symptom` / `## Quick triage` flat structure.
**The implementer should follow the AC literally** (required H2 sections), not this
structural deviation, unless the adversary critic confirms the deviation is justified.
Use the AC's sections but within each section distinguish the two alert cases.

**On the README line:** Add `corpus-drift-runbook.md` to the existing `## Operations`
runbook table — NOT a new `## Common tasks` section. The AC literally says add a line
pointing to `make reconcile`; placing it in the operations table with a "Corpus marker
drift or unindexed-rows alert" trigger description is the minimal, coherent change. A
new `## Common tasks` H2 would violate CLAUDE.md §1's intent for README scope.

**On `make ingest` for unindexed rows:** `make ingest` is NOT a stub (CLAUDE.md §7 is
stale). Reference it in the Remediation section as the real remediation command.

---

## Open questions

1. **AC literal H2 structure vs alert-split structure:** The AC requires exactly these
   H2 sections: `## Symptom`, `## Quick triage`, `## Likely causes`, `## Remediation`,
   `## Escalation`. This is a flat single-runbook structure. The research brief
   recommends per-alert H2 substructure because the two alerts have different triage.
   **The implementer must choose:** follow AC literally (flat H2) or adopt per-alert
   nesting. Recommendation: follow AC literally to pass the acceptance check cleanly;
   distinguish the two alert cases within each section using H3 subheadings.

2. **README "Common tasks" section literal vs Operations table:** The AC says `README.md`
   "Common tasks" section but this section does not exist. The implementer must create it
   (a new H2) or add to the existing `## Operations` section. If a new H2 is created,
   confirm it does not violate CLAUDE.md §1's README scope restriction. This is a genuine
   ambiguity — researcher-1 may have a different reading.

---

## External writes the implementation will require

None — this milestone is purely local.

Files modified:
- `docs/ops/corpus-drift-runbook.md` — content replacement (existing file)
- `README.md` — one-line addition

Both are local edits. No `git push`, no `gh` commands, no infra mutations. The
three-commit pattern (feat + rect + chore) lands on `main` directly per CLAUDE.md §4.1.
