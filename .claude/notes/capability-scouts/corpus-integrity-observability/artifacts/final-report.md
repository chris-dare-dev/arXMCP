# Final Report — corpus-integrity-observability

**Scout ID:** corpus-integrity-observability
**Generated:** 2026-05-31
**Synthesis:** [`artifacts/synthesis.md`](synthesis.md) — 25 deduplicated candidates
**Challenge:** [`artifacts/challenge.md`](challenge.md) — 0 BLOCKER, 3 MAJOR, 9 MINOR, 13 NONE; 2 kills recommended
**Phase:** Phase 4 / final report

---

## 1. Executive summary

The top 3 candidates by RICE-light are **CAND-1 (Prometheus alert rules; RICE 36)**, **CAND-3 (Write-time WAP gate in `ingest/store.py`; RICE 7.2)**, and **CAND-8 (End-to-end multi-paper write→server→/readyz integration test; RICE 7.2 — tie)**. The thematic recommendation is *operationalize the m1-m3 gauges into alerts and write-time gates* — the prior epic's milestones closed the detection capabilities but the alarm and write-gate surfaces never landed. The challenger flagged two existing-work surprises (CAND-24 runbooks and CAND-25 `make reconcile` Makefile target are already shipped — the adversary brief pre-dated their landing) and one architecture-lock issue worth surfacing (CAND-3's sketched gate is a tautology against current code at `ingest/store.py:938-942` — the implementation brief must redesign the gate, e.g. as a post-marker-write second `count_rows()` against the marker file). Confidence in the top 3 is high (4-brief triangulation on CAND-1; 3-brief on CAND-3 and CAND-8); confidence in the agent-facing candidates (CAND-16/17/18) is low because no calling-pipeline consumer is documented today.

---

## 2. Quick-glance ranking table

