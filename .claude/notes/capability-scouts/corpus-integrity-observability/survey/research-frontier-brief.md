# Research-Frontier Brief — corpus-integrity-observability
**Scout run:** 2026-05-31  
**Scope:** Observability and reporting for corpus/index integrity — specifically the class of bug where a persisted metadata field (e.g. corpus-version.json `chunk_count`) silently diverges from ground-truth table state, and wrong values go unnoticed in startup logs / reports.

---

## 1. TL;DR

Top-3 methods to consider: **(1) Write-Audit-Publish (WAP) pattern applied to the ingest store write path** — a lightweight, code-only pre-commit invariant that gates marker publication on a confirmed row-count reconciliation; **(2) Pandera-style schema + invariant validation at write-time** — a zero-infrastructure Python library that lets you declare row-count bounds and cross-field consistency rules as first-class test predicates that fire on every write, not just in CI; **(3) structlog + pytest-structlog assertable structured logging** — the only pattern that makes startup log emission machine-testable in-process without standing up a scrape endpoint. The main thematic shift in the literature is from "dashboard shows metrics" to "assertions at write time and startup block bad state from being persisted in the first place" — the dominant 2024–2025 pattern treats data validation as a gate on the write path, not a lagging indicator scraped from a running system.

---

## 2. Method candidates

### CAND-1: Write-Audit-Publish (WAP) pattern — ingest pre-commit invariant

