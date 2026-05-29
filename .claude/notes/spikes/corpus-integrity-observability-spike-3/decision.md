# Spike Decision — corpus-integrity-observability-spike-3

**Locked decision record for the e3 implementer. Read this; the full investigation
is in `research.md`.**

**Date:** 2026-05-29 · **Verdict:** GO — e3 is safe to commit, sized **M** (~150 LOC).

---

## Decision 1 — Gauge (last-run-snapshot), NOT Counter

The note-08 draft names `arxmcp_ingest_papers_processed_total` /
`arxmcp_ingest_chunks_written_total` as **counters** (`08-security-observability-ops.md:131-138`).
**Override that: implement them as gauges with last-run-snapshot semantics.**

**Why Counter is wrong here** (the load-bearing reason this spike existed):
- A Prometheus Counter needs a durable, monotonically-increasing cumulative total.
- Ingest runs in a **cron/CLI process that exits between runs**; the server's in-process
  registry resets on restart. A sentinel-file Counter would have to carry a
  forever-cumulative total that survives a **corpus rebuild / `ops_dir` wipe** — and when
  that resets to zero, the Counter goes **backwards**, violating the Counter contract and
  corrupting any `rate()`.
- The one existing cross-scrape Counter (`EMBED_SINGLEFLIGHT_DEDUP_COUNTER`,
  `health.py:301-305`) only works because its source is an **in-process** monotonic
  singleton in the same process as the registry. Ingest is a different process — the
  analogy does not transfer.
- `rate()` over a once-daily local cron is not operationally useful. The operator's real
  question is "did the last run succeed and how big was it?" — a **snapshot**.

The scout challenger (`challenge.md:121-125`) and the synthesis both already leaned Gauge.

## Decision 2 — metric names + NO `{driver}` Prometheus label

**Locked names (unlabeled scalar gauges):**
```
arxmcp_ingest_last_run_papers     gauge   # replaces ..._papers_processed_total
arxmcp_ingest_last_run_chunks     gauge   # replaces ..._chunks_written_total
arxmcp_ingest_last_run_timestamp_seconds   gauge   # finished_at as epoch (freshness)
```

**Refinement on the research (do NOT add a `{driver}` label).** `ingest-summary.json` is a
SINGLE file each driver overwrites, so the reader only ever sees the most-recent run. A
`{driver}` Prometheus label would (a) leave the non-most-recent driver's series frozen at
a stale value forever, and (b) break the clean "absent file → set 0.0" reset (you can't
blanket-zero a labelled series without knowing every label value). **Keep the gauges
unlabeled; carry `driver` as a JSON field surfaced in the daily-report row only.** This
preserves the established `_sentinel_gauge`/absence-zeroing pattern exactly.

**note-08 update is part of e3** — replace the two `_total` counter rows with the gauge
names above, BEFORE wiring the Prometheus objects, so brief and code never diverge.
`arxmcp_ingest_oai_pmh_lag_seconds` already correctly a gauge — leave it.

## Decision 3 — `ingest-summary.json` schema (v1, locked)

Path: `var/arxmcp/ops/ingest-summary.json` (under `config.ops_dir`; gitignored).
Atomic write: temp-then-`os.replace()`, identical to `oai_delta._write_state`
(`oai_delta.py:216-224`). Inherits the F1 64 KB oversized guard via `_read_capped`
automatically.

```json
{
  "schema_version": 1,
  "driver": "bulk_ingest",
  "finished_at": "2026-05-29T04:00:00Z",
  "elapsed_seconds": 312.4,
  "papers_processed": 52,
  "papers_succeeded": 50,
  "papers_failed": 2,
  "chunks_written_this_run": 4820,
  "total_rows_after_commit": 10298
}
```
- `schema_version` — reader fails fast / leaves prior gauges on an unknown bump.
- `papers_processed` ← `IngestSummary.papers_total` (bulk) / `DeltaSummary.records_total`
  (delta); map `papers_succeeded`←`records_ingested`, `papers_failed`←`records_failed`
  on the delta path.
- `chunks_written_this_run` ← accumulate `WriteStats.rows_inserted + rows_updated` over
  the run loop (accurate per-run, no extra `count_rows()`).
- `total_rows_after_commit` ← the final `tbl.count_rows()` already computed inside
  `write_chunks` (`store.py:931`, shipped in m1) — thread it through `WriteStats` (CAND-8).

Reader: a new block in `refresh_sentinel_metrics` (file present → `.set()` papers/chunks/
timestamp; malformed → WARN + leave prior; absent → `.set(0.0)`), mirroring the
`backup-status.json` reader.

## Decision 4 — WriteStats enrichment (CAND-8)

Add `paper_id: str = ""` and `total_rows_after_commit: int = 0` to `WriteStats`
(`store.py:173-204`) + `to_dict()`; populate from `write_chunks` (both already in scope —
`paper_id` is an arg, `total_rows_after_commit` = the m1 `count_rows()` at `store.py:931`).
Zero extra I/O. Keep `chunk_count` (per-batch) unchanged.

## e3 implementation surface (M, ~150 LOC)

| File | Change |
|---|---|
| `ingest/store.py` | `WriteStats` += `paper_id`, `total_rows_after_commit`; populate in `write_chunks` |
| `ingest/ingest_summary.py` (new) | `write_ingest_summary(ops_dir, driver, summary)` — atomic |
| `ingest/bulk_ingest.py` | call it after the `run_bulk_ingest` loop (success path) |
| `ingest/oai_delta.py` | call it after `run_delta` success path |
| `server/metrics.py` | `INGEST_LAST_RUN_PAPERS` / `_CHUNKS` / `_TIMESTAMP` gauges (unlabeled) |
| `server/health.py` | `refresh_sentinel_metrics` += `ingest-summary.json` reader + `_INGEST_SUMMARY_NAME` |
| `tools/daily_metrics_report.py` | optional: an "Ingestion throughput" row (replaces the current TODO stub) reading the new gauges + `driver` |
| `.claude/notes/08-security-observability-ops.md` | `_total` counters → the gauge names |
| tests | writer (happy/missing-dir/atomic) + reader (present/absent/oversized/malformed) + the metrics-fixture regen |

**Pre-condition satisfied:** m1 shipped (`count_rows()` in `write_chunks`), so CAND-8 is
free. **External writes:** none (local sentinel under `var/arxmcp/ops/`).

## Open questions

None blocking. The daily-report "Ingestion throughput" row currently a TODO stub
(`daily_metrics_report.py`) is a natural fold-in for e3 but optional — flag it in the e3
brief as in-or-out of scope.