| Rank | CAND id | Title | Category | Size | R | I | C | E | Adj | RICE | Challenger |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | CAND-1 | Prometheus alert rules for corpus-integrity gauges | Ops / infra | XS | 3 | 3 | 1.0 | 0.25 | 1.0 | **36.0** | MINOR |
| 2 | CAND-3 | WAP write-time invariant in `ingest/store.py` | Ingestion / parsing | S | 3 | 3 | 0.8 | 1 | 1.0 | **7.2** | MINOR (redesign gate) |
| 3 | CAND-8 | End-to-end multi-paper write→/readyz integration test | Ops / infra | S | 3 | 3 | 0.8 | 1 | 1.0 | **7.2** | NONE |
| 4 | CAND-6 | BM25 index version cross-check vs LanceDB | Ops / infra | XS | 3 | 1 | 0.3 | 0.25 | 1.0 | 3.6 | MINOR |
| 5 | CAND-4 | structlog migration + `capture_logs()`-assertable startup events | Ops / infra | S | 3 | 1 | 0.8 | 1 | 1.0 | 2.4 | NONE |
| 6 | CAND-10 | Per-run `paper_id_min`/`max` in `ingest-summary.json` | Ingestion / parsing | XS | 3 | 0.5 | 0.3 | 0.25 | 1.0 | 1.8 | NONE |
| 7 | CAND-15 | "Still Fresh?" eval-fixture chunk_id liveness | Retrieval quality | XS | 3 | 0.5 | 0.3 | 0.25 | 1.0 | 1.8 | NONE |
| 8 | CAND-19 | `make audit` dev utility over `store-stats.jsonl` | Ops / infra | XS | 3 | 0.5 | 0.3 | 0.25 | 1.0 | 1.8 | NONE (no DuckDB dep) |
| 9 | CAND-20 | mcpdiff `.mcpc.json` contract snapshot | MCP tool surface | XS | 3 | 0.5 | 0.3 | 0.25 | 1.0 | 1.8 | MINOR (path) |
| 10 | CAND-21 | `infra/corpus-checks.yml` versioned threshold config | Ops / infra | XS | 3 | 0.5 | 0.3 | 0.25 | 1.0 | 1.8 | NONE |
| 11 | CAND-22 | Weaviate per-shard unindexed-rows reframing | Ops / infra | XS | 3 | 0.5 | 0.3 | 0.25 | 1.0 | 1.8 | NONE (spike first) |
| 12 | CAND-23 | LanceDB v0.33 manifest-summary API | Ingestion / parsing | XS | 3 | 0.5 | 0.3 | 0.25 | 1.0 | 1.8 | NONE (parking — exp API) |
| 13 | CAND-25 | `make reconcile` + README docs | Ops / infra | XS | 3 | 0.5 | 0.3 | 0.25 | 1.0 | 1.8 | MINOR (Makefile already shipped) |
| 14 | CAND-2 | Daily report `## Corpus integrity` + retrieval-health sections | Ops / infra | S | 3 | 1 | 0.5 | 1 | 1.0 | 1.5 | NONE |
| 15 | CAND-5 | Mid-session live `count_rows()` refresh | Ops / infra | S | 3 | 1 | 0.5 | 1 | 0.75 | 1.13 | **MAJOR** |
| 16 | CAND-17 | OTel `mcp.session.id` + `corpus_snapshot` event | Agent harness | S | 3 | 1 | 0.3 | 1 | 1.0 | 0.9 | MINOR (a-only v0) |
| 17 | CAND-7 | Kùzu graph paper-count cross-check vs LanceDB | Citation graph | S | 3 | 0.5 | 0.3 | 1 | 1.0 | 0.45 | MINOR (cond. on graph) |
| 18 | CAND-9 | SHA-256 sidecar checksum for `corpus-version.json` | Ingestion / parsing | XS | 3 | 0.5 | 0.3 | 1 | 1.0 | 0.45 | MINOR (S not XS) |
| 19 | CAND-18 | Session corpus guard advisory envelope field | MCP tool surface | S | 3 | 0.5 | 0.3 | 1 | 1.0 | 0.45 | MINOR (v0 internal-only) |
| 20 | CAND-12 | Evidently-style dataset drift checks (native impl) | Retrieval quality | M | 3 | 0.5 | 0.5 | 3 | 1.0 | 0.25 | NONE |
| 21 | CAND-11 | AVH-style auto-historical bounds | Ingestion / parsing | M | 3 | 0.5 | 0.3 | 3 | 1.0 | 0.15 | MINOR (bootstrap problem) |
| 22 | CAND-13 | ReproRAG-style startup reproducibility check | Retrieval quality | M | 3 | 0.5 | 0.3 | 3 | 1.0 | 0.15 | NONE (post-ingest cron) |
| 23 | CAND-16 | `get_corpus_delta(since_version)` MCP tool | MCP tool surface | M | 3 | 0.5 | 0.3 | 3 | 0.50 | **0.075** | **MAJOR → KILL** |
| 24 | CAND-14 | LLM Readiness Harness CI gate | Retrieval quality | L | 3 | 0.5 | 0.3 | 8 | 1.0 | 0.056 | NONE (parking) |
| 25 | CAND-24 | Operator runbook files (already shipped) | Ops / infra | XS | — | — | — | — | — | **0** | **MAJOR → KILL** |

Scoring notes:
- **Adj** column: `0.75` = MAJOR penalty per phase-prioritize rubric; `0.50` = BLOCKER penalty (CAND-16 has 2 independent blockers per challenger, effectively BLOCKER-class).
- Reach is bounded at 3 for all candidates because arXMCP's consumer is a single workstation operator + the multi-agent pipeline; no candidate is positioning-changing on arXMCP's substrate role.
- Confidence dial: 1.0 = 4+ briefs (CAND-1 only); 0.8 = 3 briefs (CAND-3, CAND-4, CAND-8); 0.5 = 2 briefs; 0.3 = 1 brief.

---

## 3. Top 10 in detail

### Rank 1 — CAND-1 — Ship Prometheus alert rules for corpus-integrity gauges

**Category:** Ops / infra
**Size:** XS (~30 LOC YAML)
**Evidence triangulation:** 4 briefs (adversary H1 ✓, comparative C3 ✓, oss-trends 2.6 ✓, research-frontier CAND-6 ✓)

**Synthesis catalog entry (verbatim):**

