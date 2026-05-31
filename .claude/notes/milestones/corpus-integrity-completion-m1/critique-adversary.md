# Critique — corpus-integrity-completion-m1

**Critic:** adversary
**Generated:** 2026-05-31T00:00:00Z
**Commit range:** ff00f49..c58c19e
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES — implementation matches the literal AC and the synthesis contract; two MEDIUM findings on the test surface (runbook_url presence not asserted; `for: 1h` durations not pinned) should be closed before m2 lands so the regression guard actually guards what its docstring claims.
- Finding counts: 0 CRITICAL, 0 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk file:line: `tests/test_alerts_yaml.py:84-108` — `test_alert_rule_shape` does not assert `annotations.runbook_url` exists, so a future drop of the runbook_url key would not be caught despite the m1 docstring claiming forward regression protection.
- Pattern: the regression guard the implementer added (extending `test_required_alerts_present` with the two new alert names) only pins NAMES, not the SHAPE the AC actually mandates (expr, for, severity, runbook_url). A future change can rename, retarget, or silently strip a key on either of the new rules without test failure.
- Pattern: roadmap accepted-risk on the 404 runbook URL is honored at the YAML+test level, but no `docs/ops/corpus-drift-runbook.md` placeholder was added; if m2 slips or its scope shifts, alerts will fire and operators will land on a github 404.
- `component: corpus` is a NEW label value (existing: storage / server / backup / eval / latexml). Implementer documented this in implementation-summary §"Decisions made beyond the literal AC" but no alertmanager / grafana routing config exists in the repo to verify or break; flagged LOW for awareness only.
- `for: 1h` on `ArXMCPCorpusUnindexedRows` is longer than every prior `for:` value in this file (`5m / 1m / 10m / 1m / 1m`). The rationale (transient startup + rebuild window) is sound per the synthesis but the choice is operator-impacting and would benefit from a unit test pinning the duration so future tuning is intentional.
- All eight axes walked; AC-3 promtool gate skips locally as documented; pre-existing `tests/test_tools_all.py::test_cite_neighbors_wired` failure is verified pre-existing — m1's commit `c58c19e` does NOT touch that file (`git diff` empty), per CLAUDE.md §7 (cite_neighbors handler is a known v1 stub).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — runbook_url presence not asserted by any test

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_alerts_yaml.py:84-108
- **What:** `test_alert_rule_shape` requires `{alert, expr, for, labels, annotations}` exist plus `labels.severity` is canonical, but does NOT assert `annotations.runbook_url` is present or even a string. AC-1 and AC-2 both explicitly call out `runbook_url pointing to docs/ops/corpus-drift-runbook.md`, and the extended `test_required_alerts_present` (tests/test_alerts_yaml.py:50-81) only pins the alert NAMES — a future commit could silently drop the runbook_url annotation on either new rule and every existing test would still pass. The docstring at tests/test_alerts_yaml.py:54-59 explicitly claims forward regression protection that the assertion does not actually provide.
- **Why it matters:** When sibling m2 ships and `docs/ops/corpus-drift-runbook.md` is real, operators encountering a critical-severity `ArXMCPCorpusCountRowsFailed` alert depend on `runbook_url` being present to land on the recovery procedure. The brief's AC names this annotation explicitly; leaving it untested means the AC is not enforced after the implementer's session ends.
- **Proposed fix:** Add a new test `test_runbook_url_present_for_required_alerts` that loads alerts.yml, iterates the required set (same constant the existing `test_required_alerts_present` uses — extract to a module-level set), and asserts `rule["annotations"]["runbook_url"]` is present and starts with `"https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/"`. ~15 LOC.
- **Regression guard:** the new test IS the regression guard.

