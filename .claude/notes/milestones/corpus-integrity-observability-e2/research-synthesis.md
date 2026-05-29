# Research Synthesis — corpus-integrity-observability-e2

**Merged from:** research-brief-1.md (exact seam map) + research-brief-2.md
(failure modes + logging design). **Generated:** 2026-05-29.
**Verdict:** INLINE, ~80–120 LOC across `tools/daily_metrics_report.py` +
`server/health.py` + `server/observability/logging_setup.py` + `server/config.py`
+ `ingest/store.py` + tests. Purely local. Depends on e1 (m1 `8e58c42` + m2
`513aeb6`, BOTH shipped). Both briefs concur on the design; 0 external writes.

## 1. The three deliverables (locked design)

### D-1 — Daily ops report corpus-integrity row (scout CAND-9)

`tools/daily_metrics_report.py::render_report` (lines 304–449) renders rows by
`lines.append(...)`; the **Sentinels section** (412–447) is the template for a named
scalar block, read via `_sentinel_gauge(fams, name)`. The report scrapes the running
server's `/metrics` (`DEFAULT_METRICS_URL = "http://127.0.0.1:7733/metrics"`,
cron at 05:00 UTC) — the **data source is the `/metrics` gauges, NOT a direct file
read** (both briefs concur, brief-2 FM-5). Add a `_corpus_integrity_row(fams)` helper
+ a `## Corpus integrity` section reading the three m2-shipped gauges:
`arxmcp_corpus_chunk_count_marker`, `arxmcp_corpus_chunk_count_actual`,
`arxmcp_corpus_version`. Flag `[DIVERGED]` when `marker != actual` **and neither is
NaN nor the -1 sentinel** (see §3 D4). Snapshot/assertion test in
`tests/test_daily_metrics_report.py` (mirror `test_renders_no_traceback_on_empty_metrics`
+ `test_failed_state_surfaces_in_report`); fabricate exposition text inline for the
divergence branch rather than mutating the shared fixture where possible.

### D-2 — `/readyz` 200 body carries chunk_count + marker_chunk_count (CAND-6b)

`server/health.py::readyz` 200 "ready" body (lines 241–251):
```python
content={"status": "ready", "warm": {"embedder": ..., "lancedb": ..., "reranker": ...}}
```
Add two top-level keys from m2's already-cached `Resources` fields (NO new I/O):
- `chunk_count` ← `resources.startup_chunk_count` (render `null` when `-1` — §3 D4)
- `marker_chunk_count` ← `resources.corpus_info.chunk_count`

