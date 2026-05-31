# OSS Trends Brief — Corpus Integrity & Observability

**Scout run ID:** corpus-integrity-observability
**Date:** 2026-05-31
**Scout:** capability-scout-oss-trends (claude-sonnet-4-6)

---

## 1. TL;DR

**Top-3 projects worth borrowing from:** structlog (design-pattern lift for
assertable structured log fields and `capture_logs()` test harness), Pandera
(design-pattern lift for assertion-at-write DSL — schema-level row-count and
statistical checks), and Evidently AI (design-pattern lift for dataset-level
statistic drift detection with a pass/fail test-suite surface).

**Main thematic gap in arXMCP:** the `ingest/store.py` bug — where
`corpus-version.json::chunk_count` was written with `len(chunks)` (the
per-batch size, ~106) rather than `tbl.count_rows()` (ground truth, ~10 298)
— is an instance of a **write-time invariant gap**: the system has no
automated check that verifies "what the marker file records == what the
underlying table actually contains," and nothing in the startup path, the ops
report, or the Prometheus `/metrics` surface alerted on the ~100x discrepancy.
Every project in this brief addresses one or more faces of that same gap.

---

## 2. Project Candidates

### 2.1 structlog

- **URL:** https://github.com/hynek/structlog
- **License:** Apache-2.0 / MIT (dual; permissive)
- **Stars / last commit:** 4 800 stars / v25.5.0 released October 2025
- **What it does:** structlog replaces Python's stdlib logging with a
  processor-chain model where every log call produces an immutable event
  dictionary. Each processor receives `(logger, method_name, event_dict)`
  and returns a (possibly mutated) dict. The final processor renders the dict
  as JSON, logfmt, or pretty console output. Bound loggers accumulate
  `key=value` context via `.bind()` — context bleeds neither across async
  tasks nor across OS threads. The `structlog.testing.capture_logs()`
  context manager captures the event-dict stream so tests can assert on
  specific field values (`assert cap_logs[0]["chunk_count"] == 10298`).
- **Specific capability worth borrowing:** `capture_logs()` for test-time
  assertions on structured log fields, and the processor-chain pattern that
  makes every log call carry machine-readable fields (`corpus_version`,
  `chunk_count`, `paper_count`, `lancedb_version`) that CI can grep or
  pytest can assert. arXMCP already uses stdlib `logging.getLogger` with
  unstructured `%s`-style messages; none of the `write_corpus_version_marker`
  log calls carry assertable numeric fields.
- **arXMCP positioning:** Design-pattern lift. Wire `structlog` as the
  project-wide log renderer (drop-in on top of the existing `logging`
  hierarchy via `stdlib.recreate_defaults()`). Add `capture_logs()`-based
  pytest assertions in `tests/test_ingest_store.py` that check
  `event="corpus_marker_written"`, `chunk_count=<ground truth>`,
  `paper_count=<ground truth>`. This makes the ~100x discrepancy a test
  failure in CI, not a silent production surprise. Landing module:
  `ingest/store.py` + `tests/test_ingest_store.py`.
- **Risk flags:** Zero runtime overhead when configured as a stdlib pass-
  through; no GPU deps; no distributed systems. The Apache-2.0/MIT dual
  license is unambiguous. Single-workstation-friendly. Low risk.

---

### 2.2 Pandera

- **URL:** https://github.com/unionai-oss/pandera
- **License:** MIT
- **Stars / last commit:** 4 400 stars / v0.31.1 released April 2026
- **What it does:** Pandera provides a schema-declaration and assertion DSL for
  dataframe-like objects. A `DataFrameSchema` or `DataFrameModel` specifies
  column types, nullable rules, and custom `Check` functions that run at
  validation time. `DataFrameSchema.validate(df)` raises
  `SchemaError` (with a structured report) if any assertion fails.
  DataFrame-level checks (`checks=[]` at the schema level) can assert on
  cross-column properties, row counts, or statistical bounds. v0.29+
  supports Pandas, Polars, DuckDB/Ibis, PySpark, and xarray. v0.31.1
  released April 2026 — actively maintained under Union.ai.
