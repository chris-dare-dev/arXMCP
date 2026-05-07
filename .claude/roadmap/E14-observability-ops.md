# E14 — Observability, Operations, and Deferred Work

Epic dependencies: E06_S01 (server skeleton with `/metrics` route stub), E07_S08 (logging scaffolding), E11_S05 (MVCC corpus swap live — daily delta can run), E13_S08 (log redaction filter)

Goal: Stand up the full observability and operations surface specified in `.claude/notes/08-security-observability-ops.md` § Observability, § Failure modes and graceful degradation, and § Daily ops cadence. Prometheus `/metrics`, OpenTelemetry tracing per JSON-RPC call, Phoenix retrieval-quality views, structured JSON logging with required fields, failure-mode handlers, daily and weekly ops crons, restic backup/restore, and a Grafana cache-hit dashboard. Milestones E14_S01–E14_S05 are Tier 5, parallel to E11 and E13 — they complete the production-readiness surface without gating the corpus cutover. E14_S06 is the deferred-work tracker (Tier 6): ColBERT-v2, TikZ-cd extraction, proof-skeleton classifier, multi-paper dedup, ORCID disambiguation, withdrawal flag surface, and Lean kernel integration. The deferred items are PARKED; each has an explicit trigger that would un-park it.

Effort: M + M + M + S + L + S + S + S + S + M + S + S = XL total (observability completions); deferred tracker is 0 engineering.

References: `.claude/notes/08-security-observability-ops.md` lines 100–209 (Observability, Failure modes, Daily ops cadence, Backup and restore); `.claude/notes/06-mcp-server-design.md` lines 340–349 (Health and readiness); `.claude/notes/09-feature-priorities.md` lines 80–140 (Tier 6, Tier 7, Decision points)

---

### E14_S01 — `/metrics` endpoint: full Prometheus surface

**Status:** NEW
**Tier:** 5
**Effort:** M
**Dependencies:** E07_S08, E08_S08

**Description.** Expose the complete set of server-side metrics from `.claude/notes/08-security-observability-ops.md` § Metrics on the `/metrics` endpoint using Prometheus exposition format. The endpoint stub was created in E06_S01; this milestone fills it with all documented metric families.

The metric families are: request counters (`arxmcp_request_total{tool, status}`, `arxmcp_request_latency_seconds{tool}`, `arxmcp_request_inflight{tool}`, `arxmcp_result_bytes{tool}`); cache metrics from the three-tier cache implemented in E08 (`arxmcp_cache_lookups_total{layer}`, `arxmcp_cache_hits_total{layer}`, `arxmcp_cache_evictions_total{layer}`, `arxmcp_cache_bytes{layer}`); embedder and reranker metrics (`arxmcp_embed_calls_total{model, outcome}`, `arxmcp_embed_latency_seconds{model}`, `arxmcp_embed_singleflight_dedup_total`, `arxmcp_rerank_calls_total{model, outcome}`, `arxmcp_rerank_latency_seconds{model}`); and retrieval-quality metrics (`arxmcp_retrieval_ndcg5{corpus_version}` — updated by the eval harness in E11_S04 and surfaced here for drift alerting). The `corpus_version` label on retrieval metrics connects the Prometheus surface to the MVCC corpus versioning in E11_S05.

Metric instrumentation is implemented in `server/observability/metrics.py` as a thin wrapper over the `prometheus_client` library. Each tool handler increments its counters via a context-manager decorator; the embedder and reranker update their families via callbacks registered in `server/resources.py`. The `/metrics` endpoint is served by the existing FastAPI app; no separate process is needed.

**Deliverables.**
- `server/observability/metrics.py` — all metric family definitions and helper decorators
- Updated tool handlers in `server/tools/` — `@track_request` decorator applied to all 7
- Updated `server/resources.py` — embedder/reranker callbacks register metric increments
- `tests/test_metrics.py` — exercises each of the 7 tools and asserts the expected counter increments; validates `/metrics` response with `promtool check metrics`

