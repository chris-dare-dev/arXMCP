# Comparative Landscape Brief — Corpus Integrity & Observability
**Scout run:** corpus-integrity-observability
**Date:** 2026-05-31
**Scope:** Corpus/index integrity, data-consistency, startup self-checks, metadata-vs-ground-truth discrepancies. Motivated by `ingest/store.py::write_chunks` writing `corpus-version.json` with `chunk_count=len(chunks)/paper_count` from only the last per-paper batch — a ~100x silent discrepancy nothing flagged.

**Prior run context:** The 2026-05-28 run `2026q2-observability-reporting` covered this scope in full and produced a final report with 16 ranked candidates (CAND-1 through CAND-16). The implementation milestones m1/m2/m3/e2/e3 have shipped against that catalog. This run confirms what has landed, surfaces any landscape changes since then, and identifies residual gaps.

---

## 1. TL;DR

The three highest-value capabilities that remain unimplemented or only partially addressed are: (1) **per-run ingest summary sentinel** exposing `ingest_last_run_papers`, `ingest_last_run_chunks`, and `ingest_last_run_timestamp_seconds` as Prometheus gauges rehydrated from `ingest-summary.json` (CAND-7/e3 — gauges defined but the reader hook completeness is worth confirming against the current state); (2) **dbt `source freshness` threshold-gated reporting** — the explicit `warn_after`/`error_after` window model applied to corpus-version staleness has no analog in arXMCP's daily report (CAND-9, unshipped per the prior final report); and (3) **Prometheus alert rule file** — no off-the-shelf catalog covers the "marker vs actual count divergence" alarm, and arXMCP could ship a trivial `infra/prometheus-alerts.yml` that operationalizes the m2 gauges. The main thematic gap is that the write-time and startup reconciliation defects are now closed (m1, m2, m3, e2, e3), but the **operator-facing reporting surface** (daily report corpus-integrity section, sample alert rules) has not landed.

---

## 2. Top Capability Candidates

---

### C1 — DatasetInfo reload-from-artifact pattern (recompute counts on load)

**Source system:** Hugging Face Datasets (Apache-2.0)

**Public evidence:** https://huggingface.co/docs/datasets/package_reference/main_classes — `DatasetInfo.from_directory()` "automatically updates all dynamically generated fields" (`num_examples`, `hash`, time of creation) by reading from the Arrow files on disk rather than trusting the persisted JSON metadata. The idiom is: write the metadata file at ingest time, but on load always recompute the count fields from the actual data, then compare.

**Capability angle:** arXMCP's `server/corpus.py` reads `CorpusVersionInfo` from `corpus-version.json` at startup — the m2 milestone added a startup `count_rows()` check that compares the marker value to the live table. The HuggingFace pattern extends this: the `DatasetInfo` file is explicitly a hint, not ground truth, and `from_directory()` re-derives counts from the artifact. If arXMCP's startup path emits a clearly named structured log field (`chunk_count_diverged`) whenever marker and table disagree, the divergence becomes test-assertable in CI via `caplog` assertions. The m2 implementation does emit a WARN, but whether the field name is machine-queryable is unconfirmed.

**Technical angle:** Zero new dependencies. One `count_rows()` call at startup (already cached in `Resources.startup_chunk_count` per m2). What remains is confirming the structured log field name is grep-able and that a CI test asserts it.

**Cross-reference to arXMCP:** `server/resources.py` (`Resources.startup` — calls `count_rows()` per m2). `server/health.py` — m2 comment block around `"chunk_count_diverged"` check. Largely implemented; structured field name and test coverage are unconfirmed.

---

### C2 — dbt `source freshness` threshold-gated staleness reporting

**Source system:** dbt (Apache-2.0)

**Public evidence:** https://docs.getdbt.com/reference/resource-properties/freshness — dbt's `warn_after`/`error_after` threshold model: a source's "most recent loaded_at" is compared to `now()`, emitting tiered pass/warn/error. The SQL executed is `SELECT MAX(loaded_at_field) AS max_loaded_at, CURRENT_TIMESTAMP AS snapshotted_at FROM source`.

