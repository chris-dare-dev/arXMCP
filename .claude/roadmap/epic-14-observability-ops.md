# E14 — Observability & Operations

**Epic dependencies:** E07, E11.

**Goal:** stand up the full observability + ops surface from `08-security-observability-ops.md`. Prometheus metrics on `/metrics`, OpenTelemetry tracing exported to a configurable endpoint, Phoenix as the v1 default for retrieval-quality eyeballing, structured JSON logging to stdout, daily ops runbooks, on-disk failure-mode handlers. Some metric scaffolds land inline in earlier epics; this epic completes the surface and adds the operational glue.

**Effort:** 1–2 weeks.

**References:** `08-security-observability-ops.md` § Observability, § Failure modes and graceful degradation, § Daily ops cadence; `06-mcp-server-design.md` § Health and readiness.

---

### E14_S01 — `/metrics` endpoint with all server-side counters

**Description.** Expose the full set of server-side metrics from `08-security-observability-ops.md` § Metrics on a single `/metrics` endpoint in Prometheus exposition format.

**Acceptance criteria.**
- [ ] `arxmcp_request_total{tool, status}`, `arxmcp_request_latency_seconds{tool}`, `arxmcp_request_inflight{tool}`, `arxmcp_result_bytes{tool}` all exposed.
- [ ] Cache metrics from E08 surfaced: `arxmcp_cache_lookups_total{layer}`, `arxmcp_cache_hits_total{layer}`, `arxmcp_cache_evictions_total{layer}`, `arxmcp_cache_bytes{layer}`.
- [ ] Embedder/reranker metrics: `arxmcp_embed_calls_total{model, outcome}`, `arxmcp_embed_latency_seconds{model}`, `arxmcp_embed_singleflight_dedup_total`, `arxmcp_rerank_calls_total{model, outcome}`.
- [ ] Test: hitting each tool produces sensible metric increments.
- [ ] `/metrics` returns valid Prometheus text format (validated by `promtool check`).

**Dependencies.** E07_S08, E08_S08.

**Complexity.** M.

**Labels.** `area:observability`, `kind:infra`.

---

### E14_S02 — OpenTelemetry tracing with one span per JSON-RPC request

**Description.** Per `08-security-observability-ops.md` § Tracing — emit one span per JSON-RPC request with child spans for embed, vector-search, rerank, summarize. Span attributes per the note: `mcp.session_id`, `mcp.tool_name`, `arxmcp.cache_layer_served`, `arxmcp.corpus_version`, `arxmcp.k`, `arxmcp.agent_role`.

**Acceptance criteria.**
- [ ] OTel SDK initialized at server startup; OTLP exporter pointed at `ARXMCP_OTEL_ENDPOINT`.
- [ ] Every tool handler creates a parent span; embedder/reranker/summarizer create child spans.
- [ ] All documented attributes set on the parent span.
- [ ] `agent_role` is read from a request-side parameter (added to tool args via the orchestrator) — documented but not required.
- [ ] Test: a recorded span trace shows the expected hierarchy and attributes.
- [ ] Documented in `docs/observability/tracing.md`.

**Dependencies.** E07_S08.

**Complexity.** M.

**Labels.** `area:observability`, `kind:infra`.

---

### E14_S03 — Phoenix integration for retrieval-quality views

**Description.** Per `08-security-observability-ops.md` § Recommended export targets — Phoenix is the v1 default for retrieval-quality eyeball checks. Run Phoenix locally in Docker; route OTel spans for retrieval calls there.

**Acceptance criteria.**
- [ ] `infra/observability/phoenix-compose.yml` runs Phoenix locally.
- [ ] OTel exporter routes retrieval spans to the Phoenix collector.
- [ ] Phoenix UI shows queries, top-k retrievals, scores, and reranker output.
- [ ] Documented startup procedure in `docs/observability/phoenix.md`.
- [ ] Phoenix is opt-in (separate compose profile).

**Dependencies.** E14_S02.

**Complexity.** M.

**Labels.** `area:observability`, `kind:infra`.

---

### E14_S04 — Structured JSON logging with required fields

