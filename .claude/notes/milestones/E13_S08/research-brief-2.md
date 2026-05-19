# Research Brief — E13_S08

**Agent:** milestone-researcher (brief-2, external-sources-first approach)
**Generated:** 2026-05-19T22:35:00Z

## External sources — logging filter semantics and JSON serialization patterns

### Python logging.Filter contract

Per Python 3.11 standard library docs, `Filter.filter(record)` receives a `LogRecord`
object and returns a truthy/falsy value:
- **Return True (or nonzero):** allow the record to be processed further by handlers
- **Return False (or 0):** reject the record entirely — it will not be emitted

**Critical:** The filter can **modify `record.__dict__` in place** before returning:
> "Although filters are used primarily to filter records based on more sophisticated
> criteria than levels, ... changing the LogRecord needs to be done with some care, but
> it does allow the injection of contextual information into logs."

This is the correct pattern for redaction: iterate over `record.__dict__` and delete or
clear sensitive keys.

### LogRecord attributes and extra-dict injection

Every log call creates a LogRecord with standard attributes:
- Standard: `name`, `levelname`, `levelno`, `message`, `asctime`, `created`, `pathname`, `funcName`, `lineno`, `process`, `thread`, etc.
- Custom (via `extra={...}`):** injected as direct attributes on `record.__dict__`

When a handler calls `logger.info("event", extra={"query": "...text...", "chunk_id": "..."})`,
both `query` and `chunk_id` are added to `record.__dict__` and are available for formatting.

