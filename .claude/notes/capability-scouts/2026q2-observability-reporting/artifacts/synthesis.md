# Synthesis — capability-scout 2026q2-observability-reporting

**Generated:** 2026-05-28 (main session, all 5 briefs read end-to-end)
**Scope:** observability & reporting — making "persisted metadata silently diverges from ground truth" (and wrong values in logs/reports) automatically catchable. Motivated by the `corpus-version.json` `chunk_count=106` vs 10,298-real-rows bug.

## 1. Executive summary

16 candidates across 4 of the 7 taxonomy categories (Ops/infra dominates; then Ingestion/parsing, MCP tool surface, Agent harness; nothing in Citation graph or Verification/proof tooling — out of scope for this run). The survey shows **extreme triangulation**: all 5 scouts independently converged on the same root-cause class — *derived aggregates are computed from the in-flight batch, never reconciled against the write target* — and on the same dominant fix pattern: **"shift-left" write-time reconciliation** (compute `chunk_count`/`paper_count` from `tbl.count_rows()` at write time, not `len(chunks)`). The top theme: arXMCP already has all the *infrastructure* (atomic marker writes, Prometheus registry, sentinel-file cross-process bridge, OTel tracing, degraded-mode `/readyz`) but **none of the reconciliation steps that bridge a persisted claim to the live store.** The top tension: whether to fix at the write site (root cause, cheapest) or guard at startup/read time (defense-in-depth, catches future regressions) — resolved as "both, in that order." A strong secondary finding: the ingest-throughput metric families named in `08-security-observability-ops.md` were specified but never implemented — a deferred stub that survived E11/E13/E14.

## 2. Triangulation strength

- **5-brief (all scouts):** CAND-1 (write-time ground-truth reconciliation — the fix).
- **3-brief (strong):** CAND-2 (startup reconciliation invariant), CAND-3 (corpus-size Prometheus gauges + delta), CAND-4 (structured/JSON logging + assertable write-path fields), CAND-5 (property-based + multi-paper reconciliation tests), CAND-6 (corpus-status surface: tool or `/readyz` body).
- **2-brief:** CAND-7 (ingest-throughput metrics), CAND-8 (WriteStats/manifest enrichment), CAND-9 (daily-report corpus-integrity section), CAND-13 (embedder-version-skew signal).
- **1-brief (weak — flag for challenger):** CAND-10 (LanceDB `index_stats()` unindexed-rows guard), CAND-11 (OTel GenAI/MCP semconv alignment), CAND-12 (envelope `corpus_integrity_token`), CAND-14 (semantic eval-coverage scan), CAND-15 (deepdiff corpus-validate utility), CAND-16 (session corpus-version guard).

## 3. Candidate catalog

### Ingestion / parsing

### CAND-1 — Compute corpus-version counts from the table, not the batch

**Category:** Ingestion / parsing
**Size:** XS
**Evidence triangulation:** 5 briefs (comparative C2 ✓, research-frontier 2.3 ✓, oss-trends pandera/pointblank/GX ✓, multi-agent ALTK-adjacent ✓, adversary H1 ✓)

**What it is:** In `ingest/store.py::write_chunks`, the corpus-version marker is written on every call with `chunk_count=len(chunks)` and `paper_count=len({c.paper_id for c in chunks})` — the in-flight batch. `bulk_ingest.py` and `re_embed.py` call `write_chunks` once per paper, so the final marker records only the last paper's counts (106 vs 10,298 real rows). Replace these with values derived from the committed table after `_create_indices`: `tbl.count_rows()` and a distinct-`paper_id` count.

**Why it matters:** Every downstream observability surface (startup log, `CORPUS_VERSION_GAUGE` neighbors, daily report) sources corpus size from this marker. The sketcher/autoformalizer pipeline and the operator both consume a metadata claim that is silently ~100× wrong. This is the root cause; everything else is defense-in-depth.

**Sources:** comparative C2 (arXiv S3 manifest derives `num_items` from the artifact); research-frontier 2.3 ("ground-truth-first aggregate reconciliation", dbt/Great-Expectations lineage); oss-trends 2.1/2.5/2.7 (pandera/pointblank/GX row-count postconditions); adversary H1 (verified live); multi-agent C2 (ALTK "silent error").

