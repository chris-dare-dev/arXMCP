# Challenge — capability-scout 2026q2-observability-reporting

**Challenger:** capability-scout-challenger
**Generated:** 2026-05-28
**Synthesis path:** `.claude/notes/capability-scouts/2026q2-observability-reporting/artifacts/synthesis.md`
**Candidates evaluated:** CAND-1 through CAND-16 (16 total)

---

## 1. Executive Summary

Zero BLOCKERs. The catalog is architecturally clean: no candidate violates the
`assert`-ban, no-fork policy, or `BaseHTTPMiddleware` prohibition, and none adds
a distributed-systems dependency. Four MAJORs surface real costs the synthesis
either glossed or under-quantified: (1) CAND-6's MCP-tool form carries a
`EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` re-pin cost that the
synthesis acknowledges but does not price — the `/readyz`-body form is the
correct v0; (2) CAND-7's "M-effort" estimate is plausible only if the sentinel
JSON schema and the scrape-hook contract are stable — a new sentinel type always
requires a server-side schema guard, driving effort toward M+; (3) CAND-5's
Hypothesis layer is a significant ongoing test-maintenance burden the synthesis
treats as optional but low-cost — it is low-cost to write but non-trivial to
keep green as the write path evolves; (4) CAND-13's effort annotation "S → L"
correctly flags the adapter as deferred but the gauge itself conceals a startup
O(N) scan that breaks the synthesis's "startup-only" caching claim. The top two
cross-cutting issues are: (a) **four candidates (CAND-3, CAND-7, CAND-10,
CAND-13) share a `count_rows()` or `index_stats()` call that must be
startup-cached and never re-evaluated per-scrape** — the synthesis states this
principle but individual candidate sketches are inconsistent about it; (b) the
dependency DAG (CAND-9 → CAND-3, CAND-8 → CAND-1, CAND-2 and CAND-3 share a
startup `count_rows()`) is noted but never made explicit — it matters for
sequencing.

---

## 2. BLOCKER Findings

None.

---

## 3. MAJOR Findings

---

### CAND-6 — Corpus-status surface: `get_corpus_status` tool OR `/readyz` body extension

**Severity:** MAJOR

**Objections:**

- **Axis 3 (Prompt-cache discipline BP1/BP2):** The synthesis correctly identifies
  the BP1 re-pin cost but underweights it. Adding `get_corpus_status` to `ALL_TOOLS`
  in `server/tools.py` forces a re-pin of both `EXPECTED_TOOL_SCHEMA_SHA256`
  (`tests/test_server_tool_schema.py:94`) AND `EXPECTED_BP1_SHA256`
  (`tests/test_prompts.py:649`) — both pins must move in lockstep and the
  `--update-tool-schema-hash` pytest flag must be exercised. This is not a
  prohibitive cost but it is a real coupling that affects the entire agent
  pipeline's cache validity on the next deployment.

- **Axis 4 (MCP tool-surface contract):** The synthesis says "the tool form is
  agent-facing and unique." That may be true, but uniqueness is not a reason to
  pay the BP1 cost. No agent path in the sketcher → autoformalizer → tactician
  → fixer pipeline requires corpus-integrity data at tool-call time — the
  `corpus_version` already in every envelope (via `server/tools.py::envelope`)
  is sufficient for session consistency checks. A new tool without a concrete
  agent consumption path should not exist.

- **Axis 9 (Value density):** CLAUDE.md §2 frames valuable LLM roles upstream
  of verification. Corpus integrity is an *operator/infra* concern, not an agent
  reasoning concern. The `/readyz`-body form (form b) costs nothing and is
  fully sufficient for the operator use case. The MCP-tool form adds agent API
  surface for a use case no agent sub-role currently needs.

**Suggested scope adjustment (v0/v1 cut-line):**

- v0 (this observability milestone): ship form (b) only — extend the `/readyz`
  200 body (`server/health.py:219–229`) with `chunk_count` and
  `marker_chunk_count`. Zero BP1 cost. Zero schema re-pin.