**Description.** Per `08-security-observability-ops.md` § Logging — one line per event in JSON. Required fields: `timestamp` (ISO 8601 UTC), `level`, `logger`, `mcp.session_id`, `request_id`, `event`, `msg`. Sensitive fields at DEBUG only (E13_S08 enforces redaction).

**Acceptance criteria.**
- [ ] `server/observability/logging.py::configure()` sets up structlog (or equivalent) with the required field set.
- [ ] All log lines are valid JSON; one event per line.
- [ ] Default log target is stdout (12-factor).
- [ ] Test: a sample tool call produces log lines containing all required fields.
- [ ] Documented in `docs/observability/logging.md`.

**Dependencies.** E07_S09.

**Complexity.** S.

**Labels.** `area:observability`, `kind:infra`.

---

### E14_S05 — Failure-mode handlers from the table in `08-security-observability-ops.md`

**Description.** Per `08-security-observability-ops.md` § Failure modes and graceful degradation, implement the documented detection + response for each failure: hosted embedder outage → fall back to local; LanceDB corrupt on restart → fall back to previous version; OOM from large result → enforce caps (already in E06_S07); reranker slow cold start → pre-warm; LaTeXML hang → subprocess timeout (E02_S02); singleflight deadlock → try/finally (E08_S04); disk full → block ingestion; OAI-PMH 503 → exponential backoff (E11_S02); per-paper 503 → backoff (E11_S03).

**Acceptance criteria.**
- [ ] LanceDB-corruption fallback: on `dataset.checkout()` failure, server logs error, swaps the symlink to the prior version, and warns. Test with a synthetic corruption.
- [ ] Reranker pre-warm: model is loaded and a dummy inference run during readiness check (already part of E07_S07; add explicit warm-up).
- [ ] Disk-full detection: a Prometheus alert rule on free space; ingestion paused on hit (block at the queue level). Reads continue.
- [ ] Hosted-embedder outage fallback: tag results with `degraded=true` so reranker can deprioritize cross-model hits.
- [ ] Documented in `docs/ops/failure-modes.md` with a table mapping each note row to its implementation.

**Dependencies.** E07_S07, E07_S08, E11_S05.

**Complexity.** L.

**Labels.** `area:observability`, `area:server`, `kind:infra`.

---

### E14_S06 — Daily metrics report

**Description.** Per `08-security-observability-ops.md` § Daily ops cadence — "05:00 metrics report mailed (if configured)." Generate a daily markdown report summarizing requests served, cache hit rates, ingestion stats, parser-failure counts. Email is optional; the report file is canonical.

**Acceptance criteria.**
- [ ] `tools/daily_metrics_report.py` reads Prometheus metrics + parser-failure logs and produces a markdown report at `var/arxmcp/ops/daily-reports/<date>.md`.
- [ ] Sections: requests served, P50/P95/P99 latency by tool, cache hit rates per layer, ingestion throughput, parser failure counts (linking to the E02_S06 weekly report).
- [ ] Optional email sender via `MAIL_*` env vars (off by default).
- [ ] Cron schedule documented; runs at 05:00 UTC after E11_S07's daily delta completes.
- [ ] Test: synthetic metrics produce a stable, deterministic report.

**Dependencies.** E14_S01, E12_S06.

**Complexity.** S.

**Labels.** `area:observability`, `kind:infra`.

---

### E14_S07 — Weekly parser-failures report cron

**Description.** Per `08-security-observability-ops.md` § Daily ops cadence — "Weekly: parser-failures review (human-in-the-loop)." Wire the report script from E02_S06 to a weekly cron and document the review procedure.

**Acceptance criteria.**
- [ ] Cron entry runs `tools/parser_failures_report.py` weekly (Sundays 06:00 UTC).
- [ ] Report destination: `var/arxmcp/ops/reports/parser-failures-<week>.md`.
- [ ] `docs/ops/parser-failure-review.md` describes the human review workflow: triage common failure patterns, file fixes against the parser layer.
- [ ] Test: cron entry validated as syntactically correct.

**Dependencies.** E02_S06.

