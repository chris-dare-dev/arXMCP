# Research Brief — corpus-integrity-observability-e2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T14:45:00Z

---

## In-codebase context

### Design constitution applicability

`08-security-observability-ops.md` §Logging mandates (verbatim):

> Structured JSON logs to stdout (12-factor). One line per event. Required fields on
> every log line: timestamp (ISO 8601 UTC), level (DEBUG / INFO / WARN / ERROR), logger,
> mcp.session_id (when applicable), request_id (when applicable), event (short event name),
> msg (human-readable).
> Sensitive fields (full query text, chunk bodies) are logged at DEBUG only, never at INFO
> or above.

This is the canonical spec for the structured-log deliverable (CAND-4). The `event` field is
explicitly required on every line.

`07-multi-agent-caching.md` Property 1 (verbatim):

> Pin tool JSON schemas. Sort properties alphabetically at serialization time. Freeze
> descriptions as constants in source. A casual edit to a tool description blows every
> sub-agent's cache.

The brief specifies `/readyz` and `/metrics` are **NOT** MCP surface. Confirmed: these are
FastAPI routes (`server/health.py::router`), NOT registered in `server/tools.py::ALL_TOOLS`.
`EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` are genuinely unaffected by all three
deliverables.

### Existing shipping state (m1+m2 baseline)

**m2 is shipped.** `server/resources.py` already carries:
- `Resources.startup_chunk_count: int = -1` (line 331) with FM-2 sentinel documented
- `compute_chunk_count_divergence()` (line 219) — pure function, already unit-tested in
  `tests/test_corpus_count_reconciliation.py`
- `server/health.py` Prometheus gauges: `CORPUS_CHUNK_COUNT_MARKER` (line 103) and
  `CORPUS_CHUNK_COUNT_ACTUAL` (line 114) — both set in `refresh_metrics_from_singleton_state`
  (line 282-283) from `resources.corpus_info.chunk_count` and `resources.startup_chunk_count`

**Redaction is shipped** (`server/observability/log_filter.py::RedactionFilter`).
**`JsonFormatter` is shipped** (`server/observability/logging_setup.py::JsonFormatter`) but
NOT wired as default — the `configure()` function only installs `RedactionFilter`; it does not
install `JsonFormatter`.

**`logging_setup.configure()` is called from `server/main.py:728`** with `cfg.log_level`.
There is NO `json_logs` / `ARXMCP_JSON_LOGS` flag in `server/config.py` today.

### /readyz current body shape

`server/health.py:readyz()` (lines 241-251): the 200 ready body is exactly:
```json
{"status": "ready", "warm": {"embedder": bool, "lancedb": bool, "reranker": bool}}
```

`tests/test_server_startup.py:TestReadinessTransition.test_readyz_200_when_warm` (line 202)
asserts `body["status"] == "ready"` and three `body["warm"][*]` keys — **does NOT pin the full
key set**. Adding `chunk_count` / `marker_chunk_count` will NOT break this test.

The shim (`shim/arxmcp_shim.py:_probe`) reads `/readyz` status code only (`r.status != 200`),
then calls `r.read()` discarding the body (line 96-97). **The shim does not parse the body.**

### Daily report structure

`tools/daily_metrics_report.py::render_report()` calls `_families_by_name(metrics_text)` which
parses the Prometheus exposition. The corpus-integrity row must read
`arxmcp_corpus_chunk_count_marker` and `arxmcp_corpus_chunk_count_actual` from the scraped
text. **The daily report runs in cron context — the server IS expected to be running** when
the cron fires (05:00 UTC per `08-security-observability-ops.md`). The server embeds the
gauges in `/metrics`; the report scrapes `/metrics`.

### write_chunks logging gap

`ingest/store.py::write_chunks` (line 770) emits only one structured log call today:
- Line 798: empty-chunks warning (low-value for this milestone)
- Line 944: error on marker-write failure

