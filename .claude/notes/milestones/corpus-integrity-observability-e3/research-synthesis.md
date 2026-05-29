# Research Synthesis — corpus-integrity-observability-e3

**Merged from:** research-brief-1.md (seam verification) + research-brief-2.md (failure
modes). **Generated:** 2026-05-29.
**Verdict:** INLINE, ~150 LOC. **DESIGN IS LOCKED by spike-3** — follow
`.claude/notes/spikes/corpus-integrity-observability-spike-3/decision.md` verbatim; this
synthesis is the verified seam map + failure-mode discipline + implementation order.

## ⚠️ BLOCKER (both briefs, independently) — resolve before Phase 2 commit

**`server/health.py` has ~222 lines of UNCOMMITTED `notebook-ops-hardening-m4` edits**
(the `/status` endpoint + `compute_health_status()`, inserted ~after line 261; they do
NOT touch `refresh_sentinel_metrics`). e3 must add `_INGEST_SUMMARY_NAME` + a reader block
to `server/health.py`. Committing e3's `health.py` edits while the m4 work is uncommitted
would sweep two milestones into one commit (violates the three-commit pattern). **The m4
work must be committed (or stashed) by the parallel session before e3's `health.py` change
can land cleanly.** Surface to the user at the Phase 2 boundary.

## 1. Locked design (spike-3 decision.md — do NOT re-litigate)

- **GAUGE last-run-snapshot, NOT Counter.** Unlabeled scalar gauges (note-08's `_total`
  counter names are OVERRIDDEN): `arxmcp_ingest_last_run_papers`,
  `arxmcp_ingest_last_run_chunks`, `arxmcp_ingest_last_run_timestamp_seconds`. **NO
  `{driver}` Prometheus label** (research.md's labelled form is superseded by decision.md
  Decision 2; a labelled non-recent-driver series would freeze stale). `driver` rides as a
  JSON field, surfaced in the daily-report row only.
- **`ingest-summary.json` v1** at `var/arxmcp/ops/` (atomic same-dir `.tmp` +
  `tmp.replace(path)`; inherits the 64 KB `_read_capped` guard). Fields: `schema_version`,
  `driver`, `finished_at` (ISO-8601 UTC), `elapsed_seconds`, `papers_processed`,
  `papers_succeeded`, `papers_failed`, `chunks_written_this_run`, `total_rows_after_commit`.
- **WriteStats += `paper_id` + `total_rows_after_commit`** (CAND-8; free — m1 computes
  `count_rows()` at `store.py:931`). Keep `chunk_count` as-is — **no alias/deprecation**
  (resolves the research.md "deprecated alias" note; brief-1 §3).

## 2. Verified seam map (CURRENT file:line — the parallel churn shifted them)

