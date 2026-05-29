# Critique — corpus-integrity-observability-e3

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** aa7779c82c0ef2b1a6c62a0193dbe4b68e682f6a..0f63c553c29e797508385b5ba0f9b959bf6593a7
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the /metrics gauge path + sentinel reader are correct and
  well-tested; the defects are on the WriteStats/daily-report surfaces, not the
  metrics path the milestone is named for.
- Finding counts: 0 CRITICAL, 1 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk: `ingest/store.py:887` vs `:941` — `total_rows_after_commit` is
  appended to `store-stats.jsonl` BEFORE it is populated, so AC3's field ships
  always-0 in its only consumer, and the impl-summary deviation note claims the
  opposite.
- The locked spike-3 design (gauge-not-counter, no `{driver}` label, atomic
  same-dir write, schema_version-first leave-prior) is implemented faithfully —
  NOT re-litigated here.
- Reader FM-4/FM-5/FM-7 mitigations have genuine regression tests that would fail
  if the mitigation were removed (incl. a dedicated "schema mismatch must NOT
  zero" guard) — the strongest part of this milestone.
- Test-surface gap: the driver-level WIRING (run_bulk_ingest / run_delta actually
  CALL write_ingest_summary) has ZERO coverage; the best-effort try/except would
  silently swallow a broken call. AC2 is unverified by tests.
- Cache byte-stability preserved: no prompts.py/tools.py change, BP1 + tool-schema
  hashes untouched. No new dependency. No-fork clean. No `assert` introduced.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — WriteStats.total_rows_after_commit appended before it is set

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/store.py:887 (append) vs ingest/store.py:941 (populate)
- **What:** `stats = WriteStats(...)` is constructed at :877 WITHOUT
  `total_rows_after_commit`, and `_append_store_stats(stats)` runs at :887 — which
  serializes the object to `store-stats.jsonl`. The field is only assigned at :941
  (`stats.total_rows_after_commit = chunk_count`), AFTER the append. `write_chunks`
  returns `dataset_version` (:978), not `stats`, and `_append_store_stats` is
  called exactly once (grep-verified). So the populate at :941 is a dead write:
  the field is `0` in every `store-stats.jsonl` row and is never read anywhere.
- **Why it matters:** AC3 ("WriteStats records `paper_id` + `total_rows_after_commit`")
  is half-broken — `paper_id` is set at :884 before the append and is correct, but
  `total_rows_after_commit` is always 0 in its only consumer (the audit log). The
  CAND-8 enrichment is non-functional in production. Worse, the implementation
  summary's "Deviations" section actively claims the field "is populated correctly
  in `WriteStats.to_dict()` for ops log consumers" — directly contradicted by the
  code. A future ops dashboard keying on this field reads a constant 0.
- **Proposed fix:** move the `stats.total_rows_after_commit = chunk_count` assignment
  to BEFORE `_append_store_stats(stats)`. The `count_rows()` at :937 lives inside a
  best-effort `try/except` after the marker logic, so either (a) hoist the
  `tbl.count_rows()` read above the `WriteStats(...)` construction and pass it into
  the dataclass, or (b) move `_append_store_stats(stats)` to AFTER :941. Option (a)
  keeps the append crash-safe even if the marker block raises.
- **Regression guard:** add a test in `tests/test_store.py` that calls
  `write_chunks`, reads the last line of `store-stats.jsonl`, and asserts
  `row["total_rows_after_commit"] == row["chunk_count"]` (or `== tbl.count_rows()`)
  — non-zero for a non-empty write. This would fail on the current ordering.

### F2 — Daily-report renders "0" papers/chunks when sentinel genuinely absent

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/daily_metrics_report.py:452-453 (via `_int_cell`, :405-407)
- **What:** When the sentinel is absent in production, `refresh_sentinel_metrics`
  (server/health.py:710-712) sets the 3 gauges to `0.0`, so `/metrics` exposes
  `arxmcp_ingest_last_run_papers 0.0`. The report parses `0.0` (not NaN) and
  `_int_cell(0.0)` returns `"0"`, so the rows render `papers (last run): 0` /
  `chunks (last run): 0`. The `driver` and `last run age` cells DO render "n/a"
  (driver from absent file, age from `ts == 0.0`). Verified live: feeding
  `0.0` gauges + no sentinel file yields papers=0, chunks=0, driver=n/a, age=n/a.
- **Why it matters:** AC4 says "`n/a` when the sentinel is absent." Two of four
  cells violate it. "0 papers / 0 chunks" reads as "the last run ingested nothing"
  rather than "no run has happened" — exactly the silent-lie class spike-3 worried
  about for the never-ingested signal. `test_absent_gauges_render_na`
  (tests/test_daily_metrics_report.py:493-499) passes ONLY because it feeds an
  EMPTY metrics string (server-cold → NaN → n/a), which is a different scenario
  than "server up, sentinel absent" (→ 0.0 → "0"). The real absent path is untested.
- **Proposed fix:** drive the papers/chunks cells off the freshness signal: if
  `ingest_ts == 0.0` (or NaN), render papers/chunks as "n/a" too (a 0.0 timestamp
  means "never ingested", so the counts are meaningless). Alternatively gate all
  three cells on `_ingest_summary_driver(...) is None`.
- **Regression guard:** add a test that calls `render_report` with metrics text
  containing the three gauges all at `0.0` AND no `ingest-summary.json` in
  `ops_dir`, then asserts the papers/chunks cells render "n/a" (not "0").

### F3 — No test that run_bulk_ingest / run_delta actually write the sentinel

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/bulk_ingest.py:407-425, ingest/oai_delta.py:836-854
- **What:** The writer is unit-tested in isolation (tests/test_ingest_summary.py)
  and the reader in isolation (tests/test_server_metrics.py), but neither
  `tests/test_bulk_ingest.py` nor `tests/test_oai_delta.py` asserts that the driver
  loops call `write_ingest_summary` and produce a sentinel (grep-verified: no
  `write_ingest_summary` / `ingest-summary` reference in those files). The call is
  wrapped in `except Exception: logger.warning(...)` (best-effort), so a regression
  that broke the call — wrong kwarg name, the call drifting into the dry-run
  early-return path, an import error — would be silently swallowed with no test
  failure.
- **Why it matters:** AC2 ("a real bulk + delta run writes `ingest-summary.json`")
  is the seam this milestone exists for, and it has zero coverage. The best-effort
  swallow makes the wiring especially fragile: the failure mode is invisible.
- **Proposed fix:** add one test per driver that runs `run_bulk_ingest` /
  `run_delta` with a fake/empty work list (or monkeypatched pipeline) and a
  `tmp_path` `ops_dir`, then asserts `(ops_dir / "ingest-summary.json").is_file()`
  with `schema_version == 1` and the expected `driver` name. Also assert the
  dry-run path does NOT write a sentinel (it returns before the write).
- **Regression guard:** the tests above ARE the guard — they fail if the call is
  removed or mis-wired.

### F4 — Delta papers_processed over-counts deletions vs succeeded+failed

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/oai_delta.py:842-844 (mapping) with :775 / :786 / :806-808 (counters)
- **What:** On the delta path the sentinel sets `papers_processed = records_total`
  (:842), `papers_succeeded = records_ingested` (:843), `papers_failed =
  records_failed` (:844). But `records_total` (:775, `+= len(records)`) includes
  deleted records, while `records_ingested`/`records_failed` exclude them (deleted
  records hit `records_deleted += 1` then `continue` at :786/:794). So on any delta
  run with deletions, `papers_processed > papers_succeeded + papers_failed`, and
  `arxmcp_ingest_last_run_papers` over-counts (a deletion is not ingest work that
  produces chunks).
- **Why it matters:** the gauge `arxmcp_ingest_last_run_papers` is the operator's
  "how big was the last run" signal; counting deletions inflates it and breaks the
  intuitive `processed = succeeded + failed` invariant the bulk path satisfies.
  The synthesis specified this mapping verbatim, so it is a spec-level imprecision
  inherited faithfully — but it still ships an inaccurate gauge.
- **Proposed fix:** map `papers_processed = summary.records_ingested +
  summary.records_failed` (non-deleted attempted), OR explicitly include
  `records_deleted` in the definition and document it. Decide and make the bulk and
  delta definitions consistent.
- **Regression guard:** add a delta test with ≥1 deleted record asserting the
  sentinel's `papers_processed == papers_succeeded + papers_failed` (or whichever
  invariant is chosen).