- **Specific capability worth borrowing:** The **DataFrame-level check** that
  asserts `len(df) >= N` or `abs(len(df) - expected) < threshold`, applied
  at the ingest write boundary. For arXMCP this would look like a
  `@pa.check_input` or `@pa.check_output` decorator on `write_chunks` that
  validates the arrow table passed to `tbl.merge_insert` before the write
  commits. More concretely: a post-write `Check` comparing
  `tbl.count_rows()` to the marker's `chunk_count` catches the exact
  discrepancy the live bug produced. The DSL separates "what must be true"
  from "where to enforce it."
- **arXMCP positioning:** Design-pattern lift (native re-implementation,
  not import). The project already bans implicit deps; the Pandera idiom to
  adopt is: at write-time in `write_chunks`, after `merge_insert`, assert
  `tbl.count_rows() == sum(stats.rows_inserted + all prior rows)`. Wire this
  as a `RuntimeError`-raising post-write invariant (matches arXMCP's
  `assert`-is-banned convention: `if … raise RuntimeError`). Pandera's
  schema-declaration syntax is the design teacher; the implementation is a
  ~10-line guard in `ingest/store.py`. Landing module: `ingest/store.py`.
- **Risk flags:** Pandera itself carries `pandas`, `pydantic`, `scipy`-optional
  and other transitive deps that arXMCP does not need; the no-fork policy
  rules out adding pandera as a runtime dep. The *idea* (invariant DSL at
  boundary) is the borrow, not the library. Low risk for the design-lift
  approach.

---

### 2.3 Evidently AI

- **URL:** https://github.com/evidentlyai/evidently
- **License:** Apache-2.0
- **Stars / last commit:** 7 600 stars / v0.7.21 released March 2026
- **What it does:** Evidently is a Python framework for evaluating and
  monitoring ML/LLM systems and data pipelines. The `TestSuite` / `Report`
  APIs accept a `current` dataset and an optional `reference` dataset and run
  100+ metrics. `RowCount`, `MissingValues`, `ColumnDrift`,
  `DatasetDriftScore` — each produces a structured pass/fail result. The
  `RowCount` test specifically supports conditions like
  `gte(Reference(relative=0.1))` (current count >= reference count – 10%).
  Self-hosted OSS version requires no cloud connectivity; runs entirely
  in-process.
- **Specific capability worth borrowing:** The **reference-based RowCount
  test** pattern: persist a "last-known-good" row count (the reference) after
  a successful full ingest, then on each subsequent incremental ingest or
  server startup, assert current `tbl.count_rows()` is >= reference * (1 -
  tolerance). This makes corpus shrinkage (e.g. a botched cutover that
  deletes rows) an automatic failure rather than a silent drift discovered
  hours later. The arXMCP analogue: the `corpus-version.json` marker already
  stores `chunk_count`; adding a startup check that reads the marker and
  asserts `tbl.count_rows() == marker.chunk_count` (with a small tolerance
  for MVCC compaction) implements this pattern natively in
  `server/corpus.py::open_chunks_table`.
- **arXMCP positioning:** Design-pattern lift. The specific pattern is a
  "marker-vs-table reconciliation check" at two sites: (a) post-write in
  `ingest/store.py` (same session as the write), and (b) at server startup
  in `server/corpus.py` when `open_chunks_table` reads the marker. The
  Evidently reference-dataset model is the design teacher. Evidently itself
  is not imported (heavy dep tree, ML model drift context not needed).
  Landing modules: `ingest/store.py` + `server/corpus.py`.
- **Risk flags:** Evidently itself is a large dep (100+ metrics, optional
  ML packages). The borrow is purely the reference-baseline + pass/fail test
  idiom, not the library. The OSS core runs locally without cloud. The
  project is actively maintained by the Evidently team through 2026.

---

### 2.4 Great Expectations (assertion DSL only)

- **URL:** https://github.com/great-expectations/great_expectations
- **License:** Apache-2.0
- **Stars / last commit:** 11 500 stars / active 2026
- **What it does:** Great Expectations defines an "Expectation" vocabulary:
  `expect_table_row_count_to_equal(N)`,
  `expect_column_values_to_not_be_null("chunk_id")`,
  `expect_table_row_count_to_be_between(min, max)`. Each Expectation is a
  named, parameterized, composable assertion that runs against a data batch.
  A `Checkpoint` groups Expectations into a validation pass and produces a
  structured JSON validation result with `success: true|false` and per-
  expectation detail. The `StoreMetricsAction` writes metric history so
  consecutive runs can compare across time.
