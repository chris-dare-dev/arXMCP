# Comparative Landscape Brief — Observability & Reporting
**Scout run:** 2026q2-observability-reporting  
**Date:** 2026-05-28  
**Scope:** Corpus/index integrity, data-consistency, startup self-checks, metadata-vs-ground-truth discrepancies. Motivated by `ingest/store.py::write_corpus_version_marker` writing `chunk_count` and `paper_count` from only the last per-paper batch rather than the cumulative table total — a ~100x silent discrepancy nothing flagged.

---

## 1. TL;DR

The three highest-value capabilities to consider are: (1) **LanceDB `index_stats()` indexed/unindexed row delta exposed as a startup invariant check**, surfacing the exact class of silent staleness the motivating bug represents; (2) **Qdrant's `collection_points` vs `indexed_vectors_count` Prometheus delta metric**, which directly models the "metadata claim ≠ ground truth" alarm pattern at the metrics layer; and (3) **arXiv's per-chunk S3 manifest with `num_items` + `md5sum` per tar**, showing how bulk-ingest provenance systems record ground-truth counts alongside each committed artifact. The main thematic gap in arXMCP is the absence of a startup-time invariant that reconciles `corpus-version.json::chunk_count` against `tbl.count_rows()` — every comparable system that manages large corpora (Qdrant, Weaviate, LanceDB, OpenAlex) surfaces exactly this class of count and either exposes it as a metric or gates startup on it.

---

## 2. Top Capability Candidates

---

### C1 — Indexed/unindexed row delta as a startup guard

**Source system:** LanceDB OSS (Apache-2.0)

**Public evidence:** https://docs.lancedb.com/indexing/reindexing — `index_stats()` returns `num_indexed_rows` + `num_unindexed_rows`; documented: "This will be zero when indexes are fully up-to-date." The `IndexStatistics` interface (https://lancedb.github.io/lancedb/js/interfaces/IndexStatistics/) confirms `numIndexedRows`, `numUnindexedRows`, `indexType`, `distanceType`, `loss`, `numIndices` as the full field set.

**Capability angle:** An LLM agent or operator calling `readyz` would see an explicit count of rows that exist in the table but are NOT yet covered by the HNSW index — i.e. searches over them fall back to brute-force scan. If arXMCP surfaced `unindexed_rows` as a Prometheus gauge and checked `num_unindexed_rows == 0` before marking readiness (or at least logged it at startup), the marker–vs–table discrepancy class of bug would become visible immediately.

**Technical angle:** Single API call (`tbl.index_stats(index_name)`). arXMCP already calls `_create_indices` and reads `tbl.version` at write time (`ingest/store.py:862`); adding an `index_stats()` read costs one round-trip. The wrinkle: LanceDB's Python and JS APIs differ slightly in the stat field names (Python uses snake_case `num_indexed_rows`; JS interface uses camelCase). The Python 0.30.x API needs a specific index name passed — requires knowing the canonical names `"hnsw_stmt"` and `"hnsw_proof"` at startup read time.

**Cross-reference to arXMCP:** `ingest/store.py:558–628` (`_create_indices` — writes indices but never reads `index_stats()`); `server/corpus.py` (opens the table but never queries index stats); `server/health.py:159–229` (`/readyz` — does not include `unindexed_rows` check). No analog for exposing this as a metric or a startup gate. **Net-new as a guard/metric.**

---

### C2 — Ground-truth count reconciliation at write time (marker vs table)

**Source system:** arXiv S3 bulk manifest (arXiv.org)

**Public evidence:** https://info.arxiv.org/help/bulk_data_s3.html — each `<file>` entry in `arXiv_pdf_manifest.xml` carries `num_items` (count of PDFs/source files in that tar), `md5sum` (tar package checksum), `content_md5sum` (concatenated-content checksum), `first_item`, `last_item`, and byte `size`. This is the canonical example of a per-batch commit recording a ground-truth count (from the actual files written), not a count derived from an in-memory slice.

