# Critique — corpus-integrity-observability-e2

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** 55e4e8830881ab4e0929ebd063780eb64533d970..4706ecf2fa3d37b48aae55bcd8963c32357a6898
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the code is correct on every load-bearing path (FM-2
  redaction-bypass guard is real + tested, gauges/fields all exist, hashes
  frozen); the open issues are doc-drift + one missing test, not behavior bugs.
- Finding counts: 0 CRITICAL, 0 HIGH, 3 MEDIUM, 1 LOW.
- Highest-risk: `.claude/docs/security-observability-logging.md:217-221,251-256`
  — the operator-facing SECURITY doc now states a false logging default.
- Axis 1 (cache byte-stability) CLEAN: tool-schema + prompts diff is empty;
  `test_server_tool_schema.py` + `test_prompts.py` both pass green.
- Axis 3 (security) CLEAN on mechanics: `configure()` installs `JsonFormatter`
  on the SAME redaction-filtered handler; `uvicorn.run(log_config=None)` keeps
  uvicorn on the configured root logger; log fields are aggregate-only.
- The FM-2 SECURITY-CRITICAL guard (`test_json_format_installs_formatter_and_keeps_redaction`)
  asserts both formatter-on-handler AND filter-on-handler + an end-to-end
  redaction check — it WOULD fail if a 2nd handler were added. Strong.
- Cross-test-pollution risk from the JSON default is handled: `_isolate_root`
  snapshots/restores handler formatters; a broad 153-test slice ran green.
- The recurring failure mode this run is doc/docstring drift (operator doc +
  in-module docstring still say "JSON NOT installed by default" — now false).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Operator security doc states a now-false logging default

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** .claude/docs/security-observability-logging.md:217-221 (also :251-256, :262)
- **What:** The operator-facing security/observability doc still says "The
  `JsonFormatter` is shipped but NOT installed by default. Production stdout
  shape is unchanged — plain text" (:217-221) and "JsonFormatter is exported
  but not installed by default ... the codebase emits plain text today ... keep
  production output unchanged" (:251-256). e2 flips JSON to the DEFAULT
  (`server/config.py:271` `log_format: str = "json"`;
  `server/observability/logging_setup.py:174-179` installs `JsonFormatter` when
  `want_json`). Line :262 also still reads `configure(cfg.log_level)` whereas
  `server/main.py:732` now calls `configure(cfg.log_level, cfg.log_format)`.
- **Why it matters:** This is the operator-facing claim about the production
  logging threat surface (the doc the in-code comments at `server/main.py:727`
  and `logging_setup.py` reference). An operator reading it to reason about what
  lands on stdout (and whether redaction is the only transform) is misled about
  the actual default shape. Same doc-drift class flagged on prior milestones
  (security-doc must move in lockstep with the code it describes).
