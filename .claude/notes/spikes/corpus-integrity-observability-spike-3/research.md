# Design Spike: corpus-integrity-observability-spike-3
# `ingest-summary.json` sentinel schema + counter-vs-gauge decision

**Generated:** 2026-05-29T00:00:00Z
**Spike question:** Design the `ingest-summary.json` sentinel schema and decide
counter-since-boot vs last-run-snapshot gauge semantics, to de-risk e3 before commit.

---

## 1. Findings

### A. How the existing sentinel-file → /metrics bridge works

**`_MAX_SENTINEL_BYTES = 64 * 1024`** (`server/health.py:85`) — every sentinel read goes
through `_read_capped(path)` (`health.py:444-470`), which calls `path.stat().st_size`
first and returns `None` (plus a WARNING log) if the file exceeds 64 KB. The caller
treats `None` as "oversized; leave prior gauge value". This is the F1 guard all new
sentinels must inherit.

The existing sentinel files and their contracts (from `server/health.py:60-65` and
`refresh_sentinel_metrics:342-441`):

| File | Schema | Missing/absent behavior |
|---|---|---|
| `drift-detected.flag` | touch-file OR `{"fixture_count": N}` | absence → gauge 0.0 |
| `eval-quarantine.flag` | touch-file (any body) | absence → gauge 0.0 |
| `delta-timeout.flag` | `{"elapsed_seconds": F, "budget_seconds": F, "ts": ISO}` | absence → gauge 0.0 |
| `backup-status.json` | `{"status": "ok"\|"failed"\|"running", "finished_at": ISO}` | absence → all state cells 0.0 |
| `eval-reports/corpus_v<N>-*.json` | `{"ndcg5_mean": F, ...}` | absent dir → no-op |

Per-file errors are **isolated** (`health.py:427`): malformed JSON in one file logs a
WARNING and leaves the prior gauge value; it does NOT prevent other sentinels from
refreshing.

**`refresh_sentinel_metrics(ops_dir: Path)`** (`health.py:342`) is called from
`refresh_metrics_from_singleton_state` (`health.py:323-324`) on every `/metrics` scrape.
The `ops_dir` comes from `config.ops_dir` (`server/config.py:160`), defaulting to
`var/arxmcp/ops`.

**`refresh_metrics_from_singleton_state`** (`health.py:269`): the only existing
cross-process Counter bridge is `EMBED_SINGLEFLIGHT_DEDUP_COUNTER` (`health.py:147`).
The pattern:

```python
# health.py:301-305
current = get_singleflight_dedup_count()
delta = current - _LAST_DEDUP_COUNT
if delta > 0:
    EMBED_SINGLEFLIGHT_DEDUP_COUNTER.inc(delta)
    _LAST_DEDUP_COUNT = current
```

This requires the source-of-truth integer to be a **monotonically increasing in-process
singleton** (`_LAST_DEDUP_COUNT` module-level at line 158). There is no analogous
durable-cumulative-total file read at scrape time — the singleflight counter is
in-process only.

### B. `delta-status.json` — does it exist?

**No.** Grepping the entire codebase (excluding worktrees) confirms:
- `tools/daily_metrics_report.py:428` references `var/arxmcp/ops/delta-status.json` as
  a future sentinel in a TODO comment. The string appears verbatim as part of an ops
  note about what is NOT yet wired.
- `ingest/oai_delta.py` writes `oai-pmh-state.json` (run state + last harvest date,
  `oai_delta.py:123-224`) and `delta-timeout.flag` (`oai_delta.py:641-663`), but NO
  `delta-status.json`.
- The `DeltaSummary` dataclass (`oai_delta.py:185-195`) holds: `sets_harvested`,
  `records_total`, `records_deleted`, `records_ingested`, `records_failed`,
  `pages_fetched`, `elapsed_seconds`, `budget_breached`. It is never serialized to a
  sentinel file.

**`delta-status.json` is a phantom** — named in a comment but not written by any
driver. `ingest-summary.json` for e3 must be a **net-new sentinel**; it cannot reuse
an existing file.

### B. WriteStats current fields

`WriteStats` (`store.py:173-204`) fields:

```python
chunk_count: int = 0          # per-batch count (len(chunks))
elapsed_s: float = 0.0
lancedb_version: int = 0      # post-index tbl.version
rows_inserted: int = 0
rows_updated: int = 0
indices_created: dict[str, bool] = field(default_factory=dict)
```

**Missing:** `paper_id` (CAND-8 scout request) and `total_rows_after_commit` (the
cumulative table count). Both are already available in `write_chunks` at the point
`stats` is constructed (`store.py:873-880`) — `paper_id` is a direct argument to
`write_chunks`, and `total_rows_after_commit` = `tbl.count_rows()` already called at
`store.py:931` for the marker. The cost is zero extra I/O.

