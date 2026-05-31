# Synthesis — corpus-integrity-observability

**Scout ID:** corpus-integrity-observability
**Generated:** 2026-05-31
**Synthesizer:** main session (per phase-synthesize protocol)
**Briefs consumed:** 5 (adversary, comparative, multi-agent, oss-trends, research-frontier)

---

## 1. Executive summary

25 deduplicated candidates emerged across 5 briefs. **Ops / infra dominates with 11 candidates** — the prior corpus-integrity-observability epic (m1/m2/m3/e2/e3) closed the write-time and startup-reconciliation defects, so the residual landscape is heavily oriented toward operator-facing alerting and reporting, mid-session refresh, cross-store consistency, and integration-test coverage. **Top theme: the gauges exist but the alarms don't fire.** All 5 briefs converge on the observation that arXMCP shipped the dual-gauge pair (`arxmcp_corpus_chunk_count_marker` / `..._actual`), the `DegradedState("chunk_count_diverged")` path, and the daily-report rendering — but the Prometheus alert rule that would page within a scrape interval (CAND-1) has 4-way triangulation and is the highest-signal candidate. **Top tension:** the multi-agent scout uniquely surfaces *agent-facing* capabilities (a `get_corpus_delta` MCP tool, OTel `mcp.session.id` corpus-snapshot events, session corpus guards) — none of the other 4 scouts surface these because they read the bug as an operator-visibility problem, not a calling-agent visibility problem. The synthesizer flags this disagreement to the challenger explicitly.

---

## 2. Triangulation strength