| Touch point | Current location | Note |
|---|---|---|
| `refresh_sentinel_metrics` | `server/health.py:558` (was :342) | mirror the `backup-status.json` reader block (`:606-652`); reader goes after it |
| `_read_capped` 64 KB guard | `server/health.py:660` (`_MAX_SENTINEL_BYTES` = `:85`) | inherited automatically |
| sentinel name constants | `server/health.py:60-64` | add `_INGEST_SUMMARY_NAME = "ingest-summary.json"` at ~:65 |
| **new gauges** | **`server/metrics.py` ~:278** (after `BACKUP_STATUS_GAUGE`) | NOT health.py — all scrape-time sentinel gauges live in metrics.py; add to `reset_sentinel_metrics_for_tests()` + `__all__`; late-import in `refresh_sentinel_metrics` |
| `WriteStats` + `to_dict()` | `ingest/store.py:173-204` | add 2 fields; populate in `write_chunks` ~`:873-880` from the `chunk_count`/`paper_id` already in scope |
| `run_bulk_ingest` | `ingest/bulk_ingest.py:338`, return ~`:397` | call `write_ingest_summary` before `return summary`; map from `IngestSummary` (`papers_total`/`_succeeded`/`_failed`); accumulate `chunks_written` from per-paper `outcome.chunks_written` (or `WriteStats.rows_inserted+rows_updated`) |
| `run_delta` | `ingest/oai_delta.py:677`, after `_write_state` ~`:824` | call `write_ingest_summary`; map `papers_processed←records_total`, `_succeeded←records_ingested`, `_failed←records_failed` |
| atomic-write template | `ingest/oai_delta.py:216-224` (`_write_state`) | copy EXACTLY: same-dir `.tmp` then `tmp.replace(path)` |
| daily-report stub | `tools/daily_metrics_report.py:421-431` | replace TODO with a real row (mirror e2's `## Corpus integrity` + `_sentinel_gauge`); read `driver` from the sentinel file directly |
| regen fixture | `tools/regen_metrics_fixture.py::populate_registry` :59-119 | `.set()` the 3 gauges with representative values, then regen `tests/fixtures/metrics_sample.txt` |
| note-08 | `.claude/notes/08-security-observability-ops.md:131-138` | replace the 2 `_total` counter rows with the 3 gauge names (FIRST, before wiring) |

`ingest/ingest_summary.py` is fully net-new (no existing `write_ingest_summary`). Drivers
hardcode `var/arxmcp/ops/`; the writer takes `ops_dir: Path` (callers pass the hardcoded
path); the reader gets `ops_dir` from `config.ops_dir` — same directory.

## 3. Failure modes → required mitigations (brief-2)

- **FM-1 torn write** → same-dir `.tmp` + `tmp.replace(path)` (POSIX-atomic on one fs).
  Do NOT use `tempfile.NamedTemporaryFile(dir=None)` (defaults to `/tmp` → cross-fs →
  non-atomic). Copy `_write_state` exactly.
- **FM-2 metrics-fixture regen** (this bit e2) → add `.set()` for all 3 gauges in
  `populate_registry`, run `uv run python -m tools.regen_metrics_fixture`, commit the
  fixture in the feat commit. `TestRegenFixture` fails otherwise.
- **FM-3 driver staleness** → expected; `arxmcp_ingest_last_run_timestamp_seconds` is the
  freshness signal; the report row shows `driver` (from JSON) + the age.
- **FM-4 sentinel absent** → reader `.set(0.0)` on all 3 (mirror `backup-status.json`
  absence); report renders `n/a`. Timestamp 0.0 = epoch → a freshness alert fires (correct
  "never ingested" signal).
- **FM-5 oversized/malformed** → `_read_capped` (None→leave prior) + wrap the full
  parse-and-set in `except (json.JSONDecodeError, OSError, ValueError): WARN` (per-file
  isolation — a bad file must not crash the scrape or zero the gauges).
- **FM-6 chunks accuracy** → `rows_inserted + rows_updated` (merge_insert: insert N OR
  update N → N either way; not a double-count). Prefer threading `WriteStats` for
  auditability; `outcome.chunks_written` is coincidentally equal in the current code.
- **FM-7 schema_version** → check `payload.get("schema_version") != 1` FIRST → WARN +
  leave-prior (NOT crash, NOT silent-zero — a silent-zero would read as "never ingested").
  No `assert` (banned for invariants); use `if … : return` + WARN.

## 4. Acceptance criteria (from the e3 epic)

1. `arxmcp_ingest_last_run_papers` / `_chunks` / `_timestamp_seconds` reach `/metrics` via
   the `ingest-summary.json` sentinel read by `refresh_sentinel_metrics`.
2. A real bulk + delta run writes `ingest-summary.json` atomically with the v1 schema.
3. `WriteStats` records `paper_id` + `total_rows_after_commit`.
4. The daily report renders an Ingestion-throughput row (papers / chunks / driver /
   freshness), `n/a` when the sentinel is absent.
5. note-08 updated (counters → gauges); `EXPECTED_TOOL_SCHEMA_SHA256` +
   `EXPECTED_BP1_SHA256` UNCHANGED; `make test` green (incl. regenerated fixture).
6. Tests: writer (happy / missing-dir / atomic same-dir-tmp) + reader (present / absent /
   oversized / malformed / schema_version-mismatch).

## 5. Implementation order (brief-2 §Recommendation — minimizes test breakage)

1. note-08 (counter rows → gauge names). 2. `WriteStats` fields + populate. 3.
`ingest/ingest_summary.py` (atomic). 4. wire into `run_bulk_ingest` + `run_delta`. 5. 3
gauges in `server/metrics.py`. 6. reader block in `refresh_sentinel_metrics`
(schema_version-first; except-wrapped). 7. update `populate_registry` + regen fixture. 8.
daily-report row. 9. tests.

## 6. Open questions

**None blocking the design.** ONE process blocker (not a design question): the uncommitted
m4 work in `server/health.py` (§BLOCKER) must clear before e3's `health.py` edit can be
committed cleanly. The orchestrator will surface this at the Phase 2 boundary.

## 7. External writes required

**None** — purely local (`ingest/`, `server/`, `tools/`, note-08, the fixture; the sentinel
is gitignored under `var/arxmcp/ops/`). Both briefs concur.
