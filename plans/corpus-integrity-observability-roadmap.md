# Corpus-integrity observability — Roadmap

**Slug:** `corpus-integrity-observability`
**Created:** 2026-05-28T20:30:08Z
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

How might we make a persisted-metadata-vs-ground-truth divergence (and the wrong
values it puts in startup logs and reports) impossible to ship silently — for
arXMCP's operators and its sketcher → autoformalizer → tactician → fixer
consumer — without adding new heavy infrastructure or touching the BP1 /
tool-schema cache pins?

### Sharpening questions answered

1. **What is the failure, precisely?** `ingest/store.py::write_chunks` (lines
   900-908) writes `corpus-version.json` with `chunk_count=len(chunks)` and
   `paper_count=len({c.paper_id for c in chunks})` from the in-flight per-paper
   batch; `bulk_ingest.py` + `re_embed.py` call `write_chunks` once per paper,
   so the final marker records only the LAST paper's counts (live: 106 vs 10,298
   real rows; `paper_count=1` for a 53-paper notebook). Found by manual
   inspection during the notebook-cutover-m1 live cutover.
2. **Retrieval correctness or only observability?** Only observability/reporting.
   Retrieval and the Tier-1 cache key use `corpus_version` (correct, = the
   post-index `tbl.version`); no correctness path reads `chunk_count`/`paper_count`
   (readers are `server/resources.py:341-342` startup log + `server/corpus.py`
   `to_dict` only — adversary H1 + grep confirm zero correctness consumers).
3. **Where should the guard live?** All four layers, in DAG order: the write-time
   fix (root cause) → a startup reconciliation invariant + a `/metrics` gauge
   pair (defense-in-depth, alertable) → a regression test (permanent guard) →
   a daily-report row (human cadence). Per capability-scout
   `2026q2-observability-reporting`'s final report (5-brief triangulation).
4. **What must NOT change?** `EXPECTED_TOOL_SCHEMA_SHA256` /
   `EXPECTED_BP1_SHA256` (no new/changed MCP tool); local-first single-workstation
   (no new heavy infra, no non-loopback surface); `count_rows()` must be
   startup-cached, never recomputed per `/metrics` scrape.
5. **Is the fix already in flight?** Yes — the write-time fix is tracked as
   in-session task #26. This roadmap supplies the precise mechanism
   (`tbl.count_rows()` + moving the marker write to once-per-bulk-run to avoid an
   O(N²) paper-id scan) and sequences the surrounding guards into shippable
   milestones.

### Assumptions

- `[MUST]` `tbl.count_rows()` is cheap (Lance reads the fragment-metadata footer,
  not rows) — cheap enough to call once at server startup and once per
  bulk-run. The synthesis claims O(1); the challenger flags that the
  *distinct-`paper_id`* scan is O(N) (→ O(N²) if left in the per-paper loop).
  Validated by SEQUENCE Spike-1 + the once-per-run write design.
- `[MUST]` No reader of the marker's `chunk_count`/`paper_count` makes a
  correctness decision, so correcting the values + adding a divergence WARN
  cannot regress retrieval or the cache. Re-confirmed at MATERIALIZE (grep +
  the X-gate test run).
- `[SHOULD]` arXMCP's synchronous `num_partitions=1` HNSW build never leaves
  `num_unindexed_rows > 0` in normal operation — determines whether the
  index-staleness guard is a pure corruption tripwire. SEQUENCE Spike-2.
- `[SHOULD]` Flipping the default log format to JSON won't break tests that
  grep human-readable log text — DECOMPOSE designs the fallback (audit
  `grep -r caplog tests/` first; gate behind `ARXMCP_LOG_FORMAT`).
- `[MIGHT]` Operators want a Prometheus *alert rule* on divergence (not just a
  startup WARN) — the gauge pair assumes yes, but is cheap regardless.

### Objective

Make silent corpus-metadata divergence a caught-at-write-or-startup failure
rather than a manual-inspection discovery — restoring operator and agent trust
in every corpus-state number arXMCP reports.

### Key Results

1. After any multi-paper ingest or re-embed run, `corpus-version.json`
   `chunk_count`/`paper_count` equal the live LanceDB table counts — asserted by
   a regression test that FAILS on today's code and passes after the fix.
2. A marker-vs-table divergence beyond a configurable tolerance (default 5%) is
   surfaced within one server startup: a WARN log + a `degraded` `/readyz`
   signal + a non-zero `abs(actual − marker)` on a `/metrics` gauge pair.
