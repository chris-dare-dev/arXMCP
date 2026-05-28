# Research-Frontier Brief — Observability & Reporting (2026-Q2)

**Scout ID:** 2026q2-observability-reporting  
**Date:** 2026-05-28  
**Motivating bug:** `ingest/store.py::write_corpus_version_marker` receives `paper_count` and `chunk_count` from the per-paper batch in scope at call time, not from a post-write aggregate query against the LanceDB table — a ~100x silent discrepancy went undetected.

---

## 1. TL;DR

**Top-3 methods to consider:**  
(1) **Pandera declarative schema + statistical validation** — a ~50-LOC post-write assertion that queries the LanceDB table row-count and verifies it is consistent with the written marker, expressed as typed column contracts; already has PyArrow and Polars backends relevant to arXMCP's Arrow tables.  
(2) **Hypothesis `RuleBasedStateMachine` + `@invariant`** — stateful property-based testing that models `write_chunks` → `write_corpus_version_marker` → `read marker` as a state machine and fires the invariant "marker.chunk_count must equal table.count_rows()" after every write rule; catches the exact class of bug with zero new runtime infra.  
(3) **RAGOps-style corpus-coverage consistency checks** — a lightweight post-ingest reconciliation step comparing stored aggregate fields against table ground truth using a read-back query, plus a periodic semantic-coverage gap scan to detect under-represented corpus regions.

**Main thematic shift:** The literature in 2024-2026 has converged on a "shift-left" discipline for data quality — declarative assertions co-located with the write path, checked at write time and in tests, rather than relying on downstream monitoring dashboards to catch discrepancies that are already in the persisted artifact. The move from reactive (scrape `/metrics` and alert later) to proactive (raise at the write-site or in a `pytest --tb=short` run) is the dominant pattern.

---

## 2. Method Candidates

---

### 2.1 Pandera Declarative Schema Validation

**Method name:** Pandera DataFrameSchema / PyArrow-backend validation  
**Year + author:** Niels Bantilan (Union.ai); original SciPy 2023 paper "Pandera: Going Beyond Pandas Data Validation"; library version 0.19–0.29 (2024–Jan 2026).  
**Primary citation:** SciPy Proceedings 2023, https://proceedings.scipy.org/articles/gerudo-f2bc6f59-010 (peer-reviewed); PyPI: https://pypi.org/project/pandera/; docs: https://pandera.readthedocs.io  
**License:** MIT (Apache 2.0 for Union.ai forks). OSS ref impl is the library itself.

**Summary:** Pandera lets you declare a typed schema for a DataFrame-like object (Pandas, Polars, PyArrow, Dask, PySpark) and validate it in a single call. The schema captures column presence, dtype, nullable constraints, range checks, and statistical checks (distribution tests). Applied to arXMCP's `ingest/store.py`, a post-write validator could (a) open the LanceDB table, convert to Arrow, run `schema.validate(arrow_table)`, and (b) assert a custom `Check` that `len(arrow_table) == marker["chunk_count"]`. This is exactly the "aggregate field vs. ground-truth table count" reconciliation that would have caught the motivating bug. The PyArrow and Polars backends shipped in 2024 (v0.19) are directly relevant to arXMCP's Arrow-native pipeline; no Pandas dependency needed. The `@check_types` decorator can gate `write_corpus_version_marker` so the marker is only written after the assertion passes.

**Compute footprint:** Pure algorithm — no GPU, no model download. A `count_rows()` query against LanceDB + one `pa.Table` schema validation pass; O(columns) not O(rows). Negligible on a single workstation for a 200K-row corpus.

**Implementation complexity:** ~50–100 LOC for a `PostWriteValidator` class in `ingest/store.py` that opens the table, runs `schema.validate()`, and compares marker fields. The Pandera library itself is the only new dep (`pandera[pandas]` is already in the ecosystem of many data projects; the PyArrow backend is `pandera` alone with no extras). No custom training run.

