# Critique — notebook-preamble-recovery-m1

**Critic:** infra-safety
**Generated:** 2026-05-27T00:00:00Z
**Commit range:** aec46ce7d1b5a93e00170d61ee58c1f966dec48e..be1a3ffb12c78a4e9585cd692043775de19b41ea
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one MEDIUM finding (operator warning hidden from `make help`)
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 1 LOW
- All container, compose, and CI axes N/A; Makefile axis walked in full
- Target is structurally correct: tab-indented, no sudo, idempotent, exit codes propagate
- PHONY declaration clean — no duplicates, new target correctly appended
- tools/__init__.py and tools/recover_preambles.py both verified present

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — Operator WARNING on chunk_id rotation hidden from `make help`

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** Makefile:159-163
- **What:** The `OPERATOR WARNING` block (lines 159-163) lives inside the recipe's `@#`-prefixed comment section. Make suppresses `@#` lines at runtime — they are silent. The warning is visible only to someone who opens the Makefile in an editor before running the target; it does not surface via `make help`.
- **Why it matters:** The warning documents a material consequence for the operator: the next `make re-embed-all` will re-embed every back-filled paper (2-4 hours additional CPU), because preamble bytes now flow into the chunk_id hash. An operator who learns about the target from `make help` alone — the intended UX — has no visibility into this consequence before triggering a multi-hour downstream job.
- **Proposed fix:** Add a second `@echo` line to the `help` target summarizing the chunk_id-rotation consequence. For example:

  ```makefile
  @echo "  make ingest-recover-preambles  Back-fill raw .tex + preamble.json for ar5iv-only papers (notebook-preamble-recovery-m1)"
  @echo "                                   NOTE: triggers chunk_id rotation; follow with make re-embed-all (2-4h CPU)"
  ```

  This is ≤ 2 LOC and surfaces the warning at the point of discovery.
- **Regression guard:** Run `make help 2>&1 | grep ingest-recover-preambles` and verify both lines appear.

---

### IS2 — Help line column alignment breaks at `ingest-recover-preambles`

- **Severity:** LOW
- **Source:** infra-safety
- **File:** Makefile:18
- **What:** Every sibling target's description starts at column 19 (`ingest`, `delta`, `re-embed`, `watchdog`, `cutover`). The new target's description starts at column 33 (two spaces after the 29-char target name), visually misaligned. Note that `re-embed-all` (pre-existing, col 20) is a mild pre-existing precedent for overflow, but `ingest-recover-preambles` breaks alignment by 14 columns.
- **Why it matters:** Style only — `make help` output is harder to scan when description columns are ragged. No behavioral impact.
- **Proposed fix:** Accept the overflow and align the description to a wider column (e.g. col 36 for all targets), or wrap with a continuation line as shown in IS1's proposed fix, which separates target name from description on two lines.
- **Regression guard:** None required (LOW; style only).

## What was done well

- **Tab discipline is perfect.** Every recipe line in the new target starts with a hard tab (verified via binary inspection). No spaces-masquerading-as-tabs.
- **`.PHONY` declaration is correct.** `ingest-recover-preambles` was appended cleanly; no comma drift, no duplicates (16 unique targets, 16 declared).
- **No `sudo`.** The entire Makefile contains zero `sudo` calls.
- **Exit-code propagation is correct.** The recipe has two lines: the Python version assertion (non-zero exit kills Make) and `$(PYTHON) -m tools.recover_preambles $(ARGS)` with no `|| true`, no semicolon chaining. Make's default `set -e`-equivalent applies.
- **Idempotent by design.** The Makefile recipe adds no non-idempotent step beyond delegating to the Python driver, which is itself idempotent (SHA256-guarded short-circuit per module docstring line 15).
- **No destructive defaults.** The recipe writes only to `var/arxmcp/corpus/raw/` and `var/arxmcp/corpus/preamble/` — operator-side data dirs that are gitignored. No corpus-version.json is touched, consistent with the project convention that `make cutover` owns that step.
- **ARGS-spaces-footgun warning is present** (Makefile:165-167). The comment follows the exact wording pattern established in sibling targets (`ingest`, `re-embed`, `re-embed-all`, `watchdog`, `cutover`), satisfying the forward-contract for future path-bearing flags.
- **Python version assertion is correct.** Uses the same `$(MIN_PY_MINOR)` macro and same multi-line continuation form as every other target in the Makefile — no copy-paste deviation.
- **`tools/__init__.py` is present**, so `-m tools.recover_preambles` will resolve correctly as a module invocation. No import-path foot-gun.
- **`make test` target is unaffected.** The diff does not touch the `test` target; `make -n test` still invokes ruff + pytest correctly.

## Recommended rectification order

1. **IS1 (MEDIUM)** — Add the chunk_id-rotation consequence as a second `@echo` line under `ingest-recover-preambles` in the `help` target. Cheap (≤ 2 LOC), high operator-safety value.
2. **IS2 (LOW)** — Optionally fix column alignment when IS1's second echo line is added (the two-line form naturally resolves the alignment issue).

## Deferred findings

- IS2 (LOW) — help column alignment; defer if IS1's two-line echo form is adopted.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