- **Specific capability worth borrowing:** The **Expectation vocabulary
  naming discipline**: rather than ad-hoc log messages like
  `"wrote N chunks"`, every data-boundary assertion in arXMCP's ingest
  pipeline should have a canonical name and structured result
  (`assert_table_row_count_equals`, `assert_marker_matches_table`, etc.)
  stored in a persistent results log (JSONL). The GX `Checkpoint` pattern —
  "run named assertions, emit a structured pass/fail result, persist it" — is
  directly implementable as a lightweight `IngestAssertion` dataclass in
  `ingest/store.py` that writes to `var/arxmcp/ops/ingest-assertions.jsonl`.
- **arXMCP positioning:** Design-pattern lift (NOT an import). GX itself is
  a substantial framework with cloud-sync dependencies and a complex setup;
  arXMCP needs the vocabulary concept, not the framework. Implement a
  minimal `IngestAssertion(name, expected, actual, passed)` dataclass and a
  `run_post_write_assertions` function in `ingest/store.py` that appends to
  `ops/ingest-assertions.jsonl`. Landing module: `ingest/store.py`.
- **Risk flags:** GX itself has a large dep tree and optional cloud SaaS;
  never import it. The design idea (named-assertion DSL + structured result
  persistence) is well within arXMCP's capability. Study-only.

---

### 2.5 LanceDB (manifest summary + table stats, v0.33.0)

- **URL:** https://github.com/lancedb/lancedb
- **License:** Apache-2.0
- **Stars / last commit:** Active; v0.33.0 released May 28, 2026
- **What it does:** LanceDB is arXMCP's existing vector store. v0.33.0 (May
  2026) adds a "manifest summary" feature (accessible from the `Version`
  object) and a "hint file to eliminate manifest scans." The Lance file format
  now includes "experimental column statistics for predicate pushdown." The
  manifest summary provides metadata-level counts and statistics about the
  dataset at a given version — accessible without a full table scan.
- **Specific capability worth borrowing:** The **manifest summary API**
  (`tbl.version_info()` or similar) to cheaply verify that the dataset
  version recorded in `corpus-version.json` exists in LanceDB's version
  history and that its row count matches the marker's `chunk_count`. This is
  cheaper than `tbl.count_rows()` at startup and doesn't require scanning
  all data files. arXMCP's `server/corpus.py::open_chunks_table` could call
  the manifest summary rather than a full count-rows at startup to perform
  the reconciliation check.
- **arXMCP positioning:** Design-pattern lift (already a runtime dep).
  Add a `_verify_corpus_version_marker()` function in `server/corpus.py`
  that calls `tbl.version_info()` at startup, reads `corpus-version.json`,
  and logs a `CRITICAL` event if `marker.chunk_count != table.row_count`.
  Wire this into the `/readyz` path so the server refuses to mark itself
  ready when the discrepancy exceeds a threshold (e.g. >5%). Landing module:
  `server/corpus.py`.
- **Risk flags:** Already a project dep (no new dep-bloat). The manifest
  summary API is described as experimental in v0.33.0 — call it through
  `tbl.count_rows()` as fallback if the API isn't stable. LanceDB ships on
  a monthly cadence; the feature is real and recent.

---

### 2.6 Prometheus + Alertmanager (delta-gauge alert pattern)

- **URL:** https://github.com/prometheus/prometheus / https://prometheus.io
- **License:** Apache-2.0
- **Stars / last commit:** 57 000+ stars / active 2026
- **What it does:** Prometheus is the standard open-source time-series
  monitoring system. The `prometheus-client` Python library (already a
  project dep via `pyproject.toml`) exposes `Gauge` and `Counter` metric
  types. A `Gauge` for "current table row count" and a separate `Gauge` for
  "marker-recorded row count" produce a computable delta
  `(table_rows - marker_rows)` that can be scraped, graphed, and alerted on.
  Prometheus alerting rules (`.yml` rules file) define conditions like
  `abs(arxmcp_table_rows - arxmcp_marker_rows) > 100` → fire
  `CorpusMarkerDrift` alert with severity=critical.