There is NO post-success structured log event with `corpus_version`, `chunk_count`,
`paper_count` fields. The marker values ARE computed at lines 931-933 (after m1 fix), so
the data is available — it just is not logged.

---

## Failure-mode analysis (PRIMARY DELIVERABLE — SIX MODES)

### FM-1: Default-JSON-logging blast radius (HIGHEST RISK)

**Trigger:** `configure()` installs `JsonFormatter` on the root handler by default (no
config flag).

**Observable symptom:** Every existing `caplog`/`assertLogs` test that checks plain-format
message text against `r.getMessage()` or `r.message` STILL works — `caplog` intercepts
`LogRecord` objects BEFORE formatting; pytest's `caplog` fixture bypasses the handler
formatter entirely. The `getMessage()` method returns the plain formatted string from
`record.msg % record.args` regardless of installed formatter.

However, tests that do `caplog.text` (the full formatted output from pytest's captured
stream handler) DO use the handler's formatter. `caplog.text` contains pytest-formatted
text by default; if the production handler emits JSON, the `caplog.text` path could differ
in tests where the test installs the production handler explicitly.

**More critical:** `test_corpus_count_reconciliation.py:TestStartupReconciliation` uses:
```python
msgs = [r.getMessage() for r in caplog.records]
```
This calls `LogRecord.getMessage()` which is format-independent. These tests are SAFE.

**BUT:** `make up` / dev-console readability degrades significantly if JSON is the default.
The brief says "selectable and defaulted per the scout" — the scout recommendation is an
external input; the design constitution says "Structured JSON logs to stdout (12-factor)"
which argues for JSON as default. **FLAG: the operator-experience tradeoff is unresolved.**

**Recommendation:** Default JSON on — it is the 12-factor standard and the constitution
says so. Add `ARXMCP_LOG_JSON=true/false` flag in `server/config.py` defaulting to `true`.
Operators wanting human-readable dev output set `ARXMCP_LOG_JSON=false`. This prevents
blast radius on existing tests AND keeps the default aligned with the design constitution.

**Uvicorn collision:** `server/main.py:782` passes `log_config=None` to `uvicorn.run()`.
This suppresses uvicorn's own log config; uvicorn uses the root logger already configured
by `_configure_logging`. Uvicorn's access logs (access logger) will also emit JSON if the
root handler has `JsonFormatter`. That's correct 12-factor behavior, not a bug.

### FM-2: Log redaction bypass via new JsonFormatter wiring (SECURITY-CRITICAL)

**Trigger:** The implementer installs `JsonFormatter` as a NEW handler on the root logger
AFTER `configure()` has run (i.e., adds a second `StreamHandler` with `JsonFormatter`).
This new handler does NOT have `RedactionFilter` installed — the `configure()` idempotency
guard only skips handlers that ALREADY HAVE a `RedactionFilter`.

From `logging_setup.configure()` (line 139-142 verbatim):
```python
for handler in root.handlers:
    if not any(isinstance(f, RedactionFilter) for f in handler.filters):
        handler.addFilter(RedactionFilter())
```

Adding a new handler after `configure()` bypasses this loop. The new handler would emit
redacted fields (query text, chunk bodies) at INFO+ level — directly violating Threat 8.

**Mitigation (load-bearing):** The implementer MUST NOT add a second handler.
The correct implementation is: call `configure()`, then REPLACE the existing handler's
formatter with `JsonFormatter` (i.e., `handler.setFormatter(JsonFormatter())` on the already-
redaction-filtered handler). This preserves the filter chain.

Alternatively: modify `configure()` itself to accept a `json_logs: bool` parameter and
install `JsonFormatter` on the handler inside `configure()` — the single safe wiring point.

### FM-3: /readyz body key drift breaks existing test assertions

**Trigger:** Adding `chunk_count` and `marker_chunk_count` to the 200 ready body.

`tests/test_server_startup.py:test_readyz_200_when_warm` (line 208) currently asserts:
```python
assert body["status"] == "ready"
assert body["warm"]["embedder"] is True
```

