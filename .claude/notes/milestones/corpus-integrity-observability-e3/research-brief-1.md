# Research Brief — corpus-integrity-observability-e3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T15:10:00Z

---

## In-codebase context

### Spike verification — design still maps to current code

**All spike touch points verified against current HEAD. Line numbers have shifted
but the structural patterns are intact. Details per touch point:**

---

#### 1. `server/health.py::refresh_sentinel_metrics` — CURRENT structure

`refresh_sentinel_metrics` is at **`server/health.py:558`** (was documented at :342 in the
spike; shifted +216 lines due to `notebook-ops-hardening-m4` `/status` block insertion).

Current function signature and pattern (lines 558–658):
```python
def refresh_sentinel_metrics(ops_dir: Path) -> None:
    from server.metrics import (
        BACKUP_LAST_SUCCESS_GAUGE,
        BACKUP_STATUS_GAUGE,
        DELTA_TIMEOUT_ACTIVE_GAUGE,
        EVAL_QUARANTINE_ACTIVE_GAUGE,
        LATEXML_DRIFT_DETECTED_GAUGE,
    )
    # --- drift-detected.flag, eval-quarantine.flag, delta-timeout.flag ---
    # --- backup-status.json → BACKUP_LAST_SUCCESS + BACKUP_STATUS --------
    # --- eval-reports/corpus_v<N>-*.json → EVAL_NDCG5_GAUGE --------------
```

The `backup-status.json` reader block is the **template to mirror** for the new
`ingest-summary.json` reader (lines 606–652). It follows exactly the pattern the
spike describes:
- `_read_capped(backup_status)` called on a file handle (`ops_dir / _BACKUP_STATUS_NAME`)
- `json.loads(raw) if raw is not None else None` (oversized → None → leave prior)
- per-field `payload.get(...)` with fallback
- `except (json.JSONDecodeError, OSError, ValueError): logger.warning(... exc_info=True)`
- `else: gauge.set(0.0)` on absence

**`_read_capped`** is at **`server/health.py:660`** (shifted from :444-470 in spike).
Current signature and guard:
```python
# health.py:676
if size > _MAX_SENTINEL_BYTES:
    logger.warning(...)
    return None
return path.read_text(encoding="utf-8")
```
`_MAX_SENTINEL_BYTES = 64 * 1024` is at **`server/health.py:85`** (unchanged). The
64 KB guard is intact.

**Sentinel name constants** are at **lines 60–64**:
```python
_DRIFT_FLAG_NAME: str = "drift-detected.flag"
_QUARANTINE_FLAG_NAME: str = "eval-quarantine.flag"
_DELTA_TIMEOUT_FLAG_NAME: str = "delta-timeout.flag"
_BACKUP_STATUS_NAME: str = "backup-status.json"
_EVAL_REPORTS_DIR: str = "eval-reports"
```

`_INGEST_SUMMARY_NAME: str = "ingest-summary.json"` **goes here at line ~65** (after
`_BACKUP_STATUS_NAME`). The new reader block inserts at the **end** of
`refresh_sentinel_metrics`, before the `eval-reports` block or after
`backup-status.json` — either is valid; after `backup-status.json` mirrors the
documented sentinel order.

---

#### 2. Where do the new Prometheus gauges live? — `server/metrics.py` (CONFIRMED)

The spike's `decision.md` says "gauges go in `server/metrics.py`". **This is correct.**

**Key finding:** `CORPUS_VERSION_GAUGE`, `CORPUS_CHUNK_COUNT_MARKER`, and
`CORPUS_CHUNK_COUNT_ACTUAL` are defined in **`server/health.py`** (lines 92–119) —
these are startup-set gauges that live in the same module as the startup logic.

However, ALL sentinel-bridged gauges (populated at scrape time, not startup) already
live in **`server/metrics.py`**:
- `LATEXML_DRIFT_DETECTED_GAUGE` — `metrics.py:199`
- `EVAL_NDCG5_GAUGE` — `metrics.py:221`
- `EVAL_QUARANTINE_ACTIVE_GAUGE` — `metrics.py:237`
- `DELTA_TIMEOUT_ACTIVE_GAUGE` — `metrics.py:248`
- `BACKUP_LAST_SUCCESS_GAUGE` — `metrics.py:260`
- `BACKUP_STATUS_GAUGE` — `metrics.py:271`