- **Specific capability worth borrowing:** The **dual-gauge delta pattern**:
  expose `arxmcp_corpus_table_rows` (set by querying LanceDB at startup and
  on each ingest) and `arxmcp_corpus_marker_rows` (set by reading
  `corpus-version.json` at startup). The delta between them is zero under
  correct operation and ~10 000 under the reported bug. An alerting rule on
  `abs(arxmcp_corpus_table_rows - arxmcp_corpus_marker_rows) > 500` would
  have fired within the first Prometheus scrape after the buggy ingest.
  arXMCP already exports a `/metrics` endpoint via `prometheus-client` —
  this is a 3-metric addition to `server/metrics.py`, not a new system.
- **arXMCP positioning:** Design-pattern lift (prometheus-client already a
  dep). Add `arxmcp_corpus_table_rows_total` (Gauge), `arxmcp_corpus_marker_rows_total`
  (Gauge), and `arxmcp_corpus_marker_drift` (Gauge = abs(table - marker))
  to `server/metrics.py`. Populate them in `server/corpus.py::open_chunks_table`
  at startup. A Prometheus alerting rule file in `infra/` closes the
  detection gap. Landing module: `server/metrics.py` + `server/corpus.py` +
  `infra/alerts.yml`.
- **Risk flags:** prometheus-client is already a dep. Zero new system
  dependencies. Alertmanager is optional (alerts still appear in Prometheus
  expression browser without it). macOS-compatible. No GPU.

---

### 2.7 structlog `capture_logs()` test-assertion pattern (as a standalone entry)

See §2.1 above — this is the same project. Calling it out separately because
the **testing** capability (`capture_logs()` for pytest assertions on log
fields) is distinct from the **production logging** capability (structured
event dicts). Both are worth implementing; they compose.

**Telescoped entry for the table:** same URL/license/stars as §2.1.
Specific testing capability: `structlog.testing.capture_logs()` yields a list
of event-dict snapshots — each snapshot is a plain Python dict assertable in
pytest. Tests for `write_corpus_version_marker` could assert
`cap_logs[-1]["chunk_count"] == tbl.count_rows()` to pin that the logged
value matches ground truth. If the writer ever regresses to `len(chunks)`, the
test fails with a clear diff.

---

### 2.8 Soda Core (check DSL)

- **URL:** https://github.com/sodadata/soda-core
- **License:** Apache-2.0
- **Stars / last commit:** 2 400 stars / actively maintained 2025
- **What it does:** Soda Core is a Python library and CLI for expressing data
  quality checks in a YAML DSL. A `checks.yml` file contains:
  ```yaml
  checks for chunks:
    - row_count > 0
    - row_count between 9000 and 15000
  ```
  Running `soda scan -d lance chunks.yml` executes the checks and returns
  structured pass/fail results. Soda Core supports DuckDB, PostgreSQL,
  Snowflake, Spark, and Pandas; it does NOT have a LanceDB backend — arXMCP
  would need to first `COPY` the LanceDB table into DuckDB (which LanceDB
  already supports natively via its DuckDB extension) before running Soda
  checks.
- **Specific capability worth borrowing:** The **YAML-declared check DSL**
  that treats "row_count between X and Y" as a first-class versioned
  configuration artifact. The operational insight: threshold values for
  corpus size checks should live in a versioned config file (`infra/corpus-checks.yml`)
  not scattered through Python `if` guards — so when the corpus grows from
  10 K to 100 K rows, one config edit updates all checks.
- **arXMCP positioning:** Design-pattern lift. The YAML schema for checks is
  the borrowable idea; Soda Core itself is too heavy a dep (cloud sync
  features, Spark support). Implement a `var/arxmcp/ops/corpus-checks.yml`
  with threshold values read by `ingest/store.py`'s post-write invariant
  guard. Landing modules: `ingest/store.py` + `var/arxmcp/ops/corpus-checks.yml`.
- **Risk flags:** No LanceDB backend in Soda Core (LanceDB→DuckDB bridge
  needed for a real integration). The dep tree pulls in `soda-core[duckdb]`
  extras which are moderate-weight. Study-only for arXMCP; borrow the YAML
  threshold-config pattern only.

---

## 3. Sources Reviewed

