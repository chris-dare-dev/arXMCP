# Challenge — corpus-integrity-observability

**Challenger:** capability-scout-challenger
**Generated:** 2026-05-31
**Synthesis path:** `.claude/notes/capability-scouts/corpus-integrity-observability/artifacts/synthesis.md`
**Candidates evaluated:** 25 (CAND-1 through CAND-25; out-of-sequence: CAND-19, CAND-22, CAND-23)

---

## 1. Executive summary

0 BLOCKERs. 3 MAJORs. 9 MINORs. 13 clean candidates. The dominant issue across the catalog is **staleness of the synthesis baseline**: two candidates (CAND-24 and CAND-25) describe work the synthesis claims is unshipped but direct file inspection confirms is already fully or substantially implemented — CAND-24's four runbook files exist as real, substantive documents under `docs/ops/`, and CAND-25's `make reconcile` target is a 30-line implemented Makefile target present at `Makefile:560` and announced in `Makefile:66` (`make help`). These should be killed or reduced to a README one-liner. The second dominant issue is **value density for agent-facing candidates**: CAND-16 and CAND-18 surface agent-facing corpus-change signals, but no element of the live arXMCP sketcher → autoformalizer → tactician → fixer pipeline is wired to consume them, making both speculative capability uplift rather than near-term infrastructure — and CAND-16 carries an additional data schema blocker that makes it unimplementable as sketched.

---

## 2. BLOCKER findings

None.

---

## 3. MAJOR findings

### CAND-5 — Mid-session live `count_rows()` refresh for `arxmcp_corpus_chunk_count_actual`

**Severity:** MAJOR

**Objections:**

- **Axis 3 (Prompt-cache discipline / test contract):** Replacing the startup-cached read with a scrape-time refresh directly violates the "computed once at startup" contract pinned by `tests/test_corpus_count_reconciliation.py::TestUnindexedRowsGauge::test_gauge_set_from_cache_not_recomputed_per_scrape` (line 735). The synthesis acknowledges this but frames it as "needs explicit re-negotiation." The test contract is a deliberate architectural boundary: `server/health.py:567-568` carries an explicit "NEVER call count_rows() here" comment. That is a hard invariant documented at implementation time, not test debt.

- **Axis 8 (Effort honesty):** The synthesis implies ~30 LOC (XS effort). Actual scope is S: (a) the test contract must be re-negotiated (not just updated), (b) the proposed `_live` Counter alongside `_startup` Gauge adds a new metric name requiring a Prometheus semantics decision and alert-rule updates across CAND-1, (c) LanceDB's O(1) `count_rows()` is O(1) per single cold call, but default Prometheus scrape interval is 15s — a TTL floor is required to avoid hammering the Lance metadata footer 4 times per minute under concurrent sessions.

- **Axis 9 (Value density):** The motivating mid-session scenario is already mitigated for the most common path: UI-triggered notebook ingest fires a server-side event visible via `/readyz`. The incremental value of a scrape-time refresh vs the operator checking the next scheduled scrape (or restarting the server) is low for a single-workstation project.

**Suggested scope adjustment:** v0 = ship CAND-1 alert rules first. CAND-5 as v1 only if a concrete mid-session drift scenario is documented that CAND-1 cannot catch within its scrape interval. The synthesis T3 `_startup` vs `_live` split is the correct architectural approach when this is revisited — but it warrants a dedicated milestone brief, not a LOC estimate in a catalog.

---

### CAND-16 — `get_corpus_delta(since_version: int)` MCP tool

**Severity:** MAJOR

**Objections:**

