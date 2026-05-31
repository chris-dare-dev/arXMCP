# Critique (merged) — corpus-integrity-completion-m1

**Merged by:** main orchestrator session
**Generated:** 2026-05-31
**Critics fired:** adversary + infra-safety (Makefile/CI/Dockerfile not touched — those axes flagged N/A by infra-safety)
**Commit range:** `ff00f49..c58c19e` (single feat commit)
**Verdict:** SHIP-WITH-FIXES — both critics independently arrived at the same verdict.

## Executive summary (orchestrator)

- **0 CRITICAL, 0 HIGH, 4 MEDIUM, 3 LOW.** Combined finding count after merge: 7 (4 from adversary, 2 from infra-safety, 1 shared theme).
- **Strongest signal: cross-critic agreement on the runbook_url 404.** Adversary F3 and infra-safety IS1 are the same finding — `docs/ops/corpus-drift-runbook.md` does not yet exist; both new alert rules' `runbook_url` resolves to a GitHub 404 until sibling m2 ships. Both critics recommend the same fix (ship a stub runbook file in m1). This is the highest-leverage rectification.
- **Second-strongest signal: test-surface gaps.** Adversary F1 and F2 both observe that the implementer's extension of `test_required_alerts_present` pins NAMES but not SHAPE — `runbook_url` annotation presence and `for:` duration values are not asserted by any test. AC-1 and AC-2 explicitly name those fields; leaving them untested means the AC is not enforced after the implementer's session ends. Cheap fix (~25 LOC combined test).
- **Three LOW findings.** F4 (new `component: corpus` value — informational), F5 (implementation-summary line citations off by 2-8 lines — cosmetic), IS2 (`for: 1h` calibration lacks corpus-scale citation — comment-only). All deferrable per the MEDIUM≤30LOC rubric.
- **All 8 adversary axes walked + 10 infra-safety axes walked.** No CRITICAL or HIGH findings — the implementation matches the literal AC + synthesis contract; the open items are test-surface tightenings, not behavior correctness.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement (highest priority)

- **F3 (adversary) + IS1 (infra-safety) — runbook_url 404 until sibling m2 lands.** Both critics flagged the same file:line (`infra/prometheus/alerts.yml:143,172`) at MEDIUM severity with the same fix recommendation (stub the `docs/ops/corpus-drift-runbook.md` file). Treat as ONE finding for rectification purposes; close with a single edit.

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings — adversary

### F1 — runbook_url presence not asserted by any test

- **Severity:** MEDIUM
- **File:** `tests/test_alerts_yaml.py:84-108`
- **What:** `test_alert_rule_shape` requires `{alert, expr, for, labels, annotations}` exist plus `labels.severity` is canonical, but does NOT assert `annotations.runbook_url` is present. AC-1 + AC-2 explicitly name `runbook_url` — a future commit could silently drop it on either new rule and every existing test would still pass.
- **Proposed fix:** new test `test_runbook_url_present_for_required_alerts` iterates the required-set, asserts `rule["annotations"]["runbook_url"]` is present and starts with `"https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/"`. ~15 LOC.

### F2 — `for:` durations not pinned by any test

- **Severity:** MEDIUM
- **File:** `tests/test_alerts_yaml.py:84-108` + `infra/prometheus/alerts.yml:129,159`
- **What:** `test_alert_rule_shape` requires the `for` key but not its value. AC-1 mandates `for: 10m`; AC-2 mandates `for: 1h`. A future tuning commit could change either without test failure. Precedent for pinning a numeric value against a constant exists in `test_disk_full_threshold_matches_implementation`.
- **Proposed fix:** new test `test_corpus_integrity_alert_durations` asserting both rules' `for` values match. ~12 LOC. Combine with F1's loop.

### F3 — runbook_url 404 has no placeholder file or test gate (SHARED with IS1)

- **Severity:** MEDIUM
- **File:** `infra/prometheus/alerts.yml:143,172` + missing `docs/ops/corpus-drift-runbook.md`
- **What:** Both new rules point `runbook_url` at a non-existent file. The roadmap's "either order" claim acknowledges this, but no test asserts the URL resolves and no placeholder file exists. The named anti-pattern from `milestone-adversary` memory: deferred-without-tracking class.
- **Proposed fix (preferred):** (a) Add `docs/ops/corpus-drift-runbook.md` with a "PLACEHOLDER — see sibling m2" header and the alert names listed. Operator-friendly minimum; stops the 404 immediately.

### F4 — `component: corpus` introduces new label value with no documented routing impact

- **Severity:** LOW
- **File:** `infra/prometheus/alerts.yml:132,162`
- **What:** New label value not present in existing 5 rules. Implementation summary notes it as "informational" but no operator-routing-config exists in the repo to validate against.
- **Proposed action:** Defer — record in state.json `follow_ups` for the future operator-deployment milestone.

### F5 — implementation-summary line citations are off by 2-8 lines

- **Severity:** LOW
- **File:** `.claude/notes/milestones/corpus-integrity-completion-m1/implementation-summary.md:11-12`
- **What:** Cited lines for AC-1 ("112-146") and AC-2 ("148-180") are off — actual locations are 112-143 and 145-172.
- **Proposed action:** Defer — cosmetic; if other rect edits already touch the summary, fix inline; otherwise leave.

## Findings — infra-safety

### IS1 — Runbook URL 404 until sibling m2 lands (SHARED with F3)

- **Severity:** MEDIUM
- **File:** `infra/prometheus/alerts.yml:143,172`
- See F3 above — same finding, same proposed fix.

### IS2 — `for: 1h` calibration lacks corpus-scale citation

