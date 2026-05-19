# Research Brief — E13_S08

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-19T14:15:00Z

## In-codebase context

### Existing logging infrastructure (no E07_S08)

**Critical finding:** The E13 roadmap lists "E07_S08" as a dependency, but E07 only has milestones S01–S04. The brief's claim of "structured logging scaffolding" from E07_S08 does not exist as a shipped artifact.

Actual logging state (shipped):
- `server/main.py` line 537: `logging.basicConfig(level=os.environ.get("ARXMCP_LOG_LEVEL", "INFO"))`
- `server/config.py` line 181: `log_level: str = "INFO"` config field exists
- `server/main.py` line 548: `logging.getLogger().setLevel(cfg.log_level)` applies the config
- Every module uses stdlib `logging` (imports: `logging.getLogger(__name__)`)
- No `structlog` dependency exists in `pyproject.toml`

**Logging pattern throughout codebase:** Each module `import logging` and creates `logger = logging.getLogger(__name__)`, then calls `logger.info(...)`, `logger.debug(...)`, `logger.warning(...)`, `logger.error(...)`. No custom handlers or filters currently exist.

### `server/observability/` package structure (exists, partial)

The directory exists with three modules:
- `metrics.py` (E14_S01) — Prometheus counters; no logging filter logic
- `tracing.py` (E14_S02) — OTel spans; `logger = logging.getLogger(__name__)` on line 69
- `sanitize.py` (E13_S02) — content sanitizer; logs at WARN once per process

**NO `logging.py` exists yet.** The brief calls for `server/observability/logging.py::configure()` — this file and function must be created from scratch.

### Sensitive-field logging patterns (current state)

Grep across `server/handlers/` + `server/retrieval/` + `server/cache.py` finds:
- `logger.info(...)` calls exist but NONE currently pass `query=`, `body_canonical`, `body_raw_latex`, or `mathml` fields
- `logger.debug(...)` calls are primarily for tracing / introspection (cache misses, embedder fallback)
- One example: `server/handlers/equation.py` line 150: `logger.warning("EquationIndex.query failed on MathML: %s", exc)` — passes the exception message, not the MathML itself

This is a **pre-emptive security measure**, not a reactive fix. No evidence of sensitive content leakage today, but the brief aims to prevent future handlers from accidentally logging it.

### Configuration and environment-variable precedent

From design note `.claude/notes/08-security-observability-ops.md` § Logging (lines 200–214):

> Structured JSON logs to stdout (12-factor). One line per event. Required fields on every log line: timestamp, level, logger, mcp.session_id, request_id, event, msg. **Sensitive fields (full query text, chunk bodies) are logged at DEBUG only, never at INFO or above.**

The `ARXMCP_LOG_LEVEL` env var is already wired (confirmed in `server/main.py` and `server/config.py`). Setting `ARXMCP_LOG_LEVEL=DEBUG` explicitly is the developer opt-in; the brief's default (INFO) strips sensitive fields.

### `RedactionFilter` semantics question: stdlib logging vs structlog

The brief says "A structlog (or Python `logging`) filter" — it does NOT prescribe which one. Key difference:
- **Stdlib `logging.Filter`:** Subclass `logging.Filter`, override `filter(record)` returning `bool`. To redact, mutate `record.__dict__` in-place (dangerous: other handlers/threads may see un-redacted data). Thread-safe mutation requires care.
- **structlog:** Processor-based; works on a dict at render time (before serialization). Cleaner redaction surface (no mutation race with other handlers).

**Recommendation:** Use stdlib `logging.Filter` because:
1. No new dependency (structlog not in `pyproject.toml`)
2. Codebase already uses stdlib throughout
3. The filter can safely mutate `record.__dict__` if applied globally **before** any handlers consume the record (which it will be — installed in `configure()` at startup)

### Doc-placement conflict: `docs/observability/log-redaction.md` vs `.claude/docs/`

The brief specifies `docs/observability/log-redaction.md`. Per CLAUDE.md §1 (read first at session start) and prior E13 precedent:

> **Concrete consequences:** The root README is project-scope-only. Anything roadmap-flavored or work-tracking goes under `.claude/`. Agent-internal documents (model policy, orchestrator rules, snippet contracts, proof-chain workflow, tier gates) live under `.claude/docs/`.

