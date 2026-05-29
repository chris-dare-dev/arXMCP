# Research Brief — corpus-integrity-observability-e3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T15:20:00Z

---

## In-codebase context

### Design locked — spike-3 decision.md governs

The spike decision at `.claude/notes/spikes/corpus-integrity-observability-spike-3/decision.md`
is the authoritative design document. Key verbatim constraints:

> "**note-08 update is part of e3** — replace the two `_total` counter rows with the gauge
> names above, BEFORE wiring the Prometheus objects, so brief and code never diverge."
> (decision.md §Decision 2)

> "Atomic write: temp-then-`os.replace()`, identical to `oai_delta._write_state`
> (`oai_delta.py:216-224`). Inherits the F1 64 KB oversized guard via `_read_capped`
> automatically." (decision.md §Decision 3)

**CONFLICT WITH NOTE-08 — MUST EDIT:**
`08-security-observability-ops.md:131-138` currently names:
```
arxmcp_ingest_papers_processed_total{parser,outcome}    counter
arxmcp_ingest_chunks_written_total                      counter
```
The spike **explicitly overrides** these names and types. The implementer MUST edit
note-08 to replace those two rows with the locked gauge names BEFORE wiring the
Prometheus objects. If not done, the code and the design constitution will diverge.

### Relevant notes

- `08-security-observability-ops.md` — threat model + sentinel contract + ops cadence.
  The `_read_capped` guard lives in `server/health.py:660-686` (cap = `_MAX_SENTINEL_BYTES`
  = `64 * 1024`; `health.py:85`). This guard is inherited by the new reader at no extra cost.
- `07-multi-agent-caching.md` — no impact: no MCP tool surface changed. Hash freeze
  constraint confirmed: `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` unchanged.

### Implementation touchpoints (from codebase verification)

| File | Current state |
|---|---|
| `ingest/store.py:174-204` | `WriteStats` lacks `paper_id` + `total_rows_after_commit` |
| `ingest/store.py:873-880` | `write_chunks` constructs `WriteStats` — add fields here |
| `ingest/store.py:931` | `chunk_count = tbl.count_rows()` — already computed for the marker; thread through `WriteStats` |
| `ingest/bulk_ingest.py:374-397` | `run_bulk_ingest` accumulates `IngestSummary` (has `papers_total`, `papers_succeeded`, `papers_failed`); call `write_ingest_summary` after return |
| `ingest/oai_delta.py:216-224` | `_write_state` is the canonical atomic-write pattern to copy |
| `ingest/oai_delta.py:803-824` | `run_delta` final state write; call `write_ingest_summary` here |
| `server/health.py:558-652` | `refresh_sentinel_metrics` — add `ingest-summary.json` reader block mirroring backup-status.json block |
| `server/metrics.py:260-278` | Existing `BACKUP_LAST_SUCCESS_GAUGE` pattern is canonical for unlabeled scalar gauges |
| `tools/daily_metrics_report.py:421-431` | TODO stub "Ingestion throughput" — replace with real row |
| `tools/regen_metrics_fixture.py:59-119` | `populate_registry` — add `.set()` calls for the 3 new gauges |

---

## Prior decisions and lessons

Recent git log (`git log --oneline -20`):
```
12edf98 chore(notes): finalize notebook-ops-hardening-m1 state -> complete
f53e0f0 rect(ops): close notebook-ops-hardening-m1 critique (1H 2M 1L)
5ff3264 feat(ops): notebooks enter restic backup scope (notebook-ops-hardening-m1)
9cd28af chore(notes): finalize corpus-integrity-observability-m2 state -> complete
a8c7414 rect(server): close 5 of 6 from corpus-integrity-observability-m2 critique
```

From MEMORY.md (directly applicable):

**e2 lesson — `json-formatter-new-handler-bypasses-redaction`:** installing a NEW handler after `configure()` bypasses `RedactionFilter`. The same principle applies here: the 3 new gauges must be wired inside the existing `refresh_sentinel_metrics` call chain in `health.py`, not as a separate function invocation, to preserve per-file isolation.

**e2 lesson — `readyz-200-body-no-exhaustive-pin`:** absence of an exhaustive test on the `/readyz` 200 body means adding new gauges is additive-safe from the test perspective. No `/readyz` test update is needed for e3.

**`prometheus-gauge-set-not-recomputed` (2026-05-28):** `Gauge.set(value)` stores atomically; `generate_latest()` reads it directly. A gauge set once at startup never recomputes. The `refresh_sentinel_metrics` scrape-time hook is the correct pattern — gauges are set at scrape time, not at startup.

---

## Failure-mode analysis (primary deliverable)