| Project | URL | Stars | Last Commit | High-Signal |
|---|---|---|---|---|
| structlog | https://github.com/hynek/structlog | 4 800 | Oct 2025 (v25.5.0) | YES |
| Pandera | https://github.com/unionai-oss/pandera | 4 400 | Apr 2026 (v0.31.1) | YES |
| Evidently AI | https://github.com/evidentlyai/evidently | 7 600 | Mar 2026 (v0.7.21) | YES |
| Great Expectations | https://github.com/great-expectations/great_expectations | 11 500 | 2026 (active) | YES (DSL only) |
| LanceDB | https://github.com/lancedb/lancedb | ~6 000 | May 2026 (v0.33.0) | YES |
| Soda Core | https://github.com/sodadata/soda-core | 2 400 | 2025 (active) | YES (DSL pattern) |
| Prometheus | https://github.com/prometheus/prometheus | 57 000+ | 2026 (active) | YES |
| Bighorn (Kùzu fork) | https://github.com/Kineviz/bighorn | 129 | Oct 2025 (dormant) | NO |
| DVC | https://github.com/iterative/dvc | ~13 000 | 2025 | LOW (wrong abstraction) |
| lakeFS | https://github.com/treeverse/lakeFS | ~4 500 | 2025 | LOW (object-store focus) |
| python-json-logger | https://github.com/nhairs/python-json-logger | ~1 500 | 2025 | LOW (structlog is better) |
| FastMCP | https://github.com/PrefectHQ/fastmcp | active | 2026 | LOW (no integrity hooks) |

---

## 4. Themes

**Theme 1 — Write-time is the right boundary.** Every high-signal project
enforces assertions at the moment data crosses a write boundary (Pandera's
`check_output` decorator, GX's Checkpoint, Soda's `soda scan` step). arXMCP's
ingest pipeline has a pre-write NPZ alignment check but no post-write
count-reconciliation check — the gap the bug exploited.

**Theme 2 — Dual representation is the core risk.** The class of bug reported
(marker file diverges from table) is universal in any system where the same
fact is persisted in two places (a metadata file AND a database row count).
The pattern all these projects converge on is: compute ground truth from the
authoritative store (`tbl.count_rows()`), write that to the derivative
representation (marker file), then immediately assert equality. Never trust
the derivative in silence.

**Theme 3 — Structured + assertable logs eliminate silent discrepancy.** The
structlog `capture_logs()` idiom reveals that the discrepancy would have been
catchable in tests if the log messages carried the numeric fields. arXMCP's
current logging uses unstructured `%s`-style formatting, making CI log
assertions essentially impossible. Structured logging costs nothing at the
dependency level (structlog + stdlib bridge = zero new heavy deps).

**Theme 4 — Prometheus dual-gauge delta is the cheapest runtime alarm.**
arXMCP already ships `prometheus-client` and a `/metrics` endpoint (E14_S01).
Exposing `arxmcp_corpus_table_rows` alongside `arxmcp_corpus_marker_rows` as
two `Gauge` metrics converts the detection gap from "manual inspection" to
"first Prometheus scrape." This is the lowest-effort path to making the bug
class alarm automatically.

---

## 5. Out of Scope / Parking Lot

| Project | Rejection reason |
|---|---|
| Bighorn (Kùzu fork) | 129 stars, dormant — no independent active development beyond preserving upstream codebase; no writes since Oct 2025 |
| DVC | Dataset-level file-hash tracking; no concept of vector-table row-count validation; S3/remote-storage-first abstraction |
| lakeFS | Git-for-object-storage; excellent for data lake versioning but overkill for single-workstation LanceDB; requires a server process |
| python-json-logger | Structlog subsumes all its capabilities and adds the processor-chain + `capture_logs()` test harness |
| FastMCP (observability) | FastMCP's `Context.log()` sends messages to the MCP client, not to the server's own structured log stream; no integrity-check hooks |
| Deequ | Apache Spark–only data quality framework; distributed systems dep incompatible with arXMCP's local-first constraint |
| dbt tests | SQL-transform pipeline tool; no LanceDB adapter; out of scope for an embedding ingest pipeline |
| Quilt / Dolt | Dataset versioning systems focused on content-addressable file storage / SQL-diff; no LanceDB integration path |
| Lean tooling (LeanDojo etc.) | Out of scope for this observability-focused scout run |
| BGE-M3 / FlagEmbedding | No integrity-relevant new capabilities surfaced for this specific bug class; embedding-norm assertions are a separate future concern |