- **Proposed fix:** Update :217-221 and :251-256 to "JSON is the 12-factor
  default; `ARXMCP_LOG_FORMAT=text` is the escape hatch; redaction runs before
  formatting in both cases (`configure()` installs the filter, then the
  formatter, on the same handler)." Update :262 to `configure(cfg.log_level,
  cfg.log_format)`. Optionally add an `ARXMCP_LOG_FORMAT` row to the AC table.
- **Regression guard:** Extend `TestAuditDocPresence::test_audit_doc_exists`
  (tests/security/test_log_redaction.py:569) to assert the doc body contains
  `ARXMCP_LOG_FORMAT` and does NOT contain the stale phrase "emits plain text
  today" / "NOT installed by default" — so a future default flip can't leave the
  doc stale silently.

### F2 — In-module docstring contradicts same-file code (JSON default)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/observability/logging_setup.py:20-22
- **What:** The module docstring still reads "The formatter is NOT installed by
  default — the redaction works regardless of the output format, and changing
  the default stdout shape is out of scope for an audit milestone." The e2 code
  in the SAME file (`logging_setup.py:174-179`) now installs `JsonFormatter` by
  default (`configure(log_level, log_format="json")`, `want_json` true by
  default). The docstring directly contradicts the function it documents.
- **Why it matters:** A reader of this module (the canonical logging setup) gets
  an actively-wrong contract statement at the top of the file. Stale-docstring
  anti-pattern: the milestone "ships X" but the docstring that said "X is out of
  scope" was not retracted. Cheap to fix and prevents future confusion about
  whether JSON is opt-in or default.
- **Proposed fix:** Replace :20-22 with: "`JsonFormatter` is installed by
  default (12-factor JSON to stdout, per `08-security-observability-ops.md`
  §Logging); `configure(log_format='text')` opts out. The formatter always runs
  AFTER `RedactionFilter` on the same handler, so the format choice never
  affects redaction." Leave the `:param log_format:` block at :153-158 as-is
  (it is already correct).
- **Regression guard:** No code regression guard needed (docstring-only); the
  F1 doc-presence assertion can be the single guard for the "JSON is default"
  claim across both surfaces, or add a one-line test asserting
  `configure.__doc__` / module docstring no longer contains "NOT installed by
  default" if the rectifier wants belt-and-suspenders.

### F3 — `/readyz` `-1`→`null` branch is reasoned, not tested (AC2 gap)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/health.py:253 (test: tests/test_server_startup.py:214-226)
- **What:** `server/health.py:253` renders `"chunk_count": None if
  startup_count < 0 else startup_count`. The only test
  (`test_readyz_200_body_carries_corpus_counts`, startup_count=2) covers the
  happy path. The `-1`→`null` sentinel branch (m2 FM-2: `count_rows()` failed at
  startup) is covered ONLY by the inline comment and the AC reasoning — no test
  exercises it. A repo-wide grep confirms no other test asserts the `/readyz`
  `null` rendering. Synthesis §5 AC2 explicitly required "a test asserts both
  keys present + the `-1`→`null` rendering."
- **Why it matters:** The negative branch is the entire point of CAND-6b
  (surface the count-unavailable state distinctly from a real 0). A future edit
  that drops the `< 0` guard (e.g. emitting `-1` to the probe) would pass the
  whole suite. The logic is correct by inspection today, so this is a
  test-surface gap, not a behavior bug — hence MEDIUM, not HIGH.
- **Proposed fix:** Add `test_readyz_200_body_chunk_count_null_on_sentinel` to
  `TestReadinessTransition`: build a `warm_app` whose `resources.startup_chunk_count
  == -1` (monkeypatch the attribute on the attached `Resources`, mirroring the
  `startup_chunk_count=-1` construction in
  `tests/test_corpus_count_reconciliation.py:390`), GET `/readyz`, and assert
  `body["chunk_count"] is None` while `body["marker_chunk_count"]` still equals
  the marker count.
- **Regression guard:** The test above IS the guard (≤ 15 LOC, additive).

### F4 — corpus_version cell value unasserted; `_count_cell` conflates count/version

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/daily_metrics_report.py:391,406 (test: tests/test_daily_metrics_report.py:271-299)
- **What:** The `## Corpus integrity` section renders `corpus_version` via
  `_count_cell(corpus_ver)` (`daily_metrics_report.py:406`, helper at :393).
  `TestCorpusIntegritySection` sets `version=645.0` in the fixture
  (`test_daily_metrics_report.py:258,268`) but never asserts the rendered
  `corpus_version` cell value — only marker/actual cells and Status. Separately,
  `_count_cell` is named for "count" semantics (it renders `n/a` for negative)
  but is reused to render the corpus VERSION (an MVCC integer); the negative-→-na
  rule is meaningless for a version number.
- **Why it matters:** Low blast radius — the rendering path is exercised by the
  marker/actual assertions, so a crash would be caught; only the specific
  corpus_version value pin and the helper-name clarity are missing. A renamed or
  dropped corpus_version gauge would not be caught by the integrity-section
  tests.
- **Proposed fix:** Add `assert "| corpus_version | 645 |" in out` to
  `test_section_present_and_matching_is_ok`. Optionally rename the local helper
  to `_int_cell` (or add a one-line comment that it doubles for the version
  cell) to drop the count-only implication. Defer if the rectifier is tight on
  budget — no behavior change.
- **Regression guard:** The added assertion above.

## What was done well

- FM-2 (SECURITY-CRITICAL) is implemented exactly to the synthesis §3 D2: the
  formatter is set on the same handler that just received the `RedactionFilter`
  (`logging_setup.py:175-179`), never a 2nd handler — and the guard test asserts
  formatter-on-handler, filter-on-handler, AND an end-to-end redaction.
- The `write_chunks_complete` emission site is correct: INSIDE the marker `try`
  AFTER `write_corpus_version_marker(...)` (`ingest/store.py:950-958`), so the
  counts are bound and the event fires only on the success path — the
  except-path stays the sole failure signal, avoiding a spurious "complete."
- The `extra=` keys (`event`, `corpus_version`, `chunk_count`, `paper_count`)
  are all non-reserved LogRecord attributes — no KeyError-at-log-time collision.