### FM-1: Partial/torn write race — scrape during ingest write

**Trigger:** `/metrics` is scraped at the exact moment a driver writes `ingest-summary.json`.

**Analysis:** The `_write_state` pattern at `oai_delta.py:216-224` is:
```python
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(...)
tmp.replace(path)
```
`path.with_suffix(path.suffix + ".tmp")` produces `ingest-summary.json.tmp` in the **same directory** as `ingest-summary.json` (both under `config.ops_dir = var/arxmcp/ops/`). The new `write_ingest_summary` in `ingest/ingest_summary.py` must follow the same pattern exactly. POSIX `rename(2)` is atomic on a single filesystem; since `.tmp` is in the same directory as the target, the move is guaranteed same-filesystem. **This fully closes the torn-write race.** The reader in `refresh_sentinel_metrics` will see either the old complete file or the new complete file — never a partial write.

**Risk to flag:** If the implementer uses `tempfile.NamedTemporaryFile()` with the default `dir=None` (which defaults to `/tmp`), the `.tmp` will be on a different filesystem from `var/arxmcp/ops/`, and `os.replace()` will fall back to a non-atomic copy+delete on some platforms. Explicitly pass `dir=path.parent` to any tempfile use, or use the `path.with_suffix(".tmp")` idiom directly.

**Observable symptom if broken:** Sporadic `json.JSONDecodeError` in `refresh_sentinel_metrics` at scrape time. The WARN + leave-prior pattern suppresses crashes but leaves stale gauge values.

**Mitigation:** Mirror `_write_state` exactly: `tmp = path.with_suffix(path.suffix + ".tmp")`, then `tmp.replace(path)`.

---

### FM-2: Metrics-fixture regen failure (test breakage without explicit regen step)

**Trigger:** 3 new gauges are added to `server/metrics.py` but `tools/regen_metrics_fixture.py::populate_registry` is not updated.

**Analysis:** `tests/test_daily_metrics_report.py::TestRegenFixture::test_regen_matches_checked_in_fixture` (line 330) runs the regen script in a subprocess and diffs against the checked-in `tests/fixtures/metrics_sample.txt`. If `populate_registry` imports the new gauges but does not call `.set()` on them, the regen output will include the new gauge families at their zero default, while the on-disk fixture will not have them — the test fails. The test runs in a fresh subprocess so it will catch the mismatch immediately.

**Required steps:**
1. Add the 3 new `Gauge` objects to `server/metrics.py`.
2. In `tools/regen_metrics_fixture.py::populate_registry`, import and call `.set()` on all 3 with representative non-zero values (e.g. `INGEST_LAST_RUN_PAPERS.set(52)`, `INGEST_LAST_RUN_CHUNKS.set(4820)`, `INGEST_LAST_RUN_TIMESTAMP_SECONDS.set(1748476800.0)`).
3. Run `uv run python -m tools.regen_metrics_fixture` to regenerate `tests/fixtures/metrics_sample.txt`.
4. Commit the updated fixture alongside the code change.

**Observable symptom if broken:** `TestRegenFixture::test_regen_matches_checked_in_fixture` fails with a unified diff showing the 3 new `# HELP` / `# TYPE` / value lines absent from the on-disk fixture.

**Mitigation:** The implementer MUST run the regen script and commit the new fixture as part of the e3 feat commit.

---

### FM-3: Gauge staleness across drivers (bulk vs delta)

**Trigger:** Bulk ingest runs at 04:00, writes `ingest-summary.json` with `driver="bulk_ingest"`. Delta ingest runs at 00:00 the following night, overwrites with `driver="oai_delta"`. A scrape between 04:00 and 00:00 shows the bulk run; after 00:00+epsilon it shows the delta run.

**Analysis:** This is correct and intended. The spike decision explicitly prohibits a `{driver}` Prometheus label precisely because a labelled series for the non-most-recent driver would stay frozen at a stale value forever. Unlabeled gauges with last-run-any semantics are correct.

**The staleness check:** `arxmcp_ingest_last_run_timestamp_seconds` is the visibility mechanism. An operator can alert on `now() - arxmcp_ingest_last_run_timestamp_seconds > 172800` (48 hours) to detect a missed run. The `tools/daily_metrics_report.py` row should render the age in human-readable form alongside the `driver` field from the JSON sentinel.