**Closest arXMCP analog (today):** `ingest/store.py:900-908` — the `write_corpus_version_marker(..., chunk_count=len(chunks))` call site. `version` (from `tbl.version`) is already ground-truth-correct; only the counts are wrong.

**Sketch:** After `dataset_version = tbl.version`, add `table_chunk_count = tbl.count_rows()` (O(1) — reads fragment metadata) and `table_paper_count = len(set(tbl.to_arrow().column("paper_id").to_pylist()))` (O(N), bounded), and pass those to `write_corpus_version_marker`. No schema change; no cache-key impact (BP1 uses `version` only). **Already filed as task #26.**

**Open questions:** The O(N) paper-id scan on a 200K-row bulk ingest — acceptable as a once-per-paper post-write cost, or batch the marker write to once-per-run? (Challenger to weigh.)

### CAND-8 — Enrich WriteStats / add a per-run ingest manifest

**Category:** Ingestion / parsing
**Size:** S
**Evidence triangulation:** 2 briefs (comparative C5+C9 ✓, adversary M1 ✓)

**What it is:** `WriteStats` (and `store-stats.jsonl`) record per-call `chunk_count=len(chunks)` with no `paper_id` and no cumulative table count — so the ops log is a per-batch trace, not an auditable corpus record. Add `paper_id`, rename the ambiguous `chunk_count` → `chunks_written_this_call`, and add `total_rows_after_commit` (from `tbl.count_rows()`). Optionally write a per-run `ingest-summary.json` (OpenAlex/arXiv-manifest idiom) recording committed rows per paper + total + version + batch hash.

**Why it matters:** Makes silent per-paper drops (a paper that contributed 0 chunks) auditable via `grep paper_id store-stats.jsonl`, and turns each JSONL line into a ground-truth-checkable record.

**Sources:** comparative C5 (per-run manifest), C9 (per-paper audit log); adversary M1 (misleading field name).

**Closest arXMCP analog:** `ingest/store.py:173-203` (`WriteStats`), `:636-651` (`_append_store_stats`). Partial — missing `paper_id` + cumulative count.

**Sketch:** Schema-extend `WriteStats.to_dict()`; the `paper_id` is already in the caller's scope. The `total_rows_after_commit` field depends on CAND-1's `count_rows()` call (share it).

**Open questions:** none.

### Ops / infra

### CAND-2 — Startup marker-vs-table reconciliation invariant → degraded mode

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 3 briefs (comparative C6+C8 ✓, multi-agent C2 ALTK ✓, adversary H3 ✓)

**What it is:** At `Resources.startup`, after opening the chunks table, call `chunks_table.count_rows()` and compare against `corpus_info.chunk_count` (from the marker). On divergence beyond a configurable tolerance (suggested 5%), log a WARNING with both values and set `resources.degraded` with a new `DegradedState.reason="chunk_count_diverged"`. The existing `/readyz` 503 path + `arxmcp_degraded_mode_active` gauge then surface it with zero new alerting infra.

**Why it matters:** Defense-in-depth that catches the bug class even after CAND-1 (e.g. a future write path that regresses, or a hand-edited marker). It is the ALTK "silent error review" pattern realized as a startup invariant — no per-request overhead.

**Sources:** comparative C6 (structured startup self-check), C8 (functional probe in readiness); multi-agent C2 (ALTK post-tool-result checking → startup invariant); adversary H3 (unchecked startup log).

**Closest arXMCP analog:** `server/resources.py:337-345` (startup log sources counts from the marker, no cross-check). `count_rows()` is already called nearby at `:476` (reranker warmup) — marginal I/O is ~0. `DegradedState` machinery (`server/corpus.py`) already exists.

**Sketch:** One `count_rows()` + compare in `Resources.startup`; extend the `DegradedState.reason` enum; reuse `refresh_degraded_mode_metric`. Tolerance via an `ARXMCP_*` config knob.

**Open questions:** Should divergence be WARN-and-serve or refuse `/readyz` (503)? (Lean WARN-and-serve since retrieval correctness is unaffected — the data is fine, only the count metadata lies.)

### CAND-3 — Corpus-size Prometheus gauges (marker vs actual) + divergence alert

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 3 briefs (comparative C3+C7 ✓, adversary M5 ✓ (+H3), research-frontier 2.6-adjacent)