**Method name:** Write-Audit-Publish (WAP) — as a local ingest gate  
**Year + author:** Pattern formalized in Apache Iceberg (2021–2022); resurged in 2024 practitioner literature; no single academic paper — the canonical reference is the Dagster blog post and the lakeFS implementation guide.  
**Primary citation:** Dagster blog "Write-Audit-Publish pattern in Pipelines", https://dagster.io/blog/python-write-audit-publish (2024). Apache Iceberg spec table-branch mechanics is the underlying primitive.  
**Summary:** WAP inserts an explicit audit step between writing data to a staging branch/version and publishing it to the canonical production pointer. In the arXMCP context, the precise analogue is: `write_chunks` merges rows into LanceDB and creates a new dataset version; the marker (`corpus-version.json`) is the "publish" step. WAP says: between the merge and the marker write, run a count reconciliation — `tbl.count_rows(version=new_version)` must equal the accumulated total the writer tracked internally; only on equality should the marker be written. The motivating bug class (marker `chunk_count` = 106 while table has 10298 rows) is exactly what WAP's audit step closes: the audit step would have compared the writer's running total to `count_rows()` and refused to publish the marker with the wrong count.  
**Compute footprint:** Pure algorithm. One `count_rows()` call per `write_chunks` invocation (O(1) in LanceDB's columnar format — reads footer metadata, not full scan). No GPU, no model download.  
**Implementation complexity:** ~20–40 LOC delta to `ingest/store.py`. No OSS reference impl for this exact context, but the `notebook_reconcile_marker.py` tool already contains the reconciliation logic (`_recount_lancedb`) that would move to the write path. The new primitive is: raise `RuntimeError` (not `assert`) if `count_rows()` != `stats.total_rows_after_commit` before writing the marker.  
**arXMCP fit:** `ingest/store.py::write_chunks` — the marker-write path (already writes `corpus-version.json` at the end of `write_chunks`). The reconciliation call would be added between `_create_indices()` and the marker-write.  
**Maturity signal:** Widely adopted in Apache Iceberg, Delta Lake, and Apache Hudi (pre-commit validator). The Dagster blog post is practitioner-grade, not academic; the pattern is independently implemented in lakeFS, Databricks, and AWS Glue.

---

### CAND-2: Pandera write-time schema and invariant validation

**Method name:** Pandera — dataframe schema validation with statistical checks  
**Year + author:** Niels Bantilan (Union.ai), OSS; v0.20 (Polars/PyArrow support) shipped 2024, v1.x stable.  
**Primary citation:** Pandera documentation https://pandera.readthedocs.io; PyPI: `pandera` — Apache-2.0 license. No single academic paper — production maturity is evidenced by 3,500+ GitHub stars, 500K+ monthly PyPI downloads, and adoption in Prefect, Airflow, and Kedro pipelines.  
**Summary:** Pandera lets you declare a typed schema for a PyArrow or Pandas table — column types, null constraints, value ranges, and custom `Check` objects that can assert any invariant (e.g. `Check(lambda s: s.sum() > 0, element_wise=False)` to assert a chunk_count column is non-zero). The schema is evaluated at call-site via a function decorator or an explicit `schema.validate(table)` call. Applied to arXMCP, you would declare a `CorpusMarkerSchema` asserting `chunk_count > 0` and `chunk_count <= row_count_from_table` (a cross-field check), then validate the marker dict before writing it. Any violation raises `SchemaError` (not `assert`, so not stripped by `-O`). The key advantage over a raw `if ... raise` check is that the schema is composable, reusable across test and production, and produces structured error messages that land in the log output with field-level detail.  
**Compute footprint:** Pure CPU, negligible (column type checks + range checks over a dict or small dataframe). No GPU.  
**Implementation complexity:** ~30 LOC for the schema declaration + `schema.validate()` call. OSS reference impl: https://github.com/unionai-oss/pandera (Apache-2.0). No model download needed.  
**arXMCP fit:** `ingest/store.py` (marker payload validation before write) and optionally `ingest/schema.py` (LanceDB table schema cross-checks). Could also validate `WriteStats.to_dict()` output before appending to `store-stats.jsonl`. Note: arXMCP pins PyArrow; Pandera supports PyArrow natively as of v0.20.  
**Maturity signal:** 3,500+ GitHub stars, 500K+/month downloads, Polars + PyArrow backends added 2024. Widely cited in 2025 data-validation landscape surveys. Production-ready since v0.9; no breaking changes in v1.x migration.

---

### CAND-3: structlog + pytest-structlog — assertable startup invariants

**Method name:** structlog `capture_logs()` / pytest-structlog `log.has()` — structured logging with machine-testable event fields  
**Year + author:** Hynek Schlawack (structlog, MIT), current stable 25.5.0 (2025); pytest-structlog: Wim Glenn (MIT), active.  
**Primary citation:** structlog documentation https://www.structlog.org/en/stable/testing.html; pytest-structlog: https://github.com/wimglenn/pytest-structlog (MIT).  
**Summary:** The motivating bug also manifested as "wrong values in startup logs going unnoticed." The fix is to make startup log emissions machine-testable. structlog's `capture_logs()` context manager (or pytest-structlog's `log` fixture) captures every log event emitted during a test as a Python dict, enabling assertions like `assert {"event": "corpus_marker_loaded", "marker_chunk_count": 106, "table_chunk_count": 10298} in log.events`. If the startup code emits a `logger.warning("corpus marker divergence detected", marker_count=..., table_count=..., delta=...)` structured event, a test can assert both that the warning fires and that its numeric fields are correct. This turns startup log emission from documentation into executable invariants. The pattern closes the "wrong values in startup logs going unnoticed" problem: you write one test that exercises the divergence path, assert the structured log fields, and future regressions fail the test suite rather than silently passing.  
**Compute footprint:** Zero — pure in-process test infrastructure. No network, no GPU.  
**Implementation complexity:** Adding structlog to arXMCP is a ~1-line dependency change (it is already a Python logging replacement, not a separate service). pytest-structlog adds `log` fixture to existing pytest tests. The actual assertions are ~5–10 LOC per invariant path. OSS: structlog (MIT) at https://github.com/hynek/structlog; pytest-structlog (MIT) at https://github.com/wimglenn/pytest-structlog.  
**arXMCP fit:** `server/main.py` lifespan startup (the chunk-count divergence log already emits via `server/health.py` — the gap is that it emits to stdlib `logging`, not structlog, so it is not field-assertable in tests). The fit is: migrate the startup divergence logger to structlog, write a pytest test using `capture_logs()` that exercises the `Resources.startup()` path with a mock `count_rows()` returning a divergent count, and assert the structured fields.  
**Maturity signal:** structlog is the de-facto standard for structured Python logging in production FastAPI/Starlette deployments. 3,500+ GitHub stars. pytest-structlog is narrower (400+ stars) but is the only dedicated pytest plugin for this pattern. Both are actively maintained as of 2025.

---

### CAND-4: Evidently — open-source ML/data drift monitoring, local mode