- **4-brief triangulation (strongest signal):** 1 candidate — CAND-1 (Prometheus alert rule for marker-vs-actual drift) appears in adversary H1, comparative C3, oss-trends 2.6, and research-frontier CAND-1+CAND-6 indirectly.
- **3-brief triangulation:** 3 candidates — CAND-3 (write-time invariant gate / WAP pattern), CAND-4 (structlog + capture_logs assertable startup events), CAND-8 (end-to-end multi-paper integration test).
- **2-brief triangulation:** 3 candidates — CAND-2 (daily report integrity section), CAND-5 (mid-session live count_rows refresh), CAND-12 (Evidently-style dataset-drift detection).
- **1-brief triangulation:** 18 candidates — weak signal; flagged for challenger scrutiny. Most live in adversary M1/M2/L1-L3 (specific gaps the other scouts didn't traverse) and in multi-agent (which uniquely surfaces the agent-facing change-surface lens).

---

## 3. Candidate catalog

### Ops / infra (11 candidates)

#### CAND-1 — Ship Prometheus alert rules for corpus-integrity gauges

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 4 briefs (adversary H1 ✓, comparative C3 ✓, oss-trends 2.6 ✓, research-frontier CAND-6 indirectly ✓)

**What it is:** Add 2–3 rules to `infra/prometheus/alerts.yml` operationalizing the m2/m3 gauges: (a) `abs(arxmcp_corpus_chunk_count_actual - arxmcp_corpus_chunk_count_marker) / clamp_min(marker, 1) > 0.05` (drift > tolerance), (b) `arxmcp_corpus_chunk_count_actual == -1 for 10m` (count_rows() failure sentinel), (c) optionally `arxmcp_corpus_unindexed_rows > 0 for 1h` (m3 tripwire).

**Why it matters:** Without alert rules the dual-gauge pair is silent telemetry. Operators see drift only on next restart or by daily-report inspection. A rule fires within the scrape interval. arXMCP would be the first local-vector-store project with such a rule pattern documented (awesome-prometheus-alerts catalog confirms absence per comparative C3). The motivating ~100x drift would have paged within 60s.

**Sources:**
- Adversary H1 — "no `arxmcp_corpus_chunk_count_actual != arxmcp_corpus_chunk_count_marker` rule; daily-report `[DIVERGED]` is a Markdown badge, not an alarm"
- Comparative C3 — Qdrant/Elasticsearch pattern; awesome-prometheus-alerts confirms the rule is not in any public catalog
- OSS-trends 2.6 — Prometheus + Alertmanager delta-gauge pattern; `prometheus-client` already a dep
- Research-frontier CAND-6 — LLM Readiness Harness CI-gate framing aligns with falsifiable contracts

**Closest arXMCP analog (today):** `infra/prometheus/alerts.yml` has `ArXMCPDiskFull`, `ArXMCPDegradedMode`, `ArXMCPBackupStale`, `ArXMCPEvalQuarantine`, `ArXMCPLatexmlDrift` — exactly the pattern; no rule yet exists for the corpus-count divergence gauges shipped in m2.

**Sketch:** Append two `groups[0].rules[]` YAML entries to `infra/prometheus/alerts.yml`. Use the existing `severity`, `runbook_url`, `for:` shape. No server code. Pair with a stub runbook page (or update CAND-24 to land them together).

**Open questions:** Does the existing `ArXMCPDegradedMode` rule already cover the above-tolerance path? (Yes per adversary — but a sub-tolerance drift still produces no alert.) Decide whether to define a `warning` severity for sub-tolerance drift.

---

#### CAND-2 — Daily report `## Corpus integrity` + `## Retrieval index health` sections

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 2 briefs (comparative C2+C9 ✓ — explicit, also flagged from prior scout as "unshipped"; adversary L1 ✓)

**What it is:** Extend `tools/daily_metrics_report.py` with a `## Corpus integrity` section reading the m2 gauges and rendering a pass/warn/error classification (dbt-source-freshness pattern), plus a `## Retrieval index health` section surfacing the latest `arxmcp_eval_ndcg5` value and `arxmcp_corpus_unindexed_rows` from m3.

**Why it matters:** This is the human-cadence read of the same signals as CAND-1's alerts. Operators who don't run a Prometheus stack still get visibility through `make daily-report`. The IETF `application/health+json` tiered model is already established in `server/health.py::compute_health_status` — the daily report would mirror it.

**Sources:**
- Comparative C2 + C9 — dbt source-freshness threshold-gated reporting; CAND-9 was already on the prior-run catalog as unshipped
- Adversary L1 — daily report omits Kùzu graph coverage, BM25 alignment, and eval nDCG@5 watchdog values

**Closest arXMCP analog (today):** `tools/daily_metrics_report.py` — has sections for requests, latency, cache, embedder, ingestion throughput, backup status. The IETF tiered model lives at `server/health.py::compute_health_status` (used for backup staleness + process uptime).

**Sketch:** ~30 LOC in `tools/daily_metrics_report.py` reading the relevant gauges from the local `/metrics` scrape (or directly from `Resources.startup_chunk_count` if the script runs in-process). Reuse the pass/warn/error tier logic from `compute_health_status`.

**Open questions:** Should the daily report fetch via curl `/metrics` (requires server running) or read directly from `Resources` (requires being inside the server process)? Current daily-report behavior should be checked.

---

#### CAND-3 — Write-Audit-Publish (WAP) post-write invariant in `ingest/store.py`

**Category:** Ingestion / parsing
**Size:** S
**Evidence triangulation:** 3 briefs (research-frontier CAND-1+CAND-2 ✓ — explicit top method; oss-trends 2.1+2.2+2.4 ✓ — structlog test + Pandera schema + GX Checkpoint patterns; adversary supports indirectly via "write-time is the right boundary" theme)

**What it is:** Between `_create_indices()` and the marker write in `ingest/store.py::write_chunks`, add a post-write invariant: `if tbl.count_rows() != stats.total_rows_after_commit: raise RuntimeError(...)`. Block marker publication on a confirmed reconciliation. Modeled on Apache Iceberg's WAP pattern + Pandera's `check_output` DSL + GX's Checkpoint contract.

**Why it matters:** This is the only candidate that prevents the buggy marker from being persisted in the first place rather than detecting drift after. Defense-in-depth alongside m1's fix (which routed the writer through `count_rows()` but did not gate publication on a final reconciliation). The motivating ~100x bug class would have crashed the ingest run rather than producing a silent live cutover.

**Sources:**
- Research-frontier CAND-1 (WAP) — Dagster blog + lakeFS reference; the exact pattern
- Research-frontier CAND-2 (Pandera) — schema-level row-count Check applied at write boundary; ~30 LOC
- OSS-trends 2.1 (structlog capture_logs test) — turns the invariant into a CI-assertable contract
- OSS-trends 2.2 (Pandera) + 2.4 (GX Expectation) — both validate write-time as the right enforcement point

**Closest arXMCP analog (today):** `ingest/store.py::write_chunks` already calls `tbl.count_rows()` post-m1 fix; what's missing is the equality assertion + raise. `tools/notebook_reconcile_marker.py::_recount_lancedb` has the exact reconciliation logic, but it runs reactively (after-the-fact), not as a write-gate.

**Sketch:** ~20–40 LOC in `ingest/store.py::write_chunks` after the merge_insert + index commit, before the `write_corpus_version_marker` call. Use `if … raise RuntimeError(…)` (project bans `assert`). Emit the existing `write_chunks_complete` structured log event (already shipped per e2) with an additional `reconciliation_check_passed: bool` field. Add a multi-paper unit test using a 3-paper × 30-chunks synthetic corpus that asserts the path raises on a mocked count mismatch.

**Open questions:** What is the tolerance window? (m2 ships `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE` for startup reconciliation — should write-time use the same constant or zero-tolerance?) Synthesizer leans zero-tolerance because write-time has no concurrent-writer concern.

---

#### CAND-4 — structlog migration + `capture_logs()`-assertable startup events

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 3 briefs (research-frontier CAND-3 ✓ — explicit; oss-trends 2.1+2.7 ✓ — Top-1 project; adversary M3 ✓ — startup INFO log uses `%s` formatting, not structured fields)

**What it is:** Migrate selected critical-path log calls (the `Resources.startup: pinning corpus_version=...` line at `server/resources.py:508-512`, and any other startup integrity logs) to use `extra={"event": "corpus_pinned", "corpus_version": …, "chunk_count": …, "paper_count": …}` so the `JsonFormatter` surfaces them as top-level JSON fields. Add `pytest-structlog` (or `caplog.records[N].chunk_count`) tests asserting the field values.

**Why it matters:** The motivating bug's "wrong values went unnoticed" half is closed by making startup log emissions test-assertable. The bug would have failed a CI test (`assert record.chunk_count == 10298`) rather than reaching production. This is the cheapest path to making future structural log-field regressions immediately visible.

**Sources:**
- Research-frontier CAND-3 — structlog `capture_logs()` is the only pattern that makes startup log emission machine-testable in-process without a scrape endpoint
- OSS-trends 2.1 + 2.7 — top project; specifically calls out the `Resources.startup` log line and `write_corpus_version_marker` log as the right migration targets
- Adversary M3 — explicitly identifies `server/resources.py:508-512` as the un-structured outlier vs `ingest/store.py:961-969` which IS structured (e2)

**Closest arXMCP analog (today):** `ingest/store.py:961-969` already uses the pattern (`extra={"event": "write_chunks_complete", "corpus_version": …, "chunk_count": …}`). The startup log in `server/resources.py:508` predates e2 and was not retroactively updated. JsonFormatter is the default since e2.

**Sketch:** ~5–10 LOC in `server/resources.py` to rewrite the startup INFO log with `extra=`. Add `pytest-structlog` (~15 KB MIT-licensed pytest plugin) or use stdlib `caplog` with manual record inspection. New test in `tests/test_server_startup.py` asserting `record.corpus_version == expected`. The migration could expand to other startup events (BGE-M3 loaded, BM25 loaded, reranker loaded) but the corpus_pinned event is the critical-path priority.

**Open questions:** Add `pytest-structlog` as a dep, or stick with stdlib `caplog`? Stdlib is sufficient if the migration only changes the `extra=` shape; full structlog migration is a larger refactor (parking-lot until adopted broadly).

---

#### CAND-5 — Mid-session live `count_rows()` refresh for `arxmcp_corpus_chunk_count_actual`

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 2 briefs (adversary H2 ✓ — explicit "startup-only, stale-by-design"; multi-agent Candidate 3 indirectly via session corpus_snapshot event)

**What it is:** Replace the startup-cached `arxmcp_corpus_chunk_count_actual` with a scrape-time-refreshed gauge using `asyncio.to_thread(tbl.count_rows)` (LanceDB documents this as O(1) Lance fragment-metadata read). Alternative: TTL-based refresh (1 hour) backed by background task. Resolves the m2 limitation explicitly documented at `server/health.py:570-580`.

**Why it matters:** A divergence introduced mid-session (a notebook ingest via the UI, a manual re-embed run, a textbook-pipeline call) is invisible until the next server restart. CAND-1's alert rule cannot fire on a mid-session drift without this refresh. The m2 decision to cache-once was sound under "no scrape-time blocking I/O" but the tradeoff was accepted without a documented plan to address.

**Sources:**
- Adversary H2 — "Reconciliation is startup-only; mid-session divergence is invisible"; cites `count_rows()` as O(1) fragment-metadata read per LanceDB docs
- Multi-agent Candidate 3 — OTel `corpus_snapshot` per-session event would benefit from live counts

**Closest arXMCP analog (today):** `server/health.py:111-120` defines both gauges; `refresh_metrics_from_singleton_state` at `health.py:563` reads `resources.startup_chunk_count` (zero I/O at scrape time). LanceDB docs (https://docs.lancedb.com/tables/consistency) confirm `count_rows()` is O(1) on the metadata footer.

**Sketch:** ~30 LOC. Replace the current `refresh_metrics_from_singleton_state` reading of `startup_chunk_count` with a scrape-callable refresh. Critical constraint: never block the event loop on a sync Prometheus callback — use `asyncio.Task` or `run_in_executor` (same pattern as `resources.py:564`). The m2 test `test_count_rows_called_at_most_once` will fail by design — needs an explicit decision to relax it.

**Open questions:** Will scrape-time `count_rows()` violate the m2 zero-call contract test? (Yes — needs explicit re-negotiation.) Does Phoenix/Datadog expect the value to be stable for trace-attribute purposes? (Decoupled — span attribute is the value at span-open; gauge is point-in-time at scrape.) Synthesizer recommends a separate `actual_live` Counter alongside `actual_startup` so the test contract stays clean.

---

#### CAND-6 — BM25 index version cross-check vs LanceDB corpus version

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (adversary M1 ✓)

**What it is:** At `Resources.startup`, after loading the BM25 index, verify that the loaded index's path component `v<N>` matches `corpus_info.version`. Emit a structured WARN log on mismatch and set a new Gauge `arxmcp_bm25_index_version_mismatch` (0 = match, 1 = mismatch). Optionally an `ArXMCPBM25Drift` alert rule.

**Why it matters:** `ingest/bm25_indexer.py:6-30` docstring explicitly notes that "the BM25 index must be built manually after ingest." A stale BM25 (pointing at `v3` while LanceDB is on `v4`) silently serves wrong retrieval. CLAUDE.md §7 does not list this as a known stub, but the bm25_indexer docstring effectively makes it one. Cheapest fix to the second-largest dual-store integrity gap.

**Sources:**
- Adversary M1 — explicit. The BM25 path already encodes the version; the cross-check is the missing piece.

**Closest arXMCP analog (today):** `ingest/bm25_indexer.py:6-30` (version-namespacing); `server/retrieval/bm25.py` (load path). No cross-check at startup, no metric, no log field.

**Sketch:** ~15 LOC at startup. New Gauge in `server/observability/metrics.py`. New CAND-1 alert rule. No new infra.

**Open questions:** Is there a credible production path where a mismatched BM25 is correct? (No — the path encodes the version, so mismatch = stale BM25 = always wrong.)

---

#### CAND-7 — Kùzu citation graph paper-count cross-check vs LanceDB

**Category:** Citation graph
**Size:** S
**Evidence triangulation:** 1 brief (adversary M2 ✓)

**What it is:** At server startup, query Kùzu for `MATCH (p:Paper) RETURN count(p)` and compare against `corpus_info.paper_count`. Expose as gauge pair `arxmcp_graph_papers_in_kuzu` + `arxmcp_corpus_papers_in_lancedb`. A fractional coverage below 0.5 emits a startup WARN.

**Why it matters:** A partial citation-graph ingest is invisible to operators. `cite_neighbors` (currently a stub per CLAUDE.md §7) silently returns impoverished results when graph coverage is < 50% of corpus. Same "metadata silently diverges from ground truth" class as the motivating bug, in a different store. Bridges adversary's "no shared invariant enforcer across independent stores" theme.

**Sources:**
- Adversary M2 — explicit; cites `ingest/kuzudb_schema.py:92` `_schema_meta` storing schema version only, not paper count

**Closest arXMCP analog (today):** `ingest/graph_ingest.py` upserts Paper nodes; no startup cross-check; no Prometheus gauge for graph coverage.

**Sketch:** ~30 LOC. Kùzu open/query at startup with `asyncio.to_thread` (Kùzu's Python API is sync). Two new gauges in `server/observability/metrics.py`. CAND-1 alert rule on coverage fraction. May want to gate on whether the `cite_neighbors` handler is wired (stub today).

**Open questions:** Should the check run conditionally on graph existence (skip silently if Kùzu DB absent)? Synthesizer recommends yes — graph is optional infrastructure for many notebooks.

---

#### CAND-8 — End-to-end multi-paper write→server→/readyz integration test

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 3 briefs (comparative C7 ✓ — explicit "CAND-5a"; research-frontier CAND-3 indirectly via "make startup log assertions test-assertable"; adversary M4 ✓)

**What it is:** A new `requires_full_corpus`-tagged or fixture-gated test in `tests/test_server_startup_integration.py` that: (a) writes a real LanceDB table via `write_chunks` with 3+ papers × 30 chunks each, (b) boots a temporary in-process FastAPI server against it, (c) hits `/readyz` and asserts `body["chunk_count"] == body["marker_chunk_count"]`, (d) optionally asserts `/metrics` exposes equal gauges.

**Why it matters:** The motivating bug lived in the gap BETWEEN m1's write-path test (synthetic data) and m2's reconciliation test (mocked tables). Neither boundary test crosses the seam. An integration test would have caught the per-paper-batch-only chunk_count silently because it constructs real data end-to-end.

**Sources:**
- Comparative C7 — explicitly CAND-5a from prior run; was listed as must-ship alongside the m1 fix
- Research-frontier CAND-3 — structlog `capture_logs()` would let this test also assert the structured-log fields
- Adversary M4 — "no test-mode 'assert marker equals table' gate in the standard test suite"

**Closest arXMCP analog (today):** `tests/test_store.py::TestCorpusVersionMarkerReconciliation` (write path, synthetic); `tests/test_corpus_count_reconciliation.py` (read path, mocked); `tests/test_server_startup.py` (TestClient bootstrap pattern). None cross all three boundaries.

**Sketch:** ~80 LOC test. Uses existing synthetic LanceDB fixture pattern from `tests/_graph_helpers.py`. Can combine with CAND-4's structlog assertions for double-coverage. Tag `requires_full_corpus` or use a tiny synthetic 3-paper corpus to stay in the default-run set.

**Open questions:** Should this also be wired into `make eval` as a pre-flight gate? (Synthesizer says yes — it's faster than nDCG@5 and catches a higher-class bug.)

---

#### CAND-19 — `tools/audit.py` / `make audit` dev utility over `store-stats.jsonl`

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (multi-agent Candidate 7 FlorDB ✓)

**What it is:** New dev utility / Make target that pivots `var/arxmcp/ops/store-stats.jsonl` and `var/arxmcp/ops/ingest-summary.json` into a human-readable table showing per-paper chunk counts vs the final marker. Implementable with `jq` or `duckdb` inline (no new dep), or as a tiny Python CLI.

**Why it matters:** Operators auditing a suspected drift today have to read JSONL by eye. An `make audit` target produces "WARN: paper math.AG/1234.5678 wrote 47 chunks; marker total includes only 32" if drift is present. Complements CAND-2 (daily report) — daily is high-level pass/warn/error; audit is per-paper detail.

**Sources:**
- Multi-agent Candidate 7 — FlorDB hindsight-logging pattern; "treat your structured JSONL as queryable tables"

**Closest arXMCP analog (today):** `ingest/store.py::_append_store_stats` writes the JSONL; no read-side utility.

**Sketch:** ~30 LOC Python CLI or a `jq` recipe in the Makefile. No new dep if jq/duckdb already available (DuckDB is already used elsewhere in arXMCP per pyproject.toml).

**Open questions:** Python CLI vs jq one-liner? Synthesizer leans Python CLI for cross-platform reliability.

---

#### CAND-22 — Weaviate-style per-shard unindexed-rows reframing of `arxmcp_corpus_unindexed_rows`

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (comparative C4 ✓ — also open spike from prior run)

**What it is:** Resolve the open spike from prior scout run: verify `tbl.list_indices()` API behavior in lancedb 0.30.x; switch `arxmcp_corpus_unindexed_rows` from a global summed total to per-index gauges (`hnsw_stmt`, `hnsw_proof`).

**Why it matters:** A non-zero global unindexed-rows can hide that one HNSW column is fine while another is broken. Per-index visibility makes diagnosis faster. Open spike from prior catalog; m3 implementation made a defensible decision (global total) but the per-shard reframing would be more diagnostic.

**Sources:**
- Comparative C4 — Weaviate's per-shard `vectorQueueLength` pattern; explicitly marked as the open spike from prior final report

**Closest arXMCP analog (today):** `server/health.py:122-134` (`CORPUS_UNINDEXED_ROWS` shipped per m3, global total).

**Sketch:** Spike first to verify lancedb API. If feasible, ~20 LOC swap. Otherwise leave as-is and document the design choice.

**Open questions:** Spike is the blocker, not the implementation.

---

#### CAND-23 — LanceDB v0.33 manifest-summary API for cheap startup verify

**Category:** Ingestion / parsing
**Size:** XS
**Evidence triangulation:** 1 brief (oss-trends 2.5 ✓)

**What it is:** Replace startup `tbl.count_rows()` with LanceDB v0.33's manifest-summary API (`tbl.version_info()` or similar) — described as cheaper than `count_rows()` and not requiring scanning data files.

**Why it matters:** Lighter-weight startup. Becomes more meaningful at scale (200K-paper corpus). Not a correctness improvement; an efficiency one.

**Sources:**
- OSS-trends 2.5 — LanceDB v0.33.0 (May 28, 2026) manifest summary; flagged as "experimental"

**Closest arXMCP analog (today):** `server/corpus.py::open_chunks_table` + `tbl.count_rows()` (m2).

**Sketch:** Conditional API use with fallback to `count_rows()` since the API is experimental. ~15 LOC.

**Open questions:** Is the manifest-summary API stable enough to depend on? (Probably not yet — defer until v1.0.) Synthesizer flags this as a parking-lot candidate, not a Now-lane.

---

#### CAND-24 — Operator runbook files at the paths `alerts.yml` references

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (adversary L2 ✓)

**What it is:** Create skeleton runbook files at `docs/ops/failure-modes.md`, `docs/ops/backup-restore.md`, `docs/ops/drift-watchdog.md`, `docs/ops/latexml-drift-runbook.md` (the paths `infra/prometheus/alerts.yml` already references). Add to those a new `docs/ops/corpus-drift-runbook.md` matching CAND-1's new alert rules.

**Why it matters:** Operators reaching an alert hit a broken link today. CAND-1's new alert rules will compound this if they also reference non-existent runbooks. Pair these two.

**Sources:**
- Adversary L2 — explicit; references the four broken runbook URLs

**Closest arXMCP analog (today):** Only `docs/install.md` exists. The other paths are aspirational.

**Sketch:** ~5 stub Markdown files, each ~100 lines (`Symptom` / `Quick triage` / `Likely causes` / `Remediation` / `Escalation`). The IETF health+json model in `compute_health_status` is a natural template.

**Open questions:** None.

---

#### CAND-25 — `make reconcile` target + README documentation

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (adversary L3 ✓)

**What it is:** Add `make reconcile` target to Makefile + README "Common tasks" entry. `tools/notebook_reconcile_marker.py`'s docstring already references `make reconcile`. The Makefile target is missing.

**Why it matters:** An operator hitting a divergence and running `make help` cannot find the remediation tool today.

**Sources:**
- Adversary L3 — explicit; the docstring already promises `make reconcile`

**Closest arXMCP analog (today):** `tools/notebook_reconcile_marker.py` exists; not in `make help` or README.

**Sketch:** ~5 LOC Makefile target + 2-line README entry.

**Open questions:** None.

---

### Ingestion / parsing (5 candidates — beyond CAND-3 which counts here too)

#### CAND-9 — SHA-256 sidecar checksum for `corpus-version.json`

**Category:** Ingestion / parsing
**Size:** XS
**Evidence triangulation:** 1 brief (comparative C5 ✓)

**What it is:** Write `corpus-version.json.sha256` sidecar at marker-write time; verify at startup. Addresses file-corruption / manual-edit failure modes (distinct from the count-mismatch class).

**Why it matters:** Detects a different failure mode: a corrupted marker JSON file or one manually edited mid-debug. arXiv S3 bulk manifest uses dual `md5sum`/`content_md5sum` for the same defense.

**Sources:**
- Comparative C5 — freshprobe (MIT) + arXiv S3 manifest dual-hash pattern

**Closest arXMCP analog (today):** `ingest/store.py::write_corpus_version_marker` writes JSON, no checksum.

**Sketch:** `hashlib.sha256(json.dumps(marker_dict, sort_keys=True).encode()).hexdigest()` written atomically alongside the marker; at startup, recompute and compare. ~25 LOC.

**Open questions:** Should mismatch trigger DegradedState (same path as count mismatch) or be a separate failure mode? (Synthesizer: separate, because corruption is different from drift.)

---

#### CAND-10 — Per-run `paper_id_min`/`paper_id_max` in `ingest-summary.json`

**Category:** Ingestion / parsing
**Size:** XS
**Evidence triangulation:** 1 brief (comparative C6 ✓)

**What it is:** Extend `ingest-summary.json` with two string fields (`paper_id_min`, `paper_id_max`) so partial-ingest gaps are visible without parsing `store-stats.jsonl`.

**Why it matters:** If `paper_count == expected_total` but `paper_id_max - paper_id_min` doesn't span the expected range, a gap exists. O(1) sentinel-file extension. Mirrors arXiv S3 manifest's `first_item` / `last_item` per-tar fields.

**Sources:**
- Comparative C6 — arXiv S3 + OpenAlex snapshot patterns

**Closest arXMCP analog (today):** `ingest/oai_delta.py` writes `ingest-summary.json` (e3); `WriteStats.paper_id` exposes per-call ID. Min/max running-aggregate in the writer is trivial.

**Sketch:** ~10 LOC in `ingest/oai_delta.py` to maintain a running min/max in the loop. Two new string fields in the JSON schema (version bump).

**Open questions:** Schema-version bump implications for `ingest-summary.json` readers? (Cheap forward-compat; readers ignore unknown fields.)

---

#### CAND-11 — AVH-style auto-historical bounds (rolling-mean drift)

**Category:** Ingestion / parsing
**Size:** M
**Evidence triangulation:** 1 brief (research-frontier CAND-7 ✓)

**What it is:** Read `store-stats.jsonl` history, compute rolling bounds (IQR or Z-score) on `total_rows_after_commit` and `papers_processed` per run, and flag a new run as anomalous if it falls outside the historical normal range. Microsoft's AVH algorithm (KDD 2023).

**Why it matters:** Catches "this run wrote 100x more chunks than usual" or "this run wrote 0 chunks" without per-corpus tuning — adapts to the corpus growth curve.

**Sources:**
- Research-frontier CAND-7 — KDD 2023, validated on 2000 Microsoft production pipelines

**Closest arXMCP analog (today):** `store-stats.jsonl` already exists; no consumer; no bounds-learning step.

**Sketch:** ~100 LOC native impl (no public Microsoft OSS impl). Reads JSONL, computes IQR-based bounds over the last 30 runs, fails new run if outside `[Q1 - 1.5×IQR, Q3 + 1.5×IQR]`. Runs as post-ingest cron alongside the existing drift watchdog.

**Open questions:** How many history points before bounds become meaningful? (Probably N >= 7; documented in the AVH paper.)

---

#### CAND-21 — `infra/corpus-checks.yml` versioned threshold config

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (oss-trends 2.8 ✓ — Soda DSL pattern)

**What it is:** A YAML file holding threshold values for corpus-integrity checks (e.g. `min_chunk_count: 9000`, `max_marker_drift_pct: 5`, `min_papers_per_run: 1`). Read by `ingest/store.py`'s post-write guard (CAND-3) and `server/health.py`'s tolerance reads.

**Why it matters:** Centralizes thresholds in a versioned config file rather than scattering them across Python literals. When corpus grows 10x, one config edit updates all checks. Soda Core's `checks.yml` DSL pattern.

**Sources:**
- OSS-trends 2.8 — Soda Core YAML check-DSL; the borrowable pattern is the threshold-config separation

**Closest arXMCP analog (today):** Thresholds are in `server/config.py` (e.g. `corpus_chunk_count_tolerance = 0.05`). Centralization is partial.

**Sketch:** ~20 LOC schema + reader in `server/config.py` or a new `server/integrity_config.py`. Wire CAND-3 to use it.

**Open questions:** Pydantic for the schema or stdlib YAML + manual validation? (Pydantic for consistency with `Config`.)

---

### MCP tool surface (3 candidates)

#### CAND-16 — `get_corpus_delta(since_version: int)` MCP tool

**Category:** MCP tool surface
**Size:** M
**Evidence triangulation:** 1 brief (multi-agent Candidate 2 VersionRAG + Candidate 4 LeanAgent dynamic-DB)

**What it is:** New MCP tool that reads `store-stats.jsonl` and aggregates `rows_inserted` + `rows_updated` per paper since `since_version`. Returns a structured `{papers_added: N, chunks_added: M, papers_modified: K, ...}` for the calling agent. Closes the agent-facing change-surface gap.

**Why it matters:** Today the agent sees `corpus_version: int` in every envelope but cannot ask "what changed since my last run?" The fixer agent re-running the same query after a delta ingest gets different results with no diagnostic. VersionRAG's research findings (90% vs 58% accuracy on version-sensitive queries) suggest material agent capability uplift.

**Sources:**
- Multi-agent Candidate 2 (VersionRAG arXiv:2510.08109) — corpus version-graph + change-tracking queries
- Multi-agent Candidate 4 (LeanAgent ICLR 2025) — dynamic-DB pattern; "make incremental additions auditable to the agent"

**Closest arXMCP analog (today):** `corpus_version` field in every envelope (`server/tools.py::envelope`). No tool exposes diff semantics. `store-stats.jsonl` exists but is operator-facing only.

**Sketch:** New handler in `server/handlers/corpus_delta.py`. Adds one entry to `ALL_TOOLS` — requires `EXPECTED_TOOL_SCHEMA_SHA256` re-pin (BP1 cost). Reads `store-stats.jsonl`; the tool result is NOT cached (ops query).

**Open questions:** Is the calling agent (sketcher → autoformalizer → tactician → fixer) actually wired to consume this? (Per CLAUDE.md §2 the pipeline does NOT today track per-call corpus version evolution — this is speculative agent capability.) Synthesizer flags this as a candidate the challenger should scrutinize for "value density" axis.

---

#### CAND-18 — Session corpus guard / `corpus_version_at_session_start` advisory field

**Category:** MCP tool surface
**Size:** S
**Evidence triangulation:** 1 brief (multi-agent Candidate 5 SoK Agentic RAG ✓)

**What it is:** `server/session.py` records `corpus_version_at_session_start`. Tool result envelopes include `session_corpus_mismatch: bool` field (true only when live corpus has advanced mid-session). Implements SoK Agentic RAG's "retrieval misalignment" mitigation.

**Why it matters:** The bug the multi-agent scout names "retrieval misalignment" — agent calls return different results because the corpus changed under them. Advisory; doesn't refuse to serve, just flags.

**Sources:**
- Multi-agent Candidate 5 — SoK Agentic RAG paper formally names this failure mode

**Closest arXMCP analog (today):** Per-session caps in `server/session.py`; no recorded session-start corpus_version; envelope has `corpus_version` but not `session_corpus_mismatch`.

**Sketch:** ~30 LOC in `server/session.py` + envelope-extension in `server/tools.py`. Adds one envelope field — needs to verify no BP1 impact (synthesizer believes none — `tools/list` schema bytes don't change, just the result envelope).

**Open questions:** Does adding `session_corpus_mismatch: false` (true only on mismatch) keep the byte-stable common-case envelope? (Yes per multi-agent Cache interaction.) Does it actually help the agent or is the calling pipeline going to ignore it? (Same value-density concern as CAND-16.)

---

#### CAND-20 — mcpdiff `.mcpc.json` contract snapshot artifact

**Category:** MCP tool surface
**Size:** XS
**Evidence triangulation:** 1 brief (multi-agent Candidate 1 ✓)

**What it is:** `make snapshot-tools` Make target that serializes `ALL_TOOLS` from `server/tools.py` into a git-tracked `.mcpc.json` so `git diff .mcpc.json` produces a human-readable description-level diff on any PR/commit. Complements `EXPECTED_TOOL_SCHEMA_SHA256` (hash detects drift; mcpc shows what drifted).

**Why it matters:** When the schema hash regenerates, the diff is opaque ("hash mismatch") rather than semantic. mcpc gives reviewers the description-level diff for free. Dev tooling, not server runtime.

**Sources:**
- Multi-agent Candidate 1 (mcpdiff / mcp-contracts MIT) — community OSS practice

**Closest arXMCP analog (today):** `tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256` (hash pin). The `pytest --update-tool-schema-hash` path is the natural place to also write `.mcpc.json`.

**Sketch:** ~20 LOC: extend the test-hook to dump `ALL_TOOLS` JSON; add `make snapshot-tools` target. Commit `.mcpc.json` to repo.

**Open questions:** Does this duplicate the hash pin's protection? (No — it adds a human-readable surface.) Does this violate the no-fork policy? (No — `.mcpc.json` is a generated artifact, not vendored code.)

---

### Agent harness (1 candidate)

#### CAND-17 — OTel `mcp.session.id` attribute + `corpus_snapshot` per-session event

**Category:** Agent harness
**Size:** S
**Evidence triangulation:** 1 brief (multi-agent Candidate 3 OTel SemConv v1.40 ✓)

**What it is:** (a) Add `mcp.session.id` attribute extraction from `Mcp-Session-Id` request header in `server/observability/tracing.py::span_tool_call`. (b) Emit a `corpus_snapshot` span event at session-open carrying `{chunk_count, corpus_version, bm25_index_version}` so Phoenix timelines show drift across sessions.

**Why it matters:** OTel GenAI MCP SemConv (April 2026) is the emerging cross-vendor standard. arXMCP already integrates Phoenix. Without `mcp.session.id`, Phoenix/Datadog dashboards can't group tool calls by session — a major analytics gap. The `corpus_snapshot` event makes the motivating bug visible as a session-to-session count change in the timeline UI.

**Sources:**
- Multi-agent Candidate 3 — OTel GenAI MCP SemConv (https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/), v1.40

**Closest arXMCP analog (today):** `server/observability/tracing.py::span_tool_call` uses `mcp.tool_name`, `arxmcp.corpus_version`, but not `mcp.session.id`. `server/session.py` tracks session caps but doesn't thread session ID into span context.

**Sketch:** ~40 LOC. Thread the `Mcp-Session-Id` header through `_wrap_with_observability` into `span_tool_call`. Add `emit_corpus_snapshot_event` helper. Resources' `startup_chunk_count` and `corpus_info.version` are already cached.

**Open questions:** Should this attach to `arxmcp.session.id` (vendor namespace) or `mcp.session.id` (spec)? (Spec.) Does Phoenix v3.x already key on `mcp.session.id`? (Per the spec, yes — but verify.)

---

### Retrieval quality (3 candidates)

#### CAND-12 — Evidently AI-style dataset drift checks (post-ingest cron)

**Category:** Retrieval quality
**Size:** M
**Evidence triangulation:** 2 briefs (research-frontier CAND-4 ✓, oss-trends 2.3 ✓ — design-pattern lift only; multi-agent Candidate 6 indirectly)

**What it is:** Reference-baseline dataset drift check applied to chunk-count distribution, embedding norms, or other scalar stats. After every ingest run, compare current vs reference; emit a JSON drift report; surface as a sentinel that the daily-report can consume. NOT importing Evidently (heavy deps); borrowing the reference-baseline + pass/fail-test pattern natively.

**Why it matters:** Catches "the new ingest looks distributionally wrong" — different failure mode than count mismatch (catches structural changes like all-zero embeddings, suddenly-narrow chunk-length distribution). Local-first; no SaaS.

**Sources:**
- Research-frontier CAND-4 — Evidently AI (25K stars, MIT)
- OSS-trends 2.3 — Evidently AI (7.6K stars, Apache-2.0, v0.7.21 March 2026) — note: star count differs between briefs — synthesizer flags as ambiguous
- Multi-agent Candidate 6 — production MLOps tolerance-threshold patterns

**Closest arXMCP analog (today):** `ops/drift_check.py` (LaTeXML parser-output drift). No dataset-level statistical drift check.

**Sketch:** ~100 LOC native impl. Read embeddings from LanceDB; compute simple stats (mean norm, dimension distribution). Compare to a stored reference JSON. Emit pass/fail. Run as post-ingest cron.

**Open questions:** What's the right reference baseline? (Stored after first known-good full corpus build.) Is this overhead worth it for the workstation use case? (Synthesizer flags this for challenger; could be a Spike candidate.)

---

#### CAND-13 — ReproRAG-style startup reproducibility check (top-k golden set)

**Category:** Retrieval quality
**Size:** M
**Evidence triangulation:** 1 brief (research-frontier CAND-5 ✓)

**What it is:** At server startup or as a post-ingest cron, run N=20 fixed queries against the pinned corpus; compute top-k result sets; compare to a stored golden set via Exact Match Rate or Jaccard Similarity. Flag a startup if EMR drops below a threshold — indicates ANN index corruption or unexpected rebuild that changed ranking.

**Why it matters:** Catches index-corruption / re-rebuild ranking shifts that wouldn't trip the count-divergence check (count stays correct; ranking changes). ReproRAG (arXiv:2509.18869) confirms dynamic data insertion is one of the most significant sources of result variation.

**Sources:**
- Research-frontier CAND-5 — arXiv:2509.18869 (September 2025)

**Closest arXMCP analog (today):** `make eval` runs nDCG@5 against the 20-query fixture (weekly cadence). No startup-time variant.

**Sketch:** ~100 LOC reusing the eval fixture infrastructure. BGE-M3 is already loaded at startup (no extra cost). Adds ~30s to startup on cold cache.

**Open questions:** Is 30s startup overhead acceptable? (Probably not; better as a post-ingest cron.) Does it duplicate `make eval`? (Partially — but `make eval` is weekly, this is per-ingest.)

---

#### CAND-14 — LLM Readiness Harness composite-readiness CI gate on cutover

**Category:** Retrieval quality
**Size:** L
**Evidence triangulation:** 1 brief (research-frontier CAND-6 ✓)

**What it is:** Pre-cutover gate that combines retrieval hit rate, latency budget, corpus-integrity checks, and policy compliance into a "readiness score" with explicit Pareto bounds. Refuses to update the corpus pointer (cutover) if the score regresses. Extends `ops/watchdog_eval.py`'s quarantine-flag mechanism to multiple dimensions.

**Why it matters:** Today the cutover gate is nDCG@5-only. A regression in corpus integrity (drift > tolerance) would not block cutover — only retrieval quality regression does. Composite gates guard against gaming a single threshold.

**Sources:**
- Research-frontier CAND-6 — arXiv:2603.27355 (March 2026)

**Closest arXMCP analog (today):** `ops/watchdog_eval.py` (nDCG@5 quarantine flag); `infra/prometheus/alerts.yml` `ArXMCPEvalQuarantine` rule.

**Sketch:** ~200 LOC extending the existing quarantine-flag mechanism. Adds composite-score computation.

**Open questions:** Is this overkill for the single-workstation use case? (Likely — synthesizer flags as parking-lot candidate unless cutover frequency increases.)

---

#### CAND-15 — "Still Fresh?" eval-fixture chunk_id liveness check

**Category:** Retrieval quality
**Size:** XS
**Evidence triangulation:** 1 brief (research-frontier CAND-8 ✓)

**What it is:** On every corpus version bump, verify expected chunk_ids in the eval fixture (`tests/eval/fixtures/queries.json`) are still present in `count_rows()` output. A missing chunk_id means corpus corruption or unexpected chunk_id reassignment.

**Why it matters:** Closes a gap in the eval fixture's validity: today fixtures could silently reference dead chunk_ids after a re-embed.

**Sources:**
- Research-frontier CAND-8 — arXiv:2603.04532 (March 2026, code released)

**Closest arXMCP analog (today):** `tools/validate_eval_fixtures.py` validates fixture structure but not chunk_id liveness.

**Sketch:** ~30 LOC extending `tools/validate_eval_fixtures.py`. Could pre-flight `make eval`.

**Open questions:** None.

---

## 4. Cross-cutting tensions

**T1 — Agent-facing vs operator-facing change-surface.** The multi-agent scout uniquely surfaces CAND-16, CAND-17, CAND-18 — capabilities that expose corpus-change information *to the calling agent*. The other 4 scouts read the bug as an operator-visibility problem and surface dashboards/alerts/tests. The challenger should explicitly evaluate whether arXMCP's sketcher → autoformalizer → tactician → fixer pipeline today is wired to consume agent-facing change signals (per CLAUDE.md §2 mission) — if it is not, these candidates are speculative agent capability uplift rather than near-term value.

**T2 — Defense-in-depth vs single-fix sufficiency.** CAND-3 (WAP write-time gate) and CAND-1 (Prometheus alert rule) both protect against the same bug class at different boundaries (write-time vs read-time-of-metrics). All 5 briefs imply both should ship. The implementer needs explicit guidance on whether to land both as defense-in-depth or sequence them (write-time first; read-time as confirmation).

**T3 — Mid-session refresh tradeoff against m2's explicit zero-call test contract.** CAND-5 (live count_rows on scrape) violates m2's `test_count_rows_called_at_most_once` contract. The m2 implementation summary defended this caching choice as correct under "no scrape-time blocking I/O." Synthesizer recommends a separate `_live` Counter alongside `_startup` Gauge so the test contract stays clean — but this is an architectural decision the implementer should not make unilaterally.

**T4 — Star-count signal between briefs.** Research-frontier CAND-4 cites Evidently AI as "25,000+ GitHub stars"; oss-trends 2.3 cites "7,600 stars." Both are accurate at different points (Evidently has multiple repos; the canonical OSS repo is in the 7K range). Star-count discrepancy is a methodological note for the challenger.

**T5 — Schema/effort cost of new MCP tools.** CAND-16 (`get_corpus_delta`), CAND-18 (`session_corpus_mismatch` envelope field), and CAND-17 (`mcp.session.id` span attr) all require BP1 attention. CAND-16 and CAND-18 specifically re-pin `EXPECTED_TOOL_SCHEMA_SHA256`. The challenger needs to weigh BP1 invalidation cost against capability value — a known anti-pattern is "shipping a tool with low agent uptake but high BP1 amortization cost."

---

## 5. What's already in flight

- **CAND-1 (Prometheus alert rules):** the m2/m3 milestones shipped the gauges; the alert rules were flagged as "alert rule potential" in `.claude/notes/08-security-observability-ops.md` but never scheduled as ACs. No current in-flight milestone covers this.
- **CAND-3 (WAP write-time gate):** prior corpus-integrity-observability-m1 fixed the per-paper-batch chunk_count bug by routing through `count_rows()`; what's missing is the publication-gating reconciliation. No in-flight milestone.
- **CAND-4 (structlog):** `ingest/store.py::write_chunks_complete` event was added in e2; the startup log in `resources.py` was not retroactively updated. No in-flight milestone.
- **CAND-8 (integration test):** prior CAND-5a in the 2026-05-28 scout final report; listed as must-ship but never landed.
- **CAND-22 (LanceDB per-shard unindexed-rows spike):** open spike from prior final report; not addressed in m3 because the global-total decision was made first.
- **CAND-24 + CAND-25 (runbooks, make reconcile):** referenced in alert rules and tool docstrings but never created — represent unfinished deferral from m3 and e2.

---

## 6. Parking lot

- **HuggingFace `DatasetInfo.from_directory()` (comparative C1).** Design validation only — m2 already implements the equivalent `count_rows()`-from-artifact pattern. No code change needed.
- **LanceDB `checkout_latest()` design validation (comparative C8).** Design validation; the once-at-startup caching choice is correct per LanceDB docs. No code change.
- **CAND-23 (LanceDB v0.33 manifest-summary API).** API is experimental; defer until v1.0 stable. Re-evaluate next scout.
- **NabaOS tool receipts (multi-agent parking).** Covered by prior scout; no code; ranks behind implemented items.
- **BPD adversarial multi-agent monitoring (multi-agent parking).** Wrong threat model; arXMCP is single-user.
- **DVC / lakeFS / Quilt / Dolt (oss-trends parking).** Heavy data-lake infra; conflicts with local-first constraint.
- **Pandera as a runtime dep (oss-trends 2.2).** Importing Pandera violates no-fork-policy spirit (heavy transitive deps). The schema-validation IDEA lands natively as CAND-3.
- **Great Expectations as a runtime dep (oss-trends 2.4).** Same — the Expectation vocabulary lands natively as part of CAND-3.
- **Evidently as a runtime dep.** Same — the reference-baseline pattern lands natively as CAND-12.
- **Soda Core as a runtime dep.** Same — the YAML threshold-config pattern lands natively as CAND-21.
- **structlog as a project-wide replacement for stdlib logging.** Too broad a migration for one milestone. CAND-4 lands the narrow critical-path subset; broader migration is a separate proposal.
- **V3DB Zero-Knowledge Proofs for Vector Search (research-frontier parking).** ZKP overhead vs local-first single-user; off-axis.
- **DaQL / Stream DaQ streaming pipelines (research-frontier parking).** arXMCP is batch, not streaming.
- **Grafana promql-anomaly-detection (research-frontier parking).** Captured by CAND-11 (AVH-style native impl) without external infra.
- **`get_corpus_status` MCP tool (prior-run parking).** Re-parked — `/readyz` body already surfaces what's needed; no agent need expressed.

---

## 7. Orchestrator synthesis note

- Briefs were highly compatible — no direct disagreements. The dominant disagreement signal was *which lens* to apply (operator-facing vs agent-facing), surfaced in §4 Tension T1.
- The candidate count (25) is moderate — the corpus-integrity-observability scope is well-bounded and the prior scout's 16 candidates set a strong prior. Most of this run's value is in updating against the post-m1/m2/m3/e2/e3 shipped baseline.
- The challenger should specifically interrogate: (a) whether CAND-3 and CAND-1 are both needed or one suffices (T2); (b) the value density of CAND-16 / CAND-18 (T1, T5); (c) whether the multi-agent candidates align with arXMCP's pipeline reality (T1).