- **Severity:** LOW
- **File:** `infra/prometheus/alerts.yml:159`
- **What:** Inline comment says `for: 1h` "filters any transient startup + rebuild window" but cites no measured/estimated rebuild time. `1h` is 6× the next-longest existing `for:` duration.
- **Proposed action:** Defer — comment-only nit; can be addressed in m2 alongside the runbook content.

## What was done well (combined, deduped)

- **Inline code comments in alerts.yml carry rationale into the file the operator reads at alert-handling time** — including the explicit reason no third "above-tolerance drift" rule was added (AC-4 met as documented behavior).
- **Two rules' label and annotations shape mirrors existing 5 rules byte-for-byte** — pattern-consistency is load-bearing.
- **Implementation summary §"Decisions made beyond the literal AC" explicitly enumerates the two scope additions** (`component: corpus`, `test_required_alerts_present` extension) with synthesis FM-references that ground them.
- **AC-3's promtool gate correctly handled via the EXISTING `pytest.mark.skipif(shutil.which("promtool") is None, ...)` pattern** — no new skip pattern needed.
- **AC-4's "no fourth rule" decision documented inline AND in the implementation summary** with explicit reference to the scout's CAND-1 challenger MINOR resolution.
- **`test_required_alerts_present` extension is the minimum-viable forward regression guard** — pins names; F1+F2 critiques add shape-protection on top.
- **All 6 non-promtool tests pass; promtool test correctly skips on dev.** No ruff regressions.
- **Pre-existing `tests/test_tools_all.py::test_cite_neighbors_wired` failure correctly identified as unrelated to m1** — m1's diff does not touch that file; the cite_neighbors handler stub is the known root cause documented in CLAUDE.md §7.
- **Implementation correctly chose to APPEND inside `groups[0].rules[]` rather than introduce a new `groups:` block** — synthesis FM-4 was a real risk avoided.
- **Both PromQL expressions are syntactically unambiguous: `== -1` and `> 0`** — simplest and most portable PromQL form for single-workstation deployments.
- **The `-1` sentinel design eliminates the entire class of cold-clone false-positive alerts** documented as synthesis FM-2 — empty table = `count_rows() = 0`, so `actual == -1` fires only on genuine API failure.
- **`ArXMCPCorpusUnindexedRows` correctly excludes the `-1` unknown sentinel** (`-1 > 0` is false), preventing double-firing with `ArXMCPDegradedMode` when the index API is broken.
- **Deployment-topology comment in the alerts.yml header (lines 1-16) is accurate** — file correctly scoped as operator-managed infrastructure outside arXMCP's own docker-compose.
- **Single feat commit, conventional-commit subject + co-author trailer + GPG signature** all conform to CLAUDE.md §4.3 / §4.4 — milestone-pipeline three-commit-per-milestone pattern is on track.

## Recommended rectification order (orchestrator)

1. **F1 + F2 as a single test addition** (~25 LOC in `tests/test_alerts_yaml.py`) — closes the runbook_url + duration unenforced-AC gap. Same file, same edit; do both.
2. **F3 + IS1 (cross-critic-shared) — ship the stub `docs/ops/corpus-drift-runbook.md`** with a PLACEHOLDER header, the two alert names, the brief recovery procedure pointer, and a "see sibling m2 for full content" reference. ~50 LOC of skeleton markdown. Stops the 404 + matches roadmap KR-5's "operator hitting any new alert can land on a runnable next step" clause sooner.
3. **F4, F5, IS2 — defer** per the LOW rubric. Record under `deferred_findings` in state.json.

## Rectification status

- **F1 | MEDIUM | fixed** in rect commit (see below) — new `test_runbook_url_present_for_required_alerts` in `tests/test_alerts_yaml.py` iterates the required-alert set and asserts each rule's `annotations.runbook_url` starts with the project's `https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/` prefix. Regression guard: the new test IS the guard.
- **F2 | MEDIUM | fixed** in rect commit — new `test_corpus_integrity_alert_durations` pins `ArXMCPCorpusCountRowsFailed["for"] == "10m"` and `ArXMCPCorpusUnindexedRows["for"] == "1h"` via a module-level `_CORPUS_INTEGRITY_RULES` map. Regression guard: the new test IS the guard.
- **F3 | MEDIUM | fixed** in rect commit (CROSS-CRITIC — shared with IS1) — new `docs/ops/corpus-drift-runbook.md` placeholder file ships with PLACEHOLDER header + the two alert names + minimal "Immediate triage" sections operators can act on during the m1→m2 gap + explicit pointer to m2 for full content. Stops the GitHub 404 immediately. Regression guard: the file's existence is sufficient — `runbook_url` resolution is verified manually at this stage; the F1 test catches drop-of-the-link regression.
- **IS1 | MEDIUM | fixed** in rect commit (CROSS-CRITIC — shared with F3) — same fix as F3 above.
- **F4 | LOW | deferred** — recorded in state.json `deferred_findings`. The `component: corpus` label routing impact lands in a future operator-deployment milestone (E14_S09 per the alerts.yml header comment) when Grafana/Alertmanager routing config is authored.
- **F5 | LOW | deferred** — implementation-summary line citations are off by 2-8 lines; cosmetic. Not amending the implementation-summary in the rect commit (the rect commit's own commit body documents the line numbers correctly for the new files).
- **IS2 | LOW | deferred** — `for: 1h` calibration comment lacks corpus-scale citation. Comment-only nit; can be folded into m2 alongside the full runbook content (which will likely cite the rebuild window in operator-actionable form).

**Invalidation rate:** 0/7 findings invalidated on re-verify (every cited file:line still matched the finding when re-read pre-fix). Both critics calibrated cleanly; no prompt-tuning note in the rect commit body.
