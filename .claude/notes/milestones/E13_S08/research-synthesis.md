# Research Synthesis — E13_S08

**Generated:** 2026-05-19 (orchestrator merge of brief-1 and brief-2)
**Mode:** standard (2× milestone-researcher, Haiku 4.5)

---

## Current state of the world (load-bearing)

**Logging stack:** the codebase uses **stdlib `logging` only**. No `structlog`,
no `python-json-logger` in `pyproject.toml`. Every module follows the same
pattern: `logger = logging.getLogger(__name__)`.

**Existing wiring** (`server/main.py:537,548`):

```python
logging.basicConfig(level=os.environ.get("ARXMCP_LOG_LEVEL", "INFO"))
# ... Config() load ...
logging.getLogger().setLevel(cfg.log_level)
```

**Config field** (`server/config.py:181`): `log_level: str = "INFO"`. Already
wired to `ARXMCP_LOG_LEVEL` via the BaseSettings `env_prefix="ARXMCP_"`
convention.

**`server/observability/` exists with:**

- `__init__.py`
- `metrics.py` (E14_S01 — Prometheus counters)
- `sanitize.py` (E13_S02 — content sanitizer + warn-once pattern)
- `tracing.py` (E14_S02 — OTel spans)

**No `server/observability/logging.py` exists.** This milestone creates it.
**No `RedactionFilter` exists today** — pure-new code.

**Threat 8 verbatim** (`.claude/notes/08-security-observability-ops.md` § Logging):

> Structured JSON logs to stdout (12-factor). One line per event. Required
> fields on every log line: timestamp (ISO 8601 UTC), level (DEBUG / INFO /
> WARN / ERROR), logger, mcp.session_id (when applicable), request_id (when
> applicable), event (short event name), msg (human-readable).
>
> **Sensitive fields (full query text, chunk bodies) are logged at DEBUG
> only, never at INFO or above.**

---

## Brief/repo conflicts — resolved by orchestrator

Same systematic drift seen in E13_S01–S07. Resolutions:

| # | Brief says | Repo policy | Resolution |
|---|---|---|---|
| 1 | `docs/observability/log-redaction.md` | CLAUDE.md §1: `docs/` is operator-only (`install.md` only) | Use `.claude/docs/security-observability-logging.md` (matches `.claude/docs/security-*` precedent from E13_S01–S07) |
| 2 | "Dependencies: E07_S08" | E07 only has S01–S04; `E07_S08` is fictional | Treat E13_S08 as pure-new infrastructure; the dependency line is documented drift, not an unmet prerequisite |
| 3 | "A structlog (or Python logging) filter" | `structlog` is NOT in `pyproject.toml`; codebase is 100% stdlib | Use stdlib `logging.Filter`. Both researchers independently recommended this |

---

## Where briefs agreed

Both researchers converged cleanly on:

1. **stdlib `logging.Filter` over structlog** — no new dependency, lower
   blast radius, matches existing codebase patterns.
2. **Doc placement at `.claude/docs/security-observability-logging.md`** —
   matches every prior E13 audit doc.
3. **Filter installed globally on the root logger** in a new
   `server/observability/logging.py::configure()`, called from
   `server/main.py` to replace the current `logging.basicConfig(...)` +
   `setLevel(...)` two-step.
4. **Mutate `record.__dict__` in place** (delete the redacted keys),
   return `True` to keep the record. The filter runs BEFORE any handler /
   formatter (Python logging architecture: logger → filters → handlers →
   formatters), so all downstream consumers see the redacted record.
5. **Test harness needs a JSON formatter to verify field presence/absence**
   because the codebase emits plain-text logs today; a tests-only
   `json.dumps(record.__dict__)` is sufficient and avoids a third-party
   formatter dependency.
6. **`args` tuple redaction is OUT of scope** — the brief's AC checks for
   field absence in the serialized JSON, which means attribute-level
   absence. Args redaction would require fragile message recomposition.

---

## Failure modes (union, deduped)