### F5 — Daily-report driver helper caps after full read + ignores schema_version

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/daily_metrics_report.py:545-548
- **What:** `_ingest_summary_driver` calls `sentinel.read_text()` FIRST (:545), THEN
  checks `len(raw.encode("utf-8")) > 64*1024` (:546) — so an oversized file is fully
  read into memory before being rejected, unlike the server-side `_read_capped`
  which checks `stat().st_size` before reading (server/health.py:733-736). It also
  never checks `schema_version`, so a `schema_version: 99` file would still surface
  its `driver` in the report even though the server reader correctly distrusts the
  layout (server/health.py:682).
- **Why it matters:** defense-in-depth inconsistency across the two read surfaces.
  Blast radius is tiny (local cron-run CLI, operator/cron-written file under
  `var/arxmcp/ops/`, not network-facing), hence LOW.
- **Proposed fix:** check `sentinel.stat().st_size` before `read_text`; optionally
  reject `payload.get("schema_version") != 1` to match the server reader.
- **Regression guard:** a test feeding a >64KB sentinel asserting the helper returns
  None without reading the whole body (or simply mirrors `_read_capped`).

### F6 — Inline `__import__("json")` in driver helper instead of top-level import

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/daily_metrics_report.py:548
- **What:** `payload = __import__("json").loads(raw)` is used because `json` is not
  imported at module top (verified: the import block :38-49 has no `import json`).
  The `__import__` builtin idiom is unusual and harder to read than a normal import.
