# E14_S04 Research Brief 1 — In-codebase context

## 1. In-codebase context

### 1.1 The "Daily ops cadence" verbatim (`.claude/notes/08-security-observability-ops.md` §, lines 252-267)

```
00:00 UTC   OAI-PMH delta harvest starts
00:15       New paper IDs queued for /e-print/ fetch
00:15-04:00 Fetch + parse + chunk + embed new papers
04:00       LanceDB write new corpus version (new dataset version via MVCC append)
04:05       Update corpus-version.json atomically (no symlink swap; see E04_S02 in roadmap/E04-vector-store.md)
04:10       Daily snapshot (restic) starts
05:00       Snapshot done; metrics report mailed (if configured)

Continuous   INSPIRE-HEP per-paper enrichment (15 rps)
Monthly      OpenAlex bulk diff + Kùzu graph rebuild
Weekly       Parser-failures review (human-in-the-loop)
Quarterly    Restore drill + dependency upgrades
```

Note the **drift between brief and note**: the brief says delta is 00:00, watchdog is 04:30. Note 08 says delta is 00:00, restic 04:10, "metrics report mailed" 05:00 — **no explicit watchdog UTC time in note 08**. The actual landed watchdog cron (`ops/cron/arxmcp-watchdog.sh` header comment) is `30 2 * * *`, and the actual landed delta timer (`ops/systemd/arxmcp-delta.timer`) is `OnCalendar=*-*-* 02:00:00`. **The note's "00:00 UTC" is aspirational; production is 02:00 UTC delta / 02:30 UTC watchdog / 03:30 UTC backup.** E14_S04 should reconcile this in `docs/ops/daily-ops-cadence.md`.

### 1.2 What already lives where — critical finding: brief's `infra/cron/` is **wrong**

`infra/` contains only `infra/README.md` (placeholder for E14 docker-compose) and `infra/observability/` (E14_S03 Phoenix profile). **No `infra/cron/`.**

The **actual** location of cron + systemd assets is `ops/`:

```
ops/cron/
  arxmcp-delta.sh         (E11_S02 — uv run python -m ingest.oai_delta)
  arxmcp-watchdog.sh      (E11_S04 — uv run python -m ops.watchdog_eval)
  arxmcp-backup.sh        (E11_S05 — restic + sentinel)
  latexml-drift-check.sh  (E10_S04)
ops/systemd/
  arxmcp-delta.{service,timer}    (E11_S02)
  arxmcp-backup.{service,timer}   (E11_S05)
```

Note the **gap**: the watchdog has a `.sh` but **no `.service` / `.timer`**. The brief should land those (or be explicit that systemd parity for E11_S04 is being filled here). And **the brief's `infra/cron/` deliverable list is mis-located** — they belong in `ops/cron/` and `ops/systemd/` to match the established convention. Recommendation: **place new files at `ops/cron/` and `ops/systemd/`** and document the brief drift in the implement-summary. Do **not** introduce a parallel `infra/cron/` tree.

### 1.3 `tools/parser_failures_report.py` — does NOT exist

```
$ ls tools/
README.md  __init__.py  __pycache__  arxiv_fetch.py  curate_seed.py
fetch_one_paper.py  fetch_seed.py  seed-papers.txt  validate_eval_fixtures.py
```

The brief asserts "(authored in E02_S06)" but **no E02_S06 milestone exists** (E02 stops at S05). The script is a phantom dependency.

**Recommendation:** write a minimal `tools/parser_failures_report.py` as part of E14_S04. It is straightforward: iterate `var/arxmcp/ops/parser-failures/*.{log,jsonl}`, group rows by `paper_id` and failure-reason regex, render an ISO-week markdown report with counts + top-10 failing-paper table. The producer files already exist:

```
ingest/chunker.py::CHUNK_LOG_PATH          → parser-failures/chunk.log    (TSV)
ingest/preamble.py                         → parser-failures/preamble.log (TSV)
ingest/embedder.py                         → parser-failures/embed.log    (TSV)
tools/fetch_seed.py::LOG_PATH              → parser-failures/seed.log     (TSV)
ingest/oai_delta.py                        → parser-failures/delta.jsonl  (JSONL)
ingest/re_embed.py                         → parser-failures/re-embed.jsonl
ingest/bulk_ingest.py                      → parser-failures/bulk.jsonl
```

Mixed TSV (early ingest stages) + JSONL (E11 stages). The reporter must read both. **Tab-separated, 4 columns: `paper_id<TAB>status<TAB>duration_s<TAB>reason`** per existing `chunk.log`. JSONL rows are arbitrary keyed dicts; minimum keys `paper_id` and `reason` per ingest module convention.

### 1.4 Metric families to scrape (verbatim names)

