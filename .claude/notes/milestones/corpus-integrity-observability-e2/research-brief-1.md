# Research Brief — corpus-integrity-observability-e2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T00:00:00Z

## In-codebase context

### Deliverable 1 — Daily ops report corpus-integrity row

**Module:** `tools/daily_metrics_report.py` (`render_report`, lines 304–449)

The report renders rows by appending to a `lines: list[str]`. The **Sentinels section** (lines 412–447) is the existing pattern for adding a named scalar row:

```python
# tools/daily_metrics_report.py:412-447
drift = _sentinel_gauge(fams, "arxmcp_latexml_drift_fixtures")
...
lines.append("## Sentinels")
lines.append("")
lines.append("| Sentinel | Value |")
lines.append("|---|---:|")
lines.append(
    f"| LaTeXML drift fixtures | "
    f"{0 if drift != drift else int(drift)} |"
)
```

The **new `## Corpus integrity` section** must come from the two m2-shipped Prometheus gauges, read via `_sentinel_gauge(fams, name)`:
- `"arxmcp_corpus_chunk_count_marker"` — `server/health.py:103-108` (`CORPUS_CHUNK_COUNT_MARKER`)
- `"arxmcp_corpus_chunk_count_actual"` — `server/health.py:114-119` (`CORPUS_CHUNK_COUNT_ACTUAL`)
- `"arxmcp_corpus_version"` — `server/health.py:92-97` (`CORPUS_VERSION_GAUGE`)

These gauges ARE already in `tests/fixtures/metrics_sample.txt` lines 22-27 (both set to `0.0`), so the fixture requires updated values to exercise the divergence-flag path in a snapshot test.

**Pattern to follow:** insert a new `## Corpus integrity` section inside `render_report` (after `## Embedder + reranker`, before `## Ingestion throughput`) following the same `lines.append(...)` structure. Add a helper `_corpus_integrity_row(fams)` returning a rendered block (mirroring `_sentinel_gauge`). Flag divergence when `abs(actual - marker) > 0` (since gauges are set correctly after m1; flag any persistent mismatch to the operator).

**Snapshot test location:** `tests/test_daily_metrics_report.py` — add a `TestCorpusIntegrity` class. The existing `test_renders_no_traceback_on_empty_metrics` (line 143) and `test_failed_state_surfaces_in_report` (line 204) are the canonical patterns for render-assertion tests. The test must update `tests/fixtures/metrics_sample.txt` with non-zero gauge values to exercise the mismatch branch — or fabricate exposition text inline (preferred for a targeted test).

### Deliverable 2 — /readyz 200 body

**File:** `server/health.py`, lines 241-251

The current 200 "ready" body is:

```python
# server/health.py:241-251
return JSONResponse(
    status_code=200,
    content={
        "status": "ready",
        "warm": {
            "embedder": resources.is_resource_warm("embedder"),
            "lancedb": resources.is_resource_warm("lancedb"),
            "reranker": resources.is_resource_warm("reranker"),
        },
    },
)
```

**Sources for the two new fields:**
- `chunk_count` = `resources.startup_chunk_count` (field declared at `server/resources.py:325-331`; `-1` sentinel means count was unavailable at startup)
- `marker_chunk_count` = `resources.corpus_info.chunk_count` (field available via `server/resources.py:267`)

Both are already cached on `Resources` from m2 — no new I/O required.

**Test pinning concern:** search for tests that assert the exact `/readyz` body key set. `tests/test_corpus_count_reconciliation.py` has `TestReadyzChunkCountDivergedBody` (line 49 of implementation summary) which asserts the degraded 503 body — it does NOT pin the 200 body keys. Grep confirms there is no test asserting `"status": "ready"` key-set exhaustively. Adding `chunk_count` and `marker_chunk_count` to the 200 body is therefore additive with no test update required beyond a new test for the new fields.

**EXPECTED_TOOL_SCHEMA_SHA256 + EXPECTED_BP1_SHA256:** `/readyz` is NOT an MCP tool surface (design note `06-mcp-server-design.md` defines the 7-tool surface as search_papers, get_chunk, find_equation, get_definitions, find_lemma_by_name, get_paper, cite_neighbors). Both pins remain FROZEN per the brief's AC.

