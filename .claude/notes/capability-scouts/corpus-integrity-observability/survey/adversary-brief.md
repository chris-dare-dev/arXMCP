# Adversary Scout Brief — corpus-integrity-observability capability survey

**Scout ID:** corpus-integrity-observability
**Scope:** Observability & reporting — logging, metrics, operator-facing reporting, and the class of bug where a persisted metadata field silently diverges from ground truth.
**Motivating bug:** `ingest/store.py::write_chunks` historically wrote `corpus-version.json` with `chunk_count=len(chunks)` (last-paper-batch only), producing a marker that read `chunk_count=106` against a table with 10,298 rows — a ~100x silent discrepancy that surfaced only by manual inspection. m1–e3 in this epic have addressed several aspects, but the landscape still has gaps worth naming.

---

## 1. Executive summary

The m1/m2/m3/e2/e3 milestone chain closed the most acute gaps: the write-time count now comes from `tbl.count_rows()`, the `/metrics` endpoint exposes both `arxmcp_corpus_chunk_count_marker` and `arxmcp_corpus_chunk_count_actual`, the daily report now shows a `## Corpus integrity` divergence section, and the `DegradedState("chunk_count_diverged")` path wires degraded-mode alerting. That is real, tangible progress.

The residual gaps are four in character. First, **no Prometheus alert rule fires on a marker-vs-actual divergence** — the gauges exist, the daily report shows `[DIVERGED]`, but there is no `alerts.yml` rule that would page an operator within minutes of a mismatched restart. Second, the **reconciliation is startup-only and stale-by-design**: the gauges are cached at boot and never refreshed, so a divergence that appears mid-run (a failed write, a crashed ingest, a notebook-scope truncation) is invisible until the next restart. Third, **the BM25 index version has no cross-check against the LanceDB corpus version**: the BM25 pickle at `index/bm25/v<N>/bm25.pkl` can silently refer to a stale corpus version if the final `build_bm25_index` call is omitted after a multi-paper ingest. Fourth, **the Kùzu citation graph's `_schema_meta` paper count is never compared against the LanceDB paper count**, meaning a partial graph ingest can serve retrieval silently without the operator knowing the graph is an undercount of the corpus.

---

## 2. Critical gaps

None. The motivating bug is fixed at write time; the missing capabilities degrade operator visibility but do not corrupt the retrieval data path for the sketcher → autoformalizer → tactician → fixer consumer.

---

## 3. High gaps

### H1 — No Prometheus alert rule fires on chunk_count divergence

**Severity:** HIGH

**What comparable systems / SOTA expects:**
Production retrieval systems that expose reconciliation gauges always pair them with an alert expression. Elastic's `index.docs.count` vs stored `_meta.doc_count` delta fires within the scrape interval. OpenSearch cluster-stats anomaly detection ships as a built-in rule. The arXMCP `infra/prometheus/alerts.yml` file itself demonstrates this pattern for disk space (`ArXMCPDiskFull`), degraded mode (`ArXMCPDegradedMode`), and backup staleness (`ArXMCPBackupStale`) — all with sub-5-minute `for:` windows.

**What arXMCP has today:**
`infra/prometheus/alerts.yml` contains rules for `ArXMCPDiskFull`, `ArXMCPDegradedMode`, `ArXMCPBackupStale`, `ArXMCPEvalQuarantine`, and `ArXMCPLatexmlDrift`. There is no rule of the form `arxmcp_corpus_chunk_count_actual != arxmcp_corpus_chunk_count_marker` (or any ratio/gap expression). The gap is visible in `health.py:101-120` where both gauges are defined with clear docstrings noting the comparison, and in `health.py:1017-1025` where the `chunk_count_diverged` reason resets known labels — but no alert rule consumes those gauges.

The `DegradedState("chunk_count_diverged")` path at `server/resources.py:475` does fire `ArXMCPDegradedMode`, so a divergence that crosses the tolerance threshold at startup does produce an alert. However: (a) the alert fires only if the server restarts after the divergence occurs; (b) a divergence below the tolerance threshold (`ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE`, default 5%) produces no alert even though both gauges are exposed and the diff is visible; (c) the daily report renders `[DIVERGED]` as a Markdown badge, not a machine-checkable alarm.