> Add 2–3 rules to `infra/prometheus/alerts.yml` operationalizing the m2/m3 gauges: (a) `abs(arxmcp_corpus_chunk_count_actual - arxmcp_corpus_chunk_count_marker) / clamp_min(marker, 1) > 0.05` (drift > tolerance), (b) `arxmcp_corpus_chunk_count_actual == -1 for 10m` (count_rows() failure sentinel), (c) optionally `arxmcp_corpus_unindexed_rows > 0 for 1h` (m3 tripwire). Without alert rules the dual-gauge pair is silent telemetry. The motivating ~100x drift would have paged within 60s.

**Challenger objections (MINOR):**

- **Axis 1 (overlap):** Rule (a) is redundant with the existing `ArXMCPDegradedMode` for the above-tolerance case — `DegradedState("chunk_count_diverged")` already fires that alert. Drop rule (a) or emit it as `severity: warning` only for sub-tolerance drift.
- **Axis 6 (doc-placement):** `runbook_url` should point either to `docs/ops/corpus-drift-runbook.md` (extends the pre-existing `docs/ops/` exception, which is technically a CLAUDE.md §1 violation) or to a `.claude/notes/` runbook. Make a conscious decision.

**Challenger v0 scope adjustment:** Ship rule (b) (`actual == -1 for 10m` — count_rows() failure sentinel; NOT covered by `ArXMCPDegradedMode`) and rule (c) (`unindexed_rows > 0 for 1h` — NOT covered). Fold a `corpus-drift-runbook.md` into this scope; absorb CAND-24's killed runbook idea here.

**RICE breakdown:** R=3 (operator consumer), I=3 (decisive — catches motivating-bug class within scrape interval), C=1.0 (4-brief triangulation; strongest signal in catalog), E=0.25 (XS — pure YAML). **RICE = 36.0**, no adjustment.

**Rank rationale:** This is the only candidate where the multipliers compound favorably — high Reach, high Impact, top Confidence, lowest Effort. It would have alerted on the motivating bug within 60s. The MINOR objection is real but cleanly addressable in the implementation brief.

---

### Rank 2 (tie) — CAND-3 — Write-Audit-Publish (WAP) post-write invariant in `ingest/store.py`

**Category:** Ingestion / parsing
**Size:** S (~30 LOC if redesigned)
**Evidence triangulation:** 3 briefs (research-frontier CAND-1+CAND-2, oss-trends 2.1+2.2+2.4, adversary indirectly via top theme)

**Synthesis catalog entry (verbatim):**

> Between `_create_indices()` and the marker write in `ingest/store.py::write_chunks`, add a post-write invariant: `if tbl.count_rows() != stats.total_rows_after_commit: raise RuntimeError(...)`. Block marker publication on a confirmed reconciliation. Modeled on Apache Iceberg's WAP pattern + Pandera's `check_output` DSL + GX's Checkpoint contract. The motivating ~100x bug class would have crashed the ingest run rather than producing a silent live cutover.

**Challenger objections (MINOR — gate sketch is a tautology):**

- **Axis 1 (tautology risk):** `ingest/store.py:938-942` already does `chunk_count = tbl.count_rows(); stats.total_rows_after_commit = chunk_count`. Comparing `count_rows()` against `stats.total_rows_after_commit` later is comparing `chunk_count` against `chunk_count` — always true.
- **Suggested redesign:** A meaningful WAP gate is a second `count_rows()` read AFTER `write_corpus_version_marker` returns, verifying `tbl.count_rows() == marker_chunk_count_just_written` (catches filesystem/serialization failures in the marker write itself). OR a caller-provided `expected_total` parameter passed into `write_chunks`. v0 = the post-marker-write variant.

**RICE breakdown:** R=3 (every ingest run), I=3 (decisive — prevents bad marker at the source), C=0.8 (3-brief), E=1 (S). **RICE = 7.2**, no adjustment.

**Rank rationale:** This is the only candidate that prevents the buggy marker from being persisted at all (CAND-1 detects it after the fact). Defense-in-depth with CAND-1. Tautology redesign is non-blocking but must be in the implementation brief.

---