This test does NOT assert `body.keys() == {...}` nor use a schema-strict assertion. Adding
new top-level keys is SAFE for this test. **No existing test pins the exact /readyz-200
key set.**

`tests/test_failure_modes.py:TestDegradedReadyz` (line 283) tests the 503 degraded body —
unaffected by 200-body changes.

The shim (`shim/arxmcp_shim.py:96-97`) reads `/readyz`, checks status code only, calls
`r.read()` to drain the body and discard it — no body parsing. **Safe.**

### FM-4: startup_chunk_count = -1 sentinel displayed as "-1 chunks" in report/readyz

**Trigger:** `count_rows()` failed at startup (FM-2 in Resources — e.g. LanceDB not yet
populated or internal error). `startup_chunk_count = -1` is the sentinel.

**Observable symptom without mitigation:** `/readyz` body shows `"chunk_count": -1` and the
daily report shows "marker=N actual=-1" which looks like a severe negative divergence.

**Mitigation:** The -1 sentinel is already handled by `compute_chunk_count_divergence()`
(returns `None` on `actual_count < 0`, line 241 of `resources.py`). The `/readyz` body
should render `-1` as a special string: `"chunk_count": "unavailable"` or `null`. The daily
report should show "actual: n/a (count_rows failed)" rather than "-1".

### FM-5: Daily report data-source question — /metrics vs direct file read

**Trigger:** The daily report cron runs at 05:00 UTC per ops cadence. The server IS running
(always-on per `08-security-observability-ops.md` Docker design). The report already
`fetch_metrics_text()` from `DEFAULT_METRICS_URL = "http://127.0.0.1:7733/metrics"`.

**The data-source is `/metrics` (Prometheus gauges), NOT a direct file read.**

This is already the existing pattern for all other sentinel metrics in `render_report()`.
The corpus-integrity row must read `arxmcp_corpus_chunk_count_marker` and
`arxmcp_corpus_chunk_count_actual` from the scraped text — no new data source needed.

**Risk:** If the server is down at cron time, `fetch_metrics_text()` raises `URLError` and
the report fails. This is existing behavior; the milestone does not change it. Document
in the row render that gauges reflect startup-cached values (stale by design).

### FM-6: corpus-version marker absent at report render time

**Trigger:** Fresh corpus, no ingest run yet. `corpus-version.json` absent.

**Observable symptom:** `Resources.startup` raises `CorpusNotIngestedError` and the server
never starts — `/metrics` is unreachable. The report fails with `URLError`.

This is the same failure mode as FM-5 (server down). No mitigation needed beyond the
existing error message; document it in the daily report's error handling.

**HOWEVER:** the corpus-integrity row in the report renders from the `/metrics` gauges.
If the server never started, `arxmcp_corpus_chunk_count_marker` and `_actual` will be absent
from the metrics text. The `_sentinel_gauge()` helper already returns `nan` on absent
families (`fams.get(...)` → `None` → nan). The row must handle `nan` gracefully (render
"n/a").

---

## External sources

No new external deps needed for any of the three deliverables:

- **Stdlib `logging`** (Python 3.11+): `JsonFormatter` is already shipped in
  `server/observability/logging_setup.py`. No `python-json-logger` or similar third-party
  package needed; the existing class is sufficient. Confirmed: no JSON log package in
  `pyproject.toml`.
- **`/readyz` is not MCP surface.** Confirmed by reading `server/tools.py::ALL_TOOLS` and
  `server/health.py::router` — `readyz` is a FastAPI route on `APIRouter`, NOT a registered
  MCP tool. MCP spec is not relevant.
- **Prometheus client** (`prometheus_client==0.25.0`): already in deps. The daily report
  uses `text_string_to_metric_families` for parsing; the corpus-integrity row follows the
  same pattern as the existing sentinel rows.

---

## In-codebase cross-check (constraint verification)