- v1 (only if a concrete agent branching-on-corpus-integrity need is identified):
  add `get_corpus_status` as an MCP tool, accept the re-pin cost, and add it to
  the snippet contract (`/.claude/docs/snippet-contract.md`).

---

### CAND-7 — Ingest throughput metrics via the sentinel-file bridge

**Severity:** MAJOR

**Objections:**

- **Axis 8 (Effort honesty):** The synthesis rates this M and notes the
  sentinel-file pattern is "established." That is true for the *reader* side
  (`server/health.py:300–400`). The *writer* side is net-new: the ingest process
  must produce a well-formed `ingest-summary.json` that the server's
  `refresh_sentinel_metrics` hook can parse. The existing sentinels (drift,
  quarantine, backup) all have fixed schemas; adding a new sentinel type requires
  (a) a server-side schema guard in `_read_capped` callers, (b) a new
  `INGEST_PAPERS_PROCESSED_GAUGE` / `INGEST_CHUNKS_WRITTEN_GAUGE` pair in
  `server/health.py`, (c) a new `refresh_ingest_metrics` hook or extension of
  the existing `refresh_sentinel_metrics`, and (d) tests for both the writer and
  the reader path. Together these drive the milestone closer to M+ than S.

- **Axis 10 (Sequencing dependencies):** The synthesis notes that
  `ingest-summary.json` doubles as CAND-1's ground-truth record. This creates
  a sequencing dependency: CAND-7 should be implemented *after* CAND-1 (so that
  `ingest-summary.json` records the correct `tbl.count_rows()` value, not
  `len(chunks)`). If implemented before, the sentinel will carry the same wrong
  values the root-cause fix is meant to eliminate. The synthesis notes the
  overlap but does not flag it as a sequencing constraint.

- **Axis 8 (Effort honesty, continued):** The "counter-since-boot vs last-run
  snapshot" open question is not trivial. If the snapshot semantics change
  between ingest runs, the Prometheus gauge will show misleading deltas unless
  the reader handles missing/stale files correctly (the existing sentinels are
  present-or-not, not time-series). This design decision must be made before
  implementation, not deferred to the milestone.

**Suggested scope adjustment (v0/v1 cut-line):**

- v0: After CAND-1 is shipped, write `ingest-summary.json` with last-run totals
  (gauges, not counters: `papers_processed_last_run`, `chunks_written_last_run`,
  `timestamp`). Extend `refresh_sentinel_metrics` with a new reader for this
  file. Add `INGEST_PAPERS_GAUGE` + `INGEST_CHUNKS_GAUGE` as Gauge (not Counter)
  to avoid reset-on-restart complexity.
- v1: Convert to counter-since-boot if a time-series need is identified (adds a
  persistent state file and more server logic).

---

### CAND-5 — Reconciliation regression tests (multi-paper + Hypothesis stateful)

**Severity:** MAJOR

**Objections:**

- **Axis 8 (Effort honesty):** The synthesis correctly marks (a) as must-have
  (~25 LOC) and (b) as optional (150–250 LOC + Hypothesis). But it underweights
  the ongoing maintenance cost of (b). A `RuleBasedStateMachine` with `@invariant`
  ties the test to the exact calling contract of `write_chunks` — if the
  signature evolves (e.g., E11-style partial-reembed changes arguments or
  batching semantics), the state machine needs to track the change. The synthesis
  treats Hypothesis as a one-time cost. It is also a recurring maintenance cost.

- **Axis 2 (No-fork policy):** The synthesis notes that Hypothesis is MPL-2.0
  and states "test tooling is outside the no-fork/ship policy." This is correct
  for test tooling — Hypothesis as a `dev` dependency is fine under arXMCP's
  no-fork policy (which forbids importing/forking OSS *implementation* code into
  shipped modules, not test infrastructure). However, the synthesis does not
  confirm that Hypothesis is NOT already in `pyproject.toml` as a dev dep.
  Verification: `grep hypothesis pyproject.toml` returns empty — it is not yet
  present, so adding it is a new dev dep decision. That decision is reasonable
  but should be explicit.