**Complexity.** S.

**Labels.** `area:observability`, `kind:infra`.

---

### E14_S08 — Quarterly restore drill cron-reminder

**Description.** Per `08-security-observability-ops.md` § Daily ops cadence — "Quarterly: restore drill + dependency upgrades." This is process not code, but ship a cron-reminder script that creates a calendar/issue reminder so the drill doesn't get skipped.

**Acceptance criteria.**
- [ ] `tools/quarterly_drill_reminder.sh` writes a reminder file with the runbook link 7 days before the next quarter mark.
- [ ] Cron entry committed.
- [ ] Documented in `docs/ops/quarterly-cadence.md`.
- [ ] First reminder fires successfully in dry-run mode.

**Dependencies.** E12_S09.

**Complexity.** S.

**Labels.** `area:observability`, `kind:infra`.

---

### E14_S09 — Cache hit-ratio dashboard

**Description.** Build a small Grafana dashboard (or equivalent) over the `arxmcp_cache_*` metrics. Useful for operational visibility into multi-agent fan-out behavior.

**Acceptance criteria.**
- [ ] `infra/observability/grafana-dashboard.json` defines panels for cache hit ratio per layer (Tier 1, 2, 3, summary, query_embed, chunk_embed).
- [ ] Includes panels for embedder singleflight dedup count and rerank latency.
- [ ] Dashboard committed; provisioning config in `infra/observability/grafana-provisioning.yml`.
- [ ] Optional Grafana docker-compose profile to run it.

**Dependencies.** E14_S01.

**Complexity.** S.

**Labels.** `area:observability`, `kind:infra`.

---

### E14_S10 — Ops runbook index

**Description.** Consolidate the operational runbooks into a single index document under `docs/ops/`. Each link covers one named scenario from `08-security-observability-ops.md` (server crashed, ingestion paused, disk full, restore from backup, model swap, schema migration).

**Acceptance criteria.**
- [ ] `docs/ops/README.md` lists all runbooks with one-line summaries.
- [ ] At least these runbooks exist: server-crash recovery, ingestion-pause recovery, disk-full handling, restore-from-backup (links to E12_S09), model swap (links to chunker version bumping in E03_S07), corpus version rollback (atomic symlink revert per E05_S07).
- [ ] Each runbook has a "symptoms / detection / steps / verification" section.
- [ ] Runbooks linked from the top-level README.

**Dependencies.** E12_S09, E14_S05.

**Complexity.** M.

**Labels.** `area:observability`, `kind:research`.

---

### E14_S11 — Optional Langfuse hookup for orchestrator-side tracing

**Description.** Per `08-security-observability-ops.md` § Recommended export targets — "Langfuse if/when the agent orchestrator becomes part of this repo." Today the orchestrator may live in user code; ship documentation for how to hook orchestrator-side traces to Langfuse so end-to-end visibility is achievable.

**Acceptance criteria.**
- [ ] `docs/observability/langfuse-orchestrator.md` shows how a Claude-API caller can wrap their tool-using agent and ship traces to Langfuse.
- [ ] Reference snippet uses Langfuse Python SDK with the canonical pattern.
- [ ] Documented as opt-in; not part of the server's mandatory deps.

**Dependencies.** E08_S10.

**Complexity.** S.

**Labels.** `area:observability`, `kind:research`.

---

### E14_S12 — API spend metrics for hosted-model fallbacks

**Description.** Per `08-security-observability-ops.md` § Spend (when using API embedders for query-time) — `arxmcp_api_spend_usd_total{provider, agent_role}`. Hosted-API spend tracking for the optional Voyage query-time path AND for the Haiku summary generator (E08_S07).

**Acceptance criteria.**
- [ ] Spend counter incremented after each hosted-API call with the documented per-call cost.
- [ ] Per-provider, per-agent-role labels.
- [ ] Daily report (E14_S06) surfaces top spend categories.
- [ ] Test: a fixture spend event increments the counter correctly.

**Dependencies.** E14_S01, E08_S07.

**Complexity.** S.

**Labels.** `area:observability`, `area:cache`.

---