**Capability angle:** The motivating bug in arXMCP is structurally identical to if arXiv wrote `num_items=N` in the manifest from only the last batch of papers loaded into memory rather than counting all files actually written to the tar. The arXiv pattern of: (a) derive `num_items` from the artifact (the tar), not the in-memory list; (b) include both `md5sum` (package) and `content_md5sum` (content), so two independent checks can agree — is directly applicable as a design idiom. For arXMCP: derive `chunk_count` from `tbl.count_rows()` immediately after `merge_insert` completes, not from `len(chunks)` passed into the call.

**Technical angle:** `tbl.count_rows()` is a single SQL `COUNT(*)` — O(1) for most LanceDB configurations. The issue is that `write_corpus_version_marker` in `ingest/store.py:901` receives `chunk_count=len(chunks)` as a parameter from the caller, so the fix is purely at the call site: replace `len(chunks)` with a post-commit `tbl.count_rows()`. No schema change needed.

**Cross-reference to arXMCP:** `ingest/store.py:900–908` — the call to `write_corpus_version_marker(..., chunk_count=len(chunks))` is precisely the site of the bug. `ingest/store.py:658–762` (`write_corpus_version_marker`) trusts its `chunk_count` parameter without cross-checking the table. **Closest existing thing is the marker write itself; the reconciliation step is absent.**

---

### C3 — vectors_count vs indexed_vectors_count Prometheus metric (delta metric)

**Source system:** Qdrant (Apache-2.0)

**Public evidence:** https://qdrant.tech/documentation/ops-monitoring/monitoring/ — Qdrant exposes `collection_points` (total points per collection) and per-collection vector counts, plus `collection_indexed_only_excluded_points` (v1.16+). The well-known issue https://github.com/qdrant/qdrant/issues/4522 ("Discrepancy between indexed_vectors_count and points_count affecting query speed") documents that Qdrant tracks both `points_count` and `indexed_vectors_count` as observable metrics and that a discrepancy between them causes silent performance degradation — exactly the "silent divergence between persisted metadata and ground truth" class.

**Capability angle:** Qdrant's design exposes both the metadata count (indexed) and the ground-truth count (total points) as separate Prometheus time series so an operator can write an alert rule `points_count - indexed_vectors_count > 0`. arXMCP could analogously expose an `arxmcp_chunk_count_delta` gauge: `tbl.count_rows()` minus `corpus_version_marker.chunk_count`. A non-zero delta means the marker is stale.

**Technical angle:** In Qdrant this is a built-in metric because the indexer is a separate async optimizer and the gap is a normal operating state (small positive delta is expected during background reindexing). For arXMCP the gap should only ever be zero after a completed ingest — so the delta gauge doubles as an integrity alarm, not just an operational metric. Cost: one `tbl.count_rows()` call at startup, result stored in a Gauge and served at `/metrics`. The existing `CORPUS_VERSION_GAUGE` in `server/health.py:92` is the closest structural analog but only records the version integer, not the count.

**Cross-reference to arXMCP:** `server/health.py:92` (`CORPUS_VERSION_GAUGE`) — records version but not count. `server/metrics.py` — no `chunk_count_delta` gauge exists. `server/corpus.py` — opens the table but does not call `count_rows()` at startup. **Net-new gauge; closest analog is `CORPUS_VERSION_GAUGE`.**

---

### C4 — Per-node object count in readiness/status endpoint

**Source system:** Weaviate (BSD-3-Clause)

**Public evidence:** https://docs.weaviate.io/deploy/configuration/status — Weaviate's node status endpoint returns per-shard object counts ("Total number of indexed objects on the node"), queue lengths for pending vector indexing (when ASYNC_INDEXING is enabled), and schema synchronization status. The `/v1/.well-known/ready` endpoint returns 503 when shards report `INDEXING` status, preventing traffic routing to a node that has not finished indexing.

**Capability angle:** Weaviate's design provides the pattern of embedding object count in the readiness response body — so `GET /readyz` returns not just `ready/not_ready` but also the count of indexed objects, making a discrepancy immediately visible in any readiness poll. For arXMCP: the `/readyz` response at `server/health.py:219–229` already returns `{"status": "ready", "warm": {...}}` — adding `"chunk_count": N` and `"marker_chunk_count": M` to this body costs nothing and makes the divergence visible to any caller who parses the JSON.