**What it is:** Add `arxmcp_corpus_chunk_count_marker` and `arxmcp_corpus_chunk_count_actual` gauges (mirroring `CORPUS_VERSION_GAUGE`), set once at startup (`count_rows()` is I/O, so cache — do NOT recompute per scrape). Operators write the alert rule `abs(actual-marker)/actual > 0.05`. This is Qdrant's `points_count` vs `indexed_vectors_count` delta-metric idiom.

**Why it matters:** Makes the divergence visible to Prometheus/alerting, not just a one-time startup log. Closes the gap that `/metrics` exposes `corpus_version` but no corpus *size*.

**Sources:** comparative C3 (Qdrant delta metric), C7 (Elasticsearch `_cat/indices` docs.count); adversary M5 (no corpus-size gauges) + H3 (gauges enable the alert).

**Closest arXMCP analog:** `server/health.py:92` (`CORPUS_VERSION_GAUGE`), `:237` (`refresh_metrics_from_singleton_state` scrape hook). No size gauge exists.

**Sketch:** ~15 LOC; set both gauges in `refresh_metrics_from_singleton_state` from `resources.corpus_info.chunk_count` (marker) and a startup-cached `count_rows()` (actual). No `tools/list`/BP1 impact (metrics content is outside both pins).

**Open questions:** Pairs with CAND-2 (shared `count_rows()` at startup).

### CAND-4 — Wire structured JSON logging by default + assertable write-path fields

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 3 briefs (oss-trends 2.2 structlog/pytest-structlog ✓, adversary M2+L3 ✓, research-frontier theme ✓)

**What it is:** The `JsonFormatter` exists (`server/observability/logging_setup.py:78`) but is deliberately NOT installed by default; logs are human-readable text. (a) Add `ARXMCP_LOG_FORMAT={text|json}` (default json in prod) wiring `JsonFormatter` in `configure()`; (b) emit a structured write-path event `{event:"write_chunks_done", chunk_count, table_rows, match}` so the value becomes machine-queryable AND test-assertable (`capture_logs`/`assertLogs`); (c) inject `mcp.session.id` via a `contextvars.ContextVar` (note-08 §Logging required field, currently absent).

**Why it matters:** The motivating bug produced *no log line at all* about the count mismatch; structured, assertable fields turn "we logged it" into "CI asserts what we logged." Aligns the runtime with the note-08 logging spec.

**Sources:** oss-trends 2.2 (structlog `capture_logs`, pytest-structlog); adversary M2 (JsonFormatter not wired), L3 (missing `mcp.session.id`/`event`); research-frontier theme (shift-left, assertable).

**Closest arXMCP analog:** `server/observability/logging_setup.py:22-23` (explicitly not installed), `:78-120` (`JsonFormatter` exists, missing context fields).

**Sketch:** Conditional in `configure()` mirroring the `ARXMCP_LOG_LEVEL` pattern; `contextvars` session-id propagation set at the MCP dispatcher. Few tests grep human-readable log text (most use Prometheus counters), so default-flip churn is small.

**Open questions:** Add `pytest-structlog` (65 stars) as a dev dep, or use stdlib `assertLogs`? (Lean stdlib — no new dep.)

### CAND-5 — Reconciliation regression tests (multi-paper + Hypothesis stateful)

**Category:** Ops / infra (test surface)
**Size:** S
**Evidence triangulation:** 3 briefs (research-frontier 2.2 ✓, oss-trends 2.3 Hypothesis ✓, adversary M4 ✓)

**What it is:** Two layers: (a) a deterministic integration test that ingests N synthetic papers via the per-paper loop, then asserts `corpus-version.json::chunk_count == tbl.count_rows()` (this fails TODAY, passes after CAND-1); (b) a Hypothesis `RuleBasedStateMachine` with an `@invariant` `marker.chunk_count == tbl.count_rows()` after any sequence of `write_chunks` calls — permanently regression-blocks the accumulator-bug class and auto-shrinks to the minimal reproducing sequence.

**Why it matters:** The bug existed because no test asserted the marker against the table across a multi-paper write. This is the cheapest permanent guard.