- **Axis 4 (MCP tool-surface contract / T5):** Adds one entry to `ALL_TOOLS` in `server/tools.py`. Per CLAUDE.md §9 and `tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256` (UPDATE-ANCHOR at line 94), this forces an `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. Every future multi-agent session permanently carries this tool's description in the `tools/list` cached prefix — adding ~200–400 token overhead to BP1 on every cache write, amortized against zero confirmed call sites in the current pipeline.

- **Axis 9 (Value density / T1):** The synthesis explicitly asks the challenger to scrutinize this (T1, T5): "Is the calling agent wired to consume this?" The answer from CLAUDE.md §2 is no. The sketcher → autoformalizer → tactician → fixer pipeline has no delta-aware turn type. VersionRAG's 90% vs 58% accuracy improvement applies to version-sensitive document queries, not to a monthly-delta single-corpus math retrieval system where agents retrieve on demand and do not carry version-diff context.

- **Axis 10 (Sequencing dependencies — DATA SCHEMA BLOCKER):** `WriteStats.to_dict()` at `ingest/store.py:198-208` serializes `lancedb_version` (post-index table version integer), NOT `corpus_version` (the corpus-version.json integer). The tool's `since_version: int` parameter filters `store-stats.jsonl` by corpus version, but no such field exists in the current JSONL schema. The tool as sketched is unimplementable against the current data without first adding `corpus_version` to `WriteStats`. The synthesis did not surface this dependency.

**Suggested scope adjustment:** Kill or defer. Two independent blockers: (a) no pipeline consumer exists, creating permanent BP1 overhead with no value realization; (b) `WriteStats` schema does not support the `since_version` filter. If revisited, ship `corpus_version` field on `WriteStats` first as a standalone CAND; then `get_corpus_delta` can be re-evaluated once the data shape exists and a pipeline consumer is documented.

---

### CAND-24 — Operator runbook files at the paths `alerts.yml` references

**Severity:** MAJOR

**Objections:**

- **Axis 8 (Effort honesty — ALREADY SHIPPED):** Direct file inspection shows all four referenced runbooks exist as real, substantive documents, NOT stubs:
  - `docs/ops/failure-modes.md` — exists, full operator runbook
  - `docs/ops/backup-restore.md` — exists, full operator runbook
  - `docs/ops/drift-watchdog.md` — exists, full operator runbook
  - `docs/ops/latexml-drift-runbook.md` — exists, full operator runbook

  The synthesis adversary brief (L2) was produced before the prior milestones (m1/m2/m3/e2/e3) shipped these files. The synthesis did not verify the current state before forwarding this candidate. Scheduling work that is already done is a catalog quality failure.

**Recommended action:** Kill immediately. The only genuine remainder is whether a `corpus-drift-runbook.md` is needed for CAND-1's new alert rules — that is a ~100-line artifact that should be folded into CAND-1's scope, not a standalone candidate.

---

## 4. MINOR findings

### CAND-1 — Ship Prometheus alert rules for corpus-integrity gauges

**Severity:** MINOR

**Objections:**

- **Axis 1 (Architecture-lock compatibility — alert overlap):** The existing `ArXMCPDegradedMode` alert fires when `arxmcp_degraded_mode_active == 1`. Per `server/resources.py`, a divergence beyond `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE` already sets `DegradedState("chunk_count_diverged")`, which surfaces via `ArXMCPDegradedMode`. CAND-1(a) (drift > tolerance) would fire redundantly. The synthesis notes this overlap but does not resolve it — the implementer needs explicit guidance to avoid a noisy duplicate.

- **Axis 6 (Doc-placement discipline):** New alert rules need a `runbook_url` pointing to `docs/ops/corpus-drift-runbook.md`. CLAUDE.md §1 table specifies `docs/` is "ONLY user-facing documentation referenced by the root README.md." The `docs/ops/` tree is a pre-existing doc-placement violation; CAND-1 should not compound it without a conscious decision. Alternative: point the runbook URL to a `.claude/notes/` path (which is correct per §1) or accept the `docs/ops/` exception as already established.

**Suggested scope adjustment:** v0 = add rule (b) (`actual == -1 for 10m` — count_rows() failure sentinel; NOT covered by `ArXMCPDegradedMode`) and rule (c) (`unindexed_rows > 0 for 1h` — NOT covered). Rule (a) (above-tolerance drift) is redundant with `ArXMCPDegradedMode` for the above-threshold case; add as `warning` severity only if sub-threshold drift signal is wanted. Fold the `corpus-drift-runbook.md` artifact into CAND-1's scope (CAND-24 is already killed).

---

### CAND-3 — Write-Audit-Publish (WAP) post-write invariant in `ingest/store.py`

**Severity:** MINOR

**Objections:**

- **Axis 1 (Architecture-lock compatibility — tautology risk):** In `ingest/store.py`, `count_rows()` is already called at line 938 and assigned to `chunk_count`. At line 942, `stats.total_rows_after_commit = chunk_count`. The synthesis's proposed gate — "if `tbl.count_rows() != stats.total_rows_after_commit`" — compares `chunk_count` against `chunk_count`, which is always true and therefore never fires. A meaningful WAP gate requires either: (a) a caller-provided `expected_total` parameter to `write_chunks`, or (b) a second `count_rows()` call AFTER the marker write (verifying the marker file was written with the correct value). The per-call path does not need (a) — the caller doesn't know the expected total before the write. Option (b) catches marker-file corruption but not count divergence.

**Suggested scope adjustment:** v0 = add the gate as a second `count_rows()` read immediately after `write_corpus_version_marker` returns, verifying that `tbl.count_rows() == marker_chunk_count_just_written`. This catches filesystem/serialization failures in the marker write itself, which is the genuine WAP contract here. The synthesis's comparison is a tautology in the current code structure — this must be resolved in the implementation brief.

---

### CAND-6 — BM25 index version cross-check vs LanceDB corpus version

**Severity:** MINOR

**Objections:**

- **Axis 6 (Doc-placement / gauge registry inconsistency):** The synthesis says "New Gauge in `server/observability/metrics.py`" but all existing corpus-integrity gauges (`CORPUS_CHUNK_COUNT_MARKER`, `CORPUS_CHUNK_COUNT_ACTUAL`, `CORPUS_UNINDEXED_ROWS`) live in `server/health.py:93-134`. Adding a new corpus-integrity gauge to `metrics.py` instead of `health.py` splits the corpus-integrity gauge registry across two files. Minor but worth noting for maintainability.

**Suggested scope adjustment:** v0 = define the new gauge in `server/health.py` alongside the existing corpus-count pair; add the startup cross-check in `server/resources.py::Resources.startup`.

---

### CAND-7 — Kùzu citation graph paper-count cross-check vs LanceDB

**Severity:** MINOR

**Objections:**

- **Axis 10 (Sequencing dependencies):** `cite_neighbors` MCP handler is a v1 stub (CLAUDE.md §7). A graph coverage gauge will chronically show < 100% for operators who have not run `ingest/graph_ingest.py` — which is optional / separate from the main ingest path. Without clear documentation that sub-100% is expected-and-normal when graph ingest has not run, the gauge will generate operator confusion. The alert rule (if added via CAND-1) should explicitly condition on graph DB file existence.

- **Axis 5 (Local-first — Kùzu version pin):** Adding `asyncio.to_thread(kuzu_query)` at startup is fine (loopback-only). However, `kuzu==0.11.3` is a pinned archived project (CLAUDE.md §8 Gotcha 2). Verify the 0.11.3 Python API works safely under `asyncio.to_thread` before implementing; the project's existing use of Kùzu is async-wrapped in `server/graph_queries.py` and should be the reference pattern.

**Suggested scope adjustment:** v0 = add check with: (a) conditional on graph DB file existence (skip + log "graph DB absent, skipping coverage check"), (b) documentation that sub-100% is expected until `make ingest-graph` has run, (c) no alert rule for coverage < threshold — the gauge alone is sufficient until `cite_neighbors` handler is un-stubbed.

---

### CAND-9 — SHA-256 sidecar checksum for `corpus-version.json`

**Severity:** MINOR

**Objections:**

- **Axis 8 (Effort honesty):** The synthesis estimates ~25 LOC. The full implementation scope is S: (a) sidecar write in `ingest/store.py::write_corpus_version_marker` (atomic, alongside the marker), (b) startup verification in `server/resources.py::Resources.startup` (already ~600 LOC, complex function), (c) new `DegradedState` reason or WARN-only path decision, (d) tests for write, verify, and mismatch paths. Realistic: S, not XS.

**Suggested scope adjustment:** v0 = write the sidecar and emit a structured WARN on mismatch at startup — do NOT enter DegradedState for a missing/mismatched `.sha256` file in v0, since the reconcile tool (`make reconcile`) legitimately rewrites the marker without the sidecar. DegradedState upgrade is v1 once write+verify round-trip is stable in tests.

---

### CAND-11 — AVH-style auto-historical bounds (rolling-mean drift)

**Severity:** MINOR

**Objections:**

- **Axis 8 (Effort honesty — bootstrapping problem):** The synthesis estimates ~100 LOC and notes "N >= 7 before bounds become meaningful." For a monthly delta ingest on the seed corpus (50 papers), accumulating 7 history points takes 7 months of operation. The IQR-based bounds will be noise until then. The synthesis does not flag this bootstrapping problem, which affects the candidate's near-term value.

- **Axis 9 (Value density):** For a single-workstation operator running monthly ingests, CAND-3 (WAP write-time gate) and CAND-1 (alert on divergence) address the same "this run wrote wrong number of chunks" signal with less bootstrapping overhead. CAND-11 adds value primarily when the ingest runs at weekly+ frequency and the corpus is large enough to accumulate bounds data.

**Suggested scope adjustment:** Defer until delta ingest runs at weekly minimum frequency. Do not schedule before CAND-1, CAND-3, CAND-8.

---

### CAND-17 — OTel `mcp.session.id` attribute + `corpus_snapshot` per-session event

**Severity:** MINOR

**Objections:**

- **Axis 8 (Effort honesty — session-open hook gap):** The synthesis says ~40 LOC and notes `current_session_id` ContextVar already exists at `server/observability/tracing.py:118`. This is confirmed. The (a) part (`mcp.session.id` span attribute) is genuinely ~10 LOC. However, CAND-17(b) (`corpus_snapshot` event at session-open) has no natural session-open hook in the current server — the server is stateless between tool calls. The "first tool call per session" workaround requires a per-session tracking dict to detect the first call, which adds complexity not in the LOC estimate.

**Suggested scope adjustment:** v0 = (a) only: add `mcp.session.id` attribute to `span_tool_call` from `current_session_id`. This is self-contained and immediately valuable for Phoenix session grouping. CAND-17(b) is v1, gated on a session-open hook (which CAND-18's `corpus_version_at_session_start` tracking in `session.py` naturally provides).

---

### CAND-18 — Session corpus guard / `corpus_version_at_session_start` advisory field

**Severity:** MINOR

**Objections:**

- **Axis 4 (MCP tool-surface contract / T5):** Adding `session_corpus_mismatch: false` to every result envelope does NOT require an `EXPECTED_TOOL_SCHEMA_SHA256` re-pin (confirmed: the schema pin covers `inputSchema`, not the runtime result envelope). However, the constant `false` → `true` transition on mid-session cutover produces a non-identical byte in the tool result, invalidating the Tier-1 exact-query cache key for that turn. This is a cache MISS not a catastrophe — but it is a non-obvious side effect worth documenting.

- **Axis 9 (Value density / T1):** The calling pipeline is not wired to consume `session_corpus_mismatch: true`. Value realization is speculative today.

**Suggested scope adjustment:** v0 = add `corpus_version_at_session_start` to `server/session.py` only (internal tracking, no envelope change — also needed for CAND-17(b)). Defer the `session_corpus_mismatch` envelope field until a pipeline agent is documented as consuming it.

---

### CAND-20 — mcpdiff `.mcpc.json` contract snapshot artifact

**Severity:** MINOR

**Objections:**

- **Axis 6 (Doc-placement discipline):** The synthesis suggests committing `.mcpc.json` to the repo root. CLAUDE.md §1: "Repo root — Only `README.md`, `CLAUDE.md`, `CHANGES.md`, `SECURITY.md`, `OWNERS.md`. Nothing else." A generated `.mcpc.json` at the root violates this rule.

**Suggested scope adjustment:** v0 = write the snapshot artifact to `.claude/docs/tools-snapshot.json`. Update `make snapshot-tools` target accordingly. The `git diff` workflow is identical; only the path changes.

---

### CAND-25 — `make reconcile` target + README documentation

**Severity:** MINOR

**Objections:**

- **Axis 8 (Effort honesty — substantially already shipped):** `make reconcile` is a fully implemented 30-line Makefile target at `Makefile:560`. It appears in `make help` output at `Makefile:66`. The synthesis claims both the target and the README entry are missing — only the README entry is missing.

**Suggested scope adjustment:** v0 = add one line to README "Common tasks" section pointing to `make reconcile`. The Makefile target is already done.

---

## 5. Clean candidates

- **CAND-2** — Daily report `## Corpus integrity` + `## Retrieval index health` sections. No violations; genuine gap against `tools/daily_metrics_report.py`; value density is good for the operator cadence.
- **CAND-4** — structlog migration + `capture_logs()`-assertable startup events. Sound; the gap at `server/resources.py:507-515` is real; `ingest/store.py:961-969` is the model to follow.
- **CAND-8** — End-to-end multi-paper write→server→/readyz integration test. No violations; the seam between `tests/test_store.py` (write path) and `tests/test_corpus_count_reconciliation.py` (read path, mocked) is a real gap; this was in the prior catalog as unshipped.
- **CAND-10** — Per-run `paper_id_min`/`paper_id_max` in `ingest-summary.json`. XS; `ingest/ingest_summary.py` schema v1 confirmed to have no such fields; trivial addition.
- **CAND-12** — Evidently AI-style dataset drift checks (native impl). M but sound; no OSS dep violation (native impl explicit); genuine gap.
- **CAND-13** — ReproRAG-style startup reproducibility check. No violations; synthesizer's defer-to-post-ingest-cron recommendation is endorsed (30s startup overhead unacceptable).
- **CAND-14** — LLM Readiness Harness composite-readiness CI gate. L effort; parking-lot for single-workstation; no violations.
- **CAND-15** — "Still Fresh?" eval-fixture chunk_id liveness check. XS; no violations; genuine gap in `tools/validate_eval_fixtures.py`.
- **CAND-19** — `tools/audit.py` / `make audit` dev utility. XS; no violations. Note: DuckDB is NOT a current project dep (confirmed: absent from `pyproject.toml`) despite synthesis claim — use Python stdlib or jq.
- **CAND-21** — `infra/corpus-checks.yml` versioned threshold config. XS; `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE` already in `server/config.py` as Pydantic field; centralization value is real but small.
- **CAND-22** — Weaviate-style per-shard unindexed-rows reframing. Spike-first per synthesis; correct recommendation; no violations.
- **CAND-23** — LanceDB v0.33 manifest-summary API. Parking-lot; API experimental; no violations.