**Technical angle:** `count_rows()` on a pinned LanceDB table returns the total rows in that versioned view. Adding it to the readiness body requires reading it once during lifespan startup (`server/main.py` startup path) and caching it in `Resources`. A mismatch between the marker value and the live count would log a WARNING at startup — zero runtime overhead after startup.

**Cross-reference to arXMCP:** `server/health.py:159–229` (`readyz` handler) — currently returns warm-map only. `server/main.py` (lifespan) — where a one-time `count_rows()` could be called. **Extends existing `readyz`; no new module needed.**

---

### C5 — Ingest provenance manifest as a per-run artifact

**Source system:** OpenAlex snapshot manifest (CC0 1.0 Universal license)

**Public evidence:** https://developers.openalex.org/download-all-data/snapshot-data-format — OpenAlex manifest uses Redshift manifest format; each entry has a `url` pointing to a data file within an `updated_date` partition. The manifest-presence-as-integrity-signal idiom: "if the manifest is present, all data files are complete." Manifest is deleted at the start of a write and recreated on completion — atomic commit signal.

**Capability angle:** arXMCP's `ingest/store.py` already writes `store-stats.jsonl` (append log of per-write `WriteStats`) and `corpus-version.json` (last-write summary). The gap is that neither file is an artifact that can be compared against the live table to assert completeness. An OpenAlex-style ingest manifest would record per-paper chunk counts (committed rows per paper_id), total row count at commit, the LanceDB version, and a hash of the chunks batch — making a future `store.py` call auditable against `SELECT COUNT(*) FROM chunks WHERE paper_id = X`.

**Technical angle:** arXMCP's `WriteStats.to_dict()` already records `rows_inserted`, `rows_updated`, `lancedb_version`, and `chunk_count`. The gap is that `chunk_count` records `len(chunks)` (the batch size), not the post-commit total. Extending `WriteStats` to include a `total_rows_after_commit` field derived from `tbl.count_rows()` after `_create_indices` would make every JSONL line an auditable record.

**Cross-reference to arXMCP:** `ingest/store.py:173–203` (`WriteStats` dataclass) — records per-call stats but misses cumulative table count. `ingest/store.py:636–651` (`_append_store_stats`) — writes the stats to JSONL. **Partial analog; the cumulative count field is missing.**

---

### C6 — Structured startup self-check log with assertable fields

**Source system:** Semantic Scholar S2 Open Data Platform

**Public evidence:** arXiv:2301.10140 (Lo et al., 2023) — the S2 platform's open data release documentation describes the `datasets/v1` endpoint (https://api.semanticscholar.org/api-docs/datasets) returning per-dataset file lists with `release_id`, `diff_from_release_id` for incremental updates, and the expectation that "the dataset is consistent" once a release is complete. The S2ORC paper (https://arxiv.org/pdf/1911.02782) describes a structured metadata record per corpus snapshot including paper count, field distribution, and version string — all designed to be machine-parseable for downstream consistency checking.

**Capability angle:** arXMCP emits an INFO log line at startup that reads the `corpus-version.json` marker. That log line currently includes `version`, `chunker_version`, `embedder_version`, `paper_count`, and `chunk_count` as read from the marker file — but does NOT include the ground-truth value from `tbl.count_rows()` or `tbl.index_stats()`. Structured startup log lines that include both `marker_chunk_count` and `actual_chunk_count` (derived from the live table) would make the bug class visible: a log parser or a `grep` on `"chunk_count_mismatch"` would catch it. S2's convention of emitting structured release metadata aligns with this: every release is a queryable record, not a narrative log line.

**Technical angle:** Zero infrastructure overhead. The startup path in `server/corpus.py` (where `CorpusVersionInfo` is populated from the marker file) could issue one `tbl.count_rows()` call and compare — then log at WARNING if they diverge. A `chunk_count_mismatch` structured field (present only when divergent) makes it grep-able.

**Cross-reference to arXMCP:** `server/corpus.py:109+` (`CorpusVersionInfo` dataclass — populated from the marker file at startup); `server/main.py` (lifespan startup — where the INFO log is emitted). The `CorpusVersionInfo` class could gain a `live_chunk_count: int` field. **No analog for the reconciliation log line; the marker-read log exists but doesn't cross-check.**