**Sources:** research-frontier 2.2 (Hypothesis `@invariant`); oss-trends 2.3 (RuleBasedStateMachine); adversary M4 (missing reconciliation test).

**Closest arXMCP analog:** `tests/test_store.py` tests `write_chunks` + marker independently; no multi-paper reconciliation assertion.

**Sketch:** (a) ~25 LOC, no new deps, synthetic fixtures. (b) ~150-250 LOC + Hypothesis (MPL-2.0, dev-only — fine; test tooling is outside the no-fork/ship policy).

**Open questions:** Is the Hypothesis layer worth the LOC, or does the deterministic test suffice? (Challenger to weigh; (a) is the must-have, (b) is the nice-to-have.)

### CAND-7 — Ingest throughput metrics via the sentinel-file bridge

**Category:** Ops / infra
**Size:** M
**Evidence triangulation:** 2 briefs (adversary H2 ✓, multi-agent-adjacent ✓)

**What it is:** The families `arxmcp_ingest_papers_processed_total{parser,outcome}` and `arxmcp_ingest_chunks_written_total` are named in `08-security-observability-ops.md` and referenced as ABSENT in the daily report's own comment, but no emitter exists. Emit them as process-level counters in `bulk_ingest.run_bulk_ingest`, bridged to the server's `/metrics` via a new `var/arxmcp/ops/ingest-summary.json` sentinel read by `refresh_sentinel_metrics` (the established cross-process pattern used by drift/quarantine/backup).

**Why it matters:** Ingest is currently unobservable from `/metrics`; the daily report admits it. The sentinel bridge is the no-new-infra fix already proven by E14_S01.

**Sources:** adversary H2 (named-but-unimplemented metric families); multi-agent (corpus-snapshot telemetry).

**Closest arXMCP analog:** `server/health.py:300-400` (`refresh_sentinel_metrics`/`_read_capped`); `tools/daily_metrics_report.py:385-395` (the "absent" admission).

**Sketch:** Counter increments per paper outcome in the ingest process → JSON summary at run end → server reads at scrape. The `ingest-summary.json` doubles as CAND-1's ground-truth record.

**Open questions:** Counter-since-boot vs last-run snapshot semantics across ingest runs? (Lean: last-run snapshot gauges, like backup-status.)

### CAND-9 — Daily-report corpus-integrity + corpus-version section

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 2 briefs (adversary M3+L2 ✓, comparative C4-adjacent ✓)

**What it is:** Add a `## Corpus integrity` section to `tools/daily_metrics_report.py` rendering marker vs actual chunk_count + a red-flag on divergence, plus a header row for `corpus_version` + uptime (currently read from `/metrics` but never rendered).

**Why it matters:** Surfaces the divergence in the human-facing daily cadence. Cheap.

**Sources:** adversary M3 (no reconciliation section), L2 (no corpus_version row); comparative C4 (count in status surface).

**Closest arXMCP analog:** `tools/daily_metrics_report.py:304-449` (`render_report`).

**Sketch:** ~30 LOC reading the CAND-3 gauges. Depends on CAND-3.

**Open questions:** none.

### CAND-10 — LanceDB `index_stats()` unindexed-rows guard

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 1 brief (comparative C1) — weak; flag for challenger

**What it is:** `index_stats()` returns `num_indexed_rows` + `num_unindexed_rows` (rows in the table but not in the HNSW index → brute-force fallback). Expose `num_unindexed_rows` as a gauge and check `==0` (or log) at startup — a DISTINCT integrity axis from the count mismatch (catches stale/partial indexing).

**Why it matters:** Catches "rows present but not searchable" — silent retrieval-quality degradation comparable systems (Qdrant `indexed_vectors_count`) surface as first-class.

