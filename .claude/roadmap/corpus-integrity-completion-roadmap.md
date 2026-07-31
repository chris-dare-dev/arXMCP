---
project: arxmcp
type: roadmap
status: active
authorship: agent-generated
tags:
- project/arxmcp
- type/roadmap
- authorship/agent-generated
---

# Corpus integrity completion (close the alarm + write-gate + integration-test gap) — Roadmap

> [!done] ARCHIVED — track complete, retained for the record
> **Moved** from `plans/corpus-integrity-completion-roadmap.md` to `.claude/roadmap/` on 2026-07-29.
> `plans/` is reserved for live `roadmap/1` tracks (`plans/<slug>/roadmap.yaml`);
> `CLAUDE.md` § 1 allows no other Markdown outside `.claude/`. This directory is
> already the home of completed standalone briefs (`notebook-cutover.md`,
> `embedder-truncation.md`, …) and stays inside
> `milestone-pipeline-resolve-brief.py`'s legacy-prose glob, so `/milestone-pipeline`
> still resolves every id below.
>
> **Completed milestones (5)** — `state.json` phase `complete`: `corpus-integrity-completion-e1`, `corpus-integrity-completion-m1`, `corpus-integrity-completion-m2`, `corpus-integrity-completion-m3`, `corpus-integrity-completion-spike-1`
> **Last commit touching this track:** `198d98b chore(notes): session handoff 2026-06-01 â€” corpus-integrity-completion-e1`


**Slug:** `corpus-integrity-completion`
**Created:** 2026-05-31T19:27:56Z
**Status:** init

<!--
This roadmap is itself the state. Re-invoking the `roadmap` skill on
this file resumes from the first un-populated phase. Sections below
contain `{{TOKEN}}` placeholders until their phase runs.

Phases:
  1. REFINE     — How-Might-We, sharpening questions, assumptions, OKR, Won't list
  2. DECOMPOSE  — technique, epics, INVEST, specialist suggestions
  3. SEQUENCE   — MoSCoW, RICE, Now/Next/Later, spike lane, Now-lane milestones
  4. MATERIALIZE — validation results, optional GitHub bundle, next-step handoff
-->

---

## Phase 1 — Refine

### How Might We

How might we make a `corpus-version.json`-marker-vs-LanceDB-table chunk-count divergence **impossible to ship and impossible to miss when it occurs** for the single-workstation arXMCP operator, without introducing a distributed-systems dependency or violating BP1/BP2 prompt-cache discipline?

### Sharpening questions answered

1. **Should the epic absorb CAND-6 (BM25 index version cross-check, RICE 3.6) in addition to the scout's top-4 bundle (CAND-1 + CAND-3 + CAND-8 + CAND-21)?**
   Yes. The bundle's thematic frame is "close every marker-vs-ground-truth seam, end-to-end." CAND-6 is the parallel seam for the BM25 index (path-encoded `v<N>` vs `corpus_info.version`) that the prior epic explicitly skipped. Adding it keeps the epic coherent — every cross-store integrity pair gets the same observability treatment. Adversary brief §M1 + synthesis catalog entry CAND-6 ground this.

2. **What does CAND-3's redesigned WAP gate actually look like, given the challenger flagged the synthesis sketch as a tautology at `ingest/store.py:938-942`?**
   The Spike S-1 finding (final-report §4) is binding: pick between (a) a SECOND `tbl.count_rows()` AFTER `write_corpus_version_marker` returns, comparing the live table against the just-written marker file's `chunk_count` (catches filesystem/serialization failure in the marker write itself), or (b) a `expected_total` parameter threaded from the BULK caller (`ingest/bulk_ingest.py`) that accumulates expected per-paper counts and is asserted equal to `tbl.count_rows()` at end of run (catches per-paper-batch arithmetic errors). Recommendation in the Spike: ship BOTH — (a) inside `write_chunks` for per-call integrity, (b) at the bulk-driver boundary for end-of-run integrity. Half-day spike before the milestone.