---

### C7 — Index-staleness Prometheus gauge with alert rule

**Source system:** Elasticsearch/OpenSearch `_cat/indices` + `/_stats` (Apache-2.0)

**Public evidence:** https://www.elastic.co/guide/en/elasticsearch/reference/8.19/cat-indices.html — Elasticsearch `_cat/indices` returns `docs.count`, `docs.deleted`, `store.size`, `pri.store.size`, `segments.count`, and index health (`green/yellow/red`) for every index. The `/_stats` endpoint (https://docs.opensearch.org/latest/api-reference/index-apis/stats/) returns per-shard `docs.count` vs `docs.deleted` — the difference is the effective live row count. This pattern of health-classifying the gap between total stored and total indexed is well-established in Lucene-based systems.

**Capability angle:** For arXMCP: a Prometheus gauge `arxmcp_chunks_table_row_count` that is set from `tbl.count_rows()` at scrape time (or at startup and then updated post-ingest) would allow an alert rule `arxmcp_chunks_table_row_count != arxmcp_corpus_marker_chunk_count` to fire whenever the marker and the table diverge. Currently `CORPUS_VERSION_GAUGE` records the version integer but no per-version row count is exposed. Elasticsearch's pattern demonstrates this is standard ops hygiene for search indices.

**Technical angle:** `tbl.count_rows()` is a LanceDB `COUNT(*)` scan — O(1) per LanceDB docs for versioned tables. Reading it at each `/metrics` scrape would be a ~1ms overhead per scrape interval. Alternatively, read it once during startup and re-read it only after an ingest completion event. The marker file's `chunk_count` field provides the value to compare against without any additional API.

**Cross-reference to arXMCP:** `server/metrics.py` — no `chunks_table_row_count` gauge exists. `server/health.py:92` (`CORPUS_VERSION_GAUGE`) — only version int. `server/health.py:237+` (`refresh_metrics_from_singleton_state`) — the scrape-time hook that would host this gauge refresh. **Net-new Prometheus gauge; natural addition to the scrape hook.**

---

### C8 — Functional tool probe in readiness (beyond resource warm-up)

**Source system:** MCP health check patterns (community)

**Public evidence:** https://fast.io/resources/implementing-mcp-server-health-checks/ — describes three tiers: liveness (process up), readiness (JSON-RPC event loop responsive), and "functional status" (downstream dependencies accessible, including database query executes, authentication valid, memory usage within bounds). The functional probe fires a real query — e.g. `SELECT COUNT(*) FROM chunks` — to verify the data layer is actually responsive, not just open.

**Capability angle:** arXMCP's `/readyz` checks `resources.warm` (embedder, LanceDB handle, reranker booleans) but does not execute a test query against the LanceDB table. A functional probe that runs `tbl.count_rows()` and compares the result to the marker's `chunk_count` would catch: (a) the table open succeeded but is empty (silent crash), (b) the table count diverges from the marker (motivating bug class), (c) the index_stats show `num_unindexed_rows > 0` (staleness). These three checks together constitute a "corpus integrity functional probe" that distinguishes "LanceDB handle is open" from "corpus data matches expectations."

**Technical angle:** The functional probe runs once during lifespan startup (`server/main.py::lifespan`). A `count_rows()` call at that point costs one round-trip. The result can be cached in `Resources` and compared against `corpus_info.chunk_count` (from the marker). If divergent, `Resources.degraded` can be set — reusing the existing `DegradedState` machinery in `server/corpus.py:110–135`.

**Cross-reference to arXMCP:** `server/corpus.py:140+` (`open_chunks_table_with_fallback`) — opens table with fallback on corruption. `server/main.py` (lifespan) — where startup probing occurs. `server/health.py:203–217` (degraded-mode 503 path) — already handles a `DegradedState`. **Extends existing startup + degraded-mode machinery; no new module needed.**

---

### C9 — Per-paper chunk-count audit log

**Source system:** arXiv + Semantic Scholar ingest pipelines (public architecture)

