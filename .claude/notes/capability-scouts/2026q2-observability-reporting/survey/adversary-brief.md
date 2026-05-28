# Adversary Brief — Capability Scout 2026q2-observability-reporting

**Scout run:** 2026q2-observability-reporting
**Critic role:** Current-State Adversary
**Date:** 2026-05-28
**Scope:** Observability & Reporting — logging, metrics, operator-facing reporting, data-integrity / marker-vs-table reconciliation

---

## 1. Executive Summary

The motivating bug is confirmed: `ingest/store.py::write_chunks` (lines 865–907) writes `corpus-version.json` with `chunk_count=len(chunks)` and `paper_count=len({c.paper_id for c in chunks})` derived from the **in-flight batch**, not from the LanceDB table's actual ground truth. Since `bulk_ingest.py::ingest_one_paper` and `re_embed.py` call `write_chunks` once per paper, each successive call overwrites the marker with a single-paper count — producing `chunk_count=106` (one paper) on a table that actually holds 10,298 rows. The server logs and exposes this wrong value at startup and via `CORPUS_VERSION_GAUGE`, and nothing in the pipeline ever checks the recorded value against the table's real row count. This is a HIGH gap (not CRITICAL only because the server's retrieval correctness is unaffected — LanceDB's actual rows are fine; it is purely the metadata that lies). Four compounding HIGH/MEDIUM gaps surround it: the daily report openly admits ingestion throughput is unmeasured (no emitter for the `arxmcp_ingest_*` families named in note-08), the startup log emits misleading marker-sourced counts without a ground-truth cross-check, `store-stats.jsonl` per-call chunk counts are also per-batch (same root cause), and the `JsonFormatter` exists but is not wired as the default output handler so the "structured JSON logs" promise of note-08 §Logging is architecturally unrealized in production.

---

## 2. Critical Gaps

None identified. The motivating bug is serious but the server's retrieval pipeline operates correctly — the metadata discrepancy does not cause wrong query results or data loss, only operator/agent misinformation.

---

## 3. High Gaps

### H1 — Corpus-version marker records per-batch counts, not ground-truth table counts

**Gap name:** Per-batch chunk_count / paper_count in corpus-version.json

**Severity:** HIGH

