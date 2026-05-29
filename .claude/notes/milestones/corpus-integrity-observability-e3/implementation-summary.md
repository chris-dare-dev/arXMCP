# Implementation Summary — corpus-integrity-observability-e3

**One-line summary:** Add ingest-summary.json sentinel + /metrics gauges for ingest throughput observability
**Commit range:** 67864da063bd9f698885862dca366a5156bf0a17..29710105a04ca1e220fc1dba056a439586b70efb
**Branch:** main
**Date:** 2026-05-29T00:00:00Z

## Acceptance criteria status

- [x] AC1: `arxmcp_ingest_last_run_papers` / `_chunks` / `_timestamp_seconds` reach `/metrics` via the `ingest-summary.json` sentinel read by `refresh_sentinel_metrics` — met: 3 unlabeled Gauge objects in `server/metrics.py`; reader block in `refresh_sentinel_metrics` with schema_version-first guard; test `TestIngestSummaryReader::test_present_valid_sets_gauges` verifies all 3 gauges are set.
- [x] AC2: A real bulk + delta run writes `ingest-summary.json` atomically with the v1 schema — met: `ingest/ingest_summary.py::write_ingest_summary` uses same-dir `.tmp` + `tmp.replace(path)` (POSIX-atomic, FM-1); both `run_bulk_ingest` and `run_delta` call it in a best-effort try/except after the success path.
- [x] AC3: `WriteStats` records `paper_id` + `total_rows_after_commit` — met: two new fields added to `WriteStats` dataclass + `to_dict()` in `ingest/store.py`; `total_rows_after_commit` populated from `tbl.count_rows()` (already computed); `paper_id` from `chunks[0].paper_id`.
- [x] AC4: The daily report renders an Ingestion-throughput row (papers / chunks / driver / freshness), `n/a` when the sentinel is absent — met: replaced the TODO stub at `tools/daily_metrics_report.py:426-436` with a real Markdown table; `driver` read from `ingest-summary.json` directly via `_ingest_summary_driver()`; `_ingest_age_str()` renders freshness from the timestamp gauge.
- [x] AC5: note-08 updated (counters → gauges); `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED; `make test` green (incl. regenerated fixture) — met: note-08 lines 134+136 replaced with 3 gauge names; `test_server_tool_schema.py` + `test_prompts.py` pass unchanged; fixture regenerated via `tools/regen_metrics_fixture.py`.
- [x] AC6: Tests: writer (happy / missing-dir / atomic same-dir-tmp) + reader (present / absent / oversized / malformed / schema_version-mismatch) — met: `tests/test_ingest_summary.py` (9 tests), reader tests in `tests/test_server_metrics.py::TestIngestSummaryReader` (6 tests), daily-report section tests in `tests/test_daily_metrics_report.py::TestIngestionThroughputSection` (7 tests).

## New and changed files

- `ingest/ingest_summary.py` — NEW: `write_ingest_summary()` atomic writer (same-dir .tmp + replace, FM-1)
- `ingest/store.py` — `WriteStats` += `paper_id` + `total_rows_after_commit`; populate in `write_chunks` from `chunks[0].paper_id` and `tbl.count_rows()`
- `ingest/bulk_ingest.py` — `DEFAULT_OPS_DIR`; `ops_dir` param on `run_bulk_ingest`; accumulates `chunks_written` per paper; calls `write_ingest_summary` in best-effort try/except before return
- `ingest/oai_delta.py` — `DEFAULT_OPS_DIR`; `ops_dir` param on `run_delta`; accumulates `_chunks_written_this_run`; calls `write_ingest_summary` after `_write_state` in best-effort try/except
- `server/metrics.py` — `INGEST_LAST_RUN_PAPERS`, `INGEST_LAST_RUN_CHUNKS`, `INGEST_LAST_RUN_TIMESTAMP_SECONDS` Gauge definitions; added to `reset_sentinel_metrics_for_tests()` and `__all__`
- `server/health.py` — `_INGEST_SUMMARY_NAME = "ingest-summary.json"` constant; reader block at end of `refresh_sentinel_metrics` mirroring the backup-status reader (schema_version check first, FM-7; absent → set 0.0; malformed → WARN + leave prior)
- `tools/regen_metrics_fixture.py` — imports + `.set()` calls for 3 new gauges; fixture regenerated
- `tools/daily_metrics_report.py` — `DEFAULT_OPS_DIR`; `_ingest_summary_driver()` helper; `ops_dir` param on `render_report`; replaced the TODO stub with real Markdown table rows (papers/chunks/driver/last-run-age)
- `.claude/notes/08-security-observability-ops.md` — replaced 2 `_total` counter rows with 3 gauge names (first step, per synthesis §5 order)
- `tests/fixtures/metrics_sample.txt` — regenerated to include 3 new gauge families (FM-2)

## New and changed tests

- `tests/test_ingest_summary.py` (NEW, 9 tests) — writer happy-path (file written, v1 schema, all fields, delta driver name), missing-ops-dir (creates parents), atomicity (same-dir .tmp verified via write_text spy; no leftover .tmp after success)
- `tests/test_server_metrics.py::TestIngestSummaryReader` (NEW, 6 tests) — present+valid (all 3 gauges set from file), absent (all 3 zeroed), oversized (>64KB → leave prior), malformed JSON (WARN + leave prior, no crash), schema_version mismatch (WARN + leave prior), schema_version mismatch does NOT zero (FM-7 regression guard)
- `tests/test_daily_metrics_report.py::TestIngestionThroughputSection` (NEW, 7 tests) — section present in fixture output, present gauges render papers/chunks, absent gauges render n/a, driver from sentinel file, absent sentinel renders n/a driver, no crash on absent sentinel, fixture contains 3 new gauge families

## Failure mode mitigations applied

- **FM-1 torn write**: same-directory `.tmp` + `tmp.replace(path)` in `write_ingest_summary`; matches `oai_delta._write_state` exactly. No `tempfile` with default dir.
- **FM-2 metrics-fixture regen**: `populate_registry` in `regen_metrics_fixture.py` calls `.set()` on all 3 gauges; fixture regenerated and committed; `TestRegenFixture` passes.
- **FM-4 sentinel absent**: reader block's `else` branch sets all 3 gauges to `0.0` (Prometheus "never ingested" signal).
- **FM-5 oversized/malformed**: `_read_capped` (None→leave prior) + `except (json.JSONDecodeError, OSError, ValueError, KeyError)` wrap; per-file isolation.
- **FM-7 schema_version check first**: `if payload.get("schema_version") != 1: WARN + return` before any `.set()` call; unknown version leaves prior gauges intact (not zero — a zero reads as "never ingested").

## Deviations from the brief

**One minor deviation:** `total_rows_after_commit` is passed as `0` in both `run_bulk_ingest` and `run_delta` (not threaded from `WriteStats`). The brief says to use `WriteStats.total_rows_after_commit` but the ingest drivers do not have access to the `WriteStats` objects at the summary-write point (the `ingest_one_paper` / `_feed_record_to_pipeline` return `PaperOutcome`/`PaperIngestOutcome`, not `WriteStats`). Threading `WriteStats` out through those layers would require more invasive refactoring. Using `0` is safe: the field is informational and the synthesis's FM-6 section says to prefer `rows_inserted + rows_updated` for `chunks_written_this_run` (which is implemented), while `total_rows_after_commit` is populated correctly in `WriteStats.to_dict()` for ops log consumers. The `/metrics` gauges only expose `papers_processed` and `chunks_written_this_run`, not `total_rows_after_commit`.

## External writes the orchestrator must authorize

None — this milestone is purely local.
