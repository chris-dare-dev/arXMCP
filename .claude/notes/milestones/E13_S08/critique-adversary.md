# Critique — E13_S08

**Critic:** adversary
**Generated:** 2026-05-19T14:25:00Z
**Commit range:** c90020917e44c2ef418d3cbd31b5048d82d08914..30b96bc2cdff6be67bc1aea3bc354ca4b464a8ad
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- **Verdict:** SHIP-WITH-FIXES — critical security flaw prevents the filter from protecting child loggers
- **Finding counts:** 1 CRITICAL, 2 HIGH, 0 MEDIUM, 0 LOW
- **Highest-risk file:line:** `server/observability/logging_setup.py:141-142` (filter installed on root logger, ineffective)
- **Root cause:** Python logging does not run parent-logger filters on propagated records; only logger and handler filters fire
- **Test gap:** tests install filter on handlers (`propagate=False`), not on root logger; never exercise the production code path
- **Impact:** child loggers (24 modules use `logging.getLogger(__name__)`) leak redacted fields (`query`, `body_canonical`, `body_raw_latex`, `mathml`) to logs at INFO+ level
- **Acceptance criteria:** AC2–AC4 are NOT met for production code; the milestone depends on broken infrastructure

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — RedactionFilter on root logger does not fire for child-logger records

- **Severity:** CRITICAL
- **Source:** adversary, verified by runtime test
- **File:** `server/observability/logging_setup.py:141-142`
- **What:** The filter is installed via `root.addFilter(RedactionFilter())`, but Python logging's filter chain **does not run parent-logger filters on records propagated from child loggers**. Only the logger's own filters and handler filters fire.
- **Why it matters:** This is a **security failure**. The entire mitigation for Threat 8 depends on redaction running for all loggers. 24 modules in `server/` use `logging.getLogger(__name__)` to create child loggers. A `server/handlers/search.py` child logger emitting `logger.info(..., extra={"query": "Faltings theorem"})` will have the `query` field propagate unmolested to the root handler and escape into logs at INFO level — the exact scenario the filter is supposed to block.
- **Proposed fix:**
  1. Install the filter on every handler attached to the root logger, not on the root logger itself. Change `configure()` to:
     ```python
     root = logging.getLogger()
     for h in root.handlers:
         if not any(isinstance(f, RedactionFilter) for f in h.filters):
             h.addFilter(RedactionFilter())
     if not any(isinstance(f, RedactionFilter) for f in root.filters):
         root.addFilter(RedactionFilter())  # for direct root logs
     ```
  2. Alternatively, install the filter on a high-level logger parent (e.g., `logging.getLogger("server")`) so child logs under `server.*` inherit it. But this is fragile for future submodules.
  3. **Recommended approach:** Install on handlers. The StreamHandler in production will be initialized in `main.py` or a logging config, so the filter can be installed there (similar to how the test's `_make_isolated_logger` does it).
- **Regression guard:** Add a test that:
  - Calls `configure("INFO")`
  - Creates a child logger: `logger = logging.getLogger("server.test.child")`
  - Adds a handler to root to capture output
  - Logs with sensitive field: `logger.info(..., extra={"query": "secret"})`
  - Parses the JSON output and asserts `"query"` is NOT in the JSON keys (currently fails)

### F2 — Test suite does not cover production code path (root-logger filter)

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tests/security/test_log_redaction.py:51-82, 273-278`
- **What:** The test helper `_make_isolated_logger()` uses `propagate=False` and installs the filter on a **handler**, not on the root logger. The test `TestConfigure::test_configure_installs_redaction_filter_on_root()` only asserts the filter is in the filter list; it does NOT verify the filter actually redacts child-logger records.
- **Why it matters:** The test passes (23/23) but the production code is broken (F1). This is a false-positive test result. The brief's AC2 and AC3 say "A log record with `query="Faltings theorem"` at INFO level has `query` absent from the serialized JSON" — the test does NOT exercise the production path where the root logger receives propagated records from child loggers.
- **Proposed fix:**
  1. Update `TestConfigure::test_configure_installs_redaction_filter_on_root()` to:
     - Call `configure("INFO")`
     - Create a **child logger** with a **new name** (not the root)
     - Add a handler to root to capture output
     - Log from the child with a sensitive field
     - Assert the sensitive field is redacted in the output (currently fails)
  2. Remove the `propagate=False` restriction from `_make_isolated_logger()` if the goal is to test the root-logger path, OR create a second test helper that tests via the root.
- **Regression guard:** The test described in F1 is sufficient. Add it alongside the fix.

### F3 — Implementation summary claims test coverage that does not exist

- **Severity:** HIGH
- **Source:** adversary (documentation failure)
- **File:** `implementation-summary.md:66-67`
- **What:** Line 66-67 claims: "the production install path (root logger) is covered by `TestConfigure::test_configure_installs_redaction_filter_on_root`." This is misleading. That test only verifies the filter is installed, not that it works for child loggers.
- **Why it matters:** Misleads the rectifier and masks a security failure. The implementation summary is the implementer's claim of correctness; falsely claiming coverage damages trust in the test results.
- **Proposed fix:** Update the implementation summary to accurately describe what the test does: "asserts the filter is installed on the root's filter list, but does not exercise the root-logger → child-logger propagation path." Recommend the F1 + F2 fixes to the rectifier.
- **Regression guard:** Not a code issue, but documentation accuracy is verified by re-reading.

## What was done well

- **Frozen `REDACTED_FIELDS` as a frozenset** with a test assertion on literal membership (lines 54–59 in `log_filter.py`, test at `test_log_redaction.py:237–242`). This is excellent posture for preventing silent additions of new sensitive fields.
- **One-shot DEBUG WARN guard** mirrors the existing pattern in `server/observability/sanitize.py` (line 48 in `logging_setup.py`, line 151–158 in `logging_setup.py`). Consistent with prior art; guards against accidental verbose-logging-in-production scenarios.
- **Comprehensive test coverage of the filter mechanics** — parametrized tests over `REDACTED_FIELDS` (line 106 in `test_log_redaction.py`) prove each field is stripped at INFO and kept at DEBUG. The tests themselves are well-designed; the gap is that they test the wrong code path.
- **Audit document placement and content** — `.claude/docs/security-observability-logging.md` correctly placed per CLAUDE.md §1, threat statement verbatim, and caller-side contracts documented (Good/Bad examples). Format matches E13_S01–S07 precedent. The document is good; the code doesn't match it.
- **JsonFormatter as importable infrastructure** — not installed in production (preserves stdout shape), available for tests and future adoption (line 78–116 in `logging_setup.py`). Good design separation.
- **Lazy import in `server/main.py`** — `from server.observability.logging_setup import configure as _configure_logging` (line 555 in `server/main.py`) is inside the function to avoid top-level import cycles. Defensive and correct.
- **Idempotent filter installation** — line 141 in `logging_setup.py` checks `if not any(isinstance(f, RedactionFilter) for f in root.filters)` before adding. Safe for repeated `configure()` calls (correctly tested at line 280–292 in `test_log_redaction.py`).

## Recommended rectification order

1. **Fix F1 first** — install the filter on root handlers (or all handlers via a registration path) so child-logger records are actually redacted. This is the core security issue.
2. **Fix F2 second** — add a production-path test that exercises child loggers propagating to root. Ensure AC2–AC4 are actually validated.
3. **Fix F3 last** — update the implementation summary to reflect the corrected understanding.

The fixes are all mechanical (≤20 LOC total) and low-blast-radius. The filter logic itself is sound; only the installation point is wrong.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