**Method name:** Evidently AI — ML observability framework with dataset drift reports  
**Year + author:** Evidently AI (Emeli Dral, Elena Samuylova), MIT, v0.5.x 2024–2025.  
**Primary citation:** https://github.com/evidentlyai/evidently (MIT). 25,000+ GitHub stars. Academic origin: "Evidently" presented at various MLOps conferences 2022–2023; current v0.5 includes LLM/RAG evaluation presets (2024).  
**Summary:** Evidently compares a "reference" dataset to a "current" dataset and produces structured drift reports across 20+ statistical tests (PSI, KS, Wasserstein, etc.) and 100+ metrics. Applied to arXMCP's corpus-integrity problem: after every ingest run, run `DataDriftPreset` comparing the distribution of chunk counts, embeddings norms, or other scalar statistics between the previous corpus snapshot and the new one. A sudden jump in `chunk_count` distribution (e.g. all values collapsing to a single outlier) would be flagged as drift. The LLM/RAG preset added in 2024 includes a `RetrievalQualityPreset` that can run against the eval fixture to detect retrieval regression. Local mode requires no server — reports are emitted as JSON or HTML.  
**Compute footprint:** Drift detection on scalar statistics is CPU-only, seconds per run. The retrieval-quality preset is heavier (requires running the embedding model), but the corpus-integrity use case (count distributions, metadata distributions) is lightweight.  
**Implementation complexity:** ~50 LOC to integrate as a post-ingest cron step producing `var/arxmcp/ops/drift-reports/<date>.json`. The Evidently report can be exposed as a sentinel file readable by the existing scrape hook. OSS: https://github.com/evidentlyai/evidently (MIT).  
**arXMCP fit:** A new cron step (alongside `ops/drift_check.py` for LaTeXML drift) that runs after bulk ingest and produces a corpus-level drift report. The report's `drift_detected` boolean could gate the existing `eval-quarantine.flag` mechanism. Also fits `tools/daily_metrics_report.py` — the daily report could import the latest Evidently JSON and include a "corpus drift" section.  
**Maturity signal:** 25,000+ GitHub stars, actively maintained, includes RAG/LLM eval presets as of v0.5 (2024). Used in production by Booking.com, Olist, and others. The most mature OSS drift-monitoring library for local, single-process use.

---

### CAND-5: ReproRAG — RAG reproducibility benchmarking framework

**Method name:** ReproRAG — quantifying RAG pipeline reproducibility via Exact Match Rate, Jaccard Similarity, Kendall's Tau  
**Year + author:** Multiple authors, arXiv 2509.18869, September 2025.  
**Primary citation:** arXiv:2509.18869, "On The Reproducibility Limitations of RAG Systems" (2025). Open-sourced (license not confirmed in abstract; verify before use).  
**Summary:** ReproRAG measures non-determinism in vector-based retrieval by running the same queries multiple times under different conditions (different embedding models, hardware, insertion order) and measuring Exact Match Rate (do the same top-k documents appear?), Jaccard Similarity (overlap of result sets), and Kendall's Tau (rank correlation). For arXMCP's corpus-integrity concern, the key finding is that **dynamic data insertion is one of the most significant sources of result variation** — directly confirming that the order in which `write_chunks` is called per-paper affects ANN index state and thus retrieval results. A startup-time reproducibility check based on ReproRAG's Exact Match Rate metric (re-run N fixed queries against the pinned corpus version; compare top-k result sets to a stored golden set; flag if EMR drops below a threshold) would catch index corruption or unexpected index rebuild that changes ranking.  
**Compute footprint:** Requires running the embedding model (BGE-M3) and ANN search for N queries. For a 20-query golden fixture this is a ~30s CPU-bound check (no GPU needed with quantized BGE-M3).  
**Implementation complexity:** ~100 LOC extending the existing `tests/eval/` fixture infrastructure. The golden query set already exists (`tests/fixtures/queries.json`). The new primitive is a result-set comparison at startup or post-ingest rather than only in `make eval`. No separate model download needed (BGE-M3 is already loaded).  
**arXMCP fit:** Extends `server/resources.py::startup()` (post-warmup, compare top-k for N fixed queries to stored golden results; emit a structured log event on mismatch) and/or a `tools/eval_smoke_test.py` cron step. Would close the gap between "nDCG@5 evaluator that runs weekly" and "startup-time sanity check that runs every startup."  
**Maturity signal:** arXiv:2509.18869, open-sourced. 2025 paper, limited citation count as of May 2026 (new). Methodological maturity is high — Exact Match Rate and Kendall's Tau are well-established retrieval metrics.

---

### CAND-6: LLM Readiness Harness — CI gates for RAG/LLM systems