**Public evidence:** arXiv's S3 manifest records `first_item` and `last_item` (the arXiv ID range) alongside `num_items` (count per tar), so a consumer can verify that every paper in a range contributed exactly one item. S2's open data platform (arXiv:2301.10140, §3.2) describes per-paper metadata records including version-tracking at the paper granularity. Both treat the per-paper record count as an auditable unit, not just the batch total.

**Capability angle:** arXMCP's `write_chunks` is called once per paper (per the bulk ingest loop). The `store-stats.jsonl` records `chunk_count` per call but does not record `paper_id` — so if paper X contributed 0 chunks (silent drop), the JSONL records a `chunk_count=0` line but nothing cross-checks against the expected yield for that paper. Adding `paper_id` to `WriteStats` and logging it would make the per-paper audit trail completable: an operator can `grep '"paper_id": "2301.12345"'` in `store-stats.jsonl` to see exactly what that paper contributed.

**Technical angle:** Trivial schema extension to `WriteStats.to_dict()`. The `paper_id` is already available in the calling context — `bulk_ingest` and `re_embed` iterate over papers and call `write_chunks` per paper. A cosmetic addition of `paper_id: str | None` to `WriteStats` makes the JSONL auditable at the paper granularity.

**Cross-reference to arXMCP:** `ingest/store.py:173–203` (`WriteStats` — missing `paper_id`). `ingest/store.py:636–651` (`_append_store_stats`). **Partial analog in `store-stats.jsonl`; paper-id tracking is absent.**

---

### C10 — Snapshot version reporting at tool-call level

**Source system:** Context7 (Apache-2.0) + OpenAlex

