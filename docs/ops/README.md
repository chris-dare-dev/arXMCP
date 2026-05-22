# arXMCP operator runbook index

This is the single entry-point for operator runbooks. Each entry
covers one named failure or maintenance scenario with a consistent
4-part skeleton: **Symptoms → Detection → Steps → Verification**.

> If you came from a Prometheus alert's `runbook_url:` annotation
> for a specific failure mode, see the
> [Failure modes table](failure-modes.md) which catalogues all 9
> documented failure modes with the same Symptoms/Detection/
> Recovery/Verification structure inline.

The runbooks live in this directory (`docs/ops/`). Agent-internal
references and per-feature design docs live in
[`.claude/docs/`](../../.claude/docs/) per
[`CLAUDE.md` §1](../../CLAUDE.md).

---

## Failure and maintenance scenarios

| # | Runbook | When to fire |
|---|---|---|
| 1 | [server-crash recovery](server-crash.md) | The daemon exited / SIGSEGV'd / OOM-killed; bring the service back. |
| 2 | [ingestion-pause (disk-full origin)](failure-modes.md#disk-full) | A `ingest-paused` sentinel is on disk; reads still work but new papers stop landing. Today the only documented trigger is the disk-full handler (see #3); operator-initiated pause is a future scenario. |
| 3 | [disk-full handling](failure-modes.md#disk-full) | `arxmcp_disk_free_bytes < 10 GB` alert (`ArXMCPDiskFull`) fired. |
| 4 | [restore from backup](backup-restore.md) | A corpus or DB needs to be recovered from a restic snapshot. |
| 5 | [model swap](model-swap.md) | Upgrade the embedder (BGE-M3) or reranker (bge-reranker-v2-m3) to a new commit SHA. |
| 6 | [corpus-version rollback](corpus-rollback.md) | A bad `corpus_version` bump produced regressed nDCG@5; revert to N-1 via LanceDB MVCC. |
| 7 | [LaTeXML worker restart](latexml-restart.md) | A LaTeXML subprocess hung or LaTeXML output drift was detected. |
| 8 | [drift watchdog alert response](drift-watchdog.md) | `arxmcp_eval_ndcg5` regressed against the baseline; gate ingestion until the source is identified. |

---

## Related runbooks (operational cadence and one-off pipelines)

These cover scheduled operations and bulk one-time pipelines rather
than failure-driven scenarios; they live alongside this index for
discoverability:

- [`bulk-ingest-runbook.md`](bulk-ingest-runbook.md) — initial bulk
  ingest of the Academic Torrents corpus (E11_S01).
- [`delta-loop.md`](delta-loop.md) — nightly OAI-PMH delta harvest
  (E11_S02).
- [`re-embed-runbook.md`](re-embed-runbook.md) — partial re-embed
  after a chunker / embedder bump (E11_S03).
- [`cutover-runbook.md`](cutover-runbook.md) — 200K staging → active
  cutover activation + rollback (E11_S05).
- [`daily-ops-cadence.md`](daily-ops-cadence.md) — daily / weekly /
  quarterly cron schedule (E14_S04).
- [`parser-failure-review.md`](parser-failure-review.md) — weekly
  parser-failure triage workflow (E14_S04).
- [`latexml-drift-runbook.md`](latexml-drift-runbook.md) — LaTeXML
  version drift remediation (E10_S04).
- [`notebook-modes.md`](notebook-modes.md) — multi-notebook
  deployment topology (per-daemon vs per-call filter).
- [`failure-modes.md`](failure-modes.md) — catalogue of all 9
  documented failure modes (E14_S05; this index's #2 and #3 link
  into specific anchors in this file).

---

## Conventions

Every runbook follows the same 4-part skeleton so operators can
skim in any order:

- **Symptoms** — what the operator sees on the dashboard / in logs.
- **Detection** — the alert, log line, or metric that fires.
- **Steps** — the ordered actions to take, with code blocks where
  applicable.
- **Verification** — how to confirm the system is recovered.

If a runbook needs to deviate from this skeleton (e.g., the
existing `bulk-ingest-runbook.md` predates this convention), the
index entry calls that out explicitly.

---

## When you can't find a runbook

If you hit a failure mode not covered here:

1. Check `.claude/notes/08-security-observability-ops.md` § Failure
   modes table — the design constitution catalogues all 9 currently-
   documented modes.
2. If genuinely new, the post-incident task is to add a runbook
   here and back-link it from the alert's `runbook_url:`
   annotation in `infra/prometheus/alerts.yml`.
3. For incidents that span multiple subsystems, file an entry in
   `.claude/notes/deferred-work-tracker.md` so the gap is tracked
   even if not fixed immediately.