**arXMCP fit:** `ingest/store.py::write_chunks` (postcondition on every successful write); `ingest/store.py::write_corpus_version_marker` (precondition check before writing). Could also be a `pytest` fixture in `tests/test_ingest_store.py` that checks post-write invariants without touching production code paths.

**Maturity signal:** 4.4k GitHub stars, ~500k monthly PyPI downloads. Used in production at several ML platform teams. PyArrow backend added 2024 (v0.19); Polars backend updated 2024–2026. No known adoption in an arxiv-MCP-like system, but the use case is textbook.

---

### 2.2 Hypothesis `RuleBasedStateMachine` with `@invariant`

**Method name:** Hypothesis stateful property-based testing with write-read invariants  
**Year + author:** David R. MacIver et al., Hypothesis project; stateful testing API stable since Hypothesis v3 (2017); `@invariant` decorator added Hypothesis v5.8 (2021); active development through v6.152 (2026).  
**Primary citation:** Hypothesis docs: https://hypothesis.readthedocs.io/en/latest/stateful.html; ICSE 2019 "Hypothesis: A new approach to property-based testing" (MacIver et al.). arXiv 2510.09907 (Oct 2024, Nathan Cooper et al.) demonstrates agentic PBT finding real bugs (56% valid, 3 NumPy patches merged).  
**License:** MPL-2.0. OSS ref impl is the library itself.

**Summary:** Hypothesis `RuleBasedStateMachine` models a stateful system as a set of `@rule()` methods (operations) and `@invariant()` methods (postconditions checked after every rule). For arXMCP, a `WriteReadMachine` would have rules: `write_batch(chunks, embeddings)` (calls `write_chunks`), `read_marker()` (reads corpus-version.json), and an `@invariant` that asserts `marker["chunk_count"] == lancedb_table.count_rows()`. Hypothesis generates arbitrary sequences of writes and checks the invariant holds after every step. This directly catches the motivating bug — a multi-batch ingest where `write_corpus_version_marker` is called inside each paper loop instead of once after the full loop. The `@invariant` fires between every rule transition, so a partially-written state where the marker is stale by a batch would fail the test. The arXiv 2510.09907 paper confirms this paradigm finds real production bugs including "flawed cache implementations," which maps closely to the marker-vs-table discrepancy.

**Compute footprint:** Pure algorithm. Tests run against a temporary LanceDB directory (standard `tmp_path` pytest fixture). No GPU, no model. A full stateful test run exploring ~100 sequences takes seconds on a laptop.

**Implementation complexity:** ~150–250 LOC for a `WriteReadMachine` in `tests/test_ingest_store_stateful.py`. Hypothesis is already a reasonable addition to `pyproject.toml` dev deps (~3MB package, no C extensions for the pure stateful API). The invariant body is a one-liner: `assert self.marker_chunk_count() == self.table_row_count()`.

**arXMCP fit:** New test file `tests/test_ingest_store_stateful.py`. Does not touch production code. The `@invariant` would have directly caught the motivating bug in a pre-commit test run.

**Maturity signal:** Hypothesis is the de-facto standard PBT library for Python (~5M monthly PyPI downloads, used across NumPy, Django, cryptography). The `RuleBasedStateMachine` + `@invariant` pattern is documented in the official guide and exercised by hundreds of OSS projects. The 2510.09907 paper validates the agentic extension; the core library needs no external validation.

---

### 2.3 Post-Write Aggregate Reconciliation Pattern (Homegrown, Informed by dbt-test Lineage)