**Public evidence:** Context7 (https://github.com/upstash/context7) does NOT expose corpus freshness or version in its tool results — a notable gap identified in this survey. OpenAlex's manifest-presence-as-integrity-signal (present = all files written, absent = in-progress) provides a clean commit-signal model. The Semantic Scholar API release notes page (https://www.semanticscholar.org/product/release-notes) exposes a named `release_id` per dataset snapshot so consumers can detect when their local copy is stale.

**Capability angle:** arXMCP's `search_papers` and `get_chunk` result envelopes include `corpus_version` in the response metadata (the snippet contract at `.claude/docs/snippet-contract.md`). The capability gap: there is no MCP tool that lets an LLM agent directly query "what does my corpus claim vs what does the table actually contain?" — i.e. a `get_corpus_status` tool returning `{marker_chunk_count, live_chunk_count, delta, unindexed_rows, corpus_version}`. Such a tool would be unique among surveyed systems (none of them expose this).

**Technical angle:** A new tool `get_corpus_status` (or a richer `/readyz` body) would consolidate: marker-file values, `tbl.count_rows()`, `tbl.index_stats()` for each embedding column. It requires no schema changes, just a new handler calling existing LanceDB APIs. The returned delta is the key operator signal.

**Cross-reference to arXMCP:** `server/tools.py::ALL_TOOLS` — no corpus-status tool currently registered. `server/health.py:219–229` (`readyz` 200 body) — closest existing surface. **Net-new MCP tool; partially serviced by `/readyz` but without count reconciliation.**

---

## 3. Sources Reviewed

| System | URL | What was read | High-signal? |
|---|---|---|---|
| LanceDB — index_stats | https://docs.lancedb.com/indexing/reindexing | `index_stats()` fields, `num_indexed_rows`, `num_unindexed_rows`, reindexing behavior | Yes — primary API docs |
| LanceDB — IndexStatistics interface | https://lancedb.github.io/lancedb/js/interfaces/IndexStatistics/ | Full field list for `IndexStatistics`: `numIndexedRows`, `numUnindexedRows`, `distanceType`, `loss`, `numIndices` | Yes — API reference |
| LanceDB — consistency | https://lancedb.com/docs/tables/consistency/ | 404 — page not found at this path | No (404) |
| arXiv S3 bulk data | https://info.arxiv.org/help/bulk_data_s3.html | Manifest XML format: `num_items`, `md5sum`, `content_md5sum`, `first_item`, `last_item`, `size`, `timestamp` per tar chunk | Yes — primary docs |
| OpenAlex snapshot format | https://developers.openalex.org/download-all-data/snapshot-data-format | Manifest-presence-as-integrity-signal; Redshift manifest format; `url` per entry; entries list | Partial — format overview only, no checksums documented |
| Qdrant monitoring | https://qdrant.tech/documentation/ops-monitoring/monitoring/ | `collection_points` gauge (v1.16+), `collection_vectors`, `collection_indexed_only_excluded_points`, `/telemetry` endpoint, per-collection API metrics (v1.18+) | Yes — primary API docs |
| Qdrant — indexed/unindexed issue | https://github.com/qdrant/qdrant/issues/4522 | `indexed_vectors_count` vs `points_count` discrepancy report and known behavior | Yes — primary evidence of the pattern |
| Weaviate cluster status | https://docs.weaviate.io/deploy/configuration/status | Node status: object counts per shard, queue lengths (INDEXING state), schema sync status; `/v1/.well-known/ready` returns 503 when shards are INDEXING | Yes — primary docs |
| Semantic Scholar Datasets API | https://api.semanticscholar.org/api-docs/datasets | Navigation-only rendered; could not extract field list | No (rendered page issue) |
| Semantic Scholar open data paper | https://arxiv.org/html/2301.10140v2 | Release structure: per-paper structured metadata, diff/incremental model, `release_id` | Yes — primary paper |
| arXiv-mcp-server README | https://github.com/blazickjp/arxiv-mcp-server/blob/main/README.md | 4 tools: `search_papers`, `download_paper`, `list_papers`, `read_paper`; no health/corpus-stats surface; local filesystem only | Yes — primary source |
| Context7 README | https://github.com/upstash/context7 | 2 tools: `resolve-library-id`, `query-docs`; no freshness/version/health surface exposed via MCP | Yes — primary source |
| Elasticsearch `_cat/indices` | https://www.elastic.co/guide/en/elasticsearch/reference/8.19/cat-indices.html | `docs.count`, `docs.deleted`, `store.size`, index health status (`green/yellow/red`), segment count | Yes — primary API docs |
| OpenSearch index stats | https://docs.opensearch.org/latest/api-reference/index-apis/stats/ | Page content not accessible in fetch; general knowledge supplemented | Partial |
| MCP health check patterns | https://fast.io/resources/implementing-mcp-server-health-checks/ | Three-tier model: liveness / readiness / functional-status; functional probe pattern described | Yes — primary |
| Elicit corpus sourcing | https://support.elicit.com/en/articles/553025 | Sources papers from Semantic Scholar; 250M+ papers; no per-corpus consistency surface visible | Low (marketing-adjacent) |
| FastMCP | https://gofastmcp.com/updates | Framework ergonomics; no corpus stats or integrity patterns relevant to this scope | Low (framework only) |

---

## 4. Cross-References to arXMCP

- **C1 (LanceDB index_stats startup guard):** No analog. `ingest/store.py:558–628` writes indices but never reads back `index_stats()`. `server/corpus.py` opens the table but does not query `index_stats()`.

- **C2 (Ground-truth count from table at write time):** The motivating bug site. `ingest/store.py:900–908` passes `chunk_count=len(chunks)` to `write_corpus_version_marker` rather than `tbl.count_rows()`.

- **C3 (Prometheus delta metric — marker vs live count):** No analog in `server/metrics.py`. `CORPUS_VERSION_GAUGE` (health.py:92) records version only. `refresh_metrics_from_singleton_state` (health.py:237) is the hook where a `chunk_count_delta` gauge refresh belongs.

- **C4 (Object count in readiness body):** `server/health.py:219–229` — current readyz 200 body has `status` + `warm` only. No `chunk_count` or `marker_chunk_count` field.

- **C5 (Per-run ingest manifest):** `ingest/store.py:173–203` (`WriteStats`) — partial analog. Missing: `total_rows_after_commit` (cumulative post-write table count) and `paper_id` per write.

- **C6 (Structured startup log with assertable fields):** `server/corpus.py` reads marker file and populates `CorpusVersionInfo`. No reconciliation log line comparing `marker.chunk_count` to `tbl.count_rows()`. `server/main.py` lifespan is where such a log line belongs.

- **C7 (Index-staleness Prometheus gauge):** `server/metrics.py` — no `chunks_table_row_count` gauge. The scrape hook `refresh_metrics_from_singleton_state` (health.py:237) is the natural host.

- **C8 (Functional tool probe in readiness):** `server/corpus.py:140+` (`open_chunks_table_with_fallback`) provides the fallback skeleton. The functional count-check probe (count_rows + compare to marker) is absent from the startup path. The `DegradedState` machinery exists and could receive a new `reason="chunk_count_mismatch"` variant.

- **C9 (Per-paper chunk-count audit log):** `ingest/store.py:173–203` (`WriteStats`) — missing `paper_id` field. `ingest/store.py:636–651` (`_append_store_stats`) — writes the JSONL.

- **C10 (Corpus-status MCP tool):** `server/tools.py::ALL_TOOLS` — no such tool registered. `server/health.py:219–229` is the closest surface but not an MCP tool.

---

## 5. Themes

The dominant pattern across every high-signal source is that mature systems bifurcate metadata (a file, a marker, a manifest) from ground truth (the actual store's row count) and then actively reconcile the two — either at scrape time via a Prometheus delta metric, at startup via a readiness gate, or at write-completion via a functional assertion. arXMCP already has the marker file and the metrics infrastructure; what it lacks is the reconciliation step that bridges them. The second pattern is that "unindexed rows" (vectors in the table but not yet in the HNSW index) is a distinct observable state from "table count mismatch" — LanceDB's `index_stats()` and Qdrant's `indexed_vectors_count` both surface this as a first-class metric, and arXMCP has the index write machinery but not the read-back check. Third, every system that handles bulk ingest (arXiv S3, OpenAlex, S2) treats count-per-artifact as a write-time invariant, not a read-time check — the right fix for arXMCP is to derive `chunk_count` from `tbl.count_rows()` at write time, not to add a post-hoc validator that compensates for an incorrect recorded value.

---

## 6. Out of Scope / Parking Lot

- **Elasticsearch shard segment API** (`_cat/segments`, `/_segments`): Rich segment-level introspection, but arXMCP uses LanceDB's internal fragment model, not Lucene segments — the analogy doesn't transfer to actionable implementation ideas beyond what the `_cat/indices` row-count pattern already covers.

- **Connected Papers / ResearchRabbit neighborhood expansion**: These are UI products; their "coverage" surface is not operator-observable via an API or tool call — no primary evidence of a corpus-stats endpoint.

- **ChromaDB `collection.count()` + `heartbeat()`**: ChromaDB's `count()` is the exact capability (count rows in a collection), but arXMCP already uses LanceDB's `tbl.count_rows()` API which is architecturally equivalent. No net-new idea.

- **INSPIRE-HEP statistics endpoint**: Their public API exposes aggregate record counts (1.8M+ literature records as of 2025) but not a per-ingest-run provenance manifest — the resolution is too coarse for arXMCP's per-call audit use case.

- **Weaviate ASYNC_INDEXING queue-length metric**: The async indexing queue is a Weaviate-specific architectural feature (background vector indexing separate from object storage). arXMCP's LanceDB write model calls `_create_indices` synchronously — the queue-length metric concept doesn't transfer since there is no async queue; the staleness is captured by `num_unindexed_rows` from `index_stats()` instead (C1 above).

- **Elicit / Consensus search quality reporting**: These systems report query-level confidence but not corpus-level integrity. Their provenance surface is at the citation level (per-claim sentence links), not at the corpus-metadata level arXMCP needs.

- **zbMATH corpus statistics**: zbMATH Open's public API exposes paper counts and MSC classification distributions but no ingest provenance or metadata-vs-table reconciliation surface relevant to this scope.

- **S2ORC bulk download checksums**: S2ORC provides per-shard `.gz` files with a shard manifest but the API to download it requires S2 authorization and the fields documented publicly do not include per-record checksums (unlike arXiv's S3 manifest). Deprioritized as lower-evidence than arXiv S3.