3. Zero change to `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256` and zero
   new runtime dependency or non-loopback surface (verified green in the
   milestone-pipeline X-gates).
4. The daily ops report renders a corpus-integrity row (marker vs actual +
   `corpus_version`) so the divergence is visible in the existing daily cadence.
5. `count_rows()` is computed at most once at startup (cached on `Resources`)
   and never per-`/metrics`-scrape — verified by a test asserting a single call.

### Won't (explicit out-of-scope)

- A new `get_corpus_status` MCP tool (re-pins BP1; deferred until a concrete
  agent branching-on-corpus-integrity need exists — the BP1-free `/readyz`-body
  extension is in scope instead). [scout CAND-6 tool form]
- Embedder-version-skew gauge / Drift-Adapter / GradNormIR — zero diagnostic
  value until BGE-M3 is ever upgraded; E14 S06+ backlog. [CAND-13]
- OTel GenAI/MCP semantic-convention attribute alignment — Phoenix/Datadog QOL,
  not a correctness fix; E14 S06+ backlog. [CAND-11]
- A `corpus_integrity_token` envelope field — `corpus_version` already serves
  the substrate-change signal. [CAND-12]
- Semantic eval-coverage scan — belongs to the eval-curation track, blocked on a
  non-empty `queries.json`. [CAND-14]
- The Hypothesis stateful property-test layer — the deterministic multi-paper
  test is the must-have; the `RuleBasedStateMachine` + new dev-dep is its own
  later milestone. [CAND-5b]
- A standalone `validate_corpus` CLI and a per-session corpus-version guard —
  killed by the scout challenger (subsumed by the startup check + test;
  structurally dead under the startup-pin architecture). [CAND-15, CAND-16]
- Heavy data-validation runtimes (Great Expectations, soda-core, dbt, DVC,
  LakeFS) and remote/OpenMetrics-exemplar backends — conflict with local-first /
  no-new-infra; patterns are lifted natively.

---

## Phase 2 — Decompose

### Technique

Vertical slicing + enabler stories. Each epic is an end-to-end slice of the
detect→surface loop (write-the-correct-count→catch-divergence→report-it), not a
horizontal layer — so each epic is independently demoable. (Event Storming was
considered for the ingest event-flow but the scope is too small to warrant it.)

### Epics

#### corpus-integrity-observability-e1 — Corpus counts always match the table, and any divergence is caught at write + startup

- **Type:** value
- **Specialist suggestion:** `determinism-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (the marker counts + the startup-cached `count_rows()` must be deterministic and reconciled against ground truth; touches `ingest/store.py` + `server/resources.py` + `server/health.py`)
- **Outcome:** after any multi-paper ingest/re-embed, `corpus-version.json`
  counts equal `tbl.count_rows()`; a divergence beyond tolerance trips a WARN +
  `degraded` `/readyz` + a `/metrics` gauge pair, within one startup. (scout
  CAND-1 root fix + CAND-5a regression test + CAND-2 startup invariant + CAND-3
  gauges.)
- **Estimated size:** M
- **INVEST check:** I — clean (self-contained; CAND-1 is the root, the rest build within the epic); N — negotiable (tolerance %, gauge names); V — value (kills the motivating bug class); E — estimable; S — M (≤ 3 wk, under the 6-wk cap); T — testable (the regression test IS the acceptance gate).
- **Dependencies:** none (CAND-1 = in-flight task #26; absorb it here).
- **Won't conflict check:** none (no new MCP tool, no BP1 change — honors the Won't list).

#### corpus-integrity-observability-e2 — Operators see corpus integrity in the daily report and in structured logs

- **Type:** value
- **Specialist suggestion:** `—` (health-endpoint + reporting + logging changes; no parser/schema/cache/subprocess path — the milestone-pipeline adversary critic suffices)
- **Outcome:** the daily ops report renders a corpus-integrity row (marker vs
  actual + `corpus_version`); the `/readyz` 200 body carries `chunk_count` /
  `marker_chunk_count`; the write path emits a structured, test-assertable log
  event and JSON logging is selectable by default. (scout CAND-9 + CAND-6b
  `/readyz`-body form + CAND-4.)
- **Estimated size:** S
- **INVEST check:** I — borderline (the daily-report row consumes e1's CAND-3 gauges → depends on e1); N — clean; V — value (human-cadence visibility); E — estimable; S — S (≤ 1 wk); T — testable (assertLogs on the structured event; report-render snapshot).
- **Dependencies:** e1 (CAND-9 reads the CAND-3 gauges; sequence after).
- **Won't conflict check:** none (`/readyz`-body form is the BP1-free CAND-6 cut; the `get_corpus_status` tool stays on the Won't list).

#### corpus-integrity-observability-e3 — Ingest throughput is observable from /metrics

- **Type:** value (enabler-flavored — closes the note-08 deferred metric stub)
- **Specialist suggestion:** `determinism-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (the new `ingest-summary.json` sentinel schema + `WriteStats` enrichment must be deterministic and reconcile with the table)
- **Outcome:** `arxmcp_ingest_papers_processed_total` / `..._chunks_written_total`
  (the families named in `08-security-observability-ops.md` but never emitted)
  reach `/metrics` via an `ingest-summary.json` sentinel read by
  `refresh_sentinel_metrics`; `WriteStats` records `paper_id` +
  `total_rows_after_commit`. (scout CAND-7 + CAND-8.)