**Method name:** LLM Readiness Harness — multi-dimensional readiness scoring with CI quality gates  
**Year + author:** Multiple authors, arXiv:2603.27355, March 2026.  
**Primary citation:** arXiv:2603.27355, "LLM Readiness Harness: Evaluation, Observability, and CI Gates for LLM/RAG Applications" (2026). License of reference implementation not confirmed.  
**Summary:** The harness combines OpenTelemetry tracing, automated benchmarks, and CI quality gates that actively block deployment when metrics regress. It aggregates retrieval hit rate, latency, cost, policy compliance, and groundedness into a "readiness score" with Pareto frontiers. The CI gate pattern is the most applicable piece: define a readiness threshold (e.g. retrieval hit rate >= 0.80, corpus chunk count within 5% of marker), run the harness as a post-ingest step, and refuse to update the corpus pointer if the threshold is not met. This is the academic formalization of what the WAP pattern implements operationally. The key idea novel to this paper: **readiness is not a single metric** — a composite score over retrieval quality + corpus integrity + latency guards against gaming a single threshold.  
**Compute footprint:** OTel tracing is near-zero overhead. The retrieval benchmark requires embedding + ANN search for the benchmark query set. CI mode is designed to run in minutes.  
**Implementation complexity:** The paper's reference implementation is tied to Azure OpenAI (not directly portable). The ideas are implementable in ~200 LOC against arXMCP's existing eval harness. The core primitive (run eval fixture, compare to stored threshold, refuse corpus pointer update on regression) is already partially present in `ops/watchdog_eval.py`.  
**arXMCP fit:** `ops/watchdog_eval.py` + `ingest/bulk_ingest.py` — extends the existing quarantine-flag mechanism to include corpus-integrity invariants (not just nDCG@5 regression) as a gate on `notebook_cutover.py`.  
**Maturity signal:** arXiv:2603.27355, published March 2026 — very new. The ideas (OTel + eval + CI gates) are each mature independently; this paper combines them with a readiness-score formalism. Weight: paper idea, low OSS maturity, but the individual components (OTel, promptfoo, RAGAS) are production-grade.

---

### CAND-7: Auto-Validate by-History (AVH) — automated data quality constraint generation

**Method name:** Auto-Validate by-History (AVH) — automatically infers data quality constraints from historical pipeline execution statistics  
**Year + author:** Multiple authors, KDD 2023 (arXiv:2306.02421). Applied at Microsoft on 2000 production pipelines.  
**Primary citation:** arXiv:2306.02421, "Auto-Validate by-History: Auto-Program Data Quality Constraints to Validate Recurring Data Pipelines" (KDD 2023).  
**Summary:** AVH observes historical execution statistics for a recurring data pipeline (e.g. daily ingest: papers_processed, chunks_written, rows_after_commit) and automatically generates statistical constraints — "chunks_written should be between 80% and 120% of the rolling 7-day mean." On each new run, the constraint is checked and the pipeline is blocked if the metric is outside its historical normal range. Applied to arXMCP: after N successful ingest runs, AVH would learn that `total_rows_after_commit` grows by approximately (new_papers x avg_chunks_per_paper); a run where it jumps by 100x or drops to zero would be flagged. The paper reports precision guarantees and approximate algorithms — not just "flag outliers" but "flag with controlled false-positive rate."  
**Compute footprint:** Pure statistical algorithm (rolling means, percentiles, IQR). CPU-only, negligible. Runs in milliseconds on a 100-entry history JSONL.  
**Implementation complexity:** ~100 LOC reading `var/arxmcp/ops/store-stats.jsonl` (already exists) and computing rolling bounds. No OSS reference impl publicly released (Microsoft internal). The algorithm (IQR-based or Z-score-based bounds on historical per-run metrics) is vanilla statistics, implementable natively.  
**arXMCP fit:** `ingest/bulk_ingest.py` post-run check, reading `store-stats.jsonl` for historical data. Also fits as a cron step alongside the drift watchdog. The existing `WriteStats.to_dict()` and the new `ingest-summary.json` sentinel provide exactly the time-series data AVH needs.  
**Maturity signal:** KDD 2023 (peer-reviewed), validated on 2000 production pipelines at Microsoft. No public OSS impl. The algorithmic idea is simple enough that a faithful implementation is ~100 LOC of vanilla Python/NumPy.

---

### CAND-8: "Still Fresh?" — temporal drift in retrieval benchmarks

