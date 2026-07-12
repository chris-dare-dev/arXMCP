---
project: arxmcp
type: doc
tags:
- project/arxmcp
- type/doc
- authorship/agent-generated
authorship: agent-generated
---

# Failure modes and graceful degradation

This runbook is the operator's reference for every documented
failure mode of the arXMCP server. The 9 modes below mirror the
table in [`.claude/notes/08-security-observability-ops.md`](../../.claude/notes/08-security-observability-ops.md)
§"Failure modes and graceful degradation". E14_S05 implemented
detection + recovery for the modes flagged ✅ below; modes
flagged 📋 are documented behavior that has been shipped in
prior milestones.

The Prometheus alert rules at
[`infra/prometheus/alerts.yml`](../../infra/prometheus/alerts.yml)
fire on each detection signal. Operators land here from each
alert's `runbook_url:` annotation.

---

## Summary table

| # | Failure mode | Detection | Recovery | Alert | Status |
|---|---|---|---|---|---|
| 1 | [Hosted-embedder outage](#hosted-embedder-outage) | HTTP 4xx/5xx, timeout | Fall back to local BGE-M3; tag `degraded=true` | `ArXMCPDegradedMode` | ✅ E14_S05 |
| 2 | [LanceDB corruption on restart](#lancedb-corruption) | Manifest read error at startup | Fall back to corpus_version N-1; `/readyz` 503 | `ArXMCPDegradedMode` | ✅ E14_S05 |
| 3 | [MCP OOM from large result](#mcp-oom) | Memory pressure | Hard cap k≤50, body 256 KB | — | 📋 E06_S04 |
| 4 | [Reranker slow cold start](#reranker-cold-start) | Readiness probe fails | Pre-warm dummy inference at lifespan | — | ✅ E14_S05 |
| 5 | [LaTeXML hang](#latexml-hang) | Subprocess timeout | Kill; mark paper as parser-failure; continue | — | 📋 E02_S02 |
| 6 | [Singleflight deadlock (defensive)](#singleflight-deadlock) | (defensive) | Always pop inflight key in try/finally | — | 📋 E03_S03 |
| 7 | [Disk full](#disk-full) | `arxmcp_disk_free_bytes < 10 GB` | `ingest-paused` sentinel; reads continue | `ArXMCPDiskFull` | ✅ E14_S05 |
| 8 | [OAI-PMH endpoint 503](#oai-pmh-503) | HTTP retry exhausted | Pause delta with exponential backoff (max 1h) | — | 📋 E11_S02 |
| 9 | [arxiv.org per-paper 503](#arxiv-per-paper-503) | HTTP retry exhausted | Pause fetcher; queue for retry next cycle | — | 📋 E01_S01 |

---

## Hosted-embedder outage

**What.** When `ARXMCP_QUERY_EMBED_PROVIDER=voyage` is set and the
hosted API call fails (HTTP 4xx/5xx, timeout, auth error, rate
limit), the server falls back to the in-process BGE-M3 embedder
and stamps `degraded=true` + `degraded_reasons:
["hosted_embedder_outage"]` on every result in the response.

**Detection.** `arxmcp_hosted_embed_fallback_total{provider}`
counter increments on every fallback event. The first fallback in
a process emits a WARN log; subsequent fallbacks are silent (read
the counter for the rate). The `ArXMCPDegradedMode` alert fires
when `arxmcp_degraded_mode_active{reason="hosted_embedder_outage"} == 1`.

**Recovery.** Investigate the hosted provider (Voyage status
page, API key, rate limit). The local BGE-M3 path is fully
functional and serves results; the only operator-facing impact
is the `degraded=true` tag and the slight quality difference
between BGE-M3 and the hosted model. Once the hosted path
recovers, the next request flips back automatically.

**v1 note.** The Voyage path is currently a STUB that always
raises `_HostedEmbedderUnavailable`. The fallback wrapper exists
so the contract is testable; full Voyage HTTP integration is a
separate ticket. Today only `ARXMCP_QUERY_EMBED_PROVIDER=local`
serves real hosted-provider traffic.

---

## LanceDB corruption

**What.** When the server starts and `open_table("chunks")` (or
the version-pinned `checkout()`) raises an exception from the
union `(lance.LanceError, OSError, RuntimeError, ValueError)`,
`server.corpus.open_chunks_table_with_fallback` retries at
`corpus_version - 1`. If that succeeds, the server serves
requests with `degraded.reason = "corpus_corruption"` and
`/readyz` returns 503 with `{"status": "degraded", "reason":
"corpus_corruption", "fallback_version": N-1, ...}`.

If both the live tip AND N-1 fail to open, the server REFUSES to
start (the lifespan handler raises `RuntimeError(
"corpus_corruption_unrecoverable")` and uvicorn exits). The
operator must restore from the most-recent restic snapshot.

**Detection.** Startup log: `Resources.startup: LanceDB OPENED IN
DEGRADED MODE`. `/readyz` returns 503 (vs 200 healthy / 503
not_ready during startup window). The `ArXMCPDegradedMode` alert
fires on `arxmcp_degraded_mode_active{reason="corpus_corruption"} == 1`.

**Recovery.**

1. Stop the server.
2. Inspect the live LanceDB version directory at
   `${ARXMCP_DATA_DIR}/index/lancedb/_versions/<v>.manifest`.
   Verify the manifest is intact (compare file size + checksum
   against the previous version).
3. If the live tip is genuinely corrupt, run
   `ops/restore_drill.sh` to validate the most-recent restic
   snapshot still restores cleanly. Then perform a full restore
   per [`docs/ops/backup-restore.md`](backup-restore.md)
   §"Restore drill".
4. Restart the server; `/readyz` should flip to 200.

**MVCC fallback dependency.** The N-1 fallback works because
LanceDB's MVCC keeps prior version directories on disk
indefinitely. Confirm that `ingest/store.py` does NOT call
`dataset.cleanup_old_versions()` — see
[`docs/ops/backup-restore.md`](backup-restore.md) §"Risks" for
the version-dir vs restic-prune note.

---

## MCP OOM

**What.** A handler returning >256 KB of `structuredContent` is
rejected at the response middleware (`server.main.BodySizeCapMiddleware`,
E06_S04). The hard cap on tool input `k <= 50` is enforced by
the per-tool schema in `server.tools` (E06_S03). These caps
prevent the long-tail OOM from a single handler.

**Detection.** Operator sees a 413 response from `/mcp`. The
`RETRIEVAL_CAP_REJECTIONS_COUNTER` Prometheus counter
(E08_S04) increments per tool.

**Recovery.** No server-side action. The orchestrator request
that breached the cap must re-request with a smaller `k` or
accept the result truncation.

---

## Reranker cold start

**What.** The BGE-reranker-v2-m3 cross-encoder takes 0.5-2s on
CPU for the first inference. Without warm-up, the first user
request pays this cost. E14_S05 D3 adds an explicit dummy
inference at lifespan startup: ten chunks from the live corpus
are run through the reranker BEFORE `/readyz` opens, so the
operator's first real request hits a warm model.

**Detection.** The `Resources.startup: reranker warmed via
10-chunk dummy inference` log line. `/readyz` blocks until the
warm-up completes.

**Recovery.** None required — the warm-up is automatic. If the
warm-up fails (broad except in `Resources.startup`), the server
logs WARN and continues — the first real request pays the cold
cost as a fallback.

---

## LaTeXML hang

**What.** When `latexmlc` hangs on a malformed source archive,
the ingest pipeline kills the subprocess after a per-paper
timeout, records a parser-failure row in
`var/arxmcp/ops/parser-failures/chunk.log`, and continues with
the next paper.

**Detection.** The weekly parser-failures report
([`docs/ops/parser-failure-review.md`](parser-failure-review.md))
shows the failure pattern. Sustained per-paper timeouts indicate
a LaTeXML version drift — see
[`docs/ops/latexml-drift-runbook.md`](latexml-drift-runbook.md).

---

## Singleflight deadlock

**What.** Defensive only. The `server.query_encoder._inflight`
dict could theoretically retain a never-completed entry; the
discipline of `try/finally` around the pop guards against it.
No production occurrence; covered by
`tests/test_query_encoder.py::test_inflight_popped_on_exception`.

---

## Disk full

**What.** `shutil.disk_usage(${ARXMCP_DATA_DIR})` is checked at
every Prometheus scrape (E14_S05 D4). The
`arxmcp_disk_free_bytes` gauge is the alert source. When free
drops below 10 GB, the server writes
`${ARXMCP_DATA_DIR}/ops/ingest-paused` with reason `disk_low`;
the delta cron + `ingest.oai_delta.main` short-circuit and exit
0. Read operations are unaffected.

When free climbs back above 15 GB (hysteresis — avoids
threshold-flap), the server auto-clears the sentinel if it owns
it (the sentinel JSON's `reason` field is checked: only
`reason=disk_low` is auto-cleared; operator-written sentinels
survive).

**Detection.** `ArXMCPDiskFull` Prometheus alert fires after
5 minutes of sustained low-disk. Operator-facing daily report at
`var/arxmcp/ops/daily-reports/<date>.md` includes the
`arxmcp_disk_free_bytes` gauge in the Sentinels table.

**Recovery.**

1. Identify the disk consumer: `du -sh ${ARXMCP_DATA_DIR}/*`.
   Common culprits: LanceDB MVCC version dirs (no
   `cleanup_old_versions()` in v1 — see backup-restore.md),
   parser-failure logs (`var/arxmcp/ops/parser-failures/`),
   Phoenix SQLite (`var/arxmcp/observability/phoenix/` —
   configurable retention is 14 days).
2. Free space. The sentinel auto-clears at 15 GB free.
3. Manual override: `python -m tools.ingest_sentinel clear`
   removes the sentinel unconditionally (useful for an operator
   who has confirmed disk has been freed faster than the next
   `/metrics` scrape will detect).

**Manual pause for maintenance.** Use
`python -m tools.ingest_sentinel write --reason=maintenance`
before any operator work that should pause ingest (kernel
patches, hardware replacement, etc.). The auto-clear logic
ONLY clears `reason=disk_low` sentinels, so the manual
maintenance pause survives auto-recovery.

---

## OAI-PMH 503

**What.** The OAI-PMH endpoint returns 503 under heavy load.
`ingest/oai_delta.py` retries with exponential backoff (max 1
hour); if all retries exhaust, the delta loop exits with a
non-zero status and the cron mailer surfaces the failure.

**Detection.** The delta-loop progress sentinel records the
failure. The next day's delta run picks up from the last
successful timestamp.

**Recovery.** Wait. arXiv operations resolves outages on the
order of hours, and the daily delta cron re-runs at 02:00 UTC.

---

## arxiv per-paper 503

**What.** A per-paper `/e-print/` fetch returns 503. The fetcher
queues the paper_id for retry on the next delta cycle; the
current cycle continues with the remaining papers.

**Detection.** Parser-failure log (`seed.log` or `delta.jsonl`).
Sustained 503s for the same paper_id across multiple weekly
reports indicate a broken upstream tarball; skiplist the paper
per
[`docs/ops/parser-failure-review.md`](parser-failure-review.md).

---

## Backup + restore

The restic backup + restore-drill surface is shipped under
[`docs/ops/backup-restore.md`](backup-restore.md). E14_S05 does
not modify the surface; it documents the LanceDB version-dir
dependency that the corruption-fallback (failure mode 2) relies
on. See
[`backup-restore.md`](backup-restore.md) §"Risks" for the
clarifying paragraph.

---

## See also

- [`daily-ops-cadence.md`](daily-ops-cadence.md) — daily/weekly/
  quarterly schedule + alert thresholds
- [`backup-restore.md`](backup-restore.md) — restic backup +
  restore drill
- [`drift-watchdog.md`](drift-watchdog.md) — eval-regression
  watchdog
- [`parser-failure-review.md`](parser-failure-review.md) — weekly
  triage workflow
- [`latexml-drift-runbook.md`](latexml-drift-runbook.md) —
  LaTeXML version drift recovery
- [`.claude/notes/08-security-observability-ops.md`](../../.claude/notes/08-security-observability-ops.md)
  §"Failure modes and graceful degradation" — design rationale
- [`infra/prometheus/alerts.yml`](../../infra/prometheus/alerts.yml)
  — alert rule definitions