- **Estimated size:** M
- **INVEST check:** I — borderline (depends on e1's CAND-1 so the sentinel records correct counts, not `len(chunks)`); N — clean; V — value (ingest is unobservable today); E — borderline (the challenger flagged the writer-side sentinel schema as net-new → M+; gated by a SEQUENCE spike); S — M; T — testable (writer + reader path).
- **Dependencies:** e1 (CAND-1 correctness) + SEQUENCE Spike-1 (sentinel schema + counter-vs-gauge semantics).
- **Won't conflict check:** none (sentinel-file bridge is the established local-first pattern; no new heavy infra).

---

## Phase 3 — Sequence

### MoSCoW assignment

- **Must** (≤ 60% of total effort): `corpus-integrity-observability-e1` (42.9% by `score-moscow.py` — the gap-killer; without it the bug ships)
- **Should**: `corpus-integrity-observability-e2` (operator/human-cadence visibility; the release still catches the bug without it)
- **Could**: `corpus-integrity-observability-e3` (ingest throughput metrics; spike-gated, e1-dependent)
- **Won't (this cycle)**: the deferred/killed scout candidates listed in Phase 1's Won't — CAND-6 tool form, CAND-10, CAND-11, CAND-12, CAND-13, CAND-14, CAND-15, CAND-16.

_`score-moscow.py` → Must = 42.9% (≤ 60% cap), exit 0._

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| corpus-integrity-observability-e1 | 1000 | 3.00 | 90% | 3.00 | 900.0 |

_Single Must → rank is trivial. Confidence 90% (not the 50% default): 5-brief
triangulation + the bug is already root-caused (task #26). No `*` markers._

### Now / Next / Later

- **Now** (fully spec'd, in-flight or next-up): `e1` (decomposed into m1, m2 below; m1 = in-flight task #26).
- **Next** (shaped, awaiting capacity): `e2` (operator reporting + structured logging; sequence after e1 lands so the daily-report row reads correct gauges).
- **Later** (outcome-only, low-confidence horizon): `e3` (ingest metrics; gated by spike-3's sentinel-schema + counter-vs-gauge decision).

### Spike / discovery lane

- `corpus-integrity-observability-spike-1` — measure `tbl.count_rows()` cost (confirm it reads Lance fragment metadata, ~O(1)) AND the distinct-`paper_id` scan cost on the live bridgeland notebook (10,298 rows); confirm the once-per-bulk-run marker-write design eliminates the O(N²) concern. (≤ 1 day, validates `[MUST]`: "`count_rows()` is cheap enough to call at startup + once per bulk-run".)
- `corpus-integrity-observability-spike-2` — `grep`/trace every reader of `corpus-version.json` `chunk_count`/`paper_count` (expected: only `server/resources.py:341-342` startup log + `server/corpus.py` `to_dict`) to confirm no correctness path consumes them, so correcting the values + adding a divergence WARN cannot regress retrieval or the cache. (≤ 1 day, validates `[MUST]`: "no reader makes a correctness decision".)
- `corpus-integrity-observability-spike-3` — design the `ingest-summary.json` sentinel schema + decide counter-since-boot vs last-run-snapshot gauge semantics (the challenger flagged the writer-side schema as net-new → M+). (≤ 2 days, de-risks the Later epic e3 before it is committed; not tied to a `[MUST]`.)

### Milestones — Now lane

<!--
Each Now-lane milestone is its own H3 below. Heading format is
`### <slug>-mN — Title` exactly — milestone-pipeline's init-state.sh
greps for this. Do not change it.
-->

### corpus-integrity-observability-m1 — Write-time corpus-count reconciliation (= task #26)

**Description.** Fix the root cause: `ingest/store.py::write_chunks` must derive
`chunk_count`/`paper_count` from the committed table (`tbl.count_rows()` + a
distinct-`paper_id` count), not from the in-flight `len(chunks)` batch. To avoid
an O(N²) per-paper scan, move `write_corpus_version_marker` OUT of the per-paper
loop in `bulk_ingest.py` / `re_embed.py` to once per run, computing the counts
once against the final table. Ships with the multi-paper regression test that
fails on today's code (scout CAND-1 + CAND-5a). Absorbs in-session task #26.

**Acceptance criteria.**
- Given a multi-paper ingest or re-embed run, When it completes, Then
  `corpus-version.json::chunk_count == tbl.count_rows()` and `paper_count ==`
  the distinct-`paper_id` count of the committed table.
- [ ] `write_corpus_version_marker` is invoked once per run (not once per
  paper), reading counts from the committed table; `version` stays the
  post-index `tbl.version`.
- [ ] A regression test ingests ≥2 synthetic papers through the per-paper loop
  and asserts marker counts == table counts; it FAILS on the pre-fix code.
- [ ] `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` unchanged; no
  `CHUNKER_VERSION` bump; `make test` green.

**Dependencies.** none (absorbs task #26); informed by spike-1 (count cost) + spike-2 (no correctness reader).

**Complexity.** M

**Specialist suggestion.** `determinism-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md`

### corpus-integrity-observability-m2 — Startup reconciliation invariant + corpus-size gauges

**Description.** Add defense-in-depth + an alertable signal. At
`Resources.startup`, compute `count_rows()` ONCE (cache it on `Resources`) and
compare against the marker's `chunk_count`; on divergence beyond a configurable
tolerance (default 5%) log a WARN with both values and set
`DegradedState.reason="chunk_count_diverged"` (WARN-and-serve — retrieval is
unaffected). Expose `arxmcp_corpus_chunk_count_marker` +
`arxmcp_corpus_chunk_count_actual` gauges from that single cached value (scout
CAND-2 + CAND-3).

**Acceptance criteria.**
- Given a marker whose `chunk_count` diverges from the live table by > tolerance,
  When the server starts, Then it logs a WARN with both values and `/readyz`
  reports `degraded` with `reason="chunk_count_diverged"`.
- Given matching counts, When the server starts, Then no WARN, not degraded, and
  the two gauges are equal.
- [ ] Both gauges are set once at startup from a single cached `count_rows()`;
  a test asserts `count_rows()` is called at most once (never per `/metrics`
  scrape).
- [ ] `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` unchanged; `make
  test` green.

**Dependencies.** `e1` / m1 (the marker must be correct first); shares the startup-cached `count_rows()` contract (one `Resources` field).

**Complexity.** M

**Specialist suggestion.** `determinism-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md`

---

## Phase 4 — Materialize

### Validation

- `validate-roadmap.py`: PASS (all 4 phases populated, no unresolved placeholders).
- Must-cap: 42.9% (≤ 60% — `score-moscow.py` exit 0).
- All Now-lane milestones have AC: PASS (m1, m2 each carry G/W/T + bullet AC; validator MILESTONE-AC check green).
- Slug format valid: yes (`corpus-integrity-observability` matches `^[a-z][a-z0-9-]{2,30}$`, not `^e\d+$`).

### GitHub tickets

Not requested — `--github` was not passed, so no per-issue body files or
`create-tickets.sh` were generated. (arXMCP creates issues manually; re-invoke
`roadmap corpus-integrity-observability --github` to produce the bundle.)

### Next step

First Now-lane milestone: `corpus-integrity-observability-m1` (the write-time
count reconciliation — it ALSO closes in-session task #26). To execute it
end-to-end:

```
/milestone-pipeline corpus-integrity-observability-m1
```

`milestone-pipeline`'s `init-state.sh` resolves the brief by grepping
`### corpus-integrity-observability-m1 ` in `plans/*.md`, so it finds this doc
directly. Then `corpus-integrity-observability-m2` (startup invariant + gauges)
once m1 lands. This skill does NOT invoke milestone-pipeline — cache stays
warmer if you start that session within 5 minutes.

Two SEQUENCE spikes (`spike-1` count cost, `spike-2` no-correctness-reader) are
≤1-day pre-flights for m1; `spike-3` (ingest-summary schema) de-risks the
Later epic e3 before it's committed.

<!-- Default suggestion: run `milestone-pipeline corpus-integrity-observability-m1` for the first
Now-lane milestone. Offered, not auto-invoked. -->

---

<!-- end:roadmap -->