Prior E13 milestones (E13_S01–S07) all place audit docs at `.claude/docs/security-threat-N-audit.md`. **The correct placement for E13_S08 is `.claude/docs/security-observability-logging.md`** (not `docs/observability/`).

### Field redaction scope: REDACTED_FIELDS definition

The brief specifies four fields:
- `query` — full user query text passed to `search_papers` (sensitive: can reveal research direction)
- `body_canonical` — prose version of chunk body (sensitive: paper content)
- `body_raw_latex` — LaTeX source of chunk (sensitive: can contain PII in author notes)
- `mathml` — MathML rendering of equations (sensitive: might reveal research focus)

**Out of scope per brief:** `paper_id`, `chunk_id` (identifiers, not content). PII redaction (system does not handle PII inputs directly).

### Test surface for `logging.Filter`

Python's stdlib `logging.Filter`:
1. Called **before** any handlers format the record
2. Returns `bool`: `True` keeps record, `False` drops it
3. To redact: mutate `record.__dict__` and return `True`

The brief's two test cases:
- **INFO level:** log a record with `query="Faltings theorem"`, serialize to JSON, assert `query` field absent
- **DEBUG level:** same record, assert `query` present in JSON

This requires:
- A test logger configured with the filter
- A handler that outputs JSON (not stdlib's default `%(message)s` format)
- Capture + parse the JSON output to verify field presence/absence

The codebase doesn't currently emit structured JSON logs; it uses stdlib's default format. The brief's ACs assume JSON serialization happens — either:
1. The test builds a custom JSON handler for testing only
2. The implementation ships a JSON formatter for production (E14_S03 concern, or a future follow-up)

**For this milestone:** The test should use a `logging.StreamHandler` with a custom `JSONFormatter` that produces `{"timestamp": ..., "level": ..., "logger": ..., "query": ..., ...}` and verify fields are present/absent after filtering.

## Prior decisions and lessons

### E13_S02 / E13_S05–S07 precedents

All prior E13 milestones:
- Place audit docs at `.claude/docs/security-threat-N-audit.md` (NOT `docs/`)
- Use stdlib `logging` (not structlog)
- Enforce patterns via test assertions, not code-level mutations
- Bundle tests under `tests/security/test_*.py`

**Memory record:** From MEMORY.md § E13_S01 "doc-placement-correction-pattern": "E13 milestone briefs mandate `docs/security/threat-N-audit.md`. CLAUDE.md §1 restricts `docs/` to operator-facing content. Correct destination is always `.claude/docs/security-threat-N-audit.md`."

### Logging discipline landmine: thread safety

The key risk with stdlib `logging.Filter` field mutation:
- A filter runs **serially** before handlers format the record
- But if multiple handlers are installed, each handler gets the SAME mutated `record` object
- If one handler reads a field AFTER another handler has redacted it, the second handler sees redacted data (correct, but fragile)
- If a handler spawns a thread and reads the record later, there's a race (unlikely but possible)

**Mitigation:** Apply the filter **globally at install time** in `configure()`, before any handlers attach. This ensures the record is redacted once, early, before any handler sees it.

### Prior artifact: E13_S02 sanitizer pattern

`server/observability/sanitize.py` (E13_S02) demonstrates the warn-once pattern:

```python
logger = logging.getLogger(__name__)
_warned = False
def sanitize_retrieved_text(text: str) -> str:
    global _warned
    if not _warned:
        logger.warning("ARXMCP_SANITIZE_RETRIEVED_CONTENT=1 enabled")
        _warned = True
```

Apply the same pattern for the redaction filter: when `ARXMCP_LOG_LEVEL=DEBUG` is detected at startup, log once at INFO level: "DEBUG log level enabled; sensitive fields (query, body_canonical, body_raw_latex, mathml) will be included in logs."

### Failure modes (at least 5, per brief instruction)

1. **A handler other than the filter reads un-redacted record** — mitigation: register the filter globally before handlers attach, in `configure()`
2. **DEBUG log level set inadvertently in production (typo in env var)** — mitigation: log a clear WARN at startup when DEBUG is active; document in `.claude/docs/security-observability-logging.md` that `ARXMCP_LOG_LEVEL=DEBUG` is unsafe for production
3. **A new sensitive field added (e.g., `equation_latex`) but not added to `REDACTED_FIELDS`** — mitigation: code review gate in the brief's AC; document the allowlist; add field to REDACTED_FIELDS in same PR that introduces logging of that field
4. **JSON serialization includes redacted fields anyway** — mitigation: test harness must verify that the JSON serializer respects the `record.__dict__` mutation; if using a third-party JSON encoder, confirm it doesn't cache/snapshot the dict before filtering
5. **Logging happens at a level that bypasses the filter** (e.g., direct `sys.stderr.write()`)** — mitigation: grep-based linting rule in CI (flag any bare `print()` or `sys.stderr.write()` in `server/handlers/` + `server/retrieval/`; all logging must go through `logger.*()`)

## External sources

Not applicable. This milestone is purely stdlib `logging` and codebase-internal. No vendor docs required.

MCP spec does not define logging requirements (logging is a server-internal concern, not a tool-protocol concern).

## Recommendation

**Use stdlib `logging.Filter` (not structlog).**

Implement a pure-ASGI middleware-free logging redaction approach:

1. Create `server/observability/log_filter.py` with class `RedactionFilter(logging.Filter)` that:
   - Defines `REDACTED_FIELDS = frozenset({"query", "body_canonical", "body_raw_latex", "mathml"})`
   - Overrides `filter(record)` to delete each field from `record.__dict__` if `logging.getLevelName(record.levelno) != "DEBUG"`
   - Returns `True` (keep the record)

2. Create `server/observability/logging.py` with function `configure()` that:
   - Is called from `server/main.py` (before `Config()` loads) or after config loads
   - Installs the `RedactionFilter` globally: `logging.getLogger().addFilter(RedactionFilter())`
   - Sets the root logger level from `cfg.log_level` (already done in main.py, but consolidate here)
   - If `ARXMCP_LOG_LEVEL=DEBUG`, log a WARN: "DEBUG logging enabled; sensitive fields included in logs."

3. Tests at `tests/security/test_log_redaction.py`:
   - Use a custom `logging.StreamHandler` with a JSON formatter (e.g., Python's `json.dumps()` over `record.__dict__`)
   - Test case 1: INFO-level record with `query=...` → JSON lacks `query` key
   - Test case 2: DEBUG-level record with `query=...` → JSON includes `query` key
   - Same for `body_canonical`, `body_raw_latex`, `mathml` (parametrized or separate tests)

4. Documentation at `.claude/docs/security-observability-logging.md`:
   - Redaction contract: which fields, at which levels
   - Developer guidance: "Set `ARXMCP_LOG_LEVEL=DEBUG` locally for debugging; never in production."
   - Production guidance: leave `ARXMCP_LOG_LEVEL` unset (defaults to INFO); this redacts sensitive fields automatically

**Rationale:** Stdlib `logging` is already in use; no new dependency. Filter API is simple and deterministic. The early-registration pattern in `configure()` ensures thread-safe global redaction.

## Open questions

1. **Caller of `configure()`?** Should `server/observability/logging.py::configure()` be called from `server/main.py` at startup? If so, before or after `Config()` is instantiated? (Current pattern: `logging.basicConfig()` at line 537 before Config, then `getLogger().setLevel()` at line 548 after. Suggest consolidating into a single `configure()` call after Config loads and before Resources startup.)

2. **JSON formatter in production?** The current codebase emits plain-text logs to stdout (stdlib default). For the test to verify JSON field presence/absence, tests need a JSON formatter. Should the implementation ship a JSON formatter for production, or only for tests? (Suggest: test-only for now; production JSON formatting is deferred to E14_S03 or a future observability upgrade.)

3. **Regex-based sensitive-content sanitization (optional)?** The brief mentions `ARXMCP_SANITIZE_RETRIEVED_CONTENT=1` (E13_S02). Should we add an analogous `ARXMCP_SANITIZE_LOG_CONTENT=1` flag to strip the literal patterns (`<|system|>`, `[INST]`, etc.) from log values in addition to redacting the fields? (Suggest: No — field-level redaction is the primary defense; content sanitization is a higher-layer concern deferred to content handlers, per E13_S02 design.)

## External writes the implementation will require

- None — this milestone is purely local code + tests. No git push, infra mutation, or third-party API calls.

(The implementer will commit via the standard 3-commit pattern: `feat(server,tests): ...`, `rect(...)`, `chore(notes): finalize E13_S08 state -> complete`.)