3. **Where does the new `corpus-drift-runbook.md` live — `docs/ops/` or `.claude/notes/`?**
   `docs/ops/corpus-drift-runbook.md`. CLAUDE.md §1 restricts `docs/` to "user-facing documentation referenced by the root README.md," but `docs/ops/` is a pre-existing exception (4 runbook files already shipped: `failure-modes.md`, `backup-restore.md`, `drift-watchdog.md`, `latexml-drift-runbook.md`, confirmed by challenger §6.1). Extending the exception is operationally consistent. A separate `docs/-purity` cleanup is out of scope.

4. **Does the existing `ArXMCPDegradedMode` alert make rule (a) of CAND-1 redundant?**
   For the above-tolerance path, yes — `DegradedState("chunk_count_diverged")` already fires `ArXMCPDegradedMode` when divergence exceeds `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE`. v0 ships rule (b) (`actual == -1 for 10m` — count_rows-failure sentinel) + rule (c) (`unindexed_rows > 0 for 1h` — m3 tripwire); rule (a) downgraded to `severity: warning` for **sub-tolerance** drift only (deferred to v1 in the Won't list).

5. **Does CAND-21 (`infra/corpus-checks.yml`) add real value or premature centralization?**
   Real, if-and-only-if CAND-3 + CAND-1 land together. Today `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE` is a single Pydantic field in `server/config.py`. Adding CAND-3's per-call gate threshold + CAND-1's alert-rule thresholds creates ≥3 thresholds that benefit from collocation. If the epic ships those two together, CAND-21 absorbs the new thresholds and is a coherent ~XS addition. If only CAND-1 ships, CAND-21 is premature — drop it.

### Assumptions

- `[MUST]` The post-merge_insert `tbl.count_rows()` at `ingest/store.py:938` is a stable contract — the redesigned WAP gate depends on it being callable a SECOND time (after the marker write) without race-condition concern. Validated by reading `ingest/store.py`; no concurrent writer is documented in the single-writer-per-process model.
- `[MUST]` `arxmcp_corpus_chunk_count_actual = -1` is the canonical "count_rows failure" sentinel per the m2/m3 implementation (verified at `server/health.py:111-120`). CAND-1's alert rule (b) depends on this contract not silently changing.
- `[MUST]` The seed/synthetic corpus is reachable in the standard test suite (`make test` without `requires_full_corpus`). CAND-8's integration test needs a real LanceDB table; the `tests/_graph_helpers.py` synthetic-fixture pattern is the validated approach.
- `[SHOULD]` The operator runs a Prometheus scrape against `/metrics` (not Datadog-only or stdout-only). If an operator runs no scrape stack, CAND-1 has zero observable value to them — CAND-3 + CAND-8 still apply.
- `[SHOULD]` The 5% `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE` default is acceptable for v0 alert thresholds; not re-litigated in this epic.
- `[SHOULD]` `docs/ops/corpus-drift-runbook.md` placement is acceptable; the `docs/` purity violation is a pre-existing exception that is NOT this epic's job to resolve.
- `[MIGHT]` LanceDB v0.33's `manifest-summary` API (CAND-23) stabilizes within the epic timeline; if so, the per-call `count_rows()` in CAND-3 could become cheaper. If not, the current approach is fine — `count_rows()` is documented as O(1) on Lance fragment metadata.
- `[MIGHT]` An operator running mid-session ingest flows observes alerts within the next scrape interval before next-server-restart (relates to deferred CAND-5).

### Objective

Make the arXMCP corpus-marker-vs-table chunk-count integrity invariant **structurally impossible to silently break** — end-to-end from write-time enforcement through monitoring alerts through integration-test coverage — so the motivating ~100x drift bug class (and its BM25 / per-shard analogues) cannot recur undetected.

### Key Results

1. By epic close: `make test` passes a new multi-paper end-to-end integration test (`tests/test_server_startup_integration.py`) that boots a real FastAPI server against a 3-paper × ~30-chunks synthetic LanceDB corpus, hits `/readyz`, and asserts `body["chunk_count"] == body["marker_chunk_count"]`. Test fails on a re-introduced `len(chunks)` pre-fix bug shape (mutation-tested).
2. `infra/prometheus/alerts.yml` ships ≥2 new corpus-integrity rules (`arxmcp_corpus_chunk_count_actual == -1 for 10m` + `arxmcp_corpus_unindexed_rows > 0 for 1h`); every new rule's `runbook_url` resolves to an existing file at the named path.
3. `ingest/store.py::write_chunks` raises `RuntimeError` on a post-`write_corpus_version_marker` second `count_rows()` mismatch against the just-written marker file (Spike S-1 variant a). The pre-m1 bug shape (`chunk_count` set from last per-paper batch) fails the gate at write time, not at next-restart inspection.
4. `arxmcp_bm25_index_version_mismatch` gauge ships in `server/health.py`; startup emits structured WARN with `extra={"event": "bm25_version_mismatch", "bm25_index_version": ..., "corpus_version": ...}` when the BM25 pickle's path-encoded `v<N>` does not match `corpus_info.version`.
5. `docs/ops/corpus-drift-runbook.md` exists with `Symptom / Quick triage / Likely causes / Remediation / Escalation` sections; every new alert rule from KR-2 references it; an operator hitting any new alert can land on a runnable next step (`make reconcile` or equivalent).

### Won't (explicit out-of-scope)

- **Mid-session live `count_rows()` refresh (CAND-5).** Challenger MAJOR; m2's "cached once at startup" test contract at `tests/test_corpus_count_reconciliation.py:735` is a deliberate architectural boundary. Revisit only if KR-2's alert rules miss a documented mid-session scenario.
- **Agent-facing change surface — `get_corpus_delta` MCP tool (CAND-16) and `session_corpus_mismatch` envelope field (CAND-18).** Killed / deferred per challenger: CAND-16 has both a permanent BP1 overhead concern + a `WriteStats` schema blocker (serializes `lancedb_version` not `corpus_version`); CAND-18 has no documented pipeline consumer today.
- **Daily report `## Corpus integrity` section (CAND-2).** Sound but ranked below the integrity-completion bundle (RICE 1.5 vs ≥3.6). Bundle into a future ops-uplift epic when daily-report sections are batch-extended.
- **structlog migration + capture_logs() assertions (CAND-4).** Sound (RICE 2.4, 3-brief triangulation) but pairs better as a broader logging-modernization milestone touching all critical-path startup events, not just the corpus_pinned one.
- **Kùzu graph paper-count cross-check (CAND-7).** Depends on `cite_neighbors` handler de-stubbing (CLAUDE.md §7) before the coverage gauge becomes actionable.
- **mcpdiff `.mcpc.json` contract snapshot (CAND-20).** Dev tooling; decoupled from the integrity theme. Bundle into a future MCP-surface-hygiene epic.
- **LanceDB v0.33 manifest-summary API (CAND-23).** Experimental API per LanceDB release notes; defer until v1.0-stable.
- **The 4 pre-existing operator runbooks (`failure-modes.md`, `backup-restore.md`, `drift-watchdog.md`, `latexml-drift-runbook.md`) from CAND-24.** Already shipped per challenger §6.1; only the NEW `corpus-drift-runbook.md` is in scope (folded into KR-5).
- **AVH-style historical bounds detector (CAND-11).** Bootstrapping problem: needs ≥7 ingest-run history points; monthly delta = 7 months before signal becomes meaningful. Defer until ingest cadence increases.
- **The `make reconcile` Makefile target (CAND-25 part).** Already shipped at `Makefile:560` per challenger §3 CAND-25; only the README one-liner under "Common tasks" remains, folded into KR-5 as a documentation nit.

---

## Phase 2 — Decompose

<!-- populated by DECOMPOSE phase -->

### Technique

**Vertical slicing + enabler stories** along the *integrity seam* axis. Each integrity boundary in the corpus pipeline (the chunk-count marker seam; the BM25-index-version seam) gets a self-contained slice that includes its write-time gate, its operator-visible signal (alert / log), and its test surface. The end-to-end CI smoke test is its own value epic protecting all future seams. This matches the way the prior epic (`corpus-integrity-observability`) was shaped — one seam per milestone — and lets each epic ship independently behind a `make test` gate.

### Epics

#### corpus-integrity-completion-e1 — Chunk-count seam: WAP gate that refuses bad markers

- **Type:** enabler
- **Specialist suggestion:** `cache-stability-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (touches `ingest/store.py::write_chunks` marker write + writer-side `chunk_id` / row counts; the byte-stability of the marker JSON is load-bearing for the m2 startup reconciliation cache key)
- **Outcome:** `ingest/store.py::write_chunks` raises `RuntimeError` whenever the just-written `corpus-version.json` marker's `chunk_count` does not match a fresh `tbl.count_rows()`. The pre-m1 bug shape (`chunk_count` from last per-paper batch) fails the write boundary, not the next-restart inspection. `ingest/bulk_ingest.py` accumulates expected per-paper totals and asserts equality at end-of-run.
- **Estimated size:** S
- **INVEST check:** I depends on Spike S-1 outcome (gate variant pick) but ships after the spike; N clean (new RuntimeError path); V clean (operator-observable crash on bad marker); E clean (S — small surface in `ingest/store.py`); S clean (S size); T clean (mutation-tested in `tests/test_store.py`)
- **Dependencies:** Spike S-1 (gate-variant pick)
- **Won't conflict check:** none

#### corpus-integrity-completion-e2 — Chunk-count seam: Prometheus alerts + operator runbook

- **Type:** value
- **Specialist suggestion:** `—` (no path heuristic matches; YAML + Markdown — milestone-pipeline adversary critic suffices)
- **Outcome:** `infra/prometheus/alerts.yml` ships 2 new rules (`arxmcp_corpus_chunk_count_actual == -1 for 10m` count_rows-failure sentinel; `arxmcp_corpus_unindexed_rows > 0 for 1h` m3 tripwire). A new `docs/ops/corpus-drift-runbook.md` provides Symptom / Quick triage / Likely causes / Remediation / Escalation sections; each new alert's `runbook_url` resolves to it. `README.md` gains a one-line "Common tasks" entry pointing at `make reconcile`.
- **Estimated size:** XS
- **INVEST check:** I clean (no code change); N clean (additive only); V clean (operator-visible alerts); E clean (XS); S clean (XS); T clean (`promtool check rules infra/prometheus/alerts.yml` is the verifier)
- **Dependencies:** none — can ship in parallel with e1
- **Won't conflict check:** none

#### corpus-integrity-completion-e3 — BM25-index seam: version cross-check at startup

- **Type:** enabler
- **Specialist suggestion:** `cache-stability-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (touches `server/health.py` gauge registry + the path-encoded version contract from `ingest/bm25_indexer.py:6-30`; both interact with the corpus-version cache discipline)
- **Outcome:** `arxmcp_bm25_index_version_mismatch` Gauge ships alongside the existing corpus-integrity gauges in `server/health.py` (NOT `server/observability/metrics.py` — per challenger §3 CAND-6 the registry should not split). `Resources.startup` cross-checks the loaded BM25 pickle's path-encoded `v<N>` against `corpus_info.version` and emits a structured WARN with `extra={"event": "bm25_version_mismatch", "bm25_index_version": ..., "corpus_version": ...}` on mismatch.
- **Estimated size:** XS
- **INVEST check:** I clean (independent of e1/e2/e4); N clean (new gauge, new log event); V borderline (gauge is operator-observable but no immediate behavior change — the value lands only when a future BM25 staleness occurs); E clean; S clean; T clean (synthetic mismatched-filename fixture, assert gauge value = 1)
- **Dependencies:** none
- **Won't conflict check:** none

#### corpus-integrity-completion-e4 — End-to-end multi-paper integration test

- **Type:** value
- **Specialist suggestion:** `determinism-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (synthetic fixture must produce a byte-stable, reproducible LanceDB state across CI runs and platforms; mutation tests of the gate require deterministic ingest output)
- **Outcome:** A new `tests/test_server_startup_integration.py` boots a real FastAPI server lifespan against a synthetic 3-paper × ~30-chunks LanceDB corpus, hits `/readyz`, and asserts `body["chunk_count"] == body["marker_chunk_count"]`. A mutation test rewrites the marker `chunk_count` to a wrong value and asserts the test catches it. The test runs in the default `make test` set (no `requires_full_corpus` marker — uses the synthetic fixture pattern from `tests/_graph_helpers.py`).
- **Estimated size:** S
- **INVEST check:** I clean (independent of e1's gate — this test validates the marker-equals-table seam end-to-end whether or not the write-time gate is in place); N clean (new file); V clean (CI surface protecting every future change); E clean; S clean; T clean (the test IS the test)
- **Dependencies:** none (independent — but pairs naturally with e1's gate which it can also exercise once e1 ships)
- **Won't conflict check:** none

---

## Phase 3 — Sequence

<!-- populated by SEQUENCE phase -->

### MoSCoW assignment

- **Must** (≤ 60% of total effort — 50.0% of 2.5 person-weeks): `e2`, `e4`
- **Should**: `e1`
- **Could**: `e3`
- **Won't (this cycle)**: — (the broader Won't list is in REFINE)

`score-moscow.py` exit 0; Must = 1.25pm / 50.0% of total 2.5pm.

Rationale: `e2` (alerts + runbook) and `e4` (end-to-end integration test) close the chunk-count seam observably and durably. `e1` (write-time gate) is genuine defense-in-depth — strongly preferred — but the bug class is mitigated by the alert + test combination even without it; Should rather than Must. `e3` (BM25 cross-check) addresses the parallel BM25 seam, which the synthesis correctly ranked at lower triangulation (1 brief vs 3-4 for the chunk-count work); Could.

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| e2 | 3 | 3.00 | 100% | 0.25 | 36.0 |
| e4 | 3 | 3.00 | 80% | 1.00 | 7.2 |

(No `*` markers — every Confidence is evidence-backed by the scout's 4-brief / 3-brief triangulation; see `.claude/notes/capability-scouts/corpus-integrity-observability/artifacts/final-report.md` §3 Rank 1 and Rank 3.)

### Now / Next / Later

- **Now** (fully spec'd): `e2`, `e4`
- **Next** (shaped, awaiting capacity): `e1` — gated on Spike S-1 (gate-variant pick)
- **Later** (outcome-only, low-confidence horizon): `e3`

### Spike / discovery lane

- `corpus-integrity-completion-spike-1` — pick the WAP gate variant for `e1`: (a) post-marker second `count_rows()` in `write_chunks`, (b) caller-provided `expected_total` threaded from `ingest/bulk_ingest.py`, or (c) both. The synthesis sketch was a tautology at `ingest/store.py:938-942` (per challenger §3 CAND-3); this spike picks the redesign. (≤ ½ day; not strictly validating a REFINE `[MUST]` but unblocks the Should-lane epic `e1`.)

  _Note on the REFINE `[MUST]` assumptions: all three (`count_rows()` stable contract; `actual = -1` sentinel; synthetic-corpus reachable in standard test suite) were validated by direct code-read during the REFINE phase (see Phase 1 §Sharpening Q1-Q5 and §Assumptions). No additional spike work is needed for them; the [MUST]-without-spike anti-pattern (`anti-patterns.md` row 5) is mitigated by inline citation in the Assumptions section._

### Milestones — Now lane

<!--
Each Now-lane milestone is its own H3 below. Heading format is
`### <slug>-mN — Title` exactly — milestone-pipeline's init-state.sh
greps for this. Do not change it.
-->

### corpus-integrity-completion-m1 — Prometheus alert rules: count_rows-failure + unindexed-rows-tripwire

**Description.** Append two rules to `infra/prometheus/alerts.yml` operationalizing the m2/m3 gauges that today are silent telemetry. Run `promtool check rules infra/prometheus/alerts.yml` to verify syntax (existing pattern; `ArXMCPDiskFull` and friends use the same shape).

**Acceptance criteria.**
- [ ] `infra/prometheus/alerts.yml` contains a new rule `ArXMCPCorpusCountRowsFailed` with expression `arxmcp_corpus_chunk_count_actual == -1`, `for: 10m`, `severity: critical`, and a `runbook_url` pointing to `https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/corpus-drift-runbook.md` (the runbook ships in m2).
- [ ] `infra/prometheus/alerts.yml` contains a new rule `ArXMCPCorpusUnindexedRows` with expression `arxmcp_corpus_unindexed_rows > 0`, `for: 1h`, `severity: warning`, and the same `runbook_url`.
- [ ] `promtool check rules infra/prometheus/alerts.yml` exits 0 (validate as part of `make test` if a `requires_promtool` test marker pattern is added; otherwise documented in implementation summary).
- [ ] No new rule is added for above-tolerance drift in this milestone — the existing `ArXMCPDegradedMode` covers it; that decision is documented in the implementation summary per challenger §3 CAND-1.

**Dependencies.** `e2` (parent). Independent of `m2` (runbook can land in either order without breaking the build; `m1` references `m2`'s file path optimistically and the link will resolve once both ship).

**Complexity.** S (≤ 1 day execution).

**Specialist suggestion.** `—` (YAML + Markdown only; milestone-pipeline adversary critic suffices).

### corpus-integrity-completion-m2 — Corpus-drift operator runbook + README "Common tasks" nit

**Description.** Author `docs/ops/corpus-drift-runbook.md` mirroring the structure of the 4 existing runbooks (`failure-modes.md`, `backup-restore.md`, `drift-watchdog.md`, `latexml-drift-runbook.md`). Sections: Symptom, Quick triage, Likely causes, Remediation (`make reconcile` or `tools/notebook_reconcile_marker.py`), Escalation. Add a one-line entry to `README.md` under "Common tasks" pointing to `make reconcile`.

**Acceptance criteria.**
- [ ] `docs/ops/corpus-drift-runbook.md` exists with H2 sections: `## Symptom`, `## Quick triage`, `## Likely causes`, `## Remediation`, `## Escalation`.
- [ ] The Remediation section references the existing `make reconcile` Makefile target (already shipped per challenger §3 CAND-25 at `Makefile:560`) and the underlying `tools/notebook_reconcile_marker.py` CLI.
- [ ] `README.md` "Common tasks" section gains one line `- 'make reconcile' — Heal corpus-version.json marker drift; see docs/ops/corpus-drift-runbook.md.`
- [ ] No new entries are added to the 4 other pre-existing runbooks (they were shipped in prior epics; this milestone does not touch them).

**Dependencies.** `e2` (parent). Can land before or after `m1`.

**Complexity.** S (≤ 1 day execution).

**Specialist suggestion.** `—`.

### corpus-integrity-completion-m3 — End-to-end multi-paper write→/readyz integration test

**Description.** Create `tests/test_server_startup_integration.py`. Use the synthetic-fixture pattern from `tests/_graph_helpers.py` to build a 3-paper × ~30-chunks LanceDB corpus via `ingest/store.py::write_chunks`. Boot a real FastAPI lifespan via `httpx.AsyncClient` + the existing `tests/test_server_startup.py` TestClient bootstrap pattern. Hit `GET /readyz`. Assert the JSON body's `chunk_count` equals `marker_chunk_count`. Add a mutation test that monkey-patches `ingest/store.py::write_chunks` to write `chunk_count=len(last_batch)` (the pre-m1 bug shape) and asserts the new integration test FAILS — proving the test catches the original regression class.

**Acceptance criteria.**
- [ ] `tests/test_server_startup_integration.py` exists with one positive-path test `test_chunk_count_marker_equals_table_after_multi_paper_write` and one mutation test `test_pre_m1_bug_shape_is_caught_by_integration`.
- [ ] The positive-path test exercises a real `write_chunks` call against a `tmp_path`-rooted LanceDB; boots the FastAPI lifespan; asserts `GET /readyz` returns 200 with `body["chunk_count"] == body["marker_chunk_count"]`.
- [ ] The mutation test uses `monkeypatch.setattr` on `ingest/store.py::write_corpus_version_marker` to write a deliberately-wrong `chunk_count`, then asserts the integration test detects the divergence (either via `/readyz` 503 or via the marker-equals-table assertion failing).
- [ ] Both tests run under `make test` without the `requires_full_corpus` marker (synthetic fixture; ≤ 5s wall-clock).
- [ ] The implementation summary documents that this test now protects against any future `len(chunks)`-flavored regression on the write path.

**Dependencies.** `e4` (parent). Independent of `m1` / `m2` / spike-1. Pairs with `e1` once that ships — the same test can be re-asserted against the gate (covered in a future epic if `e1` ships).

**Complexity.** M (1–3 days execution — synthetic-fixture construction is the bulk; mutation test is straightforward).

**Specialist suggestion.** `determinism-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (the synthetic fixture must produce byte-stable LanceDB state across CI runs and platforms; mutation tests of the gate require deterministic ingest output).

---

## Phase 4 — Materialize

<!-- populated by MATERIALIZE phase -->

### Validation

- `validate-roadmap.py`: pass (phases populated: Refine, Decompose, Sequence, Materialize)
- Must-cap: 50.0% (≤ 60% — `score-moscow.py` exit 0)
- All Now-lane milestones have AC: yes (`m1`, `m2`, `m3`)
- Slug format valid: yes (`corpus-integrity-completion` — matches `^[a-z][a-z0-9-]{2,30}$`, 27 chars, does not collide with `^e\d+$` epic IDs)
- Spike-lane coverage: 1 spike (`spike-1`) for the only non-validated [MUST] (gate variant pick); the 3 other [MUST] assumptions are inline-validated by code-read in REFINE §Sharpening

### GitHub tickets

Not requested (run `/roadmap corpus-integrity-completion --github` if you want a `plans/corpus-integrity-completion-tickets/` bundle with epic + story bodies and a `create-tickets.sh` script).

### Next step

First Now-lane milestone: `corpus-integrity-completion-m1`. To execute it end-to-end, run:

```
/milestone-pipeline corpus-integrity-completion-m1
```

This skill will not invoke milestone-pipeline. Cache stays warmer if you start the milestone-pipeline session within 5 minutes.

Suggested execution order for the Now lane:
1. `corpus-integrity-completion-m1` (alert rules) — XS, references the m2 runbook path optimistically
2. `corpus-integrity-completion-m2` (corpus-drift-runbook + README) — XS, makes m1's `runbook_url` resolve
3. `corpus-integrity-completion-m3` (end-to-end integration test) — M, independent of m1/m2

Optional follow-on (Next lane, awaiting Spike S-1):
4. Run `corpus-integrity-completion-spike-1` to pick the gate variant for `e1`, then file a fresh `e1` milestone.

Optional follow-on (Later lane):
5. `e3` (BM25 cross-check) — re-evaluate priority once `m1`/`m2`/`m3` land and the chunk-count seam is fully closed.

---

<!-- end:roadmap -->