Per-tool (`server/observability/metrics.py`, E14_S01):

- `arxmcp_request_total{tool,status}` — Counter
- `arxmcp_request_latency_seconds{tool}` — Histogram (P50/P95/P99 via `histogram_quantile`)
- `arxmcp_request_inflight{tool}` — Gauge
- `arxmcp_result_bytes{tool}` — Histogram

Embedder/reranker:

- `arxmcp_embed_calls_total{model,outcome}`, `arxmcp_embed_latency_seconds{model}`
- `arxmcp_rerank_calls_total{model,outcome}`, `arxmcp_rerank_latency_seconds{model}`

Cache (`server/metrics.py`, label **is `tier` not `layer`**):

- `arxmcp_cache_lookups_total{tier}`, `arxmcp_cache_hits_total{tier}`,
  `arxmcp_cache_evictions_total{tier}`, `arxmcp_cache_bytes{tier}`,
  `arxmcp_cache_payload_skips_total{reason}`

**Mismatch with note 08:** note 08 documents `{layer}`, but `server/metrics.py` ships `{tier}` (string-typed: `"1"`, `"2"`, `"3"` via `TIER_1/2/3` constants, line 289-291). The report must scrape `tier` to match reality. (Note 08 needs a follow-up update; out of scope for E14_S04.)

Sentinel-source gauges (E14_S01, scrape-time hydrated):

- `arxmcp_latexml_drift_fixtures`, `arxmcp_eval_ndcg5{corpus_version}`,
  `arxmcp_eval_quarantine_active`, `arxmcp_delta_timeout_active`,
  `arxmcp_backup_last_success_timestamp_seconds`, `arxmcp_backup_status{state}`

**Ingestion throughput** (brief asks for "papers ingested, chunks written"): the metric families `arxmcp_ingest_papers_processed_total` / `arxmcp_ingest_chunks_written_total` are **documented in note 08 but NOT implemented in code** (grep on `server/` + `ingest/` returns zero hits). The daily report should derive throughput from `var/arxmcp/ops/delta-status.json` or sentinel files written by `ingest/oai_delta`, **not** from `/metrics`. Alternative: count rows in the day's `parser-failures/delta.jsonl` and parse the success/failure column. **Recommendation:** read `delta-status.json` (whatever sentinel `oai_delta` writes) if present; otherwise show "n/a — ingest metrics not yet wired".

The 7 tools (from `server/tools.py::ALL_TOOLS`): `search_papers`, `get_chunk`, `find_equation`, `get_definitions`, `find_lemma_by_name`, `get_paper`, `cite_neighbors`.

### 1.5 Tools/ script conventions

Existing scripts (`tools/fetch_seed.py`, `tools/curate_seed.py`) all share:

- `#!/usr/bin/env python3` shebang
- `from __future__ import annotations`
- Module docstring with usage examples
- `argparse` with explicit `--dry-run` where applicable
- `REPO_ROOT = Path(__file__).resolve().parent.parent`
- Exit 0 / non-zero with one-line stderr on failure

Match this exactly. `uv run python tools/daily_metrics_report.py --dry-run` per CLAUDE.md §4.5.

### 1.6 Quarterly drill reminder — wire to existing `ops/restore_drill.sh`

`ops/restore_drill.sh` already exists (E11_S05). Its invocation: `cd <repo> && ops/restore_drill.sh`. The quarterly reminder shell script should write a markdown reminder file to `var/arxmcp/ops/reminders/quarterly-drill-<YYYY-QN>.md` containing: (a) link to `docs/ops/backup-restore.md`, (b) the exact `ops/restore_drill.sh` invocation, (c) the sentinel-flag path `var/arxmcp/ops/restore-drill-passed.flag` that `cutover.py` later reads. Detection of "7 days before next quarter mark" is simple date math against `date -u +%Y%m%d`.

### 1.7 Doc placement is `docs/ops/` — confirmed precedent

`docs/ops/` already houses 7 E11/E10 ops runbooks (backup-restore, bulk-ingest-runbook, cutover-runbook, delta-loop, drift-watchdog, latexml-drift-runbook, re-embed-runbook). New runbooks `docs/ops/daily-ops-cadence.md` and `docs/ops/parser-failure-review.md` fit the precedent. **Do NOT put them under `.claude/docs/`** — those are agent-internal references; the ops runbooks are operator-facing and per CLAUDE.md §1 the `docs/ops/` tree is grandfathered.

### 1.8 Tests — pattern for tool scripts