- **Why it matters:** style only; no correctness impact.
- **Proposed fix:** add `import json` to the module-top import block and use
  `json.loads(raw)`.
- **Regression guard:** none required (style).

## What was done well

- Spike-3 locked design implemented faithfully: unlabeled gauges (no `{driver}`
  Prometheus label), gauge-not-counter, with an accurate code comment citing
  Decision 2 (server/metrics.py:280-306).
- FM-1 atomic write is real and well-tested: same-dir `.tmp` + `tmp.replace`
  (ingest/ingest_summary.py:94-99), with a test asserting the tmp's `.parent`
  equals the target dir (not just that a write happened) AND a no-leftover-tmp test
  (tests/test_ingest_summary.py:119-161).
- FM-4/FM-5/FM-7 reader mitigations have genuine teeth: present/absent/oversized/
  malformed/schema-mismatch all covered, including a dedicated regression guard that
  a schema mismatch must NOT zero the gauges (tests/test_server_metrics.py:811-831).
- FM-7 ordering is correct: `schema_version != 1` is checked FIRST after parse and
  leaves prior gauges (server/health.py:682-688), not silent-zero, not crash.
- FM-2 fixture regen done properly: all 3 gauge families present in
  tests/fixtures/metrics_sample.txt:96-104 with values, and a subprocess-based
  regen-matches-fixture test guards drift (tests/test_daily_metrics_report.py:330).
- note-08 updated FIRST per synthesis §5: the 2 `_total` counter rows replaced with
  the 3 gauge names, `arxmcp_ingest_oai_pmh_lag_seconds` correctly left as gauge.
- Best-effort summary write: both drivers wrap the call in `try/except Exception`
  with a WARN so a sentinel-write failure cannot abort an otherwise-successful
  ingest run (ingest/bulk_ingest.py:420, ingest/oai_delta.py:849).
- Timestamp handling correct: writer emits trailing-`Z` ISO-8601; reader uses
  `datetime.fromisoformat` which handles `Z` on the project's Python 3.11+ floor
  (verified live on 3.12 → 1780027200.0).
- Cache byte-stability preserved: no `server/prompts.py` / `server/tools.py` change,
  `EXPECTED_BP1_SHA256` + `EXPECTED_TOOL_SCHEMA_SHA256` untouched, no new gauge
  enters any prompt-cache key or tool-result payload.
- Hygiene: no new dependency (stdlib + existing prometheus_client only), no-fork
  clean, no `assert` for invariants introduced, all 3 gauges added to `__all__` and
  `reset_sentinel_metrics_for_tests`; the 23 new e3 tests pass.

