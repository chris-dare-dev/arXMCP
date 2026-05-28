# Final Report — capability-scout 2026q2-observability-reporting

**Generated:** 2026-05-28 (main session, Phase 4 prioritize)
**Scope:** observability & reporting — make "persisted metadata silently diverges from ground truth" (and wrong values in logs/reports) automatically catchable.
**Inputs:** synthesis.md (16 candidates) + challenge.md (0 BLOCKER, 4 MAJOR, 10 MINOR; kill CAND-15/16; defer CAND-11/12/13/14).

## 1. Executive summary

All 5 scouts converged, with unusual unanimity, on a single root cause and a single dominant fix: derived corpus aggregates (`chunk_count`/`paper_count`) are computed from the in-flight per-paper batch and never reconciled against the write target, and **nothing — not a write-time check, a startup invariant, a metric, a log, or a test — bridges the persisted claim to `tbl.count_rows()`.** The top-3 by RICE are **CAND-1 (fix the count at write time — 36.0), CAND-3 (corpus-size Prometheus gauges marker-vs-actual — 9.6), and CAND-9 (daily-report corpus-integrity section — 3.0)** — and they form a clean dependency chain (CAND-1 → CAND-3 → CAND-9), so the thematic recommendation is to ship them as **one "corpus-integrity observability" milestone** alongside CAND-2 (startup reconciliation guard), CAND-5a (the multi-paper regression test), and CAND-4 (structured/assertable logging). The challenger found **zero BLOCKERs** — the catalog is architecturally clean (no `assert`-ban / `BaseHTTPMiddleware` / no-fork / non-loopback violations) — and its sharpest contribution is the cross-cutting note that all gauge candidates must share one startup-cached `count_rows()` and that the work has a real sequencing DAG rooted at CAND-1 (= in-flight task #26). **Honest caveat:** RICE-light here is effort-sensitive (XS effort × 5-brief confidence × gap-killing impact drives CAND-1 to 36); the absolute numbers matter less than the clear top-tier cut and the dependency order.

## 2. Quick-glance ranking table

| Rank | Cand | Title | Category | Size | R | I | C | E | RICE | Challenger |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | CAND-1 | Compute corpus counts from the table, not the batch | Ingestion/parsing | XS | 3 | 3 | 1.0 | 0.25 | **36.0** | MINOR |
| 2 | CAND-3 | Corpus-size Prometheus gauges (marker vs actual) + alert | Ops/infra | XS | 3 | 1 | 0.8 | 0.25 | **9.6** | MINOR |
| 3 | CAND-9 | Daily-report corpus-integrity + corpus-version section | Ops/infra | XS | 3 | 0.5 | 0.5 | 0.25 | **3.0** | MINOR |
| 4 | CAND-2 | Startup marker-vs-table reconciliation → degraded | Ops/infra | S | 3 | 1 | 0.8 | 1 | 2.4 | MINOR |
| 5 | CAND-4 | Wire JSON logging by default + assertable write fields | Ops/infra | S | 3 | 1 | 0.8 | 1 | 2.4 | MINOR |
| 6 | CAND-5 | Reconciliation tests (multi-paper + Hypothesis) | Ops/infra | S | 3 | 1 | 0.8 | 1 | 1.8 | MAJOR |
| 7 | CAND-8 | Enrich WriteStats / per-run ingest manifest | Ingestion/parsing | S | 3 | 0.5 | 0.5 | 1 | 0.75 | MINOR |
| 8 | CAND-11 | OTel GenAI/MCP semconv alignment | Agent harness | S | 3 | 0.5 | 0.3 | 1 | 0.45 (defer) | MINOR |
| 9 | CAND-7 | Ingest throughput metrics (sentinel bridge) | Ops/infra | M | 3 | 1 | 0.5 | 3 | 0.375 | MAJOR |
| 10 | CAND-6 | Corpus-status surface (`/readyz` body / tool) | MCP tool surface | S | 1 | 0.5 | 0.8 | 1 | 0.3 | MAJOR |
| 11 | CAND-13 | Embedder-version-skew gauge | Retrieval quality | S | 1 | 0.5 | 0.5 | 1 | 0.19 (defer) | MAJOR |
| 12 | CAND-10 | LanceDB `index_stats()` unindexed-rows guard | Ops/infra | S | 1 | 0.5 | 0.3 | 1 | 0.15 | MINOR |
| 13 | CAND-12 | `corpus_integrity_token` in envelope | Agent harness | S | 1 | 0.5 | 0.3 | 1 | 0.15 (defer) | MINOR |
| 14 | CAND-14 | Semantic eval-coverage scan | Retrieval quality | M | 1 | 1 | 0.3 | 3 | 0.1 (defer) | MINOR |
| — | CAND-15 | `validate_corpus` utility | Ops/infra | XS | — | — | — | — | KILLED | MINOR |
| — | CAND-16 | Per-session corpus-version guard | Agent harness | S | — | — | — | — | KILLED | MINOR |

*Effort note: CAND-1's XS is the immediate one-call fix (`tbl.count_rows()` for `len(chunks)`); the challenger's O(N²)-at-200K-papers concern bumps the "proper" form (move the marker write to once-per-bulk-run) to S — see CAND-1 detail.*

## 3. Top 10 in detail

### Rank 1 — CAND-1 — Compute corpus-version counts from the table, not the batch
- **RICE:** R3 × I3 × C1.0 / E0.25 = **36.0** (5-brief triangulation → C=1.0; kills the motivating gap → I=3).
- **What/why (synthesis):** `ingest/store.py:900-908` writes the marker with `chunk_count=len(chunks)` / `paper_count=len({paper_ids})` from the per-paper batch; `bulk_ingest`/`re_embed` call `write_chunks` once per paper → the final marker holds the last paper's counts (106 vs 10,298). Replace with `tbl.count_rows()` + a distinct-paper-id count derived from the committed table. `version` is already correct; only the counts lie. No cache-key/BP1 impact.
- **Challenger (MINOR):** the per-paper `paper_id` unique scan is O(N) → O(N²) over a 200K-paper bulk run. Fix: move `write_corpus_version_marker` **out of the per-paper loop** to once-per-bulk-run (one `count_rows()` + one paper-id scan at the end) — the architecturally correct form. At current 50-paper/notebook scale the naive form is fine.
- **Rank rationale:** the root-cause fix the entire scout converged on; XS-S effort, max confidence, gap-killing. **Already in flight as task #26 — this report supplies the precise mechanism + the once-per-run refinement + the regression test (CAND-5a).** P0, critical path for the whole catalog.

### Rank 2 — CAND-3 — Corpus-size Prometheus gauges (marker vs actual) + divergence alert
- **RICE:** R3 × I1 × C0.8 / E0.25 = **9.6**.
- **What/why:** add `arxmcp_corpus_chunk_count_marker` + `arxmcp_corpus_chunk_count_actual` gauges (mirroring `CORPUS_VERSION_GAUGE`, `server/health.py:92`), set once at startup from the marker + a startup-cached `count_rows()`; operators alert on `abs(actual-marker)/actual > 0.05` (Qdrant's points-vs-indexed delta idiom). Outside the `tools/list`/BP1 pins → cache-safe.
- **Challenger (MINOR):** "~15 LOC" omits the ~30 LOC test surface; must share the startup `count_rows()` with CAND-2 (designate one `Resources` cache field). Real effort ~45 LOC.
- **Rank rationale:** tiny change, turns the divergence into a standing alertable signal (not a one-time log). Pairs with CAND-2.

### Rank 3 — CAND-9 — Daily-report corpus-integrity + corpus-version section
- **RICE:** R3 × I0.5 × C0.5 / E0.25 = **3.0**.
- **What/why:** add a `## Corpus integrity` section to `tools/daily_metrics_report.py` (marker vs actual + red-flag) plus a `corpus_version`/uptime header row.
- **Challenger (MINOR):** pure consumer of CAND-3's gauges → must ship after CAND-3 (else it would read LanceDB from a reporting script, violating server/ingest separation). ~30 LOC accurate.
- **Rank rationale:** cheap human-facing surface that closes the loop in the daily cadence. Tail of the CAND-1→CAND-3→CAND-9 chain.

### Rank 4 — CAND-2 — Startup marker-vs-table reconciliation invariant → degraded
- **RICE:** R3 × I1 × C0.8 / E1 = **2.4**.
- **What/why:** at `Resources.startup`, `count_rows()` vs `corpus_info.chunk_count`; on divergence WARN + set `DegradedState.reason="chunk_count_diverged"` → existing `/readyz` 503 + `arxmcp_degraded_mode_active` gauge surface it. Defense-in-depth even after CAND-1.
- **Challenger (MINOR):** `DegradedState.reason` is a plain `str` (`server/corpus.py:135`), not an enum (one-liner, not an enum extension); must share the startup `count_rows()` with CAND-3.
- **Rank rationale:** the always-on safety net that catches future regressions / hand-edited markers. Lean WARN-and-serve (retrieval correctness is unaffected).

### Rank 5 — CAND-4 — Wire structured JSON logging by default + assertable write-path fields
- **RICE:** R3 × I1 × C0.8 / E1 = **2.4**.
- **What/why:** `JsonFormatter` exists but isn't installed; add `ARXMCP_LOG_FORMAT={text|json}` wiring, emit a structured `{event:"write_chunks_done", chunk_count, table_rows, match}` write-path event (machine-queryable + test-assertable), and a `contextvars` `mcp.session_id`.
- **Challenger (MINOR):** verify (not assume) no test greps human-readable log text before flipping the default (`grep -r caplog tests/`); the `contextvars` session-id needs a `None`-graceful path for non-request (startup/sentinel) logs — defer it as a sub-item.
- **Rank rationale:** "we logged it" → "CI asserts what we logged"; the bug produced no log line at all. Ship the env-var + structured event in v0; defer session-id propagation.

### Rank 6 — CAND-5 — Reconciliation regression tests (multi-paper + Hypothesis)
- **RICE:** R3 × I1 × C0.8 / E1 = 2.4 × 0.75 (MAJOR) = **1.8**.
- **What/why:** (a) deterministic multi-paper test asserting `marker.chunk_count == tbl.count_rows()` (fails today, passes after CAND-1); (b) Hypothesis `RuleBasedStateMachine` + `@invariant`.
- **Challenger (MAJOR):** (a) is the must-have ~25 LOC; (b) is real ongoing maintenance + a first-use learning curve + a new dev-dep (Hypothesis not in `pyproject.toml`) — split (b) into its own later S milestone (`pytest -m stateful`/nightly).
- **Rank rationale:** (a) is the load-bearing regression guard and ships WITH CAND-1; (b) is deferred.

### Rank 7 — CAND-8 — Enrich WriteStats / per-run ingest manifest
- **RICE:** R3 × I0.5 × C0.5 / E1 = **0.75**.
- **What/why:** add `paper_id` + `total_rows_after_commit` to `WriteStats`; rename ambiguous `chunk_count` → `chunks_written_this_call`; optional `ingest-summary.json`.
- **Challenger (MINOR):** the rename is a breaking `store-stats.jsonl` schema change (no readers today, but keep `chunk_count` as a deprecated alias for one cycle); ship `paper_id` independently of `total_rows_after_commit` (which depends on CAND-1).
- **Rank rationale:** makes the ops log auditable per-paper; modest value, pairs with CAND-1's count.

### Rank 8 — CAND-11 — OTel GenAI/MCP semconv alignment *(defer)*
- **RICE:** R3 × I0.5 × C0.3 / E1 = **0.45**.
- **Challenger (MINOR):** tangential to the motivating bug; Phoenix/Datadog compatibility QOL. **Defer to E14 S06+.**

### Rank 9 — CAND-7 — Ingest throughput metrics (sentinel bridge)
- **RICE:** R3 × I1 × C0.5 / E3 = 0.5 × 0.75 (MAJOR) = **0.375**.
- **What/why:** the note-08 `arxmcp_ingest_*` families are specified but never implemented; emit via `ingest-summary.json` → `refresh_sentinel_metrics`.
- **Challenger (MAJOR):** the *writer* side is net-new (new sentinel schema + server gauges + reader hook + tests → M+, not S/M); must ship after CAND-1 (else the sentinel carries the same wrong counts); decide counter-vs-gauge semantics up front (lean last-run gauges).
- **Rank rationale:** real value (ingest is unobservable today) but M+ effort and CAND-1-dependent. A natural second milestone after the corpus-integrity bundle.

### Rank 10 — CAND-6 — Corpus-status surface (`/readyz` body / `get_corpus_status` tool)
- **RICE:** R1 × I0.5 × C0.8 / E1 = 0.4 × 0.75 (MAJOR) = **0.3**.
- **Challenger (MAJOR):** the MCP-tool form re-pins `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` (lockstep) for an agent use case no sub-role currently needs. **v0 = `/readyz`-body extension only (BP1-free)**; defer the tool form until a concrete agent need exists.
- **Rank rationale:** the `/readyz`-body half is a near-free add (fold into the corpus-integrity bundle); the tool half is parked.

*(Ranks 11–14: CAND-13 embedder-skew gauge, CAND-10 unindexed-rows guard, CAND-12 envelope token, CAND-14 eval-coverage — all low RICE; dispositions in §4/§6.)*

## 4. Recommended next steps

1. **Feed ONE bundle to `/roadmap` first — "corpus-integrity observability".** It is the coherent top-tier: **CAND-1** (root fix, = task #26, P0) → **CAND-2 + CAND-3** (startup guard + gauges, sharing one `Resources.startup_chunk_count`) → **CAND-9** (daily report) + **CAND-5a** (regression test) + **CAND-4** (structured/assertable logging, minus session-id). This is the minimal set that makes the bug class *automatically catchable* — exactly the user's stated goal — and the RICE top-3 all live here. `/roadmap` will decompose it into `<slug>-mN` milestones honoring the DAG.
2. **Two Spike-lane items (unvalidated assumptions) — one spike each before a milestone:**
   - **CAND-10 spike:** confirm `num_partitions=1` synchronous HNSW build never leaves `num_unindexed_rows > 0` in normal operation (and that `tbl.list_indices()` exists in lancedb 0.30.x to discover index names) → determines whether the unindexed-rows guard is a pure tripwire worth a few LOC.
   - **CAND-7 spike:** decide the `ingest-summary.json` schema + counter-vs-gauge semantics + the new server-side reader contract before committing the M+ milestone.
3. **Second milestone (after the bundle): CAND-7 + CAND-8** — ingest throughput metrics + WriteStats enrichment, both CAND-1-dependent; together they close "ingest is unobservable from `/metrics`" (the note-08 deferred stub).
4. **Park for the E14 S06+ backlog / next scout:** CAND-11 (OTel semconv), CAND-12 (envelope token), CAND-13 (embedder-skew gauge), CAND-14 (eval-coverage scan). All are real but tangential to the motivating bug, or blocked on a precondition (a second embedder version; a non-empty `queries.json`).
5. **Drop (killed):** CAND-15 (`validate_corpus` — subsumed by CAND-2 + CAND-5a; fold any ad-hoc CLI value into a `python -m server.corpus --validate` mode) and CAND-16 (per-session version guard — structurally dead under the startup-pin architecture; the orchestrator can compare envelope `corpus_version` itself).

## 5. Honest limitations

- Each scout had a ~15-minute budget; the comparative/oss-trends scouts cover the integrity-tooling landscape well, but the multi-agent and research-frontier scouts were steered onto an observability scope that is narrower than their usual math-retrieval remit — their candidates (CAND-11/12/13/14) skew speculative and correctly land in the parking lot.
- 5-brief triangulation on CAND-1 is unusually strong evidence, but it reflects that the bug was handed to the scouts pre-diagnosed — the convergence validates the fix, it does not independently discover the problem.
- Effort numbers are t-shirts → person-weeks (XS=0.25w … L=8w); ±50% is the realistic ceiling. RICE-light is effort-sensitive — CAND-1's 36.0 and CAND-3's 9.6 reflect XS effort more than a 12× value gap over CAND-2.
- The challenger evaluated against current `CLAUDE.md` architecture locks; the only BP1-touching candidate (CAND-6 tool form) is correctly cut to its BP1-free form. If conventions evolve, the CAND-6 calculus changes.

## 6. Cross-reference index

| Cand | comparative | research-frontier | oss-trends | multi-agent | adversary |
|---|---|---|---|---|---|
| CAND-1 | C2 | 2.3 | 2.1/2.5/2.7 | C2 | H1 |
| CAND-2 | C6, C8 | — | — | C2 (ALTK) | H3 |
| CAND-3 | C3, C7 | (2.6) | — | — | M5, H3 |
| CAND-4 | C6 | theme | 2.2 | — | M2, L3 |
| CAND-5 | — | 2.2 | 2.3 | — | M4 |
| CAND-6 | C10, C4 | — | — | C3 | H3 |
| CAND-7 | C5 | — | — | C6 | H2 |
| CAND-8 | C5, C9 | — | — | — | M1 |
| CAND-9 | C4 | — | — | — | M3, L2 |
| CAND-10 | C1 | — | (2.6 soda) | — | — |
| CAND-11 | — | — | — | C1, C7 | — |
| CAND-12 | C10 | — | — | C3 | — |
| CAND-13 | — | 2.6 | — | C8 | — |
| CAND-14 | — | 2.5 | — | — | — |
| CAND-15 | — | — | 2.4 | — | — |
| CAND-16 | — | — | — | C4 | — |

## Handoff offer

The top candidates above (CAND-1/3/9 ≥ 3.0, plus the coherent CAND-2/4/5a) are ready to feed the `roadmap` skill as a source brief. To materialize as a roadmap with milestones:

```
/roadmap corpus-integrity-observability --brief "$(head -200 .claude/notes/capability-scouts/2026q2-observability-reporting/artifacts/final-report.md)"
```

The roadmap skill will refine → decompose → sequence → materialize from this report (honoring the CAND-1 → CAND-3 → CAND-9 DAG and the two spike-lane items), and its milestones (`corpus-integrity-observability-mN`) hand off to `/milestone-pipeline` for execution.

*(capability-scout NEVER auto-invokes `/roadmap` — this is an offer; you choose the cut.)*