`tests/test_fetch_seed.py`, `tests/test_restore_drill.py`, `tests/test_oai_delta.py`, `tests/test_cutover.py`, `tests/test_watchdog_eval.py` all exist. Pattern: pure-unit tests with `tmp_path`, no network, mock subprocess. The `--dry-run` path is the natural test surface. Acceptance criterion 1 ("dry-run produces a valid markdown report against a fixture `/metrics` response") implies a `tests/fixtures/metrics-sample.txt` Prometheus text-exposition fixture; ship one alongside.

### 1.9 Makefile — no daily-report target today

`make help` lists `bootstrap/test/eval/up/ingest/delta/re-embed/watchdog/cutover`. **Recommendation:** add `make daily-report` and `make parser-failures-report` for operator parity. Mirror the `watchdog` block style: ARGS-forwarding + python version assertion.

## 2. Prior decisions and lessons

- **`uv` resolution + `flock` check** — every cron wrapper in `ops/cron/` enforces the same UV_BIN + flock-presence preamble. Copy it verbatim into the daily-metrics + weekly-parser-failures wrappers. The `ARXMCP_UV` env override is established convention.
- **`flock -n` on lockfiles under `var/arxmcp/ops/.<name>.lock`** — every cron uses this; daily-metrics + parser-failures must too (no concurrent runs).
- **Sentinel-file pattern** — restic, watchdog, delta all write `var/arxmcp/ops/<x>-status.json` or `.flag`. The daily report could itself write `var/arxmcp/ops/daily-report-status.json` for self-monitoring.
- **`HANDOFF.md`** — no prior ops-cadence deferral; this is fresh ground.
- **systemd timer `RandomizedDelaySec=300`** (E11_S02 pattern) — keep it; avoids thundering-herd if multiple machines run the same crons.
- **`Documentation=https://github.com/chris-dare/arXMCP/blob/main/...`** trailer — both existing timers include it; do the same.

## 3. External sources

External-lane researcher 2 covers Prometheus query syntax + `histogram_quantile`, `smtplib` SSL/TLS contract, ISO-week date math. Stub pointers only:

- Prometheus text-exposition format spec (rendering of histograms via `_bucket{le="X"}`)
- Python stdlib `email.mime.multipart` + `smtplib.SMTP_SSL` for the optional `MAIL_TO` path
- `datetime.date.isocalendar()` returns `(year, week, weekday)` — straightforward for the weekly-report filename `parser-failures-<YYYY>-W<NN>.md`

## Open questions

1. **`tools/parser_failures_report.py` existence:** does NOT exist; "authored in E02_S06" is a phantom dependency (E02 stops at S05). **Recommendation: expand E14_S04 scope to author this script.** It is ~150 LOC of Python (TSV+JSONL readers, dict aggregation, markdown render). Cheaper to write it now than to land a cron pointing at a missing file.
2. **`infra/cron/` vs `ops/cron/`:** the brief says `infra/cron/`; the established convention is `ops/cron/` + `ops/systemd/` (4 existing wrappers, 2 existing service/timer pairs). **Recommendation: use `ops/cron/` and `ops/systemd/`**; document the brief drift in the implement-summary. Do **not** create a parallel tree.
3. **cron `.cron` fragment vs systemd `.timer`:** ship BOTH per brief. The repo's deployment story is "macOS dev + Linux production" (per `arxmcp-delta.sh` comments) — operators on Linux use systemd, on macOS use cron. Existing precedent: delta + backup ship both, watchdog ships only `.sh`. E14_S04 should land `.timer` parity for watchdog while it's here.
4. **`var/arxmcp/ops/daily-reports/` vs `var/arxmcp/ops/reports/`:** the brief uses both. **Recommendation:** `daily-reports/<YYYY-MM-DD>.md` for the daily report, `reports/parser-failures-<YYYY>-W<NN>.md` for the weekly. Two separate directories — daily is high-volume (~365/yr), weekly is low-volume (~52/yr), keep them separate so `ls` is readable.
5. **Alert thresholds:** note 08 has none; existing runbooks give concrete numbers. Pull from there: `regression_pct > 10%` (drift-watchdog.md §4 line 79), `now() - arxmcp_backup_last_success_timestamp_seconds > 86400` (backup-restore.md alert rules), `arxmcp_eval_quarantine_active > 0` (E11_S04 critique). For latency/error-rate: propose **P99 > 2.5s sustained 5min**, **error rate > 1% sustained 5min** as defaults — anchored to the highest histogram bucket below the 5s timeout.
6. **SMTP:** stdlib `smtplib.SMTP_SSL` is sufficient (delivery is opt-in, single-message). **Recommendation: stdlib only.** No new deps.

## External writes the implementation will require

Zero beyond local commits and the standard `git push origin main` cadence (CLAUDE.md §4.1: single-user, lands on `main`). No GitHub-API calls, no cron-registration on the user's actual host (the wrappers ship as files for the operator to enable).