### Deliverable 3 — Structured write-path log event + JSON logging

**Emission site — `ingest/store.py:943-951`:**

The write-path success path is just before `return dataset_version` (line 952). The marker-write try/except ends at line 950. Add a `logger.info(...)` call with keyword kwargs immediately after the marker-write try/except block, emitting assertable structured fields:

```python
# after line 950, before line 952 (return dataset_version)
logger.info(
    "write_chunks_done",
    extra={
        "event": "write_chunks_done",
        "corpus_version": dataset_version,
        "chunk_count": chunk_count,       # from tbl.count_rows() on line 931
        "paper_count": paper_count,        # from line 932-934
        "lancedb_path": str(target_path),
    },
)
```

Fields match `08-security-observability-ops.md §Logging`: `event` (short event name), plus domain-specific assertable fields. `chunk_count` and `paper_count` must NOT be leaked to debug/info when they could be sensitive — but these are aggregate counts (not paper content), safe at INFO per the redaction policy (`server/observability/log_filter.py:67`: redaction applies to `query`, `body_canonical`, `body_raw_latex`, `mathml` — NOT to count integers).

**Existing logging infrastructure:**

`server/observability/logging_setup.py:78-115` already has a `JsonFormatter` class, with this explicit note at line 22-23:

> "Also exports :class:`JsonFormatter` as importable infrastructure for tests (and for any future production-side adoption of JSON log output). The formatter is NOT installed by default — the redaction works regardless of the output format, and changing the default stdout shape is out of scope for an audit milestone."

The `configure(log_level)` function at line 118 does NOT install the `JsonFormatter`. It only installs `RedactionFilter`.

**Adding `ARXMCP_LOG_FORMAT` config field:** add `log_format: str = "json"` to `server/config.py` (mirroring `log_level: str = "INFO"` at line 265). Extend `configure(log_level, log_format="json")` in `logging_setup.py` to install `JsonFormatter` when `log_format == "json"`. The `server/main.py:729` call `_configure_logging(cfg.log_level)` becomes `_configure_logging(cfg.log_level, cfg.log_format)`.

**Ingest CLIs:** `ingest/bulk_ingest.py:489`, `ingest/oai_delta.py:895`, etc. call `logging.basicConfig(...)` independently (not via `configure()`). The brief asks for JSON logging "selectable by default" for the write path only — do NOT retrofit all ingest CLI entrypoints. The `ingest/store.py` logger already uses `logger = logging.getLogger(__name__)` (line 106); it will inherit the configured handler if the caller (server or test) configures the root logger via `configure()`. For standalone ingest CLI runs, keep `basicConfig` as-is (no change) — the structured log event still emits, just not as JSON unless the root logger has a `JsonFormatter`.