The three new ingest gauges (`INGEST_LAST_RUN_PAPERS`, `INGEST_LAST_RUN_CHUNKS`,
`INGEST_LAST_RUN_TIMESTAMP`) are also sentinel-bridged (populated at scrape time from
`ingest-summary.json`) and **MUST go in `server/metrics.py`**, NOT `server/health.py`.
The late import in `refresh_sentinel_metrics` (`from server.metrics import ...`) is the
established pattern — add the three new names to that import block.

**Recommendation:** place the three new gauge definitions in `server/metrics.py` after
`BACKUP_STATUS_GAUGE` (line ~278). Add them to `reset_sentinel_metrics_for_tests()` and
`__all__`.

---

#### 3. `ingest/store.py::WriteStats` — CURRENT fields + write_chunks seam

`WriteStats` is at **`store.py:173–204`**. Current fields (verbatim):
```python
chunk_count: int = 0
elapsed_s: float = 0.0
lancedb_version: int = 0
rows_inserted: int = 0
rows_updated: int = 0
indices_created: dict[str, bool] = field(default_factory=dict)
```

`to_dict()` at **`store.py:196–204`** exists and returns these 6 fields.

The m1 `count_rows()` call is at **`store.py:931`** (`chunk_count = tbl.count_rows()`).
`paper_id` is available as a direct argument to `write_chunks`.

**CAND-8 additions:** add `paper_id: str = ""` and `total_rows_after_commit: int = 0`
to `WriteStats` + `to_dict()`. Populate `total_rows_after_commit` from the existing
`chunk_count` local variable (already = `tbl.count_rows()`) and `paper_id` from the
`write_chunks` argument — both at lines 930–943 (the marker-write block).

**Decision-vs-research.md discrepancy on `chunk_count`:** `research.md:317` says
"Keep `chunk_count` as deprecated alias per challenger rec." `decision.md` does NOT
repeat this recommendation. The implementer should keep `chunk_count` as-is (no alias,
no deprecation) — it's a separate per-batch counter serving a different purpose.
Do NOT rename or alias it; just ADD the two new fields.

---

#### 4. `ingest/bulk_ingest.py::run_bulk_ingest` — end-of-run seam

`run_bulk_ingest` is at **`bulk_ingest.py:338`**, returns `IngestSummary` at line 397:
```python
summary.elapsed_seconds = time.monotonic() - started
return summary  # ← write_ingest_summary goes BEFORE this return
```

`IngestSummary` fields (lines 114–123): `papers_total`, `papers_succeeded`,
`papers_failed`, `papers_skipped`, `ar5iv_hits`, `ar5iv_misses`, `elapsed_seconds`.
`papers_skipped` is in `IngestSummary` but NOT in the spike's mapping — it does NOT
appear in the `ingest-summary.json` v1 schema. Include only the v1 schema fields.

**`chunks_written_this_run`** is NOT directly available from `IngestSummary`. The
implementer must accumulate it from `WriteStats.rows_inserted + rows_updated` across
the loop, or read `outcome.chunks_written` (available on `PaperIngestOutcome` at
`bulk_ingest.py:108`) per paper. Simplest: accumulate a `chunks_written = 0` running
total inside `run_bulk_ingest`, incrementing by `outcome.chunks_written` each iteration
(already available). Then pass `chunks_written` to `write_ingest_summary`.

---

#### 5. `ingest/oai_delta.py::run_delta` — end-of-run seam

`run_delta` is at **`oai_delta.py:677`**. The success-path sentinel write happens at
**line 824** (`_write_state(state_path, final_state)`). The `write_ingest_summary` call
goes **AFTER** `_write_state` and **BEFORE** `return summary` (line 826):

```python
_write_state(state_path, final_state)
# ← write_ingest_summary() here
return summary
```

`DeltaSummary` fields (lines 185–194): `sets_harvested`, `records_total`,
`records_deleted`, `records_ingested`, `records_failed`, `pages_fetched`,
`elapsed_seconds`, `budget_breached`.