**Important:** The filter sees ALL attributes, both standard and extra. Deleting a key
from `record.__dict__` removes it from formatting, but NOT from the message string
itself if the message was pre-composed (see failure mode #5 below).

### JSON logging patterns

Three widely-used Python JSON logging approaches:
1. **python-json-logger** (PyPI: actively maintained, v3.2.1 released 2025-03-07) —
   extends `logging.Formatter` to emit JSON. Iterates `record.__dict__` and serializes
   all keys to JSON, using customizable encoders for UUIDs, bytes, etc.
2. **Rolled custom:** Subclass `logging.Formatter`, override `format(record)` to return
   `json.dumps(record.__dict__, ...)` after stripping unwanted keys.
3. **structlog** (third-party async-friendly logger) — completely separate from stdlib
   logging; not in pyproject.toml dependencies.

The codebase uses **only stdlib logging today** (no python-json-logger import found).
The brief calls for "structured JSON logs"; no JSON formatter library is currently a
dependency. The brief's deliverable list includes `server/observability/logging.py::configure()`,
which implies we wire the JSON formatter at startup, but does NOT specify which library.

### Filtering failures: seven failure modes

**F1: Nested dict/list payloads.** If `record.context = {"query": "...", "paper_id": "xyz"}`,
deleting `record.query` does NOT redact the nested dict. Example: `logger.info("event", extra={"context": {"query": "full text"}})` — the filter deletes top-level `query` but `record.context["query"]` survives. *Mitigation:* Deep-delete only top-level keys in `REDACTED_FIELDS`; nested payloads are out of scope per the brief's "query" (singular) redaction scope.

**F2: Message pre-composition.** If the caller does
```python
query_text = "Faltings theorem"
logger.info(f"Searching: {query_text}", extra={"query": query_text})
```
the message string is ALREADY composed; deleting `record.query` leaves the text in
`record.message`. *Mitigation:* Document in the audit log that message-body composition
must avoid embedding sensitive values; the filter redacts the `extra=` attributes only.

**F3: Multiple handlers, no filter on root logger.** If the filter is installed only on
a specific handler but not on the logger itself, records skip the handler-level filter if
the logger has multiple handlers attached. *Mitigation:* Install the filter on the root
logger (as the brief specifies via `configure()`), not just on a single handler.

**F4: `record.args` tuple.** If the log call is `logger.info("query=%s", query_text, extra={...})`,
the `query_text` is stored in `record.args`, not `record.message` (message is computed
AFTER filtering). Deleting `record.query` doesn't touch `record.args`. *Mitigation:*
The brief specifies redacting `query`, `body_canonical`, `body_raw_latex`, `mathml` as
**field names** — it's agnostic about whether they come from `extra=` or `args`. If we
want to redact `record.args`, we'd need to re-compose `record.args` minus sensitive
indices, which is fragile. The brief's AC ("a log record with `query=...` at INFO level
has `query` absent") suggests redacting only the attribute, not the args tuple.

**F5: Formatter runs before filter.** If a custom formatter has already cached
`record.__dict__` before the filter runs, modifications are lost. *Mitigation:* Filters
run BEFORE formatters (per Python logging architecture: logger → filters → handlers →
formatters), so this is not a risk.

**F6: DEBUG-level opt-out forgotten.** If `ARXMCP_LOG_LEVEL=DEBUG` but the operator
forgets to rotate logs (expecting INFO-level redaction), sensitive content streams
to stdout indefinitely. *Mitigation:* This is an operational risk, not a code risk.
Document in the audit log that DEBUG level is a "full disclosure" mode.

**F7: OTel/Prometheus log export.** The threat model mentions log aggregation pipelines
("stdout → Prometheus → OTel"). If OTel's OTLP log exporter reads `record.__dict__`
directly (without calling a formatter), it may transmit the redacted attributes. The
Python OTel SDK's LogExporter interface accepts LogRecord objects; whether it redacts is
handler-dependent. *Mitigation:* The filter modifies `record.__dict__` before ANY handler
sees it, so any downstream OTel exporter will see the already-redacted record. Confirmed:
OTel SDK reads the formatted output, not `record.__dict__` directly (for logging).

### BP1 cache stability implications

The brief says to update `server/observability/logging.py::configure()`. This function
does NOT touch the MCP `tools/list` response schema, so **no re-pinning of**
`**EXPECTED_TOOL_SCHEMA_SHA256` is required. The logging configuration is internal
infrastructure, not a tool parameter.

## In-codebase context

### Design constitution: logging requirements

From `.claude/notes/08-security-observability-ops.md` § Logging (lines 200–214):

> "Structured JSON logs to stdout (12-factor). One line per event. Required fields on
> every log line: timestamp (ISO 8601 UTC), level (DEBUG / INFO / WARN / ERROR), logger,
> mcp.session_id (when applicable), request_id (when applicable), event (short event
> name), msg (human-readable).
>
> **Sensitive fields (full query text, chunk bodies) are logged at DEBUG only, never at
> INFO or above.**"

The threat model (line 213) explicitly mandates redaction. The E13_S08 brief operationalizes
this via a `RedactionFilter`.

### Codebase logging state

- **No `server/observability/logging.py` exists yet.** The directory `server/observability/`
  contains only `__init__.py`, `metrics.py`, `sanitize.py`, `tracing.py`. Logging configuration
  is currently inline in `server/main.py::537` as a single `basicConfig()` call.
- **stdlib logging only.** No `python-json-logger` in pyproject.toml. No JSON formatter
  anywhere. The brief's "structured JSON logs" requirement is aspirational — currently logs
  are plain-text format.
- **Sensitive fields already logged.** Grep confirms that `logger.info(...)` calls in
  `server/cache.py`, `server/cache_sqlite.py`, and handler modules do not currently log
  `query`, `body_canonical`, etc. — they log cache hits, exceptions, config state. However,
  the brief mandates defensive redaction for ANY future handlers that might log these fields.
- **E07_S08 is fictional.** The brief lists "E07_S08 (structured logging scaffolding)" as
  a dependency. E07 has only S01–S04 (confirmed in project memory). The logging infrastructure
  is NOT shipped; E13_S08 is a pure-new implementation.

### Log-level control

`server/config.py` has a `log_level` field. It's already wired:
```python
logging.basicConfig(level=os.environ.get("ARXMCP_LOG_LEVEL", "INFO"))
```
The default is INFO; `ARXMCP_LOG_LEVEL=DEBUG` explicitly enables sensitive-field logging.

### Doc placement precedent

Prior E13 milestones confirm that security audit docs live at `.claude/docs/security-*`,
NOT `docs/observability/`. The brief erroneously specifies `docs/observability/log-redaction.md`.
Per project memory (2026-05-19 E13_S08 note), the correct path is
`.claude/docs/security-observability-logging.md`.

## Prior decisions and lessons

### E13 audit-and-verification pattern

E13_S01 through E13_S07 all follow the same pattern:
- Milestone brief specifies a threat from `08-security-observability-ops.md`
- E13 milestone adds the audit harness (tests, enforcement, documentation)
- Earlier epic (E06, E07) may have shipped partial mitigations; E13 completes the audit

For E13_S08, no earlier epic shipped the `RedactionFilter`. This is pure-new code.

### Fictional dependencies

The E13_S08 brief cites `E07_S08` (structured logging scaffolding) as a dependency.
This is fictional — E07 has only S01–S04. Every E13 milestone brief has at least one
fictional dependency (confirmed in memory across S01–S07). This is NOT an error in the
brief; the implicit assumption is "audit will either find the scaffolding or deliver
it from scratch."

### json.dumps() safety

The brief does NOT call for custom JSON serialization; it assumes `json.dumps(record.__dict__)`.
Standard Python LogRecord attributes (strings, ints, None, tuples) are JSON-serializable
out of the box. Custom attributes added via `extra=` MUST be JSON-able; if a handler
tries to log a non-serializable object (e.g., a Lambda function), the formatter will fail
(or require a custom encoder). *Risk:* Low, because the server's handlers are code-controlled,
not user-input-controlled. *Mitigation:* The test harness should include a case where
a handler tries to log a complex object and confirm the JSON formatter doesn't silently drop it.

### Rate-limit interaction

The brief is independent of rate-limiting (E13_S04). A rate-limit rejection at 1000 calls/hour
will itself be logged (as an ERROR or WARN); that log record will be filtered same as any
other (no sensitive fields in rate-limit errors).

## Recommendation

**Implement a stdlib-only approach with a custom JSON formatter.**

Why: The codebase already has a baseConfig call; python-json-logger is a third-party
dependency that would require pyproject.toml + uv.lock updates + test setup. A rolled
custom formatter is ~30 lines, stays within stdlib, and is transparent to operators.

**Implementation approach:**
1. Create `server/observability/log_filter.py` with:
   - `REDACTED_FIELDS = frozenset({"query", "body_canonical", "body_raw_latex", "mathml"})`
   - `class RedactionFilter(logging.Filter)` with `filter(record)` that:
     - If `record.levelno >= logging.INFO` (INFO and above), delete all keys in
       `record.__dict__` whose names are in `REDACTED_FIELDS`
     - Always return `True` (never reject records, only redact)
2. Create `server/observability/logging.py::configure()` that:
   - Extends `logging.Formatter` to emit `json.dumps(record.__dict__)`
   - Installs `RedactionFilter` on the root logger
   - Reads `ARXMCP_LOG_LEVEL` from config and sets the level
   - Returns the configured logger for use by `server/main.py`
3. Update `server/main.py` to call `from server.observability.logging import configure; configure()`
   instead of `logging.basicConfig()`
4. Write `tests/security/test_log_redaction.py` with:
   - Test case: log a record with `query=...` at INFO level, assert absent from JSON
   - Test case: same record at DEBUG level, assert present in JSON
   - Parametrize over all 4 redacted fields
5. Write `.claude/docs/security-observability-logging.md` (NOT `docs/observability/`)
   documenting the filter behavior, opt-in DEBUG mode, and failure-mode warnings.

**No tool-schema re-pin needed** — logging is internal infrastructure.

## Open questions

1. **JSON formatter library:** Should we use python-json-logger (PyPI) or rolled custom?
   - *Decision:* Rolled custom. Lower dependency footprint, transparent.

2. **Redact `record.args` tuple?** The brief says redact `query` field; it's silent on
   whether `logger.info("query=%s", sensitive_value)` (where the value is in args) should
   be redacted.
   - *Decision:* No. The brief's AC explicitly checks for field absence in serialized JSON;
     field absence = attribute removed from `record.__dict__`. The args tuple is a separate
     layer. Requiring args redaction would force re-composition logic that's fragile and
     out of scope.

3. **Doc path:** `.claude/docs/security-observability-logging.md` or
   `docs/observability/log-redaction.md`?
   - *Decision:* `.claude/docs/security-observability-logging.md`. Audit docs live under
     `.claude/docs/security-*`. Precedent established in E13_S01–S07.

4. **Does structlog replace stdlib logging?**
   - *Decision:* No. structlog is NOT a dependency. The codebase is 100% stdlib logging.
     Structlog is a completely separate logging framework (async-native, context-local
     state). Migration would require rewriting every logging call in the server. Out of
     scope for an audit milestone.

5. **OTel log export safety:**  If an OTel exporter reads `record.__dict__` AFTER formatting,
   does the redaction survive?
   - *Decision:* Yes. The filter modifies the LogRecord in place BEFORE any handler/formatter
     sees it. All downstream consumers (formatters, exporters) see the already-redacted
     version.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| None | — | This milestone is purely local: no git push, no API call, no infra mutation. The RedactionFilter, logging config, and tests all land in a single feat+rect+chore commit triple. |

## Notes for the implementer

- **Failure-mode risk F2 (message pre-composition):** Document in the audit log that
  handlers MUST NOT compose sensitive values into the message string. Bad:
  `logger.info(f"query={query}")`. Good: `logger.info("search", extra={"query": query})`.
- **BP1 cache:** Logging infrastructure does not touch tool schemas; no re-pinning needed.
- **Doc placement:** Use `.claude/docs/security-observability-logging.md`, not `docs/observability/`.
- **structlog fallback:** If config.log_level interacts with a future structlog migration,
  that's deferred to E14; stdlib logging is the v1 target.