**EXPECTED_TOOL_SCHEMA_SHA256:** confirmed unaffected. No MCP tool is added or modified.
`server/tools.py::ALL_TOOLS` is not touched by any deliverable.

**EXPECTED_BP1_SHA256:** confirmed unaffected. `server/prompts.py` (the BP1 system prompt)
is not touched. `/readyz` body changes do not affect BP1.

**macOS segfault guard (`KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py`):** unaffected.
None of the three deliverables touch `conftest.py`.

**Banned patterns:**
- No `assert` for invariants — the -1 sentinel check uses `if actual_count < 0: return None`.
- No `BaseHTTPMiddleware` — not relevant.
- No `import anthropic` — not relevant.

**No design note conflicts found.** The brief's "EXPECTED_TOOL_SCHEMA_SHA256 + EXPECTED_BP1_SHA256
MUST stay frozen" is consistent with what `07-multi-agent-caching.md` mandates.

---

## Recommendation

Implement all three deliverables in a single commit with this structure:

1. **Structured write-path log event (CAND-4):** Add a `logger.info(...)` call at the end of
   `ingest/store.py::write_chunks` (after the `write_corpus_version_marker` call, whether or
   not the marker write succeeded), using `extra={"event": "write_chunks_complete",
   "corpus_version": dataset_version, "chunk_count": chunk_count, "paper_count": paper_count}`.
   Guard with `try/except` to never swallow the `dataset_version` return. Test with `caplog`
   asserting on `r.extra["event"]` == "write_chunks_complete" and presence of the three fields.

2. **Default JSON logging (CAND-4 cont.):** Modify `logging_setup.configure()` to accept a
   `json_logs: bool = True` parameter. When `True`, call
   `handler.setFormatter(JsonFormatter())` on each root handler INSIDE `configure()` — the
   same loop that installs `RedactionFilter`. This is the ONLY safe wiring point (avoids the
   FM-2 redaction bypass). Add `json_logs: bool = True` to `server/config.py::Config` and
   wire via `ARXMCP_LOG_JSON` env var. Existing tests using `caplog.records[i].getMessage()`
   are unaffected (format-independent).

3. **`/readyz` 200 body (CAND-6b):** Add `chunk_count` and `marker_chunk_count` to the 200
   response in `server/health.py::readyz()`. Read from `resources.startup_chunk_count` and
   `resources.corpus_info.chunk_count`. Render `-1` as `None` (JSON null) for the
   count-unavailable sentinel. Update the docstring to document the new key contract.

4. **Daily report row (CAND-9):** Add a `_corpus_integrity_row()` function and a new
   "## Corpus integrity" section in `render_report()`. Read the two gauge values from the
   parsed metrics families. Render: marker count, actual count, corpus_version, and a
   `[DIVERGED]` flag if `|actual - marker| > 0`. Return "n/a" for gauges absent from the
   metrics text (server not started or cold corpus). Add a snapshot assertion in
   `tests/test_daily_metrics_report.py` using the existing fixture, plus a new fixture line
   for the two new gauges.

---

## Open questions

1. **`ARXMCP_LOG_JSON` default:** The brief says "defaulted per the scout" but the scout
   recommendation is not in-repo. Recommend defaulting to `True` (aligned with
   `08-security-observability-ops.md`'s "Structured JSON logs to stdout (12-factor)"). If
   the scout said `False`, that contradicts the constitution — the constitution wins.

2. **`ingest/store.py` also runs in the ingest subprocess (not the server).** The JSON
   logging default applies to the server process. The write-path log event in `store.py` is
   emitted in whatever process calls `write_chunks` — ingest cron, test, server. Tests that
   call `write_chunks` directly and use `caplog` will see the structured-field log record
   regardless of the formatter. No open question here — `caplog` is format-independent.

---

## External writes the implementation will require

None — this milestone is purely local.

All deliverables are local source changes + tests. No git push, no PR, no infra mutation,
no third-party API calls. The implementer commits locally; the push is per-event authorized
by the user in Phase 4.