Field mapping to v1 schema:
- `papers_processed` ← `summary.records_total`
- `papers_succeeded` ← `summary.records_ingested`
- `papers_failed` ← `summary.records_failed`
- `chunks_written_this_run` — NOT in `DeltaSummary`; must be accumulated inside
  `run_delta`'s per-record loop from `write_chunks` outcomes. The simplest approach:
  add a `chunks_written` accumulator in the loop where `records_ingested` is
  incremented (lines ~796–801), threading `WriteStats.rows_inserted + rows_updated`.
- `total_rows_after_commit` — from the last `WriteStats.total_rows_after_commit` seen
  in the loop (after CAND-8 lands).

**Atomic write pattern:** `_write_state` at **`oai_delta.py:216–224`** is the canonical:
```python
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(state, ...) + "\n", encoding="utf-8")
tmp.replace(path)
```
The new `write_ingest_summary` in `ingest/ingest_summary.py` MUST use the same pattern.

---

#### 6. `tools/daily_metrics_report.py` — Ingestion throughput stub

The current stub is at **`daily_metrics_report.py:421–431`** (verbatim):
```python
# --- Ingestion throughput (TODO — metrics not yet emitted) -----------
lines.append("## Ingestion throughput")
lines.append("")
lines.append(
    "_Papers ingested + chunks written are not yet exposed via "
    "`/metrics`; the families `arxmcp_ingest_papers_processed_total` "
    "and `arxmcp_ingest_chunks_written_total` are named in note 08 "
    "but no emitter exists yet. See `var/arxmcp/ops/delta-status.json` "
    "for the most-recent delta run summary, or "
    "`docs/ops/delta-loop.md` for the operator workflow._"
)
```

The `_sentinel_gauge` helper is at **line 488**:
```python
def _sentinel_gauge(fams: dict[str, object], name: str) -> float:
    fam = fams.get(name)
    if fam is None:
        return float("nan")
    for s in fam.samples:
        if s.name == name:
            return float(s.value)
    return float("nan")
```

The e2 "Corpus integrity" row (lines ~390–419) is the pattern to mirror — it calls
`_sentinel_gauge` three times and renders a Markdown table with a conditional
divergence flag. The new Ingestion-throughput row replaces the TODO stub with:
`_sentinel_gauge(fams, "arxmcp_ingest_last_run_papers")`,
`_sentinel_gauge(fams, "arxmcp_ingest_last_run_chunks")`,
`_sentinel_gauge(fams, "arxmcp_ingest_last_run_timestamp_seconds")`.
The `driver` field is in `ingest-summary.json` but NOT exposed as a Prometheus gauge
(unlabeled decision); the report reads `driver` from the sentinel file directly — or
renders "n/a" when the sentinel is absent.

---

### note-08 lines to replace

From `.claude/notes/08-security-observability-ops.md:131–138` (verbatim):
```
Ingestion (separate process; same metrics endpoint pattern):

arxmcp_ingest_papers_processed_total{parser,outcome}    counter
arxmcp_ingest_paper_duration_seconds{parser,quantile}   summary
arxmcp_ingest_chunks_written_total                      counter
arxmcp_ingest_oai_pmh_lag_seconds                       gauge
```

The implementer replaces lines 134 and 136 with the locked gauge names:
```
arxmcp_ingest_last_run_papers         gauge  (replaces _papers_processed_total)
arxmcp_ingest_last_run_chunks         gauge  (replaces _chunks_written_total)
arxmcp_ingest_last_run_timestamp_seconds  gauge  (freshness)
```
`arxmcp_ingest_paper_duration_seconds` (summary) and `arxmcp_ingest_oai_pmh_lag_seconds`
(gauge) are unchanged; they remain in the block. The note-08 update is a ~5-line diff.

---

## Prior decisions and lessons

### CRITICAL: `server/health.py` has UNCOMMITTED EDITS

**`git status --short server/health.py` output: `M server/health.py`**

The uncommitted changes are from `notebook-ops-hardening-m4` — specifically the new
`/status` endpoint and `compute_health_status()` function (~222 lines inserted after
line 261). These changes DO NOT touch `refresh_sentinel_metrics`, `_read_capped`,
or any sentinel-reading logic.