**Test pattern:** use `caplog.at_level("INFO", logger="ingest.store")` (pytest's built-in — no new dev dep), assert `any(r.getMessage() == "write_chunks_done" and hasattr(r, "event") for r in caplog.records)`. The synthesis (CAND-4, final-report rank 5) explicitly confirms: "lean stdlib — no new dep." `pytest-structlog` is explicitly rejected.

## Prior decisions and lessons

**m1 shipped (commit `a54f8f3`):** `write_chunks` now computes `chunk_count = tbl.count_rows()` (line 931) and `paper_count = len(set(...paper_id...))` (lines 932-934) from the committed table — the root-cause fix. These are the same values the new structured log event should emit.

**m2 shipped (commit `513aeb6`, rect `a8c7414`):** `server/resources.py` has `startup_chunk_count: int = -1` (line 331); `server/health.py` has `CORPUS_CHUNK_COUNT_MARKER` + `CORPUS_CHUNK_COUNT_ACTUAL` Prometheus gauges (lines 103-119); `refresh_metrics_from_singleton_state` sets both at scrape time from cached values (lines 282-283); the 503 degraded body from `/readyz` already serializes `reason="chunk_count_diverged"`.

**`JsonFormatter` exists but is deliberately not default** (`logging_setup.py:22-23`): the E13_S08 audit milestone scoped it out-of-band. This e2 milestone is the correct place to wire it as the default per `08-security-observability-ops.md §Logging`: "Structured JSON logs to stdout (12-factor). One line per event."

**`08-security-observability-ops.md §Logging` verbatim constraint:**
> "Sensitive fields (full query text, chunk bodies) are logged at DEBUG only, never at INFO or above."

`chunk_count`, `paper_count`, `corpus_version` are aggregate integers — not sensitive. Safe at INFO. The `RedactionFilter` (`server/observability/log_filter.py`) guards `query`, `body_canonical`, `body_raw_latex`, `mathml` only. No conflict.

**`08-security-observability-ops.md §Logging` required fields:** `timestamp`, `level`, `logger`, `mcp.session_id` (when applicable), `request_id` (when applicable), `event`, `msg`. The `write_chunks_done` event has no `mcp.session_id` (it is an ingest event, not a server request) — emit without it per "when applicable."

**No test greps human-readable log text in `test_store.py` or test_corpus_count_reconciliation.py.** Confirmed by grep above — no tests assert the format of `ingest.store` logger output. Flipping the default to JSON for the server's `configure()` is safe; ingest CLI callers use `basicConfig` independently and are unaffected.

**Banned patterns check:** No `assert` invariants, no `BaseHTTPMiddleware`, no `anthropic` SDK — none of these are risked by this milestone. `JsonFormatter` is stdlib `logging.Formatter` subclass — clean.

**`EXPECTED_TOOL_SCHEMA_SHA256`:** No MCP tool surface change. Brief explicitly states it MUST stay frozen. Confirmed safe by the `/readyz`-body approach for deliverable 2.

## External sources

No external vendor docs needed. `/readyz` is NOT MCP surface (no spec consult needed). `JsonFormatter` uses only `json.dumps` and stdlib `logging.Formatter` — no new dependencies required. The design note `08-security-observability-ops.md §Logging` is the authoritative spec for structured logging fields (version-pinned to the repo's design constitution, not an external reference).

## Recommendation

**Deliverable 1 (daily report):** Add `_corpus_integrity_row(fams: dict) -> list[str]` to `tools/daily_metrics_report.py` reading `arxmcp_corpus_chunk_count_marker`, `arxmcp_corpus_chunk_count_actual`, and `arxmcp_corpus_version` via `_sentinel_gauge`. Insert a `## Corpus integrity` section in `render_report` between the existing Embedder+reranker section and Ingestion throughput. Flag with `**DIVERGED**` when `marker != actual` and neither is NaN. Update `tests/fixtures/metrics_sample.txt` to have non-zero values; add a `TestCorpusIntegrity` class with a snapshot test and a divergence-flag test.

**Deliverable 2 (/readyz body):** Add `"chunk_count": resources.startup_chunk_count` and `"marker_chunk_count": resources.corpus_info.chunk_count` to the `/readyz` 200 `content` dict at `server/health.py:244`. No other files need touching. Add one new test asserting both keys are present in the 200 body.

**Deliverable 3 (structured logging):** (a) Add `log_format: str = "json"` to `server/config.py` (after the `log_level` field at line 265). (b) Extend `server/observability/logging_setup.py::configure(log_level, log_format="json")` to install `JsonFormatter` on root handlers when `log_format == "json"`. (c) Update `server/main.py:729` to pass `cfg.log_format`. (d) After the marker-write try/except in `ingest/store.py` (~line 951), emit `logger.info("write_chunks_done", extra={"event": "write_chunks_done", "corpus_version": dataset_version, "chunk_count": chunk_count, "paper_count": paper_count})`. (e) Add a `caplog`-based test in `tests/test_store.py` (or a new `tests/test_write_path_logging.py`) asserting field presence.

Use stdlib `logging` throughout — no `structlog`, no `pytest-structlog`.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The only near-open question (whether `mcp.session_id` should be added to the structured write-path event) is explicitly resolved by the synthesis and the `08-security-observability-ops.md` "when applicable" qualifier: it is NOT applicable to ingest-path events. Defer session-id `contextvars` propagation per CAND-4 sub-item note.

## External writes the implementation will require

None — this milestone is purely local. No git push, PR creation, ticket, infra mutation, or third-party API call.