- BP1 + tool-schema discipline respected: no MCP tool, no `server/prompts.py`
  change; `test_server_tool_schema.py` + `test_prompts.py` verified green and
  the diff for those files is empty.
- `_isolate_root` was correctly hardened to snapshot/restore handler formatters
  (test_log_redaction.py:269,277-279), pre-empting JSON-default cross-test
  pollution of `caplog.text`; a 153-test slice across log/startup/re-embed/
  notebook-script suites ran green.
- The `-1`/NaN sentinels are handled consistently across both surfaces:
  `/readyz` renders `null` (`health.py:253`), the daily report renders `n/a`
  and does NOT raise `[DIVERGED]` (`daily_metrics_report.py:394-413`), with
  divergence gated on both values being real and non-negative.
- `log_format` validation mirrors the established sibling pattern (strip +
  lower-case, `{"json","text"}`, `ValueError` with the env-var name in the
  message) — `config.py:661-670` — and is covered by 3 validator tests.
- `uvicorn.run(..., log_config=None)` (`main.py:785`) is the correct choice to
  keep uvicorn access logs on the redaction-filtered + JSON-formatted root
  logger, so the JSON default does not open an un-redacted uvicorn handler.
- Tier-sequencing is sound: all three gauges the report reads exist in
  `server/health.py:93,103-117` (e1/m2), and `Resources.corpus_info` /
  `startup_chunk_count` (resources.py:267,331) are already startup-cached — e2
  is genuinely pure presentation with zero new I/O.
- No banned patterns, no new dependency, no vendored code, no doc placed outside
  `.claude/`; the structured-log + empty-chunks behavior is pinned by tests
  (test_store.py:1632-1666, 1718-1747).

## Recommended rectification order

1. F1 — fix the operator security doc (`.claude/docs/security-observability-logging.md`);
   highest blast radius (operator-facing security claim) and the F1 doc-presence
   assertion also becomes the guard for F2.
2. F2 — retract the stale module docstring (`logging_setup.py:20-22`); trivial,
   same "JSON-is-default" claim as F1, do them together.
3. F3 — add the `/readyz` `-1`→`null` test; closes the AC2 coverage gap (≤15 LOC).
4. F4 — add the corpus_version cell assertion (and optional helper rename);
   LOW, fold in only if cheap.

## Rectification status

- **F1 (MEDIUM) — FIXED.** Updated `.claude/docs/security-observability-logging.md`:
  the threat-surface bullet (now "JSON is the default as of e2;
  `ARXMCP_LOG_FORMAT=text` is the escape hatch; redaction runs before formatting"),
  the deviation bullet (now "deferred at E13_S08, shipped at e2"), and the
  `configure(cfg.log_level)` → `configure(cfg.log_level, cfg.log_format)` reference.
  Regression guard: `TestAuditDocPresence::test_audit_doc_exists` now asserts the doc
  contains `ARXMCP_LOG_FORMAT` and no longer contains "Production stdout shape is
  unchanged".
- **F2 (MEDIUM) — FIXED.** Replaced the stale module docstring in
  `server/observability/logging_setup.py` ("NOT installed by default ... out of scope
  for an audit milestone") with the e2 reality ("installed BY DEFAULT; `log_format=
  'text'` opts out; always runs after RedactionFilter"). Guarded transitively by the
  F1 doc-presence assertion + the existing FM-2 behavior test.
- **F3 (MEDIUM) — FIXED.** Added
  `TestReadinessTransition::test_readyz_200_body_chunk_count_null_on_sentinel`: sets
  `startup_chunk_count = -1` on the attached Resources post-startup, GETs `/readyz`,
  asserts `chunk_count is None` and `marker_chunk_count == 2`. Closes the AC2
  `-1`→null coverage gap; fails if the `< 0` guard is dropped.
- **F4 (LOW) — FIXED (cheap).** Added `assert "| corpus_version | 645 |"` to
  `test_section_present_and_matching_is_ok`; renamed the local `_count_cell` →
  `_int_cell` with a comment that it renders both counts and the version (the
  negative→n/a guard is a no-op for the never-negative version).

**Invalidation summary:** 4 findings (0 CRITICAL, 0 HIGH, 3 MEDIUM, 1 LOW). All 4
FIXED. 0 invalidated (no CRITICAL/HIGH to re-verify; the MEDIUM doc-drift + test-gap
findings were all confirmed accurate). Adversary invalidation rate: 0%.