**No test pins the exact 200 key set** (both briefs confirmed:
`test_server_startup.py::test_readyz_200_when_warm` asserts only `status` + the three
`warm.*` keys; the shim `shim/arxmcp_shim.py:96-97` drains the body without parsing).
Additive change — add ONE new test asserting both keys present + the `-1`→`null`
rendering. **This is the BP1-free CAND-6 cut — NO `get_corpus_status` MCP tool**
(stays on the Won't list). `/readyz` is NOT MCP surface
(`06-mcp-server-design.md` 7-tool list); `EXPECTED_TOOL_SCHEMA_SHA256` +
`EXPECTED_BP1_SHA256` stay FROZEN.

### D-3 — Structured write-path log event + default JSON logging (scout CAND-4)

`JsonFormatter` ALREADY EXISTS (`server/observability/logging_setup.py:78–115`) but
is deliberately NOT installed by default — the E13_S08 audit milestone scoped it
out-of-band; `configure(log_level)` (line 118) installs only the `RedactionFilter`.
e2 is the right place to wire it on by default, per `08-security-observability-ops.md`
§Logging: *"Structured JSON logs to stdout (12-factor). One line per event."*

Two parts:
- **(a) Emit the event** in `ingest/store.py::write_chunks`. See §3 D3 for the EXACT
  site (inside the marker `try`, after `write_corpus_version_marker(...)` — NOT after
  the try/except). Event: `logger.info("write_chunks_complete", extra={"event":
  "write_chunks_complete", "corpus_version": dataset_version, "chunk_count":
  chunk_count, "paper_count": paper_count})`. `caplog`-based test (format-independent;
  stdlib only — NO `structlog`/`pytest-structlog`).
- **(b) Default JSON logging** via a new `log_format` config field, wired INSIDE
  `configure()` (see §3 D1 + the SECURITY-CRITICAL §3 D2).

## 2. Load-bearing facts (quoted, both briefs concur)

- **m2 baseline shipped:** `Resources.startup_chunk_count: int = -1`
  (`resources.py:331`); `compute_chunk_count_divergence()` returns `None` on
  `actual_count < 0` (`resources.py:241`); gauges `CORPUS_CHUNK_COUNT_MARKER` /
  `CORPUS_CHUNK_COUNT_ACTUAL` (`health.py:103/114`) set in
  `refresh_metrics_from_singleton_state` (282–283). The data e2 surfaces is all
  already computed — e2 is pure presentation.
- **Redaction is shipped** (`server/observability/log_filter.py::RedactionFilter`)
  and guards `query`, `body_canonical`, `body_raw_latex`, `mathml` — NOT aggregate
  integers. `chunk_count`/`paper_count`/`corpus_version` are safe at INFO
  (`08-security-observability-ops.md` §Logging: sensitive fields are DEBUG-only).
- **`configure()` idempotency loop** (`logging_setup.py:139–142`) adds
  `RedactionFilter` to any handler lacking it. This is the single safe wiring point
  for the formatter (§3 D2).
- **EXPECTED_TOOL_SCHEMA_SHA256 + EXPECTED_BP1_SHA256 unaffected** — no MCP tool,
  no `server/prompts.py` change (both briefs verified). `make test` green is the AC.
- **No new dependency** — the existing `JsonFormatter` (stdlib `logging.Formatter`
  subclass + `json.dumps`) is sufficient; `prometheus_client==0.25.0` already parses
  the report's families. No-fork respected.

## 3. Divergences + correctness points resolved (orchestrator synthesis note)

**D1 — JSON-logging default + config field shape.** brief-1: `log_format: str =
"json"`; brief-2: `json_logs: bool = True` (`ARXMCP_LOG_JSON`). Both recommend
**default JSON ON** (constitution: "Structured JSON logs to stdout (12-factor)").
**RESOLVED → `log_format: str = "json"`** with a `@field_validator` accepting
`{"json", "text"}` (mirrors the sibling `log_level: str` + the `eq_ted_weight` /
`corpus_chunk_count_tolerance` validator pattern; more extensible than a bool). Env
`ARXMCP_LOG_FORMAT`; operators set `ARXMCP_LOG_FORMAT=text` for human-readable dev
output. `configure(log_level, log_format="json")`; `server/main.py` passes
`cfg.log_format`.

**D2 — SECURITY-CRITICAL: do NOT bypass the redaction filter (brief-2 FM-2).** The
formatter MUST be installed by calling `handler.setFormatter(JsonFormatter())` on the
EXISTING redaction-filtered handler INSIDE `configure()` — the same loop that adds
`RedactionFilter`. Adding a SECOND `StreamHandler` after `configure()` would emit
log lines that never pass through `RedactionFilter` (Threat-8 leak of query/body at
INFO+). This is load-bearing and must have a regression guard (a test asserting the
JSON-formatted handler still carries a `RedactionFilter`).

**D3 — EXACT emission site (correctness, neither brief got it precisely right).**
`chunk_count`/`paper_count` are computed INSIDE the marker-write `try`
(`store.py:931–934`), immediately before `write_corpus_version_marker(...)`. The
`except` (943–950) logs a marker-write failure. Emitting the success event AFTER the
try/except (brief-1's "line 951") would raise `NameError` when the `try` failed
(counts unbound). **RESOLVED → emit `logger.info("write_chunks_complete", ...)` as
the LAST statement INSIDE the `try`, right after `write_corpus_version_marker(...)`
returns.** This (a) guarantees the counts are bound, (b) logs only on the success
path (marker written), (c) leaves the existing error log as the sole failure signal.
Event name `"write_chunks_complete"` (brief-2; clearer than brief-1's
`"write_chunks_done"`).

**D4 — the `-1` count-unavailable sentinel must not render as a bogus divergence
(both briefs, FM-4).** When `startup_chunk_count == -1` (m2 FM-2: `count_rows()`
failed at startup): `/readyz` renders `"chunk_count": null` (not `-1`); the daily
report renders the actual as `n/a` (also for NaN/absent gauges per
`_sentinel_gauge`) and does NOT raise the `[DIVERGED]` flag. The divergence flag
fires only when both values are real non-negative numbers and differ.

## 4. Failure modes (brief-2, the primary deliverable)

- **FM-1 default-JSON blast radius — MANAGED.** `caplog`/`assertLogs` tests use
  `LogRecord.getMessage()` which is format-independent (verified: the m2 startup
  tests use `r.getMessage()`), so flipping the default does NOT break them. The
  dev-console-readability tradeoff is handled by the `ARXMCP_LOG_FORMAT=text` escape
  hatch (§3 D1). uvicorn (`log_config=None`) rides the configured root logger — JSON
  access logs are correct 12-factor behavior, not a bug.
- **FM-2 redaction bypass — RESOLVED by §3 D2** (wire inside `configure()`, never a
  2nd handler). SECURITY-CRITICAL; add a regression test.
- **FM-3 `/readyz` key drift — NON-ISSUE.** No test pins the 200 key set; the shim
  doesn't parse the body. Additive.
- **FM-4 `-1` sentinel rendering — RESOLVED by §3 D4.**
- **FM-5 report data source — `/metrics` (server running at cron time).** If the
  server is down, `fetch_metrics_text()` raises `URLError` (existing behavior,
  unchanged). Gauges absent → `_sentinel_gauge` → NaN → render `n/a`.
- **FM-6 marker absent (cold corpus) — server refuses to start → `/metrics`
  unreachable → report shows `n/a`** (same path as FM-5). No new mitigation needed.

## 5. Acceptance criteria (from the e2 epic)

1. The daily ops report renders a `## Corpus integrity` row (marker vs actual +
   `corpus_version`) with a `[DIVERGED]` flag on mismatch and graceful `n/a` on
   unavailable; a report-render assertion test covers both branches.
2. The `/readyz` 200 body includes `chunk_count` (null on the `-1` sentinel) and
   `marker_chunk_count`; a test asserts both.
3. `ingest/store.py::write_chunks` emits a structured, test-assertable
   `write_chunks_complete` INFO event (`corpus_version`, `chunk_count`,
   `paper_count`) on the success path; a `caplog` test asserts the fields. JSON
   logging is selectable via `ARXMCP_LOG_FORMAT` and defaults to `json`, wired inside
   `configure()` so the `RedactionFilter` is preserved (regression test).
4. `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED; `make test` green.

## 6. Implementation plan (INLINE; ~5 source files + tests)

1. `server/config.py` — `log_format: str = "json"` + `@field_validator` ∈ {json,text}.
2. `server/observability/logging_setup.py` — `configure(log_level, log_format="json")`;
   inside the handler loop, after ensuring `RedactionFilter`, `setFormatter(JsonFormatter())`
   when `log_format == "json"`.
3. `server/main.py` — pass `cfg.log_format` to `_configure_logging`.
4. `ingest/store.py` — emit `write_chunks_complete` INFO inside the marker `try`
   (§3 D3).
5. `server/health.py::readyz` — add `chunk_count` (null on -1) + `marker_chunk_count`
   to the 200 body.
6. `tools/daily_metrics_report.py` — `_corpus_integrity_row` + `## Corpus integrity`
   section (NaN/-1 → `n/a`, flag on real mismatch).
7. Tests: `tests/test_store.py` (or new `test_write_path_logging.py`) caplog event;
   a logging_setup test that the JSON handler keeps `RedactionFilter` (FM-2 guard);
   `tests/test_server_startup.py` /readyz-200 new-keys test;
   `tests/test_daily_metrics_report.py` corpus-integrity render + divergence + n/a.
   `assert` is fine in tests; banned for invariants in `server/`/`ingest/`.

## 7. Open questions

**None blocking.** Both briefs' open items are resolved: (1) default JSON ON
(constitution-aligned, with `ARXMCP_LOG_FORMAT=text` escape hatch — §3 D1); (2)
ingest-subprocess logging is a non-issue (`caplog` is format-independent; standalone
ingest CLIs keep their own `basicConfig` — only the server's `configure()` flips to
JSON, and the structured event emits regardless of formatter).

## 8. External writes required

**None** — purely local. No git push, PR, infra, or third-party API. (Both concur.)