**Sources:** comparative C1 (LanceDB `index_stats`, Qdrant #4522).

**Closest arXMCP analog:** `ingest/store.py:558-628` writes indices but never reads `index_stats()`; `server/health.py` has no unindexed gauge.

**Sketch:** One `tbl.index_stats(index_name)` read at startup per embedding column (`hnsw_stmt`/`hnsw_proof`); Python API needs the index name. Gauge + optional readyz field.

**Open questions:** Does the project's `num_partitions=1` HNSW build ever leave unindexed rows in normal operation? (If never, this is a pure tripwire; verify.)

### MCP tool surface

### CAND-6 — Corpus-status surface: `get_corpus_status` tool OR `/readyz` body extension

**Category:** MCP tool surface
**Size:** S
**Evidence triangulation:** 3 briefs (comparative C10+C4 ✓, multi-agent C3-adjacent ✓, adversary H3-adjacent ✓)

**What it is:** Consolidate `{corpus_version, marker_chunk_count, live_chunk_count, delta, unindexed_rows}` into a queryable surface. Two forms: (a) a new `get_corpus_status` MCP tool (agent-facing — an autoformalizer could detect a degraded substrate) — but a new tool **re-pins `EXPECTED_TOOL_SCHEMA_SHA256` + invalidates BP1**; (b) extend the `/readyz` 200 body with `chunk_count`/`marker_chunk_count` (operator-facing, **zero BP1 cost**).

**Why it matters:** No surveyed system (Context7, arxiv-mcp-server) exposes corpus integrity to the agent; arXMCP could be unique. But the BP1 cost of a new tool is real.

**Sources:** comparative C10 (net-new tool, none of the surveyed systems have it), C4 (Weaviate object-count-in-readiness body); multi-agent C3 (envelope trust signal); adversary H3.

**Closest arXMCP analog:** `server/tools.py::ALL_TOOLS` (no corpus-status tool); `server/health.py:219-229` (`/readyz` 200 body — warm-map only).

**Sketch:** Start with (b) `/readyz` body extension (free, operator-facing). Defer (a) the MCP tool to a separate decision given the BP1 re-pin cost — only worth it if the agent pipeline genuinely needs to branch on corpus integrity.

**Open questions:** Does the sketcher/autoformalizer actually need a corpus-integrity tool, or is the `corpus_version` already in every envelope sufficient? (Challenger: the BP1 re-pin makes the tool form expensive; lean to readyz-body + CAND-12.)

### Agent harness

### CAND-12 — `corpus_integrity_token` in the result envelope

**Category:** Agent harness
**Size:** S
**Evidence triangulation:** 1 brief (multi-agent C3 NabaOS) — weak; flag for challenger

**What it is:** Add a deterministic `corpus_integrity_token = sha256(corpus_version, chunk_count, bm25_version, kuzu_schema_version)` to the result envelope, computed once at startup. A fixer/tactician sub-agent that sees a different token on a later call knows the substrate changed mid-session.

**Why it matters:** Closes "the server says X" → "the server committed to X" for the multi-agent pipeline, at zero per-call cost. Cache-safe (deterministic, same per call → shared cache hit preserved).

**Sources:** multi-agent C3 (NabaOS tool receipts, adapted to a hash — no key management since arXMCP runs no LLM).

**Closest arXMCP analog:** `server/tools.py::envelope()` already adds `corpus_version`; the token is an additional deterministic field (envelope shape is NOT BP1-hashed — only `{name,description}` per tool is).

**Sketch:** Compute once in `Resources.startup`; add to `envelope()`. Deterministic → BP1/cache-safe per `07-multi-agent-caching.md`.

**Open questions:** Overlaps `corpus_version` — is the extra token worth it, or does `corpus_version` already serve the "detect substrate change" need? (Likely the latter for v1.)

### CAND-11 — OTel GenAI/MCP semconv alignment

**Category:** Agent harness
**Size:** S
**Evidence triangulation:** 1 brief (multi-agent C1+C7) — weak; flag for challenger

**What it is:** Align span attributes to the OTel GenAI/MCP semantic conventions: `mcp.session.id` (from the `Mcp-Session-Id` header), `gen_ai.tool.name`, and `isError → error.type="tool_error"`. arXMCP uses private attr names (`mcp.tool_name`, `arxmcp.corpus_version`) today.

**Why it matters:** Makes arXMCP traces scrape-compatible with Phoenix/Datadog GenAI dashboards (Phoenix already integrated in E14); enables grouping a whole agent session's tool calls into one trace (detect "autoformalizer got v5, fixer got v6").

**Sources:** multi-agent C1+C7 (OTel semconv v1.39+).

**Closest arXMCP analog:** `server/observability/tracing.py`, `server/tools.py::_wrap_with_observability` (private attr names; session-id not threaded into spans).

**Sketch:** Attribute renames + thread `Mcp-Session-Id` into `span_tool_call`. No BP1 impact (tracing layer only).

**Open questions:** Tangential to the motivating bug — separate observability-quality milestone.

### CAND-16 — Per-session corpus-version guard

**Category:** Agent harness
**Size:** S
**Evidence triangulation:** 1 brief (multi-agent C4 SagaLLM) — weak

**What it is:** Record `corpus_version_at_session_start` in `server/session.py`; if the live version advances mid-session, add an advisory `session_corpus_mismatch:true` to the envelope so the orchestrator can decide to restart.

**Why it matters:** Cross-agent consistency when a delta-ingest bumps the corpus mid-session. Rule-based (CLAUDE-compliant analogue of SagaLLM's LLM validator).

**Sources:** multi-agent C4.

**Closest arXMCP analog:** `server/session.py` (tracks caps, not corpus version); `corpus_version` already in every envelope.

**Sketch:** Advisory flag; `false` is the common case (cache-safe). Note: arXMCP pins `corpus_version` at startup and never auto-upgrades, so mid-session drift only happens on a server relaunch — limiting the value.

**Open questions:** Given startup-pinned version, does mid-session drift even occur without a relaunch? (Likely low-value for v1.)

### Retrieval quality

### CAND-13 — Embedder-version-skew gauge (+ optional Drift-Adapter / GradNormIR)

**Category:** Retrieval quality
**Size:** S (gauge) → L (adapter)
**Evidence triangulation:** 2 briefs (research-frontier 2.6 ✓, multi-agent C8 ✓)

**What it is:** The pure-monitoring win: an `arxmcp_embedder_version_skew` gauge = fraction of chunks whose `embedder_version` column ≠ the server's current model — the "index staleness" signal. The heavier options (Drift-Adapter to bridge embedding spaces across model upgrades; GradNormIR OOD-corpus detection) are larger and gradient-access-gated.

**Why it matters:** Detects when stored vectors become incompatible with live query encodings (relevant if BGE-M3 is ever superseded). The gauge is cheap; the adapter is a separate epic.

**Sources:** research-frontier 2.6 (Drift-Adapter, version-skew gauge); multi-agent C8 (GradNormIR).

**Closest arXMCP analog:** chunks table already has an `embedder_version` column; no skew gauge.

**Sketch:** Gauge from a startup scan of distinct `embedder_version` values. Adapter/GradNormIR explicitly parked (gradient access + training).

**Open questions:** Only the gauge is in-scope for an observability milestone; the rest is a re-embed/retrieval epic.

### CAND-14 — Semantic eval-coverage scan

**Category:** Retrieval quality
**Size:** M
**Evidence triangulation:** 1 brief (research-frontier 2.5) — weak; tangential

**What it is:** Embed corpus chunks + eval queries into one space; cluster to find corpus regions no query exercises — guiding eval-fixture curation (the open `queries.json` hand-labeling task).

**Why it matters:** Addresses a real open task but is only loosely "observability."

**Sources:** research-frontier 2.5 (arXiv:2510.00001).

**Closest arXMCP analog:** `tests/eval/fixtures/queries.json` (hand-labeled, CLAUDE.md §7).

**Sketch:** `tools/coverage_scan.py` + k-means; emits a coverage gauge via sentinel.

**Open questions:** Belongs to the eval-curation track, not this observability run.

### CAND-15 — `validate_corpus` operator utility (deepdiff-style)

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (oss-trends 2.4) — weak

**What it is:** A `tools/validate_corpus.py` that diffs the marker dict against live stats (`count_rows()`, distinct papers, `index_stats()`) and exits non-zero on divergence — operator-runnable and a `make ingest` CI gate. The deepdiff value-changed tree is the report shape (native dict-compare, no import).

**Why it matters:** A manual/CI reconciliation entry point distinct from the always-on startup check (CAND-2) — useful for `make ingest` gating and ad-hoc audits.

**Sources:** oss-trends 2.4 (deepdiff), 2.6 (soda-core YAML checks).

**Closest arXMCP analog:** no corpus-validate utility; `tools/` has per-domain scripts.

**Sketch:** ~30 LOC; reuses CAND-1's count logic. Largely subsumed by CAND-2 + CAND-5 — keep only if an operator-facing CLI gate is wanted.

**Open questions:** Redundant with CAND-2 (startup) + CAND-5 (tests)? (Likely fold in.)

## 4. Cross-cutting tensions

1. **Write-time fix (CAND-1) vs read/startup-time guard (CAND-2/3).** research-frontier + oss-trends are emphatic that the fix belongs at the write site ("shift-left" — assertions co-located with the write, not a downstream dashboard). comparative + multi-agent emphasize startup/scrape-time reconciliation as the alarm. **Resolution:** not either/or — CAND-1 removes the root cause; CAND-2/3 are defense-in-depth that catch *future* regressions (and a hand-edited marker). Sequence: CAND-1 first, then CAND-2/3.

2. **New MCP tool vs `/readyz`-body extension (CAND-6).** A `get_corpus_status` tool is agent-facing and unique among surveyed systems — but **re-pins `EXPECTED_TOOL_SCHEMA_SHA256` and invalidates BP1** (a load-bearing arXMCP cost per `07-multi-agent-caching.md`). The `/readyz`-body extension is operator-facing and BP1-free. **Resolution:** prefer the `/readyz` body; gate the MCP-tool form on a demonstrated agent-pipeline need.

3. **`count_rows()` at every scrape vs once at startup.** comparative C7 floats scrape-time; adversary M5 insists startup-only (I/O cost per scrape). **Resolution:** startup-cached + refreshed post-ingest (not per scrape).

4. **Heavy data-validation libraries vs native re-implementation.** Great Expectations / soda-core / dbt all encode the pattern but bring heavy deps / external runtimes that conflict with arXMCP's local-first, no-new-heavy-infra constraint. **Resolution (unanimous across briefs):** lift the *pattern* (write-time postcondition, row-count check) natively; the only candidate dev-dep additions are Hypothesis / pytest-structlog (test-only, optional).

5. **Does the marker even need `chunk_count`/`paper_count`?** No correctness path reads them (retrieval + cache key use `version` only — adversary H1, comparative). One could argue for deleting the fields. **Resolution:** keep them (operator value + the integrity-check baseline) but make them honest (CAND-1) — deleting would lose a useful corpus-size signal.

## 5. What's already in flight

- **CAND-1** overlaps **task #26** ("Fix corpus-version.json chunk_count/paper_count") filed during this session's deep-dive. The scout strongly validates it and adds the precise `tbl.count_rows()` mechanism + the multi-paper test (CAND-5a) as the regression guard. NOT re-litigated — flagged so the challenger doesn't treat it as net-new.
- **Phoenix + OTel tracing** already integrated (E14_S04) — CAND-11 is an *alignment* refinement on existing infra, not net-new.
- **Sentinel-file bridge** (E14_S01) is the proven mechanism CAND-7 reuses — not net-new infra.
- **E14 S06 / S09–S12** remain unstarted (CLAUDE.md §3) — several candidates (CAND-7 ingest metrics) plausibly belong under that observability epic.

## 6. Parking lot (did not survive synthesis)

- **Drift-Adapter (full) + GradNormIR** (research-frontier 2.6, multi-agent C8) — embedding-space migration / gradient-access OOD detection; their own re-embed/retrieval epic, not observability. Only the version-skew *gauge* (CAND-13) survives.
- **DVC / LakeFS / dbt-core / datacontract-cli / soda runtime / Great Expectations runtime** — all rejected by ≥2 briefs as too-heavy / external-runtime / conflicting with local-first; patterns lifted natively where relevant.
- **data-diff** (Datafold) — abandoned May 2024.
- **NabaOS full HMAC signing** — no key-management problem for a single-user local server; the deterministic-hash adaptation (CAND-12) is the survivable form.
- **PROV-AGENT / MAIF / V3DB / MeTMaP / Nautilus Compass / ZEDD / Freshprobe / MCPAgentBench / SagaLLM-full** — out of scope (external provenance stores, cryptographic verifiability, agent-side benchmarking, persona drift) per the briefs' own rejections.
- **MCP tool-description "smells" (arXiv:2602.14878)** — a tool-description-quality signal; possible future tool-surface-review scout, not observability.