**Capability angle:** arXMCP's daily report (`tools/daily_metrics_report.py`) reports metrics but has no threshold-gated corpus freshness check. Adding a `## Corpus integrity` section that classifies `corpus_version.json` age as `pass` / `warn` / `error` — using the `application/health+json` tiered model already in `server/health.py::compute_health_status` — would make the daily report machine-parseable for CI gating. This is CAND-9 from the prior run, which the final report explicitly listed as unshipped.

**Technical angle:** ~30 LOC in `tools/daily_metrics_report.py`. Reads the Prometheus metrics already exposed at `/metrics` (`arxmcp_corpus_chunk_count_marker`, `arxmcp_corpus_chunk_count_actual`) and computes a threshold-gated section. No new dependencies.

**Cross-reference to arXMCP:** `tools/daily_metrics_report.py` (existing daily ops report — no corpus integrity section). `server/health.py::compute_health_status` (tiered pass/warn/fail model for backup staleness — the exact pattern to copy). **CAND-9 — not shipped per prior final report §4**.

---

### C3 — Prometheus delta alert rule (marker vs actual count)

**Source system:** Qdrant (Apache-2.0); Elasticsearch/OpenSearch (Apache-2.0)

**Public evidence:** https://qdrant.tech/documentation/ops-monitoring/monitoring/ — `collection_points` vs `collection_indexed_only_excluded_points` as separate Prometheus time series; operators write alert rules firing when `points_count - indexed_vectors_count > N`. https://www.elastic.co/guide/en/elasticsearch/reference/8.19/cat-indices.html — `docs.count` vs `docs.deleted` as independent time series enabling delta rules.

**Capability angle:** arXMCP already exposes `arxmcp_corpus_chunk_count_marker` and `arxmcp_corpus_chunk_count_actual` (shipped per m2, `server/health.py:104–120`). The Qdrant/Elasticsearch pattern shows the PromQL alert rule: `abs(arxmcp_corpus_chunk_count_actual - arxmcp_corpus_chunk_count_marker) / clamp_min(arxmcp_corpus_chunk_count_actual, 1) > 0.05`. Shipping a `infra/prometheus-alerts.yml` with this rule (plus `arxmcp_corpus_unindexed_rows > 0` and `arxmcp_corpus_chunk_count_actual < 1`) closes the operator loop without any code change.

