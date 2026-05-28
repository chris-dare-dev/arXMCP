# OSS Trends Brief — Observability & Reporting (2026-Q2)
# Scout run: capability-scout-2026q2-observability-reporting
# Date: 2026-05-28

---

## 1. TL;DR

The three projects whose ideas would most directly prevent the motivating
marker-vs-table discrepancy bug are: **pandera** (schema-first validation that
asserts row counts and cross-field invariants at write time), **structlog**
(structured logs that are diff-assertable in tests rather than inspected by
eye), and **Hypothesis stateful testing** (model-based tests that let you
drive `write_chunks` through an in-memory reference and assert the marker
always reflects the real table state). The main thematic gap in arXMCP's
current observability stack is the absence of a _write-time postcondition
contract_ that verifies `corpus-version.json::chunk_count` against the
actual post-write LanceDB row count — the daily report, Prometheus metrics,
and sentinel flags all surface what the server _thinks_ is true, but nothing
automatically validates that belief against the ground truth table.

---

## 2. Project candidates

### 2.1 pandera
- **URL:** https://github.com/unionai-oss/pandera
- **License:** MIT
- **Stars / last commit:** 4.4k / April 2026 (v0.31.1)
- **What it does:** pandera is a statistical data testing library for Python
  that lets you declare a schema (column types, nullable flags, row-count
  bounds, cross-column constraints, custom checks) as a class or object, then
  call `.validate(dataframe)` to get a structured `SchemaError` with every
  violation listed. It operates on pandas, polars, PyArrow tables, and
  plain Python containers. It has no runtime daemon and no network dependency
  — validation is a pure Python function call.
- **Specific capability worth borrowing:** pandera's `DataFrameSchema` accepts
  a `checks` list at the _table_ level (not just column level), including
  `pa.Check(lambda df: len(df) == expected_count, error="chunk_count mismatch")`.
  The pattern — declare a `WritePostcondition` class that bundles expected
  `paper_count` + `chunk_count` from the in-flight write, then validate the
  Arrow table returned by `tbl.to_arrow()` against it before writing
  `corpus-version.json` — would make the marker-vs-table bug a test-time hard
  failure instead of a silent runtime discrepancy.
- **arXMCP positioning:** Design-pattern lift into `ingest/store.py`. Native
  re-implementation: a `_assert_write_postconditions(tbl, expected_chunk_count,
  expected_paper_count)` function that calls `tbl.count_rows()` and
  `tbl.to_arrow().column("paper_id").n_unique()` and raises `RuntimeError` if
  either diverges from the caller-supplied expected values by more than a
  configurable tolerance. No pandera import; the pattern is the contribution.
- **Risk flags:** pandera itself is low-risk (no network, no GPU, pure Python).
  arXMCP would borrow the design pattern only; no import dependency introduced.

---

### 2.2 structlog (+ pytest-structlog)
- **URL:** https://github.com/hynek/structlog ; https://github.com/wimglenn/pytest-structlog
- **License:** Apache-2.0 / MIT (structlog dual-licensed); MIT (pytest-structlog)
- **Stars / last commit:** 4.8k / Oct 2025 (structlog v25.5.0); 65 / Sep 2025
  (pytest-structlog v1.2)
- **What it does:** structlog replaces Python's standard `logging` with a
  processor-chain architecture that emits structured key-value dictionaries as
  JSON (or logfmt). Every log call is a dict: `{"event": "write_chunks_complete",
  "chunk_count": 106, "table_rows": 10298, "paper_count": 1}`. The
  `structlog.testing.capture_logs()` context manager and the `pytest-structlog`
  plugin expose all emitted log events as an assertable list, enabling tests
  like `assert {"event": "corpus_version_marker_written", "chunk_count": 106,
  "table_rows": 10298} in log.events`. The motivating bug produced no log line
  at all because `write_corpus_version_marker` was called with the batch count
  (106) not the table total; with structlog, a test would have asserted the
  _emitted_ key-value payload and caught the wrong value.
