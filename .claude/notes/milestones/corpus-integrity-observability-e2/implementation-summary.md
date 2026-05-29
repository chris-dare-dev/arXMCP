# Implementation Summary — corpus-integrity-observability-e2

**One-line:** Operators now see corpus integrity at human cadence — a daily-report
`## Corpus integrity` row, a `/readyz` 200 body carrying `chunk_count` /
`marker_chunk_count`, and a structured `write_chunks_complete` log event with
default 12-factor JSON logging.

**Commit range:** `12edf98..<HEAD>` (this feat commit)

**Implementation path:** INLINE — 6 source files + 4 test files. Purely local.
Depends on e1 (m1 `8e58c42` + m2 `513aeb6`, both shipped).

## What landed (the three CAND deliverables)

**CAND-9 — daily ops report corpus-integrity row** (`tools/daily_metrics_report.py`):
a `## Corpus integrity` section in `render_report` (between Embedder+reranker and
Ingestion throughput) reading the m2 gauges `arxmcp_corpus_chunk_count_marker` /
`_actual` / `arxmcp_corpus_version` via `_sentinel_gauge`. Renders `[DIVERGED]` on a
real mismatch; renders `n/a` for NaN (gauge absent — server down/cold) or the `-1`
count-unavailable sentinel (m2 FM-2), never a bogus negative; the `-1`/NaN cases do
NOT raise the divergence flag.

**CAND-6b — `/readyz` 200 body** (`server/health.py::readyz`): the ready body now
carries `chunk_count` (from `resources.startup_chunk_count`, rendered `null` when
`-1`) and `marker_chunk_count` (from `resources.corpus_info.chunk_count`). This is
the BP1-free cut — NO `get_corpus_status` MCP tool (stays on the Won't list);
`/readyz` is not MCP surface, so the tool-schema + BP1 hashes are untouched.

**CAND-4 — structured write-path log event + default JSON logging:**
- `ingest/store.py::write_chunks` emits `logger.info("write_chunks_complete",
  extra={event, corpus_version, chunk_count, paper_count})` INSIDE the marker `try`,
  after `write_corpus_version_marker(...)` — so the counts are bound and it fires
  only on the success path (a marker-write failure is logged by the existing
  `except`, not as a spurious "complete").
- `server/config.py` — new `log_format: str = "json"` (env `ARXMCP_LOG_FORMAT`) with
  a `@field_validator` ∈ {json, text}.
- `server/observability/logging_setup.py::configure(log_level, log_format="json")` —
  installs `JsonFormatter` on the SAME handler that just got `RedactionFilter`
  (never a new handler — the FM-2 redaction-bypass guard). 12-factor JSON default;
  `ARXMCP_LOG_FORMAT=text` is the human-readable dev escape hatch.
- `server/main.py` — passes `cfg.log_format` to `configure`.

## Acceptance criteria

1. ✅ Daily-report corpus-integrity row (marker vs actual + corpus_version) with
   divergence flag + graceful n/a. `TestCorpusIntegritySection` (4 tests: matching,
   divergence, `-1`→n/a, absent→n/a).
2. ✅ `/readyz` 200 body includes `chunk_count` + `marker_chunk_count`.
   `test_readyz_200_body_carries_corpus_counts`.
3. ✅ Structured `write_chunks_complete` INFO event (caplog test, format-independent);
   JSON logging selectable via `ARXMCP_LOG_FORMAT` + defaulted, wired inside
   `configure()` preserving `RedactionFilter`.
   `TestWriteChunksStructuredLog` + `TestConfigure::test_json_format_installs_formatter_and_keeps_redaction`
   (FM-2 security guard) + `test_text_format_leaves_formatter_unchanged` +
   `TestConfigValidation` log_format tests.
4. ✅ `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED (no MCP tool /
   no `server/prompts.py` change); `make test` green.

## New / changed test paths

- `tests/test_daily_metrics_report.py` — `TestCorpusIntegritySection` (4).
- `tests/test_server_startup.py` — `test_readyz_200_body_carries_corpus_counts` +
  3 `log_format` validator tests in `TestConfigValidation`.
- `tests/security/test_log_redaction.py` — `test_json_format_installs_formatter_and_keeps_redaction`
  (FM-2 guard) + `test_text_format_leaves_formatter_unchanged`; the `_isolate_root`
  fixture now also snapshots/restores handler formatters (configure() mutates them
  under the JSON default).
- `tests/test_store.py` — `TestWriteChunksStructuredLog` (1).

## Deviations from the synthesis

- **Emission site (synthesis §3 D3, locked):** emitted INSIDE the marker `try`, not
  after the try/except (which would `NameError` on the counts if `count_rows()`
  raised). This is the synthesis's resolved position, recorded here for the critic.
- **`_isolate_root` test-fixture hardening (not in synthesis):** because `configure()`
  now mutates handler formatters under the JSON default, the `TestConfigure`
  isolation fixture was extended to snapshot/restore formatters, preventing a
  JsonFormatter from leaking onto pytest's handler and corrupting later tests'
  `caplog.text`. Pure test hygiene.

## External writes required

**None** — purely local. No git push, PR, infra, or third-party API.