`_append_store_stats(stats: WriteStats)` (`store.py:637`) appends to
`var/arxmcp/ops/store-stats.jsonl` — this is NOT the sentinel file for `/metrics`
scraping; it is an append-only ops audit log.

### B. Driver end-of-run totals

**`run_bulk_ingest`** (`bulk_ingest.py:338`, returns `IngestSummary`): fields
`papers_total`, `papers_succeeded`, `papers_failed`, `papers_skipped`, `ar5iv_hits`,
`ar5iv_misses`, `elapsed_seconds`. No ops_dir access; writes to hardcoded paths under
`var/arxmcp/ops/` via module-level constants. No sentinel write at end of run.

**`run_delta`** (`oai_delta.py:677`, returns `DeltaSummary`): fields
`records_total`, `records_deleted`, `records_ingested`, `records_failed`,
`pages_fetched`, `elapsed_seconds`, `budget_breached`. Writes `oai-pmh-state.json`
via `_write_state` (atomic temp+replace pattern, `oai_delta.py:216-224`). No
ingest-summary sentinel written.

**`run_re_embed`** (`re_embed.py:627`, returns `ReEmbedSummary`): different concern
(re-embedding existing chunks, not paper count ingestion).

**Atomic write pattern:** `ingest/preamble._write_preamble_json` (`preamble.py:262-286`)
and `ingest/oai_delta._write_state` (`oai_delta.py:216-224`) both use the same pattern:
write to `path.with_suffix(suffix + ".tmp")`, then `os.replace(tmp, path)` (POSIX
atomic). The e3 writer must follow the same pattern.

**`ops_dir` access:** ingest drivers hardcode paths under `var/arxmcp/ops/` via
module-level `REPO_ROOT / "var" / "arxmcp" / "ops" / ...` constants. They do NOT
read `server/config.py` (server-only). The `ops_dir` for the ingest-summary sentinel
should therefore be the same hardcoded base: `REPO_ROOT / "var" / "arxmcp" / "ops" /
"ingest-summary.json"`. This matches the convention and is the path
`refresh_sentinel_metrics` will find under `config.ops_dir` (default
`var/arxmcp/ops`).

### C. Note-08 metric names

From `08-security-observability-ops.md:131-138` (verbatim):

```
Ingestion (separate process; same metrics endpoint pattern):

arxmcp_ingest_papers_processed_total{parser,outcome}    counter
arxmcp_ingest_paper_duration_seconds{parser,quantile}   summary
arxmcp_ingest_chunks_written_total                      counter
arxmcp_ingest_oai_pmh_lag_seconds                       gauge
```

Note-08 **explicitly names these as `counter`** with `_total` suffixes.
No annotation says "Gauge acceptable as interim." The naming is clear-intent Counter.

### D. Scout challenge (verbatim, CAND-7 — `challenge.md:92-117`)

> "The writer side is net-new: the ingest process must produce a well-formed
> `ingest-summary.json` that the server's `refresh_sentinel_metrics` hook can parse.
> The existing sentinels (drift, quarantine, backup) all have fixed schemas; adding a
> new sentinel type requires (a) a server-side schema guard in `_read_capped` callers,
> (b) a new `INGEST_PAPERS_PROCESSED_GAUGE` / `INGEST_CHUNKS_WRITTEN_GAUGE` pair in
> `server/health.py`, (c) a new `refresh_ingest_metrics` hook or extension of the
> existing `refresh_sentinel_metrics`, and (d) tests for both the writer and the reader
> path. Together these drive the milestone closer to M+ than S."

The challenger also (`challenge.md:119-127`) recommended: "v0: After CAND-1 is shipped,
write `ingest-summary.json` with last-run totals (gauges, not counters:
`papers_processed_last_run`, `chunks_written_last_run`, `timestamp`). Extend
`refresh_sentinel_metrics` with a new reader for this file. Add `INGEST_PAPERS_GAUGE`
+ `INGEST_CHUNKS_GAUGE` as Gauge (not Counter) to avoid reset-on-restart complexity."

CAND-8 (`challenge.md:348-373`) confirmed `total_rows_after_commit` depends on CAND-1's
`count_rows()` call — which has now shipped in corpus-integrity-observability-m1 (per
`store.py:931`).

---

## 2. Recommended `ingest-summary.json` schema

**File path:** `var/arxmcp/ops/ingest-summary.json` (under `config.ops_dir`).

**Writer:** Each ingest driver writes/overwrites this file at successful end-of-run.
For e3 scope, `run_bulk_ingest` (in `bulk_ingest.py`) and `run_delta` (in `oai_delta.py`)
are the two drivers. A shared helper `_write_ingest_summary(path, payload)` should live
in a new `ingest/ingest_summary.py` module (or be inlined per-driver — prefer the shared
module for testability).

