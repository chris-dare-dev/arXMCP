# Corpus-drift operator runbook

**Status:** PLACEHOLDER — full content lands in `corpus-integrity-completion-m2`.
**Created by:** `corpus-integrity-completion-m1` (rect F3 + IS1) — exists so the
`runbook_url` annotation on the two new corpus-integrity alert rules does not
resolve to a GitHub 404 during the gap between m1 and m2.

This file is **operator-readable now** but is intentionally thin until m2 ships
the full Symptom / Quick triage / Likely causes / Remediation / Escalation
sections.

---

## Alerts covered by this runbook

Both rules ship in `infra/prometheus/alerts.yml`
(`corpus-integrity-completion-m1`):

### `ArXMCPCorpusCountRowsFailed` (severity: critical, for: 10m)

**What it means.** The arXMCP server's startup `chunks_table.count_rows()`
call raised. The exposed Prometheus gauge `arxmcp_corpus_chunk_count_actual`
is set to `-1` (the canonical "count failed" sentinel; see
`server/health.py:115-120`). The marker-vs-actual reconciliation surfaced
by `GET /readyz` is unreliable as long as the gauge reports `-1`.

**Immediate triage (m1 minimum).**
1. Check the server logs for the `Resources.startup FM-2` error path
   (search for the `Resources.startup` event class).
2. Verify the LanceDB dataset at the configured `lancedb_path` is readable
   on disk (`ls -la $LANCEDB_PATH/_versions/`).
3. If the dataset is corrupt or missing, restore from the most recent
   restic backup per `docs/ops/backup-restore.md`.

### `ArXMCPCorpusUnindexedRows` (severity: warning, for: 1h)

**What it means.** The HNSW ANN index has one or more rows committed to the
chunks table without a successful index rebuild. The Prometheus gauge
`arxmcp_corpus_unindexed_rows` reports a positive value (see
`server/health.py:128-134`). ANN queries brute-force those rows — results
stay correct but get slower.

**Immediate triage (m1 minimum).**
1. Confirm the count by scraping `/metrics` and looking at
   `arxmcp_corpus_unindexed_rows`.
2. Re-run the ingest pipeline; `ingest/store.py::_create_indices` runs
   synchronously inside `write_chunks` and will rebuild the index.
3. If re-ingestion does not clear the gauge, check the LanceDB index API
   error stream and consider a manual `tbl.create_index(...)` per the
   LanceDB docs.

---

## Why this is a placeholder

The full runbook content (with operator-tested remediation procedures,
escalation paths, and rollback steps for the
`tools/notebook_reconcile_marker.py` CLI) ships in
`corpus-integrity-completion-m2`. That milestone authors the canonical
Symptom / Quick triage / Likely causes / Remediation / Escalation
sections following the pattern of the other 4 operator runbooks in this
directory (`failure-modes.md`, `backup-restore.md`, `drift-watchdog.md`,
`latexml-drift-runbook.md`).

m1 ships the alert rules; m2 ships the full content here. Both rules'
`runbook_url` annotation references this file path; this PLACEHOLDER
stops the GitHub 404 in the m1→m2 gap so an operator hitting an alert
during that window lands on a runnable next step (the Immediate triage
sections above) rather than a broken link.

## See also

- `infra/prometheus/alerts.yml` — the rule definitions
- `plans/corpus-integrity-completion-roadmap.md` — the parent epic
- `.claude/notes/capability-scouts/corpus-integrity-observability/` —
  the discovery work behind these alerts
- `docs/ops/backup-restore.md`, `docs/ops/drift-watchdog.md` — adjacent
  operator runbooks following the same structure m2 will adopt here.