## Recommended rectification order

1. F1 (HIGH) — reorder the WriteStats populate before the append (or hoist
   count_rows); add the store-stats.jsonl assertion. Highest leverage: closes the
   broken AC3 and corrects the false deviation-note claim.
2. F3 (MEDIUM) — add driver-level wiring tests for run_bulk_ingest / run_delta;
   this is the AC2 seam and is currently untested behind a swallow.
3. F2 (MEDIUM) — make papers/chunks render "n/a" on the genuine absent path
   (gate on the 0.0 timestamp); add the scraped-while-absent test.
4. F4 (MEDIUM) — decide the delta `papers_processed` definition and make bulk/delta
   consistent; add the deletion-counting test.
5. F5 + F6 (LOW) — fold the daily-report driver helper (stat-before-read,
   schema_version check, top-level json import) in opportunistically if F2 is
   already touching that file.

## Rectification status

- **F1 (HIGH) — FIXED.** Relocated `_append_store_stats(stats)` from before the
  marker block to AFTER it (just before `return dataset_version`), so the audit row
  captures the populated `total_rows_after_commit` (set inside the marker `try` at
  `count_rows()` time) instead of always-0. Chose relocate over hoisting
  `count_rows()` out of its guard — preserves m1's crash-safety (on a count_rows
  failure the marker is still skipped, not written with 0). Regression:
  `tests/test_store.py::TestStoreStats::test_total_rows_after_commit_recorded_not_zero`
  (asserts the last store-stats.jsonl row's `total_rows_after_commit == 3`; fails on
  the old ordering). NOTE: the sentinel's `total_rows_after_commit` is independently
  hardcoded `0` by both drivers (it is NOT a gauge — only papers/chunks/timestamp are
  surfaced); left as-is (informational field, not the adversary's flagged audit-log
  consumer).
- **F2 (MEDIUM) — FIXED.** The daily-report papers/chunks cells now render `n/a` when
  the freshness signal says "no run recorded" (`ingest_ts` is `0.0` or NaN) — covering
  BOTH server-cold (NaN) and server-up-sentinel-absent (gauges `0.0`). Previously the
  `0.0` path rendered `"0"` (reads as "ingested nothing"). Regression:
  `tests/test_daily_metrics_report.py::TestIngestionThroughputSection::test_zero_gauges_absent_sentinel_render_na_not_zero`.
- **F3 (MEDIUM) — FIXED.** Added driver-level wiring tests (the AC2 seam, previously
  untested behind a best-effort swallow):
  `test_bulk_ingest.py::TestRunBulkIngest::test_writes_ingest_summary_sentinel` +
  `test_dry_run_does_not_write_ingest_summary`, and
  `test_oai_delta.py::TestRunDelta::test_writes_ingest_summary_sentinel`. Each asserts
  the sentinel is written with `schema_version==1` + the expected `driver`.
- **F4 (MEDIUM) — FIXED.** `oai_delta.py` now maps `papers_processed =
  records_ingested + records_failed` (excludes deletions), restoring the
  `processed == succeeded + failed` invariant the bulk path satisfies and not
  inflating the gauge with deletions. Regression:
  `test_oai_delta.py::TestRunDelta::test_papers_processed_excludes_deletions` (a run
  with 1 deletion + 1 ingest asserts `papers_processed == 1`; pre-fix `== 2`).
- **F5 (LOW) — FIXED.** `_ingest_summary_driver` now `stat()`s before reading (rejects
  oversized WITHOUT materializing the body, matching server `_read_capped`) and rejects
  `schema_version != 1` (matching the server reader's distrust of unknown layouts).
- **F6 (LOW) — FIXED.** Added a top-level `import json` and replaced the
  `__import__("json")` idiom in `_ingest_summary_driver` with `json.loads`.

**Invalidation summary:** 6 findings (0 CRITICAL, 1 HIGH, 3 MEDIUM, 2 LOW). All 6
FIXED. 0 invalidated (the HIGH F1 was re-verified against `ingest/store.py` — the
append-before-populate ordering was confirmed real before fixing). Adversary
invalidation rate: 0%. Sub-agent-implemented milestone; the fresh-eyes critique caught
a genuine always-0 field the implementer's summary had claimed was correct.