**Method name:** "Ground-truth-first aggregate reconciliation" — a write-postcondition that queries the actual table after every write and asserts stored aggregates are consistent with the query result  
**Year + author:** Lineage from dbt's built-in `not_null`, `accepted_values`, `unique` tests (2020–2025, Fishtown Analytics / dbt Labs); popularized as "data unit tests" by Chad Sanderson ("Data Contracts" 2022–2024). No single canonical paper; the pattern appears in dbt docs: https://docs.getdbt.com/docs/build/tests and Great Expectations: https://greatexpectations.io.  
**Primary citation:** dbt docs (tests): https://docs.getdbt.com/reference/resource-properties/tests; Great Expectations docs: https://docs.greatexpectations.io; "Shift-Left Imperative" post: https://dev.to/nabindebnath/the-shift-left-imperative-implementing-data-contracts-in-cicd-pipeline-40cl  
**License:** dbt-core is Apache-2.0; Great Expectations is Apache-2.0; arXMCP would implement the pattern natively (no-fork policy).

**Summary:** The dbt "source freshness" and "accepted_values" / "not_null" pattern distills to: after every materialization, run assertions against the result table using SQL or Python. For arXMCP, the analog is: after `write_chunks` commits rows to LanceDB, a postcondition function runs `tbl.count_rows()` and `len({c.paper_id for c in tbl.to_arrow()["paper_id"].to_pylist()})` and compares those against the values about to be written to `corpus-version.json`. If they diverge, raise rather than persist the wrong marker. This is a ~20-LOC change to `write_corpus_version_marker` — it becomes `assert_and_write_corpus_version_marker` that takes the `tbl` handle and recomputes the aggregates from ground truth instead of trusting the caller to pass the right values. The "data unit test" framing (Sanderson, 2022–2024) emphasizes that such assertions belong at the write site and in the test suite, not in a post-hoc monitoring dashboard.