- **Specific capability worth borrowing:** The `capture_logs()` context manager
  pattern for write-path tests. arXMCP's `tests/test_store.py` already tests
  that `write_corpus_version_marker` is called, but does not assert that its
  arguments match a post-write `tbl.count_rows()`. Adding a structured-log emit
  of `{"event": "write_chunks_postcondition", "expected_chunks": N,
  "actual_table_rows": M, "match": bool}` plus a `capture_logs` assertion on
  that event is the minimal change that would have surfaced the bug in CI.
- **arXMCP positioning:** Design-pattern lift into `ingest/store.py` logging
  discipline + a new test assertion pattern in `tests/test_store.py`. arXMCP
  already uses stdlib `logging`; the concrete deliverable is adding structured
  key-value fields to the critical `write_chunks`/`write_corpus_version_marker`
  log lines and adding `pytest-structlog` as a dev dependency. The `capture_logs`
  test pattern is a native re-implementation compatible with stdlib logging's
  `assertLogs()` if `pytest-structlog` is not added.
- **Risk flags:** structlog is well-maintained and battle-tested. pytest-structlog
  is small (65 stars) but focused and stable; low abandonware risk. Neither has
  GPU or network dependencies.

---

### 2.3 Hypothesis (stateful/model-based testing)
- **URL:** https://github.com/HypothesisWorks/hypothesis
- **License:** Mozilla Public License 2.0 (MPL-2.0) — study-only under
  arXMCP's no-fork policy; ideas implemented natively in pytest tests
