# Critique — notebook-cutover-m1

**Critic:** infra-safety
**Generated:** 2026-05-28T00:00:00Z
**Commit range:** c16aac7ad4b962e5af96446bb2a4fbb71bc1cb62..9625512cf2897484c8474e9aead0ed644edb173c
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one MEDIUM finding (missing `make help` entry); all other axes clean
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 0 LOW
- The new `notebook-cutover` target follows the established Makefile pattern faithfully (MIN_PY guard, ARGS whitespace warning, .PHONY registration, no sudo, no destructive defaults without guards)
- The only gap: `notebook-cutover` is absent from the `help` target, leaving its default all-notebooks scope and operator warnings invisible without reading `@#` recipe comments
- Exit codes propagate correctly; idempotency is well-guarded by the tool's downgrade gate and `discover_promotable()` no-op when staging is absent
- `make test` target unaffected; ruff + pytest invocation unchanged

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — notebook-cutover absent from `make help`; default all-notebooks scope invisible

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** Makefile:7-30 (help target)
- **What:** The `help` target lists every other Makefile target by name (`bootstrap`, `test`, `eval`, `up`, `ingest`, `delta`, `re-embed`, `re-embed-all`, `ingest-recover-preambles`, `watchdog`, `cutover`, `daily-report`, `parser-failures-report`, `sbom`, `refresh-arxiv-ca`) but has no entry for `notebook-cutover`. The operator warnings — that `make notebook-cutover` with no ARGS defaults to promoting ALL notebooks with a `lancedb-staging` dir, that the server must be restarted afterward, and that the pre-promotion comparison window is destroyed — live exclusively in `@#` recipe comments (Makefile:239-255) and are therefore silent at runtime.
- **Why it matters:** An operator who runs `make help` to survey available targets before acting will not see `notebook-cutover` at all. If they discover the target via grep or prior knowledge, they may invoke it without ARGS expecting single-notebook behavior (the safe default for `cutover`), not knowing the `notebook-cutover` default sweeps all promotable notebooks simultaneously. The silent operator warnings in `@#` comments follow the exact anti-pattern documented in the project memory entry for `notebook-preamble-recovery-m1` (`2026-05-27` entry): a material consequence buried in silent comments but absent from `make help` output.
- **Proposed fix:** Add one or two `@echo` lines to the `help` target between the `cutover` and `daily-report` entries. Example (≤4 LOC):
  ```
  @echo "  make notebook-cutover           Promote notebook staging->active for all notebooks with staging"
  @echo "                                   (default: ALL promotable; use ARGS='--notebook=<slug>' to scope)"
  ```
  The "restart the server after cutover" warning should also appear here, mirroring how `ingest-recover-preambles` has an explicit `NOTE:` line in the help echo block (Makefile:18-19).
- **Regression guard:** After adding the echo lines, run `make help 2>&1 | grep notebook-cutover` to confirm the entry appears and that the line length is readable (≤100 chars per line). No test exists for `make help` output format; visual inspection suffices.

## What was done well

- `.PHONY` declaration at Makefile:1 is updated to include `notebook-cutover` — the target correctly participates in Make's phony target protocol and will always re-run even if a directory named `notebook-cutover` somehow existed.
- The MIN_PY_MINOR guard (Makefile:256-258) is character-for-character consistent with every sibling target (`cutover`, `re-embed-all`, `watchdog`, `re-embed`, `ingest`, `up`, `eval`, `test`) — same `@$(PYTHON) -c "import sys; assert ..."` form, same f-string, same `Try: make <target> PYTHON=python3.$(MIN_PY_MINOR)` hint. No drift introduced.
- The ARGS whitespace footgun warning (Makefile:254-255) is present and accurate. `--notebook=<slug>` carries no space risk in the slug itself (validated by `validate_slug` which enforces a no-whitespace regex), but `ARGS="--rollback --notebook=<slug>"` involves two flags and the warning correctly guards the multi-token ARGS case.
- Exit codes propagate correctly: the version guard (line 256) uses `@` prefix only to suppress echo, not to suppress errors — a Python assert failure exits non-zero and Make stops. The driver invocation (Makefile:259) has no `-` prefix and no `|| true`, so a non-zero return from `tools.notebook_cutover` stops Make with a failure.
- The new target is idempotent: re-running `make notebook-cutover` after a successful promotion is a no-op (`discover_promotable()` finds no `lancedb-staging` dirs, prints "no promotable notebooks", returns 0).
- No `sudo`, no hardcoded absolute paths, no destructive default that operates without pre-swap validation gates — the tool enforces staging existence, corpus-version.json completeness, and a downgrade guard before any `os.rename`.
- The recipe comments (Makefile:239-255) are detailed and correct: MEASURE-THEN-PROMOTE framing, rollback syntax, downgrade-override flag, and the server-restart requirement are all documented.
- The `make test` target is untouched (Makefile:57-62): `ruff check . && python -m pytest` still invokes correctly; `make -n test` confirms the full test chain.

## Recommended rectification order

1. **IS1 (MEDIUM):** Add `notebook-cutover` entry to the `help` target (≤ 4 LOC). Include the default all-notebooks scope note and the server-restart requirement. This is the only open finding.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