- **Axis 8 (Effort honesty, continued):** The synthesis says Hypothesis has a
  "steep learning curve relative to simple unit tests" but then rates the whole
  candidate as S. The learning-curve admission and the S rating are inconsistent
  for a team where no Hypothesis test infrastructure currently exists. Getting
  the first `RuleBasedStateMachine` to work correctly against a real LanceDB
  temporary path (not a mock) is a non-trivial first-use.

**Suggested scope adjustment (v0/v1 cut-line):**

- v0 (must-have): ship part (a) only — the deterministic multi-paper integration
  test (~25 LOC) that fails today and passes after CAND-1. No new deps. This is
  the regression guard the synthesis correctly identifies as load-bearing.
- v1 (after the write path is stable): add the Hypothesis `RuleBasedStateMachine`
  as a `pytest -m slow` or CI-nightly test with Hypothesis added to dev deps
  (`pyproject.toml` `[tool.pytest.ini_options].markers` already has the
  extension point). Treat it as a separate milestone S with its own
  research/implement/critique cycle.

---

### CAND-13 — Embedder-version-skew gauge (+ optional Drift-Adapter / GradNormIR)

**Severity:** MAJOR

**Objections:**

- **Axis 8 (Effort honesty):** The synthesis rates the gauge as S and the adapter
  as L, correctly deferring the adapter. But the gauge itself has a hidden effort
  cost: reading distinct `embedder_version` values from the `chunks` table at
  startup requires either a full `tbl.to_arrow().column("embedder_version").unique()`
  scan (O(N) — the same O(N) scan the synthesis flags as "acceptable" for
  `paper_count` in CAND-1 but acknowledges requires a note about the 200K-row
  bulk case) or a `SELECT DISTINCT embedder_version FROM chunks` query (requires
  knowing whether LanceDB supports this efficiently). The synthesis says "startup
  scan of distinct `embedder_version` values" without acknowledging the per-200K-row
  cost or the caching requirement.

- **Axis 3 (Prompt-cache discipline BP1/BP2):** No direct BP1 impact — gauges
  live in `server/metrics.py` and are outside the `tools/list` pin. But the
  startup `embedder_version` scan must be cached (not re-evaluated per scrape)
  per the CAND-3 cross-cutting principle. The synthesis does not state this
  explicitly for CAND-13 the way it does for CAND-3.

- **Axis 7 (Retrieval-quality regression):** This candidate addresses a real
  risk (embedding model skew post-upgrade) but the risk is currently
  hypothetical: arXMCP pins BGE-M3 and has never upgraded it. The gauge is
  a useful tripwire but has zero immediate diagnostic value on a freshly-built
  corpus (skew will always be 0). The effort-to-value ratio is lower than
  CAND-3 or CAND-2.

- **Axis 9 (Value density):** For the current observability milestone, CAND-13
  is tangential to the motivating bug (marker-vs-table divergence). The synthesis
  correctly notes this but rates it S alongside the more impactful CAND-2/CAND-3
  candidates. It should be deprioritized relative to those.

**Suggested scope adjustment (v0/v1 cut-line):**

- v0: Skip. The gauge has zero diagnostic value until a second embedder version
  is introduced. File as a follow-up for the "E14 S06+ follow-ups" backlog
  (CLAUDE.md §3 notes S06/S09–S12 remain unstarted).
- v1 (when BGE-M3 is first upgraded): add the gauge alongside the partial
  re-embed driver. At that point the skew signal is immediately actionable.

---

## 4. MINOR Findings

---

### CAND-1 — Compute corpus-version counts from the table, not the batch

**Severity:** MINOR

**Objections:**