**What comparable systems / SOTA expects:**
Any production vector-store deployment (Weaviate, Qdrant, Milvus, LanceDB's own `count_rows()` primitive) treats the persisted corpus-size metadata as a derived, ground-truth-verified quantity, not an in-memory approximation of the last write batch. OpenTelemetry's semantic conventions for database observability (semconv `db.client.connection.pool.*`, analogous in-process metrics) require that gauges reflect actual state, not "what we think we just wrote."

**What arXMCP has today:**
`ingest/store.py:865-907` — `write_chunks` computes `paper_count = len({c.paper_id for c in chunks})` and `chunk_count = len(chunks)` from the in-memory `chunks` list that was passed in THIS CALL, then passes them to `write_corpus_version_marker`. `bulk_ingest.py::ingest_one_paper` (line 319) calls `write_chunks(chunks, embed_record, ...)` once per paper; `re_embed.py` does the same. Each call overwrites `corpus-version.json` with the counts from one paper's batch (typically ~100 chunks), not from the cumulative table. CLAUDE.md §7 does not document this as a known stub.

**What a credible v1 fill-in would look like:**
After `_create_indices(tbl)` returns and `tbl.version` is resolved, call `tbl.count_rows()` and `len(tbl.to_arrow().column("paper_id").unique().to_pylist())` (or an equivalent bounded scan) to derive ground-truth `chunk_count` and `paper_count` from the actual LanceDB table state. Pass these to `write_corpus_version_marker` instead of `len(chunks)` / `len({c.paper_id for c in chunks})`. The LanceDB `count_rows()` call is O(1) — it reads fragment metadata, not row data. The unique-paper_id scan is O(N) but bounded by corpus size; for a bulk ingest at the staging path this is an acceptable post-write cost. An alternative: track a cumulative counter in the bulk-ingest loop and pass it explicitly to the final `write_corpus_version_marker` call only (writing the marker once per full-corpus run, not per paper).

**Architecture-lock interaction:**
No conflict with CLAUDE.md §4.7 hard rules. The fix is inside `ingest/store.py` which is writer-only (no server imports). LanceDB MVCC discipline (§4.7 / `ingest/store.py` docstring "MVCC handshake") is unaffected — the corpus-version `version` integer stays as the post-index LanceDB version; only the derived `chunk_count` / `paper_count` fields change. BP1/BP2 cache keys use only `version`, not `chunk_count` (confirmed: `server/corpus.py:76`, `notes/07-multi-agent-caching.md` §"Tier 1" key formula), so this fix does not invalidate any cached prompt or tool result.

**Why this hasn't been fixed yet:**
The `write_chunks` function was designed as a single-call atomic writer (E04_S01) where the caller knows everything about the batch. In the seed-corpus era (50 papers in one or a few batches) the per-batch counts were close enough to the table totals to be undetectable. The bug only manifests at scale when `bulk_ingest.py` calls `write_chunks` once-per-paper — a calling pattern that postdates the function's original contract. E11_S01 added the bulk loop without auditing the marker-write semantics.

---

### H2 — Ingestion throughput absent from /metrics and daily report

**Gap name:** No ingestion throughput metrics emitter

**Severity:** HIGH

**What comparable systems / SOTA expects:**
Every production ingest pipeline (Elasticsearch bulk API, Kafka, Pinecone upsert endpoints) exposes real-time throughput counters. The design note `08-security-observability-ops.md:130-135` explicitly names four families: `arxmcp_ingest_papers_processed_total{parser,outcome}`, `arxmcp_ingest_paper_duration_seconds{parser,quantile}`, `arxmcp_ingest_chunks_written_total`, `arxmcp_ingest_oai_pmh_lag_seconds`. These are part of the system's own stated specification.

**What arXMCP has today:**
None of these families exist in `server/metrics.py`, `server/observability/metrics.py`, or any ingest module. The daily report (`tools/daily_metrics_report.py:385-395`) openly acknowledges this with the comment: _"Papers ingested + chunks written are not yet exposed via `/metrics`; the families `arxmcp_ingest_papers_processed_total` and `arxmcp_ingest_chunks_written_total` are named in note 08 but no emitter exists yet."_ The JSONL ops files (`store-stats.jsonl`, `ingestion.log`) are the only records, but they are unreachable from the `/metrics` endpoint and the daily report does not read them. The `store-stats.jsonl` contains per-call `chunk_count` which is also wrong (same root cause as H1).

**What a credible v1 fill-in would look like:**
Emit `arxmcp_ingest_papers_processed_total{parser,outcome}` and `arxmcp_ingest_chunks_written_total` as process-level counters inside `bulk_ingest.py::run_bulk_ingest` (one increment per paper outcome). The ingest process is separate from the server process, so these counters cannot be exposed at `/metrics` at runtime — the right bridge is the same sentinel-file pattern already used for drift, quarantine, and backup: after each bulk run write a structured JSON summary to `var/arxmcp/ops/ingest-summary.json`, and have the server's `refresh_sentinel_metrics` hook read it at scrape time to populate Prometheus gauges. This is the established local-first cross-process signal channel (E14_S01 `server/health.py:300-400`).

**Architecture-lock interaction:**
No conflicts. The sentinel-file pattern is explicitly the chosen cross-process bridge for this architecture. No new heavy infra required.

**Why this hasn't been fixed yet:**
E14_S04 (daily report) explicitly deferred this to a future milestone, stating it requires a design decision about how to bridge the ingest-vs-server process boundary. That decision was made implicitly by E14_S01 (sentinel files) but never connected to the ingest side.

---

### H3 — Startup log reports marker-sourced chunk_count without ground-truth cross-check

**Gap name:** Unchecked startup corpus-size log

**Severity:** HIGH

**What comparable systems / SOTA expects:**
Production MCP servers and comparable retrieval systems (Weaviate, Qdrant) validate that startup metadata matches the actual data layer during readiness probing. The standard pattern is: read the version-pinned metadata, then verify it against the live table's `count_rows()`, log a WARNING or refuse to open `/readyz` when the skew exceeds a threshold (e.g., >1% difference). PostgreSQL's `pg_stat_user_tables` / `reltuples` versus `count(*)` discrepancy is a well-known class of silent stale-statistics bugs; the resolution is to add a reconciliation check at startup.

**What arXMCP has today:**
`server/resources.py:337-345` logs `chunk_count=%d` and `paper_count=%d` sourced exclusively from `corpus_info` (which is deserialized from the marker file, carrying the wrong per-batch values from H1). The `CORPUS_VERSION_GAUGE` (set at `server/health.py:251`) records the marker `version` integer correctly, but no `/metrics` gauge exposes the marker-recorded `chunk_count` vs. the live table's `count_rows()` — so the discrepancy is invisible to Prometheus alert rules. The startup log is the only operator-visible output of these counts, and it is misleading.

**What a credible v1 fill-in would look like:**
After opening the LanceDB table (`Resources.startup` step 2), call `chunks_table.count_rows()` and compare it against `corpus_info.chunk_count`. If the absolute difference exceeds a configurable threshold (suggested: 5%), log a WARNING with both values. Expose a `arxmcp_corpus_chunk_count_actual` Gauge (set to `count_rows()`) alongside `arxmcp_corpus_chunk_count_marker` (set to `corpus_info.chunk_count`) so an alert rule can fire on `abs(actual - marker) / actual > 0.05`. This doubles as a startup integrity check for H1 and as a live correctness signal post-fix.

**Architecture-lock interaction:**
`count_rows()` is already called at `Resources.startup:476` for the reranker warmup path — the addition is cheap. The BM25Phase startup at line 407 already does `chunks_table.to_arrow().column("chunk_id").to_pylist()` which is a full table materialization; calling `count_rows()` before that for the reconciliation check adds zero marginal I/O.

**Why this hasn't been fixed yet:**
The discrepancy was undetectable on the 50-paper seed corpus (single write = table total). Startup logging was designed when ingest and marker-write were co-located in a single batch; the assumption that "the marker says what the table holds" was never tested at scale.

---

## 4. Medium Gaps

### M1 — store-stats.jsonl per-call counts are per-batch, not cumulative

**Gap name:** store-stats.jsonl misleading chunk_count field

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
Ops audit logs (e.g., Elasticsearch `_cat/shards`, LanceDB's own `describe_index_stats`) record cumulative state, not per-operation deltas, when the field name is `chunk_count` (an aggregate) rather than `chunks_written_this_call` (a delta). The `WriteStats.chunk_count` field (ingest/store.py:188-197) is documented as "per-call summary" but the field name suggests an absolute count.

**What arXMCP has today:**
`ingest/store.py:865-866` — `WriteStats(chunk_count=len(chunks), ...)` records the per-call batch size. For a per-paper bulk ingest, each JSONL line shows `chunk_count=106` (one paper), never the corpus total. The ops log is therefore only useful as a per-paper write trace, not as a cumulative corpus audit trail. No reader in `tools/` reads `store-stats.jsonl` to produce any report. CLAUDE.md §7 does not flag this.

**What a credible v1 fill-in would look like:**
Rename the field to `chunks_written_this_call` in `WriteStats.to_dict()` to make the per-call semantics explicit, OR add a separate `table_chunk_count` field sourced from `tbl.count_rows()` (which requires H1 to be fixed first). Either approach eliminates the ambiguity. Changing the field name is a one-line rename with a test update.

**Architecture-lock interaction:**
`store-stats.jsonl` is a write-once ops artifact; renaming a field in `to_dict()` does not touch the server, BP1, or cache keys. Any external consumer that parses the JSONL would need to be updated — but there are no such consumers in the codebase (grep confirms zero reads of `store-stats.jsonl` outside the writer).

**Why this hasn't been fixed yet:**
The field naming was established in E04_S01 where a single batch WAS the corpus. Not revisited when bulk-ingest changed the call pattern.

---

### M2 — JsonFormatter exists but is not the default log output format

**Gap name:** Structured JSON logging promised but not wired by default

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
12-factor apps (https://12factor.net/logs) and any production observability stack (ELK, Loki, Cloud Logging) require machine-parseable JSON log output as the default. Design note `08-security-observability-ops.md:207-215` specifies required fields on every log line: `timestamp`, `level`, `logger`, `mcp.session_id`, `event`, `msg`. The `JsonFormatter` (`server/observability/logging_setup.py:78`) implements this spec.

**What arXMCP has today:**
`server/observability/logging_setup.py:22-23` explicitly states: _"The formatter is NOT installed by default — the redaction works regardless of the output format, and changing the default stdout shape is out of scope for an audit milestone."_ `server/main.py` calls `configure(cfg)` which installs `RedactionFilter` but uses Python's default text formatter. Log lines like `Resources.startup: pinning corpus_version=3 (chunk_count=106, ...)` are emitted as human-readable text strings, not as JSON objects with the `mcp.session_id`, `event`, and `msg` fields specified in note-08. This means neither the misleading `chunk_count` value (H3) nor other startup anomalies have machine-parseable fields that an alert pipeline could filter on.

**What a credible v1 fill-in would look like:**
Introduce an `ARXMCP_LOG_FORMAT` env var (values: `"text"` / `"json"`, default `"json"` for production, `"text"` for interactive dev). When `"json"`, `configure(cfg)` attaches `JsonFormatter` to the root handler. This is a single conditional in `configure()` and matches the existing `ARXMCP_LOG_LEVEL` pattern. No new dependency required.

**Architecture-lock interaction:**
No CLAUDE.md §4.7 conflicts. The `configure()` function is already the single logging setup entry point. Changing the default to JSON would change test output; tests that grep log lines by human-readable text would need updating (but there are few such tests — most use the Prometheus metric counters, not log assertions).

**Why this hasn't been fixed yet:**
E13_S08 explicitly scoped it out as "out of scope for an audit milestone." The deferral was documented but never picked up.

---

### M3 — Daily report reads /metrics but has no marker-vs-table reconciliation section

**Gap name:** Daily report blind to corpus-size divergence

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
Ops dashboards for search/retrieval systems (Elasticsearch's cluster health API, Weaviate's `/v1/meta`, Qdrant's `/collections/{name}`) expose both the indexed count and a freshness/staleness indicator in their daily/periodic reports. Any equivalent of arXMCP's daily report would include a "corpus integrity" section: marker-recorded vs. ground-truth row count, discrepancy %, last full reconciliation timestamp.

**What arXMCP has today:**
`tools/daily_metrics_report.py::render_report` (lines 304-449) includes sections for requests, latency, cache, embedder/reranker, sentinels — but no corpus-integrity section. It reads `arxmcp_corpus_version` from `/metrics` (via `server/health.py:CORPUS_VERSION_GAUGE`) but not `paper_count` or `chunk_count` because those are not exposed as Prometheus gauges at all. The "Ingestion throughput" section (lines 384-395) explicitly says these metrics are absent. There is no automated reconciliation step anywhere in the daily ops cadence (`08-security-observability-ops.md:254-267`).

**What a credible v1 fill-in would look like:**
Add a `## Corpus integrity` section to `render_report` that reads (a) the `arxmcp_corpus_chunk_count_actual` and `arxmcp_corpus_chunk_count_marker` Prometheus gauges proposed in H3, (b) the `arxmcp_corpus_version` gauge, and (c) shows a red-flag indicator when `abs(actual - marker) > threshold`. This section should render as a one-row table: "| Metric | Marker | Actual | Status |". This is a ~30-line addition to `daily_metrics_report.py` and is entirely local-first (reads from the same `/metrics` endpoint the report already uses).

**Architecture-lock interaction:**
Depends on H3 (new gauges) being implemented first. No hard-rule conflicts.

**Why this hasn't been fixed yet:**
The gap was not visible until the H1 root cause was exposed. Before this scout run, the marker and table counts were assumed to be consistent.

---

### M4 — No test asserts marker chunk_count / paper_count matches table ground truth

**Gap name:** Missing reconciliation invariant test

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
Any integration test suite for a vector store with a versioned metadata marker should include a test that writes N papers, verifies the marker, then calls `table.count_rows()` and asserts the marker's `chunk_count` equals the table's row count. This is the minimum regression guard for the H1 class of bug.

**What arXMCP has today:**
`tests/test_store.py` (inferred from CLAUDE.md's test count of 2100) tests `write_chunks` and `write_corpus_version_marker` independently. There is no test that calls `ingest_one_paper` (or `run_bulk_ingest`) over multiple papers and then verifies that the final `corpus-version.json::chunk_count` equals `tbl.count_rows()`. The H1 bug would have been caught by such a test.

**What a credible v1 fill-in would look like:**
In `tests/test_bulk_ingest.py` (or equivalent), write a test that runs `ingest_one_paper` for 3 synthetic papers (using the existing `_graph_helpers.py`-style fixture machinery), then opens the staging LanceDB table and asserts `json.loads((staging_path / "corpus-version.json").read_text())["chunk_count"] == staging_tbl.count_rows()`. This test is ~25 LOC and requires no new fixtures or model downloads. It would fail TODAY (before H1 is fixed) and pass after.

**Architecture-lock interaction:**
No conflicts. Test-only; does not touch server or BP1 cache keys.

**Why this hasn't been fixed yet:**
The test was never written because the per-batch calling pattern was never the target of a specific integration test at the marker level. E11_S01 added a smoke test for one-paper ingest but did not add a multi-paper marker-reconciliation assertion.

---

### M5 — /metrics exposes no corpus-size ground-truth gauges

**Gap name:** Corpus ground-truth metrics absent from /metrics

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
Pinecone (`describe_index_stats`), Qdrant (`/collections/{name}`), Weaviate (`/v1/meta`) all expose current indexed vector count and object count as live health metrics. The `/metrics` scrape is the operator's primary corpus-health signal in arXMCP.

**What arXMCP has today:**
`server/health.py:92-97` exposes `arxmcp_corpus_version` (the LanceDB version integer). `server/metrics.py` does not expose `chunk_count` or `paper_count` as Prometheus gauges. The `CORPUS_VERSION_GAUGE` is the only corpus-identity signal at `/metrics`. `server/observability/metrics.py` adds request, latency, and failure-mode gauges but no corpus-size gauge. Operators cannot write an alert rule of the form "alert when chunk_count drops >5% vs. baseline."

**What a credible v1 fill-in would look like:**
Add `CORPUS_CHUNK_COUNT_MARKER_GAUGE` and `CORPUS_CHUNK_COUNT_ACTUAL_GAUGE` to `server/health.py` (mirroring `CORPUS_VERSION_GAUGE`). Set the marker gauge once in `refresh_metrics_from_singleton_state` from `resources.corpus_info.chunk_count`. Set the actual gauge from `chunks_table.count_rows()` — but since `count_rows()` involves I/O, this should be done at startup only and cached, not at every scrape. The two gauges then enable alert rules on divergence. This is ~15 LOC.

**Architecture-lock interaction:**
Adding Prometheus gauges does not touch the `tools/list` byte-stable hash (`EXPECTED_TOOL_SCHEMA_SHA256`) or `EXPECTED_BP1_SHA256` — those pin tool schema and prompt-prefix bytes, not `/metrics` content. No conflicts.

**Why this hasn't been fixed yet:**
The corpus_version gauge was added in E14_S01 as the identity signal; the counts were considered derivable from the marker. The marker-vs-ground-truth discrepancy (H1) was not known at that time.

---

## 5. Low Gaps

### L1 — ingestion.log uses TSV format instead of JSON

**Gap name:** ops/ingestion.log is TSV, not structured JSON

**Severity:** LOW

**What comparable systems / SOTA expects:**
Consistent structured-log format (JSON) across all machine-written ops artifacts. TSV is harder to parse reliably when field values contain tabs or newlines.

**What arXMCP has today:**
`ingest/bulk_ingest.py:155-169` — `_log_progress` writes tab-separated text (`f"{timestamp}\tpaper={paper_id}\ttotal={...}\tok={...}\tfail={...}\t..."`). All other ops artifacts (`store-stats.jsonl`, `parser-failures/bulk.jsonl`, `re-embed-state.json`, `backup-status.json`) use JSON.

**What a credible v1 fill-in would look like:**
Replace the TSV format with `json.dumps(record)` matching the shape of `store-stats.jsonl`. One-line change in `_log_progress`; update tests that parse the TSV format.

**Architecture-lock interaction:**
No conflicts.

**Why this hasn't been fixed yet:**
Cosmetic gap; TSV is human-readable in `tail -f` usage which may have been the design motivation.

---

### L2 — Daily report has no corpus_version section

**Gap name:** Daily report does not surface corpus_version

**Severity:** LOW

**What comparable systems / SOTA expects:**
Any daily ops report for a versioned retrieval system includes the current corpus version and the last-update timestamp.

**What arXMCP has today:**
`tools/daily_metrics_report.py::render_report` reads from `/metrics` but never renders `arxmcp_corpus_version` or `arxmcp_process_start_time_seconds` into the markdown output. These values are present in the Prometheus exposition but not surfaced in the report.

**What a credible v1 fill-in would look like:**
Add a two-row table in the report header: `| corpus_version | N |` and `| server uptime | Xh |`. ~8 LOC.

**Architecture-lock interaction:**
None.

**Why this hasn't been fixed yet:**
The report template was built around request / cache / sentinel metrics. Corpus identity was not explicitly scoped into the daily report.

---

### L3 — JsonFormatter is missing mcp.session_id and event fields from note-08 spec

**Gap name:** JsonFormatter missing required log-line fields

**Severity:** LOW

**What comparable systems / SOTA expects:**
The project's own design note (`08-security-observability-ops.md:207-215`) specifies `mcp.session_id` and `event` as required fields on every applicable log line.

**What arXMCP has today:**
`server/observability/logging_setup.py:78-120` — `JsonFormatter` emits `timestamp`, `level`, `logger`, `message` (and any extra kwargs passed to `logger.info(..., extra={...})`). It does NOT inject `mcp.session_id` automatically unless the caller passes it in `extra`. There is no context-var or request-local propagation of session_id into the log record.

**What a credible v1 fill-in would look like:**
Use a `contextvars.ContextVar` for `mcp.session_id` set at request entry in the MCP dispatcher and read by `JsonFormatter.format()`. This is the standard pattern for structured-log context injection in async Python (used by structlog and similar). ~20 LOC.

**Architecture-lock interaction:**
No conflicts. Logging is orthogonal to BP1/BP2, tool schema, and cache keys.

**Why this hasn't been fixed yet:**
M2 (JsonFormatter not installed by default) means the missing fields are not yet operational. The gap is latent until M2 is resolved.

---

## 6. What arXMCP Does Well

- **Sentinel-file cross-process bridge is solid and already battle-tested.** The `refresh_sentinel_metrics` / `_read_capped` pattern (`server/health.py:300-400`) is a clean, bounded, and safe mechanism for bridging ingest-process metrics into the server's Prometheus surface. All E14_S01 sentinel types (drift, quarantine, delta-timeout, backup) correctly use it.
- **Prometheus metric registry is well-organized and complete for the request path.** `server/observability/metrics.py` provides `REQUEST_COUNTER`, `REQUEST_LATENCY`, `REQUEST_INFLIGHT`, `RESULT_BYTES` with correct histogram bucket choices, per-tool labels, and test-reset helpers. This covers the serving path comprehensively.
- **Atomic marker write pattern is correct.** `ingest/store.py::write_corpus_version_marker` uses PID+UUID tmpfile + `os.replace` for POSIX-atomic writes, matching the canonical pattern from `ingest.preamble._write_preamble_json`. The **mechanism** for writing the marker is sound; only the **values** are wrong (H1).
- **Backup / restore observability is well-implemented.** `BACKUP_LAST_SUCCESS_GAUGE`, `BACKUP_STATUS_GAUGE`, and the `_BACKUP_STATES` exclusive-cell pattern give operators a complete Prometheus-side view of backup health, including the `unknown` catch-all bucket for future state strings.
- **Scrape-time size cap on sentinel files.** `_read_capped` at 64 KB (`server/health.py:85`) prevents a runaway cron from OOMing the server at scrape time. This is a detail that most local-first systems miss entirely.
- **RedactionFilter + JsonFormatter exist and are correctly separated.** The redaction (`server/observability/log_filter.py`) is installed unconditionally regardless of output format. The JSON formatter is available for future activation. The security-vs-format separation is architecturally clean.

---

## 7. Themes

The dominant theme across H1–M5 is **"write-path metadata diverges silently from ground truth because no layer computes derived aggregates from the actual data store."** The marker, the ops log, the startup log, and the daily report all source their corpus-size numbers from the in-memory batch at write time rather than from a post-write table scan — a coherent class of bugs rooted in a single architectural assumption (single-batch = full corpus) that broke when E11 introduced per-paper bulk ingest.

A secondary theme is **"the observability infrastructure for the ingest pipeline was specified (note-08 §Metrics) but never implemented."** The `arxmcp_ingest_*` metric families are named in the design note and referenced in the daily report as absent — a deferred stub that has now survived E11, E13, and E14 without being addressed. The sentinel-file bridge pattern from E14_S01 provides a ready mechanism to close this without new heavy infrastructure.

A third theme is **"structured logging is incomplete."** `JsonFormatter` is implemented but not wired; `ingestion.log` uses TSV; `mcp.session_id` context propagation is absent. The observability spec in note-08 §Logging describes a fully structured log surface that does not exist at runtime today.