### Rank 2 (tie) — CAND-8 — End-to-end multi-paper write→server→/readyz integration test

**Category:** Ops / infra
**Size:** S (~80 LOC test)
**Evidence triangulation:** 3 briefs (comparative C7 ✓, research-frontier CAND-3 indirectly, adversary M4 ✓)

**Synthesis catalog entry (verbatim):**

> A new `requires_full_corpus`-tagged or fixture-gated test in `tests/test_server_startup_integration.py` that: (a) writes a real LanceDB table via `write_chunks` with 3+ papers × 30 chunks each, (b) boots a temporary in-process FastAPI server against it, (c) hits `/readyz` and asserts `body["chunk_count"] == body["marker_chunk_count"]`, (d) optionally asserts `/metrics` exposes equal gauges. The motivating bug lived in the gap BETWEEN m1's write-path test (synthetic data) and m2's reconciliation test (mocked tables).

**Challenger objections:** NONE — clean candidate.

**RICE breakdown:** R=3 (CI surface protecting every future change), I=3 (decisive — closes the test-coverage seam the motivating bug lived in), C=0.8 (3-brief), E=1 (S). **RICE = 7.2**, no adjustment.

**Rank rationale:** Tied with CAND-3. Could ship together — CAND-3 implements the gate; CAND-8 verifies the gate works end-to-end and catches future regressions of the same class.

---

### Rank 4 — CAND-6 — BM25 index version cross-check vs LanceDB corpus version

**Category:** Ops / infra
**Size:** XS (~15 LOC + gauge + alert rule)
**Evidence triangulation:** 1 brief (adversary M1 ✓)

**Synthesis catalog entry (excerpt):**

> At `Resources.startup`, after loading the BM25 index, verify that the loaded index's path component `v<N>` matches `corpus_info.version`. Emit a structured WARN log on mismatch and set a new Gauge `arxmcp_bm25_index_version_mismatch`. A stale BM25 silently serves wrong retrieval.

**Challenger objections (MINOR):**
- **Axis 6 (gauge registry consistency):** Place the new gauge in `server/health.py` alongside the existing corpus-integrity gauges, NOT `server/observability/metrics.py` as the synthesis sketch said.

**RICE breakdown:** R=3, I=1 (parity), C=0.3 (1-brief), E=0.25 (XS). **RICE = 3.6**, no adjustment.

**Rank rationale:** Closes the second-largest dual-store integrity gap (after the corpus-version one already fixed). Trivial effort. Confidence is lower (1 brief) but the gap is concrete and the fix is mechanical.

---

### Rank 5 — CAND-4 — structlog migration + `capture_logs()`-assertable startup events

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 3 briefs (research-frontier CAND-3, oss-trends 2.1+2.7, adversary M3)

**Synthesis catalog entry (excerpt):**

> Migrate the `Resources.startup` log line at `server/resources.py:508-512` to use `extra={"event": "corpus_pinned", "corpus_version": …, "chunk_count": …, "paper_count": …}`. Add tests asserting `record.chunk_count == 10298`. The motivating bug's "wrong values in startup logs went unnoticed" half is closed by making startup log emissions test-assertable.

**Challenger objections:** NONE.

**RICE breakdown:** R=3, I=1 (parity), C=0.8 (3-brief), E=1. **RICE = 2.4**.

**Rank rationale:** Sound and high-triangulation but smaller impact than the top 3 because it's a regression-guard, not a bug-prevention primitive. Pairs naturally with CAND-8 (integration test can assert the structured log fields).

---

### Rank 6-8 — XS candidates with NONE objections

**CAND-10 (paper_id_min/max), CAND-15 (chunk_id liveness), CAND-19 (`make audit` utility)** — all RICE 1.8, XS, no objections. Low individual signal (1 brief each) but XS effort makes them attractive bundle candidates alongside the top 3.

---

### Rank 9 — CAND-20 — mcpdiff `.mcpc.json` contract snapshot

**Category:** MCP tool surface
**Size:** XS
**Evidence triangulation:** 1 brief (multi-agent Candidate 1)

**Challenger objection (MINOR):** Repo-root `.mcpc.json` violates CLAUDE.md §1; write to `.claude/docs/tools-snapshot.json` instead.