### F2 — `for: 10m` and `for: 1h` durations not pinned by any test

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_alerts_yaml.py:84-108 + infra/prometheus/alerts.yml:129,159
- **What:** AC-1 mandates `for: 10m` and AC-2 mandates `for: 1h`. `test_alert_rule_shape` requires the `for` KEY exist but does not assert its VALUE. The existing `test_disk_full_threshold_matches_implementation` (tests/test_alerts_yaml.py:111-130) is the precedent for pinning a numeric value against a Python constant — no analogous assertion was added for the two new rules' durations. A future tuning commit could change `for: 10m` to `for: 1d` (defeating the critical-severity tripwire) or `for: 1h` to `for: 5m` (operator-page-storm risk) without any test failure.
- **Why it matters:** The `for:` duration is the ONLY thing distinguishing a one-shot startup hiccup (suppressed by `for: 10m`) from a persistent count_rows() outage (the actual alarm condition). The synthesis §1 explicitly fixed these durations as part of the contract. Leaving them untested means the contract is unenforced.
- **Proposed fix:** Add `test_corpus_integrity_alert_durations` asserting `ArXMCPCorpusCountRowsFailed["for"] == "10m"` and `ArXMCPCorpusUnindexedRows["for"] == "1h"`. ~12 LOC. Pairs naturally with F1's runbook_url test in the same loop.
- **Regression guard:** the new test IS the regression guard.

### F3 — runbook_url 404 has no placeholder file or test gate

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/prometheus/alerts.yml:143,172 + missing docs/ops/corpus-drift-runbook.md
- **What:** Both new rules point `runbook_url` at `https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/corpus-drift-runbook.md`. That file does not exist (verified `find /Users/chris.dare/Personal/SourceCode/arXMCP/docs/ops -name "corpus-drift-runbook.md"` returns empty). The roadmap's "either order" claim (plans/corpus-integrity-completion-roadmap.md:188) is the documented accepted-risk, and the implementation summary §"Adversary critic preparation" reiterates this — but no test or precommit hook asserts the URL resolves once both milestones ship. If sibling m2 slips, is descoped, or renames the file, alerts will fire in production-equivalent and operators will land on a github 404 page with no test signal that the link is dead. The roadmap KR-5 promised "every new alert rule from KR-2 references it; an operator hitting any new alert can land on a runnable next step" — m1 honors the rule-references-it half but not the lands-on-step half.
- **Why it matters:** The `runbook_url` annotation is the only path-of-resolution data an operator gets at alert time. A 404 is worse than no runbook_url because it suggests-then-betrays. This is the named anti-pattern from the agent-memory "deferred-without-tracking" class (see milestone-adversary MEMORY.md entry `2026-05-28 — textbook-ingest-m5`).
- **Proposed fix:** EITHER (a) add a minimal placeholder `docs/ops/corpus-drift-runbook.md` in this milestone with a "PLACEHOLDER — see sibling m2" header and the alert names listed, so the URL at least resolves to *something* operator-readable; OR (b) add a test marker / xfail gate `test_corpus_drift_runbook_exists` that asserts `docs/ops/corpus-drift-runbook.md` is a file. xfail until m2 ships, then auto-passes — provides a forcing function on the m2 ship and unambiguous test signal that the broken link is a known-deferred state, not a regression. Option (a) is the more operator-friendly minimum.
- **Regression guard:** the placeholder file existence assertion (option b) IS the regression guard; with option (a) the deliverable IS the guard (the placeholder text says PLACEHOLDER so a future ack-and-forget is obvious).

### F4 — `component: corpus` introduces a new label value with no documented routing impact

