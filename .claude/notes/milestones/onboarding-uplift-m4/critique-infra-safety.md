# Critique — onboarding-uplift-m4

**Critic:** infra-safety
**Generated:** 2026-05-31T00:00:00Z
**Commit range:** 574f1c2..071d4b1
**Verdict:** SHIP

## Executive summary

- Verdict: SHIP — no blocking infra issues; the Makefile change is clean and consistent.
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 1 LOW findings.
- `.PHONY` stanza placement, env-var injection form, version-check pattern, help-block
  column alignment, and idempotence are all correct.
- The one MEDIUM finding is a pre-existing `.PHONY`-comment / `make help` label mismatch
  ("FIRST-TIME?" vs "FIRST TIME?") that the new `up-wizard` addition exposes but did not
  introduce.
- The one LOW finding is that the `make help` FIRST-TIME section header still reads
  "(onboarding-uplift-m2)" even though m4 extends it with a new target; a cosmetic nit.
- No CI surface was touched; no GitHub Actions files in diff — that axis is N/A.
- `make test` dry-run still invokes ruff + pytest correctly (unchanged by this diff).
- Total `make help` output: 58 lines — well within the 120-line pagination threshold.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — PHONY comment label "FIRST-TIME?" vs help label "FIRST TIME?"

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** Makefile:6-8 (`.PHONY` stanza comment) vs Makefile:40 (`make help` echo)
- **What:** The `.PHONY` stanza comment reads `# FIRST-TIME?` (with hyphen) while the
  `make help` section header reads `FIRST TIME? (onboarding-uplift-m2)` (no hyphen). Per
  the m3 critique IS1 note in MEMORY.md, the project convention is that each `.PHONY`
  stanza comment "pairs with the section it describes." The labels do not match.
- **Why it matters:** The `.PHONY` stanza promises a 1:1 alignment with the help section
  it guards. A future contributor reading the stanza comment to decide where to add a
  new target sees "FIRST-TIME?" but the rendered help section says "FIRST TIME?" —
  taxonomy drift silently accumulates. The m3 memory note (onboarding-uplift-m3) flags
  this exact pattern as MEDIUM.
- **Proposed fix:** Align the `.PHONY` stanza comment to match the help section label.
  Change line 6 from:
  ```
  # FIRST-TIME? — the onboarding-uplift verbs an operator needs on a
  ```
  to:
  ```
  # FIRST TIME? — the onboarding-uplift verbs an operator needs on a
  ```
  (1 LOC change; well within the ≤30 LOC MEDIUM threshold.)
- **Regression guard:** `grep -n "FIRST.TIME" Makefile` should show the same label in
  the stanza comment (line 6) and in the `@echo` line (line 40) after the fix.

### IS2 — help section header epoch tag "(onboarding-uplift-m2)" is stale

- **Severity:** LOW
- **Source:** infra-safety
- **File:** Makefile:40
- **What:** The FIRST TIME? section header in `make help` reads
  `(onboarding-uplift-m2)` — it was written when m2 introduced that section. The m4
  commit adds `up-wizard` to that section without updating the epoch tag.
- **Why it matters:** Purely cosmetic; the section is still correct. The epoch tag can
  mislead a future developer into thinking the section hasn't been touched since m2.
- **Proposed fix:** Either drop the epoch tag entirely
  (`FIRST TIME?:`) or update it to reflect the last milestone that extended the section
  (`FIRST TIME? (onboarding-uplift-m4):`). Defer to m5.

## What was done well

- `.PHONY` placement is correct: `up-wizard` was appended to the FIRST-TIME stanza
  (Makefile:8) rather than to CORPUS LIFECYCLE or OPS / MAINTENANCE — exactly the right
  group per the m3 convention.
- Help-block column alignment is exact: `make up-wizard` indents its description to
  column 33, matching `make bootstrap`, `make ingest`, `make up`, and `make notebook-list`
  — all verified to column 33 by character count.
- Env-var injection form is correct: `ARXMCP_BOOTSTRAP_MODE=1` appears as a leading
  assignment on the same recipe line before `$(PYTHON)` (Makefile:172), which is the
  POSIX-standard per-command env override. This is the only env-var-as-leading-assignment
  in the Makefile (no prior art to diverge from), and the form is correct.
- Version-check stanza in `up-wizard` (Makefile:169-171) is a byte-for-byte copy of the
  pattern in `up`, `test`, `eval`, and all other targets: `assert sys.version_info >= (3,
  $(MIN_PY_MINOR))` with the `Try: make up-wizard PYTHON=python3.$(MIN_PY_MINOR)` suffix.
  No typo, no version-number drift.
- `make test` is unaffected: dry-run confirms it still invokes `ruff check .` then
  `pytest` with the correct Python check prefix.
- `make up-wizard` is idempotent: the target body contains no `mkdir`, `touch`, `rm`, or
  state-mutating pre-step — it is a pure thin wrapper that sets one env-var and delegates
  to `python -m server.main`.
- Signal handling matches `make up`: both targets invoke `$(PYTHON) -m server.main`
  directly in the foreground with no trap, background wrapper, or additional process
  group manipulation; SIGINT propagates to the Python process normally.
- No env-var cross-pollution between `make up` and `make up-wizard`: Make spawns a
  fresh subshell per target recipe, so `ARXMCP_BOOTSTRAP_MODE=1` set in the wizard
  recipe never leaks into a subsequent `make up` invocation in the same session.
- The help description for `up-wizard` (Makefile:56-59) accurately describes the
  behavior (no_notebook_selected envelope, in-process promotion, no restart) — operator
  documentation is accurate, not aspirational.
- `make help` total output is 58 lines — well under the 120-line pagination threshold,
  no structural refactor needed.
- No CI surface touched; no `.github/workflows/` changes in diff — no CI safety axis
  to audit.

## Recommended rectification order

1. **IS1 (MEDIUM):** Align `.PHONY` stanza comment label "FIRST-TIME?" → "FIRST TIME?"
   at Makefile:6. Single-character change, zero runtime impact.
2. **IS2 (LOW):** Update or drop the "(onboarding-uplift-m2)" epoch tag at Makefile:40.
   Defer to next milestone touching the FIRST TIME? section.

## Rectification status (filled by Phase 4)

- IS1 | MEDIUM | fixed | Makefile:6: FIRST-TIME? → FIRST TIME? (drop hyphen to match make help section header)
- IS2 | LOW | deferred | orchestrator will record under deferred_findings in state.json