---

## 6. Cross-cutting concerns

**6.1 Two candidates describe already-shipped work (CAND-24, CAND-25-partial).** Both were forwarded from adversary briefs generated before m1/m2/m3/e2/e3 shipped without post-milestone verification. `docs/ops/failure-modes.md`, `docs/ops/backup-restore.md`, `docs/ops/drift-watchdog.md`, `docs/ops/latexml-drift-runbook.md`, and `make reconcile` are all real implementations. This is a synthesis quality signal: adversary briefs should be verified against `git log` + current file state before forwarding candidates as unshipped.

**6.2 T1 — Agent-facing candidates (CAND-16, CAND-17, CAND-18) need pipeline-wiring prerequisite.** CAND-17 (OTel session ID) has immediate independent value for Phoenix session grouping. CAND-16 and CAND-18 require documented pipeline consumers before their BP1 overhead is justified. Kill CAND-16 (additional schema blocker); defer CAND-18 to a v0 internal-only `corpus_version_at_session_start` in `session.py`.

**6.3 T2 — CAND-3 (write-time) and CAND-1 (read-time) are complementary defense-in-depth.** Both should ship; CAND-3 first (prevents bad marker), CAND-1 second (detects bad marker at startup). The WAP gate logic needs rethinking (see CAND-3 finding) before implementation, but the candidate itself is sound.