1. **Message pre-composition leaks the value.** Caller does
   `logger.info(f"Searching {query}", extra={"query": query})`. Redacting
   `record.query` leaves the value in `record.message`. **Mitigation:** the
   audit doc must call out the contract "do not embed sensitive values in
   the message template" with a Good/Bad example. Lint-level enforcement
   is out of scope for v1.
2. **Nested dict payloads.** `extra={"context": {"query": "..."}}`. Top-level
   `query` deletion does not touch the nested dict. **Mitigation:** document
   the scope (only top-level keys). Future hardening could add deep redaction.
3. **`args` tuple holds the value.** `logger.info("q=%s", query)`. The args
   tuple is rendered into the message only after the filter runs but
   `record.args` is still present in the LogRecord dict.
   **Mitigation:** document the scope; do not attempt args rewriting.
4. **Filter installed on a handler, not the root logger** → records emitted
   via a different handler bypass redaction. **Mitigation:** install on the
   root logger via `logging.getLogger().addFilter(...)` AND on each handler
   the implementation adds, so propagation order doesn't matter.
5. **DEBUG opt-out forgotten in production.** Operator sets
   `ARXMCP_LOG_LEVEL=DEBUG` for triage and forgets to revert. **Mitigation:**
   emit a WARN log at startup when the level is DEBUG (warn-once pattern
   mirroring `server/observability/sanitize.py`).
6. **A new sensitive field is added** (e.g. `equation_latex`) but not added
   to `REDACTED_FIELDS`. **Mitigation:** make `REDACTED_FIELDS` a module-level
   `frozenset` with a clear comment that any new sensitive field MUST be
   added here in the same commit that introduces logging it. A test asserts
   the literal contents of the frozenset to make changes visible in code
   review.
7. **Tests that exercise the test JSON formatter accidentally couple to its
   exact output shape.** **Mitigation:** parse the formatter output as JSON
   and assert on key presence/absence, never on byte-stable substring matches.

---

## Implementation plan (concrete deliverables)

1. **`server/observability/log_filter.py`** (new) — contains:
   - `REDACTED_FIELDS: frozenset[str] = frozenset({"query", "body_canonical", "body_raw_latex", "mathml"})`
   - `class RedactionFilter(logging.Filter)` with `filter(record)` that:
     - If `record.levelno >= logging.INFO`, deletes each key in
       `REDACTED_FIELDS` from `record.__dict__` via `delattr` /
       `record.__dict__.pop(key, None)`. Returns `True` either way.
     - Otherwise (DEBUG and below), returns `True` without mutation.

2. **`server/observability/logging.py`** (new) — contains:
   - `class JsonFormatter(logging.Formatter)` — emits a single line of
     `json.dumps(record.__dict__, default=str, sort_keys=True)` minus the
     uninteresting builtin LogRecord internals (e.g. `args`, `msg`,
     `exc_info`, `exc_text`, `stack_info` — these are present on every
     record and would bloat the JSON without adding value). The formatter
     is the test-only JSON path for verifying the filter; production may
     opt to install it too, but the brief is silent on production JSON.
   - `def configure(log_level: str) -> None` — installs `RedactionFilter()`
     on the root logger via `logging.getLogger().addFilter(...)`, sets the
     root log level, and if `log_level.upper() == "DEBUG"` emits a WARN log
     once: `"ARXMCP_LOG_LEVEL=DEBUG: sensitive fields are NOT redacted from
     INFO+ records; do not run this configuration in production."` (matches
     the `server/observability/sanitize.py` warn-once pattern).

3. **`server/main.py`** (modify) — replace the
   `logging.basicConfig(...) + getLogger().setLevel(...)` two-step with a
   single `configure(cfg.log_level)` call. The fallback `basicConfig(...)`
   before `Config()` still needs to run (so a Config-load failure can log
   at FATAL); the new `configure()` runs AFTER Config loads.