**What a credible v1 fill-in would look like:**
Add two rules to `infra/prometheus/alerts.yml`. Rule 1 fires when `arxmcp_corpus_chunk_count_actual >= 0` AND `arxmcp_corpus_chunk_count_marker >= 0` AND `abs(actual - marker) / marker > 0.05` (matching the default tolerance constant in `server/config.py`). Rule 2 fires when `arxmcp_corpus_chunk_count_actual == -1` for more than, say, 10 minutes (the `count_rows()` failure sentinel that signals startup I/O trouble). Both rules should carry a `runbook_url` pointing to the reconcile CLI (`tools/notebook_reconcile_marker.py --shared`). No new code changes to the server; the gauges already exist. The missing piece is purely the YAML expression.

**Architecture-lock interaction:**
None. `infra/prometheus/alerts.yml` is already the pattern for this kind of rule (CLAUDE.md §4.7 is silent on alert rules). Does not touch `tools.py`, `prompts.py`, or any BP1/BP2 surface.

**Why this hasn't been fixed yet:**
The milestone sequence (m1 → m2 → e2 → e3) prioritized building the gauge pair and the write-time fix. The alert rule was noted as "alert rule potential" in the design constitution (note-08 §Metrics docblock for `arxmcp_ingest_oai_pmh_lag_seconds`) but was never scheduled as an explicit acceptance criterion for any milestone. The `ArXMCPDegradedMode` rule captures the above-tolerance path; the below-tolerance path was apparently considered acceptable as a "warn but don't degrade" signal.

---

### H2 — Reconciliation is startup-only; mid-session divergence is invisible

**Severity:** HIGH

**What comparable systems / SOTA expects:**
Elasticsearch's `_cat/health` and `_cluster/stats` APIs provide live row counts, not startup-cached ones. Apache Solr's `numDocs` gauge refreshes on every Prometheus scrape. The LanceDB documentation itself describes `count_rows()` as an O(1) Lance fragment-metadata read — not a full table scan. arXMCP's own code comments in `server/health.py:111-120` note that both gauges are "read ONCE at startup" and explicitly bracket this as a limitation ("a gap indicates corpus/marker divergence" — but only as of the last restart).

**What arXMCP has today:**
`server/health.py:570-580` explicitly documents "cached once at startup; NOT recomputed per scrape" for `CORPUS_CHUNK_COUNT_ACTUAL`. `server/resources.py:381-392` defines `startup_chunk_count: int = -1` as the process-lifetime cache field. `refresh_metrics_from_singleton_state` at `health.py:563` reads `resources.startup_chunk_count` directly — zero I/O at scrape time. A divergence introduced by a mid-session ingest (notebook ingest via the UI, a manual re-embed run, a textbook-pipeline call) cannot be seen in the gauges until the MCP server restarts. The daily report is also startup-sourced.

**What a credible v1 fill-in would look like:**
The cleanest local-first option consistent with arXMCP's constraints is a scrape-time refresh of `arxmcp_corpus_chunk_count_actual` via a lightweight `count_rows()` call wrapped in `asyncio.to_thread` (as already used at startup in `resources.py:564`). The key constraint is to never block the event loop on a scrape — the existing pattern at `resources.py:436` shows the idiom. A second option is a "staleness TTL" flag that marks the gauge stale after a configurable window (e.g. 1 hour) and triggers a background recount — similar to the refresh-token pattern used in `server/cache.py`. Given the "local-first, single-workstation, no-new-heavy-infra" constraint, either option is tractable in under 50 LOC.

**Architecture-lock interaction:**
The scrape-time refresh must be ASGI-safe (no blocking I/O in the sync Prometheus callback — use an `asyncio.Task` or `run_in_executor` pattern). Does not touch tools.py or BP1/BP2 cache keys (the count is never a cache key component per `server/corpus.py` docstring).

**Why this hasn't been fixed yet:**
The m2 implementation summary explicitly chose "cached once" to satisfy AC-3 ("a test asserts `count_rows()` is called AT MOST ONCE across startup + a `/metrics` scrape"). The reasoning was sound for preventing scrape-time blocking, but the tradeoff (invisible mid-session divergences) was accepted without a documented plan to address it. The m2 adversary critique confirmed the per-scrape zero-call contract as correct; the live-refresh option was not explored.

---