**6.4 T5 — Only CAND-16 adds an MCP tool, triggering `EXPECTED_TOOL_SCHEMA_SHA256` re-pin.** CAND-18 (envelope field) and CAND-17 (span attribute) do NOT require a re-pin. Synthesis was correct on this.

**6.5 CAND-3 WAP gate as sketched is a tautology.** `stats.total_rows_after_commit = tbl.count_rows()` at line 942 means any subsequent comparison against `tbl.count_rows()` is identity. The gate needs a redesign (see CAND-3 finding). This does not block the candidate but must be caught before the implementation brief is written.

**6.6 `docs/ops/` placement is a pre-existing doc-placement violation.** CLAUDE.md §1 says `docs/` allows only `install.md`. The 16-file `docs/ops/` tree is a pre-existing exception. Candidates should not create new files under `docs/ops/` without a conscious decision to extend this exception; `.claude/docs/` is the strictly-correct location for new agent-internal runbooks.

**6.7 DuckDB is not a current project dependency.** CAND-19 references "DuckDB is already used elsewhere in arXMCP per pyproject.toml" — this claim is incorrect; DuckDB is absent from `pyproject.toml`. The `make audit` utility in CAND-19 must use Python stdlib `json` iteration, not DuckDB, unless a new dependency is explicitly added.

---

## 7. Recommended kill list

**CAND-24 — Operator runbook files** — KILL. All four referenced runbooks exist as substantive, non-stub documents under `docs/ops/`. This candidate represents work that is already done. The only remainder (a `corpus-drift-runbook.md` for CAND-1's new alert rules) should be folded into CAND-1's scope.

**CAND-16 — `get_corpus_delta(since_version: int)` MCP tool** — KILL. Two independent blockers: (a) no pipeline consumer is wired to receive delta information, creating permanent BP1 prefix overhead with no value realization; (b) `WriteStats.to_dict()` serializes `lancedb_version` not `corpus_version`, so the JSONL cannot be filtered by `since_version` as the tool's interface requires. If revisited, add `corpus_version` to `WriteStats` first as a standalone prerequisite, then re-evaluate once a pipeline consumer is documented.