**Acceptance criteria.**
- [ ] `pytest tests/test_metrics.py` passes: each tool increments `arxmcp_request_total` with the correct `tool` label
- [ ] `arxmcp_cache_hits_total{layer="tier1"}` increments on a cache hit (test with a repeated query)
- [ ] `arxmcp_embed_singleflight_dedup_total` increments when two concurrent identical queries share one embedding call
- [ ] `arxmcp_retrieval_ndcg5{corpus_version=...}` is present with the current corpus version label
- [ ] `GET /metrics` returns valid Prometheus text format; `promtool check metrics` exits 0
- [ ] The drift watchdog (E11_S04) updates `arxmcp_retrieval_ndcg5` and the value is readable via `/metrics`

**Out of scope.** Grafana dashboard (E14_S09). API spend metrics for hosted-model fallbacks (E14_S12). Alerting rules (documented in E14_S04's runbook).

**Risk notes.**
- The `corpus_version` label on `arxmcp_retrieval_ndcg5` is load-bearing for the drift watchdog alert. If the label is missing or stale, alert suppression is possible. This is a MEDIUM finding from `.claude/notes/08-security-observability-ops.md` § Drift detection.

**Labels.** `area:observability`, `kind:infra`, `tier:5`

---

### E14_S02 — OpenTelemetry tracing: one span per JSON-RPC tool call

**Status:** NEW
**Tier:** 5
**Effort:** M
**Dependencies:** E07_S08

**Description.** Emit one parent OTel span per JSON-RPC request, with child spans for each major sub-operation: embed (BGE-M3 call), vector-search (LanceDB ANN query), BM25 search (Tantivy query), rerank (BGE-reranker-v2-m3 call), and summarize (Haiku API call when configured). The span hierarchy gives end-to-end latency visibility across the full retrieval pipeline.

Required span attributes on the parent span: `mcp.session_id` (from `Mcp-Session-Id` header), `mcp.tool_name`, `arxmcp.cache_layer_served` (e.g., `"tier1"`, `"tier3"`, `"miss"`), `arxmcp.corpus_version` (integer from startup), `arxmcp.k` (requested result count), `arxmcp.agent_role` (optional; read from a `_agent_role` parameter in the tool args if present — documented in the tool schema but not required). Child spans carry the model name (BGE-M3 commit SHA for embed; BGE-reranker-v2-m3 commit SHA for rerank) as `model.revision`.

The OTel SDK is initialized in `server/observability/tracing.py::setup_tracing()` called from the lifespan context manager. The OTLP exporter destination is `ARXMCP_OTEL_ENDPOINT` (default: `http://localhost:4317`). If the endpoint is unreachable, tracing fails silently with a logged WARN (never crashes the server).

**Deliverables.**
- `server/observability/tracing.py` — `setup_tracing()`, `span_tool_call()` context manager, `span_embed()`, `span_rerank()`, `span_summarize()`
- Updated tool handlers — each wrapped with `span_tool_call(tool_name, session_id, ...)`
- `tests/test_tracing.py` — uses an in-process OTel SDK span exporter; asserts span hierarchy and attribute presence
- `docs/observability/tracing.md` — attribute catalog, OTLP configuration

**Acceptance criteria.**
- [ ] `pytest tests/test_tracing.py` passes: a `search_papers` call produces a parent span with child spans for embed + ANN + rerank
- [ ] Parent span has all 6 documented attributes set (including `arxmcp.cache_layer_served`)
- [ ] `model.revision` on embed child span matches the configured BGE-M3 commit SHA
- [ ] OTel endpoint unreachable → server continues operating; WARN logged once at startup
- [ ] `ARXMCP_OTEL_ENDPOINT` unset → tracing disabled (no-op exporter); no error

**Out of scope.** Phoenix integration (E14_S03). Langfuse orchestrator-side tracing (E14_S11). Sampling configuration (all spans exported in v1; sampling is a Tier-6 concern).

**Risk notes.**
- OTel spans containing `mcp.session_id` must not be forwarded to a remote endpoint by default — the default OTLP endpoint is localhost Phoenix. Forwarding to an external SaaS collector would leak session IDs. Document this in `docs/observability/tracing.md`.

**Labels.** `area:observability`, `kind:infra`, `tier:5`

---

### E14_S03 — Phoenix integration for retrieval-quality views

**Status:** NEW
**Tier:** 5
**Effort:** M
**Dependencies:** E14_S02

**Description.** Phoenix (Arize Phoenix, open-source) is the v1 default for retrieval-quality eyeballing — it renders queries, retrieved chunks with scores, and reranker output in a local UI. It runs in Docker alongside the MCP server and receives OTel spans from E14_S02 via the OTLP collector Phoenix ships with.

Phoenix is opt-in: a separate Docker Compose profile (`--profile phoenix`) adds the Phoenix container. Without the profile, the server operates normally and the OTel exporter's endpoint simply receives no responses (failing silently per E14_S02). The compose profile also starts a Prometheus scrape target for the `/metrics` endpoint, making E14_S01 metrics visible in Phoenix's metrics pane.

The setup procedure must be a copy-paste-runnable sequence in `docs/observability/phoenix.md`: `docker compose --profile phoenix up -d`, navigate to `http://localhost:6006`. No manual configuration of span routing is required — the `ARXMCP_OTEL_ENDPOINT` default points at the Phoenix OTLP collector port.

**Deliverables.**
- `infra/observability/phoenix-compose.yml` — Phoenix service definition (or a `profiles:` block in the main `docker-compose.yml`)
- Updated `docker-compose.yml` — Phoenix profile integrated
- `docs/observability/phoenix.md` — startup procedure, screenshot of the retrieval trace view

**Acceptance criteria.**
- [ ] `docker compose --profile phoenix up -d` starts Phoenix without error
- [ ] Phoenix UI at `http://localhost:6006` shows spans from a test `search_papers` call (top-k chunks, scores, reranker output)
- [ ] Without the `phoenix` profile, the server starts normally; no connection errors in the log
- [ ] `docs/observability/phoenix.md` is self-contained and tested

**Out of scope.** Langfuse (E14_S11). Custom Phoenix ingest pipelines. Phoenix cloud/SaaS integration.

**Risk notes.**
- Phoenix receives OTel spans that include `mcp.session_id`. The Phoenix container must be localhost-only (no external port binding); document this in the compose file.

**Labels.** `area:observability`, `kind:infra`, `tier:5`

---

### E14_S04 — Daily ops runbook and cron cadence

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E11_S02, E14_S01

**Description.** Codify the daily and weekly ops cadence from `.claude/notes/08-security-observability-ops.md` § Daily ops cadence as runnable cron entries and documented procedures. The cadence is: 00:00 UTC — daily delta (E11_S02 cron, already landed); 04:30 UTC — drift watchdog eval (E11_S04 cron, already landed); 05:00 UTC — daily metrics report generated by `tools/daily_metrics_report.py`; Sunday 06:00 UTC — parser-failures review report; quarterly — restore drill reminder.

`tools/daily_metrics_report.py` reads Prometheus metrics from the running server's `/metrics` endpoint and per-day parser-failure log files, then produces a markdown report at `var/arxmcp/ops/daily-reports/<YYYY-MM-DD>.md`. Sections: requests served, P50/P95/P99 latency per tool (7 tools), cache hit rates per layer (Tier 1, 2, 3), ingestion throughput (papers ingested, chunks written), parser failure counts. Email delivery is optional (`MAIL_TO`, `MAIL_FROM`, `SMTP_HOST` env vars; off by default).

The weekly parser-failures review cron runs `tools/parser_failures_report.py` (authored in E02_S06) every Sunday at 06:00 UTC and writes `var/arxmcp/ops/reports/parser-failures-<ISO-week>.md`. A quarterly drill reminder script (`tools/quarterly_drill_reminder.sh`) writes a reminder file 7 days before the next quarter mark. All three cron entries are committed to `infra/cron/` as both crontab fragments and systemd timer unit files.

**Deliverables.**
- `tools/daily_metrics_report.py`
- `infra/cron/daily-metrics-report.cron` + `infra/cron/daily-metrics-report.timer`
- `infra/cron/parser-failures-weekly.cron` + `infra/cron/parser-failures-weekly.timer`
- `tools/quarterly_drill_reminder.sh`
- `infra/cron/quarterly-drill-reminder.cron`
- `docs/ops/daily-ops-cadence.md` — full schedule table, alert thresholds, escalation path
- `docs/ops/parser-failure-review.md` — human triage workflow

**Acceptance criteria.**
- [ ] `python tools/daily_metrics_report.py --dry-run` produces a valid markdown report against a fixture `/metrics` response
- [ ] Report includes all 7 tools in the latency breakdown
- [ ] `tools/quarterly_drill_reminder.sh --dry-run` writes a reminder file without error
- [ ] All cron entries pass `crontab -l | crontab -` syntax validation
- [ ] `docs/ops/daily-ops-cadence.md` lists all cron entries with UTC times and links to the relevant runbooks

**Out of scope.** Grafana alerting rules (documented in the runbook but implemented in E14_S09). Email delivery as a required feature (opt-in only).

**Risk notes.**
- The "ops cadence" HIGH finding from `.claude/notes/08-security-observability-ops.md` § Daily ops cadence: without a documented and automated cadence, parser failures and corpus drift accumulate silently.

**Labels.** `area:observability`, `kind:infra`, `tier:5`

---

### E14_S05 — Failure-mode handlers, restic backup, and restore drill

**Status:** NEW
**Tier:** 5
**Effort:** L
**Dependencies:** E07_S07, E07_S08, E11_S05

**Description.** Implement the failure-mode detection and response table from `.claude/notes/08-security-observability-ops.md` § Failure modes and graceful degradation, and execute the backup and restore procedures from § Backup and restore. This milestone folds in the backup/restore scope from the original E12_S08–S09.

The failure modes and their responses:

**LanceDB corruption on restart.** If `dataset.checkout(corpus_version)` raises at startup, the server logs an ERROR, attempts to fall back to the previous version (corpus_version − 1), and marks itself degraded (`/readyz` returns 503 with body `{"status":"degraded","reason":"corpus_corruption"}`). A `pytest` test injects a synthetic corruption by writing an invalid fragment file into the version directory.

**Reranker slow cold start.** The readiness probe already waits for the reranker to complete a dummy inference (E07_S07). This milestone makes the warm-up explicit: a single dummy inference on 10 randomly selected cached chunk embeddings is run during `lifespan` startup before `/readyz` returns 200.

**Disk-full detection.** A Prometheus alert rule file (`infra/prometheus/alerts.yml`) defines `ArXMCPDiskFull` (fires when free space on `$ARXMCP_DATA_DIR`'s filesystem < 10 GB). Ingestion is paused at the queue level by writing `var/arxmcp/ops/ingest-paused` sentinel file; the delta cron checks for this sentinel before running. Read operations continue normally.

**Hosted-embedder outage fallback.** When the optional hosted embedder path (`ARXMCP_QUERY_EMBED_PROVIDER=voyage`) is configured and the API call fails, the server falls back to the local BGE-M3 embedder and tags results with `degraded=true` in the response metadata, so the orchestrator can be aware of the degradation.

**Restic backup.** `infra/restic/repo-init.sh` initializes a restic repository targeting either a local NAS path (`RESTIC_REPOSITORY` env var) or Backblaze B2 (`b2:<bucket>:<path>`). `infra/restic/nightly.sh` takes a snapshot of `var/arxmcp/corpus/`, `var/arxmcp/index/lancedb/`, and `var/arxmcp/index/kuzu/`, then prunes to a 7-daily / 4-weekly / 12-monthly retention policy. The restic password is stored in `RESTIC_PASSWORD` env var; never in source.

**Restore drill.** `docs/ops/restore-runbook.md` documents the exact commands to restore the most recent restic snapshot to a fresh `var/arxmcp/` on a separate machine or sandbox path. The drill is executed once before this milestone closes; the time-to-restore is measured and recorded in the runbook. The next drill is scheduled via `tools/quarterly_drill_reminder.sh` (E14_S04).

**Deliverables.**
- `server/corpus.py` — updated `checkout()` fallback logic; degraded `/readyz` response
- `server/resources.py` — explicit reranker warm-up inference in `lifespan`
- `infra/prometheus/alerts.yml` — `ArXMCPDiskFull` alert rule
- `tools/ingest_sentinel.py` — writes/reads the `ingest-paused` sentinel
- `infra/restic/repo-init.sh`, `infra/restic/nightly.sh`
- `infra/cron/restic-nightly.cron` + `.timer`
- `docs/ops/failure-modes.md` — table mapping each failure mode to its detection and response
- `docs/ops/restore-runbook.md` — restore procedure with measured time-to-restore
- `tests/test_failure_modes.py` — LanceDB corruption fallback test, disk-sentinel test

**Acceptance criteria.**
- [ ] Synthetic LanceDB corruption → server starts in degraded mode, `/readyz` returns 503 with `reason:"corpus_corruption"`, fallback version serves requests
- [ ] `pytest tests/test_failure_modes.py` passes: corruption fallback and disk-sentinel tests
- [ ] `infra/restic/nightly.sh` completes a test snapshot successfully; `restic check` exits 0
- [ ] `RESTIC_PASSWORD` never appears in source; CI secret-scan confirms
- [ ] Restore drill executed once on a sandbox path; time-to-restore documented in `docs/ops/restore-runbook.md`
- [ ] `infra/prometheus/alerts.yml` passes `promtool check rules`
- [ ] `docs/ops/failure-modes.md` covers all 8 failure modes from the notes table

**Out of scope.** S3 backup (constraint: no AWS for arXiv data; B2 and local NAS are the documented options). Automated restore (restore is a human-in-the-loop operation; the drill proves the runbook works).

**Risk notes.**
- The MVCC corpus version fallback (LanceDB corruption → previous version) depends on the old version directory remaining on disk. The restic retention policy must not prune the LanceDB version directories used as fallback targets. Document this dependency in `docs/ops/restore-runbook.md`.

**Labels.** `area:observability`, `area:server`, `kind:infra`, `tier:5`

---

### E14_S06 — DEFERRED WORK TRACKER (Tier 6+): parked items and un-park triggers

**Status:** PARKED
**Tier:** 6
**Effort:** —
**Dependencies:** E11_S05 (v1 in steady state — prerequisite for all un-park decisions)

**Description.** This milestone is a living tracker for work that is explicitly out of v1 scope but motivates v1 design decisions. No engineering is budgeted here. Items move to active milestones only when their stated trigger condition is met and documented. The tracker consolidates the former E15 epic (quality-of-life and v2 deferred work) into a single file location.

Each item below lists: what it is, why it was deferred, and what evidence would un-park it.

---

**ColBERT-v2 late interaction for theorem-level chunks (Tier 6 / v1.5 candidate)**
Colbert-v2 (v1.5 or newer) late-interaction retrieval beats single-vector dense on long technical chunks at approximately 10× storage cost. The schema reserved `embedding_colbert` in E05_S01. *Un-park trigger:* documented evidence from the E11_S04 retrieval-quality eval that single-vector ANN retrieval is the bottleneck — specifically, that the nDCG@5 gap between BGE-M3 and the theoretical ceiling (BM25 oracle re-ranked) is > 0.10. Do not build until that data exists. Estimated complexity: XL.

**TikZ-cd commutative diagram extraction for math.AG (Tier 6 candidate)**
TikZ-cd diagrams carry significant semantic content in math.AG papers. The chunker would emit `DiagramAtom` records with normalized graph (nodes + edges) for graph-similarity retrieval, plus a new `find_diagram` tool. *Un-park trigger:* a documented retrieval-failure case where a TikZ-cd-rich paper is the known correct answer for a test query, but BM25 + ANN retrieval both miss it. Estimated complexity: XL.

**Proof-skeleton classifier (Tier 6 candidate)**
A small fine-tuned classifier (DistilBERT-class) that tags theorem chunks with proof-skeleton labels (induction, contradiction, spectral sequence, generic functoriality). Training data: Mathlib tagged proofs. Would add a `proof_skeleton` filter to `search_papers`. *Un-park trigger:* a tactician sub-agent demonstrates documented need for "find me proofs that use induction on the dimension" and the existing keyword + semantic search is insufficient. Estimated complexity: XL.

**Multi-paper deduplication (Tier 6 candidate)**
Cross-listed papers, withdraw-and-resubmit cases, and near-duplicate works on different arXiv IDs create redundancy in retrieval results. Detection via pairwise chunk-similarity scan over papers with overlapping authors and close submission dates; output is a `near_duplicates` field on the papers table. *Un-park trigger:* retrieval evaluations show ≥ 5% of top-10 result sets contain duplicates of the same work. Estimated complexity: L.

**ORCID author disambiguation (Tier 6 candidate)**
ORCID data arrives via INSPIRE / OpenAlex enrichment in E09_S05. This would expose `find_papers_by_author(orcid)` and disambiguate the `authors` filter in `search_papers`. Also surfaces `withdrawn=true` flags more visibly (a `warning: "withdrawn"` field at the top of `get_paper` and `search_papers` results). *Un-park trigger:* a documented agent failure caused by author-name collision where ORCID disambiguation would resolve it. Estimated complexity: M.

**Lean 4 toolchain integration (Tier 7 / v2 deferred)**
LeanDojo bindings to expose Lean's proof state to arXMCP, enabling a `lean_kernel_query` pass-through tool. This is the gateway feature for the autoformalizer integration and the subgoal-decomposition orchestrator agent (DeepSeek-Prover-V2 pattern). *Un-park trigger:* a dedicated v2 design document exists and the autoformalizer integration is the primary development goal. The v1 design (deterministic chunk IDs, hierarchical retrieval, definitions table, `expand_macro` tool, `find_lemma_by_name` tool) was made with this in mind. Estimated complexity: XL. A `lean_kernel_query` tool is NOT to be added to the 7-tool v1 surface without a v2 scope decision.

**Mathlib lookup and subgoal-decomposition orchestrator (Tier 7 / v2 deferred)**
Maps arXMCP theorem-name hits to Mathlib lemma names and statements where they exist. Builds on `find_lemma_by_name` (E10_S03) but requires a Mathlib snapshot index and a name-disambiguation layer. The subgoal-decomposition orchestrator that uses arXMCP retrieval to find candidate Mathlib lemmas and arXiv proofs of similar facts lives in a separate repo (not the arXMCP server). *Un-park trigger:* Lean 4 toolchain integration (above) is active. Estimated complexity: L + XL.

**Non-goal: LLM critic tool**
An LLM "critic" tool (`critique`, `adversarial_check`, `llm_critic`, or similar) is explicitly NOT to be built. Lean is the critic. An LLM critic is theater. This is a hard design constraint, not a deferred item. Any PR that registers a tool with one of those names should be rejected at review. A CI lint check enforcing this constraint is part of E13_S02's scope (the `docs/non-goals.md` entry) and is not re-opened here.

**Out of scope.** Engineering work of any kind within this milestone. Trigger-condition evaluation is a periodic human review (quarterly, during the restore drill cadence established in E14_S04).

**Labels.** `area:retrieval`, `area:parser`, `area:embedder`, `area:server`, `area:graph`, `kind:research`, `tier:6`

---

### E14_S09 — Cache hit-ratio and latency Grafana dashboard

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E14_S01

**Description.** A Grafana dashboard provides operational visibility into cache behavior and retrieval latency without requiring Phoenix to be running. The dashboard is defined as a provisioned JSON file (checked into source) so it loads automatically when Grafana starts.

The dashboard panels: cache hit ratio per layer (Tier 1, 2, 3 — derived from `arxmcp_cache_hits_total / arxmcp_cache_lookups_total`); embedder singleflight dedup count (`arxmcp_embed_singleflight_dedup_total`); reranker latency P50/P95 (`arxmcp_rerank_latency_seconds` histogram); per-tool P95 request latency; and active inflight requests per tool. A Prometheus datasource at `http://localhost:9090` is provisioned automatically.

**Deliverables.**
- `infra/observability/grafana-dashboard.json` — Grafana dashboard definition
- `infra/observability/grafana-provisioning.yml` — datasource + dashboard provisioning config
- `infra/observability/grafana-compose.yml` (or `profiles:` block) — opt-in Grafana + Prometheus compose profile
- `docs/observability/grafana.md` — startup procedure

**Acceptance criteria.**
- [ ] `docker compose --profile grafana up -d` starts Grafana at `http://localhost:3000` and Prometheus at `http://localhost:9090`
- [ ] Dashboard loads automatically with all panels populated after a few tool calls
- [ ] Cache hit ratio panels show sensible values after a repeated query (Tier-1 hit visible)
- [ ] Without the `grafana` profile, the server operates normally

**Out of scope.** Alertmanager configuration (alert rules are in `infra/prometheus/alerts.yml` per E14_S05; routing is a Tier-6 concern). PagerDuty / email alerting integration.

**Risk notes.**
- The Grafana container must not expose port 3000 to non-localhost interfaces. Compose `ports:` mapping must be `127.0.0.1:3000:3000`.

**Labels.** `area:observability`, `kind:infra`, `tier:5`

---

### E14_S10 — Ops runbook index

**Status:** NEW
**Tier:** 5
**Effort:** M
**Dependencies:** E14_S05

**Description.** Consolidate the operational runbooks written across E11, E13, and E14 into a single indexed entry point at `docs/ops/README.md`. Each runbook covers one named failure or maintenance scenario drawn from `.claude/notes/08-security-observability-ops.md`. The index is linked from the top-level `README.md`.

Required runbooks (each with symptoms / detection / steps / verification sections): server-crash recovery; ingestion-pause recovery (disk-full sentinel); disk-full handling; restore from backup (links to `docs/ops/restore-runbook.md` from E14_S05); model swap (embedder or reranker version upgrade — links to the embedder-loader SHA-pinning procedure from E13_S06); corpus version rollback (MVCC atomic revert: revert `corpus-version.json` to the previous LanceDB dataset version per E04_S02 + E11_S05); LaTeXML worker restart; drift watchdog alert response.

**Deliverables.**
- `docs/ops/README.md` — runbook index with one-line summaries and links
- Individual runbook files for any scenarios not already documented: `docs/ops/server-crash.md`, `docs/ops/model-swap.md`, `docs/ops/corpus-rollback.md`, `docs/ops/latexml-restart.md`, `docs/ops/drift-alert.md`
- `README.md` updated — link to `docs/ops/README.md` in the Operations section

**Acceptance criteria.**
- [ ] `docs/ops/README.md` lists all 8 runbooks with one-line summaries
- [ ] Every runbook has symptoms / detection / steps / verification sections
- [ ] `docs/ops/corpus-rollback.md` describes the MVCC revert command exactly (revert `corpus-version.json`; restart MCP server)
- [ ] Top-level `README.md` links to `docs/ops/README.md`

**Out of scope.** Automated remediation (runbooks are human-in-the-loop by design). Schema migration runbook (deferred to the first schema change after v1 ships).

**Risk notes.**
- The corpus rollback runbook must note that reverting `corpus-version.json` (and the LanceDB dataset version pin) does not roll back the Kùzu citation graph — these are independent stores. Document the asymmetry explicitly.

**Labels.** `area:observability`, `kind:research`, `tier:5`

---

### E14_S11 — Langfuse orchestrator-side tracing documentation

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E14_S02

**Description.** Per `.claude/notes/08-security-observability-ops.md` § Recommended export targets — "Langfuse if/when the agent orchestrator becomes part of this repo." Today the orchestrator lives in the caller's codebase. This milestone ships documentation for how a Claude API caller can wrap their tool-using agent and route orchestrator-side traces to Langfuse, enabling end-to-end visibility from the LLM call through the MCP tool result.

The documentation provides a reference snippet using the Langfuse Python SDK with the canonical pattern: wrap the Claude API call in a Langfuse `trace`, add the arXMCP MCP session ID as a tag so traces can be joined with the OTel spans from E14_S02, and log tool inputs and outputs. The MCP session ID is available from the `Mcp-Session-Id` response header returned by the server.

**Deliverables.**
- `docs/observability/langfuse-orchestrator.md` — explanation + reference snippet (< 60 lines of Python)

**Acceptance criteria.**
- [ ] `docs/observability/langfuse-orchestrator.md` contains a runnable Python snippet (tested manually)
- [ ] Snippet uses the Langfuse Python SDK; joins traces via `mcp_session_id` tag
- [ ] Documented as opt-in; Langfuse is not in the server's `pyproject.toml` dependencies

**Out of scope.** Langfuse as a required dependency. Server-side Langfuse integration.

**Labels.** `area:observability`, `kind:research`, `tier:5`

---

### E14_S12 — API spend metrics for hosted-model fallbacks

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E14_S01, E08_S07

**Description.** When the optional hosted-embedder path (`ARXMCP_QUERY_EMBED_PROVIDER=voyage`) is configured, or when the Haiku summarizer (E08_S07) is active, the server incurs API spend. A spend counter tracks this for operational visibility and budget control.

The metric family is `arxmcp_api_spend_usd_total{provider, model, agent_role}`. The `provider` label is `"voyage"` or `"anthropic"`. The `model` label is the specific model name (`"voyage-3"`, `"claude-haiku-4-5"`, etc.). The `agent_role` label is populated from the `_agent_role` tool arg if present (same as E14_S02). Per-call cost constants are documented in `server/observability/spend_constants.py` and must be updated when pricing changes (no automated pricing API).

The daily metrics report (E14_S04) surfaces the top spend categories by summing `arxmcp_api_spend_usd_total` grouped by provider and model.

**Deliverables.**
- `server/observability/spend_constants.py` — per-call cost constants with source URLs and last-verified dates
- Updated `server/embedder/` and `server/summarizer/` — increment spend counter after each hosted API call
- `tests/test_spend_metrics.py` — fixture API call increments the counter with the correct labels

**Acceptance criteria.**
- [ ] `pytest tests/test_spend_metrics.py` passes: fixture Haiku summarizer call increments `arxmcp_api_spend_usd_total{provider="anthropic", model="claude-haiku-4-5"}`
- [ ] Counter is absent (zero value, not present) when hosted providers are not configured
- [ ] `spend_constants.py` has a comment citing the pricing page URL and the date last verified
- [ ] Daily report (E14_S04) includes a spend section

**Out of scope.** Budget alerting (a Prometheus alert rule on cumulative spend is a Tier-6 operational tuning concern). Automated pricing updates.

**Labels.** `area:observability`, `area:cache`, `tier:5`