## 4. Medium gaps

### M1 — BM25 index corpus_version has no cross-check against LanceDB marker

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
Any retrieval system with a derived index (BM25, inverted, quantized) typically stores the source-data version in the index metadata and compares it at load time. The `bm25_indexer.py` module already version-namespaces its output as `index/bm25/v<N>/bm25.pkl`, which is a creditable approach. What is absent is any enforcement that the `N` in the BM25 path equals the `version` in `corpus-version.json` at server startup, or any log/metric that surfaces a mismatch.

**What arXMCP has today:**
`ingest/bm25_indexer.py:6-30` explains the per-corpus-version naming and explicitly states the index must be built manually ("Until that driver lands, the BM25 index must be built manually after ingest"). `server/retrieval/bm25.py` loads the BM25 pickle at server startup; a grep shows no cross-check of the loaded index's version against `corpus_info.version`. There is no metric, log field, or startup WARN for a version mismatch. CLAUDE.md §7 does not list BM25 version drift as a known stub, though the bm25_indexer docstring effectively makes it one.

**What a credible v1 fill-in would look like:**
The BM25 index directory path already encodes the version integer. At startup in `Resources.startup`, after loading the BM25 index, verify that the loaded index's path component `v<N>` matches `corpus_info.version`. If they differ, emit a structured WARN log with fields `bm25_index_version` and `corpus_version`, and set a new Gauge `arxmcp_bm25_index_version_mismatch` (0 = match, 1 = mismatch). This is a pure observability addition, no behavioral change. The alert rule (`arxmcp_bm25_index_version_mismatch == 1`) would then close the gap.

**Architecture-lock interaction:**
None. Does not touch tools.py or prompt cache keys.

**Why this hasn't been fixed yet:**
The BM25 version-namespacing was introduced as a correctness mechanism (prevents stale BM25 cache), but the cross-check was never added as an explicit requirement. The observation was present implicitly in the `bm25_indexer.py` docstring "Until that driver lands, the BM25 index must be built manually" — the manual gap was noted but the observability dimension was not pursued.

---