**RICE:** 1.8, no adjustment.

**Rank rationale:** Cheap dev-tooling complement to `EXPECTED_TOOL_SCHEMA_SHA256` (gives reviewers a description-level diff on PR). Could ship as part of a /roadmap "cleanup" milestone alongside other XS candidates.

---

### Rank 10 — CAND-21 — `infra/corpus-checks.yml` versioned threshold config

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (oss-trends 2.8)

**Synthesis catalog entry (excerpt):**

> A YAML file holding threshold values for corpus-integrity checks. When corpus grows 10x, one config edit updates all checks. Borrows Soda Core's `checks.yml` DSL pattern (native impl, not import).

**Challenger objection:** NONE.

**RICE:** 1.8.

**Rank rationale:** Pairs naturally with CAND-3 (gate reads thresholds from the YAML) and CAND-1 (alert rule expression uses the same thresholds).

---

## 4. Recommended next steps

### Now-lane first pick for `/roadmap`

**Bundle: CAND-1 + CAND-3 + CAND-8 + CAND-21 (a `corpus-integrity-completion` epic).**

Rationale:
- All four are write/read symmetry on the same gauge pair (read-time alert, write-time gate, integration-test verify, threshold-config centralization).
- Together they close the motivating-bug class at both boundaries with regression test coverage.
- Total effort: XS + S + S + XS ≈ 4 weeks. Fits a single roadmap epic.
- Confidence: high (CAND-1 strongest; CAND-3 and CAND-8 triangulated 3 ways).

### Spike-lane candidates