**Schema (JSON):**

```json
{
  "schema_version": 1,
  "driver": "bulk_ingest" | "oai_delta",
  "finished_at": "2026-05-29T04:00:00Z",
  "elapsed_seconds": 312.4,
  "papers_processed": 52,
  "papers_succeeded": 50,
  "papers_failed": 2,
  "chunks_written_this_run": 4820,
  "total_rows_after_commit": 10298
}
```

Field notes:
- `schema_version: 1` — enables the reader to fail fast on future incompatible schema
  bumps rather than silently misinterpreting fields.
- `finished_at` — ISO-8601 UTC, same convention as `backup-status.json`.
- `papers_processed` — `IngestSummary.papers_total` (bulk) or
  `DeltaSummary.records_total` (delta). Note: `records_total` in DeltaSummary already
  includes deleted records; use `records_ingested` for `papers_succeeded` on the delta
  path, `records_failed` for `papers_failed`.
- `chunks_written_this_run` — sum of `WriteStats.rows_inserted + rows_updated` across
  the run, OR `IngestSummary.papers_succeeded * avg_chunks` approximation. The cleanest
  approach: accumulate `WriteStats.rows_inserted + rows_updated` in the driver loop.
  This avoids a second `count_rows()` call and is accurate per-run.
- `total_rows_after_commit` — final `tbl.count_rows()` from the last `write_chunks`
  call in the run (already computed inside `write_chunks` at `store.py:931`; propagate
  via `WriteStats` by adding `total_rows_after_commit` field there per CAND-8).

**Atomicity:** temp-then-`os.replace()` identical to `_write_state` in `oai_delta.py:216-224`.
No partial-write race with the scrape hook.

**Reader shape** (to add inside `refresh_sentinel_metrics`):

```python
_INGEST_SUMMARY_NAME: str = "ingest-summary.json"
# ...
ingest_summary_path = ops_dir / _INGEST_SUMMARY_NAME
if ingest_summary_path.is_file():
    try:
        raw = _read_capped(ingest_summary_path)
        payload = json.loads(raw) if raw is not None else None
        if payload is not None:
            INGEST_PAPERS_LAST_RUN_GAUGE.set(
                float(payload.get("papers_processed", 0))
            )
            INGEST_CHUNKS_LAST_RUN_GAUGE.set(
                float(payload.get("chunks_written_this_run", 0))
            )
    except (json.JSONDecodeError, OSError, ValueError):
        logger.warning("ingest-summary.json at %s is malformed; leaving prior gauge values",
                       ingest_summary_path, exc_info=True)
else:
    INGEST_PAPERS_LAST_RUN_GAUGE.set(0.0)
    INGEST_CHUNKS_LAST_RUN_GAUGE.set(0.0)
```

The `_read_capped` F1 guard is inherited automatically — no new size-cap logic needed.

---

## 3. Counter-vs-gauge DECISION

**Decision: Gauge (last-run-snapshot semantics). Rename the metric families. Update note-08.**

**Reasoning:**

The core tension: note-08 names `arxmcp_ingest_papers_processed_total` and
`arxmcp_ingest_chunks_written_total` as Counters (`_total` suffix). A sentinel-file
bridge cannot safely implement Counter semantics for a cron-exit process because:

1. **Counter requires a durable monotonically-increasing cumulative total.** The ingest
   process exits between runs. The server's in-process counter resets to zero on restart.
   Implementing a Counter via sentinel requires the sentinel to carry a
   FOREVER-CUMULATIVE total (not a per-run count). That total must survive: server
   restarts (trivial — read from file), corpus rebuilds/ops_dir wipes (fragile —
   the cumulative resets to zero, making the Counter go BACKWARDS at the next run,
   which violates the Counter contract and corrupts `rate()` queries).

2. **The singleflight counter analogy does NOT apply.** `EMBED_SINGLEFLIGHT_DEDUP_COUNTER`
   works because its source-of-truth integer is an in-process monotonically-increasing
   singleton in the SAME process as the Prometheus registry. The ingest drivers live in
   a DIFFERENT process. The `inc(delta)` pattern requires a reliable `_LAST_VALUE` that
   survives scrapes — which requires a durable file read anyway. And if the ops_dir is
   wiped, the delta becomes negative. There is no safe way to implement Counter semantics
   via a sentinel file written by an exiting process without a separate durable-total
   state file, which is YAGNI complexity for a single-user local server.

3. **Gauge is semantically correct for cron-exit reality.** The question "how many papers
   did the last ingest run process?" is a snapshot, not a rate. Prometheus Gauges are the
   correct instrument. The challenger explicitly recommended this (`challenge.md:121-125`).
   The synthesis also leaned Gauge (`synthesis.md:147`).