### M2 — Kùzu graph `_schema_meta` paper count not compared against LanceDB paper count

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
Citation graph systems (INSPIRE-HEP's own reporting, OpenAlex dataset integrity documentation) expose a "covered papers" fraction alongside the corpus size — a citation graph that covers only 40% of the ingested corpus is a known-impaired retrieval surface. LeanDojo's lean4-corpus metadata carries `num_theorems` alongside the extraction stats. arXMCP's Kùzu graph stores `_schema_meta` with `schema_version` (see `kuzudb_schema.py:92`), but the ingested paper count is never cross-referenced against the LanceDB `paper_count` from `corpus-version.json`.

**What arXMCP has today:**
`ingest/kuzudb_schema.py:92` defines a `_schema_meta` node table with `key`/`value` pairs, storing the schema version. `ingest/graph_ingest.py` upserts Paper nodes. There is no Prometheus gauge for "graph_papers / corpus_papers" coverage fraction, no startup check in `Resources.startup`, and no entry in `daily_metrics_report.py` for citation-graph coverage. CLAUDE.md §6 notes the `cite_neighbors` MCP tool handler is a stub — but even the library path has no coverage visibility.

**What a credible v1 fill-in would look like:**
At server startup (or as a sentinel-file pattern mirroring `ingest-summary.json`), query Kùzu for `MATCH (p:Paper) RETURN count(p)` and compare against `corpus_info.paper_count`. Expose as a gauge pair: `arxmcp_graph_papers_in_kuzu` and `arxmcp_corpus_papers_in_lancedb`. A fractional coverage below, say, 0.5 should emit a startup WARN. This is a single `add_sentinel_file` + gauge approach consistent with how `ingest-summary.json` bridges ingest-process and server-process. No additional dependency; Kùzu's Python API is already loaded for `cite_neighbors`.

**Architecture-lock interaction:**
The Kùzu open/query at startup must be async-safe (same `run_in_executor` pattern as the LanceDB `count_rows()` at `resources.py:564`). Does not touch tools.py or BP1/BP2.

**Why this hasn't been fixed yet:**
The citation graph ingest (`graph_ingest.py`, `inspire_ingest.py`) was designed as an independent background process, and the `cite_neighbors` MCP tool handler is a documented stub (CLAUDE.md §7). The observability gap in graph coverage was never flagged as a priority because the tool was not fully wired. The consequence is that a partially-ingested graph is invisible: the operator has no signal that `cite_neighbors` will return impoverished results.

---

### M3 — Structured log fields at startup are not test-assertable in CI

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
The 2026 state of the art for structured logging in retrieval infrastructure (see Vespa's `search.log` contract, Elasticsearch's `json-log` format documentation) is that key startup events have stable, assertable field schemas — so a test can grep for `event=corpus_pinned chunk_count=NNN` and catch a regression where the field is renamed or dropped. The arXMCP note-08 §Logging already specifies required fields: `event`, `msg`, `level`, `timestamp`, `logger`. The corpus-integrity-observability-e2 milestone added a `write_chunks_complete` event with `extra={"event": ..., "corpus_version": ..., "chunk_count": ..., "paper_count": ...}`. However, the startup INFO log at `server/resources.py:508-512` is a free-text `%`-formatted string with positional arguments (`corpus_version=%d`, `paper_count=%d`, `chunk_count=%d`, `chunker=%s`, `embedder=%s`) — it is NOT a structured-log emission with machine-assertable `extra=` keys.

**What arXMCP has today:**
`server/resources.py:505-512` emits: `logger.info("Resources.startup: pinning corpus_version=%d (paper_count=%d, chunk_count=%d, chunker=%s, embedder=%s)", ...)`. The `JsonFormatter` (installed by default since e2) will format this as a single `msg` string containing the interpolated values — not as individual fields accessible to a log-aggregation filter or a test assertion like `assert record["chunk_count"] == 10298`.

Compare with `ingest/store.py:961-969`: the `write_chunks_complete` log correctly uses `extra={"event": "write_chunks_complete", "corpus_version": ..., "chunk_count": ..., "paper_count": ...}`, which the `JsonFormatter` will surface as top-level JSON fields. The startup log in `resources.py` does not follow this pattern.

**What a credible v1 fill-in would look like:**
Convert the `resources.py:508` startup INFO log to use `extra={"event": "corpus_pinned", "corpus_version": ..., "chunk_count": ..., "paper_count": ..., "chunker_version": ..., "embedder_version": ...}`. Then add one test in `tests/test_server_startup.py` using `caplog` or a log-record filter that asserts `record.corpus_version == expected` on the corpus-pinned event — the same pattern used in the e2 milestone for `write_chunks_complete`. This is a ~5-line production change and ~10-line test, and closes the class of "log says one thing, table has another" that went unnoticed with the free-text format.

**Architecture-lock interaction:**
The structured-log fields (`chunk_count`, `paper_count`) are aggregate-only and are explicitly declared safe for INFO-level emission in note-08 §Logging: "Sensitive fields (full query text, chunk bodies) are logged at DEBUG only." No BP1/BP2 impact.

**Why this hasn't been fixed yet:**
The `write_chunks_complete` event was added in e2 with the structured-log pattern. The startup log in `resources.py` predates that milestone and was not retroactively updated during e2. The e2 adversary critique did not cover `resources.py` startup logs — it focused on the write-path event and the `/readyz` surface.

---

### M4 — No test-mode "assert marker equals table" gate in the standard test suite

**Severity:** MEDIUM

**What comparable systems / SOTA expects:**
Beir and other retrieval eval frameworks include a "corpus sanity check" step that verifies the index size equals the expected corpus size before running any queries — a fast pre-flight that catches "did you forget to re-index?" errors. arXMCP's own m1 regression test (`test_marker_reflects_table_after_per_paper_writes`) does exactly this for the ingest path. However, there is no equivalent gate that runs as part of `make test` against a LIVE (warm) corpus, and no gate that validates the startup reconciliation path end-to-end from the server's perspective.

**What arXMCP has today:**
`tests/test_store.py::TestCorpusVersionMarkerReconciliation` tests the ingest write path with synthetic data. `tests/test_corpus_count_reconciliation.py` tests the `Resources.startup` reconciliation logic with monkeypatched tables. Neither test constructs a real LanceDB table, writes real chunks, boots a real server against it, and then asserts `/readyz` returns `chunk_count == marker_chunk_count`. The eval gate (`make eval`, `tests/eval/test_retrieval_quality.py`) tests retrieval quality, not corpus-count integrity.

**What a credible v1 fill-in would look like:**
A new test (appropriately tagged `requires_full_corpus` or gated on a config flag) that: (1) boots a temporary in-process server against the test corpus, (2) hits `/readyz` and asserts `body["chunk_count"] == body["marker_chunk_count"]`, and (3) optionally asserts the Prometheus gauges are equal via a `/metrics` scrape. This is the "production truth check" that the motivating bug would have tripped — it is not covered by any existing test because all existing tests use either synthetic data or mocked table handles.

**Architecture-lock interaction:**
Can be implemented as a `pytest` fixture that creates a fresh `Config` pointing at `tmp_path` LanceDB, runs a synthetic multi-paper ingest via `write_chunks`, then starts the `FastAPI` test client — the standard pattern used in `tests/test_server_startup.py`. No new infra.

**Why this hasn't been fixed yet:**
The m1 regression test validates the write path. The m2 tests validate the reconciliation logic. The missing piece is an integration test that crosses the boundary between the two — proving that what `write_chunks` writes, `Resources.startup` correctly reads and reconciles, and `/readyz` correctly surfaces. This crossing was judged adequate by inference across the two test suites, not by a direct integration test.

---

## 5. Low gaps

### L1 — Daily report does not include Kùzu citation graph coverage

**Severity:** LOW

**What arXMCP has today:**
`tools/daily_metrics_report.py` renders sections for: requests, latency, cache hit rates, embedder/reranker, corpus integrity (marker vs actual), ingestion throughput, and backup status. There is no section for citation graph coverage (papers in Kùzu vs papers in LanceDB), no section for BM25 index version alignment, and no section for the eval nDCG@5 watchdog values (even though `arxmcp_eval_ndcg5{corpus_version=N}` is exposed as a gauge via `server/metrics.py:221`).

**What a credible v1 fill-in would look like:**
Add a `## Retrieval index health` section to the daily report that reads `arxmcp_eval_ndcg5` from the metrics scrape and renders the most recent nDCG@5 value, comparable to how backup status is surfaced. This is a pure reporting addition (the gauge already exists) consistent with the "make it human-visible at daily cadence" design principle that motivated the `## Corpus integrity` section.

**Architecture-lock interaction:** None.

**Why this hasn't been fixed yet:** The e3 adversary critique flagged the missing sections but at LOW severity; all three remaining scrape-side gaps are deferrals from prior milestones.

---

### L2 — `infra/prometheus/alerts.yml` runbook URLs point to a non-existent path

**Severity:** LOW

**What arXMCP has today:**
`infra/prometheus/alerts.yml` references `https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/failure-modes.md`, `docs/ops/backup-restore.md`, `docs/ops/drift-watchdog.md`, and `docs/ops/latexml-drift-runbook.md`. These paths do not exist under `docs/` — the repo only contains `docs/install.md`. The runbook files are referenced but not created; the operator reaching an alert is immediately dead-ended.

**What a credible v1 fill-in would look like:**
Create skeleton runbook files at the referenced paths (they are allowed under `docs/` per CLAUDE.md §1: "ONLY user-facing documentation referenced by the root README.md") OR update the `runbook_url` values to point to existing `.claude/docs/` content — noting that `.claude/` paths are agent-internal and not operator-facing. The cleaner option is to create stub operator-facing runbooks under `docs/ops/` for each alert rule.

**Architecture-lock interaction:** None.

**Why this hasn't been fixed yet:** The alert rules were written as forward-looking artifacts (E14_S05) and the runbooks were listed as E14_S10 (Ops runbook index), which remains unstarted per the roadmap README.

---

### L3 — `make reconcile` CLI is not documented in README or `make help`

**Severity:** LOW

**What arXMCP has today:**
`tools/notebook_reconcile_marker.py` is a runbook-facing tool (the CLI analog of `POST /ui/api/notebooks/{slug}/reconcile-marker`). It is not listed in `make help`, not referenced in `README.md`, and not mentioned in `docs/install.md`. An operator who encounters a corpus-count divergence and runs `make help` will not find the remediation tool.

**What a credible v1 fill-in would look like:**
Add a `reconcile` target to `Makefile` (as noted in `notebook_reconcile_marker.py`'s usage docstring which already references `make reconcile`) and a one-line entry in `README.md` under the "Common tasks" section.

**Architecture-lock interaction:** None.

**Why this hasn't been fixed yet:** The CLI was written in the onboarding-uplift-m3 milestone focused on "reconcile-marker endpoint"; the Makefile target was mentioned in the docstring but not implemented.

---

## 6. What arXMCP does well

- **Write-time count reconciliation from the committed table.** `ingest/store.py:938-944` uses `tbl.count_rows()` (O(1) Lance fragment metadata) plus a distinct `paper_id` PyArrow select, not `len(chunks)`. The marker is therefore correct after a multi-paper ingest, re-embed, or notebook-textbook run. The m1 regression test fails on the pre-fix code with `assert 2 == 5` — exactly the production bug shape.

- **Dual-gauge startup reconciliation with configurable tolerance.** `server/resources.py:219-251` (`compute_chunk_count_divergence`) is a clean, exhaustively-tested pure helper with 10 unit cases pinning the FM-2/3/4/6 edge cases. The `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE` config knob (default 5%) with a `max(1, tolerance * marker)` floor avoids false alarms on micro-corpora while being strict enough to catch the motivating ~100x drift.

- **The degraded-mode path is wired, tested, and mutation-valid.** When reconciliation at startup detects divergence above tolerance, `DegradedState("chunk_count_diverged")` is set, `/readyz` returns 503 with the reason, `ArXMCPDegradedMode` fires in the alert rules, and `test_corpus_corruption_not_clobbered` proves the signal cannot be clobbered by a subsequent `corpus_corruption` fallback. This is a genuinely rare property in observability implementations — the mutation test works.

- **Structured log event at write time.** `ingest/store.py:961-969` emits `write_chunks_complete` with `extra={"event": "write_chunks_complete", "corpus_version": ..., "chunk_count": ..., "paper_count": ...}` as structured JSON fields (not free-text). Combined with the `JsonFormatter` default since e2, this event is grep-assertable in production logs and is pinned by `tests/test_store.py`.

- **Sentinel-file bridge pattern between ingest process and server metrics.** `ingest/ingest_summary.py` writes a v1 JSON sentinel atomically; `server/health.py:refresh_sentinel_metrics` reads it at scrape time. The FM-4/5/7 mitigations (schema_version-first guard, 64KB cap, unknown-version leave-prior) are genuine defenses that prevent a corrupt sentinel from breaking the server. This design pattern is correctly local-first and requires no shared IPC.

- **HNSW unindexed-rows tripwire.** `CORPUS_UNINDEXED_ROWS` gauge (m3) exposes total unindexed HNSW rows at startup. After the m3 HIGH fix (filtering BTree from the ANN index count), a vector-index-less corpus now correctly returns `-1` (unknown coverage) rather than a false-clean `0`. The scalar `paper_id_idx` contamination was caught by empirical verification against a real seeded corpus — a level of testing rigor not common in comparable systems.

---

## 7. Themes

The overarching theme is **point-in-time observability without continuous watch**: arXMCP has invested heavily in making a divergence detectable at startup and visible in the daily report, but has not closed the loop with live alerting rules or mid-session gauge refresh. The motivating ~100x chunk_count bug could recur in a different form (BM25 stale, graph partial, a new metadata field) and survive undetected until a human notices something odd in `/readyz` output — not because the tooling is absent, but because the alert rules and live-refresh paths have not been written for the new gauges.

A secondary theme is **independent stores, no shared invariant enforcer**: LanceDB, the BM25 pickle, Kùzu, per-notebook LanceDB, and `notebooks.db` are all independently maintained with their own version markers, but there is no process that periodically audits their mutual consistency. The reconcile-marker CLI and the `compute_chunk_count_divergence` function are strong building blocks; what is missing is a scheduled job (cron or watchdog) that invokes them and writes results to a sentinel, completing the sentinel-file bridge pattern already established for ingest throughput and nDCG@5.

The third theme is **test coverage at boundaries, not across them**: both the write-path (ingest) and the read-path (server startup) reconciliation logic are unit-tested with high fidelity, but no integration test crosses the ingest-write → server-startup → `/readyz` boundary end-to-end. The motivating bug lived precisely in that gap.