4. **`tests/security/test_log_redaction.py`** (new) — at minimum:
   - `TestRedactionFilter::test_info_record_strips_query` — INFO record
     with `extra={"query": "Faltings theorem"}`; capture via a `StringIO`
     stream handler with the test `JsonFormatter`; assert `query` key is
     absent from parsed JSON.
   - `test_debug_record_keeps_query` — same setup at DEBUG; assert
     `query` is present.
   - Parametrize over `("query", "body_canonical", "body_raw_latex", "mathml")`
     so AC4 ("body_canonical / body_raw_latex / mathml follow the same
     pattern") is satisfied without per-field copy-paste.
   - `test_redacted_fields_frozen_contract` — pins the literal frozenset
     contents so a future change to the field set is visible in PR review
     (failure mode 6).
   - `test_configure_warns_on_debug_level` — capture WARN log; assert it
     fires only when DEBUG is the chosen level.
   - `test_filter_installed_on_root_logger` — `configure()` is called;
     assert the root logger has an instance of `RedactionFilter` attached.
   - `test_non_redacted_fields_preserved` — confirm fields like
     `event`, `paper_id`, `chunk_id` (explicitly OUT of scope per brief)
     pass through untouched at INFO level.

5. **`.claude/docs/security-observability-logging.md`** (new) — audit doc:
   - Threat verbatim from `08-security-observability-ops.md` § Logging.
   - The `REDACTED_FIELDS` allowlist + rationale.
   - Operator guidance: `ARXMCP_LOG_LEVEL=DEBUG` is a developer-only
     setting; production stays at INFO.
   - Failure modes 1, 2, 3 documented (caller contracts: don't embed
     sensitive values in the message template; don't nest sensitive
     values in dict payloads).
   - Deviation from brief: doc placement and structlog rejection.

---

## Acceptance-criteria mapping

| AC (verbatim) | Status / how met |
|---|---|
| `pytest tests/security/test_log_redaction.py` passes | ✓ — new test file, ≥ 6 tests |
| INFO record with `query="Faltings theorem"` has `query` absent from JSON | ✓ — `test_info_record_strips_query` |
| Same record at DEBUG includes `query` | ✓ — `test_debug_record_keeps_query` |
| `body_canonical` / `body_raw_latex` / `mathml` follow the same pattern | ✓ — parametrized test |

---

## Open questions (deferred to implementer)

1. **Production JSON formatter?** The brief speaks of "structured JSON logs
   to stdout" but the codebase emits plain text today. **Synthesis decision:**
   ship the `JsonFormatter` in `server/observability/logging.py` so it's
   importable, but do NOT install it on the root handler in `configure()`
   by default — the redaction works regardless of formatter. Operators who
   want JSON output can subclass / configure later; the test harness uses
   it directly. This keeps the production stdout shape unchanged.

2. **Where to call `configure()` from `server/main.py`?** Replace the
   existing `basicConfig + setLevel` two-step entirely with one
   `configure(cfg.log_level)` call AFTER Config loads. The earlier
   `basicConfig(...)` before `Config()` stays so FATAL config-load
   failures can still log to stderr.

3. **REDACTED_FIELDS additions over time?** The frozenset is module-level
   and asserted-as-literal in the test so additions surface in code review.
   No env-var override for the field set — adding a field requires a code
   change (correct posture).

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| Git commit (feat) | local main | Implementation commit |
| Git commit (rect) | local main | Rectifier commit closing critic findings |
| Git commit (chore) | local main | Finalize state.json |

**No `git push`, no PR, no infra apply, no third-party API write. Purely local.**

---

## Orchestrator synthesis note

Briefs were highly concordant — every divergence was resolvable by picking
the simpler/safer option (stdlib over structlog, custom JSON formatter over
python-json-logger, `.claude/docs/` over `docs/`). No real disagreement.
The synthesis lifts the union of failure modes (each brief surfaced ~5; the
combined list is 7 unique items) and prescribes a tighter test surface than
either brief individually (6 tests vs the brief's 2-case minimum) so AC4's
parametrization-style "follow the same pattern" claim is explicitly proven
rather than inferred.

The `JsonFormatter` is included in the new `server/observability/logging.py`
as importable infrastructure but NOT installed on production handlers — this
keeps the diff's blast radius small (the redaction is the actual security
goal; JSON output shape is orthogonal). A future milestone can flip the
formatter on globally without re-running this audit.