4. **`rate()` is not needed.** This is a local single-user server. The ingest runs at most
   once daily. The operator wants to know "did the last run succeed and how big was it" —
   a panel showing `arxmcp_ingest_last_run_papers` is sufficient. `rate()` over a
   once-daily counter is not operationally useful.

**Resulting metric names (note-08 must be updated):**

```
arxmcp_ingest_last_run_papers{driver}       gauge  (replaces _papers_processed_total)
arxmcp_ingest_last_run_chunks{driver}       gauge  (replaces _chunks_written_total)
```

The `{driver}` label (`bulk_ingest` | `oai_delta`) lets the operator distinguish runs.
The label is populated from `ingest-summary.json["driver"]`.

`arxmcp_ingest_oai_pmh_lag_seconds` stays as-is (gauge — correctly named already).
`arxmcp_ingest_paper_duration_seconds` is a future concern; not in e3 scope.

**Note-08 update required:** The `counter` annotation on the two `_total` families must
be replaced with `gauge` + the new family names. This is a deliberate deviation from
the note-08 draft, justified by the process-exit reality that makes Counter semantics
unsafe here. The update is a ~3-line diff to the note.

**Hybrid (YAGNI verdict):** A sentinel with BOTH a per-run snapshot AND a since-forever
cumulative is not worth the schema cost. The since-forever cumulative requires an
additional state-file write on every run (another atomic write with its own failure
modes), a reader that merges two files, and test coverage for the backward-step guard.
For a once-daily local cron on a single-user server, this is pure overhead. Reject.

---

## 4. e3 resize verdict

**Size: M (not M+, not S).**

The writer side is net-new (CAND-7 challenger was correct that the estimate was too low
for S). The reader side reuses the established pattern with minimal new code. The scope
is bounded: two drivers (bulk + delta), one new module, one gauge pair, one note-08
update.

**Implementation surface:**

| File | Change |
|---|---|
| `ingest/store.py` | Add `paper_id: str = ""` + `total_rows_after_commit: int = 0` to `WriteStats`; update `to_dict()`; propagate from `write_chunks` (CAND-8). Keep `chunk_count` as deprecated alias per challenger rec. |
| `ingest/bulk_ingest.py` | After `run_bulk_ingest` loop: call `_write_ingest_summary(path, payload)` |
| `ingest/oai_delta.py` | After `run_delta` success path: call `_write_ingest_summary(path, payload)` |
| `ingest/ingest_summary.py` | New: `write_ingest_summary(ops_dir, driver, summary)` with atomic write |
| `server/metrics.py` | Add `INGEST_PAPERS_LAST_RUN_GAUGE` + `INGEST_CHUNKS_LAST_RUN_GAUGE` (Gauge, label `driver`) |
| `server/health.py` | Extend `refresh_sentinel_metrics` with `ingest-summary.json` reader; add `_INGEST_SUMMARY_NAME` constant at top |
| `.claude/notes/08-security-observability-ops.md` | Replace `_total` Counter families with gauge names |
| `tests/test_ingest_summary.py` | New: writer tests (happy path, missing ops_dir, atomic write) |
| `tests/test_server_sentinel_metrics.py` (or extend existing) | New cases: present+valid, absent, oversized, malformed |

**Estimated LOC:** ~150 (50 writer + 40 reader + 60 tests). That is comfortably M.

**Safe to commit?** Yes, with one pre-condition: corpus-integrity-observability-m1 has
shipped (`store.py:931` already calls `tbl.count_rows()` inside `write_chunks`), so
`total_rows_after_commit` can be threaded through `WriteStats` with zero extra I/O.
The CAND-1 sequencing dependency is satisfied.

---

## 5. Open questions

**None blocking implementation.** The counter-vs-gauge decision is locked. The schema
is fully specified. The writer placement is clear (end of `run_bulk_ingest` /
`run_delta` after the success path). One advisory note:

- The e3 brief says the families should be `arxmcp_ingest_papers_processed_total` /
  `arxmcp_ingest_chunks_written_total` (note-08 names). The implementer must update
  note-08 to use the new gauge names BEFORE wiring the Prometheus objects, to avoid
  a situation where the brief and the code diverge immediately. The note-08 update
  is part of the e3 work, not post-hoc cleanup.

---

## 6. External writes the e3 implementation will require

None. This milestone is purely local:
- No git push beyond the normal three-commit pattern.
- No GitHub issues or PRs.
- No infra mutations (no new Docker service, no cron change, no restic scope change).
- No third-party API calls.

The `ingest-summary.json` sentinel is a local file under `var/arxmcp/ops/` (gitignored).