- **Severity:** LOW
- **Source:** adversary
- **File:** infra/prometheus/alerts.yml:132,162
- **What:** The two new rules introduce `component: corpus` — the 6th distinct value in the file (existing: `storage`, `server`, `backup`, `eval`, `latexml`). The implementation summary §"Decisions made beyond the literal AC" §1 acknowledges this as a "new value but NOT test-restricted" and notes the single-workstation target makes Grafana/Alertmanager routing rule updates informational rather than blocking. No alertmanager / grafana / routing config exists anywhere in `/Users/chris.dare/Personal/SourceCode/arXMCP/` to validate against (grep returns only the implementation-summary's own mention plus the YAML). Pattern-consistent with the existing rules; the LOW severity reflects that this is correctly-justified scope expansion, not a hidden risk.
- **Why it matters:** When the eventual operator-side prometheus/alertmanager configuration lands (E14_S09 per the alerts.yml header comment), the routing logic will need a `component=corpus` clause or the two new alerts will fall through to the default route. Worth surfacing in the implementation-summary as a known future-operator follow-up rather than just an "informational" note.
- **Proposed fix:** No code change; consider adding a single bullet to the milestone state's `follow_ups` field naming the future Grafana/Alertmanager `component=corpus` routing requirement, so it surfaces in the next operator-deployment milestone's research scan.
- **Regression guard:** none required (LOW).

### F5 — implementation-summary line citations are off by 2-8 lines

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/notes/milestones/corpus-integrity-completion-m1/implementation-summary.md:11-12
- **What:** Implementation summary claims AC-1 lives at "Lines 112-146 of the updated infra/prometheus/alerts.yml" and AC-2 at "Lines 148-180". Actual locations: AC-1 is lines 112-143 (off by -3 at the tail), AC-2 is lines 145-172 (off by -3 to -8). The rule blocks are at the right relative positions but every line number cited is wrong.
- **Why it matters:** Adversary critique relies on the implementation summary for orientation; wrong line numbers cause the critic to read the wrong window the first time, costing time on a structured-data-only milestone where the diff is small enough to read in full anyway. On a larger milestone this drift would be a real cost. Pattern: implementation-summary line citations should be regenerated AFTER all edits, not before.
- **Proposed fix:** Re-cite as "AC-1: lines 112-143" and "AC-2: lines 145-172". One-character edit each.
- **Regression guard:** none required (LOW).

## What was done well

- Inline code comments (alerts.yml:112-126 and :145-156) carry the rationale into the file the operator reads at alert-handling time — including the exact reason no third "above-tolerance drift" rule was added (AC-4 met as documented behavior, not silent omission).
- The two rules' label and annotations shape mirrors the existing 5 rules byte-for-byte (severity + component labels; summary + description + runbook_url annotations) — pattern-consistency is load-bearing for any future YAML-shape lint.
- Implementation summary §"Decisions made beyond the literal AC" explicitly enumerates the two going-beyond-the-AC choices (`component: corpus`, `test_required_alerts_present` extension) with the synthesis FM-references that ground them — exactly the right way to document deliberate scope expansion.
- AC-3's promtool gate is correctly handled via the EXISTING `pytest.mark.skipif(shutil.which("promtool") is None, ...)` pattern; no new skip pattern needed — the synthesis Q2 resolution is honored.
- AC-4's "no fourth rule" decision is documented inline AND in the implementation summary with explicit reference to the upstream scout's CAND-1 challenger MINOR resolution — a negative AC handled with explicit documentation rather than silent omission is the right pattern.
- The `test_required_alerts_present` extension (tests/test_alerts_yaml.py:50-81) is the minimum-viable forward regression guard — pins the two new alert NAMES so a future commit cannot silently drop either rule (the named-protection slice; the shape-protection slice is F1+F2 above).
- All 6 non-promtool tests in tests/test_alerts_yaml.py pass; promtool test correctly skips on dev. No ruff regressions.
- Pre-existing `tests/test_tools_all.py::test_cite_neighbors_wired` failure correctly identified as unrelated to m1 (verified: m1's diff does not touch that file; the cite_neighbors handler stub is the known root cause documented in CLAUDE.md §7).
- Implementation correctly chose to APPEND inside the existing `groups[0].rules[]` array rather than introduce a new `groups:` block — FM-4 in the synthesis was a real risk and was avoided.
- Single feat commit, conventional-commit subject + co-author trailer + GPG signature all conform to CLAUDE.md §4.3 / §4.4 — milestone-pipeline three-commit-per-milestone pattern is on track.

## Recommended rectification order

1. **F1** + **F2** as a single test addition (~25 LOC in tests/test_alerts_yaml.py) — closes the runbook_url-and-duration unenforced-AC gap. Same file, same edit; do both or neither.
2. **F3** as option (a) — drop a placeholder `docs/ops/corpus-drift-runbook.md` so the 404 stops being a 404 (~15 LOC of skeleton markdown referencing the two alert names). Cheaper than option (b) and matches the roadmap's KR-5 "operator hitting any new alert can land on a runnable next step" clause sooner.
3. **F4** as a follow-up note in `state.json` `follow_ups` array — no code change, ~1 LOC of bookkeeping.
4. **F5** as a one-character correction in the implementation-summary — defer-friendly; do only if other edits already touch that file.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