- **Stars / last commit:** 8.7k / May 2026 (v6.155.0)
- **What it does:** Hypothesis is Python's property-based and stateful testing
  library. Its `RuleBasedStateMachine` lets you define a set of state transitions
  (e.g. "write a batch of chunks", "read back corpus_version.json", "query the
  table row count") and Hypothesis finds sequences of those transitions that
  break invariants — specifically, it will find the multi-batch write scenario
  where the last batch is 106 chunks but the total table is 10298 rows and
  the marker is written with the wrong count.
- **Specific capability worth borrowing:** The _invariant_ pattern:
  `@invariant()` methods in a `RuleBasedStateMachine` run after every
  transition and assert that `marker.chunk_count == tbl.count_rows()`. When
  Hypothesis fails this invariant it reports the minimal sequence of transitions
  that produces the failure — a two-step sequence "write 50 papers (batch 1),
  write 56 papers (batch 2), read marker" would immediately expose the
  last-batch-wins bug.
- **arXMCP positioning:** Design-pattern lift. A native re-implementation in
  `tests/test_store_stateful.py` using Hypothesis's `@given` + `@invariant`
  machinery (MPL-2.0 means the test file is fine — only code that is shipped
  in the arXMCP package must comply with the no-fork policy; test tooling has no
  such restriction). The invariant is: after any sequence of `write_chunks` calls
  that feed the same `lancedb_path`, the last-written `corpus-version.json`
  must have `chunk_count == tbl.count_rows()` and `paper_count ==
  tbl.to_arrow().column("paper_id").n_unique()`.
- **Risk flags:** MPL-2.0 is more restrictive than MIT/Apache for _shipping_
  code, but Hypothesis is a dev-only test tool. No GPU or network dependency.
  Hypothesis is extremely well-maintained (weekly releases in 2026). The
  stateful-testing surface has steep learning curve relative to simple unit
  tests.

---

### 2.4 deepdiff
- **URL:** https://github.com/seperman/deepdiff
- **License:** MIT
- **Stars / last commit:** 2.5k / March 2026 (v9.0.0)
- **What it does:** deepdiff computes the deep structural diff between two
  Python objects — dicts, lists, dataclasses, or any object — and returns a
  typed diff tree: `{'values_changed': {'root["chunk_count"]': {'old_value': 106,
  'new_value': 10298}}}`. Its `DeepHash` submodule computes content-addressed
  hashes of nested structures, useful for change detection without storing the
  full old value.
- **Specific capability worth borrowing:** A post-cutover integrity check that
  calls `DeepDiff(marker_dict, live_stats_dict)` and fails loudly if any key
  diverges by more than an acceptable threshold. The motivating bug would have
  produced `{'values_changed': {'root["chunk_count"]': {'old_value': 106,
  'new_value': 10298}}}` — immediately actionable. The `DeepHash` pattern
  could also be applied to detect whether `corpus-version.json` has been
  regenerated since the last ingest run (hash the marker file contents; compare
  to a pre-ingest hash stored in ops/state).
- **arXMCP positioning:** Design-pattern lift into `tools/validate_corpus.py`
  (a new or extended operator utility). The deepdiff call itself is a
  `dict-diff(read_corpus_version_json(), compute_live_stats(lancedb_path))`
  — native re-implementation is a 10-line Python function using plain dict
  comparison; deepdiff's contribution is the diff-tree _shape_ and the per-key
  tolerance pattern.
- **Risk flags:** MIT, no network, no GPU. v9.0.0 is a major version bump
  (potential API changes from v8). Library is actively maintained.

---

### 2.5 pointblank
- **URL:** https://github.com/posit-dev/pointblank
- **License:** MIT
- **Stars / last commit:** 434 / April 2026 (v0.24.0)
- **What it does:** pointblank is a Posit-maintained Python data validation
  library that runs a _validation plan_ — a list of checks such as row count
  bounds, column type checks, null-fraction thresholds, and value-range checks
  — against a tabular dataset and produces a structured report with per-check
  pass/fail, severity levels (warning / error / critical), and optional
  side-effect actions (e.g. write a sentinel file). It wraps Narwhals so it
  works with Polars, Pandas, DuckDB, and PyArrow tables without any cloud
  dependency.
- **Specific capability worth borrowing:** The `row_count_match(count=N,
  thresholds=...)` check combined with a `critical` threshold action that writes
  a sentinel file. This is the closest OSS analogue to the "write-time
  postcondition contract" pattern arXMCP needs: after every `write_chunks`, run
  a pointblank-style validation plan against the LanceDB PyArrow table that
  asserts `row_count == expected` and `paper_id.n_unique() == expected_papers`,
  with `critical` level failures triggering a `VALIDATION_FAILED` sentinel in
  `var/arxmcp/ops/`. A native re-implementation in arXMCP requires no new
  import — just calling `tbl.count_rows()` and comparing to the expected value
  before writing the marker.
- **arXMCP positioning:** Design-pattern lift. The pointblank _threshold +
  action_ model is the right shape for arXMCP's write-time postcondition: run
  checks; if `count_mismatch > 0`, write a validation-failed sentinel, log a
  structured error, and surface the discrepancy on the next `/metrics` scrape
  via a new `arxmcp_ingest_validation_errors_total` counter.
- **Risk flags:** 434 stars is on the lower end for a general-purpose validation
  library, but Posit (formerly RStudio) has strong institutional backing; the
  50-release milestone blog post (2025) indicates committed maintenance. No GPU
  or cloud dependency.

---

### 2.6 soda-core (DuckDB connector only)
- **URL:** https://github.com/sodadata/soda-core
- **License:** Apache-2.0
- **Stars / last commit:** 2.4k / May 2026 (v4.11.0)
- **What it does:** soda-core is a data contracts engine: you write YAML check
  files like `row_count min: 1000` or `missing_percent < 5`, run `soda contract
  verify`, and it produces a structured pass/fail report. The `soda-duckdb`
  connector runs checks against DuckDB — which can read Parquet/Lance files
  directly. This means you could point a Soda check file at the LanceDB chunks
  table (via DuckDB's Lance extension) and assert `chunk_count >= N` without
  any cloud dependency.
- **Specific capability worth borrowing:** The YAML-declarative check file
  pattern for index integrity. A `checks/corpus-integrity.yml` file declaring
  `row_count >= ${EXPECTED_CHUNK_COUNT}` and `paper_id.unique_count ==
  ${EXPECTED_PAPER_COUNT}` plus `freshness < 24h` (comparing `last_modified`
  from the Lance dataset metadata) would catch the marker bug AND stale-corpus
  scenarios. The _contract-as-code_ shape — a small YAML checked into the repo
  alongside the schema — is the design-pattern contribution, not the Soda
  runtime itself.
- **arXMCP positioning:** Design-pattern lift for a future `checks/`
  directory containing declarative corpus integrity assertions. The immediate
  native re-implementation is a `tools/verify_corpus_integrity.py` script
  that runs the same numeric checks as Soda's YAML would encode, exiting
  non-zero on failure so `make ingest` can gate on it.
- **Risk flags:** soda-core's cloud push (Soda Cloud) is the business model
  but standalone mode is real and tested. The DuckDB Lance integration is
  experimental (Lance format support in DuckDB is 2026-Q2 new; verify before
  relying on it). Apache-2.0 is on arXMCP's permissive allow-list.

---

### 2.7 Great Expectations (GX Core — study-only; out of the box too heavy)
- **URL:** https://github.com/great-expectations/great_expectations
- **License:** Apache-2.0
- **Stars / last commit:** ~10k / May 2026
- **What it does:** GX is the canonical data quality platform for Python:
  define Expectations (assertions), run Validations against data sources,
  generate Data Docs HTML reports. 300+ built-in expectations including
  `expect_table_row_count_to_equal` and `expect_column_pair_values_A_to_be_greater_than_B`.
- **Specific capability worth borrowing:** The _expectation suite_ pattern:
  a named suite of assertions (row count, column not-null, value range) run
  as a batch after every ingest. The `expect_table_row_count_to_equal(N)` check
  would catch the marker bug if run immediately after `write_chunks` with the
  expected N.
- **arXMCP positioning:** Study-only for the Expectation Suite design pattern.
  GX Core's dep tree (~20 MB installed) and its own config store are too heavy
  for arXMCP's local-first, no-new-infra constraint. The pattern is lifted:
  a `WriteExpectations` dataclass in `ingest/store.py` that encodes the
  expected row count and paper count, validated against the post-write
  `tbl.count_rows()` before `write_corpus_version_marker` is called.
- **Risk flags:** Heavy dep tree (SQLAlchemy, cloud connectors installed by
  default). Config store is not optional in older versions. The GX-as-a-platform
  trajectory conflicts with arXMCP's no-new-infra bias. Listed for pattern study
  only; see §5 for parking lot reasoning.

---

## 3. Sources reviewed

| Project | URL | Stars | Last commit | High-signal? |
|---|---|---|---|---|
| pandera | https://github.com/unionai-oss/pandera | 4.4k | Apr 2026 | YES |
| structlog | https://github.com/hynek/structlog | 4.8k | Oct 2025 | YES |
| pytest-structlog | https://github.com/wimglenn/pytest-structlog | 65 | Sep 2025 | YES (focused) |
| Hypothesis | https://github.com/HypothesisWorks/hypothesis | 8.7k | May 2026 | YES |
| deepdiff | https://github.com/seperman/deepdiff | 2.5k | Mar 2026 | YES |
| pointblank | https://github.com/posit-dev/pointblank | 434 | Apr 2026 | YES |
| soda-core | https://github.com/sodadata/soda-core | 2.4k | May 2026 | YES (pattern only) |
| Great Expectations | https://github.com/great-expectations/great_expectations | ~10k | May 2026 | STUDY-ONLY (too heavy) |
| frictionless-py | https://github.com/frictionlessdata/frictionless-py | 821 | Apr 2026 | PARTIAL (see §5) |
| datacompy | https://github.com/capitalone/datacompy | 645 | May 2026 | LOW (see §5) |
| loguru | https://github.com/Delgan/loguru | 21k | 2025 | LOW for this scope |
| LanceDB lance format | https://github.com/lance-format/lance | — | May 2026 | PARTIAL (built-in count_rows) |

---

## 4. Themes

**Theme 1 — Write-time postcondition contracts are the missing layer.**
Every project surfaced in §2 converges on the same insight: the motivating bug
is a _missing postcondition_, not a missing metric. Prometheus, daily reports,
and sentinel flags are all read-time signals; they surface divergence hours or
days later when an operator is reading a dashboard. pandera, pointblank, and
GX all implement the same pattern — run assertions immediately after a write
and fail hard before the marker is committed — which would have prevented the
bug entirely. arXMCP should adopt this pattern natively without taking any of
these as runtime dependencies.

**Theme 2 — Structured log fields are testable; log messages are not.**
structlog and pytest-structlog demonstrate that the gap between "we logged
it" and "we can assert what was logged" is architectural. arXMCP's current
logging emits human-readable strings; a post-write log line that includes
`chunk_count`, `actual_table_rows`, and `match=True/False` as structured
fields would be both machine-queryable and test-assertable. The one-line
change from `logger.info("wrote %d chunks", n)` to `logger.info("write_chunks_done",
chunk_count=n, table_rows=m, match=(n == m))` is the pattern contribution.

**Theme 3 — Content-addressed manifests > timestamp-only sentinels.**
deepdiff's `DeepHash` and frictionless-py's manifest pattern both suggest that
a hash of the marker file's contents (not just its mtime) should be stored
alongside it, so post-cutover validation can detect silent in-place overwrites.
arXMCP's current sentinel approach records `created_at` but not a hash of the
file's own payload — meaning a re-write that changes only `chunk_count` looks
identical from the outside.

**Theme 4 — Property-based stateful tests expose accumulator bugs.**
Hypothesis's `RuleBasedStateMachine` is specifically designed to catch the
class of bug where a multi-step sequence (batch-1 write, batch-2 write, read
marker) produces state-invariant violations. The accumulator pattern — writing
a per-call value instead of a post-write aggregate — is exactly the pattern
Hypothesis's shrinking algorithm finds and minimises to the smallest reproducing
sequence. Adding one Hypothesis stateful test to `tests/test_store_stateful.py`
would permanently regression-block the marker-vs-table bug class.

---

## 5. Out of scope / parking lot

| Project | URL | Reason excluded |
|---|---|---|
| frictionless-py | https://github.com/frictionlessdata/frictionless-py | 821 stars; focus is tabular CSV/JSON, not Arrow/LanceDB. The `datapackage` descriptor pattern is interesting but frictionless has no LanceDB connector and the descriptor format adds a new file format to ops burden. Design pattern (manifest-as-schema) lifted but project not surfaced. |
| datacompy | https://github.com/capitalone/datacompy | 645 stars; designed for A-vs-B dataframe comparison (e.g. two CSV snapshots), not for live-vs-marker validation. Overkill for a `count_rows()` vs `chunk_count` check. The DeepDiff pattern (§2.4) covers the same ground with less overhead. |
| loguru | https://github.com/Delgan/loguru | 21k stars but arXMCP already uses stdlib `logging` throughout and the project-level discipline (never replace stdlib logging) means loguru adoption would require a pervasive migration. The structured-log pattern is better lifted from structlog (§2.2). |
| Great Expectations (GX Core) | https://github.com/great-expectations/great_expectations | ~10k stars, actively maintained, but the dep tree (SQLAlchemy + cloud connectors) is too heavy for arXMCP's local-first, no-new-infra constraint. The Expectation Suite pattern is lifted natively (see §2.7). |
| soda-core DuckDB + Lance | https://github.com/sodadata/soda-core | DuckDB's Lance extension support is 2026-Q2 new and experimental; relying on it for integrity checks would add a fragile dependency. Pattern lifted as YAML-check-file design; the native re-implementation is a Python script. |
| dbt-style tests | https://github.com/dbt-labs/dbt-core | GPL-3.0 for core; designed for SQL warehouses; no Lance/LanceDB adapter; heavy. Study-only for the "tests-as-source-of-truth" mental model. |
| Prometheus OpenMetrics exemplars | — | arXMCP already uses prometheus_client. Exemplars require a Prometheus 2.26+ remote endpoint — conflicts with local-first, no-new-infra. Pattern noted but not surfaced as a project candidate. |