**Action required:** the implementer must verify that `notebook-ops-hardening-m4`
is committed (or that its changes are still uncommitted and need to be committed first)
BEFORE adding the e3 implementation to `server/health.py`. Committing two milestones'
changes in one commit violates the three-commit-per-milestone pattern. The implementer
should confirm whether these edits should land in a separate m4 commit first.

### research.md vs. decision.md: `{driver}` label conflict

**`research.md:285`** recommended `arxmcp_ingest_last_run_papers{driver}` with a
`{driver}` label. **`decision.md` (Decision 2)** explicitly overrides this:
> "**do NOT add a `{driver}` Prometheus label**... Keep the gauges unlabeled; carry
> `driver` as a JSON field surfaced in the daily-report row only."

The implementer follows **`decision.md`** (locked). Gauges are **unlabeled scalar
gauges**. Any `{driver}` label seen in the spike research materials is superseded.

### e2 shipped cleanly (state: complete, 4 findings closed)

e2 landed in commit `4706ecf` (feat) + `f962d62` (rect). It added `CORPUS_CHUNK_COUNT_MARKER`,
`CORPUS_CHUNK_COUNT_ACTUAL` gauges in `health.py`, the `/readyz` body enrichment, and
structured logging. The daily report's corpus-integrity row is now live. The Ingestion
throughput section remains a TODO stub — confirmed above.

### `ingest/ingest_summary.py` does not exist yet

Grepped the entire repo: no `write_ingest_summary` call, no `ingest_summary` module.
The new module is fully net-new.

### `ops_dir` path in ingest drivers

Ingest drivers (`bulk_ingest.py`, `oai_delta.py`) do NOT import `server/config.py`.
They hardcode paths as `REPO_ROOT / "var" / "arxmcp" / "ops" / ...` module-level
constants. The `ingest/ingest_summary.py` writer must accept `ops_dir: Path` as an
argument (callers pass the hardcoded path); `server/health.py`'s reader receives
`ops_dir` from `config.ops_dir` at scrape time. Both resolve to the same directory.

### `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` — UNCHANGED

This milestone adds NO MCP tool (confirmed: no `ALL_TOOLS` change, no `prompts.py`
change). Both hashes stay frozen. Do NOT run `--update-tool-schema-hash`.

---

## External sources

Not relevant to this milestone. The implementation is purely local:
- No MCP spec changes (no new tool).
- No Anthropic prompt-caching changes (no new cache breakpoint).
- No third-party API calls.

Note-07 was reviewed; the cache byte-stability concern does not apply here — this
milestone writes no new tool schema and no new prompt prefix.

---

## Recommendation

Implement e3 VERBATIM per `decision.md`, with two sequencing notes:

1. **Resolve `server/health.py` uncommitted state first.** Confirm whether the
   `notebook-ops-hardening-m4` changes (222+ lines of `/status` endpoint code) in the
   working tree belong in a preceding commit. If they do, commit them as a separate
   m4 feat commit before starting e3 implementation. Do not mix the two milestones.

2. **New gauges go in `server/metrics.py`, NOT `server/health.py`.** All existing
   sentinel-bridged scrape-time gauges live in `server/metrics.py`; the three ingest
   gauges follow the same pattern. Add them after `BACKUP_STATUS_GAUGE` (~line 278),
   add to `reset_sentinel_metrics_for_tests()` and `__all__`.

3. **`report driver` from sentinel file directly in `daily_metrics_report.py`** — not
   as a Prometheus gauge. The report reads `ingest-summary.json` directly (like the
   existing `_backup_status_active_state` helper reads `backup-status.json`), or calls
   a new `_ingest_summary_driver(ops_dir)` helper that returns the driver string.
   Alternatively, read the file in the report function's scrape path and render n/a when
   absent. Do not add a `{driver}` Prometheus label.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one advisory from `decision.md §"Open questions"` is already resolved: note-08 update
is part of e3 and must happen BEFORE wiring the Prometheus objects (so brief and code
never diverge). This is captured above.

---

## External writes the implementation will require

None — this milestone is purely local.

| Type | Target | Why |
|---|---|---|
| (none) | — | `ingest-summary.json` is a local sentinel under `var/arxmcp/ops/` (gitignored). No git push beyond the normal three-commit pattern. No GitHub issues, PRs, or infra mutations. |