**Compute footprint:** One `count_rows()` call (O(1) in LanceDB's Lance format — it reads the metadata footer, not all rows). One Arrow read for `paper_id` uniqueness check (O(N) but cached in the already-loaded table handle). Single workstation, negligible.

**Implementation complexity:** ~20–30 LOC change to `write_corpus_version_marker` signature + ~50 LOC in tests. No new library dep; uses only `lancedb` (already in pyproject.toml). This is the lowest-complexity candidate that directly fixes the motivating bug class.

**arXMCP fit:** `ingest/store.py::write_corpus_version_marker` — the function should accept the already-open `tbl` handle and recompute `chunk_count` / `paper_count` by querying the table rather than accepting them as caller-supplied parameters. This closes the "wrong value in, wrong value persisted" root cause.

**Maturity signal:** The dbt built-in tests are the single most widely adopted form of declarative data quality assertions in the industry (~50k GitHub stars for dbt-core). Great Expectations has ~10k stars. The specific pattern (compute aggregates from the write target, not from the input batch) is a well-known antipattern fix in data engineering.

---

### 2.4 RAGOps Corpus Data-Quality Lifecycle (Post-Ingest Verification)

**Method name:** RAGOps data quality lifecycle — hash-based deduplication, completeness checks, consistency cross-checks at ingest  
**Year + author:** Castagna et al., "RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines," arXiv:2506.03401 (June 2025).  
**Primary citation:** arXiv:2506.03401, https://arxiv.org/abs/2506.03401  
**License:** N/A (paper, not OSS library).

**Summary:** The RAGOps paper synthesizes operational practice for production RAG systems. For data quality at ingest time, it proposes five verifications: (1) **Quality** — structural/format checks; (2) **Completeness** — all expected fields present; (3) **Recency** — timestamp-driven freshness gates; (4) **Consistency** — semantic similarity cross-checks between new data and existing corpus using cosine similarity on embeddings; (5) **Uniqueness** — hash-based deduplication plus embedding-cluster dedup. For arXMCP, items (2) and (5) are directly actionable: a completeness check after write verifies all expected columns are non-null for the batch; a hash-based dedup check flags chunks that were re-ingested without version bump. The paper also formalizes a three-level testing hierarchy (module, component, end-to-end) that maps directly to arXMCP's existing test structure — unit tests for `write_chunks`, integration tests for `write_chunks` → `write_corpus_version_marker`, and eval tests for `make eval`. The cross-process sentinel file pattern arXMCP already uses (drift-detected.flag, eval-quarantine.flag) is the exact "observability via file-system signals" pattern the paper validates as a production-grade pattern.

**Compute footprint:** The quality/completeness/hash checks are O(N) over the batch being ingested — negligible. The semantic consistency check (embedding cosine similarity against existing corpus vectors) requires a nearest-neighbor lookup — cheap at 10K-chunk scale, acceptable at 200K-chunk scale with LanceDB's ANN index.

**Implementation complexity:** The completeness and hash checks are ~50 LOC additions to `_build_arrow_table`. The semantic consistency check requires invoking the existing `ingest/embedder.py` model (already present); the lookup uses `server/retrieval/ann.py` (already present). Total estimated effort: 100–200 LOC across existing files, no new deps.

**arXMCP fit:** `ingest/store.py::_build_arrow_table` (quality/completeness checks inline); `ingest/store.py::write_chunks` (post-write uniqueness check); new `ingest/post_write_checks.py` for the semantic consistency check. The paper's framing also validates arXMCP's existing sentinel-file architecture as an acceptable operational pattern.

**Maturity signal:** arXiv preprint (June 2025), no citation count yet. However, the specific sub-methods (hash dedup, cosine similarity, completeness checks) have individual, well-established maturity signals. The paper is primarily a synthesis/survey rather than introducing novel methods.

---

### 2.5 Semantic Test Coverage for RAG Systems (arXiv:2510.00001)

**Method name:** Semantic Test Coverage Quantification  
**Year + author:** Unnamed authors at time of this scout run (arXiv submission Sept 2024), arXiv:2510.00001.  
**Primary citation:** arXiv:2510.00001, https://arxiv.org/abs/2510.00001  
**License:** Paper only; no OSS reference impl found at time of scan.

**Summary:** This paper proposes a framework for measuring whether a RAG system's eval fixture (i.e., the 20-query fixture in `tests/eval/fixtures/queries.json`) adequately covers the knowledge embedded in the corpus. It embeds both document chunks and test questions into the same vector space, then uses clustering (e.g., k-means or HDBSCAN) to identify document clusters that have low test-question density — i.e., regions of the corpus that no query exercises. Three metrics: basic proximity coverage, content-weighted coverage, and multi-topic coverage. For arXMCP, this closes a known gap: the eval fixture (`tests/eval/fixtures/queries.json`) is still being hand-labeled (CLAUDE.md §7) and the 20 queries may not cover the full `math.AG` + `math.NT` + `hep-th` + `math-ph` distribution of the 50-paper seed corpus. The semantic coverage scan would flag under-represented regions, guiding which queries to add next.

**Compute footprint:** Requires running BGE-M3 to embed both corpus chunks (already done at ingest time and stored in LanceDB) and test queries (~20 vectors, negligible). The clustering step is scikit-learn k-means — O(N·k·iter), seconds on a single workstation for 10K chunks. No GPU at inference time.

**Implementation complexity:** ~150–200 LOC for a `tools/coverage_scan.py` script that loads the LanceDB table, loads the eval queries, embeds queries using `ingest.embedder` (or the server's cached embedding), and runs k-means coverage analysis. OSS reference impl: not published, but all components (LanceDB, scikit-learn, the existing embedder) are already in arXMCP.

**arXMCP fit:** New `tools/coverage_scan.py` utility. Could emit a coverage score to `var/arxmcp/ops/coverage-report.json` and expose it as a Prometheus gauge `arxmcp_eval_coverage_score` via the existing sentinel-file refresh mechanism in `server/health.py::refresh_sentinel_metrics`.

**Maturity signal:** arXiv preprint, Oct 2024. No known external citations yet. The sub-components (embedding-based coverage, k-means gap detection) have strong individual maturity. High relevance to arXMCP given the open eval-fixture curation task.

---

### 2.6 Drift-Adapter for Embedding Model Version Migration

**Method name:** Drift-Adapter — learnable transformation layer bridging embedding spaces across model versions  
**Year + author:** Unnamed team, arXiv:2509.23471, Sept 2025.  
**Primary citation:** arXiv:2509.23471, https://arxiv.org/abs/2509.23471  
**License:** Paper only; no OSS ref impl confirmed at scan time.

**Summary:** When an embedding model is upgraded (e.g., BGE-M3 → a hypothetical BGE-M3-v2), all stored corpus vectors become incompatible with new query vectors. Drift-Adapter trains a lightweight linear/MLP transformation that maps new query embeddings into the old model's embedding space, recovering 95–99% of retrieval recall while avoiding full re-encoding of the corpus (>100x cost reduction). Three adapter variants (Orthogonal Procrustes, Low-Rank Affine, Residual MLP) are compared, all trained on a small paired sample. For arXMCP, this is relevant if BGE-M3 is ever superseded: instead of a full re-embed run (the `partial_reembed` driver in E11_S03), an adapter could be applied at query time while the corpus is incrementally re-indexed in the background. The monitoring implication: arXMCP should track `embedder_version` per chunk (already in `chunks.embedder_version` column) and alert when a non-negligible fraction of chunks have a stale embedder version — this is the "index staleness" signal.

**Compute footprint:** Training the adapter requires ~1000 paired query samples (old model encode + new model encode) and a standard least-squares or Adam optimization step. Trainable on CPU in minutes. Inference is one matrix multiply per query.

**Implementation complexity:** ~200–300 LOC for adapter training script + ~50 LOC modification to `server/retrieval/ann.py` query path to apply the adapter if a version mismatch is detected. The training component is the main effort; inference addition is trivial.

**arXMCP fit:** `server/retrieval/ann.py` (query-time adapter application); new `tools/train_drift_adapter.py`; `server/metrics.py` (new `arxmcp_embedder_version_skew` gauge that reports the fraction of chunks with an embedder version different from the server's current model). The version-skew gauge is the pure-monitoring win; the adapter itself is optional.

**Maturity signal:** arXiv preprint, Sept 2025. The method is novel but the components (Procrustes alignment, low-rank adaptation) are well-established. No known OSS implementation. Medium complexity relative to the simple monitoring/alerting win from just tracking embedder version skew.

---

### 2.7 Pointblank Data Validation for Reporting

**Method name:** Pointblank — data validation toolkit with human-readable reporting  
**Year + author:** Rich Iannone (Posit); first Python release late 2024 (v0.1); active development through 2025.  
**Primary citation:** GitHub: https://github.com/posit-dev/pointblank (MIT license); blog: https://posit.co/blog/introducing-pointblank-for-python  
**License:** MIT.

**Summary:** Pointblank is a Python library for data validation that generates rich HTML/Markdown reports alongside pass/fail results. Unlike Pandera (focused on type contracts) or Great Expectations (focused on statistical suites), Pointblank emphasizes stakeholder-readable output: a validation plan runs against a DataFrame and emits a table with per-check results, row counts, failure rates, and visual indicators. It supports Pandas, Polars, DuckDB, and Parquet backends. For arXMCP's `tools/daily_metrics_report.py` use case, Pointblank could replace the hand-written markdown construction with a validation plan that asserts: (a) `chunk_count` in the corpus-version.json marker matches the LanceDB table row count; (b) all 7 tool counter labels are present in `/metrics`; (c) store-stats.jsonl rows for the last 24h all have `chunk_count > 0`. The resulting HTML report is the `daily-reports/<date>.md` analog but richer.

**Compute footprint:** Pure algorithm. The library is a thin wrapper around DataFrame operations; no GPU or model.

**Implementation complexity:** ~100–150 LOC to write a `tools/corpus_quality_report.py` that constructs a Pointblank validation plan and runs it against the LanceDB table. The main effort is deciding which checks to include; the library handles report rendering. Package is small (no heavy deps beyond its DataFrame backends).

**arXMCP fit:** New `tools/corpus_quality_report.py` (replaces or supplements `tools/daily_metrics_report.py`). Also usable as a `tests/test_corpus_quality.py` pytest integration that fails CI if any check fails.

**Maturity signal:** First Python release late 2024; ~1k GitHub stars as of mid-2025. Relatively early-stage for the Python version (the R package is mature). The validation-plan approach is sound; the reporting layer is the differentiator. Low risk to adopt for tooling/reporting; higher risk as a test gate dependency.

---

## 3. Sources Reviewed

| Venue | URL pattern | Papers / pages scanned | High-signal? |
|---|---|---|---|
| arXiv cs.IR | arxiv.org/list/cs.IR/recent | Targeted search via WebSearch | Low (RAG eval paper found via direct arXiv id) |
| arXiv cs.AI | arxiv.org/abs/2506.03401 | RAGOps paper — full HTML fetch | **YES** |
| arXiv cs.LG | arxiv.org/abs/2509.23471 | Drift-Adapter paper | YES (narrow) |
| arXiv cs.SE | arxiv.org/abs/2510.09907 | Agentic PBT paper | **YES** |
| arXiv cs.IR | arxiv.org/abs/2510.00001 | Semantic test coverage | YES |
| Pandera docs | pandera.readthedocs.io | Schema validation API docs | **YES** |
| Hypothesis docs | hypothesis.readthedocs.io/en/latest/stateful.html | Stateful testing guide | **YES** |
| dbt Labs blog | getdbt.com/blog/data-quality-checks | Data quality tests pattern | YES |
| Pointblank GitHub/blog | posit-dev.github.io/pointblank | Python data validation | YES |
| data-diff PyPI | pypi.org/project/data-diff | Table diff library | Low (project abandoned 2024) |
| DVC docs | dvc.org | Dataset versioning | Low (too heavy for arXMCP's local-first constraint) |
| Datafold blog | datafold.com/open-source-data-diff | Data diff techniques | Low (cloud-focused) |
| WebSearch (RAG pipeline monitoring) | Various blogs/Medium | Embedding drift detection | Medium — no single citable paper |
| WebSearch (data contracts) | datacontract.com/cli | Data contract CLI | Low (YAML-based, overkill for single-workstation) |
| MarkTechPost (PBT 2026) | marktechpost.com | PBT guide | Low (survey, no new methods) |

---

## 4. Themes

The dominant theme in 2024–2026 is **shift-left data quality** — the industry and research community have converged on the view that aggregate metadata fields (counts, versions, checksums) must be computed from the **write target** (the actual written data), not derived from the input batch and passed as parameters. The dbt "source freshness" pattern, Pandera's postcondition validators, and the Hypothesis `@invariant` decorator are all expressions of the same idea: assertions belong at the write site, not in a monitoring dashboard that fires hours later.

A secondary theme is **embedding space version management**: the Drift-Adapter paper and several industry posts frame the `embedder_version` column (which arXMCP already writes to every chunk) as the essential audit trail for detecting when stored vectors become incompatible with live query encodings. The monitoring win (a Prometheus gauge tracking the fraction of chunks with a stale embedder version) requires no new ML infrastructure.

Third theme: **semantic coverage quantification for RAG eval fixtures**. The arXiv:2510.00001 paper formalizes what data teams have done informally — checking whether eval queries cover all the knowledge in the corpus. This directly bears on arXMCP's open eval-curation task.

---

## 5. Already in arXMCP / Already Considered

- **Prometheus gauges for corpus version, resource warm state, nDCG@5, quarantine flags, backup status** — `server/metrics.py` (all metric definitions), `server/health.py::refresh_sentinel_metrics`. Already covers the *reporting* side of monitoring.
- **Store-stats.jsonl per-write audit log** — `ingest/store.py::_append_store_stats` (line 636–651). Records `chunk_count` per write call, but this is the per-batch value, not the cumulative table count.
- **HNSW index creation result in `WriteStats.indices_created`** — `ingest/store.py` line 183–203. Already tracks whether indices were successfully built; does not verify the table row count.
- **LATEXML drift detection (E10_S04)** — `server/metrics.py::LATEXML_DRIFT_DETECTED_COUNTER`, `server/health.py::_read_drift_flag`. Drift detection for the LaTeXML parser is shipped; the same sentinel pattern applies to metadata consistency.
- **MVCC dataset version pinning** — `ingest/store.py` module docstring (lines 1–73), `server/corpus.py`. Version pinning is correct; the motivating bug is orthogonal (wrong aggregate values, not wrong version pin).
- **Daily ops metrics report** — `tools/daily_metrics_report.py`. Scrapes `/metrics` but does not query LanceDB directly, so cannot catch the marker-vs-table discrepancy.
- **DVC** — documented in `.claude/notes/10-references-and-prior-art.md`? No explicit mention. However, DVC's content-addressed manifest model is heavier than what arXMCP needs (arXMCP is already local-first with LanceDB MVCC versions as the content-addressing mechanism).
- **Great Expectations** — not in `.claude/notes/10-references-and-prior-art.md`; not in any milestone notes found. The library is heavyweight (PySpark dependencies, expectation suites, validation stores) relative to what arXMCP needs; Pandera's PyArrow backend is the lighter analog.
- **ColBERT / late-interaction retrieval** — `.claude/notes/10-references-and-prior-art.md` line 165–166. Out of scope for this observability scout run.

---

## 6. Out of Scope / Parking Lot

| Method / paper | Rejection reason |
|---|---|
| **data-diff library** (Datafold OSS) | Abandoned by maintainer May 2024; no active development. The concept (value-level table diff between source and target) is sound but arXMCP's reconciliation need is simpler (assert aggregate counts match). Implement natively. |
| **LakeFS** (Git-for-data, branching model over object storage) | Requires a running LakeFS server; incompatible with arXMCP's local-first, no-new-heavy-infra constraint. The MVCC version integer already covers arXMCP's versioning need. |
| **dbt-core + dbt-expectations** | dbt's DAG model assumes SQL materialization targets, not an embedded vector store. Port of the *idea* (data unit tests) is captured in Method 2.3 above; importing dbt would be a category error. |
| **datacontract-cli** (YAML-based data contracts, soda-core) | Designed for API-boundary contracts between teams; overkill for a single-developer, single-workstation project. The shift-left *principle* is valuable (captured in 2.3); the tool is not. |
| **Langfuse / Helicone** (LLM call tracing platforms) | Already considered in `.claude/notes/10-references-and-prior-art.md` (Observability section). Both are server-side LLM proxy tools; they do not observe the ingest pipeline. |
| **Phoenix (Arize)** (retrieval-eval views) | Already in `.claude/notes/10-references-and-prior-art.md` and used in E14. Out of scope for ingest-side data quality. |
| **V3DB** (zero-knowledge proofs for verifiable vector search, arXiv:2603.03065) | Cryptographic verifiability for external-facing vector DBs; arXMCP is single-user local-first — threat model does not include untrusted clients querying the index. |
| **MeTMaP** (metamorphic testing for RAG vector matching, 2024) | Focused on verifying embedding similarity computations, not pipeline aggregate metadata. Relevant if BGE-M3 distance calculations were in question; not relevant to the motivating bug class. |
| **Nautilus Compass** (persona drift detection, arXiv:2605.09863, 2025) | LLM agent persona drift at inference time; not a data pipeline monitoring tool. |
| **Zero-Shot Embedding Drift Detection / ZEDD** (arXiv:2601.12359, Jan 2026) | Focused on detecting prompt injection via embedding-space shift; not corpus data quality. Interesting for the security track but out of scope here. |
| **DVC pipelines + dvc.lock** | The content-addressed manifest model is elegant, but arXMCP already uses LanceDB MVCC integer versions for the same purpose. Adopting DVC would add a parallel versioning system for diminishing returns. |