- **Axis 8 (Effort honesty):** The synthesis leaves open "the O(N) paper-id scan
  on a 200K-row bulk ingest — acceptable as once-per-paper post-write cost?"
  and asks the challenger to weigh in. The honest answer: O(N) on every
  `write_chunks` call (once per paper in `bulk_ingest`) means 200K papers ×
  ~200K rows growing scan = O(N²) total cost over a full bulk run. For the
  current 50-paper seed corpus this is negligible; for a 200K-paper corpus it
  is not. The fix: either (a) do the `paper_id` unique scan only at the *end*
  of the bulk run (move `write_corpus_version_marker` out of the per-paper loop
  into the post-loop cleanup — which is the architecturally correct solution per
  the synthesis's own root-cause analysis), or (b) maintain a running set of
  paper_ids in the bulk_ingest loop and pass the count, not recompute it from
  the table on every call. The synthesis notes `tbl.count_rows()` is O(1) (reads
  fragment metadata) but the `paper_id` unique scan is O(N) — and the
  synthesis's sketch conflates the two.

- **Axis 10 (Sequencing dependencies):** CAND-1 is already in-flight as task #26.
  The synthesis flags this. But the challenge is: if CAND-5(a), CAND-8, CAND-9,
  CAND-2, CAND-3, and CAND-7 all depend on CAND-1 being correct first, task #26
  is the critical-path item for the entire catalog. Phase 4 prioritization should
  treat it as P0.

**Suggested scope adjustment:**

Move `write_corpus_version_marker` to once-per-bulk-run (outside the per-paper
loop in `bulk_ingest.py::run_bulk_ingest`) rather than once-per-paper. This
eliminates the O(N²) concern: one `tbl.count_rows()` + one `paper_id` unique
scan at the end of the full run. The per-paper `WriteStats` still records
per-paper chunk counts (CAND-8) without a table scan.

---

### CAND-2 — Startup marker-vs-table reconciliation invariant → degraded mode

**Severity:** MINOR

**Objections:**

- **Axis 10 (Sequencing dependencies):** CAND-2 and CAND-3 both call
  `count_rows()` at startup and the synthesis notes they should share the call.
  The sharing mechanism is not specified: is it a field on `Resources`? A module-
  level cache? Without a clear sharing design, two independent implementations
  will each make a `count_rows()` call, defeating the "marginal I/O ~= 0" claim.
  The milestone implementation brief should explicitly designate one location for
  the cached value.

- **Axis 8 (Effort honesty):** The `DegradedState.reason` field is a `str`
  (`server/corpus.py:135`), not an enum — extending it to include
  `"chunk_count_diverged"` is a one-liner, but the synthesis implies an enum
  extension ("extend the `DegradedState.reason` enum"). The field is a plain
  string; treating it as an enum is a documentation debt, not a blocking issue.

**Suggested scope adjustment:**

Define a module-level `_STARTUP_COUNT_ROWS_CACHE: int | None = None` in
`server/resources.py` (or a field on `Resources`) to share the result between
CAND-2's invariant check and CAND-3's gauge. Explicitly document in both
milestone briefs that this cache is the contract.

---

### CAND-3 — Corpus-size Prometheus gauges (marker vs actual) + divergence alert

**Severity:** MINOR

**Objections:**

- **Axis 8 (Effort honesty):** The synthesis states "~15 LOC" but this includes
  no test surface. Two new Prometheus gauges require at least one test that
  asserts the gauges are set at startup and that the values reflect the mock
  LanceDB table's count. The test surface adds another ~30 LOC and a fixture.
  The synthesis's LOC estimate is for the implementation only, not for the
  complete deliverable.

- **Axis 3 (Prompt-cache discipline BP1/BP2):** The synthesis correctly notes
  "No `tools/list`/BP1 impact." Confirmed: Prometheus gauges are not in the
  `EXPECTED_TOOL_SCHEMA_SHA256` pin (`tests/test_server_tool_schema.py:94`) or
  `EXPECTED_BP1_SHA256` (`tests/test_prompts.py:649`). No cache-discipline risk.

**Suggested scope adjustment:**

Add a `tests/test_startup_gauges.py` test (or extend `tests/test_health.py`)
that mocks LanceDB `count_rows()`, starts the server, and asserts both
`arxmcp_corpus_chunk_count_marker` and `arxmcp_corpus_chunk_count_actual` are
set to the expected values. Budget ~45 LOC total (implementation + tests).

---

### CAND-4 — Wire structured JSON logging by default + assertable write-path fields

**Severity:** MINOR

**Objections:**

- **Axis 8 (Effort honesty):** The synthesis says "few tests grep human-readable
  log text." This needs verification, not an assertion. If any test in
  `tests/test_store.py` or `tests/test_bulk_ingest.py` does `caplog.records`
  with string matching against human-readable text, flipping the default to JSON
  will break those tests. The synthesis should have audited `grep -r "caplog"
  tests/` before making this claim. The "churn is small" assumption may be wrong.

- **Axis 8 (Effort honesty, continued):** Adding `contextvars.ContextVar` for
  `mcp.session_id` into `JsonFormatter.format()` requires threading the session
  ID through the entire request lifecycle into the logging context. In a FastAPI
  async handler, the ContextVar is set per-request — but log lines emitted from
  background tasks (e.g., startup, sentinel refresh) will have no session ID.
  The synthesis proposes this without acknowledging the "no session ID in
  non-request context" case. The formatter must handle `None` gracefully.

**Suggested scope adjustment:**

v0: Ship the `ARXMCP_LOG_FORMAT` env var wiring + the structured write-path
event. Defer the `contextvars` session-ID propagation to a separate sub-item
(it requires handler-chain threading and a non-request context strategy). The
session-ID propagation is L3 from the adversary brief — LOW severity — and
correctly sequenced after M2 (default JSON) lands.

---

### CAND-8 — Enrich WriteStats / add a per-run ingest manifest

**Severity:** MINOR

**Objections:**

- **Axis 10 (Sequencing dependencies):** The synthesis correctly notes
  `total_rows_after_commit` depends on CAND-1's `count_rows()` call. It should
  also note that `paper_id` addition to `WriteStats` is independent of CAND-1
  and can ship earlier. The two sub-items should be treated as distinct
  deliverables in the implementation brief, not bundled.

- **Axis 8 (Effort honesty):** The synthesis notes "no open questions" but does
  not flag that renaming `chunk_count` → `chunks_written_this_call` in
  `WriteStats.to_dict()` is a breaking change to the `store-stats.jsonl` schema.
  Any monitoring script or grep that reads `store-stats.jsonl` (the adversary
  confirms there are none today, per "grep confirms zero reads") but a future
  operator tool could parse this file. Adding a `chunks_written_this_call` field
  while keeping `chunk_count` as a deprecated alias for one release cycle is the
  safer migration path.

**Suggested scope adjustment:**

Add both fields (`chunks_written_this_call` and `chunk_count` as alias) in v0;
remove the deprecated alias in v1 after one release cycle. Ship `paper_id`
independently of `total_rows_after_commit`.

---

### CAND-9 — Daily-report corpus-integrity + corpus-version section

**Severity:** MINOR

**Objections:**

- **Axis 10 (Sequencing dependencies):** The synthesis correctly states this
  "depends on CAND-3." The dependency chain is: CAND-1 → CAND-3 → CAND-9.
  CAND-9 is a pure consumer of gauges that CAND-3 provides; without CAND-3, the
  implementation would need to read LanceDB directly from a reporting script,
  which violates the server/ingest separation. The sequencing must be enforced.

- **Axis 6 (Doc-placement discipline):** The synthesis proposes adding a
  `## Corpus integrity` section to `tools/daily_metrics_report.py`. This is a
  `tools/` module, not a markdown file — no doc-placement issue. Confirmed clean.

**Suggested scope adjustment:** None beyond enforcing the sequencing (ship after
CAND-3). The ~30 LOC estimate is accurate.

---

### CAND-10 — LanceDB `index_stats()` unindexed-rows guard

**Severity:** MINOR

**Objections:**

- **Axis 8 (Effort honesty):** The synthesis raises the question "does
  `num_partitions=1` HNSW build ever leave unindexed rows in normal operation?"
  without answering it. The comparative brief (C1) confirms `index_stats()` is
  documented to return `num_unindexed_rows == 0` when "indexes are fully
  up-to-date." arXMCP calls `_create_indices` synchronously (`ingest/store.py:
  558–628`) — the index is built before returning, so in normal operation the
  answer is "no unindexed rows." This makes the guard a pure tripwire (non-zero
  only on corruption or a partial write). That is still valuable, but the
  operator-messaging for the alert should be clear: non-zero is always abnormal.

- **Axis 8 (Effort honesty, continued):** `tbl.index_stats(index_name)` requires
  knowing the exact index names (`"hnsw_stmt"` and `"hnsw_proof"`). If the index
  names ever change, this call silently raises or returns empty. The startup
  code must either hard-code these names (fragile) or discover them from
  `tbl.list_indices()` (if that API exists in lancedb 0.30.x). The synthesis
  does not address this.

**Suggested scope adjustment:**

v0: Use `tbl.list_indices()` to discover active index names, then call
`index_stats()` for each. Wrap in a try/except that logs a WARNING on unknown
index names but does not fail startup. The gauge value defaults to 0 if
`index_stats()` is unavailable.

---

### CAND-11 — OTel GenAI/MCP semconv alignment

**Severity:** MINOR

**Objections:**

- **Axis 9 (Value density):** The synthesis correctly notes this is "tangential
  to the motivating bug" and suggests it belongs in a "separate
  observability-quality milestone." The challenger agrees. This is a quality-of-
  life improvement for Phoenix/Datadog compatibility, not a correctness fix.
  It belongs in the E14 S06+ backlog (CLAUDE.md §3), not the current run.

- **Axis 8 (Effort honesty):** Threading `Mcp-Session-Id` into span context
  requires the FastMCP handlers to pass request headers into
  `span_tool_call` — the multi-agent brief (C7) confirms this requires
  adding a `session_id: str | None = None` parameter to `span_tool_call` and
  modifying every handler that calls it. The synthesis rates this as S; it is
  plausibly S but the handler-chain threading is not zero-cost.

**Suggested scope adjustment:**

Defer entirely to the E14 S06+ follow-up work. If the current observability run
is sequenced, do not include CAND-11. File as a standalone S milestone in the
backlog with clear acceptance criteria (Phoenix GroupBy session_id works after
the change).

---

### CAND-12 — `corpus_integrity_token` in the result envelope

**Severity:** MINOR

**Objections:**

- **Axis 9 (Value density):** The synthesis asks "does `corpus_version` already
  serve the `detect substrate change` need?" The answer is yes — `corpus_version`
  is already in every result envelope (`server/tools.py::envelope`), is already
  used as the Tier-1 cache key (`07-multi-agent-caching.md` §"Tier 1"), and is
  the deterministic substrate-change signal for the agent pipeline. The
  `corpus_integrity_token` adds a hash over additional fields (`bm25_version`,
  `kuzu_schema_version`) that have never been shown to drift independently of
  `corpus_version` — these indices are rebuilt during every ingest that bumps the
  version. Adding a field that encodes no new information is noise in the
  envelope.

- **Axis 4 (MCP tool-surface contract):** The synthesis correctly notes the
  envelope shape is NOT BP1-hashed (only `{name, description}` per tool is). But
  adding a field to every result envelope still changes the byte content of every
  `tool_result` block. If the receiving agent has been trained or prompted to
  parse the exact envelope shape, adding a new deterministic field is a silent
  protocol change. The synthesis acknowledges this is "deterministic and cache-
  safe" but does not acknowledge the envelope-shape contract with consuming
  agents.

**Suggested scope adjustment:**

Skip for v0. If the agent pipeline demonstrates a case where `corpus_version`
is insufficient (e.g., BM25 index rebuilt without a version bump), add the
token at that time. The open question "overlaps `corpus_version`" is the correct
instinct — overlapping signals with no concrete use case are technical debt.

---

### CAND-15 — `validate_corpus` operator utility (deepdiff-style)

**Severity:** MINOR

**Objections:**

- **Axis 9 (Value density):** The synthesis asks "redundant with CAND-2 + CAND-5?"
  and hedges "Likely fold in." The challenger says: fold in. CAND-2 provides
  the always-on startup check; CAND-5(a) provides the CI regression guard;
  CAND-15 provides an operator CLI that duplicates both. The only unique value
  is "operator-runnable ad-hoc before a deployment" — which is covered by
  `python -c "from server.corpus import open_chunks_table_with_fallback; ..."`.
  A dedicated script adds maintenance surface for negligible incremental value
  over CAND-2.

- **Axis 8 (Effort honesty):** "~30 LOC" is accurate for the core logic but the
  synthesis does not account for the `make ingest` CI gate wiring, which requires
  a `Makefile` target, an exit-code contract, and a test that the target fires
  on divergence. That triples the effective scope.

**Suggested scope adjustment:**

Fold into CAND-2 as a `tools/` script mode (e.g., `python -m server.corpus
--validate` that exercises the same invariant check outside the server context).
Do not ship as a standalone milestone.

---

### CAND-16 — Per-session corpus-version guard

**Severity:** MINOR

**Objections:**

- **Axis 9 (Value density):** The synthesis correctly identifies the limiting
  factor: "arXMCP pins `corpus_version` at startup and never auto-upgrades, so
  mid-session drift only happens on a server relaunch." A server relaunch
  terminates all active sessions, so `session_corpus_mismatch: true` will
  never be set unless the server supports hot-reload (it does not). The signal
  is structurally dead under arXMCP's startup-pin architecture.

- **Axis 9 (Value density, continued):** `corpus_version` is already in every
  result envelope. The consuming orchestrator can trivially implement a
  session-level version guard by comparing envelope versions without any server
  changes. Adding server-side session tracking for a check the orchestrator can
  do itself is the wrong abstraction boundary.

**Suggested scope adjustment:**

Drop from this catalog. The consuming orchestrator's responsibility for
multi-turn version consistency is documented in `.claude/docs/orchestrator-rules.md`.
File as a documentation clarification (add an orchestrator rule for checking
`corpus_version` drift) if the need resurfaces.

---

### CAND-14 — Semantic eval-coverage scan

**Severity:** MINOR

**Objections:**

- **Axis 9 (Value density):** The synthesis correctly characterizes this as
  "belongs to the eval-curation track, not this observability run." The
  challenger agrees. The eval-fixture hand-labeling task (CLAUDE.md §7) is the
  open work; a coverage scan is a guide for that labeling, not an observability
  fix. Including it in this catalog dilutes the run's focus.

- **Axis 7 (Retrieval-quality regression):** The candidate could theoretically
  inform eval fixture curation and prevent indirect nDCG@5 degradation — but the
  relationship is indirect and the evaluation harness (`make eval`) is already
  skipped because `tests/eval/fixtures/queries.json` is empty (CLAUDE.md §7).
  Fixing the fixture is the prerequisite; a coverage scan on an empty fixture is
  undefined.

**Suggested scope adjustment:**

Defer to a standalone eval-curation milestone (separate from this observability
run). The `tools/coverage_scan.py` utility is straightforwardly M in effort
(requires running BGE-M3 embedder) and needs the `requires_model` gate.

---

## 5. Clean Candidates

The following candidates passed all 10 axes without objection:

- **CAND-1** — MINOR only (O(N) paper-id scan placement, sequencing with task #26); architecturally clean
  *(Note: this candidate has a MINOR finding above, but no blocking issue.)*

Fully clean (NONE):

- None of the 16 candidates reached a full NONE — every candidate has at least
  one MINOR concern. The cleanest are CAND-1 (XS, architecturally sound, just
  O(N) placement concern) and CAND-9 (pure consumer of upstream gauges, ~30 LOC).

---

## 6. Cross-Cutting Concerns

### CC-1: Three candidates add Prometheus gauges; none share a startup `count_rows()` call

CAND-2, CAND-3, CAND-7, CAND-10, and CAND-13 all involve a `count_rows()` or
`index_stats()` call at startup. The synthesis states these should share one
call but does not define the mechanism. Phase 4 implementation briefs must
designate a single cache field on `Resources` (e.g.,
`Resources.startup_chunk_count: int`) populated once in `Resources.startup`,
and all five candidates read from it. A second `count_rows()` call anywhere
except the ingest write path is a performance regression.

### CC-2: The DAG is implicit; the sequencing must be made explicit

The synthesis acknowledges dependencies informally. The full sequencing DAG is:

```
task #26 (= CAND-1) → CAND-5a (regression test passes)
                     → CAND-8 (total_rows_after_commit correct)
                     → CAND-7 (ingest-summary.json correct)
                     → CAND-3 (actual gauge correct)
                             → CAND-9 (daily report reads correct gauges)
CAND-2 (independent of CAND-1 but should share count_rows() with CAND-3)
CAND-6b (readyz extension) independent
CAND-4 (independent)
CAND-10 (independent)
CAND-11/CAND-13/CAND-14/CAND-16 — deferred
```

Phase 4 should enforce this order in the implementation plan.

### CC-3: No candidate violates the `assert`-ban or BaseHTTPMiddleware prohibition

All candidates operate in `ingest/`, `server/health.py`, `server/resources.py`,
or `tools/` — none propose using `assert` for invariants in runtime code (the
write-postcondition pattern in CAND-1 is correctly described as `if ... raise
RuntimeError`), and none propose new middleware. Architecture-lock compliance
is clean across the catalog.

### CC-4: CAND-6 is the only BP1-touching candidate; its safe form is form (b)

Only CAND-6 touches the MCP tool surface. The `/readyz`-body form (b) is BP1-
safe. If form (a) is ever pursued, the implementation brief must include the
`pytest --update-tool-schema-hash` step and the paired `EXPECTED_BP1_SHA256`
update (`tests/test_prompts.py:649`). Both pins must move in lockstep;
updating one without the other is a test failure.

### CC-5: Hypothesis is not in `pyproject.toml`; adding it is a deliberate dep decision

Four scout briefs reference Hypothesis. It is not currently a dev dep. Adding it
requires an explicit `pyproject.toml` change with a pinned version and a marker
registration in `[tool.pytest.ini_options].markers` (e.g., `stateful: marks
stateful property-based tests`). This should be a conscious decision in the
implementation milestone, not an incidental side effect.

---

## 7. Recommended Kill List

The following candidates should be dropped before Phase 4 prioritization:

- **CAND-16** (Per-session corpus-version guard): The signal is structurally
  dead under arXMCP's startup-pin architecture; the orchestrator can implement
  the same check externally without server changes. No path to non-zero value
  at v0 or v1.

- **CAND-15** (`validate_corpus` utility): Fully subsumed by CAND-2 (startup
  check) + CAND-5a (CI test). The standalone CLI adds maintenance surface with
  negligible incremental value. Fold any remaining unique value (operator ad-hoc
  CLI) into a `--validate` mode on an existing command.

The following should be deferred to the E14 S06+ backlog, not this run:

- **CAND-11** (OTel semconv alignment): Tangential to the motivating bug;
  observability quality improvement. Belongs in E14 S06+.
- **CAND-13** (embedder-version-skew gauge): Zero diagnostic value until
  BGE-M3 is upgraded. File in the re-embed/retrieval backlog.
- **CAND-14** (semantic eval-coverage scan): Belongs to the eval-curation track;
  blocked on a non-empty `queries.json` fixture.
- **CAND-12** (`corpus_integrity_token` envelope): `corpus_version` already
  serves the need; defer unless a concrete agent pipeline deficiency is
  identified.