**Technical angle:** A single YAML file, < 30 LOC. No code change. All referenced metric names exist after m2/m3. The awesome-prometheus-alerts catalog (https://samber.github.io/awesome-prometheus-alerts/) confirms no off-the-shelf rule covers this pattern for local vector stores — arXMCP would be the first.

**Cross-reference to arXMCP:** `server/metrics.py` (`CORPUS_CHUNK_COUNT_MARKER`, `CORPUS_CHUNK_COUNT_ACTUAL`, `CORPUS_UNINDEXED_ROWS` — all shipped). `infra/` (placeholder README only — no alert rules). **Net-new file; zero code change**.

---

### C4 — Weaviate `vectorQueueLength` per-index unindexed-rows check

**Source system:** Weaviate (BSD-3-Clause)

**Public evidence:** https://docs.weaviate.io/deploy/configuration/status — `/v1/nodes` returns `shards[].objectCount` (total indexed objects per shard) and `shards[].vectorQueueLength` (objects waiting to be indexed, requires `ASYNC_INDEXING` enabled). The queue length is the per-shard analog of LanceDB's `num_unindexed_rows`.

**Capability angle:** arXMCP's m3 milestone added `CORPUS_UNINDEXED_ROWS` gauge (`server/health.py:122–134`) using LanceDB's `index_stats()`. Weaviate's pattern adds nuance: it checks per-index (per-shard) queue length, not just a global total. The prior final report left an open spike item: "confirm `num_partitions=1` synchronous HNSW build never leaves `num_unindexed_rows > 0` in normal operation, and that `tbl.list_indices()` exists in lancedb 0.30.x." This assumption governs whether the m3 implementation is correct. Weaviate's per-shard model suggests the right arXMCP check is per-ANN-index (one for `hnsw_stmt`, one for `hnsw_proof`) rather than a summed total.

**Technical angle:** The spike item is a single `lancedb_tbl.list_indices()` call in a test environment to confirm behavior. No code change until the spike is resolved.

**Cross-reference to arXMCP:** `server/health.py:122–134` (`CORPUS_UNINDEXED_ROWS` — shipped per m3). `server/resources.py` (startup `index_stats()` call — m3). The spike validation of `tbl.list_indices()` in lancedb 0.30.x: **open assumption from the prior final report**.

---

### C5 — SHA-256 sidecar checksum for corpus-version.json

**Source system:** freshprobe (MIT); arXiv S3 manifest (arXiv.org)

**Public evidence:** https://github.com/Sudhan30/freshprobe — computes SHA-256 of HTTP response body across repeated probes to detect content changes. https://info.arxiv.org/help/bulk_data_s3.html — arXiv S3 manifest records `md5sum` (tar package) AND `content_md5sum` (concatenated content) — two independent hash checks per artifact.

**Capability angle:** arXMCP writes `corpus-version.json` as a plain JSON file. A startup integrity check that computes `sha256(corpus-version.json)` and compares it to a sidecar `.corpus-version.json.sha256` written atomically alongside the marker would detect file-level corruption or manual editing — a different failure mode than the count mismatch addressed by m1/m2. The arXiv pattern of recording both package-hash and content-hash for independent verification is the fullest form; arXMCP would need only a single content hash.

**Technical angle:** `hashlib.sha256(json.dumps(marker_dict, sort_keys=True).encode()).hexdigest()` at write time, stored as a sidecar. At startup, recompute and compare. A mismatch triggers the same `DegradedState` path as the count divergence (m2). This is purely local-first and adds zero new dependencies.

**Cross-reference to arXMCP:** `ingest/store.py:658–762` (`write_corpus_version_marker` — writes JSON, no checksum). `server/corpus.py` (reads marker — no checksum verification). **Net-new integrity pattern; not in prior run candidates; addresses file-corruption failure mode**.

---

### C6 — Per-run paper range in ingest-summary.json

**Source system:** arXiv S3 bulk manifest (arXiv.org); OpenAlex snapshot (CC0)

**Public evidence:** https://info.arxiv.org/help/bulk_data_s3.html — arXiv S3 manifest records `first_item` / `last_item` (arXiv ID range) per tar alongside `num_items`. https://docs.openalex.org/download-all-data/openalex-snapshot — per-file URL entries make each data partition independently verifiable.

**Capability angle:** arXMCP's `ingest-summary.json` (e3, written by `ingest/oai_delta.py`) exposes `INGEST_LAST_RUN_PAPERS` and `INGEST_LAST_RUN_CHUNKS` as Prometheus gauges. The arXiv manifest pattern adds the concept of per-run paper range: `paper_id_min` / `paper_id_max` in the sentinel would make partial-ingest failures (where only 30 of 50 papers succeeded) visible without reading the full `store-stats.jsonl` JSONL. This is O(1) in the sentinel file size and unambiguous — if `paper_count == expected_total` but `paper_id_max - paper_id_min` doesn't span the expected range, a gap exists.

**Technical angle:** Extending `ingest-summary.json` with two string fields (`paper_id_min`, `paper_id_max`). The `paper_ids_processed` list would be O(N) and is not recommended; the min/max approach is O(1). The oai_delta.py writer already collects `paper_id` per call (via `WriteStats.paper_id`, e3) — a running `min`/`max` over the loop is trivial.

**Cross-reference to arXMCP:** `ingest/oai_delta.py` (ingest-summary.json writer — e3). `ingest/store.py:195` (`WriteStats.paper_id` — shipped per e3). `server/metrics.py:285–306` (`INGEST_LAST_RUN_*` gauges). **Partial implementation; paper range fields are absent from current sentinel**.

---

### C7 — Structured write-path event + CAND-5a regression test

**Source system:** arXMCP's own e2 milestone; confirmed by code at `ingest/store.py:961–969`

**Public evidence:** `ingest/store.py:961–969` — `write_chunks_complete` structured log event emitted at INFO with fields `corpus_version`, `chunk_count`, `paper_count`. `server/observability/logging_setup.py` — `JsonFormatter` installed by default when `ARXMCP_LOG_FORMAT=json` (e2).

**Capability angle:** The structured event is a machine-assertable ingest correctness signal. A `tests/test_store_write_integrity.py` test that calls `write_chunks` with a multi-paper synthetic corpus (e.g., 3 papers × ~30 chunks each), captures `caplog`, and asserts `record.chunk_count == tbl.count_rows()` on the `write_chunks_complete` event would be the CAND-5a regression test from the prior final report. Without it, the m1 bug class can silently regress (e.g., if a caller passes `chunk_count` as a parameter again). The test is the load-bearing guard.

**Technical angle:** ~25 LOC using the existing synthetic LanceDB fixture pattern (`tests/_graph_helpers.py`). No new dependencies. Pytest `caplog` captures structured log output from Python's logging module directly.

**Cross-reference to arXMCP:** `ingest/store.py:961–969` (`write_chunks_complete` event — shipped). `tests/_graph_helpers.py` (synthetic fixture helpers). `tests/` — CAND-5a regression test: **unconfirmed existence; the prior final report listed this as must-ship alongside CAND-1**.

---

### C8 — LanceDB `checkout_latest()` / pinned-version design validation

**Source system:** LanceDB (Apache-2.0)

**Public evidence:** https://docs.lancedb.com/tables/consistency — `read_consistency_interval` parameter: unset = no cross-process refresh; zero = check every read; non-zero = periodic check. `checkout_latest()` manually refreshes. These are the two APIs for managing version pinning vs. freshness tradeoffs.

**Capability angle:** arXMCP's `CORPUS_CHUNK_COUNT_ACTUAL` gauge (`server/health.py:111–120`) is explicitly cached once at startup and not refreshed at scrape time. The LanceDB consistency docs confirm this is the correct design for a single-writer system: `read_consistency_interval` unset means the server's pinned view is stable. The design comment in `server/health.py` is correct but implicit — the docs provide the explicit rationale that could be quoted in the implementation. This is a design validation, not a gap.

**Technical angle:** No code change needed. The implementation note could quote `docs.lancedb.com/tables/consistency` as the authority for the once-at-startup caching decision.

**Cross-reference to arXMCP:** `server/health.py:111–120` (once-at-startup cache comment — m2). **Design validation; confirms existing choice is architecturally grounded**.

---

### C9 — Daily report corpus-integrity section (CAND-9, unshipped)

**Source system:** dbt (Apache-2.0); arXMCP `server/health.py::compute_health_status`

**Public evidence:** https://docs.getdbt.com/docs/deploy/source-freshness — dbt's `dbt source freshness` command outputs a structured YAML/JSON report with per-source status (`pass`/`warn`/`error`) and max_loaded_at timestamp. arXMCP's `compute_health_status` in `server/health.py` already implements the IETF `application/health+json` tiered model for backup staleness and process uptime.

**Capability angle:** `tools/daily_metrics_report.py` is the operator-facing daily ops report. Adding a `## Corpus integrity` section with: (a) `corpus_version` header, (b) `marker_chunk_count` vs `actual_chunk_count` with a pass/warn/fail classification, (c) `unindexed_rows` status — would complete the "automatically catchable" goal stated in the scout brief. An operator running the daily report would see a `WARN: chunk_count_delta=192 (1.9%) — marker may be stale` line rather than discovering the bug by manual inspection.

**Technical angle:** The report already reads metrics from the running server (or from sentinel files). Reading `arxmcp_corpus_chunk_count_marker` and `arxmcp_corpus_chunk_count_actual` from `/metrics` (or from the startup-cached `Resources` values if the server is the reporter) and computing a delta is ~30 LOC. The threshold (>5% delta = warn, >20% = error) mirrors the IETF health+json convention already used in the server.

**Cross-reference to arXMCP:** `tools/daily_metrics_report.py` (no corpus integrity section). `server/health.py::compute_health_status` (tiered model to reuse). **CAND-9 — unshipped per prior final report; the metrics it would read are now available (m2/m3)**.

---

## 3. Sources Reviewed

| System | URL | What was read | High-signal? |
|---|---|---|---|
| LanceDB consistency docs | https://docs.lancedb.com/tables/consistency | `read_consistency_interval`, `checkout_latest()`, `on_bad_vectors` — confirms once-at-startup caching is correct for single-writer arXMCP | Yes — primary API docs |
| LanceDB indexing/reindexing | https://docs.lancedb.com/indexing/reindexing | `index_stats()` returns num_indexed_rows + num_unindexed_rows; zero = fully up-to-date | Yes — primary API docs |
| LanceDB changelog | https://docs.lancedb.com/changelog/changelog | 404 (path invalid); fallback to GitHub releases shows 2026 focus on DuckDB SQL / multi-bucket; no new integrity APIs | No (404) |
| Qdrant monitoring | https://qdrant.tech/documentation/ops-monitoring/monitoring/ | `collection_points`, `collection_indexed_only_excluded_points` (v1.16+) — confirms delta metric pattern | Yes — primary API docs |
| Weaviate cluster status | https://docs.weaviate.io/deploy/configuration/status | `stats.objectCount`, `shards[].vectorQueueLength`, `shards[].vectorIndexingStatus` — per-shard unindexed-queue pattern | Yes — primary API docs |
| arXiv S3 bulk manifest | https://info.arxiv.org/help/bulk_data_s3.html | `num_items`, `md5sum`, `content_md5sum`, `first_item`/`last_item` per tar | Yes — primary docs |
| OpenAlex snapshot format | https://docs.openalex.org/download-all-data/openalex-snapshot | Redshift manifest format, per-file URLs, incremental partition model | Partial |
| HuggingFace datasets DatasetInfo | https://huggingface.co/docs/datasets/package_reference/main_classes | `num_examples`, `dataset_size`, `from_directory()` reload-from-artifact idiom, `fingerprint` hash chain | Yes — primary API docs |
| dbt source freshness | https://docs.getdbt.com/reference/resource-properties/freshness | `warn_after`/`error_after` threshold model, `loaded_at_field` SQL check, tiered pass/warn/error | Yes — primary API docs |
| dbt source freshness deployment | https://docs.getdbt.com/docs/deploy/source-freshness | Per-source `pass`/`warn`/`error` output, structured JSON report shape | Yes — primary docs |
| Prometheus alerting rules | https://prometheus.io/docs/tutorials/alerting_based_on_metrics/ | `expr`, `for`, severity labels — PromQL alert rule structure | Yes — primary docs |
| Awesome Prometheus Alerts | https://samber.github.io/awesome-prometheus-alerts/ | 954 rules / 112 exporters — no corpus integrity rules for local vector stores (confirmed gap) | Yes — confirmed absence |
| freshprobe | https://github.com/Sudhan30/freshprobe | SHA-256 content fingerprinting, freshness_score, repeat probing; MIT license | Yes — primary README |
| blazickjp/arxiv-mcp-server | https://github.com/blazickjp/arxiv-mcp-server | 7 tools; no health/corpus-status surface | Yes — confirms absence |
| Semantic Scholar Datasets API | https://api.semanticscholar.org/api-docs/datasets | Rendered JS page — could not extract fields | No (JS page) |
| Pandera/Great Expectations survey | https://aeturrell.com/blog/posts/the-data-validation-landscape-in-2025/ | Pandera 0.29 (Jan 2026) with Polars/Ibis; no corpus-level count invariant pattern | Partial |
| Context7 MCP server | https://github.com/upstash/context7 | 2 tools: `resolve-library-id`, `query-docs`; no freshness/integrity surface | Yes — confirms absence |

---

## 4. Cross-References to arXMCP

- **C1 (HuggingFace reload-from-artifact):** `server/resources.py` (startup `count_rows()` — m2). `server/health.py` m2 block — structured `chunk_count_diverged` field: **confirm field name is machine-queryable**. Largely shipped.

- **C2 (dbt source freshness reporting):** `tools/daily_metrics_report.py` — no corpus integrity section. `server/health.py::compute_health_status` — tiered model to copy. **CAND-9 — unshipped per prior final report**.

- **C3 (Prometheus delta alert rule):** `server/metrics.py` (`CORPUS_CHUNK_COUNT_MARKER`, `CORPUS_CHUNK_COUNT_ACTUAL`, `CORPUS_UNINDEXED_ROWS` — all shipped). `infra/` — no alert rules file. **Net-new artifact; trivial effort**.

- **C4 (Weaviate vectorQueueLength / per-index check):** `server/health.py:122–134` (`CORPUS_UNINDEXED_ROWS` — m3). Open spike: `tbl.list_indices()` behavior in lancedb 0.30.x. **Spike item unresolved**.

- **C5 (SHA-256 sidecar checksum):** `ingest/store.py::write_corpus_version_marker` — no checksum. `server/corpus.py` — no checksum verification. **Net-new integrity pattern; not in prior run**.

- **C6 (per-run paper range in ingest-summary.json):** `ingest/oai_delta.py` (writer — e3). `ingest/store.py:195` (`WriteStats.paper_id` — e3). `paper_id_min`/`paper_id_max` fields: **absent from current sentinel**.

- **C7 (CAND-5a regression test):** `ingest/store.py:961–969` (`write_chunks_complete` event — e2). `tests/` — multi-paper regression test asserting `chunk_count == tbl.count_rows()`: **unconfirmed existence**.

- **C8 (LanceDB checkout_latest design validation):** `server/health.py:111–120` (once-at-startup comment). **Design validated by LanceDB docs; no change needed**.

- **C9 (daily report corpus-integrity section):** `tools/daily_metrics_report.py` — no corpus integrity section. **CAND-9 — same as C2; both point to the same unshipped daily-report addition**.

---

## 5. Themes

The dominant pattern across this survey is that the write-time and startup reconciliation gaps are **now closed** in arXMCP (m1/m2/m3/e2/e3), and the remaining work is the **operator-facing reporting layer** that makes the fixed invariants visible in the daily ops cadence. Every comparable system that manages a large corpus (HuggingFace, dbt, arXiv, OpenAlex) has an explicit human-readable or machine-parseable report surface that surfaces count/freshness status — arXMCP has the Prometheus gauges but not the daily-report section or sample alert rules that would make them actionable without standing up a full Prometheus stack. The second theme is that **content-hash integrity** (C5 — SHA-256 sidecar) is a standard pattern in HTTP-layer tools (freshprobe) and bulk-ingest provenance systems (arXiv S3 dual-hash) but is absent from arXMCP's local marker file; it addresses a distinct failure mode (corruption/tampering) from the count-mismatch class that m1/m2 address. The third theme is that the awesome-prometheus-alerts catalog confirms no off-the-shelf alert rule exists for "local vector-store metadata vs table count divergence" — arXMCP has an opportunity to define and document a rule pattern that the broader community lacks.

---

## 6. Out of Scope / Parking Lot

- **`get_corpus_status` MCP tool:** The prior final report explicitly parked this (CAND-6) due to `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` re-pin overhead with no concrete agent need; the `/readyz` body extension (e2) already surfaces `chunk_count` + `marker_chunk_count`. Not re-surfaced.

- **ChromaDB `collection.count()`:** Architecturally equivalent to LanceDB's `tbl.count_rows()` — the basis of m2. No net-new idea.

- **Semantic Scholar release diffs API:** An incremental corpus update pattern, not an integrity check; arXMCP's OAI-PMH delta loop (E11) is the analog. Out of scope.

- **Great Expectations / Pandera schema validation:** Validate column types and null rates, not count provenance. Useful for embedder output quality (E03/E05) but not the marker-vs-table class of bug. Noted for a potential future ingest quality gate epic.

- **Weaviate async replication Merkle tree:** Multi-node replication concern; arXMCP is single-process, single-workstation. Not applicable.

- **INSPIRE-HEP statistics API:** Aggregate record counts (1.8M+) but no per-ingest provenance or marker reconciliation surface. Too coarse for arXMCP's per-call audit use case.

- **Elasticsearch shard segment API (`_cat/segments`):** arXMCP uses LanceDB fragment model, not Lucene segments; no transfer beyond what C3 already covers.

- **dbt `unique` / `not_null` tests on corpus marker:** dbt requires a data warehouse backend; disproportionate for a one-call `count_rows()` check in a local-first system.