**Spike S-1: CAND-3 gate redesign.** The implementation brief MUST address the tautology issue (`stats.total_rows_after_commit = tbl.count_rows()` at `ingest/store.py:942` means the synthesis's sketched gate is identity). Spike before milestone: ½ day to pick between (a) post-marker `count_rows()` verifying the marker file, or (b) caller-provided `expected_total` parameter, or (c) some other shape.

**Spike S-2: CAND-22 LanceDB `list_indices()` API.** Open spike from prior scout — verify `tbl.list_indices()` behavior in lancedb 0.30.x before reframing `CORPUS_UNINDEXED_ROWS` per-index. ½ day. May spawn an XS milestone or confirm no work needed.

### Parking lot (defer to next scout)

- **CAND-16** (`get_corpus_delta` MCP tool) — KILL per challenger; revisit only if (a) a pipeline consumer is documented AND (b) `corpus_version` field is added to `WriteStats` first as a standalone prerequisite.
- **CAND-24** (operator runbook files) — KILL; all 4 already shipped. Fold any remaining corpus-drift runbook into CAND-1's scope.
- **CAND-25** Makefile part — already shipped; only the README one-liner remains. Reduce to docs nit; bundle into the next docs milestone.
- **CAND-14** (LLM Readiness Harness) — L effort; single-workstation use case doesn't justify cost.
- **CAND-23** (LanceDB v0.33 manifest API) — experimental API; defer until v1.0 stable.
- **CAND-11** (AVH historical bounds) — bootstrapping problem (needs ≥7 history points; monthly ingest = 7 months); defer until ingest cadence increases.
- **CAND-5** (mid-session live `count_rows()`) — MAJOR per challenger; revisit only if CAND-1's alert rule misses a documented mid-session scenario.
- **CAND-12** (Evidently-style drift), **CAND-13** (ReproRAG), **CAND-2** (daily report sections) — sound but ranked below the top bundle; bundle into a "Phase 2 ops uplift" epic.

---

## 5. Honest limitations

- **Scouts had a 15-minute budget each.** Some categories may be under-explored; the multi-agent scout's unique surfacing of CAND-16/17/18 is high-signal but uncorroborated by the other 4 scouts (1-brief triangulation).
- **The prior scout run (2026-05-28) shaped this run's landscape heavily.** Adversary brief in particular forwarded 2 candidates (CAND-24, CAND-25) that pre-date m1-m3/e2-e3 milestone landings — synthesis did not verify against `git log`. Challenger caught both. Future scouts should pre-scan `git log --since="<prior-scout-date>"` for milestone landings.
- **Triangulation strength varies sharply.** CAND-1 has 4-way triangulation (RICE C=1.0); 14 candidates have 1-brief signal (C=0.3). The top 3 are robust; the long tail is noisier.
- **Effort estimates are T-shirts; ±50% accuracy.** CAND-3's "S" depends on the gate redesign; could be XS if (a) is picked or M if (c) is picked.
- **Challenger evaluated against current architecture locks.** If CLAUDE.md §4.7 conventions evolve (e.g. structlog adopted broadly), MINOR objections on CAND-4 and CAND-17 may shift.
- **Pipeline-consumer assumptions for agent-facing candidates are unverified.** CAND-16, CAND-17, CAND-18 all assume a specific pipeline shape; per CLAUDE.md §2 the sketcher → autoformalizer → tactician → fixer pipeline is documented but the agent-side consumption of corpus-delta signals is not detailed.
- **CAND-19's DuckDB assumption is wrong** (challenger caught — DuckDB is NOT in `pyproject.toml`). Scope adjusts to stdlib JSON iteration.

---

## 6. Cross-reference index

| CAND id | Adversary | Comparative | Multi-agent | OSS-trends | Research-frontier |
|---|---|---|---|---|---|
| CAND-1 | H1 ✓ | C3 ✓ | — | 2.6 ✓ | CAND-6 (indirect) ✓ |
| CAND-2 | L1 ✓ | C2 + C9 ✓ | — | — | — |
| CAND-3 | (theme indirect) | — | — | 2.1 + 2.2 + 2.4 ✓ | CAND-1 + CAND-2 ✓ |
| CAND-4 | M3 ✓ | — | — | 2.1 + 2.7 ✓ | CAND-3 ✓ |
| CAND-5 | H2 ✓ | — | Cand. 3 (ind.) | — | — |
| CAND-6 | M1 ✓ | — | — | — | — |
| CAND-7 | M2 ✓ | — | — | — | — |
| CAND-8 | M4 ✓ | C7 ✓ | — | — | CAND-3 (ind.) ✓ |
| CAND-9 | — | C5 ✓ | — | — | — |
| CAND-10 | — | C6 ✓ | — | — | — |
| CAND-11 | — | — | — | — | CAND-7 ✓ |
| CAND-12 | — | — | Cand. 6 (ind.) | 2.3 ✓ | CAND-4 ✓ |
| CAND-13 | — | — | — | — | CAND-5 ✓ |
| CAND-14 | — | — | — | — | CAND-6 ✓ |
| CAND-15 | — | — | — | — | CAND-8 ✓ |
| CAND-16 | — | — | Cand. 2 + 4 ✓ | — | — |
| CAND-17 | — | — | Cand. 3 ✓ | — | — |
| CAND-18 | — | — | Cand. 5 ✓ | — | — |
| CAND-19 | — | — | Cand. 7 ✓ | — | — |
| CAND-20 | — | — | Cand. 1 ✓ | — | — |
| CAND-21 | — | — | — | 2.8 ✓ | — |
| CAND-22 | — | C4 ✓ | — | — | — |
| CAND-23 | — | — | — | 2.5 ✓ | — |
| CAND-24 | L2 ✓ (stale baseline; killed) | — | — | — | — |
| CAND-25 | L3 ✓ (Makefile already shipped) | — | — | — | — |

---

## Handoff offer

The top-4 candidates above are ready to feed the `roadmap` skill as a source brief (RICE-light scores of 36.0, 7.2, 7.2, 3.6 all clear the ≥3.0 handoff threshold). To materialize as a roadmap with milestones:

```text
/roadmap corpus-integrity-completion --brief "$(head -200 .claude/notes/capability-scouts/corpus-integrity-observability/artifacts/final-report.md)"
```

The roadmap skill will refine → decompose → sequence → materialize from this report, and its milestones (`corpus-integrity-completion-mN`) hand off to `/milestone-pipeline` for execution.

(Note: capability-scout NEVER auto-invokes `/roadmap`. Always offer-and-wait. The user picks the cut.)
