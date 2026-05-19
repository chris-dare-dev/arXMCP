# Implementation summary — E13_S08

**Milestone:** E13_S08 — Tool-result and request-input redaction in structured logs
**Implementation base SHA:** `c90020917e44c2ef418d3cbd31b5048d82d08914`
**Path:** inline (orchestrator implemented directly in main session)

## One-line summary

Added stdlib `logging.Filter`-based redaction for four sensitive fields
(`query`, `body_canonical`, `body_raw_latex`, `mathml`) at INFO+ level,
plus a `configure()` entry point installed on the root logger from
`server/main.py`. DEBUG opt-in preserves the values for developer triage
with a one-time WARN log.

## Files changed

| File | Change | Why |
|---|---|---|
| `server/observability/log_filter.py` | NEW | `RedactionFilter(logging.Filter)` + `REDACTED_FIELDS` frozenset |
| `server/observability/logging_setup.py` | NEW | `configure(log_level)` (installs filter on root logger, sets level, warn-once on DEBUG) + tests-only `JsonFormatter` |
| `server/main.py` | MODIFIED | Replaces the inline `logging.getLogger().setLevel(cfg.log_level)` with a `configure(cfg.log_level)` call so the redaction filter is installed alongside the level setting |
| `tests/security/test_log_redaction.py` | NEW | 23 tests across 5 classes |
| `.claude/docs/security-observability-logging.md` | NEW | Audit doc: threat verbatim, compliance matrix, caller-side contracts (with good/bad examples), known limitations, deviations from brief |

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| `pytest tests/security/test_log_redaction.py` passes | ✅ | 23 tests pass |
| INFO record with `query="Faltings theorem"` has `query` absent from JSON | ✅ | `TestRedactionFilter::test_faltings_theorem_brief_example_info` |
| Same record at DEBUG includes `query` | ✅ | `TestRedactionFilter::test_faltings_theorem_brief_example_debug` |
| `body_canonical`, `body_raw_latex`, `mathml` follow the same pattern | ✅ | `TestRedactionFilter::test_info_record_strips_sensitive_field` / `test_debug_record_keeps_sensitive_field` parametrized over `sorted(REDACTED_FIELDS)` |

## Brief deviations (all resolved by orchestrator synthesis)

1. **`docs/observability/log-redaction.md` → `.claude/docs/security-observability-logging.md`** — CLAUDE.md §1 restricts `docs/` to operator-facing content. Matches E13_S01–S07 precedent.
2. **`server/observability/logging.py` → `server/observability/logging_setup.py`** — avoids reader confusion with stdlib `logging` (Python 3 absolute imports keep `import logging` resolving to stdlib regardless, but the same-named local module is a grep / readability hazard).
3. **"E07_S08" dependency** — fictional (E07 only has S01–S04). E13_S08 is pure-new infrastructure; no prior scaffolding existed.
4. **structlog rejected** — `structlog` is not in `pyproject.toml`; the codebase is 100% stdlib `logging`. Both researchers independently recommended stdlib; the synthesis adopted it.
5. **JSON formatter shipped but NOT installed by default** — installing globally would change every operator's stdout shape (orthogonal to redaction). `JsonFormatter` is exported as importable infrastructure; the test harness uses it; production output shape is unchanged.

## Tests

- **New test file:** `tests/security/test_log_redaction.py` (23 tests, all passing)
- **Test classes:**
  - `TestRedactionFilter` (10 tests) — parametrized over `sorted(REDACTED_FIELDS)` for both INFO-strips and DEBUG-keeps, plus the brief's verbatim Faltings example for both directions, plus a check that non-redacted fields (`paper_id`, `chunk_id`, `k`) are preserved at INFO
  - `TestRedactedFieldsContract` (2 tests) — pins `REDACTED_FIELDS` as a frozenset with literal membership, so any future change is visible in PR review
  - `TestConfigure` (6 tests) — installs filter on root, idempotent, sets level, DEBUG warns, INFO doesn't warn, warn is one-shot
  - `TestJsonFormatter` (3 tests) — valid JSON output, `levelname` → `level` field rename, `default=str` survives non-JSON-serializable values
  - `TestAuditDocPresence` (1 test) — audit doc exists and references all four redacted fields by name, `ARXMCP_LOG_LEVEL`, and "Threat"

## Project-check status

- `ruff check .` → clean
- `pytest tests/security/test_log_redaction.py` → 23 passed
- Full `pytest` → 2063 passed (+24 from E13_S07 baseline of 2039), 30 pre-existing Windows-platform failures unchanged, 22 skipped, 1 xfailed

## External writes required

None. Purely local implementation: new modules, new tests, new audit doc, one wire-up edit in `server/main.py`.

## Anything notable for the critic

1. **Filter operates on `record.__dict__` only** — nested dicts, `record.args` tuples, and pre-composed message templates are explicitly NOT redacted. The audit doc spells this out with Good/Bad code examples and labels the caller-side contract. A future hardening pass could add deep redaction; that's beyond v1 scope and the brief's ACs are met at the attribute layer.

2. **Filter installed on every root-logger HANDLER** (and on the root logger itself for defense-in-depth) in `configure()`. **F1 rectification (E13_S08 adversary, CRITICAL):** the original implementation installed the filter ONLY on the root logger; that does NOT redact records propagated from child loggers (Python's filter chain only runs parent-logger filters on records ORIGINATING at the parent). Since 24+ production modules use `logging.getLogger(__name__)`, every INFO+ child-logger emit was leaking the sensitive fields. The fix attaches the filter to every handler the root logger owns at configure-time so the filter fires at handler-emit, regardless of originating logger. Covered by `TestConfigure::test_configure_redacts_child_logger_records_via_root_handler`.

3. **The DEBUG warn-once guard is process-global** — `_debug_warning_emitted` lives at module scope. Tests reset it via `_reset_debug_warning_for_tests()` to exercise the warn-fires-once contract. A `pytest` fixture (`_isolate_root` in `TestConfigure`) snapshot/restores the root logger filters and level so the cross-test global state doesn't leak.

4. **`JsonFormatter` exists but is not installed in production by default.** The audit doc explains this trade-off (production stdout shape unchanged; orthogonal to redaction). The formatter would be the right candidate for a future 12-factor JSON output milestone.

5. **The `configure()` call in `server/main.py` is imported lazily inside the function body** to avoid a top-level import cycle risk and to keep import-time work minimal. The existing `logging.basicConfig(level=os.environ.get("ARXMCP_LOG_LEVEL", "INFO"))` BEFORE `Config()` loads is preserved so a Config-load failure can still emit a FATAL log to stderr.

6. **No tool-schema change** — logging is internal infrastructure. No `EXPECTED_TOOL_SCHEMA_SHA256` re-pin needed.

7. **No-fork policy compliance** — no code lifted from `python-json-logger`, `structlog`, or any OSS. The filter is ~10 lines of stdlib `logging.Filter` boilerplate; the formatter is ~15 lines of `json.dumps(record.__dict__)` discipline. Both are reasonable rolled-custom implementations.

8. **No `pyproject.toml` change** — no new runtime dependency.