**Key requirement:** The daily-report row must read `driver` from `ingest-summary.json` (not from Prometheus — it's not a label), display it alongside the gauge values. This is the only place `driver` is visible in the report.

**Observable symptom if the sentinel is not updated:** Stale timestamp becomes the alert signal. The gauge correctly shows the last successful run regardless of which driver.

---

### FM-4: Sentinel absent (cold corpus / never ingested)

**Trigger:** Fresh installation; `var/arxmcp/ops/ingest-summary.json` does not exist.

**Analysis:** The backup-status.json reader at `health.py:649-652` sets all its gauges to 0.0 when the file is absent:
```python
else:
    BACKUP_LAST_SUCCESS_GAUGE.set(0.0)
    for s in _BACKUP_STATES:
        BACKUP_STATUS_GAUGE.labels(state=s).set(0.0)
```
The new ingest-summary reader must follow the same pattern: `INGEST_LAST_RUN_PAPERS.set(0.0)`, `INGEST_LAST_RUN_CHUNKS.set(0.0)`, `INGEST_LAST_RUN_TIMESTAMP_SECONDS.set(0.0)`.

A timestamp of `0.0` is the Unix epoch (1970-01-01). An alert on
`now() - arxmcp_ingest_last_run_timestamp_seconds > 172800` will fire immediately — this is the correct operator signal ("no ingest has ever run").

**Daily-report row behavior when absent:** the row should render `n/a` for all three values, with a note "ingest-summary.json absent — no ingest run recorded." This mirrors the existing TODO stub behavior gracefully.

**Mitigation:** Per-file absence handling in `refresh_sentinel_metrics`; zero-gauges are the correct absence signal, not unregistered gauges (which would make the metric disappear from `/metrics`).

---

### FM-5: Oversized / malformed sentinel

**Trigger A (oversized):** A buggy cron writes a multi-MB `ingest-summary.json` (e.g. accidentally redirects a log dump).

**Analysis:** `_read_capped` at `health.py:660-686` checks `path.stat().st_size > _MAX_SENTINEL_BYTES` (64 KB) before reading, returning `None` and emitting a WARNING. The caller pattern in the backup reader is:
```python
raw = _read_capped(backup_status)
payload = json.loads(raw) if raw is not None else None
```
When `raw is None`, `payload` is `None`, and the gauge-update block is skipped — leaving prior gauge values in place. This is the correct behavior: stale-but-plausible values are better than zeroing a running corpus's metrics because of a sentinel corruption.

**Trigger B (malformed JSON):** JSON parse failure.

**Analysis:** The existing `except (json.JSONDecodeError, OSError, ValueError)` block logs a WARNING and falls through without touching gauges. The new reader must catch the same exception set. Importantly, `malformed → WARN + leave prior` means the gauges will show the last successfully-parsed values — the operator's WARNING log is the actionable signal.

**Risk:** If the implementer uses a bare `json.loads(raw)` outside the try/except, a `JSONDecodeError` will propagate and crash `refresh_sentinel_metrics` for this file, which per the docstring contract should be isolated: "Per-file errors are isolated: malformed JSON in one file does NOT prevent the others from being refreshed." (`health.py:579-581`). The try/except must wrap the full parse-and-set block.

**Mitigation:** Wrap the ingest-summary.json parse block in the same `except (json.JSONDecodeError, OSError, ValueError)` pattern as the backup-status reader.

---

### FM-6: `chunks_written_this_run` accuracy on re-runs

**Trigger:** Bulk ingest is run twice without resetting the corpus. The same 50 papers are re-ingested.

**Analysis:** The spike decision says:
> "`chunks_written_this_run` ← accumulate `WriteStats.rows_inserted + rows_updated` over
> the run loop (accurate per-run, no extra `count_rows()`)" (decision.md §Decision 3)

`merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all()` at `store.py:842-845` means:
- On a first-run: `rows_inserted = N`, `rows_updated = 0`
- On a re-run of the same chunks: `rows_inserted = 0`, `rows_updated = N`

`rows_inserted + rows_updated` = N in both cases. This accurately reflects "chunks touched this run" regardless of whether they were new or updates. It is NOT a double-count.

**The accumulation pattern:** `bulk_ingest.py::run_bulk_ingest` calls `write_chunks` once per paper (via `ingest_one_paper`). The caller must accumulate `stats.rows_inserted + stats.rows_updated` from each `write_chunks` return. Currently `run_bulk_ingest` does not retain `WriteStats` — it only reads `version` (via `outcome.chunks_written = len(chunks)`). The implementer must thread `WriteStats` up through the call chain or sum `outcome.chunks_written` per-paper and use that as `chunks_written_this_run`.

**Risk:** `outcome.chunks_written = len(chunks)` at `bulk_ingest.py:322` uses `len(chunks)` (the input batch size), not `rows_inserted + rows_updated` from the actual write. On a re-run, `len(chunks)` equals the batch size but `rows_updated` also equals the batch size — so `len(chunks)` is coincidentally accurate for re-runs too. However, for correctness, the sentinel should use `rows_inserted + rows_updated` from `WriteStats` as specified. The `WriteStats.total_rows_after_commit` field (new in e3) should come from `tbl.count_rows()` at `store.py:931`.

**Mitigation:** Accumulate `WriteStats.rows_inserted + WriteStats.rows_updated` in the run loop, OR sum `outcome.chunks_written` per-paper (same value in the current codebase). Prefer the former for auditability.

---

### FM-7: `schema_version` mismatch (v2 sentinel read by v1 reader)

**Trigger:** A future v2 `ingest-summary.json` (with new fields, different structure) is written by a newer driver and read by the v1 reader in the current server.

**Analysis:** The spike decision says:
> "`schema_version` — reader fails fast / leaves prior gauges on an unknown bump."
> (decision.md §Decision 3)

The v1 reader should check:
```python
if payload.get("schema_version") != 1:
    logger.warning("ingest-summary.json schema_version %r not supported; leaving prior gauge values", payload.get("schema_version"))
    return  # don't update gauges
```
This is the "leave-prior" pattern, not "fail-fast crash." The server continues serving `/metrics` with stale-but-plausible gauge values. The WARNING log is the operator signal to upgrade the server.

**Risk:** If the reader does NOT check `schema_version`, it will silently try to read v2 fields with v1 key names, possibly getting `None` values and setting gauges to 0.0 (which looks like "no ingest has run") — a silent lie that's worse than stale values.

**Mitigation:** `schema_version` check must be the FIRST thing the reader does after JSON parse. Leave-prior on unknown version.

---

## External sources

The spike decision correctly identifies that this milestone does NOT touch the MCP tool surface and does NOT require the MCP spec or prompt-caching docs — `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` are frozen.

`prometheus_client==0.25.0` is the pinned version. The 3 new metrics are plain `Gauge` objects (not `Counter` — no `_total` suffix, no `.inc()` method). `Gauge.set(value)` stores atomically; `generate_latest()` reads it at scrape time directly. No `set_function()` is needed; the scrape-time `refresh_sentinel_metrics` call in `health.py:540` is already the recompute-on-scrape mechanism. Confirmed: `/metrics` and `ingest-summary.json` are NOT MCP surface — no spec impact, hashes frozen.

---

## Recommendation

**Implement in this order to minimize test breakage:**

1. Edit `08-security-observability-ops.md` first (counter rows → gauge names).
2. Add `WriteStats.paper_id` + `WriteStats.total_rows_after_commit`; populate in `write_chunks` at `store.py:873-880`.
3. Create `ingest/ingest_summary.py` with `write_ingest_summary(ops_dir, driver, summary)` using the `_write_state` idiom from `oai_delta.py:216-224` exactly (same-dir `.tmp`, `tmp.replace(path)`).
4. Call `write_ingest_summary` at end of `run_bulk_ingest` (after `summary.elapsed_seconds = time.monotonic() - started`) and at end of `run_delta` (after `_write_state(state_path, final_state)`).
5. Add 3 `Gauge` objects to `server/metrics.py` using `BACKUP_LAST_SUCCESS_GAUGE` as the style template.
6. Add the `ingest-summary.json` reader block to `refresh_sentinel_metrics` in `server/health.py`, mirroring the backup-status.json block verbatim; wrap in `except (json.JSONDecodeError, OSError, ValueError)`; add `schema_version` check as the first guard.
7. Update `tools/regen_metrics_fixture.py::populate_registry` with `.set()` for all 3 new gauges with representative non-zero values.
8. Run `uv run python -m tools.regen_metrics_fixture` and commit updated `tests/fixtures/metrics_sample.txt`.
9. Replace the `daily_metrics_report.py` TODO stub with a real row reading the gauges + `driver` from the sentinel.
10. Write tests: writer (happy/missing-dir/atomic), reader (present/absent/oversized/malformed), `schema_version` mismatch.

**Banned patterns to watch:** No `assert` for the `schema_version` check — use `if ... raise` or the leave-prior WARN pattern. No new Markdown outside `.claude/`.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The daily-report "Ingestion throughput" row is in-scope (the TODO stub exists at `daily_metrics_report.py:421-431`; replacing it is an acceptance criterion in the milestone brief).

---

## External writes the implementation will require

None — this milestone is purely local. All writes are to `var/arxmcp/ops/ingest-summary.json` (gitignored), source files under `ingest/` and `server/`, and the test fixture at `tests/fixtures/metrics_sample.txt`. No git push, PR, ticket, or infra mutation is required.