**Method name:** Temporal benchmark drift detection via corpus snapshot comparison  
**Year + author:** Multiple authors, arXiv:2603.04532, March 2026.  
**Primary citation:** arXiv:2603.04532, "Still Fresh? Evaluating Temporal Drift in Retrieval Benchmarks" (2026). Code released.  
**Summary:** The paper compares two corpus snapshots taken one year apart for technical documentation corpora (FreshStack), measuring whether queries remain answerable and whether model rankings are stable (Kendall's tau up to 0.978). The main finding for arXMCP: **if you store a golden evaluation fixture against a specific corpus version and the corpus changes, benchmark validity should be re-checked** — specifically whether the relevant documents still exist at their expected chunk_ids. This is a systematic check that the arXMCP eval fixture (`tests/fixtures/queries.json`) can run: on every corpus version bump, verify that the expected chunk_ids for each query are still present in `count_rows()` output. A missing chunk_id means corpus corruption or an unexpected chunk_id reassignment.  
**Compute footprint:** Pure metadata check (lookup chunk_ids in the LanceDB table, no embedding needed). Runs in seconds.  
**Implementation complexity:** ~30 LOC extending `tools/validate_eval_fixtures.py` to cross-check expected chunk_ids against the live table. The tool already validates fixture structure; this adds a liveness check.  
**arXMCP fit:** `tools/validate_eval_fixtures.py` + startup resource check in `server/resources.py`. Could be added to the `make eval` target as a pre-flight gate.  
**Maturity signal:** arXiv:2603.04532 (March 2026), code released. Very new; methodological maturity is solid (the snapshot-comparison method is simple and well-understood).

---

## 3. Sources reviewed

| Venue | URL pattern | Papers / sources scanned | High-signal? |
|---|---|---|---|
| arXiv cs.DB | https://arxiv.org/abs/2306.02421 | Auto-Validate by-History (KDD 2023) | YES |
| arXiv cs.SE | https://arxiv.org/abs/2603.27355 | LLM Readiness Harness (2026) | YES (ideas) |
| arXiv cs.IR | https://arxiv.org/abs/2603.04532 | "Still Fresh?" benchmark drift (2026) | YES |
| arXiv cs.IR | https://arxiv.org/abs/2509.18869 | ReproRAG reproducibility (2025) | YES |
| arXiv cs.DB (older) | https://arxiv.org/abs/2108.13557 | ML Pipeline Observability (VLDB 2022) | PARTIAL (too old / infra-heavy) |
| arXiv misc | https://arxiv.org/abs/2603.03065 | V3DB zero-knowledge vector proofs (2026) | NO (ZKP overkill for local-first) |
| GitHub OSS | https://github.com/evidentlyai/evidently | Evidently AI OSS library | YES |
| GitHub OSS | https://github.com/unionai-oss/pandera | Pandera OSS library | YES |
| GitHub OSS | https://github.com/hynek/structlog | structlog OSS library | YES |
| GitHub OSS | https://github.com/wimglenn/pytest-structlog | pytest-structlog plugin | YES |
| Practitioner blog | https://dagster.io/blog/python-write-audit-publish | WAP pattern (Dagster 2024) | YES |
| Practitioner guide | https://lakefs.io/blog/how-to-implement-write-audit-publish/ | WAP implementation guide | YES |
| Practitioner docs | https://pandera.readthedocs.io | Pandera documentation | YES |
| Practitioner docs | https://www.structlog.org/en/stable/testing.html | structlog testing docs | YES |
| Web survey | production RAG observability CI gates 2025 | RAG eval practice landscape | PARTIAL |

---

## 4. Themes

The most prominent 2024–2026 shift is from **lagging-indicator dashboards to write-path invariant gates**: the field has moved from "scrape metrics and alert later" to "validate data before it is persisted and block the write on failure." Write-Audit-Publish, Pandera, and the emerging CI-gate RAG harnesses all embody this shift. Second, **structured logging as a test primitive** is gaining traction — the pattern of making startup log emissions field-assertable in tests (via `capture_logs()` or pytest-structlog) treats observability output as a first-class contract, not an afterthought. Third, **reproducibility checking for retrieval indices** is an emerging sub-field (ReproRAG, "Still Fresh?") that directly addresses whether an index-rebuild or corpus-version bump silently changes retrieval behavior. Fourth, consistent with the prior scout lesson (2026-05-28): all high-signal methods for a local-first, single-workstation system come from **practitioner documentation and OSS libraries**, not novel academic papers — the academic papers (AVH, ReproRAG, "Still Fresh?") contribute specific metrics and algorithms, but the implementable form is always an OSS library or a standard engineering pattern.

---

## 5. Already in arXMCP / already considered

- **Prometheus gauges `arxmcp_corpus_chunk_count_marker` and `arxmcp_corpus_chunk_count_actual`** — both exist in `server/health.py:104–120` and are set at startup. The divergence IS exposed via `/metrics`. What is missing: (a) a write-time invariant that prevents the wrong value being persisted in the first place, and (b) a structlog-assertable structured log event for the divergence path.
- **`tools/notebook_reconcile_marker.py`** — already implements MVCC-pinned `count_rows()` reconciliation. The gap: it is a CLI tool run reactively, not a pre-write gate in `ingest/store.py`.
- **`ingest/ingest_summary.py`** — already writes `total_rows_after_commit` to `var/arxmcp/ops/ingest-summary.json`. The gap: no cross-check between `chunks_written_this_run` and the stored `chunk_count` in `corpus-version.json`.
- **`server/health.py::compute_health_status`** — already surfaces corpus version, backup staleness, disk usage. The gap: no corpus count-divergence check in the `checks` dict (only exposed as a Prometheus gauge, not as a `/status` `checks` entry).
- **`ops/watchdog_eval.py`** — nDCG@5 watchdog already implements a quarantine-flag gate on corpus cutover. The gap: the gate is retrieval-quality-only, not corpus-integrity (marker vs table count).
- **Restic backup** (E11_S05) — already implemented. Drift detection post-restore is not tested.
- **LaTeXML drift detection** (`ops/drift_check.py`, E10_S04) — already implemented for parser output drift. Not for corpus count drift.
- **Phoenix (Arize)** — already in `.claude/notes/10-references-and-prior-art.md` under "Observability." Retrieval-eval views are an explicit design reference. NOT superseded by Evidently (different scope — Phoenix is for LLM tracing; Evidently is for dataset drift).
- **Evidently** — not mentioned in `.claude/notes/10-references-and-prior-art.md` and not in any existing module. CAND-4 is genuinely new.
- **Pandera** — not mentioned in prior art or existing modules. CAND-2 is genuinely new.
- **structlog + pytest-structlog** — structlog is not yet a dependency (`pyproject.toml` uses stdlib `logging`). CAND-3 is genuinely new.
- **WAP pattern** — not mentioned in any design notes or existing code as an explicit gate. CAND-1 is genuinely new.
- **AVH / Auto-Validate by-History** — not mentioned in prior art. CAND-7 is genuinely new.

---

## 6. Out of scope / parking lot

| Paper / method | Rejection reason |
|---|---|
| V3DB: Zero-Knowledge Proofs for Vector Search (arXiv:2603.03065) | ZKP cryptographic overhead is wildly disproportionate for a local-first single-user system; verifiability against external clients is not a requirement. |
| ML Pipeline Observability VLDB 2022 (arXiv:2108.13557) | Pre-window (2022), and the proposed system is a "bolt-on monitoring service" requiring separate infra — not local-first. The problem framing is correct but the solution complexity is wrong. |
| Evidently's LLM-as-judge "Retrieval Quality Preset" (heavy mode) | Requires API calls to a hosted LLM; conflicts with arXMCP's no-hosted-LLM-at-runtime constraint for server-side tooling. The dataset-drift mode (CAND-4) is the local-first safe subset. |
| DaQL / Stream DaQ (arXiv:2506.06147) | Targets streaming data pipelines and Flink/Kafka environments. arXMCP's ingest is batch (OAI-PMH delta loop), not streaming. |
| DVC + MLflow lineage | DVC requires a Git-tracked data directory and remote; MLflow requires a tracking server. Both add infra arXMCP explicitly avoids. Lineage is already covered by LanceDB MVCC version integers and `store-stats.jsonl`. |
| ReproRAG startup-time full benchmark (heavy mode) | Running all N queries with BGE-M3 on every server startup is too expensive for a startup health check. The lightweight variant (CAND-5, N=20 query eval smoke test as a post-ingest cron step) is the implementable scope. |
| LLM Readiness Harness reference implementation | Tied to Azure OpenAI; not directly portable. Ideas surfaced via CAND-6; the reference implementation is rejected. |
| Grafana promql-anomaly-detection (github.com/grafana/promql-anomaly-detection) | Requires Grafana + Prometheus scrape infrastructure external to the server. Z-score idea is captured more simply by CAND-7 (AVH-style rolling bounds in Python). |
| "Detecting Dataset Drift via k-NN" (arXiv:2305.15696, 2023) | Pre-window. Targets feature drift in model inputs, not corpus-count metadata divergence. Pandera (CAND-2) and Evidently (CAND-4) subsume its use case with better OSS support. |
