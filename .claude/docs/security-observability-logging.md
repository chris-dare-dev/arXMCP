# Threat 8 audit — tool-result and request-input redaction in structured logs

**Threat model source:** [`.claude/notes/08-security-observability-ops.md`](../notes/08-security-observability-ops.md) § Logging
**Milestone:** E13_S08
**Status:** SHIPPED 2026-05-19

## Threat statement (verbatim)

> Structured JSON logs to stdout (12-factor). One line per event. Required
> fields on every log line: timestamp (ISO 8601 UTC), level (DEBUG / INFO /
> WARN / ERROR), logger, mcp.session_id (when applicable), request_id
> (when applicable), event (short event name), msg (human-readable).
>
> **Sensitive fields (full query text, chunk bodies) are logged at DEBUG
> only, never at INFO or above.**

## What this milestone changed

Added `server/observability/log_filter.py` (the `RedactionFilter` class +
`REDACTED_FIELDS` frozenset) and `server/observability/logging_setup.py`
(the `configure()` entry point + a tests-only `JsonFormatter`). Wired
`configure(cfg.log_level)` into `server/main.py` right after Config loads
so every logger created via `logging.getLogger(__name__)` inherits the
redaction without per-module wiring.

## Redacted fields

```python
REDACTED_FIELDS: frozenset[str] = frozenset({
    "query",
    "body_canonical",
    "body_raw_latex",
    "mathml",
})
```

Rationale per field:

| Field | Why sensitive |
|---|---|
| `query` | Full user search text. Reveals research direction and intent. |
| `body_canonical` | Prose version of a chunk body. Paper content; potentially pre-publication. |
| `body_raw_latex` | LaTeX source of a chunk. Same paper-content concern, plus may contain author notes / comments stripped from the rendered output. |
| `mathml` | MathML rendering of an equation. Reveals the equation under analysis; combined with cite traces, can fingerprint the research thread. |

**Out of scope per brief:** `paper_id`, `chunk_id` (these are identifiers,
not content). The audit tests pin this exclusion so a future addition of
either field to `REDACTED_FIELDS` would be a deliberate code change with
visible code-review impact.

## How redaction works

`RedactionFilter` is a stdlib `logging.Filter` subclass. Its `filter()`
method:

1. Receives the `LogRecord` BEFORE any handler / formatter sees it
   (Python logging architecture: logger → filters → handlers →
   formatters).
2. If `record.levelno >= logging.INFO`, deletes each key in
   `REDACTED_FIELDS` from `record.__dict__` via `dict.pop(key, None)`.
3. Always returns `True` — records are never dropped, only redacted.
   Dropping would also hide the `event` / `msg` fields the operator
   needs for incident response.

The filter is installed by `configure()` on **every handler** attached
to the root logger (and on the root logger itself for defense-in-
depth). The handler-level installation is load-bearing: Python's
filter chain runs parent-logger filters ONLY on records originating
at the parent, NOT on records propagated from child loggers. Since
every server module uses `logging.getLogger(__name__)`, installing the
filter only on the root logger would leave every child-logger emit
un-redacted — the F1 rectification (E13_S08 adversary) corrected this
by moving the install point to the handlers, which DO fire on
propagated records at emit time.

Because filter mutation is in place and the LogRecord is the only
object passed to downstream handlers, every consumer — JSON
formatter, stdout text formatter, future OTel log exporter — sees the
already-redacted record. There is no race window where an un-redacted
record can escape.

**Handler-add contract:** if a future code path installs a NEW handler
on the root logger AFTER `configure()` has run, that handler will NOT
automatically have the filter attached. Callers that add post-configure
handlers must either re-call `configure(cfg.log_level)` (idempotent —
the function re-discovers handlers) or install the filter manually.
The contract is enforced by code review, not by hooking
`Logger.addHandler`.

## Operator runbook

### Default (production)

Leave `ARXMCP_LOG_LEVEL` unset (or set to `"INFO"`). At this default,
the four redacted fields are stripped from every record before any
handler can emit them. The operator sees the structured fields
(`event`, `level`, `name`, `paper_id`, `chunk_id`, etc.) but never the
paper content itself.

### Developer opt-in (full disclosure)

```bash
export ARXMCP_LOG_LEVEL=DEBUG
make up
```

At DEBUG level, the filter is a no-op and the redacted fields appear
in the log. **This must never be used in production.** `configure()`
emits a one-time WARN at startup making the trade-off visible:

```
WARNING arxmcp.security.logging: ARXMCP_LOG_LEVEL=DEBUG: sensitive
fields ['body_canonical', 'body_raw_latex', 'mathml', 'query'] are
NOT redacted from INFO+ records under this configuration. Do not
run this in production. See
.claude/docs/security-observability-logging.md.
```

The warn-once pattern mirrors `server/observability/sanitize.py` —
the operator sees the trade-off explicitly in their startup log even
if they forgot they set the env var.

### Adding a new sensitive field

If a future log call site introduces a new sensitive field (e.g.
`equation_latex`):

1. Add the field to `REDACTED_FIELDS` in
   `server/observability/log_filter.py`.
2. Update the literal-membership assertion in
   `tests/security/test_log_redaction.py::TestRedactedFieldsContract::test_redacted_fields_literal_membership`.
3. Update the table in this audit doc.
4. Commit all three in the same change.

The frozenset is intentionally NOT controlled by an env var — adding
a field is a deliberate security policy decision, not an operator
toggle.

## Caller-side contract (load-bearing)

The filter mutates `record.__dict__` keys ONLY. The following caller
patterns are NOT protected and MUST be avoided:

### ❌ Bad — sensitive value composed into the message template

```python
logger.info(f"Searching for query={query}", extra={"query": query})
```

The filter strips `record.query` but the message string still
contains the value verbatim. The serialized log line will include
the embedded text under `msg`.

### ✅ Good — sensitive value only in `extra=`

```python
logger.info("search_papers", extra={"event": "search_papers", "query": query})
```

The filter strips `record.query` at INFO+. The `msg` is the literal
string `"search_papers"`.

### ❌ Bad — sensitive value nested in a dict

```python
logger.info("search", extra={"context": {"query": query, "k": 5}})
```

The filter strips top-level `record.query` (not present here) but
`record.context["query"]` survives because the filter does NOT
recurse into nested dicts.

### ✅ Good — sensitive value as a top-level extra

```python
logger.info(
    "search",
    extra={"event": "search", "k": 5, "query": query},
)
```

### ❌ Bad — sensitive value in `args` tuple

```python
logger.info("query=%s", query)
```

The `query` value lives in `record.args`, not in `record.__dict__`,
and the filter does not touch the tuple. Even though `record.query`
is absent, the rendered message will leak the value.

### ✅ Good — never use `%s` for sensitive values

```python
logger.info("query_received", extra={"query": query})
```

## Known limitations

1. **Nested dict redaction is not implemented.** Adding deep redaction
   would require either (a) walking arbitrary nested structures and
   mutating them in place (fragile, slow), or (b) refusing dict-valued
   `extra=` fields entirely (over-restrictive). The caller contract
   above is the v1 mitigation; if a real-world leak is observed, a
   follow-up milestone can add structured-value redaction.

2. **Pre-composed message templates leak.** The filter operates at the
   `record.__dict__` layer, not the rendered message layer. Linting
   for `f"..."` and `"..." % ...` inside `logger.*` calls is a future
   hardening pass.

3. **`record.args` redaction is not implemented.** Same reasoning as
   pre-composed messages: redaction would force re-composition of the
   args tuple by attribute index, which is fragile and surface-area-
   creating. The caller contract (above) is the v1 mitigation.

4. **`JsonFormatter` is the default as of corpus-integrity-observability-e2.**
   Production stdout is 12-factor JSON (one structured line per record), per
   `08-security-observability-ops.md` §Logging. `ARXMCP_LOG_FORMAT=text` is the
   escape hatch for human-readable dev output. Redaction is format-independent:
   `configure()` installs `RedactionFilter` first, THEN sets `JsonFormatter` on
   the SAME handler, so the format choice never affects redaction. (Through
   E13_S08 the formatter shipped but was NOT installed by default — e2 flipped
   it on.)

## Acceptance-criteria status

| Brief AC | Status | Where met |
|---|---|---|
| `pytest tests/security/test_log_redaction.py` passes | ✅ | new test file, ~18 tests |
| INFO record with `query="Faltings theorem"` has `query` absent | ✅ | `TestRedactionFilter::test_faltings_theorem_brief_example_info` |
| Same record at DEBUG includes `query` | ✅ | `TestRedactionFilter::test_faltings_theorem_brief_example_debug` |
| `body_canonical`, `body_raw_latex`, `mathml` follow the same pattern | ✅ | parametrized `test_info_record_strips_sensitive_field` + `test_debug_record_keeps_sensitive_field` over `sorted(REDACTED_FIELDS)` |

## Deviations from the brief

1. **`docs/observability/log-redaction.md` → `.claude/docs/security-observability-logging.md`.**
   CLAUDE.md §1 restricts `docs/` to operator-facing content
   (today: only `docs/install.md`). All E13_S01–S07 audit docs landed
   under `.claude/docs/`; this milestone follows that precedent.

2. **File rename: `server/observability/logging.py` → `server/observability/logging_setup.py`.**
   Python 3 absolute imports already make `import logging` resolve to
   the stdlib from anywhere in this package, so a same-named module
   is not a functional hazard — but it is a reader-confusion hazard.
   `logging_setup.py` makes the intent unambiguous and keeps grep
   results free of ambiguity ("which `logging` is this?").

3. **"E07_S08" dependency is fictional.** E07 only has S01–S04. E13_S08
   is pure-new infrastructure; no prior scaffolding existed. The
   milestone delivers `server/observability/log_filter.py` +
   `server/observability/logging_setup.py` from scratch.

4. **`JsonFormatter` default — deferred at E13_S08, shipped at e2.** At E13_S08
   the formatter was exported as importable infrastructure but NOT installed by
   default (installing it globally was orthogonal to the redaction audit). The
   `08-security-observability-ops.md` §Logging "structured JSON logs to stdout
   (12-factor)" requirement was later satisfied by
   corpus-integrity-observability-e2, which added `ARXMCP_LOG_FORMAT`
   (default `json`) and wired `JsonFormatter` inside `configure()` on the same
   redaction-filtered handler.

## References

- [`server/observability/log_filter.py`](../../server/observability/log_filter.py) — `RedactionFilter` + `REDACTED_FIELDS`
- [`server/observability/logging_setup.py`](../../server/observability/logging_setup.py) — `configure()` + `JsonFormatter`
- [`server/main.py`](../../server/main.py) — calls `configure(cfg.log_level, cfg.log_format)` after Config loads
- [`tests/security/test_log_redaction.py`](../../tests/security/test_log_redaction.py) — full coverage (18 tests)
- [`server/observability/sanitize.py`](../../server/observability/sanitize.py) — warn-once pattern precedent (E13_S02)
- Python stdlib `logging.Filter` — <https://docs.python.org/3.11/library/logging.html#logging.Filter>
